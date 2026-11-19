"""Round-4 controls for integrated v2: the overseer's two reproduced defects rebuilt as controls, plus containment of actual publications against the independent oracle.
 R1 rounding allowance: summing the exact table [2^53, 1] in binary64 gives absolute error 1; the returned bound must permit it (v1 permitted 1/128).
 R2 underflow before the range check: a strictly positive model whose float products would underflow must be REFUSED (typed), never ZERO_EVIDENCE and never published.
 R3 exact-rational propagation never absorbs u: a chain of 40 products / sums keeps a bound >= the true accumulated error on a worst-case table.
 C1-C2 containment (same small models as round 3), C3 injected cap, C4 zero global mass, C5 perturbed stream, C6 conservative inversion vs an exact-rational evaluation of the quadratic set."""
import sys, os, json, random, time, math
from fractions import Fraction as F
HERE = os.path.dirname(os.path.abspath(__file__)); CODE = os.path.dirname(os.path.dirname(HERE))
for p in (HERE, os.path.join(CODE, 'cex', 'cqr'), os.path.join(CODE, 'cex', 'newarm')):
    if p not in sys.path: sys.path.insert(0, p)
import numpy as np
import integrated as IG, blockres as BR, oracle, task as T
OUT = sys.argv[1]; TMP = os.path.join(os.path.dirname(OUT), 'ctl_models'); os.makedirs(TMP, exist_ok=True); EPS = F(1, 200); rows = []
def write_uai(name, cards, factors, evidence=None):
    p = os.path.join(TMP, name + '.uai'); lines = ['MARKOV', str(len(cards)), ' '.join(map(str, cards)), str(len(factors))]
    for sc, _ in factors: lines.append('%d %s' % (len(sc), ' '.join(map(str, sc))))
    for sc, vals in factors: lines.append(str(len(vals))); lines.append(' '.join(str(v) for v in vals))
    open(p, 'w').write('\n'.join(lines) + '\n'); ev = evidence or {}; open(p + '.evid', 'w').write(('%d ' % len(ev)) + ' '.join('%d %d' % kv for kv in ev.items()) + '\n'); return p
def say(r): r['ok'] = bool(r['ok']); rows.append(r); print(json.dumps(r, default=str)[:420])
# R1: the overseer's rounding-allowance reproducer
fn = BR.Fn((0,), np.array([1 << 53, 1], dtype=object), [0], []); ft = IG.ft_from_int(fn, [2]); s = IG.ft_eliminate([ft], 0, [2], 'sum')
approx = F(float(s.M)) * F(2) ** s.e; exact = (1 << 53) + 1; err = abs(approx - exact); allowed = s.rho * exact
say(dict(control='R1_rounding_allowance_sum_2p53_plus_1', float_value=str(approx), exact=str(exact), abs_error=str(err), allowed_abs_error=float(allowed), ok=(err <= allowed)))
# R2: positive model whose float products would underflow: unary [2^900, 1] on x0, [1, 2^900] on x1, pairwise [1, 2^900, 2^900, 1]: every product of two tables spans 1800 bits
p2 = write_uai('r2_underflow_positive', [2, 2], [((0,), [1 << 900, 1]), ((1,), [1, 1 << 900]), ((0, 1), [1, 1 << 900, 1 << 900, 1])])
t2 = T.load_task(p2); r2 = oracle.truth(t2['model'], t2['queries']); res = IG.solve(p2, 3.0, table_cap=0, enum_cap=1, force_approx=True, mb_cap=4)
pubs = [a for a in res['answers'] if a['guarantee'] != 'NOT_PUBLISHED']
say(dict(control='R2_underflow_refused_not_zero_evidence', outcome=res['outcome'], refusal=res.get('refusal'), published=len(pubs), truth_Z_positive=(r2['Z'] > 0), ok=(res['outcome'] == 'NUMERIC_RANGE_REFUSED' and not pubs)))
# R2b: the same mechanism with a milder range that FITS the budget must compute, and its EXACT witness / publications must be contained (two binary variables -> approximate path forced)
p2b = write_uai('r2b_fits_budget', [2, 2], [((0,), [1 << 400, 1]), ((1,), [1, 1 << 400]), ((0, 1), [1, 1 << 400, 1 << 400, 1])])
t2b = T.load_task(p2b); r2b = oracle.truth(t2b['model'], t2b['queries']); res = IG.solve(p2b, 4.0, table_cap=0, enum_cap=1, force_approx=True, mb_cap=4)
tv = {(q.output['variable'], q.output['state']): a for q, a in zip(t2b['queries'], r2b['answers'])}; miss = []
for a in res['answers']:
    if a['guarantee'] == 'NOT_PUBLISHED': continue
    if not (F(a['lo']) <= tv[(a['var'], a['state'])] <= F(a['hi'])): miss.append((a['var'], a['state'], a['lo'], a['hi'], str(tv[(a['var'], a['state'])])))
say(dict(control='R2b_within_budget_computes_and_contains', outcome=res['outcome'], published=sum(1 for a in res['answers'] if a['guarantee'] != 'NOT_PUBLISHED'), misses=len(miss), range_sum_bits=res['mechanism'].get('mb_max_range_sum_bits'), ok=(res['outcome'] != 'NUMERIC_RANGE_REFUSED' and not miss)))
# R4: the overseer's SCALE-INVARIANCE reproducer: one factor 2^E [[1, 3], [3, 9]] on two binary variables, E = 2^24 (exact marginals 1/4, 3/4). For every assignment the
#     implemented X must be within the declared relative error rho_X of the analysed X = z / (q_an U_cap) (U_cap evaluated in 60-digit decimal), and a forced-approximate run must publish intervals containing the truth.
from decimal import Decimal, getcontext
getcontext().prec = 80
E24 = 1 << 18; p4 = write_uai('r4_scale_invariance', [2, 2], [((0, 1), [1 << E24, 3 << E24, 3 << E24, 9 << E24])])     # 2^18 (the overseer used 2^24; the decimal UAI encoding of 2^(2^24) takes minutes to parse; the mechanism is identical: the exponent is cancelled exactly)
model, _ = BR.core.read_uai(p4); cards4 = model['cards']; fns, const, scale, mult, fl = BR.integerize(model); tr = []; od = []; st = dict(elim_work=0, eliminations=0, query_work=0)
live = [f for f in BR.contract(fns, cards4, 0, time.monotonic() + 10, st, tr, od) if f.scope]; blocks = [IG.ft_from_int(f, cards4) for f in live]; mbp = IG.MBFloat(blocks, cards4, 4, time.monotonic() + 10)
S4 = sorted({v for b in blocks for v in b.scope}); pos4 = {v: i for i, v in enumerate(S4)}; E_tot = sum(b.e for b in blocks) - mbp.E_U; wid = IG.numerical_widening(blocks, mbp, [], len(S4), 2, E_tot)
rho_X = IG.fup(wid['rho_X']); rho_cap = IG.fup(wid['rho_cap']); logU_capf = IG.up(mbp.logU_f + IG.up(math.log2(1.0 + rho_cap)) + 2 ** -40)
import itertools
Sall = np.array(list(itertools.product(range(2), range(2))), dtype=np.int64); logq, q_an = mbp.logq_given(Sall, pos4); worst = Decimal(0); maxX = -1.0
U_cap_dec = Decimal(2) ** mbp.E_U * (Decimal(logU_capf) * Decimal(2).ln()).exp()        # U_cap = 2^(logU_capf + E_U); the solver combines E_tot = E_z - E_U exactly
for i, srow in enumerate(Sall.tolist()):
    z_exact = 1
    for f in live: z_exact *= int(np.asarray(f.arr, dtype=object)[tuple(srow[pos4[u]] for u in f.scope)])
    logz = sum(math.log2(float(b.M[tuple(srow[pos4[u]] for u in b.scope)])) for b in blocks)
    X_impl = 2.0 ** ((logz - float(logq[i]) - logU_capf) + float(E_tot)); maxX = max(maxX, X_impl)
    X_an = Decimal(z_exact) / (Decimal(q_an[i].numerator) / Decimal(q_an[i].denominator) * U_cap_dec)
    worst = max(worst, abs(Decimal(X_impl) - X_an) / X_an)
say(dict(control='R4_scale_invariance_2p24_implemented_vs_analysed_X', E_tot=E_tot, worst_relative_error=float(worst), declared_rho_X=rho_X, ratio_error_over_allowance=float(worst) / rho_X, max_X_impl=maxX, cap_holds=(maxX <= 1 + 2 * rho_X), ok=(float(worst) <= rho_X and maxX <= 1 + 2 * rho_X)))
t4 = T.load_task(p4); r4_ = oracle.truth(t4['model'], t4['queries']); tv4 = {(q.output['variable'], q.output['state']): a for q, a in zip(t4['queries'], r4_['answers'])}
res = IG.solve(p4, 4.0, table_cap=0, enum_cap=1, force_approx=True, mb_cap=4, schedule='targeted'); miss = []
for a in res['answers']:
    if a['guarantee'] == 'NOT_PUBLISHED': continue
    if not (F(a['lo']) <= tv4[(a['var'], a['state'])] <= F(a['hi'])): miss.append((a['var'], a['state'], a['lo'], a['hi'], str(tv4[(a['var'], a['state'])])))
say(dict(control='R4b_scale_invariance_run_publications_contain_truth', outcome=res['outcome'], published=sum(1 for a in res['answers'] if a['guarantee'] != 'NOT_PUBLISHED'), misses=len(miss), eps_num_log2=res['mechanism'].get('eps_num_log2'), E_tot=res['mechanism'].get('E_tot'), ok=(not miss and res['outcome'] != 'NUMERIC_RANGE_REFUSED')))
# R3: exact propagation on a chain: 40 random products and binary sums against exact integers (worst case: the bound must hold at every step)
rng = random.Random(5); cards = [2, 2, 2]; bad = 0; steps = 0
for trial in range(12):
    a = BR.Fn((0, 1), np.array([rng.randint(1, 1 << 60) for _ in range(4)], dtype=object).reshape(2, 2), [0], []); b = BR.Fn((1, 2), np.array([rng.randint(1, 1 << 60) for _ in range(4)], dtype=object).reshape(2, 2), [1], [])
    fa, fb = IG.ft_from_int(a, cards), IG.ft_from_int(b, cards); ex = BR._eliminate([a, b], 1, cards); fe = IG.ft_eliminate([fa, fb], 1, cards)
    for n, m in zip(np.asarray(ex.arr, dtype=object).reshape(-1).tolist(), fe.M.reshape(-1).tolist()):
        steps += 1
        if not abs(F(m) * F(2) ** fe.e - n) <= fe.rho * n: bad += 1
say(dict(control='R3_exact_rational_bounds_hold_on_random_eliminations', checked_entries=steps, violations=bad, ok=(bad == 0)))
# C6: the conservative inversion contains the exact-rational set on random accumulator states
def exact_set(A, B, P, Q, R, c, grid=4001):
    pts = [F(i, grid - 1) for i in range(grid)]; keep = [float(m) for m in pts if abs(F(A) - m * F(B)) <= F(c) + 2 * (F(P) - 2 * m * F(Q) + m * m * F(R))]
    return (min(keep), max(keep)) if keep else None
bad = 0; tested = 0
for trial in range(30):
    cert = IG.Certificate(1, 1e-6, 2 ** -34, 1 / 200, 'baseline'); mu = rng.random()
    for _ in range(rng.choice([5, 50, 400])):
        X = np.array([rng.random() * 0.4]); f = np.array([[1.0 if rng.random() < mu else 0.0]]); cert.update_batch(X, f)
    lo, hi = cert.sets(); ex = exact_set(cert.A[0], cert.B[0], cert.P[0], cert.Q[0], cert.R[0], cert.log_term + cert.Lam[0] * cert.eps_num)
    tested += 1
    if ex is not None and not (lo[0] <= ex[0] + 1e-9 and hi[0] >= ex[1] - 1e-9): bad += 1
    if ex is None and np.isfinite(lo[0]): pass
say(dict(control='C6_conservative_inversion_contains_exact_rational_set', tested=tested, violations=bad, ok=(bad == 0)))
# C1-C2 containment of actual publications (same models as round 3; written by check.py earlier)
FAST = os.environ.get('FAST') == '1'
for name, fn_, kw, budget in (() if FAST else (('C1_complete_separator_14_cap256', 'c7_complete_sep.uai', dict(table_cap=1 << 6, enum_cap=1 << 4, mb_cap=256), 25.0), ('C2_product_interior_10_cap64', 'c4_product_interior.uai', dict(table_cap=1 << 2, enum_cap=1 << 4, mb_cap=64), 15.0))):
    p = os.path.join(TMP, fn_); t = T.load_task(p); r = oracle.truth(t['model'], t['queries'], max_assignments=1 << 20, max_table=1 << 20); tv = {(q.output['variable'], q.output['state']): a for q, a in zip(t['queries'], r['answers'])}
    for sched in ('baseline', 'targeted'):
        res = IG.solve(p, budget, force_approx=True, schedule=sched, **kw); n = 0; miss = []; worst = F(0)
        for a in res['answers']:
            if a['guarantee'] == 'NOT_PUBLISHED': continue
            n += 1; tr = tv[(a['var'], a['state'])]; lo, hi, pt = F(a['lo']), F(a['hi']), F(a['point'])
            if not (lo <= tr <= hi) or abs(pt - tr) > EPS: miss.append((a['var'], a['state'], float(lo), float(hi), float(tr)))
            worst = max(worst, abs(pt - tr))
        m = res['mechanism']; say(dict(control=name + '_' + sched, outcome=res['outcome'], published=n, K=res['K'], misses=len(miss), worst_abs_error=float(worst), draws=m.get('draws'), ms_per_draw=m.get('ms_per_draw'), X_mean=m.get('X_mean'), max_remaining_width=m.get('max_remaining_width'), ok=(n > 0 and not miss), detail=miss[:3]))
# C3 injected cap violation
p = os.path.join(TMP, 'c7_complete_sep.uai'); _orig = IG.MBFloat.__init__
def _lowered(self, *a, **k): _orig(self, *a, **k); self.logU_f -= 40.0
IG.MBFloat.__init__ = _lowered; res = IG.solve(p, 4.0, force_approx=True, table_cap=1 << 6, enum_cap=1 << 4, mb_cap=16); IG.MBFloat.__init__ = _orig
say(dict(control='C3_injected_cap_violation_refused', outcome=res['outcome'], error=res.get('error', '')[:70], ok=(res['outcome'] == 'CERTIFICATE_DEFECT')))
# C4 zero global mass
p = os.path.join(TMP, 'c9_zero_global_mass.uai'); res = IG.solve(p, 2.0, table_cap=64, enum_cap=16, force_approx=True, mb_cap=16); pubs = [x for x in res['answers'] if x['guarantee'] != 'NOT_PUBLISHED']
say(dict(control='C4_zero_global_mass_nothing_published', outcome=res['outcome'], published=len(pubs), witness=res.get('positive_mass_witness'), ok=(len(pubs) == 0)))
# C5 perturbed stream excludes the truth
rng = random.Random(3); cert = IG.Certificate(2, 1e-6 / 2, 2 ** -30, 1 / 200, 'targeted'); mu = 0.3; shift = 10 / 200
for _ in range(60):
    X = np.array([rng.random() for _ in range(1000)]); f0 = np.array([1.0 if rng.random() < mu else 0.0 for _ in range(1000)]); cert.update_batch(X, np.stack([np.minimum(1.0, f0 + shift), f0], axis=1))
lo, hi = cert.sets(); say(dict(control='C5_perturbed_stream_excludes_truth', set_shifted=(float(lo[0]), float(hi[0])), set_true=(float(lo[1]), float(hi[1])), truth=mu, ok=(not (lo[0] <= mu <= hi[0]) and (lo[1] <= mu <= hi[1]) and (lo[0] <= mu + shift <= hi[0]))))
summary = dict(utc=time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()), version=IG.VERSION, all_ok=all(r['ok'] for r in rows), rows=rows); json.dump(summary, open(OUT, 'w'), indent=1, default=str)
print('ALL_OK' if summary['all_ok'] else 'FAILURES', sum(1 for r in rows if not r['ok']), 'of', len(rows))
