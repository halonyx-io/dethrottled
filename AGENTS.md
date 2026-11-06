# Working on Dethrottled

These instructions are for agents changing this repository. For using the engine
as a client, start with [SKILL-dethrottled.md](SKILL-dethrottled.md) and
[the client playbook](docs/AGENT-PLAYBOOK.md). The user's
current instructions determine task scope; this file supplies repository defaults.

## Establish the actual state

- Read `git status`, applicable local instructions and the relevant implementation
  before editing. Preserve unrelated/untracked user work.
- Distinguish checkout/package version, running API version, adapter application
  version and MCP SDK version. Check live capabilities/readiness when working on
  a deployment; matching version labels alone do not prove matching source.
- Use `docs/HTTP-REFERENCE.md` and `docs/MCP-REFERENCE.md` for static contracts;
  connected OpenAPI and MCP `tools/list` are authoritative for a running instance.
- For a question about configuration, inspect source, Compose interpolation and
  the selected deployment. Do not assume a documented default overrides an operator.

## Preserve the engine's operating policy

- Default content acquisition stays self-hosted and keyless. Optional integrations
  must remain explicit. Do not introduce a compulsory account, model API or paid
  dependency, or reintroduce a removed hosted-reader fallback.
- Discovery is a compact source menu: ten DDG-family choices, up to three per
  supplementary engine, six supplements total, fifteen unique URLs overall.
  DDG acquisition alternatives are one family, not independent agreement votes.
- Research uses the same search policy and its own shared candidate/source bounds.
  Prefer useful coverage and evidence accuracy over speculative efficiency gains.
  Changing ceilings or ranking policy requires an explicit rationale and evaluation.
- HTTP success, a completed browser step and readable text are separate outcomes.
  Preserve failed/thin/suspect results, warnings, provenance, partial/truncated state,
  retained-document handles and continuation instructions.
- Keep request and transport differences deliberate. New REST fields do not
  automatically become MCP arguments. Update adapter validation, namespaces and
  contracts when exposing a capability remotely.
- Corpus v2 shares only explicitly eligible public evidence. Keep its 90-day
  passage/vector lifetime separate from search, extraction and document caches.
  Standard support checks are not answer verification; preserve the warned broad
  path for additional multilingual/paraphrase candidates and report its tradeoffs.
- Browser interaction may have side effects. Respect caller scope, public-target
  checks, explicit render/OCR restrictions and operation-id retry semantics.

## Change and verify

- Read [documentation maintenance](docs/DOCUMENTATION-MAINTENANCE.md). Use its
  change-impact matrix rather than editing only the page nearest the changed code.
- Regenerate generated references after contract changes; do not hand-edit them.
- Keep helpers/state ownership coherent. Preserve supported imports and existing
  callers unless the requested change intentionally removes a capability.
- Use meaningful focused tests, then required checks. Run neither live-provider
  stress tests nor repeated broad suites without a reason. Retain original failures
  and negative results; do not rewrite evidence to make a change look successful.
- Distinguish a code cleanup, measured helper improvement, end-to-end latency gain
  and retrieval-quality gain. Claim only what the retained measurements establish.
- Keep credentials, browser storage, private hostnames and private infrastructure
  out of committed docs, fixtures and published artifacts. Use architecture/device
  descriptions and measured specifications for public hardware comparisons.

## Documentation and delivery

- Every tracked documentation file must appear in the inventory with a lifecycle.
  Current guides describe present behaviour; dated evidence records an observation.
  Do not replace historical version numbers with today's version indiscriminately.
- Update README/navigation, client instructions, configuration, public access,
  generated references and module/CLI descriptions when the change affects them.
- Publishing/deploying requires the user's authorization; do not ask again when it
  is already provided. Prepare and verify the concrete result before approval gates.
- Never overwrite a published package version or retag an existing release. Follow
  `docs/OPERATIONS.md` for exact-version CI, publication, artifact hashes and rollout.
- After an authorized rollout, verify actual PyPI artifacts and the live API/MCP
  backend identity; preserve volumes and retain rollback material.
