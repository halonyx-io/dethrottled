"""List the Python packages inside built images and flag non-permissive licences.

    python scripts/license_inventory.py dethrottled-api:1.8.10 dethrottled-dnb:1.8.10 ...
    python scripts/license_inventory.py --json inventory.json IMAGE ...

Each image runs offline (`--network none`) with its own interpreter and reports
the declared licence of every installed distribution. Anything that is not
plainly permissive, or declares no licence at all, is printed for a human to
check. Packages whose metadata is empty (shims, vendored code) need reading by
hand; KNOWN records the ones already checked. SearXNG itself (AGPL-3.0) is
source, not a distribution, so it does not appear. System packages, browsers
and model weights are not covered; see THIRD-PARTY-NOTICES.md for those.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys

PROBE = r"""
import importlib.metadata as m, json
rows = []
for d in m.distributions():
    md = d.metadata
    lic = (md.get('License-Expression') or '').strip()
    if not lic and len((md.get('License') or '').strip()) < 120:
        lic = (md.get('License') or '').strip()
    if not lic:
        lic = '; '.join(c.split('::')[-1].strip()
                        for c in md.get_all('Classifier') or [] if c.startswith('License'))
    rows.append({'name': md['Name'], 'version': md['Version'], 'license': lic})
print(json.dumps(rows))
"""
PERMISSIVE = re.compile(
    r"^(The )?(\d-Clause )?(MIT|BSD|Apache|ISC|PSF|Python Software Foundation|"
    r"Unlicense|0BSD|Zlib|HPND|CNRI-Python|CC0|Public Domain)", re.I)
# Packages whose metadata is vague or empty, checked by hand against upstream.
KNOWN = {
    "python-dateutil": "Apache-2.0 OR BSD-3-Clause (declared as 'Dual License')",
    "tiktoken": "MIT (licence file only)",
    "pymupdf4llm": "empty 2.0 shim; the code ships inside PyMuPDF",
    "pymupdf-layout": "empty 2.0 shim; the code ships inside PyMuPDF",
}
INTERPRETERS = ("python3", "/usr/local/searxng/.venv/bin/python")


def inventory(image):
    for interpreter in INTERPRETERS:
        done = subprocess.run(
            ["docker", "run", "--rm", "--network", "none", "--entrypoint", interpreter,
             image, "-c", PROBE], capture_output=True, text=True)
        if done.returncode == 0 and done.stdout.strip() not in ("", "[]"):
            return json.loads(done.stdout)
    raise SystemExit(f"{image}: no Python interpreter found\n{done.stderr[-400:]}")


def needs_review(license_text):
    parts = re.split(r"\s+(?:OR|AND)\s+|\s*[;|]\s*", license_text or "")
    return not license_text or not all(PERMISSIVE.match(p.strip()) for p in parts if p.strip())


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("images", nargs="+")
    parser.add_argument("--json", help="write the full inventory here")
    args = parser.parse_args()
    found = {image: inventory(image) for image in args.images}
    if args.json:
        with open(args.json, "w") as handle:
            json.dump(found, handle, indent=1, sort_keys=True)
    flagged = {}
    for image, rows in found.items():
        for row in rows:
            if row["name"].lower().replace("_", "-") in KNOWN:
                continue
            if needs_review(row["license"]):
                key = (row["name"].lower(), row["version"], row["license"] or "(none declared)")
                flagged.setdefault(key, []).append(image)
    for (name, version, licence), images in sorted(flagged.items()):
        print(f"{name} {version}: {licence}  [{', '.join(images)}]")
    total = sum(len(rows) for rows in found.values())
    print(f"{len(flagged)} of {total} package entries need review", file=sys.stderr)


if __name__ == "__main__":
    main()
