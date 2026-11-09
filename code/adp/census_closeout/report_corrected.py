"""Corrected REPORT for the bounded census correction (review of 8 Nov 2026). Starts from the PRESERVED original REPORT.md and applies the
reviewer's corrections as explicit, asserted replacements (each original passage must be present exactly once), inserting the corrected
derived records from review_2026-11-08/corrected/*.json. Writes review_2026-11-08/REPORT_corrected.md. Nothing numerical is rerun.
    python -m adp.census_closeout.report_corrected D"""
from __future__ import annotations
import os, sys, json, re
HERE = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))); sys.path.insert(0, HERE)


def jl(p):
    return [json.loads(l) for l in open(p)] if os.path.exists(p) else []


def replace_once(text, old, new, label):
    n = text.count(old)
    assert n == 1, "passage for %s found %d times" % (label, n)
    return text.replace(old, new)


def main(D):
    R = os.path.join(D, "review_2026-11-08"); C = os.path.join(R, "corrected")
    rep = open(os.path.join(D, "REPORT.md")).read()
    A = json.load(open(os.path.join(C, "A_execution_timings.json"))); CX = json.load(open(os.path.join(C, "C_execution_corrections.json")))
    D2 = json.load(open(os.path.join(C, "D2_rank1_payload.json"))); D3 = json.load(open(os.path.join(C, "D3_single_input_split.json")))
    D4 = json.load(open(os.path.join(C, "D4_common_refinement.json"))); D5 = json.load(open(os.path.join(C, "D5_deterministic_states.json")))
    ACC = json.load(open(os.path.join(C, "ACCOUNTING_RECONCILIATION.json"))); man = json.load(open(os.path.join(D, "CENSUS_MANIFEST.json")))
    rows = jl(os.path.join(D, "CELLS_LEDGER.jsonl")); diag = {r["case"]: r for r in rows if r["stage"] == "diag"}; prim = {(r["case"], int(r["budget_s"])): r for r in rows if r["stage"] == "primary"}
    # ------------------------------------------------------------------ preface
    preface = ("\n> **CORRECTED VERSION (review of 8 November 2026; amendment_2).** This document is the original REPORT.md with the reviewer's corrections applied "
               "as explicit replacements; the original is preserved unchanged at `REPORT.md` and copied to `review_2026-11-08/REPORT_prior_580e0fbe.md`. Every "
               "measured table (A, B, C, D1, D2, D5 columns) is reproduced from the same saved cells; corrected derived records are in `review_2026-11-08/corrected/`. "
               "**No new inference panel was run, no cell was repeated or edited, the numerical source is unchanged (frozen-set hash da5b2c49… verified before and after), "
               "and no inference rule was implemented.** Passages marked ⟂ replace a withdrawn statement. Labels: [observation] read from records; [inferred] my reading; "
               "[conditional] a mathematical statement with its hypotheses; [unmeasured proposal] no runtime evidence.\n")
    first_nl = rep.index("\n"); rep = rep[:first_nl + 1] + preface + rep[first_nl + 1:]
    # ------------------------------------------------------------------ A: DIABETES + stop kinds
    old = ("Status changes 20 s: {\"same\": 45, \"CERTIFIED -> LATE_OUTPUT\": 1}; 120 s: {\"same\": 46}. Each cell is ONE observation on the repaired code; a status change between the frozen and the repaired code on a deadline-stopped case can also reflect ordinary run-to-run variation near the deadline, not only the repair.")
    d = A["diabetes"]["repaired"]; h = A["diabetes"]["frozen_historical_context_not_contemporaneous"]
    new = (old + "\n\n⟂ **Stop kinds.** 'Every other status equals the frozen status' holds for the top-level label only: 14 full-arm stop kinds changed VALUE_CAP → DEADLINE (5 at 20 s, 9 at 120 s; table above and section B). "
           "**DIABETES [observation].** Primary 20 s: first fully checked output at %.7f s, complete response %.7f s → LATE_OUTPUT (the status stands). Diagnostic 20 s: checked output %.7f s, complete %.7f s (corroboration, not a replacement observation). Primary 120 s: %.7f s. "
           "Frozen historical context (NOT contemporaneous): %s. Repaired checker %.2f–%.2f s, publication %.2f–%.2f s. The cause of the 20 s regression (added task-binding work in checking and publication vs run-to-run variation) is **not isolated** by these observations; the earlier assertion that it is 'variation, not a repair effect' is withdrawn."
           % (d["primary_20s"]["t_first_checked_output_s"], d["primary_20s"]["complete_response_s"], d["diagnostic_20s"]["t_first_checked_output_s"], d["diagnostic_20s"]["complete_response_s"], d["primary_120s"]["complete_response_s"],
              "; ".join("%s rep %s: %.2f s (checker %.2f, publish %.2f)" % (x["stage"], x["repetition"], x["complete_response_s"], x["checker_s"] or 0, x["publish_s"] or 0) for x in h),
              min(v["checker_s"] for v in d.values()), max(v["checker_s"] for v in d.values()), min(v["publish_s"] for v in d.values()), max(v["publish_s"] for v in d.values())))
    rep = replace_once(rep, old, new, "A status changes")
    # ------------------------------------------------------------------ C: column label + corrected cost attribution
    rep = replace_once(rep, "| forward s (incl. partial node) |", "| forward s (sum over COMPLETED nodes; the active unfinished operation is EXCLUDED when the stop is in forward) |", "C header")
    act = []
    for c in man["cases"]:
        r = diag[c["case"]]; od = os.path.join(D, r["out_dir"]); cj = json.load(open(os.path.join(od, "cell.json")))
        if cj["status"] == "CERTIFIED":
            continue
        ev = jl(os.path.join(od, "nodes.jsonl")); pre = sum(v for k, v in cj["phases_s"].items() if isinstance(v, (int, float)) and k in ("startup_imports", "parse", "source_reductions", "plan"))
        comp = sum(e["wall_s"] for e in ev); last_t = max((e.get("t_s") or 0) for e in ev) if ev else None; stop = (cj.get("stop") or {}).get("current")
        active = (cj["complete_response_s"] - last_t) if (last_t is not None and last_t < 1e6) else None
        act.append({"case": c["case"], "status": cj["status"], "stop": stop, "pre_numeric_s": pre, "completed_nodes_wall_s": comp, "nodes_completed": len({(e["phase"], e["nid"]) for e in ev}), "active_operation_elapsed_s": active, "complete_response_s": cj["complete_response_s"], "checker_s": (cj.get("attempts") or [{}])[-1].get("phases_s", {}).get("checker")})
    json.dump({"rule": "completed-node wall sums EXCLUDE the active unfinished operation; active-operation elapsed = cell complete-response time minus the timestamp of the last completed node event (outer requester; inner lazy dependencies are NOT attributed); where the producer completed (stop = null, SOLVER_COMPLETE_CHECKER_INCOMPLETE) the active operation is the checker and the elapsed figure includes the checker's wall", "rows": act}, open(os.path.join(C, "C_active_operation_split.json"), "w"), indent=1)
    tbl = ["| case | status | operation at stop | pre-numeric s | completed-node wall s | active operation elapsed s (unattributed inside) | checker s | complete response s |", "|---|---|---|---|---|---|---|---|"]
    for a in act:
        tbl.append("| %s | %s | %s | %.2f | %.2f | %s | %s | %.2f |" % (a["case"], a["status"], json.dumps(a["stop"]), a["pre_numeric_s"], a["completed_nodes_wall_s"], ("%.2f" % a["active_operation_elapsed_s"]) if a["active_operation_elapsed_s"] is not None else "n/a", ("%.2f" % a["checker_s"]) if a["checker_s"] else "—", a["complete_response_s"]))
    L = A["checker_largest"]; inc = A["checker_incomplete_by_budget"]; p14 = CX["promedus_14"]; pr = CX["protein_lazy_accounting"]
    exc = "; ".join("%s: %s" % (k, ", ".join("%s (%s)" % (e["case"], e["largest"]) for e in v["exceptions"])) for k, v in L.items())
    old = "Separation of the four quantities: PLAN SIZE"
    new = ("### C-corrected. Where the time went, by budget and dependency ⟂\n\n"
           "**Three quantities kept separate [observation]:** completed-prefix wall (the table's forward column), elapsed time of the ACTIVE unfinished operation, and unmeasured inner attribution. The recorded 'current' node is the outer requester and may be waiting on expensive lazy predecessors. Over the %d non-certified diagnostic cells (`corrected/C_active_operation_split.json`):\n\n%s\n\n"
           "**Checker-incomplete sets are budget-specific [observation]:** 20 s primary: %s; 120 s primary: %s (Segmentation_13 certifies at 120 s). 20 s diagnostics of %s stop in the BACKWARD pass and never start checking. CSP_13 and MUNIN1 were omitted by the earlier four-regime list and ObjectDetection was counted twice; the regimes are not a partition of the 24 cells.\n\n"
           "**Checker as largest phase [observation]:** the checker exceeds forward and backward individually in every certified cell; among ALL recorded phases (incl. startup, parse, source reductions, plan, publication) it is largest in %d/%d primary-20 s, %d/%d primary-120 s and %d/%d diagnostic certifications. Exceptions: %s.\n\n"
           "**Promedus_14 [observation]:** node %d is the scalar ROOT (scope %s, %d planned core entry, %d bag rows); the transition is node %d (%s; planned core %s entries), after which %d further nodes execute lazily because a child has no complete sparse support (%d sparse, %d lazy nodes in the observed prefix); the root's demand on that chain is where the stop occurs (lazy evals %d, hits %d). The earlier description of node 404 as a 4 M-entry sparse core is withdrawn.\n\n"
           "**Protein lazy accounting [observation]:** 1aie prefix %d lazy evaluations, %d hits, %d evictions; retained-value growth equals evaluations × 176 B: %s. 1qt9: %d / %d / %d, growth = evals × 176 B: %s. These prefixes evaluate NEW entries; they are not evidence of recomputation. The `lazy_recomputes` counter is never incremented (not instrumented); its zero is not a measurement. At 120 s: 1aie %s, 1qt9 %s, 1jer %s, 1npl %s (evals / hits / evictions) — 1jer's reuse is substantial, so low reuse is not a family property.\n\n"
           % (len(act), "\n".join(tbl), inc["20s_primary"], inc["120s_primary"], inc["20s_diagnostic_stopped_in_backward_before_checking"],
              L["primary_20s"]["checker_largest_among_all_recorded_phases"], L["primary_20s"]["certified"], L["primary_120s"]["checker_largest_among_all_recorded_phases"], L["primary_120s"]["certified"], L["diagnostic_20s"]["checker_largest_among_all_recorded_phases"], L["diagnostic_20s"]["certified"], exc,
              p14["root_node"], p14["root_scope"], p14["root_planned_core_entries"], p14["root_bag_rows"], p14["first_lazy_node"], p14["first_lazy_reason"], "{:,}".format(p14["planned_core_of_first_lazy"]), p14["counters_at_stop"]["lazy_nodes"] - 1, p14["counters_at_stop"]["sparse_nodes"], p14["counters_at_stop"]["lazy_nodes"], p14["counters_at_stop"]["lazy_evals"], p14["counters_at_stop"]["lazy_hits"],
              pr["1aie"]["lazy_evals_at_stop"], pr["1aie"]["lazy_hits_at_stop"], pr["1aie"]["lazy_evictions_at_stop"], pr["1aie"]["growth_equals_evals_x_176"], pr["1qt9"]["lazy_evals_at_stop"], pr["1qt9"]["lazy_hits_at_stop"], pr["1qt9"]["lazy_evictions_at_stop"], pr["1qt9"]["growth_equals_evals_x_176"],
              *["%s / %s / %s" % (pr[c]["primary_120s_counters"]["lazy_evals"], pr[c]["primary_120s_counters"]["lazy_hits"], pr[c]["primary_120s_counters"]["lazy_evictions"]) for c in ("1aie", "1qt9", "1jer", "1npl")]))
    rep = replace_once(rep, old, new + old, "C separation paragraph")
    # ------------------------------------------------------------------ D1 obstruction paragraph
    i0 = rep.index("Obstruction (recorded, not applied):"); i1 = rep.index("\n", i0)
    new = ("⟂ **Interpretation [observation + conditional].** The recorded masks are over mapped child CORE-CLASS keys after the view map, not raw representative states; a class with a dead representative and a live member is marked referenced. The compressed-axis flag (MUNIN1 node 120) is therefore NOT the old global-support counterexample. "
           "Conditional whole-class demand pruning (reviewer's lemma, `rules_audit.txt` item 4; exact controls in `rules_audit_witnesses.json`): if (i) every subsequent semantic consumer's COMPLETE positive support is known, (ii) the consumer's boundary views refine the child's relevant views, (iii) the demand set records the child class of EVERY positive consumer row, and (iv) query markers are preserved, then a child class absent from the demand set contributes zero to every root value and every original-query derivative, and zeroing it is exact. Identity views are sufficient for (ii), not necessary. "
           "Capped or partial scans certify nothing; the counts above are OBSERVATIONS, not pruning certificates; no pruning is implemented.")
    rep = rep[:i0] + new + rep[i1:]
    # ------------------------------------------------------------------ D2 proof-obligation paragraph
    i0 = rep.index("Proof obligation (algebraic, exact): sum_x"); i1 = rep.index("\n", i0); k = D2["dbn_node0"]
    new = ("⟂ **Metric relabelled [correction].** The column 'rank-1 volume' is the saved PROXY `rank1_terms_volume_if_disjoint` = |D_x| × Σ(full input table sizes); the input tables already include x, so the proxy over-counts. For the DBN initial stars a DIRECT two-term payload (per eliminated state: one coefficient + one boundary vector per disjoint pair factor) needs %s scalar numbers before markers and metadata (saved proxy %s; first consumer node %s). Ratios are regenerated only where the direct payload is well defined (binary stars of source pair factors); elsewhere the proxy stands as a proxy. "
           "Separability is over disjoint input BLOCKS (not necessarily single variables); a later factor crossing blocks grows a block. **Topology [observation]:** DBN_16 nodes 0–21 each consume source factors only and all have parent node %d, which is the FIRST consumer of the 22 two-term messages; the earlier sequential 2, 4, 8, … narrative is withdrawn. A full distributed product has 2^22 terms — an expansion UPPER BOUND for one representation, not a minimal-rank proof; a factored representation can save materialisation and repeated arithmetic without reducing rank. "
           "**[conditional]** the local identity sum_x ∏_j f_j(x, S_j) = Σ_x coefficient_x × ∏_j (block vector)_j is exact; a closed contract must track block growth, term-count growth, and carry EVERY internal marker of the input messages into the term factors. **[unmeasured]** any downstream contraction schedule, reverse-pass cost and checker cost."
           % ({c: v["direct_two_term_payload_numbers"] for c, v in k.items()}, {c: v["saved_proxy_rank1_volume"] for c, v in k.items()}, {c: v["consumer_first_at"] for c, v in k.items()}, k["DBN_16"]["consumer_first_at"]))
    rep = rep[:i0] + new + rep[i1:]
    # ------------------------------------------------------------------ D3 table + paragraph
    hdr = "| case | state | single-input nodes | volume of their outputs (core entries) |"
    i0 = rep.index(hdr); i1 = rep.index("For these nodes the forward consumer needs only sum_x"); i2 = rep.index("\n", i1)
    byc = {r["case"]: r for r in D3["rows"]}; opp = {o["case"]: o for o in jl(os.path.join(D, "OPPORTUNITIES.jsonl")) if o["inspection"] == "single_input_elimination_aggregate"}
    t = ["| case | state | single-input nodes consuming a SOURCE FACTOR | consuming a MESSAGE (non-root) | root with a single message input | volume of the message-consuming outputs (core entries) |", "|---|---|---|---|---|---|"]
    for c in man["cases"]:
        r = byc[c["case"]]; t.append("| %s | %s | %d | %d | %d | %d |" % (c["case"], opp[c["case"]]["state"], r["single_input_nodes_source_factor"], r["single_input_nodes_message"], r["single_input_root_nodes_message"], r["message_output_volume"]))
    T = D3["totals"]
    new = ("\n".join(t) + "\n\n⟂ **Split [observation]:** %d single-input nodes consume a SOURCE FACTOR (a source read, not an avoidable intermediate), %d non-root nodes consume a MESSAGE, plus %d roots whose single input is a message (%d message-consuming in all); %d cases have single-input nodes, %d have message-consuming ones; ASIA's are source-only. "
           "**Requirement restated [conditional]:** for a message child m(x, s) with incoming adjoint h(s), the all-query contract requires the reverse contraction N_x = Σ_s h(s) m(x, s), which may be evaluated by an explicit scan, streaming, recomputation or a proved structured aggregate; it does NOT force residency of the table (the lazy engine is a counterexample). The forward aggregate Σ_x m(x, s) alone is generally insufficient. Fusion into the parent is exact with the matching reverse chain rule, but nested lazy recomputation is not guaranteed to cost 'one extra pass'."
           % (T["F"], T["M_non_root"], T["M_root"], T["M_total_incl_roots"], T["cases_with_any"], T["cases_with_message_nodes"]))
    rep = rep[:i0] + new + rep[i2:]
    # ------------------------------------------------------------------ D4 header + paragraph + joint witnesses
    rep = replace_once(rep, "| example (nid, axis, classes per input, finest input) |", "| example (nid, axis, classes per input, LARGEST-CLASS-COUNT input — does NOT determine refinement order) |", "D4 header")
    i0 = rep.index("Exact: an output axis stays at full width iff"); i1 = rep.index("\n", i0)
    jw = D4["joint_refinement_witnesses"]; percase = {}
    for j in jw:
        percase.setdefault(j["case"], []).append(j)
    t = ["| case | full-width axes by JOINT refinement (no discrete input) | largest-count input refines all others (count) | example (nid, axis, raw states, classes per input → out, minimal joint subset) |", "|---|---|---|---|"]
    for c in sorted(percase):
        js = percase[c]; e = js[0]
        t.append("| %s | %d | %d | nid %d axis %d: %d states; %s → %d; needs %s |" % (c, len(js), sum(1 for j in js if j["largest_count_input_refines_all_others"]), e["nid"], e["axis"], e["raw"], ", ".join("%s %d" % (ref, k) for ref, k in e["classes_per_input"]), e["classes_out"], e["minimal_joint_subset"]))
    pc = D4["per_case"]
    new = ("⟂ **Rule [conditional, exact]:** the output partition along an axis is the COMMON REFINEMENT of the certified input partitions. A full-width output arises either because some input is already discrete (sufficient, NOT necessary) or because several non-discrete partitions cross. Of %s inspected axes, %s are compressed — in %d cases (%s) SOME axis is compressed and in %d none; the original census's 13 is its narrower compression-STOP witness count (ALARM 2/70 and MILDEW 3/113 have compressed axes without a stop witness), not the any-compression count; %s full-width axes have a discrete input; **%d full-width axes in %s have NO discrete input** (`corrected/D4_common_refinement.json`, with the minimal joint subset and the input-refines-input matrix for each):\n\n%s\n\n"
           "Protein compression by case: %s (the earlier range '216–237 of ~360' did not describe 1aie). The saved field `finest_inputs` is the LARGEST-CLASS-COUNT input and is retained under that meaning. "
           "**[conditional]** all-marker proportionality is necessary and sufficient for the chosen one-profile-per-class representation under its declared arbitrary-exterior contract; it is not necessary for every exact summary of the fixed singleton task (a value-plus-first-derivative representation or another exact decoder can suffice). Numerical equality of generated values remains unsafe on its own. **[observation]** no missed symbolic identity was found; the %d joint-refinement axes are where one would have to act."
           % ("{:,}".format(D4["axes_total"]), "{:,}".format(D4["axes_compressed"]), len(D4["cases_with_compression"]), ", ".join(D4["cases_with_compression"]), 46 - len(D4["cases_with_compression"]), "{:,}".format(D4["discrete_input_axes"]), len(jw), sorted(percase), "\n".join(t),
              ", ".join("%s %d/%d" % (c, pc[c]["compressed"], pc[c]["axes"]) for c in ("1aie", "1jer", "1npl", "1qt9")), len(jw)))
    rep = rep[:i0] + new + rep[i1:]
    # ------------------------------------------------------------------ D5 states + corrected column
    cnt = D5["corrected_counts"]; st = {r["case"]: r["state_corrected"] for r in D5["rows"]}
    rep = replace_once(rep, "States over the 46 cases: {\"WITNESS_FOUND\": 46}.", "States over the 46 cases (ORIGINAL, stale): {\"WITNESS_FOUND\": 46}. ⟂ **Corrected typed states:** %s — a row is a structural WITNESS only if it has exact zeros or a deterministic factor of arity ≥ 2; the %d rows with neither are relabelled OBSERVED_NO_ZERO_NO_DETERMINISTIC_FACTOR (their source-census values stand as observations; see the last column; `corrected/D5_deterministic_states.json` lists each changed row with its source record)." % (json.dumps(cnt), cnt.get("OBSERVED_NO_ZERO_NO_DETERMINISTIC_FACTOR", 0)), "D5 states")
    hdr = "| case | factors | entries | exact zeros | deterministic factors (arity ≥ 2; recomputed) | reductions applied | free vars original → reduced | remaining factors / entries | recognition capped |"
    i0 = rep.index(hdr); i1 = rep.index("\n\n", i0); block = rep[i0:i1].split("\n")
    block[0] = block[0] + " corrected state |"; block[1] = block[1] + "---|"
    for k in range(2, len(block)):
        case = block[k].split("|")[1].strip(); block[k] = block[k] + " %s |" % st[case]
    rep = rep[:i0] + "\n".join(block) + rep[i1:]
    rep = replace_once(rep, "| deterministic_source_structure | 0 | 0 | 0 | 0 | 46 |", "| deterministic_source_structure (corrected) | 0 | %d (OBSERVED_NO_ZERO_NO_DETERMINISTIC_FACTOR) | 0 | 0 | %d |" % (cnt.get("OBSERVED_NO_ZERO_NO_DETERMINISTIC_FACTOR", 0), cnt.get("WITNESS_FOUND", 0)), "D6 row")
    # ------------------------------------------------------------------ E: replace with the corrected analysis
    i0 = rep.index("## E. Mathematical questions"); i1 = rep.index("## Budget (separate 10,800 s ceiling")
    ana = open(os.path.join(R, "ANALYSIS_E_corrected.md")).read(); ana = ana[ana.index("\n") + 1:]
    rep = rep[:i0] + "## E. Corrected analysis ⟂ (replaces the original section E, preserved in REPORT.md / ANALYSIS_E.md)\n" + ana.replace("\n## ", "\n### ") + "\n" + rep[i1:]
    # ------------------------------------------------------------------ Budget + amendments
    i0 = rep.index("## Budget (separate 10,800 s ceiling"); i1 = rep.index("Amendments:"); i2 = rep.index("\n", i1)
    cl = jl(os.path.join(R, "CORRECTION_LEDGER.jsonl")); crc = {r["jid"]: r for r in cl if r["kind"] == "RECEIPT"}; cst = [r for r in cl if r["kind"] == "START"]
    corr_known = sum(crc[r["jid"]]["wall_s"] for r in cst if r["jid"] in crc); corr_unres = [r["job"] for r in cst if r["jid"] not in crc]
    cl_ = ACC["census_ledger"]; un = ACC["uncharged_or_unwrapped"]; sw = ACC["stage_wallclock"]
    am = json.load(open(os.path.join(D, "AMENDMENTS.json")))
    new = ("## Budget ⟂ (separate 10,800 s ceiling; corrected accounting — `corrected/ACCOUNTING_RECONCILIATION.json`)\n\n"
           "**Authoritative:** the complete append-only CENSUS_LEDGER.jsonl has %d STARTs and %d RECEIPTs (every start resolved); the receipts sum to **%.9f s**. The final package receipt (%.6f s) lies outside the archive it describes and is included in that sum. "
           "**Retired as final values (retained as as-of snapshots):** %s. "
           "**Known uncharged / unwrapped work (the all-attempt rule exempts none of it):** measured cell-level outer-minus-supervised remainder %.9f s (added once; never the nested cell walls again); the stage runners' own remainder is NOT receipted and is bounded above by stage wall-clock minus cell receipts (primary %.1f s, diag %.1f s); the two aborted stage launches of amendment_1 are UNKNOWN (< 1 s each by log timestamps); two sub-second ad-hoc reconciliation calls that rewrote BUDGET_LEDGER.json's final field are UNKNOWN. "
           "**Compliance: QUALIFIED, not exact** — known %.3f s + measured remainder %.3f s = %.3f s; approximate all-attempt ENVELOPE %.1f s (not a formal bound: it adds the stage wall-clock remainders and the 96 s pre-cell window that contains both aborted launches, and omits the two unmeasured ad-hoc reconciliation calls); every figure is far inside 10,800 s.\n\n"
           "**Correction pass (separate 600 s ceiling; `review_2026-11-08/CORRECTION_LEDGER.jsonl`, every executed job under the REPAIRED supervisor):** %d starts, %d receipts, known %.3f s%s at the time this report was generated (this generator's own receipt and the later verify / package jobs are pending by construction; the final ledger is authoritative). Read-only inspection commands that printed fields of saved JSON ran outside the supervisor and are not charged (charge UNKNOWN; not bounded by evidence). The outside PACKAGE_RECORD.json of each archive is an INTEGRITY record (bytes, sha256, CRC table), not a supervisory job receipt; the package job's RECEIPT is in CORRECTION_LEDGER.jsonl (committed after the package) and is also copied as a sidecar `<zip>.PACKAGE_JOB_RECEIPT.json` next to the archive.\n\n"
           "Amendments (append-only; AMENDMENTS.json): %s.\n"
           % (cl_["starts"], cl_["receipts"], cl_["known_receipt_sum_s"], cl_["final_package_receipt"], "; ".join("%s = %s" % (k, v) for k, v in cl_["stale_snapshots_retired"].items()),
              un["stage_runner_nonnested_overhead"]["measured_outer_minus_supervisor_wall_s_over_cells"], sw["primary"]["runner_remainder_upper_bound_s"], sw["diag"]["runner_remainder_upper_bound_s"],
              cl_["known_receipt_sum_s"], un["stage_runner_nonnested_overhead"]["measured_outer_minus_supervisor_wall_s_over_cells"], cl_["known_receipt_sum_s"] + un["stage_runner_nonnested_overhead"]["measured_outer_minus_supervisor_wall_s_over_cells"], ACC["approximate_envelope_all_attempt_s"],
              len(cst), len(crc), corr_known, (" (unresolved at generation: %s)" % corr_unres) if corr_unres else "",
              "; ".join("%s — %s" % (a["id"], (a.get("scope") or a.get("what") or "")[:160]) for a in am)))
    rep = rep[:i0] + new + rep[i2 + 1:]
    open(os.path.join(R, "REPORT_corrected.md"), "w").write(rep)
    print(json.dumps({"report_corrected_chars": len(rep), "active_rows": len(act), "sample_active": [(a["case"], round(a["completed_nodes_wall_s"], 2), round(a["active_operation_elapsed_s"], 2) if a["active_operation_elapsed_s"] is not None else None) for a in act[:6]]}))


if __name__ == "__main__":
    main(os.path.abspath(sys.argv[1]))
