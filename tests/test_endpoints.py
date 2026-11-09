"""The endpoint surface: two verbs, one combination, and the aliases.

The shape is a deliberate decision and worth pinning. There is no `/crawl`,
because rendering is a strategy for obtaining a page rather than something a
caller wants for its own sake -- a caller who picked the renderer by hand would
spend four seconds of Chromium on pages `direct` serves in two hundred
milliseconds. Forcing the question is the `render` parameter instead.

The aliases matter just as much: callers already exist that were written
against `/extract`, and a rename for tidiness would break them for nothing.
"""
import shutil

import pytest

fastapi_testclient = pytest.importorskip("fastapi.testclient")
TestClient = fastapi_testclient.TestClient

from dethrottled import server as srv  # noqa: E402

FAKE_ROWS = [
    {"url": "https://example.com/one", "title": "One", "snippet": "first",
     "publishedDate": "", "engine": "web-duckduckgo"},
]
FAKE_META = {"ok": True, "count": 1, "per_source": {"web": 1},
             "elapsed_ms": 5, "cost": "free"}


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setattr(srv.fs, "search",
                        lambda *a, **k: (list(FAKE_ROWS), dict(FAKE_META)))
    monkeypatch.setattr(srv, "index_fetched", lambda *a, **k: 0)

    def fake_fetch(url, **kw):
        row = {"ok": True, "text": "body text", "tier": "direct",
               "extractor": "trafilatura", "title": "T", "published": "",
               "chars": 9, "url": url, "reason": "", "cached": False,
               "content_type": "html", "_render": kw.get("allow_render")}
        if kw.get("keep_html"):
            row["html"] = "<html>source</html>"
        return row

    monkeypatch.setattr(srv.fetcher, "fetch_and_extract", fake_fetch)
    return TestClient(srv.app)


# ── the surface ──────────────────────────────────────────────────────────────

def test_there_is_no_crawl_endpoint():
    """Rendering is a parameter, not a route. If this ever starts passing as a
    404-not-found-because-someone-added-it, read the module docstring first."""
    paths = {r.path for r in srv.app.routes}
    assert "/crawl" not in paths
    assert {"/search", "/fetch", "/search-and-fetch"} <= paths


def test_extract_aliases_are_still_mounted():
    """Existing callers were written against these names."""
    paths = {r.path for r in srv.app.routes}
    assert "/extract" in paths
    assert "/search-and-extract" in paths


def test_capabilities_name_installed_readers_without_promising_video_access(client):
    read = client.get("/v2/capabilities").json()["read"]
    assert {"html", "csv", "tsv"} <= set(read["formats"])
    assert ("doc" in read["formats"]) == bool(shutil.which("antiword"))
    assert ("ppt" in read["formats"]) == bool(shutil.which("catppt"))
    assert isinstance(read["pdf_ocr_installed"], bool)
    assert isinstance(read["youtube_captions_configured"], bool)


def test_search_keeps_source_order_by_default_and_accepts_opt_in_bm25(client):
    default = client.post("/search", json={"query": "One", "limit": 1}).json()
    lexical = client.post("/search", json={"query": "One", "limit": 1,
                                            "rank": True}).json()
    assert default[0]["ranking"] == []
    assert lexical[0]["ranking"] == ["bm25"]


@pytest.mark.parametrize("path", ["/search", "/v2/search"])
def test_default_menu_and_expansion_reach_acquisition(client, monkeypatch, path):
    requested = []

    def source(query, **kwargs):
        requested.append(kwargs["max_items"])
        return ([dict(FAKE_ROWS[0], url=f"https://example.com/{i}",
                          engine="web-ddg-lite")
                 for i in range(25)], dict(FAKE_META))

    monkeypatch.setattr(srv.fs, "search", source)
    for body, count in [({}, 10), ({"limit": 15}, 10),
                        ({"num_results": 5}, 5), ({"max_items": 3}, 3)]:
        response = client.post(path, json={"query": "One", **body})
        assert response.status_code == 200
        rows = response.json()
        if path == "/v2/search":
            rows = rows["results"]
        assert len(rows) == count
        assert rows[0]["ranking"] == []
        expected = body.get("limit", body.get("num_results", body.get("max_items", 15)))
        assert requested[-1] == expected


@pytest.mark.parametrize("path", ["/fetch", "/extract"])
def test_fetch_and_its_alias_behave_identically(client, path):
    rows = client.post(path, json={"urls": ["https://example.com/a"]}).json()
    assert rows[0]["quality"] == "ok"
    assert rows[0]["content"] == "body text"


@pytest.mark.parametrize("path", ["/search-and-fetch", "/search-and-extract"])
def test_combined_and_its_alias_behave_identically(client, path):
    rows = client.post(path, json={"query": "anything", "num_results": 1}).json()
    assert rows and rows[0]["content"] == "body text"


# ── raw ──────────────────────────────────────────────────────────────────────

def test_raw_returns_the_source(client):
    rows = client.post("/fetch", json={"urls": ["https://example.com/a"],
                                       "raw": True}).json()
    assert rows[0]["html"] == "<html>source</html>"


def test_normal_fetch_omits_the_source(client):
    """The default response must not carry the page source: it is often twenty
    times the size of the text, and nobody asked for it."""
    rows = client.post("/fetch", json={"urls": ["https://example.com/a"]}).json()
    assert "html" not in rows[0]


# ── render control ───────────────────────────────────────────────────────────

def test_render_never_forbids_the_renderer(client):
    """`render` says what the ladder is ALLOWED to do, not what it must do."""
    captured = {}
    original = srv.fetcher.fetch_and_extract

    def spy(url, **kw):
        captured["allow_render"] = kw.get("allow_render")
        return original(url, **kw)

    srv.fetcher.fetch_and_extract = spy
    try:
        client.post("/fetch", json={"urls": ["https://example.com/a"],
                                    "render": "never"})
        assert captured["allow_render"] is False
        client.post("/fetch", json={"urls": ["https://example.com/a"]})
        assert captured["allow_render"] is True
    finally:
        srv.fetcher.fetch_and_extract = original


def test_capabilities_lists_the_web_engines(client):
    """"web search" is not one source, and a caller debugging an empty result
    wants to know which engines were even asked."""
    body = client.get("/v2/capabilities").json()
    assert any(name.startswith("web-") for name in body["search"])


def test_capabilities_lists_configured_browser_worker(client, monkeypatch):
    monkeypatch.setattr(srv.fs, "BROWSER_SEARCH_URL", "http://browser-search:19888")
    assert "browser-search" in client.get("/v2/capabilities").json()["search"]
    monkeypatch.setattr(srv.fs, "BROWSER_SEARCH_URL", "")
    assert "browser-search" not in client.get("/v2/capabilities").json()["search"]


def test_render_always_puts_the_renderer_first(client):
    """ exists for the page whose static HTML has SOME text but whose
    real content needs JavaScript -- there,  never asks the renderer."""
    seen = {}
    original = srv.fetcher.fetch_and_extract

    def spy(url, **kw):
        seen["render_first"] = kw.get("render_first")
        seen["allow_render"] = kw.get("allow_render")
        return original(url, **kw)

    srv.fetcher.fetch_and_extract = spy
    try:
        client.post("/fetch", json={"urls": ["https://example.com/a"],
                                    "render": "always"})
        assert seen == {"render_first": True, "allow_render": True}
        client.post("/fetch", json={"urls": ["https://example.com/a"],
                                    "render": "auto"})
        assert seen == {"render_first": False, "allow_render": True}
        client.post("/fetch", json={"urls": ["https://example.com/a"],
                                    "render": "never"})
        assert seen == {"render_first": False, "allow_render": False}
    finally:
        srv.fetcher.fetch_and_extract = original


# -- what real clients actually send -----------------------------------------

def test_search_accepts_language_and_forwards_it(monkeypatch):
    """`language` reaches the engine, rather than being accepted and dropped.

    It was neither for a while: the engine honoured it, the HTTP body did not
    offer it, and once unknown fields became a 422 every client that sent it
    broke outright. An OpenClaw plugin sends it on every native search.
    """
    seen = {}

    def fake_search(query, **kw):
        seen.update(kw)
        return list(FAKE_ROWS), dict(FAKE_META)

    monkeypatch.setattr(srv.fs, "search", fake_search)
    monkeypatch.setattr(srv, "index_fetched", lambda *a, **k: 0)
    c = TestClient(srv.app)

    assert c.post("/search", json={"query": "q", "language": "fr"}).status_code == 200
    assert seen.get("language") == "fr"


def test_news_search_uses_a_short_cache_ttl(monkeypatch):
    seen = {}

    def fake_search(query, **kw):
        seen.update(kw)
        return list(FAKE_ROWS), dict(FAKE_META)

    monkeypatch.setattr(srv.fs, "search", fake_search)
    c = TestClient(srv.app)
    assert c.post("/search", json={"query": "q", "categories": "news"}).status_code == 200
    assert seen["cache"].max_age == srv.NEWS_SEARCH_TTL
    seen.clear()
    assert c.post("/search", json={"query": "q", "profile": "news"}).status_code == 200
    assert seen["cache"].max_age == srv.NEWS_SEARCH_TTL


def test_news_search_respects_a_tighter_caller_max_age(monkeypatch):
    seen = {}

    def fake_search(query, **kw):
        seen.update(kw)
        return list(FAKE_ROWS), dict(FAKE_META)

    monkeypatch.setattr(srv.fs, "search", fake_search)
    c = TestClient(srv.app)
    assert c.post(
        "/search", json={"query": "q", "categories": "news", "max_age": 600}
    ).status_code == 200
    assert seen["cache"].max_age == 600


def test_general_search_keeps_its_requested_or_default_cache_ttl(monkeypatch):
    seen = {}

    def fake_search(query, **kw):
        seen.update(kw)
        return list(FAKE_ROWS), dict(FAKE_META)

    monkeypatch.setattr(srv.fs, "search", fake_search)
    c = TestClient(srv.app)
    assert c.post("/search", json={"query": "q", "max_age": 7200}).status_code == 200
    assert seen["cache"].max_age == 7200
    seen.clear()
    assert c.post("/search", json={"query": "q"}).status_code == 200
    assert seen["cache"].max_age is None


def test_absent_language_is_not_forwarded_as_empty(monkeypatch):
    """No language means no hint -- not an empty string to be interpreted."""
    seen = {}

    def fake_search(query, **kw):
        seen.update(kw)
        return list(FAKE_ROWS), dict(FAKE_META)

    monkeypatch.setattr(srv.fs, "search", fake_search)
    monkeypatch.setattr(srv, "index_fetched", lambda *a, **k: 0)
    c = TestClient(srv.app)

    assert c.post("/search", json={"query": "q"}).status_code == 200
    assert seen.get("language") is None


def test_the_openclaw_plugin_payload_is_accepted(client):
    """The exact body that plugin sends, field for field.

    Pinned as a whole rather than field by field because the failure was not
    any one field being wrong -- it was the combination a real caller sends
    going untested while each field looked defensible on its own.
    """
    body = {"query": "raspberry pi", "num_results": 5, "engines": "auto",
            "language": "en", "fresh": False, "profile": "fast"}
    assert client.post("/search", json=body).status_code == 200

    fetch_body = {"urls": ["https://example.com"], "max_chars": 3000,
                  "fresh": False, "profile": "fast"}
    assert client.post("/fetch", json=fetch_body).status_code == 200


def test_language_is_declared_because_it_is_honoured(client):
    """Declared fields are promises. This one is kept; engines/profile are not
    declared precisely because they are accepted and change nothing."""
    declared = client.get("/v2/capabilities").json()["optional_fields"]
    assert "language" in declared["search"]
    assert "engines" in declared["search"]
    assert "profile" in declared["search"]


def test_local_corpus_cannot_return_a_fifty_url_menu(client, monkeypatch):
    class Corpus:
        def search(self, query, **options):
            assert options['limit'] == 10
            return [{'url': f'https://example.com/{i}'} for i in range(50)]

    monkeypatch.setattr(srv, 'shared_corpus', Corpus)
    result = client.get('/corpus/search', params={'q': 'One', 'limit': 50})
    assert result.status_code == 200
    assert result.json()['count'] == 10


def test_search_exposes_date_source_and_freshness_metadata(monkeypatch):
    rows = [
        {"url": "https://github.com/a/b", "title": "Repo", "snippet": "one",
         "publishedDate": "2026-11-09", "engine": "web-ddg"},
        {"url": "https://news.example/a", "title": "Story", "snippet": "Updated 8 November 2026",
         "publishedDate": "", "engine": "bing-news"},
        {"url": "https://random.example/a", "title": "Other", "snippet": "undated",
         "publishedDate": "", "engine": "web-ddg"},
    ]
    monkeypatch.setattr(srv.fs, "search", lambda *a, **k: (rows, dict(FAKE_META)))
    c = TestClient(srv.app)
    result = c.post("/search", json={"query": "q"}).json()
    assert result[0]["date_source"] == "structured"
    assert result[1]["date_source"] == "snippet"
    assert result[1]["publishedDate"] == "8 November 2026"
    assert result[2]["date_source"] == "none"
    assert result[0]["source_type"] == "repo"
    assert result[0]["fetch_relevance"] == "high"
    assert result[0]["snippet_tokens"] > 0
    assert result[0]["dated_results"] == 2
    assert result[0]["freshness_note"] is None
    envelope = c.post("/v2/search", json={"query": "q"}).json()
    assert envelope["dated_results"] == 2
    assert envelope["freshness_note"] is None


def test_search_warns_when_most_results_are_undated(monkeypatch):
    rows = [{"url": "https://example.com/%d" % n, "title": "T", "snippet": "s",
             "publishedDate": "", "engine": "web-ddg"} for n in range(3)]
    monkeypatch.setattr(srv.fs, "search", lambda *a, **k: (rows, dict(FAKE_META)))
    result = TestClient(srv.app).post("/search", json={"query": "q"}).json()
    assert result[0]["dated_results"] == 0
    assert "Most results are undated" in result[0]["freshness_note"]
