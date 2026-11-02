# Source choices for agents — 3 November 2026

Keep DDG's source order for normal discovery and start with ten choices. The
larger study does **not** justify automatically adding this host's SearXNG Bing
or Brave results, or a neural/lexical reranker. Explicit expansion remains useful
when evidence is missing. This is a single-host result, not a claim that Bing
always fails everywhere or that Dethrottled beats paid search services.

## What was measured

The baseline is release 1.1.2, commit `ddb2f3d`. A separate Compose project used
its pinned API, browser and SearXNG images, separate data/state volumes and the
host's optional GPU configuration. Production configuration was not changed for
collection. The normal browser `/search` worker acquired DDG Lite/HTML lists;
SearXNG acquired Bing/Yahoo lists. Brave was guarded after refusal. `/drive`
was used only for separate Bing diagnostics, never as a substitute for the
normal-worker measurements.

There are **120 questions**, split before capture into **80 development and 40
held-out**. Eighty use HotpotQA's human-labelled supporting Wikipedia pages and
sentences, including bridge and comparison questions; forty cover technical and
practical tasks with reference pages and expected facts. Related reference pages
stay in one split. This mix is deliberately wider than the earlier 20 technical
queries, but it remains Wikipedia-heavy and is not a population sample of agent
workloads, shopping, current affairs or multilingual search.

For each question we captured the full available primary list up to 20 and one
available SearXNG page per backup. Query starts were paced at least eight seconds
apart. Candidate URLs were canonicalized and deduplicated while retaining each
provider's original rank. DDG Lite/HTML/TLS/browser constitute one provider
family; they never receive independent agreement votes. Yahoo is an acquisition
alternative and is not claimed to provide an independent index.

Ranking was replayed on identical lists: primary sizes 5/10/20, novel backup
quotas 0/2/3/5, source order versus RRF with `k=60`, backup weights
0.1/0.25/0.5/1, and preservation of DDG's first 0/1/3 rows. The union is fused
**before** display quotas. Policies cover no backups, always, failure, a frozen
lexical-suspicion trigger, and explicit broader requests. Both Bing/Brave and
Bing/Yahoo pairs were considered: **1,560 configurations per normal/broader mode**.
The trigger does not consult relevance labels or an LLM at runtime.

The protocol selected on development only: maximize estimated menu evidence-facet
coverage while allowing at most a 3-point loss in useful precision@3 and a
2-point increase in obvious off-topic fraction. Prefer at most 16 initial URLs
unless additional coverage warrants more; within one point of the best coverage,
prefer fewer upstream requests and fewer bytes. The locked selection was DDG10,
source order, no automatic backups for both normal and broader modes. Held-out
metrics were then evaluated once for the locked choices and fixed baselines;
the held-out set was not used to retune weights or triggers.

## Held-out results

“Useful” means an exact labelled reference page or a provider/rank-blind model
judgement that a candidate likely helps the task. “Estimated coverage” means
reference/evidence facets likely supported by the menu, not a verified answer.

| Frozen menu | Useful choices @3 | Useful choices @5 | Useful choices @10 | Estimated menu coverage | Obvious off-topic fraction |
|---|---:|---:|---:|---:|---:|
| DDG5, source order | 2.53 | 4.10 | 4.10 | 80.0% | 2.0% |
| **DDG10, source order** | **2.53** | **4.10** | **7.53** | **81.3%** | **3.3%** |
| DDG20, source order | 2.53 | 4.10 | 7.53 | 86.3% | 6.2% |
| DDG10 + up to 3 Bing / 3 Brave, appended | 2.53 | 4.10 | 7.53 | 81.3% | 25.0% |
| Same quotas, equal-weight RRF60 | 1.73 | 2.53 | 5.55 | 81.3% | 25.0% |
| DDG10 + up to 3 Bing / 3 Yahoo, appended | 2.53 | 4.10 | 7.53 | 82.5% | 23.3% |
| Same quotas, equal-weight RRF60 | 2.50 | 4.00 | 5.63 | 82.5% | 23.3% |

Brave supplied **zero** candidates; “up to” is important. Precision is divided
by the actual menu length when fewer than k rows exist; counts above make this
visible. DDG10 matched **53.8% of exact labelled reference pages**, versus 57.5%
for DDG20. This is page identity, not domain matching. Useful@3 precision for
DDG10 was 84.2%; at least one useful top-three choice occurred in the per-query
results retained in the archive.

The paired 10,000-sample query bootstrap estimates DDG20's additional menu
coverage at **+5.0 percentage points, 95% interval +1.3 to +10.0**. Four of forty
questions gained a facet, none lost one. Equal-weight Bing/Brave RRF lost
**26.7 points of useful precision@3**, interval **−30.8 to −22.5**: 32 losses,
zero wins, eight ties. Bing/Yahoo RRF's top-three difference was −0.8 points,
interval −4.2 to +2.5; two wins, three losses, 35 ties. It did not establish a
reliable ranking improvement.

Development DDG20 coverage was 85.6% versus 80.6% for DDG10, but its off-topic
fraction increased by 2.6 points, failing the preset quality gate. We retain the
locked choice instead of changing the gate after seeing the holdout. An agent
missing a fact can explicitly expand to 20 while preserving the useful first ten;
that is different from automatically replacing every initial menu with 20.

A supplementary, post-selection description of the old HTTP default8 versus
selected10 found development coverage 79.4% versus 80.6%, and held-out coverage
81.3% for both. The extra two choices are not a demonstrated held-out accuracy
win over eight. Ten aligns HTTP with the existing MCP default and the tested
normal-menu setting. This comparison did not select or retune the policy.

The archive includes every query's menus, useful counts, reference/facet matches,
provider ranks, uncertainty, response bytes and wins/losses, plus category splits.
The bootstrap measures query sampling uncertainty; it does not remove model bias,
benchmark contamination or host/upstream variation.

## Labels versus fetched evidence

Candidate judgements used `deepseek-v4.1-flash:cloud` through the owner's existing
Ollama gateway solely for evaluation. It is **not** a runtime dependency or
ranking service. Candidates were shuffled; provider, rank and configuration were
hidden. The independent Codex audit agreed on useful/not-useful classification in
55/60 sampled development pairs. The five disagreements were useful intermediate
pages the judge rated too low. The sample was stratified and both reviewers are
models: this is not human-rated population accuracy. Some search results echo
Hotpot questions/answers; answer text in a URL is not treated as fetched proof.

We fetched the primary first choice and each available leading novel backup
choice through normal `/fetch` with automatic rendering/recovery: **283 unique
URLs**, 16,000 returned characters per read, all negative outcomes preserved.
An independent content-verification pass required a task-relevant factual excerpt
from retained text. Excerpts were checked for exact presence and valid facet IDs;
21 proposed supports failed those checks and were rejected. Semantic interpretation
is still model-assisted, and the character cap can omit evidence later on a page.

| Leading choice | Query/choice pairs | Extraction quality `ok` | Readable >=200 chars | At least one verified evidence excerpt |
|---|---:|---:|---:|---:|
| DDG first | 119 | 115 | 115 | 96 |
| Bing first novel | 120 | 99 | 109 | 1 |
| Yahoo first novel | 70 | 67 | 67 | 48 |
| Brave | 0 | — | — | — |

There was one genuine empty primary capture. Useful evidence in a first choice
does not imply the entire multi-hop question was answered. Conversely, readable
Bing pages frequently failed the task: transport success is a poor relevance
metric. Quality, truncation, completeness, pollution, timings, hashes and evidence
support are recorded separately. The check does not claim that unflagged text
is pollution-free or that all pages in every menu were fetched.

## Live acquisition, bursts and upstream refusals

The 12-query paired, randomized-order live size comparison used the normal
DDG browser `/search` path, with an eight-second pause between calls. All
**36/36 requests succeeded**. Median latency was **855 ms / 902 ms / 1673 ms**
for requested sizes **5 / 10 / 20**. Five and ten used one page in the winning
route but two recorded navigation requests across the speculative Lite/HTML
race; twenty used two winning-route pages and four navigation requests. Thus
showing five instead of ten did not halve upstream work. The mean compact
worker-response sizes were approximately **2.6 / 4.8 / 9.0 KB**; these include
worker diagnostics, unlike the replay's menu-only byte metric.

Six further development queries compared actual no-backup, always-on Bing/Yahoo
and frozen-suspicion acquisition. All 18 primary searches succeeded. Median
end-to-end times were **913 / 915 / 1016 ms**, respectively. Always-on made
12 additional backup calls; the suspicion trigger did not fire. Parallel
backups were cheap in latency here, but their poor choices still failed the
quality gate. This small live subset does not demonstrate conditional recovery
under a genuine outage. In the frozen development data, failure/suspicion
Bing/Yahoo backups recovered one additional half-facet, raising average coverage
from 80.6% to 81.3%; that is within the preset one-point simplicity margin and
has no held-out failure case to validate it.

The bounded burst workload ran **three concurrent requests in three batches**,
60 seconds apart: **9/9 successful**, median 1535 ms, range 878–1974 ms. This tests
small realistic concurrency, not sustained saturation or unlimited capacity.
The separate, unmodified production Compose API returned **12/12** explicit
10-result, cache-bypassed controls, median 694 ms. All 120 returned rows reported
`web-tls-ddg-lite`. Those controls verify the actual cheap-tier path; they are
not pooled into the frozen headed-DDG ranking scores or counted as independent
provider votes. The full normal `web` path can use browser Bing on fallback;
its name alone does not identify its backend.

SearXNG's effective measured settings were 180 s access-denied/429, 3600 s CAPTCHA,
1296000s Cloudflare CAPTCHA, 86400 s Cloudflare denial and 604800 s reCAPTCHA.
The core's separate configured rest was 1800 s. The initial Brave preflight
reported too-many-requests; its raw first HTTP status was not instrumented.
A single recovery probe just over 30 minutes later recorded **HTTP429**, a
CAPTCHA page and **no Retry-After header**. It returned zero rows, so the test
extended its next-probe delay to at least 3600 s. No per-query Brave retry was
made during its cooldown, and timer expiry was never counted as recovery.

Across browser telemetry there were **468 HTTP200 and six HTTP202 navigation
responses**, including pagination and later controls. The non-200 observations
are retained. We did not retain bodies for those 202 responses, so they are
reported as non-usable responses, not proven CAPTCHAs. The evaluation route
guard covered 403/429 and named challenge reasons but did not rest bare 202;
this limits the rate-policy inference. This experiment is not evidence that
DDG never refuses requests.

For the Dirleton fortress question, two repeated normal SearXNG requests returned
Middle Ages/dictionary pages despite an upstream200 and a page title echoing the
full query. Two corrected `/drive` controls with the same query instead exposed
Dirleton/Firth of Forth results. Exploratory SearXNG locale probes returned
relevant titles for `all` and `en-MY`, while `en-GB` returned no rows. The pinned
source already contains upstream's locale-related Bing fix. These observations
point to an acquisition/locale issue, but one question cannot select a universal
locale or justify enabling a new Bing route. Two earlier browser-control probes
used an unsupported action and returned 422 before navigation; they are preserved
as harness errors, not provider failures.

## What changes, and what stays optional

The candidate changes HTTP's default menu from eight to ten, retains source order,
and exposes the measured normal/expansion workflow in the agent-visible instructions.
Explicit counts, the 50-result ceiling, source profiles and expansion remain
available. No automatic Bing/Brave fusion or snippet reranker is enabled.
Existing `ranking="fusion"` remains an opt-in source/lexical blend; it is not
renamed as multi-provider RRF or claimed as the experiment's fusion winner.

A real cooldown bug is corrected: selecting one blocked engine, or exhausting all
selected engines, no longer forces a retry during its rest period. An empty
rested-engine list returns diagnostic `cooldown` without calling SearXNG, because
an empty SearXNG engine parameter would select its defaults. Twenty controlled
calls during a sole-engine cooldown cause zero network requests.

The pinned SearXNG image ignored `Retry-After`. A small Compose plugin now extends
its existing suspension on refusal using integer seconds or HTTP dates; it never
shortens CAPTCHA/Cloudflare suspension. Offline tests in the actual pinned image
verify both 429 and 403 with `Retry-After: 7200` suspend for at least 7,200 seconds,
while short or invalid headers preserve the original policy. This proves header
handling, not that a real provider will become usable when the timer expires.
No API keys, cloud ranking service, paid upstream or new runtime package is added.

The base-install offline suite passed **607 tests**, with 67 skips and two network
tests deselected. The actual full API image with candidate source mounted passed
**677 tests**, with 15 skips and two deselections. Targeted checks cover sole/all-
engine cooldowns, twenty no-request calls, header/date parsing, unchanged exception
types and stronger suspensions, and default/explicit menu counts reaching
acquisition on both HTTP search shapes. Ruff and Compose validation passed.
The staged API reports 1.1.3 and its OpenAPI default is 10. The real staged MCP → API → TLS/browser test returned ten default and twenty
explicit results, with adapter/backend versions 1.1.3 and matching instruction
hashes. It initially caught a duplicated stale bridge workflow despite matching
versions. The bridge now imports the API's shared workflow; a controlled stale-
adapter rerun reproduces the mismatch, and the corrected test passes. The offline
adapter verifier also asserts shared instructions. Native CI and promotion are
recorded separately; these local observations do not assert that CI has run.

## Reproduction and limits

Download [replay-evidence.zip](replay-evidence.zip), check its
[SHA-256](replay-evidence.sha256), and extract it outside the checkout. From a
Dethrottled checkout run:

```sh
DETHROTTLED_REPO_ROOT="$PWD" python3 /path/to/extracted/reproduce.py
```

This uses Python 3.10+ standard library only and makes no model/upstream calls.
It checks the frozen question/protocol hashes and reproduces the selected
configuration's development metrics and all fixed held-out baseline metrics.
The original grid code, per-provider ranks, labels, raw captures, corrected
telemetry counts and per-query comparisons are included. The archive records
HotpotQA's CC-BY-SA4.0 attribution and dataset mirror. Search snippets remain
attributed to their URLs.

Bulk fetched third-party page bodies, browser state and credentials are excluded
from publication. Full read bodies/model verification records remain in the
local raw bundle; the public [read summary](read-summary.json) retains per-query
quality, facet counts and limitations. Public results include the
[held-out comparisons](heldout-results.json), [selection lock](selection-lock.json)
and [live observations](live-summary.json). Exact live acquisition/fetchability
will change with time and host; ranking replay is the reproducible part.

Two captures affected by evaluation-container setup/restarts were repeated in full
and rejudged; originals remain in the private raw bundle with the repair record.
The repeated empty result is retained, not retried until success. Initial schema-
invalid judging pilots are also preserved but excluded from final scores. Raw
request counters with missing query-hash correlation are retained; reported costs
use provider host plus unambiguous serial acquisition windows, with the correction
recorded explicitly. Local cached/suspended calls are never counted as upstream
requests or evidence of recovery.

Upstream context: SearXNG [issue 4964](https://github.com/searxng/searxng/issues/4964)
describes unrelated/first-word Bing results. Its [September fix](https://github.com/searxng/searxng/pull/6671)
changes locale parameters; our pinned source already includes it. These reports
support investigating the failure mode, not assuming that it explains every
response or provides a successful fix on this host.
