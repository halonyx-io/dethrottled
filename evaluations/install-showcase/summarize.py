"""Derive report metrics/charts from retained cases, never hand-enter chart values."""

import argparse
import hashlib
import json
import math
import re
import statistics
from collections import Counter, defaultdict
from pathlib import Path

P = argparse.ArgumentParser()
P.add_argument("--results", type=Path, required=True)
P.add_argument("--assets", type=Path, required=True)
A = P.parse_args()


def read(path):
    return json.loads(path.read_text())


def timing(rows):
    values = sorted(x["elapsed_ms"] for x in rows)
    return dict(
        n=len(values),
        median_ms=statistics.median(values),
        p95_ms=values[math.ceil(0.95 * len(values)) - 1],
    )


def memory_bytes(value):
    match = re.match(r"([\d.]+)([KMGT]?i?B)", value.strip())
    units = {
        "B": 1,
        "kB": 1000,
        "KB": 1000,
        "KiB": 1024,
        "MB": 10**6,
        "MiB": 1024**2,
        "GB": 10**9,
        "GiB": 1024**3,
        "TB": 10**12,
        "TiB": 1024**4,
    }
    return float(match[1]) * units[match[2]]


metrics = {
    "method": "Client wall time; nearest-rank p95; no semantic accuracy inference.",
    "devices": {},
}
for host in ("q6a", "szbox"):
    device = metrics["devices"][host] = {}
    for folder in sorted(A.results.glob(host + "-*")):
        if not folder.is_dir():
            continue
        casefile = folder / "cases.json"
        if casefile.exists():
            rows = read(casefile)
            phase = folder.name.removeprefix(host + "-")
            result = dict(
                timing(rows),
                http_200=sum(r["status"] == 200 for r in rows),
                response_bytes=sum(r.get("response_bytes", 0) for r in rows),
            )
            if phase.startswith("search"):
                result.update(
                    nonempty=sum(r["result_count"] > 0 for r in rows),
                    results_total=sum(r["result_count"] for r in rows),
                    all_menus_within_15=all(r["menu_budget_ok"] for r in rows),
                    cached_rows=sum(x.get("cached", False) for r in rows for x in r["results"]),
                )
            elif phase == "research":
                result.update(
                    tasks_with_sources=sum(bool(r["sources"]) for r in rows),
                    readable_sources=sum(len(r["sources"]) for r in rows),
                )
            else:
                result.update(
                    quality=dict(Counter(r.get("quality") or "request_error" for r in rows)),
                    literal_assertions_pass=sum(r.get("assertions_pass", False) for r in rows),
                    retained_assertions_pass=sum(
                        r.get("retained_assertions_pass", False) for r in rows
                    ),
                )
            if phase == "concurrency":
                result["by_callers"] = {
                    str(c): dict(
                        timing([r for r in rows if r["concurrency"] == c]),
                        batches=[b for b in read(folder / "batches.json") if b["concurrency"] == c],
                    )
                    for c in (1, 3, 6)
                }
            samples = defaultdict(lambda: {"bytes": 0, "cpu": 0})
            for row in read(folder / "resources.json"):
                sample = samples[row["at"]]
                sample["bytes"] += memory_bytes(row["memory"].split("/")[0])
                sample["cpu"] += float(row["cpu_percent_one_core"].rstrip("%"))
            result["resources"] = dict(
                samples=len(samples),
                peak_working_set_bytes=max((v["bytes"] for v in samples.values()), default=0),
                peak_cpu_percent_one_core=max((v["cpu"] for v in samples.values()), default=0),
            )
            result["run"] = read(folder / "summary.json")
            device[phase] = result
    contracts = [
        r for i in (1, 2, 3) for r in read(A.results / f"{host}-contracts-{i}/contracts.json")
    ]
    device["contracts"] = dict(
        timing(contracts),
        passed=sum(r["passed"] for r in contracts),
        restore=read(A.results / f"{host}-contracts-3/restore.json"),
    )
(A.results / "metrics.json").write_text(json.dumps(metrics, indent=2) + "\n")

# Static publication figures, with source paths embedded as metadata.
import matplotlib  # noqa: E402

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

plt.rcParams.update(
    {
        "figure.facecolor": "#0b1118",
        "axes.facecolor": "#0b1118",
        "text.color": "#f0f7fa",
        "axes.labelcolor": "#9eb2bf",
        "xtick.color": "#9eb2bf",
        "ytick.color": "#f0f7fa",
        "axes.edgecolor": "#29404d",
        "font.family": "DejaVu Sans",
        "svg.fonttype": "none",
    }
)
A.assets.mkdir(parents=True, exist_ok=True)
fig, axes = plt.subplots(2, 2, figsize=(12, 7))
for ax, (phase, title) in zip(
    axes.flat,
    [
        ("formats", "Controlled formats"),
        ("search-fresh", "Live search · fresh"),
        ("fetch-fresh", "Live fetch · fresh"),
        ("research", "Live research"),
    ],
):
    for i, host in enumerate(("q6a", "szbox")):
        r = metrics["devices"][host][phase]
        ax.barh(
            i + 0.14,
            r["p95_ms"] / 1000,
            height=0.25,
            color="#29404d",
            label="p95" if i == 0 else "",
        )
        ax.barh(
            i - 0.14,
            r["median_ms"] / 1000,
            height=0.25,
            color="#43e0d0" if host == "q6a" else "#82baff",
            label="median" if i == 0 else "",
        )
    ax.set_yticks([0, 1], ["Q6A", "szbox"])
    ax.set_title(title + f" · n={metrics['devices']['q6a'][phase]['n']} per device", loc="left")
    ax.set_xlabel("Seconds per request · failures included")
    ax.spines[["top", "right"]].set_visible(False)
    ax.legend(frameon=False, labelcolor="#9eb2bf", fontsize=9)
fig.suptitle("Same workload. Two native architectures. Software rendering.", fontsize=17)
fig.tight_layout(rect=(0, 0, 1, 0.94))
fig.savefig(
    A.assets / "latency.svg",
    metadata={"Description": "Derived from metrics.json and per-case JSON; all outcomes included."},
)
plt.close(fig)

fig, ax = plt.subplots(figsize=(12, 4))
colors = {"ok": "#43e0d0", "thin": "#e1b76a", "failed": "#e57a88", "request_error": "#8d8cae"}
for i, host in enumerate(("q6a", "szbox")):
    counts = metrics["devices"][host]["fetch-fresh"]["quality"]
    start = 0
    for key, color in colors.items():
        value = counts.get(key, 0)
        ax.barh(i, value, left=start, color=color, label=key if i == 0 else "")
        if value:
            ax.text(start + value / 2, i, str(value), ha="center", va="center", color="#0b1118")
        start += value
ax.set_yticks([0, 1], ["Q6A", "szbox"])
ax.set_xlim(0, metrics["devices"]["q6a"]["fetch-fresh"]["n"])
ax.set_xlabel("Fixed public targets · n=30 per device · fresh acquisition")
ax.set_title(
    "Live reads: useful-looking text, thin results and failures stay separate", loc="left", pad=22
)
ax.legend(frameon=False, labelcolor="#9eb2bf", ncols=4, loc="lower right")
ax.spines[["top", "right"]].set_visible(False)
fig.tight_layout()
fig.savefig(
    A.assets / "live-outcomes.svg",
    metadata={
        "Description": "quality labels from fetch-fresh/cases.json; not semantic verification."
    },
)
plt.close(fig)

checksums = {
    str(p.relative_to(A.results)): hashlib.sha256(p.read_bytes()).hexdigest()
    for p in sorted(A.results.rglob("*"))
    if p.is_file() and p.name != "checksums.json"
}
(A.results / "checksums.json").write_text(json.dumps(checksums, indent=2) + "\n")
print(json.dumps(metrics, indent=2))
