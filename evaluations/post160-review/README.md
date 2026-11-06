# Post-1.6.0 review: refreshes, streams and client contracts

Uncommitted candidate; no publication, deployment, runtime dependency or model
change. [Results and cumulative change summary](results/2026-11-06/REPORT.md).
Earlier PDF/corpus evidence remains in [the retrieval review](../retrieval-review/README.md).

Use a disposable `dethrottled:1.6.0` image container, candidate checkout mounted
at `/work`, and disposable `DETHROTTLED_DATA_DIR`. The release package is selected
with empty `PYTHONPATH`; `/work/src` selects the candidate. Disable automatic
blocklist updates for ordinary tests. Enable filtering only for the explicit
refresh/stream harnesses below. They use no upstream network or production state.

For refresh measurements supply a **public list snapshot**, not tokens/browser
state, at `/tmp/list.json`. This is the updater's `multi-pro.json` (body and
validators). The retained run used 222,452 rules with SHA-256
`60d08482e3de2686856a32e7ef5c05e6723d8f1fa659caed80e7effeac08dbfa`.
The harness copies it into a new temporary directory for every process.

```sh
DETHROTTLED_ADBLOCK=1 PYTHONPATH= python /work/evaluations/post160-review/refresh.py --label baseline
DETHROTTLED_ADBLOCK=1 PYTHONPATH=/work/src python /work/evaluations/post160-review/refresh.py --label candidate
DETHROTTLED_ADBLOCK=1 PYTHONPATH= python /work/evaluations/post160-review/streams.py --label baseline
DETHROTTLED_ADBLOCK=1 PYTHONPATH=/work/src python /work/evaluations/post160-review/streams.py --label candidate
PYTHONPATH= python /work/evaluations/post160-review/crawl.py --label baseline
PYTHONPATH=/work/src python /work/evaluations/post160-review/crawl.py --label candidate
```

Repeat refresh/stream pairs three times, alternating order. Run measurements
sequentially. The stream harness uses real loopback sockets, a 4 MiB HTTP body,
a valid WebSocket handshake/masked frames, and a deterministic mid-transfer rule
change. CONNECT/TLS pass-through and redirect/chaining coverage remain in the
regression suite. A baseline transfer terminated by policy is a failed transfer,
not a throughput baseline against which to claim speed gains.

The refresh benchmark models one updater and three readers in one process;
CPU is process time, not a production aggregate or acquisition speedup. Initial
setup failed because the copied public snapshot was unreadable by the test UID;
permissions were corrected in the disposable container before measurements.
The initial diagnostic measurement is retained separately from three paired runs.
The adapter verifier initially needed its lockfile beside the copied harness;
it passed after preparing that documented image-style layout in a temporary
support directory. Neither setup issue changed production or package inputs.
