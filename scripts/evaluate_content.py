#!/usr/bin/env python3
"""Freeze and record task-assertion comparisons; no model, paid API or success inflation.

Run against isolated endpoints with the same upstream configuration. Regex assertions
must encode expected facts before acquisition. Matches are supporting excerpts for
review, not an automated semantic truth/completeness judgement.
"""

import argparse
import hashlib
import json
import re
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

from dethrottled.content import assess_content


def score(case, row):
    text = row.get("content", "")
    # Apply the same text-only evaluator to every endpoint, including old versions.
    independent = assess_content(text)
    spans = independent["spans"]
    assertions = []
    for fact in case["facts"]:
        matches = []
        for match in re.finditer(fact["pattern"], text, re.I):
            if any(match.start() < s["end"] and match.end() > s["start"] for s in spans):
                continue
            matches.append(dict(start=match.start(), end=match.end(), quote=match[0]))
            if len(matches) == 3:
                break
        assertions.append(dict(id=fact["id"], matched=bool(matches), evidence=matches))
    matched = sum(a["matched"] for a in assertions)
    return dict(extraction_success=bool(text) and row.get("quality") != "failed",
                assertions=assertions, supported_assertions=matched,
                expected_assertions=len(assertions),
                task_assertions_complete=bool(assertions) and matched == len(assertions),
                pollution=independent["pollution"], source_completeness="unknown",
                answer_verified=False, text_sha256=independent["text_sha256"])


def request_json(url, payload=None):
    data = None if payload is None else json.dumps(payload).encode()
    request = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(request, timeout=240) as response:
        return json.load(response)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("protocol", type=Path)
    parser.add_argument("--endpoint", action="append", required=True, help="name=http://host:port")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--repeat", type=int, default=2)
    args = parser.parse_args()
    protocol_bytes = args.protocol.read_bytes()
    protocol = json.loads(protocol_bytes)
    for case in protocol["cases"]:
        assert case["facts"], "Define expected facts before acquisition"
        for fact in case["facts"]:
            re.compile(fact["pattern"])
    endpoints = [e.split("=", 1) for e in args.endpoint]
    args.output.mkdir(parents=True, exist_ok=False)
    (args.output / "protocol.json").write_bytes(protocol_bytes)
    manifest = dict(started_at=datetime.now(timezone.utc).isoformat(),
                    protocol_sha256=hashlib.sha256(protocol_bytes).hexdigest(),
                    endpoints=dict(endpoints), repeat=args.repeat,
                    note="Assertion matches require review; not semantic answer verification. "
                         "Shared upstream/browser state and temporal drift can affect results.")
    (args.output / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    results = []
    with (args.output / "results.jsonl").open("w") as output:
        for repeat in range(args.repeat):
            for index, case in enumerate(protocol["cases"]):
                shift = (repeat + index) % len(endpoints)
                for name, endpoint in endpoints[shift:] + endpoints[:shift]:
                    for strategy in protocol["strategies"]:
                        payload = dict(strategy["arguments"], urls=[case["url"]],
                                       max_chars=protocol["max_chars"], cache_mode="bypass",
                                       evidence_namespace="content-eval-" + hashlib.sha256(
                                           name.encode()).hexdigest()[:12])
                        record = dict(case=case["id"], url=case["url"], repeat=repeat,
                                      endpoint=name, strategy=strategy["id"], request=payload,
                                      started_at=datetime.now(timezone.utc).isoformat())
                        started = time.monotonic()
                        try:
                            response = request_json(endpoint.rstrip("/") + "/fetch", payload)
                            row = response[0]
                            record.update(http_success=True, response=response,
                                          score=score(case, row))
                        except (OSError, ValueError, KeyError, IndexError) as exc:
                            record.update(http_success=False,
                                          error=type(exc).__name__ + ": " + str(exc))
                        record["elapsed_ms"] = round((time.monotonic() - started) * 1000, 2)
                        output.write(json.dumps(record, ensure_ascii=False) + "\n")
                        output.flush()
                        results.append(record)
                        print(name, case["id"], strategy["id"], repeat,
                              record.get("score", {}).get("supported_assertions", 0), flush=True)
    summary = {}
    for record in results:
        key = record["endpoint"] + "/" + record["strategy"]
        totals = summary.setdefault(key, dict(requests=0, http_success=0, extraction_success=0,
                                             complete_task_assertions=0, supported_assertions=0))
        totals["requests"] += 1
        totals["http_success"] += record["http_success"]
        scored = record.get("score", {})
        for total, field in (("extraction_success", "extraction_success"),
                             ("complete_task_assertions", "task_assertions_complete"),
                             ("supported_assertions", "supported_assertions")):
            totals[total] += scored.get(field, 0)
    (args.output / "summary.json").write_text(json.dumps(summary, indent=2) + "\n")


if __name__ == "__main__":
    main()
