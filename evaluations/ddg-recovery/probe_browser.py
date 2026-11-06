import argparse
import asyncio
import hashlib
import json
import os
import time

import service
from patchright.async_api import async_playwright

os.environ.setdefault("DISPLAY", ":99")
q = "Were Scott Derrickson and Ed Wood of the same nationality?"


async def main():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=False)
        rows = []
        try:
            for mode in ["lite-get", "html-form", "js-main"]:
                if rows:
                    await asyncio.sleep(4)
                context = await browser.new_context()
                page = await context.new_page()
                t = time.perf_counter()
                try:
                    if mode == "lite-get":
                        a = await service._engine(context, "ddg-lite", q, 0, 10)
                        rows.append({"variant": mode, "attempt": a})
                        continue
                    if mode == "html-form":
                        response = await page.goto(
                            "https://html.duckduckgo.com/html/",
                            wait_until="domcontentloaded",
                            timeout=8000,
                        )
                        await page.locator("input[name=q]").first.fill(q)
                        async with page.expect_navigation(
                            wait_until="domcontentloaded", timeout=8000
                        ) as nav:
                            await page.locator("input[name=q]").first.press("Enter")
                        response = await nav.value
                        result = await service._extract(page, "ddg-html", q, 10)
                    else:
                        response = await page.goto(
                            "https://duckduckgo.com/?q=" + service.quote_plus(q) + "&ia=web",
                            wait_until="domcontentloaded",
                            timeout=8000,
                        )
                        await page.locator('[data-testid="result-title-a"]').first.wait_for(
                            timeout=7000
                        )
                        result = await page.locator('[data-testid="result-title-a"]').evaluate_all(
                            "(els)=>els.slice(0,10).map(e=>({title:e.innerText,url:e.href}))"
                        )
                    body = await page.content()
                    rows.append(
                        {
                            "variant": mode,
                            "status": response.status if response else None,
                            "seconds": time.perf_counter() - t,
                            "result_count": len(result),
                            "sample_results": result[:3],
                            "body_sha256": hashlib.sha256(body.encode()).hexdigest(),
                            "challenge_markers": [
                                m
                                for m in ["anomaly.js", "bots use duckduckgo"]
                                if m in body.lower()
                            ],
                        }
                    )
                except Exception as e:
                    rows.append(
                        {
                            "variant": mode,
                            "seconds": time.perf_counter() - t,
                            "error": type(e).__name__,
                        }
                    )
                finally:
                    await context.close()
            print(json.dumps(rows, indent=2))
        finally:
            await browser.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Live browser DDG acquisition controls")
    parser.add_argument("--live", action="store_true", required=True)
    parser.parse_args()
    asyncio.run(main())
