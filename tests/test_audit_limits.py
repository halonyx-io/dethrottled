"""Broader requested coverage must survive the complete core request path."""
import pytest
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


@pytest.mark.parametrize("same_publisher", [False, True])
def test_research_keeps_thirty_sources_and_all_explicit_facets(monkeypatch, same_publisher):
    monkeypatch.setattr(research, 'public_url', lambda url: True)
    monkeypatch.setattr(server, 'index_fetched', lambda *args: 0)
    observed_queries = []

    def ranked(body):
        observed_queries.append(body.query)
        return ([{'url': (f'https://official.example/report/{i}' if same_publisher
                          else f'https://source{i}.example/report'), 'title': f'Allocation {i}'}
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


def test_publisher_diversity_is_preferred_without_discarding_primary_docs(monkeypatch):
    monkeypatch.setattr(research, 'public_url', lambda url: True)
    primary = [{'url': f'https://official.example/{i}'} for i in range(8)]
    other = {'url': 'https://independent.example/report'}
    rows = research.select_sources([[*primary, other]], 6)
    assert [row['url'] for row in rows[:3]] == [primary[0]['url'], primary[1]['url'], other['url']]
    assert len(rows) == 6 and rows[-1]['url'] == primary[4]['url']
