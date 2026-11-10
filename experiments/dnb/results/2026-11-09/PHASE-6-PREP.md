# Phase 6 preparation

2026-11-09. This is prep work only; Phase 6 execution has not started. The
production Compose stack was not modified; `dethrottled-dethrottled-1` stayed
healthy on 1.7.1 throughout.

## Frozen candidate

- Source commit: `735d420dd00d76bd0d5f198b0266fca05938f038`
  (`Freeze 1.8.0 DNB candidate after phase 5`).
- Local tag: `phase5-candidate-20261109`.
- Reference image: `dethrottled-dnb-browser:reference`
  `sha256:c1726a324dbab92a632425108a58da4803e93af44eb44fac7379b6fea227801c`.
- Candidate image: `dethrottled-dnb:1.8.0-candidate-20261109`
  `sha256:c6633da36d6be3d20d808e034a469398a686c804ec9f9c8d72ee7e836124bf23`.
- The candidate was built from the frozen reference browser image, not from the
  Phase 3 intermediate image.

## Parity smoke

A disposable copy of the DNB Compose lab used the frozen candidate on port
19983, reference browser on 19981, reference renderer on 19982 and the fixture
on 8090. No production container or volume was used.

- `compare.py`: 30 renders, 9 raw failures. The 9 are 3 reference `/tiny`
  results with the thin-content `success=false` flag (facts still present), plus
  3 reference and 3 candidate `/missing` 404s. These are retained, not filtered.
- `verify.py`: **both reference and candidate passed** 27 facts, all 27 drive
  actions, exact download bytes, network fact, concurrent operation and
  checkpoint restore across a real restart.
- Median render latency: reference 636 ms, candidate 641 ms.

Evidence: [parity-summary.json](PHASE-6-PREP/parity-summary.json),
[parity-verification.json](PHASE-6-PREP/parity-verification.json),
[checkpoint-reference.json](PHASE-6-PREP/checkpoint-reference.json),
[checkpoint-candidate.json](PHASE-6-PREP/checkpoint-candidate.json).

## Resource smoke

10 sequential `/long`/`/article` renders, three alternating phases:

- reference: ~2.43-2.84 CPU-seconds per phase.
- candidate: ~6.83-7.22 CPU-seconds per phase.
- latency: ~8.08-8.32 s per 10 renders on both sides.

The candidate uses more CPU, consistent with the consolidated extraction
workers; the old pilot CPU figures must not be presented as this candidate's
measurement. Evidence: [resource-smoke.json](PHASE-6-PREP/resource-smoke.json).

## ARM64 prep

- `q6a` is reachable, `aarch64`, Docker 29.9.3.
- It has no candidate or reference images yet.
- Next prep step is to build the reference browser and candidate on q6a (or via
  buildx with a verified arm64 reference), then run the same parity/resource
  checks there.

## Remaining Phase 6 work

1. Freeze/package version `1.8.0`; no release without approval.
2. PDF/OCR/Office/media/layout coverage, mixed batches and the 8 MiB HTML
   ceiling reconciliation.
3. Paced live/hostile-source comparison with predefined facts.
4. ARM64 build/parity/resource run on q6a.
5. PyPI/GitHub installation route outside the source checkout.
6. Mixed-load, long-running memory and crash-containment checks.
7. Rollback/volume-preservation verification and release artifacts.

## Commands used

```sh
git add -A && git commit -m 'Freeze 1.8.0 DNB candidate after phase 5'
git tag -a phase5-candidate-20261109 -m 'DNB 1.8.0 candidate after Phase 5'
docker build -f experiments/dnb/Dockerfile -t dethrottled-dnb:1.8.0-candidate-20261109 .
# Disposable copy of experiments/dnb with compose.yml candidate image changed
docker compose -f /tmp/opencode/p6/dnb/compose.yml up -d --wait
python compare.py /tmp/opencode/p6/out-frozen
python verify.py /tmp/opencode/p6/out-frozen
python measure.py /tmp/opencode/p6/resources.json
docker compose -f /tmp/opencode/p6/dnb/compose.yml down --remove-orphans
```
