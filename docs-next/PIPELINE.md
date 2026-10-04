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

The API asks the browser worker for general web results. Its single headed
Chromium process races DuckDuckGo Lite, DuckDuckGo HTML, and Bing in separate
tabs, with staggered starts. It accepts a race only when it gets real result
URLs and enough useful titles/snippets; an HTTP 200 or challenge page alone is
not success. It reports per-engine status and reasons. The worker allows three
active searches, with up to three tabs each, and queues a limited number of
additional requests. If it cannot produce a usable result, the API tries its
direct keyless web engines.

In parallel, the API queries Bing News RSS and its configured SearXNG news
engines. It may use Google News RSS to discover additional headlines, but it
resolves those to publisher URLs before returning them. Search merges the
sources, removes canonical-URL and repeated-title duplicates, drops known junk
domains, and interleaves news with web results when `categories` is `news`.
Search engine failures can be rested temporarily; `/stats` and first-row
`search_attempts` help reveal degradation. Results from outside search engines
cannot be guaranteed on every query.

By default, source order is retained. With `rank: true`, the API searches a
larger pool and uses lexical BM25 on titles and short text before choosing
which URLs to return or fetch. `corpus` can merge already-fetched passages
into that candidate pool. `recency` changes BM25 ordering of relevant dated
results. There is no cross-encoder reranker or decision model in this path.

## Reading: `/fetch`

The API checks its extraction cache unless `fresh` is true. A recognized
YouTube video URL is handled through its caption track before the web-page
ladder; it does not run speech recognition. Other URLs use these tiers, when
enabled, in order:

1. Direct HTTP fetch and local extraction.
2. `curl_cffi` with a browser TLS fingerprint.
3. Local Crawl4AI Chromium rendering.
4. Optional external Jina reader, disabled in the default Compose project.

`render: "always"` moves Crawl4AI to the front; `render: "never"` skips it.
Each tier must yield usable content. A 200 status with a login page, challenge,
or JavaScript shell does not count as a successful read. Short HTML extraction
can trigger escalation; if no tier does better, the best short result is
returned with its tier. Structured documents use a different floor because a
five-row table can be useful even though it is short.

File detection uses bytes first for PDF, Office ZIP/OLE, EPUB, OpenDocument,
and RTF. Some formats, especially CSV, need a URL or server-header hint after
sanity checks. The page extractor then uses local parsers and preserves table
row breaks. A named `/fetch` can OCR a scanned PDF; bulk
`/search-and-fetch` skips OCR for each search hit.

Fetched successful prose is indexed into the corpus in a background task.
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
windows matched to question terms. Its output is an evidence bundle with
source IDs, content, and per-query attempts; it does not synthesize a written
answer. Search and page reads are parallel within bounded request pools.

## Local corpus

The corpus stores passages and 384-dimensional vectors in SQLite under
`/data`. Only `all-MiniLM-L6-v2` is used. ONNX Runtime and the `tokenizers`
library are inside the API image; no host model service is needed. Corpus
search embeds the query and compares it with stored vectors. The default
relevance floor helps avoid presenting the least-bad unrelated passage as an
answer. The corpus is not Engram or Hypnos and does not require Redis.

## What runs where

The API image is self-contained for direct search, fetch, extraction, and
corpus search. The full browser-backed pipeline requires the Compose sidecars.
The image includes the MiniLM weights and tokenizer in
`/opt/dethrottled/models/emb-minilm`; the named `/data` volume contains only
mutable state. No unused reranker or decision-model weights are shipped.
