"""Optional neural reranking is inert without a model and explainable with one."""

import json
import math
import struct

import pytest

from dethrottled import rerank


def _write_safetensors(path, tensors):
    import numpy as np

    header = {}
    blobs = []
    offset = 0
    for name, array in tensors.items():
        data = np.asarray(array, dtype="<f4").tobytes()
        header[name] = {
            "dtype": "F32",
            "shape": list(np.shape(array)),
            "data_offsets": [offset, offset + len(data)],
        }
        offset += len(data)
        blobs.append(data)
    encoded = json.dumps(header).encode("utf-8")
    path.write_bytes(struct.pack("<Q", len(encoded)) + encoded + b"".join(blobs))


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


def test_onnx_path_accepts_the_ettin_quantized_filename(tmp_path, monkeypatch):
    (tmp_path / "model_quint8_avx2.onnx").write_bytes(b"onnx")
    (tmp_path / "tokenizer.json").write_text("{}", encoding="utf-8")
    monkeypatch.setenv("DETHROTTLED_RERANK_MODEL", str(tmp_path))
    monkeypatch.delenv("DETHROTTLED_RERANK_ONNX", raising=False)
    assert rerank.available() is True
    assert rerank.onnx_path().endswith("model_quint8_avx2.onnx")


def test_explicit_onnx_filename_wins(tmp_path, monkeypatch):
    (tmp_path / "model.onnx").write_bytes(b"a")
    (tmp_path / "model_full.onnx").write_bytes(b"b")
    (tmp_path / "tokenizer.json").write_text("{}", encoding="utf-8")
    monkeypatch.setenv("DETHROTTLED_RERANK_MODEL", str(tmp_path))
    monkeypatch.setenv("DETHROTTLED_RERANK_ONNX", "model_full.onnx")
    assert rerank.onnx_path().endswith("model_full.onnx")
    assert rerank.available() is True


def test_safetensors_reader_parses_f32(tmp_path):
    np = pytest.importorskip("numpy")
    weights = np.arange(6, dtype=np.float32).reshape(2, 3)
    path = tmp_path / "module.safetensors"
    _write_safetensors(path, {"linear.weight": weights})
    parsed = rerank._read_safetensors(str(path), np)
    assert parsed["linear.weight"].shape == (2, 3)
    assert parsed["linear.weight"].tolist() == weights.tolist()


def test_encoder_only_output_is_pooled_and_scored():
    np = pytest.importorskip("numpy")
    # CLS pooling takes token 0; the final Dense reads its first feature.
    head = {
        "pooling": "cls",
        "w2": np.eye(3, dtype=np.float32),
        "ln_weight": np.ones(3, dtype=np.float32),
        "ln_bias": np.zeros(3, dtype=np.float32),
        "w4": np.asarray([[1.0, 0.0, 0.0]], dtype=np.float32),
        "b4": np.asarray([0.0], dtype=np.float32),
        "eps": 1e-5,
    }
    hidden = np.asarray([[[1.0, 2.0, 3.0], [8.0, 8.0, 8.0]],
                         [[2.0, 2.0, 3.0], [9.0, 9.0, 9.0]]], dtype=np.float32)
    scores = rerank._postprocess(np, hidden, head)
    assert scores.shape == (2, 1)
    assert scores[0, 0] < scores[1, 0]
    gelu = np.asarray([0.5 * value * (1.0 + math.erf(value / math.sqrt(2.0)))
                       for value in (1.0, 2.0, 3.0)], dtype=np.float32)
    expected = (gelu - gelu.mean()) / math.sqrt(gelu.var() + 1e-5)
    assert abs(float(scores[0, 0]) - float(expected[0])) < 1e-4
