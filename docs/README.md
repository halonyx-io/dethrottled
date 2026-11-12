# Dethrottled documentation

Use these pages to install Dethrottled, connect an agent and obtain inspectable
web evidence. They describe the current implementation on this branch. Runtime
capabilities are authoritative for an installation: optional workers, model
assets and public adapters may differ.

## Choose a starting point

| Your task | Start here | Continue with |
|---|---|---|
| First install or non-model application | [Quick start](QUICKSTART.md) | [Python](PYTHON.md), [HTTP API](API.md) |
| Connect an agent | [Client playbook](AGENT-PLAYBOOK.md), [agent skill](../SKILL-dethrottled.md) | [MCP reference](MCP-REFERENCE.md), [public adapters](PUBLIC-ACCESS.md) |
| Request broader coverage | [Limits and continuation](LIMITS.md) | [Agent integration](AGENT-UPGRADES.md) |
| Read a source or file | [Reading and evidence](DEPENDABLE-WORKFLOWS.md) | [HTTP API](API.md), [browser operation](DRIVE.md) |
| Understand automatic escalation | [Read planner](READ-PLANNER.md) | [Agent integration](AGENT-UPGRADES.md), [evidence](EVIDENCE.md) |
| Install or extend the stack | [Python and managed installation](PYTHON.md) | [Requirements](REQUIREMENTS.md), [configuration](CONFIGURATION.md) |
| Call from application code | [HTTP API](API.md) | [Request reference](HTTP-REFERENCE.md), [Python API](PYTHON.md) |
| Manage ad/tracker filtering | [Native adblock](ADBLOCK.md) | [Measurements](../evaluations/adblock/README.md) |
| Assess capabilities and quality | [Feature inventory](FEATURES.md) | [Evidence and limits](EVIDENCE.md) |
| Print supplied HTML as PDF | [HTML-to-PDF worker](PDF_WORKER.md) | [Configuration](CONFIGURATION.md) |
| Reuse shared public evidence | [Corpus v2](CORPUS.md) | [Measured comparison](../evaluations/corpus-v2/results/2026-11-05/REPORT.md), [client playbook](AGENT-PLAYBOOK.md) |

## Contribute and maintain

Read [repository instructions](../AGENTS.md), [documentation maintenance](DOCUMENTATION-MAINTENANCE.md)
and the [tracked inventory](DOCUMENTATION-INVENTORY.md) before changing behaviour or published claims.
The [integration details](AGENT-UPGRADES.md) complement the client playbook.

## Understand the result

Search returns candidates, fetch returns extracted evidence, research assembles
sources, and drive operates a browser. None verifies that a proposition is true.
A normal read can be incomplete or irrelevant. Preserve provenance, warnings,
partial/truncation flags and continuation handles until the agent has enough
support for its answer.

The raw API is local and unauthenticated. REST/MCP adapters add public identity,
policy and shared admission; they are optional services, not built-in API
routes. Base Compose includes the API, DNB, SearXNG and the format reader. Speech and
PDF layout use automatically connected profiles; public adapters use an overlay.

The [current two-device evaluation](BENCHMARKS.md) records installation and workload measurements.
The [1.0 release gates](ONE-ZERO.md) explain measured capabilities, portability
checks and remaining limits.

## Current guides and historical evidence

Guides explain present behavior. [Evidence](EVIDENCE.md) indexes dated reports,
frozen protocols and raw results. Those reports retain the configuration and
limits observed at the time; their release-specific details are not setup
instructions for the latest code. The repository has no separate GitHub Pages
site configured; GitHub renders these Markdown pages directly.

[Documentation home](README.md) · [Agent guide](AGENT-UPGRADES.md) · [API](API.md) · [Evidence](EVIDENCE.md)

Read [Corpus v2](CORPUS.md) for visibility,
coverage, resource bounds, migration, and rollback.
