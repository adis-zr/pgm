"""DIAGNOSTIC REPORT (spec of 7 Nov 2026): population and coverage first, every family and arm accounted for, then prespecified comparisons,
mechanisms with evidence / counterevidence, the 'collected but not explanatory' ledger, case dispositions, missingness, budget.
Reads ONLY the record files produced by diag_extract.py / census.py / ledger.py.   python bench/diag_report.py SWEEP_DIR -> diag_2026-11-07/DIAG_REPORT.md"""
from __future__ import annotations
import os, sys, json, math, collections, statistics as st
HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ARMS = ["CBI_NATIVE", "MDI_EXISTING", "LBP", "WMB", "IJGP", "SAMPLESEARCH", "EXACT", "PGMAX_SUMPRODUCT_BP"]; RUNNABLE = [a for a in ARMS if a != "SAMPLESEARCH"]
FAMS = ["GridBN", "Grids", "Pedigree", "Promedus", "CSP", "DBN", "ObjectDetection", "Segmentation", "Protein", "bnlearn"]
GOOD = {"CERTIFIED", "VALID_BUT_TOO_WIDE", "COMPLETE", "COMPLETE_UNCONVERGED", "CERTIFIED_SINGLE_QUERY", "VALID_BUT_TOO_WIDE_SINGLE_QUERY"}


def ST(i):
    """reconciled status label (the wrapper's own label stays in i['status'])"""
    return i.get("status_reconciled") or i.get("status")


def jl(p):
    return [json.loads(l) for l in open(p)] if os.path.exists(p) else []


def load(p, d=None):
    return json.load(open(p)) if os.path.exists(p) else d


def med(xs):
    xs = [x for x in xs if x is not None]; return ("%.3g" % st.median(xs)) if xs else "—"


def spearman(x, y):
    """rank correlation on paired finite values; returns (rho, n) or (None, n)"""
    pts = [(a, b) for a, b in zip(x, y) if a is not None and b is not None and all(isinstance(v, (int, float)) and math.isfinite(v) for v in (a, b))]
    n = len(pts)
    if n < 5:
        return None, n
    def ranks(v):
        o = sorted(range(len(v)), key=lambda i: v[i]); r = [0.0] * len(v); i = 0
        while i < len(v):
            j = i
            while j + 1 < len(v) and v[o[j + 1]] == v[o[i]]:
                j += 1
            for k in range(i, j + 1):
                r[o[k]] = (i + j) / 2 + 1
            i = j + 1
        return r
    rx, ry = ranks([p[0] for p in pts]), ranks([p[1] for p in pts]); mx, my = st.mean(rx), st.mean(ry)
    num = sum((a - mx) * (b - my) for a, b in zip(rx, ry)); den = math.sqrt(sum((a - mx) ** 2 for a in rx) * sum((b - my) ** 2 for b in ry))
    return (num / den if den else None), n


def main(S):
    D = os.path.join(S, "diag_2026-11-07"); cases = jl(os.path.join(D, "RECORDS_cases.jsonl")); invs = jl(os.path.join(D, "RECORDS_invocations.jsonl")); qs = jl(os.path.join(D, "RECORDS_queries.jsonl"))
    miss = load(os.path.join(D, "MISSINGNESS.json"), {}); BL = load(os.path.join(S, "BUDGET_LEDGER.json"), {}); dman = load(os.path.join(D, "DIAG_MANIFEST.json")); sd = load(os.path.join(D, "SCORES_DIAG.json"), {}); gates = load(os.path.join(D, "MDI_SELECTOR_GATE_CENSUS_saved.json"), {})
    ovh = load(os.path.join(D, "controls", "INSTRUMENTATION_OVERHEAD.json"), {}); prespec = load(os.path.join(D, "FEATURE_COMPARISONS_PRESPEC.json"), {}); AM = load(os.path.join(S, "AMENDMENTS.json"), {})
    acc = {c["case"]: c for c in cases if c.get("accessible")}; L = []; w = L.append
    hist = [i for i in invs if i["kind"] == "historical_primary"]; newA = [i for i in invs if i["kind"] == "diagnostic_A"]; newC = [i for i in invs if i["kind"] == "diagnostic_C"]; newB = [i for i in invs if i["kind"] == "diagnostic_B"]; newD = [i for i in invs if i["kind"] == "diagnostic_D"]; newE = [i for i in invs if i["kind"] == "diagnostic_E"]
    w("# Full-panel diagnostic of the external inference sweep (7 November 2026)\n")
    w("Branch `cbi-benchmark-sweep-2026-11-06`; diagnostic manifest frozen at code hash `%s` (commit `%s`) before any new primary-population measurement. Purpose: establish what happened, what was attempted, what was blocked and what the saved and new evidence can explain, across the WHOLE panel. No new algorithm, representation, policy change or corpus change. Observation, derivation, proof and conjecture are labelled.\n" % ((dman or {}).get("code_hash", "")[:12], str((dman or {}).get("commit", ""))[:12]))
    w("**Carried-forward corrected facts (reviewer, saved data):** ten distinct MDI-certified cases over fourteen invocations; thirteen untransformed (dense identity) invocations and one executed quotient (depth / Pedigree_13); zero support / quotient attempts in the 20 s breadth stage; one single-observation MDI timing advantage (1.803 vs 1.900 s complete response, depth Pedigree_13 vs libDAI); no established substantial repeatable external advantage; zero useful native CBI certifications. These motivate questions; they do not settle explanations.\n")
    # ---------------- 0. correctness closeout
    w("## 0. Correctness closeout (three remaining issues)\n")
    for k in ("amendment_9", "amendment_10", "amendment_11"):
        a = AM.get(k)
        if a:
            w("- **%s** (%s). Finding: %s Repair: %s %s" % (k, a.get("kind"), a.get("finding", "")[:400], a.get("repair", "")[:500], ("Effect on saved results: " + a["effect_on_saved_results"]) if a.get("effect_on_saved_results") else ""))
    w("\nControls: `tests/test_bench_adapters.py` (fixed-state variants int / str / float / fraction / bool / out-of-range / wrong state; both original exploits; contract subset / mismatch; harness identity: legitimate reuse, changed model / evidence / configuration / budget / query scope, changed-then-unchanged code history); 39 tests pass (`diag_2026-11-07/repairs/TEST_RECEIPT_pytest_verbose_r3.txt`). Recheck by distinct directory: 9 saved native artifact directories (13 ledger rows; the overwritten first-pass directory carries 5 rows whose originals are LOST), all 9 pass adapter and verifier (`repairs/RECHECK_ADMITTED_distinct_dirs.json`). Reconciliation: 464 primary cells inherited through task-equal, equivalence-covered predecessor chains (4 via labelled amendment reruns), 0 unsatisfied.\n")
    # ---------------- 1. population and coverage
    w("## 1. Population and coverage\n")
    w("Intended slots 48 (Pedigree and CSP have 3 each: two inaccessible slots are recorded in the census and the case records). Accessible cases %d. Primary rows 464 (368 breadth, 96 depth) + 4 PGMax amendment reruns + 14 historical diagnostic rows = 482. Depth selection: the 12 frozen cases only; other cases were not scheduled for depth and are not depth failures.\n" % len(acc))
    w("### 1a. New diagnostic families: planned vs run (every planned cell has a value or a typed reason)\n"); w("| family | planned cells | run | COMPLETED | killed (timeout / memory) | NOT_RUN_BUDGET | NOT_APPLICABLE | charged s | cap s |"); w("|---|---|---|---|---|---|---|---|---|")
    drows = [i for i in invs if i["kind"].startswith("diagnostic_")]
    for fam in ("A", "B", "C", "D", "E"):
        rs = [i for i in drows if i.get("family_code") == fam]; planned = (dman or {}).get("counts", {}).get(fam, 0)
        w("| %s | %d | %d | %d | %d | %d | %d | %.1f | %s |" % (fam, planned, sum(1 for r in rs if r.get("cell_id")), sum(1 for r in rs if r.get("outcome") == "COMPLETED"), sum(1 for r in rs if r.get("outcome") in ("TIMEOUT_KILL", "MEMORY_KILL")), sum(1 for r in rs if r.get("outcome") == "NOT_RUN_BUDGET"), sum(1 for r in rs if r.get("outcome") == "NOT_APPLICABLE"), sum((r.get("supervisor_wall_s") or 0) for r in rs), (dman or {}).get("caps_s", {}).get("family", {}).get(fam)))
    w("\n### 1b. Applicability by family × arm — HISTORICAL breadth (20 s) and NEW family A (20 s, instrumented), status counts\n")
    def short(s):
        return {"UNSUPPORTED_REPRESENTATION": "UNSUP", "RESOURCE_LIMIT": "RLIM", "CERTIFIED": "CERT", "VALID_BUT_TOO_WIDE": "WIDE", "COMPLETE": "OK", "COMPLETE_UNCONVERGED": "OK~", "TIMEOUT": "TO", "FAILED": "FAIL", "ADMISSION_REFUSED": "ADM", "UNAVAILABLE": "N/A", "ENGINE_REFUSED_PREPROCESSING": "PREP", "CHECK_FAILED": "PREP*", "KILLED_MEMORY_KILL": "MEM", "KILLED_TIMEOUT_KILL": "TO!", "INVALID_OUTPUT": "INV", "INFEASIBLE_EVIDENCE": "Z=0", "NOT_RUN_BUDGET": "NRB", "NO_RECORD": "NOREC", "CERTIFIED_SINGLE_QUERY": "CERT1", "VALID_BUT_TOO_WIDE_SINGLE_QUERY": "WIDE1", "SINGLE_QUERY_VARIABLE_OBSERVED": "OBS", "SINGLE_QUERY_VARIABLE_FIXED": "FIX"}.get(s, str(s)[:6])
    w("| family (n) | " + " | ".join("%s hist / A" % a for a in RUNNABLE) + " |"); w("|---|" + "---|" * len(RUNNABLE))
    for fam in FAMS:
        cs = [c for c in acc.values() if c["family"] == fam]
        if not cs:
            continue
        row = []
        for arm in RUNNABLE:
            h = collections.Counter(short(ST(i)) for i in hist if i["stage"] == "breadth" and i["arm"] == arm and acc.get(i["case"], {}).get("family") == fam); a = collections.Counter(short(ST(i)) for i in newA if i["arm"] == arm and acc.get(i["case"], {}).get("family") == fam)
            row.append(" ".join("%s×%d" % kv for kv in h.most_common(3)) + " / " + (" ".join("%s×%d" % kv for kv in a.most_common(3)) or "—"))
        w("| %s (%d) | %s |" % (fam, len(cs), " | ".join(row)))
    w("\nCodes as in REPORT.md; PREP* = the wrapper's CHECK_FAILED label for the engine's preprocessing refusal; CERT1 / WIDE1 = single-query certificate; OBS = probe variable observed.")
    w("\n### 1c. Family-balanced and case-weighted complete-answer rates (A, new instrumented run) and historical breadth, per arm\n"); w("| arm | hist family-balanced | hist case-weighted | A family-balanced | A case-weighted | C family-balanced | C case-weighted |"); w("|---|---|---|---|---|---|---|")
    def rates(rows_, arm):
        fr = []; allc = [r for r in rows_ if r["arm"] == arm]
        for fam in FAMS:
            cs = [r for r in allc if acc.get(r["case"], {}).get("family") == fam]
            if cs:
                fr.append(sum(1 for r in cs if ST(r) in GOOD) / len(cs))
        return (st.mean(fr) if fr else float("nan")), ((sum(1 for r in allc if ST(r) in GOOD) / len(allc)) if allc else float("nan"))
    for arm in RUNNABLE:
        hb = rates([i for i in hist if i["stage"] == "breadth"], arm); ab = rates(newA, arm); cb = rates(newC, arm)
        w("| %s | %.2f | %.2f | %.2f | %.2f | %.2f | %.2f |" % (arm, *hb, *ab, *cb))
    # ---------------- 2. census
    w("\n## 2. Common model census (46 accessible cases; `CENSUS.jsonl`, schema `CENSUS_SCHEMA.json`; extractor census-2026-11-07-v1; total cost %.1f s)\n" % sum(((c.get("census") or {}).get("costs_s") or {}).get("total", 0) for c in cases if c.get("accessible")))
    w("| family | n | vars median | sliced entries median (max) | max arity (sliced) | nonbinary cases | support density median (sliced) | forced beyond evidence | MDI relations (fixed+merged) | min-fill width (primal, sliced+forced) | cycle rank median | log2 state space median |"); w("|---|---|---|---|---|---|---|---|---|---|---|---|")
    for fam in FAMS:
        cs = [c for c in acc.values() if c["family"] == fam]
        if not cs:
            continue
        g = lambda c, *ks: (lambda d: [d := (d or {}).get(k) for k in ks][-1])(c["census"])
        w("| %s | %d | %s | %s (%s) | %s | %d | %s | %s | %s | %s | %s | %s |" % (fam, len(cs), med([c["variables"] for c in cs]), med([g(c, "sliced", "table_entries_total") for c in cs]), max(g(c, "sliced", "table_entries_total") for c in cs), max(g(c, "sliced", "max_arity") for c in cs), sum(1 for c in cs if any(int(k) != 2 for k in c["domain_histogram"])), med([g(c, "sliced", "support_density") for c in cs]),
                                                                        " ".join(str(g(c, "forced_states", "beyond_evidence")) for c in cs), " ".join("%s+%s" % (g(c, "relations_mdi_quotient", "fixed"), g(c, "relations_mdi_quotient", "merged")) for c in cs), " ".join(str(g(c, "graph_sliced_plus_forced", "minfill", "induced_width_estimate")) for c in cs), med([g(c, "graph_sliced_plus_forced", "cycle_rank") for c in cs]), med([g(c, "graph_sliced_plus_forced", "log2_state_space") for c in cs])))
    w("\nNamed graph: primal graph of the evidence-sliced (plus proved-forced) factor scopes; min-fill is an ordering ESTIMATE of induced width, not treewidth and not inherent difficulty. Forced states by `prove_forced` (unary-slice zero exclusion); MDI relations by `mdi.quotient.recognize` (5 s cap): non-discovery is not absence.\n")
    w("### 2a. CBI obstruction profiles — every predicate on every case (blocker SETS, not first blockers)\n")
    bl = collections.Counter(tuple(sorted(c["census"]["cbi_obstructions"]["blockers_active"])) for c in acc.values()); w("| blocker set | cases |"); w("|---|---|")
    for k, v in bl.most_common():
        w("| %s | %d |" % (", ".join(k) if k else "(none: representable by the current adapter)", v))
    cnt = collections.Counter(b for c in acc.values() for b in c["census"]["cbi_obstructions"]["blockers_active"]); w("\nNon-exclusive counts over 46 cases: %s. Local vs global: 'inconsistent sign gauges' is the GLOBAL parity contradiction (odd repulsive cycle among square-cross-ratio pairs); the others are local. Per-case predicate values, witnesses (factor index, scope, table excerpt, cross-ratio, frustrated pair) in `CENSUS.jsonl` → `cbi_obstructions`. Failure of the present adapter is not impossibility of every representation.\n" % dict(cnt))
    # ---------------- 3. MDI gates
    w("## 3. MDI selector gates — saved records (what was attempted vs blocked), every MDI row\n")
    gc = collections.Counter(v["class"].split(":")[0] for k, v in gates.items() if k.endswith("|breadth")); gd = collections.Counter(v["class"].split(":")[0] for k, v in gates.items() if k.endswith("|depth"))
    w("Breadth (46): %s. Depth (12): %s. Probed at depth: %s. Executed routes: breadth dense ×9; depth dense ×4, quotient ×1 (Pedigree_13). PROVED gate behaviour (source `mdi/pipeline.py::_select_route`): probes start only when remaining wall ≥ window (20 s) + dense forecast + 30 s margin, so NO 20 s invocation can probe; the exact-zero gate bypasses zero-free laws (18 of 46 breadth cases); 7 cases are refused earlier by exact preprocessing; 2 have no dense reference plan under the byte cap (BN_31, Promedus_14); 1 stopped in dense planning; 1 was killed before a selector record (ObjectDetection_39). These are frozen-policy facts, not evidence that transformations were structurally impossible.\n" % (dict(gc), dict(gd), {k.split("|")[0]: v["class"] for k, v in gates.items() if k.endswith("|depth") and v["class"].startswith("PROBED")}))
    # ---------------- 4. family B
    w("## 4. Family B — existing transformations scheduled independently on every case (30 s / 8 GiB, diagnostic wrapper)\n")
    w("Gates intervened (named in every probe record): selector exact-zero gate (routines run on zero-free laws and record no-op), probe window and remaining-wall precondition (not applied), the 5 s per-routine wall caps raised to 30 s, dense-reference byte cap removed for the STRUCTURAL ordering only. Gates remaining: SUPPORT_MEM_CAP_BYTES (512 MiB), the routines' own refusals, MIN_REDUCTION_RATIO reported as the production verdict (not applied as a stop), and the full production admission in the EXECUTION phase. These are not a proposed policy and not matched 20 s speed claims.\n")
    w("| case | family | quotient: structural verdict | fixed+merged (free before→after) | ratio | exec outcome / s | support: structural verdict | sparse vs dense rows (ratio) | exec outcome / s |"); w("|---|---|---|---|---|---|---|---|---|")
    for case in sorted(acc, key=lambda x: (acc[x]["family"], x)):
        qv = next((i for i in newB if i["case"] == case and i.get("mechanism") == "quotient"), None); sv = next((i for i in newB if i["case"] == case and i.get("mechanism") == "support"), None)
        def qcell(i):
            if not i:
                return ("not run", "", "", "")
            s_ = i.get("structural") or {}; rr = s_.get("recognition") or {}; pr = s_.get("price") or {}; ex = i.get("execution") or {}
            return (str(s_.get("verdict") or i.get("probe_status") or i.get("status"))[:60], "%s+%s (%s→%s)" % (rr.get("fixed", "—"), rr.get("merged", "—"), rr.get("free_before", "—"), rr.get("free_after", "—")), ("%.2f" % pr["reduction_ratio"]) if pr.get("reduction_ratio") is not None else "—", ("%s / %.1f" % (ex.get("outcome"), ex.get("elapsed_s") or 0)) if ex.get("outcome") else str(ex.get("why", ""))[:40])
        def scell(i):
            if not i:
                return ("not run", "", "")
            s_ = i.get("structural") or {}; pr = s_.get("price") or {}; ex = i.get("execution") or {}; cnts = pr.get("counts") or {}
            return (str(s_.get("verdict") or i.get("probe_status") or i.get("status"))[:60], ("%s vs %s (%.2f)" % (cnts.get("enumerated_schedule_rows", "—"), pr.get("dense_enumerated_schedule_rows", "—"), pr.get("reduction_ratio", float("nan")))) if pr else "—", ("%s / %.1f" % (ex.get("outcome"), ex.get("elapsed_s") or 0)) if ex.get("outcome") else str(ex.get("why", ""))[:40])
        a1 = qcell(qv); a2 = scell(sv); w("| %s | %s | %s | %s | %s | %s | %s | %s | %s |" % (case, acc[case]["family"], *a1, *a2))
    # ---------------- 5. family A/C paired
    w("\n## 5. Families A and C — complete task vs one-variable query, paired per (case, arm), 20 s, same settings (every row ONE observation)\n")
    w("Query interface per arm: CBI_NATIVE and MDI_EXISTING native single-query (CBI: rooted / region dispatch for one block; MDI: `pipeline.solve(queries={v})`); LBP / EXACT / WMB / IJGP / PGMax: complete MAR followed by extraction, the ENTIRE cost charged (labelled). One chosen query does not characterize average query difficulty.\n")
    w("| arm | pairs | both complete | A status counts | C status counts | median A s | median C s | median C/A ratio (both complete) | pairs with C < 0.9 A | pairs with C > 1.1 A |"); w("|---|---|---|---|---|---|---|---|---|---|")
    for arm in RUNNABLE:
        A_ = {i["case"]: i for i in newA if i["arm"] == arm}; C_ = {i["case"]: i for i in newC if i["arm"] == arm}; pairs = [c for c in A_ if c in C_]
        both = [c for c in pairs if ST(A_[c]) in GOOD and ST(C_[c]) in GOOD and A_[c].get("complete_response_s") and C_[c].get("complete_response_s")]
        ratios = [C_[c]["complete_response_s"] / A_[c]["complete_response_s"] for c in both]
        w("| %s | %d | %d | %s | %s | %s | %s | %s | %d | %d |" % (arm, len(pairs), len(both), dict(collections.Counter(short(ST(A_[c])) for c in pairs)), dict(collections.Counter(short(ST(C_[c])) for c in pairs)), med([A_[c].get("complete_response_s") for c in both]), med([C_[c].get("complete_response_s") for c in both]), med(ratios), sum(1 for r in ratios if r < 0.9), sum(1 for r in ratios if r > 1.1)))
    # instrumented vs historical (same case/arm, different code versions: disclosed)
    w("\n### 5a. New instrumented A vs historical breadth (same case, arm, 20 s; DIFFERENT code versions and instrumentation: not a same-code A/B; one observation each)\n"); w("| arm | pairs both complete | median hist s | median A s | median A/hist | status changes hist→A |"); w("|---|---|---|---|---|---|")
    for arm in RUNNABLE:
        H_ = {i["case"]: i for i in hist if i["stage"] == "breadth" and i["arm"] == arm}; A_ = {i["case"]: i for i in newA if i["arm"] == arm}
        both = [c for c in A_ if c in H_ and ST(H_[c]) in GOOD and ST(A_[c]) in GOOD and H_[c].get("complete_response_s") and A_[c].get("complete_response_s")]
        chg = collections.Counter((short(H_[c]["status"]), short(ST(A_[c]))) for c in A_ if c in H_ and H_[c]["status"] != A_[c]["status"])
        w("| %s | %d | %s | %s | %s | %s |" % (arm, len(both), med([H_[c]["complete_response_s"] for c in both]), med([A_[c]["complete_response_s"] for c in both]), med([A_[c]["complete_response_s"] / H_[c]["complete_response_s"] for c in both]), dict(chg) or "none"))
    if ovh:
        w("\nInstrumentation overhead on the fixed controls (3 repetitions each, instrumented cells.py vs the campaign-era wrapper control, cross-version): %s. Disclosure: %s" % ({a: ("%.3f vs %.3f s" % (v["instrumented_median"], v["campaign_era_control_complete_response_s"] or float("nan"))) for a, v in ovh["results"].items()}, ovh["disclosure"]))
    # ---------------- 6. accuracy of new outputs
    w("\n## 6. Accuracy of the new outputs (A and C) against the ORIGINAL references, and D's expanded references kept separate\n")
    w("References: R0 exact (ASIA); R1 binary64 exact-algorithm POINT; R2 official 2014 POINT; new family-D libDAI outputs are R1 and are NOT independent of the EXACT arm (EXACT scored against them is a self-comparison and is marked). Contracts kept separate: empirical max |error| ≤ 0.005, certified width ≤ 0.01, convergence flag, output validity. Original-reference denominator: %s; expanded: %s; new R1 from D: %s.\n" % (sd.get("reference_classes_original"), sd.get("reference_classes_expanded"), sd.get("new_R1_from_D")))
    w("| arm | A scored (orig R0/R1) | A target met | A scored (expanded) | A target met | C scored (orig) | C target met | median max|err| A (orig) | worst-query cases (A, orig, err > 0.1) |"); w("|---|---|---|---|---|---|---|---|---|")
    for arm in RUNNABLE:
        def cnt_(rows_, key, cls_ok=("R0", "R1")):
            sc = [r for r in rows_ if r["arm"] == arm and isinstance(r.get(key), dict) and r[key].get("class") in cls_ok and r[key].get("max_abs_error") is not None and r[key].get("independent_of_arm", True)]
            return len(sc), sum(1 for r in sc if r[key].get("target_0.005_met")), [r[key]["max_abs_error"] for r in sc], [r["case"] for r in sc if r[key]["max_abs_error"] > 0.1]
        a1 = cnt_(newA, "accuracy_original_reference"); a2 = cnt_(newA, "accuracy_expanded_reference"); c1 = cnt_(newC, "accuracy_original_reference")
        w("| %s | %d | %d | %d | %d | %d | %d | %s | %s |" % (arm, a1[0], a1[1], a2[0], a2[1], c1[0], c1[1], med(a1[2]), ", ".join(a1[3][:6]) or "—"))
    w("\nReference-poor outputs (R3 / R2-only) stay visible in `RECORDS_invocations.jsonl` with `point_quality: UNKNOWN`; pairwise disagreement between heuristics on those cases is descriptive only (agreement is not truth).")
    # ---------------- 7. family D
    w("\n## 7. Family D — reference coverage (EXACT at 120 s on the %d cases lacking R0/R1 at freeze)\n" % len([i for i in newD]))
    w("| case | family | status | wall s | peak RSS GB | min-fill width est. | peak table log2 est. | new class |"); w("|---|---|---|---|---|---|---|---|")
    for i in sorted(newD, key=lambda x: (acc.get(x["case"], {}).get("family", ""), x["case"])):
        cz = (acc.get(i["case"]) or {}).get("census") or {}; mf = (cz.get("graph_sliced_plus_forced") or {}).get("minfill") or {}
        w("| %s | %s | %s | %.1f | %.2f | %s | %s | %s |" % (i["case"], acc.get(i["case"], {}).get("family"), i["status"], i.get("supervisor_wall_s") or 0, (i.get("peak_tree_rss_bytes") or 0) / 2 ** 30, mf.get("induced_width_estimate", mf.get("induced_width_so_far")), ("%.1f" % mf["peak_table_log2_entries_estimate"]) if mf.get("peak_table_log2_entries_estimate") is not None else "—", "R1 (new, non-independent of EXACT)" if i["status"] == "COMPLETE" and not i.get("censored") else "unresolved (R3 / R2 stays)"))
    # ---------------- 8. family E
    w("\n## 8. Family E — local certificate behaviour on the CBI-admitted cases (120 s)\n")
    for i in newE:
        ex = i.get("extraction_summary") or {}; fs = i.get("failed_sufficient_conditions") or {}; bc = i.get("boundary_contrasts_summary") or {}
        w("**%s** (%s): %s blocks; region size %s; crossing influence d_max over region %s; first-iterate c_q + Σθ at the query node %s; inside influence row sum ‖A‖∞ %s; transport iterations %s; final radius z %s; regional enclosure width %s (solver %s; surrogate η max %s; coarse ρ %s). Failed sufficient conditions (exact): %s | %s | %s. Frozen boundary contrasts (%s): coverage %s; max observed contrast quantiles %s; regions with observed contrast > 0.01: %s, > 0.1: %s. %s\n" % (
            i["case"], i["status"], ex.get("blocks"), ex.get("region_size"), ex.get("d_max_over_region"), ex.get("first_iterate_query"), ex.get("inside_rowsum_max"), ex.get("iterations"), ex.get("z_query"), ex.get("regional_width"), ex.get("solver"), ex.get("surrogate_eta_max"), "0" if not ex.get("rho_coarse") else ex.get("rho_coarse"),
            fs.get("theorem1_first_iterate"), fs.get("contraction_sufficient_condition_Ainf_lt_1"), fs.get("nonbacktracking_perron_lower_bound"), bc.get("frozen_contrasts"), bc.get("coverage"), bc.get("max_observed_contrast"), bc.get("regions_with_contrast_above_0.01"), bc.get("regions_with_contrast_above_0.1"), bc.get("interpretation")))
    if not newE:
        w("(no family-E rows yet)")
    # ---------------- 9. prespecified comparisons
    w("\n## 9. Prespecified feature comparisons (`FEATURE_COMPARISONS_PRESPEC.json`; 46 family-clustered cases; Spearman rank correlations reported as DESCRIPTIVE values with n; no threshold search; null and contrary results included)\n")
    feats = {"variables": lambda c: c["variables"], "sliced_entries": lambda c: c["census"]["sliced"]["table_entries_total"], "largest_table": lambda c: c["census"]["sliced"]["table_entries_largest"], "max_arity": lambda c: c["census"]["sliced"]["max_arity"], "support_density": lambda c: c["census"]["sliced"]["support_density"],
             "dyn_range_log10": lambda c: c["census"]["sliced"]["positive_log10_dynamic_range"], "forced_beyond_ev": lambda c: c["census"]["forced_states"].get("beyond_evidence"), "mdi_relations": lambda c: ((c["census"]["relations_mdi_quotient"].get("fixed") or 0) + (c["census"]["relations_mdi_quotient"].get("merged") or 0)) if c["census"]["relations_mdi_quotient"].get("status") == "complete" else None,
             "cycle_rank": lambda c: c["census"]["graph_sliced_plus_forced"]["cycle_rank"], "minfill_width": lambda c: c["census"]["graph_sliced_plus_forced"]["minfill"].get("induced_width_estimate"), "peak_table_log2": lambda c: c["census"]["graph_sliced_plus_forced"]["minfill"].get("peak_table_log2_entries_estimate"), "log2_state_space": lambda c: c["census"]["graph_sliced_plus_forced"]["log2_state_space"]}
    w("### 9a. Structural features vs historical breadth outcome per arm (complete-answer indicator and complete response time of complete cells)\n"); w("| arm | feature | ρ(feature, complete-answer 0/1) n | ρ(feature, response s | complete) n | note |"); w("|---|---|---|---|---|")
    for arm in RUNNABLE:
        H_ = {i["case"]: i for i in hist if i["stage"] == "breadth" and i["arm"] == arm}
        for fn, f in feats.items():
            xs = []; ys = []; xt = []; yt = []
            for case, c in acc.items():
                if case not in H_:
                    continue
                try:
                    v = f(c)
                except Exception:
                    v = None
                xs.append(v); ys.append(1.0 if ST(H_[case]) in GOOD else 0.0)
                if ST(H_[case]) in GOOD and H_[case].get("complete_response_s"):
                    xt.append(v); yt.append(H_[case]["complete_response_s"])
            r1, n1 = spearman(xs, ys); r2, n2 = spearman(xt, yt)
            note = "constant outcome" if len(set(ys)) == 1 else ("" if r1 is None or abs(r1) < 0.5 else "|ρ| ≥ 0.5 (exploratory; family-clustered)")
            w("| %s | %s | %s %d | %s %d | %s |" % (arm, fn, ("%.2f" % r1) if r1 is not None else "—", n1, ("%.2f" % r2) if r2 is not None else "—", n2, note))
    w("\n### 9b. Blocker set × arm status (historical breadth): cross-tab\n")
    sets = sorted({tuple(sorted(c["census"]["cbi_obstructions"]["blockers_active"])) for c in acc.values()}, key=lambda k: (-bl[k], k)); w("| blocker set (cases) | " + " | ".join(RUNNABLE) + " |"); w("|---|" + "---|" * len(RUNNABLE))
    for k in sets:
        cs = [c for c in acc if tuple(sorted(acc[c]["census"]["cbi_obstructions"]["blockers_active"])) == k]
        w("| %s (%d) | %s |" % (", ".join(k) if k else "(none)", len(cs), " | ".join(" ".join("%s×%d" % kv for kv in collections.Counter(short(ST(i)) for i in hist if i["stage"] == "breadth" and i["arm"] == arm and i["case"] in cs).most_common(3)) for arm in RUNNABLE)))
    # forecast vs actual (MDI)
    w("\n### 9c. MDI dense forecast vs actual (saved records: forecast seconds where recorded; actual = pipeline wall where executed)\n"); w("| case | stage | forecast producer+checker s | actual pipeline s | executed | note |"); w("|---|---|---|---|---|---|")
    for i in hist:
        if i["arm"] != "MDI_EXISTING" or not i.get("mdi"):
            continue
        m_ = i["mdi"]; fc = (m_.get("dense_forecast_seconds") or {}); act = (m_.get("arm_stages_s") or {}).get("pipeline_s") or (m_.get("pipeline_stages_s") or {}).get("pipeline_s")
        if fc or m_.get("route", {}).get("executed_route"):
            w("| %s | %s | %s | %s | %s | %s |" % (i["case"], i["stage"], fc.get("producer_and_checker", fc.get("total", "—")) if fc else "— (forecast not recorded: not refused by forecast)", ("%.2f" % act) if act else "—", m_.get("route", {}).get("executed_route") or "not executed", "unexecuted forecasts have no actual-cost observation" if not m_.get("route", {}).get("executed_route") else ""))
    # ---------------- 10. costs
    w("\n## 10. Cost categories (new family A, medians over complete cells; arm's own timers mapped to non-overlapping categories; original timer names in `phases_s`)\n")
    w("| arm | n | load/conversion | representation/preprocessing | discovery/planning | numerical execution | independent checking | query restoration/output | wrapper (imports) | unassigned residual | complete response | peak RSS MB |"); w("|---|---|---|---|---|---|---|---|---|---|---|---|")
    for arm in RUNNABLE:
        rs = [i for i in newA if i["arm"] == arm and isinstance(i.get("cost_categories_s"), dict)]
        if rs:
            g = lambda k: med([r["cost_categories_s"].get(k) for r in rs])
            w("| %s | %d | %s | %s | %s | %s | %s | %s | %s | %s | %s | %.0f |" % (arm, len(rs), g("load_conversion"), g("representation_preprocessing"), g("discovery_planning"), g("numerical_execution"), g("independent_checking"), g("query_restoration_output"), g("wrapper_unassigned"), g("unassigned_residual"), med([r.get("complete_response_s") for r in rs]), st.median([(r.get("peak_tree_rss_bytes") or 0) / 1e6 for r in rs])))
        else:
            rs2 = [i for i in newA if i["arm"] == arm]
            w("| %s | %d | %s |" % (arm, len(rs2), " not separable from the arm's own timers (see mdi_stages / runs per step) | " * 1 + " — |" * 8 + " %s | %.0f |" % (med([r.get("complete_response_s") for r in rs2 if ST(r) in GOOD]), st.median([(r.get("peak_tree_rss_bytes") or 0) / 1e6 for r in rs2]) if rs2 else 0)))
    w("\nMDI stage timers (pipeline's own names: parse, preprocess, discover, persist, binding_restriction, select, producer_restriction, execute, check) are in each MDI invocation record; the engine's `execute` and `check` are its numerical execution and independent checking; `discover` + `persist` are planning / construction / publication of plan records.")
    # ---------------- 11. collected-but-not-explanatory ledger
    w("\n## 11. 'Collected but not explanatory' ledger (every family and prespecified comparison)\n"); w("| question | applicable denominator | completeness | effect or lack of effect | uncertainty | evidence | disposition |"); w("|---|---|---|---|---|---|---|")
    ledger_rows = []
    for arm in RUNNABLE:
        H_ = {i["case"]: i for i in hist if i["stage"] == "breadth" and i["arm"] == arm}
        for fn, f in feats.items():
            xs = []; ys = []
            for case, c in acc.items():
                if case in H_:
                    try:
                        xs.append(f(c))
                    except Exception:
                        xs.append(None)
                    ys.append(1.0 if ST(H_[case]) in GOOD else 0.0)
            r1, n1 = spearman(xs, ys)
            if len(set(ys)) == 1:
                disp = "property constant across this panel (outcome)"; eff = "n/a"
            elif r1 is None:
                disp = "inadequate measurement (n < 5)"; eff = "—"
            elif abs(r1) < 0.3:
                disp = "no useful association detected"; eff = "ρ = %.2f" % r1
            else:
                disp = "exploratory association (family-clustered; counterexamples in 9b)"; eff = "ρ = %.2f" % r1
            ledger_rows.append(("does %s relate to %s complete-answer status (breadth)?" % (fn, arm), "%d cases" % n1, "complete", eff, "46 family-clustered cases; rank correlation only", "RECORDS_cases.jsonl / RECORDS_invocations.jsonl", disp))
    for fam, qn in (("A", "do instrumented 20 s complete-task outcomes reproduce the historical breadth statuses?"), ("B", "do the existing transformations find structure when their gates are bypassed?"), ("C", "does one-variable query scope change cost or status vs the complete task?"), ("D", "does 120 s exact inference resolve the R0/R1-poor cases?"), ("E", "is the admitted-case certificate pessimistic or is boundary sensitivity large?")):
        rs = [i for i in drows if i.get("family_code") == fam]; done = sum(1 for r in rs if r.get("outcome") == "COMPLETED"); planned = (dman or {}).get("counts", {}).get(fam, 0)
        ledger_rows.append((qn, "%d planned" % planned, "%d completed, %d killed, %d not run" % (done, sum(1 for r in rs if r.get("outcome") in ("TIMEOUT_KILL", "MEMORY_KILL")), sum(1 for r in rs if r.get("outcome") == "NOT_RUN_BUDGET")), "see sections 4-8", "one observation per cell", "DIAG_CELLS_LEDGER.jsonl", "measured; interpretation in section 12"))
    for r in ledger_rows:
        w("| %s |" % " | ".join(str(x) for x in r))
    # ---------------- 11b. graveyard
    w("\n## 11b. Graveyard — avenues retired from active discussion after this accounting (narrow evidence recorded; a null is not an impossibility result)\n")
    retired = [r for r in ledger_rows if r[6] in ("no useful association detected", "property constant across this panel (outcome)")]
    w("| retired avenue | what was measured | why retired | evidence |"); w("|---|---|---|---|")
    w("| Inferring reference uncertainty intervals from printed digits (R2 boxes) | half-ulp boxes inflated Hellinger / error bounds (0.25 half-width) | not a documented reference error rule; replaced by point references (amendment 5) | SCORES_prior_invented_R2_boxes.json vs SCORES.json |")
    w("| Theorem 2 (nonbacktracking contraction) as a rescue for the admitted DBNs | exact nonbacktracking min row sums 6.87 / 8.17 (Perron lower bound on the spectral radius) | the contraction sufficient condition fails under the saved coefficients; finite comparison stays valid but gives no contraction | repair_2026-11-07/NONBACKTRACKING_ROW_SUMS.json; family E |")
    w("| Theorem 4 (anchored transfer) as a rescue for the admitted DBNs | regional enclosure width ≤ 1e-28 on d = 1 kernels | the local error it would reduce is already zero; the failed term is the boundary comparison | family E extraction |")
    w("| 'A nonbinary / higher-arity port unlocks 34 cases' | blocker SETS per case (2a): most refused cases carry 2-3 simultaneous blockers | first blockers are not admission guarantees; arbitrary tables need their own exact representation, consistency and query map | CENSUS.jsonl cbi_obstructions; WITNESS_INDEX.json |")
    w("| 'MDI never transformed anything on the panel' | saved Pedigree_13 depth selector: executed_route = quotient, 52 fixed + 29 merged, ratio 7.25 | false as stated; corrected to 13 untransformed invocations + 1 executed quotient | MDI_INVOCATION_RECORDS_saved.json |")
    w("| 'Every MDI vs baseline comparison was a loss' | Pedigree_13 depth 1.803 s vs libDAI 1.900 s (one observation) | corrected to 'no established repeatable advantage'; the single small win stays visible | section 12 M3 |")
    for r in retired:
        w("| %s | rank correlation over %s | %s (%s) | %s |" % (r[0], r[1], r[6], r[3], r[5]))
    w("\nRetained for the record, not retired: every other prespecified comparison with |ρ| ≥ 0.3 (exploratory), the family-D unresolved references, the lost first-pass diagnostic artifacts.")
    # ---------------- 12. mechanisms
    w("\n## 12. Mechanisms — evidence, coverage, supporting and contradicting cases, alternatives, missing observation\n")
    mech = []
    # M1 representability
    nb = sum(1 for c in acc.values() if "nonbinary domains" in c["census"]["cbi_obstructions"]["blockers_active"]); ha = sum(1 for c in acc.values() if "remaining high arity" in c["census"]["cbi_obstructions"]["blockers_active"]); none_ = [c for c in acc if not acc[c]["census"]["cbi_obstructions"]["blockers_active"]]
    mech.append(("M1 Unavailable representation (CBI)", "PROVED gate behaviour on 44/46 cases: the adapter's predicates are mathematically defined and evaluated on every case (census); blocker sets in 2a; 2 cases pass all predicates (%s)." % none_, "all 46", "supporting: every refused case has ≥ 1 active predicate with a saved witness; contradicting: none", "a different exact representation could admit some refused cases (not impossibility); a nonbinary port is not a proved small extension", "an exact admission construction for any refused class"))
    # M2 policy eligibility (MDI)
    mech.append(("M2 Unattempted work by frozen policy (MDI)", "PROVED from source + saved records: 20 s breadth cannot satisfy window + forecast + 30 s margin → 0 probes in 368 breadth rows; family B shows what the routines find when gates are bypassed (section 4).", "46 breadth, 12 depth, 92 B probes", "supporting: depth probes occur only where the precondition holds (5 cases); contradicting: none", "even with probes, admission (ratio ≥ 2 / ≥ 10) and checker forecasts refuse most (depth ASIA / ALARM / ANDES declined)", "B's structural verdicts vs depth admissions on the same cases"))
    # M3 overhead consuming savings (Pedigree_13)
    mech.append(("M3 Useful transformation with overhead (Pedigree_13 quotient)", "OBSERVED (single run): producer ops 5,185,157 → 924,679 (5.6×), execute 0.469 → 0.165 s, check 1.225 → 0.618 s, but discover 0.250 → 0.499 s and persist 0.128 → 0.345 s; complete response 2.245 → 1.803 s (vs libDAI 1.889 / 1.900 s).", "1 case, 2 runs (breadth dense vs depth quotient; different budgets)", "supporting: the saved stage timers; contradicting: the two runs differ in budget (20 vs 120 s) so the dense-vs-quotient contrast is confounded with admission", "machine noise (one observation); construction costs may not scale with the op-count saving", "a same-budget paired run (family B execution phase on Pedigree_13 gives the quotient route at 30 s)"))
    # M4 cheap baselines
    ex_ok = [c for c in acc if any(i["case"] == c and i["arm"] == "EXACT" and i["stage"] == "breadth" and i["status"] == "COMPLETE" for i in hist)]
    mech.append(("M4 Cheap exact baselines where MDI certifies", "OBSERVED: every MDI-certified case is also completed by libDAI junction tree within 20 s (%d EXACT breadth completions overall); min-fill width estimates of those cases ≤ 11 (census).", "10 MDI-certified cases", "supporting: section 9b blocker/arm cross-tab, 9a width correlations; contradicting: Pedigree_13 depth is 5%% faster than libDAI in one observation", "the comparison is time-to-certified vs time-to-float-point: different contracts", "repeated paired runs on Pedigree_13 / Segmentation_16 (not authorized here beyond A/C)"))
    # M5 certificate looseness (DBN)
    e_ = {i["case"]: i for i in newE}
    mech.append(("M5 Certificate pessimism vs real boundary sensitivity (admitted DBNs)", "OBSERVED (family E): regional solves exact (width ≤ 1e-28); Theorem-1 first iterate ≥ 9 at every query node (saturation is a proved consequence of d_v ≈ 12-14 and inside θ ≈ 0.6); ‖A‖∞ ≈ 23 and nonbacktracking min row sum 6.87 / 8.17 (contraction sufficient conditions FAIL); frozen boundary contrasts (all-0 / all-1 outside states) move P(x=+1) by up to %s on DBN_16 — the two configurations ARE a lower bound showing LARGE actual sensitivity on these regions." % ((e_.get("DBN_16") or {}).get("boundary_contrasts_summary") or {}).get("max_observed_contrast", {}).get("max") if e_.get("DBN_16") else "(pending)", "2 cases, 86 blocks", "supporting: the contrasts; contradicting: none so far — the saturated radius is not shown pessimistic by these contrasts", "the frozen contrasts are extreme configurations; typical-boundary sensitivity may be much smaller (not measured)", "boundary sensitivity under the model's own marginal boundary distribution (not a current routine)"))
    # M6 point inaccuracy of heuristics
    mech.append(("M6 Point inaccuracy of heuristics on strongly coupled / deterministic families", "OBSERVED (historical R0/R1 scoring): LBP 5/27, PGMax 3/27, WMB 18/27, IJGP 19/27 meet 0.005 at 20 s; failures concentrate on Grids, Promedus, Pedigree (LBP/PGMax) — see REPORT.md section 3.", "27 R0/R1 cases", "supporting: per-case tables; contradicting: ObjectDetection / Segmentation_12 met by all", "reference is R1 binary64 (numerical, not rigorous); 20 s is one budget", "the same at 120 s (depth table in REPORT.md)"))
    # M7 resource exhaustion
    mech.append(("M7 Resource exhaustion", "OBSERVED: libDAI refuses 16/46 by maxmem forecast and times out 6 at 20 s; WMB/IJGP ladders hit 8 GiB on ObjectDetection_39 / 1aie at depth; MDI refuses by byte cap on GridBN (4), Grids (2), CSP, DBN, Promedus.", "46 cases", "supporting: census largest tables / peak table estimates (GridBN peak log2 ≥ 28, Protein 81-state tables); contradicting: Segmentation_16 MDI certified at 120 s using 8.4 GB", "memory enforcement is sampled (overshoot recorded)", "—"))
    for m_ in mech:
        w("**%s.** %s *Coverage:* %s. *Supporting / contradicting:* %s. *Alternatives:* %s. *Missing discriminating observation:* %s.\n" % m_)
    # ---------------- 13. dispositions
    w("\n## 13. Per-case disposition (every case, every arm; historical breadth / depth; new A / C; B; D; E)\n"); w("| case | family | " + " | ".join(a[:6] for a in RUNNABLE) + " | B quotient / support | D | E |"); w("|---|---|" + "---|" * len(RUNNABLE) + "---|---|---|")
    for c in sorted(cases, key=lambda x: (x["family"], x["case"])):
        if not c.get("accessible"):
            w("| %s | %s | %s |" % (c["case"], c["family"], " | ".join(["INACCESSIBLE"] * (len(RUNNABLE) + 3)))); continue
        dp = c["dispositions"]; row = []
        for arm in RUNNABLE:
            d_ = dp[arm]; row.append("%s/%s A:%s C:%s" % (short(d_["breadth"]), short(d_["depth"]) if d_["depth"] != "not scheduled for depth" else "·", short(d_["A"]), short(d_["C"])))
        w("| %s | %s | %s | %s / %s | %s | %s |" % (c["case"], c["family"], " | ".join(row), short(dp["B"]["quotient"]), short(dp["B"]["support"]), short(dp["D"]) if dp["D"] not in ("not scheduled (R0/R1 existed)",) else "·", short(dp["E"]) if "not applicable" not in dp["E"] else "·"))
    # ---------------- 14. missingness
    w("\n## 14. Missingness ledger (typed; null is never zero)\n"); w("%s items: %s. Lost artifacts: the first-pass diagnostic numerical files (7 rows; ledger receipts retained). Not instrumented: Merlin phase splits (per-step walls only), libDAI clique/table resources, per-iteration residuals of Merlin / PGMax. Not run within budget: see family rows. Full list in `MISSINGNESS.json`." % (miss.get("count"), miss.get("by_reason")))
    # ---------------- 15. budget
    if BL:
        dg = BL.get("diagnostic_2026-11-07", {})
        w("\n## 15. Budget (nonnested receipts; aggregate ceiling 28,800 s)\n"); w("Campaign %.3f s (90 receipts) + repairs %.3f s (%d) + diagnostics %.3f s (%d jobs + %d cells; ceiling 22,000) = **%.3f s**; remaining %.3f s. Diagnostic by family (cells): %s; by scope (jobs): %s. Fresh-process conditions: new process per cell, warm filesystem caches, reused dependency state, PGMax recompiles per process; no cache purge." % (BL["total_charged_s"], BL["repair_ledger_2026-11-07"]["charged_s"], BL["repair_ledger_2026-11-07"]["receipts"], dg.get("charged_s", 0), dg.get("jobs", 0), dg.get("cells", 0), BL["aggregate_charged_s"], BL["aggregate_remaining_s"], dg.get("by_family_cells"), dg.get("by_scope_jobs")))
    # ---------------- 16. strongest explanations
    w("\n## 16. Strongest supported explanations, counterevidence, uncertainties (derivation vs conjecture labelled)\n")
    w("1. **(Proved gate behaviour)** CBI's external coverage is bounded by its representation predicates: 44 of 46 cases fail at least one mathematically defined predicate (nonbinary 20, arity ≥ 3 after slicing 25, non-square cross-ratio 15, frustrated gauge 9, zero pattern 6; sets in 2a); the two admitted DBNs are certified too wide because the original-law transport saturates at the first iterate (d_v ≈ 12-14, inside θ ≈ 0.6) — a proved consequence of the saved coefficients, and the frozen extreme boundary contrasts show the actual sensitivity on those regions is itself large (a lower bound); the certificate is not shown pessimistic by this evidence. *Uncertain:* typical-boundary sensitivity; whether any sharper certificate applies.")
    w("2. **(Proved gate behaviour + observation)** MDI's 20 s breadth stage attempted no transformation because the frozen selector precondition (window + forecast + 30 s) cannot hold at 20 s; at depth it probed 5 cases and executed one quotient. Family B (section 4) measures what the routines find on every case when those gates are bypassed; its verdicts are structural potential under a different cap, not a policy proposal.")
    w("3. **(Observation, single run)** Where a transformation executed (Pedigree_13 quotient), a 5.6× producer-op reduction became a 20 %% complete-latency reduction and a 5 %% advantage over libDAI: construction, persistence and checking absorb most of the saving. *Counterevidence:* one observation, different budgets. *Conjecture:* the same shape would appear on other admitted quotients; untested.")
    w("4. **(Observation)** The exact baseline (libDAI junction tree) completes every case MDI certifies, within 20 s; its own limit is memory (16 refusals, 6 timeouts), which tracks the census min-fill / peak-table estimates (9a). Where it fails, no certified arm succeeds either. *Alternative:* different contracts (certified width vs floating point).")
    w("5. **(Observation)** Heuristic point accuracy at 20 s separates by family: near-exact on Segmentation / ObjectDetection / bnlearn; poor on Grids / Promedus / Pedigree for LBP and PGMax; WMB / IJGP reach exactness where the i-bound reaches the induced width. *Uncertain:* R1 references are numerical.")
    w("\nNo implementation list, backend, selector margin or benchmark selection follows from this report.")
    open(os.path.join(D, "DIAG_REPORT.md"), "w").write("\n".join(L) + "\n"); print("DIAG_REPORT.md written (%d lines)" % len(L))


if __name__ == "__main__":
    main(os.path.abspath(sys.argv[1]))
