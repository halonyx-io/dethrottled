"""Readiness and search outcome truth under controlled provider failures."""
import json
import sys
import threading
import time
import types
from concurrent.futures import ThreadPoolExecutor

import pytest

from dethrottled import search as fs
from dethrottled import search_diagnostics as diag
from dethrottled import server
from dethrottled.api_models import SearchBody


def row(engine="web-tls-ddg-lite", index=0):
    return {"url": f"https://example.org/{engine}/{index}", "engine": engine,
            "title": "Useful source choice", "snippet": "A relevant source with detailed evidence."}


@pytest.fixture(autouse=True)
def isolated(monkeypatch, tmp_path):
    monkeypatch.setenv("DETHROTTLED_ENGINE_HEALTH", str(tmp_path / "engines.json"))
    monkeypatch.setattr(diag, "_OBSERVATIONS", {})
    monkeypatch.setattr(fs, "_DDG_RECOVERY", False)
    monkeypatch.setattr(fs, "SEARXNG_URL", "http://fixture")


@pytest.mark.parametrize("primary,supplementary", [(False, True), (True, False), (False, False),
                                                  (True, True)])
def test_health_observes_primary_separately_and_never_probes(monkeypatch, primary, supplementary):
    def web(*args, diagnostics, **kwargs):
        diagnostics.update(status="ok" if primary else "unavailable")
        return [row()] if primary else []

    def searx(*args, diagnostics, engines, **kwargs):
        diagnostics.update(status="ok" if supplementary else "http_429")
        return [row(engines)] if supplementary else []

    monkeypatch.setattr(fs, "web_search", web)
    monkeypatch.setattr(fs, "searxng", searx)
    rows, meta = fs.search("controlled evidence")
    expected = [row()] if primary else []
    if supplementary:
        expected += [row("yandex"), row("yahoo")]
    assert [r["url"] for r in rows] == [r["url"] for r in expected]
    monkeypatch.setattr(fs.requests, "get", lambda *a, **k: pytest.fail("Status must not probe"))
    monkeypatch.setattr(fs, "search", lambda *a, **k: pytest.fail("Status must not search"))
    for _ in range(5):
        report = fs.health()
        assert report["ok"] == primary
        assert report["searxng"] == supplementary
        assert report["degraded"] == (not primary or not supplementary)
    assert meta["discovery"]["outcome"] == (
        "results" if primary and supplementary else "partial_results" if rows else "unavailable")


def test_cold_and_stale_readiness_are_unknown_without_network(monkeypatch):
    monkeypatch.setattr(fs, "search", lambda *a, **k: pytest.fail("No upstream health queries"))
    report = fs.health()
    assert not report["ok"] and report["initializing"]
    assert report["primary_discovery"]["availability"] == "unknown"
    diag.observe({"providers": {"web": {"status": "ok", "count": 1,
                                       "availability": "available"}}})
    diag._OBSERVATIONS["web"]["observed_at"] -= diag.OBSERVATION_TTL + 1
    assert not fs.health()["ok"]
    assert fs.health()["primary_discovery"]["stale"]


@pytest.mark.parametrize("status,count,expected", [("ok", 0, "no_results"),
    ("failed", 0, "unavailable"), ("indeterminate", 0, "indeterminate"),
    ("http_429", 1, "partial_results"), ("ok", 1, "results")])
def test_envelope_adds_precise_outcome_without_breaking_legacy_status(monkeypatch, status, count,
                                                                    expected):
    rows = [row()] if count else []
    reports = {"web": {"status": status}}
    meta = {"per_source": {"web": count}, "source_reports": reports,
            "discovery": diag.summarize({"web": count}, reports)}
    monkeypatch.setattr(server, "_ranked", lambda body: (rows, meta, 15))
    body = server.search_envelope(SearchBody(query="controlled evidence"))
    assert body["outcome"] == expected
    assert body["status"] == ("ok" if count else "no_results_or_degraded")
    assert len(body["results"]) == count
    assert body["attempts"][0]["status"] == status


def refusal_paths(monkeypatch, *, http_status=429, browser_ok=False, retry_after=0):
    calls = []
    monkeypatch.setenv("DETHROTTLED_CHEAP_DISCOVERY", "1")

    def tls(*a, diagnostics, **k):
        calls.append("tls")
        diagnostics.update(status="challenge_or_http_error", http_status=http_status,
                           retry_after_seconds=retry_after)
        return []

    def browser(*a, diagnostics, **k):
        calls.extend(["browser-lite", "browser-html"])
        diagnostics.update(status="ok" if browser_ok else "http_503", attempts=[] if browser_ok
            else [{"engine": e, "status": http_status, "reason": "http_" + str(http_status)}
                  for e in ["ddg-lite", "ddg-html"]])
        return [row("web-browser-ddg-lite")] if browser_ok else []

    class DDGS:
        def text(self, *a, **k):
            calls.append("ddgs")
            raise RuntimeError("controlled refusal")

    monkeypatch.setattr(fs, "tls_search", tls)
    monkeypatch.setattr(fs, "browser_search", browser)
    monkeypatch.setitem(sys.modules, "ddgs", types.SimpleNamespace(DDGS=DDGS))
    return calls


def test_correlated_refusals_rest_all_paths_and_survive_reload(monkeypatch):
    calls = refusal_paths(monkeypatch)
    for _ in range(3):
        fs.web_search("controlled evidence", diagnostics={})
    assert calls == ["tls", "browser-lite", "browser-html", "ddgs"]
    persisted = json.loads(fs._health_path().read_text())
    assert persisted["family:ddg"]["until"] > time.time()
    # There is no in-memory success shortcut: a new caller reads persisted rest.
    fs._DDG_RECOVERY = False
    report = {}
    assert fs.web_search("another query", diagnostics=report) == []
    assert report["status"] == "cooldown"
    assert len(calls) == 4


@pytest.mark.parametrize("http_status,browser_ok", [(429, True), (500, False)])
def test_browser_recovery_and_nonrefusal_errors_do_not_rest_family(monkeypatch, http_status,
                                                                  browser_ok):
    calls = refusal_paths(monkeypatch, http_status=http_status, browser_ok=browser_ok)
    fs.web_search("controlled evidence", diagnostics={})
    fs.web_search("another query", diagnostics={})
    assert calls.count("tls") == 2
    assert "family:ddg" not in fs._load_health()


def test_retry_after_and_cached_results_during_cooldown(monkeypatch):
    calls = refusal_paths(monkeypatch, retry_after=120)
    fs.web_search("controlled evidence", diagnostics={})
    state = fs._load_health()["family:ddg"]
    assert state["until"] - state["at"] >= 119

    class Cache:
        def get(self, *key):
            return [row()] if key[1] == "tls-ddg-lite" else None

    report = {}
    assert fs.web_search("cached evidence", cache=Cache(), diagnostics=report) == [row()]
    assert report["status"] == "cached" and report["upstream_status"] == "cooldown"
    assert len(calls) == 4
    assert fs._load_health()["family:ddg"] == state


def test_one_recovery_probe_and_clear_only_after_success(monkeypatch):
    fs._save_health({"family:ddg": {"fails": 1, "until": time.time() - 1}})
    entered, release = threading.Event(), threading.Event()
    calls = []

    def acquire(*a, **k):
        calls.append(1)
        k["diagnostics"].update(status="ok", count=1)
        entered.set()
        assert release.wait(3)
        return [row()]

    monkeypatch.setattr(fs, "_acquire_web", acquire)
    with ThreadPoolExecutor(max_workers=4) as pool:
        first = pool.submit(fs.web_search, "recovery")
        assert entered.wait(2)
        others = [pool.submit(fs.web_search, "other") for _ in range(3)]
        assert all(f.result(timeout=2) == [] for f in others)
        release.set()
        assert first.result(timeout=3) == [row()]
    assert len(calls) == 1
    assert "family:ddg" not in fs._load_health()


def test_cooldown_expiry_is_not_reported_as_recovery(monkeypatch):
    calls = refusal_paths(monkeypatch)
    fs._save_health({"family:ddg": {"fails": 1, "until": time.time() - 1}})
    fs.web_search("recovery still refused", diagnostics={})
    state = fs._load_health()["family:ddg"]
    assert state["fails"] == 2 and state["until"] > time.time() + 59
    assert len(calls) == 4


def test_explicit_non_ddg_fallback_stays_available_during_family_rest(monkeypatch):
    fs._save_health({"family:ddg": {"fails": 1, "until": time.time() + 60}})
    monkeypatch.setattr(fs, "WEB_ENGINES", ["duckduckgo", "bing"])
    observed = []

    def acquire(*a, engines, **k):
        observed.append(engines)
        return [row("web-bing")]

    monkeypatch.setattr(fs, "_acquire_web", acquire)
    assert fs.web_search("other provider") == [row("web-bing")]
    assert observed == [["bing"]]


def test_searx_ddg_rest_does_not_suppress_independent_engine(monkeypatch):
    fs._save_health({"family:ddg": {"fails": 1, "until": time.time() + 60}})
    observed = []

    class Response:
        status_code = 200

        def json(self):
            return {"results": []}

    def get(*a, params, **k):
        observed.append(params["engines"])
        return Response()

    monkeypatch.setattr(fs.requests, "get", get)
    fs.searxng("controlled evidence", engines="duckduckgo,yahoo")
    assert observed == ["yahoo"]


def test_cached_success_does_not_clear_expired_family_rest(monkeypatch):
    state = {"fails": 1, "until": time.time() - 1}
    fs._save_health({"family:ddg": state})

    def cached(*a, diagnostics, **k):
        diagnostics.update(status="cached", count=1)
        return [row()]

    monkeypatch.setattr(fs, "_acquire_web", cached)
    assert fs.web_search("cached evidence") == [row()]
    assert fs._load_health()["family:ddg"] == state
    diag.observe(diag.summarize({"web": 1}, {"web": {"status": "cached"}}))
    assert not fs.health()["ok"]
    assert fs.health()["primary_discovery"]["cached_results_available"]


def test_readiness_reports_persisted_rest_and_recovery_due():
    fs._save_health({"family:ddg": {"fails": 2, "until": time.time() + 60}})
    report = fs.health()
    assert not report["ok"] and report["ddg_family"]["status"] == "cooldown"
    assert report["primary_discovery"]["availability"] == "unavailable"
    fs._save_health({"family:ddg": {"fails": 2, "until": time.time() - 1}})
    report = fs.health()
    assert not report["ok"] and report["ddg_family"]["status"] == "recovery_due"


def test_cold_supplement_status_is_unknown_not_down():
    assert fs.health()["searxng_status"] == "unknown"


def test_searx_cached_ddg_remains_readable_during_family_rest(monkeypatch):
    fs._save_health({"family:ddg": {"fails": 1, "until": time.time() + 60}})
    monkeypatch.setattr(fs.requests, "get", lambda *a, **k: pytest.fail("No new upstream request"))

    class Cache:
        def get(self, *key):
            return [row("duckduckgo")]

    report = {}
    assert fs.searxng("cached", engines="duckduckgo", cache=Cache(), diagnostics=report)
    assert report["status"] == "cached" and report["upstream_status"] == "cooldown"
