"""Fresh-process policy cost and actual HTTP/TLS/DDGS/document acquisition controls."""

import argparse
import hashlib
import json
import os
import resource
import statistics
import time
from pathlib import Path

from fixtures import FACTS, Fixture

from dethrottled import adblock, fetch, netfilter

parser = argparse.ArgumentParser()
parser.add_argument("--list", required=True)
parser.add_argument("--enabled", type=int, required=True)
parser.add_argument("--output", required=True)
args = parser.parse_args()
os.environ["DETHROTTLED_ADBLOCK"] = str(args.enabled)
blob = Path(args.list).read_bytes()
adblock.FILTER.start = lambda: None
rss_before = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
started = time.monotonic()
if args.enabled:
    adblock.FILTER.rules = adblock.parse(blob)
load_ms = (time.monotonic() - started) * 1000
rss_after = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
started = time.perf_counter()
hits = sum(
    bool(adblock.FILTER.match("https://child.a.google-analytics.com/path")) for _ in range(100000)
)
match_ns = (time.perf_counter() - started) * 1e9 / 100000
fixture = Fixture()
report = {
    "enabled": bool(args.enabled),
    "architecture": os.uname().machine,
    "list_sha256": hashlib.sha256(blob).hexdigest(),
    "rule_count": len(adblock.FILTER.rules),
    "parse_ms": load_ms,
    "rss_before_kib": rss_before,
    "rss_after_parse_kib": rss_after,
    "match_ns": match_ns,
    "match_iterations": 100000,
    "matched": hits,
    "cases": [],
}
try:
    import curl_cffi.requests as tls
    from ddgs.http_client import HttpClient

    netfilter.install_ddgs()
    for name, get in [
        ("http", netfilter.get),
        ("tls", lambda u: netfilter.get_using(tls.get, u)),
        ("ddgs", HttpClient().get),
    ]:
        for repetition in range(3):
            fixture.reset()
            started = time.monotonic()
            response = get(f"http://127.0.0.1:{fixture.port}/document.txt")
            report["cases"].append(
                {
                    "transport": name,
                    "repetition": repetition,
                    "elapsed_ms": (time.monotonic() - started) * 1000,
                    "facts": sum(f in response.text for f in FACTS[:2]),
                    "traffic": dict(fixture.counts),
                }
            )
        if args.enabled:
            try:
                get(f"http://127.0.0.1:{fixture.port}/redirect")
            except adblock.AdblockBlocked:
                report[name + "_redirect_blocked"] = True
            else:
                report[name + "_redirect_blocked"] = False
    for repetition in range(3):
        fixture.reset()
        started = time.monotonic()
        document = fetch.fetch_and_extract(
            f"http://127.0.0.1:{fixture.port}/document.pdf", allow_render=False, max_chars=5000
        )
        report["cases"].append(
            {
                "transport": "document_pdf",
                "repetition": repetition,
                "elapsed_ms": (time.monotonic() - started) * 1000,
                "facts": sum(f in document["text"] for f in FACTS[:2]),
                "ok": document["ok"],
                "traffic": dict(fixture.counts),
            }
        )
    report["cpu_seconds"] = (
        resource.getrusage(resource.RUSAGE_SELF).ru_utime
        + resource.getrusage(resource.RUSAGE_SELF).ru_stime
    )
    report["maxrss_kib"] = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    report["all_evidence_retained"] = all(row["facts"] == 2 for row in report["cases"])
    report["median_ms"] = {
        name: statistics.median(
            row["elapsed_ms"] for row in report["cases"] if row["transport"] == name
        )
        for name in ["http", "tls", "ddgs"]
    }
finally:
    fixture.stop()
    Path(args.output).write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report.get("median_ms", {})))
