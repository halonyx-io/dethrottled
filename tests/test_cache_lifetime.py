"""How long a read may be served from cache follows what the read is.

14 Nov 2026: the Hacker News front page was served 2.5 days old, and walls or
teasers were cached for 21 days although their own label said they were not
the page.
"""
import time

import pytest
from test_fetch_internals import ARTICLE, tier

from dethrottled import fetch as f
from dethrottled.cache import DEFAULT_TTL, Cache, CacheView


@pytest.mark.parametrize("url, out, kind", [
    ("https://news.ycombinator.com/", {}, "hub"),
    ("https://www.bbc.com/news", {}, "hub"),
    ("https://www.bbc.com/news/articles/c4g0x1y2z3", {}, "stable"),
    ("https://en.wikipedia.org/wiki/Tarpit", {}, "stable"),
    ("https://example.com/", {"published": "2026-11-13"}, "stable"),
    ("https://www.theguardian.com/world/live/2026/nov/14/election", {}, "live"),
    ("https://news.example/story", {"page_metadata": {"types": ["LiveBlogPosting"]}}, "live"),
    ("https://example.com/feed.xml", {"content_type": "application/rss+xml"}, "feed"),
])
def test_volatility(url, out, kind):
    assert f.volatility({"content_type": "html", **out}, url) == kind


def test_limited_reads_are_cached_briefly_whatever_the_page():
    article = "https://example.com/a/long-article-slug-here"
    assert f.cache_lifetime({"quality": "ok"}, article) == DEFAULT_TTL["extract"]
    assert f.cache_lifetime({"quality": "thin"}, article) == f.CACHE_LIMITED_SECONDS
    gated = {"quality": "ok", "content_assessment": {"gate": "login"}}
    assert f.cache_lifetime(gated, article) == f.CACHE_LIMITED_SECONDS
    assert f.cache_lifetime({"quality": "thin", "content_type": "html"},
                            "https://example.com/") == f.CACHE_HUB_SECONDS


def test_an_expired_front_page_is_fetched_again(monkeypatch, tmp_path):
    monkeypatch.setattr(f, "_throttle", lambda domain: None)
    monkeypatch.setattr(f, "CRAWL4AI_URL", "")
    calls = []

    def direct(url, *a, **k):
        calls.append(url)
        return tier(html=ARTICLE)(url)
    monkeypatch.setattr(f, "_tier_direct", direct)
    view = CacheView(Cache(tmp_path / "cache.sqlite"))
    first = f.fetch_and_extract("https://front.example/", cache=view)
    again = f.fetch_and_extract("https://front.example/", cache=view)
    assert len(calls) == 1 and again.get("cached")
    assert again["cache_expires_at"]  # reports the short lifetime, not 21 days
    real = time.time
    monkeypatch.setattr(f.time, "time", lambda: real() + f.CACHE_HUB_SECONDS + 5)
    later = f.fetch_and_extract("https://front.example/", cache=view)
    assert len(calls) == 2 and not later.get("cached")
    assert first["ok"]
