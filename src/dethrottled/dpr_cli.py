"""Submit DPR jobs and export their evidence using the standard library."""

import argparse
import csv
import json
import os
import sys
import time
import urllib.error
import urllib.request
import uuid
from collections import Counter
from pathlib import Path

ROOT = "/v1/dpr"
CSV_FIELDS = (
    "item_key", "requested_url", "final_url", "outcome", "quality", "http_status",
    "fetched_at", "checked_at", "last_modified", "published_at", "completed_at",
    "cached", "content_sha256", "document_id", "document_expires_at", "failure_reason",
    "warnings", "archived_text", "archive_status", "archive_error",
)


class DirectEndpoint(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


_OPENER = urllib.request.build_opener(DirectEndpoint)


def request(base, path, payload):
    headers = {"Content-Type": "application/json"}
    if token := os.getenv("DETHROTTLED_TOKEN"):
        headers["Authorization"] = f"Bearer {token}"
    req = urllib.request.Request(base.rstrip("/") + path, json.dumps(payload).encode(),
                                 headers=headers)
    for attempt in range(3):
        try:
            with _OPENER.open(req, timeout=240) as response:
                return json.load(response)
        except urllib.error.HTTPError as exc:
            delay = exc.headers.get("Retry-After", "")
            if exc.code != 429 or attempt == 2 or not delay.isdecimal() or int(delay) > 60:
                raise
            exc.close()
            time.sleep(max(1, int(delay)))


def manifest(path):
    with path.open(encoding="utf-8-sig", newline="") as stream:
        if path.suffix.lower() == ".csv":
            reader = csv.DictReader(stream)
            if not reader.fieldnames or "url" not in reader.fieldnames:
                raise ValueError("CSV needs a url column and may contain an item_key column")
            urls, keys = [], []
            for index, row in enumerate(reader):
                urls.append((row["url"] or "").strip())
                keys.append(row.get("item_key") or str(index))
            return {"urls": urls, "item_keys": keys}
        return {"urls": [line.strip() for line in stream if line.strip()]}


def archive(read, row, directory, export_directory):
    identifier = row.get("document_id")
    if not identifier:
        row["archive_status"] = "no_retained_document"
        return
    path = directory / f'{row["source_index"]:04d}.txt'
    incomplete = path.with_suffix(".partial")
    offset = 0
    try:
        with incomplete.open("x", encoding="utf-8") as stream:
            while True:
                page = read("/documents/read", {
                    "document_id": identifier, "offset": offset, "max_chars": 12000,
                    "response_format": "concise",
                })
                stream.write(page["content"])
                next_offset = page.get("next_offset")
                if next_offset is None:
                    break
                if next_offset <= offset:
                    raise ValueError("document continuation did not advance")
                offset = next_offset
        incomplete.rename(path)
        try:
            reference = os.path.relpath(path, export_directory)
        except ValueError:  # Windows paths on different drives.
            reference = str(path.resolve())
        row.update(archived_text=reference, archive_status="retained_text_saved")
    except (OSError, ValueError, KeyError) as exc:
        incomplete.unlink(missing_ok=True)
        row["archive_status"] = "archive_failed"
        row["archive_error"] = str(exc)


def _csv_cell(value):
    if isinstance(value, list):
        value = " | ".join(map(str, value))
    if isinstance(value, str) and value.lstrip().startswith(("=", "+", "-", "@")):
        return "'" + value
    return value


def collect(read, job, output, output_format, archive_dir):
    if archive_dir is not None:
        archive_dir.mkdir()
    counts = Counter()
    cursor = 0
    with output.open("x", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, CSV_FIELDS) if output_format == "csv" else None
        if writer:
            writer.writeheader()
        while True:
            page = read(ROOT + "/jobs/read", {"job_id": job, "cursor": cursor})
            for row in page["results"]:
                if archive_dir is not None:
                    archive(read, row, archive_dir, output.parent)
                if writer:
                    writer.writerow({field: _csv_cell(row.get(field)) for field in CSV_FIELDS})
                else:
                    stream.write(json.dumps(
                        {"schema_version": page["schema_version"], **row},
                        ensure_ascii=False) + "\n")
                counts[row["outcome"]] += 1
            stream.flush()
            cursor = page["next_cursor"]
            if cursor < page["completed"]:
                continue
            if page["status"] not in {"queued", "running"}:
                print(json.dumps({"job_id": job, "status": page["status"],
                                  "outcomes": counts, "output": str(output)}))
                return 0 if page["status"] == "completed" else 1
            time.sleep(max(1, page["poll_after_ms"] / 1000))


def main(argv=None):
    parser = argparse.ArgumentParser(prog="dethrottled dpr", description=__doc__)
    parser.add_argument("--url", default=os.getenv("DETHROTTLED_URL", "http://127.0.0.1:8787"))
    commands = parser.add_subparsers(dest="action", required=True)
    fetch = commands.add_parser("fetch", help="submit a URL list or CSV")
    fetch.add_argument("manifest", type=Path)
    fetch.add_argument("--operation-id")
    fetch.add_argument("--fresh", action="store_true")
    fetch.add_argument("--index-public", action="store_true")
    export = commands.add_parser("export", help="collect a previously submitted job")
    for command in (fetch, export):
        command.add_argument("--output", type=Path, required=command is export)
        command.add_argument("--format", choices=("jsonl", "csv"), default="jsonl")
        command.add_argument("--archive-dir", type=Path)
    for action in ("export", "status", "cancel", "resume", "retry"):
        command = export if action == "export" else commands.add_parser(action)
        command.add_argument("job_id")
        if action == "retry":
            command.add_argument("--operation-id")
    resolve = commands.add_parser("resolve", help="find and read one source for a query")
    resolve.add_argument("query")
    resolve.add_argument("--alternatives", type=int, default=0)
    args = parser.parse_args(argv)

    def read(path, data):
        return request(args.url, path, data)

    try:
        if args.action == "resolve":
            print(json.dumps(read(ROOT + "/resolve", {"search": {"query": args.query},
                                                      "alternatives": args.alternatives})))
        elif args.action in {"fetch", "export"}:
            if args.output and args.output.exists():
                raise ValueError(f"Output already exists: {args.output}")
            if args.archive_dir and (not args.output or args.archive_dir.exists()):
                raise ValueError("An archive requires --output and a new --archive-dir")
            if args.action == "fetch":
                operation = args.operation_id or uuid.uuid4().hex
                print(f"DPR submission key {operation}", file=sys.stderr, flush=True)
                job = read(ROOT + "/jobs", {
                    **manifest(args.manifest),
                    "operation_id": operation,
                    "cache_mode": "refresh" if args.fresh else "use",
                    "index_public": args.index_public,
                })["job_id"]
            else:
                job = args.job_id
            print(f"DPR job {job}", file=sys.stderr, flush=True)
            if args.output:
                return collect(read, job, args.output, args.format, args.archive_dir)
            print(json.dumps({"job_id": job}))
        else:
            action = "read" if args.action == "status" else args.action
            payload = {"job_id": args.job_id}
            if action == "retry":
                payload["operation_id"] = args.operation_id or uuid.uuid4().hex
            print(json.dumps(read(ROOT + "/jobs/" + action, payload)))
    except urllib.error.HTTPError as exc:
        print(f"HTTP {exc.code}: {exc.read(4096).decode(errors='replace')}", file=sys.stderr)
        return 1
    except (OSError, ValueError, KeyError) as exc:
        print(str(exc), file=sys.stderr)
        return 1
    return 0
