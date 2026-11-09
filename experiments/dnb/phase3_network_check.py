"""Real-network check for the adapter identity hop.

Starts a disposable core on 0.0.0.0 and proves that the forwarded caller
credential is accepted only from a configured adapter peer. No assertion key is
involved; this is the generic adapter contract.
"""

import argparse
import json
import os
import socket
import subprocess
import sys
import time
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[2]


def lan_address():
    probe = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        probe.connect(("192.0.2.1", 9))
        return probe.getsockname()[0]
    finally:
        probe.close()


def curl(url, token, interface=None):
    command = ["curl", "-sS", "-m", "10", "-o", "/dev/null", "-w", "%{http_code}"]
    if interface:
        command += ["--interface", interface]
    command += ["-H", "X-Dethrottled-Caller-Authorization: Bearer " + token, url]
    result = subprocess.run(command, capture_output=True, text=True)
    return result.stdout.strip() or result.stderr.strip()


def main(args):
    output = Path(args.output)
    output.mkdir(parents=True, exist_ok=True)
    token = json.loads(Path(args.tokens).read_text())["alice"]
    env = {
        **os.environ,
        "PYTHONPATH": str(ROOT / "src"),
        "DETHROTTLED_DNB": "1",
        "DETHROTTLED_BROWSER_SEARCH_URL": args.worker,
        "DETHROTTLED_CRAWL4AI_URL": args.worker,
        "DETHROTTLED_DNB_PRIVATE_KEY": args.private_key,
        "DETHROTTLED_DNB_PUBLIC_KEY": args.public_key,
        "DETHROTTLED_ADAPTER_CIDRS": "127.0.0.1/32,::1/128",
        "DETHROTTLED_CALLER_REGISTRY": args.registry,
        "DETHROTTLED_TOKEN_REGISTRY": args.registry,
        "DETHROTTLED_DATA_DIR": str(output),
        "DETHROTTLED_CORPUS_SCHEMA": "2",
        "DETHROTTLED_ADBLOCK": "0",
    }
    log = (output / "network-core.log").open("wb")
    process = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "dethrottled.server:app",
         "--host", "0.0.0.0", "--port", str(args.port)],
        cwd=ROOT, env=env, stdout=log, stderr=subprocess.STDOUT,
    )
    base = f"http://127.0.0.1:{args.port}"
    lan = lan_address()
    try:
        deadline = time.monotonic() + 30
        while time.monotonic() < deadline:
            try:
                if httpx.get(base + "/health", timeout=1).status_code == 200:
                    break
            except httpx.HTTPError:
                pass
            time.sleep(0.2)
        else:
            raise AssertionError("disposable core did not start")
        path = "/v2/capabilities"
        trusted = curl(base + path, token)
        untrusted = curl(f"http://{lan}:{args.port}{path}", token, interface=lan)
        result = {
            "lan_address": lan,
            "trusted_loopback_status": int(trusted),
            "untrusted_lan_status": int(untrusted),
            "passed": int(trusted) == 200 and int(untrusted) == 403,
        }
    finally:
        process.terminate()
        try:
            process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            process.kill()
        log.close()
    (output / "phase3-network.json").write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps(result, indent=2))
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=19985)
    parser.add_argument("--worker", default="http://127.0.0.1:19888")
    parser.add_argument("--registry", default="/tmp/opencode/p3/registry.json")
    parser.add_argument("--tokens", default="/tmp/opencode/p3/tokens.json")
    parser.add_argument("--private-key", default="/tmp/opencode/p3/keys/private.pem")
    parser.add_argument("--public-key", default="/tmp/opencode/p3/keys/public.pem")
    parser.add_argument("--output", default="/tmp/opencode/p3")
    args = parser.parse_args()
    raise SystemExit(main(args))
