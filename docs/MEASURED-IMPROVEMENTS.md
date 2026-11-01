# Measured improvements — 0.8.0

> Historical evaluation: the measurements and deployment statements below describe
> the recorded release, not current installation instructions. Use the
> [current guides](README.md) and [evidence index](EVIDENCE.md) for context.

This release prioritizes source coverage and recoverable work over lower latency.
Baseline is commit `5bd93c4` / deployed 0.7.0. The changes use existing agent entry
points; clients do not need to learn another extraction endpoint. Normal `fetch`
automatically routes the two measured format signatures and scanned layout;
`corpus_search` uses the dual index when enabled. MCP startup instructions and
capabilities describe this behavior; explicit native/OCR controls remain available.

| Area | Baseline | Candidate | What this establishes |
|---|---|---|---|
| Renderer admission, 48 controlled successful upstream responses | 40/48 admitted | 48/48 admitted | Removes a local hourly ceiling, not a claim about upstream success |
| Public-format fixtures: two MSG, two XLSB | MSG errors; XLSB archive XML rather than worksheet text | Four readable bodies with expected content | Specific coverage expansion for these fixtures |
| Raster PDF table, four known numeric cells | Words and numbers recovered, zero structured tables | One table, all four numeric cells preserved | Added table structure on one clean synthetic scan |
| Cancelled speech computation | Gate released while thread continued | Child killed before gate release; next work succeeds | Recoverable cancellation/deadline/disconnect in supervised process tests |
| Corpus relevance, 20 calibration queries | 10/20 correct returned first hits at existing floor | 20/20 | Fixture calibration gain, not held-out accuracy |
| Corpus relevance, 11 distinct fresh queries | 2/11 correct returned first hits | 10/11 | Small held-out multilingual gain |
| Known-source recovery with 10,188 retained distractor passages, 11 fresh queries | 1/11 | 7/11 | Stronger local-context check; alternative retained sources were not relabelled |
| Four fresh unrelated-topic queries | 4/4 empty | 4/4 empty | No observed negative-case regression on these four queries |

Corpus tests use eight fixed English passages and English, Chinese, Malay and
French questions. MiniLM raw ranking was 14/20; its existing 0.22 relevance floor
reduced correct returned hits to 10/20. E5's separate 0.77 floor was chosen on the
calibration examples and frozen before the fresh queries. One of twelve proposed
holdout queries duplicated calibration exactly; it is explicitly excluded from
the 11-query holdout count. One fresh query still fails. This is not an external
benchmark or a representative web-scale evaluation. A follow-up in a private copy
of the complete retained corpus adds 10,188 distractor passages. Known-source
first-hit recovery is 9/20 to 14/20 on calibration and 1/11 to 7/11 on fresh
queries. Results omit private URLs and text; the exact distractor snapshot is
not published, so that local check cannot be fully reproduced from this bundle
alone. A hit on a different retained source is counted as a controlled-source
miss, without asserting that its text cannot answer the question. Negative
queries are not scored there because their absence from the broader corpus is
unknown. Rank fusion preserves separate
cosine scales. A missing E5 model falls back to English hits with a warning.

The table fixture's known cells are ALPHA: 17 / 7341 and BETA: 291 / 420, columns
2024 / 2025, units tonnes. Native OCR already recovered the numbers; the gain is
structured layout, not newly discovered numeric accuracy. Inferred structure and
OCR require source-pixel verification for critical values. Native vector tables
continue to use existing native extraction. Automatic layout escalation is bounded
to at most ten selected pages; agents can request further page ranges.

Speech produced identical timestamped text on the 11-second JFK fixture. One run
increased from 2326 ms to 5182 ms because weights load in a fresh process. This is
a documented reliability tradeoff, not a speed improvement. Tests exercise actual
child processes with controlled cancellation, disconnect and deadline faults;
they do not claim that every production fault has been reproduced.

A rollout caught a second lifecycle bug: interpreter shutdown during threaded E5
backfill caused a native fault, and writing a core dump delayed replacement by
about two minutes. A controlled restart after the first 44 migrated passages
reproduced exit code 139 in the threaded version. The revised supervised-child
version exited 0 in 1123 ms under the same condition (the threaded probe took
1758 ms with core dumps disabled). Before model inference began, both versions
exited 0; both warmup results are retained. Backfill now runs in a separate child,
shutdown kills/reaps it, and missing URLs resume on restart. Native child failure
is visible in status and cannot terminate the API. API/heavy-worker containers
inherit a zero core-dump limit. This fixes an observed rollout failure rather
than assuming passing unit tests alone proves dependable shutdown.

## Candidates and scope

Kreuzberg 4.10.4, a Rust-backed alternative, read three of the four format fixtures
but panicked on `testEXCEL.xlsb` (`no entry found for key` in its XLSB parser).
It was rejected. Apache Tika 3.3.3 read all four, so only its bytes-only worker is
shipped. Routing requires the matching filename extension and file signature;
extensionless download endpoints are not established by these tests. Rust has no demonstrated advantage worth a Dethrottled rewrite here.
Tika's 3.x line remains supported according to [Apache Tika](https://tika.apache.org/).
The jar is pinned and SHA-512 checked at build time. The native parsers, working
DDG browser path, Crawl4AI version, SearXNG configuration and paid search defaults
are preserved.

Multilingual E5 is pinned to revision
`614241f622f53c4eeff9890bdc4f31cfecc418b3`. Prefixing, pooling and normalization
follow the [publisher's model card](https://huggingface.co/intfloat/multilingual-e5-small).
Additional weights are approximately 470 MB plus tokenizer; index and runtime
memory also grow. Corpus evidence does not prove that current web search improves.

Worker readiness distinguishes absent weights, inaccessible services and ready
workers. The old speech/layout workers returned 404 for `/ready` and `/metrics`;
the new workers expose both. The API's status includes bounded cached probes,
job counts and model-index backfill status. Liveness is still a separate check.
Targeted cache compatibility checks refresh old XLSB archive listings and flat
scan OCR when the improved reader is available, preserving ordinary HTML hits.
Cost metadata now reports cumulative usage as unavailable rather than a fake zero.
No new paid provider is enabled.

## Reproduction and records

`tests/test_measured_workers.py` covers fair rotation, concurrency bounds, queue
expiry, real child cancellation/deadline/disconnect recovery, input limits,
separate model indexes, resumable backfill, signature routing, explicit OCR controls
fallback to English when E5 is unavailable, and supervised backfill completion,
interruption and native child failure. Run the full non-network suite
and lint with `pytest -q -m "not network"` and `ruff check .`.

Raw outputs, fixture hashes, evaluation scripts, the rejected Rust result and
public deployment checks are retained in `docs/benchmarks/2026-11-01-measured/`.
Public-format fixtures originate from Apache Tika's Apache-2.0 test resources;
the speech fixture originates from whisper.cpp's samples. Their URLs and SHA-256
hashes are recorded in `fixture-manifest.json`. Controlled tests isolate local
admission and lifecycle behavior from variable upstream services. They are not
measurements of internet-wide coverage. Production checks and exact test counts
are recorded in the release evidence summary.

## Final release checks

- Full non-network suite: **544 passed, 15 skipped, 2 deselected**; lint passed.
  Actual model experiments are recorded separately from dependency-skipped tests.
- Public MCP exposes 20 tools. Fresh SDK 1.28.1 sessions completed fetch, inspect
  and retained-read workflows for MSG/XLSB; instruction hashes match capabilities.
- Public REST parses both formats without requiring new client endpoints, and
  retained evidence hashes match. Existing discovery, research, speech, site
  coverage, browser checkpoint/cleanup and MCP-to-REST continuity checks pass.
- All five configured worker probes are ready. The original MiniLM index remains;
  multilingual backfill completed at **10,188 passages / 3,604 pages** in each index.
- Live core package, worker source files and MCP adapter match the checked source.
  The token registry is unchanged. Protected config/database backups and rollback
  image tags remain on the host; temporary test containers were removed.

The observed rollout interruption is disclosed above. The final release includes
its supervised-backfill correction and was rechecked publicly after deployment.
This release does not establish internet-wide superiority, arbitrary-file
readability, perfect OCR, or universal multilingual precision.
