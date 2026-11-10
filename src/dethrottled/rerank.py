"""Optional ONNX cross-encoder reranking.

A bi-encoder ranks by broad topical similarity. A cross-encoder reads the query
and candidate together, which is why the open-source search projects that use
one (Hound's ``ms-marco-MiniLM-L-6-v2`` is the reference point) report better
top-k ordering. This module is deliberately opt-in: the model is not in the base
image, the default stays lexical/source ranking, and an absent model is a no-op.

Set ``DETHROTTLED_RERANK_MODEL`` to a directory containing an ONNX model and
``tokenizer.json`` (a Transformers.js/Xenova or sentence-transformers export
works) and set ``DETHROTTLED_RERANK=1``. The model is loaded lazily and reused.

Two export shapes are supported:

* a headless cross-encoder that returns ``logits`` (BGE, GTE, Jina);
* an encoder-only export that returns ``last_hidden_state`` plus the
  sentence-transformers post-processing modules on disk (Ettin rerankers).
"""

from __future__ import annotations

import json
import os
import struct
import threading

_MODEL = None
_LOCK = threading.Lock()

# Common sentence-transformers / optimum exports. Prefer fp32, then the
# optimised O4 build, then the instruction-set-specific quantized files.
_ONNX_NAMES = ("model.onnx", "model_O4.onnx", "model_quint8_avx2.onnx",
               "model_qint8_avx2.onnx", "model_qint8_avx512.onnx",
               "model_qint8_avx512_vnni.onnx", "model_qint8_arm64.onnx")


def model_dir() -> str:
    return os.getenv("DETHROTTLED_RERANK_MODEL", "").strip()


def onnx_path() -> str:
    """Return the configured ONNX file, accepting the usual quantized names."""
    root = model_dir()
    if not root:
        return ""
    explicit = os.getenv("DETHROTTLED_RERANK_ONNX", "").strip()
    if explicit:
        return explicit if os.path.isabs(explicit) else os.path.join(root, explicit)
    for name in _ONNX_NAMES:
        candidate = os.path.join(root, name)
        if os.path.isfile(candidate):
            return candidate
    return os.path.join(root, _ONNX_NAMES[0])


def available() -> bool:
    return bool(model_dir()) and os.path.isfile(onnx_path()) and os.path.isfile(
        os.path.join(model_dir(), "tokenizer.json")
    )


def _read_safetensors(path: str, np):
    """Read a plain F32/F16 safetensors file without the optional dependency."""
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
    """Load sentence-transformers Dense/GELU/LayerNorm/Dense post-processing."""
    pooling = {}
    pooling_path = os.path.join(root, "1_Pooling", "config.json")
    if os.path.isfile(pooling_path):
        with open(pooling_path, encoding="utf-8") as source:
            pooling = json.load(source)
    dense2 = os.path.join(root, "2_Dense", "model.safetensors")
    norm = os.path.join(root, "3_LayerNorm", "model.safetensors")
    dense4 = os.path.join(root, "4_Dense", "model.safetensors")
    if not (os.path.isfile(dense2) and os.path.isfile(norm) and
            os.path.isfile(dense4)):
        return None
    try:
        first = _read_safetensors(dense2, np)
        layer_norm = _read_safetensors(norm, np)
        last = _read_safetensors(dense4, np)
        return {
            "pooling": (pooling.get("pooling_mode") or "cls").lower(),
            "w2": first["linear.weight"],
            "ln_weight": layer_norm["norm.weight"],
            "ln_bias": layer_norm["norm.bias"],
            "w4": last["linear.weight"],
            "b4": last["linear.bias"],
        }
    except (KeyError, OSError, ValueError):
        return None


def _gelu(np, values):
    """Exact GELU, matching torch.nn.GELU's default approximate='none'."""
    from math import erf, sqrt

    erf_vector = np.frompyfunc(erf, 1, 1)
    return 0.5 * values * (1.0 + erf_vector(values / sqrt(2.0)).astype(np.float32))


def _postprocess(np, hidden, head, mask=None):
    """Turn last_hidden_state into one logit per pair, as sentence-transformers does."""
    if head["pooling"] == "mean":
        if mask is None:
            pooled = hidden.mean(axis=1)
        else:
            weights = mask[:, :, None].astype(np.float32)
            pooled = (hidden * weights).sum(axis=1) / np.maximum(
                weights.sum(axis=1), 1.0)
    else:
        pooled = hidden[:, 0, :]
    values = pooled @ head["w2"].T
    values = _gelu(np, values)
    values = (values - values.mean(axis=1, keepdims=True)) / np.sqrt(
        values.var(axis=1, keepdims=True) + head["eps"])
    values = values * head["ln_weight"] + head["ln_bias"]
    logits = values @ head["w4"].T + head["b4"]
    return logits


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
        options.intra_op_num_threads = int(os.getenv("DETHROTTLED_RERANK_THREADS", "2"))
        options.log_severity_level = 3
        session = onnxruntime.InferenceSession(
            onnx_path(), options, providers=["CPUExecutionProvider"],
        )
        outputs = session.get_outputs()
        input_names = {item.name for item in session.get_inputs()}
        head = None
        # A 3-D output is the encoder's last_hidden_state, not a ready-made logit.
        if outputs and len(outputs[0].shape) == 3:
            head = _load_head(root, np)
            if head is not None:
                head["eps"] = float(config.get("layer_norm_eps", 1e-5))
        _MODEL = (np, tokenizer, session, input_names, head)
        return _MODEL


def score(query: str, documents: list) -> list:
    """Return one cross-encoder logit per document; higher is more relevant."""
    if not documents:
        return []
    np, tokenizer, session, inputs, head = _load()
    pairs = [(query or "", text or "") for text in documents]
    encoded = tokenizer.encode_batch(pairs)
    arrays = {
        "input_ids": np.asarray([row.ids for row in encoded], dtype=np.int64),
        "attention_mask": np.asarray([row.attention_mask for row in encoded],
                                     dtype=np.int64),
        "token_type_ids": np.asarray([row.type_ids for row in encoded], dtype=np.int64),
    }
    feed = {key: value for key, value in arrays.items() if key in inputs}
    output = session.run(None, feed)[0]
    if head is not None:
        output = _postprocess(np, output, head, arrays["attention_mask"])
    return [float(row[0]) for row in output]


def rerank_rows(rows: list, query: str, *, text_chars: int | None = None) -> list:
    """Sort rows by cross-encoder score; never raises on an unavailable model."""
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
    except Exception:
        return rows
    ranked = [dict(row, neural_score=round(value, 6))
              for row, value in zip(rows, scores)]
    ranked.sort(key=lambda row: -row["neural_score"])
    return ranked
