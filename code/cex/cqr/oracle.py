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
