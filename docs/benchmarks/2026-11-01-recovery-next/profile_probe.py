import asyncio
import json
import tempfile
import time
from pathlib import Path

from patchright.async_api import async_playwright

protocol = json.loads(Path("/evidence/live-protocol.json").read_text())


async def main():
    rows = []
    async with async_playwright() as p:
        for channel in ["chromium", "chrome"]:
            for case in protocol:
                with tempfile.TemporaryDirectory(prefix="profile-evaluation-") as directory:
                    start = time.monotonic()
                    row = {
                        "channel": channel,
                        "profile": "persistent/no_viewport/mesa",
                        "name": case["name"],
                        "url": case["url"],
                    }
                    context = None
                    try:
                        context = await p.chromium.launch_persistent_context(
                            directory,
                            channel=channel if channel == "chrome" else None,
                            headless=False,
                            no_viewport=True,
                            args=["--use-gl=angle", "--use-angle=gl", "--ignore-gpu-blocklist"],
                        )
                        row["browser_version"] = (
                            context.browser.version if context.browser else None
                        )
                        page = context.pages[0]
                        status = {}

                        def response(r, page=page, status=status):
                            if (
                                r.request.is_navigation_request()
                                and r.request.frame == page.main_frame
                            ):
                                status.update(
                                    status=r.status, challenge=r.headers.get("cf-mitigated", "")
                                )

                        page.on("response", response)
                        await page.goto(case["url"], wait_until="commit", timeout=12000)
                        for _ in range(10):
                            await page.wait_for_timeout(1000)
                            text = await page.locator("body").inner_text(timeout=2000)
                            signals = any(
                                x in text.lower()
                                for x in [
                                    "just a moment",
                                    "verify you are human",
                                    "verification required",
                                    "checking your browser",
                                    "please wait while we verify",
                                ]
                            )
                            if not signals and len(text) > 600:
                                break
                        row.update(
                            status,
                            chars=len(text),
                            markers_found=all(m.lower() in text.lower() for m in case["markers"]),
                            readable_candidate=bool(
                                not signals
                                and len(text) > 600
                                and status.get("status") == 200
                                and all(m.lower() in text.lower() for m in case["markers"])
                            ),
                            text_preview=text[:200],
                        )
                    except Exception as e:
                        row.update(
                            readable_candidate=False, error=type(e).__name__ + ":" + str(e)[:250]
                        )
                    finally:
                        if context:
                            await context.close()
                    row["elapsed_ms"] = round((time.monotonic() - start) * 1000)
                    rows.append(row)
                    Path("/evidence/profile-results.json").write_text(json.dumps(rows, indent=2))
                    print(
                        channel,
                        case["name"],
                        row.get("readable_candidate"),
                        row.get("error", ""),
                        flush=True,
                    )


asyncio.run(main())
