# dethrottled

**Web search, fetch and extraction with no API keys, no accounts, and no quota.**

Ask it a question and it returns results. Give it a URL and it returns the text
— from a web page, a PDF, a spreadsheet, a slide deck, an ebook, or a video's
captions. It runs on your machine, and there is nothing to sign up for.

```bash
pip install 'dethrottled[all]'
dethrottled
```

```bash
curl -X POST localhost:8787/search-and-fetch \
  -H 'content-type: application/json' \
  -d '{"query": "okapi bm25 ranking", "num_results": 3}'
```

Or bring up the whole self-hosted stack — search engines, a JavaScript renderer
and the API. Search queries still go to public search services; page rendering
and extraction run locally:

```bash
docker compose up -d
```

The Docker deployment is self-contained as a **Compose project**: the API image
includes its Python libraries, Tesseract, ONNX Runtime, and MiniLM embedding
weights. The checked-in Compose file starts its private browser-search,
SearXNG, and Crawl4AI helpers; the optional PDF worker is in the checked-in
overlay. It needs Docker, network access for the searches and URLs you request,
and no Engram, Hypnos, host Python environment, API key, or host model folder.
Fetched-page cache and the corpus live in the `dethrottled-data` Docker volume;
back up that volume if you want to retain them when moving hosts.

To check that the API image has its own dependencies and models, build it and
run its included verifier without network access or host bind mounts:

```bash
docker compose build dethrottled
docker run --rm --network none dethrottled:local python /app/verify_image.py
```

The single API image can do direct search, fetch, extraction, and corpus search.
The complete browser-backed search and JavaScript rendering pipeline uses the
sidecars in this Compose project. Those services are part of the portable
deployment, not services to install separately on another machine.

> Want the whole story? [**TLDREADME.md**](TLDREADME.md) documents every tier,
> every measurement, and every decision in full. This page is the short version.

---

## Maintainer

This repository is owned and maintained by [@zataraine](https://github.com/zataraine).

## Why it exists

Most search and scraping tools ask for an API key, meter you, and cut you off.
The ones that don't usually fall over on the pages that matter — the JavaScript
app, the PDF with no text layer, the spreadsheet where the actual numbers live.

dethrottled handles those, locally, for nothing. Every number below is measured
and reproducible from scripts in this repository.

## Core endpoints

| endpoint | what it does |
| --- | --- |
| `POST /search` | a query → ranked results |
| `POST /fetch` | URLs → their text (`format: "html"` for the source, `"links"` for its anchors) |
| `POST /search-and-fetch` | both in one call, fetching only the winners |
| `POST /research` | a question → a bounded evidence bundle with source text and excerpts; no model answer |

In the Docker stack, default search tries a private browser-search worker for
general web discovery, then falls back to direct DDGS if that worker is down or
returns too little. The worker races DuckDuckGo Lite, DuckDuckGo HTML, and Bing
in one Chromium process, accepts only substantive search pages, and reports
each engine's HTTP status or failure reason in `search_attempts`. Bing News RSS,
local SearXNG news engines, and resolved Google News headlines remain in the
default pool. Existing callers receive news without setting a category.
Browser discovery, Bing News RSS, and SearXNG run concurrently, then merge in
the same source order. Fetch requests overlap up to four selected URLs at a
time, with eight page-read slots shared across requests.
Explicit `categories: "news"` searches interleave browser context with Bing
and SearXNG news so short responses do not hide the articles. Google News
headline resolution is skipped when the already collected, usable pool fills
the entire return window. Source order remains the default within each source;
BM25 is optional; the MiniLM corpus embedding model remains installed.

The szbox Compose deployment checked on 3 October 2026 runs Patchright
1.63.0 in headed Chromium under Xvfb, SearXNG `2026.10.2-19ffbcd30`, and
Crawl4AI 0.9.4. The PDF worker shares the pinned Crawl4AI image. The browser
worker has FastAPI 0.142.2 and Uvicorn 0.54.0. The images and app versions are
pinned or rebuilt deliberately; a later upstream release is not installed
automatically. The raw LAN API includes every route here. The separate public
REST gateway exposes `/search`, `/fetch`, `/extract`, and `/research`, while
the public MCP bridge offers `search`, `fetch`, `search_and_fetch`, and
`research` with a different bearer-token set.

Plus `/corpus/search` (query what you've already fetched, no network),
`/health`, `/v2/status`, `/v2/capabilities` and `/stats`. The capability
response lists installed read formats, OCR, and configured caption support;
configured captions do not imply YouTube is reachable from this host.

There is deliberately **no `/crawl`**. Rendering is a strategy for obtaining a
page, not something a caller wants for its own sake — the ladder escalates by
itself, and a caller choosing the renderer by hand would spend four seconds of
Chromium on a page `direct` serves in two hundred milliseconds. Where forcing
it is genuinely useful, that's the `render` parameter — `always` puts the
renderer first, `never` keeps to the cheap tiers.

`/extract` and `/search-and-extract` remain as aliases. So does
`/extract-with-links`, which is `/fetch` with `format: "links"`: the anchors kept
and rendered as markdown, resolved to absolute URLs. For link discovery rather than
reading — an index page's value is what it points at, and the article
extractors drop that by design.

## The fetch ladder

Three tiers, tried in order, and **a tier only succeeds if it yields readable
prose**. That's the whole design, and it comes from a measurement:

```
page          direct   tls    crawl4ai
quotes-js          0     0       ✓        ← JavaScript-only page
indeed             0  2340       ✓        ← 403s an ordinary TLS handshake
wikipedia      26861 26861       ✓
```

`quotes-js` returns **HTTP 200, a complete response body, and zero characters
of article text.** A ladder that escalates on failed fetches declares victory
there and hands you an empty shell. So escalation is driven by recovered text,
and anything under 600 characters counts as a miss.

| tier | speed | what it's for | needs |
| --- | --- | --- | --- |
| `direct` | ~2.1s | most pages. requests + trafilatura | nothing |
| `tls` | ~0.3s | a real Chrome TLS fingerprint, no browser | a library |
| `crawl4ai` | ~4.4s | renders JavaScript, locally | a container you run |

The renderer solves **JavaScript, not anti-bot**. Some sites answer with a
managed challenge — an interactive "verify you are human" checkbox — and that
is not a fingerprinting problem to be tuned away. Measured: a real Chrome, on
the same machine and address, received the *identical* 403 those sites give us,
carrying the same challenge document. It could run the challenge; it still
ended at a checkbox waiting for a person.

dethrottled reports that honestly as `challenge_needs_a_human` rather than
`http_403`, because "forbidden" and "willing, if you tick a box" are different
facts and only one of them means stop asking.

Only `direct` is required. `tls` is **faster than plain requests** (310ms vs
536ms median) because curl-impersonate is C — it's not a slow fallback, it's a
quick one. A shorter ladder solves fewer pages and nothing breaks.

There is deliberately **no relay tier**. Every option needs an account (a
Cloudflare Worker), a third party who then learns every URL you fetch (a hosted
reader, a CORS proxy), or an address range that anti-bot vendors blocklist on
sight (Tor publishes its exit list in real time).

## Everything it can read

PDF, ZIP-based Office/OpenDocument/EPUB, OLE2 and RTF are routed by their
**file signatures**, even when a server sends the wrong Content-Type. CSV/TSV
has no reliable signature, so it needs a MIME or URL hint; an HTML error page
mislabelled as a spreadsheet is kept out of the spreadsheet parser.

| kind | formats |
| --- | --- |
| web | HTML, via trafilatura → resiliparse → selectolax |
| documents | PDF (+ OCR for scans), DOCX, XLSX, XLS, PPTX, CSV/TSV |
| open formats | ODT, ODS, ODP, EPUB, RTF |
| video | YouTube captions when YouTube serves a track to this host; no audio transcription |

The in-memory HTML format check measured about **0.7µs** on szbox. That figure
does not include downloading a file, parsing a document, or OCR.

## Ranking

Results arrive from several sources. Source order is the default. BM25 remains
available per request; the previously tested cross-encoder was removed because
it made live web and corpus results worse in the measured pools:

1. **BM25** — lexical, no model, microseconds
2. **Corpus merge** — passages you've already fetched, competing with the web

An older four-case synthetic probe favored the cross-encoder. Larger live
search and corpus probes reversed that result, so Dethrottled no longer ships
that reranker. Sending `rerank: true` now returns HTTP 422.

Two orderings are deliberate: **rank before fetching**, because fetching is the
expensive step; and **merge the corpus before optional BM25 ranking**.

## The corpus

Every page fetched is split into passages, embedded and stored in SQLite, so
the cache quietly becomes searchable:

```bash
curl -G localhost:8787/corpus/search --data-urlencode 'q=how are documents ranked'
```

No vector database. Brute-force cosine over 50,000 passages takes **2.5ms** —
an index would be machinery with nothing to do.

## It learns which sites are readable

Some domains reliably return nothing: single-page apps that render from a
private API, syndication aggregators, consent walls. Ranking answers *"is this
relevant?"* and has no idea whether a page can be **read**.

So dethrottled records per-domain extraction outcomes and uses them at exactly
one point — choosing which of the already-ranked results to spend a fetch on.
It never reorders by relevance and never drops a result.

Crucially it's **measured, not declared**. No blocklist ships. Evidence decays
with a 14-day half-life, so a site that starts working recovers on its own.

## Install

```bash
pip install 'dethrottled[all]'           # everything below. Start here
```

The base install is deliberately small — eight pure-Python dependencies — and
gives you search, the `direct` fetch tier and the extraction cascade. Every
other capability is an extra, because the heavy pieces are the ones many
callers never use:

```bash
pip install dethrottled                  # search, direct fetch, extraction
pip install 'dethrottled[documents]'     # + PDF, Office, ODF, EPUB, RTF, OCR
pip install 'dethrottled[tls]'           # + the TLS tier
pip install 'dethrottled[semantic]'      # + the corpus
pip install 'dethrottled[media]'         # + video transcripts
```

Every optional import is guarded: a missing extra removes a capability, it does
not break one, and `/v2/capabilities` reports exactly what this install can
actually do rather than what the code is capable of.

Runs on **x86-64 and ARM64**, Linux, macOS and Windows, Python 3.10–3.13. CI
tests both architectures. Nothing needs a compiler — **including on a Pi**.

One model, 87MB:

```bash
./scripts/fetch-models.sh
```

## Politeness

This fetches other people's pages. The fetch ladder does not request or
consult `robots.txt`.
It still uses one request per domain at a time with a 1.5s floor, an
identifiable User-Agent, bounded retries, and a 10MB response ceiling.

That 1.5s floor means **fetching many URLs from one site is slow by design** —
8 URLs from one domain take 12.7s, 8 URLs from eight domains take 3.3s. That's
the politeness working, not a defect.

## Licensing

MIT. The container image bakes in the Apache-2.0 `all-MiniLM-L6-v2` corpus
embedding model; the source repository fetches it during the image build.

There is deliberately **no non-commercially-licensed component in any code
path** — "optional" is not something a licence audit can rely on.

## Documentation

- [**TLDREADME.md**](TLDREADME.md) — everything, in depth. Every tier, every
  measurement, every rejected alternative
- [USAGE.md](USAGE.md) — the API and every configuration knob
- [ARCHITECTURE.md](ARCHITECTURE.md) — how the pieces fit
- [SECURITY.md](SECURITY.md) — **read before exposing this to a network**

## Licence

MIT. See [LICENSE](LICENSE).
