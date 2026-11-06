# Long PDFs and corpus candidate diagnostics

Uncommitted candidate based on 1.6.0. See the [findings and limits](results/2026-11-06/REPORT.md).
The harness uses fixed files and an isolated corpus; it never reads production
state or searches upstream. Acquire the RFC fixture once, then replay identical
bytes against the released and candidate packages. No benchmark score is rewritten.

The recorded comparison used the local immutable `dethrottled:1.6.0` release
image, an isolated disposable container, and a candidate checkout mounted at
`/work`. The image contains the existing MiniLM/E5 weights. It requires no new
models or product dependencies. Tests additionally require the development extra.

```sh
curl --fail --location https://www.rfc-editor.org/rfc/rfc9110.pdf -o /tmp/rfc9110.pdf
sha256sum /tmp/rfc9110.pdf
```

Expected SHA-256:
`60b30efa1048900833d1758440247fe8ac85a3134f2327388dcb24e07d814c89`.
This matches the independent benchmark's retained `p08` bytes.

Inside the isolated release-image container, copy that file to `/tmp/rfc9110.pdf`
and run each command in a separate fresh process. An empty `PYTHONPATH` selects
its released site-packages; `/work/src` selects candidate source. Set
`DETHROTTLED_ADBLOCK=0` and `DETHROTTLED_DATA_DIR` to a disposable directory.

```sh
PYTHONPATH= python /work/evaluations/retrieval-review/evaluate.py pdf --label baseline
PYTHONPATH=/work/src python /work/evaluations/retrieval-review/evaluate.py pdf --label candidate
PYTHONPATH= python /work/evaluations/retrieval-review/evaluate.py pdf --mode native --label baseline
PYTHONPATH=/work/src python /work/evaluations/retrieval-review/evaluate.py pdf --mode native --label candidate
PYTHONPATH= python /work/evaluations/retrieval-review/evaluate.py corpus --label baseline
PYTHONPATH=/work/src python /work/evaluations/retrieval-review/evaluate.py corpus --label candidate
PYTHONPATH=/work/src python /work/evaluations/retrieval-review/api_check.py
```

Repeat PDF modes three times with alternating baseline/candidate order. The API
check uses real parsing, retention and API serialization with a fixture transport
and a forbidden browser callback; no upstream fetch or production change occurs.
Corpus cases use actual packaged models against four synthetic sources, twelve
labelled questions, three retrieval modes and both support policies. Labels measure
whether returned sources support the predefined task, separately from retrieval
success. This is a diagnostic pilot, not a general retrieval-quality benchmark.

`pdf-before-regressions.txt` retains the original four failing assertions. JSON
files retain timings, CPU time, per-process peak RSS, fact results and negative
corpus outcomes. Shared-host load limits performance conclusions; inspect the
report before quoting any latency or memory number.
