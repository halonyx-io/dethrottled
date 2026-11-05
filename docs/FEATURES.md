# Features and availability

Use `/v2/capabilities` to discover the configured installation and `/v2/status`
to check its workers. This inventory distinguishes the base stack from optional
services; a supported format does not guarantee a correct or complete extraction.

| Capability | Entry point | Availability and result |
|---|---|---|
| Web, news and academic discovery | `search`, `POST /search` or `/v2/search` | Keyless profiles, explicit engines, source attempts; v2 retains diagnostics for empty results |
| Known-source reading | `fetch`, `POST /fetch` | HTTP/TLS/render/headed ladder, automatic challenge and script-shell recovery, explicit thin/failed outcomes |
| Mixed-content diagnostics | `fetch`, `research`, retained reads | Suspect banner spans and text hashes, preserved evidence, bounded recovery and agent inspection actions; narrow heuristics, not semantic verification |
| Autonomous reading | Normal text `fetch` | Observed-gap planner, declared primary representations, browser state/details/scroll/network recovery, preserved attempts and stop reasons |
| Combined discovery/read | `search_and_fetch`, `/search-and-fetch` | Ranked candidates with per-source extraction status |
| Evidence bundle | `research`, `/research` | Diverse source references, term windows, facet gaps; no generated answer |
| Site traversal | `crawl_site`, `/site/crawl` | One-origin/path bounds, sitemap/HTML discovery, frontier and incomplete coverage |
| Retained text and citations | `read_document`, `inspect_document` | Scoped version hashes, Unicode positions, source structure and continuation |
| Source pixels | `view_document_image` | Retained/reacquired verified source bytes where supported; not available for every page |
| Durable read jobs | `start_fetch_job`, `read_fetch_job`, `resume_fetch_job`, `cancel_fetch_job` | Completion-order results, cursors, explicit interruption/resume |
| Browser interaction | `drive`, `/drive` | Sessions, selectors, iframes, tabs, screenshots, downloads and application responses |
| Browser restart state | `drive` checkpoint/history | Cookies, storage and action outcomes; not live DOM or every tab |
| Shared public corpus | `corpus_search`, `/corpus/search` | Bounded lexical/semantic/hybrid retrieval, durable indexing, coverage and standard/broad support; [Corpus v2](CORPUS.md) |
| Speech | Fetch direct audio/video | Optional media worker; captions do not require the speech worker |
| Advanced PDF layout | `document_mode="layout"` | Optional Docling worker; native parsing/table detection/OCR also have local paths |
| MSG and XLSB | Normal fetch/read | Tika format worker included in the default stack for these two measured formats |
| HTML-to-PDF output | Separate worker `POST :8788/pdf` | Optional overlay; offline printing of supplied HTML |

The base API image includes HTML and document parsers, Tesseract language data
and MiniLM/E5 corpus weights. The base Compose stack adds browser-search,
SearXNG, Crawl4AI and the format reader. Media/layout model downloads may be needed on first use;
format parsing uses its own worker. See the [format matrix](DEPENDABLE-WORKFLOWS.md)
and [setup](CONFIGURATION.md).

Search profiles and explicit engines actively select sources. Lexical BM25 and
fusion ranking are supported; neural reranking is disabled and `rerank=true` is
rejected. Corpus models retrieve stored passages, not live-web cross-encoder
reranking. Optional Exa/Tavily/Parallel discovery is explicitly selected and can
be metered; defaults remain keyless.

Compose defaults to verified graphics `auto` mode. The optional host helper exposes
DRM devices when available; the worker verifies hardware rendering or falls back
to software. Neither result fabricates a GPU identity. Universal CAPTCHA defeat, every-file-format
support, exhaustive site coverage and verified answers are not promised. The
[evidence index](EVIDENCE.md) separates measured successes from remaining failures.

[Documentation home](README.md) · [Agent guide](AGENT-UPGRADES.md) · [API](API.md) · [Evidence](EVIDENCE.md)

## Native ad/tracker domain filtering

Dethrottled 1.6.0 adds default-on HaGeZi Multi PRO filtering across
shipped acquisition clients and managed workers, with persistent background
updates and explicit policy refusals. See
[coverage, diagnostics and limitations](ADBLOCK.md) and the
[controlled resource evaluation](../evaluations/adblock/README.md).
