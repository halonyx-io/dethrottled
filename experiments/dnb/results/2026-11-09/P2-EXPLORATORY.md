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

## Neural rerank — second pass, correctly configured

Added `src/dethrottled/rerank.py`, opt-in with `DETHROTTLED_RERANK=1` and
`DETHROTTLED_RERANK_MODEL=<dir>` containing `model.onnx`, `tokenizer.json` and
`config.json`.

The first pass used a tiny hand-labelled set and a fixed padding id. That was
not a fair test. The second pass fixed the setup:

- Model-specific pad id from `config.json` (BGE pad 1, GTE pad 50283), instead
  of forcing 0.
- Query/document pair encoding, 512-token truncation, model-specific input
  names (GTE/BGE/MXBAI do not take `token_type_ids`).
- Full title+text input up to 3,000 characters for reranking; BM25 baseline on
  the same full text.
- A real BEIR **SciFact** reranking set: 60 test queries, BM25 top-30 candidates,
  nDCG@10 and MRR@10. Models are compared on exactly the same candidate lists.

### Models tested

| Model | License | 60-query nDCG@10 | MRR@10 | Time |
|---|---|---:|---:|---:|
| BM25 baseline | — | **0.7635** | **0.7390** | — |
| `Xenova/bge-reranker-base` | MIT | 0.7645 | 0.7283 | 593 s |
| `Xenova/ms-marco-MiniLM-L-12-v2` | Apache-2.0 | 0.7501 | 0.7167 | 220 s |
| `Alibaba-NLP/gte-reranker-modernbert-base` | Apache-2.0 | **0.8187** | **0.7982** | 923 s |
| `jinaai/jina-reranker-v2-base-multilingual` | **CC-BY-NC-4.0** | **0.8251** | **0.8076** | 725 s |

GTE gained **+0.055 nDCG@10** and **+0.059 MRR@10** over BM25. Per query:
12 wins, 9 losses, 39 ties. A paired bootstrap over the 60 queries gave a 95%
interval for the nDCG delta of **-0.0066 to +0.1216** (MRR -0.0131 to +0.1366),
so the gain is promising but **not statistically conclusive** at 60 queries.
Jina scored slightly higher but is non-commercial; it is not a bundle candidate.
BGE and MiniLM-12 did not beat BM25 on MRR.

The official GTE usage examples use `max_length=512` and paired query/document
inputs; the corrected implementation follows that. Sentence-transformers applies
softmax/sigmoid for display, but ranking is monotonic and our evidence is based on
ordering.

**Decision:** keep reranking opt-in. GTE is the recommended optional model
(Apache-2.0, 144 MB quantized ONNX); do not make it a default until a larger
SciFact/other labelled evaluation confirms the gain. `scripts/fetch-rerank-model.sh`
fetches the pinned GTE model. The earlier small-set result is retained in
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

- Host offline suite: **912 passed, 137 skipped, 2 deselected**.
- Full suite inside the candidate API image: **1,061 passed, 15 skipped,
  2 deselected**.
- P2 targeted tests: **58 passed**.
- Documentation and agent-doc checks pass.

Images:

- API: `dethrottled-dnb-api:1.8.0-dev-p2-20261109`
  (`sha256:b4f219da…`)
- Worker: `dethrottled-dnb:1.8.0-dev-p2-20261109`
  (`sha256:b44b4b39…`)

No default ranking, provider key, proxy or cookie behavior changed. P2 outcomes
that did not earn a default stay opt-in, and no release action is authorised.
