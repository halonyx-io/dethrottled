# 0.9.1 recovery evidence

Baseline: commit `13ec0aa` / 0.9.0. See [findings and limits](../../RECOVERY-GAPS.md).
`summary.json` indexes results. Raw JSON retains failures as well as successes.

`fixture_initial.py` is the initial reader-only experiment: `/slow` embeds static
text before a blocking script. `fixture.py` is the stronger final fixture: `/slow`
generates the report in JavaScript, and `/webgl` requires an actual red-pixel
readback before revealing the report. Serve one fixture version at a time on port
19890 with Docker name `dethrottled-recovery-fixture` on an isolated test network.
Use the initial version for `*-reader.json` and the final version for
`*-end-to-end.json`, `*-default-workflow.json` and `api-candidate.json`.

`reader_probe.py` imports the core, calls the headed tier and submits six parallel
reads. Mount this directory writable at `/evidence`, set `LABEL=baseline` or
`candidate` and `DETHROTTLED_BROWSER_SEARCH_URL` to that build's isolated worker.
Baseline uses 0.9.0; candidate uses reviewed source/package 0.9.1. Use separate
browser state per build. Keep Crawl4AI unconfigured in the core harnesses to
isolate headed behavior; the full production service retains it.
`end_to_end_probe.py` explicitly enables headed fallback; `default_probe.py` does
not. Both use the full core acquisition function, not a fabricated extractor.

Serve `clearance_fixture.py` on a separate test container with aliases
`dethrottled-findings-fixture` and `dethrottled-findings-frame` for the retained
`controlled_probe.py`. That checks delayed clearance, same-caller reuse,
separate-caller state and plain direct acquisition. No private-address policy
exceptions or fixture code are included in production images.

For GPU experiments, run `gpu_probe.py` inside a headed worker with DISPLAY=:99.
`gpu-hardware.json` grants `/dev/dri/renderD128` and its host render group only in
the experiment; `gpu-mesa.json` does not. The working Mesa renderer is software,
not proof of hardware acceleration. `Dockerfile.runtime-browser` adds only EGL
and GLES runtime libraries; the initial experiment also had mesa-utils, which is
not needed or shipped. Production Compose enables the measured Mesa profile.
The profile can be disabled with `DETHROTTLED_BROWSER_GRAPHICS=default`.

`live_probe.py` expects old/new isolated workers on loopback 18413/18412. It
records three searches and selected Sannysoft checks. Full fingerprint HTML is
not published. `hostile_probe.py` imports the core and reads the frozen five-URL
protocol through each headed worker with public target restrictions enabled.
`profile_probe.py` runs persistent Chromium and Chrome independently, with real
browser state in temporary directories. Its Chrome image is experimental only.
A nonempty body or matching term alone does not establish a verified answer;
`readable_candidate` is a retrieval screen, and every hostile case fails it.

`api_probe.py` checks the candidate API on loopback 18415 against final fixtures:
automatic default reads and partial-source workflow. The API intentionally reports
composite tier/extractor names. `baseline-operation.json` and
`candidate-operation.json` compare actual worker operation fingerprints to guard
pre-upgrade idempotency compatibility.

Published logs normalize trailing whitespace. Initial readiness, permission and
harness-assertion mistakes remain in the local work logs and are described in the
report; their incomplete results are not counted as improvements. The final
production checks run through the existing public HTTPS MCP/REST gateway. They
record no bearer tokens, cookie jars, full profiles or private checkpoint data.
