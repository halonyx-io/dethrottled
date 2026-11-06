"""Refusal truth and sparse static discovery without contacting providers."""
import sys
import types

import pytest

from dethrottled import discovery
from dethrottled import search_diagnostics as diag


def serp(count):
    return ''.join(f'<a class="result-link" href="https://example.org/source/{i}">'
                   f'Primary source evidence {i}</a><div class="result-snippet">'
                   'Substantive evidence supporting the requested question.</div>'
                   for i in range(count))


@pytest.mark.parametrize('count', [1, 2, 10])
def test_tls_accepts_sparse_valid_sources(monkeypatch, count):
    monkeypatch.setitem(sys.modules, 'curl_cffi', types.SimpleNamespace(
        requests=types.SimpleNamespace(get=lambda *a, **k: None)))
    response = types.SimpleNamespace(text=serp(count), status_code=200, headers={})
    monkeypatch.setattr(discovery.requests, 'get_using', lambda *a, **k: response)
    diagnostics = {}
    rows = discovery.tls_search('source evidence', max_items=count, diagnostics=diagnostics)
    assert len(rows) == count and diagnostics['status'] == 'ok'
    assert diagnostics['refusal'] is False


@pytest.mark.parametrize('status,body', [
    (202, 'Unfortunately, bots use DuckDuckGo too. anomaly.js'),
    (429, 'Too many requests'),
    (200, '<html>No source results</html>'),
    (200, serp(1).replace('Substantive evidence supporting the requested question.', 'short')),
])
def test_tls_does_not_accept_refusals_or_weak_results(monkeypatch, status, body):
    monkeypatch.setitem(sys.modules, 'curl_cffi', types.SimpleNamespace(
        requests=types.SimpleNamespace(get=lambda *a, **k: None)))
    response = types.SimpleNamespace(text=body, status_code=status, headers={})
    monkeypatch.setattr(discovery.requests, 'get_using', lambda *a, **k: response)
    diagnostics = {}
    assert discovery.tls_search('source evidence', diagnostics=diagnostics) == []
    assert diagnostics['refusal'] == (status in {202, 429})


def test_empty_counts_during_known_refusal_are_not_genuine_zero_results():
    assert diag.outcome(0, {'status': 'no_results', 'upstream_status': 'cooldown'}) == 'unavailable'


@pytest.mark.parametrize("header", ["NaN", "inf", "-inf", "not-a-date"])
def test_invalid_retry_after_does_not_suspend_discovery_for_a_day(monkeypatch, header):
    monkeypatch.setitem(sys.modules, 'curl_cffi', types.SimpleNamespace(
        requests=types.SimpleNamespace(get=lambda *a, **k: None)))
    response = types.SimpleNamespace(text='Refused', status_code=429,
                                     headers={'Retry-After': header})
    monkeypatch.setattr(discovery.requests, 'get_using', lambda *a, **k: response)
    diagnostics = {}
    assert discovery.tls_search('source evidence', diagnostics=diagnostics) == []
    assert diagnostics['retry_after_seconds'] == 0
