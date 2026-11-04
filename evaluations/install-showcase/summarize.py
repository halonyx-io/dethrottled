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
    all_cpu, all_memory = [], []
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
            all_cpu.extend(v["cpu"] for v in samples.values())
            all_memory.extend(v["bytes"] for v in samples.values())
            result["resources"] = dict(
                samples=len(samples),
                peak_working_set_bytes=max((v["bytes"] for v in samples.values()), default=0),
                peak_cpu_percent_one_core=max((v["cpu"] for v in samples.values()), default=0),
            )
            result["run"] = read(folder / "summary.json")
            device[phase] = result
    ordered_cpu = sorted(all_cpu)
    device["resources_overall"] = dict(
        snapshots=len(all_cpu),
        peak_working_set_bytes=max(all_memory),
        median_cpu_percent_one_core=statistics.median(all_cpu),
        p95_cpu_percent_one_core=ordered_cpu[math.ceil(0.95 * len(ordered_cpu)) - 1],
        max_reported_cpu_percent_one_core=max(all_cpu),
        caveat=(
            "Docker per-container CPU intervals are not exactly aligned; "
            "summed peaks may overstate instantaneous use."
        ),
    )
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
        "figure.facecolor": "#0F1720",
        "axes.facecolor": "#0F1720",
        "text.color": "#F8FAFC",
        "axes.labelcolor": "#93A3B2",
        "xtick.color": "#93A3B2",
        "ytick.color": "#F8FAFC",
        "axes.edgecolor": "#2A3540",
        "font.family": "DejaVu Sans",
        "svg.fonttype": "none",
        "svg.hashsalt": "dethrottled-1.4.0",
    }
)


def hardware_caption(fig):
    fig.text(
        0.5,
        0.02,
        "ARM64 edge: 8 cores (4 Cortex-A55 + 4 Cortex-A78), 11.29 GiB RAM visible to OS.\n"
        "x86_64 mini PC: Ryzen 7 5800U, 8 cores / 16 threads, 30.76 GiB RAM visible to OS.",
        ha="center",
        va="bottom",
        fontsize=9,
        color="#93A3B2",
        linespacing=1.4,
    )


A.assets.mkdir(parents=True, exist_ok=True)
fig, axes = plt.subplots(2, 2, figsize=(12, 8))
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
            color="#2A3540",
            label="p95" if i == 0 else "",
        )
        ax.barh(
            i - 0.14,
            r["median_ms"] / 1000,
            height=0.25,
            color="#22D3EE",
            label="median" if i == 0 else "",
        )
    ax.set_yticks([0, 1], ["ARM64\nedge device", "x86_64\nmini PC"])

    def failures(host, phase):
        row = metrics["devices"][host][phase]
        if phase == "formats":
            return row["n"] - row["literal_assertions_pass"], "Fact misses"
        if phase.startswith("search"):
            return row["n"] - row["nonempty"], "Empty menus"
        if phase == "research":
            return row["n"] - row["tasks_with_sources"], "Zero-source tasks"
        return sum(row["quality"].get(k, 0) for k in ("failed", "request_error")), "Failed reads"

    failed_q, kind = failures("q6a", phase)
    failed_s, _ = failures("szbox", phase)
    ax.set_title(
        title
        + f" · n={metrics['devices']['q6a'][phase]['n']}/device\n"
        + f"{kind}: ARM64 {failed_q} · x86_64 {failed_s}",
        loc="left",
        fontsize=11,
    )
    ax.set_xlabel("Seconds per request · failures included")
    ax.spines[["top", "right"]].set_visible(False)
    ax.legend(frameon=False, labelcolor="#93A3B2", fontsize=9)
fig.suptitle("ARM64 edge device vs x86_64 mini PC · software rendering", fontsize=17)
hardware_caption(fig)
fig.tight_layout(rect=(0, 0.10, 1, 0.94))
fig.savefig(
    A.assets / "latency.svg",
    metadata={
        "Description": "Derived from metrics.json and per-case JSON; all outcomes included.",
        "Date": None,
    },
)
plt.close(fig)

fig, ax = plt.subplots(figsize=(12, 5))
colors = {"ok": "#22D3EE", "thin": "#e1b76a", "failed": "#e57a88", "request_error": "#8d8cae"}
for i, host in enumerate(("q6a", "szbox")):
    counts = metrics["devices"][host]["fetch-fresh"]["quality"]
    start = 0
    for key, color in colors.items():
        value = counts.get(key, 0)
        ax.barh(i, value, left=start, color=color, label=key if i == 0 else "")
        if value:
            ax.text(start + value / 2, i, str(value), ha="center", va="center", color="#0F1720")
        start += value
ax.set_yticks([0, 1], ["ARM64\nedge device", "x86_64\nmini PC"])
ax.set_xlim(0, metrics["devices"]["q6a"]["fetch-fresh"]["n"])
ax.set_xlabel("Fixed public targets · n=30 per device · fresh acquisition")
ax.set_title(
    "Live fetch outcomes · engine assessment, not verified answer correctness", loc="left", pad=48
)
ax.legend(
    frameon=False,
    labelcolor="#93A3B2",
    ncols=4,
    loc="lower left",
    bbox_to_anchor=(0, 1.01),
    borderaxespad=0,
)
ax.spines[["top", "right"]].set_visible(False)
hardware_caption(fig)
fig.tight_layout(rect=(0, 0.17, 1, 1))
fig.savefig(
    A.assets / "live-outcomes.svg",
    metadata={
        "Description": "quality labels from fetch-fresh/cases.json; not semantic verification.",
        "Date": None,
    },
)
plt.close(fig)

fig, axes = plt.subplots(1, 2, figsize=(12, 5))
for metric, ax, label, divisor in zip(
    ("peak_working_set_bytes", "p95_cpu_percent_one_core"),
    axes,
    ("Peak container working set (GiB)", "p95 Docker CPU % (100% = one logical core)"),
    (1024**3, 1),
):
    for i, host in enumerate(("q6a", "szbox")):
        value = metrics["devices"][host]["resources_overall"][metric] / divisor
        ax.barh(i, value, color="#22D3EE" if i == 0 else "#93A3B2", height=0.5)
        ax.text(value, i, f" {value:.2f}", va="center", color="#F8FAFC")
    ax.set_yticks([0, 1], ["ARM64\nedge device", "x86_64\nmini PC"])
    ax.set_xlabel(label)
    ax.spines[["top", "right"]].set_visible(False)
fig.suptitle(
    "Default-stack memory and CPU · host activity and fixture server excluded", fontsize=14
)
counts = [metrics["devices"][h]["resources_overall"]["snapshots"] for h in ("q6a", "szbox")]
fig.text(
    0.5,
    0.14,
    f"Snapshots: ARM64 n={counts[0]}, x86_64 n={counts[1]}. Sampling can miss spikes.",
    ha="center",
    color="#93A3B2",
)
hardware_caption(fig)
fig.tight_layout(rect=(0, 0.25, 1, 0.9))
fig.savefig(
    A.assets / "resources.svg",
    metadata={
        "Date": None,
        "Description": "Derived from Docker stats resource snapshots; not total host memory.",
    },
)
plt.close(fig)

for name in ("latency.svg", "live-outcomes.svg", "resources.svg"):
    path = A.assets / name
    path.write_text("\n".join(line.rstrip() for line in path.read_text().splitlines()) + "\n")

checksums = {
    str(p.relative_to(A.results)): hashlib.sha256(p.read_bytes()).hexdigest()
    for p in sorted(A.results.rglob("*"))
    if p.is_file() and p.name != "checksums.json"
}
(A.results / "checksums.json").write_text(json.dumps(checksums, indent=2) + "\n")
print(json.dumps(metrics, indent=2))
