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
    AM = load(S, "AMENDMENTS.json", {})
    w("**Review of 7 November 2026 (bounded correctness and evidence repair).** Two adapter false accepts (added native edge; invented fixation) were reproduced on the submitted code and repaired in the independent checker (amendment 4); R2 / R1 reference boxes inferred from printed digits were replaced by point references (amendment 5, prior scores preserved); the libDAI wrapper's zero-scalar-after-evidence defect was fixed (amendment 6; no selected input affected); harness identity and ledger reconciliation repaired (amendments 7, 8); cbi rooted-alias / timeout-preservation / deadline repairs with controls. All eleven saved admitted CBI artifacts pass the repaired checker; no primary cell was rerun. Conclusions that SURVIVE: zero useful native CBI certifications; MDI certifies ten distinct cases, every one also completed by an exact baseline within 20 s; no measured external advantage. Conclusions that CHANGED: R2 distances (section 3) and the budget total (section 9). UNKNOWN: point quality on the %d R3 cases.\n" % sum(1 for v in SC["reference_classes"].values() if v["class"] == "R3"))
    w("Limitation recorded BEFORE outcomes: the native library accepts explicit binary block tables joined by the product kernel K_r(x,y) = Π_j (1 + r x_j y_j) with rational r in [0,1]; the campaign adapter maps binary unary/pairwise table models to it exactly (section 11 algebra) and nothing else. General factor extraction, nonbinary domains, arity ≥ 3 after evidence slicing, non-square cross-ratios and frustrated sign gauges are not supported.\n")
    # ---- 1. applicability matrix (breadth)
    w("## 1. Applicability matrix — breadth stage (20 s), status per family × arm\n")
    w("Codes: CERT certified width ≤ 1/100 · WIDE valid certificate but too wide · OK complete validated point output (OK~ = BP did not converge within tol) · UNSUP representation refused by the native adapter · RLIM engine admission / resource stop · ADM libDAI junction-tree memory admission refused · PREP MDI exact-preprocessing admission refused (factor above the locally verifiable cap) · TO deadline censored · FAIL wrapper or solver failure · N/A arm unavailable · Z=0 zero partition proved · MEM / TO! supervisor kill. Counts over the family's cases (n).\n")
    w("| family (n) | " + " | ".join(ARMS) + " |"); w("|---|" + "---|" * len(ARMS))
    fam_n = collections.Counter(c["case"] for c in prim if c["stage"] == "breadth" and c["arm"] == "CBI_NATIVE"); fam_cases = collections.defaultdict(set)
    for c in prim:
        if c["stage"] == "breadth":
            fam_cases[c["family"]].add(c["case"])
    amended = [c for c in cells if str(c.get("label") or "").startswith("amendment")]
    for fam in FAMS:
        if fam not in fam_cases:
            continue
        row = []
        for arm in ARMS:
            cnt = collections.Counter(short(c["status"]) for c in prim if c["stage"] == "breadth" and c["family"] == fam and c["arm"] == arm)
            cell = " ".join("%s×%d" % (k, v) for k, v in sorted(cnt.items(), key=lambda kv: -kv[1]))
            am = collections.Counter(short(c["status"]) for c in amended if c["stage"] == "breadth" and c["family"] == fam and c["arm"] == arm)
            if am:
                cell += " [amend.1 rerun: %s]" % " ".join("%s×%d" % kv for kv in am.items())
            row.append(cell)
        w("| %s (%d) | %s |" % (fam, len(fam_cases[fam]), " | ".join(row)))
    if amended:
        w("\nOriginal rows are the frozen run; bracketed values are the labelled reruns after amendment 1 (PGMax wrapper merges identical-scope factors). Both are kept in the ledger.")
    # checkpoint coverage
    w("\n### Checkpoint coverage — fraction of breadth cells with a COMPLETE output already available at 1 / 5 / 20 s (snapshots were copies of the latest complete output, never fresh runs)\n")
    w("| arm | at 1 s | at 5 s | at 20 s | median time to first complete output s |"); w("|---|---|---|---|---|")
    ledger = [json.loads(l) for l in open(os.path.join(S, "CELLS_LEDGER.jsonl"))]
    for arm in ARMS:
        rs = [r for r in ledger if r["stage"] == "breadth" and r["arm"] == arm and r.get("label") is None and r.get("snapshots")]
        if not rs:
            continue
        def frac(cp):
            vals = [any(sn.get("checkpoint_s") == cp and sn.get("complete_output") for sn in r["snapshots"]) for r in rs]; return "%.2f" % (sum(vals) / len(vals))
        tf = [r["t_first_complete_output_s"] for r in rs if r.get("t_first_complete_output_s")]
        w("| %s | %s | %s | %s | %s |" % (arm, frac(1.0), frac(5.0), frac(20.0), ("%.2f" % st.median(tf)) if tf else "—"))
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
    w("| arm | stage | certified (width met) | valid but too wide | zero-partition proofs | admission / resource refusals | representation refusals | preprocessing refusals (MDI) | other | median time-to-verified-width s (certified cells) |"); w("|---|---|---|---|---|---|---|---|---|---|")
    for arm in ("CBI_NATIVE", "MDI_EXISTING"):
        for stage in ("breadth", "depth"):
            cs = [c for c in prim if c["arm"] == arm and c["stage"] == stage]
            if not cs:
                continue
            cert = [c for c in cs if c["status"] == "CERTIFIED"]; tt = [c["t_first_verified_width_met_s"] for c in cert if c.get("t_first_verified_width_met_s")]
            w("| %s | %s | %d | %d | %d | %d | %d | %d | %d | %s |" % (arm, stage, len(cert), sum(c["status"] == "VALID_BUT_TOO_WIDE" for c in cs), sum(c["status"] in ("INFEASIBLE_CERTIFIED", "INFEASIBLE_ADAPTER") for c in cs),
                                                          sum(c["status"] == "RESOURCE_LIMIT" for c in cs), sum(c["status"] == "UNSUPPORTED_REPRESENTATION" for c in cs), sum(c["status"] == "ENGINE_REFUSED_PREPROCESSING" for c in cs), sum(c["status"] not in ("CERTIFIED", "VALID_BUT_TOO_WIDE", "INFEASIBLE_CERTIFIED", "INFEASIBLE_ADAPTER", "RESOURCE_LIMIT", "UNSUPPORTED_REPRESENTATION", "ENGINE_REFUSED_PREPROCESSING") for c in cs), ("%.2f" % st.median(tt)) if tt else "—"))
    certs = [c for c in prim if c["arm"] in ("CBI_NATIVE", "MDI_EXISTING") and c["status"] in ("CERTIFIED", "VALID_BUT_TOO_WIDE")]
    if certs:
        w("\nCertified / valid cells:\n"); w("| case | family | arm | stage | status | complete response s | peak RSS MB | reference class | max abs error upper bound vs reference |"); w("|---|---|---|---|---|---|---|---|---|")
        for c in sorted(certs, key=lambda c: (c["stage"], c["family"], c["case"])):
            acc = c.get("accuracy") or {}
            w("| %s | %s | %s | %s | %s | %.2f | %.0f | %s | %s |" % (c["case"], c["family"], c["arm"], c["stage"], c["status"], c.get("complete_response_s") or 0, (c.get("peak_tree_rss_bytes") or 0) / 1e6, c.get("reference_class"), ("%.2e" % acc["max_abs_error_upper"]) if acc else "—"))
    # ---- 3. accuracy track
    w("\n## 3. Accuracy track — empirical point error at fixed budgets on cases with a qualified reference (R0 / R1 separated from R2)\n")
    w("Point estimates: heuristics' output vectors; CBI_NATIVE's declared point is the midpoint of P(state 1) and its complement (binary); MDI_EXISTING's declared point is its own simplex-feasible representative inside the certified intervals (4,055 of 4,462 published coordinates differ from the interval midpoint; all lie inside their intervals and each vector sums to one). References: R0 = exact rational value (ASIA only); R1 = binary64 exact-algorithm output used as a POINT (no enclosure; the computation error is not bounded); R2 = official UAI 2014 solution vector used as a POINT (provenance undocumented). No uncertainty interval is inferred from printed digits (amendment 5). `met` = max |error| <= 0.005 against the reference point; R1 / R2 distances are approximate-reference numerical comparisons, not rigorous error claims. Heuristics' certification track is NOT_OFFERED.\n")
    rc = SC["reference_classes"]
    # repeat counts and distinct case / variable / coordinate counts, separately (spec section 8)
    for stage in ("breadth", "depth"):
        sc_ = [c for c in prim if c["stage"] == stage and c.get("accuracy") and rc.get(c["case"], {}).get("class") in ("R0", "R1")]
        w("Scored against R0/R1 in the %s stage: %d cells (ONE observation each) over %d distinct cases; %d variables and %d coordinates per arm-case summed = %d variable-scores, %d coordinate-scores." % (stage, len(sc_), len({c["case"] for c in sc_}), sum(c["accuracy"]["variables"] for c in sc_) // max(1, len({c["arm"] for c in sc_})), sum(c["accuracy"]["coordinates"] for c in sc_) // max(1, len({c["arm"] for c in sc_})), sum(c["accuracy"]["variables"] for c in sc_), sum(c["accuracy"]["coordinates"] for c in sc_)))
    w("Reference classes over the panel: %s. Cross-reference consistency where two reference candidates exist (actual pair and max coordinate distance between the two reference points; an R1/R1 pair is two exact-algorithm runs, an R1/R2 pair is an exact run vs the official vector): %s.\n" % (dict(collections.Counter(v["class"] for v in rc.values())), "; ".join("%s %s/%s %.1e" % (k, v["cross_reference_pair"][0], v["cross_reference_pair"][1], v["cross_reference_max_coordinate_distance"]) for k, v in sorted(rc.items()) if v.get("cross_reference_pair"))))
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
    # per-case tradeoff table for the depth stage (full status + time + error for every arm)
    w("\n### Depth stage (120 s): per-case status · complete response s · max |error| upper bound (R0/R1/R2 reference as marked); every entry is ONE observation\n")
    w("| case | ref | " + " | ".join(ARMS) + " |"); w("|---|---|" + "---|" * len(ARMS))
    for case in sorted({c["case"] for c in prim if c["stage"] == "depth"}, key=lambda x: (INV[x]["family"], x)):
        row = []
        for arm in ARMS:
            c = next((x for x in prim if x["stage"] == "depth" and x["case"] == case and x["arm"] == arm), None)
            if c is None:
                row.append("—"); continue
            acc = c.get("accuracy"); t = ("%.1fs" % c["complete_response_s"]) if c.get("complete_response_s") else ""
            row.append("%s %s%s" % (short(c["status"]), t, (" e≤%.0e" % acc["max_abs_error_upper"]) if acc else ""))
        w("| %s (%s) | %s | %s |" % (case, INV[case]["family"], rc.get(case, {}).get("class", "R3"), " | ".join(row)))
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
    w("\nTime breakdown (medians over cells with the phase recorded; seconds). Phase labels are per-arm instrumentation and NOT a common causal stage model: CBI convert = evidence slicing + adapter, plan = validation + reductions + system construction, solve = dispatch + numerics + publication, verify = native verifier, serialize = adapter CHECK + interval / point / result writing (the adapter check is inside this phase; some adapter file writes fall outside recorded phases); MDI solve = the engine pipeline time which COMBINES planning, numerics and its independent checker; libDAI convert = evidence clamping, plan = algorithm construction; PGMax plan = BP state construction / compilation. complete response is the cell's own timer: it starts after interpreter start-up and the cell's imports and ends after the numerical outputs and certificates are serialized but BEFORE the cell metadata record is written; the supervisor spawn-to-reap wall is the whole-process measure. bnlearn cells read PRECONVERTED UAI inputs: BIF parsing, conversion and correspondence checking happened at setup and are NOT in these cold times (prepared-input comparison, not the frozen original-source contract).\n")
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
    BK = load(S, "BLOCKERS.json", {}); AT = load(S, "ADMITTED_FAILURE_ATTRIBUTION.json", {})
    if BK:
        w("\n### Structural refusals of the native adapter, with one witness per blocker class\n")
        w("| blocker class | cells | families | witness |"); w("|---|---|---|---|")
        for cls, n in sorted(BK["cbi_native"]["by_class"].items(), key=lambda kv: -kv[1]):
            fams = [f for f, d in BK["cbi_native"]["by_family_class"].items() if cls in d]; wt = BK["cbi_native"]["witnesses"].get(cls, {})
            desc = {k: v for k, v in wt.items() if k in ("case", "factor", "scope", "cards", "free_after_slicing", "variable", "states", "pair", "cross_ratio", "attractive_pairs", "repulsive_pairs")}
            w("| %s | %d | %s | %s |" % (cls, n, ", ".join(fams), json.dumps(desc)[:220]))
        w("\nMDI_EXISTING refusals by typed reason: %s\n" % json.dumps(BK["mdi_existing"]["by_typed_reason"])[:900])
    if AT and AT.get("cells"):
        w("\n### Admitted CBI_NATIVE cells that stayed too wide: error-budget components\n")
        for case, a in AT["cells"].items():
            w("**%s** (%s, %d blocks, %s): regional enclosure width before transport max %.1e; transport radius z saturated at 1 on %d/%d blocks; crossing influence d_v at the query node %s, over the region boundary max %.1f; influence θ over %d edges median %.2f (fraction > 0.5: %.2f); escalations %s. Attribution: %s\n" % (
                case, a["stage"], a["blocks"], a["status"], a["regional_enclosure_width_before_transport"]["max"] or 0, a["transport_radius_z"]["saturated_at_1"], a["blocks"], a["crossing_influence_d_v"]["at_query_node"], a["crossing_influence_d_v"]["max_over_region_boundary"]["max"],
                a["influence_theta_over_edges"]["edges"], a["influence_theta_over_edges"]["median"], a["influence_theta_over_edges"]["fraction_above_0.5"], json.dumps(a["escalations_and_refusals"])[:300], a["attribution"]))
    # breadth -> depth status changes (budget effect)
    w("\n### Effect of the 120 s budget: cells whose status changed from breadth (20 s) to depth (120 s), same case and arm\n")
    w("| case | arm | breadth | depth | depth complete response s | depth peak RSS MB | note |"); w("|---|---|---|---|---|---|---|"); nchg = 0
    for c in prim:
        if c["stage"] != "depth":
            continue
        b = next((x for x in prim if x["stage"] == "breadth" and x["case"] == c["case"] and x["arm"] == c["arm"]), None)
        if b and b["status"] != c["status"]:
            note = ""
            if c["arm"] == "MDI_EXISTING" and c["status"] == "CERTIFIED":
                note = "refused at 20 s by the engine's checker-wall forecast; admitted and certified at 120 s (identity route)"
            elif c["status"].startswith("KILLED_MEMORY"):
                note = "a higher i-bound step of the ladder crossed the 8 GiB budget; the last complete lower-i-bound output is retained (scored separately)"
            elif c["arm"] == "PGMAX_SUMPRODUCT_BP" and b["status"] == "FAILED":
                note = "NOT a budget effect: the breadth FAILED row predates amendment 1 (duplicate-scope merge); its labelled 20 s rerun already completed in about 1.1 s"
            w("| %s | %s | %s | %s | %s | %.0f | %s |" % (c["case"], c["arm"], b["status"], c["status"], ("%.2f" % c["complete_response_s"]) if c.get("complete_response_s") else "—", (c.get("peak_tree_rss_bytes") or 0) / 1e6, note)); nchg += 1
    if nchg == 0:
        w("| (none) | | | | | | |")
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
            w("| case | probe | status | wall s | detail |"); w("|---|---|---|---|---|")
            for r in DG["A_rows"]:
                det = ""; cj = os.path.join(S, r["out_dir"], "cell.json") if r.get("out_dir") else None
                if cj and os.path.exists(cj):
                    d = json.load(open(cj))
                    if d.get("single_query"):
                        sq = d["single_query"]; det = "var %s: %s, proof kind %s (region certificate for the one requested node, radius-1 region of %d nodes; the forest rooted schedule does not apply to a cyclic DBN component); interval of state 1 %s" % (sq["var"], sq["status"], sq["proof_kind"], len(sq["H"] or []), [("%.4f" % float(__import__("fractions").Fraction(x))) for x in (sq["interval_state1"] or [])])
                    elif d.get("certified"):
                        det = "max width %s over %d blocks" % (d["certified"]["max_width"], d["certified"]["free_vars_total"])
                w("| %s | %s | %s | %.2f | %s |" % (r["case"], r["label"], r["status"], r["supervisor_wall_s"], det))
            w("\nRooted vs all-query correctness on DBN_15 (var 25): the single-query certificate and the all-query certificate both carry transport radius z = 1 and publish the trivial interval [0, 1] for the probed state; they agree and are both valid. The single-query dispatch certified one region (0.20 s complete response) instead of 42 (1.95 s). The forest rooted-inward schedule itself was exercised and validated on the saved forest controls (REPLAY4, section 7), not on an external case: no external case was a forest.")
        if load(S, "DIAGNOSTICS_FIRST_PASS_ROWS.json"):
            w("\nA first diagnostics pass wrote all DBN_15 probes into one directory (amendment 3): its NUMERICAL ARTIFACTS ARE LOST (overwritten, unrecoverable); only its ledger receipts survive (CELLS_LEDGER.jsonl rows, DIAGNOSTICS_FIRST_PASS_ROWS.json, DIAGNOSTICS_prior_overwritten_artifacts.json). The table above is the labelled rerun; it does not restore the originals.")
        if DG.get("B_repetitions"):
            w("\nConditional repetition subset (%s):\n" % DG["B_repetitions"][0]["label"].rsplit("_rep", 1)[0]); w("| case | arm | rep | status | complete response s | peak RSS MB |"); w("|---|---|---|---|---|---|")
            for r in DG["B_repetitions"]:
                w("| %s | %s | %s | %s | %s | %.0f |" % (r["case"], r["arm"], r["label"][-1], r["status"], ("%.2f" % r["complete_response_s"]) if r.get("complete_response_s") else "—", (r.get("peak_tree_rss_bytes") or 0) / 1e6))
    if AM:
        for k, a in AM.items():
            w("\n**%s** (%s): %s %s Exposed before: %d cells; reruns: %s. %s" % (k, a.get("kind"), a.get("what") or a.get("finding") or "", ("Repair: " + a["repair"]) if a.get("repair") else "", len(a.get("exposed_before_amendment", [])), [(r["case"], r["status"]) for r in a.get("reruns", [])], ("Effect on saved results: " + a["effect_on_saved_results"]) if a.get("effect_on_saved_results") else ""))
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
        w("\nCampaign total = %d nonnested top-level receipts counted once = **%.9f s**; nested cell sums (inside the stage supervisors, not added): %s; over-allocation: %s. Separate prospective REPAIR ledger (review of 7 Nov 2026, 1,800 s allowance): %.3f s in %d receipts. Remaining envelope %.3f s. The earlier 4,458.4 s figure was stale (amendment 8)." % (BL["nonnested_receipts"], BL["total_charged_s"], BL["nested_cell_sums_s_not_added"], BL.get("over_allocation") or "none", BL["repair_ledger_2026-11-07"]["charged_s"], BL["repair_ledger_2026-11-07"]["receipts"], BL["remaining_s"]))
        RC = load(S, "RECONCILIATION.json", {})
        if RC:
            w("\nRow reconciliation against the current manifest (code hash %s): %d cells satisfied by their own row, %d inherited from an explicitly declared predecessor (amendment with unchanged arm semantics), %d unsatisfied. %s" % (RC["manifest_code_hash"][:12], RC["own"], RC["inherited"], len(RC["unsatisfied"]), RC.get("note", "")))
    # ---- 10. decision
    w("\n## 10. Decision and prioritized next steps (from the observed bottlenecks)\n")
    cb = [c for c in prim if c["arm"] == "CBI_NATIVE"]; un = sum(1 for c in cb if c["status"] == "UNSUPPORTED_REPRESENTATION"); ad = [c for c in cb if c["status"] in ("CERTIFIED", "VALID_BUT_TOO_WIDE")]
    md = [c for c in prim if c["arm"] == "MDI_EXISTING"]; mdc = [c for c in md if c["status"] == "CERTIFIED"]; mdc_cases = sorted({c["case"] for c in mdc}); mdc_b = sorted({c["case"] for c in mdc if c["stage"] == "breadth"})
    def ex_of(case):
        e = next((x for x in prim if x["arm"] == "EXACT" and x["case"] == case and x["stage"] == "breadth"), None); return (e["status"], e.get("complete_response_s")) if e else (None, None)
    ex_rows = {case: ex_of(case) for case in mdc_cases}; ex_ok = [c for c, (st_, t) in ex_rows.items() if st_ == "COMPLETE"]; ex_not = [c for c, (st_, t) in ex_rows.items() if st_ != "COMPLETE"]
    w("1. **Most CBI_NATIVE failures are representation failures** (%d of %d cells refused by the adapter; %d admitted, %d certified). The FIRST blockers are, in order of cells: %s. They occur in the %s families. A first blocker is not a guarantee of admission once removed (item 5). The frustrated-gauge blocker (Grids, DBN) is removable at the representation layer by per-edge signed couplings (item 5); the nonbinary / arity blockers are not a proved small extension." % (un, len(cb), len(ad), sum(1 for c in ad if c["status"] == "CERTIFIED"), ", ".join("%s ×%d" % kv for kv in sorted((BK.get("cbi_native", {}).get("by_class") or {}).items(), key=lambda kv: -kv[1])) if BK else "see BLOCKERS.json", ", ".join(f for f, d in (BK.get("cbi_native", {}).get("by_family_class") or {}).items() if "nonbinary domains" in d or "remaining high arity" in d) if BK else "—"))
    w("2. **Where CBI_NATIVE was admitted (DBN_15, DBN_16) the bounds are wide while the exact arms' answers are available**: the failed term is the boundary / original-law comparison followed by the refusal of the enlarged region. The regional solves (d = 1 kernels, degree one already exact) carry publication-precision error only, so an anchored-transfer expansion (Theorem 4) cannot remove an error that is already zero; and the existing nonbacktracking contraction (Theorem 2) is not a rescue under the saved coefficients either: with exact rational arithmetic every nonbacktracking row sum is at least about 6.87 (DBN_15) and 8.17 (DBN_16), so the spectral radius exceeds one and no contraction holds (reviewer's computation, confirmed below in BLOCKERS / ATTRIBUTION). Finite nonbacktracking comparison stays valid; what is ruled out is the hoped-for contraction with these coefficients. The open question is a sharper (field-sensitive or nonlinear) boundary certificate; it is not resolved by implementing either unimplemented theorem.")
    w("3. **MDI_EXISTING certifies %d distinct cases of %d** (%d invocations: %d at 20 s; %s only at 120 s), all by the dense identity FALLBACK route (no structural transformation route succeeded), the slowest in %s s; it refuses the rest before admission by its checker-wall forecast or byte cap, and on the Protein family and three bnlearn networks its exact preprocessing refuses factors above the locally verifiable cap. Its certified answers are useful AND fast where its admission accepts; the measured implementation cost that blocks the rest is the exact-aggregation checker forecast, a candidate for the next bounded engineering pass." % (len(mdc_cases), len({c["case"] for c in md if c["stage"] == "breadth"}), len(mdc), len(mdc_b), ", ".join(c for c in mdc_cases if c not in mdc_b) or "none", ("%.1f" % max(c["complete_response_s"] for c in mdc)) if mdc else "—"))
    w("4. **Our methods work where baselines are already cheap**: of the %d cases MDI_EXISTING certified, libDAI junction tree (R1) completed %d within the 20 s breadth budget (%s)%s, and WMB / IJGP reached exact-by-i-bound outputs on most of them. No case in this panel shows a certified answer that an exact baseline could not produce within the same budget. This is stated as the finding; no held-out follow-up is proposed for a family that showed promise, because none did." % (len(mdc_cases), len(ex_ok), ", ".join("%s %.2f s" % (c, ex_rows[c][1]) for c in ex_ok), ("; EXACT did not complete on %s" % ", ".join("%s (%s)" % (c, ex_rows[c][0]) for c in ex_not)) if ex_not else ""))
    w("5. Research position after the sweep and its review: useful external coverage and competitive performance have NOT been demonstrated for CBI; MDI's successful cells all used its dense fallback; the benchmark exposes both interface restrictions and a difficult conditional-error bound. The recorded blocker counts are FIRST blockers, not guarantees that a nonbinary / higher-arity port would admit those cases (arbitrary tables need an exact representation, consistency constraints, query maps and a cost analysis; partial-coordinate consistency can introduce hard zeros between blocks, so the positive-law premise cannot be assumed). One genuinely bounded, exactly provable representation extension exists: per-edge SIGNED r in (-1, 1) for positive binary tables with rational-square cross-ratios (t = sqrt(ad/(bc)), r = (t-1)/(t+1), g = (1, ct/a), h = (a/(1+r), b/(1-r)); entrywise F = g h K_r; no global flip consistency needed; influence and Fourier tails use |r|; coarsening premises separately checked; negative interior edges NOT treated as near-equality). It would admit the six sign-refused Grids / DBN cases at the representation layer and promises neither useful width nor speed; it is not part of this repair. No held-out follow-up is proposed; none of the above is a claim of future competitiveness.")
    open(os.path.join(S, "REPORT.md"), "w").write("\n".join(L) + "\n"); print("REPORT.md written (%d lines)" % len(L))


if __name__ == "__main__":
    main(os.path.abspath(sys.argv[1]))
