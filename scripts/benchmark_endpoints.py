#!/usr/bin/env python3
"""Reproducible live API benchmark: 50 English queries and fixed fetch URLs.

Run the modes in order: search, search-fetch, fetch, research. Search writes the
URL manifest used by both machines. Each request uses the public raw API and
the normal source pipeline. The resource sampler records every named container.
"""
from __future__ import annotations

import argparse
import json
import shlex
import statistics
import subprocess
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

QUERIES = [
    ("news", "EU AI Act enforcement news 2026"),
    ("news", "latest NASA Artemis mission updates"),
    ("news", "Federal Reserve interest rate latest decision"),
    ("news", "semiconductor supply chain news"),
    ("news", "UK energy price cap October 2026"),
    ("news", "Australia housing policy latest news"),
    ("news", "renewable energy storage breakthrough news"),
    ("news", "cybersecurity Patch Tuesday latest"),
    ("news", "COP31 climate conference preparations"),
    ("news", "WHO measles outbreak updates"),
    ("government", "Nashville Tennessee zoning ordinance 2026"),
    ("government", "Davidson County Tennessee property tax rate"),
    ("government", "US Census 2025 population estimates"),
    ("government", "EU AI Act official regulation text"),
    ("government", "California building energy code 2025"),
    ("technical", "qBittorrent port forwarding troubleshooting"),
    ("technical", "Python asyncio TaskGroup documentation"),
    ("technical", "Rust ownership guide examples"),
    ("technical", "Kubernetes liveness readiness startup probes configuration"),
    ("technical", "PostgreSQL EXPLAIN ANALYZE guide"),
    ("technical", "Docker Compose healthcheck syntax"),
    ("technical", "React hydration mismatch troubleshooting"),
    ("technical", "Linux systemd linger documentation"),
    ("technical", "ONNX Runtime Python inference documentation"),
    ("technical", "Caddy reverse proxy documentation"),
    ("reference", "Okapi BM25 ranking function explained"),
    ("reference", "SQLite write ahead logging file format"),
    ("reference", "Unicode normalization forms NFC NFKC explanation"),
    ("reference", "HTTP 429 Retry-After header semantics"),
    ("reference", "PDF A archival standard overview"),
    ("science", "genome sequencing read depth explanation"),
    ("science", "NASA exoplanet archive API documentation"),
    ("science", "lithium ion battery degradation research paper"),
    ("science", "IPCC AR6 synthesis report PDF"),
    ("science", "global atmospheric carbon dioxide dataset"),
    ("documents", "government climate risk report PDF"),
    ("documents", "World Bank population data CSV download"),
    ("documents", "open electricity data XLSX spreadsheet"),
    ("documents", "renewable energy public presentation PPTX"),
    ("documents", "Project Gutenberg EPUB download"),
    ("community", "Reddit home lab Docker backup discussion"),
    ("community", "GitHub FastAPI memory leak issue"),
    ("community", "Stack Overflow pandas timezone conversion"),
    ("community", "Hacker News SQLite performance discussion"),
    ("community", "forum qBittorrent port forwarding discussion"),
    ("web", "React single page app client side rendering"),
    ("web", "Cloudflare bot challenge documentation"),
    ("web", "YouTube video transcript captions example"),
    ("web", "Wikipedia article with large data tables"),
    ("web", "laptop specifications comparison Ryzen 5800U 7840U"),
]

RESEARCH = [
    "What changed in the Python 3.12 release?",
    "What are the current EU AI Act implementation dates?",
    "What does the IPCC AR6 synthesis report say about warming?",
    "What are the documented causes of lithium ion battery degradation?",
    "How does PostgreSQL EXPLAIN ANALYZE report query time?",
    "What are NASA's current Artemis mission milestones?",
    "How is the US Census population estimate calculated?",
    "What does the current Caddy reverse proxy documentation recommend?",
]

# One frozen URL from each of several source types. Use the same positions in
# the shared 50-URL manifest on both hosts so a renderer failure is comparable.
RENDER_INDICES = (1, 16, 18, 19, 24, 26, 27, 38, 47, 48)


def api_call(base: str, path: str, payload: dict, timeout: int = 120) -> dict:
    req = urllib.request.Request(
        base + path, data=json.dumps(payload).encode(), method="POST",
        headers={"Content-Type": "application/json"})
    start = time.perf_counter()
    try:
        with urllib.request.urlopen(req, timeout=timeout) as response:
            code, body = response.status, json.load(response)
        error = None
    except (urllib.error.URLError, TimeoutError, ValueError) as exc:
        code, body, error = None, None, str(exc)[:180]
    return {"elapsed_ms": round((time.perf_counter() - start) * 1000, 1),
            "http_status": code, "body": body, "error": error}


def mem_mib(value: str) -> float | None:
    value = value.strip()
    for suffix, scale in (("GiB", 1024), ("MiB", 1), ("KiB", 1 / 1024),
                          ("GB", 1000), ("MB", 1000 / 1024), ("kB", 1 / 1024)):
        if value.endswith(suffix):
            try:
                return round(float(value[:-len(suffix)]) * scale, 1)
            except ValueError:
                return None
    return None


def sample_stats(docker: list[str], containers: list[str], stop: threading.Event,
                 records: list[dict]) -> None:
    while not stop.is_set():
        stamp = time.time()
        proc = subprocess.run(
            [*docker, "stats", "--no-stream", "--format", "{{json .}}", *containers],
            capture_output=True, text=True, timeout=20, check=False)
        for line in proc.stdout.splitlines():
            try:
                row = json.loads(line)
            except ValueError:
                continue
            records.append({"at": stamp, "name": row.get("Name"),
                            "cpu_percent": float((row.get("CPUPerc") or "0").rstrip("%")),
                            "memory_mib": mem_mib((row.get("MemUsage") or "").split("/")[0])})
        stop.wait(2)


def percentile(values: list[float], pct: int) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    return ordered[max(0, (pct * len(ordered) + 99) // 100 - 1)]


def summarize(cases: list[dict], resources: list[dict]) -> dict:
    times = [case["elapsed_ms"] for case in cases]
    per_container = {}
    for name in sorted({r["name"] for r in resources if r["name"]}):
        rows = [r for r in resources if r["name"] == name]
        cpus = [r["cpu_percent"] for r in rows]
        mem = [r["memory_mib"] for r in rows if r["memory_mib"] is not None]
        per_container[name] = {
            "samples": len(rows), "cpu_mean_percent_one_core": round(statistics.mean(cpus), 2),
            "cpu_peak_percent_one_core": max(cpus),
            "memory_mean_mib": round(statistics.mean(mem), 1) if mem else None,
            "memory_peak_mib": max(mem) if mem else None,
        }
    return {"cases": len(cases), "http_200": sum(c["http_status"] == 200 for c in cases),
            "useful_cases": sum(c.get("useful", False) for c in cases),
            "median_ms": statistics.median(times) if times else None,
            "p95_ms": percentile(times, 95),
            "mean_ms": round(statistics.mean(times), 1) if times else None,
            "min_ms": min(times) if times else None,
            "max_ms": max(times) if times else None,
            "resources": per_container}


def make_manifest(search_cases: list[dict]) -> list[dict]:
    selected, seen = [], set()
    for case in search_cases:
        for row in case.get("results", []):
            url = row.get("url", "")
            parsed = urllib.parse.urlparse(url)
            if parsed.scheme in {"http", "https"} and parsed.netloc and url not in seen:
                selected.append({"query": case["query"], "url": url})
                seen.add(url)
                break
    if len(selected) < len(QUERIES):
        for case in search_cases:
            for row in case.get("results", []):
                url = row.get("url", "")
                if url not in seen and urllib.parse.urlparse(url).scheme in {"http", "https"}:
                    selected.append({"query": case["query"], "url": url,
                                     "supplemental": True})
                    seen.add(url)
                    if len(selected) == len(QUERIES):
                        return selected
    return selected


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mode", choices=("search", "search-fetch", "fetch", "render",
                                            "research"),
                        required=True)
    parser.add_argument("--api", required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--manifest", type=Path)
    parser.add_argument("--manifest-out", type=Path)
    parser.add_argument("--docker", default="docker")
    parser.add_argument("--container", action="append", default=[])
    args = parser.parse_args()
    base = args.api.rstrip("/")
    cases, resources = [], []
    stop = threading.Event()
    thread = None
    if args.container:
        thread = threading.Thread(target=sample_stats, args=(shlex.split(args.docker),
                                  args.container, stop, resources), daemon=True)
        thread.start()
        time.sleep(2)
    started = time.time()
    try:
        if args.mode in {"fetch", "render"}:
            if not args.manifest:
                parser.error("--manifest is required for fetch and render")
            manifest = json.loads(args.manifest.read_text(encoding="utf-8"))
            if args.mode == "render":
                workload = [("fixed-render-url", manifest[i]["url"])
                            for i in RENDER_INDICES]
            else:
                workload = [("fixed-url", item["url"]) for item in manifest]
        elif args.mode == "research":
            workload = [("research", question) for question in RESEARCH]
        else:
            workload = QUERIES
        for number, (category, value) in enumerate(workload, 1):
            if args.mode == "search":
                path, body = "/search", {"query": value, "limit": 3, "fresh": True}
            elif args.mode == "search-fetch":
                path, body = "/search-and-fetch", {
                    "query": value, "limit": 3, "fresh": True, "max_chars": 4000}
            elif args.mode in {"fetch", "render"}:
                path, body = "/fetch", {"urls": [value], "fresh": True,
                                        "max_chars": 4000}
                if args.mode == "render":
                    body["render"] = "always"
            else:
                path, body = "/research", {"question": value, "max_sources": 4,
                                           "fresh": True}
            response = api_call(base, path, body)
            rows = response["body"] if isinstance(response["body"], list) else []
            if args.mode == "research":
                bundle = response["body"] if isinstance(response["body"], dict) else {}
                sources = bundle.get("sources") or []
                item = {"source_count": len(sources),
                        "evidence_count": sum(len(s.get("evidence") or []) for s in sources),
                        "useful": bool(sources and any(s.get("evidence") for s in sources))}
            elif args.mode == "search":
                valid = [r for r in rows if r.get("url", "").startswith(("http://", "https://"))
                         and len(r.get("title") or "") >= 10]
                item = {"result_count": len(rows), "valid_result_count": len(valid),
                        "results": [{"url": r.get("url"), "title": r.get("title"),
                                     "engine": r.get("engine"),
                                     "snippet_chars": len(r.get("snippet") or "")}
                                    for r in rows], "useful": bool(valid)}
            else:
                good = [r for r in rows if r.get("quality") == "ok" and
                        len(r.get("content") or "") >= 600]
                item = {"result_count": len(rows), "good_count": len(good),
                        "thin_count": sum(r.get("quality") == "ok" and 0 <
                                          len(r.get("content") or "") < 600 for r in rows),
                        "failed_count": sum(r.get("quality") == "failed" for r in rows),
                        "chars_total": sum(len(r.get("content") or "") for r in rows),
                        "tiers": sorted({r.get("tier") for r in rows if r.get("tier")}),
                        "useful": bool(good)}
            case = {"number": number, "category": category,
                    "query" if args.mode not in {"fetch", "render"} else "url": value,
                    "elapsed_ms": response["elapsed_ms"],
                    "http_status": response["http_status"], "error": response["error"],
                    **item}
            cases.append(case)
            print(f"{number:02d}/{len(workload)} {response['elapsed_ms']:7.0f} ms "
                  f"{'OK' if case['useful'] else 'THIN/FAIL'} {value[:65]}", flush=True)
    finally:
        stop.set()
        if thread:
            thread.join(timeout=25)
    ended = time.time()
    output = {"meta": {"mode": args.mode, "api": base, "started_at_epoch": started,
                       "ended_at_epoch": ended, "duration_s": round(ended-started, 2),
                       "container_names": args.container},
              "summary": summarize(cases, resources), "cases": cases, "resource_samples": resources}
    if args.mode == "render":
        output["summary"]["crawl4ai_cases"] = sum(
            any(str(tier).startswith("crawl4ai/") for tier in case["tiers"])
            for case in cases)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(output, indent=2), encoding="utf-8")
    if args.mode == "search" and args.manifest_out:
        manifest = make_manifest(cases)
        args.manifest_out.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
        print(f"wrote {len(manifest)} fixed fetch URLs to {args.manifest_out}")
    print("summary:", json.dumps(output["summary"], indent=2), flush=True)
    print("wrote", args.out)


if __name__ == "__main__":
    main()
