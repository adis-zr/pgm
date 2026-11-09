"""Census extraction: CASES.jsonl (48 slots), OPERATIONS.jsonl (every planned node of every diagnostic plan), OPPORTUNITIES.jsonl (fixed
inspections x cases with explicit states), RECONCILIATION.json (historical frozen statuses vs the repaired primary statuses), BUDGET_LEDGER.json
(every START/RECEIPT once; unresolved starts at their max permitted charge). Numbers come from saved artifacts only.
    python -m adp.census_closeout.extract D"""
from __future__ import annotations
import os, sys, json, collections, math
HERE = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))); sys.path.insert(0, HERE)
from adp.census import run as RUN
PREV = RUN.PREV


def load_jsonl(p):
    return [json.loads(l) for l in open(p)] if os.path.exists(p) else []


def cell_json(D, row):
    p = os.path.join(D, row["out_dir"], "cell.json") if row.get("out_dir") else None
    return json.load(open(p)) if p and os.path.exists(p) else {}


def main(D):
    man = json.load(open(os.path.join(D, "CENSUS_MANIFEST.json"))); rows = load_jsonl(os.path.join(D, "CELLS_LEDGER.jsonl"))
    old = load_jsonl(os.path.join(PREV, "CELLS_LEDGER.jsonl")); cases = {c["case"]: c for c in man["cases"]}
    def old_status(case, stage):
        r = [x for x in old if x["case"] == case and x["arm"] == "AGGREGATE_DP_V1" and x["stage"] == stage and x.get("config_key") == "full" and x.get("repetition") == 0]
        return (r[0]["status"], ((r[0].get("stop") or {}).get("kind")), r[0].get("complete_response_s")) if r else (None, None, None)
    prim = {(r["case"], int(r["budget_s"])): r for r in rows if r["stage"] == "primary"}; diag = {r["case"]: r for r in rows if r["stage"] == "diag"}
    # ---------------------------------------------------------------- CASES
    C = []; recon = []
    def cellrec(r):
        if r is None:
            return {"status": "NOT_RUN", "reason": "no row"}
        cj = cell_json(D, r); att = (cj.get("attempts") or [{}])[-1]; chk = cj.get("checker") or {}; red = cj.get("reductions") or {}; pg = cj.get("program") or {}
        return {"cell_id": r["cell_id"], "attempt": r.get("attempt"), "predecessors": r.get("predecessors"), "status": r["status"], "outcome": r["outcome"], "requested_s": r["budget_s"], "supervisor_wall_s": r["supervisor_wall_s"], "complete_response_s": r.get("complete_response_s"), "t_checked_answer_delivered_s": r.get("t_first_complete_output_s"),
                "phases_s": {**(cj.get("phases_s") or {}), **{"forward": att.get("phases_s", {}).get("forward"), "backward": att.get("phases_s", {}).get("backward"), "checker": att.get("phases_s", {}).get("checker")}}, "checker_status": chk.get("status"), "checker_wall_s": chk.get("wall_s"), "checker_counters": chk.get("counters"), "precision_attempts": [a.get("precision") for a in (cj.get("attempts") or [])],
                "peak_tree_rss_bytes": r.get("peak_tree_rss_bytes"), "rss_samples": r.get("rss_samples"), "stop": cj.get("stop"), "downgraded_to_lazy": (att.get("counters") or {}).get("downgraded_to_lazy", 0) or att.get("downgraded_to_lazy", 0), "lazy_evals": (att.get("counters") or {}).get("lazy_evals", 0),
                "reductions": red, "reduced_hash": cj.get("reduced_hash"), "program": {k: pg.get(k) for k in ("nodes", "components", "formats_planned", "core_entries_total", "bag_rows_total", "largest_core", "largest_bag", "structure_hash", "order_capped_at", "views_nontrivial_axes", "raw_boundary_product_total", "single_input_eliminations", "disjoint_input_nodes", "compressed_axes", "axes_total")},
                "formats_executed": att.get("formats_executed"), "counters": att.get("counters"), "certified": cj.get("certified"), "reason": cj.get("reason")}
    for c in man["cases"]:
        p20 = cellrec(prim.get((c["case"], 20))); p120 = cellrec(prim.get((c["case"], 120))); dg = cellrec(diag.get(c["case"]))
        dj = cell_json(D, diag[c["case"]]) if c["case"] in diag else {}
        h20 = old_status(c["case"], "P20"); h120 = old_status(c["case"], "P120")
        same_plan = (p20.get("program", {}).get("structure_hash") == p120.get("program", {}).get("structure_hash")) if (p20.get("program", {}).get("structure_hash") and p120.get("program", {}).get("structure_hash")) else None
        rec = {"slot": c["case"], "accessible": True, "family": c["family"], "source": {"raw_model_sha256": c["raw_model_sha256"], "raw_evidence_sha256": c["raw_evidence_sha256"], "census": dj.get("source_census")}, "primary_20s": p20, "primary_120s": p120, "diagnostic_20s": dg,
               "reduced_hash_20_vs_120_same": (p20.get("reduced_hash") == p120.get("reduced_hash")) if (p20.get("reduced_hash") and p120.get("reduced_hash")) else None, "plan_hash_20_vs_120_same": same_plan,
               "historical": {"P20": {"status": h20[0], "stop": h20[1], "complete_response_s": h20[2]}, "P120": {"status": h120[0], "stop": h120[1], "complete_response_s": h120[2]}},
               "unknown": [k for k, v in (("diagnostic_plan", dj.get("program")), ("checker_per_node_work", None)) if v is None]}
        C.append(rec)
        recon.append({"case": c["case"], "family": c["family"], "historical_P20": h20[0], "historical_P20_stop": h20[1], "repaired_20s": p20["status"], "repaired_20s_stop": (p20.get("stop") or {}).get("kind"), "historical_P120": h120[0], "historical_P120_stop": h120[1], "repaired_120s": p120["status"], "repaired_120s_stop": (p120.get("stop") or {}).get("kind"),
                      "change_20": ("same" if h20[0] == p20["status"] else "%s -> %s" % (h20[0], p20["status"])), "change_120": ("same" if h120[0] == p120["status"] else "%s -> %s" % (h120[0], p120["status"])), "lazy_downgrades_20": p20.get("downgraded_to_lazy"), "lazy_downgrades_120": p120.get("downgraded_to_lazy"), "lazy_evals_20": p20.get("lazy_evals"), "lazy_evals_120": p120.get("lazy_evals")})
    for s in man["inaccessible_slots"]:
        C.append({"slot": s["case"], "accessible": False, "family": s["family"], "reason": s["reason"], "primary_20s": {"status": "INPUT_UNAVAILABLE"}, "primary_120s": {"status": "INPUT_UNAVAILABLE"}, "diagnostic_20s": {"status": "INPUT_UNAVAILABLE"}})
    with open(os.path.join(D, "CASES.jsonl"), "w") as f:
        for r in C:
            f.write(json.dumps(r, default=str) + "\n")
    json.dump({"rule": "historical = frozen campaign AGGREGATE_DP_2026-11-07 primary rows (code hash b915a293); repaired = this pass (code hash da5b2c49); one observation each; statuses compared, times NOT paired measurements", "rows": recon,
               "summary": {"20s": dict(collections.Counter(r["change_20"] for r in recon)), "120s": dict(collections.Counter(r["change_120"] for r in recon))}}, open(os.path.join(D, "RECONCILIATION.json"), "w"), indent=1)
    # ---------------------------------------------------------------- OPERATIONS (from the diagnostic plan + node events)
    nops = 0
    with open(os.path.join(D, "OPERATIONS.jsonl"), "w") as f:
        for case, r in diag.items():
            od = os.path.join(D, r["out_dir"]); pp = os.path.join(od, "plan_record.json")
            if not os.path.exists(pp):
                f.write(json.dumps({"case": case, "state": "PLAN_UNAVAILABLE", "reason": "diagnostic cell stopped before the plan was persisted", "status": r["status"]}) + "\n"); continue
            plan = json.load(open(pp)); met = {x["nid"]: x for x in plan["node_metrics"]}; ev = load_jsonl(os.path.join(od, "nodes.jsonl")); fw = {e["nid"]: e for e in ev if e["phase"] == "forward"}; bw = {e["nid"]: e for e in ev if e["phase"] == "backward"}
            for nd in plan["nodes"]:
                m = met[nd["nid"]]; e = fw.get(nd["nid"]); b = bw.get(nd["nid"])
                rec = {"case": case, "nid": nd["nid"], "v": nd["v"], "dom_v": m["dom_v"], "parent": nd["parent"], "comp": nd["comp"], "inputs": nd["inputs"], "input_scopes": m["input_scopes"], "scope": nd["scope"], "boundary_variables": len(nd["scope"]), "raw_boundary_domain_product": m["raw_boundary_domain_product"], "response_class_product": m["response_class_product"],
                       "planned_core_entries": m["planned_core_entries"], "planned_bag_rows": m["planned_bag_rows"], "planned_format": nd["fmt"], "axes": m["axes"], "single_input_elimination": m["single_input_elimination"], "inputs_have_disjoint_boundary_scopes": m["inputs_have_disjoint_boundary_scopes"], "rank1_terms_volume_if_disjoint": m["rank1_terms_volume_if_disjoint"], "any_zero_input": m["any_zero_input"],
                       "observed": None if e is None else {"executed_format": e["executed_format"], "forward_wall_s": e["wall_s"], "forward_counters": e["counters_delta"], "core_entries_stored": e["core_entries_stored"], "sparse_rows": e["sparse_rows"], "sparse_out_rows": e["sparse_out_rows"], "abandoned_sparse": e["abandoned_sparse"], "referenced_child_entries": e["referenced_child_entries"], "bytes_vals_after": e["bytes_vals"],
                                                           "backward_wall_s": (b or {}).get("wall_s"), "backward_counters": (b or {}).get("counters_delta"), "bytes_adj_after_backward": (b or {}).get("bytes_adj"), "pending_flushes_after_backward": (b or {}).get("pending_flushes")},
                       "state": ("OBSERVED_FORWARD_AND_BACKWARD" if (e and b) else ("OBSERVED_FORWARD_ONLY" if e else "NOT_REACHED")), "unique_entry_count_note": "entries stored = unique core entries for dense / sparse formats; for lazy formats unique counts are NOT derivable from totals that include recomputation (unavailable)"}
                f.write(json.dumps(rec, default=str) + "\n"); nops += 1
    # ---------------------------------------------------------------- OPPORTUNITIES (fixed inspections on every case)
    opp = []
    for case, r in diag.items():
        od = os.path.join(D, r["out_dir"]); pp = os.path.join(od, "plan_record.json"); cj = cell_json(D, r)
        if not os.path.exists(pp):
            for insp in ("dead_local_rows", "disjoint_input_rank1", "single_input_elimination_aggregate", "response_partition_stop", "deterministic_source_structure", "cost_classification"):
                opp.append({"case": case, "inspection": insp, "state": "NOT_REACHED", "reason": "plan not persisted (%s)" % r["status"]})
            continue
        plan = json.load(open(pp)); met = plan["node_metrics"]; ev = load_jsonl(os.path.join(od, "nodes.jsonl")); fw = {e["nid"]: e for e in ev if e["phase"] == "forward"}; observed = len(fw); total = len(met)
        # 1. dead local rows: child entries never referenced by the parent (one-level global-infeasibility witness) -- from observed forward events
        dead = []; checked = 0
        for e in fw.values():
            for cid, rr in e["referenced_child_entries"].items():
                checked += 1
                if rr["referenced"] < rr["child_entries"]:
                    ch = met[int(cid)]; dead.append({"child_nid": int(cid), "parent_nid": e["nid"], "child_entries": rr["child_entries"], "referenced": rr["referenced"], "dead": rr["child_entries"] - rr["referenced"], "child_format": ch["planned_format"], "child_has_compressed_axis": any(a["compressed"] for a in ch["axes"])})
        opp.append({"case": case, "inspection": "dead_local_rows", "question": "do locally supported (upward-complete) child entries include contexts the parent never references (hence globally infeasible one level up)?", "state": ("WITNESS_FOUND" if dead else ("NO_WITNESS_IN_COMPLETED_SCAN" if observed == total else "SCAN_CAPPED")), "extent": {"parent_child_pairs_checked": checked, "nodes_observed": observed, "nodes_planned": total},
                    "witnesses": sorted(dead, key=lambda d: -d["dead"])[:20], "total_dead_entries": sum(d["dead"] for d in dead), "obstruction": "a dead entry may be a class REPRESENTATIVE whose class has live members: global pruning inside a response view needs a whole-root / view-compatibility proof (recorded, not applied); witnesses flag child_has_compressed_axis", "cost": "O(bag rows) boolean mask inside the diagnostic cell (charged to its wall)"})
        # 2. disjoint-input rank-1 structure
        r1 = [m for m in met if m["inputs_have_disjoint_boundary_scopes"] and len(m["inputs"]) > 1 and m["rank1_terms_volume_if_disjoint"] is not None]
        gain = [m for m in r1 if m["rank1_terms_volume_if_disjoint"] < m["planned_core_entries"]]
        opp.append({"case": case, "inspection": "disjoint_input_rank1", "question": "does an intermediate retain product structure (bucket inputs with pairwise-disjoint boundary scopes => output = sum over x of |D_x| rank-1 terms) usable without expansion?", "state": ("WITNESS_FOUND" if gain else ("RULE_APPLIES_NO_VOLUME_GAIN" if r1 else "NO_WITNESS_IN_COMPLETED_SCAN")),
                    "extent": {"nodes_inspected": total}, "nodes_with_disjoint_inputs": len(r1), "nodes_with_volume_gain": len(gain), "witnesses": [{"nid": m["nid"], "v": m["v"], "planned_core_entries": m["planned_core_entries"], "rank1_terms_volume": m["rank1_terms_volume_if_disjoint"], "ratio": m["planned_core_entries"] / m["rank1_terms_volume_if_disjoint"]} for m in sorted(gain, key=lambda m: -m["planned_core_entries"])[:20]],
                    "downstream_requirement": "the parent multiplies this message with other inputs and sums its own x; a sum-of-rank-1-terms representation is closed under restriction and under products with other rank-1 terms only if the term count stays bounded (it multiplies); the reverse pass needs per-entry adjoints of the stored object", "proof_obligation": "exact: the identity sum_x prod_j f_j(x, S_j) with disjoint S_j is a sum of |D_x| separable terms (algebraic); affordability of the downstream product / reverse operations is unmeasured"})
        # 3. single-input eliminations: forward needs only an aggregate, reverse needs each entry
        si = [m for m in met if m["single_input_elimination"] and m["parent"] is not None]
        opp.append({"case": case, "inspection": "single_input_elimination_aggregate", "question": "does a consumer need the whole intermediate or only aggregates? (a bucket with ONE input marginalizes it; forward needs sum_x, reverse needs every entry for the marker derivatives)", "state": ("RULE_APPLIES_NO_VOLUME_GAIN" if si else "NO_WITNESS_IN_COMPLETED_SCAN"), "extent": {"nodes_inspected": total},
                    "nodes": len(si), "volume_of_single_input_outputs": sum(m["planned_core_entries"] for m in si), "obligation": "forward sufficiency = aggregate; reverse (all variables queried) needs the pre-aggregation entries at every requested marker: the aggregate alone is NOT sufficient for the all-query contract; a fused child+parent operation would avoid STORING the child core but not visiting its bag rows"})
        # 4. where response partitions stop compressing and why
        stops = []
        for m in met:
            for a in m["axes"]:
                if not a["compressed"] and any(k < a["raw"] for _, k in a["classes_per_input"]):
                    stops.append({"nid": m["nid"], "axis": a["w"], "raw": a["raw"], "classes_per_input": a["classes_per_input"], "finest_inputs": a["finest_inputs"], "classes_out": a["classes_out"]})
        comp = sum(1 for m in met for a in m["axes"] if a["compressed"]); allax = sum(len(m["axes"]) for m in met)
        opp.append({"case": case, "inspection": "response_partition_stop", "question": "where do response partitions cease to compress, and which input is responsible?", "state": ("WITNESS_FOUND" if stops else ("NO_WITNESS_IN_COMPLETED_SCAN" if allax else "NOT_REACHED")), "extent": {"axes_inspected": allax, "axes_compressed": comp},
                    "witnesses": stops[:30], "count": len(stops), "note": "exact: an axis stays uncompressed iff some input has every state in its own class (finest_inputs); numerical equality of generated values is never used"})
        # 5. deterministic / zero source structure
        sc = cj.get("source_census") or {}; red = cj.get("reductions") or {}
        opp.append({"case": case, "inspection": "deterministic_source_structure", "question": "does the source carry deterministic mappings / zeros that exact reductions exploited or left?", "state": ("WITNESS_FOUND" if (sc.get("deterministic_factors") or sc.get("zeros")) else "NO_WITNESS_IN_COMPLETED_SCAN"),
                    "source": {"factors": sc.get("factors"), "entries": sc.get("entries"), "zeros": sc.get("zeros"), "deterministic_factors": sc.get("deterministic_factors")}, "reductions_applied": red.get("steps"), "free_vars": [red.get("free_original"), red.get("free_reduced")], "remaining": {"factors": red.get("factors_remaining"), "entries": red.get("entries_remaining")}, "recognition_capped": (red.get("recognition") or {}).get("capped")})
        # 6. cost classification (observational)
        tot_fw = sum(e["wall_s"] for e in fw.values()); recomp = sum((e["counters_delta"] or {}).get("lazy_evictions", 0) for e in fw.values()); lazy = sum((e["counters_delta"] or {}).get("lazy_evals", 0) for e in fw.values())
        att = (cj.get("attempts") or [{}])[-1]; ph = att.get("phases_s", {}); chk = (cj.get("checker") or {})
        opp.append({"case": case, "inspection": "cost_classification", "state": ("OBSERVED" if fw else "NOT_REACHED"), "status": r["status"], "planned_volume": {"core_entries": sum(m["planned_core_entries"] for m in met), "bag_rows": sum(m["planned_bag_rows"] for m in met), "raw_boundary_products": sum(m["raw_boundary_domain_product"] for m in met)},
                    "realized": {"nodes_forward_observed": observed, "of": total, "forward_wall_s": tot_fw, "entries_computed": sum((e["counters_delta"] or {}).get("entries_computed", 0) for e in fw.values()), "bag_rows_visited": sum((e["counters_delta"] or {}).get("bag_rows", 0) for e in fw.values()), "lazy_evals": lazy, "lazy_evictions_recompute_pressure": recomp, "downgraded_to_lazy": sum((e["counters_delta"] or {}).get("downgraded_to_lazy", 0) for e in fw.values())},
                    "setup": {"source_reductions_s": (cj.get("phases_s") or {}).get("source_reductions"), "plan_s": (cj.get("phases_s") or {}).get("plan")}, "checker": {"status": chk.get("status"), "wall_s": chk.get("wall_s"), "counters": chk.get("counters")}, "phases_s": {"forward": ph.get("forward"), "backward": ph.get("backward"), "checker": ph.get("checker")},
                    "largest_observed_node": (max(fw.values(), key=lambda e: e["wall_s"])["nid"] if fw else None), "earliest_sharp_rise": _earliest_rise(fw, met), "classification_note": "observational: 'unavoidable under the CURRENT representation' = planned volume; 'repeated work' = lazy evictions / recomputation; 'residency' = bytes_vals/adj trajectories in nodes.jsonl; 'setup' = reductions + plan; 'checker' = its record; not a lower bound"})
    with open(os.path.join(D, "OPPORTUNITIES.jsonl"), "w") as f:
        for o in opp:
            f.write(json.dumps(o, default=str) + "\n")
    # ---------------------------------------------------------------- budget
    led = load_jsonl(os.path.join(D, "CENSUS_LEDGER.jsonl")); rec = {r["jid"]: r for r in led if r["kind"] == "RECEIPT"}; total = 0.0; by_scope = collections.defaultdict(float); unresolved = []; jobs = []
    for r in led:
        if r["kind"] == "START":
            if r["jid"] in rec:
                w = rec[r["jid"]]["wall_s"]; total += w; by_scope[r["scope"]] += w; jobs.append({"job": r["job"], "scope": r["scope"], "wall_s": round(w, 3), "outcome": rec[r["jid"]]["outcome"]})
            else:
                unresolved.append({"job": r["job"], "scope": r["scope"], "max_permitted_charge_s": r.get("max_permitted_charge_s")}); total += (r.get("max_permitted_charge_s") or 0.0); by_scope[r["scope"]] += (r.get("max_permitted_charge_s") or 0.0)
    B = {"ceiling_s": RUN.CEILING_S, "envelopes_s": RUN.ENVELOPES, "rule": "every executed process job of this pass runs under adp.census.supervise; a START without a RECEIPT is charged at its max permitted charge and listed UNRESOLVED; the stage runner and this extraction are jobs too", "total_charged_s": round(total, 3), "by_scope_s": {k: round(v, 3) for k, v in by_scope.items()}, "unresolved_starts": unresolved,
         "exact_compliance": ("EXACT (every start has a receipt)" if not unresolved else "UNRESOLVED (%d starts without receipts charged at their maxima)" % len(unresolved)), "within_ceiling": total <= RUN.CEILING_S, "jobs": jobs, "disclosed_uncharged": "none known: all probes of this pass ran under the supervisor; the two aborted stage launches of amendment_1 (< 1 s, NameError before any process spawn) are the only unwrapped executions"}
    json.dump(B, open(os.path.join(D, "BUDGET_LEDGER.json"), "w"), indent=1)
    print(json.dumps({"cases": len(C), "operations": nops, "opportunities": len(opp), "budget_total_s": B["total_charged_s"], "unresolved": len(unresolved), "recon_20": json.load(open(os.path.join(D, "RECONCILIATION.json")))["summary"]}))


def _earliest_rise(fw, met):
    """first node (in elimination order) whose forward wall exceeds 10x the median of the nodes before it, or whose bytes_vals jumps by > 25 % of the final"""
    if len(fw) < 3:
        return None
    seq = [fw[k] for k in sorted(fw)]; walls = [e["wall_s"] for e in seq]; final_bytes = max(e["bytes_vals"] for e in seq) or 1
    import statistics
    for i in range(2, len(seq)):
        medprev = statistics.median(walls[:i])
        if walls[i] > 10 * max(medprev, 1e-4) and walls[i] > 0.05:
            return {"nid": seq[i]["nid"], "kind": "forward_wall", "wall_s": walls[i], "median_before_s": medprev, "planned_core_entries": met[seq[i]["nid"]]["planned_core_entries"]}
        if i > 0 and seq[i]["bytes_vals"] - seq[i - 1]["bytes_vals"] > 0.25 * final_bytes:
            return {"nid": seq[i]["nid"], "kind": "residency_jump", "bytes_vals": seq[i]["bytes_vals"], "planned_core_entries": met[seq[i]["nid"]]["planned_core_entries"]}
    return None


if __name__ == "__main__":
    main(os.path.abspath(sys.argv[1]))
