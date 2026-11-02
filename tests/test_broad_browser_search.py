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
