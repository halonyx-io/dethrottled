"""Refetches refresh the vector corpus without rebuilding it per request."""

import pytest

from dethrottled import corpus as c


def test_changed_page_replaces_text_and_cached_matrix(tmp_path, monkeypatch):
    pytest.importorskip("numpy")
    monkeypatch.setattr(c, "embed", lambda texts: [[float(len(x)), 1.0] for x in texts])
    corpus = c.Corpus(tmp_path / "corpus.sqlite")
    prefix = "National statistics office capacity report. " * 4
    old = prefix + "Fiscal year 2024: 100 megawatts."
    new = prefix + "Fiscal year 2025: 5120 megawatts."
    url = "https://example.org/report"

    assert corpus.add(url, "Report", old) == 1
    corpus.matrix()
    assert corpus.add(url, "Report", new) == 1
    assert corpus.add(url, "Report", new) == 0
    matrix, meta = corpus.matrix()
    assert len(matrix) == len(meta) == 1
    assert "2025" in meta[0]["text"]
    assert "2024" not in meta[0]["text"]


def test_shortened_page_removes_old_tail_passages(tmp_path, monkeypatch):
    pytest.importorskip("numpy")
    monkeypatch.setattr(c, "embed", lambda texts: [[float(len(x)), 1.0] for x in texts])
    corpus = c.Corpus(tmp_path / "corpus.sqlite")
    url = "https://example.org/report"
    assert corpus.add(url, "Report", "Long report text. " * 160) > 1
    corpus.matrix()
    corpus.add(url, "Report", "Short updated report. " * 8)
    assert corpus._db.execute("SELECT COUNT(*) FROM passages").fetchone()[0] == 1
    assert len(corpus.matrix()[1]) == 1


def test_shared_corpus_reuses_one_instance(tmp_path, monkeypatch):
    monkeypatch.setenv("DETHROTTLED_DATA_DIR", str(tmp_path))
    monkeypatch.setattr(c, "_SHARED_CORPUS", None)
    assert c.shared_corpus() is c.shared_corpus()


def test_other_sqlite_writer_invalidates_resident_matrix(tmp_path, monkeypatch):
    pytest.importorskip("numpy")
    monkeypatch.setattr(c, "embed", lambda texts: [[float(len(x)), 1.0] for x in texts])
    path = tmp_path / "corpus.sqlite"
    reader = c.Corpus(path)
    writer = c.Corpus(path)
    writer.add("https://example.org/one", "One", "First report. " * 20)
    assert len(reader.matrix()[1]) == 1
    writer.add("https://example.org/two", "Two", "Second report. " * 20)
    assert len(reader.matrix()[1]) == 2
