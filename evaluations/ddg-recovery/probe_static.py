import argparse
import hashlib
import json
import time
from urllib.parse import quote_plus

from curl_cffi import requests as curl
from selectolax.lexbor import LexborHTMLParser

from dethrottled import adblock, netfilter


def main():
    parser = argparse.ArgumentParser(description="Live static DDG acquisition controls")
    parser.add_argument("--live", action="store_true", required=True)
    parser.parse_args()
    q = "Were Scott Derrickson and Ed Wood of the same nationality?"
    rows = []
    for label, host, method in [
        ("plain-lite-get", "lite", "plain"),
        ("tls-lite-get", "lite", "get"),
        ("tls-lite-form", "lite", "post"),
        ("tls-html-form", "html", "post"),
        ("tls-html-get", "html", "get"),
    ]:
        if rows:
            time.sleep(4)
        base = f"https://{host}.duckduckgo.com/{host}/"
        url = base + "?q=" + quote_plus(q)
        t = time.perf_counter()
        try:
            adblock.check(base)
            if method == "plain":
                r = netfilter.get(url, timeout=8)
            elif method == "get":
                r = netfilter.get_using(curl.get, url, impersonate="chrome", timeout=8)
            else:
                r = curl.post(
                    base,
                    data={"q": q, "b": ""},
                    impersonate="chrome",
                    headers={
                        "Referer": f"https://{host}.duckduckgo.com/",
                        "Sec-Fetch-Mode": "navigate",
                        "Sec-Fetch-Site": "same-origin",
                        "Sec-Fetch-Dest": "document",
                    },
                    timeout=8,
                    allow_redirects=False,
                )
            html = r.text
            tree = LexborHTMLParser(html)
            links = tree.css("a.result-link" if host == "lite" else "a.result__a")
            snips = tree.css(".result-snippet" if host == "lite" else ".result__snippet")
            rows.append(
                {
                    "variant": label,
                    "query": q,
                    "observed_at": time.time(),
                    "status": r.status_code,
                    "seconds": time.perf_counter() - t,
                    "body_sha256": hashlib.sha256(html.encode()).hexdigest(),
                    "body_chars": len(html),
                    "result_count": len(links),
                    "sample_results": [
                        {
                            "title": link.text(strip=True),
                            "url": link.attributes.get("href"),
                            "snippet": snips[i].text(strip=True) if i < len(snips) else "",
                        }
                        for i, link in enumerate(links[:3])
                    ],
                    "challenge_markers": [
                        m
                        for m in [
                            "anomaly.js",
                            "bots use duckduckgo",
                            "challenge-platform",
                            "select all squares",
                        ]
                        if m in html.lower()
                    ],
                    "retry_after": r.headers.get("Retry-After"),
                }
            )
        except Exception as e:
            rows.append(
                {
                    "variant": label,
                    "query": q,
                    "observed_at": time.time(),
                    "seconds": time.perf_counter() - t,
                    "error": type(e).__name__,
                }
            )
        print(json.dumps(rows[-1]), flush=True)


if __name__ == "__main__":
    main()
