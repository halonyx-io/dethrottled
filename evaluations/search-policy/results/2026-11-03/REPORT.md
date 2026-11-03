# Bounded default discovery — 1.3.0

The default web menu now combines DDG with Yahoo/Yandex through SearXNG. It preserves DDG order, alternates novel supplements and returns at most fifteen unique URLs. DDG acquisition variants share ten choices; supplements admit at most three each. Search acquires one SERP page per selected SearXNG engine, not article bodies. Fast stays DDG-only. News/academic sources remain explicit.

Research keeps ten readable sources by default and permits twenty. Across query facets it admits at most 24 unique candidate URLs, selecting at most max_sources + four primary URLs. Failed/duplicate reads can use those replacements; the global ceiling is never lifted to fill the bundle. Attachment and transport recovery remain separate acquisition attempts.

## Evidence behind the decision

The expanded experiment froze 400 questions: 300 train and 100 new test; one erroneous training reference was quarantined, leaving 299. Technical Stack Overflow questions and multi-hop HotpotQA questions were used. This is not representative of all news, shopping, local or multilingual tasks. The exact query/ranking comparisons are in [per-query-comparison.csv](per-query-comparison.csv); source attribution is in [ATTRIBUTION.md](ATTRIBUTION.md).

Provider/rank-blind model labels were used, not human ground truth. DeepSeek v4.1 Flash supplied primary labels; GPT-OSS 120B independently reviewed all 3,909 test candidates. Binary usefulness agreement was 85.65%; exact grade agreement 55.05%. A useful source means direct evidence or a necessary useful intermediate according to that judge.

| Mean useful sources | DDG alone | Compact source combination | Compact XGBoost |
|---|---:|---:|---:|
| Primary top three | 2.37 | 2.40 | 2.50 |
| Independent reviewer top three | 2.00 | 2.04 | 2.11 |
| Primary top ten | 6.99 | 7.34 | 7.37 |
| Independent reviewer top ten | 5.59 | 5.93 | 5.95 |

Supplements improve the available menu on this test. XGBoost's compact top-three difference versus source order was +0.10 (query bootstrap 95% interval +0.03 to +0.18), but the reviewer gave +0.07 (-0.02 to +0.16). Top-five intervals crossed zero for both. Larger pools averaged 23.64 and 39.09 candidates versus 11.64 compact, without a clear top-five or task-facet coverage gain. Semantic features were not selected by training CV. Increasing training size did not consistently improve outcomes. No trained ranker, extra pagination or semantic inference is enabled in this release.

Fresh cache-bypassed reads of 35 URLs on a fixed stratified 12-question sample found supporting excerpts on 12/17 promoted and 12/17 displaced URLs. Promoted IMDb failed; displaced CSDN was thin. The sample does not establish an end-to-end evidence-recovery gain. Exact excerpts were checked against retained text, but task support was still model reviewed.

Actual pinned Compose SearXNG acquisition issued 694 new Yahoo and 700 Yandex page requests, excluding reused legacy training first pages. Six Yahoo second-page slots were skipped. Yahoo had three parsing-error cells, an HTTP error and a local suspension; no observed upstream 403/429/CAPTCHA or Retry-After. This was a paced run, not a capacity guarantee. DDG made 300 new worker requests, with 286 Lite winners, five HTML winners and nine HTTP-503 failures, including two in test. Empty/error cells were retained.

Raw acquisition, all label attempts, full page bodies, model matrices and a verified offline replay/refit pack remain retained locally. This repository includes aggregate and per-query outcomes, not private corpus excerpts or full fetched pages. [Test summaries](test-summary.json), [pool/latency/judge statistics](experiment-stats.json), [learning curves](learning-curves.json), and [fresh-read summary](read-summary.json) preserve negative results.

## Implementation checks

Regression cases cover the 15-choice ceiling, DDG-first order, alternating bounded supplements, an empty/failed provider, explicit single-page engine parameters and original provider ranks, 20-source research, and a 24-attempt primary-URL ceiling under failed reads. Core and MCP schemas, capability metadata, defaults and docs use the same policy. The local suite passed 615 tests (67 skipped, two network tests deselected); lint and documentation checks passed. [Real offline adapter checks](offline-adapters.json) exercised 15 search results, 20 research sources, validation, native images and backend identity replacement. [Staged Compose searches](staged-search.json) returned 11/12/11 unique choices in 0.6–1.3 seconds.

[Deployed public REST/MCP checks](deployed-public.json) confirmed 1.3.0 end to end: the public default search returned twelve unique choices in 1.24 seconds; a two-source research smoke test read two sources from fifteen candidates in 10.2 seconds. MCP initialization/workflow hash, tool schemas, excess-limit rejection and matching backend identity passed. These are deployment smoke checks, not an additional relevance benchmark.

A larger default menu is not proof of better answers. Read and verify selected sources; no-fetch events remain unknown rather than automatic negative relevance labels.
