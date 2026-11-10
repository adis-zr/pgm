"""GENERAL_BIDI_V2 closeout (third review H1-H4): CELLS_LEDGER.jsonl (every planned row through gbidi.reconcile, the ONE strict reconciler shared with
resume: bound record + adapter mapping for comparators + full task / query / budget / config / pin identity + exactly one START/SPAWNED/RECEIPT chain
+ output hash + launch-relative delivery), BUDGET_LEDGER.json (= gbidi.pilot.charged: every attempt once, every outer attempt's parent-only remainder
once by parent_jid; unresolved at max permitted; QUALIFIED while anything is unresolved), MISSINGNESS.json (typed), SCORES.json (raw vs DELIVERED widths), MECHANISMS.json
(typed provenance per node: APPLIED / CHECKED_NO_OP / SKIPPED_ROW_CAP / SKIPPED_WALL / NOT_ATTEMPTED / UNKNOWN / DISABLED -- a FULL-safe fallback is
never a no-op proof), REPORT.md and HANDOFF.md. Statistics use the ordinary median on unrounded observations and launch-relative timing for
deadline classification. Reads only saved artifacts; never modifies a cell.    python -m gbidi_closeout.report D"""
from __future__ import annotations
import os, sys, json, hashlib, collections
HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__))); sys.path.insert(0, HERE)
sys.set_int_max_str_digits(0)
from fractions import Fraction as Fr
from gbidi import pilot as PI
OLD = os.path.join(HERE, "runs", "mdi_2026-10-28", "EXTERNAL_SWEEP_2026-11-06"); ADP = os.path.join(HERE, "runs", "mdi_2026-10-28", "AGGREGATE_DP_2026-11-07")
ARMS_A = ["A1_NO_DEMAND_MASKS", "A2_NO_FUSION", "A3_NO_RESPONSE_VIEWS"]
CERT = ("CERTIFIED",); DONE_UNCERT = ("COMPLETE",)


def jl(p):
    return [json.loads(l) for l in open(p)] if os.path.exists(p) else []


def sha(p):
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for ch in iter(lambda: f.read(1 << 20), b""):
            h.update(ch)
    return h.hexdigest()


def median(xs):
    """the ordinary median (mean of the two middle observations for even n); None for an empty sample"""
    xs = sorted(xs); n = len(xs)
    if n == 0:
        return None
    return xs[n // 2] if n % 2 else (xs[n // 2 - 1] + xs[n // 2]) / 2


def read_points(p):
    from ext import uai as U
    rows, _ = U.read_mar(p); return [[Fr(x) for x in r] for r in rows]


# ---------------------------------------------------------------------------------------------------------------- ledgers
from gbidi import reconcile as RC


def cells_ledger(D, man):
    """every planned row through the ONE strict reconciler (gbidi.reconcile; the same one gbidi.pilot uses on resume)"""
    idx = RC.ledger_index(D); return [RC.reconcile(D, man, c, idx) for c in man["cells"]]


def budget(D, man, cells):
    """nonnested accounting = gbidi.pilot.charged (shared with the live guard): every non-outer attempt once; each OUTER attempt's parent-only
    remainder once (outer wall - its own children by parent_jid); unresolved starts / outer starts without receipt at max permitted and listed;
    compliance QUALIFIED while anything is unresolved."""
    total, by, unresolved, extra = PI.charged(D); led = jl(os.path.join(D, "GB_LEDGER.jsonl"))
    jobs = [{"job": r["job"], "jid": r["jid"], "scope": r["scope"], "wall_s": round(r["wall_s"], 3), "outcome": r["outcome"], "parent_jid": r.get("parent_jid")} for r in led if r["kind"] == "RECEIPT" and r.get("wall_s") is not None]
    pre = sum(r["wall_s"] for r in led if r["kind"] == "RECEIPT" and r.get("wall_s") and r.get("start_utc", "") < man["frozen_utc"] and not r["scope"].startswith("stage_outer"))
    return {"ceiling_s": man["ceiling_s"], "rule": "nonnested (gbidi.pilot.charged): every non-outer START once (receipt wall; no receipt / duplicate receipts / unresolved cleanup -> max permitted, listed); every outer attempt's parent-only remainder once (outer wall - its OWN children by parent_jid); an outer START without receipt is unresolved (max permitted); pre-freeze jobs are charged too",
            "total_charged_s": round(total, 3), "by_scope_s": {k: round(v, 3) for k, v in by.items()}, "pre_freeze_jobs_s": round(pre, 3), "unresolved": [{"job": u["job"], "jid": u["jid"], "outer": u.get("outer", False)} for u in unresolved], "outer_attempts": extra["outer_attempts"], "duplicate_receipts": extra["duplicate_receipts"], "jobs": jobs,
            "compliance": "QUALIFIED" if unresolved or extra["duplicate_receipts"] else "every start receipted exactly once; every outer attempt's parent remainder measured; uncharged: read-only shell inspections, git, file copies",
            "within_ceiling_known_charges": total <= man["ceiling_s"]}


# ---------------------------------------------------------------------------------------------------------------- references / scores
def references(man):
    old = json.load(open(os.path.join(ADP, "SCORES.json")))["reference_classes"]; refs = {}
    from ext import uai as U
    for case, c in man["cases"].items():
        m = U.read_model(os.path.join(HERE, c["model_path"])); cls = old.get(case, {}).get("class", "R3"); pts = None; src = old.get(case, {}).get("source")
        try:
            if cls == "R0":
                d = json.load(open(os.path.join(OLD, "references", case + ".R0.json"))); pts = [[Fr(x) for x in d["marginals"][str(v)]] for v in range(m.nvars)]
            elif cls == "R1":
                rows = jl(os.path.join(OLD, "CELLS_LEDGER.jsonl")); hit = [r for r in rows if r["case"] == case and r["arm"] == "EXACT" and r.get("status") == "COMPLETE" and not r.get("censored")]
                if hit:
                    pts = read_points(os.path.join(OLD, hit[0]["out_dir"], "output.MAR"))
            elif cls == "R2":
                op = os.path.join(OLD, "sources", "uai14", "sol", case + ".uai.MAR")
                if os.path.exists(op):
                    pts = read_points(op)
        except Exception:
            pts = None
        refs[case] = {"class": cls, "source": src, "points_available": pts is not None, "_pts": pts, "nvars": m.nvars}
    return refs


def scores(D, man, cells, refs):
    out = {}
    for r in cells:
        if r["arm"] not in PI.GB_ARMS or r.get("status") != "CERTIFIED" or not r.get("accepted"):
            continue
        ref = refs[r["case"]]; od = os.path.join(D, r["out_dir"]); rec = json.load(open(os.path.join(od, "checked_record.json"))); pts = read_points(os.path.join(od, "output.MAR"))
        ivs = {int(v): [(Fr(a), Fr(b)) for a, b in row] for v, row in rec["certified_intervals"].items()}; dl = json.load(open(os.path.join(od, "intervals.json")))["intervals"]; dvs = {x["var"]: [(Fr(a), Fr(b)) for a, b in x["intervals"]] for x in dl}
        e = {"case": r["case"], "arm": r["arm"], "stage": r["stage"], "reference_class": ref["class"], "max_raw_width": float(max(b - a for row in ivs.values() for a, b in row)), "max_delivered_width": float(max(b - a for row in dvs.values() for a, b in row))}
        if ref["_pts"] is not None:
            inside = sum(1 for v in dvs for s in range(len(dvs[v])) if dvs[v][s][0] <= ref["_pts"][v][s] <= dvs[v][s][1]); n = sum(len(dvs[v]) for v in dvs)
            e["reference_coordinates_inside_delivered_interval"] = "%d/%d" % (inside, n); e["max_abs_distance_point_to_reference"] = float(max(abs(pts[v][s] - ref["_pts"][v][s]) for v in dvs for s in range(len(dvs[v]))))
            e["containment_meaning"] = "PROOF CHECK (exact R0)" if ref["class"] == "R0" else "consistency observation only (R1/R2 are rounded points)"
        out["%s|%s|%s" % (r["stage"], r["arm"], r["case"])] = e
    return out


# ---------------------------------------------------------------------------------------------------------------- mechanisms (typed provenance)
def typed_mechanisms(r):
    mk = r.get("mechanisms") or {}; prov = r.get("node_provenance") or []; out = {}
    def summarise(kind, key_fn):
        m = mk.get(kind) or {}
        if str(m.get("state", "")).startswith("DISABLED"):
            return "DISABLED"
        cnt = collections.Counter(key_fn(nd) for nd in prov if key_fn(nd) is not None)
        if any(k.startswith("COMPRESSED") or k in ("RESTRICTED", "SUPPORT_RESTRICTED", "POLICY") for k in cnt):
            return "APPLIED_WITH_PROOF"
        if any(k.startswith("SKIPPED_WALL") for k in cnt):
            return "SKIPPED_WALL_UNKNOWN"
        if any(k.startswith("SKIPPED_ROW_CAP") for k in cnt):
            return "SKIPPED_ROW_CAP_UNKNOWN"
        if any(k in ("FULL_CONSUMER_SUPPORT_UNKNOWN", "MEMORY", "NOT_ATTEMPTED") for k in cnt):
            return "UNKNOWN"
        if kind == "fusion":
            return "DECLINED_BY_FROZEN_POLICY" if (m.get("edges_declined_by_policy") or 0) > 0 else ("NO_EDGE_OFFERED" if not cnt else "UNKNOWN")
        return "CHECKED_NO_OP" if cnt else "UNKNOWN"
    out["views"] = summarise("views", lambda nd: None if not nd.get("view_prov") else ("COMPRESSED" if any(p == "COMPRESSED" for p in nd["view_prov"].values()) else ("SKIPPED_WALL" if any(p == "SKIPPED_WALL" for p in nd["view_prov"].values()) else ("SKIPPED_ROW_CAP" if any(p == "SKIPPED_ROW_CAP" for p in nd["view_prov"].values()) else "CHECKED_NO_OP"))))
    out["demand"] = summarise("demand", lambda nd: nd.get("demand_prov") if nd.get("demand_prov") not in ("FULL_MANDATORY", "ROOT_FULL") else nd.get("support_prov"))
    out["fusion"] = summarise("fusion", lambda nd: nd.get("fused_by"))
    out["node_provenance_counts"] = {"support": dict(collections.Counter(nd.get("support_prov") for nd in prov)), "demand": dict(collections.Counter(nd.get("demand_prov") for nd in prov)), "views": dict(collections.Counter(p for nd in prov for p in (nd.get("view_prov") or {}).values())), "fused_by": dict(collections.Counter(nd.get("fused_by") for nd in prov))}
    out["mechanisms_raw"] = mk; out["discovery_stop"] = r.get("discovery_stop"); out["route"] = r.get("route"); out["status"] = r.get("status"); out["source"] = "diagnostic (stopped attempt)" if r.get("diagnostic_present") else "completed record"
    return out


# ---------------------------------------------------------------------------------------------------------------- report
def main(D):
    man = json.load(open(os.path.join(D, "GB_MANIFEST.json"))); cells = cells_ledger(D, man); B = budget(D, man, cells); refs = references(man); S = scores(D, man, cells, refs)
    with open(os.path.join(D, "CELLS_LEDGER.jsonl"), "w") as f:
        for r in cells:
            f.write(json.dumps(r, default=str) + "\n")
    json.dump(B, open(os.path.join(D, "BUDGET_LEDGER.json"), "w"), indent=1); json.dump({"reference_classes": {c: {k: v for k, v in refs[c].items() if k != "_pts"} for c in refs}, "frozen_source": "AGGREGATE_DP_2026-11-07/SCORES.json sha256 %s" % sha(os.path.join(ADP, "SCORES.json")), "cells": S}, open(os.path.join(D, "SCORES.json"), "w"), indent=1, default=str)
    res = collections.Counter(r["resolution"] for r in cells)
    miss = {"planned": len(cells), "accepted": sum(1 for r in cells if r["accepted"]), "delivered_valid_output_not_accepted": [r["job"] for r in cells if r.get("delivered_valid_output") and not r["accepted"]], "resolutions": dict(res), "not_accepted_rows": [{"job": r["job"], "resolution": r["resolution"], "record_status": r.get("record_status"), "reasons": r.get("reasons")} for r in cells if not r["accepted"] and r["resolution"] not in ("EXPLICITLY_UNLAUNCHED",)], "unavailable_slots": man["unavailable_slots"],
            "stopped_cells_with_diagnostic": sum(1 for r in cells if r.get("status") == "RESOURCE_STOP" and r.get("diagnostic_present")), "stopped_cells_without_diagnostic": [r["job"] for r in cells if r.get("status") == "RESOURCE_STOP" and r["arm"] in PI.GB_ARMS and not r.get("diagnostic_present")],
            "uncharged_disclosed": ["read-only shell inspections, git, file copies", "development smoke runs before the freeze are charged under scope qualification where they ran under the supervisor; any that did not are disclosed in the handoff"]}
    json.dump(miss, open(os.path.join(D, "MISSINGNESS.json"), "w"), indent=1)
    from adp import campaign as C
    h, _ = C.code_hash(); UH = {"frozen_numerical_set_code_hash": h, "inputs": {c: {"model_ok": sha(os.path.join(HERE, v["model_path"])) == v["raw_model_sha256"], "evidence_ok": sha(os.path.join(HERE, v["evidence_path"])) == v["raw_evidence_sha256"]} for c, v in man["cases"].items()}, "config_adp_ok": sha(os.path.join(HERE, man["config_adp_repaired_path"])) == man["config_adp_repaired_sha256"]}
    json.dump(UH, open(os.path.join(D, "UNCHANGED_HISTORY.json"), "w"), indent=1)
    MECH = {"%s|%s|%s" % (r["stage"], r["arm"], r["case"]): typed_mechanisms(r) for r in cells if r["arm"] in PI.GB_ARMS and (r.get("mechanisms") or r.get("node_provenance"))}
    json.dump(MECH, open(os.path.join(D, "MECHANISMS.json"), "w"), indent=1)
    by = {(r["stage"], r["arm"], r["case"]): r for r in cells}; cases = PI.inventory(); fam = {c: man["cases"][c]["family"] for c in cases}; families = [f for f, _ in PI.FAMILY_ORDER]
    def st(stage, arm, case):
        r = by.get((stage, arm, case), {}); return r.get("status") if r.get("accepted") or r.get("resolution") in ("NOT_LAUNCHED", "EXPLICITLY_UNLAUNCHED") else ("NOT_ACCEPTED:" + str(r.get("record_status")) if r else None)
    def cert(stage, arm):
        return [c for c in cases if st(stage, arm, c) in CERT]
    def comp(stage, arm):
        return [c for c in cases if st(stage, arm, c) in DONE_UNCERT]
    def tm(stage, arm, c):
        r = by.get((stage, arm, c), {}); return r.get("delivery_from_launch_s")                                           # launch-relative for EVERY arm (adapter for comparators)
    L = ["# %s broad round — %d planned cells on the 46-case panel\n" % (man["pass"], len(cells)), "Branch `%s`, frozen commit `%s` (kernel `%s`). Seed %d; order per empirical_plan.txt §3 (reconciled incl. task / cell identities). One observation per cell. Coverage counts use ACCEPTED rows only (record bound to the planned task + exactly one compatible receipt); non-accepted rows are listed in MISSINGNESS.json. Timing uses the launch-relative clock.\n" % (man["branch"], man["commit"][:12], man["kernel_binary_sha256"][:12], man["seed"])]
    L.append("## 1. Coverage by arm / stage (accepted rows)\n\n| arm / stage | certified | complete (uncertified) | typed stops | late | not accepted | other |\n|---|---|---|---|---|---|---|")
    for stage, arms, b in PI.STAGES:
        for a in arms:
            sts = [st(stage, a, c) for c in cases]; L.append("| %s %ds | %d/46 | %d | %d | %d | %d | %s |" % (a, int(b), sum(1 for x in sts if x in CERT), sum(1 for x in sts if x in DONE_UNCERT), sum(1 for x in sts if x in ("RESOURCE_STOP", "TIMEOUT", "ADMISSION_REFUSED", "NUMERIC_UNRESOLVED", "NUMERIC_RANGE", "ROUTE_LIMITATION")), sum(1 for x in sts if x == "LATE_OUTPUT"), sum(1 for x in sts if x and x.startswith("NOT_ACCEPTED")), dict(collections.Counter(x for x in sts if x not in CERT + DONE_UNCERT + ("RESOURCE_STOP", "TIMEOUT", "ADMISSION_REFUSED", "NUMERIC_UNRESOLVED", "NUMERIC_RANGE", "ROUTE_LIMITATION", "LATE_OUTPUT") and not (x or "").startswith("NOT_ACCEPTED")))))
    L.append("\n| family | n | " + " | ".join("%s %d" % (a[:10], int(b)) for stage, arms, b in PI.STAGES for a in arms) + " |\n|---|---|" + "---|" * 9)
    for f in families:
        cs = [c for c in cases if fam[c] == f]; L.append("| %s | %d | %s |" % (f, len(cs), " | ".join(str(sum(1 for c in cs if st(stage, a, c) in (DONE_UNCERT if a == "EXACT_LIBDAI" else CERT))) for stage, arms, b in PI.STAGES for a in arms)))
    g20, p20, a20 = set(cert("primary_breadth", "GENERAL_BIDI_V2")), set(cert("primary_breadth", "NATIVE_PLAIN_V2")), set(cert("primary_breadth", "ADP_REPAIRED")); g120, p120 = set(cert("primary_depth", "GENERAL_BIDI_V2")), set(cert("primary_depth", "NATIVE_PLAIN_V2"))
    L.append("\nGENERAL vs PLAIN (20 s): gained %s, lost %s; GENERAL vs ADP: gained %s, lost %s; (120 s) GENERAL vs PLAIN gained %s, lost %s.\n" % (sorted(g20 - p20), sorted(p20 - g20), sorted(g20 - a20), sorted(a20 - g20), sorted(g120 - p120), sorted(p120 - g120)))
    L.append("## 2. Matched-pair timing (ordinary median of launch-relative times; one observation each)\n")
    for name, A, Bm, stg in (("GENERAL/PLAIN 20 s", "GENERAL_BIDI_V2", "NATIVE_PLAIN_V2", "primary_breadth"), ("GENERAL/ADP 20 s", "GENERAL_BIDI_V2", "ADP_REPAIRED", "primary_breadth"), ("PLAIN/ADP 20 s", "NATIVE_PLAIN_V2", "ADP_REPAIRED", "primary_breadth"), ("GENERAL/libDAI 20 s", "GENERAL_BIDI_V2", "EXACT_LIBDAI", "primary_breadth"), ("GENERAL/PLAIN 120 s", "GENERAL_BIDI_V2", "NATIVE_PLAIN_V2", "primary_depth")):
        joint = [c for c in cases if st(stg, A, c) in CERT and st(stg, Bm, c) in (DONE_UNCERT if Bm == "EXACT_LIBDAI" else CERT) and tm(stg, A, c) and tm(stg, Bm, c)]; ratios = [tm(stg, A, c) / tm(stg, Bm, c) for c in joint]
        L.append("- %s: median ratio %s over %d matched cells %s" % (name, ("%.3f" % median(ratios)) if ratios else "—", len(joint), joint))
    L.append("\n## 3. Mechanisms (typed provenance; FULL-safe fallback is never a no-op proof)\n")
    cnt = collections.Counter()
    for k, v in MECH.items():
        stage, arm, case = k.split("|")
        if arm == "GENERAL_BIDI_V2" and stage == "primary_breadth":
            for mech in ("views", "demand", "fusion"):
                cnt["%s:%s" % (mech, v[mech])] += 1
    L.append("Typed outcomes over the GENERAL_BIDI_V2 20 s cells with a plan record (certified AND stopped, via the diagnostic record): %s. Per-node provenance counts are in MECHANISMS.json.\n" % dict(cnt))
    L.append("## 4. Ablations (20 s)\n\n| ablation | certified | lost vs GENERAL | gained vs GENERAL | median time ratio (ablation / GENERAL) |\n|---|---|---|---|---|")
    for a in ARMS_A:
        ca = set(cert("ablation_breadth", a)); joint = sorted(ca & g20); ratios = [tm("ablation_breadth", a, c) / tm("primary_breadth", "GENERAL_BIDI_V2", c) for c in joint if tm("primary_breadth", "GENERAL_BIDI_V2", c)]
        L.append("| %s | %d/46 | %s | %s | %s (n=%d) |" % (a, len(ca), sorted(g20 - ca) or "—", sorted(ca - g20) or "—", ("%.3f" % median(ratios)) if ratios else "—", len(joint)))
    L.append("\n## 5. Stopped cells: what was running (from the durable diagnostic record)\n\n| cell | status | stop | route attempts | primal rows | reverse rows | frame depth | plan order |\n|---|---|---|---|---|---|---|---|")
    for r in cells:
        if r["arm"] in PI.GB_ARMS and r.get("status") in ("RESOURCE_STOP", "NUMERIC_UNRESOLVED", "NUMERIC_RANGE", "ROUTE_LIMITATION", "REJECTED") and r.get("accepted"):
            a = (r.get("attempts") or [{}])[-1]; c_ = a.get("counters") or {}
            L.append("| %s | %s | %s | %s | %s | %s | %s | %s |" % (r["job"].split(":", 2)[2][:40], r["status"], json.dumps(r.get("stop"))[:50], [(x.get("route"), x.get("stop") or x.get("outcome")) for x in (r.get("attempts") or [])], c_.get("primal_rows"), c_.get("reverse_rows"), c_.get("max_frame_depth"), r.get("plan_order")))
    L.append("\n## 6. Reconciliation\n")
    L.append("Charged (nonnested; = the live guard): **%.1f s of %.0f s** by scope %s (outer attempts: %s). Unresolved: %s. Compliance: %s. Rows: %s; accepted %d of %d; delivered valid output but not accepted: %s. Inputs equal the census hashes: %s; comparator config unchanged: %s. Width statistics report raw and delivered widths separately (SCORES.json).\n"
             % (B["total_charged_s"], B["ceiling_s"], B["by_scope_s"], [(o["job"], o.get("parent_remainder_s")) for o in B["outer_attempts"]], B["unresolved"] or "none", B["compliance"], miss["resolutions"], miss["accepted"], miss["planned"], miss["delivered_valid_output_not_accepted"] or "none", all(v["model_ok"] and v["evidence_ok"] for v in UH["inputs"].values()), UH["config_adp_ok"]))
    L.append("Permitted conclusions: coverage counts on accepted rows are the primary result; ratios are exploratory, matched-cell only; one observation per cell. STOPPED FOR REVIEW.\n")
    open(os.path.join(D, "REPORT.md"), "w").write("\n".join(L))
    print(json.dumps({"G20": len(g20), "P20": len(p20), "ADP20": len(a20), "libDAI20": len(comp("primary_breadth", "EXACT_LIBDAI")), "G120": len(g120), "P120": len(p120), "ablations": {a: len(cert("ablation_breadth", a)) for a in ARMS_A}, "charged_s": B["total_charged_s"], "compliance": B["compliance"][:40], "accepted": miss["accepted"], "planned": miss["planned"]}))


if __name__ == "__main__":
    main(os.path.abspath(sys.argv[1]))
