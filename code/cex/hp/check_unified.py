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
    def two_level(n, edges):
        lat4 = [a // 2 for a in range(8)]; lat2 = [k // 2 for k in range(4)]; facs = []
        for (u, v) in edges:
            while True:
                T = [rng.randrange(1, 10) for _ in range(4)]
                if T[0] * T[3] - T[1] * T[2] != 0: break
            su = [F(2) ** rng.randrange(-2, 3) for _ in range(8)]; sv = [F(2) ** rng.randrange(-2, 3) for _ in range(8)]; pert = {(k, l): 1 + F(rng.choice((-1, 1)), 16384) for k in range(4) for l in range(4)}; vals = []
            for a in range(8):
                for b in range(8): vals.append(F(T[2 * lat2[lat4[a]] + lat2[lat4[b]]]) * pert[(lat4[a], lat4[b])] * su[a] * sv[b])
            facs.append(((u, v), vals))
        for v in range(n): facs.append(((v,), [F(rng.randrange(1, 10), 8) for _ in range(8)]))
        facs.append(((), [F(3, 7)]))
        return mk([8] * n, facs)
    mC = two_level(4, cyc(4)); mC['cards'] = mC['cards'] + [4]; mC['factors'].append(dict(scope=(4,), values=[F(1), F(2), F(0), F(0)]))     # + a factorless variable with zero-mass states
    ZC, NC = brute(mC)
    def exact_and_identity_pricey(vol, K):
        T, parts = orig_est(vol, K); return (T, parts) if vol['states'] <= 2 * 4 else (1e9, parts)                                       # only the 2-state approx (<= 8 states over 4 variables) is affordable
    UP.est_solve = exact_and_identity_pricey
    try: d = run(mC)
    finally: UP.est_solve = orig_est
    ok, pub, mw, det = contained(d, mC, ZC, NC); ex = [c for c in d['candidates'] if c['kind'] == 'exact']; ap = [c for c in d['candidates'] if c['kind'] == 'approx']; solved = d['mechanism']['representations_solved']
    rec('C_composition_exact_then_approx_native', ok and d['outcome'] == 'COMPLETE' and pub == d['K'] and bool(ex) and ex[0]['states'] == 16 and bool(ap) and ap[0]['name'].startswith('approx(exact') and all(n_.startswith('approx(exact') for n_ in solved) and len(solved) >= 1, actions=acts(d), published=pub, K=d['K'], exact_states=(ex[0]['states'] if ex else None), approx_states=(ap[0]['states'] if ap else None), solved=solved, Z=d.get('Z_enclosure'), detail=det, note='8 -> 4 exact (2 clones per class) -> 2 approx; the factorless zero-mass states publish EXACT 0 through the fixed-row map; the scalar 3/7 enters once')
    d0 = run(mC); ok0, pub0, _, det0 = contained(d0, mC, ZC, NC); rec('C_composition_plain_run_sound', ok0 and d0['outcome'] == 'COMPLETE', solved=d0['mechanism']['representations_solved'], detail=det0)
    M_, c1, s1, C1, M1, clock, bud = H.internals(mC); rec('C_exact_stage_reduces_8_to_4', all(k == 4 for k in C1.ccards[:4]) and C1.exact, ccards=C1.ccards); prof, _ = CE.slice_profiles(M1); cl2 = [CE.canonical_classes(CE.farthest_split(prof[v], list(range(M1.cards[v]))), M1.cards[v]) for v in range(len(M1.cards))]; Cz2 = CE.check_candidate(M1, cl2, CE.unit_scales(M1), clock, bud)
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
    mQ = clones(rng, 3, 4, cyc(3), 'generic'); mQ['factors'][3]['values'] = [F(1), F(1), F(1), F(1, 10 ** 6)]           # variable 0 state 3 has tiny unary weight -> tiny posterior
    ZQ, NQ = brute(mQ); P = UP.Planner(mQ, 3.5, t_start=time.monotonic()); P.M = CE.canonicalize(mQ, P.clock, P.budget); P.canonical_charge = P.budget.live; ident = P.make_identity(P.clock); P.cands.append(ident)
    cl = [[0, 0, 1, 1]] * 3; Czq = CE.check_candidate(P.M, cl, CE.unit_scales(P.M), P.clock, P.budget); c = UP.Cand('approx', ident); c.Cz = Czq; c.scales = CE.unit_scales(P.M); c.classes = cl; c.prof = None; c.M1 = P.M; c.stages = [(cl, Czq)]; c.cards = list(Czq.ccards); c.scopes = [sc for sc, _ in P.M.factors]; c.constructions = 1; c.name = 'approx(supplied)'; P.set_quality(c); c.order, c.vol = UP.order_and_volume(c.cards, c.scopes, P.clock, P.budget); c.fbytes = UP.forecast_bytes(c.vol); P.cands.append(c)
    r0 = P.perform(dict(kind='solve', cand=c, side='lower', deadline=P.adm, record=dict(T_b_s=0.01))); rows = CE.publish(P.M, P.retained, F(1, 200), P.clock); pubq = sum(1 for r in rows.values() if r)
    okq = all(P.retained[(v, a)][0] <= NQ[v][a] / ZQ <= P.retained[(v, a)][1] for v in range(3) for a in range(4)); widths = {k: float(hi - lo) for k, (lo, hi) in P.retained.items()}
    rec('D_unknown_quality_useful_query_specific_bound', okq and c.prospective_quality() == 'unknown' if hasattr(c, 'prospective_quality') else (okq and not c.promising and c.R is not None and float(c.bound_width) > 0.01 and min(widths.values()) < 0.01), R=CE.fl(c.R), worst_width_bound=CE.fl(c.bound_width), min_row_width=min(widths.values()), max_row_width=max(widths.values()), published_rows=pubq, note='global worst-case bound fails 2 eps, yet the one-solve interval of the improbable coordinate is far inside the contract: quality UNKNOWN is the right label')
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
    CE.exact_profile_classes = slow_profiles; UP.est_solve = big_identity
    try: d = run(mB)
    finally: CE.exact_profile_classes = orig_epc; UP.est_solve = orig_est
    ok, pub, mw, det = contained(d, mB, ZB, NB); ex = [a for a in acts(d) if a[0] == 'discover_exact']
    rec('G_exact_allowance_expiry_other_candidates_usable', ok and d['outcome'] == 'COMPLETE' and bool(ex) and ex[0][2] == 'REFUSED_ALLOWANCE_EXPIRED' and not any(n_.startswith('exact') for n_ in d['mechanism']['representations_solved']) and not any(c['kind'] == 'exact' for c in d['candidates']), actions=acts(d), detail=det, solved=d['mechanism']['representations_solved'], note='the slow exact discovery is CALLED, expires at its allowance, is NOT an executable candidate, and the remaining candidates (identity / FAST) complete the task')
    orig_sp = CE.slice_profiles
    def refuse_profiles(M1, clock=None, budget=None): raise CE.Refused('MEMORY', 'injected profile byte refusal')
    CE.slice_profiles = refuse_profiles; UP.est_solve = big_identity
    try: d = run(mP)
    finally: CE.slice_profiles = orig_sp; UP.est_solve = orig_est
    ok, pub, mw, det = contained(d, mP, ZP, NP); fa = [a for a in acts(d) if a[0] == 'discover_fast']
    rec('G_profile_byte_refusal_identity_usable', ok and d['outcome'] == 'COMPLETE' and bool(fa) and fa[0][2] == 'REFUSED_MEMORY' and 'identity' in d['mechanism']['representations_solved'], actions=acts(d), detail=det, note='FAST discovery is CALLED and refused on bytes; identity then completes')
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
    mz = mk([2, 2], [((0, 1), [0, 1, 1, 0])]); Zz, Nz = brute(mz); P = UP.Planner(mz, 3.5, t_start=time.monotonic()); P.M = CE.canonicalize(mz, P.clock, P.budget); P.canonical_charge = P.budget.live; ident = P.make_identity(P.clock); P.cands.append(ident)
    cl = [[0, 0], [0, 0]]; Czm = CE.check_candidate(P.M, cl, CE.unit_scales(P.M), P.clock, P.budget); c = UP.Cand('approx', ident); c.Cz = Czm; c.scales = CE.unit_scales(P.M); c.classes = cl; c.prof = None; c.M1 = P.M; c.stages = [(cl, Czm)]; c.cards = list(Czm.ccards); c.scopes = [sc for sc, _ in P.M.factors]; c.constructions = 1; c.name = 'approx(supplied_mixed)'; P.set_quality(c); c.order, c.vol = UP.order_and_volume(c.cards, c.scopes, P.clock, P.budget); c.fbytes = UP.forecast_bytes(c.vol); P.cands.append(c)
    r0 = P.perform(dict(kind='solve', cand=c, side='lower', deadline=P.adm, record=dict(T_b_s=0.01))); r1 = P.perform(dict(kind='solve', cand=c, side='upper', deadline=P.adm, record=dict(T_b_s=0.01))); st = (c.status['lower'], c.status['upper']); pos = P.out['mechanism']['positive_mass_witness']
    dI = run(mz, 'identity'); okI, pubI, _, detI = contained(dI, mz, Zz, Nz)
    rec('J_zero_lower_positive_upper_no_witness', r0 is None and r1 is None and c.SL.zero and c.SU is not None and c.SU.Z_lo > 0 and st == ('LOWER_ZERO_MASS', 'UPPER_SOLVED_NO_LOWER_WITNESS') and pos is not True and len(P.retained) == 0 and 'defect' not in P.out['mechanism'] and okI and dI['outcome'] == 'COMPLETE' and Zz == 2, statuses=st, positive_mass_witness=pos, Z=str(Zz), Z_U_lo=str(c.SU.Z_lo), mixed=Czm.mixed, R=CE.fl(Czm.R), identity=dI['outcome'], note='Z_L = 0 < Z = 2 <= Z_U = 4: both solves run, no witness, no row, no defect; identity completes')
    # ---- K. retention / release accounting across multiple live candidates; the 8^4 profile and expired 150-clique boundaries through the reused functions
    UP.est_solve = big_identity
    try: d = run(mD)
    finally: UP.est_solve = orig_est
    mech = d['mechanism']; rec('K_multi_candidate_accounting', mech['constructor_budget_cumulative_bytes'] >= mech['constructor_budget_peak_bytes'] >= mech['constructor_live_at_end_bytes'] >= 0 and len(d['candidates']) >= 2 and mech['constructor_live_ledger_identity'] and all(c['charged_bytes'] >= 0 for c in d['candidates']), peak=mech['constructor_budget_peak_bytes'], cumulative=mech['constructor_budget_cumulative_bytes'], live_end=mech['constructor_live_at_end_bytes'], ledger_identity=mech['constructor_live_ledger_identity'], charges=[(c['name'], c['charged_bytes']) for c in d['candidates']])
    P = UP.Planner(mD, 10, admission_stop_s=10, t_start=time.monotonic()); P.M = CE.canonicalize(mD, P.clock, P.budget); P.canonical_charge = P.budget.live; ident = P.make_identity(P.clock); P.cands.append(ident); c0 = P.discover_fast(ident, P.clock); P.cands.append(c0); l0 = P.budget.live; r1 = P.refine_cand(c0, P.clock); P.cands.append(r1); l1 = P.budget.live; r2 = P.refine_cand(r1, P.clock); P.cands.append(r2); l2 = P.budget.live
    rec('K_two_refinements_retain_and_charge', r1.charged >= 0 and r2.charged >= 0 and l1 >= l0 and l2 >= l1 and c0 in P.cands and c0.Cz is not None and r1.Cz is not None and P.budget.live == P.canonical_charge + sum(x.charged for x in P.cands) and r1.shares.get('prof') == c0.name, charges=[(x.name, x.charged) for x in P.cands], live=(l0, l1, l2), ledger_identity=(P.budget.live == P.canonical_charge + sum(x.charged for x in P.cands)))
    n = 150; scopes = [(i, j) for i in range(n) for j in range(i + 1, n)]; clock = CE.Clock(time.monotonic() + 5, {}); bg = CE.Budget(CE.CONSTRUCTOR_BYTES); import tracemalloc; tracemalloc.start(); o1, v1 = UP.order_and_volume([2] * n, scopes, clock, bg); _, pk = tracemalloc.get_traced_memory(); tracemalloc.stop(); o2, _ = CE.elimination_order([2] * n, scopes, CE.Clock(time.monotonic() + 5, {}), CE.Budget(CE.CONSTRUCTOR_BYTES))
    rec('K_single_guarded_order_volume_pass', o1 == o2 and bg.peak >= pk and bg.live == 0, charged_peak=bg.peak, traced_peak=pk, order_identical=(o1 == o2))
    star = mk([2] * 150, [((0, j), [1, 2, 3, 4]) for j in range(1, 150)]); P = UP.Planner(star, 10, admission_stop_s=10, t_start=time.monotonic()); P.M = CE.canonicalize(star, P.clock, P.budget); P.canonical_charge = P.budget.live; ident = P.make_identity(P.clock); P.cands.append(ident); P.clock.deadline = P.hclock.deadline = time.monotonic() - 1; tracemalloc.start()
    try: P.optimistic_after_fast(ident); k_ = None
    except CE.Refused as e: k_ = e.kind
    _, pk2 = tracemalloc.get_traced_memory(); tracemalloc.stop(); rec('K_optimistic_estimate_guarded', k_ == 'DEADLINE' and pk2 < 65536, refusal=k_, traced=pk2)
    P.clock.deadline = P.hclock.deadline = time.monotonic() + 10; P.budget.cap = P.budget.live + 100000; cum0 = P.budget.cumulative; tracemalloc.start()
    try: P.optimistic_after_fast(ident); k2 = None
    except CE.Refused as e: k2 = e.kind
    _, pk3 = tracemalloc.get_traced_memory(); tracemalloc.stop(); ch3 = P.budget.cumulative - cum0
    rec('K_optimistic_estimate_memory_admitted', (k2 == 'MEMORY') or (k2 is None and ch3 >= pk3 and pk3 < 100000), refusal=k2, charged=ch3, traced=pk3, note='along the ADMITTED leaf-first identity order the star needs no hub clique: the pass is cheap and its charge covers the traced bytes (the reviewer\'s natural-order clique is no longer built); a refusal is the other acceptable outcome')
    P.budget.cap = P.budget.live + 1000
    try: P.optimistic_after_fast(ident); k3 = None
    except CE.Refused as e: k3 = e.kind
    rec('K_optimistic_estimate_refuses_under_tiny_cap', k3 == 'MEMORY', refusal=k3)
    Mp = CE.Canon(); Mp.cards = [8] * 4; Mp.psi = [[F(1)] * 8 for _ in range(4)]; Mp.factors = [(tuple(range(4)), [F(i + 1, 17) for i in range(4096)])]
    try: CE.exact_profile_classes(Mp, CE.Clock(time.monotonic() + 5, {}), CE.Budget(600000)); k = None
    except CE.Refused as e: k = e.kind
    rec('K_8x8x8x8_profile_refusal_reused', k == 'MEMORY')
    n = 150; scopes = [(i, j) for i in range(n) for j in range(i + 1, n)]; clock = CE.Clock(time.monotonic() - 1, {})
    try: UP.order_and_volume([1] * n, scopes, clock, CE.Budget(CE.CONSTRUCTOR_BYTES)); k = None
    except CE.Refused as e: k = e.kind
    rec('K_expired_150_clique_refuses_at_entry', k == 'DEADLINE' and clock.polls == 1)
    # ---- R4 / R5 (24 Nov review): the API success boundary enforces the hard deadline after the diagnostic tail; an incumbent is cut early only for a USABLE alternative
    real_res = UP.resource.getrusage; off = [0.0]; CE.tnow = lambda: time.monotonic() + off[0]; UP.tnow = CE.tnow
    def late_rusage(who): off[0] = 10.0; return real_res(who)
    UP.resource.getrusage = late_rusage
    try: d = UP.plan_and_solve(mk([2, 2], [((0, 1), [1, 2, 3, 4])]), 3.5, policy='identity', t_start=time.monotonic())
    finally: CE.tnow = orig_now; UP.tnow = orig_now; UP.resource.getrusage = real_res
    rec('R4_api_success_boundary_enforces_hard_deadline', d['outcome'] == 'DEADLINE' and d['published'] == 0 and d['hard_deadline_respected'] is False, outcome=d['outcome'], published=d['published'], late=d['mechanism'].get('late_assembly'))
    P = UP.Planner(mk([2, 2], [((0, 1), [1, 2, 3, 4])]), 10, admission_stop_s=10, t_start=time.monotonic()); P.M = CE.canonicalize(P.model, P.clock, P.budget); P.canonical_charge = P.budget.live; ident = P.make_identity(P.clock); P.cands.append(ident); P.W = lambda: 1.0; P.T_solve = lambda *a: (0.1, {}); P.optional_actions = lambda: [dict(name='discover_fast', cand=ident, D=0.9, S=0.01, parts={})]; f1 = P.decide()
    P.optional_actions = lambda: [dict(name='discover_fast', cand=ident, D=0.1, S=0.01, parts={})]; f2 = P.decide()
    rec('R5_reserve_only_for_usable_alternative', f1['kind'] == 'solve' and f1['record']['competing_alternative'] == [] and abs(f1['deadline'] - P.adm) < 1e-6 and f2['kind'] == 'solve' and f2['record']['competing_alternative'] == ['discover_fast'] and f2['deadline'] < P.adm, unusable=f1['record']['why'], usable=f2['record']['why'])
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
