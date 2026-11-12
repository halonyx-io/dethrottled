"""Inline text keeps the spaces around highlighted or nested markup.

selectolax's text(strip=True) strips every text node and joins them with no
separator, so "The <b>Python</b> module" became "ThePythonmodule". DDG Lite
wraps matched query terms in <b>, which glued exactly the words that matter.
"""
import sys
import types

from dethrottled import discovery, extract


def test_tls_keeps_spaces_around_highlighted_query_terms(monkeypatch):
    body = ('<table><tr><td><a class="result-link" '
            'href="https://docs.python.org/3/library/sqlite3.html">'
            '<b>sqlite3</b> — DB-API 2.0 interface for <b>SQLite</b> databases</a></td></tr>'
            '<tr><td class="result-snippet">The <b>Python</b> <b>sqlite3</b> module provides '
            'an interface for <b>SQLite</b> databases. Read the <b>docs</b>, then run.'
            '</td></tr></table>')
    monkeypatch.setitem(sys.modules, 'curl_cffi', types.SimpleNamespace(
        requests=types.SimpleNamespace(get=lambda *a, **k: None)))
    response = types.SimpleNamespace(text=body, status_code=200, headers={})
    monkeypatch.setattr(discovery.requests, 'get_using', lambda *a, **k: response)
    rows = discovery.tls_search('python sqlite3 documentation', max_items=5, diagnostics={})
    assert rows[0]['title'] == 'sqlite3 — DB-API 2.0 interface for SQLite databases'
    assert rows[0]['snippet'] == ('The Python sqlite3 module provides an interface for '
                                  'SQLite databases. Read the docs, then run.')


def test_link_text_keeps_spaces_around_inline_markup():
    html = ('<html><body><p>See <a href="/guide">the <b>install</b> <em>guide</em></a> '
            'for details about the configuration options used here.</p></body></html>')
    text = extract.links(html, "https://example.org/")
    assert "[the install guide](https://example.org/guide)" in text
