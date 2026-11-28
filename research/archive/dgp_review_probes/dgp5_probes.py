"""DGP5 before / after probes of the six open DGP4 findings (brief CLAUDE_DGP5_JOINT_CONSTRUCTION_SPEC.md section 10), runnable against ANY source root: before = the pinned frozen parent pgm-eval-9355663, after = the DGP5
frozen commit. The fixtures and the recorded quantities are the DGP4 independent review's (`dgp4_review/rmax_audit/probes.py`, `dgp4_review/code_fit/integration_probes.py`); only the path resolution is adapted and every
step is wrapped so a REPAIRED refusal is recorded instead of aborting the script. Per finding the record carries `finding_present` = the review's failure condition evaluated on this root (True before, False after).
usage: dgp5_probes.py --source ROOT --output OUT.json"""
import sys, os, json, time, argparse, traceback, gc, weakref, itertools, random, re
from fractions import Fraction as F
ap = argparse.ArgumentParser(); ap.add_argument('--source', required=True); ap.add_argument('--output', required=True); a = ap.parse_args()
ROOT = os.path.abspath(a.source); SRC = os.path.join(ROOT, 'code'); sys.path[:0] = [os.path.join(SRC, 'cex/hp'), os.path.join(SRC, 'cex/blockres'), os.path.join(SRC, 'cex/newarm')]
import numpy as np
import residual_max_envelope as R, check_dgp as C, coarse_envelope as CE, pac_actions as PA
OUT = dict(source=ROOT, probes={}, utc=time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()))
def rec(name, **kw): OUT['probes'][name] = kw; print(json.dumps({name: kw}, default=str)[:700], flush=True)
def guard(name, fn):
    try: fn()
    except Exception as e: rec(name + '_ERROR', error=repr(e)[:300], tb=traceback.format_exc()[-1200:])

def f1_wide_pack():
    """finding 1a: the valid 3,001-bit card-4 factor [2^3000, 1, ..., 1] -- packing diagnostics must not refuse the stream"""
    m = dict(cards=[4, 4], factors=[dict(scope=(0, 1), values=[F(2 ** 3000)] + [F(1)] * 15)], evidence={}); M, cl, Cz, rows, clk, B = C._stage(m, [[0, 0, 1, 1]] * 2)
    co = R.RMAXCompile(M, cl, Cz, rows, R.PROFILE_PRODUCTION, B, clk); co.build_sources(); co.set_order(); co.run_stages(time.monotonic() + 2); co.closure(); res = {}
    try: co.pack(); res['pack'] = dict(result='success', inflation=co.packing)
    except Exception as e: res['pack'] = dict(result=type(e).__name__, reason=str(e)[:160], stages_done=co.stages_done)
    co.release_all()
    S = PA.LiftedStream(2, M, M, [], cl, Cz, 1, C.EPS, C.DELTA / 4, dict(C.PAC_OPTS, budget_obj=B, rmax_profile=R.PROFILE_PRODUCTION), envelope='RMAX'); stage = S.prepare(time.monotonic() + 3)
    res['stream'] = dict(stage=stage, reason=S.closed_reason, mechanism=S.mech.get('rmax_refusal'), rows=len(S.pub), factor_bits=3001)
    present = (res['pack']['result'] != 'success') or (stage != 'READY' and 'NUMERIC' in str(S.closed_reason))
    rec('F1a_wide_pack', finding_present=present, **res)

def f1_pack_expired():
    """finding 1b: packing + its checker under an already-expired injected clock must refuse at entry (polls > 0); packed arrays must be charged"""
    M, cl, Cz, rows, clk, B = C._stage(C._four_cycle(), [[0, 0, 1, 1]] * 4); co = R.RMAXCompile(M, cl, Cz, rows, R.PROFILE_PRODUCTION, B, clk)
    co.build_sources(); co.build_seeds([(0, 1), (2, 3)]); co.set_order(); co.run_stages(time.monotonic() + 2); co.closure()
    class Expired:
        def __init__(self): self.calls = 0
        def poll(self, *args): self.calls += 1; raise CE.Refused('DEADLINE', 'already expired')
    e = Expired(); co.clock = e; before = B.live; res = {}
    try: co.pack(); pk = R.check_packing(co.closed, co.packed); res.update(result='success', clock_calls=e.calls, budget_before=before, budget_after=B.live, packed_array_bytes=sum(P['ints'].nbytes for P in co.packed), check=pk)
    except Exception as ex: res.update(result=type(ex).__name__, reason=str(ex)[:120], clock_calls=e.calls, budget_before=before, budget_after=B.live)
    co.release_all(); present = (res['result'] == 'success' and res['clock_calls'] == 0); rec('F1b_pack_expired', finding_present=present, **res)

def f1_source_volume():
    """finding 1c: the source volume cap is enforced BEFORE allocation (V = 4 on the four-cycle: 16-entry sources)"""
    M, cl, Cz, rows, clk, B = C._stage(C._four_cycle(), [[0, 0, 1, 1]] * 4); base = B.live; co = R.RMAXCompile(M, cl, Cz, rows, dict(V=4, fanin=16, mantissa_bits=128), B, clk); res = dict(V=4)
    try: co.build_sources(); res.update(build_sources='success', allocated_max_volume=max(T.volume() for T in co.active), owned_bytes=co.owned[0], live_delta=B.live - base)
    except Exception as ex: res.update(build_sources=type(ex).__name__, reason=str(ex)[:160], owned_bytes=co.owned[0], live_delta=B.live - base)
    if res['build_sources'] == 'success':
        co.set_order()
        try: co.stage(co.residual_order[0]); res['stage_result'] = 'success'
        except Exception as ex: res['stage_result'] = type(ex).__name__; res['stage_reason'] = str(ex)[:160]
    co.release_all(); present = (res['build_sources'] == 'success' and res.get('allocated_max_volume', 0) > 4); rec('F1c_source_volume_before_allocation', finding_present=present, **res)

def f2_duplicate_checker():
    """finding 2: the stage checker accepts the SAME table id 17 twice (two 1/2 inputs, consistent 1/4 output) -- an accepted malformed proof"""
    axes = (0, 1); arr = np.empty((1, 2), dtype=object); arr.fill(R.from_fraction_up(F(1, 2))); t = R.Table(axes, arr, 17, ('factor', 0))
    outarr = np.empty((1,), dtype=object); outarr.fill(R.from_fraction_up(F(1, 4))); out = R.Table((0,), outarr, 18, ('message', 0, (17, 17)))
    receipt = R.check_stage([t, t], out, 1, [1], [2], [[[0, 1]]], CE.Clock(time.monotonic() + 2, {}))
    rec('F2_duplicate_input_checker', finding_present=bool(receipt.get('ok')), receipt=receipt, original_input_value='1/2', returned_output_value='1/4', underbounds_original=True)

def f3_close_ownership():
    """finding 3: Stream._close releases constructor charges while the arrays stay reachable (RMAX 5,248 B; G2 7,904 B)"""
    def stream(envelope):
        M, cl, Cz, rows, clk, B = C._stage(C._four_cycle(), [[0, 0, 1, 1]] * 4)
        return PA.LiftedStream(2, M, M, [], cl, Cz, 1, C.EPS, C.DELTA / 4, dict(C.PAC_OPTS, budget_obj=B), envelope=envelope), B
    for envelope in ('G2', 'RMAX'):
        S, B = stream(envelope); r = S.prepare(PA.tnow() + 10); assert r == 'READY', (r, S.closed_reason)
        fields = ['fine_bytes', 'grouped_bytes', 'rmax_bytes']; before = {k: getattr(S, k, 0) for k in fields}; before.update(live=B.live, retained=S.retained_bytes)
        fine_refs = [weakref.ref(b.M) for b in S.fine]; comp_ref = weakref.ref(S.rmax) if S.rmax is not None else None; packed_refs = [weakref.ref(p['ints']) for p in S.rmax.packed] if S.rmax is not None else []
        grouped_refs = [weakref.ref(U) if not isinstance(U, (list, tuple, dict)) else None for _, U in S.grouped['tables']] if S.grouped else []; n_grouped = len(S.grouped['tables']) if S.grouped else 0
        S._close('injected post-construction refusal'); gc.collect()
        after = {k: getattr(S, k, 0) for k in fields}; after.update(live=B.live, retained=S.retained_bytes, live_fine_arrays=sum(w() is not None for w in fine_refs), live_compiler=(comp_ref() is not None if comp_ref else None), live_packed_arrays=sum(w() is not None for w in packed_refs), live_grouped_tables=(len(S.grouped['tables']) if S.grouped else 0), live_grouped_table_objects=sum(1 for w in grouped_refs if w is not None and w() is not None))
        released = before['live'] - after['live']; present = released > 0 and (after['live_fine_arrays'] > 0 or after['live_compiler'] or after['live_packed_arrays'] > 0 or after['live_grouped_tables'] > 0)
        rec('F3_close_ownership_' + envelope, finding_present=present, before=before, after=after, released=released, grouped_tables_before=n_grouped, note='no RSS claim; reachable ownership vs ledger release')

def f4_ready_after_allowance():
    """finding 4: the final READY poll precedes the fingerprint traversal; an injected clock crossing inside the actual tobytes traversal must not yield READY at 102 > until 101"""
    M, cl, Cz, rows, clk, B = C._stage(C._four_cycle(), [[0, 0, 1, 1]] * 4); S = PA.LiftedStream(2, M, M, [], cl, Cz, 1, C.EPS, C.DELTA / 4, dict(C.PAC_OPTS, budget_obj=B), envelope='RMAX')
    S._l_decoder(PA.tnow() + 10); S.rmax_midpoint = PA.tnow() + 5; S._l_coarse_proposal(PA.tnow() + 10); S._l_fine_tables(PA.tnow() + 10); clock = {'now': 100., 'copies': 0}; old = (PA.tnow, CE.tnow); real_prepare = PA.prepare_sampler_polled
    class TimedArray(np.ndarray):
        def tobytes(self, *args, **kwargs):
            clock['copies'] += 1; clock['now'] = 102.; return super().tobytes(*args, **kwargs)
    def prep(*args, **kwargs):
        n = real_prepare(*args, **kwargs)
        for _, tabs in S.mbp.prep:
            if tabs:
                for i, (lm, strides, scope) in enumerate(tabs): tabs[i] = (lm.view(TimedArray), strides, scope)
        return n
    PA.tnow = CE.tnow = lambda: clock['now']; PA.prepare_sampler_polled = prep
    try: r = S.prepare(110., until=101.)
    finally: PA.tnow, CE.tnow = old; PA.prepare_sampler_polled = real_prepare
    rec('F4_ready_after_allowance', finding_present=(r == 'READY'), result=r, stage=S.stage, clock=clock['now'], effective_deadline=101., hard_deadline=110., fingerprint_table_copies=clock['copies'], elapsed_beyond_allowance=clock['now'] - 101., published=len(S.pub), closed=S.closed_reason)

def f5_allowance_reopened():
    """finding 5: a preparation first limited to 101 (yield at the stage boundary) must not reopen when resumed with until 110"""
    M, cl, Cz, rows, clk, B = C._stage(C._four_cycle(), [[0, 0, 1, 1]] * 4); S = PA.LiftedStream(2, M, M, [], cl, Cz, 1, C.EPS, C.DELTA / 4, dict(C.PAC_OPTS, budget_obj=B), envelope='RMAX'); real_decoder = S._l_decoder; clock = {'now': 100.}
    def decode_then_expire(deadline): real_decoder(deadline); clock['now'] = 101.
    S._l_decoder = decode_then_expire; old = (PA.tnow, CE.tnow, PA.IG.tnow); PA.tnow = CE.tnow = PA.IG.tnow = lambda: clock['now']
    try: r1 = S.prepare(110., until=101.); stage1 = S.stage; r2 = S.prepare(110., until=110.)
    finally: PA.tnow, CE.tnow, PA.IG.tnow = old
    rec('F5_allowance_reopened_after_yield', finding_present=(r1 == 'YIELD' and r2 == 'READY'), first_result=r1, first_stage=stage1, second_result=r2, second_stage=S.stage, clock=clock['now'], first_until=101., second_until=110., midpoint=S.rmax_midpoint, closed=S.closed_reason, recorded_allowance=S.mech.get('rmax_allowance'))

def f6_vacuous_controls():
    """finding 6: D41 permits CLOSED / YIELD / READY (recorded READY); D37's zero-class assertion is vacuous on an all-positive fixture; D38 accepts kind in (BITS, None)"""
    src = open(os.path.join(SRC, 'cex/hp/check_dgp.py')).read(); res = {}
    d41 = src[src.index('def D41_'):]; d41 = d41[:d41.index('\nCONTROLS')] if '\nCONTROLS' in d41 else d41; res['D41_accepts_READY'] = ("in ('CLOSED', 'YIELD', 'READY')" in d41)
    d38 = src[src.index('def D38_'):src.index('def D39_')]; res['D38_accepts_None_kind'] = ("kind in ('BITS', None)" in d38)
    d37 = src[src.index('def D37_'):src.index('def D38_')]; res['D37_zero_class_text'] = ('zero_classes_zero_U' in d37); res['D37_has_genuine_zero_class_fixture'] = ('genuine_zero_class' in d37 and "executed" in d37)
    # D37's fixture: does every class carry positive target mass (making all(... for c in cs if c not in t) vacuous)?
    rng = random.Random(3); vals = [F(rng.randint(1, 9)) for _ in range(16)]; vals[5] = F(0); vals[9] = F(0)
    m = dict(cards=[4, 4], factors=[dict(scope=(0, 1), values=vals), dict(scope=(0,), values=[F(1), F(0), F(2), F(3)])], evidence={}); classes = [[0, 0, 0, 1], [0, 1, 1, 1]]
    M, cl, Cz, rows, clk, B = C._stage(m, classes); t, T = R.exact_t(M, cl, Cz, rows); cs = list(itertools.product(range(2), range(2))); res['D37_fixture_zero_mass_classes'] = [c for c in cs if c not in t]
    # D41 (d) as executed: forced RMAX with a 0.05 s allowance on the n16 clique
    try:
        from unified_pac_planner import UPlanner; import cost_model as CM
        model, binding = C.load_mid('dg_n16_c4_clique_two'); P = UPlanner(model, binding, 8.0, admission_stop_s=7.5, t_start=PA.tnow(), seed=1, pac=True, lifted=True, force_stream='lifted', envelope='RMAX'); P.M = CE.canonicalize(model, P.hclock, P.budget); P.canonical_charge = P.budget.live; P.mf = CM.model_features(P.M, P.clock, P.budget)
        ident = P.make_identity(P.clock); P.cands.append(ident); c = P.discover_fast_lift_only(ident, CE.Clock(PA.tnow() + 5, {})); P.lift_cands.append(c); S = P.make_lifted(c); r = S.prepare(P.adm, until=PA.tnow() + 0.05)
        res['D41d_forced_tight_allowance'] = dict(result=r, stage=S.stage, closed=(S.closed_reason or '')[:100])
    except Exception as e: res['D41d_forced_tight_allowance'] = dict(error=repr(e)[:200])
    # D38 (e): the 3^3000 source -> kind
    mb = dict(cards=[2, 2], factors=[dict(scope=(0, 1), values=[F(3) ** 3000, F(1), F(1), F(1)])], evidence={}); kind = 'NONE'
    try:
        Mb_, clb, Czb, rowsb, clkb, Bb = C._stage(mb, [[0, 1], [0, 1]]); cb = R.RMAXCompile(Mb_, clb, Czb, rowsb, R.PROFILE_PRODUCTION, Bb, clkb); cb.build_sources(); cb.release_all()
    except (CE.Refused, R.RefusedRMAX) as e: kind = getattr(e, 'kind', None)
    res['D38e_bits_fixture_kind'] = kind
    present = res['D41_accepts_READY'] or res['D38_accepts_None_kind'] or (res['D37_fixture_zero_mass_classes'] == [] and not res['D37_has_genuine_zero_class_fixture'])
    rec('F6_vacuous_controls', finding_present=present, **res)

for fn in (f1_wide_pack, f1_pack_expired, f1_source_volume, f2_duplicate_checker, f3_close_ownership, f4_ready_after_allowance, f5_allowance_reopened, f6_vacuous_controls): guard(fn.__name__, fn)
OUT['findings_present'] = {k: v.get('finding_present') for k, v in OUT['probes'].items()}
json.dump(OUT, open(a.output, 'w'), indent=1, default=str); print(json.dumps(OUT['findings_present'])); print('written', a.output)
