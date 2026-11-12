"""Script-facing contracts for Dethrottled Programmatic Resolve."""

import hashlib
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from . import __version__
from .access import CLAIMS
from .api_models import JobReadBody, SearchBody

SCHEMA = 1
MAX_ITEMS = 500
ItemKey = Annotated[str, Field(min_length=1, max_length=100)]
Url = Annotated[str, Field(min_length=1, max_length=2048)]


class ResolveOptions(BaseModel):
    model_config = ConfigDict(extra="forbid")
    render: Literal["auto", "never"] = "auto"
    cache_mode: Literal["use", "refresh", "bypass"] = "use"
    max_age: float | None = Field(default=None, ge=0, le=1814400)
    max_chars: int = Field(default=2000, ge=100, le=16000)
    index_public: bool = False
    evidence_namespace: str = Field(default="local", max_length=100)

    @model_validator(mode="after")
    def scope_to_verified_caller(self):
        if claims := CLAIMS.get():
            self.evidence_namespace = claims["namespace"]
        return self


class BatchBody(ResolveOptions):
    urls: list[Url] = Field(min_length=1, max_length=MAX_ITEMS)
    item_keys: list[ItemKey] | None = Field(default=None, max_length=MAX_ITEMS)
    operation_id: str = Field(default="", max_length=100, pattern=r"^[A-Za-z0-9._-]*$")

    @model_validator(mode="after")
    def matching_unique_keys(self):
        if self.item_keys is not None and (
            len(self.item_keys) != len(self.urls) or len(set(self.item_keys)) != len(self.urls)
        ):
            raise ValueError("item_keys must be unique and match the URL count")
        return self


class BatchReadBody(JobReadBody):
    limit: int = Field(default=10, ge=1, le=50)

    @model_validator(mode="after")
    def scope_to_verified_caller(self):
        if claims := CLAIMS.get():
            self.evidence_namespace = claims["namespace"]
        return self


class BatchRetryBody(BatchReadBody):
    operation_id: str = Field(min_length=1, max_length=100, pattern=r"^[A-Za-z0-9._-]+$")


class ResolveQueryBody(ResolveOptions):
    search: SearchBody
    alternatives: int = Field(default=0, ge=0, le=4)


def utc_now():
    return datetime.now(timezone.utc).isoformat()


def header_date(value):
    try:
        date = parsedate_to_datetime(value)
        return date.astimezone(timezone.utc).isoformat() if date.tzinfo else None
    except (TypeError, ValueError, OverflowError):
        return None


def evidence(url, row):
    text = row.get("content", "")
    canonical = row.get("_index_text") or text
    attempts = row.get("acquisition_attempts", [])
    reason = row.get("failure_reason")
    quality = row.get("quality", "failed")
    challenged = any(a.get("outcome") == "challenge" for a in attempts)
    fetched = row.get("retrieved_at")
    origin = row.get("origin_response", {})
    observed = next((a for a in reversed(attempts) if a.get("http_status")), {})
    status = origin.get("status") or (observed.get("http_status") if not text else None)
    blocked = reason in {"public_target_required", "redirect_target_not_public"}
    if row.get("policy_blocked") or blocked:
        outcome = "blocked"
    elif not text and (challenged or status in {401, 403}):
        outcome = "blocked"
    elif not text:
        outcome = "failed"
    elif quality != "ok" or row.get("source_partial") or row.get("content_status") == "partial":
        outcome = "partial"
    else:
        outcome = "usable"
    retryable = (status in {408, 425, 429} or status >= 500) if status else None
    modified = header_date(origin.get("last_modified"))
    return {
        "requested_url": url,
        "final_url": row.get("final_url") or (observed.get("final_url") if not text else None),
        "canonical_url": row.get("source_canonical"),
        "title": row.get("title") or None,
        "outcome": outcome,
        "quality": quality,
        "failure_reason": reason,
        "retryable": retryable if outcome == "failed" else False,
        "policy_blocked": row.get("policy_blocked"),
        "content_type": row.get("content_type"),
        "content": text,
        "content_chars": row.get("content_chars", len(text)),
        "preview_truncated": bool(row.get("truncated")),
        "source_partial": bool(row.get("source_partial")),
        "content_status": row.get("content_status"),
        "extraction_completeness": row.get("extraction", {}).get("completeness"),
        "content_sha256": hashlib.sha256(canonical.encode()).hexdigest() if canonical else None,
        "source_sha256": row.get("source_sha256"),
        "document_id": row.get("document_id"),
        "document_expires_at": row.get("document_expires_at"),
        "acquisition_tier": row.get("tier"),
        "extractor_version": __version__,
        "warnings": row.get("warnings", []),
        "attempts": attempts,
        "cached": bool(row.get("cached")),
        "fetched_at": fetched,
        "checked_at": (fetched or observed.get("observed_at")) if not row.get("cached") else None,
        "http_status": status,
        "last_modified": modified,
        "last_modified_source": "http_header" if modified else None,
        "published_at": row.get("published") or None,
        "published_at_source": row.get("date_source") if row.get("published") else None,
        "completed_at": utc_now(),
    }


def batch_page(page, payload):
    keys = payload.get("item_keys")
    rows = page["results"]
    for row in rows:
        index = row["source_index"]
        row["item_key"] = keys[index] if keys is not None else str(index)
        row.setdefault("requested_url", payload["urls"][index])
        row.setdefault("outcome", "failed")
    return {k: v for k, v in page.items() if k != "workflow"} | {"schema_version": SCHEMA}
