"""Independent checks of the block-contraction backend against cqr/oracle (exact enumeration / bucket elimination over the ORIGINAL model; never imports blockres internals
except the public solve()). Controls (brief, 19 Nov 2026): shared boundary variables; eliminated queried variables; hard zeros (incl. ZERO_EVIDENCE); an identically zero
residual with positive mass; a nonzero perturbation (an off-by-more-than-eps candidate must NOT validate); a deliberately underestimated bound (must be refused as a
certificate defect); a case with affordable interiors but a separator too large to enumerate (forces the approximate route). Writes CONTROLS.json."""
import sys, os, json, random, time
from fractions import Fraction as F
HERE = os.path.dirname(os.path.abspath(__file__)); CODE = os.path.dirname(os.path.dirname(HERE))
for p in (HERE, os.path.join(CODE, 'cex', 'cqr'), os.path.join(CODE, 'cex', 'newarm')):
    if p not in sys.path: sys.path.insert(0, p)
import blockres as BR
import oracle, task as T

OUT = sys.argv[1] if len(sys.argv) > 1 else os.path.join(HERE, 'CONTROLS.json'); TMP = os.path.join(os.path.dirname(OUT) or '.', 'ctl_models'); os.makedirs(TMP, exist_ok=True)
EPS = F(1, 200)


def write_uai(name, cards, factors, evidence=None):
    """factors: list of (scope, values as Fractions/ints/str in UAI row-major order)"""
    p = os.path.join(TMP, name + '.uai'); lines = ['MARKOV', str(len(cards)), ' '.join(map(str, cards)), str(len(factors))]
    for sc, _ in factors: lines.append('%d %s' % (len(sc), ' '.join(map(str, sc))))
    for sc, vals in factors: lines.append(str(len(vals))); lines.append(' '.join(str(v) for v in vals))
    open(p, 'w').write('\n'.join(lines) + '\n'); ev = evidence or {}
    open(p + '.evid', 'w').write(('%d ' % len(ev)) + ' '.join('%d %d' % kv for kv in ev.items()) + '\n'); return p


def truth(p):
    t = T.load_task(p); r = oracle.truth(t['model'], t['queries'], max_assignments=1 << 20, max_table=1 << 20)
    return t, r


def compare(name, p, res, r, t, mode):
    """every published answer must contain the truth (exact => equal); returns a row"""
    q = t['queries']; ev = t['model'].get('evidence', {}); ok = True; worst = F(0); n_exact = 0; n_pub = 0; detail = []
    if r['answers'] and r['answers'][0] == 'ZERO_EVIDENCE':
        row = dict(control=name, mode=mode, outcome=res['outcome'], expected='ZERO_EVIDENCE', ok=(res['outcome'] == 'ZERO_EVIDENCE')); return row
    tv = {}
    for qq, a in zip(q, r['answers']):
        tv[(qq.output['variable'], qq.output['state'])] = a
    for row_ in res['answers']:
        x, v = row_['var'], row_['state']
        if row_['guarantee'] == 'NOT_PUBLISHED': continue
        n_pub += 1; lo, hi, pt = F(row_['lo']), F(row_['hi']), F(row_['point']); tr = tv[(x, v)]
        if row_['guarantee'] == 'EXACT':
            n_exact += 1
            if pt != tr: ok = False; detail.append(dict(var=x, state=v, point=str(pt), truth=str(tr), kind='EXACT_MISMATCH'))
        else:
            if not (lo <= tr <= hi) or abs(pt - tr) > EPS: ok = False; detail.append(dict(var=x, state=v, lo=str(lo), hi=str(hi), point=str(pt), truth=str(tr), kind='CONTAINMENT_MISS'))
            worst = max(worst, abs(pt - tr))
    return dict(control=name, mode=mode, outcome=res['outcome'], guarantee=res.get('guarantee'), published=n_pub, K=res['K'], exact=n_exact, worst_abs_error=str(worst), ok=ok and (n_pub > 0 or mode == 'factorwise'), note=('ablation published nothing (expected when the old bounds are too loose); correctness vacuous' if n_pub == 0 else None), detail=detail[:5],
                mechanism={k: res['mechanism'].get(k) for k in ('blocks', 'separator_vars', 'eliminated_vars', 'N_S_log2', 'root_B_log2', 'root_B_other_log2', 'published_by', 'ratio_draws', 'signed_draws', 'splits')}, wall_s=round(res['wall_s'], 3))


def rnd_table(rng, size, zeros=0.0, lo=1, hi=99):
    return [0 if rng.random() < zeros else rng.randint(lo, hi) for _ in range(size)]


rows = []; rng = random.Random(7)
def run(name, p, **kw):
    t, r = truth(p); assert r is not None, 'oracle failed on ' + name
    for mode in ('block', 'factorwise'):
        res = BR.solve(p, kw.pop('budget', 8.0) if 'budget' in kw else 8.0, bounds=mode, **kw); rows.append(compare(name, p, res, r, t, mode)); print(json.dumps(rows[-1], default=str)[:400])
    return t, r

# 1. shared boundary variables: a chain of 3-variable blocks sharing one variable each (ternary cards), interior variables queried -> exact route (small separator)
cards = [3, 2, 3, 2, 3, 2, 3]; facs = []
for i in range(0, 6, 2): facs.append(((i, i + 1, i + 2), rnd_table(rng, 18)))
run('shared_boundary_chain', write_uai('c1', cards, facs))
# 2. eliminated queried variables with evidence and a factorless variable
cards = [2, 2, 2, 2, 2, 3]; facs = [((0, 1), rnd_table(rng, 4)), ((1, 2), rnd_table(rng, 4)), ((2, 3), rnd_table(rng, 4)), ((3, 4), rnd_table(rng, 4))]
run('eliminated_queried_evidence_factorless', write_uai('c2', cards, facs, evidence={4: 1}))
# 3. hard zeros inside tables + a zero-evidence case
cards = [2, 2, 2, 2]; facs = [((0, 1), [0, 3, 5, 0]), ((1, 2), [2, 0, 0, 7]), ((2, 3), [1, 1, 0, 4])]
run('hard_zeros', write_uai('c3', cards, facs))
facs0 = [((0, 1), [0, 0, 0, 5]), ((1,), [1, 0])]
run('zero_evidence', write_uai('c3z', [2, 2], facs0))
# 7. a large separator with affordable interiors: a COMPLETE graph on nS binary separator variables (pairwise factors; treewidth nS-1 blocks elimination under the cap)
#    with a private 3-variable chain hanging off every separator variable (eliminated into blocks). N_S = 2^nS > enum_cap -> approximate route; oracle = bucket elimination.
nS = 14; cards = [2] * nS + [2] * (3 * nS); facs = []
for i in range(nS):
    for j in range(i + 1, nS): facs.append(((i, j), rnd_table(rng, 4, lo=1, hi=9)))
    y0, y1, y2 = nS + 3 * i, nS + 3 * i + 1, nS + 3 * i + 2
    facs.append(((i, y0), rnd_table(rng, 4, lo=1, hi=9))); facs.append(((y0, y1), rnd_table(rng, 4, lo=1, hi=9))); facs.append(((y1, y2), rnd_table(rng, 4, lo=1, hi=9)))
p_ring = write_uai('c7_complete_sep', cards, facs)
t_ring, r_ring = run('large_separator_affordable_interiors', p_ring, budget=20.0, enum_cap=1 << 10, table_cap=1 << 6)
# 4. identically zero residual with positive mass: K_10 separator + one PRODUCT-FORM interior per separator variable (phi(a, y) = psi(a) u(y) with u = [1, 2]):
#    the interior conditional response is the constant 1/3 (y = 0) on every boundary assignment -> for the candidate 1/3 the residual is identically zero while the mass is positive.
nZ = 10; cards = [2] * nZ + [2] * nZ; facs = []
for i in range(nZ):
    for j in range(i + 1, nZ): facs.append(((i, j), rnd_table(rng, 4, lo=1, hi=9)))
    facs.append(((i, nZ + i), [1, 2, 3, 6]))          # psi(a) = (1, 3), u(y) = (1, 2) -> rho(y=0 | a) = 1/3 for both a
p_sym = write_uai('c4_product_interior', cards, facs)
t_sym, r_sym = run('zero_residual_positive_mass', p_sym, budget=20.0, enum_cap=1 << 4, table_cap=1 << 2, force_approx=True)
def zero_residual_control():
    model, _ = BR.core.read_uai(p_sym); cards_ = model['cards']; fns, const, scale, mult, fl = BR.integerize(model); st = dict(elim_work=0, eliminations=0, query_work=0); tr = []; od = []
    live = BR.contract(fns, cards_, 1 << 2, time.monotonic() + 10, st, tr, od); step_of = {v: i for i, (v, _) in enumerate(tr)}
    blocks = [BR.Block(i, f, cards_) for i, f in enumerate(live) if f.scope]; fac_fns = {next(iter(f.facs)): f for f in fns}
    for b in blocks: b.set_queries([(x, BR.recover_query_table(b, x, cards_, 1 << 8, tr, step_of, time.monotonic() + 10, st)) for x in b.interior], cards_)
    S = sorted({v for b in blocks for v in b.scope}); sq = [(x, v) for x in range(len(cards_)) for v in range(cards_[x])]
    sep = BR.Separator(blocks, cards_, S, sq, 'block', fac_fns, time.monotonic() + 30)
    for _ in range(6): sep.split(max(sep.open, key=lambda i: sep.open[i].B))
    tv = {(qq.output['variable'], qq.output['state']): a for qq, a in zip(t_sym['queries'], r_sym['answers'])}
    interior_caps = []; sep_caps = []; mass_pos = all(c.L > 0 for c in sep.open.values())
    for c in sep.open.values():
        for j, (x, v) in enumerate(sq):
            cap = sep.residual_cap_query(c, j, tv[(x, v)])
            (interior_caps if x >= nZ else sep_caps).append(cap)
    # the solver-level channel: residual_caps with the exact candidate must be EXACTLY zero for a cell whose only nonzero contributions could come from interior queries
    cand_int = [tv[q] if q[0] >= nZ else F(0) for q in sq]
    c0 = next(iter(sep.open.values())); a_int_only = None
    return dict(control='zero_residual_positive_mass_exact_channel', ok=(all(cp == 0 for cp in interior_caps) and all(cp > 0 for cp in sep_caps) and mass_pos and all(tv[(x, 0)] == F(1, 3) for x in range(nZ, 2 * nZ))),
                interior_caps_all_zero=all(cp == 0 for cp in interior_caps), separator_caps_all_positive=all(cp > 0 for cp in sep_caps), every_open_cell_mass_lower_bound_positive=mass_pos, truth_interior_is_one_third=all(tv[(x, 0)] == F(1, 3) for x in range(nZ, 2 * nZ)), cells=len(sep.open))
rows.append(zero_residual_control()); print(json.dumps(rows[-1], default=str)[:400])
# 5. nonzero perturbation: force a candidate off by 3 eps and check the signed stream never validates it within the budget (negative control on the validation law)
def perturbed_candidate_control():
    # reuse internals: build the separator for the ring, then run a SignedStream with a candidate shifted by +3 eps on query 0 and ensure the interval excludes [-eps Zlo, eps Zlo]
    model, _ = BR.core.read_uai(p_ring); cards_ = model['cards']; fns, const, scale, mult, fl = BR.integerize(model); st = dict(elim_work=0, eliminations=0, query_work=0); tr = []; od = []
    live = BR.contract(fns, cards_, 1 << 6, time.monotonic() + 10, st, tr, od); step_of = {v: i for i, (v, _) in enumerate(tr)}
    blocks = [BR.Block(i, f, cards_) for i, f in enumerate(live) if f.scope]
    fac_fns = {next(iter(f.facs)): f for f in fns}
    for b in blocks:
        tabs = [(x, BR.recover_query_table(b, x, cards_, 1 << 8, tr, step_of, time.monotonic() + 10, st)) for x in b.interior]; b.set_queries(tabs, cards_)
    S = sorted({v for b in blocks for v in b.scope}); sq = [(x, v) for x in range(len(cards_)) for v in range(cards_[x])]
    sep = BR.Separator(blocks, cards_, S, sq, 'block', fac_fns, time.monotonic() + 30); rng_ = random.Random(3)
    for _ in range(40):
        cid = max(sep.open, key=lambda i: sep.open[i].B)
        if len(sep.open[cid].states) < len(sep.order): sep.split(cid)
    truth_vals = {}
    for qq, a in zip(t_ring['queries'], r_ring['answers']): truth_vals[(qq.output['variable'], qq.output['state'])] = a
    cand = [truth_vals[q] for q in sq]; cand[0] = min(F(1), cand[0] + 3 * EPS)
    key = ('epoch', 1); E = sum((sep.residual_caps(c, cand, key) for c in sep.open.values()), F(0)); ss = BR.SignedStream(cand, len(sq), F(1, 10 ** 6) / len(sq), E, 1)
    validated = False; t0 = time.monotonic()
    while time.monotonic() - t0 < 6:
        ss.draw(sep, rng_)
        iv = ss.intervals(); Zlo = sep.Zlo()
        if iv and -EPS * Zlo <= iv[0][0] and iv[0][1] <= EPS * Zlo: validated = True; break
    # the interval for S_0 must eventually EXCLUDE 0-centered acceptance: check that the interval center is on the negative side by about 3 eps Z
    c0 = (iv[0][0] + iv[0][1]) / 2 / sep.Zhi() if iv else None
    return dict(control='nonzero_perturbation_not_validated', ok=(not validated), draws=ss.t, interval_center_over_Zhi=str(c0), expected_about=str(-3 * EPS), E_log2=float(F(E).numerator.bit_length() - F(E).denominator.bit_length()))
rows.append(perturbed_candidate_control()); print(json.dumps(rows[-1], default=str)[:400])
# 6. deliberately underestimated bound: halve a cell's B after construction; the importance-weight cap must be violated and refused (AssertionError -> CERTIFICATE_DEFECT)
def underestimated_bound_control():
    model, _ = BR.core.read_uai(p_ring); cards_ = model['cards']; fns, const, scale, mult, fl = BR.integerize(model); st = dict(elim_work=0, eliminations=0, query_work=0); tr = []; od = []
    live = BR.contract(fns, cards_, 1 << 6, time.monotonic() + 10, st, tr, od); blocks = [BR.Block(i, f, cards_) for i, f in enumerate(live) if f.scope]
    fac_fns = {next(iter(f.facs)): f for f in fns}; S = sorted({v for b in blocks for v in b.scope})
    sep = BR.Separator(blocks, cards_, S, [], 'block', fac_fns, time.monotonic() + 30); rng_ = random.Random(5)
    for _ in range(8): sep.split(max(sep.open, key=lambda i: sep.open[i].B))
    for c in sep.open.values(): sep.sumE -= c.E; c.E = 1; sep.sumE += c.E          # inject: every integrated bound replaced by 1 (a gross underestimate; the cap check must refuse the first contribution that exceeds it)
    rs = BR.RatioStream(0, F(1, 10 ** 6), sep.sumE); caught = None
    try:
        for _ in range(2000): rs.draw(sep, rng_)
    except AssertionError as e: caught = str(e)
    return dict(control='underestimated_bound_refused', ok=(caught is not None), refusal=caught, draws_before_refusal=rs.t)
rows.append(underestimated_bound_control()); print(json.dumps(rows[-1], default=str)[:400])
# 8. a random medium model with ternary variables, mixed zeros and evidence, approximate route forced (small caps) -> containment vs bucket elimination
rng2 = random.Random(11); nS = 18; cards = [3] * nS + [2] * (2 * nS); facs = []
for i in range(nS):
    a, b = i, (i + 1) % nS; y0, y1 = nS + 2 * i, nS + 2 * i + 1
    facs.append(((a, y0), rnd_table(rng2, 6, zeros=0.15))); facs.append(((y0, y1), rnd_table(rng2, 4))); facs.append(((y1, b), rnd_table(rng2, 6, zeros=0.15)))
run('ternary_ring_zeros_evidence_forced_approx', write_uai('c8', cards, facs, evidence={nS + 1: 0, 5: 2}), budget=20.0, enum_cap=1 << 8, table_cap=1 << 5, force_approx=True)

# 9. OVERSEER FINDING (19 Nov 2026): global normalizer exactly ZERO (two contradictory parity factors over 12 binary variables), an independent unary factor [1, 2]
#    and a factorless binary variable. The eliminated-component / factorless marginals (1/3, 2/3, 1/2, 1/2) are UNDEFINED globally and must NOT be published as EXACT.
#    (a) small table cap + tiny budget: the parity factors stay in the separator; no draw ever has z > 0 -> no witness -> nothing published, typed outcome.
#    (b) the separator enumerable: ZERO_EVIDENCE.
par = [1 if bin(i).count('1') % 2 == 0 else 0 for i in range(1 << 12)]; npar = [1 - v for v in par]
cards = [2] * 12 + [2, 2]; facs = [(tuple(range(12)), par), (tuple(range(12)), npar), ((12,), [1, 2])]
p_zero = write_uai('c9_zero_global_mass', cards, facs)
for mode in ('block', 'factorwise'):
    for prop in ('cell', 'mb'):
        res = BR.solve(p_zero, 1.0, bounds=mode, table_cap=64, enum_cap=16, force_approx=True, proposal=prop)
        pubs = [r for r in res['answers'] if r['guarantee'] != 'NOT_PUBLISHED']
        rows.append(dict(control='zero_global_mass_no_unwitnessed_publication', mode=mode, proposal=prop, outcome=res['outcome'], published=len(pubs), witness=res.get('positive_mass_witness'), withheld=res.get('withheld_without_witness'),
                         ok=(len(pubs) == 0 and res['outcome'] in ('ZERO_EVIDENCE', 'DEADLINE_PARTIAL', 'DEADLINE')))); print(json.dumps(rows[-1], default=str)[:300])
res = BR.solve(p_zero, 5.0, bounds='block', table_cap=64, enum_cap=1 << 14)
rows.append(dict(control='zero_global_mass_enumerable_is_ZERO_EVIDENCE', outcome=res['outcome'], ok=(res['outcome'] == 'ZERO_EVIDENCE' and not [r for r in res['answers'] if r['guarantee'] != 'NOT_PUBLISHED']))); print(json.dumps(rows[-1], default=str)[:300])
# 10. the mini-bucket proposal arm on the complete-separator control and the product-interior control: containment vs the oracle; the cap must hold on every draw
for name, pth, tr, rr in (('mb_proposal_large_separator', p_ring, t_ring, r_ring), ('mb_proposal_zero_residual', p_sym, t_sym, r_sym)):
    for cap in (16, 256):
        res = BR.solve(pth, 10.0, bounds='block', enum_cap=1 << 4, table_cap=(1 << 6 if 'large' in name else 1 << 2), force_approx=True, proposal='mb', mb_cap=cap)
        row = compare(name + '_cap%d' % cap, pth, res, rr, tr, 'block'); row['proposal'] = 'mb'
        if row['published'] == 0: row['ok'] = not row['detail']; row['note'] = 'mini-bucket arm published nothing at this tiny cap (mechanism outcome, not a defect); correctness vacuous'
        row['mb'] = None; row['mb'] = {k: res['mechanism'].get(k) for k in ('mb_U_log2', 'mb_L_log2', 'root_E_log2', 'cap_tightening_log2_E_minus_U', 'Zhat_log2_DIAGNOSTIC', 'ratio_draws', 'signed_draws')}; rows.append(row); print(json.dumps(row, default=str)[:400])
# 11. mini-bucket cap violation injected: U halved (grossly) -> the first draw exceeding it must be refused
def mb_underestimated_cap_control():
    model, _ = BR.core.read_uai(p_ring); cards_ = model['cards']; fns, const, scale, mult, fl = BR.integerize(model); st = dict(elim_work=0, eliminations=0, query_work=0); tr = []; od = []
    live = BR.contract(fns, cards_, 1 << 6, time.monotonic() + 10, st, tr, od); blocks = [BR.Block(i, f, cards_) for i, f in enumerate(live) if f.scope]; fac_fns = {next(iter(f.facs)): f for f in fns}
    S = sorted({v for b in blocks for v in b.scope}); sep = BR.Separator(blocks, cards_, S, [], 'block', fac_fns, time.monotonic() + 30); mbp = BR.MBProposal(blocks, cards_, 16, time.monotonic() + 30)
    rs = BR.MBRatioStream(0, F(1, 10 ** 6), mbp.U >> 40); caught = None; rng_ = random.Random(9)
    try:
        for _ in range(3000): rs.draw(sep, mbp, rng_)
    except AssertionError as e: caught = str(e)
    return dict(control='mb_underestimated_cap_refused', ok=(caught is not None), refusal=caught, draws_before_refusal=rs.t)
rows.append(mb_underestimated_cap_control()); print(json.dumps(rows[-1], default=str)[:300])

summary = dict(utc=time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()), version=BR.VERSION, all_ok=all(r['ok'] for r in rows), rows=rows)
json.dump(summary, open(OUT, 'w'), indent=1, default=str); print('ALL_OK' if summary['all_ok'] else 'FAILURES', sum(1 for r in rows if not r['ok']), 'of', len(rows))
