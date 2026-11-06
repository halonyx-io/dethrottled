# Long PDFs and corpus diagnostics — 6 November 2026

Uncommitted candidate based on released 1.6.0 (`0006cdf`). No version bump,
publication, push or deployment. Production and the independent benchmark files
were not changed. [Reproduction](../../README.md), [raw summary](summary.json).

## Confirmed issues and fixes

| Finding | Implementation and evidence |
|---|---|
| Implicit PDF extraction stopped after 100 pages | Native text now considers up to 1,000 pages within the existing one-million-character extraction default; explicit API ranges remain at most 100 pages. Same 194-page RFC bytes recover all three fixed facts. |
| Character clipping could consume a page but discard its tail | Stop before adding a later page that does not fit; continuation starts at that unconsumed page. A single oversize page remains explicitly clipped with `truncated_page`/warning and source-image inspection. |
| OCR cap could consume unread scanned pages | Stop at the first page requiring OCR after its budget is exhausted. `next_page` now points to that page; continuation gets another bounded OCR budget. No unlimited OCR. |
| HTML browser recovery attempted on successfully acquired partial documents | Non-HTML parser evidence retains its format/range continuation instead of HTML browser actions. The actual candidate API fixture made zero browser calls. HTML acquisition/challenge recovery remains unchanged. |
| Reparse retained stale status, character count and recovery-gap metadata | Refresh `content_status`, `source_partial` and `content_chars`; discard the superseded plan on the new extraction version. Original handle/trace remains retained. Late-page image inspection targets the actual selected/clipped page. |
| Capabilities omitted corpus request methods/required parameter | Add request descriptions and executable GET example while preserving existing endpoint fields and REST `q`/MCP `query` contracts. Regression executes the advertised example and verifies wrong method/parameter rejection. |
| Related semantic candidates could be mistaken for answer coverage | Add `result_kind`, explanatory envelope note and bounded per-hit literal `query_anchors`. Clarify MCP/workflow/guides. No ranking, filtering, floors, model changes or answer-verification claims. |

Native table analysis remains bounded to 100 pages per read and reports its
separate scan range/partial state. Later native text is still retained; select
later explicit ranges for table analysis. Long explicit layout requests beyond
that window retain native output and request a narrower layout range.

## RFC 9110: fixed fact labels, identical bytes

SHA-256: `60b30efa1048900833d1758440247fe8ac85a3134f2327388dcb24e07d814c89`.
It matches the independent benchmark's retained PDF. Original frozen scores were
not changed. Measured character counts below are parser text, not serialized JSON
including page/block diagnostics.

| Measurement | Released baseline | Candidate |
|---|---:|---:|
| Pages retained, each of three auto-mode parser runs | 100/194 | 194/194 |
| Fixed facts retained, each run | 1/3 | 3/3 |
| Parser text characters, auto mode | 272,357 | 522,376 |
| Median elapsed seconds, auto mode | 52.76 | 58.83 |
| Median peak parser-process RSS, MiB | 370.98 | 391.60 |
| Median elapsed seconds, native mode | 3.60 | 5.63 |
| Median peak parser-process RSS, native mode | 158.71 | 158.80 |

Elapsed time/CPU varied on a busy shared host (observed load average 36.93 on
16 logical CPUs). The first auto baseline overlapped corpus-model evaluation;
some native repeats overlapped regressions. All original observations are
retained. **These establish fact recovery, not a clean latency win, reliable CPU
delta or universal memory requirement.** See per-run CPU seconds in the JSON;
per-process RSS is not whole-stack memory. Larger native reads can cost more.

A separate offline **actual `/fetch` API** test, using real parsing/retention and
fixture transport, returned HTTP 200, all three facts, all 194 pages, 466,034
normalized retained characters, `source_partial=false`, `truncated=false`,
`content_status=complete` and zero browser calls. This verifies the normal API
path rather than parser output alone. It does not verify every fact in the RFC.

Remaining bounds: character/page ceilings, eight-page default OCR budget,
bounded inferred tables/layout and single oversize-page clipping. Cached 1.6.0
extractions are not rewritten; refresh/bypass to reassess coverage.

## Corpus: real models, separate evidence labels

Four fixed synthetic sources, twelve manually labelled questions (direct facts,
paraphrases, related-but-insufficient and absent answers), three retrieval modes
and two support policies produce **72 paired configurations**. MiniLM and E5 are
the existing actual packaged models. This is a small diagnostic pilot.

- All 72 configurations preserve identical ordered hits/support status.
- Both versions return 42 candidate passages across those configurations; 32
  support the predefined tasks and 10 do not. These are repeated configuration
  outcomes, not 42 independent pages or a general precision estimate.
- All 42 candidate hits now carry bounded literal-overlap diagnostics.
- Standard semantic retrieval retains all four tested useful paraphrases.
- The absent question asking when the exit marker was installed still retrieves
  its descriptive passage. That passage does not answer the date question:
  `answer_support=unverified` remains. Diagnostics clarify this without filtering
  away the same source when it answers a useful paraphrase.
- Absent `land patent` gets no standard semantic hit in this small fixture;
  the controlled regression separately forces related land-survey candidates
  and verifies that unmatched `patent` is visible without asserting whole-corpus
  absence. No claim of zero false positives or automatic entailment detection.

## Deployment resource report

The independent harness sums Docker CLI memory for the entire Compose project;
its recorded smoke observation was 3,122.7 MiB across eight containers. This
includes optional workers and an additional PDF worker. It is neither a default
five-service idle requirement nor an isolated adblock delta. The harness used an
already-running warmed deployment; its own startup figure is not a fresh stack
startup benchmark. Documentation now makes service scope, memory accounting,
model/browser/cache state and workload conditions explicit. No fabricated
Firecrawl comparison or speculative memory optimization was added.

## Validation and remaining gates

Final relevant native x86_64 regressions: **216 passed**. They cover formats,
PDF ordering/continuation, actual document reparse, read plans/workflow, corpus
lifecycle/cross-caller retention, API contracts and endpoints. Original pre-fix
assertions retain **four failures and one pass** in `pdf-before-regressions.txt`.
Documentation/example checks, generated references, agent coverage and targeted
lint also pass. Full release CI has not been run for this uncommitted candidate.

Native ARM64 rerun could not start: the available SSH alias rejected public-key
and password authentication. No remote configuration was changed. That gate
remains before release; prior 1.6.0 ARM64 results are not presented as validation
of these changes. No new runtime dependencies, services, models or paid APIs.
