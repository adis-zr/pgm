"""DGP8 before / after probes of the seven DGP7 independent-review findings (brief section 5, abbreviated list). The review file `DGP7_INDEPENDENT_REVIEW_2026-11-26.md` and its supplied probes did NOT arrive on this machine: these probes are THIS
round's, written from the brief's wording against the DGP7 code, and are labelled so. Each probe answers one question: is the finding PRESENT in the source tree given by --source? (True on the parent pgm-eval-2ae105c = the DGP7 engine 47d4024
+ harness amendments; False after the DGP8 repairs). The probes feature-detect the repaired API (the parent lacks it) and never depend on campaign labels.
  R1 residual-bank identity / range checks: an atom cell tampered above one, and a bank presented under another model identity, are consumed silently (present) or rejected typed (absent).
  R2 post-deadline publication: a certificate check (the publication step) runs inside the bounded activation after the activation's hard clock has passed (present) or is skipped (absent).
  R3 retained-object accounting: per-batch records retained by the stream outside the byte ledger grow without bound (present: > 64 KiB after 300 batches) or are bounded (absent).
  R4 over-cap banks: after a committed transaction the bank exceeds its declared limits (64 atoms / 131,072 entries / 64 MiB) (present) or holds them (absent).
  R5 underestimated workspace: the ACTUAL tracemalloc peak of fit + kernel on a 65,536-cell window with 16 atoms exceeds the admitted estimate (present) or is dominated by it (absent).
  R6 same-law region mismatch: the same-law kernel pass of a window planned with a G1 target-only parent is rejected by the kernel's region rule (present) or accepted on the recomputed same-law window (absent).
  R7 missing scheduling calibration check: no control compares the frozen time blocks with actual scored-cell window seconds and no runtime actual / predicted record exists (present) or both exist (absent).
usage: dgp8_probes.py --source ROOT --output OUT.json"""
import sys, os, json, time, math, argparse, tracemalloc, inspect, random
ap = argparse.ArgumentParser(); ap.add_argument('--source', required=True); ap.add_argument('--output', required=True); ap.add_argument('--records', default='/Users/adis/Workspace/pgm-records/code/runs/mdi_2026-10-28/DGP7_RESIDUAL_JOINT'); ap.add_argument('--only', default=None, help='comma list of probe prefixes (R1..R7)'); a = ap.parse_args()
SRC = os.path.abspath(a.source); HP = os.path.join(SRC, 'code', 'cex', 'hp'); sys.path[:0] = [HP, os.path.join(SRC, 'code', 'cex', 'blockres'), os.path.join(SRC, 'code', 'cex', 'newarm')]
from fractions import Fraction as F
import numpy as np
import coarse_envelope as CE, core as CORE, joint_proposal as JP, residual_bank as RB, residual_local as RL, check_residual as CR, residual_stream as RS, pac_actions as PA
from unified_pac_planner import PAC_OPTS
EPS = F(1, 200); DELTA = F(1, 10 ** 6); REC = '/Users/adis/Workspace/pgm-records/code/runs/mdi_2026-10-28'
MODELS = dict(n6=REC + '/DGP2_REPAIR_AND_DIAGNOSIS/oracle/dev_inputs/dg_n6_c4_clique_two.uai', n8=REC + '/DENSE_GENERIC_PAC_INTEGRATION_1/dev/inputs/dg_n8_c4_clique_two.uai', n32c2=REC + '/DENSE_GENERIC_PAC_INTEGRATION_1/inputs_eval/dg_n32_c2_clique_two.uai', n32er=REC + '/DGP4_RESIDUAL_MAX/inputs_fresh/dg_n32_c4_er50_two.uai')
out = dict(source=SRC, utc=time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()), probes={}, findings_present={}, note='THIS round\'s probes written from the brief\'s abbreviated list (the supplied DGP7 review and probes were absent); present = the finding is observed in --source')


def stage(model, secs=120.0, budget=None):
    clk = CE.Clock(PA.tnow() + secs, {}); B = budget or CE.Budget(CE.CONSTRUCTOR_BYTES); M = CE.canonicalize(model, clk, B); order, _ = CE.elimination_order(list(M.cards), [tuple(sc) for sc, _ in M.factors], clk, B); return M, order, clk, B


def rstream(M, allow=20.0, mode='residual_joint', budget=None):
    B = budget or CE.Budget(CE.CONSTRUCTOR_BYTES); S = RS.ResidualStream(2, M, M, [], 1, EPS, DELTA / 4, dict(PAC_OPTS, budget_obj=B), mode=mode); r = S.prepare(PA.tnow() + allow, until=PA.tnow() + allow); return S, B, r


def kernel_accepts_identity(): return 'expected_identity' in inspect.signature(CR.local_kernel).parameters


def probe(name, fn):
    t0 = PA.tnow()
    try: r = fn(); r['seconds'] = round(PA.tnow() - t0, 3); out['probes'][name] = r; out['findings_present'][name] = r.get('present')
    except Exception as e:
        import traceback; out['probes'][name] = dict(error=repr(e)[:300], tb=traceback.format_exc()[-1500:], seconds=round(PA.tnow() - t0, 3)); out['findings_present'][name] = None
    print(name, json.dumps({k: v for k, v in out['probes'][name].items() if k not in ('tb',)}, default=str)[:400], flush=True)


def same_law_region(w, prop, st, cards, order):
    pos = {v: i for i, v in enumerate(order)}; A = list(w['A']); R = set(A)
    for v in A: R |= set(prop.conds[v].parents)
    for aid in w['atoms']: R |= set(st.atoms[aid].axes)
    Rs = sorted(R, key=lambda x: pos[x]); return dict(w, R=Rs, C=[x for x in Rs if x not in A], vol=JP.vol_of(tuple(Rs), cards))


# ---- R1: identity / range
def R1():
    model, _ = CORE.read_uai(MODELS['n8']); M, order, clk, B = stage(model); S, B_, r = rstream(M, allow=30.0); assert r == 'READY', (r, S.closed_reason); S.pilot_action(PA.tnow() + 20); st = S.state; prop = S.epoch.prop; cards = list(M.cards); lp = S.profile['local']
    targets = S._frozen_targets(prop, cards, B_, clk); wins, _ = RL.plan_windows(st, prop, targets, cards, prop.order, lp); assert wins, 'no window'
    w = same_law_region(wins[0], prop, st, cards, prop.order)                                               # a same-law window whose region passes the structural rule on BOTH trees (the region question is R6)
    kw = dict(expected_identity=st.model_identity) if kernel_accepts_identity() else {}
    base = CR.local_kernel(st, w, w['atoms'], prop.conds, None, cards, prop.order, clk, want_rho=False, **kw); res = dict(baseline_ok=base.get('ok'), baseline_why=(base.get('why') or '')[:100])
    # (a) range: one atom cell above one
    at = st.atoms[w['atoms'][0]]; arr = at.arr; arr.setflags(write=True); flat = arr.reshape(-1); old = flat[0]; flat[0] = (1, 1)                       # value 2 > 1
    try: k = CR.local_kernel(st, w, w['atoms'], prop.conds, None, cards, prop.order, clk, want_rho=False, **kw)
    finally: flat[0] = old; arr.setflags(write=False)
    res['tampered_above_one'] = dict(accepted=bool(k.get('ok')), why=(k.get('why') or '')[:120])
    # (b) identity: the same atoms presented under another model identity
    st2 = RB.ResidualState('other-model-identity', st.seed_proof_identity, st.law, st.envelope_B, st.consumed_B, st.initial_seed_cap, B_); st2.atoms = dict(st.atoms); st2.version = st.version
    kw2 = dict(expected_identity=st.model_identity) if kernel_accepts_identity() else {}
    k2 = CR.local_kernel(st2, w, w['atoms'], prop.conds, None, cards, prop.order, clk, want_rho=False, **kw2); res['other_identity'] = dict(accepted=bool(k2.get('ok')), why=(k2.get('why') or '')[:120])
    S._close('probe'); res['present'] = bool(res['tampered_above_one']['accepted'] or res['other_identity']['accepted']); return res


# ---- R2: a certificate check after the activation's hard clock
def R2():
    model, _ = CORE.read_uai(MODELS['n6']); M, order, clk, B = stage(model); S, B_, r = rstream(M, allow=30.0); assert r == 'READY', (r, S.closed_reason); S.pilot_action(PA.tnow() + 20); att = S.optimize_action(PA.tnow() + 20, PA.tnow() + 60)
    res = dict(optimize_status=att.get('status'), activation_pending=S.activation_pending)
    if not S.activation_pending: res['present'] = None; res['note'] = 'no changed law committed: the activation path could not be exercised'; S._close('probe'); return res
    real = RS.tnow; shift = [0.0]; RS.tnow = lambda: real() + shift[0]; hard = real() + 5.0; calls = []; orig_batch = S.batch; orig_check = S.check
    def batch(*a_, **k_):
        r_ = orig_batch(*a_, **k_); shift[0] = 1000.0; return r_                                             # the clock crosses the activation's hard deadline right after the first committed batch
    def check():
        calls.append(RS.tnow() >= hard); return orig_check()
    S.batch = batch; S.check = check
    try: act = S.activation_action(hard)
    finally: RS.tnow = real; S.batch = orig_batch; S.check = orig_check
    res.update(activation=dict(status=act.get('status'), batches=act.get('batches'), checks=act.get('checks'), late_checks_skipped=act.get('late_checks_skipped')), checks_after_deadline=sum(1 for c in calls if c), present=any(calls)); S._close('probe'); return res


# ---- R3: unbounded per-batch records outside the ledger
def R3():
    model, _ = CORE.read_uai(MODELS['n6']); M, order, clk, B = stage(model); S, B_, r = rstream(M, allow=60.0); assert r == 'READY', (r, S.closed_reason)
    n0 = len(S.measurements); p0 = len(S.batch_pins); t_end = PA.tnow() + 30
    for _ in range(300):
        rr = S.batch(t_end, t_end)
        if rr != 'COMMITTED': break
    def deep(o, seen=None):
        seen = seen if seen is not None else set()
        if id(o) in seen: return 0
        seen.add(id(o)); s = sys.getsizeof(o)
        if isinstance(o, dict): s += sum(deep(k, seen) + deep(v, seen) for k, v in o.items())
        elif isinstance(o, (list, tuple, set)): s += sum(deep(x, seen) for x in o)
        return s
    meas = [m for m in S.measurements if m.get('kind') == 'joint_batch']; b_meas = deep(meas); b_pins = deep(S.batch_pins)
    res = dict(batches=S.batches, measurements_total=len(S.measurements), batch_measurements=len(meas), batch_pins=len(S.batch_pins), bytes_batch_measurements=b_meas, bytes_batch_pins=b_pins, aggregated_records=sum(1 for m in meas if m.get('aggregated')), ledger_bytes=S.joint_bytes + getattr(S, 'bank_bytes', 0))
    res['present'] = bool((b_meas + b_pins) > (64 << 10) or len(meas) > 100); S._close('probe'); return res


# ---- R4: the bank limits after a committed transaction
def R4():
    model, _ = CORE.read_uai(MODELS['n32er']); M, order, clk, B = stage(model); S, B_, r = rstream(M, allow=40.0); assert r == 'READY', (r, S.closed_reason); S.pilot_action(PA.tnow() + 20); st = S.state
    before = dict(live_atoms=len(st.live_atoms()), entries=st.entries(), bytes=st.bytes_live()); saved = RB.BANK_MAX_ENTRIES; RB.BANK_MAX_ENTRIES = before['entries'] + 16384              # a declared entry limit the replacement atom (a 65,536-cell region) must violate unless the transaction enforces it
    try: att = S.optimize_action(PA.tnow() + 25, PA.tnow() + 60)
    finally: limit_used = RB.BANK_MAX_ENTRIES; RB.BANK_MAX_ENTRIES = saved
    tx = att.get('transaction') or {}
    after = dict(live_atoms=len(st.live_atoms()), entries=st.entries(), bytes=st.bytes_live(), version=st.version); over = dict(atoms=after['live_atoms'] > RB.BANK_MAX_ATOMS, entries=after['entries'] > limit_used, bytes=after['bytes'] > RB.BRANCH_CAP_BYTES)
    res = dict(optimize_status=att.get('status'), refusal_kind=att.get('kind'), transaction_kind=tx.get('kind'), window_vol=(tx.get('window') or {}).get('vol'), evicted_for_bank_limits=tx.get('evicted_for_bank_limits'), before=before, after=after, limits=dict(atoms=RB.BANK_MAX_ATOMS, entries_declared_for_probe=limit_used, bytes=RB.BRANCH_CAP_BYTES), over=over)
    if att.get('status') == 'PROMOTED': res['present'] = any(over.values())                                                                  # committed: the bank must respect the declared limits afterwards
    elif att.get('status') == 'REFUSED' and att.get('kind') == 'MEMORY_POLICY': res['present'] = False                                           # the repaired stream refused the over-limit transaction typed
    else: res['present'] = None; res['note'] = 'no transaction committed and no typed limit refusal in this run: inconclusive'
    S._close('probe'); return res


# ---- R5: actual workspace peak vs the admitted estimate (65,536-cell window, 16 atoms)
def R5():
    import dgp7_rates as R7
    rng = random.Random(11); card = 4; n_out = 2; n = 10; cards = [card] * n; order = list(range(n)); pos = {v: i for i, v in enumerate(order)}; Rc = order[n_out:]; A = Rc[-2:]; others = Rc[:-2]
    conds_old = {}; targets = {}
    for v in order:
        earlier = order[:pos[v]]; pool = [x for x in earlier if x in Rc] or earlier; par_old = tuple(sorted(rng.sample(pool, min(len(pool), rng.randint(0, 2))), key=lambda x: pos[x])) if pool else (); conds_old[v] = R7.rand_cond(rng, v, par_old, cards)
        if v in A:
            extra = [w for w in pool if w not in par_old]; targets[v] = tuple(sorted(par_old + ((rng.choice(extra),) if extra and JP.vol_of(par_old, cards) * card * card <= 4096 else ()), key=lambda x: pos[x]))
    prop = JP.Proposal(cards, conds_old, order, RB.one_compact(), RB.one_compact(), dict(kind='probe')); atoms = []
    for j in range(16):
        axes = {A[j % 2], others[j % len(others)]}
        if j % 3 == 0: axes.add(others[(j // 3) % len(others)])
        atoms.append(R7.rand_atom(rng, tuple(sorted(axes)), cards, j, 0))
    R = set(A)
    for v in A: R |= set(conds_old[v].parents) | set(targets[v])
    for at in atoms: R |= set(at.axes)
    assert R == set(Rc), (sorted(R), Rc)
    Rs = sorted(R, key=lambda x: pos[x]); C = [x for x in Rs if x not in A]; vol = JP.vol_of(tuple(Rs), cards)
    state = RB.ResidualState('probe', 'probe', prop, prop.B, prop.B, prop.B, CE.Budget(CE.CONSTRUCTOR_BYTES))
    for at in atoms: at.verified = True; state.atoms[at.aid] = at
    window = dict(A=list(A), R=list(Rs), C=list(C), atoms=[at.aid for at in atoms], vol=vol, bank_version=0, target_parents={v: targets[v] for v in A}, max_vol=65536, whole_model_region=(len(Rs) == n), score=1.0, predicted_work_s=0.0, model_identity=state.model_identity, seed_proof_identity=state.seed_proof_identity, law_identity=state.law_identity)
    clk = CE.Clock(PA.tnow() + 600, {}); rng_np = np.random.default_rng(5)
    tracemalloc.start(); tracemalloc.reset_peak(); b0 = tracemalloc.get_traced_memory()[0]; fit = RL.fit_window(prop, window, atoms, cards, order, 'auto', rng_np, 1.1, clock=clk); peak_fit = tracemalloc.get_traced_memory()[1] - b0
    conds_new = fit.get('conds_new') if fit.get('status') == 'CANDIDATE' else None; fit_status = fit.get('status'); del fit
    tracemalloc.reset_peak(); b1 = tracemalloc.get_traced_memory()[0]; kw = dict(expected_identity=state.model_identity) if kernel_accepts_identity() else {}; k = CR.local_kernel(state, window, [at.aid for at in atoms], conds_old, conds_new, cards, order, clk, want_rho=True, **kw); peak_kernel = tracemalloc.get_traced_memory()[1] - b1; tracemalloc.stop()
    nR = len(Rs); est_counts = sum(JP.COUNT_BYTES * JP.vol_of(tuple(targets[v]), cards) * cards[v] + 256 for v in A)
    if hasattr(RS, 'window_workspace_estimate'): est_float, est_kernel, total = RS.window_workspace_estimate(vol, nR, len(atoms), est_counts); formula = 'residual_stream.window_workspace_estimate (max of the two lifetimes + counts)'
    else: est_float = 8 * vol * (nR + 12) + 65536; est_kernel = JP.ENTRY_BYTES * vol * 3 + 4096 * len(atoms); total = est_float + est_kernel + est_counts; formula = 'the DGP7 inline formula (8 vol (nR + 12) + 64 KiB; ENTRY_BYTES vol 3 + 4 KiB per atom; charged as the SUM)'
    res = dict(vol=vol, nR=nR, atoms=len(atoms), fit_status=fit_status, kernel_ok=k.get('ok'), kernel_why=(k.get('why') or '')[:80], peak_fit_bytes=peak_fit, peak_kernel_bytes=peak_kernel, est_float=est_float, est_kernel=est_kernel, est_total=total, formula=formula, ratio_fit=(peak_fit / est_float), ratio_kernel=(peak_kernel / est_kernel), ratio_peak_over_admitted=(max(peak_fit, peak_kernel) / total))
    res['present'] = bool(peak_fit > est_float or peak_kernel > est_kernel); return res


# ---- R6: the same-law pass on a window planned with a G1 target-only parent
def R6():
    import dgp7_rates as R7
    rng = random.Random(3); card = 2; n = 10; cards = [card] * n; order = list(range(n)); pos = {v: i for i, v in enumerate(order)}; A = [8, 9]
    conds_old = {}
    for v in order:
        earlier = order[:pos[v]]; par = tuple(sorted(rng.sample(earlier, min(len(earlier), 2)), key=lambda x: pos[x])) if earlier else (); conds_old[v] = R7.rand_cond(rng, v, par, cards)
    prop = JP.Proposal(cards, conds_old, order, RB.one_compact(), RB.one_compact(), dict(kind='probe')); at = R7.rand_atom(rng, (7, 9), cards, 0, 0); at.verified = True
    base = set(A) | set(conds_old[8].parents) | set(conds_old[9].parents) | set(at.axes); x = max([v for v in order if pos[v] < pos[A[0]] and v not in base], key=lambda v: pos[v])        # the G1 target-only parent of variable 8
    targets = {8: tuple(sorted(conds_old[8].parents + (x,), key=lambda v: pos[v])), 9: tuple(conds_old[9].parents)}
    R_plan = sorted(base | {x}, key=lambda v: pos[v])                                                                                                   # what plan_windows declares (A + old / TARGET parents + atom scopes)
    state = RB.ResidualState('probe', 'probe', prop, prop.B, prop.B, prop.B, CE.Budget(CE.CONSTRUCTOR_BYTES)); state.atoms[at.aid] = at
    w = dict(A=list(A), R=R_plan, C=[v for v in R_plan if v not in A], atoms=[at.aid], vol=JP.vol_of(tuple(R_plan), cards), bank_version=0, target_parents=targets, max_vol=65536, whole_model_region=False, score=1.0, predicted_work_s=0.0, model_identity=state.model_identity, seed_proof_identity=state.seed_proof_identity, law_identity=state.law_identity)
    clk = CE.Clock(PA.tnow() + 60, {}); kw = dict(expected_identity=state.model_identity) if kernel_accepts_identity() else {}
    k_raw = CR.local_kernel(state, w, w['atoms'], conds_old, None, cards, order, clk, want_rho=False, **kw); res = dict(target_only_parent=x, planned_R=R_plan, raw_same_law_pass=dict(ok=k_raw.get('ok'), why=(k_raw.get('why') or '')[:140]))
    if hasattr(RS, 'same_law_window'):
        w2 = RS.same_law_window(w, prop, state, cards, order, RL.PROFILE_RESIDUAL); k2 = CR.local_kernel(state, w2, w2['atoms'], conds_old, None, cards, order, clk, want_rho=False, **kw) if w2 is not None else dict(ok=False, why='region cap')
        res['same_law_window'] = dict(ok=k2.get('ok'), why=(k2.get('why') or '')[:140], R=(w2 or {}).get('R')); res['present'] = not bool(k2.get('ok'))
    else: res['same_law_window'] = None; res['present'] = (not bool(k_raw.get('ok'))) and ('region' in (k_raw.get('why') or ''))
    return res


# ---- R7: the scheduling calibration check (a control + a runtime record)
def R7():
    import check_dgp as C
    src = inspect.getsource(RS); has_ctrl = any(c.__name__.startswith('D71') for c in C.CONTROLS); has_runtime = ('actual_over_predicted' in src) and ('forecast_underestimates' in src)
    return dict(control_D71=has_ctrl, runtime_record=has_runtime, present=not (has_ctrl and has_runtime))


for name, fn in (('R1_bank_identity_range', R1), ('R2_post_deadline_publication', R2), ('R3_retained_object_accounting', R3), ('R4_over_cap_banks', R4), ('R5_underestimated_workspace', R5), ('R6_same_law_region_mismatch', R6), ('R7_scheduling_calibration_check', R7)):
    if a.only and name.split('_')[0] not in a.only.split(','): continue
    probe(name, fn)
out['n_present'] = sum(1 for v in out['findings_present'].values() if v); out['n_absent'] = sum(1 for v in out['findings_present'].values() if v is False); out['n_inconclusive'] = sum(1 for v in out['findings_present'].values() if v is None)
json.dump(out, open(a.output, 'w'), indent=1, default=str); print(json.dumps(dict(present=out['findings_present'], n_present=out['n_present'], n_inconclusive=out['n_inconclusive'])))
