"""Real browser/renderer OFF/ON controls; all acquisition uses local fixtures."""

import argparse
import asyncio
import hashlib
import json
import os
import resource
import statistics
import sys
import time
from pathlib import Path

from fixtures import FACTS, TRACKER, Fixture

parser = argparse.ArgumentParser()
parser.add_argument("--list", required=True)
parser.add_argument("--backend", choices=["patchright", "crawl4ai"], required=True)
parser.add_argument("--output", required=True)
args = parser.parse_args()
if args.backend == "patchright":
    sys.path.insert(0, "/app")
    import service
    import dethrottled_adblock as adblock
    import patchright.async_api as api
else:
    import playwright.async_api as api
    import dethrottled_adblock as adblock
    import dethrottled_adblock_browser as browser_filter

    browser_filter.install(api)

blob = Path(args.list).read_bytes()
start = time.monotonic()
rules = adblock.parse(blob)
load_ms = (time.monotonic() - start) * 1000
adblock.FILTER.rules = rules
adblock.FILTER.start = lambda: None
report = {
    "backend": args.backend,
    "architecture": os.uname().machine,
    "list_sha256": hashlib.sha256(blob).hexdigest(),
    "rules": len(rules),
    "parse_ms": load_ms,
    "cases": [],
    "limitations": [
        "Local simulated challenge script, not proof of passing a real hostile challenge",
        "Traffic is origin response-body bytes, excluding transport overhead",
        "RSS is fresh harness plus Python/extractor libraries; browser child RSS reported separately",
    ],
}
fixture = Fixture()
launch_args = [
    "--no-sandbox",
    "--no-proxy-server",
    "--ignore-certificate-errors",
    "--host-resolver-rules=MAP *.example 127.0.0.1, MAP *.google-analytics.com 127.0.0.1, MAP challenges.cloudflare.com 127.0.0.1",
]


async def main():
    for enabled in (False, True):
        os.environ["DETHROTTLED_ADBLOCK"] = "1" if enabled else "0"
        if args.backend == "crawl4ai":
            from crawl4ai import AsyncWebCrawler, BrowserConfig, CacheMode, CrawlerRunConfig

            async with AsyncWebCrawler(
                config=BrowserConfig(headless=True, extra_args=launch_args)
            ) as crawler:
                failures = []

                async def capture(page, failures=failures, **kwargs):
                    page.on(
                        "requestfailed",
                        lambda r: failures.append({"url": r.url, "reason": r.failure}),
                    )

                crawler.crawler_strategy.set_hook("on_page_context_created", capture)
                for repetition in range(3):
                    fixture.reset()
                    started = time.monotonic()
                    result = await crawler.arun(
                        f"http://content.example:{fixture.port}/page",
                        config=CrawlerRunConfig(
                            cache_mode=CacheMode.BYPASS,
                            page_timeout=10000,
                            delay_before_return_html=0.2,
                            js_code="document.querySelector('#open').click()",
                        ),
                    )
                    text = result.cleaned_html or ""
                    report["cases"].append(
                        {
                            "enabled": enabled,
                            "repetition": repetition,
                            "elapsed_ms": (time.monotonic() - started) * 1000,
                            "ok": result.success,
                            "fact_hits": sum(f in text for f in FACTS),
                            "facts": len(FACTS),
                            "traffic": dict(fixture.counts),
                            "failures": failures[-20:],
                            "html_sample": (result.html or "")[:400],
                        }
                    )
                fixture.reset()
                redirected = await crawler.arun(
                    f"http://content.example:{fixture.port}/redirect",
                    config=CrawlerRunConfig(cache_mode=CacheMode.BYPASS, page_timeout=10000),
                )
                report["cases"].append(
                    {
                        "enabled": enabled,
                        "kind": "redirect",
                        "tracking_requests": fixture.counts["tracking_requests"],
                        "status": redirected.status_code,
                        "error": str(redirected.error_message)[:300],
                    }
                )
        else:
            async with api.async_playwright() as p:
                browser = await p.chromium.launch(headless=False, args=launch_args)
                for repetition in range(3):
                    fixture.reset()
                    state = await service._make_drive_state(browser, [])
                    started = time.monotonic()
                    output = await service._drive(
                        state,
                        service.DriveRequest(
                            url=f"http://content.example:{fixture.port}/page",
                            screenshot="never",
                            steps=[
                                {"action": "wait_for", "selector": '#challenge:has-text("6193")'},
                                {"action": "click", "selector": "#open"},
                                {"action": "text", "selector": "body", "max_chars": 10000},
                            ],
                        ),
                    )
                    text = str(output["steps"])
                    await asyncio.sleep(0.2)
                    report["cases"].append(
                        {
                            "enabled": enabled,
                            "repetition": repetition,
                            "elapsed_ms": (time.monotonic() - started) * 1000,
                            "ok": output["ok"],
                            "fact_hits": sum(f in text for f in FACTS),
                            "facts": len(FACTS),
                            "traffic": dict(fixture.counts),
                            "access": output["access"],
                        }
                    )
                    await state["context"].close()
                # Redirect, popup, downloads and existing public-target guard.
                for kind in ["redirect", "popup", "download", "public_target"]:
                    fixture.reset()
                    state = await service._make_drive_state(
                        browser, [], public_only=kind == "public_target"
                    )
                    page = state["page"]
                    outcome = {}
                    try:
                        if kind == "redirect":
                            response = await page.goto(
                                f"http://content.example:{fixture.port}/redirect"
                            )
                            outcome["status"] = response.status
                        elif kind == "popup":
                            await page.goto(f"http://content.example:{fixture.port}/page")
                            async with page.expect_popup() as event:
                                await page.click("#popup")
                            popup = await event.value
                            await popup.wait_for_load_state()
                            outcome["popup_url"] = popup.url
                        elif kind == "download":
                            await page.goto(f"http://content.example:{fixture.port}/page")
                            async with page.expect_download() as event:
                                await page.click("#download")
                            download = await event.value
                            outcome["fact_retained"] = (
                                FACTS[0] in Path(await download.path()).read_text()
                            )
                        else:
                            await page.goto(f"http://127.0.0.1:{fixture.port}/page", timeout=3000)
                    except Exception as exc:
                        outcome["error"] = type(exc).__name__ + ":" + str(exc)[:160]
                    await asyncio.sleep(0.1)
                    report["cases"].append(
                        {
                            "enabled": enabled,
                            "kind": kind,
                            "traffic": dict(fixture.counts),
                            **outcome,
                        }
                    )
                    await state["context"].close()
                await browser.close()
    report["blocked"] = adblock.FILTER.status()["blocked_requests"]
    report["maxrss_kib"] = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    report["browser_children_maxrss_kib"] = resource.getrusage(resource.RUSAGE_CHILDREN).ru_maxrss
    normal = [r for r in report["cases"] if "repetition" in r]
    report["normal_cases_passed"] = all(r["ok"] and r["fact_hits"] == r["facts"] for r in normal)
    report["normal_summary"] = {
        str(enabled): {
            "median_ms": statistics.median(
                r["elapsed_ms"] for r in normal if r["enabled"] == enabled
            ),
            "body_bytes": [r["traffic"]["body_bytes"] for r in normal if r["enabled"] == enabled],
            "tracking_requests": [
                r["traffic"].get("tracking_requests", 0) for r in normal if r["enabled"] == enabled
            ],
        }
        for enabled in (False, True)
    }


try:
    asyncio.run(main())
finally:
    fixture.stop()
    Path(args.output).write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report.get("normal_summary", {})))
