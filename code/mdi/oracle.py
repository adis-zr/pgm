"""Exact brute-force oracle: the tiny-fixture ground truth (spec section 5)."""
from __future__ import annotations
import itertools
from fractions import Fraction as Fr


def exact_all_marginals(restricted):
    """Enumerate every free assignment with exact Fractions.

    Returns (Z, marginals) where marginals[v][s] is the exact conditional
    probability, or (0, None) when the evidence weight is exactly zero.
    """
    free = restricted.free
    card = restricted.card
    facs = restricted.factors
    Z = Fr(0)
    acc = {v: [Fr(0)] * card[v] for v in free}
    for combo in itertools.product(*[range(card[v]) for v in free]):
        a = dict(zip(free, combo))
        w = Fr(1)
        for f in facs:
            st = f.strides()
            off = 0
            for k, v in enumerate(f.scope):
                off += a[v] * st[k]
            e = f.table[off]
            if e == 0:
                w = Fr(0)
                break
            w *= e
        if w == 0:
            continue
        Z += w
        for v, s in a.items():
            acc[v][s] += w
    if Z == 0:
        return Fr(0), None
    return Z, {v: [x / Z for x in acc[v]] for v in free}
