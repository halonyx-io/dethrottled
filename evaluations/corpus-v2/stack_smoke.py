"""Local-only migration/rollback smoke for an isolated managed validation stack."""

import argparse
import json
import os
import subprocess
import time
import urllib.request
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project", required=True)
    parser.add_argument("--port", type=int, required=True)
    parser.add_argument("--context", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if not args.project.startswith("corpus-v2-"):
        raise SystemExit("Use a dedicated corpus-v2-* project; never production.")
    env = {
        key: value
        for key, value in os.environ.items()
        if not key.startswith(("DETHROTTLED_", "COMPOSE_", "CRAWL4AI_"))
    }
    env.update(DETHROTTLED_PORT=str(args.port), DETHROTTLED_BIND="127.0.0.1")
    compose = [
        "docker",
        "compose",
        "--env-file",
        os.devnull,
        "-p",
        args.project,
        "-f",
        str(args.context / "docker-compose.yml"),
        "-f",
        str(args.context / "managed.json"),
    ]

    def command(command):
        return subprocess.check_output(command, text=True, env=env)

    container = command([*compose, "ps", "-q", "dethrottled"]).strip()
    version = command(
        [
            "docker",
            "exec",
            container,
            "python",
            "-c",
            "import dethrottled; print(dethrottled.__version__)",
        ]
    ).strip()
    if ".dev" not in version:
        raise SystemExit("This harness requires an unpublished development validation build.")

    def request(path, body=None):
        data = json.dumps(body).encode() if body else None
        req = urllib.request.Request(
            "http://127.0.0.1:%d%s" % (args.port, path),
            data=data,
            headers={"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(req, timeout=10) as response:
            return json.load(response)

    def wait(test):
        deadline = time.monotonic() + 90
        while time.monotonic() < deadline:
            try:
                result = test()
                if result:
                    return result
            except (OSError, ValueError):
                pass
            time.sleep(0.1)
        raise TimeoutError("stack smoke condition")

    seed = """
import hashlib,json
from dethrottled import corpus, paths
from dethrottled.evidence import Documents
corpus.embed=lambda texts,**kw:[[1.,0.,0.]]*len(texts)
c=corpus.Corpus()
c.add('https://example.org/legacy','Legacy','ROLLBACK-FACT-1234567: original retained source. '*10)
c._db.execute('PRAGMA wal_checkpoint(TRUNCATE)')
d=Documents(paths.data_dir()/'evidence.sqlite')
r=d.put('agent-one','https://example.org/full','Background extracted prose. '*400+
        '\\n\\nAPI-TAIL-FACT-1234567: quantity 47.',{'corpus_visibility':'public','quality':'ok'})
print(json.dumps({'legacy_sha256':hashlib.sha256((paths.data_dir()/'corpus.sqlite').read_bytes()).hexdigest(),
                  'document_id':r['document_id']}))
"""
    original = json.loads(command(["docker", "exec", container, "python", "-c", seed]))
    migration = json.loads(
        command(
            [
                "docker",
                "exec",
                container,
                "python",
                "-m",
                "dethrottled.corpus_migrate",
                "--limit",
                "32",
                "--drain",
            ]
        )
    )
    hit = wait(lambda: request("/corpus/search?q=API-TAIL-FACT-1234567&mode=lexical")["results"])
    assert hit[0]["document_available"]
    document = request(
        "/documents/read",
        {
            "document_id": original["document_id"],
            "evidence_namespace": "agent-two",
            "max_chars": 20000,
        },
    )
    assert "quantity 47" in json.dumps(document)
    fingerprint = command(
        [
            "docker",
            "exec",
            container,
            "python",
            "-c",
            "import hashlib;from dethrottled import paths;"
            'print(hashlib.sha256((paths.data_dir()/"corpus.sqlite").read_bytes()).hexdigest())',
        ]
    ).strip()
    assert fingerprint == original["legacy_sha256"]
    copies = command(
        [
            "docker",
            "exec",
            container,
            "python",
            "-c",
            'import sqlite3;print(sqlite3.connect("/data/evidence.sqlite").execute('
            '"select count(*) from documents").fetchone()[0])',
        ]
    ).strip()
    assert copies == "1", copies
    override = args.context / "corpus-rollback-smoke.json"
    override.write_text(
        json.dumps(
            {
                "services": {
                    "dethrottled": {
                        "environment": {
                            "DETHROTTLED_CORPUS_SCHEMA": "1",
                            "DETHROTTLED_MULTILINGUAL_CORPUS": "0",
                        }
                    }
                }
            }
        )
    )
    command([*compose, "-f", str(override), "up", "-d", "--no-deps", "dethrottled"])
    wait(lambda: request("/corpus/stats").get("schema") == 1)
    assert request("/corpus/search?q=ROLLBACK-FACT-1234567&mode=lexical")["results"]
    assert not request("/corpus/search?q=API-TAIL-FACT-1234567&mode=lexical")["results"]
    command([*compose, "up", "-d", "--no-deps", "dethrottled"])
    wait(lambda: request("/corpus/stats").get("index", {}).get("schema") == 2)
    assert request("/corpus/search?q=API-TAIL-FACT-1234567&mode=lexical")["results"]
    report = {
        "version": version,
        "passed": True,
        "checks": [
            "local migration",
            "deep fact",
            "cross-agent public handle",
            "no duplicate retained body",
            "v1 file unchanged by migration",
            "actual API rollback to v1",
            "actual API restore to v2",
        ],
        "migration": migration,
        "final_status": request("/corpus/stats"),
    }
    args.output.write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report))


if __name__ == "__main__":
    main()
