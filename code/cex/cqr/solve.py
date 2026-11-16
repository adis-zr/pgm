"""CQR CONTROLLER -- the manuscript's REFERENCE POLICY (§7), executable (no cost oracle):
 1. bind the task; create the PROTECTED exact reference (reference.Reference) and reserve HALF of the charged work quanta for it (gamma = 1/2 in Work units; the compile
    is charged to the optional half and the reference catches up before the adaptive loop; quantum rounding is bounded by QUANTUM);
 2. in the optional half: the bounded reduction compiler (compiler.compile_task; the enabled operator set is the ARM), then the frontier on the compiled model;
 3. adaptive loop: alternate ONE refinement quantum (cell with the largest E_C h_C when a candidate exists, else the largest E_C; canonical ties; close when N_C <= LEAF_CAP,
    else split on the first unassigned variable of the fixed order) and ONE statistical quantum (a full-support ratio draw, then a fixed-candidate signed draw; record BEFORE
    resolve; one draw in flight per stream; a failed draw stops its stream);
 4. risk: delta/2 to the ratio stream; delta / (2 e (e+1)) to validation epoch e; an epoch ends after 2^e completed observations unless it certifies; candidate = schema-
    feasible rational projection of the ratio estimate (or a feasible deterministic point); E = 0 => deterministic residual test (certify or retire), never inverse-zero;
 5. after every completed transaction: deterministic publication first (roots of F-/F+ intersected with every earlier proved interval; feasibility (4) with tau = eps - bias -
    rounding), then PAC (ratio intervals ∩ deterministic, or a certified candidate). An empty intersection DISABLES the statistical claim (diagnostic) and never the reference.
 6. the reference completing => EXACT publication (any mode). EXACT_RATIONAL mode publishes only exact results (reference / fully closed frontier / proved constants with a positive witness).
Normalizer tasks (query_spec.normalizer_task): Z with relative error; component omission and TV-only surrogates disabled; publish c in [(1-eps) U, (1+eps) L].
Memory: open cells capped (OPEN_CAP): on pressure refinement only closes, carving stops; the reference is never cancelled."""
import os, sys, time, json, random, hashlib
from fractions import Fraction as F
import sys as _sys; _sys.set_int_max_str_digits(0)
from math import prod
HERE = os.path.dirname(os.path.abspath(__file__)); NEWARM = os.path.join(os.path.dirname(HERE), 'newarm')
for p in (HERE, NEWARM):
    if p not in sys.path: sys.path.insert(0, p)
import compiler as CP, frontier as FR, reference as RF, numerics as NM
from task import Work, task_identity

SOLVER_VERSION = 'cqr-solve-v1 (2026-11-16)'
POLICY = dict(solver_version=SOLVER_VERSION, compiler=CP.POLICY, frontier=FR.FRONTIER_VERSION,
              quantum_units=4096, reference_parity='before EVERY publication test the reference is brought to >= the cumulative work of the optional half (gamma = 1/2 at every publication; rounding <= one reference step of 256 assignments)', work_unit_commensurability='every table lookup (factor or query, in the reference, in cell closures, in draws and in compiler scans) is ONE entry unit; cell / rational operations one unit each: the two halves are measured in the same currency', deterministic_test_cadence='every max(1, |F| x K // 1024) optional quanta (the root computation is O(|F| log |F|) per query, K queries; charged |F| x K ratops per test; the cadence bounds the test cost to a constant fraction of the optional half)', reference_share='1/2 of charged Work units (gamma = 1/2): the reference runs one quantum for every optional quantum; the compile is charged to the optional half and the reference catches up before the adaptive loop',
              leaf_cap=4096, open_cap=40000, open_cap_rule='min(40000, 4e7 / n_compiled) (prefix cells store <= n ints)', carve_max_free=14, deterministic_test='after every optional quantum (charged: cells x queries ratops)',
              risk='delta/2 ratio stream; delta/(2 e (e+1)) validation epoch e; epoch length 2^e completed observations',
              predictable_weights='b_t = the largest power of two <= (U*/U_t)^2 (ratio) / (E*/E_t)^2 (signed): positive, predictable, dyadic (bit growth bounded; statistics stay EXACT rationals; max bit length recorded in work.max_bits)',
              candidate='schema-feasible rational projection of the ratio estimate onto the dyadic grid of resolution eps/16 inside the deterministic boxes (simplex rows for singleton families; clip to [0,1] otherwise), else the un-snapped projection, else deterministic interval midpoints; fixed within the epoch',
              rounding_margin='2/10^8 (8 outward decimal digits)', work_unit='one table entry read / rational op / point evaluation / cell op (task.Work)')
ARMS = {
    'N1_CQR': dict(enabled=set(CP.POLICY['order']), signed_stream=True, query_directed_refinement=True),
    'G0_CQR': dict(enabled={'evidence'}, signed_stream=False, query_directed_refinement=False),
    'N1_NO_QUOTIENT': dict(enabled=set(CP.POLICY['order']) - {'exact_quotient_pass', 'approx_quotient'}, signed_stream=True, query_directed_refinement=True),
    'N1_NO_AFFINE': dict(enabled=set(CP.POLICY['order']) - {'affine'}, signed_stream=True, query_directed_refinement=True),
    'N1_NO_INFLUENCE': dict(enabled=set(CP.POLICY['order']) - {'influence_deletion'}, signed_stream=True, query_directed_refinement=True),
    'N1_NO_CONCENTRATION': dict(enabled=set(CP.POLICY['order']) - {'concentration'}, signed_stream=True, query_directed_refinement=True),
    'N1_NO_SYMMETRY_RELEVANCE': dict(enabled=set(CP.POLICY['order']) - {'symmetry', 'leaf_sumout', 'component_omission'}, signed_stream=True, query_directed_refinement=True),
    'N1_NO_SIGNED_STREAM': dict(enabled=set(CP.POLICY['order']), signed_stream=False, query_directed_refinement=True),
    'N1_NO_QUERY_DIRECTED_REFINEMENT': dict(enabled=set(CP.POLICY['order']), signed_stream=True, query_directed_refinement=False),
}
MARGIN = F(2, 10 ** 8)


class Stop(Exception):
    def __init__(self, kind, info=None): super().__init__(kind); self.kind = kind; self.info = info or {}


def _simplex_feasible(boxes):
    """boxes: list of (lo, hi) per state; returns a point in the boxes summing to 1, or None"""
    los = [max(F(0), lo) for lo, hi in boxes]; his = [min(F(1), hi) for lo, hi in boxes]
    if any(l > h for l, h in zip(los, his)) or sum(los) > 1 or sum(his) < 1: return None
    pt = list(los); rem = 1 - sum(los)
    for i in range(len(pt)):
        add = min(rem, his[i] - los[i]); pt[i] += add; rem -= add
    return pt if rem == 0 else None


def _box(lo, hi, tau):
    """the publication box of one query: inside the certified interval AND within tau of both endpoints (manuscript (4) intersected with the legacy row contract lo <= c <= hi)"""
    return (max(lo, hi - tau), min(hi, lo + tau))


def _feasible_point(task, bounds, groups):
    """bounds: per original query (lo, hi) boxes; groups: list of lists of query indices forming simplex rows (singleton families) -> point list or None"""
    pt = [None] * len(bounds)
    for g in groups:
        p = _simplex_feasible([bounds[j] for j in g])
        if p is None: return None
        for j, x in zip(g, p): pt[j] = x
    for j, (lo, hi) in enumerate(bounds):
        if pt[j] is None:
            if lo > hi: return None
            pt[j] = min(max((lo + hi) / 2, F(0)), F(1))
    return pt


def _singleton_groups(task):
    """indices of queries that form one simplex row per original variable (all states of a variable present as singleton queries)"""
    by = {}
    for j, q in enumerate(task['queries']):
        if q.kind == 'expectation' and (q.output or {}).get('kind') == 'singleton': by.setdefault(q.output['variable'], {})[q.output['state']] = j
    cards = task['model']['cards']
    return [[d[s] for s in range(cards[v])] for v, d in by.items() if len(d) == cards[v]]


def solve(task, deadline, arm, seed, cap_bytes=3 * 1024 ** 3, diagnostic=None):
    """diagnostic (QUALIFICATION ONLY, never a production arm; recorded in the certificate and REFUSED by the checker): 'sampling_only' switches off the protected reference,
    the frontier refinement and deterministic publication so only the statistical streams can publish (confidence-sequence calibration on tiny models at large delta);
    'no_reference' switches off only the protected reference so the frontier + streams must publish (stream / refinement interaction controls)"""
    t0 = time.monotonic(); spec = ARMS[arm]; work_ref = Work(); work_opt = Work(); rng = random.Random(int(hashlib.sha256(('cqr|%s|%s' % (seed, arm)).encode()).hexdigest(), 16))
    model = task['model']; queries = task['queries']; K = len(queries); eps = task['epsilon']; delta = task['delta']; mode = task['mode']; normalizer = bool((task.get('query_spec') or {}).get('normalizer_task'))
    trace = dict(arm=arm, diagnostic=diagnostic, solver_version=SOLVER_VERSION, policy_sha256=hashlib.sha256(json.dumps(POLICY, sort_keys=True, default=str).encode()).hexdigest(), phase='bind', events=[])
    def late(): return deadline is not None and time.monotonic() >= deadline
    def check(where):
        if late(): raise Stop('DEADLINE', dict(where=where))
    groups = _singleton_groups(task) if not normalizer else []
    # ---------------- 1. protected reference
    ref = RF.Reference(model, queries, work_ref); check('bind')
    def ref_quantum(units):
        if diagnostic in ('sampling_only', 'no_reference'): return 0
        w0 = work_ref.total()
        while work_ref.total() - w0 < units and not ref.done:
            ref.step(256)
            if late(): break
        return work_ref.total() - w0
    # ---------------- 2. compile (optional half) then catch-up
    trace['phase'] = 'compile'; C = None; compile_log = None; zero_proof = None
    try: C, compile_log = CP.compile_task(task, enabled=spec['enabled'] if normalizer is False else (spec['enabled'] - {'component_omission', 'approx_quotient', 'influence_deletion', 'concentration'}), deadline=deadline, work=work_opt)
    except CP.ZeroEvidence as z: zero_proof = z.proof
    check('after compile')
    ref_quantum(work_opt.total())                      # the reference catches up to the optional half's spend
    if zero_proof is not None:
        return dict(outcome='PROVED_ZERO_EVIDENCE', guarantee_type='DETERMINISTIC', zero_proof=dict(kind='compiler', proof=zero_proof), certificate=_cert(task, arm, mode, trace, None, None, None, None, None, [], ref, work_ref, work_opt, None, None, t0, zero=zero_proof), stats=_stats(work_ref, work_opt, None, None, t0))
    cards = C.cards; cq = C.queries; Kc = len(cq)
    assert [q['orig_index'] for q in cq] == list(range(K)), 'compiled queries must be the original queries in order'
    # a direct concentration answer: deterministic publication candidate (bias already in C.bias)
    direct = compile_log.get('direct')
    fr = FR.Frontier(cards, C.views, cq, work_opt, order=list(range(len(cards)))) if cards else None
    trace['phase'] = 'adaptive'; Q = POLICY['quantum_units']; open_cap = max(64, min(POLICY['open_cap'], (4 * 10 ** 7) // max(1, len(cards))))      # memory: prefix cells store <= n ints each
    ratio = FR.RatioStream(Kc, delta / 2, fr.U() if fr and fr.U() > 0 else F(1), random.Random(rng.getrandbits(64))) if (fr is not None and mode == 'PAC_EPS') else None
    if normalizer: spec = dict(spec, signed_stream=False, query_directed_refinement=False)
    def known_scale():
        """Z_original = Z_compiled * prod(known positive scalars) (normalizer tasks never omit a component, so every cancelled scalar is a KNOWN exact rational)"""
        sc = F(1)
        for d in C.scalars:
            if d.get('kind') == 'omitted_component_mass': raise AssertionError('normalizer task with an omitted component')
            sc *= F(d['value'])
        for d in (C.certs[0].get('constant_factor_scalars') or []): sc *= F(d['value'])
        return sc
    def try_publish_normalizer():
        """Z with RELATIVE error eps: 0 < L <= Z <= U (original units) and c in [(1-eps) U, (1+eps) L]; deterministic from the frontier, PAC from the ratio stream's Z interval ∩ deterministic"""
        nonlocal pub
        sc = known_scale()
        if fr is None: z = sc; pub = dict(route='normalizer_exact_zero_dimensional', bounds=[(z, z)], point=[z], guarantee='DETERMINISTIC', exact=True, scale=str(sc)); return pub
        if mode == 'EXACT_RATIONAL':
            if fr.open: return None
            z = fr.resolved_mass / fr.scale_den * sc
            if z == 0: return None
            pub = dict(route='normalizer_exact_frontier_closure', bounds=[(z, z)], point=[z], guarantee='DETERMINISTIC', exact=True, scale=str(sc)); return pub
        L = fr.Zlo() / fr.scale_den * sc; U = fr.Zhi() / fr.scale_den * sc
        if L <= 0: return None
        if (1 - eps) * U <= (1 + eps) * L:
            c = ((1 - eps) * U + (1 + eps) * L) / 2; pub = dict(route='normalizer_deterministic_frontier', bounds=[(L, U)], point=[c], guarantee='DETERMINISTIC', scale=str(sc)); return pub
        if mode == 'PAC_EPS' and ratio is not None and ratio.stopped is None:
            zi = ratio.Z_interval()
            if zi is not None:
                l2 = max(L, zi[0] / fr.scale_den * sc); u2 = min(U, zi[1] / fr.scale_den * sc)
                if l2 > u2: disabled.append(dict(kind='INTERSECTION_EMPTY_Z', t=ratio.t)); ratio.stopped = 'INTERSECTION_EMPTY (Z; statistical claim disabled; diagnostic)'; return None
                if (1 - eps) * u2 <= (1 + eps) * l2:
                    c = ((1 - eps) * u2 + (1 + eps) * l2) / 2; pub = dict(route='normalizer_pac_ratio_intersected_with_deterministic', bounds=[(l2, u2)], det_bounds=[(L, U)], stat_bounds=[(str(zi[0] / fr.scale_den * sc), str(zi[1] / fr.scale_den * sc))], point=[c], guarantee='PAC', scale=str(sc), ratio_t=ratio.t); return pub
        return None
    epochs = []; cur_epoch = None; epoch_no = 0; stat_toggle = 0; events = trace['events']; det_bounds = None; pub = None; disabled = []
    def tau(j): return eps - C.bias[j] - MARGIN
    def widen(b):
        """PUBLISHED bounds for the ORIGINAL task: the compiled-model enclosure widened by the proved compiler bias beta_j (|mu_orig - mu_compiled| <= beta_j); clipped to [0,1]"""
        out = []
        for j, x in enumerate(b):
            if x is None or x[0] == 'UNDEFINED': out.append(x); continue
            out.append((max(F(0), x[0] - C.bias[j]), min(F(1), x[1] + C.bias[j])))
        return out
    def around(c, j, r):
        return (max(F(0), c - r), min(F(1), c + r))
    # ------------------------------------------------ publication tests
    def query_bounds_original():
        """per ORIGINAL query: (lo, hi) deterministic from constants / frontier; compiled queries are the original queries carried through the chain"""
        if fr is None:   # zero-dimensional compiled model: every query is exact = its table value at the empty assignment... all variables fixed: compiled query views have empty scope
            out = []
            for q in cq:
                if q['kind'] == 'expectation': v = q['f'].values[0]; out.append((v, v))
                else:
                    g = q['g'].values[0]
                    if g == 0: out.append(('UNDEFINED', 'UNDEFINED'))
                    else: out.append((q['h'].values[0] / g, q['h'].values[0] / g))
            return out
        if 'det' in cache: return cache['det']
        try: b = fr.deterministic_bounds(deadline=deadline)
        except TimeoutError: raise Stop('DEADLINE', dict(where='deterministic bounds'))
        out = []
        for j in range(Kc):
            if j in C.constant_queries: c = C.constant_queries[j]; out.append((c, c))
            else: out.append(b[j])
        cache['det'] = out; return out
    def positive_mass():
        """Z > 0 proved (compiled units): resolved mass > 0, or sum L_C > 0, or the compiler's witness"""
        if fr is None: return True
        return fr.resolved_mass > 0 or any(c.L > 0 for c in fr.open.values()) or (C.witness is not None and FR_weight(C, C.witness) > 0)
    cache = {}
    def denominators_positive():
        """per query: a proved positive lower bound on its denominator (Z for expectations; D_j for ratios) in compiled units; cached per iteration (`cache` is reset every loop turn)"""
        if 'Lj' in cache: return cache['Lj']
        out = []
        if fr is None:
            for q in cq: out.append(F(1) if q['kind'] == 'expectation' else q['g'].values[0])
        else:
            zlo = fr.Zlo(); rd = fr.resolved_den if any(q['kind'] == 'ratio' for q in cq) else None
            for j, q in enumerate(cq):
                if q['kind'] == 'expectation': out.append(zlo); continue
                out.append(rd[j] + sum(c.L * c.qlo[j][1] for c in fr.open.values()))
        cache['Lj'] = out; return out
    def try_publish(route_hint):
        nonlocal pub
        if normalizer: return try_publish_normalizer()
        if mode == 'EXACT_RATIONAL':
            if fr is not None and fr.open: return None
            b = query_bounds_original()
            if any(x[0] != x[1] for x in b if x[0] != 'UNDEFINED'): return None
            if not positive_mass(): return None
            pub = dict(route='exact_frontier_closure' if fr is not None else 'exact_zero_dimensional', bounds=b, point=[x[0] for x in b], guarantee='DETERMINISTIC', exact=True); return pub
        if not positive_mass(): return None
        Lj = denominators_positive(); b = query_bounds_original(); boxes = []
        if diagnostic == 'sampling_only': b = [(F(0), F(1)) if x[0] != 'UNDEFINED' else x for x in b]       # deterministic information withheld: only the streams may certify
        for j in range(Kc):
            lo, hi = b[j]
            if lo == 'UNDEFINED': boxes.append(None); continue
            if cq[j]['kind'] == 'ratio' and Lj[j] <= 0: boxes.append(None); continue        # denominator not yet proved positive: no claim for this query
            boxes.append(_box(lo, hi, tau(j)))
        det_ok = all(bx is not None for bx in boxes) and diagnostic != 'sampling_only'
        if det_ok:
            pt = _feasible_point(task, boxes, groups)
            if pt is not None: pub = dict(route='deterministic_frontier' if fr is not None else 'deterministic_zero_dimensional', bounds=widen(b), compiled_bounds=b, point=pt, guarantee='DETERMINISTIC', tau=[str(tau(j)) for j in range(Kc)]); return pub
        if mode != 'PAC_EPS' or fr is None: return None
        # PAC: ratio stream intervals ∩ deterministic
        if ratio is not None and ratio.stopped is None:
            iv = ratio.intervals()
            if iv is not None:
                inter = []; empty = False
                for j in range(Kc):
                    lo, hi = b[j]
                    if lo == 'UNDEFINED' or (cq[j]['kind'] == 'ratio' and Lj[j] <= 0): inter.append(None); continue
                    l2, h2 = max(lo, iv[j][0]), min(hi, iv[j][1])
                    if l2 > h2: empty = True; inter.append(None); continue
                    inter.append((l2, h2))
                if empty: disabled.append(dict(kind='INTERSECTION_EMPTY', t=ratio.t)); ratio.stopped = 'INTERSECTION_EMPTY (statistical claim disabled; diagnostic)'
                elif all(x is not None for x in inter):
                    pt = _feasible_point(task, [_box(l, h, tau(j)) for j, (l, h) in enumerate(inter)], groups)
                    if pt is not None: pub = dict(route='pac_ratio_intersected_with_deterministic', bounds=widen(inter), compiled_bounds=inter, det_bounds=b, stat_bounds=[(str(a), str(c)) for a, c in iv], point=pt, guarantee='PAC', tau=[str(tau(j)) for j in range(Kc)], ratio_t=ratio.t); return pub
        return None
    # ------------------------------------------------ candidate construction (schema feasible; outer intervals)
    def make_candidate():
        if fr is None: return None
        est = None
        if ratio is not None and ratio.stopped is None and ratio.H > 0:
            est = [min(F(1), max(F(0), (ratio.G[j] / ratio.Hj[j]) if ratio.Hj[j] > 0 else F(1, 2))) for j in range(Kc)]
        b = query_bounds_original()
        if any(x[0] == 'UNDEFINED' for x in b): return None
        boxes = [(lo, hi) for lo, hi in b]
        grid = eps / 16
        def snap(x, lo, hi):
            """nearest point of the dyadic-rational grid (resolution eps/16) inside [lo, hi]: a schema-feasible rational projection whose coincidences with constant query values
            (e.g. 1/2) are reachable, so proved-zero-residual cells can actually be omitted"""
            g_ = round(x / grid) * grid; return min(max(g_, lo), hi)
        if est is not None:
            boxes2 = [(snap(est[j], lo, hi),) * 2 for j, (lo, hi) in enumerate(boxes)]
            pt = _feasible_point(task, [(x[0], x[1]) for x in boxes2], groups)
            if pt is not None: return pt
            pt = _feasible_point(task, [(min(max(est[j], lo), hi),) * 2 for j, (lo, hi) in enumerate(boxes)], groups)
            if pt is not None: return pt
        return _feasible_point(task, boxes, groups)
    def FR_weight(C_, x):
        w = F(1)
        for v in C_.views: w *= v.at(C_.cards, x)
        return w
    # ------------------------------------------------ the loop
    direct_pub = None; it = 0; last_opt = 0
    if direct is not None and mode != 'EXACT_RATIONAL':
        # concentration gave a direct certified answer with bias in C.bias: publish deterministically (point = f(x*), interval = point ± bias handled by tau)
        b = [(direct['answers'][j], direct['answers'][j]) if j in direct['answers'] else None for j in range(Kc)]
        if all(x is not None for x in b) and positive_mass():
            pt = _feasible_point(task, [_box(lo, hi, tau(j)) for j, (lo, hi) in enumerate(b)], groups)
            if pt is not None: pub = dict(route='deterministic_concentration', bounds=widen(b), compiled_bounds=b, point=pt, guarantee='DETERMINISTIC', tau=[str(tau(j)) for j in range(Kc)])
    ref_quantum(max(0, work_opt.total() - work_ref.total()))        # parity before the first publication test
    if pub is None and not ref.done: try_publish('initial')
    trace['normalizer_task'] = normalizer
    while pub is None:
        check('loop')
        # ---- reference quantum: at least Q units, and at least as many units as the optional half spent in the previous iteration (gamma = 1/2 in Work units)
        ref_quantum(max(Q, last_opt))
        if ref.done:
            r = ref.result(); check('reference completion')
            if r['kind'] == 'ZERO_EVIDENCE': return dict(outcome='PROVED_ZERO_EVIDENCE', guarantee_type='DETERMINISTIC', zero_proof=dict(kind='reference_enumeration', assignments=r['assignments']), certificate=_cert(task, arm, mode, trace, C, compile_log, fr, ratio, epochs, events, ref, work_ref, work_opt, None, None, t0, zero=dict(kind='reference')), stats=_stats(work_ref, work_opt, fr, ratio, t0))
            if normalizer: z = F(r['Z']); pub = dict(route='normalizer_exact_reference', bounds=[(z, z)], point=[z], guarantee='DETERMINISTIC', exact=True, reference=r); break
            pub = dict(route='exact_reference', bounds=[(F(a), F(a)) if a != 'UNDEFINED' else ('UNDEFINED', 'UNDEFINED') for a in r['answers']], point=[F(a) if a != 'UNDEFINED' else 'UNDEFINED' for a in r['answers']], guarantee='DETERMINISTIC', exact=True, reference=r); break
        if fr is None: break
        # ---- optional quantum: refinement
        w0 = work_opt.total(); work_opt.cells += len(fr.open)        # the cell-selection scan is charged
        it += 1; cache.clear()
        if fr.open and diagnostic != 'sampling_only':
            cand = cur_epoch.cand if (cur_epoch is not None and cur_epoch.retired is None) else None
            if cand is not None and spec['query_directed_refinement']:
                cells, _E = fr.signed_law(cand, key=('epoch', cur_epoch.epoch)); best = max(cells, key=lambda ca: (ca[1], -ca[0].id))[0] if cells else max(fr.open.values(), key=lambda c: (c.E, -c.id))
            else: best = max(fr.open.values(), key=lambda c: (c.E, -c.id))
            if best.N <= POLICY['leaf_cap'] or len(fr.open) > open_cap: fr.close(best.id); events.append(dict(op='close', cell=best.id))
            else: kids = fr.split(best.id); events.append(dict(op='split', cell=best.id, children=kids))
            cache.clear()
        # ---- optional quantum: statistics (one ratio draw, one signed draw)
        if mode == 'PAC_EPS' and fr.open:
            if ratio is not None and ratio.stopped is None:
                s = ratio.launch(fr)
                if s is not None:
                    events.append(dict(op='ratio_draw', cell=s['cell'], x={str(k): v for k, v in s['x'].items()}, U=str(s['U']), b=str(s['b']), A=str(s['A']), a=[str(v) for v in s['a']], d=[str(v) for v in s['d']]))
                    try:
                        w, fq = fr.weight_and_queries(s['x']); ratio.complete(fr, w, fq)
                    except Exception as ex: ratio.stopped = 'draw failed: %s' % str(ex)[:80]; events.append(dict(op='ratio_stream_stopped', reason=ratio.stopped)); ratio.in_flight = None
                    else:
                        if diagnostic != 'sampling_only' and s['cell'] in fr.open and (fr.n - fr.open[s['cell']].depth) <= POLICY['carve_max_free'] and len(fr.open) <= open_cap:
                            fr.carve_point(s['cell'], s['x']); events.append(dict(op='carve', cell=s['cell'], x={str(k): v for k, v in s['x'].items()})); cache.clear()
            if spec['signed_stream']:
                if cur_epoch is None or cur_epoch.retired is not None:
                    cand = make_candidate()
                    if cand is not None:
                        epoch_no += 1; de = delta / (2 * epoch_no * (epoch_no + 1)); cells, E0 = fr.signed_law(cand, key=('epoch', epoch_no))
                        cur_epoch = FR.SignedStream(cand, Kc, de, E0 if E0 > 0 else F(1), random.Random(rng.getrandbits(64)), epoch_no); epochs.append(cur_epoch)
                        events.append(dict(op='epoch_start', epoch=epoch_no, candidate=[str(c) for c in cand], delta_e=str(de), E_star=str(cur_epoch.E_star)))
                if cur_epoch is not None and cur_epoch.retired is None:
                    s = cur_epoch.launch(fr)
                    if s == 'E_ZERO':
                        # deterministic residual test: S_j(c) = d_j exactly; certify if |d_j| <= tau_j L_j for all j, else retire
                        Lj = denominators_positive(); ok = True; rn = fr.resolved_num; rd_ = fr.resolved_den; rm = fr.resolved_mass
                        for j in range(Kc):
                            d = rn[j] - cur_epoch.cand[j] * (rm if cq[j]['kind'] == 'expectation' else rd_[j])
                            if Lj[j] <= 0 or abs(d) > tau(j) * Lj[j]: ok = False; break
                        events.append(dict(op='epoch_E_zero', epoch=epoch_no, certified=ok))
                        if ok and positive_mass() and diagnostic != 'sampling_only': pub = dict(route='deterministic_signed_residual_E_zero', bounds=[around(c, j, eps - MARGIN) for j, c in enumerate(cur_epoch.cand)], point=list(cur_epoch.cand), guarantee='DETERMINISTIC', tau=[str(tau(j)) for j in range(Kc)], epoch=epoch_no); break
                        cur_epoch.retired = 'E_ZERO_not_certified'
                    elif s is not None:
                        events.append(dict(op='signed_draw', epoch=epoch_no, cell=s['cell'], x={str(k): v for k, v in s['x'].items()}, p=str(s['p']), E=str(s['E']), b=str(s['b']), d=[str(v) for v in s['d']]))
                        try:
                            w, fq = fr.weight_and_queries(s['x']); cur_epoch.complete(fr, w, fq)
                        except Exception as ex: cur_epoch.retired = 'draw failed: %s' % str(ex)[:80]; events.append(dict(op='epoch_retired', epoch=epoch_no, reason=cur_epoch.retired)); cur_epoch.in_flight = None
                        else:
                            iv = cur_epoch.intervals(); Lj = denominators_positive()
                            if iv is not None and positive_mass() and all(Lj[j] > 0 and iv[j][0] >= -tau(j) * Lj[j] and iv[j][1] <= tau(j) * Lj[j] for j in range(Kc)):
                                pub = dict(route='pac_signed_residual_validation', bounds=[around(c, j, eps - MARGIN) for j, c in enumerate(cur_epoch.cand)], point=list(cur_epoch.cand), guarantee='PAC', tau=[str(tau(j)) for j in range(Kc)], epoch=epoch_no, L=[str(x) for x in Lj], intervals=[(str(a), str(b_)) for a, b_ in iv]); break
                            if cur_epoch.t >= 2 ** epoch_no: cur_epoch.retired = 'epoch_length_reached'; events.append(dict(op='epoch_retired', epoch=epoch_no, reason='length 2^e reached'))
        # ---- deterministic test first, then PAC (charged; cadence from the policy). BEFORE any publication test the protected reference is brought to PARITY with the optional
        # half (gamma = 1/2 holds at every publication, not one iteration late: the quantum rounding is bounded by one reference step of 256 assignments)
        if it % max(1, (len(fr.open) * Kc) // 1024) == 0 or not fr.open:
            work_opt.ratops += len(fr.open) * Kc
            ref_quantum(max(0, work_opt.total() - work_ref.total()))
            if ref.done:
                r = ref.result(); check('reference completion')
                if r['kind'] == 'ZERO_EVIDENCE': return dict(outcome='PROVED_ZERO_EVIDENCE', guarantee_type='DETERMINISTIC', zero_proof=dict(kind='reference_enumeration', assignments=r['assignments']), certificate=_cert(task, arm, mode, trace, C, compile_log, fr, ratio, epochs, events, ref, work_ref, work_opt, None, None, t0, zero=dict(kind='reference')), stats=_stats(work_ref, work_opt, fr, ratio, t0))
                if normalizer: z = F(r['Z']); pub = dict(route='normalizer_exact_reference', bounds=[(z, z)], point=[z], guarantee='DETERMINISTIC', exact=True, reference=r); break
                pub = dict(route='exact_reference', bounds=[(F(a), F(a)) if a != 'UNDEFINED' else ('UNDEFINED', 'UNDEFINED') for a in r['answers']], point=[F(a) if a != 'UNDEFINED' else 'UNDEFINED' for a in r['answers']], guarantee='DETERMINISTIC', exact=True, reference=r); break
            try_publish('loop')
        if not fr.open and pub is None:
            # frontier fully closed: exact compiled answers
            if normalizer:
                z = fr.resolved_mass / fr.scale_den * known_scale(); pub = dict(route='normalizer_exact_frontier_closure', bounds=[(z, z)], point=[z], guarantee='DETERMINISTIC', exact=True, scale=str(known_scale())) if z > 0 else None
            else:
                b = query_bounds_original(); pub = dict(route='exact_frontier_closure', bounds=b, point=[x[0] for x in b], guarantee='DETERMINISTIC', exact=True) if positive_mass() else None
            if pub is None:
                return dict(outcome='PROVED_ZERO_EVIDENCE', guarantee_type='DETERMINISTIC', zero_proof=dict(kind='frontier_closed_zero_mass'), certificate=_cert(task, arm, mode, trace, C, compile_log, fr, ratio, epochs, events, ref, work_ref, work_opt, None, None, t0, zero=dict(kind='frontier')), stats=_stats(work_ref, work_opt, fr, ratio, t0))
        if work_opt.total() - w0 == 0: work_opt.cells += 1       # a no-work optional turn still yields its service (bounded)
        last_opt = work_opt.total() - w0
    check('publication')
    if pub is None: raise Stop('DEADLINE', dict(where='loop end'))
    cert = _cert(task, arm, mode, trace, C, compile_log, fr, ratio, epochs, events, ref, work_ref, work_opt, pub, disabled, t0)
    return dict(outcome='PUBLISHED', guarantee_type=pub['guarantee'], publication=pub, certificate=cert, stats=_stats(work_ref, work_opt, fr, ratio, t0), bias=[str(b) for b in C.bias])


def _stats(wr, wo, fr, ratio, t0):
    return dict(total_s=time.monotonic() - t0, work_reference=wr.snapshot(), work_optional=wo.snapshot(), reference_share=str(F(wr.total(), max(1, wr.total() + wo.total()))),
                frontier=(dict(open=len(fr.open), resolved=fr.resolved_cells, splits=fr.splits, closures=fr.closures) if fr is not None else None), ratio_draws=(ratio.t if ratio is not None else 0))


def _cert(task, arm, mode, trace, C, log, fr, ratio, epochs, events, ref, wr, wo, pub, disabled, t0, zero=None):
    snap = C.snapshot_json() if C is not None else None
    cert = dict(certificate_version='cqr-certificate-v1', arm=arm, mode=mode, diagnostic=trace.get('diagnostic'), epsilon=str(task['epsilon']), delta=str(task['delta']), task_identity=task_identity(task), solver_version=SOLVER_VERSION, policy=POLICY,
                enabled_operators=sorted(ARMS[arm]['enabled']), signed_stream=ARMS[arm]['signed_stream'], query_directed_refinement=ARMS[arm]['query_directed_refinement'],
                compile=dict(log=log, certificates=C.certs if C is not None else None, final=snap, final_sha256=hashlib.sha256(json.dumps(snap, sort_keys=True, default=str).encode()).hexdigest() if snap is not None else None) if C is not None else None,
                frontier=fr.record() if fr is not None else None, events=events, ratio_stream=ratio.record() if ratio is not None else None, epochs=[e.record() for e in (epochs or [])],
                reference=dict(progress=ref.progress(), done=ref.done, assignments_total=ref.total, result=ref.result() if ref.done else None),
                publication=(dict(pub, bounds=[(str(a), str(b)) if a != 'UNDEFINED' else ('UNDEFINED', 'UNDEFINED') for a, b in pub['bounds']], point=[str(x) for x in pub['point']], det_bounds=[(str(a), str(b)) if a != 'UNDEFINED' else ('UNDEFINED', 'UNDEFINED') for a, b in pub['det_bounds']] if pub.get('det_bounds') else None, compiled_bounds=[(str(a), str(b)) if a != 'UNDEFINED' else ('UNDEFINED', 'UNDEFINED') for a, b in pub['compiled_bounds']] if pub.get('compiled_bounds') else None) if pub else None),
                statistical_claims_disabled=disabled, zero=zero, work=dict(reference=wr.snapshot(), optional=wo.snapshot()), bias=[str(b) for b in C.bias] if C is not None else None,
                chain='original task (binding) -> compiler chain (each step verified by its own certificate on the pre-step model; deterministic replay reproduces final_sha256) -> frontier events (partition replayed; every closed cell re-enumerated; every draw recomputed from its recorded law and point) -> streams (statistics and outward boundary recomputed) -> publication (feasibility, tau = eps - bias - rounding, positive mass / denominators) -> original queries are the compiled queries carried through the chain')
    return cert
