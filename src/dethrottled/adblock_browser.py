"""Chromium Fetch interception checks redirect hops as well as initial URLs.

Shared by Patchright and the pinned managed Crawl4AI Playwright worker. No page
JavaScript overrides. Existing scope/public-network interception stays in place.
"""

from __future__ import annotations

import asyncio
import base64

try:
    from . import adblock
except ImportError:  # Shared source copied into the private browser images.
    import dethrottled_adblock as adblock


async def attach(page):
    if not adblock.enabled():
        return
    task = getattr(page, "_dethrottled_adblock_task", None)
    if task is None:
        task = asyncio.create_task(_attach(page))
        page._dethrottled_adblock_task = task
    await task


async def _attach(page):
    session = await page.context.new_cdp_session(page)

    async def paused(event):
        domain = adblock.FILTER.match(event["request"]["url"])
        try:
            if domain:
                adblock.FILTER.blocked(domain, "browser")
                if event.get("resourceType") == "Document":
                    await session.send(
                        "Fetch.fulfillRequest",
                        {
                            "requestId": event["requestId"],
                            "responseCode": 451,
                            "responseHeaders": [
                                {"name": "X-Dethrottled-Blocked", "value": "adblock"},
                                {"name": "Content-Type", "value": "text/plain"},
                            ],
                            "body": base64.b64encode(
                                ("adblock_blocked:" + domain).encode()
                            ).decode(),
                        },
                    )
                else:
                    await session.send(
                        "Fetch.failRequest",
                        {"requestId": event["requestId"], "errorReason": "BlockedByClient"},
                    )
            else:
                await session.send("Fetch.continueRequest", {"requestId": event["requestId"]})
        except Exception:
            # Closing a tab detaches its protocol session; never log target URLs.
            if not page.is_closed():
                raise

    session.on("Fetch.requestPaused", paused)
    await session.send(
        "Fetch.enable", {"patterns": [{"urlPattern": "*", "requestStage": "Request"}]}
    )


async def context_ready(context):
    if not adblock.enabled():
        return context
    async def frontdoor(route, request):
        domain = adblock.FILTER.match(request.url)
        if domain:
            adblock.FILTER.blocked(domain, 'browser')
            if request.is_navigation_request():
                await route.fulfill(status=451, headers={'X-Dethrottled-Blocked': 'adblock'},
                                    body='adblock_blocked:' + domain)
            else:
                await route.abort('blockedbyclient')
            return
        # Context interception covers the first popup request before the page
        # event. Attach CDP before continuing it, so its redirects are covered too.
        try:
            await attach(request.frame.page)
        except Exception as exc:
            adblock.FILTER.error = 'browser_interception_failed:' + type(exc).__name__
            await route.abort('blockedbyclient')
            return
        await route.fallback()
    await context.route('**/*', frontdoor)
    # Popups also belong to this context. new_page below awaits interception;
    # the page event covers pages opened by page JavaScript.
    async def created(page):
        try:
            await attach(page)
        except Exception as exc:
            if not page.is_closed():
                adblock.FILTER.error = 'browser_interception_failed:' + type(exc).__name__
                await page.close()
    context.on("page", created)
    if hasattr(context, "route_web_socket"):

        async def socket(route):
            domain = adblock.FILTER.match(route.url)
            if domain:
                adblock.FILTER.blocked(domain, "websocket")
                await route.close(code=1008, reason="adblock_blocked:" + domain)
            else:
                await route.connect_to_server()

        await context.route_web_socket("**/*", socket)
    for page in context.pages:
        await attach(page)
    return context


def install(api):
    """Install once per private browser application, before creating contexts."""
    if getattr(api.Browser.new_context, "_dethrottled_filter", False):
        return
    original_context = api.Browser.new_context
    original_page = api.BrowserContext.new_page

    async def new_context(self, *args, **kwargs):
        if adblock.enabled():
            kwargs["service_workers"] = "block"
        return await context_ready(await original_context(self, *args, **kwargs))

    async def new_page(self, *args, **kwargs):
        page = await original_page(self, *args, **kwargs)
        await attach(page)
        return page

    new_context._dethrottled_filter = True
    api.Browser.new_context = new_context
    api.BrowserContext.new_page = new_page
