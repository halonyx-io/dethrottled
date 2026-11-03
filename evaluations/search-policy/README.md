# Search policy evidence

The [1.3.0 report](results/2026-11-03/REPORT.md) explains why normal discovery uses
DDG with small Yahoo/Yandex supplements and a fifteen-choice menu. Research has
separate twenty-source and twenty-four-candidate ceilings.

The experiment used 299 usable training questions and 100 fresh held-out test
questions. Its larger internal pools and XGBoost models were evaluated, not
promoted to runtime defaults. Relevance labels came from models; fresh page
checks did not demonstrate better evidence recovery from reranking.

## Audit the published results

Run this command with standard-library Python; no network or API key is needed:

```sh
python evaluations/search-policy/verify.py
```

The check verifies artifact hashes, all 600 per-query comparison rows, identical
question sets across pool/judge groups, fifteen-result URL limits, 24 aggregate
means, and paired win/loss/tie counts. It does not establish that a relevance
judgement or supporting claim is correct, recompute bootstrap intervals, or
reproduce live upstream acquisition.

[Aggregate results](results/2026-11-03/test-summary.json) and
[per-query comparisons](results/2026-11-03/per-query-comparison.csv) retain losses
as well as wins. [Attribution](results/2026-11-03/ATTRIBUTION.md) identifies the
question sources. Full acquisition responses, judge attempts, corpus excerpts,
fetched bodies and the offline model replay/refit pack remain retained locally;
the public repository contains a partial evidence export, not that complete pack.
[Deployment checks](results/2026-11-03/deployed-public.json) are smoke tests,
separate from the relevance evaluation.

Earlier [compact-menu evidence](../compact-search/results/2026-11-03/REPORT.md)
and [agent-search evidence](../agent-search/results/2026-11-03/REPORT.md) retain
their historical versions and settings. They are not current setup instructions.
