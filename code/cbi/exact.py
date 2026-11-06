"""Exact variable elimination over blocks (dense integer tables, Python ints, numpy object arrays): the exact reference for small
instances and the priced dense fallback. Factors: unary weight vectors and edge kernels kappa (scaled by v^d'); eliminates blocks in
min-fill order; the largest intermediate table is priced BEFORE any allocation against `max_entries`. Returns Z (scaled) and, per
requested block, the exact row marginal numerators at the same scale (so coordinate probabilities are exact rationals)."""
from __future__ import annotations
from fractions import Fraction as Fr
import numpy as np
from cbi import arith as A


class TooLarge(Exception):
    pass


def _kernel_table(bu, bv, mask, r):
    dp = bin(mask).count("1"); u, v = A.uv(r)
    kap = [A.kappa_int(dp, u, v, dd) for dd in range(dp + 1)]
    X = np.asarray(bu.rows, dtype=np.uint64); Y = np.asarray(bv.rows, dtype=np.uint64)
    D = np.bitwise_count((X[:, None] ^ Y[None, :]) & np.uint64(mask))
    tab = np.empty(D.shape, dtype=object)
    for dd in range(dp + 1):
        tab[D == dd] = kap[dd]
    return tab


def _order(blocks, edges, keep):
    adj = {b: set() for b in blocks}
    for e in edges:
        adj[e.u].add(e.v); adj[e.v].add(e.u)
    rem = set(b for b in blocks if b != keep); order = []
    while rem:
        best = None
        for x in sorted(rem):
            nb = [y for y in adj[x] if y in rem or y == keep]
            miss = sum(1 for i in range(len(nb)) for j in range(i + 1, len(nb)) if nb[j] not in adj[nb[i]])
            size = 1
            for y in nb:
                size *= len(blocks[y].rows)
            key = (miss, size * len(blocks[x].rows), x)
            if best is None or key < best[0]:
                best = (key, x)
        x = best[1]; nb = [y for y in adj[x] if y in rem or y == keep]
        for a in nb:
            for b in nb:
                if a != b:
                    adj[a].add(b)
        rem.discard(x); order.append(x)
    return order


def price(blocks, edges, keep):
    """Largest intermediate table (entries) along the min-fill order, without allocating."""
    order = _order(blocks, edges, keep)
    scopes = [frozenset([e.u, e.v]) for e in edges] + [frozenset([b]) for b in blocks]
    worst = 0
    for x in order:
        inv = [s for s in scopes if x in s]; new = frozenset().union(*inv) - {x} if inv else frozenset()
        size = 1
        for y in (new | {x}):
            size *= len(blocks[y].rows)
        worst = max(worst, size)
        scopes = [s for s in scopes if x not in s] + ([new] if new else [])
    return worst, order


def marginal(blocks, edges, keep, max_entries=1 << 20):
    """Exact unnormalized marginal over the rows of block `keep` (Python ints; common positive scale) and the log."""
    worst, order = price(blocks, edges, keep)
    if worst > max_entries:
        raise TooLarge("largest intermediate table %d entries exceeds the limit %d" % (worst, max_entries))
    # factors as (scope tuple, object ndarray)
    facs = [((b,), np.array(blk.w, dtype=object)) for b, blk in blocks.items()]
    for e in edges:
        facs.append(((e.u, e.v), _kernel_table(blocks[e.u], blocks[e.v], e.mask, e.r)))
    for x in order:
        inv = [f for f in facs if x in f[0]]; rest = [f for f in facs if x not in f[0]]
        scope = []
        for s, _ in inv:
            for y in s:
                if y not in scope:
                    scope.append(y)
        shape = tuple(len(blocks[y].rows) for y in scope)
        acc = np.ones(shape, dtype=object)
        for s, t in inv:
            # broadcast t over `scope`
            idx = [slice(None) if y in s else None for y in scope]
            perm = [s.index(y) for y in scope if y in s]
            tt = np.transpose(t, perm) if len(s) > 1 else t
            acc = acc * tt[tuple(idx)]
        ax = scope.index(x); summed = acc.sum(axis=ax)
        nscope = tuple(y for y in scope if y != x)
        if nscope:
            rest.append((nscope, summed))
        else:
            rest.append(((), summed))
        facs = rest
    out = np.array(blocks[keep].w, dtype=object) * 0 + 1
    scalar = 1
    for s, t in facs:
        if s == (keep,):
            out = out * t
        elif s == ():
            scalar *= int(t)
        else:
            raise RuntimeError("unexpected residual scope %s" % (s,))
    return [int(x) * scalar for x in out.tolist()], {"largest_table_entries": worst, "order": order}


def coordinate_probabilities(blocks, keep, marg, d):
    Z = sum(marg); rows = blocks[keep].rows
    return [Fr(sum(w for x, w in zip(rows, marg) if (x >> j) & 1), Z) for j in range(d)], Z
