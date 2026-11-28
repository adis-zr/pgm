"""Independent exact-arithmetic qualification of the scaled forest proof.

Run: python prototype/audit_forest_theory.py
The receipt binds the tested implementation and this checker. It is executable
qualification evidence, not a formal proof of the Python interpreter/compiler.
"""
from fractions import Fraction as F
from itertools import product
from pathlib import Path
import hashlib
import json
import random
import time

import forest

HERE = Path(__file__).resolve().parent


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def value(x):
    return F(x.m) * (F(2) ** x.e)


def exact_oracle(model):
    cards = model['cards']
    rows = [[F(0)] * d for d in cards]
    z = F(0)
    for assignment in product(*(range(d) for d in cards)):
        if any(assignment[v] != a for v, a in model['evidence'].items()):
            continue
        weight = F(1)
        for factor in model['factors']:
            offset = 0
            for v in factor['scope']:
                offset = offset * cards[v] + assignment[v]
            weight *= factor['values'][offset]
        z += weight
        for v, a in enumerate(assignment):
            rows[v][a] += weight
    return None if z == 0 else [[x / z for x in row] for row in rows]


def arithmetic_controls():
    rng = random.Random(63042)
    checks = 0
    for p in (3, 5, 8, 17, 53):
        arithmetic = forest.Arithmetic(p)
        u = F(1, 2 ** (p - 1))
        for _ in range(200):
            x = F(rng.randrange(1, 10000), rng.randrange(1, 10000)) * F(2) ** rng.randint(-400, 400)
            y = F(rng.randrange(1, 10000), rng.randrange(1, 10000)) * F(2) ** rng.randint(-400, 400)
            a, b = arithmetic.source(x), arithmetic.source(y)
            for result, truth in ((a, x), (b, y), (arithmetic.add(a, b), x + y), (arithmetic.mul(a, b), x * y)):
                assert (1 - u) ** result.E * truth <= value(result.lo) <= truth <= value(result.hi) <= (1 + u) ** result.E * truth
                checks += 1
            result = arithmetic.div(a, b)
            truth = x / y
            # The quotient label has the reciprocal bound, distinct from the
            # source/add/product invariant. Quotients are terminal responses.
            assert (1 - u) ** result.E * truth <= value(result.lo) <= truth <= value(result.hi) <= truth / (1 - u) ** result.E
            checks += 1
        for _ in range(100):
            x = F(rng.randrange(1, 10000), rng.randrange(1, 10000)) * F(2) ** rng.randint(-400, 400)
            result = arithmetic.source(x)
            for grid_bits in (1, 7, 19):
                lo = F(forest._grid(result.lo, grid_bits, False), 2 ** grid_bits)
                hi = F(forest._grid(result.hi, grid_bits, True), 2 ** grid_bits)
                assert lo <= min(x, 1) <= hi
                checks += 1
    assert checks == 6500
    return checks


def full_model_controls():
    rng = random.Random(94412)
    positive = zero = 0
    for case in range(80):
        n = rng.randint(1, 7)
        cards = [rng.randint(1, 3) for _ in range(n)]
        factors = []
        for v in range(n):
            for _ in range(rng.randint(0, 2)):
                factors.append({'scope': (v,), 'values': [F(rng.randint(0, 9), rng.randint(1, 13)) for _ in range(cards[v])]})
            if v and rng.random() < .8:
                w = rng.randrange(v)
                for _ in range(rng.randint(1, 3)):
                    scope = (v, w) if rng.randrange(2) else (w, v)
                    factors.append({'scope': scope, 'values': [F(rng.randint(0, 9), rng.randint(1, 13)) for _ in range(cards[scope[0]] * cards[scope[1]])]})
        if rng.random() < .3:
            factors.append({'scope': (), 'values': [F(rng.randint(0, 2), 3)]})
        model = {'cards': cards, 'factors': factors, 'evidence': {v: rng.randrange(cards[v]) for v in range(n) if rng.random() < .17}}
        truth = exact_oracle(model)
        epsilon = (F(1, 200), F(1, 3), F(1, 100000), F(1))[case % 4]
        if truth is None:
            try:
                forest.solve(model, epsilon=epsilon)
            except forest.ZeroEvidence:
                zero += 1
            else:
                raise AssertionError(('accepted zero evidence', case))
            continue
        result = forest.solve(model, epsilon=epsilon)
        assert result['stats']['independent_replay']
        for target, row, point in zip(truth, result['intervals'], result['points']):
            assert sum(point) == 1
            for actual, (lo, hi), estimate in zip(target, row, point):
                assert 0 <= lo <= actual <= hi <= 1
                assert lo <= estimate <= hi
                assert hi - lo <= 2 * epsilon
                assert max(abs(estimate - lo), abs(estimate - hi)) <= epsilon
                assert abs(estimate - actual) <= epsilon
        positive += 1
    return {'models': 80, 'positive': positive, 'zero_evidence': zero}


def main():
    start = time.monotonic()
    paths = {'forest.py': HERE / 'forest.py', Path(__file__).name: Path(__file__)}
    before = {name: sha(path) for name, path in paths.items()}
    arithmetic = arithmetic_controls()
    models = full_model_controls()
    after = {name: sha(path) for name, path in paths.items()}
    assert before == after, 'source changed during independent audit'
    receipt = {
        'status': 'PASS', 'sha256': after,
        'arithmetic_and_grid_checks': arithmetic,
        'full_model_controls': models,
        'seeds': {'arithmetic': 63042, 'models': 94412},
        'coverage': ['directed conversion/addition/product/terminal quotient', 'exact rational oracle', 'small and large exponent gaps', 'clipped dyadic publication', 'unequal domains including singleton domains', 'reversed pair axes', 'parallel factors', 'disconnected and isolated variables', 'literal zeros and zero evidence', 'evidence restriction', 'four tolerance levels', 'all original singleton coordinates', 'exact simplex and point membership'],
        'elapsed_s': time.monotonic() - start,
        'scope': 'Independent executable qualification and mathematical source review; not a formal proof of Python or a universal optimality certificate.'
    }
    output = HERE / 'THEORY_FOREST_AUDIT.json'
    output.write_text(json.dumps(receipt, indent=2) + '\n')
    print(json.dumps(receipt, indent=2))


if __name__ == '__main__':
    main()
