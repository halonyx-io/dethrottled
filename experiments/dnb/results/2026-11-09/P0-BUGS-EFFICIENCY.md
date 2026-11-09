# P0 bugs and efficiency

2026-11-09. Candidate held. This is test-bed work; no version bump, publish or
deployment. Production remains 1.7.1.

## P0.1 Cache ceiling and expiry enforcement — implemented

- Added `DETHROTTLED_CACHE_MAX_BYTES` (default 512 MiB) and
  `DETHROTTLED_CACHE_MAINTENANCE_EVERY` (default 200 writes).
- Maintenance deletes rows past each kind's TTL and enforces the ceiling by
  deleting oldest rows, then compacting with `VACUUM`.
- Unknown kinds expire at the longest known TTL.
- `/stats` now reports `bytes`, `max_bytes` and the last maintenance result.
- Tests cover expiry, automatic maintenance, ceiling eviction (newest retained),
  and stats.

The first implementation looped on file size before compacting, which deleted
every row; the test caught it. It now selects rows by stored payload, compacts
once, and rechecks. A second bug was `VACUUM` failing inside an open transaction;
cursors are closed and the write committed first.

## P0.2 Browser idle close and memory pressure — implemented

- `DETHROTTLED_BROWSER_IDLE_SECONDS` (default 300, `0` disables) closes the
  separate crawl browser after it is idle and no render is active; the next
  crawl relaunches it on demand through `DETHROTTLED_CRAWL_SEPARATE`.
- The context factory and idle reaper share a lock, so a new context cannot race
  a close.
- `Memory.simulatePressureNotification` is sent after `/crawl` and `/drive`;
  `DETHROTTLED_MEMORY_PRESSURE=0` disables it. `/dnb/status.counts` reports
  `memory_pressure` / `memory_pressure_failed`.

Measured with a 2-second idle timeout:

| State | Result |
|---|---|
| After render | 691.5 MiB, `crawl_browser_separate=true` |
| After idle | 486.5 MiB, `crawl_browser_separate=false` |
| Relaunch render | 1.18 s, `quality=ok`, browser back |

Thirty renders stayed flat at ~698-706 MiB with pressure. A no-pressure control
was also flat at ~682-700 MiB on the simple page, so no separate RSS reduction is
claimed; the material saving is idle close.

## P0.3 PDF CID-corruption OCR — implemented

- Added `formats._cid_garbage` and per-page detection for `(cid:NNN)` tokens.
- A corrupted page forces OCR, replaces the unusable layer with recovered text,
  records `cid_garbage: true`, and warns
  `cid_garbage_recovered; OCR replaced an unreadable font text layer`.
- With OCR disabled it keeps the text and warns `cid_garbage; OCR disabled`.
- Tests cover thresholding, forced OCR, disabled OCR and the clean-page path.

Caveat: the test fixture creates literal `(cid:NNN)` text and a mocked OCR
result; a real paper with a missing ToUnicode map is still needed for a stronger
sample.

## P0.4 Error-page audit and gate detection — fixed

Controlled audit, reference vs candidate, `render=never`:

| Page | Reference | Candidate after fix |
|---|---|---|
| 403 / 429 / 503 | failed | failed |
| Short login / paywall / access-denied | thin | thin + `gate_page:*` |
| Long login / paywall / access-denied | **ok** | **thin + `gate_page:*`** |
| Ordinary article | ok | ok |

`content.gate_kind` now names `login`, `paywall`, `access_denied` and
`maintenance` only when a gate-like title and a visible gate signal agree. It
sets `quality=thin` and adds `gate_page:<kind>; content_limited; inspect_source`,
without touching the extracted text. Clean articles are unchanged.

## P0.5 Reddit efficiency — tested, not adopted

Current candidate with the consolidated browser:

- `https://www.reddit.com/r/programming/`: ok, `crawl4ai/crawl4ai-native`,
  1.83 s, 1,000 characters.
- `https://old.reddit.com/r/programming/`: failed after 7.12 s; direct 403,
  TLS empty extraction, crawl4ai network-policy host rejection, headed error.

The Hound rewrite does not transfer unchanged to this stack. No rewrite was
added; a future attempt needs an allowed-host and challenge-recovery design, not
a URL string replacement.

## P0.6 MCP tool-definition token cost — measured and reduced

| Profile | Tools | JSON chars | Approx tokens |
|---|---:|---:|---:|
| full (default) | 20 | 31,205 | 7,801 |
| core (`MCP_TOOL_PROFILE=core`) | 6 | 16,721 | 4,180 |

Core exposes `search`, `fetch`, `search_and_fetch`, `drive`, `read_document` and
`capabilities`; the full contract remains the default. Approximation is
`chars / 4`, not a tokenizer measurement. Hound's six tools are ~2.7K tokens;
the remaining difference is Dethrottled's richer schemas, not duplicated prose.

## Verification

- Host offline suite: **886 passed, 137 skipped, 2 deselected**.
- Full suite inside the candidate API image: **1,035 passed, 15 skipped,
  2 deselected** (includes PDF, Office and OCR tests skipped on the host).
- Targeted cache, CID/PDF and gate tests: **48 passed**.
- Documentation and agent-doc checks pass.
- Production remains healthy on 1.7.1; no lab containers left.

## Images

- API: `dethrottled-dnb-api:1.8.0-dev-p0-20261109`
  (`sha256:00fdfbcf…`)
- Worker: `dethrottled-dnb:1.8.0-dev-p0-20261109`
  (`sha256:316174ac…`)

Evidence: [p0-browser-lifecycle.json](p0-browser-lifecycle.json),
[p0-error-audit.json](p0-error-audit.json), [p0-reddit.json](p0-reddit.json),
[p0-tool-tokens.json](p0-tool-tokens.json),
[p0-full-suite.log](p0-full-suite.log),
[p0-image-suite.log](p0-image-suite.log),
[p0-targeted-tests.log](p0-targeted-tests.log).

Next: P1 date/source provenance, decoy buckets, query normalization and token /
truncation polish. No release action is authorised.
