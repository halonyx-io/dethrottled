# Release gates

The 1.0 candidate is evaluated with controlled task facts, fresh deployment
contracts and separate live observations. A listening HTTP server does not pass
a reading gate, and a passing fixture does not establish access to every website.
No model, API key, GPU or host `.env` is required for the default contracts.

## Fresh default deployment

From an installed Docker/Compose host, run:

```sh
python3 evaluations/release/compose-check.py --out /tmp/dethrottled-release
```

The runner builds API/browser/format images, starts a randomly named project with
fresh volumes and an empty interpolation file, then removes only that project.
It also removes inherited `DETHROTTLED_*`, `CRAWL4AI_*` and `COMPOSE_*` settings.
The Docker connection/context is preserved. Port 19087 must be available; select
`--port` to change it. `--no-build` uses the three named candidate images when
CI or a local build has already prepared them. No production services are changed.

The fixture adds deterministic sources to the otherwise default stack. Checks
cover automatic primary representations, loading/scroll/details/network recovery,
visitor state, scoped browser handoff, negative cases, retained late table rows,
real MSG/XLSB reads, frame actions, popups, captured downloads and four storage
types across a worker restart. Exceptions and failures are recorded immediately.
The runner returns nonzero if any contract fails. Native AMD64 and ARM64 CI jobs
run the same deployment checks and upload their observations even on failure.

The Apache POI MSG/XLSB fixtures are copied unmodified, with commit URLs, hashes,
expected text, license and notice under `fixtures/`. The tests check extracted
text, not full attachment or physical cell completeness.

## Live sources

`live.py --cpu URL [--gpu URL] --out DIRECTORY` compares private browser endpoints
with identical recovery policy. It records hashes, task assertions, access states,
native interactions and individual timings, without publishing page bodies. The
Reddit sources repeat three times per browser configuration; the other sources
run once. These small single-host samples are neither a general anti-bot success
rate nor a ranking/answer-accuracy benchmark. Keep failed sources in the report.

## Remote agents

`remote.py --token-files FIRST SECOND --out FILE` exercises actual authenticated
REST/MCP adapters: published instructions, tool count, native interaction/replay,
shared browser state, retained-document forwarding, caller isolation and private
address rejection. Use disposable adapters/registries, not production credentials.
The SDK environment needs `mcp` and `httpx`. Default ports are 19084 and 19086.

`cold-agent.py --token-file FILE --out DIRECTORY` starts a fresh tool-capable
Ollama model conversation using only MCP's published instructions and schemas.
This optional evaluation can use a configured cloud subscription; the engine has
no dependency on it. A result is one observed model conversation. Do not count it
as a mechanical contract or universal agent reliability estimate. Local transcripts
contain source text; publish only reviewed, sanitized summaries. Provider reasoning
and bearer values are never saved by the harness.

See the [candidate gate status](../../docs/ONE-ZERO.md). Publication and the final
1.0 version remain separate from preparation and local test completion.
