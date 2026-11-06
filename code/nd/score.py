"""Scoring from saved artifacts only (candidates sealed before the references): per candidate the mask, certificate, checker,
retained law, transfer and target outcomes; per lambda the dense reference (exact Z when certified) and D = Z - R, delta = D/Z,
U/D; containment of the true marginals in the published intervals where a reference exists; the prospective selection rule
reconstructed from the saved traces (labelled a reconstruction); complete charged costs from the allowance ledger."""
import os, sys, json
HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)
from fractions import Fraction as Fr
E = os.path.join(HERE, "runs/mdi_2026-10-28/ND_CERTIFICATE_2026-11-05")
LAMBDAS = ["1e-6", "1e-4", "1e-2", "1"]; GAPS = ["G100", "G10000"]
TARGETS = [Fr(1, 100), Fr(1, 50), Fr(1, 20)]
gen = json.load(open(os.path.join(E, "GENERATION.json")))
zero_loc = {int(k): set(v) for k, v in gen["zero_locations"].items()}            # generator annotation: scoring / explanation ONLY
led = json.load(open(os.path.join(E, "ALLOWANCE_LEDGER.json")))


def fl(x, nd=6):
    return None if x is None else float(x)


refs = {}
for lam in LAMBDAS:
    prob = "Promedus_12_L%s" % lam; d = os.path.join(E, "references", prob)
    rec = json.load(open(os.path.join(d, "attempt_1", "arm_%s_baseline.json" % prob)))
    sup = json.load(open(os.path.join(d, "supervisor_receipt.json")))
    zt = (rec.get("pipeline") or {}).get("checker", {}).get("exact_total")
    refs[lam] = {"status": rec["outcome"], "reason": str(rec.get("reason"))[:400], "supervisor_wall_s": sup["elapsed_s"], "supervisor_outcome": sup["outcome"],
                 "arm_elapsed_s": rec.get("elapsed_s"), "peak_tree_rss_kib": sup["peak_tree_rss_kib"], "arm_high_water_bytes": rec.get("peak_rss_bytes"),
                 "stages": (rec.get("pipeline") or {}).get("stages"), "preprocess": {k: (v if not isinstance(v, list) else len(v)) for k, v in ((rec.get("pipeline") or {}).get("preprocess") or {}).items()},
                 "Z_exact": (zt or {}).get("Z_original_units"), "counts": (zt or {}).get("counts_original_units"), "final_max_width": rec.get("final_max_width"),
                 "rejected": [(x.get("typed"), str(x.get("reason"))[:300]) for x in ((rec.get("pipeline") or {}).get("rejected") or [])]}
rows = []
run = json.load(open(os.path.join(E, "CANDIDATES_RUN.json")))
for r in run["order"]:
    lam, g, lab = r["lambda"], r["gap"], r["label"]; d = os.path.join(E, "candidates", lab)
    row = {"label": lab, "lambda": lam, "gap": g}
    if not r.get("launched"):
        row.update({"status": "IDENTICAL_MASK_NOT_RECOMPUTED", "identical_to": r["identical_mask_to"]}); rows.append(row); continue
    c = json.load(open(os.path.join(d, "candidate.json"))); sup = json.load(open(os.path.join(d, "supervisor_receipt.json")))
    mk = json.load(open(os.path.join(d, "mask.json")))
    rem_orig_zero = sum(1 for x in mk for i in x["removed"] if i in zero_loc.get(x["origin"], set())) if lam != "1" else None
    # (orig_positions are needed to map restricted indices to original; the 3 observed variables make them differ for 3 factors only; approximate by restricted index == original index where the factor has no observed variable)
    occ_free = {}
    row.update({"status": c["status"], "reason": str(c.get("reason", ""))[:300], "supervisor_wall_s": sup["elapsed_s"], "supervisor_outcome": sup["outcome"], "returncode": sup["returncode"],
                "peak_tree_rss_kib": sup["peak_tree_rss_kib"], "child_high_water_bytes": c.get("child_high_water_rss_bytes"), "steps_s": c.get("steps"),
                "mask": {"occurrences_with_removals": c["mask"]["occurrences_with_removals"], "removed_entries": c["mask"]["removed_entries"], "restricted_entries": c["mask"]["restricted_entries"], "digest": c["mask"]["digest"][:16]}})
    ce = c.get("certificate"); 
    if ce:
        V, U = Fr(ce["V"]), Fr(ce["U"])
        row["certificate"] = {"V": ce["V"], "U": ce["U"], "U_over_V": fl(U / V) if V > 0 else None, "rho_lower_bound_U_over_V_plus_U": fl(U / (V + U)) if V + U > 0 else None,
                              "split_buckets": ce["stats"]["split_buckets"], "groups": ce["stats"]["groups"], "pair_products": ce["stats"]["pair_products"], "pair_additions": ce["stats"]["pair_additions"],
                              "max_union_entries": ce["stats"]["max_union_entries"], "max_bits": ce["stats"]["max_bits"], "C_bits": ce["C_bits"], "K": ce["K"], "producer_wall_s": c["steps"].get("certificate_s"),
                              "checker_status": (c.get("certificate_check") or {}).get("status"), "checker_wall_s": c["steps"].get("certificate_check_s")}
    rt = c.get("retained") or {}
    row["retained"] = {"status": rt.get("status"), "route": rt.get("route"), "R_exact": rt.get("R"), "support_price": {k: rt.get("support_price", {}).get(k) for k in ("reduction_ratio", "admitted", "dense_enumerated_schedule_rows")} if rt.get("support_price") else None,
                       "stages": rt.get("stages"), "rejected_typed": rt.get("rejected_typed"), "executed_ops": (rt.get("executed") or {}).get("ops"), "refusal_reason": str(rt.get("reason", ""))[:300]}
    ref = refs[lam]
    if ce and rt.get("R") is not None and ref.get("Z_exact"):
        R, Z = Fr(rt["R"]), Fr(ref["Z_exact"]); D = Z - R
        row["truth"] = {"Z": ref["Z_exact"], "D_exact": str(D), "delta_D_over_Z": fl(D / Z), "rho": fl(U / (R + U)), "U_over_D": fl(U / D) if D > 0 else None, "V_over_R": fl(V / R), "R_le_Z": bool(R <= Z)}
        # containment of the TRUE marginals in the published (outward) intervals and the exact transferred ones
        pub = json.load(open(os.path.join(d, "published_intervals_outward.json"))); exact = json.load(open(os.path.join(d, "transferred_intervals_exact.json")))
        counts = ref["counts"]; fails_pub = fails_ex = 0; n = 0
        ev = {}
        for v in pub:
            for a in range(len(pub[v])):
                key = "%s:%d" % (v, a)
                if key not in counts:
                    continue                                        # observed variables are not in the free counts
                t = Fr(counts[key]) / Z; n += 1
                lo, hi = Fr(pub[v][a][0]), Fr(pub[v][a][1]); fails_pub += 0 if lo <= t <= hi else 1
                lo, hi = Fr(exact[v][a][0]), Fr(exact[v][a][1]); fails_ex += 0 if lo <= t <= hi else 1
        row["truth"]["containment"] = {"coordinates": n, "published_outward_failures": fails_pub, "exact_transferred_failures": fails_ex}
    elif ce and rt.get("R") is not None:
        row["truth"] = {"Z": None, "note": "no exact reference (dense reference refused): D/Z, U/D and the containment check are UNAVAILABLE", "rho": fl(U / (Fr(rt["R"]) + U))}
    else:
        row["truth"] = {"Z": ref.get("Z_exact"), "note": "no retained R (retained solve refused): rho is UNAVAILABLE; only the lower bound U/(V+U) is known"}
    tr = c.get("transfer")
    if tr:
        row["transfer"] = {"rho": fl(Fr(tr["rho"])), "worst_numerical_width": fl(Fr(tr["worst_numerical_width"])), "worst_transferred_width_exact": fl(Fr(tr["worst_transferred_width_exact"])),
                           "worst_published_width_outward": fl(Fr(tr["worst_published_width_outward_rounded"])), "targets": {k: v["met_on_outward_rounded_endpoints"] for k, v in tr["targets"].items()},
                           "rule_(eps-w)/(1-w)_satisfied": {k: v["rule_satisfied"] for k, v in tr["targets"].items()}}
    rows.append(row)
# ---- selection rule reconstruction (G100 first, G10000 second, else refusal), per lambda and target
sel = {}
for lam in LAMBDAS:
    sel[lam] = {}
    for t in TARGETS:
        path = []; chosen = None; cost = 0.0
        for g in ["G100", "G10000"]:
            rw = next(x for x in rows if x["lambda"] == lam and x["gap"] == g)
            if rw["status"] == "IDENTICAL_MASK_NOT_RECOMPUTED":
                rw = next(x for x in rows if x["label"] == rw["identical_to"])
            cost += rw.get("supervisor_wall_s") or 0.0
            met = bool(rw.get("transfer", {}).get("targets", {}).get(str(t), False)) if rw.get("transfer") else False
            path.append({"gap": g, "status": rw["status"], "met_target": met, "charged_s": rw.get("supervisor_wall_s")})
            if met:
                chosen = g; break
        sel[lam][str(t)] = {"path": path, "selected": chosen or "REFUSAL_TO_EXISTING_FALLBACK", "paid_candidate_walls_s": round(cost, 6),
                            "note": "RECONSTRUCTED from separate diagnostic traces (each candidate's complete supervised child wall); not a measured end-to-end adaptive run; the fallback's own cost is the dense reference row (refused for lambda <= 1e-2)"}
charges = [c for c in led["charges"] if c.get("status") == "TERMINAL"]
out = {"candidates": rows, "references": refs, "selection_rule_reconstruction": sel,
       "allowance": {"allowance_s": led["allowance_s"], "charged_s": sum(c["charged_s"] for c in charges), "children": len(charges), "unknown_charges": led.get("unknown_charges"), "refused_launches": led.get("refused_launches"),
                     "by_kind": {k: round(sum(c["charged_s"] for c in charges if c["kind"] == k), 6) for k in ("control", "candidate", "reference")}}}
json.dump(out, open(os.path.join(E, "SCORES.json"), "w"), indent=1, default=str)
print(json.dumps({"allowance": out["allowance"], "selection": {lam: {t: v["selected"] for t, v in s.items()} for lam, s in sel.items()}}, indent=1))
for rw in rows:
    print(rw["label"], rw["status"], "| cert U/V", (rw.get("certificate") or {}).get("U_over_V"), "rho_lb", (rw.get("certificate") or {}).get("rho_lower_bound_U_over_V_plus_U"), "| truth", {k: v for k, v in (rw.get("truth") or {}).items() if k in ("delta_D_over_Z", "rho", "U_over_D", "V_over_R", "containment")})
