"""Regrade retained synthetic evidence and verify hashes offline; standard library only."""

import ast
import gzip
import hashlib
import json
import math
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
RESULTS = Path(__file__).parent / "results" / "2026-11-05"


def load(name):
    path = RESULTS / name
    if not path.exists():
        path = path.with_suffix(path.suffix + ".gz")
    raw = path.read_bytes()
    return json.loads(gzip.decompress(raw) if path.suffix == ".gz" else raw)


def syntax_digest(raw):
    """Stable across AST dump changes and optional empty fields in Python 3.10+."""

    def canonical(value):
        if isinstance(value, ast.AST):
            return [
                type(value).__name__,
                [
                    (key, canonical(item))
                    for key, item in ast.iter_fields(value)
                    if item is not None and item != []
                ],
            ]
        if isinstance(value, list):
            return [canonical(item) for item in value]
        return [type(value).__name__, repr(value)]

    return hashlib.sha256(json.dumps(canonical(ast.parse(raw))).encode()).hexdigest()


def grade(rows, data):
    questions = {q["id"]: q for q in data["questions"]}
    positive, negative, matched = [], [], 0
    for row in rows:
        question = questions[row["id"]]
        ranks = [
            i
            for i, h in enumerate(row["hits"], 1)
            if question["facts"]
            and h["url"] == question["url"]
            and all(f.casefold() in h["text"].casefold() for f in question["facts"])
        ]
        rank = min(ranks) if ranks else None
        assert row["answer_rank"] == rank, row["id"]
        assert row["negative"] == (not question["facts"]), row["id"]
        if question["facts"]:
            positive.append(rank)
        else:
            negative.append(bool(row["hits"]))
        matched += 1
    return dict(
        recall_at_5=sum(bool(r and r <= 5) for r in positive) / len(positive),
        mrr_at_10=sum(1 / r if r else 0 for r in positive) / len(positive),
        negative_trials=len(negative),
        negative_queries_with_hits=sum(negative),
        trials=matched,
    )


def main():
    for line in (RESULTS / "SHA256SUMS").read_text().splitlines():
        digest, name = line.split("  ", 1)
        assert hashlib.sha256((RESULTS / name).read_bytes()).hexdigest() == digest, name
    checked = 0
    for arch in ("x86_64", "arm64"):
        for variant in ("v1", "v2", "v2-before-support"):
            for dataset in ("development", "heldout"):
                path = RESULTS / f"{arch}-{variant}-{dataset}.json"
                if not path.exists() and not path.with_suffix(".json.gz").exists():
                    continue
                result = load(path.name)
                data = load(dataset + "-manifest.json")
                digest = hashlib.sha256(json.dumps(data, sort_keys=True).encode()).hexdigest()
                assert result["summary"]["manifest_sha256"] == digest
                calculated = grade(result["queries"], data)
                for key in (
                    "recall_at_5",
                    "mrr_at_10",
                    "negative_trials",
                    "negative_queries_with_hits",
                ):
                    assert math.isclose(calculated[key], result["summary"][key]), (path.name, key)
                checked += calculated["trials"]
        for name in (
            f"{arch}-multilingual-development.json",
            f"{arch}-multilingual-validation.json",
            f"{arch}-model-comparison.json",
        ):
            result = load(name)
            digest = hashlib.sha256(
                json.dumps(result["manifest"], sort_keys=True).encode()
            ).hexdigest()
            assert result["manifest_sha256"] == digest
            for variant in result["results"]:
                calculated = grade(variant["queries"], result["manifest"])
                assert math.isclose(calculated["recall_at_5"], variant["summary"]["recall_at_5"])
                distinct = {r["id"] for r in variant["queries"] if r["negative"] and r["hits"]}
                assert len(distinct) == variant["summary"]["negative_questions_with_hits"]
                checked += calculated["trials"]
        assert load(f"{arch}-stack.json")["passed"]
        assert load(f"{arch}-replay.json")["passed"]
        assert all(e["passed"] for e in load(f"{arch}-lifecycle.json")["events"])
        concurrency = load(f"{arch}-concurrency.json")
        assert concurrency["idle"]["fact_successes"] == 48
        assert concurrency["indexing"]["fact_successes"] == 48
    build = load("build.json")
    for name, digest in build["runtime_source_sha256"].items():
        raw = (ROOT / name).read_bytes()
        actual = hashlib.sha256(raw).hexdigest()
        if actual != digest:
            formatting = build.get("format_only_changes", {}).get(name, {})
            assert actual == formatting.get("current_sha256"), name
            assert syntax_digest(raw) == formatting["tested_ast_sha256"]
    replayed = sum(
        g["trials"] for arch in ("x86_64", "arm64") for g in load(f"{arch}-replay.json")["gates"]
    )
    print(
        json.dumps(
            dict(
                passed=True,
                independently_regraded_trials=checked,
                native_regression_replay_trials=replayed,
            )
        )
    )


if __name__ == "__main__":
    main()
