"""Census-pass harness: freeze -> primary (92 full-arm cells: 46 x 20 s then 46 x 120 s) -> diag (46 instrumented cells at 20 s) -> status.

    python -m adp.census.run freeze   D
    python -m adp.census.run primary  D
    python -m adp.census.run diag     D
    python -m adp.census.run status   D

Primary cells run the UNCHANGED repaired arm (adp.cell at the repaired pin; code hash of the frozen set must equal the recorded
baseline hash) with the historical CONFIG_new_arm.json bytes. Diagnostic cells run adp.census.diag_cell (observation only; same
semantics / configuration). Every cell is a separately charged job through adp.census.supervise (START record before launch, receipt in
finally, process-group kill by recorded pgid); each cell gets an immutable directory named by its cell id; a second attempt gets a new
directory and an explicit predecessor link (never an overwrite). Stage admission: a cell is launched only if its maximum permitted charge
(budget + grace + launch overhead) fits the stage envelope AND leaves the closeout reserve of the 10,800 s ceiling.
"""
from __future__ import annotations
import os, sys, json, time, hashlib, subprocess, shutil
HERE = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))); sys.path.insert(0, HERE)
PY = os.path.join(HERE, ".venv", "bin", "python")
OLD = os.path.join(HERE, "runs", "mdi_2026-10-28", "EXTERNAL_SWEEP_2026-11-06")
PREV = os.path.join(HERE, "runs", "mdi_2026-10-28", "AGGREGATE_DP_2026-11-07")
BASELINE = {"repaired_commit": "ec4ae4274d120bccc6ea41f826a124743ace9d7a", "code_hash": "da5b2c49b1bd34d181fa1a18f123304d1cfb4f651a995c5f82081dff05500404", "r3_archive_sha256": "6745898cb6589ba0ff98f868c3aed3c4757b92d4448889757f50f121b701a706"}
CEILING_S = 10800.0; ENVELOPES = {"setup_qualification": 600.0, "primary": 7000.0, "diagnostics": 1500.0, "analysis_package": 1200.0, "reserve": 500.0}
GRACE_S = 4.0; LAUNCH_OVERHEAD_S = 2.0; MEM_GIB = 8.0
THREAD_ENV = {"OMP_NUM_THREADS": "1", "OPENBLAS_NUM_THREADS": "1", "MKL_NUM_THREADS": "1", "VECLIB_MAXIMUM_THREADS": "1", "NUMEXPR_NUM_THREADS": "1", "PYTHONHASHSEED": "0"}


def sha_file(p):
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for ch in iter(lambda: f.read(1 << 20), b""):
            h.update(ch)
    return h.hexdigest()


def frozen_set_hash():
    """The campaign rule's code hash (adp/*.py top level + bench/cells.py + libdai + ext + mdi/*.py)."""
    from adp import campaign as C
    return C.code_hash()


def harness_hash():
    files = sorted("adp/census/" + f for f in os.listdir(os.path.join(HERE, "adp", "census")) if f.endswith(".py")) + ["tests/test_adp_census.py"]
    h = hashlib.sha256(); per = {}
    for f in files:
        p = os.path.join(HERE, f)
        if os.path.exists(p):
            d = sha_file(p); per[f] = d; h.update(f.encode()); h.update(d.encode())
    return h.hexdigest(), per


def git_head():
    return subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=HERE).decode().strip()


def ledger_rows(D):
    p = os.path.join(D, "CENSUS_LEDGER.jsonl")
    return [json.loads(l) for l in open(p)] if os.path.exists(p) else []


def charged(D):
    """Nonnested accounting: every RECEIPT once; every START without a RECEIPT counts its max permitted charge (UNRESOLVED)."""
    rows = ledger_rows(D); rec = {r["jid"]: r for r in rows if r["kind"] == "RECEIPT"}; total = 0.0; unresolved = []
    for r in rows:
        if r["kind"] == "START":
            if r["jid"] in rec:
                total += rec[r["jid"]]["wall_s"]
            else:
                unresolved.append(r); total += (r.get("max_permitted_charge_s") or 0.0)
    by_scope = {}
    for r in rows:
        if r["kind"] == "RECEIPT":
            by_scope[r["scope"]] = by_scope.get(r["scope"], 0.0) + r["wall_s"]
    return total, by_scope, unresolved


def freeze(D):
    ch, per = frozen_set_hash(); assert ch == BASELINE["code_hash"], "frozen-set code hash %s differs from the repaired baseline %s" % (ch[:12], BASELINE["code_hash"][:12])
    hh, hper = harness_hash()
    man_prev = json.load(open(os.path.join(PREV, "CAMPAIGN_MANIFEST.json"))); cases = man_prev["cases"]
    for c in cases:
        assert sha_file(os.path.join(HERE, c["model_path"])) == c["raw_model_sha256"] and sha_file(os.path.join(HERE, c["evidence_path"])) == c["raw_evidence_sha256"], "input bytes of %s differ" % c["case"]
    cfg_src = os.path.join(PREV, "CONFIG_new_arm.json"); cfg_bytes = open(cfg_src, "rb").read(); cfg_dst = os.path.join(D, "CONFIG_new_arm.json"); open(cfg_dst, "wb").write(cfg_bytes)
    cfg_sha = hashlib.sha256(cfg_bytes).hexdigest(); assert cfg_sha == sha_file(cfg_src)
    order = list(man_prev["case_order"])
    man = {"pass": "AGGREGATE_DP_CENSUS_2026-11-08", "frozen_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "commit": git_head(), "baseline": BASELINE, "frozen_set_code_hash": ch, "frozen_set_files_sha256": per, "harness_hash": hh, "harness_files_sha256": hper,
           "config_new_arm_sha256": cfg_sha, "config_new_arm_bytes": cfg_bytes.decode(), "config_source": os.path.relpath(cfg_src, HERE), "previous_manifest": os.path.relpath(os.path.join(PREV, "CAMPAIGN_MANIFEST.json"), HERE),
           "ceiling_s": CEILING_S, "envelopes_s": ENVELOPES, "grace_s": GRACE_S, "launch_overhead_s": LAUNCH_OVERHEAD_S, "memory_budget_gib": MEM_GIB, "thread_env": THREAD_ENV,
           "order_rule": "historical manifest case order; all 20 s primary cells, then all 120 s primary cells, then all 20 s diagnostic cells", "case_order": order, "cases": cases, "inaccessible_slots": man_prev["inaccessible_slots"],
           "query_contract": "every original variable (observed variables as point masses); bound independently at checking and publication", "cells": []}
    def add(stage, budget, c, kind):
        task = {"model": c["canonical_model_sha256"], "evidence": c["canonical_evidence_sha256"], "queries": "all_original_variables", "arm": "AGGREGATE_DP_V1", "config_sha256": cfg_sha, "budget_s": budget, "memory_gib": MEM_GIB, "grace_s": GRACE_S, "kind": kind}
        tid = hashlib.sha256(json.dumps(task, sort_keys=True).encode()).hexdigest()[:16]; cid = hashlib.sha256((tid + "|" + ch + "|" + hh).encode()).hexdigest()[:16]
        man["cells"].append({"cell_id": cid, "task_id": tid, "task": task, "stage": stage, "kind": kind, "case": c["case"], "family": c["family"], "budget_s": budget, "model_path": c["model_path"], "evidence_path": c["evidence_path"], "raw_model_sha256": c["raw_model_sha256"], "raw_evidence_sha256": c["raw_evidence_sha256"]})
    byname = {c["case"]: c for c in cases}
    for b in (20.0, 120.0):
        for name in order:
            add("primary", b, byname[name], "primary")
    for name in order:
        add("diag", 20.0, byname[name], "diagnostic")
    man["counts"] = {"primary": 92, "diag": 46, "nominal_primary_s": 92 * 70.0, "max_permitted_primary_s": sum(c["budget_s"] + GRACE_S + LAUNCH_OVERHEAD_S for c in man["cells"] if c["stage"] == "primary")}
    mp = os.path.join(D, "CENSUS_MANIFEST.json")
    if os.path.exists(mp):
        prior = json.load(open(mp)); dst = os.path.join(D, "CENSUS_MANIFEST_prior_%s.json" % prior["frozen_utc"].replace(":", "").replace("-", "")); os.replace(mp, dst); man["prior_manifests"] = (prior.get("prior_manifests") or []) + [os.path.basename(dst)]
    json.dump(man, open(mp, "w"), indent=1); print("frozen:", man["counts"], "commit", man["commit"][:12], "frozen-set", ch[:12], "harness", hh[:12])


def run_stage(D, stage):
    man = json.load(open(os.path.join(D, "CENSUS_MANIFEST.json"))); ch, _ = frozen_set_hash(); hh, _ = harness_hash()
    assert ch == man["frozen_set_code_hash"], "frozen-set code hash changed since the freeze"
    assert hh == man["harness_hash"], "harness hash changed since the freeze: amend + re-freeze"
    cells = [c for c in man["cells"] if c["stage"] == stage]; done = {}
    for l in (open(os.path.join(D, "CELLS_LEDGER.jsonl")) if os.path.exists(os.path.join(D, "CELLS_LEDGER.jsonl")) else []):
        r = json.loads(l); done[r["cell_id"]] = r
    env_scope = {"primary": "primary", "diag": "diagnostics"}[stage]; envelope = ENVELOPES[env_scope]
    for c in cells:
        if c["cell_id"] in done and done[c["cell_id"]]["status"] not in ("NO_RECORD",):
            continue
        assert sha_file(os.path.join(HERE, c["model_path"])) == c["raw_model_sha256"] and sha_file(os.path.join(HERE, c["evidence_path"])) == c["raw_evidence_sha256"], "live input differs from the manifest binding"
        total, by_scope, unresolved = charged(D); maxcharge = c["budget_s"] + GRACE_S + LAUNCH_OVERHEAD_S; spent_stage = by_scope.get(env_scope, 0.0)
        if spent_stage + maxcharge > envelope or total + maxcharge > CEILING_S - ENVELOPES["reserve"]:
            row = {"cell_id": c["cell_id"], "task_id": c["task_id"], "stage": stage, "kind": c["kind"], "case": c["case"], "family": c["family"], "budget_s": c["budget_s"], "status": "NOT_RUN_BUDGET", "outcome": "NOT_RUN_BUDGET", "supervisor_wall_s": 0.0,
                   "reason": "stage %s spent %.1f of %.1f s or ceiling %.1f + %.1f would breach %.1f - reserve %.1f" % (env_scope, spent_stage, envelope, total, maxcharge, CEILING_S, ENVELOPES["reserve"])}
            open(os.path.join(D, "CELLS_LEDGER.jsonl"), "a").write(json.dumps(row) + "\n"); print(c["case"], c["budget_s"], "NOT_RUN_BUDGET"); continue
        attempt = 1 + sum(1 for r in done.values() if r.get("task_id") == c["task_id"]); pred = [r["cell_id"] for r in done.values() if r.get("task_id") == c["task_id"]]
        base = os.path.join(D, "cells", stage, "%s__%ds__%s" % (c["case"], int(c["budget_s"]), c["cell_id"])); prior_dirs = sorted(d for d in os.listdir(os.path.join(D, "cells", stage)) if d.startswith(os.path.basename(base) + "__a")) if os.path.isdir(os.path.join(D, "cells", stage)) else []
        attempt = max(attempt, 1 + len(prior_dirs)); out = base + "__a%d" % attempt; os.makedirs(out, exist_ok=False); pred = pred + [d for d in prior_dirs]
        mp = os.path.join(HERE, c["model_path"]); ep = os.path.join(HERE, c["evidence_path"]); cfgp = os.path.join(D, "CONFIG_new_arm.json")
        inner = [PY, "-m", "adp.cell" if stage == "primary" else "adp.census.diag_cell", mp, ep, out, "%.3f" % c["budget_s"], cfgp]
        cmd = [PY, "-m", "adp.census.supervise", "--ledger", os.path.join(D, "CENSUS_LEDGER.jsonl"), "--scope", env_scope, "--job", "cell:%s:%s:%ds:a%d" % (stage, c["case"], int(c["budget_s"]), attempt), "--timeout", "%.3f" % c["budget_s"], "--mem-gib", str(MEM_GIB), "--cwd", HERE, "--stdout", os.path.join(out, "supervisor.log"), "--stderr", os.path.join(out, "supervisor.log")] + [x for k, v in THREAD_ENV.items() for x in ("--env", "%s=%s" % (k, v))] + ["--env", "PYTHONPATH=" + HERE, "--"] + inner
        t0 = time.monotonic(); subprocess.run(cmd, cwd=HERE); wall_outer = time.monotonic() - t0
        rows = ledger_rows(D); rcpt = [r for r in rows if r["kind"] == "RECEIPT" and r["job"] == "cell:%s:%s:%ds:a%d" % (stage, c["case"], int(c["budget_s"]), attempt)]
        rcpt = rcpt[-1] if rcpt else {"wall_s": None, "outcome": "RECEIPT_MISSING", "peak_tree_rss_bytes": None, "rss_samples": None}
        cj = os.path.join(out, "cell.json"); rec = json.load(open(cj)) if os.path.exists(cj) else {}
        row = {"cell_id": c["cell_id"], "task_id": c["task_id"], "stage": stage, "kind": c["kind"], "case": c["case"], "family": c["family"], "budget_s": c["budget_s"], "attempt": attempt, "predecessors": pred, "out_dir": os.path.relpath(out, D),
               "supervisor_wall_s": rcpt["wall_s"], "outer_wall_s": wall_outer, "outcome": rcpt["outcome"], "peak_tree_rss_bytes": rcpt["peak_tree_rss_bytes"], "rss_samples": rcpt["rss_samples"], "returncode": rcpt.get("returncode"),
               "status": rec.get("status") if rec else ("KILLED_" + rcpt["outcome"] if rcpt["outcome"] in ("MEMORY_KILL", "TIMEOUT_KILL") else "NO_RECORD"), "complete_response_s": rec.get("complete_response_s"), "within_deadline": rec.get("within_deadline"), "censored": bool(rec.get("censored")) or rcpt["outcome"] in ("MEMORY_KILL", "TIMEOUT_KILL"),
               "t_first_complete_output_s": rec.get("t_first_complete_output_s"), "phases_s": rec.get("phases_s"), "reason": (rec.get("reason") or "")[:300] if isinstance(rec.get("reason"), str) else rec.get("reason"), "stop": rec.get("stop"), "frozen_set_code_hash": ch, "harness_hash": hh}
        open(os.path.join(D, "CELLS_LEDGER.jsonl"), "a").write(json.dumps(row, default=str) + "\n")
        print("%-20s %4ds %-9s %-34s %6.2fs peak %5.0fMB %s" % (c["case"], c["budget_s"], stage, str(row["status"])[:34], rcpt["wall_s"] or 0, (rcpt["peak_tree_rss_bytes"] or 0) / 1e6, rcpt["outcome"] if rcpt["outcome"] != "COMPLETED" else ""), flush=True)
    total, by_scope, unresolved = charged(D); print("stage %s done; charged total %.1f s of %.0f; by scope %s; unresolved %d" % (stage, total, CEILING_S, {k: round(v, 1) for k, v in by_scope.items()}, len(unresolved)))


def status(D):
    import collections
    rows = [json.loads(l) for l in open(os.path.join(D, "CELLS_LEDGER.jsonl"))] if os.path.exists(os.path.join(D, "CELLS_LEDGER.jsonl")) else []
    for st in ("primary", "diag"):
        rs = [r for r in rows if r["stage"] == st]; print(st, len(rs), dict(collections.Counter((int(r["budget_s"]), r["status"]) for r in rs)))
    total, by_scope, unresolved = charged(D); print("charged %.1f s of %.0f; by scope %s; unresolved starts %d" % (total, CEILING_S, {k: round(v, 1) for k, v in by_scope.items()}, len(unresolved)))


if __name__ == "__main__":
    cmd, D = sys.argv[1], os.path.abspath(sys.argv[2])
    {"freeze": lambda: freeze(D), "primary": lambda: run_stage(D, "primary"), "diag": lambda: run_stage(D, "diag"), "status": lambda: status(D)}[cmd]()
