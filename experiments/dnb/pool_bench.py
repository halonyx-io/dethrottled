#!/usr/bin/env python3
"""Small controlled context-reuse comparison; no external search/source traffic."""

import argparse
import hashlib
import json
import statistics
import subprocess
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from html.parser import HTMLParser
from pathlib import Path

from compare import FIXTURE
from measure import cpu, stats

TOKEN = "dnb-disposable-lab-only"
BASE = "http://127.0.0.1:19983"
MODES = ["reference", "anonymous", "fresh", "persistent"]


def render(
    mode,
    path="/article",
    owner="bench",
    session="default",
    delay=0.5,
    scope="fixture-public",
    hosts="",
    public_only=None,
    headless=True,
):
    base = "http://127.0.0.1:19982" if mode == "reference" else BASE
    headers = {"Content-Type": "application/json", "Authorization": "Bearer " + TOKEN}
    if mode in {"fresh", "persistent"}:
        headers.update(
            {
                "x-dnb-owner": owner,
                "x-dnb-session": session,
                "x-dnb-page": mode,
                "x-dnb-scope": scope,
                "x-dnb-allowed-hosts": hosts,
                **(
                    {"x-dnb-public-only": "1" if public_only else "0"}
                    if public_only is not None
                    else {}
                ),
            }
        )
    payload = {
        "urls": [FIXTURE + path],
        "browser_config": {"type": "BrowserConfig", "params": {"headless": headless}},
        "crawler_config": {
            "type": "CrawlerRunConfig",
            "params": {
                "cache_mode": "bypass",
                "check_robots_txt": False,
                "page_timeout": 10000,
                "delay_before_return_html": delay,
                **({"wait_for": "css:#ready"} if path.startswith("/state") else {}),
            },
        },
    }
    start = time.perf_counter()
    req = urllib.request.Request(
        base + "/crawl", data=json.dumps(payload).encode(), headers=headers
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as response:
            body = json.load(response)
            status = response.status
    except urllib.error.HTTPError as exc:
        body = json.load(exc)
        status = exc.code
    return {"http": status, "ms": (time.perf_counter() - start) * 1000, "body": body}


class StateParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.inside = False
        self.text = ""

    def handle_starttag(self, tag, attrs):
        if tag == "pre":
            self.inside = True

    def handle_endtag(self, tag):
        if tag == "pre":
            self.inside = False

    def handle_data(self, data):
        if self.inside:
            self.text += data


def state(mode, owner, session="default", seed=""):
    response = render(mode, "/state" + ("?set=" + seed if seed else ""), owner, session, delay=0)
    assert response["http"] == 200, response
    row = response["body"]["results"][0]
    parser = StateParser()
    parser.feed(row["html"])
    return json.loads(parser.text)


def isolation():
    checks = {}
    for mode in ["fresh", "persistent"]:
        a = state(mode, "alice", seed="alice-proof")
        b = state(mode, "bob")
        again = state(mode, "alice")
        other_session = state(mode, "alice", session="separate")
        assert a["local"] == a["idb"] == "alice-proof" and "alice-proof" in a["cookie"]
        assert not b["local"] and not b["idb"] and "alice-proof" not in b["cookie"]
        assert again["local"] == again["idb"] == "alice-proof" and "alice-proof" in again["cookie"]
        assert (again["session"] == "alice-proof") == (mode == "persistent")
        assert not other_session["local"] and not other_session["idb"]
        checks[mode] = {
            "same_owner_storage_retained": True,
            "other_owner_isolated": True,
            "other_session_isolated": True,
            "fresh_page_resets_session_storage": mode == "fresh",
        }
    assert state("anonymous", "ignored", seed="anonymous-proof")["local"] == "anonymous-proof"
    assert state("anonymous", "ignored")["local"] is None
    # Capacity four: inserting five independent owners must destroy the eldest.
    state("fresh", "evicted-owner", seed="discard-me")
    for n in range(4):
        state("fresh", "new-owner-" + str(n))
    assert state("fresh", "evicted-owner")["local"] is None
    checks["anonymous_isolated"] = True
    checks["lru_destroys_state"] = True
    # Busy session is rejected rather than concurrently mutating the same page.
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: render("fresh", owner="busy-owner", delay=0.5), range(2)))
    assert sorted(r["http"] for r in results) == [200, 409], results
    checks["same_session_concurrent_rejected"] = True
    # Unauthenticated caller cannot select somebody else's pool identity.
    req = urllib.request.Request(
        BASE + "/crawl",
        data=json.dumps({"urls": [FIXTURE + "/article"]}).encode(),
        headers={"Content-Type": "application/json", "x-dnb-owner": "alice"},
    )
    try:
        urllib.request.urlopen(req, timeout=5)
        raise AssertionError("unauthorized owner accepted")
    except urllib.error.HTTPError as exc:
        assert exc.code == 403
    checks["untrusted_identity_rejected"] = True
    return checks


def main(output):
    output.mkdir(parents=True, exist_ok=True)
    checks = isolation()
    records = []
    for mode in MODES:
        render(mode)
    for repeat, order in enumerate(
        [MODES, list(reversed(MODES)), ["fresh", "reference", "persistent", "anonymous"]]
    ):
        for mode in order:
            side = "reference" if mode == "reference" else "candidate"
            before = cpu(side)
            rows = [render(mode) for _ in range(4)]
            consumed = (cpu(side) - before) / 1_000_000
            captures = []
            for response in rows:
                row = response["body"]["results"][0]
                md = row["markdown"]["raw_markdown"]
                assert row["success"] and all(
                    f in md for f in ["cobalt-731", "amber-592", "violet-683"]
                )
                captures.append(
                    {
                        "ms": response["ms"],
                        "facts": 3,
                        "markdown_sha256": hashlib.sha256(md.encode()).hexdigest(),
                        "reused": row.get("dnb", {}).get("context_reused"),
                    }
                )
            records.append(
                {
                    "mode": mode,
                    "repeat": repeat,
                    "cpu_seconds": consumed,
                    "requests": captures,
                    "working_set_snapshot": stats(),
                }
            )
    summary = {}
    for mode in MODES:
        rows = [r for r in records if r["mode"] == mode]
        summary[mode] = {
            "reads": 12,
            "facts": 36,
            "median_ms": statistics.median(x["ms"] for r in rows for x in r["requests"]),
            "median_cpu_seconds_per_4": statistics.median(r["cpu_seconds"] for r in rows),
        }
    # Preserve measurements before any restart/readiness diagnostic can fail.
    (output / "measurements.json").write_text(
        json.dumps({"isolation": checks, "summary": summary, "records": records}, indent=2) + "\n"
    )
    # In-memory contexts must not survive a restart.
    state("fresh", "restart-owner", seed="restart-proof")
    subprocess.run(
        [
            "docker",
            "compose",
            "-f",
            str(Path(__file__).with_name("compose.yml")),
            "restart",
            "candidate",
        ],
        check=True,
        capture_output=True,
    )
    for _ in range(40):
        time.sleep(0.5)
        try:
            with urllib.request.urlopen(BASE + "/health", timeout=2) as response:
                healthy = response.status == 200
            if healthy and state("fresh", "restart-owner")["local"] is None:
                break
        except (urllib.error.URLError, ConnectionError):
            continue
    else:
        raise AssertionError("restart did not clear retained contexts")
    checks["restart_drops_state"] = True
    result = {
        "isolation": checks,
        "summary": summary,
        "records": records,
        "scope": "one host; 12 warm renders per variant; 0.5-second settle; no live providers",
    }
    (output / "results.json").write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps({"isolation": checks, "summary": summary}))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("output", type=Path)
    main(parser.parse_args().output)
