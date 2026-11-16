"""CQR REDUCTION COMPILER (manuscript §3; supporting notes query_structure_algorithm.txt, reduction_algorithms.txt). Transactional: every operator PROPOSES from
source data, CONSTRUCTS a candidate, VERIFIES its certificate against the current compiled model with exact arithmetic (the `verify_*` functions below are the same
ones the independent checker calls on the recorded chain), then COMMITS. Finite work quota (policy); canonical order; no unchanged proposal is retried.
Operators (mandatory set A-E of the handoff):
  A  evidence restriction; checked support propagation (identically-zero incident slices remove states; empty domain / zero factor => ZERO_EVIDENCE); fixed-variable
     substitution; local leaf sum-out of a nonquery variable in exactly one factor; omission of a query-free component after a positivity proof (normalized tasks only);
     generic symmetry verifier with a bounded proposer (global binary complement; table-signature state swaps).
  B  exact proportional incident-slice quotient: classes = equal normalized slices in EVERY incident factor; multiplicity weights kappa / S; stochastic decoder; query
     tables averaged with kappa/S (both h and g of a ratio query).
  C  checked approximate quotient: common zero masks, canonical pivots, surrogate, ALL-entry ratio certificate l_a <= phi/phi~ <= u_a, R = prod u/l,
     beta = (R-1)/(R+3) spent from the bias allowance, then the exact quotient of the surrogate.
  D  local affine-support recognizer (|R| == 2^rank test), global GF(2) elimination (inconsistency => ZERO_EVIDENCE), compact linear-map views, query pullbacks
     (singletons become parities); applied ONCE, last, as the representation change.
  E  generic categorical influence (Dobrushin comparison; strictly positive tables required; zeros decline) with bounded deletion policy, and the concentration
     certificate (local ratio inequalities around a cheap proposed assignment) -> a direct certified answer with a proved bias.
Decoder (per ORIGINAL variable): fixed(state) | map(compiled var, {compiled state: [(orig state, weight)]}) stochastic | affine(c, z vars) | summed | omitted."""
import time
from fractions import Fraction as F
import sys as _sys; _sys.set_int_max_str_digits(0)
from itertools import product
from math import prod
from views import View, gf2_rank_basis, gf2_reduce, gf2_span
from task import Work

COMPILER_VERSION = 'cqr-compiler-v1 (2026-11-16)'
POLICY = dict(
    compiler_version=COMPILER_VERSION,
    order=('evidence', 'support_fixpoint', 'fixed_substitution', 'leaf_sumout', 'component_omission', 'exact_quotient_pass', 'symmetry', 'approx_quotient', 'concentration', 'influence_deletion', 'affine'),
    quota_rule='discovery work quota D = max(50_000, 8 * (sum of source table entries + sum of query table entries)) work units; each operator stops at its share; the complete exact quotient pass gets its own share of the same size (so the clone-family attainment is reachable)',
    bias_reserve='DETERMINISTIC_EPS / PAC_EPS: at most epsilon/4 of every query allowance for compiler bias (manuscript §3.2); EXACT_RATIONAL: zero',
    symmetry_proposer='global binary complement; for each variable the state swap induced by sorting its unary signature (bounded: at most n + 1 candidates)',
    approx_quotient_order='variables in canonical order; states in canonical order; first representative group with a matching zero mask whose widened ratio certificate still fits the remaining bias allowance; pair-scan cap d_v^2',
    influence_policy='all non-unary factors first; then greedy in order of decreasing table size (ties: factor index), each candidate accepted only if every query bias fits; Neumann T = 8',
    concentration_proposal='per variable the maximizer of the product of its unary factors (ties: first state); no coordinate ascent',
    well_founded='every committed operator strictly decreases (variables, total domain, factor+query entries) in lexicographic order, except affine (once, last)')


class ZeroEvidence(Exception):
    def __init__(self, proof): super().__init__('ZERO_EVIDENCE'); self.proof = proof


class CompileStop(Exception):
    """raised by `tick` at a CONSISTENT point of an operator (between committed transactions): the compiled model is the last committed state. kind in
    {'deadline', 'reference_done', 'cancelled'}; the driver records the interrupted operator and returns the committed model."""
    def __init__(self, kind, op=None): super().__init__(kind); self.kind = kind; self.op = op


def tick(C, quota=None, op=None):
    """called inside every costly loop at points where the model is consistent: (1) enforces the operator quota (raises CompileStop('quota') => the operator DECLINES the
    rest, keeping what it committed); (2) calls the solver's service hook (reference parity; deadline) which may raise CompileStop('deadline' | 'reference_done')."""
    if quota is not None and C.work.total() >= quota: raise CompileStop('quota', op)
    fn = getattr(C, 'service', None)                         # TASK-LOCAL hook (no module state; it lives on this task's Compiled object, so it cannot leak across tasks)
    if fn is not None: fn(op)


class Compiled:
    """the compiled task state"""
    def __init__(self, cards, views, queries, decoder, work, bias, normalizer_task=False):
        self.cards = list(cards); self.views = views; self.queries = queries; self.decoder = decoder; self.work = work; self.bias = bias
        self.certs = []; self.scalars = []; self.constant_scalars = []; self.witness = None; self.normalizer_task = normalizer_task; self.affine_done = False; self.service = None; self.constant_queries = {}

    def n(self): return len(self.cards)
    def measure(self): return (len(self.cards), sum(self.cards), sum(v.size() for v in self.views) + sum(_qsize(q) for q in self.queries))
    def snapshot_json(self):
        return dict(cards=list(self.cards), factors=[v.to_json() for v in self.views], queries=[_q_json(q) for q in self.queries], decoder=_dec_json(self.decoder), bias=[str(b) for b in self.bias],
                    scalars=list(self.scalars), constant_queries={str(k): str(v) for k, v in self.constant_queries.items()}, affine_done=self.affine_done)


def _qsize(q): return q['f'].size() if q['kind'] == 'expectation' else q['h'].size() + q['g'].size()
def _q_json(q):
    d = dict(name=q['name'], kind=q['kind'], output=q.get('output'), orig_index=q['orig_index'])
    if q['kind'] == 'expectation': d['f'] = q['f'].to_json()
    else: d['h'] = q['h'].to_json(); d['g'] = q['g'].to_json()
    return d
def _dec_json(dec):
    out = []
    for d in dec:
        e = dict(d)
        if d['kind'] == 'map': e['states'] = {str(k): [(a, str(w)) for a, w in v] for k, v in d['states'].items()}
        out.append(e)
    return out


def q_views(q): return [q['f']] if q['kind'] == 'expectation' else [q['h'], q['g']]
def q_scope(q): return set().union(*(set(v.scope) for v in q_views(q)))


# ======================================================================================================================
# construction from the original task (operator A: evidence restriction)
# ======================================================================================================================
def from_task(task, work=None):
    """evidence-restricted compiled task over the FREE original variables (observed variables: decoder 'fixed'); factor and query tables restricted to the evidence"""
    work = work or Work(); m = task['model']; cards0 = m['cards']; ev = m.get('evidence', {}); n0 = len(cards0)
    free = [v for v in range(n0) if v not in ev]; new_of = {v: i for i, v in enumerate(free)}; cards = [cards0[v] for v in free]
    def restrict(scope, values):
        ns = tuple(new_of[v] for v in scope if v not in ev); vals = []
        for xs, w in zip(product(*(range(cards0[v]) for v in scope)), values):
            work.entries += 1
            if all(v in new_of or ev[v] == s for v, s in zip(scope, xs)): vals.append(F(w))
        return ns, vals
    views = []; constant_scalars = []           # TASK-LOCAL (review CQR-07: a module-global list leaked constants across tasks when ZeroEvidence bypassed its clearing)
    for fi, f in enumerate(m['factors']):
        ns, vals = restrict(f['scope'], f['values'])
        if not ns:
            if vals[0] == 0: raise ZeroEvidence(dict(kind='fully_observed_factor_zero', factor=fi))
            if vals[0] != 1: constant_scalars.append(dict(factor=fi, value=str(vals[0])))      # a positive constant factor: cancelled for normalized tasks (symbolic scalar), kept as an exact scalar for normalizer tasks
            continue
        views.append(View('table', ns, vals))
    queries = []
    for j, q in enumerate(task['queries']):
        if q.kind == 'expectation':
            ns, vals = restrict(q.f.scope, q.f.values); queries.append(dict(name=q.name, kind='expectation', f=View('table', ns, vals), output=q.output, orig_index=j))
        else:
            nh, vh = restrict(q.h.scope, q.h.values); ng, vg = restrict(q.g.scope, q.g.values); queries.append(dict(name=q.name, kind='ratio', h=View('table', nh, vh), g=View('table', ng, vg), output=q.output, orig_index=j))
    decoder = [dict(kind='fixed', state=ev[v]) if v in ev else dict(kind='map', var=new_of[v], states={a: [(a, F(1))] for a in range(cards0[v])}) for v in range(n0)]
    normalizer_task = bool((task.get('query_spec') or {}).get('normalizer_task'))
    C = Compiled(cards, views, queries, decoder, work, [F(0)] * len(task['queries']), normalizer_task=normalizer_task)
    C.constant_scalars = constant_scalars
    C.certs.append(dict(op='evidence', evidence={str(k): v for k, v in sorted(ev.items())}, free=free, constant_factor_scalars=list(constant_scalars)))
    return C


# ======================================================================================================================
# helpers on views that are plain tables
# ======================================================================================================================
def _slice(view, cards, var, state):
    """the slice of a table view over the other scope variables at var = state, as a tuple in row-major order of the remaining scope"""
    assert view.kind == 'table'; k = view.scope.index(var); rest = [v for v in view.scope if v != var]; out = []
    for xs in product(*(range(cards[v]) for v in rest)):
        x = dict(zip(rest, xs)); x[var] = state; i = 0
        for v in view.scope: i = i * cards[v] + x[v]
        out.append(view.values[i])
    return tuple(out)


def _replace_axis(view, cards, var, new_states, new_card):
    """rebuild a table view with the axis `var` replaced: new_states[s'] = the OLD state whose slice represents new state s' (table), returns the new View (cards must carry the new card)"""
    rest_axes = []; scope = view.scope; vals = []
    old_cards = dict(zip(scope, [cards[v] for v in scope])); old_cards[var] = cards[var]
    def idx(x):
        i = 0
        for v in scope: i = i * old_cards[v] + x[v]
        return i
    for xs in product(*((range(new_card) if v == var else range(old_cards[v])) for v in scope)):
        x = dict(zip(scope, xs)); x[var] = new_states[x[var]]; vals.append(view.values[idx(x)])
    return View('table', scope, vals)


def _average_axis(view, cards, var, classes, weights):
    """query pullback for a quotient: new value at class C = sum_{a in C} weights[a] * old value at a"""
    scope = view.scope; vals = []
    def idx(x):
        i = 0
        for v in scope: i = i * cards[v] + x[v]
        return i
    for xs in product(*((range(len(classes)) if v == var else range(cards[v])) for v in scope)):
        x = dict(zip(scope, xs)); c = x[var]; s = F(0)
        for a in classes[c]: x[var] = a; s += weights[a] * view.values[idx(x)]
        vals.append(s)
    return View('table', scope, vals)


def _remove_var_from_scope_fixed(view, cards, var, state):
    scope = view.scope; rest = tuple(v for v in scope if v != var); vals = []
    for xs in product(*(range(cards[v]) for v in rest)):
        x = dict(zip(rest, xs)); x[var] = state; i = 0
        for v in scope: i = i * cards[v] + x[v]
        vals.append(view.values[i])
    return View('table', rest, vals)


def _renumber(C, removed):
    """remove compiled variables `removed` (set) from every view / query / decoder; they must not occur in any scope any more"""
    keep = [v for v in range(C.n()) if v not in removed]; new = {v: i for i, v in enumerate(keep)}
    for v in C.views + [vv for q in C.queries for vv in q_views(q)]:
        assert not (set(v.scope) & removed), 'variable still in a scope'
        v.scope = tuple(new[u] for u in v.scope)
        if v.kind == 'affine': v.cat_scope = tuple(new[u] for u in v.cat_scope); v.zcols = tuple(new[u] for u in v.zcols)
    for d in C.decoder:
        if d['kind'] == 'map': d['var'] = new[d['var']]
        if d['kind'] == 'affine': d['zvars'] = [new[u] for u in d['zvars']]
    C.cards = [C.cards[v] for v in keep]


# ======================================================================================================================
# operator A: support fixpoint, fixed substitution, leaf sum-out, component omission
# ======================================================================================================================
def support_fixpoint(C, quota):
    """remove compiled states whose slice is identically zero in some incident table factor; fixpoint; an empty domain => ZERO_EVIDENCE"""
    changed = True; removed = []; passes = 0
    while changed and C.work.total() < quota:
        changed = False; passes += 1
        for var in range(C.n()):
            tick(C, None, 'support_fixpoint')
            inc = [v for v in C.views if v.kind == 'table' and var in v.scope]
            dead = set()
            for v in inc:
                for s in range(C.cards[var]):
                    sl = _slice(v, C.cards, var, s); C.work.entries += len(sl)
                    if not any(sl): dead.add(s)
            if dead:
                alive = [s for s in range(C.cards[var]) if s not in dead]
                if not alive: raise ZeroEvidence(dict(kind='empty_domain_after_support_propagation', compiled_variable=var, pass_=passes))
                _restrict_states(C, var, alive); removed.append(dict(var=var, dead=sorted(dead))); changed = True
    if removed: C.certs.append(dict(op='support', removed=removed, passes=passes))
    return bool(removed)


def _restrict_states(C, var, alive):
    """keep only states `alive` (ordered) of compiled variable var; tables / queries re-indexed; decoder maps composed (dead original states get weight through nothing: removed)"""
    for v in C.views + [vv for q in C.queries for vv in q_views(q)]:
        if var in v.scope:
            assert v.kind == 'table'
            nv = _replace_axis(v, C.cards, var, alive, len(alive)); v.values = nv.values
    pos = {s: i for i, s in enumerate(alive)}
    for d in C.decoder:
        if d['kind'] == 'map' and d['var'] == var: d['states'] = {pos[s]: lst for s, lst in d['states'].items() if s in pos}
    C.cards[var] = len(alive)


def fixed_substitution(C):
    """compiled variables with one state are substituted into every factor / query and removed; decoder: the original states mapped to it become fixed (weighted among themselves if several)"""
    fixed = [v for v in range(C.n()) if C.cards[v] == 1]
    if not fixed: return False
    for var in fixed:
        for v in C.views + [vv for q in C.queries for vv in q_views(q)]:
            if var in v.scope: nv = _remove_var_from_scope_fixed(v, C.cards, var, 0); v.scope = nv.scope; v.values = nv.values
        for d in C.decoder:
            if d['kind'] == 'map' and d['var'] == var:
                lst = d['states'][0]
                if len(lst) == 1 and lst[0][1] == 1: d.clear(); d.update(kind='fixed', state=lst[0][0])
                else: d.clear(); d.update(kind='fixed_mixture', states=lst)   # a class fixed as a whole: original states keep their conditional weights
    # constant (empty-scope) factors created by substitution: positive scalars cancel (normalized) or are retained (normalizer task); zero => ZERO_EVIDENCE
    keep = []
    for i, v in enumerate(C.views):
        if not v.scope:
            if v.values[0] == 0: raise ZeroEvidence(dict(kind='constant_factor_zero_after_substitution', factor=i))
            C.scalars.append(dict(kind='constant_factor', value=str(v.values[0])))
        else: keep.append(v)
    C.views = keep; _renumber(C, set(fixed)); C.certs.append(dict(op='fixed_substitution', variables=fixed)); return True


def leaf_sumout(C, quota):
    """a compiled variable outside every query scope occurring in exactly ONE table factor: replace that factor by its sum over the variable (no fill); positive scalar
    results cancel (normalized) / are retained (normalizer); a zero sum is ZERO_EVIDENCE only when the resulting factor is identically zero"""
    done = []
    while C.work.total() < quota:
        tick(C, None, 'leaf_sumout')
        qscope = set().union(*(q_scope(q) for q in C.queries)) if C.queries else set()
        cand = None
        for var in range(C.n()):
            if var in qscope: continue
            inc = [i for i, v in enumerate(C.views) if var in v.scope]
            if len(inc) == 1 and C.views[inc[0]].kind == 'table': cand = (var, inc[0]); break
        if cand is None: break
        var, fi = cand; v = C.views[fi]; rest = tuple(u for u in v.scope if u != var); vals = []
        for xs in product(*(range(C.cards[u]) for u in rest)):
            x = dict(zip(rest, xs)); s = F(0)
            for a in range(C.cards[var]):
                x[var] = a; i = 0
                for u in v.scope: i = i * C.cards[u] + x[u]
                s += v.values[i]; C.work.entries += 1
            vals.append(s)
        if not any(vals): raise ZeroEvidence(dict(kind='leaf_sum_identically_zero', compiled_variable=var, factor=fi))
        if rest: v.scope = rest; v.values = vals
        else: C.scalars.append(dict(kind='leaf_sum_scalar', value=str(vals[0]))); C.views.pop(fi)
        for d in C.decoder:
            if d['kind'] == 'map' and d['var'] == var: d.clear(); d.update(kind='summed')
        _renumber(C, {var}); done.append(dict(var=var, factor=fi))
    if done: C.certs.append(dict(op='leaf_sumout', steps=done))
    return bool(done)


def _components(C):
    adj = {v: set() for v in range(C.n())}
    for v in C.views:
        for a in v.scope: adj[a] |= set(v.scope) - {a}
    seen = set(); comps = []
    for v in range(C.n()):
        if v in seen: continue
        todo = [v]; comp = {v}
        while todo:
            u = todo.pop()
            for w in adj[u]:
                if w not in comp: comp.add(w); todo.append(w)
        seen |= comp; comps.append(sorted(comp))
    return comps


def component_omission(C):
    """omit a query-free connected component ONLY with a positivity proof (all its tables strictly positive, or a witness restricted to it has positive weight); normalized tasks only"""
    if C.normalizer_task: return False
    qscope = set().union(*(q_scope(q) for q in C.queries)) if C.queries else set(); omitted = []
    for comp in _components(C):
        if set(comp) & qscope: continue
        fv = [i for i, v in enumerate(C.views) if set(v.scope) <= set(comp)]
        proof = None
        if all(all(x > 0 for x in C.views[i].values) for i in fv): proof = dict(kind='all_tables_strictly_positive', factors=fv); C.work.entries += sum(C.views[i].size() for i in fv)
        elif C.witness is not None:
            w = F(1)
            for i in fv: w *= C.views[i].at(C.cards, C.witness); C.work.evals += 1
            if w > 0: proof = dict(kind='witness_restricted_positive', factors=fv, witness={str(v): C.witness[v] for v in comp}, weight=str(w))
        if proof is None: continue
        omitted.append(dict(variables=comp, factors=fv, proof=proof))
    if not omitted: return False
    drop_f = set(); drop_v = set()
    for o in omitted: drop_f |= set(o['factors']); drop_v |= set(o['variables'])
    C.views = [v for i, v in enumerate(C.views) if i not in drop_f]
    for d in C.decoder:
        if d['kind'] == 'map' and d['var'] in drop_v: d.clear(); d.update(kind='omitted')
    _renumber(C, drop_v); C.scalars.append(dict(kind='omitted_component_mass', count=len(omitted), note='symbolic positive scalar; unknown numeric value; never reused as a numeric bound'))
    C.certs.append(dict(op='component_omission', omitted=omitted)); return True


# ======================================================================================================================
# operator B / C: proportional-slice quotient (exact) and the checked approximate variant
# ======================================================================================================================
def _signatures(C, var):
    """per state: tuple over incident table factors of (normalized slice tuple, pivot); None if an incident view is not a plain table (quotient declines)"""
    inc = [v for v in C.views if var in v.scope]
    if any(v.kind != 'table' for v in inc): return None, inc
    sig = {}
    for s in range(C.cards[var]):
        parts = []
        for v in inc:
            sl = _slice(v, C.cards, var, s); C.work.entries += len(sl)
            piv = next((x for x in sl if x), None)
            if piv is None: return None, inc            # a zero slice: support propagation must run first
            parts.append((tuple(x / piv for x in sl), piv)); C.work.ratops += len(sl)
        sig[s] = parts
    return sig, inc


def exact_quotient_pass(C, quota, hook=None):
    """one complete pass over the compiled variables in canonical order (manuscript §3.1): classes of equal normalized incident slices; commit when some class has >= 2 states.
    A variable with NO incident factor has identical (empty) slices: all its states form one class (kappa = 1, S = d: the uniform marginal through the decoder).
    hook(kind, var, classes, sig, inc) is called BEFORE each commit (the checker verifies the step on the exact pre-step state)."""
    committed = []
    for var in range(C.n()):
        if var >= C.n(): break
        try: tick(C, quota, 'exact_quotient_pass')
        except CompileStop as cs:
            if cs.kind == 'quota': break
            if committed: C.certs.append(dict(op='exact_quotient_pass', steps=committed, interrupted=cs.kind))
            raise
        sig, inc = _signatures(C, var)
        if sig is None: continue
        if not inc: sig = {s: [] for s in range(C.cards[var])}
        groups = {}
        for s in range(C.cards[var]): groups.setdefault(tuple(p[0] for p in sig[s]), []).append(s)
        classes = [sorted(g) for g in groups.values()]; classes.sort(key=lambda g: g[0])
        if len(classes) == C.cards[var]: continue
        if hook is not None: hook('exact', var, classes, sig, inc)
        step = _quotient_commit(C, var, classes, sig, inc, approx=None)
        committed.append(step)
    if committed: C.certs.append(dict(op='exact_quotient_pass', steps=committed))
    return bool(committed)


def _quotient_commit(C, var, classes, sig, inc, approx):
    """commit a quotient of compiled variable var into `classes` (list of sorted state lists) with representative = first state; sig gives pivots; approx records the surrogate certificate"""
    reps = [g[0] for g in classes]; kappa = {}; S = []
    for g in classes:
        tot = F(0)
        for a in g:
            k = F(1)
            for fi in range(len(inc)): k *= sig[a][fi][1] / sig[g[0]][fi][1]; C.work.ratops += 1
            kappa[a] = k; tot += k
        S.append(tot)
    # factor slices -> representative slices (surrogate already applied in the approximate case)
    for v in inc:
        nv = _replace_axis(v, C.cards, var, reps, len(classes)); v.values = nv.values
    # unary S_C (combined with an existing unary over var if present)
    un = next((v for v in C.views if v.kind == 'table' and v.scope == (var,)), None)
    if un is not None: un.values = [un.values[i] * S[i] for i in range(len(classes))]
    else: C.views.append(View('table', (var,), list(S)))
    # queries: weighted average with kappa_a / S_C
    weights = {a: kappa[a] / S[ci] for ci, g in enumerate(classes) for a in g}
    for q in C.queries:
        for vv in q_views(q):
            if var in vv.scope: nv = _average_axis(vv, C.cards, var, classes, weights); vv.values = nv.values; C.work.ratops += len(nv.values)
    # decoder: compose
    for d in C.decoder:
        if d['kind'] == 'map' and d['var'] == var:
            new = {}
            for ci, g in enumerate(classes):
                lst = []
                for a in g:
                    for (orig, w) in d['states'][a]: lst.append((orig, w * weights[a]))
                new[ci] = lst
            d['states'] = new
    C.cards[var] = len(classes)
    rec = dict(var=var, classes=classes, representatives=reps, kappa={str(a): str(k) for a, k in kappa.items()}, S=[str(s) for s in S], incident_factors=[C.views.index(v) for v in inc], approx=approx)
    return rec


def approx_quotient(C, quota, allowance, hook=None):
    """operator C: for each variable (canonical order) try to merge states whose normalized slices are CLOSE: common zero masks; surrogate = scaled representative slice;
    ALL-entry ratio bounds per incident factor; beta = h(prod u/l) must fit min_j (allowance_j - bias_j); then the exact quotient of the surrogate. Declines when any
    incident view is not a plain table, when zero masks differ, or when the bias does not fit."""
    if all(a <= 0 for a in allowance): return False
    committed = []
    for var in range(C.n()):
        try: tick(C, quota, 'approx_quotient')
        except CompileStop as cs:
            if cs.kind == 'quota': break
            if committed: C.certs.append(dict(op='approx_quotient', steps=committed, interrupted=cs.kind))
            raise
        inc = [v for v in C.views if var in v.scope]
        if not inc or any(v.kind != 'table' for v in inc): continue
        d = C.cards[var]
        if d < 2: continue
        slices = {s: [(_slice(v, C.cards, var, s)) for v in inc] for s in range(d)}; C.work.entries += sum(len(sl) for s in slices for sl in slices[s])
        masks = {s: tuple(tuple(bool(x) for x in sl) for sl in slices[s]) for s in range(d)}
        remaining = min(allowance[j] - C.bias[j] for j in range(len(C.bias))) if C.bias else F(0)
        if remaining <= 0: break
        groups = []; pairs = 0; over = False
        for s in range(d):
            placed = False
            if C.work.total() >= quota: over = True; break                      # INNER quota (review CQR-06: 350,208 units were spent against a 50,000 quota)
            for g in groups:
                pairs += 1
                if pairs > d * d: break
                if C.work.total() >= quota: over = True; break
                r = g['rep']
                if masks[s] != masks[r]: continue
                # candidate: add s to g; compute the ratio bounds of the whole factor under the surrogate for the proposed grouping of this variable
                trial = [dict(gg) for gg in groups]; tg = trial[groups.index(g)]; tg['states'] = tg['states'] + [s]
                R, _ = _surrogate_ratio(C, var, inc, slices, trial)
                if R is None: continue
                beta = (R - 1) / (R + 3)
                if beta <= remaining: g['states'].append(s); placed = True; break
            if over: break
            if not placed: groups.append(dict(rep=s, states=[s]))
        if over: C.certs.append(dict(op='approx_quotient', declined='quota exhausted inside the pair scan of variable %d (nothing of this variable committed)' % var)); break
        if all(len(g['states']) == 1 for g in groups): continue
        R, bounds = _surrogate_ratio(C, var, inc, slices, groups); beta = (R - 1) / (R + 3)
        if beta > remaining: continue
        try: tick(C, None, 'approx_quotient')                                    # last consistent point before the surrogate is written
        except CompileStop as cs:
            if committed: C.certs.append(dict(op='approx_quotient', steps=committed, interrupted=cs.kind))
            raise
        if hook is not None: hook('approx', var, groups, slices, inc, R, beta)          # the checker recomputes R / beta on the exact pre-step slices
        # apply the surrogate to the incident factors: phi~(s, y) = c_a(s) phi(r, y) with c from the first common positive pivot
        for fi, v in enumerate(inc):
            scope = v.scope; k = scope.index(var); rest = [u for u in scope if u != var]
            for g in groups:
                r = g['rep']; sl_r = slices[r][fi]; piv_i = next(i for i, x in enumerate(sl_r) if x)
                for s in g['states']:
                    if s == r: continue
                    c = slices[s][fi][piv_i] / sl_r[piv_i]
                    for ri, xs in enumerate(product(*(range(C.cards[u]) for u in rest))):
                        x = dict(zip(rest, xs)); x[var] = s; i = 0
                        for u in scope: i = i * C.cards[u] + x[u]
                        v.values[i] = c * sl_r[ri]; C.work.ratops += 1
        for j in range(len(C.bias)): C.bias[j] += beta
        sig, inc2 = _signatures(C, var); classes = [sorted(g['states']) for g in groups]; classes.sort(key=lambda g: g[0])
        step = _quotient_commit(C, var, classes, sig, inc2, approx=dict(R=str(R), beta=str(beta), factor_bounds=[(str(l), str(u)) for l, u in bounds], groups=[g['states'] for g in groups]))
        committed.append(step)
    if committed: C.certs.append(dict(op='approx_quotient', steps=committed))
    return bool(committed)


def _surrogate_ratio(C, var, inc, slices, groups):
    """R = prod_a (u_a / l_a) with l_a, u_a the extrema of phi/phi~ over ALL positive entries of incident factor a under the grouping; None if a mask mismatch"""
    R = F(1); bounds = []
    for fi in range(len(inc)):
        lo = hi = None
        for g in groups:
            r = g['rep']; sl_r = slices[r][fi]; piv_i = next((i for i, x in enumerate(sl_r) if x), None)
            if piv_i is None: return None, None
            for s in g['states']:
                sl = slices[s][fi]
                if tuple(bool(x) for x in sl) != tuple(bool(x) for x in sl_r): return None, None
                c = sl[piv_i] / sl_r[piv_i]
                for a, b in zip(sl, sl_r):
                    if a:
                        rho = a / (c * b); C.work.ratops += 1
                        lo = rho if lo is None or rho < lo else lo; hi = rho if hi is None or rho > hi else hi
        bounds.append((lo, hi)); R *= hi / lo
    return R, bounds


# ======================================================================================================================
# operator A (symmetry): bounded proposer + generic verifier
# ======================================================================================================================
def symmetry(C, quota):
    """candidates: global complement on all-binary compiled models; per-variable state swap induced by the unary signature. Verifier: the action maps the MULTISET of
    table factors to itself (scope-wise, with reordered coordinates). For an involution tau, a query table with f(x) + f(tau x) = 2c everywhere becomes the constant c
    (recorded; published only with a positive-mass proof). Declines on affine views."""
    if any(v.kind != 'table' for v in C.views) or not C.views: return False
    cands = []
    if all(c == 2 for c in C.cards): cands.append(dict(name='global_complement', perm=list(range(C.n())), state_maps=[[1, 0]] * C.n()))
    for var in range(min(C.n(), 64)):
        if C.cards[var] == 2:
            maps = [[0, 1]] * C.n(); maps = list(maps); maps[var] = [1, 0]; cands.append(dict(name='swap_var_%d' % var, perm=list(range(C.n())), state_maps=maps))
    found = []
    for cand in cands:
        if C.work.total() >= quota: break
        try: tick(C, quota, 'symmetry')                               # service / deadline / quota inside the candidate scan (review CQR-06)
        except CompileStop as cs:
            if cs.kind == 'quota': break
            raise
        if verify_symmetry_action(C.cards, C.views, cand, C.work):
            consts = {}
            for qi, q in enumerate(C.queries):
                if q['kind'] != 'expectation': continue
                c = _query_symmetric_constant(C.cards, q['f'], cand, C.work)
                if c is not None: consts[qi] = c
            if consts:
                found.append(dict(action=cand, constants={str(k): str(v) for k, v in consts.items()}))
                for qi, c in consts.items(): C.constant_queries[qi] = c
    if found: C.certs.append(dict(op='symmetry', actions=found))
    return bool(found)


def _apply_action(cand, x):
    y = [None] * len(x)
    for v, s in enumerate(x): y[cand['perm'][v]] = cand['state_maps'][v][s]
    return y


def verify_symmetry_action(cards, views, cand, work):
    """the action maps every table factor to a table factor of the multiset (as functions)"""
    perm = cand['perm']
    if sorted(perm) != list(range(len(cards))): return False
    if any(cards[perm[v]] != cards[v] or sorted(cand['state_maps'][v]) != list(range(cards[v])) for v in range(len(cards))): return False
    used = [False] * len(views)
    for v in views:
        img_scope = tuple(perm[u] for u in v.scope); match = None
        for i, w in enumerate(views):
            if used[i] or set(w.scope) != set(img_scope) or len(w.values) != len(v.values): continue
            ok = True
            for xs in product(*(range(cards[u]) for u in v.scope)):
                x = {u: s for u, s in zip(v.scope, xs)}; y = {perm[u]: cand['state_maps'][u][s] for u, s in x.items()}
                work.entries += 2
                if v.at(cards, x) != w.at(cards, y): ok = False; break
            if ok: match = i; break
        if match is None: return False
        used[match] = True
    return True


def _query_symmetric_constant(cards, f, cand, work):
    """c such that f(x) + f(tau x) = 2c for every x (tau an involution on f's scope); None otherwise"""
    perm = cand['perm']
    if any(perm[u] not in f.scope for u in f.scope): return None
    c = None
    for xs in product(*(range(cards[u]) for u in f.scope)):
        x = dict(zip(f.scope, xs)); y = {perm[u]: cand['state_maps'][u][s] for u, s in x.items()}; z = {perm[u]: cand['state_maps'][u][s] for u, s in y.items()}
        if z != x: return None
        s = (f.at(cards, x) + f.at(cards, y)) / 2; work.entries += 2
        if c is None: c = s
        elif s != c: return None
    return c


# ======================================================================================================================
# operator E: concentration certificate and influence deletion
# ======================================================================================================================
def _unary_product_argmax(C, var):
    best = None; bw = None
    for s in range(C.cards[var]):
        w = F(1)
        for v in C.views:
            if v.kind == 'table' and v.scope == (var,): w *= v.values[s]; C.work.entries += 1
        if bw is None or w > bw: bw = w; best = s
    return best


def concentration(C, quota, allowance):
    """reduction note §4: propose x* (unary argmax), compute per-site ratio sums R_i from local ratio inequalities over every incident factor (zeros handled: 0/0 no
    constraint, pos/0 = infinity, all-zero bad slice = 0), t_i = R_i / (1 + R_i); certify |E f_j - f_j(x*)| <= sum_{i in scope(f_j)} t_i; accept only when it fits
    every query's remaining allowance. Returns the direct answer record or None."""
    if any(v.kind != 'table' for v in C.views) or any(q['kind'] != 'expectation' for q in C.queries) or not C.queries: return None
    if all(a <= 0 for a in allowance): return None
    xstar = {var: _unary_product_argmax(C, var) for var in range(C.n())}
    wst = F(1)
    for v in C.views: wst *= v.at(C.cards, xstar); C.work.evals += 1
    if wst == 0: C.certs.append(dict(op='concentration', declined='proposed assignment has zero weight (no positive witness)')); return None
    C.witness = dict(xstar)
    t = {}
    for var in range(C.n()):
        try: tick(C, quota, 'concentration')
        except CompileStop as cs:
            if cs.kind == 'quota': C.certs.append(dict(op='concentration', declined='quota exhausted during the ratio scans')); return None
            raise
        Ri = F(0); inf = False
        for s in range(C.cards[var]):
            if s == xstar[var]: continue
            r = F(1); zero_bound = False
            for v in C.views:
                if var not in v.scope: continue
                sl_s = _slice(v, C.cards, var, s); sl_r = _slice(v, C.cards, var, xstar[var]); C.work.entries += 2 * len(sl_s)
                bound = F(0); has_pos = False
                for a, b in zip(sl_s, sl_r):
                    if a == 0: continue
                    has_pos = True
                    if b == 0: bound = None; break
                    bound = max(bound, a / b)
                if not has_pos: r = F(0); zero_bound = True; break
                if bound is None: r = None; break
                r *= bound
            if zero_bound: continue
            if r is None: inf = True; break
            Ri += r
        t[var] = F(1) if inf else Ri / (1 + Ri)
    answers = {}; biases = {}
    for qi, q in enumerate(C.queries):
        b = min(F(1), sum(t[u] for u in q['f'].scope)) if q['f'].scope else F(0)
        if b > allowance[qi] - C.bias[qi]: C.certs.append(dict(op='concentration', declined='bias %s exceeds the allowance of query %d' % (b, qi), t={str(k): str(v) for k, v in t.items()})); return None
        answers[qi] = q['f'].at(C.cards, xstar); biases[qi] = b
    rec = dict(op='concentration', xstar={str(k): v for k, v in xstar.items()}, weight=str(wst), t={str(k): str(v) for k, v in t.items()}, answers={str(k): str(v) for k, v in answers.items()}, bias={str(k): str(v) for k, v in biases.items()}, query_scopes={str(qi): list(q['f'].scope) for qi, q in enumerate(C.queries)})
    for qi, b in biases.items(): C.bias[qi] += b                 # the certified bias is SPENT in the ledger (the publication is widened by it; tau shrinks)
    C.certs.append(rec); return dict(answers=answers, bias=biases, record=rec)


def _h(R): return (R - 1) / (R + 3)


def influence_deletion(C, quota, allowance, neumann_T=8):
    """reduction note §3: strictly positive table factors only (zeros decline); Cbar_ij = min(1, sum_a h(R_aij)); D_ai; alpha = max_i sum_j Cbar_ij < 1 required;
    deletion set: all non-unary factors first, then greedy by decreasing size; e = Neumann sum + tail; beta_j = sum_{i in scope(f_j)} e_i; accepted only within the allowance"""
    if any(v.kind != 'table' for v in C.views) or any(q['kind'] != 'expectation' for q in C.queries): return False
    if all(a <= 0 for a in allowance): return False
    if any(x <= 0 for v in C.views for x in v.values): C.certs.append(dict(op='influence_deletion', declined='hard zeros remain: the strictly positive comparison operator does not apply')); return False
    n = C.n(); Cbar = {}; Dai = {}            # SPARSE: Cbar[i][j] exists only for pairs sharing a factor (no dense n x n table)
    def cb(i, j): return Cbar.get(i, {}).get(j, F(0))
    for fi, v in enumerate(C.views):
        if len(v.scope) < 1: continue
        try: tick(C, quota, 'influence_deletion')
        except CompileStop as cs:
            if cs.kind == 'quota': C.certs.append(dict(op='influence_deletion', declined='quota exhausted during the local scans')); return False
            raise
        sc = v.scope
        for i in sc:
            try: tick(C, quota, 'influence_deletion')                 # quota / deadline / service INSIDE the costly per-site scans (review CQR-06: 32-state factors cost 2^16 units each)
            except CompileStop as cs:
                if cs.kind == 'quota': C.certs.append(dict(op='influence_deletion', declined='quota exhausted during the local scans')); return False
                raise
            rest = [u for u in sc if u != i]; best = F(1)
            for xs in product(*(range(C.cards[u]) for u in rest)):
                try: tick(C, quota, 'influence_deletion')
                except CompileStop as cs:
                    if cs.kind == 'quota': C.certs.append(dict(op='influence_deletion', declined='quota exhausted during the local scans')); return False
                    raise
                x = dict(zip(rest, xs)); vals = []
                for s_ in range(C.cards[i]): x[i] = s_; vals.append(v.at(C.cards, x)); C.work.entries += 1
                best = max(best, max(vals) / min(vals))
            Dai[(fi, i)] = best
            for j in sc:
                if j == i: continue
                try: tick(C, quota, 'influence_deletion')
                except CompileStop as cs:
                    if cs.kind == 'quota': C.certs.append(dict(op='influence_deletion', declined='quota exhausted during the local scans')); return False
                    raise
                rest2 = [u for u in sc if u not in (i, j)]; Rmax = F(1)
                for xs in product(*(range(C.cards[u]) for u in rest2)):
                    x = dict(zip(rest2, xs))
                    for u_ in range(C.cards[i]):
                        try: tick(C, quota, 'influence_deletion')         # innermost granularity: one row of state pairs (<= 2 * card_i * card_j entries)
                        except CompileStop as cs:
                            if cs.kind == 'quota': C.certs.append(dict(op='influence_deletion', declined='quota exhausted during the local scans')); return False
                            raise
                        for v_ in range(u_ + 1, C.cards[i]):
                            qs = []
                            for s_ in range(C.cards[j]):
                                x[i] = u_; x[j] = s_; a = v.at(C.cards, x); x[i] = v_; b = v.at(C.cards, x); qs.append(a / b); C.work.entries += 2
                            Rmax = max(Rmax, max(qs) / min(qs))
                Cbar.setdefault(i, {})[j] = min(F(1), cb(i, j) + _h(Rmax))
        if C.work.total() >= quota: C.certs.append(dict(op='influence_deletion', declined='quota exhausted during the local scans')); return False
    alpha = max((sum(row.values()) for row in Cbar.values()), default=F(0))
    if alpha >= 1: C.certs.append(dict(op='influence_deletion', declined='alpha = %s >= 1: the contraction condition fails (not a statement about the model)' % alpha)); return False
    sites = sorted({i for v in C.views for i in v.scope})
    def bias_of(dset):
        bbar = {i: min(F(1), sum(_h(Dai[(fi, i)]) for fi in dset if i in C.views[fi].scope)) for i in sites}
        e = {i: F(0) for i in sites}; term = dict(bbar)
        for _ in range(neumann_T):
            for i in sites: e[i] += term[i]
            term = {i: sum(cij * term[j] for j, cij in Cbar.get(i, {}).items()) for i in sites}
        tail = (alpha ** neumann_T) * (max(bbar.values()) if bbar else F(0)) / (1 - alpha)
        e = {i: x + tail for i, x in e.items()}
        return [min(F(1), sum(e.get(u, F(0)) for u in q['f'].scope)) for q in C.queries], e, bbar
    nonunary = [fi for fi, v in enumerate(C.views) if len(v.scope) >= 2]
    if not nonunary: return False
    chosen = None
    b_all, e_all, bb_all = bias_of(set(nonunary))
    if all(b_all[j] <= allowance[j] - C.bias[j] for j in range(len(C.queries))): chosen = set(nonunary); bias = b_all; e = e_all
    else:
        D = set(); cur = [F(0)] * len(C.queries)
        for fi in sorted(nonunary, key=lambda i: (-C.views[i].size(), i)):
            b, e_, _ = bias_of(D | {fi})
            if all(b[j] <= allowance[j] - C.bias[j] for j in range(len(C.queries))): D.add(fi); cur = b; e = e_
        if D: chosen = D; bias = cur
    if not chosen: C.certs.append(dict(op='influence_deletion', declined='no deletion set fits the allowance (alpha %s)' % alpha)); return False
    for j in range(len(C.queries)): C.bias[j] += bias[j]
    C.views = [v for fi, v in enumerate(C.views) if fi not in chosen]
    C.certs.append(dict(op='influence_deletion', deleted=sorted(chosen), alpha=str(alpha), bias=[str(b) for b in bias], e={str(i): str(x) for i, x in e.items()}, neumann_T=neumann_T, sparse_pairs=sum(len(r) for r in Cbar.values())))
    return True


# ======================================================================================================================
# operator D: affine support (local recognizer, global elimination, compact views, query pullback)
# ======================================================================================================================
def local_affine(view, cards, work):
    """for an all-binary table view: positive rows R; affine iff |R| == 2^rank(differences); returns (equations as (rowmask over view.scope bits, rhs)) or None"""
    k = len(view.scope)
    if any(cards[u] != 2 for u in view.scope) or k == 0: return None
    rows = []
    for i, w in enumerate(view.values):
        work.entries += 1
        if w > 0: rows.append(i)        # row index i = bits of the scope in row-major order (first scope var = most significant bit)
    if not rows: raise ZeroEvidence(dict(kind='table_with_no_positive_entry'))
    r0 = rows[0]; rank, basis = gf2_rank_basis([r ^ r0 for r in rows])
    if len(rows) != 1 << rank: return None
    if rank == k: return []             # full support: no equation
    # orthogonal complement of span(basis) in GF(2)^k: solve H b = 0 for basis vectors
    comp = []
    for cand in range(1, 1 << k):
        if all(bin(cand & b).count('1') % 2 == 0 for b in basis):
            red = gf2_reduce(cand, comp)
            if red: comp.append(red); comp.sort(reverse=True)
        if len(comp) == k - rank: break
    eqs = [(h, bin(h & r0).count('1') % 2) for h in comp]
    return eqs


def affine(C, quota):
    """collect local equations over the compiled BINARY variables; eliminate globally; inconsistency => ZERO_EVIDENCE; otherwise x_bin = c + B z with pivot-free z;
    rewrite every factor / query touching the binary block into an affine view (y = U z); decoder: original binary states = c_i XOR B_i z. Applied once; declines if no
    nontrivial equation or if any view is already affine."""
    if C.affine_done or any(v.kind != 'table' for v in C.views): return False
    bin_vars = [v for v in range(C.n()) if C.cards[v] == 2]
    if not bin_vars: return False
    pos = {v: i for i, v in enumerate(bin_vars)}; nb = len(bin_vars); eqs = []; local = []
    for fi, v in enumerate(C.views):
        if C.work.total() >= quota: break
        try: tick(C, quota, 'affine')
        except CompileStop as cs:
            if cs.kind == 'quota': break
            raise
        if not all(C.cards[u] == 2 for u in v.scope): continue
        le = local_affine(v, C.cards, C.work)
        if not le: continue
        local.append(dict(factor=fi, equations=[(h, b) for h, b in le]))
        for h, b in le:
            row = 0
            for bit in range(len(v.scope)):
                if (h >> (len(v.scope) - 1 - bit)) & 1: row |= 1 << pos[v.scope[bit]]
            eqs.append((row, b))
    if not eqs: return False
    # Gaussian elimination over GF(2) on augmented rows (bit nb = rhs)
    aug = [(r | (b << nb)) for r, b in eqs]; basis = []
    for r in aug:
        for bb in basis:
            if (r ^ bb) & ((1 << nb) - 1) < r & ((1 << nb) - 1) or ((r ^ bb) & ((1 << nb) - 1)) == (r & ((1 << nb) - 1)) and (r ^ bb) < r: r ^= bb
        rr = r & ((1 << nb) - 1)
        if rr == 0:
            if r >> nb: raise ZeroEvidence(dict(kind='inconsistent_affine_equations', equations=len(eqs)))
            continue
        basis.append(r); basis.sort(reverse=True)
    # reduced echelon: pivots = highest bit of each basis row
    basis = _rref(basis, nb); pivots = [(_msb(r & ((1 << nb) - 1))) for r in basis]; free_bits = [i for i in range(nb) if i not in pivots]
    rank = len(basis)
    if rank == 0: return False
    # parametrization: x_i = c_i + sum_{z} B_{i z} z over free bits; free bit i -> z coordinate index
    zidx = {fb: k for k, fb in enumerate(free_bits)}; crow = {}; Brow = {}
    for i in range(nb):
        if i in zidx: crow[i] = 0; Brow[i] = 1 << zidx[i]
    for r in basis:
        pv = _msb(r & ((1 << nb) - 1)); rhs = r >> nb; others = (r & ((1 << nb) - 1)) & ~(1 << pv); brow = 0
        for fb in free_bits:
            if (others >> fb) & 1: brow |= 1 << zidx[fb]
        crow[pv] = rhs; Brow[pv] = brow
    # new compiled variables: z coordinates (binary) + categorical (nonbinary) in canonical order
    cat_vars = [v for v in range(C.n()) if C.cards[v] != 2]; newcards = [2] * len(free_bits) + [C.cards[v] for v in cat_vars]; cat_new = {v: len(free_bits) + i for i, v in enumerate(cat_vars)}
    def make_view(v):
        bin_in = [u for u in v.scope if C.cards[u] == 2]; cat_in = [u for u in v.scope if C.cards[u] != 2]
        if not bin_in: return View('table', tuple(cat_new[u] for u in v.scope), list(v.values))
        rows = [Brow[pos[u]] for u in bin_in]; rank_u, ub = gf2_rank_basis(rows)
        # U rows = ub (rank rho rows over z); T maps each bin var's B-row to its coordinates in the ub basis: express B_u = sum T_uk ub_k
        coords = []
        for r in rows:
            coord = 0; x = r
            for k, bvec in enumerate(ub):
                if x ^ bvec < x: x ^= bvec; coord |= 1 << k
            assert x == 0; coords.append(coord)
        zcols = sorted({k for bvec in ub for k in range(len(free_bits)) if (bvec >> k) & 1})
        ub_local = []
        for bvec in ub:
            loc = 0
            for kk, zc in enumerate(zcols):
                if (bvec >> zc) & 1: loc |= 1 << kk
            ub_local.append(loc)
        # g(y, cat): for each y (rho bits, as a tuple y_0..y_{rho-1} with y_k = coefficient of ub_k) and cat assignment: x_u = c_u XOR <coords_u, y>
        rho = len(ub); vals = []
        for yb in product((0, 1), repeat=rho):
            for cs in product(*(range(C.cards[u]) for u in cat_in)):
                x = dict(zip(cat_in, cs))
                for ui, u in enumerate(bin_in):
                    bit = crow[pos[u]]
                    for k in range(rho):
                        if (coords[ui] >> k) & 1 and yb[k]: bit ^= 1
                    x[u] = bit
                vals.append(v.at(C.cards, x)); C.work.entries += 1
        # urows as rows over the LOCAL zcols; the View indexes y as y_0 most significant -> urows[0] is y_0 = ub_0
        return View('affine', tuple(zcols) + tuple(cat_new[u] for u in cat_in), vals, cat_scope=tuple(cat_new[u] for u in cat_in), zcols=tuple(zcols), urows=ub_local)
    new_views = [make_view(v) for v in C.views]
    for q in C.queries:
        if q['kind'] == 'expectation': q['f'] = make_view(q['f'])
        else: q['h'] = make_view(q['h']); q['g'] = make_view(q['g'])
    # constant affine views (rank 0, no cat): scalars
    keep = []
    for v in new_views:
        if not v.scope:
            if v.values[0] == 0: raise ZeroEvidence(dict(kind='affine_image_zero'))
            C.scalars.append(dict(kind='affine_constant_factor', value=str(v.values[0])))
        else: keep.append(v)
    C.views = keep
    # decoder
    for d in C.decoder:
        if d['kind'] == 'map':
            var = d['var']
            if C.cards[var] == 2:
                sts = d['states']; b = Brow[pos[var]]; zv = [k for k in range(len(free_bits)) if (b >> k) & 1]
                d.clear(); d.update(kind='affine_map', c=crow[pos[var]], zvars=zv, states={k: lst for k, lst in sts.items()})
            else: d['var'] = cat_new[var]
    C.cards = newcards; C.affine_done = True
    C.certs.append(dict(op='affine', local=local, rank=rank, binary_variables=bin_vars, free_bits=free_bits, c={str(i): crow[i] for i in range(nb)}, B={str(i): Brow[i] for i in range(nb)}))
    return True


def _msb(x): return x.bit_length() - 1
def _rref(basis, nb):
    basis = sorted(basis, reverse=True); out = []
    for r in basis:
        for o in out:
            pv = _msb(o & ((1 << nb) - 1))
            if (r >> pv) & 1: r ^= o
        if r & ((1 << nb) - 1): out.append(r)
    # back-substitute
    out.sort(reverse=True)
    for i in range(len(out)):
        pv = _msb(out[i] & ((1 << nb) - 1))
        for j in range(len(out)):
            if j != i and (out[j] >> pv) & 1: out[j] ^= out[i]
    return sorted(out, reverse=True)


# ======================================================================================================================
# the compile driver (reference policy order) and the independent verifiers used by the checker
# ======================================================================================================================
def quota_for(task):
    m = task['model']; ent = sum(len(f['values']) for f in m['factors']) + sum((len(q.f.values) if q.kind == 'expectation' else len(q.h.values) + len(q.g.values)) for q in task['queries'])
    return max(50_000, 8 * ent)


NORMALIZER_FORBIDDEN = ('component_omission', 'approx_quotient', 'influence_deletion', 'concentration')      # TV-only / unknown-scalar / normalized-only rewrites (manuscript §9)


def effective_operators(arm_enabled, task):
    """the ONE task-effective operator policy shared by the producer and the checker (review CQR-08): the arm's set minus the rewrites a normalizer task forbids"""
    en = set(arm_enabled)
    if (task.get('query_spec') or {}).get('normalizer_task'): en -= set(NORMALIZER_FORBIDDEN)
    return en


def _save_state(C):
    """the committed compiled model (every field an operator may change); views / queries / decoder entries are replaced, never mutated in place, by the operators (list copies suffice)"""
    import copy as _copy
    return dict(cards=list(C.cards), views=list(C.views), queries=list(C.queries), decoder=_copy.deepcopy(C.decoder), bias=list(C.bias), certs=list(C.certs), scalars=list(C.scalars),
                constant_scalars=list(C.constant_scalars), witness=_copy.deepcopy(C.witness), affine_done=C.affine_done, constant_queries=dict(C.constant_queries))
def _restore_state(C, s):
    C.cards = s['cards']; C.views = s['views']; C.queries = s['queries']; C.decoder = s['decoder']; C.bias = s['bias']; C.certs = s['certs']; C.scalars = s['scalars']
    C.constant_scalars = s['constant_scalars']; C.witness = s['witness']; C.affine_done = s['affine_done']; C.constant_queries = s['constant_queries']


def compile_task(task, enabled=None, deadline=None, work=None, service=None, fault=None):
    """returns (Compiled, log). `enabled` = the TASK-EFFECTIVE operator set (effective_operators); every other operator records 'disabled'. `service(op)` is called at every
    consistent point (review CQR-06): it may raise CompileStop('deadline' | 'reference_done' | 'cancelled'); the driver then returns the LAST COMMITTED model with
    log['interrupted'] set and every charge preserved. A quota exhaustion inside an operator makes that operator decline the rest (its commits stay)."""
    enabled = set(POLICY['order']) if enabled is None else set(enabled); t0 = time.monotonic(); C = from_task(task, work)
    D = quota_for(task); allowance = [(task['epsilon'] / 4 if task['mode'] != 'EXACT_RATIONAL' else F(0))] * len(task['queries']); log = dict(quota=D, steps=[], direct=None, interrupted=None, failed=None)
    def q_(k): return C.work.total() + D if k == 'exact_quotient_pass' else C.work.total() + D
    def svc(op):
        if deadline is not None and time.monotonic() >= deadline: raise CompileStop('deadline', op)
        if service is not None: service(op)
    C.service = svc
    def step(name, fn):
        if log['interrupted']: log['steps'].append(dict(op=name, skipped='interrupted')); return False
        if deadline is not None and time.monotonic() >= deadline: log['steps'].append(dict(op=name, skipped='deadline')); return False
        if name not in enabled: log['steps'].append(dict(op=name, disabled=True)); return False
        if log.get('failed'): log['steps'].append(dict(op=name, skipped='optional_failure')); return False
        w0 = C.work.total(); m0 = C.measure(); saved = _save_state(C)
        try:
            if fault == name: raise RuntimeError('INJECTED optional fault in %s (qualification control; never a production run)' % name)      # an optional failure: NOT a CompileStop
            r = fn()
        except CompileStop as cs:
            log['steps'].append(dict(op=name, interrupted=cs.kind, work=C.work.total() - w0, measure_before=m0, measure_after=C.measure())); log['interrupted'] = dict(op=name, kind=cs.kind); return False
        except (ZeroEvidence, MemoryError): raise
        except Exception as ex:
            # an OPTIONAL FAILURE inside one operator: the transaction is rolled back to the LAST COMMITTED model (its certificates and bias ledger intact), every unit spent stays charged,
            # the failure is recorded, and no later operator runs; the caller publishes from the committed model or lets the protected reference finish
            _restore_state(C, saved); log['steps'].append(dict(op=name, failed='%s: %s' % (type(ex).__name__, str(ex)[:160]), work=C.work.total() - w0, measure_before=m0, measure_after=C.measure()))
            log['failed'] = dict(op=name, error='%s: %s' % (type(ex).__name__, str(ex)[:160])); return False
        log['steps'].append(dict(op=name, committed=bool(r), work=C.work.total() - w0, measure_before=m0, measure_after=C.measure())); return r
    step('support_fixpoint', lambda: support_fixpoint(C, q_('support')))
    step('fixed_substitution', lambda: fixed_substitution(C))
    step('leaf_sumout', lambda: leaf_sumout(C, q_('leaf')))
    step('component_omission', lambda: component_omission(C))
    # the exact quotient pass gets its own share; support / fixed may re-apply after it (domains shrink)
    if step('exact_quotient_pass', lambda: exact_quotient_pass(C, q_('exact_quotient_pass'))):
        step('fixed_substitution', lambda: fixed_substitution(C)); step('leaf_sumout', lambda: leaf_sumout(C, q_('leaf')))
    step('symmetry', lambda: symmetry(C, q_('symmetry')))
    if task['mode'] != 'EXACT_RATIONAL':
        if step('approx_quotient', lambda: approx_quotient(C, q_('approx'), allowance)): step('fixed_substitution', lambda: fixed_substitution(C))
        direct = [None]
        def _conc():
            direct[0] = concentration(C, q_('conc'), allowance); return direct[0] is not None
        step('concentration', _conc)                      # under the SAME deadline / interruption wrapper as every other operator (review CQR-06)
        log['direct'] = direct[0]
        if direct[0] is None: step('influence_deletion', lambda: influence_deletion(C, q_('infl'), allowance))
        if direct[0] is None: step('leaf_sumout', lambda: leaf_sumout(C, q_('leaf')))
    else:
        for name in ('approx_quotient', 'concentration', 'influence_deletion'): log['steps'].append(dict(op=name, disabled='EXACT_RATIONAL mode'))
    step('affine', lambda: affine(C, q_('affine')))
    C.service = None                                           # the hook is released with the task (the certificate serializer never sees it)
    log['wall_s'] = time.monotonic() - t0; log['work'] = C.work.snapshot(); log['final_measure'] = C.measure(); log['bias'] = [str(b) for b in C.bias]
    return C, log


# ---------------------------------------------------------------------------------------------------------------- verifiers (independent of the proposers)
def verify_quotient_step(cards_before, views_before, step, work):
    """cross-multiplication check of the proportional identities for a recorded quotient step on the model BEFORE the step: for every incident factor and every class,
    phi(s, y) * pivot(r) == phi(r, y) * pivot(s) for all y; kappa / S recomputed and compared"""
    var = step['var']; classes = step['classes']; inc = [views_before[i] for i in step['incident_factors']]
    if not inc and any(var in v.scope for v in views_before): return 'factor-less quotient recorded for a variable with incident factors'
    kappa = {}
    for g in classes:
        r = g[0]
        for s in g:
            k = F(1)
            for v in inc:
                sl_s = _slice(v, cards_before, var, s); sl_r = _slice(v, cards_before, var, r); work.entries += 2 * len(sl_s)
                ps = next((x for x in sl_s if x), None); pr = next((x for x in sl_r if x), None)
                if ps is None or pr is None: return 'zero slice in a quotient class'
                for a, b in zip(sl_s, sl_r):
                    if a * pr != b * ps: return 'proportionality fails for var %d states %d/%d' % (var, s, r)
                k *= ps / pr
            kappa[s] = k
    for s, k in kappa.items():
        if F(step['kappa'][str(s)]) != k: return 'kappa differs for state %d' % s
    for ci, g in enumerate(classes):
        if F(step['S'][ci]) != sum(kappa[s] for s in g): return 'S differs for class %d' % ci
    return None


def verify_affine_record(cards_before, views_before, rec, work):
    """re-derive the local equations of every listed factor (|R| == 2^rank), check Hx = b on every positive row, and that c, B satisfy every equation"""
    pos = {v: i for i, v in enumerate(rec['binary_variables'])}; nb = len(pos)
    for loc in rec['local']:
        v = views_before[loc['factor']]; le = local_affine(v, cards_before, work)
        if le is None or sorted(le) != sorted(tuple(e) for e in loc['equations']): return 'local affine equations of factor %d do not re-derive' % loc['factor']
        for i, w in enumerate(v.values):
            if w > 0:
                for h, b in le:
                    if bin(h & i).count('1') % 2 != b: return 'positive row violates a local equation'
    # c + B z satisfies every local equation for all z: H c = b and H B = 0 (checked via the free-bit parametrization)
    for loc in rec['local']:
        v = views_before[loc['factor']]
        for h, b in loc['equations']:
            cbit = 0; brow = 0
            for bit in range(len(v.scope)):
                if (h >> (len(v.scope) - 1 - bit)) & 1:
                    u = v.scope[bit]; cbit ^= int(rec['c'][str(pos[u])]); brow ^= int(rec['B'][str(pos[u])])
            if cbit != b or brow != 0: return 'global parametrization violates a local equation of factor %d' % loc['factor']
    return None
