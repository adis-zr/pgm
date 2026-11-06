"""Pass-2 panel scorer (REPLAY3). Reads only replay3/ records + ledger; writes REPLAY3_SCORES.json. No inference."""
import json, os, sys, statistics as st
E = sys.argv[1] if len(sys.argv) > 1 else "runs/mdi_2026-10-28/CBI_LIBRARY_2026-11-06"
L = json.load(open(E + "/REPLAY3_LEDGER.json")); M = json.load(open(E + "/REPLAY3_MANIFEST.json"))
rows = []
for ch in L["charges"]:
    f = [x for x in os.listdir(E + "/replay3") if x.startswith("%03d_" % ch["id"]) and not x.endswith(".result.json")]
    rec = json.load(open(E + "/replay3/" + f[0])) if f else {}
    t = rec.get("timings", {}); pq = rec.get("per_query") or {}
    res_f = rec.get("result_file"); cert = json.load(open(E + "/replay3/" + res_f)) if res_f and os.path.exists(E + "/replay3/" + res_f) else {}
    proofs = cert.get("proofs") or {}
    # directed transfers and checker work from the proof records
    directed = 0; nodes_solved = 0; region_solves = 0; max_int_digits = 0
    for pid, P in proofs.items():
        ops = P.get("inside_ops") or P.get("ops") or {}
        if P.get("kind") == "forest_batched":
            directed += 2 * len(ops); nodes_solved += len(P.get("nodes") or P.get("H") or [])
        else:
            region_solves += 1; directed += len(ops)
        for q in (P.get("intervals") or {}).values():
            pass
    widths = [q.get("max_width") for q in pq.values() if q.get("max_width") is not None]
    rows.append({"id": ch["id"], "instance": ch["instance"], "mode": ch["mode"], "width": ch["width"], "queries": ch["queries"], "rep": ch["rep"],
                 "outcome": ch["outcome"], "status": rec.get("status"), "verify_accepted": rec.get("verify_accepted"),
                 "outer_wall_s": ch["outer_wall_s"], "cold_incl_load_s": t.get("cold_incl_load_s"), "solve_s": t.get("solve_s"), "verify_s": t.get("verify_s"),
                 "publish_s": (t.get("solve_phases_s") or {}).get("publish"),
                 "proofs": rec.get("proofs"), "by_kind": rec.get("distinct_proofs_by_kind"), "certificate_bytes": rec.get("certificate_bytes"),
                 "max_z_grid_bits": rec.get("max_z_grid_bits"), "rss_bytes": rec.get("child_high_water_rss_bytes"),
                 "directed_transfers": directed, "region_solves": region_solves, "forest_nodes": nodes_solved,
                 "max_width": max(widths) if widths else None, "n_queries": len(pq),
                 "containment": rec.get("truth_containment"), "true_max_movement": rec.get("true_max_movement_from_pi"),
                 "moved_gt_half_width": rec.get("coordinates_moved_more_than_half_width"),
                 "price_pairs_per_edge": rec.get("price_pairs_per_edge"), "per_query_status": sorted({q.get("status") for q in pq.values()}),
                 "modes": sorted({str(q.get("mode")) for q in pq.values()}), "systems": sorted({str(q.get("system")) for q in pq.values()}),
                 "ops": sorted({json.dumps(v) for q in pq.values() for v in (q.get("ops") or {}).values()}),
                 "fault": rec.get("reason") if rec.get("status") == "FAULT" else None})
# paired forest comparison (library vs comparator_exact, all queries, 1/100, 3 reps) on cold_incl_load_s
pairs = {}
for r in rows:
    if r["queries"] == "all" and r["width"] == "1/100" and r["mode"] in ("library", "comparator_exact") and r["cold_incl_load_s"] is not None:
        pairs.setdefault(r["instance"], {}).setdefault(r["mode"], []).append(r["cold_incl_load_s"])
comp = {}
for inst, d in pairs.items():
    if "comparator_exact" in d:
        lib = d["library"]; ex = d["comparator_exact"]
        comp[inst] = {"library_cold_s": lib, "comparator_cold_s": ex, "library_median": st.median(lib), "comparator_median": st.median(ex),
                      "ratio_library_over_comparator": st.median(lib) / st.median(ex)}
S = {"commit": L.get("commit"), "manifest_commit": M.get("commit"), "cases": len(rows), "completed": sum(r["outcome"] == "COMPLETED" for r in rows),
     "all_verified": all(r["verify_accepted"] is True for r in rows if r["outcome"] == "COMPLETED"),
     "containment_total": sum((r["containment"] or {}).get("coordinates", 0) for r in rows), "containment_failures": sum((r["containment"] or {}).get("failures", 0) for r in rows),
     "total_outer_wall_s": sum(r["outer_wall_s"] for r in rows), "forest_comparison": comp, "rows": rows}
json.dump(S, open(E + "/REPLAY3_SCORES.json", "w"), indent=1)
print("cases %d completed %d all_verified %s containment %d/%d failures total wall %.1f s" % (S["cases"], S["completed"], S["all_verified"], S["containment_total"] - S["containment_failures"], S["containment_total"], S["total_outer_wall_s"]))
print("%-28s %-16s %-5s %-4s %-9s %6s %6s %6s %6s %3s %7s %4s %6s %9s %4s %s" % ("instance", "mode", "w", "q", "status", "cold", "solve", "verif", "wall", "pf", "cert_B", "zb", "RSS_MB", "maxwidth", "dir", "ops"))
for r in rows:
    print("%-28s %-16s %-5s %-4s %-9s %6.2f %6.2f %6.2f %6.2f %3s %7s %4s %6.0f %9.2e %4d %s" % (r["instance"], r["mode"], r["width"], r["queries"], r["status"], r["cold_incl_load_s"] or -1, r["solve_s"] or -1, r["verify_s"] or -1, r["outer_wall_s"], r["proofs"], r["certificate_bytes"], r["max_z_grid_bits"], (r["rss_bytes"] or 0) / 1e6, r["max_width"] or 0, r["directed_transfers"], ",".join(r["ops"])))
for inst, c in comp.items():
    print("PAIR %-24s library median %.3f s  comparator median %.3f s  ratio %.2f" % (inst, c["library_median"], c["comparator_median"], c["ratio_library_over_comparator"]))

# ---- comparator-enclosure containment (saved endpoints only): for instances WITHOUT an exact truth file, check that every library
# interval contains the independently verified exact comparator's enclosure (width ~3e-24) on the same instance / queries / width.
S = json.load(open(E + "/REPLAY3_SCORES.json"))
by = {}
for r in S["rows"]:
    f = [x for x in os.listdir(E + "/replay3") if x.startswith("%03d_" % r["id"]) and x.endswith(".result.json")]
    if f: by[r["id"]] = json.load(open(E + "/replay3/" + f[0]))["intervals"]
cc = {}
for r in S["rows"]:
    if r["mode"] != "library" or r["containment"] is not None: continue
    comps = [c for c in S["rows"] if c["mode"] == "comparator_exact" and c["instance"] == r["instance"] and c["queries"] == "all"]
    if not comps or r["id"] not in by: continue
    ref = by[comps[0]["id"]]; lib = by[r["id"]]; n = 0; fails = 0
    for q, iv in lib.items():
        for j, c in enumerate(iv["coordinates"]):
            rc = ref[q]["coordinates"][j]; n += 1
            if not (int(c["lo"]) <= int(rc["lo"]) and int(rc["hi"]) <= int(c["hi"])): fails += 1
    cc[r["id"]] = {"instance": r["instance"], "width": r["width"], "queries": r["queries"], "coordinates": n, "failures": fails, "reference_case": comps[0]["id"]}
    r["comparator_enclosure_containment"] = cc[r["id"]]
S["comparator_enclosure_containment"] = {"note": "library intervals vs the verified exact comparator's enclosure (closed, saved endpoints; NOT an exact truth)", "coordinates": sum(v["coordinates"] for v in cc.values()), "failures": sum(v["failures"] for v in cc.values()), "cases": cc}
json.dump(S, open(E + "/REPLAY3_SCORES.json", "w"), indent=1)
print("comparator-enclosure containment: %d/%d" % (S["comparator_enclosure_containment"]["coordinates"] - S["comparator_enclosure_containment"]["failures"], S["comparator_enclosure_containment"]["coordinates"]), {v["instance"] + " q=" + v["queries"] + " w=" + v["width"]: (v["coordinates"], v["failures"]) for v in cc.values()})
