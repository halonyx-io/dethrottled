# Working on dethrottled

This file is for anyone changing this repository, human or AI. To *use* the
engine from an agent, read [SKILL-dethrottled.md](SKILL-dethrottled.md) and the
[client playbook](docs/AGENT-PLAYBOOK.md) instead. The person you are working
for sets the task; this file sets the house rules.

## What lives where

| Path | What it is |
|---|---|
| `src/dethrottled/server.py` | The FastAPI app: every route, request shaping and response assembly |
| `src/dethrottled/fetch.py` | The acquisition ladder (direct, TLS, render, headed), tier resting and caching |
| `src/dethrottled/extract.py` | HTML extraction: extractor choice, completeness checks, page metadata and dates |
| `src/dethrottled/readplan.py` | Automatic browser recovery for incomplete reads |
| `src/dethrottled/search.py`, `discovery.py`, `rank.py`, `rerank.py` | Discovery: providers, merging, ranking and the local reranker |
| `src/dethrottled/dedupe.py`, `urls.py` | Shared URL and content identity, and duplicate merging |
| `src/dethrottled/signals.py` | Dates, source and page types, fetch relevance |
| `src/dethrottled/research.py` | Bounded evidence bundles |
| `src/dethrottled/corpus*.py` | Corpus v2: storage, indexing, retrieval and support checks |
| `src/dethrottled/dpr*.py`, `jobs.py` | Durable batch reads and fetch jobs |
| `browser-search/service.py` | Browser worker: search, `/drive` actions and settling |
| `experiments/dnb/` | DNB: the production browser service (rendering, scope, delegation) |
| `adapters/` | Authenticated MCP server and REST gateway |
| `docker-compose*.yml` | The default stack and optional overlays |
| `evaluations/` | Dated measurements, release gates and their fixtures |
| `docs/` | Current guides, generated references and the documentation inventory |

## Ground rules

- **Find out what is actually there first.** Read `git status`, local
  instructions and the code you will touch. Leave unrelated and untracked work
  alone. A checkout, an installed package, a running API and an adapter can each
  be a different version; check `/health` and `/v2/capabilities` on a running
  service before reasoning about it.
- **Keyless stays keyless.** The default stack must work with no account, API
  key, model API or paid service. Optional providers stay explicit opt-ins. Do
  not reintroduce a hosted-reader fallback.
- **Search is a compact menu.** Ten DDG-family choices, at most three per
  supplementary engine and six supplements in total, fifteen unique URLs. DDG
  transports are one provider family, not independent votes. Changing these
  bounds or the ranking policy needs a stated reason and a measurement.
- **Never turn a failure into a success.** HTTP 200, a completed browser step
  and readable text are three different things. Keep failed, thin and suspect
  outcomes, warnings, provenance, partial and truncated flags, document handles
  and continuation steps intact.
- **Per-host problems stay per-host.** One site's 403, challenge or timeout must
  not disable a tier for other sites. Only a shared service that is itself busy
  or unreachable may be rested (see `_RESTABLE_TIERS` and `_service_refusal` in
  `fetch.py`).
- **Transports differ on purpose.** A new REST field is not automatically an MCP
  argument. When exposing something remotely, update adapter validation,
  namespaces and contracts together.
- **Corpus sharing is narrow.** Only explicitly eligible public evidence enters
  Corpus v2, for 90 days, separate from search, extraction and document caches.
  Its support checks are not answer verification.
- **Browser actions have side effects.** Respect caller scope, public-target
  checks, render and OCR restrictions and operation-ID retry semantics.
- **Check a dependency's licence before adding it.** The package's required
  dependencies stay permissive. Anything copyleft, or anything with an
  attribution clause, goes into [THIRD-PARTY-NOTICES.md](THIRD-PARTY-NOTICES.md)
  in the same change; `scripts/license_inventory.py` lists what the built
  images actually contain.
- **No private infrastructure in the tree.** No credentials, browser storage,
  private hostnames or private addresses in code, tests, fixtures or docs. CI
  rejects private IPv4 addresses anywhere in the tree, tests included (see the
  `no-secrets` job); use a name such as `intranet.lan` instead. Describe hardware by architecture and measured specification.

## Verify a change

Run focused tests while you work, then the full set before you call it done.

```sh
python -m pytest -q -m "not network"
ruff check .
python scripts/docs_reference.py --check
python scripts/documentation_inventory.py --check
python scripts/check_agent_docs.py
python scripts/check_docs.py
python evaluations/corpus-v2/verify.py
python evaluations/search-policy/verify.py
```

The DNB and browser-worker tests need the DNB image's dependencies:

```sh
docker build -f browser-search/Dockerfile --target dnb -t dethrottled-dnb:dev .
docker run --rm -v "$PWD:/repo:ro" --entrypoint sh dethrottled-dnb:dev -c \
  'cp -r /app /tmp/w && cp /repo/experiments/dnb/*.py /repo/browser-search/*.py /tmp/w/ &&
   cd /tmp/w && pip install -q --target /tmp/p pytest &&
   PYTHONPATH=/tmp/p:/tmp/w:/repo/src python -m pytest -q test_*.py'
```

Changes to fetching, rendering, recovery or the browser should also pass the
release gates, which CI runs on AMD64 and ARM64. They start a throwaway stack
under a random project name and remove it afterwards:

```sh
python3 evaluations/release/compose-check.py --out /tmp/release-gates
```

Things that catch people out:

- `check_docs.py` validates every `curl` body in the guides against the real
  request models, and requires the README's `This checkout is **X**` line to match
  the package version.
- The documentation inventory is generated from Git's tracked files. `git add` a
  new file, then run `python scripts/documentation_inventory.py` to regenerate it.
- Generated references (`docs/HTTP-REFERENCE.md`, `docs/MCP-REFERENCE.md`) come
  from `scripts/docs_reference.py`; never edit them by hand.
- Release-gate fixtures encode assumptions about what the renderer can and
  cannot do. If you make the renderer more capable, a gate may need a fixture
  the renderer still cannot solve, not a weaker assertion.
- The README images are built by `scripts/build_readme_art.py` from the Halonyx
  style kit fonts; `scripts/build_showcase.py` builds the architecture and
  profile diagrams.

## Measure honestly

- Separate a code cleanup, a faster helper, an end-to-end latency gain and a
  retrieval-quality gain. Claim only what a retained measurement shows.
- Live sites vary from minute to minute. Compare against a control run in the
  same window, and recheck a regression before believing it.
- Keep failures and negative results. Never rewrite evidence to make a change
  look better; a measured "this did not help" is worth recording.

## Documentation and delivery

- Read [documentation maintenance](docs/DOCUMENTATION-MAINTENANCE.md) and use its
  change-impact matrix, not just the page nearest the code you changed.
- Current guides describe present behaviour. Dated reports record what was
  observed at the time; do not update their version numbers.
- Update the README, client instructions, configuration, public access and
  generated references whenever a change affects them.
- Publishing and deploying need the maintainer's explicit go-ahead. Prepare and
  verify everything first, so the approval is the last step.
- Never overwrite a published version or move an existing tag. Follow
  [operations](docs/OPERATIONS.md) for CI, publication, artifact hashes and
  rollout, then verify the published artifacts and the running service's
  identity.
