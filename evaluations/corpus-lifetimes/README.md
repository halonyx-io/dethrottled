# Corpus routes and independent lifetimes — 5 November 2026

Unreleased diagnostic improvements based on 1.5.2 and the existing local
candidate. No publication, deployment, lifetime change or new background task.

## Findings

The running API returned **404** at `/v2/corpus/stats`, and **200**, `ok=true`,
schema 2 at `/corpus/stats`. The former was a guessed route, not a moved endpoint.
MCP `corpus_stats` and the public REST allowlist already use `/corpus/stats`.
Corpus v2 describes its storage schema, not an HTTP namespace.

No data-loss defect was reproduced in the four-clock design. Existing hits
already report `corpus_expires_at` and `document_available`; stats distinguish
indexing coverage snapshots from current document availability. Three new
controlled-clock/eviction regressions passed before any runtime change.

The small runtime change addresses discoverability and diagnosis:

- Capabilities now advertise `corpus.endpoints` with the two canonical URLs.
- Schema-2 corpus stats add `lifetimes`, using cache defaults and actual document
  TTL/size and corpus retention settings. Lookup-only expiry and possible document
  capacity eviction are explicit. Existing fields and schema-1 shape survive.
- Agent instructions and guides explain the routes and independent write/admission
  clocks. No alias was added merely to validate a guessed URL.

| Time after initial writes/admission | Search cache | Extraction cache | Document handle | Corpus passage |
|---|---|---|---|---|
| Initially | Available | Available | Available | Available |
| Six hours + one second | Expired | Available | Available | Available |
| Seven days + one second | Expired | Available | Unavailable | Available |
| 21 days + one second | Expired | Expired | Unavailable | Available |
| 90 days + one second | Expired | Expired | Unavailable | Expired |

The same test verifies that repeated lookups do not renew corpus expiry and
that pruning expired public-document registrations does not remove valid
passages. Another test renews an unchanged admission at day 89 without a new
embedding job: the passage and newly retained document remain available on day
91. A third forces document-store capacity eviction before TTL and confirms
passages remain readable with `document_available=false` and the unavailable
count incremented.

A fetch can write a document and re-admit eligible evidence even when its
extraction came from cache. That renews those write/admission clocks; it is not
proof of fresh upstream acquisition. Acquisition timestamps remain separate.
Document availability alone does not identify whether expiry or eviction caused
a missing handle. Query filters, indexing state, corpus capacity and model
availability can also explain absent results; an empty query is not proof of
physical deletion. Existing policies are preserved, not unified to hide those
states.

## Tests and evidence

- **81 relevant tests passed on each native architecture**, x86_64 and ARM64:
  contract, cache, Corpus v2 and operations suites.
- **Three final API diagnostics regressions passed on each architecture** after
  making the lookup-only semantics explicit: canonical route discovery, actual
  overridden settings and unchanged legacy schema-1 stats shape.
- The new diagnostics assertions initially failed because those additive fields
  were absent. This establishes the observability gap, not an expiry defect.
- Documentation contracts, agent coverage and lint checks passed.

[Validation records](results/validation.json) retain exact summaries, source
hashes and the bounded live route observations. No upstream search/load test was
needed. Controlled tests require no network or real multi-day wait.

```sh
DETHROTTLED_ADBLOCK=0 PYTHONPATH=src pytest -q tests/test_contract.py tests/test_corpus_v2.py tests/test_corpus_v2_operations.py tests/test_cache.py
```
