"""Artifact-only scoring: per cell, every attempted route's artifact (selected runs, diagnostics, references) with: input hash, sizes,
P0, symmetry, h/k, scout result, Z_k / R_h and residual bounds, every published interval, max width, times, memory, max bits,
exact-reference containment (E on primaries; E and W on the small control), movement from the ignore-bridge marginals pi, F0 width
outcome, selector regret (selected complete time minus the fastest measured complete route on the cell). Writes SCORES.json."""
import os, sys, json, glob
from research.paths import runs_root
from fractions import Fraction as Fr
from pgm.algorithms.sf import core as C
E = str(runs_root() / "mdi_2026-10-28" / "SF_BRIDGE_2026-11-06")
led = json.load(open(os.path.join(E, "ALLOWANCE_LEDGER.json")))
charges = {c["artifact"]: c for c in led["charges"] if c.get("status") == "TERMINAL"}
Q = 1 << C.GRID_BITS


def load_cell(panel, r):
    d = os.path.join(E, "cells", panel, C.r_label(r).replace("/", "_").replace("^", "p"))
    arts = {}
    for f in sorted(glob.glob(os.path.join(d, "*.json"))):
        if os.path.basename(f).startswith("SEAL"):
            continue
        arts[os.path.basename(f)] = json.load(open(f))
    return d, arts


def exact_points(art):
    return [Fr(lo) for lo, hi in art["intervals_exact"]] if art.get("status") == "OK" and art["route_record"].get("exact") else None


cells = []
for r in C.R_PRIORITY:
    for p in ["small_control", "primary_A", "primary_B", "ordinary_control"]:
        d, arts = load_cell(p, r)
        refE = next((a for f, a in arts.items() if f.startswith("reference_E_rep0")), None)
        refW = next((a for f, a in arts.items() if f.startswith("reference_W_rep0")), None)
        truth = exact_points(refE) if refE else None
        truthW = exact_points(refW) if refW else None
        cell = {"panel": p, "r": str(r), "r_label": C.r_label(r), "reference_E_status": (refE or {}).get("status"), "reference_W_status": (refW or {}).get("status"),
                "E_W_agree": (truth == truthW) if (truth is not None and truthW is not None) else None, "routes": []}
        pi = None
        for f, a in arts.items():
            ch = charges.get(os.path.join(d, f)) or {}
            row = {"file": f, "kind": a.get("mode"), "eps": a.get("eps"), "rep": int(f.split("_rep")[-1].split(".")[0]) if "_rep" in f else 0, "route": a.get("route"), "params": a.get("params"), "status": a.get("status"), "reason": a.get("reason"),
                   "input_sha256": a.get("input_sha256"), "mA": a.get("mA"), "mB": a.get("mB"), "P0": (a.get("overlap") or {}).get("P0"), "intersection_rows": (a.get("overlap") or {}).get("intersection_rows"),
                   "symmetry": (a.get("symmetry") or {}).get("antipodal_A"), "scouts": (a.get("selection") or {}).get("scouts"), "qualified": (a.get("selection") or {}).get("qualified"), "proxies": (a.get("selection") or {}).get("proxies"),
                   "max_width": a.get("max_width"), "max_width_float": a.get("max_width_float"), "width_met": a.get("width_met"), "phases_s": a.get("phases_s"), "route_walls_s": a.get("route_walls_s"),
                   "child_wall_s": a.get("child_wall_s"), "producer_only_s": a.get("producer_only_s"), "complete_supervisor_wall_s": ch.get("charged_s"), "supervisor_outcome": (ch.get("supervisor") or {}).get("outcome"),
                   "peak_tree_rss_kib": (ch.get("supervisor") or {}).get("peak_tree_rss_kib"), "child_high_water_rss_bytes": a.get("child_high_water_rss_bytes"), "max_bits": a.get("max_bits"),
                   "checker": (a.get("checker") or {}).get("status"), "max_movement_bound_from_pi": a.get("max_movement_bound_from_pi")}
            rr = a.get("route_record") or {}
            for k in ("Zk_int", "R_int", "U_int", "P_int", "Z_int", "eta_Z", "eta_M", "Z_k", "radius", "rho", "pairs_retained", "N_k", "transforms", "rows_histogrammed", "symmetric_halving", "tails"):
                if k in rr:
                    row[k] = rr[k]
            if a.get("pi_plus"):
                pi = [Fr(x) for x in a["pi_plus"]]
            if truth is not None and a.get("status") == "OK":
                fails = 0; moved = []
                for i, (lg, hg) in enumerate(a["published"]):
                    if not (Fr(int(lg), Q) <= truth[i] <= Fr(int(hg), Q)):
                        fails += 1
                row["reference_containment_failures"] = fails; row["coordinates"] = len(a["published"])
            cell["routes"].append(row)
        if truth is not None and pi is not None:
            mv = [abs(truth[i] - pi[i]) for i in range(len(pi))]
            cell["movement"] = {"max_abs_shift_from_pi": str(max(mv)), "max_abs_shift_float": float(max(mv)), "coordinates_moved_more_than_half_width": {str(e): sum(1 for m in mv if m > e / 2) for e in C.WIDTHS},
                                "all_shifts_float": [float(m) for m in mv]}
        # F0 width outcome and selector regret
        f0 = next((x for x in cell["routes"] if x["route"] == "F0" and x["status"] == "OK"), None)
        cell["F0_width_met"] = (f0 or {}).get("width_met")
        # CORRECTED metric (the first scoring pass compared against the fastest verified route regardless of width; preserved as
        # SCORES_prior_regret_metric.json): the regret baseline is the fastest COMPLETE, VERIFIED route on the cell that MEETS the
        # requested width eps (any kind: selected, diagnostic or reference; rep 0 only)
        def fastest_meeting(eps):
            cand = [(x["complete_supervisor_wall_s"], x["route"], x["file"]) for x in cell["routes"] if x["status"] == "OK" and x["rep"] == 0 and x["complete_supervisor_wall_s"] is not None and x["checker"] == "VERIFIED" and (x.get("width_met") or {}).get(eps)]
            return min(cand) if cand else None
        cell["fastest_complete_verified_route_meeting_width"] = {e: ({"s": f_[0], "route": f_[1], "file": f_[2]} if f_ else None) for e, f_ in ((str(e), fastest_meeting(str(e))) for e in C.WIDTHS)}
        cell["selector"] = {}
        for x in cell["routes"]:
            if x["kind"] == "select" and x["rep"] == 0:
                fastest = fastest_meeting(x["eps"])
                cell["selector"][x["eps"]] = {"route": x["route"], "status": x["status"], "complete_s": x["complete_supervisor_wall_s"], "producer_only_s": x["producer_only_s"], "width_met": (x.get("width_met") or {}).get(x["eps"]),
                                             "regret_s": (x["complete_supervisor_wall_s"] - fastest[0]) if (fastest and x["complete_supervisor_wall_s"] is not None) else None,
                                             "fastest_route": fastest[1] if fastest else None,
                                             "diagnostics_passing_width_but_not_qualified": [y["route"] for y in cell["routes"] if y["kind"] == "route" and y["status"] == "OK" and (y.get("width_met") or {}).get(x["eps"]) and y["route"] not in (x.get("qualified") or []) and y["route"] not in ("E", "W")]}
        cells.append(cell)
alw = {"allowance_s": led["allowance_s"], "charged_s": sum(c["charged_s"] for c in led["charges"] if c.get("status") == "TERMINAL"), "children": sum(1 for c in led["charges"] if c.get("status") == "TERMINAL"),
       "unknown": led.get("unknown_charges"), "unattempted": led.get("unattempted"), "reused": len(led.get("reused", [])),
       "by_kind": {k: round(sum(c["charged_s"] for c in led["charges"] if c.get("status") == "TERMINAL" and c.get("kind") == k), 3) for k in ("control", "generation", "select", "diag", "reference")}}
json.dump({"cells": cells, "allowance": alw}, open(os.path.join(E, "SCORES.json"), "w"), indent=1, default=str)
print(json.dumps(alw, indent=1))
