"""Bounded diagnostics (spec section 9), predeclared in CAMPAIGN_MANIFEST.diagnostic_rules; run only after all primary cells are terminal.
  A. width probes 1/50 and 1/500 (20 s caps) + a rooted single-query probe, on the first two CBI-admitted depth cases in manifest order
     (reserve 240 s). Single-query variable = unobserved original variable minimizing SHA256(case-content-hash, variable-id).
  B. two extra repetitions of at most two case/arm comparisons (120 s) on the first two depth cases in manifest order where CBI_NATIVE and an
     external arm both produced full outputs; external arm by priority PGMAX_SUMPRODUCT_BP, SAMPLESEARCH, IJGP, WMB, LBP, EXACT; else the same
     rule for MDI_EXISTING, labelled separately (max 960 s).
    python bench/diagnostics.py SWEEP_DIR"""
import os, sys, json, hashlib
HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__))); sys.path.insert(0, HERE)
from bench import campaign as C
PRIORITY = ["PGMAX_SUMPRODUCT_BP", "SAMPLESEARCH", "IJGP", "WMB", "LBP", "EXACT"]


def main(S):
    man = json.load(open(os.path.join(S, "CAMPAIGN_MANIFEST.json"))); rows = C.ledger_rows(S); inv = {c["case"]: c for c in json.load(open(os.path.join(S, "INVENTORY.json")))["cases"]}
    depth_order = []
    for c in man["cells"]:
        if c["stage"] == "depth" and c["case"] not in depth_order:
            depth_order.append(c["case"])
    st = {(r["case"], r["arm"]): r for r in rows if r["stage"] == "depth" and r.get("label") is None}
    admitted = [c for c in depth_order if st.get((c, "CBI_NATIVE"), {}).get("status") in ("CERTIFIED", "VALID_BUT_TOO_WIDE")][:2]
    log = {"A_width_probes_cases": admitted, "B_repetitions": [], "notes": []}
    spentA = 0.0
    if not admitted:
        log["notes"].append("no external case was admitted by the native CBI adapter in the depth stage: width / rooted probes not applicable to external cases; the repair is validated by the saved forest controls (REPLAY4) only, which are NOT added to the external score")
    for case in admitted:
        cell = next(c for c in man["cells"] if c["stage"] == "depth" and c["case"] == case and c["arm"] == "CBI_NATIVE")
        for w in ("1/50", "1/500"):
            if spentA + 24 > 240:
                break
            cfgp = os.path.join(S, "CONFIG_width_%s.json" % w.replace("/", "_")); json.dump({**man["config"], "width": w}, open(cfgp, "w"))
            r = C.run_cell(S, {**cell, "stage": "diag"}, cfgp, "diag", label_extra="width_probe_%s" % w, deadline=20.0); spentA += r["supervisor_wall_s"]; log.setdefault("A_rows", []).append({k: r.get(k) for k in ("case", "label", "status", "supervisor_wall_s", "out_dir")})
        # rooted single-query probe: variable = argmin SHA256(case-content-hash, var-id) over unobserved variables
        row = inv[case]; from ext import uai as U
        m = U.read_model(os.path.join(S, row.get("committed_model_path", row["model_path"]))); ev = U.read_evidence(os.path.join(S, row.get("committed_evidence_path", row["evidence_path"])))
        free = [v for v in range(m.nvars) if v not in ev]; var = min(free, key=lambda v: hashlib.sha256(("%s|%d" % (row["canonical_model_sha256"], v)).encode()).hexdigest())
        cfgp = os.path.join(S, "CONFIG_single_%s.json" % case); json.dump({**man["config"], "single_query_var": var}, open(cfgp, "w"))
        if spentA + 24 <= 240:
            r = C.run_cell(S, {**cell, "stage": "diag"}, cfgp, "diag", label_extra="rooted_single_query_var%d" % var, deadline=20.0); spentA += r["supervisor_wall_s"]; log.setdefault("A_rows", []).append({k: r.get(k) for k in ("case", "label", "status", "supervisor_wall_s", "out_dir")})
    # B
    full = lambda r: r is not None and r.get("status") in ("CERTIFIED", "VALID_BUT_TOO_WIDE", "COMPLETE", "COMPLETE_UNCONVERGED") and not r.get("censored")
    pairs = []
    for case in depth_order:
        if not full(st.get((case, "CBI_NATIVE"))):
            continue
        ext = next((a for a in PRIORITY if full(st.get((case, a)))), None)
        if ext:
            pairs.append((case, "CBI_NATIVE", ext))
        if len(pairs) == 2:
            break
    subset = "conditional_repetition_subset_CBI"
    if not pairs:
        subset = "conditional_repetition_subset_MDI"; log["notes"].append("no depth case has full CBI_NATIVE and external outputs; the same rule is applied to MDI_EXISTING (labelled separately)")
        for case in depth_order:
            if not full(st.get((case, "MDI_EXISTING"))):
                continue
            ext = next((a for a in PRIORITY if full(st.get((case, a)))), None)
            if ext:
                pairs.append((case, "MDI_EXISTING", ext))
            if len(pairs) == 2:
                break
    spentB = 0.0; cfgp = os.path.join(S, "CONFIG.json")
    for case, ours, ext in pairs:
        for rep in (1, 2):
            for arm in (ours, ext):
                if spentB + 124 > 960:
                    log["notes"].append("repetition budget exhausted before %s %s rep %d" % (case, arm, rep)); break
                cell = next(c for c in man["cells"] if c["stage"] == "depth" and c["case"] == case and c["arm"] == arm)
                r = C.run_cell(S, {**cell, "stage": "diag"}, cfgp, "diag", label_extra="%s_rep%d" % (subset, rep), deadline=120.0); spentB += r["supervisor_wall_s"]
                log["B_repetitions"].append({k: r.get(k) for k in ("case", "arm", "label", "status", "supervisor_wall_s", "complete_response_s", "peak_tree_rss_bytes", "out_dir")})
    log["spent_s"] = {"A": spentA, "B": spentB}; json.dump(log, open(os.path.join(S, "DIAGNOSTICS.json"), "w"), indent=1); print(json.dumps({k: v for k, v in log.items() if k != "A_rows"}, indent=1, default=str)[:3000])


if __name__ == "__main__":
    main(os.path.abspath(sys.argv[1]))
