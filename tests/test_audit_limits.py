"""Broader requested coverage must survive the complete core request path."""
from fastapi.testclient import TestClient

from dethrottled import research, server


def test_search_returns_requested_late_sources(monkeypatch):
    def search(_query, **options):
        assert options['max_items'] == 50
        return ([{'url': f'https://source{i}.example/report', 'title': f'Allocation report {i}',
                  'snippet': 'Regional allocation evidence', 'engine': 'fixture'}
                 for i in range(60)], {'elapsed_ms': 1, 'per_source': {'fixture': 60}})
    monkeypatch.setattr(server.fs, 'search', search)
    client = TestClient(server.app)
    response = client.post('/search', json={'query': 'allocation', 'limit': 50})
    assert response.status_code == 200
    assert len(response.json()) == 50
    assert response.json()[-1]['url'] == 'https://source49.example/report'
    assert client.post('/search', json={'query': 'allocation', 'limit': 51}).status_code == 422


def test_research_keeps_thirty_sources_and_all_explicit_facets(monkeypatch):
    monkeypatch.setattr(research, 'public_url', lambda url: True)
    monkeypatch.setattr(server, 'index_fetched', lambda *args: 0)
    observed_queries = []

    def ranked(body):
        observed_queries.append(body.query)
        return ([{'url': f'https://source{i}.example/report', 'title': f'Allocation {i}'}
                 for i in range(30)], {'elapsed_ms': 1}, body.limit)

    def extracted(url, max_chars, **options):
        return {'url': url, 'quality': 'ok', 'content': 'Allocation is 7341 tonnes.'}

    monkeypatch.setattr(server, '_ranked', ranked)
    monkeypatch.setattr(server, '_extract_row', extracted)
    response = TestClient(server.app).post('/research', json={
        'question': 'Allocation evidence?', 'queries': [f'facet {i}' for i in range(10)],
        'max_sources': 30, 'max_chars': 120000})
    assert response.status_code == 200
    result = response.json()
    assert len(result['sources']) == 30
    assert set(observed_queries) == {'Allocation evidence?', *(f'facet {i}' for i in range(10))}
    assert all('7341 tonnes' in row['content'] for row in result['sources'])
