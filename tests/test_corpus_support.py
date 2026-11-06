"""Retrieval corroboration is explicit and never presented as answer verification."""

import pytest
from test_corpus_v2 import admit, finish
from test_corpus_v2 import store as store_fixture

from dethrottled.corpus_chunks import chunks, representative
from dethrottled.corpus_support import assess

store = store_fixture


def test_question_scaffolding_does_not_supply_query_anchors():
    row = {"title": "Laboratory", "text": "How this procedure is performed at the laboratory."}
    assert assess("How do black holes emit Hawking radiation?", row, {"e5"}) == "unconfirmed"
    assert assess("laboratory procedure", row, {"minilm"}) == "query_terms"
    assert assess("Which laboratory emits radiation?", row, {"minilm"}) == "unconfirmed"
    assert assess("laboratory", row, {"minilm"}) == "query_terms"


def test_marginal_single_model_match_is_rejected_but_remains_accessible(store, monkeypatch):
    from dethrottled import corpus_vectors

    admit(store, "Laboratory reagent handling and equipment maintenance procedures. " * 10)
    finish(store)
    identifier = store.db.execute("select id from passages limit 1").fetchone()[0]
    monkeypatch.setattr(
        corpus_vectors,
        "candidates",
        lambda _, model, *args: [(identifier, 0.773348, model)] if model != "minilm" else [],
    )
    query = "How do black holes emit Hawking radiation?"
    assert store.search(query, mode="semantic") == []
    broad = store.search(query, mode="semantic", support="broad")
    assert len(broad) == 1
    assert broad[0]["support_status"] == "unconfirmed"
    assert broad[0]["answer_support"] == "unverified"
    assert "single_model_match_without_query_anchors" in broad[0]["retrieval_warning"]
    with pytest.raises(ValueError, match="support policy"):
        store.search(query, support="anything")


def test_agreement_can_support_different_passages_from_same_source(store, monkeypatch):
    from dethrottled import corpus_vectors

    admit(store, "A useful maintenance paragraph describing laboratory equipment. " * 35)
    finish(store)
    identifiers = [r[0] for r in store.db.execute("select id from passages order by id limit 2")]
    assert len(identifiers) == 2
    monkeypatch.setattr(
        corpus_vectors,
        "candidates",
        lambda _, model, *args: [(identifiers[model != "minilm"], 0.9, model)],
    )
    hits = store.search("a paraphrase without literal overlap", mode="semantic")
    assert len(hits) == 2
    assert all(h["support_status"] == "model_agreement" for h in hits)
    assert all(h["answer_support"] == "unverified" for h in hits)


def test_models_on_different_sources_do_not_corroborate_each_other(store, monkeypatch):
    from dethrottled import corpus_vectors

    for suffix in ("first", "second"):
        admit(
            store,
            (suffix + " laboratory maintenance equipment procedures. ") * 20,
            url="https://example.org/" + suffix,
        )
        finish(store)
    identifiers = [
        r[0]
        for r in store.db.execute(
            "select min(id) from passages group by source_id order by min(id)"
        )
    ]
    monkeypatch.setattr(
        corpus_vectors,
        "candidates",
        lambda _, model, *args: [(identifiers[model != "minilm"], 0.9, model)],
    )
    assert not store.search("unrelated astronomy question", mode="semantic")


@pytest.mark.parametrize(
    "text",
    [
        "温室灌溉系统只在日出前运行。",
        "停電時には冷凍保管庫の扉を閉めたままにしてください。",
        "ควรเปลี่ยนไส้กรองน้ำทุกหกเดือน",
    ],
)
def test_unspaced_sentences_are_not_discarded_as_too_few_words(text):
    items = list(chunks(text))
    assert representative(items, 32) == items


def test_english_model_cannot_corroborate_unsupported_script_scores():
    row = {"title": "温室灌溉", "text": "温室灌溉系统只在日出前运行。"}
    assert assess("谁画了星夜？", row, {"minilm", "e5"}) == "unconfirmed"  # noqa: RUF001
    assert assess("温室灌溉", row, {"minilm", "e5"}) == "query_terms"


def test_model_failures_remain_visible_when_no_hits_are_returned(store, monkeypatch):
    from dethrottled import corpus, server

    def unavailable(*args, **kwargs):
        raise ImportError("semantic dependencies absent")

    monkeypatch.setattr(corpus, "embed", unavailable)
    hits = store.search("a question with no usable model", mode="semantic")
    assert not hits
    assert set(hits.retrieval_warnings) == {
        "minilm: ImportError",
        "e5-test: ImportError",
    }
    monkeypatch.setattr(server, "shared_corpus", lambda: store)
    result = server.corpus_search("a question with no usable model", mode="semantic")
    assert not result["results"]
    assert result["retrieval_warnings"] == hits.retrieval_warnings


def test_schema_one_rollback_reports_legacy_policy_and_no_broad_hint(monkeypatch):
    from dethrottled import server

    class Legacy:
        def search(self, *args, **kwargs):
            return []

    monkeypatch.setenv("DETHROTTLED_CORPUS_SCHEMA", "1")
    monkeypatch.setattr(server, "shared_corpus", lambda: Legacy())
    result = server.corpus_search("a query")
    assert result["support"] == "legacy"
    assert "Use support=broad" not in result["broader_retrieval"]
    assert not server.corpus_search("a query", support="broad")["ok"]


def test_candidate_diagnostics_do_not_filter_useful_paraphrases(store, monkeypatch):
    from dethrottled import corpus_vectors
    admit(store, 'The emergency exit marker is green. Follow the illuminated sign. ' * 10)
    finish(store)
    identifier = store.db.execute('select id from passages limit 1').fetchone()[0]
    monkeypatch.setattr(corpus_vectors, 'candidates',
                        lambda _, model, *args: [(identifier, 0.9, model)])
    hits = store.search('What hue indicates the escape route?', mode='semantic')
    assert hits and hits[0]['support_status'] == 'model_agreement'
    assert hits[0]['answer_support'] == 'unverified'
    anchors = hits[0]['query_anchors']
    assert anchors['unmatched_count'] > 0
    assert 'hue' in anchors['unmatched_terms']
    assert 'green' in hits[0]['text']


def test_related_candidate_does_not_claim_patent_coverage(store, monkeypatch):
    from dethrottled import corpus_vectors
    admit(store, 'The land survey shows boundary markers beside the river. ' * 10)
    finish(store)
    identifier = store.db.execute('select id from passages limit 1').fetchone()[0]
    monkeypatch.setattr(corpus_vectors, 'candidates',
                        lambda _, model, *args: [(identifier, 0.9, model)])
    assert store.search('land patent', mode='lexical') == []
    hits = store.search('land patent', mode='semantic')
    assert hits[0]['query_anchors']['unmatched_terms'] == ['patent']
    assert hits[0]['query_anchors']['scope'] == 'returned_passage_and_title'
    assert hits[0]['answer_support'] == 'unverified'


def test_literal_diagnostic_payload_is_bounded():
    from dethrottled.corpus_support import query_anchors
    query = ' '.join('term' + str(i) + 'x' * 100 for i in range(100))
    result = query_anchors(query, {'title': '', 'text': ''})
    assert result['unmatched_count'] == 100
    assert len(result['unmatched_terms']) == 12
    assert all(len(word) <= 64 for word in result['unmatched_terms'])
