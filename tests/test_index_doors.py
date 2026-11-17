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


def yahoo_page(rows):
    items = "".join(
        f'<div class="dd algo algo-sr"><div class="compTitle"><a href="https://r.search.yahoo.com'
        f'/_ylt=x/RV=2/RE=1/RO=10/RU={u.replace(":", "%3a").replace("/", "%2f")}/RK=2/RS=y-">'
        f'<span>breadcrumb</span><h3><span>{t}</span></h3></a></div>'
        f'<div class="compText"><p>{s}</p></div></div>' for u, t, s in rows)
    return f"<html>{items}</html>"


GOOD = [(f"https://example.org/autovacuum-{i}", f"PostgreSQL autovacuum tuning guide {i}",
         "Oct 31, 2025 · How to tune autovacuum thresholds and cost limits in PostgreSQL.")
        for i in range(5)]


class Response:
    def __init__(self, text, status=200):
        self.text, self.status_code, self.headers = text, status, {}


@pytest.fixture(autouse=True)
def fresh_doors(monkeypatch):
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
    rows = fs._beyond_ddg(QUERY, max_items=8, cache=None, report=report)
    assert calls == ["bing", "yahoo"] and rows[0]["engine"] == "web-tls-yahoo"
    assert report["doors"][0]["status"] == "decoy" and discovery.door_resting("bing") > 0
    assert report["door"] == "yahoo"


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
