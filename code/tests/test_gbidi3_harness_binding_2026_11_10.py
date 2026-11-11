"""HASH-NAMESPACE CORRECTION CONTROLS (10 Nov 2026; authorized after the material stop of the first freeze at cell 10 of 414). The manifest builder's case
dictionary is now `gbidi3.pilot.normalize_case`: every TASK_BINDING_FIELD from the PRODUCER's Snapshot.task (canonical_model_sha256 / canonical_evidence_sha256
= the producer's legacy text hash), the census content hashes preserved as census_content_*, and the same dictionary feeds canonical_task on construction and
reconstruction. These controls exercise the ACTUAL census-to-manifest construction path (not a synthetic manifest assembled from producer fields), then the
real harness + the ONE strict reconciler on a tiny synthetic task whose case record goes through normalize_case, and the genuine substitution refusals.
  WA  the real build path: build_manifest(D, proposed=True) on the frozen census; every binding field of all 46 cases equals an independently loaded producer
      snapshot; the census content hashes are preserved under distinct names and differ from the legacy fields for every case (the defect that stopped the
      first freeze); the manifest reconciles and preflights (qualification copy); the OLD frozen manifest (116d7caf) fails binding for every case with
      exactly the two legacy fields (the material stop's finding, reproduced from the preserved file)
  WB  the real harness: a tiny synthetic task normalized by normalize_case from a census-like record runs through gbidi3.cell (GENERAL) and through the
      comparator adapters (ADP_REPAIRED, EXACT_LIBDAI) under the real outer supervisor and gbidi3.pilot.run; every row is ACCEPTED with FULL task binding
  WC  genuine substitutions still fail: a model byte change (TASK_MISMATCH / raw hash), an evidence change, a swapped census content hash alone (not a
      binding field: no effect on binding, recorded as provenance), a forged legacy field in the manifest (record NOT accepted), a wrong variable count
      (normalize_case refuses), a census raw hash that disagrees with the bytes (normalize_case refuses)"""
from __future__ import annotations
import sys, os, json, time, copy, shutil, subprocess, hashlib
import pytest
HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__))); sys.path.insert(0, HERE); sys.path.insert(0, os.path.join(HERE, "tests"))
sys.set_int_max_str_digits(0)
from gbidi3 import pilot as PI, reconcile as RC, source as GS, identity as ID, executor as EX, planner as PL
from bench import inventory as INV
from ext import uai as U
import test_gbidi3_complete as Q
PY = sys.executable; ENV = dict(os.environ, PYTHONPATH=HERE)
RD = os.path.join(HERE, "runs", "mdi_2026-10-28", "GENERAL_BIDI_COMPLETE_V3_2026-11-10")


def _stage(D, name):
    return subprocess.run([PY, "-m", "gbidi.supervise", "--ledger", os.path.join(D, "GB_LEDGER.jsonl"), "--scope", "stage_outer_" + name, "--job", "stage_runner:" + name, "--timeout", "600", "--cwd", HERE, "--env", "PYTHONPATH=" + HERE, "--", PY, "-m", "gbidi3.pilot", "run", D, name], capture_output=True, text=True, timeout=900, cwd=HERE, env=ENV)


# ============================================================================================================ WA  the real census-to-manifest construction path
def test_WA1_real_build_path_binds_every_field_of_all_46_cases_to_independently_loaded_producer_snapshots(tmp_path):
    man = PI.build_manifest(RD, proposed=True)                                                                                                        # the ACTUAL construction path on the frozen census inventory
    assert man["manifest_status"] == "PROPOSED_NOT_FROZEN" and len(man["cases"]) == 46 and len(man["cells"]) == 414 and PI.reconcile_manifest(man) is None
    census = {c["case"]: c for c in json.load(open(os.path.join(PI.CENSUS_D, "CENSUS_MANIFEST.json")))["cases"]}
    for case, cs in man["cases"].items():
        S = GS.Snapshot(os.path.join(HERE, cs["model_path"]), os.path.join(HERE, cs["evidence_path"]))                                                   # independent producer load
        exp = dict(cs, queries_sha256=hashlib.sha256(json.dumps(list(range(int(cs["variables"])))).encode()).hexdigest(), nvars=int(cs["variables"]), orig_card=list(cs.get("orig_card") or []), eps=cs.get("eps", "1/200"), max_width=cs.get("max_width", "1/100"), canonical_version=cs.get("canonical_version"))
        assert ID.check_task(S.task, exp, GS.TASK_BINDING_FIELDS) == [], (case, ID.check_task(S.task, exp, GS.TASK_BINDING_FIELDS))                     # every binding field, the reconciler's own comparison
        cc = census[case]; m = U.read_model(os.path.join(HERE, cs["model_path"])); ev = U.read_evidence(os.path.join(HERE, cs["evidence_path"]))
        assert cs["census_content_model_sha256"] == cc["canonical_model_sha256"] == INV.canonical_model_hash(m) and cs["census_content_evidence_sha256"] == cc["canonical_evidence_sha256"] == INV.canonical_evidence_hash(ev), case   # provenance preserved under distinct names
        assert cs["canonical_model_sha256"] != cs["census_content_model_sha256"] and cs["canonical_evidence_sha256"] != cs["census_content_evidence_sha256"], case                          # the two namespaces differ for every case (the defect was universal)
        assert cs["raw_model_sha256"] == cc["raw_model_sha256"] and cs["raw_evidence_sha256"] == cc["raw_evidence_sha256"] and int(cs["variables"]) == int(cc["variables"])
        # construction AND reconstruction use the normalized dictionary: the task id of every cell of this case reconstructs from man["cases"][case]
        for c in [x for x in man["cells"] if x["case"] == case][:2]:
            tid, cid = PI.canonical_task(cs, c, man["config_adp_repaired_sha256"], man["kernel_binary_sha256"], man["commit"]); assert (tid, cid) == (c["task_id"], c["cell_id"]) and c["out_dir"].endswith("__" + tid)
    # the preserved FIRST frozen manifest (116d7caf) fails on exactly the two legacy fields for every case: the material stop's finding, from the preserved file
    old = json.load(open(os.path.join(RD, "GB_MANIFEST_frozen_116d7caf_aborted_segment.json")))
    for case, cs in old["cases"].items():
        S = GS.Snapshot(os.path.join(HERE, cs["model_path"]), os.path.join(HERE, cs["evidence_path"]))
        exp = dict(cs, queries_sha256=hashlib.sha256(json.dumps(list(range(int(cs["variables"])))).encode()).hexdigest(), nvars=int(cs["variables"]), orig_card=list(cs.get("orig_card") or []), eps=cs.get("eps", "1/200"), max_width=cs.get("max_width", "1/100"), canonical_version=cs.get("canonical_version"))
        assert sorted(ID.check_task(S.task, exp, GS.TASK_BINDING_FIELDS)) == ["task field canonical_evidence_sha256 missing or differs", "task field canonical_model_sha256 missing or differs"], case
    # the new proposal's identities do not collide with the aborted segment's (different task ids -> different output directories and job names)
    assert not ({c["task_id"] for c in man["cells"]} & {c["task_id"] for c in old["cells"]}) and not ({c["out_dir"] for c in man["cells"]} & {c["out_dir"] for c in old["cells"]})
    assert not ({RC.job_name(c) for c in man["cells"]} & {RC.job_name(c) for c in old["cells"]})


# ============================================================================================================ WB  the real harness on a normalized synthetic case
def _census_like(case, mp, ep, nvars, family="F"):
    """a census-style case record (raw hashes + bench.inventory CONTENT hashes), as the frozen census stores it"""
    m = U.read_model(mp); ev = U.read_evidence(ep); raw = lambda p: hashlib.sha256(open(p, "rb").read()).hexdigest()
    return {"case": case, "family": family, "model_path": mp, "evidence_path": ep, "raw_model_sha256": raw(mp), "raw_evidence_sha256": raw(ep), "canonical_model_sha256": INV.canonical_model_hash(m), "canonical_evidence_hash": None, "canonical_evidence_sha256": INV.canonical_evidence_hash(ev), "variables": str(nvars), "accessible": True}


def _qual_manifest(cases, cells):
    br = json.load(open(os.path.join(HERE, "gbidi3", "BUILD_RECORD.json"))); cfg_adp = os.path.join(HERE, "runs", "mdi_2026-10-28", "AGGREGATE_DP_CENSUS_2026-11-08", "CONFIG_new_arm.json")
    src = ["gbidi3/executor.py", "gbidi3/kernel3.cpp", "gbidi3/pilot.py", "gbidi3/reconcile.py", "gbidi3/arm_adapter.py", "gbidi/supervise.py", "adp/cell.py", "bench/cells.py"]
    man = {"pass": "QUALIFICATION_HASH_NAMESPACE", "manifest_status": "FROZEN", "qualification_unfrozen": True, "frozen_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(time.time() - 2)), "commit": "unfrozen", "branch": "test", "seed": PI.SEED, "source_files_sha256": {f: EX.sha_file(os.path.join(HERE, f)) for f in src}, "kernel_binary_sha256": br["binary_sha256"], "kernel_build": br, "python_sources_sha256": ID.python_sources_sha256(), "protocol": ID.PROTOCOL,
           "config_adp_repaired_path": os.path.relpath(cfg_adp, HERE), "config_adp_repaired_sha256": EX.sha_file(cfg_adp), "common_rules": list(PL.COMMON_RULES), "arms_config": {a: dict(PL.ARMS[a], cell_config=PI.CELL_CONFIG) for a in PL.ARMS}, "ceiling_s": 28800.0, "closeout_reserve_s": 0.0, "cases": cases, "unavailable_slots": [], "cells": []}
    for i, c in enumerate(cells):
        tid, cid = PI.canonical_task(cases[c["case"]], c, man["config_adp_repaired_sha256"], br["binary_sha256"], man["commit"])
        man["cells"].append(dict(c, index=i, task_id=tid, cell_id=cid, producer_arm=c["arm"] if c["arm"] in PI.GB_ARMS else PI.PRODUCER_ARM[c["arm"]], out_dir="cells/%s/%03d__%s__%s__%ds__%s" % (c["stage"], i, c["case"], c["arm"], int(c["budget_s"]), tid), max_permitted_charge_s=c["budget_s"] + 6.0))
    assert PI.reconcile_manifest(man) is None; return man


def test_WB1_tiny_synthetic_task_through_a_new_arm_and_both_comparator_adapters_is_accepted_with_full_binding(tmp_path):
    from gbidi3_closeout import report as R
    D = str(tmp_path / "run"); os.makedirs(D); inputs = tmp_path / "inputs"; inputs.mkdir()
    card = [2, 3, 2]; facs = Q.rnd_model(12, card, [(0, 1), (1, 2), (0, 2)]); dec = lambda q: "%d.%02d" % divmod(q.numerator * (100 // q.denominator), 100)
    mp, ep = Q.write_uai(str(inputs / "X.uai"), card, facs, {2: 1}, tokens=[[dec(x) for x in tab] for _, tab in facs]); S, Z, N, rows = Q.truth(mp, ep)
    cc = _census_like("X", mp, ep, 3); case = PI.normalize_case(cc, GS.Snapshot(mp, ep))                                                              # the corrected normalization, from a CENSUS-style record
    assert case["canonical_model_sha256"] == GS.canonical_legacy(open(mp, "rb").read()) != case["census_content_model_sha256"] == cc["canonical_model_sha256"]
    cells = [{"stage": "primary_breadth", "arm": a, "case": "X", "budget_s": 20.0, "kind": "primary"} for a in ("GENERAL_BIDI_COMPLETE_V3", "ADP_REPAIRED", "EXACT_LIBDAI")]
    man = _qual_manifest({"X": case}, cells); json.dump(man, open(os.path.join(D, "GB_MANIFEST.json"), "w"))
    r1 = _stage(D, "primary_breadth"); assert "STOP" not in r1.stdout, r1.stdout[-800:] + r1.stderr[-800:]
    rws = {r["arm"]: r for r in R.cells_ledger(D, man)}
    assert all(r["accepted"] for r in rws.values()), [(a, r["reasons"]) for a, r in rws.items() if not r["accepted"]]
    assert rws["GENERAL_BIDI_COMPLETE_V3"]["status"] == "CERTIFIED" and rws["GENERAL_BIDI_COMPLETE_V3"]["task_binding"] == "FULL" and rws["GENERAL_BIDI_COMPLETE_V3"]["delivered_valid_output"]
    assert rws["ADP_REPAIRED"]["status"] in ("CERTIFIED",) and rws["EXACT_LIBDAI"]["status"] in ("COMPLETE",), {a: r["status"] for a, r in rws.items()}
    od = os.path.join(D, rws["GENERAL_BIDI_COMPLETE_V3"]["out_dir"]); g = json.load(open(os.path.join(od, "cell.json"))); chk = json.load(open(os.path.join(od, "checked_record.json")))
    assert g["task"]["canonical_model_sha256"] == case["canonical_model_sha256"] and Q.contained(chk, rows)                                           # the cell record binds the producer's legacy field; the production-config (binary64-admitted) checked record ENCLOSES the exact rows
    # ---- WC-style genuine substitutions on COPIES of this run (the record / manifest / bytes are the real ones)
    def variant(name, mutate_manifest=None, mutate_files=None):
        dest = str(tmp_path / name); shutil.copytree(D, dest); m2 = json.load(open(os.path.join(dest, "GB_MANIFEST.json")))
        if mutate_manifest:
            mutate_manifest(m2)
        json.dump(m2, open(os.path.join(dest, "GB_MANIFEST.json"), "w")); return dest, m2
    # (a) a forged legacy field in the manifest -> every record NOT accepted on exactly that field
    dest, m2 = variant("forged_legacy", lambda m: m["cases"]["X"].__setitem__("canonical_model_sha256", "0" * 64))
    rr = R.cells_ledger(dest, m2); assert all(not r["accepted"] and "task field canonical_model_sha256 missing or differs" in r["reasons"] for r in rr), [r["reasons"] for r in rr]
    # (b) a swapped CENSUS content hash alone is provenance, not a binding field: rows stay accepted (and the task id does not change: content hashes are not in canonical_task)
    dest, m2 = variant("swapped_content", lambda m: m["cases"]["X"].__setitem__("census_content_model_sha256", "f" * 64))
    rr = R.cells_ledger(dest, m2); assert all(r["accepted"] for r in rr), [r["reasons"] for r in rr]
    assert PI.canonical_task(m2["cases"]["X"], m2["cells"][0], m2["config_adp_repaired_sha256"], m2["kernel_binary_sha256"], m2["commit"])[0] == m2["cells"][0]["task_id"]
    # (c) a changed model byte at the frozen path: the runner's pre-launch TASK_MISMATCH guard (inputs_match) and the record's raw hash both refuse
    mp2 = str(inputs / "X2.uai"); open(mp2, "w").write(open(mp).read().replace("\n", " \n", 1)); assert hashlib.sha256(open(mp2, "rb").read()).hexdigest() != case["raw_model_sha256"]
    m3 = copy.deepcopy(man); m3["cases"]["X"]["model_path"] = mp2; assert not PI.inputs_match(m3, "X")
    bad = GS.Snapshot(mp2, ep).task; assert "task field raw_model_sha256 missing or differs" in ID.check_task(bad, dict(case, nvars=3), GS.TASK_BINDING_FIELDS) and bad["canonical_model_sha256"] == case["canonical_model_sha256"]   # whitespace-only change: legacy hash equal, raw differs -> still refused
    # (d) a changed evidence file (different observation): raw AND canonical fields differ
    ep2 = str(inputs / "X2.uai.evid"); open(ep2, "w").write("1 2 0\n"); bad = GS.Snapshot(mp, ep2).task
    assert {"task field raw_evidence_sha256 missing or differs", "task field canonical_evidence_sha256 missing or differs", "task field canonical_v2_evidence_sha256 missing or differs"} <= set(ID.check_task(bad, dict(case, nvars=3), GS.TASK_BINDING_FIELDS))
    # (e) normalize_case refuses a census record whose raw hash or variable count disagrees with the bytes
    with pytest.raises(SystemExit):
        PI.normalize_case(dict(cc, raw_model_sha256="0" * 64), GS.Snapshot(mp, ep))
    with pytest.raises(SystemExit):
        PI.normalize_case(dict(cc, variables="4"), GS.Snapshot(mp, ep))


def test_WB2_aborted_segment_is_labelled_and_excluded_and_the_inventory_names_this_module():
    lab = json.load(open(os.path.join(RD, "ABORTED_SEGMENT_116d7caf.json"))); assert lab["status"] == "ABORTED_BENCHMARK_SEGMENT_WITH_NUMERICAL_EXPOSURE" and len(lab["cells"]) == 10 and all(os.path.exists(os.path.join(RD, c["out_dir"], "cell.json")) for c in lab["cells"])
    assert os.path.exists(os.path.join(RD, "GB_MANIFEST_frozen_116d7caf_aborted_segment.json")) and os.path.exists(os.path.join(RD, "RUN_STOPPED_aborted_segment_116d7caf.json"))
    from gbidi3_closeout import package as PK
    assert "tests/test_gbidi3_harness_binding_2026_11_10.py" in PK.TEST_FILES_DEFAULT and "gbidi3_harness_binding_final" in open(os.path.join(HERE, "gbidi3_closeout", "ready_for_review.py")).read()
