"""Direct doors to Bing's index after DuckDuckGo, Mwmbl, and Google last."""
import base64

import pytest

from dethrottled import discovery
from dethrottled import search as fs

QUERY = "postgresql autovacuum tuning"


def bing_href(url):
    token = base64.urlsafe_b64encode(url.encode()).decode().rstrip("=")
    return "https://www.bing.com/ck/a?!&&p=x&u=a1" + token + "&ntb=1"


def bing_page(rows):
    items = "".join(
        f'<li class="b_algo"><h2><a href="{bing_href(u)}">{t}</a></h2>'
        f'<div class="b_caption"><p>{s}</p></div></li>' for u, t, s in rows)
    return f'<html><ol id="b_results">{items}</ol></html>'


def yahoo_page(rows, date=""):
    stamp = f'<span class="fc-smoke">{date} · </span>' if date else ""
    items = "".join(
        f'<div class="dd algo algo-sr"><div class="compTitle"><a href="https://r.search.yahoo.com'
        f'/_ylt=x/RV=2/RE=1/RO=10/RU={u.replace(":", "%3a").replace("/", "%2f")}/RK=2/RS=y-">'
        f'<span>breadcrumb</span><h3><span>{t}</span></h3></a></div>'
        f'<div class="compText"><p>{stamp}{s}</p></div></div>' for u, t, s in rows)
    return f"<html>{items}</html>"


GOOD = [(f"https://example.org/autovacuum-{i}", f"PostgreSQL autovacuum tuning guide {i}",
         "Oct 31, 2025 · How to tune autovacuum thresholds and cost limits in PostgreSQL.")
        for i in range(5)]


class Response:
    def __init__(self, text, status=200):
        self.text, self.status_code, self.headers = text, status, {}


@pytest.fixture(autouse=True)
def fresh_doors(monkeypatch):
    monkeypatch.setenv("DETHROTTLED_DIRECT_DOORS", "1")
    monkeypatch.setattr(discovery, "_DOOR_REST", {})
    monkeypatch.setattr(discovery, "_DOOR_NEXT", {})


def serve(monkeypatch, pages):
    calls = []

    def get(name, url, timeout=4.0):
        calls.append(name)
        return pages[name]() if callable(pages[name]) else pages[name]
    monkeypatch.setattr(discovery, "_door_get", get)
    return calls


def test_bing_rows_unwrap_links_and_keep_snippet_dates(monkeypatch):
    serve(monkeypatch, {"bing": Response(bing_page(GOOD))})
    report = {}
    rows = discovery.door_search("bing", QUERY, diagnostics=report)
    assert [r["url"] for r in rows] == [u for u, _, _ in GOOD]
    assert rows[0]["engine"] == "web-tls-bing" and rows[0]["snippet"].startswith("Oct 31, 2025")
    assert report["status"] == "ok" and report["count"] == 5


def test_yahoo_rows_unwrap_ru_links_and_use_h3_title(monkeypatch):
    serve(monkeypatch, {"yahoo": Response(yahoo_page(GOOD))})
    rows = discovery.door_search("yahoo", QUERY)
    assert rows[0]["url"] == GOOD[0][0]
    assert rows[0]["title"] == GOOD[0][1] and rows[0]["engine"] == "web-tls-yahoo"


def test_a_refusing_door_rests_and_is_not_asked_again(monkeypatch):
    calls = serve(monkeypatch, {"bing": Response("<html>captcha</html>", 200)})
    report = {}
    assert discovery.door_search("bing", QUERY, diagnostics=report) == []
    assert report["refusal"] and discovery.door_resting("bing") > 0
    again = {}
    assert discovery.door_search("bing", QUERY, diagnostics=again) == []
    assert again["status"] == "resting" and calls == ["bing"]


def test_chain_asks_bing_then_yahoo_and_rests_a_decoy(monkeypatch):
    decoy = [(f"https://icons.example/escalation-{i}", f"Postgresql icon pack number {i}",
              "Free vector icons and symbols for your design projects.") for i in range(6)]
    calls = serve(monkeypatch, {"bing": Response(bing_page(decoy)),
                                "yahoo": Response(yahoo_page(GOOD))})
    monkeypatch.setattr(fs, "INDEX_DOORS", ("bing", "yahoo"))
    report = {}
    rows = fs._beyond_ddg(QUERY, max_items=8, cache=None, report=report, google=False)
    assert calls == ["bing", "yahoo"] and rows[0]["engine"] == "web-tls-yahoo"
    assert report["doors"][0]["status"] == "decoy" and discovery.door_resting("bing") > 0
    assert report["door"] == "yahoo"


def test_google_is_only_the_last_resort(monkeypatch):
    serve(monkeypatch, {"bing": Response("", 503), "yahoo": Response("", 503)})
    monkeypatch.setattr(fs, "INDEX_DOORS", ("bing", "yahoo"))
    monkeypatch.setattr(fs, "GOOGLE_LAST_RESORT", True)
    monkeypatch.setattr(fs, "BROWSER_SEARCH_URL", "http://worker")
    asked = []

    def browser(query, *, engines=None, diagnostics=None, **kwargs):
        asked.append(engines)
        diagnostics["status"] = "ok"
        return [{"url": "https://example.org/g", "title": "Google result for autovacuum",
                 "engine": "web-browser-google"}]
    monkeypatch.setattr(fs, "browser_search", browser)
    report = {}
    rows = fs._beyond_ddg(QUERY, max_items=8, cache=None, report=report)
    assert asked == [["google"]] and rows[0]["engine"] == "web-browser-google"
    assert [d["engine"] for d in report["doors"]] == ["tls-bing", "tls-yahoo", "browser-google"]


def test_ddg_success_never_reaches_the_other_doors(monkeypatch):
    monkeypatch.setenv("DETHROTTLED_CHEAP_DISCOVERY", "1")
    monkeypatch.setattr(fs, "tls_search", lambda *a, diagnostics, **k: (
        diagnostics.update(status="ok") or [{"url": "https://example.org/ddg",
                                             "title": "DuckDuckGo lite result",
                                             "engine": "web-tls-ddg-lite"}]))
    monkeypatch.setattr(fs, "_beyond_ddg", lambda *a, **k: pytest.fail("doors asked"))
    assert fs._acquire_web(QUERY)[0]["engine"] == "web-tls-ddg-lite"


def test_ddg_refusal_goes_to_the_doors_before_the_browser(monkeypatch):
    monkeypatch.setenv("DETHROTTLED_CHEAP_DISCOVERY", "1")
    monkeypatch.setattr(fs, "tls_search", lambda *a, diagnostics, **k: (
        diagnostics.update(status="challenge_or_http_error", refusal=True, http_status=202)
        or []))
    monkeypatch.setattr(fs, "browser_search", lambda *a, **k: pytest.fail("browser asked"))
    monkeypatch.setattr(fs, "_beyond_ddg", lambda *a, **k: [
        {"url": "https://example.org/bing", "title": "Bing door result here",
         "engine": "web-tls-bing"}])
    assert fs._acquire_web(QUERY)[0]["engine"] == "web-tls-bing"


def test_mwmbl_rows_from_its_keyless_api(monkeypatch):
    monkeypatch.setenv("DETHROTTLED_MWMBL", "1")

    class Json(Response):
        def json(self):
            return [{"url": "https://example.org/mw", "title": [
                {"value": "PostgreSQL", "is_bold": True}, {"value": " autovacuum tuning"}],
                "extract": [{"value": "Tune autovacuum."}]}]
    serve(monkeypatch, {"mwmbl": Json("")})
    rows = discovery.mwmbl_search(QUERY)
    assert rows == [{"title": "PostgreSQL autovacuum tuning", "url": "https://example.org/mw",
                     "snippet": "Tune autovacuum.", "engine": "mwmbl", "publishedDate": "",
                     "cached": False}]


def test_engines_lists_every_provider_and_drives_fetch_relevance():
    from dethrottled import consensus, signals
    row = {"url": "https://example.org/a", "title": "Example", "engine": "web-tls-ddg-lite",
           "discovery": [{"provider": "web"}, {"provider": "searxng:yandex"},
                         {"provider": "mwmbl"}]}
    consensus.annotate_consensus([row])
    assert row["engines"] == ["web-tls-ddg-lite", "mwmbl", "searxng:yandex"]
    assert row["engines_consensus"] == 3
    lone = {"url": "https://example.org/b", "engine": "web-tls-ddg-lite", "score": 1.0}
    assert signals.fetch_relevance(dict(row, score=1.0), max_score=10.0) != "low"
    assert signals.fetch_relevance(lone, max_score=10.0) == "low"


# --- Destination recovery for results listed without a usable link ----------

from dethrottled import dedupe  # noqa: E402

ITEM = {"rank": 5, "title": "PostgreSQL Logical Replication Setup: A Step-by-Step …",
        "snippet": "Set up logical replication.", "domain": "learnomate.org",
        "engine": "google", "reason": "google_goto_throttled"}
SAME = {"url": "https://www.learnomate.org/postgresql-logical-replication/",
        "title": "PostgreSQL Logical Replication Setup: A Step-by-Step Guide - Learnomate",
        "engine": "yandex"}


def test_match_needs_same_host_and_title_prefix():
    assert dedupe.match_destination(ITEM, [SAME]) is SAME
    other_host = dict(SAME, url="https://mirror.example/postgresql-logical-replication/")
    assert dedupe.match_destination(ITEM, [other_host]) is None
    other_title = dict(SAME, title="Learnomate courses and pricing")
    assert dedupe.match_destination(ITEM, [other_title]) is None


def test_two_different_urls_are_ambiguous_and_not_guessed():
    twin = dict(SAME, url="https://learnomate.org/blog/postgresql-logical-replication-v2/")
    assert dedupe.match_destination(ITEM, [SAME, twin]) is None
    copy = dict(SAME, url="https://learnomate.org/postgresql-logical-replication/")
    assert dedupe.match_destination(ITEM, [SAME, copy]) is SAME  # one page, two spellings


def test_recovery_joins_an_existing_row_and_labels_new_ones_as_inferred():
    merged = [dict(SAME, discovery=[{"provider": "yandex"}])]
    door_row = {"url": "https://kb.example.org/logical-replication-checklist",
                "title": "Logical replication checklist for PostgreSQL 18",
                "engine": "web-tls-bing"}
    report = {"unresolved": [ITEM, dict(ITEM, rank=6, title=door_row["title"],
                                        domain="kb.example.org"),
                             dict(ITEM, rank=7, title="Nothing else lists this page",
                                  domain="nowhere.example")],
              "doors": [{"engine": "tls-bing", "status": "no_matching_candidates",
                         "candidates": [door_row]}]}
    left = fs._recover_destinations(merged, report)
    assert merged[0]["discovery"][-1]["destination"] == {
        "method": "cross_engine_match", "inferred": True, "matched_from": "yandex"}
    added = merged[1]
    assert added["url"] == door_row["url"] and added["destination"]["inferred"]
    assert added["destination"]["matched_from"] == "web-tls-bing"
    assert [i["rank"] for i in left] == [7] and left[0]["reason"] == "google_goto_throttled"


def test_a_decoy_doors_urls_are_never_used():
    door_row = {"url": "https://kb.example.org/x", "title": ITEM["title"],
                "engine": "web-tls-bing"}
    report = {"unresolved": [dict(ITEM, domain="kb.example.org")],
              "doors": [{"engine": "tls-bing", "status": "decoy", "candidates": [door_row]}]}
    merged = []
    assert len(fs._recover_destinations(merged, report)) == 1 and merged == []


def test_a_door_keeps_off_topic_rows_only_as_candidates(monkeypatch):
    off = [("https://example.org/pricing", "Unrelated pricing page for widgets",
            "Prices and plans for the widget product line.")]
    serve(monkeypatch, {"bing": Response(bing_page(off))})
    monkeypatch.setattr(discovery, "constrained", lambda query, row: False)  # e.g. domain filter
    report = {}
    assert discovery.door_search("bing", QUERY, diagnostics=report) == []
    assert report["status"] == "no_matching_candidates"
    assert report["candidates"][0]["url"] == "https://example.org/pricing"


def test_worker_reads_the_breadcrumb_domain():
    import ast
    from pathlib import Path
    from urllib.parse import urlparse
    source = Path(__file__).resolve().parents[1] / "browser-search/service.py"
    tree = ast.parse(source.read_text())
    function = next(n for n in tree.body
                    if isinstance(n, ast.FunctionDef) and n.name == "_cite_host")
    scope = {"urlparse": urlparse}
    exec(compile(ast.Module(body=[function], type_ignores=[]), "<worker>", "exec"), scope)
    assert scope["_cite_host"]("https://www.learnomate.org \u203a PostgreSQL") == "learnomate.org"
    assert scope["_cite_host"]("2 years ago") == ""
    assert scope["_cite_host"]("") == ""


# --- 1.9.2: Yahoo beside DDG, visible supplements, bounded waits ------------

def _ddg(i):
    return {"url": f"https://example.org/page-{i}", "title": f"Autovacuum tuning page {i}",
            "snippet": "Tuning autovacuum thresholds in PostgreSQL databases.",
            "engine": "web-tls-ddg-lite"}


def test_yahoos_copy_lends_ddg_its_date_and_only_novel_rows_join(monkeypatch):
    monkeypatch.setattr(fs, "web_search", lambda *a, **k: [_ddg(i) for i in range(10)])
    monkeypatch.setattr(fs, "searxng", lambda *a, **k: [])
    monkeypatch.setattr(discovery, "mwmbl_search", lambda *a, **k: [])
    dated = [dict(_ddg(i), snippet="Oct 31, 2025 · Tuning autovacuum thresholds.",
                  engine="web-tls-yahoo") for i in range(5)]
    novel = [dict(_ddg(50), url="https://example.org/only-on-yahoo", engine="web-tls-yahoo")]
    monkeypatch.setattr(discovery, "door_search", lambda name, query, **k: dated + novel)
    rows, meta = fs.search(QUERY, max_items=15, profile="web")
    first = next(r for r in rows if r["url"] == _ddg(0)["url"])
    assert first["engine"] == "web-tls-ddg-lite" and "Oct 31, 2025" in (
        first.get("publishedDate") or first.get("date_hint", {}).get("value", "")
        or str(first.get("date_hint") or ""))
    assert [r["engine"] for r in rows].count("yahoo") == 1  # the novel row only
    assert rows[3]["engine"] == "yahoo"  # visible at small limits


def test_a_door_answering_for_ddg_is_not_capped_at_three(monkeypatch):
    rows = [dict(_ddg(i), engine="web-tls-yahoo") for i in range(7)]
    assert len(fs.bounded_results(rows, 10)) == 7


def test_a_slow_supplement_is_capped_not_waited_for(monkeypatch):
    import time as _time
    monkeypatch.setattr(fs, "SUPPLEMENT_WAIT_SECONDS", 0.2)
    monkeypatch.setattr(fs, "web_search", lambda *a, **k: [_ddg(i) for i in range(3)])
    monkeypatch.setattr(fs, "searxng", lambda *a, **k: _time.sleep(1.5) or [])
    monkeypatch.setattr(discovery, "mwmbl_search", lambda *a, **k: [])
    monkeypatch.setattr(discovery, "door_search", lambda *a, **k: [])
    started = _time.monotonic()
    rows, meta = fs.search(QUERY, max_items=8, profile="web")
    assert _time.monotonic() - started < 1.0 and meta["per_source"]["yandex"] == "capped"


def test_a_capped_supplement_does_not_degrade_the_search(monkeypatch):
    import time as _time
    monkeypatch.setattr(fs, "SUPPLEMENT_WAIT_SECONDS", 0.2)
    monkeypatch.setattr(fs, "web_search", lambda *a, diagnostics=None, **k: (
        diagnostics.update(status="ok") or [_ddg(i) for i in range(3)]))
    monkeypatch.setattr(fs, "searxng", lambda *a, diagnostics=None, **k: (
        diagnostics.update(status="ok") or [{"url": "https://example.org/y", "title":
                                            "Yandex result about autovacuum", "engine": "yandex"}]))
    monkeypatch.setattr(discovery, "mwmbl_search", lambda *a, diagnostics=None, **k: (
        diagnostics.update(status="ok") or []))
    monkeypatch.setattr(discovery, "door_search", lambda *a, **k: _time.sleep(1.0) or [])
    rows, meta = fs.search(QUERY, max_items=8, profile="web")
    assert meta["per_source"]["yahoo"] == "capped"
    assert meta["discovery"]["degraded"] is False


def test_fetch_accepts_url_for_one_page():
    from dethrottled.api_models import FetchBody
    assert FetchBody(url="https://example.org/a").urls == ["https://example.org/a"]
    assert FetchBody(urls=["https://example.org/a"]).urls == ["https://example.org/a"]


def test_one_engine_is_named_once():
    from dethrottled import consensus
    row = {"url": "https://example.org/a", "engine": "web-tls-yahoo",
           "discovery": [{"provider": "web"}, {"provider": "yahoo"},
                         {"provider": "searxng:yandex"}]}
    consensus.annotate_consensus([row])
    assert row["engines"] == ["web-tls-yahoo", "searxng:yandex"]
    assert row["engines_consensus"] == 2


def test_yahoos_date_element_is_the_provider_date(monkeypatch):
    plain = [(u, t, "How to tune autovacuum thresholds and cost limits.") for u, t, _ in GOOD]
    serve(monkeypatch, {"yahoo": Response(yahoo_page(plain, date="Oct 31, 2025"))})
    rows = discovery.door_search("yahoo", QUERY)
    assert rows[0]["publishedDate"] == "Oct 31, 2025"
    assert "Oct 31, 2025" not in rows[0]["snippet"]


def test_gateway_accepts_url_for_one_page():
    import ast
    from pathlib import Path
    source = (Path(__file__).resolve().parents[1] / "adapters/rest_gateway.py").read_text()
    assert "'urls': [payload['url']]" in source
    ast.parse(source)


def test_fast_waits_a_short_grace_for_yahoo(monkeypatch):
    import time as _time
    monkeypatch.setattr(fs, "FAST_GRACE_SECONDS", 0.3)
    monkeypatch.setattr(fs, "web_search", lambda *a, **k: [_ddg(i) for i in range(5)])
    dated = [dict(_ddg(i), publishedDate="Oct 31, 2025", engine="web-tls-yahoo")
             for i in range(5)]
    for delay, expect_dated in ((0.1, True), (0.8, False)):
        monkeypatch.setattr(discovery, "door_search",
                            lambda *a, delay=delay, **k: _time.sleep(delay) or dated)
        started = _time.monotonic()
        rows, meta = fs.search(QUERY, max_items=5, profile="fast")
        assert _time.monotonic() - started < 0.7
        assert bool(rows[0].get("publishedDate")) is expect_dated
