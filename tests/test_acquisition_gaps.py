"""Regressions from the 12 Nov 2026 acquisition benchmark misses.

Each case reproduces a mechanism, not a live site: list retention, a thin
main-content pick beside a fuller extractor, silent clipping at the cache
limit, static application shells and page-supplied descriptions.
"""
from dethrottled import extract, fetch

FILLER = " ".join(f"Sentence {i} explains how the journal records each change." for i in range(40))


def page(body):
    return f"<html><head><title>Fixture</title></head><body><main>{body}</main></body></html>"


def test_list_items_survive_main_content_extraction():
    html = page(f"<h1>Write-Ahead Logging</h1><p>{FILLER}</p><p>Advantages include:</p>"
                "<ul><li>WAL is significantly faster in most scenarios.</li>"
                "<li>WAL provides more concurrency as readers do not block writers.</li></ul>"
                f"<p>But there are also disadvantages:</p><p>{FILLER}</p>")
    text = extract.extract(html, "https://fixture.example/wal", max_chars=100_000)["text"]
    assert "WAL is significantly faster in most scenarios." in text


def test_thin_trafilatura_pick_yields_to_a_fuller_extractor(monkeypatch):
    monkeypatch.setattr(extract, "_via_trafilatura",
                        lambda html, url: {"text": "Company Performance Metrics " * 18,
                                           "tier": "trafilatura", "title": "Profile"})
    fuller = "OpenAI was founded in 2015 and is headquartered in San Francisco. " * 60
    monkeypatch.setattr(extract, "_via_resiliparse",
                        lambda html, url: {"text": fuller, "tier": "resiliparse"})
    result = extract.extract(page(FILLER), "https://fixture.example/org", max_chars=100_000)
    assert result["tier"] == "resiliparse"
    assert "San Francisco" in result["text"]
    assert result["title"] == "Profile"
    assert result["completeness"]["assessment"] == "thin_primary_compared"
    assert result["completeness"]["selection_changed"] is True


def test_substantial_trafilatura_pick_is_kept(monkeypatch):
    monkeypatch.setattr(extract, "_via_trafilatura",
                        lambda html, url: {"text": FILLER, "tier": "trafilatura"})
    monkeypatch.setattr(extract, "_via_resiliparse",
                        lambda html, url: {"text": FILLER * 10, "tier": "resiliparse"})
    assert extract.extract(page(FILLER), "https://fixture.example/", max_chars=100_000)[
        "tier"] == "trafilatura"


def test_clipping_at_the_cache_limit_is_reported():
    result = extract.extract(page(f"<p>{FILLER}</p>" * 5), "https://fixture.example/book",
                             max_chars=1000)
    assert result["clipped"] is True
    assert len(result["text"]) <= 1000
    assert "extraction_cache_limit" in result["warnings"]
    whole = extract.extract(page(f"<p>{FILLER}</p>"), "https://fixture.example/", max_chars=100_000)
    assert whole["clipped"] is False and "extraction_cache_limit" not in whole["warnings"]


def test_static_shell_is_not_a_stopping_result():
    shell_html = "<html>" + "<script>var x=1;</script>" * 4000 + "<p>Live market data</p></html>"
    shell = {"chars": 1941, "content_type": "html"}
    assert fetch._looks_like_shell("tls", shell, shell_html)
    assert fetch._looks_like_shell("direct", shell, shell_html)
    # Rendering tiers and substantial or text-dense reads are not shells.
    assert not fetch._looks_like_shell("headed", shell, shell_html)
    assert not fetch._looks_like_shell("tls", {"chars": 5000, "content_type": "html"}, shell_html)
    assert not fetch._looks_like_shell("tls", shell, "<p>" + "x" * 3000 + "</p>")
    assert not fetch._looks_like_shell("tls", {"chars": 1941, "content_type": "pdf"}, shell_html)


def test_meta_descriptions_are_collected_and_deduplicated():
    html = ('<html><head><meta property="og:description" content="Executive strategy &amp; '
            'product advisor of @mastodon. Likes all things analog.">'
            '<meta name="description" content="Executive strategy &amp; product advisor of '
            '@mastodon. Likes all things analog.">'
            '<script type="application/ld+json">{"@type":"Person","description":'
            '"Official account for support questions and announcements."}</script>'
            '</head><body></body></html>')
    found = extract.meta_descriptions(html)
    assert found[0] == "Executive strategy & product advisor of @mastodon. Likes all things analog."
    assert "Official account for support questions and announcements." in found
    assert len(found) == 2


def test_thin_read_is_supplemented_with_page_description():
    html = ('<html><head><meta property="og:description" content="Likes all things analog '
            'and builds federated software."></head><body></body></html>')
    candidate = {"text": "Skip to main content Hotkey Mastodon", "chars": 36,
                 "content_type": "html", "extraction": {}, "warnings": []}
    fetch._supplement_thin(candidate, html)
    assert candidate["text"].startswith("Likes all things analog")
    assert candidate["chars"] == len(candidate["text"])
    assert candidate["extraction"]["metadata_supplement"] == 1
    assert "page_metadata_description_added" in candidate["warnings"]
    long_read = {"text": FILLER * 3, "chars": len(FILLER * 3), "content_type": "html",
                 "extraction": {}, "warnings": []}
    fetch._supplement_thin(long_read, html)
    assert "metadata_supplement" not in long_read["extraction"]


def test_metadata_supplement_does_not_hide_a_shell():
    html = ('<html><head><meta property="og:description" content="' + "Leading exchange. " * 40
            + '"></head><body>' + "<script>var x=1;</script>" * 4000 + "</body></html>")
    candidate = {"text": "Live market data " * 100, "chars": 1700, "content_type": "html",
                 "extraction": {}, "warnings": []}
    fetch._supplement_thin(candidate, html)
    assert candidate["chars"] > fetch.SHELL_MAX_TEXT
    assert fetch._looks_like_shell("tls", candidate, html)


def test_selectolax_reattaches_punctuation_after_inline_links():
    html = ("<html><body><p>When the user agent is to <a href='#a'>abort a parser</a>, "
            "it must run the following steps (in <code>order</code>).</p>"
            + "<p>" + FILLER + "</p></body></html>")
    text = extract._via_selectolax(html, "https://fixture.example/")["text"]
    assert "abort a parser, it must" in " ".join(text.split())
    assert "(in order)." in " ".join(text.split())


def test_title_block_identifiers_are_kept():
    html = ("<html><body><main><div class='page-title'><h1>guava</h1>"
            "<label><span>pkg:maven/com.google.guava/guava@33.4.0</span></label></div>"
            f"<article><p>{FILLER}</p><p>{FILLER}</p></article></main></body></html>")
    result = extract.extract(html, "https://fixture.example/artifact", max_chars=100_000)
    assert "pkg:maven/com.google.guava/guava@33.4.0" in result["text"]
    assert result["completeness"].get("title_block_added") is True


def test_large_heading_container_is_not_prepended():
    html = f"<html><body><h1>Title</h1><p>{FILLER}</p><p>{FILLER}</p></body></html>"
    assert extract._title_block(html) == ""


def test_crawl_tier_renders_public_targets_in_a_public_scope(monkeypatch, tmp_path):
    import pytest
    pytest.importorskip("jwt")
    from dethrottled import delegation, research
    monkeypatch.setenv("DETHROTTLED_DNB", "1")
    monkeypatch.setenv("DETHROTTLED_DNB_PRIVATE_KEY", str(tmp_path / "issuer.pem"))
    monkeypatch.setenv("DETHROTTLED_DNB_PUBLIC_KEY", str(tmp_path / "issuer.pub"))
    delegation.ensure_keys()
    sent = []

    class Response:
        status_code = 200

        def json(self):
            return {"results": [{"success": True, "status_code": 200, "markdown": FILLER}]}

    monkeypatch.setattr(fetch.requests, "post",
                        lambda url, json=None, headers=None, timeout=None:
                        (sent.append((json, headers)), Response())[1])
    monkeypatch.setattr(fetch, "CRAWL4AI_URL", "http://dnb")
    for public_target in (True, False):
        sent.clear()
        monkeypatch.setattr(research, "public_url", lambda url, p=public_target: p)
        fetch._crawl4ai_via_crawl("https://crates.io/crates/serde")
        body, headers = sent[0]
        claims = delegation.verify(headers["X-DNB-Delegation"], body,
                                   str(tmp_path / "issuer.pub"), path="/crawl")
        assert claims["public_only"] is public_target


def test_coverage_guard_compares_large_but_narrow_picks(monkeypatch):
    narrow = "Company Performance Metrics and links. " * 80          # ~3K, above the size guard
    monkeypatch.setattr(extract, "_via_trafilatura",
                        lambda html, url: {"text": narrow, "tier": "trafilatura"})
    monkeypatch.setattr(extract, "_visible_chars", lambda html: 60_000)
    fuller = "OpenAI was founded in 2015 and is headquartered in San Francisco. " * 200
    monkeypatch.setattr(extract, "_via_resiliparse",
                        lambda html, url: {"text": fuller, "tier": "resiliparse"})
    big = page("".join(f"<div><span>{FILLER}</span></div>" for _ in range(30)))
    result = extract.extract(big, "https://fixture.example/org", max_chars=1_000_000)
    assert result["tier"] == "resiliparse"


def test_coverage_guard_keeps_a_pick_with_reasonable_coverage(monkeypatch):
    article = "A normal article paragraph. " * 200                    # ~5.6K
    monkeypatch.setattr(extract, "_via_trafilatura",
                        lambda html, url: {"text": article, "tier": "trafilatura"})
    monkeypatch.setattr(extract, "_visible_chars", lambda html: 20_000)
    monkeypatch.setattr(extract, "_via_resiliparse",
                        lambda html, url: {"text": article * 5, "tier": "resiliparse"})
    assert extract.extract(page(FILLER), "https://fixture.example/a",
                           max_chars=1_000_000)["tier"] == "trafilatura"


def test_page_metadata_reads_declared_identity():
    html = ('<html><head><link rel="canonical" href="https://example.org/book">'
            '<meta property="og:type" content="book">'
            '<meta name="citation_doi" content="10.1000/xyz123">'
            '<meta name="description" content="A guide to write-ahead logging internals.">'
            '<script type="application/ld+json">{"@context":"https://schema.org","@graph":['
            '{"@type":"SoftwareApplication","softwareVersion":"3.46.1"},'
            '{"@type":"Product","sku":"WAL-001","gtin13":"9780000000001"}]}</script>'
            '</head><body><span itemprop="isbn">978-0-00-000000-2</span></body></html>')
    meta = extract.page_metadata(html)
    assert meta["canonical"] == "https://example.org/book"
    assert meta["identifiers"]["doi"] == "10.1000/xyz123"
    assert meta["identifiers"]["softwareVersion"] == "3.46.1"
    assert meta["identifiers"]["sku"] == "WAL-001"
    assert meta["identifiers"]["isbn"] == "978-0-00-000000-2"
    assert {"SoftwareApplication", "Product", "book"} <= set(meta["types"])
    assert meta["descriptions"] == ["A guide to write-ahead logging internals."]


def test_missing_declared_identifiers_are_kept_with_the_text():
    html = ('<html><head><script type="application/ld+json">{"@type":"SoftwareSourceCode",'
            '"identifier":"pkg:cargo/serde@1.0.229"}</script></head><body><main>'
            f'<p>{FILLER}</p><p>{FILLER}</p></main></body></html>')
    result = extract.extract(html, "https://fixture.example/crate", max_chars=1_000_000)
    assert "pkg:cargo/serde@1.0.229" in result["text"]
    assert result["completeness"]["identifiers_added"] == ["identifier"]
    assert result["page_metadata"]["identifiers"]["identifier"] == "pkg:cargo/serde@1.0.229"


def test_retained_budget_exceeds_the_response_limit():
    assert fetch.CACHE_CHARS >= 4_000_000
