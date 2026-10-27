"""Deterministic reporter for the normalization-free diagnostic. Reads only the durable records (state.json, lock.json, stage_b/*, stage_c/*,
control/*, validation/*/result.json, events.jsonl) and writes REPORT.md + tables.json. Accepts partial runs, validation failures, timeouts
and early stops; honours the first applicable stop; assigns no decision weight to anything after it. No timestamps are generated here."""
from __future__ import annotations
import sys
sys.set_int_max_str_digits(0)
import os, json, glob
from fractions import Fraction as Fr
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from nf.certs import dec, fr_str
from nf.ivpy import fx

def _j(p, default=None):
    try: return json.load(open(p))
    except Exception: return default

def _d(x, n=9):
    try: return dec(Fr(x), n)
    except Exception: return "n/a"

def _sci(x):
    """short scientific display of a tiny nonnegative rational width (display only; exact endpoints live in the records)"""
    try:
        x = Fr(x)
        if x == 0: return "0"
        e = 0
        while x < 1: x *= 10; e -= 1
        while x >= 10: x /= 10; e += 1
        return f"{dec(x, 3)}e{e}"
    except Exception: return "n/a"

def write_report(run_dir):
    R = os.path.abspath(run_dir); S = _j(os.path.join(R, "state.json"), {}); L = _j(os.path.join(R, "lock.json"), {}); W = _j(os.path.join(R, "stage_b", "witness.json")); V = _j(os.path.join(R, "stage_b", "checker_verdict.json")); CK = _j(os.path.join(R, "stage_b", "checker_kernel.json"))
    C = _j(os.path.join(R, "control", "control_gate.json")); MV = _j(os.path.join(R, "stage_c", "moment_verdict.json"))
    ev = [json.loads(l) for l in open(os.path.join(R, "events.jsonl"))] if os.path.exists(os.path.join(R, "events.jsonl")) else []
    outcome = S.get("outcome") or "NOT_FINISHED"; stops = S.get("stops", []); first = stops[0] if stops else None; stB = S.get("stages", {}).get("B", {}); stC = S.get("stages", {}).get("C", {}); stA = S.get("stages", {}).get("A", {})
    T = {"outcome": outcome, "first_stop": first, "stages": {k: v.get("status") for k, v in S.get("stages", {}).items()}}
    out = []; w = out.append
    w(f"# Normalization-free certificate clearance diagnostic — {outcome}\n")
    w("Frozen bounded diagnostic (CLAUDE_CODE_SPEC.md v1; spec zip sha256 662f3d5b…). One shared calculation on the exact rank-five witness `NF_WALSH5_MAIN_V1` (n = 262144, query index 131072, event X[131072] = +1, requested unclipped width 1/100) with two cheap certificate branches. This is a certificate-clearance result about **finite admission and implementation cost**. It is not an empirical proof of the theorem, not a speedup, and not evidence that the witness represents a useful workload. All timings are **raw-transfer implementation costs** on one machine; no comparative speed claim is made.\n")
    w("## Outcome and first applicable stop\n")
    if first: w(f"- **{outcome}** — stop `{first['code']}` in stage {first['stage']}: {first['reason']}")
    else: w(f"- **{outcome}** — no stop record (run did not finish; see state.json / reasons/).")
    for s in stops[1:]: w(f"- (later record, no decision weight) `{s['code']}` in stage {s['stage']}: {s['reason']}")
    w(f"- Stages: " + ", ".join(f"{k} = {v.get('status')}" for k, v in S.get("stages", {}).items()) + (" ; C = NOT_RUN" if "C" not in S.get("stages", {}) and outcome not in ("NOT_FINISHED",) else "") + "\n")
    # ---- Stage A
    w("## Stage A — preflight, tiny validation, geometry, control, lock\n")
    steps = stA.get("steps", {})
    for k in ("compile_nfchain", "compile_nfcheck", "tiny_validation"):
        if k in steps: w(f"- {k}: exit {steps[k].get('exit')}, wall {steps[k].get('wall_s', 0):.2f} s, CPU {steps[k].get('cpu_s', 0):.2f} s" + (f", killed: {steps[k]['kill']}" if steps[k].get("kill") else ""))
    vals = sorted(glob.glob(os.path.join(R, "validation", "*", "result.json")))
    if vals:
        w("- Tiny fixtures vs 256-bit enumeration (all singletons, projected means/gradient, M, pinned answers; certificate publications checked against the enumerated target where hypotheses hold):")
        for p in vals:
            r = _j(p, {}); name = r.get("fixture") or os.path.basename(os.path.dirname(p))
            if "fixture" in r: w(f"  - {name}: all_ok = {r.get('all_ok')}, states {r.get('enumerated_states')}, nfchain q width {_sci(r.get('nfchain_q_width', 0))}, nfchain M width {_sci(r.get('nfchain_M_width', 0))}, nfcheck q width {_sci(r.get('nfcheck_q_width', 0))}" + (f"; note: {r['note']}" if r.get("note") else ""))
            else: w(f"  - rejections: all_ok = {r.get('all_ok')}; " + ", ".join(f"{k}: {v.get('verdict')}" for k, v in r.items() if isinstance(v, dict) and "verdict" in v and k != "positive_control") + f"; stage C controls: {r.get('stage_c_positive_control')}/{r.get('stage_c_width_miss_is_precision_inconclusive')}/{r.get('stage_c_containment_failure_is_checking_failure')}")
    g = steps.get("main_geometry", {})
    if g: w(f"- MAIN geometry verified from the generated entries (Python regeneration): all_ok = {g.get('all_ok')} — AAᵀ = I/4: {g.get('AAt_quarter_identity')}, α² = 5/2²⁰: {g.get('alpha2_5_over_2^20')}, τ 4/5 & 1/10: {g.get('tau_strong_4/5_weak_1/10')}, K = 99/46: {g.get('K_99/46')}, V = 495/184: {g.get('V_495/184')}, block row sum ≤ 1/5: {g.get('block_row_sum_le_1/5')}, pair columns equal (D_b = 4α): {g.get('block_diameter_le_4alpha_pair_columns_equal')}, loading types {g.get('loading_types')}, contiguous segments {g.get('contiguous_segments')}. Canonical input sha256 {str(g.get('canonical_sha256'))[:16]}…; logical expanded size {g.get('logical_expanded_bytes', 0):,} bytes (formula module {g.get('formula_bytes', 0):,} bytes); Python geometry wall {g.get('wall_s', 0):.2f} s.")
    gb = steps.get("generator_binding", {})
    if gb: w("- Generator binding: " + "; ".join(f"{k} regeneration sha256 matches = {v.get('matches_python_canonical')} ({v.get('wall_s', 0):.2f} s)" for k, v in gb.items()))
    if C: w(f"- Cheap-rejection CONTROL `{C['case_id']}` ({C['definition']}): uniform NEW bound at residual 0 → R_new ∈ [{_d(C['R_new_enclosure'][0])}, {_d(C['R_new_enclosure'][1])}], ideal padded width ∈ [{_d(C['ideal_padded_width_enclosure'][0])}, {_d(C['ideal_padded_width_enclosure'][1])}] → **{C['classification']}** before any center evaluation. Input validation shared with MAIN; additional gate cost {C['additional_gate_cost']['wall_s']*1000:.1f} ms wall. Not claimed: {', '.join(C['not_claimed'])}.")
    w("")
    # ---- Stage B
    w("## Stage B — common center, residual query, both cheap certificates, independent check\n")
    if stB:
        w("| update | center (2⁻⁶⁴ grid) | residual² upper (Σ max|g_j|²) | ≤ 1/256 | wall s | CPU/wall | q width |"); w("|---:|---|---|---|---:|---:|---|")
        for e in stB.get("center_evaluations", []):
            w(f"| {e['update']} | {', '.join(_d(x, 6) for x in e['center'])} | {_d(e['residual_sq_upper'], 10)} | {e['residual_ok']} | {e['wall_s']:.2f} | {e.get('cpu_over_wall') or 0:.3f} | {_sci(e.get('q_width', 0))} |")
        T["center_evaluations"] = stB.get("center_evaluations")
    if W:
        ql, qh = fx(W["q_query"][0]), fx(W["q_query"][1]); w(f"\n- Residual query at the stored center ({W['updates_used']} updates used of ≤ 6): q ∈ [{dec(ql, 12)}, {dec(qh, 12)}], width {_sci(qh-ql)} (≤ 1/8000 required); exact midpoint q̂ = {dec(Fr(W['qhat']), 12)}.")
        w(f"- Residual (producer): Σ max|g_j|² = {_d(W['residual_sq_upper'], 12)} ≤ 1/256; M_uniform = V + r² = {_d(W['M_uniform'], 12)}; s_query ∈ [{_d(W['s_query'][0], 9)}, {_d(W['s_query'][1], 9)}] (finite-path recurrence; diagnostic cross-check K·α_upper = {_d(Fr(99, 46) * Fr(W['alpha_query'][1]), 9)}); α_query ∈ [{_d(W['alpha_query'][0], 9)}, {_d(W['alpha_query'][1], 9)}].")
        for nm in ("old", "new"):
            p = W["publication"][nm]; cc = stB.get("certificates", {}).get(nm, {}); iw = stB.get("ideal_width_enclosures", {}).get(nm, ["?", "?"])
            w(f"- **{nm.upper()} certificate**: R ∈ [{_d(p['R_lower'], 9)}, {_d(p['R_upper'], 9)}]; published unclipped [{_d(p['unclipped'][0], 9)}, {_d(p['unclipped'][1], 9)}] width **{_d(p['unclipped_width'], 9)}**; clipped [{_d(p['clipped'][0], 9)}, {_d(p['clipped'][1], 9)}]; ideal padded width enclosure [{_d(iw[0], 9)}, {_d(iw[1], 9)}] vs 1/100 → **{cc.get('status')}** ({cc.get('reason')}).")
        T["stage_b"] = {"q": [str(ql), str(qh)], "qhat": W["qhat"], "residual_sq_upper": W["residual_sq_upper"], "M_uniform": W["M_uniform"], "s_query": W["s_query"], "alpha_query": W["alpha_query"], "publications": W["publication"], "certificates": stB.get("certificates"), "ideal_width_enclosures": stB.get("ideal_width_enclosures")}
    if V:
        cr = stB.get("checker_run", {}); w(f"- Independent checker (192 bits, stored-backward/forward-sweep kernel, fresh regeneration sha256 match = {V['checks'].get('generator_hash_matches_lock')}): **{V['verdict']}**" + (f", failed: {V['failed_checks']}" if V["failed_checks"] else f"; {len(V['checks'])} named checks passed") + f"; wall {cr.get('wall_s', 0):.2f} s, CPU/wall {cr.get('cpu_over_wall') or 0:.3f}, peak RSS {cr.get('peak_rss', 0)/2**20:.0f} MiB.")
        d = V.get("detail", {}).get("checker_recomputed", {})
        if d: w(f"  - checker's own residual² {_d(d.get('residual_sq_upper'), 12)}, q ∈ [{_d(d['q'][0], 12)}, {_d(d['q'][1], 12)}], s ∈ [{_d(d['s'][0], 9)}, {_d(d['s'][1], 9)}], M_uniform(checker residual) {_d(d['M_uniform'], 12)}; old enclosure [{_d(d['old']['checker_enclosure'][0], 9)}, {_d(d['old']['checker_enclosure'][1], 9)}], new enclosure [{_d(d['new']['checker_enclosure'][0], 9)}, {_d(d['new']['checker_enclosure'][1], 9)}] — both required inside the retained UNCLIPPED publications.")
        T["checker"] = {"verdict": V["verdict"], "failed": V["failed_checks"], "recomputed": d}
    if not stB: w("Stage B did not run (see Stage A / reasons/).")
    w("")
    # ---- Stage C
    w("## Stage C — conditional actual-moment refinement\n")
    if stC.get("status") == "NOT_RUN" or not stC: w(f"NOT_RUN — {stC.get('reason', 'Stage B stopped before it (frozen protocol)')}. **No actual moments were computed for MAIN**; the moment kernels were exercised only on the tiny fixtures in Stage A.")
    else:
        w(f"- status {stC.get('status')}; producer moment pass wall {stC.get('producer_run', {}).get('wall_s', 0):.2f} s, checker covariance pass wall {stC.get('checker_run', {}).get('wall_s', 0):.2f} s; moment verdict **{stC.get('moment_verdict')}**")
        md = stC.get("moment_detail", {}); rf = stC.get("refined", {})
        if md: w(f"- raw producer M [{_d(md.get('producer_raw', ['?','?'])[0], 12)}, {_d(md.get('producer_raw', ['?','?'])[1], 12)}] (width {_d(md.get('producer_width'), 15)}), guarded [{_d(md.get('producer_guarded', ['?','?'])[0], 12)}, {_d(md.get('producer_guarded', ['?','?'])[1], 12)}]; checker M [{_d(md.get('checker_raw', ['?','?'])[0], 12)}, {_d(md.get('checker_raw', ['?','?'])[1], 12)}] (width {_d(md.get('checker_width'), 15)})")
        if rf:
            w(f"- selected upper M: {rf.get('selection')} = {_d(rf.get('M_upper_selected'), 12)}; lower M for ideal widths (checker lower) = {_d(rf.get('M_lower_for_ideal_widths'), 12)}")
            for nm in ("old", "new"): c2 = rf["certificates"][nm]; p2 = rf["publications"][nm]; w(f"- **{nm.upper()} (refined)**: published unclipped width {_d(p2['unclipped_width'], 9)}, ideal padded width enclosure [{_d(c2['ideal_padded_width_enclosure'][0], 9)}, {_d(c2['ideal_padded_width_enclosure'][1], 9)}] → **{c2['status']}**")
        T["stage_c"] = stC
    w("")
    # ---- costs
    w("## Complete costs (primary subtotal; raw-transfer implementation costs, one machine)\n")
    cs = S.get("costs", {}); subs = [e for e in ev if e.get("kind") == "subcall_terminal"]
    w("| phase | stage | wall s | CPU s | CPU/wall | peak RSS MiB | exit / kill |"); w("|---|---|---:|---:|---:|---:|---|")
    tot_w = 0.0
    for e in subs:
        tot_w += e.get("wall_s", 0); w(f"| {e.get('phase')}{(' #'+str(e['update'])) if 'update' in e else ''} | {e.get('stage')} | {e.get('wall_s', 0):.3f} | {e.get('cpu_s', 0):.3f} | {(e.get('cpu_over_wall') or 0):.3f} | {e.get('peak_rss_bytes', 0)/2**20:.0f} | {e.get('exit_code')}{(' / '+e['kill_reason']) if e.get('kill_reason') else ''} |")
    w(f"\n- Subprocess wall subtotal (no double counting; nested children are inside their parent's interval): **{tot_w:.2f} s**; charged commands + Python phases: **{cs.get('charged_commands_and_phases_s', 0):.2f} s** of the 600 s cumulative cap; small validation {cs.get('small_validation_s', 0):.2f} s of 60 s; Stage B elapsed {stB.get('elapsed_s', 0):.2f} s of 120 s" + (f"; Stage C elapsed {stC.get('elapsed_s', 0):.2f} s of 120 s" if stC.get("elapsed_s") else "") + f"; driver elapsed {cs.get('driver_elapsed_s', 0):.2f} s; children CPU {cs.get('children_cpu_s', 0):.2f} s; driver CPU {cs.get('driver_cpu_s', 0):.2f} s; children max RSS (rusage) {cs.get('children_maxrss_bytes_rusage', 0)/2**20:.0f} MiB. Cap violations: {cs.get('cap_violations')}.")
    w(f"- Machine load average at start {S.get('loadavg_at_start') or L.get('environment', {}).get('loadavg_1_5_15')} / at end {S.get('loadavg_at_end')}; foreign-CPU contention violations: {len(S.get('contention', {}).get('violations', []))} → timing contamination flag = **{S.get('timing_contamination')}**.")
    w("- Historical comparison (labelled, not a target met): the earlier 30-second complete-time target is NOT addressed by passing the 120 s diagnostic caps. " + (f"This construction's Stage B took {stB.get('elapsed_s', 0):.1f} s" + (" — more than 30 s." if stB.get("elapsed_s", 0) > 30 else " on this machine; machine differences and unoptimised code prevent a direct historical speed comparison.") if stB.get("elapsed_s") else ""))
    w("- Charged but not in this subtotal: report generation, archive checking and later replay — see `CLOSEOUT_RECEIPT.jsonl` (append-only). The implementation task wall time (first task record to archive) is also recorded there.\n")
    wc = W["counts"] if W else {}
    if wc: w(f"- Operation counts (producer, one evaluation): sites {wc.get('sites'):,}, exp calls {wc.get('exp_calls'):,}, reciprocals {wc.get('reciprocals'):,}, directed interval ops {wc.get('interval_ops'):,}; the precision contract's loose ceilings are 524,288 exp calls and 33,554,432 fixed-precision ops per pass — actual counts are reported, not the ceilings.\n")
    # ---- unknowns
    w("## What remains unknown / not established\n")
    w("- No speedup, wall-time affordability, novelty, input adaptivity or inference-hardness claim follows from this diagnostic. The 30 s historical target was not addressed.")
    w("- Only the two frozen sufficient tests were evaluated. A DECLINE (if any) concerns the prescribed test, not every old refinement or sharper tilt-specific bound.")
    if outcome == "OLD_CHEAP_ALREADY_SUFFICIENT": w("- The witness establishes **no additional integration avoidance at width 0.01**: the sharpened old certificate already admits the query. A tighter new interval is accuracy headroom only. Actual moments (Stage C) were not computed; whether the new certificate would separate on a different witness is unknown.")
    if outcome.startswith("INCONCLUSIVE") or outcome == "NUMERICAL_OR_BOUNDARY_INCONCLUSIVE": w("- The result is a named inconclusive stop; it is not a mathematical contradiction and grants no favourable admission or speed claim.")
    w("- Named specialist opportunities preserved (mandatory before any broader performance claim; not built here): sixteen contiguous loading patterns and a geometric unary progression; certified piecewise-constant field approximation for residual gradients; type/count or representation reductions and query-sensitive mode deletion; sharper old response bounds under justified tilt-specific information. The Fourier marker-ratio stopping rule remains the future deterministic comparator; this diagnostic evaluated zero Fourier frequencies and zero positive-grid node masses; sampling was not run.")
    w("- The previous implementation NO_GO, H4 and the centering pilot are unchanged; no historical threshold was altered.\n")
    w("## Records\n"); w("`lock.json` (frozen before Stage B), `events.jsonl` (heartbeats ≥ 1 Hz during native work, contention samples, stops), `state.json`, `stage_b/{witness.json, checker_kernel.json, checker_verdict.json, producer_eval*.json, progress.jsonl}`, `stage_c/` (if run), `control/control_gate.json`, `validation/*/result.json`, `reasons/*.txt`, `input_main.txt` (the exact 19,841,034-byte canonical NFCHAIN-V1 input actually bound; kernels regenerate from the formula and their dumps hash to it), `NUMERICAL_CONTRACT.md`, `REPRODUCE.md`, `CLOSEOUT_RECEIPT.jsonl`.")
    open(os.path.join(R, "REPORT.md"), "w").write("\n".join(out) + "\n"); json.dump(T, open(os.path.join(R, "tables.json"), "w"), indent=1, default=str, sort_keys=True); return outcome

if __name__ == "__main__": print(write_report(sys.argv[1]))
