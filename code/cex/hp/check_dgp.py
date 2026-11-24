"""Qualification controls of DENSE_GENERIC_PAC_INTEGRATION_1 (brief section 7). usage: check_dgp.py OUT.json [--only D1,D2,..]. Every control asserts actual branch execution."""
import sys, os, json, time, math, argparse, traceback
from fractions import Fraction as F
HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, HERE); sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(HERE)), 'cex', 'newarm')); sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(HERE)), 'cex', 'blockres'))
import numpy as np
import integrated as IG, blockres as BR, core as CORE, coarse_envelope as CE, pac_actions as PA, lifted_decoder as LD
DEV = '/Users/adis/Workspace/pgm-records/code/runs/mdi_2026-10-28/DENSE_GENERIC_PAC_INTEGRATION_1/dev/inputs'
OPTS = dict(table_cap=1 << 18, enum_cap=1 << 16, mb_cap=1 << 24, batch=1024, schedule='targeted', crosscheck=True, exact_route=True)
EPS = F(1, 200); DELTA = F(1, 10 ** 6)
R = []
def rec(name, ok, **kw): R.append(dict(control=name, ok=bool(ok), **kw)); print(json.dumps(dict(control=name, ok=bool(ok), **{k: v for k, v in kw.items() if k != 'detail'}), default=str)[:400], flush=True)

def load(name): return CORE.read_uai(os.path.join(DEV, name + '.uai'))
MID = DEV.replace('/inputs', '/inputs_mid')
def load_mid(name): return CORE.read_uai(os.path.join(MID, name + '.uai'))

def run_stream(model, binding, seed, budget_s, delta_s, opts, n_batches=None, exact_route=True):
    st = PA.RequestState(model, binding, EPS, DELTA); t0 = PA.tnow(); deadline = t0 + budget_s
    status, rows, info = PA.structural_routes(st, deadline, flags=dict(evidence_expansion=False, layered_contraction=False, ancestral_response=False, support_closure=True))
    assert status == 'CONTINUE', status
    o = dict(opts, exact_route=exact_route); S = PA.Stream(1, 'original', st.model, st.queries, seed, EPS, delta_s, o)
    r = S.prepare(deadline, cdead=t0 + 0.5 * budget_s)
    while S.stage == 'READY' and (n_batches is None or S.batches < n_batches) and PA.tnow() < deadline:
        S.batch(deadline)
    return st, S

def D1_forced_pac_matches_accepted():
    """forced original-target PAC: the stream reaches the production sampler + Certificate; with the same seed / options / risk division its committed certificate state after the same number of batches equals the accepted engine's (same draws)"""
    name = 'dg_n12_c4_clique_two'; model, binding = load(name); path = os.path.join(DEV, name + '.uai')
    IG.SUPPORT_CLOSURE_DEFAULT = True
    out = IG.solve(path, 2.0, seed=7, route='pac', schedule='targeted', table_cap=OPTS['table_cap'], enum_cap=OPTS['enum_cap'], mb_cap=OPTS['mb_cap'], batch=OPTS['batch'], evidence_expansion=False, layered_contraction=False, ancestral_response=False)
    m = out['mechanism']; nb = m['draws'] // m['batch_used']; assert m['route'] == 'pac' and nb >= 2, (m.get('route'), nb)
    st, S = run_stream(model, binding, 7, 30.0, DELTA, OPTS, n_batches=nb, exact_route=False)
    w = S.check(); same_draws = S.draws == m['draws']; same_sumX = abs(S.sumX - m['sum_X']) <= 1e-12 * max(1.0, abs(m['sum_X'])); same_zero = S.zero_draws == m['zero_draws']
    acc_pub = out['mechanism']['published']; our_pub = len(S.pub)
    # the accepted run checks on a 0.5 s cadence and once at the end; our single check after nb batches must reproduce its final published set and widths from identical accumulators
    tr = out['trace'][-1]; same_width = abs(tr['max_remaining_width'] - S.max_unresolved_width()) <= 1e-9 if tr['remaining'] else S.all_published()
    rec('D1_forced_pac_matches_accepted', same_draws and same_sumX and same_zero and our_pub == acc_pub and same_width and S.witness == bool(out['positive_mass_witness']) and S.mech['alpha_per_coordinate'] == float(DELTA) / m['Kq'],
        accepted=dict(draws=m['draws'], sum_X=m['sum_X'], published=acc_pub, Kq=m['Kq'], batch_used=m['batch_used'], max_remaining=tr['max_remaining_width'], eps_num=m['eps_num'], rho_cap=m['rho_cap']), stream=dict(draws=S.draws, sum_X=S.sumX, published=our_pub, Kq=S.Kq, batch_used=S.batch_used, max_remaining=S.max_unresolved_width(), eps_num=S.eps_num, rho_cap=S.mech['rho_cap'], stage=S.stage, stages=[x['stage'] for x in S.measurements if x['kind'] == 'pac_stage']))

def D2_suspend_resume_between_batches():
    """yield at every batch boundary (deadline between batches) then resume: committed state equals uninterrupted execution with the same draws"""
    name = 'dg_n12_c4_clique_half'; model, binding = load(name)
    st, A = run_stream(model, binding, 3, 30.0, DELTA, OPTS, n_batches=6, exact_route=False)
    st2 = PA.RequestState(model, binding, EPS, DELTA); t0 = PA.tnow(); PA.structural_routes(st2, t0 + 30, flags=dict(evidence_expansion=False, layered_contraction=False, ancestral_response=False, support_closure=True))
    B = PA.Stream(1, 'original', st2.model, st2.queries, 3, EPS, DELTA, dict(OPTS, exact_route=False)); yields = 0
    # preparation yielded between stages: each prepare call gets a deadline that expires right away after one stage
    while B.stage != 'READY':
        r = B.prepare(t0 + 30, cdead=t0 + 15, until=PA.tnow() + 0.0005); yields += (r == 'YIELD')
        if r == 'CLOSED': break
    for k in range(6): r = B.batch(PA.tnow() + 30); assert r == 'COMMITTED', r; B.check() if k % 2 else None
    wA = A.check(); wB = B.check()
    rec('D2_suspend_resume_between_batches', B.stage == 'READY' and A.draws == B.draws and A.sumX == B.sumX and np.array_equal(A.cert.A, B.cert.A) and np.array_equal(A.cert.Q, B.cert.Q) and np.allclose(wA, wB, equal_nan=True) and yields >= 1, yields=yields, draws=(A.draws, B.draws), stagesB=[x['stage'] for x in B.measurements if x['kind'] == 'pac_stage'])

def D3_pending_batch_resumes_same_draws():
    """a yield INSIDE a batch (shared responses) retains the generated draws; the resumed batch commits the same draws (no fresh draws under the old certificate); an abandoned pending batch closes the stream"""
    name = 'dg_n12_c4_reg6_two'; model, binding = load(name); opts3 = dict(OPTS, table_cap=1 << 13)
    old = IG.RECOVERY_BYTE_BUDGET; IG.RECOVERY_BYTE_BUDGET = 0                      # force the SHARED response path (the dense budget is zero) on a model whose contraction leaves interior variables
    try:
        st, A = run_stream(model, binding, 11, 30.0, DELTA, opts3, n_batches=3, exact_route=False)
        assert A.shared_blocks > 0, 'fixture has no interior blocks (shared_blocks 0, Kq %d, sep %d)' % (A.Kq, len(A.sep_q))
        st2 = PA.RequestState(model, binding, EPS, DELTA); t0 = PA.tnow(); PA.structural_routes(st2, t0 + 30, flags=dict(evidence_expansion=False, layered_contraction=False, ancestral_response=False, support_closure=True))
        B = PA.Stream(1, 'original', st2.model, st2.queries, 11, EPS, DELTA, dict(opts3, exact_route=False)); B.prepare(t0 + 30, cdead=t0 + 15); assert B.stage == 'READY', (B.stage, B.closed_reason)
        for k in range(2): assert B.batch(PA.tnow() + 30) == 'COMMITTED'
        r = B.batch(PA.tnow() - 1.0)                                  # deadline already passed when the shared block is reached -> PENDING (draws retained)
        pend = r == 'PENDING' and B.pending is not None; Sb_pending = B.pending['Sb'].copy() if pend else None
        r2 = B.batch(PA.tnow() + 30); committed = r2 == 'COMMITTED' and B.batches == 3
        same = pend and committed and A.draws == B.draws and A.sumX == B.sumX and np.array_equal(A.cert.A, B.cert.A)
        # abandon path: a new pending batch, then abandon -> CLOSED, committed prefix intact
        r3 = B.batch(PA.tnow() - 1.0); B.abandon('control'); closed = B.stage == 'CLOSED' and B.batches == 3 and B.draws == A.draws
        rec('D3_pending_batch_resumes_same_draws', same and closed and (B.shared_blocks > 0), pending=pend, resumed=committed, closed=closed, shared_blocks=B.shared_blocks, draws=(A.draws, B.draws), r3=r3)
    finally: IG.RECOVERY_BYTE_BUDGET = old

def D4_exact_route_in_stream():
    """an unsplit construction takes the accepted exact reverse route inside the stream (deterministic rows, zero risk) and matches the accepted engine's rows"""
    name = 'dg_n12_c2_clique_two'; model, binding = load(name); path = os.path.join(DEV, name + '.uai')
    out = IG.solve(path, 5.0, seed=1, route='auto', schedule='targeted', table_cap=1 << 6, enum_cap=1 << 4, mb_cap=1 << 24, batch=1024, evidence_expansion=False, layered_contraction=False, ancestral_response=False)
    st = PA.RequestState(model, binding, EPS, DELTA); t0 = PA.tnow(); PA.structural_routes(st, t0 + 30, flags=dict(evidence_expansion=False, layered_contraction=False, ancestral_response=False, support_closure=True))
    S = PA.Stream(1, 'original', st.model, st.queries, 1, EPS, DELTA, dict(OPTS, table_cap=1 << 6, enum_cap=1 << 4)); S.prepare(t0 + 30, cdead=t0 + 15)
    rows_acc = {(r['var'], r['state']): (r['lo'], r['hi']) for r in out['answers'] if r['guarantee'] != 'NOT_PUBLISHED'}
    rows_s = {q: (str(S.ans[j]['lo']), str(S.ans[j]['hi'])) for q, j in S.qix.items() if j in S.ans}
    rec('D4_exact_route_in_stream', out['mechanism'].get('route') == 'exact' and S.stage == 'COMPLETE' and S.mech.get('terminal') == 'EXACT_ROUTE' and rows_acc == rows_s and len(rows_s) == S.K, accepted_route=out['mechanism'].get('route'), terminal=S.mech.get('terminal'), rows=len(rows_s), K=S.K, crosscheck=(S.mech.get('exact_route') or {}).get('crosscheck', {}).get('status'))

CONTROLS = [D1_forced_pac_matches_accepted, D2_suspend_resume_between_batches, D3_pending_batch_resumes_same_draws, D4_exact_route_in_stream]




# ---------------------------------------------------------------- lifted route, numerics, streams, edge cases, expiry
import itertools, random
from unified_pac_planner import UPlanner, PAC_OPTS, SLICE_S
import unified_pac_planner as UPP
import unified_planner as UP
from unified_planner import Refused, Defect, CM

def enum_marginals(M):
    """exact original-coordinate marginals of a canonical model by enumeration (<= 2^16 states)"""
    n = len(M.cards); assert math.prod(M.cards) <= 1 << 16; Z = F(0); num = {}
    for z in itertools.product(*[range(k) for k in M.cards]):
        W = LD.parent_weight(M, z); Z += W
        for v, a in enumerate(z): num[(v, a)] = num.get((v, a), F(0)) + W
    return Z, {k: v / Z for k, v in num.items()}

def fast_stage(M, clk, B):
    prof, why = CE.slice_profiles(M, clk, B); assert prof is not None, why
    classes = [CE.canonical_classes(CE.farthest_split(prof[v], list(range(M.cards[v])), clk), M.cards[v]) for v in range(len(M.cards))]; return classes, CE.check_candidate(M, classes, CE.unit_scales(M), clk, B)

def duplicate_states(model, seed=5):
    """exact-copy lift: every state a of card d becomes (a, k), k in {0, 1}, with per-state positive scales on every incident axis and unary -> the exact profile quotient recovers the pairs"""
    rng = random.Random(seed); cards = model['cards']; n = len(cards); facs = []
    sc_v = {v: [F(rng.randrange(1, 9), 4) for _ in range(2 * cards[v])] for v in range(n)}
    for f in model['factors']:
        sc = tuple(f['scope'])
        if len(sc) == 1: v = sc[0]; facs.append(dict(scope=sc, values=[f['values'][a // 2] * sc_v[v][a] for a in range(2 * cards[v])])); continue
        u, v = sc; vals = []
        for a in range(2 * cards[u]):
            for b in range(2 * cards[v]): vals.append(f['values'][(a // 2) * cards[v] + (b // 2)] * sc_v[u][a] * sc_v[v][b])
        facs.append(dict(scope=sc, values=vals))
    return dict(cards=[2 * c for c in cards], factors=facs, evidence={})

def D5_lifted_enumeration_identity_parent():
    """lifted route on an identity parent with NONUNIFORM decoders: decoder support / normalization, pointwise W <= G_U d, d / r <= kappa, X <= 1 on the analyzed law for EVERY state, response identity E_q[X (g_j - mu_j)] = 0 exactly"""
    model, binding = load('dg_n8_c4_clique_two'); clk = CE.Clock(time.monotonic() + 60, {}); B = CE.Budget(CE.CONSTRUCTOR_BYTES); M = CE.canonicalize(model, clk, B); classes, Cz = fast_stage(M, clk, B)
    S = PA.LiftedStream(1, M, M, [], classes, Cz, 3, EPS, DELTA / 2, dict(PAC_OPTS)); r = S.prepare(time.monotonic() + 60); assert r == 'READY', (r, S.closed_reason)
    chk = LD.enumerate_check(M, classes, Cz, S.rows); nonuniform = any(len(set(S.rows.counts[k])) > 1 for k in S.rows.counts)
    # analyzed law over EVERY state: q(z) = q_an(c) r(z|c) with q_an from the accepted sampler's exact replay (logq_given); X_an = W(z) / (cap_total q(z)) must be <= 1; the estimating equation sums to zero exactly
    Z, mu = enum_marginals(M); n = len(M.cards); cap_exact = None; worst = F(0); eq = {k: F(0) for k in mu}; tot_q = F(0)
    coarse_states = list(itertools.product(*[range(k) for k in Cz.ccards])); Sb = np.array(coarse_states, dtype=np.int64); logq, q_an = S.mbp.logq_given(Sb, S.pos)
    cap_total = F(2) ** 0  # cap_total_exact = 2^(logU_capf) x 2^(-E_tot) in the float domain; the exact analyzed cap = (B_C scale ratio) x kappa; both bound W/q: test the certified float cap directly
    capf = F(2) ** F(S.logU_capf).limit_denominator(1 << 40) if False else None
    for ci, c in enumerate(coarse_states):
        qc = q_an[ci]
        if qc == 0: continue
        for zs in itertools.product(*[S.rows.members[v][c[v]] for v in range(n)]):
            z = tuple(zs); W = LD.parent_weight(M, z) / M.scalar; r_ = F(1)
            for v in range(n): r_ *= LD.r_prob(S.rows, v, c[v], z[v])
            q = qc * r_; tot_q += q
            # implemented float cap: 2^(logU_capf - E_tot) in units of W_int = scale_F x W'  => X_an = scale_F W / (2^(logU_capf - E_tot) q); use the float cap as an exact dyadic upper bound via Fraction(float)
            Xan = F(S.scale_F) * W / q / (F(2.0 ** (S.logU_capf - int(S.logU_capf))) * F(2) ** (int(S.logU_capf) + S.mbp.E_U))          # the certified cap 2^logU_capf x 2^E_U in units of W_int = scale_F W'
            if Xan > worst: worst = Xan
            for v, a in enumerate(z): eq[(v, a)] += q * Xan * (1 - mu[(v, a)])
            for v in range(n):
                for a in range(M.cards[v]):
                    if a != z[v]: eq[(v, a)] += q * Xan * (0 - mu[(v, a)])
    eq_zero = all(abs(x) < F(1, 10 ** 30) for x in eq.values()); mass_one = abs(tot_q - 1) < F(1, 10 ** 12)
    rec('D5_lifted_enumeration_identity_parent', worst <= 1 and eq_zero and nonuniform and chk['zero_weight_states'] == 0 and mass_one, max_X_analyzed=float(worst), estimating_equation_max_abs=float(max(abs(x) for x in eq.values())), nonuniform_decoder=nonuniform, kappa=chk['kappa_float'], ccards=Cz.ccards, states=chk['states'], total_q=float(tot_q))

def D6_lifted_enumeration_exact_then_approx():
    """a TRUE exact-then-approximate composition: card-8 model with exact state copies -> exact quotient parent (card 4) -> FAST approximate stage on the parent; enumeration over EVERY parent state of the analyzed law:
    X_an <= 1, total proposal mass 1, and the ORIGINAL response identity E_q[X (g_j - mu_j)] = 0 with g_j = the exact decoder value d_par(a | z_v) and mu_j the ORIGINAL marginal (enumerated on the fine model); then a few committed batches: witness + containment of any certified row"""
    import dense_gen as DG
    base, _ = DG.build(DG.TAG_DEV, 5, 4, 'clique', F(1, 4)); model = duplicate_states(base); clk = CE.Clock(time.monotonic() + 60, {}); B = CE.Budget(CE.CONSTRUCTOR_BYTES); M = CE.canonicalize(model, clk, B)
    classes1 = CE.exact_profile_classes(M, clk, B); Cz1 = CE.check_candidate(M, classes1, CE.exact_scales(M, classes1, clk), clk, B); assert Cz1.exact and list(Cz1.ccards) == [4] * 5, (Cz1.exact, Cz1.ccards)
    M1 = CE.stage_model(M, Cz1); classes2, Cz2 = fast_stage(M1, clk, B); assert not Cz2.exact
    S = PA.LiftedStream(2, M, M1, [(classes1, Cz1)], classes2, Cz2, 9, EPS, DELTA / 4, dict(PAC_OPTS)); r = S.prepare(time.monotonic() + 60); assert r == 'READY', (r, S.closed_reason)
    nontrivial = any(0 < float(x) < 1 for Dm in S.Dm for x in Dm.reshape(-1)); assert S.resp_rel > 0 and nontrivial, 'exact decoder responses must be nontrivial'
    Z, mu = enum_marginals(M); n = len(M1.cards); worst = F(0); tot_q = F(0); eq = {k: F(0) for k in mu}
    coarse_states = list(itertools.product(*[range(k) for k in Cz2.ccards])); Sb = np.array(coarse_states, dtype=np.int64); logq, q_an = S.mbp.logq_given(Sb, S.pos)
    for ci, c in enumerate(coarse_states):
        qc = q_an[ci]
        if qc == 0: continue
        for z in itertools.product(*[S.rows.members[v][c[v]] for v in range(n)]):
            W = LD.parent_weight(M1, z) / M1.scalar * (M.scalar / M1.scalar) if False else LD.parent_weight(M1, z) / M1.scalar; r_ = F(1)
            for v in range(n): r_ *= LD.r_prob(S.rows, v, c[v], z[v])
            q = qc * r_; tot_q += q; Xan = F(S.scale_F) * W / q / (F(2.0 ** (S.logU_capf - int(S.logU_capf))) * F(2) ** (int(S.logU_capf) + S.mbp.E_U))
            if Xan > worst: worst = Xan
            for v in range(n):
                for a in range(M.cards[v]):
                    c_, d_ = CE.compose_decoder([(classes1, Cz1)], v, a); g = d_ if c_ == z[v] else F(0)                    # the EXACT decoder response; the implemented float response float(d) deviates by <= u d (covered by resp_rel in rho_f)
                    eq[(v, a)] += q * Xan * (g - mu[(v, a)])
    float_resp_ok = all(abs(F(S.Dm[v][CE.compose_decoder([(classes1, Cz1)], v, a)[0], a]) - CE.compose_decoder([(classes1, Cz1)], v, a)[1]) <= IG.UF * CE.compose_decoder([(classes1, Cz1)], v, a)[1] for v in range(n) for a in range(M.cards[v]))
    eq_ok = all(abs(x) < F(1, 10 ** 28) for x in eq.values()) and float_resp_ok; mass_one = abs(tot_q - 1) < F(1, 10 ** 12)
    t0 = time.monotonic()
    while time.monotonic() - t0 < 3 and not S.all_published():
        S.batch(time.monotonic() + 60)
        if S.batches % 50 == 0: S.check()
    S.check(); rows = S.pac_rows(); viol = sum(1 for j, (L, H) in rows.items() if not (L <= mu[S.queries[j]] <= H)); chk = LD.enumerate_check(M1, classes2, Cz2, S.rows)
    rec('D6_lifted_enumeration_exact_then_approx', worst <= 1 and eq_ok and mass_one and nontrivial and S.witness and viol == 0 and chk['zero_weight_states'] == 0, max_X_analyzed=float(worst), estimating_equation_max_abs=float(max(abs(x) for x in eq.values())), total_q=float(tot_q), published=len(rows), K=S.Kq, violations=viol, X_mean=S.sumX / max(1, S.draws), draws=S.draws, parent_cards=list(M1.cards), coarse_cards=list(Cz2.ccards), decoder_stages=len(S.par_stages), kappa=chk['kappa_float'])

def D7_zero_lower_positive_upper_witness():
    """a candidate whose lower envelope mass is ZERO while the upper and the original masses are positive: the deterministic lower solve is a no-witness state (Solve.zero); the lifted proposal on the upper model has support and obtains a GENUINE positive original-weight witness; certified rows contain the oracle"""
    model = dict(cards=[2, 2, 2], factors=[dict(scope=(0, 1), values=[F(3), F(0), F(0), F(2)]), dict(scope=(1, 2), values=[F(1), F(2), F(2), F(1)]), dict(scope=(0,), values=[F(1), F(1)]), dict(scope=(1,), values=[F(1), F(2)]), dict(scope=(2,), values=[F(1), F(1)])], evidence={})
    clk = CE.Clock(time.monotonic() + 60, {}); B = CE.Budget(CE.CONSTRUCTOR_BYTES); M = CE.canonicalize(model, clk, B); classes = [[0, 0], [0, 0], [0, 1]]; Cz = CE.check_candidate(M, classes, CE.unit_scales(M), clk, B)
    assert Cz.mixed and Cz.R is None
    SL = CE.run_executor(CE.coarse_model(M, Cz, 0), [0, 1, 2], M.scalar, time.monotonic() + 30, {}, 'lower'); SU = CE.run_executor(CE.coarse_model(M, Cz, 1), [0, 1, 2], M.scalar, time.monotonic() + 30, {}, 'upper')
    S = PA.LiftedStream(1, M, M, [], classes, Cz, 1, EPS, DELTA / 2, dict(PAC_OPTS)); r = S.prepare(time.monotonic() + 60); assert r == 'READY', (r, S.closed_reason)
    Z, mu = enum_marginals(M); t0 = time.monotonic()
    while time.monotonic() - t0 < 6 and not S.all_published():
        S.batch(time.monotonic() + 60)
        if S.batches % 20 == 0: S.check()
    S.check(); rows = S.pac_rows(); viol = sum(1 for j, (L, H) in rows.items() if not (L <= mu[S.queries[j]] <= H)); zf = S.zero_draws / max(1, S.draws)
    rec('D7_zero_lower_positive_upper_witness', SL.zero and not SU.zero and Z > 0 and S.witness and 0.1 < zf < 0.9 and len(rows) == S.Kq and viol == 0, lower_zero=SL.zero, upper_zero=SU.zero, Z=str(Z), witness=S.witness, zero_weight_fraction=zf, published=len(rows), violations=viol, draws=S.draws)

def D8_surrogate_mutant_fails_oracle():
    """a coarse surrogate whose marginal differs from the original by more than epsilon: the production lifted estimator's certified rows contain the ORIGINAL marginals; the mutant weighting by the surrogate G_U(c) d(z|c) (controls-only hook) certifies rows that EXCLUDE the original marginal"""
    rng = random.Random(21); n = 4; card = 4
    def table(strength): return [F(round(math.exp(strength * rng.uniform(-1, 1)) * 2 ** 20), 2 ** 20) for _ in range(card * card)]
    found = None
    for strength in (F(3, 2), F(2), F(5, 2), F(3)):
        rng = random.Random(21); model = dict(cards=[card] * n, factors=[dict(scope=(i, (i + 1) % n), values=table(strength)) for i in range(n)] + [dict(scope=(v,), values=[F(1) + F(rng.randrange(0, 5), 8) for _ in range(card)]) for v in range(n)], evidence={})
        clk = CE.Clock(time.monotonic() + 60, {}); B = CE.Budget(CE.CONSTRUCTOR_BYTES); M = CE.canonicalize(model, clk, B); classes = [[0, 0, 1, 1]] * n; Cz = CE.check_candidate(M, classes, CE.unit_scales(M), clk, B)
        Z, mu = enum_marginals(M)
        # the surrogate marginal: upper model normalized, decoded by d
        cm = CE.coarse_model(M, Cz, 1); ZU = F(0); nu = {}
        for c in itertools.product(*[range(k) for k in Cz.ccards]):
            w = M.scalar
            for v in range(n): w *= Cz.A[v][c[v]]
            for fi, (sc, _) in enumerate(M.factors):
                idx = 0
                for x in sc: idx = idx * Cz.ccards[x] + c[x]
                w *= Cz.U[fi][idx]
            ZU += w
            for v in range(n):
                for a in range(card):
                    if classes[v][a] == c[v]: nu[(v, a)] = nu.get((v, a), F(0)) + w * Cz.d[v][a]
        diff = max(abs(nu[k] / ZU - mu[k]) for k in mu)
        if diff > 2 * EPS: found = (strength, M, classes, Cz, mu, diff); break
    assert found, 'no surrogate with a marginal gap > 2 eps among the tried strengths'
    strength, M, classes, Cz, mu, diff = found
    def run(mutant):
        S = PA.LiftedStream(1, M, M, [], classes, Cz, 4, EPS, DELTA / 2, dict(PAC_OPTS)); S.mutant_surrogate = mutant; r = S.prepare(time.monotonic() + 60); assert r == 'READY', (r, S.closed_reason); t0 = time.monotonic()
        while time.monotonic() - t0 < 10 and not S.all_published():
            S.batch(time.monotonic() + 60)
            if S.batches % 40 == 0: S.check()
        S.check(); rows = S.pac_rows(); return S, rows, sum(1 for j, (L, H) in rows.items() if not (L <= mu[S.queries[j]] <= H))
    S0, rows0, v0 = run(False); S1, rows1, v1 = run(True)
    rec('D8_surrogate_mutant_fails_oracle', diff > 2 * EPS and len(rows0) > 0 and v0 == 0 and len(rows1) > 0 and v1 > 0, surrogate_gap=float(diff), strength=str(strength), production=dict(published=len(rows0), K=S0.Kq, violations=v0, X_mean=S0.sumX / max(1, S0.draws), draws=S0.draws), mutant=dict(published=len(rows1), violations=v1, X_mean=S1.sumX / max(1, S1.draws), draws=S1.draws))

def D9_numerical_bound_operation_by_operation():
    """the lifted widening on a tiny exact-rational example: (i) every implemented log2 X lies within eps_num-scale of the exact analyzed log2 X on every state (the bound d_total holds); (ii) each part is >= the directly recomputed operation count bound; (iii) a deliberately UNDERSTATED cap makes the cap assertion fire (certificate defect), it never publishes; (iv) an underflow-prone fine table (entries near 2^-1000) is refused typed by ft_from_int / RANGE before any sample"""
    model, binding = load('dg_n8_c2_er50_eighth'); clk = CE.Clock(time.monotonic() + 60, {}); B = CE.Budget(CE.CONSTRUCTOR_BYTES); M = CE.canonicalize(model, clk, B); classes = [[0, 0]] * len(M.cards); Cz = CE.check_candidate(M, classes, CE.unit_scales(M), clk, B)
    S = PA.LiftedStream(1, M, M, [], classes, Cz, 2, EPS, DELTA / 2, dict(PAC_OPTS)); assert S.prepare(time.monotonic() + 60) == 'READY'
    n = len(M.cards); worst_dev = 0.0; Xmax_exact = F(0)
    Sb = np.zeros((1, n), dtype=np.int64); logq, q_an = S.mbp.logq_given(Sb, S.pos); qc = q_an[0]              # one coarse state (all variables merged into one class)
    cap_exact_num = F(2) ** (int(S.logU_capf)) * F(2.0 ** (S.logU_capf - int(S.logU_capf))) * F(2) ** (S.mbp.E_U)   # the certified float cap as an exact dyadic (coarse cap exponent E_U)
    for z in itertools.product(*[range(k) for k in M.cards]):
        W = LD.parent_weight(M, z) / M.scalar; r_ = F(1)
        for v in range(n): r_ *= LD.r_prob(S.rows, v, 0, z[v])
        Xan = F(S.scale_F) * W / (qc * r_) / cap_exact_num; Xmax_exact = max(Xmax_exact, Xan)
        zz = np.array([z], dtype=np.int64); logz = 0.0
        for i in range(len(S.fine)): logz += float(S.fLM[i][S._flat_fine(zz, i)][0])
        logr = sum(math.log2(S.rows.counts[(v, 0)][S.rows.members[v][0].index(z[v])]) - LD.Q_BITS for v in range(n)); logX_impl = (logz - float(logq[0]) - logr - S.logU_capf) + float(S.E_tot)
        dev = abs(logX_impl - math.log2(float(Xan))); worst_dev = max(worst_dev, dev)
    wid = S.mech['widening']; parts = S.mech['widening_parts']; bound_ok = worst_dev <= float(wid['delta_log_total']) + 1e-12
    # (ii) direct recomputation of two parts
    u = IG.UF; d_r_direct = n * u * (LD.Q_BITS + 1) + u * n * (n * LD.Q_BITS + n); d_zf_direct = sum(u * (b.R + 1) for b in S.fine) + u * len(S.fine) * (sum(b.R for b in S.fine) + len(S.fine))
    parts_ok = abs(parts['d_r'] - float(d_r_direct)) <= 1e-30 and abs(parts['d_zf'] - float(d_zf_direct)) <= 1e-30
    # (iii) understated cap -> the assertion fires
    S2 = PA.LiftedStream(1, M, M, [], classes, Cz, 2, EPS, DELTA / 2, dict(PAC_OPTS)); assert S2.prepare(time.monotonic() + 60) == 'READY'; S2.logU_capf -= 3.0; fired = False
    try: S2.batch(time.monotonic() + 60)
    except AssertionError as e: fired = 'certificate defect' in str(e)
    # (iv) underflow-prone fine table: entries spanning more than RANGE_BITS -> typed refusal before any sample
    bad = dict(cards=[2, 2], factors=[dict(scope=(0, 1), values=[F(1), F(1, 2 ** 1200), F(1), F(1)]), dict(scope=(0,), values=[F(1), F(1)]), dict(scope=(1,), values=[F(1), F(1)])], evidence={}); Mb = CE.canonicalize(bad, clk, B); Czb = CE.check_candidate(Mb, [[0, 0], [0, 0]], CE.unit_scales(Mb), clk, B)
    S3 = PA.LiftedStream(1, Mb, Mb, [], [[0, 0], [0, 0]], Czb, 2, EPS, DELTA / 2, dict(PAC_OPTS)); r3 = S3.prepare(time.monotonic() + 60); typed = r3 == 'CLOSED' and S3.draws == 0 and ('RANGE' in str(S3.closed_reason) or 'REFUSED' in str(S3.closed_reason))
    rec('D9_numerical_bound_operation_by_operation', bound_ok and parts_ok and fired and typed and Xmax_exact <= 1, worst_log2_deviation=worst_dev, delta_log_total=wid['delta_log_total'], eps_num=S.eps_num, max_X_exact=float(Xmax_exact), parts=parts, understated_cap_fired=fired, underflow_typed=typed, underflow_reason=str(S3.closed_reason)[:120])

def D10_three_streams_risk_and_conflicts():
    """three adaptively selected streams on one request: delta/2, delta/4, delta/8 allocated BEFORE the first draw, alpha = delta_s / K_s per coordinate, proposals immutable (fingerprints), identical semantic streams ALIAS (no new risk), a fourth distinct stream is refused (cap), no refund of elapsed exploration time after a refused candidate, a disjoint PAC / deterministic pair is a recorded conflict and the variable is withheld"""
    base, binding = load_mid('dg_n16_c4_clique_two'); model = duplicate_states(base)                                  # card 8 with an exact quotient to card 4 (PAC needed on the quotient): primary = exact-parent stream; lifted on the quotient parent
    P = UPlanner(model, dict(model_sha256='ctrl'), 8.0, admission_stop_s=7.5, t_start=PA.tnow(), seed=3, pac=True, lifted=True); out = P.run()
    kinds = [S.kind for S in P.streams]; led = out['risk_ledger']; alloc_ok = all(F(x['delta_s']) == DELTA / 2 ** x['stream'] for x in led) and len(led) >= 2 and kinds[:2] == ['exact_parent', 'lifted']
    alpha_ok = all(abs(S.mech['alpha_per_coordinate'] - float(S.delta_s) / S.Kq) < 1e-18 for S in P.streams if hasattr(S, 'Kq') and S.mech.get('alpha_per_coordinate') is not None)
    immut = all(S.mech.get('proposal_immutable', True) for S in P.streams); first_draw = {a.get('stream'): a['t_s'] for a in reversed(out['actions']) if a.get('action') in ('advance_stream', 'probe_stream')}; created_before_draw = all(x['created_t_s'] <= first_draw.get(x['label'], 1e9) for x in led)
    n0 = len(P.streams); S3 = P.new_stream('original', model=P.req.model, queries=P.req.queries, decode=None, label='pac(original)'); third_new = len(P.streams) == n0 + 1 and S3.sid == 3 and F(out['risk_ledger'][-1]['delta_s']) == DELTA / 8
    S3b = P.new_stream('original', model=P.req.model, queries=P.req.queries, decode=None, label='pac(original) again'); aliased = (S3b is S3) and len(P.streams) == n0 + 1 and len(out['risk_ledger']) == n0 + 1
    over = None
    try: P.new_stream('original', model=P.req.model, queries=P.req.queries[:1], decode=None, label='distinct')
    except Refused as e: over = e.kind
    refused_actions = [a for a in out['actions'] if str(a.get('status', '')).startswith('REFUSED')]; E_used_ok = P.E_used >= sum(a.get('actual_s') or 0 for a in refused_actions) - 1e-9 and P.E_used <= P.E + 0.6
    P.retained = {(0, 0): (F(1, 10), F(1, 10) + F(1, 1000))}
    class FakeS:
        label = 'fake'; kind = 'original'; pending = None; retained_bytes = 0; measurements = []
        def pac_rows(self): return {0: (F(9, 10), F(95, 100))}
        def live(self): return False
        decode_rows = staticmethod(lambda rows_q, S=None: {(int(P.M.orig_of[0]), 0): rows_q[0]})
    P.streams.append(FakeS()); n_conf = len(P.conflicts); rows = P.snapshot(); x0 = int(P.M.orig_of[0]); withheld = all(rows.get((x0, a)) is None for a in range(P.cards_in[x0]))
    rec('D10_three_streams_risk_and_conflicts', alloc_ok and alpha_ok and immut and created_before_draw and third_new and aliased and over == 'STREAMS' and E_used_ok and len(P.conflicts) > n_conf and withheld, kinds=kinds, ledger=led, third_new=third_new, aliased=aliased, over_cap=over, E=P.E, E_used=P.E_used, outcome=out['outcome'], published=(out['published'], out['K']), conflicts=P.conflicts[-1:], immutable=immut, created_before_draw=created_before_draw)

def D11_expiry_and_memory_injections():
    """hard expiry injected in PAC preparation / in a batch at the work cutoff / in final assembly / in output; exhausted memory before an input-sized allocation (lifted decoder rows; the mini-bucket memory plan); an optional refusal leaves other admitted work usable"""
    import dense_gen as DG
    model, binding = load('dg_n12_c4_clique_two'); res = {}
    # (a) expiry inside preparation: the work cutoff passes during preparation -> the stream closes typed, the planner returns DEADLINE / PARTIAL, nothing invalid
    t0 = PA.tnow(); P = UPlanner(model, binding, 3.85, admission_stop_s=0.12, t_start=t0, seed=1, pac=True, lifted=False); out = P.run(); res['prep_expiry'] = dict(outcome=out['outcome'], streams=[(S.stage, (S.closed_reason or '')[:60]) for S in P.streams], published=out['published'])
    # (b) a hard cut inside a shared-response batch closes the stream with its committed prefix (Stream.batch with hard = now - 1 after READY)
    model_r, binding_r = load('dg_n12_c4_reg6_two'); st = PA.RequestState(model_r, binding_r, EPS, DELTA); t0 = PA.tnow(); PA.structural_routes(st, t0 + 30, flags=dict(evidence_expansion=False, layered_contraction=False, ancestral_response=False)); old = IG.RECOVERY_BYTE_BUDGET; IG.RECOVERY_BYTE_BUDGET = 0
    try:
        S = PA.Stream(1, 'original', st.model, st.queries, 1, EPS, DELTA, dict(PAC_OPTS, exact_route=False, table_cap=1 << 13)); S.prepare(t0 + 30, cdead=t0 + 15); assert S.stage == 'READY' and S.shared_blocks > 0, (S.stage, S.closed_reason, getattr(S, 'shared_blocks', None))
        for _ in range(2): assert S.batch(PA.tnow() + 30) == 'COMMITTED'
        r = S.batch(PA.tnow() + 30, hard=PA.tnow() - 1.0); res['batch_hard_cut'] = dict(result=r, batches=S.batches, closed=(S.closed_reason or '')[:80], pending=(S.pending is not None))
    finally: IG.RECOVERY_BYTE_BUDGET = old
    # (c) final assembly / output expiry: the inherited authoritative sample (fin) and write_result -> nothing published; exercised by forcing hard = now before fin
    P2 = UPlanner(model, binding, 3.85, admission_stop_s=3.5, t_start=PA.tnow(), seed=1, pac=False, lifted=False); P2.M = CE.canonicalize(model, P2.hclock, P2.budget); P2.orig_to_canon = {}; P2.out['mechanism']['positive_mass_witness'] = True; P2.hard = PA.tnow() - 1.0
    rows = {(P2.M.orig_of[0], a): dict(lo=F(1, 4), hi=F(1, 4), point=F(1, 4), guarantee='EXACT') for a in range(4)}; o2 = P2.fin('COMPLETE', rows); res['final_assembly_expiry'] = dict(outcome=o2['outcome'], published=o2['published'], suppressed=o2['mechanism'].get('suppressed_late_rows'))
    import tempfile; d = tempfile.mkdtemp(); o3 = dict(outcome='COMPLETE', published=1, K=1, answers=[dict(var=0, state=0, lo='1', hi='1', point='1', guarantee='EXACT')], phases_s={}, mechanism={}); o3 = UP.write_result(o3, os.path.join(d, 'r.json'), 1.0, t_process_start=PA.tnow() - 5.0); res['output_expiry'] = dict(outcome=o3['outcome'], published=o3['published'], late_commit=o3['mechanism'].get('late_commit') is not None)
    # (d) memory exhausted before the input-sized allocation: lifted decoder rows refuse MEMORY at the charge (nothing allocated), the mini-bucket plan refuses typed under a tiny USABLE
    clk = CE.Clock(PA.tnow() + 30, {}); M = CE.canonicalize(model, clk, CE.Budget(CE.CONSTRUCTOR_BYTES)); classes, Cz = fast_stage(M, clk, CE.Budget(CE.CONSTRUCTOR_BYTES)); tiny = CE.Budget(100); mem = None
    try: LD.build_rows(M, classes, Cz, clk, tiny)
    except CE.Refused as e: mem = (e.kind, tiny.live, tiny.peak)
    model_m, binding_m = load_mid('dg_n16_c4_clique_two'); st_m = PA.RequestState(model_m, binding_m, EPS, DELTA); PA.structural_routes(st_m, PA.tnow() + 30, flags=dict(evidence_expansion=False, layered_contraction=False, ancestral_response=False)); oldU = IG.USABLE_BYTES; IG.USABLE_BYTES = 1 << 20
    try: S4 = PA.Stream(1, 'original', st_m.model, st_m.queries, 1, EPS, DELTA, dict(PAC_OPTS, exact_route=False)); r4 = S4.prepare(PA.tnow() + 30, cdead=PA.tnow() + 15); res['memory_plan_refusal'] = dict(result=r4, closed=(S4.closed_reason or '')[:80], draws=S4.draws, stages=[m['stage'] for m in S4.measurements])
    finally: IG.USABLE_BYTES = oldU
    # (e) an optional refusal leaves other admitted work usable: the lifted stream refused (tiny budget) while the primary stream completes
    P5 = UPlanner(model_m, binding_m, 8.0, admission_stop_s=7.5, t_start=PA.tnow(), seed=1, pac=True, lifted=True); P5._orig_make_lifted = P5.make_lifted
    def refusing_lifted(approx): raise Refused('MEMORY', 'injected: lifted decoder rows exceed the constructor budget')
    P5.make_lifted = refusing_lifted; o5 = P5.run(); res['optional_refusal_other_work'] = dict(outcome=o5['outcome'], published=o5['published'], K=o5['K'], lifted_refused=any(a.get('action') == 'create_lifted' and str(a.get('status', '')).startswith('REFUSED') for a in o5['actions']), streams=[S.kind for S in P5.streams])
    ok = (res['prep_expiry']['outcome'] in ('DEADLINE', 'PARTIAL', 'DEADLINE_PARTIAL', 'REFUSED') and res['prep_expiry']['published'] == 0 and res['batch_hard_cut']['result'] == 'CLOSED' and res['batch_hard_cut']['batches'] == 2 and not res['batch_hard_cut']['pending']
          and res['final_assembly_expiry']['outcome'] == 'DEADLINE' and res['final_assembly_expiry']['published'] == 0 and res['output_expiry']['outcome'] == 'DEADLINE' and res['output_expiry']['published'] == 0 and mem is not None and mem[0] == 'MEMORY' and mem[1] == 0
          and res['memory_plan_refusal']['result'] == 'CLOSED' and 'MEMORY_POLICY' in res['memory_plan_refusal']['closed'] and res['optional_refusal_other_work']['lifted_refused'] and res['optional_refusal_other_work']['outcome'] == 'COMPLETE')
    rec('D11_expiry_and_memory_injections', ok, **res, decoder_memory=mem)

def D12_structural_routes_reach_accepted_completions():
    """the accepted structural routes execute INSIDE the planner on their fixtures and deliver the accepted rows: layered contraction (R20 tiny fixtures), signed evidence expansion (R19 fixtures), ancestral responses (G4) -- compared with integrated.solve on the same inputs"""
    RDB = '/Users/adis/Workspace/pgm-records/code/runs/mdi_2026-10-28/BLOCKRES_2026-11-19'
    fixtures = [('layered', os.path.join(RDB, 'round20/R20_PACKET/theory_r20_prototype/tiny/case1.uai'), 'layered_contraction'), ('layered2', os.path.join(RDB, 'round20/R20_PACKET/theory_r20_prototype/tiny/case7.uai'), 'layered_contraction'), ('ancestral_G4', os.path.join(RDB, 'round21/inputs/G4_near_c3_theta17-20_span3.uai'), 'ancestral_response')]
    import glob; sig = sorted(glob.glob(os.path.join(RDB, 'round19/**/*.uai'), recursive=True))[:1]
    for p in sig: fixtures.append(('signed', p, 'signed_evidence_expansion'))
    res = []; ok_all = True
    for name, path, route in fixtures:
        if not os.path.exists(path): res.append(dict(name=name, missing=path)); continue
        model, binding = CORE.read_uai(path); out_b = IG.solve(path, 19.5, seed=1, route='auto', schedule='targeted', table_cap=1 << 18, enum_cap=1 << 16, mb_cap=1 << 24, batch=1024)
        P = UPlanner(model, binding, 19.5, admission_stop_s=19.0, t_start=PA.tnow(), seed=1, pac=True, lifted=True); out = P.run()
        rb = {(r['var'], r['state']): (r['lo'], r['hi']) for r in out_b['answers'] if r['guarantee'] != 'NOT_PUBLISHED'}; rp = {(r['var'], r['state']): (r['lo'], r['hi']) for r in out['answers'] if r['guarantee'] != 'NOT_PUBLISHED'}
        same = rb == rp; route_b = out_b['mechanism'].get('route'); route_p = out['mechanism'].get('route'); okk = same and out['outcome'] == 'COMPLETE' and route_p == route_b and (route_b == route or name == 'signed'); ok_all &= okk
        res.append(dict(name=name, accepted_route=route_b, planner_route=route_p, rows_identical=same, outcome=out['outcome'], accepted_outcome=out_b['outcome'], published=(out['published'], out_b['published']), wall=(round(out['wall_s'], 3), round(out_b['wall_s'], 3))))
    rec('D12_structural_routes_reach_accepted_completions', ok_all and len([r for r in res if 'missing' not in r]) >= 3, fixtures=res)

def D13_functional_completion_after_partial_action():
    """a stream closed by a hard cut (its last batch abandoned) while its committed prefix + the deterministic rows complete the request: the final snapshot decides COMPLETE; the termination reason and the closure are recorded separately; phase timings preserved"""
    model, binding = load_mid('dg_n16_c4_clique_two'); P = UPlanner(model, binding, 30.0, admission_stop_s=29.0, t_start=PA.tnow(), seed=1, pac=True, lifted=False); P.cands = []
    # drive: canonicalize, then a primary stream to full publication, then abandon a pending batch (closing the stream), then fin with a partial label
    P.M = CE.canonicalize(model, P.hclock, P.budget); P.orig_to_canon = {int(P.M.orig_of[v]): v for v in range(len(P.M.cards))}; P.mf = CM.model_features(P.M, P.clock, P.budget); P.t_mark = PA.tnow()
    PA.structural_routes(P.req, P.adm, flags=dict(evidence_expansion=False, layered_contraction=False, ancestral_response=False)); S = P.make_primary(); P.primary = S; S.prepare(P.adm, cdead=P.cdead); assert S.stage == 'READY', (S.stage, S.closed_reason)
    t0 = PA.tnow()
    while PA.tnow() - t0 < 20 and not S.all_published():
        S.batch(P.adm)
        if S.batches % 25 == 0: S.check()
    S.check(); assert S.all_published(), (len(S.pub), S.Kq)
    S.pending = dict(Sb=np.zeros((4, len(S.S)), dtype=np.int64), bi=0); S.abandon('injected hard cut'); assert S.stage == 'CLOSED'
    P.out['mechanism']['positive_mass_witness'] = S.witness; rows = P.snapshot(); out = P.fin('DEADLINE_PARTIAL', rows, note='control')
    rec('D13_functional_completion_after_partial_action', out['outcome'] == 'COMPLETE' and out['mechanism']['termination'] == 'DEADLINE_PARTIAL' and out['guarantee'] == 'PAC' and out['published'] == out['K'] and out['streams'][0]['stage'] == 'CLOSED' and out['streams'][0]['abandoned'] == 1 and 'contract' in out['streams'][0]['phases'], outcome=out['outcome'], termination=out['mechanism']['termination'], guarantee=out['guarantee'], published=(out['published'], out['K']), stream=(out['streams'][0]['stage'], out['streams'][0]['closed'][:60]), phases=list(out['streams'][0]['phases']))

def D14_edge_cases_typed():
    """hard zeros / zero evidence / zero unary mass / extreme positive rationals / factorless + fixed coordinates / scalar ownership / incompatible bindings: typed outcomes, no publication without the witness, fixed rows exact"""
    res = {}
    def run(model, **kw):
        P = UPlanner(model, dict(model_sha256='ctrl'), 3.0, admission_stop_s=2.5, t_start=PA.tnow(), seed=1, pac=True, lifted=True, **kw); return P.run()
    o = run(dict(cards=[2, 2], factors=[dict(scope=(0, 1), values=[F(0), F(1), F(1), F(0)])], evidence={0: 0, 1: 0})); res['zero_evidence'] = (o['outcome'], o['published'], o['mechanism'].get('positive_mass_witness'))
    o = run(dict(cards=[2, 2, 3], factors=[dict(scope=(0, 1), values=[F(1), F(0), F(0), F(1)]), dict(scope=(1, 2), values=[F(1), F(2), F(0), F(0), F(1), F(1)])], evidence={})); res['hard_zeros'] = (o['outcome'], o['published'], o['K'], o['guarantee'])
    o = run(dict(cards=[2, 2], factors=[dict(scope=(0, 1), values=[F(1), F(1), F(1), F(1)]), dict(scope=(0,), values=[F(0), F(0)])], evidence={})); res['zero_unary'] = (o['outcome'], o['published'])
    o = run(dict(cards=[2, 2], factors=[dict(scope=(0, 1), values=[F(2) ** 1500, F(1), F(1), F(2) ** -1500])], evidence={})); res['extreme_rationals'] = (o['outcome'], o['published'], o['K'], (o['mechanism'].get('refusal') or {}).get('kind'))
    o = run(dict(cards=[2, 3, 1, 4], factors=[dict(scope=(0, 1), values=[F(1), F(2), F(3), F(4), F(5), F(6)]), dict(scope=(3,), values=[F(1), F(1), F(2), F(4)]), dict(scope=(), values=[F(7)])], evidence={})); fx = {(r['var'], r['state']): r for r in o['answers']}
    res['factorless_fixed_scalar'] = (o['outcome'], o['published'], o['K'], fx[(2, 0)].get('lo'), fx[(3, 3)].get('lo'), fx[(3, 3)].get('guarantee'))
    o = run(dict(cards=[2, 2], factors=[dict(scope=(0, 1), values=[F(1), F(2), F(3), F(4)])], evidence={}), ); res['plain'] = (o['outcome'], o['published'])
    import tempfile, subprocess; d = tempfile.mkdtemp(); bad = os.path.join(d, 'bad.uai'); open(bad, 'w').write('MARKOV\n2\n2 2\n1\n2 0 1\n4\n1 2 3 4\n'); open(bad + '.evid', 'w').write('1 5 0\n')
    r = subprocess.run([sys.executable, os.path.join(HERE, 'unified_pac_planner.py'), '--input', bad, '--output', os.path.join(d, 'out.json'), '--budget', '2.0', '--admission-stop', '1.5'], capture_output=True, text=True, cwd=os.path.dirname(HERE)); ob = json.load(open(os.path.join(d, 'out.json'))); res['incompatible_binding'] = (ob['outcome'], ob['published'], r.returncode)
    ok = (res['zero_evidence'][0] == 'ZERO_EVIDENCE' and res['zero_evidence'][1] == 0 and res['hard_zeros'][0] == 'COMPLETE' and res['hard_zeros'][1] == res['hard_zeros'][2] and res['zero_unary'][0] == 'ZERO_EVIDENCE' and res['zero_unary'][1] == 0
          and res['extreme_rationals'][1] in (0, res['extreme_rationals'][2]) and res['factorless_fixed_scalar'][0] == 'COMPLETE' and res['factorless_fixed_scalar'][3] == '1' and res['factorless_fixed_scalar'][4] == '1/2' and res['factorless_fixed_scalar'][5] == 'EXACT' and res['plain'][0] == 'COMPLETE' and res['incompatible_binding'][0] == 'INVALID_TASK' and res['incompatible_binding'][1] == 0)
    rec('D14_edge_cases_typed', ok, **res)

CONTROLS += [D5_lifted_enumeration_identity_parent, D6_lifted_enumeration_exact_then_approx, D7_zero_lower_positive_upper_witness, D8_surrogate_mutant_fails_oracle, D9_numerical_bound_operation_by_operation, D10_three_streams_risk_and_conflicts, D11_expiry_and_memory_injections, D12_structural_routes_reach_accepted_completions, D13_functional_completion_after_partial_action, D14_edge_cases_typed]


if __name__ == '__main__':
    ap = argparse.ArgumentParser(); ap.add_argument('out'); ap.add_argument('--only', default=None); a = ap.parse_args(); t0 = time.time()
    for c in CONTROLS:
        if a.only and c.__name__.split('_')[0] not in a.only.split(','): continue
        try: c()
        except Exception as e: rec(c.__name__, False, error=repr(e)[:300], tb=traceback.format_exc()[-1200:])
    res = dict(all_ok=all(r['ok'] for r in R), n=len(R), n_ok=sum(r['ok'] for r in R), wall_s=round(time.time() - t0, 2), controls=R); json.dump(res, open(a.out, 'w'), indent=1, default=str); print(json.dumps({k: v for k, v in res.items() if k != 'controls'}))
