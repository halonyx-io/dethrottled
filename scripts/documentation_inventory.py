#!/usr/bin/env python3
"""Generate/check documentation coverage from Git's tracked tree; no network calls."""

from __future__ import annotations

import argparse
import json
import posixpath
import re
import subprocess
from collections import Counter
from pathlib import Path

TEXT_SUFFIXES = {".md", ".mdx", ".rst", ".adoc", ".txt"}
CURRENT = {
    "README.md",
    "AGENTS.md",
    "SKILL-dethrottled.md",
    ".github/pull_request_template.md",
    *(
        "docs/" + name + ".md"
        for name in (
            "README",
            "API",
            "ADBLOCK",
            "AGENT-UPGRADES",
            "AGENT-PLAYBOOK",
            "BENCHMARKS",
            "CONFIGURATION",
            "DEPENDABLE-WORKFLOWS",
            "DRIVE",
            "EVIDENCE",
            "FEATURES",
            "LIMITS",
            "OPERATIONS",
            "PDF_WORKER",
            "PIPELINE",
            "PUBLIC-ACCESS",
            "PYTHON",
            "READ-PLANNER",
            "REQUIREMENTS",
            "QUICKSTART",
            "CORPUS",
            "DOCUMENTATION-MAINTENANCE",
        )
    ),
}
GENERATED = {
    "docs/HTTP-REFERENCE.md",
    "docs/MCP-REFERENCE.md",
    "docs/DOCUMENTATION-INVENTORY.md",
    "docs/documentation-inventory.json",
}
HISTORICAL = {
    "docs/BENCHMARKS-2026-10-04.md",
    "docs/MEASURED-IMPROVEMENTS.md",
    "docs/ONE-ZERO.md",
    "docs/RECOVERY-GAPS.md",
    "docs/REVIEWED-BOT-FINDINGS.md",
    "evaluations/module-refactor/README.md",
    "evaluations/retrieval-reliability/REPORT.md",
}
GOVERNANCE = {
    "pyproject.toml",
    "setup.py",
    "MANIFEST.in",
    "Dockerfile",
    ".env.example",
    ".dockerignore",
    "LICENSE",
    ".github/workflows/ci.yml",
    ".github/workflows/release.yml",
    "scripts/docs_reference.py",
    "scripts/check_docs.py",
    "scripts/documentation_inventory.py",
    "scripts/verify_image.py",
    "scripts/verify_adapter.py",
    "scripts/verify_stack_package.py",
}
POLICIES = {
    "current-guide": "Change author: reconcile current behaviour, examples and navigation.",
    "planned-work": (
        "Planning maintainer: verify proposals against current contracts; "
        "not implemented behaviour or execution authorization."
    ),
    "generated": "Change author: regenerate from source; do not hand-edit generated tables.",
    "historical-evidence": (
        "Evidence maintainer: preserve observations; append explicit corrections."
    ),
    "harness-guide": "Harness maintainer: check runnable commands and label dated assumptions.",
    "dependency-input": "Dependency maintainer: reconcile install/platform and lock documentation.",
    "third-party-notice": "Artifact maintainer: preserve required attribution.",
    "visual": "Documentation maintainer: check source data, labels, units and embedding.",
    "source-contract": (
        "Change author: audit docs impact, advertised defaults and generated contracts."
    ),
    "unclassified": "Assign an explicit lifecycle before accepting this document.",
}


def lifecycle(path):
    if path in GENERATED:
        return "generated"
    if path in HISTORICAL or re.search(r"(?:^|/)\d{4}-\d{2}-\d{2}(?:/|-|$)", path):
        return "historical-evidence"
    if path.startswith("docs/plans/"):
        return "planned-work"
    if path in CURRENT:
        return "current-guide"
    if path.startswith("docs/benchmarks/"):
        return "historical-evidence"
    if path.startswith(("evaluations/", "experiments/")) and path.endswith("/README.md"):
        return "harness-guide"
    if Path(path).name in {"APACHE-LICENSE.txt", "HAGEZI-GPL-3.0.txt", "NOTICE.txt", "LICENSE"}:
        return "third-party-notice"
    if "requirements" in Path(path).name or path.startswith("requirements/"):
        return "dependency-input"
    if path.startswith("docs/assets/") and path.endswith(".svg"):
        return "visual"
    if path in GOVERNANCE or path.startswith("docker-compose"):
        return "source-contract"
    if path.startswith(("requirements/", "docker/", "experiments/")):
        return "source-contract"
    if path.endswith((".py", "Dockerfile", ".sh")) and path.startswith(
        (
            "src/dethrottled/",
            "adapters/",
            "browser-search/",
            "workers/",
            "format-worker/",
            "media-worker/",
            "docling-worker/",
            "scripts/",
        )
    ):
        return "source-contract"
    return "unclassified"


def selected(path):
    return (
        Path(path).suffix.lower() in TEXT_SUFFIXES
        or "requirements" in Path(path).name
        or path in GENERATED
        or path in GOVERNANCE
        or path.startswith("docker-compose")
        or (path.startswith("experiments/") and not path.endswith(".pyc"))
        or (path.startswith("docs/assets/") and path.endswith(".svg"))
        or (path.startswith(("requirements/", "docker/")) and not path.endswith(".pyc"))
        or (
            path.endswith((".py", "Dockerfile", ".sh"))
            and path.startswith(
                (
                    "src/dethrottled/",
                    "adapters/",
                    "browser-search/",
                    "workers/",
                    "format-worker/",
                    "media-worker/",
                    "docling-worker/",
                    "scripts/",
                )
            )
        )
    )


def generate(root, extra):
    tracked = subprocess.check_output(["git", "ls-files", "-z"], cwd=root).decode().split("\0")
    paths = {p for p in tracked if p and (root / p).is_file()}
    if extra:
        paths.update(p.relative_to(extra).as_posix() for p in extra.rglob("*") if p.is_file())
    # Include these outputs in their own registry without recursive content hashes.
    paths.update(
        GENERATED & {"docs/DOCUMENTATION-INVENTORY.md", "docs/documentation-inventory.json"}
    )
    entries = [
        {"path": p, "lifecycle": lifecycle(p), "review": POLICIES[lifecycle(p)]}
        for p in sorted(paths)
        if selected(p)
    ]
    unknown = [e["path"] for e in entries if e["lifecycle"] == "unclassified"]
    if unknown:
        raise ValueError(
            "Unclassified documentation: "
            + ", ".join(unknown)
            + ". Assign its lifecycle in documentation_inventory.py."
        )
    manifest = {
        "schema_version": 1,
        "scope": "Tracked documentation, visuals and contract surfaces",
        "entries": entries,
    }
    lines = [
        "# Documentation inventory",
        "",
        "Generated by `python scripts/documentation_inventory.py` from tracked files.",
        "See [maintenance policy](DOCUMENTATION-MAINTENANCE.md) for change-impact checks.",
        "This is file coverage, not a certification that prose is correct.",
        "",
        "Untracked/private reports are intentionally excluded. New tracked documentation",
        "must be classified; unknown paths fail generation/checking.",
        "",
    ]
    counts = Counter(e["lifecycle"] for e in entries)
    lines += ["| Lifecycle | Files |", "|---|---:|"]
    lines += [f"| {kind} | {counts[kind]} |" for kind in sorted(counts)]
    for kind in sorted(counts):
        lines += ["", "## " + kind, "", POLICIES[kind], "", "| File |", "|---|"]
        for entry in entries:
            if entry["lifecycle"] == kind:
                path = entry["path"]
                target = (
                    posixpath.relpath(path, "docs")
                    if Path(path).suffix.lower() in TEXT_SUFFIXES
                    and not path.startswith((".github/", "requirements/"))
                    and entry["lifecycle"] != "dependency-input"
                    else "https://github.com/halonyx-io/dethrottled/blob/main/" + path
                )
                lines.append(f"| [{path}]({target}) |")
    return "\n".join(lines) + "\n", json.dumps(manifest, indent=2) + "\n", len(entries)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true")
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument(
        "--extra-root", type=Path, help="Preview an uncommitted draft overlay; do not use in CI"
    )
    parser.add_argument("--output-root", type=Path, help="Write a draft outside the live checkout")
    args = parser.parse_args()
    try:
        md, js, count = generate(args.root.resolve(), args.extra_root)
        target = args.output_root or args.root
        outputs = {"docs/DOCUMENTATION-INVENTORY.md": md, "docs/documentation-inventory.json": js}
        for name, content in outputs.items():
            path = target / name
            if args.check:
                if not path.exists() or path.read_text() != content:
                    raise ValueError(name + " is stale; regenerate the documentation inventory.")
            else:
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(content)
        print(f"Documentation inventory matches {count} tracked review surfaces")
    except (ValueError, OSError, subprocess.CalledProcessError) as exc:
        parser.exit(1, str(exc) + "\n")


if __name__ == "__main__":
    main()
