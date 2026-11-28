"""Independent exact-enumeration controls for the native stream certificate."""

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
import ctypes
import hashlib
import json
import random
import time

import pgm.algorithms.structural.stream_float as stream_float


def truth(model):
    cards = model['cards']
    out = [[F(0) for _ in range(d)] for d in cards]
    z = F(0)
    for xs in product(*(range(d) for d in cards)):
        if any(xs[v] != a for v, a in model['evidence'].items()):
            continue
        w = F(1)
        for factor in model['factors']:
            index = 0
            for v in factor['scope']:
                index = index * cards[v] + xs[v]
            w *= factor['values'][index]
        z += w
        for v, a in enumerate(xs):
            out[v][a] += w
    return None if z == 0 else [[q / z for q in row] for row in out]


def hashes():
    root = Path(__file__).resolve().parent
    return {name: hashlib.sha256((root / name).read_bytes()).hexdigest()
            for name in ['stream_float.py', 'stream.py', 'stream_kernel.cpp', 'libstream_kernel.so']}


def run():
    stream_float.build()
    before = hashes()
    receipts = []
    for seed in range(60):
        rng = random.Random(seed + 173000)
        n = 7
        ids = list(range(n))
        rng.shuffle(ids)
        left, right = ids[:3], ids[3:]
        factors = []
        for v in ids:
            factors.append({'scope': (v,), 'values': [
                F(rng.randrange(0, 12), rng.randrange(1, 13)) for _ in range(2)]})
        for a in left:
            for b in right:
                if rng.random() < .6:
                    pair = (a, b) if rng.random() < .5 else (b, a)
                    factors.append({'scope': pair, 'values': [
                        F(rng.randrange(0, 12), rng.randrange(1, 13)) for _ in range(4)]})
                    if rng.random() < .15:
                        factors.append({'scope': pair[::-1], 'values': [
                            F(rng.randrange(1, 8), rng.randrange(1, 9)) for _ in range(4)]})
        evidence = {v: rng.randrange(2) for v in rng.sample(ids, seed % 3)}
        model = {'cards': [2] * n, 'factors': factors, 'evidence': evidence}
        exact = truth(model)
        try:
            result = stream_float.solve(model, deadline=time.monotonic() + 10)
        except ValueError as error:
            assert exact is None, (seed, str(error))
            receipts.append({'seed': seed, 'zero_mass_detected': True})
            continue
        assert exact is not None
        for v, row in enumerate(exact):
            assert sum(result['points'][v]) == 1
            for a, value in enumerate(row):
                lo, hi = result['intervals'][v][a]
                point = result['points'][v][a]
                assert lo <= value <= hi, (seed, v, a, value, lo, hi)
                assert 0 <= lo <= hi <= 1 and hi-lo <= F(1, 100)
                assert max(abs(point-lo), abs(point-hi)) <= F(1, 200)
        receipts.append({'seed': seed, 'all_coordinates_contained': True,
                         'configurations': result['stats']['configurations']})
    model = {'cards': [2], 'factors': [
        {'scope': (0,), 'values': [F(1, 10**400), F(1)]}], 'evidence': {}}
    try:
        stream_float.solve(model)
        raise AssertionError('extreme source ratio accepted')
    except stream_float.RangeError:
        range_ok = True
    model = {'cards': [2], 'factors': [
        {'scope': (0,), 'values': [F(1, 3), F(2, 3)]}], 'evidence': {}}
    libc = ctypes.CDLL(None)
    old = libc.fegetround()
    round_ok = False
    try:
        assert libc.fesetround(0x400) == 0  # FE_DOWNWARD on the qualified Linux host.
        try:
            stream_float.solve(model)
            raise AssertionError('wrong rounding mode accepted')
        except stream_float.RangeError:
            round_ok = True
    finally:
        assert libc.fesetround(old) == 0
    assert hashes() == before, 'audited files changed during controls'
    report = {'controls': receipts, 'range_refusal': range_ok,
              'wrong_round_mode_refusal': round_ok, 'source_and_binary_hashes': before,
              'scope': 'Independent exact oracle on 60 tiny bipartite models; no benchmark replay and no formal software verification.'}
    path = Path(__file__).resolve().parent / 'THEORY_NATIVE_AUDIT.json'
    path.write_text(json.dumps(report, indent=2) + '\n')
    print({'controls': len(receipts),
           'positive': sum('all_coordinates_contained' in r for r in receipts),
           'zero': sum('zero_mass_detected' in r for r in receipts),
           'range': range_ok, 'rounding': round_ok, 'hashes': before})


if __name__ == '__main__':
    run()
