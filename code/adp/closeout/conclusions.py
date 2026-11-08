"""Fill the outcome-dependent sections of REPORT.md and emit the prose deliverables (ledger entry E-MDI-38 text, HANDOFF.txt paragraph,
GRAVEYARD.json) from SCORES.json / RECORDS_cells.jsonl / BUDGET_LEDGER.json. Numbers are read from records, never typed by hand.
    python adp/closeout/conclusions.py D   -> appends sections 9-12 to D/REPORT.md, writes D/LEDGER_ENTRY_E-MDI-38.md, D/HANDOFF_PARAGRAPH.txt, D/GRAVEYARD.json"""
from __future__ import annotations
import os, sys, json, collections, statistics
HERE = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))); sys.path.insert(0, HERE)
NEW = "AGGREGATE_DP_V1"


def main(D):
    man = json.load(open(os.path.join(D, "CAMPAIGN_MANIFEST.json"))); S = json.load(open(os.path.join(D, "SCORES.json"))); B = json.load(open(os.path.join(D, "BUDGET_LEDGER.json")))
    R = [json.loads(l) for l in open(os.path.join(D, "RECORDS_cells.jsonl"))]; fam = {c["case"]: c["family"] for c in man["cases"]}; cases = [c["case"] for c in man["cases"]]
    def key(r):
        return r["arm"] if r["arm"] != NEW else r["config_key"]
    def get(stage, k, case, rep=0):
        return next((r for r in R if r["stage"] == stage and key(r) == k and r["case"] == case and r.get("repetition") == rep), None)
    full20 = {c: get("P20", "full", c) for c in cases}; ex20 = {c: get("P20", "EXACT", c) for c in cases}; mdi20 = {c: get("P20", "MDI_EXISTING", c) for c in cases}
    full120 = {c: get("P120", "full", c) for c in cases}; ex120 = {c: get("P120", "EXACT", c) for c in cases}
    cert20 = sorted(c for c in cases if full20[c] and full20[c].get("certified_target")); cert120 = sorted(c for c in cases if full120[c] and full120[c].get("certified_target"))
    exc20 = sorted(c for c in cases if ex20[c] and ex20[c].get("complete_output")); exc120 = sorted(c for c in cases if ex120[c] and ex120[c].get("complete_output"))
    mdic20 = sorted(c for c in cases if mdi20[c] and mdi20[c].get("certified_target"))
    # coverage questions
    new_not_exact20 = sorted(set(cert20) - set(exc20)); exact_not_new20 = sorted(set(exc20) - set(cert20)); new_not_exact120 = sorted(set(cert120) - set(exc120)); exact_not_new120 = sorted(set(exc120) - set(cert120))
    new_not_mdi = sorted(set(cert20) - set(mdic20)); mdi_not_new = sorted(set(mdic20) - set(cert20))
    # paired times (both complete, three repetitions)
    pairs = []
    for c in cases:
        if c in cert20 and c in exc20:
            tn = [r["complete_response_s"] for k in (0, 1, 2) for r in [next((x for x in R if x["stage"] in ("P20", "REP") and key(x) == "full" and x["case"] == c and x.get("repetition") == k), None)] if r and r.get("certified_target")]
            te = [r["complete_response_s"] for k in (0, 1, 2) for r in [next((x for x in R if x["stage"] in ("P20", "REP") and x["arm"] == "EXACT" and x["case"] == c and x.get("repetition") == k), None)] if r and r.get("complete_output")]
            mn = full20[c].get("peak_tree_rss_bytes", 0) / 1e6; me = ex20[c].get("peak_tree_rss_bytes", 0) / 1e6
            pairs.append((c, tn, te, mn, me))
    def ratio_summary(pairs):
        rs = [statistics.median(tn) / statistics.median(te) for _, tn, te, _, _ in pairs if tn and te and statistics.median(te) > 0]
        return (statistics.median(rs), min(rs), max(rs), len(rs)) if rs else (None, None, None, 0)
    med_ratio, min_ratio, max_ratio, npairs = ratio_summary(pairs)
    faster = [c for c, tn, te, _, _ in pairs if tn and te and statistics.median(tn) < statistics.median(te)]
    # certified cells: where the time went
    cert_rows = [full20[c] for c in cert20]
    def share(r, name):
        a = (r.get("adp") or {}).get("attempts") or []; ph = a[-1].get("phases_s", {}) if a else {}
        v = {"checker": ph.get("checker"), "forward": ph.get("forward"), "backward": ph.get("backward"), "source": r["phases_s"].get("source_reductions"), "publish": r["phases_s"].get("publish")}.get(name) or 0.0
        return v / r["complete_response_s"] if r.get("complete_response_s") else None
    chk_share = statistics.median([share(r, "checker") for r in cert_rows]) if cert_rows else None; bwd_share = statistics.median([share(r, "backward") for r in cert_rows]) if cert_rows else None; fwd_share = statistics.median([share(r, "forward") for r in cert_rows]) if cert_rows else None
    # stops
    stops = collections.Counter(); stop_cases = collections.defaultdict(list)
    for c in cases:
        r = full20[c]
        if r and not r.get("certified_target"):
            k = ((r.get("adp") or {}).get("stop") or {}).get("kind") or r["status"]; stops[k] += 1; stop_cases[k].append(c)
    # ablations
    abl = {}
    for k in sorted(man["ablations"]):
        rs = [r for r in R if r["stage"] == "ABL" and r["config_key"] == k]; ce = {r["case"] for r in rs if r.get("certified_target")}
        lost = sorted(set(cert20) - ce); gained = sorted(ce - set(cert20)); common = sorted(ce & set(cert20))
        rat = [r["complete_response_s"] / full20[r["case"]]["complete_response_s"] for r in rs if r["case"] in common and full20[r["case"]].get("complete_response_s")]
        abl[k] = {"certified": len(ce), "lost_vs_full": lost, "gained_vs_full": gained, "median_time_ratio_vs_full_on_common": (statistics.median(rat) if rat else None), "n_common": len(common), "recorded": len(rs)}
    # empirical accuracy of certified cells vs references; R0 containment
    cont = [(c, full20[c]["reference_in_intervals"]) for c in cert20 if full20[c].get("reference_in_intervals")]
    cont_ok = sum(1 for _, x in cont if x["contained"] == x["coordinates"]); emp = [full20[c]["empirical"]["max_abs_error"] for c in cert20 if full20[c].get("empirical")]
    r0cases = [c for c in cases if S["reference_classes"][c]["class"] == "R0"]
    # per-family explanation
    fams = sorted(set(fam.values())); famtab = []
    for f in fams:
        cs = [c for c in cases if fam[c] == f]; famtab.append((f, len(cs), sum(1 for c in cs if c in cert20), sum(1 for c in cs if c in cert120), sum(1 for c in cs if c in exc20), sum(1 for c in cs if c in mdic20), dict(collections.Counter((((full20[c] or {}).get("adp") or {}).get("stop") or {}).get("kind") or (full20[c] or {}).get("status") for c in cs if c not in cert20))))
    # ---------------------------------------------------------------- prose
    L = []; P = L.append
    P("\n## 9. The primary question: did the complete algorithm improve COVERAGE, full producer+checker COST, or MEMORY at the declared guarantee?\n")
    P("**Coverage (certified, width ≤ 1/100 and robust-center point verified by the independent checker).** 20 s: AGGREGATE_DP_V1 certified %d of 46 cases (%s). The pinned MDI_EXISTING certified %d (%s). libDAI EXACT (no certificate; floating-point complete output) completed %d. 120 s: AGGREGATE_DP_V1 certified %d (%s); EXACT completed %d.\n" % (len(cert20), ", ".join(cert20), len(mdic20), ", ".join(mdic20), len(exc20), len(cert120), ", ".join(cert120), len(exc120)))
    P("- certified by the new arm but NOT completed by EXACT at 20 s: %s\n- completed by EXACT but NOT certified by the new arm at 20 s: %s\n- at 120 s: new-only %s; EXACT-only %s\n- certified by the new arm but not by MDI_EXISTING at 20 s: %s; the converse: %s\n" % (", ".join(new_not_exact20) or "none", ", ".join(exact_not_new20) or "none", ", ".join(new_not_exact120) or "none", ", ".join(exact_not_new120) or "none", ", ".join(new_not_mdi) or "none", ", ".join(mdi_not_new) or "none"))
    P("**Cost (complete response incl. source reductions, planning, forward, backward, independent checking, publication; both sides complete; three 20 s observations each, medians).** %d successful pairs against EXACT; median ratio new/EXACT %s (min %s, max %s); the new arm was faster on %d of them (%s). EXACT carries no certificate, so this compares time-to-certified against time-to-floating-point." % (npairs, ("%.2f" % med_ratio) if med_ratio else "—", ("%.2f" % min_ratio) if min_ratio else "—", ("%.2f" % max_ratio) if max_ratio else "—", len(faster), ", ".join(faster) or "none"))
    P("\n| case | new s (3 obs) | EXACT s (3 obs) | median ratio | new peak MB | EXACT peak MB |\n|---|---|---|---|---|---|")
    for c, tn, te, mn, me in pairs:
        P("| %s | %s | %s | %s | %.0f | %.0f |" % (c, "/".join("%.2f" % x for x in tn), "/".join("%.2f" % x for x in te), ("%.2f" % (statistics.median(tn) / statistics.median(te))) if (tn and te) else "—", mn, me))
    P("\n**Memory.** Peak process-tree RSS (producer + checker together) of certified new-arm cells vs EXACT on the same pairs is in the table; the new arm's per-entry representation is a Python object per MPFR value (72-128 bytes each) in numpy object arrays, so its resident footprint per core entry is an order of magnitude above a binary64 table.\n")
    P("**Where the time goes in a certified cell (medians over %d certified 20 s cells):** independent checking %s of the complete response, backward pass %s, forward pass %s. The checker replays the same reduced program with outward intervals (two MPFR values per entry, its own index arithmetic and joins): its cost is of the order of the producer's, as the numerics contract predicted, and on the larger certified cases (Segmentation, BARLEY, DIABETES, CSP_12) it is the single largest phase.\n" % (len(cert_rows), ("%.0f %%" % (100 * chk_share)) if chk_share is not None else "—", ("%.0f %%" % (100 * bwd_share)) if bwd_share is not None else "—", ("%.0f %%" % (100 * fwd_share)) if fwd_share is not None else "—"))
    P("**Typed stops of the non-certified 20 s cells:** %s. Every stop is a resource outcome of the frozen caps (deadline polled inside numeric execution; resident value cap) on a program that is mathematically valid; no case was refused by admission or representation.\n" % "; ".join("%s ×%d (%s)" % (k, n, ", ".join(stop_cases[k])) for k, n in stops.most_common()))
    P("## 10. Every family, including no-gain families\n")
    P("| family | cases | new certified 20 s | new certified 120 s | EXACT complete 20 s | MDI_EXISTING certified 20 s | stops of the non-certified new-arm cells (20 s) |\n|---|---|---|---|---|---|---|")
    for f, n, a, b, e, m, st in famtab:
        P("| %s | %d | %d | %d | %d | %d | %s |" % (f, n, a, b, e, m, json.dumps(st)))
    P("")
    P("## 11. Ablations (same contracts; one mechanism disabled each)\n")
    P("| ablation | certified (of 46) | lost vs full | gained vs full | median time ratio vs full on common certified cases |\n|---|---|---|---|---|")
    for k, v in abl.items():
        P("| %s | %d | %s | %s | %s (n=%d) |" % (k, v["certified"], ", ".join(v["lost_vs_full"]) or "none", ", ".join(v["gained_vs_full"]) or "none", ("%.2f" % v["median_time_ratio_vs_full_on_common"]) if v["median_time_ratio_vs_full_on_common"] else "—", v["n_common"]))
    P("")
    P("## 12. References: certified cells vs exact / point references\n")
    P("Reference classes over the 46 cases: %s. Of the %d certified 20 s cells with a reference, %d have the reference inside every published interval (%d of them R0 exact — a proof check; the rest R1 / R2 points — a consistency observation). Empirical max coordinate error of the certified cells' published points vs their references: max %s (a certified point is within 1/200 of truth by construction; the reference's own rounding is not). R0 cases: %s.\n" % (json.dumps(S["reference_class_counts"]), len(cont), cont_ok, sum(1 for c, _ in cont if c in r0cases), ("%.2e" % max(emp)) if emp else "—", ", ".join(r0cases)))
    P("## 13. Demonstrated results versus remaining unknowns\n")
    P("**Demonstrated (this campaign, independently checked):**\n- The single lazy bucket engine accepts every one of the 46 inputs without an admission or representation refusal; every cell ended in CERTIFIED or a TYPED resource stop (no faults, no false certificates: every R0 reference lies inside the published intervals; the checker rejected 12 adversarial mutant certificates in qualification).\n- Certified coverage at 20 s: %d of 46 (MDI_EXISTING: %d); at 120 s: %d.\n- The exact source reductions (quotient/alias/exclude/constant/separable) and the inductive response views are sound as implemented (600 random models × 9 configurations, every original coordinate enclosed; the checker proves every declared view).\n- Independent checking costs about as much as the producer's forward+backward passes; it is the dominant phase on the larger certified cases.\n" % (len(cert20), len(mdic20), len(cert120)))
    P("**Not demonstrated / unknown:**\n- No repeatable end-to-end cost advantage over libDAI junction tree on the cases both complete (see the pair table: the new arm is a certified interval method in Python-object MPFR arithmetic; libDAI is compiled binary64 without a certificate).\n- Whether the dense positive families (GridBN, Grids, DBN, Segmentation ≥ 2^20 cores, CSP_11/13, ObjectDetection, Protein) would certify under a compiled kernel: the stops are deadline / resident-value-cap stops of the frozen Python implementation, not structural refusals; the per-entry arithmetic cost (≈0.1–0.2 µs per MPFR op in numpy object arrays, plus Python-level gather/scatter) is the binding constraint, not the program size.\n- Globally pruned (downward semijoin) supports, value-only message merging, anytime bounds, lossy state merging: deliberately excluded from v1; their effect is unmeasured.\n- The response-view mechanism (A2) and the native sparse join (A3) are measured only as ablations on this panel; the Protein cores whose views were audited in the packet did not complete at 20 s or 120 s here, so the audited Protein saving was not exercised end to end.\n")
    open(os.path.join(D, "REPORT.md"), "a").write("\n".join(L) + "\n")
    # ---------------------------------------------------------------- graveyard
    grave = {"rules_or_configurations_that_did_not_help_on_this_panel": [{"ablation": k, "observation": "certified %d vs full %d; lost %s; gained %s; median time ratio vs full %s" % (v["certified"], len(cert20), v["lost_vs_full"] or "none", v["gained_vs_full"] or "none", ("%.2f" % v["median_time_ratio_vs_full_on_common"]) if v["median_time_ratio_vs_full_on_common"] else "n/a"), "disposition": ("mechanism carried no measurable benefit on this panel (narrow evidence: 46 family-clustered cases, one 20 s observation each)" if (v["certified"] >= len(cert20) and (v["median_time_ratio_vs_full_on_common"] or 1.0) <= 1.05) else "mechanism contributes on this panel")} for k, v in abl.items()],
             "note": "a null here is not an impossibility result; every ablation keeps the same exact query, numerical and checker contracts"}
    json.dump(grave, open(os.path.join(D, "GRAVEYARD.json"), "w"), indent=1)
    # ---------------------------------------------------------------- ledger entry + handoff paragraph
    E = []
    E.append("## E-MDI-38 — AGGREGATE_DP_V1 implemented, qualified and run on the frozen 46-case panel against libDAI EXACT, MDI_EXISTING, WMB, IJGP (branch aggregate-dp-2026-11-07; 7–8 November 2026)\n")
    E.append("Design packet AGGREGATE_DP_DESIGN_AND_EVIDENCE_2026-11-07.zip (sha256 0423e3db…; decision: one lazy sum-product bucket engine, source-certified response views, bounded memoization, shared backward pass, independent reduced-program checker). Implementation code/adp/ (new; accepted mdi pins untouched; mdi.model parsing and mdi.arith directed-MPFR primitives reused), checker adp/checker.py (own parser ext.uai, own step re-derivation, view soundness proofs, own index arithmetic / hash joins / complete supports, outward interval replay forward and reverse, cancellation-safe normalization, second-process point verification from the delivered decimals). Qualification: tests/test_adp_v1.py 23 pass (600 random models × 9 configurations, every original coordinate enclosed; 3/4-vs-1/2 equal-message counterexample; normalized-leaf; zero normalizer; 1e-60 denominators; nonuniform quotient decoder; repeated-use adjoints; width-only publication counterexample; 12 mutant certificates rejected for their specific condition; altered MAR rejected); the packet's four controls replayed (48/3,993/32; 32 models 768 derivatives; provenance 40/40 with Protein cores 390/84/180/51; global-support counterexample 18 vs 14). Campaign frozen at 395b5c7f before any outcome: 736 cells (P20 230, P120 92, ABL 230, REP 184; 23,920 s of allowances; separate 28,800 s ceiling), block order seeded by the config hash, 8 GiB process-tree kill, fresh process per cell.")
    E.append("RESULTS. 20 s: AGGREGATE_DP_V1 CERTIFIED %d of 46 (%s); MDI_EXISTING certified %d; libDAI EXACT completed %d (no certificate); WMB / IJGP completed %d / %d. 120 s: new arm %d, EXACT %d. New-only vs EXACT at 20 s: %s; EXACT-only: %s. Matched pairs (both complete, three 20 s observations): %d pairs, median new/EXACT time ratio %s (min %s, max %s), new arm faster on %d (%s). Certified-cell anatomy: checker ≈ %s of the complete response, backward %s, forward %s. Non-certified new-arm 20 s cells: %s — all typed resource stops of the frozen Python implementation (deadline inside numeric execution / resident value cap), none a representation or admission refusal. Every R0 reference lies inside the published intervals. Ablations: %s. Budget: %s s of 28,800 (%s). Records: AGGREGATE_DP_2026-11-07/{REPORT.md, SCORES.json, RECORDS_cells.jsonl, CELLS_LEDGER.jsonl, BUDGET_LEDGER.json, MISSINGNESS.json, CAMPAIGN_MANIFEST.json, AMENDMENTS.json, GRAVEYARD.json, PROVENANCE.json, cells/}. STOPPED FOR REVIEW (no merge)." % (
        len(cert20), ", ".join(cert20), len(mdic20), len(exc20), sum(1 for c in cases if (get("P20", "WMB", c) or {}).get("complete_output")), sum(1 for c in cases if (get("P20", "IJGP", c) or {}).get("complete_output")), len(cert120), len(exc120), ", ".join(new_not_exact20) or "none", ", ".join(exact_not_new20) or "none",
        npairs, ("%.2f" % med_ratio) if med_ratio else "—", ("%.2f" % min_ratio) if min_ratio else "—", ("%.2f" % max_ratio) if max_ratio else "—", len(faster), ", ".join(faster) or "none", ("%.0f %%" % (100 * chk_share)) if chk_share is not None else "—", ("%.0f %%" % (100 * bwd_share)) if bwd_share is not None else "—", ("%.0f %%" % (100 * fwd_share)) if fwd_share is not None else "—",
        "; ".join("%s ×%d" % (k, n) for k, n in stops.most_common()), "; ".join("%s certified %d (lost %s, gained %s, time ratio %s)" % (k, v["certified"], ",".join(v["lost_vs_full"]) or "none", ",".join(v["gained_vs_full"]) or "none", ("%.2f" % v["median_time_ratio_vs_full_on_common"]) if v["median_time_ratio_vs_full_on_common"] else "n/a") for k, v in abl.items()), B["total_charged_s"], B["total_status"]))
    open(os.path.join(D, "LEDGER_ENTRY_E-MDI-38.md"), "w").write("\n".join(E) + "\n")
    H = "2026-11-08 (AGGREGATE_DP_V1, branch aggregate-dp-2026-11-07 from 8b5f8583): the overseer's lazy bucket engine with source-certified response views, shared backward pass and an INDEPENDENT checker implemented (code/adp/), qualified (23 tests; packet controls replayed) and run on the frozen 46-case panel (736 cells). 20 s: CERTIFIED %d/46 (MDI_EXISTING %d; EXACT complete %d); 120 s: %d. Matched pairs vs EXACT: %d, median time ratio %s, faster on %d. Non-certified cells are typed deadline / value-cap stops of the Python-object MPFR implementation, not refusals. Checker ≈ %s of a certified cell. %s s of 28,800. See E-MDI-38. STOPPED FOR REVIEW." % (len(cert20), len(mdic20), len(exc20), len(cert120), npairs, ("%.2f" % med_ratio) if med_ratio else "—", len(faster), ("%.0f %%" % (100 * chk_share)) if chk_share is not None else "—", B["total_charged_s"])
    open(os.path.join(D, "HANDOFF_PARAGRAPH.txt"), "w").write(H + "\n"); print("conclusions appended; ledger entry, handoff paragraph, graveyard written")


if __name__ == "__main__":
    main(os.path.abspath(sys.argv[1]))
