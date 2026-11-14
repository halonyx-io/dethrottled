"""News-profile search quality on current-events queries; no gold labels needed.

    python evaluations/news-profile/run.py --endpoint http://127.0.0.1:8787 --out FILE
    python evaluations/news-profile/run.py --compare A.json B.json

Each query runs with profile=news, limit 8 and the search cache bypassed.
Scored on the returned menu only:

- dated: results with a provider- or page-declared date (not snippet hints);
- recent_48h: dated within 48 hours of the run;
- hub: undated front, section or topic pages (path depth <= 1, or a known
  aggregator topic page), which answer "where is the news" not "what happened";
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
    dated, recent, hubs = 0, 0, 0
    for row in rows:
        when = parse(row.get("published_at") or "") if row.get("published_at") else None
        if when:
            dated += 1
            recent += (now - when).total_seconds() <= 48 * 3600
        path = [part for part in urlsplit(row["url"]).path.split("/") if part]
        if not when and (len(path) <= 1 or "/topics/" in row["url"]):
            hubs += 1
    return {"results": len(rows), "dated": dated, "recent_48h": recent, "hub": hubs,
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
    keys = ("results", "dated", "recent_48h", "hub", "domains")
    ok = [row for row in data.values() if "error" not in row]
    summary = {key: sum(row[key] for row in ok) for key in keys}
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
