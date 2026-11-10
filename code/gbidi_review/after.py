"""AFTER controls: the reviewers' witnesses (first + second packet) re-run on the REPAIRED source (GENERAL_BIDI_V2); the BEFORE results are
runs/.../GENERAL_BIDI_V1_2026-11-09/review_repro/REPRO_RESULTS.json and REPRO_R2_RESULTS.json (frozen V1 source). Same fixtures, independent truths.
    python -m gbidi_review.after OUT"""
from __future__ import annotations
import os, sys, json, time, traceback, subprocess, ctypes, copy
HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__))); sys.path.insert(0, HERE)
sys.set_int_max_str_digits(0)
from fractions import Fraction as Fr
from gbidi import executor as EX, plan as PL, source as GS
from gbidi_review.repro import write_uai, chain_exact, contain, delivered
from gbidi_review.repro_r2 import star
from adp.engine import View
from bidi import oracle as OR
from ext import uai as U
OUT = None


def run(arm, mp, ep, out, cfg, budget=30):
    return EX.execute(arm, mp, ep, out, time.monotonic() + budget, dict(cfg, budget_s=budget))


def pub(out, mp, ep, rec):
    cell = {"phases_s": {}}; st = EX.publish(out, mp, ep, rec, cell, time.monotonic() + 30); return st, (cell.get("point_check") or {}).get("status"), cell


def main(out):
    global OUT; OUT = out; os.makedirs(out, exist_ok=True); rep = {"purpose": "AFTER controls on the repaired source", "git_head": os.popen("git -C %s rev-parse HEAD" % HERE).read().strip(), "kernel_binary_sha256": EX.sha_file(EX.LIB), "utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}
    old = dict(PL.CAPS)
    # F1
    n = 22; b = "1.000000000000000001"; tgt = 5; mp, ep = write_uai(os.path.join(out, "f1.uai"), [2] * n, [((tgt,), ["0.49", "0.51"])] + [((i, i + 1), ["1", b, b, "1"]) for i in range(n - 1)]); truth = chain_exact(n, ["1", b, b, "1"], tgt, ["0.49", "0.51"])
    PL.CAPS["value_cache"] = 1150
    try:
        rec = run("NATIVE_PLAIN_V2", mp, ep, os.path.join(out, "f1_out"), {"allow_binary64": True, "rules": list(PL.COMMON_RULES)}); st, pc, cell = pub(os.path.join(out, "f1_out"), mp, ep, rec)
        rep["F1_near1_cap22"] = {"BEFORE": "binary64 CERTIFIED + POINT_VERIFIED with both delivered intervals EXCLUDING truth (K_acc = 4, e = 470)", "AFTER": {"route": rec["route"], "labels": rec["attempts"][-1]["labels"], "delta_max": rec["attempts"][-1]["delta_max"], "raw_misses": contain(rec["certified_intervals"], truth), "delivered_misses": contain(delivered(os.path.join(out, "f1_out")), truth), "publication": st, "point_check": pc, "downgraded_nodes": sum(1 for nd in rec["plan"]["nodes"] if nd["downgrade"]), "stream_reevals": rec["attempts"][-1]["counters"]["stream_reevals"], "frame_depth": rec["attempts"][-1]["counters"]["max_frame_depth"]}}
    finally:
        PL.CAPS.clear(); PL.CAPS.update(old)
    # F2
    mp, ep = write_uai(os.path.join(out, "f2.uai"), [2, 2], [((0, 1), ["1", "2", "3", "4"]), ((0, 1), ["1", "1", "1", "2"])]); m = U.read_model(mp); Z, N = OR.brute(m, {}); truth2 = {v: [N[v][s] / Z for s in range(2)] for v in range(2)}; orig = PL.plan; f2 = {}
    for mode in ("unchanged", "omit_factor_occurrence", "forge_response_view", "drop_message_consumer", "forge_storage_set"):
        def proposed(R, cfg, deadline=None, caps=None, mode=mode):
            P, table = orig(R, cfg, deadline, caps)
            if mode == "omit_factor_occurrence":
                nd = next(x for x in P.nodes if sum(k == "F" for k, r in x.inputs) >= 2); nd.inputs.pop(next(i for i in reversed(range(len(nd.inputs))) if nd.inputs[i][0] == "F"))
            elif mode == "forge_response_view":
                nd = next(x for x in P.nodes if x.scope); w = nd.scope[0]; nd.views[w] = View([0, 0], [0], [Fr(1), Fr(1)]); nd.radix = tuple(len(nd.views[x].reps) for x in nd.scope); nd.core_entries = 1; nd.demand = "FULL"; nd._support_out = None
            elif mode == "drop_message_consumer":
                nd = next(x for x in P.nodes if any(k == "M" for k, r in x.inputs)); nd.inputs = [x for x in nd.inputs if x[0] != "M"]
            elif mode == "forge_storage_set":
                nd = next(x for x in P.nodes if x.scope); nd.demand = [0]; nd.materialize = True; nd.fused = False
            return P, table
        PL.plan = proposed
        try:
            rec = run("GENERAL_BIDI_V2", mp, ep, os.path.join(out, "f2_" + mode), {"allow_binary64": False}); st, pc, cell = pub(os.path.join(out, "f2_" + mode), mp, ep, rec)
            f2[mode] = {"status": rec["status"], "publication": st, "point_check": pc, "misses": contain(rec["certified_intervals"], truth2), "reads_outside_demand": rec["attempts"][-1]["counters"]["reads_outside_demand"]}
        except EX.Refuse as ex:
            f2[mode] = {"REFUSED": ex.kind, "reason": ex.reason[:160]}
        finally:
            PL.plan = orig
    rep["F2_untrusted_compiler"] = {"BEFORE": "omit_factor / forge_view: wrong marginals CERTIFIED + POINT_VERIFIED", "AFTER": f2}
    # F3
    mp, ep = write_uai(os.path.join(out, "f3.uai"), [2, 2], [((0, 1), ["1", "2", "3", "4"]), ((0,), ["2", "1"])]); m = U.read_model(mp); Z, N = OR.brute(m, {}); truth3 = {v: [N[v][s] / Z for s in range(2)] for v in range(2)}; f3 = {}
    for kind in ("frames_scratch_publication", "pending_adjoints", "source_ir_maps_output", "reverse_pinned", "value_cache"):
        PL.CAPS.clear(); PL.CAPS.update(old); PL.CAPS[kind] = 1
        try:
            if kind == "source_ir_maps_output":
                def proposed(R, cfg, deadline=None, caps=None):
                    P, table = orig(R, cfg, deadline, caps); nd = next(x for x in P.nodes if x.scope); nd.demand = [0]; nd.materialize = True; nd.fused = False; return P, table
                PL.plan = proposed
            rec = run("NATIVE_PLAIN_V2", mp, ep, os.path.join(out, "f3_" + kind), {"allow_binary64": False, "rules": [], "reference_fallback": True}); f3[kind] = {"stop": rec.get("stop"), "route": rec.get("route"), "truth_contained": not contain(rec["certified_intervals"], truth3)}
        except EX.Refuse as ex:
            f3[kind] = {"REFUSED": ex.kind, "reason": ex.reason[:120]}
        finally:
            PL.plan = orig; PL.CAPS.clear(); PL.CAPS.update(old)
    rep["F3_category_caps"] = {"BEFORE": "scratch / pending / source caps of 1 byte ignored (INTERVALS_OK, 1040 B scratch used)", "AFTER": f3}
    # F4
    mp, ep = write_uai(os.path.join(out, "f4.uai"), [2, 2], [((0, 1), ["1", "2", "3", "5"]), ((1,), ["7", "11"])]); f4 = {}
    for arm in ("GENERAL_BIDI_V2", "A2_NO_FUSION"):
        rec = run(arm, mp, ep, os.path.join(out, "f4_" + arm), {"allow_binary64": False, "rules": [], "reference_fallback": False}); c = rec["attempts"][-1]["counters"]
        f4[arm] = {"fused": rec["plan"]["totals"]["fused"], "cold_work_proxy": rec["plan"]["totals"]["cold_work_proxy"], "fusion_price": [nd["cost"].get("fusion_price") for nd in rec["plan"]["nodes"] if nd["cost"].get("fusion_price")], "primal_rows": c["primal_rows"], "reverse_rows": c["reverse_rows"], "mults": c["mults"], "adds": c["adds"]}
    rep["F4_fusion_price"] = {"BEFORE": "equal proxies 52/52; actual 51/16 vs 47/14 mults/adds; 'no extra arithmetic' claim", "AFTER": f4, "note": "the combined value+pullback frame regenerates the last streamed input once per reverse row: fused mults now equal the stored path's (51 = 51) while storing one entry instead of three; the price (28 vs 30) reflects the actual schedule"}
    # F5
    import random
    r = random.Random(9); n = 18; facs = [((i, j), ["%d.%02d" % divmod(r.randint(1, 99), 100) for _ in range(4)]) for i in range(n) for j in range(i + 1, n)]; mp, ep = write_uai(os.path.join(out, "f5.uai"), [2] * n, facs)
    try:
        EX.execute("NATIVE_PLAIN_V2", mp, ep, os.path.join(out, "f5_out"), time.monotonic() + 0.3, {"budget_s": 0.3, "allow_binary64": False, "reference_fallback": True, "rules": []})
    except EX.Refuse as ex:
        rep["F5_record_loss"] = {"BEFORE": "Refuse without the record; 74/74 stopped V1 cells had no plan / attempts / counters", "AFTER": {"kind": ex.kind, "record_keys": sorted(k for k in ("task", "plan", "plan_candidates", "plan_validation", "mechanisms", "attempts", "live") if k in ex.rec), "diagnostic_file": os.path.exists(os.path.join(out, "f5_out", "diagnostic_record.json")), "counters_at_stop": {k: ex.rec["attempts"][-1]["counters"][k] for k in ("primal_rows", "value_frames", "polls")}, "live": ex.rec.get("live")}}
    # R2-01
    mp = os.path.join(out, "race.uai"); ep = mp + ".evid"; open(mp, "w").write("MARKOV\n1\n2\n1\n1 0\n2 1 3\n"); open(ep, "w").write("0\n"); oi = GS.Snapshot.__init__
    def racing(self, m_, e_):
        oi(self, m_, e_); open(m_, "w").write("MARKOV\n1\n2\n1\n1 0\n2 3 1\n")
    GS.Snapshot.__init__ = racing
    try:
        rec = run("GENERAL_BIDI_V2", mp, ep, os.path.join(out, "race_out"), {"allow_binary64": False, "rules": []})
    finally:
        GS.Snapshot.__init__ = oi
    st, pc, cell = pub(os.path.join(out, "race_out"), mp, ep, rec)
    rep["R2_01_hash_race"] = {"BEFORE": "old posterior [1/4,3/4] bound to the NEW file's hash: CERTIFIED + POINT_VERIFIED (error 1/2)", "AFTER": {"record_bound_to_parsed_bytes": rec["task"]["raw_model_sha256"] != EX.sha_file(mp), "publication": st, "reason": cell.get("reason")}}
    # R2-02
    r2 = {}
    for nn, budget in ((600, 20.0), (300, 2.0)):
        mp, ep, truth = star(os.path.join(out, "star%d.uai" % nn), nn)
        for arm in ("GENERAL_BIDI_V2", "NATIVE_PLAIN_V2"):
            t = time.monotonic(); cell = {"phases_s": {}}
            try:
                rec = EX.execute(arm, mp, ep, os.path.join(out, "star%d_%s" % (nn, arm)), time.monotonic() + budget, {"budget_s": budget, "allow_binary64": False, "reference_fallback": True, "rules": list(PL.COMMON_RULES)}, phases=cell["phases_s"]); st = EX.publish(os.path.join(out, "star%d_%s" % (nn, arm)), mp, ep, rec, cell, time.monotonic() + budget)
                r2["n%d_%s" % (nn, arm)] = {"status": rec["status"], "publication": st, "point_check": (cell.get("point_check") or {}).get("status"), "order": rec["plan"]["order"]["name"], "misses": len(contain(rec["certified_intervals"], truth)), "elapsed_s": round(time.monotonic() - t, 3), "plan_s": round(cell["phases_s"]["plan"], 3), "candidates": [(c["order"], c.get("state"), c.get("baseline")) for c in rec["plan_candidates"]]}
            except EX.Refuse as ex:
                r2["n%d_%s" % (nn, arm)] = {"REFUSED": ex.kind, "reason": ex.reason[:120]}
    rep["R2_02_star"] = {"BEFORE": "GENERAL 600 @ 20 s: REJECTED 'program index exceeds int64' after 1.4-2.5 s; PLAIN certified", "AFTER": r2}
    # R2-04 / R2-05 / R2-06 / R2-07 are covered one-to-one by tests/test_gbidi_v2.py (R2_04 deep chain under the default stack, R2_05 bad_alloc + source-free polling, R2_06 FE_UPWARD + MPFR exponent envelope, R2_07 malformed grammar); R2-08 supervisor, R2-09 identity / closeout likewise
    rep["covered_by_tests"] = {"R2_04": "test_R2_04_deep_streamed_chain_runs_on_explicit_frames_under_the_default_stack", "R2_05": ["test_R2_05_bad_alloc_is_a_typed_memory_stop_not_a_process_abort", "test_R2_05_source_free_bucket_polls_the_deadline"], "R2_06": ["test_R2_06_upward_rounding_refuses_binary64_and_mpfr_still_certifies", "test_R2_06_mpfr_exponent_overflow_and_underflow_are_typed_range_stops_without_a_precision_ladder"], "R2_07": ["test_R2_07_malformed_input_is_a_typed_refusal_never_certified", "test_R2_07_valid_scalar_factors_and_bad_evidence"], "R2_08": "test_R2_08_supervisor_completion_means_the_owned_group_is_empty", "R2_09": ["test_R2_09_manifest_identity_reconciliation_rejects_forged_ids_aliases_and_duplicates", "test_R2_09_closeout_ledger_requires_a_bound_record_and_a_matching_receipt"], "F6": [t for t in ("test_F6_split_root_deltas_with_eviction_on_a_model_with_non_root_stored_values", "test_F6_response_views_fire_on_a_nonbipartite_nonbinary_model_and_reduce_core_volume", "test_F6_demand_restriction_fires_and_reduces_stored_entries", "test_F6_fusion_must_activate_on_the_cycle_fixture", "test_F6_forged_result_token_is_caught_by_the_simplex_consistency_check")], "extra": ["test_reference_stream_is_a_resumable_odometer_with_growable_export (2^63 gate, 4 MiB export buffer)", "test_SB_03_empty_query_task_goes_through_the_same_separate_verifier", "test_SB_02_interrupted_view_pass_leaves_consistent_metadata", "test_R2_02_metadata_cap_during_adjacency_keeps_the_original_candidate", "test_R2_02_expired_discovery_clock_keeps_the_baseline_and_an_expired_inspect_refuses_to_spend", "test_median_is_the_ordinary_median", "test_counters_match_a_hand_enumerated_two_node_schedule"]}
    json.dump(rep, open(os.path.join(out, "AFTER_RESULTS.json"), "w"), indent=1, default=str); print(json.dumps(rep, indent=1, default=str)[:6000])


if __name__ == "__main__":
    main(os.path.abspath(sys.argv[1]))
