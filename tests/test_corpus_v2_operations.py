"""Admission bounds, concurrent requests, inference scheduling and public reads."""

import threading
import time

from test_corpus_v2 import admit, finish
from test_corpus_v2 import store as store_fixture

from dethrottled.corpus_v2 import CorpusV2
from dethrottled.evidence import Documents

store = store_fixture


def test_full_queue_is_explicit_and_does_not_lose_existing_job(store, monkeypatch):
    monkeypatch.setenv("DETHROTTLED_CORPUS_QUEUE", "1")
    admit(store, "First pending useful technical material. " * 10)
    result = admit(
        store, "Second pending useful technical material. " * 10, url="https://example.org/second"
    )
    assert result["reason"] == "queue_full" and result["retryable"]
    finish(store)
    assert admit(
        store, "Second pending useful technical material. " * 10, url="https://example.org/second"
    )["accepted"]


def test_inference_does_not_hold_database_lock(store, monkeypatch):
    from dethrottled import corpus

    entered, release = threading.Event(), threading.Event()

    def slow(texts, **kwargs):
        entered.set()
        assert release.wait(3)
        return [[1.0, 0.0, 0.0]] * len(texts)

    monkeypatch.setattr(corpus, "embed", slow)
    admit(store, "Durable concurrent source of technical evidence. " * 10)
    thread = threading.Thread(target=store.run_one)
    thread.start()
    assert entered.wait(3)
    start = time.monotonic()
    assert store.status()["jobs"]["running"] == 1
    assert admit(
        store,
        "Second concurrent useful source of technical evidence. " * 10,
        url="https://example.org/second",
    )["accepted"]
    assert time.monotonic() - start < 0.5
    release.set()
    thread.join(3)
    assert not thread.is_alive()


def test_waiting_query_precedes_next_index_batch():
    from dethrottled.corpus_jobs import inference

    order, queued = [], threading.Event()

    def query():
        queued.set()
        with inference():
            order.append("query")

    def background():
        with inference(background=True):
            order.append("background")

    with inference(background=True):
        reader = threading.Thread(target=query)
        reader.start()
        assert queued.wait(1)
        # Wait for registration rather than relying on scheduling sleeps.
        from dethrottled import corpus_jobs

        deadline = time.monotonic() + 1
        while corpus_jobs._WAITING == 0 and time.monotonic() < deadline:
            time.sleep(0.001)
        writer = threading.Thread(target=background)
        writer.start()
    reader.join(1)
    writer.join(1)
    assert order == ["query", "background"]


def test_core_install_keeps_fts_when_models_are_absent(tmp_path, monkeypatch):
    from dethrottled import corpus

    def missing(*args, **kwargs):
        raise ImportError("semantic extra absent")

    monkeypatch.setattr(corpus, "_model", missing)
    obj = CorpusV2(tmp_path / "core.sqlite", documents=Documents(tmp_path / "docs.sqlite"))
    admit(obj, "CORE-FACT-1938461: this evidence remains searchable without models.")
    finish(obj)
    hit = obj.search("CORE-FACT-1938461", mode="lexical")[0]
    assert hit["coverage"]["embedded_passages"] == {"minilm": 0}
    assert "semantic_dependencies_or_weights_unavailable" in hit["coverage"]["omissions"]


def test_lexical_limit_is_distributed_and_omission_is_visible(store, monkeypatch):
    monkeypatch.setenv("DETHROTTLED_CORPUS_LEXICAL_CHARS", "1800")
    text = (
        "Beginning ordinary relevant material. " * 200
        + "\n\nTAIL-FACT-123456789: retained end material."
    )
    admit(store, text)
    finish(store)
    hit = store.search("TAIL-FACT-123456789", mode="lexical")[0]
    assert "lexical_budget" in hit["coverage"]["omissions"]
    assert hit["coverage"]["harvested_chars"] == len(text)
    assert hit["coverage"]["lexical_chars"] <= 1800


def test_library_and_ordinary_search_share_configured_instance(store, monkeypatch):
    from dethrottled import corpus, rank

    monkeypatch.setattr(corpus, "_SHARED_CORPUS", store)
    calls = []
    monkeypatch.setattr(
        store, "search", lambda query, **kwargs: calls.append(tuple(store.models)) or []
    )
    assert rank.add_corpus([], "technical evidence") == []
    assert calls == [("minilm", "e5-test")]


def test_public_document_fallback_never_reads_other_private_namespaces(tmp_path, monkeypatch):
    from dethrottled import server

    docs = Documents(tmp_path / "docs.sqlite")
    public = docs.put(
        "corpus-public", "https://example.org/public", "Public retained evidence.", {}
    )
    private = docs.put("alice", "https://example.org/private", "Private retained evidence.", {})
    monkeypatch.setattr(server, "_documents", docs)
    public_store = CorpusV2(tmp_path / "public.sqlite", documents=docs)
    monkeypatch.setattr(server, "shared_corpus", lambda: public_store)
    # The namespace name alone is not a sharing grant.
    assert server.retained_document("bob", public["document_id"]) is None
    public_store.enqueue(
        "https://example.org/public",
        "",
        "Public retained evidence.",
        {"corpus_visibility": "public"},
    )
    assert server.retained_document("bob", public["document_id"])["text"].startswith("Public")
    assert server.retained_document("bob", private["document_id"]) is None


def test_metadata_never_duplicates_source_text(store):
    text = "UNIQUE-SOURCE-TEXT " * 50
    store.enqueue(
        "https://example.org/a",
        "",
        text,
        {
            "corpus_visibility": "public",
            "content": text,
            "_index_text": text,
            "extraction": {"pages": [{"page": 1, "method": "ocr", "text": text}]},
        },
    )
    row = store.db.execute("select provenance from sources").fetchone()[0]
    assert "UNIQUE-SOURCE-TEXT" not in row
    metadata = store.documents.db.execute("select metadata from documents").fetchone()[0]
    assert "UNIQUE-SOURCE-TEXT" not in metadata
    assert "ocr" in metadata


def test_newest_unchanged_acquisition_cancels_pending_changed_version(store):
    text = "Original stable source with a verified fact. " * 10
    admit(store, text)
    finish(store)
    admit(store, "Superseded intervening change with different facts. " * 10)
    assert admit(store, text)["unchanged"]
    assert not store.run_one()
    assert store.search("Original", mode="lexical")
    assert not store.search("intervening", mode="lexical")


def test_expired_retained_document_fails_job_explicitly(store):
    admit(store, "Unavailable retained document with factual material. " * 10)
    with store.documents.db:
        store.documents.db.execute("update documents set expires=0")
    assert store.run_one()
    assert store.status()["jobs"]["failed"] == 1
    error = store.db.execute("select error from index_jobs").fetchone()[0]
    assert "missing_or_expired" in error


def test_retry_limit_preserves_negative_result(store, monkeypatch):
    def broken(*args, **kwargs):
        raise RuntimeError("reproducible index failure")

    monkeypatch.setattr(store, "_prepare", broken)
    admit(store, "A document whose indexing fails consistently. " * 10)
    for _ in range(3):
        assert store.run_one()
        with store.db:
            store.db.execute("update index_jobs set available=0")
    assert store.status()["jobs"]["failed"] == 1
    assert not store.run_one()
    assert (
        "reproducible index failure"
        in store.db.execute("select error from index_jobs").fetchone()[0]
    )


def test_ninety_day_retention_expires_sources_together(store, monkeypatch):
    monkeypatch.delenv("DETHROTTLED_CORPUS_RETENTION_DAYS", raising=False)
    for day in (89, 91):
        admit(
            store,
            ("Retained age %d source of factual evidence. " % day) * 10,
            url="https://example.org/age-%d" % day,
        )
        finish(store)
        with store.db:
            store.db.execute(
                "update sources set touched=? where url=?",
                (time.time() - day * 86400, "https://example.org/age-%d" % day),
            )
    assert store.status()["limits"]["retention_days"] == 90
    assert store.prune() == 1
    assert store.search("89", mode="lexical")
    assert not store.search("91", mode="lexical")
    assert all(row["pages"] == 1 for row in store.stats().values())


def test_matrix_cache_is_invalidated_by_external_atomic_promotion(store, monkeypatch):
    from dethrottled import corpus

    admit(store, "Old retained semantic fact with detailed engineering material. " * 10)
    finish(store)
    reader = CorpusV2(store.path, documents=store.documents, models=store.models)
    assert reader.search("engineering", mode="semantic")
    assert reader.status()["resident_vector_bytes"] > 0
    original = corpus.embed
    monkeypatch.setattr(
        corpus,
        "embed",
        lambda texts, **kw: (
            original(texts, **kw) if kw.get("query") else [[0.0, 1.0, 0.0]] * len(texts)
        ),
    )
    admit(store, "New unrelated semantic fact with a changed embedding direction. " * 10)
    finish(store)
    assert not reader.search("engineering", mode="semantic")


def test_hybrid_exact_and_semantic_have_explicit_model_provenance(store):
    admit(store, "HYBRID-FACT-123456: retained evidence of engineering procedures. " * 10)
    finish(store)
    hits = store.search("HYBRID-FACT-123456", mode="hybrid")
    assert hits and hits[0]["retrieval"] == "hybrid"
    assert "lexical" in hits[0]["model_scores"]
    assert "minilm" in hits[0]["model_scores"]
    assert "e5-test" in hits[0]["model_scores"]


def test_signed_urls_are_not_shared(store):
    import pytest

    with pytest.raises(ValueError, match="credential-bearing"):
        admit(store, "Signed private content.", url="https://example.org/a?access_token=not-real")


def test_migration_survives_document_rowid_reuse(store, tmp_path):
    from dethrottled.corpus_migrate import backfill

    legacy = Documents(tmp_path / "legacy-reuse.sqlite")
    legacy.put(
        "one",
        "https://example.org/first",
        "First public retained source.",
        {"corpus_visibility": "public"},
    )
    assert backfill(store, tmp_path / "legacy-reuse.sqlite")["accepted"] == 1
    with legacy.db:
        legacy.db.execute("delete from documents")
    legacy.put(
        "two",
        "https://example.org/second",
        "Second public retained source.",
        {"corpus_visibility": "public"},
    )
    # SQLite reused rowid 1; UUID-based progress must still see the new document.
    assert backfill(store, tmp_path / "legacy-reuse.sqlite")["accepted"] == 1


def test_migration_skips_obsolete_retained_versions(store, tmp_path):
    from dethrottled.corpus_migrate import backfill

    legacy = Documents(tmp_path / "legacy-versions.sqlite")
    for value in ("old", "new"):
        legacy.put(
            "one",
            "https://example.org/version",
            value + " public retained facts.",
            {"corpus_visibility": "public"},
        )
    result = backfill(store, tmp_path / "legacy-versions.sqlite")
    assert result["obsolete"] == result["accepted"] == 1
    finish(store)
    assert store.search("new", mode="lexical")
    assert not store.search("old", mode="lexical")


def test_cached_semantic_candidates_respect_source_diversity(store):
    for i in range(3):
        admit(
            store,
            ("source %d relevant technical evidence. " % i) * 400,
            url="https://example.org/%d" % i,
        )
        finish(store)
    hits = store.search("technical evidence", mode="semantic", limit=6, per_url=2)
    assert len(hits) == 6
    assert len({hit["url"] for hit in hits}) == 3


def test_streaming_fallback_and_cache_obey_memory_budget(store, monkeypatch):
    import numpy as np

    from dethrottled.corpus_vectors import candidates

    admit(store, "Budgeted semantic source of technical evidence. " * 10)
    finish(store)
    with store.db:
        passage = store.db.execute("select id from passages limit 1").fetchone()[0]
        # Declared vector count exceeds one MiB even though its source text is tiny.
        for index in range(1000):
            cur = store.db.execute(
                "insert into passages(source_id,start,end,text,digest,heading) "
                "select source_id,?,?,'extra','hash','' from passages where id=?",
                (10000 + index, 10001 + index, passage),
            )
            vector = np.zeros(384, dtype="float32")
            vector[0] = 1
            store.db.execute(
                "insert into embeddings values(?,?,?,?,?)",
                (cur.lastrowid, "minilm", 384, vector.tobytes(), store.revisions["minilm"]),
            )
    monkeypatch.setenv("DETHROTTLED_CORPUS_VECTOR_MIB", "1")
    q = np.zeros(384, dtype="float32")
    q[0] = 1
    hits = candidates(store, "minilm", q, 0.22, 5, lambda url: True, 2)
    assert len(hits) == 2
    assert store.status()["resident_vector_bytes"] == 0


def test_http_admission_reuses_retained_text_and_commits_before_response(store, monkeypatch):
    from dethrottled import corpus, server

    text = "A public retained HTTP extraction with verifiable facts. " * 50
    record = store.documents.put("agent-one", "https://example.org/http", text, {})
    row = {
        "url": "https://example.org/http",
        "quality": "ok",
        "corpus_visibility": "public",
        "content": "short display",
        "_index_text": text,
        **record,
    }
    monkeypatch.setattr(corpus, "_SHARED_CORPUS", store)
    monkeypatch.setattr(store, "start", lambda: None)
    server._queue_corpus([row], namespace="agent-one")
    assert row["corpus_indexing"]["accepted"]
    assert store.status()["jobs"]["pending"] == 1
    assert store.documents.db.execute("select count(*) from documents").fetchone()[0] == 1
    monkeypatch.setattr(server, "_documents", store.documents)
    monkeypatch.setattr(server, "shared_corpus", lambda: store)
    assert server.retained_document("agent-two", record["document_id"])["text"] == text
    finish(store)
    assert store.search("verifiable", mode="lexical")[0]["document_available"]


def test_whole_source_harvest_bound_rejects_without_prefix_indexing(store, monkeypatch):
    monkeypatch.setenv("DETHROTTLED_CORPUS_HARVEST_CHARS", "100")
    result = admit(store, "A" * 101)
    assert result["reason"] == "harvest_limit"
    assert store.status()["jobs"] == {}


def test_second_model_failure_never_publishes_partial_first_model(store, monkeypatch):
    from dethrottled import corpus

    def fail_second(texts, **kwargs):
        if kwargs.get("model_name") == "e5":
            raise RuntimeError("E5 unavailable during inference")
        return [[1.0, 0.0, 0.0]] * len(texts)

    monkeypatch.setattr(corpus, "embed", fail_second)
    admit(store, "Atomic dual-model source with no partially visible vectors. " * 20)
    assert store.run_one()
    assert not store.stats()
    assert not store.search("Atomic", mode="lexical")
    assert store.status()["jobs"]["pending"] == 1


def test_normal_shutdown_interruptions_do_not_consume_failure_budget(store, monkeypatch):
    admit(store, "Graceful shutdown evidence with enough technical context. " * 20)

    def interrupted(*args, **kwargs):
        raise InterruptedError("normal shutdown")

    monkeypatch.setattr(store, "_prepare", interrupted)
    for _ in range(5):
        assert store.run_one()
        with store.db:
            store.db.execute("update index_jobs set available=0")
    assert store.status()["jobs"]["pending"] == 1
    assert store.db.execute("select attempts from index_jobs").fetchone()[0] == 0


def test_cache_lifetimes_are_separate_from_corpus_retention(store):
    from dethrottled.cache import DEFAULT_TTL

    assert DEFAULT_TTL["search"] == 6 * 3600
    assert DEFAULT_TTL["extract"] == DEFAULT_TTL["fetch"] == 21 * 86400
    assert store.status()["limits"]["retention_days"] == 90


def test_passage_identifiers_are_not_recycled_after_pruning(store):
    admit(store, "Earlier source with a stable semantic identity. " * 10)
    finish(store)
    old_max = store.db.execute("select max(id) from passages").fetchone()[0]
    with store.db:
        store.db.execute("update sources set touched=0")
    store.prune()
    admit(
        store,
        "Later source with a different semantic identity. " * 10,
        url="https://example.org/later",
    )
    finish(store)
    assert store.db.execute("select min(id) from passages").fetchone()[0] > old_max


def test_expired_sources_are_unreadable_before_background_pruning(store):
    admit(store, "Expired evidence must not be returned between maintenance passes. " * 10)
    finish(store)
    assert store.search("Expired", mode="semantic")  # warm the matrix before ageing
    with store.db:
        store.db.execute("update sources set touched=?", (time.time() - 91 * 86400,))
    assert not store.search("Expired", mode="semantic")
    assert not store.search("Expired", mode="lexical")


def test_each_model_keeps_its_original_floor(store):
    from dethrottled.corpus import _pack

    admit(store, "Threshold calibration source of useful technical facts. " * 10)
    finish(store)
    with store.db:
        store.db.execute("update embeddings set vector=?", (_pack([0.6, 0.8, 0.0]),))
    hits = store.search("threshold", mode="semantic")
    assert hits
    assert set(hits[0]["model_scores"]) == {"minilm"}  # .6 clears .22, not E5's .77
    explicit = store.search("threshold", mode="semantic", floor=0.1)
    assert set(explicit[0]["model_scores"]) == {"minilm"}


def test_reindex_campaign_progresses_in_bounded_batches(store):
    for index in range(5):
        admit(
            store,
            ("Repair source %d with stable technical facts. " % index) * 10,
            url="https://example.org/repair-%d" % index,
        )
        finish(store)
    counts = []
    for _ in range(4):
        counts.append(store.reindex(limit=2))
        while store.run_one():
            pass
    assert counts == [2, 2, 1, 0]
    assert store.status()["active_sources"] == 5


def test_reindex_never_revokes_an_active_lease(store):
    admit(store, "Stable evidence remains active throughout repair. " * 10)
    finish(store)
    assert store.reindex() == 1
    source, lease = store._claim()
    with store.db:
        store.db.execute("delete from metadata where key='reindex_cursor'")
    assert store.reindex() == 0
    store._heartbeat(source["id"], lease)


def test_large_expiry_backlog_is_pruned_in_bounded_resumable_batches(store):
    import time

    for index in range(70):
        admit(
            store,
            "An independently retained expiry fixture with useful text. " * 8,
            url="https://example.org/expiry-%d" % index,
        )
        finish(store)
    with store.db:
        store.db.execute("update sources set touched=?", (time.time() - 91 * 86400,))
    assert store.prune() == 32
    assert store.maintenance_pending
    assert store.status()["active_sources"] == 38
    assert store.prune() == 32
    assert store.maintenance_pending
    assert store.prune() == 6
    assert not store.maintenance_pending
    assert store.status()["active_sources"] == 0
    assert store.db.execute("select count(*) from embeddings").fetchone()[0] == 0
    assert store.db.execute("select count(*) from passage_fts").fetchone()[0] == 0
    assert store.db.execute("pragma foreign_key_check").fetchall() == []


def test_four_lifetimes_expire_independently_without_extending_on_reads(store, tmp_path,
                                                                      monkeypatch):
    from dethrottled.cache import Cache

    clock = [1_800_000_000.0]
    monkeypatch.setattr(time, "time", lambda: clock[0])
    cache = Cache(tmp_path / "cache.sqlite")
    try:
        cache.put("search", "query", value=["source"])
        cache.put("extract", "https://example.org/report", value={"text": "cached extraction"})
        text = "CLOCK-FACT-7349213: independent retained evidence. " * 30
        admit(store, text)
        finish(store)
        expiry = clock[0] + 90 * 86400
        for age, search_alive, extraction_alive, document_alive, corpus_alive in [
            (0, True, True, True, True),
            (6 * 3600 + 1, False, True, True, True),
            (7 * 86400 + 1, False, True, False, True),
            (21 * 86400 + 1, False, False, False, True),
            (90 * 86400 + 1, False, False, False, False),
        ]:
            clock[0] = 1_800_000_000.0 + age
            assert (cache.get("search", "query") is not None) == search_alive
            assert (cache.get("extract", "https://example.org/report") is not None
                    ) == extraction_alive
            hits = store.search("CLOCK-FACT-7349213", mode="lexical")
            assert bool(hits) == corpus_alive
            if hits:
                assert hits[0]["document_available"] == document_alive
                assert hits[0]["corpus_expires_at"] == expiry
                assert text[hits[0]["start"]:hits[0]["end"]] == hits[0]["text"]
            if age == 7 * 86400 + 1:
                store.prune()  # Expired handle registry does not remove corpus evidence.
        assert store.prune() > 0
        assert store.status()["active_sources"] == 0
    finally:
        cache.close()


def test_new_admission_renews_corpus_and_document_clocks_without_reembedding(store, monkeypatch):
    clock = [1_800_000_000.0]
    monkeypatch.setattr(time, "time", lambda: clock[0])
    text = "RENEWAL-FACT-7349213: acquired public evidence. " * 30
    admit(store, text)
    finish(store)
    clock[0] += 89 * 86400
    assert not store.search("RENEWAL-FACT-7349213", mode="lexical")[0]["document_available"]
    assert admit(store, text)["unchanged"]
    assert not store.run_one()
    clock[0] += 2 * 86400  # Original 90-day clock has expired; the renewed one has not.
    hit = store.search("RENEWAL-FACT-7349213", mode="lexical")[0]
    assert hit["document_available"]
    assert hit["corpus_expires_at"] == 1_800_000_000.0 + 179 * 86400


def test_document_capacity_eviction_preserves_passages_and_reports_unavailability(store):
    store.documents.max_bytes = 2000
    text = "EVICTION-FACT-7349213: retained evidence. " * 30
    admit(store, text)
    finish(store)
    assert store.search("EVICTION-FACT-7349213", mode="lexical")[0]["document_available"]
    store.documents.put("other-caller", "https://example.org/other", "x" * 1300, {})
    hit = store.search("EVICTION-FACT-7349213", mode="lexical")[0]
    assert not hit["document_available"] and "retained evidence" in hit["text"]
    assert store.status()["retained_documents"]["unavailable"] == 1
