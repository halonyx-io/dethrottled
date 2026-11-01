# Recorded coverage checks

`components.py` declares 22 controlled parser/range/structure tasks before
execution and records full text, metadata, timings and expected values. Run it
inside each API image with writable `/evidence`; place table.pdf under
/evidence/fixtures. The recorded fixture server and browser runner are included
in the release evidence archive, together with the actual PDF bytes.

`web.py` declares 40 paired discovery/source tasks (80 checks), including two
non-English queries, official documentation and structured public data. It saves
raw responses, expected domains/phrases and elapsed times. A domain hit is not a
relevance or semantic-correctness judgment; a phrase hit is not verification of
an answer. Public sources and search engines can change between sequential runs.

The eight browser workflows use real headed Chromium against controlled pages.
They test chunked JSON, decoded size limits, frame reading/action, popup reading,
four storage types across restart, action history, and file downloads.

The suite therefore has 110 mechanical checks per build, not 110 independent
research questions. Fresh model conversations are separate qualitative evidence;
never include them in this mechanical denominator. Contract unit tests, this
coverage suite and a paid-product comparison answer different questions.

Run web.py with Python 3; configure DETHROTTLED_EVAL_OUTPUT,
DETHROTTLED_EVAL_BASELINE_URL and DETHROTTLED_EVAL_CANDIDATE_URL as needed.
Defaults are evaluation-results, http://127.0.0.1:18396 and http://127.0.0.1:8787.
Model/account credentials are never needed for this suite. Paid comparisons must
be recorded separately and must not silently substitute cached local results.

See the [current evidence index](../../docs/EVIDENCE.md) and
[agent guide](../../docs/AGENT-UPGRADES.md) for present behavior.
