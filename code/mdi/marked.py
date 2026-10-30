"""Marked models: the lifted representation every transformation acts on
(spec §4 "unique current owner", §5.6 "query restoration and a second scale").

A `Marked` model is an ordinary nonnegative factor graph over its CURRENT
variables plus, for every ORIGINAL requested (variable, state), a nonnegative
marker table over one current variable -- its unique owner -- with

        sum_a  marker[(i, a)][c]  ==  M_owner(c)        for every state c,

where M_owner is the owner's local mass factor. At the input the current
variables ARE the original ones and the markers are indicator rows. After a
regional coarsening the current variables are cells and the markers are the
fractional payloads N_{R,i,a}(C). Applying the transformation AGAIN (a second
scale) groups cell variables into parents and recomputes masses and markers
under the current coarse model, exactly as §5.6 requires.

The final contraction of any Marked model reads original outputs directly:
P(x_i = a) = sum_c P(owner = c) * marker[(i,a)][c] / M_owner(c).

Nothing here is specific to a level. Level one is `coarsen(input_marked)`;
level two is `coarsen(level_one)`; the composed route fits a collective mode
on the factors of whichever Marked model it is handed.
"""
from __future__ import annotations
import sys
sys.set_int_max_str_digits(0)
from fractions import Fraction as Fr
from dataclasses import dataclass, field
import itertools
from mdi import model as M, config as K, regions as R, compact as CP
from mdi import factors as FX


class MarkedError(ValueError):
    pass


@dataclass
class Marked:
    card: dict                    # current variable -> cardinality
    factors: list                 # M.Factor over current variables
    owner: dict                   # original variable -> current owner variable
    marks: dict                   # (orig var, state) -> list over owner states
    mass: dict                    # current variable -> list of local masses M(c)
                                  #   (identically 1 at the input level)
    orig_card: dict               # original variable -> cardinality
    level: int = 0
    certificate: dict = field(default_factory=dict)
    # True when the owner masses are ALREADY multiplied into `factors` (the
    # fitted residual's unaries own them): law_factors() then omits them,
    # while payload() keeps dividing by the owner mass as before.
    mass_absorbed: bool = False

    # ---- construction ----
    @staticmethod
    def from_restricted(r, queries):
        """Level 0: variables are the original free ones, markers indicators."""
        card = dict(r.card)
        owner = {v: v for v in sorted(queries)}
        marks = {}
        for v in sorted(queries):
            for a in range(card[v]):
                row = [Fr(0)] * card[v]
                row[a] = Fr(1)
                marks[(v, a)] = row
        mass = {v: [Fr(1)] * card[v] for v in card}
        return Marked(card=card, factors=list(r.factors), owner=owner,
                      marks=marks, mass=mass, orig_card=dict(r.card), level=0)

    def free(self):
        return sorted(self.card)

    def queries(self):
        return sorted(self.owner)

    def payload(self, v, a, c) -> Fr:
        """g_{i,a}(c) = N/M, the fixed query observable, in [0, 1]."""
        Mc = self.mass[self.owner[v]][c]
        if Mc == 0:
            return Fr(0)
        return self.marks[(v, a)][c] / Mc

    def check_identity(self):
        """sum_a N_{i,a}(c) == M_owner(c) for every owner state."""
        for v in self.owner:
            o = self.owner[v]
            for c in range(self.card[o]):
                tot = sum(self.marks[(v, a)][c] for a in range(self.orig_card[v]))
                if tot != self.mass[o][c]:
                    raise MarkedError(
                        "marker sum %s != owner mass %s at original %d, "
                        "current %d state %d" % (tot, self.mass[o][c], v, o, c))
        return True

    def mass_factors(self):
        """The current variables' local masses as unary factors (origin
        -(v+1)); omitted where the mass is identically one (level 0)."""
        out = []
        if self.mass_absorbed:
            return out
        for v in self.free():
            row = self.mass[v]
            if any(x != 1 for x in row):
                out.append(M.Factor(scope=(v,), card=(self.card[v],),
                                    table=[Fr(x) for x in row], origin=-(v + 1)))
        return out

    def law_factors(self):
        """Every factor of the represented law: masses and crossings."""
        return self.mass_factors() + list(self.factors)

    def restricted_view(self, with_mass=True, dense_cap=None):
        """An M.Restricted over the CURRENT variables (for consumers that take
        one: partition proposals need scopes only; the collective recognizer
        needs bounded dense tables and passes `dense_cap`). Projected views
        are densified ONLY when a cap is given and they fit it; otherwise
        they are passed through as views (scopes/cards intact)."""
        facs = self.law_factors() if with_mass else list(self.factors)
        if dense_cap is not None:
            facs = [FX.densify(f, dense_cap) for f in facs]
        n = (max(self.card) + 1) if self.card else 1
        mdl = M.Model(nvars=n, card=[self.card.get(v, 1) for v in range(n)],
                      factors=facs)
        if dense_cap is not None:
            mdl.validate()
        return M.Restricted(model=mdl, evidence={}, factors=facs,
                            free=self.free(), card=dict(self.card),
                            constant=Fr(1), impossible_factor=None)


# ------------------------------------------------------------- readout

def read_original(marked: Marked, Z, cell_counts):
    """cell_counts: {current var: [count per state]} with count/Z = P(state).
    Returns {orig var: [(lo, hi)]} as EXACT points (lo == hi); the caller
    widens by the certified radii. Z and counts may be (lo, hi) pairs."""
    out = {}
    for v in marked.queries():
        o = marked.owner[v]
        rows = []
        for a in range(marked.orig_card[v]):
            lo = hi = Fr(0)
            for c in range(marked.card[o]):
                g = marked.payload(v, a, c)
                if g == 0:
                    continue
                cc = cell_counts[o][c]
                if isinstance(cc, tuple):
                    lo += Fr(cc[0]) * g
                    hi += Fr(cc[1]) * g
                else:
                    lo += Fr(cc) * g
                    hi += Fr(cc) * g
            if isinstance(Z, tuple):
                Zlo, Zhi = Fr(Z[0]), Fr(Z[1])
            else:
                Zlo = Zhi = Fr(Z)
            qlo = lo / Zhi if Zhi > 0 else Fr(0)
            qhi = hi / Zlo if Zlo > 0 else Fr(1)
            rows.append((max(Fr(0), qlo), min(Fr(1), qhi)))
        out[v] = rows
    return out


# ------------------------------------------------------- one coarsening scale

@dataclass
class Scale:
    """The record of one applied regional transformation on a Marked model."""
    regions: list                 # tuples of CURRENT (input) variables
    rds: list                     # RegionData per region (input-level masses)
    coarse: list                  # CoarseRegion per region
    deletions: list               # DeletionRecord or None per region
    projected: list               # ProjectedCrossing per crossing factor
    t_level: Fr
    deletion_radius_total: Fr
    R_level: Fr
    lifted: Marked                # the OUTPUT marked model
    input_card: dict = field(default_factory=dict)   # cardinalities of the INPUT variables


def _region_data_marked(marked: Marked, region, deadline=None, budget=None):
    """A_R(b) and A_{R,i,a}(b) for a region of CURRENT variables, where the
    internal weight is the product of internal factors and each original
    marker is the marked product: the owner's mass replaced by its marker.

    At level 0 masses are 1 and markers are indicators, so this is exactly
    regions.region_data; at a higher level it is §5.6's parent construction.
    """
    rset = set(region)
    card = marked.card
    if marked.level == 0 and not marked.mass_absorbed:
        # the INPUT level: unit masses and indicator markers, so this is
        # exactly the measured, budget-charging regions.region_data
        q = {v for v in marked.queries() if v in rset}
        return R.region_data(region, card, marked.factors, q, deadline=deadline,
                             budget=budget)
    internal, crossing = [], []
    for fi, f in enumerate(marked.factors):
        sc = set(f.scope)
        if sc <= rset:
            internal.append(fi)
        elif sc & rset:
            crossing.append(fi)
    boundary = tuple(sorted({v for fi in crossing for v in marked.factors[fi].scope
                             if v in rset}))
    interior = tuple(v for v in region if v not in boundary)
    nb = 1
    for v in boundary:
        nb *= card[v]
    ni = 1
    for v in interior:
        ni *= card[v]
    if nb * ni > K.CAPS["region_local_enumeration"]:
        raise R.CapExceeded("region %s local space %d exceeds the declared "
                            "region_local_enumeration cap %d"
                            % (tuple(region), nb * ni,
                               K.CAPS["region_local_enumeration"]))
    # original queries whose CURRENT owner is in this region
    want = [(v, a) for v in marked.queries() if marked.owner[v] in rset
            for a in range(marked.orig_card[v])]
    A, marks = {}, {k: {} for k in want}
    ops = 0
    pre = [marked.factors[fi] for fi in internal]
    if deadline is not None:
        deadline()
    seen = 0
    for bc in itertools.product(*[range(card[v]) for v in boundary]):
        tot = Fr(0)
        mk = {k: Fr(0) for k in want}
        for ic in itertools.product(*[range(card[v]) for v in interior]):
            seen += 1
            if deadline is not None and (seen & 0xFF) == 0:
                deadline()
            a = dict(zip(boundary, bc))
            a.update(zip(interior, ic))
            w = Fr(1)
            for f in pre:
                e = f.at(a)
                if e == 0:
                    w = Fr(0)
                    break
                w *= e
                ops += 1
            if w == 0:
                continue
            # the current variables' local masses are factors of the law too
            for v in region:
                mv = marked.mass[v][a[v]]
                if mv == 0:
                    w = Fr(0)
                    break
                if mv != 1:
                    w *= mv
                    ops += 1
            if w == 0:
                continue
            if not R.bitlen_ok(w):
                raise R.CapExceeded("local weight exceeded the rational bit cap")
            tot += w
            ops += 1
            for (v, aa) in want:
                o = marked.owner[v]
                # replace the owner's mass by its marker: w * N/M
                Mo = marked.mass[o][a[o]]
                Nv = marked.marks[(v, aa)][a[o]]
                if Nv == 0:
                    continue
                mk[(v, aa)] += w * Nv / Mo
                ops += 1
        if tot == 0:
            continue
        if not R.bitlen_ok(tot):
            raise R.CapExceeded("ACCUMULATED region mass exceeded the bit cap")
        A[tuple(bc)] = tot
        if budget is not None:
            budget.charge("local_mass_entries", 1, "marked region mass")
        for k in want:
            if mk[k] != 0:
                if not R.bitlen_ok(mk[k]):
                    raise R.CapExceeded("ACCUMULATED marked mass exceeded the "
                                        "bit cap")
                marks[k][tuple(bc)] = mk[k]
                if budget is not None:
                    budget.charge("local_mass_entries", 1, "marked region marker")
    for v in marked.queries():
        if marked.owner[v] not in rset:
            continue
        for b in A:
            s = sum(marks[(v, a)].get(b, Fr(0))
                    for a in range(marked.orig_card[v]))
            if s != A[b]:
                raise MarkedError("marks do not sum to the mass at %s/%s"
                                  % (tuple(region), b))
    rd = R.RegionData(vars=tuple(region), boundary=boundary,
                      internal_factors=internal, crossing_factors=crossing,
                      A=A, marks=marks, removed_zero=nb - len(A),
                      construction_ops=ops)
    return rd


def coarsen(marked: Marked, regions, t_level: Fr, deletion_radius: Fr,
            deadline=None, budget=None, aggregate=True, allow_deletion=True):
    """Apply ONE regional scale to a Marked model: local masses and marked
    masses, positive-state deletion (own proof, own radius), exact cell merge
    with the §5.3/5.4 admission test, compact projection of the crossings,
    and the LIFTED Marked model whose variables are the cells.

    The queries' owners move to the cell variable of the region that holds
    them; their markers become N_{R,i,a}(C) and the owner's mass becomes
    M_R(C). The transformation errors are returned on the Scale record; the
    caller adds them by the triangle inequality across scales (§5.6).
    """
    region_of = {v: i for i, reg in enumerate(regions) for v in reg}
    cover_miss = [v for v in marked.card if v not in region_of]
    if cover_miss:
        raise MarkedError("regions do not cover variables %s" % cover_miss[:4])
    if len(region_of) != sum(len(r) for r in regions):
        raise MarkedError("regions overlap")
    nreg = len(regions)
    rho_cap = K.region_distortion_budget(t_level, nreg)
    per_region_del = (Fr(deletion_radius) / nreg) if nreg else Fr(0)
    rds, crs, dels = [], [], []
    del_total = Fr(0)
    for reg in regions:
        if deadline is not None:
            deadline()
        rd = _region_data_marked(marked, reg, deadline=deadline, budget=budget)
        drec = None
        if allow_deletion and per_region_del > 0:
            try:
                rd2, drec = R.apply_deletion(rd, marked.factors, marked.card,
                                             per_region_del)
                if drec is not None:
                    rd2.construction_ops = rd.construction_ops
                    rd = rd2
                    del_total += drec.prob_bound
            except R.Declined:
                drec = None
        cr = R.merge_region(rd, marked.factors, marked.card, rho_cap,
                            set(k[0] for k in rd.marks), deadline=deadline,
                            region_of=region_of, aggregate=aggregate)
        rds.append(rd)
        crs.append(cr)
        dels.append(drec)
    R_level = R.level_distortion(crs)
    if not K.certify_R_against_t(R_level, t_level):
        raise R.Declined("R_level %s is not certified at t=%s" % (R_level, t_level))
    # ---- the LIFTED marked model: cell variables, local mass factors,
    # COMPACT projected crossings (offset maps composed through the scale,
    # nothing expanded), moved ownership, payload markers
    ncell = [len(c.cells) for c in crs]
    lcard = {i: ncell[i] for i in range(nreg)}
    reps = {i: [tuple(c.rep) for c in crs[i].cells] for i in range(nreg)}
    bpos = {i: {v: k for k, v in enumerate(rds[i].boundary)} for i in range(nreg)}
    lfactors = []
    for f in marked.factors:
        rs = sorted({region_of[v] for v in f.scope})
        if len(rs) <= 1:
            continue
        lfactors.append(FX.as_view(f).compose(region_of, reps, bpos, ncell))
    projected = lfactors
    lowner = {}
    lmarks = {}
    for v in marked.queries():
        i = region_of[marked.owner[v]]
        lowner[v] = i
        for a in range(marked.orig_card[v]):
            lmarks[(v, a)] = [Fr(x) for x in crs[i].N[(v, a)]]
    lmass = {i: [Fr(x) for x in crs[i].M] for i in range(nreg)}
    lifted = Marked(card=lcard, factors=lfactors, owner=lowner, marks=lmarks,
                    mass=lmass, orig_card=dict(marked.orig_card),
                    level=marked.level + 1,
                    certificate={"t_level": str(t_level), "R_level": str(R_level),
                                 "deletion_radius": str(del_total),
                                 "regions": [tuple(r) for r in regions],
                                 "cells": ncell})
    lifted.check_identity()
    return Scale(regions=[tuple(r) for r in regions], rds=rds, coarse=crs,
                 deletions=dels, projected=projected, t_level=Fr(t_level),
                 deletion_radius_total=del_total, R_level=R_level,
                 lifted=lifted, input_card=dict(marked.card))


def contract_exact(marked: Marked, deadline=None, budget=None, order=None):
    """Exact sparse contraction of a Marked model's law (mass factors times
    its factors): returns (Z, {current var: [count per state]}, jt)."""
    from mdi import sparse_jt as SJ
    tabs = []
    touched = {v for f in marked.factors for v in f.scope}
    for v in marked.free():
        row = marked.mass[v]
        ent = {(c,): Fr(x) for c, x in enumerate(row) if x != 0}
        if any(x != 1 for x in row) or v not in touched:
            tabs.append(SJ.Table((v,), ent))
    for f in marked.factors:
        if FX.is_view(f):
            tabs.append(SJ.lazy_from_factor(f))
        else:
            tabs.append(SJ.table_from_factor(f, deadline=deadline))
    charge = None
    if budget is not None:
        budget.charge("local_mass_entries", 1, "marked exact contraction")
        charge = lambda n: budget.charge("local_mass_entries", n,
                                         "marked exact contraction")
    Z, counts, jt = SJ.all_marginals(tabs, marked.card, deadline=deadline,
                                     order=order, charge=charge,
                                     only=set(marked.owner.values()))
    return Z, counts, jt


def propose_regions(marked: Marked, cap_assign=None):
    """Partition proposals over the CURRENT variables, via the same bounded
    growth rules regions.propose_partitions applies to an input model."""
    view = marked.restricted_view(with_mass=False)
    return R.propose_partitions(view.free, view.card, view.factors,
                                cap_assign=cap_assign)

