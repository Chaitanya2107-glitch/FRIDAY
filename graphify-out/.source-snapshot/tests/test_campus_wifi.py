import asyncio
from types import SimpleNamespace

import pytest

from services.automation import intent, logins
from services.network import campus

PORTAL = "http://captiveportal.reva.edu.in:1000/fgtauth?0f0a1b2c3d"


@pytest.fixture(autouse=True)
def fresh(monkeypatch):
    monkeypatch.setattr(campus, "_last_try", 0.0)
    opened = []
    monkeypatch.setattr("services.automation.system_control.system.open_url", lambda url: opened.append(url) or "ok")
    return opened


def redirect(monkeypatch, *, location=None, body=""):
    reply = SimpleNamespace(status_code=303 if location else 200, headers={"location": location} if location else {},
                            text=body)
    monkeypatch.setattr(campus.httpx, "get", lambda *a, **k: reply)


def test_finds_the_portal_from_a_redirect_or_a_page(monkeypatch):
    redirect(monkeypatch, location=PORTAL)
    assert campus.portal_url() == PORTAL
    redirect(monkeypatch, body=f'<script>window.location="{PORTAL}";</script>')
    assert campus.portal_url() == PORTAL
    redirect(monkeypatch, body="Microsoft Connect Test")
    assert campus.portal_url() is None


def test_campus_portal_is_opened_and_signed_into(monkeypatch, fresh):
    redirect(monkeypatch, location=PORTAL)
    assert campus.on_no_internet(now_ts=1_000).startswith("Campus Wi-Fi wants a sign-in — I opened it.")  # none saved
    assert fresh == [PORTAL]

    logins._save({"wifi": {"url": "https://captiveportal.reva.edu.in:1000", "two_step": True}})
    signed = []

    def log_in(name, open_url):
        open_url("the saved page")
        signed.append(name)
        return "Signing you in to wifi."
    monkeypatch.setattr(logins, "log_in", log_in)
    assert campus.on_no_internet(now_ts=10_000) == "Campus Wi-Fi: Signing you in to wifi."
    assert signed == ["wifi"] and fresh[-1] == PORTAL  # the detected page (its one-time token), not the saved one
    assert campus.on_no_internet(now_ts=10_060) is None  # not again within RETRY_MINUTES


def test_other_networks_only_get_a_notification(monkeypatch, fresh):
    redirect(monkeypatch, location="http://hotspot.cafe.example/login")
    logins._save({"wifi": {"url": "https://captiveportal.reva.edu.in:1000", "two_step": True}})
    monkeypatch.setattr(logins, "log_in", lambda *a: pytest.fail("typed the college password on another network"))
    assert campus.on_no_internet() == "This Wi-Fi wants you to sign in (hotspot.cafe.example). Open a browser to continue."
    assert fresh == []


def test_open_lms(monkeypatch, fresh):
    assert asyncio.run(intent.try_system_action("open lms", "openrouter")).success
    assert fresh == ["https://rulms.reva.edu.in"]  # nothing saved: just the site
    logins._save({"lms": {"url": "https://rulms.reva.edu.in/login/index.php", "two_step": False}})
    assert logins.match_login_command("lms login") == {"type": "system", "action": "log_in", "name": "lms"}
    assert logins.match_login_command("open my lms")["action"] == "log_in"
