# Keeping the documentation correct

A change is ready when a user can follow the current guides and get the described
behaviour from the intended installation. Passing a Markdown link check alone
cannot establish that. This guide defines the review surfaces and evidence needed.

## Authority and lifecycle

| Material | Authority | Maintenance rule |
|---|---|---|
| Running HTTP/MCP contracts | Connected OpenAPI, `tools/list`, initialization and capabilities | Verify the installation actually reached; optional workers/configuration can differ |
| Source contracts | API models/routes, adapter signatures/validation, workflow policy and worker actions | Change implementation and exposed interfaces together |
| Generated HTTP/MCP references | `scripts/docs_reference.py` | Regenerate from source; never edit tables by hand |
| Current guides and contributor instructions | README, AGENTS, current `docs/` guides | Reconcile with source and a runnable example when behaviour changes |
| Harness instructions | Evaluation READMEs | Keep commands usable; label configuration/date assumptions |
| Dated reports, results and raw failures | Frozen observations plus their protocol | Preserve observed versions/results; append explicit editorial notes if corrected |
| Third-party licenses/notices | Original attribution | Preserve unless the corresponding material is removed |

The [generated inventory](DOCUMENTATION-INVENTORY.md) lists every tracked Markdown,
reStructuredText, MDX, AsciiDoc and text document, plus visual and contract surfaces.
Its [JSON companion](documentation-inventory.json) is machine-readable. Adding a
file without an assigned lifecycle must fail the inventory check. Generated
inventories record file coverage, not proof that every sentence is true.

Untracked user attachments and private reports are not repository documentation.
Do not commit them merely to satisfy inventory coverage. Review a newly adopted
report explicitly before adding it to Git or a packaged deployment context.

## Change-impact matrix

| What changed | Source/contract surfaces | Read and reconcile |
|---|---|---|
| HTTP route, field, type, default or validation | `api_models.py`, `server.py`, OpenAPI, REST allowlists | API, HTTP reference, limits, client playbook, agent guide, quick start examples |
| MCP tool/argument/result/image handling | `adapters/mcp_server.py`, SDK lock, adapter verifier | MCP reference, public access, client playbook, workflow and client integration |
| Agent workflow or automatic recovery | `workflow.py`, read planner, fetch, browser recovery | Agent guide/playbook, read planner, pipeline, drive, reading/evidence and capability descriptions |
| Search providers, profiles, caps or ranking | search/discovery/rank, workflow limits, SearXNG settings | API, limits, agent playbook, pipeline, configuration, README claims and ranking evidence |
| File readers, OCR, tables, retained documents | document parsers, evidence, OCR, format/layout/media workers | Reading/evidence, features, API/MCP references, worker setup and format limitations |
| Browser actions, sessions, downloads or checkpoints | browser service/recovery, Drive models, adapter policy | Drive, client playbook, agent integration, public access and browser examples |
| Authentication, scope, admission, namespaces or proxy | shared access, public adapters, agents overlay, dependency lock | Public access, operations, limits, client transport examples and deployment probes |
| Configuration, defaults or worker dependencies | Compose/overlays, Dockerfiles, env examples, stack CLI, locks | Configuration, Python/quick start, requirements, profiles graphic and operations |
| Package/CLI/installation | CLI/stack, setup/manifest, project metadata, release workflow | Quick start, Python, README, requirements, operations and package metadata |
| Version or release | Package metadata, runtime version, Compose/example user agent | Current version statements, adapter companion identity and release notes; leave dated evidence dated |
| Architecture, hardware or performance claim | Retained protocol/results and chart generator/source | README, evidence/benchmarks, requirements and SVG labels/units/sample sizes |
| Feature removal | Every caller, flag/env mapping, probe, test, script, package context | All current guides, diagrams, references and historical editorial policy; scan actual built artifacts |

The root `SKILL-dethrottled.md` is the agent client entrypoint. Reconcile its workflow when
controls change and keep its linked references packaged; `check_agent_docs.py`
checks that all MCP tools remain discoverable there.

Module and function docstrings are documentation too. Inspect opening summaries,
CLI help, comments claiming defaults, route counts and compatibility aliases.
Prefer descriptions such as “common routes” over counts that will silently drift.
Do not equate the application version with the independently pinned MCP SDK.

## Working checklist

1. State the intended behaviour, affected transports and scope. Read the relevant
   inventory entries and implementation; record the checkout/runtime versions.
2. Compare implementation, defaults, advertised capabilities, return metadata and
   agent workflow. Decide whether the change is compatible or an intentional removal.
3. Update current guides and navigation. Keep one canonical detailed parameter table
   in generated references; examples/playbooks explain selection and consequences.
4. Regenerate references and the inventory. New docs need a lifecycle/owner in the
   inventory rules. Add newly maintained executable guides to `check_docs.py`'s
   guide set. Markdown link coverage comes from the inventory, including root and
   contributor files; packaged checks cover the files present in that distribution.
5. Check links/fragments, shell/Python/JSON example syntax and parameter schemas.
   Exercise changed examples against controlled fixtures or a disposable instance.
   A syntax check alone does not prove an installation command or live fetch works.
6. Run relevant tests and required CI. Real worker/transport changes need the native
   gates; document optional/model-dependent skips. Keep credentials out of outputs.
7. For an authorized release, use the release checklist below. Record original
   failures, fixes, retries and negative outcomes before declaring completion.

## Commands in a prepared development environment

```sh
python scripts/docs_reference.py
python scripts/docs_reference.py --check
python scripts/check_agent_docs.py
python scripts/documentation_inventory.py
python scripts/documentation_inventory.py --check
python scripts/check_docs.py
ruff check --no-cache .
pytest -q -m 'not network'
```

`documentation_inventory.py` reads tracked files (including newly staged files).
Stage new documentation before regenerating the inventory. Commit the generated
Markdown/JSON outputs together. A clean CI checkout should reproduce them exactly.
The non-network suite is a regression gate, not a reason to run it repeatedly after
pure prose changes; use the checks justified by the affected implementation.

## Release and rollout checklist

- Use a new unpublished version for runtime/CLI removals or changes that need a
  distinguishable delivered identity. Do not overwrite old wheels, source archives
  or tags. A current-guide correction can land on main without another deployment.
- Synchronize package/runtime metadata, current checkout wording, Compose/example
  user agent and adapter version modules. Do not bump the SDK because the app bumped.
- Require exact-version native CI and build/import checks. Compare merge-tree
  content with the tested candidate before tagging.
- Verify the actual PyPI wheel/source hashes, metadata and managed deployment
  context. A successful GitHub release page is not proof of PyPI publication.
- Exercise a fresh install outside the checkout. Separate core/optional Python
  capabilities from Docker worker availability and model initialization.
- For deployment, preserve data/model volumes, back up mutable state and retain
  rollback images. Verify running source and API/MCP backend identity afterward.
- Test public proxy routing/auth rejection and the affected authenticated workflow
  where credentials are authorized and available. State what was actually tested.
- Registry file-bind replacements may require adapter recreation; follow the
  current public-access guide. Reconnect clients that cache old tool descriptions.
- Publish sanitized verification records. Note publication/index propagation delays
  as observations, with paced retries; never overwrite the original failure record.

## Historical evidence and version checks

Old versions in dated reports and pinned dependency versions are legitimate. Flag
outdated *current-behaviour claims*, not every older-looking number. Keep benchmark
scope, device architecture/specifications, failure counts and source hashes attached
to numeric claims. A versionless chart URL is not a claim that its data is new.

When a user requests removal from distributed history, archive originals outside
the public tree, identify editorial omissions and preserve unrelated results.
Never silently fabricate a fresh experiment or rewrite an observation as a success.
Git history and previously published immutable distributions are separate artifacts.

The agent-doc check catches missing route/tool/action/field names in the playbook;
it cannot establish that the prose explains their semantics correctly.
The inventory guard prevents missing files; source-derived references prevent
parameter-table drift; controlled examples and review catch semantic drift. None
replaces the others.

## 1.6.1 completed work

Checked items are included in 1.6.1. The dated investigations retain their
original candidate observations; final publication checks belong to the release. See the [retained investigation](../evaluations/retrieval-review/results/2026-11-06/REPORT.md).

- [x] Improve corpus discovery in `GET /v2/capabilities`. Preserve the existing
  endpoint fields and add explicit HTTP methods, required query parameters and
  a runnable example for `GET /corpus/search?q=...`; identify `GET /corpus/stats`
  as the statistics route. Make the REST `q` versus MCP `query` distinction clear.
  Add a focused regression test for the advertised contract and exercise the
  example against the route. Reconcile the API guide, agent playbook and generated
  references as needed. Keep current response shapes and retrieval behaviour.
  Raised by post-release 1.6.0 agent testing on 2026-11-06.

- [x] Investigate whether corpus responses and agent instructions clearly distinguish
  retrieved semantic candidates from evidence supporting the requested facts.
  Trigger: `land patent` returned six standard semantic/hybrid candidates but zero
  lexical hits; a contemporaneous database check found no passage containing
  `patent`. This observation establishes neither answer coverage nor a general
  retrieval defect. Evaluate known-answer, related-but-insufficient, absent-answer
  and useful-paraphrase cases across standard/broad support and lexical/semantic/
  hybrid modes. Inspect existing provenance, warnings and answer-support labels
  before proposing minimal, backward-compatible diagnostic or instruction changes.
  Do not require literal query words or change ranking/filtering without evidence.
  Retain per-case results and verify that useful paraphrases remain discoverable.
  Raised by post-release 1.6.0 agent testing on 2026-11-06.

- [x] Review unchanged blocklist refreshes and active stream policy. Reuse validated
  equal-content rules; preserve check/update semantics and protect metadata.
  Keep admitted streams alive while checking new connections. Retain local
  transfer/update evidence and document the TLS connection-reuse limitation.
- [x] Correlate MCP admission refusals with JSON-RPC IDs and bounded request reads;
  preserve REST/auth/transport retry contracts. Verify actual adapter integration.
- [x] Extend required-parameter discovery across core HTTP routes from OpenAPI;
  test crawl thin-navigation discovery, explicit no-`ok` outcomes and multi-URL
  job progress. Preserve original quality, failure and scope policy.

The [post-1.6.0 report](../evaluations/post160-review/results/2026-11-06/REPORT.md)
records cumulative changes and deliberately unchanged network/admission policies.
Release gates include native AMD64/ARM64 CI and final package/deployment verification;
see the [1.6.1 release](https://github.com/halonyx-io/dethrottled/releases/tag/v1.6.1).
