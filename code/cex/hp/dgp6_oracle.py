"""DGP6 oracle harness (brief section 6 'Oracle panel'; PROTOCOL.md section 5): for one <= 2^16-state model -- (1) exact enumeration (dgp2_oracle: W per state, Z, singleton marginals; vectorized floating law quantities for every law);
(2) the production SEED (joint_proposal.compile_seed, production profile) with its float law quantities and (<= 4,096 states) the exact-rational check; (3) the production-like GLOBAL construction on BOTH graphs with the brief's finite
optimizer limits (the same seed, source circuits, eta from the pilot Z_proxy of a real GlobalStream on this model, box, p = 16 / 64 phases, <= 32 evaluations, 17-point segment): G0 (the seed contexts) and G1 (the production graph) each
yielding the JOINT law + the CAP_ONLY (min log B) and MOMENT_ONLY (min log S) endpoints -- every actual quantized law recomputed through the compact circuits from its counts and independently certified; (4) the corrected local DGP5 law
(joint_optimize frontier with the affine grid; labelled reference); (5) the oracle-only floor q = p, B = Z (ideal law; never a candidate); (6) the production trajectory of the real GlobalStream (what the planner would commit) reported
separately; (7) --replay: the accepted certificate replayed for 2^18 draws x seeds 1 / 2 / 3 for the laws in the FROZEN priority order (seed, G0 joint, G1 joint, ideal q = p; then the cap-only / moment-only G1 endpoints; then the rest),
each with its OWN implemented cap and the tight cap paired on identical draws (dgp3_oracle.replay_fine_law). Per law: checked B / S, enumerated true max weight R*, M2 = S_0 / Z_0^2, per-query second moments, witness slack (B / R*, S / S_0),
quantization loss (float vs checked log2 B / S at lambda), table volumes, work counts, costs; identical laws / whole-model graphs classified, never dropped. ORACLE ONLY: enumeration, Z_0, ideal laws never reach production. usage:
dgp6_oracle.py MODEL.uai OUT.json [--cap-s 100] [--replay] [--replay-laws LIST] [--replay-draws 262144] [--seeds 1,2,3] [--continue]"""
import sys, os, json, time, math, argparse, itertools, hashlib
from fractions import Fraction as F
import numpy as np
HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, HERE); sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(HERE)), 'cex', 'newarm')); sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(HERE)), 'cex', 'blockres'))
import coarse_envelope as CE, pac_actions as PA, integrated as IG, core as CORE, dgp2_oracle as O2, dgp3_oracle as O3
import joint_proposal as JP, joint_witness as JW, joint_optimize as JO, check_joint as CJ, joint_stream as JS
import global_circuit as GC, global_optimize as GO, check_global as CG, global_stream as GS
from residual_max_envelope import ZERO, norm_up, from_fraction_up, to_fraction, mul_exact, log2_up
from dgp2_oracle import EPS, DELTA, CHECKPOINTS, fl, lg, Deadline, tnow
from unified_pac_planner import PAC_OPTS
PROF = dict(GS.PROFILE_GLOBAL); LN2 = math.log(2.0)
REPLAY_PRIORITY = ['seed', 'G0_joint', 'G1_joint', 'ideal_q_eq_p', 'G1_cap_only', 'G1_moment_only', 'G0_cap_only', 'G0_moment_only', 'local_dgp5']          # frozen (PROTOCOL.md section 5): the first four on every anchor before any endpoint replay


def law_logq(prop, states):
    n = len(prop.cards); lq = np.zeros(states.shape[0])
    for v in prop.order:
        c = prop.conds[v]; rows = c.row_index(states); lq += np.log2(c.counts[rows, states[:, v]].astype(float))
    return lq - JP.D_BITS * n


def law_record(prop, states, logW0, G, mu, label, extra=None):
    q = CG.float_law_quantities(prop, states, logW0, G, mu); rec = dict(label=label, proposal=prop.record()); rec.update({k: (float(v) if isinstance(v, (float, np.floating)) else v) for k, v in q.items()})
    rec['log2_B_over_Rstar'] = prop.log2_B() - q['log2_B_star']; rec['log2_S_over_Sstar'] = prop.log2_S() - q['log2_S_star']; rec['log2_B_over_Z0'] = prop.log2_B() - q['log2_Z0']; rec['max_log2_X_implemented'] = q['log2_B_star'] - prop.log2_B(); rec.update(extra or {}); return rec


def construct(M, prop_seed, order, cards, parents, graph_label, log2_eta, d_seed, arity_sum, Kq, mode, deadline, B, clk, states, logW0, G, mu):
    """the production-like global construction on one graph with one objective: plans, replicated seed, checked reference, bounded L-BFGS-B, segment, ONE quantized candidate certified; -> (record, Proposal | None)"""
    t0 = tnow(); rec = dict(graph=graph_label, objective=mode, parents={int(v): list(parents[v]) for v in parents}, total_entries=sum(JP.vol_of(parents[v], cards) * cards[v] for v in prop_seed.order))
    try:
        PB, PS = GC.build_plans(M, prop_seed.order, parents, order, V=PROF['V_coef'], fanin=PROF['fanin'], budget=B, clock=clk); rec['plans'] = dict(cap=PB.record(), moment=PS.record())
        alias = all(tuple(parents[v]) == tuple(prop_seed.conds[v].parents) for v in prop_seed.order); p1 = prop_seed if alias else GO.replicate_graph(prop_seed, parents, cards, budget=B); rec['alias_G0'] = alias
        tr = tnow(); cB_ref, _ = GC.compact_evaluate(PB, M, p1, B, clk); cS_ref, _ = GC.compact_evaluate(PS, M, p1, B, clk); kB = CG.certify(PB, M, p1, cB_ref, clk, budget=B, order_elim=order, kind='cap'); kS = CG.certify(PS, M, p1, cS_ref, clk, budget=B, order_elim=order, kind='moment'); rec['reference'] = dict(seconds=tnow() - tr, log2_B=kB.get('log2'), log2_S=kS.get('log2'), ok=kB['ok'] and kS['ok'], consumed_log2_B=prop_seed.log2_B(), consumed_log2_S=prop_seed.log2_S())
        B_tight = min(prop_seed.B, kB['value']); S_ref = min([s for s in (prop_seed.S, kS['value']) if s[1]] + [norm_up(*mul_exact(B_tight, B_tight))]); l2 = lambda x: (log2_up(x) if x[1] else -math.inf)
        w0 = prop_seed.work(arity_sum, Kq); d0 = d_seed; d1 = d_seed * p1.work(arity_sum, Kq) / w0; log_eta = log2_eta * LN2
        FB = GC.FloatCircuit(PB, GC.source_logs(M, 1), cards); FS = GC.FloatCircuit(PS, GC.source_logs(M, 2), cards); t_seed = FB.logits_from_counts(p1); o0 = GC.objective(FB, FS, t_seed, log_eta, None, mode); rec['float_seed'] = dict(log2_B=o0['logB'] / LN2, log2_S=o0['logS'] / LN2)
        opt = GO.BoundedLBFGS(FB, FS, log_eta, mode, deadline, PROF['lbfgs_hard_total']); to = tnow(); endpoint, phases = opt.run(t_seed); rec['optimizer'] = dict(seconds=tnow() - to, evaluations=opt.evals, cache_hits=opt.cache_hits, phases=phases, endpoint=({k: v for k, v in endpoint.items() if k != 't'} if endpoint else None))
        if endpoint is None: rec['status'] = 'OPTIMIZER_FAILED'; return rec, None
        seg, best, (rows_seed, rows_opt) = GO.segment_scores(FB, FS, t_seed, endpoint['t'], log_eta, math.log(d1), mode, deadline, PROF['segment_points']); rec['segment'] = dict(points=seg, best=best)
        if best is None or best['lam'] == 0: rec['status'] = 'SEGMENT_SELECTED_SEED' if best is not None else 'SEGMENT_FAILED'; rec['identical_to_seed'] = True; return rec, None
        tq = tnow(); conds = GO.quantize_segment(FB, rows_seed, rows_opt, best['lam'], cards, prop_seed.order, parents, budget=B); same = all(np.array_equal(conds[v].counts, p1.conds[v].counts) for v in prop_seed.order); rec['quantization'] = dict(seconds=tnow() - tq, lam=best['lam'], identical_to_seed=same)
        if same: rec['status'] = 'QUANTIZED_TO_SEED'; rec['identical_to_seed'] = True
        newp = JP.Proposal(cards, conds, prop_seed.order, ZERO, ZERO, dict(kind='oracle_global', graph=graph_label, objective=mode, lam=best['lam'])); tc = tnow(); cB, _ = GC.compact_evaluate(PB, M, newp, B, clk); cS, _ = GC.compact_evaluate(PS, M, newp, B, clk); kB2 = CG.certify(PB, M, newp, cB, clk, budget=B, order_elim=order, kind='cap'); kS2 = CG.certify(PS, M, newp, cS, clk, budget=B, order_elim=order, kind='moment')
        rec['certification'] = dict(seconds=tnow() - tc, ok=kB2['ok'] and kS2['ok'], log2_B=kB2.get('log2'), log2_S=kS2.get('log2'), why=(kB2.get('why') or kS2.get('why')), float_at_lambda=dict(log2_B=best['logB'] / LN2, log2_S=best['logS'] / LN2), quantization_loss_bits=dict(B=(kB2.get('log2') or 0) - best['logB'] / LN2, S=(kS2.get('log2') or 0) - best['logS'] / LN2))
        if not rec['certification']['ok']: rec['status'] = 'CERTIFIER_REJECTED'; return rec, None
        newp.B = kB2['value']; newp.S = min(kS2['value'], norm_up(*mul_exact(kB2['value'], kB2['value']))); newp.sha256 = hashlib.sha256(repr((newp.order, [(v, newp.conds[v].sha256) for v in newp.order], newp.B, newp.S)).encode()).hexdigest()
        dc = d_seed * newp.work(arity_sum, Kq) / w0; Hc = JO.H_log2(l2(newp.S), l2(newp.B), log2_eta, mode); H_best = JO.H_log2(l2(S_ref), l2(B_tight), log2_eta, mode); H_cons = JO.H_log2(l2(S_ref), l2(prop_seed.B), log2_eta, mode)
        rec['selection'] = dict(candidate_log2_J=math.log2(dc) + Hc, best_same_law_log2_J=math.log2(d0) + H_best, consumed_log2_J=math.log2(d0) + H_cons, promoted_vs_best=(math.log2(dc) + Hc <= math.log2(d0) + H_best + math.log2(1 - PROF['promotion_margin'])), promoted_vs_consumed=(math.log2(dc) + Hc <= math.log2(d0) + H_cons + math.log2(1 - PROF['promotion_margin'])), B_tight_log2=l2(B_tight), S_ref_log2=l2(S_ref), d_hat=dict(seed=d0, graph=d1, candidate=dc), witness_only_available=(B_tight < prop_seed.B), cap_nonincreasing_checked=(not (newp.B > prop_seed.B)))
        rec['status'] = 'CANDIDATE' if not same else 'QUANTIZED_TO_SEED'; rec['seconds'] = tnow() - t0; return rec, newp
    except (JP.RefusedJoint, CE.Refused) as e: rec['status'] = 'REFUSED'; rec['kind'] = getattr(e, 'kind', type(e).__name__); rec['why'] = str(getattr(e, 'reason', e))[:200]; rec['seconds'] = tnow() - t0; return rec, None
    finally: rec.setdefault('seconds', tnow() - t0)


def main():
    ap = argparse.ArgumentParser(); ap.add_argument('model'); ap.add_argument('out'); ap.add_argument('--cap-s', type=float, default=100.0); ap.add_argument('--replay', action='store_true'); ap.add_argument('--replay-laws', default=None, help='comma list from REPLAY_PRIORITY (default: the frozen order)'); ap.add_argument('--replay-draws', type=int, default=1 << 18); ap.add_argument('--seeds', default='1,2,3'); ap.add_argument('--continue', dest='cont', action='store_true'); a = ap.parse_args()
    t_start = tnow(); deadline = t_start + a.cap_s; seeds = [int(x) for x in a.seeds.split(',')]; model, binding = CORE.read_uai(a.model); prev = json.load(open(a.out)) if (a.cont and os.path.exists(a.out)) else {}
    out = dict(model=os.path.abspath(a.model), binding=binding, profile={k: v for k, v in PROF.items() if not isinstance(v, (list, tuple))}, cap_s=a.cap_s, replay_requested=a.replay, utc=time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()), phases=dict(prev.get('phases') or {}), censored=[], continued_from=(dict(utc=prev.get('utc'), wall_s=prev.get('wall_s'), censored=prev.get('censored')) if prev else None), replays=dict(prev.get('replays') or {}), replay_priority=REPLAY_PRIORITY)
    clk = CE.Clock(deadline, {}); B = CE.Budget(CE.CONSTRUCTOR_BYTES); M = CE.canonicalize(model, clk, B); n = len(M.cards); cards = list(M.cards); assert math.prod(cards) <= 1 << 16
    props = {}; laws = {}
    try:
        t0 = tnow(); enum = O2.enumerate_original(M, deadline); out['phases']['enumeration'] = tnow() - t0; Z = enum['Z']; Z0 = Z / M.scalar; states = np.array(enum['states'], dtype=np.int64); logW0 = CJ.oracle_logW0(M, states); lZ0 = CJ._logsumexp2(logW0)
        K = sum(cards); G = np.zeros((states.shape[0], K)); j = 0
        for v in range(n):
            for a_ in range(cards[v]): G[:, j] = (states[:, v] == a_).astype(float); j += 1
        pf = np.exp2(logW0 - lZ0); mu = (pf[:, None] * G).sum(axis=0); W0_frac = [w / M.scalar for w in enum['W']]
        out['original'] = dict(Z=str(Z), log2_Z=lg(Z), log2_Z0=lg(Z0), log2_Z0_float_oracle=lZ0, scalar=str(M.scalar), K=K, n=n, cards=cards, states=int(states.shape[0]))
        # ---- (2) seed
        order, vols = CE.elimination_order(cards, [tuple(sc) for sc, _ in M.factors], clk, B); t0 = tnow(); prop_seed, rec_seed, owned = JP.compile_seed(M, order, JP.PROFILE_PRODUCTION, B, clk); out['phases']['seed'] = tnow() - t0
        out['seed'] = dict(record={k: v for k, v in rec_seed.items() if k != 'plan'}, law=law_record(prop_seed, states, logW0, G, mu, 'seed'), exact_check=({k_: v_ for k_, v_ in CJ.ref_check_law(M, prop_seed).items() if k_ not in ('Z0', 'Rstar', 'S0')} if states.shape[0] <= 4096 else dict(note='exact-rational check restricted to <= 4,096 states; the floating quantities are exhaustive floating diagnostics')))
        props['seed'] = prop_seed; laws['seed'] = out['seed']['law']
        # ---- (3a) the real GlobalStream on this model: pilot Z_proxy (the production selector) + the production trajectory (separately reported)
        t0 = tnow(); S = GS.GlobalStream(2, M, M, [], 1, EPS, DELTA / 4, dict(PAC_OPTS, budget_obj=CE.Budget(CE.CONSTRUCTOR_BYTES)), mode='global'); r = S.prepare(deadline, until=deadline); pil = S.pilot_action(deadline) if r == 'READY' else None; out['phases']['stream_seed_pilot'] = tnow() - t0
        out['stream'] = dict(prepare=r, closed=S.closed_reason, pilot=pil, seed_matches_offline=(r == 'READY' and S.epochs[0].prop.sha256 == prop_seed.sha256), cap_consumed_log2_W0=(S.epochs[0].B_eff_log2 if r == 'READY' else None), eps_num=(S.eps_num if r == 'READY' else None))
        zp = (pil or {}).get('log2_Z_proxy_fit'); d_seed = (pil or {}).get('d_seed_s_per_draw') or 1e-6; log2_eta = math.log2(float(EPS)) + (zp if zp is not None else lZ0) - math.log2(6.0); log2_eta_oracle = math.log2(float(EPS)) + lZ0 - math.log2(6.0)
        out['selector'] = dict(log2_Z_proxy_fit=zp, log2_Z0_true=lZ0, log2_eta_production=log2_eta, log2_eta_oracle_Z=log2_eta_oracle, proxy_error_bits=((zp - lZ0) if zp is not None else None), note='the production selector uses the pilot Z_proxy (heuristic); eta is pinned for every construction below')
        arity_sum = 2 * n + sum(len(sc) + 1 for sc, _ in M.factors); Kq = K
        if r == 'READY':
            t0 = tnow(); att = S.optimize_action(deadline, deadline + 1000.0) if S.can_optimize() else dict(status='NOT_APPLICABLE'); act = S.activation_action(deadline) if S.can_activate() else None
            out['production_trajectory'] = dict(attempt={k: v for k, v in att.items() if k not in ('segment', 'plans')}, segment_best=((att.get('segment') or {}).get('best')), activation=act, epochs=[e.record for e in S.epochs], final_law=(law_record(S.epoch.prop, states, logW0, G, mu, 'production_final') if S.epoch is not None and S.epoch.prop is not None else None), seconds=tnow() - t0, note='what the real stream commits (the ONE bounded attempt + <= 2 activation batches); separately reported')
        S._close('oracle')
        # ---- (3b) the constructions on G0 and G1 x {joint, cap_only, moment_only} with the pinned eta / box / limits
        pairs, chg = JO.interaction_scores(M, B, clk); parents0 = {v: tuple(prop_seed.conds[v].parents) for v in prop_seed.order}; parents1, g1rec = GO.select_g1(prop_seed, pairs, cards, PROF['V_family']); out['graphs'] = dict(G0=dict(parents={int(v): list(parents0[v]) for v in parents0}, total_entries=sum(prop_seed.conds[v].family_volume() for v in prop_seed.order)), G1=dict(g1rec, parents={int(v): list(parents1[v]) for v in parents1}), whole_model=any(len(parents1[v]) + 1 == n for v in prop_seed.order))
        out['constructions'] = {}
        for graph_label, parents in (('G1', parents1), ('G0', parents0)):
            for mode in ('joint', 'cap_only', 'moment_only'):
                if tnow() >= deadline: raise Deadline('construction %s %s' % (graph_label, mode))
                key = '%s_%s' % (graph_label, mode); rec_c, newp = construct(M, prop_seed, order, cards, parents, graph_label, log2_eta, d_seed, arity_sum, Kq, mode, deadline, B, clk, states, logW0, G, mu); out['constructions'][key] = rec_c
                if newp is not None and not rec_c.get('identical_to_seed'): props[key] = newp; laws[key] = law_record(newp, states, logW0, G, mu, key, dict(graph=graph_label, objective=mode, selection=rec_c.get('selection'), quantization_loss_bits=(rec_c.get('certification') or {}).get('quantization_loss_bits'), exact_check=({k_: v_ for k_, v_ in CJ.ref_check_law(M, newp).items() if k_ not in ('Z0', 'Rstar', 'S0')} if (states.shape[0] <= 4096 and mode == 'joint') else None)))        # exact-rational checks (<= 4,096 states) on the seed and the two joint laws; the endpoints carry the exhaustive floating quantities
                else: laws[key] = dict(label=key, identical_to_seed=True, status=rec_c.get('status'), graph=graph_label, objective=mode)
                print(json.dumps(dict(model=os.path.basename(a.model), construction=key, status=rec_c.get('status'), log2_B=((rec_c.get('certification') or {}).get('log2_B')), log2_S=((rec_c.get('certification') or {}).get('log2_S')), M2=(laws[key].get('log2_M2')), seconds=round(rec_c.get('seconds') or 0, 2)), default=str), flush=True)
                # G0 + joint: the law the SEED circuits reproduce; G1 alias -> the same as G0 (classified, never dropped)
        # ---- (4) the corrected local DGP5 law (labelled reference): first family + affine frontier at V 4,096, joint objective, own witnesses
        if tnow() < deadline:
            t0 = tnow()
            try:
                exps = JO.rank_expansions(prop_seed, pairs, cards, PROF['V_family']); fam = exps[0] if exps else JO.choose_retune(prop_seed, pairs, cards); z = fam['z']; parents_f = tuple(fam['new_parents']); pk = JW.build_packet(M, prop_seed, z, parents_f, order, JP.PROFILE_PRODUCTION, B, clk, deadline_fn=(lambda: tnow() >= deadline))
                inc = JW.witnesses_of(pk, pk.cond_ctx, S_ref=None); B_tight = min(prop_seed.B, inc['B']); S_ref = min([s for s in (prop_seed.S, inc['S']) if s[1]] + [norm_up(*mul_exact(B_tight, B_tight))]); l2 = lambda x: (log2_up(x) if x[1] else -math.inf); w0 = prop_seed.work(arity_sum, Kq)
                incumbent = dict(label='seed_best_same_law', is_current=True, log2_B=l2(B_tight), log2_S=l2(S_ref), log2_H=JO.H_log2(l2(S_ref), l2(B_tight), log2_eta), family_volume=prop_seed.conds[z].family_volume(), index=-1, d_hat=d_seed); incumbent['log2_J'] = math.log2(d_seed) + incumbent['log2_H']; cands = []
                for i, (lab, cond, nominal) in enumerate(JO.frontier_laws(pk, prop_seed, cards, JP.PROFILE_PRODUCTION, 'joint', prop_seed.B)):
                    if cond is None: continue
                    w = JW.witnesses_of(pk, cond, S_ref=S_ref); conds = dict(prop_seed.conds); conds[z] = cond; np_ = JP.Proposal(cards, conds, prop_seed.order, w['B'], w['S'], dict(kind='local_dgp5', label=lab)); d = d_seed * np_.work(arity_sum, Kq) / w0; H = JO.H_log2(w['log2_S'], w['log2_B'], log2_eta); cands.append(dict(label=lab, is_current=False, prop=np_, log2_B=w['log2_B'], log2_S=w['log2_S'], log2_H=H, log2_J=math.log2(d) + H, family_volume=cond.family_volume(), index=i + 1, d_hat=d))
                win, prom = JO.select(cands, incumbent, PROF['promotion_margin']); pk.release(); out['local_dgp5'] = dict(family=dict(z=z, parents=list(parents_f), whole_model=(len(parents_f) + 1 == n)), winner=win['label'], promoted=prom, incumbent_log2_J=incumbent['log2_J'], winner_log2_J=win['log2_J'], grid='affine in C (DGP6 amendment of the DGP5 utility)', seconds=tnow() - t0, note='the corrected local DGP5 law: a labelled REFERENCE (not a DGP6 candidate)')
                if prom: props['local_dgp5'] = win['prop']; laws['local_dgp5'] = law_record(win['prop'], states, logW0, G, mu, 'local_dgp5', dict(reference='corrected local DGP5 law'))
                else: laws['local_dgp5'] = dict(label='local_dgp5', identical_to_seed=True, status='KEPT_SEED')
            except (JP.RefusedJoint, CE.Refused) as e: out['local_dgp5'] = dict(refused=getattr(e, 'kind', type(e).__name__), reason=str(getattr(e, 'reason', e))[:160], seconds=tnow() - t0)
        # ---- (5) the ideal floor q = p, B = Z (oracle only)
        laws['ideal_q_eq_p'] = dict(label='ideal_q_eq_p', log2_Z0=lZ0, log2_B_star=lZ0, log2_S_star=2 * lZ0, log2_M2=0.0, log2_B_over_Rstar=0.0, log2_B_star_over_Z0=0.0, note='ORACLE-ONLY certificate floor: q = p exactly (X = 1 on every state), B = Z_0, S_0 = sum W_0^2 / p = Z_0^2 -> M2 = 1 (log2 0); never a deployable candidate')
        # ---- classification
        shas = {k: p_.sha256 for k, p_ in props.items()}; groups = {}
        for k, h in shas.items(): groups.setdefault(h, []).append(k)
        out['classification'] = dict(identical_laws=[v for v in groups.values() if len(v) > 1], G1_alias_G0=g1rec['alias_G0'], whole_model=out['graphs']['whole_model'], laws_recorded=sorted(laws), actual_laws=sorted(props))
        out['laws'] = laws
        # ---- (7) replays in the frozen priority order (each law with its own implemented cap + the tight cap on identical draws)
        if a.replay:
            alpha = float(DELTA / 4) / K; eps_num = out['stream']['eps_num'] or 1e-11; cap_margin = (S.epochs[0].record['constants']['cap_margin'] if S.epochs else 0.0); want = (a.replay_laws.split(',') if a.replay_laws else REPLAY_PRIORITY)
            for name in want:
                if name in out['replays'] and O3.complete_record(out['replays'][name]): continue
                if name == 'ideal_q_eq_p':
                    if tnow() >= deadline: out['replays'][name] = dict(censored='deadline'); continue
                    t0 = tnow(); qlog = logW0 - lZ0; rep = dict(law=name, ideal=True, log2_cap_implemented_over_Z0=0.0, log2_cap_tight_over_Z0=0.0, caps={})
                    rep['caps']['implemented'] = O3.replay_fine_law(enum['states'], W0_frac, Z0, G, mu, qlog, 0.0, K, alpha, eps_num, seeds, a.replay_draws, deadline, name + ':implemented'); rep['caps']['tight'] = rep['caps']['implemented']; rep['seconds'] = tnow() - t0; out['replays'][name] = rep
                else:
                    p_ = props.get(name)
                    if p_ is None: out['replays'][name] = dict(not_available=True, reason=(laws.get(name) or {}).get('status', 'identical to the seed or not constructed')); continue
                    if tnow() >= deadline: out['replays'][name] = dict(censored='deadline'); continue
                    t0 = tnow(); qlog = law_logq(p_, states); R_star = laws[name]['log2_B_star'] - lZ0; B_impl = p_.log2_B() + cap_margin - lZ0
                    rep = dict(law=name, proposal_sha256=p_.sha256, same_as_seed=(p_.sha256 == prop_seed.sha256), log2_cap_implemented_over_Z0=B_impl, log2_cap_tight_over_Z0=R_star, caps={})
                    for capname, caplog in (('implemented', B_impl), ('tight', R_star)): rep['caps'][capname] = O3.replay_fine_law(enum['states'], W0_frac, Z0, G, mu, qlog, caplog, K, alpha, eps_num, seeds, a.replay_draws, deadline, name + ':' + capname)
                    rep['seconds'] = tnow() - t0; out['replays'][name] = rep
                print(json.dumps(dict(model=os.path.basename(a.model), replay=name, worst=[(out['replays'][name].get('caps', {}).get('implemented', {}).get('seeds', {}).get(str(s_), {}).get('checkpoints') or [{}])[-1].get('worst_radius') for s_ in seeds] if out['replays'][name].get('caps') else out['replays'][name], seconds=round(out['replays'][name].get('seconds') or 0, 1)), default=str), flush=True)
        B.release(owned + chg)
    except Deadline as e: out['censored'].append(str(e))
    out['wall_s'] = tnow() - t_start; json.dump(out, open(a.out, 'w'), indent=1, default=str)
    print(json.dumps(dict(model=os.path.basename(a.model), wall=round(out['wall_s'], 2), censored=out['censored'], laws={k: (round(v['log2_B_star'] - v['log2_Z0'], 3), round(v['log2_M2'], 3)) for k, v in (out.get('laws') or {}).items() if 'log2_M2' in v and 'log2_Z0' in v}), default=str))


if __name__ == '__main__': main()
