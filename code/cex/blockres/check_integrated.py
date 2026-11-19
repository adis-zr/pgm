"""Controls for the integrated float path (round 3) against the independent exact oracle: containment of every PAC_EB publication on the small models (complete-separator,
product-interior, ternary ring with zeros), the float tables vs the exact integers (every entry inside its relative-error bound), the zero-global-mass model (no witness ->
nothing published), an injected cap violation (refused), and a false-identity control (a query's responses replaced by a wrong constant must NOT be certified at the true value)."""
import sys, os, json, random, time, math
from fractions import Fraction as F
HERE = os.path.dirname(os.path.abspath(__file__)); CODE = os.path.dirname(os.path.dirname(HERE))
for p in (HERE, os.path.join(CODE, 'cex', 'cqr'), os.path.join(CODE, 'cex', 'newarm')):
    if p not in sys.path: sys.path.insert(0, p)
import numpy as np
import integrated as IG, blockres as BR, oracle, task as T
OUT = sys.argv[1]; TMP = os.path.join(os.path.dirname(OUT), 'ctl_models'); EPS = F(1, 200); rows = []
def truth(p):
    t = T.load_task(p); return t, oracle.truth(t['model'], t['queries'], max_assignments=1 << 20, max_table=1 << 20)
def contain(name, p, res, extra=None):
    t, r = truth(p); tv = {(q.output['variable'], q.output['state']): a for q, a in zip(t['queries'], r['answers'])}; miss = []; n = 0; worst = F(0); ex = 0
    for a in res['answers']:
        if a['guarantee'] == 'NOT_PUBLISHED': continue
        n += 1; tr = tv[(a['var'], a['state'])]; lo, hi, pt = F(a['lo']), F(a['hi']), F(a['point'])
        if a['guarantee'] == 'EXACT':
            ex += 1
            if pt != tr: miss.append((a['var'], a['state'], 'EXACT', str(pt), str(tr)))
        else:
            if not (lo <= tr <= hi) or abs(pt - tr) > EPS: miss.append((a['var'], a['state'], a['guarantee'], float(lo), float(hi), float(tr)))
            worst = max(worst, abs(pt - tr))
    m = res['mechanism']; row = dict(control=name, outcome=res['outcome'], published=n, K=res['K'], exact=ex, misses=len(miss), worst_abs_error=float(worst), ok=(not miss), detail=miss[:4], wall_s=round(res['wall_s'], 2),
                 mech={k: (round(m[k], 3) if isinstance(m.get(k), float) else m.get(k)) for k in ('blocks', 'separator_vars', 'mb_logU', 'draws', 'zero_draws', 'ms_per_draw', 'X_mean', 'median_width', 'published', 'eps_num_log2')}); 
    if extra: row.update(extra)
    row['ok'] = bool(row['ok']); rows.append(row); print(json.dumps(row, default=str)[:420]); return row
# 1-3: containment on the three approximate-route models from check.py (same files)
for name, fn, kw in (('complete_separator_14', 'c7_complete_sep.uai', dict(table_cap=1 << 6, enum_cap=1 << 4, mb_cap=16)), ('complete_separator_14_cap256', 'c7_complete_sep.uai', dict(table_cap=1 << 6, enum_cap=1 << 4, mb_cap=256)),
                     ('product_interior_10', 'c4_product_interior.uai', dict(table_cap=1 << 2, enum_cap=1 << 4, mb_cap=16)), ('ternary_ring_zeros', 'c8.uai', dict(table_cap=1 << 5, enum_cap=1 << 4, mb_cap=64))):
    p = os.path.join(TMP, fn); contain(name, p, IG.solve(p, 12.0, force_approx=True, **kw))
# 4: float tables inside their error bounds (all entries, exact rational check) on the complete-separator model
p = os.path.join(TMP, 'c7_complete_sep.uai'); model, _ = BR.core.read_uai(p); cards = model['cards']; fns, const, scale, mult, fl = BR.integerize(model); tr = []; od = []; st = dict(elim_work=0, eliminations=0, query_work=0)
live = [f for f in BR.contract(fns, cards, 1 << 6, time.monotonic() + 10, st, tr, od) if f.scope]; bad = 0; checked = 0
for f in live:
    ft = IG.ft_from_int(f, cards)
    for n, m in zip(np.asarray(f.arr, dtype=object).reshape(-1).tolist(), ft.M.reshape(-1).tolist()):
        checked += 1; approx = F(m) * F(2) ** ft.e
        if n == 0:
            if m != 0.0: bad += 1
        elif not (abs(approx - n) <= F(ft.rho) * n): bad += 1
rows.append(dict(control='float_tables_inside_relative_error_bound', checked=checked, violations=bad, ok=(bad == 0))); print(json.dumps(rows[-1], default=str))
# 5: an eliminated float message vs the exact elimination (sum over one variable of a product of two tables)
a, b = live[0], live[1]; v = next(iter(set(a.scope) & set(b.scope))) if set(a.scope) & set(b.scope) else a.scope[0]
ex = BR._eliminate([a, b], v, cards) if v in b.scope else BR._eliminate([a], v, cards); fe = IG.ft_eliminate([IG.ft_from_int(a, cards), IG.ft_from_int(b, cards)] if v in b.scope else [IG.ft_from_int(a, cards)], v, cards)
bad = 0
for n, m in zip(np.asarray(ex.arr, dtype=object).reshape(-1).tolist(), fe.M.reshape(-1).tolist()):
    approx = F(m) * F(2) ** fe.e
    if (n == 0 and m != 0.0) or (n and not abs(approx - n) <= F(fe.rho) * n): bad += 1
rows.append(dict(control='float_elimination_inside_relative_error_bound', entries=int(np.asarray(ex.arr).size), violations=bad, rho=fe.rho, ok=(bad == 0))); print(json.dumps(rows[-1], default=str))
# 6: zero global mass (overseer model): no witness -> nothing published
p = os.path.join(TMP, 'c9_zero_global_mass.uai'); res = IG.solve(p, 2.0, table_cap=64, enum_cap=16, force_approx=True, mb_cap=16)
pubs = [x for x in res['answers'] if x['guarantee'] != 'NOT_PUBLISHED']; rows.append(dict(control='zero_global_mass_nothing_published', outcome=res['outcome'], published=len(pubs), witness=res.get('positive_mass_witness'), ok=(len(pubs) == 0))); print(json.dumps(rows[-1], default=str))
# 7: injected cap violation: run the stream with logU_cap lowered by 40 bits -> the assertion must fire
p = os.path.join(TMP, 'c7_complete_sep.uai')
_orig = IG.MBFloat.__init__
def _lowered(self, *a, **k): _orig(self, *a, **k); self.logU_cap -= 40.0
IG.MBFloat.__init__ = _lowered; res = IG.solve(p, 5.0, force_approx=True, table_cap=1 << 6, enum_cap=1 << 4, mb_cap=16); IG.MBFloat.__init__ = _orig
rows.append(dict(control='injected_cap_violation_refused', outcome=res['outcome'], error=res.get('error', '')[:80], ok=(res['outcome'] == 'CERTIFICATE_DEFECT'))); print(json.dumps(rows[-1], default=str))
# 8: nonzero perturbation: feed the certificate a stream whose responses for query 0 are shifted by +3 eps; it must NOT certify an interval containing the TRUE value
rng = random.Random(3); cert = IG.Certificate(2, 1e-6 / 2, 2 ** -30); mu = 0.3; shift = 10 / 200
for t in range(60000):
    X = rng.random(); f0 = 1.0 if rng.random() < mu else 0.0; cert.update(X, np.array([min(1.0, f0 + shift), f0]))
lo, hi = cert.sets(); rows.append(dict(control='perturbed_stream_excludes_truth', shift=shift, draws=60000, set_shifted=(float(lo[0]), float(hi[0])), set_true=(float(lo[1]), float(hi[1])), truth=mu, ok=(not (lo[0] <= mu <= hi[0]) and (lo[1] <= mu <= hi[1]) and (lo[0] <= mu + shift <= hi[0])))); print(json.dumps(rows[-1], default=str))
def _py(o):
    if isinstance(o, dict): return {k: _py(v) for k, v in o.items()}
    if isinstance(o, (list, tuple)): return [_py(v) for v in o]
    if isinstance(o, (np.bool_,)): return bool(o)
    if isinstance(o, (np.floating,)): return float(o)
    if isinstance(o, (np.integer,)): return int(o)
    return o
rows = _py(rows); summary = dict(utc=time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()), version=IG.VERSION, all_ok=all(bool(r['ok']) for r in rows), rows=rows); json.dump(summary, open(OUT, 'w'), indent=1, default=str)
print('ALL_OK' if summary['all_ok'] else 'FAILURES', sum(1 for r in rows if not r['ok']), 'of', len(rows))
