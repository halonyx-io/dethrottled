"""Install an in-process domain gate for managed Chromium contexts.

No request-routing/JavaScript overrides, service-worker restrictions or TLS MITM.
A per-context gate covers redirects, popups, subresources, workers and WebSockets.
"""

from __future__ import annotations

try:
    from . import adblock
    from .adblock_proxy import Gate
except ImportError:
    import dethrottled_adblock as adblock
    from dethrottled_adblock_proxy import Gate


def install(api):
    if getattr(api.Browser.new_context, "_dethrottled_filter", False):
        return
    original_context = api.Browser.new_context
    original_close = api.BrowserContext.close
    original_launch = api.BrowserType.launch
    original_goto = api.Page.goto
    original_browser_close = api.Browser.close

    async def launch(self, *args, **kwargs):
        browser = await original_launch(self, *args, **kwargs)
        browser._dethrottled_upstream_proxy = kwargs.get("proxy")
        return browser

    async def new_context(self, *args, **kwargs):
        if not adblock.enabled():
            return await original_context(self, *args, **kwargs)
        upstream = kwargs.get("proxy") or getattr(self, "_dethrottled_upstream_proxy", None)
        gate = Gate(upstream)
        kwargs["proxy"] = await gate.start()
        try:
            context = await original_context(self, *args, **kwargs)
        except BaseException:
            await gate.close()
            raise
        context._dethrottled_adblock_gate = gate
        context._dethrottled_adblock_events = gate.events
        return context

    async def goto(self, url, *args, **kwargs):
        adblock.check(url, "browser")
        refused = []

        def failed(request):
            if request.is_navigation_request():
                domain = adblock.FILTER.match(request.url)
                if domain:
                    refused.append(domain)

        self.on("requestfailed", failed)
        try:
            return await original_goto(self, url, *args, **kwargs)
        except Exception:
            if refused:
                raise adblock.AdblockBlocked(refused[-1]) from None
            raise
        finally:
            self.remove_listener("requestfailed", failed)

    async def close(self, *args, **kwargs):
        try:
            await original_close(self, *args, **kwargs)
        finally:
            gate = getattr(self, "_dethrottled_adblock_gate", None)
            if gate:
                await gate.close()

    async def browser_close(self, *args, **kwargs):
        contexts = list(self.contexts)
        try:
            await original_browser_close(self, *args, **kwargs)
        finally:
            for context in contexts:
                gate = getattr(context, "_dethrottled_adblock_gate", None)
                if gate:
                    await gate.close()

    new_context._dethrottled_filter = True
    api.Browser.close = browser_close
    api.Page.goto = goto
    api.BrowserType.launch = launch
    api.Browser.new_context = new_context
    api.BrowserContext.close = close
