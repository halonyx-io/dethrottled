# Agent integration

Dethrottled is an evidence engine. An agent can start with high-level tools,
follow the returned workflow and use lower-level browser operations when the
task needs them. There is no requirement to perform a search before a known-URL
read, or to obey every suggested follow-up regardless of relevance.

## Connect and discover

For MCP, initialize the connection and refresh `tools/list`. Forward the actual
server instructions, tool descriptions and input schemas to the model. Compare
the SHA-256 of `initialize.instructions` with
`capabilities.client_contract.workflow_sha256`. A mismatch can mean an old
adapter or cached client contract; the server version does not prove that a
remote plugin loaded new code.

For REST, start with `GET /v2/capabilities` and use the same workflow policy.
Inspect `/v2/status` for worker readiness. Capabilities describe configuration;
readiness and a successful functional request provide different evidence.
See [public access](PUBLIC-ACCESS.md) for authentication and deployment.

## Work through the task

Text fetches use the [read planner](READ-PLANNER.md) automatically. Preserve its
decision trace and source alternatives. It selects bounded actions from observed
gaps; it does not verify semantic support or operate arbitrary application controls.

1. Use `fetch` directly for known URLs. Otherwise discover with `search`;
   choose `web`, `news`, `academic` or `thorough` for the question. Use
   `crawl_site` for bounded discovery within one origin/path.
2. Read selected sources. Use `focus` for the question, or explicit page/row
   ranges for a large file. `search_and_fetch` combines discovery and reading;
   `research` assembles diverse sources and a coverage ledger without generating
   an answer.
3. Inspect every source's quality and completeness. Continue a `document_id`
   through `read_document`, inspect structure through `inspect_document`, and
   view retained source images with `view_document_image` where available.
4. Follow relevant `workflow.next_actions` when evidence is missing. Automatic
   recovery can try rendering, headed challenge/script-shell acquisition and
   bounded asset recovery. Explicit render/OCR restrictions take precedence.
5. Use `drive` when reading needs interaction, visual inspection, an export or
   application data. Reuse sessions; inspect frames, tabs and network results
   before guessing selectors. Close sessions when finished.
6. Assess source authority, date, agreement and semantic support yourself. Stop
   when the question is supported, not merely when a tool reports success.

For ordinary discovery, start with `profile="web", limit=10, ranking="source"`.
When useful evidence is missing, expand to 20, rewrite around the missing fact
or choose the appropriate specialist profile. More providers do not guarantee
better choices: the [recorded source-menu study](../evaluations/agent-search/results/2026-11-03/REPORT.md)
found unrelated Bing results and a blocked Brave route on the tested host.
Treat the DDG acquisition variants as one family; confirm facts in the pages
you read rather than counting agreement between those variants.

## Preserve the evidence contract

Keep `document_id`, `document_sha256`, `workflow`, `warnings`, `source_partial`,
`truncated`, `extraction`, `acquisition_attempts`, `content_assessment`, `read_plan`,
`acquisition_url` and continuation fields in the
model-visible result. `quality=ok` means extraction succeeded; `thin` retains
short HTML evidence with uncertain coverage; `suspect` retains possible error-banner
pollution after available recovery; `failed` means acquisition failed. Inspect exact
suspect ranges against the full retained document, not a clipped or focused excerpt.
Research keeps these reads in `partial_sources` while seeking clean sources.
Structured short documents can still be valid. `answer_verified` is not set true
by a successful read or lexical match.

MCP screenshots and source images are native image blocks. Forward them to a
vision-capable model; replacing them with a textual placeholder defeats visual
inspection. A wrapper that exposes only flat text can hide document continuation
and recovery even when the server supports them.

Use canonical parameter names: `categories`, not `category`, and
`format="html"`/`format="links"`, not MCP `raw`/`links` aliases. All 20 tools
reject unexpected fields. A client that discards a field before transmission
remains outside server-side validation. [MCP reference](MCP-REFERENCE.md) lists
source-derived tool parameters; the connected server's schemas are authoritative.

## Long work, retries and limits

Use fetch jobs for slow media or batches. Poll with the returned cursor and
`poll_after_ms`; resume interrupted jobs explicitly, retaining committed results.
Use a browser `operation_id` for a deliberate retry of the identical named-session
operation. Unknown browser outcomes require inspection, not blind mutation replay.

429 responses identify different limiters: caller/global admission, request rate,
research, renderer or gateway pressure. Respect the returned retry hint. A busy
polling hint is not a guarantee that a crashed 300-second lease expires then.
Record exact arguments, request ID, timing, version and result when reporting a
problem. Keep bearer tokens and browser login state out of evaluation archives.

## Validate the client

```sh
python evaluations/client_probe.py --endpoint https://your-host/mcp \
  --token-file /secure/path/bearer-token --output sdk-evidence.json
```

Run this with the MCP SDK installed and a protected plaintext token file. It
records a real handshake and reading workflow without authorization headers.
SDK compatibility does not prove that an agent wrapper forwards the contract or
images correctly. [Cold-agent evaluations](../evaluations/agent-workflow/README.md)
record bounded model tasks separately from parser and browser checks.

[Documentation home](README.md) · [Agent guide](AGENT-UPGRADES.md) · [API](API.md) · [Evidence](EVIDENCE.md)

## Broader coverage and MCP parsing

[Limits and continuation](LIMITS.md) lists generous per-call ceilings and ways to
continue larger jobs. Increase requested coverage when the evidence warrants it.
For MCP legacy list tools, parse each JSON `content[].text` entry separately;
never concatenate entries before parsing. Prefer `structuredContent` when supplied
and keep native image blocks available to the model.
