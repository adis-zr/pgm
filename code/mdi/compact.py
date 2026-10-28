"""Compact projected crossing factors and direct original-query readout
(contract §D).

A crossing factor is NOT expanded into a Cartesian table over its incident
cells. It keeps the ORIGINAL table plus, per incident region, a map from that
region's cell index to the offset its representative contributes. Evaluation
sums offsets and indexes the original table once.

`coarse.build_coarse_model` materialized the full product, which for Pedigree's
worst scope would have been 1.6e9 entries for a single factor.
"""
from __future__ import annotations
import sys
sys.set_int_max_str_digits(0)
from fractions import Fraction as Fr
from dataclasses import dataclass, field


class CompactError(ValueError):
    pass


@dataclass
class ProjectedCrossing:
    """One original crossing factor, stored once, evaluated by offset lookup."""
    origin: int
    scope: tuple                 # ORIGINAL variable ids, declaration order
    card: tuple                  # aligned with scope
    table: list                  # the ORIGINAL exact entries, unexpanded
    regions: tuple               # incident region indices, sorted
    offsets: dict                # region index -> [offset per cell]
    covered: tuple               # the scope positions this factor's regions cover

    def entries(self) -> int:
        n = 1
        for c in self.card:
            n *= c
        return n

    def value(self, cell_of_region: dict) -> Fr:
        """Evaluate at one assignment of cells to incident regions."""
        off = 0
        for ri in self.regions:
            try:
                row = self.offsets[ri]
            except KeyError:
                raise CompactError("factor %d has no projection for region %d"
                                   % (self.origin, ri))
            ci = cell_of_region.get(ri)
            if ci is None:
                raise CompactError(
                    "factor %d: region %d has no assigned cell. A missing "
                    "projection must never be treated as the value 1."
                    % (self.origin, ri))
            if not (0 <= ci < len(row)):
                raise CompactError("factor %d region %d cell %d out of range"
                                   % (self.origin, ri, ci))
            off += row[ci]
        if not (0 <= off < len(self.table)):
            raise CompactError("factor %d: offset %d outside its table"
                               % (self.origin, off))
        return self.table[off]


def project_crossings(restricted, regions, coarse, rds):
    """Build one ProjectedCrossing per original crossing factor.

    Every scoped variable must be covered by some incident region's boundary,
    and every representative must supply a concrete offset. A variable missing
    from a projection is an error, never a silent 1.
    """
    region_of = {}
    for i, reg in enumerate(regions):
        for v in reg:
            region_of[v] = i
    out = []
    for f in restricted.factors:
        rs = sorted({region_of[v] for v in f.scope if v in region_of})
        if len(rs) <= 1:
            continue
        st = f.strides()
        offsets = {}
        covered = []
        for ri in rs:
            rd = rds[ri]
            bpos = {v: k for k, v in enumerate(rd.boundary)}
            # the scope positions this region is responsible for
            mine = [k for k, v in enumerate(f.scope) if region_of.get(v) == ri]
            for k in mine:
                v = f.scope[k]
                if v not in bpos:
                    raise CompactError(
                        "factor %d scopes variable %d in region %d, but that "
                        "variable is not on the region's boundary, so no "
                        "representative can supply its value"
                        % (f.origin, v, ri))
            covered.extend(mine)
            row = []
            for cell in coarse[ri].cells:
                rep = cell.rep
                o = 0
                for k in mine:
                    v = f.scope[k]
                    o += rep[bpos[v]] * st[k]
                row.append(o)
            offsets[ri] = row
        if sorted(covered) != list(range(len(f.scope))):
            raise CompactError(
                "factor %d: scope positions %s are not fully covered by its "
                "incident regions (covered %s)"
                % (f.origin, list(range(len(f.scope))), sorted(covered)))
        out.append(ProjectedCrossing(
            origin=f.origin, scope=tuple(f.scope), card=tuple(f.card),
            table=list(f.table), regions=tuple(rs), offsets=offsets,
            covered=tuple(sorted(covered))))
    return out, region_of


def cartesian_entries_avoided(projected, coarse):
    """How many table entries the Cartesian construction would have built."""
    total = 0
    for pc in projected:
        n = 1
        for ri in pc.regions:
            n *= len(coarse[ri].cells)
        total += n
    return total


def compact_entries(projected):
    """What the compact form actually stores: the original tables plus maps."""
    tables = sum(pc.entries() for pc in projected)
    maps = sum(len(row) for pc in projected for row in pc.offsets.values())
    return {"original_table_entries": tables, "offset_map_entries": maps,
            "total": tables + maps}


# ------------------- direct original-query readout (§D.3) -------------------

def query_counts(region_index, coarse, rds, var, state, cavity):
    """Contract D.3: event and complement counts for ONE original state.

        A = sum_c H_R(c) * N_{i,a}(c)
        C = sum_c H_R(c) * (M_R(c) - N_{i,a}(c))

    `cavity` maps a cell index to its exact H_R(c), the product of everything
    outside the region. M_R is excluded by a zero-safe product supplied by the
    caller, never by division, and the complement is formed from M - N rather
    than from 1 minus a rounded probability.
    """
    cr = coarse[region_index]
    key = (var, state)
    if key not in cr.N:
        raise CompactError("region %d holds no marker for variable %d state %d; "
                           "query ownership is wrong" % (region_index, var, state))
    A = Fr(0)
    C = Fr(0)
    for ci in range(len(cr.cells)):
        H = cavity.get(ci)
        if H is None:
            raise CompactError("cavity is missing cell %d" % ci)
        H = Fr(H)
        N = Fr(cr.N[key][ci])
        M = Fr(cr.M[ci])
        if N > M:
            raise CompactError("marker exceeds its mass at cell %d (%s > %s)"
                               % (ci, N, M))
        A += H * N
        C += H * (M - N)
    if A < 0 or C < 0:
        raise CompactError("negative count")
    return A, C


def normalize_once(A: Fr, C: Fr, pad: Fr, eps: Fr):
    """Normalize and pad ONCE per original output.

    The padded-cell approach padded per cell and then combined, which inflated a
    tiny event requested at width 0.01 to width 0.02. Here the ratio is formed
    first from exact counts, then padded once.
    """
    A, C, pad, eps = Fr(A), Fr(C), Fr(pad), Fr(eps)
    if A + C <= 0:
        raise CompactError("no positive total: cannot normalize")
    q = A / (A + C)
    lo = max(Fr(0), q - pad)
    hi = min(Fr(1), q + pad)
    if hi - lo > eps:
        raise CompactError("padded width %s exceeds eps %s" % (hi - lo, eps))
    return lo, hi


def payload(coarse, region_index, var, state, cell) -> Fr:
    """g_{i,a}(C) = N/M, the fixed query observable (contract D.4)."""
    cr = coarse[region_index]
    M = Fr(cr.M[cell])
    if M <= 0:
        raise CompactError("cell %d has zero mass; g is undefined" % cell)
    return Fr(cr.N[(var, state)][cell]) / M


def tilted_marked(U: Fr, g: Fr):
    """Contract D.4: under a compensated/tilted unary U the observable stays
    g = N/M, so the marked pair is (U*g, U*(1-g)). Reusing the uncompensated N
    as the new marked factor would lose the gauge and self-term corrections."""
    U, g = Fr(U), Fr(g)
    if not (0 <= g <= 1):
        raise CompactError("payload g=%s outside [0,1]" % g)
    return U * g, U * (Fr(1) - g)
