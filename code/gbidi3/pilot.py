"""GENERAL_BIDI_COMPLETE_V3 broad-round harness (brief §19-§22): propose the 414-row manifest by the EXACT frozen procedure (one random.Random(20261109);
per stage shuffle + randrange offset; rotate the arm list by (i+offset) mod n), run (every cell a charged job through gbidi.supervise; the stage runner itself
a supervised outer job), status. Protocol of the repaired GENERAL_BIDI_V2 harness (H2 / H3 / R2-09): manifest carries the sha256 of every input file and of
the comparator configuration; before EVERY launch the live model / evidence / config bytes are compared with the manifest; reconcile_manifest reconstructs
task_id / cell_id and requires unique ids / output directories; one exclusive run lock; resume only through the strict reconciler; nonnested budget guard
(unresolved starts charged at max permitted) + remaining commitment + closeout reserve under the ceiling; STOP_REQUESTED stops between cells.
At the present stop point only `propose` is used (writes GB_MANIFEST_PROPOSED.json, status PROPOSED_NOT_FROZEN); `freeze` and `run` exist for the
reviewed round and refuse to act on a proposed manifest without the explicit --authorized flag file FREEZE_AUTHORIZED.txt in the run directory.
    python -m gbidi3.pilot propose D ; python -m gbidi3.pilot freeze D ; python -m gbidi3.pilot run D STAGE ; python -m gbidi3.pilot status D"""
from __future__ import annotations
import os, sys, json, time, math, hashlib, random, subprocess, fcntl
HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__))); sys.path.insert(0, HERE)
from adp.census import run as CR
from gbidi3 import reconcile as RC
from gbidi3.arm_adapter import PRODUCER_ARM
PY = sys.executable
CEILING_S = 28800.0; PREPARATION_CAP_S = 5000.0; MATRIX_RESERVE_S = 19964.0; INSPECTION_RESERVE_S = 1200.0; CLOSEOUT_RESERVE_S = 1200.0; CONTINGENCY_S = 1436.0
GRACE_S = 4.0; LAUNCH_OVERHEAD_S = 2.0; MEM_GIB = 8.0; SEED = 20261109
THREAD_ENV = {"OMP_NUM_THREADS": "1", "OPENBLAS_NUM_THREADS": "1", "MKL_NUM_THREADS": "1", "VECLIB_MAXIMUM_THREADS": "1", "NUMEXPR_NUM_THREADS": "1", "PYTHONHASHSEED": "0"}
FAMILY_ORDER = [("GridBN", ["BN_12", "BN_13", "BN_15", "BN_31"]), ("Grids", ["Grids_11", "Grids_14", "Grids_15", "Grids_17"]), ("Pedigree", ["Pedigree_11", "Pedigree_12", "Pedigree_13"]), ("Promedus", ["Promedus_33", "Promedus_14", "Promedus_12", "Promedus_37"]), ("CSP", ["CSP_12", "CSP_11", "CSP_13"]), ("DBN", ["DBN_11", "DBN_12", "DBN_15", "DBN_16"]), ("ObjectDetection", ["ObjectDetection_34", "ObjectDetection_56", "ObjectDetection_39", "ObjectDetection_24"]), ("Segmentation", ["Segmentation_11", "Segmentation_12", "Segmentation_16", "Segmentation_13"]), ("Protein", ["1qt9", "1jer", "1aie", "1npl"]), ("bnlearn", ["ASIA", "CHILD", "INSURANCE", "WATER", "MILDEW", "ALARM", "BARLEY", "HAILFINDER", "WIN95PTS", "MUNIN1", "ANDES", "DIABETES"])]
UNAVAILABLE = [("Pedigree_slot_4", "Pedigree"), ("CSP_slot_4", "CSP")]
STAGES = [("primary_breadth", ["GENERAL_BIDI_COMPLETE_V3", "NATIVE_PLAIN_COMPLETE_V3", "ADP_REPAIRED", "EXACT_LIBDAI"], 20.0), ("primary_depth", ["GENERAL_BIDI_COMPLETE_V3", "NATIVE_PLAIN_COMPLETE_V3"], 120.0), ("ablation_breadth", ["A1_NO_DEMAND_MASKS", "A2_NO_FUSION", "A3_NO_RESPONSE_VIEWS"], 20.0)]
GB_ARMS = {"GENERAL_BIDI_COMPLETE_V3", "NATIVE_PLAIN_COMPLETE_V3", "A1_NO_DEMAND_MASKS", "A2_NO_FUSION", "A3_NO_RESPONSE_VIEWS"}
CENSUS_D = os.path.join(HERE, "runs", "mdi_2026-10-28", "AGGREGATE_DP_CENSUS_2026-11-08")
PASS = "GENERAL_BIDI_COMPLETE_V3"
CELL_CONFIG = {"allow_binary64": True, "reference_fallback": True}


def sha(p):
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for ch in iter(lambda: f.read(1 << 20), b""):
            h.update(ch)
    return h.hexdigest()


def ledger_path(D):
    return os.path.join(D, "GB_LEDGER.jsonl")


def charged(D):
    """nonnested accounting (rule: children + measured nonnegative parent-only remainder): every non-outer START once (receipt wall; no receipt /
    duplicate receipts / unresolved cleanup -> max permitted, listed unresolved); every OUTER attempt's parent remainder once = outer wall - its own
    children (parent_jid); the live outer attempt this runner executes inside is charged elapsed - children so far."""
    p = ledger_path(D); rows = [json.loads(l) for l in open(p)] if os.path.exists(p) else []
    rec = {}; dup = []
    for r in rows:
        if r["kind"] == "RECEIPT":
            if r["jid"] in rec:
                dup.append(r["jid"])
            rec[r["jid"]] = r
    total = 0.0; unresolved = []; by = {}; outer = []; children_of = {}; measured = 0.0; envelope = 0.0; unknown_wall = []; parent_unknown_children = {}
    def finite(x):
        return isinstance(x, (int, float)) and not isinstance(x, bool) and math.isfinite(x) and x >= 0
    for r in rows:
        if r["kind"] != "START" or r["scope"].startswith("stage_outer"):
            continue
        rc = rec.get(r["jid"]); pj = r.get("parent_jid") or (rc or {}).get("parent_jid"); cap = r.get("max_permitted_charge_s")
        if rc is not None and not finite(rc.get("wall_s")):
            # a terminal receipt with an UNKNOWN wall (parent-generated PARENT_CLEANUP_KILL): never arithmetic on null; charged at the attempt's envelope, listed separately
            env = cap if finite(cap) else 0.0; total += env; envelope += env; by["envelope_unknown_wall:" + r["scope"]] = by.get("envelope_unknown_wall:" + r["scope"], 0.0) + env
            unknown_wall.append({"job": r["job"], "jid": r["jid"], "outcome": rc.get("outcome"), "envelope_s": env, "cleanup_unresolved": bool(rc.get("cleanup_unresolved")), "envelope_known": finite(cap)})
            if pj:
                parent_unknown_children[pj] = parent_unknown_children.get(pj, 0) + 1
            if rc.get("cleanup_unresolved") or not finite(cap):
                unresolved.append(dict(r, cleanup_unresolved=bool(rc.get("cleanup_unresolved")), wall_unknown=True))
            continue
        if rc is not None and not rc.get("cleanup_unresolved") and r["jid"] not in dup:
            total += rc["wall_s"]; measured += rc["wall_s"]; by[r["scope"]] = by.get(r["scope"], 0.0) + rc["wall_s"]
            if pj:
                children_of[pj] = children_of.get(pj, 0.0) + rc["wall_s"]
        elif rc is not None:
            env = max(rc["wall_s"], cap if finite(cap) else 0.0); unresolved.append(dict(r, cleanup_unresolved=True)); total += env; envelope += env
        else:
            env = cap if finite(cap) else 0.0; unresolved.append(r); total += env; envelope += env
    live_parent = os.environ.get("GBIDI_PARENT_JID")
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
        if rc is None or rc.get("cleanup_unresolved") or not finite(rc.get("wall_s")):
            env = r.get("max_permitted_charge_s") if finite(r.get("max_permitted_charge_s")) else 0.0; unresolved.append(dict(r, outer=True)); total += env; envelope += env; outer.append({"job": r["job"], "jid": r["jid"], "receipt": rc is not None, "parent_remainder_s": None}); continue
        if parent_unknown_children.get(r["jid"]):
            # a child of this outer attempt has an UNKNOWN wall: the parent-only remainder cannot be inferred by subtraction; the outer wall is charged WHOLE (conservative, no manufactured remainder)
            total += rc["wall_s"]; envelope += rc["wall_s"]; by["outer_whole_unknown_child:" + r["scope"]] = by.get("outer_whole_unknown_child:" + r["scope"], 0.0) + rc["wall_s"]
            outer.append({"job": r["job"], "jid": r["jid"], "receipt": True, "wall_s": rc["wall_s"], "children_s_measured": children_of.get(r["jid"], 0.0), "children_unknown_wall": parent_unknown_children[r["jid"]], "parent_remainder_s": None, "charged": "whole outer wall (an unknown child wall forbids subtraction)"}); continue
        rem = max(0.0, rc["wall_s"] - children_of.get(r["jid"], 0.0)); total += rem; measured += rem; by["parent_remainder:" + r["scope"]] = by.get("parent_remainder:" + r["scope"], 0.0) + rem
        outer.append({"job": r["job"], "jid": r["jid"], "receipt": True, "wall_s": rc["wall_s"], "children_s": children_of.get(r["jid"], 0.0), "parent_remainder_s": rem})
    return total, by, unresolved, {"outer_attempts": outer, "duplicate_receipts": dup, "measured_s": measured, "envelope_s": envelope, "unknown_wall_receipts": unknown_wall, "rule": "total = measured receipted walls + conservative ENVELOPE charges (unknown / unreceipted / unresolved attempts at max_permitted_charge_s; an outer attempt with an unknown-wall child charged whole); null / nonfinite walls are never used in arithmetic"}


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
    task = {"model": cs["canonical_model_sha256"], "evidence": cs["canonical_evidence_sha256"], "raw_model": cs["raw_model_sha256"], "raw_evidence": cs["raw_evidence_sha256"], "queries": "all_original_variables", "eps": "1/200", "max_width": "1/100", "arm": c["arm"], "budget_s": c["budget_s"], "memory_gib": MEM_GIB, "grace_s": GRACE_S, "kind": c["kind"], "stage": c["stage"], "config_adp_repaired_sha256": cfg_adp_sha, "cell_config": CELL_CONFIG, "pass": PASS}
    tid = hashlib.sha256(json.dumps(task, sort_keys=True).encode()).hexdigest()[:16]
    return tid, hashlib.sha256((tid + "|" + commit + "|" + kernel_sha).encode()).hexdigest()[:16]


def source_set():
    return sorted("gbidi3/" + f for f in os.listdir(os.path.join(HERE, "gbidi3")) if f.endswith((".py", ".cpp"))) + ["gbidi/supervise.py", "tests/test_gbidi3_complete.py", "adp/cell.py", "adp/checker.py", "adp/publish.py", "adp/engine.py", "adp/source.py", "adp/census/supervise.py", "adp/census/run.py", "bench/cells.py", "bench/libdai/libdai_mar", "ext/uai.py"] + sorted("mdi/" + f for f in os.listdir(os.path.join(HERE, "mdi")) if f.endswith(".py"))


def build_manifest(D, proposed):
    man_c = json.load(open(os.path.join(CENSUS_D, "CENSUS_MANIFEST.json"))); cases = {c["case"]: c for c in man_c["cases"]}
    assert sorted(cases) == sorted(inventory()), "inventory differs from the frozen census"
    br = json.load(open(os.path.join(HERE, "gbidi3", "BUILD_RECORD.json"))); cfg_adp_path = os.path.join(CENSUS_D, "CONFIG_new_arm.json"); cfg_sha = sha(cfg_adp_path)
    fsh, _ = CR.frozen_set_hash()
    from gbidi3 import planner as PL, executor as EX, clock as GC, memory as GM
    for c in cases.values():
        assert sha(os.path.join(HERE, c["model_path"])) == c["raw_model_sha256"] and sha(os.path.join(HERE, c["evidence_path"])) == c["raw_evidence_sha256"], c["case"]
    commit = CR.git_head(); dirty = subprocess.run(["git", "status", "--porcelain"], cwd=HERE, capture_output=True, text=True).stdout.strip()
    man = {"pass": PASS + "_2026-11-10", "manifest_status": "PROPOSED_NOT_FROZEN" if proposed else "FROZEN", "frozen_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "commit": commit, "working_tree_dirty": bool(dirty), "branch": subprocess.check_output(["git", "rev-parse", "--abbrev-ref", "HEAD"], cwd=HERE).decode().strip(), "python": sys.version.split()[0],
           "parent_lineage": {"v2_closeout_commit": "88a3e325e159b92eb6655ef31dd5bba9f9e1e58c", "v2_package_record_commit": "16c79e67eae569d4e998d51333aaabfe442e6853", "v1_round": "GENERAL_BIDI_V1_2026-11-09 (paused after cell 219; preserved)", "v1_final_freeze": "a62625e66a05897d83fe4dd65aa479ba54834ff4", "repaired_adp_commit": "ec4ae4274d120bccc6ea41f826a124743ace9d7a", "repaired_adp_package_record_commit": "3a0648fbf47f3c80051c001c7c681644a12d122c", "frozen_numerical_set_code_hash": fsh, "repaired_adp_code_hash_expected": "da5b2c49b1bd34d181fa1a18f123304d1cfb4f651a995c5f82081dff05500404"},
           "source_files_sha256": {f: sha(os.path.join(HERE, f)) for f in source_set() if os.path.exists(os.path.join(HERE, f))}, "kernel_build": br, "kernel_binary_sha256": br["binary_sha256"], "kernel_binary": br["binary"], "supervisor": "gbidi/supervise.py v3 (owned-tree completion; parent_jid linkage) -- unchanged from the V2 closeout", "arm_adapter": {"module": "gbidi3/arm_adapter.py", "planned_to_producer": PRODUCER_ARM, "timing": "launch-relative delivery observed by the adapter for comparators; GBIDI_LAUNCH_MONO for new arms"},
           "arms_config": {a: dict(PL.ARMS[a], cell_config=CELL_CONFIG) for a in PL.ARMS}, "planner_constants": dict(PL.PLANNER_CONSTANTS, caps_bytes=GM.CAPS, precisions=list(EX.PRECISIONS), optional_allowance="min(1 s, 0.05 x budget), ONE shared allowance from the start of the reductions", poll_units=GC.POLL_UNITS), "common_rules": list(PL.COMMON_RULES), "counter_definitions": EX.COUNTER_DEFINITIONS,
           "shared_vs_different": shared_vs_different(), "config_adp_repaired_path": os.path.relpath(cfg_adp_path, HERE), "config_adp_repaired_sha256": cfg_sha, "libdai_binary_sha256": sha(os.path.join(HERE, "bench", "libdai", "libdai_mar")), "libdai_algorithm": "JTREE[inference=SUMPROD,updates=HUGIN,maxmem=8589934592]",
           "ceiling_s": CEILING_S, "mem_gib": MEM_GIB, "allocation_s": {"qualification_builds_synthetic": PREPARATION_CAP_S, "matrix_414_cells_plus_launch_cleanup": MATRIX_RESERVE_S, "uniform_inspection_analysis": INSPECTION_RESERVE_S, "closeout_packaging": CLOSEOUT_RESERVE_S, "contingency": CONTINGENCY_S}, "closeout_reserve_s": CLOSEOUT_RESERVE_S, "grace_s": GRACE_S, "launch_overhead_s": LAUNCH_OVERHEAD_S, "memory_budget_gib": MEM_GIB, "thread_env": THREAD_ENV, "seed": SEED, "order_procedure": "brief §20: single continuing random.Random(20261109); per stage copy the ORIGINAL inventory, shuffle once, draw one randrange(number_of_arms) offset; at shuffled position i rotate the stage's arm list left by (i+offset) mod n",
           "query_contract": "every original singleton marginal; eps = 1/200; DELIVERED grid max width <= 1/100 (and pre-grid width recorded); exact dyadic-grid point; separate task-bound point verification; LATE_OUTPUT classified on the launch-relative clock",
           "cases": {c: {k: cases[c][k] for k in ("family", "model_path", "evidence_path", "raw_model_sha256", "raw_evidence_sha256", "canonical_model_sha256", "canonical_evidence_sha256", "variables")} for c in inventory()}, "unavailable_slots": [{"case": c, "family": f, "status": "INPUT_UNAVAILABLE"} for c, f in UNAVAILABLE], "cells": []}
    from gbidi3 import source as GS, identity as ID
    for c in inventory():
        S = GS.Snapshot(os.path.join(HERE, cases[c]["model_path"]), os.path.join(HERE, cases[c]["evidence_path"]))
        for k in ("canonical_v2_model_sha256", "canonical_v2_evidence_sha256", "canonical_version", "orig_card", "eps", "max_width", "queries_sha256"):
            man["cases"][c][k] = S.task[k]
    man["python_sources_sha256"] = ID.python_sources_sha256(); man["protocol"] = ID.PROTOCOL
    for i, c in enumerate(order()):
        cs = cases[c["case"]]; tid, cid = canonical_task(cs, c, cfg_sha, br["binary_sha256"], commit)
        man["cells"].append(dict(c, index=i, task_id=tid, cell_id=cid, producer_arm=(c["arm"] if c["arm"] in GB_ARMS else PRODUCER_ARM[c["arm"]]), out_dir="cells/%s/%03d__%s__%s__%ds__%s" % (c["stage"], i, c["case"], c["arm"], int(c["budget_s"]), tid), max_permitted_charge_s=c["budget_s"] + GRACE_S + LAUNCH_OVERHEAD_S))
    man["counts"] = {"cells": len(man["cells"]), "nominal_s": sum(c["budget_s"] for c in man["cells"]), "max_permitted_s": sum(c["max_permitted_charge_s"] for c in man["cells"]), "per_stage": {s: sum(1 for c in man["cells"] if c["stage"] == s) for s, _, _ in STAGES}}
    assert man["counts"]["cells"] == 414 and man["counts"]["nominal_s"] == 17480.0 and man["counts"]["max_permitted_s"] == 19964.0 and man["counts"]["per_stage"] == {"primary_breadth": 184, "primary_depth": 92, "ablation_breadth": 138}
    assert reconcile_manifest(man) is None
    return man


def shared_vs_different():
    return {"shared_by_all_seven_arms": ["gbidi/supervise.py outer supervisor (sampled 8 GiB process-tree RSS, one worker, THREAD_ENV = 1 thread)", "launch-relative timing (GBIDI_LAUNCH_MONO)", "the frozen 46-case inputs (raw bytes hashed in the manifest)", "the strict reconciler gbidi3.reconcile"],
            "shared_by_the_five_new_arms": ["gbidi3.source snapshot + strict grammar + task binding (raw / legacy canonical / canonical_v2)", "adp.source common reductions (exclude, constants, separate, alias, quotient) with the marked decoder; pinned", "gbidi3.trusted snapshot + independent replay (pinned adp.checker.SourceReplay)", "gbidi3.validate (untrusted-plan validation -> Validated)", "gbidi3/kernel3.cpp (explicit frames, dense blocks, sparse joins, indexed stream, LRU, pending deltas, outward MPFR / binary64 labels, reserved categories, polling)", "binary64 admission (exact leaf conversion + leaf range predicate) + kernel runtime labels", "enclosure through the trusted decoder", "adp.publish dyadic grid + delivered-width check + gbidi3.verify separate task-bound verifier (incl. the pinned adp.checker point mode)", "one-pass protocol", "exact integer fallback on memory stop / not representable", "durable noncertifying diagnostics", "gbidi3.memory host-side ledger"],
            "GENERAL_BIDI_COMPLETE_V3": "three candidate orders; general region planner (one-/two-axis cutsets, residual components); exact response views; support joins + consumer demand restriction (D1/D2); consumer fusion by whole-path price (D3); SPARSE / DENSE / STREAM / CACHE storage by price and caps",
            "NATIVE_PLAIN_COMPLETE_V3": "min-volume order with original-order fallback; bucket schedule (one-axis cutsets); identity views; FULL demand; no fusion; the SAME storage substrate (dense blocks, sparse joins, stream, cache) under the same caps",
            "A1_NO_DEMAND_MASKS": "GENERAL minus D1/D2 (demand restriction off; supports still computed for fusion pricing)", "A2_NO_FUSION": "GENERAL minus D3", "A3_NO_RESPONSE_VIEWS": "GENERAL minus V (identity views)",
            "ADP_REPAIRED": "pinned adp.cell (AGGREGATE_DP_V1 repaired r3, code hash da5b2c49...) through gbidi3.arm_adapter with CONFIG_new_arm.json; its own checker and publication; CERTIFIED under its own contract", "EXACT_LIBDAI": "pinned bench.cells EXACT (libDAI JTREE HUGIN, maxmem 8 GiB, one worker) through gbidi3.arm_adapter; COMPLETE uncertified floating output validated by bench.cells.validate_mar",
            "not_shared_disclosed": ["comparators do not use the new native arithmetic, rules or verifier (by design)", "libDAI's guarantee is weaker (uncertified floating point)", "GENERAL-vs-PLAIN measures the planning / scheduling bundle on a shared substrate, not one isolated bit"]}


def propose(D):
    man = build_manifest(D, proposed=True); json.dump(man, open(os.path.join(D, "GB_MANIFEST_PROPOSED.json"), "w"), indent=1)
    print(json.dumps({"status": man["manifest_status"], "cells": man["counts"], "commit": man["commit"][:12], "dirty": man["working_tree_dirty"], "kernel": man["kernel_binary_sha256"][:12]}))


def freeze(D):
    if not os.path.exists(os.path.join(D, "FREEZE_AUTHORIZED.txt")):
        raise SystemExit("REFUSED: no FREEZE_AUTHORIZED.txt in %s (the brief authorizes a freeze only after a passing review)" % D)
    man = build_manifest(D, proposed=False)
    if man["working_tree_dirty"]:
        raise SystemExit("REFUSED: the working tree is dirty; a freeze binds a committed source state")
    json.dump(man, open(os.path.join(D, "GB_MANIFEST.json"), "w"), indent=1); print(json.dumps({"status": "FROZEN", "cells": man["counts"], "commit": man["commit"][:12]}))


def reconcile_manifest(man):
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


def preflight(D, man):
    try:
        head = CR.git_head()
    except Exception:
        head = None
    if head is None and not man.get("qualification_unfrozen"):
        raise SystemExit("REFUSED: a frozen manifest requires a Git checkout (the frozen commit must be verifiable)")
    head = head or "NO_GIT_CHECKOUT (qualification manifest; a clean extraction is not a Git checkout)"
    if man.get("manifest_status") != "FROZEN" and not man.get("qualification_unfrozen"):
        raise SystemExit("REFUSED: the manifest is %s, not FROZEN" % man.get("manifest_status"))
    if not man.get("qualification_unfrozen"):
        if subprocess.run(["git", "diff", "--quiet", man["commit"], head, "--"] + list(man["source_files_sha256"]), cwd=HERE).returncode != 0:
            raise SystemExit("a frozen source file differs between the frozen commit %s and HEAD %s" % (man["commit"], head))
        if subprocess.run(["git", "status", "--porcelain", "--"] + list(man["source_files_sha256"]), cwd=HERE, capture_output=True, text=True).stdout.strip():
            raise SystemExit("uncommitted change to a frozen source file")
    bad = [f for f, h in man["source_files_sha256"].items() if sha(os.path.join(HERE, f)) != h]
    if bad:
        raise SystemExit("frozen source hashes differ: %s" % bad)
    br = json.load(open(os.path.join(HERE, "gbidi3", "BUILD_RECORD.json")))
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


def _no_record_stub(out, c, cs):
    json.dump({"status": "NO_RECORD", "arm": c["arm"] if c["arm"] in GB_ARMS else PRODUCER_ARM[c["arm"]], "planned_arm": c["arm"], "cell_id": c["cell_id"], "task_id": c["task_id"], "budget_s": c["budget_s"], "expected_task": {"raw_model_sha256": cs["raw_model_sha256"], "raw_evidence_sha256": cs["raw_evidence_sha256"], "cell_id": c["cell_id"], "task_id": c["task_id"]}, "producer_diagnostics": "UNAVAILABLE", "note": "the cell process left no cell.json (killed before writing); see supervisor.log / progress.json / diagnostic_record.json / adapter.json"}, open(os.path.join(out, "cell.json"), "w"))


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
        prior = idx.get(RC.job_name(c)); launched_before = bool(prior and prior["START"])
        if os.path.exists(os.path.join(out, "cell.json")) or launched_before:
            if launched_before and not os.path.exists(os.path.join(out, "cell.json")):
                os.makedirs(out, exist_ok=True); _no_record_stub(out, c, cs)                    # resume after an interrupted stage (parent cleanup / kill): the typed stub is written here, never a relaunch
            row = RC.reconcile(D, man, c, idx)                                                        # the ONE reconciler: a reconciled attempt (success OR typed noncertifying NO_RECORD / stop) is done; a genuine identity conflict stops
            if not row["accepted"]:
                return stopfile("RESUME_CONFLICT", at_index=c["index"], detail="existing attempt is not reconciled to the planned cell: %s" % row["reasons"][:4])
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
        if total + remaining_commit + INSPECTION_RESERVE_S + CLOSEOUT_RESERVE_S > CEILING_S:
            os.makedirs(out, exist_ok=True); json.dump({"status": "NOT_LAUNCHED_BUDGET", "charged_s": total, "remaining_commit_s": remaining_commit, "reserve_s": INSPECTION_RESERVE_S + CLOSEOUT_RESERVE_S, "ceiling_s": CEILING_S}, open(os.path.join(out, "NOT_LAUNCHED.json"), "w")); print("STOP: budget guard"); return
        try:
            os.makedirs(out, exist_ok=False)
        except FileExistsError:
            if os.listdir(out):
                return stopfile("RESUME_CONFLICT", at_index=c["index"], detail="non-empty output directory without cell.json")
        mp = os.path.join(HERE, cs["model_path"]); ep = os.path.join(HERE, cs["evidence_path"]); t = time.monotonic(); expected = json.dumps({"raw_model_sha256": cs["raw_model_sha256"], "raw_evidence_sha256": cs["raw_evidence_sha256"], "task_id": c["task_id"], "cell_id": c["cell_id"]})
        cell_py = os.environ.get("GBIDI_CELL_PY") or PY                                     # qualification override (launch-failure control, review C4): any attempt launched with another interpreter is accepted ONLY as a typed LAUNCH_FAILED (gbidi3.reconcile)
        if c["arm"] in GB_ARMS:
            inner = [cell_py, "-m", "gbidi3.cell", c["arm"], mp, ep, out, "%.3f" % c["budget_s"], json.dumps(CELL_CONFIG), expected]
        else:
            inner = [cell_py, "-m", "gbidi3.arm_adapter", c["arm"], mp, ep, out, "%.3f" % c["budget_s"], cfg_adp if c["arm"] == "ADP_REPAIRED" else "{}", expected]
        job = RC.job_name(c)
        mem_gib = float(c.get("mem_gib", man.get("mem_gib", MEM_GIB)))                                   # frozen manifests carry MEM_GIB; qualification manifests may lower it (hard-kill control, review C4)
        cmd = [PY, "-m", "gbidi.supervise", "--ledger", ledger, "--scope", "matrix_" + stage, "--job", job, "--timeout", "%.3f" % c["budget_s"], "--mem-gib", str(mem_gib), "--cwd", HERE,
               "--stdout", os.path.join(out, "supervisor.log"), "--stderr", os.path.join(out, "supervisor.log")] + [x for k, v in THREAD_ENV.items() for x in ("--env", "%s=%s" % (k, v))] + ["--env", "PYTHONPATH=" + HERE, "--env", "GBIDI_LAUNCH_MONO=%.9f" % t, "--"] + inner
        subprocess.run(cmd, cwd=HERE); wall = time.monotonic() - t; idx = RC.ledger_index(D)
        rec = json.load(open(os.path.join(out, "cell.json"))) if os.path.exists(os.path.join(out, "cell.json")) else None
        if rec is None:                                                                            # a launched attempt without a producer record: typed NO_RECORD row bound to the manifest + receipt (review C2)
            _no_record_stub(out, c, cs)
        row = RC.reconcile(D, man, c, idx)
        print("%-3d %-26s %-20s %4ds  %-30s %-10s %7.2fs  parent+child %.2fs %s" % (c["index"], c["arm"], c["case"], int(c["budget_s"]), row.get("record_status") or "NO_RECORD", "ACCEPTED" if row["accepted"] else "NOT_ACC", row.get("delivery_from_launch_s") or 0, wall, "" if row["accepted"] else row["reasons"][:2]), flush=True)
    open(os.path.join(D, "stage_%s_finished.txt" % stage), "a").write("finished %s parent_wall_s %.3f\n" % (time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), time.monotonic() - t_stage))
    total, by, unresolved, extra = charged(D); print("stage %s done; charged total %.1f s of %.0f; unresolved %d" % (stage, total, CEILING_S, len(unresolved)))


def status(D):
    total, by, unresolved, extra = charged(D); print(json.dumps({"charged_s": round(total, 3), "by_scope": {k: round(v, 3) for k, v in by.items()}, "unresolved": [u["job"] for u in unresolved], "outer_attempts": extra["outer_attempts"], "duplicate_receipts": extra["duplicate_receipts"], "preparation_cap_s": PREPARATION_CAP_S, "ceiling_s": CEILING_S}))


if __name__ == "__main__":
    cmd = sys.argv[1]; D = os.path.abspath(sys.argv[2])
    {"propose": lambda: propose(D), "freeze": lambda: freeze(D), "run": lambda: run(D, sys.argv[3]), "status": lambda: status(D)}[cmd]()
