"""CAMPAIGN ENTRY POINT (spec section 10): from the committed manifest, run preparation checks, supervised execution, scoring and reporting.

    python bench/campaign.py freeze   SWEEP_DIR            -> CAMPAIGN_MANIFEST.json (cases x arms x budgets, hashes, config, commit)
    python bench/campaign.py run      SWEEP_DIR STAGE      -> executes every scheduled cell of STAGE (breadth | depth | diag:<name>) not yet
                                                              terminal in CELLS_LEDGER.jsonl; serial; resumable (cells identified by hash)
    python bench/campaign.py status   SWEEP_DIR
Cells: one fresh process `bench/cells.py ARM MODEL EVID OUT DEADLINE CFG`, supervised: process group, sampled process-tree RSS (50 ms) with
SIGKILL at the 8 GiB budget (best-effort policing, not an allocator cap), SIGKILL at deadline + grace. The supervisor spawn-to-reap wall is
the charged job wall (each top-level job once). Thread env pins BLAS / OpenMP / XLA to one thread; CPU affinity is not available on macOS
(best effort: one worker at a time, nothing else scheduled by the campaign). Adding a benchmark = adding a case to PANEL_SELECTION.json
(model + evidence paths) and re-freezing; no solver internals are touched."""
from __future__ import annotations
import os, sys, json, time, hashlib, subprocess, signal
import psutil
HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__))); sys.path.insert(0, HERE)
PY = os.path.join(HERE, ".venv", "bin", "python")
ARMS = ["CBI_NATIVE", "MDI_EXISTING", "LBP", "WMB", "IJGP", "SAMPLESEARCH", "EXACT", "PGMAX_SUMPRODUCT_BP"]
UNAVAILABLE = {"SAMPLESEARCH"}
GRACE_S = 4.0; MEM_GIB = 8.0; INTERVAL = 0.05
BUDGET = {"breadth": 7680.0, "depth": 11520.0, "diag": 1200.0, "reference": 2400.0}
THREAD_ENV = {"OMP_NUM_THREADS": "1", "OPENBLAS_NUM_THREADS": "1", "MKL_NUM_THREADS": "1", "VECLIB_MAXIMUM_THREADS": "1", "NUMEXPR_NUM_THREADS": "1", "XLA_FLAGS": "--xla_cpu_multi_thread_eigen=false intra_op_parallelism_threads=1", "JAX_PLATFORMS": "cpu", "PYTHONHASHSEED": "0"}


def sha_file(p):
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for ch in iter(lambda: f.read(1 << 20), b""):
            h.update(ch)
    return h.hexdigest()


def git_head():
    try:
        return subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=HERE).decode().strip()
    except Exception:
        return None


def code_hash():
    files = ["bench/cells.py", "bench/cbi_adapter.py", "bench/pgmax_mar.py", "bench/libdai/libdai_mar", "bench/bif.py", "ext/uai.py"] + sorted("cbi/" + f for f in os.listdir(os.path.join(HERE, "cbi")) if f.endswith(".py")) + sorted("mdi/" + f for f in os.listdir(os.path.join(HERE, "mdi")) if f.endswith(".py"))
    h = hashlib.sha256()
    for f in files:
        h.update(f.encode()); h.update(sha_file(os.path.join(HERE, f)).encode())
    return h.hexdigest(), files


def freeze(S, amendment=None, cfg_override=None):
    """amendment = {"name": ..., "arms_with_changed_numerical_semantics": [...], "note": ...} on a RE-freeze: every new cell records its predecessor
    cell id from the prior manifest; a cell whose arm's numerical semantics are unchanged INHERITS its predecessor's primary row (recorded, never
    silent); a cell whose arm changed must be rerun under the new id."""
    sel = json.load(open(os.path.join(S, "PANEL_SELECTION.json"))); inv = {c["case"]: c for c in json.load(open(os.path.join(S, "INVENTORY.json")))["cases"]}
    cfg = cfg_override or {"width": "1/100", "cbi_limits": {}, "pgmax_iters": 200, "pgmax_damping": 0.5}
    ch, files = code_hash(); cfg_hash = hashlib.sha256(json.dumps(cfg, sort_keys=True).encode()).hexdigest()
    man = {"frozen_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "commit": git_head(), "code_hash": ch, "code_files": files, "config": cfg, "config_hash": cfg_hash, "arms": ARMS, "unavailable_arms": sorted(UNAVAILABLE),
           "budgets_s": {"breadth_cell": 20.0, "depth_cell": 120.0}, "stage_allowances_s": BUDGET, "memory_budget_gib": MEM_GIB, "grace_s": GRACE_S,
           "enforcement": {"time": "cooperative deadline inside the cell + SIGKILL of the process group at deadline + grace (hard)", "memory": "sampled process-tree RSS every 50 ms, SIGKILL above 8 GiB (best effort; overshoot recorded); RLIMIT_AS unavailable on macOS", "cpu": "one cell at a time; thread env pinned to 1; no affinity on macOS (best effort)"},
           "diagnostic_rules": {"width_probes": "first two CBI-admitted depth cases in manifest order; widths 1/50 and 1/500; 20 s caps; separately labelled",
                                "rooted_query_probe": "single-query probe on the unobserved original variable minimizing SHA256(case-content-hash, variable-id); compare rooted vs all-query correctness",
                                "repetitions": "two extra repetitions of at most two case/arm comparisons (120 s) on the first two depth cases in manifest order where CBI and an external arm both produced full outputs; external arm by priority PGMAX_SUMPRODUCT_BP, SAMPLESEARCH, IJGP, WMB, LBP, EXACT; else MDI_EXISTING labelled separately",
                                "reference_budget": "tiny ASIA / conversion controls first, then the smallest selected case per UAI family lacking a reference, 300 s per job, exact rational VE (bench/ref_exact.py); EXACT arm outputs are R1"},
           "cells": []}
    # families round-robin order; arm order rotated by case hash
    fams = {}
    for c in sel["selected"]:
        fams.setdefault(c["family"], []).append(c)
    order = []
    while any(fams.values()):
        for fam in list(fams):
            if fams[fam]:
                order.append(fams[fam].pop(0))
    depth_cases = {d["case"] for d in sel["depth_cases"]}
    for stage, budget in (("breadth", 20.0), ("depth", 120.0)):
        for c in order:
            if stage == "depth" and c["case"] not in depth_cases:
                continue
            row = inv[c["case"]]; row = dict(row, model_path=row.get("committed_model_path", row["model_path"]), evidence_path=row.get("committed_evidence_path", row["evidence_path"])); rot = int(hashlib.sha256((row["canonical_model_sha256"] + row["canonical_evidence_sha256"]).encode()).hexdigest(), 16) % len(ARMS)
            arms = ARMS[rot:] + ARMS[:rot]
            for arm in arms:
                # TASK identity = every non-code field of the task: original model + evidence content, query set (complete MAR = all unobserved),
                # configuration, effective resource limits (budget, memory, grace), arm. cell_id = task + code hash.
                task = {"model": row["canonical_model_sha256"], "evidence": row["canonical_evidence_sha256"], "queries": "all_unobserved", "config": cfg_hash, "arm": arm, "budget_s": budget, "memory_gib": MEM_GIB, "grace_s": GRACE_S}
                task_id = hashlib.sha256(json.dumps(task, sort_keys=True).encode()).hexdigest()[:16]
                cid = hashlib.sha256(("%s|%s|%s|%s|%s|%s" % (row["canonical_model_sha256"], row["canonical_evidence_sha256"], arm, budget, ch, cfg_hash)).encode()).hexdigest()[:16]
                man["cells"].append({"cell_id": cid, "task_id": task_id, "task": task, "stage": stage, "case": c["case"], "family": c["family"], "anchor": c.get("anchor", False), "arm": arm, "budget_s": budget, "model_path": row["model_path"], "evidence_path": row["evidence_path"],
                                     "raw_model_sha256": row["raw_model_sha256"], "raw_evidence_sha256": row["raw_evidence_sha256"], "canonical_model_sha256": row["canonical_model_sha256"], "canonical_evidence_sha256": row["canonical_evidence_sha256"]})
    man["counts"] = {"breadth": sum(1 for c in man["cells"] if c["stage"] == "breadth"), "depth": sum(1 for c in man["cells"] if c["stage"] == "depth"), "cases": len(sel["selected"]), "target_denominator": 48}
    mp = os.path.join(S, "CAMPAIGN_MANIFEST.json")
    if os.path.exists(mp):
        prior = json.load(open(mp)); hist = list(prior.get("code_hash_history") or [])
        # EVERY re-freeze preserves the prior manifest (same-code input / configuration revisions included) and extends the code history
        tag = (prior.get("code_hash", "")[:12] or "x") + "_" + (prior.get("frozen_utc", "").replace(":", "").replace("-", "") or "t"); dst = os.path.join(S, "CAMPAIGN_MANIFEST_prior_%s.json" % tag); k = 1
        while os.path.exists(dst):                                  # never overwrite a preserved manifest
            dst = os.path.join(S, "CAMPAIGN_MANIFEST_prior_%s_%d.json" % (tag, k)); k += 1
        os.replace(mp, dst)
        if prior.get("code_hash") != ch:
            assert amendment and "arms_with_changed_numerical_semantics" in amendment, "a re-freeze with a changed code hash needs an explicit amendment declaration"
            hist.append({"code_hash": prior["code_hash"], "frozen_utc": prior["frozen_utc"], "commit": prior.get("commit"), "transition_to": ch, "amendment": amendment})
        man["code_hash_history"] = hist; man["amendment"] = amendment if prior.get("code_hash") != ch else prior.get("amendment")
    # LINEAGE: a predecessor is a cell of a preserved prior manifest with the SAME task_id (all non-code task fields equal); a predecessor row may
    # satisfy this cell only if EVERY code transition between the predecessor's code hash and the current one carries an amendment declaring the
    # arm's numerical semantics unchanged (a later "unchanged" cannot skip an earlier changed-semantics transition)
    priors = []
    for f in sorted(os.listdir(S)):
        if f.startswith("CAMPAIGN_MANIFEST_prior_") and f.endswith(".json"):
            pm = json.load(open(os.path.join(S, f))); priors.append((pm.get("frozen_utc", ""), pm))
    priors.sort(key=lambda x: x[0], reverse=True)
    transitions = {}                                                    # code_hash -> (next code_hash, amendment)
    for h in man.get("code_hash_history") or []:
        if h.get("transition_to"):
            transitions[h["code_hash"]] = (h["transition_to"], h.get("amendment") or {})
    def equivalent_path(code_from, arm, case):
        """True iff every transition from code_from to the current code hash declares `arm` unchanged (or is a no-op)."""
        cur = code_from; seen = set()
        while cur != ch:
            if cur in seen or cur not in transitions:
                return False, "no recorded transition from %s" % cur[:12]
            nxt, am = transitions[cur]; seen.add(cur)
            if arm in set(am.get("arms_with_changed_numerical_semantics") or []):
                aff = (am.get("affected_cases") or {}).get(arm)
                if aff is None or case in aff:
                    return False, "transition %s -> %s changed %s semantics (%s%s)" % (cur[:12], nxt[:12], arm, am.get("name"), (" on %s" % case) if aff is not None else "")
            cur = nxt
        return True, "every intervening transition declares %s unchanged" % arm
    for c in man["cells"]:
        preds = []
        for _, pm in priors:
            for pc in pm["cells"]:
                if pc.get("task_id") == c["task_id"] or (pc.get("task_id") is None and pc["case"] == c["case"] and pc["arm"] == c["arm"] and pc["stage"] == c["stage"] and pc["budget_s"] == c["budget_s"]
                                                       and pc["canonical_model_sha256"] == c["canonical_model_sha256"] and pc["canonical_evidence_sha256"] == c["canonical_evidence_sha256"] and (pm.get("config_hash") == man["config_hash"])):
                    ok, why = equivalent_path(pm["code_hash"], c["arm"], c["case"])
                    preds.append({"cell_id": pc["cell_id"], "code_hash": pm["code_hash"], "frozen_utc": pm.get("frozen_utc"), "reusable": ok, "why": why})
        if preds:
            c["supersedes"] = preds[0]["cell_id"]; c["predecessors"] = preds; c["predecessor_chain"] = [x["cell_id"] for x in preds if x["reusable"]]
    json.dump(man, open(mp, "w"), indent=1); print("frozen:", man["counts"], "commit", man["commit"], "code_hash", ch[:12])


def tree_rss(p):
    try:
        return sum((q.memory_info().rss for q in [p] + p.children(recursive=True) if q.is_running()), 0)
    except psutil.Error:
        return 0


def ledger_rows(S):
    lp = os.path.join(S, "CELLS_LEDGER.jsonl")
    return [json.loads(l) for l in open(lp)] if os.path.exists(lp) else []


def stage_spent(rows, stage):
    """primary cells only (labelled rows are diagnostics / repetitions charged to their own scope)."""
    return sum(r["supervisor_wall_s"] for r in rows if r.get("stage") == stage and r.get("label") is None and r.get("outcome") not in ("NOT_RUN_BUDGET", "UNAVAILABLE"))


def run_cell(S, cell, cfgp, stage_key, label_extra=None, out_root=None, deadline=None):
    # labelled runs (diagnostics, amended reruns) get their own directory: the label is part of the name so probes / repetitions never overwrite
    # each other's artifacts (amendment 3: the first diagnostics pass wrote every DBN_15 probe into one directory)
    sub = "%s__%s__%s" % (cell["case"], cell["arm"], cell["cell_id"]) + (("__" + label_extra.replace("/", "_")) if label_extra else "")
    out = os.path.join(S, out_root or "cells", cell["stage"], sub); os.makedirs(out, exist_ok=True)
    deadline = deadline or cell["budget_s"]
    cmd = [PY, os.path.join(HERE, "bench", "cells.py"), cell["arm"], os.path.join(S, cell["model_path"]), os.path.join(S, cell["evidence_path"]), out, "%.3f" % deadline, cfgp]
    env = dict(os.environ); env.update(THREAD_ENV); env["PYTHONPATH"] = HERE
    log = open(os.path.join(out, "supervisor.log"), "ab"); t0 = time.time(); m0 = time.monotonic()
    proc = subprocess.Popen(cmd, stdout=log, stderr=subprocess.STDOUT, env=env, cwd=HERE, start_new_session=True); p = psutil.Process(proc.pid)
    peak = 0; overshoot = 0; outcome = "COMPLETED"; samples = 0
    while proc.poll() is None:
        r = tree_rss(p); peak = max(peak, r); samples += 1
        if r > MEM_GIB * 2 ** 30:
            outcome = "MEMORY_KILL"; overshoot = r - MEM_GIB * 2 ** 30; os.killpg(proc.pid, signal.SIGKILL); proc.wait(); break
        if time.monotonic() - m0 > deadline + GRACE_S:
            outcome = "TIMEOUT_KILL"; os.killpg(proc.pid, signal.SIGKILL); proc.wait(); break
        time.sleep(INTERVAL)
    wall = time.monotonic() - m0; log.close()
    cj = os.path.join(out, "cell.json"); rec = json.load(open(cj)) if os.path.exists(cj) else {}
    if outcome == "COMPLETED" and proc.returncode != 0:
        outcome = "NONZERO_EXIT"
    row = {**{k: cell[k] for k in ("cell_id", "stage", "case", "family", "arm", "budget_s", "anchor")}, "deadline_s": deadline, "out_dir": os.path.relpath(out, S), "start_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(t0)),
           "supervisor_wall_s": wall, "returncode": proc.returncode, "outcome": outcome, "peak_tree_rss_bytes": peak, "rss_samples": samples, "mem_overshoot_bytes": overshoot,
           "status": rec.get("status") if rec else ("KILLED_" + outcome if outcome in ("MEMORY_KILL", "TIMEOUT_KILL") else "NO_RECORD"), "complete_response_s": rec.get("complete_response_s"), "within_deadline": rec.get("within_deadline"),
           "censored": bool(rec.get("censored")) or outcome in ("MEMORY_KILL", "TIMEOUT_KILL"), "t_first_complete_output_s": rec.get("t_first_complete_output_s"), "t_first_verified_width_met_s": rec.get("t_first_verified_width_met_s"),
           "output_bytes": rec.get("output_bytes"), "phases_s": rec.get("phases_s"), "reason": (rec.get("reason") or "")[:300] if isinstance(rec.get("reason"), str) else rec.get("reason"), "failure_primary": rec.get("failure_primary"),
           "snapshots": rec.get("snapshots"), "label": label_extra, "code_hash": code_hash()[0]}
    with open(os.path.join(S, "CELLS_LEDGER.jsonl"), "a") as f:
        f.write(json.dumps(row, default=str) + "\n")
    return row


def run(S, stage):
    man = json.load(open(os.path.join(S, "CAMPAIGN_MANIFEST.json"))); cfgp = os.path.join(S, "CONFIG.json"); json.dump(man["config"], open(cfgp, "w"))
    ch, _ = code_hash(); assert ch == man["code_hash"], "code hash differs from the frozen manifest: re-freeze or restore the code"
    # IDENTITY: a cell is DONE when a primary row carries its own cell_id (input + evidence + arm + budget + code + config), or the id of a
    # predecessor in its explicitly declared chain AND the amendment declared the arm's numerical semantics unchanged (an inherited row, listed
    # in RECONCILIATION.json). Names alone never match a row.
    rows = ledger_rows(S); have = {r["cell_id"]: r for r in rows if r.get("label") is None or str(r.get("label", "")).startswith("amendment")}
    def live_ok(c):
        """the LIVE input files must hash to the manifest's bindings before any execution or reuse"""
        return sha_file(os.path.join(S, c["model_path"])) == c["raw_model_sha256"] and sha_file(os.path.join(S, c["evidence_path"])) == c["raw_evidence_sha256"]
    def satisfied(c):
        if c["cell_id"] in have:
            return True
        return any(p in have for p in (c.get("predecessor_chain") or []))          # chain already contains only task-equal, equivalence-covered predecessors
    cells = []
    for c in man["cells"]:
        if c["stage"] != stage:
            continue
        assert live_ok(c), "live input of %s does not match its manifest binding" % c["case"]
        if not satisfied(c):
            cells.append(c)
    allowance = BUDGET[stage]; n = 0
    for c in cells:
        if c["arm"] in UNAVAILABLE:
            row = {**{k: c[k] for k in ("cell_id", "stage", "case", "family", "arm", "budget_s", "anchor")}, "outcome": "UNAVAILABLE", "status": "UNAVAILABLE", "supervisor_wall_s": 0.0, "reason": "arm unavailable (AVAILABILITY.json); no simulated timeout", "label": None}
            open(os.path.join(S, "CELLS_LEDGER.jsonl"), "a").write(json.dumps(row) + "\n"); continue
        spent = stage_spent(ledger_rows(S), stage)
        if spent + c["budget_s"] + GRACE_S + 2.0 > allowance:
            row = {**{k: c[k] for k in ("cell_id", "stage", "case", "family", "arm", "budget_s", "anchor")}, "outcome": "NOT_RUN_BUDGET", "status": "NOT_RUN_BUDGET", "supervisor_wall_s": 0.0, "reason": "stage allowance exhausted (%.1f of %.1f s)" % (spent, allowance), "label": None}
            open(os.path.join(S, "CELLS_LEDGER.jsonl"), "a").write(json.dumps(row) + "\n"); continue
        row = run_cell(S, c, cfgp, stage); n += 1
        print("%-20s %-20s %-5s %-24s %6.2fs peak %5.0fMB %s" % (c["case"], c["arm"], c["stage"][:5], str(row["status"])[:24], row["supervisor_wall_s"], row["peak_tree_rss_bytes"] / 1e6, row["outcome"] if row["outcome"] != "COMPLETED" else ""), flush=True)
    print("stage %s: ran %d cells; spent %.1f of %.1f s" % (stage, n, stage_spent(ledger_rows(S), stage), allowance))


def status(S):
    rows = ledger_rows(S); import collections
    for st in ("breadth", "depth"):
        rs = [r for r in rows if r["stage"] == st]
        print(st, len(rs), "rows; spent %.1f s;" % stage_spent(rows, st), dict(collections.Counter(r["status"] for r in rs)))


def reconcile(S):
    """RECONCILIATION.json: for every cell of the current manifest, the primary row that satisfies it (own id or an inherited predecessor row),
    with the amendment relation made explicit; unsatisfied cells are listed."""
    man = json.load(open(os.path.join(S, "CAMPAIGN_MANIFEST.json"))); rows = {}
    for r in ledger_rows(S):
        if r.get("label") is None:
            rows[r["cell_id"]] = r
    for r in ledger_rows(S):                                             # amended reruns are explicit, labelled rows under the re-frozen id
        if str(r.get("label") or "").startswith("amendment") and r["cell_id"] not in rows:
            rows[r["cell_id"]] = dict(r, _amended_rerun=True)
    out = {"manifest_code_hash": man["code_hash"], "cells": [], "unsatisfied": [], "inherited": 0, "own": 0}
    for c in man["cells"]:
        if c["cell_id"] in rows:
            out["cells"].append({"cell_id": c["cell_id"], "task_id": c.get("task_id"), "case": c["case"], "arm": c["arm"], "stage": c["stage"], "row": c["cell_id"], "relation": "own", "row_code_hash": rows[c["cell_id"]].get("code_hash")}); out["own"] += 1; continue
        pred = next((p for p in (c.get("predecessors") or []) if p["reusable"] and p["cell_id"] in rows), None)
        if pred:
            out["cells"].append({"cell_id": c["cell_id"], "task_id": c.get("task_id"), "case": c["case"], "arm": c["arm"], "stage": c["stage"], "row": pred["cell_id"], "relation": ("inherited from the labelled amendment rerun row: " if rows[pred["cell_id"]].get("_amended_rerun") else "inherited: ") + "same task_id; %s" % pred["why"], "row_code_hash": rows[pred["cell_id"]].get("code_hash"), "row_label": rows[pred["cell_id"]].get("label")}); out["inherited"] += 1
        else:
            out["unsatisfied"].append({"cell_id": c["cell_id"], "task_id": c.get("task_id"), "case": c["case"], "arm": c["arm"], "stage": c["stage"], "non_reusable_predecessors": [(p["cell_id"], p["why"]) for p in (c.get("predecessors") or [])]})
    # amendment 1 (PGMax duplicate-scope merge) changed PGMax's computation ONLY on inputs with repeated sliced scopes: those primary rows are the
    # pre-amendment FAILED rows and their labelled reruns are the valid outputs -- stated explicitly, never silently inherited as unchanged
    aff = json.load(open(os.path.join(S, "repair_2026-11-07", "PGMAX_AMENDMENT1_AFFECTED_INPUTS.json")))["cases"] if os.path.exists(os.path.join(S, "repair_2026-11-07", "PGMAX_AMENDMENT1_AFFECTED_INPUTS.json")) else []
    lab = [r for r in ledger_rows(S) if str(r.get("label") or "").startswith("amendment_1")]
    for c in out["cells"]:
        if c["arm"] == "PGMAX_SUMPRODUCT_BP" and c["case"] in aff and c["stage"] == "breadth":
            rr = [r for r in lab if r["case"] == c["case"]]; c["relation"] += "; amendment_1 CHANGED this arm's computation on this input (duplicate sliced scopes): the primary row is the pre-amendment FAILED outcome, the labelled rerun row(s) %s are the valid outputs" % [(r["cell_id"], r["status"]) for r in rr]
    out["note"] = "Amendment 1 changed the PGMax wrapper's computation only on %s (repeated sliced factor scopes); their breadth primary rows are pre-amendment FAILED outcomes with labelled reruns; every other inherited row ran code whose numerical semantics the amendments left unchanged." % aff
    json.dump(out, open(os.path.join(S, "RECONCILIATION.json"), "w"), indent=1); print("reconciliation: own %d, inherited %d, unsatisfied %d" % (out["own"], out["inherited"], len(out["unsatisfied"])))


if __name__ == "__main__":
    cmd, S = sys.argv[1], os.path.abspath(sys.argv[2])
    if cmd == "freeze":
        freeze(S, json.loads(sys.argv[3]) if len(sys.argv) > 3 else None)
    else:
        {"run": lambda: run(S, sys.argv[3]), "status": lambda: status(S), "reconcile": lambda: reconcile(S)}[cmd]()
