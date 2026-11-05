"""Native API crash/restart, public read and graceful index shutdown smoke."""

import json
import os
import platform
import signal
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

from dethrottled.corpus_v2 import CorpusV2

URL = "http://127.0.0.1:17897"


def request(path, body=None):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(
        URL + path, data=data, headers={"Content-Type": "application/json"}
    )
    with urllib.request.urlopen(req, timeout=10) as response:
        return json.load(response)


def wait(test, timeout=90):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            value = test()
            if value:
                return value
        except (OSError, ValueError):
            pass
        time.sleep(0.005)
    raise TimeoutError("lifecycle condition not satisfied")


def main():
    root = Path(os.environ["DETHROTTLED_DATA_DIR"])
    obj = CorpusV2()
    log = (root / "api.log").open("w")
    events = []
    env = dict(
        os.environ,
        DETHROTTLED_AUTO_WORKERS="0",
        DETHROTTLED_SEARXNG_URL="",
        DETHROTTLED_CRAWL4AI_URL="",
        DETHROTTLED_BROWSER_SEARCH_URL="",
    )
    process = None

    def boot():
        proc = subprocess.Popen(
            [sys.executable, "-m", "dethrottled.server", "--port", "17897"],
            stdout=log,
            stderr=log,
            env=env,
            start_new_session=True,
        )
        wait(lambda: request("/health"))
        return proc

    def enqueue(version):
        text = "\n\n".join(
            "## Section %d\n" % i
            + ("Version %d section %d describes the retained lifecycle evidence. " % (version, i))
            * 8
            for i in range(150)
        )
        text += "\n\nLIFECYCLE-FACT-1234567: version %d. LIFECYCLE-VERSION-%d-1234567" % (
            version,
            version,
        )
        return obj.enqueue(
            "https://example.org/lifecycle", "Lifecycle", text, {"corpus_visibility": "public"}
        )

    try:
        enqueue(1)
        process = boot()
        wait(lambda: obj.status()["jobs"].get("completed"))
        first = request("/corpus/search?q=LIFECYCLE-FACT-1234567&mode=hybrid")["results"][0]
        for namespace in ("agent-one", "agent-two"):
            doc = request(
                "/documents/read",
                {
                    "document_id": first["document_id"],
                    "evidence_namespace": namespace,
                    "max_chars": 1000000,
                },
            )
            assert "version 1" in json.dumps(doc)
        events.append({"test": "cross-agent public retained read + hybrid HTTP", "passed": True})
        enqueue(2)
        wait(lambda: obj.status()["jobs"].get("running"))
        os.killpg(process.pid, signal.SIGKILL)
        process.wait(timeout=10)
        assert obj.search("LIFECYCLE-VERSION-1-1234567", mode="lexical")
        assert obj.status()["jobs"].get("running")
        events.append(
            {"test": "SIGKILL during indexing preserves prior active version", "passed": True}
        )
        # Advance the durable lease rather than sleeping two minutes. This is
        # explicitly simulated clock expiry, not an upstream recovery claim.
        with obj.db:
            obj.db.execute("UPDATE index_jobs SET expires=0")
        process = boot()
        wait(
            lambda: (
                not obj.status()["jobs"].get("running")
                and obj.search("LIFECYCLE-VERSION-2-1234567", mode="lexical")
            )
        )
        assert not obj.search("LIFECYCLE-VERSION-1-1234567", mode="lexical")
        events.append(
            {
                "test": "restart + simulated lease expiry promotes complete replacement",
                "passed": True,
            }
        )
        enqueue(3)
        wait(lambda: obj.status()["jobs"].get("running"))
        before = time.monotonic()
        process.terminate()
        code = process.wait(timeout=35)
        assert code in (0, -signal.SIGTERM), code
        events.append(
            {
                "test": "SIGTERM during native inference exits cleanly",
                "passed": True,
                "seconds": time.monotonic() - before,
                "exit_code": code,
            }
        )
        report = {"architecture": platform.machine(), "events": events, "status": obj.status()}
        (root / "lifecycle.json").write_text(json.dumps(report, indent=2) + "\n")
        print(json.dumps(report))
    finally:
        if process and process.poll() is None:
            os.killpg(process.pid, signal.SIGKILL)
            process.wait(timeout=10)
        log.close()


if __name__ == "__main__":
    main()
