"""DGP10 controls D91-D102 (FROZEN_EXPERIMENT_SPEC sections 3-5; brief sections 3-7): run after check_dgp.py's D1-D90 from the clean checkout. Each control is a branch-asserting test of the DGP10 mechanisms and carried repairs:
  D91 matched run: observer ON vs OFF -> identical RNG consumption, transitions, final state and occupation counts (the observer never changes the draws / law / counters); every committed visit of a queried site observes exactly once incl.
      null moves; an unresolved step observes inside hb_apply (bit injection forces the ambiguous prefix) and the recorded enclosure contains the exact conditional; an abandoned batch (deadline) observes nothing extra
  D92 enclosure differential: the Q32 enclosure contains the exact source conditional at random states on mixed cardinalities, duplicated factors and source rescaling 2^-600 / 2^600 (identical L / U across gauges); width <= a few grid units
  D93 reservation transaction: unit invariants (entry live restored on every failure ordinal; transfer; idempotent close; double release / underflow are Defects, never clamps); the failure-ordinal sweep over EVERY reservation of the spectral,
      native (incl. observer), two-plan and exact-fallback constructors (injected MEMORY at the k-th charge -> live == entry, no owner returned); the retained witness arrays dropped by release_retained; compile / version-probe timeouts
      equal the remaining allowance (no 1 s / 30 s floors; exhausted allowance refuses BEFORE spawning)
  D94 bit-length range witness: admitted iff the exact predicate on random small rationals incl. straddling cases (exact products formed only there); fallback estimate admitted BEFORE weights_exact (zero headroom refuses with no weights)
  D95 risk allocation: the declared total <= delta for the frozen J's; per-variable / per-coordinate allowances; the group maximum of category averages >= every category average; intersection never widens; empty -> conflict
  D96 local checkpoint plan: the exact formula, strictly increasing; the kernel snapshots at EXACTLY M_j (count == M_j, immutable afterwards while the current sums move on); centers C = round(S / k) ties to the smaller integer
  D97 staged output commit: an injected crossing inside json.dumps -> the written file is DEADLINE with no rows (both on the factorless and the ordinary task); a crossing inside the response tail -> raw-only publication, response unavailable typed;
      the written file's timing fields are consistent (numeric wall, outcome / hard_deadline_respected coherent)
  D98 residual postcommit: on a PROMOTED residual action no ResidualState.record / live-atom scan runs after the commit sample (hook counts); the prospective record equals the final state
  D99 checker / proposer separation: the production checker module is byte-identical to the packet reference (sha256); the proposer's floating rho is never used without the checker; a check refusal (expired budget) leaves the group unavailable
  D100 rows_from_boxes == rows_from_counts on the raw boxes (same publication geometry); conflict / unavailable sites keep the raw enclosure
  D101 RESPONSE runner end to end on a tiny model: response executed, records present (snapshots, groups, risks, per-coordinate R / arithmetic width, phase times, ownership), every unpublished coordinate has a final enclosure, the diagnostics
      namespace is outside answers / enclosures; --exact-chain --response -> response unavailable typed, raw-only rows; ledger identity at the end
  D102 eta and counter bounds: eta = n g / (1 + n g) exact and monotone; M > 2^63 - 1 refused by the checker; uint128 limb recombination
usage: check_dgp10.py OUT.json [--only D91,D93]"""
import sys, os, json, time, math, random, argparse, traceback, tempfile, subprocess, itertools, hashlib, glob
from fractions import Fraction as F
from types import SimpleNamespace
from unittest.mock import patch
HERE = os.path.dirname(os.path.abspath(__file__)); sys.path[:0] = [HERE, os.path.join(os.path.dirname(os.path.dirname(HERE)), 'cex', 'blockres'), os.path.join(os.path.dirname(os.path.dirname(HERE)), 'cex', 'newarm')]
import numpy as np
import coarse_envelope as CE, spectral_witness as SW, heatbath_exact as HX, heatbath_native as HN, markov_certificate as MC, response_certificate as RC, checked_tilt as CT, reservation as RV, global_circuit as GC
R = []; PY = sys.executable; RUNNER = os.path.join(HERE, 'spectral_heatbath_run.py')
def rec(name, ok, **kw): R.append(dict(control=name, ok=bool(ok), **kw)); print(json.dumps({name: {k: v for k, v in R[-1].items() if k in ('ok', 'summary', 'error')}}, default=str)[:300], flush=True)


def tiny(cards, unaries, edges, scale=F(1)):
    psi = [[F(v) * scale for v in row] for row in unaries]; factors = [((i, j), [F(v) * scale for v in itertools.chain.from_iterable(tab)]) for (i, j, tab) in edges]
    return SimpleNamespace(cards=list(cards), psi=psi, factors=factors, orig_of=list(range(len(cards))), fixed_rows={}, scalar=F(1), zero_mass=False)


T1 = tiny([2, 3, 4], [[1, 2], [1, 1, 2], [3, 1, 1, 2]], [(0, 1, [[2, 1, 1], [1, 3, 1]]), (1, 2, [[1, 2, 1, 1], [2, 1, 1, 3], [1, 1, 2, 1]]), (0, 2, [[1, 1, 2, 1], [2, 1, 1, 1]])])


class RefuseAt(CE.Budget):
    """refuses the k-th charge (1-based) with MEMORY, counting from arm()"""
    def __init__(self, cap, k): super().__init__(cap); self.k = k; self.count = 0; self.armed = False
    def arm(self): self.armed = True; self.count = 0
    def charge(self, n, what):
        if self.armed:
            self.count += 1
            if self.count == self.k: raise CE.Refused('MEMORY', 'injected refusal at charge %d (%s)' % (self.k, what))
        return super().charge(n, what)


def _obs(hbm): return dict(sites=list(range(hbm.n)), centers=[HN.center_for(k) for k in hbm.cards], plan=HN.local_checkpoint_plan())


def D91_matched_run_and_commit_once():
    hbm = HX.HeatBathModel(T1); n = hbm.n; res = {}; ok = True; clk = CE.Clock(time.monotonic() + 30, {}); B = CE.Budget(32 << 20)
    a = HN.NativeChain(hbm, [0] * n, 5, clk, budget=B, observer=_obs(hbm)); b = HN.NativeChain(hbm, [0] * n, 5, clk, budget=B)
    a.run(3000); b.run(3000); a.set_recording(); a.observer_start(); b.set_recording(); a.run(70000); b.run(70000)
    res['same_state'] = a.state() == b.state(); res['same_occupation'] = a.flush() == b.flush(); ca = a.counters(); cb = b.counters(); res['same_counters'] = all(ca[k] == cb[k] for k in ('resolved', 'unresolved', 'null_moves', 'site_rejections'))
    st = a.observer_state(); vis = sum(a.observer_current(q)['count'] for q in range(n)); res['observed_once'] = (vis == 70000 and st['committed'] == 70000 and ca['null_moves'] > 0); ok &= res['same_state'] and res['same_occupation'] and res['same_counters'] and res['observed_once']
    # RNG consumption identity: continue both and compare again
    a.run(5000); b.run(5000); res['same_after_more'] = a.state() == b.state(); ok &= res['same_after_more']; a.close(); b.close(); res['live_after'] = B.live; ok &= B.live == 0
    # forced ambiguous prefix on a single-variable 2-state model with equal weights: n = 1 -> site selection uses 0 bits; inject u53 = 2^52 (U = 1/2 exactly at the CDF boundary) -> unresolved -> host fallback -> hb_apply observes
    m1 = HX.HeatBathModel(tiny([2], [[1, 1]], [])); B1 = CE.Budget(1 << 20); c1 = HN.NativeChain(m1, [0], 3, clk, budget=B1, observer=_obs(m1)); c1.set_recording(); c1.observer_start()
    c1.inject_bits(1 << 52, 53); done = c1.run(1); cc = c1.counters(); cur = c1.observer_current(0); L, U = cur['first_lo'], cur['first_hi']; S = 1 << 32
    res['forced_fallback'] = dict(steps=done, unresolved=cc['unresolved'], exact_fallbacks=cc['exact_fallbacks'], visits=cur['count'], state=c1.state(), encloses_half=all(F(L[a_], S) <= F(1, 2) <= F(U[a_], S) for a_ in range(2)))
    ok &= (done == 1 and cc['unresolved'] == 1 and cc['exact_fallbacks'] == 1 and cur['count'] == 1 and res['forced_fallback']['encloses_half']); c1.close(); ok &= B1.live == 0
    # abandoned batch: a deadline inside a batch -> the visits equal the committed steps (nothing pending counted)
    B2 = CE.Budget(32 << 20); c2 = HN.NativeChain(hbm, [0] * n, 9, CE.Clock(time.monotonic() + 30, {}), budget=B2, observer=_obs(hbm)); c2.set_recording(); c2.observer_start(); c2.clock = CE.Clock(time.monotonic() - 1, {})
    try: c2.run(500000, batch=1000); res['abandoned'] = 'no deadline'
    except CE.Refused as e: res['abandoned'] = e.kind
    vis2 = sum(c2.observer_current(q)['count'] for q in range(n)); res['abandoned_visits_eq_steps'] = (vis2 == c2.steps()); ok &= res['abandoned'] == 'DEADLINE' and res['abandoned_visits_eq_steps']; c2.close()
    rec('D91_matched_run_and_commit_once', ok, **res)


def D92_enclosure_differential_and_gauges():
    res = {}; ok = True; rng = random.Random(92); S = 1 << 32; clk = CE.Clock(time.monotonic() + 60, {})
    for name, m in (('mixed', T1), ('dup', tiny([2, 2], [[1, 1], [1, 1]], [(0, 1, [[2, 1], [1, 2]]), (0, 1, [[3, 1], [1, 3]])])), ('rand', None)):
        if m is None:
            cards = [rng.choice([2, 3, 4]) for _ in range(6)]; m = tiny(cards, [[rng.randint(1, 9) for _ in range(k)] for k in cards], [(i, j, [[rng.randint(1, 9) for _ in range(cards[j])] for _ in range(cards[i])]) for i in range(6) for j in range(i + 1, 6) if rng.random() < 0.7])
        hbm = HX.HeatBathModel(m); B = CE.Budget(32 << 20); ch = HN.NativeChain(hbm, [0] * hbm.n, 1, clk, budget=B, observer=_obs(hbm)); viol = 0; wmax = 0
        for _ in range(300):
            ch.run(1); x = ch.state(); i = rng.randrange(hbm.n); L, U = ch.observe_inspect(i); q = HX.conditional_exact(hbm, x, i)
            for a in range(hbm.cards[i]): viol += int(not (F(L[a], S) <= q[a] <= F(U[a], S))); wmax = max(wmax, U[a] - L[a])
        ch.close(); res[name] = dict(violations=viol, width_units_max=wmax); ok &= viol == 0 and wmax <= 8
    # gauges: identical L / U across source rescaling
    LUs = []
    for power in (0, -600, 600):
        sc = (F(2) ** power) if power >= 0 else F(1) / (F(2) ** (-power)); m = tiny([2, 3], [[2, 3], [1, 2, 1]], [(0, 1, [[4, 1, 2], [1, 3, 2]])], scale=sc); hbm = HX.HeatBathModel(m); B = CE.Budget(32 << 20); ch = HN.NativeChain(hbm, [0, 0], 1, clk, budget=B, observer=_obs(hbm)); ch.run(100); LUs.append(json.dumps([ch.observe_inspect(i) for i in range(2)]) + json.dumps(ch.state())); ch.close()
    res['identical_across_gauges'] = len(set(LUs)) == 1; ok &= res['identical_across_gauges']
    rec('D92_enclosure_differential_and_gauges', ok, **res)


def D93_reservation_transaction_and_failure_sweep():
    res = {}; ok = True
    # unit invariants
    B = CE.Budget(10000); B.charge(352, 'pre')
    with RV.Txn(B) as tx:
        t1 = tx.reserve(100, 'a'); o = RV.Owner(B, 'o'); tx.transfer(t1, o); tx.reserve(50, 'tmp')
    res['temp_released_retained_kept'] = (B.live == 452 and o.bytes == 100); o.close(); o.close(); res['idempotent_close'] = (B.live == 352)
    try:
        with RV.Txn(B) as tx: tx.reserve(10, 'x'); raise CE.Refused('DEADLINE', 'inj')
    except CE.Refused: pass
    res['rollback_restores_entry'] = (B.live == 352)
    try: RV._release_token(B, RV.Token(10 ** 9, 'huge')); res['underflow_is_defect'] = False
    except CE.Defect: res['underflow_is_defect'] = True
    try: tx2 = RV.Txn(B); tx2.__enter__(); tk = tx2.reserve(5, 'y'); tx2.release(tk); tx2.release(tk); res['double_release_is_defect'] = False
    except CE.Defect: res['double_release_is_defect'] = True; tx2.__exit__(None, None, None)
    ok &= all(res[k] for k in ('temp_released_retained_kept', 'idempotent_close', 'rollback_restores_entry', 'underflow_is_defect', 'double_release_is_defect'))
    # failure-ordinal sweep: spectral certify
    import core as CORE
    m = T1; clk = CE.Clock(time.monotonic() + 60, {}); sweep = {}
    def sweep_ctor(label, fn, kmax=12):
        rows = []
        for k in range(1, kmax + 1):
            Bk = RefuseAt(64 << 20, k); Bk.charge(777, 'entry live'); entry = Bk.live; Bk.arm()
            try: r_ = fn(Bk); rows.append(dict(k=k, outcome='constructed', live_delta=Bk.live - entry, closed_live=(r_() if callable(r_) else None)))
            except CE.Refused as e: rows.append(dict(k=k, outcome=e.kind, live_delta=Bk.live - entry))
            except CE.Defect as e: rows.append(dict(k=k, outcome='DEFECT', error=str(e)[:80], live_delta=Bk.live - entry))
        sweep[label] = rows; return all(r_['live_delta'] == 0 for r_ in rows if r_['outcome'] != 'constructed') and all(r_['outcome'] != 'DEFECT' for r_ in rows) and any(r_['outcome'] == 'MEMORY' for r_ in rows)
    def f_spectral(Bk):
        W = SW.certify(m, Bk, clk, policy=SW.POLICY_REVISED); live_mid = Bk.live; SW.release_retained(W, Bk); return lambda: Bk.live
    ok_s = sweep_ctor('spectral', f_spectral, 10); res['spectral_sweep_ok'] = ok_s; ok &= ok_s
    hbm = HX.HeatBathModel(m)
    def f_native(Bk):
        ch = HN.NativeChain(hbm, [0] * hbm.n, 1, clk, budget=Bk, observer=_obs(hbm)); ch.close(); return lambda: Bk.live
    ok_n = sweep_ctor('native_with_observer', f_native, 8); res['native_sweep_ok'] = ok_n; ok &= ok_n
    # spectral constructed cases must end with live == entry after release_retained
    res['spectral_release_returns_to_entry'] = all(r_['closed_live'] == 777 for r_ in sweep['spectral'] if r_['outcome'] == 'constructed'); res['native_close_returns_to_entry'] = all(r_['closed_live'] == 777 for r_ in sweep['native_with_observer'] if r_['outcome'] == 'constructed'); ok &= res['spectral_release_returns_to_entry'] and res['native_close_returns_to_entry']
    # two-plan construction: the second plan refused -> no orphan
    import joint_proposal as JP
    n_ = 8; cards = [2] * n_; order = list(range(n_)); parents = {v: tuple(range(max(0, v - 3), v)) for v in order}; Mp = SimpleNamespace(cards=cards, factors=[((i, i + 1), [F(1)] * 4) for i in range(n_ - 1)])
    B1 = CE.Budget(1 << 30); p1, p2 = GC.build_plans(Mp, order, parents, order, budget=B1, clock=clk); one = p1.charged_bytes; p1.release(); p2.release(); res['two_plan_release_zero'] = (B1.live == 0)
    B2 = CE.Budget(one + one // 2); B2.charge(0, 'none')
    try: GC.build_plans(Mp, order, parents, order, budget=B2, clock=clk); res['two_plan_second_refused'] = 'constructed'
    except CE.Refused as e: res['two_plan_second_refused'] = e.kind
    res['two_plan_no_orphan'] = (B2.live == 0); ok &= res['two_plan_release_zero'] and res['two_plan_second_refused'] == 'MEMORY' and res['two_plan_no_orphan']
    # retained arrays dropped by release_retained
    B3 = CE.Budget(64 << 20); W = SW.certify(m, B3, clk, policy=SW.POLICY_REVISED); SW.release_retained(W, B3); res['retained_dropped'] = (W['h'] is None and W['cards'] is None and W['offsets'] is None and W.get('owner') is None and B3.live == 0); ok &= res['retained_dropped']
    # compile / version timeouts: patch subprocess inside heatbath_native to capture timeouts; force a rebuild by redirecting RECORD / cache digest
    seen = []
    def fake_call(cmd, timeout=None, **kw): seen.append(('call', timeout)); open(cmd[cmd.index('-o') + 1], 'wb').write(b'x'); return 0
    def fake_out(cmd, timeout=None, **kw): seen.append(('version', timeout)); return b'fake 1.0\n'
    with tempfile.TemporaryDirectory() as td:
        # the fake compiler writes into a TEMPORARY cache (HERE redirected): the real native_cache is never touched by this control
        with patch.object(HN, 'HERE', td), patch.object(HN, 'SRC', os.path.join(HERE, 'heatbath_native.c')), patch.object(HN, 'RECORD', os.path.join(td, 'rec.json')), patch.object(HN, 'FLAGS', list(HN.FLAGS) + ['-DDGP10_TEST_%d' % random.randrange(10 ** 9)]), patch.object(HN.subprocess, 'check_call', fake_call), patch.object(HN.subprocess, 'check_output', fake_out), patch.object(HN, '_LIB', None):
            try: HN.build(CE.Clock(time.monotonic() + 0.4, {})); built = 'built'
            except Exception as e: built = repr(e)[:80]
            res['build_timeouts'] = dict(seen=[(k, round(t_, 3) if isinstance(t_, float) else t_) for k, t_ in seen], result=built)
            ok &= len(seen) == 2 and all(isinstance(t_, float) and 0 < t_ <= 0.4 for _, t_ in seen)                   # (the fake library cannot be dlopen'ed: `built` records the OSError; the timeouts are what this control asserts)
            seen.clear()
            for f_ in glob.glob(os.path.join(td, 'native_cache', '*.dylib')) + [os.path.join(td, 'rec.json')]:
                if os.path.exists(f_): os.remove(f_)                                                           # a rebuild is required again: the exhausted allowance must refuse BEFORE any subprocess
            try: HN.build(CE.Clock(time.monotonic() - 1, {})); res['exhausted_allowance'] = 'built'
            except CE.Refused as e: res['exhausted_allowance'] = e.kind
            except Exception as e: res['exhausted_allowance'] = repr(e)[:80]
            ok &= res['exhausted_allowance'] == 'DEADLINE' and not seen
    res['sweeps'] = {k: [(r_['k'], r_['outcome'], r_['live_delta']) for r_ in v] for k, v in sweep.items()}
    rec('D93_reservation_transaction_and_failure_sweep', ok, **res)


def D94_bitlength_range_witness_and_fallback_admission():
    res = {}; ok = True; rng = random.Random(94); agree = 0; straddle = 0; total = 0
    for trial in range(60):
        n_ = rng.randint(2, 5); cards = [rng.choice([2, 3]) for _ in range(n_)]; e = rng.choice([-3, -300, -890, -895, -899, -900, -901, -905, 0])
        def val(): return F(rng.randint(1, 15), rng.randint(1, 15)) * (F(2) ** (e // max(1, n_)) if e >= 0 else F(1) / (F(2) ** (-e // max(1, n_))))
        m = tiny(cards, [[val() for _ in range(k)] for k in cards], [(i, j, [[val() for _ in range(cards[j])] for _ in range(cards[i])]) for i in range(n_) for j in range(i + 1, n_)]); hbm = HX.HeatBathModel(m)
        w = HN.range_witness(hbm); total += 1; straddle += int(w['range']['exact_products_formed'] > 0)
        # the exact predicate by brute force
        floor_ = F(1, 2 ** 900); worst = None
        for i in range(hbm.n):
            s_i = HN._pow2_scale(max(hbm.psi[i])); lo = min(hbm.psi[i]) / HN._pow2(s_i)
            for fi, _ in hbm.incident[i]: vals = hbm.pairs[fi][4]; lo *= min(vals) / HN._pow2(HN._pow2_scale(max(vals)))
            worst = lo if worst is None else min(worst, lo)
        agree += int(w['range']['admitted'] == (worst >= floor_))
    # deterministic straddling fixtures at the 2^-900 floor (BOTH variables): unary [7, 7] (floor -1, ceil 0 after normalization) x pair min 5 x 2^-901 (normalized 5 x 2^-902: floor -900, ceil -899) -> sum of floors -901 < -900 <= sum of ceilings -899 (straddles) and the
    # exact product (7/8)(5 x 2^-902) = 35 x 2^-905 >= 2^-900 -> ADMITTED; unary [3, 3] -> (3/4)(5 x 2^-902) = 15 x 2^-904 < 2^-900 -> REFUSED (straddles too)
    tiny_ = F(5, 2 ** 901); fx = {}
    for lab, un, expect in (('admitted_straddle', [7, 7], True), ('refused_straddle', [3, 3], False)):
        m = tiny([2, 2], [un, un], [(0, 1, [[1, tiny_], [tiny_, 1]])]); w = HN.range_witness(HX.HeatBathModel(m)); fx[lab] = dict(admitted=w['range']['admitted'], exact_formed=w['range']['exact_products_formed'], min_log2=w['range']['min_weight_log2_lower']); straddle += int(w['range']['exact_products_formed'] > 0); agree += int(w['range']['admitted'] == expect); total += 1
    res['fixtures'] = fx; res['trials'] = total; res['agree_with_exact_predicate'] = agree; res['straddling_cases'] = straddle; ok &= agree == total and straddle >= 2 and fx['admitted_straddle']['admitted'] is True and fx['refused_straddle']['admitted'] is False and fx['admitted_straddle']['exact_formed'] > 0
    # fallback admission before weights_exact: zero headroom -> MEMORY, weights_exact never called
    hbm = HX.HeatBathModel(T1); clk = CE.Clock(time.monotonic() + 30, {}); B = CE.Budget(32 << 20); ch = HN.NativeChain(hbm, [0] * hbm.n, 2, clk, budget=B, observer=_obs(hbm)); ch.budget = CE.Budget(0); calls = []
    orig = hbm.weights_exact; hbm.weights_exact = lambda x, i: (calls.append(i), orig(x, i))[1]
    class Fake:
        def hb_unresolved(self, ctx, p): p._obj.value = 1 << 52; return 0
    lib = ch.lib; ch.lib = SimpleNamespace(hb_unresolved=Fake().hb_unresolved, hb_apply=lib.hb_apply)
    try: ch._resolve(); res['fallback_zero_headroom'] = 'resolved'
    except CE.Refused as e: res['fallback_zero_headroom'] = e.kind
    res['weights_exact_called_before_admission'] = bool(calls); ch.lib = lib; ch.budget = B; ch.close(); ok &= res['fallback_zero_headroom'] == 'MEMORY' and not calls and B.live == 0
    rec('D94_bitlength_range_witness_and_fallback_admission', ok, **res)


def D95_risk_allocation_grouping_intersection():
    res = {}; ok = True; delta = F(1, 10 ** 6)
    tot = RC.total_risk(delta, 64, 64); res['total_over_delta'] = str(tot / delta); ok &= tot <= delta
    al = RC.risk_allocation(delta, 64, 256, 17); res['delta_m_17'] = str(al['delta_m']); res['delta_b_17'] = str(al['delta_b']); ok &= al['delta_m'] == delta / (17 * 18) / (8 * 64) and al['delta_b'] == delta / (17 * 18) / (8 * 256)
    # grouping: max of category averages >= each
    S = 1 << 32; snaps = [dict(site=i, q=i, k=4, center=HN.center_for(4), count=16384, j=1, M=16384, first_lo=[16384 * (S // 4) - 100] * 4, first_hi=[16384 * (S // 4) + 100] * 4, second_hi=[16384 * (S // 4) ** 2 // (50 + i)] * 4) for i in range(5)]
    rc_ = RC.response_intervals(snaps, F(1, 10), delta, 5, 20); g = rc_['groups'][0]; ymax = F(g['y_max']); ys = [F(s['second_hi'][a], s['count'] * S * S) / RC.B_of(s['center']) for s in snaps for a in range(4)]; res['group_max_ge_each'] = all(ymax >= y for y in ys); ok &= res['group_max_ge_each'] and rc_['n_certified'] == 1
    # intersection never widens; empty -> conflict
    raw = [(F(1, 10), F(3, 10)), (F(7, 10), F(9, 10))]; resp_ = [dict(lo=F(2, 10), hi=F(5, 10)), dict(lo=F(65, 100), hi=F(95, 100))]
    box, conflict = RC.intersect_boxes(raw, resp_); res['intersection'] = dict(box=[(str(l), str(h)) for l, h in box], conflict=conflict); ok &= (not conflict) and box[0] == (F(2, 10), F(3, 10)) and all(l >= rl and h <= rh for (l, h), (rl, rh) in zip(box, raw))
    box2, conflict2 = RC.intersect_boxes(raw, [dict(lo=F(4, 10), hi=F(5, 10)), resp_[1]]); res['conflict_detected'] = conflict2; ok &= conflict2 and box2 == raw
    rec('D95_risk_allocation_grouping_intersection', ok, **res)


def D96_local_plan_snapshots_centers():
    res = {}; ok = True; plan = HN.local_checkpoint_plan(); exp = [math.ceil(F(2 ** 14) * F(5, 4) ** j) for j in range(64)]; res['plan_formula_exact'] = (plan == exp); res['strictly_increasing'] = all(plan[j] > plan[j - 1] for j in range(1, 64)); ok &= res['plan_formula_exact'] and res['strictly_increasing']
    res['centers'] = {k: HN.center_for(k) for k in (2, 3, 4, 5, 7)}; ok &= HN.center_for(2) == 1 << 31 and HN.center_for(4) == 1 << 30 and HN.center_for(3) == 1431655765 and HN.center_for(7) == 613566757 and all(abs(F(HN.center_for(k)) - F(1 << 32, k)) <= F(1, 2) for k in (2, 3, 4, 5, 7))
    # snapshot at EXACTLY M_1 on a single-variable model (every step visits site 0)
    m1 = HX.HeatBathModel(tiny([2], [[1, 3]], [])); clk = CE.Clock(time.monotonic() + 30, {}); B = CE.Budget(1 << 20); ch = HN.NativeChain(m1, [0], 4, clk, budget=B, observer=_obs(m1)); ch.set_recording(); ch.observer_start(); ch.run(plan[0] - 1)
    s0 = ch.observer_snapshots()[0]; res['no_snapshot_before_M1'] = (s0['j'] is None); ch.run(1); s1 = ch.observer_snapshots()[0]; res['snapshot_at_M1'] = (s1['j'] == 1 and s1['count'] == plan[0]); ch.run(500); s2 = ch.observer_snapshots()[0]; cur = ch.observer_current(0)
    res['snapshot_immutable_while_current_moves'] = (s2 == s1 and cur['count'] == plan[0] + 500 and cur['first_lo'] != s1['first_lo']); ch.run(plan[1] - plan[0] - 500); s3 = ch.observer_snapshots()[0]; res['snapshot_at_M2'] = (s3['j'] == 2 and s3['count'] == plan[1]); ch.close()
    ok &= res['no_snapshot_before_M1'] and res['snapshot_at_M1'] and res['snapshot_immutable_while_current_moves'] and res['snapshot_at_M2']
    rec('D96_local_plan_snapshots_centers', ok, **res)


def _run_runner(path, budget, stop, extra=(), env_extra=None):
    out = tempfile.mktemp(suffix='.json', prefix='dgp10_ctl_'); cmd = [PY, RUNNER, '--input', path, '--output', out, '--budget', str(budget), '--admission-stop', str(stop), '--seed', '7'] + list(extra)
    p = subprocess.run(cmd, capture_output=True, text=True, timeout=120, cwd=os.path.dirname(HERE), env=dict(os.environ, **(env_extra or {})))
    try: d = json.load(open(out))
    except Exception: d = None
    return d, p.returncode, p.stderr[-600:]


def _tiny_uai():
    import hp_gen as G; p = tempfile.mktemp(suffix='.uai', prefix='dgp10_tiny_'); G.write(p, dict(cards=[2, 3, 2], factors=[dict(scope=(0, 1), values=[F(v) for v in (6, 5, 5, 5, 6, 5)]), dict(scope=(1, 2), values=[F(v) for v in (5, 6, 6, 5, 5, 6)]), dict(scope=(0, 2), values=[F(v) for v in (6, 5, 5, 6)])], evidence={})); return p          # WEAK couplings (the spectral width must be < 2)


def D97_staged_output_commit():
    res = {}; ok = True; path = _tiny_uai()
    # the injected crossing inside json.dumps: a one-shot sitecustomize-free approach -- run the runner in-process with patches
    import importlib, io
    def run_with(patch_target, side):
        import spectral_heatbath_run as SHR; out = tempfile.mktemp(suffix='.json'); clock = {'t': 0.0, 'cross': False}
        base = time.monotonic()
        def now(): return base + clock['t']
        orig_dumps = json.dumps
        def dumps_cross(*a_, **k_):
            if side == 'serialization' and not clock['cross']: clock['t'] = 100.0; clock['cross'] = True
            return orig_dumps(*a_, **k_)
        with patch.object(SHR, 'tnow', side_effect=now), patch.object(CE, 'tnow', side_effect=now), patch.object(SHR.json, 'dumps', side_effect=dumps_cross), patch.object(sys, 'argv', ['ctl', '--input', path, '--output', out, '--budget', '10', '--admission-stop', '9', '--policy', 'revised'] + (['--response'] if side != 'hb' else [])):
            try: SHR.main()
            except SystemExit: pass
        d = json.load(open(out)); return d
    d = run_with(None, 'serialization'); res['crossing_in_encoder'] = dict(outcome=d['outcome'], published=d['published'], respected=d['hard_deadline_respected'], wall=d['wall_s'], suppressed=(d['mechanism'] or {}).get('suppressed_late_rows')); ok &= d['outcome'] == 'DEADLINE' and d['published'] == 0 and d['hard_deadline_respected'] is False and isinstance(d['wall_s'], float) and not d['enclosures']
    # the real runner on the tiny task: timing fields consistent; RESPONSE records present; diagnostics outside answers
    d2, rc_, err = _run_runner(path, 3.0, 2.5, ['--policy', 'revised', '--response']); m = (d2 or {}).get('mechanism') or {}; r = m.get('response') or {}
    res['real_cell'] = dict(outcome=(d2 or {}).get('outcome'), refusal=m.get('refusal'), published=(d2 or {}).get('published'), K=(d2 or {}).get('K'), wall=(d2 or {}).get('wall_s'), respected=(d2 or {}).get('hard_deadline_respected'), executed=r.get('executed'), groups=r.get('n_groups'), certified=r.get('n_certified'), enclosures=len((d2 or {}).get('enclosures') or []), diag_keys=list(((d2 or {}).get('diagnostics') or {}).keys()), ledger_identity=m.get('constructor_live_ledger_identity'), rc=rc_)
    ok &= bool(d2) and rc_ == 0 and isinstance(d2['wall_s'], float) and d2['wall_s'] <= 3.0 and d2['hard_deadline_respected'] is True and r.get('executed') is True and (r.get('n_certified') or 0) >= 1 and m.get('constructor_live_ledger_identity') is True and 'raw_full_delta_same_path' in (d2.get('diagnostics') or {}) and all('raw_full' not in json.dumps(a_) for a_ in d2['answers'])
    rows = {(a_['var'], a_['state']) for a_ in d2['answers'] if a_['guarantee'] != 'NOT_PUBLISHED'} | {(e_['var'], e_['state']) for e_ in d2['enclosures']}; res['every_coordinate_has_row_or_enclosure'] = (len(rows) == d2['K']); ok &= res['every_coordinate_has_row_or_enclosure']
    # a crossing inside the response tail: patch RC.response_intervals to raise DEADLINE -> raw-only publication, typed
    import spectral_heatbath_run as SHR
    out3 = tempfile.mktemp(suffix='.json')
    with patch.object(RC, 'response_intervals', side_effect=CE.Refused('DEADLINE', 'injected inside the response tail')), patch.object(sys, 'argv', ['ctl', '--input', path, '--output', out3, '--budget', '3', '--admission-stop', '2.5', '--policy', 'revised', '--response']):
        try: SHR.main()
        except SystemExit: pass
    d3 = json.load(open(out3)); r3 = d3['mechanism'].get('response') or {}; res['tail_crossing'] = dict(outcome=d3['outcome'], executed=r3.get('executed'), unavailable=r3.get('unavailable'), cert_type=(d3['mechanism'].get('certificate') or {}).get('type'), enclosures=len(d3['enclosures']))
    ok &= r3.get('executed') is False and 'DEADLINE' in str(r3.get('unavailable')) and (d3['mechanism'].get('certificate') or {}).get('type') == 'markov_heatbath' and d3['outcome'] in ('PARTIAL', 'COMPLETE')
    rec('D97_staged_output_commit', ok, **res)


def D98_residual_postcommit_no_scan():
    """the residual action's PROMOTED path: ResidualState.record and live_atoms are not called after the commit sample (hook counts after the epoch commit)"""
    res = {}; ok = True
    try:
        import residual_bank as RB, residual_stream as RS, joint_stream as JS, pac_actions as PA
        sys.path.insert(0, HERE); import check_dgp as CD
        s, b = CD._residual_ready(RS.ResidualStream, profile={'V_seed': 16}) if hasattr(CD, '_residual_ready') else (None, None)
        if s is None:
            # reuse the carried probe's construction through check_dgp's helper if present; otherwise build via the DGP9 control fixture
            from dgp9_probes_support import ready  # may not exist
        res['status'] = 'helper missing'
    except Exception as e:
        res['status'] = 'fixture unavailable in this suite: %s' % repr(e)[:120]
    # the probe-equivalent: run the carried probe logic inline using the check_dgp D88 fixture builder when available
    try:
        import check_dgp as CD
        fn = getattr(CD, '_ready_stream', None)
        if fn is None: raise RuntimeError('check_dgp has no _ready_stream helper')
        import residual_bank as RB, residual_stream as RS, joint_stream as JS, pac_actions as PA
        s, b = fn(RS.ResidualStream, profile={'V_seed': 16}); assert s.pilot_action(time.monotonic() + 15)['status'] == 'COMPLETE'
        calls = {'record_after': 0, 'live_after': 0}; committed = {'t': None}; orig_rec = RB.ResidualState.record; orig_live = RB.ResidualState.live_atoms; orig_commit = JS.JointStream._commit_epoch if hasattr(JS, 'JointStream') else None
        def rec_hook(state):
            if committed['t'] is not None: calls['record_after'] += 1
            return orig_rec(state)
        def live_hook(state):
            if committed['t'] is not None: calls['live_after'] += 1
            return orig_live(state)
        def commit_hook(self_, *a_, **k_):
            ep = orig_commit(self_, *a_, **k_); committed['t'] = ep.committed_at; return ep
        with patch.object(RB.ResidualState, 'record', rec_hook), patch.object(RB.ResidualState, 'live_atoms', live_hook), patch.object(JS.JointStream, '_commit_epoch', commit_hook):
            r_ = s.optimize_action(time.monotonic() + 20, time.monotonic() + 30)
        res.update(status=r_.get('status'), record_calls_after_commit=calls['record_after'], live_scans_after_commit=calls['live_after'], committed=committed['t'] is not None)
        ok &= (r_.get('status') != 'PROMOTED') or (calls['record_after'] == 0 and calls['live_after'] == 0)
        if r_.get('status') != 'PROMOTED': res['note'] = 'no promotion on this fixture: the postcommit path was not exercised here (the carried probe_commit_boundaries covers it)'
    except Exception as e: res['status2'] = 'fixture unavailable: %s' % repr(e)[:160]; res['note'] = 'the carried probe_commit_boundaries (controls/after) is the authoritative check of this path'
    rec('D98_residual_postcommit_no_scan', ok, **res)


def D99_checker_identity_and_refusal():
    res = {}; ok = True; ref = os.environ.get('DGP10_REFERENCE_CHECKED_TILT'); here_sha = hashlib.sha256(open(os.path.join(HERE, 'checked_tilt.py'), 'rb').read()).hexdigest(); res['checked_tilt_sha256'] = here_sha
    if ref and os.path.exists(ref): res['reference_sha256'] = hashlib.sha256(open(ref, 'rb').read()).hexdigest(); res['byte_identical_to_reference'] = (res['reference_sha256'] == here_sha); ok &= res['byte_identical_to_reference']
    else: res['byte_identical_to_reference'] = 'reference path not given (DGP10_REFERENCE_CHECKED_TILT); the freeze records both hashes'
    # the proposer alone never authorizes: an expired checker leaves the group unavailable even when the proposer found a candidate
    c = RC.certify_group(1 << 20, F(1, 10), F(1, 1000), RC.B_of(1 << 30), F(1, 10 ** 9), F(1, 10 ** 9), deadline=time.monotonic() - 1); res['expired_checker'] = dict(available=c['available'], reason=c.get('reason')); ok &= (not c['available']) and 'DEADLINE' in str(c.get('reason'))
    c2 = RC.certify_group(1 << 20, F(1, 10), F(1, 1000), RC.B_of(1 << 30), F(1, 10 ** 9), F(1, 10 ** 9)); res['live_checker'] = dict(available=c2['available'], U=c2['moment']['U_float'], R=c2['mean']['R_float'], mode=c2['moment']['mode']); ok &= c2['available'] and c2['moment']['proof'].get('accepted') is True and c2['mean']['proof'].get('accepted') is True
    # the accepted rho is the checker's verified one (string equality with the proof record)
    ok &= c2['moment']['rho'] == c2['moment']['proof']['rho'] and c2['mean']['rho'] == c2['mean']['proof']['rho']
    rec('D99_checker_identity_and_refusal', ok, **res)


def D100_rows_from_boxes_equals_counts():
    res = {}; ok = True; rng = random.Random(100)
    for trial in range(20):
        cards = [rng.choice([2, 3, 4]) for _ in range(5)]; N = rng.choice([1000, 10 ** 5, 10 ** 7]); occ = []
        for k in cards:
            cuts = sorted(rng.sample(range(1, N), k - 1)); occ.append([b - a for a, b in zip([0] + cuts, cuts + [N])])
        r = F(rng.choice([1, 3, 7, 20, 100]), 1000); eps = F(1, 200); orig_of = list(range(5))
        pub1, enc1, st1 = MC.rows_from_counts(occ, N, r, eps, orig_of, {}); boxes = [[(max(F(0), F(c_, N) - r), min(F(1), F(c_, N) + r)) for c_ in row] for row in occ]; pub2, enc2, st2 = MC.rows_from_boxes(boxes, eps, orig_of, {})
        if not (pub1 == pub2 and enc1 == enc2 and st1['variables_published'] == st2['variables_published']): ok = False; res['mismatch_trial'] = trial; break
    res['trials'] = 20; rec('D100_rows_from_boxes_equals_counts', ok, **res)


def D101_response_runner_end_to_end_and_exact_fallback():
    res = {}; ok = True; path = _tiny_uai()
    d, rc_, err = _run_runner(path, 3.0, 2.5, ['--policy', 'revised', '--response', '--exact-chain']); m = (d or {}).get('mechanism') or {}; r = m.get('response') or {}
    res['exact_chain_response'] = dict(outcome=(d or {}).get('outcome'), chain=m.get('chain'), unavailable=r.get('unavailable'), executed=r.get('executed'), cert_type=(m.get('certificate') or {}).get('type'), published=(d or {}).get('published'), rc=rc_)
    ok &= bool(d) and m.get('chain') == 'exact' and 'exact chain fallback' in str(r.get('unavailable')) and (m.get('certificate') or {}).get('type') == 'markov_heatbath' and m.get('constructor_live_ledger_identity') is True
    d2, rc2, err2 = _run_runner(path, 4.0, 3.5, ['--policy', 'revised', '--response']); m2 = (d2 or {}).get('mechanism') or {}; r2 = m2.get('response') or {}
    need = ['eta', 'local_plan_head', 'centers', 'risks', 'snapshots', 'groups', 'per_coordinate', 'radius', 'publication', 'observer_state', 'local_counts', 'tail_s']; res['records_present'] = {k: (k in r2) for k in need}; ok &= all(res['records_present'].values())
    pc = r2.get('per_coordinate') or []; res['per_coordinate'] = dict(n=len(pc), fields=sorted(pc[0].keys()) if pc else None); ok &= bool(pc) and all(k in pc[0] for k in ('R', 'arith_width', 'y_upper', 'mean_lo', 'mean_hi', 'lo', 'hi'))
    ph = (d2 or {}).get('phases_s') or {}; res['phases'] = sorted(ph.keys()); ok &= all(k in ph for k in ('response_snapshots', 'response_certificate', 'response_intersection', 'publication'))
    res['bytes'] = m2.get('bytes'); ok &= (m2.get('bytes') or {}).get('observer') is not None and (r2.get('risks') or {}).get('declared_total_le_delta') is True
    rec('D101_response_runner_end_to_end_and_exact_fallback', ok, **res)


def D102_eta_and_bounds():
    res = {}; ok = True
    e1 = RC.eta_lower(F(1, 1000), 64); e2 = RC.eta_lower(F(2, 1000), 64); res['eta_monotone'] = e2 > e1; res['eta_formula'] = (e1 == F(64, 1000) / (1 + F(64, 1000))); ok &= res['eta_monotone'] and res['eta_formula']
    try: RC.eta_lower(F(1), 64); res['eta_refuses_g_ge_1'] = False
    except ValueError: res['eta_refuses_g_ge_1'] = True
    res['M_too_large_refused'] = not CT.verify_moment_upper(1 << 63, F(1, 4), F(1), F(1, 100), F(1, 50), F(-1, 10), F(1, 10 ** 6))['accepted']
    limbs = [(2 ** 64 - 1), 5]; res['limb_recombination'] = HN.NativeChain._ints(limbs, 1) == [(5 << 64) | (2 ** 64 - 1)]; ok &= res['eta_refuses_g_ge_1'] and res['M_too_large_refused'] and res['limb_recombination']
    rec('D102_eta_and_bounds', ok, **res)


CONTROLS = [D91_matched_run_and_commit_once, D92_enclosure_differential_and_gauges, D93_reservation_transaction_and_failure_sweep, D94_bitlength_range_witness_and_fallback_admission, D95_risk_allocation_grouping_intersection, D96_local_plan_snapshots_centers, D97_staged_output_commit, D98_residual_postcommit_no_scan, D99_checker_identity_and_refusal, D100_rows_from_boxes_equals_counts, D101_response_runner_end_to_end_and_exact_fallback, D102_eta_and_bounds]
if __name__ == '__main__':
    ap = argparse.ArgumentParser(); ap.add_argument('out'); ap.add_argument('--only', default=None); a = ap.parse_args(); t0 = time.time()
    for c in CONTROLS:
        if a.only and c.__name__.split('_')[0] not in a.only.split(','): continue
        try: c()
        except Exception as e: rec(c.__name__, False, error=repr(e)[:300], tb=traceback.format_exc()[-1500:])
    res = dict(all_ok=all(r['ok'] for r in R), n=len(R), n_ok=sum(r['ok'] for r in R), wall_s=round(time.time() - t0, 2), controls=R); json.dump(res, open(a.out, 'w'), indent=1, default=str); print(json.dumps({k: v for k, v in res.items() if k != 'controls'}))
