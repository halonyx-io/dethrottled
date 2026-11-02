# Python API

The package can be used without an HTTP server. Install the published package:

```sh
python -m pip install --upgrade 'dethrottled[all]'
dethrottled --host 127.0.0.1 --port 8787
```

A Python install enables libraries, not Docker workers, system OCR tools or
model weights. For the complete default engine, use Docker Compose. For a
source checkout:

```sh
python -m pip install '.[all]'
./scripts/fetch-models.sh --multilingual
dethrottled --host 127.0.0.1 --port 8787
```

Extras are `documents`, `media` (YouTube captions), `semantic`, `tls` and their
union `all`. The image includes native document/OCR dependencies and both corpus
models; source installs need weights and system converters/OCR tools explicitly.
Set worker URLs in the process environment to use separately running services.
The media extra alone does not install the speech worker.

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
