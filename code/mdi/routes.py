"""Route programs: BUILD them during discovery, EXECUTE them from the record.

The executor side consumes only (original restricted model, requested
variables, the parsed program). It rebuilds every lifted model from the
persisted witness -- cells, member weights, masses, markers -- and the
collective residual from the persisted mode record, then contracts with the
producer's sparse engine along the persisted elimination order. Discovery's
live objects are not an input to execution.
"""
from __future__ import annotations
import sys
sys.set_int_max_str_digits(0)
from fractions import Fraction as Fr
from mdi import (model as M, config as K, regions as R, marked as MK,
                 program as PG, collective_route as CR, collective_jt as CJ,
                 sparse_jt as SJ, arith as A, budget as B, factors as FX)


class RouteError(Exception):
    pass


# ------------------------------------------------------------- building

def build_scales(marked0: MK.Marked, first_regions, levels, deadline=None,
                 budget=None, second_regions=None):
    """Apply `levels` (1 or 2) regional scales. The regional allowance is split
    equally across the levels BEFORE construction (§8); each level's deletion
    allowance is split equally across its regions inside `coarsen`."""
    t = K.level_radius(levels)
    del_level = K.RADII["state_deletion_total"] / levels
    scales = []
    cur = marked0
    regions = first_regions
    for lvl in range(levels):
        if lvl == 1:
            if second_regions is None:
                props = [p for p in MK.propose_regions(cur)
                         if p["mode"] != "singleton"
                         and len(p["regions"]) < len(cur.card)]
                if not props:
                    raise R.Declined("no grouping of the level-1 cells reduces "
                                     "the variable count; a second scale is "
                                     "not available")
                regions = props[0]["regions"]
            else:
                regions = second_regions
        sc = MK.coarsen(cur, [tuple(x) for x in regions], t, del_level,
                        deadline=deadline, budget=budget)
        scales.append(sc)
        cur = sc.lifted
    return scales, cur


def research_executed(scales, coll) -> dict:
    """What the program ACTUALLY transforms (§15): a nontrivial cell merge, a
    certified deletion, or a collective computation."""
    merged = sum(1 for sc in scales for cr, rd in zip(sc.coarse, sc.rds)
                 if len(cr.cells) < len(rd.A))
    deleted = sum(len(d.deleted) for sc in scales for d in sc.deletions if d)
    return {"cells_merged_regions": merged, "deleted_states": deleted,
            "collective": coll["evaluator"] if coll else None,
            "qualifies": bool(merged or deleted or coll)}


def identity_program(order, precision, emin, emax, queries, checker_precision):
    """The persisted program of the IDENTITY route: the validated generic
    schedule, its arithmetic settings and its checker's strategy."""
    return {"kind": "identity", "scales": [], "collective": None,
            "order": [int(x) for x in order], "precision": int(precision),
            "queries": sorted(int(v) for v in queries),
            "research": {"cells_merged_regions": 0, "deleted_states": 0,
                         "collective": None, "qualifies": False},
            "arithmetic": {"emin": int(emin), "emax": int(emax), "mode": "P"},
            "checker": {"strategy": "min_fill_interval",
                        "precision": int(checker_precision)}}


def program_for(kind, scales, coll, order, precision, queries, extra=None):
    """The persisted program block of a plan record."""
    prog = {"kind": kind,
            "scales": [PG.scale_to_jsonable(sc) for sc in scales],
            "collective": None, "order": [int(x) for x in order],
            "precision": int(precision), "queries": sorted(int(v) for v in queries),
            "research": research_executed(scales, coll),
            "arithmetic": {"emin": None, "emax": None, "mode": "E"},
            "checker": {"strategy": "dense_min_fill",
                        "precision": int(precision) + 16}}
    if coll is not None:
        prog["collective"] = {
            "evaluator": coll["evaluator"],
            "candidate": PG.cand_to_jsonable(coll["candidate"]),
            "Q": coll["Q"], "delta": (None if coll.get("delta") is None
                                      else str(Fr(coll["delta"]))),
            "deltas": (None if not coll.get("deltas") else [str(Fr(x)) for x in coll["deltas"]]),
            "lattices": (None if not coll.get("lattices") else [
                {"T": str(Fr(l["T"])), "h": str(Fr(l["h"])), "nodes": int(l["nodes"]),
                 "total_bound": str(Fr(l["total_bound"]))} for l in coll["lattices"]]),
            "fit_tv": str(Fr(coll["fit_tv"])),
            "rounding_tv": str(Fr(coll["rounding_tv"])),
            "quadrature_tv": str(Fr(coll["quadrature_tv"])),
            "precision": int(coll["precision"]), "round_bits": int(coll["round_bits"]),
            "kept_factors": [int(x) for x in coll["kept_factors"]],
            "dropped_pairs": [[int(a), int(b)] for a, b in coll["dropped_pairs"]],
            "drop_budget": str(Fr(coll["drop_budget"]))}
    if extra:
        prog["research"].update(extra)
    return prog


def allocations_for(scales, coll) -> dict:
    """Every radius the program charges, by name (exact rationals)."""
    out = {}
    for k, sc in enumerate(scales):
        out["regional_level%d" % (k + 1)] = Fr(sc.t_level)
        out["deletion_level%d" % (k + 1)] = Fr(sc.deletion_radius_total)
    if coll is not None:
        out["collective_fit"] = Fr(coll["fit_tv"])
        out["collective_rounding"] = Fr(coll["rounding_tv"])
        out["gaussian_quadrature"] = Fr(coll["quadrature_tv"])
    return out


def total_radius(allocations) -> Fr:
    return sum((Fr(v) for v in allocations.values()), Fr(0))


# ------------------------------------------------------------- executing

def lift_from_record(marked: MK.Marked, sc, deadline=None, budget=None):
    """Rebuild the lifted Marked model of one PERSISTED scale on top of
    `marked` (its input model). Uses the record's cells, masses and markers
    and the input model's crossing factors evaluated at the representatives.
    Nothing is recomputed from the raw law here: this is the producer
    executing its own record."""
    regs = sc["regions"]
    region_of = {}
    for i, rg in enumerate(regs):
        for v in rg["region"]:
            if v in region_of:
                raise RouteError("regions overlap on variable %d" % v)
            region_of[v] = i
    if set(region_of) != set(marked.card):
        raise RouteError("the persisted regions do not cover the model")
    ncell = [len(rg["cells"]) for rg in regs]
    if ncell != list(sc["lifted_card"]):
        raise RouteError("the persisted lifted cardinalities disagree with the "
                         "cell lists")
    # masses and markers straight from the witness
    lmass = {}
    lmarks = {}
    lowner = {}
    for i, rg in enumerate(regs):
        lmass[i] = [c["M"] for c in rg["cells"]]
        if budget is not None:
            budget.charge("local_mass_entries", max(1, len(rg["cells"])),
                          "lifted cell masses")
    for v in marked.queries():
        i = region_of[marked.owner[v]]
        lowner[v] = i
        for a in range(marked.orig_card[v]):
            col = []
            for c in regs[i]["cells"]:
                col.append(c["N"].get((v, a), Fr(0)))
            lmarks[(v, a)] = col
    # crossing factors as COMPACT views: the record's representatives select
    # offsets into the ORIGINAL tables; maps compose across scales
    reps = {i: [tuple(c["rep"]) for c in regs[i]["cells"]] for i in range(len(regs))}
    bpos = {i: {v: k for k, v in enumerate(regs[i]["boundary"])} for i in range(len(regs))}
    lfactors = []
    for f in marked.factors:
        rs = sorted({region_of[v] for v in f.scope})
        if len(rs) <= 1:
            continue
        try:
            lfactors.append(FX.as_view(f).compose(region_of, reps, bpos, ncell))
        except FX.ViewError as e:
            raise RouteError(str(e))
        if budget is not None:
            budget.charge("local_mass_entries", lfactors[-1].map_entries(),
                          "lifted offset maps")
    lifted = MK.Marked(card={i: ncell[i] for i in range(len(regs))},
                       factors=lfactors, owner=lowner, marks=lmarks, mass=lmass,
                       orig_card=dict(marked.orig_card), level=marked.level + 1,
                       certificate={"t_level": str(sc["t_level"]),
                                    "R_level": str(sc["R_level"]),
                                    "deletion_radius": str(sc["deletion_radius_total"])})
    lifted.check_identity()
    return lifted


def scale_view_from_record(marked, sc):
    """A Scale-like view of a PERSISTED scale sufficient for pricing: regions,
    RegionData shells (support and marker keys from the witness), coarse
    shells (cells, M, N) and the lifted model's compact crossings."""
    regs = [tuple(rg["region"]) for rg in sc["regions"]]
    rds, crs, dels = [], [], []
    for rg in sc["regions"]:
        A = {}
        marks = {}
        for c in rg["cells"]:
            for mb, al in c["members"]:
                A[tuple(mb)] = Fr(1)
            for k in c["N"]:
                marks.setdefault(k, {})
        for b in rg["deleted"]:
            A[tuple(b)] = Fr(1)
        rset = set(rg["region"])
        internal = [fi for fi, f in enumerate(marked.factors) if set(f.scope) <= rset]
        crossing = [fi for fi, f in enumerate(marked.factors)
                    if (set(f.scope) & rset) and not (set(f.scope) <= rset)]
        rds.append(R.RegionData(vars=tuple(rg["region"]), boundary=tuple(rg["boundary"]),
                                internal_factors=internal, crossing_factors=crossing,
                                A=A, marks=marks))
        cells = [R.Cell(rep=tuple(c["rep"]), members=[(tuple(mb), Fr(al)) for mb, al in c["members"]])
                 for c in rg["cells"]]
        N = {}
        for c in rg["cells"]:
            for k in c["N"]:
                N.setdefault(k, [])
        for c in rg["cells"]:
            for k in N:
                N[k].append(Fr(c["N"].get(k, Fr(0))))
        crs.append(R.CoarseRegion(region=tuple(rg["region"]), boundary=tuple(rg["boundary"]),
                                  cells=cells, M=[Fr(c["M"]) for c in rg["cells"]], N=N,
                                  cell_of={}, rho_region=Fr(rg["rho_region"]),
                                  comparisons=0, declines={},
                                  aggregation=[dict(e) for e in (rg.get("aggregation") or [])]))
        dels.append(None if not rg["deleted"] else
                    R.DeletionRecord(region=tuple(rg["region"]),
                                     deleted=[tuple(b) for b in rg["deleted"]],
                                     U=Fr(0), L=Fr(1), prob_bound=Fr(rg["deletion_bound"]),
                                     radius_charged=Fr(rg["deletion_bound"]),
                                     retained_states=len(rg["cells"]),
                                     positive_denominator=True))
    lifted = lift_from_record(marked, sc)
    return MK.Scale(regions=regs, rds=rds, coarse=crs, deletions=dels,
                    projected=list(lifted.factors), t_level=Fr(sc["t_level"]),
                    deletion_radius_total=Fr(sc["deletion_radius_total"]),
                    R_level=Fr(sc["R_level"]), lifted=lifted,
                    input_card=dict(marked.card))


def sharp_rows(counts, orig_card, queries):
    """P(x_i = a) from count enclosures by the sharp marker ratio with the
    producer's OWN complement sums: X = count(a), C = sum of the other states'
    counts, P in [X_l/(X_l + C_u), X_u/(X_u + C_l)]."""
    rows = {}
    for v in sorted(queries):
        xs = [(Fr(counts[v][a][0]), Fr(counts[v][a][1])) for a in range(orig_card[v])]
        tl = sum(x[0] for x in xs)
        th = sum(x[1] for x in xs)
        if th <= 0:
            raise RouteError("variable %d has no positive total count" % v)
        rr = []
        for a, (xl, xu) in enumerate(xs):
            cl, cu = tl - xl, th - xu
            dl, du = xl + cu, xu + cl
            lo = xl / dl if dl > 0 else Fr(0)
            hi = xu / du if du > 0 else Fr(1)
            rr.append((max(Fr(0), lo), min(Fr(1), hi)))
        rows[v] = rr
    return rows


def execute(prog, r, queries, deadline=None, budget=None, engine="sparse",
            num_eps=None, progress=None):
    """Run a PARSED program on the restricted model. Returns
    (rows {orig var: [(lo, hi)] of exact enclosures of the REPRESENTED law's
    marginals}, meta). The caller widens by the recorded allocations."""
    marked = MK.Marked.from_restricted(r, set(queries))
    for sc in prog["scales"]:
        marked = lift_from_record(marked, sc, deadline=deadline, budget=budget)
    meta = {"levels": len(prog["scales"]),
            "final_vars": len(marked.card),
            "final_cards": [marked.card[v] for v in marked.free()]}
    order = prog["order"] or None
    if order is not None and sorted(order) != marked.free():
        raise RouteError("the persisted elimination order does not name the "
                         "final model's variables")
    if prog["collective"] is None:
        Z, counts, jt = MK.contract_exact(marked, deadline=deadline,
                                          budget=budget, order=order)
        rows = MK.read_original(marked, Z, counts)
        meta.update({"evaluator": "exact", "ops": jt.ops,
                     "peak_live_entries": jt.peak_live_entries,
                     "order": list(jt.order), "largest_bag": jt.largest_bag})
        return rows, meta
    coll = prog["collective"]
    ctx = A.Ctx(coll["precision"])
    rmk, res, can = CR.rebuild_residual(marked, coll, ctx)
    charge = None
    if budget is not None:
        charge = lambda n: budget.charge("local_mass_entries", n,
                                         "collective evaluation")
    (Zlo, Zhi), counts, cmeta = CJ.evaluate(rmk, coll, ctx, engine=engine,
                                            deadline=deadline, order=order,
                                            charge=charge, num_eps=num_eps)
    if progress is not None:
        progress("collective", "%s evaluated" % coll["evaluator"])
    if Zhi <= 0:
        raise RouteError("the collective evaluation has no positive total")
    # the SHARP marker ratio from the counts (event against its own complement)
    rows = sharp_rows(counts, rmk.orig_card, rmk.queries())
    meta.update(cmeta)
    meta["residual_factors"] = len(rmk.factors)
    return rows, meta
