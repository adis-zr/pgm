"""Census REPORT.md generator (reads CASES.jsonl / OPERATIONS.jsonl / OPPORTUNITIES.jsonl / RECONCILIATION.json / BUDGET_LEDGER.json / manifest).
Observations, inferred bottlenecks, proposed rules and unproved claims are labelled as such. Numbers are read from records.
    python -m adp.census_closeout.report D"""
from __future__ import annotations
import os, sys, json, collections, statistics
HERE = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))); sys.path.insert(0, HERE)


def jl(p):
    return [json.loads(l) for l in open(p)] if os.path.exists(p) else []


def fmt(x, d=2):
    return "—" if x is None else (("%.*f" % (d, x)) if isinstance(x, float) else str(x))


def main(D):
    man = json.load(open(os.path.join(D, "CENSUS_MANIFEST.json"))); C = jl(os.path.join(D, "CASES.jsonl")); OPS = jl(os.path.join(D, "OPERATIONS.jsonl")); OPP = jl(os.path.join(D, "OPPORTUNITIES.jsonl")); REC = json.load(open(os.path.join(D, "RECONCILIATION.json"))); B = json.load(open(os.path.join(D, "BUDGET_LEDGER.json")))
    AM = json.load(open(os.path.join(D, "AMENDMENTS.json"))) if os.path.exists(os.path.join(D, "AMENDMENTS.json")) else []
    acc = [c for c in C if c["accessible"]]; fam = {c["slot"]: c["family"] for c in acc}; fams = sorted(set(fam.values()))
    L = []; P = L.append
    P("# Repaired baseline and exact-structure census — AGGREGATE_DP_V1 (brief of 8 November 2026; run 9 November 2026)\n")
    P("Branch `adp-census-2026-11-08`; manifest commit `%s`; numerical source at the REPAIRED pin (frozen-set code hash `%s` = commit ec4ae427…); harness hash `%s`; CONFIG_new_arm.json sha256 `%s` (historical bytes). 46 accessible cases + 2 inaccessible slots; one repaired full-arm invocation per case at 20 s and at 120 s (92 primary cells), then one instrumented diagnostic invocation per case at 20 s (46 cells). No baseline reruns, no ablations, no repetitions, no code change to the arm. Historical frozen results (campaign of 7 Nov, code hash b915a293…) are shown as LABELLED HISTORICAL CONTEXT only: 22/46 at 20 s, 23/46 at 120 s, six repeatable case-specific speed advantages, no broad advantage.\n" % (man["commit"][:12], man["frozen_set_code_hash"][:12], man["harness_hash"][:12], man["config_new_arm_sha256"][:12]))
    P("Vocabulary (units differ and are never mixed): a CORE ENTRY is one representative class tuple of a node's output; BAG ROWS = core entries × |D_x| (one per eliminated state); a BAG VISIT is one row's arithmetic in the producer; a CHECKER VISIT is one row replayed by the independent checker; the RAW BOUNDARY-DOMAIN PRODUCT is ∏|D_w| over the boundary variables; the RESPONSE-CLASS PRODUCT is the planned core size after the source-certified views. 'Observed' = measured in the diagnostic cell; 'planned' = read from the plan before execution.\n")
    # ---------------------------------------------------------------- A
    P("## A. What the repaired full arm certifies at each budget; changes from the frozen statuses\n")
    for b, key, hk in ((20, "primary_20s", "P20"), (120, "primary_120s", "P120")):
        st = collections.Counter(c[key]["status"] for c in acc); cert = sorted(c["slot"] for c in acc if c[key]["status"] == "CERTIFIED"); hist = sorted(c["slot"] for c in acc if c["historical"][hk]["status"] == "CERTIFIED")
        P("**%d s.** Repaired arm: %s. CERTIFIED %d/46: %s. Historical (frozen code) CERTIFIED %d/46. Gained vs historical: %s. Lost vs historical (REGRESSIONS): %s.\n" % (b, dict(st), len(cert), ", ".join(cert), len(hist), ", ".join(sorted(set(cert) - set(hist))) or "none", ", ".join(sorted(set(hist) - set(cert))) or "none"))
    P("Status changes 20 s: %s; 120 s: %s. Each cell is ONE observation on the repaired code; a status change between the frozen and the repaired code on a deadline-stopped case can also reflect ordinary run-to-run variation near the deadline, not only the repair.\n" % (json.dumps(REC["summary"]["20s"]), json.dumps(REC["summary"]["120s"])))
    P("| case | family | hist 20 s | repaired 20 s | hist 120 s | repaired 120 s | lazy downgrades 20/120 | lazy evals 20/120 | reduced hash 20=120 | plan hash 20=120 |\n|---|---|---|---|---|---|---|---|---|---|")
    for c in acc:
        r = next(x for x in REC["rows"] if x["case"] == c["slot"])
        P("| %s | %s | %s%s | %s%s | %s%s | %s%s | %s / %s | %s / %s | %s | %s |" % (c["slot"], c["family"], r["historical_P20"], (" [%s]" % r["historical_P20_stop"]) if r["historical_P20_stop"] else "", r["repaired_20s"], (" [%s]" % r["repaired_20s_stop"]) if r["repaired_20s_stop"] else "", r["historical_P120"], (" [%s]" % r["historical_P120_stop"]) if r["historical_P120_stop"] else "", r["repaired_120s"], (" [%s]" % r["repaired_120s_stop"]) if r["repaired_120s_stop"] else "", r["lazy_downgrades_20"], r["lazy_downgrades_120"], r["lazy_evals_20"], r["lazy_evals_120"], c["reduced_hash_20_vs_120_same"], c["plan_hash_20_vs_120_same"]))
    P("\nThe 20 s and 120 s invocations of a case are the SAME reduced model and the SAME plan only where the two hash columns say True; the source-reduction fixpoint has a deadline-dependent allowance (30 % of the remaining wall), so a 120 s run may reduce further than a 20 s run. Where the hashes differ the pair is not 'the same computation with six times the time'.\n")
    # ---------------------------------------------------------------- B
    P("## B. Former VALUE_CAP cases: what the repaired fallback did\n")
    vc = [c for c in acc if (c["historical"]["P20"]["stop"] == "VALUE_CAP" or c["historical"]["P120"]["stop"] == "VALUE_CAP")]
    P("| case | hist 20 s | repaired 20 s | hist 120 s | repaired 120 s | downgrades 20/120 | lazy evals 20/120 | lazy evictions 20/120 | stop 120 s (current node) |\n|---|---|---|---|---|---|---|---|---|")
    for c in vc:
        p20 = c["primary_20s"]; p120 = c["primary_120s"]; ct20 = p20.get("counters") or {}; ct120 = p120.get("counters") or {}
        P("| %s | %s [%s] | %s [%s] | %s [%s] | %s [%s] | %s / %s | %s / %s | %s / %s | %s |" % (c["slot"], c["historical"]["P20"]["status"], c["historical"]["P20"]["stop"], p20["status"], (p20.get("stop") or {}).get("kind"), c["historical"]["P120"]["status"], c["historical"]["P120"]["stop"], p120["status"], (p120.get("stop") or {}).get("kind"), p20.get("downgraded_to_lazy"), p120.get("downgraded_to_lazy"), ct20.get("lazy_evals"), ct120.get("lazy_evals"), ct20.get("lazy_evictions"), ct120.get("lazy_evictions"), json.dumps(((p120.get("stop") or {}).get("current")))))
    P("\nObservation: a VALUE_CAP stop of the frozen code becomes, under the repaired code, a lazy downgrade of the cores that do not fit, followed by whichever stop the deadline imposes on the lazily served program. Certification of a former VALUE_CAP case requires the lazily served nodes AND the checker to finish within the budget; the table shows which happened.\n")
    # ---------------------------------------------------------------- C
    P("## C. Where observed work, memory and checking concentrate (diagnostic cells, 20 s)\n")
    cost = {o["case"]: o for o in OPP if o["inspection"] == "cost_classification"}
    P("| case | diag status | nodes observed / planned | planned core entries | planned bag rows | bag visits at stop/end | entries computed at stop/end | lazy evals (hits) at stop/end | downgrades | forward s (incl. partial node) | backward s | checker s | checker status | largest completed node (nid) | earliest sharp rise | operation at stop |\n|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|")
    for c in acc:
        o = cost.get(c["slot"])
        if not o or o["state"] != "OBSERVED":
            P("| %s | %s | — | — | — | — | — | — | — | — | — | — | %s | — | %s |" % (c["slot"], c["diagnostic_20s"]["status"], (o or {}).get("checker", {}).get("status") if o else "—", (o or {}).get("state", "NOT_REACHED"))); continue
        r = o["realized"]; pv = o["planned_volume"]; ph = o["phases_s"]; er = o.get("earliest_sharp_rise")
        P("| %s | %s | %d / %d | %d | %d | %d | %d | %d (%d) | %d | %s | %s | %s | %s | %s | %s | %s |" % (c["slot"], o["status"], r["nodes_forward_observed"], r["of"], pv["core_entries"], pv["bag_rows"], r["bag_rows_at_stop"], r["entries_computed_at_stop"], r["lazy_evals_at_stop"], r["lazy_hits_at_stop"], r["downgraded_to_lazy_at_stop"], fmt(r["forward_wall_s_incl_partial_node"]), fmt(ph.get("backward")), fmt(ph.get("checker")), o["checker"]["status"], o["largest_observed_node"], ("%s@nid %s" % (er["kind"], er["nid"])) if er else "none", json.dumps(o.get("current_operation_at_stop"))))
    P("\nSeparation of the four quantities: PLAN SIZE (planned core entries / bag rows, exact from the plan), REALIZED WORK (bag visits and entries computed in the observed prefix), REPEATED WORK (lazy evaluations beyond stored entries and evictions; a lazy entry re-evaluated after eviction is counted again in lazy evals, so unique counts are not derivable from these totals), PARTIAL TRACES (nodes observed / planned < 1 means the suffix is UNSEEN: the observed prefix is not evidence about the unseen suffix's cost). Checker work is from the checker's own record (its internals were not instrumented; per-node checker work is unavailable).\n")
    P("### Per-family concentration (sums over the observed prefixes of the diagnostic cells)\n")
    P("| family | cases | diag certified | planned core entries (sum) | planned bag rows (sum) | realized bag visits (sum) | forward s (sum) | checker s (sum) | nodes observed / planned |\n|---|---|---|---|---|---|---|---|---|")
    for f in fams:
        cs = [c for c in acc if c["family"] == f]; os_ = [cost[c["slot"]] for c in cs if c["slot"] in cost and cost[c["slot"]]["state"] == "OBSERVED"]
        P("| %s | %d | %d | %d | %d | %d | %s | %s | %d / %d |" % (f, len(cs), sum(1 for c in cs if c["diagnostic_20s"]["status"] == "CERTIFIED"), sum(o["planned_volume"]["core_entries"] for o in os_), sum(o["planned_volume"]["bag_rows"] for o in os_), sum(o["realized"]["bag_rows_at_stop"] for o in os_), fmt(sum((o["realized"]["forward_wall_s_incl_partial_node"] or 0) for o in os_)), fmt(sum(o["phases_s"].get("checker") or 0 for o in os_)), sum(o["realized"]["nodes_forward_observed"] for o in os_), sum(o["realized"]["of"] for o in os_)))
    P("")
    # ---------------------------------------------------------------- D
    P("## D. Exact simplification opportunities: concrete evidence, empty scans, unobserved\n")
    for insp, title in (("dead_local_rows", "D1. Locally supported child entries the parent never references (one-level global-infeasibility witnesses)"), ("disjoint_input_rank1", "D2. Intermediates with retained product structure (bucket inputs with pairwise-disjoint boundary scopes)"), ("single_input_elimination_aggregate", "D3. Consumers that need only an aggregate forward (single-input eliminations) — and still need every entry in reverse"), ("response_partition_stop", "D4. Where response partitions stop compressing, and which input is responsible"), ("deterministic_source_structure", "D5. Deterministic / zero source structure and what the exact reductions did with it")):
        P("### %s\n" % title)
        rows = {o["case"]: o for o in OPP if o["inspection"] == insp}; states = collections.Counter(rows[c["slot"]]["state"] if c["slot"] in rows else "NOT_REACHED" for c in acc)
        P("States over the 46 cases: %s.\n" % json.dumps(dict(states)))
        if insp == "dead_local_rows":
            P("| case | state | parent-child pairs checked | nodes observed / planned | total dead entries | largest witness (child nid → parent nid: dead / child entries, child format, child has compressed axis) |\n|---|---|---|---|---|---|")
            for c in acc:
                o = rows.get(c["slot"])
                if not o:
                    P("| %s | NOT_REACHED | — | — | — | — |" % c["slot"]); continue
                w = o["witnesses"][0] if o["witnesses"] else None
                P("| %s | %s | %d | %d / %d | %d | %s |" % (c["slot"], o["state"], o["extent"]["parent_child_pairs_checked"], o["extent"]["nodes_observed"], o["extent"]["nodes_planned"], o["total_dead_entries"], ("%d → %d: %d / %d, %s, %s" % (w["child_nid"], w["parent_nid"], w["dead"], w["child_entries"], w["child_format"], w["child_has_compressed_axis"])) if w else "—"))
            P("\nObstruction (recorded, not applied): a dead entry can be a class REPRESENTATIVE whose other class members are live; pruning it inside a response view would corrupt the view (the packet's global-support counterexample). A future rule needs a whole-root equivalence and view-compatibility proof, and must preserve the reverse pass (every requested marginal). Witnesses with `child has compressed axis = True` are exactly the ones where this obstruction bites.\n")
        elif insp == "disjoint_input_rank1":
            P("| case | state | nodes with disjoint inputs | nodes with volume gain | largest gain (nid: planned core entries vs rank-1 volume, ratio) |\n|---|---|---|---|---|")
            for c in acc:
                o = rows.get(c["slot"])
                if not o:
                    P("| %s | NOT_REACHED | — | — | — |" % c["slot"]); continue
                w = o["witnesses"][0] if o["witnesses"] else None
                P("| %s | %s | %d | %d | %s |" % (c["slot"], o["state"], o["nodes_with_disjoint_inputs"], o["nodes_with_volume_gain"], ("nid %d: %d vs %d (%.1f×)" % (w["nid"], w["planned_core_entries"], w["rank1_terms_volume"], w["ratio"])) if w else "—"))
            P("\nProof obligation (algebraic, exact): sum_x ∏_j f_j(x, S_j) with pairwise-disjoint S_j equals a sum of |D_x| separable terms. UNMEASURED: whether the downstream product with the parent's other inputs and the reverse pass stay affordable (term counts multiply; the reverse pass needs per-entry adjoints of whatever object is stored). A volume gain here is a representation-size statement, not a runtime win.\n")
        elif insp == "single_input_elimination_aggregate":
            P("| case | state | single-input nodes | volume of their outputs (core entries) |\n|---|---|---|---|")
            for c in acc:
                o = rows.get(c["slot"]); P("| %s | %s | %s | %s |" % (c["slot"], o["state"] if o else "NOT_REACHED", o["nodes"] if o else "—", o["volume_of_single_input_outputs"] if o else "—"))
            P("\nFor these nodes the forward consumer needs only sum_x of one input, but because every variable is queried the reverse pass needs the pre-aggregation entries at every marker: the aggregate alone is NOT sufficient under the all-query contract. A fused child+parent kernel would avoid STORING the child's core (residency) without avoiding its bag visits (work).\n")
        elif insp == "response_partition_stop":
            P("| case | state | axes inspected | axes compressed | uncompressed axes where SOME input compressed (witness count) | example (nid, axis, classes per input, finest input) |\n|---|---|---|---|---|---|")
            for c in acc:
                o = rows.get(c["slot"])
                if not o:
                    P("| %s | NOT_REACHED | — | — | — | — |" % c["slot"]); continue
                w = o["witnesses"][0] if o["witnesses"] else None
                P("| %s | %s | %d | %d | %d | %s |" % (c["slot"], o["state"], o["extent"]["axes_inspected"], o["extent"]["axes_compressed"], o["count"], ("nid %d axis %d: %s finest %s" % (w["nid"], w["axis"], w["classes_per_input"], w["finest_inputs"])) if w else "—"))
            P("\nExact: an output axis stays at full width iff some input already distinguishes every state of that variable (the 'finest input'); the certified view is the intersection, so one fine input defeats the compression of all the others. Numerical equality of generated message values is NOT used and would not be a valid merge (their marker derivatives can differ).\n")
        else:
            P("| case | factors | entries | exact zeros | deterministic factors (arity ≥ 2; recomputed) | reductions applied | free vars original → reduced | remaining factors / entries | recognition capped |\n|---|---|---|---|---|---|---|---|---|")
            for c in acc:
                o = rows.get(c["slot"])
                if not o:
                    P("| %s | — | — | — | — | — | — | — | — |" % c["slot"]); continue
                s = o["source"]; P("| %s | %s | %s | %s | %s | %s | %s → %s | %s / %s | %s |" % (c["slot"], s["factors"], s["entries"], s["zeros"], s.get("deterministic_factors_arity_ge2"), json.dumps(o["reductions_applied"]), o["free_vars"][0], o["free_vars"][1], o["remaining"]["factors"], o["remaining"]["entries"], o["recognition_capped"]))
            P("")
    P("### D6. No-op and missingness summary over all inspection × case pairs\n")
    cnt = collections.Counter((o["inspection"], o["state"]) for o in OPP)
    P("| inspection | " + " | ".join(sorted({s for _, s in cnt})) + " |\n|---|" + "---|" * len({s for _, s in cnt}))
    for insp in sorted({i for i, _ in cnt}):
        P("| %s | %s |" % (insp, " | ".join(str(cnt.get((insp, s), 0)) for s in sorted({s for _, s in cnt}))))
    P("\nSCAN_CAPPED and NOT_REACHED never mean 'no useful structure'; NO_WITNESS_IN_COMPLETED_SCAN excludes only the named narrow rule on the completed extent; RULE_APPLIES_NO_VOLUME_GAIN means the identity holds but the representation it yields is not smaller.\n")
    # ---------------------------------------------------------------- E
    ap = os.path.join(D, "ANALYSIS_E.md")
    if os.path.exists(ap):
        P(open(ap).read())
    else:
        P("## E. (analysis file ANALYSIS_E.md missing)\n")
    # ---------------------------------------------------------------- budget
    P("## Budget (separate 10,800 s ceiling; every executed process job charged)\n")
    P("Total charged %s s (%s); by scope %s; envelopes %s; unresolved starts %d; within ceiling: %s. Disclosed uncharged: %s.\n" % (B["total_charged_s"], B["exact_compliance"], json.dumps(B["by_scope_s"]), json.dumps(B["envelopes_s"]), len(B["unresolved_starts"]), B["within_ceiling"], B["disclosed_uncharged"]))
    P("Amendments: %s.\n" % "; ".join("%s (%s)" % (a["id"], a["scope"][:120]) for a in AM))
    open(os.path.join(D, "REPORT.md"), "w").write("\n".join(L) + "\n"); print("REPORT.md written: %d lines" % len(L))


if __name__ == "__main__":
    main(os.path.abspath(sys.argv[1]))
