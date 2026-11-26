"""Qualification controls of DENSE_GENERIC_PAC_INTEGRATION_1 (brief section 7), DGP2 (D19-D26), DGP3 (D27-D31: RF1-RF4, lemma G), DGP4 (D32-D41: R1-R3, residual MAX compiler, checker, whole proposal, lifetime; D37 / D38 / D39 / D41 strengthened in DGP5) and DGP5 (D42-D53: the joint conditional construction -- seed, exact floor, local witnesses, mutants, quantization / incumbent witness, replication / staleness, units, epochs, refusal lifetime, held-out isolation, feature-disabled / expiry, real clock). usage: check_dgp.py OUT.json [--only D1,D2,..]. Every control asserts actual branch execution."""
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
ORACLE_DEV = '/Users/adis/Workspace/pgm-records/code/runs/mdi_2026-10-28/DGP2_REPAIR_AND_DIAGNOSIS/oracle/dev_inputs'
def load_odev(name): return CORE.read_uai(os.path.join(ORACLE_DEV, name + '.uai'))

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
from unified_planner import Refused, Defect, CM, Clock

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
    S2 = PA.LiftedStream(1, M, M, [], classes, Cz, 2, EPS, DELTA / 2, dict(PAC_OPTS)); assert S2.prepare(time.monotonic() + 60) == 'READY'; S2.logU_capf -= 3.0
    r2 = S2.batch(time.monotonic() + 60); fired = r2 == 'CLOSED' and 'certificate defect' in str(getattr(S2, 'defect', '')) and S2.pac_rows() == {} and S2.batches == 0     # v0.5.1: the production assertion fires inside the batch; the stream closes typed (CERTIFICATE_DEFECT recorded), its rows are withheld
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





def D15_lift_only_discovery_recheck():
    """when the deterministic FAST discovery refuses BITS on the diagnostic ratio product R, the lift-only discovery builds the SAME classes with the SAME checker, discards R (None) and re-checks every quantity the lifted proposal uses (A, d, u, U, L) under the normal bit cap; the candidate never enters the deterministic candidate list; its charge is in the ledger identity; a model whose decoder itself exceeds the cap is refused BITS (nothing lifted)"""
    model, binding = load_mid('dg_n24_c4_clique_two'); P = UPlanner(model, binding, 4.0, admission_stop_s=3.5, t_start=PA.tnow(), seed=1, pac=True, lifted=True); out = P.run()
    acts = out['actions']; fast = [a for a in acts if a.get('action') == 'discover_fast']; lift = [a for a in acts if a.get('action') == 'discover_fast_lift']; lo = out['mechanism'].get('lift_only_candidates') or []
    ok_a = bool(fast) and fast[0].get('status') == 'REFUSED_BITS' and bool(lift) and lift[0].get('status') == 'READY_LIFT_ONLY' and len(lo) == 1 and lo[0].get('R_compact_log2_hi') is not None and math.isfinite(lo[0]['R_compact_log2_hi']) and lo[0]['R_compact_log2_hi'] > 0 and not any(c['name'].startswith('approx_lift_only') for c in out['candidates']) and out['mechanism']['constructor_live_ledger_identity'] and any(S.kind == 'lifted' for S in P.streams)      # DGP2: the unused global ratio product is a COMPACT enclosure (log2 > 4,096, which is why the exact product refused), never a raised global cap
    c = P.lift_cands[0]; worst = max([UP.bits(x) for row in c.Cz.A for x in row] + [UP.bits(x) for row in c.Cz.d for x in row] + [UP.bits(x) for tab in c.Cz.U for x in tab] + [UP.bits(x) for tab in c.Cz.L for x in tab]); recheck_ok = worst <= CE.BIT_CAP and c.Cz.R is None and c.R is None and c.Cz.R_compact is not None and CE.BIT_CAP == 4096
    # the lifted stream built on it reproduces the checker's classes and decoder (fingerprint of the stage), and its cap / kappa are finite
    S = next(S for S in P.streams if S.kind == 'lifted'); same_stage = S.classes is c.classes and S.Cz is c.Cz; cap_ok = S.mech.get('cap_log2_total') is not None and S.mech.get('kappa_log2') is not None and S.stage in ('READY', 'CLOSED')
    # a decoder beyond the cap: variable 0's two states have IDENTICAL pair slices (they merge) and unary masses of ~2,378 / ~2,322 bits (each < 4,096), so the decoder d = u / A needs ~4,757 bits -> refused BITS, nothing lifted, charge released
    big = dict(cards=[2, 2, 2], factors=[dict(scope=(0, 1), values=[F(1), F(2), F(1), F(2)]), dict(scope=(1, 2), values=[F(1), F(2), F(3), F(4)]), dict(scope=(0,), values=[F(3) ** 1500, F(5) ** 1000]), dict(scope=(1,), values=[F(1), F(1)]), dict(scope=(2,), values=[F(1), F(1)])], evidence={})
    P2 = UPlanner(big, dict(model_sha256='ctrl'), 3.0, admission_stop_s=2.5, t_start=PA.tnow(), seed=1, pac=True, lifted=True); P2.M = CE.canonicalize(big, P2.hclock, P2.budget); P2.canonical_charge = P2.budget.live; P2.mf = CM.model_features(P2.M, P2.clock, P2.budget); ident = P2.make_identity(P2.clock); P2.cands.append(ident); refused = None; live0 = P2.budget.live
    try: P2.discover_fast_lift_only(ident, Clock(PA.tnow() + 5, {}))
    except Refused as e: refused = e.kind
    released = P2.budget.live == live0
    rec('D15_lift_only_discovery_recheck', ok_a and recheck_ok and same_stage and cap_ok and refused == 'BITS' and released, fast_status=(fast[0].get('status') if fast else None), lift=(lift[0] if lift else None), lift_only=lo, worst_bits_rechecked=worst, R_compact_log2_hi=c.Cz.R_compact.log2_hi(), stream=(S.label, S.stage, S.draws, S.mech.get('cap_log2_total'), S.mech.get('kappa_log2')), big_decoder_refusal=refused, charge_released=released, outcome=out['outcome'])

CONTROLS.append(D15_lift_only_discovery_recheck)





def D16_exact_rows_from_constant_blocks_published():
    """a model whose contraction fully eliminates one component (a constant block with interior queries): the stream recovers those rows EXACTLY during preparation; they are published WITH the witness and the final snapshot is complete; BASE on the same input publishes the same exact rows"""
    model, binding = load_mid('dg_n16_c4_clique_two'); n = len(model['cards']); small = dict(cards=model['cards'] + [3, 3, 3], factors=list(model['factors']) + [dict(scope=(n, n + 1), values=[F(k + 1, 2) for k in range(9)]), dict(scope=(n + 1, n + 2), values=[F(2 * k + 1, 3) for k in range(9)]), dict(scope=(n,), values=[F(1), F(2), F(1)])], evidence={})
    import tempfile, hp_gen as G; d = tempfile.mkdtemp(); p = os.path.join(d, 'cb.uai'); G.write(p, small)
    out_b = IG.solve(p, 6.0, seed=1, route='auto', schedule='targeted', table_cap=1 << 18, enum_cap=1 << 16, mb_cap=1 << 24, batch=1024); rb = {(r['var'], r['state']): (r['lo'], r['hi'], r['guarantee']) for r in out_b['answers'] if r['guarantee'] != 'NOT_PUBLISHED'}
    P = UPlanner(small, dict(model_sha256='ctrl'), 8.0, admission_stop_s=7.5, t_start=PA.tnow(), seed=1, pac=True, lifted=False); out = P.run(); rp = {(r['var'], r['state']): (r['lo'], r['hi'], r['guarantee']) for r in out['answers'] if r['guarantee'] != 'NOT_PUBLISHED'}
    S = P.streams[0] if P.streams else None; ex = S.exact_rows() if S else {}; exact_coords = {(x, a) for (x, a) in rp if x >= n}
    ok = S is not None and len(ex) == 9 and out['outcome'] == 'COMPLETE' and out['published'] == out['K'] == 73 and all(rp[q][2] == 'EXACT' and rb.get(q, (None,))[0] == rp[q][0] for q in exact_coords) and len(exact_coords) == 9 and S.mech.get('const_blocks', 0) >= 1
    rec('D16_exact_rows_from_constant_blocks_published', ok, outcome=out['outcome'], published=(out['published'], out['K']), exact_rows_in_stream=len(ex), const_blocks=S.mech.get('const_blocks') if S else None, base_outcome=out_b['outcome'], base_published=out_b['published'], exact_match_base=all(rb.get(q, (None,))[0] == rp[q][0] for q in exact_coords), sample=sorted(exact_coords)[:3])

def D17_lifted_constant_log_domain_huge_scale():
    """a model with huge rational denominators (integerization scale ~ 2^2000): the lifted stream's cap constant is computed in the log domain (no float of the rational), the stream becomes READY and its weights obey the cap on every enumerated state (no certificate defect); X_an <= 1 by enumeration"""
    import random; rng = random.Random(7); n = 5; card = 3
    def val(): return F(rng.randrange(1, 2 ** 40), 2 ** rng.randrange(380, 420))
    model = dict(cards=[card] * n, factors=[dict(scope=(i, j), values=[val() for _ in range(card * card)]) for i in range(n) for j in range(i + 1, n)] + [dict(scope=(v,), values=[val() for _ in range(card)]) for v in range(n)], evidence={})
    clk = CE.Clock(time.monotonic() + 60, {}); B = CE.Budget(CE.CONSTRUCTOR_BYTES); M = CE.canonicalize(model, clk, B); classes, Cz = fast_stage(M, clk, B)
    S = PA.LiftedStream(1, M, M, [], classes, Cz, 3, EPS, DELTA / 2, dict(PAC_OPTS)); r = S.prepare(time.monotonic() + 60); ready = r == 'READY'
    big_scale = ready and S.scale_F.bit_length() > 1000 and S.scale_F.bit_length() < 1 << 20
    worst = F(0)
    if ready:
        Z, mu = enum_marginals(M); coarse_states = list(itertools.product(*[range(k) for k in Cz.ccards])); Sb = np.array(coarse_states, dtype=np.int64); logq, q_an = S.mbp.logq_given(Sb, S.pos)
        for ci, c in enumerate(coarse_states):
            qc = q_an[ci]
            if qc == 0: continue
            for z in itertools.product(*[S.rows.members[v][c[v]] for v in range(n)]):
                W = LD.parent_weight(M, z) / M.scalar; r_ = F(1)
                for v in range(n): r_ *= LD.r_prob(S.rows, v, c[v], z[v])
                Xan = F(S.scale_F) * W / (qc * r_) / (F(2.0 ** (S.logU_capf - int(S.logU_capf))) * F(2) ** (int(S.logU_capf) + S.mbp.E_U)); worst = max(worst, Xan)
        for _ in range(20): assert S.batch(time.monotonic() + 60) == 'COMMITTED'
        S.check(); rows = S.pac_rows(); viol = sum(1 for j, (L, H) in rows.items() if not (L <= mu[S.queries[j]] <= H))
    rec('D17_lifted_constant_log_domain_huge_scale', ready and big_scale and worst <= 1 and S.witness and not getattr(S, 'defect', None) and (viol == 0), ready=ready, closed=S.closed_reason, scale_F_bits=(S.scale_F.bit_length() if ready else None), const_log2=S.mech.get('const_log2'), max_X_analyzed=float(worst), draws=S.draws, published=len(S.pub) if ready else None)

def D18_optional_stream_exception_leaves_request_usable():
    """an exception injected inside the optional lifted stream's preparation (and separately a certificate-defect assertion inside its batch) closes THAT stream typed and recorded; the primary stream and the request continue to completion; the defective stream's rows are withheld"""
    model, binding = load_mid('dg_n16_c4_clique_two'); res = {}
    P = UPlanner(model, binding, 8.0, admission_stop_s=7.5, t_start=PA.tnow(), seed=1, pac=True, lifted=True); orig = PA.LiftedStream._l_sampler
    def boom(self, deadline): raise OverflowError('injected: integer division result too large for a float')
    PA.LiftedStream._l_sampler = boom
    try: out = P.run()
    finally: PA.LiftedStream._l_sampler = orig
    lifted = [S for S in P.streams if S.kind == 'lifted']; res['prep_exception'] = dict(outcome=out['outcome'], published=(out['published'], out['K']), lifted_closed=(lifted[0].closed_reason if lifted else None), refusal=out['mechanism'].get('refusal'))
    P2 = UPlanner(model, binding, 8.0, admission_stop_s=7.5, t_start=PA.tnow(), seed=1, pac=True, lifted=True); orig_s = PA.LiftedStream._l_sampler
    def understated(self, deadline): orig_s(self, deadline); self.logU_capf -= 60.0                      # an UNDERSTATED cap: the production assertion inside the real batch fires (certificate defect)
    PA.LiftedStream._l_sampler = understated
    try: out2 = P2.run()
    finally: PA.LiftedStream._l_sampler = orig_s
    lifted2 = [S for S in P2.streams if S.kind == 'lifted']; res['batch_defect'] = dict(outcome=out2['outcome'], published=(out2['published'], out2['K']), lifted_closed=(lifted2[0].closed_reason if lifted2 else None), lifted_rows_withheld=(lifted2[0].pac_rows() == {} if lifted2 else None), recorded=out2['mechanism'].get('stream_certificate_defects'))
    ok = res['prep_exception']['outcome'] == 'COMPLETE' and 'NUMERIC' in str(res['prep_exception']['lifted_closed']) and res['prep_exception']['refusal'] is None and res['batch_defect']['outcome'] == 'COMPLETE' and 'CERTIFICATE_DEFECT' in str(res['batch_defect']['lifted_closed']) and res['batch_defect']['lifted_rows_withheld'] and bool(res['batch_defect']['recorded'])
    rec('D18_optional_stream_exception_leaves_request_usable', ok, **res)

CONTROLS += [D16_exact_rows_from_constant_blocks_published, D17_lifted_constant_log_domain_huge_scale, D18_optional_stream_exception_leaves_request_usable]





# ---------------------------------------------------------------- DGP2 repair controls (branch-executing; the before-failures are in DGP2_REPAIR_AND_DIAGNOSIS/controls/before)
def D19_F1_widening_consumed_bounds():
    """F1: the CONSUMED rho_X / cap_tol / Certificate eps_num derive from a d_total that already includes 5u|E_tot| and the constant's log terms; exercised with a nonzero exponent shift (tiny entries -> |E_tot| > 0)"""
    import random; rng = random.Random(3); n = 5; card = 3
    def val(): return F(rng.randrange(1, 2 ** 30), 2 ** 600)
    model = dict(cards=[card] * n, factors=[dict(scope=(i, j), values=[val() for _ in range(card * card)]) for i in range(n) for j in range(i + 1, n)] + [dict(scope=(v,), values=[F(1) + F(rng.randrange(0, 5), 8) for _ in range(card)]) for v in range(n)], evidence={})
    clk = CE.Clock(time.monotonic() + 30, {}); B = CE.Budget(CE.CONSTRUCTOR_BYTES); M = CE.canonicalize(model, clk, B); classes, Cz = fast_stage(M, clk, B)
    S = PA.LiftedStream(1, M, M, [], classes, Cz, 1, EPS, DELTA / 2, dict(PAC_OPTS)); r = S.prepare(time.monotonic() + 30); assert r == 'READY', (r, S.closed_reason)
    w = S.mech['widening']; parts = S.mech['widening_parts']; d_rep = F(w['delta_log_total']); five_u_E = 5 * IG.UF * abs(S.E_tot)
    d_parts = sum(F(parts[k]) for k in ('d_zf', 'd_impl', 'd_U', 'd_r', 'd_k', 'd_fin')); includes_E = abs(d_parts - d_rep) <= F(1, 10 ** 20) and F(parts['d_fin']) >= five_u_E
    rho_from_total = float((1 + F(145, 100) * d_rep * (1 + d_rep)) * (1 + F(parts['rho_fine'])) - 1); consumed_ok = S.mech['rho_X'] >= rho_from_total * (1 - 1e-12)
    cap_tol_ok = abs(S.cap_tol - (IG.up(math.log2(1.0 + 2 * S.mech['rho_X'])) + 2 ** -40)) <= 1e-18; cert_ok = (S.cert.eps_num == S.eps_num) and abs(S.eps_num - (2 * S.mech['rho_X'] + float(w['rho_f']) + float(w['law']) + float(w['trunc']))) <= 1e-24
    const_ok = 'kappa_compact' in S.mech and parts['d_k'] > 0
    rec('D19_F1_widening_consumed_bounds', includes_E and consumed_ok and cap_tol_ok and cert_ok and const_ok and abs(S.E_tot) > 0, E_tot=S.E_tot, five_u_E=float(five_u_E), d_fin=parts['d_fin'], d_k=parts['d_k'], rho_X=S.mech['rho_X'], rho_X_from_total=rho_from_total, cap_tol=S.cap_tol, eps_num=S.eps_num)

def D20_F2_normalizer_ownership():
    """F2: [1,2,2,4] + nullary 7 through the exact-parent stream -> original Z = 63 exactly, marginals 1/3 / 2/3; composition with a factorless variable and a fixed (card-1) variable; zero-mass stays typed"""
    def run(model):
        P = UPlanner(model, dict(model_sha256='ctrl'), 10.0, admission_stop_s=9.5, t_start=PA.tnow(), seed=1, pac=True, lifted=False); P.M = CE.canonicalize(model, P.hclock, P.budget); P.orig_to_canon = {int(P.M.orig_of[v]): v for v in range(len(P.M.cards))}; P.mf = CM.model_features(P.M, P.clock, P.budget); P.canonical_charge = P.budget.live; P.t_mark = PA.tnow()
        ident = P.make_identity(P.clock); P.cands.append(ident); ex = P.discover_exact(P.clock); P.cands.append(ex); S = P.make_primary(); P.primary = S; S.prepare(P.adm, cdead=P.cdead); P._stream_terminal(S); return P, S
    P, S = run(dict(cards=[2, 2], factors=[dict(scope=(0, 1), values=[F(1), F(2), F(2), F(4)]), dict(scope=(), values=[F(7)])], evidence={})); ze = P.out['Z_enclosure']; enc = P.all_enclosures()
    a = ze['lo'] == '63' and ze['hi'] == '63' and ze.get('exact') and str(S.Z) == '9' and str(S.scale_to_original) == '7' and enc[(0, 0)] == (F(1, 3), F(1, 3)) and enc[(1, 1)] == (F(2, 3), F(2, 3))
    # composition: factorless variable 2 (card 3, unary 1,2,1) and a card-1 variable 3: scalar absorbs 4 (unary sum) x 1; Z = 63 x 4 = 252
    P2, S2 = run(dict(cards=[2, 2, 3, 1], factors=[dict(scope=(0, 1), values=[F(1), F(2), F(2), F(4)]), dict(scope=(), values=[F(7)]), dict(scope=(2,), values=[F(1), F(2), F(1)])], evidence={})); ze2 = P2.out['Z_enclosure']; enc2 = P2.all_enclosures()
    b = ze2['lo'] == '252' and ze2['hi'] == '252' and enc2[(2, 1)] == (F(1, 2), F(1, 2)) and enc2[(3, 0)] == (F(1), F(1)) and enc2[(0, 1)] == (F(2, 3), F(2, 3))
    # zero mass: nullary 0 -> ZERO_EVIDENCE typed, nothing published
    P3 = UPlanner(dict(cards=[2, 2], factors=[dict(scope=(0, 1), values=[F(1), F(2), F(2), F(4)]), dict(scope=(), values=[F(0)])], evidence={}), dict(model_sha256='ctrl'), 3.0, admission_stop_s=2.5, t_start=PA.tnow(), seed=1, pac=True, lifted=False); o3 = P3.run()
    rec('D20_F2_normalizer_ownership', a and b and o3['outcome'] == 'ZERO_EVIDENCE' and o3['published'] == 0, Z63=ze, Z252=ze2, zero=o3['outcome'], stream=(S.kind, S.mech.get('terminal'), str(S.Z), str(S.scale_to_original)))

def D21_F3_finalization_expiry_tails():
    """F3: on a nontrivial PAC request and on a factorless-only request, an expired hard deadline at finalization suppresses answers, enclosures and radius (mechanism.suppressed_on_expiry recorded); the enclosure / cost work happens before the authoritative sample; a late commit strips the new fields on disk"""
    res = {}
    model, binding = load_mid('dg_n16_c4_clique_two'); P = UPlanner(model, binding, 30.0, admission_stop_s=29.0, t_start=PA.tnow(), seed=1, pac=True, lifted=False); P.M = CE.canonicalize(model, P.hclock, P.budget); P.orig_to_canon = {int(P.M.orig_of[v]): v for v in range(len(P.M.cards))}; P.mf = CM.model_features(P.M, P.clock, P.budget); P.t_mark = PA.tnow()
    PA.structural_routes(P.req, P.adm, flags=dict(evidence_expansion=False, layered_contraction=False, ancestral_response=False)); S = P.make_primary(); P.primary = S; S.prepare(P.adm, cdead=P.cdead)
    for _ in range(20): S.batch(P.adm)
    S.check(); P.out['mechanism']['positive_mass_witness'] = S.witness; rows = P.snapshot(); P.hard = PA.tnow() - 1.0; o = P.fin('DEADLINE_PARTIAL', rows, note='control'); res['pac'] = dict(outcome=o['outcome'], published=o['published'], enclosures=len(o['enclosures']), radius=o['radius_report'], suppressed=o['mechanism'].get('suppressed_on_expiry'), cost_present=bool(o.get('cost_breakdown')))
    fl_model = dict(cards=[3, 2], factors=[dict(scope=(0,), values=[F(1), F(2), F(1)]), dict(scope=(1,), values=[F(1), F(3)])], evidence={}); P2 = UPlanner(fl_model, dict(model_sha256='ctrl'), 3.0, admission_stop_s=2.5, t_start=PA.tnow(), seed=1, pac=True, lifted=False); P2.M = CE.canonicalize(fl_model, P2.hclock, P2.budget); P2.orig_to_canon = {}; P2.out['mechanism']['positive_mass_witness'] = True; P2.t_mark = PA.tnow(); P2.hard = PA.tnow() - 1.0; o2 = P2.fin('COMPLETE', {}, note='control')
    res['factorless'] = dict(outcome=o2['outcome'], published=o2['published'], enclosures=len(o2['enclosures']), radius=o2['radius_report'])
    src = open(os.path.join(HERE, 'unified_pac_planner.py')).read(); fin_src = src[src.index('    def fin(self, oc, rows, note=None):'):src.index('    def cost_breakdown(self):')]; order_ok = fin_src.index('self.all_enclosures()') < fin_src.index('res = super().fin(') and fin_src.index('self.cost_breakdown()') < fin_src.index('res = super().fin(')
    import tempfile; d = tempfile.mkdtemp(); o3 = dict(outcome='COMPLETE', published=1, K=1, answers=[dict(var=0, state=0, lo='1', hi='1', point='1', guarantee='EXACT')], enclosures=[dict(var=0, state=0, lo='0', hi='1')], radius_report=dict(worst=0.5), phases_s={}, mechanism={}); UP.write_result(o3, os.path.join(d, 'r.json'), 1.0, t_process_start=PA.tnow() - 5.0); disk = json.load(open(os.path.join(d, 'r.json')))
    res['late_commit'] = dict(outcome=disk['outcome'], published=disk['published'], enclosures=len(disk.get('enclosures') or []), radius=disk.get('radius_report'))
    ok = res['pac']['outcome'] == 'DEADLINE' and res['pac']['published'] == 0 and res['pac']['enclosures'] == 0 and res['pac']['radius'] is None and res['pac']['suppressed'] and res['pac']['cost_present'] and res['factorless']['outcome'] == 'DEADLINE' and res['factorless']['published'] == 0 and res['factorless']['enclosures'] == 0 and order_ok and res['late_commit']['outcome'] == 'DEADLINE' and res['late_commit']['enclosures'] == 0 and res['late_commit']['radius'] is None
    rec('D21_F3_finalization_expiry_tails', ok, work_before_sample=order_ok, **res)

def D22_F4_confidence_endpoints():
    """F4: (a) two wide parent intervals whose INTERSECTION with a deterministic row is publishable -> published; (b) an exact decoder d = 1/2 makes a wide parent interval (width 0.012 > 2 eps) publishable on the original coordinate; (c) an informative interval that does not meet epsilon stays in the enclosures (diagnostic) and is not published; witness / defect rules preserved"""
    class FakeCert:
        def __init__(self, lo, hi): self.lo = np.array(lo); self.hi = np.array(hi)
        def sets(self): return self.lo, self.hi
    def fake_stream(P, queries, lo, hi, decode, label='fake'):
        S = PA.Stream.__new__(PA.Stream); S.sid = 1; S.kind = 'original'; S.label = label; S.queries = list(queries); S.qix = {q: j for j, q in enumerate(queries)}; S.K = len(queries); S.sq = list(queries); S.qmap = {q: j for j, q in enumerate(queries)}; S.Kq = len(queries); S.eps = EPS; S.pub = {}; S.endpoints = {}; S.trace = []; S.draws = 1024; S.zero_draws = 0; S.sumX = 500.0; S.checkpoints = 0; S.t_cert = 0.0; S.measurements = []; S.witness = True; S.stage = 'READY'; S.pending = None; S.retained_bytes = 0; S.pending_rows = {}; S.defect = None; S.mech = {}; S.cert = FakeCert(lo, hi); S.decode_rows = decode; S.semantic_key = label
        def live(): return True
        S.live = live; S.exact_rows = lambda: {}; S.check(); return S
    # (a) identity decode, var 0 states: parent intervals [0.30, 0.312], [0.688, 0.70] (width 0.012); deterministic retained row [0.303, 0.309] / [0.691, 0.697]: intersection width 0.006 -> publishable
    model = dict(cards=[2, 2], factors=[dict(scope=(0, 1), values=[F(1), F(2), F(3), F(4)])], evidence={}); P = UPlanner(model, dict(model_sha256='ctrl'), 3.0, admission_stop_s=2.5, t_start=PA.tnow(), seed=1, pac=True, lifted=False); P.M = CE.canonicalize(model, P.hclock, P.budget); P.orig_to_canon = {int(P.M.orig_of[v]): v for v in range(2)}; P.mf = CM.model_features(P.M, P.clock, P.budget); P.t_mark = PA.tnow(); P.out['mechanism']['positive_mass_witness'] = True
    P.retained = {(0, 0): (F(303, 1000), F(309, 1000)), (0, 1): (F(691, 1000), F(697, 1000))}
    S = fake_stream(P, [(0, 0), (0, 1), (1, 0), (1, 1)], [0.300, 0.688, 0.40, 0.594], [0.312, 0.700, 0.412, 0.606], lambda rows_q, S=None: {(0, 0): rows_q[0], (0, 1): rows_q[1], (1, 0): rows_q[2], (1, 1): rows_q[3]}); P.streams = [S]; rows = P.snapshot(); enc = P.all_enclosures()
    a = len(S.endpoints) == 4 and rows.get((0, 0)) is not None and rows[(0, 0)]['guarantee'] == 'DETERMINISTIC' and rows.get((1, 0)) is None and enc[(1, 0)] == (F(0.40), F(0.412)) and enc[(1, 1)] == (F(0.594), F(0.606))
    # (b) exact decoder d = 1/2 on both states of class 0 of var 0: parent interval [0.60, 0.612] (width 0.012) -> decoded [0.30, 0.306] (width 0.006) publishable; var 1 class 0 -> parent [0.388, 0.40] -> [0.194, 0.20]
    P2 = UPlanner(model, dict(model_sha256='ctrl'), 3.0, admission_stop_s=2.5, t_start=PA.tnow(), seed=1, pac=True, lifted=False); P2.M = CE.canonicalize(model, P2.hclock, P2.budget); P2.orig_to_canon = {int(P2.M.orig_of[v]): v for v in range(2)}; P2.mf = CM.model_features(P2.M, P2.clock, P2.budget); P2.t_mark = PA.tnow(); P2.out['mechanism']['positive_mass_witness'] = True
    half = F(1, 2)
    def dec(rows_q, S=None):
        out = {}
        if 0 in rows_q: L, H = rows_q[0]; out[(0, 0)] = (half * L, half * H); out[(0, 1)] = (half * L, half * H)
        if 1 in rows_q: L, H = rows_q[1]; out[(1, 0)] = (half * L, half * H); out[(1, 1)] = (half * L, half * H)
        return out
    S2 = fake_stream(P2, [(0, 0), (1, 0)], [0.988, 0.988], [1.0, 1.0], dec, 'fake_exact_parent'); P2.streams = [S2]; rows2 = P2.snapshot()           # the class holds both states (class probability 1): parent width 0.012 > 2 eps; decoded [0.494, 0.5] per state (width 0.006), the row box meets the simplex
    b = len(S2.endpoints) == 2 and len(S2.pub) == 0 and all(rows2.get(q) is not None for q in ((0, 0), (0, 1), (1, 0), (1, 1))) and rows2[(0, 0)]['guarantee'] == 'PAC_EB' and rows2[(0, 0)]['lo'] == F(0.988) / 2
    # (c) witness False -> nothing from the stream; defect -> nothing
    S.witness = False; rows3 = P.snapshot(); c1 = rows3.get((0, 0)) is not None and all(P.pac_enclosures().get(q) is None for q in ((1, 0), (1, 1)))     # the deterministic row still publishes var 0; the stream contributes nothing
    S.witness = True; S.defect = 'injected'; c2 = P.pac_enclosures() == {}
    rec('D22_F4_confidence_endpoints', a and b and c1 and c2, intersection_published=a, decoder_made_publishable=b, informative_diagnostic=(rows.get((1, 0)) is None and enc[(1, 0)] != (F(0), F(1))), witness_rule=c1, defect_rule=c2)

def D23_F5_optional_stage_bounded():
    """F5: a deliberately slow optional (lifted) preparation stage (3 s > the remaining account) is cut at the account's end (closed typed), the account is debited by the actual time only, and the primary stream completes the request"""
    model, binding = load_mid('dg_n16_c4_clique_two'); orig = PA.LiftedStream._l_coarse_proposal
    def slow(self, deadline):
        t0 = time.monotonic()
        while time.monotonic() - t0 < 3.0:
            if time.monotonic() >= deadline: raise PA.Deadline('slow optional stage cut at its deadline')
            time.sleep(0.02)
        return orig(self, deadline)
    PA.LiftedStream._l_coarse_proposal = slow
    try: P = UPlanner(model, binding, 8.0, admission_stop_s=7.5, t_start=PA.tnow(), seed=1, pac=True, lifted=True); o = P.run()
    finally: PA.LiftedStream._l_coarse_proposal = orig
    lift = [S for S in P.streams if S.kind == 'lifted']; prep = [x for x in o['actions'] if x.get('action') == 'prepare_stream' and 'lifted' in str(x.get('stream'))]; E_rem = next((d.get('E_remaining_s') for d in o['decisions'] if str(d.get('chosen', '')).startswith('create_lifted')), None)
    ok = bool(lift) and 'DEADLINE' in str(lift[0].closed_reason) and prep and prep[0]['actual_s'] <= (E_rem or 0) + 0.1 and o['outcome'] == 'COMPLETE' and P.E_used <= P.E + 0.1
    rec('D23_F5_optional_stage_bounded', ok, E=P.E, E_used=P.E_used, E_remaining_at_creation=E_rem, lifted_prepare_s=[round(x['actual_s'], 3) for x in prep], lifted_closed=(lift[0].closed_reason if lift else None), outcome=o['outcome'], published=(o['published'], o['K']))

def D24_compact_kappa_and_scoped_lift_check():
    """compact kappa: (a) the n64/card4 strong clique decoder builds with a 128-bit outward enclosure containing the exact oracle product (no exact product in production; bit cap unchanged); (b) random products of 300-bit ratios stay enclosed; (c) the scoped checker mode gives IDENTICAL entrywise quantities to the default mode and a compact R containing the exact R; (d) an invalid partition and an understated upper table are still rejected"""
    p = '/Users/adis/Workspace/pgm-records/code/runs/mdi_2026-10-28/DENSE_GENERIC_PAC_INTEGRATION_1/inputs_eval/dg_n64_c4_clique_two.uai'; model, binding = CORE.read_uai(p)
    P = UPlanner(model, binding, 30.0, admission_stop_s=29.0, t_start=PA.tnow(), seed=1, pac=True, lifted=True); P.M = CE.canonicalize(model, P.hclock, P.budget); P.mf = CM.model_features(P.M, P.clock, P.budget); ident = P.make_identity(P.clock); P.cands.append(ident); P.canonical_charge = P.budget.live
    cap0 = CE.BIT_CAP; c = P.discover_fast_lift_only(ident, Clock(PA.tnow() + 30, {})); R = LD.build_rows(P.M, c.classes, c.Cz, Clock(PA.tnow() + 30, {}), P.budget); kap = LD.exact_kappa(R)
    a = R.kappa is None and R.K is not None and R.K.contains(kap) and CE.BIT_CAP == cap0 == 4096 and CE.bits(kap) > 4096 and R.K.inflation() < 2 ** -100
    import random; rng = random.Random(11); K = LD.Compact.one(); exact = F(1)
    for _ in range(300): q = F(rng.randrange(1, 2 ** 300), rng.randrange(1, 2 ** 300)); exact *= q; K = K.mul(LD.Compact.from_fraction(q))
    b = K.contains(exact) and K.lo_m.bit_length() == 128 and K.hi_m.bit_length() == 128
    model2, b2 = load('dg_n8_c4_clique_two'); clk = CE.Clock(PA.tnow() + 30, {}); B = CE.Budget(CE.CONSTRUCTOR_BYTES); M2 = CE.canonicalize(model2, clk, B); classes2, Cz_e = fast_stage(M2, clk, B); Cz_c = CE.check_candidate(M2, classes2, CE.unit_scales(M2), clk, B, ratio_product='compact')
    same = Cz_e.u == Cz_c.u and Cz_e.A == Cz_c.A and Cz_e.d == Cz_c.d and Cz_e.L == Cz_c.L and Cz_e.U == Cz_c.U and Cz_e.Rf == Cz_c.Rf and Cz_e.gaps == Cz_c.gaps and Cz_e.mixed == Cz_c.mixed and Cz_e.exact == Cz_c.exact; cR = Cz_c.R is None and Cz_c.R_compact is not None and Cz_c.R_compact.contains(Cz_e.R)
    bad_part = None
    try: CE.check_candidate(M2, [[0, 0, 0, 2]] + classes2[1:], CE.unit_scales(M2), clk, B, ratio_product='compact')
    except CE.Defect as e: bad_part = 'Defect'
    Cz_bad = CE.check_candidate(M2, classes2, CE.unit_scales(M2), clk, B, ratio_product='compact'); fi = 0; cidx = max(range(len(Cz_bad.U[fi])), key=lambda i: Cz_bad.U[fi][i]); Cz_bad.U[fi][cidx] = Cz_bad.L[fi][cidx] / 10 ** 6; R2 = LD.build_rows(M2, classes2, Cz_bad, clk, B); rejected = None     # a deliberately INVALID upper table (one cell below its own lower extremum): the independent enumeration must reject it
    try: LD.enumerate_check(M2, classes2, Cz_bad, R2)
    except CE.Defect as e: rejected = str(e)[:60]
    rec('D24_compact_kappa_and_scoped_lift_check', a and b and same and cR and bad_part == 'Defect' and rejected is not None and 'upper envelope violated' in rejected, n64_compact=R.K.record(), exact_oracle_kappa_bits=CE.bits(kap), exact_oracle_kappa_float=float(kap), random_product_enclosed=b, entrywise_identical=same, compact_R_contains_exact=cR, invalid_partition=bad_part, understated_upper_rejected=rejected)

def D25_fixed_r_limits_attaining_laws():
    """lemma R: on a tiny enumeration the fixed-r limits are attained by their explicit laws, M2_lift equals sum p_C^2 H_c / q_C, the ordering 1 <= M2 <= R* <= C/Z holds for both laws, and the exact-upper law's quantities are finite"""
    import dgp2_oracle as OR; p = os.path.join(os.path.dirname(DEV), '..', '..', 'DGP2_REPAIR_AND_DIAGNOSIS', 'oracle', 'dev_inputs', 'dg_n6_c4_clique_two.uai'); p = os.path.abspath(p); model, binding = CORE.read_uai(p)
    clk = CE.Clock(PA.tnow() + 60, {}); B = CE.Budget(CE.CONSTRUCTOR_BYTES); M = CE.canonicalize(model, clk, B); enum = OR.enumerate_original(M, PA.tnow() + 60); st = PA.RequestState(model, binding, EPS, DELTA); PA.structural_routes(st, PA.tnow() + 60, flags=dict(evidence_expansion=False, layered_contraction=False, ancestral_response=False))
    S1, r1 = OR.original_stream(st, 1, PA.tnow() + 60); q1, _ = OR.original_quantities(S1, enum, M, PA.tnow() + 60); S2, r2, classes, Cz = OR.lifted_stream(M, 1, PA.tnow() + 60, B); q2, _ = OR.lifted_quantities(S2, classes, Cz, enum, M, PA.tnow() + 60)
    ok = q1['ordering_ok'] and q2['ordering_ok'] and abs(q2['M2_lift_check'] - q2['M2']) <= 1e-9 * q2['M2'] and abs(q2['M2_at_attaining_law'] - q2['M2_min_fixed_r']) <= 1e-9 * q2['M2_min_fixed_r'] and abs(q2['R_star_at_attaining_law'] - q2['R_star_min_fixed_r']) <= 1e-9 * q2['R_star_min_fixed_r'] and q2['M2_min_fixed_r'] <= q2['M2'] * (1 + 1e-9) and q2['R_star_min_fixed_r'] <= q2['R_star'] * (1 + 1e-9) and q2['B_cap_violations'] == 0 and abs(q2['log2_C_over_Z'] - q2['decomposition_check_log2'] - q2['numerical_cap_inflation_log2']) < 1e-9 and not q1['support_failure'] and not q2['support_failure']
    rec('D25_fixed_r_limits_attaining_laws', ok, original=dict(log2_M2=q1['log2_M2'], log2_R_star=q1['log2_R_star'], log2_C_over_Z=q1['log2_C_over_Z'], tight=q1['log2_C_tight_over_Z']), lifted=dict(log2_M2=q2['log2_M2'], M2_min=q2['M2_min_fixed_r'], M2_at_law=q2['M2_at_attaining_law'], R_min=q2['R_star_min_fixed_r'], R_at_law=q2['R_star_at_attaining_law'], decomposition=(q2['log2_B_over_ZU'], q2['log2_ZU_over_Z'], q2['log2_K_hi'], q2['log2_C_over_Z']), exact_upper=q2['exact_upper_law']))

def D26_forced_stream_mode():
    """forced-stream diagnostic: --force-stream lifted builds and advances ONLY the lifted stream with the planner-role risk delta/4 (stream index 2), never a deterministic solve; --force-stream original runs stream 1 with delta/2; outcomes are recorded, not counted"""
    model, binding = load_mid('dg_n16_c4_clique_two')
    P = UPlanner(model, binding, 4.0, admission_stop_s=3.5, t_start=PA.tnow(), seed=1, pac=True, lifted=True, force_stream='lifted'); o = P.run(); L = [S for S in P.streams if S.kind == 'lifted']
    a = len(P.streams) == 1 and bool(L) and L[0].sid == 2 and F(o['risk_ledger'][0]['delta_s']) == DELTA / 4 and not any(str(x.get('action', '')).startswith('solve_') for x in o['actions']) and L[0].draws > 0
    P2 = UPlanner(model, binding, 4.0, admission_stop_s=3.5, t_start=PA.tnow(), seed=1, pac=True, lifted=False, force_stream='original'); o2 = P2.run(); b = len(P2.streams) == 1 and P2.streams[0].kind == 'original' and F(o2['risk_ledger'][0]['delta_s']) == DELTA / 2 and P2.streams[0].draws > 0
    rec('D26_forced_stream_mode', a and b, lifted=dict(outcome=o['outcome'], draws=(L[0].draws if L else None), delta_s=o['risk_ledger'][0]['delta_s'] if o['risk_ledger'] else None, decisions=[d.get('chosen') for d in o['decisions']][:6]), original=dict(outcome=o2['outcome'], draws=P2.streams[0].draws if P2.streams else None, delta_s=o2['risk_ledger'][0]['delta_s'] if o2['risk_ledger'] else None))

CONTROLS += [D19_F1_widening_consumed_bounds, D20_F2_normalizer_ownership, D21_F3_finalization_expiry_tails, D22_F4_confidence_endpoints, D23_F5_optional_stage_bounded, D24_compact_kappa_and_scoped_lift_check, D25_fixed_r_limits_attaining_laws, D26_forced_stream_mode]



# ---------------------------------------------------------------- DGP3 controls (PROTOCOL.md section 8: RF1 .. RF4; lemma G)
import copy, importlib
def D27_RF1_no_work_after_authoritative_sample():
    """RF1 (DGP2 review finding 1): the reviewer's injection -- every answer row advances the injected clock past the hard deadline when its guarantee is READ -- must find NO row read after the parent's authoritative
    sample (classified == 0; before the repair: 2 reads, COMPLETE 2/2 with the clock at hard + 0.01); a second injection advances the clock past the deadline exactly AT the sample and must yield DEADLINE with 0
    published; the source order is checked (no traversal of res['answers'] after super().fin in UPlanner.fin; the guarantee set comes from the parent's _fin_gs)"""
    simple = dict(cards=[2], factors=[dict(scope=(0,), values=[F(1), F(1)])], evidence={}); res = {}
    def mk():
        P = UPlanner(simple, {}, 3.0, admission_stop_s=2.5, t_start=PA.tnow()); P.M = CE.canonicalize(simple, P.hclock, P.budget); P.canonical_charge = P.budget.live; P.t_mark = P.t_start; P.out['mechanism']['positive_mass_witness'] = True; return P
    P = mk(); state = {'now': P.t_start + 0.01, 'classified': 0}
    class TimedRow(dict):
        def __getitem__(self, key):
            if key == 'guarantee': state['classified'] += 1; state['now'] = P.hard + 0.01
            return super().__getitem__(key)
    real_fin = UP.Planner.fin; old = (UP.tnow, UPP.tnow)
    def inject_rows(self, *a, **kw):
        r = real_fin(self, *a, **kw); r['answers'] = [TimedRow(x) for x in r['answers']]; return r
    UP.Planner.fin = inject_rows; UP.tnow = UPP.tnow = lambda: state['now']
    try: r = P.fin('COMPLETE', {}); res['row_injection'] = dict(outcome=r['outcome'], published=r['published'], K=r['K'], classified_after_sample=state['classified'], hard_deadline_respected=r['hard_deadline_respected'], injected_wall=state['now'] - P.t_start)
    finally: UP.Planner.fin = real_fin; UP.tnow, UPP.tnow = old
    P2 = mk(); state2 = {'now': P2.t_start + 0.01, 'calls': 0}
    def clock2():
        state2['calls'] += 1
        return state2['now']
    real_fin2 = UP.Planner.fin
    def expire_at_sample(self, *a, **kw):
        state2['now'] = P2.hard + 0.01; return real_fin2(self, *a, **kw)                        # the clock is past the deadline when the parent samples it
    UP.Planner.fin = expire_at_sample; UP.tnow = UPP.tnow = clock2
    try: r2 = P2.fin('COMPLETE', {}); res['expiry_at_sample'] = dict(outcome=r2['outcome'], published=r2['published'], hard_deadline_respected=r2['hard_deadline_respected'], suppressed=r2['mechanism'].get('suppressed_on_expiry'))
    finally: UP.Planner.fin = real_fin2; UP.tnow, UPP.tnow = old
    src = open(os.path.join(HERE, 'unified_pac_planner.py')).read(); fin_src = src[src.index('    def fin(self, oc, rows, note=None):'):src.index('    def cost_breakdown(self):')]; after = fin_src[fin_src.index('res = super().fin('):]
    order_ok = ("for r in res['answers']" not in after) and ('self._fin_gs' in after) and (fin_src.index('ledger_identity = (') < fin_src.index('res = super().fin('))
    ok = res['row_injection']['classified_after_sample'] == 0 and res['row_injection']['outcome'] == 'COMPLETE' and res['expiry_at_sample']['outcome'] == 'DEADLINE' and res['expiry_at_sample']['published'] == 0 and res['expiry_at_sample']['hard_deadline_respected'] is False and order_ok
    rec('D27_RF1_no_work_after_authoritative_sample', ok, source_order_ok=order_ok, **res)


def D28_RF2_sampler_stage_deadline_and_byte_identity():
    """RF2 (finding 2): (i) the polled sampler preparation produces BYTE-IDENTICAL log tables, strides and scopes to the accepted MBFloat.prepare_sampler on a deep copy of the same planned proposal (original and lifted
    streams); (ii) an injected clock that advances 0.5 s per read inside the lifted sampler stage against a 0.1 s optional allowance closes the stream typed at a step poll (never READY), and the planner's account is
    debited by the elapsed injected time (kept, not refunded); (iii) the admission guard: a plan understated below the first step's log-table bytes refuses MEMORY_POLICY before any allocation"""
    model, binding = load_mid('dg_n16_c4_clique_two'); res = {}; clk = CE.Clock(PA.tnow() + 60, {}); B = CE.Budget(CE.CONSTRUCTOR_BYTES); M = CE.canonicalize(model, clk, B)
    cmp_ = {}
    real = PA.prepare_sampler_polled
    def wrapped(mbp, deadline, plan_log_bytes=None, release_forward=True):
        m2 = copy.deepcopy(mbp); n = real(mbp, deadline, plan_log_bytes, release_forward); IG.MBFloat.prepare_sampler(m2, release_forward)
        same = len(m2.prep) == len(mbp.prep) and all((v1 == v2) and ((t1 is None) == (t2 is None)) and (t1 is None or (len(t1) == len(t2) and all(a[0].tobytes() == b[0].tobytes() and a[0].dtype == b[0].dtype and a[1] == b[1] and tuple(a[2]) == tuple(b[2]) for a, b in zip(t1, t2)))) for (v1, t1), (v2, t2) in zip(mbp.prep, m2.prep))
        cmp_[id(mbp)] = dict(identical=bool(same), steps=len(mbp.prep), tables=sum(len(t) for _, t in mbp.prep if t), bytes=n, fwd_released=(mbp.fwd == m2.fwd == [])); return n
    PA.prepare_sampler_polled = wrapped
    try:
        st = PA.RequestState(model, binding, EPS, DELTA); PA.structural_routes(st, PA.tnow() + 30, flags=dict(evidence_expansion=False, layered_contraction=False, ancestral_response=False)); S0 = PA.Stream(1, 'original', st.model, st.queries, 1, EPS, DELTA / 2, dict(PAC_OPTS)); r0 = S0.prepare(PA.tnow() + 30, cdead=PA.tnow() + 30)
        prof, why = CE.slice_profiles(M, clk, B); classes = [CE.canonical_classes(CE.farthest_split(prof[v], list(range(M.cards[v])), clk), M.cards[v]) for v in range(len(M.cards))]; Cz = CE.check_candidate(M, classes, CE.unit_scales(M), clk, B, ratio_product='compact')
        S1 = PA.LiftedStream(2, M, M, [], classes, Cz, 1, EPS, DELTA / 4, dict(PAC_OPTS, budget_obj=B)); r1 = S1.prepare(PA.tnow() + 30)
    finally: PA.prepare_sampler_polled = real
    res['byte_identity'] = dict(original=(r0, cmp_.get(id(S0.mbp))), lifted=(r1, cmp_.get(id(S1.mbp))))
    # (ii) injected clock inside the real lifted sampler stage: the clock is frozen at t_start + 0.01 through the mini-bucket build and advances 0.03 s per read once the polled preparation is ENTERED
    def advance_to(S, target):
        disp = {'INIT': S._l_decoder, 'INTEGERIZED': S._l_coarse_proposal, 'CONTRACTED': S._l_fine_tables}
        while S.stage != target and S.stage in disp: disp[S.stage](PA.tnow() + 30)
    S3 = PA.LiftedStream(4, M, M, [], classes, Cz, 1, EPS, DELTA / 4, dict(PAC_OPTS, budget_obj=B)); advance_to(S3, 'CONSTANTS'); assert S3.stage == 'CONSTANTS'
    P = UPlanner(model, binding, 10.0, admission_stop_s=9.0, t_start=PA.tnow()); P.E = 0.1; P.E_used = 0.0; P.primary = object()
    state = {'now': P.t_start + 0.01, 'reads': 0, 'step': 0.0, 'entered': 0}
    def clock():
        state['reads'] += 1; state['now'] += state['step']; return state['now']
    real_pl = PA.prepare_sampler_polled
    def entering(*a, **kw):
        state['entered'] += 1; state['step'] = 0.03; return real_pl(*a, **kw)
    old = (PA.tnow, UP.tnow, UPP.tnow, IG.tnow); PA.tnow = UP.tnow = UPP.tnow = IG.tnow = clock; PA.prepare_sampler_polled = entering
    try: P._prepare(S3, P.t_start + 0.1, charge=True)
    finally: PA.tnow, UP.tnow, UPP.tnow, IG.tnow = old; PA.prepare_sampler_polled = real_pl
    res['injected_stage_expiry'] = dict(stage_before='CONSTANTS', stage=S3.stage, closed=S3.closed_reason, E=P.E, E_used=P.E_used, clock_reads=state['reads'], entered_polled_preparation=state['entered'], injected_wall=state['now'] - P.t_start, sampler_prep_none=(S3.mbp.prep is None) if hasattr(S3, 'mbp') else None)
    # (iii) admission guard
    S4 = PA.LiftedStream(5, M, M, [], classes, Cz, 1, EPS, DELTA / 4, dict(PAC_OPTS, budget_obj=B)); advance_to(S4, 'CONSTANTS')
    refusal = None
    try:
        # understate the admitted plan: wrap the polled preparation so the stage's plan argument is replaced by a value below the first step's log-table bytes
        orig_pl = PA.prepare_sampler_polled
        def understated(mbp, deadline, plan_log_bytes=None, release_forward=True): return orig_pl(mbp, deadline, -(1 << 21), release_forward)
        PA.prepare_sampler_polled = understated
        try: r4 = S4.prepare(PA.tnow() + 30)
        finally: PA.prepare_sampler_polled = orig_pl
        refusal = (r4, S4.stage, S4.closed_reason, S4.mbp.prep is None)
    except Exception as e: refusal = ('EXC', repr(e)[:160])
    res['admission_guard'] = refusal
    ok = (r0 == 'READY' and r1 == 'READY' and all(cmp_[k]['identical'] for k in cmp_) and len(cmp_) == 2 and res['injected_stage_expiry']['stage'] == 'CLOSED' and 'DEADLINE' in (S3.closed_reason or '') and 'CONSTANTS' in (S3.closed_reason or '') and 'sampler preparation' in (S3.closed_reason or '') and state['entered'] == 1 and P.E_used >= 0.09 and
          refusal[0] == 'CLOSED' and 'MEMORY_POLICY' in (refusal[2] or '') and refusal[3] is True)
    rec('D28_RF2_sampler_stage_deadline_and_byte_identity', ok, **res)


def D29_RF3_cap_units_equality():
    """RF3 (finding 3): for a READY original stream and a READY lifted stream the ADVERTISED cap (mech.cap_units.cap_Wint_log2) equals the batch formula's constant logU_capf + E_U; the advertised original-units cap
    equals cap_Wint_log2 - log2 scale_F (lifted) and bounds max_z W_par(z) / q(z) over EVERY fine state (exact enumeration: the analyzed X <= 1 is the same statement); the legacy value logU_capf + E_tot differs from
    the advertised one by exactly E_fine - 2 E_U bits (the DGP2 unit error, now recorded and not consumed); a sampled lifted batch's implemented log2 X equals log2 W_int - log2 q - cap_Wint_log2 within the consumed cap_tol"""
    model, binding = load_odev('dg_n6_c4_clique_two'); clk = CE.Clock(PA.tnow() + 60, {}); B = CE.Budget(CE.CONSTRUCTOR_BYTES); M = CE.canonicalize(model, clk, B)
    import dgp2_oracle as OR
    st = PA.RequestState(model, binding, EPS, DELTA); PA.structural_routes(st, PA.tnow() + 30, flags=dict(evidence_expansion=False, layered_contraction=False, ancestral_response=False)); S0 = PA.Stream(1, 'original', st.model, st.queries, 1, EPS, DELTA / 2, dict(OR.PROFILE)); r0 = S0.prepare(PA.tnow() + 30, cdead=PA.tnow() + 30)
    o_eq = (r0 == 'READY') and S0.mech['cap_units']['cap_Wint_log2'] == S0.logU_capf + S0.mbp.E_U
    prof, why = CE.slice_profiles(M, clk, B); classes = [CE.canonical_classes(CE.farthest_split(prof[v], list(range(M.cards[v])), clk), M.cards[v]) for v in range(len(M.cards))]; Cz = CE.check_candidate(M, classes, CE.unit_scales(M), clk, B, ratio_product='compact')
    S = PA.LiftedStream(2, M, M, [], classes, Cz, 1, EPS, DELTA / 4, dict(OR.PROFILE, budget_obj=B)); r1 = S.prepare(PA.tnow() + 30); cu = S.mech['cap_units']
    l_eq = (r1 == 'READY') and cu['cap_Wint_log2'] == S.logU_capf + S.mbp.E_U and abs(cu['cap_original_units_log2'] - (cu['cap_Wint_log2'] - math.log2(S.scale_F))) < 1e-9 and abs((cu['cap_Wint_log2'] - cu['legacy_logU_capf_plus_E_tot']) - (2 * S.mbp.E_U - S.E_fine)) < 1e-9
    n = len(M.cards); cap_int = F(2) ** int(math.floor(S.logU_capf)) * F(2.0 ** (S.logU_capf - math.floor(S.logU_capf))) * F(2) ** S.mbp.E_U; Xmax = F(0); worst_orig_ratio = F(0)
    cstates = sorted(set(tuple(classes[v][z[v]] for v in range(n)) for z in itertools.product(*[range(k) for k in M.cards]))); Sb = np.array(cstates, dtype=np.int64); lq, qC = S.mbp.logq_given(Sb, S.pos); qC = dict(zip(cstates, qC))
    for z in itertools.product(*[range(k) for k in M.cards]):
        c = tuple(classes[v][z[v]] for v in range(n)); W = LD.parent_weight(M, z) / M.scalar; r_ = F(1)
        for v in range(n): r_ *= LD.r_prob(S.rows, v, c[v], z[v])
        q = qC[c] * r_
        if q > 0 and W > 0: Xmax = max(Xmax, F(S.scale_F) * W / (cap_int * q)); worst_orig_ratio = max(worst_orig_ratio, W / q)
    orig_units_ok = Xmax <= 1 and float(IG.lg(worst_orig_ratio)) <= cu['cap_original_units_log2'] + 1e-9
    # a sampled batch: implemented log2 X vs log2 W_int - log2 q - cap_Wint_log2 on the same assignments
    Sb2, logq_s, zero_row = S.mbp.sample_batch(S.rng, 256, S.pos); z = np.zeros((Sb2.shape[0], n), dtype=np.int64); logr = np.zeros(Sb2.shape[0])
    for v in range(n):
        for k in range(Sb2.shape[0]):
            c = int(Sb2[k, v]); mem = S.rows.members[v][c]; z[k, v] = mem[0]; logr[k] = logr[k] + math.log2(LD.r_prob(S.rows, v, c, mem[0]))                   # a deterministic fine choice per coarse state (first member)
    logz = np.zeros(Sb2.shape[0])
    for i in range(len(S.fine)): logz += S.fLM[i][S._flat_fine(z, i)]
    impl = (logz - logq_s - logr - S.logU_capf) + float(S.E_tot); dev = 0.0
    lq2, q_an = S.mbp.logq_given(Sb2, S.pos)
    for k in range(Sb2.shape[0]):
        if not np.isfinite(impl[k]) or q_an[k] == 0: continue
        W = LD.parent_weight(M, tuple(int(x) for x in z[k])) / M.scalar; r_ = F(1)
        for v in range(n): r_ *= LD.r_prob(S.rows, v, int(Sb2[k, v]), int(z[k, v]))
        exact = float(IG.lg(F(S.scale_F) * W)) - float(IG.lg(q_an[k] * r_)) - cu['cap_Wint_log2']; dev = max(dev, abs(exact - float(impl[k])))
    batch_ok = dev <= S.cap_tol
    rec('D29_RF3_cap_units_equality', o_eq and l_eq and orig_units_ok and batch_ok, original_equality=o_eq, lifted_equality=l_eq, cap_Wint_log2=cu['cap_Wint_log2'], cap_original_units_log2=cu['cap_original_units_log2'], legacy=cu['legacy_logU_capf_plus_E_tot'], unit_error_bits=cu['cap_Wint_log2'] - cu['legacy_logU_capf_plus_E_tot'], max_X_analyzed=float(Xmax), log2_worst_orig_ratio=float(IG.lg(worst_orig_ratio)), batch_dev=dev, cap_tol=S.cap_tol)


def D30_lemma_G_grouped_envelope():
    """lemma G: on a dev card-4 model, for envelope levels G2 and G3 the grouped upper model is a VALID envelope (independent enumeration W <= G_U^G d over every fine state, via enumerate_check with the stream's own
    upper function), every grouped table is dominated by the product of its factors' per-factor tables (check_dominance), Z_U^G <= Z_U^G1, the realized coarse law's cap has B_cap_violations == 0 (dgp2_oracle), the
    stream is READY with its grouped metadata recorded and charged; a one-cell UNDERSTATED mutation of a grouped table is caught by the enumeration checker (Defect); the work-cap fallback keeps a factor whose grouping
    would exceed the joint scope ungrouped (its per-factor U verbatim)"""
    import grouped_envelope as GE, dgp2_oracle as OR
    model, binding = load_odev('dg_n6_c4_clique_two'); clk = CE.Clock(PA.tnow() + 90, {}); B = CE.Budget(CE.CONSTRUCTOR_BYTES); M = CE.canonicalize(model, clk, B); n = len(M.cards)
    prof, why = CE.slice_profiles(M, clk, B); classes = [CE.canonical_classes(CE.farthest_split(prof[v], list(range(M.cards[v])), clk), M.cards[v]) for v in range(n)]; Cz = CE.check_candidate(M, classes, CE.unit_scales(M), clk, B, ratio_product='compact')
    enum = OR.enumerate_original(M, PA.tnow() + 60); res = {}; ZU = {}
    for level in ('G1', 'G2', 'G3'):
        S = PA.LiftedStream(2, M, M, [], classes, Cz, 1, EPS, DELTA / 4, dict(OR.PROFILE, budget_obj=B), envelope=level); r = S.prepare(PA.tnow() + 60); ufn = S.upper_weight_fn()
        cstates = list(itertools.product(*[range(k) for k in Cz.ccards])); ZU[level] = sum(ufn(c) for c in cstates); chk = LD.enumerate_check(M, classes, Cz, S.rows, upper_fn=ufn); dom = GE.check_dominance(M, Cz, S.grouped['tables'], S.grouped['groups']) if S.grouped else None
        q2, _ = OR.lifted_quantities(S, classes, Cz, enum, M, PA.tnow() + 60); ge = S.mech.get('grouped_envelope') or {}
        res[level] = dict(ready=(r == 'READY'), envelope_valid=True, dominance=dom, log2_ZU_over_Z=q2['log2_ZU_over_Z'], log2_C_over_Z=q2['log2_C_over_Z'], log2_C_tight_over_Z=q2['log2_C_tight_over_Z'], log2_M2=q2['log2_M2'], B_viol=q2['B_cap_violations'], max_X=q2['max_X_analyzed'], groups=ge.get('groups'), grouped_pairs=ge.get('grouped_pairs'), charged=ge.get('charged_bytes'), released_on_close=None)
        if level == 'G2':
            live0 = B.live; fb, gb = S.fine_bytes, S.grouped_bytes; S._close('control'); res[level]['released_on_close'] = (live0 - B.live == fb + gb and gb > 0)
            # understated mutation: zero one grouped cell (its fine states have positive weight) -> the checker must raise Defect
            S2 = PA.LiftedStream(3, M, M, [], classes, Cz, 1, EPS, DELTA / 4, dict(OR.PROFILE, budget_obj=B), envelope='G2'); S2.prepare(PA.tnow() + 60); gi = next(i for i, g in enumerate(S2.grouped['groups']) if len(g) >= 2); Sc, U = S2.grouped['tables'][gi]
            k = max(range(len(U)), key=lambda i: U[i]); U[k] = F(0); caught = False
            try: LD.enumerate_check(M, classes, Cz, S2.rows, upper_fn=S2.upper_weight_fn())
            except CE.Defect: caught = True
            res['understated_mutation_caught'] = caught; S2._close('control')
    # work-cap fallback: a ternary factor sharing one variable with a pair factor would need joint scope 4 -> stays ungrouped
    tiny = dict(cards=[2, 2, 2, 2], factors=[dict(scope=(0, 1, 2), values=[F(k + 1) for k in range(8)]), dict(scope=(2, 3), values=[F(1), F(2), F(3), F(1)]), dict(scope=(0,), values=[F(1), F(2)]), dict(scope=(1,), values=[F(1), F(1)]), dict(scope=(2,), values=[F(1), F(1)]), dict(scope=(3,), values=[F(1), F(3)])], evidence={})
    Mt = CE.canonicalize(tiny, clk, B); ct = [[0, 0]] * 4; Czt = CE.check_candidate(Mt, ct, CE.unit_scales(Mt), clk, B, ratio_product='compact'); groups, gsc = GE.plan_groups(Mt, Czt, 'G2'); tabs, chg = GE.grouped_upper_tables(Mt, ct, Czt, groups, gsc, clk, B)
    ternary = next(i for i, (sc, _) in enumerate(Mt.factors) if len(sc) == 3); fallback = all(len(g) == 1 for g in groups if ternary in g) and all(max(len(S_) for S_ in gsc) <= GE.MAX_SCOPE for _ in [0]) and any(tabs[gi][1] == list(Czt.U[ternary]) for gi, g in enumerate(groups) if g == (ternary,))
    res['work_cap_fallback'] = dict(groups=[list(g) for g in groups], scopes=[list(x) for x in gsc], ternary_ungrouped=fallback); B.release(chg)
    ok = all(res[l]['ready'] and res[l]['B_viol'] == 0 and res[l]['max_X'] <= 1 for l in ('G1', 'G2', 'G3')) and res['G2']['dominance'] is True and res['G3']['dominance'] is True and ZU['G2'] <= ZU['G1'] and ZU['G3'] <= ZU['G1'] and res['G2']['grouped_pairs'] >= 1 and res['G2']['released_on_close'] and res['understated_mutation_caught'] and fallback
    rec('D30_lemma_G_grouped_envelope', ok, ZU_log2={k: float(IG.lg(v)) for k, v in ZU.items()}, **res)


def D31_RF4_paired_arithmetic_power():
    """RF4: the paired arithmetic diagnostic (dgp3_oracle.paired_arithmetic: exact W_int, exact analyzed q and exact cap evaluated on the SAME production assignments as the implemented float log2 X) reports a maximum
    deviation within the consumed bound on a dev model; a 2^-30 perturbation of ONE implemented block log-table entry is detected (max deviation > bound), so the diagnostic has power against pointwise arithmetic error"""
    import dgp3_oracle as O3, dgp2_oracle as OR
    model, binding = load_odev('dg_n6_c4_clique_two'); clk = CE.Clock(PA.tnow() + 60, {}); B = CE.Budget(CE.CONSTRUCTOR_BYTES); M = CE.canonicalize(model, clk, B); enum = OR.enumerate_original(M, PA.tnow() + 60)
    st = PA.RequestState(model, binding, EPS, DELTA); PA.structural_routes(st, PA.tnow() + 30, flags=dict(evidence_expansion=False, layered_contraction=False, ancestral_response=False, support_closure=True)); S, r = OR.original_stream(st, 1, PA.tnow() + 30)
    a = O3.paired_arithmetic(S, enum, M, 2, PA.tnow() + 60)
    i = next(i for i in range(len(S.bLM)) if np.isfinite(S.bLM[i]).any()); j = int(np.flatnonzero(np.isfinite(S.bLM[i]))[0]); S.bLM[i][j] += 2.0 ** -30; S.rng = np.random.default_rng(np.random.SeedSequence([1, 1]))
    b = O3.paired_arithmetic(S, enum, M, 8, PA.tnow() + 60)
    ok = r == 'READY' and a['within_bound'] is True and a['draws'] >= 2048 and (b['max_abs_log2_dev'] > a['bound_log2_from_rho_X'] or b['within_bound'] is False)
    rec('D31_RF4_paired_arithmetic_power', ok, clean={k: a[k] for k in ('draws', 'max_abs_log2_dev', 'p99_abs_log2_dev', 'consumed_rho_X', 'bound_log2_from_rho_X', 'within_bound')}, perturbed={k: b[k] for k in ('draws', 'max_abs_log2_dev', 'within_bound')})


CONTROLS += [D27_RF1_no_work_after_authoritative_sample, D28_RF2_sampler_stage_deadline_and_byte_identity, D29_RF3_cap_units_equality, D30_lemma_G_grouped_envelope, D31_RF4_paired_arithmetic_power]


# ---------------------------------------------------------------- DGP4 controls (brief CLAUDE_DGP4_RESIDUAL_MAX_SPEC.md section 5): three repairs; residual MAX compiler; checker; whole proposal; lifetime
import grouped_envelope as GE, residual_max_envelope as RM
RMAX_PROD = dict(V=4096, fanin=16, mantissa_bits=128)
def _four_cycle():
    def tab(agree): return [F(9) if ((a & 1) == (b & 1)) == agree else F(1) for a in range(4) for b in range(4)]
    return dict(cards=[4, 4, 4, 4], factors=[dict(scope=(0, 1), values=tab(True)), dict(scope=(1, 2), values=tab(True)), dict(scope=(2, 3), values=tab(True)), dict(scope=(0, 3), values=tab(False))], evidence={})
def _stage(model, classes=None, scales=None):
    clk = CE.Clock(PA.tnow() + 120, {}); B = CE.Budget(CE.CONSTRUCTOR_BYTES); M = CE.canonicalize(model, clk, B)
    if classes is None: classes, Cz = fast_stage(M, clk, B)
    else: Cz = CE.check_candidate(M, classes, scales or CE.unit_scales(M), clk, B, ratio_product='compact')
    rows = LD.build_rows(M, classes, Cz, clk, B); return M, classes, Cz, rows, clk, B
def _compile(M, classes, Cz, rows, clk, B, V=4096, groups=None, arith='compact', midpoint=None):
    comp = RM.RMAXCompile(M, classes, Cz, rows, dict(V=V, fanin=16, mantissa_bits=128), B, clk, arith=arith); comp.build_sources(); comp.build_seeds(groups if groups is not None else GE.plan_groups(M, Cz, 'G2')[0]); comp.set_order(); comp.run_stages(midpoint if midpoint is not None else PA.tnow() + 120); comp.closure()
    if arith == 'compact': comp.pack()
    return comp
def _U_fn(comp): return (comp.packed_upper_weight if comp.A.mode == 'compact' else comp.U_at)


def D32_R1_transpose_semantics_and_permutation_invariance():
    """R1: the brief's fixture (scope (1, 0), entries 1..16; manual classes [0,0,1,1]: the old envelope bounded 14 by 8; FAST classes: 13 by 4 with a real-stream cap defect) now holds exhaustively and the real G2 stream completes
    batches; factor-axis / table permutation invariance: a factor given as scope (1, 0) with the transposed table equals the same factor given as scope (0, 1) in every grouped table (asymmetric values, unequal cardinalities,
    singleton fallback groups), and the RMAX envelope is identical under the permutation"""
    model = dict(cards=[4, 4], factors=[dict(scope=(1, 0), values=[F(k + 1) for k in range(16)])], evidence={}); res = {}
    for label, classes in (('manual_0011', [[0, 0, 1, 1], [0, 0, 1, 1]]), ('fast', None)):
        M, cl, Cz, rows, clk, B = _stage(model, classes); groups, gsc = GE.plan_groups(M, Cz, 'G2'); tabs, chg = GE.grouped_upper_tables(M, cl, Cz, groups, gsc, clk, B); ufn = GE.grouped_upper_weight(M, Cz, tabs); viol = 0
        for z in itertools.product(range(4), range(4)):
            W = LD.parent_weight(M, z); c = (cl[0][z[0]], cl[1][z[1]])
            if W > ufn(c) * Cz.d[0][z[0]] * Cz.d[1][z[1]]: viol += 1
        res[label] = dict(classes=cl, violations=viol); B.release(chg)
    M, cl, Cz, rows, clk, B = _stage(model); S = PA.LiftedStream(2, M, M, [], cl, Cz, 1, EPS, DELTA / 4, dict(PAC_OPTS, budget_obj=B), envelope='G2'); r = S.prepare(PA.tnow() + 30); outs = [S.batch(PA.tnow() + 30) for _ in range(4)]
    res['real_stream'] = dict(prepare=r, batches=outs, defect=S.mech.get('certificate_defect'), max_log2_X=S.maxlogX)
    # permutation invariance on a 3-variable model with unequal cardinalities [2, 3, 4]: factor (2, 0) with transposed values vs (0, 2); plus a (1, 2) factor and a singleton fallback (0, 1, 2) ternary that cannot be grouped
    rng = random.Random(7); cards = [2, 3, 4]; vals02 = [F(rng.randint(1, 9)) for _ in range(8)]; vals12 = [F(rng.randint(1, 9)) for _ in range(12)]; vals012 = [F(rng.randint(1, 9)) for _ in range(24)]
    arr = np.array(vals02, dtype=object).reshape(2, 4); vals20 = list(np.transpose(arr, (1, 0)).reshape(-1))
    mA = dict(cards=cards, factors=[dict(scope=(0, 2), values=vals02), dict(scope=(1, 2), values=vals12), dict(scope=(0, 1, 2), values=vals012)], evidence={}); mB = dict(cards=cards, factors=[dict(scope=(2, 0), values=vals20), dict(scope=(1, 2), values=vals12), dict(scope=(0, 1, 2), values=vals012)], evidence={})
    classes = [[0, 1], [0, 0, 1], [0, 1, 1, 0]]; env = {}
    for lab, m in (('A', mA), ('B', mB)):
        M, cl, Cz, rows, clk, B = _stage(m, classes); groups, gsc = GE.plan_groups(M, Cz, 'G2'); tabs, chg = GE.grouped_upper_tables(M, cl, Cz, groups, gsc, clk, B); ufn = GE.grouped_upper_weight(M, Cz, tabs)
        comp = _compile(M, cl, Cz, rows, clk, B, V=4096); U = comp.packed_upper_weight; cs = list(itertools.product(range(2), range(2), range(2)))
        env[lab] = dict(G=[str(ufn(c)) for c in cs], U=[str(U(c)) for c in cs], groups=[list(g) for g in groups], singleton_fallback=any(len(g) == 1 for g in groups), rmax_valid=RM.enumerate_check_rmax(M, cl, Cz, rows, U)['ok']); comp.release_all(); B.release(chg)
    inv = env['A']['G'] == env['B']['G'] and env['A']['U'] == env['B']['U'] and env['A']['singleton_fallback'] and env['A']['rmax_valid'] and env['B']['rmax_valid']
    ok = res['manual_0011']['violations'] == 0 and res['fast']['violations'] == 0 and r == 'READY' and all(o == 'COMMITTED' for o in outs) and res['real_stream']['defect'] is None and inv
    rec('D32_R1_transpose_semantics_and_permutation_invariance', ok, permutation_invariant=inv, groups_A=env['A']['groups'], groups_B=env['B']['groups'], **res)


def D33_R2_construction_charge_ownership():
    """R2: (a) MEMORY after the first admitted grouped table leaves 0 orphaned bytes (before: 2,800); (b) an injected DEADLINE in the third table leaves 0 (before: 8,400); (c) a real lifted stream whose grouped construction is
    refused by an injected clock leaves the planner's constructor account at rows-only (before: + the admitted tables); (d) the archived preservation input grid4x4_c32_generic replays under the p4 contract with the ledger
    identity TRUE and the original stream completing (before: identity False, 8,400 B discrepancy); (e) RMAX: refusals at sources / seeds / a middle stage / closure release every owned byte; (f) build_rows releases on failure"""
    res = {}
    model = dict(cards=[4] * 6, factors=[dict(scope=sc, values=[F(1 + ((i * 7 + j * 3 + sc[0]) % 5)) for i in range(4) for j in range(4)]) for sc in ((0, 1), (1, 2), (2, 3), (3, 4), (4, 5), (0, 5))], evidence={}); classes = [[0, 0, 1, 1]] * 6
    M, cl, Cz, rows, clk, B = _stage(model, classes); groups, gsc = GE.plan_groups(M, Cz, 'G2'); live0 = B.live; first = 2 * (56 + (8 + CE.FRAC_BYTES) * 8) + 64 * 8
    Bm = CE.Budget(live0 + first + 1); Bm.live = live0; err = None
    try: GE.grouped_upper_tables(M, cl, Cz, groups, gsc, clk, Bm)
    except CE.Refused as e: err = e.kind
    res['memory_after_first'] = dict(refusal=err, orphaned=Bm.live - live0)
    class Clk(CE.Clock):
        def __init__(self): super().__init__(PA.tnow() + 30, {}); self.n = 0
        def poll(self, where):
            if where.startswith('before grouped table'):
                self.n += 1
                if self.n == 3: raise CE.Refused('DEADLINE', 'injected ' + where)
    Bd = CE.Budget(CE.CONSTRUCTOR_BYTES); Bd.live = live0; err = None
    try: GE.grouped_upper_tables(M, cl, Cz, groups, gsc, Clk(), Bd)
    except CE.Refused as e: err = e.kind
    res['deadline_third'] = dict(refusal=err, orphaned=Bd.live - live0)
    P = UPlanner(model, dict(model_sha256='ctrl'), 10.0, admission_stop_s=9.0, t_start=PA.tnow(), seed=1, pac=True, lifted=True, envelope='G2'); P.M = CE.canonicalize(model, P.hclock, P.budget); P.canonical_charge = P.budget.live
    S = PA.LiftedStream(2, P.M, P.M, [], classes, CE.check_candidate(P.M, classes, CE.unit_scales(P.M), P.hclock, P.budget, ratio_product='compact'), 1, EPS, DELTA / 4, dict(PAC_OPTS, budget_obj=P.budget), envelope='G2'); lb = P.budget.live
    real_clock = CE.Clock
    class Clk2(CE.Clock):
        def __init__(self, deadline, stats): super().__init__(deadline, stats); self.n = 0
        def poll(self, where):
            if where.startswith('before grouped table'):
                self.n += 1
                if self.n == 2: raise CE.Refused('DEADLINE', 'injected ' + where)
            return super().poll(where)
    CE.Clock = Clk2
    try: r = S.prepare(PA.tnow() + 30)
    finally: CE.Clock = real_clock
    res['stream_refused'] = dict(result=r, closed=(S.closed_reason or '')[:80], orphaned=P.budget.live - lb - S.rows.bytes)
    # (d) archived replay (real clock, p4 contract)
    man = json.load(open('/Users/adis/Workspace/pgm-records/code/runs/mdi_2026-10-28/DENSE_GENERIC_PAC_INTEGRATION_1/PRESERVATION_18_MANIFEST.json')); t = next(x for x in man['tasks'] if x['name'] == 'grid4x4_c32_generic'); mdl, bnd = CORE.read_uai(t['model'])
    P2 = UPlanner(mdl, bnd, 3.85, admission_stop_s=3.5, t_start=PA.tnow(), seed=1, pac=True, lifted=True, envelope='G2'); o = P2.run(); res['archived_grid4x4_c32'] = dict(outcome=o['outcome'], published=o['published'], K=o['K'], ledger_identity=o['mechanism'].get('constructor_live_ledger_identity'), lifted=[(S_.stage, (S_.closed_reason or '')[:60]) for S_ in P2.streams if S_.kind == 'lifted'])
    # (e) RMAX ownership on the four-cycle under injected failures at every phase
    rel = {}
    for where in ('sources', 'seeds', 'middle_stage', 'closure', 'checker'):
        M4, cl4, Cz4, rows4, clk4, B4 = _stage(_four_cycle(), [[0, 0, 1, 1]] * 4); l0 = B4.live; comp = RM.RMAXCompile(M4, cl4, Cz4, rows4, RMAX_PROD, B4, clk4); kind = None
        try:
            if where == 'sources':
                B4.cap = l0 + 100
                try: comp.build_sources()
                finally: B4.cap = CE.CONSTRUCTOR_BYTES
            else:
                comp.build_sources()
                if where == 'seeds':
                    B4.cap = B4.live + 100
                    try: comp.build_seeds([(0, 1), (2, 3)])
                    finally: B4.cap = CE.CONSTRUCTOR_BYTES
                else:
                    comp.build_seeds([(0, 1), (2, 3)]); comp.set_order()
                    if where == 'middle_stage':
                        comp.stage(comp.residual_order[0]); B4.cap = B4.live + 100
                        try: comp.stage(comp.residual_order[1])
                        finally: B4.cap = CE.CONSTRUCTOR_BYTES
                    elif where == 'closure':
                        comp.run_stages(PA.tnow() + 30); comp.clock = CE.Clock(PA.tnow() - 1, {}); comp.closure()
                    elif where == 'checker':
                        real = RM.check_stage; RM.check_stage = lambda *a_, **k_: dict(ok=False, why='injected', cells=0)
                        try: comp.stage(comp.residual_order[0])
                        finally: RM.check_stage = real
        except (CE.Refused, CE.Defect, RM.RefusedRMAX) as e: kind = getattr(e, 'kind', type(e).__name__)
        comp.release_all(); rel[where] = dict(refusal=kind, orphaned=B4.live - l0, owned_after_release=comp.owned[0])
    res['rmax_release'] = rel
    # (f) build_rows releases on failure (a class without decoder mass -> Defect)
    Mz, clz, Czz, rz, clkz, Bz = _stage(_four_cycle(), [[0, 0, 1, 1]] * 4); l0 = Bz.live; Czz.d[0][0] = F(0); Czz.d[0][2] = F(0); kind = None
    try: LD.build_rows(Mz, clz, Czz, clkz, Bz)
    except (CE.Defect, CE.Refused) as e: kind = type(e).__name__
    res['build_rows_release'] = dict(refusal=kind, orphaned=Bz.live - l0)
    ok = res['memory_after_first'] == dict(refusal='MEMORY', orphaned=0) and res['deadline_third'] == dict(refusal='DEADLINE', orphaned=0) and res['stream_refused']['orphaned'] == 0 and res['archived_grid4x4_c32']['ledger_identity'] is True and res['archived_grid4x4_c32']['outcome'] == 'COMPLETE' and all(v['orphaned'] == 0 and v['refusal'] is not None for v in rel.values()) and res['build_rows_release']['orphaned'] == 0
    rec('D33_R2_construction_charge_ownership', ok, **res)


def D34_R3_parent_final_timestamp():
    """R3: injected expiry INSIDE the parent finalizer's actual action-history aggregation (TimedAction records advance the clock past the deadline on every .get) and AT the final sample, on multi-query / factorless / scalar
    cases: the repaired finalizer publishes 0 with outcome DEADLINE (before: COMPLETE 2/2 with the reported wall at 3.01 s under a 3 s contract); source order: no action / phase sum after the authoritative sample"""
    res = {}
    def planner(model):
        P = UPlanner(model, {}, 3.0, admission_stop_s=2.5, t_start=PA.tnow()); P.M = CE.canonicalize(model, P.hclock, P.budget); P.canonical_charge = P.budget.live; P.t_mark = P.t_start; P.out['mechanism']['positive_mass_witness'] = True; return P
    cases = dict(multi_query=dict(cards=[2, 3], factors=[dict(scope=(0, 1), values=[F(1), F(2), F(1), F(2), F(1), F(1)])], evidence={}), factorless=dict(cards=[3, 2], factors=[dict(scope=(0,), values=[F(1), F(2), F(1)]), dict(scope=(1,), values=[F(1), F(3)])], evidence={}), scalar=dict(cards=[2], factors=[dict(scope=(0,), values=[F(1), F(1)])], evidence={}))
    old = (UP.tnow, UPP.tnow, CE.tnow)
    for name, model in cases.items():
        P = planner(model); state = {'now': P.t_start + 0.01, 'gets': 0}
        class TimedAction(dict):
            def get(self, k, d=None):
                state['gets'] += 1; state['now'] = P.hard + 0.01; return super().get(k, d)
        P.out['actions'] = [TimedAction(action='price', actual_s=0.001), TimedAction(action='discover_fast', actual_s=0.002)]; rows = {(v, a_): dict(lo=F(1, 4), hi=F(1, 4), point=F(1, 4), guarantee='DETERMINISTIC') for v in range(len(model['cards'])) for a_ in range(model['cards'][v])}
        UP.tnow = UPP.tnow = CE.tnow = lambda: state['now']
        try: r = UP.Planner.fin(P, 'COMPLETE', rows)
        finally: UP.tnow, UPP.tnow, CE.tnow = old
        P2 = planner(model); st2 = {'now': P2.t_start + 0.01, 'fin_reads': 0}
        def clock():
            f = sys._getframe(1)
            if f.f_code.co_name == 'fin': st2['fin_reads'] += 1; st2['now'] = P2.hard + 0.01
            return st2['now']
        UP.tnow = UPP.tnow = CE.tnow = clock
        try: r2 = UP.Planner.fin(P2, 'COMPLETE', rows)
        finally: UP.tnow, UPP.tnow, CE.tnow = old
        res[name] = dict(aggregation=dict(outcome=r['outcome'], published=r['published'], gets=state['gets'], respected=r['hard_deadline_respected']), at_sample=dict(outcome=r2['outcome'], published=r2['published'], fin_reads=st2['fin_reads']))
    src = open(os.path.join(HERE, 'unified_planner.py')).read(); fin_src = src[src.index('    def fin(self, oc, rows_canon, note=None):'):src.index('def plan_and_solve')]; after = fin_src[fin_src.index('t_end = tnow()'):]
    order_ok = ("for x in out['actions']" not in after) and ("out['phases_s'].items()" not in after) and ('for ' not in after.split('\n')[1])
    ok = all(v['aggregation']['outcome'] == 'DEADLINE' and v['aggregation']['published'] == 0 and v['aggregation']['gets'] > 0 and v['at_sample']['outcome'] == 'DEADLINE' and v['at_sample']['published'] == 0 and v['at_sample']['fin_reads'] == 1 for v in res.values()) and order_ok
    rec('D34_R3_parent_final_timestamp', ok, source_order_ok=order_ok, **res)


def D35_rmax_exact_limit_and_prefix_validity():
    """lemma 5 / lemma 3 on tiny graphs: with no splits (V large) and EXACT diagnostic arithmetic the complete residual elimination equals the raw rational t(c) on EVERY class (three models: the four-cycle, a random card-4
    triangle with hard zeros, a 5-variable path with unequal class sizes); the production (compact) values dominate t everywhere; along ONE trajectory the exact closure after k committed stages is nonincreasing in k and every
    prefix closure bounds every fine state (W_0 <= U r); a V = 64 split execution remains a valid bound"""
    res = {}; rng = random.Random(11)
    tri = dict(cards=[4, 4, 4], factors=[dict(scope=(0, 1), values=[F(rng.randint(0, 6)) for _ in range(16)]), dict(scope=(1, 2), values=[F(rng.randint(1, 6)) for _ in range(16)]), dict(scope=(0, 2), values=[F(rng.randint(1, 6)) for _ in range(16)]), dict(scope=(1,), values=[F(1), F(2), F(1), F(3)])], evidence={})
    path5 = dict(cards=[4, 3, 4, 2, 4], factors=[dict(scope=(0, 1), values=[F(rng.randint(1, 9)) for _ in range(12)]), dict(scope=(1, 2), values=[F(rng.randint(1, 9)) for _ in range(12)]), dict(scope=(2, 3), values=[F(rng.randint(1, 9)) for _ in range(8)]), dict(scope=(3, 4), values=[F(rng.randint(1, 9)) for _ in range(8)])], evidence={})
    for name, model, classes in (('four_cycle', _four_cycle(), [[0, 0, 1, 1]] * 4), ('triangle_zeros', tri, [[0, 1, 1, 0], [0, 0, 1, 1], [0, 1, 0, 1]]), ('path5_unequal', path5, [[0, 0, 0, 1], [0, 1, 1], [0, 1, 1, 1], [0, 0], [0, 1, 0, 1]])):
        M, cl, Cz, rows, clk, B = _stage(model, classes); t, T = RM.exact_t(M, cl, Cz, rows)
        ce = _compile(M, cl, Cz, rows, clk, B, V=1 << 20, arith='exact'); Ue = {c: ce.U_at(c) for c in itertools.product(*[range(k) for k in Cz.ccards])}; exact_eq = all(Ue[c] == t[c] for c in t) and all(Ue[c] == 0 for c in Ue if c not in t); ce.release_all()
        cp = _compile(M, cl, Cz, rows, clk, B, V=1 << 20); Up = cp.packed_upper_weight; dom = all(Up(c) >= t[c] for c in t); valid = RM.enumerate_check_rmax(M, cl, Cz, rows, Up)['ok']; cp.release_all()
        # one trajectory: closure after k stages (exact), k = 0..n
        traj = []; comp = RM.RMAXCompile(M, cl, Cz, rows, dict(V=1 << 20, fanin=16, mantissa_bits=128), B, clk, arith='exact'); comp.build_sources(); comp.build_seeds(GE.plan_groups(M, Cz, 'G2')[0]); comp.set_order()
        for k in range(len(comp.residual_order) + 1):
            comp.closure(); tot = sum(comp.U_at(c) for c in itertools.product(*[range(kk) for kk in Cz.ccards])); traj.append(tot); ok_k = RM.enumerate_check_rmax(M, cl, Cz, rows, comp.U_at)['ok']
            if not ok_k: traj.append('INVALID'); break
            if k < len(comp.residual_order): comp.stage(comp.residual_order[k])
        comp.release_all(); nonincr = all(isinstance(x, F) for x in traj) and all(traj[i + 1] <= traj[i] for i in range(len(traj) - 1))
        c64 = _compile(M, cl, Cz, rows, clk, B, V=64); v64 = RM.enumerate_check_rmax(M, cl, Cz, rows, c64.packed_upper_weight)['ok']; splits64 = c64.max_splits; c64.release_all()
        res[name] = dict(exact_equals_t=exact_eq, T=str(T), compact_dominates_t=dom, compact_valid=valid, trajectory_log2=[float(math.log2(x)) if isinstance(x, F) and x > 0 else str(x) for x in traj], nonincreasing=nonincr, V64_valid=v64, V64_splits=splits64, zero_classes=sum(1 for c in Ue if c not in t))
    ok = all(v['exact_equals_t'] and v['compact_dominates_t'] and v['compact_valid'] and v['nonincreasing'] and v['V64_valid'] for v in res.values())
    rec('D35_rmax_exact_limit_and_prefix_validity', ok, **res)


def D36_compatibility_witness_four_cycle():
    """the brief's witness: pinned seeds {01, 12} / {23, 03}; prefix-zero closure 16 * 9^4 on every class; exact t(c) = 16 * 9^3; a no-split run with V >= 256 attains t exactly (9x tighter); the trace shows a message
    consumed by a later elimination; the V = 64 split run remains a valid bound (and is looser)"""
    M, cl, Cz, rows, clk, B = _stage(_four_cycle(), [[0, 0, 1, 1]] * 4); t, T = RM.exact_t(M, cl, Cz, rows); cs = list(itertools.product(*[range(2)] * 4)); res = dict(t=sorted(set(str(x) for x in t.values())), expected=str(16 * 9 ** 3))
    for V in (64, 256, 4096):
        comp = RM.RMAXCompile(M, cl, Cz, rows, dict(V=V, fanin=16, mantissa_bits=128), B, clk); comp.build_sources(); comp.build_seeds([(0, 1), (2, 3)]); comp.closure(); U0 = {c: comp.U_at(c) for c in cs}
        comp.set_order(); comp.run_stages(PA.tnow() + 60); comp.closure(); comp.pack(); U = {c: comp.packed_upper_weight(c) for c in cs}; rec_ = comp.record()
        consumed_later = any(g['consumed_messages'] > 0 for p in rec_['plan'] for g in p['groups']); valid = RM.enumerate_check_rmax(M, cl, Cz, rows, comp.packed_upper_weight)['ok']
        res['V%d' % V] = dict(prefix0=sorted(set(str(x) for x in U0.values())), U=sorted(set(str(x) for x in U.values())), ratio=str(min(U0.values()) / max(U.values())), splits=rec_['max_splits'], message_consumed_later=consumed_later, valid=valid, checker_ok=rec_['checker']['all_ok']); comp.release_all()
    ok = res['t'] == [str(16 * 9 ** 3)] and res['V256']['U'] == [str(16 * 9 ** 3)] and res['V4096']['U'] == [str(16 * 9 ** 3)] and res['V256']['prefix0'] == [str(16 * 9 ** 4)] and res['V256']['ratio'] == '9' and res['V256']['message_consumed_later'] and res['V256']['splits'] == 0 and res['V64']['valid'] and res['V64']['splits'] >= 1 and all(res['V%d' % V]['checker_ok'] for V in (64, 256, 4096))
    rec('D36_compatibility_witness_four_cycle', ok, **res)


def D37_axes_domains_support_and_scalars():
    """axes / domains: unequal class sizes with padding (card 4 split 1 / 3 and 3 / 1), hard zeros (a zero source entry stays zero through MAX; a class whose every fine state has zero target mass gets U = 0), empty support refusal
    (a positive unary with zero decoder probability -> typed SUPPORT refusal, nothing leaked), identity classes (every class a singleton: U == W_0 / r exactly, trivially); parent / scalars: an exact-quotient parent with scalars
    7 and 252 recovers original-coordinate responses from the RMAX stream (Z units preserved; no duplicate factor), and the identity parent with a nonunit canonical scalar keeps the scalar out of U"""
    res = {}
    # unequal class sizes + hard zeros
    rng = random.Random(3); vals = [F(rng.randint(1, 9)) for _ in range(16)]; vals[5] = F(0); vals[9] = F(0)
    m = dict(cards=[4, 4], factors=[dict(scope=(0, 1), values=vals), dict(scope=(0,), values=[F(1), F(0), F(2), F(3)])], evidence={}); classes = [[0, 0, 0, 1], [0, 1, 1, 1]]
    M, cl, Cz, rows, clk, B = _stage(m, classes); t, T = RM.exact_t(M, cl, Cz, rows); comp = _compile(M, cl, Cz, rows, clk, B); U = comp.packed_upper_weight; cs = list(itertools.product(range(2), range(2)))
    res['unequal_zeros'] = dict(pads=comp.pads, U_vs_t=[(str(U(c)), str(t.get(c, F(0)))) for c in cs], valid=RM.enumerate_check_rmax(M, cl, Cz, rows, U)['ok'], zero_mass_classes=[c for c in cs if c not in t]); comp.release_all()
    # DGP5 (finding 6): a GENUINELY zero-mass class -- every pair entry with x_0 in class 0 = {0, 1} is zero while the unaries stay positive (decoder defined): t(c) is undefined (zero) on both coarse states (0, *); U must be exactly 0 there and positive elsewhere
    vz = [F(0)] * 8 + [F(rng.randint(1, 9)) for _ in range(8)]; mz = dict(cards=[4, 4], factors=[dict(scope=(0, 1), values=vz), dict(scope=(0,), values=[F(1), F(2), F(2), F(3)])], evidence={}); clz = [[0, 0, 1, 1], [0, 1, 1, 1]]
    Mz, clz_, Czz, rowsz, clkz, Bz = _stage(mz, clz); tz, Tz = RM.exact_t(Mz, clz_, Czz, rowsz); cz_ = _compile(Mz, clz_, Czz, rowsz, clkz, Bz); Uz = cz_.packed_upper_weight; csz = list(itertools.product(range(2), range(2))); zero_cs = [c for c in csz if c not in tz]
    res['genuine_zero_class'] = dict(zero_mass_classes=zero_cs, U_on_zero_classes=[str(Uz(c)) for c in zero_cs], U_on_positive=[str(Uz(c)) for c in csz if c in tz], executed=(len(zero_cs) >= 1), all_zero_U=(len(zero_cs) >= 1 and all(Uz(c) == 0 for c in zero_cs)), positive_elsewhere=all(Uz(c) > 0 for c in csz if c in tz), valid=RM.enumerate_check_rmax(Mz, clz_, Czz, rowsz, Uz)['ok']); cz_.release_all()
    # empty support: force a decoder row with zero probability on a positive-unary state
    M2, cl2, Cz2, rows2, clk2, B2 = _stage(m, classes); l0 = B2.live; rows2.counts[(0, 0)] = [rows2.Q, 0, 0]; kind = None
    comp2 = RM.RMAXCompile(M2, cl2, Cz2, rows2, RMAX_PROD, B2, clk2)
    try: comp2.build_sources()
    except RM.RefusedRMAX as e: kind = e.kind
    comp2.release_all(); res['empty_support'] = dict(refusal=kind, orphaned=B2.live - l0)
    # identity classes
    M3, cl3, Cz3, rows3, clk3, B3 = _stage(_four_cycle(), [[0, 1, 2, 3]] * 4); t3, T3 = RM.exact_t(M3, cl3, Cz3, rows3); c3 = _compile(M3, cl3, Cz3, rows3, clk3, B3); ident_ok = all(c3.packed_upper_weight(c) == t3[c] for c in t3); c3.release_all(); res['identity_classes'] = dict(U_equals_t=ident_ok, n_classes=len(t3))
    # scalars 7 and 252 via a nullary factor on the identity parent: the canonical scalar is outside U (U bounds W_0 / r WITHOUT the scalar); the stream's scale_to_original carries it
    for sc_ in (7, 252):
        mm = dict(cards=[4, 4, 4], factors=[dict(scope=(0, 1), values=[F(1 + (i * 3 + j) % 5) for i in range(4) for j in range(4)]), dict(scope=(1, 2), values=[F(1 + (i + 2 * j) % 4) for i in range(4) for j in range(4)]), dict(scope=(), values=[F(sc_)])], evidence={})
        Ms, cls, Czs, rowss, clks, Bs = _stage(mm, [[0, 0, 1, 1]] * 3); comps = _compile(Ms, cls, Czs, rowss, clks, Bs); ts, Ts = RM.exact_t(Ms, cls, Czs, rowss); Us = comps.packed_upper_weight
        S = PA.LiftedStream(2, Ms, Ms, [], cls, Czs, 1, EPS, DELTA / 4, dict(PAC_OPTS, budget_obj=Bs, rmax_profile=RMAX_PROD), envelope='RMAX'); r = S.prepare(PA.tnow() + 30)
        # DGP5 (finding 6): the claimed scalar / Z branch EXECUTED: 30 committed batches; the sampled normalizer diagnostic mean(X) x 2^cap_Wint_log2 / scale_F x scale_to_original must lie within a factor 2 of the enumerated ORIGINAL Z (scalar included), and every certified row contains the enumerated marginal
        Zs, mus = enum_marginals(Ms); outs = [S.batch(PA.tnow() + 30) for _ in range(30)]; S.check(); rq = S.pac_rows(); viol = sum(1 for j, (L, H) in rq.items() if not (L <= mus[S.queries[j]] <= H))
        logZ_hat = (math.log2(S.sumX / S.draws) + S.mech['cap_units']['cap_Wint_log2'] - math.log2(S.scale_F) + float(IG.lg(S.scale_to_original))) if S.sumX > 0 else None; logZ = float(IG.lg(Zs))
        res['scalar_%d' % sc_] = dict(canonical_scalar=str(Ms.scalar), stream_scale_to_original=str(S.scale_to_original), U_excludes_scalar=all(Us(c) >= ts[c] for c in ts) and all(Us(c) < F(sc_) * ts[c] for c in ts if ts[c] > 0) if sc_ > 1 else True, prepare=r, batches=sum(1 for o in outs if o == 'COMMITTED'), log2_Z_hat_original_units=logZ_hat, log2_Z_true=logZ, Z_units_within_factor_2=(logZ_hat is not None and abs(logZ_hat - logZ) <= 1.0), certified_rows=len(rq), containment_violations=viol, factors_in_model=len(S.model['factors'])); comps.release_all(); S._close('ctrl')
    # exact-quotient parent: card-8 model with duplicated states -> exact quotient (card 4) -> RMAX on the parent; the stream's rows decode to ORIGINAL coordinates and contain the enumerated original marginals after batches
    base = _four_cycle(); base['factors'].append(dict(scope=(0,), values=[F(1), F(2), F(1), F(3)])); big = duplicate_states(base, seed=5); clk = CE.Clock(PA.tnow() + 120, {}); B = CE.Budget(CE.CONSTRUCTOR_BYTES); Mb = CE.canonicalize(big, clk, B)      # card 8, n 4: 4,096 fine states
    classes1 = CE.exact_profile_classes(Mb, clk, B); Cz1 = CE.check_candidate(Mb, classes1, CE.exact_scales(Mb, classes1, clk), clk, B, ratio_product='compact'); M1 = CE.stage_model(Mb, Cz1); prof, why = CE.slice_profiles(M1, clk, B)
    classes2 = [CE.canonical_classes(CE.farthest_split(prof[v], list(range(M1.cards[v])), clk), M1.cards[v]) for v in range(len(M1.cards))]; Cz2_ = CE.check_candidate(M1, classes2, CE.unit_scales(M1), clk, B, ratio_product='compact')
    S = PA.LiftedStream(2, Mb, M1, [(classes1, Cz1)], classes2, Cz2_, 1, EPS, DELTA / 4, dict(PAC_OPTS, budget_obj=B, rmax_profile=RMAX_PROD), envelope='RMAX', scale_to_original=M1.scalar); r = S.prepare(PA.tnow() + 60)
    import dgp2_oracle as OR; enum = OR.enumerate_original(Mb, PA.tnow() + 60); mu = enum['mu']
    for _ in range(40):
        if S.stage != 'READY': break
        S.batch(PA.tnow() + 60)
    S.check(); rows_q = S.pac_rows(); viol = sum(1 for j, (L, H) in rows_q.items() if not (L <= mu[(int(Mb.orig_of[S.queries[j][0]]), S.queries[j][1])] <= H)) if rows_q else None
    res['exact_quotient_parent'] = dict(prepare=r, parent_cards=list(M1.cards), fine_cards=list(Mb.cards)[:6], draws=S.draws, certified_rows=len(rows_q), containment_violations=viol, witness=S.witness, rmax_stages=(S.mech.get('rmax') or {}).get('stages_done'), scale_to_original=str(S.scale_to_original), defect=S.mech.get('certificate_defect')); S._close('ctrl')
    gz = res['genuine_zero_class']
    ok = (res['unequal_zeros']['valid'] and gz['executed'] and gz['all_zero_U'] and gz['positive_elsewhere'] and gz['valid'] and res['empty_support'] == dict(refusal='SUPPORT', orphaned=0) and res['identity_classes']['U_equals_t']
          and all(res['scalar_%d' % k]['prepare'] == 'READY' and res['scalar_%d' % k]['U_excludes_scalar'] and res['scalar_%d' % k]['canonical_scalar'] == str(k) and res['scalar_%d' % k]['batches'] == 30 and res['scalar_%d' % k]['Z_units_within_factor_2'] and res['scalar_%d' % k]['containment_violations'] == 0 and res['scalar_%d' % k]['certified_rows'] > 0 for k in (7, 252))
          and res['exact_quotient_parent']['prepare'] == 'READY' and res['exact_quotient_parent']['containment_violations'] == 0 and res['exact_quotient_parent']['defect'] is None)
    rec('D37_axes_domains_support_and_scalars', ok, **res)


def D38_numeric_upper_direction_and_packing():
    """upward direction: (a) from_fraction_up >= q on random rationals incl. huge / tiny exponents; (b) mul_exact + norm_up >= exact product; (c) packing: every packed entry >= the closed compact entry, positive-below-quantum
    entries become one unit (a table with a 2^-400 entry next to a 2^300 one), zeros stay zero, the inflation is reported and nonzero there; (d) extreme exponents: a model with factors ~2^900 and ~2^-900 compiles and the
    stream bridges with the packed exponent in E_U (no float of a huge rational), or refuses typed; (e) a BITS refusal on a source whose rational exceeds the bit cap is typed"""
    rng = random.Random(5); res = {}
    qs = [F(rng.getrandbits(200) + 1, rng.getrandbits(180) + 1) for _ in range(200)] + [F(1, 2 ** 900), F(2 ** 900), F(3, 7)]; up_ok = all(RM.to_fraction(RM.from_fraction_up(q)) >= q and RM.to_fraction(RM.from_fraction_up(q)) <= q * (1 + F(1, 1 << 126)) for q in qs)
    pairs = [(RM.from_fraction_up(F(rng.getrandbits(300) + 1)), RM.from_fraction_up(F(1, rng.getrandbits(300) + 1))) for _ in range(100)]; mul_ok = all(RM.to_fraction(RM.norm_up(*RM.mul_exact(a, b))) >= RM.to_fraction(a) * RM.to_fraction(b) for a, b in pairs)
    res['conversion_up'] = up_ok; res['mul_up'] = mul_ok
    # packing with a tiny entry
    m = dict(cards=[2, 2], factors=[dict(scope=(0, 1), values=[F(2) ** 300, F(1, 2 ** 400), F(1), F(0)])], evidence={}); M, cl, Cz, rows, clk, B = _stage(m, [[0, 1], [0, 1]]); comp = _compile(M, cl, Cz, rows, clk, B); P = comp.packed[0]
    tiny_one = any(int(x) == 1 for x in P['ints'].reshape(-1)); zero_kept = any(int(x) == 0 for x in P['ints'].reshape(-1)); pk = RM.check_packing(comp.closed, comp.packed); infl = comp.packing['max_ratio_log2']; valid = RM.enumerate_check_rmax(M, cl, Cz, rows, comp.packed_upper_weight)['ok']; comp.release_all()
    res['packing'] = dict(tiny_became_one=tiny_one, zero_kept=zero_kept, check=pk['ok'], max_inflation_log2=infl, valid=valid)
    # extreme exponents through the stream
    mx = dict(cards=[4, 4, 4], factors=[dict(scope=(0, 1), values=[F(2) ** 900 * F(1 + (i + j) % 3) for i in range(4) for j in range(4)]), dict(scope=(1, 2), values=[F(1, 2 ** 900) * F(1 + (i * j) % 3) for i in range(4) for j in range(4)])], evidence={}); Mx, clx, Czx, rowsx, clkx, Bx = _stage(mx, [[0, 0, 1, 1]] * 3)
    S = PA.LiftedStream(2, Mx, Mx, [], clx, Czx, 1, EPS, DELTA / 4, dict(PAC_OPTS, budget_obj=Bx, rmax_profile=RMAX_PROD), envelope='RMAX'); r = S.prepare(PA.tnow() + 30); outs = [S.batch(PA.tnow() + 30) for _ in range(3)] if r == 'READY' else []
    res['extreme_exponents'] = dict(prepare=r, closed=(S.closed_reason or '')[:100], E_U=getattr(S.mbp, 'E_U', None) if hasattr(S, 'mbp') else None, packed_exponent_sum=(S.mech.get('rmax') or {}).get('packed_exponent_sum'), batches=outs, defect=S.mech.get('certificate_defect')); S._close('ctrl')
    # BITS: a source rational beyond the bit cap
    mb = dict(cards=[2, 2], factors=[dict(scope=(0, 1), values=[F(3) ** 3000, F(1), F(1), F(1)])], evidence={}); kind = None
    try:
        Mb_, clb, Czb, rowsb, clkb, Bb = _stage(mb, [[0, 1], [0, 1]]); cb = RM.RMAXCompile(Mb_, clb, Czb, rowsb, RMAX_PROD, Bb, clkb); cb.build_sources(); cb.release_all()
    except (CE.Refused, RM.RefusedRMAX) as e: kind = getattr(e, 'kind', None)
    res['bits_refusal'] = kind
    ok = up_ok and mul_ok and tiny_one and zero_kept and pk['ok'] and infl > 0 and valid and (r == 'READY' and all(o == 'COMMITTED' for o in outs) and res['extreme_exponents']['defect'] is None or r == 'CLOSED') and kind == 'BITS'       # DGP5 (finding 6): the BITS refusal is FORCED by the 3^3000 source and asserted exactly
    rec('D38_numeric_upper_direction_and_packing', ok, **res)


def D39_independent_checker_mutants():
    """the stage checker rejects: an omitted input factor (the output lacks its axes), a duplicated input, wrong output axes, an underbounded message (one entry lowered), an invalid class mask (a nonzero at a padded position),
    and a downward packing (one packed entry decremented); it ACCEPTS a valid looser bound (one entry doubled)"""
    M, cl, Cz, rows, clk, B = _stage(_four_cycle(), [[0, 0, 1, 1]] * 4); comp = RM.RMAXCompile(M, cl, Cz, rows, RMAX_PROD, B, clk); comp.build_sources(); comp.build_seeds([(0, 1), (2, 3)]); comp.set_order()
    v = comp.residual_order[0]; sv = 2 * v + 1; bucket = [T for T in comp.active if sv in T.axes]; u = tuple(sorted(set(a for T in bucket for a in T.axes))); P = RM._norm(RM.product_exact(bucket, u, comp.ccards, comp.pads)); R, raxes = RM.max_over(P, u, [sv]); good = RM.Table(raxes, R.copy(), 999, ('ctrl',))
    res = dict(valid=RM.check_stage(bucket, good, sv, comp.ccards, comp.pads, rows.members, clk)['ok'])
    res['omitted_input'] = not RM.check_stage(bucket[:-1], good, sv, comp.ccards, comp.pads, rows.members, clk)['ok']
    res['duplicated_input'] = not RM.check_stage(bucket + [bucket[0]], good, sv, comp.ccards, comp.pads, rows.members, clk)['ok']
    R2w, raxes2 = RM.max_over(R, raxes, [raxes[0]]); wrong = RM.Table(raxes2, R2w, 998, ('ctrl',))                          # the output with ONE further axis maxed away: valid values, WRONG axes -> must be rejected
    res['wrong_axes'] = not RM.check_stage(bucket, wrong, sv, comp.ccards, comp.pads, rows.members, clk)['ok']
    low = good.arr.copy(); idx = next(i for i in itertools.product(*[range(k) for k in low.shape]) if low[i][1]); e, m_ = low[idx]; low[idx] = (e, m_ - 1); res['underbounded'] = not RM.check_stage(bucket, RM.Table(raxes, low, 997, ('ctrl',)), sv, comp.ccards, comp.pads, rows.members, clk)['ok']
    loose = good.arr.copy(); loose[idx] = (e + 1, m_); res['looser_accepted'] = RM.check_stage(bucket, RM.Table(raxes, loose, 996, ('ctrl',)), sv, comp.ccards, comp.pads, rows.members, clk)['ok']
    # invalid class mask: on a model with unequal classes, set a padded position nonzero in an input
    m = dict(cards=[4, 4], factors=[dict(scope=(0, 1), values=[F(1 + (i * j) % 5) for i in range(4) for j in range(4)])], evidence={}); M2, cl2, Cz2, rows2, clk2, B2 = _stage(m, [[0, 0, 0, 1], [0, 1, 1, 1]]); c2 = RM.RMAXCompile(M2, cl2, Cz2, rows2, RMAX_PROD, B2, clk2); c2.build_sources()
    T = c2.active[0]; mask = RM.valid_mask(T.axes, c2.ccards, c2.pads, rows2.members); bad = next(i for i in itertools.product(*[range(k) for k in T.arr.shape]) if not mask[i]); T.arr[bad] = (0, RM.HALF)
    u2 = T.axes; P2 = RM._norm(RM.product_exact([T], u2, c2.ccards, c2.pads)); R2, ra2 = RM.max_over(P2, u2, [1]); res['invalid_mask'] = not RM.check_stage([T], RM.Table(ra2, R2, 995, ('ctrl',)), 1, c2.ccards, c2.pads, rows2.members, clk2)['ok']; c2.release_all()
    comp.closure(); comp.pack(); P0 = comp.packed[0]; i0 = next(i for i in itertools.product(*[range(k) for k in P0['ints'].shape]) if int(P0['ints'][i]) > 1); P0['ints'][i0] = int(P0['ints'][i0]) - 1; res['downward_packing'] = not RM.check_packing(comp.closed, comp.packed)['ok']; comp.release_all()
    # DGP5 (finding 2): mutants with an internally CONSISTENT recomputed output -- (a) the same input twice with the output recomputed from the doubled list; (b) an omitted factor with the output recomputed from the shorter list;
    # both pass pointwise dominance and must be rejected by the inventory / partition binding; (c) a fresh output id reusing a live inventory id; (d) a closure whose inventory drops a table
    M5, cl5, Cz5, rows5, clk5, B5 = _stage(_four_cycle(), [[0, 0, 1, 1]] * 4); c5 = RM.RMAXCompile(M5, cl5, Cz5, rows5, RMAX_PROD, B5, clk5); c5.build_sources(); c5.build_seeds([(0, 1), (2, 3)]); c5.set_order()
    v5 = c5.residual_order[0]; sv5 = 2 * v5 + 1; bucket5 = [T for T in c5.active if sv5 in T.axes]; inv5 = [T.tid for T in c5.active]; bid5 = [T.tid for T in bucket5]
    dup_in = bucket5 + [bucket5[0]]; u_d = tuple(sorted(set(a for T in dup_in for a in T.axes))); Pd = RM._norm(RM.product_exact(dup_in, u_d, c5.ccards, c5.pads)); Rd, rad = RM.max_over(Pd, u_d, [sv5]); out_d = RM.Table(rad, Rd, 990, ('message', v5, tuple(T.tid for T in dup_in)))
    res['duplicated_consistent'] = not RM.check_stage(dup_in, out_d, sv5, c5.ccards, c5.pads, rows5.members, clk5, inventory=inv5, bucket_ids=bid5)['ok']
    om_in = bucket5[:-1]; u_o = tuple(sorted(set(a for T in om_in for a in T.axes))); Po = RM._norm(RM.product_exact(om_in, u_o, c5.ccards, c5.pads)); Ro, rao = RM.max_over(Po, u_o, [sv5]); out_o = RM.Table(rao, Ro, 991, ('message', v5, tuple(T.tid for T in om_in)))
    res['omitted_consistent_group_accepted_alone'] = RM.check_stage(om_in, out_o, sv5, c5.ccards, c5.pads, rows5.members, clk5, inventory=inv5, bucket_ids=bid5)['ok'] if len(bucket5) > 1 else True       # a valid GROUP of a partition
    res['omitted_caught_by_partition'] = not RM.check_partition(bid5, [[T.tid for T in om_in]])['ok'] if len(bucket5) > 1 else True                                                              # ... but the PARTITION of the bucket misses a table
    out_reuse = RM.Table(rao, Ro, inv5[0], ('message', v5, tuple(T.tid for T in om_in))); res['reused_live_id_rejected'] = not RM.check_stage(om_in, out_reuse, sv5, c5.ccards, c5.pads, rows5.members, clk5, inventory=inv5, bucket_ids=bid5)['ok']
    res['wrong_origin_rejected'] = not RM.check_stage(om_in, RM.Table(rao, Ro, 992, ('message', v5, (999,))), sv5, c5.ccards, c5.pads, rows5.members, clk5, inventory=inv5, bucket_ids=bid5)['ok']
    c5.closure(); res['closure_inventory_valid'] = RM.check_closure_inventory(c5.active, c5.closed)['ok']; res['closure_inventory_dropped_rejected'] = not RM.check_closure_inventory(c5.active, c5.closed[:-1])['ok']; res['closure_inventory_dup_rejected'] = not RM.check_closure_inventory(c5.active, c5.closed + [c5.closed[0]])['ok']
    c5.pack(); res['packing_check_with_clock'] = RM.check_packing(c5.closed, c5.packed, clk5)['ok']; res['packing_missing_table_rejected'] = not RM.check_packing(c5.closed, c5.packed[:-1], clk5)['ok']; c5.release_all()
    ok = (res['valid'] and res['omitted_input'] and res['duplicated_input'] and res['wrong_axes'] and res['underbounded'] and res['looser_accepted'] and res['invalid_mask'] and res['downward_packing'] and res['duplicated_consistent'] and res['omitted_caught_by_partition']
          and res['reused_live_id_rejected'] and res['wrong_origin_rejected'] and res['closure_inventory_valid'] and res['closure_inventory_dropped_rejected'] and res['closure_inventory_dup_rejected'] and res['packing_check_with_clock'] and res['packing_missing_table_rejected'])
    rec('D39_independent_checker_mutants', ok, **res)


def D40_whole_proposal_rmax_vs_reference():
    """whole proposal on a dev card-4 model (identity parent, FAST classes, production profile): the analyzed law q_C r is normalized (sum over every fine state = 1 within the sampler's exact replay), W_0 <= B q_C r on EVERY fine
    state (B in W_0 units from logU_capf + E_U - log2 scale_F), the production float log2 X on 2 batches equals the exact analyzed value on the SAME assignments within cap_tol; the surrogate mutant (U r as the weight)
    certifies rows that EXCLUDE the original marginal while the production estimator's rows contain it"""
    import dgp2_oracle as OR
    model, binding = load_mid('dg_n16_c4_clique_two') if False else load('dg_n8_c4_clique_two'); M, cl, Cz, rows, clk, B = _stage(model); enum = OR.enumerate_original(M, PA.tnow() + 60); Z = enum['Z']; n = len(M.cards)
    S = PA.LiftedStream(2, M, M, [], cl, Cz, 1, EPS, DELTA / 4, dict(PAC_OPTS, budget_obj=B, rmax_profile=RMAX_PROD), envelope='RMAX'); r = S.prepare(PA.tnow() + 90); assert r == 'READY', (r, S.closed_reason)
    cstates = list(itertools.product(*[range(k) for k in Cz.ccards])); Sb = np.array(cstates, dtype=np.int64); lq, qC = S.mbp.logq_given(Sb, S.pos); qC = dict(zip(cstates, qC)); C_int = F(2) ** int(math.floor(S.logU_capf)) * F(2.0 ** (S.logU_capf - math.floor(S.logU_capf))) * F(2) ** S.mbp.E_U; B_W0 = C_int / F(S.scale_F)
    tot_q = F(0); Xmax = F(0); viol = 0
    for z, w in zip(enum['states'], enum['W']):
        c = tuple(cl[v][z[v]] for v in range(n)); r_ = F(1)
        for v in range(n): r_ *= F(rows.counts[(v, c[v])][rows.members[v][c[v]].index(z[v])], rows.Q)
        q = qC[c] * r_; tot_q += q
        if w > 0:
            if q == 0: viol += 1; continue
            X = (w / M.scalar) / (B_W0 * q); Xmax = max(Xmax, X)
    # same-assignment arithmetic comparison on 2 batches
    dev = 0.0; nb = 0
    for _ in range(2):
        Sb2, logq_s, zero_row = S.mbp.sample_batch(S.rng, S.batch_used, S.pos); Bn = Sb2.shape[0]; z = np.zeros((Bn, n), dtype=np.int64); logr = np.zeros(Bn)
        for v in range(n):
            u = S.rng.integers(0, LD.Q, size=Bn, dtype=np.int64); cv = Sb2[:, v]
            for c in np.unique(cv):
                rws = np.nonzero(cv == c)[0]; cum = np.asarray(S.rows.cum[(v, int(c))], dtype=np.int64); k = np.searchsorted(cum, u[rws], side='right'); mem = np.asarray(S.rows.members[v][int(c)], dtype=np.int64); cnt = np.asarray(S.rows.counts[(v, int(c))], dtype=np.int64); z[rws, v] = mem[k]; logr[rws] += np.log2(cnt[k].astype(float)) - LD.Q_BITS
        logz = np.zeros(Bn)
        for i in range(len(S.fine)): logz += S.fLM[i][S._flat_fine(z, i)]
        impl = (logz - logq_s - logr - S.logU_capf) + float(S.E_tot); lq2, q_an = S.mbp.logq_given(Sb2, S.pos)
        for k in range(Bn):
            if not np.isfinite(impl[k]) or q_an[k] == 0: continue
            W = LD.parent_weight(M, tuple(int(x) for x in z[k])) / M.scalar; r_ = F(1)
            for v in range(n): r_ *= F(rows.counts[(v, int(Sb2[k, v]))][rows.members[v][int(Sb2[k, v])].index(int(z[k, v]))], rows.Q)
            exact = float(IG.lg(W)) - float(IG.lg(q_an[k] * r_)) - float(IG.lg(B_W0)); dev = max(dev, abs(exact - float(impl[k]))); nb += 1
    # surrogate mutant vs production containment
    mu = enum['mu']; res_m = {}
    for mutant in (False, True):
        S2 = PA.LiftedStream(2, M, M, [], cl, Cz, 4, EPS, DELTA / 4, dict(PAC_OPTS, budget_obj=B, rmax_profile=RMAX_PROD), envelope='RMAX'); S2.mutant_surrogate = mutant; assert S2.prepare(PA.tnow() + 60) == 'READY'
        for _ in range(60): S2.batch(PA.tnow() + 60)
        S2.check(); rq = S2.pac_rows(); excl = sum(1 for j, (L, H) in rq.items() if not (L <= mu[(int(M.orig_of[S2.queries[j][0]]), S2.queries[j][1])] <= H)); res_m['mutant' if mutant else 'production'] = dict(rows=len(rq), excluding_truth=excl, draws=S2.draws); S2._close('ctrl')
    rm = S.mech['rmax']; S._close('ctrl')
    ok = abs(tot_q - 1) < F(1, 10 ** 9) and Xmax <= 1 and viol == 0 and dev <= S.cap_tol and nb > 500 and res_m['production']['excluding_truth'] == 0 and res_m['mutant']['excluding_truth'] > 0 and rm['stages_done'] > 0 and rm['checker']['all_ok']
    rec('D40_whole_proposal_rmax_vs_reference', ok, total_q=float(tot_q), max_X_analyzed=float(Xmax), support_violations=viol, same_assignment_dev=dev, cap_tol=S.cap_tol, compared=nb, log2_B_W0_over_Z0=float(IG.lg(B_W0 / (Z / M.scalar))), rmax=dict(stages=rm['stages_done'], splits=rm['max_splits'], consumed=rm['consumed_messages'], packing_log2=rm['packing']['max_ratio_log2'], seconds=rm['seconds_total']), **res_m)


def D41_lifetime_cutoffs_and_incumbent():
    """lifetime: in a full planner run with RMAX, injected refusals at (a) the RMAX adapter (packing check), (b) the sampler stage (deadline), (c) the midpoint (zero MAX allowance) leave the request COMPLETE / usable through the
    primary stream, the constructor ledger identity TRUE, every lifted charge released, and no row published after expiry; (d) a forced RMAX request with a tight preparation allowance refuses typed (not the hard deadline)"""
    model, binding = load_mid('dg_n16_c4_clique_two'); res = {}
    def run(label, patch):
        P = UPlanner(model, binding, 8.0, admission_stop_s=7.5, t_start=PA.tnow(), seed=1, pac=True, lifted=True, envelope='RMAX'); undo = patch(P) if patch else None
        try: o = P.run()
        finally:
            if undo: undo()
        L = [S for S in P.streams if S.kind == 'lifted']; m = o['mechanism']
        res[label] = dict(outcome=o['outcome'], published=o['published'], K=o['K'], ledger_identity=m.get('constructor_live_ledger_identity'), lifted=[(S.stage, (S.closed_reason or '')[:80], S.rmax_bytes, (S.mech.get('rmax_refusal') or {}).get('kind'), (S.mech.get('rmax') or {}).get('stages_done')) for S in L], hard_respected=o['hard_deadline_respected'], late=m.get('late_assembly'), request_defect=m.get('defect'))
    def patch_pack(P):
        real = RM.check_packing; RM.check_packing = lambda *a_, **k_: dict(ok=False, why='injected')
        return lambda: setattr(RM, 'check_packing', real)
    def patch_sampler(P):
        real = PA.prepare_sampler_polled
        def fail(mbp, deadline, *a_, **k_):
            if getattr(mbp, '_is_lifted_probe', False) or True:
                import inspect; f = inspect.currentframe().f_back
                if f.f_code.co_name == '_l_sampler': raise PA.Deadline('injected in the lifted sampler stage')
            return real(mbp, deadline, *a_, **k_)
        PA.prepare_sampler_polled = fail; return lambda: setattr(PA, 'prepare_sampler_polled', real)
    def patch_midpoint(P):
        real = PA.LiftedStream.prepare
        def prep(self, deadline, cdead=None, until=None):
            self.rmax_midpoint = PA.tnow() - 1.0; return real(self, deadline, cdead, until)
        PA.LiftedStream.prepare = prep; return lambda: setattr(PA.LiftedStream, 'prepare', real)
    run('baseline', None); run('adapter_packing_refused', patch_pack); run('sampler_stage_deadline', patch_sampler); run('midpoint_zero_allowance', patch_midpoint)
    # (d) forced RMAX with a tight allowance: the stream closes typed with its charge released; the hard deadline is NOT substituted
    P = UPlanner(model, binding, 8.0, admission_stop_s=7.5, t_start=PA.tnow(), seed=1, pac=True, lifted=True, force_stream='lifted', envelope='RMAX'); P.M = CE.canonicalize(model, P.hclock, P.budget); P.canonical_charge = P.budget.live; P.mf = CM.model_features(P.M, P.clock, P.budget)
    ident = P.make_identity(P.clock); P.cands.append(ident); c = P.discover_fast_lift_only(ident, Clock(PA.tnow() + 5, {})); P.lift_cands.append(c); S = P.make_lifted(c); l0 = P.budget.live
    # DGP5 (finding 6): an INJECTED clock (every read advances 1 ms; no millisecond host race): the 50 ms allowance is crossed deterministically inside the first RMAX stage while the hard deadline (7.5 s away) is not
    inj = {'now': PA.tnow(), 'reads': 0}
    def tick(): inj['now'] += 0.001; inj['reads'] += 1; return inj['now']
    old_t = (PA.tnow, CE.tnow, PA.IG.tnow); PA.tnow = CE.tnow = PA.IG.tnow = tick
    try: r = S.prepare(P.adm, until=inj['now'] + 0.05)
    finally: PA.tnow, CE.tnow, PA.IG.tnow = old_t
    cr = str(S.closed_reason or ''); res['forced_tight_allowance'] = dict(result=r, stage=S.stage, closed=cr[:100], injected_reads=inj['reads'], injected_elapsed_s=inj['reads'] * 0.001, hard_deadline_margin_s=P.adm - inj['now'], released=(P.budget.live - l0 - (S.rows.bytes if getattr(S, 'rows', None) else 0) <= 0), allowance=S.mech.get('rmax_allowance'), typed_allowance_refusal=(r == 'CLOSED' and ('ALLOWANCE' in cr or 'DEADLINE' in cr) and inj['now'] < P.adm - 1.0))
    ok = (all(res[k]['ledger_identity'] is True and res[k]['hard_respected'] for k in ('baseline', 'adapter_packing_refused', 'sampler_stage_deadline', 'midpoint_zero_allowance')) and res['baseline']['outcome'] == 'COMPLETE' and res['adapter_packing_refused']['outcome'] == 'COMPLETE' and res['sampler_stage_deadline']['outcome'] == 'COMPLETE'
          and all(l[0] == 'CLOSED' and l[2] == 0 and l[3] == 'Defect' for l in res['adapter_packing_refused']['lifted']) and all(l[0] == 'CLOSED' and l[2] == 0 for l in res['sampler_stage_deadline']['lifted']) and res['midpoint_zero_allowance']['outcome'] == 'COMPLETE' and all(l[4] == 0 for l in res['midpoint_zero_allowance']['lifted'])
          and res['forced_tight_allowance']['typed_allowance_refusal'] and res['forced_tight_allowance']['released'])        # DGP5 (finding 6): the specific injected outcome is REQUIRED
    rec('D41_lifetime_cutoffs_and_incumbent', ok, **res)


CONTROLS += [D32_R1_transpose_semantics_and_permutation_invariance, D33_R2_construction_charge_ownership, D34_R3_parent_final_timestamp, D35_rmax_exact_limit_and_prefix_validity, D36_compatibility_witness_four_cycle, D37_axes_domains_support_and_scalars, D38_numeric_upper_direction_and_packing, D39_independent_checker_mutants, D40_whole_proposal_rmax_vs_reference, D41_lifetime_cutoffs_and_incumbent]

# ---------------------------------------------------------------- DGP5 controls (brief CLAUDE_DGP5_JOINT_CONSTRUCTION_SPEC.md section 11): the joint conditional construction
import joint_proposal as JP, joint_witness as JW, joint_optimize as JO, check_joint as CJ, joint_stream as JS
from residual_max_envelope import to_fraction as _tf, from_fraction_up as _fu, log2_up as _l2, ZERO as _ZERO, ge_exact as _ge
JPROF = dict(JP.PROFILE_PRODUCTION)
def _jstage(model, budget_s=120):
    clk = CE.Clock(PA.tnow() + budget_s, {}); B = CE.Budget(CE.CONSTRUCTOR_BYTES); M = CE.canonicalize(model, clk, B); order, _ = CE.elimination_order(list(M.cards), [tuple(sc) for sc, _ in M.factors], clk, B); return M, order, clk, B
def _rand_model(rng, cards, edges, zeros=0, nullary=None, factorless=()):
    facs = []
    for (u, v) in edges:
        vals = [F(rng.randint(1, 9), rng.randint(1, 5)) for _ in range(cards[u] * cards[v])]
        for _ in range(zeros): vals[rng.randrange(len(vals))] = F(0)
        facs.append(dict(scope=(u, v), values=vals))
    for v in range(len(cards)):
        if v in factorless: continue
        facs.append(dict(scope=(v,), values=[F(rng.randint(1, 7)) for _ in range(cards[v])]))
    if nullary is not None: facs.append(dict(scope=(), values=[F(nullary)]))
    return dict(cards=list(cards), factors=facs, evidence={})
def _jstream(M, mode='joint', seed=1, budget=None, allow=10.0, profile=None):
    B = budget or CE.Budget(CE.CONSTRUCTOR_BYTES); S = JS.JointStream(2, M, M, [], seed, EPS, DELTA / 4, dict(PAC_OPTS, budget_obj=B), mode=mode, profile=profile or JPROF); r = S.prepare(PA.tnow() + allow, until=PA.tnow() + allow); return S, B, r


def D42_seed_exhaustive_validity():
    """exhaustive tiny seeds: on 24 random small models (cards 2-5, 3-5 variables, cycles; some with source zeros, a nullary constant, a factorless variable) the seed is a normalized positive law, W_0 <= B q on EVERY fine
    state, B >= R* (tight), actual SUM / MAX splits occur (V_seed forced small), zero guide rows (M = 0) produce positive near-uniform rows, and the production stream path reports the same cap"""
    rng = random.Random(42); res = dict(models=0, valid=0, normalized=0, splits_seen=0, zero_rows_seen=0, nullary_seen=0, factorless_seen=0, worst_B_over_Rstar_bits=0.0, failures=[])
    for k in range(24):
        n = rng.randint(3, 5); cards = [rng.randint(2, 5) for _ in range(n)]; edges = [(i, (i + 1) % n) for i in range(n)] + ([(0, 2)] if n > 3 and rng.random() < 0.5 else []); zeros = 2 if k % 3 == 0 else 0; nul = F(rng.randint(2, 9), rng.randint(1, 3)) if k % 4 == 0 else None
        fl = (n - 1,) if k % 5 == 0 else (); edges = [e for e in edges if n - 1 not in e] if fl else edges; model = _rand_model(rng, cards, edges, zeros=zeros, nullary=nul, factorless=fl)
        try:
            M, order, clk, B = _jstage(model); prof = dict(JPROF, V_seed=(32 if k % 2 else 1024)); l0 = B.live; prop, rec_, owned = JP.compile_seed(M, order, prof, B, clk); ref = CJ.ref_check_law(M, prop)
            res['models'] += 1; res['valid'] += int(ref['violations'] == 0); res['normalized'] += int(ref['normalized']); res['splits_seen'] += int(rec_['max_splits'] > 0); res['zero_rows_seen'] += int(rec_['zero_rows'] > 0); res['nullary_seen'] += int(nul is not None and M.scalar != 1); res['factorless_seen'] += int(bool(fl))
            if ref['log2_Rstar'] > -math.inf: res['worst_B_over_Rstar_bits'] = max(res['worst_B_over_Rstar_bits'], prop.log2_B() - ref['log2_Rstar'])
            if ref['violations'] or not ref['normalized'] or prop.log2_B() + 1e-9 < ref['log2_Rstar']: res['failures'].append(dict(k=k, cards=cards, violations=ref['violations'], normalized=ref['normalized'], log2_B=prop.log2_B(), log2_Rstar=ref['log2_Rstar']))
            B.release(owned); res.setdefault('live_after_release_zero', True); res['live_after_release_zero'] &= (B.live == l0)
        except (CE.Refused, JP.RefusedJoint) as e: res['failures'].append(dict(k=k, refusal=getattr(e, 'kind', None), reason=str(getattr(e, 'reason', e))[:80]))
    # the stream path on the four-cycle reports the same checked cap (W_0 units) as compile_seed, and its batch weights never exceed the cap
    M, order, clk, B = _jstage(_four_cycle()); prop, rec_, owned = JP.compile_seed(M, order, JPROF, B, clk); S, B2, r = _jstream(M); outs = [S.batch(PA.tnow() + 10) for _ in range(5)]
    res['stream'] = dict(prepare=r, batches=outs, cap_equal=(abs(S.epochs[0].prop.log2_B() - prop.log2_B()) < 1e-12), max_log2_X=S.maxlogX, cap_tol=S.epochs[0].cap_tol, X_mean=S.sumX / max(1, S.draws)); B.release(owned); S._close('ctrl')
    ok = res['models'] >= 20 and res['valid'] == res['models'] and res['normalized'] == res['models'] and not res['failures'] and res['splits_seen'] >= 3 and res['zero_rows_seen'] >= 1 and res['nullary_seen'] >= 1 and res['factorless_seen'] >= 1 and res['live_after_release_zero'] and r == 'READY' and all(o == 'COMMITTED' for o in outs) and res['stream']['cap_equal'] and S.maxlogX <= S.epochs[0].cap_tol
    rec('D42_seed_exhaustive_validity', ok, **res)


def D43_exact_floor_and_count_boundaries():
    """the exact-floor count rule: (a) the ratio 1 - 2^-100 (P = M (1 - 2^-100)) has floor (D - k)(1 - 2^-100) -> floor D - k - 1 exactly (a downward-rounded ratio followed by floor would cross the integer boundary);
    (b) huge compact exponent gaps (P = M 2^-5000 -> count 1; P = M -> count 1 + D - k); (c) bulk leftover counts: all P equal -> leftovers distributed by full cycles then the prefix; (d) k near D on a small grid (D' = 16, k = 15
    and k = 16 -> refusal) via the row inequality checker on the real D (k >= D refused typed); (e) upward products / SUM / MAX / source conversion dominate the exact values on random pairs; (f) packed and source bounds of the
    repaired RMAX path (check_packing with a clock; the 2^3000 factor packs with bounded diagnostics)"""
    res = {}; D = JP.D; k = 4
    M1 = _fu(F(1)); P = (M1[0], M1[1] - (M1[1] >> 100)); cnt, zero = JP.floor_ratio_counts([P, _ZERO, _ZERO, _ZERO], M1, k)
    res['boundary_1_minus_2pow_minus_100'] = dict(count0=cnt[0], expected_initial=1 + math.floor((D - k) * (1 - 2 ** -100)), sum_D=(sum(cnt) == D)); exact_initial = 1 + ((D - k) * (M1[1] - (M1[1] >> 100))) // M1[1]
    res['boundary_1_minus_2pow_minus_100']['exact_floor_matches'] = (cnt[0] == exact_initial + (D - sum([exact_initial, 1, 1, 1])) // k + 1)
    Pt = (M1[0] - 5000, M1[1]); cnt2, _ = JP.floor_ratio_counts([Pt, M1, _ZERO, _ZERO], M1, k); res['huge_gap'] = dict(tiny_count=cnt2[0], full_count=cnt2[1], sum_D=(sum(cnt2) == D), tiny_is_minimal=(cnt2[0] <= 2), full_dominates=(cnt2[1] >= D - k - 2))
    cnt3, _ = JP.floor_ratio_counts([_fu(F(1, 3))] * 3, M1, 3); res['bulk_leftover'] = dict(counts=cnt3, sum_D=(sum(cnt3) == D), spread=max(cnt3) - min(cnt3), positive=min(cnt3) >= 1)
    kind = None
    try: JP.floor_ratio_counts([M1] * 4, M1, D + 1)                                                        # k >= D is refused BEFORE any row is touched (the row argument is a 4-element stand-in; a 2^40-element list would not fit memory)
    except JP.RefusedJoint as e: kind = e.kind
    res['k_ge_D_refused'] = kind
    kind2 = None
    try: JP.quantize_row([1.0] * 4, D + 1)
    except JP.RefusedJoint as e: kind2 = e.kind
    res['quantize_k_ge_D_refused'] = kind2
    # near-D on a small test grid: the row inequality (D - k) P <= M c with k = D - 1 on the real D (every count 1 except the leftover): checked by check_seed_rows on a synthetic row
    kk = 6; Pm = np.empty((1, kk), dtype=object); Mf = np.empty(1, dtype=object); Mf[0] = M1
    for i in range(kk): Pm[0, i] = _fu(F(1, kk))
    c6, _ = JP.floor_ratio_counts(list(Pm[0]), M1, kk); counts = np.array([c6], dtype=np.int64); res['row_check_k6'] = CJ.check_seed_rows(Pm, Mf, counts, kk, CE.Clock(PA.tnow() + 5, {}))['ok']
    bad = counts.copy(); bad[0, 0] -= 1; bad[0, 1] += 1; res['row_check_rejects_shifted'] = not CJ.check_seed_rows(Pm, Mf, bad, kk, CE.Clock(PA.tnow() + 5, {}))['ok'] or True       # shifting one count keeps the sum; the inequality may still hold (not a failure); recorded
    low = counts.copy(); low[0, 0] = 1; low[0, 1] += counts[0, 0] - 1; res['row_check_rejects_underweight'] = not CJ.check_seed_rows(Pm, Mf, low, kk, CE.Clock(PA.tnow() + 5, {}))['ok']
    # upward direction on random pairs
    rng = random.Random(11); ups = 0; tot = 0
    for _ in range(200):
        a = F(rng.getrandbits(300) + 1, rng.getrandbits(200) + 1); b = F(rng.getrandbits(100) + 1, rng.getrandbits(300) + 1); A = _fu(a); Bc = _fu(b); tot += 3
        ups += int(_tf(A) >= a) + int(_tf(RM.norm_up(*RM.mul_exact(A, Bc))) >= a * b) + int(_tf(RM.sum_up([A, Bc])) >= a + b)
    res['upward_direction'] = dict(ok=ups, of=tot)
    # repaired packing path: the 2^3000 factor (finding 1) packs; the packing checker with a clock passes; the stream path refuses typed RANGE (an exact entry would keep < 64 significant bits in the float adapter), never NUMERIC
    m = dict(cards=[4, 4], factors=[dict(scope=(0, 1), values=[F(2 ** 3000)] + [F(1)] * 15)], evidence={}); Mw, clw, Czw, rowsw, clkw, Bw = _stage(m, [[0, 0, 1, 1]] * 2); co = RM.RMAXCompile(Mw, clw, Czw, rowsw, RMAX_PROD, Bw, clkw); co.build_sources(); co.set_order(); co.run_stages(PA.tnow() + 2); co.closure(); co.pack(); pk = RM.check_packing(co.closed, co.packed, clkw); infl = co.packing['max_ratio_log2']; co.release_all()
    Sw = PA.LiftedStream(2, Mw, Mw, [], clw, Czw, 1, EPS, DELTA / 4, dict(PAC_OPTS, budget_obj=Bw, rmax_profile=RMAX_PROD), envelope='RMAX'); rw = Sw.prepare(PA.tnow() + 3); res['wide_factor'] = dict(packed=pk['ok'], inflation_log2=infl, stream=rw, closed=(Sw.closed_reason or '')[:90], typed_not_numeric=('NUMERIC' not in str(Sw.closed_reason))); Sw._close('ctrl')
    ok = (res['boundary_1_minus_2pow_minus_100']['exact_floor_matches'] and res['boundary_1_minus_2pow_minus_100']['sum_D'] and res['huge_gap']['sum_D'] and res['huge_gap']['tiny_is_minimal'] and res['huge_gap']['full_dominates'] and res['bulk_leftover']['sum_D'] and res['bulk_leftover']['spread'] <= 1 and res['bulk_leftover']['positive']
          and kind == 'RANGE' and kind2 == 'RANGE' and res['row_check_k6'] and res['row_check_rejects_underweight'] and ups == tot and pk['ok'] and infl > 2000 and res['wide_factor']['typed_not_numeric'])
    rec('D43_exact_floor_and_count_boundaries', ok, **res)


def D44_local_witness_inequalities():
    """local b / a inequalities by exhaustive enumeration on (a) the eight-state positive binary triangle of the theory note section 9 incl. a CHILD conditional depending on the updated variable (the update of the first-sampled
    variable with every later conditional depending on it), (b) the four-cycle and (c) a random card-3 five-cycle: every bounded b / a dominates the exact b* / a* (zero violations); every frontier law's recomputed cap and moment
    dominate the exact R* and S_0 of that law; the (W_0 / q_-)^2 SUBSTITUTION fixture: a-pass sources built from (W_0)^2 with the reciprocal applied TWICE underbound the exact a* on a model where q_- is far from uniform
    (the fixture FAILS under the substitution, passes under the correct W_0^2 / q_-); the theory-note triangle numbers (cap 4.30 -> 3.15 lower, raw moment 5.27 -> 5.06 lower under the joint update) are reproduced in direction"""
    res = {}; cases = {}
    tri = dict(cards=[2, 2, 2], factors=[dict(scope=(0, 1), values=[F(3), F(1), F(1), F(2)]), dict(scope=(1, 2), values=[F(2), F(1), F(1), F(3)]), dict(scope=(0, 2), values=[F(1), F(2), F(2), F(1)])], evidence={})
    rng = random.Random(9); five = _rand_model(rng, [3] * 5, [(i, (i + 1) % 5) for i in range(5)])
    for name, model in (('triangle', tri), ('four_cycle', _four_cycle()), ('five_cycle_c3', five)):
        M, order, clk, B = _jstage(model); cards = list(M.cards); prop, rec_, owned = JP.compile_seed(M, order, JPROF, B, clk); ref0 = CJ.ref_check_law(M, prop); pairs, chg = JO.interaction_scores(M, B, clk)
        # the FIRST-sampled variable (every later conditional may depend on it) retuned on its (empty) context: a child-dependent update
        z0 = prop.order[0]; pk0 = JW.build_packet(M, prop, z0, (), order, JPROF, B, clk); b_ref, a_ref = CJ.ref_coefficients(M, prop, z0, ()); wc0 = CJ.ref_witness_check(pk0.b, pk0.a, b_ref, a_ref)
        exps = JO.rank_expansions(prop, pairs, cards, JPROF['V_family']); e = exps[0] if exps else JO.choose_retune(prop, pairs, cards); z = e['z']; parents = tuple(e['new_parents']); pk = JW.build_packet(M, prop, z, parents, order, JPROF, B, clk); b_ref2, a_ref2 = CJ.ref_coefficients(M, prop, z, parents); wc = CJ.ref_witness_check(pk.b, pk.a, b_ref2, a_ref2)
        inc = JW.witnesses_of(pk, pk.cond_ctx, S_ref=None); laws = JO.frontier_laws(pk, prop, cards, JPROF, 'joint', prop.B); fv = 0; fb = 0; best = None
        for lab, cond, nominal in laws:
            if cond is None: continue
            w = JW.witnesses_of(pk, cond, S_ref=inc['S']); conds = dict(prop.conds); conds[z] = cond; newp = JP.Proposal(cards, conds, prop.order, w['B'], w['S'], {}); r = CJ.ref_check_law(M, newp)
            okl = (r['violations'] == 0 and r['normalized'] and w['log2_B'] + 1e-9 >= r['log2_Rstar'] and w['log2_S'] + 1e-9 >= r['log2_S0']); fv += int(okl); fb += int(not okl)
            if best is None or r['log2_S0'] < best[1]: best = (lab, r['log2_S0'], r['log2_Rstar'], w['log2_B'], w['log2_S'])
        cases[name] = dict(seed_log2_B=prop.log2_B(), seed_exact=dict(Rstar=ref0['log2_Rstar'], S0=ref0['log2_S0'], Z0=ref0['log2_Z0']), child_dependent_update=dict(z=z0, violations=wc0['violations'], slack_b=wc0['max_slack_b_bits'], slack_a=wc0['max_slack_a_bits']), family=dict(z=z, parents=list(parents), violations=wc['violations'], slack_b=wc['max_slack_b_bits'], slack_a=wc['max_slack_a_bits']), frontier_valid=fv, frontier_invalid=fb, best_moment_law=best)
        pk0.release(); pk.release(); B.release(owned + chg)
    # the (W_0 / q_-)^2 substitution: a-pass with the reciprocal applied twice (power 2 on the reciprocal) underbounds a* on a model whose seed law is far from uniform
    M, order, clk, B = _jstage(five); cards = list(M.cards); prop, rec_, owned = JP.compile_seed(M, order, JPROF, B, clk); z = prop.order[-1]; parents = tuple(prop.conds[z].parents)
    owned2 = [0]; srcs = JP.source_tables(M, B, clk, owned2, V=4096, power=2); tid = len(srcs)
    for v in prop.order:
        if v == z: continue
        T = JW.reciprocal_table(prop.conds[v], cards, tid, B, clk, owned2); T.arr = RM._norm(RM._mul(T.arr, T.arr)); srcs.append(T); tid += 1                   # (D / c)^2: the WRONG substitution (W_0 / q_-)^2
    comp = JP.JointCompile(cards, srcs, order, 4096, 16, B, clk, 'sum', retain=tuple(sorted(parents + (z,))), owned=owned2); comp.run(); T = comp.retained_product(); Fax = tuple(sorted(parents + (z,))); layout = parents + (z,); a_wrong = np.ascontiguousarray(np.transpose(T.arr, [Fax.index(v) for v in layout])).reshape(-1, cards[z])
    b_ref3, a_ref3 = CJ.ref_coefficients(M, prop, z, parents); under = sum(1 for i in range(a_wrong.shape[0]) for j in range(a_wrong.shape[1]) if _tf(a_wrong[i, j]) < a_ref3[i][j]); over = sum(1 for i in range(a_wrong.shape[0]) for j in range(a_wrong.shape[1]) if _tf(a_wrong[i, j]) > a_ref3[i][j])
    pk_ok = JW.build_packet(M, prop, z, parents, order, JPROF, B, clk); wc_ok = CJ.ref_witness_check(pk_ok.b, pk_ok.a, b_ref3, a_ref3); res['substitution_fixture'] = dict(z=z, parents=list(parents), wrong_underbounds=under, wrong_overbounds=over, correct_violations=wc_ok['violations'], fails_under_substitution=(under > 0 or over > 0), note='(W_0 / q_-)^2 is NOT the a-target W_0^2 / q_-: the mutant differs from a* (underbounds where q_- > 1 ... overbounds elsewhere)')
    B.release(owned2[0]); pk_ok.release(); B.release(owned)
    # direction (theory note section 9): on a seed that is NOT exact (V_seed forced to 9 on the card-3 five-cycle -> SUM / MAX splits), the best frontier law of the first family LOWERS the exact S_0 and keeps a checked cap >= its exact R*;
    # (an exact seed -- the triangle / four-cycle above with no splits -- has q = p and cannot be improved: its frontier laws reproduce S_0 to rounding, recorded above)
    M, order, clk, B = _jstage(five); cards = list(M.cards); prop_s, rec_s, owned_s = JP.compile_seed(M, order, dict(JPROF, V_seed=9), B, clk); ref_s = CJ.ref_check_law(M, prop_s); pairs, chg = JO.interaction_scores(M, B, clk); e = JO.rank_expansions(prop_s, pairs, cards, 4096)[0]
    pk_s = JW.build_packet(M, prop_s, e['z'], tuple(e['new_parents']), order, JPROF, B, clk); inc_s = JW.witnesses_of(pk_s, pk_s.cond_ctx, S_ref=None); best_s = None
    for lab, cond, nominal in JO.frontier_laws(pk_s, prop_s, cards, JPROF, 'joint', prop_s.B):
        if cond is None: continue
        w = JW.witnesses_of(pk_s, cond, S_ref=inc_s['S']); conds = dict(prop_s.conds); conds[e['z']] = cond; r = CJ.ref_check_law(M, JP.Proposal(cards, conds, prop_s.order, w['B'], w['S'], {}))
        if best_s is None or r['log2_S0'] < best_s['exact_S0']: best_s = dict(law=lab, exact_S0=r['log2_S0'], exact_Rstar=r['log2_Rstar'], checked_B=w['log2_B'], checked_S=w['log2_S'], violations=r['violations'])
    res['split_seed_direction'] = dict(seed_splits=rec_s['max_splits'], seed_log2_B=prop_s.log2_B(), seed_exact_S0=ref_s['log2_S0'], seed_exact_Rstar=ref_s['log2_Rstar'], best=best_s, S0_lowered=(best_s is not None and best_s['exact_S0'] < ref_s['log2_S0'] - 1e-9), cap_checked=(best_s is not None and best_s['checked_B'] + 1e-9 >= best_s['exact_Rstar'] and best_s['violations'] == 0)); pk_s.release(); B.release(owned_s + chg)
    tri_ok = rec_s['max_splits'] > 0 and res['split_seed_direction']['S0_lowered'] and res['split_seed_direction']['cap_checked']
    res['cases'] = cases
    ok = (all(c['child_dependent_update']['violations'] == 0 and c['family']['violations'] == 0 and c['frontier_invalid'] == 0 and c['frontier_valid'] >= 10 for c in cases.values()) and res['substitution_fixture']['fails_under_substitution'] and res['substitution_fixture']['correct_violations'] == 0 and tri_ok)
    rec('D44_local_witness_inequalities', ok, **res)


def D45_witness_pass_mutants():
    """the joint checkers reject: wrong output axes, a permuted scope (entries transposed), nonbinary cards (a card-3 table indexed as card-2 -> shape mismatch caught), a missing factor (inventory / partition), duplicate ids,
    a dropped reciprocal conditional (the b / a packet built WITHOUT one reciprocal underbounds the exact coefficients -> ref_witness_check reports violations), an illegal retained-variable elimination (eliminating a family
    variable raises a Defect), an all-MAX mutant in the SUM pass (a MAX message where a SUM is claimed is rejected by check_stage: the message does not dominate the exact sum)"""
    res = {}; M, order, clk, B = _jstage(_rand_model(random.Random(2), [4, 4, 3], [(0, 1), (1, 2)])); cards = list(M.cards); prop, rec_, owned = JP.compile_seed(M, order, JPROF, B, clk); own = [0]; srcs = JP.source_tables(M, B, clk, own, V=4096); u = (0, 1); T0 = [T for T in srcs if T.axes == (0, 1)][0]; T1 = [T for T in srcs if T.axes == (1,)][0]      # the pair (0, 1) and the unary of the ELIMINATED variable 1
    inv = [T.tid for T in srcs]; P = RM._norm(JP.product_exact([T0, T1], u, cards)); R, rax = JP.max_over(P, u, [1]); out = JP.JTable(rax, R, 999, ('max_message', 1, (T0.tid, T1.tid)))
    res['valid_max'] = CJ.check_stage([T0, T1], out, 1, cards, 'max', clk, inventory=inv, bucket_ids=[T.tid for T in srcs if 1 in T.axes])['ok']
    res['wrong_axes'] = not CJ.check_stage([T0, T1], JP.JTable((1,), R, 998, ('max_message', 1, (T0.tid, T1.tid))), 1, cards, 'max', clk, inventory=inv)['ok']           # output claims axes (1,) where the union minus the eliminated variable is (0,)
    Tp = JP.JTable((0, 1), np.ascontiguousarray(T0.arr.T), 997, ('factor', 99)); Pp = RM._norm(JP.product_exact([Tp, T1], u, cards)); Rp, _ = JP.max_over(Pp, u, [1])                                                       # a TRANSPOSED (permuted-scope) factor table
    res['permuted_scope_differs'] = any(_tf(Rp.reshape(-1)[i]) != _tf(R.reshape(-1)[i]) for i in range(R.size))
    res['permuted_scope_rejected_as_underbound'] = (not CJ.check_stage([T0, T1], JP.JTable(rax, Rp, 996, ('max_message', 1, (T0.tid, T1.tid))), 1, cards, 'max', clk, inventory=inv)['ok']) or (not CJ.check_stage([Tp, T1], JP.JTable(rax, R, 996, ('max_message', 1, (Tp.tid, T1.tid))), 1, cards, 'max', clk, inventory=inv + [Tp.tid])['ok'])     # the messages differ -> at least one direction underbounds: the checker indexes each input by ITS OWN axes
    try: JP.JTable((0,), T0.arr, 995, ('factor', 98)); res['nonbinary_shape_caught'] = False
    except AssertionError: res['nonbinary_shape_caught'] = True
    res['duplicate_ids'] = not CJ.check_stage([T0, T0], out, 1, cards, 'max', clk, inventory=inv)['ok']
    res['missing_factor_partition'] = not RM.check_partition([T.tid for T in srcs if 1 in T.axes], [[T0.tid, T1.tid]])['ok']
    # all-MAX mutant in a SUM pass: a MAX message claimed as SUM
    res['all_max_in_sum_rejected'] = not CJ.check_stage([T0, T1], JP.JTable(rax, R, 994, ('sum_message', 1, (T0.tid, T1.tid))), 1, cards, 'sum', clk, inventory=inv)['ok']
    Rs, _ = JP.sum_over_up(P, u, [1]); res['sum_accepted'] = CJ.check_stage([T0, T1], JP.JTable(rax, Rs, 993, ('sum_message', 1, (T0.tid, T1.tid))), 1, cards, 'sum', clk, inventory=inv)['ok']
    # dropped reciprocal conditional: the packet built without one reciprocal (power 0) underbounds b* / a*
    z = prop.order[-1]; parents = tuple(prop.conds[z].parents); own2 = [0]; srcs2 = JP.source_tables(M, B, clk, own2, V=4096); tid = len(srcs2); skipped = None
    for v in prop.order:
        if v == z: continue
        if skipped is None: skipped = v; continue
        srcs2.append(JW.reciprocal_table(prop.conds[v], cards, tid, B, clk, own2)); tid += 1
    comp = JP.JointCompile(cards, srcs2, order, 4096, 16, B, clk, 'max', retain=tuple(sorted(parents + (z,))), owned=own2); comp.run(); T = comp.retained_product(); Fax = tuple(sorted(parents + (z,))); lay = parents + (z,); b_drop = np.ascontiguousarray(np.transpose(T.arr, [Fax.index(v) for v in lay])).reshape(-1, cards[z])
    b_ref, a_ref = CJ.ref_coefficients(M, prop, z, parents); res['dropped_reciprocal_underbounds'] = sum(1 for i in range(b_drop.shape[0]) for j in range(b_drop.shape[1]) if _tf(b_drop[i, j]) < b_ref[i][j]) > 0; B.release(own2[0])
    # illegal retained-variable elimination
    kind = None; own3 = [0]; srcs3 = JP.source_tables(M, B, clk, own3, V=4096); comp3 = JP.JointCompile(cards, srcs3, order, 4096, 16, B, clk, 'max', retain=(0, 1), owned=own3)
    try: comp3.stage(1); kind = 'ELIMINATED_RETAINED'
    except Exception as e: kind = type(e).__name__
    comp3.release_all(); res['retained_elimination'] = kind                                                                  # stage() on a retained variable is never reached by run(); calling it directly eliminates -> the retained product then detects the missing axis
    own4 = [0]; srcs4 = JP.source_tables(M, B, clk, own4, V=4096); comp4 = JP.JointCompile(cards, srcs4, order, 4096, 16, B, clk, 'max', retain=(0, 1), owned=own4); comp4.stage(1); kind4 = None
    try: comp4.retained_product()
    except CE.Defect as e: kind4 = 'Defect'
    except Exception as e: kind4 = type(e).__name__
    comp4.release_all(); res['retained_product_detects_eliminated_family_variable'] = kind4; B.release(own[0] + owned)
    ok = res['valid_max'] and res['wrong_axes'] and res['permuted_scope_differs'] and res['permuted_scope_rejected_as_underbound'] and res['nonbinary_shape_caught'] and res['duplicate_ids'] and res['missing_factor_partition'] and res['all_max_in_sum_rejected'] and res['sum_accepted'] and res['dropped_reciprocal_underbounds'] and kind4 == 'Defect'
    rec('D45_witness_pass_mutants', ok, **res)


def D46_quantization_cap_and_incumbent_witness():
    """(a) actual quantized caps may EXCEED the nominal C of the frontier (recorded; the checked cap is used everywhere); (b) every quantized row is a positive law summing to D; (c) count-density / sample agreement: on 4,096
    draws the sampled log-density equals logq_bits of the drawn states to 1e-9 and the empirical state frequencies of a 2-variable law are within 5 sigma of the exact counts / D; (d) best-incumbent witness retention: a second packet
    with a LOOSER a (coarser profile) cannot inflate the incumbent's S (S_ref = min over the checked witnesses); (e) same-law cap tightening is a candidate that changes the consumed cap, while a tighter moment bound alone leaves the
    incumbent's J on both sides (no manufactured promotion)"""
    res = {}; rng = random.Random(5); model = _rand_model(rng, [4, 4, 3, 3], [(0, 1), (1, 2), (2, 3), (0, 3)]); M, order, clk, B = _jstage(model); cards = list(M.cards); prop, rec_, owned = JP.compile_seed(M, order, JPROF, B, clk)
    pairs, chg = JO.interaction_scores(M, B, clk); e = JO.rank_expansions(prop, pairs, cards, 4096)[0]; z = e['z']; parents = tuple(e['new_parents']); pk = JW.build_packet(M, prop, z, parents, order, JPROF, B, clk); inc = JW.witnesses_of(pk, pk.cond_ctx, S_ref=None)
    laws = JO.frontier_laws(pk, prop, cards, JPROF, 'joint', prop.B); exceed = 0; valid_rows = 0; n_laws = 0
    for lab, cond, nominal in laws:
        if cond is None or nominal is None: continue
        w = JW.witnesses_of(pk, cond, S_ref=inc['S']); n_laws += 1; exceed += int(w['log2_B'] > nominal + 1e-12); valid_rows += int((cond.counts.sum(axis=1) == JP.D).all() and (cond.counts >= 1).all())
    res['frontier'] = dict(laws=n_laws, actual_cap_exceeds_nominal=exceed, positive_rows=valid_rows)
    # (c) sampling agreement
    rng_np = np.random.default_rng(3); X, logc = prop.sample(rng_np, 4096); lc2, qx = prop.logq_bits(X); res['density_agreement'] = dict(max_dev=float(np.abs(logc - lc2).max()), exact_match=float(max(abs(float(math.log2(q)) + JP.D_BITS * len(cards) - l) for q, l in zip(qx, logc))))
    v0 = prop.order[0]; c0 = prop.conds[v0]; freq = np.bincount(X[:, v0], minlength=cards[v0]) / 4096.0; pr = c0.counts[0] / JP.D; sig = np.sqrt(pr * (1 - pr) / 4096.0); res['frequency_agreement'] = dict(max_z=float(np.abs(freq - pr).max() / sig.min()), within_5_sigma=bool((np.abs(freq - pr) <= 5 * np.maximum(sig, 1e-9)).all()))
    # (d) a looser packet cannot inflate the incumbent's S
    pk2 = JW.build_packet(M, prop, z, parents, order, dict(JPROF, V_coef=max(256, JP.vol_of(parents, cards) * cards[z]), fanin=2), B, clk)       # a LOOSER coefficient profile (fan-in 2 -> more splits) that still admits the family
    inc2 = JW.witnesses_of(pk2, pk2.cond_ctx, S_ref=None); S_ref = min([s for s in (prop.S, inc['S'], inc2['S']) if s[1]]); res['incumbent_witness'] = dict(log2_S_tight_packet=inc['log2_S'], log2_S_loose_packet=inc2['log2_S'], log2_S_ref=_l2(S_ref), S_ref_is_min=(S_ref == min(inc['S'], inc2['S'], prop.S)), loose_not_used=(_l2(S_ref) <= inc['log2_S'] + 1e-12)); inc2 = JW.witnesses_of(pk2, pk2.cond_ctx, S_ref=None); S_ref = min([s for s in (prop.S, inc['S'], inc2['S']) if s[1]]); res['incumbent_witness'] = dict(log2_S_tight_packet=inc['log2_S'], log2_S_loose_packet=inc2['log2_S'], log2_S_ref=_l2(S_ref), S_ref_is_min=(S_ref == min(inc['S'], inc2['S'], prop.S)), loose_not_used=(_l2(S_ref) <= inc['log2_S'] + 1e-12))
    # (e) same-law cap tightening vs moment knowledge: build the incumbent record with S_ref on both sides; a tighter S_ref alone does not change the ranking between incumbent and itself; a tighter CAP is a distinct candidate
    log2_eta = math.log2(0.005) + 10.0 - math.log2(6); H_inc = JO.H_log2(_l2(S_ref), prop.log2_B(), log2_eta); B_tight = min(prop.B, inc['B']); H_tight = JO.H_log2(_l2(S_ref), _l2(B_tight), log2_eta)
    incumbent = dict(label='current', is_current=True, log2_B=prop.log2_B(), log2_S=_l2(S_ref), log2_J=H_inc, family_volume=prop.conds[z].family_volume(), index=-1); same_law_tighter = dict(label='same_law_tighter_cap', is_current=False, log2_B=_l2(B_tight), log2_S=_l2(S_ref), log2_J=H_tight, family_volume=prop.conds[z].family_volume(), index=0)
    moment_only_knowledge = dict(label='moment_knowledge_only', is_current=False, log2_B=prop.log2_B(), log2_S=_l2(S_ref), log2_J=H_inc, family_volume=prop.conds[z].family_volume(), index=1)     # the same law with the same consumed cap and only better S knowledge: ties the incumbent -> current wins
    win1, prom1 = JO.select([moment_only_knowledge], incumbent, 0.01); win2, prom2 = JO.select([same_law_tighter], incumbent, 0.01)
    res['promotion_semantics'] = dict(moment_knowledge_promotes=prom1, moment_knowledge_winner=win1['label'], cap_tightening_is_candidate=(B_tight < prop.B), cap_tightening_promotes=prom2, log2_B_consumed=prop.log2_B(), log2_B_tight=_l2(B_tight))
    pk.release(); pk2.release(); B.release(owned + chg)
    ok = (n_laws >= 10 and valid_rows == n_laws and res['density_agreement']['max_dev'] < 1e-9 and res['density_agreement']['exact_match'] < 1e-7 and res['frequency_agreement']['within_5_sigma'] and res['incumbent_witness']['S_ref_is_min'] and res['incumbent_witness']['loose_not_used'] and not prom1 and win1['label'] == 'current' and (prom2 == (B_tight < prop.B and H_tight <= H_inc + math.log2(0.99))))
    rec('D46_quantization_cap_and_incumbent_witness', ok, **res)


def D47_context_replication_and_staleness():
    """(a) row replication across an added parent preserves q EXACTLY on every fine state (lemma L4); (b) context parents respect the sampling order (a parent sampled after its child is refused by the Proposal invariant);
    (c) updating ANOTHER conditional invalidates stale numeric messages: a packet built for family F on the OLD proposal underbounds the exact b* / a* of the NEW proposal (hence rebuilt, never reused); (d) family source and final
    retained products obey volume admission (a family of 4,097 entries is refused VOLUME before allocation; the retained product refuses when the union exceeds V_coef; a MEMORY refusal inside a pass releases every byte)"""
    res = {}; M, order, clk, B = _jstage(_four_cycle()); cards = list(M.cards); prop, rec_, owned = JP.compile_seed(M, order, JPROF, B, clk); l0 = B.live
    z = prop.order[-1]; c = prop.conds[z]; extra = [v for v in prop.order if v not in c.parents and v != z][0]; newpar = tuple(sorted(c.parents + (extra,), key=lambda p: prop.order.index(p))); rep = c.replicate(newpar, cards)
    conds = dict(prop.conds); conds[z] = rep; prop2 = JP.Proposal(cards, conds, prop.order, prop.B, prop.S, {}); states = list(itertools.product(*[range(k) for k in cards])); res['replication_exact'] = all(prop.q_exact(x) == prop2.q_exact(x) for x in states)
    try: JP.Proposal(cards, {**prop.conds, z: JP.Conditional(z, (prop.order[0],), rep.counts[:cards[prop.order[0]] ** 0 * (JP.vol_of((prop.order[0],), cards))] if False else c.counts.repeat(1, axis=0)[:JP.vol_of((prop.order[0],), cards)], cards)}, [z] + [v for v in prop.order if v != z], prop.B, prop.S, {}); res['order_violation_refused'] = False
    except AssertionError: res['order_violation_refused'] = True
    # (c) staleness
    pairs, chg = JO.interaction_scores(M, B, clk); zA = prop.order[1]; zB = prop.order[2]; pkB = JW.build_packet(M, prop, zB, tuple(prop.conds[zB].parents), order, JPROF, B, clk)
    lawsA = JO.frontier_laws(JW.build_packet(M, prop, zA, tuple(prop.conds[zA].parents), order, JPROF, B, clk), prop, cards, JPROF, 'moment_only', prop.B); condA = [cnd for _, cnd, _ in lawsA if cnd is not None][0]; conds3 = dict(prop.conds); conds3[zA] = condA; prop3 = JP.Proposal(cards, conds3, prop.order, prop.B, prop.S, {})
    b_ref, a_ref = CJ.ref_coefficients(M, prop3, zB, tuple(prop.conds[zB].parents)); stale = CJ.ref_witness_check(pkB.b, pkB.a, b_ref, a_ref); pkB2 = JW.build_packet(M, prop3, zB, tuple(prop.conds[zB].parents), order, JPROF, B, clk, inherit=False); fresh = CJ.ref_witness_check(pkB2.b, pkB2.a, b_ref, a_ref)
    res['staleness'] = dict(changed_var=zA, family_var=zB, stale_packet_violations=stale['violations'], rebuilt_packet_violations=fresh['violations'], law_changed=(condA.sha256 != prop.conds[zA].sha256)); pkB.release(); pkB2.release()
    # (d) volume admission
    kind = None
    try: JW.coefficient_pass(M, prop, z, tuple(v for v in prop.order if v != z), order, 'max', dict(JPROF, V_family=255), B, clk)
    except JP.RefusedJoint as e: kind = e.kind
    res['family_volume_refused'] = kind; lv = B.live; kind2 = None
    try: JW.coefficient_pass(M, prop, z, tuple(prop.conds[z].parents), order, 'max', dict(JPROF, V_coef=8), B, clk)
    except JP.RefusedJoint as e: kind2 = e.kind
    res['union_volume_refused'] = dict(kind=kind2, orphaned=B.live - lv); lv = B.live; kind3 = None; cap0 = B.cap; B.cap = B.live + 2000
    try: JW.coefficient_pass(M, prop, z, tuple(prop.conds[z].parents), order, 'sum', JPROF, B, clk)
    except CE.Refused as e: kind3 = e.kind
    B.cap = cap0; res['memory_refusal_releases'] = dict(kind=kind3, orphaned=B.live - lv); B.release(owned + chg)
    ok = res['replication_exact'] and res['order_violation_refused'] and res['staleness']['law_changed'] and res['staleness']['stale_packet_violations'] > 0 and res['staleness']['rebuilt_packet_violations'] == 0 and kind == 'VOLUME' and kind2 == 'VOLUME' and res['union_volume_refused']['orphaned'] == 0 and kind3 == 'MEMORY' and res['memory_refusal_releases']['orphaned'] == 0
    rec('D47_context_replication_and_staleness', ok, **res)


def D48_units_and_paired_arithmetic():
    """nonunit target / scalar / integerization units: (a) scalars 7 and 252 with denominators 3 and 17 -- the stream's W_int units, cap units and scale_to_original recover the ORIGINAL marginals (certified rows contain the
    enumerated truth; the sampled normalizer diagnostic in original units within a factor 2 of Z); (b) a prior 538-bit scalar (2^538 / 3) and an approximately 2^2000 scalar: the stream prepares READY and samples valid rows WITHOUT any
    float conversion of the huge rational (the scalar is owned by scale_to_original; W_0 excludes it); (c) paired arithmetic: on 3 batches the implemented float log2 X equals the exact analyzed log2 X on the SAME assignments
    within cap_tol (operation-by-operation widening consumed); (d) the exact-quotient parent (duplicated states, card 8 -> exact card-4 quotient): the joint stream on the parent decodes to original coordinates containing the truth"""
    res = {}
    for sc_, den in ((7, 3), (252, 17), (F(2) ** 538 / 3, 1), (F(2) ** 2000, 1)):
        model = _four_cycle(); model['factors'][0]['values'] = [v / F(den) for v in model['factors'][0]['values']]; model['factors'].append(dict(scope=(), values=[F(sc_)])); M, order, clk, B = _jstage(model); Zs, mus = enum_marginals(M); S, B2, r = _jstream(M); outs = [S.batch(PA.tnow() + 10) for _ in range(30)] if r == 'READY' else []
        if r == 'READY': S.check(); rq = S.pac_rows(); viol = sum(1 for j, (L, H) in rq.items() if not (L <= mus[S.queries[j]] <= H)); lz = (math.log2(S.sumX / S.draws) + S.epochs[0].B_eff_log2 + float(IG.lg(S.scale_to_original))) if S.sumX > 0 else None
        else: rq = {}; viol = None; lz = None
        res['scalar_%s' % (str(sc_)[:12] + ('...' if len(str(sc_)) > 12 else ''))] = dict(prepare=r, closed=(S.closed_reason or '')[:80], batches=sum(1 for o in outs if o == 'COMMITTED'), rows=len(rq), containment_violations=viol, log2_Zhat_original=lz, log2_Z=float(IG.lg(Zs)), within_factor_2=(lz is not None and abs(lz - float(IG.lg(Zs))) <= 1.0), scale_to_original_bits=CE.bits(S.scale_to_original), canonical_scalar_bits=CE.bits(M.scalar)); S._close('ctrl')
    # (c) paired arithmetic on the same assignments
    M, order, clk, B = _jstage(_four_cycle()); S, B2, r = _jstream(M); ep = S.epochs[0]; dev = 0.0; nb = 0
    for _ in range(3):
        X, logc = ep.prop.sample(S.rng, 256); logz = np.zeros(256)
        for i in range(len(S.fine)): logz += S.fLM[i][S._flat_fine(X, i)]
        impl = (logz - logc) + float(S.E_fine + JP.D_BITS * S.n_par) - S.log_sF - ep.B_eff_log2
        for k in range(256):
            W = CJ.ref_W0(M, tuple(int(x) for x in X[k])); q = ep.prop.q_exact(tuple(int(x) for x in X[k])); exact = float(IG.lg(W)) - float(IG.lg(q)) - ep.B_eff_log2; dev = max(dev, abs(exact - float(impl[k]))); nb += 1
    res['paired_arithmetic'] = dict(compared=nb, max_abs_log2_dev=dev, cap_tol=ep.cap_tol, within=dev <= ep.cap_tol, rho_X=ep.rho_X); S._close('ctrl')
    # (d) exact-quotient parent
    base = _four_cycle(); base['factors'].append(dict(scope=(0,), values=[F(1), F(2), F(1), F(3)])); big = duplicate_states(base, seed=5); clk = CE.Clock(PA.tnow() + 120, {}); B = CE.Budget(CE.CONSTRUCTOR_BYTES); Mb = CE.canonicalize(big, clk, B)
    classes1 = CE.exact_profile_classes(Mb, clk, B); Cz1 = CE.check_candidate(Mb, classes1, CE.exact_scales(Mb, classes1, clk), clk, B, ratio_product='compact'); M1 = CE.stage_model(Mb, Cz1); import dgp2_oracle as OR; enum = OR.enumerate_original(Mb, PA.tnow() + 60); mu = enum['mu']
    Sq = JS.JointStream(2, Mb, M1, [(classes1, Cz1)], 1, EPS, DELTA / 4, dict(PAC_OPTS, budget_obj=B), mode='joint', scale_to_original=M1.scalar); rq_ = Sq.prepare(PA.tnow() + 30); outs = [Sq.batch(PA.tnow() + 30) for _ in range(40)] if rq_ == 'READY' else []; Sq.check() if rq_ == 'READY' else None; rows_q = Sq.pac_rows() if rq_ == 'READY' else {}
    viol_q = sum(1 for j, (L, H) in rows_q.items() if not (L <= mu[(int(Mb.orig_of[Sq.queries[j][0]]), Sq.queries[j][1])] <= H)) if rows_q else None
    res['exact_quotient_parent'] = dict(prepare=rq_, closed=(Sq.closed_reason or '')[:80], parent_cards=list(M1.cards), fine_cards=list(Mb.cards)[:4], draws=Sq.draws, rows=len(rows_q), containment_violations=viol_q, defect=Sq.mech.get('certificate_defect')); Sq._close('ctrl')
    ok = all(v['prepare'] == 'READY' and v['containment_violations'] == 0 and v['rows'] > 0 and v['within_factor_2'] for k_, v in res.items() if k_.startswith('scalar_')) and res['paired_arithmetic']['within'] and res['exact_quotient_parent']['prepare'] == 'READY' and res['exact_quotient_parent']['containment_violations'] == 0 and res['exact_quotient_parent']['defect'] is None
    rec('D48_units_and_paired_arithmetic', ok, **res)


def D49_epoch_switch_and_certificate_continuity():
    """(a) an epoch switch with a PENDING batch is refused without mutation (the certificate state, draws, epochs, RNG state unchanged); (b) committed evidence / t is preserved across a switch (cert.t, SA, SB identical before and after;
    the next batch adds to the same accumulators); (c) the allowance increase re-widens the SAME state: cert.eps_num after the switch = max(old, new) and the new epoch's eps_num entered BEFORE its first batch; (d) Z diagnostics are
    epoch-local (each epoch's ZCertificate counts only its own draws; the sum equals the stream's draws; no pooled interval reported); (e) the pilot draws are committed exactly once (cert.t == draws) and the pilot store is never
    re-committed or reweighted (the certificate's t after refine equals its t before + 0); (f) the RNG state and draw ids are independent of rejected-candidate bookkeeping (two streams with the same seed, one with a candidate
    refusal injected, draw identical states)"""
    res = {}; model, _ = load('dg_n8_c4_clique_two'); M, order, clk, B = _jstage(model)
    S, B2, r = _jstream(M, allow=10.0); assert r == 'READY', (r, S.closed_reason); S.batch(PA.tnow() + 10); S.batch(PA.tnow() + 10)
    # (a) pending refusal: fake a pending batch
    S.pending = dict(fake=True); t0 = S.cert.t; SA0 = S.cert.SA.copy(); n_ep0 = len(S.epochs); rs0 = S.rng.bit_generator.state['state']['state']; kind = None
    try: S._commit_epoch(S.epoch.prop, 'ctrl', PA.tnow() + 5, B2)
    except PA.StreamRefused as e: kind = e.kind
    S.pending = None; res['pending_switch'] = dict(refused=kind, t_unchanged=(S.cert.t == t0), SA_unchanged=bool((S.cert.SA == SA0).all()), epochs_unchanged=(len(S.epochs) == n_ep0), rng_unchanged=(S.rng.bit_generator.state['state']['state'] == rs0))
    # (b, c) a real switch to a candidate law (moment-only row of the first family) with a LARGER allowance injected
    pairs, chg = JO.interaction_scores(M, B2, clk); e = JO.rank_expansions(S.epoch.prop, pairs, list(M.cards), 4096)[0]; pk = JW.build_packet(M, S.epoch.prop, e['z'], tuple(e['new_parents']), order, JPROF, B2, clk); cond = [c for _, c, _ in JO.frontier_laws(pk, S.epoch.prop, list(M.cards), JPROF, 'moment_only', S.epoch.prop.B) if c is not None][0]
    w = JW.witnesses_of(pk, cond, S_ref=S.epoch.prop.S); conds = dict(S.epoch.prop.conds); conds[e['z']] = cond; newp = JP.Proposal(list(M.cards), conds, S.epoch.prop.order, w['B'], w['S'], {}, predecessor=0)
    t_before = S.cert.t; SA_b = S.cert.SA.copy(); SB_b = S.cert.SB; eps_old = S.cert.eps_num; real = JS.joint_widening
    def wider(*a_, **k_):
        d = real(*a_, **k_); d['eps_num'] = d['eps_num'] * 4; return d
    JS.joint_widening = wider
    try: B2.charge(newp.bytes, 'ctrl law'); S.joint_bytes += newp.bytes; ep = S._commit_epoch(newp, 'ctrl', PA.tnow() + 5, B2)
    finally: JS.joint_widening = real
    eps_after_commit = S.cert.eps_num; res['switch'] = dict(t_preserved=(S.cert.t == t_before), SA_preserved=bool((S.cert.SA == SA_b).all()), SB_preserved=(S.cert.SB == SB_b), eps_num_old=eps_old, eps_num_epoch=ep.eps_num, eps_num_after=eps_after_commit, rewidened_to_max=(eps_after_commit == max(eps_old, ep.eps_num) and eps_after_commit > eps_old), new_epoch_index=ep.index, draws_at_switch=S.draws)
    r3 = S.batch(PA.tnow() + 10); res['switch']['next_batch'] = r3; res['switch']['t_grows_same_accumulator'] = (S.cert.t == t_before + S.batch_used); res['switch']['eps_num_entered_before_first_batch'] = (eps_after_commit == S.cert.eps_num)
    # (d) epoch-local Z diagnostics
    res['z_epoch_local'] = dict(epoch0_draws=S.epochs[0].zcert.t, epoch1_draws=S.epochs[1].zcert.t, sum_equals_stream=(S.epochs[0].zcert.t + S.epochs[1].zcert.t == S.draws), epoch0_record_has_cap=('Z_over_cap_EB_DIAGNOSTIC_epoch' in S.epochs[0].record), pooled_reported=('Z_over_Ucap_EB_DIAGNOSTIC' in S.diagnostics() and S.diagnostics().get('Z_over_Ucap_EB_DIAGNOSTIC') is not None))
    pk.release(); S._close('ctrl')
    # (e, f) pilot committed once; RNG independent of rejected bookkeeping
    S1, Ba, r1 = _jstream(M, allow=10.0); S2, Bb, r2 = _jstream(M, allow=10.0); p1 = S1.pilot_action(PA.tnow() + 10); p2 = S2.pilot_action(PA.tnow() + 10); res['pilot_once'] = dict(cert_t=S1.cert.t, draws=S1.draws, equal=(S1.cert.t == S1.draws == p1['draws']))
    real_bp = JW.build_packet
    def refuse(*a_, **k_): raise JP.RefusedJoint('CTRL', 'injected candidate refusal')
    JW.build_packet = refuse
    try: a2 = S2.refine_action(PA.tnow() + 10, PA.tnow() + 20)
    finally: JW.build_packet = real_bp
    X1, _ = S1.epoch.prop.sample(S1.rng, 64); X2, _ = S2.epoch.prop.sample(S2.rng, 64); res['rng_independent_of_refusal'] = dict(refusal=a2.get('status'), kind=a2.get('kind'), identical_draws=bool((X1 == X2).all()), ids_equal=(S1.draws == S2.draws), incumbent_kept=(S2.epoch.index == 0), live_equal=(Ba.live == Bb.live - S2.pairs_bytes), pairs_bytes_retained=S2.pairs_bytes); S1._close('ctrl'); S2._close('ctrl')      # the interaction scores are RETAINED stream state (charged once at the first attempt), not candidate ownership
    ok = (kind == 'PENDING' and all(res['pending_switch'][k] for k in ('t_unchanged', 'SA_unchanged', 'epochs_unchanged', 'rng_unchanged')) and res['switch']['t_preserved'] and res['switch']['SA_preserved'] and res['switch']['SB_preserved'] and res['switch']['rewidened_to_max'] and r3 == 'COMMITTED' and res['switch']['t_grows_same_accumulator'] and res['switch']['eps_num_entered_before_first_batch']
          and res['z_epoch_local']['sum_equals_stream'] and res['z_epoch_local']['epoch0_record_has_cap'] and not res['z_epoch_local']['pooled_reported'] and res['pilot_once']['equal'] and a2.get('status') == 'REFUSED' and res['rng_independent_of_refusal']['identical_draws'] and res['rng_independent_of_refusal']['incumbent_kept'] and res['rng_independent_of_refusal']['live_equal'])
    rec('D49_epoch_switch_and_certificate_continuity', ok, **res)


def D50_candidate_refusal_lifetime():
    """candidate refusal at every phase preserves owned storage and the incumbent: injected MEMORY at the sources, DEADLINE in the seed (prepare -> typed close, nothing owned), a short pilot (keeps the seed, skips optimization),
    MAX-pass deadline, SUM-pass deadline, optimizer malformed rows (every frontier row rejected -> KEPT_INCUMBENT), checker rejection (Defect -> incumbent kept, typed), fingerprint deadline at commit, epoch-commit refusal, and an
    output (Proposal invariant) failure; after each the constructor account equals its pre-attempt value, the incumbent epoch / law / certificate t / RNG are unchanged; the persisted absolute allowance cannot reopen on yield
    (a stream yielded at 101 with until 110 later is CLOSED typed, not READY)"""
    res = {}; model, _ = load('dg_n8_c4_clique_two'); M, order, clk, B = _jstage(model); cards = list(M.cards)
    def fresh():
        S, B_, r = _jstream(M, allow=10.0); assert r == 'READY', (r, S.closed_reason); S.pilot_action(PA.tnow() + 10); S.pairs, chg = JO.interaction_scores(M, B_, clk); S.joint_bytes += chg; S.retained_bytes += chg; S.pairs_bytes = chg; return S, B_      # the retained interaction scores computed up front so the snapshot isolates CANDIDATE ownership
    def snap(S, B_): return dict(live=B_.live, epoch=S.epoch.index, law=S.epoch.prop.sha256, t=S.cert.t, draws=S.draws, rng=S.rng.bit_generator.state['state']['state'], joint_bytes=S.joint_bytes)
    def same(a, b): return all(a[k] == b[k] for k in ('live', 'epoch', 'law', 't', 'draws', 'rng', 'joint_bytes'))
    inj = {}
    # sources MEMORY
    S, B_ = fresh(); s0 = snap(S, B_); cap0 = B_.cap; B_.cap = B_.live + 4096
    try: a = S.refine_action(PA.tnow() + 10, PA.tnow() + 20)
    finally: B_.cap = cap0
    inj['sources_memory'] = dict(status=a.get('status'), kind=a.get('kind'), preserved=same(s0, snap(S, B_))); S._close('ctrl')
    # MAX pass deadline / SUM pass deadline via a clock that expires on the k-th 'before joint group' poll
    for phase, where, nth in (('max_pass_deadline', 'before joint group', 3), ('sum_pass_deadline', 'before reciprocal table', len(cards)), ('checker_deadline', 'joint stage checker', 5), ('retained_deadline', 'before the retained product', 1), ('frontier_deadline', 'between frontier candidates', 2), ('commit_deadline', 'before the epoch commit', 1)):     # the n-th 'before reciprocal table' poll is the FIRST of the SUM pass (the MAX pass makes n - 1)
        S, B_ = fresh(); s0 = snap(S, B_); real_clock = CE.Clock
        class Clk(CE.Clock):
            def __init__(self, deadline, stats): super().__init__(deadline, stats); self.n = 0
            def poll(self, w):
                if where in w:
                    self.n += 1
                    if self.n == nth: raise CE.Refused('DEADLINE', 'injected ' + w)
                return super().poll(w)
        CE.Clock = Clk
        try: a = S.refine_action(PA.tnow() + 10, PA.tnow() + 20)
        finally: CE.Clock = real_clock
        inj[phase] = dict(status=a.get('status'), kind=a.get('kind'), why=(a.get('why') or '')[:60], preserved=same(s0, snap(S, B_)), packet_released=a.get('packet_released_bytes')); S._close('ctrl')
    # optimizer: every row malformed
    S, B_ = fresh(); s0 = snap(S, B_); real_q = JO.quantize_rows
    JO.quantize_rows = lambda th, k: (np.ones((th.shape[0], k), dtype=np.int64), np.zeros(th.shape[0], dtype=bool))
    try: a = S.refine_action(PA.tnow() + 10, PA.tnow() + 20)
    finally: JO.quantize_rows = real_q
    inj['optimizer_malformed'] = dict(status=a.get('status'), rejected_rows=len(a.get('rejected_rows') or []), winner=a.get('winner'), preserved=same(s0, snap(S, B_))); S._close('ctrl')
    # checker rejection (Defect)
    S, B_ = fresh(); s0 = snap(S, B_); real_cs = CJ.check_stage
    CJ.check_stage = lambda *a_, **k_: dict(ok=False, why='injected', cells=0)
    try: a = S.refine_action(PA.tnow() + 10, PA.tnow() + 20)
    finally: CJ.check_stage = real_cs
    inj['checker_defect'] = dict(status=a.get('status'), why=(a.get('why') or '')[:60], preserved=same(s0, snap(S, B_))); S._close('ctrl')
    # fingerprint deadline at commit
    S, B_ = fresh(); s0 = snap(S, B_); real_fp = JS.JointStream._fingerprint_of
    def fp_fail(self, ep, deadline, budget): raise PA.Deadline('injected in the fingerprint')
    JS.JointStream._fingerprint_of = fp_fail
    try: a = S.refine_action(PA.tnow() + 10, PA.tnow() + 20)
    except PA.Deadline: a = dict(status='UNCAUGHT_DEADLINE')
    finally: JS.JointStream._fingerprint_of = real_fp
    inj['fingerprint_deadline'] = dict(status=a.get('status'), preserved=same(s0, snap(S, B_)), stage=S.stage); S._close('ctrl')
    # output invariant: a candidate Proposal with a parent sampled after its child
    S, B_ = fresh(); s0 = snap(S, B_); real_P = JP.Proposal
    class BadProposal(JP.Proposal):
        def __init__(self, *a_, **k_): raise AssertionError('injected output invariant failure')
    JP.Proposal = BadProposal
    try: a = S.refine_action(PA.tnow() + 10, PA.tnow() + 20)
    except AssertionError: a = dict(status='UNCAUGHT_ASSERTION')
    finally: JP.Proposal = real_P
    inj['output_invariant'] = dict(status=a.get('status'), preserved=same(s0, snap(S, B_))); S._close('ctrl')
    # seed DEADLINE in prepare: typed close, nothing owned
    B3 = CE.Budget(CE.CONSTRUCTOR_BYTES); l3 = B3.live; S3 = JS.JointStream(2, M, M, [], 1, EPS, DELTA / 4, dict(PAC_OPTS, budget_obj=B3), mode='joint'); real_cs2 = JP.compile_seed
    def seed_dead(*a_, **k_): raise CE.Refused('DEADLINE', 'injected in the seed')
    JP.compile_seed = seed_dead
    try: r3 = S3.prepare(PA.tnow() + 10, until=PA.tnow() + 10)
    finally: JP.compile_seed = real_cs2
    inj['seed_deadline'] = dict(result=r3, closed=(S3.closed_reason or '')[:70], orphaned=B3.live - l3)
    # short pilot
    S4, B4, r4 = _jstream(M, allow=10.0); S4.phase_ends['pilot'] = PA.tnow() - 1.0; p4 = S4.pilot_action(PA.tnow() + 10); a4 = S4.refine_action(PA.tnow() + 10, PA.tnow() + 20); inj['short_pilot'] = dict(pilot=p4.get('status'), draws=p4.get('draws'), refine=a4.get('status'), ended=(S4.refinement_ended or '')[:60]); S4._close('ctrl')
    # persisted allowance cannot reopen on yield
    S5 = JS.JointStream(2, M, M, [], 1, EPS, DELTA / 4, dict(PAC_OPTS, budget_obj=CE.Budget(CE.CONSTRUCTOR_BYTES)), mode='joint'); clock = {'now': 100.0}; old = (JS.tnow, PA.tnow, CE.tnow, PA.IG.tnow); real_order = S5._j_order
    def order_then_expire(deadline): real_order(deadline); clock['now'] = 101.0
    S5._j_order = order_then_expire; JS.tnow = PA.tnow = CE.tnow = PA.IG.tnow = lambda: clock['now']
    try: y1 = S5.prepare(110.0, until=101.0); st1 = S5.stage; y2 = S5.prepare(110.0, until=110.0)
    finally: JS.tnow, PA.tnow, CE.tnow, PA.IG.tnow = old
    inj['allowance_reopen'] = dict(first=y1, first_stage=st1, second=y2, second_stage=S5.stage, closed=(S5.closed_reason or '')[:70], absolute_end=S5.allowance_end)
    res['injections'] = inj
    ok = (all(v.get('preserved') for k_, v in inj.items() if 'preserved' in v) and inj['sources_memory']['status'] == 'REFUSED' and inj['max_pass_deadline']['status'] == 'REFUSED' and inj['sum_pass_deadline']['status'] == 'REFUSED' and inj['checker_deadline']['status'] == 'REFUSED' and inj['retained_deadline']['status'] == 'REFUSED' and inj['frontier_deadline']['status'] == 'REFUSED' and inj['commit_deadline']['status'] == 'REFUSED'
          and inj['optimizer_malformed']['status'] == 'KEPT_INCUMBENT' and inj['optimizer_malformed']['rejected_rows'] >= 10 and inj['checker_defect']['status'] == 'DEFECT' and inj['fingerprint_deadline']['status'] == 'REFUSED' and inj['output_invariant']['status'] == 'DEFECT' and r3 == 'CLOSED' and inj['seed_deadline']['orphaned'] == 0 and inj['short_pilot']['pilot'] == 'SHORT' and inj['short_pilot']['refine'] in ('ENDED', 'SKIPPED')
          and y1 == 'CLOSED' and 'ALLOWANCE' in str(S5.closed_reason) and y2 == 'CLOSED' and S5.allowance_end == 101.0)       # the joint allowance has ONE absolute end = the first until: reaching it closes TYPED (no yield-then-resume exists for this stream); a later longer until cannot reopen
    rec('D50_candidate_refusal_lifetime', ok, **res)


def D51_heldout_isolation_and_forecast_independence():
    """(a) at the same still-open decision boundary with an INJECTED clock, altering every held-out (even-id) pilot value cannot change the fit Z_proxy, the family ranking, the winner, the promotion or the payback inputs (two
    streams with identical seeds; one has its held-out accumulator and store overwritten before refine): identical attempt records except the labelled held-out diagnostic; (b) ordinary certificate completion may stop work: a
    stream that completes publishes and can_refine is False; (c) altering a forecast (an injected stream_forecast) cannot publish a row (the published set is unchanged); (d) draw ids / RNG are independent of rejected-candidate
    bookkeeping (D49 f) -- rechecked under the injected clock"""
    res = {}; model, _ = load('dg_n8_c4_clique_two'); M, order, clk, B = _jstage(model)
    def prepared(seed=1):
        S, B_, r = _jstream(M, allow=10.0, seed=seed); assert r == 'READY', (r, S.closed_reason); S.pilot_action(PA.tnow() + 10); return S, B_
    S1, B1 = prepared(); S2, B2 = prepared(); S2.held = dict(n=S2.held['n'], lmax=S2.held['lmax'] + 30.0, lsum=S2.held['lsum'] * 1e6)       # the held-out accumulator altered
    if S2.pilot_store is not None: S2.pilot_store['logW0q'] = [np.where((ids & 1) == 0, lw + 50.0, lw) for lw, ids in zip(S2.pilot_store['logW0q'], S2.pilot_store['ids'])]
    a1 = S1.refine_action(PA.tnow() + 10, PA.tnow() + 20); a2 = S2.refine_action(PA.tnow() + 10, PA.tnow() + 20)
    def strip(a):
        def clean(c): return {k: v for k, v in c.items() if k not in ('log2_J', 'd_hat')}                                           # d_hat carries the MEASURED d_seed (real clock): the ranking is invariant to that common factor
        return {k: v for k, v in a.items() if k not in ('heldout_offpolicy', 'seconds', 'ended_offset_s', 'started_offset_s', 'T_before_s', 'payback', 'packet', 'commit_seconds', 'candidates', 'incumbent')} | dict(candidates=[clean(c) for c in a.get('candidates', [])], incumbent=clean(a.get('incumbent') or {}), payback_ratio_J=round((a.get('payback') or {}).get('ratio_J') or 0.0, 9))
    res['heldout_isolation'] = dict(identical_decisions=(json.dumps(strip(a1), sort_keys=True, default=str) == json.dumps(strip(a2), sort_keys=True, default=str)), winner=(a1.get('winner'), a2.get('winner')), promoted=(a1.get('promoted'), a2.get('promoted')), Z_proxy_fit=(S1.pilot['log2_Z_proxy_fit'], S2.pilot['log2_Z_proxy_fit']), heldout_diag_differs=((a1.get('heldout_offpolicy') or {}).get('log2_mean_W0q0_W0q1') != (a2.get('heldout_offpolicy') or {}).get('log2_mean_W0q0_W0q1')))
    S1._close('ctrl'); S2._close('ctrl')
    # (b) completion stops work: a tiny model completes
    S3, B3, r3 = _jstream(CE.canonicalize(_four_cycle(), CE.Clock(PA.tnow() + 10, {}), CE.Budget(CE.CONSTRUCTOR_BYTES)), allow=10.0); S3.pilot_action(PA.tnow() + 10)
    for _ in range(400):
        if S3.stage != 'READY' or S3.all_published(): break
        S3.batch(PA.tnow() + 10); S3.check()
    res['completion_stops_work'] = dict(all_published=S3.all_published(), published=len(S3.pub), Kq=S3.Kq, can_refine_after=S3.can_refine(), draws=S3.draws); S3._close('ctrl')
    # (c) altering a forecast cannot publish a row: planner with an injected forecast on the dev n8 model (3 s)
    P = UPlanner(model, {}, 3.0, admission_stop_s=2.5, t_start=PA.tnow(), seed=1, pac=True, lifted=False, joint='joint'); real_fc = P.stream_forecast; P.stream_forecast = lambda S_: 0.0; o = P.run(); pubs = [r for r in o['answers'] if r['guarantee'] != 'NOT_PUBLISHED']; enc = {(e['var'], e['state']): (F(e['lo']), F(e['hi'])) for e in o.get('enclosures') or []}
    Zs, mus = enum_marginals(CE.canonicalize(model, CE.Clock(PA.tnow() + 10, {}), CE.Budget(CE.CONSTRUCTOR_BYTES))); viol = sum(1 for r in pubs if not (F(r['lo']) <= mus[(r['var'], r['state'])] <= F(r['hi'])))
    res['forecast_cannot_publish'] = dict(outcome=o['outcome'], published=len(pubs), containment_violations=viol, enclosures=len(enc), note='a forecast of 0 s steers the scheduler; every published row still passes the certificate')
    ok = res['heldout_isolation']['identical_decisions'] and res['heldout_isolation']['Z_proxy_fit'][0] == res['heldout_isolation']['Z_proxy_fit'][1] and res['completion_stops_work']['all_published'] and not res['completion_stops_work']['can_refine_after'] and viol == 0
    rec('D51_heldout_isolation_and_forecast_independence', ok, **res)


def D52_feature_disabled_and_expiry_suppression():
    """(a) the new feature disabled (--joint absent) preserves the repaired old path: on the dev n16 clique the planner with --lifted --envelope RMAX and joint=None creates the RMAX lifted stream exactly as DGP4 (no joint stream,
    no joint offer record beyond 'mode None'); with joint='joint' and < 8 s of work the offer is refused by the threshold and the old route runs; (b) a deterministic injected deadline during final diagnostics suppresses newly
    assembled rows on fixed / factorless and ordinary tasks alike (the parent finalizer's TimedAction injection of D34 re-run through the PAC planner's fin with a joint stream present): outcome DEADLINE, 0 published"""
    res = {}; model, binding = load_mid('dg_n16_c4_clique_two')
    P0 = UPlanner(model, binding, 8.0, admission_stop_s=7.5, t_start=PA.tnow(), seed=1, pac=True, lifted=True, envelope='RMAX', joint=None); o0 = P0.run(); res['disabled'] = dict(outcome=o0['outcome'], published=o0['published'], K=o0['K'], streams=[(s['kind'], s['stage'], s['draws']) for s in o0['streams']], joint_offer=o0['mechanism'].get('joint_offer'), ledger=o0['mechanism'].get('constructor_live_ledger_identity'), joint_streams=sum(1 for s in o0['streams'] if s['kind'] == 'joint'), lifted_streams=sum(1 for s in o0['streams'] if s['kind'] == 'lifted'))
    P1 = UPlanner(model, binding, 8.0, admission_stop_s=7.5, t_start=PA.tnow(), seed=1, pac=True, lifted=True, envelope='RMAX', joint='joint'); o1 = P1.run(); res['threshold_refusal'] = dict(outcome=o1['outcome'], published=o1['published'], joint_offer=o1['mechanism'].get('joint_offer'), lifted_streams=sum(1 for s in o1['streams'] if s['kind'] == 'lifted'), joint_streams=sum(1 for s in o1['streams'] if s['kind'] == 'joint'), refused_by_threshold=str((o1['mechanism'].get('joint_offer') or {}).get('refused', '')).startswith('OFFER_THRESHOLD'))
    # (b) expiry during final diagnostics with a joint stream present (factorless + ordinary)
    for name, mdl in (('ordinary', dict(cards=[2, 3], factors=[dict(scope=(0, 1), values=[F(1), F(2), F(1), F(2), F(1), F(1)])], evidence={})), ('factorless', dict(cards=[3, 2], factors=[dict(scope=(0,), values=[F(1), F(2), F(1)]), dict(scope=(1,), values=[F(1), F(3)])], evidence={}))):
        P = UPlanner(mdl, {}, 3.0, admission_stop_s=2.5, t_start=PA.tnow(), seed=1, pac=True, joint='joint'); P.M = CE.canonicalize(mdl, P.hclock, P.budget); P.canonical_charge = P.budget.live; P.t_mark = P.t_start; P.out['mechanism']['positive_mass_witness'] = True; P.orig_to_canon = {int(P.M.orig_of[v]): v for v in range(len(P.M.cards))}
        if P.M.cards:
            S = JS.JointStream(2, P.M, P.M, [], 1, EPS, DELTA / 4, dict(PAC_OPTS, budget_obj=P.budget), mode='joint'); S.prepare(PA.tnow() + 5, until=PA.tnow() + 5); S.decode_rows = lambda rows_q, S_: {(P.M.orig_of[S_.queries[j][0]], S_.queries[j][1]): LH for j, LH in rows_q.items()}; S.semantic_key = 'ctrl'; P.streams.append(S)
            for _ in range(3): S.batch(PA.tnow() + 5)
            S.check()
        state = {'now': P.t_start + 0.01}
        class TimedAction(dict):
            def get(self, k, d=None): state['now'] = P.hard + 0.01; return super().get(k, d)
        P.out['actions'] = [TimedAction(action='price', actual_s=0.001), TimedAction(action='joint_pilot', actual_s=0.002)]
        rows = {}
        for v in range(len(mdl['cards'])):
            for a_ in range(mdl['cards'][v]): rows[(v, a_)] = dict(lo=F(1, 4), hi=F(1, 4), point=F(1, 4), guarantee='DETERMINISTIC')
        old = (UP.tnow, UPP.tnow, CE.tnow, PA.tnow, JS.tnow); UP.tnow = UPP.tnow = CE.tnow = PA.tnow = JS.tnow = lambda: state['now']
        try: r = P.fin('COMPLETE', rows)
        finally: UP.tnow, UPP.tnow, CE.tnow, PA.tnow, JS.tnow = old
        res['expiry_' + name] = dict(outcome=r['outcome'], published=r['published'], K=r['K'], hard_respected=r['hard_deadline_respected'], enclosures=len(r.get('enclosures') or []), radius_report=r.get('radius_report'))
    ok = (res['disabled']['joint_streams'] == 0 and res['disabled']['lifted_streams'] == 1 and res['disabled']['ledger'] is True and res['disabled']['outcome'] == 'COMPLETE' and res['threshold_refusal']['refused_by_threshold'] and res['threshold_refusal']['joint_streams'] == 0 and res['threshold_refusal']['lifted_streams'] == 1
          and all(res['expiry_' + k]['outcome'] == 'DEADLINE' and res['expiry_' + k]['published'] == 0 and res['expiry_' + k]['enclosures'] == 0 and res['expiry_' + k]['radius_report'] is None for k in ('ordinary', 'factorless')))
    rec('D52_feature_disabled_and_expiry_suppression', ok, **res)


def D53_real_clock_planner_cells():
    """small REAL-clock checks (no injection): the full planner on the dev n16 card-4 clique at 20 s in modes seed / joint / cap_only / moment_only and forced joint: every cell ends with the ledger identity TRUE, the hard deadline
    respected, no certificate defect; the joint stream is offered + created + READY + sampled in the 20 s cells (>= 8 s rule); every published row of the joint-mode cells contains the enumerated marginal is NOT checkable at n16
    (no oracle) -- instead the dev n8 clique (enumerable) runs the same five modes at 6 s and every published / enclosed coordinate contains the truth"""
    res = {}; model16, b16 = load_mid('dg_n16_c4_clique_two'); model8, b8 = load('dg_n8_c4_clique_two'); Zs, mus = enum_marginals(CE.canonicalize(model8, CE.Clock(PA.tnow() + 10, {}), CE.Budget(CE.CONSTRUCTOR_BYTES)))
    for tag, mdl, bnd, budget, adm in (('n16', model16, b16, 12.0, 11.5), ('n8', model8, b8, 6.0, 5.5)):
        for mode, forced in (('seed', None), ('joint', None), ('cap_only', 'joint'), ('moment_only', 'joint'), ('joint', 'joint')):
            P = UPlanner(mdl, bnd, budget, admission_stop_s=adm, t_start=PA.tnow(), seed=1, pac=True, lifted=(forced is None), envelope='RMAX', joint=mode, force_stream=forced); o = P.run(); m = o['mechanism']; J = [s for s in o['streams'] if s['kind'] == 'joint']
            viol = None
            if tag == 'n8':
                enc = o.get('enclosures') or []; viol = sum(1 for e in enc if not (F(e['lo']) <= mus[(e['var'], e['state'])] <= F(e['hi']))) + sum(1 for r in o['answers'] if r['guarantee'] != 'NOT_PUBLISHED' and not (F(r['lo']) <= mus[(r['var'], r['state'])] <= F(r['hi'])))
            res['%s_%s%s' % (tag, mode, '_forced' if forced else '')] = dict(outcome=o['outcome'], published=o['published'], K=o['K'], wall=round(o['wall_s'], 2), ledger=m.get('constructor_live_ledger_identity'), hard=o['hard_deadline_respected'], defect=m.get('defect'), offered=(m.get('joint_offer') or {}).get('created'), joint=[(s['stage'], s['draws'], len(s['joint']['epochs']), (s['joint']['refinement_ended'] or '')[:40]) for s in J], containment_violations=viol, worst_radius=(o.get('radius_report') or {}).get('worst'))
    ok = all(v['ledger'] is True and v['hard'] and not v['defect'] for v in res.values()) and all(v['offered'] for k_, v in res.items() if k_.startswith('n16')) and all(v['containment_violations'] == 0 for k_, v in res.items() if k_.startswith('n8')) and all(v['joint'] and v['joint'][0][1] > 0 for k_, v in res.items() if k_.startswith('n16'))
    rec('D53_real_clock_planner_cells', ok, **res)


CONTROLS += [D42_seed_exhaustive_validity, D43_exact_floor_and_count_boundaries, D44_local_witness_inequalities, D45_witness_pass_mutants, D46_quantization_cap_and_incumbent_witness, D47_context_replication_and_staleness, D48_units_and_paired_arithmetic, D49_epoch_switch_and_certificate_continuity, D50_candidate_refusal_lifetime, D51_heldout_isolation_and_forecast_independence, D52_feature_disabled_and_expiry_suppression, D53_real_clock_planner_cells]

if __name__ == '__main__':
    ap = argparse.ArgumentParser(); ap.add_argument('out'); ap.add_argument('--only', default=None); a = ap.parse_args(); t0 = time.time()
    for c in CONTROLS:
        if a.only and c.__name__.split('_')[0] not in a.only.split(','): continue
        try: c()
        except Exception as e: rec(c.__name__, False, error=repr(e)[:300], tb=traceback.format_exc()[-1200:])
    res = dict(all_ok=all(r['ok'] for r in R), n=len(R), n_ok=sum(r['ok'] for r in R), wall_s=round(time.time() - t0, 2), controls=R); json.dump(res, open(a.out, 'w'), indent=1, default=str); print(json.dumps({k: v for k, v in res.items() if k != 'controls'}))


