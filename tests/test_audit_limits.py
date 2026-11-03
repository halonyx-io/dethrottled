"""Broader requested coverage must survive the complete core request path."""
import pytest
from fastapi.testclient import TestClient

from dethrottled import research, server


def test_search_returns_bounded_source_menu(monkeypatch):
    def search(_query, **options):
        assert options['max_items'] == 15
        return ([{'url': f'https://source{i}.example/report', 'title': f'Allocation report {i}',
                  'snippet': 'Regional allocation evidence',
                  'engine': ('web-ddg-lite' if i < 10 else 'crossref' if i < 13
                             else 'openalex')}
                 for i in range(60)], {'elapsed_ms': 1, 'per_source': {'fixture': 60}})
    monkeypatch.setattr(server.fs, 'search', search)
    client = TestClient(server.app)
    response = client.post('/search', json={'query': 'allocation', 'limit': 15})
    assert response.status_code == 200
    assert len(response.json()) == 15
    assert response.json()[-1]['url'] == 'https://source14.example/report'
    assert client.post('/search', json={'query': 'allocation', 'limit': 16}).status_code == 422


@pytest.mark.parametrize("same_publisher", [False, True])
def test_research_bounds_sources_and_all_explicit_facets(monkeypatch, same_publisher):
    monkeypatch.setattr(research, 'public_url', lambda url: True)
    monkeypatch.setattr(server, 'index_fetched', lambda *args: 0)
    observed_queries = []

    def ranked(body):
        observed_queries.append(body.query)
        return ([{'url': (f'https://official.example/{body.query.replace(" ", "-")}/{i}'
                          if same_publisher
                          else f'https://source{i}.example/{body.query.replace(" ", "-")}'),
                          'title': f'Allocation {i}',
                          'engine': ('web-ddg-lite' if i < 10 else 'crossref' if i < 13
                                     else 'openalex')}
                 for i in range(30)], {'elapsed_ms': 1}, body.limit)

    def extracted(url, max_chars, **options):
        return {'url': url, 'quality': 'ok', 'content': 'Allocation is 7341 tonnes.'}

    monkeypatch.setattr(server, '_ranked', ranked)
    monkeypatch.setattr(server, '_extract_row', extracted)
    response = TestClient(server.app).post('/research', json={
        'question': 'Allocation evidence?', 'queries': [f'facet {i}' for i in range(10)],
        'max_sources': 20, 'max_chars': 120000})
    assert response.status_code == 200
    result = response.json()
    assert len(result['sources']) == 20
    assert result['summary']['candidates'] == 24
    all_candidates = {u for f in result['coverage']['facets'] for u in f['unread']}
    all_candidates.update(s['url'] for s in result['sources'])
    assert len(all_candidates) <= 24
    assert set(observed_queries) == {'Allocation evidence?', *(f'facet {i}' for i in range(10))}
    assert all('7341 tonnes' in row['content'] for row in result['sources'])


def test_publisher_diversity_is_preferred_without_discarding_primary_docs(monkeypatch):
    monkeypatch.setattr(research, 'public_url', lambda url: True)
    primary = [{'url': f'https://official.example/{i}'} for i in range(8)]
    other = {'url': 'https://independent.example/report'}
    rows = research.select_sources([[*primary, other]], 6)
    assert [row['url'] for row in rows[:3]] == [primary[0]['url'], primary[1]['url'], other['url']]
    assert len(rows) == 6 and rows[-1]['url'] == primary[4]['url']


def test_research_failed_reads_cannot_expand_past_replacement_budget(monkeypatch):
    monkeypatch.setattr(research, 'public_url', lambda url: True)
    monkeypatch.setattr(server, 'index_fetched', lambda *args: 0)
    monkeypatch.setattr(server, '_ranked', lambda body: ([
        {'url': f'https://example.org/{body.query}/{i}', 'engine': 'web-ddg-lite'}
        for i in range(15)], {}, 15))
    attempted = []
    def fail(url, *args, **kwargs):
        attempted.append(url)
        return {'url': url, 'quality': 'failed', 'content': ''}
    monkeypatch.setattr(server, '_extract_row', fail)
    response = TestClient(server.app).post('/research', json={
        'question': 'Evidence question', 'queries': ['facet A', 'facet B'],
        'max_sources': 20, 'follow_assets': False})
    assert response.status_code == 200
    assert len(attempted) == len(set(attempted)) == 24
    assert response.json()['summary']['attempted'] == 24
    assert TestClient(server.app).post('/research', json={
        'question': 'Evidence question', 'max_sources': 21}).status_code == 422
