"""Supervised driver for the frozen H4 arithmetic comparison (CLAUDE_ROOT_SPEC.md §7-§10).
Stage A -> environment observation -> nine cold bundles (3 reps x 3 arms, frozen order) -> cross-check -> decision.
External supervisor: process-group kill on the earliest applicable deadline or the 4 GiB RSS cap, 5-second durable
heartbeats in every phase, a 900-second cumulative executed-command cap with a 60-second closing reserve."""
from __future__ import annotations
import sys, os, json, time, subprocess, hashlib, resource, signal, argparse, platform, struct
import shlex
sys.set_int_max_str_digits(0)
from fractions import Fraction as Fr
from pathlib import Path
from pgm.algorithms.h4 import kernels
import psutil

ROOT = str(Path(__file__).resolve().parents[3])
CAPS = {"implementation_wall_s_informational": 7200, "cumulative_commands_s": 900, "stage_a_s": 120, "bundle_s": 120,
        "closing_reserve_s": 60, "rss_cap_bytes": 4 << 30, "threads": 1}
THRESH = {"PP_over_C_complete": Fr(1, 2), "PP_over_C_producer": Fr(8, 10), "PI_over_C_complete": Fr(8, 10)}
SCHEDULE = [("C", "PI", "PP"), ("PI", "PP", "C"), ("PP", "C", "PI")]
FOREIGN_CORE_LIMIT = 0.5

def now(): return time.strftime("%Y-%m-%dT%H:%M:%S%z")
def sha(p): return hashlib.sha256(open(p, "rb").read()).hexdigest()

class Journal:
    def __init__(self, path):
        self.path = path; self.fh = open(path, "a"); self.seq = 0
    def write(self, rec):
        self.seq += 1; rec = {"seq": self.seq, "at": now(), "mono": time.monotonic(), **rec}
        self.fh.write(json.dumps(rec, default=str) + "\n"); self.fh.flush(); os.fsync(self.fh.fileno())
    def close(self): self.fh.close()

class Budget:
    def __init__(self): self.t0 = time.monotonic(); self.spent = 0.0
    def elapsed(self): return time.monotonic() - self.t0
    def remaining(self, reserve=0.0): return CAPS["cumulative_commands_s"] - self.spent - reserve
    def charge(self, s): self.spent += s

def dump(path, obj):
    tmp = path + ".tmp"; f = open(tmp, "w"); json.dump(obj, f, indent=1, default=str); f.flush(); os.fsync(f.fileno()); f.close(); os.replace(tmp, path)

def supervise(cmd, cwd, J, budget, deadline_s, meta, hb_s=5.0):
    """Launch in its own process group; poll RSS/CPU; heartbeat >= every hb_s; kill the whole group on the earliest
    applicable deadline or the RSS cap; charge the wall time; record a durable reason."""
    eff = min(deadline_s, max(budget.remaining(CAPS["closing_reserve_s"]), 0.0))
    if eff <= 0:
        J.write({"kind": "cap_block", "cap": "cumulative_commands_s", "spent_s": budget.spent, **meta}); return {"rc": None, "kill": "cumulative_cap_before_launch", "wall_s": 0.0, "cpu_s": 0.0, "peak_rss": 0}
    t0 = time.monotonic(); r0 = resource.getrusage(resource.RUSAGE_CHILDREN)
    J.write({"kind": "launch", "cmd": cmd, "deadline_s": eff, **meta})
    p = subprocess.Popen(cmd, cwd=cwd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, start_new_session=True)
    try: proc = psutil.Process(p.pid)
    except psutil.Error: proc = None
    peak = 0; kill = None; last = t0; term_at = None
    while p.poll() is None:
        t = time.monotonic()
        rss = 0; cpu = 0.0
        if proc is not None:
            try:
                for q in [proc] + proc.children(recursive=True):
                    with q.oneshot():
                        rss += q.memory_info().rss; c = q.cpu_times(); cpu += c.user + c.system
            except psutil.Error: pass
        peak = max(peak, rss)
        if rss > CAPS["rss_cap_bytes"] and kill is None:
            kill = "rss_cap"; J.write({"kind": "cap_crossed", "cap": "rss", "observed": rss, **meta})
            try: os.killpg(p.pid, signal.SIGKILL)
            except Exception: pass
        if t - t0 > eff and kill is None:
            kill = "deadline"; term_at = t; J.write({"kind": "deadline", "elapsed_s": t - t0, **meta})
            try: os.killpg(p.pid, signal.SIGTERM)
            except Exception: pass
        if kill == "deadline" and term_at and t - term_at > 3.0:
            try: os.killpg(p.pid, signal.SIGKILL)
            except Exception: pass
        if t - last >= hb_s:
            last = t; J.write({"kind": "heartbeat", "elapsed_s": round(t - t0, 2), "remaining_budget_s": round(budget.remaining(), 1),
                               "tree_rss_bytes": rss, "tree_cpu_s": round(cpu, 2), **meta})
        time.sleep(0.1)
    out, err = p.communicate(); wall = time.monotonic() - t0
    r1 = resource.getrusage(resource.RUSAGE_CHILDREN)
    budget.charge(wall)
    rec = {"rc": p.returncode, "kill": kill, "wall_s": wall, "cpu_s": (r1.ru_utime - r0.ru_utime) + (r1.ru_stime - r0.ru_stime),
           "peak_rss": max(peak, r1.ru_maxrss), "stdout": out.decode()[-2000:], "stderr": err.decode()[-1500:]}
    J.write({"kind": "terminal", **{k: v for k, v in rec.items() if k not in ("stdout",)}, **meta})
    return rec

def observe_environment(J, budget, seconds=10.0):
    """Supervised foreign-CPU observation (charged, with heartbeats). Foreign = any process outside our own tree."""
    t0 = time.monotonic(); own = {os.getpid()}
    try:
        me = psutil.Process(os.getpid()); own |= {c.pid for c in me.children(recursive=True)}
    except psutil.Error: pass
    for p in psutil.process_iter(["pid"]):
        try: p.cpu_percent(None)
        except psutil.Error: pass
    samples = []; last = t0
    while time.monotonic() - t0 < seconds:
        time.sleep(1.0)
        tot = 0.0; busy = []
        for p in psutil.process_iter(["pid", "name"]):
            try: c = p.cpu_percent(None)
            except psutil.Error: continue
            if p.pid in own: continue
            if c > 1.0: tot += c; busy.append((p.pid, p.info["name"], round(c, 1)))
        samples.append({"foreign_cpu_cores": tot / 100.0, "top": sorted(busy, key=lambda x: -x[2])[:4]})
        if time.monotonic() - last >= 5.0:
            last = time.monotonic(); J.write({"kind": "heartbeat", "phase": "environment_observation", "samples": len(samples), "last_foreign_cores": round(tot / 100.0, 3)})
    wall = time.monotonic() - t0; budget.charge(wall)
    avg = sum(s["foreign_cpu_cores"] for s in samples) / max(len(samples), 1)
    rec = {"phase": "environment_observation", "wall_s": wall, "samples": samples, "mean_foreign_cores": avg,
           "limit_cores": FOREIGN_CORE_LIMIT, "eligible": avg < FOREIGN_CORE_LIMIT, "coverage": "all host processes outside this driver tree, 1 Hz"}
    J.write({"kind": "environment", **{k: v for k, v in rec.items() if k != "samples"}})
    return rec

def main():
    ap = argparse.ArgumentParser(); ap.add_argument("--run-dir", required=True); ap.add_argument("--packet", required=True)
    ap.add_argument("--stage-a-only", action="store_true")
    a = ap.parse_args()
    RUN = os.path.abspath(a.run_dir); PK = os.path.abspath(a.packet); os.makedirs(RUN, exist_ok=True)
    for d in ("stage_a", "bundles", "reasons", "crosscheck"): os.makedirs(os.path.join(RUN, d), exist_ok=True)
    J = Journal(os.path.join(RUN, "events.jsonl")); B = Budget()
    st = {"started": now(), "caps": CAPS, "thresholds": {k: str(v) for k, v in THRESH.items()}, "schedule": SCHEDULE,
          "stages": {}, "stops": [], "outcome": None}
    def save(): dump(os.path.join(RUN, "state.json"), st)
    def stop(code, reason, stage):
        st["stops"].append({"code": code, "reason": reason, "stage": stage, "at": now(), "budget_spent_s": B.spent})
        open(os.path.join(RUN, "reasons", f"{stage}_{code}.txt"), "w").write(reason + "\n")
        J.write({"kind": "stop", "code": code, "reason": reason, "stage": stage}); save()
    J.write({"kind": "driver_start", "pid": os.getpid(), "caps": CAPS, "packet": PK,
             "note": "the 120-minute implementation/editing cap is recorded as informational (deviation 2): it bounds "
                     "editing effort, not numerical validity. The 900 s cumulative command cap, the 120 s Stage A and "
                     "per-bundle caps, the 4 GiB RSS cap and one-thread rule remain enforced."})
    # ---------- environment + lock ----------
    env = {"platform": platform.platform(), "machine": platform.machine(), "python": sys.version.split()[0],
           "cpu": subprocess.run(["sysctl", "-n", "machdep.cpu.brand_string"], capture_output=True, text=True).stdout.strip(),
           "memsize": subprocess.run(["sysctl", "-n", "hw.memsize"], capture_output=True, text=True).stdout.strip(),
           "compiler": subprocess.run([*shlex.split(os.environ.get("CXX", "c++")), "--version"], capture_output=True, text=True).stdout.split("\n")[0],
           "loadavg_start": os.getloadavg(), "git_head": subprocess.run(["git", "-C", ROOT, "rev-parse", "HEAD"], capture_output=True, text=True).stdout.strip()}
    try:
        import gmpy2; env["gmpy2"] = gmpy2.version(); env["mpfr"] = gmpy2.mpfr_version(); env["gmp"] = gmpy2.mp_version()
    except Exception as e: env["gmpy2"] = str(e)
    # ---------- compile (charged, one-time) ----------
    FLAGS = list(kernels.FLAGS)
    build_record = os.path.join(RUN, "host_build.json")
    r = supervise([sys.executable, "-m", "pgm.algorithms.h4.kernels", "--output-record", build_record],
                  ROOT, J, B, CAPS["stage_a_s"], {"phase": "compile_h4"})
    if r["rc"] != 0:
        stop("VALIDITY_FAILURE", "H4 host build failed: " + r["stderr"][:500], "build")
        st["outcome"] = "VALIDITY_FAILURE"; save(); return finish(J, B, st, RUN)
    builds = json.load(open(build_record))["kernels"]
    srcs = {}
    for directory, prefix in ((Path(kernels.__file__).parent, "pgm.algorithms.h4"),
                              (Path(__file__).parent, "research/campaigns/h4")):
        for source in sorted(directory.glob("*.py")):
            srcs[prefix + "/" + source.name] = sha(source)
    for source in sorted(kernels.SOURCE_DIR.glob("*.cpp")):
        srcs["pgm.algorithms.h4/native/" + source.name] = sha(source)
    F = json.load(open(os.path.join(PK, "inputs", "FROZEN_NODES.json")))
    lock = {"lock_version": "H4-ARITH-LOCK-1", "written": now(),
            "packet": {"zip_sha256": "797a00a3c15a6b2562d4b21f27eb8ee1099ac684c942d4bf9d2b9cd841d2272a",
                       "files": {f: sha(os.path.join(PK, f)) for f in ("CLAUDE_ROOT_SPEC.md", "NUMERICAL_THEOREM.md", "TABLES_AND_DOMAIN.md", "IMPLEMENTATION_CONTRACT.md", "README.md", "REVIEW.md", "LEDGER_ADDITION.md")}},
            "inputs": {f: sha(os.path.join(PK, "inputs", f)) for f in ("FROZEN_NODES.json", "H4-n128-s1.canonical.json", "ARCHIVED_NODE_RECORDS.json", "PROVENANCE.json", "SMALL_FIXTURES.json")},
            "model": {"model_id": F["model_id"], "model_hash": F["model_hash"], "n": 128, "seed": 1, "source_site": F["source_site"], "target_site": F["target_site"],
                      "context": "E0", "beta": ["3", "2", "-2", "-2"], "residual": "width2"},
            "selected_nodes": F["nodes"], "processed_counts": F["processed_counts"], "representatives": 265,
            "grid": {s: [{k: v for k, v in c.items() if k in ("column", "a", "h", "J", "s", "t", "c_max", "R_tot")} for c in F["frequency_grids"][s]] for s in ("1", "-1")},
            "analytic_delta_comp_exact": F["analytic_delta_comp_exact"],
            "arithmetic": {"producer_prec": 256, "checker_prec": 320, "reference_prec": 512, "mesh": "2^-53", "shrink": "1-2^-50",
                           "eps_p": "2^-48", "eps_phi": "2^-48", "eps_lambda": "2^-48", "E_ch": "2^-38", "E_int": "2^-36",
                           "E_pub": "2^-30", "C_raw_radius_gate": "2^-36", "interval_checker_width_gate": "2^-35",
                           "mass_publication": "m*(1 +- 2^-200)", "tau": "2^-1075"},
            "arms": {"C": "cached 256-bit rectangular producer + independent 320-bit rectangular checker",
                     "PI": "point producer (binary64, MPFR256 tables) + the SAME independent 320-bit rectangular checker as C",
                     "PP": "the same point producer + independently implemented opposite-direction 320-bit point checker"},
            "schedule": SCHEDULE, "thresholds": {k: str(v) for k, v in THRESH.items()}, "caps": CAPS,
            "timing_boundary": "from before model/grid reconstruction through the final checker verdict and the durable bundle record for all six nodes",
            "cache_policy": "one source-independent phase/weight cache per cold bundle per role (producer 256, checker 320), reused across both source signs and all six nodes; sign-specific rows/unaries/masks always rebuilt",
            "sources": srcs, "builds": builds, "environment": env, "compiler_flags": FLAGS}
    dump(os.path.join(RUN, "LOCK.json"), lock); J.write({"kind": "lock_written", "sha256": sha(os.path.join(RUN, "LOCK.json"))})
    dump(os.path.join(RUN, "selection.json"), {"rule": F["selection"], "nodes": F["nodes"], "processed_counts": F["processed_counts"],
         "model_hash": F["model_hash"], "source_site": F["source_site"], "target_site": F["target_site"], "representatives": 265,
         "frozen_nodes_sha256": sha(os.path.join(PK, "inputs", "FROZEN_NODES.json"))})
    # ---------- Stage A ----------
    A = st["stages"]["A"] = {"status": "RUNNING"}; save()
    r = supervise([sys.executable, "-m", "research.campaigns.h4.stagea_main", "--packet", PK, "--out", os.path.join(RUN, "stage_a")], ROOT, J, B, CAPS["stage_a_s"], {"phase": "stage_a"})
    A["wall_s"] = r["wall_s"]; A["rc"] = r["rc"]; A["kill"] = r["kill"]
    sa_path = os.path.join(RUN, "stage_a", "stage_a.json")
    A["result"] = json.load(open(sa_path)) if os.path.exists(sa_path) else {"error": r["stderr"][:600]}
    if r["rc"] != 0 or not A["result"].get("all_ok"):
        code = "INCONCLUSIVE_RESOURCE_OR_TIMING" if r["kill"] else "VALIDITY_FAILURE"
        stop(code, f"Stage A did not pass (rc={r['rc']}, kill={r['kill']})", "A"); A["status"] = "FAILED"; st["outcome"] = code; save(); return finish(J, B, st, RUN)
    A["status"] = "PASSED"; save()
    if a.stage_a_only:
        stop("STAGE_A_ONLY", "driver invoked with --stage-a-only", "A"); st["outcome"] = "STAGE_A_ONLY"; save(); return finish(J, B, st, RUN)
    # ---------- environment observation ----------
    envobs = observe_environment(J, B, 10.0); st["stages"]["environment"] = envobs; save()
    if not envobs["eligible"]:
        # Recorded deviation 1 (amendments/DEVIATION_1_CONTENDED_TIMING.md): the overseer directed that the
        # measurement be taken on a working machine with contention disclosed. The gate is still evaluated and
        # reported per bundle; ineligible bundles are retained and NO positive timing decision may follow.
        st["contended_timing_deviation"] = {"amendment": "amendments/DEVIATION_1_CONTENDED_TIMING.md",
            "gate_mean_foreign_cores": envobs["mean_foreign_cores"], "limit": FOREIGN_CORE_LIMIT,
            "effect": "timing proceeds; outcome capped at INCONCLUSIVE_ENVIRONMENT; ratios are contended diagnostics"}
        J.write({"kind": "deviation", **st["contended_timing_deviation"]}); save()
    # ---------- Stage B: nine cold bundles ----------
    Bst = st["stages"]["B"] = {"status": "RUNNING", "bundles": []}; save()
    for rep, order in enumerate(SCHEDULE, start=1):
        for arm in order:
            key = f"rep{rep}_{arm}"; od = os.path.join(RUN, "bundles", key)
            pre = observe_environment(J, B, 3.0)
            r = supervise([sys.executable, "-m", "pgm.algorithms.h4.arm", "--arm", arm, "--rep", str(rep), "--out-dir", od, "--packet", PK],
                          ROOT, J, B, CAPS["bundle_s"], {"phase": "bundle", "arm": arm, "rep": rep})
            bj = os.path.join(od, "bundle.json")
            b = json.load(open(bj)) if os.path.exists(bj) else None
            entry = {"key": key, "arm": arm, "rep": rep, "rc": r["rc"], "kill": r["kill"], "supervised_wall_s": r["wall_s"],
                     "cpu_s": r["cpu_s"], "peak_rss_bytes": r["peak_rss"], "foreign_cores_before": pre["mean_foreign_cores"],
                     "eligible": pre["eligible"] and r["rc"] == 0 and r["kill"] is None,
                     "complete_wall_s": b["complete_wall_s"] if b else None,
                     "producer_phase_wall_s": b["producer_phase_wall_s"] if b else None,
                     "checker_phase_wall_s": b["checker_phase_wall_s"] if b else None,
                     "all_verified": b["all_verified"] if b else False, "nodes": len(b["nodes"]) if b else 0}
            Bst["bundles"].append(entry); save(); J.write({"kind": "bundle_done", **{k: v for k, v in entry.items() if k != "nodes"}})
            if r["rc"] != 0 or not entry["all_verified"]:
                code = "INCONCLUSIVE_RESOURCE_OR_TIMING" if r["kill"] else "VALIDITY_FAILURE"
                stop(code, f"bundle {key} failed (rc={r['rc']}, kill={r['kill']}, verified={entry['all_verified']}): {r['stderr'][:300]}", "B")
                Bst["status"] = "FAILED"; st["outcome"] = code; save(); return finish(J, B, st, RUN)
            if B.remaining(CAPS["closing_reserve_s"]) <= 0:
                stop("INCONCLUSIVE_RESOURCE_OR_TIMING", "cumulative command budget exhausted before the remaining bundles", "B")
                Bst["status"] = "INCOMPLETE"; st["outcome"] = "INCONCLUSIVE_RESOURCE_OR_TIMING"; save(); return finish(J, B, st, RUN)
    Bst["status"] = "DONE"; save()
    # ---------- cross-check across arms, per repetition ----------
    r = supervise([sys.executable, "-m", "research.campaigns.h4.crosscheck", "--run-dir", RUN, "--out", os.path.join(RUN, "crosscheck")], ROOT, J, B, 120, {"phase": "crosscheck"})
    cc_path = os.path.join(RUN, "crosscheck", "crosscheck.json")
    st["stages"]["crosscheck"] = {"wall_s": r["wall_s"], "rc": r["rc"], "result": json.load(open(cc_path)) if os.path.exists(cc_path) else {"error": r["stderr"][:500]}}
    save()
    if r["rc"] != 0 or not st["stages"]["crosscheck"]["result"].get("all_ok"):
        stop("VALIDITY_FAILURE", "cross-arm enclosure cross-check failed", "crosscheck"); st["outcome"] = "VALIDITY_FAILURE"; save(); return finish(J, B, st, RUN)
    # ---------- decision ----------
    bl = {(e["arm"], e["rep"]): e for e in Bst["bundles"]}
    def med(vals):
        v = sorted(vals); return v[len(v) // 2] if len(v) % 2 else (v[len(v)//2 - 1] + v[len(v)//2]) / 2
    pairs = {}
    for name, num, den, field in (("PI_over_C_complete", "PI", "C", "complete_wall_s"),
                                  ("PP_over_C_complete", "PP", "C", "complete_wall_s"),
                                  ("PP_over_C_producer", "PP", "C", "producer_phase_wall_s")):
        rs = [Fr(bl[(num, rep)][field]).limit_denominator(10**12) / Fr(bl[(den, rep)][field]).limit_denominator(10**12) for rep in (1, 2, 3)]
        pairs[name] = {"per_repetition": [str(x) for x in rs], "per_repetition_float": [float(x) for x in rs], "median": str(med(rs)), "median_float": float(med(rs))}
    st["ratios"] = pairs
    all_elig = all(e["eligible"] for e in Bst["bundles"]) and len(Bst["bundles"]) == 9
    contended = "contended_timing_deviation" in st
    pp_c = med([Fr(bl[("PP", r2)]["complete_wall_s"]).limit_denominator(10**12) / Fr(bl[("C", r2)]["complete_wall_s"]).limit_denominator(10**12) for r2 in (1, 2, 3)])
    pp_p = med([Fr(bl[("PP", r2)]["producer_phase_wall_s"]).limit_denominator(10**12) / Fr(bl[("C", r2)]["producer_phase_wall_s"]).limit_denominator(10**12) for r2 in (1, 2, 3)])
    pi_c = med([Fr(bl[("PI", r2)]["complete_wall_s"]).limit_denominator(10**12) / Fr(bl[("C", r2)]["complete_wall_s"]).limit_denominator(10**12) for r2 in (1, 2, 3)])
    st["pi_decision"] = "PI_COMMON_CHECKER_GAIN" if pi_c <= THRESH["PI_over_C_complete"] else "PI_NO_COMMON_CHECKER_GAIN"
    if contended or not all_elig:
        why = ("timing ran under recorded contention (deviation 1); the frozen 0.5-core eligibility gate was not met, "
               "so no positive timing decision is available. Measured ratios are retained as contended diagnostics: "
               f"median PP/C complete {float(pp_c):.4f}, median PP/C producer {float(pp_p):.4f}, median PI/C complete {float(pi_c):.4f}. "
               f"Thresholds that WOULD have applied under a clean measurement: PP/C complete <= 0.50 {'met' if pp_c <= THRESH['PP_over_C_complete'] else 'not met'}, "
               f"PP/C producer <= 0.80 {'met' if pp_p <= THRESH['PP_over_C_producer'] else 'not met'}.")
        stop("INCONCLUSIVE_ENVIRONMENT", why, "decision"); st["outcome"] = "INCONCLUSIVE_ENVIRONMENT"
        st["withheld_decision"] = {"would_have_been": ("GO_TO_COMPLETE_QUERY_PILOT_DESIGN" if (pp_c <= THRESH["PP_over_C_complete"] and pp_p <= THRESH["PP_over_C_producer"]) else "NO_GO_FOR_THIS_KERNEL_IMPLEMENTATION"),
                                   "reason": "eligibility gate not met; frozen rule withholds a positive timing decision"}
    elif pp_c <= THRESH["PP_over_C_complete"] and pp_p <= THRESH["PP_over_C_producer"]:
        stop("GO_TO_COMPLETE_QUERY_PILOT_DESIGN", f"median PP/C complete {float(pp_c):.4f} <= 0.50 and median PP/C producer {float(pp_p):.4f} <= 0.80, all checks and nine eligible bundles pass", "decision")
        st["outcome"] = "GO_TO_COMPLETE_QUERY_PILOT_DESIGN"
    else:
        stop("NO_GO_FOR_THIS_KERNEL_IMPLEMENTATION", f"median PP/C complete {float(pp_c):.4f} (<=0.50 required), median PP/C producer {float(pp_p):.4f} (<=0.80 required)", "decision")
        st["outcome"] = "NO_GO_FOR_THIS_KERNEL_IMPLEMENTATION"
    save(); return finish(J, B, st, RUN)

def finish(J, B, st, RUN):
    ru = resource.getrusage(resource.RUSAGE_CHILDREN); rs = resource.getrusage(resource.RUSAGE_SELF)
    st["accounting"] = {"cumulative_commands_s": B.spent, "cap": CAPS["cumulative_commands_s"], "driver_elapsed_s": B.elapsed(),
                        "children_cpu_s": ru.ru_utime + ru.ru_stime, "driver_cpu_s": rs.ru_utime + rs.ru_stime,
                        "children_peak_rss_bytes": ru.ru_maxrss, "within_cap": B.spent <= CAPS["cumulative_commands_s"]}
    st["loadavg_end"] = os.getloadavg(); st["ended"] = now()
    dump(os.path.join(RUN, "state.json"), st)
    J.write({"kind": "driver_end", "outcome": st["outcome"], "accounting": st["accounting"]}); J.close()
    print(json.dumps({"outcome": st["outcome"], "stops": [s["code"] for s in st["stops"]], "ratios": st.get("ratios"),
                      "pi_decision": st.get("pi_decision"), "charged_s": round(B.spent, 1)}, default=str))

if __name__ == "__main__": main()
