"""Trusted offline extension point; callbacks and input remain inside this process."""
from dataclasses import dataclass
import math
import re
import threading
from typing import Callable


@dataclass(frozen=True)
class Action:
    name: str
    label: str
    run: Callable[[str], str | None]


@dataclass(frozen=True)
class Detector:
    name: str
    detect: Callable[[str], float]
    actions: tuple[Action, ...]
    preview: Callable[[str], str] = lambda text: 'Clipboard actions available.'


class Registry:
    """Service clipboard_actions: register(name, detect, actions, preview=...)."""
    def __init__(self):
        self._detectors = {}
        self._lock = threading.RLock()

    def register(self, name: str, detect: Callable, actions, preview=None):
        actions = tuple(actions)
        if (not re.fullmatch(r'[a-z][a-z0-9_]{0,39}', name) or not callable(detect)
                or not all(callable(getattr(a, 'run', None))
                           and isinstance(getattr(a, 'name', None), str)
                           and re.fullmatch(r'[a-z][a-z0-9_]{0,39}', a.name)
                           and isinstance(getattr(a, 'label', None), str)
                           and 0 < len(a.label) <= 40 for a in actions)
                or len({a.name for a in actions}) != len(actions)):
            raise ValueError('Invalid clipboard detector or action.')
        with self._lock:
            if name in self._detectors:
                raise ValueError('Clipboard detector already registered.')
            self._detectors[name] = Detector(name, detect, actions, preview or Detector.preview)
        return lambda: self.unregister(name)

    def unregister(self, name: str):
        with self._lock:
            self._detectors.pop(name, None)

    def classify(self, text: str):
        with self._lock:
            detectors = tuple(self._detectors.values())
        best, confidence = None, 0.0
        for detector in detectors:
            try:
                score = float(detector.detect(text))
                if math.isfinite(score) and 0 <= score <= 1 and score > confidence:
                    best, confidence = detector, score
            except Exception:
                pass  # Never expose an extension exception containing clipboard text.
        return best, confidence
