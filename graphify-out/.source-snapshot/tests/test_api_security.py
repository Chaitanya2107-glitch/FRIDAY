import pytest
from fastapi.testclient import TestClient

from interfaces.api.app import create_app

LOCAL = "http://127.0.0.1:8000"


@pytest.fixture
def client(monkeypatch):
    def must_not_run(name):
        raise AssertionError("a blocked request reached the chat handler")
    monkeypatch.setattr("providers.failover.get_provider", must_not_run)
    return TestClient(create_app(), base_url=LOCAL)


def test_other_website_cannot_run_commands(client):
    # What a page can send blind: a POST with a JSON body and no Content-Type
    # header, which browsers send without asking and FastAPI would parse.
    resp = client.post(
        "/api/v1/chat",
        content=b'{"message": "organise downloads"}',
        headers={"Origin": "https://evil.example"},
    )
    assert resp.status_code == 403
    assert resp.json()["message"] == "Requests from other websites aren't allowed."


def test_sandboxed_page_null_origin_is_blocked(client):
    assert client.get("/health", headers={"Origin": "null"}).status_code == 403


@pytest.mark.parametrize("headers", [
    {},                                        # tray / command bar / curl send no Origin
    {"Origin": LOCAL},                         # the /docs page
    {"Origin": "http://localhost:8000"},
])
def test_local_clients_are_allowed(client, headers):
    assert client.get("/health", headers=headers).status_code == 200


def test_dns_rebinding_host_is_rejected(client):
    assert client.get("/health", headers={"Host": "evil.example"}).status_code == 400


def test_no_cors_headers_are_granted(client):
    resp = client.options(
        "/api/v1/chat",
        headers={"Origin": "https://evil.example", "Access-Control-Request-Method": "POST"},
    )
    assert "access-control-allow-origin" not in resp.headers
