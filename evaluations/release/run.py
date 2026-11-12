"""End-to-end release contracts on a fresh default Compose project.

Fixed synthetic facts, no model/key/Internet needed. Live-source checks are separate.
Every case is saved immediately, including errors; nonzero exit means a gate failed.
"""

import argparse
import json
import time
import uuid
from pathlib import Path
from urllib.request import Request, urlopen

parser = argparse.ArgumentParser()
parser.add_argument("--endpoint", default="http://127.0.0.1:19087")
parser.add_argument("--fixture", default="http://fixture:8099")
parser.add_argument("--out", type=Path, required=True)
parser.add_argument("--phase", choices=["contracts", "restore"], default="contracts")
a = parser.parse_args()
a.out.mkdir(parents=True, exist_ok=True)
records = []
namespace = "release-" + uuid.uuid4().hex[:12]


def call(path, payload=None):
    data = json.dumps(payload).encode() if payload is not None else None
    request = Request(a.endpoint + path, data=data, headers={"Content-Type": "application/json"})
    with urlopen(request, timeout=100) as response:
        return json.load(response)


def check(name, operation):
    at = time.monotonic()
    try:
        evidence = operation()
        record = dict(case=name, passed=True, evidence=evidence)
    except Exception as exc:
        record = dict(case=name, passed=False, error=type(exc).__name__, detail=str(exc)[:200])
    record["elapsed_ms"] = round((time.monotonic() - at) * 1000, 2)
    records.append(record)
    (a.out / (a.phase + ".json")).write_text(json.dumps(records, indent=2) + "\n")
    print(name, record["passed"], record["elapsed_ms"], flush=True)


def fetch(path, **options):
    return call(
        "/fetch",
        dict(
            urls=[a.fixture + path],
            cache_mode="bypass",
            max_chars=8000,
            evidence_namespace=namespace,
            **options,
        ),
    )[0]


def fact_read(path):
    row = fetch("/" + path)
    assert "7341 tonnes" in row.get("content", ""), row.get("quality")
    assert row["document_id"] and row["read_plan"]
    result = dict(quality=row["quality"], document_retained=True, read_plan=row["read_plan"])
    if path == "lazy":
        session = row["read_plan"]["browser_session"]
        continuation = call(
            "/drive",
            dict(
                session=session["id"],
                allowed_hosts=session["allowed_hosts"],
                evidence_namespace=namespace,
                screenshot="never",
                steps=[{"action": "text", "selector": "body"}],
            ),
        )
        assert "7341 tonnes" in str(continuation["steps"])
        result["same_browser_handoff"] = True
    return result


for _retry in range(90):
    try:
        status = call("/v2/status")
        if all(
            status["workers"][k]["status"] == "ready" for k in ["browser", "renderer", "formats"]
        ):
            break
    except OSError:
        pass
    time.sleep(1)
else:
    raise RuntimeError("Default workers did not become ready")

(a.out / "status.json").write_text(json.dumps(status, indent=2) + "\n")
caps = call("/v2/capabilities")
(a.out / "capabilities.json").write_text(json.dumps(caps, indent=2) + "\n")
base = dict(
    session="release-contract",
    allowed_hosts=["fixture"],
    screenshot="never",
    evidence_namespace="release-contract",
    timeout_ms=30000,
)


def drive(**payload):
    result = call("/drive", dict(base, **payload))
    assert result["ok"], [s.get("reason") for s in result.get("steps", []) if not s.get("ok")]
    return result


if a.phase == "contracts":

    def defaults():
        assert status["workers"]["formats"]["status"] == "ready"
        assert status["workers"]["speech"]["status"] == "not_configured"
        assert status["workers"]["layout"]["status"] == "not_configured"
        assert {"msg", "xlsb"} <= set(caps["read"]["formats"])
        assert not any(caps["optional_search_providers"].values())
        return {
            "format_worker_discovered": True,
            "keys_required": False,
            "graphics": status["workers"]["browser"].get("graphics"),
        }

    check("fresh-defaults", defaults)

    def long_browser_read():
        value = drive(session="release-long", url=a.fixture + "/long-read",
                      steps=[{"action": "text", "selector": "body", "max_chars": 200000}],
                      close_session=True)
        step = value["steps"][-1]
        assert len(step["data"]) > 120000 and "ALLOCATION_TOTAL_7341" in step["data"]
        assert not step.get("truncated")
        return {"late_fact_retained": True, "content_chars": len(step["data"])}

    check("long-browser-read", long_browser_read)
    for name in [
        "alternate",
        "lazy",
        "details",
        "network",
        "cookie-seed",
        "cookie-gated",
        "normal",
    ]:
        check("automatic-" + name, lambda name=name: fact_read(name))

    def negative(mode):
        if mode == "other-caller":
            global namespace
            namespace = "other-" + uuid.uuid4().hex[:12]
            row = fetch("/cookie-gated")
        else:
            row = fetch(
                "/lazy" if mode != "poison" else "/poison",
                **(
                    {"render": "never"}
                    if mode == "render-never"
                    else {"recovery": "manual"}
                    if mode == "manual"
                    else {}
                ),
            )
        assert "7341 tonnes" not in row.get("content", "")
        return dict(quality=row["quality"], fact_not_fabricated=True)

    for mode in ["poison", "render-never", "manual", "other-caller"]:
        check(mode, lambda mode=mode: negative(mode))

    def late_table():
        row = fetch("/late.csv", row_start=2539, row_end=2539)
        assert "R2537" in row["content"] and "43129" in row["content"]
        retained = call(
            "/documents/read",
            dict(
                document_id=row["document_id"],
                evidence_namespace=namespace,
                max_chars=8000,
                row_start=2539,
                row_end=2539,
            ),
        )
        assert "R2537" in retained["content"]
        return dict(late_fact=True, retained_range=True)

    check("late-table-retention", late_table)

    def broad_format(name, expected):
        row = fetch("/" + name)
        assert expected in row["content"]
        assert row["extraction"]["parser"] == "apache-tika"
        return dict(known_fact=True, parser="apache-tika", warnings=row.get("warnings", []))

    check(
        "default-msg-read",
        lambda: broad_format("quick.msg", "The quick brown fox jumps over the lazy dog"),
    )
    check(
        "default-xlsb-read",
        lambda: broad_format(
            "Simple.xlsb",
            "This is an example spreadsheet created with Microsoft Excel 2007 Beta 2.",
        ),
    )

    def setup():
        value = drive(url=a.fixture + "/app", steps=[{"action": "wait_for", "selector": "#ready"}])
        return {"access": value.get("access")}

    check("browser-start", setup)

    def frame():
        value = drive(
            steps=[
                {"action": "click", "frame": "#embed", "selector": "button"},
                {"action": "text", "frame": "#embed", "selector": "#allocation"},
            ]
        )
        assert "updated 291" in str(value["steps"])
        return {"fact": True}

    check("native-frame-action", frame)

    def popup():
        value = drive(
            steps=[
                {"action": "click", "selector": "#popup"},
                {"action": "wait", "ms": 200},
                {"action": "switch_tab", "index": 1},
                {"action": "text", "selector": "#report"},
            ]
        )
        assert "420 tonnes" in str(value["steps"])
        drive(steps=[{"action": "switch_tab", "index": 0}])
        return {"fact": True}

    check("native-popup", popup)

    def download():
        value = drive(steps=[{"action": "download", "selector": "#download", "ms": 5000}])
        data = value["steps"][-1]["data"]
        assert data["artifact_id"] and "7341" in data["content"]
        return {"csv_fact": True, "bytes": data["size_bytes"], "retained": True}

    check("native-download", download)

    def checkpoint():
        value = drive(
            operation_id="release-checkpoint",
            steps=[
                {"action": "click", "selector": "#save"},
                {
                    "action": "wait_for",
                    "selector": '#state:text-is("true|local-kept|session-kept|idb-kept")',
                },
                {"action": "text", "selector": "#state"},
                {"action": "checkpoint"},
            ]
        )
        assert "true|local-kept|session-kept|idb-kept" in str(value["steps"])
        return {"four_storage_types": True}

    check("checkpoint-before-restart", checkpoint)
else:

    def restore():
        value = drive(
            steps=[
                {"action": "wait_for", "selector": "#ready"},
                {"action": "text", "selector": "#state"},
            ]
        )
        assert value["session"]["restored_from_checkpoint"]
        assert "true|local-kept|session-kept|idb-kept" in str(value["steps"])
        drive(steps=[], close_session=True)
        return {"four_storage_types": True, "restored": True}

    check("restore-after-worker-restart", restore)

raise SystemExit(0 if all(r["passed"] for r in records) else 1)
