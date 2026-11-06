"""Planner / selector: uses ONLY the input -- never a reference answer. Two graphs: the ORIGINAL-LAW influence system (components, regions,
transport) and the simplified computational graph of Q (operators, solves). Per influence component: a forest or cheaply priced component
is solved exactly on the whole component (zero transport unless a node carries a retention defect); otherwise a radius-1 (then radius-2)
region with fixed outside states and the cheapest prospectively qualified operator per inside edge; escalation raises degrees, enlarges the
region or goes exact while limits permit. Component pricing is cached; every attempt is recorded and counted."""
from __future__ import annotations
from fractions import Fraction as Fr
import time
from cbi import model as M, arith as A, transfer as T, tree as TR, exact as EX, region as RG

DEFAULT_LIMITS = {"max_entries": 1 << 20, "exact_direct_entries": 1 << 14, "max_pairs_per_edge": 1 << 25, "degrees": [0, 1, 2, 3], "radii": [0, 1],
                  "max_region_radius": 2, "max_attempts": 8, "max_time_s": 120.0, "T_iterations": 64, "force_exact": False, "no_coarsening": False}


class TimeLimit(Exception):
    pass


def _edge_key(e):
    return (min(e.u, e.v), max(e.u, e.v))


def prospective_op(e, mu, mv, eps_edge, limits, surrogate_allowed=False):
    dp = e.s(); r = e.r; cands = []
    pairs = mu["m"] * mv["m"]
    if pairs <= limits["max_pairs_per_edge"]:
        cands.append((("exact",), T.work_estimate(("exact",), mu["m"], mv["m"], dp)))
    for k in limits["degrees"]:
        if k >= dp:
            continue
        bound = A.tail(dp, k, r) / (1 - r) ** dp if r < 1 else None
        if bound is not None and bound <= eps_edge:
            w = T.work_estimate(("fourier", k), mu["m"], mv["m"], dp)
            if surrogate_allowed:
                cands.append((("poly", k), w))
            cands.append((("fourier", k), w))
    ov = min(mu.get("ov", Fr(0)), mv.get("ov", Fr(0)))
    if ov > 0 and r < 1:
        u, v = A.uv(r)
        for h in limits["radii"]:
            if h >= dp:
                continue
            rho = Fr((1 - ov) * A.kappa_int(dp, u, v, h + 1), ov * A.kappa_int(dp, u, v, 0))
            if rho <= eps_edge:
                cands.append((("sparse", h), T.work_estimate(("sparse", h), mu["m"], mv["m"], dp)))
    if not cands:
        return None, {}
    pref = {"poly": 0, "fourier": 1, "sparse": 2, "exact": 3}
    return min(cands, key=lambda c: (c[1], pref[c[0][0]], str(c[0])))[0], {str(c[0]): c[1] for c in cands}


def overlap_fraction(red, cadj, u, v):
    e = cadj[u][v]; bu, bv = red.blocks[u], red.blocks[v]; agg = {}
    for x, w in zip(bv.rows, bv.w):
        agg[x & e.mask] = agg.get(x & e.mask, 0) + w
    num = sum(w * agg.get(x & e.mask, 0) for x, w in zip(bu.rows, bu.w))
    return Fr(num, sum(bu.w) * sum(bv.w))


class Planner:
    def __init__(self, infl, red, eps, limits, t_start=None):
        self.infl = infl; self.red = red; self.eps = Fr(eps); self.limits = dict(DEFAULT_LIMITS); self.limits.update(limits or {})
        self.cadj = M.adjacency(red); self.t0 = t_start if t_start is not None else time.monotonic()
        self.comps = infl.components(); self.comp_of = {b: i for i, c in enumerate(self.comps) for b in c}
        self._price = {}; self.batched = {}                      # component index -> {node: IVec belief} for exact whole-forest solves

    def deadline(self):
        if time.monotonic() - self.t0 > self.limits["max_time_s"]:
            raise TimeLimit("time limit %.1f s" % self.limits["max_time_s"])

    def comp_price(self, ci):
        if ci not in self._price:
            comp = self.comps[ci]; edges = [e for e in self.red.edges if e.u in comp and e.v in comp]
            forest = len(edges) <= len(comp) - 1 and M.is_forest(M.Reduced(self.red.d, {v: self.red.blocks[v] for v in comp}, edges, {}, {}))
            self._price[ci] = (0, forest) if forest else (EX.price({v: self.red.blocks[v] for v in comp}, edges, comp[0])[0], False)
        return self._price[ci]

    def batched_forest(self, ci):
        """All node beliefs of an exact whole-forest component in ONE two-pass schedule (exact operators; no transport unless a node carries
        rho, in which case the per-query certificate is built from the shared beliefs). Returns {node: IVec} or None."""
        if ci in self.batched:
            return self.batched[ci]
        comp = self.comps[ci]; edges = [e for e in self.red.edges if e.u in comp and e.v in comp]
        ops = {_edge_key(e): ("exact",) for e in edges}
        for e in edges:
            if len(self.red.blocks[e.u].rows) * len(self.red.blocks[e.v].rows) > self.limits["max_pairs_per_edge"]:
                self.batched[ci] = None; return None
        ts = TR.TreeSolver({v: self.red.blocks[v] for v in comp}, edges, ops, deadline=self.deadline)
        self.batched[ci] = (ts.all_beliefs(), ops, ts.minfo); return self.batched[ci]

    def solve_query(self, q):
        ci = self.comp_of[q]; comp = self.comps[ci]; attempts = []; best = None
        comp_price, forest = self.comp_price(ci)
        if forest and not any(self.infl.rho.get(v, Fr(0)) > 0 for v in comp) and not any(u not in comp for v in comp for u in self.infl.adj[v]):
            # exact law of the whole component: shared two-pass messages, zero transport
            try:
                bt = self.batched_forest(ci)
            except TimeLimit as ex:
                return None, [{"mode": "TREE_MESSAGE", "status": "RESOURCE_LIMIT", "reason": str(ex)}]
            if bt is not None:
                bel, ops, minfo = bt
                lu = TR.coordinate_intervals(bel[q], self.red.blocks[q].rows, self.red.d)
                cert = {"H": sorted(comp), "xi": {}, "inside_ops": {"%d-%d" % k: list(v) for k, v in ops.items()}, "theta": {"%d-%d" % k: str(v) for k, v in self.infl.theta.items() if k[0] in comp or k[1] in comp},
                        "d": {str(v): "0" for v in comp}, "beta": {str(v): "0" for v in comp}, "b": {str(v): "0" for v in comp}, "eta": {"%d-%d" % k: "0" for k in ops}, "rho": {}, "z": {str(v): "0" for v in comp}, "iterations": 0,
                        "z_query": "0", "transport": "none (exact law of the whole influence component; exact operators, batched two-pass schedule)", "regional_lu": [[str(l), str(u)] for l, u in lu],
                        "intervals_exact": lu, "solver_info": {"regional_solver": "tree_batched", "messages": {"%d->%d" % k: v for k, v in minfo.items()}}, "query_block": q}
                width = max(hi - lo for lo, hi in lu)
                attempts.append({"mode": "TREE_MESSAGE", "H": sorted(comp), "radius": len(comp), "ops": cert["inside_ops"], "width": str(width), "width_float": float(width), "z_query": "0", "iterations": 0, "status": "OK", "batched": True, "elapsed_s": time.monotonic() - self.t0})
                return {"mode": "TREE_MESSAGE", "H": sorted(comp), "xi": {}, "ops": ops, "cert": cert, "intervals_exact": lu, "width": width, "attempt": 1}, attempts
        whole_ok = forest or comp_price <= self.limits["max_entries"]
        radius = len(comp) if (forest or comp_price <= self.limits["exact_direct_entries"] or self.limits["force_exact"]) else 1
        while len(attempts) < self.limits["max_attempts"]:
            try:
                self.deadline()
            except TimeLimit as ex:
                attempts.append({"mode": "-", "status": "RESOURCE_LIMIT", "reason": str(ex)}); break
            H = set(comp) if radius >= len(comp) else self.infl.ball(q, radius)
            inside = [e for e in self.red.edges if e.u in H and e.v in H]
            sub = M.Reduced(self.red.d, {v: self.red.blocks[v] for v in H}, inside, {}, {})
            sub_forest = M.is_forest(sub)
            outside_comp = sorted({u for v in H for u in self.cadj[v] if u not in H})        # computational crossing edges need fixed states
            xi = {u: RG.fixed_outside_state(self.red.blocks[u]) for u in outside_comp}
            eps_edge = self.eps / (4 * max(1, len(inside)))
            ops = {}; menus = {}; missing = []
            if attempts and attempts[-1].get("_next_ops"):
                ops = dict(attempts[-1]["_next_ops"])
            elif self.limits["force_exact"]:
                ops = {_edge_key(e): ("exact",) for e in inside}
            else:
                for e in inside:
                    ov = overlap_fraction(self.red, self.cadj, e.u, e.v)
                    mu = {"m": len(self.red.blocks[e.u].rows), "ov": ov}; mv = {"m": len(self.red.blocks[e.v].rows), "ov": ov}
                    op, menu = prospective_op(e, mu, mv, eps_edge, self.limits, surrogate_allowed=(H != set(comp)))
                    menus["%d-%d" % _edge_key(e)] = menu
                    if op is None:
                        missing.append(_edge_key(e))
                    else:
                        ops[_edge_key(e)] = op
            if missing:
                attempts.append({"mode": "-", "H": sorted(H), "status": "RESOURCE_LIMIT", "reason": "no operator within max_pairs_per_edge qualifies on edges %s" % missing[:4]}); break
            if not sub_forest:
                worst, _ = EX.price({v: self.red.blocks[v] for v in H}, inside, q)
                if worst > self.limits["max_entries"]:
                    attempts.append({"mode": "REGION_SURROGATE" if H != set(comp) else "EXACT_VE", "H": sorted(H), "status": "RESOURCE_LIMIT", "radius": radius,
                                     "reason": "the region graph has cycles and its dense elimination needs %d entries > limit %d" % (worst, self.limits["max_entries"])}); break
                ops = {_edge_key(e): ("exact",) for e in inside}
            if H == set(comp):
                mode = "TREE_MESSAGE" if sub_forest else "EXACT_VE"
            else:
                mode = "REGION_SURROGATE"
            if any(self.infl.rho.get(v, Fr(0)) > 0 for v in H):
                mode = "COARSE_REGION" + ("" if H == set(comp) else "+SURROGATE")
            try:
                cert = RG.certify(self.infl, self.red, H, xi, ops, q, T_max=self.limits["T_iterations"], max_entries=self.limits["max_entries"], deadline=self.deadline)
            except EX.TooLarge as ex:
                attempts.append({"mode": mode, "H": sorted(H), "status": "RESOURCE_LIMIT", "reason": str(ex)}); break
            except TimeLimit as ex:
                attempts.append({"mode": mode, "H": sorted(H), "status": "RESOURCE_LIMIT", "reason": str(ex)}); break
            except RG.SurrogateError as ex:
                att = {"mode": mode, "H": sorted(H), "status": "REJECTED_SURROGATE", "reason": str(ex), "ops": {"%d-%d" % k: list(v) for k, v in ops.items()}}
                att["_next_ops"] = {k: (("exact",) if v[0] == "poly" else v) for k, v in ops.items()}; att["escalation"] = "surrogate rejected: exact kernels on those edges"; attempts.append(att); continue
            width = max(hi - lo for lo, hi in cert["intervals_exact"])
            att = {"mode": mode, "H": sorted(H), "radius": radius, "ops": {"%d-%d" % k: list(v) for k, v in ops.items()}, "menus": menus, "width": str(width), "width_float": float(width),
                   "z_query": cert["z_query"], "iterations": cert["iterations"], "status": "OK", "elapsed_s": time.monotonic() - self.t0}
            attempts.append(att)
            res = {"mode": mode, "H": sorted(H), "xi": xi, "ops": ops, "cert": cert, "intervals_exact": cert["intervals_exact"], "width": width, "attempt": len(attempts)}
            if best is None or width < best["width"]:
                best = res
            if width + A.EPS_PUBLISH_SLACK <= self.eps:
                break
            zq = Fr(cert["z_query"]); lu_w = max(Fr(u) - Fr(l) for l, u in cert["regional_lu"])
            if lu_w > 2 * zq and any(v[0] != "exact" for v in ops.values()):
                new = {}
                for k, v in ops.items():
                    if v[0] in ("fourier", "poly"):
                        nk = int(v[1]) + 1; new[k] = (v[0], nk) if nk in self.limits["degrees"] else ("exact",)
                    elif v[0] == "sparse":
                        nh = int(v[1]) + 1; new[k] = ("sparse", nh) if nh in self.limits["radii"] else ("exact",)
                    else:
                        new[k] = v
                att["_next_ops"] = new; att["escalation"] = "numerical width dominates: raise degrees / radii, exact where exhausted"; continue
            if H != set(comp) and radius < self.limits["max_region_radius"]:
                radius += 1; att["escalation"] = "transport radius dominates: enlarge the region to radius %d" % radius; continue
            if H != set(comp) and whole_ok:
                radius = len(comp); att["escalation"] = "whole component exactly (priced %d entries within the limit)" % comp_price; continue
            if any(v[0] != "exact" for v in ops.values()):
                att["_next_ops"] = {k: ("exact",) for k in ops}; att["escalation"] = "last resort: exact operators"; continue
            break
        for a in attempts:
            a.pop("_next_ops", None)
        return best, attempts
