# Quick start for people, scripts and applications

Dethrottled works with curl, Python, scheduled scripts and ordinary applications.
An AI agent is one client choice, not a prerequisite. The API returns source
choices and extracted evidence; your program decides what to display or act on.

## Get the complete local engine

The same HTTP API serves agents and ordinary applications. Corpus v2 can reuse
previously indexed public evidence without a model API or an AI client; see the
[corpus guide](CORPUS.md) for lexical queries and optional semantic retrieval.

Install Python 3.10+ and a running Docker Engine with Compose v2+. Managed workers
use Linux containers on native AMD64 or ARM64; Docker Desktop must select Linux
containers. See [tested requirements](REQUIREMENTS.md) before provisioning storage.

On Linux/macOS:

```sh
python3 -m venv .venv
. .venv/bin/activate
python -m pip install --upgrade dethrottled
dethrottled stack up
dethrottled stack status
```

On Windows PowerShell, the equivalent environment/install commands are:

```powershell
py -m venv .venv
.\.venv\Scripts\python.exe -m pip install --upgrade dethrottled
.\.venv\Scripts\dethrottled.exe stack up
.\.venv\Scripts\dethrottled.exe stack status
```

The package includes matching deployment sources; no Git clone is required.
Installation alone starts nothing and downloads no models. Explicit startup can
build/download images and acquire corpus weights. The default starts the API, DNB browser, SearXNG and the format reader. First-time builds need network/disk/time;
read the reported failure or initialization state rather than assuming a hang.

Choose one optional worker profile:

```sh
dethrottled stack up --profile media
dethrottled stack up --profile layout
dethrottled stack up --profile full
```

Media adds speech; layout adds PDF layout inference; full adds both. Their models
can download on first use. These are worker profiles, distinct from search/read
profiles in API requests. Status distinguishes ready, initializing and unavailable.

The normal API is `http://127.0.0.1:8787`. If that port is already used, create an
isolated installation and use its chosen URL in the examples:

```sh
dethrottled stack up --project my-web-tools --port 8790
dethrottled stack status --project my-web-tools
```

No system packages, privileges or firewall changes are silently applied. For
remote clients use the [authenticated public adapters](PUBLIC-ACCESS.md); do not
publish the raw API to an untrusted network.

## Search from a terminal

With the default local port:

```sh
curl -sS http://127.0.0.1:8787/v2/search \
  -H 'Content-Type: application/json' \
  -d '{"query":"Python sqlite3 backup documentation","limit":5,"profile":"web"}'
```

This returns a diagnostic envelope with source candidates and attempt information.
The menu is bounded; it is not a generated answer. `/search` provides the simpler
legacy array. Upstream providers can fail or return irrelevant choices; read the
source you select rather than trusting a title/snippet.

## Read a URL you already know

```sh
curl -sS http://127.0.0.1:8787/fetch \
  -H 'Content-Type: application/json' \
  -d '{"urls":["https://docs.python.org/3/library/sqlite3.html"],"focus":"backing up a database","max_chars":4000}'
```

Inspect `quality`, `warnings`, `source_partial`, `truncated`, content and provenance.
Keep the returned `document_id` if you need another range or a later focused read.
HTTP 200 alone is not proof of useful evidence. A blocked/partial result remains an
explicit result your application must handle.

## Call it from ordinary Python

Save this as `read_source.py`. It uses only the Python standard library on the
client and talks to the already running engine:

```python
import json
from urllib.request import Request, urlopen

BASE_URL = "http://127.0.0.1:8787"
payload = {
    "urls": ["https://docs.python.org/3/library/sqlite3.html"],
    "focus": "backing up a database",
    "max_chars": 4000,
}
request = Request(
    BASE_URL + "/fetch",
    data=json.dumps(payload).encode("utf-8"),
    headers={"Content-Type": "application/json"},
)
with urlopen(request, timeout=120) as response:
    rows = json.load(response)
for row in rows:
    print("quality:", row.get("quality"))
    print("warnings:", row.get("warnings", []))
    print("document:", row.get("document_id"))
    print(row.get("content", ""))
```

```sh
python read_source.py
```

A production script should also handle HTTP/time-out errors, 429 retry hints and
failed/partial content. It can store document IDs and fetch another range later.
This is useful for a scheduled document watcher, a local source browser or an
application ingestion step without any LLM dependency. A watcher needs its own
schedule/state/change comparison; Dethrottled does not create one automatically.

## Choose another workflow

| Need | Operation |
|---|---|
| Search then read selected pages in one request | `/search-and-fetch` |
| Multi-source evidence bundle | `/research` |
| Bounded same-site collection | `/site/crawl` |
| Read a retained document/range | `/documents/read` |
| Inspect document blocks/tables | `/documents/structure` |
| Click, fill, export or inspect a browser page | `/drive` |
| Run slow reads asynchronously | `/jobs/fetch`, then `/jobs/read` |

`/docs` offers the raw API's interactive reference; `/openapi.json` supplies the
machine-readable schema. See the [API guide](API.md), [exact request fields](HTTP-REFERENCE.md)
and [agent/client playbook](AGENT-PLAYBOOK.md) for controls and continuations.

## Shutdown and updates

```sh
dethrottled stack down
```

Down preserves data volumes and downloaded models. For a named installation use
`--project my-web-tools` consistently. To update the managed engine, upgrade the
Python package and run `stack up` explicitly; upgrading a package alone does not
replace running containers. Back up data before operational upgrades.

Profile changes add/update services. To remove previously enabled optional workers,
use down then up with the desired smaller profile, retaining the data volumes.
The managed stack is separate from an existing Git-checkout Compose project.

## Smaller Python-only installation

If you deliberately want only a standalone server/library:

```sh
python -m pip install dethrottled
dethrottled --host 127.0.0.1 --port 8791
```

This does not launch Chromium, SearXNG, Crawl4AI or format/media/layout workers.
Optional Python extras add libraries, not those services or system converters.
Use the complete managed stack for the broad default engine. Direct library calls
are also available; their return shape differs from HTTP (`text`/`ok` versus HTTP
`content`/`quality`). See [Python capabilities](PYTHON.md).
