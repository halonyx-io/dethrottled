"""RSS and Atom feeds come back as dated items, newest first, not XML source."""
import pytest
from defusedxml import EntitiesForbidden

from dethrottled import fetch as f
from dethrottled import formats

RSS = b"""<?xml version="1.0"?><rss version="2.0"><channel><title>Wire</title>
<link>https://wire.example/</link>
<item><title>Older story</title><link>https://wire.example/old</link>
<pubDate>Wed, 12 Nov 2026 08:00:00 GMT</pubDate>
<description>&lt;p&gt;Old body&lt;/p&gt;</description></item>
<item><title>Newest story</title><link>https://wire.example/new</link>
<pubDate>Fri, 14 Nov 2026 09:30:00 GMT</pubDate><description>Fresh body</description></item>
<item><title>No date</title><link>https://wire.example/undated</link></item>
</channel></rss>"""

ATOM = b"""<?xml version="1.0" encoding="utf-8"?>
<feed xmlns="http://www.w3.org/2005/Atom"><title>Releases</title>
<link href="https://code.example/releases"/>
<entry><title>v2.0</title><link href="https://code.example/v2"/>
<updated>2026-11-10T16:57:17Z</updated><summary>Second</summary></entry>
<entry><title>v1.0</title><link href="https://code.example/v1"/>
<updated>2026-10-01T00:00:00Z</updated></entry></feed>"""


def test_rss_is_read_as_dated_items_newest_first():
    text, metadata = formats.read_blob(RSS, "xml", 100000)
    assert "<item>" not in text and "<rss" not in text
    assert text.index("Newest story") < text.index("Older story") < text.index("No date")
    assert "2026-11-14 09:30 UTC - Newest story" in text and "Fresh body" in text
    assert "<p>" not in text  # summaries are text, not markup
    feed = metadata["feed"]
    assert feed["items"] == 3 and feed["newest"].startswith("2026-11-14T09:30")
    assert feed["items_detail"][0]["url"] == "https://wire.example/new"


def test_atom_is_read_the_same_way():
    text, metadata = formats.read_blob(ATOM, "xml", 100000)
    assert text.index("v2.0") < text.index("v1.0")
    assert metadata["feed"]["oldest"].startswith("2026-10-01")


def test_other_xml_keeps_its_structure():
    text, metadata = formats.read_blob(b"<catalog><book id='1'>Dune</book></catalog>",
                                       "xml", 1000)
    assert "<book" in text and "feed" not in metadata


def test_entity_tricks_are_still_refused():
    bomb = (b'<?xml version="1.0"?><!DOCTYPE rss [<!ENTITY a "aaaa">'
            b'<!ENTITY b "&a;&a;&a;&a;">]><rss><channel><title>&b;</title></channel></rss>')
    with pytest.raises(EntitiesForbidden):
        formats.read_blob(bomb, "xml", 1000)


def test_a_feed_is_cached_as_a_feed():
    out = {"content_type": "xml", "extraction": {"feed": {"items": 3}}}
    assert f.volatility(out, "https://wire.example/rss") == "feed"
    assert f.cache_lifetime(out, "https://wire.example/rss") == f.CACHE_FEED_SECONDS
