# Python API

Request schemas live in `dethrottled.api_models`; existing imports such as
`from dethrottled.server import FetchBody` remain supported. Shared URL identity
normalization lives in `dethrottled.urls` and remains available as
`dethrottled.fetch.canonical_url`. Importing the URL helper directly does not load
the fetch ladder or HTTP server.

Install the published package into a virtual environment:

```sh
python3 -m venv .venv
. .venv/bin/activate
python -m pip install dethrottled
```

## Complete managed engine

The package bundles version-matched deployment sources. No Git checkout is needed:

```sh
dethrottled stack up
dethrottled stack status
dethrottled stack down
```

Install a local Linux Docker Engine and its Compose plugin (v2+) first.
Managed workers support native AMD64/ARM64 Docker hosts; Docker Desktop must use
Linux containers. See [tested costs and requirements](REQUIREMENTS.md). The command checks these
prerequisites and never installs system packages, elevates privileges or changes
firewall configuration itself. First startup builds/downloads API and worker images,
including corpus weights. Optional speech/layout models initialize on first use.

The default stack includes API, DDG browser, SearXNG, renderer and format reader.
Use `--profile media`, `--profile layout` or `--profile full` with `stack up` for
optional inference workers. Status distinguishes ready, initializing and unavailable
services. A first-use model download is reported separately from a failed worker.

`--project NAME` and `--port PORT` allow isolated installations. The default project
is `dethrottled-managed`; API publication stays on loopback. Managed image tags are
separate from Git-checkout production images. Project ownership is checked before
changing existing containers. The extracted context and project settings live under
`~/.local/share/dethrottled/stacks` (LOCALAPPDATA on Windows); override with
`DETHROTTLED_STACK_HOME`. Commands ignore unrelated parent Compose/application secrets.
`stack down` keeps data volumes and downloaded models. Profile changes add/update
services; use down then up with a smaller profile to remove previously enabled
optional services while retaining their caches. A package upgrade supplies a
new matched context; run `stack up` explicitly to rebuild/update its managed services.

## Standalone Python server

```sh
python -m pip install 'dethrottled[all]'
dethrottled --host 127.0.0.1 --port 8787
```

`[all]` installs the optional Python libraries, not external services or system
OCR/conversion tools. The standalone server therefore has fewer capabilities than
the managed stack until these are configured. Use `stack up` for the complete
installation. Nothing starts and no models download during `pip install` itself.
Extras are `documents`, `media` (YouTube captions), `semantic`, `tls` and `all`.
Direct module calls remain supported. For an editable source checkout, use the
repository Compose files for workers rather than the packaged stack commands.

## Direct calls

```python
from pathlib import Path
from dethrottled import fetch, rank, search
from dethrottled.cache import Cache

cache = Cache(Path("cache.sqlite"))
rows, meta = search.search("Python sqlite3", max_items=8, cache=cache)
rows, stages = rank.apply(rows, "Python sqlite3", bm25=True, corpus=0)
page = fetch.fetch_and_extract(
    "https://docs.python.org/3/library/sqlite3.html",
    max_chars=8000, cache=cache,
)
if page["ok"]:
    print(page["text"], page["tier"], page.get("warnings", []))
else:
    print(page["reason"])
```

Search returns `(rows, metadata)`; ranking returns `(rows, stages)`. The direct
fetch result uses `ok`, `text` and `reason`; HTTP responses use `quality`,
`content` and `failure_reason`. Do not interchange those contracts. Direct fetch
also exposes acquisition/recovery/partial metadata where available.

Direct module calls do not automatically retain HTTP document handles, attach
HTTP workflows or index pages in the background. The server orchestrates those
features. Use the [HTTP API](API.md) when that lifecycle is required.

## Retrieval and preferences

`Corpus().search(...)` accesses the original MiniLM corpus. Use
`shared_corpus()` with `DETHROTTLED_MULTILINGUAL_CORPUS=1` and matching E5 assets
for the dual retriever. Corpus queries search already indexed passages; they do
not fetch the web or rerank live sources with a cross-encoder.

Direct search accepts `prefer_domains`; the HTTP search model also exposes
its own list-valued `prefer_domains` field. `media.transcript(video_url)` reads
available YouTube captions and returns `(text, title, reason)`; it is not speech
transcription. Direct media-file extraction can use the configured speech worker.
`documents.kind_of(data, url, content_type)` detects supported native document
kinds; broader format dispatch includes other readers beyond that helper.

[Documentation home](README.md) · [Agent guide](AGENT-UPGRADES.md) · [API](API.md) · [Evidence](EVIDENCE.md)
