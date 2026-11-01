# Dethrottled documentation

Use these pages to install Dethrottled, connect an agent and obtain inspectable
web evidence. They describe the current implementation on this branch. Runtime
capabilities are authoritative for an installation: optional workers, model
assets and public adapters may differ.

## Choose a starting point

| Your task | Start here | Continue with |
|---|---|---|
| Connect an agent | [Agent integration](AGENT-UPGRADES.md) | [MCP reference](MCP-REFERENCE.md), [public adapters](PUBLIC-ACCESS.md) |
| Read a source or file | [Reading and evidence](DEPENDABLE-WORKFLOWS.md) | [HTTP API](API.md), [browser operation](DRIVE.md) |
| Install or extend the stack | [Configuration](CONFIGURATION.md) | [Operations](OPERATIONS.md), [architecture](PIPELINE.md) |
| Call from application code | [HTTP API](API.md) | [Request reference](HTTP-REFERENCE.md), [Python API](PYTHON.md) |
| Assess capabilities and quality | [Feature inventory](FEATURES.md) | [Evidence and limits](EVIDENCE.md) |
| Print supplied HTML as PDF | [HTML-to-PDF worker](PDF_WORKER.md) | [Configuration](CONFIGURATION.md) |

## Understand the result

Search returns candidates, fetch returns extracted evidence, research assembles
sources, and drive operates a browser. None verifies that a proposition is true.
A normal read can be incomplete or irrelevant. Preserve provenance, warnings,
partial/truncation flags and continuation handles until the agent has enough
support for its answer.

The raw API is local and unauthenticated. REST/MCP adapters add public identity,
policy and shared admission; they are optional services, not built-in API
routes. Base Compose has four services. Optional profiles add speech, PDF layout,
broad-format parsing or public adapters.

## Current guides and historical evidence

Guides explain present behavior. [Evidence](EVIDENCE.md) indexes dated reports,
frozen protocols and raw results. Those reports retain the configuration and
limits observed at the time; their release-specific details are not setup
instructions for the latest code. The repository has no separate GitHub Pages
site configured; GitHub renders these Markdown pages directly.

[Documentation home](README.md) · [Agent guide](AGENT-UPGRADES.md) · [API](API.md) · [Evidence](EVIDENCE.md)
