"""Prose report generator of the AGGREGATE_DP_2026-11-07 campaign (reads SCORES.json / RECORDS_cells.jsonl / BUDGET_LEDGER.json /
MISSINGNESS.json / CAMPAIGN_MANIFEST.json; writes REPORT.md). Coverage first; availability, completion, certified target, empirical
target and timing are separate columns; matched comparisons need identical tasks; a timeout is censored; the primary question is
whether the complete algorithm improved coverage, full producer+checker cost or memory at the declared guarantee.
    python adp/closeout/report.py D"""
from __future__ import annotations
import os, sys, json, collections, statistics
HERE = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))); sys.path.insert(0, HERE)
NEW = "AGGREGATE_DP_V1"


def med(xs):
    xs = [x for x in xs if x is not None]
    return (statistics.median(xs) if xs else None)


def fmt(x, d=2):
    return "—" if x is None else ("%.*f" % (d, x) if isinstance(x, float) else str(x))


def main(D):
    man = json.load(open(os.path.join(D, "CAMPAIGN_MANIFEST.json"))); S = json.load(open(os.path.join(D, "SCORES.json"))); B = json.load(open(os.path.join(D, "BUDGET_LEDGER.json"))); MI = json.load(open(os.path.join(D, "MISSINGNESS.json")))
    R = [json.loads(l) for l in open(os.path.join(D, "RECORDS_cells.jsonl"))]
    fam = {c["case"]: c["family"] for c in man["cases"]}; cases = [c["case"] for c in man["cases"]]; fams = sorted(set(fam.values()))
    def key(r):
        return r["arm"] if r["arm"] != NEW else r["config_key"]
    def rows(stage, k, rep=None):
        return [r for r in R if r["stage"] == stage and key(r) == k and (rep is None or r.get("repetition") == rep)]
    L = []; P = L.append
    P("# AGGREGATE_DP_V1 full-panel campaign (frozen 8 November 2026) — review report\n")
    P("Branch `aggregate-dp-2026-11-07` from `8b5f8583` (sweep closeout); manifest commit `%s`, code hash `%s`; design packet sha256 `0423e3db…`. One new arm (AGGREGATE_DP_V1: lazy sum-product bucket engine with source-certified response views, bounded memoization, shared backward pass, INDEPENDENT checker) measured against the unchanged historical arms (libDAI junction tree = EXACT, the pinned MDI_EXISTING selector engine, Merlin WMB / IJGP ladders) on the frozen 46-case panel (+2 inaccessible slots), plus five frozen ablations and two paired repetitions. Every statement below is an observation of THIS campaign unless labelled; the historical sweep's rows are not re-used as matched measurements.\n" % (man["commit"][:12], man["code_hash"][:12]))
    P("## 1. Population and coverage (every planned cell has a row or a typed reason)\n")
    P("| stage | planned | recorded | statuses |\n|---|---|---|---|")
    for st in ("P20", "P120", "ABL", "REP"):
        rs = [r for r in R if r["stage"] == st]; P("| %s | %d | %d | %s |" % (st, sum(1 for c in man["cells"] if c["stage"] == st), len(rs), ", ".join("%s %d" % kv for kv in sorted(collections.Counter(r["status"] for r in rs).items()))))
    P("\nInaccessible inventory slots (recorded, never run): %s. Typed missingness: %s. Unrun planned cells: %d (listed in MISSINGNESS.json).\n" % (", ".join("%s (%s)" % (x["case"], x["reason"]) for x in man["inaccessible_slots"]), json.dumps(MI["typed_missingness"]), len(MI["unrun_cells"])))
    # ---- 2. headline: 20 s and 120 s, per arm: available / complete / certified / empirical / median time
    P("## 2. Availability, completion, certified target, empirical target and timing — SEPARATE axes\n")
    def arm_table(stage, keys):
        P("| arm / config | available | complete output | certified (checker) | empirical ≤0.005 of complete w/ ref | unknown accuracy (no ref) | median complete response s | median peak tree RSS MB |\n|---|---|---|---|---|---|---|---|")
        for k in keys:
            rs = rows(stage, k, rep=0); av = sum(1 for r in rs if r.get("available")); co = sum(1 for r in rs if r.get("complete_output")); ce = sum(1 for r in rs if r.get("certified_target"))
            em = sum(1 for r in rs if r.get("empirical") and r["empirical"]["target_0.005"] == "met"); unk = sum(1 for r in rs if r.get("complete_output") and r.get("empirical") is None)
            t = med([r.get("complete_response_s") for r in rs if r.get("complete_output")]); mb = med([r.get("peak_tree_rss_bytes", 0) / 1e6 for r in rs if r.get("complete_output")])
            P("| %s | %d/%d | %d | %s | %d | %d | %s | %s |" % (k, av, len(rs), co, (str(ce) if k in (NEW, "MDI_EXISTING", "full") or k.startswith("A") else "not offered"), em, unk, fmt(t), fmt(mb, 0)))
    P("### 2a. 20 s (primary, repetition 0)\n"); arm_table("P20", ["full", "EXACT", "MDI_EXISTING", "WMB", "IJGP"]); P("")
    P("### 2b. 120 s (single observation each)\n"); arm_table("P120", ["full", "EXACT"]); P("")
    P("Certified = the independent checker's own outward replay produced intervals of width ≤ 1/100 on every original coordinate AND the delivered decimal point satisfied the robust-center predicate (|p − q| ≤ 1/200 for every q in the certified box, rows summing to 1 exactly) under a second independent re-parse. Baselines offer no rigorous certificate; their 'empirical' column compares a floating-point point vector to a reference POINT (R0 exact / R1 binary64 / R2 official) and is not a certificate. 'Unknown accuracy' = complete output but no qualified reference for that case.\n")
    # ---- 3. per-case table at 20 s
    P("## 3. Per-case disposition at 20 s (primary repetition): status / complete response s (— if none) per arm; AGGREGATE_DP_V1 adds its typed stop\n")
    P("| case | family | %s |\n|---|---|%s|" % (" | ".join(["AGGREGATE_DP_V1", "EXACT", "MDI_EXISTING", "WMB", "IJGP"]), "---|" * 5))
    def cellstr(r):
        if r is None:
            return "—"
        s = r["status"]; t = r.get("complete_response_s")
        if r.get("complete_output") and t is not None:
            s += " %.2fs" % t
        if r["arm"] == NEW and r.get("adp") and r["adp"].get("stop"):
            s += " [%s]" % r["adp"]["stop"].get("kind")
        if r.get("censored") and not r.get("complete_output"):
            s += " (censored)"
        return s
    for c in cases:
        P("| %s | %s | %s |" % (c, fam[c], " | ".join(cellstr(next((r for r in rows("P20", k, rep=0) if r["case"] == c), None)) for k in ["full", "EXACT", "MDI_EXISTING", "WMB", "IJGP"])))
    P("")
    # ---- 4. matched pairs new vs EXACT (both complete) and repeatability
    P("## 4. Matched comparisons AGGREGATE_DP_V1 vs libDAI EXACT (identical task; both must have a COMPLETE output; a timeout is censored, not a time)\n")
    for stage, reps in (("P20", [0]), ("P120", [0])):
        both = []; only_new = []; only_ex = []; neither = []
        for c in cases:
            a = next((r for r in rows(stage, "full") if r["case"] == c and r.get("repetition") == 0), None); b = next((r for r in rows(stage, "EXACT") if r["case"] == c and r.get("repetition") == 0), None)
            ca = bool(a and a.get("complete_output") and a.get("certified_target")); cb = bool(b and b.get("complete_output"))
            if ca and cb:
                both.append((c, a["complete_response_s"], b["complete_response_s"], a.get("peak_tree_rss_bytes", 0) / 1e6, b.get("peak_tree_rss_bytes", 0) / 1e6))
            elif ca:
                only_new.append(c)
            elif cb:
                only_ex.append(c)
            else:
                neither.append(c)
        P("### %s: all-pair status coverage\n" % stage)
        P("- both certified / complete: %d — %s" % (len(both), ", ".join(x[0] for x in both)))
        P("- only AGGREGATE_DP_V1 certified: %d — %s" % (len(only_new), ", ".join(only_new) or "none"))
        P("- only EXACT complete: %d — %s" % (len(only_ex), ", ".join(only_ex) or "none"))
        P("- neither: %d — %s\n" % (len(neither), ", ".join(neither) or "none"))
        if both:
            P("| case | new s (producer+checker+publication) | EXACT s | ratio new/EXACT | new peak MB | EXACT peak MB |\n|---|---|---|---|---|---|")
            for c, ta, tb, ma, mb in both:
                P("| %s | %.2f | %.2f | %.2f | %.0f | %.0f |" % (c, ta, tb, ta / tb if tb else float("inf"), ma, mb))
            rat = [ta / tb for _, ta, tb, _, _ in both if tb]; P("\nmedian ratio new/EXACT over the %d successful pairs: %.2f (min %.2f, max %.2f). The denominator excludes every case where either side has no complete answer.\n" % (len(both), statistics.median(rat), min(rat), max(rat)))
    # repetitions
    P("### Repeatability (three 20 s observations of each AGGREGATE_DP_V1 / EXACT cell: P20 rep 0 + REP reps 1, 2)\n")
    P("| case | new statuses (r0,r1,r2) | new s | EXACT statuses | EXACT s |\n|---|---|---|---|---|")
    for c in cases:
        na = [next((r for r in R if r["stage"] in ("P20", "REP") and key(r) == "full" and r["case"] == c and r.get("repetition") == k), None) for k in (0, 1, 2)]
        ex = [next((r for r in R if r["stage"] in ("P20", "REP") and r["arm"] == "EXACT" and r["case"] == c and r.get("repetition") == k), None) for k in (0, 1, 2)]
        if all(x is None for x in na + ex):
            continue
        f = lambda rs: ",".join((r["status"][:12] if r else "—") for r in rs); g = lambda rs: ",".join(("%.2f" % r["complete_response_s"] if (r and r.get("complete_output")) else "—") for r in rs)
        P("| %s | %s | %s | %s | %s |" % (c, f(na), g(na), f(ex), g(ex)))
    P("")
    # ---- 5. ablations
    P("## 5. Ablations (20 s; explanations, not contestants). Each disables ONE mechanism of the frozen engine; A1 changes the program graph and may cost more\n")
    P("| config | certified | complete | typed stops | median s (certified) | median peak MB | cases lost vs full | cases gained vs full |\n|---|---|---|---|---|---|---|---|")
    full = {r["case"]: r for r in rows("P20", "full", rep=0)}
    for k in sorted(man["ablations"]) :
        rs = rows("ABL", k); ce = {r["case"] for r in rs if r.get("certified_target")}; cf = {c for c, r in full.items() if r.get("certified_target")}
        stops = collections.Counter(((r.get("adp") or {}).get("stop") or {}).get("kind") or r["status"] for r in rs if not r.get("certified_target"))
        P("| %s | %d | %d | %s | %s | %s | %s | %s |" % (k, len(ce), sum(1 for r in rs if r.get("complete_output")), dict(stops), fmt(med([r["complete_response_s"] for r in rs if r.get("certified_target")])), fmt(med([r.get("peak_tree_rss_bytes", 0) / 1e6 for r in rs]), 0), ", ".join(sorted(cf - ce)) or "none", ", ".join(sorted(ce - cf)) or "none"))
    P("\nPer-case ablation timings (certified cells only; s):\n")
    P("| case | full | %s |\n|---|---|%s|" % (" | ".join(sorted(man["ablations"])), "---|" * len(man["ablations"])))
    for c in cases:
        f0 = full.get(c); cells_ = [next((r for r in rows("ABL", k) if r["case"] == c), None) for k in sorted(man["ablations"])]
        P("| %s | %s | %s |" % (c, ("%.2f" % f0["complete_response_s"]) if (f0 and f0.get("certified_target")) else (f0["status"][:14] if f0 else "—"), " | ".join((("%.2f" % r["complete_response_s"]) if (r and r.get("certified_target")) else ((((r.get("adp") or {}).get("stop") or {}).get("kind") or r["status"])[:14] if r else "—")) for r in cells_)))
    P("")
    # ---- 6. where the time goes in the new arm
    P("## 6. Cost anatomy of AGGREGATE_DP_V1 (certified 20 s cells): phase medians and shares; every phase is inside the complete response\n")
    cert = [r for r in rows("P20", "full", rep=0) if r.get("certified_target")]
    def phase(r, name):
        a = (r.get("adp") or {}).get("attempts") or []; ph = a[-1].get("phases_s", {}) if a else {}
        return {"source_reductions": r["phases_s"].get("source_reductions"), "plan": r["phases_s"].get("plan"), "forward": ph.get("forward"), "backward": ph.get("backward"), "checker": ph.get("checker"), "publish": r["phases_s"].get("publish"), "startup": r["phases_s"].get("startup_imports")}.get(name)
    P("| phase | median s | share of median complete response |\n|---|---|---|")
    T = med([r["complete_response_s"] for r in cert]) or 1.0
    for name in ("startup", "source_reductions", "plan", "forward", "backward", "checker", "publish"):
        m = med([phase(r, name) for r in cert]); P("| %s | %s | %s |" % (name, fmt(m, 3), fmt((m / T) if m is not None else None, 2)))
    P("\nPer-case anatomy (certified cells): reductions / planned formats / core entries / checker share\n")
    P("| case | free vars orig→reduced | steps | formats (planned) | core entries | bag rows | nontrivial view axes | fwd s | bwd s | checker s | checker share | total s | peak MB |\n|---|---|---|---|---|---|---|---|---|---|---|---|---|")
    for r in cert:
        a = r["adp"]; red = a.get("reductions") or {}; pg = a.get("program") or {}; at = (a.get("attempts") or [{}])[-1]; ph = at.get("phases_s", {})
        P("| %s | %s→%s | %s | %s | %s | %s | %s | %s | %s | %s | %s | %.2f | %.0f |" % (r["case"], red.get("free_original"), red.get("free_reduced"), json.dumps(red.get("steps")), json.dumps(pg.get("formats_planned")), pg.get("core_entries_total"), pg.get("bag_rows_total"), pg.get("views_nontrivial_axes"), fmt(ph.get("forward")), fmt(ph.get("backward")), fmt(ph.get("checker")), fmt((ph.get("checker") or 0) / r["complete_response_s"], 2), r["complete_response_s"], r.get("peak_tree_rss_bytes", 0) / 1e6))
    P("")
    P("### Typed stops of AGGREGATE_DP_V1 (20 s, primary): where the non-certified cells stopped\n")
    P("| case | status | stop kind | phase | planned formats | core entries total | largest core | forward s before stop |\n|---|---|---|---|---|---|---|---|")
    for r in rows("P20", "full", rep=0):
        if r.get("certified_target"):
            continue
        a = r.get("adp") or {}; st = a.get("stop") or {}; pg = a.get("program") or {}; at = (a.get("attempts") or [{}])[-1]
        P("| %s | %s | %s | %s | %s | %s | %s | %s |" % (r["case"], r["status"], st.get("kind"), st.get("phase"), json.dumps(pg.get("formats_planned")), pg.get("core_entries_total"), pg.get("largest_core"), fmt((at.get("phases_s") or {}).get("forward"))))
    P("")
    # ---- 7. references and empirical accuracy
    P("## 7. References and empirical accuracy (points; a reference matching its own engine is not independent)\n")
    P("Reference classes: %s. For every CERTIFIED new-arm cell with an R0 reference, every exact R0 coordinate must lie inside the published interval (a proof check); for R1 / R2 references containment is a consistency observation (those references carry undocumented rounding).\n" % json.dumps(S["reference_class_counts"]))
    P("| case | ref class | new arm: ref inside intervals (coords) | new arm point max err | EXACT max err | MDI max err | WMB max err | IJGP max err |\n|---|---|---|---|---|---|---|---|")
    for c in cases:
        rc = S["reference_classes"][c]["class"]; cells_ = {k: next((r for r in rows("P20", k, rep=0) if r["case"] == c), None) for k in ["full", "EXACT", "MDI_EXISTING", "WMB", "IJGP"]}
        a = cells_["full"]; cont = (a or {}).get("reference_in_intervals"); e = lambda r: fmt((r.get("empirical") or {}).get("max_abs_error") if r else None, 6)
        P("| %s | %s | %s | %s | %s | %s | %s | %s |" % (c, rc, ("%d/%d" % (cont["contained"], cont["coordinates"])) if cont else "—", e(a), e(cells_["EXACT"]), e(cells_["MDI_EXISTING"]), e(cells_["WMB"]), e(cells_["IJGP"])))
    P("")
    # ---- 8. budget
    P("## 8. Budget (nonnested receipts; separate 28,800 s ceiling)\n")
    P("Qualification %s s; cells %s s (%s); closeout %s s; total %s s (%s); remaining %s s; within ceiling: %s. Stage allowances %s; over-allowance %s.\n" % (B["qualification_s"], B["cells_s"], json.dumps(B["cells_by_stage_s"]), B["closeout_s"], B["total_charged_s"], B["total_status"], B["remaining_s"], B["within_ceiling"], json.dumps(B["stage_allowances_s"]), json.dumps(B["over_stage_allowance"])))
    P("Enforcement: cooperative deadline polled per chunk / operation inside the cell; the supervisor SIGKILLs the process group at deadline + 4 s and when the sampled process-tree RSS (50 ms; producer + checker together) exceeds 8 GiB — best-effort policing, not an allocator cap; overshoots are recorded. Fresh process per cell; dependency caches warm; no cache purge.\n")
    open(os.path.join(D, "REPORT.md"), "w").write("\n".join(L) + "\n"); print("REPORT.md written: %d lines" % len(L))


if __name__ == "__main__":
    main(os.path.abspath(sys.argv[1]))
