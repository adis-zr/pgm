"""Brute-force exact rational oracle for qualification ONLY: enumerates every joint assignment of a (tiny) UAI model with evidence and
returns Z and every singleton numerator as Fractions. Shares nothing with the kernel's traversal, lanes, trees or indexing; it reads the
ext.uai Model's factor tables directly through Factor.at()."""
from __future__ import annotations
import itertools
from fractions import Fraction as Fr


def brute(model, ev):
    """model: ext.uai.Model (checked); ev: {var: state}. Returns (Z, {v: [N_v0, N_v1, ...]})."""
    doms = [range(model.card[v]) if v not in ev else [ev[v]] for v in range(model.nvars)]
    Z = Fr(0); N = {v: [Fr(0)] * model.card[v] for v in range(model.nvars)}
    for assign in itertools.product(*doms):
        w = Fr(1)
        for f in model.factors:
            w *= f.at({v: assign[v] for v in f.scope})
            if w == 0:
                break
        if w == 0:
            continue
        Z += w
        for v in range(model.nvars):
            N[v][assign[v]] += w
    return Z, N
