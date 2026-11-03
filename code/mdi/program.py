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
    for k in ("t_level", "R_level", "deletion_radius_total"):
        if _fr(d[k], k) < 0:
            raise ProgramError("scale radius %s is negative (%s): an invalid proof budget" % (k, d[k]))
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
            "kind": str(cand.kind),
            "masked": [[int(a), int(b)] for a, b in (getattr(cand, "masked", None) or [])],
            "strict": bool(getattr(cand, "strict", False))}


def cand_from_jsonable(d: dict):
    _need(d, ("signs", "gammas", "features", "kind", "masked", "strict"), "mode candidate")
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
    masked = []
    for pr in d.get("masked") or []:
        if not (isinstance(pr, (list, tuple)) and len(pr) == 2):
            raise ProgramError("a masked pair must be a 2-list of variables")
        masked.append((int(pr[0]), int(pr[1])))
    if not isinstance(d["strict"], bool):
        raise ProgramError("the strict flag must be a boolean")
    return MD.ModeCandidate(signs=signs, gammas=gammas, features=feats,
                            kind=str(d["kind"]), masked=masked, strict=d["strict"])


GRID_KEYS = ("rule", "version", "sign", "beta", "R", "tol", "t", "m", "T", "b", "h",
             "nodes", "signed_frequencies", "representatives", "error", "error_kind")


def _grid_from_jsonable(g: dict) -> dict:
    term = ("K",) if int(g.get("sign", 0)) > 0 else ("J",)
    _need(g, GRID_KEYS + term, "GF grid record")
    out = {"rule": str(g["rule"]), "version": int(g["version"]), "sign": int(g["sign"]),
           "beta": _fr(g["beta"], "grid beta"), "R": _fr(g["R"], "grid R"),
           "tol": _fr(g["tol"], "grid tolerance"), "t": int(g["t"]), "m": int(g["m"]),
           "T": int(g["T"]), "b": int(g["b"]), "h": _fr(g["h"], "grid spacing"),
           "nodes": int(g["nodes"]), "signed_frequencies": int(g["signed_frequencies"]),
           "representatives": int(g["representatives"]), "error": _fr(g["error"], "grid error"),
           "error_kind": str(g["error_kind"])}
    if out["sign"] not in (1, -1):
        raise ProgramError("grid sign must be +1 or -1")
    if out["sign"] > 0:
        if "K" not in g:
            raise ProgramError("a positive GF1 grid needs its terminal index K")
        out["K"] = int(g["K"])
    else:
        if "J" not in g:
            raise ProgramError("a negative GF2 grid needs its terminal index J")
        out["J"] = int(g["J"])
    if out["m"] < 1 or out["h"] <= 0 or out["nodes"] < 1 or out["tol"] <= 0:
        raise ProgramError("a GF grid has non-positive parameters")
    if out["error"] <= 0:
        raise ProgramError("a GF grid records a non-positive error allocation %s" % out["error"])
    if out["h"] != Fr(1, out["m"]):
        raise ProgramError("GF grid spacing %s is not 1/m = 1/%d" % (out["h"], out["m"]))
    term = out["K"] if out["sign"] > 0 else out["J"]
    if term < 0:
        raise ProgramError("GF grid terminal index is negative")
    if out["signed_frequencies"] != 2 * term + 1 or out["nodes"] != 2 * term + 1:
        raise ProgramError("GF grid signed-frequency count %d / node count %d do not match the "
                           "terminal index %d (2 x %d + 1)" % (out["signed_frequencies"], out["nodes"], term, term))
    want_rep = (2 * term + 1) if out["sign"] > 0 else (term + 1)
    if out["representatives"] != want_rep:
        raise ProgramError("GF grid representative count %d does not match the terminal index %d"
                           % (out["representatives"], term))
    return out


COLLECTIVE_KEYS = ("evaluator", "candidate", "Q", "delta", "deltas", "grids",
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
           "grids": (None if d["grids"] is None else [_grid_from_jsonable(g) for g in d["grids"]]),
           "fit_tv": _fr(d["fit_tv"], "fit_tv"),
           "rounding_tv": _fr(d["rounding_tv"], "rounding_tv"),
           "quadrature_tv": _fr(d["quadrature_tv"], "quadrature_tv"),
           "precision": int(d["precision"]), "round_bits": int(d["round_bits"]),
           "kept_factors": [int(x) for x in d["kept_factors"]],
           "dropped_pairs": [[int(a), int(b)] for a, b in d["dropped_pairs"]],
           "drop_budget": _fr(d["drop_budget"], "drop_budget")}
    if out["Q"] is not None and out["Q"] < 1:
        raise ProgramError("Q must be a positive integer")
    for k in ("fit_tv", "rounding_tv", "quadrature_tv", "drop_budget"):
        if out[k] < 0:
            raise ProgramError("collective radius %s is negative (%s): an invalid proof budget" % (k, out[k]))
    if out["evaluator"] == "statistic":
        if out["Q"] is None or out["deltas"] is not None:
            raise ProgramError("a statistic record needs Q and no lattice deltas")
    else:
        if out["deltas"] is None or len(out["deltas"]) != out["candidate"].rank:
            raise ProgramError("a quadrature record needs one lattice delta per mode")
        if out["grids"] is None or len(out["grids"]) != out["candidate"].rank:
            raise ProgramError("a quadrature record needs one GF grid per mode")
        for k, g in enumerate(out["grids"]):
            if g["sign"] != out["candidate"].signs[k]:
                raise ProgramError("grid %d has sign %d but mode sign %d"
                                   % (k, g["sign"], out["candidate"].signs[k]))
            if Fr(g["tol"]) != out["deltas"][k]:
                raise ProgramError("grid %d tolerance %s differs from the recorded delta %s"
                                   % (k, g["tol"], out["deltas"][k]))
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
# support (OPTIONAL, identity only; bounded pilot 3 November 2026): the compiled global
# support the sparse executor and the sparse checkers run on -- the checker reconstructs
# it independently and refuses unless rows_per_bag / rows_total / digest agree exactly
SUPPORT_KEYS = ("compiled", "digest", "rows_total", "max_rows", "rows_per_bag", "sep_entries", "method")
OPTIONAL_PROGRAM_KEYS = ("support",)
# arithmetic: {"emin": int|None, "emax": int|None, "mode": "P"|"E"}
# checker:    {"strategy": "min_fill"|"dense_min_fill", "precision": int}
ARITH_KEYS = ("emin", "emax", "mode")
CHECKER_KEYS = ("strategy", "precision")


def validate_program(prog: dict) -> dict:
    """Strict parse of the program block of a plan record. Returns a dict
    with exact rationals and typed structures."""
    if not isinstance(prog, dict):
        raise ProgramError("program must be a mapping")
    _need({k: v for k, v in prog.items() if k not in OPTIONAL_PROGRAM_KEYS}, PROGRAM_KEYS, "program")
    kind = prog["kind"]
    support = None
    if "support" in prog and prog["support"] is not None:
        if kind != "identity":
            raise ProgramError("only an identity program may carry a compiled support")
        sup = prog["support"]
        if not isinstance(sup, dict):
            raise ProgramError("support must be a mapping")
        _need(sup, SUPPORT_KEYS, "support")
        if sup["compiled"] is not True:
            raise ProgramError("support.compiled must be true when a support block is present")
        if not isinstance(sup["rows_per_bag"], list) or not all(isinstance(x, int) and x >= 0 for x in sup["rows_per_bag"]):
            raise ProgramError("support.rows_per_bag must be a list of non-negative integers")
        if int(sup["rows_total"]) != sum(int(x) for x in sup["rows_per_bag"]):
            raise ProgramError("support.rows_total %s does not equal the sum of rows_per_bag %d" % (sup["rows_total"], sum(int(x) for x in sup["rows_per_bag"])))
        if int(sup["max_rows"]) != (max(int(x) for x in sup["rows_per_bag"]) if sup["rows_per_bag"] else 0):
            raise ProgramError("support.max_rows does not equal the largest rows_per_bag entry")
        if not (isinstance(sup["digest"], str) and len(sup["digest"]) == 64):
            raise ProgramError("support.digest must be a 64-hex sha256")
        support = {"compiled": True, "digest": str(sup["digest"]), "rows_total": int(sup["rows_total"]), "max_rows": int(sup["max_rows"]),
                   "rows_per_bag": [int(x) for x in sup["rows_per_bag"]], "sep_entries": int(sup["sep_entries"]), "method": str(sup["method"])}
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
    out = {"kind": kind, "scales": scales, "collective": coll, "order": order,
           "precision": prec, "queries": queries, "research": research,
           "arithmetic": {"emin": arith["emin"], "emax": arith["emax"],
                          "mode": arith["mode"]},
           "checker": {"strategy": chk["strategy"], "precision": int(chk["precision"])}}
    if support is not None:
        out["support"] = support
    return out
