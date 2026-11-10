"""Closeout generator at the READY_FOR_REVIEW stop point (brief §23). Reads only immutable records (ledger receipts, pytest outputs, inspection, proposed
manifest, repair directories) and writes: REQUIREMENTS.json/.md (rows advanced with evidence), QUALIFICATION_MANIFEST.json, BUDGET_LEDGER.json,
CODE_LINEAGE.json, REFERENCE_SNAPSHOT.json, INSPECTION_SCHEMA.json, NOT_IMPLEMENTED.json, AMENDMENTS.json, PROTECTED_SETS_SHA256_AFTER.txt + diff.
    python -m gbidi3_closeout.ready_for_review RUN_DIR"""
from __future__ import annotations
import os, sys, json, time, hashlib, subprocess, re, collections
HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__))); sys.path.insert(0, HERE)
from gbidi3 import requirements as RQ, pilot as PI, planner as PL, memory as GM, clock as GC, executor as EX


def sha(p):
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for ch in iter(lambda: f.read(1 << 20), b""):
            h.update(ch)
    return h.hexdigest()


def git(*a):
    return subprocess.check_output(["git"] + list(a), cwd=HERE, text=True).strip()


def receipts(D):
    rows = [json.loads(l) for l in open(os.path.join(D, "GB_LEDGER.jsonl"))]
    return [r for r in rows if r["kind"] == "RECEIPT"], [r for r in rows if r["kind"] == "START"]


def pytest_summary(path):
    txt = open(path).read() if os.path.exists(path) else ""
    m = re.search(r"(\d+) passed", txt); f = re.search(r"(\d+) failed", txt)
    return {"file": os.path.relpath(path, HERE), "passed": int(m.group(1)) if m else 0, "failed": int(f.group(1)) if f else 0, "summary_line": txt.strip().splitlines()[-1] if txt.strip() else None}


def main(D):
    D = os.path.abspath(D); rel = lambda p: os.path.relpath(p, HERE); q = os.path.join(D, "qualification"); rc, st = receipts(D)
    # ---------------------------------------------------------------- qualification manifest (every test attempt, pass/fail counts, receipts)
    attempts = []
    for r in rc:
        if r["job"].startswith("pytest:"):
            name = r["job"].split(":", 1)[1]; out = os.path.join(q, "pytest_" + name + ".txt")
            if not os.path.exists(out):
                out = os.path.join(q, ("pytest_" + name.replace("gbidi3_", "") + ".txt") if not name.startswith("existing") else ("pytest_" + name + ".txt"))
            if name.startswith("repair2_"):
                out = os.path.join(D, "repairs", "r2_suite", name.replace("repair2_controls_", "repair2_").replace("repair2_suites_", "suites_") + ".out") if not os.path.exists(out) else out
            elif name.startswith("repair_"):
                out = os.path.join(D, "repairs", "r1_suite", {"repair_A_1": "pytest_repair_A_1.txt"}.get(name, name.replace("repair_DE_planner_kernel_", "suite_").replace("repair_controls_", "repair_") + ".out"))
                out = out if os.path.exists(out) else os.path.join(q, "pytest_" + name + ".txt")
            cand = [f for f in os.listdir(q) if f.endswith(".txt") and name.replace("gbidi3_", "") in f] if not os.path.exists(out) else [os.path.basename(out)]
            s = pytest_summary(os.path.join(q, cand[0])) if cand else {"file": None, "passed": None, "failed": None}
            attempts.append({"job": r["job"], "jid": r["jid"], "wall_s": r["wall_s"], "outcome": r["outcome"], "returncode": r["returncode"], **s})
    def last(job):
        c = [a for a in attempts if a["job"] == job]; return c[-1] if c else {"job": job, "outcome": "MISSING", "passed": None, "failed": None}
    def latest_final(prefix):
        """the final run of a suite family = the pytest job with the greatest attempt number among pytest:<prefix>_<N> (unique stdout per attempt, review G4)"""
        c = sorted([a for a in attempts if a["job"].startswith("pytest:" + prefix + "_") and a["job"].rsplit("_", 1)[-1].isdigit()], key=lambda a: int(a["job"].rsplit("_", 1)[-1]))
        return c[-1] if c else {"job": "pytest:" + prefix + "_?", "outcome": "MISSING", "passed": None, "failed": None, "file": None}
    final_v3 = latest_final("gbidi3_full_final"); final_rep = latest_final("gbidi3_repair_controls_final"); final_rep2 = latest_final("gbidi3_repair2_controls_final"); final_rep3 = latest_final("gbidi3_repair3_controls_final"); final_reg = latest_final("existing_regressions_final")
    superseded = {"v3_controls_before_the_first_review_repair": last("pytest:gbidi3_full_attempt7"), "existing_regressions_before_the_first_review_repair": last("pytest:existing_regressions_1"), "first_repair_final_runs": {"v3": last("pytest:gbidi3_full_repair_final2"), "repair_controls": last("pytest:gbidi3_repair_controls_final2"), "regressions": last("pytest:existing_regressions_repair_final2")}}
    collect = open(os.path.join(q, "pytest_collect_only.txt")).read()
    counts = collections.Counter(l.split("::")[0] for l in collect.splitlines() if "::" in l)
    man = {"utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "suite_v3": "tests/test_gbidi3_complete.py", "suite_v3_def_count": sum(1 for l in open(os.path.join(HERE, "tests/test_gbidi3_complete.py")) if l.startswith("def test_")), "collected_by_file": dict(counts),
           "final_runs": {"v3_controls": final_v3, "repair_controls": final_rep, "repair2_controls": final_rep2, "repair3_controls": final_rep3, "existing_regressions": final_reg}, "superseded_runs": superseded, "suites": ["tests/test_gbidi3_complete.py (126; disclosed fixture changes: C04, C07, C22, deterministic seeds, C17 / C22 plan-side root streaming)", "tests/test_gbidi3_repair_2026_11_10.py (25 first-review repair controls RA-RF; exact-jet helper corrected after the second review)", "tests/test_gbidi3_repair2_2026_11_10.py (25 second-review repair controls SA-SF)", "tests/test_gbidi3_repair3_2026_11_10.py (third-review repair controls TA-TG)"], "every_pytest_attempt": attempts, "skips": "none (no skip markers; architecture-dependent controls run on this arm64 macOS host: rounding-mode flag 0x400000, guard-malloc not required)",
           "import_dependencies": {"tests/test_gbidi3_complete.py": ["gbidi3.*", "adp.source (pinned reductions)", "adp.publish / adp.checker (pinned publication + point verifier)", "ext.uai (pinned dataclasses / MAR reader)", "gbidi.supervise (unchanged V2 supervisor)", "bench.cells EXACT + adp.cell producers through gbidi3.arm_adapter (C24 end-to-end)"]},
           "fixtures_and_oracle": {"oracle": "gbidi3/oracle.py (brute force over ORIGINAL factors; shares only the parser)", "fixtures": "inline in tests/test_gbidi3_complete.py (write_uai / rnd_model / star_model / chain_exact / _c16_model / _shared_consumer_program / _c15_program)"},
           "repairs_during_qualification": {"K1": rel(os.path.join(D, "repairs/K1_combined_frame")), "K2": rel(os.path.join(D, "repairs/K2_load_values_teardown")), "review_repair_2026-11-10": rel(os.path.join(D, "repairs/r1_suite")), "review_reproductions_unchanged_source": rel(os.path.join(D, "review_repro_r1"))},
           "note": "every pytest attempt (including the failing fixture-development attempts and the repair-stage attempts of both reviews) is retained with its receipt; a count alone is not qualification: the control bodies assert the named mechanism / transition fired. DISCLOSED (first repair): the stdout files of the FIRST final rerun (jobs *_repair_final; receipts in GB_LEDGER.jsonl: 126 / 25 / 236 passed) were overwritten by the second rerun (*_repair_final2) because of a shell-script path slip. Since the second repair every attempt writes pytest_<job>_<attempt>.txt (unique path, never overwritten; review G4) and the final run of each suite family is the greatest attempt number."}
    json.dump(man, open(os.path.join(D, "QUALIFICATION_MANIFEST.json"), "w"), indent=1)
    # ---------------------------------------------------------------- requirements matrix: EVERY row qualified INDIVIDUALLY from its own passing evidence (review F1: no bulk promotion)
    # evidence = test node ids (prefix match against the PASSED lines of the FINAL -rA outputs) + record files; a row is QUALIFIED only if every listed test passed in the final
    # run of its suite AND that suite's job receipt is COMPLETED / rc 0; otherwise it is IMPLEMENTED_UNQUALIFIED with the missing evidence named. The regression suite is one block.
    T = "tests/test_gbidi3_complete.py"; T2 = "tests/test_gbidi3_repair_2026_11_10.py"; T3 = "tests/test_gbidi3_repair2_2026_11_10.py"; T4 = "tests/test_gbidi3_repair3_2026_11_10.py"
    F = os.path.join(HERE, final_v3["file"]) if final_v3.get("file") else os.path.join(q, "missing"); F2 = os.path.join(HERE, final_rep["file"]) if final_rep.get("file") else os.path.join(q, "missing"); F3 = os.path.join(HERE, final_rep2["file"]) if final_rep2.get("file") else os.path.join(q, "missing"); F4 = os.path.join(HERE, final_rep3["file"]) if final_rep3.get("file") else os.path.join(q, "missing"); R = os.path.join(HERE, final_reg["file"]) if final_reg.get("file") else os.path.join(q, "missing")
    passed = set()
    for f in (F, F2, F3, F4):
        if os.path.exists(f):
            passed |= {l.split(" ", 1)[1].strip() for l in open(f) if l.startswith("PASSED ")}
    reg_ok = pytest_summary(R)["failed"] == 0 and pytest_summary(R)["passed"] >= 236
    receipts_ok = {a["job"]: (a["outcome"] == "COMPLETED" and a["returncode"] == 0 and (a["failed"] or 0) == 0 and (a["passed"] or 0) > 0) for a in attempts}
    suites_ok = all(receipts_ok.get(j["job"]) for j in (final_v3, final_rep, final_rep2, final_rep3, final_reg))
    REG = "tests/test_gbidi_v2.py + test_bidi_pilot.py + test_adp_v1.py + test_adp_census.py + test_adp_census_correction.py (236, one block)"
    ev = {"M01": [T + "::test_every_arm_encloses_exact_truth_on_every_input_class", T + "::test_malformed_models_are_typed_invalid_input_through_the_caller_pipeline", T + "::test_malformed_evidence_is_typed_invalid_input", T + "::test_valid_edge_grammar_scalars_duplicates_and_identity_fields", T + "::test_C06", T + "::test_C07", T + "::test_C10", T + "::test_C12", T + "::test_C21", T2 + "::test_RE1", T4 + "::test_TD1"],
          "M02": [T + "::test_C20", T + "::test_C12", T2 + "::test_RA1", T2 + "::test_RA2", T2 + "::test_RA3", T2 + "::test_RB1", T3 + "::test_SA1", T3 + "::test_SA2", T3 + "::test_SA3", T3 + "::test_SA4", T3 + "::test_SA5"],
          "M03": [T + "::test_C23", T2 + "::test_RE2", T3 + "::test_SE4"],
          "M04": [T + "::test_C03", T + "::test_C04", T + "::test_C13", T2 + "::test_RF1", T2 + "::test_RF5", T3 + "::test_SD1", T3 + "::test_SD2", T4 + "::test_TC1"],
          "M05": [T + "::test_every_arm_encloses_exact_truth_on_every_input_class", T + "::test_C14", T2 + "::test_RF1", T2 + "::test_RF2", T2 + "::test_RF3", T3 + "::test_SD1"],
          "M06": [T + "::test_C01", T + "::test_C04", T + "::test_C05", T + "::test_C07", T2 + "::test_RF2", T2 + "::test_RA1_five_witnesses_reject_and_their_legal_counterparts_certify[marked_axis_compression]", T2 + "::test_RA1_five_witnesses_reject_and_their_legal_counterparts_certify[forged_identity_gather_scale]", T3 + "::test_SA1", T3 + "::test_SA2", T3 + "::test_SB3", T4 + "::test_TF1", T4 + "::test_TB1"],
          "M07": [T + "::test_C17"],
          "M08": [T + "::test_C17", T + "::test_C07", T + "::test_C13", T2 + "::test_RD2", T2 + "::test_RE4", T3 + "::test_SC1", T3 + "::test_SE2", T4 + "::test_TA1", T4 + "::test_TA2"],
          "M09": [T + "::test_C18", T + "::test_C06", T3 + "::test_SB1"],
          "M10": [T + "::test_C16", T + "::test_C25", T2 + "::test_RF4", T3 + "::test_SB4"],
          "M11": [T + "::test_C16", T2 + "::test_RF4", T3 + "::test_SB3", T3 + "::test_SB4"],
          "M12": [T + "::test_C03", T + "::test_C09", T + "::test_C15", T2 + "::test_RF5", T3 + "::test_SC1", T3 + "::test_SD1", T4 + "::test_TA1"],
          "M13": [T + "::test_C09", T + "::test_C15", T + "::test_C18", T + "::test_C22", T3 + "::test_SC1", T4 + "::test_TA1", T4 + "::test_TA2"],
          "M14": [T + "::test_every_execution_mode_matches_the_oracle_rows_exactly_when_run_through_the_exact_fallback", T + "::test_C11", T + "::test_C25", T + "::test_C22", T2 + "::test_RE2", T3 + "::test_SE1"],
          "M15": [T + "::test_C11", T + "::test_C19"],
          "M16": [T + "::test_C19"],
          "M17": [T + "::test_C21", T + "::test_C12", T2 + "::test_RB1", T2 + "::test_RB2"],
          "M18": [T + "::test_C22", T + "::test_C17", T2 + "::test_RE1", T2 + "::test_RE2", T2 + "::test_RE3", T2 + "::test_RE4", T3 + "::test_SE1", T3 + "::test_SE2", T3 + "::test_SD2", T4 + "::test_TC1", T4 + "::test_TD1", T4 + "::test_TA2"],
          "M19": [T + "::test_C23", T + "::test_C22", T2 + "::test_RB2", T2 + "::test_RE1", T2 + "::test_RE2", T2 + "::test_RE3", T3 + "::test_SE3", T3 + "::test_SE4", T4 + "::test_TC1", T4 + "::test_TD1"],
          "M20": [T + "::test_C24_supervisor_completion_means_the_owned_group_is_empty", T + "::test_C24_nested_supervisors_owned_tree_is_reconciled", T3 + "::test_SF1", T4 + "::test_TE1", REG],
          "M21": [T + "::test_C24_manifest_reconciler_and_accounting", T + "::test_C24_all_seven_arms_end_to_end_through_the_real_harness_resume_and_closeout", T2 + "::test_RC1", T3 + "::test_SF1", T3 + "::test_SF2", T4 + "::test_TE1", T4 + "::test_TE2"],
          "M22": [T + "::test_C24_manifest_reconciler_and_accounting", rel(os.path.join(D, "GB_MANIFEST_PROPOSED.json")), rel(os.path.join(D, "PANEL_INSPECTION.json"))],
          "M23": [T + "::test_C14", T + "::test_C16", T2 + "::test_RD1", T2 + "::test_RD3", T3 + "::test_SB1", T3 + "::test_SB2", T3 + "::test_SB3", T3 + "::test_SB4", T4 + "::test_TB1", T4 + "::test_TB2", T4 + "::test_TB3", rel(os.path.join(D, "PANEL_INSPECTION.json"))],
          "M24": [T + "::test_C01", T + "::test_C02", T + "::test_C05", T + "::test_C10", T + "::test_C14", T + "::test_C20", T2 + "::test_RA1", T2 + "::test_RA2", T2 + "::test_RA3", T3 + "::test_SA1", T3 + "::test_SA2", T3 + "::test_SA5", T4 + "::test_TF1"],
          "M25": [T + "::test_C07", T + "::test_C11", T + "::test_C21", T2 + "::test_RC1"]}
    verdicts = {}
    THIRD_REVIEW_ROWS = {"M01", "M04", "M06", "M08", "M12", "M13", "M18", "M19", "M20", "M21", "M23", "M24"}       # rows touched by the third review's findings (sparse reverse, cost model, demand, numerals, ownership, proof scope)
    st_now = RQ._load_state(D)
    for rid in ev:                                                                              # review F1: the pre-review bulk promotion is WITHDRAWN explicitly (once) before any row is re-qualified from its own evidence
        hist = (st_now.get(rid) or {}).get("history", [])
        if not any("bulk promotion withdrawn" in (h.get("note") or "") for h in hist) and any("gbidi3_full_attempt7" in (h.get("note") or "") for h in hist):
            RQ.update(D, rid, "IMPLEMENTED_UNQUALIFIED", note="review 2026-11-10 (R7): bulk promotion withdrawn; the row must be re-qualified individually from its own passing controls on the repaired code")
        if not any("second review" in (h.get("note") or "") for h in hist) and any("individually qualified" in (h.get("note") or "") for h in hist):
            RQ.update(D, rid, "IMPLEMENTED_UNQUALIFIED", note="second review 2026-11-10 (F1-F6 / G4): qualification WITHDRAWN on the affected rows until the repaired composed-path controls pass on the target build")
        if rid in THIRD_REVIEW_ROWS and not any("third review" in (h.get("note") or "") for h in hist) and any("individually qualified" in (h.get("note") or "") for h in hist):
            RQ.update(D, rid, "IMPLEMENTED_UNQUALIFIED", note="third review 2026-11-10 (A-G): qualification WITHDRAWN on this affected row until the composition controls (deep sparse / schedule-aware cost / demand allocation / numerals / ownership) pass; unaffected rows retain their status")
    for rid, paths in ev.items():
        missing = []
        for e in paths:
            if e.startswith("tests/") and "::" in e:
                if not any(x == e or x.startswith(e + "[") or x.startswith(e + "_") for x in passed):
                    missing.append(e)
            elif e == REG:
                if not reg_ok:
                    missing.append(e)
            elif not os.path.exists(os.path.join(HERE, e)):
                missing.append(e)
        ok = suites_ok and not missing
        RQ.update(D, rid, "QUALIFIED" if ok else "IMPLEMENTED_UNQUALIFIED", evidence=paths + [rel(F), rel(F2), rel(F3), rel(F4), rel(R)], note=("individually qualified: every listed control PASSED in the final runs (%s / %s / %s / %s / %s)" % tuple(pytest_summary(x)["summary_line"] for x in (F, F2, F3, F4, R))) if ok else ("NOT qualified: missing evidence %s" % missing[:4]))
        verdicts[rid] = {"qualified": ok, "missing": missing}
    doc = RQ.write(D); json.dump({"rule": "per-row: every listed test node PASSED in the final -rA outputs and every final suite receipt COMPLETED rc 0; otherwise IMPLEMENTED_UNQUALIFIED", "passed_nodes": len(passed), "suites_ok": suites_ok, "regressions_ok": reg_ok, "verdicts": verdicts}, open(os.path.join(D, "REQUIREMENTS_EVIDENCE_CHECK.json"), "w"), indent=1)
    # ---------------------------------------------------------------- budget ledger (one authoritative total; every START reconciled)
    total, by, unresolved, extra = PI.charged(D)
    # this closeout job runs UNDER the supervisor: its own START has no receipt yet, so PI.charged counts it at its maximum permitted charge (the as-of artefact the review
    # called out in R9). Report the receipted total separately and exactly; the final total = receipted total + this job's receipt wall (lands in GB_LEDGER.jsonl right after this
    # file is written) + the packaging job's wall (its receipt is the outside-archive sidecar).
    self_jid = os.environ.get("GBIDI_PARENT_JID"); live_self = [u for u in unresolved if u.get("jid") == self_jid]; other_unresolved = [u for u in unresolved if u.get("jid") != self_jid]
    receipted_total = total - sum((u.get("max_permitted_charge_s") or 0.0) for u in live_self)
    all_receipts = [r for r in rc]; raw_sum = sum(r["wall_s"] for r in all_receipts if isinstance(r.get("wall_s"), (int, float)) and not isinstance(r.get("wall_s"), bool))
    budget = {"envelope_s": PI.CEILING_S, "preparation_cap_s": PI.PREPARATION_CAP_S, "receipted_total_s": receipted_total, "measured_s": extra.get("measured_s"), "envelope_charges_s": extra.get("envelope_s"), "unknown_wall_receipts": extra.get("unknown_wall_receipts"), "raw_receipt_sum_s_all_receipts": raw_sum, "receipts_in_ledger": len(all_receipts), "live_closeout_job": [{"job": u.get("job"), "jid": u.get("jid"), "note": "receipt pending while this file is written; its wall is the next RECEIPT in GB_LEDGER.jsonl"} for u in live_self],
              "final_total_rule": "receipted_total_s + this closeout job's receipt wall + the packaging job's receipt wall (sidecar next to the archive); recomputable from GB_LEDGER.jsonl alone", "rule": "nonnested: children + measured nonnegative parent-only remainder (gbidi3.pilot.charged); every START reconciled to exactly one RECEIPT", "total_charged_s": total, "by_scope": by, "receipts": len(rc), "starts": len(st), "unresolved": [u.get("job") for u in unresolved], "duplicate_receipts": extra["duplicate_receipts"],
              "remaining_preparation_s": PI.PREPARATION_CAP_S - total, "remaining_envelope_s": PI.CEILING_S - total, "reservations_proposed_s": {"matrix_414_plus_launch_cleanup": PI.MATRIX_RESERVE_S, "inspection_analysis": PI.INSPECTION_RESERVE_S, "closeout_packaging": PI.CLOSEOUT_RESERVE_S, "contingency": PI.CONTINGENCY_S},
              "compliance": ("EXACT over receipted jobs: every other START has exactly one RECEIPT, no unresolved cleanup, no duplicate receipts; the only receipt pending is this closeout job's own" if not other_unresolved and not extra["duplicate_receipts"] else "QUALIFIED: unresolved %s / duplicates %s" % ([u.get("job") for u in other_unresolved], extra["duplicate_receipts"])),
              "total_charged_s_incl_live_closeout_at_max_permitted": total,
              "exposure_not_in_this_ledger": "human / agent reasoning and text editing (not job wall, per the brief); ad-hoc interpreter probes run WITHOUT the supervisor: UNKNOWN exposure of the class recorded in E-MDI-38 -- NOT an upper bound, nothing was measured. Implementation stage (before the review): planner debugging / kernel probe / fixture probes, recollection only. Review-repair stage (10 Nov): patch-application python3 scripts (text editing, no inference) plus a handful of uncharged one-line interpreter checks (import-closure listing, requirement-symbol resolution, one two-axis plan probe of about 1 s); every executing probe, build and test run of the repair stage is a supervised receipt in this ledger (scopes review_repro / preparation / qualification / closeout). The pre-review snapshot BUDGET_LEDGER_asof_2026-11-10T07_13Z_snapshot.json is labelled as-of and retained unchanged.",
              "historical_ledgers": "untouched: GENERAL_BIDI_V1 (10,506.4 s raw receipts, one unreceipted START), GENERAL_BIDI_V2 (332.773 s), BIDI pilot, ADP, census; this ledger is NEW and separate (brief §22)", "packaging_receipt": "sidecar next to the archive (its wall finishes after the archive is built)"}
    json.dump(budget, open(os.path.join(D, "BUDGET_LEDGER.json"), "w"), indent=1)
    # ---------------------------------------------------------------- code lineage
    files = sorted(set(PI.source_set() + ["gbidi3_closeout/" + f for f in os.listdir(os.path.join(HERE, "gbidi3_closeout")) if f.endswith(".py")] + ["gbidi3/libgbidi3_kernel.dylib", "gbidi3/BUILD_RECORD.json"]))
    prev_lin = os.path.join(D, "CODE_LINEAGE.json")
    if os.path.exists(prev_lin):
        try:
            pl = json.load(open(prev_lin)); asof = os.path.join(D, "CODE_LINEAGE_asof_%s_snapshot.json" % (pl.get("head_before_closeout_commit", "unknown")[:12]))
            if not os.path.exists(asof):
                os.replace(prev_lin, asof)                                                       # the previous lineage is kept as an as-of snapshot (review G2); the new record is computed from the CURRENT files
        except Exception:
            pass
    lineage = {"branch": git("rev-parse", "--abbrev-ref", "HEAD"), "head_before_closeout_commit": git("rev-parse", "HEAD"), "note": "computed from the files as they are at this closeout run (after the last source edit); a later edit of any listed file makes this record stale -- the packager re-checks every listed hash at packaging time (PACKAGE_RECORD.lineage_check)", "parent_v2_closeout": "88a3e325e159b92eb6655ef31dd5bba9f9e1e58c", "parent_v2_package_record": "16c79e67eae569d4e998d51333aaabfe442e6853", "parent_prose_handoff_commit": "faa88a2ec96500e8eeb7ce9b0e59ee628afbb270",
               "repaired_adp": {"commit": "ec4ae4274d120bccc6ea41f826a124743ace9d7a", "package_record_commit": "3a0648fbf47f3c80051c001c7c681644a12d122c", "code_hash_expected": "da5b2c49b1bd34d181fa1a18f123304d1cfb4f651a995c5f82081dff05500404", "code_hash_now": __import__("adp.census.run", fromlist=["x"]).frozen_set_hash()[0]},
               "v2_closeout_archive": {"path": "/Users/adis/Workspace/GENERAL_BIDI_V2_CLOSEOUT_REVIEW_2026-11-10.zip", "sha256": "407b1b2f601af3d1f7661f2220febd5dd437304d359cf749d240a7c7cd51dfba", "bytes": 2318210, "members": 616, "verified_by": rel(os.path.join(D, "preparation/verify_closeout_archive.out"))},
               "brief": {"path": "~/Downloads/GENERAL_BIDI_COMPLETE_IMPLEMENTATION_SPEC.txt", "sha256": "af2e29bf13c2527bb9db55e9b321ad7aaf73766827b8177d0aa26ba12d12ef20", "bytes": 104238, "words": 13707},
               "files_sha256": {f: sha(os.path.join(HERE, f)) for f in files if os.path.exists(os.path.join(HERE, f))}, "kernel_build": json.load(open(os.path.join(HERE, "gbidi3/BUILD_RECORD.json"))),
               "toolchain": open(os.path.join(D, "preparation/probe_toolchain.out")).read(), "imported_local_modules": ["adp.source (reductions, pinned)", "adp.publish (grid publication, pinned)", "adp.checker (SourceReplay + verify_point_mode, pinned)", "adp.census.run (git_head, frozen_set_hash)", "ext.uai (dataclasses, MAR reader, pinned)", "gbidi.supervise (V2 supervisor, unchanged)", "bench.cells / adp.cell (comparator producers, pinned, through gbidi3.arm_adapter)"],
               "third_party": "Python 3.12.15, gmpy2 2.3.2 (GMP 6.3.0, MPFR 4.2.2), numpy 2.3.3, psutil 7.2.2, pytest 9.1.1, Apple clang 15.0.0 (clang-1500.0.40.1), macOS 26.6.2 arm64"}
    json.dump(lineage, open(os.path.join(D, "CODE_LINEAGE.json"), "w"), indent=1)
    # ---------------------------------------------------------------- reference snapshot (frozen BEFORE scoring, from the accepted ADP record)
    sc = os.path.join(HERE, "runs/mdi_2026-10-28/AGGREGATE_DP_2026-11-07/SCORES.json"); S = json.load(open(sc)); cls = S["reference_classes"]
    refsnap = {"frozen_source": rel(sc), "sha256": sha(sc), "reference_class_counts": S.get("reference_class_counts"), "per_case": {c: {"class": v["class"], "source": v.get("source"), "independence": v.get("independence")} for c, v in cls.items()},
               "rule": "R0 exact truth; R1 / R2 numerical POINTS with provenance (libDAI JTREE 10 digits / UAI-2014 solution files 6 digits / Merlin exact-by-ibound); R3 no accepted point; distance to R1/R2 is a diagnostic, not containment truth; new outputs are never promoted into a tier", "frozen_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}
    json.dump(refsnap, open(os.path.join(D, "REFERENCE_SNAPSHOT.json"), "w"), indent=1)
    # ---------------------------------------------------------------- inspection schema, NOT_IMPLEMENTED, amendments
    from gbidi3 import inspect_panel as IP
    json.dump({"fields": IP.FIELDS, "statuses": ["PLANNED", "PLAN_STOP (typed: ROW_CAP / DISCOVERY_WALL / METADATA_CAP / NOT_REPRESENTABLE)", "PLAN_REJECTED", "RESOURCE_STOP", "ZERO_EVIDENCE_PROVED", "EXACT_DECODER", "SCALAR_TASK", "INVALID_INPUT", "INPUT_UNAVAILABLE"], "missingness": "a capped inspection is UNKNOWN, never absence; unavailable slots are inventory rows", "counters": EX.COUNTER_DEFINITIONS, "counter_names": list(EX.COUNTER_NAMES), "mechanism_record": "views / demand / fusion / two_axis / sparse / downgrades per candidate order", "clock": "one hard deadline = budget; optional allowance min(1 s, 0.05 budget)"}, open(os.path.join(D, "INSPECTION_SCHEMA.json"), "w"), indent=1)
    json.dump({"optional_or_deferred_only": [r for r in doc["rows"] if r["kind"] == "OPTIONAL"], "mandatory_absent": [r["id"] for r in doc["rows"] if r["kind"] == "MANDATORY" and r["status"] != "QUALIFIED"], "disclosed_limits": ["the LRU cache key is (node, index) within ONE attempt (attempt isolation by handle lifetime); no cross-attempt reuse", "sparse join blocks are one-driver joins (smallest known support x free axes), bounded and complete; not an optimal multi-way join", "fusion merges a message REDUCE into its consumer by the whole-path price; no derived-program congruence search", "GMP/MPFR allocation failure is not catchable (GMP aborts): category reservations + external supervision bound it", "the polling quantum is 4,096 units + one indivisible MPFR primitive", "host-side memory is RESERVED by documented proxies, not measured (demand sets: 96 B per index; numerals: 3 x limb bytes + token copies; these are reservation discipline, not RSS)", "the frozen census hash (adp.campaign.code_hash) folds the sha256 of an EXTERNAL comparator binary (Merlin, absolute path outside the repository, third-party, not vendored): declared in PACKAGE_RECORD.external_provenance_dependency; on a host without it the hash differs by exactly the 'merlin' component", "the exact numeral grammar is decimal / exponent / a-slash-b only: other forms Python's Fraction would accept (underscores, nested fractions) are INVALID_INPUT, documented restriction", "the cost model's EXACT row-class prediction holds under its stated assumptions (no cache hits, downgrades, early drains; pending fits); outside them it is an upper bound of visited rows or UNKNOWN", "the explicit-frame sparse pullback removed the native recursion; the pre-repair crash threshold was platform-dependent (25k on both the reviewer's Linux build and this Apple build) and is no longer reachable"]}, open(os.path.join(D, "NOT_IMPLEMENTED.json"), "w"), indent=1)
    json.dump({"amendments": [{"id": "amendment_1_scope_completion_2026-11-10", "scope": "GENERAL_BIDI_COMPLETE_V3 implements the complete mandatory design of the brief COMPLETE-1 on top of the repaired V2 foundation (supervisor, reconciliation protocol, adapter protocol, pinned numerical comparators unchanged); V1 / V2 records untouched", "preserved_repairs": ["explicit frames", "runtime binary64 labels + range check", "C-ABI exception containment", "same-snapshot parsing / hashing", "independent proposal validation -> executable object", "caller task binding", "publication checks", "strict reconciliation", "category reservations", "process-tree ownership"]},
                               {"id": "amendment_2_delivered_width_protocol_2026-11-10", "scope": "publication requires the DELIVERED grid-widened max width <= 1/100 in addition to the pre-grid width (brief §15); applies to every new arm (GENERAL and PLAIN); historical records not relabelled"},
                               {"id": "amendment_3_canonical_v2_identity_2026-11-10", "scope": "task identity adds canonical_v2 model / evidence hashes (typed serialization); the legacy whitespace-normalized hash keeps its historical field name; never compared across versions"},
                               {"id": "amendment_4_repairs_during_qualification_2026-11-10", "scope": "K1 (combined frames single-pass; quadratic frame count on streamed chains) and K2 (value-loading teardown after a mid-loop DEADLINE: segmentation fault) repaired with before/after reproductions under repairs/; both found by the new controls before any benchmark cell"},
                               {"id": "amendment_5_conditioning_order_policy_2026-11-10", "scope": "GLOBAL policy clarification (review F4): the region tree conditions on variables in the REVERSE of the elimination order -- the last eliminated variable is the outermost cutset, its bucket's children are the residual components, recursively; a region's cutset is its top bucket's eliminated variable(s) (one axis, or two under the frozen two-axis rule). Documented in gbidi3.planner.Builder.build; not case-specific tuning."},
                               {"id": "amendment_6_review_repair_2026-11-10", "scope": "integrated correction pass after the 10 Nov adversarial review (branch general-bidi-complete-v3-repair-2026-11-10): complete local / global semantic validator (the five witnesses reject), fail-closed publication with complete execution identity binding, reconcilable NO_RECORD / LAUNCH_FAILED attempts, ONE whole-path cost for fusion and ranking with the unfused candidate retained, support-indexed sparse pullback with honest reverse counters, reserve-before-build through parsing / replay / planning / validation / flattening / fallback, polling of parsing / hashing / order scoring / gather / ADD, per-row qualification (no bulk promotion), deterministic fixture seeds. Four disclosed fixture changes in tests/test_gbidi3_complete.py (C04: the views witness is asserted on A2_NO_FUSION when the default arm fuses the two-variable chain; C07: the sparse witness zero_skips -> sparse_reverse_rows; C22: parse polling refuses an already-expired deadline at create; hash(name) seeds -> sha256 seeds). Kernel rebuilt (schedule v3.1-sparse-reverse). Historical records untouched; no freeze, no benchmark cell."},
                               {"id": "amendment_7_second_review_repair_2026-11-10", "scope": "integrated correction pass after the SECOND adversarial review (branch general-bidi-complete-v3-repair2-2026-11-10): coordinate-domain typing of every axis (a class-space message is never consumed as raw; proof note I12), compositional cold VALUE / PULLBACK / combined recurrences with reverse-phase reconstruction counters (I13), the one-axis and two-axis trees both kept as complete candidates ranked by the ONE cost, one support-indexed sparse pullback for queued AND immediate deliveries (labelled generic path), the all-consumer demand compiler honouring the arm switch under one aggregate row / wall budget with reserve-before-build, fallback bit-length reservations before growth, native reallocation peaks and scoped temporary charges, strided polled validation with a final deadline check, cumulative parser / hashing polling, binary64 admission and trusted re-check under the deadline, zero proof accepted only after the independent replay, one terminal-receipt contract for parent cleanup realized on the consumer side with the pinned supervisor unchanged (the owner's receipt is the evidence reference; unknown wall = envelope charge, never arithmetic on null), dynamic provenance closure + lineage check in the package, unique per-attempt qualification logs, qualification withdrawn and re-established per row. Disclosed fixture changes: C17 / C22 (the plan streams a non-fitting root itself), RD1-RD3 (split reverse counters; plan-side root streaming), jet_rows corrected (roots multiply), reps_perm mutation class added. Kernel schedule v3.2-sparse-immediate-reverse-counters. Historical records untouched; no freeze, no benchmark cell."},
                               {"id": "amendment_8_third_review_repair_2026-11-10", "scope": "integrated correction pass after the THIRD adversarial review (branch general-bidi-complete-v3-repair3-2026-11-10): the support-indexed sparse pullback is an explicit frame (mode 3) of the frame machine for queued AND immediate deliveries (no native recursion; 25k / 50k retained-sparse chains under a one-byte pending cap certify on the default stack); the cold recurrence follows the EMITTED operand schedule (a viewed child's STREAM GATHER wrapper is an unresolved operand) with stated assumptions; the shared-demand union is reserved while its inputs are live and every large lift polls at the 4,096 quantum with a commitment check; exact numerals are bounded from their TEXT before Fraction construction (grammar: decimal / exponent / a-slash-b numerals only; underscores and other Python-accepted forms are INVALID_INPUT); parent-cleanup receipts are accepted only with a UNIQUE owner receipt bound to the attempt's START ancestry or ownership-registry root that establishes the closure (zero kills legitimate); I12 proof scope corrected (non-REDUCE raw-cardinality restriction; identical-CLASS products passable only as unit-ratio permutations); the package inventory is derived from the qualification manifest with exact-id collection and the external Merlin provenance dependency declared. Disclosed fixture change: SC1 counts the explicit sparse-pull frame (3 reverse frames for one stored output; reverse reads still 2). Kernel schedule v3.3-sparse-pull-frames. Historical records untouched; no freeze, no benchmark cell."}]}, open(os.path.join(D, "AMENDMENTS.json"), "w"), indent=1)
    print(json.dumps({"requirements": doc["overall"], "counts": doc["mandatory_counts"], "charged_s": round(total, 3), "receipts": len(rc)}))


if __name__ == "__main__":
    main(sys.argv[1])
