"""Job-level PAC / hybrid solver (handoff 02 "Minimal empirical arms"): the frozen deterministic pipeline's reduction + component split + planner are REUSED unchanged
(cex/newarm core.py, reduction.py, planning.py, geometry.py); per component the arm policy picks the frozen deterministic route or the PAC engine (cex/pac/engine.py).
  P1_PAC_CONDITIONAL : every component with free variables goes through the PAC engine in conditional (integrated) mode (forced minimum cutset of one variable);
                       components small enough for exact enumeration are answered exactly (delta = 0, labelled DETERMINISTIC).
  H1_HYBRID          : the frozen planner's candidate routes are priced; the chosen deterministic route runs when forecast / rate_route <= gate_fraction * remaining
                       budget (rates = the slowest observed in the frozen v1.4 campaigns per route, POLICY['gate_units_per_second']); otherwise the PAC engine
                       (conditional mode) runs for the remaining budget. Zero-evidence in ANY component invalidates the global posterior (ValueError ZERO_EVIDENCE).
  A0_POINT / A1_CONDITIONAL : the matched ablation (same cutset / order / tree seed; point vs integrated); the cutset is chosen ONCE by the frozen policy and passed to both.
One global delta ledger per job: delta_range = delta_var = delta/2; alpha per coordinate = family delta / K_total where K_total = sum of cardinalities over all
coordinates handled by PAC components (deterministic components spend no delta). Every terminal return is deadline-checked; the lift to original coordinates
uses the frozen reduction decoder; publication uses the frozen outward decimal publisher + verify_output."""
import sys, os, time, math, json, hashlib, random
from fractions import Fraction as F
HERE = os.path.dirname(os.path.abspath(__file__)); NEWARM = os.path.join(os.path.dirname(HERE), 'newarm')
for p in (NEWARM, HERE):
    if p not in sys.path: sys.path.insert(0, p)
import core, reduction, engine, contrib
POLICY = engine.POLICY


class Deadline(Exception): pass


def _deadline(deadline, where, stats):
    if deadline is not None and time.monotonic() >= deadline: raise core.support.ResourceStop('DEADLINE', dict(stats, where=where)) if hasattr(core, 'support') else TimeoutError(where)


def solve(model, deadline, arm, seed, delta=F(1, 10 ** 6), cap_bytes=3 * 1024 ** 3, ablation_shared=None):
    """returns dict(intervals, points, guarantee_type, outcome, stats, decoder, certificate_metadata); raises on typed failures (the harness records them)"""
    import resource, support
    t0 = time.monotonic(); trace = dict(arm=arm, seed=str(seed), delta=str(delta), phase='reduction', components=[], policy=POLICY)
    def check(where):
        if deadline is not None and time.monotonic() >= deadline: raise support.ResourceStop('DEADLINE', dict(core_trace=trace, where=where))
    rss = lambda: resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    original_cards = list(model['cards'])
    try: reduced = reduction.reduce(model, deadline=deadline)
    except reduction.Deadline as ex: raise support.ResourceStop('DEADLINE', dict(core_trace=trace, where='reduction', stats=ex.stats))
    trace['reduction'] = reduced['stats']
    if reduced.get('status') == 'ZERO_EVIDENCE': raise ValueError('ZERO_EVIDENCE')
    rm = reduced['model']; check('after reduction'); trace['phase'] = 'components'
    try: split = core.components(rm, deadline=deadline)
    except TimeoutError: raise support.ResourceStop('DEADLINE', dict(core_trace=trace, where='components'))
    trace['phase'] = 'planning'; plans = []
    for old, cm in split:
        check('component planning')
        if arm in ('H1_HYBRID',):
            p = core._discover_component(cm, deadline, 'auto'); plans.append((old, cm, p))
        else:
            plans.append((old, cm, None))
    # ---- arm policy per component
    decisions = []; K_total = 0; pac_comps = []
    for i, (old, cm, p) in enumerate(plans):
        n = len(cm['cards']); vol = math.prod(cm['cards'])
        if arm == 'H1_HYBRID':
            rate = POLICY['gate_units_per_second'].get(p['kind'], 1e8); remaining = (deadline - time.monotonic()) if deadline else float('inf'); est = (p['forecast'] or 0) / rate
            det = est <= POLICY['gate_fraction'] * remaining
            decisions.append(dict(component=i, variables=n, route=p['kind'] if det else 'pac_conditional', forecast=p['forecast'], estimate_s=est, remaining_s=remaining, deterministic=det))
            if not det: pac_comps.append(i); K_total += sum(cm['cards']) if vol > POLICY['exact_leaf_max_completions'] else 0
        elif arm in ('P1_PAC_CONDITIONAL', 'A0_POINT', 'A1_CONDITIONAL'):
            decisions.append(dict(component=i, variables=n, route='pac_point' if arm == 'A0_POINT' else 'pac_conditional', deterministic=False)); pac_comps.append(i)
            if vol > POLICY['exact_leaf_max_completions']: K_total += sum(cm['cards'])
        else: raise ValueError('unknown arm %s' % arm)
    trace['decisions'] = decisions; trace['K_total'] = K_total; trace['delta_ledger'] = dict(delta=str(delta), range_family=str(delta / 2), variance_family=str(delta / 2), per_coordinate_alpha_each_family=str(delta / (2 * K_total)) if K_total else None, coordinates=K_total, components_pac=len(pac_comps))
    trace['phase'] = 'execution'; intervals = [None] * len(rm['cards']); points = [None] * len(intervals); records = []; guarantees = set()
    for i, (old, cm, p) in enumerate(plans):
        check('component execution'); ct = time.monotonic(); d = decisions[i]
        if d['deterministic']:
            result = core._execute_component(p, deadline)
            if result.get('status') == 'ZERO_EVIDENCE': raise ValueError('ZERO_EVIDENCE')
            rows = result['intervals']; ps = result.get('points') or [[(lo + hi) / 2 for lo, hi in row] for row in rows]; guarantees.add('DETERMINISTIC')
            records.append(dict(component=i, variables=old, route=p['kind'], guarantee='DETERMINISTIC', discovery=p['discovery'], execution_wall_s=time.monotonic() - ct, stats=result.get('stats'), certificate=result.get('certificate')))
        else:
            mode = 'point' if arm == 'A0_POINT' else 'conditional'; seed_tree = engine.seed_int(seed, 'tree', i); seed_point = engine.seed_int(seed, 'point', i)
            fixed_cut = fixed_order = None
            if arm in ('A0_POINT', 'A1_CONDITIONAL'):
                cs = engine.choose_cutset(cm, deadline, POLICY, budget_fraction=None); fixed_cut = cs['cutset']; fixed_order = cs['order']; check('after deterministic ablation cutset selection')   # deterministic: both arms of the pair derive the SAME cutset/order from the model alone; each arm charges its own selection
            if ablation_shared is not None:
                key = str(i)
                if key not in ablation_shared: cs = engine.choose_cutset(cm, deadline, POLICY, budget_fraction=None); ablation_shared[key] = dict(cutset=cs['cutset'], order=cs['order'])
                fixed_cut = ablation_shared[key]['cutset']; fixed_order = ablation_shared[key]['order']
            try:
                r = engine.run_component(cm, deadline, seed_tree, seed_point, mode, delta / 2, delta / 2, max(1, K_total), cap_bytes, rss(), POLICY, fixed_cutset=fixed_cut, fixed_order=fixed_order, forced=(arm == 'P1_PAC_CONDITIONAL'))
            except engine.EngineStop as e: raise support.ResourceStop(e.outcome, dict(core_trace=trace, component=i, stats=e.stats, reason=e.reason))
            if r['status'] == 'PROVED_ZERO_EVIDENCE': raise ValueError('ZERO_EVIDENCE')
            if r['status'] != 'PUBLISHED': raise support.ResourceStop(r['status'] if r['status'] != 'TOO_WIDE' else 'TOO_WIDE', dict(core_trace=trace, component=i, stats=r['stats']))
            rows = r['intervals']; ps = r['points']; guarantees.add(r['guarantee'])
            records.append(dict(component=i, variables=old, route='pac_' + mode, guarantee=r['guarantee'], execution_wall_s=time.monotonic() - ct, stats=r['stats'], certifier_per_row=r['certifier_per_row'], widths=r.get('widths'), variance_sets_nonconvex=r.get('variance_sets_nonconvex')))
        assert len(rows) == len(old) and len(ps) == len(old)
        for v, row, q in zip(old, rows, ps): intervals[v] = row; points[v] = q
    assert all(x is not None for x in intervals)
    core.verify_output(intervals, points); intervals, points = reduction.lift(reduced, intervals, points)
    assert len(intervals) == len(original_cards) and all(len(row) == d_ for row, d_ in zip(intervals, original_cards))
    core.verify_output(intervals, points); check('publication')
    gt = 'PAC' if 'PAC' in guarantees else 'DETERMINISTIC'
    return dict(intervals=intervals, points=points, guarantee_type=gt, outcome='PUBLISHED', stats=dict(reduction=reduced['stats'], total_s=time.monotonic() - t0, components=records, decisions=decisions, delta_ledger=trace['delta_ledger']), decoder=reduced['decoder'], certificate=dict(guarantee_type=gt, delta=str(delta) if gt == 'PAC' else '0', epsilon='1/200', components=[dict(component=r['component'], route=r['route'], guarantee=r['guarantee'], certifier_per_row=r.get('certifier_per_row'), U_root=(r.get('stats') or {}).get('U_root'), trials=(r.get('stats') or {}).get('trials_completed'), cutset=((r.get('stats') or {}).get('cutset') or {}).get('cutset')) for r in records]))
