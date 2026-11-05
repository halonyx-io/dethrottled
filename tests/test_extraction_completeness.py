"""Selective extraction comparison must preserve facts without importing furniture."""
import pytest

from dethrottled import extract as fx
from dethrottled import fetch as fetcher


def document(*, split=False, furniture=False, aside=False):
    facts, sections = [], []
    for i in range(40):
        fact = f"Section {i} specifies a retention interval of {470 + i} days for record class {i}."
        facts.append(fact)
        sections.append(f"<section><h2>Record class {i}</h2><p>" +
            ("Implementations validate message boundaries and preserve complete transport records. "
             * (5 + i % 3)) + fact + "</p></section>")
    if split:
        body = "<article>" + "".join(sections[:5]) + "</article><main>" + (
            "".join(sections[5:])) + "</main>"
    elif aside:
        body = "<article>" + "".join(sections[:5]) + "</article><aside>" + (
            "".join(sections[5:])) + "</aside>"
    else:
        body = "<article>" + "".join(sections) + "</article>"
    if furniture:
        body += "<nav><p>" + "MENU-FURNITURE " * 10000 + "</p></nav>"
    return "<html><head><title>Record interoperability</title></head><body>" + (
        body) + "</body></html>", facts


@pytest.fixture(autouse=True)
def libraries():
    pytest.importorskip("selectolax")
    pytest.importorskip("trafilatura")


def test_real_split_document_recovers_early_middle_and_tail():
    pytest.importorskip("resiliparse")
    html, facts = document(split=True)
    result = fx.extract(html, max_chars=1000000)
    assert all(facts[i] in result["text"] for i in [0, 19, 39])
    assert result["completeness"]["assessment"] == "structural_samples"
    assert result["completeness"]["status"] == "unverified"
    assert result["completeness"]["missing_samples"] == 0


@pytest.mark.parametrize("furniture", [False, True])
def test_long_complete_article_does_not_run_alternatives(monkeypatch, furniture):
    html, facts = document(furniture=furniture)
    for name in ["_via_resiliparse", "_via_selectolax"]:
        monkeypatch.setattr(fx, name, lambda *a: pytest.fail("Unnecessary comparison"))
    result = fx.extract(html, max_chars=1000000)
    assert all(facts[i] in result["text"] for i in [0, 19, 39])
    assert "MENU-FURNITURE" not in result["text"]
    assert result["completeness"]["compared_extractors"] == ["trafilatura"]


def test_missing_samples_are_warned_when_alternatives_fail(monkeypatch):
    html, facts = document()
    original = " ".join(facts[:2]) + " " + "Original useful evidence. " * 25
    monkeypatch.setattr(fx, "_via_trafilatura", lambda *a: {
        "text": original, "tier": "trafilatura"})
    monkeypatch.setattr(fx, "_via_resiliparse", lambda *a: {})

    def failed(*a):
        raise RuntimeError("controlled extractor failure")

    monkeypatch.setattr(fx, "_via_selectolax", failed)
    result = fx.extract(html, max_chars=1000000)
    assert result["ok"] and facts[0] in result["text"]
    assert result["completeness"]["status"] == "suspected_incomplete"
    assert result["warnings"] == ["extraction_missing_structural_samples"]


def test_ambiguous_aside_is_not_promoted_to_article():
    html, facts = document(aside=True)
    result = fx.extract(html, max_chars=1000000)
    assert facts[0] in result["text"]
    assert facts[-1] not in result["text"]
    assert not result["completeness"].get("selection_changed")


def test_fetch_keeps_completeness_and_canonical_offsets(monkeypatch):
    pytest.importorskip("resiliparse")
    html, facts = document(split=True)
    monkeypatch.setattr(fetcher, "_tier_direct", lambda url, *a, **k: (
        {"html": html}, "", url))
    result = fetcher.fetch_and_extract("https://example.org/records", max_chars=1000000,
                                      allow_render=False)
    assert all(facts[i] in result["text"] for i in [0, 19, 39])
    assert result["extraction"]["completeness"]["assessment"] == "structural_samples"
    assert result["content_assessment"]["completeness"] == "unknown"
    # Every retained fact occurs in the canonical extraction, not appended snippets.
    for fact in (facts[i] for i in [0, 19, 39]):
        start = result["text"].index(fact)
        assert result["text"][start:start + len(fact)] == fact


def test_native_alternate_recovers_a_substantially_incomplete_first_result(monkeypatch):
    pytest.importorskip("resiliparse")
    html, facts = document()
    first = " ".join(facts[:5]) + " " + "Original useful transport evidence. " * 20
    monkeypatch.setattr(fx, "_via_trafilatura", lambda *a: {
        "text": first, "tier": "trafilatura", "title": "Record interoperability"})
    result = fx.extract(html, max_chars=1000000)
    assert all(facts[i] in result["text"] for i in [0, 19, 39])
    assert result["completeness"]["selection_changed"]


def test_related_prose_outside_primary_content_does_not_trigger_comparison(monkeypatch):
    html, facts = document()
    related = "<div class='related-stories'>" + "".join(
        f"<p>UNRELATED-{i}: " + "Unrelated recommended content and comments. " * 20 + "</p>"
        for i in range(40)) + "</div>"
    html = html.replace("</body>", related + "</body>")
    for name in ["_via_resiliparse", "_via_selectolax"]:
        monkeypatch.setattr(fx, name, lambda *a: pytest.fail("Do not promote related prose"))
    result = fx.extract(html, max_chars=1000000)
    assert facts[-1] in result["text"]
    assert result["completeness"]["compared_extractors"] == ["trafilatura"]


def test_suspected_incompleteness_requests_inspection_without_claiming_verified_gap():
    from dethrottled.workflow import guidance
    row = {"url": "https://example.org/report", "quality": "ok",
           "extraction": {"completeness": {"status": "suspected_incomplete"}}}
    result = guidance(row)
    assert result["state"] == "needs_inspection"
    assert result["source_complete"] is None
    assert not result["answer_verified"]
