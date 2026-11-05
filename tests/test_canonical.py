"""canonical_url(): one URL per article, so the same page is not three rows.

Pure string work and the cheapest deduplication in the stack, which is exactly
why it is worth testing properly -- everything downstream keys on its output,
so a bug here shows up as mysterious duplicate results rather than as an error.
"""
import pytest

from dethrottled.fetch import canonical_url


@pytest.mark.parametrize("url,expected", [
    # Tracking parameters carry no meaning and split one article into several.
    ("https://example.com/a?utm_source=x&utm_medium=y", "https://example.com/a"),
    ("https://example.com/a?fbclid=123", "https://example.com/a"),
    ("https://example.com/a?gclid=1&id=7", "https://example.com/a?id=7"),
    # Real parameters are kept: dropping these would merge different pages.
    ("https://example.com/p?id=7&page=2", "https://example.com/p?id=7&page=2"),
    # The same article at a different host.
    ("https://www.example.com/a", "https://example.com/a"),
    ("https://m.example.com/a", "https://example.com/a"),
    ("https://amp.example.com/a", "https://example.com/a"),
    # Fragments address a place in a page, not a different page.
    ("https://example.com/a#section-3", "https://example.com/a"),
    # Trailing slash.
    ("https://example.com/a/", "https://example.com/a"),
    # Case in the host is not significant; case in the path is.
    ("https://EXAMPLE.com/Path", "https://example.com/Path"),
])
def test_canonicalises(url, expected):
    assert canonical_url(url) == expected


def test_root_path_survives():
    """A bare domain must keep its slash rather than becoming an empty path."""
    assert canonical_url("https://example.com/") == "https://example.com/"


@pytest.mark.parametrize("value", ["", "   ", "not a url", "mailto:a@b.c", "https://[bad"])
def test_rubbish_is_returned_unchanged(value):
    """Never raise on input. A URL that cannot be parsed is handed back as it
    arrived: dropping it would silently lose a search result, and raising would
    let one malformed row kill an entire response."""
    assert canonical_url(value) == value


def test_none_is_not_fatal():
    assert canonical_url(None) == ""


def test_two_forms_of_one_article_collapse():
    """The property the whole function exists for."""
    a = canonical_url("https://www.example.com/story?utm_campaign=twitter#top")
    b = canonical_url("https://m.example.com/story/")
    assert a == b


def test_tracking_prefixes_preserve_meaningful_query_pairs():
    url = ("https://example.com/a?UTM_source=x&FBCLID=z&ref_src=feed"
           "&id=7&id=8&empty=&q=caf%C3%A9&my_utm_source=keep")
    assert canonical_url(url) == (
        "https://example.com/a?id=7&id=8&empty=&q=caf%C3%A9&my_utm_source=keep")
