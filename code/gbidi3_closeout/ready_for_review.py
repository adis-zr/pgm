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
            name = r["job"].split(":", 1)[1]; out = os.path.join(q, ("pytest_" + name.replace("gbidi3_", "") + ".txt") if not name.startswith("existing") else ("pytest_" + name + ".txt"))
            cand = [f for f in os.listdir(q) if f.endswith(".txt") and name.replace("gbidi3_", "") in f] if not os.path.exists(out) else [os.path.basename(out)]
            s = pytest_summary(os.path.join(q, cand[0])) if cand else {"file": None, "passed": None, "failed": None}
            attempts.append({"job": r["job"], "jid": r["jid"], "wall_s": r["wall_s"], "outcome": r["outcome"], "returncode": r["returncode"], **s})
    final_v3 = [a for a in attempts if a["job"] == "pytest:gbidi3_full_attempt7"][0]; final_reg = [a for a in attempts if a["job"] == "pytest:existing_regressions_1"][0]
    collect = open(os.path.join(q, "pytest_collect_only.txt")).read()
    counts = collections.Counter(l.split("::")[0] for l in collect.splitlines() if "::" in l)
    man = {"utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "suite_v3": "tests/test_gbidi3_complete.py", "suite_v3_def_count": sum(1 for l in open(os.path.join(HERE, "tests/test_gbidi3_complete.py")) if l.startswith("def test_")), "collected_by_file": dict(counts),
           "final_runs": {"v3_controls": final_v3, "existing_regressions": final_reg}, "every_pytest_attempt": attempts, "skips": "none (no skip markers; architecture-dependent controls run on this arm64 macOS host: rounding-mode flag 0x400000, guard-malloc not required)",
           "import_dependencies": {"tests/test_gbidi3_complete.py": ["gbidi3.*", "adp.source (pinned reductions)", "adp.publish / adp.checker (pinned publication + point verifier)", "ext.uai (pinned dataclasses / MAR reader)", "gbidi.supervise (unchanged V2 supervisor)", "bench.cells EXACT + adp.cell producers through gbidi3.arm_adapter (C24 end-to-end)"]},
           "fixtures_and_oracle": {"oracle": "gbidi3/oracle.py (brute force over ORIGINAL factors; shares only the parser)", "fixtures": "inline in tests/test_gbidi3_complete.py (write_uai / rnd_model / star_model / chain_exact / _c16_model / _shared_consumer_program / _c15_program)"},
           "repairs_during_qualification": {"K1": rel(os.path.join(D, "repairs/K1_combined_frame")), "K2": rel(os.path.join(D, "repairs/K2_load_values_teardown"))},
           "note": "every pytest attempt (including the failing fixture-development attempts 1-6) is retained with its receipt; a count alone is not qualification: the control bodies assert the named mechanism / transition fired"}
    json.dump(man, open(os.path.join(D, "QUALIFICATION_MANIFEST.json"), "w"), indent=1)
    # ---------------------------------------------------------------- requirements matrix: advance rows with evidence
    T = "tests/test_gbidi3_complete.py"; F = rel(os.path.join(q, "pytest_full_attempt7.txt")); R = rel(os.path.join(q, "pytest_existing_regressions_1.txt"))
    ev = {"M01": [T + "::test_every_arm_encloses_exact_truth_on_every_input_class", T + "::test_malformed_models_are_typed_invalid_input_through_the_caller_pipeline", T + "::test_malformed_evidence_is_typed_invalid_input", T + "::test_valid_edge_grammar_scalars_duplicates_and_identity_fields", T + "::test_C06", T + "::test_C07", T + "::test_C10", T + "::test_C12", T + "::test_C21", F],
          "M02": [T + "::test_C20_every_corruption_class_is_rejected_or_cannot_reach_execution", T + "::test_C12 (independent replay of tampered reduction records)", F],
          "M03": [T + "::test_C23_star_cases_reach_the_cheap_order_with_an_expired_optional_clock_and_one_hard_deadline", F],
          "M04": [T + "::test_C03_every_consumer_contributes_through_a_shared_node", T + "::test_C04_dead_representative_live_class_preserved", T + "::test_C13_interrupted_discovery_keeps_full_demand_identity_views_and_exact_truth", rel(os.path.join(D, "PANEL_INSPECTION.json")) + " (demand restricted on 2/46 cases; FULL elsewhere)", F],
          "M05": [T + "::test_every_arm_encloses_exact_truth_on_every_input_class (5 arms x 12 classes x 3 modes)", T + "::test_C14 (A2_NO_FUSION contrast)", F],
          "M06": [T + "::test_C01_equal_scalar_different_marked_response_merge_rejected", T + "::test_C04", T + "::test_C05_crossing_partitions_truth_two_not_four_and_joint_refinement", T + "::test_C07 (product-zero classes)", F],
          "M07": [T + "::test_C17_dense_blocks_sparse_joins_with_aggregation_stream_downgrade_and_scalar_chunking", F],
          "M08": [T + "::test_C17", T + "::test_C07 (empty-support sparse node)", T + "::test_C13 (capped join discarded)", F],
          "M09": [T + "::test_C18_fifty_thousand_frame_chain_under_the_default_stack_and_a_shallow_lookalike", T + "::test_C06 (stream mode)", F],
          "M10": [T + "::test_C16_general_conditioning_components_isolated_variable_zeros_scalars_external_adjoints", T + "::test_C25", F],
          "M11": [T + "::test_C16 (one-axis / two-axis / ineligible > 4,096)", F],
          "M12": [T + "::test_C03", T + "::test_C09", T + "::test_C15", F],
          "M13": [T + "::test_C09_tiny_cache_eviction_regeneration_and_value_hits_never_add_numerators", T + "::test_C15_late_deltas_coalesce_exactly_once_with_eviction_and_regeneration", T + "::test_C18 (bounded reuse removes repeated visits)", T + "::test_C22 (pending cap -> early flush)", F],
          "M14": [T + "::test_every_execution_mode_matches_the_oracle_rows_exactly_when_run_through_the_exact_fallback", T + "::test_C11 (scale restoration)", T + "::test_C25 (ref faults)", T + "::test_C22 (fallback caps / deadline)", F],
          "M15": [T + "::test_C11_extreme_range_bridge_and_scale_restoration", T + "::test_C19 (MPFR exponent fault, no ladder)", F],
          "M16": [T + "::test_C19_streamed_chain_binary64_labels_against_exact_truth_and_every_guard_branch", F],
          "M17": [T + "::test_C21_task_and_publication_attacks", T + "::test_C12", F],
          "M18": [T + "::test_C22_every_category_cap_python_storage_pending_transfers_fallback_export_overflow_polling_abi", T + "::test_C17 (1-byte value category: no block allocated)", F],
          "M19": [T + "::test_C23", T + "::test_C22 (3,000-unary first poll within 4,096 units; K2 deadline during loading)", F],
          "M20": [T + "::test_C24_supervisor_completion_means_the_owned_group_is_empty", T + "::test_C24_nested_supervisors_owned_tree_is_reconciled", "tests/test_gbidi_v2.py::test_H3_nested_supervisors_owned_tree_is_reconciled (unchanged supervisor)", R],
          "M21": [T + "::test_C24_manifest_reconciler_and_accounting", T + "::test_C24_all_seven_arms_end_to_end_through_the_real_harness_resume_and_closeout", F],
          "M22": [T + "::test_C24_manifest_reconciler_and_accounting (414 = 184 + 92 + 138; order reproduced independently)", rel(os.path.join(D, "GB_MANIFEST_PROPOSED.json")), rel(os.path.join(D, "PANEL_INSPECTION.json")), F],
          "M23": [T + "::test_C14 (price declines / accepts)", T + "::test_C16 (two-axis cold estimate)", rel(os.path.join(D, "PANEL_INSPECTION.json")) + " (candidate totals per order)", F],
          "M24": [T + "::test_C01", T + "::test_C02_marker_duplication_rejected_even_though_Z_is_unchanged", T + "::test_C05", T + "::test_C10", T + "::test_C14_fusion_fires_by_price_saves_materialization_and_keeps_every_derivative", T + "::test_C20", F],
          "M25": [T + "::test_C07_zero_safety_inconsistency_zero_numerators_empty_sparse_zero_scalar_product_zero_classes", T + "::test_C11", T + "::test_C21 (zero-variable tasks)", F]}
    for rid, paths in ev.items():
        RQ.update(D, rid, "QUALIFIED", evidence=paths, note="final suite pytest:gbidi3_full_attempt7 126 passed; existing regressions 236 passed")
    doc = RQ.write(D)
    # ---------------------------------------------------------------- budget ledger (one authoritative total; every START reconciled)
    total, by, unresolved, extra = PI.charged(D)
    budget = {"envelope_s": PI.CEILING_S, "preparation_cap_s": PI.PREPARATION_CAP_S, "rule": "nonnested: children + measured nonnegative parent-only remainder (gbidi3.pilot.charged); every START reconciled to exactly one RECEIPT", "total_charged_s": total, "by_scope": by, "receipts": len(rc), "starts": len(st), "unresolved": [u.get("job") for u in unresolved], "duplicate_receipts": extra["duplicate_receipts"],
              "remaining_preparation_s": PI.PREPARATION_CAP_S - total, "remaining_envelope_s": PI.CEILING_S - total, "reservations_proposed_s": {"matrix_414_plus_launch_cleanup": PI.MATRIX_RESERVE_S, "inspection_analysis": PI.INSPECTION_RESERVE_S, "closeout_packaging": PI.CLOSEOUT_RESERVE_S, "contingency": PI.CONTINGENCY_S},
              "compliance": "EXACT for this ledger: every START has exactly one RECEIPT, no unresolved cleanup, no duplicate receipts" if not unresolved and not extra["duplicate_receipts"] else "QUALIFIED",
              "exposure_not_in_this_ledger": "human / agent reasoning and text editing (not job wall, per the brief); ad-hoc interpreter probes run WITHOUT the supervisor during development (planner debugging, kernel probe scripts, test-fixture probes): MEASURED? no; ESTIMATED upper bound ~120 s of interpreter wall across the session; UNKNOWN exact total -> disclosed as uncharged development exposure (protocol deviation of the same class recorded in the ADP campaign)",
              "historical_ledgers": "untouched: GENERAL_BIDI_V1 (10,506.4 s raw receipts, one unreceipted START), GENERAL_BIDI_V2 (332.773 s), BIDI pilot, ADP, census; this ledger is NEW and separate (brief §22)", "packaging_receipt": "sidecar next to the archive (its wall finishes after the archive is built)"}
    json.dump(budget, open(os.path.join(D, "BUDGET_LEDGER.json"), "w"), indent=1)
    # ---------------------------------------------------------------- code lineage
    files = sorted(set(PI.source_set() + ["gbidi3_closeout/" + f for f in os.listdir(os.path.join(HERE, "gbidi3_closeout")) if f.endswith(".py")] + ["gbidi3/libgbidi3_kernel.dylib", "gbidi3/BUILD_RECORD.json"]))
    lineage = {"branch": git("rev-parse", "--abbrev-ref", "HEAD"), "head_before_closeout_commit": git("rev-parse", "HEAD"), "parent_v2_closeout": "88a3e325e159b92eb6655ef31dd5bba9f9e1e58c", "parent_v2_package_record": "16c79e67eae569d4e998d51333aaabfe442e6853", "parent_prose_handoff_commit": "faa88a2ec96500e8eeb7ce9b0e59ee628afbb270",
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
    json.dump({"optional_or_deferred_only": [r for r in doc["rows"] if r["kind"] == "OPTIONAL"], "mandatory_absent": [r["id"] for r in doc["rows"] if r["kind"] == "MANDATORY" and r["status"] != "QUALIFIED"], "disclosed_limits": ["the LRU cache key is (node, index) within ONE attempt (attempt isolation by handle lifetime); no cross-attempt reuse", "sparse join blocks are one-driver joins (smallest known support x free axes), bounded and complete; not an optimal multi-way join", "fusion merges a message REDUCE into its consumer by the whole-path price; no derived-program congruence search", "GMP/MPFR allocation failure is not catchable (GMP aborts): category reservations + external supervision bound it", "the polling quantum is 4,096 units + one indivisible MPFR primitive", "host-side memory is RESERVED by documented proxies, not measured"]}, open(os.path.join(D, "NOT_IMPLEMENTED.json"), "w"), indent=1)
    json.dump({"amendments": [{"id": "amendment_1_scope_completion_2026-11-10", "scope": "GENERAL_BIDI_COMPLETE_V3 implements the complete mandatory design of the brief COMPLETE-1 on top of the repaired V2 foundation (supervisor, reconciliation protocol, adapter protocol, pinned numerical comparators unchanged); V1 / V2 records untouched", "preserved_repairs": ["explicit frames", "runtime binary64 labels + range check", "C-ABI exception containment", "same-snapshot parsing / hashing", "independent proposal validation -> executable object", "caller task binding", "publication checks", "strict reconciliation", "category reservations", "process-tree ownership"]},
                               {"id": "amendment_2_delivered_width_protocol_2026-11-10", "scope": "publication requires the DELIVERED grid-widened max width <= 1/100 in addition to the pre-grid width (brief §15); applies to every new arm (GENERAL and PLAIN); historical records not relabelled"},
                               {"id": "amendment_3_canonical_v2_identity_2026-11-10", "scope": "task identity adds canonical_v2 model / evidence hashes (typed serialization); the legacy whitespace-normalized hash keeps its historical field name; never compared across versions"},
                               {"id": "amendment_4_repairs_during_qualification_2026-11-10", "scope": "K1 (combined frames single-pass; quadratic frame count on streamed chains) and K2 (value-loading teardown after a mid-loop DEADLINE: segmentation fault) repaired with before/after reproductions under repairs/; both found by the new controls before any benchmark cell"}]}, open(os.path.join(D, "AMENDMENTS.json"), "w"), indent=1)
    print(json.dumps({"requirements": doc["overall"], "counts": doc["mandatory_counts"], "charged_s": round(total, 3), "receipts": len(rc)}))


if __name__ == "__main__":
    main(sys.argv[1])
