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
    cap = cap_assignments or (K.CAPS["region_tuple_assignments"] * 64)
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
    model, and require the published intervals to contain the result."""
    region_of = {}
    for i, reg in enumerate(regions):
        for v in reg:
            region_of[v] = i
    rho_cap = K.region_distortion_budget(t_level, len(regions))
    problems = []
    rebuilt = []
    for i, reg in enumerate(regions):
        cr, probs = recheck_region(reg, restricted, restricted.card, queries,
                                   rho_cap, region_of, coarse[i],
                                   deadline=deadline)
        rebuilt.append(cr)
        for p in probs:
            problems.append("region %d: %s" % (i, p))
    if problems:
        return False, problems, None
    Rlevel = R.level_distortion(rebuilt)
    if not K.certify_R_against_t(Rlevel, t_level):
        return False, ["R_level %s is not certified at t=%s" % (Rlevel, t_level)], None
    Z, counts = independent_contract(restricted, regions, rebuilt, rds, queries,
                                     deadline=deadline)
    fails = []
    for v in sorted(queries):
        rows = published.get(v)
        if rows is None:
            fails.append("variable %d has no published row" % v)
            continue
        for s in range(len(rows)):
            q = counts.get((v, s), Fr(0)) / Z
            lo, hi = Fr(rows[s][0]), Fr(rows[s][1])
            plo = max(Fr(0), lo - t_level)
            phi = min(Fr(1), hi + t_level)
            if not (plo <= q <= phi):
                fails.append("variable %d state %d: independent %s outside "
                             "published [%s, %s] widened by t" % (v, s, q, lo, hi))
            if hi - lo > Fr(eps):
                fails.append("variable %d state %d: published width exceeds eps"
                             % (v, s))
    return (not fails), fails, {"Z": Z, "R_level": Rlevel,
                                "regions_rebuilt": len(rebuilt),
                                "cell_assignments": None}
