#!/usr/bin/env python3
"""Assert captured facts/actions, then prove checkpoint restore across restart."""

import argparse
import base64
import json
import subprocess
import time
from pathlib import Path

from compare import BROWSERS, FIXTURE, request


def verify(directory):
    summary = json.loads((directory / "summary.json").read_text())
    checks = {}
    for side in BROWSERS:
        rows = [r for r in summary["records"] if r["side"] == side]
        assert len(rows) == 15
        assert all(all(r["facts"].values()) for r in rows), side
        assert all(r["target_status"] == 404 for r in rows if r["path"] == "/missing")
        run = json.loads((directory / f"drive-{side}.json").read_text())["run"]["body"]
        steps = run["steps"]
        assert run["ok"] and len({s["action"] for s in steps}) == 27, side
        assert [s["data"] for s in steps if s["action"] == "text"] == [
            "confirmed-928",
            "Frame fact gold-214",
        ]
        snapshot = next(s["data"] for s in steps if s["action"] == "snapshot")
        assert next(row for row in snapshot if row.get("id") == "name")["text"] == "Ada Lovelace"
        download = next(s["data"] for s in steps if s["action"] == "download")
        assert base64.b64decode(download["download_b64"]) == b"download-copper-823\n"
        network = next(s["data"] for s in steps if s["action"] == "network")
        assert "network-jade-718" in network["content"] and run.get("screenshot_b64")
        concurrent = json.loads((directory / f"concurrent-{side}.json").read_text())
        assert all(r["http_status"] == 200 for r in concurrent)
        assert all(r["body"].get("success", r["body"].get("ok")) for r in concurrent)
        checks[side] = {
            "facts": sum(len(r["facts"]) for r in rows),
            "actions": 27,
            "download_exact": True,
            "network_fact": True,
            "concurrent": True,
        }
        # A real restart, unlike close_session, retains the checkpoint.
        base = BROWSERS[side]
        result = request(
            base,
            "/drive",
            {
                "url": FIXTURE + "/article",
                "session": "restart-proof",
                "allowed_hosts": ["fixture"],
                "steps": [{"action": "click", "selector": "#go"}, {"action": "checkpoint"}],
                "screenshot": "never",
            },
        )
        assert result["body"].get("ok"), result
        service = "reference-browser" if side == "reference" else "candidate"
        subprocess.run(
            [
                "docker",
                "compose",
                "-f",
                str(Path(__file__).with_name("compose.yml")),
                "restart",
                service,
            ],
            check=True,
            capture_output=True,
        )
        for _ in range(40):
            time.sleep(0.5)
            if request(base, "/health")["http_status"] == 200:
                break
        restored = request(
            base,
            "/drive",
            {
                "session": "restart-proof",
                "allowed_hosts": ["fixture"],
                "steps": [
                    {"action": "read_state"},
                    {"action": "attr", "selector": "#name", "name": "id"},
                ],
                "screenshot": "never",
            },
        )
        assert restored["body"].get("ok"), restored
        assert restored["body"]["session"]["restored_from_checkpoint"], restored
        assert restored["body"]["steps"][-1]["data"] == "name"
        (directory / f"checkpoint-{side}.json").write_text(json.dumps(restored, indent=2) + "\n")
        checks[side]["checkpoint_restart_restored"] = True
        request(base, "/drive", {"session": "restart-proof", "close_session": True})
    (directory / "verification.json").write_text(json.dumps(checks, indent=2) + "\n")
    print(json.dumps(checks))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("directory", type=Path)
    verify(parser.parse_args().directory)
