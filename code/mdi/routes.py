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
                 sparse_jt as SJ, arith as A, budget as B)


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


def program_for(kind, scales, coll, order, precision, queries, extra=None):
    """The persisted program block of a plan record."""
    prog = {"kind": kind,
            "scales": [PG.scale_to_jsonable(sc) for sc in scales],
            "collective": None, "order": [int(x) for x in order],
            "precision": int(precision), "queries": sorted(int(v) for v in queries),
            "research": research_executed(scales, coll)}
    if coll is not None:
        prog["collective"] = {
            "evaluator": coll["evaluator"],
            "candidate": PG.cand_to_jsonable(coll["candidate"]),
            "Q": coll["Q"], "delta": (None if coll["delta"] is None
                                      else str(Fr(coll["delta"]))),
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
    # crossing factors at the representatives
    lfactors = []
    cap = K.CAPS["aggregated_kernel_entries"]
    for f in marked.factors:
        rs = sorted({region_of[v] for v in f.scope})
        if len(rs) <= 1:
            continue
        n = 1
        for i in rs:
            n *= ncell[i]
        if n > cap:
            raise RouteError("a lifted crossing over regions %s needs %d "
                             "entries, above the %d cap" % (rs, n, cap))
        st = f.strides()
        bpos = {i: {v: k for k, v in enumerate(regs[i]["boundary"])} for i in rs}
        for k, v in enumerate(f.scope):
            if v not in bpos[region_of[v]]:
                raise RouteError("variable %d of crossing factor %d is not on "
                                 "the boundary of its region" % (v, f.origin))
        lst = [1] * len(rs)
        acc = 1
        for k in range(len(rs) - 1, -1, -1):
            lst[k] = acc
            acc *= ncell[rs[k]]
        tab = []
        for flat in range(n):
            if deadline is not None and (flat & 0xFF) == 0:
                deadline()
            rem, dig = flat, []
            for k in range(len(rs)):
                dig.append(rem // lst[k])
                rem %= lst[k]
            off = 0
            for k, v in enumerate(f.scope):
                i = region_of[v]
                rep = regs[i]["cells"][dig[rs.index(i)]]["rep"]
                off += rep[bpos[i][v]] * st[k]
            tab.append(Fr(f.table[off]))
        if budget is not None:
            budget.charge("local_mass_entries", n, "lifted crossing table")
        lfactors.append(M.Factor(scope=tuple(rs), card=tuple(ncell[i] for i in rs),
                                 table=tab, origin=f.origin))
    lifted = MK.Marked(card={i: ncell[i] for i in range(len(regs))},
                       factors=lfactors, owner=lowner, marks=lmarks, mass=lmass,
                       orig_card=dict(marked.orig_card), level=marked.level + 1,
                       certificate={"t_level": str(sc["t_level"]),
                                    "R_level": str(sc["R_level"]),
                                    "deletion_radius": str(sc["deletion_radius_total"])})
    lifted.check_identity()
    return lifted


def execute(prog, r, queries, deadline=None, budget=None, engine="sparse"):
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
                                            charge=charge)
    if Zlo <= 0:
        raise RouteError("the collective evaluation has no positive total")
    rows = {}
    for v in rmk.queries():
        rr = []
        for a in range(rmk.orig_card[v]):
            lo, hi = counts[v][a]
            rr.append((max(Fr(0), lo / Zhi), min(Fr(1), hi / Zlo)))
        rows[v] = rr
    meta.update(cmeta)
    meta["residual_factors"] = len(rmk.factors)
    return rows, meta
