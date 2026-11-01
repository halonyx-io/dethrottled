# Cold-agent workflow evaluation

This is a bounded task evaluation of published MCP instructions, schemas and tool
results, using Ollama's native tool-calling API. It is not a search-ranking,
throughput, universal OCR-accuracy, or multi-model benchmark.

Every case starts a new conversation with a common generic research-assistant
prompt, the chosen server's actual `initialize.instructions`, its complete
`tools/list` descriptions/schemas, and one task. The model receives no examples,
source layout, answer keys, coaching, local files, shell, or tools outside the MCP
server. Tool outcomes are fed back until a final answer or the fixed turn limit.
Temperature is zero; provider responses can nevertheless be nondeterministic.

The two arms are alternated within each case. Two fixture variants change the
answer values. Unique per-run URLs prevent extraction-cache reuse between runs.
Separate APIs/adapters isolate baseline and candidate state. Corpus indexing is
disabled in the fixture wrappers, and browser sessions observed in results are
closed after each run. Both versions use the same browser worker and model.

`run.py` saves a protocol/answer-key manifest before model calls, both published
MCP contracts, every visible conversation message and tool response, model usage
and timings, final answers, errors and individual score components. PNG image
blocks are saved separately under content hashes and referenced from JSON. No
provider private-reasoning field is recorded. Tokens come from a separate file;
no request headers or credentials are written to results. Runs are saved
incrementally, including unfinished/failed attempts.

The automatic score checks exact expected evidence, unit where applicable, an
observed source-tool result, grounding in returned content or inspected pixels,
and a source URL in the answer. The absent-answer case requires an explicit
acknowledgment that the expiry date is unavailable. The injection case rejects
the planted false number. The visual case separately requires an actual MCP image
block to reach the model. Inspect individual components and manually audit final
answers: conservative string rules can flag a correctly qualified answer as a
failure. Do not silently discard such records or change rules after seeing scores.

Eight cases cover deep text, later table rows, an image-based timetable, a
browser-generated CSV, later PDF pages, an absent answer, source prompt injection,
and a PDF chart requiring visual inspection. The export and visual cases were
also used in a development pilot. A confirmation batch after pilot-driven fixes
is not an independent unseen-task benchmark; it tests the frozen implementation
on the declared cases. Both pilot failures and confirmation results should be
retained and reported.

## Running

The evaluator uses only Python's standard library. Fixture generation additionally
needs Pillow and PyMuPDF, both installed in Dethrottled's full runtime. The
`make_assets.py` script writes `/evaluation/assets` for two fixture variants.
`fixture_server.py` serves those files on Docker bridge address 172.17.0.1:18901,
logging source requests. Source generation includes a deliberately untrusted
instruction as a negative control; it is data, not a benchmark instruction.

The loop expects two isolated MCP adapters on loopback ports 18388/18387 and a
working tool/vision-capable Ollama model. For example:

```sh
python evaluations/agent-workflow/run.py \
  --output work/agent-workflow-confirmation \
  --token-file work/private-evaluation-token \
  --model deepseek-v4.1-flash:cloud
```

The benchmark setup uses isolated wrappers to admit exactly the private fixture
server through the ordinary public-target checks. Those wrappers are evaluation
scaffolding, must never be deployed, and are included with the evidence bundle.
Public-target policy and inferred-host bounds are checked separately by
`check_adapters.py`, using the installed adapter dependencies. This exception is
necessary to serve deterministic private fixtures; the benchmark alone does not
prove public egress enforcement.

Use a new output directory for each batch. Preserve source hashes, image IDs,
fixture hashes, baseline commit, protocol, raw traces and request log. Keep
synthetic token/registry files and environment secrets outside publication.
Manual review and summary data should cite the raw run IDs. A published claim
must identify the model, cases, sample count, pilot tuning and any infrastructure
failures; do not extrapolate to all agents from this small suite.

See the [current evidence index](../../docs/EVIDENCE.md) and
[agent guide](../../docs/AGENT-UPGRADES.md) for present behavior.
