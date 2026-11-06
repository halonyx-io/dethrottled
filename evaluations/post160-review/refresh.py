"""Compare unchanged refreshes on identical real rules in disposable directories."""

import argparse
import io
import json
import tempfile
import time
from pathlib import Path

from dethrottled import adblock


class Reply(io.BytesIO):
    def __init__(self, code):
        super().__init__()
        self.code, self.headers = code, {}


def run(snapshot):
    with tempfile.TemporaryDirectory() as directory:
        path = Path(directory) / "multi-pro.json"
        path.write_bytes(Path(snapshot).read_bytes())
        writer = adblock.Filter(directory)
        writer.load()
        readers = [adblock.Filter(directory, reader=True) for _ in range(3)]
        for reader in readers:
            reader.load()
        old_rules = [r.rules for r in readers]
        original = adblock.parse
        parses = []

        def measured(data):
            started = time.process_time()
            result = original(data)
            parses.append(time.process_time() - started)
            return result

        adblock.parse = measured
        started, cpu = time.perf_counter(), time.process_time()
        writer.update(lambda *a, **k: Reply(304), now=writer.last_check + 86400)
        for reader in readers:
            reader.load()
        return {
            "rule_count": len(writer.rules),
            "sha256": writer.metadata["sha256"],
            "seconds": time.perf_counter() - started,
            "cpu_seconds": time.process_time() - cpu,
            "parse_calls": len(parses),
            "parse_cpu_seconds": sum(parses),
            "reader_rules_reused": [r.rules is old for r, old in zip(readers, old_rules)],
            "durable_last_check": readers[0].last_check,
            "content_updated_at": readers[0].metadata["updated_at"],
        }


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--snapshot", default="/tmp/list.json")
    parser.add_argument("--label", required=True)
    args = parser.parse_args()
    print(json.dumps({"label": args.label, **run(args.snapshot)}, indent=2))
