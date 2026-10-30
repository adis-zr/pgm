"""The persisted PROGRAM a plan record carries (spec §8, §9, §11 binding).

Everything the executor needs is here, as exact strings: the coarsening
witness of every scale (regions, cells with their member weights, masses,
markers, deletions), the collective record (mode, Q, delta, declared radii),
the elimination order of the final contraction and its precision. The
executor consumes THIS -- not discovery's live objects -- and the checker
verifies THIS against the original model.

`to_jsonable` / `from_jsonable` are strict: unknown keys, floats, or a
malformed exact string are refused, because a record that cannot be parsed
exactly does not describe a program.
"""
from __future__ import annotations
import sys
sys.set_int_max_str_digits(0)
from fractions import Fraction as Fr
from mdi import regions as R, marked as MK, modes as MD


class ProgramError(ValueError):
    pass


def _q(x):
    """Exact rational -> string."""
    return str(Fr(x))


def _fr(x, what="value"):
    if isinstance(x, float):
        raise ProgramError("%s is a float; the program must be exact" % what)
    try:
        return Fr(x)
    except (TypeError, ValueError, ZeroDivisionError) as e:
        raise ProgramError("%s %r is not an exact rational (%s)" % (what, x, e))


def _need(d, keys, where):
    miss = [k for k in keys if k not in d]
    if miss:
        raise ProgramError("%s is missing %s" % (where, miss))
    extra = sorted(set(d) - set(keys))
    if extra:
        raise ProgramError("%s carries unknown fields %s" % (where, extra))


# ---------------------------------------------------------------- scales

def scale_to_jsonable(sc: MK.Scale) -> dict:
    cells = []
    for i, cr in enumerate(sc.coarse):
        rows = []
        for ci, cell in enumerate(cr.cells):
            rows.append({"rep": list(cell.rep),
                         "members": [[list(mb), _q(al)] for mb, al in cell.members],
                         "M": _q(cr.M[ci]),
                         "N": {"%d,%d" % k: _q(col[ci]) for k, col in cr.N.items()}})
        drec = sc.deletions[i]
        cells.append({"region": list(sc.regions[i]),
                      "boundary": list(sc.rds[i].boundary),
                      "cells": rows,
                      "rho_region": _q(cr.rho_region),
                      "deleted": [list(b) for b in drec.deleted] if drec else [],
                      "deletion_bound": _q(drec.prob_bound) if drec else "0",
                      "aggregation": [
                          {"factors": [int(x) for x in e["factors"]],
                           "aggregated": bool(e.get("aggregated"))}
                          for e in (cr.aggregation or [])]})
    return {"t_level": _q(sc.t_level), "R_level": _q(sc.R_level),
            "deletion_radius_total": _q(sc.deletion_radius_total),
            "regions": cells,
            "lifted_card": [int(len(c.cells)) for c in sc.coarse]}


def scale_from_jsonable(d: dict) -> dict:
    """Parsed scale witness with exact rationals (not rebuilt objects: the
    executor and checker each build what they need from this)."""
    _need(d, ("t_level", "R_level", "deletion_radius_total", "regions",
              "lifted_card"), "scale")
    regs = []
    for i, rg in enumerate(d["regions"]):
        _need(rg, ("region", "boundary", "cells", "rho_region", "deleted",
                   "deletion_bound", "aggregation"), "scale region %d" % i)
        cells = []
        for ci, c in enumerate(rg["cells"]):
            _need(c, ("rep", "members", "M", "N"), "cell %d/%d" % (i, ci))
            N = {}
            for k, v in c["N"].items():
                a, b = k.split(",")
                N[(int(a), int(b))] = _fr(v, "marker")
            cells.append({"rep": tuple(int(x) for x in c["rep"]),
                          "members": [(tuple(int(x) for x in mb), _fr(al, "alpha"))
                                      for mb, al in c["members"]],
                          "M": _fr(c["M"], "mass"), "N": N})
        regs.append({"region": tuple(int(x) for x in rg["region"]),
                     "boundary": tuple(int(x) for x in rg["boundary"]),
                     "cells": cells, "rho_region": _fr(rg["rho_region"], "rho"),
                     "deleted": [tuple(int(x) for x in b) for b in rg["deleted"]],
                     "deletion_bound": _fr(rg["deletion_bound"], "deletion bound"),
                     "aggregation": [{"factors": [int(x) for x in e["factors"]],
                                      "aggregated": bool(e["aggregated"])}
                                     for e in rg["aggregation"]]})
    return {"t_level": _fr(d["t_level"], "t_level"),
            "R_level": _fr(d["R_level"], "R_level"),
            "deletion_radius_total": _fr(d["deletion_radius_total"],
                                         "deletion radius"),
            "regions": regs, "lifted_card": [int(x) for x in d["lifted_card"]]}


# ------------------------------------------------------------- collective

def cand_to_jsonable(cand) -> dict:
    return {"signs": [int(s) for s in cand.signs],
            "gammas": [_q(g) for g in cand.gammas],
            "features": [{str(v): [_q(x) for x in f] for v, f in fk.items()}
                         for fk in cand.features],
            "kind": str(cand.kind)}


def cand_from_jsonable(d: dict):
    _need(d, ("signs", "gammas", "features", "kind"), "mode candidate")
    signs = [int(s) for s in d["signs"]]
    if any(s not in (1, -1) for s in signs):
        raise ProgramError("mode signs must be +1 or -1")
    gammas = [_fr(g, "gamma") for g in d["gammas"]]
    if any(g <= 0 for g in gammas):
        raise ProgramError("mode gammas must be positive")
    feats = [{int(v): [_fr(x, "feature") for x in f] for v, f in fk.items()}
             for fk in d["features"]]
    if not (len(signs) == len(gammas) == len(feats)) or not signs:
        raise ProgramError("mode record has inconsistent rank")
    return MD.ModeCandidate(signs=signs, gammas=gammas, features=feats,
                            kind=str(d["kind"]))


COLLECTIVE_KEYS = ("evaluator", "candidate", "Q", "delta", "deltas", "lattices",
                   "fit_tv", "rounding_tv", "quadrature_tv", "precision", "round_bits",
                   "kept_factors", "dropped_pairs", "drop_budget")


def collective_from_jsonable(d: dict) -> dict:
    _need(d, COLLECTIVE_KEYS, "collective record")
    if d["evaluator"] not in ("statistic", "gaussian", "fourier", "mixed"):
        raise ProgramError("unknown collective evaluator %r" % d["evaluator"])
    out = {"evaluator": d["evaluator"],
           "candidate": cand_from_jsonable(d["candidate"]),
           "Q": (None if d["Q"] is None else int(d["Q"])),
           "delta": (None if d["delta"] is None else _fr(d["delta"], "delta")),
           "deltas": (None if d["deltas"] is None
                      else [_fr(x, "delta") for x in d["deltas"]]),
           "lattices": (None if d["lattices"] is None else [
               {"T": _fr(l["T"], "lattice T"), "h": _fr(l["h"], "lattice h"),
                "nodes": int(l["nodes"]), "total_bound": _fr(l["total_bound"], "lattice bound")}
               for l in d["lattices"]]),
           "fit_tv": _fr(d["fit_tv"], "fit_tv"),
           "rounding_tv": _fr(d["rounding_tv"], "rounding_tv"),
           "quadrature_tv": _fr(d["quadrature_tv"], "quadrature_tv"),
           "precision": int(d["precision"]), "round_bits": int(d["round_bits"]),
           "kept_factors": [int(x) for x in d["kept_factors"]],
           "dropped_pairs": [[int(a), int(b)] for a, b in d["dropped_pairs"]],
           "drop_budget": _fr(d["drop_budget"], "drop_budget")}
    if out["Q"] is not None and out["Q"] < 1:
        raise ProgramError("Q must be a positive integer")
    if out["evaluator"] == "statistic":
        if out["Q"] is None or out["deltas"] is not None:
            raise ProgramError("a statistic record needs Q and no lattice deltas")
    else:
        if out["deltas"] is None or len(out["deltas"]) != out["candidate"].rank:
            raise ProgramError("a quadrature record needs one lattice delta per mode")
        if out["lattices"] is None or len(out["lattices"]) != out["candidate"].rank:
            raise ProgramError("a quadrature record needs one validated lattice per mode")
        for l in out["lattices"]:
            if l["nodes"] < 1 or l["T"] <= 0 or l["h"] <= 0:
                raise ProgramError("a recorded lattice has non-positive parameters")
        if any(x <= 0 for x in out["deltas"]):
            raise ProgramError("lattice deltas must be positive")
        pos = [k for k in range(out["candidate"].rank) if out["candidate"].signs[k] > 0]
        neg = [k for k in range(out["candidate"].rank) if out["candidate"].signs[k] < 0]
        want = {"gaussian": (True, False), "fourier": (False, True), "mixed": (True, True)}[out["evaluator"]]
        if (bool(pos), bool(neg)) != want:
            raise ProgramError("evaluator %s does not match the mode signs %s"
                               % (out["evaluator"], out["candidate"].signs))
    return out


PROGRAM_KEYS = ("kind", "scales", "collective", "order", "precision",
                "queries", "research", "arithmetic", "checker")
# arithmetic: {"emin": int|None, "emax": int|None, "mode": "P"|"E"}
# checker:    {"strategy": "min_fill"|"dense_min_fill", "precision": int}
ARITH_KEYS = ("emin", "emax", "mode")
CHECKER_KEYS = ("strategy", "precision")


def validate_program(prog: dict) -> dict:
    """Strict parse of the program block of a plan record. Returns a dict
    with exact rationals and typed structures."""
    if not isinstance(prog, dict):
        raise ProgramError("program must be a mapping")
    _need(prog, PROGRAM_KEYS, "program")
    kind = prog["kind"]
    if kind not in ("identity", "regional", "composed", "statistic",
                    "gaussian", "fourier", "mixed"):
        raise ProgramError("unknown program kind %r" % kind)
    scales = [scale_from_jsonable(s) for s in prog["scales"]]
    if kind in ("identity", "statistic", "gaussian", "fourier", "mixed") and scales:
        raise ProgramError("kind %s carries coarsening scales" % kind)
    if kind in ("regional", "composed") and not scales:
        raise ProgramError("kind %s carries no coarsening scale" % kind)
    if len(scales) > 2:
        raise ProgramError("more than two coarsening scales")
    coll = None
    if prog["collective"] is not None:
        coll = collective_from_jsonable(prog["collective"])
    if kind in ("composed", "statistic", "gaussian", "fourier", "mixed") and coll is None:
        raise ProgramError("kind %s carries no collective record" % kind)
    if kind in ("identity", "regional") and coll is not None:
        raise ProgramError("kind %s carries a collective record" % kind)
    if kind in ("statistic", "gaussian", "fourier", "mixed") and \
            coll["evaluator"] != kind:
        raise ProgramError("kind %s names evaluator %s" % (kind, coll["evaluator"]))
    order = [int(x) for x in prog["order"]]
    if kind == "identity" and not order:
        raise ProgramError("an identity program must record its elimination order")
    prec = int(prog["precision"])
    if prec < 8:
        raise ProgramError("precision %d is not usable" % prec)
    queries = sorted(int(x) for x in prog["queries"])
    research = prog["research"]
    if not isinstance(research, dict):
        raise ProgramError("research must be a mapping")
    arith = prog["arithmetic"]
    _need(arith, ARITH_KEYS, "arithmetic")
    for k in ("emin", "emax"):
        if arith[k] is not None and not isinstance(arith[k], int):
            raise ProgramError("arithmetic %s must be an integer or null" % k)
    if arith["mode"] not in ("P", "E"):
        raise ProgramError("arithmetic mode %r is not P (MPFR point) or E (exact)"
                           % (arith["mode"],))
    if (kind == "identity") != (arith["mode"] == "P"):
        raise ProgramError("the identity program runs the MPFR point kernel (mode "
                           "P); program routes run exact arithmetic (mode E)")
    chk = prog["checker"]
    _need(chk, CHECKER_KEYS, "checker")
    if chk["strategy"] not in ("min_fill_interval", "dense_min_fill"):
        raise ProgramError("unknown checker strategy %r" % (chk["strategy"],))
    if (kind == "identity") != (chk["strategy"] == "min_fill_interval"):
        raise ProgramError("checker strategy %r does not match kind %s"
                           % (chk["strategy"], kind))
    if int(chk["precision"]) < 8:
        raise ProgramError("checker precision is not usable")
    return {"kind": kind, "scales": scales, "collective": coll, "order": order,
            "precision": prec, "queries": queries, "research": research,
            "arithmetic": {"emin": arith["emin"], "emax": arith["emax"],
                           "mode": arith["mode"]},
            "checker": {"strategy": chk["strategy"], "precision": int(chk["precision"])}}
