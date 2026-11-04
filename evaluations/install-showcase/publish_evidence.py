"""Export case evidence without republishing search snippets or private-range strings."""

import argparse
import hashlib
import json
import re
from pathlib import Path

P = argparse.ArgumentParser()
P.add_argument("--captures", type=Path, required=True)
P.add_argument("--out", type=Path, required=True)
A = P.parse_args()
A.out.mkdir(parents=True, exist_ok=True)
exports = []
PRIVATE = re.compile(r"\b(?:192\.168\.\d+\.\d+|10\.\d+\.\d+\.\d+)\b")


def sanitize(value):
    if isinstance(value, list):
        return [sanitize(x) for x in value]
    if isinstance(value, dict):
        result = {k: sanitize(v) for k, v in value.items() if k != "snippet"}
        if isinstance(value.get("snippet"), str):
            snippet = value["snippet"]
            result.update(
                snippet_chars=len(snippet),
                snippet_sha256=hashlib.sha256(snippet.encode()).hexdigest(),
            )
        return result
    if isinstance(value, str):
        return PRIVATE.sub("[private-range-address]", value)
    return value


for folder in sorted(A.captures.iterdir()):
    if not folder.is_dir() or not folder.name.startswith(("q6a-", "szbox-")):
        continue
    target = A.out / folder.name
    target.mkdir(exist_ok=True)
    for file in sorted(folder.glob("*.json")):
        original = file.read_bytes()
        content = json.dumps(sanitize(json.loads(original)), indent=2) + "\n"
        (target / file.name).write_text(content)
        exports.append(
            dict(
                file=str(file.relative_to(A.captures)),
                original_sha256=hashlib.sha256(original).hexdigest(),
                public_sha256=hashlib.sha256(content.encode()).hexdigest(),
            )
        )
(A.out / "export-manifest.json").write_text(
    json.dumps(
        dict(
            policy="Search snippets replaced by length/SHA256; private-range strings redacted. "
            "Full original captures remain private. Numeric measurements unchanged.",
            files=exports,
        ),
        indent=2,
    )
    + "\n"
)
