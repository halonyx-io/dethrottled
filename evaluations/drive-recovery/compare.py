"""Compare actual browser endpoints; record metadata without publishing page bodies."""
import argparse
import hashlib
import json
import time
import uuid
from pathlib import Path
from urllib.error import HTTPError
from urllib.parse import urlsplit, urlunsplit
from urllib.request import Request, urlopen

parser = argparse.ArgumentParser()
parser.add_argument('--control', default='http://127.0.0.1:19905')
parser.add_argument('--candidate', default='http://127.0.0.1:19904')
parser.add_argument('--out', type=Path, required=True)
a = parser.parse_args()
a.out.mkdir(parents=True, exist_ok=True)
THREAD = ('https://www.reddit.com/r/programming/comments/1xl8d57/'
          'jepsen_on_particledb_we_tested_versions_114/')
CASES = [('reddit-thread', THREAD), ('reddit-listing', 'https://www.reddit.com/r/programming/'),
         ('python', 'https://docs.python.org/3/library/sqlite3.html'),
         ('crunchbase', 'https://www.crunchbase.com/organization/openai'),
         ('g2', 'https://www.g2.com/products/notion/reviews')]
records = []


def scrub(value):
    if isinstance(value, str) and value.startswith(('http://', 'https://')):
        u = urlsplit(value)
        return urlunsplit((u.scheme, u.netloc, u.path, '', ''))
    if isinstance(value, dict):
        return {k: scrub(v) for k, v in value.items()}
    if isinstance(value, list):
        return [scrub(v) for v in value]
    return value


def call(endpoint, case, engine, body):
    at = time.monotonic()
    request = Request(endpoint + '/drive', data=json.dumps(body).encode(),
                      headers={'Content-Type': 'application/json'})
    try:
        with urlopen(request, timeout=65) as response:
            result, status = json.load(response), response.status
    except HTTPError as exc:
        result, status = json.load(exc), exc.code
    except Exception as exc:
        result, status = {'error': type(exc).__name__}, None
    elapsed = round((time.monotonic() - at) * 1000, 2)
    texts = [s.get('data', '') for s in result.get('steps', []) if s['action'] == 'text']
    text = '\n'.join(t for t in texts if isinstance(t, str))
    saved = scrub(json.loads(json.dumps(result)))
    for step in saved.get('steps', []):
        if step['action'] in {'text', 'html'} and isinstance(step.get('data'), str):
            content = step.pop('data')
            step['evidence'] = {'chars': len(content),
                                'sha256': hashlib.sha256(content.encode()).hexdigest()}
    record = dict(case=case, engine=engine, elapsed_ms=elapsed, http_status=status,
                  content_chars=len(text), title_support='ParticleDB' in text,
                  comment_support='Vibrational Database Management Systems' in text,
                  result=saved)
    records.append(record)
    (a.out / 'observations.json').write_text(json.dumps(records, indent=2))
    print(case, engine, status, elapsed, result.get('access'), flush=True)
    return result


for _engine, endpoint in [('control', a.control), ('candidate', a.candidate)]:
    for _retry in range(40):
        try:
            with urlopen(endpoint + '/health', timeout=1):
                break
        except OSError:
            time.sleep(.25)
    else:
        raise RuntimeError('Worker not ready')
for case, url in CASES:
    for engine, endpoint in [('control', a.control), ('candidate', a.candidate)]:
        base = dict(session='comparison-' + uuid.uuid4().hex[:16],
                    allowed_hosts=[urlsplit(url).hostname], public_only=True,
                    screenshot='never', include_events=False, timeout_ms=30000)
        try:
            result = call(endpoint, case, engine, dict(base, url=url, steps=[
                {'action': 'count', 'selector': 'shreddit-comment'},
                {'action': 'text', 'selector': 'body', 'max_chars': 120000}]))
            if case == 'reddit-thread' and engine == 'candidate':
                comments = next(s['data'] for s in result['steps'] if s['action'] == 'count')
                assert comments > 0 and result['access']['status'] == 'content_observed'
                interaction = dict(base, operation_id='sort-open', steps=[
                    {'action': 'click', 'selector': 'shreddit-sort-dropdown button'},
                    {'action': 'count', 'selector': '[role="menuitem"]:visible'}])
                interacted = call(endpoint, 'reddit-sort-click', engine, interaction)
                assert interacted['ok']
                assert next(s['data'] for s in interacted['steps'] if s['action'] == 'count') > 0
                replay = call(endpoint, 'reddit-sort-retry', engine, interaction)
                assert replay['operation_replayed'] and replay['ok']
                checked = call(endpoint, 'reddit-continuation', engine, dict(base, steps=[
                    {'action': 'attr', 'selector': 'shreddit-sort-dropdown button',
                     'name': 'aria-expanded'}, {'action': 'history'}]))
                assert checked['ok']
                assert next(s['data'] for s in checked['steps'] if s['action'] == 'attr') == 'true'
        finally:
            call(endpoint, case + '-close', engine, dict(base, steps=[], close_session=True))
(a.out / 'protocol.json').write_text(json.dumps(dict(cases=CASES,
    method='Same candidate browser image/GPU configuration; recovery auto versus off; '
           'fresh sessions; no explicit wait; original action executor and scope guards. '
           'One live observation per case/engine; not a general success rate.'), indent=2))
