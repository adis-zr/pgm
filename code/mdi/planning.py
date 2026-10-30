"""The bounded external PLANNING observation (Gate A).

One baseline-plan and one research-plan pass per input through the normal
public pipeline in planning-only mode: discovery, persisted binding, pricing
and selection run; the numerical guard refuses every executor and checker
entry; no reference marginal is read; no sampler or numerical arm is launched.
Each pass runs in a FRESH child process under a hard outer supervisor: the
600 s overall ceiling, the 8 GiB whole-tree RSS ceiling (sampled by the
supervisor across the process tree), thread limits in the environment, and a
fresh directory per input and arm. Parsing and every durable write are inside
the observed elapsed time. Progress is persisted at every stage transition and
about every 30 s with the last completed candidate and the charged work. The
terminal record is explicit even on refusal, timeout or crash.

    python -m mdi.planning RUNDIR [Grids_11 Pedigree_11 Promedus_12] [--eps 1/100]

The scored reference files (*.MAR) are never opened: the child receives only
the model and evidence paths and refuses to open any other file in the input
directory.
"""
from __future__ import annotations
import sys, os, json, time, hashlib, subprocess, tempfile, signal, resource
sys.set_int_max_str_digits(0)
from fractions import Fraction as Fr

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PKT = "/tmp/tep/three_external_problems/inputs"
PROBLEMS = ("Grids_11", "Pedigree_11", "Promedus_12")
THREAD_ENV = {"OMP_NUM_THREADS": "6", "MKL_NUM_THREADS": "6", "OPENBLAS_NUM_THREADS": "6",
              "VECLIB_MAXIMUM_THREADS": "6", "NUMEXPR_NUM_THREADS": "6"}
HEARTBEAT_S = 30.0


def sha256_file(p):
    h = hashlib.sha256()
    with open(p, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def driver_hashes():
    """Hashes of the driver and configuration that govern a pass."""
    out = {}
    for rel in ("mdi/planning.py", "mdi/pipeline.py", "mdi/pricing.py", "mdi/collective_route.py",
                "mdi/modes.py", "mdi/residual.py", "mdi/regions.py", "mdi/config.py", "mdi/budget.py",
                "mdi/guard.py"):
        p = os.path.join(HERE, rel)
        if os.path.exists(p):
            out[rel] = sha256_file(p)
    return out


# ------------------------------------------------------------------ child

def _child(model_path, evid_path, rundir, label, research, eps, wall, cap):
    """One planning pass in THIS process (the supervisor spawns it)."""
    sys.path.insert(0, HERE)
    from mdi import model as M, pipeline as PLN, config as K, guard as GD, budget as B
    import mdi.registry            # noqa: F401
    t0 = time.monotonic()
    prog_path = os.path.join(rundir, "progress_%s.jsonl" % label)
    term_path = os.path.join(rundir, "terminal_%s.json" % label)
    state = {"phase": "init", "last_completed_candidate": None, "charged": {}, "events": 0}
    last = [0.0]

    def write_progress(force=False):
        now = time.monotonic()
        if force or now - last[0] >= HEARTBEAT_S:
            last[0] = now
            with open(prog_path, "a") as fh:
                fh.write(json.dumps({"t": round(now - t0, 3), **state}, default=str) + "\n")

    def progress(phase, info=""):
        state["events"] += 1
        new_phase = phase != state["phase"]
        state["phase"] = phase
        state["info"] = str(info)[:200]
        if phase in ("select", "persist") or "candidate" in str(info) or ":" in str(info):
            state["last_completed_candidate"] = str(info)[:120]
        write_progress(force=new_phase)

    rec = {"label": label, "arm": "research" if research else "baseline", "status": "STARTED",
           "eps": str(eps), "wall_s": wall, "cap_bytes": cap, "threads_declared": K.RESOURCES["threads"],
           "phase_limits": dict(B.Budget.PHASE_LIMITS), "started": time.strftime("%Y-%m-%d %H:%M:%S")}
    # the terminal record EXISTS from the first instant (a crash leaves it)
    with open(term_path, "w") as fh:
        json.dump(rec, fh, indent=1, default=str)
    try:
        progress("parse", "reading %s" % os.path.basename(model_path))
        m = M.read_uai(model_path)
        ev = M.read_evidence(evid_path, m) if evid_path else {}
        r0 = M.restrict(m, ev)
        queries = set(r0.free)
        rec["query_keys"] = {"variables": sorted(queries), "states": sum(m.card[v] for v in queries),
                             "observed": {str(v): int(st) for v, st in sorted(ev.items())}}
        rec["input_sha256"] = {"model": sha256_file(model_path),
                               "evidence": (sha256_file(evid_path) if evid_path else None)}
        pdir = os.path.join(rundir, "plans_%s" % label)
        res = PLN.solve(m, ev, queries=queries, max_width=eps, wall_s=max(1.0, wall - (time.monotonic() - t0)),
                        cap_bytes=cap, research_enabled=research, plan_dir=pdir,
                        progress=progress, plan_only=True)
        progress("terminal", res.status)
        rec.update({"status": res.status, "reason": res.reason, "plan": res.plan,
                    "prices": res.prices, "rejected": res.rejected, "stages": res.stages,
                    "budget": res.budget, "preprocess": res.preprocess,
                    "guard_entries_touched": list(GD.ENTRIES),
                    "plan_files": sorted(os.listdir(pdir)) if os.path.isdir(pdir) else []})
        # candidate / verified residual scopes and occupied vs forecast states,
        # read from the PERSISTED programs (never from live discovery objects)
        scopes = {}
        for p in res.prices:
            ident = p.get("identity")
            fp = os.path.join(pdir, "%s.plan.json" % ident) if ident else None
            if fp and os.path.exists(fp):
                prog = json.load(open(fp)).get("program") or {}
                coll = prog.get("collective")
                scopes[p["name"]] = {
                    "kind": prog.get("kind"), "levels": len(prog.get("scales") or []),
                    "regions": [len(rg["region"]) for sc in (prog.get("scales") or []) for rg in sc["regions"]][:16],
                    "cells": [len(rg["cells"]) for sc in (prog.get("scales") or []) for rg in sc["regions"]][:16],
                    "deleted": sum(len(rg["deleted"]) for sc in (prog.get("scales") or []) for rg in sc["regions"]),
                    "collective": (None if coll is None else {
                        "evaluator": coll["evaluator"], "kind": coll["candidate"]["kind"],
                        "signs": coll["candidate"]["signs"], "strict": coll["candidate"].get("strict"),
                        "masked_pairs": len(coll["candidate"].get("masked") or []),
                        "kept_factors": len(coll["kept_factors"]), "dropped_pairs": len(coll["dropped_pairs"]),
                        "Q": coll.get("Q"), "grids": [g["nodes"] for g in (coll.get("grids") or [])]}),
                    "final_variables": ((p["counters"].get("final_variables") or {}).get("value")),
                    "final_largest_bag": ((p["counters"].get("final_largest_bag") or {}).get("value")),
                    "statistic_support_bound": ((p["counters"].get("statistic_support_bound") or {}).get("value")),
                    "metered_entries_forecast": ((p["counters"].get("metered_entries_forecast") or {}).get("value")),
                    "feasibility": p.get("feasibility"), "eligible": p["eligible"],
                    "refusal": p.get("ineligible_reason")}
        # plans COMPLETED before the allowance ran out but not repriced are on
        # disk: report their scopes too, labelled unbound
        priced_ids = {p.get("identity") for p in res.prices}
        for fn in sorted(os.listdir(pdir)) if os.path.isdir(pdir) else []:
            ident = fn[:-len(".plan.json")] if fn.endswith(".plan.json") else None
            if not ident or ident in priced_ids:
                continue
            try:
                rec_j = json.load(open(os.path.join(pdir, fn)))
            except Exception:
                continue
            prog = rec_j.get("program") or {}
            coll = prog.get("collective")
            scopes[rec_j.get("name", ident)] = {
                "bound": False, "note": "completed before the construction allowance ran out; not repriced",
                "kind": prog.get("kind"), "levels": len(prog.get("scales") or []),
                "regions": [len(rg["region"]) for sc in (prog.get("scales") or []) for rg in sc["regions"]][:16],
                "cells": [len(rg["cells"]) for sc in (prog.get("scales") or []) for rg in sc["regions"]][:16],
                "deleted": sum(len(rg["deleted"]) for sc in (prog.get("scales") or []) for rg in sc["regions"]),
                "collective": (None if coll is None else {
                    "evaluator": coll["evaluator"], "kind": coll["candidate"]["kind"], "signs": coll["candidate"]["signs"],
                    "strict": coll["candidate"].get("strict"), "masked_pairs": len(coll["candidate"].get("masked") or []),
                    "kept_factors": len(coll["kept_factors"]), "dropped_pairs": len(coll["dropped_pairs"]),
                    "Q": coll.get("Q"), "grids": [g["nodes"] for g in (coll.get("grids") or [])]}),
                "recorded_counters": {k: (rec_j.get("cost_counters") or {}).get(k, {}).get("value")
                                      for k in ("final_variables", "final_largest_bag", "statistic_support_bound",
                                                "metered_entries_forecast", "producer_upward_ops", "checker_ops")}}
        rec["candidate_scopes"] = scopes
        rec["refusals"] = [{"name": x.get("name"), "typed": x.get("typed") or "CANDIDATE_REFUSAL",
                            "phase": x.get("phase"), "reason": str(x.get("reason"))[:240]} for x in (res.rejected or [])]
    except Exception as e:
        import traceback
        rec.update({"status": "PLANNING_CRASH", "reason": "%s: %s" % (type(e).__name__, e),
                    "traceback": traceback.format_exc()[-2000:]})
    rec["elapsed_s"] = round(time.monotonic() - t0, 3)
    rec["peak_rss_self_bytes"] = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    progress("done", rec["status"])
    write_progress(force=True)
    with open(term_path, "w") as fh:
        json.dump(rec, fh, indent=1, default=str)
    rec["durable_write_s"] = round(time.monotonic() - t0, 3)
    with open(term_path, "w") as fh:
        json.dump(rec, fh, indent=1, default=str)
    return rec


# ------------------------------------------------------------- supervisor

def _tree_rss_bytes(pid):
    """Whole process-tree RSS (bytes) via ps, sampled by the supervisor."""
    try:
        out = subprocess.run(["ps", "-o", "pid=,ppid=,rss=", "-ax"], capture_output=True, text=True, timeout=5).stdout
    except Exception:
        return None
    rows = []
    for line in out.splitlines():
        parts = line.split()
        if len(parts) >= 3:
            try:
                rows.append((int(parts[0]), int(parts[1]), int(parts[2]) * 1024))
            except ValueError:
                pass
    tree = {pid}
    changed = True
    while changed:
        changed = False
        for p, pp, _ in rows:
            if pp in tree and p not in tree:
                tree.add(p)
                changed = True
    return sum(r for p, _, r in rows if p in tree)


def run_pass(problem, research, rundir, eps=None, wall=None, cap=None, model_path=None, evid_path=None):
    """Supervise one planning pass in a fresh child process."""
    from mdi import config as K
    eps = Fr(eps) if eps is not None else K.MAX_WIDTH
    wall = float(wall or K.RESOURCES["arm_wall_s"])
    cap = int(cap or K.RESOURCES["arm_rss_bytes"])
    label = "%s_%s" % (problem, "research" if research else "baseline")
    os.makedirs(rundir, exist_ok=True)
    mp = model_path or os.path.join(PKT, problem + ".uai")
    ep = evid_path if evid_path is not None else os.path.join(PKT, problem + ".uai.evid")
    pre = {"label": label, "problem": problem, "arm": "research" if research else "baseline",
           "input_sha256": {"model": sha256_file(mp), "evidence": (sha256_file(ep) if ep and os.path.exists(ep) else None)},
           "eps": str(eps), "wall_s": wall, "cap_bytes": cap, "threads": THREAD_ENV,
           "driver_hashes": driver_hashes(), "fixed_order": "baseline then research, per input in packet order",
           "reference_files_opened": False, "recorded_before_start": time.strftime("%Y-%m-%d %H:%M:%S")}
    with open(os.path.join(rundir, "prestart_%s.json" % label), "w") as fh:
        json.dump(pre, fh, indent=1)
    env = dict(os.environ)
    env.update(THREAD_ENV)
    env["PYTHONPATH"] = HERE
    code = ("import sys; sys.path.insert(0, %r); from mdi import planning as P; "
            "P._child(%r, %r, %r, %r, %r, %r, %r, %r)"
            % (HERE, mp, ep if (ep and os.path.exists(ep)) else None, rundir, label, bool(research),
               str(eps), wall, cap))
    t0 = time.monotonic()
    proc = subprocess.Popen([sys.executable, "-c", code], cwd=HERE, env=env,
                            stdout=subprocess.DEVNULL, stderr=open(os.path.join(rundir, "stderr_%s.log" % label), "w"))
    peak_tree = 0
    stop = None
    while True:
        rc = proc.poll()
        if rc is not None:
            break
        el = time.monotonic() - t0
        rss = _tree_rss_bytes(proc.pid)
        if rss is not None:
            peak_tree = max(peak_tree, rss)
            if rss > cap:
                stop = {"kind": "rss_tree", "used": rss, "limit": cap, "at_s": round(el, 1)}
                proc.send_signal(signal.SIGKILL)
                break
        if el > wall + 5.0:
            stop = {"kind": "wall", "used": round(el, 1), "limit": wall, "at_s": round(el, 1)}
            proc.send_signal(signal.SIGKILL)
            break
        time.sleep(0.5)
    proc.wait()
    elapsed = time.monotonic() - t0
    term_path = os.path.join(rundir, "terminal_%s.json" % label)
    term = json.load(open(term_path)) if os.path.exists(term_path) else {"status": "NO_TERMINAL_RECORD"}
    if stop is not None:
        term["status"] = "PLANNING_RESOURCE_STOP"
        term["supervisor_stop"] = stop
        term["reason"] = "the supervisor stopped the pass: %s" % stop
    term["supervisor"] = {"elapsed_s": round(elapsed, 3), "peak_tree_rss_bytes": peak_tree,
                          "child_exit": proc.returncode, "wall_s": wall, "cap_bytes": cap}
    with open(term_path, "w") as fh:
        json.dump(term, fh, indent=1, default=str)
    return term


def main(argv):
    rundir = argv[0] if argv else tempfile.mkdtemp(prefix="mdi_planning_")
    probs = [a for a in argv[1:] if not a.startswith("--")] or list(PROBLEMS)
    eps = None
    if "--eps" in argv:
        eps = Fr(argv[argv.index("--eps") + 1])
    summary = []
    for prob in probs:
        for research in (False, True):
            d = os.path.join(rundir, "%s_%s" % (prob, "research" if research else "baseline"))
            os.makedirs(d, exist_ok=True)
            print("[planning] %s %s ..." % (prob, "research" if research else "baseline"), flush=True)
            term = run_pass(prob, research, d, eps=eps)
            row = {"problem": prob, "arm": "research" if research else "baseline", "status": term.get("status"),
                   "chosen": (term.get("plan") or {}).get("chosen"), "elapsed_s": term.get("supervisor", {}).get("elapsed_s"),
                   "peak_tree_rss_bytes": term.get("supervisor", {}).get("peak_tree_rss_bytes")}
            print("[planning] %-28s %-22s chosen=%s %.1fs" % (prob + " " + row["arm"], row["status"], row["chosen"],
                                                              row["elapsed_s"] or 0), flush=True)
            summary.append(row)
    with open(os.path.join(rundir, "PLANNING_SUMMARY.json"), "w") as fh:
        json.dump({"rows": summary, "rundir": rundir, "built": time.strftime("%Y-%m-%d %H:%M:%S")}, fh, indent=1)
    print(json.dumps(summary, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
