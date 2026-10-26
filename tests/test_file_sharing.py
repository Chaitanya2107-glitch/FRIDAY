import pytest
from fastapi.testclient import TestClient

from core.config import config
from interfaces.api.app import create_app
from services.files import sharing
from services.telegram import client as telegram


@pytest.fixture
def file(tmp_path):
    selected = tmp_path / "Chaitu's notes & नोट्स.pdf"
    selected.write_bytes(b"example document")
    return selected


@pytest.fixture
def uploads(monkeypatch):
    sent = []
    monkeypatch.setattr(config, "TELEGRAM_BOT_TOKEN", "test-token")
    monkeypatch.setattr(config, "TELEGRAM_USER_ID", 42)
    monkeypatch.setattr(telegram, "send_file", lambda recipient, path: sent.append((recipient, path)))
    return sent


def test_telegram_sends_selected_file_to_configured_user(file, uploads):
    result = sharing.share_file(str(file), "telegram")
    assert result.success and result.status == "sent"
    assert uploads == [(42, file)]


def test_filename_ending_in_apostrophe_is_preserved(file, uploads):
    selected = file.with_name("notes'")
    selected.write_bytes(b"example")
    assert sharing.share_file(str(selected), "telegram").success
    assert uploads == [(42, selected)]


def test_explicit_selection_bypasses_chat_reference_parser(file, uploads, monkeypatch):
    monkeypatch.setattr(sharing.telegram_commands, "_file", lambda *a: pytest.fail("explicit file sent through chat parser"))
    assert sharing.share_file(str(file), "telegram").success
    assert uploads == [(42, file)]


@pytest.mark.parametrize("selection", ["relative.pdf", "", "missing", "folder"])
def test_invalid_selection_is_not_sent(file, uploads, selection):
    value = str(file.parent) if selection == "folder" else str(file.parent / "missing.pdf") if selection == "missing" else selection
    result = sharing.share_file(value, "telegram")
    assert not result.success and result.status == "failed"
    assert uploads == []


def test_unconfigured_telegram_gives_setup_message(file, uploads, monkeypatch):
    monkeypatch.setattr(config, "TELEGRAM_BOT_TOKEN", "")
    result = sharing.share_file(str(file), "telegram")
    assert not result.success and "configured" in result.message
    assert not uploads


def test_telegram_limit_is_checked_before_upload(file, uploads, monkeypatch):
    monkeypatch.setattr(telegram, "MAX_UPLOAD_BYTES", 1)
    result = sharing.share_file(str(file), "telegram")
    assert not result.success and "limit" in result.message
    assert not uploads


def test_network_failure_is_reported_without_credentials(file, uploads, monkeypatch):
    def fail(*args):
        raise telegram.TelegramError("test-token")
    monkeypatch.setattr(telegram, "send_file", fail)
    result = sharing.share_file(str(file), "telegram")
    assert not result.success and result.status == "failed"
    assert "test-token" not in result.message


def test_whatsapp_prepares_attachment_for_chaitu(file, monkeypatch):
    from services.automation import whatsapp_files
    attached = []
    monkeypatch.setattr(whatsapp_files, "prepare", lambda path, contact: attached.append((path, contact)) or "Review the attachment and press Send.")
    result = sharing.share_file(str(file), "whatsapp")
    assert result.success and result.status == "prepared"
    assert attached == [(file, "chaitu")]
    assert "press Send" in result.message


def test_whatsapp_operations_do_not_overlap(file):
    sharing._whatsapp_lock.acquire()
    try:
        result = sharing.share_file(str(file), "whatsapp")
    finally:
        sharing._whatsapp_lock.release()
    assert not result.success and "progress" in result.message


def test_whatsapp_failure_releases_attachment_lock(file, monkeypatch):
    from services.automation import whatsapp_files
    from services.automation.system_control import AutomationError
    def fail(*args):
        raise AutomationError("WhatsApp lost focus.")
    monkeypatch.setattr(whatsapp_files, "prepare", fail)
    result = sharing.share_file(str(file), "whatsapp")
    assert not result.success and "lost focus" in result.message
    assert not sharing._whatsapp_lock.locked()


def test_whatsapp_size_limit_is_checked_before_opening(file, monkeypatch):
    from services.automation import whatsapp_files
    monkeypatch.setattr(sharing, "WHATSAPP_MAX_BYTES", 1)
    monkeypatch.setattr(whatsapp_files, "prepare", lambda *a: pytest.fail("oversize file opened WhatsApp"))
    result = sharing.share_file(str(file), "whatsapp")
    assert not result.success and "limit" in result.message


def test_unknown_channel_cannot_send(file, uploads):
    assert not sharing.share_file(str(file), "email").success
    assert not uploads


def test_api_sends_exact_path_without_command_parsing(file, uploads):
    client = TestClient(create_app(), base_url="http://127.0.0.1:8000")
    response = client.post("/api/v1/share/file", json={"path": str(file), "channel": "telegram"})
    assert response.status_code == 200
    assert response.json()["success"] and response.json()["status"] == "sent"
    assert uploads == [(42, file)]


@pytest.mark.parametrize("body", [
    {"path": "x", "channel": "email"}, {"channel": "telegram"},
    {"path": "x", "channel": "telegram", "recipient": 99},
])
def test_api_rejects_invalid_channel_or_recipient_override(uploads, body):
    client = TestClient(create_app(), base_url="http://127.0.0.1:8000")
    assert client.post("/api/v1/share/file", json=body).status_code == 422
    assert not uploads


def test_website_cannot_trigger_file_send(file, uploads):
    client = TestClient(create_app(), base_url="http://127.0.0.1:8000")
    response = client.post("/api/v1/share/file", json={"path": str(file), "channel": "telegram"},
                           headers={"Origin": "https://evil.example"})
    assert response.status_code == 403 and not uploads


def test_backend_registers_menu_at_startup(monkeypatch):
    from interfaces.api import app
    registered = []
    monkeypatch.setattr(app, "register_file_menu", lambda: registered.append(True))
    # Keep startup verification independent of the microphone and background tasks.
    def close_task(coroutine):
        coroutine.close()
        future = app.asyncio.get_running_loop().create_future()
        future.cancel()
        return future
    monkeypatch.setattr(app.asyncio, "create_task", close_task)
    with TestClient(app.create_app(), base_url="http://127.0.0.1:8000") as client:
        assert client.get("/health").status_code == 200
    assert registered == [True]
