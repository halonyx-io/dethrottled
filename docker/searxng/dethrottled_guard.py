"""Rate-limit adapter for the pinned Compose SearXNG version."""

from searx.exceptions import SearxEngineAccessDeniedException
from searx.network import network
from searx.plugins import Plugin, PluginInfo
from searx.plugins.dethrottled_retry_after import respecting_retry_after


class SXNGPlugin(Plugin):
    id = "dethrottled_guard"

    def __init__(self, plg_cfg):
        super().__init__(plg_cfg)
        install_adblock()
        self.info = PluginInfo(
            id=self.id,
            name="Dethrottled upstream cooldowns",
            description="Honor upstream Retry-After on search-engine refusals",
            preference_section="general",
        )
        network.raise_for_httperror = respecting_retry_after(
            network.raise_for_httperror, SearxEngineAccessDeniedException
        )


def install_adblock():
    """Guard pinned curl_cffi AsyncClient before each engine/redirect request."""
    import os

    if os.getenv("DETHROTTLED_ADBLOCK", "1") == "0":
        return
    from urllib.parse import urljoin, urlsplit

    from searx.network.client import AsyncClient
    from searx.plugins import dethrottled_adblock as adblock

    if getattr(AsyncClient.request, "_dethrottled_filter", False):
        return
    original = AsyncClient.request

    async def request(self, method, url, *args, **kwargs):
        if not adblock.enabled():
            return await original(self, method, url, *args, **kwargs)
        follow = kwargs.pop("allow_redirects", True)
        for _ in range(21):
            adblock.FILTER.check(url, "searxng")
            response = await original(
                self, method, url, *args, **dict(kwargs, allow_redirects=False)
            )
            location = response.headers.get("Location")
            if not follow or response.status_code not in {301, 302, 303, 307, 308} or not location:
                return response
            target = urljoin(url, location)
            if urlsplit(url)[:2] != urlsplit(target)[:2]:
                for key in ("auth", "cookies"):
                    kwargs.pop(key, None)
                if kwargs.get("headers"):
                    kwargs["headers"] = {
                        k: v
                        for k, v in kwargs["headers"].items()
                        if k.lower() not in {"authorization", "cookie"}
                    }
            if response.status_code == 303 or (
                response.status_code in {301, 302} and method.upper() == "POST"
            ):
                method = "GET"
                for key in ("data", "json", "files"):
                    kwargs.pop(key, None)
            kwargs.pop("params", None)
            url = target
        raise ValueError("too_many_redirects")

    request._dethrottled_filter = True
    AsyncClient.request = request
    adblock.FILTER.start()
