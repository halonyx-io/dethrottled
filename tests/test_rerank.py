"""Optional neural reranking is inert without a model and explainable with one."""

from dethrottled import rerank


def test_absent_model_is_a_no_op(monkeypatch):
    monkeypatch.delenv("DETHROTTLED_RERANK_MODEL", raising=False)
    rows = [{"url": "https://a.example", "title": "A"}]
    assert rerank.available() is False
    assert rerank.rerank_rows(rows, "q") == rows


def test_rerank_sorts_by_neural_score(monkeypatch):
    monkeypatch.setattr(rerank, "available", lambda: True)
    monkeypatch.setattr(rerank, "score", lambda query, docs: [0.2, 0.9])
    rows = [{"url": "https://a.example", "title": "A"},
            {"url": "https://b.example", "title": "B"}]
    ranked = rerank.rerank_rows(rows, "q")
    assert [row["url"] for row in ranked] == [
        "https://b.example", "https://a.example"]
    assert ranked[0]["neural_score"] == 0.9


def test_model_failure_preserves_the_original_order(monkeypatch):
    monkeypatch.setattr(rerank, "available", lambda: True)
    monkeypatch.setattr(rerank, "score", lambda query, docs: (_ for _ in ()).throw(RuntimeError()))
    rows = [{"url": "https://a.example"}, {"url": "https://b.example"}]
    assert rerank.rerank_rows(rows, "q") == rows
