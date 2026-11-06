"""Planner / selector: uses ONLY the input (topology, verified supports, varying-coordinate scans, couplings, overlap masses, work
estimates) -- never a reference answer. Menu per query block: exact or enclosure messages on a forest component; strong-island
coarsening (Theorem 3) when clusters verify; a radius-1 (then radius-2) region with fixed outside states and exact / surrogate / enclosure
operators (Theorem 1); dense exact VE on the component within the priced entry limit. Escalation while limits permit: higher degree on the
edges with the largest realized residual, exact operators, a larger region. Every attempt is recorded and counted."""
from __future__ import annotations
from fractions import Fraction as Fr
import time
from cbi import model as M, arith as A, transfer as T, tree as TR, exact as EX, region as RG, coarse as CO

DEFAULT_LIMITS = {"max_entries": 1 << 20, "exact_direct_entries": 1 << 14, "max_pairs_per_edge": 1 << 25, "degrees": [0, 1, 2, 3], "radii": [0, 1],
                  "max_region_radius": 2, "max_attempts": 8, "max_time_s": 120.0, "T_iterations": 64, "force_exact": False, "no_coarsening": False}


def _edge_key(e):
    return (min(e.u, e.v), max(e.u, e.v))


def prospective_op(e, mu, mv, eps_edge, limits, surrogate_allowed=False):
    """Cheapest operator whose PROSPECTIVE relative residual bound is <= eps_edge (generic bounds, no cavity): exact always qualifies;
    fourier k: tau_k / (1-r)^d'; poly k: the same eta; sparse h: ((1-r)/(1+r))^(h+1) / overlap-free proxy -- sparse is prospectively
    qualified only through the overlap proxy supplied by the caller (mu, mv carry the overlap mass fraction in `ov`)."""
    dp = e.s(); r = e.r
    cands = [(("exact",), T.work_estimate(("exact",), mu["m"], mv["m"], dp))]
    for k in limits["degrees"]:
        if k >= dp:
            continue
        bound = A.tail(dp, k, r) / (1 - r) ** dp if r < 1 else None              # = eta_k: the relative residual of the enclosure AND the surrogate's eta
        if bound is not None and bound <= eps_edge:
            w = T.work_estimate(("fourier", k), mu["m"], mv["m"], dp)
            if surrogate_allowed:
                cands.append((("poly", k), w))                                  # REGION_SURROGATE: a positive surrogate kernel, error charged to b_v
            cands.append((("fourier", k), w))                                   # enclosure operator, error charged to the numerical interval
    ov = min(mu.get("ov", Fr(0)), mv.get("ov", Fr(0)))
    if ov > 0 and r < 1:
        u, v = A.uv(r)
        for h in limits["radii"]:
            if h >= dp:
                continue
            rho = Fr((1 - ov) * A.kappa_int(dp, u, v, h + 1), ov * A.kappa_int(dp, u, v, 0))
            if rho <= eps_edge:
                cands.append((("sparse", h), T.work_estimate(("sparse", h), mu["m"], mv["m"], dp)))
    pref = {"poly": 0, "fourier": 1, "sparse": 2, "exact": 3}
    return min(cands, key=lambda c: (c[1], pref[c[0][0]], str(c[0])))[0], {str(c[0]): c[1] for c in cands}


def overlap_fraction(red, u, v):
    """Weight fraction of A_u x A_v on the diagonal of the edge's coordinate mask (selection proxy only)."""
    e = next(x for x in red.edges if _edge_key(x) == (min(u, v), max(u, v)))
    bu, bv = red.blocks[u], red.blocks[v]; agg = {}
    for x, w in zip(bv.rows, bv.w):
        agg[x & e.mask] = agg.get(x & e.mask, 0) + w
    num = sum(w * agg.get(x & e.mask, 0) for x, w in zip(bu.rows, bu.w))
    return Fr(num, sum(bu.w) * sum(bv.w))


def ball(red, q, radius):
    adj = M.adjacency(red); H = {q}; frontier = {q}
    for _ in range(radius):
        nxt = set()
        for v in frontier:
            nxt |= set(adj[v])
        frontier = nxt - H; H |= nxt
    return H


class Planner:
    def __init__(self, red, eps, limits, rho=None, log=None):
        self.red = red; self.eps = Fr(eps); self.limits = dict(DEFAULT_LIMITS); self.limits.update(limits or {}); self.rho = rho or {}
        self.adj = M.adjacency(red); self.log = log if log is not None else []; self.t0 = time.monotonic()
        self.comps = M.components(red); self.comp_of = {b: i for i, c in enumerate(self.comps) for b in c}

    def time_left(self):
        return self.limits["max_time_s"] - (time.monotonic() - self.t0)

    def solve_query(self, q):
        """Returns (best_result or None, attempts). best_result: dict(mode, H, xi, ops, cert, intervals_exact, width)."""
        comp = self.comps[self.comp_of[q]]; attempts = []; best = None
        comp_edges = [e for e in self.red.edges if e.u in comp]
        forest = len(comp_edges) == len(comp) - 1
        comp_price, _ = EX.price({v: self.red.blocks[v] for v in comp}, comp_edges, q) if not forest else (0, None)
        whole_ok = forest or comp_price <= self.limits["max_entries"]
        # start: a forest component or a cheaply priced whole component is solved on the whole component (exact law, zero transport);
        # otherwise a radius-1 region (Theorem 1)
        radius = len(comp) if (forest or comp_price <= self.limits["exact_direct_entries"] or self.limits["force_exact"]) else 1
        while len(attempts) < self.limits["max_attempts"] and self.time_left() > 0:
            H = set(comp) if radius >= len(comp) else ball(self.red, q, radius)
            inside = [e for e in self.red.edges if e.u in H and e.v in H]
            sub_forest = len(inside) == len(H) - 1
            outside = sorted({u for v in H for u in self.adj[v] if u not in H})
            xi = {u: RG.fixed_outside_state(self.red.blocks[u]) for u in outside}
            eps_edge = self.eps / (4 * max(1, len(inside)))          # prospective per-edge relative residual budget
            ops = {}; menus = {}
            if attempts and attempts[-1].get("escalate_ops"):
                ops = dict(attempts[-1]["escalate_ops"])
            elif self.limits["force_exact"]:
                ops = {_edge_key(e): ("exact",) for e in inside}
            else:
                for e in inside:
                    mu = {"m": len(self.red.blocks[e.u].rows), "ov": overlap_fraction(self.red, e.u, e.v)}; mv = {"m": len(self.red.blocks[e.v].rows), "ov": mu["ov"]}
                    ops[_edge_key(e)], menus["%d-%d" % _edge_key(e)] = prospective_op(e, mu, mv, eps_edge, self.limits, surrogate_allowed=(H != set(comp)))
            if not sub_forest:
                worst, _ = EX.price({v: self.red.blocks[v] for v in H}, inside, q)
                if worst > self.limits["max_entries"]:
                    attempts.append({"mode": "REGION_SURROGATE" if H != set(comp) else "EXACT_VE", "H": sorted(H), "status": "RESOURCE_LIMIT", "radius": radius,
                                     "reason": "the region graph has cycles and its dense elimination needs %d entries > limit %d" % (worst, self.limits["max_entries"])})
                    break
                ops = {_edge_key(e): ("exact",) for e in inside}          # cycles inside the region: exact kernels, dense elimination
            if H == set(comp):
                mode = "TREE_MESSAGE" if sub_forest else "EXACT_VE"
            else:
                mode = "REGION_SURROGATE"
            if self.rho and any(v in self.rho for v in H):
                mode = "COARSE_REGION" + ("" if H == set(comp) else "+SURROGATE")
            try:
                cert = RG.certify(self.red, H, xi, ops, q, rho=self.rho, T_max=self.limits["T_iterations"], max_entries=self.limits["max_entries"])
            except EX.TooLarge as ex:
                attempts.append({"mode": mode, "H": sorted(H), "status": "RESOURCE_LIMIT", "reason": str(ex)}); break
            except ValueError as ex:
                attempts.append({"mode": mode, "H": sorted(H), "status": "REJECTED_SURROGATE", "reason": str(ex), "ops": {"%d-%d" % k: list(v) for k, v in ops.items()}})
                ops = {k: (("exact",) if v[0] == "poly" else v) for k, v in ops.items()}; attempts[-1]["escalate_ops"] = ops; continue
            width = max(hi - lo for lo, hi in cert["intervals_exact"])
            att = {"mode": mode, "H": sorted(H), "radius": radius, "ops": {"%d-%d" % k: list(v) for k, v in ops.items()}, "menus": menus, "width": str(width), "width_float": float(width),
                   "z_query": cert["z_query"], "iterations": cert["iterations"], "status": "OK", "elapsed_s": time.monotonic() - self.t0}
            attempts.append(att)
            res = {"mode": mode, "H": sorted(H), "xi": xi, "ops": ops, "cert": cert, "intervals_exact": cert["intervals_exact"], "width": width, "attempt": len(attempts)}
            if best is None or width < best["width"]:
                best = res
            if width + A.EPS_PUBLISH_SLACK <= self.eps:
                break
            # ---- escalation: (1) raise the degree / switch to exact on inside edges that are not exact; (2) enlarge the region
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
                att["escalate_ops"] = new; att["escalation"] = "numerical width dominates: raise degrees / radii, exact where exhausted"; continue
            if H != set(comp) and radius < self.limits["max_region_radius"]:
                radius += 1; att["escalation"] = "transport radius dominates: enlarge the region to radius %d" % radius; continue
            if H != set(comp) and whole_ok:
                radius = len(comp); att["escalation"] = "whole component exactly (priced %d entries within the limit)" % comp_price; continue
            if any(v[0] != "exact" for v in ops.values()):
                att["escalate_ops"] = {k: ("exact",) for k in ops}; att["escalation"] = "last resort: exact operators"; continue
            break
        return best, attempts
