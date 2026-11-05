"""Offline acceptance and resource-summary replay against the retained observations."""

import hashlib
import json
import statistics
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
RESULTS = Path(__file__).with_name("results")


def read(name):
    return json.loads((RESULTS / name).read_text())


summary = read("resource-summary.json")
for arch in ["x86_64", "arm64"]:
    for mode in [0, 1]:
        for task in ["browser", "clean", "clean-reversed", "crawl4ai"]:
            data = read(f"{arch}-{task}-{mode}.json")
            assert data["normal_cases_passed"] and data["resource_measurement_comparable"]
            normal = [r for r in data["cases"] if "repetition" in r]
            assert len(normal) == (7 if task.startswith("clean") else 3)
            if mode:
                assert all(not r.get("traffic", r).get("tracking_requests") for r in data["cases"])
            if task == "browser":
                controls = {r["kind"]: r for r in data["cases"] if "kind" in r}
                assert controls["download"]["fact_retained"]
                assert controls["worker"]["legitimate_worker_fact"]
                assert controls["service_worker"]["registered"] == 1
                if mode:
                    assert controls["drive_redirect"]["access"]["reason"] == "adblock_blocked"
                assert "error" in controls["public_target"]  # Existing SSRF guard preserved.
        clean = [
            r
            for task in ["clean", "clean-reversed"]
            for r in read(f"{arch}-{task}-{mode}.json")["cases"]
            if "repetition" in r
        ]
        stored = summary[arch]["on" if mode else "off"]
        assert stored["n"] == len(clean)
        assert stored["median_cpu_ms"] == statistics.median(r["cpu_ms"] for r in clean)
        assert stored["median_elapsed_ms"] == statistics.median(r["elapsed_ms"] for r in clean)
        assert stored["median_working_set_mib"] == statistics.median(
            r["resources_after"]["working_set_bytes"] / 2**20 for r in clean
        )
        name = (
            f"arm64-native-final-{mode}.json"
            if arch == "arm64"
            else f"x86_64-native-{'on' if mode else 'off'}-final.json"
        )
        native = read(name)
        assert native["all_evidence_retained"] and len(native["cases"]) == 12
        if mode:
            assert all(native[k + "_redirect_blocked"] for k in ["http", "tls", "ddgs"])
assert read("x86_64-searxng.json")["passed"]
updater = read("live-updater-final.json")
assert updater["restart_restores_identical_rules"]
assert [r["http"] for r in updater["attempts"]] == [200, 304]
assert updater["first"]["last_update"] == updater["second"]["last_update"]
gate = read("compose-final-gate.json")
assert gate["blocked"][0]["policy_blocked"] == "adblock"
assert gate["blocked"][0]["workflow"]["next_actions"] == []
assert gate["rendered"][0]["fact_anchor_retained"]
assert gate["rendered"][0]["tier"].startswith("crawl4ai/")
assert {"api", "browser", "searxng", "crawl4ai"} <= {
    r["component"] for r in gate["status"]["workers"] if r["available"]
}
for name in ["compose-live-final-on.json", "compose-live-off.json"]:
    live = read(name)
    assert all(r["fact_anchor_retained"] for r in live["cases"])
    assert live["reddit_drive"]["access"]["status"] == "content_observed"
for line in (RESULTS / "SHA256SUMS").read_text().splitlines():
    expected, name = line.split("  ", 1)
    assert hashlib.sha256((RESULTS / name).read_bytes()).hexdigest() == expected, name
identity = read("validation.json")
for name, expected in identity["source_sha256"].items():
    assert hashlib.sha256((ROOT / name).read_bytes()).hexdigest() == expected, name
print(
    json.dumps(
        {
            "passed": True,
            "clean_samples_per_architecture_per_setting": 14,
            "source_files_verified": len(identity["source_sha256"]),
            "network_used": False,
        }
    )
)
