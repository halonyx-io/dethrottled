"""Corpus v2 lifecycle, coverage, privacy, crash recovery and retrieval gates."""

import pytest

from dethrottled.corpus_chunks import chunks, representative
from dethrottled.corpus_v2 import CorpusV2
from dethrottled.evidence import Documents


@pytest.fixture
def store(tmp_path, monkeypatch):
    pytest.importorskip("numpy", reason="mock embedding/vector gates require the semantic extra")
    from dethrottled import corpus

    docs = Documents(tmp_path / "evidence.sqlite")
    obj = CorpusV2(tmp_path / "v2.sqlite", documents=docs, models=["minilm", "e5-test"])
    monkeypatch.setattr(obj, "_token_chunks", lambda items: items)
    monkeypatch.setattr(corpus, "embed", lambda texts, **kwargs: [[1.0, 0.0, 0.0]] * len(texts))
    return obj


def admit(store, text, url="https://example.org/report", **meta):
    return store.enqueue(url, "Report", text, {"corpus_visibility": "public", **meta})


def finish(store):
    assert store.run_one()
    assert store.status()["jobs"].get("completed")


def test_deep_fact_full_lexical_and_offsets(store, monkeypatch):
    monkeypatch.setenv("DETHROTTLED_CORPUS_PAGE_PASSAGES", "2")
    text = (
        "\n\n".join(
            "## Section %d\n" % i + ("background content for topic %d. " % i) * 25
            for i in range(24)
        )
        + "\n\nDEEP-FACT-7349213: quantity is 47."
    )
    admit(store, text)
    finish(store)
    hits = store.search("DEEP-FACT-7349213", mode="lexical")
    assert hits and "quantity is 47" in hits[0]["text"]
    for hit in hits:
        assert text[hit["start"] : hit["end"]] == hit["text"]
    coverage = hits[0]["coverage"]
    assert coverage["harvested_chars"] == len(text) == coverage["lexical_chars"]
    assert coverage["embedded_chars"] < len(text)
    assert coverage["embedded_passages"] == {"minilm": 2, "e5-test": 2}
    assert store.db.execute("select count(*) from passages").fetchone()[0] > 4
    assert store.db.execute("select count(*) from embeddings").fetchone()[0] == 4


def test_unembedded_middle_is_lexically_retrievable(store, monkeypatch):
    monkeypatch.setenv("DETHROTTLED_CORPUS_PAGE_PASSAGES", "2")
    text = (
        "leading ordinary text. " * 100
        + "\n\nMIDDLE-FACT-1234567 quantity 89.\n\n"
        + "trailing ordinary text. " * 100
    )
    admit(store, text)
    finish(store)
    hit = store.search("MIDDLE-FACT-1234567", mode="lexical")[0]
    assert not store.db.execute(
        "select 1 from embeddings where passage_id=?", (hit["id"],)
    ).fetchone()
    assert hit["document_available"]


def test_privacy_and_namespaces(store):
    for meta in (
        {},
        {"corpus_visibility": "private"},
        {"corpus_visibility": "public", "authenticated": True},
        {"corpus_visibility": "public", "private": True},
    ):
        assert not store.enqueue("https://example.org/secret", "", "private text", meta)["accepted"]
    assert store.status()["active_sources"] == 0
    with pytest.raises(ValueError):
        admit(store, "secret", url="https://alice:secret@example.org/")


def test_atomic_update_and_vector_reuse(store, monkeypatch):
    from dethrottled import corpus

    calls = []
    monkeypatch.setattr(
        corpus,
        "embed",
        lambda texts, **kwargs: calls.extend(texts) or [[1.0, 0.0, 0.0]] * len(texts),
    )
    text = "A stable paragraph with useful technical material. " * 12 + "\n\nOld unique fact 47."
    admit(store, text)
    finish(store)
    before = len(calls)
    assert admit(store, text)["unchanged"]
    assert not store.run_one()
    assert len(calls) == before
    admit(store, text.replace("Old unique fact 47", "New unique fact 89"))
    assert store.search("47", mode="lexical")
    finish(store)
    assert not store.search("47", mode="lexical")
    assert store.search("89", mode="lexical")
    assert len(calls) - before == 2  # unchanged paragraph reused for both models
    assert store.status()["active_sources"] == 1


def test_stale_worker_cannot_publish(store):
    admit(store, "Initial stable fact with plenty of useful material. " * 10)
    old, lease = store._claim()
    admit(store, "Updated replacement fact with plenty of useful material. " * 10)
    with pytest.raises(InterruptedError):
        store._heartbeat(old["id"], lease)
    finish(store)
    assert store.search("replacement", mode="lexical")
    assert not store.search("Initial", mode="lexical")


def test_expired_job_lease_recovers_after_restart(store):
    admit(store, "Durable restart fact with plenty of useful material. " * 10)
    claimed = store._claim()
    assert claimed and not store.run_one()
    with store.db:
        store.db.execute("update index_jobs set expires=0")
    finish(store)
    assert store.search("restart", mode="lexical")


def test_failed_inference_leaves_previous_version_visible(store, monkeypatch):
    from dethrottled import corpus

    admit(store, "Original reliable fact for atomic promotion. " * 10)
    finish(store)
    admit(store, "Different updated fact requiring new embeddings. " * 10)

    def fail(*args, **kwargs):
        raise RuntimeError("test interruption")

    monkeypatch.setattr(corpus, "embed", fail)
    assert store.run_one()
    assert store.search("Original", mode="lexical")
    assert not store.search("Different", mode="lexical")
    assert store.status()["jobs"]["pending"] == 1


def test_lexical_domains_negatives_and_exact_identifiers(store):
    admit(store, "Reference ABCD-12345678 stable quantity 47 without animals. " * 5)
    finish(store)
    assert store.search("ABCD-12345678", mode="lexical")
    assert not store.search("ABCD-12345679", mode="lexical")
    assert not store.search("stable -animals", mode="lexical")
    assert store.search("stable", mode="lexical", domains=["example.org"])
    assert not store.search("stable", mode="lexical", domains=["ample.org"])


def test_source_pruning_keeps_models_consistent(store, monkeypatch):
    for i in range(3):
        admit(
            store,
            ("Source %d content with factual technical material. " % i) * 10,
            url="https://example.org/%d" % i,
        )
        finish(store)
    monkeypatch.setenv("DETHROTTLED_CORPUS_MAX_PASSAGES", "2")
    assert store.prune() >= 1
    assert all(row["passages"] <= 2 for row in store.stats().values())
    assert store.db.execute("pragma foreign_key_check").fetchall() == []
    assert not store.db.execute(
        "select 1 from passages p left join sources s on s.id=p.source_id where s.id is null"
    ).fetchall()


def test_retained_document_expiration_is_explicit(store):
    admit(store, "Retained fact with technical material for retrieval. " * 10)
    finish(store)
    with store.documents.db:
        store.documents.db.execute("update documents set expires=0")
    hits = store.search("Retained", mode="lexical")
    assert hits and hits[0]["document_available"] is False
    assert hits[0]["coverage"]["document_expires_at"] > 0


def test_migration_is_local_bounded_and_idempotent(store, tmp_path):
    from dethrottled.corpus_migrate import backfill

    legacy = Documents(tmp_path / "legacy.sqlite")
    legacy.put(
        "one",
        "https://example.org/a",
        "Public archived source fact. " * 20,
        {"corpus_visibility": "public"},
    )
    legacy.put("two", "https://example.org/b", "Unknown provenance must not leak.", {})
    legacy.put("three", "https://example.org/c", "Authenticated secret.", {"authenticated": True})
    first = backfill(store, tmp_path / "legacy.sqlite", limit=1)
    assert first["scanned"] == first["accepted"] == 1
    second = backfill(store, tmp_path / "legacy.sqlite", limit=10)
    assert second["unknown_visibility"] == second["private"] == 1
    assert backfill(store, tmp_path / "legacy.sqlite")["scanned"] == 0
    finish(store)
    assert store.search("archived", mode="lexical")


def test_distributed_selection_includes_tail_and_original_spans():
    text = "\n\n".join("## Page %d\n" % i + ("technical word %d " % i) * 80 for i in range(30))
    items = list(chunks(text))
    selected = representative(items, 5)
    assert len(selected) == 5
    assert selected[0] == items[0] and selected[-1] == items[-1]
    assert all(text[item.start : item.end] == item.text for item in items)


def test_schema_mismatch_rejected(store):
    with store.db:
        store.db.execute("update metadata set value='999' where key='schema'")
    with pytest.raises(ValueError, match="unsupported corpus schema"):
        CorpusV2(store.path, documents=store.documents)


def test_page_references_do_not_cross_heading_boundaries():
    text = "## Page 1\nFirst native page with relevant facts.\n\n## Page 2\nSecond OCR page."
    items = list(chunks(text))
    assert [item.page for item in items] == [1, 2]
    assert "Second" not in items[0].text and "First" not in items[1].text


def test_reindex_keeps_prior_index_until_replacement_is_complete(store):
    admit(store, "Active retained evidence available during reindexing. " * 10)
    finish(store)
    assert store.reindex(limit=1) == 1
    assert store.search("retained", mode="lexical")
    finish(store)
    assert store.search("retained", mode="lexical")


def test_unchanged_public_source_rebinds_document_namespace_and_repairs_150(store):
    text = "PUBLIC-FACT-7349213: the quantity is 47. " * 30
    url = "https://example.org/report"
    for namespace in ("caller-a", "caller-b"):
        document = store.documents.put(namespace, url, text, {"corpus_visibility": "public"})
        result = admit(store, text, document_id=document["document_id"],
                       _document_namespace=namespace)
        if namespace == "caller-a":
            finish(store)
        else:
            assert result["unchanged"]
            assert not store.run_one()
        assert store.status()["retained_documents"]["available"] == 1
        hit = store.search("PUBLIC-FACT-7349213", mode="lexical")[0]
        assert hit["document_available"]
        assert hit["document_id"] == document["document_id"]
    # Reproduce an existing 1.5.0 row, then exercise the startup repair.
    with store.db:
        store.db.execute("UPDATE sources SET namespace='caller-a'")
        store.db.execute("DELETE FROM metadata WHERE key='document_namespace_repair'")
    reopened = CorpusV2(store.path, documents=store.documents, models=store.models)
    try:
        assert reopened.status()["retained_documents"]["available"] == 1
        assert reopened.search("PUBLIC-FACT-7349213", mode="lexical")[0]["document_available"]
    finally:
        reopened.db.close()
