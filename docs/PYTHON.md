# Direct Python use

Install from this checkout in a Python environment:

```sh
python -m pip install '.[all]'
./scripts/fetch-models.sh
dethrottled --host 127.0.0.1 --port 8787
```

The image already contains the model; `fetch-models.sh` is for source
installs. The base package supports direct search, HTTP fetching, and HTML
extraction. Extras are `documents`, `tls`, `semantic`, and `media`; `all`
selects them all. A source install does **not** start SearXNG, browser-search,
or Crawl4AI. Set their URLs in the process environment if you run those
services separately; otherwise the optional paths are skipped.

## Use the modules without an HTTP server

```python
from pathlib import Path

from dethrottled import fetch, rank, search
from dethrottled.cache import Cache
from dethrottled.corpus import Corpus

cache = Cache(Path("cache.sqlite"))
rows, meta = search.search("okapi bm25", max_items=8, cache=cache)
rows, stages = rank.apply(rows, "okapi bm25", bm25=True, corpus=5)

page = fetch.fetch_and_extract(
    "https://example.com/", max_chars=8000, cache=cache)
if page["ok"]:
    print(page["text"], page["tier"], page["extractor"])
else:
    print(page["reason"])

hits = Corpus().search("what is term weighting", limit=5)
print(meta, stages, hits)
```

`search.search` returns `(rows, metadata)`. `rank.apply` returns reordered
rows and the stages actually run. `fetch.fetch_and_extract` returns a dict
with `ok`, `text`, `tier`, `extractor`, `title`, `published`, `chars`, `url`,
`reason`, and `cached`. `Corpus().search` reads local passages and embeds the
query with MiniLM. It needs the `semantic` extra and downloaded model for a
source install. Direct module calls do not automatically index fetched pages;
the HTTP routes schedule that indexing in the background.

For a caller-controlled publisher preference, the direct search module also
supports `prefer_domains`:

```python
rows, meta = search.search(
    "quarterly semiconductor statistics",
    prefer_domains={"example.org", "statistics.gov"},
    cache=cache,
)
```

That option can sweep named domains when the ordinary pool is thin on them.
The HTTP `SearchBody` does not expose `prefer_domains`, so do not send it to
`POST /search`.

Useful helpers include `fetch.canonical_url(url)`,
`dethrottled.documents.kind_of(data, url, content_type)` for file detection,
and `dethrottled.media.transcript(video_url)` for available YouTube captions.
The transcript helper returns `(text, title, reason)` and does not transcribe
audio. Module APIs are Python-level interfaces; the HTTP request and response
contract is in [API.md](API.md).
