"""DGP9 before / after probes of the review's findings (DGP8_INDEPENDENT_REVIEW_2026-11-26.md RV1-RV7; the recovered original DGP7 findings F1-F7). Each probe answers one question with EXPLICIT branch assertions: is the finding
PRESENT in the source tree given by --source? (True on the pinned parent = the frozen DGP8 engine ad20e73; False after the DGP9 repairs). The fixtures are the review's own (reconstructed here with the same values) plus the
stronger variants the brief asks for (underflow / overflow / subnormal-intermediate gauges; ambiguous prefixes that force the exact fallback; large-cancellation permutations; the clipped-interval J-box case; expiry inside the
formerly post-sample diagnostics on ordinary and factorless tasks). The probes feature-detect the repaired API (the parent lacks it) and never depend on campaign labels.
  RV1 native range: the uniform scaled triangle (1e-200 entries) through the full standalone runner publishes rows excluding 1/2 (present) or every published row contains 1/2 (absent); the 2^-600 / 2^600 / subnormal-intermediate gauges
      give identical sample paths and exact-conditional agreement (absent) or absorbing states (present); a one-table 2^+-600 range is refused NATIVE_RANGE before any commit (absent) or admitted (present)
  RV2 spectral source enclosure: 256 pairs of pointwise-inverse factors exclude the exact zero (present) or contain it (absent); the 10,000 + 10,000 + 1 false-admission fixture is admitted with width < 2 (present) or refused (absent);
      ordering permutations of the same factor list give identical enclosures (absent)
  RV3 original DGP7 F1-F5 + F4c: duplicate atom ids accepted with cap 1 vs required 2 (present) or rejected before arithmetic with no atom mutated (absent); rho = 3/2 accepted by both checkers (present) or rejected (absent); the batch /
      epoch / residual commits at an injected clock past the deadline (present) or refused / stamped from one sample (absent); extraction projects 133,120 entries over the 131,072 cap after one eviction (present) or fits after repeated
      eviction (absent); the released residual law stays reachable (present) or is cleared (absent); an expired plan allocates before its first poll (present) or polls at entry (absent)
  RV4 publication: counts [1, 998, 1] / N 1000 / r 0.007 publish raw points with endpoint radius 0.007 > eps (present) or epsilon-safe points (absent)
  RV5 runner contracts: the canonical scalar 2000 is missing from the original-Z enclosure (present) or restored (absent); an early MEMORY refusal returns K = 0 (present) or the full inventory (absent); a crossing injected inside the
      resource diagnostic returns COMPLETE with rows (present) or DEADLINE with none (absent), on a factorless and an ordinary task
  RV6 ownership: the witness returns with a live process-global cache / uncharged retained arrays (present) or a request-scoped charged cache and a declared retained charge released by the owner (absent); the native constructor stages
      ctypes copies before refusing at zero headroom (present: traced peak > 1 MB) or refuses after the range witness with a small traced peak (absent)
  RV7 replay: a requested absent rate file falls back to the default rate (present) or is a typed RATE_MODEL_MISSING failure with exit code 3 (absent)
usage: dgp9_probes.py --source ROOT --output OUT.json [--only RV1,RV3,...]"""

# Source-checkout entry point; production imports never traverse research.
if __package__ in (None, ""):
    import sys as _research_sys
    from pathlib import Path as _ResearchPath
    _research_sys.path.insert(0, str(_ResearchPath(__file__).resolve().parents[3]))
from research.bootstrap import activate as _activate_research
_activate_research()
from research.paths import repo_root as _repo_root, runs_root as _runs_root, records_root as _records_root, source_path as _source_path
import sys, os, json, time, math, argparse, tracemalloc, inspect, subprocess, itertools
from fractions import Fraction as F
from types import SimpleNamespace
from unittest.mock import patch
ap = argparse.ArgumentParser(); ap.add_argument('--source', required=True); ap.add_argument('--output', required=True); ap.add_argument('--only', default=None); a = ap.parse_args()
from research.probe_binding import bind_source as _bind_probe_source
a.source = _bind_probe_source(a.source, 'dgp9_probes.py')
SRC = os.path.abspath(a.source); HP = str(_repo_root() / 'research/campaigns/hp')
import numpy as np
import pgm.algorithms.quotient.coarse_envelope as CE, pgm.algorithms.response.spectral_witness as SW, pgm.algorithms.response.heatbath_exact as HX, pgm.algorithms.response.heatbath_native as HN, pgm.algorithms.response.markov_certificate as MC
import pgm.algorithms.quotient.joint_proposal as JP, pgm.algorithms.quotient.residual_bank as RB, pgm.algorithms.quotient.check_residual as CR, pgm.algorithms.quotient.check_joint as CJ, pgm.algorithms.quotient.residual_max_envelope as RM, pgm.algorithms.quotient.global_circuit as GC, pgm.algorithms.quotient.check_global as CG, pgm.algorithms.quotient.joint_stream as JS, pgm.algorithms.quotient.residual_stream as RS, pgm.algorithms.quotient.pac_actions as PA, research.campaigns.hp.check_dgp as C
from pgm.algorithms.quotient.unified_pac_planner import PAC_OPTS
RUNNER = _source_path('pgm.algorithms.response.spectral_heatbath_run'); PY = sys.executable; OUT_DIR = os.path.dirname(os.path.abspath(a.output)); R = {}
REPAIRED_API = dict(native_range=hasattr(HN, 'normalize_tables'), witness_cache=hasattr(SW, 'LogCache'), release_retained=hasattr(SW, 'release_retained'), policy=('--policy' in open(RUNNER).read()), plan_release=hasattr(GC.CircuitPlan, 'release'))


def probe(name, fn):
    t0 = time.monotonic()
    try: r = fn(); r['present'] = bool(r.get('present')); r['error'] = None
    except Exception as e:
        import traceback; r = dict(present=None, error=repr(e)[:300], tb=traceback.format_exc()[-1200:])
    r['seconds'] = time.monotonic() - t0; R[name] = r; print(json.dumps({name: {k: v for k, v in r.items() if k in ('present', 'error', 'seconds', 'summary')}}, default=str)[:400], flush=True)


def run_runner(path, budget, stop, extra=()):
    out = os.path.join(OUT_DIR, 'probe_run_%d.json' % (abs(hash((path, budget, tuple(extra)))) % 10 ** 8)); p = subprocess.run([PY, RUNNER, '--input', path, '--output', out, '--budget', str(budget), '--admission-stop', str(stop), '--seed', '1'] + list(extra), capture_output=True, text=True, timeout=120)
    return (json.load(open(out)) if os.path.exists(out) else None), p.returncode, (p.stderr or '')[-400:]


def tri_uai(entry):
    p = os.path.join(OUT_DIR, 'probe_tri_%s.uai' % str(entry).replace('/', '_').replace('*', 'x').replace('-', 'm')); open(p, 'w').write('MARKOV\n3\n2 2 2\n3\n2 0 1\n2 0 2\n2 1 2\n' + ''.join('4\n' + ' '.join([entry] * 4) + '\n' for _ in range(3))); return p


# ---------------------------------------------------------------- RV1
def RV1():
    r = {}
    d, rc, err = run_runner(tri_uai('1e-200'), 3.0, 2.5); rows = d['answers'] if d else []; bad = [x for x in rows if x['guarantee'] != 'NOT_PUBLISHED' and not (F(x['lo']) <= F(1, 2) <= F(x['hi']))]
    r['full_runner_1e-200'] = dict(outcome=(d or {}).get('outcome'), published=(d or {}).get('published'), wrong_rows=len(bad), chain=((d or {}).get('mechanism') or {}).get('chain'), rc=rc)
    gauges = []
    for power in (0, -600, 600, -500):
        scale = F(2) ** power if power >= 0 else F(1) / (F(2) ** (-power)); mdl = dict(cards=[2, 2, 2], factors=[dict(scope=(i, j), values=[scale] * 4) for i, j in [(0, 1), (0, 2), (1, 2)]], evidence={})
        clk = CE.Clock(time.monotonic() + 20, {}); B = CE.Budget(64 << 20); M = CE.canonicalize(mdl, clk, B); hm = HX.HeatBathModel(M)
        try:
            ch = HN.NativeChain(hm, [0, 0, 0], 1, clk, B); w, lo, hi = ch.inspect(0); ch.set_recording(); ch.run(20000, batch=1000); cnt = ch.flush(); c = ch.counters(); ch.close()
            gauges.append(dict(power=power, admitted=True, native_weights=w, counts0=cnt[0], unresolved=c['unresolved'], absorbed=any(x == 0 or x == 20000 for row in cnt for x in row), live_after=B.live))
        except CE.Refused as e: gauges.append(dict(power=power, admitted=False, kind=e.kind))
    r['gauges'] = gauges; paths_equal = len({json.dumps(g.get('counts0')) for g in gauges if g.get('admitted')}) == 1
    # a genuinely wide table: 2^600 and 2^-600 in ONE table -> the parent admits (and misdecides), the repaired code refuses NATIVE_RANGE (or falls back exactly)
    mdl = dict(cards=[2, 2], factors=[dict(scope=(0, 1), values=[F(2) ** 600, F(1), F(1), F(1) / (F(2) ** 600)])], evidence={}); clk = CE.Clock(time.monotonic() + 20, {}); B = CE.Budget(64 << 20); M = CE.canonicalize(mdl, clk, B); hm = HX.HeatBathModel(M)
    try: ch = HN.NativeChain(hm, [0, 0], 1, clk, B); w, lo, hi = ch.inspect(0); ch.close(); r['wide_table'] = dict(admitted=True, native_weights=w)
    except CE.Refused as e: r['wide_table'] = dict(admitted=False, kind=e.kind)
    # ambiguous prefixes force the exact fallback: weights (1, 2) with the 53-bit prefix at the boundary 1/3 -> decide_exact resolves with extra bits; the decision matches the exact conditional law for both continuations
    u53 = (1 << 53) // 3; a0, e0 = HX.decide_exact([F(1), F(2)], u53, lambda k: 0); a1, e1 = HX.decide_exact([F(1), F(2)], u53, lambda k: (1 << k) - 1 if k else 0)
    r['ambiguous_prefix'] = dict(low_continuation=(a0, e0), high_continuation=(a1, e1), consistent=(a0 == 0 and a1 == 1 and e0 >= 1 and e1 >= 1))
    present = bool(r['full_runner_1e-200']['wrong_rows']) or any(g.get('absorbed') for g in gauges if g.get('admitted')) or (not paths_equal) or r['wide_table']['admitted']
    r['summary'] = dict(wrong_rows=r['full_runner_1e-200']['wrong_rows'], gauges_identical_paths=paths_equal, wide_table_admitted=r['wide_table']['admitted'], repaired_api=REPAIRED_API['native_range']); r['present'] = present; return r


# ---------------------------------------------------------------- RV2
def RV2():
    r = {}
    def model(factors):
        m = CE.Canon(); m.cards = [2, 2]; m.psi = [[F(1), F(1)], [F(1), F(1)]]; m.factors = factors; m.orig_of = [0, 1]; return m
    rvals = [F(2), F(3), F(7), F(19, 3), F(1, 2), F(1, 3), F(1, 7), F(3, 19), F(2) ** 300, F(1, 2 ** 300), F(1) + F(1, 2 ** 40)]
    import random as _r; rng = _r.Random(854); worst = None
    for it in range(40):
        pos = [rng.choice(rvals) for _ in range(128)]; rs = pos + [1 / x for x in pos]; rng.shuffle(rs)
        b = SW.build_interaction(model([((0, 1), [x, F(1), F(1), x]) for x in rs]), CE.Budget(64 << 20), CE.Clock(time.monotonic() + 20, {})); lo = float(b['A_lo'][0, 2]); hi = float(b['A_hi'][0, 2])
        if not (lo <= 0 <= hi): worst = dict(trial=it, lo=lo, hi=hi); break
    r['cancellation'] = dict(trials=it + 1, excluded_zero=worst)
    # the complete false-admission fixture (10,000 + 10,000 + 1 factors; exact width > 2)
    N = 10000; k = 3000; rr = F(math.exp(-1 - 5e-10)); power = F(2) ** k
    raw = {'cards': [2, 2], 'evidence': {}, 'factors': [{'scope': (0, 1), 'values': [power, F(1), F(1), power]}] * N + [{'scope': (0, 1), 'values': [1 / power, F(1), F(1), 1 / power]}] * N + [{'scope': (0, 1), 'values': [rr, F(1), F(1), rr]}]}
    B = CE.Budget(128 << 20); clk = CE.Clock(time.monotonic() + 60, {}); M = CE.canonicalize(raw, clk, B); W = SW.certify(M, B, clk)
    if hasattr(SW, 'release_retained'): SW.release_retained(W, B)
    r['false_admission'] = dict(eligible=W['eligible'], width=W.get('width'), refusal=(W.get('refusal') or {}).get('kind'), true_width_lower=float(-2 * SW.log_enclosure(rr)[1]))
    # ordering permutations: the same multiset of factors in two orders gives the SAME enclosure (exact accumulation) -- the parent's float accumulation is order-dependent
    fs = [((0, 1), [x, F(1), F(1), x]) for x in (rvals + [1 / x for x in rvals])]; b1 = SW.build_interaction(model(fs), CE.Budget(64 << 20), CE.Clock(time.monotonic() + 20, {})); b2 = SW.build_interaction(model(list(reversed(fs))), CE.Budget(64 << 20), CE.Clock(time.monotonic() + 20, {}))
    r['order_invariance'] = dict(identical=bool(np.array_equal(b1['A_lo'], b2['A_lo']) and np.array_equal(b1['A_hi'], b2['A_hi'])), lo1=float(b1['A_lo'][0, 2]), lo2=float(b2['A_lo'][0, 2]))
    r['present'] = bool(worst) or bool(W['eligible']); r['summary'] = dict(excluded_zero=bool(worst), false_admission=bool(W['eligible']), order_invariant=r['order_invariance']['identical']); return r


# ---------------------------------------------------------------- RV3 (original DGP7 F1-F5, F4c)
def _arr(vals):
    x = np.empty(len(vals), dtype=object)
    for i, v in enumerate(vals): x[i] = RM.from_fraction_up(F(v))
    return x


def RV3():
    r = {}; clock = CE.Clock(time.monotonic() + 60, {}); cards = [2, 2]; order = [0, 1]
    conds = {v: JP.Conditional(v, (), np.array([[JP.D // 2, JP.D // 2]], dtype=np.int64), cards) for v in order}
    Bc = RM.from_fraction_up(F(4)); prop = JP.Proposal(cards, conds, order, Bc, RM.from_fraction_up(16), {'kind': 'exact tiny witness'}); st = RB.ResidualState('tiny W=rho0*rho1', 'synthetic exact identity', prop, Bc, Bc, Bc, CE.Budget(1 << 30))
    rhos = [[F(1, 2), F(1)], [F(1), F(1, 4)]]
    for j, vals in enumerate(rhos):
        at = RB.Atom(j, (0,), _arr(vals), {'kind': 'independently exact constructed bank'}, 1, 0, 0); at.verified = True; st.atoms[j] = at
    w = {'A': order, 'R': order, 'C': [], 'bank_version': 0, 'target_parents': {0: (), 1: ()}, 'max_vol': 65536}; w.update(model_identity=st.model_identity, seed_proof_identity=st.seed_proof_identity, law_identity=st.law_identity)
    kw = dict(expected_identity=st.model_identity) if 'expected_identity' in inspect.signature(CR.local_kernel).parameters else {}
    legit = CR.local_kernel(st, w, [0, 1], conds, None, cards, order, clock, **kw); dup = CR.local_kernel(st, w, [0, 0, 1], conds, None, cards, order, clock, **kw)
    mutated = any(x.consumed for x in st.atoms.values())
    r['F1_duplicate_ids'] = dict(honest_ok=legit['ok'], honest_B=str(RM.to_fraction(legit['B_new'])) if legit.get('B_new') else None, duplicate_ok=dup['ok'], duplicate_why=(dup.get('why') or '')[:120], duplicate_B=(str(RM.to_fraction(dup['B_new'])) if dup.get('B_new') else None), required_B='2', any_atom_mutated=mutated)
    f1_present = bool(dup['ok']) or mutated
    t = JP.JTable((0,), _arr([1, 1]), 0, ('factor', 0)); out_ = JP.JTable((), _arr([1]).reshape(()), 1, ('max_message', 0, (0,))); rho = _arr([F(3, 2), F(3, 2)])
    rec_ = CJ.check_stage([t], out_, 0, [2], 'max', clock, inventory=[0], bucket_ids=[0], rho=rho)
    try: RB.check_slack_cells([t], out_, rho, (0,), (), [2], clock); standalone_accepts = True
    except Exception: standalone_accepts = False
    rho1 = _arr([F(1), F(1)]); rec1 = CJ.check_stage([t], out_, 0, [2], 'max', clock, inventory=[0], bucket_ids=[0], rho=rho1)
    r['F2_rho_range'] = dict(stage_accepts_three_halves=bool(rec_.get('slack_ok')), standalone_accepts_three_halves=standalone_accepts, stage_accepts_one=bool(rec1.get('slack_ok')))
    f2_present = bool(rec_.get('slack_ok')) or standalone_accepts
    # F3: injected clocks on the production methods (batch / epoch / residual commit)
    def ready(kind, **extra):
        b = CE.Budget(100000000); m = CE.canonicalize(C._four_cycle(), CE.Clock(time.monotonic() + 20, {}), CE.Budget(100000000))
        s = kind(2, m, m, [], 1, F(1, 200), F(1, 4000000), dict(PAC_OPTS, budget_obj=b), **extra); deadline = time.monotonic() + 15; assert s.prepare(deadline, until=deadline) == 'READY', s.closed_reason; return s, b
    s, b = ready(JS.JointStream, mode='seed'); clk = [99.0]; orig = JS.tnow; JS.tnow = lambda: clk[0]
    fn = inspect.getsourcefile(JS.JointStream.batch); lines, start = inspect.getsourcelines(JS.JointStream.batch); target = start + next(i for i, l in enumerate(lines) if 'self.draws += Bn' in l)
    def cross_batch(frame, event, arg):
        if event == 'line' and frame.f_code.co_filename == fn and frame.f_lineno == target: clk[0] = 101.0
        return cross_batch
    try: sys.settrace(cross_batch); res_b = s.batch(100.0, 100.0, B_override=4)
    finally: sys.settrace(None); JS.tnow = orig
    r['F3_batch'] = dict(result=res_b, clock_after=clk[0], committed_after_deadline=(res_b == 'COMMITTED' and clk[0] > 100.0), draws=s.draws)
    # the batch's own commit sample: the repaired code reduces before ONE sample (the crossing at the scalar-update line is after the commit decision and does not create a commit stamp beyond the deadline); the PARENT
    # also reports COMMITTED here -- so the discriminating fixture is the EPOCH stamp and the residual stamp below, plus the source-order check: no variable-size reduction between the sample and the swap
    src_b = ''.join(lines); i_poll = src_b.find('t_commit = tnow()'); r['F3_batch']['single_sample_before_swap'] = (i_poll >= 0 and 'X.sum()' not in src_b[i_poll:])
    s, b = ready(JS.JointStream, mode='seed'); clk = [99.0]; orig_pa = PA.tnow; JS.tnow = lambda: clk[0]; PA.tnow = lambda: clk[0]
    fn = inspect.getsourcefile(JS.JointStream._commit_epoch); lines, start = inspect.getsourcelines(JS.JointStream._commit_epoch); hit = [i for i, l in enumerate(lines) if 'ep.committed_at = tnow()' in l or 'ep.committed_at = t_commit' in l]; target = start + hit[0]
    def cross_epoch(frame, event, arg):
        if event == 'line' and frame.f_code.co_filename == fn and frame.f_lineno == target: clk[0] = 101.0
        return cross_epoch
    try: sys.settrace(cross_epoch); ep = s._commit_epoch(s.epoch.prop, 'probe crossing', 100.0, b)
    finally: sys.settrace(None); JS.tnow = orig; PA.tnow = orig_pa
    r['F3_epoch'] = dict(committed_at=ep.committed_at, deadline=100.0, stamped_after_deadline=(ep.committed_at > 100.0))
    b = CE.Budget(100000000); m = CE.canonicalize(C._four_cycle(), CE.Clock(time.monotonic() + 20, {}), CE.Budget(100000000)); s = RS.ResidualStream(2, m, m, [], 1, F(1, 200), F(1, 4000000), dict(PAC_OPTS, budget_obj=b), profile={'V_seed': 16})
    deadline = time.monotonic() + 15; assert s.prepare(deadline, until=deadline) == 'READY'; assert s.pilot_action(deadline)['status'] == 'COMPLETE'
    clk = [99.0]; mods = [JS, RS, PA, CE]; origs = [mm.tnow for mm in mods]
    for mm in mods: mm.tnow = lambda: clk[0]
    s.allowance_start = 80.0; s.allowance_end = 100.0; s.phase_ends = {k: 100.0 for k in s.phase_ends}
    fn = inspect.getsourcefile(RS.ResidualStream._optimize_action); lines, start = inspect.getsourcelines(RS.ResidualStream._optimize_action); target = start + next(i for i, l in enumerate(lines) if 'freed = st.release_consumed' in l)
    def cross_res(frame, event, arg):
        if event == 'line' and frame.f_code.co_filename == fn and frame.f_lineno == target: clk[0] = 101.0
        return cross_res
    try: sys.settrace(cross_res); att = s.optimize_action(100.0, 110.0)
    finally:
        sys.settrace(None)
        for mm, o in zip(mods, origs): mm.tnow = o
    txn = att.get('transaction') or {}; r['F3_residual'] = dict(status=att.get('status'), epoch_committed_at=(s.epoch.committed_at if s.epoch else None), transaction_committed_at=(80.0 + txn['committed_offset_s']) if txn.get('committed_offset_s') is not None else None)
    f3_present = bool(r['F3_epoch']['stamped_after_deadline']) or (r['F3_residual']['transaction_committed_at'] is not None and r['F3_residual']['transaction_committed_at'] > 100.0) or (not r['F3_batch']['single_sample_before_swap'])
    # F4c: the released law
    s2, b2 = ready(RS.ResidualStream); law = s2.state.law; s2._close('probe'); r['F4c_law'] = dict(law_still_reachable=(s2.state.law is law), budget_live=b2.live); f4c_present = bool(s2.state.law is law)
    # F4a / F4b: expired entry; retained plans charged; the certifier's expected plan admitted
    class Expired:
        def __init__(self): self.calls = []
        def poll(self, w_): self.calls.append(w_); raise CE.Refused('DEADLINE', 'injected entry expiry')
        def remaining(self): return -1.0
    n = 1000; cards_ = [2] * n; order_ = list(range(n)); parents = {v: () for v in order_}; ex = Expired(); Bp = CE.Budget(1 << 28); tracemalloc.start()
    try: GC.CircuitPlan(cards_, order_, parents, [], 1, order_, clock=ex, budget=Bp)
    except CE.Refused: pass
    peak_exp = tracemalloc.get_traced_memory()[1]; tracemalloc.stop()
    n = 32; cards_ = [2] * n; order_ = list(range(n)); parents = {v: () for v in order_}; scopes = list(itertools.combinations(order_, 2)); Bp = CE.Budget(1 << 28); clk_ = CE.Clock(time.monotonic() + 10, {})
    P = GC.CircuitPlan(cards_, order_, parents, scopes, 1, order_, clock=clk_, budget=Bp); Q = GC.CircuitPlan(cards_, order_, parents, scopes, 2, order_, clock=clk_, budget=Bp); live_retained = Bp.live
    for pl in (P, Q):
        if hasattr(pl, 'release'): pl.release()
    r['F4ab_plans'] = dict(expired_entry_polls=ex.calls, expired_peak_bytes=peak_exp, retained_plans_ledger_live=live_retained, released_live=Bp.live); f4ab_present = (peak_exp > 100000) or (live_retained == 0)
    # F5: extraction eviction
    Bb = CE.Budget(128 << 20); sstate = RB.ResidualState('m', 'p', None, RB.ONE, RB.ONE, RB.ONE, Bb)
    def farr(n_, x):
        y = np.empty(n_, dtype=object); y.fill(x); return y
    for i, n_ in enumerate([4096] * 31 + [2048, 16]):
        axes = tuple(range(n_.bit_length() - 1)); arr_ = farr(n_, (-1, 1)).reshape((2,) * len(axes)); charge = JP.ENTRY_BYTES * n_ + RB.ATOM_META_BYTES; sstate._charge(charge, 'fixture'); sstate.add_atom(axes, arr_, {}, 0.0 if n_ == 16 else 0.000000001, -1, charge)
    sink = RB.BankSink(sstate, CE.Clock(time.monotonic() + 10, {}), 10); Pm = farr(4096, (-1, 1)).reshape((2,) * 12); Mm = SimpleNamespace(arr=farr(2048, RB.ONE).reshape((2,) * 11))
    pending = sink.prepare(0, 1, [], Pm, tuple(range(12)), Mm, tuple(range(1, 12)), [2] * 12); projected = sstate.entries() + (pending['vol'] if pending else 0)
    r['F5_extraction'] = dict(projected_entries=projected, cap=sink.max_entries, violated=(projected > sink.max_entries), evictions=len(sstate.evicted)); f5_present = projected > sink.max_entries
    if pending: sink.abort(pending)
    r['present'] = bool(f1_present or f2_present or f3_present or f4c_present or f4ab_present or f5_present); r['summary'] = dict(F1=f1_present, F2=f2_present, F3=f3_present, F4c=f4c_present, F4ab=f4ab_present, F5=f5_present); return r


# ---------------------------------------------------------------- RV4
def RV4():
    pub, enc, st = MC.rows_from_counts([[1, 998, 1]], 1000, F(7, 1000), F(1, 200), [0], {}); eps = F(1, 200)
    rows = [dict(state=a, lo=str(lo), hi=str(hi), point=str(p), endpoint_radius=float(max(p - lo, hi - p))) for (v, a), (lo, hi, p, g) in sorted(pub.items())]
    viol = sum(1 for x in rows if F(x['endpoint_radius']) > eps + F(1, 10 ** 12))
    return dict(present=bool(viol), rows=rows, violations=viol, published=len(pub), enclosures=len(enc), summary=dict(endpoint_violations=viol, published=len(pub)))


# ---------------------------------------------------------------- RV5
def RV5():
    import pgm.algorithms.response.spectral_heatbath_run as RUN; r = {}
    mdl = {'cards': [2, 2, 2], 'factors': [{'scope': [0, 1], 'values': [F(1)] * 4}, {'scope': [2], 'values': [F(1000)] * 2}], 'evidence': {}}
    with patch.object(RUN.CORE, 'read_uai', return_value=(mdl, {})), patch.object(sys, 'argv', ['x', '--input', 'unused', '--output', os.path.join(OUT_DIR, 'rv5_scalar.json'), '--budget', '3', '--admission-stop', '2.5']):
        d = RUN.main()
    z = d.get('Z_enclosure') or {}; tl = math.log2(8000); r['scalar_Z'] = dict(log2_lo=z.get('log2_lo'), log2_hi=z.get('log2_hi'), true_log2=tl, contains=bool(z.get('log2_lo') is not None and z['log2_lo'] <= tl <= z['log2_hi']))
    fl = {'cards': [2, 2, 2], 'factors': [], 'evidence': {}}; OB = CE.Budget
    with patch.object(RUN.CORE, 'read_uai', return_value=(fl, {})), patch.object(CE, 'Budget', side_effect=lambda _: OB(0)), patch.object(sys, 'argv', ['x', '--input', 'unused', '--output', os.path.join(OUT_DIR, 'rv5_early.json'), '--budget', '3', '--admission-stop', '2.5']):
        d = RUN.main()
    r['early_inventory'] = dict(K=d['K'], rows=len(d['answers']), outcome=d['outcome'])
    clock = {'t': 0.0}; orig_ru = RUN.resource.getrusage
    def now(): return clock['t']
    def cross(*a_): clock['t'] = 100.0; return orig_ru(*a_)
    for name, mm in (('factorless', fl), ('ordinary', {'cards': [2, 2], 'factors': [{'scope': [0, 1], 'values': [F(2), F(1), F(1), F(2)]}], 'evidence': {}})):
        clock['t'] = 0.0
        with patch.object(RUN.CORE, 'read_uai', return_value=(mm, {})), patch.object(RUN, 'tnow', side_effect=now), patch.object(CE, 'tnow', side_effect=now), patch.object(RUN.resource, 'getrusage', side_effect=cross), patch.object(sys, 'argv', ['x', '--input', 'unused', '--output', os.path.join(OUT_DIR, 'rv5_cross_%s.json' % name), '--budget', '10', '--admission-stop', '9']):
            try: d = RUN.main()
            except SystemExit: d = json.load(open(os.path.join(OUT_DIR, 'rv5_cross_%s.json' % name)))
        r['crossing_' + name] = dict(outcome=d['outcome'], published=d['published'], respected=d['hard_deadline_respected'])
    present = (not r['scalar_Z']['contains']) or r['early_inventory']['K'] != 6 or any(r['crossing_' + k]['published'] for k in ('factorless', 'ordinary')) or any(r['crossing_' + k]['outcome'] != 'DEADLINE' for k in ('factorless', 'ordinary'))
    r['present'] = present; r['summary'] = dict(scalar_contains=r['scalar_Z']['contains'], early_K=r['early_inventory']['K'], crossings=[r['crossing_factorless']['outcome'], r['crossing_ordinary']['outcome']]); return r


# ---------------------------------------------------------------- RV6
def RV6():
    import gc; r = {}
    M = CE.Canon(); M.cards = [32, 32]; M.psi = [[F(1)] * 32, [F(1)] * 32]; M.factors = [((0, 1), [F(1000000 + i, 1000000) for i in range(1024)])]; M.orig_of = [0, 1]
    if hasattr(SW, '_log_enclosure_cached'): SW._log_enclosure_cached.cache_clear()
    gc.collect(); B = CE.Budget(CE.CONSTRUCTOR_BYTES); l0 = B.live; W = SW.certify(M, B, CE.Clock(time.monotonic() + 20, {})); live_after = B.live - l0; ret = W.get('retained_bytes')
    if hasattr(SW, 'release_retained'): SW.release_retained(W, B)
    r['witness_ownership'] = dict(global_cache=hasattr(SW, '_log_enclosure_cached'), retained_declared=ret, live_after_certify=live_after, live_restored_after_release=(B.live == l0), cache_record=W.get('cache'), peak_charge=B.peak)
    # the native constructor at zero headroom: how much is staged before the refusal
    hm = HX.HeatBathModel(CE.canonicalize(dict(cards=[4] * 64, factors=[dict(scope=(i, j), values=[F(1, 3)] * 16) for i in range(64) for j in range(i + 1, 64)], evidence={}), CE.Clock(time.monotonic() + 30, {}), CE.Budget(1 << 30)))
    orig_build = HN.build; HN.build = lambda *a_, **k_: (None, {}); gc.collect(); tracemalloc.start()
    try: HN.NativeChain(hm, [0] * 64, 1, CE.Clock(time.monotonic() + 10, {}), CE.Budget(0)); kind = None
    except Exception as e: kind = getattr(e, 'kind', type(e).__name__)
    peak = tracemalloc.get_traced_memory()[1]; tracemalloc.stop(); HN.build = orig_build
    r['native_staging'] = dict(refusal_kind=kind, traced_peak_bytes=peak, staged_megabyte=(peak > 1 << 20))
    present = bool(r['witness_ownership']['global_cache']) or (ret is None) or (not r['witness_ownership']['live_restored_after_release']) or r['native_staging']['staged_megabyte']
    r['present'] = present; r['summary'] = dict(global_cache=r['witness_ownership']['global_cache'], retained_declared=ret, staging_peak=peak); return r


# ---------------------------------------------------------------- RV7
def RV7():
    d, rc, err = run_runner(tri_uai('1'), 2.0, 1.5, extra=['--rate-model', os.path.join(OUT_DIR, 'absent_rates.json')]); m = (d or {}).get('mechanism') or {}
    kind = (m.get('refusal') or {}).get('kind'); src = (m.get('rate_model') or {}).get('source')
    return dict(present=(kind != 'RATE_MODEL_MISSING'), rc=rc, outcome=(d or {}).get('outcome'), refusal_kind=kind, rate_source=src, summary=dict(rc=rc, refusal=kind, rate_source=src))


ALL = [('RV1', RV1), ('RV2', RV2), ('RV3', RV3), ('RV4', RV4), ('RV5', RV5), ('RV6', RV6), ('RV7', RV7)]
for name, fn in ALL:
    if a.only and name not in a.only.split(','): continue
    probe(name, fn)
out = dict(source=SRC, repaired_api=REPAIRED_API, utc=time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()), probes=R, present={k: v.get('present') for k, v in R.items()}, n_present=sum(1 for v in R.values() if v.get('present')), n_absent=sum(1 for v in R.values() if v.get('present') is False), errors=[k for k, v in R.items() if v.get('error')])
json.dump(out, open(a.output, 'w'), indent=1, default=str); print(json.dumps(dict(present=out['present'], errors=out['errors']), default=str))
