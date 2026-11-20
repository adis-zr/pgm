"""Round-7 controls for the EXACT ROUTE (unsplit mini-bucket pass -> shared backward differential): every DETERMINISTIC_EXACT_ROUTE publication must contain the independent
oracle truth (small models with hard zeros, evidence, large separators); the existing certified executor cross-check must agree; a split construction must NOT take the exact route;
an injected derivative corruption must be caught by the executor cross-check (INVESTIGATE, nothing published)."""
import sys, os, json, random, time, math
from fractions import Fraction as F
HERE = os.path.dirname(os.path.abspath(__file__)); CODE = os.path.dirname(os.path.dirname(HERE))
for p in (HERE, os.path.join(CODE, 'cex', 'cqr'), os.path.join(CODE, 'cex', 'newarm')):
    if p not in sys.path: sys.path.insert(0, p)
import numpy as np
import integrated as IG, blockres as BR, oracle, task as T
OUT = sys.argv[1]; TMP = os.path.join(os.path.dirname(OUT), 'ctl_models'); rows = []
def say(r): r['ok'] = bool(r['ok']); rows.append(r); print(json.dumps(r, default=str)[:400])
def write_uai(name, cards, factors, evidence=None):
    p = os.path.join(TMP, name + '.uai'); lines = ['MARKOV', str(len(cards)), ' '.join(map(str, cards)), str(len(factors))]
    for sc, _ in factors: lines.append('%d %s' % (len(sc), ' '.join(map(str, sc))))
    for sc, vals in factors: lines.append(str(len(vals))); lines.append(' '.join(str(v) for v in vals))
    open(p, 'w').write('\n'.join(lines) + '\n'); ev = evidence or {}; open(p + '.evid', 'w').write(('%d ' % len(ev)) + ' '.join('%d %d' % kv for kv in ev.items()) + '\n'); return p
def contain(name, p, kw):
    t = T.load_task(p); r = oracle.truth(t['model'], t['queries'], max_assignments=1 << 20, max_table=1 << 20); tv = {(q.output['variable'], q.output['state']): a for q, a in zip(t['queries'], r['answers'])}
    res = IG.solve(p, 15.0, force_approx=True, **kw); n = 0; miss = []; byg = {}; maxw = F(0)
    for a in res['answers']:
        byg[a['guarantee']] = byg.get(a['guarantee'], 0) + 1
        if a['guarantee'] == 'NOT_PUBLISHED': continue
        n += 1; tr = tv[(a['var'], a['state'])]; lo, hi = F(a['lo']), F(a['hi']); maxw = max(maxw, hi - lo)
        if not (lo <= tr <= hi): miss.append((a['var'], a['state'], float(lo), float(hi), float(tr)))
    m = res['mechanism']; er = m.get('exact_route') or {}
    say(dict(control=name, outcome=res['outcome'], route=m.get('route'), splits=m.get('mb_splits'), published=n, K=res['K'], by=byg, misses=len(miss), max_width=float(maxw), exact_status=er.get('status'), crosscheck=er.get('crosscheck'), wall_s=round(res['wall_s'], 2), ok=(n == res['K'] and not miss and m.get('route') == 'exact'), detail=miss[:3]))
rng = random.Random(11)
def rnd(n, zeros=0.0, lo=1, hi=9): return [0 if rng.random() < zeros else rng.randint(lo, hi) for _ in range(n)]
# E1: complete separator on 14 binary variables with private chains (unsplit at cap 2^14)
contain('E1_complete_separator_unsplit', os.path.join(TMP, 'c7_complete_sep.uai'), dict(table_cap=1 << 6, enum_cap=1 << 4, mb_cap=1 << 14))
# E2: product-interior model
contain('E2_product_interior_unsplit', os.path.join(TMP, 'c4_product_interior.uai'), dict(table_cap=1 << 2, enum_cap=1 << 4, mb_cap=1 << 12))
# E3: hard zeros + evidence + ternary cards on a COMPLETE separator graph of 7 ternary variables (3^7 = 2187 > enum cap; blocks = private binary chains), unsplit at cap 3^7
nS = 7; cards = [3] * nS + [2] * (2 * nS); facs = []
for i in range(nS):
    for j in range(i + 1, nS): facs.append(((i, j), rnd(9, zeros=0.2)))
    y0, y1 = nS + 2 * i, nS + 2 * i + 1; facs.append(((i, y0), rnd(6, zeros=0.15))); facs.append(((y0, y1), rnd(4)))
contain('E3_ternary_complete_zeros_evidence', write_uai('e3_complete_zeros', cards, facs, evidence={nS + 1: 0, 4: 2}), dict(table_cap=1 << 3, enum_cap=1 << 4, mb_cap=3 ** 7))
# E4: mixed cardinalities with unary factors and a factorless variable
cards = [2, 3, 4, 2, 5, 3, 2]; facs = [((0, 1), rnd(6)), ((1, 2), rnd(12, zeros=0.2)), ((2, 3), rnd(8)), ((3, 4), rnd(10)), ((4, 5), rnd(15)), ((1,), rnd(3)), ((5,), [0, 1, 2])]
contain('E4_mixed_cards_unary_factorless', write_uai('e4_mixed', cards, facs), dict(table_cap=0, enum_cap=1, mb_cap=1 << 10))
# E5: a SPLIT construction must not take the exact route (cap too small for the complete separator)
p = os.path.join(TMP, 'c7_complete_sep.uai'); res = IG.solve(p, 3.0, force_approx=True, table_cap=1 << 6, enum_cap=1 << 4, mb_cap=16, route='auto')
say(dict(control='E5_split_construction_stays_pac', splits=res['mechanism'].get('mb_splits'), route=res['mechanism'].get('route'), ok=(res['mechanism'].get('mb_splits', 0) > 0 and res['mechanism'].get('route') == 'pac')))
# E6: injected derivative corruption -> the executor cross-check must flag INVESTIGATE and nothing may be published on the exact route
_orig = IG.backward_derivatives
def _corrupt(mbp, cards, deadline):
    D = _orig(mbp, cards, deadline)
    for fi in mbp.inputs: D[id(fi)] = IG.FT(D[id(fi)].scope, D[id(fi)].M * 1.5, D[id(fi)].e, D[id(fi)].rho)       # every block derivative scaled by 1.5: all numerators wrong by 1.5x
    return D
IG.backward_derivatives = _corrupt
res = IG.solve(os.path.join(TMP, 'c7_complete_sep.uai'), 10.0, force_approx=True, table_cap=1 << 6, enum_cap=1 << 4, mb_cap=1 << 14, route='exact'); IG.backward_derivatives = _orig
er = res['mechanism'].get('exact_route') or {}; pubs = [a for a in res['answers'] if a['guarantee'] == 'DETERMINISTIC_EXACT_ROUTE']
say(dict(control='E6_corrupted_derivative_caught_by_executor_crosscheck', status=str(er.get('status'))[:80], exact_route_publications=len(pubs), outcome=res['outcome'], ok=(str(er.get('status', '')).startswith('INVESTIGATE') and not pubs)))
summary = dict(utc=time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()), version=IG.VERSION, all_ok=all(r['ok'] for r in rows), rows=rows); json.dump(summary, open(OUT, 'w'), indent=1, default=str)
print('ALL_OK' if summary['all_ok'] else 'FAILURES', sum(1 for r in rows if not r['ok']), 'of', len(rows))
