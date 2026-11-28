"""DGP4 repair probes R1 / R2 / R3 (brief CLAUDE_DGP4_RESIDUAL_MAX_SPEC.md section 2), runnable against ANY source root (before: the pinned parent pgm-eval-02b5f63; after: the frozen commit). Deterministic clock
injections; one real-clock replay of the archived preservation input. usage: dgp4_probes.py --source ROOT --output OUT.json [--replay-archived]"""
import sys, os, json, time, argparse, traceback
from fractions import Fraction as F
ap = argparse.ArgumentParser(); ap.add_argument('--source', required=True); ap.add_argument('--output', required=True); ap.add_argument('--replay-archived', action='store_true'); a = ap.parse_args()
ROOT = os.path.abspath(a.source); sys.path[:0] = [os.path.join(ROOT, 'code/cex/hp'), os.path.join(ROOT, 'code/cex/newarm'), os.path.join(ROOT, 'code/cex/blockres')]
import numpy as np
import coarse_envelope as CE, pac_actions as PA, lifted_decoder as LD, grouped_envelope as GE, unified_planner as UP, unified_pac_planner as UPP, core as CORE
from unified_pac_planner import UPlanner, PAC_OPTS
out = dict(source=ROOT, probes={}); EPS = F(1, 200); DELTA = F(1, 10 ** 6)
def rec(name, **kw): out['probes'][name] = kw; print(json.dumps({name: kw}, default=str)[:600], flush=True)

# ---------------------------------------------------------------- R1: singleton transpose semantics (factor scope (1, 0), entries 1..16)
def r1():
    model = dict(cards=[4, 4], factors=[dict(scope=(1, 0), values=[F(k + 1) for k in range(16)])], evidence={}); clk = CE.Clock(time.monotonic() + 30, {}); B = CE.Budget(CE.CONSTRUCTOR_BYTES); M = CE.canonicalize(model, clk, B)
    res = {}
    for label, classes in (('manual_0011', [[0, 0, 1, 1], [0, 0, 1, 1]]), ('fast', None)):
        if classes is None:
            prof, why = CE.slice_profiles(M, clk, B); classes = [CE.canonical_classes(CE.farthest_split(prof[v], list(range(M.cards[v])), clk), M.cards[v]) for v in range(2)]
        Cz = CE.check_candidate(M, classes, CE.unit_scales(M), clk, B, ratio_product='compact'); groups, gsc = GE.plan_groups(M, Cz, 'G2'); tabs, chg = GE.grouped_upper_tables(M, classes, Cz, groups, gsc, clk, B); ufn = GE.grouped_upper_weight(M, Cz, tabs)
        worst = None
        for z0 in range(4):
            for z1 in range(4):
                W = LD.parent_weight(M, (z0, z1)); c = (classes[0][z0], classes[1][z1]); d = Cz.d[0][z0] * Cz.d[1][z1]; G = ufn(c) * d
                if W > G and (worst is None or W / G > worst[0]): worst = (W / G, W, G, (z0, z1), c)
        res[label] = dict(classes=classes, groups=[list(g) for g in groups], scopes=[list(s) for s in gsc], violation=(dict(ratio=str(worst[0]), weight=str(worst[1]), envelope_x_d=str(worst[2]), state=worst[3], cell=worst[4]) if worst else None))
        B.release(chg)
    # the REAL lifted stream on the FAST classes: prepare, then batches (the cap assertion fires on the parent)
    prof, why = CE.slice_profiles(M, clk, B); classes = [CE.canonical_classes(CE.farthest_split(prof[v], list(range(M.cards[v])), clk), M.cards[v]) for v in range(2)]; Cz = CE.check_candidate(M, classes, CE.unit_scales(M), clk, B, ratio_product='compact')
    S = PA.LiftedStream(2, M, M, [], classes, Cz, 1, EPS, DELTA / 4, dict(PAC_OPTS, budget_obj=B), envelope='G2'); r = S.prepare(time.monotonic() + 30); outcomes = []
    for _ in range(4):
        if S.stage != 'READY': break
        outcomes.append(S.batch(time.monotonic() + 30))
    res['real_stream'] = dict(prepare=r, batches=outcomes, stage=S.stage, closed=(S.closed_reason or '')[:160], defect=S.mech.get('certificate_defect'), max_log2_X=S.maxlogX if S.draws else None)
    rec('R1_transpose_semantics', **res)

# ---------------------------------------------------------------- R2: construction charge ownership
def r2():
    import dense_gen as DG
    model = dict(cards=[2, 2, 2, 2], factors=[dict(scope=(0, 1), values=[F(1), F(2), F(3), F(4)]), dict(scope=(1, 2), values=[F(2), F(1), F(1), F(3)]), dict(scope=(2, 3), values=[F(1), F(1), F(2), F(1)]), dict(scope=(0, 3), values=[F(3), F(1), F(1), F(2)])], evidence={})
    model['cards'] = [4] * 6; model['factors'] = [dict(scope=sc, values=[F(1 + ((i * 7 + j * 3 + sc[0]) % 5)) for i in range(4) for j in range(4)]) for sc in ((0, 1), (1, 2), (2, 3), (3, 4), (4, 5), (0, 5))]       # a 6-cycle: three G2 pair groups
    clk = CE.Clock(time.monotonic() + 30, {}); B = CE.Budget(CE.CONSTRUCTOR_BYTES); M = CE.canonicalize(model, clk, B); classes = [[0, 0, 1, 1]] * 6; Cz = CE.check_candidate(M, classes, CE.unit_scales(M), clk, B, ratio_product='compact'); groups, gsc = GE.plan_groups(M, Cz, 'G2')
    res = dict(groups=[list(g) for g in groups])
    # (a) MEMORY after the first admitted table: a budget whose cap admits exactly one grouped table
    live0 = B.live; first = 2 * (56 + (8 + CE.FRAC_BYTES) * 8) + 64 * 8; Bm = CE.Budget(B.live + first + 1); Bm.live = B.live; err = None
    try: GE.grouped_upper_tables(M, classes, Cz, groups, gsc, clk, Bm)
    except CE.Refused as e: err = e.kind
    res['memory_after_first_table'] = dict(refusal=err, orphaned_bytes=Bm.live - live0, first_table_bytes=first)
    # (b) DEADLINE during the third table: a clock that expires on the third 'before grouped table' poll
    class Clk(CE.Clock):
        def __init__(self): super().__init__(time.monotonic() + 30, {}); self.n = 0
        def poll(self, where):
            if where.startswith('before grouped table'):
                self.n += 1
                if self.n == 3: raise CE.Refused('DEADLINE', 'injected deadline ' + where)
    Bd = CE.Budget(CE.CONSTRUCTOR_BYTES); Bd.live = B.live; err = None
    try: GE.grouped_upper_tables(M, classes, Cz, groups, gsc, Clk(), Bd)
    except CE.Refused as e: err = e.kind
    res['deadline_in_third_table'] = dict(refusal=err, orphaned_bytes=Bd.live - live0)
    # (c) the real stream path: a lifted stream whose grouped construction is refused -> does the stream / planner ledger stay consistent?
    P = UPlanner(model, dict(model_sha256='probe'), 10.0, admission_stop_s=9.0, t_start=PA.tnow(), seed=1, pac=True, lifted=True, envelope='G2'); P.M = CE.canonicalize(model, P.hclock, P.budget); P.canonical_charge = P.budget.live
    S = PA.LiftedStream(2, P.M, P.M, [], classes, CE.check_candidate(P.M, classes, CE.unit_scales(P.M), P.hclock, P.budget, ratio_product='compact'), 1, EPS, DELTA / 4, dict(PAC_OPTS, budget_obj=P.budget), envelope='G2'); live_before = P.budget.live; S.rows = LD.build_rows(P.M, classes, S.Cz, P.hclock, P.budget); S.retained_bytes += S.rows.bytes; S.stage = 'INTEGERIZED'
    # the REAL grouped construction under an injected clock that expires at the second table's entry poll (no substitute callee)
    real_clock = CE.Clock
    class Clk2(CE.Clock):
        def __init__(self, deadline, stats): super().__init__(deadline, stats); self.n = 0
        def poll(self, where):
            if where.startswith('before grouped table'):
                self.n += 1
                if self.n == 2: raise CE.Refused('DEADLINE', 'injected deadline ' + where)
            return super().poll(where)
    CE.Clock = Clk2
    try: r = S.prepare(time.monotonic() + 30)
    finally: CE.Clock = real_clock
    res['stream_refused_grouped'] = dict(result=r, stage=S.stage, closed=(S.closed_reason or '')[:120], live_before=live_before, live_after=P.budget.live, rows_bytes=S.rows.bytes, orphaned_bytes=P.budget.live - live_before - S.rows.bytes, grouped_bytes_attr=getattr(S, 'grouped_bytes', None))
    rec('R2_charge_ownership', **res)

def r2_archived():
    """real-clock replay of the archived preservation_18 input (grid4x4_c32_generic) under the p4 contract; records the ledger identity and the outcome"""
    p = '/Users/adis/Workspace/pgm-records/code/runs/mdi_2026-10-28/DENSE_GENERIC_PAC_INTEGRATION_1/PRESERVATION_18_MANIFEST.json'; man = json.load(open(p)); t = next(x for x in man['tasks'] if x['name'] == 'grid4x4_c32_generic')
    model, binding = CORE.read_uai(t['model']); P = UPlanner(model, binding, 3.85, admission_stop_s=3.5, t_start=PA.tnow(), seed=1, pac=True, lifted=True, envelope='G2'); o = P.run(); m = o['mechanism']
    rec('R2_archived_replay_grid4x4_c32', outcome=o['outcome'], published=o['published'], K=o['K'], ledger_identity=m.get('constructor_live_ledger_identity'), constructor_live=m.get('constructor_live_at_end_bytes'), expected_live=(getattr(P, 'canonical_charge', 0) + sum(c.charged for c in P.cands) + sum(c.charged for c in P.lift_cands) + sum(getattr(S, 'rows', None).bytes if getattr(S, 'rows', None) is not None else 0 for S in P.streams) + sum(getattr(S, 'fine_bytes', 0) + getattr(S, 'grouped_bytes', 0) + getattr(S, 'rmax_bytes', 0) for S in P.streams)), streams=[(S.kind, S.stage, (S.closed_reason or '')[:80]) for S in P.streams], wall=o['wall_s'])

# ---------------------------------------------------------------- R3: parent final timestamp (variable-sized aggregation after the sample)
def r3():
    res = {}
    def planner(model):
        P = UPlanner(model, {}, 3.0, admission_stop_s=2.5, t_start=PA.tnow()); P.M = CE.canonicalize(model, P.hclock, P.budget); P.canonical_charge = P.budget.live; P.t_mark = P.t_start; P.out['mechanism']['positive_mass_witness'] = True; return P
    cases = dict(multi_query=dict(cards=[2, 3], factors=[dict(scope=(0, 1), values=[F(1), F(2), F(1), F(2), F(1), F(1)])], evidence={}), factorless=dict(cards=[3, 2], factors=[dict(scope=(0,), values=[F(1), F(2), F(1)]), dict(scope=(1,), values=[F(1), F(3)])], evidence={}), scalar=dict(cards=[2], factors=[dict(scope=(0,), values=[F(1), F(1)])], evidence={}))
    for name, model in cases.items():
        # (a) injection INSIDE the PARENT finalizer's actual action-history aggregation (UP.Planner.fin called directly: the subclass wrapper's own pre-sample work is not the subject): every .get on an action record
        #     advances the injected clock past the hard deadline; old: the aggregation runs AFTER t_end -> the sample precedes the advance -> COMPLETE; repaired: the aggregation runs before the sample -> DEADLINE, 0 published
        P = planner(model); state = {'now': P.t_start + 0.01, 'gets': 0}
        class TimedAction(dict):
            def get(self, k, d=None):
                state['gets'] += 1; state['now'] = P.hard + 0.01; return super().get(k, d)
        P.out['actions'] = [TimedAction(action='price', actual_s=0.001), TimedAction(action='discover_fast', actual_s=0.002)]
        rows = {}
        for v in range(len(model['cards'])):
            for a_ in range(model['cards'][v]): rows[(v, a_)] = dict(lo=F(1, 4), hi=F(1, 4), point=F(1, 4), guarantee='DETERMINISTIC')
        old = (UP.tnow, UPP.tnow, CE.tnow); UP.tnow = UPP.tnow = CE.tnow = lambda: state['now']
        try: r = UP.Planner.fin(P, 'COMPLETE', rows)
        finally: UP.tnow, UPP.tnow, CE.tnow = old
        res[name + '/action_aggregation'] = dict(outcome=r['outcome'], published=r['published'], K=r['K'], hard_deadline_respected=r['hard_deadline_respected'], gets_on_actions=state['gets'], reported_wall=r['wall_s'], injected_wall=state['now'] - P.t_start, contract_s=3.0, api_boundary='the parent finalizer\'s own authoritative clock read (an OS deschedule after that read is outside any Python function\'s control; the CLI serialization guard is the separate later boundary)')
        # (b) expiry exactly AT the final sample: the clock advances past the deadline on the read made from inside `fin` itself (the authoritative sample), not on the entry poll
        P2 = planner(model); st2 = {'now': P2.t_start + 0.01, 'reads': 0, 'fin_reads': 0}
        def clock():
            st2['reads'] += 1; f = sys._getframe(1)
            if f.f_code.co_name == 'fin': st2['fin_reads'] += 1; st2['now'] = P2.hard + 0.01
            return st2['now']
        UP.tnow = UPP.tnow = CE.tnow = clock
        try: r2_ = UP.Planner.fin(P2, 'COMPLETE', rows)
        finally: UP.tnow, UPP.tnow, CE.tnow = old
        res[name + '/expiry_at_sample'] = dict(outcome=r2_['outcome'], published=r2_['published'], hard_deadline_respected=r2_['hard_deadline_respected'], clock_reads=st2['reads'], direct_reads_in_fin=st2['fin_reads'], suppressed=r2_['mechanism'].get('suppressed_late_rows'))
    src = open(os.path.join(ROOT, 'code/cex/hp/unified_planner.py')).read(); fin_src = src[src.index('    def fin(self, oc, rows_canon, note=None):'):src.index('def plan_and_solve')]; i_end = fin_src.index('t_end = tnow()'); after = fin_src[i_end:]
    res['source_order'] = dict(action_sum_after_sample=("for x in out['actions']" in after or "out['actions'] if" in after), phases_sum_after_sample=("out['phases_s'].items()" in after))
    rec('R3_parent_final_timestamp', **res)

for fn in (r1, r2, r3) + ((r2_archived,) if a.replay_archived else ()):
    try: fn()
    except Exception as e: rec(fn.__name__ + '_ERROR', error=repr(e)[:300], tb=traceback.format_exc()[-1500:])
json.dump(out, open(a.output, 'w'), indent=1, default=str); print('written', a.output)
