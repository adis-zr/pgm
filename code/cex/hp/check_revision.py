"""Focused controls for UNIFIED_SCHEDULING_REVISION_1 (brief section 6): deterministic injected clocks / estimates / coefficients so branch coverage does not depend on a millisecond race.
Covers: P0 skips vs P1 attempts a constructor with D > W/4 (positive fixture completes through the constructed candidate); allowance expiry refuses locally, releases temporaries, consumes the
attempt, preserves identity; estimation refusals and failed constructors stay unavailable under P1; unknown-quality solves with D > W/4 stay ineligible; inadmissible alternatives never cut
the incumbent; a speculative constructor failing the old post-allowance test cannot newly cut an affordable incumbent; D + S ordering; attempt caps incl. failures, no restart; identical counts
-> identical estimates; hand-made affine dataset recovers intercept / slope and excludes a timeout; full estimates compose host + kernel + recovery + U + one tail; switches off = P0 / R0;
final timestamp / charge invariants under both switches. usage: check_revision.py OUT.json [--rates PATH]"""
import sys, os, json, time, math, random, itertools, inspect, builtins, argparse
from fractions import Fraction as F
HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, HERE); sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(HERE)), 'cex', 'newarm'))
import coarse_envelope as CE, unified_planner as UP, cost_model as CM, check_hp as H
from check_hp import brute, mk, clones
RES = dict(checks=[], all_ok=True, utc=time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()))
def rec(name, ok, **kw): RES['checks'].append(dict(name=name, ok=bool(ok), **kw)); RES['all_ok'] &= bool(ok); print(('PASS ' if ok else 'FAIL ') + name, json.dumps(kw, default=str)[:230], flush=True)
def acts(d): return [(x.get('action'), x.get('cand'), x.get('status')) for x in d['actions']]
INJ = dict(model='injected', status='FITTED', frozen=True, sha256='injected', blocks={'exact_construction': dict(intercept=0.002, coefficients=[2e-6, 1e-6]), 'fast_construction': dict(intercept=0.003, coefficients=[2e-6, 3e-7, 1e-6]), 'refine_construction': dict(intercept=0.001, coefficients=[1e-6, 1e-7, 5e-7]), 'native_host': dict(intercept=0.004, coefficients=[1e-6, 2e-5]), 'native_kernel': dict(intercept=0.0, coefficients=[5e-8]), 'recovery': dict(intercept=0.0005, coefficients=[1e-6, 5e-7, 2e-7]), 'final': dict(intercept=0.001, coefficients=[1e-6])})

def set_W(P, w): P.adm = time.monotonic() + w; P.clock.deadline = P.adm; P.W = lambda: P.adm - time.monotonic()

def planner(m, sched, rates, budget=3.5, t_start=None): return UP.Planner(m, budget, admission_stop_s=budget, t_start=(time.monotonic() if t_start is None else t_start), policy='unified', sched=sched, rates=rates)
def setup(m, sched, rates):
    P = planner(m, sched, rates); P.M = CE.canonicalize(m, P.clock, P.budget); P.canonical_charge = P.budget.live; P.mf = CM.model_features(P.M, P.clock); ident = P.make_identity(P.clock); P.cands.append(ident); return P, ident

def main(out_path, rates_path):
    t_all = time.monotonic(); rng = random.Random(20261124); cyc = lambda n: [(i, (i + 1) % n) for i in range(n)]
    inj_path = os.path.join(os.path.dirname(os.path.abspath(out_path)), 'INJECTED_R1.json'); json.dump(INJ, open(inj_path, 'w')); CM.R1_PATH = inj_path
    # ---- 1. P0 skips / P1 attempts a constructor whose D > W/4; the constructed candidate completes the task (positive fixture: exact clones, identity priced out)
    mB = clones(rng, 6, 4, cyc(6), 'exact'); ZB, NB = brute(mB)
    for sched in ('P0', 'P1'):
        P, ident = setup(mB, sched, 'R1'); P.T_solve = lambda c, side=0, _o=P.T_solve: (1e9, {}) if c.kind == 'identity' else _o(c, side); P.D_exact = lambda: (0.9, dict(injected=0.9), {}); P.D_fast = lambda parent: (0.95, dict(injected=0.95), {}); set_W(P, 1.0)
        d = P.decide(); r = d['record']; ex = [o for o in r.get('optional', []) if o['name'] == 'discover_exact'][0]
        if sched == 'P0': rec('S1_P0_skips_constructor_over_quarter', d['kind'] == 'solve' and d['cand'].name == 'identity' and not ex['eligible'] and abs(ex['q_s'] - 0.25) < 0.01, chosen=r['chosen'], exact_optional=ex, why=r['why'][:90])
        else:
            ok1 = d['kind'] == 'optional' and d['act']['name'] == 'discover_exact' and ex['eligible'] and ex['forecast_bypassed'] and abs(r['allowance_s'] - 0.25) < 0.01 and d['deadline'] <= P.adm
            P.T_solve = UP.Planner.T_solve.__get__(P)
            done = P.perform(d); d2 = P.decide(); done2 = P.perform(d2) if d2['kind'] != 'finalize' else None
            okc = done2 is not None and all(x is not None for x in done2.values()) and 'exact' in [c.name for c in P.cands if c.SL is not None]
            rec('S1_P1_attempts_constructor_over_quarter_and_completes', ok1 and okc, first=dict(chosen=r['chosen'], allowance=r['allowance_s'], bypassed=r.get('forecast_bypassed'), why=r['why'][:100]), second=dict(chosen=d2['record'].get('chosen'), cand=d2['record'].get('chosen_cand')), solved=[c.name for c in P.cands if c.SL is not None])
    # ---- 2. constructor exceeding its allowance: local refusal, temporaries released, attempt consumed, identity + earlier rows preserved
    P, ident = setup(mB, 'P1', 'R1'); live0 = P.budget.live; orig_epc = CE.exact_profile_classes
    def slow(M, clock, budget):
        t = time.monotonic()
        while time.monotonic() - t < 0.4: clock.poll('injected slow profiles')
        return orig_epc(M, clock, budget)
    CE.exact_profile_classes = slow; P.T_solve = lambda c, side=0, _o=P.T_solve: (1e9, {}) if c.kind == 'identity' else _o(c, side); set_W(P, 0.6)
    try: d = P.decide(); P.perform(d)
    finally: CE.exact_profile_classes = orig_epc
    a = P.out['actions'][-1]; rec('S2_allowance_expiry_local_release_attempt_consumed', d['act']['name'] == 'discover_exact' and a['status'] == 'REFUSED_ALLOWANCE_EXPIRED' and P.budget.live == live0 and P.n_exact_disc == 1 and 'exact_discovery' in P.failed_global and not any(c.kind == 'exact' for c in P.cands), status=a['status'], live_before=live0, live_after=P.budget.live, n_exact_disc=P.n_exact_disc, allowance=round(d['record']['allowance_s'], 3))
    P.T_solve = UP.Planner.T_solve.__get__(P); set_W(P, 3.0); d2 = P.decide(); rec('S2_identity_still_available_after_expiry', d2['kind'] == 'solve' and d2['cand'].name == 'identity' and not any(o['name'] == 'discover_exact' for o in d2['record'].get('optional', [])), chosen=d2['record'].get('chosen_cand'))
    # ---- 3. estimation refusal / failed constructor unavailable under P1
    P, ident = setup(mB, 'P1', 'R1'); P.T_solve = lambda c, side=0, _o=P.T_solve: (1e9, {}) if c.kind == 'identity' else _o(c, side); set_W(P, 1.0)
    P.optimistic_after_fast = lambda parent: (_ for _ in ()).throw(CE.Refused('MEMORY', 'injected estimator refusal')); d = P.decide(); names = [o['name'] for o in d['record'].get('optional', [])]
    rec('S3_estimation_refusal_unavailable_under_P1', 'discover_fast' not in names and any(e['action'] == 'discover_fast' and e['kind'] == 'MEMORY' for e in P.out['mechanism']['estimation_refusals']), optional=names, refusals=P.out['mechanism']['estimation_refusals'])
    P.failed_global = {'exact_discovery'}; d = P.decide(); rec('S3_failed_constructor_unavailable_under_P1', 'discover_exact' not in [o['name'] for o in d['record'].get('optional', [])], optional=[o['name'] for o in d['record'].get('optional', [])])
    # ---- 4. unknown-quality solve with D > W/4 stays ineligible; inadmissible alternative never cuts; speculative constructor failing the old post-allowance test cannot newly cut an affordable incumbent; positive early-cut case
    mG = clones(rng, 4, 4, cyc(4), 'generic'); P, ident = setup(mG, 'P1', 'R1'); c = P.discover_fast(ident, P.clock); P.cands.append(c); P.n_exact_disc = UP.MAX_EXACT_DISCOVERY; P.n_fast_disc = UP.MAX_FAST_DISCOVERY
    P.T_solve = lambda cand, side=0: (1e9, {}) if cand.kind == 'identity' else (0.9, {}); set_W(P, 1.0); P.D_refine = lambda cc: (1e9, {}, {})
    d = P.decide(); r = d['record']; unk = [o for o in r.get('optional', []) if o['name'] == 'solve_lower_unknown']
    rec('S4_unknown_quality_solve_over_quarter_ineligible', bool(unk) and not unk[0]['eligible'] and not unk[0].get('forecast_bypassed') and d['kind'] == 'solve' and d['cand'].name == 'identity', unknown=unk, chosen=r.get('chosen_cand'), why=r['why'][:80])
    P.T_solve = lambda cand, side=0: (0.1, {}); c.fbytes = CE.USABLE_BYTES + 1; d = P.decide(); rec('S4_inadmissible_alternative_no_cut_P1', d['kind'] == 'solve' and d['cand'].name == 'identity' and d['record']['competing_alternative'] == [] and abs(d['deadline'] - P.adm) < 1e-6, why=d['record']['why'][:90])
    c.fbytes = 1000; d = P.decide(); rec('S4_admitted_alternative_cuts_P1', d['record']['competing_alternative'] == ['solve_lower_unknown'] and d['deadline'] < P.adm, competing=d['record']['competing_alternative'])
    P2, ident2 = setup(mB, 'P1', 'R1'); P2.T_solve = lambda cand, side=0: (0.1, {}); set_W(P2, 1.0); P2.D_exact = lambda: (0.9, {}, {}); P2.D_fast = lambda parent: (0.95, {}, {}); d = P2.decide(); r = d['record']
    rec('S4_speculative_constructor_cannot_newly_cut_affordable_incumbent', d['kind'] == 'solve' and d['cand'].name == 'identity' and r['competing_alternative'] == [] and abs(d['deadline'] - P2.adm) < 1e-6 and all(not o['eligible'] for o in r['optional']), optional=[(o['name'], o['eligible'], o['q_s']) for o in r['optional']], why=r['why'][:90])
    # ---- 5. D + S ordering (no exact-first / FAST-first), attempt caps incl. failures, no restart
    P, ident = setup(mB, 'P1', 'R1'); P.T_solve = lambda cand, side=0, _o=P.T_solve: (1e9, {}) if cand.kind == 'identity' else _o(cand, side); set_W(P, 1.0); P.D_exact = lambda: (0.9, {}, {}); P.optimistic_after_exact = lambda: 0.5; P.D_fast = lambda parent: (0.95, {}, {}); P.optimistic_after_fast = lambda parent: 0.1
    d = P.decide(); rec('S5_selection_by_D_plus_S', d['kind'] == 'optional' and d['act']['name'] == 'discover_fast', chosen=d['record']['chosen'], exact_DS=0.9 + 0.5, fast_DS=0.95 + 0.1)
    P, ident = setup(mB, 'P1', 'R1'); P.n_exact_disc = UP.MAX_EXACT_DISCOVERY; P.failed_global = {'exact_discovery'}; P.n_fast_disc = UP.MAX_FAST_DISCOVERY; P.failed_global |= {'fast_discovery'}; P.T_solve = lambda cand, side=0: (1e9, {}); set_W(P, 1.0); d = P.decide()
    rec('S5_attempt_caps_include_failures_no_restart', d['record'].get('optional') == [] and d['kind'] == 'solve' and d['cand'].name == 'identity' and 'bounded attempt' in d['record']['why'], optional=d['record'].get('optional'), why=d['record']['why'][:90])
    # ---- 6. identical physical counts -> identical estimates irrespective of label / path; hand-made affine dataset recovers intercept + slope; a timeout record is excluded
    cm = CM.R1(inj_path); f1 = dict(E_phys=100, S_phys=20, V=5000, K=40, J=40, h=1, U=0, ell=2); f2 = dict(f1); rec('S6_identical_counts_identical_estimates', cm.solve_cost(f1)[0] == cm.solve_cost(f2)[0] and cm.solve_cost(f1)[0] == cm.solve_cost(dict(f1, label='other', path='x'))[0], estimate=cm.solve_cost(f1)[0])
    rows = [(dict(V=v), 0.01 + 3e-7 * v) for v in (1000, 5000, 20000, 80000, 200000)]; r = CM.fit_nnls(rows, 'native_kernel'); rec('S6_affine_fit_recovers_intercept_slope', abs(r['intercept'] - 0.01) < 1e-6 and abs(r['coefficients'][0] - 3e-7) < 1e-10, intercept=r['intercept'], slope=r['coefficients'][0], residual_norm=r['residual_norm'])
    import calibrate_revision as CR; tmpd = os.path.join(os.path.dirname(os.path.abspath(out_path)), 'fit_fixture'); os.makedirs(tmpd, exist_ok=True)
    meas = [dict(kind='native', features=dict(E_phys=10, S_phys=4, V=100, K=8, J=8, h=0, U=0, ell=1), native_total_s=0.02, kernel_s=0.01, host_s=0.01, recovery_s=0.002, completed=True), dict(kind='native', features=dict(E_phys=20, S_phys=8, V=400, K=16, J=16, h=0, U=0, ell=1), native_total_s=0.03, kernel_s=0.015, host_s=0.015, recovery_s=0.003, completed=True), dict(kind='native', features=dict(E_phys=1000, S_phys=99, V=1e9, K=99, J=99, h=0, U=0, ell=1), native_total_s=0.6, completed=False, censored='DEADLINE')]
    json.dump(dict(measurements=meas, outcome='x', wall_s=0), open(os.path.join(tmpd, 'm1.json'), 'w')); rows_b, censored, _ = CR.collect(tmpd); rec('S6_timeout_excluded_from_completed_fit', len(rows_b['native_kernel']) == 2 and len(censored) == 1 and censored[0]['censored'] == 'DEADLINE', completed=len(rows_b['native_kernel']), censored=censored)
    # ---- 7. full estimates compose host + kernel + recovery + U (upper) + exactly one final tail; completed phases absent from remaining cost
    f = dict(E_phys=100, S_phys=20, V=5000, K=40, J=40, h=1, U=0, ell=2); T, parts = cm.solve_cost(f); fU = dict(f, U=160); TU, partsU = cm.solve_cost(fU)
    rec('S7_full_estimate_composition_one_tail', set(parts) == {'native_host', 'native_kernel', 'recovery', 'final_tail'} and abs(T - sum(parts.values())) < 1e-12 and parts['final_tail'] == max(CM.FINALIZE_RESERVE_S, cm.predict('final', f)) and TU > T and partsU['recovery'] > parts['recovery'] and partsU['final_tail'] == parts['final_tail'], parts=parts, with_upper=partsU)
    P, ident = setup(mB, 'P1', 'R1'); dE = P.D_exact(); rec('S7_constructor_D_excludes_solve_and_tail', all(k in ('intercept', 'A_ell', 'G') for k in dE[1]) and 'final_tail' not in dE[1] and 'native_kernel' not in dE[1], parts=dE[1])
    # ---- 8. switches off reproduce P0 / R0 decisions on a fixed-clock fixture; both switches keep the final-timestamp + charge invariants
    P0 = setup(mB, 'P0', 'R0')[0]; Pref = UP.Planner(mB, 3.5, admission_stop_s=3.5, t_start=time.monotonic()); Pref.M = CE.canonicalize(mB, Pref.clock, Pref.budget); Pref.canonical_charge = Pref.budget.live; Pref.mf = CM.model_features(Pref.M, Pref.clock); Pref.cands.append(Pref.make_identity(Pref.clock))
    for Q in (P0, Pref): set_W(Q, 1.0)
    d0 = P0.decide(); dr = Pref.decide(); same = (d0['record']['chosen'], d0['record'].get('chosen_cand'), [(o['name'], round(o['D_s'], 6), round(o['q_s'], 6), o['eligible']) for o in d0['record'].get('optional', [])]) == (dr['record']['chosen'], dr['record'].get('chosen_cand'), [(o['name'], round(o['D_s'], 6), round(o['q_s'], 6), o['eligible']) for o in dr['record'].get('optional', [])])
    rec('S8_switches_off_reproduce_P0_R0', same and P0.sched == 'P0' and P0.rates == 'R0' and P0.cm is None, p0=d0['record'].get('chosen'), ref=dr['record'].get('chosen'))
    for sched, rates in (('P0', 'R1'), ('P1', 'R0'), ('P1', 'R1')):
        orig_now = UP.tnow; off = [0.0]; UP.tnow = CE.tnow = lambda: time.monotonic() + off[0]; real_res = UP.resource.getrusage
        def late(who): off[0] = 10.0; return real_res(who)
        UP.resource.getrusage = late
        try: d = UP.plan_and_solve(mk([2, 2], [((0, 1), [1, 2, 3, 4])]), 3.5, policy='identity', t_start=time.monotonic(), sched=sched, rates=rates)
        finally: UP.tnow = CE.tnow = orig_now; UP.resource.getrusage = real_res
        d2 = UP.plan_and_solve(mG, 3.5, policy='unified', t_start=time.monotonic(), sched=sched, rates=rates); ZG, NG = brute(mG); ok, pub, mw, det = H.contained(d2, mG, ZG, NG)
        rec('S8_invariants_%s_%s' % (sched, rates), d['outcome'] == 'DEADLINE' and d['published'] == 0 and d2['mechanism']['constructor_live_ledger_identity'] and all(c['charged_bytes'] >= 0 for c in d2['candidates']) and ok and d2['outcome'] == 'COMPLETE' and d2['rates_model'] == rates and d2['sched'] == sched, late=d['outcome'], ledger=d2['mechanism']['constructor_live_ledger_identity'], outcome=d2['outcome'], detail=det)
    # ---- 10. USR1 closeout (independent review 24 Nov): guarded feature pass; native measurement preserved on a recovery refusal; completion status from the final validated snapshot; output timing persisted; calibration dedup
    import tracemalloc
    n = 150; clique = mk([2] * n, [((i, j), [1, 2, 3, 4]) for i in range(n) for j in range(i + 1, n)]); Mq = CE.canonicalize(clique, CE.Clock(time.monotonic() + 10, {}), CE.Budget(128 << 20))
    clk = CE.Clock(time.monotonic() - 1, {}); tracemalloc.start()
    try: CM.model_features(Mq, clk, CE.Budget(128 << 20)); k_ = None
    except CE.Refused as e: k_ = e.kind
    _, pk = tracemalloc.get_traced_memory(); tracemalloc.stop(); rec('S10_feature_pass_expired_entry_refuses', k_ == 'DEADLINE' and clk.polls == 1 and pk < 4096, refusal=k_, polls=clk.polls, traced=pk)
    class LateClock(CE.Clock):
        def __init__(self, n_ok): super().__init__(math.inf, {}); self.n_ok = n_ok
        def poll(self, where):
            self.polls += 1
            if self.polls > self.n_ok: raise CE.Refused('DEADLINE', 'injected after %d polls (%s)' % (self.n_ok, where))
    lc = LateClock(3)
    try: CM.model_features(Mq, lc, CE.Budget(128 << 20)); k2 = None
    except CE.Refused as e: k2 = e.kind; where = str(e.reason)
    rec('S10_feature_pass_polls_across_many_small_factors', k2 == 'DEADLINE' and 'scope pass' in where, refusal=k2, where=where[:80], n_factors=len(Mq.factors))
    class RecClock(CE.Clock):
        def __init__(self): super().__init__(math.inf, {}); self.wheres = []
        def poll(self, where): self.polls += 1; self.wheres.append(where)
    Mu = CE.canonicalize(mk([3] * 200, [((v,), [1, 2, 3]) for v in range(200)] + [((v, v + 1), [1] * 9) for v in range(199)]), CE.Clock(time.monotonic() + 10, {}), CE.Budget(128 << 20)); rc_ = RecClock(); CM.model_features(Mu, rc_, CE.Budget(128 << 20))
    rec('S10_feature_pass_polls_unary_scan', any('unary' in w for w in rc_.wheres) and any('scope pass' in w for w in rc_.wheres) and rc_.wheres[0].startswith('at the feature-pass entry') and rc_.wheres[-1].startswith('at the feature-pass exit'), polls=rc_.polls, unary_polls=sum(1 for w in rc_.wheres if 'unary' in w), scope_polls=sum(1 for w in rc_.wheres if 'scope pass' in w), retained_vars=len(Mu.cards))
    bq = CE.Budget(100)
    try: CM.model_features(Mq, CE.Clock(time.monotonic() + 10, {}), bq); k4 = None
    except CE.Refused as e: k4 = e.kind
    rec('S10_feature_pass_exhausted_headroom_refuses_and_releases', k4 == 'MEMORY' and bq.live == 0, refusal=k4, live_after=bq.live)
    bq2 = CE.Budget(128 << 20); CM.model_features(Mq, CE.Clock(time.monotonic() + 10, {}), bq2); rec('S10_feature_pass_scratch_charged_then_released', bq2.peak > 0 and bq2.live == 0, peak=bq2.peak, live=bq2.live)
    probe_b = CE.Budget(128 << 20); CE.canonicalize(mB, CE.Clock(time.monotonic() + 10, {}), probe_b); P = planner(mB, 'P1', 'R1'); P.budget = CE.Budget(probe_b.live); d = P.run()                       # zero constructor headroom after canonicalization: the feature pass must refuse BEFORE allocating
    rec('S10_feature_pass_in_planner_zero_headroom_refuses', d['outcome'] == 'REFUSED' and (d['mechanism'].get('refusal') or {}).get('kind') == 'MEMORY' and 'feature-pass' in (d['mechanism'].get('refusal') or {}).get('reason', '') and P.budget.live == probe_b.live and P.budget.cumulative == probe_b.live, outcome=d['outcome'], refusal=d['mechanism'].get('refusal'), live=P.budget.live, cap=P.budget.cap, cumulative=P.budget.cumulative)
    # native measurement preserved when recovery is refused; the action is labelled SOLVED_RECOVERY_<kind>, not a censored native call
    P, ident = setup(mG, 'P1', 'R1'); orig_rec = UP.CE.rows_from_witness
    def refuse_recovery(*a, **k): raise CE.Refused('DEADLINE', 'injected recovery expiry')
    c = P.discover_fast(ident, P.clock); P.cands.append(c); UP.CE.rows_from_witness = refuse_recovery
    try: P.perform(dict(kind='solve', cand=c, side='lower', deadline=P.adm, record=dict(T_b_s=0.1)))
    finally: UP.CE.rows_from_witness = orig_rec
    nat = [m for m in P.measurements if m['kind'] == 'native']; a = P.out['actions'][-1]
    rec('S10_native_measurement_preserved_on_recovery_refusal', len(nat) == 1 and nat[0]['completed'] and nat[0].get('recovery_completed') is False and nat[0].get('recovery_censored') == 'DEADLINE' and a['status'] == 'SOLVED_RECOVERY_DEADLINE' and a.get('phase', '').startswith('recovery') and c.SL is not None, native=dict(completed=nat[0]['completed'], native_total_s=round(nat[0]['native_total_s'], 4), recovery=nat[0].get('recovery_completed'), censored=nat[0].get('recovery_censored')) if nat else None, status=a['status'])
    # completion status from the final validated snapshot: an action publication allowance expires AFTER the intervals were retained; final assembly then delivers every row before the hard deadline -> COMPLETE (termination recorded separately)
    P = planner(mB, 'P1', 'R1'); orig_pub = CE.publish; calls = [0]
    def late_pub(M, acc, eps, clock):
        calls[0] += 1
        if calls[0] == 1: P.adm = time.monotonic() - 1; P.clock.deadline = P.adm; raise CE.Refused('DEADLINE', 'injected: the WORK cutoff expires during publication (the hard deadline is far away)')   # the C scenario: intervals already retained, work cutoff gone, hard deadline not
        return orig_pub(M, acc, eps, clock)
    CE.publish = late_pub
    try: d = P.run()
    finally: CE.publish = orig_pub
    ZB2, NB2 = brute(mB); okc, pubc, mwc, detc = H.contained(d, mB, ZB2, NB2)
    rec('S10_status_from_final_validated_snapshot', okc and d['outcome'] == 'COMPLETE' and d['published'] == d['K'] and d['hard_deadline_respected'] and d['mechanism'].get('termination') in ('DEADLINE', 'DEADLINE_PARTIAL') and any(x['status'].startswith('SOLVED_RECOVERY_') for x in d['actions']), outcome=d['outcome'], termination=d['mechanism'].get('termination'), published=d['published'], K=d['K'], actions=acts(d), detail=detc)
    # output timing persisted on disk
    small = dict(outcome='COMPLETE', published=1, K=1, answers=[dict(var=0, state=0, lo='1', hi='1', point='1', guarantee='EXACT')], phases_s={}, mechanism={}); pth = os.path.join(os.path.dirname(os.path.abspath(out_path)), 'WRITE_RESULT_CTRL.json'); UP.write_result(small, pth, 3.5, t_process_start=time.monotonic()); disk = json.load(open(pth)); side = json.load(open(pth + '.timing.json'))
    rec('S10_output_timing_persisted', 'output_s' in side and 'hard_deadline_respected_at_commit' in side and side['outcome'] == 'COMPLETE' and side['published'] == 1 and 'output' not in disk['phases_s'], sidecar=side)
    # calibration dedup: identical native model / order / query is dispatched once per fixture; recovery still measured
    import calibrate_revision as CR; mpath = os.path.join(os.path.dirname(os.path.abspath(out_path)), 'dedup_fixture.uai'); import hp_gen as G2; G2.write(mpath, clones(random.Random(5), 6, 4, cyc(6), 'exact')); mo = os.path.join(os.path.dirname(os.path.abspath(out_path)), 'dedup_measure.json')
    import subprocess as sp; sp.run([sys.executable, os.path.join(HERE, 'calibrate_revision.py'), 'measure', mpath, mo], capture_output=True, timeout=20); dm = json.load(open(mo)); keys = {}
    for m_ in dm['measurements']:
        if m_['kind'] == 'native': keys.setdefault(m_['cand'], 0)
    rec('S10_calibration_dedup_no_repeated_native_dispatch', dm['dedup']['dispatched'] == len([m_ for m_ in dm['measurements'] if m_['kind'] == 'native']) and len(dm['dedup']['skipped']) >= 1 and any(m_['kind'] == 'recovery_only' for m_ in dm['measurements']), dispatched=dm['dedup']['dispatched'], skipped=[(x['cand'], x['same_as']) for x in dm['dedup']['skipped']], recovery_only=sum(1 for m_ in dm['measurements'] if m_['kind'] == 'recovery_only'))
    # ---- 9. the real frozen coefficient file loads and evaluates (smoke; only when present)
    if rates_path and os.path.exists(rates_path):
        try: cmr = CM.R1(rates_path); T, parts = cmr.solve_cost(f); rec('S9_frozen_rates_load_and_evaluate', math.isfinite(T) and T > 0 and cmr.d.get('status') == 'FITTED', sha256=cmr.sha256[:16], estimate=T)
        except Exception as e: rec('S9_frozen_rates_load_and_evaluate', False, error=repr(e)[:160])
    RES['wall_s'] = time.monotonic() - t_all; RES['n'] = len(RES['checks']); RES['n_ok'] = sum(1 for c in RES['checks'] if c['ok']); json.dump(RES, open(out_path, 'w'), indent=1, default=str)
    print(json.dumps(dict(all_ok=RES['all_ok'], n=RES['n'], n_ok=RES['n_ok'], wall_s=round(RES['wall_s'], 2)))); return 0 if RES['all_ok'] else 1

if __name__ == '__main__':
    ap = argparse.ArgumentParser(); ap.add_argument('out'); ap.add_argument('--rates', default=None); a = ap.parse_args(); sys.exit(main(a.out, a.rates))
