"""Keep native model backfill outside API interpreter shutdown."""

import json
import os
import signal
import subprocess
import sys
import threading


class BackfillJob:
    def __init__(self):
        self.state = {"status": "disabled", "passages": 0}
        self.process = None
        self.watcher = None
        self.stopping = False

    def start(self, command=None):
        self.stopping = False
        self.process = subprocess.Popen(
            command or [sys.executable, "-m", "dethrottled.backfill"],
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
        self.state["status"] = "running"

        def watch():
            output, _ = self.process.communicate()
            if self.stopping:
                self.state["status"] = "interrupted"
            elif self.process.returncode:
                self.state.update(status="failed", exit_code=self.process.returncode)
            else:
                try:
                    self.state.update(status="complete", passages=json.loads(output)["passages"])
                except (ValueError, KeyError):
                    self.state["status"] = "invalid_child_output"

        self.watcher = threading.Thread(target=watch, daemon=True, name="backfill-supervisor")
        self.watcher.start()

    def stop(self):
        if self.process is not None and self.process.poll() is None:
            self.stopping = True
            try:
                os.killpg(self.process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            self.process.wait(timeout=5)
        if self.watcher is not None:
            self.watcher.join(timeout=5)


if __name__ == "__main__":
    from .corpus import backfill_multilingual

    print(json.dumps({"passages": backfill_multilingual()}))
