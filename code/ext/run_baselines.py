"""Run the author ARB and Merlin IJGP baselines on one problem (one invocation each).

Frozen settings come from the released experiment script (ARB) and the
documented defaults (Merlin). No tuning. One invocation per method/problem.
"""
from __future__ import annotations
import os, sys, json, time, shutil, subprocess
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from ext import supervise

PKT = "/tmp/tep/three_external_problems/inputs"
GRAMPLE = "/tmp/tep/grample"
MERLIN = "/tmp/tep/merlin/build/merlin"
OUTER_DEADLINE_S = 600.0
MEM_LIMIT_KIB = 8 * 1024 * 1024   # 8 GiB
THREADS = 6

# Released experiment-script settings (script/experiment @ 6b453b2)
ARB = dict(burnin=2000, chains=2, chainadds=4, cwin=2000, maxsecs=300,
           sampler="adaptive", seed=1)


def run_arb(problem, rundir):
    """Reproduce the released schedule, preserving --solution and --experiment."""
    work = os.path.join(rundir, "arb_work")
    os.makedirs(os.path.join(work, "res"), exist_ok=True)
    for ext in (".uai", ".uai.evid", ".uai.MAR", ".uai.merlin.MAR"):
        shutil.copy2(os.path.join(PKT, problem + ext), os.path.join(work, "res", problem + ext))
    shutil.copy2(os.path.join(GRAMPLE, "grample"), os.path.join(work, "grample"))
    trace = os.path.join(work, problem + ".trace")
    cmd = [os.path.join(work, "grample"), "sample",
           "--experiment", "--evidence", "--solution",
           "--sampler", ARB["sampler"],
           "--burnin", str(ARB["burnin"]),
           "--chains", str(ARB["chains"]),
           "--chainadds", str(ARB["chainadds"]),
           "--cwin", str(ARB["cwin"]),
           "--maxsecs", str(ARB["maxsecs"]),
           "--seed", str(ARB["seed"]),
           "--trace", trace,
           "--model", os.path.join("res", problem + ".uai")]
    log = os.path.join(rundir, "arb_%s.log" % problem)
    rec = supervise.run(cmd, work, log, OUTER_DEADLINE_S, MEM_LIMIT_KIB,
                        env={"GOMAXPROCS": str(THREADS)}, label="ARB/" + problem)
    rec.update({"method": "ARB", "problem": problem, "settings": dict(ARB),
                "threads_declared": THREADS, "trace": trace,
                "marginals_file": None})
    # grample writes <model>.MAR-style output? locate any produced marginal file
    produced = []
    for root, _, files in os.walk(work):
        for f in files:
            if f.endswith(".MAR") and "res/" not in os.path.join(root, f):
                produced.append(os.path.join(root, f))
    rec["produced_files"] = sorted(set(produced))
    return rec


def run_merlin(problem, rundir):
    """Documented default IJGP configuration; prints resolved i-bound/iterations."""
    work = os.path.join(rundir, "merlin_work")
    os.makedirs(work, exist_ok=True)
    mdl = os.path.join(PKT, problem + ".uai")
    evd = os.path.join(PKT, problem + ".uai.evid")
    outp = os.path.join(work, problem + ".ijgp")
    cmd = [MERLIN, "-f", mdl, "-e", evd, "-a", "ijgp", "-t", "MAR",
           "-o", outp, "-v", "1"]
    log = os.path.join(rundir, "merlin_%s.log" % problem)
    rec = supervise.run(cmd, work, log, OUTER_DEADLINE_S, MEM_LIMIT_KIB,
                        label="IJGP/" + problem)
    rec.update({"method": "IJGP", "problem": problem,
                "settings": {"algorithm": "ijgp", "task": "MAR",
                             "ibound": "default 2", "iterations": "default 10",
                             "order": "MinFill", "note": "resolved values printed by solver; see log"},
                "threads_declared": THREADS,
                "threads_actual": "single-threaded (no OpenMP/pthread in ijgp.cpp)",
                "output_file": outp})
    cands = [outp, outp + ".MAR", outp + ".mar"]
    for root, _, files in os.walk(work):
        for f in files:
            cands.append(os.path.join(root, f))
    rec["produced_files"] = sorted(set(p for p in cands if os.path.exists(p)))
    return rec


if __name__ == "__main__":
    problem, which, rundir = sys.argv[1], sys.argv[2], os.path.abspath(sys.argv[3])
    os.makedirs(rundir, exist_ok=True)
    fn = {"arb": run_arb, "merlin": run_merlin}[which]
    rec = fn(problem, rundir)
    out = os.path.join(rundir, "%s_%s_record.json" % (which, problem))
    json.dump(rec, open(out, "w"), indent=2)
    print(json.dumps({k: v for k, v in rec.items() if k != "cmd"}, indent=2))
