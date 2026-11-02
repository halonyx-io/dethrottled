"""Run controlled recovery assertions against two already-running core endpoints."""
import argparse
import json
import time
import uuid
from pathlib import Path
from urllib.request import Request, urlopen

parser = argparse.ArgumentParser()
parser.add_argument('--baseline', default='http://127.0.0.1:18792')
parser.add_argument('--candidate', default='http://127.0.0.1:18793')
parser.add_argument('--fixture', default='http://dethrottled-loop-check:8099')
parser.add_argument('--out', type=Path, required=True)
a = parser.parse_args()
a.out.mkdir(parents=True, exist_ok=True)
nonce = uuid.uuid4().hex[:10]
protocol = dict(cases=['alternate', 'lazy', 'details', 'network', 'cookie-seed',
                      'cookie-gated', 'normal', 'poison'], fact='7341 tonnes',
                max_chars=8000, cache_mode='bypass',
                notes='Synthetic same-origin fixtures; isolated core stores; shared browser. '
                      'TLS and Crawl4AI disabled to isolate recovery strategies.')
(a.out / 'protocol.json').write_text(json.dumps(protocol, indent=2))


def call(endpoint, route, payload):
    req = Request(endpoint + route, data=json.dumps(payload).encode(),
                  headers={'Content-Type': 'application/json'})
    with urlopen(req, timeout=90) as response:
        return json.load(response)


for endpoint in [a.baseline, a.candidate]:
    for _retry in range(50):
        try:
            with urlopen(endpoint + '/health', timeout=1) as response:
                if response.status == 200:
                    break
        except OSError:
            pass
        time.sleep(.2)
    else:
        raise RuntimeError('Core endpoint not ready')
records = []
with (a.out / 'comparison.jsonl').open('w') as handle:
    def record(case, name, endpoint, payload):
        start = time.monotonic()
        try:
            row = call(endpoint, '/fetch', payload)[0]
            item = dict(case=case, engine=name, has_fact=protocol['fact'] in row.get('content', ''),
                        response=row)
        except Exception as exc:
            item = dict(case=case, engine=name, error=type(exc).__name__ + ': ' + str(exc))
        item['elapsed_ms'] = round((time.monotonic() - start) * 1000, 2)
        records.append(item)
        handle.write(json.dumps(item) + '\n')
        handle.flush()
        print(case, name, item.get('has_fact'), flush=True)
        return item.get('response', {})

    for case in protocol['cases']:
        for name, endpoint in [('baseline', a.baseline), ('candidate', a.candidate)]:
            payload = dict(urls=[a.fixture + '/' + case], max_chars=8000, cache_mode='bypass',
                           evidence_namespace=nonce + '-' + name)
            row = record(case, name, endpoint, payload)
            if name == 'candidate' and case == 'lazy':
                session = row['read_plan']['browser_session']
                driven = call(endpoint, '/drive', dict(session=session['id'],
                    allowed_hosts=session['allowed_hosts'], screenshot='never',
                    evidence_namespace=nonce + '-candidate',
                    steps=[{'action': 'text', 'selector': 'body', 'max_chars': 8000}]))
                text = next(s['data'] for s in driven['steps'] if s['action'] == 'text')
                assert protocol['fact'] in text and driven['session']['id'] == session['id']
                (a.out / 'handoff.json').write_text(json.dumps(driven, indent=2))
    for mode in ['render-never', 'manual', 'other-caller']:
        payload = dict(urls=[a.fixture + ('/cookie-gated' if mode == 'other-caller' else '/lazy')],
            max_chars=8000, cache_mode='bypass',
            evidence_namespace=nonce + ('-other' if mode == 'other-caller' else '-candidate'))
        if mode == 'render-never':
            payload['render'] = 'never'
        if mode == 'manual':
            payload['recovery'] = 'manual'
        record(mode, 'candidate', a.candidate, payload)
summary = [{k: v for k, v in r.items() if k != 'response'} for r in records]
(a.out / 'comparison-summary.json').write_text(json.dumps(summary, indent=2))
for case in ['alternate', 'lazy', 'details', 'network', 'cookie-gated']:
    assert next(r for r in records if r['case'] == case and r['engine'] == 'candidate')['has_fact']
for r in records:
    assert 'error' not in r
    if r['case'] in ['poison', 'render-never', 'manual', 'other-caller']:
        assert not r['has_fact']
