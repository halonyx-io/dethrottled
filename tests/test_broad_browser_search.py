"""Requested breadth cannot bypass provider-family and menu budgets."""
import pytest

from dethrottled import search


def rows(engine, count, start=0):
    return [{'url': f'https://example.org/{i}', 'title': f'Source evidence {i}',
             'snippet': 'Known allocation evidence from a public primary source.',
             'engine': engine} for i in range(start, start + count)]


@pytest.mark.parametrize('engine,expected', [('ddg-lite', 10), ('bing', 3)])
def test_browser_worker_overdelivery_is_capped(monkeypatch, engine, expected):
    observed = []

    class Response:
        def raise_for_status(self):
            pass

        def json(self):
            return {'ok': True, 'engine': engine, 'results': rows(engine, 50)}

    def post(url, **options):
        observed.append(options['json'])
        return Response()

    monkeypatch.setattr(search, 'BROWSER_SEARCH_URL', 'http://worker')
    monkeypatch.setattr(search.requests, 'post', post)
    found = search.browser_search('allocation', max_items=50)
    assert observed == [{'query': 'allocation', 'limit': 10}]
    assert len(found) == expected
    assert all(r['engine'] == 'web-browser-' + engine for r in found)


def test_large_requests_do_not_escalate_ten_cheap_rows(monkeypatch):
    monkeypatch.setenv('DETHROTTLED_CHEAP_DISCOVERY', '1')
    observed = []

    def cheap(*args, **kwargs):
        observed.append(kwargs['max_items'])
        return rows('web-tls-ddg-lite', 10)

    def forbidden(*args, **kwargs):
        pytest.fail('Ten primary choices must not trigger breadth recovery')

    monkeypatch.setattr(search, 'tls_search', cheap)
    monkeypatch.setattr(search, 'browser_search', forbidden)
    assert len(search.web_search('allocation', max_items=50)) == 10
    assert observed == [10]


def test_cached_provider_lists_obey_current_caps(monkeypatch):
    class Cache:
        def get(self, *key):
            return rows('web-browser-bing', 50)

    monkeypatch.setattr(search, 'BROWSER_SEARCH_URL', 'http://worker')
    assert len(search.browser_search('allocation', max_items=50, cache=Cache())) == 3


def test_ddg_variants_share_one_budget_and_supplements_do_not_refill_duplicates():
    pool = [*rows('web-tls-ddg-lite', 7), *rows('web-browser-ddg-html', 8, 7),
            *rows('crossref', 8, 15), *rows('openalex', 8, 23)]
    menu = search.bounded_results(pool)
    assert len(menu) == 16
    assert sum(search.result_family(r) == 'ddg' for r in menu) == 10
    assert sum(r['engine'] == 'crossref' for r in menu) == 3
    assert sum(r['engine'] == 'openalex' for r in menu) == 3
    assert len({r['url'] for r in menu}) == 16


def test_searxng_caps_each_engine_even_for_cached_results(monkeypatch, tmp_path):
    monkeypatch.setenv('DETHROTTLED_ENGINE_HEALTH', str(tmp_path / 'health.json'))
    monkeypatch.setattr(search, 'SEARXNG_URL', 'http://searxng')

    class Response:
        status_code = 200

        def json(self):
            return {'results': [*rows('mwmbl', 20), *rows('crossref', 20, 20)]}

    monkeypatch.setattr(search.requests, 'get', lambda *a, **k: Response())
    found = search.searxng('allocation', engines='mwmbl,crossref', max_items=50)
    assert len(found) == 6
    assert sum(r['engine'] == 'mwmbl' for r in found) == 3

    class Cache:
        def get(self, *key):
            return rows('mwmbl', 50)

    assert len(search.searxng('allocation', engines='mwmbl',
                              max_items=50, cache=Cache())) == 3
