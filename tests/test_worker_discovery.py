"""Started Compose workers become usable without extra endpoint configuration."""

import socket

import pytest

from dethrottled import workers


@pytest.fixture(autouse=True)
def isolated(monkeypatch):
    workers._ENDPOINTS.clear()
    for _name, (variable, _, _) in workers._WORKERS.items():
        monkeypatch.delenv(variable, raising=False)
    monkeypatch.delenv("DETHROTTLED_AUTO_WORKERS", raising=False)


def test_source_installs_do_not_guess_network_services(monkeypatch):
    monkeypatch.setattr(socket, "getaddrinfo", lambda *a, **k: pytest.fail("DNS forbidden"))
    assert workers.endpoint("speech") == ""


@pytest.mark.parametrize("name", ["speech", "layout", "formats"])
def test_started_worker_discovery_is_cached_and_explicit_settings_win(monkeypatch, name):
    monkeypatch.setenv("DETHROTTLED_AUTO_WORKERS", "1")
    calls = []
    monkeypatch.setattr(socket, "getaddrinfo", lambda *a, **k: calls.append(a))
    variable, host, port = workers._WORKERS[name]
    assert workers.endpoint(name) == f"http://{host}:{port}"
    assert workers.endpoint(name) == f"http://{host}:{port}"
    assert calls == [(host, port)]
    monkeypatch.setenv(variable, "off")
    assert workers.endpoint(name) == ""
    monkeypatch.setenv(variable, "https://custom.example/worker/")
    assert workers.endpoint(name) == "https://custom.example/worker"
    assert len(calls) == 1


def test_missing_worker_can_appear_without_a_core_restart(monkeypatch):
    monkeypatch.setenv("DETHROTTLED_AUTO_WORKERS", "1")
    clock = [0]
    monkeypatch.setattr(workers.time, "monotonic", lambda: clock[0])

    def missing(*a, **k):
        raise socket.gaierror("not started")

    monkeypatch.setattr(socket, "getaddrinfo", missing)
    assert workers.endpoint("speech") == ""
    monkeypatch.setattr(socket, "getaddrinfo", lambda *a, **k: [])
    assert workers.endpoint("speech") == ""
    clock[0] = 11
    assert workers.endpoint("speech") == "http://media-worker:19889"


def test_cold_model_readiness_explains_automatic_first_use_download(monkeypatch):
    workers._CACHED.clear()
    monkeypatch.delenv("DETHROTTLED_BROWSER_SEARCH_URL", raising=False)
    monkeypatch.delenv("DETHROTTLED_CRAWL4AI_URL", raising=False)
    monkeypatch.setattr(
        workers, "endpoint", lambda name: "http://speech" if name == "speech" else ""
    )

    class Response:
        status_code = 503

        def json(self):
            return {"detail": "speech_model_not_cached; first transcription downloads weights"}

    monkeypatch.setattr(workers.requests, "get", lambda *a, **k: Response())
    result = workers.status()
    assert result["speech"]["status"] == "unready"
    assert result["speech"]["initialization"] == "first_use_download"
    assert result["formats"]["status"] == "not_configured"


@pytest.mark.parametrize("metrics_body", [
    [], None, ValueError("invalid JSON"), workers.requests.RequestException("timeout"),
])
def test_metrics_failure_keeps_healthy_worker_ready(monkeypatch, metrics_body):
    workers._CACHED.clear()
    monkeypatch.delenv("DETHROTTLED_BROWSER_SEARCH_URL", raising=False)
    monkeypatch.delenv("DETHROTTLED_CRAWL4AI_URL", raising=False)
    monkeypatch.setattr(
        workers, "endpoint", lambda name: "http://formats" if name == "formats" else ""
    )

    def get(url, **kwargs):
        from types import SimpleNamespace

        if url.endswith("/ready"):
            return SimpleNamespace(status_code=200, json=lambda: {"status": "ok"})
        if isinstance(metrics_body, workers.requests.RequestException):
            raise metrics_body

        def body():
            if isinstance(metrics_body, ValueError):
                raise metrics_body
            return metrics_body

        return SimpleNamespace(status_code=200, json=body)

    monkeypatch.setattr(workers.requests, "get", get)
    status = workers.status()["formats"]
    assert status["status"] == "ready"
    assert "metrics" not in status


def test_non_object_browser_health_is_reported_without_breaking_status(monkeypatch):
    from types import SimpleNamespace

    workers._CACHED.clear()
    monkeypatch.setenv("DETHROTTLED_BROWSER_SEARCH_URL", "http://browser")
    monkeypatch.delenv("DETHROTTLED_CRAWL4AI_URL", raising=False)
    monkeypatch.setattr(workers.requests, "get", lambda *a, **k: SimpleNamespace(
        status_code=200, json=lambda: ["unexpected"]))
    assert workers.status()["browser"]["status"] == "unready"
