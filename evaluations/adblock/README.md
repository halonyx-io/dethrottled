# Native adblock evaluation — 5 November 2026

Unreleased candidate based on 1.5.2; **not published or deployed**. Production
API/MCP remained on 1.5.2. All Compose changes were exercised in an isolated
project, then shut down without deleting volumes.

## Decision and implementation

Keep HaGeZi Multi PRO enabled by default with one switch. The implementation
adds no dependency, model, separately managed service or container. HTTP/native
TLS clients check each redirect. Managed browsers use a per-context asynchronous
HTTP/CONNECT gate: TLS stays encrypted and Crawl4AI's existing egress/DNS-pinning
proxy remains authoritative. Scope and public-target protections still apply.
Search ordering, corpus policy and extraction algorithms are unchanged.

The final candidate closes problems exposed by real transport tests rather than
assuming a Playwright routing hook covers everything. The default stack has four
filter-owning processes (API, browser, SearXNG, Crawl4AI); local format conversion
has no independent URL-acquisition path. See [coverage and limits](../../docs/ADBLOCK.md).

## Evidence and controls

The retained list snapshot had **239,581 rules**, upstream version
`2026.1104.1610.37`, SHA-256
`19a3db5288c7067d81a641baac44a922303e7db570194f6949fbf04fce618e78`.
The GPL list itself is runtime-downloaded and is not bundled in this repository.
The original list header/source and complete upstream license are preserved in
its persistent cache. The [official license](https://github.com/hagezi/dns-blocklists/blob/main/LICENSE)
is attributed separately from Dethrottled's own code.

| Check | Observed result |
|---|---|
| Native non-network regression suite | 836 passed, 15 skipped, 2 network tests excluded on **each** architecture |
| Final focused regressions, including a subsequently added POST/invalid-target control | 40 passed on each native architecture; lighter x86 host environment also passed 39 with 1 optional curl-client skip |
| requests, curl_cffi and DDGS native acquisition | Both fixture facts retained in all 12 cases per setting/device; ON refused all three blocked redirects |
| Actual pinned SearXNG asynchronous curl client | Allowed fact read; blocked redirect before origin connection |
| Patchright and Crawl4AI, native x86_64 and ARM64 | All four fixture facts retained in all three repetitions per setting/backend/device |
| Patchright redirects, popup, WebSocket, dedicated worker and service-worker controls | Zero tracking-origin connections reached fixtures with ON; legitimate worker read, service-worker registration and download still worked |
| Existing public-target restriction | Localhost navigation still refused |
| Real list update | HTTP 200 followed by conditional 304; identical rules restored after restart |
| Cache/update failure regressions | Offline last-good retention, corrupt/truncated/unsupported download rejection, atomic activation failure, restart, background scheduling and disabled no-I/O checks passed |
| Isolated final Compose | All four components reported the same list hash; RFC rendered through stock Crawl4AI security proxy; policy block had no suggested bypass actions |
| Small live ON/OFF smoke | Both documentation fact anchors retained; Reddit `/drive` reported `content_observed` both ways |

This is not a large live-site compatibility study. The allowed challenge script
is a **local simulation**; preserving it does not prove that a real CAPTCHA will
pass. The Reddit observation is not a verified complete thread read. The older
OFF live search returned partial results while ON returned results; upstream
availability varied, so this is **not** attributed to filtering or claimed as a
ranking improvement. There is no claim of universal ad removal or zero breakage.

The ad-heavy fixture returned **157,127 → 1,447 origin response-body bytes** and
**11 → 0 tracking requests** per normal read: a **99.1%** body-byte reduction,
with **4/4 facts retained**. Bytes exclude HTTP/TLS overhead. This deliberately
ad-heavy synthetic page does not establish an average web-wide saving.

## RAM and CPU cost

Both devices used native Linux containers and software rendering. The x86_64
mini PC has a Ryzen 7 5800U (8 cores/16 threads, 32 GB RAM); the ARM64 edge device
has four Cortex-A78 plus four Cortex-A55 cores and 12 GB RAM. These are observed
test machines, not universal minimum specifications.

Fresh OFF/ON processes were used: OFF never parsed the list. Clean-page controls
retained the same four facts and **889 body bytes** in both settings. Two pairs
ran in opposite order (OFF→ON and ON→OFF), seven reads per setting/pair. CPU is
**total cgroup CPU time**, including Chromium children and Xvfb, not a CPU usage
percentage. Working set is `memory.current - inactive_file`; it includes browser
processes and active file cache, not just the Python interpreter.

| Resource | x86_64 | ARM64 |
|---|---:|---:|
| Rule-load anonymous RAM increment, per filter process | 22.7 MiB | 22.7 MiB |
| Initial parse CPU time, per process | 270 ms | 390 ms |
| Native Python peak-RSS increment while parsing | 31.2 MiB | 31.3 MiB |
| Clean browser median working set OFF → ON | 362.8 → 391.7 MiB | 369.2 → 395.2 MiB |
| Clean browser working-set difference | **+28.9 MiB** | **+26.0 MiB** |
| Clean page median CPU OFF → ON, n=14 each | 400.4 → 416.2 ms | 1227.7 → 1218.3 ms |
| Clean page median CPU difference | **+15.9 ms (+4.0%)** | **−9.4 ms (−0.8%)** |
| Clean page median elapsed time OFF → ON | 293.6 → 311.2 ms | 485.7 → 485.3 ms |
| Native domain-match loop ON, n=100,000 | 6.8 µs/check | 10.1 µs/check |

The browser RAM difference includes rule storage, the connection gate and
ordinary Chromium variation. It is not an additional 29 MiB on top of the
23 MiB rule cost in that same process. Four rule-owning processes imply roughly
**91 MiB for rule copies alone**; that is an arithmetic planning estimate, **not
a measured whole-stack increase**. Extra worker processes multiply rule storage.
Updates may temporarily hold old and new sets together and need additional RAM;
the 31 MiB initial-parse peak is not a guaranteed update/concurrency ceiling.

These short runs do not establish a statistically reliable ARM speedup. Host
background load and substantial pre-existing swap use were recorded; the first
pair overlapped other validation, while the reversed pair reduced that overlap.
Treat the small CPU/latency differences as workload observations, not hard bounds.
The ad-heavy page used less median page CPU with ON on both architectures, but
that includes avoided tracker work and does not negate the clean-page overhead.
No sustained-concurrency or web-wide memory/CPU ceiling is claimed. Background
maintenance sleeps between 30-second local observations and approximately daily
conditional updates; it does not continuously poll upstream.

[Resource summary](results/resource-summary.json) is replay-checked against the
raw runs; [validation metadata](results/validation.json) identifies source hashes,
images, hardware and suite outcomes. [SHA256SUMS](results/SHA256SUMS) covers the
retained observations, including failed and superseded pilots.

## Original failures and corrections

| Observation | Resolution / remaining limit |
|---|---|
| Initial CDN curl returned 403; guessed domain-only URL returned 404 | Use the requested anchored PRO list; real Python updater subsequently returned 200/304. Official raw mirror is a fallback for the same list. |
| Context routing let a redirected request reach the blocked host | Reject connection targets before DNS/dial through the final gate. |
| Popup, worker, service-worker and WebSocket interception gaps in earlier approaches | Final gate covers their HTTP(S)/WS(S) connections without disabling service workers or injecting JS. Preserved in `results/pilots/`. |
| Gate cleanup initially hung under Python 3.13 | Cancel active connections before awaiting closed server; cleanup regression passes. |
| Blocked fetch initially suggested browser recovery | Explicit `policy_blocked` workflow now has no next actions. |
| Fake disabled-client constructors broke old tests | Preserve disabled-path compatibility and forward requests exception types. |
| First renderer lab failed HSTS/TLS and counted script literals as facts | Add local TLS fixture; grade visible/cleaned content, not raw scripts. |
| Early SearXNG lab used wrong Python/missed its existing cooldown plugin | Run the image's real venv and mount both existing plugins. |
| First resource run could not write results as container user | Run disposable lab containers as root; production services remain unprivileged. |
| Initial extra invalid-target test used a syntactically allowed hostname | Correct the negative fixture to a disallowed userinfo target; implementation unchanged. |

The final policy intentionally allows acquisition until a valid list is available
and exposes that state. Unsupported custom SOCKS/HTTPS upstream proxy chains fail
explicitly. External unmodified renderers, arbitrary subprocesses, model/package
downloads, browser maintenance, WebRTC and other non-HTTP protocols are outside
coverage. First-party embedded advertising and legitimate content hosted on a
blocked domain cannot be distinguished by a domain-only list. These limitations
remain documented rather than hidden by automatic bypasses.

## Reproduce

From this candidate checkout, build disposable images (the API build may download
its existing embedding models). Do not use production project names or volumes:

```sh
docker build -t dethrottled:adblock-candidate .
docker build -t dethrottled-browser-search:adblock-candidate -f browser-search/Dockerfile .
# Download and retain the exact list/hash separately. The harness does not update it.
python evaluations/adblock/verify.py  # verify retained evidence first
bash evaluations/adblock/run-local.sh /absolute/path/to/pro-adblock.txt /tmp/new-adblock-run
```

`run-local.sh` uses `--network none`, disposable containers and in-process fixture
origins; no external site is contacted. Local DNS remapping and certificate
exceptions exist only in this lab. Containers run as root to write retained lab
outputs in a fresh directory; historical results are not overwritten. This is
not the production service configuration. It reruns the first
OFF→ON pair; use `browser.py --workload clean --repetitions 7 --enabled 1|0`
in reverse order for the second pair. The verifier expects both pairs plus the
integration/update records. It deliberately rejects changed source hashes: a
new experiment needs its own reviewed manifest, not overwritten historical proof.

Run targeted regressions with the installed native dependencies:

```sh
DETHROTTLED_ADBLOCK=0 PYTHONPATH=src pytest -q tests/test_adblock.py tests/test_adblock_gate.py
DETHROTTLED_ADBLOCK=0 PYTHONPATH=src pytest -q -m 'not network'
```

`updater.py --directory <private-cache> --output <result.json>` is an explicitly
online check; start with a fresh directory for a 200/304 pair. `searxng.py` tests
the pinned image's actual `AsyncClient` using its `/usr/local/searxng/.venv/bin/python`
and the Compose plugin mounts, with a cached list supplied as `/seed`.
`compose.py` is an opt-in, paced live smoke for an isolated project at port 18987;
run once per setting after recreating only that project. Its page text is reduced
to hashes, fact-anchor checks and diagnostics. Preserve negative outcomes; do not
use it as a search relevance benchmark.
