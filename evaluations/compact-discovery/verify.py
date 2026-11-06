"""Offline concise-response comparison on identical canonical evidence.

The optional input is a saved /fetch JSON response; otherwise use a synthetic
194-page PDF metadata fixture. No network or retained-document writes occur.
"""
from __future__ import annotations

import argparse
import ast
import hashlib
import json
import statistics
import time
import tracemalloc
from pathlib import Path

from dethrottled.content import compact_row


def benchmark(fn, row):
    samples, peaks = [], []
    for _ in range(7):
        tracemalloc.start()
        started = time.perf_counter()
        encoded = json.dumps(fn(row), ensure_ascii=False, separators=(',', ':')).encode()
        samples.append((time.perf_counter() - started) * 1000)
        peaks.append(tracemalloc.get_traced_memory()[1])
        tracemalloc.stop()
    return {'json_bytes': len(encoded), 'median_serialize_ms': statistics.median(samples),
            'peak_python_traced_bytes': max(peaks), 'repetitions': len(samples)}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--baseline-source', type=Path, required=True)
    parser.add_argument('--input', type=Path)
    args = parser.parse_args()
    baseline_source = args.baseline_source.read_text()
    tree = ast.parse(baseline_source)
    function = next(n for n in tree.body if isinstance(n, ast.FunctionDef)
                    and n.name == 'compact_row')
    namespace = {}
    exec(compile(ast.Module(body=[function], type_ignores=[]), '<baseline>', 'exec'), namespace)
    if args.input:
        data = args.input.read_bytes()
        row = json.loads(data)
        row = row[0] if isinstance(row, list) else row
    else:
        row = {'content': 'Evidence excerpt.', 'document_id': 'doc_fixture',
               'document_chars': 466034, 'next_offset': 8000, 'truncated': True,
               'source_partial': False, 'warnings': ['verify table cells'],
               'extraction': {'total_pages': 194, 'partial': False, 'pages': [
                   {'page': n, 'method': 'text', 'text_chars': 2500,
                    'text_layer_blocks': [{'bbox': [1, 2, 3, 4], 'text': 'Fact evidence ' * 38}
                                          for _ in range(10)]}
                   for n in range(1, 195)]}}
        data = json.dumps(row).encode()
    before = json.dumps(row, sort_keys=True)
    baseline = benchmark(namespace['compact_row'], row)
    candidate = benchmark(compact_row, row)
    assert json.dumps(row, sort_keys=True) == before
    compact = compact_row(row)
    for key in ('content', 'document_id', 'next_offset', 'document_chars',
                'truncated', 'source_partial', 'warnings'):
        assert compact.get(key) == row.get(key)
    assert len(compact['extraction']['pages']) == len(row['extraction']['pages'])
    assert candidate['json_bytes'] < baseline['json_bytes']
    print(json.dumps({'fixture_sha256': hashlib.sha256(data).hexdigest(),
                      'fixture_kind': 'saved_fetch' if args.input else 'synthetic_pdf_metadata',
                      'scope': 'projection and JSON serialization; not acquisition latency or RSS',
                      'baseline_source_sha256': hashlib.sha256(
                          baseline_source.encode()).hexdigest(),
                      'baseline': baseline, 'candidate': candidate,
                      'canonical_metadata_unchanged': True,
                      'excerpt_handles_warnings_and_page_summaries_retained': True}, indent=2))


if __name__ == '__main__':
    main()
