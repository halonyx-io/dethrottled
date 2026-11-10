"""Short same-workload comparison and concurrent adversarial storage checks."""

import argparse
import hashlib
import json
import statistics
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from compare import request
from measure import cpu
from pool_bench import BASE, StateParser, render


def storage(mode, owner, seed="", **options):
    response = render(
        mode, "/state" + ("?set=" + seed if seed else ""), owner=owner, delay=0.2, **options
    )
    assert response["http"] == 200, response
    row = response["body"]["results"][0]
    parser = StateParser()
    parser.feed(row["html"])
    return json.loads(parser.text)


def concurrent_pair(first, second):
    barrier = threading.Barrier(2)

    def call(fn):
        barrier.wait()
        return fn()

    with ThreadPoolExecutor(max_workers=2) as workers:
        return list(workers.map(call, [first, second]))


def main(output):
    output.mkdir(parents=True, exist_ok=True)
    checks = {}
    for mode in ["fresh", "persistent"]:
        # Identical origin/session/scope/config. Only caller identity differs.
        a, b = concurrent_pair(
            lambda mode=mode: storage(mode, "adversary-A", seed="A-secret"),
            lambda mode=mode: storage(mode, "adversary-B"),
        )
        assert a["local"] == a["idb"] == "A-secret"
        assert not b["local"] and not b["idb"] and "A-secret" not in b["cookie"]
        storage(mode, "adversary-B", seed="B-secret")
        for _ in range(2):
            a, b = concurrent_pair(
                lambda mode=mode: storage(mode, "adversary-A"),
                lambda mode=mode: storage(mode, "adversary-B"),
            )
            for value, own, other in [(a, "A-secret", "B-secret"), (b, "B-secret", "A-secret")]:
                assert value["local"] == value["idb"] == own and own in value["cookie"]
                assert other not in json.dumps(value)
        storage(mode, "scope-owner", seed="scope-secret", scope="public-job")
        for options in [
            {"scope": "internal-app"},
            {"scope": "public-job", "session": "separate"},
            {"scope": "public-job", "headless": False},
            {"scope": "public-job", "hosts": "fixture"},
        ]:
            value = storage(mode, "scope-owner", **options)
            assert not value["local"] and not value["idb"] and "scope-secret" not in value["cookie"]
        checks[mode] = {
            "concurrent_cookie_local_idb_isolation": True,
            "scope_session_config_isolation": True,
        }
    blocked = render("persistent", "/private-redirect", hosts="fixture")
    row = blocked["body"]["results"][0]
    assert not row["success"] and "allowed_host" in row["error_message"], row
    checks["redirect_allowed_host_rechecked"] = True
    blocked = render("persistent", public_only=True)
    assert blocked["http"] == 403, blocked
    checks["public_scope_rejects_internal_destination"] = True
    drive = request(
        BASE,
        "/drive",
        {
            "url": "http://fixture:8090/article",
            "public_only": False,
            "allowed_hosts": ["fixture"],
            "steps": [{"action": "title"}],
            "screenshot": "never",
        },
    )
    assert drive["body"]["ok"], drive
    checks["drive_policy_preserves_trusted_fixture_access"] = True
    output.joinpath("checks.json").write_text(json.dumps(checks, indent=2) + "\n")
    records = []
    workload = {
        "/article": ["cobalt-731", "amber-592", "violet-683"],
        "/long": ["cobalt-731", "amber-592"],
        "/redirect": ["cobalt-731", "amber-592", "violet-683"],
    }
    modes = ["anonymous", "fresh", "persistent"]
    for mode in modes:
        render(mode, owner="timing-owner")
    for repeat, order in enumerate([modes, list(reversed(modes))]):
        for mode in order:
            before = cpu("candidate")
            rows = []
            for path, facts in workload.items():
                response = render(mode, path, owner="timing-owner")
                result = response["body"]["results"][0]
                text = result["markdown"]["raw_markdown"]
                assert result["success"] and all(f in text for f in facts), response
                rows.append(
                    {
                        "path": path,
                        "ms": response["ms"],
                        "facts": len(facts),
                        "sha256": hashlib.sha256(text.encode()).hexdigest(),
                    }
                )
            records.append(
                {
                    "mode": mode,
                    "repeat": repeat,
                    "cpu_seconds": (cpu("candidate") - before) / 1e6,
                    "rows": rows,
                }
            )
            output.joinpath("measurements.json").write_text(json.dumps(records, indent=2) + "\n")
    for path in workload:
        assert len({r["sha256"] for b in records for r in b["rows"] if r["path"] == path}) == 1
    summary = {
        mode: {
            "reads": 6,
            "fact_checks": 16,
            "median_ms": statistics.median(
                r["ms"] for b in records if b["mode"] == mode for r in b["rows"]
            ),
            "median_cpu_seconds_per_3": statistics.median(
                b["cpu_seconds"] for b in records if b["mode"] == mode
            ),
        }
        for mode in modes
    }
    output.joinpath("results.json").write_text(
        json.dumps({"checks": checks, "summary": summary, "records": records}, indent=2) + "\n"
    )
    print(json.dumps(summary))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("output", type=Path)
    main(parser.parse_args().output)
