# S0-S1 provenance and contract check

2026-11-09. Candidate held. No runtime code changed in this stage.

## S0 provenance

| Item | Value |
|---|---|
| Working commit | `1fdd164` (README documentation commit) |
| Frozen candidate source | `735d420` / tag `phase5-candidate-20261109` |
| Source diff from frozen candidate | none (`git diff 735d420 -- src` empty) |
| Reference image | `dethrottled:1.7.1` / `dethrottled:local` `sha256:891c3a17…` |
| Candidate worker | `dethrottled-dnb:1.8.0-candidate-20261109` `sha256:c6633da3…` |
| Candidate API | `dethrottled-dnb-api:1.8.0-candidate-20261109` `sha256:bb859007…` |
| Reference browser | `dethrottled-dnb-browser:reference` `sha256:c1726a32…` |
| Host | Debian, kernel 6.12.111, x86_64 |
| Docker server | 29.8.2 |
| Python | 3.13.5 |
| Production | 1.7.1 `dethrottled:local`, running healthy |
| Current test-bed API | `dethrottled-dnb-api:1.8.0-dev-p1-20261109` `sha256:a71e907d…` |
| Current test-bed worker | `dethrottled-dnb:1.8.0-dev-p0-20261109` `sha256:316174ac…` |

## S1 REST contract

The reference and candidate APIs were started from their images with the same
environment and no workers. `/openapi.json` was captured from both.

- 24 paths on both sides; no path or method added or removed.
- One schema addition:
  `SearchFetchBody.response_format` = `"detailed" | "concise"`, default
  `"detailed"`.
- Tested behavior: the candidate accepts the field; reference 1.7.1 rejects it
  with `extra_forbidden` and HTTP 422. The MCP `search_and_fetch` tool already
  sends this field, so the candidate is internally consistent and 1.7.1 is the
  side that lacks the additive field.

## Fixes made

1. `docs/HTTP-REFERENCE.md` and `docs/MCP-REFERENCE.md` were stale: neither
   listed `response_format` for `search_and_fetch`/`SearchFetchBody`.
   Regenerated with `scripts/docs_reference.py` (one line added to each).
2. `PHASE-6-PREP.md` linked five evidence files without their `PHASE-6-PREP/`
   directory; `scripts/check_docs.py` reported them missing. Links corrected.

Verification after the fixes:

- `scripts/docs_reference.py --check`: references match source.
- `scripts/check_docs.py`: 103 pages, 743 links, 55 examples, 10 requests, no
  broken references.
- `scripts/check_agent_docs.py`: 24 routes, 20 MCP tools, 27 browser actions, no
  errors.

Evidence: [s1-openapi-reference.json](s1-openapi-reference.json),
[s1-openapi-candidate.json](s1-openapi-candidate.json).

## External project review

Two MIT projects were reviewed read-only for the S2/S3 backlog:

| Project | Version / commit | Scope |
|---|---|---|
| `dondai1234/master-fetch` (Hound) | 12.4.1, commit `86d1b132…` | HTTP-first fetch, Patchright stealth browser, cache discipline, PDF CID OCR, focus extraction, search consensus, token-optimized tools |
| `sweetcornna/free-search-mcp` | commit `2c7fee99…` | Multi-engine RRF, FTS5 cache, date provenance, decoy-bucket detection, output shaping, freshness TTLs |

The comparison and prioritisation are in
[SIMILAR-PROJECTS-IDEAS.md](SIMILAR-PROJECTS-IDEAS.md). The S0-S10 plan now
carries the ordered backlog: **bugs/efficiency (P0) first**, then S2/S3
correctness, then exploratory P2 work.

P0 is now recorded complete in [P0-BUGS-EFFICIENCY.md](P0-BUGS-EFFICIENCY.md):
cache ceiling/expiry, browser idle close and pressure, CID PDF OCR, gate-page
warnings, the Reddit test (not adopted), and the optional core MCP profile.
P1 is recorded in [P1-AGENT-SIGNALS.md](P1-AGENT-SIGNALS.md): date/source/page
signals, fetch relevance, decoy buckets, normalized cache identity, token
estimates and boundary-aware truncation. Next is the P2 exploratory queue after
the P1 fields are evaluated against the fixed corpus.
