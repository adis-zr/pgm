"""GENERAL_BIDI_V1 broad round: freeze (414-row manifest by the EXACT procedure of empirical_plan.txt), run (every cell a charged job through the
repaired supervisor, with the stage runner itself a supervised outer job), status.
    python -m gbidi.pilot freeze D ; python -m gbidi.pilot run D STAGE ; python -m gbidi.pilot status D
Order: random.Random(20261109); stages primary_breadth / primary_depth / ablation_breadth in that order; per stage: copy the 46-case inventory in
the frozen census family order, shuffle once with the continuing generator, draw offset = randrange(len(arms)); for shuffled position i rotate the
arm list left by (i + offset) mod len(arms); append that case's cells in rotated order. Budget guard: before each launch the ledger is reconciled
(nonnested; receipts of this ledger only; stage-parent remainder measured separately) and the remaining maximum commitment of unlaunched cells +
the closeout reserve must fit under the 28,800 s ceiling."""
from __future__ import annotations
import os, sys, json, time, hashlib, random, subprocess
HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__))); sys.path.insert(0, HERE)
from adp.census import run as CR
PY = sys.executable
CEILING_S = 28800.0; CLOSEOUT_RESERVE_S = 1200.0; GRACE_S = 4.0; LAUNCH_OVERHEAD_S = 2.0; MEM_GIB = 8.0; SEED = 20261109
THREAD_ENV = {"OMP_NUM_THREADS": "1", "OPENBLAS_NUM_THREADS": "1", "MKL_NUM_THREADS": "1", "VECLIB_MAXIMUM_THREADS": "1", "NUMEXPR_NUM_THREADS": "1", "PYTHONHASHSEED": "0"}
FAMILY_ORDER = [("GridBN", ["BN_12", "BN_13", "BN_15", "BN_31"]), ("Grids", ["Grids_11", "Grids_14", "Grids_15", "Grids_17"]), ("Pedigree", ["Pedigree_11", "Pedigree_12", "Pedigree_13"]), ("Promedus", ["Promedus_33", "Promedus_14", "Promedus_12", "Promedus_37"]), ("CSP", ["CSP_12", "CSP_11", "CSP_13"]), ("DBN", ["DBN_11", "DBN_12", "DBN_15", "DBN_16"]), ("ObjectDetection", ["ObjectDetection_34", "ObjectDetection_56", "ObjectDetection_39", "ObjectDetection_24"]), ("Segmentation", ["Segmentation_11", "Segmentation_12", "Segmentation_16", "Segmentation_13"]), ("Protein", ["1qt9", "1jer", "1aie", "1npl"]), ("bnlearn", ["ASIA", "CHILD", "INSURANCE", "WATER", "MILDEW", "ALARM", "BARLEY", "HAILFINDER", "WIN95PTS", "MUNIN1", "ANDES", "DIABETES"])]
UNAVAILABLE = [("Pedigree_slot_4", "Pedigree"), ("CSP_slot_4", "CSP")]
STAGES = [("primary_breadth", ["GENERAL_BIDI_V1", "NATIVE_PLAIN_V1", "ADP_REPAIRED", "EXACT_LIBDAI"], 20.0), ("primary_depth", ["GENERAL_BIDI_V1", "NATIVE_PLAIN_V1"], 120.0), ("ablation_breadth", ["A1_NO_DEMAND_MASKS", "A2_NO_FUSION", "A3_NO_RESPONSE_VIEWS"], 20.0)]
GB_ARMS = {"GENERAL_BIDI_V1", "NATIVE_PLAIN_V1", "A1_NO_DEMAND_MASKS", "A2_NO_FUSION", "A3_NO_RESPONSE_VIEWS"}
CENSUS_D = os.path.join(HERE, "runs", "mdi_2026-10-28", "AGGREGATE_DP_CENSUS_2026-11-08")


def sha(p):
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for ch in iter(lambda: f.read(1 << 20), b""):
            h.update(ch)
    return h.hexdigest()


def ledger_path(D):
    return os.path.join(D, "GB_LEDGER.jsonl")


def charged(D):
    p = ledger_path(D); rows = [json.loads(l) for l in open(p)] if os.path.exists(p) else []
    rec = {r["jid"]: r for r in rows if r["kind"] == "RECEIPT"}; total = 0.0; unresolved = []; by = {}
    for r in rows:
        if r["kind"] != "START" or r["scope"].startswith("stage_outer"):                       # outer stage-runner receipts are kept for the parent-remainder computation, never summed with their children
            continue
        rc = rec.get(r["jid"])
        if rc is not None and not rc.get("cleanup_unresolved"):
            total += rc["wall_s"]; by[r["scope"]] = by.get(r["scope"], 0.0) + rc["wall_s"]
        elif rc is not None:
            unresolved.append(dict(r, cleanup_unresolved=True)); total += max(rc["wall_s"], r.get("max_permitted_charge_s") or 0.0)
        else:
            unresolved.append(r); total += (r.get("max_permitted_charge_s") or 0.0)
    return total, by, unresolved


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


def freeze(D):
    man_c = json.load(open(os.path.join(CENSUS_D, "CENSUS_MANIFEST.json"))); cases = {c["case"]: c for c in man_c["cases"]}
    assert sorted(cases) == sorted(inventory()), "inventory differs from the frozen census"
    br = json.load(open(os.path.join(HERE, "gbidi", "BUILD_RECORD.json"))); cfg_adp_path = os.path.join(CENSUS_D, "CONFIG_new_arm.json")
    src = sorted("gbidi/" + f for f in os.listdir(os.path.join(HERE, "gbidi")) if f.endswith((".py", ".cpp"))) + ["tests/test_gbidi.py", "adp/cell.py", "adp/checker.py", "adp/publish.py", "adp/engine.py", "adp/source.py", "adp/census/supervise.py", "adp/census/run.py", "bench/cells.py", "bench/libdai/libdai_mar", "ext/uai.py", "bidi/oracle.py"] + sorted("mdi/" + f for f in os.listdir(os.path.join(HERE, "mdi")) if f.endswith(".py"))
    fsh, _ = CR.frozen_set_hash()
    from gbidi import plan as PL, executor as EX
    man = {"pass": "GENERAL_BIDI_V1_2026-11-09", "frozen_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "commit": CR.git_head(), "branch": subprocess.check_output(["git", "rev-parse", "--abbrev-ref", "HEAD"], cwd=HERE).decode().strip(), "python": sys.version.split()[0],
           "parent_lineage": {"branched_from": "51c7df92 (bidi-native-pilot-2026-11-09 head, incl. the review repair af5c1485)", "repaired_adp_commit": "ec4ae4274d120bccc6ea41f826a124743ace9d7a", "frozen_numerical_set_code_hash": fsh, "census_supervisor_repair_commit": "9c487ad9fc4b0b9244eca157a826eeac0a641332", "native_pilot_freeze": "88afaefe", "native_pilot_review_repair": "af5c1485"},
           "source_files_sha256": {f: sha(os.path.join(HERE, f)) for f in src}, "kernel_build": br, "kernel_binary_sha256": br["binary_sha256"], "kernel_binary": br["binary"],
           "arms_config": EX.ARMS, "planner_constants": {"metadata_update_cap": PL.METADATA_UPDATE_CAP, "row_inspection_cap": PL.ROW_INSPECTION_CAP, "demand_passes": PL.DEMAND_PASSES, "block_entries": PL.BLOCK_ENTRIES, "poll_ops": PL.POLL_OPS, "two_axis_joint_max": PL.TWO_AXIS_JOINT_MAX, "caps_bytes": PL.CAPS, "discovery_wall": "min(1 s, 0.05 x budget)", "precisions": list(EX.PRECISIONS)},
           "common_rules": list(PL.COMMON_RULES), "common_rules_note": PL.COMMON_RULES_NOTE,
           "shared_vs_different": {"shared_by_all_new_arms": ["ext.uai parse + task binding", "adp.source reductions (exclude, constants, separate, alias, quotient) with the marked decoder", "gbidi/kernel.cpp native blocks (MPFR outward / binary64 nearest), category caps, deadline polling, zero-safe local reverse", "binary64 admission rule (range + depth of the actual plan)", "exact-rational enclosure through the decoder", "adp.publish dyadic grid + separate task-bound point verifier", "one-pass protocol", "exact integer reference fallback on memory stop"],
                                  "GENERAL_BIDI_V1": "3 candidate orders, exact response views, complete-consumer demand masks + zero-sibling support, consumer fusion by frozen policy", "NATIVE_PLAIN_V1": "min-volume order only, identity views, FULL demand, no fusion (memory downgrades still allowed)", "A1_NO_DEMAND_MASKS": "general minus demand masks", "A2_NO_FUSION": "general minus policy fusion", "A3_NO_RESPONSE_VIEWS": "general minus response views (identity)"},
           "config_adp_repaired_path": os.path.relpath(cfg_adp_path, HERE), "config_adp_repaired_sha256": sha(cfg_adp_path), "libdai_binary_sha256": sha(os.path.join(HERE, "bench", "libdai", "libdai_mar")), "libdai_algorithm": "JTREE[inference=SUMPROD,updates=HUGIN,maxmem=8589934592]",
           "ceiling_s": CEILING_S, "closeout_reserve_s": CLOSEOUT_RESERVE_S, "grace_s": GRACE_S, "launch_overhead_s": LAUNCH_OVERHEAD_S, "memory_budget_gib": MEM_GIB, "thread_env": THREAD_ENV, "seed": SEED, "order_procedure": "empirical_plan.txt §3 (single continuing Random(20261109); per stage shuffle + randrange offset; rotate arm list by (i+offset) mod n)",
           "query_contract": "every original singleton marginal; eps = 1/200; max width 1/100; exact dyadic-grid point; separate task-bound point verification",
           "cases": {c: {k: cases[c][k] for k in ("family", "model_path", "evidence_path", "raw_model_sha256", "raw_evidence_sha256", "canonical_model_sha256", "canonical_evidence_sha256", "variables")} for c in inventory()}, "unavailable_slots": [{"case": c, "family": f, "status": "INPUT_UNAVAILABLE"} for c, f in UNAVAILABLE], "cells": []}
    for i, c in enumerate(order()):
        cs = cases[c["case"]]; task = {"model": cs["canonical_model_sha256"], "evidence": cs["canonical_evidence_sha256"], "raw_model": cs["raw_model_sha256"], "raw_evidence": cs["raw_evidence_sha256"], "queries": "all_original_variables", "arm": c["arm"], "budget_s": c["budget_s"], "memory_gib": MEM_GIB, "grace_s": GRACE_S, "kind": c["kind"], "stage": c["stage"]}
        tid = hashlib.sha256(json.dumps(task, sort_keys=True).encode()).hexdigest()[:16]
        man["cells"].append(dict(c, index=i, task_id=tid, cell_id=hashlib.sha256((tid + "|" + man["commit"] + "|" + br["binary_sha256"]).encode()).hexdigest()[:16], out_dir="cells/%s/%03d__%s__%s__%ds__%s" % (c["stage"], i, c["case"], c["arm"], int(c["budget_s"]), tid), max_permitted_charge_s=c["budget_s"] + GRACE_S + LAUNCH_OVERHEAD_S))
    man["counts"] = {"cells": len(man["cells"]), "nominal_s": sum(c["budget_s"] for c in man["cells"]), "max_permitted_s": sum(c["max_permitted_charge_s"] for c in man["cells"]), "per_stage": {s: sum(1 for c in man["cells"] if c["stage"] == s) for s, _, _ in STAGES}}
    assert man["counts"]["cells"] == 414 and man["counts"]["nominal_s"] == 17480.0 and man["counts"]["max_permitted_s"] == 19964.0
    json.dump(man, open(os.path.join(D, "GB_MANIFEST.json"), "w"), indent=1); print(json.dumps({"cells": man["counts"], "commit": man["commit"][:12], "kernel": br["binary_sha256"][:12]}))


def reconcile_order(D):
    """independent reconstruction of the manifest order (used before launch)"""
    man = json.load(open(os.path.join(D, "GB_MANIFEST.json"))); o = order(man["seed"])
    return all((a["stage"], a["arm"], a["case"], a["budget_s"]) == (b["stage"], b["arm"], b["case"], b["budget_s"]) for a, b in zip(man["cells"], o)) and len(o) == len(man["cells"])


def run(D, stage):
    man = json.load(open(os.path.join(D, "GB_MANIFEST.json"))); head = CR.git_head()
    if subprocess.run(["git", "diff", "--quiet", man["commit"], head, "--"] + list(man["source_files_sha256"]), cwd=HERE).returncode != 0:
        raise SystemExit("a frozen source file differs between the frozen commit %s and HEAD %s" % (man["commit"], head))
    if subprocess.run(["git", "status", "--porcelain", "--"] + list(man["source_files_sha256"]), cwd=HERE, capture_output=True, text=True).stdout.strip():
        raise SystemExit("uncommitted change to a frozen source file")
    br = json.load(open(os.path.join(HERE, "gbidi", "BUILD_RECORD.json")))
    if br["binary_sha256"] != man["kernel_binary_sha256"] or sha(os.path.join(HERE, br["binary"])) != br["binary_sha256"]:
        raise SystemExit("kernel binary differs from the frozen manifest")
    if not reconcile_order(D):
        raise SystemExit("manifest order does not reconcile with the frozen procedure")
    ledger = ledger_path(D); cfg_adp = os.path.join(HERE, man["config_adp_repaired_path"]); t_stage = time.monotonic()
    open(os.path.join(D, "stage_%s_started.txt" % stage), "a").write("started %s head %s\n" % (time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), head))
    for c in man["cells"]:
        if c["stage"] != stage:
            continue
        out = os.path.join(D, c["out_dir"])
        if os.path.exists(os.path.join(out, "cell.json")) or os.path.exists(os.path.join(out, "NOT_LAUNCHED.json")):
            continue
        total, by, unresolved = charged(D); remaining_commit = sum(x["max_permitted_charge_s"] for x in man["cells"] if not os.path.exists(os.path.join(D, x["out_dir"], "cell.json")))
        if unresolved:
            json.dump({"status": "NOT_LAUNCHED_UNRESOLVED_CLEANUP", "unresolved": [u["job"] for u in unresolved]}, open(os.path.join(D, "RUN_STOPPED.json"), "w")); print("STOP: unresolved start/cleanup"); return
        if total + remaining_commit + CLOSEOUT_RESERVE_S > CEILING_S:
            os.makedirs(out, exist_ok=True); json.dump({"status": "NOT_LAUNCHED_BUDGET", "charged_s": total, "remaining_commit_s": remaining_commit, "reserve_s": CLOSEOUT_RESERVE_S, "ceiling_s": CEILING_S}, open(os.path.join(out, "NOT_LAUNCHED.json"), "w")); print("STOP: budget guard"); return
        os.makedirs(out, exist_ok=True); cs = man["cases"][c["case"]]; mp = os.path.join(HERE, cs["model_path"]); ep = os.path.join(HERE, cs["evidence_path"]); t = time.monotonic()
        if c["arm"] in GB_ARMS:
            inner = [PY, "-m", "gbidi.cell", c["arm"], mp, ep, out, "%.3f" % c["budget_s"], "{}"]
        elif c["arm"] == "ADP_REPAIRED":
            inner = [PY, "-m", "adp.cell", mp, ep, out, "%.3f" % c["budget_s"], cfg_adp]
        else:
            inner = [PY, "-m", "bench.cells", "EXACT", mp, ep, out, "%.3f" % c["budget_s"], "{}"]
        cmd = [PY, "-m", "adp.census.supervise", "--ledger", ledger, "--scope", "matrix_" + stage, "--job", "cell:%03d:%s:%s:%s:%ds" % (c["index"], stage, c["case"], c["arm"], int(c["budget_s"])), "--timeout", "%.3f" % c["budget_s"], "--mem-gib", str(MEM_GIB), "--cwd", HERE,
               "--stdout", os.path.join(out, "supervisor.log"), "--stderr", os.path.join(out, "supervisor.log")] + [x for k, v in THREAD_ENV.items() for x in ("--env", "%s=%s" % (k, v))] + ["--env", "PYTHONPATH=" + HERE, "--env", "GBIDI_LAUNCH_MONO=%.9f" % t, "--"] + inner
        subprocess.run(cmd, cwd=HERE); wall = time.monotonic() - t
        rec = json.load(open(os.path.join(out, "cell.json"))) if os.path.exists(os.path.join(out, "cell.json")) else None
        if rec is None:
            json.dump({"status": "NO_RECORD", "note": "the cell process left no cell.json (killed before writing); see supervisor.log / progress.json"}, open(os.path.join(out, "cell.json"), "w"))
        print("%-3d %-22s %-20s %4ds  %-36s %7.2fs  parent+child %.2fs" % (c["index"], c["arm"], c["case"], int(c["budget_s"]), (rec or {}).get("status", "NO_RECORD"), (rec or {}).get("complete_response_s") or 0, wall), flush=True)
    open(os.path.join(D, "stage_%s_finished.txt" % stage), "a").write("finished %s parent_wall_s %.3f\n" % (time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), time.monotonic() - t_stage))
    total, by, unresolved = charged(D); print("stage %s done; charged total %.1f s of %.0f; unresolved %d" % (stage, total, CEILING_S, len(unresolved)))


def status(D):
    total, by, unresolved = charged(D); print(json.dumps({"charged_s": round(total, 3), "by_scope": {k: round(v, 3) for k, v in by.items()}, "unresolved": [u["job"] for u in unresolved]}))


if __name__ == "__main__":
    cmd = sys.argv[1]; D = os.path.abspath(sys.argv[2])
    {"freeze": lambda: freeze(D), "run": lambda: run(D, sys.argv[3]), "status": lambda: status(D)}[cmd]()
