"""Google News and Reuters as real news engines (search.google_news).

SearXNG's scrapers for both fail from here (Google 403, Reuters DataDome 401);
Google News RSS works and its links decode through Google's own page.
"""
import json
from types import SimpleNamespace

from dethrottled import search as fs

RSS = b"""<?xml version="1.0"?><rss version="2.0"><channel><title>q</title>
<item><title>Starship flies again - The New York Times</title>
<link>https://news.google.com/rss/articles/CBMiAAA?oc=5</link>
<pubDate>Sat, 14 Nov 2026 03:06:59 GMT</pubDate>
<source url="https://www.nytimes.com">The New York Times</source></item>
<item><title>Undecodable story - Somewhere</title>
<link>https://news.google.com/rss/articles/CBMiBBB?oc=5</link>
<pubDate>Sat, 14 Nov 2026 02:00:00 GMT</pubDate></item>
</channel></rss>"""
PAGE = '<c-wiz><div jscontroller="x" data-n-a-sg="SIG" data-n-a-ts="1794600000"></div></c-wiz>'
DECODED = (')]}\'\n\n[["wrb.fr","Fbv4je","[\\"garturlres\\",\\"https://www.nytimes.com/2026/'
           '11/13/science/starship.html\\",1]",null,null,null,"generic"]]')


def network(monkeypatch, calls):
    def get(url, **kwargs):
        calls.append(("GET", url))
        if "/rss/search" in url:
            return SimpleNamespace(status_code=200, content=RSS, text=RSS.decode())
        if url.endswith("CBMiAAA"):
            return SimpleNamespace(status_code=200, text=PAGE)
        return SimpleNamespace(status_code=200, text="<html>no attributes</html>")

    def post(url, data=None, **kwargs):
        calls.append(("POST", url, json.loads(data["f.req"])))
        return SimpleNamespace(status_code=200, text=DECODED)
    monkeypatch.setattr(fs.requests, "get", get)
    monkeypatch.setattr(fs.requests, "post", post)


def test_links_decode_to_publisher_urls_with_dates_and_publishers(monkeypatch):
    calls, report = [], {}
    network(monkeypatch, calls)
    rows = fs.google_news("Starship", max_items=3, diagnostics=report)
    assert [r["url"] for r in rows] == ["https://www.nytimes.com/2026/11/13/science/starship.html"]
    row = rows[0]
    assert row["title"] == "Starship flies again" and row["publisher"] == "The New York Times"
    assert row["publishedDate"].startswith("Sat, 14 Nov 2026") and row["engine"] == "google-news"
    assert report["undecoded"] == 1 and report["count"] == 1
    request = next(c for c in calls if c[0] == "POST")[2][0][0]
    assert json.loads(request[1])[2:] == ["CBMiAAA", 1794600000, "SIG"]


def test_reuters_is_the_same_engine_limited_to_reuters(monkeypatch):
    calls = []
    network(monkeypatch, calls)
    rows = fs.google_news("Starship", max_items=3, site="reuters.com", engine="reuters")
    assert "site%3Areuters.com" in calls[0][1]
    assert rows and rows[0]["engine"] == "reuters"


def test_decoded_urls_are_cached(monkeypatch, tmp_path):
    from dethrottled.cache import Cache, CacheView
    view = CacheView(Cache(tmp_path / "c.sqlite"))
    calls = []
    network(monkeypatch, calls)
    assert fs._gnews_decode_one("https://news.google.com/rss/articles/CBMiAAA", 5, view)
    count = len(calls)
    assert fs._gnews_decode_one("https://news.google.com/rss/articles/CBMiAAA", 5, view)
    assert len(calls) == count


def test_searxng_never_gets_the_category_with_named_engines(monkeypatch):
    sent = []

    def get(url, params=None, **kwargs):
        sent.append(dict(params or {}))
        return SimpleNamespace(status_code=200, json=lambda: {"results": []}, headers={})
    monkeypatch.setattr(fs.requests, "get", get)
    monkeypatch.setattr(fs, "SEARXNG_URL", "http://searxng.invalid")
    fs.searxng("q-one", categories="news", engines="duckduckgo news,qwant news")
    assert sent and "categories" not in sent[-1]
    fs.searxng("q-two", categories="news", engines="")
    assert sent[-1].get("categories") == "news" or "engines" in sent[-1]


def test_news_profile_uses_the_engines_and_skips_bing_resolution(monkeypatch):
    monkeypatch.setattr(fs, "NEWS_FEEDS", {"google-news": "", "reuters": "reuters.com"})
    monkeypatch.setattr(fs, "web_search", lambda *a, **k: [])
    monkeypatch.setattr(fs, "bing_news", lambda *a, **k: [])
    monkeypatch.setattr(fs, "searxng", lambda *a, **k: [])
    monkeypatch.setattr(fs, "google_news_headlines",
                        lambda *a, **k: (_ for _ in ()).throw(AssertionError("fallback ran")))

    def engine(query, *, engine="google-news", **kwargs):
        return [{"title": "Story from %s" % engine, "engine": engine,
                 "url": "https://%s.example/2026/11/story" % engine,
                 "publishedDate": "Sat, 14 Nov 2026 03:00:00 GMT"}]
    monkeypatch.setattr(fs, "google_news", engine)
    rows, meta = fs.search("story news", categories="news", max_items=4)
    assert {r["engine"] for r in rows} == {"google-news", "reuters"}
    assert meta["per_source"]["gnews-resolved"] == "skipped_google_news_decoded"
