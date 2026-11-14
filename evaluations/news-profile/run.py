"""News-profile search quality on current-events queries; no gold labels needed.

    python evaluations/news-profile/run.py --endpoint http://127.0.0.1:8787 --out FILE
    python evaluations/news-profile/run.py --compare A.json B.json

Each query runs with profile=news, limit 8 and the search cache bypassed.
Scored on the returned menu only:

- dated: results with a provider- or page-declared date (not snippet hints);
- recent_48h: dated within 48 hours of the run;
- hub: undated front, section or topic pages (path depth <= 1, or a known
  aggregator topic page), which answer "where is the news" not "what happened";
- landing_dated: front pages that carry a date anyway (reuters.com/ dated 2005);
- stale_top4: results dated more than 7 days ago in the first four places;
- social: social-network posts (Facebook, X, Instagram, TikTok, Threads, ...);
- domains: distinct sites, so one publisher cannot fill the menu;
- elapsed: wall time per query.

Run baseline and candidate in the same window, alternating per query, because
news providers change minute to minute.
"""
import argparse
import json
import time
import urllib.request
from datetime import datetime, timezone
from urllib.parse import urlsplit

QUERIES = [
    "FAA ground stop", "Trump Xi meeting", "Nvidia news", "OpenAI news", "Anthropic IPO",
    "stock market today", "Federal Reserve interest rates", "Bitcoin price news",
    "Ukraine war latest", "Gaza ceasefire", "earthquake today", "hurricane warning",
    "SpaceX launch", "Apple announcement", "Microsoft layoffs", "climate summit",
    "election results", "tech news today", "world news today", "AI regulation news",
    "news headlines today", "breaking news",
]


def search(endpoint, query):
    body = json.dumps({"query": query, "limit": 8, "profile": "news",
                       "cache_mode": "bypass"}).encode()
    request = urllib.request.Request(endpoint + "/v2/search", body,
                                     {"Content-Type": "application/json"})
    started = time.monotonic()
    with urllib.request.urlopen(request, timeout=120) as response:
        data = json.load(response)
    return data, time.monotonic() - started


def parse(value):
    try:
        when = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        return when if when.tzinfo else when.replace(tzinfo=timezone.utc)
    except ValueError:
        return None


def score(data, elapsed, now):
    rows = data.get("results", [])
    dated, recent, hubs, landing_dated, stale_top4, social = 0, 0, 0, 0, 0, 0
    social_hosts = ("facebook.com", "x.com", "twitter.com", "instagram.com", "tiktok.com",
                    "threads.net", "threads.com", "linkedin.com", "pinterest.com")
    for position, row in enumerate(rows):
        when = parse(row.get("published_at") or "") if row.get("published_at") else None
        if when:
            dated += 1
            recent += (now - when).total_seconds() <= 48 * 3600
        path = [part for part in urlsplit(row["url"]).path.split("/") if part]
        landing = len(path) == 0 or (len(path) == 1 and len(path[0]) <= 24)
        if not when and (len(path) <= 1 or "/topics/" in row["url"]):
            hubs += 1
        if when and landing:
            landing_dated += 1
        if when and position < 4 and (now - when).total_seconds() > 7 * 86400:
            stale_top4 += 1
        host = (urlsplit(row["url"]).hostname or "").lower()
        social += any(host == h or host.endswith("." + h) for h in social_hosts)
    return {"results": len(rows), "dated": dated, "recent_48h": recent, "hub": hubs,
            "landing_dated": landing_dated, "stale_top4": stale_top4, "social": social,
            "domains": len({urlsplit(r["url"]).hostname for r in rows}),
            "elapsed": round(elapsed, 2),
            "urls": [r["url"] for r in rows]}


def run(args):
    now = datetime.now(timezone.utc)
    out = {"endpoint": args.endpoint, "at": now.isoformat(), "queries": {}}
    for query in QUERIES:
        try:
            data, elapsed = search(args.endpoint, query)
            out["queries"][query] = score(data, elapsed, now)
        except Exception as exc:  # recorded, never hidden
            out["queries"][query] = {"error": type(exc).__name__}
        print(query, out["queries"][query].get("dated"), out["queries"][query].get("elapsed"),
              flush=True)
    with open(args.out, "w") as handle:
        json.dump(out, handle, indent=1)


def totals(path):
    data = json.load(open(path))["queries"]
    keys = ("results", "dated", "recent_48h", "hub", "landing_dated", "stale_top4", "social",
            "domains")
    ok = [row for row in data.values() if "error" not in row]
    summary = {key: sum(row.get(key, 0) for row in ok) for key in keys}
    summary["errors"] = len(data) - len(ok)
    times = sorted(row["elapsed"] for row in ok)
    summary["median_s"] = times[len(times) // 2] if times else None
    return summary


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--endpoint")
    parser.add_argument("--out")
    parser.add_argument("--compare", nargs=2)
    args = parser.parse_args()
    if args.compare:
        for path in args.compare:
            print(path, totals(path))
    else:
        run(args)


if __name__ == "__main__":
    main()
