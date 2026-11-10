"""Short-lived standard EdDSA JWT delegation for the private browser worker.

The API owns the signing key; browser workers receive public verification only.
Imports are lazy so standalone/core installations without DNB remain unchanged.
"""

from __future__ import annotations

import hashlib
import ipaddress
import json
import os
import tempfile
import time
import uuid
from pathlib import Path


def body_digest(body):
    return hashlib.sha256(
        json.dumps(
            body, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False
        ).encode()
    ).hexdigest()


def ensure_keys():
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

    directory = (
        Path(os.getenv("DETHROTTLED_DATA_DIR", str(Path.home() / ".cache/dethrottled"))) / "dnb"
    )
    private = Path(os.getenv("DETHROTTLED_DNB_PRIVATE_KEY", str(directory / "issuer.pem")))
    public = Path(os.getenv("DETHROTTLED_DNB_PUBLIC_KEY", str(directory / "issuer.pub")))
    private.parent.mkdir(parents=True, exist_ok=True)
    if not private.exists():
        key = Ed25519PrivateKey.generate()
        data = key.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption(),
        )
        fd, name = tempfile.mkstemp(dir=private.parent, prefix=".issuer-")
        try:
            with os.fdopen(fd, "wb") as output:
                output.write(data)
                output.flush()
                os.fsync(output.fileno())
            try:
                os.link(name, private)
            except FileExistsError:
                pass
        finally:
            os.unlink(name)
    key = serialization.load_pem_private_key(private.read_bytes(), password=None)
    public.parent.mkdir(parents=True, exist_ok=True)
    data = key.public_key().public_bytes(
        serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo
    )
    if not public.exists() or public.read_bytes() != data:
        fd, name = tempfile.mkstemp(dir=public.parent, prefix=".public-")
        try:
            with os.fdopen(fd, "wb") as output:
                if hasattr(os, "fchmod"):
                    os.fchmod(output.fileno(), 0o640)
                output.write(data)
                output.flush()
                os.fsync(output.fileno())
            os.replace(name, public)
        finally:
            if os.path.exists(name):
                os.unlink(name)
    return key, hashlib.sha256(data).hexdigest()[:16]


def sign(
    body,
    *,
    owner=None,
    session="",
    scope="public-read",
    public_only=True,
    allowed_hosts=(),
    asset_hosts=None,
    operation="",
    path="/crawl",
):
    import jwt

    key, kid = ensure_keys()
    now = int(time.time())
    payload = {
        "iss": "dethrottled-api",
        "aud": "dnb",
        "iat": now,
        "nbf": now - 1,
        "exp": now + 60,
        "jti": operation or uuid.uuid4().hex,
        "sub": owner or "local:" + kid,
        "session": session,
        "scope": scope,
        "public_only": bool(public_only),
        "allowed_hosts": list(allowed_hosts),
        "asset_hosts": list(asset_hosts) if asset_hosts is not None else None,
        "page_mode": "fresh",
        "path": path,
        "method": "POST",
        "body_sha256": body_digest(body),
    }
    return jwt.encode(payload, key, algorithm="EdDSA", headers={"kid": kid})


def verify(token, body, public_file, *, path="/crawl", now=None):
    import jwt

    # Read the public file for each admission, so key rotation does not leave a
    # revoked verifier cached indefinitely. No secrets or claims are logged.
    raw = Path(public_file).read_bytes()
    claims = jwt.decode(
        token,
        raw,
        algorithms=["EdDSA"],
        audience="dnb",
        issuer="dethrottled-api",
        options={
            "require": [
                "exp",
                "iat",
                "nbf",
                "jti",
                "sub",
                "session",
                "scope",
                "public_only",
                "allowed_hosts",
                "page_mode",
                "path",
                "method",
                "body_sha256",
            ]
        },
    )
    if (
        claims["path"] != path
        or claims["method"] != "POST"
        or claims["body_sha256"] != body_digest(body)
        or not isinstance(claims["iat"], int)
        or not isinstance(claims["exp"], int)
        or claims["exp"] - claims["iat"] > 60
        or claims["iat"] > int(time.time()) + 1
        or type(claims["public_only"]) is not bool
        or any(
            not isinstance(claims[k], str) or len(claims[k]) > 128
            for k in ["sub", "session", "scope", "jti"]
        )
        or claims["page_mode"] not in {"fresh", "persistent"}
        or not isinstance(claims["allowed_hosts"], list)
        or len(claims["allowed_hosts"]) > 32
        or any(not isinstance(host, str) or len(host) > 253 for host in claims["allowed_hosts"])
    ):
        raise ValueError("delegation_policy_mismatch")
    assets = claims.get("asset_hosts")
    if assets is not None and (
        not isinstance(assets, list)
        or len(assets) > 32
        or any(not isinstance(host, str) or len(host) > 253 for host in assets)
    ):
        raise ValueError("delegation_asset_policy_mismatch")
    return claims


def _adapter_networks():
    raw = os.getenv("DETHROTTLED_ADAPTER_CIDRS", "127.0.0.1/32,::1/128")
    networks = []
    for part in raw.split(","):
        part = part.strip()
        if not part:
            continue
        try:
            networks.append(ipaddress.ip_network(part, strict=False))
        except ValueError:
            continue
    return tuple(networks)


class CallerIdentityMiddleware:
    """Verify forwarded client credentials; body namespaces never grant ownership.

    Core remains a private/local service, not a replacement for the public gateway.
    The forwarded identity header is accepted only from a configured adapter peer,
    so a LAN client cannot assert an owner by calling the core directly.
    """

    def __init__(self, app):
        from .access import Registry

        self.app = app
        self.adapter_networks = _adapter_networks()
        self.registry = Registry(
            os.getenv(
                "DETHROTTLED_CALLER_REGISTRY",
                os.getenv("DETHROTTLED_TOKEN_REGISTRY", "/etc/dethrottled-access/tokens.json"),
            )
        )

    def _peer_is_adapter(self, scope):
        client = scope.get("client")
        host = client[0] if isinstance(client, (tuple, list)) and client else ""
        try:
            address = ipaddress.ip_address(host)
        except ValueError:
            return False
        if getattr(address, "ipv4_mapped", None) is not None:
            address = address.ipv4_mapped
        return any(address in network for network in self.adapter_networks)

    async def __call__(self, scope, receive, send):
        import asyncio

        from .access import CLAIMS, AccessError

        if scope["type"] != "http" or os.getenv("DETHROTTLED_DNB", "0") != "1":
            return await self.app(scope, receive, send)
        from starlette.responses import JSONResponse

        headers = dict(scope.get("headers", []))
        forwarded = headers.get(b"x-dethrottled-caller-authorization")
        path = scope.get("path", "")
        required = (
            "drive"
            if path == "/drive"
            else "corpus"
            if path.startswith("/corpus/")
            else "web"
        )
        token = None
        if forwarded:
            if not self._peer_is_adapter(scope):
                return await JSONResponse(
                    {"error": "untrusted_identity_source"}, status_code=403
                )(scope, receive, send)
            try:
                claims = await asyncio.to_thread(self.registry.verify, forwarded.decode())
                if required not in claims["scopes"]:
                    raise AccessError("insufficient_scope", 403)
                token = CLAIMS.set(claims)
            except (AccessError, UnicodeError) as exc:
                return await JSONResponse(
                    {"error": getattr(exc, "code", "invalid_credentials")},
                    status_code=getattr(exc, "status", 401),
                )(scope, receive, send)
        try:
            return await self.app(scope, receive, send)
        finally:
            if token is not None:
                CLAIMS.reset(token)
