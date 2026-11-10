# P2 exploratory results

2026-11-09. Candidate held. These are opt-in experiments; no release, version
bump, publish or deployment. Production remains 1.7.1.

## Search consensus and intent fan-out

Implemented `src/dethrottled/consensus.py` and an opt-in
`DETHROTTLED_SEARCH_FANOUT=1` path in `_ranked`.

- Conservative intent classes: comparison, howto, research, code, reference,
  news, factual, general.
- At most one added query variant; queries under two words or 15+ words do not
  expand.
- Variants are searched with the same filters and merged by canonical URL.
- Rows expose `engines_consensus` and `consensus_score`; the first row and
  `/v2/search` expose `fanout_queries`.
- Default remains one query. Fan-out spends extra upstream requests and is not
  enabled by default.

Example: `rust vs go performance` produced the original plus
`rust vs go performance comparison benchmark`; the URL found by both variants
had consensus 2.5, the single-source URLs 1.0.

Evidence: [p2-fanout.json](p2-fanout.json), `tests/test_consensus.py`,
`tests/test_endpoints.py`.

## Neural rerank — correctly configured and tuned

Added `src/dethrottled/rerank.py`, opt-in with `DETHROTTLED_RERANK=1` and
`DETHROTTLED_RERANK_MODEL=<dir>` containing `model.onnx`, `tokenizer.json` and
`config.json`.

The earlier 8-case test was not a fair cross-encoder test. This pass fixed the
setup and then tuned it:

- Model-specific pad id from `config.json` (BGE pad 1, GTE pad 50283).
- Correct query/document pair encoding, paired special tokens and input names.
- Tokenizer truncation length configurable and clamped to the model maximum.
- Title + body up to 3,000 characters; BM25 saw the same full text.
- Real BEIR **SciFact** data: 100 test queries, BM25 top-30 candidates, nDCG@10
  and MRR@10 with identical candidate lists.
- CPU threading tested (8 threads reduced GTE time from 923 s to ~940 s for the
  100-query run versus the slower 60-query setup).

### Model comparison — 60 queries

| Model | License | nDCG@10 | MRR@10 |
|---|---|---:|---:|
| BM25 baseline | — | 0.7635 | 0.7390 |
| MiniLM-L12 | Apache-2.0 | 0.7501 | 0.7167 |
| BGE base | MIT | 0.7645 | 0.7283 |
| GTE ModernBERT (quantized) | Apache-2.0 | **0.8187** | **0.7982** |
| Jina v2 (512 tokens) | **CC-BY-NC-4.0** | **0.8251** | **0.8076** |

GTE gained +5.5 nDCG and +5.9 MRR over BM25. Per-query at 60: 12 wins, 9 losses,
39 ties. The paired bootstrap 95% interval still crossed zero
(nDCG -0.0066 to +0.1216), so it was not statistically conclusive.

### GTE settings sweep — 30 queries

| Setting | nDCG@10 | MRR@10 |
|---|---:|---:|
| BM25 baseline | 0.7454 | 0.7158 |
| 256 tokens, 3,000 chars, depth 30 | 0.7443 | 0.7367 |
| **512 tokens, 3,000 chars, depth 30** | **0.8189** | **0.8000** |
| 768 tokens, 3,000 chars, depth 30 | 0.7954 | 0.7844 |
| 1,024 tokens, 3,000 chars, depth 30 | 0.7954 | 0.7844 |
| 1,536 tokens, 3,000 chars, depth 30 | 0.7954 | 0.7844 |
| 512 tokens, 600 chars, depth 30 | 0.7643 | 0.7493 |
| 512 tokens, 1,500 chars, depth 30 | 0.7799 | 0.7603 |
| 512 tokens, title omitted, depth 30 | 0.7915 | 0.7708 |
| 512 tokens, depth 10 | 0.7979 | 0.7992 |
| 512 tokens, depth 20 | 0.7936 | 0.7837 |
| 512 tokens, depth 50 | 0.7804 | 0.7783 |
| Full-precision GTE, 512 tokens, depth 30 | 0.8227 | 0.8167 |

The best practical configuration is **quantized GTE, 512 tokens, title+text,
3,000 characters, depth 30, 8 threads**. Longer token limits did not help
SciFact; 256 hurt; 600/1,500 characters were too short; title text helped;
depth 30 beat 10/20/50. The unquantized model was only +0.004 nDCG for 4x the
disk and ~1.5x the runtime, so the quantized model is recommended.

### Final GTE run — 100 queries

| Metric | BM25 | GTE |
|---|---:|---:|
| nDCG@10 | 0.7222 | **0.7722** |
| MRR@10 | 0.6913 | **0.7455** |

Per query: 22 wins, 15 losses, 63 ties. This is a **+0.050 nDCG / +0.054 MRR**
gain over a larger query sample. It is a real positive signal, but not yet enough
to make reranking a default; the query-level wins are not overwhelming and a
larger multi-dataset run is the right next step.

### What 1.7.1 does on the same candidate pools

1.7.1 has no cross-encoder. On the same 100-query SciFact candidate pools:

| Ranking policy | nDCG@10 | MRR@10 |
|---|---:|---:|
| 1.7.1 default source order (pool order) | 0.7222 | 0.6913 |
| 1.7.1 optional BM25 ranker on the same 30 candidates | 0.6470 | 0.6108 |
| GTE, tuned settings above | **0.7722** | **0.7455** |

The 1.7.1 BM25 number is its ranker applied to an already-retrieved candidate
pool, not a full web search. The useful comparison is that GTE adds about
**+0.05 nDCG / +0.054 MRR** over the source-order baseline, and about
**+0.125 nDCG / +0.135 MRR** over the optional 1.7.1 BM25 ranker on the same pool.

### Settings that did not help

- Blend with normalized BM25: 0.50 blend 0.7971 nDCG; 0.75 blend 0.7954;
  pure GTE 0.8189 on the 30-query sweep.
- Repeating the title twice: 0.7661.
- Prefixing the query with `query: `: 0.7413.
- Longer token limits, shorter text windows, text-only input, and depth 10/20/50
  all scored below the chosen 512-token/title+text/depth-30 setting.


**Decision:** keep reranking opt-in. GTE is the recommended optional model
(Apache-2.0, 144 MB quantized ONNX). `scripts/fetch-rerank-model.sh` downloads
the pinned GTE revision. Jina scored slightly higher but is CC-BY-NC and is not a
bundle candidate. The earlier small-set result is retained in
`p2-rerank-small.json` so the failed first test is not hidden.

Evidence: [p2-rerank.json](p2-rerank.json),
[p2-rerank-small.json](p2-rerank-small.json),
`tests/test_rerank.py`.

## Semantic query cache

Added `src/dethrottled/semantic_cache.py`, off by default and enabled with
`DETHROTTLED_SEMANTIC_CACHE=1` (or a path). It uses the existing MiniLM
embeddings, a separate SQLite file, and stores only the result menu for one
filter context. It never changes the upstream query or returns corpus passages.

Measured on 8 paraphrases and 8 unrelated pairs with MiniLM:

| Signal | Value |
|---|---:|
| Same-topic similarity mean | 0.724 |
| Same-topic max | 0.934 |
| Unrelated max | 0.098 |
| Threshold | 0.55 |
| Paraphrase recall at threshold | 7/8 (0.875) |
| False hits at threshold | 0/8 |

The default threshold was lowered from 0.92 (the cross-project starting point)
to **0.55** for this model based on that separation, with the filter context in
the key. Tests cover paraphrase hits, unrelated misses, context isolation, TTL
and the off-by-default path; a server test confirms a hit skips search and is
reported as `semantic_cache`.

Risk remains: an aggressive threshold can answer a nearby but different
question. This is why the feature is opt-in, context-scoped and time-bounded.

Evidence: [p2-semantic.json](p2-semantic.json),
`tests/test_semantic_cache.py`, `tests/test_endpoints.py`.

## Persistent browser profile / stealth

Added opt-in `DETHROTTLED_SEARCH_PROFILE` (`1` for `/state/search-profile.json`
or an explicit path). The public search context saves and reloads Playwright
`storage_state` (cookies/localStorage) after each search; a malformed profile
falls back to a clean context.

Verified against the worker image:

- `/search` returned 200, engine `ddg-lite`, 3 results.
- A profile file was written.
- After a worker restart, the same search returned 200 and 3 results.
- The DDG Lite run set no cookies, so the file was `{"cookies": [], "origins": []}`;
  that is an observation about this engine, not a claim of solved anti-bot.

Limits: this is storage state for public search only, not a full Chromium disk
cache; drive checkpoints and owner isolation remain unchanged. It is off by
default because a shared cookie jar is a privacy choice.

Evidence: [p2-profile.json](p2-profile.json).

## Proxy and BYOK key rotation

`src/dethrottled/providers.py` now supports:

- `DETHROTTLED_<PROVIDER>_API_KEYS` (comma-separated) or the legacy single key.
- Per-key cooldown: 401/403 for 300s, 429 for 60s; rotate to the next key.
- `DETHROTTLED_SEARCH_PROXIES` / `DETHROTTLED_SEARCH_PROXY` round-robin per
  search call, with proxy cooldown on transport failure.
- Diagnostics expose `key_attempts`, `key_index`, `proxy_rotated`; credentials
  and proxy URLs are never logged.

Tests cover a 429-to-next-key success, all-keys-exhausted reporting, and proxy
round-robin. The feature is optional and only affects explicitly configured
metered providers.

Evidence: `tests/test_provider_rotation.py`.

## Verification

- Host offline suite: **913 passed, 137 skipped, 2 deselected**.
- Full suite inside the candidate API image: **1,061 passed, 15 skipped,
  2 deselected**.
- P2 targeted tests: **59 passed**.
- Documentation and agent-doc checks pass.

Images:

- API: `dethrottled-dnb-api:1.8.0-dev-p2-20261109`
  (`sha256:7c59f476…`)
- Worker: `dethrottled-dnb:1.8.0-dev-p2-20261109`
  (`sha256:3ad1a408…`)

No default ranking, provider key, proxy or cookie behavior changed. P2 outcomes
that did not earn a default stay opt-in, and no release action is authorised.
