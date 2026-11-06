"""Bounded deterministic fields from the HTML selected by the acquisition ladder."""

from __future__ import annotations

import hashlib

from selectolax.lexbor import LexborHTMLParser

MAX_OUTPUT = 64000


def fields(row: dict, specifications: dict, html: str, *, html_partial=False) -> dict:
    """Add structured results without changing prose quality or indexing policy."""
    tree = LexborHTMLParser(html) if html else None
    values, provenance, missing, limited = {}, {}, [], []
    remaining = MAX_OUTPUT
    for name, rule in specifications.items():
        nodes = tree.css(rule.selector) if tree is not None else []
        selected = nodes[: rule.max_matches if rule.all else 1]
        extracted = []
        for node in selected:
            text = (
                node.attributes.get(rule.attribute, "")
                if rule.attribute
                else node.text(separator=" ", strip=True)
            ) or ""
            budget = min(rule.max_chars, remaining)
            if len(text) > budget:
                limited.append(name)
            value = text[:budget]
            remaining -= len(value)
            if value:
                extracted.append(value)
        if rule.all and len(nodes) > rule.max_matches:
            limited.append(name)
        values[name] = extracted if rule.all else extracted[0] if extracted else None
        if rule.required and not extracted:
            missing.append(name)
        provenance[name] = {
            "selector": rule.selector,
            "attribute": rule.attribute or None,
            "matches": len(nodes),
            "returned": len(extracted),
        }
    row["structured"] = values
    row["structured_status"] = {
        "source_html_partial": bool(html_partial),
        "satisfied": not missing and bool(html),
        "missing": missing,
        "reason": "html_unavailable" if not html else "fields_absent" if missing else "satisfied",
        "truncated_fields": list(dict.fromkeys(limited)),
        "verification": "selector_matches_only; no semantic or answer verification",
    }
    row["structured_provenance"] = {
        "source_url": row.get("final_url", row.get("url")),
        "document_id": row.get("document_id"),
        "html_sha256": hashlib.sha256(html.encode()).hexdigest() if html else None,
        "fields": provenance,
        "offsets": "HTML selectors; not canonical prose offsets",
    }
    return row
