"""Bounded, process-local HTTP identities. Never share a jar between callers/origins."""

import threading
import time
from collections import OrderedDict
from contextlib import contextmanager
from urllib.parse import urljoin, urlsplit


def origin(url):
    parsed = urlsplit(url)
    return parsed.scheme.lower(), (parsed.hostname or "").lower(), parsed.port


class IdentityPool:
    def __init__(self, capacity=64, ttl=1800):
        self.capacity, self.ttl = capacity, ttl
        self.entries = OrderedDict()
        self.lock = threading.Lock()

    @contextmanager
    def borrow(self, namespace, url, transport, profile="", public_only=False):
        key = namespace, origin(url), transport, profile, public_only
        with self.lock:
            now = time.monotonic()
            for old_key, entry in list(self.entries.items()):
                if not entry["users"] and (now - entry["at"] > self.ttl or
                                          len(self.entries) >= self.capacity):
                    self.entries.pop(old_key)["session"].close()
            if key not in self.entries:
                # Busy jars are never evicted. Admission failure degrades to a
                # disposable identity rather than growing the pool without bound.
                cached = len(self.entries) < self.capacity
                if transport == "tls":
                    from curl_cffi import requests
                else:
                    from . import netfilter as requests
                entry = dict(session=requests.Session(), users=0, at=now,
                             lock=threading.Lock())
                if cached:
                    self.entries[key] = entry
            else:
                entry, cached = self.entries[key], True
                self.entries.move_to_end(key)
            entry["users"] += 1
        try:
            # Streaming response consumption happens inside this lease.
            with entry["lock"]:
                def get(target, **kwargs):
                    from . import netfilter as plain
                    if transport == "tls":
                        from curl_cffi import requests as client
                    else:
                        client = plain
                    follow = kwargs.pop("allow_redirects", True)
                    for _ in range(6):
                        # Off-origin redirects must not receive this identity's
                        # Domain cookies or populate its jar with another host.
                        request = (entry["session"].get if origin(target) == origin(url)
                                   else client.get)
                        from .adblock import check
                        check(target, "tls" if transport == "tls" else "http")
                        response = request(target, allow_redirects=False, **kwargs)
                        if (not follow or response.status_code not in {301, 302, 303, 307, 308}
                                or not response.headers.get("Location")):
                            return response
                        location = response.headers["Location"]
                        response.close()
                        target = urljoin(target, location)
                    raise ValueError("too_many_redirects")
                yield get
        finally:
            with self.lock:
                entry["users"] -= 1
                entry["at"] = time.monotonic()
                if not cached:
                    entry["session"].close()


POOL = IdentityPool()
