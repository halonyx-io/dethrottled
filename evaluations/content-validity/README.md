# Content validity evaluation

Measure three different outcomes: whether acquisition returned text, whether it
contains predefined task evidence, and whether error-banner pollution is suspected.
None establishes source completeness or semantic answer correctness.

## Fixed payload comparison

`fixtures/cases.json` contains 18 synthetic payloads with explicit pollution labels
and a fixed factual sentence. Run `fixtures/read.py` inside a baseline image and a
candidate with identical options. Compare surfaced diagnostics and fact retention.
The set deliberately includes unfamiliar English and French banners to expose misses.
It is a controlled regression set, not an independent population accuracy estimate.

## Live observation

Freeze the protocol before acquisition. Define URLs, tasks, expected fact assertions,
response size and strategies. Use separate core stores with identical upstream worker
configuration. The runner bypasses extraction caches, alternates endpoint order and
flushes every observation to JSONL, preserving failures even if interrupted.

```sh
python scripts/evaluate_content.py evaluations/content-validity/protocol.json \
  --endpoint baseline=http://127.0.0.1:18791 \
  --endpoint candidate=http://127.0.0.1:18790 \
  --output /tmp/dethrottled-content-observation --repeat 2
```

The evaluator applies the same independent text-only banner assessment to both
versions. Fact matches overlapping suspect spans are excluded. Exact matched quotes
and offsets are retained. Assertions can miss equivalent Markdown, synonyms or facts
outside the response bound; review the source rather than changing assertions during
the run. A matched regex is necessary evidence for its defined task, not truth proof.

HTTP success, extracted text, assertion support and suspected pollution are separate
fields. A longer response or a slower browser attempt is not a coverage win. Shared
upstream caches, browser sessions, temporal variance and short repeat counts limit
causal conclusions. No API key or paid provider is required.

For publication, retain hashes, counts, diagnostics, request parameters and short
assertion excerpts; omit full third-party page bodies. Full responses can stay in
local evaluation storage. Do not publish credentials or browser storage.

See the [recorded results](results/2026-11-01/REPORT.md).

[Documentation home](../../docs/README.md) · [API](../../docs/API.md) · [Evidence](../../docs/EVIDENCE.md)
