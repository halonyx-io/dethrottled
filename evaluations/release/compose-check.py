"""Run fresh-volume default-stack contracts without reading the checkout's .env."""

import argparse
import json
import os
import subprocess
import sys
import uuid
from pathlib import Path

p = argparse.ArgumentParser()
p.add_argument("--out", type=Path, required=True)
p.add_argument(
    "--no-build", action="store_true", help="Use the named candidate images already built"
)
p.add_argument("--port", type=int, default=19087)
a = p.parse_args()
a.out.mkdir(parents=True, exist_ok=True)
repo = Path(__file__).resolve().parents[2]
project = "dethrottled-gate-" + uuid.uuid4().hex[:10]
env = {
    k: v
    for k, v in os.environ.items()
    if not k.startswith(("DETHROTTLED_", "CRAWL4AI_", "COMPOSE_"))
}
env["DETHROTTLED_PORT"] = str(a.port)
compose = [
    "docker",
    "compose",
    "--env-file",
    os.devnull,
    "-p",
    project,
    "-f",
    str(repo / "docker-compose.yml"),
    "-f",
    str(repo / "evaluations/release/compose.yml"),
]


def run(command, **kwargs):
    subprocess.run(command, env=env, cwd=repo, check=True, **kwargs)


protocol = dict(
    project=project,
    empty_env_file=True,
    gpu_passthrough=False,
    fresh_volumes=True,
    port=a.port,
    status="running",
)
(a.out / "deployment-protocol.json").write_text(json.dumps(protocol, indent=2))
try:
    if not a.no_build:
        for tag, dockerfile, context in [
            ("dethrottled:one-zero-candidate", "Dockerfile", "."),
            (
                "dethrottled-browser-search:one-zero-candidate",
                "browser-search/Dockerfile",
                "browser-search",
            ),
            ("dethrottled-formats:local", "format-worker/Dockerfile", "."),
        ]:
            run(["docker", "build", "-f", dockerfile, "-t", tag, context])
    run([*compose, "up", "-d", "--no-build"])
    command = [
        sys.executable,
        str(repo / "evaluations/release/run.py"),
        "--endpoint",
        f"http://127.0.0.1:{a.port}",
        "--out",
        str(a.out),
    ]
    run(command)
    run([*compose, "restart", "browser-search"])
    run([*command, "--phase", "restore"])
    protocol["status"] = "passed"
except Exception:
    protocol["status"] = "failed"
    raise
finally:
    (a.out / "deployment-protocol.json").write_text(json.dumps(protocol, indent=2) + "\n")
    with (a.out / "compose.log").open("w") as output:
        subprocess.run(
            [*compose, "logs", "--no-color", "--tail", "100"],
            env=env,
            cwd=repo,
            stdout=output,
            stderr=subprocess.STDOUT,
            check=False,
        )
    # The random project is owned by this run; never remove other projects/volumes.
    subprocess.run([*compose, "down", "-v", "--remove-orphans"], env=env, cwd=repo, check=False)
