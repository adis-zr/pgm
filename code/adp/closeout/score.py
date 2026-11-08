"""Scoring of the AGGREGATE_DP_2026-11-07 campaign (runs AFTER the stages): per-cell records with availability / completion /
certified-target / empirical-target / timing kept SEPARATE; references assembled per case with their class and independence:
  R0  exact rational VE references of the historical sweep (references/*.R0.json; brute-force cross-checked on tiny models)
  R1  an EXACT (libDAI junction tree, binary64) complete output -- historical sweep or THIS campaign's EXACT cells (points; a
      new R1 from the same arm cannot validate that arm); Merlin exact-by-i-bound outputs
  R2  official UAI 2014 .MAR solution files (points; provenance undocumented)
  R3  none. References are POINTS unless a certified interval was supplied (R0 is exact). Missing reference = UNKNOWN accuracy.
AGGREGATE_DP_V1 and its ablations: certification comes from the independent checker (status CERTIFIED = width <= 1/100 AND
robust-center point verified from the delivered decimals); the empirical point error against a reference is reported separately
and is NOT a certificate. Baselines keep their native guarantee (none rigorous).
    python adp/closeout/score.py D   -> D/SCORES.json, D/RECORDS_cells.jsonl, D/MISSINGNESS.json"""
from __future__ import annotations
import os, sys, json, math, collections
sys.set_int_max_str_digits(0)
HERE = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))); sys.path.insert(0, HERE)
from fractions import Fraction as Fr
from ext import uai as U
OLD = os.path.join(HERE, "runs", "mdi_2026-10-28", "EXTERNAL_SWEEP_2026-11-06")
NEW_ARM = "AGGREGATE_DP_V1"


def read_points(path):
    rows, _ = U.read_mar(path); return [[Fr(x) for x in r] for r in rows]


def point_error(points, ref_rows, ev):
    """max |p - ref| over unobserved coordinates (point reference) and per-variable TV at the reference."""
    err = Fr(0); tv = []; n = 0
    for v, row in enumerate(points):
        if v in ev or ref_rows[v] is None:
            continue
        n += 1; tv.append(float(sum(abs(a - b) for a, b in zip(row, ref_rows[v])) / 2))
        for q, r in zip(row, ref_rows[v]):
            err = max(err, abs(q - r))
    return {"max_abs_error": float(err), "variables": n, "tv_mean": (sum(tv) / len(tv) if tv else None), "tv_max": (max(tv) if tv else None), "target_0.005": "met" if err <= Fr(1, 200) else "missed"}


def interval_containment(intervals, ref_rows, ev):
    """for a CERTIFIED new-arm output: does the (exact R0 / point R1 / R2) reference lie inside every published interval? (R0: a proof check;
    R1 / R2: a consistency observation only, since those references carry their own unknown rounding)."""
    out = 0; total = 0; worst = Fr(0)
    for v, row in enumerate(intervals):
        if v in ev or ref_rows[v] is None:
            continue
        for s, (L, Uu) in enumerate(row):
            total += 1; r = ref_rows[v][s]
            if L <= r <= Uu:
                out += 1
            else:
                worst = max(worst, max(L - r, r - Uu))
    return {"coordinates": total, "contained": out, "max_excursion": float(worst)}


def references(D, man, rows):
    refs = {}; inv = {c["case"]: c for c in json.load(open(os.path.join(OLD, "INVENTORY.json")))["cases"]}
    old_rows = [json.loads(l) for l in open(os.path.join(OLD, "CELLS_LEDGER.jsonl"))]
    for c in man["cases"]:
        case = c["case"]; m = U.read_model(os.path.join(HERE, c["model_path"])); ev = U.read_evidence(os.path.join(HERE, c["evidence_path"])); cands = []
        r0 = os.path.join(OLD, "references", case + ".R0.json")
        if os.path.exists(r0):
            d = json.load(open(r0))
            if d.get("status") == "R0":
                cands.append(("R0", "exact rational VE (historical sweep bench/ref_exact.py; brute-force cross-check on tiny models)", [[Fr(x) for x in d["marginals"][str(v)]] if str(v) in d["marginals"] else None for v in range(m.nvars)], "independent of every arm"))
        for stage in ("depth", "breadth"):
            hits = [r for r in old_rows if r["case"] == case and r["arm"] == "EXACT" and r["stage"] == stage and r.get("label") is None and r.get("status") == "COMPLETE" and not r.get("censored")]
            if hits:
                cands.append(("R1", "historical libDAI junction tree output (exact algorithm, binary64, 10 significant digits; POINT; sweep %s stage)" % stage, read_points(os.path.join(OLD, hits[0]["out_dir"], "output.MAR")), "same engine as the EXACT arm: not independent for EXACT")); break
        for r in rows:
            if r["case"] == case and r["arm"] == "EXACT" and r.get("status") == "COMPLETE" and not r.get("censored"):
                cands.append(("R1", "THIS campaign's libDAI junction tree output (stage %s; POINT)" % r["stage"], read_points(os.path.join(D, r["out_dir"], "output.MAR")), "same engine as the EXACT arm: validates only the other arms")); break
        for arm in ("WMB", "IJGP"):
            for r in old_rows + rows:
                if r["case"] == case and r["arm"] == arm and r.get("status") == "COMPLETE" and r.get("label") is None:
                    base = OLD if r in old_rows else D; cj = os.path.join(base, r["out_dir"], "cell.json")
                    if os.path.exists(cj) and json.load(open(cj)).get("exact_by_ibound"):
                        cands.append(("R1", "Merlin %s exact by i-bound (binary64, 6 decimals; POINT)" % arm, read_points(os.path.join(base, r["out_dir"], "output.MAR")), "independent engine of the new arm and of libDAI")); break
        op = os.path.join(OLD, "sources", "uai14", "sol", case + ".uai.MAR")
        if os.path.exists(op) and inv[case]["archive"] == "uai2022_tuning":
            try:
                cands.append(("R2", "official UAI 2014 MAR solution file (6 significant digits; provenance undocumented; POINT)", read_points(op), "independent of every arm; exactness undocumented"))
            except Exception:
                pass
        order = {"R0": 0, "R1": 1, "R2": 2}; cands.sort(key=lambda x: order[x[0]])
        refs[case] = {"class": cands[0][0] if cands else "R3", "source": cands[0][1] if cands else "no qualified reference", "independence": cands[0][3] if cands else None, "rows": cands[0][2] if cands else None, "candidates": [(x[0], x[1]) for x in cands], "card": list(m.card), "ev": ev, "nvars": m.nvars}
    return refs


def main(D):
    man = json.load(open(os.path.join(D, "CAMPAIGN_MANIFEST.json"))); rows = [json.loads(l) for l in open(os.path.join(D, "CELLS_LEDGER.jsonl"))] if os.path.exists(os.path.join(D, "CELLS_LEDGER.jsonl")) else []
    have = {r["cell_id"] for r in rows}; refs = references(D, man, rows); scored = []; missing = []
    for cell in man["cells"]:
        r = next((x for x in rows if x["cell_id"] == cell["cell_id"]), None)
        if r is None:
            missing.append({"cell_id": cell["cell_id"], "case": cell["case"], "arm": cell["arm"], "stage": cell["stage"], "config_key": cell["config_key"], "reason": "NOT_RUN (stage not executed or interrupted)"}); continue
        ref = refs[cell["case"]]; out = dict(r); out["reference_class"] = ref["class"]; out["reference_independence"] = ref["independence"]
        od = os.path.join(D, r["out_dir"]) if r.get("out_dir") else None; cj = json.load(open(os.path.join(od, "cell.json"))) if od and os.path.exists(os.path.join(od, "cell.json")) else {}
        out["available"] = r.get("status") != "UNAVAILABLE"; out["complete_output"] = bool(od and os.path.exists(os.path.join(od, "output.MAR")) and r.get("status") in ("CERTIFIED", "COMPLETE", "COMPLETE_UNCONVERGED", "VALID_BUT_TOO_WIDE") and not r.get("censored"))
        out["certified_target"] = (r.get("status") == "CERTIFIED") if (r["arm"] == NEW_ARM or r["arm"] == "MDI_EXISTING") else None   # the only arms offering a rigorous contract
        out["certificate_from"] = "independent checker (adp.checker, separate process; own parser / replay / point verification)" if r["arm"] == NEW_ARM else ("MDI independent checker" if r["arm"] == "MDI_EXISTING" else "none (native guarantee of the baseline)")
        if r["arm"] == NEW_ARM:
            out["adp"] = {"reductions": cj.get("reductions"), "program": cj.get("program"), "attempts": [{k: v for k, v in a.items() if k != "roots_producer_down"} for a in (cj.get("attempts") or [])], "checker": {k: (cj.get("checker") or {}).get(k) for k in ("status", "reason", "max_width_float", "wall_s", "phases_s", "counters", "maxrss_bytes")},
                          "publication": cj.get("publication"), "certified": cj.get("certified"), "stop": cj.get("stop"), "maxrss_self_bytes": cj.get("maxrss_self_bytes"), "maxrss_children_bytes": cj.get("maxrss_children_bytes"), "point_check": (cj.get("point_check") or {}).get("status")}
        if out["complete_output"] and ref["rows"] is not None:
            pts = read_points(os.path.join(od, "output.MAR")); out["empirical"] = point_error(pts, ref["rows"], ref["ev"])
            if r["arm"] == NEW_ARM and os.path.exists(os.path.join(od, "intervals.json")):
                iv = json.load(open(os.path.join(od, "intervals.json")))["intervals"]; out["reference_in_intervals"] = interval_containment([[(Fr(a), Fr(b)) for a, b in row["intervals"]] for row in iv], ref["rows"], ref["ev"])
        elif out["complete_output"]:
            out["empirical"] = None; out["empirical_note"] = "UNKNOWN accuracy (no qualified reference)"
        else:
            out["empirical"] = None
        scored.append(out)
    # missingness: typed
    types = collections.Counter()
    for r in scored:
        if r.get("status") == "UNAVAILABLE":
            types["unavailable_dependency"] += 1
        elif r.get("status") == "NOT_RUN_BUDGET":
            types["not_run_within_budget"] += 1
        elif r.get("outcome") in ("MEMORY_KILL", "TIMEOUT_KILL"):
            types["resource_censored_killed"] += 1
        elif not r.get("complete_output"):
            types["no_complete_output_typed_stop"] += 1
        elif r.get("empirical") is None:
            types["complete_output_unknown_accuracy_no_reference"] += 1
    agg = collections.defaultdict(collections.Counter)
    for r in scored:
        key = (r["stage"], r["arm"] if r["arm"] != NEW_ARM else r["config_key"]); agg[key][r["status"]] += 1
    summary = {"campaign": man["campaign"], "commit": man["commit"], "code_hash": man["code_hash"], "cells_planned": len(man["cells"]), "cells_recorded": len(scored), "cells_missing": len(missing),
               "status_by_stage_arm": {"%s|%s" % k: dict(v) for k, v in sorted(agg.items())}, "reference_classes": {c: {"class": v["class"], "source": v["source"], "independence": v["independence"], "candidates": v["candidates"]} for c, v in refs.items()},
               "reference_class_counts": dict(collections.Counter(v["class"] for v in refs.values())), "missingness_types": dict(types), "inaccessible_slots": man["inaccessible_slots"]}
    json.dump(summary, open(os.path.join(D, "SCORES.json"), "w"), indent=1, default=str)
    with open(os.path.join(D, "RECORDS_cells.jsonl"), "w") as f:
        for r in scored:
            f.write(json.dumps(r, default=str) + "\n")
    json.dump({"typed_missingness": dict(types), "unrun_cells": missing, "rule": "null is never zero: every planned cell has a row or a typed reason"}, open(os.path.join(D, "MISSINGNESS.json"), "w"), indent=1)
    print(json.dumps({k: summary[k] for k in ("cells_planned", "cells_recorded", "cells_missing", "reference_class_counts", "missingness_types")}))


if __name__ == "__main__":
    main(os.path.abspath(sys.argv[1]))
