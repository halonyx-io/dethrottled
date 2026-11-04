"""Run a frozen, paced workload locally on each benchmark host; preserve every case."""
import argparse
import concurrent.futures
import hashlib
import json
import math
import os
import platform
import statistics
import subprocess
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path

P = argparse.ArgumentParser()
P.add_argument('--api', default='http://127.0.0.1:19087')
P.add_argument('--manifest', type=Path, required=True)
P.add_argument('--out', type=Path, required=True)
P.add_argument('--phase', choices=['search-fresh', 'search-warm', 'fetch-fresh', 'fetch-warm',
                                 'research', 'formats', 'concurrency'], required=True)
A = P.parse_args()
A.out.mkdir(parents=True, exist_ok=True)
manifest_bytes = A.manifest.read_bytes()
M = json.loads(manifest_bytes)
resource = []
stop = threading.Event()


def sample():
    while not stop.is_set():
        ids = subprocess.check_output(['docker', 'ps', '-q', '--filter',
              'label=com.docker.compose.project=dethrottled-benchmark'], text=True).split()
        if not ids:
            stop.wait(2)
            continue
        proc = subprocess.run(['docker', 'stats', '--no-stream', '--format', '{{json .}}',
                               *ids], capture_output=True, text=True, check=False)
        sampled_at = time.time()
        for line in proc.stdout.splitlines():
            try:
                row = json.loads(line)
                resource.append({'at': sampled_at, 'service': row['Name'],
                                 'cpu_percent_one_core': row['CPUPerc'], 'memory': row['MemUsage']})
            except (ValueError, KeyError):
                pass
        stop.wait(2)


def call(path, payload):
    req = urllib.request.Request(A.api + path, data=json.dumps(payload).encode(),
                                 headers={'Content-Type': 'application/json'})
    started = time.perf_counter()
    try:
        with urllib.request.urlopen(req, timeout=180) as response:
            body = response.read()
            result = {'status': response.status, 'response_bytes': len(body),
                      'data': json.loads(body)}
    except urllib.error.HTTPError as exc:
        result = {'status': exc.code, 'retry_after': exc.headers.get('Retry-After'),
                  'error': exc.read(600).decode(errors='replace')}
    except Exception as exc:
        result = {'status': None, 'error': type(exc).__name__ + ': ' + str(exc)[:200]}
    result['elapsed_ms'] = round((time.perf_counter() - started) * 1000, 2)
    return result


def norm(text):
    return ' '.join(text.casefold().split())


def one(item):
    name = item.get('id', item.get('query', item.get('url', '')))
    if A.phase.startswith('search'):
        r = call('/v2/search', {'query': item['query'], 'limit': 15,
                               'fresh': A.phase.endswith('fresh')})
        envelope = r.pop('data', {})
        rows = envelope.get('results', [])
        r.update(attempts=envelope.get('attempts', []),
                 acquisition_status=envelope.get('status'))
        r.update(results=rows, result_count=len(rows),
                 snippets_with_text=sum(len(x.get('snippet', '')) >= 25 for x in rows),
                 menu_budget_ok=len(rows) <= 15)
    elif A.phase == 'research':
        r = call('/research', {'question': item['question'], 'max_sources': 4,
                              'fresh': True, 'response_format': 'concise'})
        body = r.pop('data', {})
        r.update(summary=body.get('summary'), coverage=body.get('coverage'),
                 sources=[{k: x.get(k) for k in ('url', 'quality', 'tier', 'warnings',
                          'document_id', 'evidence')} for x in body.get('sources', [])])
    else:
        r = call('/fetch', {'urls': [item['url']], 'max_chars': 12000,
                           'cache_mode': 'use' if A.phase.endswith('warm') else 'bypass',
                           'public_only': False, 'evidence_namespace': 'two-device-benchmark'})
        body = r.pop('data', [])
        row = body[0] if isinstance(body, list) and body else {}
        text = row.get('content', '')
        assertions = {phrase: norm(phrase) in norm(text) for phrase in item.get('assertions', [])}
        r.update(quality=row.get('quality'), tier=row.get('tier'), chars=len(text),
                 text_sha256=hashlib.sha256(text.encode()).hexdigest(),
                 warnings=row.get('warnings', []), assertions=assertions,
                 assertions_pass=bool(assertions) and all(assertions.values()),
                 document_id=row.get('document_id'), truncated=row.get('truncated'),
                 content_assessment=row.get('content_assessment'),
                 cached=row.get('cached'), failure_reason=row.get('failure_reason'),
                 source_partial=row.get('source_partial'), extraction=row.get('extraction'),
                 acquisition=row.get('acquisition'))
        if A.phase == 'formats' and row.get('document_id') and text:
            retained = call('/documents/read', {'document_id': row['document_id'],
                            'max_chars': 12000, 'evidence_namespace': 'two-device-benchmark'})
            rr = retained.get('data', {})
            r['retained_assertions_pass'] = bool(assertions) and all(
                norm(phrase) in norm(rr.get('content', '')) for phrase in assertions)
            r['retained_ms'] = retained['elapsed_ms']
    return dict(id=name, **r)


def summary(cases):
    times = sorted(c['elapsed_ms'] for c in cases)
    return {'cases': len(cases), 'http_200': sum(c['status'] == 200 for c in cases),
            'median_ms': statistics.median(times), 'p95_ms': times[math.ceil(.95 * len(times))-1],
            'assertions_pass': sum(c.get('assertions_pass', False) for c in cases),
            'readable_ok': sum(c.get('quality') == 'ok' for c in cases)}


thread = threading.Thread(target=sample, daemon=True)
thread.start()
cases = []
started = time.time()
load_before = os.getloadavg()
try:
    if A.phase == 'formats':
        work = [dict(x, id=x['id'] + '-repeat' + str(i))
                for i in range(3) for x in M['formats']]
    elif A.phase == 'concurrency':
        work = []
        for concurrency in (1, 3, 6):
            batch = [dict(M['formats'][0], id=f'c{concurrency}-{i}') for i in range(12)]
            with concurrent.futures.ThreadPoolExecutor(max_workers=concurrency) as pool:
                cases.extend(dict(x, concurrency=concurrency) for x in pool.map(one, batch))
            (A.out / 'cases.json').write_text(json.dumps(cases, indent=2))
    else:
        work = M['queries'] if A.phase.startswith('search') else M[
            'research' if A.phase == 'research' else 'fetches']
    for index, item in enumerate(work):
        start = time.monotonic()
        case = one(item)
        cases.append(case)
        (A.out / 'cases.json').write_text(json.dumps(cases, indent=2))
        print(A.phase, index + 1, len(work), case['status'], case['elapsed_ms'], flush=True)
        if A.phase == 'search-fresh':
            time.sleep(max(0, 3 - (time.monotonic() - start)))
finally:
    stop.set()
    thread.join(timeout=20)
    (A.out / 'resources.json').write_text(json.dumps(resource, indent=2))
    (A.out / 'summary.json').write_text(json.dumps(dict(
        summary(cases) if cases else {}, host=platform.node(), arch=platform.machine(),
        manifest_sha256=hashlib.sha256(manifest_bytes).hexdigest(),
        started_at=started, finished_at=time.time(), phase=A.phase,
        host_load_before=load_before, host_load_after=os.getloadavg()), indent=2))

if A.phase in {'formats', 'concurrency'} and any(
        not c.get('assertions_pass') or c.get('retained_assertions_pass') is False for c in cases):
    raise SystemExit('Controlled fact retention failed; stop this gate and preserve its cases.')
