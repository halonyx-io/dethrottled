# Preparing Dethrottled 1.0

The 1.0 candidate aims to give an agent one dependable path from a question to
inspectable web evidence, with browser control when ordinary reading is
insufficient. Defaults should work without keys or a host-specific setup file.
Automatic discovery removes redundant configuration; resource-intensive inference
and authenticated public access still require an explicit deployment choice.

This checkout prepares **1.0.0rc1**. It is an unpublished candidate. The currently
published/deployed release remains 0.10.1. Local measurements are described below;
new native CI and promotion verification are still required before a 1.0 release.

## Default use

```sh
docker compose up -d --build
```

The API, headed browser, SearXNG, Crawl4AI and MSG/XLSB reader start together.
Native document parsing, OCR and corpus weights are included. GPU access and a
`.env` file are unnecessary. The default browser supports software WebGL; its
actual graphics status is observable. On compatible native Linux hosts,
`scripts/compose-auto.sh` can select GPU access automatically. Remote Docker
contexts and Docker Desktop should keep the portable software path unless
compatible hardware access is explicitly configured and verified.

For local speech and PDF layout inference:

```sh
docker compose --profile full up -d --build
```

Either worker can be selected individually with `media` or `layout`. Starting the
service is sufficient: the API discovers its fixed Compose address, including a
profile started after the API. First use downloads and caches model weights; no
key is needed. Explicit custom endpoints take precedence, and `off` disables an
individual reader. Inference stays optional because memory requirements and
initial downloads are substantially larger than ordinary source reading.

## What the gates establish

| Gate | Required evidence | Candidate finding |
|---|---|---|
| Autonomous reading | Predefined facts recovered through normal fetch; manual/OCR/render policies and caller boundaries respected | Fresh default-stack recovery and negative contracts pass locally |
| Blocked-source handling | Paired source observations, retained failures, native controls and bounded work | Reddit succeeds on software and GPU in repeated fresh sessions; Crunchbase/G2 remain blocked |
| Extraction fidelity | Task facts, ranges, pollution diagnostics and provenance assessed independently | 22 parser cases pass; 8/8 known pollution cases surfaced, 0/10 negative cases flagged, 18/18 facts retained |
| Portable deployment | Empty environment file, fresh volumes, no GPU, actual parsing/browser operation and restart | Local native AMD64 default stack passes; updated native ARM64/AMD64 CI is prepared but not yet run remotely |
| Optional resources | One explicit profile choice, automatic connection, truthful cold-start status and safe fallback | Speech first-use download/transcription succeeds; layout preserves facts and adopts a complete model result after correcting a duplicate-length check |
| Agent/docs contract | Actual MCP schemas and instructions agree, tool calls work, caller isolation holds, packaged docs match | Cold conversation found and led to a fix for three missing MCP actions; final transport/model and documentation evidence is recorded with the candidate |

These gates do not establish complete-source access, semantic answer correctness,
performance on every machine, or superiority to paid web engines. Linux images on
native AMD64/ARM64 and Docker Desktop itself are different test targets. Native
ARM64 CI must pass for this candidate; the prior release's passing builds do not
substitute for that run. Windows/macOS Docker Desktop hardware behavior is not
certified by Linux CI.

## Changes backed by observations

Optional worker configuration previously needed both a profile and a URL. Compose
now discovers started workers, while source installs retain explicit setup. The
broad-format reader is a default service; actual MSG/XLSB reads establish the
additional default coverage. Its observed idle memory on this host was about
34 MiB; this is not its conversion peak or a minimum host-memory guarantee.

MCP's old action enumeration omitted `read_state`, `scroll` and `expand_details`
even though instructions advertised them. The candidate exposes all browser
actions and tests schema parity. Checkpoint capture retries read-only navigation
races without repeating a click. A layout length guard now compares the model
with original native text, avoiding a second count of appended native table text;
number retention and table-count checks remain in force.

The pollution detector recognizes two previously missed retry banners. This
improves the known regression set, not an independent population accuracy score.
Quoted/code/structured examples are still protected, and useful content is retained.

Crawl4AI 0.9.5 replaces the prior renderer after paired selector/wait/error
checks. A quoted CSS extraction that returned whitespace now retains its known
fact, and untrusted JavaScript waits are refused. The Docker API runtime package
versions are pinned separately from source-install compatibility ranges; the
offline verifier checks those pins and the baked model assets.

The [release harness](../evaluations/release/README.md) defines how to reproduce
the gates. The [candidate report](../evaluations/release/results/2026-11-02/REPORT.md) records
timings, failed pilots, raw summaries,
model-test limits and remaining promotion work. No paid-service or universal
anti-bot superiority claim is justified by these observations.

[Documentation home](README.md) · [Configuration](CONFIGURATION.md) · [Evidence](EVIDENCE.md)
