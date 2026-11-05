"""Offline native extraction comparison using frozen source/fact labels.

Run each variant in a separate container/process. Linux native RSS is KiB.
The candidate is imported through PYTHONPATH; no provider is queried here.
"""
import argparse
import gzip
import hashlib
import json
import multiprocessing
import platform
import re
import resource
import statistics
import time
from pathlib import Path

from dethrottled import extract

ROOT = Path(__file__).resolve().parent


def normalized(text):
    return " ".join(re.findall(r"\w+", text.casefold()))


def measure(item, queue):
    html = gzip.decompress((ROOT / "fixtures" / (item["file"] + ".gz")).read_bytes())
    assert hashlib.sha256(html).hexdigest() == item["sha256"]
    text = html.decode()
    timings = []
    for _ in range(3):
        start = time.perf_counter()
        result = extract.extract(text, item["url"], max_chars=1000000)
        timings.append((time.perf_counter() - start) * 1000)
    peak = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    key = normalized(result.get("text", ""))
    queue.put({"fixture": item["file"], "tier": result.get("tier"),
        "chars": result.get("chars"), "fact_hits": [normalized(f) in key for f in item["facts"]],
        "latency_ms": timings, "median_ms": statistics.median(timings),
        "peak_rss_kib": peak, "_text": result.get("text", ""),
        "completeness": result.get("completeness"),
        "warnings": result.get("warnings", []),
        "noise_labels_retained": [normalized(n) in key for n in item.get("noise_labels", [])]})


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--label", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    manifest = json.loads((ROOT / "fixtures" / "manifest.json").read_text())
    context = multiprocessing.get_context("spawn")
    rows = []
    for item in manifest:
        queue = context.Queue()
        process = context.Process(target=measure, args=(item, queue))
        process.start()
        row = queue.get(timeout=120)
        text = row.pop("_text").encode()
        text_dir = args.output.parent / "texts"
        text_dir.mkdir(parents=True, exist_ok=True)
        filename = args.output.stem + "-" + item["file"] + ".txt.gz"
        (text_dir / filename).write_bytes(gzip.compress(text, mtime=0))
        row["text_file"] = "texts/" + filename
        row["text_sha256"] = hashlib.sha256(text).hexdigest()
        rows.append(row)
        process.join(timeout=10)
        assert process.exitcode == 0, item["file"]
        queue.close()
    output = {"label": args.label, "architecture": platform.machine(),
              "source_sha256": hashlib.sha256(Path(extract.__file__).read_bytes()).hexdigest(),
              "model": "no models; native extractors", "repetitions_per_fixture": 3,
              "memory": "fresh-process peak RSS including interpreter/extractor libraries; KiB",
              "rows": rows}
    args.output.write_text(json.dumps(output, indent=2) + "\n")
    print(json.dumps({"label": args.label, "facts_retained": sum(sum(r["fact_hits"]) for r in rows),
                      "facts": sum(len(r["fact_hits"]) for r in rows),
                      "fixtures": len(rows)}))


if __name__ == "__main__":
    main()
