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
        # `dig` is indexed over ALL children, so a boundary child's cell must
        # be read at its CHILD position (cpos), not at its position within the
        # boundary list (bpos). With children 0..11 and child 11 the sole
        # boundary, bpos[11] = 0 read child 0's cell instead: the 13-site
        # control returned P(X11=1) = 3585/7168 against a true 11/14, an error
        # of about 0.285575 versus the 0.002 allowance. The last site stayed
        # correct, which is why a test checking only that marginal passed.
        b = tuple(dig[cpos[c]] for c in boundary_children)
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


def level2_marginals(restricted, regions, coarse, rds, queries, l2,
                     deadline=None):
    """Contract the level-2 model, INCLUDING every outer crossing factor.

    The previous version built the list of factors crossing between parent
    regions and then never multiplied them, and it indexed parent boundary
    masses by the parent's own A-key while reconstructing sibling weights by
    division. On a 13-variable chain forced into three parents that gave
    P(x12=1) = 14/25 against the exact 466/843, an error of 0.007212 against the
    0.002 two-level allowance.

    This version enumerates the parents' CHILD-CELL assignments directly, so
    every projected crossing is evaluated exactly once at the cells it actually
    touches, and marked masses are carried per child-cell assignment rather than
    recovered by division.
    """
    pdata = l2["parent_data"]
    if l2["skipped"]:
        raise Level2Error("%d parent regions were skipped; the level-2 model is "
                          "incomplete and must not be contracted" % l2["skipped"])
    parents = l2["parents"]
    projected = l2["projected"]

    # every projected crossing must be accounted for EXACTLY ONCE
    parent_of = {}
    for pi, pp in enumerate(parents):
        for c in pp:
            parent_of[c] = pi
    seen = set()
    for pi, pr in enumerate(pdata):
        for pc in pr.internal_crossings:
            if id(pc) in seen:
                raise Level2Error("crossing factor %d counted twice" % pc.origin)
            seen.add(id(pc))
    outer = [pc for pc in projected if id(pc) not in seen]
    for pc in outer:
        if len({parent_of[c] for c in pc.regions}) <= 1:
            raise Level2Error(
                "crossing factor %d touches one parent but was not claimed as "
                "internal: the accounting is inconsistent" % pc.origin)

    # ---- contract the PARENT representation ----
    # The previous version enumerated every child-cell assignment directly and
    # ignored the parents entirely: clearing all parent A and marks left the
    # answer unchanged, so the numerical example it fixed proved nothing about
    # the component it was meant to establish. Direct child enumeration belongs
    # in the tiny reference oracle, not in a function claiming second-level
    # execution.
    #
    # The real second level contracts over PARENT BOUNDARY assignments, using
    # each parent's own A (local mass) and marks (marked mass), with the OUTER
    # crossings evaluated once on the child cells those boundary assignments
    # name.
    for pi, pr in enumerate(pdata):
        if not pr.A:
            raise Level2Error(
                "parent region %d has an EMPTY mass table, so there is no "
                "second-level representation to contract; a parent-based "
                "calculation cannot proceed from it" % pi)

    # the parent-level variables are the parents' boundary assignments
    pkeys = [sorted(pr.A.keys()) for pr in pdata]
    pcard = [len(k) for k in pkeys]
    ptotal = 1
    for k in pcard:
        ptotal *= k
    if ptotal > K.CAPS["level2_contraction_space"]:
        raise R.CapExceeded(
            "level-2 contraction needs %d parent boundary assignments, above "
            "the declared level2_contraction_space cap %d"
            % (ptotal, K.CAPS["level2_contraction_space"]))

    pstr = [1] * len(pcard)
    acc = 1
    for k in range(len(pcard) - 1, -1, -1):
        pstr[k] = acc
        acc *= pcard[k]

    # For an OUTER crossing we need the child cell each parent boundary
    # assignment pins. A parent boundary assignment names the cell of every
    # boundary child, which is exactly the set the outer crossings touch.
    # Verify that before relying on it.
    outer_children = {c for pc in outer for c in pc.regions}
    for pi, pr in enumerate(pdata):
        pbset = set(pr.boundary_children)
        for c in pr.children:
            if c in outer_children and c not in pbset:
                raise Level2Error(
                    "child %d carries an OUTER crossing but is not a boundary "
                    "child of parent %d, so its cell is not determined by the "
                    "parent boundary assignment and the second-level "
                    "contraction would be unsound" % (c, pi))

    Zt = Fr(0)
    counts = {}
    for flat in range(ptotal):
        if deadline is not None and (flat & 0x3F) == 0:
            deadline()
        rem, dig = flat, []
        for k in range(len(pcard)):
            dig.append(rem // pstr[k])
            rem %= pstr[k]
        # the parent boundary assignment chosen in each parent
        bsel = [pkeys[k][dig[k]] for k in range(len(pdata))]
        # the product of PARENT masses: this is the second-level law
        w = Fr(1)
        for k, pr in enumerate(pdata):
            w *= Fr(pr.A[bsel[k]])
            if w == 0:
                break
        if w == 0:
            continue
        # the cell of every boundary child, read off the parent assignments
        cell_of = {}
        for k, pr in enumerate(pdata):
            for j, c in enumerate(pr.boundary_children):
                cell_of[c] = bsel[k][j]
        # OUTER crossings only: the internal ones are already inside A
        for pc in outer:
            w *= pc.value(cell_of)
            if w == 0:
                break
        if w == 0:
            continue
        Zt += w
        # ORIGINAL markers, restored from the PARENT marked masses
        for k, pr in enumerate(pdata):
            Ab = Fr(pr.A[bsel[k]])
            if Ab <= 0:
                continue
            for key, col in pr.marks.items():
                if key[0] not in queries:
                    continue
                Nb = Fr(col.get(bsel[k], Fr(0)))
                if Nb == 0:
                    continue
                counts[key] = counts.get(key, Fr(0)) + w / Ab * Nb
    if Zt <= 0:
        raise Level2Error("level-2 contraction gave a nonpositive total")
    # the mark/mass identity must hold per variable
    byvar = {}
    for (v, s), val in counts.items():
        byvar.setdefault(v, Fr(0))
        byvar[v] += val
    for v, tot in byvar.items():
        if tot != Zt:
            raise Level2Error(
                "marker sum %s != total %s for variable %d: markers were not "
                "propagated correctly" % (tot, Zt, v))
    return Zt, counts
