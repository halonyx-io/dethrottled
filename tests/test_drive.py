"""The browser-driving contract stays bounded, stateful and cheap by default."""
import pytest

fastapi_testclient = pytest.importorskip("fastapi.testclient")
TestClient = fastapi_testclient.TestClient

from dethrottled import search as fs  # noqa: E402
from dethrottled import server as srv  # noqa: E402


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setattr(srv.fs, "BROWSER_SEARCH_URL", "http://browser-search:19888")
    monkeypatch.setattr(srv.fs, "browser_drive", lambda payload: {
        "ok": True, "steps": [], "echo": payload,
        "session": {"id": payload.get("session") or None, "persistent": True},
    })
    return TestClient(srv.app)


def test_drive_defaults_to_failure_only_screenshots(client):
    body = client.post("/drive", json={"url": "https://example.com"}).json()
    assert body["echo"]["screenshot"] == "failure"
    assert body["echo"]["include_events"] is True
    assert body["echo"]["session"].startswith("auto-")


def test_drive_navigation_without_name_returns_reusable_session(client):
    body = client.post("/drive", json={
        "steps": [{"action": "goto", "url": "https://example.com"}],
    }).json()
    assert body["session"]["id"].startswith("auto-")
    assert body["session"]["persistent"] is True


def test_drive_stateful_steps_without_session_fail_actionably(client):
    response = client.post("/drive", json={
        "steps": [{"action": "snapshot", "limit": 10}],
    })
    assert response.status_code == 422
    assert "reuse the returned session.id" in response.json()["detail"]


def test_drive_accepts_agent_inspection_and_session_fields(client):
    request = {
        "session": "airtable-attacker",
        "allowed_hosts": ["staging.airtable.com", "*.staging.airtable.com"],
        "canaries": ["XSS_CANARY_123"],
        "screenshot": "canary",
        "steps": [{"action": "snapshot", "selector": "main", "limit": 50},
                  {"action": "attr", "selector": "input", "name": "value"}],
    }
    body = client.post("/drive", json=request).json()
    assert body["echo"]["session"] == "airtable-attacker"
    assert body["echo"]["steps"][0]["action"] == "snapshot"
    assert body["echo"]["canaries"] == ["XSS_CANARY_123"]


def test_drive_allows_close_only_for_named_session(client):
    response = client.post("/drive", json={"session": "victim", "close_session": True})
    assert response.status_code == 200


def test_drive_rejects_empty_or_unsafe_session_name(client):
    assert client.post("/drive", json={}).status_code == 422
    assert client.post("/drive", json={"session": "../../oops",
                                        "close_session": True}).status_code == 422


def test_capabilities_advertise_power_without_arbitrary_evaluate(client):
    manipulation = client.get("/v2/capabilities").json()["manipulation"]
    assert manipulation["persistent_sessions"] is True
    assert manipulation["automatic_sessions"] is True
    assert {"snapshot", "html", "attr", "count", "title"} <= set(manipulation["actions"])
    assert "evaluate" not in manipulation["actions"]
    assert manipulation["screenshot_modes"] == ["never", "failure", "canary", "always"]
    assert {"hidden", "unstable", "covered", "out_of_viewport"} <= set(
        manipulation["failure_diagnostics"]
    )


def test_browser_proxy_timeout_tracks_requested_run_budget(monkeypatch):
    seen = {}

    class Response:
        status_code = 200

        @staticmethod
        def json():
            return {"ok": True}

    def post(url, json, timeout):
        seen.update(url=url, payload=json, timeout=timeout)
        return Response()

    monkeypatch.setattr(fs, "BROWSER_SEARCH_URL", "http://browser-search:19888")
    monkeypatch.setattr(fs.requests, "post", post)
    fs.browser_drive({"timeout_ms": 180000})
    assert seen["timeout"] == 195
