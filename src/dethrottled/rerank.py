"""Optional Ettin 68M fp32 ONNX reranking.

The 68M Ettin export is encoder-only: `onnx/model.onnx` returns
``last_hidden_state``, not reranker logits. Its published sentence-transformers
head must be applied separately:

    Transformer -> CLS pooling
                -> Dense 512 + GELU
                -> LayerNorm 512
                -> Dense 1

This module loads the fp32 export and those post-processing modules from one
directory. It is deliberately opt-in: the model is not in the base image, the
default stays lexical/source ranking, and an absent model is a no-op.

Set ``DETHROTTLED_RERANK_MODEL`` to the directory produced by
``scripts/fetch-rerank-model.sh`` and set ``DETHROTTLED_RERANK=1``. The model is
loaded lazily and reused. The tested configuration is 512 tokens, title+text up
to 3,000 characters, the top 30 candidates and 8 ONNX threads.
"""

from __future__ import annotations

import json
import math
import os
import struct
import threading

_MODEL = None
_LOCK = threading.Lock()

_REQUIRED = (
    "model.onnx",
    "tokenizer.json",
    "config.json",
    "2_Dense/model.safetensors",
    "3_LayerNorm/model.safetensors",
    "4_Dense/model.safetensors",
)


def model_dir() -> str:
    return os.getenv("DETHROTTLED_RERANK_MODEL", "").strip()


def onnx_path() -> str:
    return os.path.join(model_dir(), "model.onnx")


def enabled() -> bool:
    return os.getenv("DETHROTTLED_RERANK", "0").strip().lower() in {"1", "true", "yes", "on"}


def available() -> bool:
    root = model_dir()
    return bool(root) and all(
        os.path.isfile(os.path.join(root, name)) for name in _REQUIRED
    )


def _read_safetensors(path: str, np):
    """Read a plain safetensors file without the optional dependency."""
    with open(path, "rb") as source:
        blob = source.read()
    if len(blob) < 9:
        raise ValueError("truncated safetensors header")
    header_len = struct.unpack("<Q", blob[:8])[0]
    header = json.loads(blob[8:8 + header_len])
    base = 8 + header_len
    out = {}
    for name, meta in header.items():
        if name == "__metadata__":
            continue
        dtype = meta.get("dtype", "F32")
        shape = tuple(int(value) for value in meta["shape"])
        start, end = (int(value) for value in meta["data_offsets"])
        raw = blob[base + start:base + end]
        if dtype == "F32":
            array = np.frombuffer(raw, dtype="<f4")
        elif dtype == "F16":
            array = np.frombuffer(raw, dtype="<f2").astype(np.float32)
        elif dtype == "BF16":
            array = (np.frombuffer(raw, dtype="<u2").astype(np.uint32) << 16).view(
                np.float32)
        else:
            raise ValueError("unsupported safetensors dtype %s" % dtype)
        out[name] = np.array(array, dtype=np.float32).reshape(shape)
    return out


def _load_head(root: str, np):
    """Load the Ettin Dense/GELU/LayerNorm/Dense post-processing modules."""
    first = _read_safetensors(os.path.join(root, "2_Dense", "model.safetensors"), np)
    layer_norm = _read_safetensors(
        os.path.join(root, "3_LayerNorm", "model.safetensors"), np)
    last = _read_safetensors(os.path.join(root, "4_Dense", "model.safetensors"), np)
    return {
        "w2": first["linear.weight"],
        "ln_weight": layer_norm["norm.weight"],
        "ln_bias": layer_norm["norm.bias"],
        "w4": last["linear.weight"],
        "b4": last["linear.bias"],
    }


def _gelu(np, values):
    """Exact GELU, matching torch.nn.GELU's default approximate='none'."""
    from math import erf, sqrt

    erf_vector = np.frompyfunc(erf, 1, 1)
    return 0.5 * values * (1.0 + erf_vector(values / sqrt(2.0)).astype(np.float32))


def _postprocess(np, hidden, head, eps):
    """Turn Ettin's last_hidden_state into one logit per pair."""
    values = hidden[:, 0, :] @ head["w2"].T
    values = _gelu(np, values)
    values = (values - values.mean(axis=1, keepdims=True)) / np.sqrt(
        values.var(axis=1, keepdims=True) + eps)
    values = values * head["ln_weight"] + head["ln_bias"]
    return values @ head["w4"].T + head["b4"]


def _load():
    global _MODEL
    if _MODEL is not None:
        return _MODEL
    with _LOCK:
        if _MODEL is not None:
            return _MODEL
        import numpy as np
        import onnxruntime
        from tokenizers import Tokenizer

        root = model_dir()
        with open(os.path.join(root, "config.json"), encoding="utf-8") as source:
            config = json.load(source)
        tokenizer = Tokenizer.from_file(os.path.join(root, "tokenizer.json"))
        requested = int(os.getenv("DETHROTTLED_RERANK_MAX_TOKENS", "512"))
        model_max = int(config.get("max_position_embeddings", requested) or requested)
        tokenizer.enable_truncation(max_length=max(8, min(requested, model_max)))
        pad_id = int(config.get("pad_token_id", 0))
        tokenizer.enable_padding(pad_id=pad_id,
                                 pad_token=tokenizer.id_to_token(pad_id) or "[PAD]")
        options = onnxruntime.SessionOptions()
        options.intra_op_num_threads = int(os.getenv("DETHROTTLED_RERANK_THREADS", "8"))
        options.log_severity_level = 3
        session = onnxruntime.InferenceSession(
            onnx_path(), options, providers=["CPUExecutionProvider"],
        )
        outputs = session.get_outputs()
        if not outputs or len(outputs[0].shape) != 3:
            raise RuntimeError("expected Ettin last_hidden_state output")
        head = _load_head(root, np)
        _MODEL = (np, tokenizer, session,
                  {item.name for item in session.get_inputs()}, head,
                  float(config.get("layer_norm_eps", 1e-5)))
        return _MODEL


def score(query: str, documents: list) -> list:
    """Return one Ettin logit per document; higher is more relevant."""
    if not documents:
        return []
    np, tokenizer, session, inputs, head, eps = _load()
    pairs = [(query or "", text or "") for text in documents]
    encoded = tokenizer.encode_batch(pairs)
    arrays = {
        "input_ids": np.asarray([row.ids for row in encoded], dtype=np.int64),
        "attention_mask": np.asarray([row.attention_mask for row in encoded],
                                     dtype=np.int64),
        "token_type_ids": np.asarray([row.type_ids for row in encoded], dtype=np.int64),
    }
    feed = {key: value for key, value in arrays.items() if key in inputs}
    hidden = session.run(None, feed)[0]
    return [float(row[0]) for row in _postprocess(np, hidden, head, eps)]


def rerank_rows(rows: list, query: str, *, text_chars: int | None = None) -> list:
    """Sort rows by Ettin score; never raises on an unavailable model."""
    if not rows or not query or not available():
        return rows
    if text_chars is None:
        text_chars = int(os.getenv("DETHROTTLED_RERANK_TEXT_CHARS", "3000"))
    texts = [
        (str(row.get("title") or "") + " " +
         str(row.get("text") or row.get("snippet") or "")[:text_chars]).strip()
        for row in rows
    ]
    try:
        scores = score(query, texts)
        if len(scores) != len(rows) or not all(math.isfinite(value) for value in scores):
            return rows
    except Exception:
        return rows
    ranked = [dict(row, neural_score=round(value, 6))
              for row, value in zip(rows, scores)]
    ranked.sort(key=lambda row: -row["neural_score"])
    return ranked
