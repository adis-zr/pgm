"""DGP6 before / after probes of the nine DGP5-review findings (brief CLAUDE_DGP6_GLOBAL_CONSTRUCTION_SPEC.md section 5), runnable against ANY source root: before = the pinned amended DGP5 source 0d6559a, after = the DGP6 frozen commit.
The review's own probe scripts were NOT supplied; each probe below is written from the finding's description in the brief and records `finding_present` = the failure condition evaluated on this root (True before, False after). Every step is wrapped
so a REPAIRED refusal is recorded instead of aborting. usage: dgp6_probes.py --source ROOT --output OUT.json"""
import sys, os, json, time, argparse, traceback, gc, weakref, itertools, random, math
from fractions import Fraction as F
ap = argparse.ArgumentParser(); ap.add_argument('--source', required=True); ap.add_argument('--output', required=True); a = ap.parse_args()
ROOT = os.path.abspath(a.source); SRC = os.path.join(ROOT, 'code'); sys.path[:0] = [os.path.join(SRC, 'cex/hp'), os.path.join(SRC, 'cex/blockres'), os.path.join(SRC, 'cex/newarm')]
import numpy as np
import coarse_envelope as CE, pac_actions as PA, check_dgp as C, joint_proposal as JP, joint_witness as JW, joint_optimize as JO, check_joint as CJ, joint_stream as JS, residual_max_envelope as RM
from unified_pac_planner import UPlanner, PAC_OPTS
OUT = dict(source=ROOT, probes={}, utc=time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())); EPS = F(1, 200); DELTA = F(1, 10 ** 6)
def rec(name, **kw): OUT['probes'][name] = kw; print(json.dumps({name: kw}, default=str)[:600], flush=True)
def guard(fn):
    try: fn()
    except Exception as e: rec(fn.__name__ + '_ERROR', error=repr(e)[:300], tb=traceback.format_exc()[-1200:])
def stage(model, budget_s=60):
    clk = CE.Clock(time.monotonic() + budget_s, {}); B = CE.Budget(CE.CONSTRUCTOR_BYTES); M = CE.canonicalize(model, clk, B); order, _ = CE.elimination_order(list(M.cards), [tuple(sc) for sc, _ in M.factors], clk, B); return M, order, clk, B
def rand_model(rng, cards, edges):
    facs = [dict(scope=(u, v), values=[F(rng.randint(1, 9), rng.randint(1, 5)) for _ in range(cards[u] * cards[v])]) for (u, v) in edges] + [dict(scope=(v,), values=[F(rng.randint(1, 7)) for _ in range(cards[v])]) for v in range(len(cards))]
    return dict(cards=list(cards), factors=facs, evidence={})

def f1_source_binding():
    """finding 1: the production checker accepts a coefficient pass that OMITS one reciprocal conditional (or the target) because it checks only dominance over the inputs it is handed"""
    M, order, clk, B = stage(C._four_cycle()); cards = list(M.cards); prop, rec_, owned = JP.compile_seed(M, order, JP.PROFILE_PRODUCTION, B, clk); z = prop.order[-1]; parents = tuple(prop.conds[z].parents); res = {}
    own = [0]; srcs = JP.source_tables(M, B, clk, own, V=4096); tid = len(srcs); skipped = None
    for v in prop.order:
        if v == z: continue
        if skipped is None: skipped = v; continue
        srcs.append(JW.reciprocal_table(prop.conds[v], cards, tid, B, clk, own)); tid += 1
    comp = JP.JointCompile(cards, srcs, order, 4096, 16, B, clk, 'max', retain=tuple(sorted(parents + (z,))), owned=own); comp.run(); T = comp.retained_product()
    res['omitted_reciprocal'] = dict(skipped_variable=skipped, checker_all_ok=all(r['ok'] for r in comp.checker_receipts), stages_checked=len(comp.checker_receipts))
    own2 = [0]; srcs2 = [T_ for T_ in JP.source_tables(M, B, clk, own2, V=4096) if T_.origin[0] != 'factor' or T_.origin[1] != 0]; tid = len(srcs2) + 1
    for v in prop.order:
        if v == z: continue
        srcs2.append(JW.reciprocal_table(prop.conds[v], cards, tid, B, clk, own2)); tid += 1
    comp2 = JP.JointCompile(cards, srcs2, order, 4096, 16, B, clk, 'max', retain=tuple(sorted(parents + (z,))), owned=own2); comp2.run(); comp2.retained_product()
    res['omitted_target_factor'] = dict(checker_all_ok=all(r['ok'] for r in comp2.checker_receipts))
    cert_fn = getattr(CJ, 'certify_sources', None); res['independent_certifier_exists'] = cert_fn is not None
    if cert_fn is not None: res['binder_rejects_omitted_reciprocal'] = not cert_fn(M, prop, srcs, z=z)['ok']; res['binder_rejects_omitted_target'] = not cert_fn(M, prop, srcs2, z=z)['ok']; res['binder_accepts_complete'] = cert_fn(M, prop, JP.source_tables(M, B, clk, [0], V=4096) + [JW.reciprocal_table(prop.conds[v], cards, 100 + v, B, clk, [0]) for v in prop.order if v != z], z=z)['ok']
    present = (cert_fn is None) or not (res['binder_rejects_omitted_reciprocal'] and res['binder_rejects_omitted_target'] and res['binder_accepts_complete'])
    B.release(own[0] + own2[0] + owned); rec('F1_independent_source_binding', finding_present=present, **res)

def f2_ownership():
    """finding 2: (a) seed_prop retained after a close between the seed and numeric stages (992 B), (b) the interaction-score dict retained after close, (c) an orphaned charge when interaction_scores is interrupted by its own poll (2,112 B); idempotent close"""
    model, _ = C.load('dg_n8_c4_clique_two'); M, order, clk, B = stage(model); res = {}
    S = JS.JointStream(2, M, M, [], 1, EPS, DELTA / 4, dict(PAC_OPTS, budget_obj=B), mode='joint'); real = S._j_fine_tables
    def fail(deadline): raise PA.Deadline('injected after the seed')
    S._j_fine_tables = fail; r = S.prepare(time.monotonic() + 10, until=time.monotonic() + 10); sp = getattr(S, 'seed_prop', None); res['seed_prop_after_close'] = dict(result=r, retained=(sp is not None), bytes=(getattr(sp, 'bytes', None)), joint_bytes_attr=S.joint_bytes, live=B.live)
    S2 = JS.JointStream(2, M, M, [], 1, EPS, DELTA / 4, dict(PAC_OPTS, budget_obj=CE.Budget(CE.CONSTRUCTOR_BYTES)), mode='joint'); r2 = S2.prepare(time.monotonic() + 10, until=time.monotonic() + 10); S2.pilot_action(time.monotonic() + 10); S2.refine_action(time.monotonic() + 10, time.monotonic() + 20); pairs_ref = S2.pairs; S2._close('probe'); res['pairs_after_close'] = dict(retained=(S2.pairs is not None), entries=(len(pairs_ref) if pairs_ref else 0))
    live0 = B.live; n = len(M.cards)
    class Clk(CE.Clock):
        def __init__(self, d, s): super().__init__(d, s); self.hit = 0
        def poll(self, where):
            if 'interaction' in where: self.hit += 1; raise CE.Refused('DEADLINE', 'injected ' + where)
    rng = random.Random(1); big = rand_model(rng, [2] * 24, [(i, j) for i in range(24) for j in range(i + 1, 24)]); Mb, ob, cb, Bb = stage(big); l0 = Bb.live; ck = Clk(time.monotonic() + 10, {}); kind = None
    try: JO.interaction_scores(Mb, Bb, ck)
    except CE.Refused as e: kind = e.kind
    res['interaction_scores_interrupted'] = dict(refusal=kind, poll_hits=ck.hit, orphaned_bytes=Bb.live - l0)
    S3 = JS.JointStream(2, M, M, [], 1, EPS, DELTA / 4, dict(PAC_OPTS, budget_obj=CE.Budget(CE.CONSTRUCTOR_BYTES)), mode='joint'); S3.prepare(time.monotonic() + 10, until=time.monotonic() + 10); Bq = S3.opts['budget_obj']; S3._close('once'); l1 = Bq.live; S3._close('twice'); res['idempotent_close'] = dict(live_after_first=l1, live_after_second=Bq.live, idempotent=(l1 == Bq.live))
    present = res['seed_prop_after_close']['retained'] or res['pairs_after_close']['retained'] or res['interaction_scores_interrupted']['orphaned_bytes'] > 0 or not res['idempotent_close']['idempotent']
    rec('F2_ownership', finding_present=present, **res)

def f3_admission():
    """finding 3: Conditional.replicate (2,048 -> 4,096 entries) allocates without a charge; under ZERO headroom the allocation must not be reached"""
    rng = random.Random(3); model = rand_model(rng, [4] * 7, [(i, j) for i in range(7) for j in range(i + 1, 7)]); M, order, clk, B = stage(model); cards = list(M.cards); prop, rec_, owned = JP.compile_seed(M, order, JP.PROFILE_PRODUCTION, B, clk)
    c = max(prop.conds.values(), key=lambda c_: c_.family_volume()); extra = [v for v in prop.order if v not in c.parents and v != c.z][0]; newpar = tuple(sorted(c.parents + (extra,), key=lambda p: prop.order.index(p))); B.cap = B.live; l0 = B.live; kind = None; alloc = None
    try:
        rep = c.replicate(newpar, cards) if 'budget' not in c.replicate.__code__.co_varnames else c.replicate(newpar, cards, budget=B); alloc = rep.counts.nbytes
    except CE.Refused as e: kind = e.kind
    res = dict(from_entries=c.family_volume(), to_entries=JP.vol_of(newpar, cards) * cards[c.z], refusal=kind, allocated_bytes=alloc, live_delta=B.live - l0, replicate_takes_budget=('budget' in c.replicate.__code__.co_varnames))
    rec('F3_admission_replication', finding_present=(kind is None and alloc is not None), **res)

def f4_cutoffs():
    """finding 4: a clock crossing the hard cutoff INSIDE the response assembly of a batch (after the single poll) still commits the batch; and inside the prior-epoch diagnostics of an epoch commit still commits the epoch"""
    model, _ = C.load('dg_n8_c4_clique_two'); M, order, clk, B = stage(model); res = {}
    S = JS.JointStream(2, M, M, [], 1, EPS, DELTA / 4, dict(PAC_OPTS, budget_obj=B), mode='joint'); r = S.prepare(time.monotonic() + 10, until=time.monotonic() + 10); assert r == 'READY', (r, S.closed_reason); S.batch(time.monotonic() + 10); t_before = S.cert.t
    state = {'now': 100.0, 'hits': 0}; old = (JS.tnow, PA.tnow, CE.tnow)
    class Timed(np.ndarray):
        def __getitem__(self, k): state['hits'] += 1; state['now'] = 200.0; return super().__getitem__(k)
    S.Dm = [d.view(Timed) for d in S.Dm]; JS.tnow = PA.tnow = CE.tnow = lambda: state['now']
    try: rb = S.batch(150.0, 150.0)
    finally: JS.tnow, PA.tnow, CE.tnow = old
    res['batch_response_assembly'] = dict(result=rb, hits=state['hits'], cert_t_before=t_before, cert_t_after=S.cert.t, committed_past_hard=(S.cert.t > t_before), stage=S.stage)
    S2 = JS.JointStream(2, M, M, [], 1, EPS, DELTA / 4, dict(PAC_OPTS, budget_obj=CE.Budget(CE.CONSTRUCTOR_BYTES)), mode='joint'); S2.prepare(time.monotonic() + 10, until=time.monotonic() + 10); S2.pilot_action(time.monotonic() + 10); n_ep = len(S2.epochs); st2 = {'now': 100.0, 'hits': 0}
    class ZC:
        def __init__(self, inner): self.inner = inner
        def interval(self): st2['hits'] += 1; st2['now'] = 200.0; return self.inner.interval()
        def update_batch(self, X): return self.inner.update_batch(X)
        @property
        def t(self): return self.inner.t
    S2.epoch.zcert = ZC(S2.epoch.zcert); old = (JS.tnow, PA.tnow, CE.tnow); JS.tnow = PA.tnow = CE.tnow = lambda: st2['now']; kind = None
    try: S2._commit_epoch(S2.epoch.prop, 'probe', 150.0, S2.opts['budget_obj'])
    except Exception as e: kind = type(e).__name__
    finally: JS.tnow, PA.tnow, CE.tnow = old
    res['epoch_commit_prior_diagnostics'] = dict(exception=kind, hits=st2['hits'], epochs_before=n_ep, epochs_after=len(S2.epochs), committed_past_deadline=(len(S2.epochs) > n_ep))
    present = res['batch_response_assembly']['committed_past_hard'] or res['epoch_commit_prior_diagnostics']['committed_past_deadline']; rec('F4_epoch_batch_cutoffs', finding_present=present, **res)

def f5_compact_sum_growth():
    """finding 5: the exact checker's sum aligns to the SMALLEST exponent (m << spread): two 128-bit inputs with exponent spread 2^24 allocate ~2^24 bits"""
    a_ = RM.from_fraction_up(F(3)); b_ = (a_[0] - (1 << 24), a_[1]); res = {}
    t0 = time.monotonic(); s = CJ._exact_sum([a_, b_]); dt = time.monotonic() - t0; res['exact_sum'] = dict(result_mantissa_bits=s[1].bit_length(), seconds=round(dt, 4), proportional_to_spread=(s[1].bit_length() > (1 << 20)))
    t0 = time.monotonic(); u = RM.sum_up([a_, b_]); res['sum_up'] = dict(result_bits=u[1].bit_length(), seconds=round(time.monotonic() - t0, 4), upper=(RM.to_fraction(u) >= RM.to_fraction(a_) + RM.to_fraction(b_)))
    rec('F5_compact_sum_growth', finding_present=res['exact_sum']['proportional_to_spread'], **res)

def f6_oracle_objectives():
    """finding 6: the DGP5 oracle promotion on the whole-model n6 cliques compared the candidate against the incumbent's CONSUMED-cap J instead of the best checked unchanged-law candidate (own tightest cap + the common tightest seed S witness) with S / H / d / J rebuilt together; probe = re-derive the selection on dg_n6_c4_clique_two with both comparators"""
    import dgp5_oracle as O5
    res = {}; p = '/Users/adis/Workspace/pgm-records/code/runs/mdi_2026-10-28/DGP2_REPAIR_AND_DIAGNOSIS/oracle/dev_inputs/dg_n6_c4_clique_two.uai'
    import core as CORE; model, binding = CORE.read_uai(p); M, order, clk, B = stage(model, 120); cards = list(M.cards); prop, rec_, owned = JP.compile_seed(M, order, JP.PROFILE_PRODUCTION, B, clk); pairs, chg = JO.interaction_scores(M, B, clk); e = JO.rank_expansions(prop, pairs, cards, 4096)[0]; z = e['z']; parents = tuple(e['new_parents'])
    pk = JW.build_packet(M, prop, z, parents, order, JP.PROFILE_PRODUCTION, B, clk); inc = JW.witnesses_of(pk, pk.cond_ctx, S_ref=None); l2 = lambda x: (RM.log2_up(x) if x[1] else -math.inf); B_tight = min(prop.B, inc['B']); S_ref = min([s for s in (prop.S, inc['S']) if s[1]] + [RM.norm_up(*RM.mul_exact(B_tight, B_tight))])
    log2_eta = math.log2(0.005) + 13.4 - math.log2(6.0); arity = 2 * len(cards) + sum(len(sc) + 1 for sc, _ in M.factors); K = sum(cards); d0 = 1e-6; w0 = prop.work(arity, K)
    inc_consumed = dict(label='seed_consumed', is_current=True, log2_B=prop.log2_B(), log2_S=l2(S_ref), log2_J=math.log2(d0) + JO.H_log2(l2(S_ref), prop.log2_B(), log2_eta), family_volume=prop.conds[z].family_volume(), index=-1)
    inc_best = dict(inc_consumed, label='seed_best_same_law', log2_B=l2(B_tight), log2_J=math.log2(d0) + JO.H_log2(l2(S_ref), l2(B_tight), log2_eta))
    cands = []
    for i, (lab, cond, nominal) in enumerate(JO.frontier_laws(pk, prop, cards, JP.PROFILE_PRODUCTION, 'joint', prop.B)):
        if cond is None: continue
        w = JW.witnesses_of(pk, cond, S_ref=S_ref); conds = dict(prop.conds); conds[z] = cond; newp = JP.Proposal(cards, conds, prop.order, w['B'], w['S'], {}); d = d0 * newp.work(arity, K) / w0; cands.append(dict(label=lab, is_current=False, log2_B=w['log2_B'], log2_S=w['log2_S'], log2_J=math.log2(d) + JO.H_log2(w['log2_S'], w['log2_B'], log2_eta), family_volume=cond.family_volume(), index=i + 1, prop=newp))
    w_c, p_c = JO.select(cands, inc_consumed, 0.01); w_b, p_b = JO.select(cands, inc_best, 0.01)
    res.update(comparator_consumed=dict(winner=w_c['label'], promoted=p_c, inc_log2_J=inc_consumed['log2_J'], win_log2_J=w_c['log2_J']), comparator_best_same_law=dict(winner=w_b['label'], promoted=p_b, inc_log2_J=inc_best['log2_J'], win_log2_J=w_b['log2_J']), log2_B_consumed=prop.log2_B(), log2_B_tight=l2(B_tight), whole_model=(len(parents) + 1 == len(cards)), dgp5_frontier_grid=('geometric in log2 C' if 'log2_Cmin + (log2_Cmax - log2_Cmin)' in open(os.path.join(SRC, 'cex/hp/joint_optimize.py')).read() else 'affine in C'))
    pk.release(); B.release(owned + chg); rec('F6_oracle_objectives_stale_J', finding_present=(p_c and not p_b) or (res['dgp5_frontier_grid'] == 'geometric in log2 C'), **res)

def f7_cap_grid():
    src = open(os.path.join(SRC, 'cex/hp/joint_optimize.py')).read(); geometric = 'log2_Cmin + (log2_Cmax - log2_Cmin) * i' in src; affine = 'Cmin + (Cmax - Cmin) * i' in src or 'affine' in src.lower()
    rec('F7_cap_grid_identity', finding_present=geometric, grid_in_log2_C=geometric, affine_marker=affine)

def f8_epoch_diagnostics():
    """finding 8: pooled X_mean / ESS / largest_share / Z_over_Ucap across epochs with different caps in the joint stream's diagnostics; D41 lacks injection hit counters"""
    model, _ = C.load('dg_n8_c4_clique_two'); M, order, clk, B = stage(model); S = JS.JointStream(2, M, M, [], 1, EPS, DELTA / 4, dict(PAC_OPTS, budget_obj=B), mode='joint'); S.prepare(time.monotonic() + 10, until=time.monotonic() + 10); S.pilot_action(time.monotonic() + 10); a1 = S.refine_action(time.monotonic() + 10, time.monotonic() + 30)
    if not a1.get('promoted'):                                                                           # force a second epoch with a different cap for the probe
        pairs, chg = JO.interaction_scores(M, B, clk); e = JO.rank_expansions(S.epoch.prop, pairs, list(M.cards), 4096)[0]; pk = JW.build_packet(M, S.epoch.prop, e['z'], tuple(e['new_parents']), order, JP.PROFILE_PRODUCTION, B, clk); cond = [c for _, c, _ in JO.frontier_laws(pk, S.epoch.prop, list(M.cards), JP.PROFILE_PRODUCTION, 'moment_only', S.epoch.prop.B) if c is not None][0]
        w = JW.witnesses_of(pk, cond, S_ref=S.epoch.prop.S); conds = dict(S.epoch.prop.conds); conds[e['z']] = cond; newp = JP.Proposal(list(M.cards), conds, S.epoch.prop.order, w['B'], w['S'], {}); B.charge(newp.bytes, 'probe'); S.joint_bytes += newp.bytes; S._commit_epoch(newp, 'probe', time.monotonic() + 5, B); pk.release()
    for _ in range(3): S.batch(time.monotonic() + 10)
    d = S.diagnostics(); pooled = [k for k in ('X_mean', 'ESS_DIAGNOSTIC', 'largest_share', 'Z_over_Ucap_EB_DIAGNOSTIC', 'log2_Zhat_over_Ucap_DIAGNOSTIC') if d.get(k) is not None]
    src = open(os.path.join(SRC, 'cex/hp/check_dgp.py')).read(); d41 = src[src.index('def D41_'):]; d41 = d41[:d41.index('\ndef D42_')] if '\ndef D42_' in d41 else d41[:4000]; hits = ('hits' in d41 or 'hit_count' in d41 or 'injection_hits' in d41)
    rec('F8_epoch_diagnostics_and_D41', finding_present=(len(pooled) > 0 and len(S.epochs) > 1) or not hits, epochs=len(S.epochs), caps=[round(e_.B_eff_log2, 3) for e_ in S.epochs], pooled_fields_present=pooled, D41_has_injection_hit_counters=hits)

def f9_reproduction():
    """finding 9: the harness resolves model paths from absolute original-workstation paths in the manifests; no resolver"""
    rp = os.path.join(SRC, 'cex/hp/run_dgp5.py'); src = open(rp).read() if os.path.exists(rp) else ''; has_resolver = ('resolve_input' in src and os.path.exists(os.path.join(SRC, 'cex/hp/dgp_paths.py')))
    man = '/Users/adis/Workspace/pgm-records/code/runs/mdi_2026-10-28/DGP5_JOINT_CONSTRUCTION/MAIN_MANIFEST.json'; absolute = all(t['model'].startswith('/Users/adis/Workspace/') for t in json.load(open(man))['tasks']) if os.path.exists(man) else None
    rec('F9_reproduction_path_resolution', finding_present=(not has_resolver), harness_has_resolver=has_resolver, manifest_paths_absolute_workstation=absolute)

for fn in (f1_source_binding, f2_ownership, f3_admission, f4_cutoffs, f5_compact_sum_growth, f6_oracle_objectives, f7_cap_grid, f8_epoch_diagnostics, f9_reproduction): guard(fn)
OUT['findings_present'] = {k: v.get('finding_present') for k, v in OUT['probes'].items()}; json.dump(OUT, open(a.output, 'w'), indent=1, default=str); print(json.dumps(OUT['findings_present'])); print('written', a.output)
