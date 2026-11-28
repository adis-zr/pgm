"""Independent exhaustive oracle qualification of prototype compositions.

The oracle does not import the production parser, contraction code, or oracle.
Seeds and coverage classes are fixed before executions; failures are retained.
"""

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
from math import prod
import hashlib
import importlib
import json
import random
import time
import traceback


def oracle(model):
    ds = model['cards']
    evidence = model.get('evidence', {})
    table = {}
    total = F(0)
    for assignment in product(*(range(d) for d in ds)):
        if any(assignment[v] != a for v, a in evidence.items()):
            continue
        weight = F(1)
        for factor in model['factors']:
            offset = sum(assignment[v] * prod(ds[w] for w in factor['scope'][j+1:])
                         for j, v in enumerate(factor['scope']))
            weight *= factor['values'][offset]
        table[assignment] = weight
        total += weight
    if total == 0:
        return None
    return [[sum(w for a, w in table.items() if a[v] == s) / total
             for s in range(ds[v])] for v in range(len(ds))]


def permute(model, rng):
    """Rename variables, reorder factors and every factor's axes with data."""
    n = len(model['cards'])
    renamed = list(range(n))
    rng.shuffle(renamed)
    cards = [None] * n
    for v, d in enumerate(model['cards']):
        cards[renamed[v]] = d
    factors = []
    for f in model['factors']:
        old = f['scope']
        axis = list(old)
        rng.shuffle(axis)
        vals = []
        for xs in product(*(range(model['cards'][v]) for v in axis)):
            a = dict(zip(axis, xs))
            ix = 0
            for v in old:
                ix = ix * model['cards'][v] + a[v]
            vals.append(f['values'][ix])
        factors.append({'scope': tuple(renamed[v] for v in axis), 'values': vals})
    rng.shuffle(factors)
    return {'cards': cards, 'factors': factors,
            'evidence': {renamed[v]: a for v, a in model.get('evidence', {}).items()}}


def random_factors(seed, binary=False, bipartite=False):
    rng = random.Random(seed)
    n = rng.randrange(1, 7 if not binary else 9)
    ds = [2 if binary else rng.randrange(2, 4) for _ in range(n)]
    witness = [rng.randrange(d) for d in ds]
    factors = []
    scopes = [(v,) for v in range(n) if rng.random() < .8]
    if bipartite:
        color = [rng.randrange(2) for _ in range(n)]
        scopes += [(u, v) for u in range(n) for v in range(u+1, n)
                   if color[u] != color[v] and rng.random() < .5]
    else:
        scopes += [tuple(rng.sample(range(n), rng.randrange(1, min(n, 3)+1)))
                   for _ in range(rng.randrange(n+2))]
    for scope in scopes:
        vals = []
        for xs in product(*(range(ds[v]) for v in scope)):
            value = F(rng.randrange(5), rng.randrange(1, 8))
            if all(witness[v] == x for v, x in zip(scope, xs)):
                value += 1
            vals.append(value)
        factors.append({'scope': scope, 'values': vals})
    if factors and seed % 3 == 0:
        f = rng.choice(factors)
        factors.append({'scope': f['scope'], 'values': list(f['values'])})
    if seed % 4 == 0:
        factors.append({'scope': (), 'values': [F(3, 7)]})
    ev = {v: witness[v] for v in range(n) if rng.random() < .25}
    return permute({'cards': ds, 'factors': factors, 'evidence': ev}, rng)


def random_dag(seed):
    rng = random.Random(seed)
    n = rng.randrange(3, 7)
    ds = [rng.randrange(2, 4) for _ in range(n)]
    fs = []
    for v in range(n):
        pa = [u for u in range(v) if rng.random() < .45][-3:]
        values = []
        for _ in product(*(range(ds[u]) for u in pa)):
            row = [rng.randrange(6) for _ in range(ds[v])]
            if not sum(row):
                row[0] = 1
            scale = F(rng.randrange(99999, 100002), 100000)
            values += [scale * F(x, sum(row)) for x in row]
        fs.append({'scope': tuple(pa) + (v,), 'values': values})
    return permute({'cards': ds, 'factors': fs, 'evidence': {}}, rng)


def combined(seed):
    rng = random.Random(seed)
    # Three disconnected structural classes: a ternary chain, a binary triangle,
    # and an isolated binary variable. All factors are positive here.
    ds = [3, 2, 2, 2, 2, 2]
    fs = [{'scope': (0,), 'values': [F(1, 6), F(1, 3), F(1, 2)]},
          {'scope': (0, 1), 'values': [F(1, 4), F(3, 4), F(1, 2), F(1, 2), F(2, 3), F(1, 3)]}]
    for scope in [(2, 3), (3, 4), (2, 4)]:
        fs.append({'scope': scope, 'values': [F(rng.randrange(1, 7), rng.randrange(1, 8)) for _ in range(4)]})
    return permute({'cards': ds, 'factors': fs, 'evidence': {}}, rng)


def random_forest(seed):
    """Positive witnessed forests with mixed domains and parallel occurrences."""
    rng = random.Random(seed)
    ds = [rng.randrange(1, 4) for _ in range(rng.randrange(1, 8))]
    witness = [rng.randrange(d) for d in ds]
    scopes = [(v,) for v in range(len(ds)) if rng.random() < .8]
    for v in range(1, len(ds)):
        if rng.random() < .8:
            edge = (rng.randrange(v), v)
            scopes += [edge] * rng.randrange(1, 4)
    scopes.append(())
    fs = []
    for scope in scopes:
        values = []
        for xs in product(*(range(ds[v]) for v in scope)):
            x = F(rng.randrange(7), rng.randrange(1, 9))
            if all(witness[v] == a for v, a in zip(scope, xs)):
                x += 1
            values.append(x)
        fs.append({'scope': scope, 'values': values})
    ev = {v: a for v, a in enumerate(witness) if rng.random() < .3}
    return permute({'cards': ds, 'factors': fs, 'evidence': ev}, rng)


def correlated_additive(seed):
    """A ternary response with signed additive parts and correlated parents."""
    rng = random.Random(seed)
    ds = [3, 2, 3, 3]
    root = [rng.randrange(1, 8) for _ in range(3)]
    fs = [{'scope': (0,), 'values': [F(x, sum(root)) for x in root]},
          {'scope': (0, 1), 'values': [F(int(u == a % 2)) for a, u in product(range(3), range(2))]},
          {'scope': (0, 2), 'values': [F(int(v == a)) for a, v in product(range(3), repeat=2)]}]
    values = []
    for u, v in product(range(2), range(3)):
        f, g = F(2*u-1, 24), F(v-1, 30)
        scale = F(rng.randrange(99999, 100002), 100000) if seed % 2 else F(1)
        values += [scale * x for x in (F(1, 3)+f+g, F(1, 3)-f, F(1, 3)-g)]
    fs.append({'scope': (1, 2, 3), 'values': values})
    return permute({'cards': ds, 'factors': fs, 'evidence': {}}, rng)


def implementation_hashes():
    base = Path(__file__).parent
    names = ('core.py', 'dag.py', 'forest.py', 'geometry.py', 'planning.py',
             'reduction.py', 'stream.py', 'stream_float.py', 'support.py',
             'stream_kernel.cpp', 'libstream_kernel.so', 'qualification.py',
             'geometry_controls.py')
    return {name: hashlib.sha256((base/name).read_bytes()).hexdigest() for name in names}


def fingerprint(model):
    payload = json.dumps(model, default=str, sort_keys=True).encode()
    return hashlib.sha256(payload).hexdigest()


def check_output(model, result, truth):
    if truth is None:
        assert result.get('status') == 'ZERO_EVIDENCE'
        assert result.get('intervals') is None
        return 0
    rows = result['intervals']
    assert len(rows) == len(truth), 'wrong original row count'
    points = result.get('points')
    count = 0
    for v, row in enumerate(rows):
        assert len(row) == len(truth[v]), 'wrong original domain'
        for s, (lo, hi) in enumerate(row):
            assert 0 <= lo <= truth[v][s] <= hi <= 1, (v, s, lo, truth[v][s], hi)
            assert hi - lo <= F(1, 100), 'width budget'
            if points is not None:
                p = points[v][s]
                assert lo <= p <= hi, 'point outside its reported interval'
                assert max(abs(p-lo), abs(p-hi)) <= F(1, 200), 'robust point accuracy'
            count += 1
        if points is not None:
            assert sum(points[v]) == 1, 'simplex'
    return count


def adversarial_controls():
    import pgm.algorithms.structural.core as core
    equality = list(map(F, [1, 0, 0, 1]))
    inequality = list(map(F, [0, 1, 1, 0]))
    zero = {'cards': [2, 2, 2], 'evidence': {}, 'factors': [
        {'scope': (0, 1), 'values': equality},
        {'scope': (1, 2), 'values': equality},
        {'scope': (0, 2), 'values': inequality}]}
    negative = {'cards': [2], 'evidence': {},
                'factors': [{'scope': (), 'values': [F(-1)]}]}
    observed = {'cards': [2], 'evidence': {0: 1},
                'factors': [{'scope': (0,), 'values': [F(1), F(1)]}]}
    cases = [('global_zero_mass', zero, 'zero'),
             ('reject_negative_scalar', negative, 'invalid'),
             ('expired_fully_observed', observed, 'expired'),
             ('expired_empty_model', {'cards': [], 'factors': [], 'evidence': {}}, 'expired'),
             ('isolated_mixed_domains', {'cards': [2, 3, 1], 'factors': [], 'evidence': {}}, 'valid'),
             ('fully_observed', observed, 'valid'),
             ('zero_scalar', {'cards': [2], 'factors': [{'scope': (), 'values': [F(0)]}], 'evidence': {}}, 'zero'),
             ('invalid_factor_shape', {'cards': [2], 'factors': [{'scope': (0,), 'values': [F(1)]}], 'evidence': {}}, 'invalid')]
    rows = []
    for name, model, expected in cases:
        row = {'name': name, 'model_sha256': fingerprint(model), 'expected': expected}
        try:
            try:
                result = core.solve(model, deadline=time.monotonic() + (-1 if expected == 'expired' else 5))
            except TimeoutError:
                assert expected == 'expired'
            except ValueError as error:
                assert expected in ('zero', 'invalid'), repr(error)
                if expected == 'zero':
                    assert 'ZERO' in str(error).upper() or 'MASS' in str(error).upper()
            else:
                if expected == 'zero':
                    assert result.get('status') == 'ZERO_EVIDENCE' and result.get('intervals') is None
                else:
                    assert expected == 'valid', 'unaccepted input/deadline returned success'
                    check_output(model, result, oracle(model))
            row['status'] = 'PASS'
        except Exception as error:
            row['status'] = 'FAIL'
            row['error'] = repr(error)
        rows.append(row)
    # Simplex and epsilon accuracy alone do not enforce the campaign's separate
    # requirement that the delivered point lie in its delivered interval.
    exact = [[(F(1,3),F(1,3)), (F(2,3),F(2,3))]]
    nonmember = [[F(1,3)+F(1,1000), F(2,3)-F(1,1000)]]
    for name, operation in [('reject_nonmember_point', core.verify_output),
                            ('reject_serialized_nonmember_point', core.publish)]:
        row = {'name':name, 'expected':'invalid publication'}
        try:
            try:
                operation(exact, nonmember)
            except (AssertionError, ValueError):
                pass
            else:
                raise AssertionError('simplex-valid epsilon-close point outside interval accepted')
            row['status']='PASS'
        except Exception as error:
            row['status']='FAIL';row['error']=repr(error)
        rows.append(row)
    return rows


def run():
    hashes_before = implementation_hashes()
    cases = []
    for seed in range(80):
        cases.append(('support', 'mixed_support', 11000 + seed, random_factors(11000+seed)))
    for seed in range(60):
        cases.append(('stream', 'binary_bipartite', 12000+seed, random_factors(12000+seed, True, True)))
    for seed in range(50):
        cases.append(('dag', 'permuted_scaled_dag', 13000+seed, random_dag(13000+seed)))
    for seed in range(30):
        cases.append(('core', 'composed_disconnected', 14000+seed, combined(14000+seed)))
    # Public integrated planner also receives general zeros, evidence and axes.
    for seed in range(40):
        cases.append(('core', 'integrated_mixed', 15000+seed, random_factors(15000+seed)))
    for seed in range(40):
        model = random_forest(34000+seed)
        cases += [(module, 'mixed_parallel_forest', 34000+seed, model) for module in ('forest', 'core')]
    for seed in range(20):
        model = correlated_additive(35000+seed)
        cases += [(module, 'correlated_signed_additive', 35000+seed, model) for module in ('dag', 'core')]
    records = []
    total_coords = 0
    for module, kind, seed, model in cases:
        record = {'module': module, 'kind': kind, 'seed': seed,
                  'model_sha256': fingerprint(model), 'nvars': len(model['cards'])}
        t = time.monotonic()
        try:
            truth = oracle(model)
            solver = importlib.import_module("pgm.algorithms.structural." + module)
            result = solver.solve(model, deadline=time.monotonic()+10)
            record['coordinates_checked'] = check_output(model, result, truth)
            if module == 'dag' and kind == 'correlated_signed_additive':
                record['additive_nodes'] = result['stats']['additive_nodes']
                assert record['additive_nodes'] >= 1, 'additive construction was not exercised'
            if module == 'core' and kind == 'mixed_parallel_forest':
                assert all(c['route'] == 'forest' for c in result['stats']['components'])
                record['integrated_route'] = 'forest'
            total_coords += record['coordinates_checked']
            record['status'] = 'PASS'
        except Exception as error:
            record['status'] = 'FAIL'
            record['error'] = repr(error)
            record['traceback'] = traceback.format_exc()
        record['oracle_and_execution_s'] = time.monotonic()-t
        records.append(record)
    from research.campaigns.structural.geometry_controls import run as geometry_run
    geometry = geometry_run()
    guards = adversarial_controls()
    hashes_after = implementation_hashes()
    stable = hashes_before == hashes_after
    return {'records': records, 'total_models': len(records),
            'passed': sum(x['status']=='PASS' for x in records),
            'coordinates_checked': total_coords,
            'geometry': geometry,
            'adversarial_controls': guards,
            'qualified_hashes': hashes_after, 'implementation_stable_during_run': stable,
            'all_pass': stable and all(x['status']=='PASS' for x in records + guards) and geometry['all_pass'],
            'scope': 'Exact exhaustive independent oracle on small legal inputs; no benchmark inference or implementation proof.'}


if __name__ == '__main__':
    out = run()
    Path(__file__).with_name('qualification.json').write_text(json.dumps(out, indent=2)+'\n')
    print(json.dumps({k:v for k,v in out.items() if k not in ('records','geometry')}, indent=2))
    for record in out['records']:
        if record['status'] != 'PASS':
            print(record['module'], record['seed'], record['error'])
