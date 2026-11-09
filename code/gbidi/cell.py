"""One GENERAL_BIDI_V1-family cell in a FRESH process (timer starts before imports):
    python -m gbidi.cell ARM MODEL.uai EVID.uai.evid OUT_DIR DEADLINE_S CONFIG(json path or literal)
ARM in gbidi.executor.ARMS. Status vocabulary follows adp.cell: CERTIFIED / LATE_OUTPUT / RESOURCE_STOP / NUMERIC_UNRESOLVED / ROUTE_LIMITATION /
CHECK_FAILED / INCONSISTENT_EVIDENCE_CERTIFIED / FAULT. Records complete_response_s (in-process), complete_response_from_launch_s when the launcher
passes GBIDI_LAUNCH_MONO, t_first_complete_output_s (first checked delivery)."""
from __future__ import annotations
import os, sys, json, time, resource, threading
T_START = time.monotonic()
sys.set_int_max_str_digits(0)
HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__))); sys.path.insert(0, HERE)
from gbidi import executor as EX

DEFAULTS = {"allow_binary64": True, "reference_fallback": True}


def now():
    return time.monotonic() - T_START


def atomic_write(path, data):
    tmp = path + ".tmp"
    with open(tmp, "w") as f:
        f.write(data); f.flush(); os.fsync(f.fileno())
    os.replace(tmp, path)


def run_cell(arm, mp, ep, out, deadline, cfg, rec):
    T_DL = T_START + deadline; rec["phases_s"]["startup_imports"] = now(); ph = {}; t = now(); cfg = dict(cfg, budget_s=deadline)
    try:
        r = EX.execute(arm, mp, ep, out, T_DL, cfg, phases=ph)
    except EX.Refuse as ex:
        rec["phases_s"].update(ph); rec["status"] = "RESOURCE_STOP" if ex.kind == "RESOURCE_STOP" else ex.kind; rec["reason"] = ex.reason; rec["stop"] = {"phase": "executor", "kind": ex.kind, "detail": ex.reason}; return
    rec["phases_s"].update(ph); rec["executor_wall_s"] = now() - t
    for k in ("task", "reductions", "plan", "plan_candidates", "mechanisms", "backend", "binary64_admission", "attempts", "route", "precision", "max_width", "reference_fallback"):
        if k in r:
            rec[k] = r[k]
    if r["status"] == "ZERO_EVIDENCE_PROVED":
        rec["status"] = "INCONSISTENT_EVIDENCE_CERTIFIED"; rec["reason"] = r.get("reason"); return
    t = now(); st = EX.publish(out, mp, ep, r, rec, T_DL); rec["phases_s"]["publish"] = now() - t; rec["status"] = st
    if st == "CERTIFIED":
        rec["t_first_complete_output_s"] = now()


def main():
    arm, mp, ep, out, deadline_s, cfgp = sys.argv[1:7]; deadline = float(deadline_s); os.makedirs(out, exist_ok=True)
    cfg = dict(DEFAULTS); cfg.update(json.load(open(cfgp)) if os.path.exists(cfgp) else json.loads(cfgp))
    rec = {"arm": arm, "model": mp, "evidence": ep, "deadline_s": deadline, "config": cfg, "phases_s": {}, "status": None, "pid": os.getpid(), "started_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}
    stop = [False]
    def flush():
        while not stop[0]:
            try:
                atomic_write(os.path.join(out, "progress.json"), json.dumps({"t_s": now(), "phases_s": rec.get("phases_s"), "status": rec.get("status")}, default=str))
            except Exception:
                pass
            time.sleep(0.5)
    threading.Thread(target=flush, daemon=True).start()
    try:
        if arm not in EX.ARMS:
            rec["status"] = "UNAVAILABLE"; rec["reason"] = "unknown arm"
        else:
            run_cell(arm, mp, ep, out, deadline, cfg, rec)
    except Exception as ex:
        import traceback
        rec["status"] = "FAULT"; rec["reason"] = "%s: %s" % (type(ex).__name__, ex); rec["traceback"] = traceback.format_exc()[-2500:]
    stop[0] = True
    rec["complete_response_s"] = now(); rec["within_deadline"] = rec["complete_response_s"] <= deadline
    lm = os.environ.get("GBIDI_LAUNCH_MONO")
    if lm:
        try:
            rec["complete_response_from_launch_s"] = time.monotonic() - float(lm); rec["t_start_after_launch_s"] = T_START - float(lm); rec["within_deadline_from_launch"] = rec["complete_response_from_launch_s"] <= deadline
        except ValueError:
            pass
    if rec["status"] in ("CERTIFIED", "CERTIFIED_TOO_WIDE", "CERTIFIED_WIDTH_ONLY_POINT_INFEASIBLE", "INCONSISTENT_EVIDENCE_CERTIFIED") and not rec["within_deadline"]:
        rec["censored"] = True; rec["status_before_deadline_check"] = rec["status"]; rec["status"] = "LATE_OUTPUT"
    rec["maxrss_self_bytes"] = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss; rec["maxrss_children_bytes"] = resource.getrusage(resource.RUSAGE_CHILDREN).ru_maxrss
    atomic_write(os.path.join(out, "cell.json"), json.dumps(rec, indent=1, default=str))
    print(json.dumps({"arm": arm, "status": rec["status"], "complete_response_s": round(rec["complete_response_s"], 3)}))


if __name__ == "__main__":
    main()
