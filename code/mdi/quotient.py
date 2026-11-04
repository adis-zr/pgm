"""Generic exact CONSTRAINT QUOTIENTING (bounded pilot, 3 November 2026; overseer's decision after the
accepted Promedus pair): binary equality / complement identification with a signed union-find PLUS
iterative forced-state propagation, derived from the exact zeros of the restricted, preprocessed factor
tables; the model is then solved on the QUOTIENT (one representative per class of related variables,
forced variables removed) with the existing identity engines, and every original singleton marginal is
restored through a representative-XOR or fixed-state mapping. Zero approximation: every positive
configuration of the original law respects the derived relations (each relation is read off a factor
that is zero wherever it fails, and a positive configuration makes every factor positive), so
substituting the relations into the factor tables changes no configuration weight; Z and every
original singleton numerator are preserved exactly, with every factor occurrence, weight, constant
scale, evidence and variable / state label kept.

Soundness of each derived relation (the obligation the checker re-derives in `mdi.quotient_check`):
* FORCED STATE: if, among the positive entries of some factor f that are consistent with the relations
  already derived, variable v takes a single state s, then every positive configuration has v = s.
* EQUALITY / COMPLEMENT: if, among those entries, the pair (a, b) of binary variables takes only values
  with a == b (resp. a != b), then every positive configuration has a == b (resp. a != b).
* Signed union-find closes these under transitivity (a ~ b with parity p, b ~ c with parity q gives
  a ~ c with parity p XOR q); a forced member forces its whole class; a class with inconsistent parity
  or inconsistent forced states, or a factor with no consistent positive entry, means NO positive
  configuration exists (zero evidence weight), which the pipeline's zero-evidence proof decides.

The recognition is bounded (wall cap, pass count) and CHARGED; an attempt that eliminates nothing or
does not reach the admission ratio falls back to the dense identity with the attempt charged.
"""
from __future__ import annotations
from fractions import Fraction as Fr
import hashlib
import itertools
import time
from mdi import model as M

QUOTIENT_WALL_CAP_S = 5.0            # the pilot's cap on ONE recognition (producer) / re-derivation (checker)
MIN_REDUCTION_RATIO = 2.0            # dense enumerated schedule rows / quotient's required to select the route
METHOD = ("binary equality/complement by signed union-find over the consistent positive entries of every factor, plus "
          "iterative forced-state propagation, to a fixpoint; representatives = the smallest variable of each class")


class QuotientError(Exception):
    """A typed stop of recognition (cap) -- not a mathematical statement about the law."""


class Contradiction(QuotientError):
    """The derived relations admit no positive configuration: zero evidence weight."""


class _SignedUF:
    """Union-find over binary variables with a parity to the root (x = root XOR parity)."""

    def __init__(self):
        self.parent = {}
        self.parity = {}

    def add(self, v):
        if v not in self.parent:
            self.parent[v] = v
            self.parity[v] = 0

    def find(self, v):
        self.add(v)
        path = []
        while self.parent[v] != v:
            path.append(v)
            v = self.parent[v]
        root = v
        # path compression with parity accumulation (from the far end)
        acc = 0
        for u in reversed(path):
            acc ^= self.parity[u]
            self.parent[u] = root
            self.parity[u] = acc
        return root, (self.parity[path[0]] if path else 0)

    def union(self, a, b, rel):
        """Relate a and b with a XOR b == rel. Returns True when something changed; raises Contradiction."""
        ra, pa = self.find(a)
        rb, pb = self.find(b)
        if ra == rb:
            if (pa ^ pb) != rel:
                raise Contradiction("variables %d and %d are related with inconsistent parity" % (a, b))
            return False
        # attach the larger id under the smaller so the representative is the smallest variable
        if ra < rb:
            self.parent[rb] = ra
            self.parity[rb] = pa ^ pb ^ rel
        else:
            self.parent[ra] = rb
            self.parity[ra] = pa ^ pb ^ rel
        return True


def recognize(factors, free, card, deadline=None, charge=None, wall_cap_s=None):
    """Derive the fixpoint of forced states and binary equality / complement relations from the
    exact zeros of `factors` (restricted, preprocessed). Returns a declaration dict (see
    `declaration`). Raises Contradiction when no positive configuration exists, QuotientError on
    the wall cap. Every scanned table entry is charged through `charge(n)`."""
    wall_cap_s = QUOTIENT_WALL_CAP_S if wall_cap_s is None else float(wall_cap_s)
    t0 = time.monotonic()
    card = dict(card)
    fixed = {}
    uf = _SignedUF()
    for v in free:
        if int(card[v]) == 2:
            uf.add(v)
    scanned = 0
    passes = 0
    changed = True
    while changed:
        changed = False
        passes += 1
        if passes > len(free) + 2:
            raise QuotientError("recognition did not reach a fixpoint in %d passes" % passes)
        for f in factors:
            scope = tuple(f.scope)
            if not scope:
                continue
            k = len(scope)
            strides = f.strides()
            # the consistent positive entries: fixed states respected, related binary variables consistent
            live = []
            shape = tuple(int(c) for c in f.card)
            for idx in itertools.product(*[range(c) for c in shape]):
                scanned += 1
                off = sum(idx[j] * strides[j] for j in range(k))
                if f.table[off] == 0:
                    continue
                ok = True
                for j, v in enumerate(scope):
                    if v in fixed and fixed[v] != idx[j]:
                        ok = False
                        break
                if not ok:
                    continue
                # pairwise consistency with the relations already derived (binary variables)
                roots = {}
                for j, v in enumerate(scope):
                    if int(card[v]) == 2 and v in uf.parent:
                        rt, pr = uf.find(v)
                        val = idx[j] ^ pr                 # the root's implied value
                        if rt in roots and roots[rt] != val:
                            ok = False
                            break
                        roots[rt] = val
                if ok:
                    live.append(idx)
            if charge is not None:
                charge(int(f.size()))
            if time.monotonic() - t0 > wall_cap_s:
                raise QuotientError("recognition exceeded its %.1f s cap" % wall_cap_s)
            if deadline is not None:
                deadline()
            if not live:
                raise Contradiction("factor over %s has no positive entry consistent with the derived relations" % (scope,))
            # forced states
            for j, v in enumerate(scope):
                states = set(e[j] for e in live)
                if len(states) == 1:
                    s = next(iter(states))
                    if v in fixed:
                        if fixed[v] != s:
                            raise Contradiction("variable %d is forced to two different states" % v)
                    else:
                        fixed[v] = s
                        changed = True
            # equality / complement among pairs of binary variables
            for j1 in range(k):
                a = scope[j1]
                if int(card[a]) != 2 or a in fixed:
                    continue
                for j2 in range(j1 + 1, k):
                    b = scope[j2]
                    if int(card[b]) != 2 or b in fixed:
                        continue
                    pairs = set((e[j1], e[j2]) for e in live)
                    if pairs <= {(0, 0), (1, 1)}:
                        if uf.union(a, b, 0):
                            changed = True
                    elif pairs <= {(0, 1), (1, 0)}:
                        if uf.union(a, b, 1):
                            changed = True
        # a forced member forces its class (polled: this loop is quadratic in the binary variables)
        for v in list(uf.parent):
            if v in fixed:
                rt, pr = uf.find(v)
                s_root = fixed[v] ^ pr
                for u in list(uf.parent):
                    ru, pu = uf.find(u)
                    if ru == rt:
                        want = s_root ^ pu
                        if u in fixed:
                            if fixed[u] != want:
                                raise Contradiction("class of %d forces %d to two states" % (rt, u))
                        else:
                            fixed[u] = want
                            changed = True
                if time.monotonic() - t0 > wall_cap_s:
                    raise QuotientError("recognition exceeded its %.1f s cap" % wall_cap_s)
                if deadline is not None:
                    deadline()
    # the declaration (inside the timed boundary): merged = non-representative, non-fixed class members
    merged = {}
    for v in sorted(uf.parent):
        if v in fixed:
            continue
        rt, pr = uf.find(v)
        if rt != v:
            merged[v] = (rt, pr)
    n_free_q = len([v for v in free if v not in fixed and v not in merged])
    decl = declaration(fixed, merged, n_free_q, scanned, passes, 0.0)
    elapsed = time.monotonic() - t0
    decl["recognition"]["seconds"] = round(elapsed, 4)
    # the FINAL deadline check: the cap and the invocation deadline on the complete elapsed time, after
    # the declaration and its digest are built, so a recognition never returns past its cap
    if elapsed > wall_cap_s:
        raise QuotientError("recognition exceeded its %.1f s cap (%.3f s at completion)" % (wall_cap_s, elapsed))
    if deadline is not None:
        deadline()
    return decl


def _digest(fixed, merged):
    h = hashlib.sha256()
    for v in sorted(fixed):
        h.update(("F%d=%d;" % (int(v), int(fixed[v]))).encode())
    for v in sorted(merged):
        rt, pr = merged[v]
        h.update(("M%d=%d^%d;" % (int(v), int(rt), int(pr))).encode())
    return h.hexdigest()


def declaration(fixed, merged, n_free_q, scanned=0, passes=0, elapsed_s=0.0):
    return {"fixed": {str(int(v)): int(s) for v, s in sorted(fixed.items())},
            "merged": {str(int(v)): [int(rt), int(pr)] for v, (rt, pr) in sorted(merged.items())},
            "n_free": int(n_free_q), "digest": _digest(fixed, merged), "method": METHOD,
            "recognition": {"entries_scanned": int(scanned), "passes": int(passes), "seconds": round(float(elapsed_s), 4)}}


def eliminated(decl):
    return len(decl["fixed"]) + len(decl["merged"])


def build_quotient(r, decl):
    """The QUOTIENT restricted model under the declaration: every factor occurrence has each fixed
    variable replaced by its state and each merged variable by (representative XOR parity); the
    table over the distinct representatives is read from the original table at the mapped assignment
    (so every positive weight is preserved exactly; inconsistent entries never occur). A factor with
    no free variable left becomes a scalar multiplied into `constant`. Returns a Restricted over the
    representatives, or raises Contradiction when a scalar is zero."""
    fixed = {int(v): int(s) for v, s in decl["fixed"].items()}
    merged = {int(v): (int(a[0]), int(a[1])) for v, a in decl["merged"].items()}
    card = dict(r.card)
    free_q = [v for v in r.free if v not in fixed and v not in merged]
    const = Fr(r.constant)
    facs = []
    for f in r.factors:
        scope = tuple(f.scope)
        strides = f.strides()
        reps = []
        for v in scope:
            if v in fixed:
                continue
            rv = merged[v][0] if v in merged else v
            if rv not in reps:
                reps.append(rv)
        if not reps:
            # fully determined: the scalar at the fixed assignment
            idx = [fixed[v] for v in scope]
            val = f.table[sum(idx[j] * strides[j] for j in range(len(scope)))]
            if val == 0:
                raise Contradiction("factor %d is zero at the forced assignment" % f.origin)
            const *= Fr(val)
            continue
        qcard = tuple(int(card[v]) for v in reps)
        pos = {v: j for j, v in enumerate(reps)}
        tab = []
        for q in itertools.product(*[range(c) for c in qcard]):
            idx = []
            for v in scope:
                if v in fixed:
                    idx.append(fixed[v])
                elif v in merged:
                    rt, pr = merged[v]
                    idx.append(q[pos[rt]] ^ pr)
                else:
                    idx.append(q[pos[v]])
            tab.append(Fr(f.table[sum(idx[j] * strides[j] for j in range(len(scope)))]))
        facs.append(M.Factor(scope=tuple(reps), card=qcard, table=tab, origin=f.origin, scale=f.scale))
    return M.Restricted(model=r.model, evidence=dict(r.evidence), factors=facs, free=free_q,
                        card={v: int(card[v]) for v in free_q}, constant=const, impossible_factor=None)


def restore(iv_q, decl, r_free, card):
    """Every original free variable's published row from the quotient's: a representative keeps its
    row; a merged variable's state s is the representative's state s XOR parity; a fixed variable is
    the exact point mass at its state."""
    fixed = {int(v): int(s) for v, s in decl["fixed"].items()}
    merged = {int(v): (int(a[0]), int(a[1])) for v, a in decl["merged"].items()}
    out = {}
    for v in r_free:
        if v in fixed:
            out[v] = [(Fr(1), Fr(1)) if s == fixed[v] else (Fr(0), Fr(0)) for s in range(int(card[v]))]
        elif v in merged:
            rt, pr = merged[v]
            row = iv_q[rt]
            out[v] = [row[s ^ pr] for s in range(2)]
        else:
            out[v] = list(iv_q[v])
    return out


def quotient_price(plan_dense, plan_q):
    """The admission figures: enumerated schedule rows of the dense identity plan against the
    quotient's (the same unit the support pilot used), the ratio and the verdict."""
    from mdi.support import dense_enumerated_schedule_rows
    d = dense_enumerated_schedule_rows(plan_dense)
    q = dense_enumerated_schedule_rows(plan_q)
    ratio = (d / q) if q else float("inf")
    return {"dense_schedule_rows": int(d), "quotient_schedule_rows": int(q), "reduction_ratio": ratio,
            "admitted": bool(ratio >= MIN_REDUCTION_RATIO), "min_reduction_ratio": MIN_REDUCTION_RATIO,
            "dense_largest_bag": int(plan_dense.largest_bag_entries), "quotient_largest_bag": int(plan_q.largest_bag_entries),
            "dense_free": len(plan_dense.free), "quotient_free": len(plan_q.free)}


# a process-local, content-keyed cache so the executor reuses discovery's recognition within ONE invocation
_RECOGNITION_CACHE = {}


def recognition_key(factors, free):
    return (tuple(int(v) for v in free), tuple((tuple(f.scope), tuple(int(c) for c in f.card), tuple(str(Fr(x)) for x in f.table)) for f in factors))


def recognize_cached(factors, free, card, **kw):
    key = recognition_key(factors, free)
    hit = _RECOGNITION_CACHE.get(key)
    if hit is not None:
        return hit, False
    decl = recognize(factors, free, card, **kw)
    _RECOGNITION_CACHE[key] = decl
    if len(_RECOGNITION_CACHE) > 4:
        _RECOGNITION_CACHE.pop(next(iter(_RECOGNITION_CACHE)))
    return decl, True
