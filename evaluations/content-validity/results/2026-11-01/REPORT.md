# Mixed-content diagnostics and recovery observations — 1 November 2026

This evaluates the 0.9.2 candidate against 0.9.1. It does not replay Bert's 24-target
test: those exact URLs and raw captures were not supplied. Current behavior is in
the [API guide](../../../../docs/API.md); the [method](../../README.md) explains limits.

## Controlled pollution detection

Eighteen fixed payloads contain a known factual sentence and labelled banner,
quotation or structured-document context. Each passed through the installed baseline
reader and the candidate with rendering disabled and identical extraction limits.

| Outcome | Baseline 0.9.1 | Candidate 0.9.2 |
|---|---:|---:|
| Labelled pollution surfaced | 0/8 | 6/8 |
| False flags on clean/quoted/structured cases | 0/10 | 0/10 |
| Known fact retained | 18/18 | 18/18 |

The candidate still misses an unfamiliar English retry banner and a French banner.
The baseline column measures surfaced mixed-content diagnostics, not whether every
existing short-interstitial check fails. These deliberately long fixtures pass that
older short-wall check. They are a regression set, not broad precision/recall evidence.

The candidate preserves exact text, supplies suspect spans and a full-text hash,
continues acquisition when allowed, and retains mixed evidence if recovery fails.
Quoted/code contexts are excluded where identifiable. Structured documents are marked
`not_assessed` for website UI pollution. Completeness and usability remain unverified.

Raw fixture outputs: [baseline](fixture-baseline.json), [candidate](fixture-candidate.json),
[label comparison](fixture-summary.json).

## Live recovery comparison

The frozen [protocol](protocol.json) contains Python sqlite3 documentation, the
Crunchbase OpenAI profile, G2 Notion reviews and Booking's home page. Two core versions,
two strategies (`auto` and renderer-first with a two-second wait/headed fallback),
and two repeats produced 32 requests. Each requested up to 120,000 characters with
cache bypass. Core data stores were separate; upstream workers/browser state were
shared. Endpoint ordering alternated, but this is not a randomized causal study.

| Version / strategy | Text extractions | Complete assertion sets | Supported assertions |
|---|---:|---:|---:|
| Baseline / auto | 4/8 | 2/8 | 6 |
| Candidate / auto | 4/8 | 2/8 | 4 |
| Baseline / rendered wait | 4/8 | 0/8 | 4 |
| Candidate / rendered wait | 4/8 | 0/8 | 4 |

All 32 HTTP requests succeeded at the API layer. That did not make all source reads
successful. Crunchbase and G2 remained unreadable under every tested condition:
**no new hostile-source win was demonstrated**. Renderer-first did not earn a default
policy change. Crunchbase reads took about 16.6–21.5 seconds; G2 took about 2.8–10.1.

Python's direct extraction matched the frozen connection-signature assertion on all
four observations. Renderer Markdown did not match that exact assertion within the
returned range; this is an assertion/representation limitation, not proof that Python
documentation became unreadable. The assertion was not changed after observation.

Booking produced real page text on all eight observations. On the first candidate
automatic read, a 659-character headed result was explicitly marked source-partial
with an HTML capture warning and an inspection action. It matched none of the three
search-interface assertions. Other observations produced longer renderer content and
matched the two date assertions, but not the destination assertion. The second
automatic repeat matched the baseline. These observations do not establish a
repeatable regression or improvement, and none satisfied the full predefined task.

[Summary](summary.json), [per-request observations](observations.jsonl) and
[manifest](manifest.json) preserve timings, negative results, hashes and excerpts.
Full live bodies remain in local evaluation storage rather than the public repository.

## Software verification and remaining work

The local non-network suite passed **604 tests**, skipped 15 and deselected two network
tests; four existing FastAPI deprecation warnings remain. The 25 new cases cover
pollution signals, quoted text, structured content, cache/clipping/retained focus,
render restrictions, failed recovery, task scoring and research partial evidence.
See [regression output](regression.log). Documentation/reference checks and lint pass.

Priority follow-ups are a larger independently labelled mixed-content corpus,
multilingual signals, and task assertions resilient to representation differences
without losing exact provenance. Recovery experiments need additional verified reads
before changing defaults. This run improves diagnostics and agent handling; it does
not claim general Cloudflare/PerimeterX defeat or paid-provider superiority.
