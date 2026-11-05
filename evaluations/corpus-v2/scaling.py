"""Vector/storage microbenchmark at the configured cap; excludes model inference."""

import argparse
import json
import os
import platform
import resource
import statistics
import time
from pathlib import Path

import numpy as np

from dethrottled import corpus
from dethrottled.corpus_v2 import CorpusV2


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("variant", choices=["v1", "v2"])
    parser.add_argument("output")
    parser.add_argument("--rows", type=int, default=50000)
    args = parser.parse_args()
    os.environ["DETHROTTLED_MULTILINGUAL_CORPUS"] = "1"
    obj = corpus.DualCorpus() if args.variant == "v1" else CorpusV2()
    connection = obj.primary._db if args.variant == "v1" else obj.db
    q = np.zeros(384, dtype="float32")
    q[0] = 1
    vector = q.tobytes()
    corpus.embed = lambda texts, **kw: [q.tolist()] * len(texts)
    now = time.time()
    started = time.perf_counter()
    with connection:
        if args.variant == "v2":
            connection.executemany(
                "INSERT INTO sources VALUES(?,?,?,?,?,?,?,?,?,1,?,?)",
                [
                    (
                        "s%d" % i,
                        "https://example.org/%d" % i,
                        str(i),
                        "missing",
                        "corpus-public",
                        "Source %d" % i,
                        "{}",
                        now,
                        now,
                        "ready",
                        "{}",
                    )
                    for i in range((args.rows + 99) // 100)
                ],
            )
        for start in range(0, args.rows, 1000):
            for i in range(start, min(start + 1000, args.rows)):
                text = ("Passage %d records controlled storage and retrieval evidence. " % i) * 12
                url = "https://example.org/%d" % (i // 100)
                if args.variant == "v1":
                    connection.executemany(
                        "INSERT INTO passages VALUES(?,?,?,?,?,?,?)",
                        [
                            ("%s-%d" % (model, i), url, "Source", text, model, vector, now)
                            for model in ("minilm", corpus.MultilingualCorpus.model_name)
                        ],
                    )
                else:
                    cur = connection.execute(
                        "INSERT INTO passages(source_id,start,end,text,digest,"
                        "heading,page) VALUES(?,?,?,?,?,?,?)",
                        (
                            "s%d" % (i // 100),
                            i * 1000,
                            i * 1000 + len(text),
                            text,
                            str(i),
                            "",
                            None,
                        ),
                    )
                    connection.executemany(
                        "INSERT INTO embeddings VALUES(?,?,?,?,?)",
                        [
                            (cur.lastrowid, model, 384, vector, obj.revisions[model])
                            for model in obj.models
                        ],
                    )
    ingestion = time.perf_counter() - started
    connection.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    readings = []
    for _ in range(6):
        started = time.perf_counter()
        hits = obj.search("controlled storage evidence", limit=10)
        readings.append((time.perf_counter() - started) * 1000)
        assert hits
    root = Path(os.environ["DETHROTTLED_DATA_DIR"])
    result = {
        "variant": args.variant,
        "architecture": platform.machine(),
        "rows_per_model": args.rows,
        "dimensions": 384,
        "models": 2,
        "inference": "fixed unit vector; excludes model/tokenizer memory and latency",
        "construction_seconds": ingestion,
        "query_ms": readings,
        "warm_p50_ms": statistics.median(readings[1:]),
        "peak_rss_kib": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
        "disk_bytes": {p.name: p.stat().st_size for p in root.iterdir() if p.is_file()},
    }
    Path(args.output).write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps(result))


if __name__ == "__main__":
    main()
