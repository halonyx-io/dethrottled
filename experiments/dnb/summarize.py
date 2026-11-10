#!/usr/bin/env python3
"""Export bounded public evidence, excluding live HTML, cookies and screenshots."""

import argparse
import hashlib
import json
import re
import statistics
from pathlib import Path


def mib(value):
    number, unit = re.match(r"([\d.]+)([A-Za-z]+)", value).groups()
    return float(number) * {"GiB": 1024, "MiB": 1, "KiB": 1 / 1024, "B": 1 / 1048576}[unit]


def summarize(source, target):
    target.mkdir(parents=True, exist_ok=True)

    def read(path):
        return json.loads((source / path).read_text())

    result = {
        "schema": 1,
        "reference": read("reference.json"),
        "candidate_image": read("candidate-image.json"),
        "platform": "x86_64; AMD Ryzen 7 5800U; 16 logical CPUs; software rendering",
        "controlled": read("run-2/summary.json"),
        "verification": read("run-2/verification.json"),
        "resources": {},
        "context_ablation": read("context-ablation.json"),
        "limitations": [
            "single host with background production load",
            "live pilot is not an anti-bot success benchmark",
            "ARM64 not tested",
            "logical image sizes are not unique disk use",
            "all fixtures public synthetic; filter test uses synthetic 10000-rule snapshot",
        ],
    }
    resource = read("resources.json")
    for side in ["reference", "candidate"]:
        rows = [r for r in resource["records"] if r["side"] == side]
        memory = []
        for row in rows:
            for sample in row["samples"]:
                selected = [
                    c
                    for c in sample["containers"]
                    if (
                        "reference-" in c["Name"]
                        if side == "reference"
                        else c["Name"].endswith("candidate-1")
                    )
                ]
                memory.append(sum(mib(c["MemUsage"].split(" / ")[0]) for c in selected))
        result["resources"][side] = {
            "requests": sum(r["requests"] for r in rows),
            "successes": sum(r["successes"] for r in rows),
            "median_request_ms": statistics.median(t for r in rows for t in r["latency_ms"]),
            "median_cpu_seconds_per_10": statistics.median(r["cpu_seconds"] for r in rows),
            "median_working_set_mib": statistics.median(memory),
            "peak_observed_working_set_mib": max(memory),
            "memory_samples": len(memory),
        }
    policy = read("filter-policy.json")
    result["policy"] = {}
    for name, response in policy.items():
        body = response["body"]
        row = (body.get("results") or [body])[0]
        result["policy"][name] = {
            "http_status": response["http_status"],
            "success": row.get("success", row.get("ok")),
            "error": row.get("error_message"),
            "blocked": row.get("adblock", {}).get("blocked"),
            "rule_count": row.get("adblock", {}).get("rule_count"),
        }
    result["live_initial"] = []
    for path in sorted((source / "run-1").glob("live-*.json")):
        response = json.loads(path.read_text())
        row = (response["body"].get("results") or [{}])[0]
        md = row.get("markdown") or {}
        text = md.get("raw_markdown", "") if isinstance(md, dict) else md
        result["live_initial"].append(
            {
                "id": path.stem,
                "url": response["url"],
                "elapsed_ms": response["elapsed_ms"],
                "transport_success": row.get("success"),
                "markdown_chars": len(text),
                "sha256": hashlib.sha256(text.encode()).hexdigest(),
                "error": row.get("error_message"),
            }
        )
    result["live_retests"] = {}
    for name, response in read("live-retests.json").items():
        row = (response["body"].get("results") or [{}])[0]
        md = row.get("markdown") or {}
        result["live_retests"][name] = {
            "success": row.get("success"),
            "elapsed_ms": response["elapsed_ms"],
            "markdown_chars": len(md.get("raw_markdown", "")),
            "error": row.get("error_message"),
            "access": row.get("access"),
            "recovery": row.get("navigation_recovery"),
            "reddit_post_links_present": "/comments/" in md.get("raw_markdown", ""),
        }
    api = read("api-integration.json")
    row = api["fetch"]["body"][0]
    result["api_integration"] = {
        "version": "1.7.1",
        "fetch_http": api["fetch"]["http_status"],
        "tier": row["tier"],
        "quality": row["quality"],
        "facts": {
            fact: fact in row["content"] for fact in ["cobalt-731", "amber-592", "violet-683"]
        },
        "drive_ok": api["drive"]["body"]["ok"],
        "drive_delayed_fact": api["drive"]["body"]["steps"][-1]["data"],
    }
    result["initial_failures"] = [
        (
            "Docker FROM bare sha256 ID was interpreted as registry reference; "
            "fixed with dedicated frozen local tag"
        ),
        (
            "First candidate skipped guarded Reddit navigation and labelled blank Markdown "
            "successful; fixed and retested"
        ),
        (
            "Initial harness closed/deleted checkpoint, so did not establish restore; "
            "separate real restart assertion added"
        ),
        (
            "First resource run overlapped live traffic; retained privately and excluded "
            "from reported numbers"
        ),
        "Context diagnostic needed DISPLAY=:99 when invoked by docker exec; corrected",
    ]
    (target / "summary.json").write_text(json.dumps(result, indent=2) + "\n")
    (target / "resource-samples.json").write_text(json.dumps(resource, indent=2) + "\n")
    files = {
        str(p.relative_to(Path(__file__).parents[2])): hashlib.sha256(p.read_bytes()).hexdigest()
        for p in Path(__file__).parent.iterdir()
        if p.suffix in {".py", ".yml", ".sh"} or p.name == "Dockerfile"
    }
    (target / "source-sha256.json").write_text(json.dumps(files, indent=2) + "\n")
    print(json.dumps(result["resources"]))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("source", type=Path)
    parser.add_argument("target", type=Path)
    args = parser.parse_args()
    summarize(args.source, args.target)
