# P1 agent signals and correctness

2026-11-09. Candidate held. Test-bed only; no version bump, publish or deploy.
Production remains 1.7.1.

## Date provenance

Search rows now carry:

- `date_source`: `structured` (engine supplied), `snippet` (parsed from result
  text) or `none`.
- `published_age_days`: whole days since the parsed date, or null.
- First-row and `/v2/search` metadata: `dated_results` and `freshness_note`.

A snippet date is never presented as a publication proof. The warning appears
when fewer than half the results are dated:

> Most results are undated; dates are leads, not verified publication dates.

Example: `2026-11-09` → structured/age 0; `Updated 8 November 2026` →
snippet/age 1; undated → none.

## Source type, page type and fetch relevance

- `source_type`: `docs`, `paper`, `repo`, `forum`, `reference`, `news`, `blog`
  or `other`, from host and path. This is a navigation aid, not an authority
  claim.
- `page_type`: `article`, `list`, `document`, `unreadable` or `unknown`, from
  the extraction result.
- `fetch_relevance`: `high`, `medium` or `low`. High requires multiple engines,
  an authoritative source class, or a top relative BM25/fusion score; low is
  reserved for a zero/near-zero score without consensus.
- Research source items preserve source/date/relevance fields.

These are simple and explainable; no new model or dependency.

## Whole-bucket decoy detection

`search.drop_decoy_buckets` groups results by engine and measures the share of
rows that mention any query term beyond the first. A low-coherence bucket is
dropped **only when another bucket with at least four rows proves the query can
be echoed** (coherence ≥ 0.5). Buckets with fewer than four rows are preserved.

The source report is exposed as `decoy_buckets` (and `decoy_dropped`) on the
first search row and `/v2/search`. Example: four `web-bing` rows saying only
"Rust game" for `rust ownership borrowing` were dropped because a `web-ddg`
bucket matched "ownership/borrowing"; the healthy bucket remained.

## Cache-key query normalization

Search cache identity now collapses whitespace and case only. The upstream query
sent to providers is unchanged. Extraction keys keep URL identity exactly:

- `search("Python   asyncio")` and `search(" python asyncio ")` share a cache entry.
- `extract("https://Example.com/A")` does not share with `https://example.com/a`.

## Token estimates and boundary-aware truncation

- `estimate_tokens`: CJK one per character, Latin roughly four characters per
  token. This is an approximation, not a tokenizer.
- `smart_truncate`: cuts at paragraph, newline, sentence, clause or word
  boundary within the cap and appends ` …`; it never exceeds `max_chars`.
- Search rows expose `snippet_tokens`; fetch/document rows expose
  `tokens_estimated`.
- `_clip` and the read-plan content path use boundary-aware truncation. Raw HTML
  output keeps its exact character cap.

## Verification

- Host offline suite: **898 passed, 137 skipped, 2 deselected**.
- Full suite inside the candidate API image: **1,047 passed, 15 skipped,
  2 deselected**.
- Targeted signal/cache/search/contract/fetch tests: **125 passed**.
- Example output: [p1-example.json](p1-example.json).

Images:

- API: `dethrottled-dnb-api:1.8.0-dev-p1-20261109`
  (`sha256:a71e907d…`)
- Worker: `dethrottled-dnb:1.8.0-dev-p0-20261109`
  (`sha256:316174ac…`)

Caveats: source and page classes are deliberately heuristic; `date_source`
depends on the provider or snippet text; decoy detection needs a witness bucket;
token counts are approximate. These fields are additive and do not replace
`quality`, `warnings`, `source_partial` or `workflow.next_actions`.

Next: P2 exploratory work only after these P1 signals are stable. No release
action is authorised.
