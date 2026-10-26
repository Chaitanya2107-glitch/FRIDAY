from datetime import datetime
from types import SimpleNamespace
from xml.etree import ElementTree

import pytest

from services.security import intruder


@pytest.fixture
def setup(tmp_path, monkeypatch):
    monkeypatch.setattr(intruder, "PHOTO_DIR", tmp_path / "intruder")
    monkeypatch.setattr(intruder.config, "TELEGRAM_BOT_TOKEN", "t")
    monkeypatch.setattr(intruder.config, "TELEGRAM_USER_ID", 42)
    sent = []
    telegram = SimpleNamespace(send_file=lambda chat, path, photo, caption: sent.append((chat, path.name, caption)),
                               send=lambda chat, text: sent.append((chat, None, text)))
    return SimpleNamespace(sent=sent, telegram=telegram)


def fake_photo(path):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"jpg")


def test_wrong_password_sends_the_photo(setup):
    at = datetime(2026, 9, 30, 14, 32, 5)
    assert intruder.alert(now=at, photo=fake_photo, telegram=setup.telegram) == "sent"
    assert setup.sent == [(42, "2026-09-30 14-32-05.jpg", "Wrong password on your laptop at 14:32 (Wed 30 Sep)")]
    assert (intruder.PHOTO_DIR / "2026-09-30 14-32-05.jpg").exists()  # kept locally too


def test_several_tries_in_a_row_send_one_alert(setup):
    at = datetime(2026, 9, 30, 14, 32, 0)
    intruder.alert(now=at, photo=fake_photo, telegram=setup.telegram)
    assert intruder.alert(now=at.replace(second=10), photo=fake_photo, telegram=setup.telegram).startswith("skipped")
    assert intruder.alert(now=at.replace(second=30), photo=fake_photo, telegram=setup.telegram) == "sent"
    assert len(setup.sent) == 2


def test_no_camera_still_sends_the_message(setup):
    def broken(path):
        raise RuntimeError("no webcam found")
    intruder.alert(now=datetime(2026, 9, 30, 9, 0), photo=broken, telegram=setup.telegram)
    assert setup.sent == [(42, None, "Wrong password on your laptop at 09:00 (Wed 30 Sep) — couldn't take a photo.")]


def test_offline_keeps_the_photo_and_never_raises(setup):
    def offline(*a, **k):
        raise ConnectionError("no internet")
    result = intruder.alert(now=datetime(2026, 9, 30, 9, 0), photo=fake_photo,
                            telegram=SimpleNamespace(send_file=offline, send=offline))
    assert result == "not sent" and any(intruder.PHOTO_DIR.glob("*.jpg"))


def test_task_runs_on_failed_logons_as_system():
    xml = intruder.task_xml()
    root = ElementTree.fromstring(xml.split("?>", 1)[1])
    ns = {"t": "http://schemas.microsoft.com/windows/2004/02/mit/task"}
    assert "EventID=4625" in root.find(".//t:Subscription", ns).text
    assert root.find(".//t:UserId", ns).text == "S-1-5-18"
    assert root.find(".//t:Arguments", ns).text == "-m services.security.intruder"
