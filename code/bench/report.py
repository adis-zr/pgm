"""Report generator (spec section 10): applicability matrix by family, verified useful-answer coverage, accuracy / time on qualified
references, failure causes and costs, the 48-row inventory, family-balanced and case-weighted summaries, anchors separately, time breakdown,
single-observation vs repeated labelling, coverage-gap note, next-step recommendation.    python bench/report.py SWEEP_DIR -> REPORT.md"""
import os, sys, json, collections, statistics as st
HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ARMS = ["CBI_NATIVE", "MDI_EXISTING", "LBP", "WMB", "IJGP", "SAMPLESEARCH", "EXACT", "PGMAX_SUMPRODUCT_BP"]
FAMS = ["GridBN", "Grids", "Pedigree", "Promedus", "CSP", "DBN", "ObjectDetection", "Segmentation", "Protein", "bnlearn"]
GOOD = {"CERTIFIED", "VALID_BUT_TOO_WIDE", "COMPLETE", "COMPLETE_UNCONVERGED"}


def load(S, name, default=None):
    p = os.path.join(S, name)
    return json.load(open(p)) if os.path.exists(p) else default


def short(s):
    return {"UNSUPPORTED_REPRESENTATION": "UNSUP", "RESOURCE_LIMIT": "RLIM", "CERTIFIED": "CERT", "VALID_BUT_TOO_WIDE": "WIDE", "COMPLETE": "OK", "COMPLETE_UNCONVERGED": "OK~", "TIMEOUT": "TO", "FAILED": "FAIL", "ADMISSION_REFUSED": "ADM", "UNAVAILABLE": "N/A",
            "INFEASIBLE_CERTIFIED": "Z=0", "INFEASIBLE_ADAPTER": "Z=0", "KILLED_MEMORY_KILL": "MEM", "KILLED_TIMEOUT_KILL": "TO!", "NO_RECORD": "NOREC", "FAULT": "FAULT", "CHECK_FAILED": "CHK", "INVALID_OUTPUT": "INV", "LATE_OUTPUT": "LATE", "NOT_RUN_BUDGET": "NRB", "ENGINE_REFUSED_PREPROCESSING": "PREP"}.get(s, (s or "?")[:5])


def main(S):
    SC = load(S, "SCORES.json"); INV = {c["case"]: c for c in load(S, "INVENTORY.json")["cases"]}; SEL = load(S, "PANEL_SELECTION.json"); AV = load(S, "AVAILABILITY.json"); BL = load(S, "BUDGET_LEDGER.json", {})
    DG = load(S, "DIAGNOSTICS.json", {}); AM = load(S, "AMENDMENTS.json", {}); R4 = load(S, "../CBI_LIBRARY_2026-11-06/REPLAY4_vs_REPLAY3.json", {}); MAN = load(S, "CAMPAIGN_MANIFEST.json")
    cells = SC["cells"]; prim = [c for c in cells if c.get("label") is None]
    L = []; w = L.append
    w("# External benchmark sweep — CBI_NATIVE and MDI_EXISTING alongside six public MAR solvers (6 November 2026)\n")
    w("Branch `cbi-benchmark-sweep-2026-11-06`, frozen at commit `%s` (code hash `%s`), spec `SPEC_2026-11-06.txt`. One campaign, 28,800 s envelope. Every row below is one fresh cold process per case and arm; 20 s (breadth) or 120 s (depth) complete-response deadline, 8 GiB sampled process-tree budget, one worker. **Winning was not a criterion.** Four questions are answered separately: applicability, accuracy where a qualified reference exists, cost of a usable answer, and the obstruction behind each failure.\n" % (MAN["commit"][:12], MAN["code_hash"][:12]))
    w("Limitation recorded BEFORE outcomes: the native library accepts explicit binary block tables joined by the product kernel K_r(x,y) = Π_j (1 + r x_j y_j) with rational r in [0,1]; the campaign adapter maps binary unary/pairwise table models to it exactly (section 11 algebra) and nothing else. General factor extraction, nonbinary domains, arity ≥ 3 after evidence slicing, non-square cross-ratios and frustrated sign gauges are not supported.\n")
    # ---- 1. applicability matrix (breadth)
    w("## 1. Applicability matrix — breadth stage (20 s), status per family × arm\n")
    w("Codes: CERT certified width ≤ 1/100 · WIDE valid certificate but too wide · OK complete validated point output (OK~ = BP did not converge within tol) · UNSUP representation refused by the native adapter · RLIM engine admission / resource stop · ADM libDAI junction-tree memory admission refused · PREP MDI exact-preprocessing admission refused (factor above the locally verifiable cap) · TO deadline censored · FAIL wrapper or solver failure · N/A arm unavailable · Z=0 zero partition proved · MEM / TO! supervisor kill. Counts over the family's cases (n).\n")
    w("| family (n) | " + " | ".join(ARMS) + " |"); w("|---|" + "---|" * len(ARMS))
    fam_n = collections.Counter(c["case"] for c in prim if c["stage"] == "breadth" and c["arm"] == "CBI_NATIVE"); fam_cases = collections.defaultdict(set)
    for c in prim:
        if c["stage"] == "breadth":
            fam_cases[c["family"]].add(c["case"])
    for fam in FAMS:
        if fam not in fam_cases:
            continue
        row = []
        for arm in ARMS:
            cnt = collections.Counter(short(c["status"]) for c in prim if c["stage"] == "breadth" and c["family"] == fam and c["arm"] == arm)
            row.append(" ".join("%s×%d" % (k, v) for k, v in sorted(cnt.items(), key=lambda kv: -kv[1])))
        w("| %s (%d) | %s |" % (fam, len(fam_cases[fam]), " | ".join(row)))
    tot = collections.defaultdict(collections.Counter)
    for c in prim:
        if c["stage"] == "breadth":
            tot[c["arm"]][c["status"]] += 1
    w("\nCase-weighted totals over %d accessible cases (target denominator 48; shortfalls: %s):\n" % (len(fam_n), ", ".join("%s %d/4" % (k, v["available"]) for k, v in SEL["shortfalls"].items()) or "none"))
    w("| arm | " + " | ".join(sorted({s for a in tot for s in tot[a]})) + " |"); keys = sorted({s for a in tot for s in tot[a]}); w("|---|" + "---|" * len(keys))
    for arm in ARMS:
        w("| %s | %s |" % (arm, " | ".join(str(tot[arm].get(k, 0)) for k in keys)))
    # family-balanced applicability: mean over families of the fraction of cases with a complete / certified answer
    w("\nFamily-balanced complete-answer rate (mean over families of the per-family fraction with OK / OK~ / CERT / WIDE):\n")
    w("| arm | family-balanced | case-weighted |"); w("|---|---|---|")
    for arm in ARMS:
        fr = []
        for fam in FAMS:
            cs = [c for c in prim if c["stage"] == "breadth" and c["family"] == fam and c["arm"] == arm]
            if cs:
                fr.append(sum(1 for c in cs if c["status"] in GOOD) / len(cs))
        allc = [c for c in prim if c["stage"] == "breadth" and c["arm"] == arm]
        w("| %s | %.2f | %.2f |" % (arm, st.mean(fr) if fr else 0, (sum(1 for c in allc if c["status"] in GOOD) / len(allc)) if allc else 0))
    # ---- 2. service track
    w("\n## 2. Service track — original-model verified coverage and time to width ≤ 1/100\n")
    w("| arm | stage | certified (width met) | valid but too wide | zero-partition proofs | admission / resource refusals | representation refusals | other | median time-to-verified-width s (certified cells) |"); w("|---|---|---|---|---|---|---|---|---|")
    for arm in ("CBI_NATIVE", "MDI_EXISTING"):
        for stage in ("breadth", "depth"):
            cs = [c for c in prim if c["arm"] == arm and c["stage"] == stage]
            if not cs:
                continue
            cert = [c for c in cs if c["status"] == "CERTIFIED"]; tt = [c["t_first_verified_width_met_s"] for c in cert if c.get("t_first_verified_width_met_s")]
            w("| %s | %s | %d | %d | %d | %d | %d | %d | %s |" % (arm, stage, len(cert), sum(c["status"] == "VALID_BUT_TOO_WIDE" for c in cs), sum(c["status"] in ("INFEASIBLE_CERTIFIED", "INFEASIBLE_ADAPTER") for c in cs),
                                                          sum(c["status"] == "RESOURCE_LIMIT" for c in cs), sum(c["status"] == "UNSUPPORTED_REPRESENTATION" for c in cs), sum(c["status"] not in ("CERTIFIED", "VALID_BUT_TOO_WIDE", "INFEASIBLE_CERTIFIED", "INFEASIBLE_ADAPTER", "RESOURCE_LIMIT", "UNSUPPORTED_REPRESENTATION") for c in cs), ("%.2f" % st.median(tt)) if tt else "—"))
    certs = [c for c in prim if c["arm"] in ("CBI_NATIVE", "MDI_EXISTING") and c["status"] in ("CERTIFIED", "VALID_BUT_TOO_WIDE")]
    if certs:
        w("\nCertified / valid cells:\n"); w("| case | family | arm | stage | status | complete response s | peak RSS MB | reference class | max abs error upper bound vs reference |"); w("|---|---|---|---|---|---|---|---|---|")
        for c in sorted(certs, key=lambda c: (c["stage"], c["family"], c["case"])):
            acc = c.get("accuracy") or {}
            w("| %s | %s | %s | %s | %s | %.2f | %.0f | %s | %s |" % (c["case"], c["family"], c["arm"], c["stage"], c["status"], c.get("complete_response_s") or 0, (c.get("peak_tree_rss_bytes") or 0) / 1e6, c.get("reference_class"), ("%.2e" % acc["max_abs_error_upper"]) if acc else "—"))
    # ---- 3. accuracy track
    w("\n## 3. Accuracy track — empirical point error at fixed budgets on cases with a qualified reference (R0 / R1 separated from R2)\n")
    w("Point estimates: heuristics' output vectors; certified arms' declared midpoints. Errors are bounded by the reference enclosure (R1: binary64 exact-algorithm output; the enclosure is the half-ulp of the 10-decimal print only, the binary64 computation error is NOT enclosed, so R1 errors are numerical comparisons; R2: official 6-significant-digit files, provenance undocumented). `met` = upper error bound ≤ 0.005; `missed` = lower bound > 0.005; otherwise unresolved. R1/R2 distances are numerical comparisons, not rigorous error claims. Heuristics' certification track is NOT_OFFERED.\n")
    rc = SC["reference_classes"]; w("Reference classes over the panel: %s. Cross-reference consistency (independent R1 vs R2 boxes disjoint on any coordinate): %s.\n" % (dict(collections.Counter(v["class"] for v in rc.values())), {k: v["cross_reference_disjoint_coordinates"] for k, v in rc.items() if v.get("cross_reference_disjoint_coordinates")} or "no disjoint coordinates found"))
    for stage in ("breadth", "depth"):
        w("\n### %s stage (%s s): max |error| upper bound · mean Hellinger (at reference midpoint) per arm, cases with R0/R1 references\n" % (stage, "20" if stage == "breadth" else "120"))
        cases = sorted({c["case"] for c in prim if c["stage"] == stage and rc.get(c["case"], {}).get("class") in ("R0", "R1")})
        if not cases:
            w("(no case in this stage has an R0 / R1 reference)"); continue
        w("| case | family | ref | " + " | ".join(a for a in ARMS if a != "EXACT") + " |"); w("|---|---|---|" + "---|" * (len(ARMS) - 1))
        for case in cases:
            row = []
            for arm in ARMS:
                if arm == "EXACT":
                    continue
                c = next((x for x in prim if x["stage"] == stage and x["case"] == case and x["arm"] == arm), None)
                if c is None:
                    row.append("—"); continue
                acc = c.get("accuracy")
                row.append(("%.1e / %.1e %s" % (acc["max_abs_error_upper"], acc["hellinger_mean_at_ref_midpoint"], {"met": "✓", "missed": "✗", "unresolved": "?"}[acc["target_0.005"]])) if acc else short(c["status"]))
            w("| %s | %s | %s | %s |" % (case, INV[case]["family"], rc[case]["class"], " | ".join(row)))
        w("\nR2-only cases (official 2014 vectors; numerical comparison only):")
        cases2 = sorted({c["case"] for c in prim if c["stage"] == stage and rc.get(c["case"], {}).get("class") == "R2"})
        if cases2:
            w("| case | family | " + " | ".join(a for a in ARMS if a not in ("EXACT",)) + " |"); w("|---|---|" + "---|" * (len(ARMS) - 1))
            for case in cases2:
                row = []
                for arm in ARMS:
                    if arm == "EXACT":
                        continue
                    c = next((x for x in prim if x["stage"] == stage and x["case"] == case and x["arm"] == arm), None); acc = (c or {}).get("accuracy")
                    row.append(("%.1e / %.1e" % (acc["max_abs_error_upper"], acc["hellinger_mean_at_ref_midpoint"])) if acc else short((c or {}).get("status")))
                w("| %s | %s | %s |" % (case, INV[case]["family"], " | ".join(row)))
        else:
            w("(none)")
    # paired time where both arms meet the same quality requirement
    w("\n### Paired time and memory where two arms meet the SAME declared quality (max error upper bound ≤ 0.005 against an R0/R1 reference, same case and stage)\n")
    w("| case | stage | arm A | time A s | RSS A MB | arm B | time B s | RSS B MB |"); w("|---|---|---|---|---|---|---|---|"); n_pairs = 0
    for stage in ("breadth", "depth"):
        for case in sorted({c["case"] for c in prim if c["stage"] == stage}):
            met = [c for c in prim if c["stage"] == stage and c["case"] == case and (c.get("accuracy") or {}).get("target_0.005") == "met" and rc.get(case, {}).get("class") in ("R0", "R1")]
            ours = [c for c in met if c["arm"] in ("CBI_NATIVE", "MDI_EXISTING")]
            for a in ours:
                for b in met:
                    if b["arm"] not in ("CBI_NATIVE", "MDI_EXISTING"):
                        w("| %s | %s | %s | %.2f | %.0f | %s | %.2f | %.0f |" % (case, stage, a["arm"], a["complete_response_s"], a["peak_tree_rss_bytes"] / 1e6, b["arm"], b["complete_response_s"], b["peak_tree_rss_bytes"] / 1e6)); n_pairs += 1
    if n_pairs == 0:
        w("| (no case where one of our arms and an external arm both met the target) | | | | | | | |")
    # ---- 4. failure causes and costs
    w("\n## 4. Failure causes and costs\n")
    for arm in ARMS:
        reasons = collections.Counter()
        for c in prim:
            if c["arm"] == arm and c["status"] not in GOOD:
                key = c.get("failure_primary") or c.get("reason") or c["status"]; key = str(key).split(":")[0] if c["status"] == "UNSUPPORTED_REPRESENTATION" else (str(key)[:90])
                reasons[(c["status"], key)] += 1
        if reasons:
            w("**%s** — %s\n" % (arm, "; ".join("%s / %s ×%d" % (k[0], k[1], v) for k, v in reasons.most_common(6))))
    w("\nTime breakdown (medians over cells with the phase recorded; seconds): conversion = evidence slicing / adapter / clamping, planning = validation + reductions + graph construction (CBI) / junction-tree construction (libDAI) / compilation (PGMax), verification = independent checker (certified arms only).\n")
    w("| arm | stage | n | startup+imports | parse | convert | plan | solve | verify | serialize | complete response | peak RSS MB |"); w("|---|---|---|---|---|---|---|---|---|---|---|---|")
    for arm in ARMS:
        for stage in ("breadth", "depth"):
            cs = [c for c in prim if c["arm"] == arm and c["stage"] == stage and c.get("phases_s")]
            if not cs:
                continue
            def med(k):
                v = [c["phases_s"].get(k) for c in cs if isinstance(c["phases_s"].get(k), (int, float))]; return ("%.3f" % st.median(v)) if v else "—"
            cr = [c["complete_response_s"] for c in cs if c.get("complete_response_s")]
            w("| %s | %s | %d | %s | %s | %s | %s | %s | %s | %s | %s | %.0f |" % (arm, stage, len(cs), med("startup_imports"), med("parse"), med("convert"), med("plan"), med("solve"), med("verify"), med("serialize"), ("%.2f" % st.median(cr)) if cr else "—", st.median([c["peak_tree_rss_bytes"] / 1e6 for c in cs])))
    # ---- 5. anchors
    w("\n## 5. Previously seen anchors (Grids_11, Pedigree_11, Promedus_12), reported separately\n")
    w("| case | arm | stage | status | complete response s | accuracy (max err upper) |"); w("|---|---|---|---|---|---|")
    for c in sorted([c for c in prim if c.get("anchor")], key=lambda c: (c["case"], c["stage"], c["arm"])):
        w("| %s | %s | %s | %s | %.2f | %s |" % (c["case"], c["arm"], c["stage"], c["status"], c.get("complete_response_s") or 0, ("%.1e" % c["accuracy"]["max_abs_error_upper"]) if c.get("accuracy") else "—"))
    # ---- 6. inventory
    w("\n## 6. Panel inventory (%d of 48 accessible; selection rule CBI-EXTERNAL-48-v1; anchors forced after hash binding)\n" % len(SEL["selected"]))
    w("| case | family | quartile | anchor | vars | factors | domains | max arity | table entries (largest) | zeros | evidence | components | topology |"); w("|---|---|---|---|---|---|---|---|---|---|---|---|---|")
    for s in SEL["selected"]:
        r = INV[s["case"]]; t = r["structure"]
        w("| %s | %s | %s | %s | %d | %d | %s | %d | %d (%d) | %d | %d | %d | %s |" % (s["case"], s["family"], s.get("quartile"), "yes" if s.get("anchor") else "", t["variables"], t["factors"], ",".join("%s:%d" % kv for kv in list(t["domain_histogram"].items())[:3]), t["max_arity"], t["table_entries_total"], t["table_entries_largest"], t["exact_zeros"], t["evidence_count"], t["connected_components"], t["topology"]))
    w("\nShortfalls: %s. Family aliases recorded: %s." % (SEL["shortfalls"], {k: v["aliases"] for k, v in SEL["families"].items() if v["aliases"]}))
    # ---- 7. diagnostics, repetitions, amendments, regression
    w("\n## 7. Diagnostics, repetitions, amendments, regression of the saved panel\n")
    w("**Single observations vs repetitions.** Every breadth and depth cell is ONE observation. Repetitions exist only for the conditional subset below.\n")
    if DG:
        w("Width probes / rooted probe cases: %s. %s\n" % (DG.get("A_width_probes_cases"), " ".join(DG.get("notes", []))))
        if DG.get("A_rows"):
            w("| case | probe | status | wall s |"); w("|---|---|---|---|")
            for r in DG["A_rows"]:
                w("| %s | %s | %s | %.2f |" % (r["case"], r["label"], r["status"], r["supervisor_wall_s"]))
        if DG.get("B_repetitions"):
            w("\nConditional repetition subset (%s):\n" % DG["B_repetitions"][0]["label"].rsplit("_rep", 1)[0]); w("| case | arm | rep | status | complete response s | peak RSS MB |"); w("|---|---|---|---|---|---|")
            for r in DG["B_repetitions"]:
                w("| %s | %s | %s | %s | %s | %.0f |" % (r["case"], r["arm"], r["label"][-1], r["status"], ("%.2f" % r["complete_response_s"]) if r.get("complete_response_s") else "—", (r.get("peak_tree_rss_bytes") or 0) / 1e6))
    if AM:
        for k, a in AM.items():
            w("\n**%s** (%s): %s Exposed before: %d cells; reruns: %s." % (k, a.get("kind"), a.get("what"), len(a.get("exposed_before_amendment", [])), [(r["case"], r["status"]) for r in a.get("reruns", [])]))
    if R4:
        w("\n**Saved-panel regression (REPLAY4 vs REPLAY3, 43 cells on the repaired code):** %d status / verification changes, %d containment changes, all verified = %s, wall %.1f s vs %.1f s. Single forest queries now use the rooted inward schedule: %s." % (len(R4["status_or_verification_changes"]), len(R4["containment_changes"]), R4["all_verified4"], R4["total_wall4_s"], R4["total_wall3_s"], "; ".join("%s %.2f→%.2f s" % (r["instance"], r["cold3"], r["cold4"]) for r in R4["single_query_forest_cells"] if r["proof_kinds4"] == ["forest_rooted"])))
    # ---- 8. availability / coverage gap
    w("\n## 8. Coverage-gap note (outside measured tables)\n")
    w("Arm availability resolved before outcomes: %s\n" % json.dumps(AV["hierarchy_resolved_before_outcomes"], indent=0)[:1800])
    w("Unavailable winning solvers: uai14-mar (2022 leaderboard leader at 1,200 / 3,600 s) and IBIA-MAR have no public runnable artifact; SampleSearch (author code) could not be run or built here after six bounded attempts. Paper-reported runtimes are not compared with these laptop measurements. Emulated arms: none remained in the panel (the only x86-64 binaries aborted at startup under emulation).\n")
    # ---- 9. budget
    if BL:
        w("\n## 9. Budget ledger (28,800 s envelope)\n"); w("| scope | allocated s | charged s |"); w("|---|---|---|")
        for k, v in BL["allocation_s"].items():
            w("| %s | %.0f | %.1f |" % (k, v, BL["charged_s"].get(k, 0)))
        w("\nTotal charged incl. stage overheads %.1f s; remaining %.1f s; over-allocation: %s." % (BL["total_charged_incl_overheads_s"], BL["remaining_s"], BL.get("over_allocation") or "none"))
    open(os.path.join(S, "REPORT.md"), "w").write("\n".join(L) + "\n"); print("REPORT.md written (%d lines)" % len(L))


if __name__ == "__main__":
    main(os.path.abspath(sys.argv[1]))
