# Agent workflow additions in 0.6.0

These additions favor coverage, inspectable evidence and recovery. Existing
fetch/search/research/drive tools and DDG browser search remain available.

| Need | Entry and follow-up |
|---|---|
| Site discovery | crawl_site accepts same-origin seeds, including sitemaps. Read document handles; inspect failures, frontier and continuation URLs. |
| Precise evidence | inspect_document returns exact text, Unicode character positions, version hash and citation selectors. PDF metadata includes bounded text-layer boxes in PDF points, not OCR alignment. |
| Application data | drive action=network lists same-host XHR/fetch responses. Read using name=body and selector=response_id; the returned document_id supports normal reading. |
| Restarting a login | drive action=checkpoint saves cookies/localStorage. Reuse session after restart; its original host scope is preserved. close_session deletes the checkpoint. |
| Interrupted batches | read_fetch_job reports resume_available; resume_fetch_job resumes missing positions, preserving committed results and cursors. |
| Timed media | Fetch VTT/SRT directly. YouTube metadata retains available cue times. Optional local speech recognition reads direct audio/video files through fetch/jobs. |

MCP initialization publishes this progression; capabilities describe configuration,
and relevant results suggest concrete follow-ups. Agents retain control of endpoints.

## Actual client checks

Initialize and refresh tools/list after upgrades. Compare the SHA256 of initialization
instructions with capabilities.client_contract.workflow_sha256. Preserve document
IDs/hashes, warnings, extraction, workflow and continuation fields when adapting to
provider payloads. Forward native MCP images to vision-capable models. A flat text
wrapper can hide these abilities. Server version cannot prove a remote plugin loaded.

```sh
python evaluations/client_probe.py --endpoint https://your-host/mcp \
  --token-file /secure/path/bearer-token --output sdk-evidence.json
```

The probe uses the real MCP Python SDK, records handshake, schemas, capabilities,
fetch, inspection and reopening, and excludes authorization headers. The token file
contains the bearer token, not its hashed registry. SDK success does not certify
that an agent integration forwards all metadata or native images to its model.

Public responses expose X-Request-ID and Server-Timing admission duration; the
edge may also provide CF-Ray. Record these alongside exact arguments and backend
elapsed_ms when investigating remote latency. Shared quota checks run outside the
async request loop and retain an open WAL connection. Ephemeral admission state
uses SQLite NORMAL synchronization; source evidence and job durability are unchanged.

## Portable deployment

Core Compose mounts browser checkpoint/journal state in a named volume. Evidence and
job payloads/results use the existing data volume. Completed browser operations can
replay their saved result after restart; unknown outcomes require inspection. Journal
entries expire after 24 hours; do not reuse operation IDs beyond that retention window.

```sh
docker compose -f docker-compose.yml -f docker-compose.agents.yml \
  --profile public up -d --build
```

Supply DETHROTTLED_TOKEN_REGISTRY_FILE pointing at an existing registry readable by
container UID 10004. The file contains hashes only:
`{"tokens":[{"sha256":"<64 hex characters>","label":"agent","scopes":["web","drive"]}]}`.
Keep bearer tokens separately. Both adapters share admission accounting. Missing
registry files fail the bind mount; there is no default credential. Set
MCP_ALLOWED_HOSTS for the reverse-proxy hostname. Ports bind to loopback: route /mcp
to 18184 and REST to 18186 behind TLS. Existing systemd adapters can remain in use.

For local speech set DETHROTTLED_MEDIA_WORKER_URL=http://media-worker:19889 and
WHISPER_MODEL=small in the Compose environment, then use both files with
--profile media. Weights download on first use and persist in media-models; audio
is processed locally. Defaults: CPU int8, 3 GiB memory, one active request,
50 MiB input and 30 minutes decoded audio. The fetch document byte limit also
applies. Prefer jobs for long work. Larger models need separate resource evaluation.

## Explicit limits

- Site traversal follows observed HTML links and sitemap entries within one origin
  and path prefix, with page/depth/discovery/time bounds. Hidden, unlinked and
  JS-only sources may be absent; whole_site_complete remains unknown.
- Citation positions refer to retained text, not HTML bytes. Table returned_row
  is an extraction ordinal, not a physical spreadsheet row. Bounded PDF text-layer
  boxes do not reconstruct chart/table geometry or align OCR output.
- Network inspection covers a 50-response session ring. Stable response IDs fail
  after eviction. Body reads require Content-Length at most 2 MB and report character
  truncation. Chunked bodies without that header need another acquisition path.
- Checkpoints hold sensitive login state locally for 24 hours and are not exported
  through public APIs. They exclude IndexedDB, sessionStorage, live DOM and sockets.
  Close unused sessions to delete checkpoints.
- Jobs predating stored payloads cannot resume. Resume reads missing positions,
  potentially repeating an uncommitted read after a crash; committed failed results
  remain visible. Browser mutations never resume automatically.
- ASR can hallucinate or mishear; times are model estimates. Video transcription
  covers speech, not frames or speaker identity. A YouTube page without accessible
  captions still needs a separately obtainable caption/media URL, not a universal
  downloader.

Validation distinguishes regression tests, real Chromium/audio checks, SDK compatibility,
fresh-agent tasks and public smoke tests. These do not establish universal accuracy.
