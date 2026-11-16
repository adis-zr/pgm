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


def check_worker_output(model_path, w, manifest_task=None, arm=None, deadline=None):
    """main entry; returns (failures, info)"""
    fails = []; info = {}; work = Work()
    def fail(m): fails.append(m)
    def late(): return deadline is not None and time.monotonic() >= deadline
    # ---------------- 1. binding
    try: task = TK.load_task(model_path, mode=(w.get('mode')))
    except Exception as ex: return ['task not readable: %s' % str(ex)[:80]], info
    if w.get('binding') != task['binding']: fail('worker binding differs from the files on disk')
    if w.get('task_identity') != TK.task_identity(task): fail('task identity differs from the re-derived identity')
    cert = w.get('certificate') or {}
    if cert.get('certificate_version') != 'cqr-certificate-v1': fail('unknown certificate version %s' % cert.get('certificate_version')); return fails, info
    if cert.get('diagnostic'): fail('a DIAGNOSTIC run (%s) is never a production publication' % cert.get('diagnostic')); return fails, info
    if manifest_task:
        for k in ('epsilon', 'delta'):
            if str(cert.get(k)) != str(manifest_task.get(k, str(task[k]))): fail('%s differs from the manifest task' % k)
    if arm is not None:
        if cert.get('arm') != arm or w.get('arm') != arm: fail('arm differs from the planned arm')
        spec = SV.ARMS.get(arm)
        if spec is None: fail('unknown arm'); return fails, info
        if sorted(cert.get('enabled_operators') or []) != sorted(spec['enabled']) or bool(cert.get('signed_stream')) != spec['signed_stream'] or bool(cert.get('query_directed_refinement')) != spec['query_directed_refinement']: fail('recorded operator set / stream flags differ from the registered arm')
    mode = cert.get('mode'); eps = task['epsilon']; delta = task['delta']
    if mode != task['mode']: fail('mode differs from the task')
    # ---------------- zero proofs
    if w.get('outcome') == 'PROVED_ZERO_EVIDENCE':
        zp = w.get('zero_evidence_proof') or {}
        if zp.get('kind') == 'compiler':
            try: CP.compile_task(task, enabled=set(cert.get('enabled_operators') or []), work=work); fail('compiler zero proof does not re-derive (compile succeeded)')
            except CP.ZeroEvidence as z:
                if z.proof.get('kind') != (zp.get('proof') or {}).get('kind'): fail('compiler zero proof kind differs (%s vs %s)' % (z.proof.get('kind'), (zp.get('proof') or {}).get('kind')))
        elif zp.get('kind') in ('reference_enumeration', 'frontier_closed_zero_mass'):
            tr = OR.enumerate_truth(task['model'], task['queries'], deadline=deadline, max_assignments=ORACLE_CAP)
            if tr is None: fail('UNVERIFIABLE: zero proof by enumeration exceeds the checker cap / allowance')
            elif tr['Z'] != 0: fail('zero-evidence claim contradicted by the independent enumerator (Z = %s)' % tr['Z'])
        else: fail('unknown zero proof kind %s' % zp.get('kind'))
        return fails, info
    if w.get('outcome') != 'PUBLISHED': return fails, info
    # ---------------- 2. compiler chain replay
    comp = cert.get('compile') or {}
    try:
        C, log = CP.compile_task(task, enabled=set(cert.get('enabled_operators') or []), work=work)
    except CP.ZeroEvidence as z: fail('replayed compile proves ZERO_EVIDENCE but the worker published'); return fails, info
    snap = C.snapshot_json(); sha_ = hashlib.sha256(json.dumps(snap, sort_keys=True, default=str).encode()).hexdigest()
    if sha_ != comp.get('final_sha256'): fail('compiled model does not replay (final_sha256 %s vs %s)' % (sha_[:12], str(comp.get('final_sha256'))[:12])); return fails, info
    # independent verification of the recorded certificates against the pre-step models (quotient / affine / symmetry / bias)
    rec_certs = comp.get('certificates') or []
    if [c.get('op') for c in rec_certs] != [c.get('op') for c in C.certs]: fail('recorded certificate chain differs from the replayed chain')
    vf = _verify_chain(task, cert.get('enabled_operators') or [], rec_certs, work, deadline)
    fails += vf
    bias = [_F(b) for b in (cert.get('bias') or [])]
    if bias != C.bias: fail('recorded bias ledger differs from the replayed one')
    if mode == 'EXACT_RATIONAL' and any(b != 0 for b in bias): fail('EXACT_RATIONAL publication with nonzero compiler bias')
    if any(b > eps / 4 for b in bias): fail('compiler bias exceeds the reserve eps/4')
    pub = cert.get('publication') or {}; route = pub.get('route'); K = len(task['queries']); cq = C.queries
    if late(): fail('UNVERIFIABLE: allowance expired after the compiler replay'); return fails, info
    normalizer = bool((task.get('query_spec') or {}).get('normalizer_task'))
    if normalizer:
        fails += _check_normalizer(task, C, cert, pub, route, eps, delta, deadline, work); info['route'] = route; return fails, info
    # ---------------- 3-4. frontier replay with draws
    fr_rec = cert.get('frontier'); events = cert.get('events') or []
    if C.cards:
        fr = FR.Frontier(C.cards, C.views, cq, work, order=fr_rec.get('order') if fr_rec else None)
        ratio_rec = cert.get('ratio_stream'); epochs = cert.get('epochs') or []
        ratio_draws = {d['t']: d for d in (ratio_rec or {}).get('draws', [])} if ratio_rec else {}
        H = F(0); Hj = [F(0)] * K; G = [F(0)] * K; V = F(0); t_r = 0; U_star = _F(ratio_rec['U_star']) if ratio_rec else None
        ep_state = {}; ep_idx = {e['epoch']: e for e in epochs}
        for ev in events:
            if late(): fail('UNVERIFIABLE: allowance expired during the frontier replay'); return fails, info
            op = ev.get('op')
            try:
                if op == 'split':
                    kids = fr.split(ev['cell'])
                    if kids != ev.get('children'): fail('split children differ at cell %s' % ev['cell']); break
                elif op == 'close': fr.close(ev['cell'])
                elif op == 'carve': fr.carve_point(ev['cell'], {int(k): v for k, v in ev['x'].items()})
                elif op == 'ratio_draw':
                    cells, U = fr.ratio_law(); c = fr.open.get(ev['cell'])
                    if c is None or _F(ev['U']) != U: fail('ratio draw %d: launch law differs (U %s vs %s)' % (t_r + 1, ev['U'], U)); break
                    x = {int(k): v for k, v in ev['x'].items()}
                    if any(x.get(k) != v for k, v in c.assign.items()): fail('ratio draw point outside its cell'); break
                    if _F(ev['A']) != fr.resolved_mass or [_F(v) for v in ev['a']] != fr.resolved_num or [_F(v) for v in ev['d']] != fr.resolved_den: fail('ratio draw %d: pre-trial resolved offsets differ (record-before-resolve violated)' % (t_r + 1)); break
                    wgt, fq = fr.weight_and_queries(x); q = c.E / U / c.N; W = wgt / q
                    if W > U: fail('importance weight exceeds the cap at draw %d' % (t_r + 1)); break
                    b = FR.dyadic_weight((U_star / U) ** 2); t_r += 1; H += b * (fr.resolved_mass + W)
                    for j in range(K):
                        fj, gj = fq[j]; G[j] += b * (fr.resolved_num[j] + W * fj); Hj[j] += b * ((fr.resolved_mass + W) if cq[j]['kind'] == 'expectation' else (fr.resolved_den[j] + W * gj))
                    V += b * b * U * U / 4
                elif op == 'epoch_start':
                    e = ev['epoch']; de = delta / (2 * e * (e + 1))
                    if _F(ev['delta_e']) != de: fail('epoch %d risk differs from delta/(2e(e+1))' % e); break
                    cand = [_F(c_) for c_ in ev['candidate']]; cells, E0 = fr.signed_law(cand, key=('epoch', e))
                    if _F(ev['E_star']) != (E0 if E0 > 0 else F(1)): fail('epoch %d E_star differs from the launch envelope' % e); break
                    ep_state[e] = dict(cand=cand, H=F(0), G=[F(0)] * K, V=F(0), t=0, E_star=_F(ev['E_star']), alpha=de / max(1, K))
                elif op == 'signed_draw':
                    st = ep_state.get(ev['epoch'])
                    if st is None: fail('signed draw before its epoch start'); break
                    cells, E = fr.signed_law(st['cand'], key=('epoch', ev['epoch'])); c = fr.open.get(ev['cell'])
                    if c is None or _F(ev['E']) != E: fail('signed draw: launch envelope differs (E %s vs %s)' % (ev['E'], E)); break
                    a_c = next((a for cc, a in cells if cc.id == c.id), None)
                    if a_c is None or _F(ev['p']) != a_c / E: fail('signed draw: cell probability differs'); break
                    rn = fr.resolved_num; rd_ = fr.resolved_den; rm = fr.resolved_mass; d = [rn[j] - st['cand'][j] * (rm if cq[j]['kind'] == 'expectation' else rd_[j]) for j in range(K)]
                    if [_F(v) for v in ev['d']] != d: fail('signed draw: pre-trial offsets differ'); break
                    x = {int(k): v for k, v in ev['x'].items()}; wgt, fq = fr.weight_and_queries(x); b = FR.dyadic_weight((st['E_star'] / E) ** 2); st['t'] += 1; st['H'] += b
                    for j in range(K):
                        fj, gj = fq[j]; R = wgt * (fj - st['cand'][j] * gj) / (a_c / E / c.N)
                        if abs(R) > E: fail('signed contribution exceeds E'); break
                        st['G'][j] += b * (d[j] + R)
                    st['V'] += b * b * E * E
                elif op in ('epoch_E_zero', 'epoch_retired', 'ratio_stream_stopped', 'prune_zero'): pass
                else: fail('unknown event %s' % op); break
            except AssertionError as ax: fail('frontier replay assertion: %s' % str(ax)[:80]); break
        if fails: return fails, info
        # final frontier record agreement
        if fr_rec is not None:
            if fr.resolved_mass != _F(fr_rec['resolved_mass']) or [str(x) for x in fr.resolved_num] != fr_rec['resolved_num'] or len(fr.open) != fr_rec['open_cells']: fail('replayed frontier totals differ from the recorded frontier')
        if ratio_rec is not None:
            if t_r != ratio_rec['t'] or str(H) != ratio_rec['H'] or [str(x) for x in G] != ratio_rec['G'] or str(V) != ratio_rec['V']: fail('ratio stream statistics do not replay')
            if _F(ratio_rec['alpha']) != delta / 2 / max(1, K) or _F(ratio_rec['rho']) != U_star * U_star / 4: fail('ratio stream risk / rho differ from the policy')
        for e in epochs:
            st = ep_state.get(e['epoch'])
            if st is None: fail('recorded epoch %s has no start event' % e['epoch']); continue
            if st['t'] != e['t'] or str(st['H']) != e['H'] or [str(x) for x in st['G']] != e['G'] or str(st['V']) != e['V']: fail('epoch %s statistics do not replay' % e['epoch'])
        if fails: return fails, info
        # ---------------- 6. exact reference route: the independent enumerator decides (frontier / streams replayed above are diagnostic for this route)
        if route == 'exact_reference':
            tr = OR.enumerate_truth(task['model'], task['queries'], deadline=deadline, max_assignments=ORACLE_CAP)
            if tr is None: fail('UNVERIFIABLE_REFERENCE_SIZE: the exact reference publication exceeds the checker cap / allowance (not shown wrong)')
            else:
                for j in range(K):
                    a = tr['answers'][j]; lo, hi = pub['bounds'][j]
                    if a == 'UNDEFINED':
                        if lo != 'UNDEFINED': fail('query %d: published a value for an undefined conditional' % j)
                    elif lo == 'UNDEFINED' or _F(lo) != a or _F(hi) != a or _F(pub['point'][j]) != a: fail('query %d: exact reference value differs from the independent enumerator' % j)
            info['exact'] = True; info['route'] = route; return fails, info
        # ---------------- 5. publication
        bounds = [( _F(a) if a != 'UNDEFINED' else 'UNDEFINED', _F(b) if b != 'UNDEFINED' else 'UNDEFINED') for a, b in pub['bounds']]; point = [(_F(p) if p != 'UNDEFINED' else 'UNDEFINED') for p in pub['point']]
        det = fr.deterministic_bounds() if fr.open or True else None
        for j in range(K):
            if j in C.constant_queries: det[j] = (C.constant_queries[j], C.constant_queries[j])
        Zlo = fr.Zlo(); positive = fr.resolved_mass > 0 or any(c.L > 0 for c in fr.open.values()) or (C.witness is not None)
        if not positive: fail('publication without a proved positive mass')
        Lj = []
        for j, q in enumerate(cq):
            if q['kind'] == 'expectation': Lj.append(Zlo)
            else: Lj.append(fr.resolved_den[j] + sum(c.L * c.qlo[j][1] for c in fr.open.values()))
        tau = [eps - C.bias[j] - SV.MARGIN for j in range(K)]; tau_pub = eps - SV.MARGIN
        def widen(x, j): return (max(F(0), x[0] - C.bias[j]), min(F(1), x[1] + C.bias[j]))
        def pub_ok(j, proven):
            """proven = the checker's enclosure of the ORIGINAL answer (already widened); the publication must contain it and the point must be within eps - margin of both published ends"""
            lo, hi = bounds[j]
            if lo == 'UNDEFINED': return 'undefined query published'
            if not (lo <= proven[0] and proven[1] <= hi): return 'published bounds of query %d do not contain the re-derived enclosure' % j
            if not (lo <= point[j] <= hi and hi - tau_pub <= point[j] <= lo + tau_pub): return 'point of query %d outside the feasibility box' % j
            return None
        if not fr.open and route in ('exact_frontier_closure',):
            for j in range(K):
                if cq[j]['kind'] == 'expectation':
                    v = fr.resolved_num[j] / fr.resolved_mass if fr.resolved_mass else None
                    if v is None or bounds[j] != (v, v) or point[j] != v: fail('closed-frontier exact answer differs for query %d' % j)
                else:
                    if fr.resolved_den[j] == 0:
                        if bounds[j][0] != 'UNDEFINED': fail('query %d undefined but published' % j)
                    else:
                        v = fr.resolved_num[j] / fr.resolved_den[j]
                        if bounds[j] != (v, v) or point[j] != v: fail('closed-frontier exact ratio differs for query %d' % j)
            info['route'] = route; return fails, info
        if route in ('deterministic_frontier', 'deterministic_zero_dimensional'):
            for j in range(K):
                if bounds[j][0] == 'UNDEFINED': fail('deterministic publication of an undefined query'); continue
                if cq[j]['kind'] == 'ratio' and Lj[j] <= 0: fail('ratio query %d published without a positive denominator bound' % j)
                m_ = pub_ok(j, widen(det[j], j))
                if m_: fail(m_)
        elif route == 'deterministic_concentration':
            dc = next((c for c in rec_certs if c.get('op') == 'concentration' and 'answers' in c), None)
            if dc is None: fail('concentration route without a concentration certificate')
            else:
                for j in range(K):
                    a_ = _F(dc['answers'][str(j)]); m_ = pub_ok(j, widen((a_, a_), j))
                    if m_: fail(m_)
        elif route == 'deterministic_signed_residual_E_zero':
            e = pub.get('epoch'); st = ep_state.get(e)
            if st is None: fail('E=0 route without its epoch')
            else:
                cells, E = fr.signed_law(st['cand'])
                if E != 0: fail('E = 0 claimed but the replayed envelope is %s' % E)
                for j in range(K):
                    d = fr.resolved_num[j] - st['cand'][j] * (fr.resolved_mass if cq[j]['kind'] == 'expectation' else fr.resolved_den[j])
                    if Lj[j] <= 0 or abs(d) > tau[j] * Lj[j]: fail('E = 0 residual of query %d does not certify' % j)
                    if point[j] != st['cand'][j]: fail('published point differs from the epoch candidate')
                    m_ = pub_ok(j, widen((st['cand'][j] - tau[j], st['cand'][j] + tau[j]), j))
                    if m_: fail(m_)
        elif route == 'pac_ratio_intersected_with_deterministic':
            if H <= 0: fail('PAC ratio publication without observations')
            else:
                B = NM.boundary_upper(U_star * U_star / 4, V, delta / 2 / K)
                for j in range(K):
                    if Hj[j] <= 0: fail('query %d has no denominator statistic' % j); continue
                    c = G[j] / Hj[j]; r = B / Hj[j]; lo = max(det[j][0], max(F(0), c - r)); hi = min(det[j][1], min(F(1), c + r))
                    if lo > hi: fail('empty intersection for query %d' % j); continue
                    m_ = pub_ok(j, widen((lo, hi), j))
                    if m_: fail(m_)
                    if cq[j]['kind'] == 'ratio' and Lj[j] <= 0: fail('ratio query %d published without a positive denominator bound' % j)
        elif route == 'pac_signed_residual_validation':
            e = pub.get('epoch'); st = ep_state.get(e)
            if st is None or st['H'] <= 0: fail('signed validation without observations')
            else:
                B = NM.boundary_upper(st['E_star'] ** 2, st['V'], st['alpha'])
                for j in range(K):
                    lo = (st['G'][j] - B) / st['H']; hi = (st['G'][j] + B) / st['H']
                    if Lj[j] <= 0 or lo < -tau[j] * Lj[j] or hi > tau[j] * Lj[j]: fail('signed validation interval of query %d does not fit [-tau L, tau L]' % j)
                    if point[j] != st['cand'][j]: fail('published point differs from the validated candidate')
                    m_ = pub_ok(j, widen((st['cand'][j] - tau[j], st['cand'][j] + tau[j]), j))
                    if m_: fail(m_)
        else: fail('unknown publication route %s' % route)
        # simplex feasibility of singleton families
        for g in SV._singleton_groups(task):
            if sum(point[j] for j in g) != 1: fail('singleton family does not sum to one')
    elif route == 'exact_reference':
        tr = OR.enumerate_truth(task['model'], task['queries'], deadline=deadline, max_assignments=ORACLE_CAP)
        if tr is None: fail('UNVERIFIABLE_REFERENCE_SIZE: the exact reference publication exceeds the checker cap / allowance (not shown wrong)')
        else:
            for j in range(K):
                a = tr['answers'][j]; lo, hi = pub['bounds'][j]
                if a == 'UNDEFINED':
                    if lo != 'UNDEFINED': fail('query %d: published a value for an undefined conditional' % j)
                elif lo == 'UNDEFINED' or _F(lo) != a or _F(hi) != a or _F(pub['point'][j]) != a: fail('query %d: exact reference value differs from the independent enumerator' % j)
    else:
        # zero-dimensional compiled model: every compiled query view has empty scope
        for j, q in enumerate(cq):
            if q['kind'] == 'expectation': v = q['f'].values[0]
            else: v = (q['h'].values[0] / q['g'].values[0]) if q['g'].values[0] else 'UNDEFINED'
            lo, hi = pub['bounds'][j]
            if v == 'UNDEFINED':
                if lo != 'UNDEFINED': fail('query %d undefined but published' % j)
            elif lo == 'UNDEFINED' or _F(lo) != v or _F(hi) != v: fail('zero-dimensional answer differs for query %d' % j)
    # legacy rows vs answers
    if w.get('intervals') is not None:
        groups = SV._singleton_groups(task); cards = task['model']['cards']
        if len(w['intervals']) != len(cards): fail('legacy rows shape differs from the original model')
        else:
            for j, q in enumerate(task['queries']):
                o = q.output or {}
                if o.get('kind') != 'singleton': continue
                lo, hi = w['intervals'][o['variable']][o['state']]; p = w['points'][o['variable']][o['state']]
                if pub['bounds'][j][0] == 'UNDEFINED' or not (F(lo) <= _F(pub['bounds'][j][0]) and _F(pub['bounds'][j][1]) <= F(hi)): fail('legacy row of query %d does not contain the exact bounds' % j)
                if abs(F(p) - _F(pub['point'][j])) > SV.MARGIN: fail('legacy point of query %d differs from the exact point beyond the rounding margin' % j)
    info['route'] = route; info['work'] = work.snapshot()
    return fails, info


def verify_quotient_step_views(cards, views, step, inc_idx, work):
    """independent cross-multiplication check of a recorded quotient step against the given pre-step views (inc_idx = indices of the incident views)"""
    st = dict(step, incident_factors=inc_idx); return CP.verify_quotient_step(cards, views, st, work)


def _verify_chain(task, enabled, rec_certs, work, deadline):
    """replay the compile step by step, verifying each recorded certificate on the PRE-step model with the independent verifiers"""
    fails = []
    try:
        C = CP.from_task(task, work)
    except CP.ZeroEvidence: return ['chain verification: evidence restriction proves zero']
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
                # recompute t_i from the recorded x* on the pre-step model
                xs = {int(k): v for k, v in rc['xstar'].items()}
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
    return fails


def _check_normalizer(task, C, cert, pub, route, eps, delta, deadline, work):
    """Z with relative error: replay the frontier (no streams besides the ratio stream), recompute L, U in ORIGINAL units (scale_den and the KNOWN scalars), check the publication rule"""
    fails = []
    if any(d.get('kind') == 'omitted_component_mass' for d in C.scalars): fails.append('normalizer task with an omitted component (unknown scalar)'); return fails
    sc = F(1)
    for d in C.scalars: sc *= F(d['value'])
    for d in (C.certs[0].get('constant_factor_scalars') or []): sc *= F(d['value'])
    if str(sc) != str(pub.get('scale', str(sc))) and route != 'normalizer_exact_reference': fails.append('known scalar product differs (%s vs %s)' % (sc, pub.get('scale')))
    lo, hi = pub['bounds'][0]; lo = _F(lo); hi = _F(hi); c = _F(pub['point'][0])
    if route == 'normalizer_exact_reference':
        tr = OR.enumerate_truth(task['model'], task['queries'], deadline=deadline, max_assignments=ORACLE_CAP)
        if tr is None: fails.append('UNVERIFIABLE_REFERENCE_SIZE: exact Z publication exceeds the checker cap')
        elif tr['Z'] != lo or lo != hi or c != lo: fails.append('exact Z differs from the independent enumerator')
        return fails
    if not C.cards:
        if lo != sc or hi != sc or c != sc: fails.append('zero-dimensional Z differs from the scalar product')
        return fails
    fr = FR.Frontier(C.cards, C.views, C.queries, work, order=(cert.get('frontier') or {}).get('order'))
    ratio_rec = cert.get('ratio_stream'); U_star = _F(ratio_rec['U_star']) if ratio_rec else None; H = F(0); Hb = F(0); V = F(0); t_r = 0
    for ev in cert.get('events') or []:
        op = ev.get('op')
        if op == 'split':
            if fr.split(ev['cell']) != ev.get('children'): fails.append('split children differ'); return fails
        elif op == 'close': fr.close(ev['cell'])
        elif op == 'carve': fr.carve_point(ev['cell'], {int(k): v for k, v in ev['x'].items()})
        elif op == 'ratio_draw':
            cells, U = fr.ratio_law(); cc = fr.open.get(ev['cell'])
            if cc is None or _F(ev['U']) != U or _F(ev['A']) != fr.resolved_mass: fails.append('ratio draw law / offset differs'); return fails
            x = {int(k): v for k, v in ev['x'].items()}; wgt, fq = fr.weight_and_queries(x); W = wgt / (cc.E / U / cc.N)
            if W > U: fails.append('importance weight exceeds the cap'); return fails
            b = FR.dyadic_weight((U_star / U) ** 2); t_r += 1; H += b * (fr.resolved_mass + W); Hb += b; V += b * b * U * U / 4
        elif op in ('ratio_stream_stopped', 'prune_zero', 'epoch_start', 'epoch_retired', 'epoch_E_zero'): pass
        else: fails.append('unexpected event %s in a normalizer run' % op); return fails
        if deadline is not None and time.monotonic() >= deadline: fails.append('UNVERIFIABLE: allowance expired'); return fails
    L = fr.Zlo() / fr.scale_den * sc; Uz = fr.Zhi() / fr.scale_den * sc
    if route == 'normalizer_exact_frontier_closure':
        if fr.open or fr.resolved_mass / fr.scale_den * sc != lo or lo != hi or c != lo: fails.append('closed-frontier exact Z differs')
        return fails
    if route == 'normalizer_deterministic_frontier':
        if lo != L or hi != Uz: fails.append('deterministic Z bounds do not replay')
    elif route == 'normalizer_pac_ratio_intersected_with_deterministic':
        if ratio_rec is None or Hb <= 0 or t_r != ratio_rec['t']: fails.append('ratio stream does not replay'); return fails
        B = NM.boundary_upper(U_star * U_star / 4, V, delta / 2 / max(1, len(C.queries)))
        zl = max(F(0), (H - B) / Hb) / fr.scale_den * sc; zu = (H + B) / Hb / fr.scale_den * sc; l2 = max(L, zl); u2 = min(Uz, zu)
        if l2 > u2: fails.append('empty Z intersection'); return fails
        if lo < l2 or hi > u2: fails.append('published Z bounds wider than the re-derived intersection')
    else: fails.append('unknown normalizer route %s' % route); return fails
    if lo <= 0: fails.append('Z lower bound not positive')
    if not ((1 - eps) * hi <= c <= (1 + eps) * lo): fails.append('Z point outside [(1-eps) U, (1+eps) L]')
    return fails
