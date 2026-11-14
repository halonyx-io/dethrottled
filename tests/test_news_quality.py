"""News ordering and engine hygiene (1.8.9).

14 Nov 2026 on live 1.8.8: reuters.com/ dated 2005-09-10 ranked #3 for "news
headlines today", a Facebook post #5, and SearXNG's slowest answer set the
search's time.
"""
import time
from email.utils import formatdate
from types import SimpleNamespace

from dethrottled import engine_policy as ep
from dethrottled import search as fs


def days_ago(days):
    return formatdate(time.time() - days * 86400, usegmt=True)


def row(url, published=""):
    return {"url": url, "title": "t", "engine": "duckduckgo news", "publishedDate": published}


def test_news_tiers():
    assert ep.news_tier(row("https://news.example/2026/11/story", days_ago(1))) == 0
    assert ep.news_tier(row("https://news.example/2026/11/story")) == 1
    assert ep.news_tier(row("https://news.example/2026/11/story", days_ago(30))) == 2
    assert ep.news_tier(row("https://www.reuters.com/", "Sat, 10 Sep 2005 00:00:00 GMT")) == 3
    assert ep.news_tier(row("https://www.facebook.com/rappler/posts/123", days_ago(0))) == 3
    assert ep.news_tier(row("https://news.example/world")) == 3


def test_feed_engines_drop_front_pages(monkeypatch):
    rss = b"""<?xml version="1.0"?><rss version="2.0"><channel>
<item><title>Reuters | Breaking News - Reuters</title><link>https://news.google.com/rss/articles/HOME</link>
<pubDate>Sat, 10 Sep 2005 00:00:00 GMT</pubDate></item>
<item><title>Court ruling today - Reuters</title><link>https://news.google.com/rss/articles/STORY</link>
<pubDate>Fri, 13 Nov 2026 10:00:00 GMT</pubDate></item></channel></rss>"""
    monkeypatch.setattr(fs.requests, "get", lambda url, **k: SimpleNamespace(
        status_code=200, content=rss, text=rss.decode()))
    monkeypatch.setattr(fs, "_gnews_decode_one", lambda link, timeout, cache=None: (
        "https://www.reuters.com/" if link.endswith("HOME")
        else "https://www.reuters.com/legal/court-ruling-today-2026-11-13/"))
    report = {}
    rows = fs.google_news("court ruling", site="reuters.com", engine="reuters",
                          diagnostics=report)
    assert [r["url"] for r in rows] == ["https://www.reuters.com/legal/court-ruling-today-2026-11-13/"]
    assert report["landing_pages"] == 1


def test_searxng_news_call_is_time_capped(monkeypatch):
    sent = []
    monkeypatch.setattr(fs.requests, "get", lambda url, params=None, **k: (
        sent.append(dict(params or {})),
        SimpleNamespace(status_code=200, json=lambda: {"results": []}, headers={}))[1])
    monkeypatch.setattr(fs, "SEARXNG_URL", "http://searxng.invalid")
    fs.searxng("capped", engines="duckduckgo news", time_limit=1.5)
    assert sent[-1]["timeout_limit"] == 1.5
    fs.searxng("uncapped", engines="yandex")
    assert "timeout_limit" not in sent[-1]
    assert "bing news" not in fs.DEFAULT_ENGINES.split(",")


def test_bing_reports_feed_items_and_filtered(monkeypatch):
    rss = b"""<?xml version="1.0"?><rss version="2.0"><channel>
<item><title>Kept</title><link>https://news.example/2026/11/kept</link></item>
<item><title>Dropped</title><link>https://www.bing.com/news/apiclick</link></item></channel></rss>"""
    monkeypatch.setattr(fs.requests, "get", lambda url, **k: SimpleNamespace(
        status_code=200, content=rss, text=rss.decode()))
    report = {}
    rows = fs.bing_news("kept story", diagnostics=report)
    assert len(rows) == 1 and report["feed_items"] == 2 and report["filtered"] == 1


def test_news_menu_orders_fresh_undated_stale_then_fronts(monkeypatch):
    monkeypatch.setattr(fs, "web_search", lambda *a, **k: [
        {"title": "Front page of the news", "url": "https://paper.example/news",
         "engine": "web-browser-ddg-lite"},
        {"title": "Undated story on the news", "url": "https://paper.example/2026/a-news-story",
         "engine": "web-browser-ddg-lite"}])
    monkeypatch.setattr(fs, "bing_news", lambda *a, **k: [])
    monkeypatch.setattr(fs, "google_news_headlines", lambda *a, **k: [])
    monkeypatch.setattr(fs, "searxng", lambda *a, **k: [
        {"title": "Old news story", "url": "https://wire.example/2026/09/old-news",
         "engine": "duckduckgo news", "publishedDate": days_ago(40)},
        {"title": "Social news post", "url": "https://www.facebook.com/page/posts/1",
         "engine": "duckduckgo news", "publishedDate": days_ago(0)},
        {"title": "Fresh news story", "url": "https://wire.example/2026/11/fresh-news",
         "engine": "duckduckgo news", "publishedDate": days_ago(0)}])
    rows, _ = fs.search("news story", categories="news", max_items=8)
    assert [r["url"] for r in rows] == [
        "https://wire.example/2026/11/fresh-news",
        "https://paper.example/2026/a-news-story",
        "https://wire.example/2026/09/old-news",
        "https://www.facebook.com/page/posts/1",
        "https://paper.example/news"]


def test_one_site_cannot_fill_the_lead():
    rows = [row("https://www.reuters.com/world/story-%d" % i, days_ago(0)) for i in range(4)]
    rows += [row("https://apnews.com/article/story-a", days_ago(0)),
             row("https://www.bbc.com/news/articles/story-b", days_ago(1))]
    ordered = ep.news_order(rows)
    hosts = [r["url"].split("/")[2] for r in ordered]
    assert hosts[:4] == ["www.reuters.com", "www.reuters.com", "apnews.com", "www.bbc.com"]
    assert len(ordered) == len(rows)  # moved back, never removed


def test_ordering_is_reported():
    rows = [row("https://www.reuters.com/world/story-%d" % i, days_ago(0)) for i in range(3)]
    rows += [row("https://news.example/2026/old-story", days_ago(30)),
             row("https://www.facebook.com/p/posts/1", days_ago(0))]
    ordered, report = ep.news_order_report(rows)
    assert report == {"fresh": 3, "undated": 0, "stale": 1, "front_page_social_or_roundup": 1,
                      "per_site_limit": 2, "moved_by_site_limit": 1}
    assert len(ordered) == 5


def test_a_capped_engine_is_reported_and_not_rested(monkeypatch):
    payload = {"results": [], "unresponsive_engines": [["qwant news", "timeout"],
                                                        ["brave.news", "access denied"]]}
    monkeypatch.setattr(fs.requests, "get", lambda url, params=None, **k: SimpleNamespace(
        status_code=200, json=lambda: payload, headers={}))
    monkeypatch.setattr(fs, "SEARXNG_URL", "http://searxng.invalid")
    failures = []
    monkeypatch.setattr(fs, "_record_failure",
                        lambda name, reason, namespace="": failures.append(name))
    report = {}
    fs.searxng("capped two", engines="qwant news,brave.news", time_limit=1.5, diagnostics=report)
    assert report["status"] == "degraded" and report["capped"] == ["qwant news"]
    assert failures == ["brave.news"], "a missed time cap must not rest the engine"


def test_headline_roundups_go_last_but_real_stories_stay():
    def titled(title):
        return dict(row("https://news.example/2026/11/item", days_ago(0)), title=title)
    for title in ("School assembly news headlines today- November 14",
                  "Top 10 news stories of the week", "Today's top headlines",
                  "News headlines for 14th November 2026"):
        assert ep.news_tier(titled(title)) == 3, title
    for title in ("Mexico's headline inflation accelerates", "Fed signals rate pause",
                  "Briefing: A nationwide ground stop"):
        assert ep.news_tier(titled(title)) == 0, title


def test_searxngs_own_timeout_suspension_is_not_a_refusal(monkeypatch):
    """After a timeout SearXNG suspends the engine for a few seconds and
    reports "Suspended: timeout"; on live 1.8.9 that rested Qwant 30 min."""
    payload = {"results": [], "unresponsive_engines": [["qwant news", "Suspended: timeout"]]}
    monkeypatch.setattr(fs.requests, "get", lambda url, params=None, **k: SimpleNamespace(
        status_code=200, json=lambda: payload, headers={}))
    monkeypatch.setattr(fs, "SEARXNG_URL", "http://searxng.invalid")
    failures = []
    monkeypatch.setattr(fs, "_record_failure",
                        lambda name, reason, namespace="": failures.append(name))
    report = {}
    fs.searxng("suspended", engines="qwant news", time_limit=1.5, diagnostics=report)
    assert report["capped"] == ["qwant news"] and failures == []


def test_v2_search_returns_the_engine_order(monkeypatch):
    from fastapi.testclient import TestClient

    from dethrottled import server
    monkeypatch.setattr(fs, "web_search", lambda *a, **k: [])
    monkeypatch.setattr(fs, "bing_news", lambda *a, **k: [])
    monkeypatch.setattr(fs, "google_news_headlines", lambda *a, **k: [])
    monkeypatch.setattr(fs, "searxng", lambda *a, **k: [
        {"title": "Fresh market story", "url": "https://wire.example/2026/11/market-story",
         "engine": "duckduckgo news", "publishedDate": days_ago(0)}])
    body = TestClient(server.app).post("/v2/search", json={
        "query": "market story", "profile": "news", "limit": 3, "cache_mode": "bypass"}).json()
    order = body["engine_order"]
    assert order["profile"] == "news" and order["ordering"]["fresh"] == 1
    web = TestClient(server.app).post("/v2/search", json={
        "query": "market story", "profile": "web", "limit": 3, "cache_mode": "bypass"}).json()
    assert "engine_order" not in web
