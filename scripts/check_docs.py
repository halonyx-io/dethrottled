"""Check first-party Markdown links, fragments and runnable guide examples offline."""

from __future__ import annotations

import ast
import json
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import get_type_hints
from urllib.parse import unquote, urlsplit

ROOT = Path(__file__).resolve().parents[1]
GUIDES = {
    "README.md",
    "AGENTS.md",
    "SKILL-dethrottled.md",
    "docs/AGENT-PLAYBOOK.md",
    "docs/QUICKSTART.md",
    "docs/DOCUMENTATION-MAINTENANCE.md",
    "docs/README.md",
    "docs/API.md",
    "docs/ADBLOCK.md",
    "docs/CONFIGURATION.md",
    "docs/DRIVE.md",
    "docs/FEATURES.md",
    "docs/PIPELINE.md",
    "docs/PYTHON.md",
    "docs/PUBLIC-ACCESS.md",
    "docs/OPERATIONS.md",
    "docs/PDF_WORKER.md",
    "docs/DEPENDABLE-WORKFLOWS.md",
    "docs/AGENT-UPGRADES.md",
    "docs/EVIDENCE.md",
    "evaluations/compact-discovery/README.md",
    "evaluations/ddg-recovery/README.md",
    "docs/READ-PLANNER.md",
}
FENCE = re.compile(r"^```([^\n]*)\n(.*?)^```\s*$", re.M | re.S)
LINK = re.compile(r'!?\[[^\]\n]*\]\((<[^>]+>|[^\s)]+)(?:\s+"[^"]*")?\)')


def anchors(text):
    text = FENCE.sub("", text)
    found = set(re.findall(r'<a\s+(?:name|id)=["\']([^"\']+)', text))
    seen = {}
    for title in re.findall(r"^#{1,6}\s+(.+?)\s*#*$", text, re.M):
        title = re.sub(r"<[^>]*>", "", title).lower()
        title = re.sub(r"[^\w\- ]", "", title).replace(" ", "-")
        count = seen.get(title, 0)
        seen[title] = count + 1
        found.add(title if not count else title + "-" + str(count))
    return found


def main():
    inventory = json.loads((ROOT / "docs/documentation-inventory.json").read_text())
    files = [ROOT / entry["path"] for entry in inventory["entries"]
             if Path(entry["path"]).suffix.lower() == ".md"
             and (ROOT / entry["path"]).is_file()]
    errors, counts = [], {"pages": len(files), "links": 0, "examples": 0, "requests": 0}
    with tempfile.TemporaryDirectory(prefix="dethrottled-doc-check-") as directory:
        os.environ["DETHROTTLED_DATA_DIR"] = directory
        sys.path.insert(0, str(ROOT / "src"))
        from dethrottled import __version__
        from dethrottled.server import app

        readme = (ROOT / "README.md").read_text()
        if f"This checkout is **{__version__}**" not in readme:
            errors.append("README.md: checkout version does not match the package")

        models = {
            route.path: get_type_hints(route.endpoint)[route.dependant.body_params[0].name]
            for route in app.routes
            if getattr(route, "body_field", None) and "POST" in route.methods
        }
        for path in files:
            text = path.read_text()
            relative = path.relative_to(ROOT).as_posix()
            body = FENCE.sub("", text)
            targets = LINK.findall(body)
            targets += re.findall(r'<img\b[^>]*\bsrc=["\']([^"\']+)', body)
            for target in targets:
                target = target.strip("<>")
                parts = urlsplit(target)
                if parts.netloc == "raw.githubusercontent.com" and parts.path.startswith(
                    "/halonyx-io/dethrottled/main/"
                ):
                    target = os.path.relpath(ROOT / parts.path.split("/main/", 1)[1], path.parent)
                    parts = urlsplit(target)
                if parts.scheme or parts.netloc:
                    continue
                counts["links"] += 1
                resolved = (path.parent / unquote(parts.path)).resolve() if parts.path else path
                if not resolved.exists():
                    errors.append(f"{relative}: missing {target}")
                elif parts.fragment and resolved.is_file() and resolved.suffix == ".md":
                    if unquote(parts.fragment) not in anchors(resolved.read_text()):
                        errors.append(f"{relative}: missing fragment {target}")
            if relative not in GUIDES:
                continue
            for language, code in FENCE.findall(text):
                counts["examples"] += 1
                try:
                    if language.strip() == "python":
                        ast.parse(code)
                    elif language.strip() == "json":
                        json.loads(code)
                    elif language.strip() in {"sh", "bash"}:
                        result = subprocess.run(
                            ["bash", "-n"], input=code, text=True, capture_output=True, check=False
                        )
                        if result.returncode:
                            raise ValueError(result.stderr.strip())
                        for match in re.finditer(r"-d\s+'(.*?)'", code, re.S):
                            urls = re.findall(
                                r"http://127\.0\.0\.1:8787([^\s\\]*)", code[: match.start()]
                            )
                            if not urls:
                                continue
                            endpoint = urls[-1]
                            if endpoint in models:
                                models[endpoint].model_validate(json.loads(match[1]))
                                counts["requests"] += 1
                except Exception as exc:
                    errors.append(f"{relative}: {language} example: {exc}")
    if errors:
        print("\n".join(errors))
        raise SystemExit(1)
    print(json.dumps({"status": "passed", **counts}, indent=2))


if __name__ == "__main__":
    main()
