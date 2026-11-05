#!/usr/bin/env python3
"""Isolated real-model v1/v2 replay. No web requests or production writes."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import resource
import statistics
import time
from pathlib import Path


def manifest():
    topics = [
        (
            "battery",
            "battery temperature controller",
            "Cooling starts at 47 degrees Celsius.",
            "47",
        ),
        (
            "water",
            "water purification membrane",
            "Replacement interval is 89 operating days.",
            "89",
        ),
        (
            "orbit",
            "satellite orbit correction",
            "Required velocity change is 23 metres per second.",
            "23",
        ),
        (
            "storage",
            "storage replication journal",
            "Journal checkpoint interval is 61 seconds.",
            "61",
        ),
        ("orchard", "orchard irrigation sensor", "Soil moisture threshold is 34 percent.", "34"),
        ("bridge", "bridge vibration monitor", "Structural alarm frequency is 73 hertz.", "73"),
    ]
    documents, questions = [], []
    for topic, title, fact, value in topics:
        sections = []
        for i in range(85):
            sections.append(
                "## Section %d\n" % i
                + (
                    "This section explains the %s subsystem at inspection station %d. "
                    "Operators record environmental observations and verify the maintenance log. "
                    "Installation requires stable mounting and checks before scheduled operation. "
                    "The reference procedure distinguishes normal readings from faults and records "
                    "each measurement with its timestamp and calibration history.\n" % (title, i)
                )
            )
        for offset, label in ((0, "FRONT"), (42, "MIDDLE"), (84, "TAIL")):
            identifier = "CORPUS-%s-%s-20261105" % (topic.upper(), label)
            sections[offset] += "\n%s: %s\n" % (identifier, fact)
            questions.append(
                {
                    "id": identifier,
                    "query": identifier,
                    "mode": "auto",
                    "facts": [identifier, value],
                    "url": "https://example.org/" + topic,
                }
            )
        documents.append(
            {"url": "https://example.org/" + topic, "title": title, "text": "\n\n".join(sections)}
        )
        questions.append(
            {
                "id": topic + "-paraphrase",
                "query": "What is the %s setting?" % title,
                "mode": "semantic",
                "facts": [fact],
                "url": "https://example.org/" + topic,
            }
        )
    for language, title, text, query, _answer in [
        (
            "fr",
            "Maintenance du compresseur",
            "La soupape du compresseur doit être remplacée après 730 heures de fonctionnement.",
            "When must the compressor valve be replaced?",
            "730",
        ),
        (
            "es",
            "Control de temperatura del horno",
            "La temperatura máxima de seguridad del horno es de 285 grados Celsius.",
            "What is the maximum safe oven temperature?",
            "285",
        ),
        (
            "de",
            "Wartung der Wasserpumpe",
            "Der Filter der Wasserpumpe muss alle 46 Tage gereinigt werden.",
            "How often should the water pump filter be cleaned?",
            "46",
        ),
    ]:
        documents.append(
            {"url": "https://example.org/" + language, "title": title, "text": (text + "\n\n") * 3}
        )
        questions.append(
            {
                "id": language,
                "query": query,
                "mode": "semantic",
                "facts": [text],
                "url": "https://example.org/" + language,
            }
        )
    for i in range(8):
        questions.append(
            {
                "id": "absent-%d" % i,
                "query": "ABSENT-UNKNOWN-%d-20261105" % i,
                "mode": "auto",
                "facts": [],
                "url": None,
            }
        )
    questions.extend(
        [
            {
                "id": "absent-semantic-1",
                "query": "Who won the Nobel Prize for literature in 1954?",
                "mode": "semantic",
                "facts": [],
                "url": None,
            },
            {
                "id": "absent-semantic-2",
                "query": "How do emperor penguins incubate their eggs?",
                "mode": "semantic",
                "facts": [],
                "url": None,
            },
        ]
    )
    return {"documents": documents, "questions": questions}


def percentile(values, fraction):
    return sorted(values)[max(0, int(len(values) * fraction + 0.999999) - 1)]


def heldout_manifest():
    cases = [
        (
            "chamber",
            "Emergency chamber purge",
            "The emergency chamber is purged with argon before the lid opens.",
            "Which gas purges the emergency chamber before opening?",
        ),
        (
            "spindle",
            "Spindle sensor insulation",
            "Use a zirconia sleeve to insulate the spindle sensor.",
            "Which material insulates the spindle sensor?",
        ),
        (
            "reagent",
            "Laboratory reagent handling",
            "Discard the reagent when its colour turns violet.",
            "What colour means the reagent should be discarded?",
        ),
        (
            "dispatch",
            "Dispatch ledger retention",
            "The dispatch ledger must retain the original customs declaration.",
            "Which customs document does the dispatch ledger retain?",
        ),
        (
            "battery-fr",
            "Nettoyage de la batterie",
            "La batterie de secours doit rester débranchée pendant le nettoyage.",
            "When cleaning, how should the backup battery be connected?",
        ),
        (
            "pump-ms",
            "Pemeriksaan pam",
            "Injap keselamatan mesti diperiksa sebelum pam dihidupkan.",
            "What must be inspected before starting the pump?",
        ),
    ]
    docs, questions = [], []
    for key, title, fact, query in cases:
        text = "\n\n".join(
            (
                "Section %d of %s describes the inspection procedure. " % (i, title)
                + "Record conditions, check the equipment and review the maintenance log. " * 4
            )
            for i in range(80)
        )
        code = "VALIDATION-%s-20261105" % key.upper()
        text += "\n\n" + code + ": " + fact
        url = "https://example.org/heldout/" + key
        docs.append({"url": url, "title": title, "text": text})
        questions.extend(
            [
                {
                    "id": key + "-exact",
                    "query": code,
                    "mode": "auto",
                    "facts": [code, fact],
                    "url": url,
                },
                {
                    "id": key + "-semantic",
                    "query": query,
                    "mode": "semantic",
                    "facts": [fact],
                    "url": url,
                },
            ]
        )
    for index, query in enumerate(
        (
            "ABSENT-HELDOUT-1234567",
            "ABSENT-HELDOUT-9876543",
            "How do black holes emit Hawking radiation?",
            "What medications treat seasonal allergic rhinitis?",
        )
    ):
        questions.append(
            {
                "id": "heldout-negative-%d" % index,
                "query": query,
                "mode": "auto",
                "facts": [],
                "url": None,
            }
        )
    return {"documents": docs, "questions": questions}


def run(variant, output, heldout=False):
    os.environ["DETHROTTLED_MULTILINGUAL_CORPUS"] = "1"
    os.environ.setdefault("DETHROTTLED_E5_REVISION", "614241f622f53c4eeff9890bdc4f31cfecc418b3")
    from dethrottled.corpus import DualCorpus
    from dethrottled.corpus_v2 import CorpusV2

    data = heldout_manifest() if heldout else manifest()
    store = DualCorpus() if variant == "v1" else CorpusV2()
    from dethrottled.evidence import Documents

    documents = Documents(Path(os.environ["DETHROTTLED_DATA_DIR"]) / "evidence.sqlite")
    enqueue_times, index_times, retention_times = [], [], []
    for doc in data["documents"]:
        start = time.perf_counter()
        record = documents.put(
            "benchmark-agent",
            doc["url"],
            doc["text"],
            {"corpus_visibility": "public", "title": doc["title"]},
        )
        retention_times.append((time.perf_counter() - start) * 1000)
        start = time.perf_counter()
        if variant == "v1":
            store.add(doc["url"], doc["title"], doc["text"][:4000])
        else:
            store.enqueue(
                doc["url"],
                doc["title"],
                doc["text"],
                {
                    "corpus_visibility": "public",
                    "document_id": record["document_id"],
                    "_document_namespace": "benchmark-agent",
                },
            )
        enqueue_times.append((time.perf_counter() - start) * 1000)
        if variant == "v2":
            start = time.perf_counter()
            if not store.run_one():
                raise RuntimeError("no index job")
            index_times.append((time.perf_counter() - start) * 1000)
    results = []
    for repeat in range(3):
        for question in data["questions"]:
            start = time.perf_counter()
            hits = store.search(question["query"], mode=question["mode"], limit=10)
            elapsed = (time.perf_counter() - start) * 1000
            ranks = [
                i
                for i, hit in enumerate(hits, 1)
                if question["facts"]
                and hit["url"] == question["url"]
                and all(fact.casefold() in hit["text"].casefold() for fact in question["facts"])
            ]
            results.append(
                {
                    "id": question["id"],
                    "repeat": repeat,
                    "mode": question["mode"],
                    "answer_rank": min(ranks) if ranks else None,
                    "hit_count": len(hits),
                    "elapsed_ms": round(elapsed, 3),
                    "negative": not question["facts"],
                    "hits": [
                        {
                            "url": hit["url"],
                            "score": hit.get("score"),
                            "text": hit["text"],
                            "start": hit.get("start"), "end": hit.get("end"),
                            "model_scores": hit.get("model_scores"),
                            "fact_retained": bool(question["facts"])
                            and hit["url"] == question["url"]
                            and all(
                                fact.casefold() in hit["text"].casefold()
                                for fact in question["facts"]
                            ),
                        }
                        for hit in hits
                    ],
                }
            )
    positives = [row for row in results if not row["negative"]]
    negatives = [row for row in results if row["negative"]]
    latency = [row["elapsed_ms"] for row in results]
    root = Path(os.environ["DETHROTTLED_DATA_DIR"])
    summary = {
        "variant": variant,
        "dataset": "heldout" if heldout else "development",
        "architecture": platform.machine(),
        "python": platform.python_version(),
        "questions": len(data["questions"]),
        "positive_questions": len(positives) // 3,
        "repeats": 3,
        "recall_at_5": sum(
            bool(row["answer_rank"] and row["answer_rank"] <= 5) for row in positives
        )
        / len(positives),
        "mrr_at_10": sum(1 / row["answer_rank"] if row["answer_rank"] else 0 for row in positives)
        / len(positives),
        "negative_queries_with_hits": sum(bool(row["hit_count"]) for row in negatives),
        "negative_trials": len(negatives),
        "latency_ms": {"p50": statistics.median(latency), "p95": percentile(latency, 0.95)},
        "retention_ms": retention_times,
        "host_load_average": os.getloadavg(),
        "enqueue_ms": {
            "p50": statistics.median(enqueue_times),
            "p95": percentile(enqueue_times, 0.95),
        },
        "index_ms": index_times,
        "peak_rss_kib": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
        "disk_bytes": {path.name: path.stat().st_size for path in root.iterdir() if path.is_file()},
        "stats": store.stats(),
        "index_status": store.status() if variant == "v2" else None,
        "manifest_sha256": hashlib.sha256(json.dumps(data, sort_keys=True).encode()).hexdigest(),
    }
    Path(output).write_text(json.dumps({"summary": summary, "queries": results}, indent=2) + "\n")
    print(json.dumps(summary), flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("variant", choices=["v1", "v2"])
    parser.add_argument("output")
    parser.add_argument("--heldout", action="store_true")
    args = parser.parse_args()
    run(args.variant, args.output, args.heldout)
