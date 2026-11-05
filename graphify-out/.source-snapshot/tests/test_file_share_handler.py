"""Explorer sends exact file paths to the local API without shell execution."""

import io
import json
from unittest.mock import MagicMock
from urllib.error import HTTPError, URLError

import pytest

from interfaces import file_share_handler as handler


@pytest.fixture
def api(monkeypatch):
    opener = MagicMock()
    response = opener.open.return_value.__enter__.return_value
    response.read.return_value = json.dumps({"success": True, "message": "Sent to your Telegram."}).encode()
    monkeypatch.setattr(handler.urllib.request, "build_opener", lambda *args: opener)
    return opener


def test_posts_exact_absolute_file_path_to_local_api(tmp_path, api):
    file = tmp_path / "notes & résumé ' $(example).txt"
    file.write_text("hello")
    result = handler.share_file("telegram", str(file), 8123)
    assert result["success"] is True
    request = api.open.call_args.args[0]
    assert request.full_url == "http://127.0.0.1:8123/api/v1/share/file"
    assert request.method == "POST"
    assert json.loads(request.data) == {"channel": "telegram", "path": str(file)}
    assert api.open.call_args.kwargs["timeout"] == 120


@pytest.mark.parametrize("kind", ["relative", "directory", "missing"])
def test_invalid_file_never_calls_api(tmp_path, api, kind):
    path = {"relative": "file.txt", "directory": str(tmp_path), "missing": str(tmp_path / "missing.txt")}[kind]
    assert handler.share_file("telegram", path, 8000)["success"] is False
    api.open.assert_not_called()


@pytest.mark.parametrize("channel,port", [("email", 8000), ("telegram", 0), ("whatsapp", 65536), ("telegram", True)])
def test_invalid_channel_or_port_never_calls_api(tmp_path, api, channel, port):
    file = tmp_path / "sample.txt"
    file.write_text("hello")
    assert not handler.share_file(channel, str(file), port)["success"]
    api.open.assert_not_called()


def test_reports_backend_json_error(tmp_path, api):
    file = tmp_path / "sample.txt"
    file.write_text("hello")
    api.open.side_effect = HTTPError("http://localhost", 400, "bad", {}, io.BytesIO(b'{"detail":"Save Chaitu as a WhatsApp contact first."}'))
    result = handler.share_file("whatsapp", str(file), 8000)
    assert not result["success"]
    assert result["message"] == "Save Chaitu as a WhatsApp contact first."


@pytest.mark.parametrize("error", [URLError("secret connection details"), TimeoutError("secret timeout details")])
def test_offline_or_timeout_error_is_visible_without_technical_details(tmp_path, api, error):
    file = tmp_path / "sample.txt"
    file.write_text("hello")
    api.open.side_effect = error
    result = handler.share_file("telegram", str(file), 8000)
    assert not result["success"]
    assert "Friday" in result["message"]
    assert "secret" not in result["message"]


@pytest.mark.parametrize("payload", [b"not JSON", b'{}', b'{"success":"true","message":"sent"}'])
def test_rejects_malformed_backend_response(tmp_path, api, payload):
    file = tmp_path / "sample.txt"
    file.write_text("hello")
    api.open.return_value.__enter__.return_value.read.return_value = payload
    assert not handler.share_file("telegram", str(file), 8000)["success"]


def test_main_reports_result_in_dialog(tmp_path, api, monkeypatch):
    file = tmp_path / "sample.txt"
    file.write_text("hello")
    messages = []
    monkeypatch.setattr(handler, "show_message", lambda message, success: messages.append((message, success)))
    assert handler.main(["telegram", str(file), "8000"]) == 0
    assert messages == [("Sent to your Telegram.", True)]


def test_main_reports_bad_arguments_in_dialog(monkeypatch):
    messages = []
    monkeypatch.setattr(handler, "show_message", lambda message, success: messages.append((message, success)))
    assert handler.main(["email", "sample.txt", "8000"]) == 1
    assert messages and messages[0][1] is False


def test_backend_can_report_prepared_whatsapp_draft(tmp_path, api):
    file = tmp_path / "sample.txt"
    file.write_text("hello")
    payload = {"success": True, "message": "Ready in WhatsApp; click Send.", "status": "prepared"}
    api.open.return_value.__enter__.return_value.read.return_value = json.dumps(payload).encode()
    assert handler.share_file("whatsapp", str(file), 8000) == payload


def test_helper_disables_proxies_and_redirects(tmp_path, monkeypatch):
    file = tmp_path / "sample.txt"
    file.write_text("hello")
    handlers = []
    opener = MagicMock()
    opener.open.side_effect = URLError("offline")
    def build(*configured):
        handlers.extend(configured)
        return opener
    monkeypatch.setattr(handler.urllib.request, "build_opener", build)
    handler.share_file("telegram", str(file), 8000)
    assert handlers[0].proxies == {}
    assert handlers[1].redirect_request(None, None, 302, "", {}, "https://external.example") is None
    assert opener.open.call_count == 1


def test_pythonw_results_use_native_dialog(monkeypatch):
    user32 = MagicMock()
    windll = MagicMock(user32=user32)
    monkeypatch.setattr(handler.ctypes, "windll", windll, raising=False)
    monkeypatch.setattr(handler.os, "name", "nt")
    handler.show_message("Sent.", True)
    args = user32.MessageBoxW.call_args.args
    assert args[:3] == (None, "Sent.", handler.TITLE)
    assert args[3] & 0x40
