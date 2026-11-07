"""Scorer for the external sweep (campaign spec section 8). Runs AFTER the primary stages. Reads every cell row + saved outputs, assembles
references (R0 exact-rational VE jobs under references/, R1 = the EXACT arm's own completed output or an exact-by-i-bound WMB output,
R2 = official UAI 2014 solution vectors (.MAR from MAR_sol.tar.gz; source does not document exactness), R3 = none), scores point vectors
against the best available reference per case, and writes SCORES.json. Interval-valued references (R0 enclosures from MDI / CBI certificates)
are scored with the lower / upper error bounds of the spec, never by their midpoint."""
from __future__ import annotations
import os, sys, json, math, hashlib, collections
HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__))); sys.path.insert(0, HERE)
sys.set_int_max_str_digits(0)
from fractions import Fraction as Fr
from ext import uai as U

ARMS = ["CBI_NATIVE", "MDI_EXISTING", "LBP", "WMB", "IJGP", "SAMPLESEARCH", "EXACT", "PGMAX_SUMPRODUCT_BP"]
HEUR = {"LBP", "WMB", "IJGP", "SAMPLESEARCH", "PGMAX_SUMPRODUCT_BP"}
R1_DECIMALS_LIBDAI = 10      # libdai driver prints setprecision(10): rounding enclosure half-width 0.5e-9 (documented by the driver)
R2_DECIMALS = 6              # official .MAR files print 6 significant digits of each probability; ONLY used as a documented print precision


def read_points(path):
    rows, raw = U.read_mar(path); return [[Fr(x) for x in r] for r in rows]


def hellinger(p, q):
    return math.sqrt(0.5 * sum((math.sqrt(float(a)) - math.sqrt(float(b))) ** 2 for a, b in zip(p, q)))


def score_points_vs_enclosure(points, ref_rows, card, ev):
    """points: list of rows (Fr); ref_rows: per var list of [L, U] (Fr) per state (R0 may be a genuine enclosure; R1 / R2 are points, L = U).
    Returns lower / upper bounds on max abs error (equal for point references), per-variable TV and Hellinger at the reference point."""
    lo_err = Fr(0); hi_err = Fr(0); tv_mid = []; hel_mid = []; nvars = 0; ncoord = 0; halfw = Fr(0)
    for v, row in enumerate(points):
        if v in ev or ref_rows[v] is None:
            continue
        nvars += 1; mid = []
        for s, q in enumerate(row):
            L, Uu = ref_rows[v][s]; ncoord += 1
            lo_err = max(lo_err, max(L - q, q - Uu, Fr(0))); hi_err = max(hi_err, max(abs(q - L), abs(q - Uu))); halfw = max(halfw, (Uu - L) / 2); mid.append((L + Uu) / 2)
        tv_mid.append(float(sum(abs(a - b) for a, b in zip(row, mid)) / 2)); hel_mid.append(hellinger(row, mid))
    return {"max_abs_error_lower": float(lo_err), "max_abs_error_upper": float(hi_err), "reference_half_width_max": float(halfw), "variables": nvars, "coordinates": ncoord,
            "tv_mean_at_ref_midpoint": (sum(tv_mid) / len(tv_mid) if tv_mid else None), "tv_max_at_ref_midpoint": (max(tv_mid) if tv_mid else None),
            "hellinger_mean_at_ref_midpoint": (sum(hel_mid) / len(hel_mid) if hel_mid else None), "hellinger_max_at_ref_midpoint": (max(hel_mid) if hel_mid else None),
            "target_0.005": ("met" if hi_err <= Fr(1, 200) else ("missed" if lo_err > Fr(1, 200) else "unresolved"))}


def enclosure_from_points(rows, decimals=None):
    """A floating-point / printed reference vector is used AS THE POINT (zero-width box). No uncertainty interval is inferred from printed
    digits (amendment 5 of the external sweep: the earlier half-ulp boxes were not a documented reference error rule). Distances to such a
    reference are approximate-reference numerical comparisons, never rigorous error claims."""
    return [[[x, x] for x in r] for r in rows]


def enclosure_from_official(path):
    """official UAI 2014 .MAR solution vector (6 significant digits, provenance undocumented) -> POINT reference (zero width)."""
    rows, _ = U.read_mar(path)
    return [[[Fr(x), Fr(x)] for x in r] for r in rows]


def main(S):
    man = json.load(open(os.path.join(S, "CAMPAIGN_MANIFEST.json"))); rows = [json.loads(l) for l in open(os.path.join(S, "CELLS_LEDGER.jsonl"))]
    inv = {c["case"]: c for c in json.load(open(os.path.join(S, "INVENTORY.json")))["cases"]}
    cells = {(r["case"], r["arm"], r["stage"], r.get("label")): r for r in rows}
    # ---- references
    refs = {}; refdir = os.path.join(S, "references"); official = os.path.join(S, "sources", "uai14", "sol")
    for case, row in inv.items():
        if case not in {c["case"] for c in man["cells"]}:
            continue
        mp = os.path.join(S, row.get("committed_model_path", row["model_path"])); ep = os.path.join(S, row.get("committed_evidence_path", row["evidence_path"]))
        m = U.read_model(mp); ev = U.read_evidence(ep); card = m.card
        cands = []
        r0 = os.path.join(refdir, case + ".R0.json")
        if os.path.exists(r0):
            d = json.load(open(r0))
            if d.get("status") == "R0":
                cands.append(("R0", "exact rational VE (bench/ref_exact.py; brute-force cross-check on tiny models)", [[[Fr(x), Fr(x)] for x in d["marginals"][str(v)]] if str(v) in d["marginals"] else None for v in range(m.nvars)]))
        # R1: EXACT arm complete outputs (depth first, then breadth), or an exact-by-ibound WMB / IJGP output
        for stage in ("depth", "breadth"):
            c = cells.get((case, "EXACT", stage, None))
            if c and c.get("status") == "COMPLETE" and not c.get("censored"):
                cands.append(("R1", "libDAI junction tree (exact algorithm in binary64, printed to 10 significant digits; used as a POINT reference, no enclosure; stage %s)" % stage, enclosure_from_points(read_points(os.path.join(S, c["out_dir"], "output.MAR")), R1_DECIMALS_LIBDAI))); break
        for arm in ("WMB", "IJGP"):
            for stage in ("depth", "breadth"):
                c = cells.get((case, arm, stage, None))
                if c and c.get("status") == "COMPLETE" and not c.get("censored"):
                    cj = json.load(open(os.path.join(S, c["out_dir"], "cell.json")))
                    if cj.get("exact_by_ibound"):
                        cands.append(("R1", "Merlin %s with i-bound >= induced width (exact elimination in binary64, printed to 6 decimals; POINT reference)" % arm, enclosure_from_points(read_points(os.path.join(S, c["out_dir"], "output.MAR")), 6)))
        op = os.path.join(official, case + ".uai.MAR")
        if os.path.exists(op) and row["archive"] == "uai2022_tuning":
            try:
                cands.append(("R2", "official UAI 2014 MAR solution file (6 significant digits; provenance undocumented; POINT reference)", enclosure_from_official(op)))
            except Exception as ex:
                pass
        order = {"R0": 0, "R1": 1, "R2": 2}; cands.sort(key=lambda c: order[c[0]])
        refs[case] = {"class": cands[0][0] if cands else "R3", "source": cands[0][1] if cands else "no qualified reference", "rows": cands[0][2] if cands else None, "all_candidates": [(c[0], c[1]) for c in cands], "card": card, "ev": ev}
        # consistency between independent rigorous / exact references: overlapping boxes
        if len(cands) >= 2:
            a, b = cands[0][2], cands[1][2]; dmax = Fr(0); disjoint = 0
            for v in range(m.nvars):
                if a[v] is None or b[v] is None or v in ev:
                    continue
                for s in range(card[v]):
                    if a[v][s][1] < b[v][s][0] or b[v][s][1] < a[v][s][0]:
                        disjoint += 1
                    dmax = max(dmax, abs((a[v][s][0] + a[v][s][1]) / 2 - (b[v][s][0] + b[v][s][1]) / 2))
            refs[case]["cross_reference_pair"] = (cands[0][0], cands[1][0]); refs[case]["cross_reference_sources"] = (cands[0][1][:60], cands[1][1][:60])
            refs[case]["cross_reference_max_coordinate_distance"] = float(dmax); refs[case]["cross_reference_disjoint_coordinates"] = disjoint if cands[0][0] == "R0" else None
    # ---- per cell scoring
    scored = []; reclass = []
    for r in rows:
        case = r["case"]; ref = refs.get(case); out = dict(r); out.pop("snapshots", None)
        # RECLASSIFICATION (reporting only; original retained): the MDI wrapper mapped the engine outcome NUMERICAL_REFUSAL to CHECK_FAILED, but
        # the engine's reason for these cells is an ADMISSION refusal of its exact preprocessing (a factor above the locally-verifiable cap),
        # not a failed numerical check of a produced answer
        if r["arm"] == "MDI_EXISTING" and r.get("status") == "CHECK_FAILED" and r.get("out_dir"):
            cj = os.path.join(S, r["out_dir"], "cell.json"); d = json.load(open(cj)) if os.path.exists(cj) else {}
            if d.get("mdi_outcome") == "NUMERICAL_REFUSAL" and "REFUSED" in str(d.get("reason", "")):
                out["status_original"] = "CHECK_FAILED"; out["status"] = "ENGINE_REFUSED_PREPROCESSING"; out["failure_primary"] = "engine admission: exact preprocessing not locally verifiable above the declared cap"; reclass.append(r["cell_id"])
        od = os.path.join(S, r["out_dir"]) if r.get("out_dir") else None; mar = os.path.join(od, "output.MAR") if od else None
        out["reference_class"] = ref["class"] if ref else "R3"
        if mar and os.path.exists(mar) and r.get("status") in ("CERTIFIED", "VALID_BUT_TOO_WIDE", "COMPLETE", "COMPLETE_UNCONVERGED") and not r.get("censored"):
            pts = read_points(mar); card = ref["card"]; ev = ref["ev"]
            ok = len(pts) == len(card) and all(len(p) == card[v] for v, p in enumerate(pts)) and all(abs(float(sum(p)) - 1) <= 1e-5 * max(1, card[v]) for v, p in enumerate(pts))
            out["output_valid"] = ok; out["full_coverage"] = ok
            if ok and ref["rows"] is not None:
                out["accuracy"] = score_points_vs_enclosure(pts, ref["rows"], card, ev)
            else:
                out["accuracy"] = None; out["point_quality"] = "UNKNOWN (no qualified reference)" if ref["rows"] is None else "INVALID_OUTPUT"
            # snapshot accuracy (retrospective time-to-error): score every emitted snapshot
            snaps = {}
            for f in sorted(os.listdir(od)):
                if f.startswith("snapshot_") and f.endswith(".MAR") and ref["rows"] is not None:
                    try:
                        sp = read_points(os.path.join(od, f)); snaps[f[len("snapshot_"):-4]] = score_points_vs_enclosure(sp, ref["rows"], card, ev)["max_abs_error_upper"]
                    except Exception:
                        snaps[f[len("snapshot_"):-4]] = "invalid"
            out["snapshot_max_abs_error_upper"] = snaps
        elif mar and os.path.exists(mar) and r.get("outcome") in ("MEMORY_KILL", "TIMEOUT_KILL") and ref is not None:
            # the supervisor killed the cell AFTER an earlier ladder step had atomically published a complete output: scored SEPARATELY as a
            # retained-before-kill output (time to that output unknown; the cell itself stays censored / killed)
            pts = read_points(mar); card = ref["card"]; ev = ref["ev"]
            ok = len(pts) == len(card) and all(len(p) == card[v] for v, p in enumerate(pts)) and all(abs(float(sum(p)) - 1) <= 1e-5 * max(1, card[v]) for v, p in enumerate(pts))
            out["output_valid"] = False; out["retained_output_before_kill"] = {"valid": ok, "accuracy": (score_points_vs_enclosure(pts, ref["rows"], card, ev) if ok and ref["rows"] is not None else None), "note": "not a completed cell; time-to-output unknown"}; out["accuracy"] = None
        else:
            out["output_valid"] = False; out["accuracy"] = None
        if r["arm"] == "PGMAX_SUMPRODUCT_BP" and r.get("status") == "INVALID_OUTPUT":
            out["failure_primary"] = "PGMax marginals not normalized on 81-state variables (rows of 0/1 entries summing to the state count): solver-side numerical failure with excluded zero configurations; output rejected, not clipped"
        if r["arm"] == "MDI_EXISTING" and r.get("out_dir"):
            ap = os.path.join(S, r["out_dir"], "arm_case_selector.json")
            if os.path.exists(ap):
                try:
                    a = json.load(open(ap)); pl = (a.get("pipeline") or {}).get("plan") or {}
                    out["mdi_route"] = {"chosen": pl.get("chosen"), "executed_kind": pl.get("executed_kind"), "route_policy": pl.get("route_policy"), "selector": (str(pl.get("selector"))[:300] if pl.get("selector") is not None else None),
                                        "outcome": a.get("outcome"), "free_vars": a.get("free_vars"), "requested_coordinates": a.get("queries"), "peak_rss_bytes_arm": a.get("peak_rss_bytes")}
                except Exception as ex:
                    out["mdi_route"] = {"error": str(ex)[:120]}
        out["certification_track"] = ("NOT_OFFERED" if r["arm"] in HEUR or r["arm"] == "EXACT" else ("CERTIFIED_WIDTH_MET" if r.get("status") == "CERTIFIED" else ("CERTIFIED_TOO_WIDE" if r.get("status") == "VALID_BUT_TOO_WIDE" else "NONE")))
        scored.append(out)
    # ---- aggregates: applicability by family x arm (breadth), service track, accuracy track
    def agg(stage):
        A = collections.defaultdict(lambda: collections.Counter())
        for r in scored:
            if r["stage"] != stage or r.get("label") is not None:
                continue
            A[(r["family"], r["arm"])][r["status"]] += 1
        return {"%s|%s" % k: dict(v) for k, v in A.items()}
    fam_cases = collections.Counter(c["family"] for c in man["cells"] if c["stage"] == "breadth" and c["arm"] == ARMS[0])
    service = {}
    for r in scored:
        if r.get("label") is not None:
            continue
        if r["arm"] in ("CBI_NATIVE", "MDI_EXISTING"):
            service.setdefault(r["arm"], collections.Counter())[(r["stage"], r["status"])] += 1
    summary = {"frozen_commit": man["commit"], "cases": man["counts"], "arms": ARMS, "unavailable": man["unavailable_arms"],
               "applicability_breadth": agg("breadth"), "applicability_depth": agg("depth"), "family_case_counts": dict(fam_cases),
               "service_track": {k: {"%s|%s" % kk: vv for kk, vv in v.items()} for k, v in service.items()},
               "reference_classes": {c: {"class": v["class"], "source": v["source"], "candidates": v["all_candidates"], "cross_reference_disjoint_coordinates": v.get("cross_reference_disjoint_coordinates"), "cross_reference_pair": v.get("cross_reference_pair"), "cross_reference_sources": v.get("cross_reference_sources"), "cross_reference_max_coordinate_distance": v.get("cross_reference_max_coordinate_distance")} for c, v in refs.items()},
               "reclassified_cells": reclass, "reclassification_note": "MDI_EXISTING cells whose engine outcome was NUMERICAL_REFUSAL with an explicit preprocessing-admission REFUSED reason are reported as ENGINE_REFUSED_PREPROCESSING (wrapper status CHECK_FAILED retained in status_original)",
               "cells": scored}
    json.dump(summary, open(os.path.join(S, "SCORES.json"), "w"), indent=1, default=str)
    print("scored", len(scored), "rows; reference classes:", collections.Counter(v["class"] for v in refs.values()))


if __name__ == "__main__":
    main(os.path.abspath(sys.argv[1]))
