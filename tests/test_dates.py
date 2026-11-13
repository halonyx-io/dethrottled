"""Dates: resolved at capture, rejected visibly, and declared by the page.

A date is either provider-reported (`published_at`), a lead from snippet text
(`date_hint`, never verified), declared by the fetched page (`date_source:
page`), or absent. Impossible values are reported, not silently dropped.
"""
from datetime import datetime, timedelta, timezone

import pytest

from dethrottled import extract, rank, signals

NOW = datetime(2026, 11, 13, 12, 0, tzinfo=timezone.utc)


@pytest.mark.parametrize("snippet,resolved,precision", [
    ("3 days ago — Kernel 6.12 released", "2026-11-10", "day"),
    ("5 hours ago · Earnings date set", "2026-11-13", "day"),
    ("an hour ago Results", "2026-11-13", "day"),
    ("2 weeks ago Notes", "2026-10-30", "week"),
    ("1 month ago Budget", "2026-10-14", "month"),
])
def test_relative_age_is_resolved_at_capture(snippet, resolved, precision):
    row = signals.resolve_relative_date({"snippet": snippet}, now=NOW)
    assert row["publishedDate"] == resolved
    assert row["date_source"] == "snippet"
    assert row["date_precision"] == precision
    assert row["observed_at"] == "2026-11-13T12:00:00+00:00"
    hint = signals.search_date_fields(row)["date_hint"]
    assert hint["value"] == row["date_relative"]
    assert hint["resolved"] == resolved
    assert signals.search_date_fields(row)["published_at"] is None


def test_relative_resolution_leaves_provider_dates_and_plain_text_alone():
    dated = {"snippet": "3 days ago", "publishedDate": "2026-11-01"}
    assert signals.resolve_relative_date(dict(dated), now=NOW) == dated
    plain = {"snippet": "Released after 3 days of testing"}
    assert signals.resolve_relative_date(dict(plain), now=NOW) == plain


def test_future_dates_are_rejected_visibly():
    future = (datetime.now(timezone.utc) + timedelta(days=30)).date().isoformat()
    fields = signals.search_date_fields({"publishedDate": future})
    assert fields["published_at"] is None and fields["date_hint"] is None
    assert fields["date_hint_rejected"] == {"value": future, "reason": "future"}
    rows, dated = signals.annotate_dates([{"publishedDate": future}])
    assert dated == 0 and rows[0]["date_source"] == "none"
    assert rows[0]["date_hint_rejected"]["reason"] == "future"
    tomorrow = (datetime.now(timezone.utc) + timedelta(hours=12)).isoformat()
    assert signals.date_rejection(tomorrow) is None


def test_date_coverage_counts_each_kind():
    future = (datetime.now(timezone.utc) + timedelta(days=30)).date().isoformat()
    rows, _ = signals.annotate_dates([
        {"publishedDate": "2026-11-01"}, {"snippet": "8 Oct 2025 — notes"},
        {"published": "2026-10-01", "date_source": "page"}, {"snippet": "undated"},
        {"publishedDate": future}])
    assert signals.date_coverage(rows) == {"provider": 1, "page": 1, "snippet": 1,
                                           "none": 2, "rejected": 1}


def test_page_dates_are_provider_tier_with_their_own_source():
    fields = signals.search_date_fields({"published": "2026-10-01T08:00:00Z",
                                         "date_source": "page"})
    assert fields["published_at"] == "2026-10-01"
    assert fields["date_hint"]["source"] == "page"


def test_rank_uses_the_shared_parser():
    # Written forms used to be undated for recency ranking.
    assert rank.age_days({"publishedDate": "8 Oct 2025"}) is not None
    assert rank.age_days({"publishedDate": "not a date"}) is None


@pytest.mark.parametrize("head,expected", [
    ('<meta property="article:published_time" content="2026-09-30T07:00:00Z">',
     "2026-09-30T07:00:00Z"),
    ('<meta name="citation_publication_date" content="2025/04/02">', "2025/04/02"),
    ('<script type="application/ld+json">{"@type":"NewsArticle",'
     '"datePublished":"2026-08-01","dateModified":"2026-08-03"}</script>', "2026-08-01"),
])
def test_page_metadata_reads_declared_dates(head, expected):
    meta = extract.page_metadata(f"<html><head>{head}</head><body></body></html>")
    assert meta["published"] == expected


def test_microdata_time_element_is_read():
    html = ('<html><body><article><time itemprop="datePublished" datetime="2026-07-04">'
            'July 4</time></article></body></html>')
    assert extract.page_metadata(html)["published"] == "2026-07-04"


def test_extraction_prefers_the_declared_date():
    filler = " ".join(f"Sentence {i} explains how the journal records each change."
                      for i in range(40))
    html = ('<html><head><meta property="article:published_time" content="2026-09-30">'
            f'</head><body><main><p>{filler}</p></main></body></html>')
    result = extract.extract(html, "https://fixture.example/story", max_chars=100_000)
    assert result["published"] == "2026-09-30"
    assert result["page_metadata"]["published"] == "2026-09-30"


def test_guessed_date_whose_year_is_not_in_the_page_is_rejected():
    # htmldate reads "the 3.14 series ... 3" on python.org as 2010-03-14.
    filler = " ".join(f"Major new features of the 3.14 series, item {i}, explained."
                      for i in range(40))
    html = (f"<html><body><main><p>{filler}</p><p>Release date: Oct. 7, 2025</p>"
            "</main></body></html>")
    meta = {}
    assert extract._page_date(meta, "2010-03-14", html) == ""
    assert meta["date_rejected"] == {"value": "2010-03-14", "reason": "year_not_in_page"}
    assert extract._page_date({}, "2025-10-07", html) == "2025-10-07"
    assert extract._page_date({"published": "2025-10-07T12:00:00Z"}, "2010-03-14", html) == \
        "2025-10-07T12:00:00Z"
