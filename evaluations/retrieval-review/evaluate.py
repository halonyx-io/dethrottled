"""Offline release-image comparison; prints JSON, never uses production state.

Supply the same RFC PDF to both runs. Set PYTHONPATH empty for the immutable
1.6.0 image package, or /work/src for the candidate mounted at /work.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import resource
import tempfile
import time
from pathlib import Path


def norm(text):
    import unicodedata

    text = unicodedata.normalize("NFKC", text).lower()
    text = re.sub(r"-\n(?=[a-z])", "", text)
    return re.sub(r"\s+", " ", text).strip()


def pdf(path, mode):
    from dethrottled.formats import read_blob

    blob = Path(path).read_bytes()
    facts = [
        "a user agent may send a date header field in a request",
        "transparent content negotiation in http",
        "ought to respond with a 415",
    ]
    started, cpu = time.perf_counter(), time.process_time()
    text, meta = read_blob(blob, "pdf", 1000000, allow_ocr=False, options={"document_mode": mode})
    return {
        "fixture_sha256": hashlib.sha256(blob).hexdigest(),
        "mode": mode,
        "seconds": time.perf_counter() - started,
        "cpu_seconds": time.process_time() - cpu,
        "peak_rss_kib": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
        "content_chars": len(text),
        "read_pages": len(meta["pages"]),
        "total_pages": meta["total_pages"],
        "partial": meta["partial"],
        "next_page": meta["next_page"],
        "warnings": meta["warnings"],
        "facts": [{"text": fact, "found": norm(fact) in norm(text)} for fact in facts],
        "table_scan": meta.get("native_table_scan"),
        "native_tables": len(meta.get("native_pdf_tables", [])),
    }


SOURCES = {
    "exit": (
        "The emergency exit marker is green. Follow the illuminated sign to leave the building."
    ),
    "survey": (
        "The land survey marks a river boundary. "
        "Surveyors measure the field corners and record distances."
    ),
    "temperature": (
        "Keep the refrigerator between two and eight degrees Celsius. Close its door after use."
    ),
    "retention": "Search results expire after six hours. Corpus passages expire after ninety days.",
}
CASES = [
    ("known-exit", "What colour is the emergency exit marker?", ["exit"]),
    ("paraphrase-exit", "What hue indicates the escape route?", ["exit"]),
    (
        "known-temperature",
        "What temperature range should the refrigerator maintain?",
        ["temperature"],
    ),
    (
        "paraphrase-temperature",
        "How cold should medicines in refrigerated storage be kept?",
        ["temperature"],
    ),
    ("known-cache", "How long are search results cached?", ["retention"]),
    ("paraphrase-cache", "When does a stored discovery response expire?", ["retention"]),
    ("known-survey", "What boundary does the land survey mark?", ["survey"]),
    ("paraphrase-survey", "Which watercourse defines the field edge?", ["survey"]),
    ("absent-patent", "land patent", []),
    ("related-insufficient", "Who granted the 1726 land patent?", []),
    ("absent-exit-date", "When was the emergency exit marker installed?", []),
    ("absent-medication", "What medicine should treat pneumonia?", []),
]


def corpus():
    from dethrottled.corpus_v2 import CorpusV2
    from dethrottled.evidence import Documents

    with tempfile.TemporaryDirectory() as directory:
        docs = Documents(Path(directory) / "documents.sqlite")
        store = CorpusV2(
            Path(directory) / "corpus.sqlite", documents=docs, models=["minilm", "e5-review"]
        )
        for name, text in SOURCES.items():
            store.enqueue(
                "https://fixture.example/" + name, name, text * 4, {"corpus_visibility": "public"}
            )
            assert store.run_one()
        rows = []
        for identifier, query, relevant in CASES:
            for mode in ["lexical", "semantic", "hybrid"]:
                for support in ["standard", "broad"]:
                    started = time.perf_counter()
                    hits = store.search(query, mode=mode, support=support)
                    rows.append(
                        {
                            "id": identifier,
                            "query": query,
                            "mode": mode,
                            "support": support,
                            "seconds": time.perf_counter() - started,
                            "relevant_sources": relevant,
                            "hits": [
                                {
                                    "source": hit["url"].rsplit("/", 1)[-1],
                                    "support_status": hit["support_status"],
                                    "answer_support": hit["answer_support"],
                                    "query_anchors": hit.get("query_anchors"),
                                    "supports_predefined_task": hit["url"].rsplit("/", 1)[-1]
                                    in relevant,
                                }
                                for hit in hits
                            ],
                        }
                    )
        return {
            "sources": SOURCES,
            "cases": rows,
            "limitations": [
                "Small diagnostic fixture, not a retrieval-quality leaderboard.",
                (
                    "Refrigeration paraphrase omits medicine identity; "
                    "only temperature facts are labelled."
                ),
                "Manual labels apply to these fixed sources and tasks only.",
            ],
        }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("kind", choices=["pdf", "corpus"])
    parser.add_argument("--pdf", default="/tmp/rfc9110.pdf")
    parser.add_argument("--mode", choices=["auto", "native"], default="auto")
    parser.add_argument("--label", required=True)
    args = parser.parse_args()
    result = pdf(args.pdf, args.mode) if args.kind == "pdf" else corpus()
    print(json.dumps({"label": args.label, "architecture": os.uname().machine, **result}, indent=2))
