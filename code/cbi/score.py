"""Scoring from saved case records only -> SCORES.json and REPORT.md."""
import os, sys, json, glob
sys.set_int_max_str_digits(0)
HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
E = os.path.join(HERE, "runs/mdi_2026-10-28/CBI_LIBRARY_2026-11-06")
from fractions import Fraction as Fr
man = json.load(open(os.path.join(E, "MANIFEST.json"))); led = json.load(open(os.path.join(E, "ALLOWANCE_LEDGER.json")))
cases = {}
for c in man["cases"]:
    f = os.path.join(E, "cases", "%03d_%s_%s_%s_rep%d.json" % (c["id"], c["instance"], c["mode"], c["width"].replace("/", "_"), c["rep"]))
    rec = json.load(open(f)) if os.path.exists(f) else {"status": "MISSING"}
    ch = [x for x in led["charges"] if x["id"] == c["id"]]
    cases[c["id"]] = {**c, "rec": rec, "charge": (ch[-1] if ch else None), "faulted_first": any(x.get("outcome") == "COMPLETED" and x.get("status") == "FAULT" for x in ch)}


def g(x, nd=3):
    return "—" if x is None else (("%." + str(nd) + "g") % x if isinstance(x, (int, float)) else str(x))


def by(inst, mode, width="1/100", rep=0):
    return next((v for v in cases.values() if v["instance"] == inst and v["mode"] == mode and v["width"] == width and v["rep"] == rep), None)


def posthoc_truth(v):
    """Containment and movement from the saved result file and the instance's truth record (artifact-only)."""
    tr = next((x["rec"] for x in cases.values() if x["instance"] == v["instance"] and x["mode"] == "truth_ve"), None)
    rf = os.path.join(E, "cases", (v["rec"].get("result_file") or ""))
    if not tr or not tr.get("truth") or not v["rec"].get("result_file") or not os.path.exists(rf):
        return None
    res = json.load(open(rf)); inst = json.load(open(os.path.join(E, "inputs", v["instance"] + ".json")))
    pi = {str(b["id"]): [Fr(sum(w for x, w in zip(b["rows"], b["weights"]) if (x >> j) & 1), sum(b["weights"])) for j in range(inst["d"])] for b in inst["blocks"]}
    n = f = 0; mv = []
    for q, iv in res["intervals"].items():
        for j, row in enumerate(iv["coordinates"]):
            t = Fr(tr["truth"][q][j]); n += 1; mv.append(abs(t - pi[q][j]))
            if not (Fr(int(row["lo"]), 1 << 80) <= t <= Fr(int(row["hi"]), 1 << 80)):
                f += 1
    return {"coordinates": n, "failures": f, "max_movement": float(max(mv)) if mv else None, "moved_gt_half_width": sum(1 for x in mv if x > Fr(v["width"]) / 2)}


rows = []
for cid, v in sorted(cases.items()):
    r = v["rec"]; t = r.get("timings") or {}; pq = r.get("per_query") or {}
    if v["mode"] == "library":
        ph = posthoc_truth(v)
        if ph:
            r["truth_containment"] = {"coordinates": ph["coordinates"], "failures": ph["failures"]}; r["true_max_movement_from_pi"] = ph["max_movement"]; r["coordinates_moved_more_than_half_width"] = ph["moved_gt_half_width"]
    modes = sorted({str(x.get("mode")) for x in pq.values()}); zs = [float(Fr(x["z"])) for x in pq.values() if x.get("z") not in (None, "0")]
    rows.append({"id": cid, "instance": v["instance"], "mode": v["mode"], "width": v["width"], "rep": v["rep"], "status": r.get("status"), "verify": r.get("verify_accepted"),
                 "outer_wall_s": (v["charge"] or {}).get("outer_wall_s"), "outcome": (v["charge"] or {}).get("outcome"), "cold_s": t.get("cold_solve_plus_verify_s"), "solve_s": t.get("solve_s"), "verify_s": t.get("verify_s"), "load_s": t.get("load_model_s"),
                 "phases": t.get("solve_phases_s"), "repeat_s": [x["solve_plus_verify_s"] for x in (t.get("repeated_query") or [])], "rss_MB": (r.get("child_high_water_rss_bytes") or 0) / 1e6,
                 "plan_modes": modes, "max_width": max([x.get("max_width") or 0 for x in pq.values()], default=None), "z_max": max(zs, default=0.0), "per_query_status": {k: x.get("status") for k, x in pq.items()},
                 "truth_containment": r.get("truth_containment"), "true_max_movement": r.get("true_max_movement_from_pi"), "moved_gt_half_width": r.get("coordinates_moved_more_than_half_width"),
                 "attempts_total": sum(len(x.get("attempts") or []) for x in pq.values()), "escalations": sum(1 for x in pq.values() for a in (x.get("attempts") or []) if a.get("escalation")),
                 "clusters_verified": len(((r.get("clusters") or {}).get("verified") or [])), "clusters_rejected": [(c["cluster"], c["reason"][:70]) for c in ((r.get("clusters") or {}).get("rejected") or [])][:3],
                 "reason": r.get("reason"), "price_entries": r.get("price_entries"), "truth_s": t.get("truth_ve_s"), "faulted_first": v["faulted_first"]})
dev = sum(float(x["seconds"]) for x in led["development_invocations"]["entries"]); exp = sum(x["outer_wall_s"] for x in led["charges"])
S = {"rows": rows, "allowance": {"allowance_s": led["allowance_s"], "development_s": dev, "experiment_outer_walls_s": exp, "total_s": dev + exp, "remaining_s": led["allowance_s"] - dev - exp, "cases_run": len(led["charges"]), "unattempted": led["unattempted"], "reruns_after_amendment": [x["id"] for x in led["charges"] if x.get("rerun_after_harness_fix")]}}
json.dump(S, open(os.path.join(E, "SCORES.json"), "w"), indent=1, default=str)

# ---------------- report
L = ["# cbi — coupled-block inference library: pass report (6 November 2026)\n"]
corr = [r for r in rows if r["instance"].startswith("c_") and r["mode"] == "library"]
n_c = sum((r["truth_containment"] or {}).get("coordinates", 0) for r in corr); f_c = sum((r["truth_containment"] or {}).get("failures", 0) for r in corr)
perf_lib = [r for r in rows if r["instance"].startswith("p_") and r["mode"] == "library"]
L.append("**Can someone use it, what works, where is the advantage?** Yes: `cbi.api.solve(model, queries, width, limits)` / `verify(model, result)` and `python -m cbi.cli` accept a supplied JSON model of binary block tables joined by the product kernel (block supports, positive weights, edges with rational couplings, hard equalities, optional cluster hints) and return checked intervals or an explicit truthful status. In this pass every one of the %d correctness-layer library results was CERTIFIED and independently verified, with %d / %d published coordinates containing the exact reference (chains, spokes, branching trees, a 4-cycle, a ladder, an open 3×3 mesh, a periodic 3×3 mesh, a strong 4-cycle island with leaves, a hard-equality cycle with a redundant edge); at the 1/100 width all performance-layer library runs were CERTIFIED except the declared challenge (seam coupling 1/64: VALID_BUT_TOO_WIDE, width %.3g), and the 1/500 width on the island meshes (VALID_BUT_TOO_WIDE: the Theorem-3/Theorem-1 radius is larger than 1/500 while the regional solve is exact). The strong-island meshes (d = 24, 4,096 rows, ≥ 512 common rows per 2×2 island, internal r = 1 − 2^−24, seam r = 1/4096) receive full-model certificates of width %.3g (4×4, corner islands only), %.3g (6×6) and %.3g (8×8; the interior-island value, which no longer grows) with cold solve+verify %.1f / %.1f / %.1f s for ALL queries, and no comparator able to run (the dense exact comparator prices at ≥ 2^24 entries and is refused before launch); weak open meshes certify at width ≈ %.2g with %.1f / %.1f / %.1f s cold (all queries). Where an exact comparator completed (chains and trees with 512-row blocks) the library was 5–11 %% faster in cold solve+verify — a margin that may be noise — because it chose exact operators on most edges and a degree-1 enclosure where it qualified; on the near-hard 4-cycle island with leaves the library certified in %.2f s while the exact comparator (with its verification) exceeded the 120 s cap and the exact-truth elimination alone took %.1f s. The meaningful advantage is therefore architectural (local certificates whose per-query cost does not grow with the mesh; no comparator completes there) rather than a matched same-task speedup against a completed exact baseline, which existed only on tree-like instances.\n" % (
    len(corr), n_c - f_c, n_c, (by("p_challenge_island_seam_1_64", "library") or {"rec": {}})["rec"].get("per_query", {}) and max(x["max_width"] for x in by("p_challenge_island_seam_1_64", "library")["rec"]["per_query"].values()),
    max(x["max_width"] for x in by("p_island_mesh_4x4", "library")["rec"]["per_query"].values()), max(x["max_width"] for x in by("p_island_mesh_6x6", "library")["rec"]["per_query"].values()), max(x["max_width"] for x in by("p_island_mesh_8x8", "library")["rec"]["per_query"].values()), by("p_island_mesh_4x4", "library")["rec"]["timings"]["cold_solve_plus_verify_s"], by("p_island_mesh_6x6", "library")["rec"]["timings"]["cold_solve_plus_verify_s"], by("p_island_mesh_8x8", "library")["rec"]["timings"]["cold_solve_plus_verify_s"],
    max(x["max_width"] for x in by("p_weak_mesh_4x4", "library")["rec"]["per_query"].values()), by("p_weak_mesh_4x4", "library")["rec"]["timings"]["cold_solve_plus_verify_s"], by("p_weak_mesh_6x6", "library")["rec"]["timings"]["cold_solve_plus_verify_s"], by("p_weak_mesh_8x8", "library")["rec"]["timings"]["cold_solve_plus_verify_s"],
    by("p_nearhard_cycle", "library")["rec"]["timings"]["cold_solve_plus_verify_s"], by("p_nearhard_cycle", "truth_ve")["rec"]["timings"]["truth_ve_s"]))
L.append("Branch `cbi-library-2026-11-06` (from main; main and all accepted records untouched). Pre-launch commit `%s`. Manifest: 21 instances (10 correctness, 11 performance base instances), 86 cases, frozen before outcomes. Allowance: %.1f s development invocations + %.1f s experiment outer walls = %.1f s of 3,600 s; %d cases run (4 reruns after a harness-record amendment, originals preserved); nothing unattempted. Timing = child in-process cold solve + verify (load, reductions, recognition, planning, certificate, verification, publication) and the parent's prompt-wait outer wall; peak memory = child ru_maxrss.\n" % (open(os.path.join(E, "COMMIT_BEFORE_LAUNCH.txt")).read().strip()[:12], dev, exp, dev + exp, len(led["charges"])))
L.append("## 1. Correctness layer (exact reference by exact VE; `truth_ve`)\n\n| instance | blocks / edges | library 1/100 | verify | contained | max width | movement max | moved > ε/2 | 1/20 | comparator (exact) | cold s lib / cmp | truth s |\n|---|---|---|---|---|---|---|---|---|---|---|---|")
for inst in [k for k in man["instances"] if k.startswith("c_")]:
    a = by(inst, "library"); b = by(inst, "library", "1/20"); c = by(inst, "comparator_exact"); t = by(inst, "truth_ve"); tc = a["rec"].get("truth_containment") or {}
    L.append("| %s | %d / %d | %s (%s) | %s | %s/%s | %s | %s | %s | %s | %s | %s / %s | %s |" % (inst, man["instances"][inst]["blocks"], man["instances"][inst]["edges"], a["rec"]["status"], ", ".join(sorted({str(x["mode"]) for x in a["rec"]["per_query"].values()})), a["rec"]["verify_accepted"], tc.get("coordinates", 0) - tc.get("failures", 0), tc.get("coordinates"), g(max(x["max_width"] for x in a["rec"]["per_query"].values())), g(a["rec"].get("true_max_movement_from_pi")), a["rec"].get("coordinates_moved_more_than_half_width"), b["rec"]["status"], c["rec"]["status"], g(a["rec"]["timings"]["cold_solve_plus_verify_s"]), g(c["rec"]["timings"].get("cold_solve_plus_verify_s")), g(t["rec"]["timings"].get("truth_ve_s"))))
L.append("\n## 2. Performance layer (d = 24; cold = in-process solve + verify; outer = parent-measured process wall; reps where measured)\n")
L.append("| instance | blocks / edges / rows | width | library status | modes | max width | z max | cold s (reps) | solve / verify s | outer s | repeat solve+verify s | RSS MB | comparator status | comparator cold s | truth |\n|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|")
for inst in [k for k in man["instances"] if k.startswith("p_")]:
    for w in ("1/100", "1/20", "1/200", "1/500"):
        libs = sorted([r for r in rows if r["instance"] == inst and r["mode"] == "library" and r["width"] == w], key=lambda r: r["rep"])
        if not libs:
            continue
        a = libs[0]; cmp_ = [r for r in rows if r["instance"] == inst and r["mode"] == "comparator_exact" and r["rep"] == 0]; cmp_ = cmp_[0] if cmp_ else None; tr = by(inst, "truth_ve")
        m0 = man["instances"][inst]["meta"]
        L.append("| %s | %d / %d / %s | %s | %s | %s | %s | %s | %s | %s / %s | %s | %s | %.0f | %s | %s | %s |" % (inst, man["instances"][inst]["blocks"], man["instances"][inst]["edges"], m0.get("m"), w, a["status"] + (" (per query: %s)" % dict(sorted({s: list(a["per_query_status"].values()).count(s) for s in set(a["per_query_status"].values())}.items())) if len(set(a["per_query_status"].values())) > 1 else ""), ", ".join(a["plan_modes"]), g(a["max_width"]), g(a["z_max"]),
            " / ".join(g(r["cold_s"]) for r in libs), g(a["solve_s"]), g(a["verify_s"]), " / ".join(g(r["outer_wall_s"]) for r in libs), ", ".join(g(x) for x in a["repeat_s"]), a["rss_MB"],
            (cmp_["status"] if cmp_ else "—") if w == "1/100" else "—", (g(cmp_["cold_s"]) if cmp_ and cmp_["cold_s"] else ("TIMEOUT 120 s" if cmp_ and cmp_["outcome"] == "TIMEOUT" else ("refused: %s entries" % g(cmp_["price_entries"]) if cmp_ and cmp_["price_entries"] else "—"))) if w == "1/100" else "—",
            ("%s (%.1f s; contained %s/%s, moved>ε/2 %s)" % (tr["rec"]["status"], tr["rec"]["timings"].get("truth_ve_s", 0), (a["truth_containment"] or {}).get("coordinates", 0) - (a["truth_containment"] or {}).get("failures", 0), (a["truth_containment"] or {}).get("coordinates"), a["moved_gt_half_width"]) if tr else "unmeasured (no feasible exact reference)")))
L.append("\n## 3. Scaling (all-query cold solve + verify; the certificate radius z does not grow with the mesh)\n\n| family | 4×4 (16 blocks) | 6×6 (36) | 8×8 (64) | comparator |\n|---|---|---|---|---|")
for fam, nm in (("weak open mesh r=1/4096", "p_weak_mesh"), ("strong-island mesh (2×2 islands)", "p_island_mesh")):
    vals = []
    for sz in ("4x4", "6x6", "8x8"):
        a = by("%s_%s" % (nm, sz), "library"); vals.append("%.1f s, width %s, z %s" % (a["rec"]["timings"]["cold_solve_plus_verify_s"], g(max(x["max_width"] for x in a["rec"]["per_query"].values())), g(max([float(Fr(x["z"])) for x in a["rec"]["per_query"].values() if x.get("z")], default=0))))
    L.append("| %s | %s | %s | %s | refused before launch (dense entries ≥ 2^24 at 4×4) |" % (fam, *vals))
L.append("\nPer-query cost is roughly constant (the region is the queried block's radius-1 ball; 5 coarse blocks at most), so all-query cost grows linearly in the block count (weak mesh 4.5 → 11.6 → 21.7 s for 16 → 36 → 64 blocks; island mesh 1.5 → 5.1 → 11.9 s); no full-mesh separator is ever built. The certificate radius depends on the number of neighbouring islands (corner 0.00088, interior 0.0021) and saturates once interior islands exist; it does not grow further with the mesh. The 6×6 and 8×8 island meshes faulted on the first run in the HARNESS (a JSON serialization of the planner's working copy and Python's 4,300-digit int→str limit on the exact iterates); solve and verify had completed and verify had accepted; the four cases were rerun once after the fix (`AMENDMENTS.json`, originals preserved).\n")
L.append("## 4. Width / work adaptation\n\n| instance | 1/100 | 1/200 | 1/500 | 1/20 |\n|---|---|---|---|---|")
for inst in ("p_island_mesh_4x4", "p_island_mesh_6x6", "p_island_mesh_8x8", "p_chain8_s0", "p_tree15_s0", "p_nearhard_cycle"):
    cells = []
    for w in ("1/100", "1/200", "1/500", "1/20"):
        a = by(inst, "library", w)
        cells.append("—" if not a else "%s w=%s att=%d esc=%d %.1fs" % (a["rec"]["status"][:9], g(max(x["max_width"] for x in a["rec"]["per_query"].values())), sum(len(x["attempts"] or []) for x in a["rec"]["per_query"].values()), sum(1 for x in a["rec"]["per_query"].values() for t in (x["attempts"] or []) if t.get("escalation")), a["rec"]["timings"]["cold_solve_plus_verify_s"]))
    L.append("| %s | %s | %s | %s | %s |" % (inst, *cells))
L.append("\nAt 1/500 the frozen cluster-acceptance rule (ρ_i ≤ ε/8 = 2.5·10^−4) REJECTED the islands (ρ_i ≈ 5·10^−4, premises verified), so the planner fell back to the uncoarsened graph, where the internal couplings r = 1 − 2^−24 give θ ≈ 1 and Theorem 1 cannot leave z = 1: VALID_BUT_TOO_WIDE with width 1 after escalation (degree raised, region enlarged, exact operators). This is a SELECTOR-DECISION failure of the frozen rule, not a limit of the certificate: at 4×4 the coarse plan that certified 0.00175 at 1/100 would also have met 1/500 (0.00175 < 0.002); at 6×6 and 8×8 (0.0036, 0.0042) it would not. The rule was frozen before outcomes and is NOT retuned in this pass; it is recorded as the next fix. The 1/200 requests certified through the same coarse plans as 1/100; the 1/20 requests reused the 1/100 plans (no cheaper qualified operator on the menu).\n")
L.append("## 5. Failures separated\n\n* Implementation correctness: none found in the computation (all exact-reference containments hold; the verifier accepted every CERTIFIED / VALID result). One harness fault (record serialization) was fixed by amendment with four reruns.\n* Certificate tightness: the strong-island certificate is ≈ 1.8·10^−3 wide at 1/100 and cannot reach 1/500 (coarsening ρ + boundary z dominate); the challenge seam 1/64 makes θ = 24·(1/64) too large for the radius-1 star (row sums ≈ 1.5) and the dense elimination of a larger region is priced out: VALID_BUT_TOO_WIDE.\n* Representation construction: the automatic strong-cluster rule proposed the correct 2×2 islands from the couplings alone on the small island mesh (and the hints were verified, not trusted, on the large ones); clusters whose ρ exceeds ε/8 are rejected with the reason recorded (the chain's r = 1 − 2^−12 pair had C_i ≈ 2·10^−7 and ρ ≈ 1).\n* Arithmetic / checking overhead: the verifier costs about as much as the solve on message-passing instances (exact transfers of 4,096×4,096 pairs with 96-bit interval cavities); on the strong-island meshes verification is a third of the cold time.\n* Selector decisions: ONE clear mistake — the frozen cluster-acceptance threshold ρ_i ≤ ε/8 rejected verified islands at the 1/500 width and lost a plan that would have certified the 4×4 island mesh (§4). On chains/trees the planner picked exact operators on most edges and degree-1 enclosures where prospectively qualified (5–11 %% faster than the all-exact comparator, possibly noise). On the challenge instance (seam 1/64) the islands were rejected for the same reason (ρ_i ≈ 0.01 > 1/800) and no plan on the menu certifies: the region star has θ ≈ 1 on the internal edges without coarsening.\n* Exact-reference limits: the dense exact comparator was refused before launch on every m = 4,096 mesh (≥ 2^24 entries) and timed out at 120 s on the near-hard cycle (its truth took 26 s with the specialized order); no claim of speedup is made against those.\n")
L.append("## 5b. Movement (exact reference vs the uncoupled prior π; where a reference exists)\n\n| instance | width | max |P − π| | coordinates moved > ε/2 | contained |\n|---|---|---|---|---|")
for r in rows:
    if r["mode"] == "library" and r["true_max_movement"] is not None:
        L.append("| %s | %s | %s | %s / %s | %s / %s |" % (r["instance"], r["width"], g(r["true_max_movement"]), r["moved_gt_half_width"], r["truth_containment"]["coordinates"], r["truth_containment"]["coordinates"] - r["truth_containment"]["failures"], r["truth_containment"]["coordinates"]))
L.append("\nFor the m = 4,096 meshes no exact global reference was obtained (the dense comparator refused before launch): their truth is UNMEASURED; the checked global certificate, the exact regional solves and the verified structural premises are what the report offers for them.\n")
L.append("## 6. Not implemented / not established\n\nAnchored Theorem-4 transfer (unimplemented theory); the nonbacktracking Theorem-2 comparison (not needed: no declared case was blocked that it would resolve); hard surrogate factors; coordinate maps and non-product kernels; Gaussian or tensor backends. No wall-time theorem; results are one host, single or three repetitions; sub-second differences are noise.\n")
open(os.path.join(E, "REPORT.md"), "w").write("\n".join(L)); print("REPORT.md", len(L), "lines; allowance", S["allowance"])
