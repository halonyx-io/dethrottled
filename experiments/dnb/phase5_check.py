"""Phase 5 lab matrix: headed/headless x software/verified hardware.

Starts one disposable worker at a time on 19888, runs the same fixture workload,
and writes bounded evidence. No production state, no live providers, no source
mounts. Requires the phase-5 image with browser-search/service.py.
"""

import argparse
import json
import subprocess
import sys
import time
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[2]
FIXTURE = "http://127.0.0.1:8090"
WORKER = "http://127.0.0.1:19888"
WORKLOADS = {
    "/article": ["cobalt-731", "amber-592", "violet-683"],
    "/tiny": ["quartz-452"],
    "/long": ["cobalt-731", "amber-592"],
    "/ticker": ["violet-683"],
    "/redirect": ["cobalt-731", "amber-592", "violet-683"],
    "/missing": [],
}
MODES = [
    {"name": "headed-software", "headless": "0", "graphics": "mesa", "device": False},
    {"name": "headed-hardware", "headless": "0", "graphics": "auto", "device": True},
    {"name": "headed-hardware-unmapped", "headless": "0", "graphics": "auto",
     "device": True, "groups": False},
    {"name": "headless-software", "headless": "1", "graphics": "mesa", "device": False},
    {"name": "headless-hardware", "headless": "1", "graphics": "auto", "device": True},
]


def docker(*args, check=True):
    return subprocess.run(["docker", *args], check=check, capture_output=True, text=True)


def gpu_sample():
    base = Path("/sys/class/drm/card0/device")
    out = {}
    for name in ("gpu_busy_percent", "mem_info_vram_used", "mem_info_gtt_used"):
        try:
            out[name] = int((base / name).read_text().strip())
        except (OSError, ValueError):
            out[name] = None
    return out


def container_stats(name):
    raw = docker("stats", "--no-stream", "--format", "{{json .}}", name).stdout.strip()
    try:
        return json.loads(raw)
    except ValueError:
        return {}


def wait_health(client, limit=120):
    deadline = time.monotonic() + limit
    while time.monotonic() < deadline:
        try:
            response = client.get(WORKER + "/health", timeout=2)
            if response.status_code == 200:
                return response.json()
        except httpx.HTTPError:
            pass
        time.sleep(0.5)
    raise AssertionError("worker did not become healthy")


def start_worker(mode, image):
    name = "p5-" + mode["name"]
    docker("rm", "-f", name, check=False)
    command = ["run", "-d", "--name", name, "--network", "host"]
    if mode["device"]:
        command += ["--device", "/dev/dri"]
        if mode.get("groups", True):
            command += ["--group-add", "991", "--group-add", "44"]
    command += [
        "-e", "DETHROTTLED_BROWSER_GRAPHICS=" + mode["graphics"],
        "-e", "DETHROTTLED_BROWSER_HEADLESS=" + mode["headless"],
        "-e", "DNB_ALLOW_INTERNAL_URLS=true",
        image,
    ]
    docker(*command)
    return name


def crawl(client, path):
    body = {
        "urls": [FIXTURE + path],
        "browser_config": {"type": "BrowserConfig", "params": {"headless": True}},
    }
    started = time.perf_counter()
    response = client.post(WORKER + "/crawl", json=body, timeout=90)
    elapsed = round((time.perf_counter() - started) * 1000, 2)
    try:
        data = response.json()
    except ValueError:
        data = {"raw": response.text[:200]}
    text = json.dumps(data)
    facts = WORKLOADS[path]
    return {
        "path": path,
        "status": response.status_code,
        "elapsed_ms": elapsed,
        "success": bool(data.get("success")),
        "facts_present": all(fact in text for fact in facts) if facts else None,
        "reason": data.get("error_message") or data.get("results", [{}])[0].get("error_message"),
    }


def screenshot(client, mode):
    body = {
        "session": "p5-" + mode["name"],
        "url": FIXTURE + "/long",
        "steps": [{"action": "read_state"}],
        "screenshot": "always",
        "timeout_ms": 60000,
        "allowed_hosts": [],
    }
    started = time.perf_counter()
    response = client.post(WORKER + "/drive", json=body, timeout=90)
    elapsed = round((time.perf_counter() - started) * 1000, 2)
    try:
        data = response.json()
    except ValueError:
        data = {}
    client.post(WORKER + "/drive", json={"session": body["session"], "close_session": True})
    image = data.get("screenshot_b64") or ""
    return {
        "status": response.status_code,
        "elapsed_ms": elapsed,
        "ok": bool(data.get("ok")),
        "screenshot_bytes": len(image) * 3 // 4 if image else 0,
        "screenshot_error": data.get("screenshot_error"),
    }


def run_mode(client, mode, image, repeats):
    name = start_worker(mode, image)
    before = gpu_sample()
    record = {"mode": mode, "gpu_before": before}
    try:
        try:
            health = wait_health(client)
        except Exception:
            logs = docker("logs", name, check=False)
            print("WORKER LOGS\n" + logs.stdout[-2000:] + "\nSTDERR\n" + logs.stderr[-2000:])
            raise
        record["graphics"] = health.get("graphics")
        record["restart_count_before"] = docker(
            "inspect", "--format", "{{.RestartCount}}", name).stdout.strip()
        results = []
        for path in WORKLOADS:
            if path in {"/redirect", "/missing"}:
                time.sleep(1.0)  # paced recovery target
            for _ in range(repeats):
                results.append(crawl(client, path))
        record["workloads"] = results
        shots = [screenshot(client, mode) for _ in range(repeats)]
        record["screenshots"] = shots
        record["screenshot"] = shots[-1]
        record["stats"] = container_stats(name)
        record["gpu_after"] = gpu_sample()
        record["health_after"] = client.get(WORKER + "/health", timeout=5).status_code
        record["restart_count_after"] = docker(
            "inspect", "--format", "{{.RestartCount}}", name).stdout.strip()
    finally:
        docker("rm", "-f", name, check=False)
    return record


def main(args):
    output = Path(args.output)
    output.mkdir(parents=True, exist_ok=True)
    fixture = None
    client = httpx.Client(timeout=120)
    try:
        try:
            client.get(FIXTURE + "/tiny", timeout=1)
        except httpx.HTTPError:
            fixture = subprocess.Popen(
                [sys.executable, str(ROOT / "experiments/dnb/fixture.py")],
                cwd=ROOT, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            )
            time.sleep(1)
        records = []
        for mode in MODES:
            if mode["device"] and not Path("/dev/dri/renderD128").exists():
                records.append({"mode": mode, "skipped": "no /dev/dri/renderD128"})
                continue
            records.append(run_mode(client, mode, args.image, args.repeats))
        (output / "phase5-matrix.json").write_text(
            json.dumps({"modes": records}, indent=2) + "\n")
        summary = []
        for record in records:
            if "skipped" in record:
                summary.append({"mode": record["mode"]["name"], "skipped": record["skipped"]})
                continue
            workloads = record["workloads"]
            summary.append({
                "mode": record["mode"]["name"],
                "graphics": record.get("graphics"),
                "requests": len(workloads),
                "failures": sum(not item["success"] for item in workloads),
                "facts_failed": sum(item["facts_present"] is False for item in workloads),
                "median_ms": sorted(item["elapsed_ms"] for item in workloads)[len(workloads)//2],
                "screenshot": record["screenshot"],
                "screenshot_median_ms": sorted(item["elapsed_ms"] for item in record["screenshots"])[len(record["screenshots"])//2],
                "screenshot_bytes": record["screenshot"]["screenshot_bytes"],
                "screenshot_failures": sum(not item["ok"] for item in record["screenshots"]),
                "cpu_percent": record["stats"].get("CPUPerc"),
                "mem_usage": record["stats"].get("MemUsage"),
                "restarts": [record["restart_count_before"], record["restart_count_after"]],
                "gpu_before": record["gpu_before"],
                "gpu_after": record["gpu_after"],
            })
        (output / "phase5-summary.json").write_text(json.dumps(summary, indent=2) + "\n")
        print(json.dumps(summary, indent=2))
    finally:
        client.close()
        if fixture is not None:
            fixture.terminate()
            try:
                fixture.wait(timeout=5)
            except subprocess.TimeoutExpired:
                fixture.kill()
    return 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--image", default="dethrottled-dnb:phase5-20261109")
    parser.add_argument("--output", default="experiments/dnb/results/2026-11-09")
    parser.add_argument("--repeats", type=int, default=3)
    args = parser.parse_args()
    raise SystemExit(main(args))
