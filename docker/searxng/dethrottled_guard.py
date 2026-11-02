"""Rate-limit adapter for the pinned Compose SearXNG version."""

from searx.exceptions import SearxEngineAccessDeniedException
from searx.network import network
from searx.plugins import Plugin, PluginInfo
from searx.plugins.dethrottled_retry_after import respecting_retry_after


class SXNGPlugin(Plugin):
    id = "dethrottled_guard"

    def __init__(self, plg_cfg):
        super().__init__(plg_cfg)
        self.info = PluginInfo(
            id=self.id,
            name="Dethrottled upstream cooldowns",
            description="Honor upstream Retry-After on search-engine refusals",
            preference_section="general",
        )
        network.raise_for_httperror = respecting_retry_after(
            network.raise_for_httperror, SearxEngineAccessDeniedException
        )
