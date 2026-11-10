"""GENERAL_BIDI_V2 closeout (repair of the V1 closeout after reviews H3 / R2-09 / empirical §3,7,8): CELLS_LEDGER.jsonl (every planned row JOINED to
its bound record AND its receipt; `accepted` only when the record is bound to the planned task / arm / cell id AND exactly one matching receipt
says COMPLETED with an empty group), BUDGET_LEDGER.json (nonnested; every repeated launch kept; outer stage receipts diagnostic; parent remainders
once per stage; unknown outer receipts keep compliance QUALIFIED), MISSINGNESS.json (typed), SCORES.json (raw vs DELIVERED widths), MECHANISMS.json
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
def cells_ledger(D, man):
    led = jl(os.path.join(D, "GB_LEDGER.jsonl")); frozen = man["frozen_utc"]
    receipts = collections.defaultdict(list)
    for r in led:
        if r["kind"] == "RECEIPT" and r["job"].startswith("cell:") and r.get("start_utc", "") >= frozen:
            receipts[r["job"]].append(r)
    out = []
    for c in man["cells"]:
        od = os.path.join(D, c["out_dir"]); cj = os.path.join(od, "cell.json"); job = "cell:%03d:%s:%s:%s:%ds:%s" % (c["index"], c["stage"], c["case"], c["arm"], int(c["budget_s"]), c["cell_id"]); rcs = receipts.get(job, []); cs = man["cases"][c["case"]]
        row = dict(c, job=job, family=cs["family"], receipts=len(rcs), accepted=False)
        rc = rcs[-1] if rcs else None
        row.update(supervisor_outcome=(rc or {}).get("outcome"), supervisor_wall_s=(rc or {}).get("wall_s"), peak_tree_rss_bytes=(rc or {}).get("peak_tree_rss_bytes"), returncode=(rc or {}).get("returncode"), group_empty_at_receipt=(rc or {}).get("group_empty_at_receipt"))
        if os.path.exists(cj):
            r = json.load(open(cj)); t_ = r.get("task") or {}
            bound = (r.get("arm") == c["arm"] and (r.get("status") == "NO_RECORD" or c["arm"] not in PI.GB_ARMS or (t_.get("raw_model_sha256") == cs["raw_model_sha256"] and t_.get("raw_evidence_sha256") == cs["raw_evidence_sha256"] and (r.get("expected_task") or {}).get("cell_id") in (None, c["cell_id"]))))
            if c["arm"] not in PI.GB_ARMS and r.get("status") != "NO_RECORD":
                tsrc = r.get("task") or r.get("source") or {}
                bound = bound and (not tsrc or tsrc.get("raw_model_sha256") == cs["raw_model_sha256"])
            if not bound:
                row.update({"status": "UNBOUND_RECORD", "resolution": "RECORD_NOT_BOUND_TO_TASK", "record_arm": r.get("arm"), "record_status": r.get("status")}); out.append(row); continue
            row.update({"status": r.get("status"), "reason": (r.get("reason") or "")[:300] if isinstance(r.get("reason"), str) else r.get("reason"), "complete_response_s": r.get("complete_response_s"), "complete_response_from_launch_s": r.get("complete_response_from_launch_s"), "within_deadline": r.get("within_deadline"), "within_deadline_from_launch": r.get("within_deadline_from_launch"), "deadline_classification_clock": r.get("deadline_classification_clock"), "t_first_complete_output_s": r.get("t_first_complete_output_s"), "phases_s": r.get("phases_s"), "stop": r.get("stop"), "censored": r.get("censored", False), "maxrss_self_bytes": r.get("maxrss_self_bytes")})
            if c["arm"] in PI.GB_ARMS:
                src = r if "plan" in r else (r.get("diagnostic") or {})
                row.update({"route": r.get("route"), "precision": r.get("precision"), "max_width_raw": r.get("max_width"), "delivered_max_width": (r.get("certified") or {}).get("delivered_max_width"), "reductions": (src.get("reductions") or {}).get("steps"), "free_reduced": (src.get("reductions") or {}).get("free_reduced"), "plan_totals": (src.get("plan") or {}).get("totals"), "plan_order": ((src.get("plan") or {}).get("order") or {}).get("name"), "plan_candidates": [{k: x.get(k) for k in ("order", "state", "baseline", "chosen", "mandatory_representable")} for x in (src.get("plan_candidates") or [])], "mechanisms": src.get("mechanisms"), "node_provenance": [{k: nd.get(k) for k in ("nid", "support_prov", "demand_prov", "view_prov", "fused_by", "downgrade")} for nd in (src.get("plan") or {}).get("nodes", [])], "binary64_admission": (src.get("binary64_admission") or {}).get("checks"),
                            "attempts": [{k: a.get(k) for k in ("route", "precision", "outcome", "stop", "stop_phase", "create_s", "forward_s", "reverse_s", "refused", "labels", "delta_max", "wall_s")} | {"counters": a.get("counters"), "counters_after_forward": a.get("counters_after_forward")} for a in (src.get("attempts") or [])], "reference_fallback": (src.get("reference_fallback") or {}).get("status"), "discovery_stop": (src.get("plan") or {}).get("discovery_stop"), "diagnostic_present": "diagnostic" in r, "live_at_stop": (r.get("diagnostic") or {}).get("live")})
            row["resolution"] = "COMPLETED_RECORD" if r.get("status") != "NO_RECORD" else "KILLED_NO_RECORD"
        elif os.path.exists(os.path.join(od, "NOT_LAUNCHED.json")):
            row.update(json.load(open(os.path.join(od, "NOT_LAUNCHED.json")))); row["resolution"] = "NOT_LAUNCHED"; out.append(row); continue
        else:
            row.update({"status": "UNLAUNCHED", "resolution": "EXPLICITLY_UNLAUNCHED"}); out.append(row); continue
        if rc is None:
            row["resolution"] = "RECORD_WITHOUT_RECEIPT"
        elif len(rcs) > 1:
            row["resolution"] = "MULTIPLE_RECEIPTS"; row["all_receipts"] = [{k: x.get(k) for k in ("jid", "start_utc", "outcome", "wall_s")} for x in rcs]
        elif rc.get("outcome") not in ("COMPLETED", "NONZERO_EXIT", "TIMEOUT_KILL", "MEMORY_KILL") or rc.get("cleanup_unresolved") or rc.get("group_empty_at_receipt") is False:
            row["resolution"] = "RECEIPT_CONTRADICTS_RECORD" if row["resolution"] == "COMPLETED_RECORD" else row["resolution"]
        if row["resolution"] == "COMPLETED_RECORD" and rc is not None and len(rcs) == 1:
            row["accepted"] = True                                                              # bound record + exactly one compatible receipt
        out.append(row)
    return out


def budget(D, man, cells):
    led = jl(os.path.join(D, "GB_LEDGER.jsonl")); rec = collections.defaultdict(list)
    for r in led:
        if r["kind"] == "RECEIPT":
            rec[r["jid"]].append(r)
    total = 0.0; by = collections.OrderedDict(); unresolved = []; jobs = []; outer = []
    for r in led:
        if r["kind"] != "START":
            continue
        rcs = rec.get(r["jid"], []); rc = rcs[-1] if rcs else None
        if r["scope"].startswith("stage_outer"):
            outer.append({"job": r["job"], "start_utc": r["start_utc"], "receipt": bool(rc), "wall_s": (rc or {}).get("wall_s"), "outcome": (rc or {}).get("outcome"), "in_final_run": r["start_utc"] >= man["frozen_utc"]}); continue
        scope = r["scope"] if r["start_utc"] >= man["frozen_utc"] else "pre_freeze_" + r["scope"]
        if rc is not None and not rc.get("cleanup_unresolved") and len(rcs) == 1:
            total += rc["wall_s"]; by[scope] = by.get(scope, 0.0) + rc["wall_s"]; jobs.append({"job": r["job"], "jid": r["jid"], "scope": scope, "wall_s": round(rc["wall_s"], 3), "outcome": rc["outcome"]})
        else:
            unresolved.append({"job": r["job"], "jid": r["jid"], "reason": "no receipt" if rc is None else ("duplicate receipts" if len(rcs) > 1 else "cleanup unresolved")}); total += max((rc or {}).get("wall_s") or 0.0, r.get("max_permitted_charge_s") or 0.0)
    stage_rem = {}
    for s, _, _ in PI.STAGES:
        o = [x for x in outer if x["job"] == "stage_runner:%s" % s and x["in_final_run"]]; kids = by.get("matrix_" + s, 0.0)
        if o and o[-1].get("wall_s") is not None:
            stage_rem[s] = {"outer_wall_s": o[-1]["wall_s"], "children_receipts_s": kids, "parent_remainder_s": max(0.0, o[-1]["wall_s"] - kids)}
        else:
            stage_rem[s] = {"outer_wall_s": None, "children_receipts_s": kids, "parent_remainder_s": None, "note": "outer receipt missing or stage not run: parent remainder UNKNOWN"}
    rem = sum(v["parent_remainder_s"] or 0.0 for v in stage_rem.values()); unknown_outer = [o for o in outer if not o["receipt"]]
    qualified = bool(unresolved) or bool(unknown_outer) or any(v["parent_remainder_s"] is None and v["children_receipts_s"] > 0 for v in stage_rem.values())
    return {"ceiling_s": man["ceiling_s"], "rule": "nonnested: every non-outer START once (receipt wall; no receipt / duplicate receipts / unresolved cleanup -> max permitted, listed); outer stage receipts diagnostic; parent-only remainder once per stage where its outer receipt exists; an outer START without receipt keeps compliance QUALIFIED (its parent overhead is UNKNOWN)",
            "total_charged_s": round(total + rem, 3), "jobs_total_s": round(total, 3), "stage_parent_remainders": stage_rem, "by_scope_s": {k: round(v, 3) for k, v in by.items()}, "unresolved": unresolved, "outer_starts": outer, "outer_without_receipt": unknown_outer, "jobs": jobs,
            "compliance": "QUALIFIED" if qualified else "all non-outer starts receipted exactly once; parent remainders measured; uncharged: read-only shell inspections, git, file copies",
            "within_ceiling_known_charges": total + rem <= man["ceiling_s"], "uncharged_exposure_disclosed": True}


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
    miss = {"planned": len(cells), "accepted": sum(1 for r in cells if r["accepted"]), "resolutions": dict(res), "not_accepted_rows": [{"job": r["job"], "resolution": r["resolution"], "status": r.get("status")} for r in cells if not r["accepted"] and r["resolution"] not in ("EXPLICITLY_UNLAUNCHED",)], "unavailable_slots": man["unavailable_slots"],
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
        r = by.get((stage, arm, case), {}); return r.get("status") if r.get("accepted") or r.get("resolution") in ("NOT_LAUNCHED", "EXPLICITLY_UNLAUNCHED") else ("NOT_ACCEPTED:" + str(r.get("resolution")) if r else None)
    def cert(stage, arm):
        return [c for c in cases if st(stage, arm, c) in CERT]
    def comp(stage, arm):
        return [c for c in cases if st(stage, arm, c) in DONE_UNCERT]
    def tm(stage, arm, c):
        r = by.get((stage, arm, c), {}); return r.get("complete_response_from_launch_s") or r.get("complete_response_s")
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
    L.append("Charged (nonnested): **%.1f s of %.0f s** = jobs %.1f s (by scope %s) + stage-parent remainders %s. Unresolved starts: %s. Outer starts without receipt: %s. Compliance: %s. Rows: %s; accepted %d of %d. Inputs equal the census hashes: %s; comparator config unchanged: %s. Width statistics report raw and delivered widths separately (SCORES.json).\n"
             % (B["total_charged_s"], B["ceiling_s"], B["jobs_total_s"], B["by_scope_s"], {k: (round(v["parent_remainder_s"], 1) if v["parent_remainder_s"] is not None else "UNKNOWN") for k, v in B["stage_parent_remainders"].items()}, B["unresolved"] or "none", [o["job"] for o in B["outer_without_receipt"]] or "none", B["compliance"], miss["resolutions"], miss["accepted"], miss["planned"], all(v["model_ok"] and v["evidence_ok"] for v in UH["inputs"].values()), UH["config_adp_ok"]))
    L.append("Permitted conclusions: coverage counts on accepted rows are the primary result; ratios are exploratory, matched-cell only; one observation per cell. STOPPED FOR REVIEW.\n")
    open(os.path.join(D, "REPORT.md"), "w").write("\n".join(L))
    print(json.dumps({"G20": len(g20), "P20": len(p20), "ADP20": len(a20), "libDAI20": len(comp("primary_breadth", "EXACT_LIBDAI")), "G120": len(g120), "P120": len(p120), "ablations": {a: len(cert("ablation_breadth", a)) for a in ARMS_A}, "charged_s": B["total_charged_s"], "compliance": B["compliance"][:40], "accepted": miss["accepted"], "planned": miss["planned"]}))


if __name__ == "__main__":
    main(os.path.abspath(sys.argv[1]))
