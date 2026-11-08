"""AGGREGATE_DP_2026-11-07 campaign harness (new, isolated; the historical EXTERNAL_SWEEP harness and its ledgers are read-only).

    python adp/campaign.py freeze  D            -> D/CAMPAIGN_MANIFEST.json (736 cells + 2 inaccessible records; every hash sealed)
    python adp/campaign.py run     D  STAGE     -> runs every non-terminal cell of STAGE serially (resumable by cell_id)
    python adp/campaign.py status  D

Stages (frozen order, primary first; ablations and repetitions only after the primary configurations are sealed):
    P20   AGGREGATE_DP_V1 + EXACT + MDI_EXISTING + WMB + IJGP at 20 s on 46 cases          230 cells   4,600 s allowance
    P120  AGGREGATE_DP_V1 + EXACT at 120 s on 46 cases                                     92 cells  11,040 s
    ABL   A1..A5 ablations of the new arm at 20 s on 46 cases                              230 cells   4,600 s
    REP   two further paired repetitions of AGGREGATE_DP_V1 + EXACT at 20 s                184 cells   3,680 s
Total 736 cells, 23,920 s of cell allowances; the separate campaign ceiling is 28,800 s of top-level charged wall including
qualification, setup and closeout receipts (QUALIFICATION_LEDGER.jsonl, CLOSEOUT_LEDGER.jsonl). Each cell runs in a fresh process
(new session), supervised: sampled process-tree RSS every 50 ms with SIGKILL above 8 GiB (best-effort policing of producer + checker
together; not an allocator cap; overshoot recorded), SIGKILL at deadline + 4 s grace. One worker at a time; thread env pinned to one.
Block order: cases shuffled by a seed derived from the manifest's configuration hash (recorded), arm order rotated per case by the
case hash; the same order is reused by every stage so paired cells of a case stay adjacent in time within a stage.
"""
from __future__ import annotations
import os, sys, json, time, hashlib, subprocess, signal, random, platform
import psutil
HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__))); sys.path.insert(0, HERE)
PY = os.path.join(HERE, ".venv", "bin", "python")
OLD = os.path.join(HERE, "runs", "mdi_2026-10-28", "EXTERNAL_SWEEP_2026-11-06")                  # read-only: inputs, inventory, selection
MERLIN = "/Users/adis/Workspace/comparators/merlin/build/merlin"
GRACE_S = 4.0; MEM_GIB = 8.0; INTERVAL = 0.05
THREAD_ENV = {"OMP_NUM_THREADS": "1", "OPENBLAS_NUM_THREADS": "1", "MKL_NUM_THREADS": "1", "VECLIB_MAXIMUM_THREADS": "1", "NUMEXPR_NUM_THREADS": "1", "PYTHONHASHSEED": "0"}
NEW_ARM = "AGGREGATE_DP_V1"
ABLATIONS = {"A1_no_source_reductions": {"rules": []}, "A2_identity_response_views": {"views": False}, "A3_no_native_sparse": {"sparse": False},
             "A4_no_memo_no_coalescing": {"memo": False, "batched": False}, "A5_scalar_entries": {"batched": False}}
BASELINE_CFG = {"width": "1/100", "cbi_limits": {}, "pgmax_iters": 200, "pgmax_damping": 0.5}       # the historical arms' own frozen config
STAGES = {"P20": 4600.0, "P120": 11040.0, "ABL": 4600.0, "REP": 3680.0}
CELL_ALLOWANCE_S = 23920.0; CEILING_S = 28800.0


def sha_file(p):
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for ch in iter(lambda: f.read(1 << 20), b""):
            h.update(ch)
    return h.hexdigest()


def code_hash():
    files = sorted("adp/" + f for f in os.listdir(os.path.join(HERE, "adp")) if f.endswith(".py")) + ["bench/cells.py", "bench/libdai/libdai_mar", "ext/uai.py", "ext/supervise.py"] + sorted("mdi/" + f for f in os.listdir(os.path.join(HERE, "mdi")) if f.endswith(".py"))
    h = hashlib.sha256(); per = {}
    for f in files:
        d = sha_file(os.path.join(HERE, f)); per[f] = d; h.update(f.encode()); h.update(d.encode())
    per["merlin"] = sha_file(MERLIN) if os.path.exists(MERLIN) else None; h.update(("merlin:%s" % per["merlin"]).encode())
    return h.hexdigest(), per


def git_head():
    try:
        return subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=HERE).decode().strip()
    except Exception:
        return None


def environment():
    import gmpy2, numpy
    return {"platform": platform.platform(), "machine": platform.machine(), "python": sys.version, "gmpy2": gmpy2.version(), "mpfr": gmpy2.mpfr_version(), "numpy": numpy.__version__, "psutil": psutil.__version__,
            "cpu_count": os.cpu_count(), "mem_total_bytes": psutil.virtual_memory().total, "thread_env": THREAD_ENV, "worker": "one cell at a time; thread env pinned to 1; no CPU affinity on macOS (best effort)"}


def freeze(D):
    from adp import engine as EN
    sel = json.load(open(os.path.join(OLD, "PANEL_SELECTION.json"))); inv = {c["case"]: c for c in json.load(open(os.path.join(OLD, "INVENTORY.json")))["cases"]}
    cfg_new = dict(EN.DEFAULTS); cfg_hash = hashlib.sha256(json.dumps({"new": cfg_new, "baseline": BASELINE_CFG, "ablations": ABLATIONS}, sort_keys=True, default=str).encode()).hexdigest()
    ch, per = code_hash()
    cases = []
    for c in sel["selected"]:
        row = inv[c["case"]]; mp = os.path.join(OLD, "inputs", c["case"] + ".uai"); ep = mp + ".evid"
        assert sha_file(mp) == row["raw_model_sha256"] and sha_file(ep) == row["raw_evidence_sha256"], "input bytes of %s differ from the inventory binding" % c["case"]
        cases.append({"case": c["case"], "family": c["family"], "model_path": os.path.relpath(mp, HERE), "evidence_path": os.path.relpath(ep, HERE), "raw_model_sha256": row["raw_model_sha256"], "raw_evidence_sha256": row["raw_evidence_sha256"],
                      "canonical_model_sha256": row["canonical_model_sha256"], "canonical_evidence_sha256": row["canonical_evidence_sha256"], "variables": row["structure"]["variables"], "accessible": True})
    inaccessible = [{"case": "%s_slot_%d" % (fam, s["available"] + 1), "family": fam, "accessible": False, "reason": "inventory shortfall: %d of %d available in the frozen 48-slot selection (CBI-EXTERNAL-48-v1)" % (s["available"], s["target"])} for fam, s in sel["shortfalls"].items()]
    seed = int(hashlib.sha256(("AGGREGATE_DP_2026-11-07|" + cfg_hash).encode()).hexdigest(), 16) % (1 << 32)
    order = list(cases); random.Random(seed).shuffle(order)
    man = {"campaign": "AGGREGATE_DP_2026-11-07", "frozen_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "commit": git_head(), "code_hash": ch, "code_files_sha256": per, "config_hash": cfg_hash, "config_new_arm": cfg_new, "config_baselines": BASELINE_CFG, "ablations": ABLATIONS,
           "environment": environment(), "block_order_seed": seed, "case_order": [c["case"] for c in order], "cases": cases, "inaccessible_slots": inaccessible, "stages": STAGES, "cell_allowance_s": CELL_ALLOWANCE_S, "ceiling_s": CEILING_S,
           "memory_budget_gib": MEM_GIB, "grace_s": GRACE_S, "publication_contract": {"eps": "1/200", "max_width": "1/100", "point": "robust center on the exact dyadic grid 2^-(40+ceil(log2 max_domain)); every row sums to 1 exactly; independently re-verified from the delivered decimals", "queries": "all original variables incl. observed point masses"},
           "enforcement": {"time": "cooperative deadline inside the cell (polled per chunk / per operation) + SIGKILL of the process group at deadline + grace", "memory": "sampled process-tree RSS every 50 ms, SIGKILL above 8 GiB (producer + checker together; best effort, overshoot recorded); RLIMIT_AS unavailable on macOS", "cpu": "serial; one worker"},
           "cells": []}
    def add(stage, arm, budget, c, rep, cfg_key, cfg):
        task = {"model": c["canonical_model_sha256"], "evidence": c["canonical_evidence_sha256"], "queries": "all_original_variables", "arm": arm, "config_key": cfg_key, "config": cfg, "budget_s": budget, "memory_gib": MEM_GIB, "grace_s": GRACE_S, "repetition": rep}
        tid = hashlib.sha256(json.dumps(task, sort_keys=True, default=str).encode()).hexdigest()[:16]; cid = hashlib.sha256((tid + "|" + ch).encode()).hexdigest()[:16]
        man["cells"].append({"cell_id": cid, "task_id": tid, "task": task, "stage": stage, "case": c["case"], "family": c["family"], "arm": arm, "budget_s": budget, "repetition": rep, "config_key": cfg_key, "model_path": c["model_path"], "evidence_path": c["evidence_path"], "raw_model_sha256": c["raw_model_sha256"], "raw_evidence_sha256": c["raw_evidence_sha256"]})
    def rotated(c, arms):
        r = int(hashlib.sha256((c["canonical_model_sha256"] + c["canonical_evidence_sha256"]).encode()).hexdigest(), 16) % len(arms); return arms[r:] + arms[:r]
    for c in order:
        for arm in rotated(c, [NEW_ARM, "EXACT", "MDI_EXISTING", "WMB", "IJGP"]):
            add("P20", arm, 20.0, c, 0, "full" if arm == NEW_ARM else "baseline", cfg_new if arm == NEW_ARM else BASELINE_CFG)
    for c in order:
        for arm in rotated(c, [NEW_ARM, "EXACT"]):
            add("P120", arm, 120.0, c, 0, "full" if arm == NEW_ARM else "baseline", cfg_new if arm == NEW_ARM else BASELINE_CFG)
    for c in order:
        keys = sorted(ABLATIONS); r = int(hashlib.sha256(c["canonical_model_sha256"].encode()).hexdigest(), 16) % len(keys); keys = keys[r:] + keys[:r]
        for k in keys:
            add("ABL", NEW_ARM, 20.0, c, 0, k, dict(cfg_new, **ABLATIONS[k]))
    for rep in (1, 2):
        for c in order:
            for arm in rotated(c, [NEW_ARM, "EXACT"]):
                add("REP", arm, 20.0, c, rep, "full" if arm == NEW_ARM else "baseline", cfg_new if arm == NEW_ARM else BASELINE_CFG)
    man["counts"] = {s: sum(1 for c in man["cells"] if c["stage"] == s) for s in STAGES}; man["counts"]["total"] = len(man["cells"]); man["counts"]["allowance_sum_s"] = sum(c["budget_s"] for c in man["cells"])
    assert man["counts"]["total"] == 736 and man["counts"]["allowance_sum_s"] == CELL_ALLOWANCE_S, man["counts"]
    mp = os.path.join(D, "CAMPAIGN_MANIFEST.json")
    if os.path.exists(mp):
        prior = json.load(open(mp)); dst = os.path.join(D, "CAMPAIGN_MANIFEST_prior_%s_%s.json" % (prior["code_hash"][:12], prior["frozen_utc"].replace(":", "").replace("-", ""))); k = 1
        while os.path.exists(dst):
            dst = dst[:-5] + "_%d.json" % k; k += 1
        os.replace(mp, dst); man["prior_manifests"] = (prior.get("prior_manifests") or []) + [os.path.basename(dst)]
        if prior["code_hash"] != ch:
            am = json.load(open(os.path.join(D, "AMENDMENTS.json"))) if os.path.exists(os.path.join(D, "AMENDMENTS.json")) else []
            assert am and am[-1].get("code_hash_to") == ch, "a re-freeze with a changed code hash needs an amendment entry naming the new code hash"
            man["amendment"] = am[-1]
    json.dump(man, open(mp, "w"), indent=1, default=str); json.dump(cfg_new, open(os.path.join(D, "CONFIG_new_arm.json"), "w"), indent=1); json.dump(BASELINE_CFG, open(os.path.join(D, "CONFIG_baselines.json"), "w"))
    for k, v in ABLATIONS.items():
        json.dump(dict(cfg_new, **v), open(os.path.join(D, "CONFIG_%s.json" % k), "w"), indent=1)
    print("frozen:", man["counts"], "commit", man["commit"], "code_hash", ch[:12], "seed", seed)


def tree_rss(p):
    try:
        return sum((q.memory_info().rss for q in [p] + p.children(recursive=True) if q.is_running()), 0)
    except psutil.Error:
        return 0


def ledger_rows(D):
    lp = os.path.join(D, "CELLS_LEDGER.jsonl")
    return [json.loads(l) for l in open(lp)] if os.path.exists(lp) else []


def receipts_total(D):
    """every nonnested top-level receipt once: qualification + closeout jobs + every cell row (the stage runner is not a receipt)."""
    tot = 0.0; n = 0
    for name in ("QUALIFICATION_LEDGER.jsonl", "CLOSEOUT_LEDGER.jsonl"):
        p = os.path.join(D, name)
        if os.path.exists(p):
            for l in open(p):
                j = json.loads(l); tot += j["wall_s"]; n += 1
    for r in ledger_rows(D):
        tot += r.get("supervisor_wall_s", 0.0) or 0.0; n += 1
    return tot, n


def run_cell(D, cell, man):
    out = os.path.join(D, "cells", cell["stage"], "%s__%s__%s__%s" % (cell["case"], cell["arm"], cell["config_key"], cell["cell_id"])); os.makedirs(out, exist_ok=True)
    mp = os.path.join(HERE, cell["model_path"]); ep = os.path.join(HERE, cell["evidence_path"])
    if cell["arm"] == NEW_ARM:
        cfgp = os.path.join(D, "CONFIG_%s.json" % ("new_arm" if cell["config_key"] == "full" else cell["config_key"]))
        cmd = [PY, "-m", "adp.cell", mp, ep, out, "%.3f" % cell["budget_s"], cfgp]
    else:
        cmd = [PY, os.path.join(HERE, "bench", "cells.py"), cell["arm"], mp, ep, out, "%.3f" % cell["budget_s"], os.path.join(D, "CONFIG_baselines.json")]
    env = dict(os.environ); env.update(THREAD_ENV); env["PYTHONPATH"] = HERE
    log = open(os.path.join(out, "supervisor.log"), "ab"); t0 = time.time(); m0 = time.monotonic()
    proc = subprocess.Popen(cmd, stdout=log, stderr=subprocess.STDOUT, env=env, cwd=HERE, start_new_session=True); p = psutil.Process(proc.pid)
    peak = 0; overshoot = 0; outcome = "COMPLETED"; samples = 0
    while proc.poll() is None:
        r = tree_rss(p); peak = max(peak, r); samples += 1
        if r > MEM_GIB * 2 ** 30:
            outcome = "MEMORY_KILL"; overshoot = r - MEM_GIB * 2 ** 30; os.killpg(proc.pid, signal.SIGKILL); proc.wait(); break
        if time.monotonic() - m0 > cell["budget_s"] + GRACE_S:
            outcome = "TIMEOUT_KILL"; os.killpg(proc.pid, signal.SIGKILL); proc.wait(); break
        time.sleep(INTERVAL)
    wall = time.monotonic() - m0; log.close()
    cj = os.path.join(out, "cell.json"); rec = json.load(open(cj)) if os.path.exists(cj) else {}
    if outcome == "COMPLETED" and proc.returncode != 0:
        outcome = "NONZERO_EXIT"
    row = {**{k: cell[k] for k in ("cell_id", "task_id", "stage", "case", "family", "arm", "budget_s", "repetition", "config_key")}, "out_dir": os.path.relpath(out, D), "start_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(t0)),
           "supervisor_wall_s": wall, "returncode": proc.returncode, "outcome": outcome, "peak_tree_rss_bytes": peak, "rss_samples": samples, "mem_overshoot_bytes": overshoot,
           "status": rec.get("status") if rec else ("KILLED_" + outcome if outcome in ("MEMORY_KILL", "TIMEOUT_KILL") else "NO_RECORD"), "complete_response_s": rec.get("complete_response_s"), "within_deadline": rec.get("within_deadline"),
           "censored": bool(rec.get("censored")) or outcome in ("MEMORY_KILL", "TIMEOUT_KILL"), "t_first_complete_output_s": rec.get("t_first_complete_output_s"), "output_bytes": rec.get("output_bytes"), "phases_s": rec.get("phases_s"),
           "reason": (rec.get("reason") or "")[:300] if isinstance(rec.get("reason"), str) else rec.get("reason"), "stop": rec.get("stop"), "code_hash": man["code_hash"]}
    with open(os.path.join(D, "CELLS_LEDGER.jsonl"), "a") as f:
        f.write(json.dumps(row, default=str) + "\n")
    return row


def run(D, stage):
    man = json.load(open(os.path.join(D, "CAMPAIGN_MANIFEST.json"))); ch, _ = code_hash(); assert ch == man["code_hash"], "code hash differs from the frozen manifest: amend + re-freeze or restore the code"
    if stage in ("ABL", "REP"):
        rows = ledger_rows(D); done = {r["cell_id"] for r in rows}
        prim = [c for c in man["cells"] if c["stage"] in ("P20", "P120")]
        assert all(c["cell_id"] in done for c in prim), "ablations / repetitions run only after every primary cell is sealed"
    have = {r["cell_id"] for r in ledger_rows(D)}
    def live_ok(c):
        return sha_file(os.path.join(HERE, c["model_path"])) == c["raw_model_sha256"] and sha_file(os.path.join(HERE, c["evidence_path"])) == c["raw_evidence_sha256"]
    cells = [c for c in man["cells"] if c["stage"] == stage and c["cell_id"] not in have]
    for c in cells:
        assert live_ok(c), "live input of %s differs from its manifest binding" % c["case"]
    for c in cells:
        if c["arm"] in ("WMB", "IJGP") and not os.path.exists(MERLIN):
            row = {**{k: c[k] for k in ("cell_id", "task_id", "stage", "case", "family", "arm", "budget_s", "repetition", "config_key")}, "outcome": "UNAVAILABLE", "status": "UNAVAILABLE", "supervisor_wall_s": 0.0, "reason": "Merlin binary absent"}
            open(os.path.join(D, "CELLS_LEDGER.jsonl"), "a").write(json.dumps(row) + "\n"); continue
        cells_spent = sum(r.get("supervisor_wall_s", 0.0) or 0.0 for r in ledger_rows(D)); total, _ = receipts_total(D)
        if cells_spent + c["budget_s"] + GRACE_S + 2.0 > CELL_ALLOWANCE_S or total + c["budget_s"] + GRACE_S + 2.0 > CEILING_S - 1200.0:
            row = {**{k: c[k] for k in ("cell_id", "task_id", "stage", "case", "family", "arm", "budget_s", "repetition", "config_key")}, "outcome": "NOT_RUN_BUDGET", "status": "NOT_RUN_BUDGET", "supervisor_wall_s": 0.0,
                   "reason": "budget: cells %.1f of %.1f s; aggregate receipts %.1f of %.1f s (1,200 s closeout reserve)" % (cells_spent, CELL_ALLOWANCE_S, total, CEILING_S)}
            open(os.path.join(D, "CELLS_LEDGER.jsonl"), "a").write(json.dumps(row) + "\n"); continue
        row = run_cell(D, c, man)
        print("%-20s %-16s %-26s %-5s %6.2fs peak %5.0fMB %s" % (c["case"], c["arm"], c["config_key"][:26], c["stage"], row["supervisor_wall_s"], row["peak_tree_rss_bytes"] / 1e6, (str(row["status"])[:30] + (" " + row["outcome"] if row["outcome"] != "COMPLETED" else ""))), flush=True)
    print("stage %s done; cells spent %.1f s; receipts total %.1f s" % (stage, sum(r.get("supervisor_wall_s", 0.0) or 0.0 for r in ledger_rows(D)), receipts_total(D)[0]))


def status(D):
    import collections
    rows = ledger_rows(D)
    for st in STAGES:
        rs = [r for r in rows if r["stage"] == st]
        print(st, len(rs), "rows; spent %.1f s;" % sum(r.get("supervisor_wall_s", 0.0) or 0.0 for r in rs), dict(collections.Counter((r["arm"] if r["arm"] != NEW_ARM else r["config_key"], r["status"]) for r in rs)))
    print("receipts total %.1f s of %.0f" % (receipts_total(D)[0], CEILING_S))


if __name__ == "__main__":
    cmd, D = sys.argv[1], os.path.abspath(sys.argv[2])
    {"freeze": lambda: freeze(D), "run": lambda: run(D, sys.argv[3]), "status": lambda: status(D)}[cmd]()
