# DPR for scripts and bulk retrieval

Dethrottled Programmatic Resolve (DPR) accepts up to 500 public HTTP(S) URLs per
job. Submit once, save the job ID, and collect one outcome per input. DPR uses
the same extraction and document retention as ordinary reads. The batch runs
with a separate, bounded executor and requires neither an agent nor a model API.

## Run a list

Put one URL per line in a text file, or use a CSV with a `url` column and
optional unique `item_key` values. Use the CLI from an environment with
Dethrottled installed and a running engine.

```sh
dethrottled dpr fetch urls.csv --operation-id monthly-audit-01 --output results.jsonl
dethrottled dpr export JOB_ID --format csv --output summary.csv
dethrottled dpr export JOB_ID --output evidence.jsonl --archive-dir extracted
```

Without `--output`, `fetch` submits and prints the job ID without waiting.
Exports require new paths. JSONL preserves the nested evidence records. CSV is
a spreadsheet summary. The optional archive copies retained extracted text into
individual files, including a per-row status if a handle has expired or a
download fails. It reflects the extraction coverage of the retained document.
An interrupted export can be collected again into a new file using the job ID.

Use `DETHROTTLED_URL` or the global `--url` option for another endpoint. For an
authenticated REST adapter, supply a bearer through `DETHROTTLED_TOKEN`. The
adapter assigns the caller namespace. Remote job submissions also fit within
the adapter's 256 KiB request-body limit.

## HTTP contract

All routes below use JSON and POST. The response envelope includes
`schema_version: 1`. The submit and retry endpoints return HTTP 202.

| Route | Request and behavior |
|---|---|
| `/v1/dpr/jobs` | `urls`, optional matching unique `item_keys`, optional `operation_id`, and read options. An identical operation ID and payload return the original job. A changed payload with the same ID returns 409. |
| `/v1/dpr/jobs/read` | `job_id`, optional `cursor` (start at zero), `limit` (1–50). Read results in completion order and persist `next_cursor` after consuming them. |
| `/v1/dpr/jobs/cancel` | `job_id`. Stops scheduling new reads. In-flight requests can still finish and must release their slot before a resume. |
| `/v1/dpr/jobs/resume` | `job_id`. Restarts unfinished inputs after interruption, cancellation, or job-level failure. It preserves committed rows and may redo an uncommitted read. |
| `/v1/dpr/jobs/retry` | `job_id` and a new `operation_id`. Creates a separate job for items with outcome `failed` in a completed job. Compare the jobs by item key. |
| `/v1/dpr/resolve` | `search` (a [search request](HTTP-REFERENCE.md)), optional `alternatives` (0–4), and read options. Considers up to five candidates and reads at most three, stopping at the first usable source in configured search order. |

```sh
curl -fsS http://127.0.0.1:8787/v1/dpr/jobs \
  -H 'Content-Type: application/json' \
  -d '{"operation_id":"sample-01","urls":["https://docs.python.org/3/library/sqlite3.html"],"item_keys":["sqlite"]}'
```

Job states are `queued`, `running`, `completed`, `cancelled`, `interrupted`, or
`failed`. A completed job can contain failed items. Poll with the returned
`poll_after_ms`. On HTTP 429, respect `Retry-After`. After a process restart,
unfinished jobs become interrupted and require explicit resume. Completed
results are retained for up to 24 hours, subject to the job storage budget.
Document handles have a separate expiry. Export promptly if results are needed
for longer.

Exact duplicate URLs with the same job settings share an acquisition and each
keep their own input index and key. DPR schedules one read at a time per job and
up to two background URL reads across jobs in one API process. Interactive reads
use their own thread pool. Browser and upstream limits still apply.

## Interpret evidence

- Keep the requested URL, final URL and canonical URL when present. A failed
  attempt may provide an observed HTTP status and final URL. Missing status
  means it was unavailable from the acquisition path.
- `usable`, `partial`, `blocked` and `failed` describe the extraction. Read
  `quality`, `warnings`, `source_partial` and `preview_truncated` separately.
  A short preview can have a longer retained document behind it.
- `fetched_at` records acquisition time for the returned content.
  `checked_at` records a live observation when available and stays empty on
  cache reuse. `completed_at` belongs to the job item. `last_modified` is the
  server's HTTP claim when captured and parseable. `published_at` is reported
  extraction metadata when available. Missing dates stay empty.
- Compare `content_sha256` across runs to detect changes in extracted text.
  Compare `extractor_version` as well. An extractor upgrade can change the text
  without a publisher update. `source_sha256` is available on acquisition paths
  that hash the original document.
- Use `cache_mode: "refresh"` (CLI `--fresh`) for a new read or `max_age` to
  bound cache reuse. DPR reports refresh failures explicitly. Conditional HTTP
  revalidation and automatic historical comparison are outside this release.
- URL batches skip search ranking. Query resolution uses configured search
  ranking, including Ettin when available. `selected` is empty when no inspected
  candidate was usable. Check the discovery diagnostics and inspected list.
- The job record works without corpus indexing. Set `index_public: true` or
  CLI `--index-public` to request indexing for eligible public evidence when the
  stack enables automatic indexing. Authenticated callers need corpus scope.

[Quick start](QUICKSTART.md) · [HTTP reference](HTTP-REFERENCE.md) · [Corpus](CORPUS.md)
