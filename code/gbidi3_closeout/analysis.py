"""READ-ONLY analysis of the GENERAL_BIDI_COMPLETE_V3 414-cell matrix (authorization of 10 Nov 2026; brief §19-§22; the fixed INSPECTION_SCHEMA.json and the
pre-outcome REFERENCE_SNAPSHOT.json). Separate from the frozen inference code: this module only reads saved artifacts (the frozen manifest, the cumulative
ledger, cell records, checked records, interval files, delivered .MAR files, the frozen reference sources) and writes ANALYSIS/*. It never launches inference,
never fills a missing counter, never promotes a new output into a reference tier. Every number carries its denominator and its censoring type.
    python -m gbidi3_closeout.analysis D
Outputs (D/ANALYSIS/): CELLS_LEDGER.jsonl (414 reconciled rows through the ONE strict reconciler), COMPLETENESS.json, REFERENCES_RESOLVED.json (the frozen
snapshot's reference rows resolved to files + hashes BEFORE scoring), SCORES.jsonl (per cell), CASES.jsonl (48), COMPARISONS.json (GENERAL vs PLAIN primary;
vs ADP; vs libDAI; ablations), MECHANISMS.jsonl (per GENERAL cell: offered / accepted / reached / no-op / declined / unknown; planned vs actual work),
FAILURES.json, GRAVEYARD.json, EXPLANATIONS.jsonl (supported / suggestive / unresolved), BUDGET_FINAL.json, EXTRACTION_RECORD.json (source hashes), REPORT_MATRIX.md."""
from __future__ import annotations
import os, sys, json, math, time, hashlib, collections
HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__))); sys.path.insert(0, HERE); sys.set_int_max_str_digits(0)
from fractions import Fraction as Fr
from ext import uai as U
from gbidi3 import reconcile as RC, pilot as PI
OLD = os.path.join(HERE, "runs", "mdi_2026-10-28", "EXTERNAL_SWEEP_2026-11-06"); ADP = os.path.join(HERE, "runs", "mdi_2026-10-28", "AGGREGATE_DP_2026-11-07")
NEW = ("GENERAL_BIDI_COMPLETE_V3", "NATIVE_PLAIN_COMPLETE_V3", "A1_NO_DEMAND_MASKS", "A2_NO_FUSION", "A3_NO_RESPONSE_VIEWS"); ABL = ("A1_NO_DEMAND_MASKS", "A2_NO_FUSION", "A3_NO_RESPONSE_VIEWS")
SUCCESS = {"GENERAL_BIDI_COMPLETE_V3": {"CERTIFIED"}, "NATIVE_PLAIN_COMPLETE_V3": {"CERTIFIED"}, "A1_NO_DEMAND_MASKS": {"CERTIFIED"}, "A2_NO_FUSION": {"CERTIFIED"}, "A3_NO_RESPONSE_VIEWS": {"CERTIFIED"}, "ADP_REPAIRED": {"CERTIFIED"}, "EXACT_LIBDAI": {"COMPLETE"}}
GUARANTEE = {"GENERAL_BIDI_COMPLETE_V3": "certified intervals (eps 1/200, delivered width <= 1/100, exact task binding, separate point verification)", "NATIVE_PLAIN_COMPLETE_V3": "same certified contract (no planner mechanisms)", "A1_NO_DEMAND_MASKS": "same certified contract (ablation)", "A2_NO_FUSION": "same certified contract (ablation)", "A3_NO_RESPONSE_VIEWS": "same certified contract (ablation)",
             "ADP_REPAIRED": "certified intervals under the pinned AGGREGATE_DP_V1 checker (different schedule, substrate and protocol)", "EXACT_LIBDAI": "UNCERTIFIED binary64 point (libDAI JTREE COMPLETE under its own qualified adapter contract)"}


def sha(p):
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for ch in iter(lambda: f.read(1 << 20), b""):
            h.update(ch)
    return h.hexdigest()


def jl(p):
    return [json.loads(l) for l in open(p)] if os.path.exists(p) else []


def load(p):
    return json.load(open(p)) if os.path.exists(p) else None


def read_points(path):
    rows, _ = U.read_mar(path); return [[Fr(x) for x in r] for r in rows]


def fnum(x):
    return None if x is None else float(x)


# ---------------------------------------------------------------------------------------------------------------- references (frozen BEFORE scoring)
def resolve_references(D, man):
    """resolve the pre-outcome REFERENCE_SNAPSHOT.json (class + source per case) to concrete rows from the SAME historical sources the snapshot names
    (adp/closeout/score.py's rules); this campaign's outputs are NEVER promoted into a tier. Returns {case: {class, source, rows|None, ev, file, sha256}}."""
    snap = load(os.path.join(D, "REFERENCE_SNAPSHOT.json")); inv = {c["case"]: c for c in json.load(open(os.path.join(OLD, "INVENTORY.json")))["cases"]}
    old_rows = jl(os.path.join(OLD, "CELLS_LEDGER.jsonl")); adp_rows = jl(os.path.join(ADP, "CELLS_LEDGER.jsonl")); out = {}
    for case, cs in man["cases"].items():
        m = U.read_model(os.path.join(HERE, cs["model_path"])); ev = U.read_evidence(os.path.join(HERE, cs["evidence_path"])); pc = snap["per_case"].get(case, {"class": "R3", "source": "no qualified reference"}); src = pc["source"]; f = None; rows = None
        try:
            if pc["class"] == "R0":
                f = os.path.join(OLD, "references", case + ".R0.json"); d = json.load(open(f)); rows = [[Fr(x) for x in d["marginals"][str(v)]] if str(v) in d["marginals"] else None for v in range(m.nvars)]
            elif src.startswith("historical libDAI junction tree output"):
                stage = "depth" if "depth stage" in src else "breadth"; hits = [r for r in old_rows if r["case"] == case and r["arm"] == "EXACT" and r["stage"] == stage and r.get("label") is None and r.get("status") == "COMPLETE" and not r.get("censored")]
                f = os.path.join(OLD, hits[0]["out_dir"], "output.MAR"); rows = read_points(f)
            elif src.startswith("THIS campaign's libDAI"):                                                                                               # "THIS campaign" in the snapshot = the AGGREGATE_DP_2026-11-07 campaign it was frozen from
                stage = src.split("stage ")[1].split(";")[0]; hits = [r for r in adp_rows if r["case"] == case and r["arm"] == "EXACT" and r["stage"] == stage and r.get("status") == "COMPLETE" and not r.get("censored")]
                f = os.path.join(ADP, hits[0]["out_dir"], "output.MAR"); rows = read_points(f)
            elif src.startswith("Merlin"):
                arm = "WMB" if "WMB" in src else "IJGP"
                for base, rr in ((OLD, old_rows), (ADP, adp_rows)):
                    hit = [r for r in rr if r["case"] == case and r["arm"] == arm and r.get("status") == "COMPLETE" and r.get("label") is None and os.path.exists(os.path.join(base, r["out_dir"], "cell.json")) and json.load(open(os.path.join(base, r["out_dir"], "cell.json"))).get("exact_by_ibound")]
                    if hit:
                        f = os.path.join(base, hit[0]["out_dir"], "output.MAR"); rows = read_points(f); break
            elif src.startswith("official UAI 2014"):
                f = os.path.join(OLD, "sources", "uai14", "sol", case + ".uai.MAR"); rows = read_points(f)
        except Exception as ex:
            rows = None; f = f or None; pc = dict(pc, resolution_error=repr(ex)[:200])
        if rows is not None and len(rows) != m.nvars:
            rows = None; pc = dict(pc, resolution_error="reference row count %s != nvars %d" % (len(rows) if rows else None, m.nvars))
        out[case] = {"class": pc["class"] if rows is not None else ("R3" if pc["class"] == "R3" else pc["class"] + "_UNRESOLVED"), "source": src, "independence": pc.get("independence"), "file": (os.path.relpath(f, HERE) if f else None), "sha256": (sha(f) if f and os.path.exists(f) else None), "rows": rows, "ev": ev, "nvars": m.nvars, "error": pc.get("resolution_error")}
    return out


def point_error(points, ref_rows, ev):
    err = Fr(0); n = 0; tv = []
    for v, row in enumerate(points):
        if v in ev or v >= len(ref_rows) or ref_rows[v] is None:
            continue
        n += 1; tv.append(float(sum(abs(a - b) for a, b in zip(row, ref_rows[v])) / 2))
        for q, r in zip(row, ref_rows[v]):
            err = max(err, abs(q - r))
    return {"max_abs_error": float(err), "unobserved_variables": n, "tv_mean": (sum(tv) / len(tv) if tv else None), "tv_max": (max(tv) if tv else None), "within_1_200": bool(err <= Fr(1, 200)) if n else None}


def reference_tolerance(ref):
    """the reference's OWN rounding: R0 exact 0; libDAI 10 significant digits -> 1e-9; Merlin 6 decimals -> 1e-6; UAI-2014 solution 6 significant digits -> 1e-5 (conservative absolute tolerances for probabilities in [0, 1])"""
    src = ref.get("source") or ""
    if ref.get("class") == "R0": return Fr(0)
    if "libDAI" in src: return Fr(1, 10 ** 9)
    if "Merlin" in src: return Fr(1, 10 ** 6)
    if "UAI 2014" in src: return Fr(1, 10 ** 5)
    return None


def interval_containment(intervals, ref_rows, ev, tol=Fr(0)):
    out = 0; total = 0; worst = Fr(0); within_tol = 0
    for v, row in enumerate(intervals):
        if v in ev or v >= len(ref_rows) or ref_rows[v] is None:
            continue
        for s, (L, Uu) in enumerate(row):
            total += 1; r = ref_rows[v][s]
            if L <= r <= Uu:
                out += 1; within_tol += 1
            else:
                exc = max(L - r, r - Uu); worst = max(worst, exc)
                if tol is not None and exc <= tol: within_tol += 1
    return {"coordinates": total, "contained": out, "contained_within_reference_tolerance": within_tol, "reference_tolerance": (float(tol) if tol is not None else None), "max_excursion": float(worst), "excursion_beyond_tolerance": bool(tol is not None and worst > tol)}


# ---------------------------------------------------------------------------------------------------------------- per-cell extraction
def counters_of(att):
    return (att or {}).get("counters") or {}


def extract_cell(D, man, r, refs):
    """one reconciled row -> the scored / explained record (nothing inferred; every missing value typed)"""
    od = os.path.join(D, r["out_dir"]); cj = load(os.path.join(od, "cell.json")) or {}; ck = load(os.path.join(od, "checked_record.json")) or load(os.path.join(od, "diagnostic_record.json")) or (cj.get("diagnostic") or {}); ad = load(os.path.join(od, "adapter.json")) or {}   # a stopped attempt leaves the NONCERTIFYING diagnostic record (plan, mechanisms, partial counters, live operation)
    arm = r["arm"]; case = r["case"]; ref = refs[case]; st = r.get("record_status"); accepted = bool(r["accepted"]); success = accepted and st in SUCCESS[arm]
    o = {"index": r["index"], "stage": r["stage"], "arm": arm, "case": case, "family": r["family"], "budget_s": r["budget_s"], "cell_id": r["cell_id"], "task_id": r["task_id"], "out_dir": r["out_dir"], "accepted": accepted, "resolution": r["resolution"], "status": st, "success": success, "guarantee": GUARANTEE[arm],
         "reasons": r.get("reasons"), "supervisor_outcome": r.get("supervisor_outcome"), "supervisor_wall_s": r.get("supervisor_wall_s"), "peak_tree_rss_bytes": r.get("peak_tree_rss_bytes"), "delivery_from_launch_s": r.get("delivery_from_launch_s"), "complete_response_s": r.get("complete_response_s"), "delivered_valid_output": r.get("delivered_valid_output"),
         "stop": r.get("stop"), "reason": r.get("reason"), "late_output": st == "LATE_OUTPUT", "censoring": None, "reference_class": ref["class"], "reference_source": ref["source"], "reference_independence": ref.get("independence")}
    if r["resolution"] in ("EXPLICITLY_UNLAUNCHED", "NOT_LAUNCHED"):
        o["censoring"] = "UNLAUNCHED (typed)"; return o
    if not accepted:
        o["censoring"] = "NOT_ACCEPTED_BY_RECONCILER (counted once, never a success)"
    elif not success:
        o["censoring"] = "TYPED_NONSUCCESS (%s)" % st
    # ---- timing decomposition (seconds; the launch-relative delivery is the contract clock)
    ph = dict(cj.get("phases_s") or {}); o["phases_s"] = ph
    if arm in NEW:
        atts = ck.get("attempts") or cj.get("attempts") or []; last = atts[-1] if atts else {}
        o["attempts"] = [{k: a.get(k) for k in ("route", "precision", "outcome", "stop", "stop_phase", "create_s", "forward_s", "reverse_s", "wall_s", "max_width", "delta_max")} for a in atts]
        o["kernel_s"] = {"create": last.get("create_s"), "forward": last.get("forward_s"), "reverse": last.get("reverse_s"), "attempt_wall": last.get("wall_s")}
        o["route"] = r.get("route"); o["precision"] = r.get("precision"); o["delivered_max_width"] = r.get("delivered_max_width"); o["pre_grid_max_width"] = r.get("max_width_raw")
        red = ck.get("reductions") or cj.get("reductions") or {}; o["reductions"] = {k: red.get(k) for k in ("steps", "passes", "entries_scanned", "seconds", "capped", "free_reduced", "zero_proof", "scale")}; o["nvars"] = (cj.get("task") or {}).get("nvars")
        plan = ck.get("plan") or cj.get("plan") or {}; tot = plan.get("totals") or {}; pred = tot.get("predicted") or {}
        o["plan"] = {"order": plan.get("order"), "nodes": plan.get("nodes"), "cold_work_proxy": tot.get("cold_work_proxy"), "forward_proxy": tot.get("forward_proxy"), "reverse_proxy": tot.get("reverse_proxy"), "materialization_proxy": tot.get("materialization_proxy"), "stored_entries": tot.get("stored_entries"), "peak_reserved_bytes_estimate": tot.get("peak_reserved_bytes_estimate"), "buckets": tot.get("buckets"), "streamed": tot.get("streamed"), "sparse": tot.get("sparse"), "max_bucket_volume": tot.get("max_bucket_volume"), "unknown": tot.get("unknown"), "predicted": pred, "candidates": len(ck.get("plan_candidates") or cj.get("plan_candidates") or []), "discovery_stop": r.get("discovery_stop"), "summary": plan.get("summary")}
        o["mechanisms"] = ck.get("mechanisms") or cj.get("mechanisms"); o["binary64_admission"] = r.get("binary64_admission"); o["plan_validation"] = r.get("plan_validation"); o["validation_s"] = ((ck.get("plan_validation") or cj.get("plan_validation") or {}).get("seconds"))
        fw = (last.get("counters_after_forward") or {}); c = counters_of(last); o["counters"] = c; o["counters_after_forward"] = fw
        if c:
            o["actual"] = {"forward_rows": fw.get("reduce_terms"), "reverse_value_rows": c.get("reverse_value_terms"), "reverse_pull_rows": (c.get("reverse_tuples") or 0) + (c.get("sparse_reverse_rows") or 0), "reverse_combined_rows": c.get("combined_terms"), "sparse_rows_joined": c.get("sparse_rows_joined"), "sparse_driver_scans": c.get("sparse_driver_scans"),
                           "adds_mults_reads": (c.get("adds") or 0) + (c.get("mults") or 0) + (c.get("source_reads") or 0), "cache_hits": c.get("cache_hits"), "downgrades": c.get("downgrades"), "early_flushes": c.get("early_flushes"), "sparse_driver_deviation": c.get("sparse_driver_deviation"), "sparse_driver_policy_differs": c.get("sparse_driver_policy_differs"), "max_frame_depth": c.get("max_frame_depth"), "used_values_bytes": c.get("used_values_bytes"), "used_index_bytes": c.get("used_index_bytes"), "pending_peak_bytes": c.get("pending_peak_bytes"), "peak_scratch_bytes": c.get("peak_scratch_bytes"), "cache_bytes": c.get("cache_bytes")}
            cond = (c.get("cache_hits") or 0) == 0 and (c.get("downgrades") or 0) == 0 and (c.get("early_flushes") or 0) == 0 and (c.get("sparse_driver_deviation") or 0) == 0 and last.get("outcome") == "INTERVALS"
            o["prediction_scope"] = "WHOLE_PLAN_EXECUTED" if last.get("outcome") == "INTERVALS" else "PARTIAL_EXECUTION (counters are a prefix of the plan; not comparable to the whole-plan estimate)"
            if pred and last.get("outcome") == "INTERVALS":
                o["predicted_vs_actual"] = {"forward_rows": (pred.get("forward_rows"), fw.get("reduce_terms")), "reverse_value_rows": (pred.get("reverse_value_rows"), c.get("reverse_value_terms")), "reverse_pull_rows": ((pred.get("reverse_pull_rows") or 0) + (pred.get("sparse_pull_rows") or 0), o["actual"]["reverse_pull_rows"]), "reverse_combined_rows": (pred.get("reverse_combined_rows"), c.get("combined_terms")), "sparse_joined": (pred.get("sparse_joined"), c.get("sparse_rows_joined")), "sparse_driver_scans": (pred.get("sparse_driver_scans"), c.get("sparse_driver_scans")), "proxy_vs_counted": (tot.get("cold_work_proxy"), o["actual"]["adds_mults_reads"]), "assumptions_held": cond,
                                           "note": "CONDITIONAL prediction: exact only under the stated assumptions (assumptions_held); a planned SPARSE child's support is an estimate (no counter on deviation); sparse_driver_policy_differs reports a changed run-time preference, not an estimate error"}
        ml = ck.get("memory_ledger") or cj.get("memory_ledger") or {}; o["memory"] = {"host_reserved_peak_bytes": sum((ml.get("peak") or {}).values()) if ml.get("peak") else None, "host_peak_by_category": ml.get("peak"), "over_release_events": ml.get("over_release_events"), "leases_live": ml.get("leases_live"), "sampled_peak_tree_rss_bytes": r.get("peak_tree_rss_bytes"), "maxrss_self_bytes": r.get("maxrss_self_bytes"), "plan_peak_reserved_estimate": tot.get("peak_reserved_bytes_estimate")}
        o["invariant_failure"] = bool(ml.get("over_release_events"))
        o["diagnostic_stage"] = ck.get("diagnostic_stage") or (cj.get("diagnostic") or {}).get("diagnostic_stage"); o["live_at_stop"] = r.get("live_at_stop"); o["exact_fallback"] = r.get("exact_fallback"); o["clock"] = r.get("clock")
        o["publication"] = {k: (cj.get("publication") or {}).get(k) for k in ("status", "reason", "grid_bits", "wall_s")} if cj.get("publication") else None; o["point_verification"] = {k: (cj.get("point_verification") or {}).get(k) for k in ("status", "wall_s")} if cj.get("point_verification") else None
    elif arm == "ADP_REPAIRED":
        o["adapter"] = {k: ad.get(k) for k in ("producer_status", "producer_returncode", "producer_exit_from_launch_s", "delivery_from_launch_s", "within_budget_from_launch", "adapter_start_after_launch_s")}; o["producer"] = {"status": cj.get("status"), "reductions": cj.get("reductions"), "program": {k: (cj.get("program") or {}).get(k) for k in ("nodes", "components", "formats_planned", "core_entries_total", "bag_rows_total", "largest_bag_rows")} if cj.get("program") else None, "stop": cj.get("stop"), "attempts": [{k: a.get(k) for k in ("outcome", "format", "wall_s")} for a in (cj.get("attempts") or [])][:6], "maxrss_self_bytes": cj.get("maxrss_self_bytes")}
    elif arm == "EXACT_LIBDAI":
        o["adapter"] = {k: ad.get(k) for k in ("producer_status", "producer_returncode", "producer_exit_from_launch_s", "delivery_from_launch_s", "within_budget_from_launch")}; o["producer"] = {"status": cj.get("status"), "solver_side": cj.get("solver_side"), "effective_limits": cj.get("effective_limits"), "output_faults": cj.get("output_faults"), "phases_s": cj.get("phases_s"), "maxrss_children_bytes": cj.get("maxrss_children_bytes")}
    # ---- empirical accuracy against the FROZEN reference (never a certificate; R0 = proof check of containment, R1 / R2 = consistency only)
    mar = os.path.join(od, "output.MAR"); o["complete_output"] = bool(success and os.path.exists(mar) and (r.get("output_sha256") is None or sha(mar) == r.get("output_sha256")))
    if o["complete_output"] and ref["rows"] is not None:
        try:
            pts = read_points(mar); o["empirical_vs_reference"] = point_error(pts, ref["rows"], ref["ev"])
            ivp = os.path.join(od, "intervals.json")
            if arm in NEW and os.path.exists(ivp):
                iv = json.load(open(ivp)); rowsI = []
                for v in range(len(pts)):
                    row = iv.get(str(v)) if isinstance(iv, dict) else None
                    rowsI.append([(Fr(a), Fr(b)) for a, b in row] if row else None)
                o["reference_in_intervals"] = interval_containment(rowsI, ref["rows"], ref["ev"], reference_tolerance(ref)) if all(x is not None for x in rowsI) else {"note": "interval rows missing for some variables"}
                o["reference_in_intervals"]["meaning"] = "PROOF CHECK (exact truth must lie inside every interval)" if ref["class"] == "R0" else "consistency observation only: the certified intervals are far narrower than the reference's own rounding, so 'contained' counts exact hits and 'contained_within_reference_tolerance' counts agreement up to that rounding"
        except Exception as ex:
            o["empirical_vs_reference"] = {"error": repr(ex)[:200]}
    elif o["complete_output"]:
        o["empirical_vs_reference"] = None; o["empirical_note"] = "UNKNOWN accuracy: no qualified reference (R3) -- not an absence of error"
    return o


# ---------------------------------------------------------------------------------------------------------------- comparisons
def ratio(a, b):
    return None if (a is None or b is None or b == 0) else a / b


def matched(cellsA, cellsB, key="delivery_from_launch_s"):
    """matched completed tasks only (both successes with a finite launch-relative delivery); censored (timeout / refusal / stop) cells NEVER enter a ratio"""
    out = []
    for case in sorted(set(cellsA) & set(cellsB)):
        a, b = cellsA[case], cellsB[case]
        if a["success"] and b["success"] and isinstance(a.get(key), (int, float)) and isinstance(b.get(key), (int, float)) and b[key] > 0:
            out.append({"case": case, "family": a["family"], "a": a[key], "b": b[key], "ratio_a_over_b": a[key] / b[key]})
    return out


def summarize_pairs(pairs):
    if not pairs:
        return {"n": 0}
    rs = sorted(p["ratio_a_over_b"] for p in pairs); n = len(rs); med = rs[n // 2] if n % 2 else (rs[n // 2 - 1] + rs[n // 2]) / 2
    return {"n": n, "median_ratio": med, "min_ratio": rs[0], "max_ratio": rs[-1], "a_faster": sum(1 for x in rs if x < 1), "b_faster": sum(1 for x in rs if x > 1), "ties": sum(1 for x in rs if x == 1), "by_family": {f: sorted(p["ratio_a_over_b"] for p in pairs if p["family"] == f) for f in sorted({p["family"] for p in pairs})}, "cases": [(p["case"], round(p["ratio_a_over_b"], 3)) for p in pairs]}


def compare(cells, armA, armB, stage, label):
    A = {c["case"]: c for c in cells if c["arm"] == armA and c["stage"] == stage}; B = {c["case"]: c for c in cells if c["arm"] == armB and c["stage"] == stage}
    both = sorted(set(A) & set(B)); sa = {k for k in both if A[k]["success"]}; sb = {k for k in both if B[k]["success"]}
    pairs = matched(A, B); work = []
    for k in both:
        a, b = A[k], B[k]
        if a["success"] and b["success"] and (a.get("actual") or {}).get("adds_mults_reads") and (b.get("actual") or {}).get("adds_mults_reads"):
            work.append({"case": k, "family": a["family"], "a": a["actual"]["adds_mults_reads"], "b": b["actual"]["adds_mults_reads"], "ratio_a_over_b": a["actual"]["adds_mults_reads"] / b["actual"]["adds_mults_reads"]})
    mem = []
    for k in both:
        a, b = A[k], B[k]
        if a["success"] and b["success"] and a.get("peak_tree_rss_bytes") and b.get("peak_tree_rss_bytes"):
            mem.append({"case": k, "family": a["family"], "a": a["peak_tree_rss_bytes"], "b": b["peak_tree_rss_bytes"], "ratio_a_over_b": a["peak_tree_rss_bytes"] / b["peak_tree_rss_bytes"]})
    return {"label": label, "stage": stage, "arm_a": armA, "arm_b": armB, "cases_compared": len(both), "success_a": len(sa), "success_b": len(sb), "both": len(sa & sb), "a_only_gains": sorted(sa - sb), "b_only_losses": sorted(sb - sa), "neither": sorted(set(both) - sa - sb),
            "status_pairs": collections.Counter("%s / %s" % (A[k]["status"], B[k]["status"]) for k in both).most_common(), "matched_delivery_ratio": summarize_pairs(pairs), "matched_counted_work_ratio": summarize_pairs(work), "matched_peak_tree_rss_ratio": summarize_pairs(mem),
            "censoring_note": "ratios use matched completed tasks only (both successes); timeouts, refusals and typed stops are listed by status and never converted to runtimes; one observation per cell -> exploratory, not repeatable speed claims",
            "guarantee_note": "%s versus %s" % (GUARANTEE[armA], GUARANTEE[armB])}


# ---------------------------------------------------------------------------------------------------------------- mechanisms and explanations (GENERAL cells)
def mechanisms_row(c):
    m = c.get("mechanisms") or {}; red = c.get("reductions") or {}; nv = c.get("nvars"); pl = c.get("plan") or {}; summ = pl.get("summary") or {}
    offered = {"source_reduction_steps": red.get("steps"), "free_variables_after_reduction": red.get("free_reduced"), "original_variables": nv, "reduction_fraction": (1 - red["free_reduced"] / nv) if (red.get("free_reduced") is not None and nv) else None, "zero_proof": red.get("zero_proof"), "capped": red.get("capped")}
    started = bool(c.get("counters")); whole = c.get("prediction_scope") == "WHOLE_PLAN_EXECUTED"
    def state(accepted, reached, noop=None, declined=None):
        if c.get("plan") is None or pl.get("nodes") is None: return "UNKNOWN (no plan recorded: stopped before planning finished)"
        if accepted and whole: return "ACCEPTED_AND_REACHED (whole plan executed)"
        if accepted and started: return "ACCEPTED_PARTIALLY_REACHED (execution started, stopped before the plan completed)"
        if accepted: return "ACCEPTED_NOT_REACHED (planned; stopped before execution)"
        if noop: return "NO_OP (checked, no effect)"
        if declined: return "DECLINED (candidates priced, none cheaper)"
        return "NOT_SELECTED (no candidate)"
    executed = whole
    v = m.get("views") or {}; d = m.get("demand") or {}; f = m.get("fusion") or {}; t = m.get("two_axis") or {}; s = m.get("sparse") or {}; dg = m.get("downgrades") or {}
    return {"index": c["index"], "stage": c["stage"], "arm": c["arm"], "case": c["case"], "family": c["family"], "status": c["status"], "offered_reduction": offered,
            "response_views": {"state": state((v.get("compressed_axes") or 0) > 0, executed, noop=(v.get("checked_no_op") or 0) > 0), "compressed_axes": v.get("compressed_axes"), "checked_no_op": v.get("checked_no_op"), "skipped": v.get("skipped")},
            "backward_demand": {"state": state((d.get("restricted_nodes") or 0) > 0, executed), "restricted_nodes": d.get("restricted_nodes"), "entries_saved": d.get("entries_saved"), "passes": d.get("passes"), "skipped": d.get("skipped"), "reads_outside_demand": (c.get("counters") or {}).get("reads_outside_demand")},
            "fusion": {"state": state((f.get("merged") or 0) > 0, executed, declined=(f.get("declined") or 0) > 0), "merged": f.get("merged"), "declined": f.get("declined"), "candidates": f.get("candidates")},
            "two_axis_conditioning": {"state": state((t.get("chosen") or 0) > 0, executed, declined=(t.get("declined") or 0) > 0), "chosen": t.get("chosen"), "declined": t.get("declined"), "ineligible": t.get("ineligible")},
            "sparse_joins": {"state": state((s.get("nodes") or 0) > 0, executed), "planned_sparse_nodes": s.get("nodes"), "sparse_rows_joined": (c.get("actual") or {}).get("sparse_rows_joined"), "driver_scans": (c.get("actual") or {}).get("sparse_driver_scans"), "deviation": (c.get("actual") or {}).get("sparse_driver_deviation"), "policy_differs": (c.get("actual") or {}).get("sparse_driver_policy_differs")},
            "planned_downgrades": dg, "runtime_downgrades": (c.get("actual") or {}).get("downgrades"), "cache": {"hits": (c.get("actual") or {}).get("cache_hits"), "early_flushes": (c.get("actual") or {}).get("early_flushes"), "cache_bytes": (c.get("actual") or {}).get("cache_bytes"), "stream_reevals": (c.get("counters") or {}).get("stream_reevals")},
            "planned_vs_actual": c.get("predicted_vs_actual"), "prediction_scope": c.get("prediction_scope"), "plan_order": pl.get("order"), "candidates_priced": pl.get("candidates"), "cold_work_proxy": pl.get("cold_work_proxy"), "storage_summary": summ.get("storage"),
            "costs_s": {"startup_imports": (c.get("phases_s") or {}).get("startup_imports"), "snapshot_parse": (c.get("phases_s") or {}).get("snapshot"), "reductions": (c.get("phases_s") or {}).get("reductions"), "trusted_snapshot": (c.get("phases_s") or {}).get("trusted_snapshot"), "plan": (c.get("phases_s") or {}).get("plan"), "validate": (c.get("phases_s") or {}).get("validate"), "flatten": (c.get("phases_s") or {}).get("flatten"), "kernel": c.get("kernel_s"), "publish": (c.get("phases_s") or {}).get("publish"), "delivery_from_launch": c.get("delivery_from_launch_s")},
            "memory": c.get("memory"), "stopped_at": {"stage": c.get("diagnostic_stage"), "live": c.get("live_at_stop"), "stop": c.get("stop")} if not c["success"] else None}


def explain(case_cells):
    """per case: GENERAL vs PLAIN at 20 s and 120 s -> one labelled explanation (supported / suggestive / unresolved) from the recorded data only"""
    out = []
    for budget, stage in ((20.0, "primary_breadth"), (120.0, "primary_depth")):
        g = case_cells.get(("GENERAL_BIDI_COMPLETE_V3", stage)); p = case_cells.get(("NATIVE_PLAIN_COMPLETE_V3", stage))
        if not g or not p or not g["accepted"] or not p["accepted"]:
            out.append({"stage": stage, "label": "unresolved", "explanation": "a cell of the pair is missing or not accepted", "evidence": None}); continue
        m = g.get("mechanisms") or {}; any_mech = any([(m.get("views") or {}).get("compressed_axes"), (m.get("demand") or {}).get("restricted_nodes"), (m.get("fusion") or {}).get("merged"), (m.get("two_axis") or {}).get("chosen"), (m.get("sparse") or {}).get("nodes")])
        ga = g.get("actual") or {}; pa = p.get("actual") or {}; gph = g.get("phases_s") or {}; gk = g.get("kernel_s") or {}
        ev = {"general_status": g["status"], "plain_status": p["status"], "general_delivery_s": g.get("delivery_from_launch_s"), "plain_delivery_s": p.get("delivery_from_launch_s"), "general_counted_work": ga.get("adds_mults_reads"), "plain_counted_work": pa.get("adds_mults_reads"), "general_proxy": (g.get("plan") or {}).get("cold_work_proxy"), "plain_proxy": (p.get("plan") or {}).get("cold_work_proxy"), "mechanisms_planned": any_mech, "general_stop": g.get("stop"), "plain_stop": p.get("stop"), "general_plan_validate_s": (gph.get("plan") or 0) + (gph.get("validate") or 0) + (gph.get("trusted_snapshot") or 0), "general_kernel_s": ((gk.get("forward") or 0) + (gk.get("reverse") or 0)) if gk else None, "general_publish_s": gph.get("publish")}
        if g["success"] and p["success"]:
            if not any_mech:
                lab, txt = "supported", "no planner mechanism was selected (views / demand / fusion / two-axis / sparse all zero): GENERAL executes the same plain schedule; the delivery difference is planner + validation overhead only"
            elif (ga.get("adds_mults_reads") or 0) < (pa.get("adds_mults_reads") or 0):
                if (g.get("delivery_from_launch_s") or 0) > (p.get("delivery_from_launch_s") or 0):
                    lab, txt = "supported", "mechanisms reduced the counted kernel work but planning / validation / publication consumed the savings (GENERAL delivered later than PLAIN)"
                else:
                    lab, txt = "supported", "mechanisms reduced the counted kernel work and GENERAL delivered no later than PLAIN"
            else:
                lab, txt = "suggestive", "mechanisms were selected but counted work did not fall below PLAIN's (the selected representation was not useful on this task, or the price model misranked it)"
        elif g["success"] and not p["success"]:
            lab, txt = ("supported" if any_mech else "suggestive"), "coverage GAIN: GENERAL certified where PLAIN stopped (%s)%s" % (p["status"], "" if any_mech else " -- without any selected mechanism (the difference is not attributable to a mechanism)")
        elif p["success"] and not g["success"]:
            lab, txt = "supported", "coverage LOSS: PLAIN certified where GENERAL stopped (%s)%s" % (g["status"], " after planning overhead" if (ev["general_plan_validate_s"] or 0) > 1.0 else "")
        else:
            same_phase = (g.get("stop") or {}).get("detail") == (p.get("stop") or {}).get("detail")
            if not any_mech:
                lab, txt = "supported", "residual work remains large: both arms stop (%s / %s) and GENERAL found no useful representation to select" % (g["status"], p["status"])
            else:
                lab, txt = ("suggestive" if same_phase else "unresolved"), "both arms stop (%s / %s); GENERAL selected mechanisms (%s) but did not finish -- residual work remains large or the selected representation did not preserve enough savings (one observation; partial counters are not comparable to the whole-plan estimate)" % (g["status"], p["status"], {k: v for k, v in m.items() if k in ("views", "demand", "fusion", "two_axis", "sparse")})
        out.append({"stage": stage, "label": lab, "explanation": txt, "evidence": ev})
    return out


# ---------------------------------------------------------------------------------------------------------------- main
def main(D, out_root=None):
    """out_root (optional): write ANALYSIS/ and CELLS_LEDGER.jsonl under this directory instead of D (dry runs on a partial matrix never touch the run directory)"""
    t0 = time.monotonic(); man = json.load(open(os.path.join(D, "GB_MANIFEST.json"))); root = out_root or D; A = os.path.join(root, "ANALYSIS"); os.makedirs(A, exist_ok=True)
    idx = RC.ledger_index(D); rows = [RC.reconcile(D, man, c, idx) for c in man["cells"]]
    with open(os.path.join(root, "CELLS_LEDGER.jsonl"), "w") as f:
        for r in rows: f.write(json.dumps(r, default=str) + "\n")
    # completeness
    comp = {}
    for r in rows:
        k = (r["stage"], r["arm"]); d = comp.setdefault(k, {"planned": 0, "launched": 0, "terminal_reconciled": 0, "accepted": 0, "not_accepted": 0, "unlaunched": 0, "success": 0, "statuses": collections.Counter()})
        launched = r["resolution"] not in ("EXPLICITLY_UNLAUNCHED", "NOT_LAUNCHED"); d["planned"] += 1; d["launched"] += launched; d["terminal_reconciled"] += launched; d["accepted"] += bool(r["accepted"]); d["not_accepted"] += (launched and not r["accepted"]); d["unlaunched"] += (not launched); d["success"] += bool(r["accepted"] and r.get("record_status") in SUCCESS[r["arm"]]); d["statuses"][r.get("record_status") or r["resolution"]] += 1
    table = [{"stage": s, "arm": a, **{k: (dict(v) if isinstance(v, collections.Counter) else v) for k, v in d.items()}} for (s, a), d in sorted(comp.items())]
    tot = {k: sum(x[k] for x in table) for k in ("planned", "launched", "terminal_reconciled", "accepted", "not_accepted", "unlaunched", "success")}
    complete_run = tot["planned"] == 414 and tot["launched"] == 414 and tot["terminal_reconciled"] == 414
    json.dump({"by_stage_arm": table, "totals": tot, "complete_414_cell_run": complete_run, "rule": "planned = frozen manifest rows; launched = a START exists; terminal_reconciled = launched with exactly one receipt (the reconciler requires it); accepted = reconciler accepted (success OR typed noncertifying attempt); success = accepted AND the arm's success status (CERTIFIED / COMPLETE); not_accepted rows are counted once and never successes", "shortfall_reason": None if complete_run else "see RUN_STOPPED.json / NOT_LAUNCHED.json rows"}, open(os.path.join(A, "COMPLETENESS.json"), "w"), indent=1)
    # references frozen before scoring
    refs = resolve_references(D, man)
    json.dump({c: {k: v for k, v in r.items() if k not in ("rows", "ev")} | {"ev_variables": sorted(r["ev"]) if r.get("ev") else [], "rows_resolved": r["rows"] is not None} for c, r in refs.items()}, open(os.path.join(A, "REFERENCES_RESOLVED.json"), "w"), indent=1)
    cells = [extract_cell(D, man, r, refs) for r in rows]
    with open(os.path.join(A, "SCORES.jsonl"), "w") as f:
        for c in cells: f.write(json.dumps(c, default=str) + "\n")
    # per-case records (48)
    by_case = collections.defaultdict(dict)
    for c in cells: by_case[c["case"]][(c["arm"], c["stage"])] = c
    with open(os.path.join(A, "CASES.jsonl"), "w") as f:
        for case, cs in man["cases"].items():
            cc = by_case[case]; rec = {"slot": case, "accessible": True, "family": cs["family"], "variables": cs["variables"], "reference": {k: v for k, v in refs[case].items() if k in ("class", "source", "file", "sha256")},
                   "cells": {"%s@%s" % (a, s): {k: c.get(k) for k in ("status", "accepted", "success", "delivery_from_launch_s", "route", "precision", "delivered_max_width", "peak_tree_rss_bytes", "stop", "empirical_vs_reference", "reference_in_intervals", "censoring")} for (a, s), c in sorted(cc.items())},
                   "general_mechanisms": {s: mechanisms_row(c) for (a, s), c in cc.items() if a == "GENERAL_BIDI_COMPLETE_V3"}, "explanations": explain(cc)}
            f.write(json.dumps(rec, default=str) + "\n")
        for u in man["unavailable_slots"]:
            f.write(json.dumps({"slot": u["case"], "accessible": False, "family": u["family"], "status": "INPUT_UNAVAILABLE", "cells": {}, "note": "inventory slot with no accessible input (frozen 48-slot selection); kept as a typed row"}) + "\n")
    # comparisons
    comps = [compare(cells, "GENERAL_BIDI_COMPLETE_V3", "NATIVE_PLAIN_COMPLETE_V3", "primary_breadth", "PRIMARY: GENERAL vs NATIVE_PLAIN at 20 s"), compare(cells, "GENERAL_BIDI_COMPLETE_V3", "NATIVE_PLAIN_COMPLETE_V3", "primary_depth", "PRIMARY: GENERAL vs NATIVE_PLAIN at 120 s"),
             compare(cells, "GENERAL_BIDI_COMPLETE_V3", "ADP_REPAIRED", "primary_breadth", "GENERAL vs ADP_REPAIRED at 20 s (bundles schedule, substrate and protocol differences)"), compare(cells, "GENERAL_BIDI_COMPLETE_V3", "EXACT_LIBDAI", "primary_breadth", "GENERAL (certified) vs EXACT_LIBDAI (uncertified point) at 20 s")]
    G20 = {c["case"]: c for c in cells if c["arm"] == "GENERAL_BIDI_COMPLETE_V3" and c["stage"] == "primary_breadth"}
    for ab in ABL:
        AB = {c["case"]: c for c in cells if c["arm"] == ab and c["stage"] == "ablation_breadth"}; both = sorted(set(AB) & set(G20)); pairs = matched(AB, G20)
        plan_changes = []
        for k in both:
            a, g = AB[k], G20[k]; ma = a.get("mechanisms") or {}; mg = g.get("mechanisms") or {}
            diff = {mk: (ma.get(mk), mg.get(mk)) for mk in ("views", "demand", "fusion", "two_axis", "sparse", "downgrades") if ma.get(mk) != mg.get(mk)}
            if diff or (a.get("plan") or {}).get("cold_work_proxy") != (g.get("plan") or {}).get("cold_work_proxy"):
                plan_changes.append({"case": k, "family": a["family"], "mechanism_diff": diff, "proxy": ((a.get("plan") or {}).get("cold_work_proxy"), (g.get("plan") or {}).get("cold_work_proxy")), "status": (a["status"], g["status"]), "delivery": (a.get("delivery_from_launch_s"), g.get("delivery_from_launch_s")), "counted_work": ((a.get("actual") or {}).get("adds_mults_reads"), (g.get("actual") or {}).get("adds_mults_reads"))})
        sa = {k for k in both if AB[k]["success"]}; sg = {k for k in both if G20[k]["success"]}
        comps.append({"label": "ABLATION %s (20 s) vs GENERAL (20 s)" % ab, "arm_a": ab, "arm_b": "GENERAL_BIDI_COMPLETE_V3", "cases_compared": len(both), "success_ablation": len(sa), "success_general": len(sg), "ablation_only": sorted(sa - sg), "general_only": sorted(sg - sa), "neither": sorted(set(both) - sa - sg), "status_pairs": collections.Counter("%s / %s" % (AB[k]["status"], G20[k]["status"]) for k in both).most_common(),
                      "matched_delivery_ratio_ablation_over_general": summarize_pairs(pairs), "plan_changed_cases": plan_changes, "plan_unchanged_cases": sorted(set(both) - {x["case"] for x in plan_changes}), "note": "a disabled mechanism may change the whole plan (policy-induced plan changes are listed), or change nothing (listed as unchanged = the mechanism was a no-op on that case)"})
    json.dump(comps, open(os.path.join(A, "COMPARISONS.json"), "w"), indent=1, default=str)
    # mechanisms (every GENERAL / ablation cell), failures, graveyard
    with open(os.path.join(A, "MECHANISMS.jsonl"), "w") as f:
        for c in cells:
            if c["arm"] in NEW and c["accepted"]: f.write(json.dumps(mechanisms_row(c), default=str) + "\n")
    fails = {"late_outputs": [(c["case"], c["arm"], c["stage"]) for c in cells if c["status"] == "LATE_OUTPUT"], "inconsistent_evidence": [(c["case"], c["arm"], c["stage"]) for c in cells if c["status"] in ("INCONSISTENT_EVIDENCE_CERTIFIED", "ZERO_EVIDENCE_PROVED")], "resource_stops": collections.Counter((c["arm"], c["stage"], (c.get("stop") or {}).get("detail") or c.get("reason")) for c in cells if c["status"] == "RESOURCE_STOP").most_common(),
             "plan_stops": [(c["case"], c["arm"], c["stage"], c.get("reason")) for c in cells if c["status"] == "PLAN_STOP"], "numerical_limits": [(c["case"], c["arm"], c["stage"], c["status"], c.get("reason")) for c in cells if c["status"] in ("UNSOUND_ROUTE", "NOT_REPRESENTABLE", "CHECK_FAILED", "VALID_BUT_TOO_WIDE")], "admission_refused": [(c["case"], c["arm"], c["stage"], c.get("reason")) for c in cells if c["status"] == "ADMISSION_REFUSED"],
             "invalid_or_faulted": [(c["case"], c["arm"], c["stage"], c["status"], c.get("reason")) for c in cells if c["status"] in ("INVALID_INPUT", "FAULT", "TASK_MISMATCH", "NO_RECORD", "LAUNCH_FAILED")], "not_accepted": [(c["case"], c["arm"], c["stage"], c["reasons"]) for c in cells if c["resolution"] == "NOT_ACCEPTED"], "unavailable_inputs": [u["case"] for u in man["unavailable_slots"]], "invariant_failures_over_release": [(c["case"], c["arm"], c["stage"]) for c in cells if c.get("invariant_failure")],
             "exact_fallbacks": [(c["case"], c["arm"], c["stage"]) for c in cells if c.get("exact_fallback")], "reference_excursions_beyond_tolerance": [(c["case"], c["arm"], c["stage"], c["reference_class"], c["reference_in_intervals"]) for c in cells if isinstance(c.get("reference_in_intervals"), dict) and c["reference_in_intervals"].get("excursion_beyond_tolerance")], "r0_containment_failures": [(c["case"], c["arm"], c["stage"], c["reference_in_intervals"]) for c in cells if c.get("reference_class") == "R0" and isinstance(c.get("reference_in_intervals"), dict) and c["reference_in_intervals"].get("contained") is not None and c["reference_in_intervals"]["contained"] < c["reference_in_intervals"]["coordinates"]]}
    json.dump(fails, open(os.path.join(A, "FAILURES.json"), "w"), indent=1, default=str)
    grave = {"mechanism_no_effect": [], "ablation_identical_to_general": [], "families_without_difference": [], "null_feature_comparisons": []}
    for c in cells:
        if c["arm"] == "GENERAL_BIDI_COMPLETE_V3" and c["accepted"]:
            m = c.get("mechanisms") or {}
            if (m.get("views") or {}).get("checked_no_op"): grave["mechanism_no_effect"].append((c["case"], c["stage"], "response views checked, no-op"))
            if (m.get("fusion") or {}).get("candidates") and not (m.get("fusion") or {}).get("merged"): grave["mechanism_no_effect"].append((c["case"], c["stage"], "fusion candidates priced, none merged"))
            if (m.get("two_axis") or {}).get("declined") and not (m.get("two_axis") or {}).get("chosen"): grave["mechanism_no_effect"].append((c["case"], c["stage"], "two-axis alternatives priced, one-axis kept"))
            if (m.get("demand") or {}).get("passes") and not (m.get("demand") or {}).get("restricted_nodes"): grave["mechanism_no_effect"].append((c["case"], c["stage"], "demand passes ran, nothing restricted"))
    for comp in comps:
        if comp.get("plan_unchanged_cases") is not None: grave["ablation_identical_to_general"].append((comp["arm_a"], comp["plan_unchanged_cases"]))
    fam = collections.defaultdict(list)
    for c in cells:
        if c["stage"] == "primary_breadth" and c["arm"] in ("GENERAL_BIDI_COMPLETE_V3", "NATIVE_PLAIN_COMPLETE_V3"): fam[c["family"]].append(c)
    for f_, cs in fam.items():
        g = {c["case"]: c["status"] for c in cs if c["arm"] == "GENERAL_BIDI_COMPLETE_V3"}; p = {c["case"]: c["status"] for c in cs if c["arm"] == "NATIVE_PLAIN_COMPLETE_V3"}
        if all(g.get(k) == p.get(k) for k in g): grave["families_without_difference"].append((f_, dict(g)))
    grave["null_feature_comparisons"].append("no selector training, benchmark tuning or implementation list is derived from this pass (by the authorization)")
    json.dump(grave, open(os.path.join(A, "GRAVEYARD.json"), "w"), indent=1, default=str)
    with open(os.path.join(A, "EXPLANATIONS.jsonl"), "w") as f:
        for case in man["cases"]:
            for e in explain(by_case[case]): f.write(json.dumps(dict(e, case=case, family=man["cases"][case]["family"]), default=str) + "\n")
    # budget (nonnested; this analysis job's own START is live)
    total, by, unresolved, extra = PI.charged(D); self_jid = os.environ.get("GBIDI_PARENT_JID"); live_self = [u for u in unresolved if u.get("jid") == self_jid]; others = [u for u in unresolved if u.get("jid") != self_jid]
    receipted = total - sum((u.get("max_permitted_charge_s") or 0.0) for u in live_self); L = jl(os.path.join(D, "GB_LEDGER.jsonl")); rc = [x for x in L if x["kind"] == "RECEIPT"]
    prep = sum(v for k, v in by.items() if not (k.startswith("matrix_") or k.startswith("parent_remainder:stage_outer"))); mat = sum(v for k, v in by.items() if k.startswith("matrix_") or k.startswith("parent_remainder:stage_outer"))
    budget = {"nonnested_receipted_total_s": receipted, "this_analysis_job_pending_at_max_permitted_s": sum((u.get("max_permitted_charge_s") or 0.0) for u in live_self), "by_scope_s": by, "preparation_type_s": prep, "matrix_type_s": mat, "receipts": len(rc), "raw_receipt_sum_s_overlapping_not_the_total": sum(x["wall_s"] for x in rc if isinstance(x.get("wall_s"), (int, float))),
              "envelope_s": PI.CEILING_S, "remaining_envelope_s": PI.CEILING_S - receipted, "allocations": {"preparation_cap_s": PI.PREPARATION_CAP_S, "matrix_reserve_s": PI.MATRIX_RESERVE_S, "inspection_analysis_reserve_s": PI.INSPECTION_RESERVE_S, "closeout_reserve_s": PI.CLOSEOUT_RESERVE_S, "contingency_s": PI.CONTINGENCY_S}, "preparation_over_cap_s": max(0.0, prep - PI.PREPARATION_CAP_S), "preparation_overage_rule": "the preparation-type excess over 5,000 s is drawn from the campaign contingency (1,436 s) inside the unchanged 28,800 s ceiling (authorized 10 Nov 2026)",
              "other_unresolved": [u.get("job") for u in others], "duplicate_receipts": extra["duplicate_receipts"], "unknown_wall_receipts": extra.get("unknown_wall_receipts"), "compliance": "receipted-charge / envelope compliance only; uncharged interpreter exposure UNKNOWN (no bound claimed); the final total adds this job's and the packaging job's receipts (sidecar)"}
    json.dump(budget, open(os.path.join(A, "BUDGET_FINAL.json"), "w"), indent=1, default=str)
    # extraction record (source hashes; read-only)
    rec = {"utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "extractor": {"gbidi3_closeout/analysis.py": sha(os.path.abspath(__file__)), "gbidi3/reconcile.py": sha(os.path.join(HERE, "gbidi3/reconcile.py")), "gbidi3/pilot.py": sha(os.path.join(HERE, "gbidi3/pilot.py")), "ext/uai.py": sha(os.path.join(HERE, "ext/uai.py"))}, "inputs": {"GB_MANIFEST.json": sha(os.path.join(D, "GB_MANIFEST.json")), "REFERENCE_SNAPSHOT.json": sha(os.path.join(D, "REFERENCE_SNAPSHOT.json")), "INSPECTION_SCHEMA.json": sha(os.path.join(D, "INSPECTION_SCHEMA.json")), "GB_LEDGER.jsonl_rows": len(L)},
           "controls": {"rows_equal_manifest_cells": len(rows) == len(man["cells"]) == 414, "every_success_has_bound_output": all(c["complete_output"] for c in cells if c["success"] and c["arm"] in NEW), "no_new_output_promoted_to_reference": all(not (r.get("file") or "").startswith(os.path.relpath(D, HERE)) for r in refs.values()), "reference_rows_count_matches_nvars": all(r["rows"] is None or len(r["rows"]) == r["nvars"] for r in refs.values()), "r0_proof_checks": [(c["case"], c["arm"], c["stage"], c["reference_in_intervals"]) for c in cells if c["reference_class"] == "R0" and c.get("reference_in_intervals")]},
           "wall_s": time.monotonic() - t0, "read_only": "no inference, no counter filled, no cell modified"}
    json.dump(rec, open(os.path.join(A, "EXTRACTION_RECORD.json"), "w"), indent=1, default=str)
    write_report(D, A, man, cells, table, tot, complete_run, comps, refs, fails, grave, budget, rec)
    print(json.dumps({"cells": len(cells), "complete_414": complete_run, "success_by_arm_stage": {"%s@%s" % (x["arm"], x["stage"]): x["success"] for x in table}, "wall_s": round(rec["wall_s"], 1)}))


def write_report(D, A, man, cells, table, tot, complete_run, comps, refs, fails, grave, budget, rec):
    L = []; P = L.append
    P("# GENERAL_BIDI_COMPLETE_V3 — 414-cell matrix: full-panel report (read-only extraction %s)" % rec["utc"])
    P(""); P("**Frozen manifest** commit `%s`, sha256 `%s`; kernel `%s…`; %d cells; one fresh-process observation per cell; launch-relative deadline. %s" % (man["commit"][:12], rec["inputs"]["GB_MANIFEST.json"][:16], man["kernel_binary_sha256"][:12], len(man["cells"]), "**COMPLETE 414-cell run** (every planned cell launched and terminally reconciled)." if complete_run else "**NOT a complete run**: see COMPLETENESS.json."))
    P(""); P("## 1. Completeness (planned / launched / terminal / accepted / success)"); P(""); P("| stage | arm | planned | launched | terminal | accepted | success | statuses |"); P("|---|---|---:|---:|---:|---:|---:|---|")
    for x in table: P("| %s | %s | %d | %d | %d | %d | %d | %s |" % (x["stage"], x["arm"], x["planned"], x["launched"], x["terminal_reconciled"], x["accepted"], x["success"], ", ".join("%s %d" % kv for kv in sorted(x["statuses"].items(), key=lambda t: -t[1]))))
    P("| **total** | | **%d** | **%d** | **%d** | **%d** | **%d** | |" % (tot["planned"], tot["launched"], tot["terminal_reconciled"], tot["accepted"], tot["success"]))
    P(""); P("Success = CERTIFIED for the five interval arms and ADP_REPAIRED (each under its own checker), COMPLETE for EXACT_LIBDAI (an UNCERTIFIED binary64 point). Not-accepted rows: %d (%s)." % (tot["not_accepted"], "none" if not fails["not_accepted"] else fails["not_accepted"][:5]))
    P(""); P("## 2. Primary comparison: GENERAL_BIDI_COMPLETE_V3 versus NATIVE_PLAIN_COMPLETE_V3")
    for comp in comps[:2]:
        md = comp["matched_delivery_ratio"]; mw = comp["matched_counted_work_ratio"]; mm = comp["matched_peak_tree_rss_ratio"]
        P(""); P("### %s" % comp["label"]); P(""); P("- cases compared %d; GENERAL certified %d; PLAIN certified %d; both %d; **GENERAL-only gains** %s; **PLAIN-only losses** %s; neither %d." % (comp["cases_compared"], comp["success_a"], comp["success_b"], comp["both"], comp["a_only_gains"] or "none", comp["b_only_losses"] or "none", len(comp["neither"])))
        P("- status pairs (GENERAL / PLAIN): %s" % ", ".join("%s ×%d" % kv for kv in comp["status_pairs"]))
        P("- matched completed tasks (both certified): n = %d; median delivery ratio GENERAL/PLAIN %s; GENERAL faster on %s, slower on %s; per-case ratios %s" % (md["n"], ("%.3f" % md["median_ratio"]) if md["n"] else "n/a", md.get("a_faster", 0), md.get("b_faster", 0), md.get("cases", [])))
        P("- matched counted kernel work (adds + mults + source reads) ratio GENERAL/PLAIN: n = %d, median %s, per-case %s" % (mw["n"], ("%.3f" % mw["median_ratio"]) if mw["n"] else "n/a", mw.get("cases", [])))
        P("- matched sampled peak process-tree RSS ratio GENERAL/PLAIN: n = %d, median %s" % (mm["n"], ("%.3f" % mm["median_ratio"]) if mm["n"] else "n/a"))
        P("- %s" % comp["censoring_note"])
    P(""); P("### Family tables (success counts; GENERAL / PLAIN / ADP / libDAI at 20 s; GENERAL / PLAIN at 120 s)"); P(""); P("| family | cases | G20 | P20 | ADP20 | libDAI20 | G120 | P120 |"); P("|---|---:|---:|---:|---:|---:|---:|---:|")
    fams = sorted({cs["family"] for cs in man["cases"].values()})
    def cnt(arm, stage, fam): return sum(1 for c in cells if c["arm"] == arm and c["stage"] == stage and c["family"] == fam and c["success"])
    for fam in fams:
        n = sum(1 for cs in man["cases"].values() if cs["family"] == fam); P("| %s | %d | %d | %d | %d | %d | %d | %d |" % (fam, n, cnt("GENERAL_BIDI_COMPLETE_V3", "primary_breadth", fam), cnt("NATIVE_PLAIN_COMPLETE_V3", "primary_breadth", fam), cnt("ADP_REPAIRED", "primary_breadth", fam), cnt("EXACT_LIBDAI", "primary_breadth", fam), cnt("GENERAL_BIDI_COMPLETE_V3", "primary_depth", fam), cnt("NATIVE_PLAIN_COMPLETE_V3", "primary_depth", fam)))
    P(""); P("## 3. Secondary comparisons (weaker or bundled)")
    for comp in comps[2:4]:
        md = comp["matched_delivery_ratio"]; P(""); P("- **%s**: GENERAL %d / other %d successes of %d; GENERAL-only %s; other-only %s; matched n = %d, median delivery ratio %s. %s" % (comp["label"], comp["success_a"], comp["success_b"], comp["cases_compared"], comp["a_only_gains"] or "none", comp["b_only_losses"] or "none", md["n"], ("%.3f" % md["median_ratio"]) if md["n"] else "n/a", comp["guarantee_note"]))
    P(""); P("## 4. Ablations (20 s) versus GENERAL (20 s), all 46 cases each")
    for comp in comps[4:]:
        md = comp["matched_delivery_ratio_ablation_over_general"]; P(""); P("- **%s**: ablation certified %d, GENERAL %d of %d; ablation-only %s; GENERAL-only %s; plan changed on %d cases %s; plan unchanged (mechanism no-op) on %d; matched delivery ratio ablation/GENERAL n = %d, median %s." % (comp["label"], comp["success_ablation"], comp["success_general"], comp["cases_compared"], comp["ablation_only"] or "none", comp["general_only"] or "none", len(comp["plan_changed_cases"]), [x["case"] for x in comp["plan_changed_cases"]], len(comp["plan_unchanged_cases"]), md["n"], ("%.3f" % md["median_ratio"]) if md["n"] else "n/a"))
    P(""); P("## 5. Failures and typed outcomes"); P("")
    P("- late outputs: %s" % (fails["late_outputs"] or "none")); P("- inconsistent / zero evidence: %s" % (fails["inconsistent_evidence"] or "none")); P("- resource stops by (arm, stage, detail): %s" % fails["resource_stops"]); P("- plan stops: %s" % (fails["plan_stops"] or "none")); P("- numerical limits: %s" % (fails["numerical_limits"] or "none")); P("- admission refused (comparators): %s" % (fails["admission_refused"] or "none")); P("- invalid / faulted / no record: %s" % (fails["invalid_or_faulted"] or "none")); P("- exact fallbacks: %s" % (fails["exact_fallbacks"] or "none")); P("- unavailable inputs (typed slots): %s" % fails["unavailable_inputs"]); P("- **accounting invariant failures (over_release_events)**: %s" % (fails["invariant_failures_over_release"] or "none")); P("- R0 containment failures (PROOF CHECK): %s" % (fails["r0_containment_failures"] or "none")); P("- R1 / R2 reference points outside a certified interval by MORE than the reference's own rounding tolerance: %s" % (fails["reference_excursions_beyond_tolerance"] or "none"))
    P(""); P("## 6. References (frozen before scoring; never promoted)"); P("")
    cls = collections.Counter(r["class"] for r in refs.values()); P("- classes over the 46 cases: %s (R0 exact truth = proof check of containment; R1 / R2 provenance-bearing points = consistency only; R3 = no reference: accuracy UNKNOWN)." % dict(cls))
    r0 = rec["controls"]["r0_proof_checks"]; P("- R0 proof checks: %s" % (r0 or "no certified R0 cell"))
    P(""); P("## 7. Per-case explanations (GENERAL vs PLAIN; supported / suggestive / unresolved)"); P("")
    ex = jl(os.path.join(A, "EXPLANATIONS.jsonl")); P("| case | family | 20 s | 120 s |"); P("|---|---|---|---|")
    for case in man["cases"]:
        e20 = next((e for e in ex if e["case"] == case and e["stage"] == "primary_breadth"), {}); e120 = next((e for e in ex if e["case"] == case and e["stage"] == "primary_depth"), {})
        P("| %s | %s | **%s** — %s | **%s** — %s |" % (case, man["cases"][case]["family"], e20.get("label"), e20.get("explanation", "")[:160], e120.get("label"), e120.get("explanation", "")[:160]))
    P(""); P("Per-case mechanism reach (offered reduction; views / demand / fusion / two-axis / sparse as ACCEPTED_AND_REACHED, ACCEPTED_NOT_REACHED, NO_OP, DECLINED, NOT_SELECTED, UNKNOWN; planned vs actual rows; costs by phase; reserved vs sampled memory; stopped-at operation): `ANALYSIS/MECHANISMS.jsonl`, `ANALYSIS/CASES.jsonl`.")
    P(""); P("## 8. Null results (graveyard)"); P(""); P("- mechanism fired with no effect: %d entries" % len(grave["mechanism_no_effect"])); P("- ablation plan identical to GENERAL: %s" % [(a, len(c)) for a, c in grave["ablation_identical_to_general"]]); P("- families with identical GENERAL / PLAIN status at 20 s: %s" % [f for f, _ in grave["families_without_difference"]]); P("- %s" % grave["null_feature_comparisons"][0])
    P(""); P("## 9. Budget (nonnested receipts; this analysis job's receipt and the packaging receipt are added after this file)"); P("")
    P("- nonnested receipted total %.3f s of the 28,800 s envelope (remaining %.3f s); matrix-type %.3f s; preparation-type %.3f s (over the 5,000 s preparation allocation by %.3f s, drawn from the 1,436 s contingency by the 10 Nov authorization); %d receipts; raw overlapping receipt sum %.3f s (not the total); unresolved %s; duplicate receipts %s." % (budget["nonnested_receipted_total_s"], budget["remaining_envelope_s"], budget["matrix_type_s"], budget["preparation_type_s"], budget["preparation_over_cap_s"], budget["receipts"], budget["raw_receipt_sum_s_overlapping_not_the_total"], budget["other_unresolved"] or "none", budget["duplicate_receipts"] or "none"))
    P("- Uncharged interpreter exposure (human / agent reasoning, ad-hoc probes outside the supervisor) is UNKNOWN; no all-work bound is claimed.")
    P(""); P("## 10. What this run does and does not establish"); P("")
    P("- Every number above is one observation per (case, arm, budget) under the frozen configuration; differences are exploratory. Agreement between GENERAL, PLAIN and the ablations is NOT independent validation (shared code); agreement with libDAI / ADP / R1 / R2 references is a consistency observation; only R0 containment is a proof check.")
    P("- The cost prediction is CONDITIONAL (assumptions in every plan); planned-vs-actual rows are compared only where the whole plan executed (`prediction_scope`).")
    P("- No selector training, benchmark tuning or implementation list follows from this pass.")
    open(os.path.join(A, "REPORT_MATRIX.md"), "w").write("\n".join(L) + "\n")


if __name__ == "__main__":
    main(os.path.abspath(sys.argv[1]), os.path.abspath(sys.argv[2]) if len(sys.argv) > 2 else None)
