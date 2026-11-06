"""Public API: solve(model, queries, requested_width, limits) and verify(model, result).

solve keeps TWO structures: the ORIGINAL-LAW influence system (hard-contracted blocks with verified clusters merged; theta from original
supports; retention defects rho) for every transport / connectivity decision, and the simplified computational graph of Q (parallel fusion,
separable absorption) for solving. Queries mapped to the same node are solved once; exact whole-forest components are solved with one
two-pass message schedule for all their queries. When coarsening is available but a query's coarse certificate misses the width, the
uncoarsened plan is tried as a second complete candidate and the narrower certificate is kept (both attempts recorded)."""
from __future__ import annotations
from fractions import Fraction as Fr
import time
from cbi import model as M, arith as A, coarse as CO, plan as PL, tree as TR, region as RG, influence as IN

STATUSES = ("CERTIFIED", "VALID_BUT_TOO_WIDE", "INFEASIBLE", "UNSUPPORTED_INPUT", "RESOURCE_LIMIT")


def _timed(timings, name, t0):
    timings[name] = timings.get(name, 0.0) + (time.monotonic() - t0)


def _systems(m2, clusters, eps, limits, cluster_log, timings, deadline=None):
    """(influence, computational reduced graph, node map) for the coarse and the plain variants."""
    t0 = time.monotonic(); out = {}
    good = []
    if clusters and not limits.get("no_coarsening"):
        for C in clusters:
            try:
                c = CO.verify_cluster(m2, C, deadline); good.append(C)
            except ValueError as ex:
                cluster_log["rejected"].append({"cluster": C, "reason": str(ex)})
    if good:
        coarse, cmap, certs, rho = CO.coarsen(m2, good, deadline)
        cluster_log["verified"] = [{k: v for k, v in c.items() if k not in ("coarse_rows", "coarse_weights")} for c in certs.values()]
        red = M.reduce_model(coarse)
        if red.infeasible is None:
            out["coarse"] = (IN.Influence(m2, cmap, rho), red, cmap)
    red0 = M.reduce_model(m2)
    if red0.infeasible is None:
        out["plain"] = (IN.Influence(m2, {b: b for b in m2.blocks}, {}), red0, {b: b for b in m2.blocks})
    _timed(timings, "build_systems", t0)
    return out


def solve(model, queries="all", requested_width="1/100", limits=None):
    T0 = time.monotonic(); timings = {}
    out = {"status": None, "requested_width": None, "grid_bits": A.GRID_BITS, "intervals": {}, "certificate": {}, "proofs": {}, "plan": {}, "timings": timings, "statuses_per_query": {}, "requested_queries": None}
    proof_ids = {}
    try:
        try:
            eps = Fr(requested_width)
        except (ValueError, ZeroDivisionError, TypeError):
            raise M.UnsupportedInput("requested_width %r is not a rational" % (requested_width,))
        if not (0 < eps <= 1):
            raise M.UnsupportedInput("requested_width must lie in (0, 1]")
        out["requested_width"] = str(eps)
        if limits is not None and not isinstance(limits, dict):
            raise M.UnsupportedInput("limits must be a dict")
        limits = dict(limits or {})
        for k, v in limits.items():
            if k not in PL.DEFAULT_LIMITS:
                raise M.UnsupportedInput("unknown limit %r" % k)
            if k in ("degrees", "radii"):
                if not (isinstance(v, list) and all(isinstance(x, int) and not isinstance(x, bool) and x >= 0 for x in v)):
                    raise M.UnsupportedInput("limit %r must be a list of nonnegative integers" % k)
            elif k in ("force_exact", "no_coarsening"):
                if not isinstance(v, bool):
                    raise M.UnsupportedInput("limit %r must be a bool" % k)
            elif not (isinstance(v, (int, float)) and not isinstance(v, bool) and v > 0):
                raise M.UnsupportedInput("limit %r must be a positive number" % k)
        if queries != "all":
            try:
                queries = [int(q) for q in queries]
            except (TypeError, ValueError):
                raise M.UnsupportedInput("queries must be 'all' or a list of block ids")
        deadline_s = float(limits.get("max_time_s", PL.DEFAULT_LIMITS["max_time_s"]))
        def deadline():
            if time.monotonic() - T0 > deadline_s:
                raise PL.TimeLimit("time limit %.1f s" % deadline_s)
        t0 = time.monotonic()
        m = (model if isinstance(model, M.Model) else M.Model.from_json(model)).validate()
        qs = sorted(m.blocks) if queries == "all" else sorted(set(int(q) for q in queries))
        for q in qs:
            if q not in m.blocks:
                raise M.UnsupportedInput("query block %d does not exist" % q)
        out["requested_queries"] = qs; out["model_sha256"] = m.sha256()
        _timed(timings, "validate", t0)
        t0 = time.monotonic(); m2, o2r, members, log, scalars, infeasible = M.contract_hard(m); _timed(timings, "reduce_hard", t0)
        if infeasible:
            out.update({"status": "INFEASIBLE", "certificate": {"zero_partition_proof": infeasible}, "plan": {"reductions": log}}); return _finish(out, T0)
        t0 = time.monotonic()
        clusters, how = ([], "disabled by limits.no_coarsening") if limits.get("no_coarsening") else CO.propose_clusters(m2, m.meta.get("cluster_hints"), o2r)
        cluster_log = {"proposal": how, "proposed": clusters, "verified": [], "rejected": []}
        _timed(timings, "coarsen_propose", t0)
        systems = _systems(m2, clusters, eps, limits, cluster_log, timings, deadline)
        if not systems:
            out.update({"status": "INFEASIBLE", "certificate": {"zero_partition_proof": M.reduce_model(m2).infeasible}}); return _finish(out, T0)
        out["plan"] = {"reductions": log, "dropped_scalars": len(scalars), "clusters": cluster_log, "queries": {}, "systems": {k: {"nodes": len(v[0].nodes), "influence_edges": len(v[0].theta), "computational_edges": len(v[1].edges), "influence": v[0].record()} for k, v in systems.items()},
                       "map": {"orig_to_hard": o2r}}
        planners = {k: PL.Planner(v[0], v[1], eps, limits, t_start=T0) for k, v in systems.items()}
        order = [k for k in ("coarse", "plain") if k in systems]
        statuses = {}; cache = {}                                 # (system, node) -> (best, attempts)
        for q in qs:
            t0 = time.monotonic()
            trials = []
            for k in order:
                node = systems[k][2][o2r[q]]
                if (k, node) not in cache:
                    cache[(k, node)] = planners[k].solve_query(node)
                best, attempts = cache[(k, node)]
                trials.append({"system": k, "node": node, "best_width": (str(best["width"]) if best else None), "attempts": attempts})
                if best is not None and best["width"] + A.EPS_PUBLISH_SLACK <= eps:
                    break                                          # certified: no need for the second candidate system
            _timed(timings, "plan_and_solve", t0)
            cands = [(t["system"], cache[(t["system"], t["node"])][0]) for t in trials if cache[(t["system"], t["node"])][0] is not None]
            out["plan"]["queries"][str(q)] = {"trials": trials}
            if not cands:
                statuses[q] = "RESOURCE_LIMIT"; continue
            sysk, best = min(cands, key=lambda kb: kb[1]["width"])
            t0 = time.monotonic()
            rows = []
            for lo, hi in best["intervals_exact"]:
                lg, hg = A.publish(lo, hi); rows.append({"lo": lg, "hi": hg, "exact": [str(lo), str(hi)], "width": str(Fr(hg - lg, 1 << A.GRID_BITS))})
            wmax = max(Fr(r["hi"] - r["lo"], 1 << A.GRID_BITS) for r in rows)
            out["intervals"][str(q)] = {"coordinates": rows, "max_width": str(wmax), "max_width_float": float(wmax), "width_met": bool(wmax <= eps), "system": sysk, "node": systems[sysk][2][o2r[q]]}
            pk = (sysk,) + best["proof_key"]
            if pk not in proof_ids:
                pid = "P%d" % len(proof_ids); proof_ids[pk] = pid
                pr = dict(best["proof"]); pr["system"] = sysk; pr["mode"] = best["mode"]; out["proofs"][pid] = pr
            out["certificate"][str(q)] = {"proof": proof_ids[pk], "node": systems[sysk][2][o2r[q]], "system": sysk, "mode": best["mode"], "H": best["H"],
                                          "z_query": str(Fr(best["proof"]["z_grid"][str(systems[sysk][2][o2r[q]])], 1 << best["proof"]["z_grid_bits"])), "iterations": best["proof"]["iterations"]}
            statuses[q] = "CERTIFIED" if wmax <= eps else "VALID_BUT_TOO_WIDE"
            _timed(timings, "publish", t0)
        out["statuses_per_query"] = {str(k): v for k, v in statuses.items()}
        vals = list(statuses.values())
        out["status"] = "CERTIFIED" if vals and all(v == "CERTIFIED" for v in vals) else ("VALID_BUT_TOO_WIDE" if any(v == "VALID_BUT_TOO_WIDE" for v in vals) else "RESOURCE_LIMIT")
    except M.UnsupportedInput as ex:
        out.update({"status": "UNSUPPORTED_INPUT", "reason": str(ex)})
    except PL.TimeLimit as ex:
        out.update({"status": "RESOURCE_LIMIT", "reason": str(ex)})
    return _finish(out, T0)


def _finish(out, T0):
    out["timings"]["total_solve"] = time.monotonic() - T0
    return out


def verify(model, result):
    from cbi import verify as V
    return V.verify(model, result)
