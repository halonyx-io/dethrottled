"""URL identity normalization shared by retrieval and discovery."""
from __future__ import annotations

from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

# Tracking params carry no meaning and split one article into several rows.
_JUNK_PARAMS = ("utm_", "fbclid", "gclid", "mc_cid", "mc_eid", "ref", "ref_src",
                "igshid", "s_cid", "cmpid", "spm", "_ga")


def canonical_url(url: str) -> str:
    """One URL per article, so the same page is not three rows.

    Strips tracking parameters, the fragment, a trailing slash, and the m. and
    amp. hosts that serve the same article at a different address. Deliberately
    string work: the pool showed 81 distinct domains across 109 rows, so
    duplication was never bad enough to justify hashing content, let alone
    embedding it.
    """
    try:
        parts = urlsplit((url or "").strip())
    except ValueError:
        return url or ""
    if not parts.netloc:
        return url or ""

    host = parts.netloc.lower()
    for prefix in ("www.", "m.", "amp."):
        if host.startswith(prefix):
            host = host[len(prefix):]
    kept = [(k, v) for k, v in parse_qsl(parts.query, keep_blank_values=True)
            if not k.lower().startswith(_JUNK_PARAMS)]
    path = parts.path.rstrip("/") or "/"
    return urlunsplit((parts.scheme or "https", host, path,
                       urlencode(kept), ""))
