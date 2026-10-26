"""
services/voice/stt.py

Speech-to-text with NVIDIA Parakeet TDT 0.6B v2 (int8 ONNX, via onnx-asr) — the
same model family Handy uses. Whisper 'small' kept missing short phrases like
"Hey Friday"; Parakeet gets them, and on the CPU it takes ~0.2 s per command
(Whisper on the GPU took ~0.8 s). The model (~650 MB) downloads once from
Hugging Face on first load.

If Parakeet can't load, falls back to faster-whisper (WHISPER_MODEL in .env,
default: small) on the GPU or CPU.

The model is loaded and warmed up in the background when the API starts
(see preload), so the first voice command doesn't pay for it.
"""

import asyncio
import threading
from itertools import chain

import numpy as np

from core.config import config
from core.errors import FridayError
from core.logger import logger

SAMPLE_RATE = 16000
PARAKEET_MODEL = "nemo-parakeet-tdt-0.6b-v2"


class STTError(FridayError):
    """Raised when speech-to-text fails for any reason."""
    pass


def _load_parakeet():
    import onnx_asr
    model = onnx_asr.load_model(PARAKEET_MODEL, quantization="int8", providers=['CPUExecutionProvider'])
    return model.recognize


def _load_whisper(device: str, compute_type: str):
    from faster_whisper import WhisperModel
    model = WhisperModel(config.WHISPER_MODEL, device=device, compute_type=compute_type)

    def recognize(audio: np.ndarray) -> str:
        segments, _ = model.transcribe(audio, language="en", beam_size=5, vad_filter=True)
        return " ".join(segment.text.strip() for segment in segments)

    return recognize


def _whisper_attempts():
    import torch
    if torch.cuda.is_available():
        yield f'Whisper {config.WHISPER_MODEL}', 'CUDA', lambda: _load_whisper('cuda', 'float16')
    yield f'Whisper {config.WHISPER_MODEL}', 'CPU', lambda: _load_whisper('cpu', 'int8')


class SpeechToText:
    def __init__(self):
        self._recognize = None
        self._load_lock = threading.RLock()  # also held throughout inference

    def load(self) -> None:
        """Load (and warm up) the model once. Blocking — call from a worker thread."""
        with self._load_lock:
            if self._recognize is not None:
                return

            # Avoid importing torch/CUDA at all when CPU Parakeet succeeds.
            attempts = chain([('Parakeet', 'CPU', _load_parakeet)], _whisper_attempts())

            failures = []
            for name, device, load in attempts:
                try:
                    recognize = load()
                    # Warm-up, so the first real command doesn't pay the start-up cost.
                    recognize(np.zeros(SAMPLE_RATE, dtype=np.float32))
                except Exception as e:
                    logger.warning(f"Speech model {name} failed to load on {device}: {e}")
                    failures.append(f"{name} ({device}): {e}")
                    continue
                self._recognize = recognize
                logger.info(f"Speech model {name} ready on {device}")
                return

            raise STTError(f"Couldn't load a speech model — {'; '.join(failures)}")

    def transcribe(self, audio: np.ndarray, log: bool = True) -> str:
        """16 kHz mono float32 audio → text. Blocking — call from a worker thread.
        log=False keeps the text out of the log (wake-word listening hears everyone)."""
        with self._load_lock:
            self.load()
            try:
                # ponytail: whole clip in one pass; commands and short voice notes only.
                text = self._recognize(audio.astype(np.float32, copy=False)).strip()
            except Exception as e:
                raise STTError(f"Transcription failed: {e}")
        if log:
            logger.info(f"Transcribed: '{text}'")
        return text

# ── Singleton ─────────────────────────────────────────────────────────────────
stt = SpeechToText()


async def preload() -> None:
    """Load the model in the background at startup. If it fails, voice retries on first use."""
    try:
        await asyncio.to_thread(stt.load)
    except STTError as e:
        logger.warning(f"{e} — will retry when voice is first used")
