"""Public API: solve(model, queries, requested_width, limits) and verify(model, result)."""
from __future__ import annotations
from fractions import Fraction as Fr
import time, json
from cbi import model as M, arith as A, coarse as CO, plan as PL, tree as TR

STATUSES = ("CERTIFIED", "VALID_BUT_TOO_WIDE", "INFEASIBLE", "UNSUPPORTED_INPUT", "RESOURCE_LIMIT")


def _timed(timings, name, t0):
    timings[name] = timings.get(name, 0.0) + (time.monotonic() - t0)


def solve(model, queries="all", requested_width="1/100", limits=None):
    """model: cbi.model.Model or a JSON-like dict; queries: "all" or a list of block ids; requested_width: rational string / Fraction.
    Returns a plain dict: status, intervals {block: {coord: {"lo","hi" (grid ints on 2^-80), "exact": [lo, hi]}}}, certificate, plan, timings."""
    T0 = time.monotonic(); timings = {}; eps = Fr(requested_width); limits = dict(limits or {})
    out = {"status": None, "requested_width": str(eps), "grid_bits": A.GRID_BITS, "intervals": {}, "certificate": {}, "plan": {}, "timings": timings, "statuses_per_query": {}}
    try:
        t0 = time.monotonic()
        m = model if isinstance(model, M.Model) else M.Model.from_json(model)
        qs = sorted(m.blocks) if queries == "all" else sorted(int(q) for q in queries)
        for q in qs:
            if q not in m.blocks:
                raise M.UnsupportedInput("query block %d does not exist" % q)
        _timed(timings, "validate", t0)
        # --- exact reductions I: hard components
        t0 = time.monotonic()
        m2, o2r, members, log, scalars, infeasible = M.contract_hard(m)
        _timed(timings, "reduce_hard", t0)
        if infeasible:
            out.update({"status": "INFEASIBLE", "certificate": {"zero_partition_proof": infeasible}, "plan": {"reductions": log}}); return _finish(out, T0)
        # --- coarsening (Theorem 3)
        t0 = time.monotonic()
        clusters, how = ([], "disabled by limits.no_coarsening") if limits.get("no_coarsening") else CO.propose_clusters(m2, m.meta.get("cluster_hints"))
        certs = {}; rho = {}; cmap = {b: b for b in m2.blocks}; coarse = m2; cluster_log = {"proposal": how, "proposed": clusters, "verified": [], "rejected": []}
        rho_max = eps / 8                                   # a cluster whose retention defect alone would consume more than an eighth of the width is not coarsened
        if clusters:
            good = []
            for C in clusters:
                try:
                    c = CO.verify_cluster(m2, C)
                    if Fr(c["rho_i"]) > rho_max:
                        cluster_log["rejected"].append({"cluster": C, "reason": "retention defect rho_i = %.3g exceeds the acceptance threshold eps/8 = %.3g (premises verified; coarsening not useful at this width)" % (float(Fr(c["rho_i"])), float(rho_max)), "rho_i": c["rho_i"]})
                        continue
                    good.append(C)
                except ValueError as ex:
                    cluster_log["rejected"].append({"cluster": C, "reason": str(ex)})
            if good:
                coarse, cmap, certs, rho = CO.coarsen(m2, good); cluster_log["verified"] = [{k: v for k, v in c.items() if k not in ("coarse_rows", "coarse_weights")} for c in certs.values()]
        _timed(timings, "coarsen", t0)
        # --- exact reductions II: parallel fusion + separable absorption on the (coarse) graph
        t0 = time.monotonic()
        red = M.reduce_model(coarse)
        _timed(timings, "reduce_separable", t0)
        if red.infeasible:
            out.update({"status": "INFEASIBLE", "certificate": {"zero_partition_proof": red.infeasible}}); return _finish(out, T0)
        out["plan"] = {"reductions": log + red.log, "dropped_scalars": len(scalars) + len(red.scalars), "clusters": cluster_log, "queries": {}, "map": {"orig_to_hard": o2r, "hard_to_coarse": cmap}}
        # --- per query
        planner = PL.Planner(red, eps, limits, rho=rho)
        statuses = {}
        for q in qs:
            t0 = time.monotonic()
            rq = cmap[o2r[q]]
            best, attempts = planner.solve_query(rq)
            _timed(timings, "plan_and_solve", t0)
            out["plan"]["queries"][str(q)] = {"reduced_block": rq, "attempts": attempts}
            if best is None:
                statuses[q] = "RESOURCE_LIMIT"; continue
            t0 = time.monotonic()
            rows = []
            for j, (lo, hi) in enumerate(best["intervals_exact"]):
                lg, hg = A.publish(lo, hi); rows.append({"lo": lg, "hi": hg, "exact": [str(lo), str(hi)], "width": str(Fr(hg - lg, 1 << A.GRID_BITS))})
            wmax = max(Fr(r["hi"] - r["lo"], 1 << A.GRID_BITS) for r in rows)
            out["intervals"][str(q)] = {"coordinates": rows, "max_width": str(wmax), "max_width_float": float(wmax), "width_met": bool(wmax <= eps), "coarse_block": rq}
            c = dict(best["cert"]); c.pop("intervals_exact", None); c["xi"] = {str(k): v for k, v in best["xi"].items()}; c["mode"] = best["mode"]
            out["certificate"][str(q)] = c
            statuses[q] = "CERTIFIED" if wmax <= eps else "VALID_BUT_TOO_WIDE"
            _timed(timings, "publish", t0)
        out["statuses_per_query"] = {str(k): v for k, v in statuses.items()}
        if all(v == "CERTIFIED" for v in statuses.values()):
            out["status"] = "CERTIFIED"
        elif any(v in ("CERTIFIED", "VALID_BUT_TOO_WIDE") for v in statuses.values()):
            out["status"] = "VALID_BUT_TOO_WIDE" if any(v == "VALID_BUT_TOO_WIDE" for v in statuses.values()) else "RESOURCE_LIMIT"
        else:
            out["status"] = "RESOURCE_LIMIT"
        out["model_sha256"] = m.sha256()
    except M.UnsupportedInput as ex:
        out.update({"status": "UNSUPPORTED_INPUT", "reason": str(ex)})
    return _finish(out, T0)


def _finish(out, T0):
    out["timings"]["total_solve"] = time.monotonic() - T0
    return out


def verify(model, result):
    from cbi import verify as V
    return V.verify(model, result)
