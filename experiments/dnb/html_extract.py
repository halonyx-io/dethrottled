"""Upstream Crawl4AI extraction, invoked only inside bounded workers."""

import re

from crawl4ai import CrawlerRunConfig

# Emphasis inside a word ("<em>ser</em>ializing") cannot be written in
# Markdown, so the generator separates it ("_ser_ ializing") and the word is
# lost to search and evidence matching. Unwrap such tags before generation:
# the emphasis goes, the word stays whole.
_INTRAWORD_EMPHASIS = re.compile(
    r"(?:(?<=\w)<(em|i|strong|b)(?:\s[^>]*)?>([^<\s][^<]*)</\1>"
    r"|<(em|i|strong|b)(?:\s[^>]*)?>([^<]*[^<\s])</\3>(?=\w))",
    re.I,
)


def _unwrap_intraword_emphasis(html):
    return _INTRAWORD_EMPHASIS.sub(lambda m: m.group(2) or m.group(4) or "", html or "")


def extract(url, html):
    config = CrawlerRunConfig()
    params = vars(config).copy()
    params.pop("url", None)
    result = config.scraping_strategy.scrap(url, html, **params)
    base = re.search(r'<base\s[^>]*href\s*=\s*["\']([^"\']+)["\']', html, re.I)
    markdown = config.markdown_generator.generate_markdown(
        input_html=_unwrap_intraword_emphasis(result.cleaned_html),
        base_url=base.group(1) if base else url,
    )
    return {
        "cleaned_html": result.cleaned_html,
        "markdown": markdown.model_dump(),
        "links": result.links.model_dump(),
        "media": result.media.model_dump(),
        "metadata": result.metadata,
        "success": bool(result.success and markdown.raw_markdown.strip()),
    }
