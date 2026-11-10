"""REVIEW REPRODUCTION, THIRD PACKET (GENERAL_BIDI_V2_REPAIR_ADVERSARIAL_REVIEW_2026-11-10) on the V2 source at 3fcb5141 BEFORE the closeout changes.
Independent truths; process-local patches restored.    python -m gbidi_review.repro_r3 OUT"""
from __future__ import annotations
import os, sys, json, time, copy, traceback, subprocess, ctypes, signal
HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__))); sys.path.insert(0, HERE)
sys.set_int_max_str_digits(0)
from fractions import Fraction as Fr
from gbidi import executor as EX, plan as PL, pilot as PI
from gbidi_closeout import report as R
from adp import source as SRC
from ext import uai as U
OUT = None


def w(path, text):
    open(path, "w").write(text); open(path + ".evid", "w").write("0\n"); return path, path + ".evid"


def v1_substitution():
    mp, ep = w(os.path.join(OUT, "two_factors.uai"), "MARKOV\n2\n2 2\n2\n2 0 1\n2 0 1\n4\n1 2 3 4\n4\n1 1 1 2\n"); truth = {"0": [Fr(3, 14), Fr(11, 14)], "1": [Fr(2, 7), Fr(5, 7)]}; orig = PL.plan; res = {}
    for mode in ("unchanged", "replace_factor_table", "replace_scale_zero", "mutate_R_in_place"):
        def altered(Rr, *a, mode=mode, **k):
            P, T = orig(Rr, *a, **k)
            if mode == "replace_factor_table":
                fid = sorted(P.fac)[1]; f = copy.deepcopy(P.fac[fid]); f.table = [Fr(1)] * 4; P.fac = dict(P.fac); P.fac[fid] = f
            elif mode == "replace_scale_zero":
                P.R = copy.deepcopy(P.R); P.R.scale = Fr(0)
            elif mode == "mutate_R_in_place":
                Rr.factors[1].table[:] = [Fr(1)] * 4                                              # a compiler bug mutating the trusted object itself
            return P, T
        PL.plan = altered
        try:
            rec = EX.execute("GENERAL_BIDI_V2", mp, ep, os.path.join(OUT, "sub_" + mode), time.monotonic() + 10, {"budget_s": 10, "allow_binary64": False}); row = {"status": rec["status"], "validation": rec.get("plan_validation", {}).get("status"), "certifying": rec.get("certifying")}
            if rec["status"] == "INTERVALS_OK":
                cell = {"phases_s": {}}; row["publication"] = EX.publish(os.path.join(OUT, "sub_" + mode), mp, ep, rec, cell, time.monotonic() + 10); row["point_check"] = (cell.get("point_check") or {}).get("status"); row["truth_contained"] = all(Fr(a) <= truth[v][s] <= Fr(b) for v in truth for s, (a, b) in enumerate(rec["certified_intervals"][v])); row["intervals"] = rec["certified_intervals"]
            res[mode] = row
        except Exception as ex:
            res[mode] = {"exception": type(ex).__name__, "kind": getattr(ex, "kind", None), "reason": str(ex)[:160]}
        finally:
            PL.plan = orig
    return res


def v2_crossed_zero():
    mp, ep = w(os.path.join(OUT, "crossed.uai"), "MARKOV\n2\n2 3\n2\n2 0 1\n2 0 1\n6\n0 1 1 0 2 2\n6\n1 0 3 2 0 4\n"); res = {}
    for rules in ([], list(PL.COMMON_RULES)):
        try:
            rec = EX.execute("GENERAL_BIDI_V2", mp, ep, os.path.join(OUT, "crossed_%d" % len(rules)), time.monotonic() + 10, {"budget_s": 10, "allow_binary64": False, "rules": rules}); res["rules_%d" % len(rules)] = {"status": rec["status"], "intervals": rec.get("certified_intervals")}
        except EX.Refuse as ex:
            res["rules_%d" % len(rules)] = {"REFUSED": ex.kind, "reason": ex.reason[:160]}
    return res


def p1_clock():
    res = {}
    for n, expired in ((40, True), (65, True), (65, False), (80, True)):
        p = os.path.join(OUT, "star_%d.uai" % n); open(p, "w").write("\n".join(["MARKOV", str(n), " ".join(["2"] * n), str(n - 1)] + ["2 0 %d" % i for i in range(1, n)] + ["4 1 2 3 4"] * (n - 1)) + "\n")
        m = U.read_model(p); Rr = SRC.Reduced(EX._ModelAdapter(m), {}); Rr.reduce([], deadline=None)
        try:
            kw = {"hard_deadline": time.monotonic() + 30} if "hard_deadline" in PL.plan.__code__.co_varnames else {}
            P, table = PL.plan(Rr, dict(EX.ARMS["GENERAL_BIDI_V2"], bytes_per_entry=96), deadline=(time.monotonic() - 1) if expired else None, **kw); res["n%d_expired%s" % (n, expired)] = {"status": "COMPLETE", "order": P.order_info["name"], "updates": P.order_info.get("updates")}
        except PL.PlanStop as ex:
            res["n%d_expired%s" % (n, expired)] = {"status": ex.kind, "reason": ex.reason[:160]}
    return res


def h1_h2_h4_harness():
    res = {}
    for planned, produced in (("ADP_REPAIRED", "AGGREGATE_DP_V1"), ("EXACT_LIBDAI", "EXACT")):
        d = os.path.join(OUT, "arm_" + planned); od = os.path.join(d, "cells", "a"); os.makedirs(od, exist_ok=True)
        c = {"index": 0, "stage": "primary_breadth", "arm": planned, "case": "X", "budget_s": 20.0, "kind": "primary", "task_id": "t", "cell_id": "c1", "out_dir": "cells/a", "max_permitted_charge_s": 26.0}
        man = {"frozen_utc": "2026-11-10T00:00:00Z", "cases": {"X": {"family": "F", "raw_model_sha256": "rm", "raw_evidence_sha256": "re", "variables": 2, "model_path": "m.uai"}}, "cells": [c], "common_rules": list(PL.COMMON_RULES)}
        json.dump({"arm": produced, "status": "CERTIFIED" if planned == "ADP_REPAIRED" else "COMPLETE", "task": {"raw_model_sha256": "rm", "raw_evidence_sha256": "re"}, "complete_response_s": .2, "within_deadline": True}, open(os.path.join(od, "cell.json"), "w"))
        open(os.path.join(d, "GB_LEDGER.jsonl"), "w").write(json.dumps({"kind": "RECEIPT", "job": "cell:000:primary_breadth:X:%s:20s:c1" % planned, "jid": "j", "start_utc": "2026-11-10T00:00:01Z", "outcome": "COMPLETED", "wall_s": .5, "returncode": 0, "cleanup_unresolved": False, "group_empty_at_receipt": True}) + "\n")
        row = R.cells_ledger(d, man)[0]; res["H1_" + planned] = {"status": row["status"], "resolution": row["resolution"], "accepted": row["accepted"], "reasons": row.get("reasons"), "note": "BEFORE: UNBOUND_RECORD (no adapter); AFTER: not accepted with the explicit reason 'adapter.json missing' -- the real producers pass through gbidi.arm_adapter (see tests H1 end-to-end + review_after_r3 adapter run)"}
    d = os.path.join(OUT, "loose"); od = os.path.join(d, "cells", "a"); os.makedirs(od, exist_ok=True)
    c = {"index": 0, "stage": "primary_breadth", "arm": "NATIVE_PLAIN_V2", "case": "X", "budget_s": 20.0, "kind": "primary", "task_id": "current_task", "cell_id": "current_cell", "out_dir": "cells/a", "max_permitted_charge_s": 26.0}
    man = {"frozen_utc": "2026-11-10T00:00:00Z", "cases": {"X": {"family": "F", "raw_model_sha256": "rm", "raw_evidence_sha256": "re", "variables": 2, "model_path": "m.uai"}}, "cells": [c], "common_rules": list(PL.COMMON_RULES)}
    json.dump({"arm": "NATIVE_PLAIN_V2", "status": "CERTIFIED", "deadline_s": 120.0, "config": {"rules": []}, "task": {"raw_model_sha256": "rm", "raw_evidence_sha256": "re", "queries": [999], "queries_sha256": "wrong"}, "complete_response_s": 99.0, "complete_response_from_launch_s": 99.1, "within_deadline": True}, open(os.path.join(od, "cell.json"), "w"))
    open(os.path.join(d, "GB_LEDGER.jsonl"), "w").write(json.dumps({"kind": "RECEIPT", "job": "cell:000:primary_breadth:X:NATIVE_PLAIN_V2:20s:current_cell", "jid": "receipt_without_start", "start_utc": "2026-11-10T00:00:01Z", "outcome": "COMPLETED", "wall_s": .5, "returncode": 0, "cleanup_unresolved": False, "group_empty_at_receipt": True}) + "\n")
    row = R.cells_ledger(d, man)[0]; res["H2_stale_120s_for_20s"] = {"status": row["status"], "resolution": row["resolution"], "accepted": row["accepted"], "reasons": row.get("reasons")}
    d = os.path.join(OUT, "remainders"); os.makedirs(d, exist_ok=True); rows = []
    for jid, scope, job, wall, beg, end in (("o1", "stage_outer", "stage_runner:primary_breadth", 10.0, 0, 10), ("c1", "matrix_primary_breadth", "cell:one", 5.0, 1, 6), ("o2", "stage_outer", "stage_runner:primary_breadth", 8.0, 20, 28), ("c2", "matrix_primary_breadth", "cell:two", 4.0, 21, 25)):
        b = "2026-11-10T00:00:%02dZ" % beg; e = "2026-11-10T00:00:%02dZ" % end; rows += [{"kind": "START", "jid": jid, "scope": scope, "job": job, "start_utc": b, "max_permitted_charge_s": 30}, {"kind": "RECEIPT", "jid": jid, "scope": scope, "job": job, "start_utc": b, "end_utc": e, "wall_s": wall, "outcome": "COMPLETED", "cleanup_unresolved": False}]
    open(os.path.join(d, "GB_LEDGER.jsonl"), "w").write("".join(json.dumps(x) + "\n" for x in rows))
    B = R.budget(d, {"frozen_utc": "2026-11-10T00:00:00Z", "ceiling_s": 100}, []); res["H4_repeated_stage_unlinked"] = {"expected": 18.0, "total_charged_s": B["total_charged_s"], "live_guard": PI.charged(d)[0], "note": "children WITHOUT parent_jid (the reviewer's fixture): each outer attempt's full wall is charged as remainder (no child can be attributed) = 10 + 8 + 5 + 4 = 27, conservative; with parent_jid linkage (production receipts) the total is exactly 18 (test_H4_*)"}
    for r_ in rows:
        if r_["jid"] in ("c1",): r_["parent_jid"] = "o1"
        if r_["jid"] in ("c2",): r_["parent_jid"] = "o2"
    open(os.path.join(d, "GB_LEDGER.jsonl"), "w").write("".join(json.dumps(x) + "\n" for x in rows)); B = R.budget(d, {"frozen_utc": "2026-11-10T00:00:00Z", "ceiling_s": 100}, []); res["H4_repeated_stage_linked"] = {"expected": 18.0, "total_charged_s": B["total_charged_s"], "live_guard": PI.charged(d)[0]}
    return res


def h3_nested():
    import psutil
    d = os.path.join(OUT, "nested"); os.makedirs(d, exist_ok=True); leaf = os.path.join(d, "leaf.json"); outer_led = os.path.join(d, "outer.jsonl"); inner_led = os.path.join(d, "inner.jsonl")
    for p in (leaf, outer_led, inner_led):
        if os.path.exists(p):
            os.remove(p)
    leafcode = "import os,time,json;open(%r,'w').write(json.dumps({'pid':os.getpid(),'pgid':os.getpgrp()}));time.sleep(3)" % leaf
    inner = [sys.executable, "-m", "gbidi.supervise", "--ledger", inner_led, "--scope", "inner", "--job", "inner", "--timeout", "1", "--", sys.executable, "-c", leafcode]
    leadercode = "import subprocess,time,os;subprocess.Popen(%r,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL);p=%r\nt=time.monotonic()\nwhile not os.path.exists(p) and time.monotonic()-t<1:time.sleep(.01)\ntime.sleep(.1)\n" % (inner, leaf)
    cmd = [sys.executable, "-m", "gbidi.supervise", "--ledger", outer_led, "--scope", "stage_outer_test", "--job", "stage_runner:test", "--timeout", "2", "--", sys.executable, "-c", leadercode]
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, env=dict(os.environ, PYTHONPATH=HERE), cwd=HERE); so, se = proc.communicate(timeout=10)
    ident = json.load(open(leaf)); pid = ident["pid"]
    def live(p):
        try:
            return psutil.Process(p).is_running() and psutil.Process(p).status() != psutil.STATUS_ZOMBIE
        except psutil.Error:
            return False
    rc = [json.loads(x) for x in open(outer_led) if json.loads(x)["kind"] == "RECEIPT"][-1]; alive = live(pid)
    res = {"outer_outcome": rc["outcome"], "group_empty_at_receipt": rc["group_empty_at_receipt"], "cleanup_unresolved": rc["cleanup_unresolved"], "leaf_alive_after_outer_receipt": alive, "leaf_group_differs": ident["pgid"] != rc["pgid"], "inner_records": [json.loads(x)["kind"] for x in open(inner_led)]}
    if alive:
        os.kill(pid, signal.SIGKILL); res["cleanup"] = "SIGKILL to the recorded synthetic leaf only"
    return res


def rt_caps_poll():
    res = {}; mp, ep = w(os.path.join(OUT, "tiny.uai"), "MARKOV\n2\n2 2\n2\n2 0 1\n1 0\n4\n1 2 3 4\n2\n2 1\n"); old = dict(PL.CAPS)
    for name, ch in (("index_cap_1", {"source_ir_maps_output": 1}), ("all_caps_1", {k: 1 for k in PL.CAPS})):
        PL.CAPS.clear(); PL.CAPS.update(old); PL.CAPS.update(ch)
        try:
            r = EX.execute("NATIVE_PLAIN_V2", mp, ep, os.path.join(OUT, name), time.monotonic() + 5, {"budget_s": 5, "allow_binary64": False}); res[name] = {"status": r["status"], "route": r.get("route"), "stop": r.get("stop"), "used_index_bytes": (r["attempts"][-1].get("counters") or {}).get("used_index_bytes") if r["attempts"] else None}
        except EX.Refuse as ex:
            res[name] = {"REFUSED": ex.kind}
        finally:
            PL.CAPS.clear(); PL.CAPS.update(old)
    L = EX.Lib.get(); c = ctypes; nf = 3000; prog = [nf]
    for i in range(nf):
        prog += [1, 0, 1, 1, i]
    prog += [1, 0, 1, nf]
    for i in range(nf):
        prog += [0, i]
    prog += [0, 1, -1, 1, 0, 0, 1, 0]
    a = (c.c_int64 * len(prog))(*prog); qs = (c.c_char_p * (nf + 1))(*([b"1/1"] * (nf + 1))); d = (c.c_double * (nf + 1))(*([1.0] * (nf + 1))); caps = (c.c_uint64 * 5)(*([1 << 28] * 5)); err = c.c_int()
    h = L.gb_create(1, 53, a, len(prog), qs, d, nf, 0, caps, 0.0, c.byref(err)); st = L.gb_forward(h); cnt = EX._counters(L, h); L.gb_destroy(h)
    res["poll_3000_unaries"] = {"forward": EX.STOP_NAMES.get(st), "polls": cnt["polls"], "lookups_before_first_poll": cnt["lookups"], "charged_units_at_first_poll_measured": nf + 1 + 1 + cnt["lookups"], "advertised": 4096, "note": "conversion units (nf+1) + frame push (1) + table loads before the first poll; V2-before: loads 3000 -> 6003 units"}
    return res


def main(out):
    global OUT; OUT = out; os.makedirs(out, exist_ok=True); rep = {"purpose": "third-packet reproduction on the V2 source BEFORE the closeout", "git_head": os.popen("git -C %s rev-parse HEAD" % HERE).read().strip(), "kernel": EX.sha_file(EX.LIB), "utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}
    for name, fn in (("V2_V1_source_substitution", v1_substitution), ("V2_V2_crossed_zero_rows", v2_crossed_zero), ("V2_P1_mandatory_clock", p1_clock), ("H1_H2_H4_harness", h1_h2_h4_harness), ("H3_nested_supervisor", h3_nested), ("RT_caps_poll", rt_caps_poll)):
        t = time.monotonic()
        try:
            rep[name] = fn()
        except Exception:
            rep[name] = {"REPRO_SCRIPT_ERROR": traceback.format_exc()[-2500:]}
        rep[name + "_s"] = time.monotonic() - t; print(name, "%.2fs" % rep[name + "_s"], flush=True)
    json.dump(rep, open(os.path.join(out, "REPRO_R3_RESULTS.json"), "w"), indent=1, default=str); print(json.dumps({k: v for k, v in rep.items() if not k.endswith("_s")}, indent=1, default=str)[:7000])


if __name__ == "__main__":
    main(os.path.abspath(sys.argv[1]))
