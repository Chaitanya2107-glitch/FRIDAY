"""
interfaces/body/sounds.py

FRIDAY's body's little robot noises — made here (sine sweeps with a soft envelope), saved once as
WAV files and played without waiting. Quiet on purpose; the body's right-click menu turns them off.
  chirp: a happy rising double beep (jumps, laughs, stretches)
  boop:  a soft falling beep (waking up, landing)
  hum:   a low wobbly purr (a stroke on her head)
  alert: two bright beeps (Claude needs you, a reminder)
"""

import wave
from pathlib import Path

import numpy as np

RATE = 22050
VOLUME = 0.22


def _tone(f0: float, f1: float, seconds: float, vibrato: float = 0.0) -> np.ndarray:
    t = np.linspace(0, seconds, int(RATE * seconds), endpoint=False)
    freq = np.linspace(f0, f1, t.size) * (1 + vibrato * np.sin(2 * np.pi * 9 * t))
    phase = 2 * np.pi * np.cumsum(freq) / RATE
    envelope = np.minimum(1, t / 0.01) * np.minimum(1, (seconds - t) / 0.04)
    return np.sin(phase) * envelope


def _gap(seconds: float) -> np.ndarray:
    return np.zeros(int(RATE * seconds))


SOUNDS = {
    "chirp": lambda: np.concatenate([_tone(900, 1400, 0.07), _gap(0.03), _tone(1100, 1700, 0.09)]),
    "boop": lambda: _tone(700, 420, 0.12),
    "hum": lambda: _tone(210, 230, 0.7, vibrato=0.04) * 0.7,
    "alert": lambda: np.concatenate([_tone(1250, 1250, 0.08), _gap(0.06), _tone(1250, 1250, 0.08)]),
}


def ensure(folder: Path) -> dict[str, Path]:
    """The WAV file for each sound, made the first time."""
    folder.mkdir(parents=True, exist_ok=True)
    files = {}
    for name, make in SOUNDS.items():
        path = folder / f"{name}.wav"
        if not path.exists():
            samples = (make() * VOLUME * 32767).astype(np.int16)
            with wave.open(str(path), "wb") as w:
                w.setnchannels(1)
                w.setsampwidth(2)
                w.setframerate(RATE)
                w.writeframes(samples.tobytes())
        files[name] = path
    return files


def play(path: Path) -> None:
    """Play without waiting (a newer sound cuts an older one short — they're tiny)."""
    import winsound

    try:
        winsound.PlaySound(str(path), winsound.SND_FILENAME | winsound.SND_ASYNC | winsound.SND_NODEFAULT)
    except RuntimeError:
        pass
