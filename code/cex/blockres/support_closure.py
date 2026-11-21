"""EXACT SUPPORT CLOSURE (round 18, 21 Nov 2026): compile the exact support of a finite nonnegative rational factor model BEFORE the block-contraction engine chooses its
partition. Three exact operations, repeated to a fixed point, with a decoder from the reduced variables back to every original one:

  support propagation   delete a state of a variable only when some incident factor has NO positive row with that state whose other states are still in their domains
                        (generalized arc consistency; Mackworth 1977). Every globally positive assignment supplies a supporting row in every factor, so deletions preserve
                        every positive assignment; an EMPTY support is exact zero evidence; a nonempty closure proves nothing about positivity.
  bijection quotient    recognise a pair (u, v) of a factor's scope as aliased only when the factor's complete positive pair projection is the graph of a bijection between the
                        FULL current domains; on positive support v = pi(u) in every such row (the factor is a product term). Compose all recognised bijections into components
                        with one representative and explicit state permutations; a cycle on which two composed maps disagree deletes those representative states (such states
                        have no positive completion). Substitute the maps into every factor occurrence, diagonalising two scope variables that share a representative and
                        dropping rows inconsistent with the maps (weight zero globally); a factor whose reduced table is constant over its full reduced domain is multiplied
                        into an exact positive scalar c and dropped; weighted relations keep their weights. Duplicate occurrences are never merged.
  decoder               every original variable is a fixed value, or a state of one representative under an explicit permutation; original positive assignments correspond
                        one-to-one with reduced positive assignments, with w(D(y)) = c w'(y), so Z = c Z' and every singleton numerator N_j = c sum_y w'(y) f_j(D(y)).

The functions `gac` and `quotient` keep the signatures of the research prototype (R18 packet, constraint_diagnostic.py) so its independent exhaustive checker runs against this
module unchanged. Bounds: one deadline (polled per factor pass) and one live-byte ceiling (a conservative object-count estimate of rows, domains, maps and the rewritten
model), both raising ClosureRefused so the caller falls back to the ORIGINAL model after charging the spent time; exact zero evidence raises ZeroEvidence."""
import sys, time
from fractions import Fraction as F
from itertools import product, combinations
from collections import deque
from math import prod, inf


class ClosureRefused(Exception): pass      # resource / deadline: the caller continues with the original model (typed, charged)
class ZeroEvidence(ValueError): pass        # exact: no positive assignment exists


def tnow(): return time.monotonic()


def rows_from_model(model, deadline=inf):
    """evidence-restricted domains and the POSITIVE rows of every factor occurrence as {assignment tuple (original states): exact Fraction}; the deadline is polled per factor"""
    cards = model['cards']; ev = model.get('evidence', {})
    domains = {v: ({ev[v]} if v in ev else set(range(c))) for v, c in enumerate(cards)}
    fs = []
    for f in model['factors']:
        if tnow() >= deadline: raise ClosureRefused('deadline while materialising the support rows')
        sc = tuple(f['scope']); vals = f['values']
        if len(sc) != len(set(sc)): raise ValueError('malformed scope %r' % (sc,))
        rows = {}
        for a, x in zip(product(*(range(cards[v]) for v in sc)), vals):
            x = F(x)
            if x < 0: raise ValueError('negative factor value')
            if x: rows[a] = x
        fs.append((sc, rows))
    return domains, fs


def _bytes_estimate(domains, fs, decoders=None):
    """conservative count-based estimate of the live workspace: tuple + Fraction + dict slot per stored row, set entries per domain state, map entries per decoder"""
    b = 0
    for sc, rows in fs: b += len(rows) * (56 + 8 * len(sc) + 2 * 28 + 104) + 120
    for v, d in domains.items(): b += 216 + 32 * len(d)
    if decoders:
        for v, (r, m) in decoders.items(): b += 240 + 72 * len(m)
    return b


def gac(domains, fs, deadline=inf):
    """generalized arc consistency to a fixed point: returns (restricted rows, stats); raises ZeroEvidence on an empty support"""
    rounds = 0; deleted = 0
    while True:
        rounds += 1; change = False; new = []
        for sc, rows in fs:
            if tnow() >= deadline: raise ClosureRefused('deadline during support propagation (round %d)' % rounds)
            rs = {a: w for a, w in rows.items() if all(x in domains[v] for v, x in zip(sc, a))}
            if not rs: raise ZeroEvidence('a factor occurrence has no positive row inside the current domains (scope %r)' % (sc,))
            for k, v in enumerate(sc):
                d = {a[k] for a in rs}; old = domains[v]
                if d != old:
                    assert d <= old; deleted += len(old) - len(d); domains[v] = d; change = True
            new.append((sc, rs))
        fs = new
        if not change: return fs, dict(rounds=rounds, deleted_states=deleted)


def quotient(domains, fs, detect_bijections=True, deadline=inf):
    """one batch of bijection recognition + composition + substitution: returns (new domains over the representatives, new rows, maps {var: (rep, {rep state: var state})}, stats)"""
    edges = {v: [] for v in domains}; edge_count = 0
    if detect_bijections:
        for fi, (sc, rs) in enumerate(fs):
            if tnow() >= deadline: raise ClosureRefused('deadline during bijection recognition')
            for i, j in combinations(range(len(sc)), 2):
                u, v = sc[i], sc[j]
                if len(domains[u]) < 2 or len(domains[u]) != len(domains[v]): continue
                ps = {(a[i], a[j]) for a in rs}
                if len(ps) != len(domains[u]): continue
                uv = dict(ps); vu = {b: a for a, b in ps}
                if len(uv) != len(ps) or len(vu) != len(ps): continue
                assert set(uv) == domains[u] and set(vu) == domains[v]                       # n distinct keys inside a domain of size n: the projection IS a bijection of the full domains
                edges[u].append((v, uv)); edges[v].append((u, vu)); edge_count += 1
    maps = {}; newdomains = {}; cycle_removed = 0; comp_sizes = []
    for r in domains:
        if r in maps: continue
        if len(domains[r]) == 1: maps[r] = (None, {None: next(iter(domains[r]))}); continue
        rm = {r: {x: x for x in domains[r]}}; todo = deque([r]); valid = set(domains[r])
        while todo:
            u = todo.popleft()
            for v, uv in edges[u]:
                mv = {x: uv[y] for x, y in rm[u].items()}
                if v in rm: valid = {x for x in valid if rm[v][x] == mv[x]}
                else: rm[v] = mv; todo.append(v)
        if not valid: raise ZeroEvidence('inconsistent bijection cycle: no representative state survives')
        cycle_removed += len(domains[r]) - len(valid); newdomains[r] = valid; comp_sizes.append(len(rm))
        for v, m in rm.items(): maps[v] = (r, {x: m[x] for x in valid})
    newfs = []; constants = []; collapsed_rows = 0; local_checked = 0
    for sc, rs in fs:
        if tnow() >= deadline: raise ClosureRefused('deadline during substitution')
        ns = tuple(sorted({maps[v][0] for v in sc if maps[v][0] is not None})); rev = {v: {a: b for b, a in maps[v][1].items()} for v in sc}; nrs = {}
        for a, w in rs.items():
            assignment = {}; ok = True
            for v, x in zip(sc, a):
                r, _ = maps[v]
                if x not in rev[v]: ok = False; break
                y = rev[v][x]
                if r is None: continue
                if r in assignment and assignment[r] != y: ok = False; break
                assignment[r] = y
            if ok:
                na = tuple(assignment[r] for r in ns); assert na not in nrs; nrs[na] = w
        if not nrs: raise ZeroEvidence('a factor occurrence has no positive row after substitution (scope %r)' % (sc,))
        collapsed_rows += len(rs) - len(nrs)
        for na in product(*(sorted(newdomains[v]) for v in ns)):                                 # exact entrywise check of the substituted table against the source table through the maps (incl. zeros)
            ra = dict(zip(ns, na)); olda = tuple(maps[v][1][ra[maps[v][0]]] if maps[v][0] is not None else maps[v][1][None] for v in sc)
            assert nrs.get(na, F(0)) == rs.get(olda, F(0)), (sc, ns, na); local_checked += 1
        if len(nrs) == prod(len(newdomains[v]) for v in ns) and len(set(nrs.values())) == 1: constants.append(next(iter(nrs.values())))
        else: newfs.append((ns, nrs))
    return newdomains, newfs, maps, dict(bijection_relations=edge_count, nontrivial_components=sorted([n for n in comp_sizes if n > 1], reverse=True), constant_factors=len(constants), constant_multiplier=str(prod(constants)), cycle_removed_root_states=cycle_removed, removed_inconsistent_rows=collapsed_rows, exact_local_entry_checks=local_checked)


def compile_closure(model, deadline, byte_ceiling, max_rounds=50):
    """the full construction: returns dict(reduced_model, decoders {orig var: (rep or None, {rep state: orig state} or {None: fixed})}, rep_states {rep: sorted states}, rid {rep: reduced index},
    scalar (exact positive Fraction), identity (bool: nothing changed), stats). Raises ZeroEvidence (exact) or ClosureRefused (deadline / bytes; the caller keeps the original model)."""
    t0 = tnow()
    if t0 >= deadline: raise ClosureRefused('no allowance left at entry')
    domains, fs = rows_from_model(model, deadline); cards = model['cards']; ev = model.get('evidence', {})
    start_key = (len(domains), sum(map(len, domains.values())), len(fs)); est = _bytes_estimate(domains, fs)
    if est > byte_ceiling: raise ClosureRefused('support rows alone estimate %d B > ceiling %d B' % (est, byte_ceiling))
    decoders = {v: (v, {a: a for a in domains[v]}) for v in domains}; scalar = F(1); trace = []; deleted = 0; relations = 0; cycle_removed = 0; checks = 0
    for it in range(max_rounds):
        key = (len(domains), sum(map(len, domains.values())), len(fs))
        fs, gs = gac(domains, fs, deadline); deleted += gs['deleted_states']
        dom2, fs2, maps, qs = quotient(domains, fs, True, deadline)
        for orig, (curr, m) in list(decoders.items()):
            if curr is not None:
                r, rm = maps[curr]; decoders[orig] = (r, {a: m[b] for a, b in rm.items()})
        c = F(qs['constant_multiplier']); assert c > 0; scalar *= c; relations += qs['bijection_relations']; cycle_removed += qs['cycle_removed_root_states']; checks += qs['exact_local_entry_checks']
        trace.append(dict(iteration=it, gac=gs, quotient={k: v for k, v in qs.items() if k != 'nontrivial_components'}, largest_component=(qs['nontrivial_components'][0] if qs['nontrivial_components'] else 1)))
        domains, fs = dom2, fs2; est = max(est, _bytes_estimate(domains, fs, decoders))
        if est > byte_ceiling: raise ClosureRefused('live workspace estimate %d B > ceiling %d B after round %d' % (est, byte_ceiling, it))
        if (len(domains), sum(map(len, domains.values())), len(fs)) == key: break
    else: raise ClosureRefused('no fixed point after %d rounds' % max_rounds)
    identity = (deleted == 0 and relations == 0 and scalar == 1 and (len(domains), sum(map(len, domains.values())), len(fs)) == start_key and all(len(domains[v]) == cards[v] for v in domains if v not in ev))
    reps = sorted(domains); rid = {r: i for i, r in enumerate(reps)}; rep_states = {r: sorted(domains[r]) for r in reps}
    red_cards = [len(rep_states[r]) for r in reps]; red_factors = []
    for sc, rs in fs:
        if tnow() >= deadline: raise ClosureRefused('deadline while materialising the reduced tables')
        red_factors.append(dict(scope=tuple(rid[r] for r in sc), values=[rs.get(a, F(0)) for a in product(*(rep_states[r] for r in sc))]))
    reduced = dict(cards=red_cards, factors=red_factors, evidence={})
    est = max(est, _bytes_estimate(domains, fs, decoders) + sum(len(f['values']) * 56 for f in red_factors))
    if est > byte_ceiling: raise ClosureRefused('reduced tables push the estimate to %d B > ceiling %d B' % (est, byte_ceiling))
    fixed_nonobs = sum(1 for v, (r, m) in decoders.items() if r is None and v not in ev)
    stats = dict(status='APPLIED' if not identity else 'IDENTITY', seconds=tnow() - t0, rounds=len(trace), deleted_states=deleted, fixed_nonobserved_variables=fixed_nonobs, bijection_relations=relations, cycle_removed_states=cycle_removed, exact_local_entry_checks=checks, representatives=len(reps), reduced_factors=len(red_factors), reduced_query_coordinates=sum(red_cards), scalar=str(scalar), live_bytes_estimate=est, byte_ceiling=byte_ceiling, trace=trace[:8])
    return dict(reduced_model=reduced, decoders=decoders, rep_states=rep_states, rid=rid, scalar=scalar, identity=identity, stats=stats)


def decode_rows(closure, cards, ev, queries_orig, qix_eff, ans_eff, failed_eff, witness):
    """original answers from the effective (reduced) ones: a fixed original variable publishes EXACT 1 / 0, a state outside the representative's image EXACT 0, an aliased state copies
    its representative coordinate's row (same enclosure, same guarantee: deterministic query recovery, no new statistical event); NOTHING is published without the positive-mass witness.
    Returns (ans_orig {orig query index: row}, failed_orig [orig vars whose representative was not recovered])"""
    dec = closure['decoders']; rid = closure['rid']; rep_states = closure['rep_states']; ans_o = {}; failed_o = set(); failed_set = set(failed_eff); inv_cache = {}
    for jo, (x, val) in enumerate(queries_orig):
        r, m = dec[x]
        if r is None:
            if witness: one = F(1 if val == m[None] else 0); ans_o[jo] = dict(lo=one, hi=one, point=one, guarantee='EXACT')
            continue
        if x not in inv_cache: inv_cache[x] = {m[s]: i for i, s in enumerate(rep_states[r])}
        inv = inv_cache[x]
        if val not in inv:
            if witness: ans_o[jo] = dict(lo=F(0), hi=F(0), point=F(0), guarantee='EXACT')
            continue
        j = qix_eff.get((rid[r], inv[val]))
        if j is not None and j in ans_eff: ans_o[jo] = ans_eff[j]
        if rid[r] in failed_set: failed_o.add(x)
    return ans_o, sorted(failed_o)
