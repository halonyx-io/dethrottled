"""Bounded same-origin traversal with an honest, inspectable coverage ledger."""

from __future__ import annotations

import time
from collections import deque
from urllib.parse import urldefrag, urljoin, urlsplit, urlunsplit

from defusedxml import ElementTree
from defusedxml.common import DefusedXmlException
from selectolax.lexbor import LexborHTMLParser

from .dedupe import url_key


def canonical(url):
    p = urlsplit(urldefrag(url)[0])
    if p.scheme not in {"https", "http"} or not p.hostname or p.username or p.password:
        raise ValueError("http_url_required")
    return urlunsplit((p.scheme.lower(), p.netloc.lower(), p.path or "/", p.query, ""))


def links(text, base):
    if text.lstrip().startswith("<"):
        try:
            tree = ElementTree.fromstring(text)
            if tree.tag.rsplit("}", 1)[-1] in {"urlset", "sitemapindex"}:
                return [n.text.strip() for n in tree.iter()
                        if n.tag.rsplit("}", 1)[-1] == "loc" and n.text][:5000]
        except (ElementTree.ParseError, DefusedXmlException):
            pass
    tree = LexborHTMLParser(text)
    return [urljoin(base, a.attributes["href"]) for a in tree.css("a[href]")[:5000]]


def crawl(seeds, read, *, max_pages=20, max_depth=2, path_prefix="/", budget_seconds=120):
    seeds = list(dict.fromkeys(canonical(u) for u in seeds))
    origin = urlsplit(seeds[0])
    scope = (origin.scheme, origin.netloc)
    queue = deque((u, 0, None) for u in seeds)
    seen, rows, outside = {url_key(u) for u in seeds}, [], set()
    duplicates, dropped = 0, 0
    deadline = time.monotonic() + budget_seconds
    while queue and len(rows) < max_pages and time.monotonic() < deadline:
        url, depth, parent = queue.popleft()
        try:
            row = read(url)
        except Exception as exc:
            row = {"quality": "failed", "failure_reason": type(exc).__name__}
        final = row.get("final_url", url)
        final_parts = urlsplit(final)
        in_scope = ((final_parts.scheme, final_parts.netloc) == scope
                    and final_parts.path.startswith(path_prefix))
        entry = {"url": url, "depth": depth, "parent": parent,
                 "quality": row.get("quality", "failed"),
                 "document_id": row.get("document_id"),
                 "failure_reason": row.get("failure_reason"),
                 "source_partial": row.get("source_partial", False),
                 "warnings": row.get("warnings", [])[:10],
                 "policy_blocked": row.get("policy_blocked")}
        entry["discovery_truncated"] = bool(row.get("truncated"))
        if not in_scope:
            entry.update(quality="failed", failure_reason="redirect_outside_site_scope")
        rows.append(entry)
        # A small index page can be thin as evidence but still expose useful
        # links. Do not discard its same-origin frontier because prose is short.
        if row.get("quality") not in {"ok", "thin", "suspect"} or not in_scope:
            continue
        found = links(row.get("html") or row.get("content", ""), final)
        for target in found:
            try:
                target = canonical(target)
            except ValueError:
                continue
            p = urlsplit(target)
            if (p.scheme, p.netloc) != scope or not p.path.startswith(path_prefix):
                if len(outside) < 5000:
                    outside.add(target)
                continue
            if url_key(target) in seen:
                duplicates += 1
                continue
            if len(seen) >= 5000:
                dropped += 1
                continue
            seen.add(url_key(target))
            if depth < max_depth:
                queue.append((target, depth + 1, url))
            else:
                dropped += 1
    succeeded = sum(r["quality"] == "ok" for r in rows)
    return {"operation": "site_crawl",
            "outcome": ("no_ok_pages" if not succeeded else
                        "partial" if succeeded < len(rows) or queue or dropped else "pages_read"),
            "sources": rows,
            "coverage": {"attempted": len(rows),
                         "succeeded": succeeded,
                         "failed": sum(r["quality"] != "ok" for r in rows),
                         "discovered_in_scope": len(seen), "pending": len(queue),
                         "depth_or_discovery_limited": dropped,
                         "duplicate_links": duplicates, "outside_scope": len(outside),
                         "frontier_exhausted": not queue and not dropped,
                         "whole_site_complete": None,
                         "stop_reason": "page_limit" if queue and len(rows) >= max_pages
                         else "time_budget" if queue else "observed_frontier_exhausted",
                         "limitation": "Only linked/sitemap URLs observed; unlinked and JS-only "
                         "sources may be absent."},
            "continuation_urls": [u for u, _, _ in list(queue)[:10]],
            "answer_verified": False}


def map_site(seeds, read, *, max_pages=20, max_depth=2, path_prefix="/",
             max_discovery_requests=5, budget_seconds=60):
    """Read seeds and nested sitemap indexes, never every discovered HTML page.

    No retained evidence is created. Discovery acquisitions are counted separately
    from evidence reads; an exhausted sitemap is not proof of whole-site coverage.
    """
    seeds = list(dict.fromkeys(canonical(u) for u in seeds))
    origin = urlsplit(seeds[0])
    scope = origin.scheme, origin.netloc
    queue = deque((u, 0, None) for u in seeds)
    visited, seen, sources, attempts = set(), set(), [], []
    dropped = outside = 0
    deadline = time.monotonic() + budget_seconds

    def admit(url, depth, parent):
        nonlocal dropped, outside
        try:
            url = canonical(url)
        except ValueError:
            return
        parts = urlsplit(url)
        if (parts.scheme, parts.netloc) != scope or not parts.path.startswith(path_prefix):
            outside += 1
            return
        if url_key(url) in seen:
            return
        seen.add(url_key(url))
        if len(sources) >= max_pages:
            dropped += 1
        else:
            sources.append({"url": url, "depth": depth, "parent": parent})

    while (queue and len(attempts) < max_discovery_requests and len(sources) < max_pages
           and time.monotonic() < deadline):
        url, depth, parent = queue.popleft()
        if url in visited:
            continue
        visited.add(url)
        try:
            row = read(url)
        except Exception as exc:
            row = {"quality": "failed", "failure_reason": type(exc).__name__}
        final = row.get("final_url", row.get("url", url))
        parts = urlsplit(final)
        in_scope = ((parts.scheme, parts.netloc) == scope and parts.path.startswith(path_prefix))
        attempt = {"url": url, "final_url": final, "quality": row.get("quality", "failed"),
                   "failure_reason": row.get("failure_reason"),
                   "acquisition_attempts": row.get("acquisition_attempts", []),
                   "truncated": bool(row.get("truncated")),
                   "warnings": row.get("warnings", [])[:10]}
        attempts.append(attempt)
        if not in_scope:
            attempt.update(quality="failed", failure_reason="redirect_outside_site_scope")
            continue
        if row.get("quality") not in {"ok", "thin", "suspect"}:
            continue
        text = row.get("html") or row.get("content", "")
        root = ""
        try:
            root = ElementTree.fromstring(text).tag.rsplit("}", 1)[-1]
        except (ElementTree.ParseError, DefusedXmlException):
            pass
        found = links(text, final)
        if root not in {"urlset", "sitemapindex"}:
            admit(final, depth, parent)
        for target in found:
            if root == "sitemapindex":
                try:
                    target = canonical(target)
                except ValueError:
                    continue
                p = urlsplit(target)
                if (p.scheme, p.netloc) != scope or not p.path.startswith(path_prefix):
                    outside += 1
                elif depth < max_depth:
                    if len(queue) < 5000:
                        queue.append((target, depth + 1, final))
                    else:
                        dropped += 1
                else:
                    dropped += 1
            else:
                admit(target, depth + 1, final)
    failed = sum(a["quality"] == "failed" for a in attempts)
    partial = bool(queue or dropped or failed or any(a["truncated"] for a in attempts))
    return {"operation": "site_map", "mode": "map",
            "outcome": "partial" if sources and partial else "urls_discovered" if sources
                       else "no_urls_discovered", "sources": sources,
            "discovery_attempts": attempts,
            "coverage": {"attempted": 0, "discovery_requests": len(attempts),
                         "discovery_failed": failed, "returned_urls": len(sources),
                         "discovered_in_scope": len(seen), "pending": len(queue),
                         "depth_or_discovery_limited": dropped, "outside_scope": outside,
                         "whole_site_complete": None,
                         "stop_reason": "url_limit" if len(sources) >= max_pages else
                         "discovery_request_limit" if (queue and
                             len(attempts) >= max_discovery_requests)
                         else "time_budget" if queue else "observed_frontier_exhausted",
                         "limitation": "Seed/sitemap reads only; candidates are not fetched or "
                         "verified evidence. Unlinked and JS-only URLs may be absent."},
            "continuation_urls": [u for u, _, _ in list(queue)[:10]],
            "answer_verified": False}
