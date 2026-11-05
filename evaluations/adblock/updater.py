"""Opt-in real conditional-update/restart check; writes the list only to --directory."""

import argparse
import json
import time
import urllib.error
import urllib.request
from pathlib import Path

from dethrottled.adblock import Filter

parser = argparse.ArgumentParser()
parser.add_argument("--directory", required=True)
parser.add_argument("--output", required=True)
args = parser.parse_args()
attempts = []


def opener(request, **kwargs):
    start = time.monotonic()
    try:
        response = urllib.request.urlopen(request, **kwargs)
    except urllib.error.HTTPError as exc:
        if exc.code != 304:
            raise
        response = exc
    attempts.append(
        {
            "source": request.full_url,
            "http": response.code,
            "conditional": request.has_header("If-none-match")
            or request.has_header("If-modified-since"),
            "header_ms": (time.monotonic() - start) * 1000,
        }
    )
    return response


manager = Filter(args.directory)
manager.load()
manager.update(opener)
first = manager.status()
manager.update(opener)
second = manager.status()
restored = Filter(args.directory)
restored.load()
report = {
    "first": first,
    "second": second,
    "attempts": attempts,
    "restart_restores_identical_rules": bool(manager.rules)
    and restored.rules == manager.rules
    and restored.metadata == manager.metadata,
}
Path(args.output).write_text(json.dumps(report, indent=2) + "\n")
assert first["available"] and not first["error"] and not second["error"]
assert report["restart_restores_identical_rules"]
print(json.dumps({"passed": True, "http": [a["http"] for a in attempts]}))
