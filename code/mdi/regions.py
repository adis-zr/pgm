"""Regional coarsening: bounded region discovery, local masses and marks, and
the checkable cell merge with its exact rational admission test (spec section 5).

Every certificate here is exact rational. Floating point may PROPOSE; it never
certifies.
"""
from __future__ import annotations
import sys
sys.set_int_max_str_digits(0)
from fractions import Fraction as Fr
from dataclasses import dataclass, field
import itertools
from mdi import config as K


class CapExceeded(Exception):
    """A frozen cap was reached. Never authorizes a merge or a deletion."""


class Declined(Exception):
    """A certificate declined. Distinct from a resource refusal."""


def bitlen_ok(q: Fr) -> bool:
    return (q.numerator.bit_length() <= K.CAPS["rational_bit_length"]
            and q.denominator.bit_length() <= K.CAPS["rational_bit_length"])


# ============================ 5.1 region discovery ============================

def factor_adjacency(free, factors):
    """Factor hyperedges define adjacency."""
    adj = {v: set() for v in free}
    for f in factors:
        sc = [v for v in f.scope if v in adj]
        for a in sc:
            for b in sc:
                if a != b:
                    adj[a].add(b)
    return adj


def _interaction_variation(f) -> Fr:
    """A certified scalar summarizing a pair factor's response variation:
    max/min over positive entries, or 0 when a zero is present (handled
    separately). Used only to ORDER candidates, never to certify."""
    pos = [t for t in f.table if t > 0]
    if not pos or len(pos) != len(f.table):
        return Fr(0)
    return max(pos) / min(pos)


def grow_partition(free, card, factors, adj, mode, cap_assign):
    """Disjoint connected regions by deterministic growth.

    mode 'ascending_id'      : seeds and growth by ascending original ID
    mode 'descending_degree' : seeds by descending degree, ties by ID
    mode 'interaction'       : growth prioritizing certified pair-factor
                               interaction variation
    A variable joins only while the region's joint-state cap is met; ties use
    original IDs. Singleton regions are retained where no merge is available.
    """
    # per-edge variation score (exact rationals; ordering only)
    escore = {}
    for f in factors:
        if len(f.scope) == 2:
            a, b = f.scope
            if a in adj and b in adj:
                s = _interaction_variation(f)
                key = (min(a, b), max(a, b))
                escore[key] = max(escore.get(key, Fr(0)), s)

    if mode == "descending_degree":
        seeds = sorted(free, key=lambda v: (-len(adj[v]), v))
    else:
        seeds = sorted(free)

    assigned = {}
    regions = []
    for s in seeds:
        if s in assigned:
            continue
        reg = [s]
        prod = card[s]
        assigned[s] = len(regions)
        frontier = set(adj[s]) - set(assigned)
        while frontier:
            cands = sorted(frontier)
            if mode == "interaction":
                def k(v):
                    best = Fr(0)
                    for r in reg:
                        key = (min(v, r), max(v, r))
                        if key in escore and escore[key] > best:
                            best = escore[key]
                    return (-best, v)
                cands.sort(key=k)
            elif mode == "descending_degree":
                cands.sort(key=lambda v: (-len(adj[v]), v))
            placed = False
            for v in cands:
                if v in assigned:
                    frontier.discard(v)
                    continue
                if prod * card[v] <= cap_assign:
                    reg.append(v)
                    prod *= card[v]
                    assigned[v] = len(regions)
                    frontier.discard(v)
                    frontier |= (set(adj[v]) - set(assigned))
                    placed = True
                    break
                frontier.discard(v)
            if not placed:
                break
        regions.append(tuple(sorted(reg)))
    # every free variable in exactly one region
    seen = set()
    for r in regions:
        for v in r:
            assert v not in seen, "regions overlap"
            seen.add(v)
    assert seen == set(free), "regions do not cover the free variables"
    return regions


PARTITION_MODES = ["ascending_id", "descending_degree", "interaction", "singleton"]


def propose_partitions(free, card, factors, cap_assign=None):
    """At most four deterministic partition candidates (spec cap)."""
    cap_assign = cap_assign or K.CAPS["region_tuple_assignments"]
    adj = factor_adjacency(free, factors)
    out = []
    for mode in PARTITION_MODES[:K.CAPS["partition_proposals_per_level"]]:
        if mode == "singleton":
            regs = tuple((v,) for v in sorted(free))
        else:
            regs = tuple(grow_partition(free, card, factors, adj, mode, cap_assign))
        out.append({"mode": mode, "regions": regs})
    # deduplicate while preserving order
    seen, uniq = set(), []
    for c in out:
        if c["regions"] in seen:
            continue
        seen.add(c["regions"]); uniq.append(c)
    return uniq


# ======================= 5.2 local masses and marks =======================

@dataclass
class RegionData:
    vars: tuple
    boundary: tuple                   # variables incident to crossing factors
    internal_factors: list            # indices into the model's factor list
    crossing_factors: list            # indices, each owned once GLOBALLY
    A: dict                           # boundary assignment tuple -> exact mass
    marks: dict                       # (var, state) -> {b: exact marked mass}
    removed_zero: int = 0

    def n_boundary_states(self):
        return len(self.A)


def region_data(region, card, factors, queries, assign_crossing_to=None,
                budget=None, deadline=None):
    """Compute A_R(b) and A_{R,i,a}(b) in ONE bounded local enumeration.

    Factors wholly inside R form w_R. Others are crossing factors. Zero internal
    masses are removed exactly.
    """
    rset = set(region)
    internal, crossing = [], []
    for fi, f in enumerate(factors):
        sc = set(f.scope)
        if sc <= rset:
            internal.append(fi)
        elif sc & rset:
            crossing.append(fi)
    boundary = tuple(sorted({v for fi in crossing for v in factors[fi].scope
                             if v in rset}))
    # interior variables are summed out
    interior = tuple(v for v in region if v not in boundary)

    nb = 1
    for v in boundary:
        nb *= card[v]
    ni = 1
    for v in interior:
        ni *= card[v]
    if nb * ni > K.CAPS["region_tuple_assignments"] * 64:
        raise CapExceeded("region %s local space %d exceeds the enumeration cap"
                          % (region, nb * ni))

    want = [(v, s) for v in region if v in queries for s in range(card[v])]
    A, marks = {}, {(v, s): {} for (v, s) in want}

    bcards = [card[v] for v in boundary]
    icards = [card[v] for v in interior]
    _seen = 0
    for bcombo in itertools.product(*[range(c) for c in bcards]):
        if deadline is not None:
            _seen += 1
            if (_seen & 0x3F) == 0:
                deadline()
        b = tuple(bcombo)
        tot = Fr(0)
        mk = {key: Fr(0) for key in want}
        for icombo in itertools.product(*[range(c) for c in icards]):
            a = dict(zip(boundary, bcombo))
            a.update(dict(zip(interior, icombo)))
            w = Fr(1)
            for fi in internal:
                f = factors[fi]
                st = f.strides()
                off = 0
                for k, v in enumerate(f.scope):
                    off += a[v] * st[k]
                e = f.table[off]
                if e == 0:
                    w = Fr(0); break
                w *= e
            if w == 0:
                continue
            if not bitlen_ok(w):
                raise CapExceeded("local weight exceeded the rational bit cap")
            tot += w
            for (v, s) in want:
                if a[v] == s:
                    mk[(v, s)] += w
        if tot == 0:
            continue                               # exact zero-mass removal
        A[b] = tot
        for key in want:
            if mk[key] != 0:
                marks[key][b] = mk[key]
    removed = nb - len(A)
    # sum_a N_{i,a}(b) == A(b) for every boundary assignment (checked invariant)
    for v in region:
        if v not in queries:
            continue
        for b in A:
            s = sum(marks[(v, s2)].get(b, Fr(0)) for s2 in range(card[v]))
            if s != A[b]:
                raise AssertionError("marks do not sum to the mass at %s/%s" % (region, b))
    return RegionData(vars=tuple(region), boundary=boundary,
                      internal_factors=internal, crossing_factors=crossing,
                      A=A, marks=marks, removed_zero=removed)


# ============ 5.3 / 5.4 the cell merge and its exact admission test ============

def crossing_profile(f, region_vars, card):
    """Enumerate the factor's arguments OUTSIDE the region, returning, for each
    in-region projection, the vector of entries over outside assignments.

    Returns (in_keys, out_count, table) where table[in_key] is a tuple of exact
    entries indexed by the outside assignment, in a fixed deterministic order.
    """
    rset = set(region_vars)
    inside = [k for k, v in enumerate(f.scope) if v in rset]
    outside = [k for k, v in enumerate(f.scope) if v not in rset]
    st = f.strides()
    icards = [f.card[k] for k in inside]
    ocards = [f.card[k] for k in outside]
    nout = 1
    for c in ocards:
        nout *= c
    tbl = {}
    for icombo in itertools.product(*[range(c) for c in icards]):
        row = []
        for ocombo in itertools.product(*[range(c) for c in ocards]):
            off = 0
            for k, d in zip(inside, icombo):
                off += d * st[k]
            for k, d in zip(outside, ocombo):
                off += d * st[k]
            row.append(f.table[off])
        tbl[tuple(icombo)] = tuple(row)
    return [f.scope[k] for k in inside], nout, tbl


def ratio_extrema(row_b, row_r):
    """Exact rational L and U over the COMMON POSITIVE entries, after checking
    identical zero masks. Never forms 0/0.

    Returns (L, U) or raises Declined when the zero masks differ.
    """
    if len(row_b) != len(row_r):
        raise Declined("profile length mismatch")
    L = U = None
    for yb, yr in zip(row_b, row_r):
        zb, zr = (yb == 0), (yr == 0)
        if zb != zr:
            raise Declined("zero masks differ")
        if zb and zr:
            continue                        # both zero: excluded, no 0/0
        q = Fr(yb) / Fr(yr)
        if L is None or q < L:
            L = q
        if U is None or q > U:
            U = q
    if L is None:
        # every outside assignment is zero for both: the rows agree trivially
        return Fr(1), Fr(1)
    return L, U



def aggregate_crossings(rd, factors, card, region_of, deadline=None,
                        cap_entries=None):
    """Spec 5.3: combine crossing factors with the SAME incident-region scope
    into their exact product kernel, before any profiling.

    This is NOT a cosmetic regrouping. A strictly positive multiplier preserves
    a zero-mask disagreement, but a nonnegative multiplier CONTAINING A ZERO can
    remove it: rows (0,2) and (1,3) disagree, yet multiplied by (0,7) they
    become (0,14) and (0,21), which share support and are proportional, so they
    merge with rho exactly 1. Profiling per factor therefore refuses merges that
    the permitted aggregation admits.

    Returns (profiles, detail). Each profile is (key, in_vars, n_out, table) in
    the same shape `crossing_profile` returns, so merge_region is agnostic to
    whether a profile is a single factor or a product kernel. The constituent
    factor list is preserved in `detail` for the ownership record: aggregation
    changes only how responses are PROFILED, never who owns a factor.
    """
    cap = cap_entries or (K.CAPS["region_tuple_assignments"] * 64)
    rset = set(rd.vars)
    me = region_of[rd.vars[0]]
    groups = {}
    for fi in rd.crossing_factors:
        f = factors[fi]
        key = tuple(sorted({region_of[v] for v in f.scope
                            if v in region_of and region_of[v] != me}))
        groups.setdefault(key, []).append(fi)
    profiles, detail = [], []
    for key, fis in sorted(groups.items()):
        if len(fis) == 1:
            f = factors[fis[0]]
            iv, nout, tbl = crossing_profile(f, rd.vars, card)
            profiles.append((fis[0], iv, nout, tbl))
            detail.append({"scope": key, "factors": fis, "aggregated": False})
            continue
        scope = sorted({v for fi in fis for v in factors[fi].scope})
        inside = [v for v in scope if v in rset]
        outside = [v for v in scope if v not in rset]
        nin = 1
        for v in inside:
            nin *= card[v]
        nout = 1
        for v in outside:
            nout *= card[v]
        if nin * nout > cap:
            for fi in fis:
                f = factors[fi]
                iv, no, tbl = crossing_profile(f, rd.vars, card)
                profiles.append((fi, iv, no, tbl))
            detail.append({"scope": key, "factors": fis, "aggregated": False,
                           "declined": "product kernel %d entries exceeds the "
                                       "cap %d" % (nin * nout, cap)})
            continue
        tbl, nz = {}, 0
        for ic in itertools.product(*[range(card[v]) for v in inside]):
            if deadline is not None:
                deadline()
            row = []
            for oc in itertools.product(*[range(card[v]) for v in outside]):
                a = dict(zip(inside, ic)); a.update(dict(zip(outside, oc)))
                w = Fr(1)
                for fi in fis:
                    f = factors[fi]
                    st = f.strides(); off = 0
                    for k, v in enumerate(f.scope):
                        off += a[v] * st[k]
                    e = f.table[off]
                    if e == 0:
                        w = Fr(0); break
                    w *= e
                if w == 0:
                    nz += 1
                if not bitlen_ok(w):
                    raise CapExceeded("aggregated kernel exceeded the bit cap")
                row.append(w)
            tbl[tuple(ic)] = tuple(row)
        profiles.append((("agg",) + tuple(fis), inside, nout, tbl))
        detail.append({"scope": key, "factors": fis, "aggregated": True,
                       "in_states": nin, "out_states": nout,
                       "zeros_in_product": nz})
    return profiles, detail


@dataclass
class Cell:
    rep: tuple                        # representative boundary assignment
    members: list                     # [(b, alpha)] including (rep, 1)
    rho_max: Fr = Fr(1)


@dataclass
class CoarseRegion:
    region: tuple
    boundary: tuple
    cells: list                       # list of Cell
    M: list                           # exact mass per cell
    N: dict                           # (var,state) -> list of exact marked mass
    cell_of: dict                     # boundary assignment -> cell index
    rho_region: Fr                    # max_b rho(b, rep)
    comparisons: int
    declines: dict
    aggregation: object = None        # per-group aggregation record, or None


def _profile_signature(b, profiles, bpos):
    """The exact tuple of crossing-factor response rows at boundary assignment b.

    Two assignments with the SAME signature have U=L=1 on every crossing factor,
    hence rho=1 and alpha=1: they merge exactly and unconditionally. Grouping by
    this key is O(states) instead of the O(states^2) pairwise scan, and it loses
    nothing, because exact-equality merges are precisely the ones a greedy
    pairwise scan would always accept.
    """
    sig = []
    for (fi, in_vars, nout, tbl) in profiles:
        sig.append(tbl[tuple(b[bpos[v]] for v in in_vars)])
    return tuple(sig)


def _zero_mask(sig):
    return tuple(tuple(e == 0 for e in row) for row in sig)


def merge_region(rd: RegionData, factors, card, rho_cap: Fr, queries,
                 comparison_budget=None, deadline=None, region_of=None,
                 aggregate=True):
    """Greedy cell merge with the exact admission test of spec 5.3/5.4.

    Candidates are ordered by DECREASING A_R(b), then lexicographically.
    Representatives are proposed in insertion order. A merge requires identical
    zero masks on every incident crossing factor and rho = prod U/L <= rho_cap.
    Reaching a cap never authorizes a merge.
    """
    budget = comparison_budget if comparison_budget is not None \
        else K.CAPS["profile_entry_comparisons"]

    # Precompute in-region response profiles. When `region_of` is supplied and
    # aggregation is enabled, crossing factors sharing an incident-region scope
    # are first combined into their exact product kernel (spec 5.3), which can
    # TURN A ZERO-MASK REFUSAL INTO AN EXACT MERGE.
    agg_detail = None
    if aggregate and region_of is not None:
        profiles, agg_detail = aggregate_crossings(rd, factors, card, region_of,
                                                   deadline=deadline)
    else:
        profiles = []
        for fi in rd.crossing_factors:
            f = factors[fi]
            in_vars, nout, tbl = crossing_profile(f, rd.vars, card)
            profiles.append((fi, in_vars, nout, tbl))

    order = sorted(rd.A.keys(), key=lambda b: (-rd.A[b], b))
    bpos = {v: k for k, v in enumerate(rd.boundary)}

    def proj(b, in_vars):
        return tuple(b[bpos[v]] for v in in_vars)

    cells, cell_of = [], {}
    comparisons = 0
    declines = {"zero_mask": 0, "rho": 0, "budget": 0, "exact_group": 0}

    # ---- phase 1: exact signature bucketing (linear, lossless) ----
    # Assignments sharing an identical crossing-response signature have
    # U = L = 1 everywhere, so alpha = 1 and rho = 1: an unconditional exact
    # merge. This collapses the dominant cost without weakening the certificate.
    sig_of, buckets = {}, {}
    _n = 0
    for b in order:
        if deadline is not None:
            _n += 1
            if (_n & 0x3F) == 0:
                deadline()
        sig = _profile_signature(b, profiles, bpos)
        comparisons += sum(len(row) for row in sig)
        if comparisons > budget:
            declines["budget"] += 1
            raise CapExceeded("signature budget exhausted while bucketing")
        sig_of[b] = sig
        buckets.setdefault(sig, []).append(b)
    for sig, members in sorted(buckets.items(), key=lambda kv: (-rd.A[kv[1][0]], kv[1][0])):
        rep = members[0]
        cell = Cell(rep=rep, members=[(mb, Fr(1)) for mb in members], rho_max=Fr(1))
        cells.append(cell)
        for mb in members:
            cell_of[mb] = len(cells) - 1
        if len(members) > 1:
            declines["exact_group"] += len(members) - 1

    # ---- phase 2: bounded approximate refinement across distinct signatures ----
    # Only representatives are compared, and only within equal zero masks. The
    # pass is skipped once the comparison budget is spent; a cap NEVER authorizes
    # a merge, it only stops further merging.
    if len(cells) > 1:
        by_mask = {}
        for ci, cell in enumerate(cells):
            by_mask.setdefault(_zero_mask(sig_of[cell.rep]), []).append(ci)
        merged_into = {}
        for mask, idxs in sorted(by_mask.items(), key=lambda kv: kv[1]):
            keep = []
            for ci in idxs:
                if deadline is not None:
                    deadline()
                if comparisons > budget:
                    declines["budget"] += 1
                    break
                placed = False
                for kj in keep:
                    try:
                        alpha, rho = Fr(1), Fr(1)
                        sb, sr = sig_of[cells[ci].rep], sig_of[cells[kj].rep]
                        for rb, rr in zip(sb, sr):
                            comparisons += len(rb)
                            if comparisons > budget:
                                declines["budget"] += 1
                                raise CapExceeded("refinement budget exhausted")
                            L, U = ratio_extrema(rb, rr)
                            if L <= 0:
                                raise Declined("nonpositive ratio lower bound")
                            alpha *= L
                            rho *= U / L
                            if rho > rho_cap:
                                raise Declined("rho exceeds the allocated cap")
                        if not bitlen_ok(alpha) or not bitlen_ok(rho):
                            raise Declined("certificate exceeded the rational bit cap")
                    except Declined as e:
                        if "zero mask" in str(e):
                            declines["zero_mask"] += 1
                        else:
                            declines["rho"] += 1
                        continue
                    except CapExceeded:
                        break
                    merged_into[ci] = (kj, alpha, rho)
                    placed = True
                    break
                if not placed:
                    keep.append(ci)
        if merged_into:
            # rebuild the cell list, folding merged cells into their targets
            newcells, remap = [], {}
            for ci, cell in enumerate(cells):
                if ci in merged_into:
                    continue
                remap[ci] = len(newcells)
                newcells.append(Cell(rep=cell.rep, members=list(cell.members),
                                     rho_max=cell.rho_max))
            for ci, (kj, alpha, rho) in merged_into.items():
                tgt = remap.get(kj)
                if tgt is None:
                    continue
                for (mb, al) in cells[ci].members:
                    newcells[tgt].members.append((mb, al * alpha))
                if rho > newcells[tgt].rho_max:
                    newcells[tgt].rho_max = rho
            cells = newcells
            cell_of = {}
            for ci, cell in enumerate(cells):
                for (mb, _) in cell.members:
                    cell_of[mb] = ci

    # cell masses and marks use the SAME alpha
    M = []
    N = {key: [] for key in rd.marks}
    for cell in cells:
        m = Fr(0)
        for (b, al) in cell.members:
            m += al * rd.A[b]
        M.append(m)
        for key in rd.marks:
            n = Fr(0)
            for (b, al) in cell.members:
                n += al * rd.marks[key].get(b, Fr(0))
            N[key].append(n)
    rho_region = max((c.rho_max for c in cells), default=Fr(1))
    cr = CoarseRegion(region=rd.vars, boundary=rd.boundary, cells=cells, M=M,
                      N=N, cell_of=cell_of, rho_region=rho_region,
                      comparisons=comparisons, declines=declines)
    cr.aggregation = agg_detail
    return cr


def level_distortion(coarse_regions) -> Fr:
    """R_level = prod_R max_b rho_R(b, rep)."""
    R = Fr(1)
    for cr in coarse_regions:
        R *= cr.rho_region
    return R


# ======================= 5.5 distribution-sensitive deletion =======================

def deletion_bounds(rd: RegionData, factors, card, D):
    """Spec 5.5. For the proposed deleted set D compute

      U_R = sum_{b in D}     A(b) * prod_{f incident} max_y psi_f(b_f, y)
      L_R = sum_{b not in D} A(b) * prod_{f incident} min_y psi_f(b_f, y)

    If L_R > 0 the deleted event has conditional probability at most
    U_R/(U_R+L_R) for every exterior configuration of positive weight.
    Hard zeros can force L_R = 0: then DECLINE this test.
    """
    profiles = []
    for fi in rd.crossing_factors:
        f = factors[fi]
        in_vars, nout, tbl = crossing_profile(f, rd.vars, card)
        profiles.append((fi, in_vars, tbl))
    bpos = {v: k for k, v in enumerate(rd.boundary)}

    def mm(b):
        hi, lo = Fr(1), Fr(1)
        for (fi, in_vars, tbl) in profiles:
            row = tbl[tuple(b[bpos[v]] for v in in_vars)]
            hi *= max(row)
            lo *= min(row)
        return lo, hi

    U = Fr(0); L = Fr(0)
    Dset = set(D)
    for b, a in rd.A.items():
        lo, hi = mm(b)
        if b in Dset:
            U += a * hi
        else:
            L += a * lo
    if L <= 0:
        raise Declined("L_R = 0 (hard zeros): deletion test declined")
    return U, L, U / (U + L)


def propose_deletions(rd: RegionData, factors, card, radius: Fr, max_tests=None):
    """Test at most eight geometrically spaced prefix sizes of the SMALLEST
    local boundary masses. Returns the largest certified deletion, or None."""
    ntest = max_tests or K.CAPS["deletion_prefix_tests"]
    order = sorted(rd.A.keys(), key=lambda b: (rd.A[b], b))
    n = len(order)
    if n <= 1:
        return None
    sizes, s = [], 1
    while s < n and len(sizes) < ntest:
        sizes.append(s)
        s = max(s + 1, (s * 3) // 2)
    best = None
    for sz in sizes:
        D = order[:sz]
        try:
            U, L, p = deletion_bounds(rd, factors, card, D)
        except Declined:
            return best
        if p <= radius:
            best = {"deleted": list(D), "U": U, "L": L, "prob_bound": p, "size": sz}
        else:
            break
    return best
