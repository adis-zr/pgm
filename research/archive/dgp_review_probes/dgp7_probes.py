"""DGP7 before / after probes of the eight DGP6-review repairs R1-R8 (brief CLAUDE_DGP7_IMPLEMENTATION_SPEC.md section 1; the supplied REPAIR_SPEC.md and its probes were NOT delivered -- these probes are written from the brief's text and labelled this
round's). Runnable against ANY source root: before = the frozen DGP6 source df02d18 (pgm-eval-df02d18), after = the DGP7 frozen commit. Each probe records `finding_present` = the defect condition evaluated on that root (True before, False after).
usage: dgp7_probes.py --source ROOT --output OUT.json [--dgp6-records DIR]"""
import sys, os, json, time, argparse, traceback, inspect, tracemalloc, math, re
from fractions import Fraction as F
ap = argparse.ArgumentParser(); ap.add_argument('--source', required=True); ap.add_argument('--output', required=True); ap.add_argument('--dgp6-records', default='/Users/adis/Workspace/pgm-records/code/runs/mdi_2026-10-28/DGP6_GLOBAL_CONSTRUCTION', help='the packet whose reproduce.sh / amendment are examined by R8 (before: the DGP6 packet; after: the DGP7 packet)'); a = ap.parse_args()
ROOT = os.path.abspath(a.source); SRC = os.path.join(ROOT, 'code'); sys.path[:0] = [os.path.join(SRC, 'cex/hp'), os.path.join(SRC, 'cex/blockres'), os.path.join(SRC, 'cex/newarm')]
import numpy as np
import coarse_envelope as CE, pac_actions as PA, check_dgp as C, joint_proposal as JP, joint_stream as JS, residual_max_envelope as RM, global_circuit as GC, check_global as CG
from unified_pac_planner import UPlanner, PAC_OPTS
import unified_pac_planner as UPP
OUT = dict(source=ROOT, probes={}, utc=time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())); EPS = F(1, 200); DELTA = F(1, 10 ** 6)
def rec(name, **kw): OUT['probes'][name] = kw; print(json.dumps({name: kw}, default=str)[:500], flush=True)
def guard(fn):
    try: fn()
    except Exception as e: rec(fn.__name__ + '_ERROR', error=repr(e)[:300], tb=traceback.format_exc()[-1200:])
def stage(model, budget_s=60):
    clk = CE.Clock(time.monotonic() + budget_s, {}); B = CE.Budget(CE.CONSTRUCTOR_BYTES); M = CE.canonicalize(model, clk, B); order, _ = CE.elimination_order(list(M.cards), [tuple(sc) for sc, _ in M.factors], clk, B); return M, order, clk, B

def r1_proof_kind_binding():
    """R1: the global certifier trusts the submitted plan's SUM / MAX designation: an all-MAX plan labelled 'moment' (power 2) with its own producer value passes the certifier although the moment proof REQUIRES a SUM at group 0 of every stage"""
    M, order, clk, B = stage(C._four_cycle()); cards = list(M.cards); prop, rec_, owned = JP.compile_seed(M, order, JP.PROFILE_PRODUCTION, B, clk); parents = {v: tuple(prop.conds[v].parents) for v in prop.order}
    sig = inspect.signature(GC.build_plans); extra = {k: v for k, v in dict(budget=B, clock=clk).items() if k in sig.parameters}
    PB, PS = GC.build_plans(M, prop.order, parents, order, **extra)
    import copy; mut = copy.copy(PS); mut.nodes = [dict(nd) for nd in PS.nodes]
    for nd in mut.nodes:
        if nd['op'] == 'reduce' and nd['agg'] == 'sum': nd['agg'] = 'max'
    n_mut = sum(1 for nd in PS.nodes if nd['op'] == 'reduce' and nd['agg'] == 'sum'); cS, _ = GC.compact_evaluate(mut, M, prop, B, clk)
    csig = inspect.signature(CG.certify); kw = dict(order_elim=order, kind='moment') if 'order_elim' in csig.parameters else {}
    r = CG.certify(mut, M, prop, cS, clk, **kw); honest = CG.certify(PS, M, prop, GC.compact_evaluate(PS, M, prop, B, clk)[0], clk, **kw)
    rec('R1_proof_kind_binding', finding_present=bool(r['ok']), mutant_sum_groups_turned_max=n_mut, mutant_accepted=r['ok'], mutant_why=r.get('why'), honest_accepted=honest['ok'], certifier_binds_kind=('order_elim' in csig.parameters))

def r2_compact_sum_transient():
    """R2: sum_up on two 128-bit terms with exponent gap 2^24 allocates an exponent-sized temporary mask ((1 << gap) - 1): the transient peak is ~2 MiB although the returned mantissa is 128 bits"""
    a_ = RM.from_fraction_up(F(3)); b_ = (a_[0] - (1 << 24), a_[1]); tracemalloc.start(); tracemalloc.reset_peak(); s = RM.sum_up([a_, b_]); cur, peak = tracemalloc.get_traced_memory(); tracemalloc.stop()
    upper = RM.to_fraction(s) >= RM.to_fraction(a_) + RM.to_fraction(b_)
    rec('R2_compact_sum_transient', finding_present=(peak > (1 << 18)), transient_peak_bytes=peak, result_bits=s[1].bit_length(), upper=upper, note='the returned mantissa was already bounded in DGP6 (D57); the finding is the TRANSIENT allocation of the remainder mask')

def r3_plan_admission_and_peak():
    """R3: graph / plan / hash construction (CircuitPlan, build_plans, plan.sha256) runs without a clock poll or an admitted charge; compact_evaluate reports peak_admitted_ok without measuring the actual simultaneous ownership against the symbolic peak"""
    sig = inspect.signature(GC.build_plans); has = ('clock' in sig.parameters and 'budget' in sig.parameters)
    M, order, clk, B = stage(C._four_cycle()); prop, rec_, owned = JP.compile_seed(M, order, JP.PROFILE_PRODUCTION, B, clk); parents = {v: tuple(prop.conds[v].parents) for v in prop.order}
    extra = {k: v for k, v in dict(budget=B, clock=clk).items() if k in sig.parameters}; PB, PS = GC.build_plans(M, prop.order, parents, order, **extra); cB, r = GC.compact_evaluate(PB, M, prop, B, clk)
    measured = ('peak_owned_bytes' in r and 'symbolic_peak_bytes' in r)
    rec('R3_plan_admission_and_peak', finding_present=(not has) or (not measured), build_plans_admitted_and_polled=has, compact_evaluate_reconciles_peak=measured, record_keys=sorted(r.keys()))

def r4_batch_refusal_boundary():
    """R4: a constructor MEMORY refusal raised inside JointStream.batch (the admitted batch scratch) escapes the batch's typed handlers (Deadline / RangeRefused / AssertionError) and propagates out of the stream instead of closing it typed"""
    model, _ = C.load('dg_n8_c4_clique_two'); M, order, clk, B = stage(model); S = JS.JointStream(2, M, M, [], 1, EPS, DELTA / 4, dict(PAC_OPTS, budget_obj=B), mode='seed'); r = S.prepare(time.monotonic() + 10, until=time.monotonic() + 10); assert r == 'READY', (r, S.closed_reason)
    S.batch(time.monotonic() + 10); B.cap = B.live; escaped = None; res = None
    try: res = S.batch(time.monotonic() + 10)
    except CE.Refused as e: escaped = e.kind
    rec('R4_batch_refusal_boundary', finding_present=(escaped is not None), escaped_exception=escaped, batch_result=res, stage=S.stage, closed=(S.closed_reason or '')[:80])

def r5_commit_diagnostics_after_poll():
    """R5: _commit_epoch builds the variable-sized epochs record list (mech['epochs'] = [e.record ...]) AFTER the authoritative deadline poll / the swap"""
    src = inspect.getsource(JS.JointStream._commit_epoch); i_poll = src.find("raise Deadline('epoch commit"); i_rec = src.find("[e.record for e in self.epochs]"); rec('R5_commit_diagnostics_after_poll', finding_present=(i_rec > i_poll), poll_index=i_poll, records_index=i_rec)

def r6_skipped_probe_protection():
    """R6: below 8 s of remaining work the probe is SKIPPED but primary_protected can still return True (the skipped-probe dict is not None and any finite forecast protects) -- the specified below-eight-second boundary is not restored"""
    class P(UPlanner.__mro__[0].__bases__[0]): pass
    fake = UPlanner.__new__(UPlanner); fake.old_policy = False; fake.force_stream = None; fake.primary_probe = dict(skipped='below 8 s', W_s=5.0)
    class S_:
        def ready(self): return True
        def all_published(self): return False
    fake.primary = S_(); fake.stream_forecast = lambda S: 1.0
    prot = fake.primary_protected(5.0); rec('R6_skipped_probe_protection', finding_present=bool(prot), protected_after_skipped_probe_at_W5=prot)

def r7_stale_J_control_and_oracle_units():
    """R7: (a) the exact-coefficient law assignment in dgp5_oracle is inside a comment; (b) the ideal-target law's log2_S_star in dgp6_oracle is lZ0 (should be 2 lZ0); (c) D57's rebuilt-J sub-check uses a synthetic incumbent (no real packet)"""
    s5 = open(os.path.join(SRC, 'cex/hp/dgp5_oracle.py')).read(); line = next((l for l in s5.split('\n') if "props['exact_coef_selected']" in l), ''); commented = ('#' in line and line.index('#') < line.index("props['exact_coef_selected']")) if line else True
    s6 = open(os.path.join(SRC, 'cex/hp/dgp6_oracle.py')).read(); ideal = next((l for l in s6.split('\n') if "laws['ideal_q_eq_p'] = dict(" in l), ''); wrong_units = ('log2_S_star=lZ0,' in ideal or 'log2_S_star=lZ0)' in ideal)
    sd = open(os.path.join(SRC, 'cex/hp/check_dgp.py')).read(); d57 = sd[sd.index('def D57_'):]; d57 = d57[:d57.index('\ndef D58_')] if '\ndef D58_' in d57 else d57[:6000]; synthetic = ("inc = dict(label='x', is_current=True, log2_B=10.0" in d57)
    rec('R7_stale_J_control_and_oracle_units', finding_present=(commented or wrong_units or synthetic), exact_coef_assignment_commented=commented, ideal_log2_S_star_wrong_units=wrong_units, D57_rebuilt_check_synthetic=synthetic)

def r8_restore_amendment_schema():
    """R8: the DGP6 reproduce.sh restore --amendment reads ['code']['commit'] but FREEZE_AMENDMENT_harness1.json carries 'amendment_commit' (KeyError); restore never overlays the amended harness over the frozen engine"""
    import glob as _g; rp = os.path.join(a.dgp6_records, 'reproduce.sh'); ams = sorted(_g.glob(os.path.join(a.dgp6_records, 'FREEZE_AMENDMENT_*.json'))); res = dict(reproduce_present=os.path.exists(rp), amendments=[os.path.basename(x) for x in ams])
    if os.path.exists(rp):
        src = open(rp).read(); block = src.split('restore)')[1].split(';;')[0] if 'restore)' in src else ''; reads_only_code_commit = ("['code']['commit']" in block and 'amendment_commit' not in block); overlays = ('harness' in block and 'checkout' in block)
        schemas = [bool((json.load(open(x)).get('code') or {}).get('commit')) or bool(json.load(open(x)).get('amendment_commit')) for x in ams]; incompatible = any(reads_only_code_commit and not bool((json.load(open(x)).get('code') or {}).get('commit')) for x in ams)
        res.update(restore_reads_only_code_commit=reads_only_code_commit, restore_overlays_amended_harness=overlays, amendment_schema_incompatible=incompatible); present = incompatible or not overlays
    else: present = True
    rec('R8_restore_amendment_schema', finding_present=present, **res)

for fn in (r1_proof_kind_binding, r2_compact_sum_transient, r3_plan_admission_and_peak, r4_batch_refusal_boundary, r5_commit_diagnostics_after_poll, r6_skipped_probe_protection, r7_stale_J_control_and_oracle_units, r8_restore_amendment_schema): guard(fn)
OUT['findings_present'] = {k: v.get('finding_present') for k, v in OUT['probes'].items()}; json.dump(OUT, open(a.output, 'w'), indent=1, default=str); print(json.dumps(OUT['findings_present'])); print('written', a.output)
