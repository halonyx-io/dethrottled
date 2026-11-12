"""HaGeZi Multi PRO domain policy. Stdlib-only, also loaded by managed workers.

No import-time I/O. Missing rules fail open and are explicitly observable. This
is a content filter, never a substitute for public-target/DNS/security checks.
"""

from __future__ import annotations

import hashlib
import io
import ipaddress
import json
import math
import os
import re
import tempfile
import threading
import time
import urllib.error
import urllib.request
from collections import Counter
from pathlib import Path
from urllib.parse import urlsplit

SOURCES = (
    "https://cdn.jsdelivr.net/gh/hagezi/dns-blocklists@latest/adblock/pro.txt",
    "https://raw.githubusercontent.com/hagezi/dns-blocklists/main/adblock/pro.txt",
)
INTERVAL = 86400
MAX_BYTES = 32 * 1024 * 1024
_DOMAIN = re.compile(r"(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z0-9-]{2,63}\Z")


class AdblockBlocked(ValueError):
    """Deliberate policy refusal, not an upstream/transport failure."""

    def __init__(self, domain):
        self.domain = domain
        super().__init__("adblock_blocked:" + domain)


def enabled():
    return os.getenv("DETHROTTLED_ADBLOCK", "1").lower().strip() not in {"0", "false", "off", "no"}


def parse(body):
    if len(body) > MAX_BYTES:
        raise ValueError("list_too_large")
    text = body[:4000].decode("utf-8")
    if not text.startswith("[Adblock Plus]") or "HaGeZi's Multi PRO" not in text[:2000]:
        raise ValueError("wrong_list_header")
    rules = set()
    lines = io.BytesIO(body)
    next(lines)
    for raw in lines:
        line = raw.decode("utf-8").rstrip("\r\n")
        if not line or line.startswith("!"):
            continue
        if not line.startswith("||") or not line.endswith("^"):
            raise ValueError("unsupported_list_rule")
        domain = line[2:-1].lower()
        if not _DOMAIN.fullmatch(domain):
            raise ValueError("invalid_domain_rule")
        rules.add(domain)
    count = re.search(r"! Number of entries: (\d+)", text[:4000])
    if not count or len(rules) != int(count[1]) or not 10000 <= len(rules) <= 2000000:
        raise ValueError("list_count_mismatch")
    return frozenset(rules)


def _atomic(path, payload):
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(prefix=".adblock-", dir=path.parent)
    try:
        with os.fdopen(fd, "w") as output:
            if hasattr(os, "fchmod"):
                os.fchmod(output.fileno(), 0o640)
            else:  # Windows does not provide descriptor chmod.
                os.chmod(name, 0o640)
            json.dump(payload, output, separators=(",", ":"))
            output.flush()
            os.fsync(output.fileno())
        os.replace(name, path)
    finally:
        if os.path.exists(name):
            os.unlink(name)


class Filter:
    def __init__(self, directory=None, *, reader=False, component="api"):
        self.directory = Path(directory) if directory is not None else None
        self.reader, self.component = reader, component
        self.rules = frozenset()
        self.metadata = {}
        self.error = None
        self.last_check = None
        self.counts = Counter()
        self.lock = threading.Lock()
        self.update_lock = threading.Lock()
        self.stop_event = threading.Event()
        self.thread = None
        self._signature = None

    @property
    def path(self):
        if self.directory is None:
            override = os.getenv("DETHROTTLED_ADBLOCK_DIR")
            base = os.getenv("DETHROTTLED_DATA_DIR") or (
                Path(
                    os.getenv(
                        "LOCALAPPDATA" if os.name == "nt" else "XDG_CACHE_HOME",
                        str(Path.home() / ".cache"),
                    )
                )
                / "dethrottled"
            )
            self.directory = Path(override) if override else Path(base) / "adblock"
        return self.directory / "multi-pro.json"

    def load(self):
        if not enabled():
            return
        try:
            stat = self.path.stat()
            signature = stat.st_mtime_ns, stat.st_size
            if signature == self._signature:
                return
            if stat.st_size > MAX_BYTES * 2:
                raise ValueError("cache_too_large")
            data = json.loads(self.path.read_text())
            if (
                not isinstance(data.get("body"), str)
                or data.get("source") not in SOURCES
                or any(
                    not isinstance(data.get(k), (int, float)) or not math.isfinite(data[k])
                    for k in ("checked_at", "updated_at")
                )
            ):
                raise ValueError("invalid_cache_metadata")
            body = data["body"].encode("utf-8")
            if hashlib.sha256(body).hexdigest() != data["sha256"]:
                raise ValueError("cache_checksum_mismatch")
            # Metadata-only refreshes still validate the body checksum, but
            # need not rebuild the same immutable domain set in every worker.
            rules = (self.rules if self.rules and self.metadata.get("sha256") == data["sha256"]
                     else parse(body))
            self.rules, self.metadata, self._signature = (
                rules,
                {k: v for k, v in data.items() if k != "body"},
                signature,
            )
            self.last_check, self.error = data.get("checked_at"), None
        except FileNotFoundError:
            if not self.rules:
                self.error = "no_valid_list"
        except (OSError, ValueError, KeyError, TypeError) as exc:
            self.error = "cache_invalid:" + type(exc).__name__

    def update(self, opener=urllib.request.urlopen, now=None):
        """Bounded conditional refresh; prior rules remain active on any failure."""
        if not enabled() or self.reader or not self.update_lock.acquire(blocking=False):
            return
        try:
            now = time.time() if now is None else now
            self.last_check = now
            errors = []
            for source in SOURCES:
                headers = {
                    "User-Agent": "Dethrottled-HaGeZi-updater",
                    "Accept-Encoding": "identity",
                }
                if self.metadata.get("source") == source and self.rules:
                    for field, header in [
                        ("etag", "If-None-Match"),
                        ("last_modified", "If-Modified-Since"),
                    ]:
                        if self.metadata.get(field):
                            headers[header] = self.metadata[field]
                try:
                    try:
                        response = opener(
                            urllib.request.Request(source, headers=headers), timeout=15
                        )
                    except urllib.error.HTTPError as exc:
                        if exc.code != 304:
                            raise
                        response = exc
                    with response:
                        if response.code == 304:
                            if not self.rules or self.metadata.get("source") != source:
                                raise ValueError("unexpected_304")
                            data = json.loads(self.path.read_text())
                            if (
                                hashlib.sha256(data["body"].encode()).hexdigest()
                                != self.metadata["sha256"]
                                or data.get("sha256") != self.metadata["sha256"]
                                or data.get("source") != source
                            ):
                                raise ValueError("cache_checksum_mismatch")
                            data = dict(self.metadata, body=data["body"], checked_at=now)
                            rules = self.rules
                        else:
                            if response.code != 200:
                                raise ValueError("update_http_" + str(response.code))
                            chunks, size, began = [], 0, time.monotonic()
                            read = getattr(response, "read1", response.read)
                            while True:
                                chunk = read(min(65536, MAX_BYTES + 1 - size))
                                if not chunk:
                                    break
                                chunks.append(chunk)
                                size += len(chunk)
                                if size > MAX_BYTES or time.monotonic() - began > 45:
                                    raise ValueError("update_size_or_time_limit")
                            body = b"".join(chunks)
                            digest = hashlib.sha256(body).hexdigest()
                            unchanged = bool(self.rules) and digest == self.metadata.get("sha256")
                            rules = self.rules if unchanged else parse(body)
                            # Reject catastrophic truncation even if its header changes.
                            if self.rules and len(rules) < len(self.rules) // 2:
                                raise ValueError("suspicious_rule_count_drop")
                            data = dict(
                                body=body.decode(),
                                sha256=digest,
                                source=source,
                                updated_at=now,
                                checked_at=now,
                                etag=response.headers.get("ETag"),
                                last_modified=response.headers.get("Last-Modified"),
                            )
                    license_file = Path(__file__).with_name("licenses") / "HAGEZI-GPL-3.0.txt"
                    if license_file.is_file():
                        _atomic(
                            self.path.with_name("license.json"),
                            {
                                "list": "HaGeZi Multi PRO",
                                "license": "GPL-3.0",
                                "source": "https://github.com/hagezi/dns-blocklists",
                                "license_text": license_file.read_text(),
                            },
                        )
                    _atomic(self.path, data)
                    stat = self.path.stat()
                    self.rules = rules
                    self.metadata = {k: v for k, v in data.items() if k != "body"}
                    self._signature = stat.st_mtime_ns, stat.st_size
                    self.error = None
                    return
                except (OSError, ValueError, KeyError, TypeError) as exc:
                    errors.append(type(exc).__name__ + ":" + str(exc)[:120])
            self.error = "update_failed:" + ";".join(errors)
        finally:
            self.update_lock.release()

    def match(self, url):
        if not enabled():
            return None
        try:
            parsed = urlsplit(url)
            if parsed.scheme not in {"http", "https", "ws", "wss"}:
                return None
            host = (parsed.hostname or "").rstrip(".").lower().encode("idna").decode("ascii")
            # Local services/IP literals stay governed by the existing security policy.
            if (
                not host
                or "." not in host
                or host == "localhost"
                or host.endswith((".localhost", ".local"))
            ):
                return None
            try:
                ipaddress.ip_address(host)
                return None
            except ValueError:
                pass
        except (ValueError, UnicodeError):
            return None
        rules = self.rules
        while "." in host:
            if host in rules:
                return host
            host = host.split(".", 1)[1]
        return None

    def blocked(self, domain, transport):
        with self.lock:
            self.counts["total"] += 1
            self.counts[transport] += 1

    def check(self, url, transport="http"):
        domain = self.match(url)
        if domain:
            self.blocked(domain, transport)
            raise AdblockBlocked(domain)

    def status(self):
        with self.lock:
            counts = dict(self.counts)
        return {
            "enabled": enabled(),
            "available": bool(self.rules) if enabled() else False,
            "state": ("disabled" if not enabled() else "active" if self.rules else "unavailable"),
            "list": "HaGeZi Multi PRO",
            "rule_count": len(self.rules) if enabled() else 0,
            "last_update": self.metadata.get("updated_at"),
            "last_check": self.last_check,
            "error": self.error if enabled() else None,
            "sha256": self.metadata.get("sha256"),
            "source": self.metadata.get("source"),
            "update_interval_seconds": INTERVAL,
            "blocked_requests": counts,
            "counter_units": "policy refusals; browser connection attempts include retries",
            "component": self.component,
            "missing_list_policy": "allow; existing network security still applies",
        }

    def start(self):
        if not enabled():
            return
        with self.lock:
            if self.thread is not None and self.thread.is_alive():
                return
            # Load once synchronously before the worker thread exists. The
            # background _run() also calls load(), so the first requests raced
            # it and were allowed through unfiltered: measured 2026-11-11, two
            # ad domains returned ALLOWED immediately after start() and only
            # one was blocked after the thread finished. A cold parse is about
            # 0.27s, paid once at startup, and it closes that window.
            self.load()
            self.stop_event.clear()
            self.thread = threading.Thread(
                target=self._run, daemon=True, name="dethrottled-adblock"
            )
            self.thread.start()

    def _run(self):
        # Disk parse/download happen off the startup/request/event-loop thread.
        while not self.stop_event.is_set() and enabled():
            self.load()
            now = time.time()
            due = max(self.metadata.get("checked_at", 0), self.last_check or 0)
            if not self.reader and now - due >= (300 if self.error else INTERVAL):
                self.update()
            if self.directory is not None:
                try:
                    _atomic(
                        self.directory
                        / ("worker-" + self.component + "-" + str(os.getpid()) + ".json"),
                        dict(self.status(), observed_at=time.time()),
                    )
                except OSError:
                    pass
            if not self.reader and self.directory is not None:
                # Process counters are observations, not an unbounded restart log.
                for path in list(self.directory.glob("worker-*.json"))[:256]:
                    try:
                        if time.time() - path.stat().st_mtime > INTERVAL:
                            path.unlink()
                    except OSError:
                        pass
            self.stop_event.wait(30)

    def stop(self):
        self.stop_event.set()


FILTER = Filter(
    reader=os.getenv("DETHROTTLED_ADBLOCK_READER") == "1",
    component=os.getenv("DETHROTTLED_ADBLOCK_COMPONENT", "api"),
)


def check(url, transport="http"):
    FILTER.start()
    FILTER.check(url, transport)


def status():
    result = FILTER.status()
    workers = []
    if enabled() and FILTER.directory is not None:
        try:
            for path in list(FILTER.directory.glob("worker-*.json"))[:256]:
                data = json.loads(path.read_text())
                if time.time() - data["observed_at"] < 120:
                    workers.append(data)
        except (OSError, ValueError, KeyError):
            pass
    result["workers"] = workers
    return result


def error_reason(exc):
    return str(exc) if isinstance(exc, AdblockBlocked) else type(exc).__name__
