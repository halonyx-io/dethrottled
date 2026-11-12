"""Guided Setup for the managed and checkout Compose stacks."""

import json
import os
import platform
import re
import shlex
import shutil
import sys
from collections import Counter
from pathlib import Path

GIB = 1024**3
PLAN_KEY = "x-dethrottled-guided"
DISK_GIB = {"default": 12, "media": 15, "layout": 19, "full": 22}


def cpu_capacities(root, allowed):
    try:
        values = [int((root / f"cpu{cpu}" / "cpu_capacity").read_text()) for cpu in allowed]
    except (OSError, ValueError):
        return []
    return values if values and min(values) > 0 else []


def inspect(engine, run):
    endpoint = os.getenv("DOCKER_HOST")
    if not endpoint or os.getenv("DOCKER_CONTEXT"):
        try:
            endpoint = run(["docker", "context", "inspect", "--format",
                            "{{.Endpoints.docker.Host}}"]).strip()
        except RuntimeError:
            endpoint = ""
    native = (sys.platform.startswith("linux") and endpoint.startswith("unix://")
              and "desktop" not in (engine.get("OperatingSystem") or "").lower()
              and "microsoft" not in platform.release().lower())
    available, total, disk, nodes, capacities = None, None, None, [], []
    if native:
        try:
            capacities = cpu_capacities(Path("/sys/devices/system/cpu"),
                                        os.sched_getaffinity(0))
        except (AttributeError, OSError):
            pass
        try:
            values = {parts[0]: int(parts[1]) * 1024
                      for line in Path("/proc/meminfo").read_text().splitlines()
                      if (parts := line.split()) and parts[0] in {"MemTotal:", "MemAvailable:"}}
            total, available = values.get("MemTotal:"), values.get("MemAvailable:")
        except (OSError, ValueError):
            pass
        try:
            if root := engine.get("DockerRootDir"):
                disk = shutil.disk_usage(root).free
        except OSError:
            pass
        for node in sorted(Path("/dev/dri").glob("renderD*")):
            try:
                if not node.is_char_device():
                    continue
                nodes.append({"path": str(node), "gid": node.stat().st_gid,
                              "accessible": os.access(node, os.R_OK | os.W_OK)})
            except OSError:
                continue
    return {"cpus": engine.get("NCPU"), "docker_ram": engine.get("MemTotal"),
            "host_ram": total, "available_ram": available, "disk_free": disk,
            "native": native, "gpu_nodes": nodes, "cpu_capacities": capacities}


def recommend(machine, usage, shared_host, profile):
    cpus = machine["cpus"] or 1
    capacities = machine.get("cpu_capacities") or []
    equivalent = min(cpus, sum(capacities) / max(capacities)) if capacities else cpus
    ram = (machine["docker_ram"] or 0) / GIB
    layout = profile in {"layout", "full"}
    strong = equivalent >= 8 and ram >= (16 if layout else 12)
    concurrency = 2 if strong and (usage != "one" or not shared_host) else 1
    if machine["available_ram"] is not None and machine["available_ram"] < 4 * GIB:
        concurrency = 1
    budget = min(4 if strong else 2, max(1, cpus // (4 if shared_host else 2)))
    if capacities:
        budget = min(budget, max(1, int(equivalent) // (2 if shared_host else 1)))
    threads = max(value for value in (1, 2, 4) if value <= budget)
    half = max(1, cpus // 2)
    return {"concurrency": concurrency, "threads": threads, "rerank_threads": half,
            "ocr_threads": min(8, half), "rerank": ram >= 6,
            "index": ram >= 6}


def override(project, port, profile, concurrency, threads, rerank, index, gpu, *,
             rerank_threads, ocr_threads=None):
    settings = {
        "DETHROTTLED_RENDER_CONCURRENCY": str(concurrency),
        "DETHROTTLED_RERANK": str(int(rerank)),
        "DETHROTTLED_RERANK_THREADS": str(rerank_threads),
        "DETHROTTLED_EMBED_THREADS": str(threads),
        "DETHROTTLED_CORPUS_AUTOINDEX": str(int(index)),
    }
    if ocr_threads is not None:
        settings["DETHROTTLED_OCR_THREADS"] = str(ocr_threads)
    browser = {"environment": {"DETHROTTLED_RENDER_CONCURRENCY": str(concurrency),
                               "DETHROTTLED_BROWSER_GRAPHICS": "auto" if gpu else "mesa"}}
    if gpu:
        browser.update(devices=[gpu["path"]], group_add=[str(gpu["gid"])])
    return {
        PLAN_KEY: {"version": 1, "project": project, "port": port, "profile": profile},
        "services": {
            "dethrottled": {"environment": settings},
            "dnb": browser,
            **{name: {"environment": {"OMP_NUM_THREADS": str(threads)}}
               for name in ("media-worker", "docling-worker")},
        },
    }


def load(path):
    plan = json.loads(path.read_text(encoding="utf-8"))
    meta = plan[PLAN_KEY]
    services = plan["services"]
    api = services["dethrottled"]["environment"]
    browser = services["dnb"]
    port, profile = meta["port"], meta["profile"]
    concurrency = int(api["DETHROTTLED_RENDER_CONCURRENCY"])
    threads = int(api["DETHROTTLED_EMBED_THREADS"])
    rerank_threads = int(api["DETHROTTLED_RERANK_THREADS"])
    ocr_threads = int(api["DETHROTTLED_OCR_THREADS"]) if "DETHROTTLED_OCR_THREADS" in api else None
    gpu = None
    if browser.get("devices"):
        node, = browser["devices"]
        gid, = browser["group_add"]
        if not re.fullmatch(r"/dev/dri/renderD[0-9]+", node) or not str(gid).isdigit():
            raise ValueError("Guided Setup can pass only an explicit DRM render node.")
        gpu = {"path": node, "gid": int(gid)}
    if (type(port) is not int or not 1 <= port <= 65535 or profile not in DISK_GIB
            or not 1 <= concurrency <= 2 or not 1 <= threads <= 8 or rerank_threads < 1
            or (ocr_threads is not None and not 1 <= ocr_threads <= 8)):
        raise ValueError("Guided Setup port, profile, concurrency or thread count is invalid.")
    expected = override(meta["project"], port, profile, concurrency, threads,
                        api["DETHROTTLED_RERANK"] == "1",
                        api["DETHROTTLED_CORPUS_AUTOINDEX"] == "1", gpu,
                        rerank_threads=rerank_threads, ocr_threads=ocr_threads)
    if plan != expected:
        raise ValueError("Expected a Guided Setup override with matching service limits.")
    return expected


def choose(title, explanation, options, recommended, ask):
    print(f"\n{title}\n{explanation}")
    values = list(options)
    for number, (key, label) in enumerate(options.items(), 1):
        print(f"  {number}. {label}" + (" [recommended]" if key == recommended else ""))
    while True:
        value = ask("Choose a number or press Enter for the recommendation: ").strip()
        if not value:
            return recommended
        if value.isdecimal() and 1 <= int(value) <= len(values):
            return values[int(value) - 1]
        print("Choose one of the listed numbers.")


def run_guided(args, engine, previous, existing, run, check_port, ask=input):
    machine = inspect(engine, run)

    def gib(value):
        return f"{value / GIB:.1f} GiB" if value is not None else "unknown"

    print("Dethrottled Guided Setup")
    print(f"Docker: {machine['cpus'] or 'unknown'} logical CPUs, {gib(machine['docker_ram'])} RAM")
    groups = Counter(machine.get("cpu_capacities") or [])
    if len(groups) > 1:
        summary = ", ".join(f"{count} at {capacity}" for capacity, count in sorted(groups.items()))
        print(f"Linux reports mixed CPU capacity groups: {summary} (relative units). "
              "Recommendations account for this; CPU placement stays with the scheduler.")
    print(f"Host: {gib(machine['host_ram'])} RAM visible to OS, "
          f"{gib(machine['available_ram'])} currently available")
    print(f"Free on Docker filesystem: {gib(machine['disk_free'])}")
    print(f"GPU render nodes detected: {len(machine['gpu_nodes'])}; "
          f"accessible: {sum(node['accessible'] for node in machine['gpu_nodes'])}. "
          "Chromium rendering has not been probed.")
    if not machine["native"]:
        print("Host disk, RAM headroom and GPU access are unverified for this Docker endpoint.")
    if machine["available_ram"] is not None and machine["available_ram"] < 4 * GIB:
        print("Current RAM headroom is low. Consider waiting for other workloads before starting.")
    active = [c for c in existing if c.get("State", {}).get("Running")]
    if active:
        print(f"This Compose project has {len(active)} running containers. "
              "Saving a plan leaves them running. Applying it can recreate affected services.")

    def pick(title, explanation, options, recommended):
        return choose(title, explanation, options, recommended, ask)

    usage = pick("How will you use Dethrottled?",
                 "More clients may benefit from parallel reads. Remote clients need authenticated "
                 "REST or MCP. This plan keeps the raw API on loopback.",
                 {"one": "One local agent or script", "local": "Several clients on this machine",
                  "remote": "Clients on other devices"}, "one")
    host = pick("Does this machine run other important workloads?",
                "Leave room for local models, other services or everyday desktop work.",
                {"shared": "Yes, leave headroom", "dedicated": "Mostly dedicated to Dethrottled"},
                "shared")
    profile = pick("Which readers do you need?",
                   "All profiles include web, browser, and the standard document reader. "
                   "Advanced layout and speech may download model weights on first use.",
                   {"default": "Default", "media": "Add speech transcription",
                    "layout": "Add advanced PDF layout", "full": "Add both"},
                   args.profile or previous.get("profile", "default"))
    disk = machine["disk_free"]
    estimate = DISK_GIB[profile]
    print(f"Allow roughly {estimate} GiB free for a fresh {profile} build. "
          "This is a planning estimate; cache and retained data vary.")
    if disk is not None and disk < estimate * GIB:
        print("The selected build may run out of disk. Free space or choose a smaller profile.")
    if profile in {"layout", "full"} and (machine["docker_ram"] or 0) < 16 * GIB:
        print("Layout inference can overlap with other workers. Prefer one render slot here.")
    advice = recommend(machine, usage, host == "shared", profile)
    concurrency = pick("How many browser render jobs should run at once?",
                       "Extra slots help simultaneous clients when CPU and RAM allow. "
                       "A single slot queues overlapping renders.",
                       {1: "One render slot", 2: "Two render slots"}, advice["concurrency"])
    threads = pick("How many CPU threads for embeddings and optional workers?",
                   "Fewer threads leave CPU for other requests.",
                   {1: "One thread", 2: "Two threads", 4: "Four threads", 8: "Eight threads"},
                   advice["threads"])
    rerank = pick("Use the local search reranker?",
                  "Ettin improves candidate ordering when it loads and adds local inference work.",
                  {True: "Enable Ettin", False: "Use provider ranking"}, advice["rerank"])
    rerank_threads = advice["rerank_threads"]
    if rerank:
        options = {n: f"{n} threads" for n in sorted({1, 2, 4, 8, rerank_threads})
                   if n <= (machine["cpus"] or 1)}
        rerank_threads = pick("How many CPU threads for the reranker?",
                              "Half the logical CPUs visible to Docker is the starting point.",
                              options, rerank_threads)
    ocr_threads = pick("How many CPU threads per API-side OCR process?",
                       "Half the visible CPUs, up to eight, leaves room for overlapping work. "
                       "Docling keeps its own worker budget.",
                       {n: f"{n} threads" for n in sorted({1, 2, 4, 8, advice["ocr_threads"]})
                        if n <= (machine["cpus"] or 1)}, advice["ocr_threads"])
    index = pick("Automatically add eligible public reads to the corpus?",
                 "This adds background indexing. Turning it off preserves the existing corpus "
                 "and its normal retention policy.",
                 {True: "Index eligible reads", False: "Pause automatic indexing"}, advice["index"])
    gpu = next((node for node in machine["gpu_nodes"] if node["accessible"]), None)
    if gpu and pick("Try GPU rendering?",
                    "Pass the detected render node to Chromium. Hardware use is verified only "
                    "when DNB starts; software fallback remains available.",
                    {"software": "Software", "gpu": f"Try {gpu['path']}"}, "software") != "gpu":
        gpu = None
    port = args.port or previous.get("port", 8787)
    if machine["native"]:
        while not any(binding.get("HostPort") == str(port)
                      for c in active if c["Config"]["Labels"]["com.docker.compose.service"]
                      == "dethrottled"
                      for binding in c["NetworkSettings"]["Ports"].get("8787/tcp") or []):
            try:
                check_port(port)
                break
            except RuntimeError:
                print(f"Loopback port {port} is already in use.")
                value = ask("Choose another port: ").strip()
                if value.isdecimal() and 1 <= int(value) <= 65535:
                    port = int(value)
    plan = override(args.project, port, profile, concurrency, threads, rerank, index, gpu,
                    rerank_threads=rerank_threads, ocr_threads=ocr_threads)
    if previous.get("guided"):
        print("\nCurrent saved settings:")
        print(json.dumps(previous["guided"], indent=2))
    print("\nProposed Compose override:")
    print(json.dumps(plan, indent=2))
    output = args.output or Path("dethrottled.guided.json")
    if ask(f"Save to {output}? [y/N] ").strip().lower() not in {"y", "yes"}:
        print("No configuration saved.")
        return 0
    with output.open("x", encoding="utf-8") as stream:
        json.dump(plan, stream, indent=2)
        stream.write("\n")
    print("Saved. To apply the plan to the managed stack:")
    print(f"dethrottled stack up --config {shlex.quote(str(output))}")
    print("From a GitHub checkout, using a POSIX shell:")
    profiles = f" --profile {profile}" if profile != "default" else ""
    print(f"DETHROTTLED_BIND=127.0.0.1 DETHROTTLED_PORT={port} docker compose -p {args.project}"
          f" -f docker-compose.yml -f {shlex.quote(str(output.resolve()))}{profiles} up -d --build")
    if usage == "remote":
        print("Set up authenticated REST/MCP separately using docs/PUBLIC-ACCESS.md.")
    return 0
