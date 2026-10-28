"""Independent regional checker (contract §D.7).

Rebuilds masses, marks, aggregation, extrema, alpha/rho, support and ownership
from the ORIGINAL local factors, then independently contracts the REDUCED model.

It must NOT globally solve the uncoarsened original model as hidden checking
work, and it must not call the producer's aggregation or readout. It therefore
has its own contraction over cell assignments, deliberately simple, with its
cost charged to the plan.
"""
from __future__ import annotations
import sys
sys.set_int_max_str_digits(0)
from fractions import Fraction as Fr
import itertools
from mdi import regions as R, config as K, compact as CP


class RegionalCheckError(ValueError):
    pass


def recheck_region(region, restricted, card, queries, rho_cap, region_of,
                   producer_coarse, deadline=None):
    """Independently rebuild one region's cells and compare STRUCTURE only.

    The producer's numbers are never consumed: masses and marks are recomputed
    from the original factors, and only the resulting membership and mass values
    are compared.
    """
    rd = R.region_data(region, card, restricted.factors, queries,
                       deadline=deadline)
    cr = R.merge_region(rd, restricted.factors, card, rho_cap, queries,
                        deadline=deadline, region_of=region_of, aggregate=True)
    pc = producer_coarse
    problems = []
    if len(cr.cells) != len(pc.cells):
        problems.append("cell count %d != producer %d" % (len(cr.cells),
                                                          len(pc.cells)))
        return cr, problems
    for ci, (a, b) in enumerate(zip(cr.cells, pc.cells)):
        if a.rep != b.rep:
            problems.append("cell %d representative %s != %s" % (ci, a.rep, b.rep))
        if sorted(x for x, _ in a.members) != sorted(x for x, _ in b.members):
            problems.append("cell %d membership differs" % ci)
        for (mb, al_a), (mb2, al_b) in zip(sorted(a.members), sorted(b.members)):
            if al_a != al_b:
                problems.append("cell %d alpha for %s: %s != %s"
                                % (ci, mb, al_a, al_b))
    for ci in range(len(cr.cells)):
        if Fr(cr.M[ci]) != Fr(pc.M[ci]):
            problems.append("cell %d mass %s != %s" % (ci, cr.M[ci], pc.M[ci]))
    if set(cr.N) != set(pc.N):
        problems.append("marker key sets differ")
    else:
        for key in cr.N:
            for ci in range(len(cr.cells)):
                if Fr(cr.N[key][ci]) != Fr(pc.N[key][ci]):
                    problems.append("marker %s cell %d: %s != %s"
                                    % (key, ci, cr.N[key][ci], pc.N[key][ci]))
    if Fr(cr.rho_region) != Fr(pc.rho_region):
        problems.append("rho %s != %s" % (cr.rho_region, pc.rho_region))
    # the mark/mass identity, independently
    for v in region:
        keys = [k for k in cr.N if k[0] == v]
        if not keys:
            continue
        for ci in range(len(cr.cells)):
            tot = sum(Fr(cr.N[k][ci]) for k in keys)
            if tot != Fr(cr.M[ci]):
                problems.append("mark/mass identity fails at %d cell %d" % (v, ci))
    return cr, problems


def independent_contract(restricted, regions, coarse, rds, queries,
                         deadline=None, cap_assignments=None):
    """Contract the REDUCED model with the checker's own code.

    Enumerates cell assignments and evaluates the compact projected crossings
    directly. This is deliberately a different implementation from the
    producer's message passing, and it never touches the original uncoarsened
    model's elimination.
    """
    cap = cap_assignments or K.CAPS["checker_contraction_space"]
    projected, _ = CP.project_crossings(restricted, regions, coarse, rds)
    ncell = [len(c.cells) for c in coarse]
    total = 1
    for k in ncell:
        total *= k
    if total > cap:
        raise RegionalCheckError(
            "independent contraction needs %d cell assignments, above the %d "
            "cap; this is a RESOURCE refusal, not a verification" % (total, cap))
    Z = Fr(0)
    counts = {}
    for tup in itertools.product(*[range(k) for k in ncell]):
        if deadline is not None:
            deadline()
        cell_of = {i: tup[i] for i in range(len(regions))}
        w = Fr(1)
        for i, ci in enumerate(tup):
            w *= Fr(coarse[i].M[ci])
        if w == 0:
            continue
        for pc in projected:
            w *= pc.value(cell_of)
            if w == 0:
                break
        if w == 0:
            continue
        Z += w
        for i, ci in enumerate(tup):
            Mc = Fr(coarse[i].M[ci])
            if Mc <= 0:
                continue
            for key, col in coarse[i].N.items():
                if key[0] not in queries:
                    continue
                Nc = Fr(col[ci])
                if Nc == 0:
                    continue
                counts[key] = counts.get(key, Fr(0)) + w / Mc * Nc
    if Z <= 0:
        raise RegionalCheckError("reduced model has nonpositive total weight")
    return Z, counts


def verify_regional_publication(restricted, regions, coarse, rds, queries,
                                published, t_level, eps, deadline=None):
    """Full §D.7 check: rebuild every region, independently contract the reduced
    model, and require the publication to CONTAIN the checker's enclosure."""
    # original model and evidence validation BEFORE any numerical work
    if restricted.impossible_factor is not None:
        return False, ["a restricted factor is identically zero: the "
                       "conditioning event has probability zero, so no "
                       "conditional distribution exists"], None
    if restricted.constant == 0:
        return False, ["a fully pinned factor is exactly zero: zero evidence "
                       "weight"], None
    if not queries:
        return False, ["no queries requested"], None
    missing = [v for v in sorted(queries) if v not in published]
    if missing:
        return False, ["variables %s have no published row" % missing[:8]], None
    region_of = {}
    for i, reg in enumerate(regions):
        for v in reg:
            region_of[v] = i
    rho_cap = K.region_distortion_budget(t_level, len(regions))
    problems = []
    rebuilt = []
    own_rds = []
    for i, reg in enumerate(regions):
        # Rebuild the region's own RegionData, including its BOUNDARY ORDER, and
        # use that rather than the producer's rds. Trusting producer boundary
        # metadata after discarding our own let a corrupted boundary ordering
        # pass an exact-coarsening example with error about 0.131.
        rd_own = R.region_data(reg, restricted.card, restricted.factors,
                               queries, deadline=deadline)
        own_rds.append(rd_own)
        if tuple(rd_own.boundary) != tuple(rds[i].boundary):
            problems.append("region %d: producer boundary order %s differs from "
                            "the independently rebuilt %s"
                            % (i, rds[i].boundary, rd_own.boundary))
        cr, probs = recheck_region(reg, restricted, restricted.card, queries,
                                   rho_cap, region_of, coarse[i],
                                   deadline=deadline)
        rebuilt.append(cr)
        for p in probs:
            problems.append("region %d: %s" % (i, p))
    if problems:
        return False, problems, None
    rds = own_rds
    Rlevel = R.level_distortion(rebuilt)
    if not K.certify_R_against_t(Rlevel, t_level):
        return False, ["R_level %s is not certified at t=%s" % (Rlevel, t_level)], None
    Z, counts = independent_contract(restricted, regions, rebuilt, rds, queries,
                                     deadline=deadline)
    fails = []
    # Build the checker's OWN original-model enclosure, then require the
    # publication to CONTAIN it.
    #
    # The previous direction was backwards: it widened the SUBMITTED interval by
    # t_level and asked whether the coarse point fitted inside. That accepts any
    # publication within t of the coarse answer, including one that is wrong
    # about the original model, and it lets a corrupted producer pass by
    # submitting its own (wrong) number.
    for v in sorted(queries):
        rows = published.get(v)
        if rows is None:
            fails.append("variable %d has no published row" % v)
            continue
        if not rows:
            fails.append("variable %d has an EMPTY state row" % v)
            continue
        nst = None
        for i, reg in enumerate(regions):
            if v in reg:
                nst = len({k[1] for k in coarse[i].N if k[0] == v})
                break
        if nst and len(rows) != nst:
            fails.append("variable %d publishes %d states, the region holds %d"
                         % (v, len(rows), nst))
            continue
        for s in range(len(rows)):
            try:
                lo, hi = Fr(rows[s][0]), Fr(rows[s][1])
            except (TypeError, ValueError, IndexError):
                fails.append("variable %d state %d: endpoints are not exact "
                             "rationals" % (v, s))
                continue
            if lo > hi:
                fails.append("variable %d state %d: INVERTED endpoints "
                             "[%s, %s]" % (v, s, lo, hi))
                continue
            if lo < 0 or hi > 1:
                fails.append("variable %d state %d: endpoints outside [0,1]"
                             % (v, s))
                continue
            # the checker's independent coarse answer, widened OUTWARD by every
            # charged error, is a rigorous enclosure of the ORIGINAL probability
            q = counts.get((v, s), Fr(0)) / Z
            clo = max(Fr(0), q - t_level)
            chi = min(Fr(1), q + t_level)
            # the publication must CONTAIN that enclosure
            if not (lo <= clo and chi <= hi):
                fails.append(
                    "variable %d state %d: publication [%s, %s] does NOT "
                    "contain the independent enclosure [%s, %s]"
                    % (v, s, lo, hi, clo, chi))
            if hi - lo > Fr(eps):
                fails.append("variable %d state %d: published width exceeds eps"
                             % (v, s))
    return (not fails), fails, {"Z": Z, "R_level": Rlevel,
                                "regions_rebuilt": len(rebuilt),
                                "independent_enclosure": True,
                                "direction": "publication must CONTAIN the "
                                             "checker's enclosure, not the "
                                             "reverse"}
