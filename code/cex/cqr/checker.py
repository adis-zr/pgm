"""INDEPENDENT END-TO-END CHECKER of a CQR worker output (the gate's validator for the CQR arms). Trust boundary: the ORIGINAL task bytes (shared reader), the worker JSON.
It RE-DERIVES, never trusts:
  1. task binding (sha256 of model / .evid / .query.json; task identity); mode / epsilon / delta against the manifest task; arm's recorded operator set == registry arm;
  2. the compiler chain: starting from the evidence-restricted original task it REPLAYS every recorded certificate step with the independent verifiers (quotient
     proportionality by cross-multiplication + kappa / S; affine local equations re-derived; symmetry action re-verified; influence / concentration / approximate-quotient
     bias re-derived from the recorded operands) and reproduces the final compiled model byte-for-byte (final_sha256);
  3. the frontier: replays every split / close / carve / prune event from the root on the compiled model; every closed cell is re-enumerated exactly; resolved totals match;
  4. every recorded draw: the launch law (cell cap E_C, N_C, U or E) is recomputed from the replayed frontier AT THAT TIME, the drawn point's weight and query values are
     re-evaluated, the statistic recomputed; the final H / G / V of each stream and the outward boundary are recomputed; the risk allocation is checked;
  5. publication: deterministic bounds re-derived from the final frontier (roots), positive mass / denominators, feasibility (tau = eps - bias - rounding), the
     published point inside the bounds, the legacy rows (if present) equal the per-query answers, outward decimals contain the exact point;
  6. EXACT publications: the reference result re-enumerated by the independent oracle when the free space is <= 2^22 assignments (else UNVERIFIABLE_REFERENCE_SIZE);
  7. zero proofs re-derived (compiler proof replayed; frontier closed with zero mass; reference enumeration re-run under the cap).
Returns a list of failure strings (empty = accepted). Deadline-aware (UNVERIFIABLE when the allowance expires)."""
import os, sys, json, time, hashlib, random
from fractions import Fraction as F
import sys as _sys; _sys.set_int_max_str_digits(0)
from itertools import product
from math import prod
HERE = os.path.dirname(os.path.abspath(__file__)); NEWARM = os.path.join(os.path.dirname(HERE), 'newarm')
for p in (HERE, NEWARM):
    if p not in sys.path: sys.path.insert(0, p)
import task as TK, compiler as CP, frontier as FR, numerics as NM, oracle as OR, solve as SV
from views import View
from task import Work

CHECKER_VERSION = 'cqr-checker-v1 (2026-11-16)'
ORACLE_CAP = 1 << 22


class Unverifiable(Exception): pass


def _F(x): return x if isinstance(x, F) else F(str(x))


EXACT_ROUTES = ('exact_reference', 'exact_frontier_closure', 'exact_zero_dimensional', 'normalizer_exact_reference', 'normalizer_exact_frontier_closure', 'normalizer_exact_zero_dimensional')
DET_ROUTES = ('deterministic_frontier', 'deterministic_frontier_closure', 'deterministic_zero_dimensional', 'deterministic_concentration', 'deterministic_signed_residual_E_zero', 'normalizer_deterministic_frontier')
PAC_ROUTES = ('pac_ratio_intersected_with_deterministic', 'pac_signed_residual_validation', 'normalizer_pac_ratio_intersected_with_deterministic')


def guarantee_class_of_route(route):
    """the proof class a route can establish (review CQR-04): exact routes and deterministic routes => DETERMINISTIC (exact routes additionally exact); statistical routes => PAC"""
    if route in EXACT_ROUTES: return 'DETERMINISTIC', True
    if route in DET_ROUTES: return 'DETERMINISTIC', False
    if route in PAC_ROUTES: return 'PAC', False
    return None, False


def mode_permits(mode, route):
    cls, exact = guarantee_class_of_route(route)
    if cls is None: return False
    if mode == 'EXACT_RATIONAL': return exact
    if mode == 'DETERMINISTIC_EPS': return cls == 'DETERMINISTIC'
    return True


def check_worker_output(model_path, w, manifest_task=None, arm=None, deadline=None):
    """main entry; returns (failures, info). The AUTHORITATIVE task is the input file (+ optional query spec) and, when given, the manifest's frozen declaration; the worker's
    own mode / epsilon / delta / guarantee labels are checked AGAINST it, never used to define it (review CQR-04)."""
    fails = []; info = {}; work = Work()
    def fail(m): fails.append(m)
    def late(): return deadline is not None and time.monotonic() >= deadline
    # ---------------- 1. binding and requested semantics
    try: task = TK.load_task(model_path)
    except Exception as ex: return ['task not readable: %s' % str(ex)[:80]], info
    if manifest_task:
        for k in ('epsilon', 'delta'):
            if k in manifest_task and str(manifest_task[k]) != str(task[k]): fail('the frozen manifest task %s (%s) differs from the input file (%s)' % (k, manifest_task[k], task[k]))
        if manifest_task.get('mode') and manifest_task['mode'] != task['mode']: fail('the frozen manifest task mode %s differs from the input file mode %s' % (manifest_task['mode'], task['mode']))
        if 'normalizer_task' in manifest_task and bool(manifest_task['normalizer_task']) != bool((task.get('query_spec') or {}).get('normalizer_task')): fail('the frozen manifest normalizer flag differs from the input file')
    if w.get('binding') != task['binding']: fail('worker binding differs from the files on disk')
    if w.get('task_identity') != TK.task_identity(task): fail('task identity differs from the re-derived identity')
    cert = w.get('certificate') or {}
    if cert.get('certificate_version') != 'cqr-certificate-v1': fail('unknown certificate version %s' % cert.get('certificate_version')); return fails, info
    if cert.get('diagnostic'): fail('a DIAGNOSTIC run (%s) is never a production publication' % cert.get('diagnostic')); return fails, info
    if cert.get('fault_injected') or w.get('fault_injected'): fail('a FAULT-INJECTION run (%s) is never a production publication' % (cert.get('fault_injected') or w.get('fault_injected'))); return fails, info
    mode = task['mode']; eps = task['epsilon']; delta = task['delta']; normalizer = bool((task.get('query_spec') or {}).get('normalizer_task'))
    if w.get('mode') != mode: fail('worker mode %s differs from the authoritative task mode %s' % (w.get('mode'), mode))
    if cert.get('mode') != mode: fail('certificate mode %s differs from the authoritative task mode %s' % (cert.get('mode'), mode))
    if str(cert.get('epsilon')) != str(eps) or str(w.get('epsilon')) != str(eps): fail('epsilon differs from the authoritative task')
    if str(cert.get('delta')) != str(delta) or str(w.get('delta')) != str(delta): fail('delta differs from the authoritative task')
    if bool(cert.get('normalizer_task')) != normalizer: fail('certificate normalizer flag differs from the task')
    if arm is not None:
        if cert.get('arm') != arm or w.get('arm') != arm: fail('arm differs from the planned arm')
        spec = SV.ARMS.get(arm)
        if spec is None: fail('unknown arm'); return fails, info
        eff = CP.effective_operators(spec['enabled'], task)
        if sorted(cert.get('arm_operators') or []) != sorted(spec['enabled']): fail('recorded arm operator set differs from the registered arm')
        if sorted(cert.get('enabled_operators') or []) != sorted(eff): fail('recorded task-effective operator set differs from the registered arm policy for this task')
        if bool(cert.get('signed_stream')) != (spec['signed_stream'] and not normalizer) or bool(cert.get('query_directed_refinement')) != (spec['query_directed_refinement'] and not normalizer): fail('recorded stream flags differ from the registered arm policy for this task')
    enabled_eff = set(cert.get('enabled_operators') or [])
    # ---------------- zero proofs
    if w.get('outcome') == 'PROVED_ZERO_EVIDENCE':
        if w.get('guarantee_type') != 'DETERMINISTIC': fail('zero-evidence proof must carry the DETERMINISTIC class')
        zp = w.get('zero_evidence_proof') or {}
        if zp.get('kind') == 'compiler':
            try: CP.compile_task(task, enabled=enabled_eff, work=work); fail('compiler zero proof does not re-derive (compile succeeded)')
            except CP.ZeroEvidence as z:
                if z.proof.get('kind') != (zp.get('proof') or {}).get('kind'): fail('compiler zero proof kind differs (%s vs %s)' % (z.proof.get('kind'), (zp.get('proof') or {}).get('kind')))
        elif zp.get('kind') in ('reference_enumeration', 'frontier_closed_zero_mass'):
            tr = OR.enumerate_truth(task['model'], task['queries'], deadline=deadline, max_assignments=ORACLE_CAP)
            if tr is None: fail('UNVERIFIABLE: zero proof by enumeration exceeds the checker cap / allowance')
            elif tr['Z'] != 0: fail('zero-evidence claim contradicted by the independent enumerator (Z = %s)' % tr['Z'])
        else: fail('unknown zero proof kind %s' % zp.get('kind'))
        if w.get('answers') is not None or w.get('intervals') is not None: fail('zero-evidence output carries published answers')
        return fails, info
    if w.get('outcome') != 'PUBLISHED': return fails, info
    pub = cert.get('publication') or {}; route = pub.get('route'); K = len(task['queries'])
    # ---------------- guarantee class is DERIVED from the route and bound to every label (review CQR-04)
    cls, exact_route = guarantee_class_of_route(route)
    if cls is None: fail('unknown publication route %s' % route); return fails, info
    if not mode_permits(mode, route): fail('route %s is not permitted by the task mode %s (EXACT_RATIONAL needs an exact route; DETERMINISTIC_EPS may not consume a statistical proof)' % (route, mode))
    if pub.get('guarantee') != cls: fail('publication guarantee %s differs from the class %s of route %s' % (pub.get('guarantee'), cls, route))
    if w.get('guarantee_type') != cls: fail('worker guarantee_type %s differs from the class %s established by route %s' % (w.get('guarantee_type'), cls, route))
    if bool(pub.get('exact')) != exact_route: fail('exact flag %s disagrees with route %s' % (pub.get('exact'), route))
    # ---------------- 2. compiler chain replay (optional work; None when the compile was cancelled and the reference alone published)
    comp = cert.get('compile'); C = None
    if comp is not None:
        try: C, log = CP.compile_task(task, enabled=enabled_eff, work=work)
        except CP.ZeroEvidence as z: fail('replayed compile proves ZERO_EVIDENCE but the worker published'); return fails, info
        if (comp.get('log') or {}).get('interrupted') or (comp.get('log') or {}).get('failed'):
            # the worker's compile was interrupted (deadline / reference_done / cancelled) or an operator FAILED and was rolled back: replay the SAME committed prefix by stopping
            # at the same operator (the failed operator contributed nothing: the step is transactional)
            C = _replay_interrupted(task, enabled_eff, comp, work)
            if C is None: fail('interrupted / failed compile prefix does not replay'); return fails, info
        snap = C.snapshot_json(); sha_ = hashlib.sha256(json.dumps(snap, sort_keys=True, default=str).encode()).hexdigest()
        if sha_ != comp.get('final_sha256'): fail('compiled model does not replay (final_sha256 %s vs %s)' % (sha_[:12], str(comp.get('final_sha256'))[:12])); return fails, info
        rec_certs = comp.get('certificates') or []
        if [c.get('op') for c in rec_certs] != [c.get('op') for c in C.certs]: fail('recorded certificate chain differs from the replayed chain')
        vf, derived = _verify_chain(task, enabled_eff, rec_certs, work, deadline)
        fails += vf
        bias = [_F(b) for b in (cert.get('bias') or [])]
        if bias != C.bias: fail('recorded bias ledger differs from the replayed one')
        if mode == 'EXACT_RATIONAL' and any(b != 0 for b in bias): fail('EXACT_RATIONAL publication with nonzero compiler bias')
        if any(b > eps / 4 for b in bias): fail('compiler bias exceeds the reserve eps/4')
    else:
        derived = {}; rec_certs = []
        if route not in ('exact_reference', 'normalizer_exact_reference'): fail('publication without a compile record on a non-reference route'); return fails, info
        # honest absence: the protected reference finished before ANY optional work was spent (no compile transaction opened), or optional work was cancelled
        wo_tot = ((cert.get('work') or {}).get('optional') or {}).get('total')
        if not cert.get('optional_cancelled') and not (wo_tot == 0 and ((cert.get('reference') or {}).get('done') is True)): fail('compile record absent without a recorded optional cancellation or a reference-first completion with zero optional work')
    if fails: return fails, info
    if late(): fail('UNVERIFIABLE: allowance expired after the compiler replay'); return fails, info
    # ---------------- 3. the PROVEN enclosure of the ORIGINAL answers, per route (compiled units widened by the proved bias)
    if normalizer:
        proven, info_n = _normalizer_enclosure(task, C, cert, pub, route, eps, delta, deadline, work, fail)
        if fails: return fails, info
        _validate_publication(task, w, pub, route, cls, exact_route, proven, mode, eps, fail, normalizer=True)
        info['route'] = route; info['work'] = work.snapshot(); return fails, info
    cq = C.queries if C is not None else None
    proven = None
    if route == 'exact_reference':
        tr = OR.enumerate_truth(task['model'], task['queries'], deadline=deadline, max_assignments=ORACLE_CAP)
        if tr is None: fail('UNVERIFIABLE_REFERENCE_SIZE: the exact reference publication exceeds the checker cap / allowance (not shown wrong)'); return fails, info
        proven = [('UNDEFINED' if a == 'UNDEFINED' else (a, a)) for a in tr['answers']]
    else:
        bias = C.bias
        def widen(x, j): return (max(F(0), x[0] - bias[j]), min(F(1), x[1] + bias[j]))
        if not C.cards:
            # zero-dimensional compiled model: every compiled query view has empty scope
            if route not in ('exact_zero_dimensional', 'deterministic_zero_dimensional', 'deterministic_concentration'): fail('route %s on a zero-dimensional compiled model' % route); return fails, info
            if route == 'exact_zero_dimensional' and any(b != 0 for b in bias): fail('exact zero-dimensional route with nonzero bias'); return fails, info
            proven = []
            for j, q in enumerate(cq):
                if q['kind'] == 'expectation': v = q['f'].values[0]; proven.append(widen((v, v), j))
                else: g = q['g'].values[0]; proven.append('UNDEFINED' if g == 0 else widen((q['h'].values[0] / g,) * 2, j))
        else:
            fr, state = _replay_frontier(task, C, cert, delta, work, deadline, fail)
            if fails: return fails, info
            if fr is None: fail('frontier replay unavailable'); return fails, info
            K_ = len(cq); det = fr.deterministic_bounds()
            for j in range(K_):
                if j in C.constant_queries: det[j] = (C.constant_queries[j], C.constant_queries[j])
            positive = fr.resolved_mass > 0 or any(c.L > 0 for c in fr.open.values()) or (C.witness is not None)
            if not positive: fail('publication without a proved positive mass')
            Lj = [(fr.Zlo() if q['kind'] == 'expectation' else fr.resolved_den[j] + sum(c.L * c.qlo[j][1] for c in fr.open.values())) for j, q in enumerate(cq)]
            undefined = [q['kind'] == 'ratio' and fr.resolved_den[j] == 0 and all(c.B * c.qhi[j][1] == 0 for c in fr.open.values()) for j, q in enumerate(cq)]
            tau = [eps - bias[j] - SV.MARGIN for j in range(K_)]
            closed = not fr.open
            if route in ('exact_frontier_closure', 'deterministic_frontier_closure'):
                if not closed: fail('closure route with open cells'); return fails, info
                if route == 'exact_frontier_closure' and any(b != 0 for b in bias): fail('exact closure claimed with nonzero compiler bias (a surrogate is not the original task)'); return fails, info
                proven = []
                for j, q in enumerate(cq):
                    if undefined[j]: proven.append('UNDEFINED'); continue
                    if q['kind'] == 'expectation': v = fr.resolved_num[j] / fr.resolved_mass
                    else: v = fr.resolved_num[j] / fr.resolved_den[j]
                    proven.append(widen((v, v), j))
            elif route in ('deterministic_frontier', 'deterministic_zero_dimensional'):
                proven = [('UNDEFINED' if undefined[j] else widen(det[j], j)) for j in range(K_)]
                for j, q in enumerate(cq):
                    if q['kind'] == 'ratio' and not undefined[j] and Lj[j] <= 0: fail('ratio query %d published without a positive denominator bound' % j)
            elif route == 'deterministic_concentration':
                ca = derived.get('concentration_answers')
                if ca is None: fail('concentration route without an independently re-derived concentration certificate'); return fails, info
                proven = [widen((ca[j], ca[j]), j) for j in range(K_)]
            elif route == 'deterministic_signed_residual_E_zero':
                e = pub.get('epoch'); st = state['epochs'].get(e)
                if st is None: fail('E=0 route without its epoch'); return fails, info
                cells, E = fr.signed_law(st['cand'])
                if E != 0: fail('E = 0 claimed but the replayed envelope is %s' % E)
                proven = []
                for j in range(K_):
                    d = fr.resolved_num[j] - st['cand'][j] * (fr.resolved_mass if cq[j]['kind'] == 'expectation' else fr.resolved_den[j])
                    if Lj[j] <= 0 or abs(d) > tau[j] * Lj[j]: fail('E = 0 residual of query %d does not certify' % j)
                    proven.append(widen((st['cand'][j] - tau[j], st['cand'][j] + tau[j]), j))
                    if _F(pub['point'][j]) != st['cand'][j]: fail('published point differs from the epoch candidate')
            elif route == 'pac_ratio_intersected_with_deterministic':
                rs = state['ratio']
                if rs is None or rs['H'] <= 0: fail('PAC ratio publication without observations'); return fails, info
                B = NM.boundary_upper(rs['U_star'] * rs['U_star'] / 4, rs['V'], delta / 2 / K_); proven = []
                for j in range(K_):
                    if undefined[j]: proven.append('UNDEFINED'); continue
                    if rs['Hj'][j] <= 0: fail('query %d has no denominator statistic' % j); proven.append((F(0), F(1))); continue
                    c = rs['G'][j] / rs['Hj'][j]; r = B / rs['Hj'][j]; lo = max(det[j][0], max(F(0), c - r)); hi = min(det[j][1], min(F(1), c + r))
                    if lo > hi: fail('empty intersection for query %d' % j); proven.append((F(0), F(1))); continue
                    if cq[j]['kind'] == 'ratio' and Lj[j] <= 0: fail('ratio query %d published without a positive denominator bound' % j)
                    proven.append(widen((lo, hi), j))
            elif route == 'pac_signed_residual_validation':
                e = pub.get('epoch'); st = state['epochs'].get(e)
                if st is None or st['H'] <= 0: fail('signed validation without observations'); return fails, info
                B = NM.boundary_upper(st['E_star'] ** 2, st['V'], st['alpha']); proven = []
                for j in range(K_):
                    lo = (st['G'][j] - B) / st['H']; hi = (st['G'][j] + B) / st['H']
                    if Lj[j] <= 0 or lo < -tau[j] * Lj[j] or hi > tau[j] * Lj[j]: fail('signed validation interval of query %d does not fit [-tau L, tau L]' % j)
                    if _F(pub['point'][j]) != st['cand'][j]: fail('published point differs from the validated candidate')
                    proven.append(widen((st['cand'][j] - tau[j], st['cand'][j] + tau[j]), j))
            else: fail('route %s is not valid for a frontier publication' % route); return fails, info
    if fails: return fails, info
    # ---------------- 4. ONE final validator for every route and every emitted representation (review CQR-01 / 03 / 05)
    _validate_publication(task, w, pub, route, cls, exact_route, proven, mode, eps, fail)
    info['route'] = route; info['work'] = work.snapshot(); info['exact'] = exact_route
    return fails, info


def _validate_publication(task, w, pub, route, cls, exact_route, proven, mode, eps, fail, normalizer=False):
    """the common contract (review item 1): shape / query identity; typed definedness per coordinate; the independently PROVEN enclosure of the original answer lies INSIDE
    the published bounds; the point lies inside the published bounds and within eps - margin of both ends (so every value in the published bounds is within eps of the point);
    exact routes publish zero-width bounds equal to the proven value; EXACT_RATIONAL mode admits only exact coordinates; singleton families sum to one; `answers` agrees
    with the certificate coordinate by coordinate; the legacy rows (when the task is the all-singleton contract) contain the exact bounds and their points agree within
    the rounding margin and form simplex rows; an unexpected legacy representation is refused."""
    K = 1 if normalizer else len(task['queries']); bounds = pub.get('bounds') or []; point = pub.get('point') or []
    if len(bounds) != K or len(point) != K: fail('publication shape differs from the task (%d bounds / %d points for %d queries)' % (len(bounds), len(point), K)); return
    tau_pub = eps - SV.MARGIN
    for j in range(K):
        pr = proven[j]; b = bounds[j]; pt = point[j]
        if pr == 'UNDEFINED':
            if not (isinstance(b, (list, tuple)) and b[0] == 'UNDEFINED' and b[1] == 'UNDEFINED' and pt == 'UNDEFINED'): fail('query %d is PROVED undefined but a value was published' % j)
            continue
        if b[0] == 'UNDEFINED' or pt == 'UNDEFINED': fail('query %d is defined but published as UNDEFINED' % j); continue
        lo, hi = _F(b[0]), _F(b[1]); p = _F(pt)
        if lo > hi: fail('query %d: inverted published bounds' % j); continue
        if normalizer:
            if not (lo <= pr[0] and pr[1] <= hi): fail('published Z bounds do not contain the re-derived enclosure [%s, %s]' % (pr[0], pr[1]))
            if lo <= 0: fail('Z lower bound not positive')
            if not ((1 - eps) * hi <= p <= (1 + eps) * lo): fail('Z point outside [(1-eps) U, (1+eps) L] of the PUBLISHED bounds (relative error not certified)')
            if exact_route and not (lo == hi == p == pr[0] == pr[1]): fail('exact normalizer route with a non-exact publication')
            continue
        if not (lo <= pr[0] and pr[1] <= hi): fail('published bounds of query %d do not contain the re-derived enclosure [%s, %s]' % (j, pr[0], pr[1]))
        if not (lo <= p <= hi): fail('point of query %d outside its published bounds' % j)
        if not (hi - tau_pub <= p <= lo + tau_pub): fail('point of query %d is not within eps of every value in its published bounds' % j)
        if exact_route or mode == 'EXACT_RATIONAL':
            if not (lo == hi == p == pr[0] == pr[1]): fail('exact publication of query %d is not the zero-width proven value' % j)
    if normalizer:
        ans = w.get('answers')
        if not (isinstance(ans, list) and len(ans) == 1 and ans[0].get('lo') == str(bounds[0][0]) and ans[0].get('hi') == str(bounds[0][1]) and ans[0].get('point') == str(point[0])): fail('normalizer answer does not agree with the certificate publication')
        if w.get('intervals') is not None or w.get('points') is not None: fail('legacy rows emitted for a normalizer task')
        return
    # simplex rows of singleton families
    for g in SV._singleton_groups(task):
        if any(proven[j] == 'UNDEFINED' for j in g): fail('singleton family contains an undefined coordinate'); continue
        if sum(_F(point[j]) for j in g) != 1: fail('singleton family does not sum to one')
    # answers <-> certificate
    ans = w.get('answers')
    if not isinstance(ans, list) or len(ans) != K: fail('answers shape differs from the task'); return
    for j, a in enumerate(ans):
        if a.get('query') != task['queries'][j].name: fail('answer %d names query %s, not %s' % (j, a.get('query'), task['queries'][j].name))
        if proven[j] == 'UNDEFINED':
            if a.get('status') != 'UNDEFINED': fail('answer %d status %s for a proved-undefined coordinate' % (j, a.get('status')))
        elif a.get('status') != 'OK' or a.get('lo') != str(bounds[j][0]) or a.get('hi') != str(bounds[j][1]) or a.get('point') != str(point[j]): fail('answer %d does not agree with the certificate publication' % j)
    # legacy rows
    iv = w.get('intervals'); pts = w.get('points'); cards = task['model']['cards']
    if task.get('all_singletons') and all(pr != 'UNDEFINED' for pr in proven):
        if iv is None or pts is None: fail('all-singleton task without legacy rows'); return
        if len(iv) != len(cards) or len(pts) != len(cards) or any(len(row) != k or len(pr) != k for row, pr, k in zip(iv, pts, cards)): fail('legacy rows shape differs from the original model'); return
        try:
            IV = [[(F(a), F(b)) for a, b in row] for row in iv]; PT = [[F(x) for x in row] for row in pts]
            import core; core.verify_output(IV, PT, eps)
        except Exception as ex: fail('legacy rows violate the publication contract: %s' % str(ex)[:60]); return
        for j, q in enumerate(task['queries']):
            o = q.output or {}; lo, hi = IV[o['variable']][o['state']]; p = PT[o['variable']][o['state']]
            if not (lo <= _F(bounds[j][0]) and _F(bounds[j][1]) <= hi): fail('legacy row of query %d does not contain the certified bounds' % j)
            if not (lo <= proven[j][0] and proven[j][1] <= hi): fail('legacy row of query %d does not contain the re-derived enclosure' % j)
            if abs(p - _F(point[j])) > SV.MARGIN: fail('legacy point of query %d differs from the certified point beyond the rounding margin' % j)
            if not (lo <= p <= hi): fail('legacy point of query %d outside its legacy row' % j)
    elif iv is not None or pts is not None: fail('legacy rows emitted for a task that is not the all-singleton contract (or has undefined coordinates)')


def _replay_interrupted(task, enabled_eff, comp, work):
    """replay a compile that the worker interrupted (deadline / reference_done / memory): the SAME operator sequence is run and stopped after the recorded interrupted operator's
    committed prefix is unavailable in general, so the replay re-runs the operators that COMMITTED (recorded steps) and refuses if the interrupted operator committed anything"""
    log = comp.get('log') or {}; steps = log.get('steps') or []; done_ops = [st['op'] for st in steps if st.get('committed')]
    inter = log.get('interrupted') or log.get('failed') or {}
    if any(st.get('op') == inter.get('op') and st.get('committed') for st in steps): return None
    # re-run with a service hook that raises at the recorded operator (an interrupted operator is stopped at its first tick; a failed one was rolled back, so stopping there is equivalent)
    stop_at = inter.get('op'); kind = inter.get('kind', 'deadline') if 'kind' in inter else 'deadline'
    def svc(op):
        if op == stop_at: raise CP.CompileStop(kind, op)
    try: C, _ = CP.compile_task(task, enabled=enabled_eff, work=work, service=svc)
    except CP.ZeroEvidence: return None
    return C


def _replay_frontier(task, C, cert, delta, work, deadline, fail):
    """replay every recorded frontier / stream event on the replayed compiled model; returns (frontier, state) with the recomputed stream statistics; fails on any divergence"""
    cq = C.queries; K = len(cq); fr_rec = cert.get('frontier'); events = cert.get('events') or []
    fr = FR.Frontier(C.cards, C.views, cq, work, order=fr_rec.get('order') if fr_rec else None)
    ratio_rec = cert.get('ratio_stream'); epochs = cert.get('epochs') or []
    H = F(0); Hj = [F(0)] * K; G = [F(0)] * K; V = F(0); t_r = 0; U_star = _F(ratio_rec['U_star']) if ratio_rec else None
    ep_state = {}
    for ev in events:
        if deadline is not None and time.monotonic() >= deadline: fail('UNVERIFIABLE: allowance expired during the frontier replay'); return None, None
        op = ev.get('op')
        try:
            if op == 'split':
                kids = fr.split(ev['cell'])
                if kids != ev.get('children'): fail('split children differ at cell %s' % ev['cell']); return None, None
            elif op == 'close': fr.close(ev['cell'])
            elif op == 'carve': fr.carve_point(ev['cell'], {int(k): v for k, v in ev['x'].items()})
            elif op == 'ratio_draw':
                cells, U = fr.ratio_law(); c = fr.open.get(ev['cell'])
                if c is None or _F(ev['U']) != U: fail('ratio draw %d: launch law differs (U %s vs %s)' % (t_r + 1, ev['U'], U)); return None, None
                x = {int(k): v for k, v in ev['x'].items()}
                if any(x.get(k) != v for k, v in c.assign.items()) or any(k not in x or not (0 <= x[k] < fr.cards[k]) for k in range(len(fr.cards))): fail('ratio draw point outside its cell'); return None, None
                if _F(ev['A']) != fr.resolved_mass or [_F(v) for v in ev['a']] != fr.resolved_num or [_F(v) for v in ev['d']] != fr.resolved_den: fail('ratio draw %d: pre-trial resolved offsets differ (record-before-resolve violated)' % (t_r + 1)); return None, None
                wgt, fq = fr.weight_and_queries(x); q = c.E / U / c.N; W = wgt / q
                if W > U: fail('importance weight exceeds the cap at draw %d' % (t_r + 1)); return None, None
                b = FR.dyadic_weight((U_star / U) ** 2); t_r += 1; H += b * (fr.resolved_mass + W)
                for j in range(K):
                    fj, gj = fq[j]; G[j] += b * (fr.resolved_num[j] + W * fj); Hj[j] += b * ((fr.resolved_mass + W) if cq[j]['kind'] == 'expectation' else (fr.resolved_den[j] + W * gj))
                V += b * b * U * U / 4
            elif op == 'epoch_start':
                e = ev['epoch']; de = delta / (2 * e * (e + 1))
                if _F(ev['delta_e']) != de: fail('epoch %d risk differs from delta/(2e(e+1))' % e); return None, None
                cand = [_F(c_) for c_ in ev['candidate']]; cells, E0 = fr.signed_law(cand, key=('epoch', e))
                if _F(ev['E_star']) != (E0 if E0 > 0 else F(1)): fail('epoch %d E_star differs from the launch envelope' % e); return None, None
                ep_state[e] = dict(cand=cand, H=F(0), G=[F(0)] * K, V=F(0), t=0, E_star=_F(ev['E_star']), alpha=de / max(1, K))
            elif op == 'signed_draw':
                st = ep_state.get(ev['epoch'])
                if st is None: fail('signed draw before its epoch start'); return None, None
                cells, E = fr.signed_law(st['cand'], key=('epoch', ev['epoch'])); c = fr.open.get(ev['cell'])
                if c is None or _F(ev['E']) != E: fail('signed draw: launch envelope differs (E %s vs %s)' % (ev['E'], E)); return None, None
                a_c = next((a for cc, a in cells if cc.id == c.id), None)
                if a_c is None or _F(ev['p']) != a_c / E: fail('signed draw: cell probability differs'); return None, None
                rn = fr.resolved_num; rd_ = fr.resolved_den; rm = fr.resolved_mass; d = [rn[j] - st['cand'][j] * (rm if cq[j]['kind'] == 'expectation' else rd_[j]) for j in range(K)]
                if [_F(v) for v in ev['d']] != d: fail('signed draw: pre-trial offsets differ'); return None, None
                x = {int(k): v for k, v in ev['x'].items()}
                if any(x.get(k) != v for k, v in c.assign.items()) or any(k not in x or not (0 <= x[k] < fr.cards[k]) for k in range(len(fr.cards))): fail('signed draw point outside its cell'); return None, None
                wgt, fq = fr.weight_and_queries(x); b = FR.dyadic_weight((st['E_star'] / E) ** 2); st['t'] += 1; st['H'] += b
                for j in range(K):
                    fj, gj = fq[j]; R = wgt * (fj - st['cand'][j] * gj) / (a_c / E / c.N)
                    if abs(R) > E: fail('signed contribution exceeds E'); return None, None
                    st['G'][j] += b * (d[j] + R)
                st['V'] += b * b * E * E
            elif op in ('epoch_E_zero', 'epoch_retired', 'ratio_stream_stopped', 'prune_zero', 'optional_cancelled', 'optional_operator_failed'): pass      # informational: the compile replay / rollback is verified separately
            else: fail('unknown event %s' % op); return None, None
        except AssertionError as ax: fail('frontier replay assertion: %s' % str(ax)[:80]); return None, None
    if fr_rec is not None:
        if fr.resolved_mass != _F(fr_rec['resolved_mass']) or [str(x) for x in fr.resolved_num] != fr_rec['resolved_num'] or len(fr.open) != fr_rec['open_cells']: fail('replayed frontier totals differ from the recorded frontier')
    ratio = None
    if ratio_rec is not None:
        if t_r != ratio_rec['t'] or str(H) != ratio_rec['H'] or [str(x) for x in G] != ratio_rec['G'] or str(V) != ratio_rec['V']: fail('ratio stream statistics do not replay')
        if _F(ratio_rec['alpha']) != delta / 2 / max(1, K) or _F(ratio_rec['rho']) != U_star * U_star / 4: fail('ratio stream risk / rho differ from the policy')
        ratio = dict(H=H, Hj=Hj, G=G, V=V, t=t_r, U_star=U_star, Hb=None)
    for e in epochs:
        st = ep_state.get(e['epoch'])
        if st is None: fail('recorded epoch %s has no start event' % e['epoch']); continue
        if st['t'] != e['t'] or str(st['H']) != e['H'] or [str(x) for x in st['G']] != e['G'] or str(st['V']) != e['V']: fail('epoch %s statistics do not replay' % e['epoch'])
    return fr, dict(ratio=ratio, epochs=ep_state)


def verify_quotient_step_views(cards, views, step, inc_idx, work):
    """independent cross-multiplication check of a recorded quotient step against the given pre-step views (inc_idx = indices of the incident views)"""
    st = dict(step, incident_factors=inc_idx); return CP.verify_quotient_step(cards, views, st, work)


def _verify_chain(task, enabled, rec_certs, work, deadline):
    """replay the compile step by step, verifying each recorded certificate on the PRE-step model with the independent verifiers; returns (fails, derived) where derived
    carries independently RE-DERIVED facts the publication check must use instead of recorded fields (concentration_answers; review CQR-01)"""
    fails = []; derived = {}
    try:
        C = CP.from_task(task, work)
    except CP.ZeroEvidence: return ['chain verification: evidence restriction proves zero'], derived
    # walk the recorded certificates in order, applying the same operators and verifying before each commit
    import copy
    allowance = [(task['epsilon'] / 4 if task['mode'] != 'EXACT_RATIONAL' else F(0))] * len(task['queries']); D = CP.quota_for(task)
    for rc in rec_certs:
        op = rc.get('op')
        if op == 'evidence': continue
        before_cards = list(C.cards); before_views = [View.from_json(v.to_json()) for v in C.views]
        if op == 'support': CP.support_fixpoint(C, C.work.total() + D)
        elif op == 'fixed_substitution': CP.fixed_substitution(C)
        elif op == 'leaf_sumout': CP.leaf_sumout(C, C.work.total() + D)
        elif op == 'component_omission':
            for o in rc.get('omitted', []):
                pr = o.get('proof') or {}
                if pr.get('kind') == 'all_tables_strictly_positive':
                    if not all(all(x > 0 for x in before_views[i].values) for i in o['factors']): fails.append('component omission: positivity proof fails')
                elif pr.get('kind') == 'witness_restricted_positive':
                    x = {int(k): v for k, v in pr['witness'].items()}; wgt = F(1)
                    for i in o['factors']: wgt *= before_views[i].at(before_cards, x)
                    if wgt <= 0: fails.append('component omission: witness has zero weight')
                else: fails.append('component omission: unknown proof kind')
            CP.component_omission(C)
        elif op in ('exact_quotient_pass', 'approx_quotient'):
            # per-step INDEPENDENT verification on the exact pre-step state through the operator hook (the operator stops before each commit)
            rec_steps = list(rc.get('steps', [])); seen = []
            def hook(kind, var, classes_or_groups, sig_or_slices, inc, *rest):
                i = len(seen); seen.append(var)
                if i >= len(rec_steps): fails.append('%s: more steps replayed than recorded' % op); return
                st = rec_steps[i]
                if st['var'] != var: fails.append('%s: step %d variable differs (%s vs %s)' % (op, i, st['var'], var)); return
                cards_now = list(C.cards); views_now = [View.from_json(v.to_json()) for v in C.views]
                if kind == 'exact':
                    m = verify_quotient_step_views(cards_now, views_now, st, [C.views.index(v) for v in inc], work)
                    if m: fails.append('quotient step %d: %s' % (i, m))
                else:
                    groups, slices, R, beta = classes_or_groups, sig_or_slices, rest[0], rest[1]; ap = st.get('approx') or {}
                    R2, _b = CP._surrogate_ratio(C, var, inc, slices, [dict(rep=g[0], states=g) for g in ap.get('groups', [])])
                    if R2 is None or str(R2) != ap.get('R') or str((R2 - 1) / (R2 + 3)) != ap.get('beta') or [g['states'] for g in groups] != ap.get('groups'): fails.append('approximate quotient certificate does not re-derive for var %d (step %d)' % (var, i))
            if op == 'approx_quotient': CP.approx_quotient(C, C.work.total() + D, allowance, hook=hook)
            else: CP.exact_quotient_pass(C, C.work.total() + D, hook=hook)
            if len(seen) != len(rec_steps): fails.append('%s: %d steps replayed, %d recorded' % (op, len(seen), len(rec_steps)))
        elif op == 'symmetry':
            for a in rc.get('actions', []):
                if not CP.verify_symmetry_action(before_cards, before_views, a['action'], work): fails.append('symmetry action does not verify')
            CP.symmetry(C, C.work.total() + D)
        elif op == 'concentration':
            if 'answers' in rc:
                # INDEPENDENTLY re-derive the whole direct certificate on the PRE-step model: x* has positive weight; every pre-step query evaluated at x*; t_i; biases
                xs = {int(k): v for k, v in rc['xstar'].items()}
                if sorted(xs) != list(range(len(before_cards))) or any(not (0 <= xs[v] < before_cards[v]) for v in xs): fails.append('concentration: assignment outside the pre-step domains')
                else:
                    wst = F(1)
                    for v in before_views: wst *= v.at(before_cards, xs)
                    if wst <= 0: fails.append('concentration: the proposed assignment has zero weight on the pre-step model')
                    before_queries = [dict(q, f=View.from_json(q['f'].to_json())) if q['kind'] == 'expectation' else None for q in C.queries]
                    if any(q is None for q in before_queries): fails.append('concentration on a ratio query')
                    else:
                        ca = {}
                        for qi, q in enumerate(before_queries):
                            val = q['f'].at(before_cards, xs); ca[qi] = val
                            if str(val) != str(rc['answers'].get(str(qi))): fails.append('concentration answer of query %d does not re-derive (%s recorded, %s at x*)' % (qi, rc['answers'].get(str(qi)), val))
                        derived['concentration_answers'] = ca; derived['concentration_scopes'] = [tuple(q['f'].scope) for q in before_queries]
                for var in range(len(before_cards)):
                    Ri = F(0); inf = False
                    for s in range(before_cards[var]):
                        if s == xs[var]: continue
                        r = F(1); zb = False
                        for v in before_views:
                            if var not in v.scope: continue
                            sl_s = CP._slice(v, before_cards, var, s); sl_r = CP._slice(v, before_cards, var, xs[var]); bound = F(0); hp = False
                            for a_, b_ in zip(sl_s, sl_r):
                                if a_ == 0: continue
                                hp = True
                                if b_ == 0: bound = None; break
                                bound = max(bound, a_ / b_)
                            if not hp: r = F(0); zb = True; break
                            if bound is None: r = None; break
                            r *= bound
                        if zb: continue
                        if r is None: inf = True; break
                        Ri += r
                    t = F(1) if inf else Ri / (1 + Ri)
                    if str(t) != rc['t'][str(var)]: fails.append('concentration t_%d does not re-derive' % var)
                if 'concentration_scopes' in derived:
                    for qi, sc in enumerate(derived['concentration_scopes']):
                        bj = min(F(1), sum(F(rc['t'][str(u)]) for u in sc)) if sc else F(0)
                        if str(bj) != str((rc.get('bias') or {}).get(str(qi))): fails.append('concentration bias of query %d does not re-derive' % qi)
            CP.concentration(C, C.work.total() + D, allowance)
        elif op == 'influence_deletion':
            if 'deleted' in rc:
                if any(x <= 0 for v in before_views for x in v.values): fails.append('influence deletion on a model with zeros')
                if _F(rc['alpha']) >= 1: fails.append('influence deletion with alpha >= 1')
            CP.influence_deletion(C, C.work.total() + D, allowance)
        elif op == 'affine':
            m = CP.verify_affine_record(before_cards, before_views, rc, work)
            if m: fails.append('affine: ' + m)
            CP.affine(C, C.work.total() + D)
        else: fails.append('unknown certificate op %s' % op)
        if deadline is not None and time.monotonic() >= deadline: fails.append('UNVERIFIABLE: allowance expired in the chain verification'); break
    return fails, derived


def _normalizer_enclosure(task, C, cert, pub, route, eps, delta, deadline, work, fail):
    """the PROVEN enclosure [L, U] of Z in ORIGINAL units (scale_den and the KNOWN scalars); the common validator then requires it INSIDE the published bounds (review CQR-02)"""
    if C is None:
        if route != 'normalizer_exact_reference': fail('normalizer publication without a compile record on a non-reference route'); return None, {}
    else:
        if any(d.get('kind') == 'omitted_component_mass' for d in C.scalars): fail('normalizer task with an omitted component (unknown scalar)'); return None, {}
    if route == 'normalizer_exact_reference':
        tr = OR.enumerate_truth(task['model'], task['queries'], deadline=deadline, max_assignments=ORACLE_CAP)
        if tr is None: fail('UNVERIFIABLE_REFERENCE_SIZE: exact Z publication exceeds the checker cap'); return None, {}
        return [(tr['Z'], tr['Z'])], {}
    sc = F(1)
    for d in C.scalars: sc *= F(d['value'])
    for d in C.constant_scalars: sc *= F(d['value'])
    if str(sc) != str(pub.get('scale', str(sc))): fail('known scalar product differs (%s vs %s)' % (sc, pub.get('scale')))
    if not C.cards:
        if route != 'normalizer_exact_zero_dimensional': fail('zero-dimensional normalizer route %s' % route)
        return [(sc, sc)], {}
    fr, state = _replay_frontier(task, C, cert, delta, work, deadline, fail)
    if fr is None: return None, {}
    if any(e.get('op') in ('epoch_start', 'signed_draw') for e in (cert.get('events') or [])): fail('signed stream events in a normalizer run')
    L = fr.Zlo() / fr.scale_den * sc; Uz = fr.Zhi() / fr.scale_den * sc
    if route == 'normalizer_exact_frontier_closure':
        if fr.open: fail('exact closure with open cells'); return None, {}
        z = fr.resolved_mass / fr.scale_den * sc; return [(z, z)], {}
    if route == 'normalizer_deterministic_frontier': return [(L, Uz)], {}
    if route == 'normalizer_pac_ratio_intersected_with_deterministic':
        rs = state['ratio']
        if rs is None or rs['t'] == 0: fail('ratio stream does not replay'); return None, {}
        Hb = sum(FR.dyadic_weight((rs['U_star'] / _F(ev['U'])) ** 2) for ev in (cert.get('events') or []) if ev.get('op') == 'ratio_draw')
        B = NM.boundary_upper(rs['U_star'] * rs['U_star'] / 4, rs['V'], delta / 2 / max(1, len(C.queries)))
        zl = max(F(0), (rs['H'] - B) / Hb) / fr.scale_den * sc; zu = (rs['H'] + B) / Hb / fr.scale_den * sc; l2 = max(L, zl); u2 = min(Uz, zu)
        if l2 > u2: fail('empty Z intersection'); return None, {}
        return [(l2, u2)], {}
    fail('unknown normalizer route %s' % route); return None, {}
