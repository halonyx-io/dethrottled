#!/usr/bin/env python3
"""Replay URL identity inputs against the pre-refactor implementation and current code."""
import argparse
import ast
import hashlib
import json
import platform
import statistics
import subprocess
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def load(source):
    """Load only the URL helper and its constants/imports; no fetch initialization."""
    tree = ast.parse(source)
    tree.body = [n for n in tree.body if (
        (isinstance(n, ast.ImportFrom) and n.module == 'urllib.parse')
        or (isinstance(n, ast.FunctionDef) and n.name == 'canonical_url')
        or (isinstance(n, ast.Assign) and any(
            isinstance(t, ast.Name) and t.id == '_JUNK_PARAMS' for t in n.targets)))]
    namespace = {}
    exec(compile(tree, '<url-normalization>', 'exec'), namespace)
    return namespace['canonical_url']


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--baseline', default='523c2bba303654e517b4d0f2f9a3db203966c826')
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    baseline_source = subprocess.check_output(
        ['git', 'show', args.baseline + ':src/dethrottled/fetch.py'], cwd=ROOT, text=True)
    candidate_source = (ROOT / 'src/dethrottled/urls.py').read_text()
    functions = {'baseline': load(baseline_source), 'candidate': load(candidate_source)}
    workloads = {
        'no_query': [f'https://www.example.com/a/{i}/#section' for i in range(5000)],
        'two_parameters': [f'https://m.example.com/a/{i}?id={i}&UTM_source=feed'
                           for i in range(5000)],
        'twelve_parameters': [f'https://example.com/a/{i}?' + '&'.join(
            f'{key}={i}' for key in ('id', 'q', 'UTM_source', 'FBCLID', 'empty', 'lang',
                                    'page', 'ref_src', 'my_utm_source', 'sort', 'filter', 'tag'))
                              for i in range(5000)],
    }
    edge_cases = ['', ' ', None, 'https://[bad', 'mailto:a@b.c',
                  'https://example.com/?id=1&id=2&empty=&q=caf%C3%A9',
                  'https://www.m.amp.example.com/Path/?REF=x&referral=y']
    for values in [edge_cases, *workloads.values()]:
        assert [functions['baseline'](u) for u in values] == [
            functions['candidate'](u) for u in values]
    result = {'baseline_revision': args.baseline, 'python': platform.python_version(),
              'machine': platform.machine(), 'rounds': 9,
              'candidate_sha256': hashlib.sha256(candidate_source.encode()).hexdigest(),
              'identical_outputs': 15000 + len(edge_cases), 'workloads': {}}
    for name, urls in workloads.items():
        for function in functions.values():
            for url in urls[:100]:
                function(url)
        timings = {name: [] for name in functions}
        for repeat in range(result['rounds']):
            order = list(functions) if repeat % 2 == 0 else list(reversed(functions))
            for variant in order:
                start = time.perf_counter()
                for url in urls:
                    functions[variant](url)
                timings[variant].append((time.perf_counter() - start) * 1000)
        medians = {key: statistics.median(values) for key, values in timings.items()}
        result['workloads'][name] = {
            'urls_per_round': len(urls), 'elapsed_ms': timings, 'median_ms': medians,
            'median_speedup': medians['baseline'] / medians['candidate']}
    args.output.write_text(json.dumps(result, indent=2) + '\n')
    print(json.dumps({k: v['median_speedup'] for k, v in result['workloads'].items()}))


if __name__ == '__main__':
    main()
