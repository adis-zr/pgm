"""DGP6 development-panel calibration of the FROZEN compact-circuit / quantization rates used by GlobalStream's pre-forecast (brief section 4: 'fit them once on a frozen development panel spanning cardinalities 2-32, distinguish
fixed overhead from physical work, and freeze before evaluation'). Panel: random pairwise models with cardinalities 2, 4, 8, 16, 32 (n = 6..12) + the dev inputs dg_n8_c4_clique_two / dg_n8_c4_er50_two. Per model: producer compact
evaluation + independent certification of BOTH circuits on the G1 graph at the seed counts (cells, seconds), quantization of every G1 row (entries, seconds). Fit seconds = overhead + cells / rate by least squares; the frozen rate is
the 25th percentile of the per-model marginal rates (conservative). usage: dgp6_rates.py OUT.json"""
import sys, os, json, time, math, random
sys.path[:0] = [os.path.dirname(os.path.abspath(__file__)), os.path.join(os.path.dirname(os.path.abspath(__file__)), '../blockres'), os.path.join(os.path.dirname(os.path.abspath(__file__)), '../newarm')]
from fractions import Fraction as F
import numpy as np
import coarse_envelope as CE, check_dgp as C, joint_proposal as JP, joint_optimize as JO, global_circuit as GC, global_optimize as GO, check_global as CG
def stage(model, budget_s=120):
    clk = CE.Clock(time.monotonic() + budget_s, {}); B = CE.Budget(CE.CONSTRUCTOR_BYTES); M = CE.canonicalize(model, clk, B); order, _ = CE.elimination_order(list(M.cards), [tuple(sc) for sc, _ in M.factors], clk, B); return M, order, clk, B
def rand_model(rng, cards, p_edge):
    n = len(cards); edges = [(i, j) for i in range(n) for j in range(i + 1, n) if rng.random() < p_edge]
    return dict(cards=list(cards), factors=[dict(scope=(u, v), values=[F(rng.randint(1, 99), rng.randint(1, 9)) for _ in range(cards[u] * cards[v])]) for (u, v) in edges] + [dict(scope=(v,), values=[F(rng.randint(1, 7)) for _ in range(cards[v])]) for v in range(n)], evidence={})
rows = []; rng = random.Random(6)
panel = [('dev_n8_clique', C.load('dg_n8_c4_clique_two')[0]), ('dev_n8_er50', C.load('dg_n8_c4_er50_two')[0])]
for card, n, pe in ((2, 12, 0.5), (2, 10, 1.0), (4, 8, 0.6), (4, 6, 1.0), (8, 8, 0.5), (8, 6, 1.0), (16, 8, 0.4), (16, 6, 1.0), (32, 6, 0.6), (32, 5, 1.0)): panel.append(('rand_c%d_n%d_p%.1f' % (card, n, pe), rand_model(rng, [card] * n, pe)))
for name, model in panel:
    try:
        M, order, clk, B = stage(model); cards = list(M.cards); prop, rec, owned = JP.compile_seed(M, order, JP.PROFILE_PRODUCTION, B, clk); pairs, chg = JO.interaction_scores(M, B, clk); parents, grec = GO.select_g1(prop, pairs, cards); p1 = GO.replicate_graph(prop, parents, cards, budget=B) if not grec['alias_G0'] else prop
        PB, PS = GC.build_plans(M, prop.order, parents, order); r = dict(name=name, n=len(cards), card=max(cards), g1_entries=grec['total_entries'], extended=grec['n_extended'])
        t0 = time.monotonic(); cB, rB = GC.compact_evaluate(PB, M, p1, B, clk); cS, rS = GC.compact_evaluate(PS, M, p1, B, clk); r['producer'] = dict(seconds=time.monotonic() - t0, cells=rB['cells'] + rS['cells'])
        t0 = time.monotonic(); kB = CG.certify(PB, M, p1, cB, clk, budget=B); kS = CG.certify(PS, M, p1, cS, clk, budget=B); r['certifier'] = dict(seconds=time.monotonic() - t0, cells=kB['cells'] + kS['cells'], ok=kB['ok'] and kS['ok'])
        r['plan_cells'] = 2 * (PB.work_cells + PB.n_source_cells(cards) + PS.work_cells + PS.n_source_cells(cards)); r['checked_seconds'] = r['producer']['seconds'] + r['certifier']['seconds']
        FB = GC.FloatCircuit(PB, GC.source_logs(M, 1), cards); t = FB.logits_from_counts(p1); rs = {v: GO.logits_to_rows(FB, t, v) for v in prop.order}; t0 = time.monotonic(); conds = GO.quantize_segment(FB, rs, rs, 0.5, cards, prop.order, parents); r['quantize'] = dict(seconds=time.monotonic() - t0, entries=sum(c.counts.size for c in conds.values()))
        t0 = time.monotonic(); FS = GC.FloatCircuit(PS, GC.source_logs(M, 2), cards); o = GC.objective(FB, FS, t, 0.0, 16.0); r['float_eval'] = dict(seconds=time.monotonic() - t0, n_params=t.size, plan_work=PB.work_cells + PS.work_cells)
        r['rates'] = dict(checked_cells_per_s=r['plan_cells'] / r['checked_seconds'], quantize_entries_per_s=r['quantize']['entries'] / max(1e-9, r['quantize']['seconds']), float_cells_per_s=r['float_eval']['plan_work'] / max(1e-9, r['float_eval']['seconds']))
        rows.append(r); print(json.dumps({k: r[k] for k in ('name', 'n', 'card', 'g1_entries', 'plan_cells', 'checked_seconds', 'rates')}, default=str))
    except Exception as e: import traceback; rows.append(dict(name=name, error=repr(e)[:200], tb=traceback.format_exc()[-800:])); print(name, 'ERROR', repr(e)[:200])
ok = [r for r in rows if 'rates' in r]; X = np.array([[1.0, r['plan_cells']] for r in ok]); y = np.array([r['checked_seconds'] for r in ok]); coef = np.linalg.lstsq(X, y, rcond=None)[0]
fit = dict(overhead_s=float(max(0.0, coef[0])), seconds_per_cell=float(coef[1]), rate_cells_per_s_fit=(1.0 / float(coef[1]) if coef[1] > 0 else None))
q = lambda k, p: float(np.percentile([r['rates'][k] for r in ok], p))
frozen = dict(compact_cells_per_s=q('checked_cells_per_s', 25), compact_overhead_s=max(fit['overhead_s'], 0.002), quantize_entries_per_s=q('quantize_entries_per_s', 25), float_cells_per_s=q('float_cells_per_s', 25), rule='25th percentile of the per-model marginal rates (conservative); overhead = the least-squares intercept (>= 2 ms)', panel=len(ok))
json.dump(dict(rows=rows, fit=fit, frozen=frozen, utc=time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())), open(sys.argv[1], 'w'), indent=1, default=str); print('FIT', fit); print('FROZEN', frozen)
