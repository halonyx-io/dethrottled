# Autonomous read-loop evaluation

This evaluation checks acquisition mechanisms with predefined facts. It does not
benchmark general research quality or establish an anti-bot success rate.

The fixture server exposes publisher Markdown, scroll-loaded text, expandable HTML
details, a primary JSON response, visitor cookies, normal text and unrelated JSON.
Run `python evaluations/read-loop/fixture.py` on a host reachable by both core
instances and the browser worker. It listens on port 8099. Start separate baseline
and candidate cores with separate data directories and caller namespaces. Configure
both to use the same browser worker; disable TLS and Crawl4AI for this controlled
comparison so those transports cannot obscure the mechanism being measured.

```sh
python evaluations/read-loop/compare.py \
  --baseline http://127.0.0.1:18792 \
  --candidate http://127.0.0.1:18793 \
  --fixture http://fixture-host:8099 --out /tmp/read-loop-evaluation
```

Use trusted local REST endpoints: public adapters correctly reject private fixtures.
Wait for the browser worker to be ready as well as both cores. The runner generates
new caller namespaces for each run. Cookie recovery follows an explicit seed read;
other-caller, manual-recovery and render-never cases must not recover the fact.
The runner also continues a scroll-recovered browser session through explicit drive.

[Recorded results](results/2026-11-02/REPORT.md) include the unsuccessful startup
pilot and a separate observational live run. Live records retain hashes, assertions,
quality and attempts rather than full third-party page bodies. No credentials or
browser state are published.
