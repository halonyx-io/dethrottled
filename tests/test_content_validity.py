"""Non-destructive pollution checks and evidence-aware recovery selection."""

import pytest

from dethrottled import fetch as f
from dethrottled.cache import Cache
from dethrottled.content import assess_content
from dethrottled.workflow import guidance

ERROR = "Something went wrong. Wait a moment and try again."
FACT = "The regional allocation for 2026 is 7341 tonnes. "
ARTICLE = FACT * 30


@pytest.mark.parametrize("text", [ERROR + " " + ARTICLE, ERROR.upper() + "\n" + ARTICLE,
                                 "Access denied. " + ARTICLE])
def test_leading_banner_is_reported_without_semantic_claims(text):
    result = assess_content(text)
    assert result["pollution"] == "suspected"
    assert result["completeness"] == "unknown"
    assert result["usable_content"] == "unverified"
    for span in result["spans"]:
        assert text[span["start"]:span["end"]] == span["quote"]
        assert span["offset_in"] == "full_extraction"


@pytest.mark.parametrize("text", [
    ARTICLE,
    'The application displayed "' + ERROR + '" during the incident. ' + ARTICLE,
    '"' + ERROR + '" is an example of a bad error message. ' + ARTICLE,
    "Something went wrong with the published allocation, so it was corrected. " + ARTICLE,
    "Access denied is a common error message. " + ARTICLE,
])
def test_ordinary_mentions_and_quoted_examples_are_not_pollution(text):
    assert assess_content(text)["pollution"] == "none_detected"


def test_html_banner_in_middle_has_exact_canonical_offsets():
    text = ARTICLE + ERROR + " " + FACT
    html = f'<article>{ARTICLE}</article><div role="alert">{ERROR}</div><p>{FACT}</p>'
    result = assess_content(text, html)
    assert result["spans"] == [dict(start=len(ARTICLE), end=len(ARTICLE) + len(ERROR),
        quote=ERROR, kind="error_banner", signal="source_ui_container",
        offset_in="full_extraction")]


@pytest.mark.parametrize("wrapper", ["pre", "code", "blockquote"])
def test_html_examples_are_not_ui_signals(wrapper):
    html = f'<{wrapper}><div role="alert">{ERROR}</div></{wrapper}>'
    assert assess_content(ARTICLE + ERROR, html)["pollution"] == "none_detected"
    assert assess_content(ERROR + ARTICLE, html)["pollution"] == "none_detected"


def test_banner_removed_by_extractor_is_not_reported_in_clean_text():
    assert assess_content(ARTICLE, f'<div role="alert">{ERROR}</div>')['spans'] == []


def test_structured_documents_are_not_classified_as_ui():
    assert assess_content(ERROR, structured=True)["pollution"] == "not_assessed"


@pytest.fixture
def tiers(monkeypatch):
    monkeypatch.setattr(f, "ENABLE_TLS", False)
    monkeypatch.setattr(f, "CRAWL4AI_URL", "http://renderer")
    monkeypatch.setattr(f, "CRAWL4AI_BUDGET", -1)
    monkeypatch.setenv("DETHROTTLED_BROWSER_SEARCH_URL", "http://browser")
    monkeypatch.setattr(f, "_tier_direct", lambda *a: ({"text": ERROR + " " + ARTICLE}, "", a[0]))
    monkeypatch.setattr(f, "_tier_crawl4ai", lambda u: ({}, "unavailable", u))
    monkeypatch.setattr(f, "_tier_headed", lambda u: ({}, "unavailable", u))
    f._tier_rest.clear()
    return monkeypatch


def test_pollution_automatically_reaches_browser_and_prefers_clean_content(tiers):
    tiers.setattr(f, "_tier_headed", lambda u: ({"text": ARTICLE}, "", u))
    result = f.fetch_and_extract("https://source.example/report")
    assert result["tier"] == "headed" and result["text"] == ARTICLE.strip()
    assert result["content_assessment"]["pollution"] == "none_detected"
    assert result["acquisition_attempts"][0]["outcome"] == "suspected_pollution"
    assert all(a["elapsed_ms"] >= 0 for a in result["acquisition_attempts"])


def test_failed_recovery_retains_original_evidence_and_warns_agents(tiers):
    result = f.fetch_and_extract("https://source.example/report")
    assert result["ok"] and result["quality"] == "suspect"
    assert result["text"] == (ERROR + " " + ARTICLE).strip()
    assert result["warnings"]
    row = dict(result, content=result["text"], document_id="document")
    workflow = guidance(row)
    assert workflow["state"] == "needs_inspection"
    assert workflow["answer_verified"] is False
    assert any(a["tool"] == "read_document" and a["arguments"]["offset"] == 0
               for a in workflow["next_actions"])


def test_thin_clean_fragment_does_not_discard_long_mixed_evidence(tiers):
    tiers.setattr(f, "_tier_crawl4ai", lambda u: ({"text": FACT * 6}, "", u))
    assert f.fetch_and_extract("https://source.example/report")["quality"] == "suspect"


def test_render_never_preserves_pollution_diagnostics_without_browser(tiers):
    tiers.setattr(f, "_tier_headed", lambda u: pytest.fail("render forbidden"))
    result = f.fetch_and_extract("https://source.example/report", allow_render=False)
    assert result["quality"] == "suspect"
    assert [a["tier"] for a in result["acquisition_attempts"]] == ["direct"]


def test_cache_and_clipping_preserve_full_extraction_spans(tiers, tmp_path):
    cache = Cache(tmp_path / "cache.sqlite")
    original = f.fetch_and_extract("https://source.example/report", cache=cache, max_chars=20)
    result = f.fetch_and_extract("https://source.example/report", cache=cache, max_chars=10)
    assert result["cached"] and result["quality"] == "suspect"
    assert result["content_assessment"] == original["content_assessment"]
    assert result["content_assessment"]["spans"][0]["end"] > len(result["text"])


def test_source_ui_metadata_survives_cache(tiers, tmp_path):
    text = ARTICLE + ERROR
    tiers.setattr(f, "_tier_direct", lambda *a: ({"text": text,
        "html": f'<article>{ARTICLE}</article><div role="alert">{ERROR}</div>'}, "", a[0]))
    cache = Cache(tmp_path / "cache.sqlite")
    first = f.fetch_and_extract("https://source.example/report", cache=cache)
    second = f.fetch_and_extract("https://source.example/report", cache=cache)
    assert first["quality"] == second["quality"] == "suspect"
    assert second["content_assessment"] == first["content_assessment"]


def test_public_row_and_retained_focus_preserve_assessment(tiers, tmp_path):
    from dethrottled import server
    from dethrottled.evidence import Documents

    store = Documents(tmp_path / "evidence.sqlite")
    tiers.setattr(server, "documents", lambda: store)
    tiers.setattr(server, "cache", lambda: Cache(tmp_path / "cache.sqlite"))
    row = server._extract_once("https://source.example/report", 20,
                               allow_render=False, evidence_namespace="test")
    assert row["quality"] == "suspect" and row["content_assessment"]["spans"]
    focused = server.read_document(server.DocumentReadBody(
        document_id=row["document_id"], evidence_namespace="test", focus="7341 tonnes"))
    assert focused["content_assessment"] == row["content_assessment"]
    assert focused["workflow"]["state"] == "needs_inspection"


def test_research_keeps_suspect_evidence_and_continues_to_clean_source(monkeypatch):
    from fastapi.testclient import TestClient

    from dethrottled import research, server

    monkeypatch.setattr(research, "public_url", lambda url: True)
    monkeypatch.setattr(server, "index_fetched", lambda rows: 0)
    monkeypatch.setattr(server, "_ranked", lambda body: (
        [{"url": "https://mixed.example/report", "title": "Mixed"},
         {"url": "https://clean.example/report", "title": "Clean"}],
        {"elapsed_ms": 1, "per_source": {"web": 2}}, 8))

    def read(url, *args, **kwargs):
        return dict(url=url, quality="suspect" if "mixed" in url else "ok",
                    content=ERROR + ARTICLE if "mixed" in url else ARTICLE,
                    warnings=["suspected_error_banner"] if "mixed" in url else [],
                    content_assessment=assess_content(ERROR + ARTICLE) if "mixed" in url else {})

    monkeypatch.setattr(server, "_extract_row", read)
    response = TestClient(server.app).post("/research", json={
        "question": "regional allocation tonnes", "max_sources": 1, "queries": ["allocation"]})
    assert response.status_code == 200
    result = response.json()
    assert result["sources"][0]["url"] == "https://clean.example/report"
    assert result["partial_sources"][0]["quality"] == "suspect"
    assert result["summary"]["partial"] == 1
    assert result["skipped"][0]["reason"] == "suspected_pollution"


@pytest.mark.parametrize("banner", [
    "A temporary problem occurred. Refresh this page.",
    "Une erreur est survenue. Veuillez réessayer.",
])
def test_observed_retry_banners_are_non_destructive_and_quote_aware(banner):
    text = banner + " " + ARTICLE
    result = assess_content(text)
    assert result["pollution"] == "suspected"
    assert result["spans"][0]["quote"] == banner
    assert result["unflagged_chars"] >= len(ARTICLE)
    assert assess_content('"' + banner + '" is an example. ' + ARTICLE)[
        "pollution"] == "none_detected"
    assert assess_content(text, '<pre>' + banner + '</pre>')['pollution'] == 'none_detected'
    assert assess_content(text, structured=True)['pollution'] == 'not_assessed'


def test_gate_pages_are_named_not_left_as_ok():
    from dethrottled.content import annotate_content

    cases = [
        ("Subscribe to continue",
         "Subscribe to continue. This article is available to subscribers."),
        ("Sign in", "Sign in. You must be signed in to continue."),
        ("Access Denied", "Access Denied. You do not have permission to view this page."),
        ("Service temporarily unavailable", "Maintenance in progress."),
    ]
    expected = ["paywall", "login", "access_denied", "maintenance"]
    for (title, text), gate in zip(cases, expected):
        row = {"title": title, "text": ARTICLE + " " + text, "warnings": []}
        annotate_content(row, structured=False)
        assert row["content_assessment"]["gate"] == gate
        assert row["quality"] == "thin"
        assert any(w.startswith("gate_page:" + gate) for w in row["warnings"])


def test_ordinary_article_with_a_sign_in_link_is_not_a_gate():
    from dethrottled.content import gate_kind

    assert gate_kind("How to sign in to your account",
                     ARTICLE + " Follow the sign-in link to continue.") == ""
    assert gate_kind("Region allocation report", ARTICLE + " Subscribe for updates.") == ""


def test_structured_documents_are_not_classified_as_web_gates():
    from dethrottled.content import annotate_content

    row = {"title": "Sign in", "text": ARTICLE + " Sign in. Password policy.", "warnings": []}
    annotate_content(row, structured=True)
    assert "gate" not in row["content_assessment"]
    assert row["warnings"] == []
