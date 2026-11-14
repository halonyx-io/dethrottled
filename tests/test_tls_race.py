"""Racing TLS against a silent plain request (fetch._race_direct).

Tarpit sites accept the connection and never answer, which cost 18.7 s a read
before TLS got its turn. A response that has begun must never be raced, and a
TLS request the race started must be reused, not sent twice.
"""
import time

import pytest
from test_fetch_internals import ARTICLE

from dethrottled import fetch as f


@pytest.fixture(autouse=True)
def isolated(monkeypatch):
    monkeypatch.setattr(f, "_throttle", lambda domain: None)
    monkeypatch.setattr(f, "CRAWL4AI_URL", "")
    monkeypatch.setattr(f, "TLS_HEDGE_SECONDS", 0.2)
    f._tier_rest.clear()
    yield


def counted(calls, name, delay, payload, reason="", respond=False):
    def run(url, *a, **k):
        calls.append(name)
        if respond and f._DIRECT_RESPONDED.get() is not None:
            f._DIRECT_RESPONDED.get().set()
        time.sleep(delay)
        return payload, reason, url
    return run


def test_tls_wins_when_plain_http_is_silent(monkeypatch):
    calls = []
    monkeypatch.setattr(f, "_tier_direct", counted(calls, "direct", 1.0, {}, "ReadTimeout"))
    monkeypatch.setattr(f, "_tier_tls", counted(calls, "tls", 0.0, {"html": ARTICLE}))
    started = time.monotonic()
    result = f.fetch_and_extract("https://tarpit.example/a", max_chars=5000)
    assert result["ok"] and result["tier"] == "tls"
    assert time.monotonic() - started < 0.9, "must not wait for the plain timeout"
    first = result["acquisition_attempts"][0]
    assert first["tier"] == "direct" and first["reason"].startswith("no_response_in_")
    assert calls.count("tls") == 1


def test_a_response_that_has_begun_is_never_raced(monkeypatch):
    calls = []
    monkeypatch.setattr(f, "_tier_direct",
                        counted(calls, "direct", 0.5, {"html": ARTICLE}, respond=True))
    monkeypatch.setattr(f, "_tier_tls", counted(calls, "tls", 0.0, {"html": ARTICLE}))
    result = f.fetch_and_extract("https://slow-download.example/a", max_chars=5000)
    assert result["tier"] == "direct" and calls == ["direct"]


def test_plain_http_still_wins_when_tls_is_challenged(monkeypatch):
    calls = []
    monkeypatch.setattr(f, "_tier_direct", counted(calls, "direct", 0.5, {"html": ARTICLE}))
    monkeypatch.setattr(f, "_tier_tls", counted(calls, "tls", 0.0, {}, "tls_challenge"))
    result = f.fetch_and_extract("https://slow-server.example/a", max_chars=5000)
    assert result["ok"] and result["tier"] == "direct"
    assert calls.count("tls") == 1


def test_the_race_result_is_reused_by_the_tls_step(monkeypatch):
    """Plain HTTP answers (with a failure) before TLS: the TLS step takes the
    already-running request instead of sending another."""
    calls = []
    monkeypatch.setattr(f, "_tier_direct", counted(calls, "direct", 0.3, {}, "ConnectionError"))
    monkeypatch.setattr(f, "_tier_tls", counted(calls, "tls", 0.5, {"html": ARTICLE}))
    result = f.fetch_and_extract("https://flaky.example/a", max_chars=5000)
    assert result["ok"] and result["tier"] == "tls"
    assert calls.count("tls") == 1
    assert [a["tier"] for a in result["acquisition_attempts"]] == ["direct", "tls"]


def test_the_race_can_be_turned_off(monkeypatch):
    calls = []
    monkeypatch.setattr(f, "TLS_HEDGE_SECONDS", 0)
    monkeypatch.setattr(f, "_tier_direct", counted(calls, "direct", 0.3, {}, "ReadTimeout"))
    monkeypatch.setattr(f, "_tier_tls", counted(calls, "tls", 0.0, {"html": ARTICLE}))
    result = f.fetch_and_extract("https://tarpit.example/b", max_chars=5000)
    assert result["tier"] == "tls" and calls == ["direct", "tls"]
