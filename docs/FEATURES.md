# Current features and how to use them

This is an inventory of the code and default Compose deployment. Use
`GET /v2/capabilities` on your running installation to see which optional
libraries and sidecars are actually configured. HTTP examples assume the
default local address `http://127.0.0.1:8787`; see [API.md](API.md) for all
request fields and responses.

| Feature | How to use it | What to check |
| --- | --- | --- |
| General web search | `POST /search` with `query` | Results and first-row `search_attempts`; browser search may fall back to direct keyless engines |
| News search | `POST /search` with `categories: "news"` | Web/news blend, publisher URLs, and source attempts |
| Fresh search | Add `fresh: true` | Bypasses six-hour search cache; useful for current events or measurement |
| Lexical ranking | Add `rank: true` | `ranking` on first row includes `bm25`; fetch only selected results afterward |
| Freshness weighting | Add `recency` from 0 to 1 **with** `rank: true` | Dates may be absent or unparseable; relevance remains required |
| Already-read material in search | Add `corpus: 5` to `/search` | Local corpus passages join the candidate pool before optional BM25 |
| Read named URLs | `POST /fetch` with `urls` | Each row's `quality`, `content`, `tier`, `cached`, and `failure_reason` |
| Render JavaScript | `/fetch` with `render: "always"` for a known JS page; `auto` is default | Crawl4AI must be configured; `never` skips it |
| Keep links | `/fetch` with `format: "links"` or use `/extract-with-links` | Content contains resolved markdown links for discovery |
| Return source HTML | `/fetch` with `format: "html"` | This refetches because source HTML is not stored in the text cache |
| Search then read | `POST /search-and-fetch` | Search rows merged with per-URL fetch status; bulk results skip OCR |
| Evidence research | `POST /research` with `question` | Source IDs, content, evidence windows, skipped sources; no model answer |
| Stateful browser operation | `POST /drive` with a named `session` and bounded `steps` | Structured snapshots, per-step results, browser events, and final URL/title |
| Execution-canary detection | Add unique `canaries` and use `screenshot: "canary"` | Dialog, console, page-error, title, URL, and visible-text matches; check `execution_signal` |
| Local semantic corpus | `GET /corpus/search?q=...` | Search happens locally; `/corpus/stats` shows indexed pages/passages |
| Health and diagnostics | `/health`, `/ready`, `/v2/status`, `/v2/capabilities`, `/stats` | Liveness differs from real source health; use functional probes too |
| Functional health command | Run `dethrottled-health --json` in the API container | Makes real search/fetch probes; can take time and reach public sites |
| Direct Python use | Import `dethrottled.search`, `fetch`, `rank`, `corpus` | See [PYTHON.md](PYTHON.md); direct mode does not start sidecars |
| Optional HTML-to-PDF | Enable Compose PDF overlay; `POST :8788/pdf` | Separate offline worker; see [PDF_WORKER.md](PDF_WORKER.md) |

## What it can read

| Input | Behavior and use |
| --- | --- |
| HTML pages | `/fetch` runs direct HTTP, TLS fingerprint, and local rendering as needed; trafilatura, resiliparse, and selectolax form the extraction cascade |
| PDFs | `/fetch` reads the text layer and can OCR scans on named URLs; bulk search-and-fetch skips OCR |
| Spreadsheets | XLSX, XLS, CSV, TSV become text with table row boundaries retained |
| Documents and slides | DOCX, PPTX, ODT, ODS, ODP, EPUB, RTF become text |
| YouTube videos | Recognized video URLs use available caption tracks; there is no audio transcription, and YouTube may block this host |

Binary signatures take precedence over server Content-Type where a reliable
signature exists. CSV/TSV have no dependable magic bytes and require a URL or
header hint. Legacy `.doc` and `.ppt` are detected but not parsed. A 200
response containing an HTML error page is not handed to a spreadsheet parser.
The API image includes readers for all listed document types and Tesseract with
English and orientation data; additional OCR languages are optional.

## Other behavior that changes results

- Search canonicalizes URLs, removes repeated titles, and temporarily rests
  failing engines. The headed browser worker validates result quality before
  accepting a race winner. Direct keyless web engines are its fallback.
  SearXNG contributes configured news engines; Bing News RSS and resolved
  Google News RSS headlines add more news coverage. Search can still return
  no results when public engines block or change their pages.
- Fetch treats an empty JavaScript shell, challenge page, or thin teaser as a
  miss and tries the next enabled tier. It can return the best thin result if
  nothing better appears. It records which tier worked or why a URL failed.
- Extraction outcomes inform **domain fetchability**. Consistently unreadable
  domains move later among already-ranked results before a bulk fetch; they
  are not globally blocked. Domain statistics appear in `/stats`.
- Successful fetched prose is cached and indexed into a local SQLite corpus in
  a background task. Search cache and extraction cache have different lifetimes;
  use `fresh: true` to bypass the relevant cache for a request.
- The corpus uses one bundled `all-MiniLM-L6-v2` ONNX embedding model. It is
  for already-fetched passages, not a live-web reranker. There is no bundled
  cross-encoder, Laya, Ettin, llama.cpp, Engram, Hypnos, or Redis dependency.
- `/research` resolves selected sources to public addresses, limits site
  concentration, removes near-duplicate text, and returns evidence windows.
  It does not write an answer or invoke Ollama.
- The fetch ladder ignores `robots.txt`. It still has page-size limits,
  per-domain pacing, tier timeouts, cooldowns, and rolling render budgets.
  These are operational controls, not paid API quotas or Docker core pinning.

`rerank: true` is rejected with HTTP 422. `engines` and `profile` request
fields are accepted for compatibility but currently do not change the search
path. See [CONFIGURATION.md](CONFIGURATION.md) before adjusting local limits
or browser pool sizes.
