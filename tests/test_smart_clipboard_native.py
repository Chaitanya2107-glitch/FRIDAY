"""Native adapter tests replace every Win32 call with an in-memory stand-in."""
import ctypes
import os
from types import SimpleNamespace

import pytest

from services.automation import clipboard
from plugins.smart_clipboard.windows import Hotkey, local_path


class NativeClipboard:
    def __init__(self):
        self.formats, self.buffers, self.requested = {}, {}, []
        self.closed = 0
        self.next_handle = 100
        self.sequence = 7
        self.text_read = False

    def RegisterClipboardFormatW(self, name):
        return name

    def IsClipboardFormatAvailable(self, name):
        return name in self.formats

    def GetClipboardData(self, name):
        self.requested.append(name)
        if name == clipboard.CF_UNICODETEXT:
            self.text_read = True
        return self.formats[name]

    def put(self, name, value):
        handle = self.GlobalAlloc(0, len(value))
        ctypes.memmove(self.GlobalLock(handle), value, len(value))
        self.formats[name] = handle

    def GlobalAlloc(self, flags, size):
        self.next_handle += 1
        self.buffers[self.next_handle] = ctypes.create_string_buffer(size)
        return self.next_handle

    def GlobalSize(self, handle):
        return ctypes.sizeof(self.buffers[handle]) if handle in self.buffers else 0

    def GlobalLock(self, handle):
        return ctypes.addressof(self.buffers[handle]) if handle in self.buffers else 0

    def GlobalUnlock(self, handle):
        return True

    def GlobalFree(self, handle):
        self.buffers.pop(handle, None)

    def OpenClipboard(self, owner):
        return True

    def CloseClipboard(self):
        self.closed += 1
        return True

    def EmptyClipboard(self):
        self.formats.clear()
        return True

    def SetClipboardData(self, name, handle):
        self.formats[name] = handle
        self.sequence += 1
        return handle

    def GetClipboardSequenceNumber(self):
        return self.sequence

    def CreateWindowExW(self, *args):
        return 9

    def DestroyWindow(self, owner):
        return True


@pytest.fixture
def native(monkeypatch):
    fake = NativeClipboard()
    monkeypatch.setattr(clipboard, 'user32', fake)
    monkeypatch.setattr(clipboard, 'kernel32', fake)
    monkeypatch.setattr(clipboard, '_owner_identity', lambda: (123456789, 'notepad'))
    fake.put(clipboard.CF_UNICODETEXT, 'never log this text\0'.encode('utf-16-le'))
    return fake


@pytest.mark.parametrize('flag,value', [
    ('ExcludeClipboardContentFromMonitorProcessing', b'\0'),
    ('Clipboard Viewer Ignore', b'\0'),
    ('CanIncludeInClipboardHistory', (0).to_bytes(4, 'little')),
    ('CanUploadToCloudClipboard', (0).to_bytes(4, 'little')),
    ('CanUploadToCloudClipboard', b'\x01'),
    ('CanIncludeInClipboardHistory', (2).to_bytes(4, 'little')),
])
def test_flags_checked_before_any_text(native, flag, value):
    native.put(flag, value)
    snapshot = clipboard.read_snapshot()
    assert snapshot.sensitive and snapshot.text is None
    assert not native.text_read and native.closed == 1


def test_allow_flags_snapshot_is_atomic_and_repr_hides_text(native):
    native.put('CanIncludeInClipboardHistory', (1).to_bytes(4, 'little'))
    native.put('CanUploadToCloudClipboard', (1).to_bytes(4, 'little'))
    snapshot = clipboard.read_snapshot()
    assert snapshot.text == 'never log this text'
    assert not snapshot.sensitive and native.closed == 1
    assert 'never log this text' not in repr(snapshot)
    assert native.requested.index('CanUploadToCloudClipboard') < native.requested.index(clipboard.CF_UNICODETEXT)


def test_blocklist_and_unreadable_owner_skip_before_text(native, monkeypatch):
    monkeypatch.setattr(clipboard, '_owner_identity', lambda: (123456789, 'bitwarden'))
    assert clipboard.read_snapshot(['Bitwarden.exe']).sensitive
    assert not native.text_read
    monkeypatch.setattr(clipboard, '_owner_identity', lambda: (123456789, None))
    assert clipboard.read_snapshot().sensitive
    assert not native.text_read


def test_friday_own_marker_and_pid_skip_text(native, monkeypatch):
    native.put(clipboard.OWN_FORMAT, b'\1\0\0\0')
    assert clipboard.read_snapshot().own and not native.text_read
    native.formats.pop(clipboard.OWN_FORMAT)
    monkeypatch.setattr(clipboard, '_owner_identity', lambda: (os.getpid(), 'python'))
    assert clipboard.read_snapshot().own and not native.text_read


def test_native_private_write_marks_history_cloud_and_own(native):
    written_sequence = clipboard.set_text('result', private=True)
    assert written_sequence == native.sequence
    assert clipboard.OWN_FORMAT in native.formats
    for flag in ('CanIncludeInClipboardHistory', 'CanUploadToCloudClipboard'):
        pointer = native.GlobalLock(native.formats[flag])
        assert ctypes.c_uint32.from_address(pointer).value == 0
    assert clipboard.EXCLUDE_FORMATS[0] in native.formats
    assert clipboard.read_snapshot().own
    assert not native.text_read


def test_write_preserves_a_newer_clipboard_copy(native):
    with pytest.raises(clipboard.ClipboardError):
        clipboard.set_text('result', private=True, expected_sequence=native.sequence - 1)
    assert clipboard.OWN_FORMAT not in native.formats
    assert clipboard.CF_UNICODETEXT in native.formats


def test_existing_private_helper_checks_cloud_flag(native):
    native.put('CanUploadToCloudClipboard', b'\0\0\0\0')
    assert clipboard.is_private()
    assert not native.text_read


def test_bounded_text_read_rejects_nontext_and_oversize(native):
    native.formats.pop(clipboard.CF_UNICODETEXT)
    assert clipboard.read_snapshot().text is None


def test_utf16_terminator_is_aligned_and_allocator_padding_is_not_decoded(native):
    native.put(clipboard.CF_UNICODETEXT, 'aĀx\0'.encode('utf-16-le') + b'\x00\xd8')
    assert clipboard.read_snapshot().text == 'aĀx'
    native.put(clipboard.CF_UNICODETEXT, 'unterminated'.encode('utf-16-le'))
    assert clipboard.read_snapshot().text is None
    native.put(clipboard.CF_UNICODETEXT, b'x' * 131076)
    assert clipboard.read_snapshot().text is None


def test_network_paths_rejected_before_filesystem_probe(monkeypatch):
    from pathlib import Path
    monkeypatch.setattr(Path, 'exists', lambda p: pytest.fail('must not probe remote path'))
    assert local_path(r'\\server\share\file.txt') is None
    assert local_path('//server/share/file.txt') is None
    assert local_path('relative.txt') is None


def test_mapped_network_drive_rejected_before_stat(monkeypatch):
    from pathlib import Path
    def drive_type(root):
        return 4
    monkeypatch.setattr(ctypes, 'WinDLL', lambda *a, **kw: SimpleNamespace(GetDriveTypeW=drive_type))
    monkeypatch.setattr(Path, 'exists', lambda p: pytest.fail('must not stat mapped drive'))
    assert local_path(r'Z:\private\file.txt') is None


def test_unknown_copying_owner_never_falls_back_to_foreground(monkeypatch):
    user = SimpleNamespace(GetClipboardOwner=lambda: None,
                           GetForegroundWindow=lambda: pytest.fail('foreground is not the copying owner'))
    monkeypatch.setattr(clipboard, 'user32', user)
    assert clipboard._owner_identity() == (None, None)


def test_fake_native_hotkey_registration_modifiers_message_and_release():
    calls = []
    class User:
        def RegisterHotKey(self, owner, key, flags, vk):
            calls.append((key, flags, vk))
            return True
        def UnregisterHotKey(self, owner, key):
            calls.append(('close', key))
        def PeekMessageW(self, pointer, owner, low, high, flags):
            return False
    hotkey = Hotkey.__new__(Hotkey)
    hotkey.user, hotkey.registered = User(), False
    assert hotkey.register('Ctrl+Shift+Alt+V')
    assert calls[0] == (0x4656, 0x4007, ord('V'))
    assert not hotkey.pressed()
    hotkey.close()
    assert calls[-1] == ('close', 0x4656)
    assert not hotkey.register('Ctrl+Ctrl+V')
    assert not hotkey.register('NotAKey')
