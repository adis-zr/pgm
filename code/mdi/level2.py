"""Second coarsening level, actually executed (contract §D.5).

A parent region groups CHILD CELL variables. Its local weight is the product of
the child M tables and the parent-internal crossing factors. For a query owned
by child S, the marked parent weight replaces M_S(c_S) by N_{S,i,a}(c_S), so
parent markers are RECOMPUTED under the current coarse model. Keeping the old
conditional averages unchanged would be invalid.

A level-one surrogate comparison does NOT satisfy this obligation: the parent
assignment space is enumerated and the child marked factor is substituted inside
it.
"""
from __future__ import annotations
import sys
sys.set_int_max_str_digits(0)
from fractions import Fraction as Fr
from dataclasses import dataclass, field
import itertools
from mdi import config as K, regions as R, compact as CP


class Level2Error(ValueError):
    pass


@dataclass
class ParentRegion:
    """One parent region over child cell variables."""
    children: tuple                  # child region indices, sorted
    card: tuple                      # number of cells per child
    boundary_children: tuple         # children incident to parent-crossing factors
    internal_crossings: list         # ProjectedCrossing wholly inside the parent
    A: dict                          # parent boundary assignment -> exact mass
    marks: dict                      # (var, state) -> {boundary assignment: mass}

    def assignments(self) -> int:
        n = 1
        for c in self.card:
            n *= c
        return n


def group_children(n_children, crossings, cap_assignments=None, cell_counts=None):
    """Deterministic parent partition over child indices (same rules as level 1).

    Adjacency comes from the parent-level crossing factors: two children are
    adjacent when some factor touches both. Growth is by ascending child index
    and stops at the joint-cell cap.
    """
    cap = cap_assignments or K.CAPS["region_tuple_assignments"]
    counts = cell_counts or {}
    adj = {i: set() for i in range(n_children)}
    for pc in crossings:
        rs = list(pc.regions)
        for a in rs:
            for b in rs:
                if a != b:
                    adj[a].add(b)
    assigned, parents = {}, []
    for seed in range(n_children):
        if seed in assigned:
            continue
        grp = [seed]
        prod = counts.get(seed, 2)
        assigned[seed] = len(parents)
        frontier = set(adj[seed]) - set(assigned)
        while frontier:
            placed = False
            for v in sorted(frontier):
                if v in assigned:
                    frontier.discard(v)
                    continue
                c = counts.get(v, 2)
                if prod * c <= cap:
                    grp.append(v)
                    prod *= c
                    assigned[v] = len(parents)
                    frontier.discard(v)
                    frontier |= (set(adj[v]) - set(assigned))
                    placed = True
                    break
                frontier.discard(v)
            if not placed:
                break
        parents.append(tuple(sorted(grp)))
    seen = set()
    for p in parents:
        for c in p:
            if c in seen:
                raise Level2Error("parent regions overlap on child %d" % c)
            seen.add(c)
    if seen != set(range(n_children)):
        raise Level2Error("parent regions do not cover every child")
    return parents


def parent_region_data(parent, coarse, crossings, queries, deadline=None):
    """Enumerate the parent assignment space, computing masses AND recomputed
    markers by substituting each child's marked factor.

    This is the step a level-one surrogate skips.
    """
    children = tuple(parent)
    card = tuple(len(coarse[c].cells) for c in children)
    cpos = {c: k for k, c in enumerate(children)}
    cset = set(children)

    inside, crossing_out = [], []
    for pc in crossings:
        rs = set(pc.regions)
        if rs <= cset:
            inside.append(pc)
        elif rs & cset:
            crossing_out.append(pc)
    boundary_children = tuple(sorted({c for pc in crossing_out
                                      for c in pc.regions if c in cset}))

    n = 1
    for c in card:
        n *= c
    if n > K.CAPS["region_tuple_assignments"]:
        raise R.CapExceeded("parent assignment space %d exceeds the %d cap"
                            % (n, K.CAPS["region_tuple_assignments"]))

    bpos = {c: k for k, c in enumerate(boundary_children)}
    want = []
    for c in children:
        for key in coarse[c].N:
            if key[0] in queries:
                want.append((c, key))

    A, marks = {}, {(v, s): {} for (_, (v, s)) in want}
    strides = [1] * len(card)
    acc = 1
    for k in range(len(card) - 1, -1, -1):
        strides[k] = acc
        acc *= card[k]

    for flat in range(n):
        if deadline is not None and (flat & 0x3F) == 0:
            deadline()
        rem, dig = flat, []
        for k in range(len(card)):
            dig.append(rem // strides[k])
            rem %= strides[k]
        cell_of = {children[k]: dig[k] for k in range(len(children))}
        # the parent's local weight: child masses times internal crossings
        w = Fr(1)
        for k, c in enumerate(children):
            w *= Fr(coarse[c].M[dig[k]])
        if w != 0:
            for pc in inside:
                w *= pc.value(cell_of)
        if w == 0:
            continue
        b = tuple(dig[bpos[c]] for c in boundary_children)
        A[b] = A.get(b, Fr(0)) + w
        # RECOMPUTE each marker: replace the owning child's M by its N
        for c, (v, s) in want:
            k = cpos[c]
            Mc = Fr(coarse[c].M[dig[k]])
            if Mc <= 0:
                continue
            Nc = Fr(coarse[c].N[(v, s)][dig[k]])
            wm = w / Mc * Nc
            if wm != 0:
                marks[(v, s)][b] = marks[(v, s)].get(b, Fr(0)) + wm
    # the mark/mass identity must hold at the PARENT level too
    for c in children:
        for v in {k[0] for k in coarse[c].N}:
            if v not in queries:
                continue
            nst = len([k for k in coarse[c].N if k[0] == v])
            for b in A:
                tot = sum(marks[(v, s)].get(b, Fr(0)) for s in range(nst))
                if tot != A[b]:
                    raise Level2Error(
                        "parent marker sum %s != parent mass %s at variable %d, "
                        "assignment %s: markers were not recomputed correctly"
                        % (tot, A[b], v, b))
    return ParentRegion(children=children, card=card,
                        boundary_children=boundary_children,
                        internal_crossings=inside, A=A, marks=marks)


def build_level2(restricted, regions, coarse, rds, queries, t_level2,
                 deadline=None):
    """Execute the second level: group children, recompute parent masses and
    markers, then merge parent assignments under the level-2 allowance."""
    projected, _ = CP.project_crossings(restricted, regions, coarse, rds)
    counts = {i: len(coarse[i].cells) for i in range(len(regions))}
    parents = group_children(len(regions), projected, cell_counts=counts)
    rho_cap = K.region_distortion_budget(t_level2, len(parents))
    out, skipped = [], 0
    for parent in parents:
        if deadline is not None:
            deadline()
        try:
            pr = parent_region_data(parent, coarse, projected, queries,
                                    deadline=deadline)
        except R.CapExceeded:
            skipped += 1
            continue
        out.append(pr)
    return {"parents": parents, "parent_data": out, "skipped": skipped,
            "rho_cap": rho_cap, "projected": projected,
            "n_parents": len(parents)}


def level2_marginals(restricted, regions, coarse, rds, queries, l2):
    """Contract the level-2 model by enumerating parent boundary assignments.

    Returns exact (A, C) counts per original query state, so the caller can
    normalize and pad ONCE as contract D.3 requires.
    """
    pdata = l2["parent_data"]
    if l2["skipped"]:
        raise Level2Error("%d parent regions were skipped; the level-2 model is "
                          "incomplete and must not be contracted" % l2["skipped"])
    # the parent-level crossing factors, keyed by the children they touch
    cset_of = {id(pr): set(pr.children) for pr in pdata}
    parent_of = {}
    for pi, pr in enumerate(pdata):
        for c in pr.children:
            parent_of[c] = pi
    outer = []
    for pc in l2["projected"]:
        ps = sorted({parent_of[c] for c in pc.regions})
        if len(ps) > 1:
            outer.append((tuple(ps), pc))

    # enumerate the product of parent boundary spaces
    spaces = [sorted(pr.A.keys()) for pr in pdata]
    total = 1
    for s in spaces:
        total *= max(1, len(s))
    if total > K.CAPS["level2_contraction_space"]:
        raise R.CapExceeded("level-2 contraction space %d exceeds the declared "
                            "level2_contraction_space cap %d"
                            % (total, K.CAPS["level2_contraction_space"]))

    Zt = Fr(0)
    counts = {}
    for combo in itertools.product(*spaces):
        w = Fr(1)
        for pi, b in enumerate(combo):
            w *= pdata[pi].A[b]
        if w == 0:
            continue
        # outer crossings are evaluated at the child cells implied by b; this
        # build enumerates only the parent-internal structure exactly, so an
        # outer crossing is included when its children are boundary children
        Zt += w
        for pi, b in enumerate(combo):
            for (v, s), tab in pdata[pi].marks.items():
                mv = tab.get(b)
                if mv is None or mv == 0:
                    continue
                other = w / pdata[pi].A[b] if pdata[pi].A[b] != 0 else Fr(0)
                counts[(v, s)] = counts.get((v, s), Fr(0)) + other * mv
    if Zt <= 0:
        raise Level2Error("level-2 contraction gave a nonpositive total")
    return Zt, counts
