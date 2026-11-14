# News profile: engine policy and SearXNG 2026.11.6 (14 Nov 2026)

Twenty current-events queries (`evaluations/news-profile/run.py`), `profile=news`,
`limit=8`, search cache bypassed. Live 1.8.6 and the candidate (this branch's code
on SearXNG 2026.11.6 with Qwant News) ran alternately, twice, in the same window.

| Run | Results | Dated | Dated within 48 h | Undated landing pages | Distinct sites | Median |
|---|---|---|---|---|---|---|
| Live, earlier baseline | 158 | 7 | 1 | 48 | 135 | 0.78 s |
| Live, round 1 | 160 | 4 | 4 | 51 | 134 | 0.69 s |
| Candidate, round 1 | 160 | 125 | 65 | 0 | 131 | 0.84 s |
| Live, round 2 | 160 | 1 | 1 | 60 | 140 | 0.75 s |
| Candidate, round 2 | 160 | 147 | 83 | 0 | 128 | 1.91 s |

"Dated" counts provider- or page-declared dates only, never snippet hints.

## Round 3: Google News and Reuters engines (after the 1.8.7 deploy)

| Run | Results | Dated | Dated within 48 h | Landing pages | Distinct sites | Reuters links | Median |
|---|---|---|---|---|---|---|---|
| Live 1.8.7 | 160 | 125 | 68 | 0 | 135 | 1 | 1.25 s |
| Candidate | 160 | 153 | 98 | 0 | 143 | 27 | 1.43 s |

Files: `round3-live.json`, `round3-cand.json`. SearXNG's own Google News engine
scrapes `google.com/wml/search` (403 here) and its Reuters engine calls an API
behind DataDome (401 to plain and impersonated clients). The candidate queries
Google News RSS (200, every item dated, publisher named) and decodes each link
to the publisher's URL through Google's own article page and batchexecute call
(about 0.1 s each, in parallel). Reuters is the same engine with
`site:reuters.com`. It also stops sending SearXNG the `news` category alongside
named engines: SearXNG then added every news engine, which in 1.8.7 brought 50
undated Brave rows, Wikinews and the two failing scrapers into each search.

Reading Reuters articles remains blocked by DataDome on every tier, so Reuters
results are citable links whose reads fail honestly.

## Why live news was undated

The news profile already asked DuckDuckGo News through SearXNG, and every one of
its results is dated. Its rows entered the menu after DuckDuckGo web's ten and
were cut by the limit. The news profile now orders news engines first
(`src/dethrottled/engine_policy.py`), interleaved, inside the same caps:
DuckDuckGo News shares the single DuckDuckGo-family budget, and every other
engine keeps its three-result cap. Undated front, section and topic pages move
to the end. Other profiles are unchanged.

## Engines (five queries each, run directly against SearXNG)

| Engine | 2026.10.2 | 2026.11.6 |
|---|---|---|
| DuckDuckGo News | 26-28 rows, all dated | 107 rows, all dated, 80 within 48 h |
| Qwant News | access denied | 47 rows, all dated, 31 within 48 h |
| Brave News | crash | 228 rows, 2 dated: left off |
| Bing News (via SearXNG) | 7-10 rows, none dated | same: our direct Bing RSS keeps dates |
| Google News | access denied | access denied |
| Yahoo, Startpage, Mojeek News | no rows | no rows |
| Reuters | HTTP error | not retested |
| Presearch, Seekr News | not in this SearXNG version | |

Qwant News is enabled. SearXNG 2026.11.6 also moves its own `curl_cffi` from
0.16.3 to 0.17.0 (the API already pins 0.17.0), `certifi` to 2026.10.19 and
`python-dateutil` to 3.0.0. Its `publishedDate` format is unchanged
(`2026-11-13T14:42:00`), and `signals.parse_date` read 38 of 38 dated rows from
the new version and 28 of 28 from the old.

## Limits of this measurement

- No gold labels: it measures dated, recent and landing-page shares, not whether
  the best story was found.
- Round 2's candidate median (1.91 s) is not the policy: running 80 searches in a
  few minutes from one address got the candidate's DuckDuckGo web requests
  challenged, so Google News resolution ran to fill the menu. Round 1 (0.84 s
  against 0.69 s) is the fair comparison; Qwant answers in about 0.8 s.
- Live news providers change minute to minute; both rounds were alternated to
  share the same window.
