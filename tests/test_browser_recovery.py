"""Observed Reddit navigation recovery and truthful access classification."""
import ast
import asyncio
import importlib.util
import os
from pathlib import Path
from unittest.mock import AsyncMock

import pytest

from dethrottled.challenges import classify

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location(
    'browser_recovery', ROOT / 'browser-search/recovery.py')
recovery = importlib.util.module_from_spec(spec)
spec.loader.exec_module(recovery)


@pytest.mark.parametrize('url', ['https://reddit.com/r/a', 'https://www.reddit.com/r/a',
                                 'https://old.reddit.com/r/a'])
def test_cookie_recipe_is_host_scoped(url):
    cookie = recovery.navigation_recipe(url)['cookie']
    assert cookie['name'] == 'cookiesEnabled' and cookie['value'] == 'true'
    assert 'domain' not in cookie and cookie['url'].endswith('.com/')


@pytest.mark.parametrize('url', ['https://reddit.com.evil.example/a',
                                 'https://notreddit.com/', 'file:///reddit.com/a',
                                 'https://user@www.reddit.com/'])
def test_no_recipe_for_unrelated_or_non_http_targets(url):
    assert recovery.navigation_recipe(url) is None


def test_existing_preference_and_operator_disable_are_preserved(monkeypatch):
    tree = ast.parse((ROOT / 'browser-search/service.py').read_text())
    function = next(n for n in tree.body if isinstance(n, ast.AsyncFunctionDef)
                    and n.name == '_prepare_navigation')
    scope = {'os': os, 'navigation_recipe': recovery.navigation_recipe}
    exec(compile(ast.Module(body=[function], type_ignores=[]), '<worker>', 'exec'), scope)
    context = AsyncMock()
    context.cookies.return_value = [{'name': 'cookiesEnabled', 'value': 'false'}]
    result = asyncio.run(scope['_prepare_navigation'](context, 'https://www.reddit.com/'))
    assert result['existing_preference_preserved'] and not result['cookie_added']
    context.add_cookies.assert_not_called()
    context.cookies.return_value = []
    result = asyncio.run(scope['_prepare_navigation'](context, 'https://www.reddit.com/'))
    assert result['cookie_added']
    context.add_cookies.assert_awaited_once()
    monkeypatch.setenv('DETHROTTLED_BROWSER_RECOVERY', 'off')
    context.reset_mock()
    assert asyncio.run(scope['_prepare_navigation'](context, 'https://www.reddit.com/')) is None
    context.cookies.assert_not_called()


def test_challenge_and_login_are_not_readable_content():
    challenge = 'Prove your humanity We are committed to safety and security. But not for bots.'
    assert recovery.assess_access(challenge)['status'] == 'challenge'
    assert classify(challenge) == 'generic'
    login = ('[Skip to main content](https://old.reddit.com/login/#main) # Log in to use old '
             'Reddit To keep Reddit safe, accounts are required to access old Reddit. Password')
    assert classify(login) == 'login_required'
    html = ('<title>Welcome to Reddit</title><h1>Log in to use old Reddit</h1>'
            '<p>To keep Reddit safe, accounts are required to access old Reddit.</p>')
    assert classify(html) == 'login_required'
    access = recovery.assess_access(
        'Log in to use old Reddit. Accounts are required to access '
        'old Reddit.', 'Welcome to Reddit', 'https://old.reddit.com/login/')
    assert access['status'] == 'login_required'


def test_mentions_in_real_content_are_not_interstitials():
    article = ('An investigation of the phrase "Prove your humanity" and the message '
               '"Log in to use old Reddit". ' * 20)
    assert classify(article) == ''
    assessment = recovery.assess_access(article, 'An investigation', 'https://example.com/article')
    assert assessment['status'] == 'content_observed' and not assessment['answer_verified']


@pytest.mark.parametrize('unavailable', [False, True])
def test_truncated_html_reads_visible_evidence_without_losing_html(monkeypatch, unavailable):
    from dethrottled import fetch
    html = '<html><body>Navigation prefix</body></html>'
    fact = 'Allocation evidence is 7341 tonnes. ' * 30

    class Response:
        def __init__(self, data):
            self.data = data

        def raise_for_status(self):
            pass

        def json(self):
            return self.data

    def post(*args, **kwargs):
        action = kwargs['json']['steps'][-1]['action']
        if action == 'text' and unavailable:
            raise fetch.requests.ConnectionError('disconnected')
        step = {'action': action, 'data': html if action == 'html' else fact,
                'truncated': action == 'html', 'ok': True}
        return Response({'ok': True, 'steps': [step]})

    monkeypatch.setattr(fetch.requests, 'post', post)
    payload, reason, _ = fetch._headed_read('https://fixture.example/', 'http://browser')
    assert not reason and payload['html'] == html
    if unavailable:
        assert 'text' not in payload
        assert payload['browser_recovery']['visible_text_error'] == 'ConnectionError'
    else:
        assert payload['text'] == fact and not payload['extraction']['partial']
        assert payload['extraction']['html_capture_partial']
