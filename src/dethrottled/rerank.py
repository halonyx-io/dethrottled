"""Optional ONNX cross-encoder reranking.

A bi-encoder ranks by broad topical similarity. A cross-encoder reads the query
and candidate together, which is why the open-source search projects that use
one (Hound's ``ms-marco-MiniLM-L-6-v2`` is the reference point) report better
top-k ordering. This module is deliberately opt-in: the model is not in the base
image, the default stays lexical/source ranking, and an absent model is a no-op.

Set ``DETHROTTLED_RERANK_MODEL`` to a directory containing ``model.onnx`` and
``tokenizer.json`` (a Transformers.js/Xenova ONNX model works) and set
``DETHROTTLED_RERANK=1``. The model is loaded lazily and reused.
"""

from __future__ import annotations

import os
import threading

_MODEL = None
_LOCK = threading.Lock()


def model_dir() -> str:
    return os.getenv("DETHROTTLED_RERANK_MODEL", "").strip()


def available() -> bool:
    root = model_dir()
    return bool(root) and all(
        os.path.isfile(os.path.join(root, name))
        for name in ("model.onnx", "tokenizer.json")
    )


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
            config = __import__("json").load(source)
        tokenizer = Tokenizer.from_file(os.path.join(root, "tokenizer.json"))
        tokenizer.enable_truncation(max_length=512)
        pad_id = int(config.get("pad_token_id", 0))
        tokenizer.enable_padding(pad_id=pad_id,
                                 pad_token=tokenizer.id_to_token(pad_id) or "[PAD]")
        options = onnxruntime.SessionOptions()
        options.intra_op_num_threads = int(os.getenv("DETHROTTLED_RERANK_THREADS", "2"))
        options.log_severity_level = 3
        session = onnxruntime.InferenceSession(
            os.path.join(root, "model.onnx"), options,
            providers=["CPUExecutionProvider"],
        )
        _MODEL = (np, tokenizer, session, {i.name for i in session.get_inputs()})
        return _MODEL


def score(query: str, documents: list) -> list:
    """Return one cross-encoder logit per document; higher is more relevant."""
    if not documents:
        return []
    np, tokenizer, session, inputs = _load()
    pairs = [(query or "", text or "") for text in documents]
    encoded = tokenizer.encode_batch(pairs)
    arrays = {
        "input_ids": np.asarray([row.ids for row in encoded], dtype=np.int64),
        "attention_mask": np.asarray([row.attention_mask for row in encoded],
                                     dtype=np.int64),
        "token_type_ids": np.asarray([row.type_ids for row in encoded], dtype=np.int64),
    }
    feed = {key: value for key, value in arrays.items() if key in inputs}
    logits = session.run(None, feed)[0]
    return [float(row[0]) for row in logits]


def rerank_rows(rows: list, query: str, *, text_chars: int = 3000) -> list:
    """Sort rows by cross-encoder score; never raises on an unavailable model."""
    if not rows or not query or not available():
        return rows
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
