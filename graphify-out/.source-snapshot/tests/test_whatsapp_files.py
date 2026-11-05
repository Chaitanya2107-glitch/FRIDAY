import ctypes
import struct
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from services.automation import whatsapp_files
from services.automation.system_control import AutomationError


@pytest.fixture
def automation(monkeypatch):
    opened, copied, pressed = [], [], []
    monkeypatch.setattr(whatsapp_files.os, "startfile", opened.append)
    monkeypatch.setattr(whatsapp_files.whatsapp, "recipient", lambda name: (name.title(), "919876543210"))
    monkeypatch.setattr(whatsapp_files, "foreground_app", lambda: "whatsapp.root")
    monkeypatch.setattr(whatsapp_files, "_copy_file", copied.append)
    monkeypatch.setattr(whatsapp_files.keyboard, "press_keys", pressed.append)
    monkeypatch.setattr(whatsapp_files.time, "sleep", lambda seconds: None)
    clock = iter(range(100))
    monkeypatch.setattr(whatsapp_files.time, "monotonic", lambda: next(clock))
    return opened, copied, pressed


def test_prepares_file_for_review_without_sending(tmp_path, automation):
    attachment = tmp_path / "report.pdf"
    attachment.write_bytes(b"file")
    reply = whatsapp_files.prepare(attachment)
    opened, copied, pressed = automation
    assert opened == ["whatsapp://send?phone=919876543210"]
    assert copied == [attachment]
    assert pressed == ["ctrl+v"]
    assert reply == "Prepared report.pdf for Chaitu in WhatsApp. Review the attachment and press Send."


@pytest.mark.parametrize("focus, copied_count", [
    (["notepad"] * 20, 0),
    (["whatsapp.root", "notepad"], 0),
    (["whatsapp.root", "whatsapp.root", "notepad"], 1),
])
def test_does_not_paste_when_whatsapp_loses_focus(tmp_path, automation, monkeypatch, focus, copied_count):
    attachment = tmp_path / "file.txt"
    attachment.write_text("file")
    windows = iter(focus)
    monkeypatch.setattr(whatsapp_files, "foreground_app", lambda: next(windows))
    with pytest.raises(AutomationError, match="WhatsApp"):
        whatsapp_files.prepare(attachment)
    assert automation[2] == []
    assert len(automation[1]) == copied_count


def test_reports_missing_whatsapp(tmp_path, automation, monkeypatch):
    attachment = tmp_path / "file.txt"
    attachment.touch()
    monkeypatch.setattr(whatsapp_files.os, "startfile", Mock(side_effect=OSError("missing handler")))
    with pytest.raises(AutomationError, match="installed"):
        whatsapp_files.prepare(attachment)
    assert automation[1:] == ([], [])


def test_reports_clipboard_failure_without_pasting(tmp_path, automation, monkeypatch):
    attachment = tmp_path / "file.txt"
    attachment.touch()
    monkeypatch.setattr(whatsapp_files, "_copy_file", Mock(side_effect=whatsapp_files.clipboard.ClipboardError("busy")))
    with pytest.raises(AutomationError, match="clipboard"):
        whatsapp_files.prepare(attachment)
    assert automation[2] == []


def test_reports_keyboard_failure_with_manual_paste_guidance(tmp_path, automation, monkeypatch):
    attachment = tmp_path / "file.txt"
    attachment.touch()
    monkeypatch.setattr(whatsapp_files.keyboard, "press_keys", Mock(side_effect=whatsapp_files.keyboard.KeyboardError("input rejected")))
    with pytest.raises(AutomationError, match="couldn't paste") as failure:
        whatsapp_files.prepare(attachment)
    assert "file is copied" in str(failure.value)
    assert "review" in str(failure.value)
    assert automation[1] == [attachment]
    assert isinstance(failure.value.__cause__, whatsapp_files.keyboard.KeyboardError)


def test_rejects_oversize_file_before_opening_whatsapp(tmp_path, automation, monkeypatch):
    attachment = tmp_path / "file.txt"
    attachment.write_bytes(b"1234")
    monkeypatch.setattr(whatsapp_files, "MAX_FILE_BYTES", 3)
    with pytest.raises(AutomationError, match="2 GB"):
        whatsapp_files.prepare(attachment)
    assert automation == ([], [], [])


def test_rejects_invalid_saved_phone_before_opening_whatsapp(tmp_path, automation, monkeypatch):
    attachment = tmp_path / "file.txt"
    attachment.touch()
    monkeypatch.setattr(whatsapp_files.whatsapp, "recipient", lambda name: ("Chaitu", "invalid&text=hello"))
    with pytest.raises(AutomationError, match="number"):
        whatsapp_files.prepare(attachment)
    assert automation == ([], [], [])


@pytest.mark.parametrize("kind", ["relative", "missing", "directory"])
def test_rejects_invalid_files_before_opening_whatsapp(tmp_path, automation, kind):
    attachment = {"relative": Path("file.txt"), "missing": tmp_path / "missing.txt", "directory": tmp_path}[kind]
    with pytest.raises(AutomationError):
        whatsapp_files.prepare(attachment)
    assert automation == ([], [], [])


def test_file_drop_payload_has_unicode_path_and_double_null():
    attachment = Path("C:/Users/Chaitu/\u6587\u4ef6 \U0001f680.txt")
    payload = whatsapp_files._file_drop_payload(attachment)
    assert struct.unpack("<IiiII", payload[:20]) == (20, 0, 0, 0, 1)
    assert payload[20:].decode("utf-16-le") == str(attachment) + "\0\0"


@pytest.fixture
def clipboard_apis(monkeypatch):
    storage = ctypes.create_string_buffer(2048)
    user = SimpleNamespace(
        CreateWindowExW=Mock(return_value=101), DestroyWindow=Mock(),
        OpenClipboard=Mock(return_value=True), CloseClipboard=Mock(),
        EmptyClipboard=Mock(return_value=True), SetClipboardData=Mock(return_value=201),
    )
    kernel = SimpleNamespace(
        GlobalAlloc=Mock(return_value=201), GlobalLock=Mock(return_value=ctypes.addressof(storage)),
        GlobalUnlock=Mock(), GlobalFree=Mock(),
    )
    monkeypatch.setattr(whatsapp_files.clipboard, "user32", user)
    monkeypatch.setattr(whatsapp_files.clipboard, "kernel32", kernel)
    monkeypatch.setattr(whatsapp_files.time, "sleep", lambda seconds: None)
    return user, kernel, storage


def test_file_clipboard_transfers_memory_ownership(clipboard_apis):
    user, kernel, storage = clipboard_apis
    attachment = Path("C:/report.txt")
    whatsapp_files._copy_file(attachment)
    payload = whatsapp_files._file_drop_payload(attachment)
    assert storage.raw[:len(payload)] == payload
    user.SetClipboardData.assert_called_once_with(15, 201)
    kernel.GlobalFree.assert_not_called()
    user.CloseClipboard.assert_called_once()
    user.DestroyWindow.assert_called_once_with(101)


@pytest.mark.parametrize("failure", ["owner", "open", "empty", "allocation", "lock", "transfer"])
def test_clipboard_failures_clean_up_handles(clipboard_apis, failure):
    user, kernel, _ = clipboard_apis
    api = {
        "owner": user.CreateWindowExW, "open": user.OpenClipboard,
        "empty": user.EmptyClipboard, "allocation": kernel.GlobalAlloc,
        "lock": kernel.GlobalLock, "transfer": user.SetClipboardData,
    }[failure]
    api.return_value = 0
    with pytest.raises(whatsapp_files.clipboard.ClipboardError):
        whatsapp_files._copy_file(Path("C:/report.txt"))
    if failure in {"empty", "lock", "transfer"}:
        kernel.GlobalFree.assert_called_once_with(201)
    if failure in {"empty", "allocation", "lock", "transfer"}:
        user.CloseClipboard.assert_called_once()
    if failure != "owner":
        user.DestroyWindow.assert_called_once_with(101)
