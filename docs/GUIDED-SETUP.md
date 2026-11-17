# Guided Setup

Guided Setup is an interactive command in the Dethrottled Python CLI. It
checks the Docker host, recommends settings, and saves a Compose override only
after confirmation. Start the stack separately when you are ready.

```sh
dethrottled stack configure --project my-web-tools --output guided.json
dethrottled stack up --config guided.json
dethrottled stack status --project my-web-tools
```

The prompts explain each choice. Press Enter for the recommendation or select
another numbered option. At the end, review the whole plan before saving.
Choose a new output path when revising a plan. The managed stack reuses its
applied plan on subsequent starts.

- **Clients and host use.** One local agent, several local clients, and remote
  clients have different concurrency needs. Separately say whether this host
  also runs important workloads. Remote clients use the [authenticated adapters](PUBLIC-ACCESS.md).
- **Capabilities.** Every profile includes web search, browser interaction, and
  standard document reading. Add speech, advanced PDF layout, or both when
  required. The wizard explains model downloads and estimated build space.
- **Resource limits.** Recommendations consider Docker CPU and memory limits
  and current host headroom when observable. Choose one or two simultaneous
  browser renders and separate budgets for embeddings and optional workers,
  reranking, and API-side OCR. The reranker starts at half of Docker's logical
  CPUs, rounded down with a minimum of one. The OCR recommendation uses the
  same starting point with a maximum of eight threads per Tesseract process.
  Search depth and per-read
  timeouts stay unchanged. When Linux exposes mixed CPU capacities, the
  recommendation accounts for them. The scheduler remains free to place
  threads across cores.
- **Ranking and corpus.** Choose whether to enable the local Ettin reranker
  and whether to index eligible reads automatically. Pausing indexing preserves
  existing corpus data and its retention policy.
- **Graphics.** A render device can be present without being accessible.
  When one is accessible, the GPU is the recommendation (since 1.9.0): Chrome
  then reports the real GPU instead of a software renderer and used about a
  third of the CPU per page in testing. The plan passes the DRM render node and
  its card node with both groups. Hardware use is verified when the browser
  worker starts, with software rendering as the fallback.
- **Browser network.** `Native` (recommended): public pages connect directly,
  HTTP/3 included, and each browser runs as its own user confined by a kernel
  firewall the worker loads at start. That needs Docker to grant the worker
  `NET_ADMIN`; if it cannot, the worker refuses to start and `stack status`
  says why. `Gate`: every page through the worker's proxy, as before 1.9.0.
- **Browser identity.** The machine's timezone and language are detected and
  passed to the browser, so it does not report UTC from another country.
  Nothing is invented: these are the machine's own settings.

`dethrottled stack up` without a saved plan applies the same truthful
detections by itself: timezone, language and an accessible GPU on a native
Linux engine (`DETHROTTLED_GPU=off` opts out of the GPU). Sizing choices stay
with the wizard.

On a local native Linux Docker Engine, the wizard checks the filesystem backing
Docker, OS-visible RAM, available RAM, loopback port and render-node access.
For Docker Desktop or a remote Docker context, host-side disk, port and GPU
checks may be unavailable. Estimates are planning guidance and first startup
still checks readiness.

## Apply to a checkout

The saved file is a regular Compose override. Use the project name, port and
profile printed by the wizard. For example, for a default-profile project:

```sh
DETHROTTLED_BIND=127.0.0.1 DETHROTTLED_PORT=8787 docker compose -p my-web-tools \
  -f docker-compose.yml -f guided.json up -d --build
```

Add `--profile full` before `up` if the plan selected both optional workers,
or use the profile shown in the plan. Use the same Compose project as the
existing deployment to retain its volumes. Applying a plan can recreate
services. Switching to a smaller profile does not stop workers already running
under a previous profile. See [operations](OPERATIONS.md) for shutdown and
[requirements](REQUIREMENTS.md) for retained state and resource costs.

[Quick start](QUICKSTART.md) · [Configuration](CONFIGURATION.md)
