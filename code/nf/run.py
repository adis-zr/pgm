"""Driver v2 (closeout amendment 1; v1 = the version hashed in runs/nf_diag_2026-10-26/lock.json executed the recorded run) for the bounded normalization-free certificate clearance diagnostic (CLAUDE_CODE_SPEC.md v1). Stages A → B → (C), first applicable
stop, external deadlines, durable records. Usage: python -m nf.run --run-dir <abs path>  (the run dir may already hold the TASK_START record)."""
from __future__ import annotations
import sys
sys.set_int_max_str_digits(0)
import os, json, time, hashlib, subprocess, platform, resource, argparse, shutil
from fractions import Fraction as Fr
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from dq.supervisor import Journal, ContentionMonitor, run_native, PhaseClock, now_iso
from nf.model import main_walsh5, verify_main_geometry
from nf import certs
from nf.check import verify_stage_b, verify_stage_c, independent_V
from nf.validate import round_grid, STEP
from nf.ivpy import fx

CODE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CAPS = {"implementation_wall_s": 5400, "compile_or_validation_cmd_s": 120, "small_validation_cumulative_s": 60, "stage_b_s": 120, "stage_c_s": 120, "all_commands_cumulative_s": 600, "rss_cap_bytes": 4 << 30, "threads": 1}
FROZEN = {"producer_prec": 128, "checker_prec": 192, "reference_prec": 256, "center_grid_bits": 64, "center_tie_rule": "ties round toward +infinity", "step": "368/467", "max_updates": 6,
          "residual_sq_max": "1/256", "center_norm_max": "257", "tilted_field_abs_max": "2 (strict)", "q_width_max": "1/8000", "delta_num": "1/16000", "delta_pub": "1/16000", "width_target": "1/100",
          "moment_width_max": "1/1000000", "moment_guard": "1/100000000", "R_old": "2 q(1-q) s exp((M-1)/2), max q(1-q) over the certified q interval incl. 1/4 if it contains 1/2",
          "R_new": "(5/4)(alpha sqrt(M) + 2 alpha^2)", "M_uniform": "V + r_upper^2", "decisions": "PASS: published unclipped width <= 1/100 and checked; DECLINE: lower ideal padded width > 1/100; else UNRESOLVED"}

def sha(p): return hashlib.sha256(open(p, "rb").read()).hexdigest()
def dump(path, obj):
    tmp = path + ".tmp"; f = open(tmp, "w"); json.dump(obj, f, indent=1, default=str); f.flush(); os.fsync(f.fileno()); f.close(); os.replace(tmp, path)
def cmd_out(c):
    try: return subprocess.run(c, capture_output=True, text=True, timeout=20).stdout.strip()
    except Exception as e: return f"unavailable: {e}"

class Clock:
    def __init__(self): self.t0 = time.monotonic(); self.commands_s = 0.0; self.validation_s = 0.0
    def elapsed(self): return time.monotonic() - self.t0

class AggregateCapExceeded(Exception): pass

def run_sub(J, clk, cmd, cwd, deadline, meta, progress=None, monitor=None):
    # closeout amendment 1 (driver v2): the 600 s cumulative cap is enforced BEFORE every launch and bounds each child's deadline; v1 only reported it post hoc
    remaining_total = CAPS["all_commands_cumulative_s"] - clk.commands_s
    if remaining_total <= 0: J.write({"kind": "cap_crossed", "cap": "all_commands_cumulative_s", "charged_s": clk.commands_s, **meta}); raise AggregateCapExceeded(meta.get("phase"))
    deadline = min(deadline, remaining_total)
    rec = run_native(cmd, cwd, J, deadline, CAPS["rss_cap_bytes"], meta, progress_path=progress, monitor=monitor, env={**os.environ, "OMP_NUM_THREADS": "1"}); clk.commands_s += rec["wall_s"]; return rec

def main():
    ap = argparse.ArgumentParser(); ap.add_argument("--run-dir", required=True); ap.add_argument("--build-dir", default=os.path.join(CODE, "build")); ap.add_argument("--stop-after-lock", action="store_true", help="preflight rehearsal: Stage A only, no MAIN center work"); a = ap.parse_args()
    RUN = os.path.abspath(a.run_dir); BUILD = os.path.abspath(a.build_dir); os.makedirs(RUN, exist_ok=True); os.makedirs(BUILD, exist_ok=True)
    for d in ("validation", "stage_b", "stage_c", "control", "reasons"): os.makedirs(os.path.join(RUN, d), exist_ok=True)
    J = Journal(os.path.join(RUN, "events.jsonl")); clk = Clock(); state = {"run_dir": RUN, "started": now_iso(), "stages": {}, "stops": [], "outcome": None, "costs": {}}
    def save(): dump(os.path.join(RUN, "state.json"), state)
    def stop(code, reason, stage):
        state["stops"].append({"code": code, "reason": reason, "stage": stage, "at": now_iso(), "elapsed_s": clk.elapsed()}); open(os.path.join(RUN, "reasons", f"{stage}_{code}.txt"), "w").write(reason + "\n"); J.write({"kind": "stop", "code": code, "reason": reason, "stage": stage}); save()
    J.write({"kind": "driver_start", "pid": os.getpid(), "caps": CAPS, "frozen": FROZEN, "loadavg_at_start": os.getloadavg(), "cwd": os.getcwd()})
    env = {"platform": platform.platform(), "machine": platform.machine(), "cpu": cmd_out(["sysctl", "-n", "machdep.cpu.brand_string"]), "memsize_bytes": cmd_out(["sysctl", "-n", "hw.memsize"]), "python": sys.version.split()[0],
           "compiler": cmd_out(["c++", "--version"]).split("\n")[0], "loadavg_1_5_15": os.getloadavg(), "uptime": cmd_out(["uptime"]), "git_head": cmd_out(["git", "-C", CODE, "rev-parse", "HEAD"]), "git_dirty_files": cmd_out(["git", "-C", CODE, "status", "--short"]).count("\n")}
    try:
        import gmpy2; env["gmpy2"] = gmpy2.version(); env["mpfr_python"] = gmpy2.mpfr_version(); env["gmp_python"] = gmpy2.mp_version()
    except Exception as e: env["gmpy2"] = f"unavailable: {e}"
    monitor = ContentionMonitor(J); monitor.start()
    # ================= Stage A =================
    A = state["stages"]["A"] = {"status": "RUNNING", "steps": {}}; save()
    srcs = {f: sha(os.path.join(CODE, f)) for f in ("native/nfchain.cpp", "native/nfcheck.cpp", "native/mpiv.hpp", "nf/model.py", "nf/certs.py", "nf/check.py", "nf/validate.py", "nf/reference.py", "nf/ivpy.py", "nf/run.py", "nf/report.py", "tests/test_nf_small.py")}
    INC = ["-I/opt/homebrew/opt/gmp/include", "-I/opt/homebrew/opt/mpfr/include"]; LIB = ["-L/opt/homebrew/opt/gmp/lib", "-L/opt/homebrew/opt/mpfr/lib", "-lmpfr", "-lgmp"]
    for k in ("nfchain", "nfcheck"):
        rec = run_sub(J, clk, ["c++", "-O2", "-std=c++17", "-fno-fast-math", *INC, os.path.join(CODE, "native", f"{k}.cpp"), "-o", os.path.join(BUILD, k), *LIB], RUN, CAPS["compile_or_validation_cmd_s"], {"phase": f"compile_{k}", "stage": "A"})
        A["steps"][f"compile_{k}"] = {"exit": rec["exit_code"], "wall_s": rec["wall_s"], "cpu_s": rec["cpu_s"], "kill": rec["kill_reason"]}
        if rec["exit_code"] != 0: stop("COMPILE_FAILURE", f"{k} failed to compile (see compile_{k}_stderr.txt)", "A"); A["status"] = "FAILED"; state["outcome"] = "VALIDITY_OR_IMPLEMENTATION_FAILURE"; save(); return finish(J, clk, state, RUN, monitor)
    bins = {k: sha(os.path.join(BUILD, k)) for k in ("nfchain", "nfcheck")}
    # tiny validation (one command, 120 s cap; 60 s cumulative small-validation budget); results land in <RUN>/validation/
    os.environ["NF_RUN_DIR"] = RUN; os.environ["NF_BUILD_DIR"] = BUILD
    rec = run_sub(J, clk, [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", os.path.join(CODE, "tests", "test_nf_small.py")], RUN, min(CAPS["compile_or_validation_cmd_s"], CAPS["small_validation_cumulative_s"]), {"phase": "tiny_validation", "stage": "A"})
    clk.validation_s += rec["wall_s"]; A["steps"]["tiny_validation"] = {"exit": rec["exit_code"], "wall_s": rec["wall_s"], "cpu_s": rec["cpu_s"], "kill": rec["kill_reason"], "env_NF_RUN_DIR": RUN}
    if rec["exit_code"] != 0: stop("VALIDATION_FAILURE", "tiny validation / rejection suite failed; large run not started (see tiny_validation_stderr.txt and validation/)", "A"); A["status"] = "FAILED"; state["outcome"] = "VALIDITY_OR_IMPLEMENTATION_FAILURE"; save(); return finish(J, clk, state, RUN, monitor)
    # MAIN geometry: third independent regeneration (Python), exact verification, canonical bytes + hash; kernels dump their own regeneration for binding
    pc = PhaseClock("main_geometry_python"); M = main_walsh5(); geo = verify_main_geometry(M); canon = M.canonical_bytes(); gh = hashlib.sha256(canon).hexdigest(); inp = os.path.join(RUN, "input_main.txt"); open(inp, "wb").write(canon); ph = pc.stop(); clk.commands_s += ph["wall_s"]
    A["steps"]["main_geometry"] = {**geo, "canonical_sha256": gh, "logical_expanded_bytes": len(canon), "formula_bytes": len(open(os.path.join(CODE, "nf", "model.py"), "rb").read()), **ph}
    if not geo["all_ok"]: stop("GEOMETRY_FAILURE", "MAIN generator facts did not verify", "A"); A["status"] = "FAILED"; state["outcome"] = "VALIDITY_OR_IMPLEMENTATION_FAILURE"; save(); return finish(J, clk, state, RUN, monitor)
    dumps = {}
    for k in ("nfchain", "nfcheck"):
        dp = os.path.join(RUN, f"dump_{k}.txt"); rec = run_sub(J, clk, [os.path.join(BUILD, k), "--gen", "NF_WALSH5_MAIN_V1", "--n", "262144", "--query", "131072", "--dump", dp], RUN, CAPS["compile_or_validation_cmd_s"], {"phase": f"generator_dump_{k}", "stage": "A"})
        dumps[k] = {"exit": rec["exit_code"], "wall_s": rec["wall_s"], "sha256": sha(dp) if os.path.exists(dp) else None}; dumps[k]["matches_python_canonical"] = dumps[k]["sha256"] == gh
        if os.path.exists(dp): os.remove(dp)   # 21 MB each; the hash is the record
    A["steps"]["generator_binding"] = dumps
    if not all(d["matches_python_canonical"] for d in dumps.values()): stop("GENERATOR_BINDING_FAILURE", "kernel regeneration disagrees with the Python canonical input", "A"); A["status"] = "FAILED"; state["outcome"] = "VALIDITY_OR_IMPLEMENTATION_FAILURE"; save(); return finish(J, clk, state, RUN, monitor)
    # cheap-rejection CONTROL: A → 2A; only the selected uniform NEW bound at residual 0; geometry validation shared with MAIN (scaling by 2 is exact)
    pc = PhaseClock("control_gate"); K = Fr(geo["exact"]["K"]); Vc = K * 4 * Fr(5, 4); a2c = 4 * Fr(5, 1048576); Rc = certs.R_new_range(certs.sqrt_lower(a2c), certs.sqrt_upper(a2c), Vc, Vc); cls = certs.classify(Rc[0], Rc[1], True, True); ph = pc.stop(); clk.commands_s += ph["wall_s"]
    ctrl = {"case_id": "NF_WALSH5_CONTROL_2A_V1", "definition": "MAIN with A replaced by 2A; same h, edges, query", "validation": "shared with MAIN (AA^T = I_5, alpha^2 = 20/2^20, same tau/K follow exactly from the verified MAIN geometry by scaling)", "evaluated": "uniform NEW bound R_new(V_control) at residual 0 only",
            "V_control": str(Vc), "alpha2_control": str(a2c), "R_new_enclosure": [str(Rc[0]), str(Rc[1])], "ideal_padded_width_enclosure": [str(x) for x in cls["ideal_padded_width_enclosure"]], "classification": cls["status"], "declined_before_any_center_evaluation": cls["status"] == "DECLINE", "additional_gate_cost": ph,
            "not_claimed": ["standalone fallback overhead", "rejection by every possible certificate", "control center/target/Fourier work (none run)"]}
    dump(os.path.join(RUN, "control", "control_gate.json"), ctrl); A["steps"]["control_gate"] = {"classification": cls["status"], **ph}
    if cls["status"] != "DECLINE": stop("CONTROL_DID_NOT_DECLINE", "the 2A control must decline before center work", "A"); A["status"] = "FAILED"; state["outcome"] = "VALIDITY_OR_IMPLEMENTATION_FAILURE"; save(); return finish(J, clk, state, RUN, monitor)
    # LOCK (frozen before Stage B)
    lock = {"lock_version": "NF-DIAG-LOCK-1", "written": now_iso(), "spec": {"file": "docs/normalization-free-diagnostic-v1/CLAUDE_CODE_SPEC.md", "sha256": sha(os.path.join(CODE, "..", "docs", "normalization-free-diagnostic-v1", "CLAUDE_CODE_SPEC.md")), "zip_sha256": "662f3d5bae721ad980e7f77b8ccff035fafd76346d9a08fca748e8ce4beb63f1"},
            "input": {"case_id": "NF_WALSH5_MAIN_V1", "n": 262144, "rank": 5, "query_index": 131072, "requested_event": "X[query_index] == +1", "requested_unclipped_interval_width": "1/100", "pins": [], "generator": "zero-based; d=floor(i/2); A[0,i]=1/1024; A[l,i]=(-1)^bit(d,17-l)/1024 l=1..4; h[i]=1/4+(i+1)/(1000(n+1)); f even 9, odd 11/9; no positive modes, no evidence",
                      "canonical_format": "NFCHAIN-V1 (see nf/model.py)", "canonical_sha256": gh, "logical_expanded_bytes": len(canon)}, "control": {"case_id": ctrl["case_id"], "definition": ctrl["definition"]},
            "frozen": FROZEN, "constants": {"K": geo["exact"]["K"], "V": geo["exact"]["V"], "alpha2": geo["exact"]["alpha2"], "block_row_sum": geo["exact"]["row_sum"], "resolvent_multiplier": "5/4", "tau_strong": "4/5", "tau_weak": "1/10"}, "caps": CAPS,
            "stage_order": ["A: compile, tiny validation (4 fixtures + rejections), MAIN geometry, generator binding, 2A control gate, lock", "B: center policy (<=6 updates, stop at residual_sq<=1/256), producer witnesses, both certificates, independent checker, decision", "C (conditional on old DECLINE and new PASS): actual moments producer (128) + checker covariance identity (192), width gate, guard, containment, re-evaluation"],
            "decision_rules": {"old PASS": "OLD_CHEAP_ALREADY_SUFFICIENT (stop)", "old UNRESOLVED": "NUMERICAL_OR_BOUNDARY_INCONCLUSIVE (stop)", "new DECLINE": "theorem/implementation discrepancy → VALIDITY_OR_IMPLEMENTATION_FAILURE (stop)", "old DECLINE & new PASS": "Stage C", "C old pass": "OLD_REFINEMENT_SUFFICIENT", "C old clean decline & new pass": "NEW_ONLY_FOR_FROZEN_TESTS", "C unresolved": "INCONCLUSIVE (named)"},
            "sources": srcs, "binaries": bins, "environment": env, "theory_packet_hashes": {f: sha(os.path.join(CODE, "..", "docs", "normalization-free-diagnostic-v1", f)) for f in ("MOMENT_CHECKER_NOTE.md", "DECISION_ADDENDUM.md", "theory/precision_contract.md", "theory/proof_candidates.md", "theory/witness_boundary.md")}}
    dump(os.path.join(RUN, "lock.json"), lock); A["status"] = "DONE"; A["elapsed_s"] = clk.elapsed(); save(); J.write({"kind": "lock_written", "sha256": sha(os.path.join(RUN, "lock.json"))})
    if a.stop_after_lock: stop("PREFLIGHT_ONLY", "driver invoked with --stop-after-lock: Stage A rehearsal, no MAIN center work", "A"); state["outcome"] = "PREFLIGHT_ONLY"; save(); return finish(J, clk, state, RUN, monitor)
    # ================= Stage B =================
    B = state["stages"]["B"] = {"status": "RUNNING", "center_evaluations": []}; save(); tB = time.monotonic(); V = Fr(lock["constants"]["V"]); sb = os.path.join(RUN, "stage_b"); prog = os.path.join(sb, "progress.jsonl")
    def remaining_b(): return CAPS["stage_b_s"] - (time.monotonic() - tB)
    c = [Fr(0)] * 5; final = None; updates = 0
    while True:
        if remaining_b() <= 0: stop("STAGE_B_DEADLINE", "Stage B 120 s cap reached during center construction", "B"); B["status"] = "DEADLINE"; state["outcome"] = "INCONCLUSIVE"; state["inconclusive_reason"] = "stage_b_deadline_during_center"; save(); return finish(J, clk, state, RUN, monitor)
        out = os.path.join(sb, f"producer_eval{updates}.json"); cstr = ",".join(str(x) for x in c)
        rec = run_sub(J, clk, [os.path.join(BUILD, "nfchain"), "--prec", "128", "--gen", "NF_WALSH5_MAIN_V1", "--n", "262144", "--query", "131072", "--center", cstr, "--out", out, "--progress", prog], sb, remaining_b(), {"phase": "producer_eval", "stage": "B", "update": updates}, progress=prog, monitor=monitor)
        if rec["exit_code"] != 0: stop("PRODUCER_FAILURE", f"producer evaluation {updates} failed/killed ({rec['kill_reason']})", "B"); B["status"] = "FAILED"; state["outcome"] = "INCONCLUSIVE" if rec["kill_reason"] else "VALIDITY_OR_IMPLEMENTATION_FAILURE"; state["inconclusive_reason"] = rec["kill_reason"]; save(); return finish(J, clk, state, RUN, monitor)
        P = json.load(open(out)); g = [(fx(x), fx(y)) for x, y in P["gradient"]]; rsq = certs.residual_sq_upper(g)
        ev = {"update": updates, "center": [str(x) for x in c], "residual_sq_upper": str(rsq), "residual_ok": rsq <= Fr(1, 256), "wall_s": rec["wall_s"], "cpu_s": rec["cpu_s"], "cpu_over_wall": rec["cpu_over_wall"], "peak_rss": rec["peak_rss_bytes"], "counts": P["counts"], "q_width": str(fx(P["q_query"][1]) - fx(P["q_query"][0]))}
        B["center_evaluations"].append(ev); save(); J.write({"kind": "center_evaluation", **{k: v for k, v in ev.items() if k != "counts"}})
        if rsq <= Fr(1, 256): final = (c, P, rsq); break
        if updates == 6: break
        c = [round_grid(c[l] - STEP * (g[l][0] + g[l][1]) / 2) for l in range(5)]; updates += 1
    if final is None: stop("CENTER_RESIDUAL_FAILURE", "residual still > 1/16 after six updates; no seventh update", "B"); B["status"] = "FAILED"; state["outcome"] = "VALIDITY_OR_IMPLEMENTATION_FAILURE"; save(); return finish(J, clk, state, RUN, monitor)
    c, P, rsq = final; ql, qh = fx(P["q_query"][0]), fx(P["q_query"][1]); qhat = (ql + qh) / 2; slo, shi = fx(P["s_query"][0]), fx(P["s_query"][1]); alo, ahi = fx(P["alpha_query"][0]), fx(P["alpha_query"][1]); Mu = V + rsq
    contract_ok = (qh - ql) <= certs.Q_WIDTH_MAX
    Ro = certs.R_old_range(ql, qh, slo, shi, Mu, Mu); Rn = certs.R_new_range(alo, ahi, Mu, Mu)
    pubs = {}; cert = {}
    for nm, R in (("old", Ro), ("new", Rn)):
        p = certs.publication(qhat, R[1]); pubs[nm] = {"unclipped": [str(p["unclipped"][0]), str(p["unclipped"][1])], "clipped": [str(p["clipped"][0]), str(p["clipped"][1])], "unclipped_width": str(p["unclipped_width"]), "R_upper": str(R[1]), "R_lower": str(R[0])}
    wit = {"case_id": P["case_id"], "n": P["n"], "rank": P["rank"], "query_index": P["query_index"], "requested_event": "X[query_index] == +1", "producer_prec": P["prec"], "producer_generator_hash": dumps["nfchain"]["sha256"], "pins": [], "producer_flags_clean": P["flags_clean"],
           "center": [str(x) for x in c], "updates_used": updates, "q_query": P["q_query"], "qhat": str(qhat), "q_width": str(qh - ql), "residual_sq_upper": str(rsq), "residual_sq_threshold": "1/256", "M_uniform": str(Mu), "V": str(V), "s_query": [str(slo), str(shi)], "alpha_query": [str(alo), str(ahi)], "gradient": P["gradient"], "publication": pubs, "counts": P["counts"]}
    dump(os.path.join(sb, "witness.json"), wit); J.write({"kind": "witness_written", "q": [str(ql), str(qh)], "residual_sq_upper": str(rsq), "updates": updates})
    # independent checker at the same stored center
    cko = os.path.join(sb, "checker_kernel.json"); cdp = os.path.join(sb, "checker_dump.txt")
    rec = run_sub(J, clk, [os.path.join(BUILD, "nfcheck"), "--prec", "192", "--gen", "NF_WALSH5_MAIN_V1", "--n", "262144", "--query", "131072", "--center", ",".join(str(x) for x in c), "--out", cko, "--progress", prog, "--dump", cdp], sb, max(remaining_b(), 0.001), {"phase": "checker", "stage": "B"}, progress=prog, monitor=monitor)
    chk_hash = sha(cdp) if os.path.exists(cdp) else None
    if os.path.exists(cdp): os.remove(cdp)
    B["checker_run"] = {"exit": rec["exit_code"], "kill": rec["kill_reason"], "wall_s": rec["wall_s"], "cpu_s": rec["cpu_s"], "cpu_over_wall": rec["cpu_over_wall"], "peak_rss": rec["peak_rss_bytes"], "regenerated_input_sha256": chk_hash}
    if rec["exit_code"] != 0: stop("CHECKER_FAILURE", f"checker kernel failed/killed ({rec['kill_reason']})", "B"); B["status"] = "FAILED"; state["outcome"] = "INCONCLUSIVE" if rec["kill_reason"] else "VALIDITY_OR_IMPLEMENTATION_FAILURE"; state["inconclusive_reason"] = rec["kill_reason"] or "checker_kernel_error"; save(); return finish(J, clk, state, RUN, monitor)
    CK = json.load(open(cko)); pc = PhaseClock("checker_python"); Vind, _ = independent_V(M); verdict = verify_stage_b(lock, wit, CK, chk_hash, pins_expected=[], V_independent=Vind); ph = pc.stop(); clk.commands_s += ph["wall_s"]; verdict["python_phase"] = ph; dump(os.path.join(sb, "checker_verdict.json"), verdict)
    ok = verdict["verdict"] == "VERIFIED"
    for nm, R in (("old", Ro), ("new", Rn)): cert[nm] = certs.classify(R[0], R[1], ok, contract_ok)
    B["certificates"] = {nm: {k: (list(map(str, v)) if isinstance(v, tuple) else str(v)) for k, v in cert[nm].items()} for nm in cert}; B["checker_verdict"] = verdict["verdict"]; B["checker_failed_checks"] = verdict["failed_checks"]
    B["ideal_width_enclosures"] = {nm: [str(2 * R[0] + certs.PADS), str(2 * R[1] + certs.PADS)] for nm, R in (("old", Ro), ("new", Rn))}
    B["witness_end"] = now_iso(); B["elapsed_s"] = time.monotonic() - tB; B["status"] = "DONE"; save(); B["durable_end"] = now_iso(); save()
    # decision (first applicable)
    if not ok: stop("CHECKER_REJECTED", f"independent checker rejected: {verdict['failed_checks']}", "B"); state["outcome"] = "VALIDITY_OR_IMPLEMENTATION_FAILURE"; save(); return finish(J, clk, state, RUN, monitor)
    if cert["new"]["status"] == "DECLINE": stop("NEW_CERTIFICATE_DECLINED", "clean DECLINE of the new certificate after valid residual/domain checks: theorem/implementation discrepancy", "B"); state["outcome"] = "VALIDITY_OR_IMPLEMENTATION_FAILURE"; save(); return finish(J, clk, state, RUN, monitor)
    if cert["old"]["status"] == "PASS": stop("OLD_CHEAP_ALREADY_SUFFICIENT", "old uniform certificate passes at width 1/100; actual moments NOT computed; no compression/Fourier work", "B"); state["outcome"] = "OLD_CHEAP_ALREADY_SUFFICIENT"; state["stages"]["C"] = {"status": "NOT_RUN", "reason": "old cheap certificate passed (frozen stop)"}; save(); return finish(J, clk, state, RUN, monitor)
    if cert["old"]["status"] == "UNRESOLVED" or cert["new"]["status"] != "PASS": stop("NUMERICAL_OR_BOUNDARY_INCONCLUSIVE", f"old={cert['old']['status']} ({cert['old']['reason']}), new={cert['new']['status']} ({cert['new']['reason']})", "B"); state["outcome"] = "INCONCLUSIVE"; state["inconclusive_reason"] = "NUMERICAL_OR_BOUNDARY_INCONCLUSIVE"; state["stages"]["C"] = {"status": "NOT_RUN", "reason": "Stage B not decisive"}; save(); return finish(J, clk, state, RUN, monitor)
    # ================= Stage C (old DECLINE, new PASS) =================
    C = state["stages"]["C"] = {"status": "RUNNING"}; save(); tC = time.monotonic(); sc = os.path.join(RUN, "stage_c"); progc = os.path.join(sc, "progress.jsonl")
    def remaining_c(): return CAPS["stage_c_s"] - (time.monotonic() - tC)
    po = os.path.join(sc, "producer_moments.json"); rec = run_sub(J, clk, [os.path.join(BUILD, "nfchain"), "--prec", "128", "--gen", "NF_WALSH5_MAIN_V1", "--n", "262144", "--query", "131072", "--center", ",".join(str(x) for x in c), "--out", po, "--progress", progc, "--moments-only"], sc, remaining_c(), {"phase": "producer_moments", "stage": "C"}, progress=progc, monitor=monitor)
    C["producer_run"] = {"exit": rec["exit_code"], "kill": rec["kill_reason"], "wall_s": rec["wall_s"], "cpu_s": rec["cpu_s"], "peak_rss": rec["peak_rss_bytes"]}
    if rec["exit_code"] != 0: stop("STAGE_C_PRODUCER_FAILURE", f"producer moment pass failed/killed ({rec['kill_reason']})", "C"); C["status"] = "FAILED"; state["outcome"] = "INCONCLUSIVE"; state["inconclusive_reason"] = rec["kill_reason"] or "moment_kernel_error"; save(); return finish(J, clk, state, RUN, monitor)
    co = os.path.join(sc, "checker_moments.json"); rec = run_sub(J, clk, [os.path.join(BUILD, "nfcheck"), "--prec", "192", "--gen", "NF_WALSH5_MAIN_V1", "--n", "262144", "--query", "131072", "--center", ",".join(str(x) for x in c), "--out", co, "--progress", progc, "--moments"], sc, max(remaining_c(), 0.001), {"phase": "checker_moments", "stage": "C"}, progress=progc, monitor=monitor)
    C["checker_run"] = {"exit": rec["exit_code"], "kill": rec["kill_reason"], "wall_s": rec["wall_s"], "cpu_s": rec["cpu_s"], "peak_rss": rec["peak_rss_bytes"]}
    if rec["exit_code"] != 0: stop("STAGE_C_CHECKER_FAILURE", f"checker moment pass failed/killed ({rec['kill_reason']})", "C"); C["status"] = "FAILED"; state["outcome"] = "INCONCLUSIVE"; state["inconclusive_reason"] = rec["kill_reason"] or "moment_checker_error"; save(); return finish(J, clk, state, RUN, monitor)
    PM = json.load(open(po)); CM = json.load(open(co)); vc = verify_stage_c(lock, {"raw": PM["M_actual"]}, CM["M_actual"]); dump(os.path.join(sc, "moment_verdict.json"), vc); C["moment_verdict"] = vc["verdict"]; C["moment_detail"] = vc["detail"]
    if vc["verdict"] != "VERIFIED":
        code = "PRECISION_INCONCLUSIVE" if vc["verdict"] == "PRECISION_INCONCLUSIVE" else "STAGE_C_CHECKING_FAILURE"; stop(code, f"actual-moment stage: {vc['verdict']} {vc['failed_checks']}", "C"); C["status"] = "DONE"; state["outcome"] = "INCONCLUSIVE" if code == "PRECISION_INCONCLUSIVE" else "VALIDITY_OR_IMPLEMENTATION_FAILURE"; state["inconclusive_reason"] = code; save(); return finish(J, clk, state, RUN, monitor)
    plo, phi = fx(PM["M_actual"][0]), fx(PM["M_actual"][1]); guard = Fr(1, 100000000); Mg_lo, Mg_hi = max(Fr(0), plo - guard), phi + guard; clo, chi = fx(CM["M_actual"]["M"][0]), fx(CM["M_actual"]["M"][1])
    M_up = min(Mu, Mg_hi); M_lo_ideal = clo; sel = "actual_guarded_upper" if Mg_hi < Mu else "uniform_upper"
    Ro2 = (certs.R_old_range(ql, qh, slo, shi, M_lo_ideal, M_lo_ideal)[0], certs.R_old_range(ql, qh, slo, shi, M_up, M_up)[1]); Rn2 = (certs.R_new_range(alo, ahi, M_lo_ideal, M_lo_ideal)[0], certs.R_new_range(alo, ahi, M_up, M_up)[1])
    cert2 = {nm: certs.classify(R[0], R[1], True, contract_ok) for nm, R in (("old", Ro2), ("new", Rn2))}
    C["refined"] = {"M_raw_producer": [str(plo), str(phi)], "M_guarded_producer": [str(Mg_lo), str(Mg_hi)], "M_checker": [str(clo), str(chi)], "M_upper_selected": str(M_up), "selection": sel, "M_lower_for_ideal_widths": str(M_lo_ideal),
                    "publications": {nm: {"unclipped": [str(x) for x in certs.publication(qhat, R[1])["unclipped"]], "unclipped_width": str(2 * R[1] + certs.PADS)} for nm, R in (("old", Ro2), ("new", Rn2))},
                    "certificates": {nm: {k: (list(map(str, v)) if isinstance(v, tuple) else str(v)) for k, v in cert2[nm].items()} for nm in cert2}}
    C["elapsed_s"] = time.monotonic() - tC; C["status"] = "DONE"; save()
    if cert2["old"]["status"] == "PASS": stop("OLD_REFINEMENT_SUFFICIENT", "old actual-moment certificate passes; both routes avoid integration; phase cost is diagnostic only", "C"); state["outcome"] = "OLD_REFINEMENT_SUFFICIENT"
    elif cert2["old"]["status"] == "DECLINE" and cert2["new"]["status"] == "PASS": stop("NEW_ONLY_FOR_FROZEN_TESTS", "old actual-moment test cleanly declines, new passes: separation of these frozen sufficient tests at this center only", "C"); state["outcome"] = "NEW_ONLY_FOR_FROZEN_TESTS"
    else: stop("STAGE_C_INCONCLUSIVE", f"old={cert2['old']['status']}, new={cert2['new']['status']}", "C"); state["outcome"] = "INCONCLUSIVE"; state["inconclusive_reason"] = "stage_c_width_straddle"
    save(); return finish(J, clk, state, RUN, monitor)

def finish(J, clk, state, RUN, monitor):
    mon = monitor.finish(); ru = resource.getrusage(resource.RUSAGE_CHILDREN); rs = resource.getrusage(resource.RUSAGE_SELF)
    state["costs"] = {"driver_elapsed_s": clk.elapsed(), "charged_commands_and_phases_s": clk.commands_s, "small_validation_s": clk.validation_s, "children_cpu_s": ru.ru_utime + ru.ru_stime, "driver_cpu_s": rs.ru_utime + rs.ru_stime, "children_maxrss_bytes_rusage": ru.ru_maxrss, "driver_maxrss_bytes": rs.ru_maxrss,
                      "caps": CAPS, "cap_violations": [k for k, lim in (("all_commands_cumulative_s", CAPS["all_commands_cumulative_s"]),) if clk.commands_s > lim] + (["small_validation_cumulative_s"] if clk.validation_s > CAPS["small_validation_cumulative_s"] else [])}
    state["contention"] = mon; state["timing_contamination"] = bool(mon["violations"]); state["loadavg_at_end"] = os.getloadavg(); state["ended"] = now_iso(); dump(os.path.join(RUN, "state.json"), state); J.write({"kind": "driver_end", "outcome": state["outcome"], "costs": state["costs"], "contention_violations": len(mon["violations"])}); J.close()
    print(json.dumps({"outcome": state["outcome"], "stops": [s["code"] for s in state["stops"]], "charged_s": round(clk.commands_s, 2), "elapsed_s": round(clk.elapsed(), 2), "contamination": state["timing_contamination"]}))

if __name__ == "__main__":
    try: main()
    except SystemExit: raise
    except AggregateCapExceeded as e:
        rd = [os.path.abspath(sys.argv[i + 1]) for i, x in enumerate(sys.argv) if x == "--run-dir"][0]; st = json.load(open(os.path.join(rd, "state.json"))); st["stops"] = st.get("stops", []) + [{"code": "ALL_COMMANDS_CUMULATIVE_CAP", "reason": f"600 s cumulative cap reached before launching {e}", "stage": "driver", "at": now_iso()}]; st["outcome"] = "INCONCLUSIVE"; st["inconclusive_reason"] = "all_commands_cumulative_cap"; st["ended"] = now_iso(); dump(os.path.join(rd, "state.json"), st); sys.exit(3)
    except BaseException as e:
        import traceback; rd = None
        for i, x in enumerate(sys.argv):
            if x == "--run-dir": rd = os.path.abspath(sys.argv[i + 1])
        if rd:
            os.makedirs(os.path.join(rd, "reasons"), exist_ok=True); open(os.path.join(rd, "reasons", "DRIVER_EXCEPTION.txt"), "w").write(traceback.format_exc())
            try:
                st = json.load(open(os.path.join(rd, "state.json")))
            except Exception: st = {"stages": {}, "stops": []}
            st["stops"] = st.get("stops", []) + [{"code": "DRIVER_EXCEPTION", "reason": f"{type(e).__name__}: {e}", "stage": "driver", "at": now_iso()}]; st["outcome"] = st.get("outcome") or "VALIDITY_OR_IMPLEMENTATION_FAILURE"; st["ended"] = now_iso(); dump(os.path.join(rd, "state.json"), st)
        raise
