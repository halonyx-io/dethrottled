# Corpus v2: issues found and resolutions

These are material failures and rejected approaches, rather than just the final
passing totals. Original working logs and private test databases remain outside
the repository. The published JSON contains synthetic evidence only.

| Finding | Resolution and retained evidence |
| --- | --- |
| Held-out Hawking-radiation question returned laboratory boilerplate at E5 cosine 0.773348 | Added source/model corroboration or meaningful literal anchors for standard support. Retained the failing `*-v2-before-support-heldout.json.gz`; final held-out files show no returned hits and unchanged labelled-answer recovery. Floors remain 0.22/0.77. |
| Raising a single threshold would also discard useful multilingual matches | Kept the existing floors. Added explicit broad retrieval with per-row support status and warnings; HTTP, MCP and agent instructions explain expansion. Model-comparison files measure each model under each policy. |
| Requiring both models on the exact same passage loses valid answers | Corroboration is source-level; unit tests cover different passages from the same source and reject agreement across different sources. |
| Title-embedding corroboration did not reject the Hawking match and discarded a legitimate Arabic match | Rejected. `prototype-title-support.json.gz` retains scores. No extra title embeddings are computed in production code. |
| MiniLM can assign high scores to unrelated non-Latin-script queries | Its English-model vote does not corroborate predominantly non-Latin queries. E5 candidates remain available through broad retrieval; literal matches remain eligible. This is script applicability, not inferred language detection. |
| Space-delimited short-text filtering discarded useful Chinese/Japanese sentences | Made semantic admission script-aware; kept real-tokenizer overflow checks. Unit/native multilingual tests and final ablations exercise the corrected selection. |
| Tokenizer cloning increased peak memory substantially | Removed cloning. Read overflow records from the existing tokenizers without mutating their settings. Native Unicode/long-identifier tests verify complete text admission. |
| Streaming every query bounded RAM but caused a large warm-latency regression | Kept streaming only as the over-budget fallback. Shared matrices have a combined budget and bounded block construction. Matched-count scaling files retain the final RAM/storage/latency tradeoff. |
| Initial multilingual labels could accept an unrelated document containing the same number | Replaced those labels with expected URLs and full fact strings. `verify.py` independently regrades the corrected frozen evidence. |
| An initial ARM source transfer omitted worker fixtures and failed collection | Repeated with the complete source bundle. Final native wheel suites passed 764 tests per architecture. |
| Host tests encountered an old experimental chunker/database lock | Isolated all final native data directories. Unknown cross-namespace reads now fail closed when the public registry is unavailable; no arbitrary namespace fallback is permitted. |
| One supposed held-out invocation omitted `--heldout` | Preserved privately as a misconfigured development repeat and excluded it from held-out evidence. The final files verify against the separate held-out manifest hash. |
| Container evidence mounts initially lacked write permissions for the image user | Repeated captures as the directory owner. Reproduction instructions explain UID ownership; production ownership was not changed. |
| A large pruning backlog could hold one transaction across the whole backlog | Bound each maintenance transaction to 32 whole sources and 256 entries per expired-reference registry. Resume pending cleanup between jobs. A 70-source expiry test verifies 32/32/6 batches and complete FTS/vector cleanup. |
| Missing semantic dependencies could produce an empty result without useful diagnostics | Keep per-query warnings on the list-compatible Python result, including empty lists, and expose them in the HTTP envelope. Fresh core-only installation verifies lexical retrieval and explicit unavailable-model diagnostics. |

Remaining weaknesses are documented in [the report](REPORT.md). Neither the
support heuristic nor the negative fixtures establish universal answerability.
