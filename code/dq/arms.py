"""Arm runners (CLAUDE_CODE_SPEC.md "Arm D and automatic fallback", "Arm F with the sharp baseline").  Each arm runs standalone in one
process with its complete input + gate + centre construction charged; the only reuse is inside the arm.  Precision ladder: producer 80
fractional bits, one whole-attempt retry at 128 if a certified numerical contract fails; checker 128 then 192.  Every attempt is charged."""
from __future__ import annotations

import sys
sys.set_int_max_str_digits(0)

import hashlib
import json
import os
import time
from fractions import Fraction as Fr

from dq.model import Model, parse_canonical
from dq.gate import response_gate, PAD_NUM, PAD_PUB, TARGET_RADIUS, RESIDUAL_REQ
from dq.fourier_consts import GRIDS, E_NUM, PAD_NUM_F, PAD_PUB_F, verify_declared_delta
from dq.publish import fx, publish_direct, marker_ratio
from dq.supervisor import run_native, PhaseClock, Journal
from dq.checker import check_arm, Q0_RAW_ERROR

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DQCHAIN = os.path.join(ROOT, "build", "dqchain")
STEPS, STEP = 17, "2/5"
GRAD_ERR_BUDGET = Fr(1, 4096)        # (gradient error + update rounding)/step per update


def sha_file(p):
    return hashlib.sha256(open(p, "rb").read()).hexdigest()


def _write(path, obj):
    tmp = path + ".tmp"
    with open(tmp, "w") as f:
        json.dump(obj, f, indent=1, default=str); f.flush(); os.fsync(f.fileno())
    os.replace(tmp, path)


def _producer_contracts(P: dict, arm: str) -> list:
    """Certified numerical contracts the producer output must meet (from its own enclosure widths); failures -> retry/NUMERIC_CONTRACT_FAILED."""
    bad = []
    q = (fx(P["final"]["q0"][0]), fx(P["final"]["q0"][1]))
    if (q[1] - q[0]) / 2 > Q0_RAW_ERROR: bad.append("q0 raw error > 1e-7")
    for it in P["center"]["iterations"]:
        hw = fx(it["grad_halfwidth_upper"])
        # update rounding to 2^-64 contributes <= 2^-65 / step; gradient half-width is the gradient error
        if hw + Fr(1, 2 ** 65) / Fr(STEP) > GRAD_ERR_BUDGET: bad.append(f"iteration {it['iter']}: gradient error + rounding/step > 1/4096")
    if fx(P["final"]["residual_abs"][1]) >= RESIDUAL_REQ: bad.append("residual upper bound not below the witness 1/8")
    if arm == "F":
        for key in ("Ghat_plus", "Ghat_minus"):
            g = (fx(P["fourier"][key][0]), fx(P["fourier"][key][1]))
            if (g[1] - g[0]) / 2 > E_NUM: bad.append(f"{key} arithmetic error > 1/400000")
    return bad


def run_arm(arm: str, case: str, n: int, out_dir: str, deadline_s: float = 90.0, rss_cap: int = 4 << 30, evidence=None, monitor=None, fbits_ladder=(80, 128), check_ladder=(128, 192), pair_tag=None, reuse_input: str | None = None) -> dict:
    """Complete standalone arm: input construction + hash, gate, producer (precision ladder), publication, independent checker (ladder)."""
    os.makedirs(out_dir, exist_ok=True)
    J = Journal(os.path.join(out_dir, "events.jsonl")); T0 = time.monotonic()
    R = {"arm": arm, "case": case, "n": n, "pair_tag": pair_tag, "deadline_s": deadline_s, "phases": [], "attempts": [], "status": None}
    def remaining(): return deadline_s - (time.monotonic() - T0)
    def finish(status, **k):
        R["status"] = status; R.update(k); R["complete_wall_s"] = time.monotonic() - T0
        R["phase_sum_s"] = sum(p["wall_s"] for p in R["phases"]) + sum(a.get("wall_s", 0.0) for a in R["attempts"])
        R["residual_overhead_s"] = R["complete_wall_s"] - R["phase_sum_s"]
        J.write({"kind": "arm_terminal", "status": status, "complete_wall_s": R["complete_wall_s"]}); J.close(); _write(os.path.join(out_dir, "result.json"), R); return R
    J.write({"kind": "arm_start", "arm": arm, "case": case, "n": n})
    # --- input construction and canonical bytes (charged)
    pc = PhaseClock("input_construction")
    inp = os.path.join(out_dir, "input.txt")
    if reuse_input:                           # automatic fallback: reuse the already-verified canonical bytes from the declined gate (charged there)
        import shutil; shutil.copy(reuse_input, inp); m = parse_canonical(inp); input_sha = m.sha256(); R["input_reused_from"] = reuse_input
    else:
        m = Model(n, case, evidence); input_sha = m.write(inp); parse_canonical(inp)       # self-verification of the written bytes against the formulas
    R["input_sha256"] = input_sha; R["input_bytes"] = os.path.getsize(inp); R["phases"].append(pc.stop()); J.write({"kind": "phase", **R["phases"][-1], "input_sha256": input_sha})
    # --- input-only structural gate (both arms run it: D needs it for admission; F records it and uses V_bar for the analytic radius check)
    pc = PhaseClock("structural_gate"); G = response_gate(m, bits=128); R["gate"] = G; R["phases"].append(pc.stop()); J.write({"kind": "phase", **R["phases"][-1], "gate_decision": G["decision"], "E0_upper": G["E0_upper"]})
    if arm == "D" and G["decision"] != "ADMITTED":
        return finish("CERTIFICATE_DECLINED", declined_reason=G["failed_bound"], fallback="F")
    # --- producer with precision ladder
    P = None; grid = GRIDS[case] if arm == "F" else None
    for fbits in fbits_ladder:
        if remaining() <= 1: return finish("DEADLINE_BEFORE_PRODUCER")
        adir = os.path.join(out_dir, f"producer_fb{fbits}"); os.makedirs(adir, exist_ok=True); prog = os.path.join(adir, "progress.txt"); outp = os.path.join(adir, "producer.json")
        cmd = [DQCHAIN, inp, outp, "--mode", arm, "--fbits", str(fbits), "--steps", str(STEPS), "--step", STEP, "--progress", prog]
        if arm == "F": cmd += ["--freq-h", str(grid["h"]), "--J", str(grid["J"])]
        rec = run_native(cmd, adir, J, remaining(), rss_cap, {"phase": "producer", "arm": arm, "fbits": fbits}, progress_path=prog, monitor=monitor)
        att = {"kind": "producer", "fbits": fbits, **{k: rec.get(k) for k in ("exit_code", "kill_reason", "wall_s", "cpu_s", "cpu_over_wall", "peak_rss_bytes")}}
        if rec["exit_code"] != 0:
            att["outcome"] = "KILLED_" + str(rec["kill_reason"]).upper() if rec["kill_reason"] else f"EXIT_{rec['exit_code']}"; R["attempts"].append(att)
            if rec["kill_reason"]: return finish("DEADLINE_DURING_PRODUCER" if rec["kill_reason"] == "deadline" else "MEMORY_CAP")
            return finish("PRODUCER_FAILED")
        Pc = json.load(open(outp)); bad = _producer_contracts(Pc, arm); att["contract_failures"] = bad; att["outcome"] = "CONTRACTS_OK" if not bad else "NUMERIC_CONTRACT_FAILED"
        att["passes"] = Pc["passes"]; att["native_phases"] = {"center": Pc["center"]["wall_s"], "final_real": Pc["final"]["wall_s"], "fourier": Pc.get("fourier", {}).get("wall_s")}
        R["attempts"].append(att); J.write({"kind": "producer_attempt", **att})
        if not bad: P = Pc; R["producer_fbits"] = fbits; R["producer_path"] = outp; break
    if P is None: return finish("NUMERIC_CONTRACT_FAILED")
    # --- publication (exact, charged)
    pc = PhaseClock("publication")
    q = (fx(P["final"]["q0"][0]), fx(P["final"]["q0"][1])); rabs = fx(P["final"]["residual_abs"][1])
    W = {"n": n, "query": m.query, "evidence": {str(k): v for k, v in m.evidence.items()}, "input_sha256": input_sha, "case": case, "arm": arm, "gate": G,
         "center": {"c": P["center"]["c"], "grid": "2^-64", "steps": STEPS, "step": STEP, "fbits": R["producer_fbits"], "mpfr_prec": P["mpfr_prec"], "iterations": P["center"]["iterations"]},
         "final": {"q0": P["final"]["q0"], "residual": P["final"]["residual"], "residual_abs": P["final"]["residual_abs"], "residual_witness": str(RESIDUAL_REQ), "q0_raw_error_requirement": str(Q0_RAW_ERROR)},
         "q0_residual_only_c0": P["q0_residual_only_c0"]}
    if arm == "D":
        pub = publish_direct(q[0], q[1], Fr(G["E0_published_radius"]), PAD_NUM); pub.update({"intrinsic_radius": G["E0_published_radius"], "intrinsic_radius_source": "declared frozen constant 3/800 (input-derived sharper bound recorded in gate.E0_input_derived_sharper, not used)", "pad_numerical": str(PAD_NUM), "pad_publication": str(PAD_PUB)})
        W["published"] = pub; W["fourier"] = None
    else:
        dd = verify_declared_delta(case, Fr(G["V_bar"]))
        eta = grid["delta_declared"] + PAD_NUM_F
        GP = (fx(P["fourier"]["Ghat_plus"][0]), fx(P["fourier"]["Ghat_plus"][1])); GM = (fx(P["fourier"]["Ghat_minus"][0]), fx(P["fourier"]["Ghat_minus"][1]))
        pub = marker_ratio(GP[0], GP[1], GM[0], GM[1], eta); pub.update({"pad_numerical": str(PAD_NUM_F), "pad_publication": str(PAD_PUB_F)})
        W["published"] = pub
        W["fourier"] = {"h": str(grid["h"]), "J": grid["J"], "delta_declared": str(grid["delta_declared"]), "delta_recomputed_from_input": dd, "pad_numerical": str(PAD_NUM_F), "E_NUM": str(E_NUM),
                        "Ghat_plus": P["fourier"]["Ghat_plus"], "Ghat_minus": P["fourier"]["Ghat_minus"], "prefactor": P["fourier"]["prefactor"], "frequencies": P["fourier"]["frequencies"], "zero_frequency": "from the common real pass: phi_+(0) = q0, phi_-(0) = 1 - q0; conjugates paired (weight 2), not recomputed"}
    W["sha256_inputs"] = {"producer_json": sha_file(R["producer_path"])}
    wpath = os.path.join(out_dir, "witness.json"); _write(wpath, W); R["witness_path"] = wpath; R["witness_sha256"] = sha_file(wpath)
    R["published"] = pub; R["phases"].append(pc.stop()); J.write({"kind": "phase", **R["phases"][-1], "published": pub})
    # --- independent checker with its own ladder
    verdict = None
    for cb in check_ladder:
        if remaining() <= 1: return finish("DEADLINE_BEFORE_CHECK", published=pub)
        cdir = os.path.join(out_dir, f"checker_fb{cb}"); os.makedirs(cdir, exist_ok=True)
        t = time.monotonic()
        try:
            V = check_arm(arm, inp, W, cdir, J, remaining(), rss_cap, cb, monitor=monitor, progress_path=os.path.join(cdir, "checker_progress.txt"))
        except Exception as e:  # noqa: BLE001
            import traceback
            V = {"verdict": "CHECKER_EXCEPTION", "reason": repr(e), "traceback": traceback.format_exc()[-3000:]}
        V["wall_s"] = time.monotonic() - t; V["fbits"] = cb; _write(os.path.join(cdir, "verdict.json"), V)
        R["attempts"].append({"kind": "checker", "fbits": cb, "wall_s": V["wall_s"], "verdict": V["verdict"], "failed_checks": V.get("failed_checks"), "kernel": V.get("kernel")})
        J.write({"kind": "checker_attempt", "fbits": cb, "verdict": V["verdict"], "failed": V.get("failed_checks"), "wall_s": V["wall_s"]})
        verdict = V
        if V["verdict"] == "VERIFIED": break
        if V["verdict"] == "REJECTED" and not any("raw_error" in f or "arithmetic_error" in f for f in (V.get("failed_checks") or [])): break   # a non-precision rejection is final
    R["checker"] = {k: verdict.get(k) for k in ("verdict", "failed_checks", "fbits", "wall_s", "independent_enclosure", "kernel", "reason")}
    if verdict["verdict"] == "VERIFIED":
        return finish("VERIFIED", guarantee="DETERMINISTIC_ORIGINAL_MODEL_INTERVAL", width=pub["width"], width_ok=Fr(pub["width"]) <= Fr(1, 100))
    if verdict["verdict"] == "REJECTED": return finish("CERTIFICATE_OR_CHECKER_FAILURE")
    return finish("CHECKER_INCOMPLETE")
