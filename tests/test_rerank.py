"""Optional Ettin reranking is inert without a model and explainable with one."""

import json
import math
import struct

import pytest

from dethrottled import rerank

MODULES = ("2_Dense/model.safetensors", "3_LayerNorm/model.safetensors",
           "4_Dense/model.safetensors")


def _write_safetensors(path, tensors):
    import numpy as np

    path.parent.mkdir(parents=True, exist_ok=True)
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


def _model_files(root):
    (root / "model.onnx").write_bytes(b"onnx")
    (root / "tokenizer.json").write_text("{}", encoding="utf-8")
    (root / "config.json").write_text('{"pad_token_id": 0}', encoding="utf-8")
    for name in MODULES:
        (root / name).parent.mkdir(parents=True, exist_ok=True)
        (root / name).write_bytes(b"")


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


def test_model_directory_is_model_onnx(tmp_path, monkeypatch):
    _model_files(tmp_path)
    monkeypatch.setenv("DETHROTTLED_RERANK_MODEL", str(tmp_path))
    assert rerank.available() is True
    assert rerank.onnx_path() == str(tmp_path / "model.onnx")


def test_available_requires_the_postprocessing_modules(tmp_path, monkeypatch):
    _model_files(tmp_path)
    monkeypatch.setenv("DETHROTTLED_RERANK_MODEL", str(tmp_path))
    (tmp_path / "3_LayerNorm/model.safetensors").unlink()
    assert rerank.available() is False


def test_safetensors_reader_parses_f32(tmp_path):
    np = pytest.importorskip("numpy")
    weights = np.arange(6, dtype=np.float32).reshape(2, 3)
    path = tmp_path / "module.safetensors"
    _write_safetensors(path, {"linear.weight": weights})
    parsed = rerank._read_safetensors(str(path), np)
    assert parsed["linear.weight"].shape == (2, 3)
    assert parsed["linear.weight"].tolist() == weights.tolist()


def test_ettin_output_is_cls_pooled_and_scored():
    np = pytest.importorskip("numpy")
    # CLS pooling takes token 0; the final Dense reads its first feature.
    head = {
        "w2": np.eye(3, dtype=np.float32),
        "ln_weight": np.ones(3, dtype=np.float32),
        "ln_bias": np.zeros(3, dtype=np.float32),
        "w4": np.asarray([[1.0, 0.0, 0.0]], dtype=np.float32),
        "b4": np.asarray([0.0], dtype=np.float32),
    }
    hidden = np.asarray([[[1.0, 2.0, 3.0], [8.0, 8.0, 8.0]],
                         [[2.0, 2.0, 3.0], [9.0, 9.0, 9.0]]], dtype=np.float32)
    scores = rerank._postprocess(np, hidden, head, 1e-5)
    assert scores.shape == (2, 1)
    assert scores[0, 0] < scores[1, 0]
    gelu = np.asarray([0.5 * value * (1.0 + math.erf(value / math.sqrt(2.0)))
                       for value in (1.0, 2.0, 3.0)], dtype=np.float32)
    expected = (gelu - gelu.mean()) / math.sqrt(gelu.var() + 1e-5)
    assert abs(float(scores[0, 0]) - float(expected[0])) < 1e-4
