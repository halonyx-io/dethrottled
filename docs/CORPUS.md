# Shared corpus: coverage, retrieval and operation

Dethrottled **1.5.0** defaults to Corpus v2 (schema 2). It leaves
`corpus.sqlite` intact and writes `corpus-v2.sqlite` beside it.

The corpus searches evidence already acquired. It does not replace live web
search, rerank the default web menu or acquire missing documents. Ordinary
search uses it only when the caller explicitly requests corpus candidates.
Both that path and `/corpus/search` use the same configured retriever.

## Four separate forms of coverage

1. **Harvest:** admit the complete eligible extraction, rather than its first
   4,000 characters or the caller's shorter display excerpt. The default harvest
   limit is eight million characters; oversized admissions are rejected with a
   reason rather than silently prefix-indexed. Upstream extraction limits and
   selected page/row ranges still constrain what was acquired.
2. **Retention:** reuse the existing retained document and namespace whenever
   its URL and complete text match. Direct library insertions without such a
   handle use a public document record. Corpus references do not extend the
   document store's existing expiry/size policy.
3. **Lexical retrieval:** store offset-preserving passages once, with FTS5 over
   the harvested text. Sources exceeding two million lexical characters receive
   distributed windows and an explicit `lexical_budget` omission.
4. **Semantic retrieval:** embed a distributed subset of useful passages,
   initially up to 32 for an ordinary source or 96 above 40,000 characters, for
   each configured model. Normalized duplicate, very short and link-heavy
   passages do not consume that budget. Unembedded text remains searchable
   lexically and reopenable while its retained document exists.

`coverage` includes harvested/retained-at-index/lexical/embedded characters,
lexical and embedded ranges, passage counts, chunker/model versions, source
partial status and omissions. `document_available` reports current handle
availability separately. Offsets refer to the original extracted text;
page markers provide page references. Generic headings provide section context,
but chunks can span adjacent sections. OCR methods and quality warnings are
preserved in provenance; their presence does not establish factual accuracy.

## Lifetimes are independent

| Component | Default lifetime |
| --- | --- |
| Search-result cache | Six hours, unchanged |
| Extracted-content/fetch cache | 21 days, unchanged |
| Corpus passages and embeddings | **90 days** since their source was last admitted |
| Retained document handles | Existing seven-day expiry and 200 MB shared-store policy |

An expired or evicted document handle does not silently delete its still-valid
corpus passages. Retrieval reports the unavailable handle; the stored passage
and offsets remain usable. Corpus coverage counters are indexing snapshots;
`retained_documents.current_chars` reports current full-document availability.

## Retrieval controls

```sh
curl -G http://127.0.0.1:8787/corpus/search \
  --data-urlencode 'q=ZX-2026-123456' --data-urlencode 'mode=lexical'

curl -G http://127.0.0.1:8787/corpus/search \
  --data-urlencode 'q=compressor valve replacement interval' \
  --data-urlencode 'mode=hybrid' --data-urlencode 'domains=example.org'

curl http://127.0.0.1:8787/corpus/stats
```

`auto` uses lexical matching for opaque identifiers and semantic retrieval
otherwise. `semantic` queries MiniLM and, when enabled, multilingual E5.
`lexical` requires the query terms and verifies opaque identifiers literally.
`hybrid` explicitly combines lexical results and configured semantic models by
reciprocal-rank fusion. It is not the default web ranking policy. Negative terms
such as `-deprecated` exclude matching passages. `domains` is a comma-separated
exact-host/subdomain filter. HTTP/MCP return at most ten results.

Model weights, 384-dimensional vectors, pooling, E5 query/passage prefixes and
model-specific floors are unchanged. With no caller override, MiniLM uses 0.22
and E5 0.77. The request `floor` overrides MiniLM; E5 keeps its separately
configured `DETHROTTLED_E5_FLOOR`, as in the v1 dual retriever. One model's
cosine score is never treated as the other's.
These floors alone do not distinguish every unrelated question from a useful
match. Schema 2 therefore defaults to `support=standard`: semantic candidates
need agreement between configured models on the same source, or at least two
non-scaffolding query terms in their title/text (one for a one-term query).
The models may support different passages from that source. MiniLM does not
provide a corroborating vote for predominantly non-Latin-script queries.
Lexical matches remain eligible. This is a retrieval heuristic, not entailment
or answer verification.

When standard retrieval is empty or incomplete, explicitly request
`support=broad`. It preserves all above-floor candidates, including genuine
cross-language matches supported only by E5. Unconfirmed rows carry
`support_status=unconfirmed` and a `retrieval_warning`; inspect their passages
before using them. Standard support trades some semantic recall for fewer
unsupported suggestions. Broad support prioritizes coverage and can return
irrelevant results. Both HTTP and MCP expose this choice, and empty HTTP
responses explain the expansion path. Changing `floor` does not disable support
checks. Schema 1 retains its original behavior and cannot select this policy.

`model_scores`, `fusion_score`, freshness and source provenance accompany hits.
Low scores can correctly yield no results; a hit is not proof that it answers
an arbitrary task. Inspect or reopen evidence before using it.

The MCP `corpus_search` tool exposes `mode`, `domains` and `support`. Explicit
corpus rows in normal search include `corpus_evidence` with coverage, support
checks, warnings and retained-document references. HTTP responses expose
`retrieval_warnings` even when a failed/unavailable model produces no hits.
Use `read_document` / `POST /documents/read` to reopen a public
corpus handle from another agent namespace.

## Indexing and resource bounds

The API commits public admission to a durable queue before acknowledging a read.
Its `corpus_indexing` field reports acceptance or rejection. Tokenization,
embedding and maintenance run in one background thread; no extra Docker service
or new mandatory dependency is introduced. Query inference precedes waiting
background inference between batches. That scheduling is within one API process.

SQLite coordinates workers through a lease. Expired running leases can be
reclaimed after 120 seconds. The old source remains active until a transaction
publishes all prepared passages and configured-model vectors. Superseded jobs
cannot publish. Failed inference retries up to three times with bounded delay;
normal shutdown interrupts do not consume those failure attempts. Job states,
recent errors and per-model counts appear in `/corpus/stats`.

Token admission uses the existing model tokenizers and splits overflowing chunks
without changing tokenizer settings. Unchanged passage/model/revision vectors
are reused. Matrix construction reads bounded blocks, avoiding a full Python
list of decoded vectors. Cached matrices share a 256 MiB budget; oversized
indexes use a bounded streaming scan instead. This budget excludes model weights,
ONNX/tokenizer workspaces, text, Python overhead and SQLite's own caches.

The initial limits are 50,000 embeddings per model and a 512 MiB soft corpus
SQLite target. Pruning removes whole old sources across FTS and both models.
Checkpoints and bounded incremental vacuum run off request paths. The disk
target is soft: WAL, pinned readers and reusable free pages can temporarily
exceed it. Status reports actual database/WAL sizes and target overruns.
Each maintenance transaction removes at most 32 whole sources and 256 entries
from each expired-reference registry. A backlog sets `maintenance.pending` and
the worker resumes it between jobs, rather than waiting for the hourly sweep.
Budgets can be exceeded while that bounded cleanup catches up.
Full-document storage has its separate existing budget.

| Variable | Default | Purpose |
| --- | --- | --- |
| `DETHROTTLED_CORPUS_SCHEMA` | `2` | Default v2; `1` selects the retained v1 implementation |
| `DETHROTTLED_CORPUS_AUTOINDEX` | `1` | Enable automatic admission |
| `DETHROTTLED_CORPUS_RETENTION_DAYS` | `90` | Corpus-only retention |
| `DETHROTTLED_CORPUS_MAX_PASSAGES` | `50000` | Embeddings per model |
| `DETHROTTLED_CORPUS_DB_MIB` | `512` | Soft corpus SQLite target |
| `DETHROTTLED_CORPUS_VECTOR_MIB` | `256` | Shared matrix budget |
| `DETHROTTLED_CORPUS_HARVEST_CHARS` | `8000000` | Whole-source admission bound |
| `DETHROTTLED_CORPUS_LEXICAL_CHARS` | `2000000` | Lexical coverage bound per source |
| `DETHROTTLED_CORPUS_PAGE_PASSAGES` | `32` | Ordinary source semantic budget |
| `DETHROTTLED_CORPUS_LONG_PASSAGES` | `96` | Long source semantic budget |
| `DETHROTTLED_CORPUS_QUEUE` | `256` | Pending/running source limit |

Compose passes these settings through. Installing the package starts no worker
and downloads no weights. A base Python install can build/query FTS without
semantic dependencies/weights; coverage explicitly records unavailable semantic
indexing. Install existing model assets and reindex retained sources to enable it.

## Public evidence and isolation

Automatic admission requires an explicit public, stateless acquisition. Local
fetches with `public_only=false`, private/authenticated content, cookie-backed
interactive reads and credential-bearing URLs are not automatically shared.
`public_only=true` alone is network protection, not a general proof that content
is public. The server also checks acquisition provenance. Explicit library
admission is an operator assertion of public visibility.

The public-document registry permits cross-agent reads of registered public
handles without making their original namespace readable. It never searches
arbitrary other private namespaces. Caller identity and credential fields are
not stored as source provenance.

## Migration, repair and rollback

Migration is local-only and bounded. It reads retained documents, never re-fetches
URLs, skips obsolete versions, records expired/partial/unknown/private outcomes,
and tracks stable document IDs across restarts and SQLite rowid reuse. Run each
batch again until its `scanned` count is zero:

```sh
docker compose exec dethrottled python -m dethrottled.corpus_migrate --limit 32 --drain
```

Legacy v1 passages contain neither full-source text nor reliable visibility
provenance. They cannot reconstruct discarded sections, and are not silently
made public. Missing/expired retained bodies require a new acquisition. The
explicit `--trust-legacy-public` option asserts that the selected legacy retained
documents are public; use it only after reviewing that assumption. Reset progress
with `--reset-cursor` when deliberately revisiting previously skipped records.
Do not use that option to bypass known private/authenticated flags.

After adding model assets, or when repairing failed jobs:

```sh
docker compose exec dethrottled python -m dethrottled.corpus_migrate --reindex --limit 32 --drain
docker compose exec dethrottled python -m dethrottled.corpus_migrate --retry-failed --limit 32 --drain
```

These commands operate on available retained text and preserve the current
active index until replacement is ready. `--reindex` and `--retry-failed` resume separate, bounded repair cursors. Repeat
batches until no sources are requeued and no work remains pending/running; use
`--reset-cursor` to begin another repair campaign. In-flight jobs are preserved.
`--drain` processes currently claimable work; another active worker or retry
delay can leave work for the API worker, as the returned status shows. Failed jobs whose full document has expired need re-acquisition.

To roll back, set `DETHROTTLED_CORPUS_SCHEMA=1` and recreate the API container.
The v1 SQLite file was not migrated in place or deleted. V2 admissions made
since the switch are not automatically copied back to v1. Keep both files and
an ordinary SQLite backup until validation is complete. Unreviewed v1 history
predates the new visibility policy; restrict it to trusted callers.

[Dated validation report](../evaluations/corpus-v2/results/2026-11-05/REPORT.md) ·
[Reproducible harnesses](../evaluations/corpus-v2/README.md)

[Documentation home](README.md) · [API](API.md) · [Configuration](CONFIGURATION.md)
