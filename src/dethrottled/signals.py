"""Lightweight, explainable result signals: source type, page type, dates.

These are derived from the URL and the extraction result. They are deliberately
not a semantic classifier: an agent can see why a source was labelled `repo` or
a date was labelled `snippet`, and a wrong label is cheap to correct.
"""

from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from urllib.parse import urlparse

_MONTHS = {
    "jan": 1, "january": 1, "feb": 2, "february": 2, "mar": 3, "march": 3,
    "apr": 4, "april": 4, "may": 5, "jun": 6, "june": 6, "jul": 7, "july": 7,
    "aug": 8, "august": 8, "sep": 9, "sept": 9, "september": 9, "oct": 10,
    "october": 10, "nov": 11, "november": 11, "dec": 12, "december": 12,
}
_DATE_PATTERNS = (
    re.compile(r"\b(20\d{2}-\d{2}-\d{2})\b"),
    re.compile(r"\b(\d{1,2}\s+(?:Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|"
               r"May|Jun(?:e)?|Jul(?:y)?|Aug(?:ust)?|Sep(?:t(?:ember)?)?|Oct(?:ober)?|"
               r"Nov(?:ember)?|Dec(?:ember)?)\s+20\d{2})\b", re.I),
    re.compile(r"\b((?:Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|"
               r"Jun(?:e)?|Jul(?:y)?|Aug(?:ust)?|Sep(?:t(?:ember)?)?|Oct(?:ober)?|"
               r"Nov(?:ember)?|Dec(?:ember)?)\s+\d{1,2},?\s+20\d{2})\b", re.I),
)

_DOCS_HOSTS = (
    "docs.", "developer.", "readthedocs.io", "python.org", "mozilla.org",
    "kubernetes.io", "rust-lang.org", "learn.microsoft.com", "developer.apple.com",
)
_PAPER_HOSTS = (
    "arxiv.org", "doi.org", "pubmed.ncbi.nlm.nih.gov", "ncbi.nlm.nih.gov",
    "openalex.org", "semanticscholar.org", "nature.com", "sciencedirect.com",
    "springer.com", "ieee.org", "acm.org", "biorxiv.org", "medrxiv.org",
)
_REPO_HOSTS = ("github.com", "gitlab.com", "bitbucket.org", "codeberg.org", "sr.ht")
_FORUM_HOSTS = (
    "stackoverflow.com", "stackexchange.com", "reddit.com", "news.ycombinator.com",
    "discourse.org",
)
_REFERENCE_HOSTS = ("wikipedia.org", "britannica.com", "worldcat.org")
_NEWS_HOSTS = (
    "reuters.com", "apnews.com", "bbc.co.uk", "bbc.com", "cnn.com", "nytimes.com",
    "theguardian.com", "washingtonpost.com", "bloomberg.com", "ft.com",
)
_BLOG_HOSTS = ("medium.com", "substack.com", "dev.to", "hashnode.com", "blog.")


def _host(url: str) -> str:
    try:
        host = (urlparse(url or "").netloc or "").lower()
    except ValueError:
        return ""
    if ":" in host:
        host = host.split(":", 1)[0]
    return host[4:] if host.startswith("www.") else host


def _path(url: str) -> str:
    try:
        return (urlparse(url or "").path or "").lower()
    except ValueError:
        return ""


def source_type(url: str) -> str:
    """Classify a source by host/path: docs, paper, repo, forum, reference, news,
    blog or other. This is a navigation aid, not an authority claim."""
    host = _host(url)
    path = _path(url)
    if not host:
        return "other"
    if any(host == item or host.endswith("." + item) for item in _REPO_HOSTS):
        return "repo"
    if any(host == item or host.endswith("." + item) for item in _PAPER_HOSTS):
        return "paper"
    if any(host == item or host.endswith("." + item) for item in _FORUM_HOSTS):
        return "forum"
    if any(host == item or host.endswith("." + item) for item in _REFERENCE_HOSTS):
        return "reference"
    if (any(host == item or host.endswith("." + item) for item in _NEWS_HOSTS)
            or path.startswith("/news")):
        return "news"
    if (host.startswith("blog.")
            or any(host == item or host.endswith("." + item) for item in _BLOG_HOSTS)):
        return "blog"
    if any(host.startswith(item) or item in host for item in _DOCS_HOSTS):
        return "docs"
    return "other"


def page_type(row: dict) -> str:
    """Describe the extraction result: article, list, document, unreadable or unknown."""
    content_type = str(row.get("content_type") or "").lower()
    status = str(row.get("content_status") or "").lower()
    if content_type and content_type not in {
        "text/html", "application/xhtml+xml", "text/plain", "",
    }:
        return "document"
    if status == "navigation_only":
        return "list"
    if row.get("quality") == "failed" or not (row.get("content") or row.get("text")):
        return "unreadable"
    return "article"


def fetch_relevance(row: dict, max_score: float | None = None) -> str:
    """High/medium/low fetch priority from rank, consensus and source type."""
    engines = len(set(row.get("engines") or [row.get("engine") or ""]))
    score = row.get("score")
    if max_score and isinstance(score, (int, float)):
        ratio = score / max_score
        if ratio >= 0.60:
            return "high"
        if ratio <= 0.15 and engines < 2:
            return "low"
    kind = source_type(row.get("url", ""))
    if engines >= 2 or kind in {"docs", "paper", "repo", "reference"}:
        return "high"
    if kind in {"news", "blog", "forum"}:
        return "medium"
    return "medium"


def parse_date(value: str):
    """Parse the date forms search engines and feeds actually send."""
    raw = (value or "").strip()
    if not raw:
        return None
    for parser in (parsedate_to_datetime,):
        try:
            when = parser(raw)
            if when is not None:
                return when if when.tzinfo else when.replace(tzinfo=timezone.utc)
        except (TypeError, ValueError, OverflowError):
            pass
    try:
        when = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        return when if when.tzinfo else when.replace(tzinfo=timezone.utc)
    except ValueError:
        pass
    for pattern in _DATE_PATTERNS:
        match = pattern.search(raw)
        if not match:
            continue
        token = match.group(1)
        for fmt in ("%Y-%m-%d", "%d %B %Y", "%d %b %Y", "%B %d, %Y", "%B %d %Y",
                    "%b %d, %Y", "%b %d %Y"):
            try:
                return datetime.strptime(token, fmt).replace(tzinfo=timezone.utc)
            except ValueError:
                continue
    return None


def age_days(value: str):
    when = parse_date(value)
    if when is None:
        return None
    return max(0, (datetime.now(timezone.utc) - when).days)


def date_provenance(row: dict) -> tuple[str, str]:
    """Return (date, source). A snippet date is a lead, never a publication proof."""
    raw = (row.get("publishedDate") or row.get("published") or "").strip()
    if raw:
        declared = row.get("date_source")
        return raw, declared if declared in {"snippet", "page"} else "structured"
    snippet = (row.get("snippet") or "").strip()
    if snippet:
        for pattern in _DATE_PATTERNS:
            match = pattern.search(snippet)
            if match:
                return match.group(1), "snippet"
    return "", "none"


# A date more than this far ahead of the clock is a parse or provider error.
FUTURE_TOLERANCE = timedelta(days=1)
_RELATIVE = re.compile(
    r"^\s*(\d+|an?|one)\s+(minute|hour|day|week|month|year)s?\s+ago\b", re.IGNORECASE)
_RELATIVE_STEP = {"minute": (timedelta(minutes=1), "day"), "hour": (timedelta(hours=1), "day"),
                  "day": (timedelta(days=1), "day"), "week": (timedelta(days=7), "week"),
                  "month": (timedelta(days=30), "month"), "year": (timedelta(days=365), "year")}


def resolve_relative_date(row: dict, now: datetime | None = None) -> dict:
    """Turn a leading "3 days ago" into a dated snippet lead at capture time.

    The label is only meaningful relative to when it was seen, so the date is
    fixed when the row is captured (and cached), with the original label, its
    precision and the observation time kept beside it. Rows that already carry
    a provider date are left alone.
    """
    if row.get("publishedDate") or row.get("published") or row.get("date_relative"):
        return row
    match = _RELATIVE.match(row.get("snippet") or "")
    if not match:
        return row
    count = 1 if match[1].lower() in {"a", "an", "one"} else int(match[1])
    step, precision = _RELATIVE_STEP[match[2].lower()]
    now = now or datetime.now(timezone.utc)
    row.update(publishedDate=(now - count * step).date().isoformat(), date_source="snippet",
               date_relative=match[0].strip(), date_precision=precision,
               observed_at=now.isoformat(timespec="seconds"))
    return row


def date_rejection(value: str, now: datetime | None = None) -> str | None:
    """Why a date cannot be a publication date, or None when it can."""
    when = parse_date(value)
    if when is not None and when > (now or datetime.now(timezone.utc)) + FUTURE_TOLERANCE:
        return "future"
    return None


def _snippet_hint(row: dict, value: str) -> dict:
    hint = {"value": value, "source": "snippet", "verified": False}
    if row.get("date_relative"):
        hint.update(value=row["date_relative"], resolved=value,
                    precision=row.get("date_precision"), observed_at=row.get("observed_at"))
    return hint


def search_date_fields(row):
    """Expose provider-reported publication days separately from snippet leads.

    A snippet date is a lead, never `published_at`. Impossible dates are not
    silently dropped: they are reported under `date_hint_rejected`.
    """
    value, source = date_provenance(row)
    rejected = row.get("date_hint_rejected")
    if value and (reason := date_rejection(value)):
        rejected = {"value": value, "reason": reason}
        value, source = "", "none"
    extra = {"date_hint_rejected": rejected} if rejected else {}
    if source in {"structured", "page"} and (parsed := parse_date(value)):
        return {"published_at": parsed.date().isoformat(),
                "date_hint": {"value": value,
                              "source": "page" if source == "page" else "provider",
                              "verified": False}, **extra}
    if not value:
        match = re.match(r"^\s*(\d+\s+(?:hours?|days?|weeks?|months?|years?)\s+ago)\b",
                         row.get("snippet") or "", re.IGNORECASE)
        if match:
            value, source = match[1], "snippet"
    return {"published_at": None, "date_hint": (
        _snippet_hint(row, value) if source == "snippet" else None), **extra}


def annotate_dates(rows: list) -> tuple[list, int]:
    """Add date_source/published_age_days to rows and count dated results."""
    dated = 0
    for row in rows:
        value, source = date_provenance(row)
        if value and (reason := date_rejection(value)):
            row["date_hint_rejected"] = {"value": value, "reason": reason}
            row.pop("publishedDate", None)
            row.pop("published", None)
            value, source = "", "none"
        row["date_source"] = source
        row["published_age_days"] = age_days(value) if value else None
        if value and source != "none":
            row["publishedDate"] = value
            dated += 1
    return rows, dated


def date_coverage(rows: list) -> dict:
    """How the returned rows are dated: provider, page, snippet lead or none."""
    counts = {"provider": 0, "page": 0, "snippet": 0, "none": 0, "rejected": 0}
    for row in rows:
        source = row.get("date_source") or "none"
        counts["provider" if source == "structured" else
               source if source in counts else "none"] += 1
        counts["rejected"] += bool(row.get("date_hint_rejected"))
    return counts
