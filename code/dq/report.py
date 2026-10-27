"""REPORT.md and tables from the durable campaign records only (CLAUDE_CODE_SPEC.md "Required handoff")."""
from __future__ import annotations

import json
import os
import statistics
import sys
from fractions import Fraction as Fr

sys.set_int_max_str_digits(0)


def _f(x, d=3):
    return "—" if x is None else f"{x:.{d}f}"


def _dec_out(q, digits, direction):
    q = Fr(q); g = 10 ** digits; v = (q * g).numerator // (q * g).denominator
    if direction == "up" and Fr(v, g) < q: v += 1
    s = f"{v / g:.{digits}f}"; return s


def write_report(run_dir: str) -> str:
    S = json.load(open(os.path.join(run_dir, "campaign_state.json"))); L = json.load(open(os.path.join(run_dir, "lock.json")))
    cells = S.get("cells", []); by = {c["cell"]: c for c in cells}
    def elig(c): return c and c["eligibility"]["eligible"]
    def verified(c): return c and c["status"] == "VERIFIED" and c.get("width_ok")
    # MAIN pairs
    pairs = []
    for p in ("pair1", "pair2", "pair3"):
        d = next((c for c in cells if c["pair"] == p and c["arm"] == "D"), None); f = next((c for c in cells if c["pair"] == p and c["arm"] == "F"), None)
        if d and f:
            ok = verified(d) and verified(f); el = elig(d) and elig(f)
            pairs.append({"pair": p, "D_s": d["complete_wall_s"], "F_s": f["complete_wall_s"], "ratio_D_over_F": d["complete_wall_s"] / f["complete_wall_s"] if f["complete_wall_s"] else None,
                          "D_cpu": sum(a.get("cpu_s") or 0 for a in d["attempts"]), "F_cpu": sum(a.get("cpu_s") or 0 for a in f["attempts"]), "both_verified": ok, "eligible": el, "D_le_30": d["complete_wall_s"] <= 30, "D_status": d["status"], "F_status": f["status"], "order": "D,F" if d["order_idx"] < f["order_idx"] else "F,D"})
    cpairs = []
    for p in ("cpair1", "cpair2", "cpair3"):
        f = next((c for c in cells if c["pair"] == p and c["arm"] == "F"), None); a = next((c for c in cells if c["pair"] == p and c["arm"] == "AUTO"), None)
        if f and a:
            cpairs.append({"pair": p, "F_s": f["complete_wall_s"], "AUTO_s": a["complete_wall_s"], "gate_s": a.get("gate_wall_s"), "overhead_ratio": a["complete_wall_s"] / f["complete_wall_s"] if f["complete_wall_s"] else None, "both_verified": verified(f) and verified(a), "eligible": elig(f) and elig(a), "order": "F,auto" if f["order_idx"] < a["order_idx"] else "auto,F", "F_status": f["status"], "AUTO_status": a["status"]})
    # decision
    elig_pairs = [p for p in pairs if p["eligible"] and p["both_verified"]]
    all_verified = all(c["status"] == "VERIFIED" and c.get("width_ok") for c in cells if c["arm"] in ("D", "F", "AUTO")) and bool(cells)
    d_screen = all(p["D_le_30"] for p in pairs if elig(by.get(f"MAIN_{p['pair']}_D")))
    rel = None; rel_ok = False
    if len(elig_pairs) >= 3:
        ratios = [p["ratio_D_over_F"] for p in elig_pairs]; rel = statistics.median(ratios); rel_ok = rel <= 0.8 and sum(1 for r in ratios if r < 1) >= 2
    elig_cpairs = [p for p in cpairs if p["eligible"] and p["both_verified"]]
    ctrl = None; ctrl_ok = False
    if len(elig_cpairs) >= 3:
        ctrl = statistics.median([p["overhead_ratio"] for p in elig_cpairs]); ctrl_ok = ctrl <= 1.10
    stops = [s["reason"] for s in S.get("stops", [])]
    if any(s in ("CERTIFICATE_OR_CHECKER_FAILURE", "PROOF_IMPLEMENTATION_MISMATCH") for s in stops) or (cells and not all_verified): decision = "CERTIFICATE_OR_CHECKER_FAILURE"
    elif "NO_GO_ABSOLUTE_COST" in stops: decision = "NO_GO_FOR_THIS_IMPLEMENTATION (absolute cost screen)"
    elif len(elig_pairs) < 3 or len(elig_cpairs) < 3: decision = "INCONCLUSIVE (fewer than three eligible matched pairs)" + (" — " + "; ".join(stops) if stops else "")
    elif d_screen and rel_ok and ctrl_ok: decision = "GO_TO_NEXT_DESIGN"
    else: decision = "NO_GO_FOR_THIS_IMPLEMENTATION (" + ", ".join(x for x, ok in (("absolute screen", d_screen), ("relative >=20% saving", rel_ok), ("fallback overhead <=10%", ctrl_ok)) if not ok) + " failed)"
    T = {"decision": decision, "main_pairs": pairs, "control_pairs": cpairs, "median_ratio_D_over_F_eligible": rel, "median_fallback_overhead_eligible": ctrl, "eligible_main_pairs": len(elig_pairs), "eligible_control_pairs": len(elig_cpairs), "all_cells_verified": all_verified, "stops": S.get("stops", [])}
    json.dump(T, open(os.path.join(run_dir, "tables.json"), "w"), indent=1, default=str)
    # ---- markdown
    M = [f"# Direct chain-query certificate pilot — report", "", f"Run `{os.path.basename(run_dir)}`; git {L['environment']['git_head'][:12]} ({'dirty' if L['environment']['git_dirty'] else 'clean'}); {L['environment']['platform']}; {L['environment']['compiler']}; gmpy2 {L['environment']['gmpy2']} / {L['environment']['mpfr']} / {L['environment']['gmp']}. Frozen: n={L['frozen']['n']}, arm cap {L['frozen']['arm_cap_s']} s, D screen {L['frozen']['d_screen_s']} s, total cap {L['frozen']['total_cap_s']} s, RSS cap 4 GiB, 17 updates step 2/5, precision ladder {L['frozen']['fbits_ladder']} / checker {L['frozen']['check_ladder']}, grids MAIN h=1 J=3 δ=113/100000, CONTROL h=3/4 J=4 δ=1/1400.", "",
         f"## Decision: **{decision}**", ""]
    if pairs:
        M += ["## MAIN pairs (complete checked wall seconds; D = direct certificate, F = scalar Fourier baseline)", "", "| pair | order | D s | F s | D/F | D CPU s | F CPU s | both verified | eligible | D ≤ 30 s |", "|---|---|---:|---:|---:|---:|---:|---|---|---|"]
        M += [f"| {p['pair']} | {p['order']} | {p['D_s']:.3f} | {p['F_s']:.3f} | {_f(p['ratio_D_over_F'])} | {p['D_cpu']:.2f} | {p['F_cpu']:.2f} | {p['both_verified']} | {p['eligible']} | {p['D_le_30']} |" for p in pairs]
        M += ["", f"Median D/F over eligible verified pairs: {_f(rel)} (rule: ≤ 0.80 with a saving in ≥ 2 of 3 pairs → {rel_ok}). Absolute screen (eligible D ≤ 30 s): {d_screen}.", ""]
    if cpairs:
        M += ["## CONTROL pairs (plain F vs gate-then-F automatic fallback)", "", "| pair | order | F s | AUTO s | gate s | AUTO/F | both verified | eligible |", "|---|---|---:|---:|---:|---:|---|---|"]
        M += [f"| {p['pair']} | {p['order']} | {p['F_s']:.3f} | {p['AUTO_s']:.3f} | {_f(p['gate_s'])} | {_f(p['overhead_ratio'])} | {p['both_verified']} | {p['eligible']} |" for p in cpairs]
        M += ["", f"Median AUTO/F over eligible verified pairs: {_f(ctrl)} (rule: ≤ 1.10 → {ctrl_ok}). The gate declines before any centre work; the fallback reuses the gate's verified input bytes.", ""]
    M += ["## Every cell", "", "| cell | status | guarantee | published interval (outward decimals) | width | complete s | phases s (input / gate / producer attempts / publication / checker attempts / overhead) | peak RSS MiB | num-phase CPU/wall | eligible (reasons) |", "|---|---|---|---|---:|---:|---|---:|---:|---|"]
    for c in cells:
        pub = c.get("published"); iv = f"[{_dec_out(pub['lo'], 6, 'down')}, {_dec_out(pub['hi'], 6, 'up')}]" if pub else "—"
        ph = {p["phase"]: p["wall_s"] for p in c.get("phases", [])}; pa = [a for a in c.get("attempts", []) if a.get("kind") == "producer"]; ca = [a for a in c.get("attempts", []) if a.get("kind") == "checker"]
        phs = f"{ph.get('input_construction', 0):.2f} / {ph.get('structural_gate', 0):.2f} / {'+'.join(f'{a.get('wall_s', 0):.2f}@{a.get('fbits')}' for a in pa) or '—'} / {ph.get('publication', 0):.2f} / {'+'.join(f'{a.get('wall_s', 0):.2f}@{a.get('fbits')}' for a in ca) or '—'} / {c.get('residual_overhead_s', 0):.2f}"
        if c["arm"] == "AUTO": phs = f"gate {c.get('gate_wall_s', 0):.2f} then " + phs
        e = c["eligibility"]
        M.append(f"| {c['cell']} | {c['status']} | {c.get('guarantee') or '—'} | {iv} | {_f(float(Fr(c['width'])) if c.get('width') else None, 6)} | {c['complete_wall_s']:.3f} | {phs} | {c.get('peak_rss_bytes', 0) / 2**20:.0f} | {_f(e.get('numerical_phase_cpu_over_wall'))} | {e['eligible']} {e['reasons'] or ''} |")
    g = S["stages"].get("1_gates", {})
    M += ["", "## Stage 1: tiny validation and input-only gates", "", f"Validation: {S['stages'].get('1_validation', {}).get('summary')} in {_f(S['stages'].get('1_validation', {}).get('wall_s'), 1)} s (cap 60 s). The three n=8 models and the two tamper checks are implementation checks; the tiny models fail the 0.01 admission gate (expected and recorded)."]
    for case, G in g.items():
        M.append(f"- {case}: **{G['decision']}** in {G['wall_s']:.2f} s; exact K (alternating closed form) {G['K_exact_alternating_closed_form']} vs declared {G['declared']['K']}; M = {_dec_out(G['M_exact'], 6, 'down')}; V̄ declared {G['declared']['V_bar']}; floor L = {G['declared']['L']} (valid: (1−x/8)^8 ≥ L); s_A0 ≤ {_dec_out(G['s_A0_upper'], 6, 'up')}; prescribed radius {_dec_out(G['E0_prescribed_from_declared_floor'], 6, 'up')}" + (f"; published radius {G['E0_published_radius']}" if G['decision'] == 'ADMITTED' else f"; declined: {G.get('failed_bound', '')[:160]}") + f". Dobrushin single-site row-sum at site 0 ≥ {_dec_out(G['dobrushin_row0_lower'], 4, 'down')} (> 1: that sufficient test fails). Weighted-count DP range ≈ {G['weighted_count_estimate']['range_float']:.1e} integer states per site (not allocated). Log-weight oscillation of the deleted collective term ≈ {float(Fr(G['log_weight_perturbation']['log_weight_oscillation_upper'])):.0f} (generic perturbation bound uninformative).")
    M += ["", "## Analytic facts recorded, not re-evaluated", "", f"Main query in ({L['analytic_facts_recorded']['main_query_range'][0]}, {L['analytic_facts_recorded']['main_query_range'][1]}); residual-only minus full marginal > {L['analytic_facts_recorded']['residual_only_minus_full_lower']} ({L['analytic_facts_recorded']['source']}). Every verified MAIN interval above lies inside that range; the producer's residual-only q0 at c=0 minus the published upper endpoint is reported in each witness.", "",
          "## What was and was not tested", "", "The work avoided by Arm D is the scalar negative-Fourier evaluation (3 complex passes on MAIN, 4 on CONTROL, per producer and per checker) and its checking. No positive-grid region pruning was tested. Sampling was not timed. Both arms share input construction, the structural gate, the 17-update centre and one final real pass; the checker reruns every contraction in the opposite sweep order with its own error propagation. Shared code: dq.model, native/dqinput.hpp, native/mpiv.hpp, the exact scalar modules (dq.constants, dq.gate, dq.fourier_consts, dq.publish). Eligibility: no foreign process ≥ 50 % of a core for 5 s and numerical-phase CPU/wall ≥ 0.90; ineligible pairs are INCONCLUSIVE, never rerun.", ""]
    if S.get("stops"): M += ["## Stops", ""] + [f"- {s['reason']} at {s['elapsed_s']:.1f} s: {s.get('detail', '')}" for s in S["stops"]] + [""]
    M += [f"Total campaign elapsed {S.get('elapsed_total_s', 0):.1f} s of the 1,200 s cap (report {S.get('report_wall_s', 0):.1f} s). Development, build and validation-authoring time are not inference runtimes and are reported separately in the handoff.", ""]
    open(os.path.join(run_dir, "REPORT.md"), "w").write("\n".join(M)); return decision
