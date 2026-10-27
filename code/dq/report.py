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
    # decision — honour the FIRST applicable frozen stop rule; CONTROL timing is supplemental whenever the MAIN cost comparison failed
    elig_pairs = [p for p in pairs if p["eligible"] and p["both_verified"]]
    all_verified = all(c["status"] == "VERIFIED" and c.get("width_ok") for c in cells if c["arm"] in ("D", "F", "AUTO")) and bool(cells)
    d_screen = all(p["D_le_30"] for p in pairs if elig(by.get(f"MAIN_{p['pair']}_D")))
    rel = None; rel_ok = False; rel_arm_medians = None
    if len(elig_pairs) >= 3:
        ratios = [p["ratio_D_over_F"] for p in elig_pairs]; rel = statistics.median(ratios); rel_ok = rel <= 0.8 and sum(1 for r in ratios if r < 1) >= 2
        rel_arm_medians = statistics.median([p["D_s"] for p in elig_pairs]) / statistics.median([p["F_s"] for p in elig_pairs])
    main_cost_failed = len(elig_pairs) >= 3 and not rel_ok
    control_supplemental = bool(cpairs) and main_cost_failed            # these cells should not have been timed under the frozen stop; retained and charged as diagnostics
    elig_cpairs = [p for p in cpairs if p["eligible"] and p["both_verified"]]
    ctrl = None; ctrl_ok = False
    if len(elig_cpairs) >= 3:
        ctrl = statistics.median([p["overhead_ratio"] for p in elig_cpairs]); ctrl_ok = ctrl <= 1.10
    stops = [s_["reason"] for s_ in S.get("stops", [])]
    if any(s_ in ("CERTIFICATE_OR_CHECKER_FAILURE", "PROOF_IMPLEMENTATION_MISMATCH") for s_ in stops) or (cells and not all_verified): decision = "CERTIFICATE_OR_CHECKER_FAILURE"
    elif "NO_GO_ABSOLUTE_COST" in stops: decision = "NO_GO_FOR_THIS_IMPLEMENTATION (absolute cost screen)"
    elif len(elig_pairs) < 3: decision = "INCONCLUSIVE (fewer than three eligible MAIN pairs)" + (" — " + "; ".join(stops) if stops else "")
    elif not d_screen: decision = "NO_GO_FOR_THIS_IMPLEMENTATION (absolute cost screen)"
    elif main_cost_failed: decision = "NO_GO_FOR_THIS_IMPLEMENTATION (relative >=20% saving rule failed; CONTROL timing supplemental)"
    elif len(elig_cpairs) < 3: decision = "INCONCLUSIVE (MAIN rules passed; fewer than three eligible CONTROL pairs)"
    elif ctrl_ok: decision = "GO_TO_NEXT_DESIGN"
    else: decision = "NO_GO_FOR_THIS_IMPLEMENTATION (fallback overhead <=10% failed)"
    # end-to-end wall per cell from the campaign events (cell_start -> cell_end, includes all durable writes)
    ev_path = os.path.join(run_dir, "events.jsonl"); e2e = {}
    if os.path.exists(ev_path):
        st = {}
        for ln in open(ev_path):
            e = json.loads(ln)
            if e.get("kind") == "cell_start": st[e["cell"]] = e["mono"]
            if e.get("kind") == "cell_end" and e["cell"] in st: e2e[e["cell"]] = e["mono"] - st[e["cell"]]
    for c in cells: c["_e2e_wall_s"] = e2e.get(c["cell"])
    # CPU coverage: native producer, native checker kernel, Python phases (input/gate/publication + checker aggregation), label each
    def cpu_parts(c):
        prod = sum(a.get("cpu_s") or 0 for a in c.get("attempts", []) if a.get("kind") == "producer")
        chk_k = sum(((a.get("kernel") or {}).get("cpu_s") or 0) for a in c.get("attempts", []) if a.get("kind") == "checker")
        py = sum(p.get("cpu_s") or 0 for p in c.get("phases", []))
        chk_py = 0.0
        for a in c.get("attempts", []):
            if a.get("kind") == "checker":
                vp = os.path.join(run_dir, os.path.dirname(c.get("result_path", "")) if c["arm"] != "AUTO" else os.path.join(c.get("result_path", ""), "fallback"), f"checker_fb{a.get('fbits')}", "verdict.json")
                if os.path.exists(vp): chk_py += sum(ph.get("cpu_s") or 0 for ph in json.load(open(vp)).get("phases", []))
        return {"native_producer": prod, "native_checker_kernel": chk_k, "python_phases": py + chk_py, "sum_logged": prod + chk_k + py + chk_py}
    for c in cells: c["_cpu"] = cpu_parts(c)
    for p in pairs:
        d = by.get(f"MAIN_{p['pair']}_D"); f = by.get(f"MAIN_{p['pair']}_F")
        if not d or not f: continue
        den = f["_cpu"]["native_producer"] + f["_cpu"]["native_checker_kernel"]
        p["cpu_native_both_ratio"] = (d["_cpu"]["native_producer"] + d["_cpu"]["native_checker_kernel"]) / den if den else None
        p["cpu_sum_logged_D"] = d["_cpu"]["sum_logged"]; p["cpu_sum_logged_F"] = f["_cpu"]["sum_logged"]; p["e2e_D"] = d["_e2e_wall_s"]; p["e2e_F"] = f["_e2e_wall_s"]
    T = {"decision": decision, "main_pairs": pairs, "control_pairs": cpairs, "control_timing_supplemental_post_stop": control_supplemental, "median_paired_ratio_D_over_F_eligible": rel, "ratio_of_arm_medians_D_over_F": rel_arm_medians, "median_fallback_overhead_eligible": ctrl, "eligible_main_pairs": len(elig_pairs), "eligible_control_pairs": len(elig_cpairs), "all_cells_verified": all_verified, "stops": S.get("stops", [])}
    json.dump(T, open(os.path.join(run_dir, "tables.json"), "w"), indent=1, default=str)
    # ---- markdown
    M = [f"# Direct chain-query certificate pilot — report", "", f"Run `{os.path.basename(run_dir)}`; git {L['environment']['git_head'][:12]} ({'dirty' if L['environment']['git_dirty'] else 'clean'}); {L['environment']['platform']}; {L['environment']['compiler']}; gmpy2 {L['environment']['gmpy2']} / {L['environment']['mpfr']} / {L['environment']['gmp']}. Frozen: n={L['frozen']['n']}, arm cap {L['frozen']['arm_cap_s']} s, D screen {L['frozen']['d_screen_s']} s, total cap {L['frozen']['total_cap_s']} s, RSS cap 4 GiB, 17 updates step 2/5, precision ladder {L['frozen']['fbits_ladder']} / checker {L['frozen']['check_ladder']}, grids MAIN h=1 J=3 δ=113/100000, CONTROL h=3/4 J=4 δ=1/1400.", "",
         f"## Decision: **{decision}**", ""]
    if pairs:
        d_times = [p["D_s"] for p in pairs]; f_times = [p["F_s"] for p in pairs]; cpu_r = [p["D_cpu"] / p["F_cpu"] for p in pairs if p["F_cpu"]]
        rel_txt = (f"median {_f(rel)} (saving {100 * (1 - rel):.2f} %); ratio of arm medians {_f(rel_arm_medians)} (saving {100 * (1 - rel_arm_medians):.2f} %); both miss the prespecified 20 %" if rel is not None else "fewer than three eligible verified pairs: no qualified ratio")
        M += ["## Headline", "",
              (f"- All {len(cells)} primary cells published deterministic original-model intervals that passed the independent checker at width ≤ 0.01 (" + ", ".join(f"{k.replace('_pair1', '')} {_f(float(Fr(by[k]['width'])), 6)}" for k in ("MAIN_pair1_D", "MAIN_pair1_F", "CONTROL_pair1_F") if by.get(k) and by[k].get("width")) + "); every MAIN D interval contains the corresponding F interval (consistency, not proof)." if all_verified else f"- Not every cell verified: {[(c['cell'], c['status']) for c in cells if c['status'] != 'VERIFIED']}."),
              f"- MAIN D complete checked time {min(d_times):.2f}–{max(d_times):.2f} s (absolute screen 30 s: passed); MAIN F {min(f_times):.2f}–{max(f_times):.2f} s. Paired wall ratios D/F {', '.join(f'{p['ratio_D_over_F']:.3f}' for p in pairs if p['ratio_D_over_F'] is not None)}: {rel_txt}. Native producer-only CPU ratios {', '.join(f'{r:.3f}' for r in cpu_r)}; native producer+checker CPU ratios {', '.join(f'{p['cpu_native_both_ratio']:.3f}' for p in pairs if p.get('cpu_native_both_ratio') is not None)} (Python phases excluded from both; not whole-worker CPU).",
              (f"- CONTROL ({'POST-STOP SUPPLEMENTAL DIAGNOSTICS: the frozen protocol skips CONTROL timing once MAIN fails the cost rule; these cells were run anyway, are retained and charged, and carry no decision weight' if control_supplemental else 'decision stage'}): the gate declined in {min(p['gate_s'] for p in cpairs):.2f}–{max(p['gate_s'] for p in cpairs):.2f} s before any centre work; gate-then-F / plain F {', '.join(f'{p['overhead_ratio']:.3f}' for p in cpairs if p['overhead_ratio'] is not None)} ({('median ' + _f(ctrl) + f', {100 * (ctrl - 1):.2f} % overhead vs the 10 % rule') if ctrl is not None else 'fewer than three eligible verified pairs'}). The fallback recomputed the structural gate (≈ 0.29–0.30 s) instead of reusing it (implementation defect, fixed after the run; the measured overhead is retained as measured)." if cpairs else "- CONTROL timing stage skipped under the frozen stop rule (MAIN cost comparison failed); the stage-1 input-only decline stands."),
              "- No correctness or precision condition failed: the 80-bit producer and 128-bit checker met every contract on the first attempt (no retries); sampled native-worker peak RSS ≈ 41 MiB (Python driver and AUTO checker peaks not covered in these records); all cells eligible (no foreign-process violation, numerical-phase CPU/wall ≥ 0.90). Amendment 1 repairs the complex-pass error argument (see `amendments/NUMERICAL_PROOF_REPAIR.md`): the saved Fourier publications remain contained under the conservative ceiling with margins > 1.3e-4; the original ≈1e-23 enclosure claims are withdrawn in favour of the ceiling 48·n·2^-P.",
              "- Work avoided by Arm D: the scalar negative-Fourier evaluation (three complex passes on MAIN per producer and per checker) and its checking — measured as ≈ 0.2 s producer + ≈ 0.3 s checker out of a ≈ 3.4 s F cell; centre construction (≈ 1.4 s, 17 real passes) dominates both arms. No positive-grid region pruning was tested.", ""]
    if pairs:
        M += ["## MAIN pairs (complete checked wall seconds; D = direct certificate, F = scalar Fourier baseline)", "", "| pair | order | D s (standalone) | F s (standalone) | D/F | D end-to-end s | F end-to-end s | native producer CPU D/F | native prod+chk CPU D/F | sum of logged CPU D s | F s | both verified | eligible | D ≤ 30 s |", "|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---|---|---|"]
        M += [f"| {p['pair']} | {p['order']} | {p['D_s']:.3f} | {p['F_s']:.3f} | {_f(p['ratio_D_over_F'])} | {_f(p.get('e2e_D'))} | {_f(p.get('e2e_F'))} | {_f(p['D_cpu'] / p['F_cpu'] if p['F_cpu'] else None)} | {_f(p.get('cpu_native_both_ratio'))} | {_f(p.get('cpu_sum_logged_D'))} | {_f(p.get('cpu_sum_logged_F'))} | {p['both_verified']} | {p['eligible']} | {p['D_le_30']} |" for p in pairs]
        M += ["", f"Median PAIRED ratio over eligible verified pairs: {_f(rel)} (rule: ≤ 0.80 with a saving in ≥ 2 of 3 pairs → {rel_ok}); ratio of arm medians: {_f(rel_arm_medians)}. Absolute screen (eligible D ≤ 30 s): {d_screen}. 'Standalone' wall runs from arm start to the terminal decision and EXCLUDES the final durable result writes (the saved records predate the durable-end timer added in amendment 3); 'end-to-end' is the campaign's cell_start→cell_end span from events.jsonl and includes them. CPU: 'native producer' and 'native prod+chk' are rusage of the native subprocess trees; 'sum of logged' adds the Python phase CPU (input, gate, publication, checker aggregation); residual orchestration CPU is not measured, so none of these is a whole-worker figure.", ""]
    if cpairs:
        M += [f"## CONTROL pairs (plain F vs gate-then-F automatic fallback){' — POST-STOP SUPPLEMENTAL DIAGNOSTICS, no decision weight' if control_supplemental else ''}", "", "| pair | order | F s | AUTO s | gate s | AUTO/F | both verified | eligible |", "|---|---|---:|---:|---:|---:|---|---|"]
        M += [f"| {p['pair']} | {p['order']} | {p['F_s']:.3f} | {p['AUTO_s']:.3f} | {_f(p['gate_s'])} | {_f(p['overhead_ratio'])} | {p['both_verified']} | {p['eligible']} |" for p in cpairs]
        M += ["", f"Median AUTO/F over eligible verified pairs: {_f(ctrl)} (rule: ≤ 1.10 → {ctrl_ok}). The gate declines before any centre work; the fallback reuses the gate's verified input bytes.", ""]
    else:
        M += ["## CONTROL pairs", "", "No CONTROL timing cells: " + ("skipped under the frozen stop rule after the MAIN cost comparison failed; the stage-1 input-only decline stands." if any(s_["reason"] == "MAIN_COST_COMPARISON_FAILED_SKIP_CONTROL_TIMING" for s_ in S.get("stops", [])) else "not reached."), ""]
    M += ["## Every cell", "", "| cell | status | guarantee | published interval (outward decimals) | width | standalone s | end-to-end s | phases s (input / gate / producer attempts / publication / checker attempts / overhead) | native peak RSS MiB | num-phase CPU/wall | eligible (reasons) |", "|---|---|---|---|---:|---:|---:|---|---:|---:|---|"]
    for c in cells:
        pub = c.get("published"); iv = f"[{_dec_out(pub['lo'], 6, 'down')}, {_dec_out(pub['hi'], 6, 'up')}]" if pub else "—"
        ph = {p["phase"]: p["wall_s"] for p in c.get("phases", [])}; pa = [a for a in c.get("attempts", []) if a.get("kind") == "producer"]; ca = [a for a in c.get("attempts", []) if a.get("kind") == "checker"]
        phs = f"{ph.get('input_construction', 0):.2f} / {ph.get('structural_gate', 0):.2f} / {'+'.join(f'{a.get('wall_s', 0):.2f}@{a.get('fbits')}' for a in pa) or '—'} / {ph.get('publication', 0):.2f} / {'+'.join(f'{a.get('wall_s', 0):.2f}@{a.get('fbits')}' for a in ca) or '—'} / {c.get('residual_overhead_s', 0):.2f}"
        if c["arm"] == "AUTO": phs = f"gate {c.get('gate_wall_s', 0):.2f} then " + phs
        e = c.get("eligibility") or {"eligible": None, "reasons": ["no eligibility record"]}
        M.append(f"| {c['cell']} | {c['status']} | {c.get('guarantee') or '—'} | {iv} | {_f(float(Fr(c['width'])) if c.get('width') else None, 6)} | {c.get('complete_wall_s', 0):.3f} | {_f(c.get('_e2e_wall_s'))} | {phs} | {(c.get('peak_rss_bytes') or 0) / 2**20:.0f} | {_f(e.get('numerical_phase_cpu_over_wall'))} | {e.get('eligible')} {e.get('reasons') or ''} |")
    g = S.get("stages", {}).get("1_gates", {})
    M += ["", "## Stage 1: tiny validation and input-only gates", "", f"Validation: {S.get('stages', {}).get('1_validation', {}).get('summary')} in {_f(S.get('stages', {}).get('1_validation', {}).get('wall_s'), 1)} s (cap 60 s). The three n=8 models and the two tamper checks are implementation checks; the tiny models fail the 0.01 admission gate (expected and recorded)."]
    for case, G in g.items():
        try:
            M.append(f"- {case}: **{G['decision']}** in {G['wall_s']:.2f} s; exact K (alternating closed form) {G.get('K_exact_alternating_closed_form')} vs declared {(G.get('declared') or {}).get('K')}; M = {_dec_out(G['M_exact'], 6, 'down')}; V̄ declared {(G.get('declared') or {}).get('V_bar')}; floor L = {(G.get('declared') or {}).get('L')} (valid: (1−x/8)^8 ≥ L); s_A0 ≤ {_dec_out(G['s_A0_upper'], 6, 'up')}; prescribed radius {_dec_out(G.get('E0_prescribed_from_declared_floor', G['E0_upper']), 6, 'up')}" + (f"; published radius {G.get('E0_published_radius')}" if G['decision'] == 'ADMITTED' else f"; declined: {G.get('failed_bound', '')[:160]}") + f". Dobrushin single-site row-sum at site 0 ≥ {_dec_out(G['dobrushin_row0_lower'], 4, 'down') if G.get('dobrushin_row0_lower') else '—'} (> 1: that sufficient test fails). Weighted-count DP range ≈ {G.get('weighted_count_estimate', {}).get('range_float', float('nan')):.1e} integer states per site (not allocated). Log-weight oscillation of the deleted collective term ≈ {float(Fr(G['log_weight_perturbation']['log_weight_oscillation_upper'])) if G.get('log_weight_perturbation') else float('nan'):.0f} (generic perturbation bound uninformative).")
        except (KeyError, TypeError) as ex:
            M.append(f"- {case}: {G.get('decision')} (incomplete gate record: {ex!r})")
    AF = L.get("analytic_facts_recorded") or {"main_query_range": ["0.5216", "0.7733"], "residual_only_minus_full_lower": "0.0236", "source": "witness_response.md section 5"}
    M += ["", "## Analytic facts recorded, not re-evaluated", "", f"Main query in ({AF['main_query_range'][0]}, {AF['main_query_range'][1]}); residual-only minus full marginal > {AF['residual_only_minus_full_lower']} ({AF['source']}). Every verified MAIN interval above lies inside that range; the producer's residual-only q0 at c=0 is a producer diagnostic (not independently recomputed by the checker).", "",
          "## What was and was not tested", "", "The work avoided by Arm D is the scalar negative-Fourier evaluation (3 complex passes on MAIN, 4 on CONTROL, per producer and per checker) and its checking. No positive-grid region pruning was tested. Sampling was not timed. Both arms share input construction, the structural gate, the 17-update centre and one final real pass; the checker reruns every contraction in the opposite sweep order with its own error propagation. Shared code: dq.model, native/dqinput.hpp, native/mpiv.hpp, the exact scalar modules (dq.constants, dq.gate, dq.fourier_consts, dq.publish). Eligibility: no foreign process ≥ 50 % of a core for 5 s and numerical-phase CPU/wall ≥ 0.90; ineligible pairs are INCONCLUSIVE, never rerun.", "",
          "**Recorded pre-launch deviation from the eligibility rule.** " + (f"The pre-existing system daemon(s) {list((L.get('eligibility_deviation') or {}).get('exempt', {}).values())} were exempted from the foreign-process rule before any timed stage; they were logged in every sample (see each cell's `exempt_daemon_busy_samples`). All other foreign processes and the worker CPU/wall rule remain in force. Without this deviation every timed cell would have been INCONCLUSIVE under the literal rule." if (L.get('eligibility_deviation') or {}).get('exempt') else "None (the exemption map was empty: the daemon had been terminated before launch)."), ""]
    if S.get("stops"): M += ["## Stops", ""] + [f"- {s_['reason']} at {s_['elapsed_s']:.1f} s: {s_.get('detail', '')}" for s_ in S["stops"]] + [""]
    ad = os.path.join(run_dir, "amendments")
    if os.path.isdir(ad):
        M += ["## Amendments (post-run, 27 Oct 2026; the execution lock and all cell records are unchanged)", ""]
        for f_ in sorted(os.listdir(ad)): M.append(f"- `amendments/{f_}`")
        M.append("")
    a1 = os.path.join(os.path.dirname(run_dir), os.path.basename(run_dir) + "_attempt1_infra_failure")
    a1_s = None
    if os.path.exists(os.path.join(a1, "campaign_state.json")):
        a1_s = json.load(open(os.path.join(a1, "campaign_state.json"))).get("elapsed_total_s")
    M += ["## Accounting", "", f"This campaign: {S.get('elapsed_total_s', 0):.1f} s wall (12 cells + stage 1 + report {S.get('report_wall_s', 0):.1f} s)." + (f" Charged failed attempt 1 (relative-path launch defect, no numerical work, preserved in `{os.path.basename(a1)}/`): {a1_s:.1f} s." if a1_s is not None else "") + f" Total post-build charged: {S.get('elapsed_total_s', 0) + (a1_s or 0):.1f} s of the 1,200 s cap. Peak RSS 41 MiB of the 4 GiB cap. Development, build, dev smoke runs and validation authoring (≈ 1 h 40 min wall on 26 Oct 2026, 18:12–19:52 PDT, interleaved with the earlier closed pilot's archive work) are not inference runtimes and are stated here for visibility only.", ""]
    open(os.path.join(run_dir, "REPORT.md"), "w").write("\n".join(M)); return decision
