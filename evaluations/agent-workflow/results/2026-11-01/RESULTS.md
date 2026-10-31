# Cold-agent evidence: 1 November 2026

Dethrottled 0.4.0 versus 0.5.0, using `deepseek-v4.1-flash:cloud` through Ollama.

| Measure | 0.4.0 | 0.5.0 |
| --- | ---: | ---: |
| Main confirmation, author-reviewed required answers, 16 model turns | 14/16 | 16/16 |
| Larger-budget fresh retests, 32 model turns | 4/4 | 4/4 |
| Unmodified mechanical scores in main confirmation | 9/16 | 12/16 |

The baseline was already capable; a larger budget let it recover the difficult
sources on fresh attempts. This supports improved guidance/recovery in a small
controlled suite, not a general accuracy or eventual-coverage superiority claim.

The 44 recorded conversations comprise four development pilots, 32 confirmation
runs, and eight larger-budget retests. Each starts with only a task, common
research-assistant instructions, and the real published MCP policy/tools. The
pilot cases were reused, so this is not an unseen-task holdout evaluation.

The raw scorer falsely rejected eight correct negative-control answers that
quoted an issue date or rejected injected number, plus a valid baseline result
decoded from an actual inline base64 CSV payload. All original scores remain;
[review decisions](manual-review.json) explain each outcome. Review covers the
required facts, evidence/citations and visual requirement, not every incidental
claim, and was performed by the implementation author rather than blinded judges.

See [per-case counts](case-results.md), [protocol](protocol.json),
[environment hashes](environment.json), and [the full evidence archive](evidence.zip).
The archive includes the full report, all visible conversations/tool results,
source fixtures, images, failed attempts, logs and reproduction scripts. It
excludes credentials and provider private reasoning. Its synthetic fixtures
include a deliberately untrusted instruction as a negative control; that text is
data, not an instruction to the reader.

The deterministic private fixture server required isolated target-check wrappers,
never deployed. Its nonstandard host/port contributed to setup errors; production
public-URL behavior was checked separately. General web discovery, real-world
noise, multiple agent clients/models and universal file-format access remain
outside this result. See the archive report for all limitations.
