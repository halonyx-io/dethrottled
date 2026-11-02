"""Small fixed live browser comparison, never a general anti-bot success rate."""

import argparse
import hashlib
import json
import time
import uuid
from pathlib import Path
from urllib.request import Request, urlopen

p = argparse.ArgumentParser()
p.add_argument("--cpu", required=True)
p.add_argument("--gpu")
p.add_argument("--out", type=Path, required=True)
a = p.parse_args()
a.out.mkdir(parents=True, exist_ok=True)
cases = [
    (
        "reddit-thread",
        "https://www.reddit.com/r/programming/comments/1xl8d57/"
        "jepsen_on_particledb_we_tested_versions_114/",
        ["ParticleDB", "WHERE 4 = 5"],
    ),
    ("reddit-listing", "https://www.reddit.com/r/programming/", ["programming"]),
    ("python", "https://docs.python.org/3/library/sqlite3.html", ["sqlite3", "Connection"]),
    ("crunchbase", "https://www.crunchbase.com/organization/openai", ["OpenAI", "2015"]),
    ("g2", "https://www.g2.com/products/notion/reviews", ["Notion", "What do you like best"]),
    ("cargurus", "https://www.cargurus.com/", ["CarGurus", "Used Cars"]),
    ("bloomberg", "https://www.bloomberg.com/", ["Bloomberg", "Markets"]),
]
(a.out / "protocol.json").write_text(
    json.dumps(
        dict(
            cases=cases,
            reddit_repeats=3,
            other_repeats=1,
            source_complete=False,
            notes="Same browser image, recovery auto, fresh sessions. CPU and GPU on one host; "
            "facts are lexical task support, not truth or complete-source verification.",
        ),
        indent=2,
    )
)
records = []


def call(endpoint, body):
    with urlopen(
        Request(
            endpoint + "/drive",
            data=json.dumps(body).encode(),
            headers={"Content-Type": "application/json"},
        ),
        timeout=65,
    ) as r:
        return json.load(r)


for case, url, facts in cases:
    for repeat in range(3 if case.startswith("reddit") else 1):
        for engine, endpoint in [("cpu", a.cpu), *([("gpu", a.gpu)] if a.gpu else [])]:
            base = dict(
                session="live-gate-" + uuid.uuid4().hex[:12],
                screenshot="never",
                allowed_hosts=[url.split("/")[2]],
                public_only=True,
                timeout_ms=30000,
            )
            at = time.monotonic()
            record = dict(case=case, engine=engine, repeat=repeat)
            try:
                result = call(
                    endpoint,
                    dict(
                        base,
                        url=url,
                        steps=[
                            {"action": "count", "selector": "shreddit-comment"},
                            {"action": "text", "selector": "body", "max_chars": 120000},
                        ],
                    ),
                )
                record["elapsed_ms"] = round((time.monotonic() - at) * 1000, 2)
                text = "\n".join(
                    s.get("data", "")
                    for s in result.get("steps", [])
                    if s.get("action") == "text" and isinstance(s.get("data"), str)
                )
                record.update(
                    access=result.get("access"),
                    recovery=result.get("navigation_recovery"),
                    action_ok=result.get("ok"),
                    chars=len(text),
                    text_sha256=hashlib.sha256(text.encode()).hexdigest(),
                    facts={f: f.casefold() in text.casefold() for f in facts},
                    comments=next(
                        (s["data"] for s in result.get("steps", []) if s.get("action") == "count"),
                        0,
                    ),
                )
                if case == "reddit-thread" and record["comments"]:
                    interaction = dict(
                        base,
                        operation_id="sort-open",
                        steps=[
                            {"action": "click", "selector": "shreddit-sort-dropdown button"},
                            {"action": "count", "selector": '[role="menuitem"]:visible'},
                        ],
                    )
                    at = time.monotonic()
                    clicked = call(endpoint, interaction)
                    record["click_ms"] = round((time.monotonic() - at) * 1000, 2)
                    record["native_menu_opened"] = clicked.get("ok") and any(
                        s.get("action") == "count" and s.get("data", 0) > 0
                        for s in clicked.get("steps", [])
                    )
                    replay = call(endpoint, interaction)
                    record["operation_replay"] = bool(replay.get("operation_replayed"))
            except Exception as exc:
                record.update(
                    error=type(exc).__name__, elapsed_ms=round((time.monotonic() - at) * 1000, 2)
                )
            finally:
                try:
                    call(endpoint, dict(base, steps=[], close_session=True))
                except Exception:
                    record["cleanup_failed"] = True
            records.append(record)
            (a.out / "observations.json").write_text(json.dumps(records, indent=2) + "\n")
            print(case, repeat, engine, record.get("access"), record.get("facts"), flush=True)
