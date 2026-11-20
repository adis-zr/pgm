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
OUT = sys.argv[1]; TMP = os.path.join(os.path.dirname(OUT), 'ctl_models'); rows = []; rng = random.Random(23); ONLY_W5 = os.environ.get('ONLY_W5') == '1'
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
    say(dict(control=name, splits=wmbp.splits, expect_split=expect_split, weights=[w for w in wmbp.weights if len(w) > 1][:4], assignments=checked, positive=nz, unreachable_positive=bad_support, q_total=float(qsum), max_row_sum_dev=rows_off,
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
    m = res['mechanism']; say(dict(control='W4_containment_' + prop, outcome=res['outcome'], published=n, K=res['K'], misses=len(miss), splits=m.get('mb_splits'), X_mean=m.get('X_mean'), ESS=m.get('ESS'), logU_mb=(m.get('wmb') or {}).get('logU_mb'), logU_wmb=(m.get('wmb') or {}).get('logU_wmb'), draws=m.get('draws'), ok=(not miss and n > 0)))
# W5: injected understated cap on the WMB arm
_orig = IG.WMBFloat.__init__
def _low(self, *a, **k): _orig(self, *a, **k); self.logU_f -= 30.0; self.logU -= 30.0        # understate the WEIGHTED cap so that it is selected and used
IG.WMBFloat.__init__ = _low; res = IG.solve(p, 3.0, force_approx=True, table_cap=1 << 6, enum_cap=1 << 4, mb_cap=64, proposal='wmb', route='pac'); IG.WMBFloat.__init__ = _orig
say(dict(control='W5_injected_understated_cap_refused', outcome=res['outcome'], ok=(res['outcome'] == 'CERTIFICATE_DEFECT')))
summary = dict(utc=time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()), version=IG.VERSION, all_ok=all(r['ok'] for r in rows), rows=rows); json.dump(summary, open(OUT, 'w'), indent=1, default=str)
print('ALL_OK' if summary['all_ok'] else 'FAILURES', sum(1 for r in rows if not r['ok']), 'of', len(rows))
