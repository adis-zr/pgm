"""REPORT.md from SCORES.json, GENERATION.json, the allowance ledger and the diagnostics (artifact-only)."""
import os, sys, json
HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
E = os.path.join(HERE, "runs/mdi_2026-10-28/ND_CERTIFICATE_2026-11-05")
S = json.load(open(os.path.join(E, "SCORES.json"))); G = json.load(open(os.path.join(E, "GENERATION.json"))); led = json.load(open(os.path.join(E, "ALLOWANCE_LEDGER.json")))
diag = json.load(open(os.path.join(E, "diagnostics/split_constancy.json"))) if os.path.exists(os.path.join(E, "diagnostics/split_constancy.json")) else None
B = json.load(open(os.path.join(E, "BINDINGS.json")))


def f(x, nd=4):
    if x is None: return "—"
    if isinstance(x, float): return ("%." + str(nd) + "g") % x
    return str(x)


L = []
L.append("# Certified inference after discarding low-weight factor entries — implementation-and-diagnostic pass (Promedus_12 derived positive family; 5–6 November 2026)\n")
L.append("Branch `nd-certificate-2026-11-05` (isolated; main and every accepted pin untouched). Pre-launch commit %s. Theory: the overseer's handoff of 5 Nov 2026 (two-channel mini-bucket certificate, sharp mixture transfer). Contract `CONTRACT.md` and `BINDINGS.json` frozen before any outcome; candidates sealed (`CANDIDATES_SEAL.json`) before any reference.\n" % B["commit_before_launch"][:12])
L.append("## 1. Decision\n")
L.append("**This certificate approach should STOP on these cases.** The two-channel first-fit mini-bucket certificate at K = 4,096 is correct (every conformance control passes; the independent checker reproduces both channels exactly on all eight candidates) and cheap (≈ 0.23–0.25 s to construct, ≈ 0.47–0.69 s to check, < 10 kbit integers), but on Promedus_12's structure it is loose by a factor 2^29 ≈ 5.4·10^8 on the retained channel (29 split buckets; measured exactly at λ = 1 against the exact R), which drives ρ to 1 − 4·10^-8 regardless of how small the true discarded mass is. Independently, at the one λ where the truth is known (λ = 1) the TRUE discarded fraction is 4.96 % (G100) and 0.25 % (G10000): the first already exceeds the 1 % target's allowance ≈ 0.75 %, the second would pass only with a certificate tight to within a factor ≈ 3. Two further findings constrain any continuation: the positive family has NO exact zeros, so the delivered dense exact reference is physically INADMISSIBLE at 8 GiB for λ ≤ 10^-2 (the exact aggregation forecasts 38.25 GiB; the original Promedus_12 is tractable only because of its 1,080 hard zeros), and the retained (masked) solve was refused by the frozen dense-first admission at the prospectively set 180 s wall for the six candidates with λ ≤ 10^-2 (forecast ≈ 248 s on this structure), so no retained enclosure, R, or sparse-route timing exists for them in this pass. No rerun, resize or K change was made.\n")
L.append("Diagnoses, kept separate: **loose upper bound — DOMINANT** (2^29 on V; U/D = 5.4·10^8 at λ = 1); **excessive true discarded mass** — PRESENT at λ = 1 for G100 (4.96 %), marginal for G10000 (0.25 %), UNKNOWN at λ ≤ 10^-2 (no reference); **empty / large retained support** — not empty (R > 0 at λ = 1); unknown at λ ≤ 10^-2 (retained solve refused); the frozen support admission itself rejected the sparse route at λ = 1 (ratio 1.62 / 1.21 < 10; at λ = 1 the preprocessing removes 141 constant factors and the whole dense solve takes < 1 s, so λ = 1 is a degenerate easy case, not representative); **construction overhead** — small (certificate 0.25 s; ≈ 1.3 % of the original 79 s dense run); **checking overhead** — small (≈ 0.6 s). The failing diagnoses are the first two.\n")
L.append("## 2. Inputs (generated; `GENERATION.json` annotations never read by solver or checker)\n")
L.append("Original Promedus_12: %d variables (all binary), %d occurrences, %d entries, %d zeros, %d observed. Rule: every zero := λ · m_f (m_f the occurrence's smallest positive entry), positives unchanged.\n" % (G["original"]["nvars"], G["original"]["factors"], G["original"]["entries"], G["original"]["zeros"], 3))
L.append("| input | λ | sha256 (uai) | zeros after | smallest entry |\n|---|---|---|---|---|")
for k, v in G["inputs"].items():
    L.append("| %s | %s | %s… | %d | %s |" % (k, v["lambda"], v["uai_sha256"][:16], v["zeros_after"], v["min_entry"]))
L.append("\n## 3. Candidates (one fresh supervised child each: 200 s deadline, 180 s retained wall, 8 GiB, no grace; complete supervisor walls)\n")
L.append("| candidate | mask: occurrences / entries removed | certificate V | U | U/V | ρ lower bound U/(V+U) | split buckets | cert s | check s | retained solve | R (exact) | ρ | published width (0.01 / 0.02 / 0.05 met) | child wall s | peak tree RSS |")
L.append("|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|")
for r in S["candidates"]:
    if r["status"] == "IDENTICAL_MASK_NOT_RECOMPUTED":
        L.append("| %s | identical mask to %s | — | — | — | — | — | — | — | not recomputed | — | — | — | 0 | — |" % (r["label"], r["identical_to"])); continue
    c = r.get("certificate") or {}; rt = r.get("retained") or {}; tr = r.get("transfer") or {}; t = r.get("truth") or {}
    V = c.get("V"); U = c.get("U")
    Vs = ("%.4e" % float(eval(V.replace("/", "/")))) if V and "/" not in V else (("%.4e" % (float(V.split("/")[0]) / float(V.split("/")[1]))) if V else "—")
    Us = (("%.4e" % (float(U.split("/")[0]) / float(U.split("/")[1]))) if U and "/" in U else (("%.4e" % float(U)) if U else "—"))
    ret = rt.get("status") + (" (%s)" % rt.get("route") if rt.get("route") else "") if rt.get("status") else "—"
    Rs = ("%.4e" % (float(rt["R_exact"].split("/")[0]) / float(rt["R_exact"].split("/")[1]))) if rt.get("R_exact") and "/" in rt["R_exact"] else (("%.4e" % float(rt["R_exact"])) if rt.get("R_exact") else "—")
    widths = ("%s (%s / %s / %s)" % (f(tr.get("worst_published_width_outward")), tr["targets"].get("1/100"), tr["targets"].get("1/50"), tr["targets"].get("1/20"))) if tr else "—"
    L.append("| %s | %d / %d | %s | %s | %s | %s | %d | %s | %s | %s | %s | %s | %s | %.3f | %d KiB |" % (
        r["label"], r["mask"]["occurrences_with_removals"], r["mask"]["removed_entries"], Vs, Us, f(c.get("U_over_V")), f(c.get("rho_lower_bound_U_over_V_plus_U")), c.get("split_buckets", 0),
        f(c.get("producer_wall_s")), f(c.get("checker_wall_s")), ret, Rs, f(t.get("rho") if t else None, 10), widths, r["supervisor_wall_s"], r["peak_tree_rss_kib"]))
L.append("\nUnits: V, U, R in ORIGINAL weight units (the certificate's integers divided by C = Π d_f; R reconciled through the exposed scale metadata). ρ = U/(L+U) with L = exact R. ρ lower bound uses V ≥ R. Masks G100 ⊇ G10000 occurrence by occurrence (verified). The six RETAINED_NOT_CERTIFIED rows are PRICE_REFUSAL `CHECKER_AGGREGATION_WALL_FORECAST_EXCEEDS` from the frozen dense-first admission at the 180 s retained wall (the dense identity forecast on this structure was 248 s on the original Promedus_12 at 600 s, where it was admitted and the support route then ran in 4.4 s); the sparse route is only priced after the dense identity is admitted. This is a consequence of the prospectively set limit; it is reported, not repaired.\n")
L.append("## 4. References (dense exact cells; pinned `mdi.launch --cell <input> baseline`, 600 s, 8 GiB; launched after the seal)\n")
L.append("| input | outcome | supervisor wall s | peak tree RSS | Z (exact, original units) | reason / scope |\n|---|---|---|---|---|---|")
for lam, r in S["references"].items():
    Zs = ("%.6e" % (float(r["Z_exact"].split("/")[0]) / float(r["Z_exact"].split("/")[1]))) if r.get("Z_exact") and "/" in r["Z_exact"] else (("%.6e" % float(r["Z_exact"])) if r.get("Z_exact") else "—")
    why = r["reason"][:230] if r["status"] != "CERTIFIED_FALLBACK_ONLY" else ("exact aggregation %s; preprocess removed %s constant factors" % ("vectorized exact integer junction tree", r["preprocess"].get("removed_constants")))
    L.append("| L%s | %s | %.3f | %d KiB | %s | %s |" % (lam, r["status"], r["supervisor_wall_s"], r["peak_tree_rss_kib"], Zs, why.replace("|", "/")))
L.append("\nThe full refusal text (λ ≤ 10^-2): *the exact integer aggregation forecasts 38.25 GiB resident (per-message bit bounds up to 10,796 bits) against the 8.00 GiB cap; … forecast 107.8 s, peak 6.86 GiB* for the producer + interval checker. With no exact zero in the perturbed tables the occupancy probe does not apply and every bag is fully occupied; the original Promedus_12 (1,080 hard zeros) was admitted at a 248 s forecast and ran in 78.5 s / 6.9 GB. Consequently D = Z − R, δ = D/Z and U/D are UNAVAILABLE for λ ≤ 10^-2; no enclosure exists either (PRICE_REFUSAL publishes nothing). No λ = 0 rerun was made.\n")
L.append("## 5. Truth where available (λ = 1)\n")
L.append("| candidate | Z | R | D = Z − R | δ = D/Z | ρ | U/D | V/R | true marginals inside published intervals |\n|---|---|---|---|---|---|---|---|---|")
for r in S["candidates"]:
    t = r.get("truth") or {}
    if t.get("Z") and t.get("D_exact"):
        c = r["certificate"]; rt = r["retained"]
        L.append("| %s | %.6e | %.6e | %.6e | %.6f | %.10f | %.4g | %.4g | %d / %d (exact: %d failures) |" % (
            r["label"], float(t["Z"].split("/")[0]) / float(t["Z"].split("/")[1]), float(rt["R_exact"].split("/")[0]) / float(rt["R_exact"].split("/")[1]),
            float(t["D_exact"].split("/")[0]) / float(t["D_exact"].split("/")[1]) if "/" in t["D_exact"] else float(t["D_exact"]), t["delta_D_over_Z"], t["rho"], t["U_over_D"], t["V_over_R"],
            t["containment"]["coordinates"] - t["containment"]["published_outward_failures"], t["containment"]["coordinates"], t["containment"]["exact_transferred_failures"]))
L.append("\nV/R = 2^29 EXACTLY for G100 (and 5.3687·10^8 for G10000): 29 split buckets, each with two groups at a binary variable. The post-hoc diagnostic (`diagnostics/split_constancy.json`, supervised) finds that in %s of the 29 split buckets the split-off lone group's message is constant in the eliminated variable on both channels (an exact factor 2 per such split); the remaining splits inflate by their own factors. The transferred intervals contain the truth on all 1,062 free coordinates (trivially: with ρ ≈ 1 every published interval is ≈ [0, 1]); the retained law's own numerical width is 0.0025035 in every case.\n" % (diag["G100"]["split_off_lone_groups_constant_in_v_both_channels"] if diag else "—"))
L.append("## 6. Target-width outcomes and the prospective selection rule (RECONSTRUCTED from the saved traces; not an end-to-end adaptive run)\n")
L.append("Every candidate fails every target (0.01, 0.02, 0.05): the two completed candidates publish width 1.0 (ρ ≈ 1); the six refused ones publish nothing. The rule \"G100 first, then G10000, then refusal to the existing fallback\" therefore selects REFUSAL on every input and every width, after paying both candidates (G100 + G10000 complete child walls: %s s per input). The existing fallback itself is REFUSED for λ ≤ 10^-2 (§4) and trivial for λ = 1 (0.9 s). Changing the requested width changed neither the selected computation nor the representation on any input; no accuracy adaptation was observed.\n" % ", ".join("%.2f" % v["1/100"]["paid_candidate_walls_s"] for v in S["selection_rule_reconstruction"].values()))
L.append("## 7. Complete measured costs (every supervised child's spawn-to-exit wall; the ONE allowance ledger)\n")
L.append("| scope | children | charged s |\n|---|---|---|")
for k, v in S["allowance"]["by_kind"].items():
    L.append("| %s | %d | %.3f |" % (k, sum(1 for c in led["charges"] if c.get("status") == "TERMINAL" and c["kind"] == k), v))
dg = [c for c in led["charges"] if c.get("status") == "TERMINAL" and c["kind"] == "diagnostic"]
L.append("| diagnostic (post-hoc split constancy) | %d | %.3f |" % (len(dg), sum(c["charged_s"] for c in dg)))
tot = sum(c["charged_s"] for c in led["charges"] if c.get("status") == "TERMINAL")
L.append("| **total** | %d | **%.3f of 3,600** |\n" % (sum(1 for c in led["charges"] if c.get("status") == "TERMINAL"), tot))
L.append("Component costs inside a candidate child (in-process stage walls; the supervisor wall above is the charge): parse + own restriction + mask 0.011–0.015 s; certificate 0.229–0.248 s (181,510 pair products, 58,407 pair additions, 560 group messages, max union table 4,096 entries, integers ≤ 9,795 bits, C ≤ 9,769 bits); independent checker 0.465–0.688 s; retained solve 0.93 s (λ = 1, dense, 12,688 multiplies) or 1.88 s to the refusal (λ ≤ 10^-2: discovery incl. the dense occupancy probe and the forecast); transfer 0.07–0.08 s. The proposed METHOD's cost on this instance is the candidate child (2.2–3.3 s each); the reference / diagnostic expense (4.4 s + 1.1 s) is separate. No speedup is claimed: there is no completed sparse retained run to compare, and the only completed dense runs (λ = 1) take 0.9 s.\n")
L.append("## 8. Unknowns and non-claims\n")
L.append("* D/Z, U/D and ρ for λ ≤ 10^-2: UNAVAILABLE (no reference, no R). The ρ LOWER bounds (≥ 0.0625 for G100 at λ ≤ 10^-4 and 0.87 at λ = 10^-2) already exceed the 0.01 target's allowance; for G10000 at λ ∈ {10^-6, 10^-2} the lower bound (≈ 0.0034 / 0.0032) does not exclude a pass by itself, but the identical 29-split schedule makes a comparable retained-channel inflation EXPECTED (not measured).\n* Whether the masked solve at λ ≤ 10^-4 would be admitted and run on the sparse route at a 600 s wall is an EXPECTATION from the original pair (forecast 248 s; support 4.4 s), untested here.\n* No statement about other instances, other K, other groupings or query-specific certificates follows; the theory's proofs are unaffected (the implementation agrees with them on every control).\n")
open(os.path.join(E, "REPORT.md"), "w").write("\n".join(L)); print("REPORT.md written (%d lines)" % len(L))
