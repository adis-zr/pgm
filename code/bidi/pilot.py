"""BIDI pilot stage runner: freeze (manifest), run (the frozen matrix, one cell per charged job through the repaired supervisor), status.
    python -m bidi.pilot freeze D
    python -m bidi.pilot run D
    python -m bidi.pilot status D
Arms: BIDI_NATIVE_CERT / BIDI_NATIVE_DUPLICATE_WORK / BIDI_MPFR53_CERT (bidi.cell), ADP_REPAIRED (adp.cell with the census's frozen
CONFIG_new_arm.json), EXACT_LIBDAI (bench.cells EXACT). Order: seeded, interleaved across cases, budgets and arms (published in the manifest).
Budget guard: before every launch the ledger is reconciled (nonnested; unresolved starts at max permitted) and the remaining maximum
commitment of all unlaunched cells + the 600 s closeout reserve must fit under the 10,800 s ceiling; otherwise the cell is recorded as
NOT_LAUNCHED_BUDGET and the run stops."""
from __future__ import annotations
import os, sys, json, time, hashlib, random, subprocess
HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__))); sys.path.insert(0, HERE)
from adp.census import run as CR
PY = sys.executable
CEILING_S = 10800.0; CLOSEOUT_RESERVE_S = 600.0; MATRIX_RESERVE_S = 3600.0; GRACE_S = 4.0; LAUNCH_OVERHEAD_S = 2.0; MEM_GIB = 8.0
THREAD_ENV = {"OMP_NUM_THREADS": "1", "OPENBLAS_NUM_THREADS": "1", "MKL_NUM_THREADS": "1", "VECLIB_MAXIMUM_THREADS": "1", "NUMEXPR_NUM_THREADS": "1", "PYTHONHASHSEED": "0"}
CASES = ["DBN_11", "DBN_12", "DBN_15", "DBN_16"]
PRIMARY_ARMS = ["BIDI_NATIVE_CERT", "ADP_REPAIRED", "EXACT_LIBDAI"]; DIAG_ARMS = ["BIDI_NATIVE_DUPLICATE_WORK", "BIDI_MPFR53_CERT"]
SEED = 20261109
CENSUS_D = os.path.join(HERE, "runs", "mdi_2026-10-28", "AGGREGATE_DP_CENSUS_2026-11-08")


def sha(p):
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for ch in iter(lambda: f.read(1 << 20), b""):
            h.update(ch)
    return h.hexdigest()


def ledger_path(D):
    return os.path.join(D, "PILOT_LEDGER.jsonl")


def charged(D):
    """Nonnested accounting over PILOT_LEDGER.jsonl (adp.census.run.charged reads CENSUS_LEDGER.jsonl; same rule, this ledger)."""
    p = ledger_path(D); rows = [json.loads(l) for l in open(p)] if os.path.exists(p) else []
    rec = {r["jid"]: r for r in rows if r["kind"] == "RECEIPT"}; total = 0.0; unresolved = []; by = {}
    for r in rows:
        if r["kind"] == "START":
            if r["jid"] in rec and not rec[r["jid"]].get("cleanup_unresolved"):
                total += rec[r["jid"]]["wall_s"]; by[r["scope"]] = by.get(r["scope"], 0.0) + rec[r["jid"]]["wall_s"]
            elif r["jid"] in rec:
                unresolved.append(dict(r, cleanup_unresolved=True)); total += max(rec[r["jid"]]["wall_s"], r.get("max_permitted_charge_s") or 0.0)
            else:
                unresolved.append(r); total += (r.get("max_permitted_charge_s") or 0.0)
    return total, by, unresolved


def order(seed):
    """Interleaved: for each case (seeded order) and budget (20 then 120), the primary arms rotated by a seeded offset; the two 120 s diagnostics
    follow their case's 120 s primaries, rotated too. No arm runs first for every case; no case is deferred to the end for every arm."""
    r = random.Random(seed); cases = list(CASES); r.shuffle(cases); cells = []
    for ci, case in enumerate(cases):
        for bi, b in enumerate((20.0, 120.0)):
            rot = (ci + bi + r.randrange(3)) % 3
            for a in PRIMARY_ARMS[rot:] + PRIMARY_ARMS[:rot]:
                cells.append({"arm": a, "case": case, "budget_s": b, "kind": "primary"})
            if b == 120.0:
                rot2 = r.randrange(2)
                for a in DIAG_ARMS[rot2:] + DIAG_ARMS[:rot2]:
                    cells.append({"arm": a, "case": case, "budget_s": b, "kind": "diagnostic"})
    return cells


def freeze(D):
    man_c = json.load(open(os.path.join(CENSUS_D, "CENSUS_MANIFEST.json"))); cases = {c["case"]: c for c in man_c["cases"]}
    br = json.load(open(os.path.join(HERE, "bidi", "BUILD_RECORD.json"))); cal = json.load(open(os.path.join(D, "LANE_CALIBRATION.json")))
    cfg_bidi = {"lanes_k": cal["frozen_lanes_k"], "block_steps": 4096, "precision": 53}
    cfg_adp_path = os.path.join(CENSUS_D, "CONFIG_new_arm.json")
    src = sorted("bidi/" + f for f in os.listdir(os.path.join(HERE, "bidi")) if f.endswith((".py", ".cpp"))) + ["tests/test_bidi_pilot.py", "adp/cell.py", "adp/checker.py", "adp/publish.py", "adp/engine.py", "adp/source.py", "adp/census/supervise.py", "adp/census/run.py", "bench/cells.py", "bench/libdai/libdai_mar", "ext/uai.py"] + sorted("mdi/" + f for f in os.listdir(os.path.join(HERE, "mdi")) if f.endswith(".py"))
    frozen_set_hash, _ = CR.frozen_set_hash()
    man = {"pass": "BIDI_NATIVE_PILOT_2026-11-09", "frozen_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "commit": CR.git_head(), "branch": subprocess.check_output(["git", "rev-parse", "--abbrev-ref", "HEAD"], cwd=HERE).decode().strip(),
           "parent_lineage": {"repaired_adp_commit": "ec4ae4274d120bccc6ea41f826a124743ace9d7a", "frozen_set_code_hash_now": frozen_set_hash, "census_supervisor_repair_commit": "9c487ad9fc4b0b9244eca157a826eeac0a641332", "branched_from": "0d0dc60cecc5bb6c1cd1d4dfb80511f79f28e334 (adp-census-2026-11-08 head)"},
           "source_files_sha256": {f: sha(os.path.join(HERE, f)) for f in src}, "kernel_build": br, "kernel_binary_sha256": br["binary_sha256"], "kernel_binary": br["binary"],
           "config_bidi": cfg_bidi, "lane_calibration": cal, "config_adp_repaired_path": os.path.relpath(cfg_adp_path, HERE), "config_adp_repaired_sha256": sha(cfg_adp_path), "libdai_binary_sha256": sha(os.path.join(HERE, "bench", "libdai", "libdai_mar")), "libdai_algorithm": "JTREE[inference=SUMPROD,updates=HUGIN,maxmem=8589934592]",
           "ceiling_s": CEILING_S, "closeout_reserve_s": CLOSEOUT_RESERVE_S, "matrix_reserve_s": MATRIX_RESERVE_S, "grace_s": GRACE_S, "launch_overhead_s": LAUNCH_OVERHEAD_S, "memory_budget_gib": MEM_GIB, "thread_env": THREAD_ENV, "seed": SEED,
           "query_contract": "every original singleton marginal; eps = 1/200; max width 1/100; exact dyadic-grid point; separate task-bound point verification",
           "cases": {c: {k: cases[c][k] for k in ("model_path", "evidence_path", "raw_model_sha256", "raw_evidence_sha256", "canonical_model_sha256", "canonical_evidence_sha256", "variables")} for c in CASES}, "cells": []}
    for i, c in enumerate(order(SEED)):
        cs = cases[c["case"]]; task = {"model": cs["canonical_model_sha256"], "evidence": cs["canonical_evidence_sha256"], "raw_model": cs["raw_model_sha256"], "raw_evidence": cs["raw_evidence_sha256"], "queries": "all_original_variables", "arm": c["arm"], "budget_s": c["budget_s"], "memory_gib": MEM_GIB, "grace_s": GRACE_S, "kind": c["kind"]}
        tid = hashlib.sha256(json.dumps(task, sort_keys=True).encode()).hexdigest()[:16]
        man["cells"].append(dict(c, index=i, task_id=tid, cell_id=hashlib.sha256((tid + "|" + man["commit"] + "|" + br["binary_sha256"]).encode()).hexdigest()[:16], out_dir="cells/%02d__%s__%s__%ds__%s" % (i, c["case"], c["arm"], int(c["budget_s"]), tid), max_permitted_charge_s=c["budget_s"] + GRACE_S + LAUNCH_OVERHEAD_S))
    man["counts"] = {"cells": len(man["cells"]), "nominal_s": sum(c["budget_s"] for c in man["cells"]), "max_permitted_s": sum(c["max_permitted_charge_s"] for c in man["cells"])}
    json.dump(man, open(os.path.join(D, "PILOT_MANIFEST.json"), "w"), indent=1); json.dump(cfg_bidi, open(os.path.join(D, "CONFIG_bidi.json"), "w"), indent=1)
    print(json.dumps({"cells": man["counts"], "commit": man["commit"], "kernel": br["binary_sha256"][:12], "lanes_k": cfg_bidi["lanes_k"]}))


def run(D):
    man = json.load(open(os.path.join(D, "PILOT_MANIFEST.json")))
    head = CR.git_head()
    if subprocess.run(["git", "diff", "--quiet", man["commit"], head, "--"] + list(man["source_files_sha256"]), cwd=HERE).returncode != 0:
        raise SystemExit("a frozen source file differs between the frozen commit %s and HEAD %s" % (man["commit"], head))     # records-only commits after the freeze are allowed
    if subprocess.run(["git", "status", "--porcelain", "--"] + list(man["source_files_sha256"]), cwd=HERE, capture_output=True, text=True).stdout.strip():
        raise SystemExit("uncommitted change to a frozen source file")
    br = json.load(open(os.path.join(HERE, "bidi", "BUILD_RECORD.json")))
    if br["binary_sha256"] != man["kernel_binary_sha256"] or sha(os.path.join(HERE, br["binary"])) != br["binary_sha256"]:
        raise SystemExit("kernel binary differs from the frozen manifest")
    for f, h in man["source_files_sha256"].items():
        if sha(os.path.join(HERE, f)) != h:
            raise SystemExit("frozen source file changed: %s" % f)
    ledger = ledger_path(D); cfg_bidi = os.path.join(D, "CONFIG_bidi.json"); cfg_adp = os.path.join(HERE, man["config_adp_repaired_path"])
    open(os.path.join(D, "matrix_started.txt"), "a").write("started %s head %s\n" % (time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), head))
    launched = []
    for c in man["cells"]:
        out = os.path.join(D, c["out_dir"])
        if os.path.exists(os.path.join(out, "cell.json")) or os.path.exists(os.path.join(out, "NOT_LAUNCHED.json")):
            continue                                                                                 # already resolved: never rerun a cell
        total, by, unresolved = charged(D); remaining_commit = sum(x["max_permitted_charge_s"] for x in man["cells"] if not os.path.exists(os.path.join(D, x["out_dir"], "cell.json")))
        if unresolved:
            json.dump({"status": "NOT_LAUNCHED_UNRESOLVED_CLEANUP", "unresolved": [u["job"] for u in unresolved]}, open(os.path.join(D, "RUN_STOPPED.json"), "w")); print("STOP: unresolved start/cleanup in the ledger"); return
        if total + remaining_commit + CLOSEOUT_RESERVE_S > CEILING_S:
            os.makedirs(out, exist_ok=True); json.dump({"status": "NOT_LAUNCHED_BUDGET", "charged_s": total, "remaining_commit_s": remaining_commit, "reserve_s": CLOSEOUT_RESERVE_S, "ceiling_s": CEILING_S}, open(os.path.join(out, "NOT_LAUNCHED.json"), "w")); print("STOP: budget guard"); return
        os.makedirs(out, exist_ok=True); cs = man["cases"][c["case"]]; mp = os.path.join(HERE, cs["model_path"]); ep = os.path.join(HERE, cs["evidence_path"])
        if c["arm"] in ("BIDI_NATIVE_CERT", "BIDI_NATIVE_DUPLICATE_WORK", "BIDI_MPFR53_CERT"):
            inner = [PY, "-m", "bidi.cell", c["arm"], mp, ep, out, "%.3f" % c["budget_s"], cfg_bidi]
        elif c["arm"] == "ADP_REPAIRED":
            inner = [PY, "-m", "adp.cell", mp, ep, out, "%.3f" % c["budget_s"], cfg_adp]
        else:
            inner = [PY, "-m", "bench.cells", "EXACT", mp, ep, out, "%.3f" % c["budget_s"], "{}"]
        cmd = [PY, "-m", "adp.census.supervise", "--ledger", ledger, "--scope", "matrix_" + c["kind"], "--job", "cell:%02d:%s:%s:%ds" % (c["index"], c["case"], c["arm"], int(c["budget_s"])), "--timeout", "%.3f" % c["budget_s"], "--mem-gib", str(MEM_GIB), "--cwd", HERE,
               "--stdout", os.path.join(out, "supervisor.log"), "--stderr", os.path.join(out, "supervisor.log")] + [x for k, v in THREAD_ENV.items() for x in ("--env", "%s=%s" % (k, v))] + ["--env", "PYTHONPATH=" + HERE, "--"] + inner
        t = time.monotonic(); subprocess.run(cmd, cwd=HERE); wall = time.monotonic() - t
        rec = None
        if os.path.exists(os.path.join(out, "cell.json")):
            rec = json.load(open(os.path.join(out, "cell.json")))
        else:
            json.dump({"status": "NO_RECORD", "note": "the cell process left no cell.json (killed before writing); see supervisor.log / progress.json"}, open(os.path.join(out, "cell.json"), "w"))
        launched.append({"index": c["index"], "arm": c["arm"], "case": c["case"], "budget_s": c["budget_s"], "outer_wall_s": wall, "status": (rec or {}).get("status", "NO_RECORD"), "complete_response_s": (rec or {}).get("complete_response_s")})
        print("%-3d %-28s %-8s %4ds  %-36s %7.2fs" % (c["index"], c["arm"], c["case"], int(c["budget_s"]), launched[-1]["status"], launched[-1]["complete_response_s"] or 0), flush=True)
    open(os.path.join(D, "matrix_finished.txt"), "a").write("finished %s\n" % time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()))
    total, by, unresolved = charged(D); print("matrix done; charged total %.1f s of %.0f; by scope %s; unresolved %d" % (total, CEILING_S, {k: round(v, 1) for k, v in by.items()}, len(unresolved)))


def status(D):
    total, by, unresolved = charged(D); print(json.dumps({"charged_s": round(total, 3), "by_scope": {k: round(v, 3) for k, v in by.items()}, "unresolved": [u["job"] for u in unresolved]}))


if __name__ == "__main__":
    {"freeze": freeze, "run": run, "status": status}[sys.argv[1]](os.path.abspath(sys.argv[2]))
