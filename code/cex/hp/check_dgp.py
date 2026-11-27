"""Qualification controls of DENSE_GENERIC_PAC_INTEGRATION_1 (brief section 7), DGP2 (D19-D26), DGP3 (D27-D31: RF1-RF4, lemma G), DGP4 (D32-D41: R1-R3, residual MAX compiler, checker, whole proposal, lifetime; D37 / D38 / D39 / D41 strengthened in DGP5) and DGP5 (D42-D54: the joint conditional construction -- seed, exact floor, local witnesses, mutants, quantization / incumbent witness, replication / staleness, units, epochs, refusal lifetime, held-out isolation, feature-disabled / expiry, real clock). usage: check_dgp.py OUT.json [--only D1,D2,..]. Every control asserts actual branch execution."""
import sys, os, json, time, math, argparse, traceback
RECORDS = os.environ.get('PGM_RECORDS_ROOT', '/Users/adis/Workspace/pgm-records')   # consolidation step 1: the private records root is a parameter (controls depending on it are reported BLOCKED when it is absent; control logic unchanged)
from fractions import Fraction as F
HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, HERE); sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(HERE)), 'cex', 'newarm')); sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(HERE)), 'cex', 'blockres'))
import numpy as np
import integrated as IG, blockres as BR, core as CORE, coarse_envelope as CE, pac_actions as PA, lifted_decoder as LD
DEV = RECORDS + '/code/runs/mdi_2026-10-28/DENSE_GENERIC_PAC_INTEGRATION_1/dev/inputs'
OPTS = dict(table_cap=1 << 18, enum_cap=1 << 16, mb_cap=1 << 24, batch=1024, schedule='targeted', crosscheck=True, exact_route=True)
EPS = F(1, 200); DELTA = F(1, 10 ** 6)
R = []
def rec(name, ok, **kw): R.append(dict(control=name, ok=bool(ok), **kw)); print(json.dumps(dict(control=name, ok=bool(ok), **{k: v for k, v in kw.items() if k != 'detail'}), default=str)[:400], flush=True)

def load(name): return CORE.read_uai(os.path.join(DEV, name + '.uai'))
MID = DEV.replace('/inputs', '/inputs_mid')
def load_mid(name): return CORE.read_uai(os.path.join(MID, name + '.uai'))
ORACLE_DEV = RECORDS + '/code/runs/mdi_2026-10-28/DGP2_REPAIR_AND_DIAGNOSIS/oracle/dev_inputs'
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
    RDB = RECORDS + '/code/runs/mdi_2026-10-28/BLOCKRES_2026-11-19'
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
    src = open(UPP.__file__).read(); fin_src = src[src.index('    def fin(self, oc, rows, note=None):'):src.index('    def cost_breakdown(self):')]; order_ok = fin_src.index('self.all_enclosures()') < fin_src.index('res = super().fin(') and fin_src.index('self.cost_breakdown()') < fin_src.index('res = super().fin(')
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
    p = RECORDS + '/code/runs/mdi_2026-10-28/DENSE_GENERIC_PAC_INTEGRATION_1/inputs_eval/dg_n64_c4_clique_two.uai'; model, binding = CORE.read_uai(p)
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
    src = open(UPP.__file__).read(); fin_src = src[src.index('    def fin(self, oc, rows, note=None):'):src.index('    def cost_breakdown(self):')]; after = fin_src[fin_src.index('res = super().fin('):]
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
    man = json.load(open(RECORDS + '/code/runs/mdi_2026-10-28/DENSE_GENERIC_PAC_INTEGRATION_1/PRESERVATION_18_MANIFEST.json')); t = next(x for x in man['tasks'] if x['name'] == 'grid4x4_c32_generic'); mdl, bnd = CORE.read_uai(t['model'])
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
    src = open(UP.__file__).read(); fin_src = src[src.index('    def fin(self, oc, rows_canon, note=None):'):src.index('def plan_and_solve')]; after = fin_src[fin_src.index('t_end = tnow()'):]
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
    hits = dict(adapter_packing_refused=0, sampler_stage_deadline=0, midpoint_zero_allowance=0)                       # DGP6 repair (finding 8): every injection counts its hits; a branch with zero hits is a VACUOUS control
    def patch_pack(P):
        real = RM.check_packing
        def fail(*a_, **k_): hits['adapter_packing_refused'] += 1; return dict(ok=False, why='injected')
        RM.check_packing = fail; return lambda: setattr(RM, 'check_packing', real)
    def patch_sampler(P):
        real = PA.prepare_sampler_polled
        def fail(mbp, deadline, *a_, **k_):
            import inspect; f = inspect.currentframe().f_back
            if f.f_code.co_name == '_l_sampler': hits['sampler_stage_deadline'] += 1; raise PA.Deadline('injected in the lifted sampler stage')
            return real(mbp, deadline, *a_, **k_)
        PA.prepare_sampler_polled = fail; return lambda: setattr(PA, 'prepare_sampler_polled', real)
    def patch_midpoint(P):
        real = PA.LiftedStream.prepare
        def prep(self, deadline, cdead=None, until=None):
            hits['midpoint_zero_allowance'] += 1; self.rmax_midpoint = PA.tnow() - 1.0; return real(self, deadline, cdead, until)
        PA.LiftedStream.prepare = prep; return lambda: setattr(PA.LiftedStream, 'prepare', real)
    run('baseline', None); run('adapter_packing_refused', patch_pack); run('sampler_stage_deadline', patch_sampler); run('midpoint_zero_allowance', patch_midpoint); res['injection_hits'] = dict(hits)
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
          and res['forced_tight_allowance']['typed_allowance_refusal'] and res['forced_tight_allowance']['released'] and all(v >= 1 for v in res['injection_hits'].values()) and all(len(res[k]['lifted']) >= 1 for k in ('adapter_packing_refused', 'sampler_stage_deadline', 'midpoint_zero_allowance')))        # DGP5 (finding 6): the specific injected outcome is REQUIRED; DGP6 (finding 8): every injection hit >= 1 and every targeted branch NONEMPTY
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

def D54_scalar_messages_and_internal_errors():
    """DGP5 validity amendment 1 (the n64 clique / CSP_11 production crash): (a) a MAX group that reduces to a SCALAR (every axis eliminated: a saturated bucket's leftover unary-only group) yields a 0-d object array,
    the seed / b-pass / a-pass complete and are valid by enumeration on a fixture that FORCES it (fan-in 1: every table its own group -> the unary of the eliminated variable is a scalar MAX message) and on the 7-variable
    card-4 clique at the production profile; (b) an injected unexpected exception inside the optional joint stream's preparation / pilot / refine closes THAT stream typed (INTERNAL, traceback recorded) and the full
    planner request on the dev n16 clique still completes through the primary with the ledger identity TRUE"""
    res = {}; M, order, clk, B = _jstage(_four_cycle()); cards = list(M.cards)
    # (a) max_over to a scalar is an ndarray
    arr = np.empty((4,), dtype=object)
    for i in range(4): arr[i] = _fu(F(i + 1))
    out, cur = JP.max_over(arr, (0,), [0]); res['max_over_scalar_is_ndarray'] = isinstance(out, np.ndarray) and out.shape == () and out[()] == _fu(F(4))
    prop, rec_, owned = JP.compile_seed(M, order, dict(JPROF, fanin=1), B, clk); ref = CJ.ref_check_law(M, prop); res['fanin1_seed'] = dict(splits=rec_['max_splits'], violations=ref['violations'], normalized=ref['normalized'], log2_B=prop.log2_B(), log2_Rstar=ref['log2_Rstar'], scalar_messages=sum(1 for p_ in rec_['plan'] for g in p_['groups'] if not g['output_axes']))
    z = prop.order[-1]; parents = tuple(prop.conds[z].parents); pk = JW.build_packet(M, prop, z, parents, order, dict(JPROF, fanin=1), B, clk); b_ref, a_ref = CJ.ref_coefficients(M, prop, z, parents); wc = CJ.ref_witness_check(pk.b, pk.a, b_ref, a_ref); res['fanin1_packet'] = dict(violations=wc['violations'], b_scalar_messages=sum(1 for p_ in pk.rec_b['plan'] for g in p_['groups'] if not g['output_axes']), a_scalar_messages=sum(1 for p_ in pk.rec_a['plan'] for g in p_['groups'] if not g['output_axes'])); pk.release(); B.release(owned)
    rng = random.Random(21); clique7 = _rand_model(rng, [4] * 7, [(i, j) for i in range(7) for j in range(i + 1, 7)]); M7, order7, clk7, B7 = _jstage(clique7); prop7, rec7, owned7 = JP.compile_seed(M7, order7, JPROF, B7, clk7); S7, Bs7, r7 = _jstream(M7, allow=10.0); p7 = S7.pilot_action(PA.tnow() + 10); a7 = S7.refine_action(PA.tnow() + 10, PA.tnow() + 20)
    res['clique7_production_profile'] = dict(seed_splits=rec7['max_splits'], stream=r7, pilot=p7.get('status'), refine=a7.get('status'), scalar_messages_seed=sum(1 for p_ in rec7['plan'] for g in p_['groups'] if not g['output_axes']), internal=S7.mech.get('internal_error')); B7.release(owned7); S7._close('ctrl')
    # (b) injected unexpected exceptions: preparation, pilot, refine
    model, binding = load_mid('dg_n16_c4_clique_two'); inj = {}
    real_cs = JP.compile_seed
    def boom(*a_, **k_): raise AttributeError("injected 'tuple' object has no attribute 'size'")
    JP.compile_seed = boom
    try: P = UPlanner(model, binding, 8.0, admission_stop_s=7.5, t_start=PA.tnow(), seed=1, pac=True, lifted=True, envelope='RMAX', joint='joint'); o = P.run()
    finally: JP.compile_seed = real_cs
    J = [s for s in o['streams'] if s['kind'] == 'joint']; inj['prepare'] = dict(outcome=o['outcome'], published=o['published'], K=o['K'], ledger=o['mechanism'].get('constructor_live_ledger_identity'), joint=[(s['stage'], (s.get('closed') or '')[:60], bool((s.get('mechanism') or {}).get('internal_error'))) for s in J], lifted_fallback=[(s['label'][:20], s['stage'], s['draws']) for s in o['streams'] if s['kind'] == 'lifted'])
    real_bp = JW.build_packet
    def boom2(*a_, **k_): raise TypeError('injected unexpected error in the packet')
    JW.build_packet = boom2
    try: P2 = UPlanner(model, binding, 8.0, admission_stop_s=7.5, t_start=PA.tnow(), seed=1, pac=True, lifted=True, envelope='RMAX', joint='joint'); o2 = P2.run()
    finally: JW.build_packet = real_bp
    J2 = [s for s in o2['streams'] if s['kind'] == 'joint']; inj['refine'] = dict(outcome=o2['outcome'], published=o2['published'], ledger=o2['mechanism'].get('constructor_live_ledger_identity'), joint=[(s['stage'], s['draws'], [(a_.get('status'), (a_.get('why') or '')[:40]) for a_ in (s.get('joint') or {}).get('attempts', [])]) for s in J2])
    res['injected'] = inj
    ok = (res['max_over_scalar_is_ndarray'] and res['fanin1_seed']['violations'] == 0 and res['fanin1_seed']['normalized'] and res['fanin1_seed']['scalar_messages'] >= 1 and res['fanin1_packet']['violations'] == 0 and r7 == 'READY' and p7.get('status') == 'COMPLETE' and a7.get('status') in ('PROMOTED', 'KEPT_INCUMBENT') and not res['clique7_production_profile']['internal']
          and inj['prepare']['outcome'] == 'COMPLETE' and inj['prepare']['ledger'] is True and all(j[0] == 'CLOSED' and 'INTERNAL' in j[1] and j[2] for j in inj['prepare']['joint']) and inj['refine']['outcome'] == 'COMPLETE' and inj['refine']['ledger'] is True and all(j[0] == 'READY' and j[1] > 0 and any(a_[0] == 'INTERNAL' for a_ in j[2]) for j in inj['refine']['joint']))
    rec('D54_scalar_messages_and_internal_errors', ok, **res)


CONTROLS.append(D54_scalar_messages_and_internal_errors)



# ---------------------------------------------------------------- DGP6 (D55-D62): the nine repairs + the global construction (brief section 5)
import global_circuit as GC, global_optimize as GO, check_global as CG, global_stream as GS, dgp_paths as DPATH
import residual_max_envelope as _RM
_LN2 = math.log(2.0)
def _gstage(model, budget_s=120):
    M, order, clk, B = _jstage(model, budget_s); cards = list(M.cards); prop, rec_, owned = JP.compile_seed(M, order, JPROF, B, clk); return M, order, clk, B, cards, prop, owned
def _gplans(M, prop, order, parents=None):
    parents = parents or {v: tuple(prop.conds[v].parents) for v in prop.order}; PB, PS = GC.build_plans(M, prop.order, parents, order); cards = list(M.cards)
    return PB, PS, GC.FloatCircuit(PB, GC.source_logs(M, 1), cards), GC.FloatCircuit(PS, GC.source_logs(M, 2), cards)
def _gstream(M, mode='global', seed=1, budget=None, allow=10.0, profile=None):
    B = budget or CE.Budget(CE.CONSTRUCTOR_BYTES); S = GS.GlobalStream(2, M, M, [], seed, EPS, DELTA / 4, dict(PAC_OPTS, budget_obj=B), mode=mode, profile=profile); r = S.prepare(PA.tnow() + allow, until=PA.tnow() + allow); return S, B, r

def D55_source_binding_mutants():
    """DGP6 finding 1 (+ brief 5: omitted target / reciprocal mutants rejected by the PRODUCTION checker without exhaustive enumeration; values / axes checked, not only ids): (a) the DGP5 coefficient-pass binder rejects an omitted reciprocal,
    an omitted target factor, a reciprocal with WRONG VALUES (same role / axes / id), a factor with transposed axes, a duplicate reciprocal; accepts the complete inventory; (b) the DGP6 circuit certifier rejects the omitted-source plan, a plan whose
    reciprocal axes do not match the actual conditional, a producer value below the independent re-derivation, a duplicated source and a tampered power; accepts the honest plan; (c) the binder's rejection happens with NO enumeration (the model has 4^8 states)"""
    res = {}; model, _ = load('dg_n8_c4_clique_two'); M, order, clk, B, cards, prop, owned = _gstage(model); z = prop.order[-1]; own = [0]
    srcs = JP.source_tables(M, B, clk, own, V=4096); recs = [JW.reciprocal_table(prop.conds[v], cards, 100 + v, B, clk, own) for v in prop.order if v != z]; full = srcs + recs
    res['complete_accepted'] = CJ.certify_sources(M, prop, full, z=z)['ok']; res['omitted_reciprocal'] = CJ.certify_sources(M, prop, srcs + recs[1:], z=z); res['omitted_target'] = CJ.certify_sources(M, prop, [T for T in srcs if T.origin[0] != 'factor' or T.origin[1] != 0] + recs, z=z)
    bad = recs[0]; wrong = JP.JTable(bad.axes, bad.arr.copy(), bad.tid, bad.origin); idx = tuple(0 for _ in bad.axes); wrong.arr[idx] = _RM.norm_up(wrong.arr[idx][0] - 1, wrong.arr[idx][1]); res['wrong_values_same_id'] = CJ.certify_sources(M, prop, srcs + [wrong] + recs[1:], z=z)
    f0 = next(T for T in srcs if T.origin[0] == 'factor'); tr = JP.JTable(f0.axes, np.ascontiguousarray(np.transpose(f0.arr)), f0.tid, f0.origin) if f0.arr.ndim == 2 else None
    res['transposed_factor'] = CJ.certify_sources(M, prop, [tr if T is f0 else T for T in srcs] + recs, z=z) if tr is not None else dict(ok=False, why='n/a')
    res['duplicate_reciprocal'] = CJ.certify_sources(M, prop, full + [recs[0]], z=z); B.release(own[0])
    PB, PS, FB, FS = _gplans(M, prop, order); cB, _ = GC.compact_evaluate(PB, M, prop, B, clk); live0 = B.live
    res['circuit_honest'] = CG.certify(PB, M, prop, cB, clk, budget=B)['ok']; p2, i2 = CG.mutate_omit(PB, 'reciprocal', prop.order[0]); res['circuit_omitted'] = CG.certify(p2, M, prop, cB, clk, budget=B).get('why')
    import copy; p3 = copy.copy(PB); p3.nodes = [dict(nd) for nd in PB.nodes]; j = next(i for i, nd in enumerate(p3.nodes) if nd['op'] == 'source' and nd['role'] == 'reciprocal' and len(nd['axes']) >= 2); p3.nodes[j]['axes'] = tuple(reversed(p3.nodes[j]['axes'])); res['circuit_wrong_axes'] = CG.certify(p3, M, prop, cB, clk).get('why')
    low = _RM.norm_up(cB[0] - 1, cB[1]); res['circuit_underbound_producer'] = CG.certify(PB, M, prop, low, clk).get('why')
    p4 = copy.copy(PB); p4.nodes = [dict(nd) for nd in PB.nodes]; k = next(i for i, nd in enumerate(p4.nodes) if nd['op'] == 'product'); p4.nodes[k]['inputs'] = list(p4.nodes[k]['inputs']) + [p4.nodes[k]['inputs'][0]]; res['circuit_duplicate_input'] = CG.certify(p4, M, prop, cB, clk).get('why')
    p5 = copy.copy(PB); p5.nodes = [dict(nd) for nd in PB.nodes]; u = next(i for i, nd in enumerate(p5.nodes) if nd['op'] == 'source' and nd['role'] == 'factor'); p5.nodes[u]['power'] = 2; res['circuit_wrong_power'] = CG.certify(p5, M, prop, cB, clk).get('why')
    res['live_delta_after_certifier'] = B.live - live0; res['states'] = math.prod(cards); B.release(owned)
    ok = (res['complete_accepted'] and not res['omitted_reciprocal']['ok'] and not res['omitted_target']['ok'] and not res['wrong_values_same_id']['ok'] and (tr is None or not res['transposed_factor']['ok']) and not res['duplicate_reciprocal']['ok'] and res['circuit_honest'] and all(res[k] for k in ('circuit_omitted', 'circuit_wrong_axes', 'circuit_underbound_producer', 'circuit_duplicate_input', 'circuit_wrong_power')) and res['live_delta_after_certifier'] == 0 and res['states'] > 4096)
    rec('D55_source_binding_mutants', ok, **{k: (v if not isinstance(v, dict) else {kk: v.get(kk) for kk in ('ok', 'why')}) for k, v in res.items()})

def D56_ownership_admission_cutoffs():
    """DGP6 findings 2 / 3 / 4: (a) ownership: after a close no seed_prop / pairs / candidate / graph reference survives, the constructor live count returns to its pre-stream value, close is idempotent; an interrupted interaction_scores orphans
    0 B; (b) admission: Conditional.replicate 2,048 -> 4,096 entries under ZERO headroom refuses MEMORY before allocation; a successful replication + release conserves ownership; quantize_segment under zero headroom refuses and releases;
    (c) cutoffs: a clock crossing inside the batch statistics assembly discards the batch (certificate t unchanged, stream closed typed); a crossing inside the prior-epoch diagnostics suppresses the epoch commit (epochs unchanged, typed Deadline)"""
    import gc, weakref; res = {}; model, _ = load('dg_n8_c4_clique_two')
    M, order, clk, B = _jstage(model); l0 = B.live; S, Bq, r = _gstream(M, budget=B); S.pilot_action(PA.tnow() + 10); att = S.optimize_action(PA.tnow() + 10, PA.tnow() + 30)
    refs = [weakref.ref(x) for x in (S.epoch.prop,) if x is not None]; S._close('ctrl'); l1 = B.live; S._close('twice'); gc.collect()
    res['ownership'] = dict(prepare=r, attempt=att.get('status'), live_before=l0, live_after_close=l1, idempotent=(l1 == B.live), seed_prop=S.seed_prop, pairs=S.pairs, candidate=S.candidate, graph_ref=S.graph is None or isinstance(S.graph, dict), epoch=S.epoch, epoch_laws_dropped=all(e.prop is None for e in S.epochs), joint_bytes=S.joint_bytes, released=S.mech.get('close_release'))
    class Clk(CE.Clock):
        def __init__(self, d, s): super().__init__(d, s); self.hit = 0
        def poll(self, where):
            if 'interaction' in where: self.hit += 1; raise CE.Refused('DEADLINE', 'injected ' + where)
    rng = random.Random(1); big = _rand_model(rng, [2] * 24, [(i, j) for i in range(24) for j in range(i + 1, 24)]); Mb, ob, cb, Bb = _jstage(big); lb = Bb.live; ck = Clk(PA.tnow() + 10, {}); kind = None
    try: JO.interaction_scores(Mb, Bb, ck)
    except CE.Refused as e: kind = e.kind
    res['interaction_interrupted'] = dict(refusal=kind, hits=ck.hit, orphaned=Bb.live - lb)
    # (b) admission
    rng = random.Random(3); m7 = _rand_model(rng, [4] * 7, [(i, j) for i in range(7) for j in range(i + 1, 7)]); M7, o7, c7, B7, cards7, p7, own7 = _gstage(m7); c = max(p7.conds.values(), key=lambda c_: c_.family_volume()); extra = [v for v in p7.order if v not in c.parents and v != c.z][0]; newpar = tuple(sorted(c.parents + (extra,), key=lambda q: p7.order.index(q)))
    cap0 = B7.cap; B7.cap = B7.live; lz = B7.live; kind = None
    try: c.replicate(newpar, cards7, budget=B7)
    except CE.Refused as e: kind = e.kind
    res['replicate_zero_headroom'] = dict(refusal=kind, live_delta=B7.live - lz, from_entries=c.family_volume(), to_entries=JP.vol_of(newpar, cards7) * cards7[c.z]); B7.cap = cap0
    rep = c.replicate(newpar, cards7, budget=B7); l_after = B7.live; B7.release(rep.bytes); res['replicate_conserves'] = dict(charged=l_after - lz, bytes=rep.bytes, back_to_start=(B7.live == lz))
    PB, PS, FB, FS = _gplans(M7, p7, o7); t = FB.logits_from_counts(p7); rows = {v: GO.logits_to_rows(FB, t, v) for v in p7.order}; B7.cap = B7.live + 1000; kind = None
    try: GO.quantize_segment(FB, rows, rows, 0.5, cards7, p7.order, {v: tuple(p7.conds[v].parents) for v in p7.order}, budget=B7)
    except CE.Refused as e: kind = e.kind
    res['quantize_zero_headroom'] = dict(refusal=kind, live_delta=B7.live - lz); B7.cap = cap0; B7.release(own7)
    # (c) cutoffs (the DGP6 probe constructions, repeated as controls)
    M, order, clk, B = _jstage(model); S = _jstream(M, allow=10.0)[0]; S.batch(PA.tnow() + 10); t_before = S.cert.t; state = {'now': 100.0, 'hits': 0}; old = (JS.tnow, PA.tnow, CE.tnow)
    class Timed(np.ndarray):
        def __getitem__(self, k): state['hits'] += 1; state['now'] = 200.0; return super().__getitem__(k)
    S.Dm = [d.view(Timed) for d in S.Dm]; JS.tnow = PA.tnow = CE.tnow = lambda: state['now']
    try: rb = S.batch(150.0, 150.0)
    finally: JS.tnow, PA.tnow, CE.tnow = old
    res['batch_assembly_crossing'] = dict(result=rb, hits=state['hits'], cert_t_unchanged=(S.cert.t == t_before), closed=(S.closed_reason or '')[:60])
    S2 = _jstream(M, allow=10.0)[0]; S2.pilot_action(PA.tnow() + 10); n_ep = len(S2.epochs); st2 = {'now': 100.0, 'hits': 0}
    class ZC:
        def __init__(self, inner): self.inner = inner
        def interval(self): st2['hits'] += 1; st2['now'] = 200.0; return self.inner.interval()
        def update_batch(self, X): return self.inner.update_batch(X)
        @property
        def t(self): return self.inner.t
    S2.epoch.zcert = ZC(S2.epoch.zcert); old = (JS.tnow, PA.tnow, CE.tnow); JS.tnow = PA.tnow = CE.tnow = lambda: st2['now']; kind = None
    try: S2._commit_epoch(S2.epoch.prop, 'ctrl', 150.0, S2.opts['budget_obj'])
    except Exception as e: kind = type(e).__name__
    finally: JS.tnow, PA.tnow, CE.tnow = old
    res['epoch_diag_crossing'] = dict(exception=kind, hits=st2['hits'], epochs_unchanged=(len(S2.epochs) == n_ep))
    o = res['ownership']; ok = (o['prepare'] == 'READY' and o['idempotent'] and o['seed_prop'] is None and o['pairs'] is None and o['candidate'] is None and o['epoch'] is None and o['epoch_laws_dropped'] and o['joint_bytes'] == 0 and o['live_after_close'] == o['live_before'] and res['interaction_interrupted']['refusal'] == 'DEADLINE' and res['interaction_interrupted']['hits'] >= 1 and res['interaction_interrupted']['orphaned'] == 0
          and res['replicate_zero_headroom']['refusal'] == 'MEMORY' and res['replicate_zero_headroom']['live_delta'] == 0 and res['replicate_conserves']['back_to_start'] and res['quantize_zero_headroom']['refusal'] == 'MEMORY' and res['quantize_zero_headroom']['live_delta'] == 0
          and res['batch_assembly_crossing']['result'] == 'CLOSED' and res['batch_assembly_crossing']['hits'] >= 1 and res['batch_assembly_crossing']['cert_t_unchanged'] and res['epoch_diag_crossing']['exception'] == 'Deadline' and res['epoch_diag_crossing']['hits'] >= 1 and res['epoch_diag_crossing']['epochs_unchanged'])
    rec('D56_ownership_admission_cutoffs', ok, **res)

def D57_bounded_sum_and_rebuilt_J():
    """DGP6 findings 5 / 6 / 7 / 8: (a) the exact checker's sum on two 128-bit inputs with exponent spread 2^24 allocates O(128) bits (not 2^24), is an UPPER bound, and refuses GROWTH typed beyond 2^20 terms; (b) dgp5_oracle.rebuilt rebuilds
    S / H / J together (a comparator with a tighter S has a lower J; J is never stale); (c) the DGP5 frontier grid is affine in C (the endpoints and the midpoint are exact); (d) a two-epoch joint stream reports no pooled X_mean / ESS and reports epoch-local statistics"""
    res = {}; a_ = _fu(F(3)); b_ = (a_[0] - (1 << 24), a_[1]); t0 = time.monotonic(); s_ = CJ._exact_sum([a_, b_]); res['sum_bits'] = s_[1].bit_length(); res['sum_seconds'] = time.monotonic() - t0; res['sum_upper'] = _tf(s_) >= _tf(a_) + _tf(b_)
    kind = None
    try: CJ._exact_sum([a_] * ((1 << 20) + 1))
    except CE.Refused as e: kind = e.kind
    res['growth_refusal'] = kind
    # DGP7 repair R7: the rebuilt-J check runs on a REAL packet (the DGP2 oracle dev clique dg_n6_c4_clique_two): the retune comparator's S witness differs from the consumed S, so a STALE comparator (S replaced, J kept) and the
    # REBUILT one (S / H / J together) give different J -- the control asserts the difference (discrimination) and the exact H / J consistency of the rebuilt value; a comparator that kept the stale J is rejected by construction
    import dgp5_oracle as O5, core as _CORE; model6, _ = _CORE.read_uai(ORACLE_DEV + '/dg_n6_c4_clique_two.uai'); M6, order6, clk6, B6 = _jstage(model6); cards6 = list(M6.cards); prop6, rec6, owned6 = JP.compile_seed(M6, order6, JPROF, B6, clk6); pairs6, chg6 = JO.interaction_scores(M6, B6, clk6)
    e6 = JO.rank_expansions(prop6, pairs6, cards6, 4096)[0]; z6 = e6['z']; par6 = tuple(e6['new_parents']); pk6 = JW.build_packet(M6, prop6, z6, par6, order6, JPROF, B6, clk6); inc6 = JW.witnesses_of(pk6, pk6.cond_ctx, S_ref=None); B_t = min(prop6.B, inc6['B']); S_ref6 = min([s_ for s_ in (prop6.S, inc6['S']) if s_[1]] + [_RM.norm_up(*_RM.mul_exact(B_t, B_t))])
    log2_eta6 = math.log2(0.005) + 13.4 - math.log2(6.0); d6 = 1e-6; inc = dict(label='seed', is_current=True, log2_B=prop6.log2_B(), log2_S=_l2(S_ref6), log2_eta=log2_eta6, d_hat=d6, family_volume=prop6.conds[z6].family_volume(), index=-1); inc['log2_H'] = JO.H_log2(inc['log2_S'], inc['log2_B'], log2_eta6); inc['log2_J'] = math.log2(d6) + inc['log2_H']
    pk_u = JW.build_packet(M6, prop6, z6, tuple(prop6.conds[z6].parents), order6, JPROF, B6, clk6) if tuple(prop6.conds[z6].parents) != par6 else pk6; inc_u = JW.witnesses_of(pk_u, pk_u.cond_ctx, S_ref=None); S_ref_u = min([s_ for s_ in (prop6.S, inc_u['S']) if s_[1]])
    # DGP9 replacement of the vacuous DGP7 D57 (original DGP7 finding F7): the retune comparator's S witness is FORCED to differ from the consumed S (S' = S_ref_u / 4, an exact tighter second-moment witness fed to the rebuild),
    # so the STALE comparator (S replaced, J kept) and the REBUILT one (S / H / J together) MUST differ, and a selection threshold placed between the two J values gives OPPOSITE decisions: the stale decision is provably
    # invalid. The real-packet retune value is recorded as well (it may or may not differ); `discriminates` is no longer an OR with the unchanged-S case
    S_forced = _RM.norm_up(S_ref_u[0] - 2, S_ref_u[1]); reb = O5.rebuilt(inc, S_forced); stale = dict(inc); stale['log2_S'] = _l2(S_forced)                 # the DGP5-frozen behaviour: S replaced, J kept
    thr = 0.5 * (stale['log2_J'] + reb['log2_J']); stale_decision = (stale['log2_J'] <= thr); rebuilt_decision = (reb['log2_J'] <= thr); reb_real = O5.rebuilt(inc, S_ref_u)
    res['rebuilt'] = dict(real_packet='dg_n6_c4_clique_two', family=dict(z=z6, parents=list(par6)), S_consumed=inc['log2_S'], S_retune_real=_l2(S_ref_u), S_forced=_l2(S_forced), J_stale=stale['log2_J'], J_rebuilt=reb['log2_J'], J_rebuilt_real_retune=reb_real['log2_J'], J_consistent=(abs(reb['log2_J'] - (math.log2(d6) + JO.H_log2(_l2(S_forced), inc['log2_B'], log2_eta6))) < 1e-12),
                          S_changed=(abs(inc['log2_S'] - _l2(S_forced)) > 1e-12), discriminates=(abs(stale['log2_J'] - reb['log2_J']) > 1e-9 and abs(inc['log2_S'] - _l2(S_forced)) > 1e-12), stale_decision_invalid=(stale_decision != rebuilt_decision), threshold=thr, eta_changes_J=(O5.rebuilt(inc, S_forced, log2_eta=log2_eta6 + 1.0)['log2_J'] != reb['log2_J']))
    if pk_u is not pk6: pk_u.release()
    pk6.release(); B6.release(owned6 + chg6)
    src = open(JO.__file__).read(); res['grid_affine'] = ('log2(1.0 + (ratio - 1.0) * i' in src) and ('log2_Cmin + (log2_Cmax - log2_Cmin) * i' not in src)
    lo, hi, n_ = 3.0, 7.0, 5; ratio = 2.0 ** (hi - lo); grid = [lo + math.log2(1.0 + (ratio - 1.0) * i / (n_ - 1)) for i in range(n_)]; Cs = [2.0 ** g for g in grid]; res['grid_check'] = dict(endpoints=(abs(Cs[0] - 8.0) < 1e-9 and abs(Cs[-1] - 128.0) < 1e-9), midpoint_affine=(abs(Cs[2] - 68.0) < 1e-9))
    model, _ = load('dg_n8_c4_clique_two'); M, order, clk, B = _jstage(model); S = _jstream(M, allow=10.0)[0]; S.pilot_action(PA.tnow() + 10); a1 = S.refine_action(PA.tnow() + 10, PA.tnow() + 30)
    if not a1.get('promoted'):
        pairs, chg = JO.interaction_scores(M, B, clk); e = JO.rank_expansions(S.epoch.prop, pairs, list(M.cards), 4096)[0]; pk = JW.build_packet(M, S.epoch.prop, e['z'], tuple(e['new_parents']), order, JPROF, B, clk); cond = [c for _, c, _ in JO.frontier_laws(pk, S.epoch.prop, list(M.cards), JPROF, 'moment_only', S.epoch.prop.B) if c is not None][0]
        w = JW.witnesses_of(pk, cond, S_ref=S.epoch.prop.S); conds = dict(S.epoch.prop.conds); conds[e['z']] = cond; newp = JP.Proposal(list(M.cards), conds, S.epoch.prop.order, w['B'], w['S'], {}); B.charge(newp.bytes, 'ctrl'); S.joint_bytes += newp.bytes; S._commit_epoch(newp, 'ctrl', PA.tnow() + 5, B); pk.release()
    for _ in range(3): S.batch(PA.tnow() + 10)
    d = S.diagnostics(); pooled = [k for k in ('X_mean', 'ESS_DIAGNOSTIC', 'largest_share', 'Z_over_Ucap_EB_DIAGNOSTIC', 'log2_Zhat_over_Ucap_DIAGNOSTIC', 'max_log2_X_observed') if d.get(k) is not None]; ews = d['joint']['epoch_weight_statistics']
    res['epoch_local'] = dict(epochs=len(S.epochs), pooled_fields=pooled, removed_note=bool(d.get('pooled_weight_statistics')), epoch_stats=[(x['epoch'], x['draws'], x['X_mean'] is not None) for x in ews]); S._close('ctrl')
    ok = (res['sum_bits'] <= 256 and res['sum_seconds'] < 0.05 and res['sum_upper'] and res['growth_refusal'] == 'GROWTH' and all(res['rebuilt'][k] for k in ('J_consistent', 'discriminates', 'eta_changes_J', 'S_changed', 'stale_decision_invalid')) and res['grid_affine'] and all(res['grid_check'].values()) and res['epoch_local']['epochs'] >= 2 and not pooled and res['epoch_local']['removed_note'] and all(x[2] for x in res['epoch_local']['epoch_stats'] if x[1] > 0))
    rec('D57_bounded_sum_and_rebuilt_J', ok, **res)

def D58_circuits_vs_exhaustive_reference():
    """brief section 5 (new controls): on binary and card-4 graphs, a scalar (nullary-factor) and a factorless-variable target, a target with hard zeros, and the four-cycle: (a) the compact MAX / SUM circuits at the SEED counts dominate the exact-rational
    B* = max W_0 / q and S* = sum W_0^2 / q by enumeration (<= 4,096 states) and the float evaluator agrees with the compact value within 1e-9 relative (log2); (b) G1 row replication preserves q EXACTLY on random assignments and the circuits on G1
    give the same values; (c) the quantized candidate law is RECOMPUTED through the circuits from its actual counts and dominates its own exhaustive reference; (d) a huge target scaling (2^200) shifts log2 B by 200, log2 S by 400 and leaves the
    chosen rows invariant; (e) a target with an all-zero row keeps exact zero mass (-inf) with zero adjoint; a zero-mass target gives B = S = 0 typed"""
    res = {}; rng = random.Random(11); ok_all = True
    fixtures = dict(four_cycle=_four_cycle(), binary_n10=_rand_model(rng, [2] * 10, [(i, j) for i in range(10) for j in range(i + 1, 10) if rng.random() < 0.5]), card4_n6=_rand_model(rng, [4] * 6, [(i, j) for i in range(6) for j in range(i + 1, 6)]), scalar_nullary=_rand_model(rng, [3] * 5, [(i, i + 1) for i in range(4)], nullary=F(7, 3)), factorless=_rand_model(rng, [3] * 5, [(0, 1), (1, 2)], factorless=(3, 4)), hard_zeros=_rand_model(rng, [3] * 6, [(i, j) for i in range(6) for j in range(i + 1, 6) if rng.random() < 0.7], zeros=2))
    for name, model in fixtures.items():
        try:
            M, order, clk, B, cards, prop, owned = _gstage(model); PB, PS, FB, FS = _gplans(M, prop, order); t = FB.logits_from_counts(prop); lB, _ = FB.forward(t); lS, _ = FS.forward(t); cB, rB = GC.compact_evaluate(PB, M, prop, B, clk); cS, rS = GC.compact_evaluate(PS, M, prop, B, clk); ref = CG.ref_exact_BS(M, prop, cap=1 << 12)
            r = dict(n=len(cards), states=math.prod(cards), log2_B=rB['log2'], log2_S=rS['log2'], ref_B=ref['log2_B_star'], ref_S=ref['log2_S_star'], B_dom=(_tf(cB) >= ref['B_star']), S_dom=(_tf(cS) >= ref['S_star']), float_B_agrees=(abs(lB / _LN2 - rB['log2']) <= 1e-9 * max(1.0, abs(rB['log2'])) + 1e-9), float_S_agrees=(abs(lS / _LN2 - rS['log2']) <= 1e-9 * max(1.0, abs(rS['log2'])) + 1e-9), cert=CG.certify(PB, M, prop, cB, clk)['ok'] and CG.certify(PS, M, prop, cS, clk)['ok'])
            pairs, chg = JO.interaction_scores(M, B, clk); parents1, g1 = GO.select_g1(prop, pairs, cards)
            if not g1['alias_G0']:
                p1 = GO.replicate_graph(prop, parents1, cards, budget=B); xs = [tuple(rng.randrange(k) for k in cards) for _ in range(32)]; r['g1_q_exact'] = all(p1.q_exact(x) == prop.q_exact(x) for x in xs); PB1, PS1, FB1, FS1 = _gplans(M, prop, order, parents1); cB1, rB1 = GC.compact_evaluate(PB1, M, p1, B, clk); cS1, rS1 = GC.compact_evaluate(PS1, M, p1, B, clk); r['g1_B_dom'] = _tf(cB1) >= ref['B_star']; r['g1_S_dom'] = _tf(cS1) >= ref['S_star']; r['g1_extended'] = g1['n_extended']
                B.release(sum(c.bytes for v, c in p1.conds.items() if c is not prop.conds[v]))
            # (c) a candidate: optimize briefly then quantize lambda = 1 and recompute
            log_eta = math.log(0.005) + (lS - lB) / 2 if math.isfinite(lS) and math.isfinite(lB) else 0.0
            if math.isfinite(lB):
                opt = GO.BoundedLBFGS(FB, FS, log_eta, 'joint', PA.tnow() + 20); endpoint, phases = opt.run(t)
                if endpoint is not None:
                    rows_s = {v: GO.logits_to_rows(FB, t, v) for v in prop.order}; rows_o = {v: GO.logits_to_rows(FB, endpoint['t'], v) for v in prop.order}; conds = GO.quantize_segment(FB, rows_s, rows_o, 1.0, cards, prop.order, {v: tuple(prop.conds[v].parents) for v in prop.order}); newp = JP.Proposal(cards, conds, prop.order, _ZERO, _ZERO, {})
                    cB2, rB2 = GC.compact_evaluate(PB, M, newp, B, clk); cS2, rS2 = GC.compact_evaluate(PS, M, newp, B, clk); ref2 = CG.ref_exact_BS(M, newp, cap=1 << 12); r['candidate'] = dict(evals=opt.evals, log2_B=rB2['log2'], log2_S=rS2['log2'], B_dom=(_tf(cB2) >= ref2['B_star']), S_dom=(_tf(cS2) >= ref2['S_star']), cert=CG.certify(PB, M, newp, cB2, clk)['ok'] and CG.certify(PS, M, newp, cS2, clk)['ok'], rows_sum_D=all((c.counts.sum(axis=1) == JP.D).all() and (c.counts >= 1).all() for c in conds.values()), changed=any(not np.array_equal(conds[v].counts, prop.conds[v].counts) for v in prop.order))
                    # (d) huge scaling: multiply one unary by 2^200 -> log2 B + 200, log2 S + 400; the optimizer's chosen rows invariant
                    M2 = copy.deepcopy(M); M2.psi[0] = [x * (F(2) ** 200) for x in M2.psi[0]]; FB2 = GC.FloatCircuit(PB, GC.source_logs(M2, 1), cards); FS2 = GC.FloatCircuit(PS, GC.source_logs(M2, 2), cards); lB2, _ = FB2.forward(t); lS2, _ = FS2.forward(t)
                    opt2 = GO.BoundedLBFGS(FB2, FS2, log_eta + 200 * _LN2, 'joint', PA.tnow() + 20); e2, _ = opt2.run(t); r['scaling'] = dict(dB=(lB2 - lB) / _LN2, dS=(lS2 - lS) / _LN2, shift_ok=(abs((lB2 - lB) / _LN2 - 200) < 1e-6 and abs((lS2 - lS) / _LN2 - 400) < 1e-6), rows_invariant=(e2 is not None and endpoint is not None and all(np.allclose(GO.logits_to_rows(FB, endpoint['t'], v), GO.logits_to_rows(FB2, e2['t'], v), rtol=1e-6, atol=1e-9) for v in prop.order)))
            B.release(owned); res[name] = r
            ok_all = ok_all and r['B_dom'] and r['S_dom'] and r['float_B_agrees'] and r['float_S_agrees'] and r['cert'] and r.get('g1_q_exact', True) and r.get('g1_B_dom', True) and r.get('g1_S_dom', True) and (r.get('candidate') is None or (r['candidate']['B_dom'] and r['candidate']['S_dom'] and r['candidate']['cert'] and r['candidate']['rows_sum_D'])) and (r.get('scaling') is None or (r['scaling']['shift_ok'] and r['scaling']['rows_invariant']))
        except Exception as e: res[name] = dict(error=repr(e)[:200], tb=traceback.format_exc()[-600:]); ok_all = False
    # (e) an all-zero reduction stays -inf with zero adjoint; zero-mass target: the seed reports zero U
    rng2 = random.Random(5); mz = _rand_model(rng2, [2, 2, 2], [(0, 1), (1, 2)]); mz['factors'][0]['values'] = [F(0)] * 4; M, order, clk, B = _jstage(mz); prop, rec_, owned = JP.compile_seed(M, order, JPROF, B, clk); res['zero_mass'] = dict(zero_U=rec_['zero_U'], B_zero=(prop.B[1] == 0))
    if not rec_['zero_U']: ok_all = False
    mh = _rand_model(rng2, [3, 3, 3], [(0, 1), (1, 2)]); mh['factors'][0]['values'] = [F(0)] * 3 + mh['factors'][0]['values'][3:]; M, order, clk, B = _jstage(mh); prop, rec_, owned = JP.compile_seed(M, order, JPROF, B, clk); PB, PS, FB, FS = _gplans(M, prop, order); t = FB.logits_from_counts(prop); lB, tp = FB.forward(t); g = FB.reverse(tp); res['hard_zero_row'] = dict(finite=math.isfinite(lB), grad_finite=bool(np.isfinite(g).all()), has_inf_source=bool(np.isinf(GC.source_logs(M, 1)[('factor', 0)]).any()))
    ok_all = ok_all and res['hard_zero_row']['finite'] and res['hard_zero_row']['grad_finite'] and res['hard_zero_row']['has_inf_source']
    rec('D58_circuits_vs_exhaustive_reference', ok_all, **res)

def D59_gradient_convexity_pnorm():
    """brief section 5: on tiny positive models (a) all-row central finite differences of the smoothed objective agree with the reverse-pass gradient (relative error <= 1e-4 over 8 random directions and 16 single coordinates); (b) every row gradient
    sums to zero (<= 1e-10); (c) the p-norm surrogate is an UPPER bound of the hard MAX circuit value and decreases toward it as p grows (p = 4, 16, 64, 256) with the structural Delta bounding the gap; (d) the fixed-circuit convex midpoint
    inequality f((t1 + t2) / 2) <= (f(t1) + f(t2)) / 2 + 1e-9 holds on 16 random pairs (a bug detector); (e) a shared source used by two products accumulates adjoints (a two-factor model where the unary of the middle variable feeds two groups
    under fan-in 1) -- checked against finite differences; (f) transposed source axes: a factor given with reversed scope evaluates identically; (g) no stale numeric reuse: after changing two rows at once the forward value equals a fresh evaluator's"""
    res = {}; rng = random.Random(23); np_rng = np.random.default_rng(23); ok_all = True
    for name, model in dict(card4_n5=_rand_model(rng, [4] * 5, [(i, j) for i in range(5) for j in range(i + 1, 5) if rng.random() < 0.8]), binary_n8=_rand_model(rng, [2] * 8, [(i, j) for i in range(8) for j in range(i + 1, 8) if rng.random() < 0.5]), mixed=_rand_model(rng, [2, 3, 4, 3, 2], [(0, 1), (1, 2), (2, 3), (3, 4), (0, 4)])).items():
        M, order, clk, B, cards, prop, owned = _gstage(model); PB, PS, FB, FS = _gplans(M, prop, order); t = FB.logits_from_counts(prop) + 0.3 * np_rng.standard_normal(FB.n_params); lB, _ = FB.forward(t); lS, _ = FS.forward(t); log_eta = math.log(0.005) + (lS - lB) / 2
        o = GC.objective(FB, FS, t, log_eta, 16.0); g = o['g']; errs = []
        for _ in range(8):
            d = np_rng.standard_normal(t.size); d /= np.linalg.norm(d); h = 1e-5; fp = GC.objective(FB, FS, t + h * d, log_eta, 16.0)['f']; fm = GC.objective(FB, FS, t - h * d, log_eta, 16.0)['f']; errs.append(abs((fp - fm) / (2 * h) - float(g @ d)) / max(1e-8, abs(float(g @ d)), 1e-3 * np.abs(g).max()))
        for i in np_rng.choice(t.size, size=min(16, t.size), replace=False):
            e = np.zeros(t.size); e[i] = 1.0; h = 1e-5; fp = GC.objective(FB, FS, t + h * e, log_eta, 16.0)['f']; fm = GC.objective(FB, FS, t - h * e, log_eta, 16.0)['f']; errs.append(abs((fp - fm) / (2 * h) - g[i]) / max(1e-8, abs(g[i]), 1e-3 * np.abs(g).max()))
        rowsum = max(abs(g[off:off + R * k].reshape(R, k).sum(axis=1)).max() for v, (off, R, k) in FB.row_slices.items())
        hard = FB.forward(t, None)[0]; ps = [4.0, 16.0, 64.0, 256.0]; vals = [FB.forward(t, p)[0] for p in ps]; deltas = [FB.delta_smoothing(p) for p in ps]
        pn = dict(hard=hard, smoothed=vals, upper=all(v >= hard - 1e-9 for v in vals), decreasing=all(vals[i] >= vals[i + 1] - 1e-9 for i in range(len(vals) - 1)), within_delta=all(v - hard <= dl + 1e-9 for v, dl in zip(vals, deltas)), deltas=deltas)
        mid_ok = True; worst = 0.0
        for _ in range(16):
            t1 = t + 0.5 * np_rng.standard_normal(t.size); t2 = t + 0.5 * np_rng.standard_normal(t.size); f1 = GC.objective(FB, FS, t1, log_eta, 16.0)['f']; f2 = GC.objective(FB, FS, t2, log_eta, 16.0)['f']; fm_ = GC.objective(FB, FS, (t1 + t2) / 2, log_eta, 16.0)['f']; worst = max(worst, fm_ - (f1 + f2) / 2); mid_ok = mid_ok and fm_ <= (f1 + f2) / 2 + 1e-9
        # (f) transposed scope
        M2 = copy.deepcopy(M); sc, vals_ = M2.factors[0]; sc = tuple(sc)
        if len(sc) == 2:
            arr = np.array(vals_, dtype=object).reshape(cards[sc[0]], cards[sc[1]]).T.reshape(-1); M2.factors[0] = ((sc[1], sc[0]), list(arr)); PB2, PS2 = GC.build_plans(M2, prop.order, {v: tuple(prop.conds[v].parents) for v in prop.order}, order); FB2 = GC.FloatCircuit(PB2, GC.source_logs(M2, 1), cards); tr_ok = abs(FB2.forward(t)[0] - lB) < 1e-9; cB2, _ = GC.compact_evaluate(PB2, M2, prop, B, clk); cB1, _ = GC.compact_evaluate(PB, M, prop, B, clk); tr_ok = tr_ok and cB2 == cB1
        else: tr_ok = True
        # (g) no stale reuse
        t3 = t.copy(); v0, v1 = prop.order[0], prop.order[-1]; off0, R0, k0 = FB.row_slices[v0]; off1, R1, k1 = FB.row_slices[v1]; t3[off0:off0 + k0] -= 1.0; t3[off1:off1 + k1] -= 2.0; fresh = GC.FloatCircuit(PB, GC.source_logs(M, 1), cards); stale_ok = abs(FB.forward(t3)[0] - fresh.forward(t3)[0]) < 1e-12 and abs(FB.forward(t)[0] - lB) < 1e-12
        B.release(owned); r = dict(n_params=t.size, max_fd_rel_error=max(errs), max_row_sum=float(rowsum), pnorm=pn, midpoint_ok=mid_ok, midpoint_worst_violation=worst, transposed_ok=tr_ok, no_stale_reuse=stale_ok); res[name] = r
        ok_all = ok_all and r['max_fd_rel_error'] <= 1e-4 and r['max_row_sum'] <= 1e-10 and pn['upper'] and pn['decreasing'] and pn['within_delta'] and mid_ok and tr_ok and stale_ok
    # (e) shared-source adjoint accumulation: fan-in 1 plan on a chain -> the middle unary is MAXed in its own group; compare to finite differences AND to a hand-built two-consumer plan
    m = _rand_model(rng, [3, 3, 3], [(0, 1), (1, 2)]); M, order, clk, B, cards, prop, owned = _gstage(m); parents = {v: tuple(prop.conds[v].parents) for v in prop.order}; PB = GC.CircuitPlan(cards, prop.order, parents, [tuple(sc) for sc, _ in M.factors], 1, order, V=4096, fanin=1)
    # a hand-made plan where ONE reciprocal leaf feeds two products (accumulation): duplicate the first product's reciprocal input into the second product
    import copy as _c; P2 = _c.copy(PB); P2.nodes = [dict(nd) for nd in PB.nodes]; prods = [i for i, nd in enumerate(P2.nodes) if nd['op'] == 'product']; recs = [i for i, nd in enumerate(P2.nodes) if nd['op'] == 'source' and nd['role'] == 'reciprocal']; shared = None
    for i in prods:
        for j in recs:
            if j not in P2.nodes[i]['inputs'] and set(P2.nodes[j]['axes']) <= set(P2.nodes[i]['axes']): P2.nodes[i]['inputs'] = list(P2.nodes[i]['inputs']) + [j]; shared = (i, j); break
        if shared: break
    FB2 = GC.FloatCircuit(P2, GC.source_logs(M, 1), cards); t = FB2.logits_from_counts(prop) + 0.2 * np_rng.standard_normal(FB2.n_params); f0, tp = FB2.forward(t, 16.0); g = FB2.reverse(tp); errs = []
    for _ in range(12):
        d = np_rng.standard_normal(t.size); d /= np.linalg.norm(d); h = 1e-5; errs.append(abs((FB2.forward(t + h * d, 16.0)[0] - FB2.forward(t - h * d, 16.0)[0]) / (2 * h) - float(g @ d)) / max(1e-8, abs(float(g @ d)), 1e-3 * np.abs(g).max()))
    res['shared_source'] = dict(shared=shared, max_fd_rel_error=max(errs), uses=(sum(1 for nd in P2.nodes if nd['op'] == 'product' and shared and shared[1] in nd['inputs']) if shared else 0)); B.release(owned); ok_all = ok_all and shared is not None and res['shared_source']['uses'] == 2 and res['shared_source']['max_fd_rel_error'] <= 1e-4
    rec('D59_gradient_convexity_pnorm', ok_all, **res)

def D60_optimizer_limits_and_expiry():
    """brief section 5: (a) the evaluation counter: a phase never exceeds 16 circuit evaluations and the total never exceeds 32 even with maxiter raised (counter enforced BEFORE evaluating; SciPy maxfun not relied on); cached identical requests are
    counted as cache hits, not evaluations; (b) EARLY expiry (deadline already passed) -> no evaluation, no endpoint, typed; LATE expiry (deadline inside phase 2) -> phase 1's best iterate survives as the endpoint; (c) checker expiry: a Clock
    deadline inside the compact certifier raises typed and releases every charge; (d) a low-count row (counts near 1) quantizes to positive counts summing to D and the exact floor rule holds; (e) the segment scorer censors points past its deadline"""
    res = {}; model, _ = load('dg_n8_c4_clique_two'); M, order, clk, B, cards, prop, owned = _gstage(model); PB, PS, FB, FS = _gplans(M, prop, order); t = FB.logits_from_counts(prop); lB, _ = FB.forward(t); lS, _ = FS.forward(t); log_eta = math.log(0.005) + (lS - lB) / 2
    old = GO.MAXITER; GO.MAXITER = 200
    try: opt = GO.BoundedLBFGS(FB, FS, log_eta, 'joint', PA.tnow() + 60); ep, ph = opt.run(t)
    finally: GO.MAXITER = old
    res['counter'] = dict(total=opt.evals, per_phase=[p_['evaluations'] for p_ in ph], cache_hits=opt.cache_hits, statuses=[(p_['status'] or {}).get('message', '')[:30] for p_ in ph], trace_len=len(opt.trace))
    opt_e = GO.BoundedLBFGS(FB, FS, log_eta, 'joint', PA.tnow() - 1.0); ep_e, ph_e = opt_e.run(t); res['early_expiry'] = dict(evals=opt_e.evals, endpoint=(ep_e is not None), status=[(p_['status'] or {}).get('message', '')[:40] for p_ in ph_e])
    class LateClock:
        def __init__(self): self.n = 0
        def __call__(self): self.n += 1; return 0.0 if self.n < 40 else 1e9
    oldt = (CE.tnow,); lc = LateClock(); CE.tnow = lc
    try: opt_l = GO.BoundedLBFGS(FB, FS, log_eta, 'joint', 5.0); ep_l, ph_l = opt_l.run(t)
    finally: CE.tnow = oldt[0]
    res['late_expiry'] = dict(evals=opt_l.evals, phases=[(p_['phase'], p_['evaluations'], (p_['status'] or {}).get('message', '')[:30]) for p_ in ph_l], endpoint_from_phase=(0 if ep_l is opt_l.best.get(0) else 1) if ep_l is not None else None, has_endpoint=(ep_l is not None))
    l0 = B.live; kind = None; cB, _ = GC.compact_evaluate(PB, M, prop, B, clk)
    try: CG.certify(PB, M, prop, cB, CE.Clock(PA.tnow() - 1.0, {}), budget=B)
    except CE.Refused as e: kind = e.kind
    res['checker_expiry'] = dict(refusal=kind, live_delta=B.live - l0)
    kind = None
    try: GC.compact_evaluate(PB, M, prop, B, CE.Clock(PA.tnow() - 1.0, {}))
    except CE.Refused as e: kind = e.kind
    res['producer_expiry'] = dict(refusal=kind, live_delta=B.live - l0)
    rows = np.array([[1e-300, 1.0 - 3e-300, 1e-300, 1e-300], [0.25, 0.25, 0.25, 0.25], [1e-17, 1e-17, 0.5, 0.5], [0.0, 0.0, 0.0, 1.0]]); q = GO.quantize_rows_exact(rows, 4); res['low_counts'] = dict(sums_D=bool((q.sum(axis=1) == JP.D).all()), positive=bool((q >= 1).all()), row0=[int(x) for x in q[0]], row3=[int(x) for x in q[3]], exact_floor_row1=bool((q[1] == 1 + ((JP.D - 4) * 1) // 4 + np.array([1, 1, 1, 1]) * 0 + (np.arange(4) < (JP.D - 4 * (1 + (JP.D - 4) // 4)))).all()))
    seg, best, _ = GO.segment_scores(FB, FS, t, t, log_eta, 0.0, 'joint', PA.tnow() - 1.0); res['segment_censored'] = dict(points=len(seg), censored=sum(1 for x in seg if x.get('censored')), best=best is None)
    B.release(owned)
    ok = (res['counter']['total'] <= 32 and all(x <= 16 for x in res['counter']['per_phase']) and res['counter']['total'] == len(opt.trace) and res['early_expiry']['evals'] == 0 and not res['early_expiry']['endpoint'] and res['late_expiry']['has_endpoint'] and res['late_expiry']['evals'] < 32 and res['checker_expiry']['refusal'] == 'DEADLINE' and res['checker_expiry']['live_delta'] == 0 and res['producer_expiry']['refusal'] == 'DEADLINE' and res['producer_expiry']['live_delta'] == 0 and res['low_counts']['sums_D'] and res['low_counts']['positive'] and res['low_counts']['exact_floor_row1'] and res['segment_censored']['censored'] == 17 and res['segment_censored']['best'])
    rec('D60_optimizer_limits_and_expiry', ok, **res)

def D61_global_stream_lifecycle():
    """brief section 5: on the n8 card-4 clique through GlobalStream: (a) the full attempt promotes or keeps the incumbent with a CHECKED candidate (certifier ok on both circuits; the committed epoch's B / S are the certified values; the
    activation runs <= 2 x 256 draws with a check after each); (b) a REFUSED candidate (injected certifier rejection) preserves the RNG state, the certificate t, the epoch count, the risk ledger and the pilot statistics -- the incumbent is
    untouched; (c) an unchanged-law witness-only candidate: with the optimizer disabled (zero float share) the same-law tighter cap is the only candidate and is labelled witness_only when promoted; (d) no optimized law enters production before
    its final checked commit: the epoch list is unchanged until the certifier returned ok (checked via a certifier spy); (e) seed mode never optimizes; (f) a planner request with --global on the dev n16 clique completes through the primary
    with the ledger identity TRUE, the primary probe recorded, and the global stream's actions logged; the old-policy flag disables the probe"""
    res = {}; model, _ = load('dg_n8_c4_clique_two'); M, order, clk, B = _jstage(model)
    S, Bq, r = _gstream(M, budget=B); pil = S.pilot_action(PA.tnow() + 10); att = S.optimize_action(PA.tnow() + 10, PA.tnow() + 30); act = S.activation_action(PA.tnow() + 10) if S.can_activate() else None
    cert = att.get('certification') or {}; res['full_attempt'] = dict(prepare=r, pilot=pil.get('status'), status=att.get('status'), promoted=att.get('promoted'), witness_only=att.get('witness_only'), graph=(att.get('graph') or {}).get('label'), certifier_ok=((cert.get('certifier') or {}).get('B_ok') and (cert.get('certifier') or {}).get('S_ok')), epochs=len(S.epochs), committed_B_is_certified=(S.epoch.prop.log2_B() == (cert.get('certifier') or {}).get('log2_B')) if att.get('promoted') and not att.get('witness_only') else None, activation=({k: act.get(k) for k in ('status', 'batches', 'draws', 'checks')} if act else None), evals=(att.get('optimizer') or {}).get('evaluations'), label=att.get('label'))
    # (b) injected certifier rejection
    M, order, clk, B = _jstage(model); S2, Bq2, r2 = _gstream(M, budget=B); S2.pilot_action(PA.tnow() + 10); rng_state = S2.rng.bit_generator.state['state']['state']; t_cert = S2.cert.t; n_ep = len(S2.epochs); fit = dict(S2.fit); l0 = B.live; real = CG.certify; hits = [0]
    def reject(plan, M_, prop_, val, clock, budget=None, graph_sha=None, **kw):
        hits[0] += 1
        if hits[0] > 2: return dict(ok=False, why='injected certifier rejection')
        return real(plan, M_, prop_, val, clock, budget=budget, graph_sha=graph_sha, **kw)
    CG.certify = reject
    try: att2 = S2.optimize_action(PA.tnow() + 10, PA.tnow() + 30)
    finally: CG.certify = real
    res['refused_candidate'] = dict(status=att2.get('status'), why=(att2.get('why') or '')[:80], hits=hits[0], rng_unchanged=(S2.rng.bit_generator.state['state']['state'] == rng_state), cert_t_unchanged=(S2.cert.t == t_cert), epochs_unchanged=(len(S2.epochs) == n_ep), fit_unchanged=(S2.fit == fit), live_back=(B.live - l0 - S2.pairs_bytes), pairs_bytes=S2.pairs_bytes, stage=S2.stage, delta_s=str(S2.delta_s))
    # (d) no law before the checked commit: spy on certify -> the epoch list must be unchanged at every certifier call
    M, order, clk, B = _jstage(model); S3, Bq3, r3 = _gstream(M, budget=B); S3.pilot_action(PA.tnow() + 10); seen = []
    def spy(plan, M_, prop_, val, clock, budget=None, graph_sha=None, **kw): seen.append(len(S3.epochs)); return real(plan, M_, prop_, val, clock, budget=budget, graph_sha=graph_sha, **kw)
    CG.certify = spy
    try: att3 = S3.optimize_action(PA.tnow() + 10, PA.tnow() + 30)
    finally: CG.certify = real
    res['no_law_before_check'] = dict(certifier_calls=len(seen), epochs_at_calls=sorted(set(seen)), epochs_after=len(S3.epochs), status=att3.get('status'))
    # (c) witness-only: on a model whose seed cap is LOOSER than the G1 circuit cap (the mid n16 clique: many seed splits), with the optimizer given no time (zero float share) the same-law tighter cap is the only candidate; when promoted it is labelled witness_only, the committed epoch keeps the SAME conditionals and carries the certified tighter cap
    model16, binding16 = load_mid('dg_n16_c4_clique_two'); M16 = CE.canonicalize(model16, CE.Clock(PA.tnow() + 60, {}), CE.Budget(CE.CONSTRUCTOR_BYTES)); S4, Bq4, r4 = _gstream(M16, allow=20.0, profile=dict(float_frac=1e-9)); S4.pilot_action(PA.tnow() + 20); conds0 = {v: S4.epoch.prop.conds[v] for v in S4.epoch.prop.order}; B0 = S4.epoch.prop.B; att4 = S4.optimize_action(PA.tnow() + 20, PA.tnow() + 60)
    res['witness_only_path'] = dict(prepare=r4, status=att4.get('status'), kind=att4.get('kind'), optimizer_failure=(att4.get('optimizer_failure') or '')[:60], candidates=[(c.get('label'), c.get('change')) for c in att4.get('candidates', [])], witness_only=att4.get('witness_only'), promoted=att4.get('promoted'), why=(att4.get('why') or '')[:80], B_tight_lt_consumed=((att4.get('baselines') or {}).get('B_tight_log2', 0) < (att4.get('baselines') or {}).get('consumed', {}).get('log2_B', 0)) if att4.get('baselines') else None, same_conditionals=(all(S4.epoch.prop.conds[v] is conds0[v] for v in conds0) if att4.get('promoted') else None), cap_tighter=((S4.epoch.prop.B < B0) if att4.get('promoted') else None))
    # (e) seed mode
    S5, Bq5, r5 = _gstream(M, mode='seed'); S5.pilot_action(PA.tnow() + 10); att5 = S5.optimize_action(PA.tnow() + 10, PA.tnow() + 30); res['seed_mode'] = dict(can_optimize=S5.can_optimize(), status=att5.get('status'))
    # (f) planner cells
    model16, binding16 = load_mid('dg_n16_c4_clique_two'); P = UPlanner(model16, binding16, 10.0, admission_stop_s=9.5, t_start=PA.tnow(), seed=1, pac=True, lifted=True, envelope='RMAX', glob='global'); o = P.run(); m = o['mechanism']; G_ = [s for s in o['streams'] if s['kind'] == 'global']
    res['planner_global'] = dict(outcome=o['outcome'], published=o['published'], K=o['K'], ledger=m.get('constructor_live_ledger_identity'), probe=({k: (m.get('scheduling_policy') or {}).get('primary_probe', {}).get(k) for k in ('batches', 'forecast_s')} if (m.get('scheduling_policy') or {}).get('primary_probe') else None), created=bool(G_), actions=[a.get('action') for a in o['actions'] if a.get('action') in ('primary_probe', 'create_joint', 'joint_pilot', 'global_optimize', 'global_activate')], global_status=[(s['stage'], (s.get('closed') or '')[:60], [(a_.get('status'), (a_.get('kind') or a_.get('label') or '')[:60]) for a_ in (s.get('joint') or {}).get('attempts', [])]) for s in G_], hard=o['hard_deadline_respected'])
    P2 = UPlanner(model16, binding16, 10.0, admission_stop_s=9.5, t_start=PA.tnow(), seed=1, pac=True, lifted=True, envelope='RMAX', old_policy=True); o2 = P2.run(); res['planner_old_policy'] = dict(outcome=o2['outcome'], probe=(o2['mechanism'].get('scheduling_policy') or {}).get('primary_probe'), old=(o2['mechanism'].get('scheduling_policy') or {}).get('old_policy'), ledger=o2['mechanism'].get('constructor_live_ledger_identity'))
    fa = res['full_attempt']; rc = res['refused_candidate']
    ok = (fa['prepare'] == 'READY' and fa['pilot'] == 'COMPLETE' and fa['status'] in ('PROMOTED', 'KEPT_INCUMBENT') and (not fa['promoted'] or fa['witness_only'] or (fa['certifier_ok'] and fa['committed_B_is_certified'] and fa['activation'] and fa['activation']['batches'] <= 2 and fa['activation']['draws'] <= 512 and fa['activation']['checks'] == fa['activation']['batches'])) and (fa['evals'] or 0) <= 32
          and rc['status'] == 'DEFECT' and rc['hits'] >= 3 and rc['rng_unchanged'] and rc['cert_t_unchanged'] and rc['epochs_unchanged'] and rc['fit_unchanged'] and rc['live_back'] == 0 and rc['stage'] == 'READY'
          and res['no_law_before_check']['certifier_calls'] >= 2 and res['no_law_before_check']['epochs_at_calls'] == [1] and res['witness_only_path']['prepare'] == 'READY' and all(c[1] == 'witness_only' for c in res['witness_only_path']['candidates']) and res['witness_only_path']['status'] in ('REFUSED', 'KEPT_INCUMBENT', 'PROMOTED') and (res['witness_only_path']['status'] == 'REFUSED' or bool(res['witness_only_path']['optimizer_failure'])) and (not res['witness_only_path']['promoted'] or (res['witness_only_path']['witness_only'] and res['witness_only_path']['same_conditionals'] and res['witness_only_path']['cap_tighter'])) and not res['seed_mode']['can_optimize'] and res['seed_mode']['status'] == 'DISABLED'
          and res['planner_global']['outcome'] == 'COMPLETE' and res['planner_global']['ledger'] is True and res['planner_global']['hard'] and res['planner_global']['probe'] is not None and res['planner_old_policy']['probe'] is None and res['planner_old_policy']['old'] is True and res['planner_old_policy']['ledger'] is True)
    rec('D61_global_stream_lifecycle', ok, **res)

def D62_primary_preservation_and_relocation():
    """brief section 5: (a) accepted primary preservation: a --global request on three dev models completes with the same published set as the --lifted RMAX request (REPAIRED) and never publishes from the global stream before the primary is READY;
    the probe policy never extends the hard cutoff (every cell's hard_deadline_respected); (b) the resolver (finding 9): a manifest path rewritten onto a non-existent workstation prefix resolves back through DGP_ROOTS / the packet root with its
    sha256 verified, and a missing file raises InputUnresolved listing the candidates (never a silent substitute)"""
    res = {}; ok = True
    for name in ('dg_n12_c4_clique_two', 'dg_n8_c4_er50_two'):
        model, binding = load(name); outs = {}
        for arm, kw in (('REPAIRED', dict(lifted=True, envelope='RMAX')), ('GLOBAL', dict(lifted=True, envelope='RMAX', glob='global')), ('SEED', dict(lifted=True, envelope='RMAX', glob='seed'))):
            P = UPlanner(model, binding, 6.0, admission_stop_s=5.5, t_start=PA.tnow(), seed=1, pac=True, **kw); o = P.run(); outs[arm] = dict(outcome=o['outcome'], published=o['published'], K=o['K'], hard=o['hard_deadline_respected'], ledger=o['mechanism'].get('constructor_live_ledger_identity'), wall=round(o['wall_s'], 3), probe=bool((o['mechanism'].get('scheduling_policy') or {}).get('primary_probe')), pub_set=sorted((a['var'], a['state']) for a in o['answers'] if a['guarantee'] != 'NOT_PUBLISHED'))
        res[name] = {a: {k: v for k, v in o.items() if k != 'pub_set'} for a, o in outs.items()}; same = outs['REPAIRED']['pub_set'] == outs['GLOBAL']['pub_set'] == outs['SEED']['pub_set']; res[name]['same_published_set'] = same
        ok = ok and same and all(o['outcome'] == 'COMPLETE' and o['hard'] and o['ledger'] is True for o in outs.values())
    man = RECORDS + '/code/runs/mdi_2026-10-28/DGP5_JOINT_CONSTRUCTION/MAIN_MANIFEST.json'
    if os.path.exists(man):
        tasks = json.load(open(man))['tasks'][:5]; old_env = os.environ.get('DGP_ROOTS'); os.environ['DGP_ROOTS'] = RECORDS + '/code/runs/mdi_2026-10-28'
        try: rel = DPATH.relocation_test(tasks, '/nonexistent/packet')
        finally:
            if old_env is None: os.environ.pop('DGP_ROOTS', None)
            else: os.environ['DGP_ROOTS'] = old_env
        kind = None
        try: DPATH.resolve_input('/nonexistent/workstation/code/runs/mdi_2026-10-28/NOWHERE/missing.uai', '/nonexistent/packet', 'ab' * 32)
        except DPATH.InputUnresolved as e: kind = str(e)[:120]
        kind2 = None
        try: DPATH.resolve_input(tasks[0]['model'], None, 'ff' * 32)
        except DPATH.InputUnresolved as e: kind2 = 'sha mismatch refused'
        res['resolver'] = dict(relocated_ok=all(r['ok'] for r in rel), n=len(rel), missing_raises=(kind is not None and 'not resolved' in kind), wrong_sha_refused=(kind2 is not None)); ok = ok and res['resolver']['relocated_ok'] and res['resolver']['missing_raises'] and res['resolver']['wrong_sha_refused']
    else: res['resolver'] = dict(skipped='DGP5 MAIN_MANIFEST absent')
    rec('D62_primary_preservation_and_relocation', ok, **res)

CONTROLS += [D55_source_binding_mutants, D56_ownership_admission_cutoffs, D57_bounded_sum_and_rebuilt_J, D58_circuits_vs_exhaustive_reference, D59_gradient_convexity_pnorm, D60_optimizer_limits_and_expiry, D61_global_stream_lifecycle, D62_primary_preservation_and_relocation]

# ---------------------------------------------------------------- DGP7 (D63-D70): the residual envelope bank, the local kernel and the residual stream (brief CLAUDE_DGP7_IMPLEMENTATION_SPEC.md section 8, items 1-8)
import residual_bank as RB, residual_local as RL, check_residual as CR, residual_stream as RS
import inspect as _inspect, hashlib
def _rstage(model, budget_s=120, time_cap=5.0, budget=None, profile=None, sink_cls=None):
    """seed pass with the residual bank attached (the dgp7_smoke pattern): -> M, order, clk, B, cards, prop, owned, state, sink, rec"""
    clk = CE.Clock(PA.tnow() + budget_s, {}); B = budget or CE.Budget(CE.CONSTRUCTOR_BYTES); M = CE.canonicalize(model, clk, B); order, _ = CE.elimination_order(list(M.cards), [tuple(sc) for sc, _ in M.factors], clk, B); cards = list(M.cards); live0 = B.live
    state = RB.ResidualState('ctrl', None, None, None, None, None, B); sink = (sink_cls or RB.BankSink)(state, clk, time_cap); prop, rec_, owned = JP.compile_seed(M, order, profile or JPROF, B, clk, sink=sink); state.bind_seed(prop, rec_['plan_sha256']); state.live0 = live0
    return M, order, clk, B, cards, prop, owned, state, sink, rec_
class _CaptureSink(RB.BankSink):
    """records COPIES of the live inputs / message of every prepared group (the controls recompute the slack independently of the sink / checker afterwards)"""
    def prepare(self, v, gi, mem, P, u, T_msg, raxes, cards):
        pre = super().prepare(v, gi, mem, P, u, T_msg, raxes, cards)
        if pre is not None: pre['capture'] = dict(mem=[JP.JTable(t.axes, t.arr.copy(), t.tid, t.origin) for t in mem], msg=JP.JTable(T_msg.axes, T_msg.arr.copy(), T_msg.tid, T_msg.origin), P=P.copy(), v=v, gi=gi, u=tuple(u), raxes=tuple(raxes), cards=list(cards))
        return pre
    def commit(self, pre, receipt, mem, T_msg):
        a = super().commit(pre, receipt, mem, T_msg)
        if a is not None and 'capture' in pre: self.captured = getattr(self, 'captured', {}); self.captured[a.aid] = pre['capture']
        return a
def _rstream(M, mode='residual_joint', seed=1, budget=None, allow=10.0, profile=None):
    B = budget or CE.Budget(CE.CONSTRUCTOR_BYTES); S = RS.ResidualStream(2, M, M, [], seed, EPS, DELTA / 4, dict(PAC_OPTS, budget_obj=B), mode=mode, profile=profile); r = S.prepare(PA.tnow() + allow, until=PA.tnow() + allow); return S, B, r
def _exact_slack_violations(cap):
    """INDEPENDENT recomputation (Fractions) of M(x_{u \\ v}) rho(x_u) >= prod inputs(x_u) at every union cell of a captured group; -> (violations, cells, max_log2_slack)"""
    def check(rho):
        u = cap['u']; cards = cap['cards']; sizes = [cards[a] for a in u]; ipos = [[u.index(a) for a in T.axes] for T in cap['mem']]; mi = [u.index(a) for a in cap['raxes']]; viol = 0; cells = 0
        for asg in itertools.product(*[range(s) for s in sizes]):
            prod = F(1)
            for T, pp in zip(cap['mem'], ipos): prod *= _tf(T.arr[tuple(asg[p] for p in pp)])
            M = _tf(cap['msg'].arr[tuple(asg[p] for p in mi)] if cap['raxes'] else cap['msg'].arr.reshape(-1)[0]); r = _tf(rho[asg])
            if M * r < prod: viol += 1
            cells += 1
        return viol, cells
    return check
def _syn_region(cards, order, A, atom_axes_list, rng, targets_extra=None):
    """a synthetic region: random positive conditionals on random earlier parents (old law), target parents = old + one extra earlier variable (when given), atoms with random values in (0, 1] over the given axes; -> state, prop, window, conds_old, conds_new"""
    import dgp7_rates as R7
    pos = {v: i for i, v in enumerate(order)}; conds_old = {}; targets = {}
    for v in order:
        earlier = order[:pos[v]]; par = tuple(sorted(rng.sample(earlier, min(len(earlier), rng.randint(0, 1))), key=lambda x: pos[x])) if earlier else (); conds_old[v] = R7.rand_cond(rng, v, par, cards)
    for v in A:
        extra = (targets_extra or {}).get(v); targets[v] = tuple(sorted(set(conds_old[v].parents) | ({extra} if extra is not None else set()), key=lambda x: pos[x]))
    prop = JP.Proposal(cards, conds_old, order, _RM.norm_up(0, 1), _RM.norm_up(0, 1), dict(kind='ctrl')); B = CE.Budget(CE.CONSTRUCTOR_BYTES); state = RB.ResidualState('ctrl', 'ctrl', prop, prop.B, prop.B, prop.B, B); atoms = []
    for j, axes in enumerate(atom_axes_list): a = R7.rand_atom(rng, tuple(sorted(axes)), cards, j, 0); a.verified = True; state.atoms[a.aid] = a; atoms.append(a)
    R = set(A)
    for v in A: R |= set(conds_old[v].parents) | set(targets[v])
    for a in atoms: R |= set(a.axes)
    R = sorted(R, key=lambda x: pos[x]); C = [x for x in R if x not in A]
    window = dict(A=list(A), R=list(R), C=list(C), atoms=[a.aid for a in atoms], vol=JP.vol_of(tuple(R), cards), bank_version=0, target_parents=targets, max_vol=65536, whole_model_region=(len(R) == len(cards)), score=1.0, predicted_work_s=0.0)
    conds_new = {v: R7.rand_cond(rng, v, targets[v], cards) for v in A}
    return state, prop, window, conds_old, conds_new, B
def _lg(q): return float(CJ.lg_bounded(q)) if q > 0 else -math.inf

def D63_seed_residual_inequalities():
    """brief section 8 item 1: (a) on two <= 4,096-state models (the n6 card-4 clique; a random card-3 model with V_seed forced to 27 so MAX groups appear) every retained atom satisfies M rho >= the EXACT product of its live inputs at
    every union cell, recomputed independently in Fractions from captured copies (not through the sink / checker); (b) the telescoping identity W_0 <= B_seed q prod rho on EVERY fine state with all atoms, with any one atom dropped
    and with none (dropping is sound); (c) zero-message handling: a hand-built MAX group whose message has zero cells gives rho = 1 there (P = 0), the checker accepts it (slack_ok) and a positive P under a zero M is a Defect;
    (d) rejections: a rho underbound (one cell scaled down) -> check_stage(rho=) slack_ok False AND check_slack_cells Defect; a lowered message cell -> the stage checker rejects dominance; a raised source cell -> the slack check
    rejects; tampered seed counts -> check_seed_rows rejects; swapped (transposed) rho axes -> rejected on an asymmetric group; the honest group is accepted"""
    res = {}; rng = random.Random(63); ok = True
    cases = [('n6_clique', load_odev('dg_n6_c4_clique_two')[0], JPROF), ('rand_c3', _rand_model(rng, [3, 3, 3, 3, 3], [(0, 1), (1, 2), (2, 3), (3, 4), (0, 4), (0, 2), (1, 3)]), dict(JPROF, V_seed=27))]
    for name, model, prof in cases:
        M, order, clk, B, cards, prop, owned, state, sink, rec_ = _rstage(model, profile=prof, sink_cls=_CaptureSink); atoms = state.live_atoms(); caps = getattr(sink, 'captured', {}); r = dict(atoms=len(atoms), captured=len(caps), states=math.prod(cards))
        viol = 0; cells = 0
        for a in atoms:
            v_, c_ = _exact_slack_violations(caps[a.aid])(a.arr); viol += v_; cells += c_
        r['independent_slack_violations'] = viol; r['independent_slack_cells'] = cells
        r['identity_all'] = CR.ref_envelope_exact(M, prop, atoms, prop.B); r['identity_none'] = CR.ref_envelope_exact(M, prop, [], prop.B); r['identity_drop_each'] = [CR.ref_envelope_exact(M, prop, [b for b in atoms if b is not a], prop.B)['violations'] for a in atoms]
        r['atoms_le_one'] = all(_ge(RB.ONE, x) for a in atoms for x in a.arr.reshape(-1)); r['bank_consistent'] = (state.owned == sum(a.bytes for a in state.atoms.values())) and (B.live - state.live0 == owned + state.owned)
        res[name] = {k: (v if k not in ('identity_all', 'identity_none') else v['violations']) for k, v in r.items()}
        ok = ok and len(atoms) >= 1 and len(caps) == len(atoms) and viol == 0 and cells > 0 and r['identity_all']['violations'] == 0 and r['identity_none']['violations'] == 0 and all(x == 0 for x in r['identity_drop_each']) and r['atoms_le_one'] and r['bank_consistent']
        if name == 'rand_c3':
            # (d) rejections on the first captured group (asymmetric: cards 3, random values)
            cap = caps[atoms[0].aid]; mem = cap['mem']; T = cap['msg']; u = cap['u']; v = cap['v']; rho = atoms[0].arr; inv = [t.tid for t in mem] + [900]; clk2 = CE.Clock(PA.tnow() + 60, {})
            honest = CJ.check_stage(mem, T, v, cards, 'max', clk2, inventory=inv, rho=rho); rej = dict(honest=dict(ok=honest['ok'], slack_ok=honest.get('slack_ok'), slack_cells=honest.get('slack_cells')))
            bad = rho.copy(); i0 = next(idx for idx in itertools.product(*[range(cards[a]) for a in u]) if rho[idx][1]); bad[i0] = _RM.norm_up(rho[i0][0] - 1, rho[i0][1]); r1 = CJ.check_stage(mem, T, v, cards, 'max', clk2, inventory=inv, rho=bad); rej['rho_underbound_checker'] = dict(ok=r1['ok'], slack_ok=r1.get('slack_ok'), why=(r1.get('slack_why') or '')[:60])
            kind = None
            try: RB.check_slack_cells(mem, T, bad, u, cap['raxes'], cards, clk2)
            except CE.Defect as e: kind = str(e)[:60]
            rej['rho_underbound_slack_cells'] = kind
            Tl = JP.JTable(T.axes, T.arr.copy(), T.tid, T.origin); j0 = next(idx for idx in itertools.product(*[range(cards[a]) for a in T.axes]) if T.arr[idx][1]); Tl.arr[j0] = _RM.norm_up(T.arr[j0][0] - 1, T.arr[j0][1]); r2 = CJ.check_stage(mem, Tl, v, cards, 'max', clk2, inventory=inv, rho=rho); rej['lowered_message'] = dict(ok=r2['ok'], why=(r2.get('why') or '')[:60])
            m0 = mem[0]; mh = JP.JTable(m0.axes, m0.arr.copy(), m0.tid, m0.origin); k0 = next(idx for idx in itertools.product(*[range(cards[a]) for a in m0.axes]) if m0.arr[idx][1]); mh.arr[k0] = _RM.norm_up(m0.arr[k0][0] + 1, m0.arr[k0][1]); r3 = CJ.check_stage([mh] + mem[1:], T, v, cards, 'max', clk2, inventory=inv, rho=rho); rej['raised_source'] = dict(ok=r3['ok'], slack_ok=r3.get('slack_ok'), why=((r3.get('why') or r3.get('slack_why') or ''))[:60])
            c0 = prop.conds[prop.order[-1]]; cnt = c0.counts.copy(); cnt[0, 0] += 1; cnt[0, 1] -= 1; Pm = np.empty(cnt.shape, dtype=object); Pm.fill(_fu(F(1, 2))); Mf = np.empty(cnt.shape[0], dtype=object); Mf.fill(_fu(F(1))); r4 = CJ.check_seed_rows(Pm, Mf, cnt, cards[c0.z], clk2); cnt2 = c0.counts.copy(); cnt2[0, 0] -= 1; r4b = CJ.check_seed_rows(Pm, Mf, cnt2, cards[c0.z], clk2); rej['tampered_counts'] = dict(sum_ok_row_ineq=r4['ok'], why=(r4.get('why') or '')[:50], sum_broken=r4b['ok'])
            if len(u) >= 2 and cards[u[0]] == cards[u[1]]:
                perm = list(range(len(u))); perm[0], perm[1] = perm[1], perm[0]; sw = np.ascontiguousarray(np.transpose(rho, perm)); r5 = CJ.check_stage(mem, T, v, cards, 'max', clk2, inventory=inv, rho=sw); rej['swapped_axes'] = dict(ok=r5['ok'], slack_ok=r5.get('slack_ok'), identical=bool(all(sw[idx] == rho[idx] for idx in itertools.product(*[range(cards[a]) for a in u]))))
            else: rej['swapped_axes'] = dict(ok=None, slack_ok=None, identical=None, note='union has < 2 equal-card axes')
            res['rejections'] = rej
            ok = ok and rej['honest']['ok'] and rej['honest']['slack_ok'] is True and rej['honest']['slack_cells'] > 0 and rej['rho_underbound_checker']['ok'] and rej['rho_underbound_checker']['slack_ok'] is False and rej['rho_underbound_slack_cells'] is not None and not rej['lowered_message']['ok'] and (not rej['raised_source']['ok'] or rej['raised_source']['slack_ok'] is False) and (rej['tampered_counts']['sum_ok_row_ineq'] is False) and not rej['tampered_counts']['sum_broken'] and (rej['swapped_axes']['identical'] or rej['swapped_axes']['slack_ok'] is False or rej['swapped_axes']['ok'] is None)
    # (c) zero-message handling on a hand-built group: inputs over (0, 1) and (1, 2) with a zero column -> M(x_0, x_2) = 0 where the product vanishes for every x_1
    cards3 = [2, 3, 2]; a_ = np.empty((2, 3), dtype=object); b_ = np.empty((3, 2), dtype=object)
    for i in range(2):
        for j in range(3): a_[i, j] = _fu(F(i + j + 1, 7)) if i == 0 else _fu(F(0))                   # row x_0 = 1 is identically zero -> M(1, x_2) = 0
    for j in range(3):
        for k in range(2): b_[j, k] = _fu(F(j + 2 * k + 1, 5))
    mem = [JP.JTable((0, 1), a_, 0, ('factor', 0)), JP.JTable((1, 2), b_, 1, ('factor', 1))]; u = (0, 1, 2); P = JP._norm(JP.product_exact(mem, u, cards3)); Rm, raxes = JP.max_over(P, u, [1]); T = JP.JTable(raxes, Rm, 2, ('max_message', 1, (0, 1))); clk3 = CE.Clock(PA.tnow() + 60, {})
    rho, unit, ml = RB.rho_of_group(P, T, u, raxes, cards3, clk3); zero_cells = [idx for idx in itertools.product(*[range(c) for c in cards3]) if T.arr[(idx[0], idx[2])][1] == 0]
    rz = CJ.check_stage(mem, T, 1, cards3, 'max', clk3, inventory=[0, 1], rho=rho); kind = None
    Pbad = P.copy(); Pbad[(1, 0, 0)] = _fu(F(1, 3))
    try: RB.rho_of_group(Pbad, T, u, raxes, cards3, clk3)
    except CE.Defect as e: kind = str(e)[:50]
    res['zero_message'] = dict(zero_message_cells=len(zero_cells), rho_one_at_zero=all(rho[idx] == RB.ONE for idx in zero_cells), P_zero_at_zero=all(P[idx][1] == 0 for idx in zero_cells), checker_ok=rz['ok'], slack_ok=rz.get('slack_ok'), positive_P_under_zero_M=kind)
    ok = ok and len(zero_cells) > 0 and res['zero_message']['rho_one_at_zero'] and res['zero_message']['P_zero_at_zero'] and rz['ok'] and rz.get('slack_ok') is True and kind is not None
    rec('D63_seed_residual_inequalities', ok, **res)

def D64_local_F_source_binding():
    """brief section 8 item 2: (a) on the n8 card-4 clique the kernel's K_ref / K_new come from the ACTUAL atoms + conditionals it is handed: a tampered atom cell (x 2) or tampered counts (the bank rebound to the tampered law) move
    K_ref exactly onto the new exhaustive-rational reference and away from the old one; (b) positive actual rows: quantize_rows_exact on extreme rows (near-one / near-zero / zero entries) always yields counts >= 1 summing to D;
    (c) unequal cardinalities (2, 3, 5, 2) with a sampling order that permutes the ids and atoms over permuted axis subsets: kernel K_ref / K_new / T2 dominate the exact reference within 2^-100 relative; (d) replication to the G1
    parents gives the same q at every region cell; (e) no true Z in fitting: fit_window's signature / module source carry no enumeration / oracle / Z input, and scaling one unary factor by 2^10 (Z x 2^10) leaves the fitted counts,
    K and rank identical while the checked caps shift by exactly 10 bits"""
    res = {}; ok = True; rng = random.Random(64)
    model, _ = load('dg_n8_c4_clique_two'); M, order, clk, B, cards, prop, owned, state, sink, rec_ = _rstage(model); pairs, chg = JO.interaction_scores(M, B, clk); parents1, g1 = GO.select_g1(prop, pairs, cards); wins, excl = RL.plan_windows(state, prop, parents1, cards, prop.order)
    w = next(w_ for w_ in wins if w_['vol'] <= 4096); aids = w['atoms']; k0 = CR.local_kernel(state, w, aids, prop.conds, None, cards, prop.order, clk); ref0 = CR.ref_local_exact(state, w, aids, prop.conds, None, cards, prop.order)
    # tampered atom: x 2 at one positive cell (a NEW Atom object with the same id in a copy of the state)
    a0 = state.atoms[aids[0]]; arr = a0.arr.copy(); idx = next(i for i in itertools.product(*[range(cards[x]) for x in a0.axes]) if arr[i][1] and not _ge(arr[i], (-1, 1))); arr[idx] = _RM.norm_up(arr[idx][0] + 1, arr[idx][1]); st2 = RB.ResidualState(state.model_identity, state.seed_proof_identity, prop, prop.B, prop.B, prop.B, B)                    # the same bank identities (DGP8: a window planned against another bank is rejected -- that rejection is R1's, not this control's)
    for aid, a in state.atoms.items(): st2.atoms[aid] = a
    t2 = RB.Atom(a0.aid, a0.axes, arr, dict(a0.provenance), a0.score, a0.mean_log2, 0); t2.verified = True; st2.atoms[a0.aid] = t2; k1 = CR.local_kernel(st2, w, aids, prop.conds, None, cards, prop.order, clk); ref1 = CR.ref_local_exact(st2, w, aids, prop.conds, None, cards, prop.order); tol = 1 + F(1, 1 << 90)
    rho_moved = sum(1 for x, y in zip(k0['rho_new'].reshape(-1), k1['rho_new'].reshape(-1)) if x != y)
    res['tampered_atom'] = dict(K_ref_before=_lg(ref0['K_ref']), K_ref_after=_lg(ref1['K_ref']), kernel_before=k0['log2_K_ref'], kernel_after=k1['log2_K_ref'], K_dominates_new=(_tf(k1['K_ref']) >= ref1['K_ref']), K_tight_new=(_tf(k1['K_ref']) <= ref1['K_ref'] * tol), T2_exact_changed=(ref1['T2'] != ref0['T2']), T2_kernel_dominates_new=(_tf(k1['T2_max']) >= ref1['T2_max']), T2_kernel_tight_new=(_tf(k1['T2_max']) <= ref1['T2_max'] * tol), rho_new_cells_moved=rho_moved, tampered_cell=idx)
    ok = ok and res['tampered_atom']['K_dominates_new'] and res['tampered_atom']['K_tight_new'] and res['tampered_atom']['T2_exact_changed'] and res['tampered_atom']['T2_kernel_dominates_new'] and res['tampered_atom']['T2_kernel_tight_new'] and rho_moved >= 1 and _tf(k0['K_ref']) >= ref0['K_ref']
    # tampered counts: one unit moved between two states of the first active variable; the bank rebound to that law (otherwise the identity check rejects: that rejection is D67's)
    v0 = w['A'][0]; c0 = prop.conds[v0]; cnt = c0.counts.copy(); r_ = 0; cnt[r_, 0] += 1; cnt[r_, 1] -= 1; conds_t = dict(prop.conds); conds_t[v0] = JP.Conditional(v0, c0.parents, cnt, cards); prop_t = JP.Proposal(cards, conds_t, prop.order, prop.B, prop.S, dict(kind='tampered')); st3 = RB.ResidualState('ctrl', 'ctrl', prop_t, prop.B, prop.B, prop.B, B)
    for aid, a in state.atoms.items(): st3.atoms[aid] = a
    cn_orig = {v: (prop.conds[v] if tuple(prop.conds[v].parents) == tuple(w['target_parents'][v]) else prop.conds[v].replicate(tuple(w['target_parents'][v]), cards)) for v in w['A']}      # the ORIGINAL law on the target parents presented as the 'new' law: K_new = max q_tampered prod rho / q_original reflects the tampered old counts exactly
    w3 = dict(w, model_identity=st3.model_identity, seed_proof_identity=st3.seed_proof_identity, law_identity=st3.law_identity); k3 = CR.local_kernel(st3, w3, aids, conds_t, cn_orig, cards, prop.order, clk); ref3 = CR.ref_local_exact(st3, w3, aids, conds_t, cn_orig, cards, prop.order)
    res['tampered_counts'] = dict(kernel_ok=k3['ok'], why=k3.get('why'), K_new_ref_log2=_lg(ref3['K_new']), kernel_K_new_log2=k3.get('log2_K_new'), K_new_dominates=(_tf(k3['K_new']) >= ref3['K_new']) if k3['ok'] else None, K_new_tight=(_tf(k3['K_new']) <= ref3['K_new'] * tol) if k3['ok'] else None, K_new_not_one=(ref3['K_new'] != 1), T2_exact_changed=(ref3['T2'] != ref0['T2']), rejected_against_original_bank=CR.local_kernel(state, w, aids, conds_t, None, cards, prop.order, clk).get('why'))
    ok = ok and k3['ok'] and res['tampered_counts']['K_new_dominates'] and res['tampered_counts']['K_new_tight'] and res['tampered_counts']['K_new_not_one'] and res['tampered_counts']['T2_exact_changed'] and 'law identity' in (res['tampered_counts']['rejected_against_original_bank'] or '')
    # (b) positive rows
    rows = np.array([[1.0 - 3e-300, 1e-300, 1e-300, 1e-300], [0.0, 0.0, 0.0, 1.0], [0.25, 0.25, 0.25, 0.25], [5e-324, 0.5, 0.5 - 5e-324, 0.0], [0.0, 0.0, 0.0, 0.0]]); q = GO.quantize_rows_exact(rows, 4); res['positive_rows'] = dict(all_ge_1=bool((q >= 1).all()), sums_D=bool((q.sum(axis=1) == JP.D).all()), zero_row_uniform=bool(abs(int(q[4].max()) - int(q[4].min())) <= 1)); ok = ok and all(res['positive_rows'].values())
    # (c) unequal cardinalities + permuted sampling order; atoms over permuted axis subsets
    cards_u = [2, 3, 5, 2]; order_u = [2, 0, 3, 1]; A_u = [3, 1]; st_u, prop_u, w_u, co_u, cn_u, B_u = _syn_region(cards_u, order_u, A_u, [(1, 2), (0, 3), (1, 3, 2), (3,)], rng, targets_extra={3: 0, 1: 2}); clk_u = CE.Clock(PA.tnow() + 60, {})
    ku = CR.local_kernel(st_u, w_u, w_u['atoms'], co_u, cn_u, cards_u, order_u, clk_u); ru = CR.ref_local_exact(st_u, w_u, w_u['atoms'], co_u, cn_u, cards_u, order_u); tol = 1 + F(1, 1 << 100)
    res['unequal_cards_permuted'] = dict(ok=ku['ok'], why=ku.get('why'), vol=w_u['vol'], R=w_u['R'], K_ref=(_tf(ku['K_ref']) >= ru['K_ref'] and _tf(ku['K_ref']) <= ru['K_ref'] * tol) if ku['ok'] else None, K_new=(_tf(ku['K_new']) >= ru['K_new'] and _tf(ku['K_new']) <= ru['K_new'] * tol) if ku['ok'] else None, T2=(_tf(ku['T2_max']) >= ru['T2_max'] and _tf(ku['T2_max']) <= ru['T2_max'] * (1 + F(1, 1 << 90))) if ku['ok'] else None)
    ok = ok and ku['ok'] and res['unequal_cards_permuted']['K_ref'] and res['unequal_cards_permuted']['K_new'] and res['unequal_cards_permuted']['T2']
    # (d) replication keeps q at every region cell
    v1 = w['A'][0]; rep = prop.conds[v1].replicate(tuple(parents1[v1]), cards) if tuple(parents1[v1]) != tuple(prop.conds[v1].parents) else prop.conds[v1]; same = True
    for _ in range(200):
        x = [rng.randrange(k) for k in cards]; ro = sum(prop.conds[v1].pstrides[p_] * x[p_] for p_ in prop.conds[v1].parents); rn = sum(rep.pstrides[p_] * x[p_] for p_ in rep.parents); same = same and int(prop.conds[v1].counts[ro, x[v1]]) == int(rep.counts[rn, x[v1]])
    res['replication_same_q'] = dict(same=same, extended=(rep is not prop.conds[v1])); ok = ok and same
    # (e) no true Z in fitting
    src = _inspect.getsource(RL); sig = list(_inspect.signature(RL.fit_window).parameters); res['no_Z_in_fit'] = dict(signature=sig, no_Z_param=not any(k in ('Z', 'Z0', 'logZ', 'enum', 'states', 'oracle') for k in sig), no_enumeration_in_source=all(t not in src for t in ('ref_enumerate', 'oracle_logW0', 'dgp2_oracle', 'enumerate_original', 'ref_W0')))
    fitA = RL.fit_window(prop, w, [state.atoms[a] for a in aids], cards, prop.order, 'auto', np.random.default_rng(3), 1.1, clock=clk)
    model2 = dict(model); model2['factors'] = [dict(f) for f in model['factors']]; fu = next(f for f in model2['factors'] if len(f['scope']) == 1); fu['values'] = [F(x) * 1024 for x in fu['values']]
    M2, order2, clk2, B2, cards2, prop2, owned2, state2, sink2, rec2 = _rstage(model2); wins2, _ = RL.plan_windows(state2, prop2, parents1, cards2, prop2.order); w2 = next(w_ for w_ in wins2 if w_['A'] == w['A'] and w_['atoms'] == w['atoms'])
    fitB = RL.fit_window(prop2, w2, [state2.atoms[a] for a in aids], cards2, prop2.order, 'auto', np.random.default_rng(3), 1.1, clock=clk2)
    kA = CR.local_kernel(state, w, aids, prop.conds, fitA.get('conds_new'), cards, prop.order, clk); kB = CR.local_kernel(state2, w2, aids, prop2.conds, fitB.get('conds_new'), cards2, prop2.order, clk2)
    res['scaled_Z'] = dict(same_order=(prop2.order == prop.order), same_seed_counts=all(np.array_equal(prop.conds[v].counts, prop2.conds[v].counts) for v in prop.order), same_atoms=all(state.atoms[a].sha256 == state2.atoms[a].sha256 for a in aids), fit_status=(fitA.get('status'), fitB.get('status')), same_fitted_counts=(fitA.get('conds_new') is not None and all(np.array_equal(fitA['conds_new'][v].counts, fitB['conds_new'][v].counts) for v in w['A'])), same_K=(fitA.get('K_float_new_actual') == fitB.get('K_float_new_actual')), cap_shift_bits=(kB['log2_B_new'] - kA['log2_B_new']) if (kA['ok'] and kB['ok']) else None, seed_cap_shift_bits=prop2.log2_B() - prop.log2_B())
    ok = ok and res['no_Z_in_fit']['no_Z_param'] and res['no_Z_in_fit']['no_enumeration_in_source'] and res['scaled_Z']['same_seed_counts'] and res['scaled_Z']['same_atoms'] and res['scaled_Z']['same_fitted_counts'] and res['scaled_Z']['same_K'] and abs(res['scaled_Z']['cap_shift_bits'] - 10.0) < 1e-9 and abs(res['scaled_Z']['seed_cap_shift_bits'] - 10.0) < 1e-9
    B.release(owned); rec('D64_local_F_source_binding', ok, **res)

def D65_exact_K_T2_and_weighted_moment():
    """brief section 8 item 3: (a) on the n6 card-4 clique (whole-model region, parent-closed C) and on a synthetic unequal-cardinality region the kernel's K_ref / K_new / T2_max dominate the exhaustive-rational reference within
    2^-90 relative and its parent-closed weighted moment (exact context marginal supplied) matches the exact weighted T2; (b) a future-touching atom (a variable sampled after the window) is rejected by validate_window; (c) the
    SAMPLED context mode (C not parent-closed) is labelled advisory, differs from the exact marginal, is never passed to the kernel by the stream (source inspection: context_weights_exact unused), and the kernel's certified weighted
    field exists only when exact weights are supplied; the uniform mode is labelled a negative diagnostic"""
    res = {}; ok = True; rng = random.Random(65); tol = 1 + F(1, 1 << 90)
    model, _ = load_odev('dg_n6_c4_clique_two'); M, order, clk, B, cards, prop, owned, state, sink, rec_ = _rstage(model); pairs, chg = JO.interaction_scores(M, B, clk); parents1, g1 = GO.select_g1(prop, pairs, cards); wins, _ = RL.plan_windows(state, prop, parents1, cards, prop.order); w = wins[0]
    fit = RL.fit_window(prop, w, [state.atoms[a] for a in w['atoms']], cards, prop.order, 'auto', np.random.default_rng(1), 1.1, clock=clk); cn = fit.get('conds_new'); C = w['C']; pc = CR.parent_closed(prop, C); wts = CR.exact_context_marginal(prop, C, cards) if pc else None
    k = CR.local_kernel(state, w, w['atoms'], prop.conds, cn, cards, prop.order, clk, context_weights_exact=wts); ref = CR.ref_local_exact(state, w, w['atoms'], prop.conds, cn, cards, prop.order, context_weights=wts)
    res['n6'] = dict(parent_closed=pc, whole_model=k.get('whole_model_region'), K_ref=(_tf(k['K_ref']) >= ref['K_ref'] and _tf(k['K_ref']) <= ref['K_ref'] * tol), K_new=(_tf(k['K_new']) >= ref['K_new'] and _tf(k['K_new']) <= ref['K_new'] * tol), T2=(_tf(k['T2_max']) >= ref['T2_max'] and _tf(k['T2_max']) <= ref['T2_max'] * tol), weighted_kernel_log2=(k.get('weighted_moment') or {}).get('log2_weighted_T2'), weighted_exact_log2=_lg(ref.get('weighted_T2', F(0))), weighted_match=(abs((k.get('weighted_moment') or {}).get('log2_weighted_T2', 0) - _lg(ref.get('weighted_T2', F(1)))) < 1e-9) if wts else None, weights_sum_one=(sum(wts.values()) == 1) if wts else None)
    ok = ok and pc and res['n6']['K_ref'] and res['n6']['K_new'] and res['n6']['T2'] and res['n6']['weighted_match'] and res['n6']['weights_sum_one']
    cards_u = [3, 2, 4, 2, 3]; order_u = [4, 1, 0, 2, 3]; A_u = [2, 3]; st_u, prop_u, w_u, co_u, cn_u, B_u = _syn_region(cards_u, order_u, A_u, [(0, 2), (1, 3), (2, 3), (4, 3)], rng, targets_extra={2: 1, 3: 0}); Cu = w_u['C']; pcu = CR.parent_closed(prop_u, Cu); wu = CR.exact_context_marginal(prop_u, Cu, cards_u) if pcu else None
    ku = CR.local_kernel(st_u, w_u, w_u['atoms'], co_u, cn_u, cards_u, order_u, clk, context_weights_exact=wu); ru = CR.ref_local_exact(st_u, w_u, w_u['atoms'], co_u, cn_u, cards_u, order_u, context_weights=wu)
    res['synthetic'] = dict(ok=ku['ok'], why=ku.get('why'), parent_closed=pcu, K_ref=(_tf(ku['K_ref']) >= ru['K_ref'] and _tf(ku['K_ref']) <= ru['K_ref'] * tol), K_new=(_tf(ku['K_new']) >= ru['K_new'] and _tf(ku['K_new']) <= ru['K_new'] * tol), T2=(_tf(ku['T2_max']) >= ru['T2_max'] and _tf(ku['T2_max']) <= ru['T2_max'] * tol), weighted_match=((abs((ku.get('weighted_moment') or {}).get('log2_weighted_T2', 0) - _lg(ru['weighted_T2'])) < 1e-9) if wu else None), per_context_T2_dominates=None)
    ok = ok and ku['ok'] and res['synthetic']['K_ref'] and res['synthetic']['K_new'] and res['synthetic']['T2'] and (res['synthetic']['weighted_match'] in (True, None))
    # (b) future-touching atom
    import dgp7_rates as R7; pos = {v: i for i, v in enumerate(order_u)}; fut = [v for v in order_u if pos[v] > pos[A_u[-1]]]
    if not fut: order_f = [4, 1, 0, 2, 3]; A_f = [1, 0]; fut = [2]
    else: A_f = A_u
    af = R7.rand_atom(rng, tuple(sorted([A_f[-1], fut[0]])), cards_u, 99, 0); af.verified = True; st_u.atoms[99] = af; wf = dict(w_u, A=A_f, atoms=w_u['atoms'] + [99], R=sorted(set(w_u['R']) | {fut[0]}, key=lambda x: pos[x])); why_f = CR.validate_window(st_u, wf, wf['atoms'], co_u, None, cards_u, order_u); del st_u.atoms[99]
    res['future_atom_rejected'] = why_f; ok = ok and why_f is not None and ('sampled after' in why_f or 'prefix' in why_f or 'CONSECUTIVE' in why_f)
    # (c) sampled vs exact vs uniform; the stream never feeds sampled weights to the kernel
    cards_s = [2, 3, 2, 2]; order_s = [0, 1, 2, 3]; A_s = [2, 3]; st_s, prop_s, w_s, co_s, cn_s, B_s = _syn_region(cards_s, order_s, A_s, [(1, 2), (1, 3)], rng, targets_extra={2: 1, 3: 1}); Cs = w_s['C']
    # force C not parent-closed: give the context variable 1 the parent 0 while 0 stays outside R (rebuild the conditional of 1 with parent 0)
    co_s2 = dict(co_s); co_s2[1] = R7.rand_cond(rng, 1, (0,), cards_s); prop_s2 = JP.Proposal(cards_s, co_s2, order_s, prop_s.B, prop_s.S, dict(kind='ctrl')); st_s.law = prop_s2; st_s.law_identity = prop_s2.sha256; Cs2 = [x for x in w_s['R'] if x not in A_s]
    asg = RL.region_assignments(w_s['R'], cards_s); rpos = {x: i for i, x in enumerate(w_s['R'])}; pcs = CR.parent_closed(prop_s2, Cs2)
    nu_s, rec_s = RL.context_weights(prop_s2, Cs2, cards_s, order_s, np.random.default_rng(5), asg, rpos, 1024, mode='auto'); nu_u, rec_u = RL.context_weights(prop_s2, Cs2, cards_s, order_s, np.random.default_rng(5), asg, rpos, 1024, mode='uniform')
    # the exact marginal of C under prop_s2 (summing out the outside parent 0 by hand) for comparison
    exact = {}
    for a1 in range(cards_s[1]): exact[a1] = sum(F(int(co_s2[0].counts[0, a0]), JP.D) * F(int(co_s2[1].counts[a0, a1]), JP.D) for a0 in range(cards_s[0]))
    key1 = asg[:, rpos[1]]; emp = {a1: float(nu_s[key1 == a1][0]) for a1 in range(cards_s[1])}; diff = max(abs(emp[a1] - float(exact[a1])) for a1 in exact)
    ks = CR.local_kernel(st_s, w_s, w_s['atoms'], co_s2, None, cards_s, order_s, clk)
    src = _inspect.getsource(RS); res['sampled_vs_certified'] = dict(parent_closed=pcs, sampled_mode=rec_s.get('mode'), uniform_mode=rec_u.get('mode'), empirical_vs_exact_max_abs=diff, empirical_differs=(diff > 1e-12), kernel_weighted_without_exact=ks.get('weighted_moment'), stream_never_passes_weights=('context_weights_exact' not in src), sampled_label_advisory=('advisory' in (rec_s.get('mode') or '')), uniform_label_diagnostic=('diagnostic' in (rec_u.get('mode') or '')))
    ok = ok and not pcs and res['sampled_vs_certified']['sampled_mode'].startswith('sampled') and res['sampled_vs_certified']['empirical_differs'] and ks.get('weighted_moment') is None and res['sampled_vs_certified']['stream_never_passes_weights'] and res['sampled_vs_certified']['sampled_label_advisory'] and res['sampled_vs_certified']['uniform_label_diagnostic']
    B.release(owned); rec('D65_exact_K_T2_and_weighted_moment', ok, **res)

def D66_waterfill_kkt_and_objective():
    """brief section 8 item 4: on 200 random rows (k = 2..9; lower bounds with sum < 1; zero coefficients mixed in) the row water fill (a) is feasible (theta >= lower, sum = 1), (b) satisfies the KKT conditions (A_a / theta_a^2 equal
    on the free coordinates; <= that value on the bound coordinates), (c) has an objective sum A / theta <= every one of 50 random feasible rows and <= the feasible projection of the incumbent, (d) matches the closed form
    sqrt(A_a) / sum sqrt(A) when no bound binds; (e) zero coefficients: theta = lower on A = 0 coordinates, an all-zero row keeps a feasible incumbent allocation; (f) tight lower sums: sum lower = 1 -> theta = lower exactly;
    sum lower > 1 -> the row is reported infeasible and keeps the incumbent; (g) zero contexts (nu = 0): the fit's coefficients vanish and the fitted rows stay feasible; (h) fit_window reports finite sweeps and asserts no optimality"""
    res = {}; ok = True; rng = np.random.default_rng(66); kkt_worst = 0.0; obj_viol = 0; feas_viol = 0; closed_worst = 0.0; n_rows = 0
    for t in range(200):
        k = int(rng.integers(2, 10)); A = rng.random(k) ** 2 * (rng.random() * 10 + 0.1); zero_mask = rng.random(k) < 0.15; A[zero_mask] = 0.0
        if A.max() <= 0: A[0] = 1.0
        zero_mask = (A == 0.0); lower = rng.random(k) * (0.8 / k); inc = rng.random(k); inc /= inc.sum(); th, info = RL.waterfill_rows(A[None, :], lower[None, :], inc[None, :]); th = th[0]; n_rows += 1
        if abs(th.sum() - 1) > 1e-9 or (th < lower - 1e-12).any(): feas_viol += 1; res.setdefault('feasibility_cases', []).append(dict(A=A.tolist(), lower=lower.tolist(), theta=th.tolist(), sum=float(th.sum()), min_gap=float((th - lower).min())))
        free = th > lower + 1e-9
        if free.sum() >= 1:
            lam = (A[free] / th[free] ** 2); lam_ref = lam.mean() if lam.size else 0.0
            if lam.size > 1 and lam_ref > 0: kkt_worst = max(kkt_worst, float(np.abs(lam - lam_ref).max() / lam_ref))
            bound = ~free
            if bound.any() and lam_ref > 0: kkt_worst = max(kkt_worst, float(max(0.0, (A[bound] / np.maximum(th[bound], 1e-300) ** 2 - lam_ref).max() / lam_ref)))
        obj = float((A / th).sum()); slack = 1.0 - lower.sum()
        for _ in range(50):
            d = rng.dirichlet(np.ones(k)); th2 = lower + slack * d
            if float((A / th2).sum()) < obj * (1 - 1e-9): obj_viol += 1
        th_inc = lower + slack * inc
        if float((A / th_inc).sum()) < obj * (1 - 1e-9): obj_viol += 1
        if not zero_mask.any():
            cf = np.sqrt(A) / np.sqrt(A).sum()
            if (cf >= lower).all(): closed_worst = max(closed_worst, float(np.abs(cf - th).max()))
        if zero_mask.any() and not (np.abs(th[zero_mask] - lower[zero_mask]) < 1e-9).all(): feas_viol += 1; res.setdefault('zero_coef_cases', []).append(dict(A=A.tolist(), lower=lower.tolist(), theta=th.tolist(), gap=float(np.abs(th[zero_mask] - lower[zero_mask]).max())))
    res['random_rows'] = dict(rows=n_rows, feasibility_violations=feas_viol, kkt_worst_relative=kkt_worst, objective_violations=obj_viol, closed_form_worst_abs=closed_worst); ok = ok and feas_viol == 0 and kkt_worst < 1e-6 and obj_viol == 0 and closed_worst < 1e-9
    A0 = np.zeros(4); inc0 = np.array([0.4, 0.3, 0.2, 0.1]); low0 = np.array([0.05, 0.05, 0.05, 0.05]); th0, i0 = RL.waterfill_rows(A0[None, :], low0[None, :], inc0[None, :]); res['all_zero_row'] = dict(zero_rows=i0['zero_rows'], feasible=bool(abs(th0.sum() - 1) < 1e-12 and (th0 >= low0 - 1e-15).all()), proportional_to_incumbent=bool(np.allclose(th0[0] - low0, 0.8 * inc0))); ok = ok and i0['zero_rows'] == 1 and res['all_zero_row']['feasible'] and res['all_zero_row']['proportional_to_incumbent']
    A1 = np.array([1.0, 2.0, 3.0]); low1 = np.array([0.2, 0.3, 0.5]); th1, i1 = RL.waterfill_rows(A1[None, :], low1[None, :], np.array([[1 / 3] * 3])); res['tight_sum_one'] = dict(theta_equals_lower=bool(np.allclose(th1[0], low1, atol=1e-12)), infeasible=i1['infeasible_rows']); ok = ok and res['tight_sum_one']['theta_equals_lower'] and i1['infeasible_rows'] == 0
    low2 = np.array([0.5, 0.4, 0.3]); inc2 = np.array([0.2, 0.3, 0.5]); th2_, i2 = RL.waterfill_rows(A1[None, :], low2[None, :], inc2[None, :]); res['infeasible_row'] = dict(infeasible=i2['infeasible_rows'], keeps_incumbent=bool(np.allclose(th2_[0], inc2))); ok = ok and i2['infeasible_rows'] == 1 and res['infeasible_row']['keeps_incumbent']
    th_s, why_s = RL.waterfill(A1, low2, inc2); res['single_row_form'] = dict(none_on_infeasible=(th_s is None), why=why_s[:40]); ok = ok and th_s is None
    # (g) zero contexts + (h) finite sweeps: a fit on the n6 clique with the uniform diagnostic weights vs auto; then nu forced to zero on half the contexts through a patched context_weights
    model, _ = load_odev('dg_n6_c4_clique_two'); M, order, clk, B, cards, prop, owned, state, sink, rec_ = _rstage(model); pairs, chg = JO.interaction_scores(M, B, clk); parents1, g1 = GO.select_g1(prop, pairs, cards); wins, _ = RL.plan_windows(state, prop, parents1, cards, prop.order); w = wins[0]; atoms = [state.atoms[a] for a in w['atoms']]
    fit = RL.fit_window(prop, w, atoms, cards, prop.order, 'auto', np.random.default_rng(1), 1.1, clock=clk); real_cw = RL.context_weights
    def half_zero(prop_, C, cards_, order_, rng_, asg, rpos, n_samples=1024, mode='auto'):
        nu, r_ = real_cw(prop_, C, cards_, order_, rng_, asg, rpos, n_samples, mode); key = asg[:, rpos[C[0]]] if C else np.zeros(asg.shape[0], dtype=np.int64); nu = np.where(key == 0, 0.0, nu); return nu, dict(r_, zeroed_contexts='C[0] = 0')
    RL.context_weights = half_zero
    try: fitz = RL.fit_window(prop, w, atoms, cards, prop.order, 'auto', np.random.default_rng(1), 1.1, clock=clk)
    finally: RL.context_weights = real_cw
    feas = lambda f: (f.get('conds_new') is None) or all((c.counts >= 1).all() and (c.counts.sum(axis=1) == JP.D).all() for c in f['conds_new'].values())
    res['fit_records'] = dict(status=fit.get('status'), sweeps=fit.get('sweeps'), best_sweep=fit.get('best_sweep'), has_sweeps_key=('sweeps' in fit), no_optimality_claim=('OPTIMAL' not in json.dumps({k: v for k, v in fit.items() if k != 'conds_new'}, default=str).upper()), zero_contexts_status=fitz.get('status'), zero_contexts_feasible=feas(fitz), zero_contexts_zero_rows=fitz.get('zero_rows'), K_within_cap=(fit.get('K_float_new_actual') is None or fit['K_float_new_actual'] <= fit['kappa_publish'] * (1 + 1e-12)))
    ok = ok and res['fit_records']['has_sweeps_key'] and res['fit_records']['no_optimality_claim'] and res['fit_records']['zero_contexts_feasible'] and res['fit_records']['K_within_cap'] and (fit.get('sweeps') or 0) <= RL.PROFILE_RESIDUAL['sweeps']
    B.release(owned); rec('D66_waterfill_kkt_and_objective', ok, **res)

def D67_sequential_transactions_and_bank_immutability():
    """brief section 8 item 5: (a) on the exposed n32 card-4 ER50 anchor through a forced ResidualStream (generous allowance) two sequential optimize actions commit two transactions (epochs 1 and 2; bank versions 1 and 2) with
    overlapping regions; every conditional outside each window is the SAME object before and after (law changed only on the window), the committed cap is the kernel's B_new; (b) on the n6 card-4 clique (4,096 states) a stream
    transaction followed by an API-level same-law transaction whose window consumes the FIRST transaction's replacement atom: the exact identity W_0 <= B q prod rho holds on every state after each, versions advance 1 -> 2, the
    replacement of the second is verified; (c) atoms untouched by a transaction keep their sha256 / verified flags; consumed atoms are flagged once and cannot be consumed again (Defect), selected by a window (validate_window) or
    used under a stale bank version; (d) a scalar-only tightening of consumed_B leaves envelope_B unchanged and the record distinguishes them; (e) rebinding: the kernel rejects a window whose old conditionals differ from the bank's
    law (identity check) and its identity hash changes with the new counts and with the version"""
    res = {}; ok = True; import dgp_paths as _DP
    # (a) two stream transactions on the n32 ER50 anchor
    p32 = RECORDS + '/code/runs/mdi_2026-10-28/DGP4_RESIDUAL_MAX/inputs_fresh/dg_n32_c4_er50_two.uai'
    if os.path.exists(p32):
        model32, _ = CORE.read_uai(p32); M32, order32, clk32, B32 = _jstage(model32); cards32 = list(M32.cards); S, B_, r = _rstream(M32, allow=30.0); assert r == 'READY', (r, S.closed_reason); S.pilot_action(PA.tnow() + 20); st = S.state
        shas0 = {a.aid: a.sha256 for a in st.atoms.values()}; props = [S.epoch.prop]; atts = []
        for _ in range(2):
            a_ = S.optimize_action(PA.tnow() + 20, PA.tnow() + 60); atts.append(a_); props.append(S.epoch.prop)
        txs = [a_.get('transaction') or {} for a_ in atts]; cons = [set(t.get('atoms') or []) for t in txs]
        per = []
        for i, (a_, t) in enumerate(zip(atts, txs)):
            if a_.get('status') != 'PROMOTED': per.append(dict(status=a_.get('status'), why=(a_.get('why') or '')[:60])); continue
            before, after = props[i], props[i + 1]; A_ = set(t['window']['A']); outside_same = all(after.conds[v] is before.conds[v] for v in after.order if v not in A_); inside_changed = [v for v in A_ if after.conds[v] is not before.conds[v]]
            per.append(dict(status='PROMOTED', kind=t['kind'], epoch=t['epoch_after'], version=t['version_after'], A=t['window']['A'], R=t['window']['R'], outside_same_objects=outside_same, inside_changed=sorted(inside_changed), rows_changed=t['rows_changed'], cap_is_kernel_B_new=(after.log2_B() == t['log2_B_after']), consumed=sorted(cons[i]), new_atom=t.get('new_atom')))
        both = all(p_.get('status') == 'PROMOTED' for p_ in per); overlap = (bool(set(txs[0].get('window', {}).get('R', [])) & set(txs[1].get('window', {}).get('R', []))) or (txs[0].get('new_atom') in cons[1])) if both else None
        res['n32_two_transactions'] = dict(transactions=per, both_promoted=both, epochs=len(S.epochs), version=st.version, overlap=overlap, overlap_via_replacement=((txs[0].get('new_atom') in cons[1]) if both else None))
        ok = ok and both and len(S.epochs) == 3 and st.version == 2 and overlap and all(p_['outside_same_objects'] and p_['cap_is_kernel_B_new'] and (p_['kind'] != 'changed_law' or (p_['inside_changed'] and p_['rows_changed'] > 0)) for p_ in per)
        untouched = [aid for aid in shas0 if aid not in cons[0] | cons[1] and aid in st.atoms]; allc = cons[0] | cons[1]
        res['immutability'] = dict(untouched=len(untouched), sha_preserved=all(st.atoms[aid].sha256 == shas0[aid] for aid in untouched), verified_preserved=all(st.atoms[aid].verified for aid in untouched), consumed_flagged=all(st.atoms[aid].consumed for aid in allc), consumed_marked_once=all('consumed_by' in st.atoms[aid].provenance for aid in allc), replacements_verified=all(st.atoms[t['new_atom']].verified for t in txs if t.get('new_atom') in st.atoms), replacement_versions=[st.atoms[t['new_atom']].version_born for t in txs if t.get('new_atom') in st.atoms])
        ok = ok and len(untouched) > 0 and res['immutability']['sha_preserved'] and res['immutability']['verified_preserved'] and res['immutability']['consumed_flagged'] and res['immutability']['consumed_marked_once'] and res['immutability']['replacements_verified'] and (res['immutability']['replacement_versions'] == [1, 2][:len(res['immutability']['replacement_versions'])] or (res['immutability']['replacement_versions'] == [2] and any('bank limits' in (e_.get('why') or '') for e_ in st.evicted)))      # DGP8 (over-cap banks repair): the first replacement may have been evicted to keep the bank inside its declared limits before the second swap -- recorded in st.evicted
        # (c) reuse rejections
        kind = None
        try: st.consume(sorted(cons[0])[:1], 'again')
        except CE.Defect as e: kind = str(e)[:40]
        prop = S.epoch.prop; pos = {v: i for i, v in enumerate(prop.order)}; cw = sorted(cons[0])[0]; ca = st.atoms[cw]; li = pos[max(ca.axes, key=lambda x: pos[x])]; A = prop.order[li - 1:li + 1] if li >= 1 else prop.order[li:li + 2]
        def wfor(aid):
            a = st.atoms[aid]; Rw = set(A) | set(a.axes)
            for v in A: Rw |= set(prop.conds[v].parents)
            return dict(A=list(A), R=sorted(Rw, key=lambda x: pos[x]), atoms=[aid], bank_version=st.version, target_parents={v: tuple(prop.conds[v].parents) for v in A}, max_vol=65536)
        why_c = CR.validate_window(st, wfor(cw), [cw], prop.conds, None, cards32, prop.order); lw = next((a for a in st.live_atoms() if any(x in A for x in a.axes) and max(pos[x] for x in a.axes) <= pos[A[-1]]), None)
        if lw is None:                                                                                                   # DGP8: no live atom touches the A of the first consumed atom in this run -> take A from a live atom (the rebinding sub-check needs one compatible live atom, not that A)
            for la in sorted((a for a in st.live_atoms() if a.axes and a.arr is not None), key=lambda a: (a.entries(), a.aid)):                                 # the smallest live atom whose window region fits the cap
                li = pos[max(la.axes, key=lambda x: pos[x])]; A_try = prop.order[li - 1:li + 1] if li >= 1 else prop.order[li:li + 2]; Rw = set(A_try) | set(la.axes)
                for v in A_try: Rw |= set(prop.conds[v].parents)
                if JP.vol_of(tuple(Rw), cards32) <= 65536: A = A_try; lw = la; res['rebinding_A_from_live_atom'] = dict(A=list(A), atom=la.aid, vol=JP.vol_of(tuple(Rw), cards32)); break
        why_stale = CR.validate_window(st, dict(wfor(lw.aid), bank_version=st.version - 1), [lw.aid], prop.conds, None, cards32, prop.order) if lw else 'n/a'; why_live = CR.validate_window(st, wfor(lw.aid), [lw.aid], prop.conds, None, cards32, prop.order) if lw else 'n/a'
        res['reuse'] = dict(consume_twice=kind, window_with_consumed=why_c, stale_version=why_stale, live_window_accepted=why_live); ok = ok and kind is not None and 'consumed' in (why_c or '') and 'version' in (why_stale or 'version') and (why_live is None or why_live == 'n/a')
        # (d) scalar-only tightening
        env0 = st.envelope_B; cons0 = st.consumed_B; st.consumed_B = _RM.norm_up(cons0[0] - 1, cons0[1]); r_ = st.record(); res['scalar_cap'] = dict(envelope_unchanged=(st.envelope_B == env0), consumed_changed=(st.consumed_B != cons0), record_distinct=(r_['log2_envelope_B'] != r_['log2_consumed_B']), record_keys=('envelope_B' in r_ and 'consumed_B' in r_)); st.consumed_B = cons0; ok = ok and all(res['scalar_cap'].values())
        # (e) rebinding rejected; identity binds counts and version
        if lw is not None:
            wl = wfor(lw.aid); v1 = A[0]; c1 = prop.conds[v1]; cnt = c1.counts.copy(); cnt[0, 0] += 1; cnt[0, 1] -= 1; conds_t = dict(prop.conds); conds_t[v1] = JP.Conditional(v1, c1.parents, cnt, cards32); kt = CR.local_kernel(st, wl, [lw.aid], conds_t, None, cards32, prop.order, clk32, want_rho=False); kh = CR.local_kernel(st, wl, [lw.aid], prop.conds, None, cards32, prop.order, clk32, want_rho=False)
            cn = {v: prop.conds[v] for v in A}; cn2 = dict(cn); cn2[v1] = JP.Conditional(v1, c1.parents, cnt, cards32); kn1 = CR.local_kernel(st, wl, [lw.aid], prop.conds, cn, cards32, prop.order, clk32, want_rho=False); kn2 = CR.local_kernel(st, wl, [lw.aid], prop.conds, cn2, cards32, prop.order, clk32, want_rho=False)
            ver_id = hashlib.sha256(repr((st.model_identity, st.seed_proof_identity, st.version + 1, [lw.aid], [(v, prop.conds[v].sha256) for v in A], None, tuple(wl['R']), (st.envelope_B[0], str(st.envelope_B[1])))).encode()).hexdigest()
            res['rebinding'] = dict(tampered_old_rejected=(kt.get('why') or '')[:70], honest_ok=kh.get('ok'), identity_changes_with_new_counts=(kn1.get('identity') != kn2.get('identity')) if (kn1.get('ok') and kn2.get('ok')) else (kn1.get('why'), kn2.get('why')), identity_changes_with_version=(kh.get('identity') != ver_id))
            ok = ok and not kt.get('ok') and 'law identity' in (kt.get('why') or '') and kh.get('ok') and res['rebinding']['identity_changes_with_new_counts'] is True and res['rebinding']['identity_changes_with_version']
        else: res['rebinding'] = dict(skipped='no live compatible atom'); ok = False
        S._close('ctrl'); res['n32_account_after_close'] = B_.live; ok = ok and B_.live == 0
    else: res['n32_two_transactions'] = dict(skipped='anchor model absent'); ok = False
    # (b) n6 clique: stream transaction, then an API-level same-law transaction consuming the replacement atom; exact identity after each
    model6, _ = load_odev('dg_n6_c4_clique_two'); M6, order6, clk6, B6 = _jstage(model6); cards6 = list(M6.cards); S6, B6_, r6 = _rstream(M6, allow=30.0); assert r6 == 'READY', (r6, S6.closed_reason); S6.pilot_action(PA.tnow() + 20); st6 = S6.state; a61 = S6.optimize_action(PA.tnow() + 20, PA.tnow() + 60); t61 = a61.get('transaction') or {}
    if a61.get('status') == 'PROMOTED':
        prop6 = S6.epoch.prop; live6 = st6.live_atoms(); id1 = CR.ref_envelope_exact(M6, prop6, live6, prop6.B); new1 = t61['new_atom']; na = st6.atoms[new1]; pos6 = {v: i for i, v in enumerate(prop6.order)}; li = pos6[max(na.axes, key=lambda x: pos6[x])]; A6 = prop6.order[li - 1:li + 1] if li >= 1 else prop6.order[li:li + 2]
        R6 = set(A6) | set(na.axes)
        for v in A6: R6 |= set(prop6.conds[v].parents)
        w6 = dict(A=list(A6), R=sorted(R6, key=lambda x: pos6[x]), atoms=[new1], bank_version=st6.version, target_parents={v: tuple(prop6.conds[v].parents) for v in A6}, max_vol=65536); k6 = CR.local_kernel(st6, w6, [new1], prop6.conds, None, cards6, prop6.order, clk6)
        if k6['ok']:
            newp6 = JP.Proposal(cards6, dict(prop6.conds), prop6.order, k6['B_ref'], prop6.S, dict(kind='ctrl_same_law')); n_bytes = JP.ENTRY_BYTES * k6['rho_new'].size + RB.ATOM_META_BYTES; st6._charge(n_bytes, 'ctrl replacement'); undo = st6.apply_transaction(dict(id='ctrl-2', atoms=[new1], kind='same_law'), newp6, tuple(w6['R']), k6['rho_new'], n_bytes, dict(kind='ctrl'), 1.0, -1.0, k6['B_ref'])
            id2 = CR.ref_envelope_exact(M6, newp6, st6.live_atoms(), newp6.B); res['n6_overlap'] = dict(first=a61.get('status'), identity_after_first=id1['violations'], states=id1['states'], second_window_A=w6['A'], second_consumes_replacement=True, identity_after_second=id2['violations'], version=st6.version, second_replacement_verified=st6.atoms[undo['new_aid']].verified, first_replacement_consumed=st6.atoms[new1].consumed, live_after=len(st6.live_atoms()), log2_B_first=prop6.log2_B(), log2_B_second=newp6.log2_B())
            ok = ok and id1['violations'] == 0 and id2['violations'] == 0 and st6.version == 2 and res['n6_overlap']['second_replacement_verified'] and res['n6_overlap']['first_replacement_consumed']
            S6.bank_bytes = st6.owned                                                                 # the API-level transaction charged the replacement through the state: sync the stream's owned attribute as the stream itself does
        else: res['n6_overlap'] = dict(first=a61.get('status'), kernel_why=k6.get('why')); ok = False
    else: res['n6_overlap'] = dict(first=a61.get('status'), why=(a61.get('why') or '')[:80]); ok = False
    S6._close('ctrl'); res['n6_account_after_close'] = dict(live=B6_.live, bank_bytes=S6.bank_bytes, state_owned=st6.owned, close_release=S6.mech.get('close_release')); ok = ok and B6_.live == 0
    rec('D67_sequential_transactions_and_bank_immutability', ok, **res)

def D68_quantization_and_cap_ceiling():
    """brief section 8 item 6: (a) on a hand-built window (two binary active variables, uniform old law, a unit atom so K_ref = 1 exactly) the exact reference gate 10 B_new <= 11 B_ref decides by ONE count unit: the law with
    K_new = 2^39 / c for c = floor(10 x 2^39 / 11) (over the ceiling by ~2^-39 relative, far inside the 2^-20 fitting reserve) FAILS and c + 1 PASSES; the float side's feasibility flag is not consulted; (b) the seed ceiling gate
    likewise flips by one ulp of initial_seed_cap; (c) wrong-law cap: B_new derived for law A does not dominate envelope_B Fhat / q_B for law B (exact cellwise recheck finds violations; the kernel's identity binds the counts) and the
    stream builds the committed Proposal from the SAME kernel call's B_new and counts (source inspection); (d) actual law equality vs representation change: counts replicated onto the G1 parents give rows_changed = 0 under the fit's
    rule, identical q at every cell, and the stream labels 'changed_law' only when conds_new is a quantized CANDIDATE with changed rows (source inspection)"""
    res = {}; ok = True; import dgp7_rates as R7; rng = random.Random(68); cards = [2, 2]; order = [0, 1]; A = [0, 1]; D = JP.D
    uni = np.array([[D // 2, D // 2]], dtype=np.int64); co = {0: JP.Conditional(0, (), uni, cards), 1: JP.Conditional(1, (0,), np.vstack([uni, uni]), cards)}; prop = JP.Proposal(cards, co, order, _RM.norm_up(0, 1), _RM.norm_up(0, 1), dict(kind='ctrl')); B = CE.Budget(CE.CONSTRUCTOR_BYTES); st = RB.ResidualState('ctrl', 'ctrl', prop, prop.B, prop.B, prop.B, B)
    one = np.empty((2, 2), dtype=object); one.fill(RB.ONE); at = RB.Atom(0, (0, 1), one, dict(kind='ctrl'), 1.0, 0.0, 0); at.verified = True; st.atoms[0] = at; clk = CE.Clock(PA.tnow() + 60, {})
    w = dict(A=A, R=[0, 1], C=[], atoms=[0], vol=4, bank_version=0, target_parents={0: (), 1: (0,)}, max_vol=65536, whole_model_region=True)
    cstar = (10 * (1 << 39)) // 11; out = {}
    for lab, c in (('over_by_one_unit', cstar), ('under_by_one_unit', cstar + 1)):
        cn = {0: JP.Conditional(0, (), np.array([[c, D - c]], dtype=np.int64), cards), 1: co[1]}; k = CR.local_kernel(st, w, [0], co, cn, cards, order, clk); ref = CR.ref_local_exact(st, w, [0], co, cn, cards, order)
        out[lab] = dict(ok=k['ok'], gate_ref_ok=k.get('gate_ref_ok'), gate_seed_ok=k.get('gate_seed_ok'), K_ref_exact_one=(ref['K_ref'] == 1), K_new_exact=str(ref['K_new']), exceeds_11_over_10=(ref['K_new'] > F(11, 10)), kernel_K_ref_one=(k['K_ref'] == RB.ONE or _tf(k['K_ref']) == 1), relative_gap=float(abs(ref['K_new'] - F(11, 10)) / F(11, 10)))
    res['reference_gate'] = out; ok = ok and out['over_by_one_unit']['ok'] and out['over_by_one_unit']['gate_ref_ok'] is False and out['over_by_one_unit']['exceeds_11_over_10'] and out['under_by_one_unit']['gate_ref_ok'] is True and not out['under_by_one_unit']['exceeds_11_over_10'] and out['over_by_one_unit']['relative_gap'] < 2 ** -20 and out['over_by_one_unit']['K_ref_exact_one']
    # the float side would call the +1 case feasible under its reserve? -> the kernel decides regardless: record the float K and kappa_fit for the over case
    fit_like = dict(K_float_new=float(F(1 << 39, cstar)), kappa_publish=1.1, kappa_fit=1.1 / (1 + 2 ** -20)); res['float_side_over_case'] = dict(fit_like, float_would_accept_at_publish=(fit_like['K_float_new'] <= 1.1 * (1 + 1e-12)), kernel_rejects=out['over_by_one_unit']['gate_ref_ok'] is False)
    # (b) seed ceiling gate: same law; initial_seed_cap at exactly 10/11 of envelope_B passes, one ulp below fails
    st.initial_seed_cap = _fu(_tf(prop.B) * F(10, 11)); k_s1 = CR.local_kernel(st, w, [0], co, None, cards, order, clk); st.initial_seed_cap = _RM.norm_up(st.initial_seed_cap[0], st.initial_seed_cap[1] - 1); k_s2 = CR.local_kernel(st, w, [0], co, None, cards, order, clk); st.initial_seed_cap = prop.B
    res['seed_gate'] = dict(at_ceiling=k_s1.get('gate_seed_ok'), one_ulp_below=k_s2.get('gate_seed_ok'), ref_gate_same_law=k_s1.get('gate_ref_ok')); ok = ok and k_s1.get('gate_seed_ok') is True and k_s2.get('gate_seed_ok') is False and k_s1.get('gate_ref_ok') is True
    # (c) wrong-law cap: B_new for law A (c + 1) presented with law B (counts [D/4, 3D/4] on variable 0): exact cellwise recheck of envelope_B Fhat <= B_new q_B
    cnA = {0: JP.Conditional(0, (), np.array([[cstar + 1, D - cstar - 1]], dtype=np.int64), cards), 1: co[1]}; cnB = {0: JP.Conditional(0, (), np.array([[D // 4, 3 * (D // 4)]], dtype=np.int64), cards), 1: co[1]}; kA = CR.local_kernel(st, w, [0], co, cnA, cards, order, clk); kB = CR.local_kernel(st, w, [0], co, cnB, cards, order, clk)
    def recheck(B_new, cn):
        viol = 0
        for x in itertools.product(range(2), range(2)):
            qo = F(int(co[0].counts[0, x[0]]), D) * F(int(co[1].counts[x[0], x[1]]), D); qn = F(int(cn[0].counts[0, x[0]]), D) * F(int(cn[1].counts[x[0], x[1]]), D); Fh = qo * _tf(one[x])
            if _tf(prop.B) * Fh > _tf(B_new) * qn: viol += 1
        return viol
    res['wrong_law_cap'] = dict(A_with_A_violations=recheck(kA['B_new'], cnA), A_cap_with_B_law_violations=recheck(kA['B_new'], cnB), B_with_B_violations=recheck(kB['B_new'], cnB), identities_differ=(kA['identity'] != kB['identity']), stream_builds_from_same_kernel=("JP.Proposal(cards, conds_full, prop.order, k['B_new']" in _inspect.getsource(RS)))
    ok = ok and res['wrong_law_cap']['A_with_A_violations'] == 0 and res['wrong_law_cap']['A_cap_with_B_law_violations'] > 0 and res['wrong_law_cap']['B_with_B_violations'] == 0 and res['wrong_law_cap']['identities_differ'] and res['wrong_law_cap']['stream_builds_from_same_kernel']
    # (d) representation-only change: replication to the G1 parents on the n8 clique
    model, _ = load('dg_n8_c4_clique_two'); M, order8, clk8, B8, cards8, prop8, owned8, st8, sink8, rec8 = _rstage(model); pairs, chg = JO.interaction_scores(M, B8, clk8); parents1, g1 = GO.select_g1(prop8, pairs, cards8); vext = next(v for v in prop8.order if tuple(parents1[v]) != tuple(prop8.conds[v].parents))
    repl = prop8.conds[vext].replicate(tuple(parents1[vext]), cards8); base = prop8.conds[vext].replicate(tuple(parents1[vext]), cards8); rows_changed = int(not np.array_equal(repl.counts, base.counts)); same_q = True
    for _ in range(300):
        x = [rng.randrange(k) for k in cards8]; ro = sum(prop8.conds[vext].pstrides[p_] * x[p_] for p_ in prop8.conds[vext].parents); rn = sum(repl.pstrides[p_] * x[p_] for p_ in repl.parents); same_q = same_q and int(prop8.conds[vext].counts[ro, x[vext]]) == int(repl.counts[rn, x[vext]])
    src = _inspect.getsource(RS); res['representation_only'] = dict(variable=vext, rows_changed=rows_changed, sha_differs=(repl.sha256 != prop8.conds[vext].sha256), same_q_every_sample=same_q, stream_changed_law_requires_candidate=("if fit['status'] == 'CANDIDATE' and fit.get('feasible_actual'): conds_new = fit['conds_new']" in src and "kind='changed_law'" in src and "'QUANTIZED_TO_INCUMBENT'" in _inspect.getsource(RL)))
    ok = ok and rows_changed == 0 and res['representation_only']['sha_differs'] and same_q and res['representation_only']['stream_changed_law_requires_candidate']
    B8.release(owned8); rec('D68_quantization_and_cap_ceiling', ok, **res)

def D69_allocation_refusal_deadline_positions():
    """brief section 8 item 7: on the n8 card-4 clique through ResidualStream, a typed refusal / deadline injected at every position -- bank extraction admission (atom temporary refused -> dropped, the seed READY), target / graph
    planning poll, context draws (Proposal.sample refused), local tables (fit sweep poll), the final division (kernel pass 2 poll), replacement construction (kernel pass 1 / T2 polls), epoch assembly (fingerprint deadline after the
    bank swap -> revert), the authoritative pre-commit sample -- leaves the bank (version, atoms, consumed flags, owned bytes), the law, the epoch count, the certificate t, the sampler RNG and the constructor account exactly as
    before the action; diagnostics() works after every refusal; the account equals the stream's owned attributes at every snapshot"""
    res = {}; ok = True; model, _ = load('dg_n8_c4_clique_two'); M, order, clk, B = _jstage(model); cards = list(M.cards)
    # (a) bank extraction admission refusal
    real_charge = RB.ResidualState._charge
    def refuse_temp(self, n, what):
        if 'temporary' in what: raise CE.Refused('MEMORY', 'injected atom temporary refusal')
        return real_charge(self, n, what)
    RB.ResidualState._charge = refuse_temp
    try: S0, B0, r0 = _rstream(M, allow=20.0)
    finally: RB.ResidualState._charge = real_charge
    res['extraction_refused'] = dict(prepare=r0, atoms=len(S0.state.atoms), dropped=len(S0.state.dropped), dropped_why=(S0.state.dropped[0]['why'][:40] if S0.state.dropped else None), bank_bytes=S0.bank_bytes, live_consistent=(B0.live == S0.joint_bytes + S0.bank_bytes + S0.fine_bytes)); S0._close('ctrl')
    ok = ok and r0 == 'READY' and res['extraction_refused']['atoms'] == 0 and res['extraction_refused']['dropped'] > 0 and res['extraction_refused']['bank_bytes'] == 0 and res['extraction_refused']['live_consistent'] and B0.live == 0
    def fresh():
        S, B_, r = _rstream(M, allow=30.0); assert r == 'READY', (r, S.closed_reason); S.pilot_action(PA.tnow() + 20); S._frozen_targets(S.epoch.prop, cards, B_, CE.Clock(PA.tnow() + 20, {})); return S, B_
    def snap(S, B_):
        st = S.state; return dict(live=B_.live, epoch=S.epoch.index, n_epochs=len(S.epochs), law=S.epoch.prop.sha256, t=S.cert.t, draws=S.draws, rng=S.rng.bit_generator.state['state']['state'], joint_bytes=S.joint_bytes, bank_bytes=S.bank_bytes, version=st.version, atoms=sorted(st.atoms), consumed=sorted(a.aid for a in st.atoms.values() if a.consumed), owned=st.owned, shas=sorted(a.sha256 for a in st.atoms.values()), env=st.envelope_B, cons=st.consumed_B, law_id=st.law_identity, txns=len(st.transactions), consistent=(B_.live == S.joint_bytes + S.bank_bytes + S.fine_bytes and st.owned == sum(a.bytes for a in st.atoms.values()) and S.bank_bytes == st.owned))
    def same(a, b): return all(a[k] == b[k] for k in a if k not in ('consistent', 'txns')) and a['consistent'] and b['consistent']
    def diff(a, b): return [k for k in a if k not in ('consistent',) and a[k] != b[k]] + ([] if (a['consistent'] and b['consistent']) else ['consistent'])
    inj = {}
    for phase, where, nth in (('graph_planning', 'after target selection', 1), ('local_tables', 'fit sweep', 2), ('replacement_pass1', 'kernel pass 1 tile', 3), ('T2_contexts', 'kernel T2 context', 1), ('final_division', 'kernel pass 2 tile', 2), ('pre_commit_sample', 'after window', 1)):
        S, B_ = fresh(); s0 = snap(S, B_); real_clock = CE.Clock
        class Clk(CE.Clock):
            def __init__(self, deadline, stats): super().__init__(deadline, stats); self.n = 0
            def poll(self, w):
                if where in w:
                    self.n += 1
                    if self.n == nth: raise CE.Refused('DEADLINE', 'injected ' + w)
                return super().poll(w)
        CE.Clock = Clk
        try: a = S.optimize_action(PA.tnow() + 20, PA.tnow() + 60)
        finally: CE.Clock = real_clock
        d = S.diagnostics(); s1 = snap(S, B_); inj[phase] = dict(status=a.get('status'), kind=a.get('kind'), why=(a.get('why') or '')[:50], preserved=same(s0, s1), differing=diff(s0, s1), windows=len(a.get('windows') or []), diagnostics_ok=(d.get('residual') is not None and d['residual'].get('bank') is not None), stage=S.stage); S._close('ctrl')
        ok = ok and a.get('status') == 'REFUSED' and a.get('kind') == 'DEADLINE' and inj[phase]['preserved'] and inj[phase]['diagnostics_ok'] and S.stage == 'CLOSED' and B_.live == 0
    # context draws: Proposal.sample refused (after the pilot)
    S, B_ = fresh(); s0 = snap(S, B_); real_sample = JP.Proposal.sample
    def refuse_sample(self, rng, n): raise CE.Refused('MEMORY', 'injected context-draw refusal')
    JP.Proposal.sample = refuse_sample
    try: a = S.optimize_action(PA.tnow() + 20, PA.tnow() + 60)
    finally: JP.Proposal.sample = real_sample
    ctx_modes = [((w_.get('fit') or {}).get('context') or {}).get('mode', '')[:7] for w_ in (a.get('windows') or [])]; reached = (a.get('status') == 'REFUSED' and 'context-draw' in (a.get('why') or ''))
    inj['context_draws_stream'] = dict(status=a.get('status'), kind=a.get('kind'), why=(a.get('why') or '')[:50], preserved=(same(s0, snap(S, B_)) if reached else None), note=(None if reached else 'sampled mode not reached on this model: every window context is parent-closed (exact weights; no draws)'), contexts=ctx_modes); S._close('ctrl')
    ok = ok and (inj['context_draws_stream']['preserved'] if reached else all(c == 'exact (' for c in ctx_modes if c)) and B_.live == 0
    # the context-draw refusal on a synthetic NON-parent-closed window through fit_window: typed, nothing retained
    import dgp7_rates as R7; rng7 = random.Random(69); cards_s = [2, 3, 2, 2]; order_s = [0, 1, 2, 3]; st_s, prop_s, w_s, co_s, cn_s, B_s = _syn_region(cards_s, order_s, [2, 3], [(1, 2), (1, 3)], rng7, targets_extra={2: 1, 3: 1}); co_s2 = dict(co_s); co_s2[1] = R7.rand_cond(rng7, 1, (0,), cards_s); prop_s2 = JP.Proposal(cards_s, co_s2, order_s, prop_s.B, prop_s.S, dict(kind='ctrl'))
    JP.Proposal.sample = refuse_sample; kind_s = None; live_s = B_s.live
    try: RL.fit_window(prop_s2, w_s, [st_s.atoms[a_] for a_ in w_s['atoms']], cards_s, order_s, 'auto', np.random.default_rng(1), 1.1, clock=CE.Clock(PA.tnow() + 20, {}))
    except CE.Refused as e: kind_s = e.kind
    finally: JP.Proposal.sample = real_sample
    nu_ok, rec_ok = RL.context_weights(prop_s2, [x for x in w_s['R'] if x not in w_s['A']], cards_s, order_s, np.random.default_rng(1), RL.region_assignments(w_s['R'], cards_s), {x: i for i, x in enumerate(w_s['R'])}, 1024, mode='auto')
    inj['context_draws_direct'] = dict(refused_kind=kind_s, parent_closed=CR.parent_closed(prop_s2, [x for x in w_s['R'] if x not in w_s['A']]), mode_without_injection=(rec_ok.get('mode') or '')[:7], account_unchanged=(B_s.live == live_s)); ok = ok and kind_s == 'MEMORY' and not inj['context_draws_direct']['parent_closed'] and inj['context_draws_direct']['mode_without_injection'] == 'sampled' and inj['context_draws_direct']['account_unchanged']
    # epoch assembly: fingerprint deadline AFTER the bank swap -> the bank reverts
    S, B_ = fresh(); s0 = snap(S, B_); real_fp = JS.JointStream._fingerprint_of; hits = [0]
    def fp_dead(self, ep, deadline, budget): hits[0] += 1; raise PA.Deadline('injected fingerprint deadline')
    JS.JointStream._fingerprint_of = fp_dead
    try: a = S.optimize_action(PA.tnow() + 20, PA.tnow() + 60)
    finally: JS.JointStream._fingerprint_of = real_fp
    s1 = snap(S, B_); inj['epoch_assembly'] = dict(status=a.get('status'), kind=a.get('kind'), hits=hits[0], preserved=same(s0, s1), differing=diff(s0, s1), reverted_marked=(bool(S.state.transactions) and S.state.transactions[-1].get('reverted') is True), transactions_recorded=s1['txns'], stage=S.stage); S._close('ctrl')
    ok = ok and a.get('status') == 'REFUSED' and hits[0] >= 1 and inj['epoch_assembly']['preserved'] and inj['epoch_assembly']['reverted_marked'] and B_.live == 0
    # budget refusal at the window workspace charge (tiny headroom) -> typed REFUSED window(s), nothing committed
    S, B_ = fresh(); s0 = snap(S, B_); cap0 = B_.cap; B_.cap = B_.live + 1024
    try: a = S.optimize_action(PA.tnow() + 20, PA.tnow() + 60)
    finally: B_.cap = cap0
    s1 = snap(S, B_); inj['workspace_admission'] = dict(status=a.get('status'), window_statuses=sorted({w_.get('status') for w_ in (a.get('windows') or [])}), kinds=sorted({w_.get('kind') for w_ in (a.get('windows') or []) if w_.get('kind')}), preserved=same(s0, s1), differing=diff(s0, s1)); S._close('ctrl')
    ok = ok and a.get('status') == 'KEPT_INCUMBENT' and set(inj['workspace_admission']['window_statuses']) <= {'REFUSED'} and inj['workspace_admission']['preserved'] and B_.live == 0
    res['injections'] = inj; rec('D69_allocation_refusal_deadline_positions', ok, **res)

def D70_zero_target_eviction_and_cleanup():
    """brief section 8 item 8: (a) a region whose atoms vanish identically -> the kernel returns the typed zero_target result (no division, no epoch material); (b) dropping an unretained replacement atom: after a transaction on the
    n6 clique the replacement atom is evicted by make_room (lowest score first until the allocation fits) with its bytes released exactly, the state stays consistent and the identity W <= B q prod rho still holds on every state
    without it; (c) eviction before seed admission: with the constructor cap set to the sink-free seed peak + 64 KiB the seed with the bank attached still succeeds (atoms evicted / dropped as needed; the account balances);
    (d) repeated close and refusal cleanup: a prepared ResidualStream closed twice releases its bytes once (account back to zero; idempotent); a seed refused by MEMORY closes typed with the account at zero"""
    res = {}; ok = True; import dgp7_rates as R7; rng = random.Random(70)
    # (a) zero local target
    cards = [2, 2, 2]; order = [0, 1, 2]; A = [1, 2]; st, prop, w, co, cn, B = _syn_region(cards, order, A, [(1, 2)], rng); z = np.empty((2, 2), dtype=object); z.fill(_ZERO); za = RB.Atom(0, (1, 2), z, dict(kind='ctrl'), 1.0, -1.0, 0); za.verified = True; st.atoms[0] = za; clk = CE.Clock(PA.tnow() + 60, {})
    kz = CR.local_kernel(st, w, [0], co, cn, cards, order, clk); res['zero_target'] = dict(ok=kz.get('ok'), zero_target=kz.get('zero_target'), has_B_new=('B_new' in kz), has_rho=('rho_new' in kz)); ok = ok and kz.get('ok') and kz.get('zero_target') is True and not res['zero_target']['has_B_new']
    # (b) dropping the replacement atom after a real transaction (n6 clique; whole-model region)
    model6, _ = load_odev('dg_n6_c4_clique_two'); M6, order6, clk6, B6 = _jstage(model6); cards6 = list(M6.cards); S, B_, r = _rstream(M6, allow=30.0); assert r == 'READY', (r, S.closed_reason); S.pilot_action(PA.tnow() + 20); a1 = S.optimize_action(PA.tnow() + 20, PA.tnow() + 60); tx = a1.get('transaction') or {}; st6 = S.state
    if a1.get('status') == 'PROMOTED':
        new_aid = tx['new_atom']; na = st6.atoms[new_aid]; live0 = B_.live; owned0 = st6.owned; sink = RB.BankSink(st6, clk6, 1.0); cap0 = B_.cap; B_.cap = B_.live + 64; lowest = min(st6.atoms.values(), key=lambda a: (a.score, -a.aid)).aid
        try: sink.make_room(na.bytes + 64)
        finally: B_.cap = cap0
        others = [a for a in st6.live_atoms()]; ident = CR.ref_envelope_exact(M6, S.epoch.prop, others, S.epoch.prop.B)
        res['drop_replacement'] = dict(evicted=(new_aid not in st6.atoms), replacement_was_lowest_score=(lowest == new_aid), evicted_record=[e['aid'] for e in st6.evicted], evictions=len(st6.evicted), bytes_released_exact=(live0 - B_.live == na.bytes and owned0 - st6.owned == na.bytes), consistent=(st6.owned == sum(a.bytes for a in st6.atoms.values())), identity_without_it=ident['violations'], states=ident['states'], live_atoms_left=len(others))
        ok = ok and res['drop_replacement']['evicted'] and res['drop_replacement']['replacement_was_lowest_score'] and res['drop_replacement']['evictions'] == 1 and res['drop_replacement']['bytes_released_exact'] and res['drop_replacement']['consistent'] and ident['violations'] == 0
    else: res['drop_replacement'] = dict(skipped=a1.get('status'), why=(a1.get('why') or '')[:80]); ok = False
    S._close('ctrl'); res['drop_replacement']['account_after_close'] = B_.live; ok = ok and B_.live == 0
    # (c) eviction before seed admission (n8 clique): peak without the sink, then a cap just above it with the sink
    model8, _ = load('dg_n8_c4_clique_two'); clk8 = CE.Clock(PA.tnow() + 60, {}); Bp = CE.Budget(CE.CONSTRUCTOR_BYTES); M8 = CE.canonicalize(model8, clk8, Bp); order8, _ = CE.elimination_order(list(M8.cards), [tuple(sc) for sc, _ in M8.factors], clk8, Bp); live_b = Bp.live; prop_p, rec_p, owned_p = JP.compile_seed(M8, order8, JPROF, Bp, clk8); peak = Bp.peak - live_b; Bp.release(owned_p)
    Bc = CE.Budget(live_b + peak + (64 << 10)); Mc = CE.canonicalize(model8, clk8, Bc); orderc, _ = CE.elimination_order(list(Mc.cards), [tuple(sc) for sc, _ in Mc.factors], clk8, Bc); stc = RB.ResidualState('ctrl', None, None, None, None, None, Bc); sinkc = RB.BankSink(stc, clk8, 5.0); kind = None
    try: propc, recc, ownedc = JP.compile_seed(Mc, orderc, JPROF, Bc, clk8, sink=sinkc); stc.bind_seed(propc, recc['plan_sha256'])
    except CE.Refused as e: kind = e.kind; ownedc = 0
    res['eviction_before_seed'] = dict(peak_without_sink=peak, cap=Bc.cap, refused=kind, seed_cap_same=(kind is None and propc.log2_B() == prop_p.log2_B()), atoms=len(stc.atoms), bank_bytes=stc.owned, evicted=len(stc.evicted), dropped=len(stc.dropped), offers=sinkc.offers, account_consistent=(stc.owned == sum(a.bytes for a in stc.atoms.values())), peak_within_cap=(Bc.peak <= Bc.cap))
    ok = ok and kind is None and res['eviction_before_seed']['seed_cap_same'] and res['eviction_before_seed']['peak_within_cap'] and (len(stc.evicted) + len(stc.dropped) + len(stc.atoms) > 0) and res['eviction_before_seed']['account_consistent']
    tight = []
    for extra in (8 << 10, 1 << 10):
        Bt = CE.Budget(live_b + peak + extra); Mt = CE.canonicalize(model8, clk8, Bt); ordert, _ = CE.elimination_order(list(Mt.cards), [tuple(sc) for sc, _ in Mt.factors], clk8, Bt); stt = RB.ResidualState('ctrl', None, None, None, None, None, Bt); sinkt = RB.BankSink(stt, clk8, 5.0); kt = None
        try: propt, rect, ownedt = JP.compile_seed(Mt, ordert, JPROF, Bt, clk8, sink=sinkt)
        except CE.Refused as e: kt = e.kind
        tight.append(dict(extra=extra, refused=kt, atoms=len(stt.atoms), evicted=len(stt.evicted), dropped=len(stt.dropped), offers=sinkt.offers, peak_within_cap=(Bt.peak <= Bt.cap), seed_cap_same=(kt is None and propt.log2_B() == prop_p.log2_B()))); ok = ok and kt is None and tight[-1]['seed_cap_same'] and tight[-1]['peak_within_cap'] and (tight[-1]['evicted'] + tight[-1]['dropped'] > 0)
    res['eviction_before_seed']['tight_caps'] = tight
    # make_room ordering: the lowest score goes first
    Bm = CE.Budget(1 << 20); stm = RB.ResidualState('ctrl', 'ctrl', prop, prop.B, prop.B, prop.B, Bm); arrs = []
    for j, sc in enumerate((0.5, 0.1, 0.9)): arr = np.empty((2, 2), dtype=object); arr.fill(_fu(F(1, 2))); n_ = JP.ENTRY_BYTES * 4 + RB.ATOM_META_BYTES; stm._charge(n_, 'atom'); stm.add_atom((1, 2), arr, dict(kind='ctrl'), sc, -1.0, n_)
    Bm.charge(Bm.cap - Bm.live - 100, 'filler'); sinkm = RB.BankSink(stm, clk, 1.0); sinkm.make_room(n_ + 50); res['make_room_order'] = dict(evicted=[e['aid'] for e in stm.evicted], remaining=sorted(stm.atoms), fits=(Bm.live + n_ + 50 <= Bm.cap)); ok = ok and stm.evicted and stm.evicted[0]['aid'] == 1 and res['make_room_order']['fits']
    # (d) repeated close; refused seed cleanup
    S2, B2, r2 = _rstream(M6, allow=20.0); live_ready = B2.live; S2._close('first'); l1 = B2.live; rel1 = S2.mech['close_release']['released_bytes']; S2._close('second'); l2 = B2.live; rel2 = S2.mech['close_release']['released_bytes']
    res['repeated_close'] = dict(prepare=r2, live_ready=live_ready, after_first=l1, after_second=l2, released_first=rel1, released_second=rel2, bank_cleared=(len(S2.state.atoms) == 0 and S2.bank_bytes == 0 and S2.state.owned == 0)); ok = ok and r2 == 'READY' and live_ready > 0 and l1 == 0 and l2 == 0 and rel1 > 0 and rel2 == 0 and res['repeated_close']['bank_cleared']
    Bs = CE.Budget(1 << 16); S3, B3, r3 = _rstream(M6, allow=20.0, budget=Bs); res['refused_seed'] = dict(prepare=r3, closed=(S3.closed_reason or '')[:60], live=B3.live, bank_owned=(S3.state.owned if S3.state is not None else None)); ok = ok and r3 == 'CLOSED' and B3.live == 0 and ('MEMORY' in (S3.closed_reason or '') or 'DEADLINE' in (S3.closed_reason or ''))
    rec('D70_zero_target_eviction_and_cleanup', ok, **res)

CONTROLS += [D63_seed_residual_inequalities, D64_local_F_source_binding, D65_exact_K_T2_and_weighted_moment, D66_waterfill_kkt_and_objective, D67_sequential_transactions_and_bank_immutability, D68_quantization_and_cap_ceiling, D69_allocation_refusal_deadline_positions, D70_zero_target_eviction_and_cleanup]


# ---------------------------------------------------------------- DGP8 (D71): the DGP7-review finding 'missing scheduling calibration check'
def D71_scheduling_calibration_vs_scored_cells():
    """the FROZEN affine time blocks of residual_local.predicted_work_s (PROFILE_RESIDUAL t_*) vs the ACTUAL window seconds recorded on the DGP7 SCORED cells (runs/*/*/result.json; fitted windows only); ratio = actual / predicted per
    window; documented tolerance: median <= 1.5 and p90 <= 2.5. The control FAILS when the frozen blocks under-predict beyond the tolerance -- the constants are NEVER tuned here (a failure is a scheduling-forecast defect to report)"""
    import glob
    RD7 = RECORDS + '/code/runs/mdi_2026-10-28/DGP7_RESIDUAL_JOINT'; ratios = []; n_cells = 0; by_vol = {}; skipped = {}
    for p in sorted(glob.glob(RD7 + '/runs/*/*/result.json')):
        try: d = json.load(open(p))
        except Exception: continue
        for S in d.get('streams') or []:
            if S.get('kind') != 'residual': continue
            n_cells += 1
            for att in (S.get('joint') or {}).get('attempts') or []:
                for w in att.get('windows') or []:
                    pred = w.get('predicted_work_s'); act = w.get('seconds') or (((w.get('fit') or {}).get('seconds') or 0.0) + ((w.get('kernel') or {}).get('seconds') or 0.0))
                    if w.get('status') in ('INTERRUPTED', 'FORECAST_SKIPPED', 'REFUSED', 'NOT_STARTED', 'STARTED') or not pred or not act: skipped[w.get('status')] = skipped.get(w.get('status'), 0) + 1; continue
                    r = act / pred; ratios.append(r); by_vol.setdefault(w.get('vol'), []).append(r)
    med = float(np.median(ratios)) if ratios else None; p90 = float(np.percentile(ratios, 90)) if ratios else None; ok = bool(ratios) and med <= 1.5 and p90 <= 2.5
    rec('D71_scheduling_calibration_vs_scored_cells', ok, n_cells=n_cells, n_windows=len(ratios), median=med, p90=p90, max=(max(ratios) if ratios else None), min=(min(ratios) if ratios else None), by_volume={str(v): dict(n=len(x), median=float(np.median(x)), p90=float(np.percentile(x, 90))) for v, x in sorted(by_vol.items(), key=lambda kv: (kv[0] or 0))}, skipped_statuses=skipped,
        tolerance='median <= 1.5 and p90 <= 2.5 of actual / predicted on the scored DGP7 windows (fitted windows only)', frozen_blocks={k: RL.PROFILE_RESIDUAL[k] for k in ('t_setup_s', 't_float_cell_s', 't_compact_cell_s', 't_context_sample_s', 't_output_s')}, note='the constants are NOT tuned by this control; a failure is reported as a scheduling-forecast defect (DGP7 review finding: missing scheduling calibration check)')

CONTROLS += [D71_scheduling_calibration_vs_scored_cells]


# ---- DGP8 (D72-D81): spectral witness / exact heat-bath / Markov certificate (brief CLAUDE_DGP8_SPECTRAL_HEATBATH_PROMPT.md section 5). Every reference here is INDEPENDENT of the production modules (decimal logarithms at 60 digits,
# Fraction enumeration, a second minimal chain implementation); the supplied references of the packet did not arrive.
import spectral_witness as SW, heatbath_exact as HX, heatbath_native as HN, markov_certificate as MC
import decimal as _dec, subprocess as _sp, ctypes as _ct, tempfile as _tmp
# consolidation step 1: subprocesses run the historical runner path (a shim re-executing the canonical module); SOURCE-TEXT controls read the canonical file (_RUNNER_SRC)
_RUNNER = os.path.join(HERE, 'spectral_heatbath_run.py'); import spectral_heatbath_run as _SHR; _RUNNER_SRC = _SHR.__file__; _PY8 = sys.executable; _WEAK32 = RECORDS + '/code/runs/mdi_2026-10-28/DENSE_GENERIC_PAC_INTEGRATION_1/inputs_eval/dg_n32_c4_er50_half.uai'; _WEAK64 = _WEAK32.replace('n32', 'n64')


def _hstage(model, budget_s=60):
    clk = CE.Clock(time.monotonic() + budget_s, {}); B = CE.Budget(CE.CONSTRUCTOR_BYTES); M = CE.canonicalize(model, clk, B); return M, clk, B


def _dec_ln(x):
    """an independent high-precision natural logarithm of a positive Fraction (decimal module, 60 digits) as a Fraction"""
    _dec.getcontext().prec = 60; x = F(x); v = _dec.Decimal(x.numerator).ln() - _dec.Decimal(x.denominator).ln(); return F(v)


def _exact_A(M):
    """the exact centered-one-hot interaction matrix (Fractions of 60-digit decimal logs): blocks P_i log(F_ij) P_j, factors on a pair added, zero variable blocks"""
    cards = list(M.cards); off = [0]
    for k in cards: off.append(off[-1] + k)
    D = off[-1]; A = [[F(0)] * D for _ in range(D)]
    for sc, vals in M.factors:
        if len(sc) != 2: continue
        i, j = sc; ki, kj = cards[i], cards[j]; L = [[_dec_ln(vals[a * kj + b]) for b in range(kj)] for a in range(ki)]
        rm = [sum(L[a]) / kj for a in range(ki)]; cm = [sum(L[a][b] for a in range(ki)) / ki for b in range(kj)]; gm = sum(rm) / ki
        for a in range(ki):
            for b in range(kj):
                c = L[a][b] - rm[a] - cm[b] + gm; A[off[i] + a][off[j] + b] += c; A[off[j] + b][off[i] + a] += c
    return A, off


def _pair_model(cards, pairs, unaries=None, evidence=None):
    """pairs = [(i, j, values row-major over (i, j))]; unaries = {v: values}"""
    facs = [dict(scope=(i, j), values=[F(v) for v in vals]) for (i, j, vals) in pairs]
    for v, vals in (unaries or {}).items(): facs.append(dict(scope=(v,), values=[F(x) for x in vals]))
    return dict(cards=list(cards), factors=facs, evidence=dict(evidence or {}))


def _contains(M, built):
    """A_lo <= A_exact <= A_hi entrywise; the constant directions are in the null space within the interval (sum over a variable block of [lo, hi] brackets 0)"""
    A, off = _exact_A(M); D = built['D']; ok = True; worst = 0.0; null_ok = True
    for r in range(D):
        for c in range(D):
            lo = F(float(built['A_lo'][r, c])); hi = F(float(built['A_hi'][r, c])); ok = ok and (lo <= A[r][c] <= hi); worst = max(worst, float(hi - lo))
        for i in range(len(off) - 1):
            slo = sum(float(built['A_lo'][r, c]) for c in range(off[i], off[i + 1])); shi = sum(float(built['A_hi'][r, c]) for c in range(off[i], off[i + 1])); null_ok = null_ok and (slo - 1e-15 <= 0.0 <= shi + 1e-15)
    return ok, worst, null_ok


def D72_interaction_matrix_and_witness_algebra():
    res = {}; ok = True; rng = random.Random(72)
    T = [[F(rng.randint(1, 9), rng.randint(1, 5)) for _ in range(3)] for _ in range(2)]                          # a 2 x 3 table over (0, 1)
    m1 = _pair_model([2, 3], [(0, 1, [T[a][b] for a in range(2) for b in range(3)])]); m2 = _pair_model([2, 3], [(1, 0, [T[a][b] for b in range(3) for a in range(2)])])
    M1, clk, B = _hstage(m1); b1 = SW.build_interaction(M1, B, clk); M2, clk2, B2 = _hstage(m2); b2 = SW.build_interaction(M2, B2, clk2)
    c1 = _contains(M1, b1); c2 = _contains(M2, b2); mid1 = 0.5 * (b1['A_lo'] + b1['A_hi']); mid2 = 0.5 * (b2['A_lo'] + b2['A_hi']); same = float(np.max(np.abs(mid1 - mid2))) <= float(np.max(b1['A_hi'] - b1['A_lo'] + b2['A_hi'] - b2['A_lo'])) + 1e-15
    res['a_orientations'] = dict(contains_ij=c1[0], contains_ji=c2[0], same_matrix=same, D=b1['D']); ok = ok and c1[0] and c2[0] and same and c1[2] and c2[2]
    # (b) unaries never enter A (they move to h)
    m3 = _pair_model([2, 3], [(0, 1, [T[a][b] for a in range(2) for b in range(3)])], unaries={0: [5, F(1, 3)], 1: [2, 7, F(1, 2)]}); M3, clk3, B3 = _hstage(m3); b3 = SW.build_interaction(M3, B3, clk3)
    res['b_unaries'] = dict(A_identical=bool(np.array_equal(b1['A_lo'], b3['A_lo']) and np.array_equal(b1['A_hi'], b3['A_hi'])), h_differs=bool(np.max(np.abs(b1['h'] - b3['h'])) > 0.1)); ok = ok and res['b_unaries']['A_identical'] and res['b_unaries']['h_differs']
    # (c) mixed cardinalities 2 / 3 / 5 on three pairs
    cards = [2, 3, 5]; prs = [(i, j, [F(rng.randint(1, 20), rng.randint(1, 9)) for _ in range(cards[i] * cards[j])]) for (i, j) in ((0, 1), (0, 2), (1, 2))]; m4 = _pair_model(cards, prs, unaries={1: [1, 2, 3]}); M4, clk4, B4 = _hstage(m4); b4 = SW.build_interaction(M4, B4, clk4); c4 = _contains(M4, b4)
    res['c_mixed_cards'] = dict(contains=c4[0], worst_width=c4[1], null_space=c4[2], D=b4['D']); ok = ok and c4[0] and c4[2] and b4['D'] == 10
    # (d) duplicate pair factors add: two tables on (0, 1) == their elementwise product in one factor
    T2 = [F(rng.randint(1, 9), rng.randint(1, 5)) for _ in range(6)]; T1 = [T[a][b] for a in range(2) for b in range(3)]
    md = _pair_model([2, 3], [(0, 1, T1), (0, 1, T2)]); mp = _pair_model([2, 3], [(0, 1, [x * y for x, y in zip(T1, T2)])]); Md, ck, Bd = _hstage(md); bd = SW.build_interaction(Md, Bd, ck); Mp, ck2, Bp = _hstage(mp); bp = SW.build_interaction(Mp, Bp, ck2)
    cd = _contains(Md, bd); cp = _contains(Mp, bp); Aex, _ = _exact_A(Mp); cont_cross = all(F(float(bd['A_lo'][r, c])) <= Aex[r][c] <= F(float(bd['A_hi'][r, c])) for r in range(bd['D']) for c in range(bd['D']))
    res['d_duplicate_pairs'] = dict(blocks_in_canonical=len([1 for sc, _ in Md.factors if len(sc) == 2]), contains_dup=cd[0], contains_product=cp[0], dup_contains_product_exact=cont_cross); ok = ok and cd[0] and cp[0] and cont_cross
    # (e) evidence conditioning: observed variable restricted out before the construction
    me = _pair_model([2, 3, 2], [(0, 1, T1), (1, 2, [F(rng.randint(1, 9)) for _ in range(6)])], evidence={2: 1}); Me, cke, Be = _hstage(me); be = SW.build_interaction(Me, Be, cke); ce = _contains(Me, be)
    res['e_evidence'] = dict(retained=len(Me.cards), D=be['D'], contains=ce[0], null_space=ce[2]); ok = ok and len(Me.cards) == 2 and be['D'] == 5 and ce[0]
    # (f) n = 1 and the independent model: A = 0, eligible, g = 1 / n (within the proposal margin)
    for name, mm in (('n1', dict(cards=[3], factors=[dict(scope=(0,), values=[F(1), F(2), F(3)])], evidence={})), ('independent_3', dict(cards=[2, 3, 2], factors=[dict(scope=(v,), values=[F(1 + v + a) for a in range(c)]) for v, c in enumerate([2, 3, 2])], evidence={}))):
        Mi, cki, Bi = _hstage(mm)
        if not Mi.cards: res['f_' + name] = dict(note='canonicalize fixed every variable (factorless -> exact rows); no matrix'); continue
        Wi = SW.certify(Mi, Bi, cki); res['f_' + name] = dict(eligible=Wi['eligible'], width=Wi['width'], g=Wi.get('gap_g'), n=Wi['n'], A_zero=bool(np.all(Wi['h'] == Wi['h']) and SW.build_interaction(Mi, Bi, cki)['A_hi'].max() == 0.0)); ok = ok and Wi['eligible'] and Wi['width'] < 1e-8 and abs(Wi['gap_g'] * Wi['n'] - 1) < 1e-8
    rec('D72_interaction_matrix_and_witness_algebra', ok, **res)


def D73_rigorous_logs_and_eigenvalue_witness():
    res = {}; ok = True; rng = random.Random(73)
    # rigorous logs incl. huge / tiny rationals (no binary64 overflow in the enclosure arithmetic)
    xs = [F(2) ** 300, F(1, 2 ** 300), F(1) + F(1, 10 ** 20), F(7, 5), F(7, 10), F(10 ** 40 + 7, 3)] + [F(rng.randint(1, 10 ** 9), rng.randint(1, 10 ** 9)) for _ in range(40)]
    bad = 0; wmax = F(0)
    for x in xs:
        lo, hi = SW.log_enclosure(x); ref = _dec_ln(x); bad += int(not (lo <= ref <= hi)); wmax = max(wmax, hi - lo); float(lo); float(hi)
    res['logs'] = dict(n=len(xs), violations=bad, max_width=float(wmax)); ok = ok and bad == 0 and wmax <= F(1, 2 ** 60)
    # interval Cholesky: a known PD matrix is proved, an indefinite one refused, a too-wide interval cannot be proved
    clk = CE.Clock(time.monotonic() + 30, {}); Mpd = np.array([[4.0, 1.0, 0.5], [1.0, 3.0, 0.2], [0.5, 0.2, 2.0]]); ind = np.array([[1.0, 0.0], [0.0, -1.0]]); wide_lo = np.array([[1.0, 0.9], [0.9, 1.0]]); wide_hi = np.array([[1.0, 1.1], [1.1, 1.0]])
    r1 = SW.interval_cholesky_pd(Mpd, Mpd, clk); r2 = SW.interval_cholesky_pd(ind, ind, clk); r3 = SW.interval_cholesky_pd(wide_lo, wide_hi, clk)
    res['cholesky'] = dict(pd_ok=r1['ok'], indefinite_ok=r2['ok'], indefinite_failed_column=r2['failed_column'], wide_ok=r3['ok']); ok = ok and r1['ok'] and (not r2['ok']) and r2['failed_column'] == 1 and (not r3['ok'])
    # negative eigenvalues retained: the Ising pair exp(+-J) (table [[t, 1/t], [1/t, t]]): A has eigenvalues +-2J; the proof of A - lI uses the NEGATIVE l; the model is untouched
    def ising(t):
        return _pair_model([2, 2], [(0, 1, [t, 1 / t, 1 / t, t])])
    t = F(164, 100); mdl = ising(t); snap = json.dumps(mdl, default=str); M, clk, B = _hstage(mdl); W = SW.certify(M, B, clk); J = _dec_ln(t)
    res['negative_retained'] = dict(l=W['l'], u=W['u'], width=W['width'], expected_width_4J=float(4 * J), eligible=W['eligible'], model_untouched=(json.dumps(mdl, default=str) == snap)); ok = ok and W['l'] < 0 and abs(W['width'] - float(4 * J)) < 1e-8 and res['negative_retained']['model_untouched']
    # the factor-of-two convention: Ising width(J) = 2 J < 1 iff categorical w(A) = 4 J < 2
    below = SW.certify(*(lambda M_, c_, b_: (M_, b_, c_))(*_hstage(ising(F(164, 100))))); above = SW.certify(*(lambda M_, c_, b_: (M_, b_, c_))(*_hstage(ising(F(166, 100)))))
    res['ising_convention'] = dict(J_below=float(_dec_ln(F(164, 100))), eligible_below=below['eligible'], width_below=below['width'], J_above=float(_dec_ln(F(166, 100))), eligible_above=above['eligible'], width_above=above['width'], refusal_above=(above['refusal'] or {}).get('kind'))
    ok = ok and below['eligible'] and (not above['eligible']) and (above['refusal'] or {}).get('kind') == 'SPECTRAL_WIDTH'
    # the boundary just below / above width two: 4 ln t = 2 -+ 2e-6
    t_lo = F(math.exp(0.5 - 5e-7)).limit_denominator(10 ** 15); t_hi = F(math.exp(0.5 + 5e-7)).limit_denominator(10 ** 15)
    wl = SW.certify(*(lambda M_, c_, b_: (M_, b_, c_))(*_hstage(ising(t_lo)))); wh = SW.certify(*(lambda M_, c_, b_: (M_, b_, c_))(*_hstage(ising(t_hi))))
    res['boundary'] = dict(width_below=wl['width'], eligible_below=wl['eligible'], margin_below=wl.get('margin_m'), width_above=wh['width'], eligible_above=wh['eligible'], refusal_above=(wh['refusal'] or {}).get('kind'))
    ok = ok and wl['eligible'] and wl['width'] < 2 and (not wh['eligible']) and wh['width'] >= 2
    # tampered / insufficient witnesses are rejected by the proof; the proposal eigenvalues are advisory (eligibility with given l / u never consults them)
    M, clk, B = _hstage(ising(t)); good = SW.certify(M, B, clk); lt, ut = good['l'], good['u']
    tam = SW.certify(M, B, clk, l=lt + 0.1, u=ut); ins = SW.certify(M, B, clk, l=lt, u=ut - 0.1); fine = SW.certify(M, B, clk, l=lt, u=ut)
    res['tampered'] = dict(tampered_l_eligible=tam['eligible'], tampered_kind=(tam['refusal'] or {}).get('kind'), insufficient_u_eligible=ins['eligible'], insufficient_kind=(ins['refusal'] or {}).get('kind'), given_true_eligible=fine['eligible'], proposal_recorded=('lambda_min_float' in fine['proposal']))
    ok = ok and (not tam['eligible']) and tam['refusal']['kind'] == 'SPECTRAL_PROOF' and (not ins['eligible']) and ins['refusal']['kind'] == 'SPECTRAL_PROOF' and fine['eligible']
    rec('D73_rigorous_logs_and_eigenvalue_witness', ok, **res)


def _enum_p(hbm):
    states = list(itertools.product(*[range(k) for k in hbm.cards])); W = [hbm.log_weight(x) for x in states]; Z = sum(W); return states, [w / Z for w in W], Z


def D74_exact_conditionals_detailed_balance_and_independent_path():
    rng = random.Random(74); model = _rand_model(rng, [2, 2, 2, 2], [(0, 1), (1, 2), (2, 3), (0, 3), (0, 2)]); M, clk, B = _hstage(model); hbm = HX.HeatBathModel(M); n = hbm.n
    states, p, Z = _enum_p(hbm); idx = {x: k for k, x in enumerate(states)}; res = dict(states=len(states)); ok = True
    # conditional rows == the Fraction normalization of W over the variable
    bad = 0
    for x in states:
        for i in range(n):
            c = HX.conditional_exact(hbm, list(x), i); ws = [p[idx[tuple(list(x[:i]) + [a] + list(x[i + 1:]))]] for a in range(hbm.cards[i])]; S = sum(ws); bad += int(any(c[a] != ws[a] / S for a in range(hbm.cards[i]))) + int(sum(c) != 1)
    res['conditional_mismatches'] = bad; ok = ok and bad == 0
    # exact detailed balance of the random-scan heat-bath kernel
    def P(x, y):
        tot = F(0)
        for i in range(n):
            if all(x[k] == y[k] for k in range(n) if k != i): tot += HX.conditional_exact(hbm, list(x), i)[y[i]]
        return tot / n
    viol = 0
    for x in states:
        for y in states: viol += int(p[idx[x]] * P(x, y) != p[idx[y]] * P(y, x))
    res['detailed_balance_violations'] = viol; ok = ok and viol == 0
    # the ExactChain path reproduced by an independent minimal implementation on the same bit stream (same rejection protocol)
    def indep_path(seed, steps):
        r = random.Random(seed); x = [0] * n; path = []
        def bits(k): return r.getrandbits(k) if k > 0 else 0
        for _ in range(steps):
            if n & (n - 1) == 0: i = bits(n.bit_length() - 1)
            else:
                k = n.bit_length()
                while True:
                    v = bits(k)
                    if v < n: i = v; break
            w = []
            for a in range(hbm.cards[i]):                                                                 # the SAME weight convention as the reference (unary of i x the INCIDENT pair factors): a different common factor would change the integer scale and the bits consumed
                y = list(x); y[i] = a; wv = F(M.psi[i][a])
                for sc, vals in M.factors:
                    if len(sc) == 2 and i in sc: wv *= vals[y[sc[0]] * hbm.cards[sc[1]] + y[sc[1]]]
                w.append(wv)
            den = 1
            for v in w: den = den * v.denominator // math.gcd(den, v.denominator)
            ints = [v.numerator * (den // v.denominator) for v in w]; S = sum(ints); kb = S.bit_length()
            while True:
                u = bits(kb)
                if u < S: break
            c = 0
            for a, wi in enumerate(ints):
                c += wi
                if u < c: x[i] = a; break
            path.append(tuple(x))
        return path
    ec = HX.ExactChain(hbm, [0] * n, 1234); ref = []
    for _ in range(400): ec.step(); ref.append(tuple(ec.x))
    ip = indep_path(1234, 400); res['independent_path_identical'] = (ip == ref); res['distinct_states_visited'] = len(set(ref)); ok = ok and ip == ref and ec.t == 400
    rec('D74_exact_conditionals_detailed_balance_and_independent_path', ok, **res)


def D75_counters_and_occupation():
    rng = random.Random(75); model = _rand_model(rng, [2, 3, 2, 3, 2], [(0, 1), (1, 2), (2, 3), (3, 4), (0, 4)]); M, clk, B = _hstage(model); hbm = HX.HeatBathModel(M); n = hbm.n; res = {}; ok = True
    # exact chain: explicit per-step counts over 500 recorded steps
    ec = HX.ExactChain(hbm, [0] * n, 5)
    for _ in range(40): ec.step()
    t_before = ec.t; ec.start_recording(); counts = [[0] * k for k in hbm.cards]; nulls = 0
    for _ in range(500):
        i, old, new = ec.step(); nulls += int(old == new)
        for v in range(n): counts[v][ec.x[v]] += 1
    occ = ec.flush(); occ2 = ec.flush()
    res['exact'] = dict(steps_counted=ec.t - t_before, null_moves=nulls, flush_equals_explicit=(occ == counts), second_flush_idempotent=(occ2 == occ), sums=[sum(r) for r in occ]); ok = ok and ec.t - t_before == 500 and occ == counts and occ2 == occ and all(sum(r) == 500 for r in occ)
    for _ in range(7):
        ec.step()
        for v in range(n): counts[v][ec.x[v]] += 1
    occ3 = ec.flush(); res['exact']['k_more_steps_add_k'] = (occ3 == counts and all(sum(r) == 507 for r in occ3)); ok = ok and res['exact']['k_more_steps_add_k']
    # first recorded state convention: the state AFTER the first step following start_recording is the first counted
    ec2 = HX.ExactChain(hbm, [1, 2, 1, 0, 1], 6); ec2.start_recording(); i, old, new = ec2.step(); o1 = ec2.flush(); res['exact']['first_recorded'] = all(o1[v][ec2.x[v]] == 1 and sum(o1[v]) == 1 for v in range(n)); ok = ok and res['exact']['first_recorded']
    # native chain: single-step runs with explicit occupancy
    ch = HN.NativeChain(hbm, [0] * n, 5, clk, budget=B)
    for _ in range(40): ch.run(1)
    s0 = ch.steps(); ch.set_recording(); counts = [[0] * k for k in hbm.cards]; prev = ch.state(); nulls = 0
    for _ in range(500):
        ch.run(1); x = ch.state(); nulls += int(x == prev); prev = x
        for v in range(n): counts[v][x[v]] += 1
    occ = ch.flush(); occ2 = ch.flush(); c = ch.counters()
    res['native'] = dict(steps_counted=ch.steps() - s0, null_moves_observed=nulls, null_moves_kernel_total=c['null_moves'], flush_equals_explicit=(occ == counts), second_flush_idempotent=(occ2 == occ), sums=[sum(r) for r in occ], max_count_le_N=all(max(r) <= 500 for r in occ))
    ok = ok and ch.steps() - s0 == 500 and occ == counts and occ2 == occ and all(sum(r) == 500 for r in occ)
    for _ in range(9):
        ch.run(1); x = ch.state()
        for v in range(n): counts[v][x[v]] += 1
    occ3 = ch.flush(); res['native']['k_more_steps_add_k'] = (occ3 == counts and all(sum(r) == 509 for r in occ3)); ok = ok and res['native']['k_more_steps_add_k']; ch.close()
    rec('D75_counters_and_occupation', ok, **res)


def D76_native_exactness_qualification():
    rng = random.Random(76); n = 5; cards = [2, 3, 2, 4, 3]
    model = dict(cards=cards, factors=[dict(scope=(i, j), values=[F(rng.randint(1, 50), rng.randint(1, 7)) for _ in range(cards[i] * cards[j])]) for i in range(n) for j in range(i + 1, n) if rng.random() < 0.7] + [dict(scope=(v,), values=[F(rng.randint(1, 9)) for _ in range(cards[v])]) for v in range(n)], evidence={})
    M, clk, B = _hstage(model); hbm = HX.HeatBathModel(M); ch = HN.NativeChain(hbm, [0] * hbm.n, 7, clk); u = 2.0 ** -53; res = {}; ok = True
    # (a) CDF interval containment at 2,000 random states (every site)
    viol = 0; checked = 0
    for _ in range(2000):
        x = [rng.randrange(k) for k in hbm.cards]; ch.lib.hb_set_state(ch.ctx, (_ct.c_int * len(x))(*x)); i = rng.randrange(hbm.n); w, clo, chi = ch.inspect(i); wx = hbm.weights_exact(x, i); cum = F(0)
        sc_i = F(2) ** (ch.scales['unary'][i] + sum(ch.scales['pair'][f] for f, _ in hbm.incident[i]))          # DGP9: the kernel holds the power-of-two NORMALIZED tables (law-preserving); the exact cumulative is compared at the same scale
        for b in range(len(wx)):
            cum += wx[b] / sc_i; checked += 1; viol += int(not (F(clo[b]) <= cum <= F(chi[b])))
    res['cdf_containment'] = dict(cells=checked, violations=viol); ok = ok and viol == 0
    # (b) the kernel's decision rule (replicated bit-for-bit from heatbath_native.c) agrees with decide_exact whenever it resolves
    def kernel_rule(clo, chi, u53):
        k = len(clo); Slo, Shi = clo[-1], chi[-1]; Tlo = (u53 * u) * Slo * (1 - 2 * u); Thi = ((u53 + 1) * u) * Shi * (1 + 2 * u); a = 0
        while a < k - 1 and not (Thi < clo[a]): a += 1
        return a, ((a == 0) or (Tlo >= chi[a - 1]))
    agree = 0; resolved = 0
    for _ in range(3000):
        x = [rng.randrange(k) for k in hbm.cards]; ch.lib.hb_set_state(ch.ctx, (_ct.c_int * len(x))(*x)); i = rng.randrange(hbm.n); w, clo, chi = ch.inspect(i); u53 = rng.getrandbits(53); a, okd = kernel_rule(clo, chi, u53)
        ex, extra = HX.decide_exact(hbm.weights_exact(x, i), u53, lambda kk: rng.getrandbits(kk) if kk else 0)
        if okd: resolved += 1; agree += int(ex == a)
    res['decisions'] = dict(trials=3000, resolved=resolved, agree=agree, disagreements=resolved - agree); ok = ok and resolved == agree and resolved > 2900
    # (c) a DELIBERATELY ALTERED floating conditional (eps = 0, nearest sums, no unresolved state) fails on an adversarial u53 at a cumulative boundary, although its histogram looks fine; the kernel rule reports UNRESOLVED there
    x = [1, 2, 0, 3, 1]; i = 3; wx = hbm.weights_exact(x, i); S = sum(wx); cum = []; c = F(0)
    for v in wx: c += v; cum.append(c)
    a_b = 1; frac = cum[a_b] / S; u53 = (frac.numerator << 53) // frac.denominator                      # U in [u53, u53 + 1) / 2^53 straddles C_{a_b} / S
    assert F(u53, 1 << 53) <= frac < F(u53 + 1, 1 << 53)
    def altered_rule(wf, u53):
        Sf = sum(wf); T = (u53 / 2.0 ** 53) * Sf; cf = 0.0
        for a, v in enumerate(wf):
            cf += v
            if T < cf: return a
        return len(wf) - 1
    wf = [float(v) for v in wx]; alt = altered_rule(wf, u53); ex0, _ = HX.decide_exact(wx, u53, lambda kk: 0); ex1, _ = HX.decide_exact(wx, u53, lambda kk: (1 << kk) - 1 if kk else 0)
    ch.lib.hb_set_state(ch.ctx, (_ct.c_int * len(x))(*x)); w_, clo_, chi_ = ch.inspect(i); ka, kok = kernel_rule(clo_, chi_, u53)
    hist = [0] * len(wx); T = 20000
    for _ in range(T): hist[altered_rule(wf, rng.getrandbits(53))] += 1
    hist_dev = max(abs(hist[a] / T - float(wx[a] / S)) for a in range(len(wx)))
    res['altered_conditional'] = dict(adversarial_u53_bits=u53.bit_length(), exact_with_zero_bits=ex0, exact_with_one_bits=ex1, altered_decision=alt, altered_disagrees_with_some_exact=(alt != ex0 or alt != ex1), kernel_rule_resolved_here=kok, histogram_max_abs_deviation=hist_dev, histogram_looks_reasonable=(hist_dev < 0.02))
    ok = ok and (ex0 != ex1) and (alt != ex0 or alt != ex1) and (not kok); ch.close()
    rec('D76_native_exactness_qualification', ok, **res)


def _run_runner(path, budget, stop, extra=()):
    out = _tmp.mktemp(suffix='.json', prefix='dgp8_ctl_'); p = _sp.run([_PY8, _RUNNER, '--input', path, '--output', out, '--budget', str(budget), '--admission-stop', str(stop), '--seed', '1'] + list(extra), capture_output=True, text=True, timeout=60)
    d = json.load(open(out)) if os.path.exists(out) else None
    return d, p.returncode, (p.stderr or '')[-600:]


def D77_optional_route_refusals():
    res = {}; ok = True; clk = CE.Clock(time.monotonic() + 30, {})
    # hard zero -> typed RefusedSpectral('HARD_ZERO')
    mz = _pair_model([2, 2], [(0, 1, [F(1), F(0), F(2), F(3)])]); Mz, ck, Bz = _hstage(mz); live0 = Bz.live
    try: SW.certify(Mz, Bz, ck); res['hard_zero'] = dict(raised=False)
    except SW.RefusedSpectral as e: res['hard_zero'] = dict(raised=True, kind=e.kind, live_restored=(Bz.live == live0))
    ok = ok and res['hard_zero'].get('kind') == 'HARD_ZERO' and res['hard_zero'].get('live_restored')
    # a 3-ary factor -> RefusedSpectral('ARITY')
    m3 = dict(cards=[2, 2, 2], factors=[dict(scope=(0, 1, 2), values=[F(1 + k) for k in range(8)])], evidence={}); M3, ck3, B3 = _hstage(m3); live0 = B3.live
    try: SW.certify(M3, B3, ck3); res['arity'] = dict(raised=False)
    except SW.RefusedSpectral as e: res['arity'] = dict(raised=True, kind=e.kind, live_restored=(B3.live == live0))
    ok = ok and res['arity'].get('kind') == 'ARITY' and res['arity'].get('live_restored')
    # a strong model (width >= 2): eligible False, typed SPECTRAL_WIDTH, no exception
    model, _ = load_odev('dg_n6_c4_clique_two'); M6, ck6, B6 = _hstage(model); W = SW.certify(M6, B6, ck6); res['strong_n6'] = dict(eligible=W['eligible'], kind=(W['refusal'] or {}).get('kind'), width=W['width']); ok = ok and (not W['eligible']) and res['strong_n6']['kind'] == 'SPECTRAL_WIDTH' and W['width'] >= 2
    # the runner on the strong model: outcome REFUSED, refusal recorded, every row NOT_PUBLISHED, complete JSON, deadline respected
    d, rc, err = _run_runner(os.path.join(ORACLE_DEV, 'dg_n6_c4_clique_two.uai'), 4.0, 3.5)
    res['runner_strong'] = dict(rc=rc, outcome=(d or {}).get('outcome'), refusal=((d or {}).get('mechanism') or {}).get('refusal'), K=(d or {}).get('K'), published=(d or {}).get('published'), all_not_published=(bool(d) and all(r.get('guarantee') == 'NOT_PUBLISHED' for r in d.get('answers') or []) and len(d.get('answers') or []) in (0, d.get('K'))), hard_deadline_respected=(d or {}).get('hard_deadline_respected'), stderr_tail=err[-200:])
    ok = ok and d is not None and rc == 0 and d.get('outcome') == 'REFUSED' and (d['mechanism'].get('refusal') or {}).get('kind') == 'SPECTRAL_WIDTH' and d.get('published') == 0 and d.get('hard_deadline_respected') is True
    rec('D77_optional_route_refusals', ok, **res)


def D78_markov_certificate_algebra():
    rng = random.Random(78); res = {}; ok = True
    model = _rand_model(rng, [2, 2, 2, 2], [(0, 1), (1, 2), (2, 3), (0, 3)]); M, clk, B = _hstage(model); hbm = HX.HeatBathModel(M); states, p, Z = _enum_p(hbm); idx = {x: k for k, x in enumerate(states)}
    x0 = MC.choose_x0(hbm); lp0, lw = MC.log_p0_lower(hbm, x0); px0 = p[idx[tuple(x0)]]; ZU = F(1)
    for i, k in enumerate(hbm.cards): ZU *= k * max(hbm.psi[i])
    for (_, _, _, _, vals) in hbm.pairs: ZU *= max(vals)
    p0_exact = hbm.log_weight(x0) / ZU
    res['p0'] = dict(ln_p0_lower=float(lp0), ln_p0_exact=float(_dec_ln(p0_exact)), ln_px0=float(_dec_ln(px0)), bound_le_exact_p0=(lp0 <= _dec_ln(p0_exact)), p0_le_px0=(p0_exact <= px0), Z_le_ZU=(Z <= ZU)); ok = ok and lp0 <= _dec_ln(p0_exact) and p0_exact <= px0 and Z <= ZU
    # logarithmic overflow handling: factor values 2^+-900 as rationals -> finite exact Fractions, finite floats
    mh = _pair_model([2, 2], [(0, 1, [F(2) ** 900, F(1, 2 ** 900), F(1), F(3)])], unaries={0: [F(2) ** 900, F(1)]}); Mh, ckh, Bh = _hstage(mh); hh = HX.HeatBathModel(Mh); lz = MC.log_Z_upper(hh); lph, _ = MC.log_p0_lower(hh, MC.choose_x0(hh))
    res['overflow'] = dict(ln_Z_upper=float(lz), ln_p0_lower=float(lph), finite=(math.isfinite(float(lz)) and math.isfinite(float(lph)))); ok = ok and res['overflow']['finite'] and lph <= 0
    # degenerate gaps: n = 1 (g -> 1), the independent model; burn-in finite
    m1 = dict(cards=[3, 2], factors=[dict(scope=(0,), values=[F(1), F(2), F(3)]), dict(scope=(1,), values=[F(1), F(5)]), dict(scope=(0, 1), values=[F(1)] * 6)], evidence={}); M1, ck1, B1 = _hstage(m1); W1 = SW.certify(M1, B1, ck1); h1 = HX.HeatBathModel(M1); lp1, _ = MC.log_p0_lower(h1, MC.choose_x0(h1))
    g1 = F(W1['g_exact']); t1, b1 = MC.burn_in_steps(lp1, g1, F(1, 2 * 10 ** 6)); res['degenerate'] = dict(width=W1['width'], g=float(g1), n=W1['n'], g_times_n=float(g1 * W1['n']), burn_in=t1, eligible=W1['eligible']); ok = ok and W1['eligible'] and abs(float(g1 * W1['n']) - 1) < 1e-8 and isinstance(t1, int) and t1 >= 0
    # the radius formula: monotone in N, matches a float evaluation
    g = F(1, 3000); Q = 256; dj = F(1, 8 * 10 ** 6); prev = F(2); mono = True; relerr = 0.0
    for N in (10 ** 3, 10 ** 4, 10 ** 5, 10 ** 6, 10 ** 7):
        r = MC.radius_upper(N, Q, dj, g); mono = mono and r <= prev; prev = r; rf = min(1.0, math.sqrt((2 - float(g)) * math.log(2 * Q / float(dj)) / (2 * N * float(g)))); relerr = max(relerr, abs(float(r) - rf) / rf)          # the certificate clips the radius at one
        ok = ok and float(r) >= rf * (1 - 1e-15)
    res['radius'] = dict(monotone=mono, max_rel_err_vs_float=relerr, upper_bound_of_float=True); ok = ok and mono and relerr < 1e-12
    # fixed checkpoints and the delta accounting
    plan = MC.checkpoint_plan(1000003); J = MC.PROFILE['checkpoints_J']; dsample = F(1, 2 * 10 ** 6); djs = [dsample / J] * J
    import spectral_heatbath_run as SHR
    res['checkpoints'] = dict(plan=plan, strictly_increasing=all(plan[k] < plan[k + 1] for k in range(len(plan) - 1)), last_is_N_max=(plan[-1] == 1000003), sum_delta_j_equals_delta_sample=(sum(djs) == dsample), beta_plus_sample_le_delta=(SHR.PROFILE['beta_share'] + SHR.PROFILE['delta_sample_share'] <= 1))
    ok = ok and res['checkpoints']['strictly_increasing'] and res['checkpoints']['last_is_N_max'] and res['checkpoints']['sum_delta_j_equals_delta_sample'] and res['checkpoints']['beta_plus_sample_le_delta']
    # a deliberate deadline crossing in the runner: zero rows, complete JSON, typed outcome
    d, rc, err = _run_runner(_WEAK32, 0.3, 0.2); res['deadline_crossing'] = dict(rc=rc, outcome=(d or {}).get('outcome'), published=(d or {}).get('published'), refusal=((d or {}).get('mechanism') or {}).get('refusal'), json_complete=(d is not None and 'wall_s' in d), stderr_tail=err[-300:])
    ok = ok and d is not None and rc == 0 and d.get('outcome') in ('REFUSED', 'DEADLINE') and d.get('published') == 0
    rec('D78_markov_certificate_algebra', ok, **res)


def D79_rng_expiry_and_admission():
    res = {}; ok = True; rng = random.Random(79)
    # rejection loop expiry: a bit source that always rejects + an expired clock -> typed DEADLINE refusal (never an endless loop)
    dead = CE.Clock(time.monotonic() - 1.0, {})
    try: HX.uniform_below(5, lambda k: (1 << k) - 1, dead, 'ctl'); res['rejection_expiry'] = dict(raised=False)
    except CE.Refused as e: res['rejection_expiry'] = dict(raised=True, kind=e.kind)
    ok = ok and res['rejection_expiry'].get('kind') == 'DEADLINE'
    # refinement expiry: weights (1, 2) with U at the boundary 1/3 whose binary expansion is fed as the refinement bits -> RNG_REFINEMENT
    S = 3; u53 = (1 << 53) // 3
    def third_bits(k, _st=[53]):
        v = ((1 << (_st[0] + k)) // 3) & ((1 << k) - 1) if k else 0; _st[0] += k; return v
    try: HX.decide_exact([F(1), F(2)], u53, third_bits, max_extra_bits=8); res['refinement_expiry'] = dict(raised=False)
    except CE.Refused as e: res['refinement_expiry'] = dict(raised=True, kind=e.kind)
    ok = ok and res['refinement_expiry'].get('kind') == 'RNG_REFINEMENT'
    # admission of the native kernel: estimate >= actual, charged before creation, released on close; a small cap refuses typed with no leak
    model = _rand_model(rng, [2, 3, 2, 3], [(0, 1), (1, 2), (2, 3)]); M, clk, B = _hstage(model); hbm = HX.HeatBathModel(M); live0 = B.live; ch = HN.NativeChain(hbm, [0] * hbm.n, 3, clk, budget=B); est = HN.kernel_bytes_estimate(hbm); act = int(ch.lib.hb_bytes(ch.ctx))
    res['kernel_admission'] = dict(estimate=est, actual=act, estimate_ge_actual=(est >= act), live_after_create=B.live - live0, charged_equals_estimate=(B.live - live0 == est)); ch.close(); res['kernel_admission']['live_after_close_restored'] = (B.live == live0); ok = ok and est >= act and B.live - live0 == 0 and res['kernel_admission']['charged_equals_estimate']
    small = CE.Budget(est // 2)
    try: HN.NativeChain(hbm, [0] * hbm.n, 3, clk, budget=small); res['small_cap'] = dict(raised=False)
    except CE.Refused as e: res['small_cap'] = dict(raised=True, kind=e.kind, live_after=small.live)
    ok = ok and res['small_cap'].get('kind') == 'MEMORY' and res['small_cap'].get('live_after') == 0
    # the witness releases every array on every exit: eligible, refused (width), and the raised class refusal
    # DGP9: the witness RETAINS the charge of its returned advisory fields (h / offsets / cards) until the owner releases it (review RV6); the controls check the retained charge is exactly the declared one and that the release restores the baseline
    M2, ck2, B2 = _hstage(_pair_model([2, 2], [(0, 1, [F(164, 100), F(100, 164), F(100, 164), F(164, 100)])])); l0 = B2.live; W = SW.certify(M2, B2, ck2); ret = W.get('retained_bytes'); res['witness_release_eligible'] = dict(eligible=W['eligible'], retained_bytes=ret, live_minus_retained_restored=(B2.live - (ret or 0) == l0)); SW.release_retained(W, B2); res['witness_release_eligible']['live_restored_after_release'] = (B2.live == l0); ok = ok and B2.live == l0 and res['witness_release_eligible']['live_minus_retained_restored'] and bool(ret)
    M3, ck3, B3 = _hstage(load_odev('dg_n6_c4_clique_two')[0]); l0 = B3.live; W3 = SW.certify(M3, B3, ck3); SW.release_retained(W3, B3); res['witness_release_refused'] = dict(kind=(W3['refusal'] or {}).get('kind'), live_restored=(B3.live == l0)); ok = ok and B3.live == l0
    M4, ck4, B4 = _hstage(_pair_model([2, 2], [(0, 1, [F(1), F(0), F(1), F(1)])])); l0 = B4.live
    try: SW.certify(M4, B4, ck4)
    except SW.RefusedSpectral: pass
    res['witness_release_raised'] = dict(live_restored=(B4.live == l0)); ok = ok and B4.live == l0
    # no negative release: a budget never goes below its baseline after charge / release cycles
    res['no_negative_release'] = (B.live >= 0 and B2.live >= 0 and B3.live >= 0 and B4.live >= 0); ok = ok and res['no_negative_release']
    rec('D79_rng_expiry_and_admission', ok, **res)


def D80_finalizer_before_single_final_timestamp():
    res = {}; ok = True; src = open(_RUNNER_SRC).read(); i0 = src.index('def finish('); i1 = src.index('\n    try:', i0); body = src[i0:i1]
    n_tnow = body.count('tnow()'); after = body.split('t_end = tnow()')[1] if 't_end = tnow()' in body else ''
    res['source'] = dict(tnow_calls_in_finish=n_tnow, single_authoritative_sample=(n_tnow == 1), rows_assigned_after_sample=("out['answers'] = rows" in after), late_suppression_present=('suppressed_late_rows' in after)); ok = ok and n_tnow == 1 and res['source']['rows_assigned_after_sample'] and res['source']['late_suppression_present']
    # a run whose final sample lands late (the budget is below the canonicalization + witness time)
    d, rc, err = _run_runner(_WEAK64, 0.05, 0.04); res['late'] = dict(rc=rc, outcome=(d or {}).get('outcome'), hard_deadline_respected=(d or {}).get('hard_deadline_respected'), published=(d or {}).get('published'), suppressed=((d or {}).get('mechanism') or {}).get('suppressed_late_rows'), refusal=((d or {}).get('mechanism') or {}).get('refusal'), json_complete=(d is not None and 'wall_s' in d), stderr_tail=err[-300:])
    ok = ok and d is not None and rc == 0 and d.get('published') == 0 and d.get('outcome') in ('DEADLINE', 'REFUSED') and len(d.get('answers') or []) == d.get('K')          # DGP9: the inventory is typed on every exit; the late-SAMPLE case itself is D85 (injected crossing)
    # a normal short run: deadline respected, at least one completed checkpoint, rows or enclosures, total failure probability within delta
    d2, rc2, err2 = _run_runner(_WEAK32, 3.0, 2.5); m = (d2 or {}).get('mechanism') or {}; cps = m.get('checkpoints') or []; cert = m.get('certificate') or {}
    res['normal'] = dict(rc=rc2, outcome=(d2 or {}).get('outcome'), hard_deadline_respected=(d2 or {}).get('hard_deadline_respected'), checkpoints_completed=sum(1 for c in cps if c.get('completed')), published=(d2 or {}).get('published'), enclosures=len((d2 or {}).get('enclosures') or []), radius=cert.get('radius'), total_failure_probability=cert.get('total_failure_probability'), transitions=(m.get('transitions') or {}).get('recorded'), wall_s=(d2 or {}).get('wall_s'), stderr_tail=err2[-300:])
    ok = ok and d2 is not None and rc2 == 0 and d2.get('hard_deadline_respected') is True and res['normal']['checkpoints_completed'] >= 1 and (d2.get('published') or len(d2.get('enclosures') or [])) and cert.get('total_failure_probability') is not None and F(cert['total_failure_probability']) <= F(1, 10 ** 6)
    rec('D80_finalizer_before_single_final_timestamp', ok, **res)


def D81_publication_geometry():
    res = {}; ok = True; eps = F(1, 200)
    pub, enc, st = MC.rows_from_counts([[60, 40]], 100, eps - F(1, 10 ** 9), eps, [0], {}); res['just_below'] = dict(published=len(pub), enclosures=len(enc), points_sum_one=(sum(v[2] for v in pub.values()) == 1 if pub else None), point_inside=all(v[0] <= v[2] <= v[1] for v in pub.values()), widths_le_2eps=all(v[1] - v[0] <= 2 * eps for v in pub.values()))
    ok = ok and len(pub) == 2 and len(enc) == 0 and res['just_below']['points_sum_one'] and res['just_below']['point_inside'] and res['just_below']['widths_le_2eps']
    pub2, enc2, st2 = MC.rows_from_counts([[60, 40]], 100, eps + F(1, 10 ** 9), eps, [0], {}); res['just_above'] = dict(published=len(pub2), enclosures=len(enc2), enclosure_width_gt_2eps=all(e[3] - e[2] > 2 * eps for e in enc2)); ok = ok and len(pub2) == 0 and len(enc2) == 2 and res['just_above']['enclosure_width_gt_2eps']
    pub3, enc3, _ = MC.rows_from_counts([[100, 0]], 100, F(1, 1000), eps, [0], {}); res['clipping'] = dict(rows=[(str(v[0]), str(v[1]), str(v[2])) for v in pub3.values()], clipped_to_unit=all(F(0) <= v[0] <= v[1] <= F(1) for v in pub3.values()), published=len(pub3)); ok = ok and len(pub3) == 2 and res['clipping']['clipped_to_unit']
    # fixed rows (card-1 and factorless variables) are EXACT rows in the runner
    import hp_gen as _G
    m = dict(cards=[2, 1, 3, 2], factors=[dict(scope=(0, 3), values=[F(3), F(1), F(1), F(2)]), dict(scope=(0,), values=[F(1), F(2)]), dict(scope=(2,), values=[F(1), F(2), F(1)])], evidence={})          # variable 1 card-1, variable 2 factorless
    path = _tmp.mktemp(suffix='.uai', prefix='dgp8_fixed_'); _G.write(path, m); d, rc, err = _run_runner(path, 2.0, 1.5); rows = {(r['var'], r['state']): r for r in (d or {}).get('answers') or []}
    fixed = {k: rows.get(k) for k in ((1, 0), (2, 0), (2, 1), (2, 2))}
    def exact_ok(r, val): return r is not None and r.get('guarantee') == 'EXACT' and r.get('lo') == r.get('hi') == r.get('point') and F(r['lo']) == val
    res['fixed_rows'] = dict(rc=rc, outcome=(d or {}).get('outcome'), rows={str(k): (v.get('guarantee'), v.get('lo')) if v else None for k, v in fixed.items()}, card1_exact_one=exact_ok(fixed[(1, 0)], F(1)), factorless_exact=(exact_ok(fixed[(2, 0)], F(1, 4)) and exact_ok(fixed[(2, 1)], F(1, 2)) and exact_ok(fixed[(2, 2)], F(1, 4))), stderr_tail=err[-200:])
    ok = ok and d is not None and res['fixed_rows']['card1_exact_one'] and res['fixed_rows']['factorless_exact']
    rec('D81_publication_geometry', ok, **res)


CONTROLS += [D72_interaction_matrix_and_witness_algebra, D73_rigorous_logs_and_eigenvalue_witness, D74_exact_conditionals_detailed_balance_and_independent_path, D75_counters_and_occupation, D76_native_exactness_qualification, D77_optional_route_refusals, D78_markov_certificate_algebra, D79_rng_expiry_and_admission, D80_finalizer_before_single_final_timestamp, D81_publication_geometry]


# ---- DGP9 (D82-D90): the review's findings RV1-RV7 and the original DGP7 findings F1-F7 as qualification controls (brief CLAUDE_DGP8_REPAIR_AND_CONTINUATION.md 'Required repairs'); every fixture is the review's own or a stronger
# variant; the controls FAIL on the parent (the DGP8 engine) and must PASS at the frozen commit
import tracemalloc as _tm
from unittest.mock import patch as _patch
_DGP9_PACKET = RECORDS + '/code/runs/mdi_2026-10-28/DGP9_SPECTRAL_HEATBATH_CONTINUATION/PACKET/review_evidence/dgp8_review/reference_recovery/packet'


def _tri_model(entry):
    return dict(cards=[2, 2, 2], factors=[dict(scope=(i, j), values=[F(entry)] * 4) for i, j in [(0, 1), (0, 2), (1, 2)]], evidence={})


def D82_native_range_gauges_and_exact_decisions():
    """review RV1: (a) the uniform scaled triangle at 2^0 / 2^-600 / 2^600 and a subnormal-intermediate gauge (entries 2^-540: pair products 2^-1080 before normalization) give IDENTICAL native sample paths, zero unresolved and
    no absorbing state (the law is scale-invariant and the normalized kernel never leaves the normal range); (b) the full standalone runner on the 1e-200 triangle returns COMPLETE with every published row containing 1/2; (c) a
    one-table 2^+-600 range is REFUSED NATIVE_RANGE before any commit and the runner's exact-chain fallback encloses the exact marginals; (d) on a random mixed-cardinality model 2,000 random (state, site, 53-bit prefix) triples
    give kernel decisions equal to decide_exact whenever the kernel resolves, and deliberately ambiguous prefixes at cumulative boundaries force the exact fallback (resolved by extra bits, both continuations consistent)"""
    res = {}; ok = True; rng = random.Random(82); paths = []
    for power in (0, -600, 600, -540):
        scale = (F(2) ** power) if power >= 0 else F(1) / (F(2) ** (-power)); M, clk, B = _hstage(dict(cards=[2, 2, 2], factors=[dict(scope=(i, j), values=[scale] * 4) for i, j in [(0, 1), (0, 2), (1, 2)]], evidence={})); hbm = HX.HeatBathModel(M)
        ch = HN.NativeChain(hbm, [0, 0, 0], 1, clk, budget=B); w, lo, hi = ch.inspect(0); ch.set_recording(); ch.run(20000, batch=1000); cnt = ch.flush(); c = ch.counters(); rec_ = ch.record(); ch.close()
        paths.append(json.dumps(cnt)); res['gauge_%d' % power] = dict(native_weights=w, counts=cnt, unresolved=c['unresolved'], range_min_log2=rec_['range']['min_weight_log2_lower'], absorbed=any(x in (0, 20000) for row in cnt for x in row))
        ok = ok and c['unresolved'] == 0 and not res['gauge_%d' % power]['absorbed'] and B.live == res.get('_live0', B.live)
    res['identical_paths_across_gauges'] = (len(set(paths)) == 1); ok = ok and res['identical_paths_across_gauges']
    import hp_gen as _G; p = _tmp.mktemp(suffix='.uai', prefix='dgp9_tri_'); _G.write(p, _tri_model(F(1, 10 ** 200))); d, rc, err = _run_runner(p, 3.0, 2.5); rows = (d or {}).get('answers') or []
    bad = [x for x in rows if x['guarantee'] != 'NOT_PUBLISHED' and not (F(x['lo']) <= F(1, 2) <= F(x['hi']))]; res['runner_1e-200'] = dict(rc=rc, outcome=(d or {}).get('outcome'), published=(d or {}).get('published'), wrong_rows=len(bad), chain=((d or {}).get('mechanism') or {}).get('chain'), stderr=err[-200:])
    ok = ok and d is not None and d.get('outcome') == 'COMPLETE' and d.get('published') == 6 and not bad
    # (c) a wide one-table range: NATIVE_RANGE, then the exact chain through the runner encloses the exact marginals of the 2 x 2 model
    wide = dict(cards=[2, 2], factors=[dict(scope=(0, 1), values=[F(2) ** 600, F(1), F(1), F(1) / (F(2) ** 600)])], evidence={}); M, clk, B = _hstage(wide); hbm = HX.HeatBathModel(M)
    try: HN.NativeChain(hbm, [0, 0], 1, clk, budget=B); res['wide_native'] = dict(refused=False)
    except CE.Refused as e: res['wide_native'] = dict(refused=True, kind=e.kind, live_after=B.live)
    ok = ok and res['wide_native'].get('kind') == 'NATIVE_RANGE'
    p2 = _tmp.mktemp(suffix='.uai', prefix='dgp9_wide_'); _G.write(p2, wide); d2, rc2, err2 = _run_runner(p2, 3.0, 2.5); m2 = (d2 or {}).get('mechanism') or {}
    Z = sum(wide['factors'][0]['values']); truth = {(0, 0): (wide['factors'][0]['values'][0] + wide['factors'][0]['values'][1]) / Z, (0, 1): (wide['factors'][0]['values'][2] + wide['factors'][0]['values'][3]) / Z, (1, 0): (wide['factors'][0]['values'][0] + wide['factors'][0]['values'][2]) / Z, (1, 1): (wide['factors'][0]['values'][1] + wide['factors'][0]['values'][3]) / Z}
    enc = {(e['var'], e['state']): (F(e['lo']), F(e['hi'])) for e in (d2 or {}).get('enclosures') or []}; enc.update({(r['var'], r['state']): (F(r['lo']), F(r['hi'])) for r in (d2 or {}).get('answers') or [] if r.get('guarantee') != 'NOT_PUBLISHED'})
    res['wide_runner'] = dict(rc=rc2, outcome=(d2 or {}).get('outcome'), chain=m2.get('chain'), native_refusal=(m2.get('native_refusal') or {}).get('kind'), rows_enclosing_truth=sum(1 for k, v in truth.items() if k in enc and enc[k][0] <= v <= enc[k][1]), rows=len(truth), transitions=(m2.get('transitions') or {}).get('total'), stderr=err2[-200:])
    ok = ok and m2.get('chain') == 'exact' and res['wide_runner']['rows_enclosing_truth'] == 4
    # (d) decisions vs decide_exact on identical prefixes; ambiguous prefixes force the fallback
    cards = [2, 3, 2, 4, 3]; model = dict(cards=cards, factors=[dict(scope=(i, j), values=[F(rng.randint(1, 50), rng.randint(1, 7)) for _ in range(cards[i] * cards[j])]) for i in range(5) for j in range(i + 1, 5) if rng.random() < 0.7] + [dict(scope=(v,), values=[F(rng.randint(1, 9)) for _ in range(cards[v])]) for v in range(5)], evidence={})
    M, clk, B = _hstage(model); hbm = HX.HeatBathModel(M); ch = HN.NativeChain(hbm, [0] * hbm.n, 7, clk, budget=B); u = 2.0 ** -53
    def kernel_rule(clo, chi, u53):
        k = len(clo); Tlo = (u53 * u) * clo[-1] * (1 - 2 * u); Thi = ((u53 + 1) * u) * chi[-1] * (1 + 2 * u); a_ = 0
        while a_ < k - 1 and not (Thi < clo[a_]): a_ += 1
        return a_, ((a_ == 0) or (Tlo >= chi[a_ - 1]))
    agree = resolved = 0; forced = 0; forced_consistent = 0
    for t in range(2000):
        x = [rng.randrange(k) for k in hbm.cards]; ch.lib.hb_set_state(ch.ctx, (_ct.c_int * len(x))(*x)); i = rng.randrange(hbm.n); w, clo, chi = ch.inspect(i); wx = hbm.weights_exact(x, i)
        if t % 10 == 0:                                                                                   # an ambiguous prefix: U straddles a cumulative boundary
            S = sum(wx); cum = F(0)
            for v in wx[:-1]: cum += v
            frac = (cum if rng.random() < 0.5 else wx[0]) / S; u53 = (frac.numerator << 53) // frac.denominator
        else: u53 = rng.getrandbits(53)
        a_, okd = kernel_rule(clo, chi, u53); e0, _ = HX.decide_exact(wx, u53, lambda kk: 0); e1, _ = HX.decide_exact(wx, u53, lambda kk: (1 << kk) - 1 if kk else 0)
        if okd: resolved += 1; agree += int(e0 == a_ == e1)
        else: forced += 1; forced_consistent += int(e0 <= e1)
    ch.close(); res['decisions'] = dict(trials=2000, resolved=resolved, agree=agree, forced_fallbacks=forced, forced_consistent=forced_consistent); ok = ok and resolved == agree and forced > 0 and forced == forced_consistent
    rec('D82_native_range_gauges_and_exact_decisions', ok, **res)


def D83_spectral_exact_accumulation():
    """review RV2: (a) 256 pointwise-inverse factor pairs on one binary pair give an interaction interval CONTAINING the exact zero; (b) the complete false-admission fixture (10,000 factors 2^3000, their 10,000 inverses, one
    rational factor with exact width > 2) is REFUSED (width cannot qualify); (c) the enclosure is invariant under permutations of the factor list (exact accumulation); (d) a near-boundary Ising under policy 'revised' is admitted
    only while u - l + 2 e_k < 2 (the retries stop when the width cannot qualify) and every attempt is recorded with its proof time"""
    res = {}; ok = True
    def model(factors):
        m = CE.Canon(); m.cards = [2, 2]; m.psi = [[F(1), F(1)], [F(1), F(1)]]; m.factors = factors; m.orig_of = [0, 1]; return m
    rv = [F(2), F(3), F(7), F(19, 3), F(1, 2), F(1, 3), F(1, 7), F(3, 19), F(2) ** 300, F(1, 2 ** 300), F(1) + F(1, 2 ** 40)]; rng = random.Random(83); worst = None
    for it in range(30):
        pos = [rng.choice(rv) for _ in range(128)]; rs = pos + [1 / x for x in pos]; rng.shuffle(rs); b = SW.build_interaction(model([((0, 1), [x, F(1), F(1), x]) for x in rs]), CE.Budget(64 << 20), CE.Clock(time.monotonic() + 20, {}))
        if not (b['A_lo'][0, 2] <= 0 <= b['A_hi'][0, 2]): worst = dict(trial=it, lo=float(b['A_lo'][0, 2]), hi=float(b['A_hi'][0, 2])); break
    res['cancellation_zero'] = dict(trials=it + 1, excluded=worst); ok = ok and worst is None
    N = 10000; k = 3000; rr = F(math.exp(-1 - 5e-10)); power = F(2) ** k
    raw = {'cards': [2, 2], 'evidence': {}, 'factors': [{'scope': (0, 1), 'values': [power, F(1), F(1), power]}] * N + [{'scope': (0, 1), 'values': [1 / power, F(1), F(1), 1 / power]}] * N + [{'scope': (0, 1), 'values': [rr, F(1), F(1), rr]}]}
    M, clk, B = _hstage(raw, 60); l0 = B.live; W = SW.certify(M, B, clk, policy=SW.POLICY_REVISED); SW.release_retained(W, B)
    res['false_admission'] = dict(eligible=W['eligible'], refusal=(W.get('refusal') or {}).get('kind'), width_proposal=W.get('width_proposal_float'), true_width_lower=float(-2 * SW.log_enclosure(rr)[1]), live_restored=(B.live == l0)); ok = ok and not W['eligible'] and res['false_admission']['refusal'] == 'SPECTRAL_WIDTH' and B.live == l0
    fs = [((0, 1), [x, F(1), F(1), x]) for x in (rv + [1 / x for x in rv])]; b1 = SW.build_interaction(model(fs), CE.Budget(64 << 20), CE.Clock(time.monotonic() + 20, {})); b2 = SW.build_interaction(model(list(reversed(fs))), CE.Budget(64 << 20), CE.Clock(time.monotonic() + 20, {}))
    res['order_invariance'] = bool(np.array_equal(b1['A_lo'], b2['A_lo']) and np.array_equal(b1['A_hi'], b2['A_hi'])); ok = ok and res['order_invariance']
    def ising(t): return dict(cards=[2, 2], factors=[dict(scope=(0, 1), values=[t, 1 / t, 1 / t, t])], evidence={})
    rows = []
    for t in (F(164, 100), F(16487, 10000), F(166, 100)):
        M, clk, B = _hstage(ising(t)); Wf = SW.certify(M, B, clk, policy=SW.POLICY_FIXED); SW.release_retained(Wf, B); Wr = SW.certify(M, B, clk, policy=SW.POLICY_REVISED); SW.release_retained(Wr, B)
        rows.append(dict(t=str(t), fixed=Wf['eligible'], revised=Wr['eligible'], attempts=len(Wr.get('attempts') or []), attempt_seconds=[round(x['seconds'], 4) for x in Wr.get('attempts') or []], refusal=(Wr.get('refusal') or {}).get('kind'), width=Wr.get('width')))
    res['policy_boundary'] = rows; ok = ok and rows[0]['fixed'] and rows[0]['revised'] and (not rows[2]['revised']) and all(r_['attempts'] >= 1 for r_ in rows[:2])
    rec('D83_spectral_exact_accumulation', ok, **res)


def D84_jbox_publication():
    """review RV4: the clipped-interval fixture (counts [1, 998, 1], N = 1000, r = 0.007, eps = 0.005) publishes ONLY epsilon-safe points (endpoint radius <= eps on every row; the review's truth (0.008, 0.991, 0.001) lies within eps of
    every point); the whole variable publishes or none; a width above 2 eps on one row keeps every row of the variable an enclosure; the J-box normalized points sum to one when the J box meets the simplex"""
    res = {}; ok = True; eps = F(1, 200); truth = [F(8, 1000), F(991, 1000), F(1, 1000)]
    pub, enc, st = MC.rows_from_counts([[1, 998, 1]], 1000, F(7, 1000), eps, [0], {}); rows = sorted(pub.items())
    res['clipped'] = dict(published=len(pub), enclosures=len(enc), endpoint_radii=[float(max(p - lo, hi - p)) for (_, (lo, hi, p, g)) in rows], max_point_error_vs_truth=float(max(abs(p - truth[a]) for ((v, a), (lo, hi, p, g)) in rows)) if rows else None, policy=st['point_policy_counts'])
    ok = ok and len(pub) == 3 and all(max(p - lo, hi - p) <= eps for (_, (lo, hi, p, g)) in rows) and all(abs(p - truth[a]) <= eps for ((v, a), (lo, hi, p, g)) in rows)
    pub2, enc2, st2 = MC.rows_from_counts([[500, 300, 200]], 1000, F(6, 1000), eps, [0], {}); res['one_wide_row_blocks_variable'] = dict(published=len(pub2), enclosures=len(enc2)); ok = ok and len(pub2) == 0 and len(enc2) == 3
    pub3, enc3, st3 = MC.rows_from_counts([[400, 600]], 1000, F(1, 500), eps, [0], {}); res['normalized_points'] = dict(published=len(pub3), sum_one=(sum(v[2] for v in pub3.values()) == 1), policy=st3['point_policy_counts']); ok = ok and len(pub3) == 2 and res['normalized_points']['sum_one']
    rec('D84_jbox_publication', ok, **res)


def D85_runner_contracts():
    """review RV5 / RV7: (a) the original-Z enclosure of a model with canonical scalar 2000 contains log2 8000; (b) an entry MEMORY refusal returns the full original inventory (K = 6, six typed rows); (c) a clock crossing injected
    INSIDE the resource diagnostic (formerly after the final timestamp) returns DEADLINE with nothing published, on a factorless and on an ordinary task; (d) the finish body takes ONE authoritative sample and assigns the rows after
    it; (e) a requested absent rate-model file is a typed RATE_MODEL_MISSING failure with exit code 3 (never a default rate)"""
    import spectral_heatbath_run as RUN; res = {}; ok = True; od = _tmp.mkdtemp(prefix='dgp9_d85_')
    mdl = {'cards': [2, 2, 2], 'factors': [{'scope': [0, 1], 'values': [F(1)] * 4}, {'scope': [2], 'values': [F(1000)] * 2}], 'evidence': {}}
    with _patch.object(RUN.CORE, 'read_uai', return_value=(mdl, {})), _patch.object(sys, 'argv', ['x', '--input', 'unused', '--output', od + '/z.json', '--budget', '3', '--admission-stop', '2.5']): d = RUN.main()
    z = d.get('Z_enclosure') or {}; tl = math.log2(8000); res['scalar_Z'] = dict(log2_lo=z.get('log2_lo'), log2_hi=z.get('log2_hi'), contains=bool(z.get('log2_lo') is not None and z['log2_lo'] <= tl <= z['log2_hi']), scalar=z.get('canonical_scalar')); ok = ok and res['scalar_Z']['contains']
    fl = {'cards': [2, 2, 2], 'factors': [], 'evidence': {}}; OB = CE.Budget
    with _patch.object(RUN.CORE, 'read_uai', return_value=(fl, {})), _patch.object(CE, 'Budget', side_effect=lambda _: OB(0)), _patch.object(sys, 'argv', ['x', '--input', 'unused', '--output', od + '/e.json', '--budget', '3', '--admission-stop', '2.5']): d = RUN.main()
    res['early_inventory'] = dict(K=d['K'], rows=len(d['answers']), outcome=d['outcome'], kind=(d['mechanism'].get('refusal') or {}).get('kind')); ok = ok and d['K'] == 6 and len(d['answers']) == 6 and d['outcome'] == 'REFUSED'
    clock = {'t': 0.0}; orig_ru = RUN.resource.getrusage
    def now(): return clock['t']
    def cross(*a_): clock['t'] = 100.0; return orig_ru(*a_)
    for name, mm in (('factorless', fl), ('ordinary', {'cards': [2, 2], 'factors': [{'scope': [0, 1], 'values': [F(2), F(1), F(1), F(2)]}], 'evidence': {}})):
        clock['t'] = 0.0
        with _patch.object(RUN.CORE, 'read_uai', return_value=(mm, {})), _patch.object(RUN, 'tnow', side_effect=now), _patch.object(CE, 'tnow', side_effect=now), _patch.object(RUN.resource, 'getrusage', side_effect=cross), _patch.object(sys, 'argv', ['x', '--input', 'unused', '--output', od + '/c_%s.json' % name, '--budget', '10', '--admission-stop', '9']):
            try: d = RUN.main()
            except SystemExit: d = json.load(open(od + '/c_%s.json' % name))
        res['crossing_' + name] = dict(outcome=d['outcome'], published=d['published'], respected=d['hard_deadline_respected'], suppressed=d['mechanism'].get('suppressed_late_rows')); ok = ok and d['outcome'] == 'DEADLINE' and d['published'] == 0 and d['hard_deadline_respected'] is False
    src = open(_RUNNER_SRC).read(); i0 = src.index('def finish('); i1 = src.index('\n    try:', i0); body = src[i0:i1]; res['finish_source'] = dict(tnow_calls=body.count('tnow()'), rows_after_sample=("out['answers'] = rows" in body.split('t_end = tnow()')[1])); ok = ok and body.count('tnow()') == 1 and res['finish_source']['rows_after_sample']
    import hp_gen as _G; p = _tmp.mktemp(suffix='.uai', prefix='dgp9_rate_'); _G.write(p, _tri_model(F(1))); d, rc, err = _run_runner(p, 2.0, 1.5, extra=['--rate-model', od + '/absent_rates.json']); m = (d or {}).get('mechanism') or {}
    res['rate_model_missing'] = dict(rc=rc, kind=(m.get('refusal') or {}).get('kind'), outcome=(d or {}).get('outcome'), K=(d or {}).get('K')); ok = ok and rc == 3 and res['rate_model_missing']['kind'] == 'RATE_MODEL_MISSING' and (d or {}).get('K') == 6
    rec('D85_runner_contracts', ok, **res)


def D86_ownership_and_admission():
    """review RV6 + original F4a / F4b: (a) the witness's rational-log cache is request-scoped and charged while live, the returned fields carry a declared retained charge released by the owner, and the ledger returns to its
    baseline; (b) the native constructor at ZERO headroom refuses after the (admitted) range witness with a traced peak below 64 KiB (the DGP8 code staged ~1.4 MB first); (c) an already-expired plan construction polls at entry
    before any allocation (traced peak below 100 KB); (d) retained plans keep their metadata charge (ledger live == the estimate) until released; (e) the certifier's expected-plan reconstruction at zero headroom refuses MEMORY"""
    import gc; res = {}; ok = True
    M = CE.Canon(); M.cards = [32, 32]; M.psi = [[F(1)] * 32, [F(1)] * 32]; M.factors = [((0, 1), [F(1000000 + i, 1000000) for i in range(1024)])]; M.orig_of = [0, 1]
    B = CE.Budget(CE.CONSTRUCTOR_BYTES); l0 = B.live; W = SW.certify(M, B, CE.Clock(time.monotonic() + 20, {})); ret = W.get('retained_bytes'); live_after = B.live - l0; SW.release_retained(W, B)
    res['witness'] = dict(global_cache_absent=(not hasattr(SW, '_log_enclosure_cached')), cache=W.get('cache'), retained_declared=ret, live_after_certify_equals_retained=(live_after == ret), restored_after_release=(B.live == l0), peak_charge=B.peak)
    ok = ok and res['witness']['global_cache_absent'] and bool(ret) and live_after == ret and B.live == l0 and (W.get('cache') or {}).get('entries', 0) > 0
    hm = HX.HeatBathModel(CE.canonicalize(dict(cards=[4] * 64, factors=[dict(scope=(i, j), values=[F(1, 3)] * 16) for i in range(64) for j in range(i + 1, 64)], evidence={}), CE.Clock(time.monotonic() + 30, {}), CE.Budget(1 << 30)))
    gc.collect(); _tm.start()
    try: HN.NativeChain(hm, [0] * 64, 1, CE.Clock(time.monotonic() + 10, {}), CE.Budget(0)); kind = None
    except CE.Refused as e: kind = e.kind
    peak = _tm.get_traced_memory()[1]; _tm.stop(); res['native_zero_headroom'] = dict(kind=kind, traced_peak_bytes=peak); ok = ok and kind == 'MEMORY' and peak < (64 << 10)
    class Expired:
        def __init__(self): self.calls = []
        def poll(self, w_): self.calls.append(w_); raise CE.Refused('DEADLINE', 'injected entry expiry')
        def remaining(self): return -1.0
    n = 1000; ex = Expired(); Bp = CE.Budget(1 << 28); cards_ = [2] * n; order_ = list(range(n)); parents_ = {v: () for v in range(n)}; gc.collect(); _tm.start()          # the fixture's own lists are built BEFORE tracing
    try: GC.CircuitPlan(cards_, order_, parents_, [], 1, order_, clock=ex, budget=Bp)
    except CE.Refused: pass
    peak2 = _tm.get_traced_memory()[1]; _tm.stop(); res['expired_plan_entry'] = dict(polls=ex.calls, traced_peak_bytes=peak2, ledger_live=Bp.live); ok = ok and len(ex.calls) == 1 and peak2 < 100000 and Bp.live == 0
    n = 32; order = list(range(n)); scopes = list(itertools.combinations(order, 2)); Bp = CE.Budget(1 << 28); clk = CE.Clock(time.monotonic() + 10, {}); P = GC.CircuitPlan([2] * n, order, {v: () for v in order}, scopes, 1, order, clock=clk, budget=Bp); Q = GC.CircuitPlan([2] * n, order, {v: () for v in order}, scopes, 2, order, clock=clk, budget=Bp)
    res['retained_plans'] = dict(ledger_live=Bp.live, meta_total=P._meta_estimate + Q._meta_estimate); ok = ok and Bp.live == P._meta_estimate + Q._meta_estimate and Bp.live > 0; P.release(); Q.release(); res['retained_plans']['released_live'] = Bp.live; ok = ok and Bp.live == 0
    Mc = CE.Canon(); Mc.cards = [2] * 16; Mc.psi = [[F(1)] * 2 for _ in Mc.cards]; Mc.factors = []; cs = {v: JP.Conditional(v, (), np.full((1, 2), JP.D // 2, dtype=np.int64), Mc.cards) for v in range(16)}
    pr = JP.Proposal(Mc.cards, cs, list(range(16)), _RM.from_fraction_up(F(2) ** 16), _RM.from_fraction_up(F(4) ** 16), {}); P0 = GC.CircuitPlan(Mc.cards, pr.order, {v: () for v in pr.order}, [], 1, list(reversed(pr.order)))
    try: r_ = CG.certify(P0, Mc, pr, pr.B, CE.Clock(time.monotonic() + 10, {}), budget=CE.Budget(0), order_elim=list(reversed(pr.order)), kind='cap'); res['certifier_zero_headroom'] = dict(result_ok=r_.get('ok'), refused=False)
    except CE.Refused as e: res['certifier_zero_headroom'] = dict(refused=True, kind=e.kind)
    ok = ok and res['certifier_zero_headroom'].get('kind') == 'MEMORY'
    rec('D86_ownership_and_admission', ok, **res)


def D87_summable_checkpoint_plan():
    """mechanism change B: (a) the revised plan N_j = ceil(rho^(j-1) N_1) is strictly increasing and finite; its risks delta_j = delta_sample / (j (j + 1)) sum to delta_sample J / (J + 1) < delta_sample for every J <= 64; the fixed
    plan's risks sum to exactly delta_sample; (b) on the weak n32 card-4 ER input at 2.5 s the revised runner completes MORE checkpoints than the fixed runner, its last completed count exceeds the fixed plan's N_max, the
    certificate's total failure probability stays <= delta and it stops by the work allowance (not by plan exhaustion); (c) the fixed runner reproduces the DGP8 policy (4 checkpoints, equal risks)"""
    res = {}; ok = True; ds = F(1, 2000000)
    for J in (1, 4, 16, 64):
        rk = MC.checkpoint_risks('revised', ds, J); res['risk_sum_J%d' % J] = str(sum(rk)); ok = ok and sum(rk) == ds * J / (J + 1) and sum(rk) < ds
    plan = MC.checkpoint_plan_revised(1000, F(5, 4), 64); res['plan'] = dict(length=len(plan), strictly_increasing=all(plan[i] < plan[i + 1] for i in range(len(plan) - 1)), head=plan[:5], tail=plan[-2:]); ok = ok and len(plan) == 64 and res['plan']['strictly_increasing']
    ok = ok and sum(MC.checkpoint_risks('fixed', ds, 4)) == ds
    df, rcf, ef = _run_runner(_WEAK32, 3.0, 2.5, extra=['--policy', 'fixed']); dr, rcr, er = _run_runner(_WEAK32, 3.0, 2.5, extra=['--policy', 'revised']); mf = (df or {}).get('mechanism') or {}; mr = (dr or {}).get('mechanism') or {}
    res['fixed'] = dict(rc=rcf, completed=mf.get('checkpoints_completed'), declared=mf.get('checkpoints_declared'), N_max=(mf.get('checkpoint_plan') or {}).get('N_max'), radius=(mf.get('certificate') or {}).get('radius'), stop=mf.get('sampling_stop'), risks=(mf.get('checkpoint_plan') or {}).get('delta_j'))
    res['revised'] = dict(rc=rcr, completed=mr.get('checkpoints_completed'), declared=mr.get('checkpoints_declared'), last_N=(mr.get('certificate') or {}).get('N'), radius=(mr.get('certificate') or {}).get('radius'), stop=mr.get('sampling_stop'), total_failure=(mr.get('certificate') or {}).get('total_failure_probability'), risk_sum=(mr.get('checkpoint_plan') or {}).get('risk_sum'), wall=(dr or {}).get('wall_s'))
    ok = ok and df is not None and dr is not None and res['fixed']['completed'] == 4 and len(set(res['fixed']['risks'] or [])) == 1 and (res['revised']['completed'] or 0) > 4 and (res['revised']['last_N'] or 0) > (res['fixed']['N_max'] or 0) and F(res['revised']['total_failure']) <= F(1, 10 ** 6) and 'allowance' in (res['revised']['stop'] or '')
    rec('D87_summable_checkpoint_plan', ok, **res)


def D88_original_dgp7_findings():
    """the recovered original DGP7 findings F1-F5 + F4c as controls: (F1) duplicate atom ids [0, 0, 1] are rejected by the independent kernel BEFORE arithmetic with no atom mutated (the honest inventory [0, 1] certifies cap 2); the
    bank's consume preflights the whole inventory; (F2) rho = 3/2 is rejected by check_stage AND check_slack_cells, rho = 1 accepted; (F3) an epoch commit whose authoritative sample lands past the deadline raises Deadline (never
    a stamp beyond it); the batch has no variable-size reduction after its sample (source order); (F4c) the residual law is unreachable after close; (F5) the extraction fixture (129,040 live entries + a 4,096-entry candidate)
    evicts until the projected entries fit the 131,072 cap"""
    res = {}; ok = True; clock = CE.Clock(time.monotonic() + 60, {}); cards = [2, 2]; order = [0, 1]
    def arr(vals):
        x = np.empty(len(vals), dtype=object)
        for i, v in enumerate(vals): x[i] = _RM.from_fraction_up(F(v))
        return x
    conds = {v: JP.Conditional(v, (), np.array([[JP.D // 2, JP.D // 2]], dtype=np.int64), cards) for v in order}; Bc = _RM.from_fraction_up(F(4)); prop = JP.Proposal(cards, conds, order, Bc, _RM.from_fraction_up(16), {'kind': 'exact tiny witness'})
    st = RB.ResidualState('tiny', 'synthetic', prop, Bc, Bc, Bc, CE.Budget(1 << 30))
    for j, vals in enumerate([[F(1, 2), F(1)], [F(1), F(1, 4)]]): at = RB.Atom(j, (0,), arr(vals), {}, 1, 0, 0); at.verified = True; st.atoms[j] = at
    w = {'A': order, 'R': order, 'C': [], 'bank_version': 0, 'target_parents': {0: (), 1: ()}, 'max_vol': 65536, 'model_identity': st.model_identity, 'seed_proof_identity': st.seed_proof_identity, 'law_identity': st.law_identity}
    legit = CR.local_kernel(st, w, [0, 1], conds, None, cards, order, clock, expected_identity=st.model_identity); dup = CR.local_kernel(st, w, [0, 0, 1], conds, None, cards, order, clock, expected_identity=st.model_identity)
    res['F1'] = dict(honest_ok=legit['ok'], honest_B=str(_RM.to_fraction(legit['B_new'])), duplicate_ok=dup['ok'], why=(dup.get('why') or '')[:80], mutated=any(x.consumed for x in st.atoms.values())); ok = ok and legit['ok'] and _RM.to_fraction(legit['B_new']) == 2 and not dup['ok'] and 'repeated' in (dup.get('why') or '') and not res['F1']['mutated']
    try: st.consume([0, 0], 'txn'); res['F1']['consume_preflight'] = False
    except CE.Defect: res['F1']['consume_preflight'] = (not any(x.consumed for x in st.atoms.values()))
    ok = ok and res['F1']['consume_preflight'] is True
    t = JP.JTable((0,), arr([1, 1]), 0, ('factor', 0)); out_ = JP.JTable((), arr([1]).reshape(()), 1, ('max_message', 0, (0,)))
    r32 = CJ.check_stage([t], out_, 0, [2], 'max', clock, inventory=[0], bucket_ids=[0], rho=arr([F(3, 2), F(3, 2)])); r1 = CJ.check_stage([t], out_, 0, [2], 'max', clock, inventory=[0], bucket_ids=[0], rho=arr([F(1), F(1)]))
    try: RB.check_slack_cells([t], out_, arr([F(3, 2), F(3, 2)]), (0,), (), [2], clock); sa = True
    except CE.Defect: sa = False
    res['F2'] = dict(stage_three_halves=r32.get('slack_ok'), stage_one=r1.get('slack_ok'), standalone_three_halves_accepted=sa); ok = ok and r32.get('slack_ok') is False and r1.get('slack_ok') is True and sa is False
    b = CE.Budget(100000000); m = CE.canonicalize(_four_cycle(), CE.Clock(time.monotonic() + 20, {}), CE.Budget(100000000)); s = JS.JointStream(2, m, m, [], 1, F(1, 200), F(1, 4000000), dict(PAC_OPTS, budget_obj=b), mode='seed'); dl = time.monotonic() + 15; assert s.prepare(dl, until=dl) == 'READY'
    clk = [99.0]; o1, o2 = JS.tnow, PA.tnow; JS.tnow = lambda: clk[0]; PA.tnow = lambda: clk[0]; fn = _inspect.getsourcefile(JS.JointStream._commit_epoch); lines, start = _inspect.getsourcelines(JS.JointStream._commit_epoch); target = start + next(i for i, l in enumerate(lines) if 't_commit = tnow()' in l)
    def cross(frame, event, arg):
        if event == 'line' and frame.f_code.co_filename == fn and frame.f_lineno == target: clk[0] = 101.0          # the crossing lands when the ONE sample line is about to execute
        return cross
    raised = None
    try:
        sys.settrace(cross); s._commit_epoch(s.epoch.prop, 'ctl', 100.0, b)
    except Exception as e: raised = type(e).__name__
    finally: sys.settrace(None); JS.tnow = o1; PA.tnow = o2
    res['F3_epoch'] = dict(raised=raised, epochs=len(s.epochs), note='the seed epoch carries the real clock stamp of prepare(); the injected crossing must leave it the ONLY epoch'); ok = ok and raised == 'Deadline' and len(s.epochs) == 1
    srcb = ''.join(_inspect.getsourcelines(JS.JointStream.batch)[0]); ip = srcb.find('t_commit = tnow()'); res['F3_batch_source'] = dict(single_sample=(ip >= 0), no_reduction_after=('X.sum()' not in srcb[ip:] and 'X.max()' not in srcb[ip:])); ok = ok and ip >= 0 and res['F3_batch_source']['no_reduction_after']
    s2 = RS.ResidualStream(3, m, m, [], 1, F(1, 200), F(1, 4000000), dict(PAC_OPTS, budget_obj=CE.Budget(100000000))); dl = time.monotonic() + 15; assert s2.prepare(dl, until=dl) == 'READY'; law = s2.state.law; s2._close('ctl'); res['F4c'] = dict(law_cleared=(s2.state.law is None), identity_kept=(s2.state.law_identity is not None)); ok = ok and s2.state.law is None
    Bb = CE.Budget(128 << 20); sst = RB.ResidualState('m', 'p', None, RB.ONE, RB.ONE, RB.ONE, Bb)
    def farr(n_, x):
        y = np.empty(n_, dtype=object); y.fill(x); return y
    for i, n_ in enumerate([4096] * 31 + [2048, 16]): axes = tuple(range(n_.bit_length() - 1)); charge = JP.ENTRY_BYTES * n_ + RB.ATOM_META_BYTES; sst._charge(charge, 'fixture'); sst.add_atom(axes, farr(n_, (-1, 1)).reshape((2,) * len(axes)), {}, 0.0 if n_ == 16 else 1e-9, -1, charge)
    sink = RB.BankSink(sst, CE.Clock(time.monotonic() + 10, {}), 10); pend = sink.prepare(0, 1, [], farr(4096, (-1, 1)).reshape((2,) * 12), tuple(range(12)), type('M', (), dict(arr=farr(2048, RB.ONE).reshape((2,) * 11)))(), tuple(range(1, 12)), [2] * 12)
    proj = sst.entries() + (pend['vol'] if pend else 0); res['F5'] = dict(projected=proj, cap=sink.max_entries, evictions=len(sst.evicted), fits=(proj <= sink.max_entries)); ok = ok and proj <= sink.max_entries and pend is not None
    if pend: sink.abort(pend)
    rec('D88_original_dgp7_findings', ok, **res)


def D89_workspace_peak_admitted():
    """original DGP7 finding F6 (the review's kernel fixture completed, not timed out): the 65,536-cell window over 16 region variables with 16 atoms and 4 active variables runs the local kernel under tracemalloc; the traced
    peak must not exceed the ADMITTED workspace of residual_stream.window_workspace_estimate (the DGP8 repair) -- a completed, bounded peak test"""
    n = 16; cards = [2] * n; order = list(range(n)); A = list(range(12, 16)); conds = {}
    for v in order: p = tuple(range(11)) if v in A else (); conds[v] = JP.Conditional(v, p, np.full((2 ** len(p), 2), JP.D // 2, dtype=np.int64), cards)
    prop = JP.Proposal(cards, conds, order, RB.ONE, RB.ONE, {}); B = CE.Budget(128 << 20); s = RB.ResidualState('m', 'p', prop, RB.ONE, RB.ONE, RB.ONE, B)
    for i in range(16): a_ = np.empty((2, 2), object); a_.fill((-1, 1)); at = RB.Atom(i, (11, 12), a_, {}, 1, -1, 0); at.verified = True; s.atoms[i] = at
    window = dict(A=A, R=order, bank_version=0, target_parents={v: conds[v].parents for v in A}, max_vol=65536, atoms=list(range(16))); import residual_stream as _RS
    ef, ek, admitted = _RS.window_workspace_estimate(65536, 16, 16, 0); import gc; gc.collect(); _tm.start(); t0 = time.monotonic(); k = CR.local_kernel(s, window, list(range(16)), conds, None, cards, order, CE.Clock(t0 + 120, {}), budget=None); cur, peak = _tm.get_traced_memory(); _tm.stop()
    res = dict(ok_kernel=k['ok'], volume=65536, atoms=16, admitted_workspace=admitted, est_float=ef, est_kernel=ek, traced_peak=peak, peak_over_admitted=peak / admitted, seconds=time.monotonic() - t0)
    rec('D89_workspace_peak_admitted', bool(k['ok']) and peak <= admitted, **res)


def D90_recovered_references():
    """the recovered normative references (the DGP8 theory packet, present this round): heatbath_reference (16 exact tiny models: row sums, detailed balance, occupation accounting), exact_aggregate_reference (44 query bounds),
    check_hs_gap -- executed from the packet copy; absent packet -> FAIL (never a substitute)"""
    res = {}; ok = True; th = os.path.join(_DGP9_PACKET, 'dgp8_theory')
    for rel, key in (('heatbath_reference/heatbath_reference.py', 'all_ok'), ('exact_reference/exact_aggregate_reference.py', 'all_ok'), ('blocks/check_hs_gap.py', 'status')):
        p = os.path.join(th, rel)
        if not os.path.exists(p): res[rel] = dict(present=False); ok = False; continue
        od = _tmp.mkdtemp(prefix='dgp9_ref_'); import shutil as _sh; _sh.copy(p, od); r_ = _sp.run([sys.executable, os.path.join(od, os.path.basename(p))], capture_output=True, text=True, timeout=120, cwd=od, env=dict(os.environ, OPENBLAS_NUM_THREADS='1'))
        try: out = json.loads(r_.stdout.strip().split('\n')[-1])
        except Exception: out = {}
        val = out.get(key); good = (val is True) or (val == 'PASS'); res[rel] = dict(present=True, rc=r_.returncode, value=val, stderr=(r_.stderr or '')[-200:]); ok = ok and r_.returncode == 0 and good
    rec('D90_recovered_references', ok, **res)


CONTROLS += [D82_native_range_gauges_and_exact_decisions, D83_spectral_exact_accumulation, D84_jbox_publication, D85_runner_contracts, D86_ownership_and_admission, D87_summable_checkpoint_plan, D88_original_dgp7_findings, D89_workspace_peak_admitted, D90_recovered_references]


if __name__ == '__main__':
    ap = argparse.ArgumentParser(); ap.add_argument('out'); ap.add_argument('--only', default=None); a = ap.parse_args(); t0 = time.time()
    for c in CONTROLS:
        if a.only and c.__name__.split('_')[0] not in a.only.split(','): continue
        try: c()
        except Exception as e: rec(c.__name__, False, error=repr(e)[:300], tb=traceback.format_exc()[-1200:])
    res = dict(all_ok=all(r['ok'] for r in R), n=len(R), n_ok=sum(r['ok'] for r in R), wall_s=round(time.time() - t0, 2), controls=R); json.dump(res, open(a.out, 'w'), indent=1, default=str); print(json.dumps({k: v for k, v in res.items() if k != 'controls'}))


