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

## Neural rerank

Added `src/dethrottled/rerank.py`, opt-in with
`DETHROTTLED_RERANK=1` and `DETHROTTLED_RERANK_MODEL=<dir>` containing
`model.onnx` + `tokenizer.json`.

I tested the same family Hound uses: `Xenova/ms-marco-MiniLM-L-6-v2`,
`onnx/model_quantized.onnx` (23 MB) + `tokenizer.json`. No new package dependency;
it uses the existing `onnxruntime`/`tokenizers` stack and is a no-op when the
model is absent.

On an 8-case hand-labelled hard set (relevant document at index 2, lexical
decoys above it):

| Ranker | Mean MRR |
|---|---:|
| BM25 | **0.583** |
| Cross-encoder | 0.489 |

The cross-encoder was **not better** on this small set, so it remains opt-in and
is not claimed as an improvement. Hound's own benchmark and model choice are
recorded as the reference, but this stack needs a larger labelled corpus before
changing the default. The module preserves original order on model failure.

Evidence: [p2-rerank.json](p2-rerank.json), `tests/test_rerank.py`.

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
  (`sha256:6c4e6318…`)
- Worker: `dethrottled-dnb:1.8.0-dev-p2-20261109`
  (`sha256:49623a83…`)

No default ranking, provider key, proxy or cookie behavior changed. P2 outcomes
that did not earn a default stay opt-in, and no release action is authorised.
