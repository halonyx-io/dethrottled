"""Upstream Crawl4AI extraction, invoked only inside bounded workers."""

import re

from crawl4ai import CrawlerRunConfig


def extract(url, html):
    config = CrawlerRunConfig()
    params = vars(config).copy()
    params.pop("url", None)
    result = config.scraping_strategy.scrap(url, html, **params)
    base = re.search(r'<base\s[^>]*href\s*=\s*["\']([^"\']+)["\']', html, re.I)
    markdown = config.markdown_generator.generate_markdown(
        input_html=result.cleaned_html, base_url=base.group(1) if base else url
    )
    return {
        "cleaned_html": result.cleaned_html,
        "markdown": markdown.model_dump(),
        "links": result.links.model_dump(),
        "media": result.media.model_dump(),
        "metadata": result.metadata,
        "success": bool(result.success and markdown.raw_markdown.strip()),
    }
