# Third-party software and licences

dethrottled's own code is under the [MIT license](LICENSE). It runs on top of
other people's software, and some of that software is under copyleft licences
that carry obligations of their own. This page lists those components, says
where each one runs, and gives the attributions their licences ask for.

It is a summary to help you comply, not legal advice. The licence that ships
with each component is the one that applies.

## Attribution

This product includes software developed by UncleCode (https://x.com/unclecode)
as part of the Crawl4AI project (https://github.com/unclecode/crawl4ai).

Ad and tracker blocking uses the [HaGeZi DNS blocklists](https://github.com/hagezi/dns-blocklists),
published under GPL-3.0. See [ad blocking](docs/ADBLOCK.md#attribution-and-license).

## How dethrottled is distributed

- **The Python package** on PyPI contains only dethrottled's own MIT code. Its
  required dependencies are all permissive (MIT, BSD, Apache-2.0 or PSF, plus
  MPL-2.0 for certifi and tld).
  Optional extras add the packages listed below.
- **The Docker images are not published.** `docker compose` builds them on your
  machine from upstream packages, and each component inside keeps its own
  licence. If you push those images somewhere others can pull them, you are
  redistributing every component below and take on its obligations.

## Copyleft components

| Component | Licence | Where it runs | Used for |
|---|---|---|---|
| [PyMuPDF](https://github.com/pymupdf/PyMuPDF) and MuPDF | AGPL-3.0, or a commercial licence from Artifex | API image; the `documents` extra | PDF text, tables, OCR page images |
| [EbookLib](https://github.com/aerkalov/ebooklib) | AGPL-3.0-or-later | API image; the `documents` extra | EPUB |
| [SearXNG](https://github.com/searxng/searxng) | AGPL-3.0 | Its own unmodified upstream container | Supplementary search engines |
| antiword, catdoc (`catppt`) | GPL-2.0 | API image, run as separate programs | Legacy `.doc` and `.ppt` |
| OpenJDK runtime | GPL-2.0 with the Classpath Exception | Format worker | Runs [Apache Tika](https://tika.apache.org/) (Apache-2.0) |
| FFmpeg, bundled with [PyAV](https://github.com/PyAV-Org/PyAV) | LGPL-3.0-or-later; the bundled x264 and x265 codecs are GPL-2.0-or-later | Media worker | Decoding audio and video for speech-to-text |
| HaGeZi Multi PRO list | GPL-3.0 | Downloaded at runtime, not bundled | Ad and tracker blocking |
| certifi, tqdm, tld | MPL-2.0 (tld offers MPL, GPL or LGPL) | Several images | CA bundle, progress bars, domain parsing |

odfpy is offered under Apache-2.0, GPL or LGPL; dethrottled uses it under
Apache-2.0.

### What the AGPL means here

PyMuPDF and EbookLib are imported into the API process, so a build that
includes them (the default Docker stack, or `pip install dethrottled[documents]`)
is a combined work covered by the AGPL-3.0 as well as by MIT:

- **Running it for yourself** places no extra obligations on you.
- **Modifying it and letting other people use it over a network** (for example
  through the public MCP or REST adapters) requires you to offer those users
  the complete source of the version you run. Unmodified dethrottled is already
  public, so linking to this repository and the exact release covers that case.
- **Distributing it** (a pushed image, a bundled appliance) requires the source
  and licence terms to go with it.
- **If you cannot accept the AGPL**, install the package without the `documents`
  extra and leave PDF and EPUB reading out, or buy a commercial PyMuPDF licence
  from [Artifex](https://artifex.com/licensing).

SearXNG runs as its own unmodified container and is reached over HTTP; it is not
combined with dethrottled's code. Its AGPL source obligation applies if you
modify SearXNG itself.

## Everything else

The remaining Python packages in every image (about 220 distinct packages,
audited on 13 November 2026) use permissive licences: MIT, BSD, Apache-2.0, ISC,
PSF or similar. Notable ones:

| Component | Licence | Used for |
|---|---|---|
| [Crawl4AI](https://github.com/unclecode/crawl4ai) | Apache-2.0 with the attribution requirement above | JavaScript rendering |
| Playwright, Patchright and Chromium | Apache-2.0; Chromium is BSD-3-Clause with bundled third-party licences | Browser rendering and `/drive` |
| trafilatura, htmldate, courlan, Resiliparse, selectolax | Apache-2.0 or MIT | HTML extraction |
| ddgs, curl_cffi, primp | MIT | Search and TLS impersonation |
| Docling, PyTorch, Transformers, RapidOCR | MIT, BSD-3-Clause, Apache-2.0 | Optional layout analysis |
| Tesseract and its trained data | Apache-2.0 | OCR |
| faster-whisper, CTranslate2, ONNX Runtime | MIT | Speech-to-text and local models |
| Apache Tika | Apache-2.0 | Optional extra document formats |

### Model weights

| Model | Licence | Used for |
|---|---|---|
| [all-MiniLM-L6-v2](https://huggingface.co/sentence-transformers/all-MiniLM-L6-v2) | Apache-2.0 | Corpus embeddings |
| [multilingual-e5-small](https://huggingface.co/intfloat/multilingual-e5-small) | MIT | Multilingual corpus embeddings |
| [ettin-reranker-68m-v1](https://huggingface.co/cross-encoder/ettin-reranker-68m-v1) | Apache-2.0 | Search reranking |
| [faster-whisper-small](https://huggingface.co/Systran/faster-whisper-small) | MIT | Speech-to-text |
| [Docling models](https://huggingface.co/docling-project/docling-models) | Apache-2.0 and CDLA-Permissive-2.0 | Layout analysis |

## Checking it yourself

Licences change between releases. To list the Python packages in your own
images and flag anything that is not plainly permissive:

```sh
python3 scripts/license_inventory.py dethrottled-api:1.8.10 dethrottled-dnb:1.8.10
```

It does not cover system packages, browsers or model weights; those are
checked by hand and recorded above.
