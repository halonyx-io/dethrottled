# Native browser recovery comparison

Run `python evaluations/drive-recovery/compare.py --control http://127.0.0.1:19905 --candidate http://127.0.0.1:19904 --out /tmp/drive-evidence` against two private browser workers.
Use the same candidate image and GPU configuration, with `DETHROTTLED_BROWSER_RECOVERY=off` on control and `auto` on candidate. Each source starts a fresh session. The runner closes its sessions, records failures and hashes text rather than publishing third-party bodies. URL queries are stripped from published observations.

The cases cover a Reddit thread/listing, neutral Python documentation and two hostile sources. Native sort-menu clicking, operation replay and continuation are tested on the thread. These are single-host observations, not a coverage benchmark or latency distribution. Separate ablations identify the preference cookie versus the copied Crawl4AI profile; automatic fetching disables other renderer tiers to expose the headed path.

See [results](results/2026-11-02/REPORT.md). Existing browser-contract fixtures are exercised separately with both recipe settings.
