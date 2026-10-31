"""Shared public-adapter identity, revocation and cross-process admission.

Only token hashes are persisted. This module uses the standard library so an
MCP bridge and a REST gateway can share it without installing the web engine.
"""

from __future__ import annotations

import contextvars
import hashlib
import hmac
import json
import os
import sqlite3
import threading
import time
import uuid
from contextlib import closing
from pathlib import Path

CLAIMS = contextvars.ContextVar("access_claims", default=None)
REQUEST_ID = contextvars.ContextVar("request_id", default="")


class AccessError(Exception):
    def __init__(self, code, status=401, retry_after=1):
        self.code, self.status, self.retry_after = code, status, retry_after
        super().__init__(code)


class Registry:
    def __init__(self, path):
        self.path = Path(path)
        self.lock = threading.Lock()
        self.tokens = ()
        self.signature = None

    def verify(self, authorization):
        if not authorization.startswith("Bearer ") or not authorization[7:].strip():
            raise AccessError("missing_bearer_token")
        digest = hashlib.sha256(authorization[7:].strip().encode()).hexdigest()
        with self.lock:
            try:
                stat = self.path.stat()
                signature = (stat.st_ino, stat.st_mtime_ns, stat.st_size)
                if signature != self.signature:
                    data = json.loads(self.path.read_text())
                    tokens = data["tokens"]
                    if not isinstance(tokens, list) or any(
                            not isinstance(t, dict) or len(t.get("sha256", "")) != 64
                            or any(c not in "0123456789abcdef" for c in t["sha256"])
                            or not isinstance(t.get("scopes", []), list) for t in tokens):
                        raise ValueError("invalid registry")
                    self.tokens, self.signature = tuple(tokens), signature
            except (OSError, ValueError, KeyError, TypeError) as exc:
                # A broken or deleted registry must not leave a revoked key alive.
                raise AccessError("credentials_unavailable", 503) from exc
            for item in self.tokens:
                if hmac.compare_digest(digest, item["sha256"]) and not item.get("revoked"):
                    return {"namespace": digest[:16], "label": item.get("label", "client"),
                            "scopes": item.get("scopes", [])}
        raise AccessError("invalid_bearer_token")


class Admission:
    def __init__(self, path, *, per_client=3, global_limit=8, per_minute=120):
        self.path = str(path)
        self.per_client, self.global_limit, self.per_minute = (
            per_client, global_limit, per_minute)
        self.initialized = False
        self.lock = threading.Lock()

    def connection(self):
        db = sqlite3.connect(self.path, timeout=0.1)
        with self.lock:
            if not self.initialized:
                db.execute("PRAGMA journal_mode=WAL")
                db.executescript("""
                    CREATE TABLE IF NOT EXISTS leases (
                        id TEXT PRIMARY KEY, client TEXT NOT NULL, expires REAL NOT NULL);
                    CREATE INDEX IF NOT EXISTS lease_client ON leases(client);
                    CREATE TABLE IF NOT EXISTS windows (
                        client TEXT NOT NULL, minute INTEGER NOT NULL, used INTEGER NOT NULL,
                        PRIMARY KEY(client,minute));
                """)
                self.initialized = True
        return db

    def acquire(self, namespace):
        now = time.time()
        minute, lease = int(now // 60), uuid.uuid4().hex
        try:
            with closing(self.connection()) as db, db:
                db.execute("BEGIN IMMEDIATE")
                db.execute("DELETE FROM leases WHERE expires<=?", (now,))
                db.execute("DELETE FROM windows WHERE minute<?", (minute - 1,))
                active = db.execute("SELECT COUNT(*) FROM leases").fetchone()[0]
                mine = db.execute("SELECT COUNT(*) FROM leases WHERE client=?",
                                  (namespace,)).fetchone()[0]
                used = db.execute("SELECT used FROM windows WHERE client=? AND minute=?",
                                  (namespace, minute)).fetchone()
                if mine >= self.per_client:
                    raise AccessError("caller_busy", 429)
                if active >= self.global_limit:
                    raise AccessError("service_busy", 429)
                if used and used[0] >= self.per_minute:
                    raise AccessError("rate_limited", 429, max(1, int(60 - now % 60)))
                db.execute("INSERT INTO windows VALUES(?,?,1) ON CONFLICT(client,minute) "
                           "DO UPDATE SET used=used+1", (namespace, minute))
                # Reap leases left by crashed adapters; all adapter timeouts are smaller.
                db.execute("INSERT INTO leases VALUES(?,?,?)", (lease, namespace, now + 300))
            return lease
        except sqlite3.Error as exc:
            raise AccessError("admission_unavailable", 503) from exc

    def release(self, lease):
        try:
            with closing(self.connection()) as db, db:
                db.execute("DELETE FROM leases WHERE id=?", (lease,))
        except sqlite3.Error:
            pass  # Expiry reclaims the lease if a transient storage failure occurs.


def require_scope(scope):
    claims = CLAIMS.get()
    if claims is None or scope not in claims["scopes"]:
        raise AccessError("insufficient_scope", 403)


class AccessMiddleware:
    def __init__(self, app, *, registry=None, admission=None):
        self.app = app
        self.registry = registry or Registry(os.environ.get(
            "DETHROTTLED_TOKEN_REGISTRY", "/etc/dethrottled-access/tokens.json"))
        self.admission = admission or Admission(os.environ.get(
            "DETHROTTLED_ADMISSION_DB", "/var/lib/dethrottled-access/admission.sqlite"),
            per_client=int(os.environ.get("DETHROTTLED_CLIENT_CONCURRENCY", "3")),
            global_limit=int(os.environ.get("DETHROTTLED_GLOBAL_CONCURRENCY", "8")),
            per_minute=int(os.environ.get("DETHROTTLED_REQUESTS_PER_MINUTE", "120")))

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http" or scope.get("path") == "/health":
            return await self.app(scope, receive, send)
        headers = dict(scope.get("headers", []))
        request_id = uuid.uuid4().hex
        lease = None
        try:
            claims = self.registry.verify(headers.get(b"authorization", b"").decode())
            path = scope.get("path", "")
            required = "drive" if path == "/drive" else (
                "corpus" if path.startswith("/corpus/") else "web")
            if not path.startswith("/mcp") and required not in claims["scopes"]:
                raise AccessError("insufficient_scope", 403)
            lease = self.admission.acquire(claims["namespace"])
        except AccessError as exc:
            body = json.dumps({"error": exc.code, "request_id": request_id}).encode()
            response_headers = [(b"content-type", b"application/json"),
                                (b"x-request-id", request_id.encode())]
            if exc.status == 401:
                response_headers.append((b"www-authenticate", b"Bearer"))
            if exc.status in {429, 503}:
                response_headers.append((b"retry-after", str(exc.retry_after).encode()))
            await send({"type": "http.response.start", "status": exc.status,
                        "headers": response_headers})
            await send({"type": "http.response.body", "body": body})
            return
        claims_token = CLAIMS.set(claims)
        trace_token = REQUEST_ID.set(request_id)

        async def traced_send(message):
            if message["type"] == "http.response.start":
                message = dict(message, headers=[*message.get("headers", []),
                                                (b"x-request-id", request_id.encode())])
            await send(message)

        try:
            await self.app(scope, receive, traced_send)
        finally:
            self.admission.release(lease)
            CLAIMS.reset(claims_token)
            REQUEST_ID.reset(trace_token)
