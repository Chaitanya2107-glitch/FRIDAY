"""Thin native adapters; no clipboard reads or hotkeys occur at import time."""
import ctypes
from ctypes import wintypes
import os
from pathlib import Path

DEFAULT_BLOCKLIST = ['keepass', 'keepassxc', 'bitwarden', '1password', 'lastpass',
                     'dashlane', 'enpass', 'nordpass', 'roboform', 'keeper', 'protonpass']


class WindowsClipboard:
    def __init__(self):
        from services.automation import clipboard
        self.native = clipboard

    def sequence_number(self):
        return self.native.sequence_number()

    def read(self, blocklist):
        return self.native.read_snapshot(blocklist)

    def write(self, text, *, expected_sequence=None):
        return self.native.set_text(text, private=True, expected_sequence=expected_sequence)


def local_path(text: str) -> Path | None:
    """Reject remote paths before stat, including mapped network drive letters."""
    text = text.strip().strip('"')
    if len(text) > 1024 or text.startswith(('\\\\', '//')) or '\0' in text:
        return None
    try:
        path = Path(text)
        if not path.is_absolute():
            return None
        if os.name == 'nt':
            kernel = ctypes.WinDLL('kernel32', use_last_error=True)
            kernel.GetDriveTypeW.argtypes = [wintypes.LPCWSTR]
            kernel.GetDriveTypeW.restype = wintypes.UINT
            if kernel.GetDriveTypeW(path.anchor) not in {2, 3, 5, 6}:
                return None
            # Junctions/symlinks can redirect a local drive to an SMB server.
            for part in reversed((path, *path.parents)):
                if part.is_symlink() or part.is_junction():
                    return None
        return path if path.exists() else None
    except (OSError, ValueError):
        return None


class Hotkey:
    """Register and pump on the same managed thread; no keyboard hook."""
    def __init__(self):
        self.user = ctypes.WinDLL('user32', use_last_error=True)
        self.registered = False

    def register(self, spec):
        self.close()
        parts = [part.strip() for part in str(spec).lower().split('+')]
        flags = {'alt': 1, 'ctrl': 2, 'shift': 4, 'win': 8}
        keys = {'space': 0x20, 'insert': 0x2d, 'home': 0x24, 'end': 0x23,
                'pageup': 0x21, 'pagedown': 0x22}
        keys.update({f'f{i}': 0x6f + i for i in range(1, 25)})
        key = parts[-1]
        vk = ord(key.upper()) if len(key) == 1 and key.isascii() and key.isalnum() else keys.get(key)
        if (len(parts) < 2 or len(set(parts)) != len(parts)
                or any(part not in flags for part in parts[:-1])
                or vk is None):
            return False
        self.registered = bool(self.user.RegisterHotKey(None, 0x4656,
                               sum(flags[part] for part in parts[:-1]) | 0x4000, vk))
        return self.registered

    def pressed(self):
        message = wintypes.MSG()
        found = False
        while self.user.PeekMessageW(ctypes.byref(message), None, 0x0312, 0x0312, 1):
            found |= message.wParam == 0x4656
        return found

    def close(self):
        if self.registered:
            self.user.UnregisterHotKey(None, 0x4656)
            self.registered = False


class Activity:
    def idle(self):
        from services.activity.log import IDLE_SECONDS, idle_seconds
        return idle_seconds() >= IDLE_SECONDS

    def fullscreen(self):
        from services.proactive.watcher import fullscreen_or_gaming
        return fullscreen_or_gaming()

    def scene(self):
        from services.automation.modes import active
        return (active() or {}).get('name', '').lower()
