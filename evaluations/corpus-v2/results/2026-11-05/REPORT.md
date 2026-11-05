# Corpus v2: measured candidate report — 5 November 2026

Dethrottled now separates complete public-text admission, canonical retention, full bounded lexical indexing and representative semantic indexing. The candidate recovers labelled evidence beyond the old 4,000-character prefix, shares public retained handles across agents, and keeps v1 available for rollback. It is an **unreleased local feature candidate**, not a production deployment or a published PyPI version.

The reported semantic false positive was addressed in code rather than merely excluded from a headline. Conservative support rejects it; broad retrieval preserves the original above-floor candidates with explicit warnings. This improves precision at a real multilingual recall cost.

## What was implemented

- Normalized schema 2: sources, offset-preserving passages, per-model/revision vectors, FTS5 and durable jobs. Passage text is stored once for both models; eligible existing document handles are reused.
- Full-source examination with separate 8M-character admission, 2M-character lexical, and 32/96-passage semantic budgets. Long sources receive distributed coverage; omissions and covered ranges are explicit. Script-aware admission preserves useful unspaced text. Real tokenizer overflow checks prevent silent embedding truncation.
- One background indexer, query priority between inference batches, leases/retries, stale-version protection, atomic promotion, unchanged-vector reuse and crash recovery. No new default service or mandatory dependency.
- Combined 256 MiB vector-matrix budget with bounded construction and streaming fallback. Whole-source pruning coordinates FTS and both models. Maintenance batches are bounded and resumable; the 512 MiB SQLite target is soft.
- **90-day corpus retention**, independent of unchanged six-hour search and 21-day extraction caches. Existing retained-document expiry/eviction remains separate; expired handles are reported.
- Shared configured retrieval for explicit ordinary-search corpus candidates; live-web ordering and corpus opt-in remain unchanged. HTTP/MCP expose lexical, semantic, hybrid, domain filtering and standard/broad support.
- Explicit public eligibility, private/authenticated/interactive exclusion, credential-URL rejection and a public-handle registry. Local backfill is bounded, restartable and privacy-preserving. V1 is neither rewritten in place nor silently promoted to public.

## Evidence quality

Both architectures produced the same labelled retrieval outcomes. Grades require the expected URL **and the full answer fact**, not domain matching or a number appearing somewhere. Each query was repeated three times. The documents are synthetic technical fixtures; this is a corpus-coverage evaluation, not a benchmark of general web search or arbitrary answerability.

| Dataset | Positive / negative cases | V1 Recall@5 | V2 standard Recall@5 | V1 / V2 MRR@10 | Negative cases with hits: V1 / V2 |
| --- | --- | --- | --- | --- | --- |
| development | 27 / 10 | 0.519 | 0.963 | 0.380 / 0.926 | 0 / 0 |
| heldout | 12 / 4 | 0.000 | 1.000 | 0.000 / 0.889 | 0 / 0 |

The 16-question held-out set exposed E5 returning laboratory boilerplate for a question about Hawking radiation, at cosine **0.773348**, just above its unchanged 0.77 floor. Before the support change, one of four negative questions returned hits; afterward, zero of four did, while all 12 labelled positives remained in the top five. That set has now been used for development and is a regression set, not an untouched final holdout. Original failing results are retained.

The development set includes 18 front/middle/tail identifier tasks, six English paraphrases and three multilingual positives. Gains mostly demonstrate deeper evidence retrieval, not a newly superior embedding model. One water-purification paraphrase recovered by v1 is still missed semantically in v2; its identifier-labelled facts remain lexically available. All promotions and losses are in [per-query.csv](per-query.csv).

## Why E5 stays, and what the support policies cost

The corrected 46-case multilingual development challenge has 22 positive cases and 24 unanswerable questions. The following comparison reuses the **identical retained corpus**, pinned weights, questions and support policy; it does not compare a raw model against a filtered model. Both machines reproduce the same accuracy outcomes.

| Models / policy | Answers in top five / 22 | Negative questions with candidates / 24 | Warm median: x86_64 / ARM64 |
| --- | --- | --- | --- |
| MiniLM, broad | 14/22 | 6/24 | 2.00 / 6.26 ms |
| E5, broad | 21/22 | 5/24 | 4.41 / 11.88 ms |
| Both, broad | 21/22 | 10/24 | 6.90 / 22.40 ms |
| Both, standard | 14/22 | 0/24 | 6.87 / 22.59 ms |

E5 contributes additional cross-language candidate recovery. It remains optional and Compose continues to enable it; no model weights, dimensions, pooling, prefixes or relevance floors changed. Combining unfiltered models also combines their false positives.

Standard support requires model agreement on the same source or meaningful literal query terms. It does **not** require both models to pick the same passage. An English MiniLM vote does not corroborate predominantly non-Latin-script queries. Broad support keeps single-model candidates available, including useful translations, with `support_status=unconfirmed` and warnings where checks fail. Every result still has `answer_support=unverified`. Two-model agreement is not proof of an answer.

On a further **20-query validation set** frozen after policy development, using the same known documents with new questions: standard recovered **6/8** positives with **0/12** negative questions returning hits; broad recovered **8/8** with **6/12** negatives returning candidates. This is evidence for an explicit coverage/precision choice, not a universal zero-false-positive claim. Questions within and across sets are correlated.

## Resources and latency

Tested targets: an ARM64 edge device with four Cortex-A55/four Cortex-A78 cores and 11.29 GiB OS-visible RAM, and an x86_64 mini PC with Ryzen 7 5800U, eight cores/16 threads and 30.76 GiB RAM. These are tested hosts, not minimum requirements. Existing host services remained running. Timings are conditional observations rather than isolated hardware rankings.

The matched-count microbenchmark holds **50,000 vectors per model**, two models, 384 float32 dimensions. It excludes model/tokenizer inference and memory. Each variant runs in a fresh process; one cold matrix load and five warm queries are retained.

| Device / variant | Corpus SQLite after checkpoint | Peak RSS, no embedding models | Warm query median |
| --- | --- | --- | --- |
| x86_64 mini PC, v1 | 411.64 MiB | 431.73 MiB | 11.32 ms |
| x86_64 mini PC, v2 | 247.84 MiB | 229.79 MiB | 51.80 ms |
| ARM64 edge, v1 | 411.64 MiB | 397.21 MiB | 28.47 ms |
| ARM64 edge, v2 | 247.84 MiB | 195.09 MiB | 108.35 ms |

The normalized corpus is about **39.8% smaller at matched vector counts**, and measured matrix-scan process peaks fall substantially. Warm scans are slower: v2 does freshness/source-diversity filtering and additional record/support checks. There is no basis to call the whole feature faster. Five warm samples and active host workloads do not establish stable tail latency.

The real nine-document development workload stores **195 passages/model in v2 versus 27/model in v1**, because much more text is indexed. V2 retains/indexes 204,570 source characters lexically and embeds selected passages covering 151,678 characters. Its actual corpus database plus active WAL is larger than v1 on that workload. The matched-count storage saving must not be presented as a smaller database for every fixed document collection.

With real models loaded, development peak RSS was approximately **1.00 GiB on both versions/devices**. The 256 MiB matrix budget excludes model weights, ONNX/tokenizer workspaces, Python overhead and SQLite caches. Real index preparation is background work, not eliminated work. Durable admission median was 7.19 ms on x86_64 and 2.64 ms on ARM64 in the development capture; retention time is recorded separately. Older v1 admission included synchronous embedding, so these admission timings are not an indexing-throughput comparison.

## Installation and reliability gates

The final private wheel is `1.5.0.dev2`; its hash and exact runtime-source hashes are in [build.json](build.json). The build record also identifies one post-test line wrap verified to have an identical Python AST. Only validation metadata was versioned this way; the feature branch remains unreleased. Retrieval captures were made before the final bounded-maintenance/diagnostic refinements, then the final wheel reproduced all recorded answer ranks and candidate counts in **555 trials per architecture**.

| Gate | x86_64 mini PC | ARM64 edge |
| --- | --- | --- |
| Native built-wheel suite, Python 3.12.16 | 764 passed; 15 skipped; 2 network cases excluded | 764 passed; 15 skipped; 2 network cases excluded |
| Five-worker packaged stack, fresh project/volumes | Ready | Ready |
| Local migration, public handle reuse, actual v1 rollback and v2 restore | Passed | Passed |
| SIGKILL during indexing, prior version retained, restart promotion | Passed | Passed |
| SIGTERM during native inference, no failed-attempt consumption | Passed | Passed |
| Eight clients, 48 idle + 48 indexing-phase reads, required fact retained | 96/96 | 96/96 |
| Final-wheel recorded-quality replay | 555/555 matched | 555/555 matched |

Crash recovery explicitly **simulates expiry of the 120-second lease** instead of claiming a full-duration timing test. SIGTERM exits use the normal signal exit code; assertions verify retained/pending work and absence of native crashes. Fresh core-only Python installation also passed lexical retention/retrieval without ONNX/tokenizer dependencies or model downloads; missing semantic support produces explicit empty-result diagnostics. Native inference uses the existing model assets.

Packaged default-stack startup measured **34.38 seconds on x86_64 and 28.64 seconds on ARM64**, with cached Docker images/model build layers. These are not cold internet-install times. Full worker builds/readiness were exercised from the wheel context outside a source checkout. The final concurrency run measured idle/indexing p95 of **119.96/289.08 ms** on x86_64 and **514.95/720.62 ms** on ARM64, with observed host load retained. This workload proves fact preservation under contention, not a general throughput guarantee.

## Rollout and remaining limits

- Keep this as a candidate until the next release decision. Production, GitHub main, releases and PyPI were not changed by this work. The existing production APIs still report 1.4.3 on x86_64 and 1.4.1 on ARM64; those deployments are outside this candidate validation. Temporary validation services are stopped after evidence capture; their data volumes are preserved.
- Backfill only eligible retained local public documents. Unknown legacy visibility is skipped; missing/expired full documents cannot be reconstructed from v1 prefix vectors. `--trust-legacy-public` is an explicit operator assertion, never a bypass for known private/authenticated flags.
- Set `DETHROTTLED_CORPUS_SCHEMA=1` and recreate the API to roll back. V1 remains intact. New v2 admissions are not copied backward automatically.
- Semantic sampling remains incomplete; broad retrieval does not recover every missing semantic fact. Use coverage/omission metadata, lexical queries and retained-document reads. Bounded lexical windows also omit parts of extremely large sources.
- Standard support deliberately loses some genuine one-model paraphrases/translations. Broad results need inspection and can contain irrelevant candidates. Neither policy performs entailment checking or establishes truth.
- Database/embedding targets can be exceeded while bounded pruning catches up; WAL/free pages and independent full-document storage have separate costs. The matrix budget is not an overall API memory cap.
- One inference worker cannot preempt a model call already in progress. Scheduling priority is between batches within an API process; it is not global fairness across independent API processes.
- This run does not establish new live-web, anti-bot, OCR accuracy or universal multilingual-model quality. Optional speech/layout profiles were not re-benchmarked for this corpus change.

## Reproduce and audit

See [the harness instructions](../../README.md), [issue resolutions](RESOLUTIONS.md), raw JSON, [per-query.csv](per-query.csv), [SHA256SUMS](SHA256SUMS) and the offline verifier. No production URLs, document bodies, searches, embeddings or database backup are included. The aggregate-only v1 snapshot records the observed starting size.

Model background: [MiniLM model card](https://huggingface.co/sentence-transformers/all-MiniLM-L6-v2) and [multilingual E5 model card](https://huggingface.co/intfloat/multilingual-e5-small). E5 documents its compressed cosine range; raw score magnitude is not a calibrated probability that a passage answers a question.
