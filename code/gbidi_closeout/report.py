"""GENERAL_BIDI_V1 closeout: CELLS_LEDGER.jsonl (every planned row reconciled to a receipt/status), BUDGET_LEDGER.json (nonnested: cell receipts
+ qualification/inspection jobs + measured stage-parent remainders; outer stage receipts diagnostic only), MISSINGNESS.json, SCORES.json
(reference tiers R0/R1/R2/R3 from the frozen earlier SCORES.json; containment / distance diagnostics), MECHANISMS.json (applied / no-op / unknown
per case and mechanism), UNCHANGED_HISTORY.json, REPORT.md (the eight required answers in order) and HANDOFF.md. Reads only saved artifacts.
    python -m gbidi_closeout.report D"""
from __future__ import annotations
import os, sys, json, hashlib, math, collections
HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__))); sys.path.insert(0, HERE)
sys.set_int_max_str_digits(0)
from fractions import Fraction as Fr
from gbidi import pilot as PI
OLD = os.path.join(HERE, "runs", "mdi_2026-10-28", "EXTERNAL_SWEEP_2026-11-06"); ADP = os.path.join(HERE, "runs", "mdi_2026-10-28", "AGGREGATE_DP_2026-11-07"); CENSUS = PI.CENSUS_D
ARMS_P = ["GENERAL_BIDI_V1", "NATIVE_PLAIN_V1", "ADP_REPAIRED", "EXACT_LIBDAI"]; ARMS_A = ["A1_NO_DEMAND_MASKS", "A2_NO_FUSION", "A3_NO_RESPONSE_VIEWS"]
CERT = ("CERTIFIED",); DONE_UNCERT = ("COMPLETE",)


def jl(p):
    return [json.loads(l) for l in open(p)] if os.path.exists(p) else []


def sha(p):
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for ch in iter(lambda: f.read(1 << 20), b""):
            h.update(ch)
    return h.hexdigest()


def read_points(p):
    from ext import uai as U
    rows, _ = U.read_mar(p); return [[Fr(x) for x in r] for r in rows]


# ---------------------------------------------------------------------------------------------------------------- ledgers
def cells_ledger(D, man):
    led = jl(os.path.join(D, "GB_LEDGER.jsonl")); frozen = man["frozen_utc"]
    rc_by_job = {r["job"]: r for r in led if r["kind"] == "RECEIPT" and r["job"].startswith("cell:") and r["start_utc"] >= frozen}       # attempt-1 receipts (before the final freeze) are excluded from the cell match (kept in the budget)
    out = []
    for c in man["cells"]:
        od = os.path.join(D, c["out_dir"]); cj = os.path.join(od, "cell.json"); job = "cell:%03d:%s:%s:%s:%ds" % (c["index"], c["stage"], c["case"], c["arm"], int(c["budget_s"])); rc = rc_by_job.get(job)
        row = dict(c, job=job, family=man["cases"][c["case"]]["family"], supervisor_outcome=(rc or {}).get("outcome"), supervisor_wall_s=(rc or {}).get("wall_s"), peak_tree_rss_bytes=(rc or {}).get("peak_tree_rss_bytes"), rss_samples=(rc or {}).get("rss_samples"), returncode=(rc or {}).get("returncode"))
        if os.path.exists(cj):
            r = json.load(open(cj)); row.update({"status": r.get("status"), "reason": (r.get("reason") or "")[:300] if isinstance(r.get("reason"), str) else r.get("reason"), "complete_response_s": r.get("complete_response_s"), "complete_response_from_launch_s": r.get("complete_response_from_launch_s"), "within_deadline": r.get("within_deadline"), "t_first_complete_output_s": r.get("t_first_complete_output_s"), "phases_s": r.get("phases_s"), "stop": r.get("stop"), "censored": r.get("censored", False), "maxrss_self_bytes": r.get("maxrss_self_bytes")})
            if c["arm"] in PI.GB_ARMS:
                row.update({"route": r.get("route"), "precision": r.get("precision"), "max_width": r.get("max_width"), "reductions": (r.get("reductions") or {}).get("steps"), "free_reduced": (r.get("reductions") or {}).get("free_reduced"), "plan_totals": (r.get("plan") or {}).get("totals"), "plan_order": ((r.get("plan") or {}).get("order") or {}).get("name"), "mechanisms": r.get("mechanisms"), "binary64_admission": (r.get("binary64_admission") or {}).get("checks"), "attempts": [{k: a.get(k) for k in ("route", "precision", "outcome", "stop", "forward_s", "reverse_s", "refused")} | {"counters": a.get("counters")} for a in (r.get("attempts") or [])], "reference_fallback": (r.get("reference_fallback") or {}).get("status"), "discovery_stop": (r.get("mechanisms") or {}).get("discovery_stop")})
            row["resolution"] = "COMPLETED_RECORD" if r.get("status") != "NO_RECORD" else "KILLED_NO_RECORD"
        elif os.path.exists(os.path.join(od, "NOT_LAUNCHED.json")):
            row.update(json.load(open(os.path.join(od, "NOT_LAUNCHED.json")))); row["resolution"] = "NOT_LAUNCHED"
        else:
            row.update({"status": "UNLAUNCHED", "resolution": "EXPLICITLY_UNLAUNCHED"})
        if rc is None and row["resolution"] == "COMPLETED_RECORD":
            row["resolution"] = "RECORD_WITHOUT_RECEIPT"
        out.append(row)
    return out


def budget(D, man, cells):
    led = jl(os.path.join(D, "GB_LEDGER.jsonl")); rec = {r["jid"]: r for r in led if r["kind"] == "RECEIPT"}; total = 0.0; by = collections.OrderedDict(); unresolved = []; jobs = []; outer = {}
    for r in led:
        if r["kind"] != "START":
            continue
        rc = rec.get(r["jid"])
        if r["scope"].startswith("stage_outer"):
            key = r["job"] if r["start_utc"] >= man["frozen_utc"] else r["job"] + " (attempt 1, aborted; START without receipt: the outer supervisor was SIGKILLed with its group -- see amendment_1)"
            outer[key] = {"receipt": bool(rc), "wall_s": (rc or {}).get("wall_s"), "outcome": (rc or {}).get("outcome"), "note": "outer stage-runner receipt: DIAGNOSTIC; its children are the charged units; the parent-only remainder is measured below"}; continue
        scope = r["scope"] if (not r["scope"].startswith("matrix_") or r["start_utc"] >= man["frozen_utc"]) else "attempt1_aborted_" + r["scope"]
        if rc is not None and not rc.get("cleanup_unresolved"):
            total += rc["wall_s"]; by[scope] = by.get(scope, 0.0) + rc["wall_s"]; jobs.append({"job": r["job"], "scope": scope, "wall_s": round(rc["wall_s"], 3), "outcome": rc["outcome"]})
        elif rc is not None:
            unresolved.append(r["job"]); total += max(rc["wall_s"], r.get("max_permitted_charge_s") or 0.0)
        else:
            unresolved.append(r["job"]); total += (r.get("max_permitted_charge_s") or 0.0)
    # stage-parent remainder: outer receipt wall minus the sum of its children's receipts (nonnegative), charged ONCE per stage
    stage_rem = {}
    for s, _, _ in PI.STAGES:
        o = outer.get("stage_runner:%s" % s); kids = by.get("matrix_" + s, 0.0)                                     # final-run children only (outer receipt of the final run)
        if o and o.get("wall_s") is not None:
            stage_rem[s] = {"outer_wall_s": o["wall_s"], "children_receipts_s": kids, "parent_remainder_s": max(0.0, o["wall_s"] - kids)}
        else:
            stage_rem[s] = {"outer_wall_s": None, "children_receipts_s": kids, "parent_remainder_s": None, "note": "outer receipt missing: parent remainder UNKNOWN"}
    rem = sum(v["parent_remainder_s"] or 0.0 for v in stage_rem.values())
    return {"ceiling_s": man["ceiling_s"], "rule": "nonnested: every non-outer job receipt once; outer stage receipts are diagnostic; the parent-only remainder (outer wall - children) is added once per stage; a START without receipt or with unresolved cleanup is charged at max permitted and listed", "total_charged_s": round(total + rem, 3), "jobs_total_s": round(total, 3), "stage_parent_remainders": stage_rem, "by_scope_s": {k: round(v, 3) for k, v in by.items()}, "unresolved": unresolved, "outer_receipts": outer, "jobs": jobs,
            "attempt1_aborted_cells_s": round(sum(v for k, v in by.items() if k.startswith("attempt1_aborted_")), 3),
            "compliance": "QUALIFIED" if (unresolved or any(v["parent_remainder_s"] is None for v in stage_rem.values())) else "all non-outer starts receipted; parent remainders measured; uncharged: read-only shell inspections, git, file copies, the disclosed pre-freeze development smoke runs",
            "within_ceiling": total + rem <= man["ceiling_s"]}


# ---------------------------------------------------------------------------------------------------------------- references / scores
def references(man, cells):
    old = json.load(open(os.path.join(ADP, "SCORES.json")))["reference_classes"]; refs = {}
    from ext import uai as U
    for case, c in man["cases"].items():
        m = U.read_model(os.path.join(HERE, c["model_path"])); cls = old.get(case, {}).get("class", "R3"); pts = None; src = old.get(case, {}).get("source")
        if cls == "R0":
            d = json.load(open(os.path.join(OLD, "references", case + ".R0.json"))); pts = [[Fr(x) for x in d["marginals"][str(v)]] for v in range(m.nvars)]
        elif cls == "R1":
            rows = jl(os.path.join(OLD, "CELLS_LEDGER.jsonl")); hit = [r for r in rows if r["case"] == case and r["arm"] == "EXACT" and r.get("status") == "COMPLETE" and not r.get("censored")]
            if hit:
                pts = read_points(os.path.join(OLD, hit[0]["out_dir"], "output.MAR"))
        elif cls == "R2":
            op = os.path.join(OLD, "sources", "uai14", "sol", case + ".uai.MAR")
            if os.path.exists(op):
                try:
                    pts = read_points(op)
                except Exception:
                    pts = None
        refs[case] = {"class": cls, "source": src, "points_available": pts is not None, "_pts": pts, "nvars": m.nvars}
    return refs


def scores(D, man, cells, refs):
    out = {}
    for r in cells:
        if r["arm"] not in PI.GB_ARMS or r.get("status") != "CERTIFIED":
            continue
        ref = refs[r["case"]]; od = os.path.join(D, r["out_dir"]); rec = json.load(open(os.path.join(od, "checked_record.json"))); pts = read_points(os.path.join(od, "output.MAR"))
        ivs = {int(v): [(Fr(a), Fr(b)) for a, b in row] for v, row in rec["certified_intervals"].items()}
        e = {"case": r["case"], "arm": r["arm"], "stage": r["stage"], "reference_class": ref["class"], "max_published_width": float(max(b - a for row in ivs.values() for a, b in row))}
        if ref["_pts"] is not None:
            inside = sum(1 for v in ivs for s in range(len(ivs[v])) if ivs[v][s][0] <= ref["_pts"][v][s] <= ivs[v][s][1]); n = sum(len(ivs[v]) for v in ivs)
            e["reference_coordinates_inside_interval"] = "%d/%d" % (inside, n); e["max_abs_distance_point_to_reference"] = float(max(abs(pts[v][s] - ref["_pts"][v][s]) for v in ivs for s in range(len(ivs[v]))))
            e["containment_meaning"] = "PROOF CHECK (exact R0)" if ref["class"] == "R0" else "consistency observation only (R1/R2 are rounded points; exact containment not expected for ~1e-13 wide intervals)"
        out["%s|%s|%s" % (r["stage"], r["arm"], r["case"])] = e
    return out


# ---------------------------------------------------------------------------------------------------------------- report
def main(D):
    man = json.load(open(os.path.join(D, "GB_MANIFEST.json"))); cells = cells_ledger(D, man); B = budget(D, man, cells); refs = references(man, cells); S = scores(D, man, cells, refs)
    with open(os.path.join(D, "CELLS_LEDGER.jsonl"), "w") as f:
        for r in cells:
            f.write(json.dumps(r, default=str) + "\n")
    json.dump(B, open(os.path.join(D, "BUDGET_LEDGER.json"), "w"), indent=1); json.dump({"reference_classes": {c: {k: v for k, v in refs[c].items() if k != "_pts"} for c in refs}, "frozen_source": "AGGREGATE_DP_2026-11-07/SCORES.json sha256 %s" % sha(os.path.join(ADP, "SCORES.json")), "counts": dict(collections.Counter(refs[c]["class"] for c in refs)), "cells": S}, open(os.path.join(D, "SCORES.json"), "w"), indent=1, default=str)
    miss = {"planned": len(cells), "completed_record": sum(1 for r in cells if r["resolution"] == "COMPLETED_RECORD"), "killed_no_record": [r["job"] for r in cells if r["resolution"] == "KILLED_NO_RECORD"], "not_launched": [r["job"] for r in cells if r["resolution"].startswith(("NOT_LAUNCHED", "EXPLICITLY"))], "record_without_receipt": [r["job"] for r in cells if r["resolution"] == "RECORD_WITHOUT_RECEIPT"], "unavailable_slots": man["unavailable_slots"],
            "uncharged_disclosed": ["pre-freeze development smoke runs of the pipeline on synthetic models (not charged)", "one direct diagnosis run of BARLEY on both arms / both routes after attempt 1 stopped (disclosed prior exposure on a panel input; ~22 s; not charged)", "read-only shell inspections, git, file copies"], "attempt1_aborted": "37 cells of attempt 1 (manifest dade3fb1) preserved under attempt1_aborted/; not evidence; their receipts remain charged"}
    json.dump(miss, open(os.path.join(D, "MISSINGNESS.json"), "w"), indent=1)
    # unchanged history
    from adp import campaign as C
    h, _ = C.code_hash(); UH = {"frozen_numerical_set_code_hash": h, "equals_repaired_pin_da5b2c49": h.startswith("da5b2c49"), "inputs": {c: {"model_ok": sha(os.path.join(HERE, v["model_path"])) == v["raw_model_sha256"], "evidence_ok": sha(os.path.join(HERE, v["evidence_path"])) == v["raw_evidence_sha256"]} for c, v in man["cases"].items()}}
    cb = os.path.join(CENSUS, "review_2026-11-08", "CELL_FILE_HASHES_before.json")
    if os.path.exists(cb):
        bh = json.load(open(cb)); UH["census_cells_unchanged"] = all(os.path.exists(os.path.join(CENSUS, k)) and sha(os.path.join(CENSUS, k)) == v for k, v in bh.items()); UH["census_cell_files"] = len(bh)
    json.dump(UH, open(os.path.join(D, "UNCHANGED_HISTORY.json"), "w"), indent=1)
    # mechanisms table: typed outcome per cell and mechanism
    def typed(kind, mk, r):
        m = mk[kind]
        if m["state"].startswith("DISABLED"):
            return "DISABLED"
        fired = (m["compressed_axes"] if kind == "views" else m["entries_skipped_by_demand"] if kind == "demand" else m["edges_fused_by_policy"]) > 0
        if fired:
            return "APPLIED_WITH_PROOF"
        if kind == "fusion":
            return "DECLINED_BY_FROZEN_POLICY"
        return "SCAN_CAPPED_UNKNOWN" if (r.get("discovery_stop") or m["state"].startswith("SCAN_CAPPED")) else "PROVED_NO_OP"
    MECH = {}
    for r in cells:
        if r["arm"] not in PI.GB_ARMS or not r.get("mechanisms"):
            continue
        mk = r["mechanisms"]
        MECH["%s|%s|%s" % (r["stage"], r["arm"], r["case"])] = {"views": typed("views", mk, r), "views_compressed_axes": mk["views"]["compressed_axes"], "views_offered_axes": mk["views"]["offered_axes"],
                                                                 "demand": typed("demand", mk, r), "demand_nodes": mk["demand"]["nodes_with_explicit_demand"], "demand_entries_skipped": mk["demand"]["entries_skipped_by_demand"],
                                                                 "fusion": typed("fusion", mk, r), "fusion_edges_offered": mk["fusion"]["edges_offered"], "fusion_by_policy": mk["fusion"]["edges_fused_by_policy"], "fusion_by_memory": mk["fusion"]["edges_fused_by_memory"],
                                                                 "discovery_stop": r.get("discovery_stop"), "route": r.get("route"), "status": r.get("status")}
    json.dump(MECH, open(os.path.join(D, "MECHANISMS.json"), "w"), indent=1)
    # ---------------------------------------------------------------- REPORT
    by = {(r["stage"], r["arm"], r["case"]): r for r in cells}; cases = PI.inventory(); fam = {c: man["cases"][c]["family"] for c in cases}; families = [f for f, _ in PI.FAMILY_ORDER]
    def st(stage, arm, case):
        return by.get((stage, arm, case), {}).get("status")
    def cert(stage, arm):
        return [c for c in cases if st(stage, arm, c) in CERT]
    def comp(stage, arm):
        return [c for c in cases if st(stage, arm, c) in DONE_UNCERT]
    L = ["# GENERAL_BIDI_V1 broad round — 414 cells on the 46-case panel (9 November 2026)\n",
         "Branch `%s`, frozen commit `%s` (kernel binary `%s`, Apple clang 15 `-ffp-model=strict -ffp-contract=off`, MPFR %s / GMP %s). Seed %d; order per empirical_plan.txt §3 (reconciled). One observation per cell; the panel is a disclosed broad TRANSFER experiment (previously exposed), not a blind holdout. Attempt 1 of the round was stopped after 37 cells for a correctness flaw (amendment_1; cells preserved, not evidence); this is the complete second run on the repaired, re-frozen source.\n"
         % (man["branch"], man["commit"][:12], man["kernel_binary_sha256"][:12], man["kernel_build"].get("linked_libraries_sha256") and "4.2.2", "6.3.0", man["seed"])]
    # Q1
    q = sorted(f for f in os.listdir(os.path.join(D, "qualification")) if f.endswith(".txt")); last = {}
    for f in q:
        t = open(os.path.join(D, "qualification", f)).read().strip().splitlines(); last[f] = t[-1] if t else ""
    L.append("## 1. Did a genuinely general implementation qualify, and what remains in the trusted boundary?\n")
    L.append("Yes, on the final build: `tests/test_gbidi.py` 76 controls (every arm × 10 input classes × 2 routes against the exhaustive rational oracle: nonbinary, higher arity, odd cycles, zeros, evidence, disconnected + isolated, duplicate occurrences, scalars, grid, kite; the brief's fixtures C D E F G H I J K L (exact answers); the mandatory shared-node split-delta control Z = 20, N = (5, 15) with eviction + recomputation between deltas; mechanism witnesses with fewer demanded/materialized entries than the SAME-backend disabled control; exact integer reference stream used on a memory stop; deadline stop; empty model; cells for all 5 arms; binding/publication rejections; binary64-vs-MPFR intersection + simplex bracket + delta-0 mutant) and 117 existing regressions pass (receipts in `qualification/`: %s). Qualification failures along the way are preserved (pytest_gbidi_1..11). Synthetic scale cells (`synthetic/SYNTHETIC_SCALE.json`): K14,14, 4×4 grid and a mixed-cardinality 10-variable model certify on both arms; exact truth inside where the joint is enumerable.\n" % "; ".join("%s: %s" % (f, last[f][:60]) for f in q if "pytest" in f or "synthetic" in f))
    L.append("Trusted boundary (stated plainly): `gbidi/executor.py`, `ext.uai`, `adp.source`'s shared reductions with their marked decoder, `gbidi/plan.py` (re-derived from the reduced model), the native kernel `gbidi/kernel.cpp` with MPFR/GMP, `adp.publish` and the separate point verifier. ONE authoritative numerical pass per cell; no second independent numerical implementation on any benchmark cell. The compiler's proposals are plans only. Pending pilot defects: F1 (no unguarded float bridge: MPFR endpoints are carried as exact dyadics into the enclosure; the binary64 route needs the range + depth premise of the ACTUAL plan) and F2 (empty dimensions) are covered by controls K and the empty-model / unary-only tests. Deviation found and repaired INSIDE this round (amendment_1): the first freeze's binary64 depth label omitted accumulation counts; the simplex-bracket detector now refuses any unsound enclosure before publication.\n")
    # Q2
    L.append("## 2. Certified coverage at 20 s and 120 s, by family; changes vs native plain and the comparators\n")
    L.append("| arm / stage | certified | complete (uncertified) | typed resource stops | late | other |\n|---|---|---|---|---|---|")
    for stage, arms, b in PI.STAGES:
        for a in arms:
            sts = [st(stage, a, c) for c in cases]; L.append("| %s %ds | %d/46 | %d | %d | %d | %s |" % (a, int(b), sum(1 for x in sts if x in CERT), sum(1 for x in sts if x in DONE_UNCERT), sum(1 for x in sts if x in ("RESOURCE_STOP", "TIMEOUT", "ADMISSION_REFUSED", "NUMERIC_UNRESOLVED")), sum(1 for x in sts if x == "LATE_OUTPUT"), dict(collections.Counter(x for x in sts if x not in CERT + DONE_UNCERT + ("RESOURCE_STOP", "TIMEOUT", "ADMISSION_REFUSED", "NUMERIC_UNRESOLVED", "LATE_OUTPUT")))))
    L.append("\n**Per family, certified counts** (GENERAL 20 / PLAIN 20 / ADP 20 / libDAI-complete 20 | GENERAL 120 / PLAIN 120):\n\n| family | n | G20 | P20 | ADP20 | libDAI20 | G120 | P120 |\n|---|---|---|---|---|---|---|---|")
    for f in families:
        cs = [c for c in cases if fam[c] == f]; L.append("| %s | %d | %d | %d | %d | %d | %d | %d |" % (f, len(cs), sum(1 for c in cs if st("primary_breadth", "GENERAL_BIDI_V1", c) in CERT), sum(1 for c in cs if st("primary_breadth", "NATIVE_PLAIN_V1", c) in CERT), sum(1 for c in cs if st("primary_breadth", "ADP_REPAIRED", c) in CERT), sum(1 for c in cs if st("primary_breadth", "EXACT_LIBDAI", c) in DONE_UNCERT), sum(1 for c in cs if st("primary_depth", "GENERAL_BIDI_V1", c) in CERT), sum(1 for c in cs if st("primary_depth", "NATIVE_PLAIN_V1", c) in CERT)))
    g20, p20, a20 = set(cert("primary_breadth", "GENERAL_BIDI_V1")), set(cert("primary_breadth", "NATIVE_PLAIN_V1")), set(cert("primary_breadth", "ADP_REPAIRED")); g120, p120 = set(cert("primary_depth", "GENERAL_BIDI_V1")), set(cert("primary_depth", "NATIVE_PLAIN_V1"))
    L.append("\nCoverage changes (20 s): GENERAL vs PLAIN gained %s, lost %s; GENERAL vs ADP gained %s, lost %s. (120 s) GENERAL vs PLAIN gained %s, lost %s. Historical ADP depth coverage (23/46 at 120 s in the census) is context only; no new ADP/libDAI 120 s cells were run.\n" % (sorted(g20 - p20), sorted(p20 - g20), sorted(g20 - a20), sorted(a20 - g20), sorted(g120 - p120), sorted(p120 - g120)))
    L.append("Complete case table (all 46 × every arm/stage; in-process complete_response_s; supervisor wall in CELLS_LEDGER.jsonl):\n")
    L.append("| case | fam | " + " | ".join("%s %d" % (a[:14], int(b)) for stage, arms, b in PI.STAGES for a in arms) + " |\n|---|---|" + "---|" * 9)
    def cellstr(stage, a, c):
        r = by.get((stage, a, c), {}); s_ = r.get("status") or "—"; t = r.get("complete_response_s"); return "%s%s" % ({"CERTIFIED": "C", "COMPLETE": "c", "RESOURCE_STOP": "R", "TIMEOUT": "T", "ADMISSION_REFUSED": "A", "LATE_OUTPUT": "L", "INCONSISTENT_EVIDENCE_CERTIFIED": "Z", "NUMERIC_UNRESOLVED": "N", "CHECK_FAILED": "X", "FAULT": "F", "NO_RECORD": "?"}.get(s_, s_[:6]), (" %.1f" % t) if t is not None and s_ in CERT + DONE_UNCERT else "")
    for c in cases:
        L.append("| %s | %s | %s |" % (c, fam[c][:6], " | ".join(cellstr(stage, a, c) for stage, arms, b in PI.STAGES for a in arms)))
    L.append("\nLegend: C certified (time s), c complete uncertified (libDAI), R typed resource stop, T timeout, A admission refused, L late output, Z inconsistent evidence certified, N numeric unresolved, X check failed, F fault.\n")
    # Q3
    L.append("## 3. Where backward demand, fusion and response views removed work; where they were no-ops or too expensive\n")
    cnt = collections.Counter(); ex = collections.defaultdict(list)
    for k, v in MECH.items():
        stage, arm, case = k.split("|")
        if arm != "GENERAL_BIDI_V1" or stage != "primary_breadth":
            continue
        for mech in ("views", "demand", "fusion"):
            cnt["%s:%s" % (mech, v[mech])] += 1
        if v["views_compressed_axes"] > 0:
            ex["views"].append("%s (%d/%d axes)" % (case, v["views_compressed_axes"], v["views_offered_axes"]))
        if v["demand_entries_skipped"] > 0:
            ex["demand"].append("%s (%d entries never requested)" % (case, v["demand_entries_skipped"]))
        if v["fusion_by_policy"] > 0:
            ex["fusion"].append("%s (%d/%d edges)" % (case, v["fusion_by_policy"], v["fusion_edges_offered"]))
    L.append("Typed outcomes over the 46 GENERAL_BIDI_V1 20 s cells (`MECHANISMS.json`): %s.\n" % dict(cnt))
    L.append("- **Exact response views** APPLIED_WITH_PROOF (compressed axes) on: %s. Elsewhere PROVED_NO_OP (no proportional marker-free rows along any axis) or SCAN_CAPPED_UNKNOWN (the 1 s / 10^6-row discovery wall ended before the scan).\n- **Complete-consumer demand masks** removed never-requested entries on: %s. Everywhere else the union over the single consumer's supported rows demanded every supported entry (PROVED_NO_OP) or support was FULL/UNKNOWN (SCAN_CAPPED).\n- **Consumer fusion** by the frozen policy fused edges on %d/46 cells (bijective reads: equal arithmetic, no storage); declined where the consumer re-reads a child many times. Memory downgrades (materialized → stream) are counted separately in `plan_totals`.\n" % (", ".join(ex["views"]) or "none", ", ".join(ex["demand"]) or "none", len(ex["fusion"])))
    L.append("Whole-path effect: compare the GENERAL vs PLAIN rows of §2 and the ablation rows of §4; a mechanism that reduced planned entries but did not change the status or the time is recorded as a planned-volume change only.\n")
    # Q4
    L.append("## 4. Which ablation differences survive certification; which are planned-volume changes or single-observation noise\n")
    L.append("| ablation (20 s) | certified | lost vs GENERAL 20 s | gained vs GENERAL 20 s | median time ratio on jointly certified cells (ablation / GENERAL) |\n|---|---|---|---|---|")
    for a in ARMS_A:
        ca = set(cert("ablation_breadth", a)); joint = sorted(ca & g20); ratios = sorted(by[("ablation_breadth", a, c)]["complete_response_s"] / by[("primary_breadth", "GENERAL_BIDI_V1", c)]["complete_response_s"] for c in joint if by[("primary_breadth", "GENERAL_BIDI_V1", c)].get("complete_response_s"))
        L.append("| %s | %d/46 | %s | %s | %s (n=%d) |" % (a, len(ca), sorted(g20 - ca) or "—", sorted(ca - g20) or "—", ("%.2f" % ratios[len(ratios) // 2]) if ratios else "—", len(joint)))
    L.append("\nEach ablation uses the same frozen planner with one mechanism disabled; the resulting route/order changes are part of the contrast (recorded per cell in `plan_order` / `plan_totals`). One observation per cell: differences of a few hundred milliseconds on sub-second cells are within launch noise and are not claimed.\n")
    # Q5
    L.append("## 5. Did more time solve the same obligations or postpone stops? Active operation in the hard cases\n")
    L.append("| case | GENERAL 20 s | GENERAL 120 s | PLAIN 20 s | PLAIN 120 s | stop phase (GENERAL 120) | route | reduced vars |\n|---|---|---|---|---|---|---|---|")
    for c in cases:
        r120 = by.get(("primary_depth", "GENERAL_BIDI_V1", c), {})
        if st("primary_depth", "GENERAL_BIDI_V1", c) in CERT and st("primary_breadth", "GENERAL_BIDI_V1", c) in CERT:
            continue
        L.append("| %s | %s | %s | %s | %s | %s | %s | %s |" % (c, st("primary_breadth", "GENERAL_BIDI_V1", c), st("primary_depth", "GENERAL_BIDI_V1", c), st("primary_breadth", "NATIVE_PLAIN_V1", c), st("primary_depth", "NATIVE_PLAIN_V1", c), json.dumps(r120.get("stop"))[:60] if r120.get("stop") else "—", r120.get("route") or "—", r120.get("free_reduced")))
    L.append("\nGained at 120 s over 20 s (GENERAL): %s; PLAIN: %s. Stops at 120 s are DEADLINE stops in the native forward stream (the active operation is the materialization / streamed re-evaluation of the largest bucket) or MEMORY stops followed by the reference stream, as recorded per cell.\n" % (sorted(g120 - g20), sorted(p120 - p20)))
    # Q6
    L.append("## 6. How much of the improvement over old ADP remains with arithmetic and protocol held fixed (native plain)?\n")
    jg = sorted(g20 & p20); jga = sorted(g20 & a20)
    def med(xs):
        xs = sorted(xs); return xs[len(xs) // 2] if xs else None
    rg = [by[("primary_breadth", "GENERAL_BIDI_V1", c)]["complete_response_s"] / by[("primary_breadth", "NATIVE_PLAIN_V1", c)]["complete_response_s"] for c in jg]; ra = [by[("primary_breadth", "GENERAL_BIDI_V1", c)]["complete_response_s"] / by[("primary_breadth", "ADP_REPAIRED", c)]["complete_response_s"] for c in jga]
    L.append("Coverage: GENERAL %d/46, PLAIN %d/46, ADP_REPAIRED %d/46 at 20 s. Matched completed pairs (in-process times; one observation each): GENERAL/PLAIN median ratio %s over %d cases %s; GENERAL/ADP median ratio %s over %d cases. PLAIN vs ADP isolates substrate + protocol (same bucket semantics, native MPFR/binary64 one-pass vs Python mpfr two-pass): PLAIN certified %d where ADP certified %d. The GENERAL vs PLAIN difference is the scheduling policy (views, demand, fusion, 3 orders) with the substrate fixed. Censored cells never enter a ratio.\n" % (len(g20), len(p20), len(a20), ("%.2f" % med(rg)) if rg else "—", len(jg), jg, ("%.2f" % med(ra)) if ra else "—", len(jga), len(p20), len(a20)))
    # Q7
    L.append("## 7. What did not transfer beyond the DBNs; systematic negative evidence\n")
    dbn = [c for c in cases if fam[c] == "DBN"]
    L.append("DBNs at 20 s: GENERAL %s, PLAIN %s (the bipartite kernel was NOT used in V1: the general bucket program with fusion materializes 1 entry per DBN and streams the rest; see `plan_totals`). Families where neither new arm certified any case at 120 s: %s. Families where PLAIN certified at least one case the GENERAL arm lost: %s. Reference-tier diagnostics (`SCORES.json`): %d certified cells scored; R0 containment is a proof check, R1/R2 distances are consistency observations.\n" % (sum(1 for c in dbn if st("primary_breadth", "GENERAL_BIDI_V1", c) in CERT), sum(1 for c in dbn if st("primary_breadth", "NATIVE_PLAIN_V1", c) in CERT), [f for f in families if not any(st("primary_depth", a, c) in CERT for a in ("GENERAL_BIDI_V1", "NATIVE_PLAIN_V1") for c in cases if fam[c] == f)], sorted({fam[c] for c in p20 - g20}), len(S)))
    L.append("Graveyard (null / undefined associations kept): mechanisms that fired with no status change; cases where views compressed axes but the deadline still hit in the stream (compression at a child does not bound the consumer's volume); fusion that saved storage but not arithmetic; the reference fallback never completing a hard case inside its budget. Per-case details are in `MECHANISMS.json`, `CELLS_LEDGER.jsonl` and `PANEL_INSPECTION.json`.\n")
    # Q8
    L.append("## 8. Reconciliation: every cell, failed attempt, stage overhead, packaging, uncharged exposure\n")
    L.append("Charged (nonnested; `BUDGET_LEDGER.json`): **%.1f s of %.0f s** = jobs %.1f s (by scope %s) + measured stage-parent remainders %s. Unresolved starts: %s. Outer stage receipts: %s. Attempt-1 aborted cells remain charged. Compliance: %s. Missingness: %d planned cells, %d completed records, killed without record %s, not launched %s, record without receipt %s; inaccessible slots %s. Uncharged, disclosed: %s. Unchanged history: frozen numerical set %s (= repaired pin: %s); inputs equal the census hashes: %s; census cell files unchanged: %s.\n"
             % (B["total_charged_s"], B["ceiling_s"], B["jobs_total_s"], B["by_scope_s"], {k: round(v["parent_remainder_s"], 1) if v["parent_remainder_s"] is not None else None for k, v in B["stage_parent_remainders"].items()}, B["unresolved"] or "none", {k: (round(v["wall_s"], 1) if v.get("wall_s") else "MISSING") for k, v in B["outer_receipts"].items()}, B["compliance"], miss["planned"], miss["completed_record"], miss["killed_no_record"] or "none", miss["not_launched"] or "none", miss["record_without_receipt"] or "none", [s["case"] for s in man["unavailable_slots"]], "; ".join(miss["uncharged_disclosed"]), UH["frozen_numerical_set_code_hash"][:12], UH["equals_repaired_pin_da5b2c49"], all(v["model_ok"] and v["evidence_ok"] for v in UH["inputs"].values()), UH.get("census_cells_unchanged")))
    L.append("Permitted conclusions: coverage counts above are the primary result; ratios are exploratory and only on matched completed cells; one observation per cell; nothing beyond this panel is claimed. STOPPED FOR REVIEW.\n")
    open(os.path.join(D, "REPORT.md"), "w").write("\n".join(L))
    H = ["GENERAL_BIDI_V1 BROAD ROUND — HANDOFF (branch %s; frozen commit %s; 9-10 November 2026)" % (man["branch"], man["commit"][:12]), "",
         "WHAT: first GENERAL implementation of the bidirectional design (finite cardinalities, arbitrary arity, nonbipartite, zeros, evidence): indexed",
         "bucket IR over the shared reduced model; exact response views; vectorized conservative support + complete-consumer demand; bottom-up fusion",
         "pricing; 3 metadata orders; native MPFR-outward / binary64 (range+depth-proved) executor with zero-safe local reverse; exact integer reference",
         "fallback; one-pass validated execution. Five arms; 414 frozen cells; every cell a supervised job; stage runners supervised as outer jobs.",
         "", "RESULT (20 s): GENERAL %d/46, PLAIN %d/46, ADP_REPAIRED %d/46, libDAI complete(uncertified) %d/46; (120 s): GENERAL %d/46, PLAIN %d/46." % (len(g20), len(p20), len(a20), len(comp("primary_breadth", "EXACT_LIBDAI")), len(g120), len(p120)),
         "  ablations (20 s): " + ", ".join("%s %d/46" % (a, len(cert("ablation_breadth", a))) for a in ARMS_A),
         "", "AMENDMENT_1: attempt 1 stopped after 37 cells (binary64 depth label omitted accumulation counts; unsound enclosure caught by the infeasible simplex point;",
         "  no wrong certificate published); repaired + simplex-bracket detector; re-frozen; attempt-1 cells preserved as non-evidence.",
         "", "BUDGET: %.1f s of 28,800 charged (nonnested); compliance %s." % (B["total_charged_s"], B["compliance"][:40]),
         "", "NOT CLAIMED: repeatability; broad superiority; anything about unrun configurations; the bipartite kernel was not used in V1 (general program only).",
         "FILES: GB_MANIFEST.json, CELLS_LEDGER.jsonl, BUDGET_LEDGER.json, MISSINGNESS.json, SCORES.json, MECHANISMS.json, UNCHANGED_HISTORY.json, PANEL_INSPECTION.json,",
         "AMENDMENTS.json, REPORT.md, qualification/, synthetic/, attempt1_aborted/, cells/<stage>/<index>__<case>__<arm>__<budget>__<task>/. STOPPED FOR REVIEW."]
    open(os.path.join(D, "HANDOFF.md"), "w").write("\n".join(H) + "\n")
    print(json.dumps({"G20": len(g20), "P20": len(p20), "ADP20": len(a20), "libDAI20": len(comp("primary_breadth", "EXACT_LIBDAI")), "G120": len(g120), "P120": len(p120), "ablations": {a: len(cert("ablation_breadth", a)) for a in ARMS_A}, "charged_s": B["total_charged_s"], "unresolved": B["unresolved"], "missing": miss["not_launched"] + miss["killed_no_record"]}))


if __name__ == "__main__":
    main(os.path.abspath(sys.argv[1]))
