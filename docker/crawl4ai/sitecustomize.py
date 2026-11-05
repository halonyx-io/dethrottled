"""Pinned Crawl4AI integration, loaded through the managed worker's PYTHONPATH."""

import os

if os.getenv("DETHROTTLED_ADBLOCK", "1") != "0":
    import dethrottled_adblock as adblock
    import dethrottled_adblock_browser as browser_filter
    import playwright.async_api as api

    adblock.FILTER.start()
    browser_filter.install(api)
