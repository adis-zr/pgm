"""INDEPENDENT original-model rational enumerator (qualification oracle; also the R0-style reference for small tasks). It never imports the compiler, frontier,
streams or decoder under test: it enumerates ORIGINAL assignments consistent with the evidence, multiplies the ORIGINAL tables, and evaluates the ORIGINAL query
tables. Output per query: exact Fraction (expectation N/Z; ratio N/D) or the typed strings 'ZERO_EVIDENCE' (Z = 0) / 'UNDEFINED' (ratio with D = 0)."""
from fractions import Fraction as F
import sys as _sys; _sys.set_int_max_str_digits(0)
from itertools import product
from math import prod, lcm
import time


def enumerate_truth(model, queries, deadline=None, max_assignments=1 << 24):
    cards = model['cards']; ev = model.get('evidence', {}); n = len(cards)
    free = [v for v in range(n) if v not in ev]
    if prod(cards[v] for v in free) > max_assignments: return None
    fden = [lcm(*[F(v).denominator for v in f['values']]) if f['values'] else 1 for f in model['factors']]; ftab = [[int(F(v) * d) for v in f['values']] for f, d in zip(model['factors'], fden)]
    fscope = [tuple(f['scope']) for f in model['factors']]; scale = prod(fden) if fden else 1
    qd = []; qt = []
    for q in queries:
        vals = q.f.values if q.kind == 'expectation' else q.h.values + q.g.values; d = lcm(*[F(v).denominator for v in vals]); qd.append(d)
        qt.append(([int(F(v) * d) for v in q.f.values], None, q.f.scope, None) if q.kind == 'expectation' else ([int(F(v) * d) for v in q.h.values], [int(F(v) * d) for v in q.g.values], q.h.scope, q.g.scope))
    Zi = 0; numi = [0] * len(queries); deni = [0] * len(queries); x = [ev.get(v, 0) for v in range(n)]; k = 0
    for xs in product(*(range(cards[v]) for v in free)):
        for v, s in zip(free, xs): x[v] = s
        k += 1
        if deadline is not None and not k & 4095 and time.monotonic() >= deadline: return None
        w = 1
        for tab, sc in zip(ftab, fscope):
            i = 0
            for v in sc: i = i * cards[v] + x[v]
            w *= tab[i]
            if not w: break
        if not w: continue
        Zi += w
        for j in range(len(queries)):
            ht, gt, hs, gs = qt[j]; i = 0
            for v in hs: i = i * cards[v] + x[v]
            numi[j] += w * ht[i]
            if gt is not None:
                i = 0
                for v in gs: i = i * cards[v] + x[v]
                deni[j] += w * gt[i]
    Z = F(Zi, scale); num = [F(numi[j], qd[j] * scale) for j in range(len(queries))]; den = [F(deni[j], qd[j] * scale) for j in range(len(queries))]
    if Z == 0: return dict(Z=Z, answers=['ZERO_EVIDENCE'] * len(queries), assignments=k)
    out = []
    for j, q in enumerate(queries):
        if q.kind == 'expectation': out.append(num[j] / Z)
        else: out.append(num[j] / den[j] if den[j] else 'UNDEFINED')
    return dict(Z=Z, answers=out, numerators=num, denominators=[den[j] if queries[j].kind == 'ratio' else Z for j in range(len(queries))], assignments=k)


def eliminate_truth(model, queries, deadline=None, max_table=1 << 22):
    """INDEPENDENT exact rational truth by bucket (variable) elimination over the ORIGINAL model (integer tables after clearing denominators; min-fill ordering; nothing from the
    frontier / decoder / compiler under test). Supports expectation queries (numerator = sum_x w(x) f(x)) and ratio queries (h / g). Returns the same shape as enumerate_truth, or
    None when an intermediate table would exceed max_table entries or the deadline passes. Used as the judge for models too large for enumeration."""
    cards = list(model['cards']); ev = dict(model.get('evidence', {})); n = len(cards)
    def tab_int(vals):
        d = lcm(*[F(v).denominator for v in vals]) if vals else 1; return [int(F(v) * d) for v in vals], d
    base = []; scale = 1
    for f in model['factors']:
        t, d = tab_int(f['values']); base.append((tuple(f['scope']), t)); scale *= d
    def run(extra):
        """Z-like sum of prod(base) * prod(extra) with evidence fixed; returns an integer"""
        facs = [(sc, list(t)) for sc, t in base] + [(sc, list(t)) for sc, t in extra]
        # apply evidence: slice every factor on the evidence variables
        def slice_ev(sc, t):
            keep = [v for v in sc if v not in ev]
            if len(keep) == len(sc): return sc, t
            out = [0] * prod(cards[v] for v in keep) if keep else [0]
            for idx, w in enumerate(t):
                x = {}; r = idx
                for v in reversed(sc): x[v] = r % cards[v]; r //= cards[v]
                if any(x[v] != ev[v] for v in sc if v in ev): continue
                i = 0
                for v in keep: i = i * cards[v] + x[v]
                out[i] += w
            return tuple(keep), out
        facs = [slice_ev(sc, t) for sc, t in facs]
        const = 1; live = []
        for sc, t in facs:
            if not sc: const *= t[0]
            else: live.append((sc, t))
        if const == 0: return 0
        remaining = sorted({v for sc, _ in live for v in sc})
        # free variables touched by NO factor (model or query) contribute their cardinality as a multiplicity (enumeration counts every assignment)
        for v in range(n):
            if v not in ev and v not in remaining: const *= cards[v]
        k = 0
        while remaining:
            if deadline is not None and time.monotonic() >= deadline: return None
            # min-fill / min-degree choice
            best = None
            for v in remaining:
                nb = set()
                for sc, _ in live:
                    if v in sc: nb |= set(sc)
                nb.discard(v); size = prod(cards[u] for u in nb) if nb else 1
                if best is None or size < best[0]: best = (size, v, nb)
            size, v, nb = best
            if size > max_table: return None
            bucket = [(sc, t) for sc, t in live if v in sc]; live = [(sc, t) for sc, t in live if v not in sc]
            new_sc = tuple(sorted(nb)); out = [0] * size
            for idx in range(size):
                x = {}; r = idx
                for u in reversed(new_sc): x[u] = r % cards[u]; r //= cards[u]
                s = 0
                for a in range(cards[v]):
                    x[v] = a; w = 1
                    for sc, t in bucket:
                        i = 0
                        for u in sc: i = i * cards[u] + x[u]
                        w *= t[i]
                        if not w: break
                    s += w
                out[idx] = s
                k += 1
                if deadline is not None and not k & 8191 and time.monotonic() >= deadline: return None
            if new_sc: live.append((new_sc, out))
            else: const *= out[0]
            remaining = [u for u in remaining if u != v]
        for sc, t in live: const *= t[0]      # (unreachable: every scoped factor was eliminated)
        return const
    Zi = run([])
    if Zi is None: return None
    Z = F(Zi, scale)
    if Z == 0: return dict(Z=Z, answers=['ZERO_EVIDENCE'] * len(queries), assignments=None, method='elimination')
    out = []; nums = []; dens = []
    for q in queries:
        if q.kind == 'expectation':
            t, d = tab_int(q.f.values); ni = run([(tuple(q.f.scope), t)])
            if ni is None: return None
            num = F(ni, d * scale); nums.append(num); dens.append(Z); out.append(num / Z)
        else:
            th, dh = tab_int(q.h.values); tg, dg = tab_int(q.g.values); hi_ = run([(tuple(q.h.scope), th)]); gi_ = run([(tuple(q.g.scope), tg)])
            if hi_ is None or gi_ is None: return None
            num = F(hi_, dh * scale); den = F(gi_, dg * scale); nums.append(num); dens.append(den); out.append(num / den if den else 'UNDEFINED')
    return dict(Z=Z, answers=out, numerators=nums, denominators=dens, assignments=None, method='elimination')


def truth(model, queries, deadline=None, max_assignments=1 << 22, max_table=1 << 22):
    """enumeration when the free assignment space is small, else elimination; both are independent of the candidate under test"""
    r = enumerate_truth(model, queries, deadline=deadline, max_assignments=max_assignments)
    return r if r is not None else eliminate_truth(model, queries, deadline=deadline, max_table=max_table)
