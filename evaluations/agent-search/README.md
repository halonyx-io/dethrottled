# Agent source-choice evaluation

This study compares search menus for an agent choosing pages to read. It does
not apply passage-ranking benchmark scores to search snippets or equate an
HTTP response with useful evidence.

The [recorded study](results/2026-11-03/REPORT.md) uses 120 questions, a frozen
80/40 development/held-out split, multiple reference pages and evidence facts,
provider-blind snippet judgements, an independent judgement audit, and separate
fetched-page checks. Ranking variants replay identical captured lists. Live
acquisition, pagination, bounded bursts and blocked-provider recovery are measured
separately in the actual Compose stack.

The reproducibility archive contains frozen candidate lists, labels, protocol,
selection lock, replay code, per-query results and sanitized observations. It
excludes credentials, browser state and bulk fetched third-party page bodies.
The report distinguishes model-assisted estimates, exact reference-page matches,
verified retained-text excerpts, controlled regression tests and live observations.
