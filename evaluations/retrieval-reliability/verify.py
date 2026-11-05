"""Independently grade frozen extraction text and compare controlled discovery."""
import gzip
import hashlib
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent


def normalized(text):
    return " ".join(re.findall(r"\w+", text.casefold()))


def read(name):
    return json.loads((ROOT / name).read_text())


def main():
    for line in (ROOT / "SHA256SUMS").read_text().splitlines():
        digest, name = line.split("  ", 1)
        assert hashlib.sha256((ROOT / name).read_bytes()).hexdigest() == digest, name
    manifest = read("fixtures/manifest.json")
    for item in manifest:
        data = gzip.decompress((ROOT / "fixtures" / (item["file"] + ".gz")).read_bytes())
        assert hashlib.sha256(data).hexdigest() == item["sha256"], item["file"]
    totals = {}
    for arch in ("x86_64", "arm64"):
        trials = {}
        for variant in ("baseline", "candidate"):
            data = read(f"results/{arch}-{variant}.json")
            assert len(data["rows"]) == len(manifest)
            graded = []
            for row, item in zip(data["rows"], manifest):
                assert row["fixture"] == item["file"]
                raw = gzip.decompress((ROOT / "results" / row["text_file"]).read_bytes())
                assert hashlib.sha256(raw).hexdigest() == row["text_sha256"]
                key = normalized(raw.decode())
                hits = [normalized(fact) in key for fact in item["facts"]]
                assert hits == row["fact_hits"], (arch, variant, row["fixture"])
                noise = [normalized(n) in key for n in item["noise_labels"]]
                assert noise == row["noise_labels_retained"]
                assert not any(noise), (arch, variant, row["fixture"], "known furniture")
                assert len(row["latency_ms"]) == 3
                assert row["peak_rss_kib"] > 0
                graded.extend(hits)
            trials[variant] = graded
        assert all(not old or new for old, new in zip(trials["baseline"], trials["candidate"]))
        assert sum(trials["baseline"]) == 21 and sum(trials["candidate"]) == 25
        totals[arch] = {k: sum(v) for k, v in trials.items()}
    before = read("results/search-baseline.json")
    after = read("results/search-candidate.json")
    for name in before["scenarios"]:
        old, new = before["scenarios"][name], after["scenarios"][name]
        assert old["urls"] == new["urls"], name
        assert old["calls"]["health_sx"] + old["calls"]["health_bing"] == 10
        assert new["calls"]["health_sx"] + new["calls"]["health_bing"] == 0
    assert not after["scenarios"]["ddg_down_backups_up"]["reported_ready"]
    assert after["scenarios"]["ddg_up_backups_down"]["reported_ready"]
    assert after["scenarios"]["genuine_empty"]["outcome"] == "no_results"
    assert after["scenarios"]["complete_outage"]["outcome"] == "unavailable"
    assert len(before["correlated_refusals"]["attempts"]) == 10
    assert len(after["correlated_refusals"]["attempts"]) == 4
    live = read("results/live-api.json")
    assert live["passed"] and all(live["checks"].values())
    canonical = next(r for r in read("results/x86_64-candidate.json")["rows"]
                     if r["fixture"] == "rfc9110.html")
    assert live["observations"]["rfc"]["document_sha256"] == canonical["text_sha256"]
    print(json.dumps({"passed": True, "independently_graded": totals,
                      "unchanged_search_menus": len(before["scenarios"])}))


if __name__ == "__main__":
    main()
