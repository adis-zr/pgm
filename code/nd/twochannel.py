"""The two-channel mini-bucket discarded-mass certificate (theory §§3-4, §6-7), producer side.

Pairs (r, d): r = mass using no removed entry, d = mass using at least one. (r,d)+(s,e) = (r+s, d+e);
(r,d)*(s,e) = (rs, re+ds+de). The implementation multiplies through the total channel t = r + d (a semiring
homomorphism): t' = t1 t2, r' = r1 r2, d' = t' - r' -- identical integers, fewer multiplications.

Construction (frozen): evidence-restricted original occurrences (pairs (a_f, b_f) by the mask) + one all-one unary
identity per free variable + scalar occurrences; denominators cleared per occurrence (both channels times d_f; the final
integers carry C = prod d_f); deterministic greedy min-fill order on the restricted scopes with key (missing neighbour
edges, product of candidate-bag cardinalities, variable label); per bucket, factors sorted by decreasing domain population
(ties by deterministic ID), first-fit into the earliest group whose union-scope population stays <= K (K = 4,096, the
eliminated variable included); each group message streamed over its union scope (the eliminated variable last), summing out
that variable only; remaining scalars multiplied with the pair product. Output: (V, U) with V >= R, U >= D (coordinatewise).
V is an UPPER bound on R and is never used as L. Refusals: an input factor domain or a free-variable domain above K."""
from __future__ import annotations
from fractions import Fraction as Fr
import math, time
import numpy as np
from gmpy2 import mpz

K_DEFAULT = 4096


class CertificateRefusal(Exception):
    """An implementation-scope refusal (cap), never a mathematical statement."""


def pair_mul(a, b):
    return (a[0] * b[0], a[0] * b[1] + a[1] * b[0] + a[1] * b[1])


def pair_add(a, b):
    return (a[0] + b[0], a[1] + b[1])


def min_fill_order(free, card, scopes):
    """The frozen rule: at each step the variable minimizing (missing edges among its current neighbours, product of
    cardinalities of v and its neighbours, original label); add fill edges; remove the variable."""
    adj = {v: set() for v in free}
    for sc in scopes:
        for a in sc:
            for b in sc:
                if a != b:
                    adj[a].add(b)
    remaining = set(free); order = []
    while remaining:
        best = None
        for v in sorted(remaining):
            nb = sorted(adj[v] & remaining)
            miss = sum(1 for i in range(len(nb)) for j in range(i + 1, len(nb)) if nb[j] not in adj[nb[i]])
            prod = card[v]
            for x in nb:
                prod *= card[x]
            key = (miss, prod, v)
            if best is None or key < best[0]:
                best = (key, v)
        v = best[1]
        nb = adj[v] & remaining
        for x in nb:
            adj[x] |= (nb - {x})
            adj[x].discard(v)
        remaining.discard(v); order.append(v)
    return order


class PFactor:
    __slots__ = ("fid", "scope", "card", "R", "T", "owned")

    def __init__(self, fid, scope, card, R, T, owned):
        self.fid = fid; self.scope = tuple(scope); self.card = tuple(card)      # scope in table order (first = most significant)
        self.R = R; self.T = T                                                  # numpy object arrays of mpz, flat, UAI order
        self.owned = frozenset(owned)

    def size(self):
        return int(self.R.size)


def _flat_index_map(union_vars, union_card, fac):
    """For every union-scope flat index (union order; last varies fastest) the factor's flat index."""
    q = 1
    for c in union_card:
        q *= c
    u = np.arange(q, dtype=np.int64)
    pos = {v: i for i, v in enumerate(union_vars)}
    ustr = [1] * len(union_vars); acc = 1
    for i in range(len(union_vars) - 1, -1, -1):
        ustr[i] = acc; acc *= union_card[i]
    fstr = [1] * len(fac.scope); acc = 1
    for i in range(len(fac.scope) - 1, -1, -1):
        fstr[i] = acc; acc *= fac.card[i]
    idx = np.zeros(q, dtype=np.int64)
    for i, v in enumerate(fac.scope):
        j = pos[v]
        idx += ((u // ustr[j]) % union_card[j]) * fstr[i]
    return idx


def build_inputs(occ, masks, scalars, free, card):
    """Pair factors with cleared denominators: occurrences (a_f, b_f) in occurrence order, then identities, then scalar
    occurrences as 0-ary pair factors. Returns (factors, C, denominators, bits)."""
    facs = []; C = 1; dens = []
    for i, (o, mk) in enumerate(zip(occ, masks)):
        L = 1
        for x in o["table"]:
            d = Fr(x).denominator; L = L * d // math.gcd(L, d)
        dens.append(L); C *= L
        rem = set(mk["removed"])
        R = np.empty(len(o["table"]), dtype=object); T = np.empty(len(o["table"]), dtype=object)
        for j, x in enumerate(o["table"]):
            w = mpz(int(Fr(x) * L))
            T[j] = w; R[j] = mpz(0) if j in rem else w
        facs.append(PFactor((0, i), o["scope"], o["card"], R, T, {("occ", i)}))
    base = len(occ)
    for k, v in enumerate(free):
        n = int(card[v])
        ones = np.array([mpz(1)] * n, dtype=object)
        facs.append(PFactor((0, base + k), (v,), (n,), ones, ones.copy(), {("id", v)}))
    for k, (origin, val) in enumerate(scalars):
        L = Fr(val).denominator; dens.append(L); C *= L
        w = mpz(int(Fr(val) * L))
        facs.append(PFactor((0, base + len(free) + k), (), (), np.array([w], dtype=object), np.array([w], dtype=object), {("scalar", k)}))
    return facs, C, dens


def run_certificate(occ, masks, scalars, free, card, K=K_DEFAULT, deadline=None, order=None):
    """Returns the certificate record: V, U (Fractions in original units), C, the schedule and statistics."""
    t0 = time.monotonic()
    card = dict(card)
    for v in free:
        if int(card[v]) > K:
            raise CertificateRefusal("free variable %d has domain %d > K=%d" % (v, card[v], K))
    for o in occ:
        n = 1
        for c in o["card"]:
            n *= c
        if n > K:
            raise CertificateRefusal("occurrence %d has domain %d > K=%d" % (o["origin"], n, K))
    facs, C, dens = build_inputs(occ, masks, scalars, free, card)
    scopes = [o["scope"] for o in occ]
    if order is None:
        order = min_fill_order(list(free), card, scopes)
    t_order = time.monotonic()
    live = list(facs)
    schedule = []
    stats = {"pair_products": 0, "pair_additions": 0, "groups": 0, "split_buckets": 0, "max_union_entries": 0, "max_bits": 0, "messages": 0}
    for e, v in enumerate(order):
        if deadline is not None:
            deadline()
        bucket = [f for f in live if v in f.scope]
        rest = [f for f in live if v not in f.scope]
        bucket.sort(key=lambda f: (-f.size(), f.fid))
        groups = []                                                    # [ [factors], union_vars_set ]
        for f in bucket:
            placed = False
            for g in groups:
                uv = g[1] | set(f.scope)
                q = 1
                for x in uv:
                    q *= int(card[x])
                if q <= K:
                    g[0].append(f); g[1] = uv; placed = True; break
            if not placed:
                groups.append([[f], set(f.scope)])
        if len(groups) > 1:
            stats["split_buckets"] += 1
        brec = {"elim_index": e, "var": v, "bucket_fids": [f.fid for f in bucket], "groups": []}
        for gi, (members, uv) in enumerate(groups):
            others = sorted(x for x in uv if x != v)
            union_vars = others + [v]
            union_card = [int(card[x]) for x in union_vars]
            q = 1
            for c in union_card:
                q *= c
            stats["max_union_entries"] = max(stats["max_union_entries"], q)
            R = None; T = None
            for f in members:
                idx = _flat_index_map(union_vars, union_card, f)
                fr = f.R[idx]; ft = f.T[idx]
                if R is None:
                    R = fr.copy(); T = ft.copy()
                else:
                    R = R * fr; T = T * ft; stats["pair_products"] += q
            dv = int(card[v])
            R2 = R.reshape(-1, dv).sum(axis=1) if others else np.array([R.sum()], dtype=object)
            T2 = T.reshape(-1, dv).sum(axis=1) if others else np.array([T.sum()], dtype=object)
            stats["pair_additions"] += q - q // dv
            R2 = np.array(R2, dtype=object).reshape(-1); T2 = np.array(T2, dtype=object).reshape(-1)
            owned = frozenset().union(*[f.owned for f in members])
            mid = (1, e, gi)
            msg = PFactor(mid, tuple(others), tuple(int(card[x]) for x in others), R2, T2, owned)
            stats["messages"] += 1; stats["groups"] += 1
            stats["max_bits"] = max(stats["max_bits"], max(int(x).bit_length() for x in T2.tolist()))
            rest.append(msg)
            brec["groups"].append({"message_fid": mid, "member_fids": [f.fid for f in members], "union_scope": union_vars, "union_entries": q, "message_scope": others})
        schedule.append(brec)
        live = rest
    # every remaining factor is a scalar (empty scope): pair-multiply
    V = mpz(1); Tt = mpz(1); owned_all = set()
    for f in live:
        assert f.scope == (), f.scope
        V = V * f.R[0]; Tt = Tt * f.T[0]; owned_all |= f.owned
    U = Tt - V
    expect = {("occ", i) for i in range(len(occ))} | {("id", v) for v in free} | {("scalar", k) for k in range(len(scalars))}
    assert owned_all == expect, "ownership is not a partition of the occurrences"
    t1 = time.monotonic()
    return {"V": Fr(int(V), C), "U": Fr(int(U), C), "V_int": str(V), "U_int": str(U), "C": str(C), "C_bits": C.bit_length(),
            "denominators_bits_max": max((d.bit_length() for d in dens), default=1), "K": K, "order": [int(x) for x in order],
            "n_free": len(free), "n_occurrences": len(occ), "n_identities": len(free), "n_scalars": len(scalars),
            "schedule": schedule, "stats": stats, "wall_s": {"order": round(t_order - t0, 6), "contraction": round(t1 - t_order, 6), "total": round(t1 - t0, 6)}}
