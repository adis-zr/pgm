"""Bounded census CORRECTION (review of 8 Nov 2026): recompute the derived records that the review found wrong, from the SAVED artifacts
only (plan_record.json, nodes.jsonl, cell.json, progress.json, CELLS_LEDGER, CENSUS_LEDGER). Writes review_2026-11-08/corrected/*.
Nothing numerical is rerun; no cell file is touched; originals stay in place.
    python -m adp.census_closeout.correct D"""
from __future__ import annotations
import os, sys, json, collections, math, itertools
HERE = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))); sys.path.insert(0, HERE)
PREV = os.path.join(HERE, "runs", "mdi_2026-10-28", "AGGREGATE_DP_2026-11-07")


def jl(p):
    return [json.loads(l) for l in open(p)] if os.path.exists(p) else []


def refines(fine, coarse):
    """partition `fine` (class index per state, -1 = zero) refines `coarse`: every fine class lies inside one coarse class."""
    m = {}
    for a, (f, c) in enumerate(zip(fine, coarse)):
        if f == -1 or c == -1:
            continue
        if f in m and m[f] != c:
            return False
        m[f] = c
    return True


def common_refinement_witness(raw, partitions):
    """partitions: list of class-index lists over `raw` states (-1 = zero). Returns (kind, need) where kind is 'discrete_input' if some
    input alone distinguishes every state, 'joint' if only a joint refinement of >= 2 non-discrete inputs is discrete, else 'not_full'."""
    counts = [len({c for c in cls if c >= 0}) for cls in partitions]
    if any(k == raw for k in counts):
        return "discrete_input", [i for i, k in enumerate(counts) if k == raw]
    for sz in range(2, len(partitions) + 1):
        for sub in itertools.combinations(range(len(partitions)), sz):
            live = [a for a in range(raw) if all(partitions[i][a] >= 0 for i in sub)]
            sigs = {tuple(partitions[i][a] for i in sub) for a in live}
            if len(sigs) == raw and len(live) == raw:
                return "joint", list(sub)
    return "not_full", None


def single_input_split(plan):
    """(source-factor single-input nodes, non-root message single-input nodes, root message single-input nodes, message output volume)."""
    F = M = MR = 0; vol_M = 0
    for nd in plan["nodes"]:
        if len(nd["inputs"]) == 1:
            if nd["inputs"][0][0] == "F":
                F += 1
            elif nd["parent"] is not None:
                M += 1; vol_M += nd["size"]
            else:
                MR += 1
    return F, M, MR, vol_M


def direct_two_term_payload(dx, pair_factor_entries):
    """scalar numbers of a direct separable representation of sum_x [unary(x) * prod_j f_j(x, s_j)] with pairwise-disjoint s_j:
    |D_x| terms x (one coefficient + one boundary vector per pair factor); markers / metadata excluded."""
    return dx * (1 + sum(e // dx for e in pair_factor_entries))


def main(D):
    out = os.path.join(D, "review_2026-11-08", "corrected"); os.makedirs(out, exist_ok=True)
    man = json.load(open(os.path.join(D, "CENSUS_MANIFEST.json"))); rows = jl(os.path.join(D, "CELLS_LEDGER.jsonl")); diag = {r["case"]: r for r in rows if r["stage"] == "diag"}
    prim = {(r["case"], int(r["budget_s"])): r for r in rows if r["stage"] == "primary"}; OPP = jl(os.path.join(D, "OPPORTUNITIES.jsonl")); changes = []
    # ---------------------------------------------------------------- (1) response partitions: common refinement, joint-refinement witnesses
    joint = []; discrete_input = []; unexplained = []; axes_total = 0; axes_compressed = 0; per_case = {}
    for case, r in diag.items():
        pp = os.path.join(D, r["out_dir"], "plan_record.json")
        if not os.path.exists(pp):
            continue
        plan = json.load(open(pp)); nodes = plan["nodes"]; sv = plan["source_views"]; red = json.load(open(os.path.join(D, r["out_dir"], "reduced_record.json")))
        fac_scope = {f["fid"]: f["scope"] for f in red["factors"]}
        def view_of(ref, w, nd):
            return sv["%d:%d" % (ref[1], w)]["cls"] if ref[0] == "F" else nodes[ref[1]]["views"][str(w)]["cls"]
        nc = 0; ncomp = 0; nj = 0; ndisc = 0
        for nd in nodes:
            for w in nd["scope"]:
                raw = len(red["dom"][str(w)]); outc = nd["views"][str(w)]; k_out = len(outc["reps"]); nc += 1
                if k_out < raw:
                    ncomp += 1
                incoming = [(ref, view_of(tuple(ref), w, nd)) for ref in nd["inputs"] if w in (fac_scope[ref[1]] if ref[0] == "F" else nodes[ref[1]]["scope"])]
                counts = [len({c for c in cls if c >= 0}) for _, cls in incoming]
                if k_out == raw and incoming:
                    kind, idx = common_refinement_witness(raw, [cls for _, cls in incoming])
                    if kind == "joint":
                        need = [list(incoming[i][0]) for i in idx]
                        order_ok = [[refines(incoming[i][1], incoming[j][1]) for j in range(len(incoming))] for i in range(len(incoming))]
                        joint.append({"case": case, "nid": nd["nid"], "axis": w, "raw": raw, "classes_per_input": [[list(ref), k] for (ref, _), k in zip(incoming, counts)], "classes_out": k_out, "minimal_joint_subset": need, "input_refines_input_matrix": order_ok, "largest_count_input_refines_all_others": any(all(order_ok[i]) for i in range(len(incoming)) if counts[i] == max(counts))}); nj += 1
                    elif kind == "discrete_input":
                        ndisc += 1; discrete_input.append({"case": case, "nid": nd["nid"], "axis": w, "raw": raw, "discrete_inputs": [list(incoming[i][0]) for i in idx]})
                    else:
                        unexplained.append({"case": case, "nid": nd["nid"], "axis": w, "raw": raw, "classes_per_input": counts})
        per_case[case] = {"axes": nc, "compressed": ncomp, "full_width_by_joint_refinement": nj, "full_width_with_a_discrete_input": ndisc}
        axes_total += nc; axes_compressed += ncomp
    json.dump({"rule": "an output axis is the COMMON REFINEMENT of the certified input partitions; full width arises either because some input is already discrete (sufficient, not necessary) or because several non-discrete partitions cross; 'finest_inputs' in the original records = largest class count, which need not refine the others", "axes_total": axes_total, "axes_compressed": axes_compressed, "cases_with_compression": sorted(c for c, v in per_case.items() if v["compressed"]), "joint_refinement_axes": len(joint), "joint_refinement_cases": sorted({j["case"] for j in joint}), "joint_refinement_witnesses": joint, "discrete_input_axes": len(discrete_input), "full_width_axes_neither_explanation": unexplained, "per_case": per_case}, open(os.path.join(out, "D4_common_refinement.json"), "w"), indent=1)
    changes.append({"finding": "D4 'finest input iff' is false", "source": "plan_record.json views of every diagnostic cell", "correction": "%d full-width axes in %s arise by JOINT refinement of non-discrete inputs; %d by a discrete input; field 'finest_inputs' documented as largest-class-count, not refinement order" % (len(joint), sorted({j["case"] for j in joint}), len(discrete_input))})
    # ---------------------------------------------------------------- (2) deterministic-source states: OBSERVED vs WITNESS
    det = []
    for o in OPP:
        if o["inspection"] != "deterministic_source_structure":
            continue
        s = o["source"]; has = bool((s.get("zeros") or 0) or (s.get("deterministic_factors_arity_ge2") or 0))
        det.append({"case": o["case"], "state_original": o["state"], "state_corrected": "WITNESS_FOUND" if has else "OBSERVED_NO_ZERO_NO_DETERMINISTIC_FACTOR", "zeros": s.get("zeros"), "deterministic_factors_arity_ge2": s.get("deterministic_factors_arity_ge2"), "reductions_applied": o["reductions_applied"]})
    json.dump({"rule": "a source census row is an OBSERVATION; WITNESS_FOUND requires exact zeros or a deterministic factor of arity >= 2 (some axis with exactly one nonzero per column)", "rows": det, "corrected_counts": dict(collections.Counter(d["state_corrected"] for d in det))}, open(os.path.join(out, "D5_deterministic_states.json"), "w"), indent=1)
    changes.append({"finding": "19 deterministic-source rows marked WITNESS_FOUND with neither zeros nor deterministic factors", "source": "OPPORTUNITIES.jsonl deterministic_source_structure rows", "correction": json.dumps(dict(collections.Counter(d["state_corrected"] for d in det)))})
    # ---------------------------------------------------------------- (3) single-input eliminations: source-factor vs message
    si = []
    for case, r in diag.items():
        pp = os.path.join(D, r["out_dir"], "plan_record.json")
        if not os.path.exists(pp):
            continue
        plan = json.load(open(pp)); F, M, MR, vol_M = single_input_split(plan)
        si.append({"case": case, "single_input_nodes_source_factor": F, "single_input_nodes_message": M, "single_input_root_nodes_message": MR, "message_output_volume": vol_M})
    json.dump({"rule": "a single-input bucket consumes either a SOURCE FACTOR (its cost is a source read, not an avoidable intermediate) or a MESSAGE (an intermediate whose storage could be avoided by fusion); the all-query contract requires the reverse contraction sum_s h(s) m(x,s), NOT residency of the table", "rows": si, "totals": {"F": sum(x["single_input_nodes_source_factor"] for x in si), "M_non_root": sum(x["single_input_nodes_message"] for x in si), "M_root": sum(x["single_input_root_nodes_message"] for x in si), "M_total_incl_roots": sum(x["single_input_nodes_message"] + x["single_input_root_nodes_message"] for x in si), "cases_with_any": sum(1 for x in si if x["single_input_nodes_source_factor"] + x["single_input_nodes_message"]), "cases_with_message_nodes": sum(1 for x in si if x["single_input_nodes_message"])}}, open(os.path.join(out, "D3_single_input_split.json"), "w"), indent=1)
    changes.append({"finding": "single-input eliminations not split by input kind; 'all queries force residency' too strong", "source": "plan_record.json inputs", "correction": "F=%d message=%d non-root + %d root = %d nodes; %d cases with any, %d with message nodes; requirement restated as the reverse contraction" % (sum(x["single_input_nodes_source_factor"] for x in si), sum(x["single_input_nodes_message"] for x in si), sum(x["single_input_root_nodes_message"] for x in si), sum(x["single_input_nodes_message"] + x["single_input_root_nodes_message"] for x in si), sum(1 for x in si if x["single_input_nodes_source_factor"] + x["single_input_nodes_message"]), sum(1 for x in si if x["single_input_nodes_message"]))})
    # ---------------------------------------------------------------- (4) rank-1 metric relabel: proxy vs direct payload for DBN_16 node 0
    rk = {}
    for case in ("DBN_16", "DBN_15", "DBN_12", "DBN_11"):
        r = diag.get(case); pp = os.path.join(D, r["out_dir"], "plan_record.json") if r else None
        if not (pp and os.path.exists(pp)):
            continue
        plan = json.load(open(pp)); nd = plan["nodes"][0]; red = json.load(open(os.path.join(D, r["out_dir"], "reduced_record.json"))); fac = {f["fid"]: f for f in red["factors"]}
        dx = len(red["dom"][str(nd["v"])]); pair = [f for t, f in nd["inputs"] if t == "F" and len(fac[f]["scope"]) == 2]; un = [f for t, f in nd["inputs"] if t == "F" and len(fac[f]["scope"]) == 1]
        payload = direct_two_term_payload(dx, [fac[f]["entries"] for f in pair])          # per eliminated state: one coefficient (unary x pinned) + one boundary vector per pair factor
        rk[case] = {"nid": 0, "v": nd["v"], "dom_v": dx, "pair_factors": len(pair), "unary_factors": len(un), "dense_core_entries": nd["size"], "saved_proxy_rank1_volume": plan["node_metrics"][0]["rank1_terms_volume_if_disjoint"], "direct_two_term_payload_numbers": payload, "note": "payload = |D_x| terms x (1 coefficient + one boundary vector per disjoint pair factor); the saved proxy multiplied the FULL input tables (which already include x) by |D_x| and is therefore conservative by ~2x here; markers / metadata excluded; messages consumed first at node %d" % (nd["parent"] if nd["parent"] is not None else -1), "consumer_first_at": nd["parent"]}
    json.dump({"rule": "the saved 'rank1_terms_volume_if_disjoint' is a size PROXY (|D_x| x sum of full input sizes), not an exact payload; separability is over disjoint input BLOCKS, which need not be single variables; a product of 22 two-term messages has 2^22 distributed terms, an expansion upper bound and NOT a minimal-rank proof", "dbn_node0": rk}, open(os.path.join(out, "D2_rank1_payload.json"), "w"), indent=1)
    changes.append({"finding": "'180 numbers' and the sequential 2,4,8 recurrence are wrong", "source": "DBN plan_record node 0 inputs / parent", "correction": "direct two-term payload %s; messages M0..M21 are consumed FIRST at node %s; expansion count is an upper bound, not a rank theorem" % ({c: v["direct_two_term_payload_numbers"] for c, v in rk.items()}, rk.get("DBN_16", {}).get("consumer_first_at"))})
    # ---------------------------------------------------------------- (5) Promedus_14 transition; completed-vs-active wall; 1aie/1qt9 lazy accounting
    def cell(case):
        r = diag[case]; od = os.path.join(D, r["out_dir"]); return json.load(open(os.path.join(od, "cell.json"))), jl(os.path.join(od, "nodes.jsonl")), json.load(open(os.path.join(od, "plan_record.json"))), (json.load(open(os.path.join(od, "progress.json"))) if os.path.exists(os.path.join(od, "progress.json")) else {})
    cj, ev, plan, prog = cell("Promedus_14"); fw = {e["nid"]: e for e in ev if e["phase"] == "forward"}
    first_lazy = next((e for e in sorted(fw.values(), key=lambda e: e["nid"]) if e["executed_format"] == "lazy"), None)
    cascade = [e["nid"] for e in fw.values() if e["executed_format"] == "lazy"]
    p14 = {"root_node": plan["nodes"][-1]["nid"], "root_scope": plan["nodes"][-1]["scope"], "root_planned_core_entries": plan["nodes"][-1]["size"], "root_bag_rows": plan["nodes"][-1]["bag"], "first_lazy_node": (first_lazy or {}).get("nid"), "first_lazy_reason": (first_lazy or {}).get("abandoned_sparse"), "planned_core_of_first_lazy": plan["nodes"][(first_lazy or {}).get("nid", 0)]["size"] if first_lazy else None, "lazy_nodes_observed": sorted(cascade), "sparse_nodes_observed": sum(1 for e in fw.values() if e["executed_format"] == "sparse"), "current_operation_at_stop": (cj.get("stop") or {}).get("current"), "counters_at_stop": (cj.get("attempts") or [{}])[-1].get("counters"), "completed_forward_wall_sum_s": sum(e["wall_s"] for e in fw.values()), "cell_complete_response_s": cj["complete_response_s"], "note": "the requesting node at the stop is the scalar root; the expensive dependency is the lazy chain starting at the first lazy node (sparse join over the rows cap); completed-node wall sums exclude the active unfinished work"}
    protein = {}
    for case in ("1aie", "1qt9", "1jer", "1npl"):
        cj, ev, plan, prog = cell(case); c = (cj.get("attempts") or [{}])[-1].get("counters") or {}; fwe = [e for e in ev if e["phase"] == "forward"]
        lazy_first = next((e for e in fwe if e["executed_format"] == "lazy"), None)
        protein[case] = {"status": cj["status"], "lazy_evals_at_stop": c.get("lazy_evals", 0), "lazy_hits_at_stop": c.get("lazy_hits", 0), "lazy_evictions_at_stop": c.get("lazy_evictions", 0), "lazy_recomputes_counter": "NOT INSTRUMENTED (initialised, never incremented): its zero is not a measurement", "bytes_vals_last_snapshot": prog.get("bytes_vals"), "bytes_vals_at_last_completed_node": (fwe[-1]["bytes_vals"] if fwe else None), "growth_bytes": (prog.get("bytes_vals") or 0) - (fwe[-1]["bytes_vals"] if fwe else 0), "growth_equals_evals_x_176": ((prog.get("bytes_vals") or 0) - (fwe[-1]["bytes_vals"] if fwe else 0)) == 176 * c.get("lazy_evals", 0), "completed_forward_wall_sum_s": sum(e["wall_s"] for e in fwe), "cell_complete_response_s": cj["complete_response_s"], "nodes_completed": len(fwe), "nodes_planned": len(plan["nodes"]), "current_operation_at_stop": (cj.get("stop") or {}).get("current")}
    p120 = {c: (json.load(open(os.path.join(D, prim[(c, 120)]["out_dir"], "cell.json"))).get("attempts") or [{}])[-1].get("counters") for c in ("1aie", "1qt9", "1jer", "1npl")}
    for c in protein:
        protein[c]["primary_120s_counters"] = {k: (p120[c] or {}).get(k) for k in ("lazy_evals", "lazy_hits", "lazy_evictions", "downgraded_to_lazy")}
    json.dump({"promedus_14": p14, "protein_lazy_accounting": protein, "rule": "lazy_evals counts every lazy entry evaluation including FIRST evaluations; lazy_hits counts memo hits; lazy_evictions counts evictions; repeated-after-eviction evaluations are NOT separately instrumented; completed-node wall sums exclude the active unfinished operation; the recorded 'current' node is the outer requester, possibly waiting on lazy predecessors"}, open(os.path.join(out, "C_execution_corrections.json"), "w"), indent=1)
    changes.append({"finding": "Promedus_14 'node 404 is a 4M sparse core'; Protein 'almost no reuse = recomputation'", "source": "nodes.jsonl / cell.json / progress.json of the diagnostic cells; primary 120 s counters", "correction": "root node %s is scalar (core %d); first lazy node %s (%s); %d lazy nodes cascade; Protein prefixes: all evaluated lazy values retained (growth = evals x 176 B) = first-time evaluation, not recomputation; 1jer at 120 s has %s hits" % (p14["root_node"], p14["root_planned_core_entries"], p14["first_lazy_node"], (p14["first_lazy_reason"] or "")[:60], len(cascade), protein["1jer"]["primary_120s_counters"]["lazy_hits"])})
    # ---------------------------------------------------------------- (6) DIABETES exact timings; checker-largest counts incl. reductions / publication; checker-incomplete by budget
    def cj_of(r):
        return json.load(open(os.path.join(D, r["out_dir"], "cell.json")))
    dia = {}
    for k, r in (("primary_20s", prim[("DIABETES", 20)]), ("primary_120s", prim[("DIABETES", 120)]), ("diagnostic_20s", diag["DIABETES"])):
        c = cj_of(r); a = (c.get("attempts") or [{}])[-1]; dia[k] = {"status": c["status"], "t_first_checked_output_s": c.get("t_first_complete_output_s"), "complete_response_s": c["complete_response_s"], "checker_s": a.get("phases_s", {}).get("checker"), "publish_s": c["phases_s"].get("publish")}
    hist = []
    for r in jl(os.path.join(PREV, "CELLS_LEDGER.jsonl")):
        if r["case"] == "DIABETES" and r["arm"] == "AGGREGATE_DP_V1" and r.get("config_key") == "full":
            c = json.load(open(os.path.join(PREV, r["out_dir"], "cell.json"))); a = (c.get("attempts") or [{}])[-1]; hist.append({"stage": r["stage"], "repetition": r.get("repetition"), "complete_response_s": c["complete_response_s"], "checker_s": a.get("phases_s", {}).get("checker"), "publish_s": c["phases_s"].get("publish")})
    largest = {}
    for key, sel in (("primary_20s", [prim[(c["case"], 20)] for c in man["cases"]]), ("primary_120s", [prim[(c["case"], 120)] for c in man["cases"]]), ("diagnostic_20s", [diag[c["case"]] for c in man["cases"]])):
        n = 0; ck = 0; exc = []
        for r in sel:
            c = cj_of(r)
            if c["status"] != "CERTIFIED":
                continue
            n += 1; a = (c.get("attempts") or [{}])[-1]; ph = {k: v for k, v in c["phases_s"].items() if isinstance(v, (int, float))}; ph.update({k: v for k, v in a.get("phases_s", {}).items() if isinstance(v, (int, float)) and k in ("forward", "backward", "checker")})
            big = max(ph, key=ph.get)
            if big == "checker":
                ck += 1
            else:
                exc.append({"case": r["case"], "largest": big, "phases": {k: round(v, 3) for k, v in ph.items()}})
        largest[key] = {"certified": n, "checker_largest_among_all_recorded_phases": ck, "exceptions": exc}
    inc = {"20s_primary": [c["case"] for c in man["cases"] if cj_of(prim[(c["case"], 20)])["status"] == "SOLVER_COMPLETE_CHECKER_INCOMPLETE"], "120s_primary": [c["case"] for c in man["cases"] if cj_of(prim[(c["case"], 120)])["status"] == "SOLVER_COMPLETE_CHECKER_INCOMPLETE"], "20s_diagnostic_stopped_in_backward_before_checking": [c["case"] for c in man["cases"] if ((cj_of(diag[c["case"]]).get("stop") or {}).get("current") or [None])[0] == "backward"]}
    json.dump({"diabetes": {"repaired": dia, "frozen_historical_context_not_contemporaneous": hist, "statement": "an observed deadline regression at 20 s whose causal contribution (repair overhead in checking / publication vs run-to-run variation) is NOT isolated by these non-contemporaneous observations; the primary LATE_OUTPUT stands; the diagnostic certification is corroboration, not a replacement"}, "checker_largest": largest, "checker_incomplete_by_budget": inc}, open(os.path.join(out, "A_execution_timings.json"), "w"), indent=1)
    changes.append({"finding": "DIABETES 'variation not repair effect'; '19.3 s'; 'checker largest in every certified cell'; regimes not budget-specific", "source": "cell.json of DIABETES (repaired + frozen), all certified cells, stop records", "correction": "exact timings recorded; causal attribution withdrawn; checker largest among ALL phases in %s; checker-incomplete sets by budget %s" % ({k: "%d/%d" % (v["checker_largest_among_all_recorded_phases"], v["certified"]) for k, v in largest.items()}, inc)})
    # ---------------------------------------------------------------- (7) 1aie compressed axes
    pc = per_case.get("1aie", {}); changes.append({"finding": "Protein range '216-237 of ~360' excluded 1aie", "source": "plan_record views", "correction": "1aie %d of %d axes compressed; 1jer/1npl/1qt9: %s" % (pc.get("compressed"), pc.get("axes"), {c: "%d/%d" % (per_case[c]["compressed"], per_case[c]["axes"]) for c in ("1jer", "1npl", "1qt9") if c in per_case})})
    # ---------------------------------------------------------------- (8) accounting reconciliation
    led = jl(os.path.join(D, "CENSUS_LEDGER.jsonl")); rc = {r["jid"]: r for r in led if r["kind"] == "RECEIPT"}; st = [r for r in led if r["kind"] == "START"]
    known = sum(rc[r["jid"]]["wall_s"] for r in st if r["jid"] in rc); unres = [r for r in st if r["jid"] not in rc]
    outer_minus_sup = sum((r.get("outer_wall_s") or 0) - (r.get("supervisor_wall_s") or 0) for r in rows if r.get("outer_wall_s") is not None and r.get("supervisor_wall_s") is not None)
    cl = jl(os.path.join(D, "review_2026-11-08", "CORRECTION_LEDGER.jsonl")); crc = {r["jid"]: r for r in cl if r["kind"] == "RECEIPT"}; cst = [r for r in cl if r["kind"] == "START"]
    corr_known = sum(crc[r["jid"]]["wall_s"] for r in cst if r["jid"] in crc and not crc[r["jid"]].get("cleanup_unresolved")); corr_unres = [r for r in cst if r["jid"] not in crc or crc[r["jid"]].get("cleanup_unresolved")]
    acct = {"census_ledger": {"starts": len(st), "receipts": len(rc), "known_receipt_sum_s": known, "unresolved_starts": [r["job"] for r in unres], "final_package_receipt": rc.get(next((r["jid"] for r in st if r["job"] == "package_r2_final"), ""), {}).get("wall_s"), "stale_snapshots_retired": {"REPORT.md section Budget 4811.45 s": "as-of report_r2 (extract_final START pending)", "BUDGET_LEDGER.json 4816.605 s": "as-of extract_final START pending charged at its 604 s maximum", "final_reconciliation 4217.154 s": "as-of after package_r2_final receipt; equals the complete-ledger receipt sum below within rounding"}},
            "uncharged_or_unwrapped": {"aborted_stage_launches_amendment_1": {"count": 2, "charge": "UNKNOWN and NOT bounded by evidence (second review): the tracebacks carry no timestamps; both log files share the modification second 02:26:09Z, which bounds the interval BETWEEN the two launches, not their durations; the pre-cell window from those logs to primary_started (02:27:45Z) is 96 s and is the only evidenced envelope for both launches plus the repair edit -- not exempt", "evidence": "primary_aborted_launch_1.log / diag_aborted_launch_1.log mtimes; primary_started.txt"}, "stage_runner_nonnested_overhead": {"measured_outer_minus_supervisor_wall_s_over_cells": outer_minus_sup, "stage_runner_own_wall": "NOT RECEIPTED (the stage runner was not run under the supervisor; its nonnested remainder beyond the cells is unknown; the cell-level outer-minus-supervised difference above is a measured lower bound of that remainder)", "double_counting_rule": "cell supervised walls are the receipts; the remainder is added once, never the nested cell walls again"}, "ad_hoc_python_reconciliation_calls": "two Python invocations that rewrote BUDGET_LEDGER.json's final_reconciliation field ran outside any supervisor (disclosed in that field); charge UNKNOWN and not bounded by evidence"},
            "correction_pass_ledger": {"ceiling_s": 600.0, "starts": len(cst), "receipts": len(crc), "known_receipt_sum_s": corr_known, "unresolved_starts": [r["job"] for r in corr_unres], "as_of": "this extractor's own START (its receipt is pending by construction while it runs); the authoritative total is the final CORRECTION_LEDGER.jsonl"},
            "compliance_statement": "census pass: the 155 receipts total %.9f s; adding the measured cell-level outer-minus-supervised remainder (%.6f s) gives %.6f s; the stage runners' own remainder is UNKNOWN (bounded above by the stage wall-clock minus cell receipts, see stage_wallclock below); the two aborted launches and two ad-hoc reconciliation calls are UNKNOWN and not bounded by evidence; exact all-attempt compliance is therefore QUALIFIED, not exact; every bound is far inside the 10,800 s ceiling" % (known, outer_minus_sup, known + outer_minus_sup)}
    # stage wall-clock envelope from the started/finished files (upper bound on runner + cells)
    import datetime
    def ts(p):
        try:
            s = open(os.path.join(D, p)).read().split()[1]; return datetime.datetime.strptime(s, "%Y-%m-%dT%H:%M:%SZ")
        except Exception:
            return None
    env = {}
    for stg in ("primary", "diag"):
        a, b = ts(stg + "_started.txt"), ts(stg + "_finished.txt")
        if a and b:
            cells_s = sum((r.get("supervisor_wall_s") or 0) for r in rows if r["stage"] == stg); env[stg] = {"wallclock_s": (b - a).total_seconds(), "cell_receipts_s": cells_s, "runner_remainder_upper_bound_s": (b - a).total_seconds() - cells_s}
    acct["stage_wallclock"] = env; acct["approximate_envelope_all_attempt_s"] = known + sum(v["runner_remainder_upper_bound_s"] for v in env.values()) + 96.0
    acct["approximate_envelope_note"] = "APPROXIMATE ENVELOPE, not a formal bound: known receipts + stage wall-clock remainders (which already contain the cell receipts' outer-minus-supervised remainder) + the 96 s pre-cell window containing both aborted launches; it OMITS the two unmeasured ad-hoc reconciliation calls, which no evidence bounds"
    json.dump(acct, open(os.path.join(out, "ACCOUNTING_RECONCILIATION.json"), "w"), indent=1)
    changes.append({"finding": "stale 4811.45 / 4816.605 totals; 'EXACT' claim; 5.84 s outer-minus-supervised overhead; unwrapped launches exempted", "source": "CENSUS_LEDGER.jsonl, CELLS_LEDGER.jsonl outer_wall_s, stage started/finished files", "correction": "155/155 receipts sum %.3f s; +%.3f s measured remainder; runner remainders bounded by stage wall-clock (%s); compliance QUALIFIED" % (known, outer_minus_sup, {k: round(v["runner_remainder_upper_bound_s"], 1) for k, v in env.items()})})
    # ---------------------------------------------------------------- (9) amendment wording
    changes.append({"finding": "amendment_1 wording: 'a2 with a1 predecessor' vs actual new-ID a1 cells with empty predecessors", "source": "CELLS_LEDGER.jsonl attempt/predecessors fields; cells/ directory names", "correction": "after the re-freeze the harness hash changed, so every cell id changed; all 138 rows are attempt a1 with empty predecessors; the two pre-repair directories (CSP_11 primary d9241f06…, diag 40fddbed…) are EMPTY attempts of the superseded manifest's cell ids, preserved on disk, never run; see AMENDMENTS.json amendment_1_correction"})
    # ---------------------------------------------------------------- (10) prose-level findings (evidence = the corrected analysis + the reviewer's audits) and the supervisor repair
    changes += [
        {"finding": "D1: 'compressed child axis = the old global-support counterexample'; pruning stated as a row-level semijoin for identity views only", "source": "adp/census/diag_cell.py referenced_child_entries are keyed by mapped child CORE-CLASS tuples; reviewer rules_audit.txt item 4 + rules_audit_witnesses.json unused_compressed_class_controls", "correction": "masks are class keys (a class with a dead representative and a live member is marked referenced); conditional whole-class demand pruning lemma recorded with its four hypotheses; identity views sufficient not necessary; capped scans certify nothing; counts remain observations (ANALYSIS_E_corrected.md E3; REPORT_corrected.md D1)"},
        {"finding": "E1: 'no saving unless terms can be re-factorised into fewer terms'; 2^k expansion presented as a rank obstruction", "source": "DBN plan_record topology (parent of nodes 0-21 = 22); reviewer rules_audit.txt item 1 (Gray-code conditioning illustration)", "correction": "withdrawn: a factored representation can save materialisation / residency / repeated arithmetic without reducing rank; 2^22 is an expansion upper bound; closed-contract obligations (block growth, term growth, every internal marker carried) stated (ANALYSIS_E_corrected.md E1)"},
        {"finding": "E2: 'the all-query contract forces residency'; fusion costs 'one extra pass'", "source": "reviewer rules_audit.txt item 2; adp/engine.py lazy format (counterexample to forced residency)", "correction": "requirement restated as the reverse contraction sum_s h(s) m(x,s); fusion exact with the reverse chain rule but nested lazy recomputation is not a guaranteed one extra pass (ANALYSIS_E_corrected.md E2)"},
        {"finding": "E4: all-marker proportionality 'iff' stated without scope", "source": "reviewer rules_audit.txt item 3", "correction": "iff scoped to the one-profile-per-class representation under its arbitrary-exterior contract; fixed singleton summaries may admit other exact decoders (ANALYSIS_E_corrected.md E4)"},
        {"finding": "E5: 'any representation that shrinks the program shrinks the proof proportionally'", "source": "reviewer REVIEW.txt section 4 (project lesson); phase records show recognition / source reductions / publication dominating some certified cells", "correction": "withdrawn without a cost theorem (ANALYSIS_E_corrected.md E5)"},
        {"finding": "supervisor: Popen before START and before try/finally -> absent executable leaves neither START nor RECEIPT", "source": "review_2026-11-08/supervisor_controls/supervise_BEFORE_580e0fbe.py; tests/test_adp_census.py::test_review_frozen_supervisor_reproduces_the_launch_gap (gap reproduced on the frozen copy)", "correction": "adp/census/supervise.py: START fsynced before launch; launch inside the receipt-producing try/finally (LAUNCH_FAILED receipt); SPAWNED pid/pgid after success; no receipt with a live child; controls: absent executable, ordered START/SPAWNED/RECEIPT, timeout kill, SIGTERM after launch, SIGTERM racing the launch (receipts review_2026-11-08/supervisor_controls/pytest_after_repair_r2.txt, 8 passed). PROSPECTIVE: the census measurements were taken under the before-version whose 155 receipts are complete"},
        {"finding": "provenance: package records HEAD 0d2080a9; the later 580e0fbe tree and the E-MDI-39 append were not evidenced by the package", "source": "review_2026-11-08/SOURCE_LINEAGE_prior_0d2080a9.json; review_2026-11-08/E_MDI_39_ledger_excerpt.md (copied from docs/LEDGER_ADDITIONS_mdi_capacity_2026-11-02.md with that file's sha256 and the commit)", "correction": "the correction package's SOURCE_LINEAGE.json names the commit at packaging time, which includes the docs append; the package proves the state of the committed tree at that commit and nothing about later commits (the post-package commit adds only PACKAGE_RECORD / SOURCE_LINEAGE / the package receipt)"}]
    # ---------------------------------------------------------------- (11) SECOND review (8 Nov 2026, packet CENSUS_R2_REVIEW_AND_TARGETED_PATCH): one lifecycle defect + three annotations
    changes += [
        {"finding": "R2 supervisor: a SIGTERM between Popen returning and the pgid assignment left the child alive at supervisor exit and charged ~10 s of a ~20 s exit (reviewer's deterministic trace-hook control)", "source": "review_2026-11-08/supervisor_controls/BOUNDARY_CONTROL_before_after.json (BEFORE copy supervise_BEFORE_3414b222.py reproduces the gap with real signals / real psutil; AFTER copy kills + reaps the child and charges the wall after cleanup); reviewer's candidate patch kept for reference as REVIEWER_candidate_supervise.patch (not applied verbatim)", "correction": "adp/census/supervise.py: cancellation deferred while START / child handle / identity are established (window opens before the START write) and acted upon right after with the child owned; group identity = child pid (start_new_session); finalisation kills + reaps BEFORE measuring the charged wall and is not interruptible; CLEANUP_UNRESOLVED recorded explicitly if the child cannot be reaped; an error after a successful launch (e.g. SPAWNED write failure) is SUPERVISOR_ERROR_AFTER_LAUNCH with the child stopped. Controls (tests/test_adp_census.py, real psutil): deterministic boundary SIGTERM, pre-launch SIGTERM, injected SPAWNED write failure (+0.2 s reap charged), before-copy gap reproduction, plus the earlier absent-executable / ordered records / timeout / post-launch SIGTERM / random early race (now also checking the receipt pid without SPAWNED): 12 passed"},
        {"finding": "R2 annotation A: '13 cases with compression, 33 without' conflated the original census's compression-STOP witness count with any-compression", "source": "corrected/D4_common_refinement.json cases_with_compression (15: incl. ALARM 2/70, MILDEW 3/113) vs OPPORTUNITIES.jsonl response_partition_stop WITNESS_FOUND (13)", "correction": "15 cases have some response compression, 31 none; 13 is the stop-witness count (ANALYSIS_E_corrected.md E4; REPORT_corrected.md D4)"},
        {"finding": "R2 annotation B: ANALYSIS_E_corrected E1 said '90 for all four DBNs'", "source": "corrected/D2_rank1_payload.json", "correction": "DBN_11 82 (consumer 20), DBN_12 86 (21), DBN_15 86 (21), DBN_16 90 (22)"},
        {"finding": "R2 annotation C: the outside PACKAGE_RECORD is an integrity record, not a supervisory job receipt; 'upper bound' all-attempt figure and '< 1 s' aborted-launch bounds were not evidenced", "source": "CORRECTION_LEDGER.jsonl package job RECEIPT (committed after the package); aborted-launch log mtimes carry no per-launch duration", "correction": "package job receipts copied as sidecars <zip>.PACKAGE_JOB_RECEIPT.json next to each archive; 'upper_bound_all_attempt_s' renamed approximate_envelope_all_attempt_s with its omissions stated; aborted launches and ad-hoc calls marked UNKNOWN and not bounded by evidence"}]
    json.dump(changes, open(os.path.join(out, "REVIEW_FINDING_TO_CORRECTION_MAP.json"), "w"), indent=1)
    print(json.dumps({"joint_refinement_axes": len(joint), "det_states": dict(collections.Counter(d["state_corrected"] for d in det)), "single_input_totals": {"F": sum(x["single_input_nodes_source_factor"] for x in si), "M": sum(x["single_input_nodes_message"] for x in si)}, "p14_first_lazy": p14["first_lazy_node"], "checker_largest": {k: "%d/%d" % (v["checker_largest_among_all_recorded_phases"], v["certified"]) for k, v in largest.items()}, "ledger_sum": round(known, 3), "remainder": round(outer_minus_sup, 3)}))


if __name__ == "__main__":
    main(os.path.abspath(sys.argv[1]))
