"""Translate explicit host constraints into the existing enforced site operators."""

from __future__ import annotations

import re

SITE = re.compile(r"(?<![\w-])(-?)site:([\w.-]+)", re.I)


def hostname(value: str) -> str:
    """Accept hosts, not URLs, ports, wildcards or ambiguous substring patterns."""
    value = value.strip().rstrip(".").lower()
    try:
        value = value.encode("idna").decode("ascii")
    except UnicodeError as exc:
        raise ValueError("domain must be a hostname") from exc
    labels = value.split(".")
    if (
        len(value) > 253
        or not value
        or any(not re.fullmatch(r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?", label) for label in labels)
    ):
        raise ValueError("domain must be a hostname without scheme, path, port or wildcard")
    return value


def within(host: str, domain: str) -> bool:
    return host == domain or host.endswith("." + domain)


def discovery_query(query: str, domains=(), exclude_domains=()) -> tuple[str, bool]:
    """Intersect explicit includes with site: includes; exclusions always win.

    Return an impossible flag rather than broadening contradictory constraints.
    Without explicit constraints preserve the original provider query exactly.
    """
    if not domains and not exclude_domains:
        return query, False
    operators = SITE.findall(query)
    existing = [name.lower().rstrip(".") for minus, name in operators if not minus]
    excluded = list(
        dict.fromkeys(
            [name.lower().rstrip(".") for minus, name in operators if minus] + list(exclude_domains)
        )
    )
    included = list(domains) or existing
    if domains and existing:
        included = list(
            dict.fromkeys(
                a if within(a, b) else b
                for a in domains
                for b in existing
                if within(a, b) or within(b, a)
            )
        )
        if not included:
            return query, True
    admitted = [name for name in included if not any(within(name, d) for d in excluded)]
    if included and not admitted:
        return query, True
    # Leave existing operators in place for exclusion-only changes. Explicit
    # includes replace them with their intersection; grouping expresses OR.
    base = SITE.sub("", query).strip() if domains else query
    if domains:
        base = re.sub(r"\(\s*(?:OR\s*)*\)", "", base, flags=re.I).strip()
        base = re.sub(r"(?:\s+OR)+\s*$|^\s*(?:OR\s+)+", "", base, flags=re.I).strip()
    positives = (
        "(" + " OR ".join("site:" + d for d in admitted) + ")"
        if len(admitted) > 1
        else "site:" + admitted[0]
        if admitted
        else ""
    )
    parts = [base, positives if domains else ""]
    parts.extend("-site:" + d for d in (excluded if domains else exclude_domains))
    return " ".join(part for part in parts if part), False
