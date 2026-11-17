"""Network policy for every browser context the worker opens.

Two lanes since 1.9.0. A context created with ``_dethrottled_lane="native"``
(public target, no host allowlist) on the public browser connects natively:
the kernel firewall (egress_firewall) confines that browser's UID to public
addresses, and the DNS filter applies the HaGeZi list. Every other context gets
a per-context CONNECT gate covering redirects, popups, subresources, workers
and WebSockets, as before, on a separate browser whose UID can reach only the
gate.
No JavaScript overrides or TLS MITM on either lane.
"""

from __future__ import annotations

import os

try:
    from . import adblock, browser_guard
    from .adblock_proxy import Gate
except ImportError:
    import dethrottled_adblock as adblock
    import dethrottled_browser_guard as browser_guard
    from dethrottled_adblock_proxy import Gate


def native_lane() -> bool:
    """True only when the start script loaded AND verified the egress firewall.

    DETHROTTLED_BROWSER_NETWORK=native with an unverified firewall never gets
    this far: the start script exits instead (fail closed). Anything run
    without that script (tests, a hand-started worker) uses the gate lane.
    """
    return (os.getenv("DETHROTTLED_BROWSER_NETWORK", "gate") == "native"
            and os.getenv("DETHROTTLED_EGRESS_FIREWALL") == "verified")


def browser_locale() -> str:
    """The machine's language as a context locale (en_GB.UTF-8 -> en-GB), or "".

    Set per context, it gives every page and worker one consistent language:
    the Accept-Language header and navigator.language(s). With Chrome's own
    default header for en-GB (en-GB,en-US;q=0.9,en;q=0.8), Reddit answered every
    read with its verification page; with the locale set it read them, and no
    other measured site changed (web-bench browser-settings-ab, round 11).
    """
    value = os.getenv("DETHROTTLED_BROWSER_LANG", "").split(".")[0].replace("_", "-")
    return value if 2 <= len(value) <= 12 and value.replace("-", "").isalpha() else ""


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
        lane = kwargs.pop("_dethrottled_lane", None)
        if browser_locale() and "locale" not in kwargs:
            kwargs["locale"] = browser_locale()
        upstream = kwargs.get("proxy") or getattr(self, "_dethrottled_upstream_proxy", None)
        if lane == "native" and native_lane() and not upstream:
            # Public context, filtering resolver running: no proxy, Chrome
            # connects itself (HTTP/3 included). See browser_guard.
            context = await original_context(self, *args, **kwargs)
            try:
                await browser_guard.install(context)
            except BaseException:
                await context.close()
                raise
            return context
        if not adblock.enabled():
            return await original_context(self, *args, **kwargs)
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
