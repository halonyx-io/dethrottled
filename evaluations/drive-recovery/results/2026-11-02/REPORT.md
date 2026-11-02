# Native Reddit browser recovery — 2 November 2026

Dethrottled 0.10.1 retains Patchright and its current Chromium/GPU. A small navigation recipe recovered Reddit in both manual driving and automatic headed reading on this host, without new packages, keys or services. This establishes additional reads for the tested sources, not general anti-bot immunity.

## Controlled results

Same image, GPU and fresh-session protocol; control disables the recipe. One observation per case is published in [observations.json](observations.json).

| Case | Recovery off | Recovery on |
|---|---|---|
| Reddit programming thread | Humanity challenge, no comments | Actual post and 16 comment elements; 1,901.6 ms navigation/read |
| Reddit programming listing | Humanity challenge | Actual posts; 1,629.17 ms |
| Python sqlite3 documentation | Content; 399.88 ms | Content; 419.37 ms |
| Crunchbase/OpenAI | HTTP 403 | HTTP 403 |
| G2/Notion | HTTP 403 | HTTP 403 |

On the recovered thread a native sort-menu click took 387.36 ms, including its wait. Replaying the same operation took 2.65 ms and left the menu open; it did not double-click. A following call retained the live page/menu and history in 53.79 ms. These are individual timings, not medians.

## What made the difference

The [2×2 ablation](ablation.json) compared the native browser, a copied Crawl4AI UA/viewport/hint profile, a host cookie alone, and both. Native and profile-only sessions challenged. Both cookie variants loaded the thread and 16 comments. The test measured after additional settling: its roughly four-second totals are not comparable to the later readiness-based navigation timings.

Crawl4AI [sets `cookiesEnabled=true` before HTTP navigation](https://github.com/unclecode/crawl4ai/blob/main/crawl4ai/browser_manager.py). Dethrottled now applies that preference only to Reddit hosts and only when absent, preserving an existing value. It waits up to five seconds within navigation time remaining for post/comment DOM readiness. Checkpoint restoration uses the same navigation path. The cookie is host-scoped; no credentials or cross-origin state are transferred.

Saved older 0.8, 0.9.2 and pre-October-31 worker images also challenged in fresh-session tests today ([history](historical-versions.json), [older worker](historical-old02.json)). These observations cannot identify which historical change caused the user's earlier working session to stop. The forward fix is verified independently of that unresolved causal history.

## Automatic reading and the failed pilots

The automatic test disables Crawl4AI, TLS and Jina in isolated cores so a successful renderer cannot hide a broken headed fallback. Control failed after 15,234.39 ms. Candidate returned 10,532 characters in 2,516.72 ms, with both the ParticleDB post and the predefined comment fact `WHERE 4 = 5`. The headed attempt took 2,294.13 ms. See [automatic.json](automatic.json). This proves that the normal ladder can acquire real thread/comment evidence through the repaired native driver, not just manual navigation.

Two pilots are retained:

- [Readiness pilot](readiness-pilot.json): waiting only for a post was too early for comments. The final predicate also waits for comment elements or an explicit empty-comments message on thread URLs.
- [HTML-prefix pilot](html-prefix-pilot.json): the HTML capture cap could retain scripts/navigation before useful comments. Headed reads now inspect visible text from the same live page when HTML is truncated. HTML truncation is preserved separately from text truncation, avoiding redundant recovery when the visible snapshot is complete. An intermediate successful run before this distinction took about 4.5 seconds; the final run above took about 2.5 seconds. This is an observation, not a statistically established speedup.

Rendered text can contain navigation, advertising and related material. The response warns of this. Matching the two predefined facts is a limited task check; full source completeness and answer correctness remain unverified. `access.status` describes observed content/challenges independently from action execution success.

## Compatibility and limits

[Existing browser contract checks](contracts.json) passed with recovery both off and on: chunked JSON, decoded-body limits, iframe read/action, popup read, restart restoration of cookies/localStorage/sessionStorage/IndexedDB, action history and downloads. The [repository test log](regression.log) records 636 passed, 15 skipped and two network tests deselected; lint and documentation contracts passed. A [Reddit-specific worker restart](reddit-restore.json) also restored the existing preference, post and comment fact in 1,515.9 ms. Native action vocabulary, operation replay, scope guards and checkpoint format remain in use.

No new Crunchbase/G2 reads were observed. GPU was held constant; this experiment does not establish a GPU benefit. No CAPTCHA solving, proxy dependency, paid API, TLS-profile churn or randomized interaction sequence was added. Existing user-provided preference cookies are respected, so a prior false preference may produce a different outcome.

## Upstream review and decision

The installed Crawl4AI implementation and upstream source suggested the cookie ablation; the local controlled result justified adopting that behavior without replacing the driver. [Patchright](https://github.com/Kaliiiiiiiiii-Vinyzu/patchright) already patches browser automation leaks. Its claims are not evidence of success against a particular source. A [Python issue](https://github.com/Kaliiiiiiiiii-Vinyzu/patchright-python/issues/104) reports init-script routing problems in a particular wheel/network environment; it does not prove this deployment is affected, so no speculative monkey-patch was applied.

An upstream [Crawl4AI latency discussion](https://github.com/unclecode/crawl4ai/discussions/2119) reports overlay-removal timers stalling under CSP and a subsequent fix. This argues for bounded, observed work rather than adding scripts indiscriminately. No overlay-removal upgrade is claimed here. Broader fingerprint changes, warm-up gestures and backend replacement remain unverified ideas; the inexpensive cookie/readiness/text fixes have direct evidence and preserve existing browser operation.
