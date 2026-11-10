"""REVIEW REPRODUCTION, SECOND PACKET (GENERAL_BIDI_FULL_ADVERSARIAL_REVIEW_R2, 9 Nov 2026) on the FROZEN source (a62625e6 set unchanged) and the frozen
Apple/ARM kernel binary. The delivered zip was truncated (no central directory; 1,812 of 9,726 members absent, among them the star fixtures, the
parse/hash-race probe and the malformed-input fixtures); those controls are RECONSTRUCTED here from the report's exact descriptions. Nothing here is
campaign evidence; every truth is independent (closed forms / exhaustive oracle). Process-local patches are restored.    python -m gbidi_review.repro_r2 OUT"""
from __future__ import annotations
import os, sys, json, time, traceback, subprocess, ctypes, ctypes.util, resource, copy
HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__))); sys.path.insert(0, HERE)
sys.set_int_max_str_digits(0)
from fractions import Fraction as Fr
from gbidi import executor as EX, plan as PL, pilot as PI
from ext import uai as U
OUT = None


def star(path, n):
    lines = ["MARKOV", str(n), " ".join(["2"] * n), str(n - 1)] + ["2 0 %d" % v for v in range(1, n)] + ["4 1 2 3 4"] * (n - 1)
    open(path, "w").write("\n".join(lines) + "\n"); open(path + ".evid", "w").write("0\n")
    Z = 3 ** (n - 1) + 7 ** (n - 1); truth = {0: [Fr(3 ** (n - 1), Z), Fr(7 ** (n - 1), Z)]}
    for v in range(1, n):
        truth[v] = [Fr(3 ** (n - 2) + 3 * 7 ** (n - 2), Z), Fr(2 * 3 ** (n - 2) + 4 * 7 ** (n - 2), Z)]
    return path, path + ".evid", truth


def contain(ivs, truth):
    return [{"var": int(v), "state": s, "lo": a, "hi": b} for v, row in ivs.items() for s, (a, b) in enumerate(row) if not (Fr(a) <= truth[int(v)][s] <= Fr(b))]


def r2_02_star():
    res = {}
    for n, budget in ((600, 20.0), (300, 2.0)):
        mp, ep, truth = star(os.path.join(OUT, "star_%d.uai" % n), n)
        for arm in ("GENERAL_BIDI_V1", "NATIVE_PLAIN_V1"):
            o = os.path.join(OUT, "star_%d_%s" % (n, arm)); t = time.monotonic(); cell = {"phases_s": {}}
            try:
                rec = EX.execute(arm, mp, ep, o, time.monotonic() + budget, {"budget_s": budget, "allow_binary64": False, "reference_fallback": True, "rules": list(PL.COMMON_RULES)}, phases=cell["phases_s"])
                st = EX.publish(o, mp, ep, rec, cell, time.monotonic() + budget)
                res["n%d_%s" % (n, arm)] = {"status": rec["status"], "publication": st, "point_check": (cell.get("point_check") or {}).get("status"), "order": rec["plan"]["order"]["name"], "candidates": [{k: c.get(k) for k in ("order", "state")} for c in rec["plan_candidates"]], "misses": len(contain(rec["certified_intervals"], truth)), "coordinates": sum(len(r) for r in rec["certified_intervals"].values()), "elapsed_s": time.monotonic() - t, "phases_s": cell["phases_s"]}
            except EX.Refuse as ex:
                res["n%d_%s" % (n, arm)] = {"refused": {"kind": ex.kind, "reason": ex.reason}, "elapsed_s": time.monotonic() - t, "budget_s": budget, "phases_s": cell["phases_s"]}
    return res


def r2_01_hash_race():
    """parse [1,3] then the file becomes [3,1] before task_binding reopens it"""
    mp = os.path.join(OUT, "race.uai"); ep = mp + ".evid"; open(mp, "w").write("MARKOV\n1\n2\n1\n1 0\n2 1 3\n"); open(ep, "w").write("0\n")
    orig = U.read_model
    def racing(path):
        m = orig(path); open(path, "w").write("MARKOV\n1\n2\n1\n1 0\n2 3 1\n"); return m          # the replacement happens AFTER parse, BEFORE the hash
    EX.U.read_model = racing; o = os.path.join(OUT, "race_out")
    try:
        rec = EX.execute("GENERAL_BIDI_V1", mp, ep, o, time.monotonic() + 5, {"budget_s": 5, "allow_binary64": False, "rules": []}); cell = {"phases_s": {}}
        st = EX.publish(o, mp, ep, rec, cell, time.monotonic() + 5)
        return {"record_intervals_x0": rec["certified_intervals"]["0"], "truth_of_named_file_x0": ["3/4", "1/4"], "record_raw_model_sha256": rec["task"]["raw_model_sha256"], "sha_of_file_now": EX.sha_file(mp), "bound_to_new_bytes": rec["task"]["raw_model_sha256"] == EX.sha_file(mp), "publication": st, "point_check": (cell.get("point_check") or {}).get("status"), "error_of_named_task": "1/2"}
    finally:
        EX.U.read_model = orig


def r2_04_stack(n_list=(100, 50000)):
    res = {}
    child = os.path.join(OUT, "deep_chain_child.py")
    open(child, "w").write('''import os,sys,time,json,resource
sys.path.insert(0,%r); sys.set_int_max_str_digits(0)
from gbidi import executor as E
n=int(sys.argv[1]); d=sys.argv[2]; os.makedirs(d,exist_ok=True); m=os.path.join(d,'model.uai')
open(m,'w').write('\\n'.join(['MARKOV',str(n),' '.join(['1']*n),str(n-1)]+['2 %%d %%d'%%(i,i+1) for i in range(n-1)]+['1 1']*(n-1))+'\\n'); open(m+'.evid','w').write('0\\n')
print(json.dumps({'stage':'begin','n':n,'stack_limit':resource.getrlimit(resource.RLIMIT_STACK)}),flush=True); t=time.monotonic()
try:
    r=E.execute('GENERAL_BIDI_V1',m,m+'.evid',os.path.join(d,'out'),time.monotonic()+12,{'budget_s':12,'allow_binary64':False,'reference_fallback':False,'rules':[]})
    print(json.dumps({'stage':'end','status':r.get('status'),'elapsed':time.monotonic()-t,'fused':r.get('plan',{}).get('totals',{}).get('fused')}),flush=True)
except Exception as e:
    print(json.dumps({'stage':'exception','type':type(e).__name__,'message':str(e)[:200],'elapsed':time.monotonic()-t}),flush=True)
''' % HERE)
    for n in n_list:
        t = time.monotonic()
        try:
            r = subprocess.run([sys.executable, child, str(n), os.path.join(OUT, "chain_%d" % n)], capture_output=True, text=True, timeout=60, cwd=HERE, env=dict(os.environ, PYTHONPATH=HERE))
            res["n%d" % n] = {"returncode": r.returncode, "signal": (-r.returncode if r.returncode < 0 else None), "stdout": r.stdout[-800:], "stderr": r.stderr[-400:], "wall_s": time.monotonic() - t}
        except subprocess.TimeoutExpired:
            res["n%d" % n] = {"timeout": True}
    return res


def r2_05_polling_and_alloc():
    res = {}; L = EX.Lib.get(); c = ctypes; n = 100000
    for source in (False, True):
        prog = ([1, 1, 0, n, n, 0, 1, 0, n, 1, 0, 0, 0, 1, -1, 1, 0, 1, 0] if source else [0, 1, 0, n, 0, 0, 1, -1, 1, 0, 1, 0]); nfac = n if source else 0
        a = (c.c_int64 * len(prog))(*prog); qs = (c.c_char_p * (nfac + 1))(*([b"1/1"] * (nfac + 1))); dbl = (c.c_double * (nfac + 1))(*([1.0] * (nfac + 1))); caps = (c.c_uint64 * 5)(2 << 30, 2 << 30, 1 << 30, 512 << 20, 512 << 20)
        h = L.gb_create(1, 53, a, len(prog), qs, dbl, nfac, 0, caps, 0.0); st = L.gb_forward(h); cnt = (c.c_uint64 * 16)(); L.gb_counters(h, cnt); L.gb_destroy(h)
        res["source_present_%s" % source] = {"remaining_s_at_create": 0.0, "forward_status": EX.STOP_NAMES.get(st), "rows": int(cnt[0]), "adds": int(cnt[2]), "polls": int(cnt[10])}
    res["alloc_note"] = "RLIMIT_AS is not enforced by macOS for malloc; the std::bad_alloc control is verified by source inspection (no try/catch at any extern C entry) and will be covered by a native fault-injection hook after the repair"
    return res


def r2_06_env():
    res = {}
    libc = ctypes.CDLL(None); libc.fegetround.restype = ctypes.c_int; libc.fesetround.argtypes = [ctypes.c_int]; libc.fesetround.restype = ctypes.c_int
    FE_TONEAREST = 0; FE_UPWARD = 0x400000 if sys.platform == "darwin" and os.uname().machine == "arm64" else 0x800      # arm64: FPCR RMode bits; x86: 0x800
    a = Fr(1) + Fr(1, 2 ** 27); tok = lambda q: "%s" % (q.numerator / Fr(q.denominator)) if False else str(q.numerator) + "/" + str(q.denominator)
    from decimal import Decimal, localcontext
    def dec(q):
        with localcontext() as ctx:
            ctx.prec = 100; return str(Decimal(q.numerator) / Decimal(q.denominator))
    tab = [a, a, 3 * a, 2 * a]; mp = os.path.join(OUT, "rn_pair.uai"); open(mp, "w").write("MARKOV\n2\n2 2\n2\n2 0 1\n2 0 1\n" + "\n".join("4 " + " ".join(map(dec, tab)) for _ in range(2)) + "\n"); open(mp + ".evid", "w").write("0\n")
    exact = {0: [Fr(2, 15), Fr(13, 15)], 1: [Fr(10, 15), Fr(5, 15)]}; old = libc.fegetround()
    try:
        for name, mode in (("nearest", FE_TONEAREST), ("upward", FE_UPWARD)):
            ok = libc.fesetround(mode); before = libc.fegetround(); x = float(a); prod = x * x
            rec = EX.execute("NATIVE_PLAIN_V1", mp, mp + ".evid", os.path.join(OUT, "rn_" + name), time.monotonic() + 5, {"budget_s": 5, "allow_binary64": True, "reference_fallback": False})
            res[name] = {"fesetround_rc": ok, "mode_before": before, "mode_after": libc.fegetround(), "status": rec["status"], "route": rec.get("route"), "truth_contained": not contain(rec["certified_intervals"], exact), "sample_a2_relative_error_exceeds_u": abs(Fr(prod) - a * a) / (a * a) > Fr(1, 2 ** 53), "Z_hex": rec.get("values_hex")}
    finally:
        libc.fesetround(old)
    # MPFR exponent environment through the SAME library the kernel links (Homebrew libmpfr)
    try:
        M = ctypes.CDLL("/opt/homebrew/lib/libmpfr.dylib")
        for f in ("mpfr_get_emin", "mpfr_get_emax"):
            getattr(M, f).restype = ctypes.c_long
        for f in ("mpfr_set_emin", "mpfr_set_emax"):
            getattr(M, f).argtypes = [ctypes.c_long]; getattr(M, f).restype = ctypes.c_int
        for f in ("mpfr_overflow_p", "mpfr_underflow_p", "mpfr_nanflag_p"):
            getattr(M, f).restype = ctypes.c_int
        old_e = (M.mpfr_get_emin(), M.mpfr_get_emax()); same_lib = (EX.Lib.get().gb_mpfr_emax() == old_e[1])
        def probe(name, toks, emin=None, emax=None):
            M.mpfr_set_emin(old_e[0]); M.mpfr_set_emax(old_e[1]); M.mpfr_clear_flags()
            if emin is not None: M.mpfr_set_emin(emin)
            if emax is not None: M.mpfr_set_emax(emax)
            p = os.path.join(OUT, name + ".uai"); open(p, "w").write("MARKOV\n2\n2 2\n2\n2 0 1\n2 0 1\n4 " + " ".join(toks) + "\n4 " + " ".join(toks) + "\n"); open(p + ".evid", "w").write("0\n")
            r = {"kernel_emin": EX.Lib.get().gb_mpfr_emin(), "kernel_emax": EX.Lib.get().gb_mpfr_emax()}
            try:
                rec = EX.execute("NATIVE_PLAIN_V1", p, p + ".evid", os.path.join(OUT, name + "_out"), time.monotonic() + 5, {"budget_s": 5, "allow_binary64": False, "reference_fallback": False}); r.update(status=rec.get("status"), intervals=rec.get("certified_intervals"), attempts=[(x.get("precision"), x.get("outcome")) for x in rec.get("attempts", [])])
            except Exception as ex:
                r.update(exception_type=type(ex).__name__, exception=str(ex)[:160], kind=getattr(ex, "kind", None))
            r.update(overflow_flag=bool(M.mpfr_overflow_p()), underflow_flag=bool(M.mpfr_underflow_p())); return r
        try:
            res["mpfr_same_library_instance"] = same_lib
            res["mpfr_baseline"] = probe("mpfr_baseline", ["100", "100", "300", "200"])
            res["mpfr_emax_5"] = probe("mpfr_overflow_env", ["100", "100", "300", "200"], emax=5)
            res["mpfr_emin_-5"] = probe("mpfr_underflow_env", ["0.0000000001", "0.0000000001", "0.0000000003", "0.0000000002"], emin=-5)
        finally:
            M.mpfr_set_emin(old_e[0]); M.mpfr_set_emax(old_e[1]); M.mpfr_clear_flags()
    except OSError as ex:
        res["mpfr_env"] = {"skipped": str(ex)}
    return res


def r2_07_malformed():
    res = {}
    cases = {"negative_factor_count": "MARKOV\n1\n2\n-1\n", "negative_scope_arity": "MARKOV\n1\n2\n1\n-1\n1 5\n", "duplicate_scope_rank_one": "MARKOV\n1\n2\n1\n2 0 0\n4 1 2 2 4\n", "duplicate_scope_nonseparable": "MARKOV\n1\n2\n1\n2 0 0\n4 1 2 3 5\n", "zero_cardinality": "MARKOV\n1\n0\n0\n"}
    for name, text in cases.items():
        p = os.path.join(OUT, name + ".uai"); open(p, "w").write(text); open(p + ".evid", "w").write("0\n"); o = os.path.join(OUT, name + "_out")
        try:
            rec = EX.execute("GENERAL_BIDI_V1", p, p + ".evid", o, time.monotonic() + 5, {"budget_s": 5, "allow_binary64": False}); cell = {"phases_s": {}}
            st = EX.publish(o, p, p + ".evid", rec, cell, time.monotonic() + 5) if rec["status"] == "INTERVALS_OK" else None
            res[name] = {"execute": rec["status"], "intervals": rec.get("certified_intervals"), "publication": st, "point_check": (cell.get("point_check") or {}).get("status")}
        except Exception as ex:
            res[name] = {"exception_type": type(ex).__name__, "message": str(ex)[:200], "kind": getattr(ex, "kind", None)}
    return res


def r2_08_supervisor_orphan():
    q = os.path.join(OUT, "orphan"); os.makedirs(q, exist_ok=True); pidfile = os.path.join(q, "descendant_pid.txt"); leader = os.path.join(q, "leader.py")
    open(leader, "w").write("import subprocess,sys,time\np=subprocess.Popen([sys.executable,'-c','import time; time.sleep(3)'])\nopen(sys.argv[1],'w').write(str(p.pid))\ntime.sleep(0.10)\n")
    cmd = [sys.executable, "-m", "adp.census.supervise", "--ledger", os.path.join(q, "ledger.jsonl"), "--scope", "review_control", "--job", "leader-exits-with-live-child", "--timeout", "1", "--stdout", os.path.join(q, "child.log"), "--stderr", os.path.join(q, "child.log"), "--", sys.executable, leader, pidfile]
    s = subprocess.run(cmd, capture_output=True, text=True, timeout=15, cwd=HERE, env=dict(os.environ, PYTHONPATH=HERE)); import psutil, signal
    pid = int(open(pidfile).read()); alive = psutil.pid_exists(pid) and psutil.Process(pid).status() != psutil.STATUS_ZOMBIE
    rc = [json.loads(x) for x in open(os.path.join(q, "ledger.jsonl")) if json.loads(x)["kind"] == "RECEIPT"][-1]
    same_group = (os.getpgid(pid) == rc["pgid"]) if alive else None
    if alive:
        os.kill(pid, signal.SIGKILL)
    return {"supervisor_rc": s.returncode, "receipt_outcome": rc["outcome"], "cleanup_unresolved": rc["cleanup_unresolved"], "descendant_running_after_receipt": alive, "same_recorded_process_group": same_group, "cleanup": "SIGKILL to the recorded synthetic descendant only"}


def r2_09_identity():
    from gbidi_closeout import report as R
    D = os.path.dirname(OUT); man = json.load(open(os.path.join(D, "GB_MANIFEST.json"))); q = os.path.join(OUT, "identity"); os.makedirs(q, exist_ok=True)
    mut = copy.deepcopy(man); first, second = mut["cells"][:2]; second["out_dir"] = first["out_dir"]; second["cell_id"] = first["cell_id"]; second["task_id"] = "not-the-task-id"; first["task_id"] = "also-not-a-task-id"
    json.dump(mut, open(os.path.join(q, "GB_MANIFEST.json"), "w")); od = os.path.join(q, first["out_dir"]); os.makedirs(od, exist_ok=True)
    json.dump({"status": "CERTIFIED", "arm": "OTHER_ARM", "task": {"raw_model_sha256": "other"}, "model": "unrelated", "deadline_s": 999, "complete_response_s": 0.001, "within_deadline": True}, open(os.path.join(od, "cell.json"), "w"))
    rows = R.cells_ledger(q, mut)
    job = rows[0]["job"]; open(os.path.join(q, "GB_LEDGER.jsonl"), "w").write(json.dumps({"kind": "RECEIPT", "job": job, "jid": "synthetic-failed", "start_utc": mut["frozen_utc"], "outcome": "LAUNCH_FAILED", "wall_s": 0.002, "returncode": None, "cleanup_unresolved": False}) + "\n")
    rows2 = R.cells_ledger(q, mut)
    return {"reconcile_order_passes_with_forged_ids_and_aliased_dirs": PI.reconcile_order(q), "two_planned_arms": [first["arm"], second["arm"]], "both_rows_status": [r["status"] for r in rows[:2]], "both_rows_resolution": [r["resolution"] for r in rows[:2]], "after_LAUNCH_FAILED_receipt": {"status": rows2[0]["status"], "resolution": rows2[0]["resolution"], "would_count_as_certified": rows2[0]["status"] in R.CERT}}


def r2_03_proved_noop():
    D = os.path.dirname(OUT); insp = json.load(open(os.path.join(D, "PANEL_INSPECTION.json")))["rows"]; out = []
    for r in insp:
        g = r.get("GENERAL_BIDI_V1") or {}
        if not isinstance(g, dict) or "totals" not in g:
            continue
        m = g["mechanisms"]; big = g.get("largest_core_entries", 0)
        if big > PL.ROW_INSPECTION_CAP and m["demand"]["entries_skipped_by_demand"] == 0 and not m.get("discovery_stop"):
            out.append({"case": r["case"], "largest_core_entries": big, "discovery_stop": m.get("discovery_stop"), "closeout_typed_rule_would_say": "PROVED_NO_OP", "actual": "largest bag > inspection allowance: NOT scanned"})
    return {"saved_plans_misclassified_as_PROVED_NO_OP": out}


def r2_10_fusion_price_and_counters():
    return {"note": "F4 witness already reproduced in REPRO_RESULTS.json (51/16 vs 47/14 mults/adds at equal proxy 52); counter semantics are a source-derived finding (kernel.cpp:70,102-219) and need no additional execution"}


def main(out):
    global OUT; OUT = out; os.makedirs(out, exist_ok=True); t0 = time.monotonic()
    rep = {"purpose": "second-packet review reproduction on the frozen source (not campaign evidence)", "git_head": os.popen("git -C %s rev-parse HEAD" % HERE).read().strip(), "kernel_binary_sha256": EX.sha_file(EX.LIB), "python": sys.version.split()[0], "utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "packet_note": "R2 zip truncated (no central directory; 1,812/9,726 members missing incl. star fixtures, source_snapshot probe, source_semantics fixtures); controls reconstructed from REPORT.txt / component notes"}
    for name, fn in (("R2_01_hash_race", r2_01_hash_race), ("R2_02_star", r2_02_star), ("R2_03_proved_noop", r2_03_proved_noop), ("R2_04_stack", r2_04_stack), ("R2_05_polling_alloc", r2_05_polling_and_alloc), ("R2_06_environment", r2_06_env), ("R2_07_malformed", r2_07_malformed), ("R2_08_supervisor_orphan", r2_08_supervisor_orphan), ("R2_09_identity", r2_09_identity), ("R2_10_counters", r2_10_fusion_price_and_counters)):
        t = time.monotonic()
        try:
            rep[name] = fn()
        except Exception:
            rep[name] = {"REPRO_SCRIPT_ERROR": traceback.format_exc()[-3000:]}
        rep[name + "_s"] = time.monotonic() - t; print(name, "%.2fs" % rep[name + "_s"], flush=True)
    rep["total_s"] = time.monotonic() - t0; json.dump(rep, open(os.path.join(out, "REPRO_R2_RESULTS.json"), "w"), indent=1, default=str); print(json.dumps(rep, indent=1, default=str))


if __name__ == "__main__":
    main(os.path.abspath(sys.argv[1]))
