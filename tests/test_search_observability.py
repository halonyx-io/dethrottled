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
    assert body["degraded"] == meta["discovery"]["degraded"]
    assert body["discovery"] == meta["discovery"]
    assert body["status"] == ("ok" if count else "no_results_or_degraded")
    assert len(body["results"]) == count
    assert body["attempts"][0]["status"] == status
    # The legacy array and envelope retain exactly the same useful source choices.
    assert server.search(SearchBody(query="controlled evidence")) == body["results"]


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
    # This provider double has no ddgs.http_client; transport wrapping is tested
    # independently and must not depend on another test having imported DDGS.
    monkeypatch.setattr(fs.requests, "install_ddgs", lambda: None)
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
    assert calls == ["tls"]  # Retry-After stops further live attempts immediately.
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


def test_browser_refusal_preserves_reason_and_elapsed_time(monkeypatch):
    import requests

    class Response:
        ok = False
        status_code = 503

        def json(self):
            return {"detail": {"reason": "no_usable_engine", "service_s": 1.25,
                               "queue_s": 0.5, "attempts": [
                                   {"engine": "ddg-lite", "status": 202,
                                    "reason": "challenge_page", "count": 0}]}}

        def raise_for_status(self):
            raise requests.HTTPError("503")

    monkeypatch.setattr(fs, "BROWSER_SEARCH_URL", "http://worker")
    monkeypatch.setattr(fs.requests, "post", lambda *a, **kw: Response())
    diagnostics = {}
    assert fs.browser_search("controlled refusal", diagnostics=diagnostics) == []
    assert diagnostics["status"] == "http_503"
    assert diagnostics["browser_count"] == 0
    assert diagnostics["reason"] == "no_usable_engine"
    assert diagnostics["elapsed_ms"] == 1250
    assert diagnostics["queue_ms"] == 500
    assert diagnostics["attempts"][0]["status"] == 202


def test_readiness_distinguishes_stale_success_from_confirmed_failure():
    assert fs.health()["primary_discovery"]["observation_state"] == "unobserved"
    diag.observe({"providers": {"web": {"status": "ok", "count": 1,
                                       "availability": "available"}}})
    assert fs.health()["primary_discovery"]["observation_state"] == "current"
    diag._OBSERVATIONS["web"]["observed_at"] -= diag.OBSERVATION_TTL + 1
    report = fs.health()["primary_discovery"]
    assert report["availability"] == "unknown" and report["observation_state"] == "stale"
    assert report["last_observed_availability"] == "available"
    assert not report["ready"]
    diag.observe({"providers": {"web": {"status": "http_503", "count": 0,
                                       "availability": "unavailable"}}})
    report = fs.health()["primary_discovery"]
    assert report["observation_state"] == "current"
    assert report["last_observed_availability"] == report["availability"] == "unavailable"


@pytest.mark.parametrize("count,status", [(2, "ok"), (0, "http_503")])
def test_browser_attempt_keeps_its_count_and_failure_after_ddgs_fallback(count, status):
    # DDGS may subsequently overwrite the web-family total/status. That must not
    # turn a failed browser request into a successful one or give it DDGS rows.
    meta = {"browser_search": {"status": "ok", "count": 10, "browser_count": count,
                               "browser_status": status, "elapsed_ms": 1250,
                               "reason": "no_usable_engine" if not count else None,
                               "attempts": [{"engine": "ddg-lite", "count": count,
                                             "status": 200 if count else 202}]}}
    attempt = next(a for a in server._attempts(meta) if a["engine"] == "browser-search")
    assert attempt["count"] == count and attempt["status"] == status
    assert attempt["reason"] == ("no_usable_engine" if not count else None)


def test_empty_ddgs_fallback_cannot_erase_correlated_refusals(monkeypatch):
    refusal_paths(monkeypatch, http_status=202)

    class DDGS:
        def text(self, *args, **kwargs):
            return []

    monkeypatch.setitem(sys.modules, "ddgs", types.SimpleNamespace(DDGS=DDGS))
    report = {}
    assert fs.web_search("controlled refusal", diagnostics=report) == []
    assert report["upstream_status"] == "cooldown"
    assert report["status"] != "no_results"
    assert diag.outcome(0, report) == "unavailable"


@pytest.mark.parametrize("status", [202, 429, 503])
def test_explicit_retry_after_prevents_more_ddg_attempts(monkeypatch, status):
    calls = refusal_paths(monkeypatch, http_status=status, retry_after=120)
    report = {}
    assert fs.web_search("server requested wait", diagnostics=report) == []
    assert calls == ["tls"]
    assert report["status"] == "retry_after" and report["upstream_status"] == "cooldown"
    assert fs._load_health()["family:ddg"]["reason"] == "retry_after"
    assert fs._load_health()["family:ddg"]["until"] - time.time() > 119
    assert fs.web_search("concurrent later caller", diagnostics={}) == []
    assert calls == ["tls"]


def test_empty_ddgs_without_refusal_stays_genuinely_empty(monkeypatch):
    monkeypatch.setenv("DETHROTTLED_CHEAP_DISCOVERY", "0")

    def browser(*args, diagnostics, **kwargs):
        diagnostics.update(status="not_configured", attempts=[])
        return []

    class DDGS:
        def text(self, *args, **kwargs):
            return []

    monkeypatch.setattr(fs, "browser_search", browser)
    monkeypatch.setitem(sys.modules, "ddgs", types.SimpleNamespace(DDGS=DDGS))
    monkeypatch.setattr(fs.requests, "install_ddgs", lambda: None)
    report = {}
    assert fs.web_search("genuinely empty", diagnostics=report) == []
    assert report["status"] == "no_results"
    assert diag.outcome(0, report) == "empty"
    assert "family:ddg" not in fs._load_health()


def test_browser_retry_after_stops_library_fallback_and_rests_family(monkeypatch):
    calls = refusal_paths(monkeypatch)

    def browser(*args, diagnostics, **kwargs):
        calls.append("browser")
        diagnostics.update(status="http_503", attempts=[
            {"engine": "ddg-lite", "status": 429, "retry_after_seconds": 120}])
        return []

    monkeypatch.setattr(fs, "browser_search", browser)
    report = {}
    assert fs.web_search("browser wait", diagnostics=report) == []
    assert calls == ["tls", "browser"]
    assert report["upstream_status"] == "cooldown"
    assert fs._load_health()["family:ddg"]["until"] - time.time() > 119
    assert fs.web_search("later caller", diagnostics={}) == []
    assert calls == ["tls", "browser"]


def test_already_received_results_survive_a_parallel_retry_after():
    report = {"status": "ok", "count": 1, "attempts": [
        {"engine": "ddg-lite", "status": 429, "retry_after_seconds": 120},
        {"engine": "ddg-html", "status": 200, "count": 1}]}
    rows = [row("web-browser-ddg-html")]
    fs._ddg_finish(rows, report, False)
    assert rows and report["upstream_status"] == "cooldown"
    assert diag.outcome(1, report) == "degraded"
