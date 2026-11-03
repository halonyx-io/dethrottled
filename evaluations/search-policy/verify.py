"""Verify published retrieval aggregates against per-query evidence, offline.

Run from any directory with Python 3.10+. This checks arithmetic, completeness,
URL menu bounds and artifact integrity; it does not adjudicate relevance labels.
"""

import collections
import csv
import hashlib
import json
import math
import statistics
from pathlib import Path

ROOT = Path(__file__).resolve().parent / 'results' / '2026-11-03'


def main():
    manifest = json.loads((ROOT / 'SHA256SUMS.json').read_text())
    for name, digest in manifest.items():
        assert hashlib.sha256((ROOT / name).read_bytes()).hexdigest() == digest, name
    with (ROOT / 'per-query-comparison.csv').open(newline='') as source:
        rows = list(csv.DictReader(source))
    groups = collections.defaultdict(list)
    identities = set()
    for row in rows:
        identity = row['pool'], row['judge'], row['id']
        assert identity not in identities, identity
        identities.add(identity)
        groups[row['pool'], row['judge']].append(row)
        for column in ('baseline_urls', 'xgb_urls'):
            urls = json.loads(row[column])
            assert len(urls) <= 15 and len(urls) == len(set(urls)), identity
        for k in (3, 5):
            before, after = (int(row[f'{name}_useful{k}']) for name in ('baseline', 'xgb'))
            assert 0 <= before <= k and 0 <= after <= k, identity
            assert int(row[f'delta{k}']) == after - before, identity
    summaries = json.loads((ROOT / 'test-summary.json').read_text())
    expected_groups = {(p, j) for p in ('small', 'page1', 'deep')
                       for j in ('primary', 'secondary')}
    assert set(groups) == expected_groups
    assert {(s['pool'], s['judge']) for s in summaries} == expected_groups
    assert len(rows) == 600
    question_sets = [{r['id'] for r in g} for g in groups.values()]
    assert all(len(g) == 100 for g in groups.values())
    assert all(q == question_sets[0] for q in question_sets)
    for summary in summaries:
        group = groups[summary['pool'], summary['judge']]
        for k in (3, 5):
            for column, policy in (('baseline', 'balanced_source15'), ('xgb', 'xgboost')):
                actual = statistics.mean(int(r[f'{column}_useful{k}']) for r in group)
                assert math.isclose(actual, summary['metrics'][policy][f'useful{k}'],
                                    abs_tol=1e-12)
            paired = summary['paired_vs_balanced_source15']['xgboost'][f'useful{k}']
            deltas = [int(r[f'delta{k}']) for r in group]
            assert math.isclose(statistics.mean(deltas), paired['delta'], abs_tol=1e-12)
            assert paired['wins'] == sum(d > 0 for d in deltas)
            assert paired['losses'] == sum(d < 0 for d in deltas)
            assert paired['ties'] == sum(d == 0 for d in deltas)
    print(json.dumps({'passed': True, 'artifact_hashes': len(manifest),
                      'per_query_rows': len(rows), 'test_questions': len(question_sets[0]),
                      'pool_judge_groups': len(groups), 'verified_means': 24,
                      'scope': 'Integrity/arithmetic only; model judgements are not ground truth.'},
                     indent=2))


if __name__ == '__main__':
    main()
