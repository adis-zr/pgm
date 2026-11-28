"""Job-level controller -- candidate v2 (repair of review F01 / F04 / F05 / F09 of 13 Nov 2026).

Shared deterministic discovery (review F01 "share the complete deterministic discovery interface"): the hybrid uses the SAME root-level candidate set as the frozen
baseline entry point (cex/newarm core._solve): (1) the complete forest route on the original model; (2) the identity source-DAG plan on the original model (retained
because a sound reduction can hide structure); (3) reduction + exact component split + per-component discovery (support / dag / stream candidates) with the identity
plan inherited when the reduction changed nothing; the representation (identity DAG vs reduced components) is selected by the same scalar-forecast comparison.
Controller (budgeted, lazy): components are executed in order; the deterministic-versus-PAC decision of a component is made immediately BEFORE its execution against
the ACTUAL remaining time (repricing), never all up front. A deterministic route that refuses with a compatible typed stop (MEMORY / REPRESENTATION / a numerical
stop that the executor could not resolve) while time remains CONTINUES into the PAC engine for that component (exact-to-PAC continuation); DEADLINE is final.
Delta ledger (review F04): the decision whether a component samples is NOT needed before allocation any more -- K_total conservatively counts EVERY coordinate of the
reduced job (sum of cardinalities over all components), so every coordinate that can ever receive a statistical bound is in the union bound; deterministic components
simply leave their allowance unspent. The executed design record of every stream (canonical cutset / order AFTER forcing, mode, exact U_root, K, alphas, seeds) and the
sufficient statistics are returned in the certificate for independent replay (gate.py, engine.hulls_from_record).
Arms: P1_PAC_CONDITIONAL (forced PAC per component, conditional mode, resolved region ON), H1_HYBRID (the controller above), A0_POINT / A1_CONDITIONAL (matched ablation:
same deterministic cutset / order / tree seed, resolution OFF in both so the residual region is held fixed; point vs integrated).
Every terminal return -- including ZERO_EVIDENCE -- is deadline-checked (review F09)."""
import sys, os, time, math, json, hashlib, random
from fractions import Fraction as F
HERE = os.path.dirname(os.path.abspath(__file__)); NEWARM = os.path.join(os.path.dirname(HERE), 'newarm')
for p in (NEWARM, HERE):
    if p not in sys.path: sys.path.insert(0, p)
import core, reduction, engine, contrib, support
POLICY = engine.POLICY
SOLVER_VERSION = 'pac-solve-v4.1 (2026-11-14 repair 4)'
CONTINUABLE_STOPS = ('MEMORY', 'REPRESENTATION', 'SUPPORT_ROWS_CAP', 'RANGE', 'WIDTH', 'FPENV', 'NUMERICAL_RANGE_OR_PRECISION')   # exact-route refusals after which the PAC engine may continue while time remains (every backend's refusal family is normalized to these in core._execute_component)


class ZeroEvidence(Exception):
    """deterministic zero-evidence proof (the worker publishes PROVED_ZERO_EVIDENCE only after the terminal deadline check). `proof` is a STRUCTURED, independently
    re-derivable record: kind in {forest, reduction, component_restriction, exact_component, pac_root_bound, pac_exact_cover} with the component partition / cutset
    needed by the checker to re-derive the zero (gate.verify_zero_proof)."""
    def __init__(self, proof, trace):
        super().__init__('ZERO_EVIDENCE'); self.proof = proof if isinstance(proof, dict) else dict(kind='legacy_text', text=str(proof)); self.trace = trace


def _stop(kind, trace, **kw):
    return support.ResourceStop(kind, dict(core_trace=trace, **kw))


def solve(model, deadline, arm, seed, delta=F(1, 10 ** 6), cap_bytes=3 * 1024 ** 3, ablation_shared=None):
    """returns dict(intervals, points, guarantee_type, outcome, stats, decoder, certificate); raises support.ResourceStop (typed) or ZeroEvidence"""
    import resource
    t0 = time.monotonic(); trace = dict(arm=arm, seed=str(seed), delta=str(delta), phase='entry', solver_version=SOLVER_VERSION, policy=engine.POLICY, root_discovery=[], components=[], continuations=[])
    def check(where):
        if deadline is not None and time.monotonic() >= deadline: raise _stop('DEADLINE', trace, where=where)
    def remaining(): return (deadline - time.monotonic()) if deadline is not None else float('inf')
    rss = lambda: core.rss_bytes()                                             # bytes on every platform (review R11)
    original_cards = list(model['cards']); n0 = len(original_cards)
    check('entry')
    # ---------------- root-level deterministic routes (shared with the baseline entry point): H1 only
    if arm == 'H1_HYBRID':
        import forest, dag
        ft = time.monotonic(); trace['phase'] = 'forest discovery'
        try:
            result = forest.solve(model, deadline=deadline, independent_replay=True)
            core.verify_output(result['intervals'], result['points'], POLICY['epsilon']); check('forest publication')
            trace['root_discovery'].append(dict(kind='forest', wall_s=time.monotonic() - ft, chosen=True))
            return _finish(result['intervals'], result['points'], [dict(component=0, variables=list(range(n0)), route='forest', guarantee='DETERMINISTIC', stats=result['stats'], certificate=result['certificate'], intervals_exact=[[(str(lo), str(hi)) for lo, hi in row] for row in result['intervals']], points_exact=[[str(x) for x in row] for row in result['points']])], dict(reduction={'not_attempted': 'complete forest computation'}), [dict(kind='identity', variable=v) for v in range(n0)], trace, t0, delta, K_total=0, check=check)
        except forest.UnsupportedError as e: trace['root_discovery'].append(dict(kind='forest', declined=str(e)[:200], wall_s=time.monotonic() - ft))
        except forest.ZeroEvidence: raise ZeroEvidence(dict(kind='forest', text='complete forest computation: zero evidence'), trace)
        except forest.DeadlineExceeded: raise _stop('DEADLINE', trace, where='forest')
        check('after forest discovery'); trace['phase'] = 'identity planning'; rt = time.monotonic(); raw_plan = None; raw_cost = None
        try:
            raw_plan = dag.plan(model, deadline=min(deadline if deadline is not None else float('inf'), time.monotonic() + 2)); raw_cost = core._dag_forecast(raw_plan['stats'])
            trace['root_discovery'].append(dict(kind='identity_source_dag', scalar_forecast=raw_cost, wall_s=time.monotonic() - rt))
        except (ValueError, TimeoutError) as e: trace['root_discovery'].append(dict(kind='identity_source_dag', declined=str(e)[:200], wall_s=time.monotonic() - rt))
        check('after identity planning')
    else: raw_plan = None; raw_cost = None
    # ---------------- reduction + components (all arms)
    trace['phase'] = 'reduction'
    try: reduced = reduction.reduce(model, deadline=deadline)
    except reduction.Deadline as ex: raise _stop('DEADLINE', trace, where='reduction', stats=ex.stats)
    trace['reduction'] = reduced['stats']
    if reduced.get('status') == 'ZERO_EVIDENCE': raise ZeroEvidence(dict(kind='reduction', reason=str(reduced.get('reason', ''))[:200]), trace)
    rm = reduced['model']; check('after reduction'); trace['phase'] = 'components'
    try: split = core.components(rm, deadline=deadline)
    except TimeoutError: raise _stop('DEADLINE', trace, where='components')
    except ValueError as e:
        if str(e) == 'ZERO_EVIDENCE': raise ZeroEvidence(dict(kind='component_restriction', text='a fully observed factor is zero after reduction'), trace)
        raise
    unchanged = (len(rm['cards']) == n0 and not model.get('evidence') and not any(reduced['stats'].get(k, 0) for k in ('aliases', 'states_removed', 'scalar_factors_cancelled')))
    # K_total: EVERY coordinate of the reduced job (conservative union bound; deterministic components leave their allowance unspent)
    K_total = sum(sum(cm['cards']) for _, cm in split); trace['K_total'] = K_total
    trace['delta_ledger'] = dict(delta=str(delta), range_family=str(delta / 2), variance_family=str(delta / 2), per_coordinate_alpha_each_family=str(delta / (2 * K_total)) if K_total else None, coordinates=K_total, rule='K_total = sum of cardinalities over ALL components of the reduced job (every coordinate that may ever receive a statistical bound); deterministic components spend none of their allowance')
    # ---------------- H1: per-component discovery and representation selection (as the baseline entry point)
    plans = []
    if arm == 'H1_HYBRID':
        trace['phase'] = 'planning'
        for old, cm in split:
            check('component planning')
            inherited = raw_plan if (unchanged and len(split) == 1 and old == list(range(n0))) else None
            plans.append(core._discover_component(cm, deadline, 'auto', inherited))
        reduced_cost = sum(p['forecast'] for p in plans)
        use_raw = raw_plan is not None and raw_cost <= reduced_cost
        trace['root_discovery'].append(dict(kind='representation_selection', chosen='identity_source_dag' if use_raw else 'reduced_components', identity_forecast=raw_cost, reduced_forecast=reduced_cost))
        if use_raw:
            rate = POLICY['gate_units_per_second']['dag']; est = raw_cost / rate; rem = remaining(); det = est <= POLICY['gate_fraction'] * rem
            trace['root_discovery'].append(dict(kind='identity_dag_gate', estimate_s=est, remaining_s=rem, admitted=det))
            if det:
                ct = time.monotonic()
                try:
                    result = dag.execute_plan(raw_plan, deadline=deadline); check('identity DAG publication')
                    return _finish(result['intervals'], result['points'], [dict(component=0, variables=list(range(n0)), route='dag', guarantee='DETERMINISTIC', discovery=trace['root_discovery'], execution_wall_s=time.monotonic() - ct, stats=result['stats'], certificate=result['certificate'], intervals_exact=[[(str(lo), str(hi)) for lo, hi in row] for row in result['intervals']], points_exact=[[str(x) for x in row] for row in result['points']])], dict(reduction={'not_attempted': 'identity source DAG selected'}), [dict(kind='identity', variable=v) for v in range(n0)], trace, t0, delta, K_total=0, check=check)
                except (dag.Deadline, TimeoutError): raise _stop('DEADLINE', trace, where='identity DAG execution')
                except (dag.Unsupported, ValueError, support.ResourceStop) as e:
                    kind = getattr(e, 'reason', None) if isinstance(e, support.ResourceStop) else 'INVALID_PLAN'
                    trace['continuations'].append(dict(from_route='identity_source_dag', stop=str(kind), reason=str(e)[:200], remaining_s=remaining(), to='reduced components (deterministic or PAC per component)'))
                    check('after identity DAG refusal')
    else:
        plans = [None] * len(split)
    # ---------------- component execution with LAZY decisions and exact-to-PAC continuation
    trace['phase'] = 'execution'; intervals = [None] * len(rm['cards']); points = [None] * len(intervals); records = []; guarantees = set(); decisions = []
    for i, ((old, cm), p) in enumerate(zip(split, plans)):
        check('component execution'); ct = time.monotonic(); n = len(cm['cards']); rows = ps = None; route_used = None; guarantee = None; rec_extra = {}
        if arm == 'H1_HYBRID':
            rate = POLICY['gate_units_per_second'].get(p['kind'], 1e8); rem = remaining(); est = (p['forecast'] or 0) / rate; det = est <= POLICY['gate_fraction'] * rem
            decisions.append(dict(component=i, variables=n, route=p['kind'] if det else 'pac_conditional', forecast=p['forecast'], estimate_s=est, remaining_s_at_decision=rem, deterministic=det))
            if det:
                try:
                    result = core._execute_component(p, deadline)
                    if result.get('status') == 'ZERO_EVIDENCE': raise ZeroEvidence(dict(kind='exact_component', component=i, variables=list(old), route=p['kind']), trace)
                    rows = result['intervals']; ps = result.get('points') or [[(lo + hi) / 2 for lo, hi in row] for row in rows]; route_used = p['kind']; guarantee = 'DETERMINISTIC'
                    rec_extra = dict(discovery=p['discovery'], stats=result.get('stats'), certificate=result.get('certificate'), intervals_exact=[[(str(lo), str(hi)) for lo, hi in row] for row in rows], points_exact=[[str(x) for x in row] for row in ps])
                except support.ResourceStop as e:
                    if e.reason == 'DEADLINE' or remaining() <= 0: raise _stop('DEADLINE', trace, component=i, stats=e.stats, reason='exact route refused at the deadline')
                    if e.reason not in CONTINUABLE_STOPS: raise _stop(e.reason, trace, component=i, stats=e.stats)
                    trace['continuations'].append(dict(component=i, from_route=p['kind'], stop=e.reason, remaining_s=remaining(), to='pac_conditional'))
                    decisions[-1].update(route='pac_conditional_after_%s' % e.reason, deterministic=False, exact_attempt_wall_s=time.monotonic() - ct)
                except (TimeoutError,) as e: raise _stop('DEADLINE', trace, component=i, reason=str(e)[:100])
        else:
            decisions.append(dict(component=i, variables=n, route='pac_point' if arm == 'A0_POINT' else 'pac_conditional', deterministic=False))
        if rows is None:
            # ---- PAC engine for this component (forced arm, ablation arm, hybrid fallback or hybrid decision)
            check('before PAC component'); mode = 'point' if arm == 'A0_POINT' else 'conditional'; seed_tree = engine.seed_int(seed, 'tree', i); seed_point = engine.seed_int(seed, 'point', i)
            fixed_cut = fixed_order = None; resolve = None
            if arm in ('A0_POINT', 'A1_CONDITIONAL'):
                resolve = False
                if ablation_shared is not None and str(i) in ablation_shared: fixed_cut = ablation_shared[str(i)]['cutset']; fixed_order = ablation_shared[str(i)]['order']
                else:
                    cs = engine.choose_cutset(cm, deadline, POLICY, budget_fraction=None); fixed_cut = cs['cutset']; fixed_order = cs['order']; check('after deterministic ablation cutset selection')
                    if ablation_shared is not None: ablation_shared[str(i)] = dict(cutset=fixed_cut, order=fixed_order)
            try:
                r = engine.run_component(cm, deadline, seed_tree, seed_point, mode, delta / 2, delta / 2, max(1, K_total), cap_bytes, rss(), POLICY, fixed_cutset=fixed_cut, fixed_order=fixed_order, forced=(arm == 'P1_PAC_CONDITIONAL'), resolve=resolve)
            except engine.EngineStop as e: raise _stop(e.outcome, trace, component=i, stats=e.stats, reason=e.reason)
            if r['status'] == 'PROVED_ZERO_EVIDENCE': raise ZeroEvidence(dict(kind='pac_root_bound' if r['stats'].get('resolved_cells', 0) == 0 and 'root' in str(r['stats'].get('proof', '')) else 'pac_exact_cover', component=i, variables=list(old), cutset=(r['stats'].get('design') or {}).get('cutset'), frontier=r['stats'].get('frontier'), resolved_totals=r['stats'].get('resolved_totals'), text=str(r['stats'].get('proof', ''))[:200]), trace)
            if r['status'] != 'PUBLISHED': raise _stop(r['status'], trace, component=i, stats=r['stats'])        # incl. the typed INTERSECTION_EMPTY diagnostic (never a publication)
            rows = r['intervals']; ps = r['points']; guarantee = r['guarantee']; route_used = 'pac_' + mode + ('' if guarantee == 'PAC' else '_' + str(r['stats'].get('route')))
            rec_extra = dict(stats=r['stats'], certifier_per_row=r['certifier_per_row'], widths=r.get('widths'), variance_sets_nonconvex=r.get('variance_sets_nonconvex'), design=r['stats'].get('design'), sufficient_statistics=r['stats'].get('sufficient_statistics'), frontier=r['stats'].get('frontier'), resolved_totals=r['stats'].get('resolved_totals'), intervals_exact=[[(str(lo), str(hi)) for lo, hi in row] for row in rows], points_exact=[[str(x) for x in row] for row in ps], cutset_mode_cards=dict(cutset=(r['stats'].get('design') or {}).get('cutset'), order_free=(r['stats'].get('design') or {}).get('order_free'), cards=list(cm['cards'])))
        guarantees.add(guarantee)
        records.append(dict(component=i, variables=old, route=route_used, guarantee=guarantee, execution_wall_s=time.monotonic() - ct, **rec_extra))
        assert len(rows) == len(old) and len(ps) == len(old)
        for v, row, q in zip(old, rows, ps): intervals[v] = row; points[v] = q
    trace['decisions'] = decisions
    assert all(x is not None for x in intervals)
    core.verify_output(intervals, points, POLICY['epsilon']); check('before lift')
    lifted_i, lifted_p = reduction.lift(reduced, intervals, points)
    return _finish(lifted_i, lifted_p, records, dict(reduction=reduced['stats'], decisions=decisions, continuations=trace['continuations']), reduced['decoder'], trace, t0, delta, K_total=K_total, check=check, reduction_certificate=reduced.get('certificate'), original_cards=original_cards, reduced_model=rm, partition=[old for old, _ in split])


def _finish(intervals, points, records, stats_extra, decoder, trace, t0, delta, K_total, check, reduction_certificate=None, original_cards=None, reduced_model=None, partition=None):
    if original_cards is not None: assert len(intervals) == len(original_cards) and all(len(row) == d_ for row, d_ in zip(intervals, original_cards))
    core.verify_output(intervals, points, POLICY['epsilon']); check('publication')
    guarantees = {r['guarantee'] for r in records}; gt = 'PAC' if 'PAC' in guarantees else 'DETERMINISTIC'
    # the risk ledger is DERIVED from the EXECUTED result (review 4 F01): a whole-model deterministic root route (reduced_model None) has K_total = 0 and no stochastic
    # coordinate -- the reduced-planning ledger kept in the trace describes a job that was NOT executed and is never reused here
    if reduced_model is None:
        assert K_total == 0 and all(r['guarantee'] == 'DETERMINISTIC' for r in records), 'whole-model root route must carry K_total = 0 and only deterministic components'
        ledger = dict(delta=str(delta), range_family=str(delta / 2), variance_family=str(delta / 2), per_coordinate_alpha_each_family=None, coordinates=0, components_pac=0, rule='whole-model deterministic root route: no stochastic coordinate (K_total = 0)')
    else:
        ledger = dict(delta=str(delta), range_family=str(delta / 2), variance_family=str(delta / 2), per_coordinate_alpha_each_family=str(delta / (2 * K_total)) if K_total else None, coordinates=K_total, components_pac=sum(1 for r in records if r['guarantee'] == 'PAC'), rule='K_total = sum of cardinalities over ALL components of the reduced job (every coordinate that may ever receive a statistical interval); deterministic components leave their allowance unspent')
    trace['delta_ledger'] = ledger
    cert = dict(certificate_version='pac-certificate-v4', arm=trace.get('arm'), guarantee_type=gt, delta=str(delta) if gt == 'PAC' else '0', epsilon='%d/%d' % (POLICY['epsilon'].numerator, POLICY['epsilon'].denominator), delta_ledger=ledger, K_total=K_total,
                components=[dict(component=r['component'], variables=r['variables'], route=r['route'], guarantee=r['guarantee'], certifier_per_row=r.get('certifier_per_row'), design=r.get('design'), sufficient_statistics=r.get('sufficient_statistics'), frontier=r.get('frontier'), resolved_totals=r.get('resolved_totals'), intervals_exact=r.get('intervals_exact'), points_exact=r.get('points_exact'), trials=(r.get('stats') or {}).get('trials_completed'), resolved_cells=(r.get('stats') or {}).get('resolved_cells')) for r in records],
                lifted_intervals_exact=[[(str(lo), str(hi)) for lo, hi in row] for row in intervals], lifted_points_exact=[[str(x) for x in row] for row in points], decoder=decoder, reduction_certificate=reduction_certificate,
                reduced_model=(dict(cards=list(reduced_model['cards']), factors=[dict(scope=list(f['scope']), values=[str(x) for x in f['values']]) for f in reduced_model['factors']]) if reduced_model is not None else None), partition=partition,
                chain='original model (binding) -> reduction.reduce (decoder; re-derivable) -> core.components (partition) -> per-component exact rows (deterministic route certificate or PAC design + statistics + frontier + resolved totals) -> reduction.lift (decoder) -> original rows -> core.publish decimals',
                trust_boundary='checker (gate v4): task binding; reduction / partition re-derived; for every PAC component a DETERMINISTIC REPLAY of the recorded design (frozen policy, derived seeds, cutset, order, mode, resolution) on the bound component model must reproduce the sufficient statistics, frontier and resolved totals exactly (statistics impossible under the law cannot be reproduced); for deterministic covers every resolved cell is re-evaluated (exact enumeration when <= exact_leaf_max_completions, else the compiled kernel re-executed on the bound cell / template: the kernel enclosure is TRUSTED at that boundary) and the accumulators are re-accumulated; the hulls, the deterministic-statistical intersection, the lift and the decimals are re-derived. NOT verified: that a particular lawful random realization contains the truth (the PAC event), and the PRNG ideal-independent-bits assumption.')
    return dict(intervals=intervals, points=points, guarantee_type=gt, outcome='PUBLISHED', stats=dict(stats_extra, total_s=time.monotonic() - t0, components=[{k: v for k, v in r.items() if k not in ('sufficient_statistics', 'intervals_exact', 'points_exact')} for r in records], root_discovery=trace.get('root_discovery'), delta_ledger=trace.get('delta_ledger'), solver_version=SOLVER_VERSION), decoder=decoder, certificate=cert)
