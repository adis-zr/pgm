"""Independent exhaustive oracle for the signed evidence-expansion operator: the R19 packet's reference checker (tools/check_reference_tiny.py) PORTED to call the PRODUCTION module
(signed_evidence.recognize / execute / dyadic_rows) instead of the research prototype. The enumeration, the inclusion-exclusion identities and the prefix identities are the packet's
own code, unchanged; only the candidate call changed. Usage: check_round19_oracle.py OUT.json"""
from fractions import Fraction as F
from itertools import product
from pathlib import Path
import json, time, sys, os, math
HERE = os.path.dirname(os.path.abspath(__file__)); CODE = os.path.dirname(os.path.dirname(HERE))
for p in (HERE, os.path.join(CODE, 'cex', 'newarm')):
    if p not in sys.path: sys.path.insert(0, p)
import signed_evidence as SE, core
OUT = sys.argv[1]; TMP = Path(os.path.dirname(OUT)) / 'ctl_models'; TMP.mkdir(exist_ok=True)

def expectation(roots, zero_events):
    q = [F(1)] * len(roots); l = F(1)
    for leak, qs in zero_events:
        l *= leak
        for r, t in qs.items(): q[r] *= t
    return l * math.prod(1 - p + p * t for p, t in zip(roots, q))

def ie(roots, findings, extra=None, skip=None, root_one=None):
    js = [j for j in range(len(findings)) if j != skip]; ans = F(0)
    for b in product([0, 1], repeat=len(js)):
        es = [findings[j] for bit, j in zip(b, js) if bit]
        if extra is not None: es.append(extra)
        if root_one is None: val = expectation(roots, es)
        else:
            r = root_one; q = F(1); red = []
            for l, qs in es:
                q *= qs.get(r, F(1)); red.append((l, {k: v for k, v in qs.items() if k != r}))
            rp = roots.copy(); rp[r] = F(0); val = roots[r] * q * expectation(rp, red)
        ans += (-1) ** sum(b) * val
    return ans

def candidate_solve(fixture):
    model, binding = core.read_uai(str(fixture)); n = len(model['cards']); ev = model['evidence']; queries = [(x, v) for x in range(n) if x not in ev for v in range(2)]
    plan = SE.recognize(model, queries, binding, math.inf); masses = SE.execute(plan, math.inf, 1 << 30); rows = SE.dyadic_rows(masses, queries)
    return dict(Z=F(masses.Znum, masses.D), answers=[dict(var=q[0], state=q[1], lo=rows[j]['lo'], hi=rows[j]['hi'], point=rows[j]['point'], guarantee=rows[j]['guarantee']) for j, q in enumerate(queries)])

out = []; start = time.monotonic()
for mode in range(3):
    roots = [F(1, 5), F(1, 4), F(2, 5)] if mode < 2 else [F(0), F(1, 4), F(1)]
    specs = [([0, 1, 0], [F(1, 3), F(2, 5), F(3, 7)], F(9, 10)), ([1, 2], [F(0) if mode else F(2, 7), F(4, 9)], F(4, 5))]
    factors = []; prefixes = {}; findings = []; obs = []; nextvar = 3
    for r, p in enumerate(roots): factors.append(((r,), [1 - p, p]))
    for j, (rs, theta, leak) in enumerate(specs):
        a, b = rs[:2]; v = nextvar; nextvar += 1; qs = {a: theta[0], b: theta[1]}
        neg = [theta[0] ** x * theta[1] ** y for x, y in product([0, 1], repeat=2)]
        factors.append(((v, a, b), neg + [1 - z for z in neg])); prefixes[v] = (j, (F(1), qs.copy()))
        for r, t in zip(rs[2:], theta[2:]):
            prev = v; v = nextvar; nextvar += 1; neg = [t ** x * F(0) ** y for x, y in product([0, 1], repeat=2)]
            factors.append(((v, r, prev), neg + [1 - z for z in neg])); qs[r] = qs.get(r, F(1)) * t; prefixes[v] = (j, (F(1), qs.copy()))
        y = nextvar; nextvar += 1; factors.append(((y, v), [leak, 0, 1 - leak, 1])); obs.append(y); findings.append((leak, qs.copy()))
    z = F(0); nums = [F(0)] * nextvar
    for xs in product([0, 1], repeat=nextvar):
        if not all(xs[v] == 1 for v in obs): continue
        w = F(1)
        for sc, vals in factors:
            ix = 0
            for v in sc: ix = 2 * ix + xs[v]
            w *= vals[ix]
        z += w
        for v, x in enumerate(xs):
            if x: nums[v] += w
    assert z == ie(roots, findings) and z > 0
    for r in range(len(roots)): assert nums[r] == ie(roots, findings, root_one=r)
    for v, (j, pref) in prefixes.items():
        nzero = ie(roots, findings, extra=pref, skip=j) - ie(roots, findings, extra=findings[j], skip=j); assert z - nums[v] == nzero, (mode, v)
    fixture = TMP / ('r19_oracle_tiny_%d.uai' % mode); lines = ['MARKOV', str(nextvar), ' '.join(['2'] * nextvar), str(len(factors))]
    for sc, vs in factors: lines.append(str(len(sc)) + ' ' + ' '.join(map(str, sc)))
    for sc, vs in factors: lines.extend([str(len(vs)), ' '.join(map(str, vs))])
    fixture.write_text('\n'.join(lines) + '\n'); Path(str(fixture) + '.evid').write_text(str(len(obs)) + ' ' + ' '.join(str(v) + ' 1' for v in obs) + '\n')
    res = candidate_solve(fixture); assert res['Z'] == z, (mode, res['Z'], z)
    expected = {(v, state) for v in range(nextvar) if v not in obs for state in [0, 1]}; assert {(a['var'], a['state']) for a in res['answers']} == expected
    for a in res['answers']:
        truth = nums[a['var']] / z if a['state'] == 1 else 1 - nums[a['var']] / z
        assert a['lo'] <= truth <= a['hi']; Q = 1 << 40; assert a['lo'] == F(math.floor(truth * Q), Q) and a['hi'] == F(math.ceil(truth * Q), Q)
    out.append(dict(candidate_all_coordinates_checked=len(expected), candidate_Z_exact_match=True, mode=mode, Z=str(z), variables=nextvar, all_queries_exact=True, duplicate_root_chain=True, hard_zeros=bool(mode)))
# the three SUPPLIED fixtures (the packet's reference/fixtures) through the production module vs brute force over the original model
for k in range(3):
    fixture = TMP / ('tiny_noisy_or_%d.uai' % k); model, binding = core.read_uai(str(fixture)); n = len(model['cards']); ev = model['evidence']
    z = F(0); nums = [F(0)] * n
    for xs in product([0, 1], repeat=n):
        if any(xs[v] != a for v, a in ev.items()): continue
        w = F(1)
        for f in model['factors']:
            ix = 0
            for v in f['scope']: ix = 2 * ix + xs[v]
            w *= f['values'][ix]
        z += w
        for v, x in enumerate(xs):
            if x: nums[v] += w
    res = candidate_solve(fixture); assert res['Z'] == z, ('supplied', k, res['Z'], z)
    for a in res['answers']:
        truth = nums[a['var']] / z if a['state'] == 1 else 1 - nums[a['var']] / z; assert a['lo'] <= truth <= a['hi']
    out.append(dict(supplied_fixture=k, Z=str(z), coordinates=len(res['answers']), candidate_Z_exact_match=True, all_contained=True))
result = dict(pass_all=True, cases=out, elapsed_s=time.monotonic() - start, candidate='production signed_evidence.py'); Path(OUT).write_text(json.dumps(result, indent=2) + '\n'); print(json.dumps({k: v for k, v in result.items() if k != 'cases'}), len(out), 'cases')
