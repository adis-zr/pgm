"""REPORT.md from SCORES.json (artifact-only)."""
import os, sys, json
from research.paths import runs_root
E = str(runs_root() / "mdi_2026-10-28" / "SF_BRIDGE_2026-11-06")
S = json.load(open(os.path.join(E, "SCORES.json"))); B = json.load(open(os.path.join(E, "BINDINGS.json"))); P = json.load(open(os.path.join(E, "inputs/PANELS.json")))
f = lambda x, nd=3: ("—" if x is None else (("%." + str(nd) + "f") % x if isinstance(x, float) else str(x)))
g = lambda x: ("—" if x is None else "%.3g" % x)
L = ["# Adaptive sparse / Fourier inference on the coupled-block family — frozen pass (6 November 2026)\n",
     "Branch `sf-bridge-2026-11-06`; pre-launch commit %s; theory: the overseer's Part A (6 Nov 2026). Contract, manifest, generator, inputs and code frozen before any outcome; each cell's candidate artifacts sealed before its references ran.\n" % B.get("commit_before_launch", "?")[:12]]
L.append("## Panels\n\n| panel | n | m_A = m_B | kind | p | seed | A∩B rows | sha256 |\n|---|---|---|---|---|---|---|---|")
for k, v in P["panels"].items():
    L.append("| %s | %d | %d | %s | %s | %d | %d | %s… |" % (k, v["n"], v["m"], v["kind"], v["p"], v["seed"], v["intersection"], v["sha256"][:16]))
L.append("\n## Selected runs (online selector; complete = supervised child spawn-to-exit wall, incl. parse, recognition, overlap scan, scouts, route, certificate, independent checker, publication)\n")
L.append("| panel | r | ε | selected | status | width met | max width | complete s | producer-only s | fastest verified route on the cell MEETING ε (s) | regret s | diagnostics passing ε but not prospectively qualified |")
L.append("|---|---|---|---|---|---|---|---|---|---|---|---|")
for c in S["cells"]:
    for eps, sel in sorted(c["selector"].items()):
        row = next((x for x in c["routes"] if x["kind"] == "select" and x["eps"] == eps and x["rep"] == 0), {})
        fr = (c["fastest_complete_verified_route_meeting_width"] or {}).get(eps) or {}
        L.append("| %s | %s | %s | %s | %s | %s | %s | %s | %s | %s (%s) | %s | %s |" % (c["panel"], c["r_label"], eps, sel["route"], sel["status"], sel["width_met"], g(row.get("max_width_float")), f(sel["complete_s"]), f(row.get("producer_only_s")), fr.get("route", "—"), f(fr.get("s")), f(sel["regret_s"]), ", ".join(sel["diagnostics_passing_width_but_not_qualified"]) or "—"))
L.append("\n## Every attempted route per cell (route-by-route cost table)\n")
L.append("| panel | r | kind | ε | route | status | checker | max width | met 1/100 | met 1/20 | complete s | producer-only s | route walls s (construction / evaluation / certificate) | checker s | peak tree RSS KiB | max bits | ref containment failures | max |shift| bound from π |")
L.append("|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|")
for c in S["cells"]:
    for x in c["routes"]:
        rw = x.get("route_walls_s") or {}
        L.append("| %s | %s | %s%s | %s | %s | %s | %s | %s | %s | %s | %s | %s | %s / %s / %s | %s | %s | %s | %s | %s |" % (c["panel"], c["r_label"], x["kind"], ("" if x["rep"] == 0 else " rep%d" % x["rep"]), x.get("eps") or "—", x["route"], x["status"], x.get("checker") or "—", g(x.get("max_width_float")),
                 (x.get("width_met") or {}).get("1/100", "—"), (x.get("width_met") or {}).get("1/20", "—"), f(x.get("complete_supervisor_wall_s")), f(x.get("producer_only_s")), g(rw.get("construction")), g(rw.get("evaluation")), g(rw.get("certificate")), f((x.get("phases_s") or {}).get("checker")), x.get("peak_tree_rss_kib") or "—", x.get("max_bits") or "—", x.get("reference_containment_failures", "—"), g(x.get("max_movement_bound_from_pi"))))
L.append("\n## Movement diagnostic (exact reference vs the ignore-bridge marginals π(X_i=+1); all coordinates are in SCORES.json)\n")
L.append("| panel | r | max |P_r − π| | coordinates moved > ε/2 at ε=1/100 | at ε=1/20 | F0 met 1/100 | F0 met 1/20 | E = W (small control) |\n|---|---|---|---|---|---|---|---|")
for c in S["cells"]:
    mv = c.get("movement") or {}
    L.append("| %s | %s | %s | %s | %s | %s | %s | %s |" % (c["panel"], c["r_label"], g(mv.get("max_abs_shift_float")), (mv.get("coordinates_moved_more_than_half_width") or {}).get("1/100", "—"), (mv.get("coordinates_moved_more_than_half_width") or {}).get("1/20", "—"), (c.get("F0_width_met") or {}).get("1/100", "—"), (c.get("F0_width_met") or {}).get("1/20", "—"), c.get("E_W_agree")))
a = S["allowance"]
L.append("\n## Allowance (one ledger; every supervised child's complete wall charged once)\n\n| scope | charged s |\n|---|---|")
for k, v in a["by_kind"].items():
    L.append("| %s | %.3f |" % (k, v))
L.append("| **total** | **%.3f of %.0f** (%d children; unknown charges: %s; unattempted: %d; reused diagnostics: %d) |\n" % (a["charged_s"], a["allowance_s"], a["children"], a["unknown"], len(a["unattempted"] or []), a["reused"]))
open(os.path.join(E, "REPORT.md"), "w").write("\n".join(L)); print("REPORT.md", len(L), "lines")
