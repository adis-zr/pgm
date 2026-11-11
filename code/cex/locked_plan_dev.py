"""LOCKED-PLAN comparison (prompt section 8 step 3): the UNCHANGED baseline planner (cex/baseline core._discover_component, charged) produces the component
plan; BOTH executors then run from the SAME validated semantic plan (same component model, same order): baseline = support.solve (exact Fraction);
new = cex_executor.execute (compiled, certified binary64 + labels). Records the semantic plan hash (identical by construction), per-executor delivered
status / wall / peak RSS / counters, and containment of the new arm's enclosures of the exact reference points. Output: a JSON per case in argv[2].
    python cex/locked_plan.py <case> <outdir> <budget_s> [cap_bytes]"""
import sys, os, json, time, resource, hashlib
sys.set_int_max_str_digits(0); HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, os.path.join(HERE, 'baseline'))
from fractions import Fraction as F
import core, reduction, support, planning, geometry
case, outdir, budget = sys.argv[1], sys.argv[2], float(sys.argv[3]); cap = int(sys.argv[4]) if len(sys.argv) > 4 else 3 * 1024 ** 3
P = '/Users/adis/Workspace/pgm/docs/handoff-received-2026-11-11-certified-executor/packet/inputs'; os.makedirs(outdir, exist_ok=True)
def rss(): r = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss; return r if sys.platform == 'darwin' else r * 1024
out = {'case': case, 'budget_s': budget, 'cap_bytes': cap}
t0 = time.monotonic(); m, binding = core.read_uai(os.path.join(P, case + '.uai')); out['binding'] = binding; out['parse_s'] = time.monotonic() - t0
# ---- the unchanged baseline planner path up to the component plan (reduction -> components -> discover), charged as plan construction
t = time.monotonic(); red = reduction.reduce(m, deadline=time.monotonic() + budget); rm = red['model']; split = core.components(rm, deadline=time.monotonic() + budget)
plans = []
for old, cm in split:
    p = core._discover_component(cm, time.monotonic() + budget, 'auto'); plans.append((old, cm, p))
out['plan_construction_s'] = time.monotonic() - t; out['components'] = [dict(variables=len(old), route=p['kind'], forecast=p['forecast'], order_len=len(p['order'])) for old, cm, p in plans]
out['reduction'] = {k: red['stats'].get(k) for k in ('aliases', 'states_removed', 'scalar_factors_cancelled')}
support_comps = [(old, cm, p) for old, cm, p in plans if p['kind'] == 'support']
if not support_comps: out['note'] = 'no support-route component: the locked-plan comparison targets the nonnegative contraction executor only'; json.dump(out, open(os.path.join(outdir, case + '.json'), 'w'), indent=1, default=str); print(json.dumps(out, default=str)[:400]); sys.exit(0)
sys.path.insert(0, os.path.join(HERE, "newarm_dev")); import cex_executor as X
res = {}
for arm in sys.argv[5].split(',') if len(sys.argv) > 5 else ('new', 'baseline'):
    rows = []; t_arm = time.monotonic(); rss0 = rss(); status = 'COMPLETED'; stop = None
    for ci, (old, cm, p) in enumerate(support_comps):
        tc = time.monotonic(); dl = t_arm + budget
        try:
            if arm == 'baseline': r = support.solve(cm, deadline=dl, order=p['order']); st = r['stats']; rows.append(dict(component=ci, variables=len(old), status=r['status'], wall_s=time.monotonic() - tc, forward_s=st.get('forward_s'), reverse_s=st.get('reverse_s'), forward_rows=st.get('forward_support_rows'), messages_entries=st.get('messages_entries'), max_numerator_bits=st.get('max_numerator_bits'), mults=st.get('multiplications'), adds=st.get('additions'), divisions=st.get('divisions'), points=r.get('points')))
            else:
                r = X.execute(cm, p['order'], deadline=dl, cap_bytes=cap); st = r['stats']; rows.append(dict(component=ci, variables=len(old), status=r['status'], wall_s=time.monotonic() - tc, build_s=st.get('build_s'), lowering_s=st.get('lowering_s'), kernel_s=st.get('kernel_s'), enclosure_s=st.get('enclosure_s'), counters=st.get('counters'), max_label_K=st.get('max_label_K'), max_width=st.get('max_width_float'), semantic_plan_sha256=r['certificate']['semantic_plan_sha256'], physical_schedule_sha256=r['certificate']['physical_schedule_sha256'], kernel_cap_bytes=st.get('kernel_cap_bytes'), intervals=r['intervals'], points=r['points']))
        except Exception as e:
            status = 'STOPPED'; stop = dict(type=type(e).__name__, reason=str(e)[:300], stats={k: v for k, v in (getattr(e, 'stats', {}) or {}).items() if k != 'core_trace'}); rows.append(dict(component=ci, variables=len(old), status='STOPPED', wall_s=time.monotonic() - tc)); break
    res[arm] = dict(status=status, wall_s=time.monotonic() - t_arm, peak_rss_bytes_process=rss(), stop=stop, components=rows)
    out['executors_partial'] = {a: {k: v for k, v in r.items() if k != 'components'} | {'components': [{k: v for k, v in c.items() if k not in ('intervals', 'points')} for c in r['components']]} for a, r in res.items()}
    json.dump(out, open(os.path.join(outdir, case + '.json'), 'w'), indent=1, default=str)      # persist after EVERY arm: a later kill (memory / deadline) keeps the finished arm's record
# ---- cross-check: the new arm's enclosures contain the exact reference points where both completed
if 'new' in res and 'baseline' in res and res['new']['status'] == 'COMPLETED' and res['baseline']['status'] == 'COMPLETED':
    allc = True; coords = 0
    for rn, rb in zip(res['new']['components'], res['baseline']['components']):
        for row, ps in zip(rn['intervals'], rb['points']):
            for (lo, hi), p in zip(row, ps): coords += 1; allc = allc and lo <= p <= hi
    out['new_encloses_exact_reference'] = allc; out['coordinates_compared'] = coords
for arm in res:
    for rw in res[arm]['components']: rw.pop('intervals', None); rw.pop('points', None)
out['executors'] = res; out['semantic_plan_identical_across_arms'] = 'by construction: both executors receive the same component model object and order; the new arm records the semantic hash'
json.dump(out, open(os.path.join(outdir, case + '.json'), 'w'), indent=1, default=str); print(json.dumps({k: out[k] for k in ('case', 'plan_construction_s', 'components', 'new_encloses_exact_reference', 'coordinates_compared') if k in out}, default=str)); print(json.dumps({a: {k: v for k, v in r.items() if k != 'components'} | {'comp0': {k: v for k, v in (r['components'][0] if r['components'] else {}).items() if k not in ('counters',)}} for a, r in res.items()}, default=str)[:1500])
