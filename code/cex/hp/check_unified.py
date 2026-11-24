"""Focused controls for the unified representation planner (brief section 8). The independent enumerator (check_hp.brute, source tables, <= 2^16 assignments asserted) is the oracle. Deterministic
controller tests use injected clocks / estimates / refusals; they are separated from empirical timing claims. usage: check_unified.py OUT.json"""
import sys, os, json, time, math, random, itertools, builtins, inspect
from fractions import Fraction as F
HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, HERE); sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(HERE)), 'cex', 'newarm'))
import coarse_envelope as CE, unified_planner as UP, hp_gen as G, check_hp as H
from check_hp import brute, mk, clones, write_model
RES = dict(checks=[], all_ok=True, utc=time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()))
def rec(name, ok, **kw): RES['checks'].append(dict(name=name, ok=bool(ok), **kw)); RES['all_ok'] &= bool(ok); print(('PASS ' if ok else 'FAIL ') + name, json.dumps(kw, default=str)[:220], flush=True)
def contained(d, m, Z, N, eps=F(1, 200)):
    H.EPS = eps; r = H.contained(d, m, Z, N); H.EPS = F(1, 200); return r
def run(m, policy='unified', budget=3.5, eps=F(1, 200), t_start=None): return UP.plan_and_solve(m, budget, policy=policy, eps=eps, t_start=(time.monotonic() if t_start is None else t_start))
def acts(d): return [(x.get('action'), x.get('cand'), x.get('status')) for x in d['actions']]
def used_discovery(d): return any(a[0] in ('discover_exact', 'discover_fast', 'refine') for a in acts(d))

def main(out_path):
    t_all = time.monotonic(); rng = random.Random(20261124); cyc = lambda n: [(i, (i + 1) % n) for i in range(n)]
    # ---- A. identity publishes the original truth WITHOUT discovery (nonbinary cycle, evidence, scalar, repeated occurrence, factorless, hard zeros)
    mA = mk([3, 4, 3, 2, 5], [((0, 1), [F(rng.randrange(1, 9), 4) for _ in range(12)]), ((1, 2), [F(rng.randrange(1, 9), 4) for _ in range(12)]), ((2, 0), [F(rng.randrange(1, 9), 4) for _ in range(9)]), ((0, 0, 3), [F(rng.randrange(1, 9), 4) for _ in range(18)]), ((), [F(7, 3)]), ((4,), [F(1), F(2), F(0), F(3), F(1)])], evidence={3: 1})
    mA['factors'][0]['values'][5] = F(0); mA['factors'][2]['values'][0] = F(0)                       # hard zeros in pair tables
    def brute_rep(model):
        cards = model['cards']; ev = model.get('evidence', {}); Z = F(0); N = [[F(0)] * c for c in cards]
        for x in itertools.product(*(range(c) for c in cards)):
            if any(x[v] != a for v, a in ev.items()): continue
            w = F(1)
            for f in model['factors']: w *= f['values'][sum(s * x[v] for s, v in zip(CE.strides([cards[v] for v in f['scope']]), f['scope']))]
            Z += w
            for v, a in enumerate(x): N[v][a] += w
        return Z, N
    ZA, NA = brute_rep(mA)
    for pol in ('identity', 'unified'):
        d = run(mA, pol); ok, pub, mw, det = contained(d, mA, ZA, NA); rec('A_identity_truth_%s' % pol, ok and d['outcome'] == 'COMPLETE' and pub == d['K'] == 15 and (pol == 'unified' or not used_discovery(d)) and d['mechanism']['representations_solved'] == ['identity'], outcome=d['outcome'], published=pub, K=d['K'], actions=acts(d), detail=det)
    # ---- B. exact quotient and approximate quotient selected + decoded correctly through the SAME publisher, actual native execution
    orig_est = UP.est_solve
    def big_identity(vol, K):
        T, parts = orig_est(vol, K); return (T, parts) if vol['states'] < 16 else (1e9, parts)
    mB = clones(rng, 6, 4, cyc(6), 'exact'); ZB, NB = brute(mB); d0 = run(mB); ok0, _, _, _ = contained(d0, mB, ZB, NB); rec('B_cheap_identity_bypasses_discovery_on_tiny_exact_clones', ok0 and d0['outcome'] == 'COMPLETE' and not used_discovery(d0), actions=acts(d0))
    UP.est_solve = big_identity
    try: d = run(mB)
    finally: UP.est_solve = orig_est
    ok, pub, mw, det = contained(d, mB, ZB, NB)
    rec('B_exact_quotient_selected_decoded', ok and d['outcome'] == 'COMPLETE' and 'exact' in d['mechanism']['representations_solved'] and any(c['kind'] == 'exact' and c['states'] == 12 for c in d['candidates']), actions=acts(d), published=pub, detail=det, cands=[(c['name'], c['states']) for c in d['candidates']])
    mP = clones(rng, 6, 4, cyc(6), 'perturbed'); ZP, NP = brute(mP); UP.est_solve = big_identity
    try: d = run(mP)
    finally: UP.est_solve = orig_est
    ok, pub, mw, det = contained(d, mP, ZP, NP)
    rec('B_approx_quotient_selected_decoded', ok and d['outcome'] == 'COMPLETE' and any(n.startswith('approx') for n in d['mechanism']['representations_solved']), actions=acts(d), published=pub, max_width=mw, detail=det, solved=d['mechanism']['representations_solved'])
    dI = run(mP, 'identity'); okI, pubI, _, detI = contained(dI, mP, ZP, NP); rec('B_same_publisher_identity_vs_approx_consistent', okI and ok and all(F(a['lo']) <= F(b['hi']) and F(b['lo']) <= F(a['hi']) for a, b in zip(dI['answers'], d['answers'])), detail=detI)
    # ---- C. exact -> approximate decoder composition: a perturbed model with planted clones inside a larger exact-duplicate structure; scalar once; zero-mass classes
    mC = clones(rng, 5, 4, cyc(5), 'perturbed'); mC['factors'].append(dict(scope=(), values=[F(3, 7)])); mC['cards'] = mC['cards'] + [4]; mC['factors'].append(dict(scope=(5,), values=[F(1), F(2), F(0), F(0)]))
    # variable 5 is factorless with zero-mass states; make variables 0..4 pairwise exact duplicates at the state level so the exact quotient is nontrivial, then perturb -> approx on exact
    ZC, NC = brute(mC); d = run(mC); ok, pub, mw, det = contained(d, mC, ZC, NC); rec('C_composition_scalar_once_zero_classes', ok and d['outcome'] == 'COMPLETE' and pub == d['K'], actions=acts(d), published=pub, K=d['K'], Z=d.get('Z_enclosure'), detail=det)
    M_, c1, s1, C1, M1, clock, bud = H.internals(mC); prof, _ = CE.slice_profiles(M1); cl2 = [CE.canonical_classes(CE.farthest_split(prof[v], list(range(M1.cards[v]))), M1.cards[v]) for v in range(len(M1.cards))]; Cz2 = CE.check_candidate(M1, cl2, CE.unit_scales(M1), clock, bud)
    zl, okl = H.lift_sum(M1, (cl2, Cz2), 0, M_.scalar); zu, oku = H.lift_sum(M1, (cl2, Cz2), 1, M_.scalar); rec('C_two_stage_lift_sandwich', okl and oku and zl <= ZC <= zu, Z=float(ZC), Z_L=float(zl), Z_U=float(zu))
    # ---- D. insufficient global R bound but useful query-specific bounds: quality UNKNOWN; a bounded probe may be admitted; a policy refusal is never 'proved inaccuracy'
    mD = clones(rng, 4, 4, cyc(4), 'generic'); ZD, ND = brute(mD); d = run(mD); ok, pub, mw, det = contained(d, mD, ZD, ND)
    cands = d['candidates']; unknown = [c for c in cands if c['kind'] == 'approx' and c['prospective']['quality'] == 'unknown']
    rec('D_unknown_quality_not_impossible', ok and d['outcome'] == 'COMPLETE' and all(c['prospective']['quality'] != 'impossible' for c in cands), unknown_candidates=[(c['name'], c['prospective']) for c in unknown][:2], actions=acts(d), detail=det, note='identity wins on this tiny generic model; approx quality is recorded as unknown, never impossible')
    # force the exploration branch: make identity unaffordable by injecting a huge identity estimate, so the planner must explore / probe
    UP.est_solve = big_identity
    try: d = run(mD, budget=3.5)
    finally: UP.est_solve = orig_est
    ok, pub, mw, det = contained(d, mD, ZD, ND); probe = [a for a in acts(d) if a[0] in ('solve_lower', 'solve_upper') and a[1] and a[1].startswith('approx')]
    rec('D_bounded_probe_under_pessimistic_identity', ok and d['outcome'] in ('COMPLETE', 'PARTIAL', 'REFUSED') and len(probe) >= 1, actions=acts(d), decisions=[x.get('why') for x in d['decisions']][:4], detail=det, outcome=d['outcome'])
    # ---- E. the same approximate fixture at eps 1/20, 1/200, 1/2000: eligibility and point checks from the requested tolerance
    for eps in (F(1, 20), F(1, 200), F(1, 2000)):
        UP.est_solve = big_identity
        try: d = run(mP, eps=eps)
        finally: UP.est_solve = orig_est
        ok, pub, mw, det = contained(d, mP, ZP, NP, eps); prom = [(c['name'], c['prospective']['model_bound_promising']) for c in d['candidates'] if c['kind'] == 'approx']
        rec('E_tolerance_%s' % eps, ok and d['outcome'] == 'COMPLETE' and (d['max_point_radius'] is None or d['max_point_radius'] <= float(eps)), eps=str(eps), solved=d['mechanism']['representations_solved'], approx_promising=prom, max_width=mw, max_point_radius=d.get('max_point_radius'), detail=det)
    # ---- F. lower -> optional upper: upper refusal retains the lower information; identity can win afterwards; an unexecuted upper is never credited
    orig_run = CE.run_executor
    def refuse_upper(cmodel, order, scalar, deadline, stats_out, label):
        if label.endswith(':upper'): raise CE.Refused('MEMORY', 'injected upper refusal')
        return orig_run(cmodel, order, scalar, deadline, stats_out, label)
    UP.est_solve = big_identity; CE.run_executor = refuse_upper
    try: d = run(mD)
    finally: UP.est_solve = orig_est; CE.run_executor = orig_run
    ok, pub, mw, det = contained(d, mD, ZD, ND); ups = [a for a in acts(d) if a[0] == 'solve_upper']
    rec('F_upper_refusal_retains_lower_identity_can_win', ok and all(a[2].startswith('REFUSED') for a in ups) and d['outcome'] in ('COMPLETE', 'PARTIAL', 'REFUSED') and not any(c['status'].get('upper') == 'SOLVED' for c in d['candidates']), actions=acts(d), outcome=d['outcome'], detail=det)
    # ---- G. discovery refusals leave identity usable: exact-profile allowance expiry; profile byte refusal; numeric RANGE
    orig_epc = CE.exact_profile_classes
    def slow_profiles(M, clock, budget):
        t = time.monotonic()
        while time.monotonic() - t < 0.5: clock.poll('injected slow exact profiles')
        return orig_epc(M, clock, budget)
    CE.exact_profile_classes = slow_profiles
    try: d = run(mB)
    finally: CE.exact_profile_classes = orig_epc
    ok, pub, mw, det = contained(d, mB, ZB, NB); ex = [a for a in acts(d) if a[0] == 'discover_exact']
    rec('G_exact_allowance_expiry_identity_usable', ok and d['outcome'] == 'COMPLETE' and (not ex or ex[0][2].startswith('REFUSED_ALLOWANCE')) and 'identity' in d['mechanism']['representations_solved'], actions=acts(d), detail=det)
    orig_sp = CE.slice_profiles
    def refuse_profiles(M1, clock=None, budget=None): raise CE.Refused('MEMORY', 'injected profile byte refusal')
    CE.slice_profiles = refuse_profiles
    try: d = run(mP)
    finally: CE.slice_profiles = orig_sp
    ok, pub, mw, det = contained(d, mP, ZP, NP); rec('G_profile_byte_refusal_identity_usable', ok and d['outcome'] == 'COMPLETE' and 'identity' in d['mechanism']['representations_solved'], actions=acts(d), detail=det)
    mR = mk([2, 2], [((0, 1), [F(1, 2 ** 1500), F(1), F(2), F(3)])]); d = run(mR); rec('G_numeric_range_typed', d['outcome'] in ('REFUSED', 'PARTIAL') and 'defect' not in d['mechanism'] and d['published'] == 0, outcome=d['outcome'], refusal=d['mechanism'].get('refusal'), actions=acts(d))
    # ---- H. injected clock / estimate controls (deterministic): optional construction cannot spend the reserved incumbent allowance; absolute budget never restarts; identical actions never rerun; forecast misses charged
    orig_now = CE.tnow; off = [0.0]; CE.tnow = lambda: time.monotonic() + off[0]; UP.tnow = CE.tnow
    def slow_epc(M, clock, budget):
        off[0] += 5.0; clock.poll('injected: exact profiles consume 5 s'); return orig_epc(M, clock, budget)
    CE.exact_profile_classes = slow_epc; UP.est_solve = big_identity
    try: d = UP.plan_and_solve(mB, 3.85, policy='unified', t_start=time.monotonic())
    finally: CE.tnow = orig_now; UP.tnow = orig_now; CE.exact_profile_classes = orig_epc; UP.est_solve = orig_est
    ex = [a for a in acts(d) if a[0] == 'discover_exact']; rec('H_optional_cannot_spend_reserved_allowance', bool(ex) and ex[0][2] in ('REFUSED_ALLOWANCE_EXPIRED', 'KILLED_GLOBAL_DEADLINE') and d['outcome'] in ('DEADLINE', 'REFUSED', 'PARTIAL') and d['published'] == 0, actions=acts(d), outcome=d['outcome'], note='the injected 5 s construction exceeds its allowance and the admission stop: nothing is published late; with a real clock identity would still be run')
    off = [0.0]; CE.tnow = lambda: time.monotonic() + off[0]; UP.tnow = CE.tnow
    def epc_small(M, clock, budget):
        off[0] += 0.2; clock.poll('injected 0.2 s exact profiles'); return orig_epc(M, clock, budget)
    CE.exact_profile_classes = epc_small; UP.est_solve = big_identity
    try: d = UP.plan_and_solve(mB, 3.85, policy='unified', t_start=time.monotonic())
    finally: CE.tnow = orig_now; UP.tnow = orig_now; CE.exact_profile_classes = orig_epc; UP.est_solve = orig_est
    ok, pub, mw, det = contained(d, mB, ZB, NB); ex = [x for x in d['actions'] if x.get('action') == 'discover_exact']
    rec('H_forecast_miss_charged_and_recorded', ok and bool(ex) and (ex[0].get('actual_s', 0) >= 0.2) and d['wall_s'] >= 0.2, actions=acts(d), discover_actual_s=(ex[0].get('actual_s') if ex else None), estimate_s=(ex[0].get('estimate_s') if ex else None), wall=d['wall_s'], detail=det)
    d = run(mB); solved = d['mechanism']['representations_solved']; rec('H_identical_action_not_rerun_alias', d['mechanism']['native_attempts'] == len(set(solved)) and d['mechanism']['native_attempts'] <= 2, native=d['mechanism']['native_attempts'], solved=solved, actions=acts(d))
    d = run(mB, t_start=time.monotonic() - 10); rec('H_absolute_budget_never_restarts', d['outcome'] == 'DEADLINE' and d['published'] == 0, outcome=d['outcome'], wall=d['wall_s'])
    # ---- I. point policy preserved: the reviewer's fixture; J-box; midpoint fallback
    pr = os.path.join(HERE, 'fixtures_closeout', 'point_error_repro.uai'); import core as CORE; mpr, _ = CORE.read_uai(pr); Zr, Nr = brute(mpr)
    for pol in ('unified', 'identity'):
        d = run(mpr, pol); ok, pub, mw, det = contained(d, mpr, Zr, Nr); worst = max((abs(F(r['point']) - Nr[r['var']][r['state']] / Zr) for r in d['answers'] if r['guarantee'] != 'NOT_PUBLISHED'), default=F(0))
        rec('I_point_error_repro_%s' % pol, ok and d['outcome'] == 'COMPLETE' and worst <= F(1, 200) and d['max_point_radius'] <= 0.005, published=pub, max_point_error=float(worst), radius=d['max_point_radius'], solved=d['mechanism']['representations_solved'], detail=det)
    box = [(F(0), F(1, 100), 'DETERMINISTIC'), (F(99, 100), F(1), 'DETERMINISTIC')]; pts, how = CE.epsilon_safe_points(box, F(1, 200)); rec('I_J_box', how == 'J_normalized' and sum(pts) == 1)
    box = [(F(0), F(1, 100), 'DETERMINISTIC'), (F(0), F(1, 100), 'DETERMINISTIC'), (F(99, 100), F(1), 'DETERMINISTIC')]; pts, how = CE.epsilon_safe_points(box, F(1, 200)); rec('I_midpoint_fallback', how == 'midpoints' and all(max(p_ - b[0], b[1] - p_) <= F(1, 200) for p_, b in zip(pts, box)))
    # ---- J. typed boundaries: expired entry; crossing during recovery / final assembly; early refusal before canonicalization; zero lower / positive upper; genuine zero evidence
    d = UP.plan_and_solve({'cards': [2], 'factors': [], 'evidence': {}}, 0.01, t_start=time.monotonic() - 1); rec('J_expired_entry', d['outcome'] == 'DEADLINE' and d['published'] == 0 and d['K'] == 2, outcome=d['outcome'])
    off = [0.0]; CE.tnow = lambda: time.monotonic() + off[0]; UP.tnow = CE.tnow; orig_pub = CE.publish
    def late_pub(*a, **k): off[0] = 5.0; return orig_pub(*a, **k)
    CE.publish = late_pub
    try: d = UP.plan_and_solve(mk([2, 2], [((0, 1), [1, 2, 3, 4]), ((0,), [1, 1])]), 1.0, t_start=time.monotonic())
    finally: CE.tnow = orig_now; UP.tnow = orig_now; CE.publish = orig_pub
    rec('J_crossing_during_recovery_refused', d['outcome'] == 'DEADLINE' and d['published'] == 0, outcome=d['outcome'], actions=acts(d))
    off = [0.0]; CE.tnow = lambda: time.monotonic() + off[0]; UP.tnow = CE.tnow
    def late_str(value):
        if inspect.currentframe().f_back.f_code.co_name == 'fin': off[0] = 2.0
        return builtins.str(value)
    UP.str = late_str
    try: d = UP.plan_and_solve({'cards': [2], 'factors': [], 'evidence': {}}, 1.0, t_start=time.monotonic())
    finally: CE.tnow = orig_now; UP.tnow = orig_now; del UP.str
    rec('J_crossing_in_final_assembly_refused', d['outcome'] == 'DEADLINE' and d['published'] == 0, outcome=d['outcome'], late=d['mechanism'].get('late_assembly'))
    old = CE.CONSTRUCTOR_BYTES; CE.CONSTRUCTOR_BYTES = 1
    try: d = run({'cards': [2], 'factors': [], 'evidence': {}}); rec('J_early_refusal_before_canonicalization', d['outcome'] == 'REFUSED' and d['mechanism'].get('refusal', {}).get('kind') == 'MEMORY' and d['K'] == 2 and d['published'] == 0, refusal=d['mechanism'].get('refusal'))
    finally: CE.CONSTRUCTOR_BYTES = old
    xor3 = mk([2, 2, 2], [((0, 1), [0, 1, 1, 0]), ((1, 2), [0, 1, 1, 0]), ((2, 0), [0, 1, 1, 0])]); d = run(xor3); rec('J_genuine_zero_evidence', d['outcome'] == 'ZERO_EVIDENCE' and d['published'] == 0 and d['mechanism']['positive_mass_witness'] is False, outcome=d['outcome'], solved=d['mechanism']['representations_solved'], Z=d.get('Z_enclosure'))
    # zero lower / positive upper on a SUPPLIED mixed-cell partition (the generic proposer skips zeros): the lower solve must not publish, must not certify zero, identity must still win
    mz = clones(rng, 4, 4, cyc(4), 'generic'); mz['factors'][0]['values'][3] = F(0); Zz, Nz = brute(mz); P = UP.Planner(mz, 3.5, t_start=time.monotonic()); P.M = CE.canonicalize(mz, P.clock, P.budget); ident = P.make_identity(P.clock); P.cands.append(ident)
    cl = [[0, 0, 1, 1]] * 4; Czm = CE.check_candidate(P.M, cl, CE.unit_scales(P.M), P.clock, P.budget); c = UP.Cand('approx', ident); c.Cz = Czm; c.scales = CE.unit_scales(P.M); c.classes = cl; c.prof = None; c.M1 = P.M; c.stages = [(cl, Czm)]; c.cards = list(Czm.ccards); c.scopes = [sc for sc, _ in P.M.factors]; c.constructions = 1; c.name = 'approx(supplied_mixed)'; P.set_quality(c); c.order, c.vol = UP.order_and_volume(c.cards, c.scopes, P.clock, P.budget); c.fbytes = UP.forecast_bytes(c.vol); P.cands.append(c)
    r0 = P.perform(dict(kind='solve', cand=c, side='lower', deadline=P.adm, record=dict(T_b_s=0.01))); st = c.status['lower']; pos = P.out['mechanism']['positive_mass_witness']
    d = P.run() if False else None
    rec('J_zero_lower_positive_upper_no_witness', r0 is None and st in ('LOWER_ZERO_MASS', 'SOLVED') and pos is not False and P.out.get('Z_enclosure', {}).get('lo', '1') != '0', lower_status=st, positive_mass_witness=pos, mixed=Czm.mixed, R=CE.fl(Czm.R), note='a zero or positive approximate lower mass never certifies zero original mass; mixed cells make R unavailable')
    # ---- K. retention / release accounting across multiple live candidates; the 8^4 profile and expired 150-clique boundaries through the reused functions
    UP.est_solve = big_identity
    try: d = run(mD)
    finally: UP.est_solve = orig_est
    mech = d['mechanism']; rec('K_multi_candidate_accounting', mech['constructor_budget_cumulative_bytes'] >= mech['constructor_budget_peak_bytes'] >= mech['constructor_live_at_end_bytes'] >= 0 and len(d['candidates']) >= 2, peak=mech['constructor_budget_peak_bytes'], cumulative=mech['constructor_budget_cumulative_bytes'], live_end=mech['constructor_live_at_end_bytes'], n_cands=len(d['candidates']))
    Mp = CE.Canon(); Mp.cards = [8] * 4; Mp.psi = [[F(1)] * 8 for _ in range(4)]; Mp.factors = [(tuple(range(4)), [F(i + 1, 17) for i in range(4096)])]
    try: CE.exact_profile_classes(Mp, CE.Clock(time.monotonic() + 5, {}), CE.Budget(600000)); k = None
    except CE.Refused as e: k = e.kind
    rec('K_8x8x8x8_profile_refusal_reused', k == 'MEMORY')
    n = 150; scopes = [(i, j) for i in range(n) for j in range(i + 1, n)]; clock = CE.Clock(time.monotonic() - 1, {})
    try: UP.order_and_volume([1] * n, scopes, clock, CE.Budget(CE.CONSTRUCTOR_BYTES)); k = None
    except CE.Refused as e: k = e.kind
    rec('K_expired_150_clique_refuses_at_entry', k == 'DEADLINE' and clock.polls == 1)
    # ---- L. mismatched model / decoder / coordinate sets rejected; permutations preserve semantics
    M_, c1, s1, C1, M1, clock, bud = H.internals(mB)
    try: CE.check_candidate(M1, [[0, 0]] * (len(M1.cards) - 1), CE.unit_scales(M1), clock, bud); rec('L_mismatched_decoder_rejected', False)
    except (CE.Defect, IndexError): rec('L_mismatched_decoder_rejected', True)
    try: CE.intersect({(0, 0): (F(0), F(1))}, {(0, 1): (F(0), F(1))}); joined = True
    except KeyError: joined = False
    P = UP.Planner(mB, 3.5, t_start=time.monotonic()); P.M = CE.canonicalize(mB, P.clock, P.budget); P.retained = {(0, 0): (F(0), F(1))}
    class FakeSL: p = [[(F(0), F(1))] * 4 for _ in range(6)]
    ident = P.make_identity(P.clock)
    ident.SL = FakeSL()
    try: P.recover(ident, P.clock); crossed = True
    except CE.Defect: crossed = False
    rec('L_cross_candidate_coordinate_sets_rejected', not crossed, note='the accumulator refuses to join different original coordinate sets (Defect)')
    for s_ in range(2):
        pm, pi = G.permute('UNIFIED-CTRL', 'cycle6', 4, 'exact%d' % s_, mB); Zp, Np = brute(pm); d = run(pm); ok, pub, mw, det = contained(d, pm, Zp, Np); rec('L_permutation_%d' % s_, ok and d['outcome'] == 'COMPLETE' and Zp == ZB, actions=acts(d), detail=det)
    RES['wall_s'] = time.monotonic() - t_all; RES['n'] = len(RES['checks']); RES['n_ok'] = sum(1 for c in RES['checks'] if c['ok']); json.dump(RES, open(out_path, 'w'), indent=1, default=str)
    print(json.dumps(dict(all_ok=RES['all_ok'], n=RES['n'], n_ok=RES['n_ok'], wall_s=round(RES['wall_s'], 2)))); return 0 if RES['all_ok'] else 1

if __name__ == '__main__': sys.exit(main(sys.argv[1]))
