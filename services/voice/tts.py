"""
services/voice/tts.py

Text-to-Speech service for F.R.I.D.A.Y.

  - Online  → edge-tts (Microsoft neural voices, free, no API key). Audio is played
              while it streams in, so FRIDAY starts talking as soon as the first
              audio arrives. Replies written in Hindi use a Hindi voice.
  - Offline → Piper (a local neural voice, PIPER_VOICE, played sentence by sentence),
              used when there's no internet (services/network/status.py) or edge-tts
              can't connect. The voice file is downloaded once at startup while online.
              pyttsx3 (Windows' built-in voices) is the last resort: Hindi text, or
              Piper missing.

stop() cuts speech off immediately — used when the user presses the voice hotkey
while FRIDAY is still talking.

Short confirmations ("Muted.", "Volume set to 40%.") are kept after they're first
spoken, and the most common ones are pre-loaded at startup, so they play
instantly. They're also saved as MP3s in memory/tts_cache/ so they stay instant
after a restart (only confirmations, never private replies; cleared together
with chat memory).

All playback happens on one dedicated audio thread: the API keeps serving
requests while FRIDAY talks, and overlapping speech plays one at a time.

Speed: "talk faster" / "slower" / "normal speed" (services/voice/voice_commands.py) sets
`rate`, a percentage saved in memory/voice.json, used by all three voices.

Voices are set with EDGE_TTS_VOICE and EDGE_TTS_HINDI_VOICE in .env.
Browse voices: edge-tts --list-voices
"""

import asyncio
import hashlib
import json
import os
import queue
import re
from collections import OrderedDict
from concurrent.futures import ThreadPoolExecutor
from typing import Iterable, Iterator

import numpy as np

from core.config import config
from core.errors import FridayError
from core.logger import logger
from services.network.status import network

CONNECT_TIMEOUT_SECONDS = 3  # after this, fall back to the offline voice
PIPER_DIR = config.MEMORY_DIR / "piper"
PIPER_URL = "https://huggingface.co/rhasspy/piper-voices/resolve/main/{lang}/{locale}/{name}/{quality}/{voice}{ext}"
CACHE_ITEMS = 100
CACHE_FILES = 300  # saved confirmations kept on disk
CACHE_DIR = config.MEMORY_DIR / "tts_cache"
SPEED_PATH = config.MEMORY_DIR / "voice.json"  # {"rate": 15} = 15% faster
MIN_RATE, MAX_RATE = -50, 100
WINDOWS_VOICE_RATE = 175  # pyttsx3 words per minute at normal speed (its default is slow)
DEVANAGARI = re.compile(r"[ऀ-ॿ]")
# Spoken often and always word-for-word the same, so synthesised once at startup.
# If a message's wording changes in code, it's simply synthesised on first use instead.
PREWARM_PHRASES = (
    "Muted.",
    "Unmuted.",
    "Okay, cancelled. Nothing was changed.",
    "Screenshot saved to your Screenshots folder.",
    "Clipboard history cleared.",
    "Your clipboard history is empty.",
    "You don't have any reminders.",
)


class TTSError(FridayError):
    """Raised when text-to-speech fails for any reason."""
    pass


MARKDOWN_LINK = re.compile(r"\[([^\]]+)\]\([^)]*\)")
MARKDOWN_SYMBOLS = re.compile(r"[*_`#~>|]+")


def spoken_text(text: str) -> str:
    """Drop markdown so the voice doesn't read out asterisks, hashes or link URLs."""
    text = MARKDOWN_LINK.sub(r"\1", text or "")
    text = re.sub(r"^\s*[-+]\s+", "", text, flags=re.MULTILINE)  # bullet markers
    text = MARKDOWN_SYMBOLS.sub(" ", text)
    return re.sub(r"[ \t]+", " ", text).strip()


def _decode_mp3(chunks: Iterable[bytes]) -> Iterator[tuple[np.ndarray, int]]:
    """Decode MP3 data as it arrives. Yields (mono float32 samples in -1..1, sample rate)."""
    import av

    codec = av.CodecContext.create("mp3", "r")
    # The decoder outputs 16-bit integer samples; the speaker stream needs floats in -1..1.
    to_float = av.AudioResampler(format="flt", layout="mono")

    def frames(packet):
        for frame in codec.decode(packet):
            for converted in to_float.resample(frame):
                yield converted.to_ndarray().reshape(-1), converted.sample_rate

    for data in chunks:
        for packet in codec.parse(data):
            yield from frames(packet)
    for packet in codec.parse(None):  # flush the parser...
        yield from frames(packet)
    yield from frames(None)  # ...then the decoder


class TextToSpeech:
    """
    Speaks text out loud using edge-tts (online) or pyttsx3 (offline).
    """

    def __init__(self):
        self.edge_voice = config.EDGE_TTS_VOICE
        self.hindi_voice = config.EDGE_TTS_HINDI_VOICE
        self._offline_engine = None  # pyttsx3 loaded lazily — only if needed
        self._piper = None           # Piper voice, loaded on first offline use
        self._cache: OrderedDict[str, bytes] = OrderedDict()  # text → MP3 audio
        self.cache_dir = CACHE_DIR
        # Bumped by stop(). Speech started (or queued) under an older value ends.
        self._generation = 0
        self._saying: list[str] = []  # text of speak() calls in progress (including queued ones)
        self.rate = self._load_rate()  # % faster (negative = slower)
        # One thread for all playback: speech never overlaps, and pyttsx3's COM
        # objects are always used from the thread that created them.
        self._audio_thread = ThreadPoolExecutor(max_workers=1, thread_name_prefix="friday-audio")
        logger.info(f"TextToSpeech initialised — voice: {self.edge_voice} | Hindi: {self.hindi_voice}")

    def stop(self) -> None:
        """Cut off whatever FRIDAY is saying, and drop any speech queued behind it."""
        self._generation += 1

    @property
    def is_speaking(self) -> bool:
        return bool(self._saying)

    @property
    def saying(self) -> list[str]:
        """What FRIDAY is saying right now — so its own words can't count as "Hey Friday"."""
        return list(self._saying)

    @property
    def generation(self) -> int:
        """Changes on every stop(): compare before and after to tell if the user cut FRIDAY off."""
        return self._generation

    @staticmethod
    def _load_rate() -> int:
        try:
            return int(json.loads(SPEED_PATH.read_text(encoding="utf-8"))["rate"])
        except (OSError, ValueError, KeyError, TypeError):
            return 0

    def set_rate(self, percent: int) -> int:
        """Change how fast FRIDAY talks (kept after a restart). Returns the rate actually set."""
        self.rate = max(MIN_RATE, min(MAX_RATE, int(percent)))
        try:
            SPEED_PATH.write_text(json.dumps({"rate": self.rate}), encoding="utf-8")
        except OSError as e:
            logger.warning(f"Couldn't save the speech speed: {e}")
        return self.rate

    def voice_for(self, text: str) -> str:
        return self.hindi_voice if DEVANAGARI.search(text) else self.edge_voice

    async def _on_audio_thread(self, fn, *args):
        return await asyncio.get_running_loop().run_in_executor(self._audio_thread, fn, *args)

    def _edge_stream(self, text: str):
        import edge_tts

        speed = {"rate": f"{self.rate:+d}%"} if self.rate else {}
        return edge_tts.Communicate(
            text, self.voice_for(text), connect_timeout=CONNECT_TIMEOUT_SECONDS, **speed
        ).stream()

    def _play(self, chunks: Iterable[bytes], generation: int) -> None:
        """Play MP3 audio as it's decoded from `chunks`, until stop() is called. Runs on the audio thread."""
        if generation != self._generation:
            return  # stopped while this speech was still queued

        import pyaudio

        audio = pyaudio.PyAudio()
        stream = None
        try:
            for samples, rate in _decode_mp3(chunks):
                if generation != self._generation:
                    break
                if stream is None:
                    stream = audio.open(format=pyaudio.paFloat32, channels=1, rate=rate, output=True)
                stream.write(samples.tobytes())
        finally:
            if stream is not None:
                if generation == self._generation:
                    stream.stop_stream()  # finished normally: let the last buffered audio play
                stream.close()  # after stop(), closing discards what's still buffered
            audio.terminate()

    def _key(self, text: str) -> str:
        return f"{self.rate}|{text}" if self.rate else text  # another speed is other audio

    def _remember(self, text: str, audio: bytes, save: bool = True) -> None:
        key = self._key(text)
        self._cache[key] = audio
        self._cache.move_to_end(key)
        while len(self._cache) > CACHE_ITEMS:
            self._cache.popitem(last=False)
        if save:
            self._save_to_disk(text, audio)

    def _cache_file(self, text: str):
        # The voice is part of the name, so changing voices never replays the old one
        speed = f"\n{self.rate}" if self.rate else ""
        name = hashlib.sha256(f"{self.voice_for(text)}\n{text}{speed}".encode()).hexdigest()
        return self.cache_dir / f"{name}.mp3"

    def _save_to_disk(self, text: str, audio: bytes) -> None:
        try:
            self.cache_dir.mkdir(parents=True, exist_ok=True)
            self._cache_file(text).write_bytes(audio)
            files = sorted(self.cache_dir.glob("*.mp3"), key=lambda f: f.stat().st_mtime)
            for old in files[:-CACHE_FILES]:
                old.unlink(missing_ok=True)
        except OSError as e:
            logger.warning(f"Couldn't save spoken phrase to the cache: {e}")

    def _cached(self, text: str) -> bytes | None:
        """Audio for text from memory, or from disk (loaded into memory), else None."""
        audio = self._cache.get(self._key(text))
        if audio is not None:
            self._cache.move_to_end(self._key(text))
            return audio
        path = self._cache_file(text)
        try:
            audio = path.read_bytes()
            os.utime(path)  # recently used: pruned last
        except OSError:
            return None
        self._remember(text, audio, save=False)
        return audio

    def clear_cache(self) -> None:
        """Forget every saved phrase, in memory and on disk."""
        self._cache.clear()
        for path in self.cache_dir.glob("*.mp3"):
            try:
                path.unlink()
            except OSError as e:
                logger.warning(f"Couldn't delete cached speech {path.name}: {e}")

    async def _speak_online(self, text: str, remember: bool, generation: int) -> None:
        """Stream edge-tts audio straight into playback."""
        chunks: queue.Queue[bytes | None] = queue.Queue()
        playback = asyncio.get_running_loop().run_in_executor(
            self._audio_thread, self._play, iter(chunks.get, None), generation
        )
        received = bytearray()
        error = None
        try:
            async for message in self._edge_stream(text):
                if generation != self._generation:
                    break  # stopped — no point downloading the rest
                if message["type"] == "audio":
                    received += message["data"]
                    chunks.put(message["data"])
        except Exception as e:
            error = e
        finally:
            chunks.put(None)  # always let playback finish

        try:
            await playback
        except Exception as e:
            raise TTSError(f"Audio playback failed: {e}")

        if error is not None:
            if not received:
                raise TTSError(f"edge-tts failed: {error}")
            # Some of it was already spoken — repeating it in the offline voice would be worse.
            logger.warning(f"edge-tts stopped part-way through speaking: {error}")
        elif remember and received and generation == self._generation:
            self._remember(text, bytes(received))

    def _get_offline_engine(self):
        """
        Load pyttsx3 once and reuse.
        Loaded lazily on first offline use.
        """
        if self._offline_engine is None:
            try:
                import comtypes
                import pyttsx3

                comtypes.CoInitialize()  # pyttsx3 uses COM, which each thread must initialise
                self._offline_engine = pyttsx3.init()

                # Try Microsoft Zira (female) if available
                voices = self._offline_engine.getProperty("voices")
                for voice in voices:
                    if "zira" in voice.name.lower():
                        self._offline_engine.setProperty("voice", voice.id)
                        break

                logger.info("pyttsx3 offline TTS engine loaded")
            except Exception as e:
                raise TTSError(f"Failed to load offline TTS engine: {str(e)}")

        return self._offline_engine

    def piper_voice_path(self):
        return PIPER_DIR / f"{config.PIPER_VOICE}.onnx"

    async def ensure_piper_voice(self) -> None:
        """Download the Piper voice (model + its config) if it isn't here yet. Needs the internet, so done at startup."""
        model = self.piper_voice_path()
        if model.exists() and model.with_suffix(".onnx.json").exists():
            return
        import httpx

        lang_locale, name, quality = config.PIPER_VOICE.split("-", 2)  # "en_US", "hfc_female", "medium"
        PIPER_DIR.mkdir(parents=True, exist_ok=True)
        try:
            async with httpx.AsyncClient(follow_redirects=True, timeout=120) as client:
                for ext in (".onnx.json", ".onnx"):  # the model last: its presence means "done"
                    url = PIPER_URL.format(lang=lang_locale.split("_")[0], locale=lang_locale, name=name,
                                           quality=quality, voice=config.PIPER_VOICE, ext=ext)
                    response = await client.get(url)
                    response.raise_for_status()
                    part = PIPER_DIR / f"{config.PIPER_VOICE}{ext}.part"
                    part.write_bytes(response.content)
                    part.replace(PIPER_DIR / f"{config.PIPER_VOICE}{ext}")
            logger.info(f"Downloaded the offline voice {config.PIPER_VOICE}")
        except (httpx.HTTPError, OSError, ValueError) as e:
            logger.warning(f"Couldn't download the offline voice {config.PIPER_VOICE}: {e}")

    def _get_piper(self):
        if self._piper is None:
            model = self.piper_voice_path()
            if not model.exists():
                raise TTSError(f"The offline voice {config.PIPER_VOICE} isn't downloaded yet")
            try:
                from piper import PiperVoice

                self._piper = PiperVoice.load(str(model))
                logger.info(f"Piper offline voice loaded: {config.PIPER_VOICE}")
            except Exception as e:
                raise TTSError(f"Couldn't load the offline voice: {e}")
        return self._piper

    def _speak_piper(self, text: str, generation: int) -> None:
        """Speak with Piper, sentence by sentence, until stop(). Runs on the audio thread."""
        voice = self._get_piper()
        import pyaudio

        audio = pyaudio.PyAudio()
        stream = None
        try:
            speed = ()
            if self.rate:
                from piper import SynthesisConfig
                speed = (SynthesisConfig(length_scale=1 / (1 + self.rate / 100)),)  # shorter = faster
            for chunk in voice.synthesize(text, *speed):  # one chunk per sentence: the first plays while the rest is made
                if generation != self._generation:
                    break
                if stream is None:
                    stream = audio.open(format=pyaudio.paFloat32, channels=1, rate=chunk.sample_rate, output=True)
                stream.write(np.asarray(chunk.audio_float_array, dtype=np.float32).tobytes())
        except TTSError:
            raise
        except Exception as e:
            raise TTSError(f"Piper failed: {e}")
        finally:
            if stream is not None:
                if generation == self._generation:
                    stream.stop_stream()
                stream.close()
            audio.terminate()

    def _speak_offline(self, text: str, generation: int):
        """
        Speak with no internet: Piper, or pyttsx3 for Hindi text / if Piper can't. Runs on the audio thread.
        """
        if generation != self._generation:
            return
        if not DEVANAGARI.search(text):  # the Piper voice is English-only
            try:
                self._speak_piper(text, generation)
                return
            except TTSError as e:
                logger.warning(f"{e} — using the Windows voice")
        try:
            engine = self._get_offline_engine()
            logger.info("pyttsx3 offline TTS speaking")
            engine.setProperty("rate", int(WINDOWS_VOICE_RATE * (1 + self.rate / 100)))
            engine.say(text)
            engine.runAndWait()
        except TTSError:
            raise
        except Exception as e:
            raise TTSError(f"Offline TTS failed: {str(e)}")

    async def speak(self, text: str, cache: bool = False) -> None:
        from services.mind.cognition import cognition

        generation = self._generation
        # Speech can contain clipboard/typed text. Record its lifecycle, not its
        # payload. The owning reply/notification already records permitted text.
        with cognition.operation("speech", "voice", "Spoken output") as event:
            await self._speak(text, cache)
            if self._generation != generation:
                event.finish("cancelled")

    async def _speak(self, text: str, cache: bool = False) -> None:
        """
        Speak text out loud. cache=True keeps the audio so the same text plays
        instantly next time — use it only for short, non-private confirmations.
        """
        text = spoken_text(text)
        if not text:
            logger.warning("TTS speak() called with empty text — skipping")
            return

        generation = self._generation
        self._saying.append(text)
        try:
            cached = self._cached(text)
            if cached is not None:
                await self._on_audio_thread(self._play, [cached], generation)
                return

            if network.online:  # known offline: don't wait CONNECT_TIMEOUT_SECONDS for edge-tts to fail
                try:
                    await self._speak_online(text, remember=cache, generation=generation)
                    return
                except TTSError as e:
                    logger.warning(f"edge-tts unavailable, using the offline voice: {e}")
            await self._on_audio_thread(self._speak_offline, text, generation)
        finally:
            self._saying.remove(text)

    async def prewarm(self) -> None:
        """Synthesise PREWARM_PHRASES in the background at startup so they play instantly; fetch the offline voice."""
        await self.ensure_piper_voice()
        for text in PREWARM_PHRASES:
            if self._cached(text) is not None:
                continue
            audio = bytearray()
            try:
                async for message in self._edge_stream(text):
                    if message["type"] == "audio":
                        audio += message["data"]
            except Exception as e:
                logger.info(f"Couldn't pre-load common phrases ({e}) — they'll be synthesised when first used")
                return
            if audio:
                self._remember(text, bytes(audio))

# ── Singleton ─────────────────────────────────────────────────────────────────
tts = TextToSpeech()
