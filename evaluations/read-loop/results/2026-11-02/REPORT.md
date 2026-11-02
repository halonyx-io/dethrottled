# Autonomous reading: 0.9.2 to 0.10.0

The candidate recovered the predefined fact in five controlled cases where the
0.9.2 baseline did not. It also supported continuing the recovered browser state
through an ordinary `drive` call. This is evidence of working recovery mechanisms,
not five hostile-site breakthroughs.

## Controlled comparison

Both cores used isolated stores, the same candidate browser worker and disabled TLS
and Crawl4AI transports. Requests used the same URL, 8,000-character limit, bypassed
cache and distinct per-run caller namespaces. The fact was declared before testing:
“7341 tonnes”. Source and runner are in the [method directory](../../README.md).

| Case | Baseline fact present | Candidate fact present |
|---|---|---|
| Publisher-declared same-path Markdown | No | Yes |
| Scroll-loaded article | No | Yes |
| Standard details section populated on expansion | No | Yes |
| Observed JSON response identifying the primary document | No | Yes |
| Cookie-dependent page after explicit seed read | No | Yes |
| Ordinary article / seed page | Yes / Yes | Yes / Yes |
| Unrelated JSON advertised as an alternative | No | No |

Candidate render-never and recovery-manual checks did not recover the lazy article.
A different caller did not inherit the seeded cookie. The explicit drive handoff
retained the lazy article's revealed fact without navigating again. These are
bounded synthetic assertions, not a cold-model agent evaluation.

[Protocol](protocol.json), [full fixture records](comparison.jsonl),
[summary](comparison-summary.json), [handoff](handoff.json).

The first startup pilot included a connection reset while restarting the candidate
and a not-yet-ready worker. It is preserved in
[startup pilot records](startup-pilot-comparison.jsonl) and its
[summary](startup-pilot-comparison-summary.json). The confirmation waited for ready
services and used fresh caller namespaces. Readiness failures are not source-access
wins or losses and are not silently removed from the record.

## Live observations: no new hostile-source win

Four frozen URLs were read once per version using the full configured transports
and the same GPU browser worker. This small live sample is observational, with
shared upstream services and no isolation from changing publisher responses.

| Source | Baseline | Candidate |
|---|---|---|
| Python sqlite3 documentation | Read; 1/1 assertion | Read; 1/1 assertion |
| Crunchbase/OpenAI | Failed; 0/3 | Failed; 0/3 |
| G2/Notion | Failed; 0/3 | Failed; 0/3 |
| Booking home page | Read; 2/3 pattern assertions | Read; 0/3 pattern assertions |

Booking is a negative finding: the selected browser view omitted the tested date
labels seen in the baseline's much larger, partly Malay extraction. The two matched
baseline patterns were occurrences of `checkin`/`checkout`, not proof of a usable
booking form. Neither version completed the declared task. Localization, separate
sessions and dynamic content further limit causal interpretation. We do not count
this as an improvement. This observation prompted an explicit `evidence_variants`
reference and warning whenever recovery selects another representation, with a
follow-up to read the retained original. That preservation behavior is unit tested;
this recorded live sweep predates the final handoff/preservation changes.

Crunchbase's existing failed headed attempt was not repeated. G2's headed transport
returned a response without an extractable document; the planner inspected once,
observed HTTP 403 and stopped. No new successful hostile-source read was observed.
[Live protocol](live-protocol.json), [observations](live-observations.jsonl),
[summary](live-summary.json).

## Graphics, regression checks and limits

On this AMD/Mesa host, full DRM device mapping plus numeric render/card group IDs
and ANGLE GL EGL produced a real AMD renderer and the expected clear/read pixel.
The same browser image without devices produced llvmpipe and the same correct pixel.
See [GPU](gpu-health.json), [software](software-health.json) and
[Compose selection](compose-selection.json). Hardware verification is a rendering
capability test; it does not establish Cloudflare, PerimeterX or DataDome defeat.

The final local regression suite passed **622 tests**, with 15 skipped, two live
network tests deselected and four existing FastAPI lifecycle deprecation warnings.
[Regression log](regression-release.log). CI and deployed public transport checks
are recorded in the pull request and deployment verification, separately.

The planner uses observed gaps and conservative predefined actions, not an LLM or
semantic answer verifier. It can still select a view that omits useful material;
read retained variants and source warnings. Its time budget admits new actions and
does not interrupt an in-flight parser/transport operation. Browser actions remain
bounded; arbitrary controls, logins and exports require deliberate agent drive calls.
TLS profile cycling and random human-like gestures were not enabled: earlier local
exploration produced no verified additional hostile-source reads.

Implementation follows [Playwright actionability](https://playwright.dev/python/docs/actionability)
for normal summary clicks and [ANGLE's documented renderer selection](https://github.com/google/angle/blob/main/doc/DebuggingTips.md).
The local renderer and pixel probes, rather than the launch flag alone, determine
whether hardware rendering actually works here.
