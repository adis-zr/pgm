"""TYPED ADAPTERS over the EXISTING structural executors of the baseline arm (cex/newarm): forest (pairwise scaled-dyadic trees), dag (exact normalized source-DAG contraction),
support (bucket contraction: compiled certified binary64 kernel with the exact Fraction fallback), stream (binary bipartite product trees: native float kernel with the exact integer
fallback). Overseer prompt of 17 Nov 2026, section 4: share the established kernels, do not copy the baseline worker; the frozen comparator (cex/pac/solve.py) is untouched.

What an adapter exposes (CAPABILITIES): the supported task / query / representation domain, discovery + conversion requirements, the cost estimate it can give BEFORE running
(R0's scalar forecasts and rate table, reused verbatim), budget / cancellation behaviour (cooperative Python deadline vs an opaque native call that polls the absolute deadline
itself and cannot be pre-empted from Python), the numerical guarantee (DETERMINISTIC enclosures; NEVER exact rationals -- the kernels' enclosures are TRUSTED at the re-execution
boundary, as in the frozen pac gate), and the evidence the checker needs (bounded re-execution of the same executor on the bound model: the rows must reproduce exactly).

Two representations (enumerated, tested; nothing else is claimed):
  ORIGINAL  the task's own model (original tables, original evidence) when EVERY query is an original singleton (the legacy all-singleton contract and any singleton subset);
            every executor answers per-variable singleton rows; evidence variables get exact indicator rows; factor-free free variables get exact uniform rows.
  COMPILED  a committed CQR model (cards / table views / no evidence) when every compiled query is an expectation whose view has scope size <= 1: the answer of query j is the
            linear combination sum_s f_j(s) p_u(s) of the executed variable's singleton row (coefficients in [0, 1]) and its enclosure is the coefficient-weighted interval sum;
            the compiler's bias ledger widens the ORIGINAL answers exactly as on the frontier routes. Affine views, ratio / conditional queries, multi-variable compiled queries and
            normalizer tasks are INAPPLICABLE (typed): they keep the existing CQR path. A structural ZERO_EVIDENCE is a typed decline, never a publication (zero evidence is proved
            only by the CQR mechanisms). EXACT_RATIONAL mode never uses a structural route (the class is deterministic, not exact).
Accounting: structural executions are charged in THEIR OWN counters (wall, executor stats, native kernel counters) -- never added to the Work ledger; the Work parity guarantee
of the protected reference covers the Work-charged phases; a structural attempt is wall-allocated (controller policy in solve.py) and bracketed by reference parity."""
import os, sys, time, hashlib, math
from fractions import Fraction as F
HERE = os.path.dirname(os.path.abspath(__file__)); NEWARM = os.path.join(os.path.dirname(HERE), 'newarm')
if NEWARM not in sys.path: sys.path.insert(0, NEWARM)
import core as NCORE, forest as NFOREST, dag as NDAG, support as NSUPPORT, stream as NSTREAM, stream_float as NSTREAMF, cex_executor as NCEX

STRUCTURAL_VERSION = 'cqr-structural-v1 (2026-11-17: typed adapters over cex/newarm forest / dag / support / stream; R0 rate table; original + compiled(scope<=1) representations)'
# R0's deterministic gate (cex/pac/engine.py POLICY['gate_units_per_second'] / ['gate_fraction']; medians observed in the frozen v1.4 campaign) -- copied verbatim and
# asserted equal to the pac module's values by the qualification suite (no new thresholds, no case-tuned numbers)
RATES = dict(support=3.1e8, stream=3.6e8, dag=5.5e5, forest=1e7); GATE_FRACTION = 0.85
# the EXPLICIT wall allocation of an admitted execution (new in CQR; R0 runs every executor with the whole remaining deadline): a bounded multiple of the forecast with a floor,
# never more than the gate fraction of the remaining budget; forest (no forecast) gets a fixed fraction. An execution that outlives its allocation is a typed DEADLINE stop of the
# structural attempt only: the CQR path (compile / frontier / streams / protected reference) continues with the rest of the budget.
ALLOC_MULTIPLE = 8; ALLOC_FLOOR_S = 2.0; FOREST_FRACTION = 0.5
ROUTES = ('structural_original', 'structural_compiled')
MIN_REMAINING_S = 0.5           # below this remaining budget no structural attempt starts (discovery alone would consume it)
DISCOVERY_ALLOWANCE_S = 2.0; DISCOVERY_FRACTION = 0.10
KINDS = ('forest', 'dag', 'support', 'stream')
CAPABILITIES = dict(
    forest=dict(executor='cex/newarm/forest.py solve', representation='whole model (original or compiled table model); evidence sliced natively', applicability='evidence-sliced arity <= 2 and acyclic after merging parallel factors; any cardinalities', estimate='none before execution (R0 tries forest first; rate 1e7 units/s applies to the PAC-engine path only)', guarantee='DETERMINISTIC enclosure (dyadic-grid outward rounding, delta_bound = K u)', exact=False, cancellation='cooperative: _tick(deadline) per factor and every 1,024 entries (pure Python)', native=False, checker='bounded re-execution of forest.solve(model, independent_replay=True); rows and points must reproduce exactly'),
    dag=dict(executor='cex/newarm/dag.py plan + execute_plan', representation='whole model or component; NO evidence (dag refuses evidence; the component split restricts evidence first)', applicability='exactly one nonempty factor per variable with a child orientation (source DAG); normalization slack delta <= epsilon/2', estimate='plan() prices the contraction exactly (scalar_forecast = additions + multiplications + normalization + additive recognition); rate 5.5e5 units/s', guarantee='DETERMINISTIC: exact normalized-DAG rationals widened by the normalization slack delta', exact=False, cancellation='cooperative: _check(deadline) per topological node / 128 peels / 1,024 rows (pure Python); planning capped at 2 s inside the discovery allowance', native=False, checker='re-plan + re-execute on the bound model; rows must reproduce exactly'),
    support=dict(executor='cex/newarm/cex_executor.py execute (compiled binary64 kernel) with support.py solve (exact Fraction) after a numerical stop', representation='component model after evidence restriction; an elimination order from planning.order_and_price / geometry.discover', applicability='general bucket contraction; refuses REPRESENTATION (restricted factor volume > 2^62), MEMORY (host budget), RANGE / WIDTH / FPENV (then the exact fallback), SUPPORT_ROWS_CAP (fallback join > 2,000,000 rows)', estimate='planning.price: scalar_forecast = 5 x ops + sum(cards); rate 3.1e8 units/s', guarantee='DETERMINISTIC: binary64 kernel enclosure [p(1-delta), p/(1-delta)] with delta = K u (TRUSTED at the re-execution boundary) or the exact fallback point rows', exact=False, cancellation='lowering polls the deadline every 256 entries; the native call lib.cex_run polls the ABSOLUTE deadline itself and is NOT pre-emptible from Python; memory charged before allocation', native=True, checker='re-discover (same kind) + re-execute incl. the native kernel; rows must reproduce exactly; kernel provenance (binary sha256) bound to the frozen identity'),
    stream=dict(executor='cex/newarm/stream_float.py solve (native float product trees) with stream.py solve (exact integer) after a range refusal', representation='component model: every free variable binary, evidence-restricted arity <= 2, bipartite', applicability='binary bipartite; refuses >= 63 conditioned variables, n > 2^28, event bound >= 2^64, working buffers > 512 MiB (REPRESENTATION)', estimate='2^|smaller side| x (8|V| + 4) + sum of table sizes; rate 3.6e8 units/s', guarantee='DETERMINISTIC: [(1-delta) r, r/(1-delta)] with delta = (E_N + E_Z) u (TRUSTED) or exact integer point rows', exact=False, cancellation='native lib.stream_run polls the absolute deadline itself (NOT pre-emptible from Python); the exact fallback is cooperative', native=True, checker='re-discover + re-execute; rows must reproduce exactly; kernel provenance bound'))
UNSUPPORTED = dict(ratio_or_conditional_queries='the CQR path (frontier / streams / reference) answers them', multi_variable_compiled_queries='compiled query view with scope size >= 2: CQR path', affine_views='compiled affine views are not table factors: CQR path', normalizer_tasks='Z is not a singleton row: CQR path', exact_rational_mode='structural enclosures are deterministic, not exact', zero_evidence='a structural ZERO_EVIDENCE is a typed decline; zero evidence is proved by the CQR mechanisms only')


def _kernel_provenance():
    """the provenance of the kernels this process would load (the pinned build records; NO rebuild is triggered: build() returns the existing record when source / flags / binary match)"""
    out = {}
    try:
        p = NCEX.build(None); lib = NCEX.load(p)          # an already-loaded digest returns the cached handle without re-stamping the path: the hash-addressed cache path is deterministic in the digest
        out['newarm_cex'] = dict(loaded_binary_path=p.get('loaded_binary_path') or str(NCEX.BASE / 'native_cache' / ('cex_%s.dylib' % p['binary_sha256'])), binary_sha256=p.get('binary_sha256'), schedule_id=p.get('schedule_id') or lib.cex_schedule_id().decode())
    except Exception as ex: out['newarm_cex'] = dict(error=str(ex)[:120])
    try:
        q = NSTREAMF.build(None); NSTREAMF._load_verified(q, None); out['newarm_stream'] = dict(loaded_binary_path=q.get('loaded_binary_path'), binary_sha256=q.get('binary_sha256'))
    except Exception as ex: out['newarm_stream'] = dict(error=str(ex)[:120])
    return out


# ---------------------------------------------------------------------------------------------------------------- representations
def model_from_task(task):
    """ORIGINAL representation: every query an original singleton (output kind 'singleton'); normalizer tasks refused"""
    if (task.get('query_spec') or {}).get('normalizer_task'): return None, 'normalizer task'
    if not task['queries']: return None, 'no queries'
    if any(q.kind != 'expectation' or (q.output or {}).get('kind') != 'singleton' for q in task['queries']): return None, 'a query is not an original singleton (ratio / conditional / joint / parity / table queries keep the CQR path)'
    m = task['model']; return dict(cards=list(m['cards']), factors=[dict(scope=tuple(f['scope']), values=list(f['values'])) for f in m['factors']], evidence=dict(m.get('evidence', {}))), None


def model_from_compiled(C):
    """COMPILED representation: table views only, no evidence, every compiled query an expectation with scope size <= 1"""
    if C.normalizer_task: return None, 'normalizer task'
    if not C.queries: return None, 'no queries'
    if any(v.kind != 'table' for v in C.views): return None, 'compiled model carries affine views'
    for q in C.queries:
        if q['kind'] != 'expectation': return None, 'compiled ratio query'
        if len(q['f'].scope) > 1: return None, 'compiled query with scope size %d' % len(q['f'].scope)
    return dict(cards=list(C.cards), factors=[dict(scope=tuple(v.scope), values=list(v.values)) for v in C.views], evidence={}), None


# ---------------------------------------------------------------------------------------------------------------- discovery (R0's candidate pricing, bounded)
def discover(model, deadline, allowance_s, whole_model=True, epsilon=F(1, 200)):
    """cheap, bounded discovery: the whole-model forest / dag candidates (as R0 tries them) and R0's per-component candidate selection (minimum scalar forecast among support /
    dag / stream) after evidence restriction and component split; the WHOLE discovery is capped at `allowance_s` (typed decline when exhausted). Returns a plan dict or a decline."""
    t0 = time.monotonic(); cap = min(deadline, t0 + allowance_s) if deadline is not None else t0 + allowance_s
    def left(): return cap - time.monotonic()
    rec = dict(version=STRUCTURAL_VERSION, allowance_s=allowance_s, epsilon=str(epsilon), candidates=[], declines=[], components=[], whole=None)
    cards = model['cards']; n = len(cards)
    if n == 0: rec['declines'].append(dict(kind='*', reason='zero variables')); rec['applicable'] = False; rec['discovery_s'] = time.monotonic() - t0; return rec
    try:
        if whole_model:
            # forest: recognition only (cheap); execution is the attempt itself
            try: NFOREST.recognize(model, deadline=cap); rec['candidates'].append(dict(kind='forest', scope='whole', forecast=None, estimate_s=None, note='no forecast: R0 tries forest first with the full deadline'))
            except NFOREST.UnsupportedError as e: rec['declines'].append(dict(kind='forest', reason=str(e)[:120]))
            except NFOREST.ZeroEvidence: rec['declines'].append(dict(kind='forest', reason='ZERO_EVIDENCE (typed decline: not a structural publication)'))
            except TimeoutError: rec['declines'].append(dict(kind='forest', reason='discovery allowance exhausted'))
            if not model.get('evidence'):
                try: dp = NDAG.plan(model, deadline=min(cap, time.monotonic() + 2), epsilon=epsilon); fc = NCORE._dag_forecast(dp['stats']); rec['candidates'].append(dict(kind='dag', scope='whole', forecast=fc, estimate_s=fc / RATES['dag'])); rec['whole_dag_plan'] = dp
                except (ValueError, TimeoutError) as e: rec['declines'].append(dict(kind='dag', reason=str(e)[:120]))
            else: rec['declines'].append(dict(kind='dag', reason='evidence present (dag needs the component split first)'))
        # components after evidence restriction (R0's exact split; a ZERO_EVIDENCE restriction is a typed decline)
        try: split = NCORE.components(model, deadline=cap)
        except ValueError as e: rec['declines'].append(dict(kind='components', reason=str(e)[:80] + ' (typed decline)')); rec['applicable'] = False; rec['discovery_s'] = time.monotonic() - t0; return rec
        except TimeoutError: rec['declines'].append(dict(kind='components', reason='discovery allowance exhausted')); rec['applicable'] = False; rec['discovery_s'] = time.monotonic() - t0; return rec
        total = 0.0
        for old, cm in split:
            if left() <= 0: rec['declines'].append(dict(kind='components', reason='discovery allowance exhausted after %d of %d components' % (len(rec['components']), len(split)))); rec['applicable'] = False; rec['discovery_s'] = time.monotonic() - t0; return rec
            if not cm['factors']: rec['components'].append(dict(variables=old, kind='uniform', forecast=0, estimate_s=0.0, plan=None)); continue
            try: p = NCORE._discover_component(cm, cap)
            except (ValueError, TimeoutError) as e: rec['declines'].append(dict(kind='component', variables=len(old), reason=str(e)[:120])); rec['applicable'] = False; rec['discovery_s'] = time.monotonic() - t0; return rec
            est = (p['forecast'] or 0) / RATES.get(p['kind'], 1e8); total += est
            rec['components'].append(dict(variables=old, kind=p['kind'], forecast=p['forecast'], estimate_s=est, plan=p, discovery=p['discovery']))
        rec['components_estimate_s'] = total; rec['n_components'] = len(split)
        # whole-model dag vs components: R0's representation selection (minimum forecast)
        wd = next((c for c in rec['candidates'] if c['kind'] == 'dag'), None)
        if wd is not None and (wd['forecast'] or 0) <= sum(c['forecast'] or 0 for c in rec['components']): rec['whole'] = 'dag'
        rec['applicable'] = True
    finally: rec['discovery_s'] = time.monotonic() - t0
    return rec


def allocation(est, remaining_s, which):
    """explicit WALL allocation (seconds) of an admitted execution: min(GATE_FRACTION x remaining, max(ALLOC_FLOOR_S, ALLOC_MULTIPLE x estimate)); forest: FOREST_FRACTION x remaining"""
    if which == 'forest' or est is None: return max(0.0, FOREST_FRACTION * remaining_s)
    return max(0.0, min(GATE_FRACTION * remaining_s, max(ALLOC_FLOOR_S, ALLOC_MULTIPLE * est)))


def admitted(disc, remaining_s):
    """R0's deterministic gate reused: estimate <= GATE_FRACTION x remaining (forest has no estimate: admitted whenever applicable, as R0 does); returns (ok, estimate_s, which)"""
    if not disc.get('applicable'): return False, None, None
    if any(c['kind'] == 'forest' for c in disc['candidates']): return True, None, 'forest'
    if disc.get('whole') == 'dag': est = next(c['estimate_s'] for c in disc['candidates'] if c['kind'] == 'dag'); return est <= GATE_FRACTION * remaining_s, est, 'whole_dag'
    est = disc.get('components_estimate_s', 0.0); return est <= GATE_FRACTION * remaining_s, est, 'components'


# ---------------------------------------------------------------------------------------------------------------- execution
class StructuralStop(Exception):
    """typed outcome of a structural attempt that produced no rows: kind in ('DEADLINE', 'MEMORY', 'REPRESENTATION', 'NUMERICAL', 'ZERO_EVIDENCE', 'UNSUPPORTED', 'FAULT')"""
    def __init__(self, kind, reason, stats=None): super().__init__('%s: %s' % (kind, reason)); self.kind = kind; self.reason = reason; self.stats = stats or {}


def _rows_result(res):
    rows = res['intervals']; pts = res.get('points') or [[(lo + hi) / 2 for lo, hi in row] for row in rows]
    return [[(F(lo), F(hi)) for lo, hi in row] for row in rows], [[F(x) for x in row] for row in pts]


def execute(model, disc, deadline, which, epsilon=F(1, 200)):
    """run the admitted structural plan under the ABSOLUTE allocation deadline; returns dict(rows, points, record) over ALL variables of `model` (evidence variables as indicator
    rows; factor-free variables as uniform rows) or raises StructuralStop (typed). Nothing here touches the Work ledger."""
    t0 = time.monotonic(); cards = model['cards']; n = len(cards); ev = model.get('evidence', {}); comps = []; counters = dict(source_entries_read=0, kernel_counters=[], native_calls=0)
    def done(rows, pts, kind, extra=None):
        rec = dict(version=STRUCTURAL_VERSION, which=which, epsilon=str(epsilon), components=comps, rows=[[(str(lo), str(hi)) for lo, hi in row] for row in rows], points=[[str(x) for x in row] for row in pts], wall_s=time.monotonic() - t0, counters=counters, kernel_provenance=(_kernel_provenance() if counters['native_calls'] else None), discovery=dict(candidates=disc['candidates'], declines=disc['declines'], discovery_s=disc['discovery_s'], components_estimate_s=disc.get('components_estimate_s')))
        if extra: rec.update(extra)
        return dict(rows=rows, points=pts, record=rec)
    try:
        if which == 'forest':
            res = NFOREST.solve(model, deadline=deadline, epsilon=epsilon, independent_replay=True); rows, pts = _rows_result(res); comps.append(dict(variables=list(range(n)), kind='forest', stats={k: v for k, v in res['stats'].items() if k in ('elapsed_s', 'precision_bits', 'delta_bound', 'output_coordinates', 'producer_s', 'replay_s')}))
            counters['source_entries_read'] += (res['stats'].get('producer') or {}).get('source_entries_read', 0) if isinstance(res['stats'].get('producer'), dict) else 0
            return done(rows, pts, 'forest')
        if which == 'whole_dag':
            dp = disc['whole_dag_plan']; res = NDAG.execute_plan(dp, deadline=deadline); rows, pts = _rows_result(res)
            comps.append(dict(variables=list(range(n)), kind='dag', forecast=NCORE._dag_forecast(dp['stats']), stats={k: res['stats'].get(k) for k in ('additions', 'multiplications', 'contraction_rows', 'numeric_execution_s', 'max_output_rational_bits')}, delta=str(dp['delta'])))
            return done(rows, pts, 'dag')
        rows = [None] * n; pts = [None] * n
        for v, a in ev.items(): rows[v] = [(F(int(s == a)), F(int(s == a))) for s in range(cards[v])]; pts[v] = [F(int(s == a)) for s in range(cards[v])]
        for c in disc['components']:
            old = c['variables']
            if time.monotonic() >= deadline: raise StructuralStop('DEADLINE', 'allocation expired before component %s' % old[:4])
            if c['kind'] == 'uniform':
                for v in old: rows[v] = [(F(1, cards[v]), F(1, cards[v]))] * cards[v]; pts[v] = [F(1, cards[v])] * cards[v]
                comps.append(dict(variables=old, kind='uniform', exact=True)); continue
            p = c['plan']; ct = time.monotonic()
            try: res = NCORE._execute_component(p, deadline)
            except NSUPPORT.ResourceStop as e:
                kind = 'DEADLINE' if e.reason == 'DEADLINE' else ('MEMORY' if e.reason == 'MEMORY' else ('NUMERICAL' if e.reason in ('RANGE', 'WIDTH', 'FPENV') else 'REPRESENTATION'))
                raise StructuralStop(kind, '%s on component of %d variables (%s route)' % (e.reason, len(old), p['kind']), dict(stats=e.stats, discovery=p.get('discovery')))
            except TimeoutError: raise StructuralStop('DEADLINE', 'component %s route %s' % (old[:4], p['kind']))
            if res.get('status') == 'ZERO_EVIDENCE': raise StructuralStop('ZERO_EVIDENCE', 'structural executor reports zero evidence on a component (typed decline; proved only by the CQR mechanisms)')
            r_, p_ = _rows_result(res)
            if len(r_) != len(old): raise StructuralStop('FAULT', 'component rows %d != variables %d' % (len(r_), len(old)))
            for v, row, q in zip(old, r_, p_): rows[v] = row; pts[v] = q
            st = res.get('stats') or {}; counters['source_entries_read'] += int(st.get('source_entries_read') or 0)
            if p['kind'] in ('support', 'stream'): counters['native_calls'] += 1; counters['kernel_counters'].append(dict(kind=p['kind'], counters=st.get('counters'), kernel_s=st.get('kernel_s'), execution_s=st.get('execution_s')))
            comps.append(dict(variables=old, kind=p['kind'], forecast=p['forecast'], order=(list(p['order']) if p['kind'] == 'support' else None), wall_s=time.monotonic() - ct, status=res.get('status'), stats={k: st.get(k) for k in ('elapsed_s', 'kernel_s', 'kernel_status', 'max_width', 'additions', 'multiplications', 'execution_s', 'total_s') if k in st}, discovery=p.get('discovery')))
        if any(r is None for r in rows): raise StructuralStop('FAULT', 'uncovered variables %s' % [v for v in range(n) if rows[v] is None][:6])
        return done(rows, pts, 'components')
    except StructuralStop: raise
    except NFOREST.ZeroEvidence: raise StructuralStop('ZERO_EVIDENCE', 'forest reports zero evidence (typed decline)')
    except (NFOREST.DeadlineExceeded, NDAG.Deadline, TimeoutError) as e: raise StructuralStop('DEADLINE', str(e)[:100])
    except (NFOREST.UnsupportedError, NDAG.Unsupported) as e: raise StructuralStop('UNSUPPORTED', str(e)[:120])
    except MemoryError: raise StructuralStop('MEMORY', 'MemoryError inside a structural executor')
    except (OverflowError, ZeroDivisionError) as e: raise StructuralStop('NUMERICAL', '%s: %s' % (type(e).__name__, str(e)[:80]))
    except Exception as e: raise StructuralStop('FAULT', '%s: %s' % (type(e).__name__, str(e)[:120]))


# ---------------------------------------------------------------------------------------------------------------- query composition (ORIGINAL task answers)
def answers_original(task, rows):
    """per original singleton query j: the executed row interval of (variable, state)"""
    out = []
    for q in task['queries']:
        o = q.output; lo, hi = rows[o['variable']][o['state']]; out.append((lo, hi))
    return out


def answers_compiled(C, rows):
    """per compiled query j (expectation, scope size <= 1) in COMPILED units: the compiler's constant queries first; otherwise the sign-correct interval sum
    sum_s f(s) [lo_s, hi_s] over the executed singleton row of the query's variable (a negative coefficient swaps the endpoints); clipped to [0, 1] (original answers are probabilities)"""
    out = []
    for j, q in enumerate(C.queries):
        if j in C.constant_queries: v = F(C.constant_queries[j]); out.append((v, v)); continue
        f = q['f']
        if not f.scope: v = F(f.values[0]); out.append((v, v)); continue
        u = f.scope[0]; lo = F(0); hi = F(0)
        for s in range(C.cards[u]):
            c = F(f.values[s]); a, b = rows[u][s]
            if c >= 0: lo += c * a; hi += c * b
            else: lo += c * b; hi += c * a
        out.append((min(F(1), max(F(0), lo)), max(F(0), min(F(1), hi))))
    return out


# ---------------------------------------------------------------------------------------------------------------- checker-side verification (bounded re-execution)
def verify(model, rec, deadline):
    """re-execute every recorded component (same kind; the order is re-derived by the same planning) / the recorded whole-model route on the BOUND model under the checker's deadline;
    the rows must reproduce exactly. Returns (rows, None) or (None, failure message). The kernels' enclosures are TRUSTED at this boundary (as in the frozen pac gate)."""
    try:
        if rec.get('version') != STRUCTURAL_VERSION: return None, 'structural record version %s is not %s' % (str(rec.get('version'))[:40], STRUCTURAL_VERSION[:40])
        epsilon = F(str(rec.get('epsilon', '1/200'))); cards = model['cards']; n = len(cards); want = [[(F(a), F(b)) for a, b in row] for row in rec['rows']]
        if len(want) != n or any(len(row) != cards[v] for v, row in enumerate(want)): return None, 'recorded structural rows do not match the bound model shape'
        if rec['which'] == 'forest':
            res = NFOREST.solve(model, deadline=deadline, epsilon=epsilon, independent_replay=True); got, _ = _rows_result(res)
        elif rec['which'] == 'whole_dag':
            if model.get('evidence'): return None, 'structural whole-model dag recorded on a model with evidence'
            res = NDAG.execute_plan(NDAG.plan(model, deadline=deadline, epsilon=epsilon), deadline=deadline); got, _ = _rows_result(res)
        elif rec['which'] == 'components':
            ev = model.get('evidence', {}); got = [None] * n
            for v, a in ev.items(): got[v] = [(F(int(s == a)), F(int(s == a))) for s in range(cards[v])]
            split = NCORE.components(model, deadline=deadline); by = {tuple(old): cm for old, cm in split}
            for c in rec['components']:
                old = tuple(c['variables'])
                if old not in by: return None, 'recorded component %s is not a component of the bound model' % list(old)[:4]
                cm = by[old]
                if c['kind'] == 'uniform':
                    if cm['factors']: return None, 'uniform component recorded on a component with factors'
                    for v in old: got[v] = [(F(1, cards[v]), F(1, cards[v]))] * cards[v]
                    continue
                if c['kind'] not in ('support', 'dag', 'stream'): return None, 'unknown structural component kind %s' % c['kind']
                plan = NCORE._discover_component(cm, deadline, c['kind']); res = NCORE._execute_component(plan, deadline)
                if res.get('status') == 'ZERO_EVIDENCE': return None, 'structural re-execution reports zero evidence'
                r_, _ = _rows_result(res)
                for v, row in zip(old, r_): got[v] = row
            if any(r is None for r in got): return None, 'structural re-execution leaves variables uncovered'
        else: return None, 'unknown structural route %s' % str(rec.get('which'))[:30]
        if got != want: return None, 'structural re-execution does not reproduce the recorded rows (%s)' % rec['which']
        return got, None
    except (TimeoutError, NFOREST.DeadlineExceeded, NDAG.Deadline): return None, 'UNVERIFIABLE: structural re-execution exceeded the checker allowance'
    except NSUPPORT.ResourceStop as e: return None, ('UNVERIFIABLE: structural re-execution stopped (%s)' % e.reason) if e.reason in ('DEADLINE', 'MEMORY') else ('structural re-execution refused: %s' % e.reason)
    except (ValueError, NFOREST.UnsupportedError, NDAG.Unsupported) as e: return None, 'structural re-execution refused: %s' % str(e)[:100]
    except MemoryError: return None, 'UNVERIFIABLE: MemoryError during structural re-execution'
