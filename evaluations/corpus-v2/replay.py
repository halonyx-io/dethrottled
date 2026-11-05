"""Replay recorded quality gates against retained, isolated v2 fixture databases."""

import argparse
import hashlib
import json
import os
import platform
from pathlib import Path

from benchmark import heldout_manifest, manifest

from dethrottled.corpus_v2 import CorpusV2
from dethrottled.evidence import Documents


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("root", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    os.environ["DETHROTTLED_MULTILINGUAL_CORPUS"] = "1"
    gates = []
    for name, directory in [
        ("development-v2", "development-v2"),
        ("heldout-v2", "heldout-v2"),
        ("cross-language", "cross-language"),
        ("validation-queries", "validation-queries"),
    ]:
        recorded_path = args.root / ("final-" + name + ".json")
        recorded = json.loads(recorded_path.read_text())
        root = args.root / "final" / directory
        obj = CorpusV2(root / "corpus-v2.sqlite", documents=Documents(root / "evidence.sqlite"))
        if "summary" in recorded:
            data = heldout_manifest() if name.startswith("heldout") else manifest()
            variants = [("standard", recorded["queries"])]
        else:
            data = recorded["manifest"]
            variants = [
                (r["summary"]["support"], r["queries"])
                for r in recorded["results"]
                if r["summary"]["models"] in {"both", "both-broad"}
            ]
        questions = {q["id"]: q for q in data["questions"]}
        for support, rows in variants:
            for row in rows:
                question = questions[row["id"]]
                hits = obj.search(
                    question["query"], mode=question.get("mode", "semantic"), support=support
                )
                ranks = [
                    i
                    for i, h in enumerate(hits, 1)
                    if question["facts"]
                    and h["url"] == question["url"]
                    and all(f.casefold() in h["text"].casefold() for f in question["facts"])
                ]
                assert (min(ranks) if ranks else None) == row["answer_rank"], (name, row["id"])
                assert len(hits) == len(row["hits"]), (name, row["id"], "candidate count")
            gates.append(
                dict(
                    dataset=name,
                    support=support,
                    trials=len(rows),
                    passed=True,
                    reference_sha256=hashlib.sha256(recorded_path.read_bytes()).hexdigest(),
                )
            )
    result = dict(
        architecture=platform.machine(),
        gates=gates,
        passed=True,
        note="Quality regression replay; concurrent host work excludes latency claims",
    )
    args.output.write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps(result))


if __name__ == "__main__":
    main()
