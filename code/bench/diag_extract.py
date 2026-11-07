"""DIAGNOSTIC EXTRACTION + SCORING (spec of 7 Nov 2026). Builds the linked canonical records from (1) immutable primary artifacts, (2) the census,
(3) the new diagnostic rows, and scores every new output against the SAME references as the primary scorer (old SCORES.json untouched):
  diag_2026-11-07/RECORDS_cases.jsonl        one per intended slot (48): census + dispositions per arm / family
  diag_2026-11-07/RECORDS_invocations.jsonl  one per historical primary / amendment / diagnostic row AND per new diagnostic cell (A..E)
  diag_2026-11-07/RECORDS_queries.jsonl      per (invocation, variable) error / width where a reference or certificate exists (A, C, D, historical)
  diag_2026-11-07/RECORDS_blocks.jsonl       per (admitted CBI case, block) certificate components (E extraction)
  diag_2026-11-07/MISSINGNESS.json           typed reasons for every planned datum not present
  diag_2026-11-07/DATA_DICTIONARY.json       field -> source artifact / computation / extractor version
  diag_2026-11-07/SCORES_DIAG.json           new-output accuracy with original- and expanded-reference denominators separate
    python bench/diag_extract.py SWEEP_DIR"""
from __future__ import annotations
import os, sys, json, math, collections, statistics as st
HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__))); sys.path.insert(0, HERE)
sys.set_int_max_str_digits(0)
from fractions import Fraction as Fr
from ext import uai as U
from bench import score as SC_

VERSION = "diag-extract-2026-11-07-v1"
MISSING = ("measured_zero", "not_applicable", "unavailable_source", "not_instrumented", "not_attempted", "early_termination", "resource_censored", "lost_artifact", "not_run_within_budget")


def load(p, default=None):
    return json.load(open(p)) if os.path.exists(p) else default


def jl(p):
    return [json.loads(l) for l in open(p)] if os.path.exists(p) else []


def hellinger(p, q):
    return math.sqrt(0.5 * sum((math.sqrt(float(a)) - math.sqrt(float(b))) ** 2 for a, b in zip(p, q)))


def transformation_payload(od, plans_dir):
    """The ACTUAL executed transformation of an MDI run, read from the persisted plan record's program (the generic kind/name 'identity' labels
    do not identify it): program.quotient = {fixed, merged, ...} when a quotient was executed; program.support when a compiled support was."""
    import glob
    out = {"plan_files": [], "quotient": None, "support": None, "label": "untransformed dense identity"}
    for pf in sorted(glob.glob(os.path.join(od, plans_dir, "*.plan.json"))):
        d = load(pf) or {}; prog = d.get("program") or {}; out["plan_files"].append(os.path.basename(pf))
        q = prog.get("quotient") if isinstance(prog, dict) else None
        if q:
            out["quotient"] = {"digest": q.get("digest"), "fixed": len(q.get("fixed") or {}), "merged": len(q.get("merged") or {}), "plan_file": os.path.basename(pf)}; out["label"] = "QUOTIENT executed (%d fixed, %d merged)" % (out["quotient"]["fixed"], out["quotient"]["merged"])
        sp = prog.get("support") if isinstance(prog, dict) else None
        if sp:
            out["support"] = {"keys": list(sp.keys())[:8] if isinstance(sp, dict) else str(sp)[:80], "plan_file": os.path.basename(pf)}; out["label"] = "SUPPORT executed"
    return out


def score_vec(points, ref_rows, card, ev):
    """points / ref_rows per variable (Fr); returns per-variable records + summary (max abs error, TV, Hellinger) against a POINT or enclosure reference."""
    per = []; mx = Fr(0); worst = None
    for v, row in enumerate(points):
        if v in ev or ref_rows[v] is None or row is None:
            continue
        ref_mid = [(L + Uu) / 2 for L, Uu in ref_rows[v]]; err = max(max(abs(x - L), abs(x - Uu)) for x, (L, Uu) in zip(row, ref_rows[v]))
        tv = sum(abs(a - b) for a, b in zip(row, ref_mid)) / 2; h = hellinger(row, ref_mid)
        per.append({"var": v, "max_abs_error": float(err), "tv": float(tv), "hellinger": h})
        if err > mx:
            mx = err; worst = v
    if not per:
        return None, []
    return {"max_abs_error": float(mx), "worst_variable": worst, "tv_mean": st.mean(p["tv"] for p in per), "tv_max": max(p["tv"] for p in per), "hellinger_mean": st.mean(p["hellinger"] for p in per), "hellinger_max": max(p["hellinger"] for p in per), "variables": len(per), "target_0.005_met": bool(mx <= Fr(1, 200))}, per


def main(S):
    D = os.path.join(S, "diag_2026-11-07"); inv = {c["case"]: c for c in load(os.path.join(S, "INVENTORY.json"))["cases"]}; man0 = load(os.path.join(S, "CAMPAIGN_MANIFEST.json")); dman = load(os.path.join(D, "DIAG_MANIFEST.json"))
    hist = jl(os.path.join(S, "CELLS_LEDGER.jsonl")); drows = jl(os.path.join(D, "DIAG_CELLS_LEDGER.jsonl")); census = {r["case"]: r for r in jl(os.path.join(D, "CENSUS.jsonl"))}
    old_scores = load(os.path.join(S, "SCORES.json")); rc_old = old_scores["reference_classes"]; mdi_saved = {r["cell_id"]: r for r in load(os.path.join(D, "MDI_INVOCATION_RECORDS_saved.json"))["rows"]}
    base_saved = {r["cell_id"]: r for r in load(os.path.join(D, "BASELINE_INVOCATION_RECORDS_saved.json"))["rows"]}; gates = load(os.path.join(D, "MDI_SELECTOR_GATE_CENSUS_saved.json"), {})
    missing = []
    def miss(where, field, reason, detail=""):
        assert reason in MISSING; missing.append({"where": where, "field": field, "reason": reason, "detail": detail})
    # ---------------- references: ORIGINAL (frozen SCORES) and EXPANDED (plus new D R1 outputs) -- separate
    refs_orig = {}; refs_exp = {}
    for case in sorted({c["case"] for c in man0["cells"]}):
        row = inv[case]; mp = os.path.join(S, row.get("committed_model_path", row["model_path"])); ep = os.path.join(S, row.get("committed_evidence_path", row["evidence_path"])); m = U.read_model(mp); ev = U.read_evidence(ep)
        cls = rc_old[case]["class"]; rows_ref = None
        if cls == "R0":
            d = load(os.path.join(S, "references", case + ".R0.json")); rows_ref = [[[Fr(x), Fr(x)] for x in d["marginals"][str(v)]] if str(v) in d["marginals"] else None for v in range(m.nvars)]
        elif cls in ("R1", "R2"):
            # reproduce the primary scorer's reference choice: EXACT depth then breadth; else exact-by-ibound WMB/IJGP; else official R2
            src = None
            for stage in ("depth", "breadth"):
                c = next((r for r in hist if r["case"] == case and r["arm"] == "EXACT" and r["stage"] == stage and r.get("label") is None and r["status"] == "COMPLETE" and not r.get("censored")), None)
                if c:
                    src = (os.path.join(S, c["out_dir"], "output.MAR"), "EXACT/" + stage); break
            if src is None:
                for arm in ("WMB", "IJGP"):
                    for stage in ("depth", "breadth"):
                        c = next((r for r in hist if r["case"] == case and r["arm"] == arm and r["stage"] == stage and r.get("label") is None and r["status"] == "COMPLETE"), None)
                        if c and (load(os.path.join(S, c["out_dir"], "cell.json")) or {}).get("exact_by_ibound"):
                            src = (os.path.join(S, c["out_dir"], "output.MAR"), arm + "/" + stage); break
                    if src:
                        break
            if src is None and cls == "R2":
                op = os.path.join(S, "sources", "uai14", "sol", case + ".uai.MAR"); src = (op, "official UAI14") if os.path.exists(op) else None
            if src:
                rows_ref = [[[Fr(x), Fr(x)] for x in r_] for r_ in U.read_mar(src[0])[0]]
        refs_orig[case] = {"class": cls, "rows": rows_ref, "card": m.card, "ev": ev, "source": rc_old[case]["source"]}
        refs_exp[case] = dict(refs_orig[case])
    for r in drows:
        if r.get("family_code") == "D" and r.get("status") == "COMPLETE" and not r.get("censored") and refs_orig[r["case"]]["class"] not in ("R0", "R1"):
            p = os.path.join(S, r["out_dir"], "output.MAR")
            if os.path.exists(p):
                refs_exp[r["case"]] = {**refs_exp[r["case"]], "class": "R1", "rows": [[[Fr(x), Fr(x)] for x in r_] for r_ in U.read_mar(p)[0]], "source": "NEW family-D libDAI junction tree (binary64 point; R1, not R0; NOT independent of the EXACT arm)", "new_in_D": True}
    # ---------------- invocation records
    invs = []; queries = []
    def add_inv(kind, r, extra):
        rec = {"record": "invocation", "kind": kind, **{k: r.get(k) for k in ("cell_id", "task_id", "case", "arm", "stage", "family_code", "label", "status", "outcome", "supervisor_wall_s", "complete_response_s", "peak_tree_rss_bytes", "censored", "mem_overshoot_bytes", "code_hash", "mechanism", "single_query_var", "historical_counterpart", "pair", "cap_s", "budget_s", "cpu_s_sampled", "t_first_complete_output_s", "output_bytes")}, **extra}
        invs.append(rec); return rec
    for r in hist:
        kind = "historical_primary" if r.get("label") is None else ("historical_amendment_rerun" if str(r["label"]).startswith("amendment") else "historical_diagnostic")
        extra = {"phases_s": r.get("phases_s"), "reason": r.get("reason"), "failure_primary": r.get("failure_primary"), "mdi": mdi_saved.get(r["cell_id"]), "baseline": base_saved.get(r["cell_id"]), "selector_gate_class": (gates.get("%s|%s" % (r["case"], r["stage"])) or {}).get("class") if r["arm"] == "MDI_EXISTING" else None}
        if r["arm"] == "MDI_EXISTING" and r.get("out_dir") and extra["mdi"] is not None:
            extra["mdi"] = dict(extra["mdi"], executed_transformation=transformation_payload(os.path.join(S, r["out_dir"]), "plans_case_selector"))
        if r["arm"] == "MDI_EXISTING" and not r.get("out_dir"):
            miss(r["cell_id"], "mdi.arm_record", "early_termination", "killed before a record")
        add_inv(kind, r, extra)
    cost_cats = {"CBI_NATIVE": {"load_conversion": ["parse", "convert"], "representation_preprocessing": ["plan"], "discovery_planning": [], "numerical_execution": ["solve"], "independent_checking": ["verify"], "query_restoration_output": ["serialize"], "wrapper_unassigned": ["startup_imports"]},
                 "LBP": {"load_conversion": ["parse", "convert"], "representation_preprocessing": [], "discovery_planning": ["plan"], "numerical_execution": ["solve"], "independent_checking": [], "query_restoration_output": ["serialize"], "wrapper_unassigned": ["startup_imports"]},
                 "EXACT": {"load_conversion": ["parse", "convert"], "representation_preprocessing": [], "discovery_planning": ["plan"], "numerical_execution": ["solve"], "independent_checking": [], "query_restoration_output": ["serialize"], "wrapper_unassigned": ["startup_imports"]},
                 "PGMAX_SUMPRODUCT_BP": {"load_conversion": ["parse", "convert"], "representation_preprocessing": [], "discovery_planning": ["plan"], "numerical_execution": ["solve"], "independent_checking": [], "query_restoration_output": ["serialize"], "wrapper_unassigned": ["startup_imports"]}}
    for r in drows:
        if not r.get("cell_id"):
            add_inv("diagnostic_not_applicable", r, {"reason": r.get("reason")}); continue
        od = os.path.join(S, r["out_dir"]) if r.get("out_dir") else None; fam = r["family_code"]
        extra = {"phases_s": r.get("phases_s"), "reason": r.get("reason"), "last_progress_before_kill": r.get("last_progress_before_kill")}
        if fam in ("A", "C", "D"):
            cj = load(os.path.join(od, "cell.json")) if od else None
            if cj:
                extra.update({"effective_limits": cj.get("effective_limits"), "query_interface": cj.get("query_interface"), "single_query": cj.get("single_query"), "runs": cj.get("runs"), "solver_side": cj.get("solver_side"), "mdi_outcome": cj.get("mdi_outcome"), "route": cj.get("route"), "mdi_stages": cj.get("mdi_stages"), "certified": cj.get("certified"), "verify_accepted": cj.get("verify_accepted"), "adapter_check_accepted": cj.get("adapter_check_accepted"), "adapter": cj.get("adapter"), "statuses_per_block": cj.get("statuses_per_block"), "snapshots": cj.get("snapshots")})
                cats = cost_cats.get(r["arm"]); ph = cj.get("phases_s") or {}
                if cats and ph:
                    extra["cost_categories_s"] = {k: sum(ph.get(x, 0.0) or 0.0 for x in v) for k, v in cats.items()}; extra["cost_categories_s"]["unassigned_residual"] = (cj.get("complete_response_s") or 0) - sum(extra["cost_categories_s"].values())
                elif r["arm"] in ("MDI_EXISTING", "WMB", "IJGP"):
                    extra["cost_categories_s"] = "not separable from the arm's own timers (MDI: pipeline combines discovery / numerics / checking, see mdi_stages; Merlin: per-step walls only)"
                # MDI arm record for A
                ap = os.path.join(od, "arm_case_selector.json")
                if r["arm"] == "MDI_EXISTING" and os.path.exists(ap):
                    a = load(ap); p = a.get("pipeline") or {}; pl = p.get("plan") or {}; sel = pl.get("selector") if isinstance(pl, dict) else None
                    extra["mdi"] = {"outcome": a.get("outcome"), "pipeline_stages_s": p.get("stages"), "route": {"chosen": pl.get("chosen"), "executed_kind": pl.get("executed_kind"), "executed_route": (sel or {}).get("executed_route")}, "selector": ({k: sel.get(k) for k in ("gate", "skipped", "precondition", "dense_candidate", "attempts", "window_s", "selector_wall_s")} if sel else None), "rejected_typed": [(x.get("name"), x.get("typed")) for x in (p.get("rejected") or [])], "executed_ops": (pl.get("executed") or {}).get("ops") if isinstance(pl.get("executed"), dict) else None, "contract_met": a.get("contract_met"),
                                    "executed_transformation": transformation_payload(od, "plans_case_selector")}
            else:
                miss(r["cell_id"], "cell.json", "early_termination" if r["outcome"] in ("TIMEOUT_KILL", "MEMORY_KILL") else "lost_artifact", r["outcome"])
            # scoring of a complete output (A: complete MAR; D: complete MAR; C: single row) against ORIGINAL and EXPANDED references
            mar = os.path.join(od, "output.MAR") if od else None; case = r["case"]
            pts = None
            if mar and os.path.exists(mar) and r.get("status") in ("COMPLETE", "COMPLETE_UNCONVERGED", "CERTIFIED", "VALID_BUT_TOO_WIDE") and not r.get("censored"):
                pts = [[Fr(x) for x in row] for row in U.read_mar(mar)[0]]
            elif fam == "C" and cj and cj.get("single_query"):
                sq = cj["single_query"]; v = sq["var"]
                if sq.get("row"):
                    pts = {v: [Fr(x) for x in sq["row"]]}
                elif sq.get("intervals"):
                    pts = {v: [(Fr(lo) + Fr(hi)) / 2 for lo, hi in sq["intervals"]]}; extra["single_query_width"] = sq.get("max_width")
                elif sq.get("interval_state1"):
                    lo, hi = (Fr(x) for x in sq["interval_state1"]); pts = {v: [1 - (lo + hi) / 2, (lo + hi) / 2]}
            if pts is not None:
                for label, refs in (("original_reference", refs_orig), ("expanded_reference", refs_exp)):
                    ref = refs[case]
                    if ref["rows"] is None:
                        extra["accuracy_" + label] = {"class": ref["class"], "point_quality": "UNKNOWN (no qualified reference)"}; continue
                    if isinstance(pts, dict):
                        rows_pts = [pts.get(v) for v in range(len(ref["card"]))]
                    else:
                        rows_pts = pts
                    if r["arm"] == "EXACT" and ref.get("source", "").startswith("libDAI") or (r["arm"] == "EXACT" and "EXACT" in str(ref.get("source"))):
                        extra["accuracy_" + label] = {"class": ref["class"], "note": "self-comparison: the reference is this arm's own algorithm; not independent validation", "independent": False}
                    summ, per = score_vec(rows_pts, ref["rows"], ref["card"], ref["ev"])
                    if summ:
                        extra["accuracy_" + label] = {**extra.get("accuracy_" + label, {}), "class": ref["class"], **summ, "independent_of_arm": not (r["arm"] == "EXACT" and "junction tree" in str(ref.get("source")).lower())}
                        for q_ in per:
                            queries.append({"record": "query", "cell_id": r["cell_id"], "case": case, "arm": r["arm"], "family_code": fam, "reference": label, "class": ref["class"], **q_})
                    else:
                        extra["accuracy_" + label] = {"class": ref["class"], "point_quality": "no scorable row (variable observed or missing)"}
            elif r.get("status") in ("COMPLETE", "CERTIFIED", "VALID_BUT_TOO_WIDE") and fam in ("A", "D"):
                miss(r["cell_id"], "output.MAR", "lost_artifact", "status complete but no output file")
        elif fam == "B":
            pj = load(os.path.join(od, "probe.json")) if od else None
            if pj:
                extra.update({"probe_status": pj.get("status"), "structural": pj.get("structural"), "execution": pj.get("execution"), "gates_intervened": pj.get("gates_intervened"), "gates_remaining": pj.get("gates_remaining"), "sizes": pj.get("sizes"), "probe_phases_s": pj.get("phases_s")})
                extra["executed_transformation"] = transformation_payload(od, "plans_probe_%s" % r.get("mechanism"))
                ap = os.path.join(od, "arm_probe_%s.json" % r.get("mechanism"))
                if os.path.exists(ap):                                   # the EXECUTION phase's engine record: pipeline stage timers, executed ops, refusals
                    a = load(ap); p = a.get("pipeline") or {}; pl = p.get("plan") or {}
                    extra["execution_engine"] = {"outcome": a.get("outcome"), "pipeline_stages_s": p.get("stages"), "arm_stages_s": a.get("stages"), "executed_ops": (pl.get("executed") or {}).get("ops") if isinstance(pl.get("executed"), dict) else None, "executed_kind": pl.get("executed_kind"), "route_policy": pl.get("route_policy"),
                                                 "rejected": [(x.get("name"), x.get("typed"), str(x.get("reason"))[:160]) for x in (p.get("rejected") or [])], "contract_met": a.get("contract_met"), "final_max_width": a.get("final_max_width"), "peak_rss_bytes": a.get("peak_rss_bytes"), "independently_verified": a.get("independently_verified")}
            else:
                miss(r["cell_id"], "probe.json", "early_termination" if r["outcome"] in ("TIMEOUT_KILL", "MEMORY_KILL") else "lost_artifact", r["outcome"])
        elif fam == "E":
            lj = load(os.path.join(od, "local_diag.json")) if od else None
            if lj:
                extra.update({"extraction_summary": {k: v for k, v in (lj.get("extraction") or {}).items() if k != "per_block"}, "failed_sufficient_conditions": lj.get("failed_sufficient_conditions"), "boundary_contrasts_summary": {k: v for k, v in (lj.get("boundary_contrasts") or {}).items() if k != "per_region"}, "saved_artifact": lj.get("saved_artifact")})
                for p in (lj.get("extraction") or {}).get("per_block", []):
                    # join with the contrast of the same query
                    con = next((c for c in (lj.get("boundary_contrasts") or {}).get("per_region", []) if c.get("query") == p["query"]), {})
                    queries.append({"record": "block", "cell_id": r["cell_id"], "case": r["case"], **p, "boundary_nodes": con.get("boundary_nodes"), "max_observed_contrast": con.get("max_observed_contrast"), "P_plus_saved_modal": con.get("P_plus_saved_modal")})
            else:
                miss(r["cell_id"], "local_diag.json", "early_termination" if r["outcome"] in ("TIMEOUT_KILL", "MEMORY_KILL") else "lost_artifact", r["outcome"])
        # RECONCILED status label (reporting only; the wrapper's label is kept in `status`): the MDI arm wrapper maps the engine's
        # NUMERICAL_REFUSAL (exact preprocessing refused above the locally verifiable cap) to CHECK_FAILED on the complete-task path
        extra["status_reconciled"] = r.get("status")
        if r["arm"] == "MDI_EXISTING" and r.get("status") == "CHECK_FAILED":
            mo = (extra.get("mdi") or {}).get("outcome") or (extra.get("mdi_outcome"))
            if mo == "NUMERICAL_REFUSAL":
                extra["status_reconciled"] = "ENGINE_REFUSED_PREPROCESSING"
        add_inv("diagnostic_" + fam, r, extra)
    for rec in invs:
        if rec["kind"] == "historical_primary" and rec["arm"] == "MDI_EXISTING" and rec.get("status") == "CHECK_FAILED" and ((rec.get("mdi") or {}).get("outcome") == "NUMERICAL_REFUSAL"):
            rec["status_reconciled"] = "ENGINE_REFUSED_PREPROCESSING"
        rec.setdefault("status_reconciled", rec.get("status"))
    # ---------------- planned-but-absent cells of the diagnostic manifest
    have = {r.get("cell_id") for r in drows if r.get("cell_id")}
    for c in dman["cells"]:
        if c.get("cell_id") and c["cell_id"] not in have:
            miss(c["cell_id"], "diagnostic cell %s %s %s" % (c["family_code"], c["case"], c["arm"]), "not_run_within_budget", "no row in DIAG_CELLS_LEDGER")
    for r in drows:
        if r.get("outcome") == "NOT_RUN_BUDGET":
            miss(r.get("cell_id"), "diagnostic cell", "not_run_within_budget", r.get("reason", ""))
        if r.get("outcome") in ("TIMEOUT_KILL", "MEMORY_KILL"):
            miss(r.get("cell_id"), "complete output", "resource_censored", r["outcome"])
    # historical lost artifacts
    fp = load(os.path.join(S, "DIAGNOSTICS_FIRST_PASS_ROWS.json"))
    if fp:
        for x in fp["rows"]:
            miss(x["cell_id"], "first-pass diagnostic numerical artifacts (%s)" % x["label"], "lost_artifact", "overwritten by the second pass (amendment 3); ledger receipt retained")
    # phase names never measured historically
    for r in hist:
        if r.get("label") is None and r["arm"] in ("WMB", "IJGP") and r.get("phases_s") and "solve" not in (r.get("phases_s") or {}):
            miss(r["cell_id"], "phase split (parse / plan / solve) for Merlin ladders", "not_instrumented", "Merlin exposes per-step walls only")
    # ---------------- case records with dispositions
    cases_out = []
    for c in jl(os.path.join(D, "CENSUS.jsonl")):
        case = c["case"]; rec = {"record": "case", **{k: c.get(k) for k in ("case", "family", "accessible", "anchor", "variables", "evidence_count", "unobserved_variables", "domain_histogram", "net_type", "reason")}, "census": ({k: c.get(k) for k in ("original", "sliced", "sliced_plus_forced", "graph_sliced_plus_forced", "forced_states", "relations_mdi_quotient", "cbi_obstructions", "costs_s")} if c["accessible"] else None)}
        if c["accessible"]:
            disp = {}
            for arm in man0["arms"]:
                b = next((r for r in hist if r["case"] == case and r["arm"] == arm and r["stage"] == "breadth" and r.get("label") is None), None); d_ = next((r for r in hist if r["case"] == case and r["arm"] == arm and r["stage"] == "depth" and r.get("label") is None), None)
                A_ = next((r for r in drows if r.get("case") == case and r.get("arm") == arm and r.get("family_code") == "A"), None); C_ = next((r for r in drows if r.get("case") == case and r.get("arm") == arm and r.get("family_code") == "C"), None)
                disp[arm] = {"breadth": (b or {}).get("status"), "depth": (d_ or {}).get("status", "not scheduled for depth"), "A": (A_ or {}).get("status", "not run"), "C": (C_ or {}).get("status", "not run")}
            disp["B"] = {m_: (next((r for r in drows if r.get("case") == case and r.get("family_code") == "B" and r.get("mechanism") == m_), None) or {}).get("status", "not run") for m_ in ("quotient", "support")}
            disp["D"] = (next((r for r in drows if r.get("case") == case and r.get("family_code") == "D"), None) or {}).get("status", "not scheduled (R0/R1 existed)" if rc_old.get(case, {}).get("class") in ("R0", "R1") else "not run")
            disp["E"] = (next((r for r in drows if r.get("case") == case and r.get("family_code") == "E"), None) or {}).get("status", "not applicable (not CBI-admitted)")
            rec["dispositions"] = disp; rec["reference_class_original"] = rc_old.get(case, {}).get("class"); rec["reference_class_expanded"] = refs_exp[case]["class"]
        cases_out.append(rec)
    with open(os.path.join(D, "RECORDS_cases.jsonl"), "w") as f:
        for x in cases_out:
            f.write(json.dumps(x, default=str) + "\n")
    with open(os.path.join(D, "RECORDS_invocations.jsonl"), "w") as f:
        for x in invs:
            f.write(json.dumps(x, default=str) + "\n")
    with open(os.path.join(D, "RECORDS_queries.jsonl"), "w") as f:
        for x in queries:
            f.write(json.dumps(x, default=str) + "\n")
    with open(os.path.join(D, "RECORDS_blocks.jsonl"), "w") as f:
        for x in queries:
            if x["record"] == "block":
                f.write(json.dumps(x, default=str) + "\n")
    json.dump({"typed_reasons": MISSING, "count": len(missing), "by_reason": dict(collections.Counter(m_["reason"] for m_ in missing)), "items": missing}, open(os.path.join(D, "MISSINGNESS.json"), "w"), indent=1)
    # scores for the new families with both denominators
    sd = {"version": VERSION, "note": "new diagnostic outputs scored against the ORIGINAL references (frozen SCORES.json classes) and the EXPANDED references (plus new family-D R1 outputs); old SCORES.json untouched; EXACT scored against its own algorithm is marked non-independent",
          "reference_classes_original": dict(collections.Counter(v["class"] for v in refs_orig.values())), "reference_classes_expanded": dict(collections.Counter(v["class"] for v in refs_exp.values())), "new_R1_from_D": sorted(c for c, v in refs_exp.items() if v.get("new_in_D")),
          "rows": [{k: x.get(k) for k in ("cell_id", "case", "arm", "family_code", "status", "complete_response_s", "accuracy_original_reference", "accuracy_expanded_reference", "single_query_var", "single_query_width", "certified")} for x in invs if x["kind"] in ("diagnostic_A", "diagnostic_C", "diagnostic_D")]}
    json.dump(sd, open(os.path.join(D, "SCORES_DIAG.json"), "w"), indent=1, default=str)
    dd = {"version": VERSION, "records": {"case": "RECORDS_cases.jsonl: census fields (bench/census.py; CENSUS_SCHEMA.json) + per-arm dispositions from CELLS_LEDGER (historical) and DIAG_CELLS_LEDGER (new)",
                                           "invocation": "RECORDS_invocations.jsonl: every ledger row; historical rows carry phases_s from cells.py, mdi (MDI_INVOCATION_RECORDS_saved: arm_case_selector.json fields), baseline (BASELINE_INVOCATION_RECORDS_saved: cell.json solver_side / runs), selector_gate_class; new rows carry cell.json / probe.json / local_diag.json fields, cost_categories_s (non-overlapping mapping of the arm's own phase timers; unassigned_residual = complete_response - mapped), accuracy_* (score_vec)",
                                           "query": "RECORDS_queries.jsonl: per (invocation, variable) max |error|, TV, Hellinger vs the reference point / enclosure (original and expanded)", "block": "RECORDS_blocks.jsonl: family-E per-block certificate components joined with the boundary contrast of the same query"},
          "cost_categories": {"load_conversion": "parse + convert timers", "representation_preprocessing": "CBI plan (validation + reductions + systems)", "discovery_planning": "libDAI / PGMax construction (plan)", "numerical_execution": "solve", "independent_checking": "CBI verify", "query_restoration_output": "serialize (CBI: incl. adapter check)", "wrapper_unassigned": "startup_imports", "unassigned_residual": "complete_response - sum of mapped"},
          "typed_missing": MISSING, "timing_boundaries": "complete_response_s: cells.py T_START (after interpreter start) to after output serialization, before cell metadata; supervisor_wall_s: spawn-to-reap of the whole process tree (the receipt); phases: the arm's own timer names (original names preserved in phases_s / mdi_stages / solver_side)",
          "references": {"original": "frozen SCORES.json classes and sources", "expanded": "original + family-D new libDAI outputs as R1 (not independent of the EXACT arm; never R0)"}}
    json.dump(dd, open(os.path.join(D, "DATA_DICTIONARY.json"), "w"), indent=1)
    print("cases", len(cases_out), "invocations", len(invs), "queries", sum(1 for q in queries if q["record"] == "query"), "blocks", sum(1 for q in queries if q["record"] == "block"), "missing items", len(missing), dict(collections.Counter(m_["reason"] for m_ in missing)))


if __name__ == "__main__":
    main(os.path.abspath(sys.argv[1]))
