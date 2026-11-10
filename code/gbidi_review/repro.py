"""REVIEW REPRODUCTION (9 Nov 2026 interim review of GENERAL_BIDI_V1): re-run the reviewer's defect witnesses on the FROZEN source at HEAD (a62625e6
frozen set unchanged; verified by the caller with git diff) and the frozen Apple/ARM kernel binary, in ONE charged job. Nothing here is campaign
evidence; nothing here modifies a historical cell. Every truth value is computed INDEPENDENTLY of the engine (exact Fraction chain messages or the
exhaustive bidi.oracle). Process-local monkeypatches (caps, planner wrapper) are restored after each probe.
    python -m gbidi_review.repro OUT_DIR"""
from __future__ import annotations
import os, sys, json, time, glob, traceback, copy
HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__))); sys.path.insert(0, HERE)
sys.set_int_max_str_digits(0)
from fractions import Fraction as Fr
from gbidi import executor as EX, plan as PL
from bidi import oracle as OR
from ext import uai as U
from adp.engine import View

OUT = None
LOG = []


def log(*a):
    s = " ".join(str(x) for x in a); LOG.append(s); print(s, flush=True)


def write_uai(path, card, factors, tokens=None):
    lines = ["MARKOV", str(len(card)), " ".join(map(str, card)), str(len(factors))] + ["%d %s" % (len(sc), " ".join(map(str, sc))) for sc, _ in factors]
    for i, (_, tab) in enumerate(factors):
        lines.append("%d %s" % (len(tab), " ".join(tab)))
    open(path, "w").write("\n".join(lines) + "\n"); open(path + ".evid", "w").write("0\n"); return path, path + ".evid"


def chain_exact(n, pair, unary_at, unary):
    """exact marginals of a binary chain 0-1-...-(n-1) with the SAME 2x2 pair table on every edge and one unary: forward/backward Fraction messages
    (independent of gbidi: no planner, no kernel)."""
    pair = [[Fr(pair[0]), Fr(pair[1])], [Fr(pair[2]), Fr(pair[3])]]; un = [[Fr(1), Fr(1)] for _ in range(n)]; un[unary_at] = [Fr(unary[0]), Fr(unary[1])]
    fwd = [None] * n; fwd[0] = [un[0][a] for a in range(2)]
    for i in range(1, n):
        fwd[i] = [un[i][b] * sum(fwd[i - 1][a] * pair[a][b] for a in range(2)) for b in range(2)]
    bwd = [None] * n; bwd[n - 1] = [Fr(1), Fr(1)]
    for i in range(n - 2, -1, -1):
        bwd[i] = [sum(pair[a][b] * un[i + 1][b] * bwd[i + 1][b] for b in range(2)) for a in range(2)]
    Z = sum(fwd[n - 1]); return {v: [fwd[v][a] * bwd[v][a] / Z for a in range(2)] for v in range(n)}


def contain(ivs_str, truth):
    miss = []
    for v, row in ivs_str.items():
        for s, (a, b) in enumerate(row):
            if not (Fr(a) <= truth[int(v)][s] <= Fr(b)):
                miss.append({"var": int(v), "state": s, "lo": a, "hi": b, "truth": str(truth[int(v)][s])})
    return miss


def delivered(out):
    p = os.path.join(out, "intervals.json")
    if not os.path.exists(p):
        return None
    d = json.load(open(p)); return {str(r["var"]): r["intervals"] for r in d["intervals"]}


def run_exec(arm, mp, ep, out, cfg, budget=30):
    return EX.execute(arm, mp, ep, out, time.monotonic() + budget, dict(cfg, budget_s=budget))


def publish(out, mp, ep, rec):
    cell = {"phases_s": {}}; st = EX.publish(out, mp, ep, rec, cell, time.monotonic() + 30); return st, cell.get("point_check", {}).get("status"), cell


# ----------------------------------------------------------------------------------------------------------------------- F1: binary64 under streaming
def f1():
    res = {}
    # (a) the reviewer's strongest witness: 22-var chain, b = 1 + 1e-18, unary [.49,.51] at 5, ALL normal rules, value cap 1150 B -> planner downgrades
    n = 22; b = "1.000000000000000001"; tgt = 5
    mp, ep = write_uai(os.path.join(OUT, "f1_near1_cap22.uai"), [2] * n, [((tgt,), ["0.49", "0.51"])] + [((i, i + 1), ["1", b, b, "1"]) for i in range(n - 1)])
    truth = chain_exact(n, ["1", b, b, "1"], tgt, ["0.49", "0.51"]); assert truth[tgt] == [Fr(49, 100), Fr(51, 100)]
    old = dict(PL.CAPS)
    try:
        PL.CAPS["value_cache"] = 1150; o = os.path.join(OUT, "f1_near1_cap22_out")
        rec = run_exec("NATIVE_PLAIN_V1", mp, ep, o, {"allow_binary64": True, "rules": list(PL.COMMON_RULES)})
        st, pc, cell = publish(o, mp, ep, rec)
        res["near1_cap22_default_rules"] = {"status": rec["status"], "route": rec.get("route"), "admission": {k: rec["binary64_admission"].get(k) for k in ("E_fwd", "E_rev", "K_acc", "E_N", "E_Z", "e", "delta", "checks")},
                                            "reductions_steps": rec["reductions"]["steps"], "downgraded_nodes": [nd["nid"] for nd in rec["plan"]["nodes"] if nd["downgrade"]], "counters": rec["attempts"][-1]["counters"],
                                            "raw_misses": contain(rec["certified_intervals"], truth), "publication": st, "point_check": pc, "delivered_misses": contain(delivered(o), truth) if delivered(o) else None,
                                            "truth_target": [str(x) for x in truth[tgt]], "raw_target": rec["certified_intervals"][str(tgt)], "delivered_target": (delivered(o) or {}).get(str(tgt))}
    finally:
        PL.CAPS.clear(); PL.CAPS.update(old)
    # (b) 21-var all-ones chain, unary [.48,.52], rules=[], cap 1100 B (reviewer's first cap witness)
    n = 21
    mp, ep = write_uai(os.path.join(OUT, "f1_cap21.uai"), [2] * n, [((tgt,), ["0.48", "0.52"])] + [((i, i + 1), ["1"] * 4) for i in range(n - 1)])
    truth = chain_exact(n, ["1"] * 4, tgt, ["0.48", "0.52"])
    try:
        PL.CAPS["value_cache"] = 1100; o = os.path.join(OUT, "f1_cap21_out")
        rec = run_exec("NATIVE_PLAIN_V1", mp, ep, o, {"allow_binary64": True, "rules": []}); st, pc, cell = publish(o, mp, ep, rec)
        res["cap21_rules_off"] = {"status": rec["status"], "route": rec.get("route"), "admission_e": rec["binary64_admission"].get("e"), "delta": rec["binary64_admission"].get("delta"), "K_acc": rec["binary64_admission"].get("K_acc"), "counters": rec["attempts"][-1]["counters"],
                                 "raw_misses": contain(rec["certified_intervals"], truth), "publication": st, "point_check": pc, "delivered_misses": contain(delivered(o), truth) if delivered(o) else None, "raw_target": rec["certified_intervals"][str(tgt)]}
    finally:
        PL.CAPS.clear(); PL.CAPS.update(old)
    # (c) same 21-var chain on the rigorous MPFR route for comparison (the general route): must contain the truth
    o = os.path.join(OUT, "f1_cap21_mpfr_out")
    try:
        PL.CAPS["value_cache"] = 1100
        rec = run_exec("NATIVE_PLAIN_V1", mp, ep, o, {"allow_binary64": False, "rules": []}); res["cap21_mpfr_control"] = {"status": rec["status"], "route": rec.get("route"), "precision": rec.get("precision"), "raw_misses": contain(rec["certified_intervals"], truth), "max_width": rec.get("max_width")}
    finally:
        PL.CAPS.clear(); PL.CAPS.update(old)
    return res


# ----------------------------------------------------------------------------------------------------------------------- F2: untrusted compiler proposals are executed unchecked
def f2():
    res = {}; mp, ep = write_uai(os.path.join(OUT, "f2_two_factors.uai"), [2, 2], [((0, 1), ["1", "2", "3", "4"]), ((0, 1), ["1", "1", "1", "2"])])
    model = U.read_model(mp); Z, N = OR.brute(model, {}); truth = {v: [N[v][s] / Z for s in range(2)] for v in range(2)}; assert Z == 14
    orig = PL.plan
    for mode in ("unchanged", "omit_factor_occurrence", "forge_response_view"):
        def proposed(R, cfg, deadline=None, mode=mode):
            P, table = orig(R, cfg, deadline)
            if mode == "omit_factor_occurrence":
                nd = next(n for n in P.nodes if sum(k == "F" for k, r in n.inputs) >= 2); i = next(i for i in reversed(range(len(nd.inputs))) if nd.inputs[i][0] == "F"); nd.inputs.pop(i)
            elif mode == "forge_response_view":
                nd = next(n for n in P.nodes if n.scope); w = nd.scope[0]; nd.views[w] = View([0, 0], [0], [Fr(1), Fr(1)]); nd.radix = tuple(len(nd.views[x].reps) for x in nd.scope); nd.core_entries = 1; nd.demand = "FULL"; nd._support_out = None
            return P, table
        PL.plan = proposed; o = os.path.join(OUT, "f2_" + mode)
        try:
            rec = run_exec("GENERAL_BIDI_V1", mp, ep, o, {"allow_binary64": False}); st, pc, cell = publish(o, mp, ep, rec)
            res[mode] = {"status": rec["status"], "publication": st, "point_check": pc, "intervals": rec["certified_intervals"], "misses_vs_exact": contain(rec["certified_intervals"], truth), "task_hash_matches_caller": rec["task"]["raw_model_sha256"] == EX.sha_file(mp)}
        except Exception as ex:
            res[mode] = {"exception": repr(ex)}
        finally:
            PL.plan = orig
    res["truth"] = {str(v): [str(x) for x in truth[v]] for v in truth}; return res


# ----------------------------------------------------------------------------------------------------------------------- F3: category caps not enforced
def f3():
    res = {}; mp, ep = write_uai(os.path.join(OUT, "f3_tiny.uai"), [2, 2], [((0, 1), ["1", "2", "3", "4"]), ((0,), ["2", "1"])]); model = U.read_model(mp); Z, N = OR.brute(model, {}); truth = {v: [N[v][s] / Z for s in range(2)] for v in range(2)}
    old = dict(PL.CAPS)
    for kind in ("frames_scratch_publication", "pending_adjoints", "source_ir_maps_output", "reverse_pinned", "value_cache"):
        try:
            PL.CAPS.clear(); PL.CAPS.update(old); PL.CAPS[kind] = 1; o = os.path.join(OUT, "f3_" + kind)
            rec = run_exec("NATIVE_PLAIN_V1", mp, ep, o, {"allow_binary64": False, "rules": [], "reference_fallback": True})
            res[kind] = {"cap_bytes": 1, "status": rec["status"], "route": rec.get("route"), "precision": rec.get("precision"), "stop": rec.get("stop"), "counters_used": {k: v for k, v in (rec["attempts"][-1].get("counters") or {}).items() if k.startswith("used_")} if rec.get("attempts") else None, "truth_contained": not contain(rec["certified_intervals"], truth)}
        except Exception as ex:
            res[kind] = {"cap_bytes": 1, "exception": repr(ex)}
        finally:
            PL.CAPS.clear(); PL.CAPS.update(old)
    return res


# ----------------------------------------------------------------------------------------------------------------------- F4: fusion price omits reverse-time primal regeneration
def f4():
    res = {}; mp, ep = write_uai(os.path.join(OUT, "f4_two_variable.uai"), [2, 2], [((0, 1), ["1", "2", "3", "5"]), ((1,), ["7", "11"])]); model = U.read_model(mp); Z, N = OR.brute(model, {}); truth = {v: [N[v][s] / Z for s in range(2)] for v in range(2)}; assert Z == 105
    for arm in ("GENERAL_BIDI_V1", "A2_NO_FUSION"):
        o = os.path.join(OUT, "f4_" + arm); rec = run_exec(arm, mp, ep, o, {"allow_binary64": False, "rules": [], "reference_fallback": False})
        res[arm] = {"status": rec["status"], "fused": rec["plan"]["totals"]["fused"], "cold_work_proxy": rec["plan"]["totals"]["cold_work_proxy"], "ideal_reuse_lower": rec["plan"]["totals"]["ideal_reuse_lower"], "materialized_entries_planned": rec["plan"]["totals"]["materialized_entries"],
                    "counters": {k: rec["attempts"][-1]["counters"][k] for k in ("rows", "mults", "adds", "lookups", "fused_reevals", "entries_materialized", "recomputations")}, "misses_vs_exact": contain(rec["certified_intervals"], truth)}
    return res


# ----------------------------------------------------------------------------------------------------------------------- F5: resource-stop record loss (live demonstration + census of the paused run)
def f5():
    res = {}
    n = 18; card = [2] * n; import random
    r = random.Random(9); facs = [((i, j), ["%d.%02d" % divmod(r.randint(1, 99), 100) for _ in range(4)]) for i in range(n) for j in range(i + 1, n)]
    mp, ep = write_uai(os.path.join(OUT, "f5_deadline.uai"), card, facs); o = os.path.join(OUT, "f5_deadline_out")
    try:
        EX.execute("NATIVE_PLAIN_V1", mp, ep, o, time.monotonic() + 0.3, {"budget_s": 0.3, "allow_binary64": False, "reference_fallback": True, "rules": []}); res["live"] = {"unexpected": "completed"}
    except EX.Refuse as ex:
        res["live"] = {"exception_kind": ex.kind, "reason": ex.reason, "record_written": os.path.exists(os.path.join(o, "checked_record.json")), "files_in_out": sorted(os.listdir(o)) if os.path.exists(o) else [], "note": "the executor's rec (task, reductions, plan, candidates, mechanisms, backend, admission, attempts, counters) existed in memory and is NOT written or returned on this path"}
    # census of the paused run's resource-stopped new-arm cells: which record keys survive
    D = os.path.dirname(OUT); cells = sorted(glob.glob(os.path.join(D, "cells", "*", "*", "cell.json"))); stopped = []; keys = {}
    for c in cells:
        rec = json.load(open(c))
        if rec.get("arm") in ("GENERAL_BIDI_V1", "NATIVE_PLAIN_V1") and rec.get("status") == "RESOURCE_STOP":
            stopped.append(c); d = os.path.dirname(c); prog = json.load(open(os.path.join(d, "progress.json"))) if os.path.exists(os.path.join(d, "progress.json")) else None
            for k in ("plan", "attempts", "mechanisms", "plan_candidates", "binary64_admission", "reductions", "task"):
                keys[k] = keys.get(k, 0) + (1 if k in rec else 0)
            keys["progress_has_only_startup_phase"] = keys.get("progress_has_only_startup_phase", 0) + (1 if prog and set(prog.get("phases_s") or {}) <= {"startup_imports"} else 0)
            keys["checked_record_present"] = keys.get("checked_record_present", 0) + (1 if os.path.exists(os.path.join(d, "checked_record.json")) else 0)
    res["paused_run_census"] = {"resource_stopped_new_arm_cells": len(stopped), "cells_with_key": keys, "note": "every stopped cell keeps phases_s (so plan/numerics wall are known) and the typed stop (phase forward/reverse) but no plan, attempts or counters"}
    return res


# ----------------------------------------------------------------------------------------------------------------------- additional bounded-control findings
def extra():
    res = {}
    # (1) assignment-count gate (>= 2^63) reported as DEADLINE 'visited None'
    mp, ep = write_uai(os.path.join(OUT, "x_count63.uai"), [2] * 63, []); old = dict(PL.CAPS)
    try:
        PL.CAPS["value_cache"] = 1; t = time.monotonic()
        try:
            EX.execute("NATIVE_PLAIN_V1", mp, ep, os.path.join(OUT, "x_count63_out"), time.monotonic() + 15, {"budget_s": 15, "allow_binary64": False, "reference_fallback": True, "rules": []}); res["count_gate"] = {"unexpected": "completed"}
        except EX.Refuse as ex:
            res["count_gate"] = {"kind": ex.kind, "reason": ex.reason, "elapsed_s": time.monotonic() - t, "expected": "a typed ROUTE_LIMITATION / INDEX_LIMIT, not DEADLINE with almost the whole budget left"}
    finally:
        PL.CAPS.clear(); PL.CAPS.update(old)
    # (2) fixed 4 MiB reference export buffer: 16,000-state unary with entries 1e300, forced fallback
    n = 16000; mp = os.path.join(OUT, "x_large_output.uai"); open(mp, "w").write("MARKOV\n1\n%d\n1\n1 0\n%d %s\n" % (n, n, " ".join(["1e300"] * n))); open(mp + ".evid", "w").write("0\n")
    try:
        PL.CAPS["value_cache"] = 1; t = time.monotonic()
        try:
            rec = EX.execute("NATIVE_PLAIN_V1", mp, mp + ".evid", os.path.join(OUT, "x_large_output_out"), time.monotonic() + 15, {"budget_s": 15, "allow_binary64": False, "reference_fallback": True, "rules": []}); res["fallback_buffer"] = {"status": rec.get("status"), "precision": rec.get("precision"), "elapsed_s": time.monotonic() - t}
        except Exception as ex:
            res["fallback_buffer"] = {"exception_type": type(ex).__name__, "exception": str(ex)[:200], "elapsed_s": time.monotonic() - t, "expected": "complete valid publication or a typed resource stop; never an unhandled IndexError"}
    finally:
        PL.CAPS.clear(); PL.CAPS.update(old)
    # (3) empty-variable positive task: publish CERTIFIED, separate verifier rejects on max([])
    mp = os.path.join(OUT, "x_empty_positive.uai"); open(mp, "w").write("MARKOV\n0\n\n1\n0\n1\n2/7\n"); open(mp + ".evid", "w").write("0\n"); o = os.path.join(OUT, "x_empty_positive_out")
    try:
        rec = EX.execute("GENERAL_BIDI_V1", mp, mp + ".evid", o, time.monotonic() + 5, {"budget_s": 5}); st, pc, cell = publish(o, mp, mp + ".evid", rec)
        import subprocess
        vp = os.path.join(o, "separate_point_probe.json"); subprocess.run([sys.executable, "-m", "adp.checker", "--verify-point", os.path.join(o, "checked_record.json"), os.path.join(o, "output.MAR"), mp, mp + ".evid", vp], cwd=HERE, env=dict(os.environ, PYTHONPATH=HERE), capture_output=True)
        res["empty_positive"] = {"execute": rec["status"], "Z": rec.get("Z_exact"), "publish": st, "separate_verifier": json.load(open(vp)) if os.path.exists(vp) else "no record"}
    except Exception as ex:
        res["empty_positive"] = {"exception": repr(ex)}
    # (4) expired Inspect accepts a huge first spend; METADATA cap during adjacency escapes plan(); partial view pass leaves stale radix
    ins = PL.Inspect(1_000_000, deadline=time.monotonic() - 1)
    try:
        ins.spend(999_999); res["expired_inspection_spend_accepted"] = True
    except PL.PlanStop:
        res["expired_inspection_spend_accepted"] = False
    mp, ep = write_uai(os.path.join(OUT, "x_meta.uai"), [2, 2], [((0, 1), ["1", "2", "3", "5"]), ((1,), ["7", "11"])]); oldcap = PL.METADATA_UPDATE_CAP
    try:
        PL.METADATA_UPDATE_CAP = 1; m = U.read_model(mp); R = EX.SRC.Reduced(EX._ModelAdapter(m), {})
        try:
            P, table = PL.plan(R, dict(EX.ARMS["GENERAL_BIDI_V1"], bytes_per_entry=96)); res["metadata_cap_during_adjacency"] = {"returned_plan": True, "table_states": [t.get("state") for t in table]}
        except PL.PlanStop as ex:
            res["metadata_cap_during_adjacency"] = {"returned_plan": False, "escaped": "PlanStop(%s)" % ex.kind, "expected": "retain the already-complete original-id candidate"}
    finally:
        PL.METADATA_UPDATE_CAP = oldcap
    mp, ep = write_uai(os.path.join(OUT, "x_partial_view.uai"), [2, 2, 2], [((0, 1, 2), ["1", "2", "2", "4", "3", "7", "6", "14"])]); oldrow = PL.ROW_INSPECTION_CAP; olda = copy.deepcopy(EX.ARMS["GENERAL_BIDI_V1"])
    for cap in (8, 100):
        try:
            PL.ROW_INSPECTION_CAP = cap; EX.ARMS["GENERAL_BIDI_V1"]["orders"] = ["original"]
            rec = EX.execute("GENERAL_BIDI_V1", mp, ep, os.path.join(OUT, "x_partial_view_%d" % cap), time.monotonic() + 5, {"budget_s": 5, "rules": [], "allow_binary64": False})
            nd0 = rec["plan"]["nodes"][0]; res["partial_view_cap_%d" % cap] = {"radix": nd0["radix"], "core_entries": nd0["core_entries"], "views_per_axis": nd0["views"], "cold_work_proxy": rec["plan"]["totals"]["cold_work_proxy"], "discovery_stop": rec["mechanisms"].get("discovery_stop"), "status": rec["status"]}
        finally:
            PL.ROW_INSPECTION_CAP = oldrow; EX.ARMS["GENERAL_BIDI_V1"] = olda
    # (5) demand EMPTY vs FULL serialization: both flatten to an empty list
    res["flatten_demand_note"] = "flatten_program emits [] for demand == 'FULL' AND for an empty proved demand list; kernel treats [] as FULL (kernel.cpp slot_of / forward)"
    return res


def main(out):
    global OUT; OUT = out; os.makedirs(out, exist_ok=True); t0 = time.monotonic(); rep = {"purpose": "review reproduction on the frozen source (not campaign evidence)", "git_head": os.popen("git -C %s rev-parse HEAD" % HERE).read().strip(), "kernel_binary_sha256": EX.sha_file(EX.LIB), "python": sys.version.split()[0], "utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}
    for name, fn in (("F1_binary64_streaming", f1), ("F2_untrusted_compiler", f2), ("F3_category_caps", f3), ("F4_fusion_price", f4), ("F5_record_loss", f5), ("extra_bounded_controls", extra)):
        t = time.monotonic()
        try:
            rep[name] = fn()
        except Exception:
            rep[name] = {"REPRO_SCRIPT_ERROR": traceback.format_exc()[-3000:]}
        rep[name + "_s"] = time.monotonic() - t; log(name, "%.2fs" % rep[name + "_s"])
    rep["total_s"] = time.monotonic() - t0; json.dump(rep, open(os.path.join(out, "REPRO_RESULTS.json"), "w"), indent=1, default=str); print(json.dumps(rep, indent=1, default=str))


if __name__ == "__main__":
    main(os.path.abspath(sys.argv[1]))
