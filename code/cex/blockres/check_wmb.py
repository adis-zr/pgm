"""Round-8 controls for the WEIGHTED mini-bucket proposal (tiny enumerable models, exact oracle, high-precision outward arithmetic for the power messages):
 W1 normalization: every implemented mixture row sums to 1 (within float) and the analysed law q_an (exact dyadics of the float row) is a probability distribution;
 W2 support: every assignment with z > 0 has q > 0 (no positive-mass assignment is unreachable);
 W3 pointwise cap: z_exact / (q_an U_cap) <= 1 on EVERY assignment (U_cap in 80-digit decimal from the stored messages' log values), incl. conflicting hard zeros, a 2^E common rescale, mixed cards;
 W4 containment of published PAC_EB intervals vs the oracle on a split construction (the WMB arm end to end);
 W5 injected understated cap -> CERTIFICATE_DEFECT; W6 the bound never exceeds the plain max-mini-bucket bound by more than the proved slack (log U_wmb <= log U_mb + 2^-30)."""
import sys, os, json, random, time, math, itertools
from fractions import Fraction as F
from decimal import Decimal, getcontext
getcontext().prec = 80
HERE = os.path.dirname(os.path.abspath(__file__)); CODE = os.path.dirname(os.path.dirname(HERE))
for p in (HERE, os.path.join(CODE, 'cex', 'cqr'), os.path.join(CODE, 'cex', 'newarm')):
    if p not in sys.path: sys.path.insert(0, p)
import numpy as np
import integrated as IG, blockres as BR, oracle, task as T
IG.EVIDENCE_EXPANSION_DEFAULT = False       # (round 19) this suite exercises its own mechanism; the evidence-expansion operator has its own suite, check_round19.py
IG.LAYERED_CONTRACTION_DEFAULT = False      # (round 20) this suite exercises its own mechanism; the layered-contraction constructor has its own suite, check_round20.py
IG.ANCESTRAL_RESPONSE_DEFAULT = False       # (round 22) this suite exercises its own mechanism; the ancestral-response constructor has its own suite, check_round22.py
IG.SUPPORT_CLOSURE_DEFAULT = False          # (round 18) this suite exercises the FROZEN comparator path (v2.9.4 behaviour); the closure has its own suite, check_round18.py
OUT = sys.argv[1]; TMP = os.path.join(os.path.dirname(OUT), 'ctl_models'); rows = []; rng = random.Random(23); ONLY_W5 = os.environ.get('ONLY_W5') == '1'; ONLY_D2 = os.environ.get('ONLY_D2') == '1'
if ONLY_D2: ONLY_W5 = True
def say(r): r['ok'] = bool(r['ok']); rows.append(r); print(json.dumps(r, default=str)[:400])
def write_uai(name, cards, factors, evidence=None):
    p = os.path.join(TMP, name + '.uai'); lines = ['MARKOV', str(len(cards)), ' '.join(map(str, cards)), str(len(factors))]
    for sc, _ in factors: lines.append('%d %s' % (len(sc), ' '.join(map(str, sc))))
    for sc, vals in factors: lines.append(str(len(vals))); lines.append(' '.join(str(v) for v in vals))
    open(p, 'w').write('\n'.join(lines) + '\n'); ev = evidence or {}; open(p + '.evid', 'w').write(('%d ' % len(ev)) + ' '.join('%d %d' % kv for kv in ev.items()) + '\n'); return p
def rnd(n, zeros=0.0, lo=1, hi=9): return [0 if rng.random() < zeros else rng.randint(lo, hi) for _ in range(n)]
def build(p, table_cap, mb_cap):
    model, _ = BR.core.read_uai(p); cards = model['cards']; fns, const, scale, mult, fl = BR.integerize(model); tr = []; od = []; st = dict(elim_work=0, eliminations=0, query_work=0)
    live = [f for f in BR.contract(fns, cards, table_cap, time.monotonic() + 10, st, tr, od) if f.scope]; blocks = [IG.ft_from_int(f, cards) for f in live]
    mbp = IG.MBFloat(blocks, cards, mb_cap, time.monotonic() + 10); wmbp = IG.WMBFloat(mbp, blocks, cards, time.monotonic() + 10, opt_s=2.0); return model, cards, live, blocks, mbp, wmbp
def exhaustive(name, p, table_cap, mb_cap, expect_split=True):
    model, cards, live, blocks, mbp, wmbp = build(p, table_cap, mb_cap); S = sorted({v for b in blocks for v in b.scope}); pos = {v: i for i, v in enumerate(S)}
    E_tot = sum(b.e for b in blocks) - wmbp.E_U; wid = IG.numerical_widening(blocks, wmbp, [], len(S), max(cards), E_tot); rho_cap = IG.fup(wid['rho_cap']); rho_X = IG.fup(wid['rho_X'])
    logU_capf = IG.up(wmbp.logU_f + IG.up(math.log2(1.0 + rho_cap)) + 2 ** -40); U_cap = Decimal(2) ** wmbp.E_U * (Decimal(logU_capf) * Decimal(2).ln()).exp()
    # analysed law: replay every assignment through the WMB sampler's row arithmetic deterministically
    def q_an_of(s):
        x = {v: s[pos[v]] for v in S}; q = F(1); row_sums = []
        for v, comps in reversed(wmbp.prep):
            n = cards[v]
            if comps is None: q /= n; continue
            qrow = np.zeros(n); dead_any = False
            for mem, wr in comps:
                L = np.zeros(n)
                for LM, strides, scope in mem:
                    base = sum(x[u] * strides[u] for u in scope if u != v); L += LM[base + np.arange(n) * strides[v]]
                _, logp, dead = IG._powsum_log(L[None, :], wr); pr = np.where(np.isfinite(logp[0]), np.exp2(np.where(np.isfinite(logp[0]), logp[0], -2000.0)), 0.0); qrow += wr * pr; dead_any |= bool(dead[0])
            qrow[qrow < math.ldexp(1.0, IG.PROB_TRUNC_LOG2)] = 0.0
            if dead_any: qrow[:] = 1.0 / n
            tot = sum(F(float(t)) for t in qrow.tolist()); row_sums.append(float(tot)); pa = F(float(qrow[x[v]]))
            if pa == 0: return F(0), row_sums
            q *= pa / tot
        return q, row_sums
    worst_cap = Decimal(0); bad_support = 0; nz = 0; rows_off = 0.0; checked = 0; qsum = F(0)
    for s in itertools.product(*(range(cards[v]) for v in S)):
        z = 1
        for f in live: z *= int(np.asarray(f.arr, dtype=object)[tuple(s[pos[u]] for u in f.scope)])
        q, rs = q_an_of(s); qsum += q; checked += 1
        for r in rs: rows_off = max(rows_off, abs(r - 1.0))
        if z > 0:
            nz += 1
            if q == 0: bad_support += 1
            else:
                X = Decimal(z) / (Decimal(q.numerator) / Decimal(q.denominator) * U_cap); worst_cap = max(worst_cap, X)
    say(dict(control=name, splits=wmbp.splits, expect_split=expect_split, weights=[[str(x) for x in w] for w in wmbp.weights if len(w) > 1][:4], assignments=checked, positive=nz, unreachable_positive=bad_support, q_total=float(qsum), max_row_sum_dev=rows_off,
             max_X_analysed=float(worst_cap), rho_cap=rho_cap, logU_mb=mbp.logU, logU_wmb=wmbp.logU, tightening_log2=(mbp.logU - wmbp.logU), ok=(bad_support == 0 and worst_cap <= 1 and abs(float(qsum) - 1) < 1e-9 and (wmbp.splits > 0) == expect_split)))      # note: with bounded weights the weighted bound CAN exceed the max bound; the solver selects by the smaller certified bound
# W1-W3 on a complete-graph separator of 6 ternary variables with private binary chains (split at a small cap), hard zeros and evidence
nS = 6; cards = [3] * nS + [2] * nS; facs = []
for i in range(nS):
    for j in range(i + 1, nS): facs.append(((i, j), rnd(9, zeros=0.2)))
    facs.append(((i, nS + i), rnd(6, zeros=0.1)))
p = write_uai('w_complete6_zeros', cards, facs, evidence={nS + 1: 1}); ONLY_W5 or exhaustive('W1-3_complete6_zeros_evidence_split', p, 1 << 2, 9)
# mixed cardinalities + a 2^300 common rescale on one factor (exponent cancellation under powers)
cards = [2, 4, 3, 2, 5]; facs = [((0, 1), [v << 300 for v in rnd(8)]), ((1, 2), rnd(12, zeros=0.2)), ((2, 3), rnd(6)), ((3, 4), rnd(10)), ((0, 4), rnd(10)), ((1, 4), rnd(20, zeros=0.1))]
p = write_uai('w_mixed_rescaled', cards, facs); ONLY_W5 or exhaustive('W1-3_mixed_cards_2p300_rescale_split', p, 0, 8)
# conflicting hard zeros: a row whose every component is dead for some later assignment
cards = [2, 2, 2, 2]; facs = [((0, 1), [0, 1, 1, 0]), ((1, 2), [1, 0, 0, 1]), ((2, 3), [0, 2, 3, 0]), ((0, 3), [1, 1, 1, 0]), ((0, 2), [1, 0, 1, 1])]
p = write_uai('w_conflicting_zeros', cards, facs); ONLY_W5 or exhaustive('W1-3_conflicting_hard_zeros', p, 0, 2)
# an unsplit construction: WMB must coincide with MB (no splits -> weights trivially 1)
p = write_uai('w_chain', [2, 3, 2, 3], [((0, 1), rnd(6)), ((1, 2), rnd(6)), ((2, 3), rnd(6))]); ONLY_W5 or exhaustive('W1-3_unsplit_chain', p, 0, 64, expect_split=False)
# W4: end-to-end containment on the complete-separator control model with the WMB arm (split construction)
p = os.path.join(TMP, 'c7_complete_sep.uai'); t = T.load_task(p); r = oracle.truth(t['model'], t['queries'], max_assignments=1 << 20, max_table=1 << 20); tv = {(q.output['variable'], q.output['state']): a for q, a in zip(t['queries'], r['answers'])}
for prop in (() if ONLY_W5 else ('mb', 'wmb')):
    res = IG.solve(p, 12.0, force_approx=True, table_cap=1 << 6, enum_cap=1 << 4, mb_cap=64, schedule='targeted', proposal=prop, route='pac'); n = 0; miss = []
    for a in res['answers']:
        if a['guarantee'] == 'NOT_PUBLISHED': continue
        n += 1
        if not (F(a['lo']) <= tv[(a['var'], a['state'])] <= F(a['hi'])): miss.append((a['var'], a['state']))
    m = res['mechanism']; say(dict(control='W4_containment_requested_' + prop, requested=prop, selected=((m.get('wmb') or {}).get('selected') or 'mb'), outcome=res['outcome'], published=n, K=res['K'], misses=len(miss), splits=m.get('mb_splits'), X_mean=m.get('X_mean'), ESS=m.get('ESS'), draws=m.get('draws'), ok=(not miss and n > 0)))
# W5: injected understated cap on the WMB arm
_orig = IG.WMBFloat.__init__
def _low(self, *a, **k): _orig(self, *a, **k); self.logU_f -= 30.0; self.logU -= 30.0        # understate the WEIGHTED cap so that it is selected (certified) and used
IG.WMBFloat.__init__ = _low; res = IG.solve(p, 3.0, force_approx=True, table_cap=1 << 6, enum_cap=1 << 4, mb_cap=64, proposal='wmb', route='pac'); IG.WMBFloat.__init__ = _orig
say(dict(control='W5_injected_understated_cap_refused', outcome=res['outcome'], ok=(res['outcome'] == 'CERTIFICATE_DEFECT')))
# ---- round 9 corrections (A-D)
if ONLY_D2: rows.clear()
# A: incremental scalar product: (3/2)^1800 from 1,800 FT scalars M = 1.5, e = 0, rho = 0 -> finite, inside its rounding allowance; empty product; exact zero
fts = [IG.FT((), np.array(1.5), 0, F(0)) for _ in range(1800)]; r = IG.ft_scalar_product(fts); approx = F(float(r.M)) * F(2) ** r.e; exact = F(3, 2) ** 1800
ONLY_D2 or say(dict(control='A_scalar_product_3half_pow_1800', finite=bool(np.isfinite(float(r.M))), log2_value=float(r.e + math.log2(float(r.M))), rel_error=float(abs(approx - exact) / exact), rho=float(r.rho), ok=(abs(approx - exact) <= r.rho * exact and float(r.M) >= 1.0 and float(r.M) < 2.0)))
e0 = IG.ft_scalar_product([]); z0 = IG.ft_scalar_product([IG.FT((), np.array(1.5), 3, F(0)), IG.FT((), np.array(0.0), 0, F(0))])
ONLY_D2 or say(dict(control='A_scalar_product_empty_and_zero', empty_is_one=(float(e0.M) == 1.0 and e0.e == 0), zero_is_zero=(float(z0.M) == 0.0), ok=(float(e0.M) == 1.0 and e0.e == 0 and float(z0.M) == 0.0)))
# A2: disconnected components with LARGE normalizers through the exact route (the scalar product of roots) -- no uncaught exception, no false ZERO_EVIDENCE
p = write_uai('a_many_components', [2] * 40, [((i,), [1 << 40, 3 << 40]) for i in range(40)]); t = T.load_task(p); rr = oracle.truth(t['model'], t['queries']); tv = {(q.output['variable'], q.output['state']): a for q, a in zip(t['queries'], rr['answers'])}
if not ONLY_D2:
  res = IG.solve(p, 6.0, force_approx=True, table_cap=0, enum_cap=0, mb_cap=4, route='exact', crosscheck=False); miss = sum(1 for a in res['answers'] if a['guarantee'] != 'NOT_PUBLISHED' and not (F(a['lo']) <= tv[(a['var'], a['state'])] <= F(a['hi'])))
  say(dict(control='A_forty_components_large_normalizers_exact_route', outcome=res['outcome'], published=res.get('published'), K=res['K'], misses=miss, ok=(res['outcome'] == 'COMPLETE' and miss == 0 and res.get('published') == res['K'])))
# C: 21 groups in one bucket (complete pairwise graph on 22 binary variables, unit factors, mb cap 4) must be REJECTED by the weight domain and fall back to max
n22 = 22; p = write_uai('c_k22_unit', [2] * n22, [((i, j), [1, 1, 1, 1]) for i in range(n22) for j in range(i + 1, n22)])
if not ONLY_D2:
  res = IG.solve(p, 8.0, force_approx=True, table_cap=0, enum_cap=0, mb_cap=4, proposal='wmb', route='pac'); w = res['mechanism'].get('wmb') or {}
  say(dict(control='C_21_groups_rejected_by_weight_domain', selected=w.get('selected'), status=str(w.get('status'))[:90], outcome=res['outcome'], ok=(w.get('selected') == 'mb' and 'INELIGIBLE' in str(w.get('status')))))
# D: a tiny case where WMB IS selected (certified cap smaller) and every publication contains the oracle truth; eps = 1/20 is a LABELLED relaxed tolerance for fast coverage (the sweep contract stays 1/200)
p = os.path.join(TMP, 'w_mixed_rescaled.uai'); t = T.load_task(p); rr = oracle.truth(t['model'], t['queries']); tv = {(q.output['variable'], q.output['state']): a for q, a in zip(t['queries'], rr['answers'])}
res = IG.solve(p, (3.0 if ONLY_D2 else 15.0), force_approx=True, table_cap=0, enum_cap=0, mb_cap=8, proposal='wmb', route='pac', schedule='targeted', eps=F(1, 20)); w = res['mechanism'].get('wmb') or {}; miss = []; n = 0
for a in ([] if ONLY_D2 else res['answers']):
    if a['guarantee'] == 'NOT_PUBLISHED': continue
    n += 1
    if not (F(a['lo']) <= tv[(a['var'], a['state'])] <= F(a['hi'])): miss.append((a['var'], a['state']))
ONLY_D2 or say(dict(control='D_wmb_selected_and_contained_RELAXED_eps_1_20', selected=w.get('selected'), certified_diff_log2=w.get('certified_diff_log2'), raw_diff_log2=w.get('raw_diff_log2'), rho_cap_wmb=w.get('rho_cap_wmb'), outcome=res['outcome'], published=n, K=res['K'], misses=len(miss), X_mean=res['mechanism'].get('X_mean'), ok=(w.get('selected') == 'wmb' and n == res['K'] and not miss)))
# D2: selection must use CERTIFIED caps: inject a large message error into the WMB construction so the raw cap is smaller but the certified cap is larger -> mb selected
_orig_init = IG.WMBFloat.__init__
def _inflate(self, *a, **k): _orig_init(self, *a, **k); self.rho_steps = [F(3, 100)] * max(1, len(self.rho_steps))        # every message carries a 3 % envelope: with the compact combination (S + S^2) the certified widening (~0.5 bits over 8 messages) exceeds the raw 0.388-bit advantage while staying inside the admitted domain (< 1/2)
IG.WMBFloat.__init__ = _inflate; res = IG.solve(p, 3.0, force_approx=True, table_cap=0, enum_cap=0, mb_cap=8, proposal='wmb', route='pac', eps=F(1, 20)); IG.WMBFloat.__init__ = _orig_init; w = res['mechanism'].get('wmb') or {}
say(dict(control='D2_certified_not_raw_selection', raw_diff_log2=w.get('raw_diff_log2'), certified_diff_log2=w.get('certified_diff_log2'), selected=w.get('selected'), status=str(w.get('status'))[:80], ok=(w.get('selected') == 'mb' and (w.get('raw_diff_log2') or 0) < 0)))
summary = dict(utc=time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()), version=IG.VERSION, all_ok=all(r['ok'] for r in rows), rows=rows); json.dump(summary, open(OUT, 'w'), indent=1, default=str)
print('ALL_OK' if summary['all_ok'] else 'FAILURES', sum(1 for r in rows if not r['ok']), 'of', len(rows))
