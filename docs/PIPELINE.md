# How the pipeline works

## Services and boundaries

```text
caller -> Dethrottled HTTP API (port 8787)
             |-- browser-search: headed Patchright Chromium under Xvfb
             |-- SearXNG: configured news engines
             |-- direct keyless web and news sources
             |-- Crawl4AI: JavaScript rendering when extraction needs it
             |-- local SQLite cache and corpus in /data
             `-- MiniLM ONNX embedding model in the API image
```

The default Compose project starts four containers: the API, browser-search,
SearXNG, and Crawl4AI. Browser-search,
SearXNG, and Crawl4AI communicate on the private Compose network and are not
published to the host. The optional HTML-to-PDF worker is a separate service
from the API and is enabled with `docker-compose.pdf-worker.yml`.

## Discovery: `/search`

When `DETHROTTLED_CHEAP_DISCOVERY=1`, the API first tries a bounded
1.5-second TLS-impersonated DDG Lite read. Challenges, thin results, and
transport failures fall through to the established browser worker. Both paths
share worker pacing. Otherwise discovery starts directly with the worker. Its single headed
Chromium process races DuckDuckGo Lite, DuckDuckGo HTML, and Bing in separate
tabs, with staggered starts. It accepts a race only when it gets real result
URLs and enough useful titles/snippets; an HTTP 200 or challenge page alone is
not success. It reports per-engine status and reasons. The worker allows three
active searches, with up to three tabs each, and queues a limited number of
additional requests. If it cannot produce a usable result, the API tries its
direct keyless web engines.

News profiles additionally query Bing News RSS and configured SearXNG news
engines. The default web profile avoids that extra work; thorough adds Mwmbl
and academic adds Crossref, OpenAlex and arXiv. It may use Google News RSS to discover additional headlines, but it
resolves those to publisher URLs before returning them. Search merges the
sources, removes canonical-URL and repeated-title duplicates, drops known junk
domains, and interleaves news with web results when `categories` is `news`.
Search engine failures can be rested temporarily; `/stats` and first-row
`search_attempts` help reveal degradation. Results from outside search engines
cannot be guaranteed on every query.

By default, source order is retained. With `rank: true`, the API searches a
larger pool and uses Unicode lexical BM25 on titles and snippets before choosing
which URLs to return or fetch. `corpus` can merge already-fetched passages
into that candidate pool. `recency` changes BM25 ordering of relevant dated
results. There is no cross-encoder reranker or decision model in this path.

## Reading: `/fetch`

The API checks its extraction cache unless refresh or bypass is requested.
Refresh writes the replacement; bypass writes nothing. Cached responses expose
the stored retrieval time and cache age. Legacy extraction entries are lazily
refetched so old encoding corruption does not survive the upgrade. A recognized
YouTube video URL is handled through its caption track before the web-page
ladder; it does not run speech recognition. Other URLs use these tiers, when
enabled, in order:

1. Direct HTTP fetch and local extraction.
2. `curl_cffi` with a browser TLS fingerprint.
3. Local Crawl4AI Chromium rendering.
4. Optional reuse of the existing headed browser (`headed_fallback: true`).
5. Optional external Jina reader, disabled in the default Compose project.

`render: "always"` moves Crawl4AI to the front; `render: "never"` skips it.
Each tier must yield usable content. A 200 status with a login page, challenge,
or JavaScript shell does not count as a successful read. Short valid HTML can succeed without being treated as an article failure.
A structural shell with no usable content is reported as incomplete rendering,
not automatically as anti-bot blocking. `wait_for` and `render_delay` allow
callers to specify DOM readiness. Structured documents use a different floor because a
five-row table can be useful even though it is short.

File detection uses bytes first for PDF, Office ZIP/OLE, EPUB, OpenDocument,
and RTF. Some formats, especially CSV, need a URL or server-header hint after
sanity checks. The page extractor then uses local parsers and preserves table
row breaks. Named and combined search/read calls can OCR scanned sources;
callers can disable OCR explicitly. Mixed PDFs record extraction method by page.

Canonical prose is indexed independently of the requested representation;
image-only and navigation-only rows are excluded. Fetched successful prose is indexed into the corpus in a background task.
The response does not wait for embeddings to finish. The fetch cache and
corpus are distinct: the corpus can retain passages after a fetch cache entry
expires.

The ladder **does not request or honor `robots.txt`**. It still has a
per-domain request gap, timeouts, response-size ceilings, tier cooldowns, and
rolling render budgets. See [CONFIGURATION.md](CONFIGURATION.md) for these
controls. They are internal workload controls, not paid API quotas or Docker
CPU pinning.

## Evidence: `/research`

Research searches the question plus an official-source probe, or the question
plus supplied facets. It interleaves results, checks that selected source URLs
resolve to public addresses, limits concentration on one host, fetches the
selected pages, removes near-duplicate text, and extracts short evidence
windows matched to question terms before clipping the returned content. Its output is an evidence bundle with
source IDs, content, and per-query attempts; it does not synthesize a written
answer. Search and page reads are parallel within bounded request pools.

## Local corpus

The corpus stores passages and 384-dimensional vectors in SQLite under
`/data`. Only `all-MiniLM-L6-v2` is used. ONNX Runtime and the `tokenizers`
library are inside the API image; no host model service is needed. Corpus
search normally embeds the query and compares it with stored vectors. A
synchronized SQLite FTS5 index supports lexical mode and exact opaque-ID
lookups. Existing passage rows are backfilled when the index is first created. The default
relevance floor helps avoid presenting the least-bad unrelated passage as an
answer. The corpus is not Engram or Hypnos and does not require Redis.

## What runs where

The API image is self-contained for direct search, fetch, extraction, and
corpus search. The full browser-backed pipeline requires the Compose sidecars.
The image includes the MiniLM weights and tokenizer in
`/opt/dethrottled/models/emb-minilm`; the named `/data` volume contains only
mutable state. No unused reranker or decision-model weights are shipped.

## Retained evidence and source files

Focused URL reads retain up to one million extracted characters independently
of response length. Scoped document handles support new questions and sequential
continuations. Progressive jobs publish sources in completion order and retain
completed results across client disconnects. Browser downloads are parsed using
the same readers; their scoped source bytes permit later page/row reads and
image inspection without repeating browser actions. OCR-derived content retains
warnings. Native text from mixed documents can enter the prose corpus; OCR
pages/supplements are excluded until that index can preserve their verification
provenance.

Agent workflow policy is published at MCP initialization and in capabilities.
Read results include prerequisite-aware next actions, and bounded automatic
recovery can retry navigation-only reads with rendering or follow relevant
image/document assets. Original HTTP file bytes can be reacquired for reparsing
or pixel inspection only after verifying their hash against the retained version;
changed bytes are never silently substituted.
