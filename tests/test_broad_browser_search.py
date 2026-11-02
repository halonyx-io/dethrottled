"""The core must forward discovery breadth and preserve each worker source."""
import pytest

from dethrottled import search


@pytest.mark.parametrize('requested', [8, 50])
def test_browser_count_and_per_row_engine_survive_the_core(monkeypatch, requested):
    observed = []

    class Response:
        ok = True

        def raise_for_status(self):
            pass

        def json(self):
            return {'ok': True, 'engine': 'ddg-lite', 'results': [
                {'url': f'https://example.org/{i}', 'title': f'Source evidence {i}',
                 'snippet': 'Known allocation evidence from a public primary source.',
                 'engine': 'bing'} for i in range(50)]}

    def post(url, **options):
        observed.append(options['json'])
        return Response()

    monkeypatch.setattr(search, 'BROWSER_SEARCH_URL', 'http://worker')
    monkeypatch.setattr(search.requests, 'post', post)
    rows = search.browser_search('allocation', max_items=requested)
    assert observed == [{'query': 'allocation', 'limit': requested}]
    assert len(rows) == requested and rows[-1]['url'].endswith('/' + str(requested - 1))
    assert all(row['engine'] == 'web-browser-bing' for row in rows)


def _rows(count):
    return [{'url': f'https://example.org/{i}', 'title': f'Allocation {i}',
             'snippet': 'Primary allocation evidence is 7341 tonnes.'} for i in range(count)]


def test_partial_cheap_discovery_escalates_for_requested_breadth(monkeypatch):
    monkeypatch.setenv('DETHROTTLED_CHEAP_DISCOVERY', '1')
    cheap = _rows(10)
    observed = []
    monkeypatch.setattr(search, 'tls_search', lambda *a, **k: cheap)

    def browser(*args, **kwargs):
        observed.append(kwargs['max_items'])
        return _rows(50)

    monkeypatch.setattr(search, 'browser_search', browser)
    diagnostics = {}
    rows = search.web_search('allocation', max_items=50, diagnostics=diagnostics)
    assert observed == [50] and len(rows) == 50
    assert rows[:10] == cheap and len({r['url'] for r in rows}) == 50
    assert diagnostics['breadth']['status'] == 'fulfilled'
    assert diagnostics['breadth']['cheap_count'] == 10


def test_small_cheap_request_does_not_start_browser(monkeypatch):
    monkeypatch.setenv('DETHROTTLED_CHEAP_DISCOVERY', '1')
    monkeypatch.setattr(search, 'tls_search', lambda *a, **k: _rows(8))

    def forbidden(*args, **kwargs):
        raise AssertionError('Small usable cheap request must remain cheap')

    monkeypatch.setattr(search, 'browser_search', forbidden)
    assert len(search.web_search('allocation', max_items=8)) == 8


def test_failed_breadth_recovery_keeps_cheap_results(monkeypatch):
    monkeypatch.setenv('DETHROTTLED_CHEAP_DISCOVERY', '1')
    monkeypatch.setattr(search, 'tls_search', lambda *a, **k: _rows(10))
    monkeypatch.setattr(search, 'browser_search', lambda *a, **k: [])
    diagnostics = {}
    rows = search.web_search('allocation', max_items=50, diagnostics=diagnostics)
    assert len(rows) == 10 and diagnostics['breadth']['status'] == 'partial'


def test_legacy_short_browser_cache_does_not_hide_new_breadth(monkeypatch):
    class LegacyCache:
        def get(self, *key):
            return _rows(10) if key[1] == 'browser' else None

        def put(self, *key, **kwargs):
            pass

    class Response:
        ok = True

        def raise_for_status(self):
            pass

        def json(self):
            return {'ok': True, 'results': _rows(50), 'engine': 'ddg-lite'}

    monkeypatch.setattr(search, 'BROWSER_SEARCH_URL', 'http://worker')
    monkeypatch.setattr(search.requests, 'post', lambda *a, **k: Response())
    assert len(search.browser_search('allocation', max_items=50, cache=LegacyCache())) == 50
