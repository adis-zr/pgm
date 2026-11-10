"""Independent exact-rational BRUTE-FORCE oracle over the ORIGINAL source factors (brief §18). Shares nothing with the optimized path except the
strict parser (gbidi3.source / ext.uai dataclasses): no reductions, no views, no orders, no conditioner, no serializer, no pullback. Enumerates every
evidence-compatible assignment of the original variables (itertools.product), multiplies every original factor occurrence once (including scalar
factors), accumulates Z and N[v][state] for every original variable (observed variables included: their numerator sits at the observed state).
Returns exact Fractions; the caller compares Z (or a rescaled Z), every N and the normalized rows."""
from __future__ import annotations
from fractions import Fraction as Fr
from itertools import product as iproduct


def brute(model, ev, cap_assignments=2_000_000):
    nv = model.nvars; card = list(model.card)
    ranges = [range(card[v]) if v not in ev else (ev[v],) for v in range(nv)]
    total = 1
    for r in ranges:
        total *= len(r)
    if total > cap_assignments:
        raise ValueError("oracle cap: %d assignments" % total)
    strides = []
    for f in model.factors:
        st = [1] * len(f.card); acc = 1
        for k in range(len(f.card) - 1, -1, -1):
            st[k] = acc; acc *= f.card[k]
        strides.append(st)
    Z = Fr(0); N = [[Fr(0)] * card[v] for v in range(nv)]
    for x in iproduct(*ranges):
        w = Fr(1)
        for f, st in zip(model.factors, strides):
            off = 0
            for k, v in enumerate(f.scope):
                off += x[v] * st[k]
            w *= f.table[off]
            if w == 0:
                break
        if w == 0:
            continue
        Z += w
        for v in range(nv):
            N[v][x[v]] += w
    return Z, N


def rows(model, ev, cap_assignments=2_000_000):
    """normalized exact rows (None when Z == 0)"""
    Z, N = brute(model, ev, cap_assignments)
    if Z == 0:
        return Z, N, None
    return Z, N, [[q / Z for q in N[v]] for v in range(model.nvars)]
