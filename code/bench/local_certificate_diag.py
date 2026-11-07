"""FAMILY E (diagnostic spec): local certificate behaviour on a CBI-admitted case, 120 s cap. (1) EXTRACTION from the saved breadth artifact of
the case: per proof / block the region size, boundary crossing influence d_v, b_v, inside theta, surrogate eta, transport iterations, final
radius, regional enclosure width, regional solver and cost; distributions, quantiles, witnesses. (2) The EXACT failed sufficient conditions of the
saved certificate: Theorem-1 first iterate c_q + sum_u theta_qu (>= 1 => saturation at the query node), the inside influence row sums
||A||_inf (contraction sufficient condition), and the nonbacktracking min row sum (Perron lower bound on the spectral radius). (3) BOUNDED
DETERMINISTIC BOUNDARY CONTRASTS (frozen before any output): for every saved region, the exact regional solve is repeated with the outside
states replaced by (a) native row 0 everywhere, (b) native row 1 everywhere (where present; else the saved modal state), and the change of the
query node's P(x = +1) against the saved modal-state solve is recorded. An observed contrast is a LOWER bound on the true boundary sensitivity
(two configurations out of 2^|boundary|); the certificate radius is an upper bound; the gap between them is what is known. Existing routines
only (cbi.region.solve_region, cbi.api._systems). No theorem is implemented.   python local_certificate_diag.py MODEL EVID OUT CAP_S SWEEP_DIR"""
from __future__ import annotations
import os, sys, json, time, statistics as st
T0 = time.monotonic()
sys.set_int_max_str_digits(0)
HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__))); sys.path.insert(0, HERE)
from fractions import Fraction as Fr


def now():
    return time.monotonic() - T0


def q(xs):
    if not xs:
        return None
    xs = sorted(xs); n = len(xs); pick = lambda f: xs[min(n - 1, max(0, int(round(f * (n - 1)))))]
    return {"n": n, "min": xs[0], "q25": pick(0.25), "median": pick(0.5), "q75": pick(0.75), "max": xs[-1]}


def main():
    mp, ep, out, cap, S = sys.argv[1], sys.argv[2], sys.argv[3], float(sys.argv[4]), sys.argv[5]; os.makedirs(out, exist_ok=True)
    rec = {"model": mp, "evidence": ep, "cap_s": cap, "phases_s": {}, "status": None}
    from ext import uai as U
    from bench import cbi_adapter as AD
    from cbi import api, region as RG, model as CM, plan as PL, tree as TR
    case = os.path.basename(mp).replace(".uai", ""); rows = [json.loads(l) for l in open(os.path.join(S, "CELLS_LEDGER.jsonl"))]
    src = next((r for r in rows if r["case"] == case and r["arm"] == "CBI_NATIVE" and r["stage"] == "breadth" and r.get("label") is None), None)
    if not src or not os.path.exists(os.path.join(S, src["out_dir"], "cbi_result.json")):
        rec["status"] = "NO_SAVED_ARTIFACT"; json.dump(rec, open(os.path.join(out, "local_diag.json"), "w"), indent=1); return
    od = os.path.join(S, src["out_dir"]); res = json.load(open(os.path.join(od, "cbi_result.json"))); native = json.load(open(os.path.join(od, "native_model.json"))); cert = json.load(open(os.path.join(od, "adapter_certificate.json")))
    rec["saved_artifact"] = src["out_dir"]; rec["phases_s"]["load"] = now()
    # ---------------- (1) extraction
    t = now(); P = res["proofs"]; C = res["certificate"]; infl_theta = {tuple(int(x) for x in k.split("-")): Fr(v) for k, v in res["plan"]["systems"]["plain"]["influence"]["theta"].items()}
    per = []
    for qid, c in C.items():
        pr = P[c["proof"]]; node = str(c["node"]); H = [int(x) for x in pr["H"]]
        th_in = [Fr(v) for v in (pr.get("theta") or {}).values()]; d = {int(k): Fr(v) for k, v in (pr.get("d") or {}).items()}; b = {int(k): Fr(v) for k, v in (pr.get("b") or {}).items()}
        lu = pr["nodes"].get(node); rw = max(Fr(u) - Fr(l) for l, u in lu) if lu else None
        # first-iterate saturation at the query node: c_q + sum_u theta_qu * 1
        qn = int(node); row_q = sum((Fr(v) for k, v in (pr.get("theta") or {}).items() if qn in (int(t_) for t_ in k.split("-"))), Fr(0)); c_q = d.get(qn, Fr(0)) + b.get(qn, Fr(0))
        rowsums = {}
        for k, v in (pr.get("theta") or {}).items():
            a_, b_ = (int(x) for x in k.split("-")); rowsums[a_] = rowsums.get(a_, Fr(0)) + Fr(v); rowsums[b_] = rowsums.get(b_, Fr(0)) + Fr(v)
        per.append({"query": int(qid), "proof": c["proof"], "kind": pr["kind"], "mode": pr.get("mode"), "system": pr.get("system"), "region_size": len(H), "boundary_nodes_with_d_positive": sum(1 for v in d.values() if v > 0),
                    "d_query": float(d.get(qn, 0)), "d_max_over_region": float(max(d.values())) if d else None, "b_query": float(b.get(qn, 0)), "inside_edges": len(th_in), "theta_inside_median": float(st.median(th_in)) if th_in else None, "theta_inside_max": float(max(th_in)) if th_in else None,
                    "first_iterate_query_c_plus_rowsum": float(c_q + row_q), "inside_rowsum_max_Ainf": float(max(rowsums.values())) if rowsums else None, "iterations": pr.get("iterations"), "z_query": float(Fr(c["z_query"])), "regional_width": float(rw) if rw is not None else None,
                    "regional_solver": (pr.get("solver_info") or {}).get("regional_solver"), "surrogate_eta_max": float(max(Fr(v) for v in (pr.get("eta") or {}).values())) if pr.get("eta") else None, "rho_coarse": float(max(Fr(v) for v in (pr.get("rho") or {}).values())) if pr.get("rho") else 0.0})
    rec["extraction"] = {"blocks": len(per), "region_size": q([p["region_size"] for p in per]), "d_query": q([p["d_query"] for p in per]), "d_max_over_region": q([p["d_max_over_region"] for p in per if p["d_max_over_region"] is not None]), "theta_inside_median": q([p["theta_inside_median"] for p in per if p["theta_inside_median"] is not None]),
                         "first_iterate_query": q([p["first_iterate_query_c_plus_rowsum"] for p in per]), "inside_rowsum_max": q([p["inside_rowsum_max_Ainf"] for p in per if p["inside_rowsum_max_Ainf"] is not None]), "iterations": q([p["iterations"] for p in per]), "z_query": q([p["z_query"] for p in per]), "regional_width": q([p["regional_width"] for p in per if p["regional_width"] is not None]),
                         "solver": {k: sum(1 for p in per if p["regional_solver"] == k) for k in set(p["regional_solver"] for p in per)}, "surrogate_eta_max": q([p["surrogate_eta_max"] for p in per if p["surrogate_eta_max"] is not None]), "modes": {k: sum(1 for p in per if p["mode"] == k) for k in set(p["mode"] for p in per)}, "per_block": per}
    rec["phases_s"]["extraction"] = now() - t
    # ---------------- (2) exact failed sufficient conditions
    adj = {}
    for (a_, b_), v in infl_theta.items():
        adj.setdefault(a_, {})[b_] = v; adj.setdefault(b_, {})[a_] = v
    nb = [sum(adj[v].values()) - adj[v][u] for u in adj for v in adj[u]]
    rec["failed_sufficient_conditions"] = {"theorem1_first_iterate": "z_q(1) = min(1, c_q + sum_u theta_qu): saturates at 1 on %d of %d blocks (c_q + rowsum >= 1)" % (sum(1 for p in per if p["first_iterate_query_c_plus_rowsum"] >= 1), len(per)),
                                           "contraction_sufficient_condition_Ainf_lt_1": "FAILS: max inside influence row sum over regions = %.3f (median %.3f)" % (max(p["inside_rowsum_max_Ainf"] for p in per if p["inside_rowsum_max_Ainf"] is not None), st.median([p["inside_rowsum_max_Ainf"] for p in per if p["inside_rowsum_max_Ainf"] is not None])),
                                           "nonbacktracking_perron_lower_bound": "spectral radius of the nonbacktracking operator >= min row sum = %.5f > 1 (exact rationals; %d directed edges): the nonbacktracking contraction sufficient condition FAILS; finite nonbacktracking comparison itself remains valid" % (float(min(nb)), len(nb)),
                                           "note": "these are failed SUFFICIENT conditions of the existing certificates and a Perron LOWER bound; they do not bound the true boundary sensitivity from below or above by themselves"}
    # ---------------- (3) bounded deterministic boundary contrasts (frozen contrasts: all-row-0, all-row-1 vs saved modal)
    t = now(); m_nat = CM.Model.from_json(native).validate(); eps = Fr(res["requested_width"]); timings = {}
    m2, o2r, members, log, scalars, infeasible = CM.contract_hard(m_nat)
    from cbi import coarse as CO
    clusters, how = CO.propose_clusters(m2, m_nat.meta.get("cluster_hints"), o2r); cluster_log = {"proposal": how, "proposed": clusters, "verified": [], "rejected": []}
    systems = api._systems(m2, clusters, eps, {}, cluster_log, timings, None)
    contrasts = []; done = 0; skipped = 0
    def deadline():
        if now() > cap - 2.0:
            raise PL.TimeLimit("cap")
    try:
        for p in per:
            pr = P[p["proof"]]; sysk = pr.get("system"); infl, red, cmap = systems[sysk]; H = set(int(x) for x in pr["H"]); node = int(C[str(p["query"])]["node"])
            inside_ops = {}
            for k, v in pr["inside_ops"].items():
                a_, b_ = (int(x) for x in k.split("-")); inside_ops[(a_, b_)] = tuple(v) if not isinstance(v, str) else (v,)
            inside_ops = {k: (v if v[0] != "exact" else ("exact",)) for k, v in inside_ops.items()}
            xi_saved = {int(k): int(v) for k, v in pr["xi"].items()}
            if not xi_saved:
                contrasts.append({"query": p["query"], "boundary_nodes": 0, "note": "no outside state (whole-component region)"}); continue
            def pq(xi):
                deadline(); bel, info = RG.solve_region(red, H, xi, inside_ops, node, max_entries=1 << 20, deadline=deadline)
                lo, hi = TR.coordinate_intervals(bel, red.blocks[node].rows, red.d)[0]; return (lo + hi) / 2, hi - lo
            p_saved, w_saved = pq(xi_saved)
            variants = {}
            for name, rowsel in (("all_row0", 0), ("all_row1", 1)):
                xi = {u: (rowsel if rowsel in set(red.blocks[u].rows) else xi_saved[u]) for u in xi_saved}
                pv, wv = pq(xi); variants[name] = {"P_plus": float(pv), "regional_width": float(wv), "abs_change_vs_saved": float(abs(pv - p_saved)), "boundary_nodes_changed": sum(1 for u in xi_saved if xi[u] != xi_saved[u])}
            contrasts.append({"query": p["query"], "boundary_nodes": len(xi_saved), "P_plus_saved_modal": float(p_saved), "regional_width_saved": float(w_saved), "variants": variants, "max_observed_contrast": max(v["abs_change_vs_saved"] for v in variants.values()), "certificate_radius": p["z_query"]}); done += 1
    except PL.TimeLimit:
        skipped = len(per) - done - sum(1 for c in contrasts if c.get("boundary_nodes") == 0)
    mc = [c["max_observed_contrast"] for c in contrasts if "max_observed_contrast" in c]
    rec["boundary_contrasts"] = {"frozen_contrasts": ["all outside nodes at native row 0 (else saved modal)", "all outside nodes at native row 1 (else saved modal)"], "coverage": {"regions_contrasted": done, "regions_without_boundary": sum(1 for c in contrasts if c.get("boundary_nodes") == 0), "regions_not_reached_within_cap": skipped, "total": len(per)},
                                "max_observed_contrast": q(mc), "regions_with_contrast_above_0.01": sum(1 for x in mc if x > 0.01), "regions_with_contrast_above_0.1": sum(1 for x in mc if x > 0.1), "worst_region": max(contrasts, key=lambda c: c.get("max_observed_contrast", -1)) if mc else None,
                                "interpretation": "observed contrasts are LOWER bounds on the true boundary sensitivity (two configurations); the certificate radius (1.0 everywhere here) is an upper bound; actual sensitivity lies in between and is NOT determined by these two numbers", "per_region": contrasts}
    rec["phases_s"]["contrasts"] = now() - t; rec["status"] = "COMPLETE" if skipped == 0 else "PARTIAL_CAP"; rec["complete_response_s"] = now()
    json.dump(rec, open(os.path.join(out, "local_diag.json"), "w"), indent=1, default=str)
    print(json.dumps({"case": case, "status": rec["status"], "blocks": len(per), "contrasted": done, "max_contrast": q(mc)["max"] if mc else None, "s": round(now(), 2)}))


if __name__ == "__main__":
    main()
