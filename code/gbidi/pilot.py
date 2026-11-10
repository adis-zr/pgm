"""GENERAL_BIDI_V2 broad round harness: freeze (414-row manifest by the EXACT procedure of empirical_plan.txt §3), run (every cell a charged job
through gbidi.supervise, the stage runner itself a supervised outer job), status. Repairs after the two adversarial reviews (H2, H3, R2-09):
  * the manifest carries the sha256 of every input file AND of the comparator configuration; the task identity includes the configuration hash;
  * before EVERY launch the live model / evidence / config bytes are hashed and compared with the manifest (TASK_MISMATCH -> stage stops);
    the expected hashes are passed to the new-arm child, which re-checks its own snapshot (gbidi.cell);
  * reconcile_order reconstructs task_id / cell_id from the canonical task and requires unique cell ids and unique output directories;
  * one exclusive run lock per run directory (an existing live lock refuses a second runner); output directories are created exist_ok=False
    and a planned cell is considered done only if its cell.json is bound to the planned task (else RESUME_CONFLICT -> stage stops);
  * budget guard: nonnested reconciliation of THIS ledger (unresolved starts charged at max permitted) + the remaining commitment + the closeout
    reserve must fit under the ceiling; a STOP_REQUESTED file stops gracefully between cells.
    python -m gbidi.pilot freeze D ; python -m gbidi.pilot run D STAGE ; python -m gbidi.pilot status D"""
from __future__ import annotations
import os, sys, json, time, hashlib, random, subprocess, fcntl
HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__))); sys.path.insert(0, HERE)
from adp.census import run as CR
from gbidi import reconcile as RC
from gbidi.arm_adapter import PRODUCER_ARM
PY = sys.executable
CEILING_S = 28800.0; CLOSEOUT_RESERVE_S = 1200.0; GRACE_S = 4.0; LAUNCH_OVERHEAD_S = 2.0; MEM_GIB = 8.0; SEED = 20261109
THREAD_ENV = {"OMP_NUM_THREADS": "1", "OPENBLAS_NUM_THREADS": "1", "MKL_NUM_THREADS": "1", "VECLIB_MAXIMUM_THREADS": "1", "NUMEXPR_NUM_THREADS": "1", "PYTHONHASHSEED": "0"}
FAMILY_ORDER = [("GridBN", ["BN_12", "BN_13", "BN_15", "BN_31"]), ("Grids", ["Grids_11", "Grids_14", "Grids_15", "Grids_17"]), ("Pedigree", ["Pedigree_11", "Pedigree_12", "Pedigree_13"]), ("Promedus", ["Promedus_33", "Promedus_14", "Promedus_12", "Promedus_37"]), ("CSP", ["CSP_12", "CSP_11", "CSP_13"]), ("DBN", ["DBN_11", "DBN_12", "DBN_15", "DBN_16"]), ("ObjectDetection", ["ObjectDetection_34", "ObjectDetection_56", "ObjectDetection_39", "ObjectDetection_24"]), ("Segmentation", ["Segmentation_11", "Segmentation_12", "Segmentation_16", "Segmentation_13"]), ("Protein", ["1qt9", "1jer", "1aie", "1npl"]), ("bnlearn", ["ASIA", "CHILD", "INSURANCE", "WATER", "MILDEW", "ALARM", "BARLEY", "HAILFINDER", "WIN95PTS", "MUNIN1", "ANDES", "DIABETES"])]
UNAVAILABLE = [("Pedigree_slot_4", "Pedigree"), ("CSP_slot_4", "CSP")]
STAGES = [("primary_breadth", ["GENERAL_BIDI_V2", "NATIVE_PLAIN_V2", "ADP_REPAIRED", "EXACT_LIBDAI"], 20.0), ("primary_depth", ["GENERAL_BIDI_V2", "NATIVE_PLAIN_V2"], 120.0), ("ablation_breadth", ["A1_NO_DEMAND_MASKS", "A2_NO_FUSION", "A3_NO_RESPONSE_VIEWS"], 20.0)]
GB_ARMS = {"GENERAL_BIDI_V2", "NATIVE_PLAIN_V2", "A1_NO_DEMAND_MASKS", "A2_NO_FUSION", "A3_NO_RESPONSE_VIEWS"}
CENSUS_D = os.path.join(HERE, "runs", "mdi_2026-10-28", "AGGREGATE_DP_CENSUS_2026-11-08")
PASS = "GENERAL_BIDI_V2"


def sha(p):
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for ch in iter(lambda: f.read(1 << 20), b""):
            h.update(ch)
    return h.hexdigest()


def ledger_path(D):
    return os.path.join(D, "GB_LEDGER.jsonl")


def charged(D):
    """nonnested accounting shared by the live guard and the closeout: every non-outer START once (receipt wall; no receipt / duplicate receipts /
    unresolved cleanup -> max permitted, listed as unresolved); every OUTER attempt's parent-only remainder once = outer wall - sum of the receipts
    of ITS OWN children (linked by parent_jid); an outer START without receipt is UNRESOLVED (charged at max permitted) and blocks launches, EXCEPT
    the outer attempt this runner is itself executing inside (GBIDI_PARENT_JID), whose parent remainder SO FAR (elapsed - its children) is charged live."""
    p = ledger_path(D); rows = [json.loads(l) for l in open(p)] if os.path.exists(p) else []
    rec = {}; dup = []
    for r in rows:
        if r["kind"] == "RECEIPT":
            if r["jid"] in rec:
                dup.append(r["jid"])
            rec[r["jid"]] = r
    total = 0.0; unresolved = []; by = {}; outer = []; children_of = {}
    for r in rows:
        if r["kind"] != "START" or r["scope"].startswith("stage_outer"):
            continue
        rc = rec.get(r["jid"])
        if rc is not None and not rc.get("cleanup_unresolved") and r["jid"] not in dup:
            total += rc["wall_s"]; by[r["scope"]] = by.get(r["scope"], 0.0) + rc["wall_s"]
            pj = r.get("parent_jid") or rc.get("parent_jid")
            if pj:
                children_of[pj] = children_of.get(pj, 0.0) + rc["wall_s"]
        elif rc is not None:
            unresolved.append(dict(r, cleanup_unresolved=True)); total += max(rc["wall_s"], r.get("max_permitted_charge_s") or 0.0)
        else:
            unresolved.append(r); total += (r.get("max_permitted_charge_s") or 0.0)
    live_parent = os.environ.get("GBIDI_PARENT_JID")                                                   # the outer attempt this runner is executing INSIDE (its receipt comes after us)
    for r in rows:
        if r["kind"] != "START" or not r["scope"].startswith("stage_outer"):
            continue
        rc = rec.get(r["jid"])
        if rc is None and r["jid"] == live_parent:
            try:
                elapsed = max(0.0, time.time() - time.mktime(time.strptime(r["start_utc"], "%Y-%m-%dT%H:%M:%SZ")) + time.timezone)
            except Exception:
                elapsed = 0.0
            rem = max(0.0, elapsed - children_of.get(r["jid"], 0.0)); total += rem; by["parent_remainder_live:" + r["scope"]] = by.get("parent_remainder_live:" + r["scope"], 0.0) + rem
            outer.append({"job": r["job"], "jid": r["jid"], "receipt": False, "live": True, "parent_remainder_so_far_s": rem}); continue
        if rc is None or rc.get("cleanup_unresolved"):
            unresolved.append(dict(r, outer=True)); total += (r.get("max_permitted_charge_s") or 0.0); outer.append({"job": r["job"], "jid": r["jid"], "receipt": rc is not None, "parent_remainder_s": None}); continue
        rem = max(0.0, rc["wall_s"] - children_of.get(r["jid"], 0.0)); total += rem; by["parent_remainder:" + r["scope"]] = by.get("parent_remainder:" + r["scope"], 0.0) + rem
        outer.append({"job": r["job"], "jid": r["jid"], "receipt": True, "wall_s": rc["wall_s"], "children_s": children_of.get(r["jid"], 0.0), "parent_remainder_s": rem})
    return total, by, unresolved, {"outer_attempts": outer, "duplicate_receipts": dup}


def inventory():
    return [c for _, cs in FAMILY_ORDER for c in cs]


def order(seed=SEED):
    rng = random.Random(seed); cells = []
    for stage, arms, budget in STAGES:
        inv = list(inventory()); rng.shuffle(inv); offset = rng.randrange(len(arms))
        for i, case in enumerate(inv):
            k = (i + offset) % len(arms); rot = arms[k:] + arms[:k]
            for a in rot:
                cells.append({"stage": stage, "arm": a, "case": case, "budget_s": budget, "kind": "ablation" if stage == "ablation_breadth" else "primary"})
    return cells


def canonical_task(cs, c, cfg_adp_sha, kernel_sha, commit):
    """the canonical task identity: inputs (raw + canonical), queries, arm, budget, memory, grace, stage, kind AND the comparator configuration"""
    task = {"model": cs["canonical_model_sha256"], "evidence": cs["canonical_evidence_sha256"], "raw_model": cs["raw_model_sha256"], "raw_evidence": cs["raw_evidence_sha256"], "queries": "all_original_variables", "arm": c["arm"], "budget_s": c["budget_s"], "memory_gib": MEM_GIB, "grace_s": GRACE_S, "kind": c["kind"], "stage": c["stage"], "config_adp_repaired_sha256": cfg_adp_sha, "pass": PASS}
    tid = hashlib.sha256(json.dumps(task, sort_keys=True).encode()).hexdigest()[:16]
    return tid, hashlib.sha256((tid + "|" + commit + "|" + kernel_sha).encode()).hexdigest()[:16]


def freeze(D):
    man_c = json.load(open(os.path.join(CENSUS_D, "CENSUS_MANIFEST.json"))); cases = {c["case"]: c for c in man_c["cases"]}
    assert sorted(cases) == sorted(inventory()), "inventory differs from the frozen census"
    br = json.load(open(os.path.join(HERE, "gbidi", "BUILD_RECORD.json"))); cfg_adp_path = os.path.join(CENSUS_D, "CONFIG_new_arm.json"); cfg_sha = sha(cfg_adp_path)
    src = sorted("gbidi/" + f for f in os.listdir(os.path.join(HERE, "gbidi")) if f.endswith((".py", ".cpp"))) + ["tests/test_gbidi.py", "adp/cell.py", "adp/checker.py", "adp/publish.py", "adp/engine.py", "adp/source.py", "adp/census/supervise.py", "adp/census/run.py", "bench/cells.py", "bench/libdai/libdai_mar", "ext/uai.py", "bidi/oracle.py"] + sorted("mdi/" + f for f in os.listdir(os.path.join(HERE, "mdi")) if f.endswith(".py"))
    fsh, _ = CR.frozen_set_hash()
    from gbidi import plan as PL, executor as EX
    for c in cases.values():                                                                             # the frozen inputs must be the census bytes NOW
        assert sha(os.path.join(HERE, c["model_path"])) == c["raw_model_sha256"] and sha(os.path.join(HERE, c["evidence_path"])) == c["raw_evidence_sha256"], c["case"]
    commit = CR.git_head()
    man = {"pass": PASS + "_2026-11-10", "frozen_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "commit": commit, "branch": subprocess.check_output(["git", "rev-parse", "--abbrev-ref", "HEAD"], cwd=HERE).decode().strip(), "python": sys.version.split()[0],
           "parent_lineage": {"v1_round": "GENERAL_BIDI_V1_2026-11-09 (paused after cell 219 at the overseer's request; preserved as evidence)", "v1_final_freeze": "a62625e66a05", "reviews": ["GENERAL_BIDI_V1_INTERIM_FULL_REVIEW_2026-11-09", "GENERAL_BIDI_FULL_ADVERSARIAL_REVIEW_R2_2026-11-09"], "repaired_adp_commit": "ec4ae4274d120bccc6ea41f826a124743ace9d7a", "frozen_numerical_set_code_hash": fsh},
           "source_files_sha256": {f: sha(os.path.join(HERE, f)) for f in src}, "kernel_build": br, "kernel_binary_sha256": br["binary_sha256"], "kernel_binary": br["binary"], "supervisor": "gbidi/supervise.py v3 (owned-tree completion; parent_jid linkage)", "arm_adapter": {"module": "gbidi/arm_adapter.py", "planned_to_producer": PRODUCER_ARM, "timing": "launch-relative delivery observed by the adapter (cell.json / output.MAR appearance) for comparators; GBIDI_LAUNCH_MONO for new arms"},
           "arms_config": EX.ARMS, "planner_constants": {"metadata_update_cap": PL.METADATA_UPDATE_CAP, "row_inspection_cap": PL.ROW_INSPECTION_CAP, "poll_units": PL.POLL_UNITS, "caps_bytes": PL.CAPS, "discovery_wall": "min(1 s, 0.05 x budget), ONE shared allowance from the start of the reductions through all candidate orders, views, supports and demand", "precisions": list(EX.PRECISIONS), "candidate_construction_order": PL.CONSTRUCTION_ORDER},
           "not_implemented": PL.NOT_IMPLEMENTED, "common_rules": list(PL.COMMON_RULES), "common_rules_note": PL.COMMON_RULES_NOTE, "counter_definitions": EX.COUNTER_DEFINITIONS,
           "shared_vs_different": {"shared_by_all_new_arms": ["gbidi.source snapshot + strict grammar + task binding", "adp.source reductions (exclude, constants, separate, alias, quotient) with the marked decoder", "gbidi.validate (untrusted-plan validation)", "gbidi/kernel.cpp explicit-frame executor (MPFR outward / binary64 with kernel-tracked labels), reserved category caps, charged polling, zero-safe local reverse", "binary64 admission (range envelope) + kernel labels", "exact enclosures through the decoder", "adp.publish dyadic grid + gbidi.verify separate task-bound verifier (incl. the pinned adp.checker point mode)", "one-pass protocol", "exact integer reference fallback on memory stop", "durable noncertifying diagnostics"],
                                  "GENERAL_BIDI_V2": "3 candidate orders (baseline = cheapest representable mandatory program), exact response views, bounded support joins + consumer storage restriction, consumer fusion by the complete-path price", "NATIVE_PLAIN_V2": "min-volume order only, identity views, FULL storage, no fusion (memory downgrades still allowed)", "A1_NO_DEMAND_MASKS": "general minus storage restriction", "A2_NO_FUSION": "general minus policy fusion", "A3_NO_RESPONSE_VIEWS": "general minus response views (identity)"},
           "config_adp_repaired_path": os.path.relpath(cfg_adp_path, HERE), "config_adp_repaired_sha256": cfg_sha, "libdai_binary_sha256": sha(os.path.join(HERE, "bench", "libdai", "libdai_mar")), "libdai_algorithm": "JTREE[inference=SUMPROD,updates=HUGIN,maxmem=8589934592]",
           "ceiling_s": CEILING_S, "closeout_reserve_s": CLOSEOUT_RESERVE_S, "grace_s": GRACE_S, "launch_overhead_s": LAUNCH_OVERHEAD_S, "memory_budget_gib": MEM_GIB, "thread_env": THREAD_ENV, "seed": SEED, "order_procedure": "empirical_plan.txt §3 (single continuing Random(20261109); per stage shuffle + randrange offset; rotate arm list by (i+offset) mod n)",
           "query_contract": "every original singleton marginal; eps = 1/200; max width 1/100; exact dyadic-grid point; separate task-bound point verification; LATE_OUTPUT classified on the launch-relative clock",
           "cases": {c: {k: cases[c][k] for k in ("family", "model_path", "evidence_path", "raw_model_sha256", "raw_evidence_sha256", "canonical_model_sha256", "canonical_evidence_sha256", "variables")} for c in inventory()}, "unavailable_slots": [{"case": c, "family": f, "status": "INPUT_UNAVAILABLE"} for c, f in UNAVAILABLE], "cells": []}
    for i, c in enumerate(order()):
        cs = cases[c["case"]]; tid, cid = canonical_task(cs, c, cfg_sha, br["binary_sha256"], commit)
        man["cells"].append(dict(c, index=i, task_id=tid, cell_id=cid, producer_arm=(c["arm"] if c["arm"] in GB_ARMS else PRODUCER_ARM[c["arm"]]), out_dir="cells/%s/%03d__%s__%s__%ds__%s" % (c["stage"], i, c["case"], c["arm"], int(c["budget_s"]), tid), max_permitted_charge_s=c["budget_s"] + GRACE_S + LAUNCH_OVERHEAD_S))
    man["counts"] = {"cells": len(man["cells"]), "nominal_s": sum(c["budget_s"] for c in man["cells"]), "max_permitted_s": sum(c["max_permitted_charge_s"] for c in man["cells"]), "per_stage": {s: sum(1 for c in man["cells"] if c["stage"] == s) for s, _, _ in STAGES}}
    assert man["counts"]["cells"] == 414 and man["counts"]["nominal_s"] == 17480.0 and man["counts"]["max_permitted_s"] == 19964.0
    assert reconcile_manifest(man) is None
    json.dump(man, open(os.path.join(D, "GB_MANIFEST.json"), "w"), indent=1); print(json.dumps({"cells": man["counts"], "commit": man["commit"][:12], "kernel": br["binary_sha256"][:12]}))


def reconcile_manifest(man):
    """independent reconstruction of the order AND of every task_id / cell_id from the canonical task; uniqueness of cell ids and output dirs. Returns None or the reason.
    A manifest marked qualification_unfrozen (tiny end-to-end harness controls on unfrozen source; NEVER a campaign) skips only the 414-cell order check."""
    o = man["cells"] if man.get("qualification_unfrozen") else order(man["seed"])
    if len(o) != len(man["cells"]):
        return "cell count"
    for a, b in zip(man["cells"], o):
        if (a["stage"], a["arm"], a["case"], a["budget_s"]) != (b["stage"], b["arm"], b["case"], b["budget_s"]):
            return "order differs at index %d" % a["index"]
        tid, cid = canonical_task(man["cases"][a["case"]], b, man["config_adp_repaired_sha256"], man["kernel_binary_sha256"], man["commit"])
        if a["task_id"] != tid or a["cell_id"] != cid:
            return "task/cell id of index %d does not reconstruct" % a["index"]
        if not a["out_dir"].endswith("__" + tid):
            return "out_dir of index %d is not bound to its task" % a["index"]
    if len({c["cell_id"] for c in man["cells"]}) != len(man["cells"]) or len({c["out_dir"] for c in man["cells"]}) != len(man["cells"]):
        return "cell ids / output directories are not unique"
    return None


def reconcile_order(D):
    return reconcile_manifest(json.load(open(os.path.join(D, "GB_MANIFEST.json")))) is None


def preflight(D, man):
    head = CR.git_head()
    if not man.get("qualification_unfrozen"):                                                            # a campaign manifest: the frozen commit must be HEAD's content for every frozen file and the tree clean
        if subprocess.run(["git", "diff", "--quiet", man["commit"], head, "--"] + list(man["source_files_sha256"]), cwd=HERE).returncode != 0:
            raise SystemExit("a frozen source file differs between the frozen commit %s and HEAD %s" % (man["commit"], head))
        if subprocess.run(["git", "status", "--porcelain", "--"] + list(man["source_files_sha256"]), cwd=HERE, capture_output=True, text=True).stdout.strip():
            raise SystemExit("uncommitted change to a frozen source file")
    bad = [f for f, h in man["source_files_sha256"].items() if sha(os.path.join(HERE, f)) != h]
    if bad:
        raise SystemExit("frozen source hashes differ: %s" % bad)
    br = json.load(open(os.path.join(HERE, "gbidi", "BUILD_RECORD.json")))
    if br["binary_sha256"] != man["kernel_binary_sha256"] or sha(os.path.join(HERE, br["binary"])) != br["binary_sha256"]:
        raise SystemExit("kernel binary differs from the frozen manifest")
    if sha(os.path.join(HERE, man["config_adp_repaired_path"])) != man["config_adp_repaired_sha256"]:
        raise SystemExit("comparator configuration differs from the frozen manifest")
    r = reconcile_manifest(man)
    if r is not None:
        raise SystemExit("manifest does not reconcile: %s" % r)
    return head


def inputs_match(man, case):
    cs = man["cases"][case]; return sha(os.path.join(HERE, cs["model_path"])) == cs["raw_model_sha256"] and sha(os.path.join(HERE, cs["evidence_path"])) == cs["raw_evidence_sha256"]


def run(D, stage):
    man = json.load(open(os.path.join(D, "GB_MANIFEST.json"))); head = preflight(D, man); idx = RC.ledger_index(D)
    lock = open(os.path.join(D, "RUN_LOCK"), "a+")
    try:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        raise SystemExit("another runner holds the run lock of %s" % D)
    lock.seek(0); lock.truncate(); lock.write(json.dumps({"pid": os.getpid(), "stage": stage, "utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())})); lock.flush()
    ledger = ledger_path(D); cfg_adp = os.path.join(HERE, man["config_adp_repaired_path"]); t_stage = time.monotonic()
    open(os.path.join(D, "stage_%s_started.txt" % stage), "a").write("started %s head %s\n" % (time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), head))
    def stopfile(status, **kw):
        json.dump(dict(status=status, utc=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), **kw), open(os.path.join(D, "RUN_STOPPED.json"), "w")); print("STOP:", status); return
    for c in man["cells"]:
        if c["stage"] != stage:
            continue
        out = os.path.join(D, c["out_dir"]); cs = man["cases"][c["case"]]
        if os.path.exists(os.path.join(out, "cell.json")):
            row = RC.reconcile(D, man, c, idx)                                                       # the SAME reconciler as the closeout: an existing record is done only if ACCEPTED (or a typed, bound non-success)
            if not row["accepted"] and not (row.get("record_status") not in RC.SUCCESS and not [x for x in row["reasons"] if not x.startswith(("launch-relative", "success"))]):
                return stopfile("RESUME_CONFLICT", at_index=c["index"], detail="existing record is not reconciled to the planned attempt: %s" % row["reasons"][:4])
            continue
        if os.path.exists(os.path.join(out, "NOT_LAUNCHED.json")):
            continue
        if os.path.exists(os.path.join(D, "STOP_REQUESTED")):
            return stopfile("STOP_REQUESTED", at_index=c["index"])
        if not inputs_match(man, c["case"]) or sha(cfg_adp) != man["config_adp_repaired_sha256"]:
            return stopfile("TASK_MISMATCH", at_index=c["index"], detail="live input / configuration bytes differ from the frozen manifest")
        total, by, unresolved, extra = charged(D); remaining_commit = sum(x["max_permitted_charge_s"] for x in man["cells"] if not os.path.exists(os.path.join(D, x["out_dir"], "cell.json")))
        if unresolved or extra["duplicate_receipts"]:
            return stopfile("NOT_LAUNCHED_UNRESOLVED_CLEANUP", unresolved=[u["job"] for u in unresolved], duplicate_receipts=extra["duplicate_receipts"])
        if total + remaining_commit + CLOSEOUT_RESERVE_S > CEILING_S:
            os.makedirs(out, exist_ok=True); json.dump({"status": "NOT_LAUNCHED_BUDGET", "charged_s": total, "remaining_commit_s": remaining_commit, "reserve_s": CLOSEOUT_RESERVE_S, "ceiling_s": CEILING_S}, open(os.path.join(out, "NOT_LAUNCHED.json"), "w")); print("STOP: budget guard"); return
        try:
            os.makedirs(out, exist_ok=False)
        except FileExistsError:
            if os.listdir(out):
                return stopfile("RESUME_CONFLICT", at_index=c["index"], detail="non-empty output directory without cell.json")
        mp = os.path.join(HERE, cs["model_path"]); ep = os.path.join(HERE, cs["evidence_path"]); t = time.monotonic(); expected = json.dumps({"raw_model_sha256": cs["raw_model_sha256"], "raw_evidence_sha256": cs["raw_evidence_sha256"], "task_id": c["task_id"], "cell_id": c["cell_id"]})
        if c["arm"] in GB_ARMS:
            inner = [PY, "-m", "gbidi.cell", c["arm"], mp, ep, out, "%.3f" % c["budget_s"], "{}", expected]
        else:
            inner = [PY, "-m", "gbidi.arm_adapter", c["arm"], mp, ep, out, "%.3f" % c["budget_s"], cfg_adp if c["arm"] == "ADP_REPAIRED" else "{}", expected]     # frozen adapter around the PINNED producer
        job = RC.job_name(c)
        cmd = [PY, "-m", "gbidi.supervise", "--ledger", ledger, "--scope", "matrix_" + stage, "--job", job, "--timeout", "%.3f" % c["budget_s"], "--mem-gib", str(MEM_GIB), "--cwd", HERE,
               "--stdout", os.path.join(out, "supervisor.log"), "--stderr", os.path.join(out, "supervisor.log")] + [x for k, v in THREAD_ENV.items() for x in ("--env", "%s=%s" % (k, v))] + ["--env", "PYTHONPATH=" + HERE, "--env", "GBIDI_LAUNCH_MONO=%.9f" % t, "--"] + inner
        subprocess.run(cmd, cwd=HERE); wall = time.monotonic() - t; idx = RC.ledger_index(D)
        rec = json.load(open(os.path.join(out, "cell.json"))) if os.path.exists(os.path.join(out, "cell.json")) else None
        if rec is None:
            json.dump({"status": "NO_RECORD", "arm": c["arm"] if c["arm"] in GB_ARMS else PRODUCER_ARM[c["arm"]], "note": "the cell process left no cell.json (killed before writing); see supervisor.log / progress.json / diagnostic_record.json / adapter.json"}, open(os.path.join(out, "cell.json"), "w"))
        row = RC.reconcile(D, man, c, idx)
        print("%-3d %-22s %-20s %4ds  %-28s %-10s %7.2fs  parent+child %.2fs %s" % (c["index"], c["arm"], c["case"], int(c["budget_s"]), row.get("record_status") or "NO_RECORD", "ACCEPTED" if row["accepted"] else "NOT_ACC", row.get("delivery_from_launch_s") or 0, wall, "" if row["accepted"] else row["reasons"][:2]), flush=True)
    open(os.path.join(D, "stage_%s_finished.txt" % stage), "a").write("finished %s parent_wall_s %.3f\n" % (time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), time.monotonic() - t_stage))
    total, by, unresolved, extra = charged(D); print("stage %s done; charged total %.1f s of %.0f; unresolved %d" % (stage, total, CEILING_S, len(unresolved)))


def status(D):
    total, by, unresolved, extra = charged(D); print(json.dumps({"charged_s": round(total, 3), "by_scope": {k: round(v, 3) for k, v in by.items()}, "unresolved": [u["job"] for u in unresolved], "outer_attempts": extra["outer_attempts"], "duplicate_receipts": extra["duplicate_receipts"]}))


if __name__ == "__main__":
    cmd = sys.argv[1]; D = os.path.abspath(sys.argv[2])
    {"freeze": lambda: freeze(D), "run": lambda: run(D, sys.argv[3]), "status": lambda: status(D)}[cmd]()
