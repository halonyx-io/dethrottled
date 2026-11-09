# Phase 6 progress

2026-11-09. Phase 6 is in progress; production remains 1.7.1 and the local
Compose container was not modified.

## Frozen candidate

- Source commit `735d420`, tag `phase5-candidate-20261109`.
- Candidate worker image `dethrottled-dnb:1.8.0-candidate-20261109`
  (`sha256:c6633da3…`).
- Candidate API image `dethrottled-dnb-api:1.8.0-candidate-20261109`
  (`sha256:bb859007…`), built from `experiments/dnb/Dockerfile.api` over
  `dethrottled:1.7.1` with the frozen `src/`.
- Reference browser image `dethrottled-dnb-browser:reference`
  (`sha256:c1726a32…`).

## Completed smoke checks

### Browser parity (prep)
`compare.py`/`verify.py` against reference and candidate: both passed 27 facts,
all 27 drive actions, exact download, network fact, concurrency and checkpoint
restore. The 9 raw `compare` failures are 3 reference `/tiny` thin-content flags
and 6 expected `/missing` 404s.

### Candidate API smoke
The candidate API image started, `/health` returned 200, and a local PDF
`/fetch` succeeded through `direct/direct-native` with quality `ok` and 213
content characters.

### PDF concise parity
Same PDF, same `max_chars=300`:

| Side | Response bytes | Native tables | Table count |
|---|---:|---:|---:|
| reference 1.7.1 | 3,847 | 1 | absent |
| candidate 1.8.0 | 3,373 | 0 | 1 |

The content and tier match; the candidate's smaller response is the intentional
Phase 4 concise-table behavior. This is a deliberate presentation difference, not
a capability loss.

Evidence: [phase6-pdf-summary.json](phase6-pdf-summary.json),
[phase6-pdf-reference.json](phase6-pdf-reference.json),
[phase6-pdf-candidate.json](phase6-pdf-candidate.json).

## Optional-worker parity

The candidate API and reference 1.7.1 ran side by side on the production Docker
network with the existing `format-worker`, `media-worker` and `docling-worker`.
A local files container served generated PDF, DOCX, XLSX, PPTX and PNG files.

| File | Reference | Candidate | Fact |
|---|---|---|---|
| office.pdf | ok / 27 chars | ok / 27 chars | golf-904 |
| office.docx | ok / 33 chars | ok / 33 chars | delta-901 |
| office.xlsx | ok / 31 chars | ok / 31 chars | echo-902 |
| office.pptx | ok / 32 chars | ok / 32 chars | foxtrot-903 |
| office.png | ok / OCR warning | ok / OCR warning | hote-005 (both; OCR misread hotel-905) |
| table.pdf | 3,843 B | 3,622 B | candidate concise-table behavior |

Office facts, tier and quality match. The PNG OCR output is identical on both
sides but misreads the intended fact; the OCR warning is retained, so this is not
an OCR accuracy claim. Media playback and a layout-worker-specific document are
still to exercise.

Evidence: [phase6-optional-summary.json](phase6-optional-summary.json).

## Layout and mixed-batch parity

Both cores used the existing docling layout worker and served the same generated
files. `table.pdf` with `document_mode=layout` returned `parser=docling`, 158
characters and the same two inference warnings on both sides. A mixed four-file
batch (PDF, DOCX, XLSX, PPTX) returned the same quality, tier and character
counts on both sides.

Evidence: [phase6-layout-mixed.json](phase6-layout-mixed.json).

## ARM64

Built the reference browser and candidate on `q6a` (`aarch64`, Docker 29.9.3):

- reference `dethrottled-dnb-browser:reference`
  `sha256:b9e0fe2a…`
- candidate `dethrottled-dnb:1.8.0-candidate-arm64`
  `sha256:9fb7c41b…`

The candidate starts and serves `/health` with software `llvmpipe`
(`hardware_verified=false`, WebGL pixel correct) and a real `/crawl` retained
`cobalt-731`. The focused phase-1/2 tests pass **29/29** on ARM64.

Evidence: [phase6-arm64-summary.json](phase6-arm64-summary.json),
[phase6-arm64-health.json](phase6-arm64-health.json),
[phase6-arm64-tests.log](phase6-arm64-tests.log).

## HTML ceiling

A 13.7 MB HTML file exceeded the existing 8 MiB capture limit. Both reference
and candidate returned HTTP 200 with the same `html_capture_limit` warning,
300 content characters, and did not include the fact placed after the ceiling.
The warning is retained rather than presenting a truncated page as complete. This
confirms the candidate preserves the existing acquisition limit; it does not
silently widen it.

Evidence: [phase6-html-ceiling.json](phase6-html-ceiling.json).

## Media / speech parity

A 3.8-second public-domain-style spoken phrase fixture (the quick brown fox
sentence, Wikimedia Commons CC BY-SA 4.0, sha256 `aabe7ed8…`; not redistributed
here) was served from the local files container. Both cores sent the bytes to the
existing `media-worker` and returned exactly the same result:

- `quality=ok`, tier `direct/direct-native`
- language `en`, duration 3.812875 s, one segment `[0.000-3.840]`
- transcript "The quick brown fox jumps over the lazy dog."
- the speech-recognition uncertainty warning on both sides

The only difference was a one-byte JSON response length. Media transcription is
confirmed against the reference worker path; no media code changed in the
candidate.

Evidence: [phase6-media-summary.json](phase6-media-summary.json).

## Live and hostile parity

Live sources used the frozen five-URL protocol from
`docs/benchmarks/2026-11-01-recovery-next/live-protocol.json` (four hostile
sources plus the Python `sqlite3` control), with predefined lexical markers and
6-8 second pacing, two passes in reversed order. This is observational: upstream
responses and challenge state can change between requests.

| Case | Pass 1 reference | Pass 1 candidate | Pass 2 reference | Pass 2 candidate |
|---|---|---|---|---|
| cargurus | failed/tls | failed/tls | failed/tls | failed/tls |
| crunchbase | ok/tls, 664 chars, 1 marker | ok/headed read-plan, 3,000 chars, 2 markers | ok/tls, 664 chars, 1 marker | ok/tls, 664 chars, 1 marker |
| g2 | failed/headed | failed/headed | ok/headed-native, 3,000 chars, 2 markers | ok/headed-native, 3,000 chars, 2 markers |
| expedia | failed/tls | ok/headed read-plan, 773 chars, 2 markers | failed/tls | failed/tls |
| python-control | ok/direct, 3,000 chars, 2 markers | ok/direct, 3,000 chars, 2 markers | ok/direct, 3,000 chars, 2 markers | ok/direct, 3,000 chars, 2 markers |

The two pass-1 differences were single-observation upstream outcomes; both sides
reported the same failed or partial results when repeated. CarGurus and Expedia
remain failed in the repeated pass, so **no new hostile-source success is
claimed**. The Python control remained readable on both sides.

Controlled hostile sources through `/fetch` matched exactly on both sides:
redirect-to-article succeeded; cross-host redirect, private redirect and 404
failed safely with zero content; thin content was labelled `thin` with the
source-completeness warning; blocked resource, busy page and oversized page
returned the same direct result and warnings. No candidate silently widened an
allow-list or converted a failure into `ok`.

Evidence: [phase6-live-hostile.json](phase6-live-hostile.json).

## Packaging and install routes

Built a wheel and sdist from a clean `git archive` of the working commit (source
tree identical to the frozen candidate; docs/experiments only after it):

| Artifact | Size | SHA-256 |
|---|---:|---|
| `dethrottled-1.7.1-py3-none-any.whl` | 12,372,096 B | `2cbf5579…` |
| `dethrottled-1.7.1.tar.gz` | 12,375,796 B | `f5ed9aa2…` |

The wheel carries the inert deployment context (`_stack/context.tar.gz`, 974
files, manifest version and digest checked), both console entry points, the MIT
licence, and all extras. Installing the wheel, the sdist and the source tree
outside the checkout each produced a working `dethrottled` import, health
command and stack command. The packaged bundle extracted and validated under a
fresh `DETHROTTLED_STACK_HOME`, and `dethrottled stack status` reported the
expected services and `volumes_preserved_on_down=true`.

The public routes were also exercised in clean venvs: `pip install
dethrottled==1.7.1` from PyPI and `pip install
git+https://github.com/halonyx-io/dethrottled.git@v1.7.1` both installed and ran
the console commands.

**Version caveat.** The package metadata is still `1.7.1`. Bumping to 1.8.0 is
release-gated and was deliberately not performed, so these artifacts prove the
build/install route and bundle integrity, not the final release artifacts. The
wheel/sdist must be rebuilt after an approved version bump and the packaged
`_stack` manifest must match that version.

Evidence: [phase6-install.json](phase6-install.json).

## Mixed load, soak and crash containment

Three-minute mixed load through `dethrottled-dnb-api` and the candidate browser
service (concurrent fetch of HTML/PDF/DOCX/XLSX/PPTX/table plus browser drive):

| Side | Requests | Failures | Median |
|---|---:|---:|---:|
| reference 1.7.1 | 859 | 0 | 20 ms |
| candidate 1.8.0 | 829 | 0 | 20 ms |

Memory stayed flat in the mixed run: candidate API 229.6 -> 237.7 MiB and its
browser 470.7 -> 470.9 MiB; the reference API 237.7 -> 237.8 MiB and its browser
300.8 -> 325.6 MiB. The local files are extraction-bound, so this run does not
claim renderer throughput.

A ten-minute soak added browser drive on every fourth operation. Candidate API
memory was flat at ~238 MiB and its `/health` stayed 200 for the whole run. The
browser process stayed between ~495 and ~619 MiB and did not restart or OOM; that
is a bounded observation over ten minutes, not proof against a slow multi-hour
leak.

Crash containment was injected at 150 s of the five-minute soak by killing the
browser container for 25 seconds:

- 999/999 fetch requests succeeded throughout; direct extraction never depended
  on the browser.
- 33/333 drive requests failed explicitly with `Connection refused` only while
  the container was absent; none hung or returned fabricated content.
- The candidate API remained healthy (`/health` 200) throughout.
- After restarting the container, browser health returned in 4.3 s and drive
  requests resumed.

The failure is contained and visible rather than masked; a caller sees a real
error for the browser-only operation while the rest of the core stays usable.

## Rollback and volume preservation

A named `p6-rollback` volume was carried through reference -> candidate ->
reference and then candidate default-schema -> reference. A marker file written
by the first reference container survived every switch.

- With `DETHROTTLED_CORPUS_SCHEMA=1`, the candidate read the reference cache
  (`cached=true`) and the second reference read the cache again after rollback.
- With the candidate's default schema 2, it created `corpus-v2.sqlite` alongside
  the legacy `corpus.sqlite`; the legacy database was left intact, and reference
  1.7.1 read the schema-2 corpus after rollback.
- No test volume or container was left running; production stayed on 1.7.1.

Evidence: [phase6-load-crash-rollback.json](phase6-load-crash-rollback.json).

## Remaining Phase 6 work

All technical Phase 6 checks above are complete. The only remaining work is the
release gate, which requires explicit approval:

1. Decide and apply the 1.8.0 version bump.
2. Rebuild the wheel, sdist and container images from the approved commit.
3. Re-run the packaged bundle version/digest check and a final install smoke.
4. Publish only after approval; production remains on 1.7.1 until then.

## Resource note

The prep resource smoke showed the candidate at ~6.8–7.2 CPU-seconds per 10
renders versus ~2.4–2.8 for the reference, with similar latency. This is
consistent with the consolidated extraction workers; old pilot CPU figures do not
apply.
