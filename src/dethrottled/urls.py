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


def host_family(url: str) -> list:
    """The page's host and its www./bare twin, for automatic browser reads.

    A browser session only navigates to its allowed hosts, matched exactly, so
    reading reddit.com/... failed with ERR_BLOCKED_BY_CLIENT when the site
    redirected to www.reddit.com (found 16 Nov 2026). The twin is the same
    site; nothing wider is allowed. Callers that pass their own allowed_hosts
    to /drive are unaffected.
    """
    from urllib.parse import urlsplit
    host = (urlsplit(url or "").hostname or "").lower().rstrip(".")
    if not host:
        return []
    labels = host.split(".")
    if host.replace(".", "").isdigit() or len(labels) < 2:
        return [host]
    if labels[0] == "www":
        return [host, host[4:]] if len(labels) >= 3 else [host]
    # Only a bare domain gets a www twin (reddit.com, bbc.co.uk), never a
    # subdomain: www.quotes.toscrape.com is not the same site.
    second_level = len(labels) == 3 and len(labels[-1]) == 2 and labels[-2] in {
        "co", "com", "org", "net", "gov", "ac", "edu", "or", "ne", "go"}
    if len(labels) == 2 or second_level:
        return [host, "www." + host]
    return [host]
