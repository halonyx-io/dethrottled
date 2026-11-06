"""Compare the prior chunked scheduler and candidate on identical local reads."""
import ast
import hashlib
import json
import statistics
import sys
import threading
import time
from pathlib import Path

from dethrottled import server

if len(sys.argv) != 2:
    raise SystemExit('usage: batch_measure.py BASELINE_SERVER_SOURCE')
source = Path(sys.argv[1]).read_text()
tree = ast.parse(source)
old = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == '_read_batch')
namespace = {'_FETCH_POOL': server._FETCH_POOL}
exec(compile(ast.Module(body=[old], type_ignores=[]), '<baseline>', 'exec'), namespace)
algorithms = {'chunked': namespace['_read_batch'], 'rolling': server._read_batch}
results = {}
for label, slow in [('one_slow', {0}), ('two_slow', {0, 4}), ('uniform', set())]:
    observations = {name: [] for name in algorithms}
    peaks = {name: 0 for name in algorithms}
    digest = None
    for repeat in range(12):
        names = list(algorithms) if repeat % 2 == 0 else list(reversed(algorithms))
        for name in names:
            lock = threading.Lock()
            active = [0]
            def read(index, *, lock=lock, active=active, peaks=peaks, name=name, slow=slow):
                with lock:
                    active[0] += 1
                    peaks[name] = max(peaks[name], active[0])
                try:
                    time.sleep(0.18 if index in slow else 0.03)
                    return {'url': str(index), 'content': f'Fact {index}: 7314.',
                            'quality': 'thin' if index == 5 else 'ok',
                            'warnings': ['partial'] if index == 5 else [],
                            'document_id': f'doc-{index}'}
                finally:
                    with lock:
                        active[0] -= 1
            at = time.perf_counter()
            rows = algorithms[name](list(range(12)), read)
            observations[name].append(round((time.perf_counter()-at)*1000, 3))
            actual = hashlib.sha256(json.dumps(rows, sort_keys=True).encode()).hexdigest()
            assert digest is None or digest == actual
            digest = actual
    results[label] = {'urls': 12, 'runs_per_scheduler': 12,
                     'same_ordered_evidence_sha256': digest, 'peak_active': peaks,
                     'elapsed_ms': observations,
                     'median_ms': {n: round(statistics.median(v), 3)
                                   for n,v in observations.items()}}
print(json.dumps({'protocol': ('alternating scheduler order; local timed fixtures; '
                               'no upstream requests'),
                  'baseline_git': 'a774f15', 'workloads': results}, indent=2))
