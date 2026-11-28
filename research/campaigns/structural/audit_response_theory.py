"""Independent qualification of additive observable synthesis in source DAGs."""

# Source-checkout entry point; production imports never traverse research.
if __package__ in (None, ""):
    import sys as _research_sys
    from pathlib import Path as _ResearchPath
    _research_sys.path.insert(0, str(_ResearchPath(__file__).resolve().parents[3]))
from research.bootstrap import activate as _activate_research
_activate_research()
from research.paths import repo_root as _repo_root, runs_root as _runs_root, records_root as _records_root, source_path as _source_path
from fractions import Fraction as F
from itertools import product
from pathlib import Path
import hashlib
import json
import random
import time

import pgm.algorithms.structural.dag as dag
from research.campaigns.structural.audit_forest_theory import exact_oracle

HERE = Path(__file__).resolve().parent


def model_for(seed, nonlinear):
    rng = random.Random(seed)
    cards = [2, 2, 3, 2, 2]
    parents = [(), (0,), (0,), (1, 2), (0, 1, 3)]
    signs = [rng.choice((-1, 1)) for _ in range(5)]
    factors = []
    for child, ps in enumerate(parents):
        scope = ps + (child,)
        table = {}
        for pa in product(*(range(cards[v]) for v in ps)):
            if child == 0:
                row = (F(3, 5), F(2, 5))
            elif child == 1:
                q = F(1, 5) + F(3, 5) * pa[0]
                row = (1 - q, q)
            elif child == 2:
                row = (F(1, 2), F(1, 3), F(1, 6)) if pa[0] == 0 else (F(1, 6), F(1, 3), F(1, 2))
            elif child == 3:
                q = F(1, 5) + F(1, 10) * pa[0] * pa[1] if nonlinear else F(1, 3) + signs[0] * F(1, 12) * pa[0] + signs[1] * F(1, 24) * pa[1]
                row = (1 - q, q)
            else:
                q = F(1, 3) + signs[2] * F(1, 20) * pa[0] + signs[3] * F(1, 10) * pa[1] + signs[4] * F(1, 12) * pa[2]
                row = (1 - q, q)
            assert sum(row) == 1 and all(0 <= x <= 1 for x in row)
            # A tiny nonconstant source-row gauge makes the raw task differ
            # from Q, so the composed distortion enclosure is checked too.
            scale = 1 + F(sum(pa) % 2, 100000)
            for state, weight in enumerate(row):
                table[pa + (state,)] = weight * scale
        shuffled = list(scope)
        rng.shuffle(shuffled)
        values = []
        for assignment in product(*(range(cards[v]) for v in shuffled)):
            byvar = dict(zip(shuffled, assignment))
            values.append(table[tuple(byvar[v] for v in scope)])
        factors.append({'scope': tuple(shuffled), 'values': values})
    permutation = list(range(len(cards)))
    rng.shuffle(permutation)
    renamed_cards = [None] * len(cards)
    for old, new in enumerate(permutation):
        renamed_cards[new] = cards[old]
    for factor in factors:
        factor['scope'] = tuple(permutation[v] for v in factor['scope'])
    rng.shuffle(factors)
    return {'cards': renamed_cards, 'factors': factors, 'evidence': {}}


def main():
    start = time.monotonic()
    paths = [Path(_source_path('pgm.algorithms.structural.dag')), HERE / 'audit_forest_theory.py', Path(__file__)]
    before = {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in paths}
    accepted = rejected = checked_coordinates = 0
    for seed in range(24):
        nonlinear = bool(seed % 2)
        model = model_for(91701 + seed, nonlinear)
        plan = dag.plan(model)
        result = dag.execute_plan(plan)
        ordinary = dag.solve(model, additive=False)
        truth = exact_oracle(model)
        assert result['points'] == ordinary['points']
        assert result['stats']['scalar_ops_predicted'] < ordinary['stats']['scalar_ops_predicted']
        assert len(plan['additive_identities']) == (1 if nonlinear else 2)
        for child in plan['additive_identities']:
            assert not plan['independent'][child], 'control must exercise correlated parents'
            accepted += 1
        rejected += sum(not check['accepted'] for check in plan['additive_checks'])
        for row, boxes, point in zip(truth, result['intervals'], result['points']):
            assert sum(point) == 1
            for target, (lo, hi), estimate in zip(row, boxes, point):
                assert 0 <= lo <= target <= hi <= 1
                assert lo <= estimate <= hi
                assert abs(estimate - target) <= F(1, 200)
                checked_coordinates += 1
    after = {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in paths}
    assert before == after, 'source changed during response qualification'
    receipt = {
        'status': 'PASS', 'sha256': after, 'models': 24,
        'correlated_parent_additive_identities': accepted,
        'rejected_nonlinear_identities': rejected,
        'original_coordinates_checked': checked_coordinates,
        'elapsed_s': time.monotonic() - start,
        'coverage': ['signed additive coefficients', 'correlated parent ancestors', 'unequal domains', 'arbitrary variable relabeling', 'arbitrary within-factor axis order', 'factor occurrence order', 'nonlinear interaction rejection', 'exact equality to ordinary source-DAG computation', 'strictly lower decoder execution count', 'raw-model distortion composition against exact enumeration'],
        'scope': 'Independent executable qualification of the additive specialization; no general linear-algebra synthesis or intrinsic operation optimum is claimed.'
    }
    (HERE / 'THEORY_RESPONSE_AUDIT.json').write_text(json.dumps(receipt, indent=2) + '\n')
    print(json.dumps(receipt, indent=2))


if __name__ == '__main__':
    main()
