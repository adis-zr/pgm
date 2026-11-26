"""DGP6 development smoke test of the circuit / optimizer / checker modules on tiny models (charged under dgp6_dev; not a control)"""
import sys, os, json, time, math, random
sys.path[:0] = [os.path.join(os.path.dirname(os.path.abspath(__file__))), os.path.join(os.path.dirname(os.path.abspath(__file__)), '../blockres'), os.path.join(os.path.dirname(os.path.abspath(__file__)), '../newarm')]
from fractions import Fraction as F
import numpy as np
import coarse_envelope as CE, check_dgp as C, joint_proposal as JP, joint_optimize as JO, check_joint as CJ, global_circuit as GC, global_optimize as GO, check_global as CG
from residual_max_envelope import to_fraction, log2_up
out = {}
def stage(model, budget_s=60):
    clk = CE.Clock(time.monotonic() + budget_s, {}); B = CE.Budget(CE.CONSTRUCTOR_BYTES); M = CE.canonicalize(model, clk, B); order, _ = CE.elimination_order(list(M.cards), [tuple(sc) for sc, _ in M.factors], clk, B); return M, order, clk, B
def run(name, model):
    t0 = time.monotonic(); M, order, clk, B = stage(model); cards = list(M.cards); prop, rec, owned = JP.compile_seed(M, order, JP.PROFILE_PRODUCTION, B, clk); live0 = B.live
    parents0 = {v: tuple(prop.conds[v].parents) for v in prop.order}
    PB, PS = GC.build_plans(M, prop.order, parents0, order); r = dict(n=len(cards), cards=cards, planB=PB.record(), planS=PS.record())
    FB = GC.FloatCircuit(PB, GC.source_logs(M, 1), cards); FS = GC.FloatCircuit(PS, GC.source_logs(M, 2), cards); t = FB.logits_from_counts(prop)
    lB, tB = FB.forward(t); lS, tS = FS.forward(t); r['float_seed'] = dict(log2_B=lB / math.log(2), log2_S=lS / math.log(2), prop_log2_B=prop.log2_B(), prop_log2_S=prop.log2_S())
    cB, recB = GC.compact_evaluate(PB, M, prop, B, clk); cS, recS = GC.compact_evaluate(PS, M, prop, B, clk); r['compact_seed'] = dict(log2_B=recB['log2'], log2_S=recS['log2'], live_delta=B.live - live0)
    import math as _m
    if _m.prod(cards) <= 4096: ref = CG.ref_exact_BS(M, prop, cap=1 << 12); r['ref'] = dict(exact=True, log2_B_star=ref['log2_B_star'], log2_S_star=ref['log2_S_star'], B_dominates=(to_fraction(cB) >= ref['B_star']), S_dominates=(to_fraction(cS) >= ref['S_star']))
    else: st_ = CJ.oracle_states(M); lw_ = CJ.oracle_logW0(M, st_); q_ = CG.float_law_quantities(prop, st_, lw_); r['ref'] = dict(exact=False, log2_B_star=q_['log2_B_star'], log2_S_star=q_['log2_S_star'], B_dominates=(recB['log2'] >= q_['log2_B_star'] - 1e-6), S_dominates=(recS['log2'] >= q_['log2_S_star'] - 1e-6))
    certB = CG.certify(PB, M, prop, cB, clk, budget=B); certS = CG.certify(PS, M, prop, cS, clk, budget=B); r['certify'] = dict(B_ok=certB['ok'], S_ok=certS['ok'], whyB=certB.get('why'), whyS=certS.get('why'), live_delta=B.live - live0)
    p2, idx = CG.mutate_omit(PB, 'reciprocal', prop.order[0]); r['certify_omitted'] = CG.certify(p2, M, prop, cB, clk, budget=B).get('why')
    # gradient check (smoothed p=16 objective)
    log_eta = math.log(0.005) + (lS - lB) / 2; o = GC.objective(FB, FS, t, log_eta, 16.0); g = o['g']; rng = np.random.default_rng(0); errs = []
    for _ in range(6):
        d = rng.standard_normal(t.size); d /= np.linalg.norm(d); h = 1e-5; fp = GC.objective(FB, FS, t + h * d, log_eta, 16.0)['f']; fm = GC.objective(FB, FS, t - h * d, log_eta, 16.0)['f']; errs.append(abs((fp - fm) / (2 * h) - float(g @ d)) / max(1e-12, abs(float(g @ d))))
    rowsum = max(abs(g[off:off + R * k].reshape(R, k).sum(axis=1)).max() for v, (off, R, k) in FB.row_slices.items()); r['gradient'] = dict(max_rel_fd_error=max(errs), max_row_sum=float(rowsum), n_params=t.size)
    # optimizer
    opt = GO.BoundedLBFGS(FB, FS, log_eta, 'joint', time.monotonic() + 20); endpoint, phases = opt.run(t); r['optimizer'] = dict(evals=opt.evals, cache_hits=opt.cache_hits, phases=phases, f0=o['f'], f_end=(endpoint['f'] if endpoint else None))
    if endpoint is not None:
        seg, best, (rs, ro) = GO.segment_scores(FB, FS, t, endpoint['t'], log_eta, 0.0, 'joint', time.monotonic() + 20); r['segment'] = dict(best=best, n=len(seg), logJ0=seg[0].get('logJ'), logJ1=seg[-1].get('logJ'))
        conds = GO.quantize_segment(FB, rs, ro, best['lam'], cards, prop.order, parents0, budget=B); newp = JP.Proposal(cards, conds, prop.order, prop.B, prop.S, {}); cB2, _ = GC.compact_evaluate(PB, M, newp, B, clk); cS2, _ = GC.compact_evaluate(PS, M, newp, B, clk)
        if _m.prod(cards) <= 4096: ref2 = CG.ref_exact_BS(M, newp, cap=1 << 12); r['candidate'] = dict(log2_B=log2_up(cB2), log2_S=log2_up(cS2), ref_log2_B=ref2['log2_B_star'], ref_log2_S=ref2['log2_S_star'], dominates=(to_fraction(cB2) >= ref2['B_star'] and to_fraction(cS2) >= ref2['S_star']))
        else: q2 = CG.float_law_quantities(newp, st_, lw_); r['candidate'] = dict(log2_B=log2_up(cB2), log2_S=log2_up(cS2), ref_log2_B=q2['log2_B_star'], ref_log2_S=q2['log2_S_star'], dominates=(log2_up(cB2) >= q2['log2_B_star'] - 1e-6 and log2_up(cS2) >= q2['log2_S_star'] - 1e-6))
        r['candidate'].update(certB=CG.certify(PB, M, newp, cB2, clk)['ok'], certS=CG.certify(PS, M, newp, cS2, clk)['ok'], seed_log2_B=prop.log2_B(), seed_log2_S=prop.log2_S(), lam=best['lam'])
    # G1
    pairs, chg = JO.interaction_scores(M, B, clk); parents1, g1rec = GO.select_g1(prop, pairs, cards); r['g1'] = g1rec
    if not g1rec['alias_G0']:
        p1 = GO.replicate_graph(prop, parents1, cards, budget=B); PB1, PS1 = GC.build_plans(M, prop.order, parents1, order); FB1 = GC.FloatCircuit(PB1, GC.source_logs(M, 1), cards); FS1 = GC.FloatCircuit(PS1, GC.source_logs(M, 2), cards); t1 = FB1.logits_from_counts(p1)
        lB1, _ = FB1.forward(t1); lS1, _ = FS1.forward(t1); r['g1_float'] = dict(log2_B=lB1 / math.log(2), log2_S=lS1 / math.log(2), planB=PB1.record()['work_cells'], same_law_q=all(p1.q_exact(x) == prop.q_exact(x) for x in [tuple(random.Random(1).randrange(k) for k in cards) for _ in range(20)]))
    r['seconds'] = time.monotonic() - t0; out[name] = r; print(name, json.dumps({k: r[k] for k in ('float_seed', 'compact_seed', 'ref', 'certify', 'certify_omitted', 'gradient')}, default=str)[:900]); print('  opt', json.dumps(r['optimizer'], default=str)[:600]); print('  seg', json.dumps(r.get('segment'), default=str)[:300]); print('  cand', json.dumps(r.get('candidate'), default=str)[:300]); print('  g1', json.dumps(r.get('g1_float'), default=str)[:300], r['g1']['n_extended'], round(r['seconds'], 2))
run('four_cycle', C._four_cycle())
run('n8_clique', C.load('dg_n8_c4_clique_two')[0])
rng = random.Random(5); run('bin_n10', dict(cards=[2] * 10, factors=[dict(scope=(i, j), values=[F(rng.randint(1, 9), rng.randint(1, 5)) for _ in range(4)]) for i in range(10) for j in range(i + 1, 10) if rng.random() < 0.5] + [dict(scope=(v,), values=[F(rng.randint(1, 7)) for _ in range(2)]) for v in range(10)], evidence={}))
json.dump(out, open(sys.argv[1], 'w'), indent=1, default=str)
