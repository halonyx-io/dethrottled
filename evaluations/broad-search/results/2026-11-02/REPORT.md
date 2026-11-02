# Broad browser search — 2 November 2026

The 1.1.0 public request accepted `limit=50`, but this live query still returned ten
results. Inspection found that the core omitted the count from its browser-worker
request, the worker inspected at most 12 anchors, and its race canceled the other
engines on the first usable page. The higher API ceiling therefore did not expand
this browser-backed discovery path.

The follow-up forwards the count and preserves the fast path for requests of 12
or fewer. Broader requests extract up to the requested ceiling per page, collect
usable engines, deduplicate URLs and follow same-origin next-page controls. Work
stays bounded by five pages per engine and the existing six-second engine budget;
no arbitrary destination or script is accepted. Partial earlier results survive a
later challenge/error. Per-row engine provenance and per-engine page/reason counts
are retained. No new upstream, account, key or proxy is introduced.

The native Chromium harness checks 50 rows from a 55-anchor page, a one-result
first-page-only request, 50 unique pooled/paginated results, and retained first-page
results after later 403 responses. Both native browser CI jobs execute the harness.
These are synthetic retrieval contracts, not semantic ranking or answer verification.

[Live baseline](live-baseline.json) used software rendering and the same query/IP as
[the three-page pilot](live-three-page-pilot.json): ten versus 38 discovered URLs,
about 0.91 versus 3.23 seconds. The first ten baseline URLs were retained. This is
one sequential comparison, not a general success-rate or latency estimate. The
larger pool includes older documentation versions and mirrors; it does not imply
38 independent facts or improved answer accuracy. The [final five-page observation](live-final.json) returns 50 URLs in about
3.77 seconds. These are discovery URLs, not verified additional reads or answers.
[Native contracts](native-final.json) pass, and the [regression suite](regression.log)
reports 654 passed, 15 skipped and two network tests deselected. An initial harness
assertion wrongly required multiple engines even when one engine already fulfilled
the 50-result request; the corrected fixture ends each engine after three pages
to exercise aggregation separately from the five-page budget case. Defaults, admission and document recovery stay unchanged.
