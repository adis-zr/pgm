"""One GENERAL_BIDI_COMPLETE_V3-family cell in a FRESH process (timer starts before imports):
    python -m gbidi3.cell ARM MODEL.uai EVID.uai.evid OUT_DIR DEADLINE_S CONFIG(json path or literal) [EXPECTED_TASK_JSON]
ARM in gbidi3.planner.ARMS. Status vocabulary: CERTIFIED / LATE_OUTPUT / RESOURCE_STOP / NUMERIC_UNRESOLVED / NUMERIC_RANGE / ROUTE_LIMITATION / REJECTED /
INVALID_INPUT / CHECK_FAILED / INCONSISTENT_EVIDENCE_CERTIFIED / FAULT / TASK_MISMATCH / CERTIFIED_TOO_WIDE / CERTIFIED_WIDTH_ONLY_POINT_INFEASIBLE /
CERTIFIED_TOO_WIDE_DELIVERED. EXPECTED_TASK_JSON (raw hashes + cell_id from the frozen manifest) is compared with the snapshot BEFORE execution. The progress
thread writes progress.json every 0.5 s with the executor's live kernel snapshot; the diagnostic record survives every typed stop and is copied into cell.json
under `diagnostic` (NONCERTIFYING). LATE_OUTPUT is classified against the LAUNCH-relative clock when the launcher passes GBIDI_LAUNCH_MONO."""
from __future__ import annotations
import os, sys, json, time, resource, threading
T_START = time.monotonic()
sys.set_int_max_str_digits(0)
HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__))); sys.path.insert(0, HERE)
from gbidi3 import memory as GM, executor as EX, source as GS

DEFAULTS = {"allow_binary64": True, "reference_fallback": True}
DIAG_KEYS = ("task", "reductions", "source_replay", "plan", "plan_candidates", "plan_validation", "plan_stop", "mechanisms", "backend", "binary64_admission", "attempts", "stop", "exact_fallback", "live", "diagnostic_stage", "memory_ledger", "clock", "unsound_witness")


def now():
    return time.monotonic() - T_START


def atomic_write(path, data):
    tmp = path + ".tmp"
    with open(tmp, "w") as f:
        f.write(data); f.flush(); os.fsync(f.fileno())
    os.replace(tmp, path)


def run_cell(arm, mp, ep, out, deadline, cfg, rec, expected):
    lm = os.environ.get("GBIDI_LAUNCH_MONO")
    try:
        T_DL = float(lm) + deadline if lm else T_START + deadline                      # ONE launch-relative absolute deadline through every layer (review E4)
    except ValueError:
        T_DL = T_START + deadline
    rec["deadline_origin"] = "launch" if lm else "process_start"; rec["phases_s"]["startup_imports"] = now(); ph = {}; t = now(); cfg = dict(cfg, budget_s=deadline)
    led = GM.Ledger()                                                                        # ONE host memory ledger for the caller's snapshot, execution AND publication (review E1)
    rec["task_raw"] = {"raw_model_sha256": EX.sha_file(mp), "raw_evidence_sha256": EX.sha_file(ep)}       # streamed hashes (constant memory) BEFORE parsing: every record, even one that never parses, is bound to the caller's bytes
    if expected:
        bad = {k: (expected[k], rec["task_raw"].get(k)) for k in ("raw_model_sha256", "raw_evidence_sha256") if k in expected and expected[k] != rec["task_raw"].get(k)}
        if bad:
            rec["status"] = "TASK_MISMATCH"; rec["reason"] = "the caller's files do not match the frozen task: %s" % json.dumps(bad); return
    try:
        S = GS.Snapshot(mp, ep, ledger=led, deadline=T_DL)
    except GS.InvalidInput as ex:
        rec["status"] = "INVALID_INPUT"; rec["reason"] = ex.reason; return
    except GS.ParseStop as ex:
        rec["status"] = "RESOURCE_STOP"; rec["reason"] = "%s during the caller snapshot: %s" % (ex.kind, ex.reason); rec["stop"] = {"phase": "snapshot", "kind": ex.kind, "detail": ex.reason}; rec["memory_ledger"] = led.report(); return
    rec["task"] = dict(S.task)
    if expected:
        bad = {k: (expected[k], S.task.get(k)) for k in ("raw_model_sha256", "raw_evidence_sha256") if k in expected and expected[k] != S.task.get(k)}
        if bad:
            rec["status"] = "TASK_MISMATCH"; rec["reason"] = "the caller's files do not match the frozen task: %s" % json.dumps(bad); return
    try:
        r = EX.execute(arm, mp, ep, out, T_DL, cfg, phases=ph, snapshot=S, ledger=led)
    except EX.Refuse as ex:
        rec["phases_s"].update(ph); rec["status"] = ex.kind; rec["reason"] = ex.reason; rec["stop"] = {"phase": "executor", "kind": ex.kind, "detail": ex.reason}
        if ex.rec:
            rec["diagnostic"] = {k: ex.rec[k] for k in DIAG_KEYS if k in ex.rec}; rec["diagnostic"]["NOTE"] = "NONCERTIFYING diagnostic record of a stopped attempt"
        return
    rec["phases_s"].update(ph); rec["executor_wall_s"] = now() - t
    for k in ("task", "reductions", "source_replay", "plan", "plan_candidates", "plan_validation", "mechanisms", "backend", "binary64_admission", "attempts", "route", "precision", "max_width", "exact_fallback", "clock", "memory_ledger", "Z", "execution"):
        if k in r:
            rec[k] = r[k]
    if r["status"] == "ZERO_EVIDENCE_PROVED":
        rec["status"] = "INCONSISTENT_EVIDENCE_CERTIFIED"; rec["reason"] = r.get("reason"); return
    t = now(); st = EX.publish(out, mp, ep, r, rec, T_DL, snapshot=S, arm=arm, cfg=cfg, ledger=led); rec["phases_s"]["publish"] = now() - t; rec["status"] = st; rec["memory_ledger"] = led.report()
    rec["execution"] = r.get("execution")
    if st == "CERTIFIED":
        rec["t_first_complete_output_s"] = now(); rec["output_sha256"] = rec["certified"]["output_sha256"]


def main():
    arm, mp, ep, out, deadline_s, cfgp = sys.argv[1:7]; deadline = float(deadline_s); os.makedirs(out, exist_ok=True); expected = json.loads(sys.argv[7]) if len(sys.argv) > 7 else None
    cfg = dict(DEFAULTS); cfg.update(json.load(open(cfgp)) if os.path.exists(cfgp) else json.loads(cfgp))
    rec = {"arm": arm, "model": mp, "evidence": ep, "deadline_s": deadline, "config": cfg, "expected_task": expected, "phases_s": {}, "status": None, "pid": os.getpid(), "started_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "counter_definitions": EX.COUNTER_DEFINITIONS}
    stop = [False]
    def flush():
        while not stop[0]:
            try:
                atomic_write(os.path.join(out, "progress.json"), json.dumps({"t_s": now(), "phases_s": rec.get("phases_s"), "status": rec.get("status"), "live": EX.live_snapshot(), "NOTE": "NONCERTIFYING progress snapshot"}, default=str))
            except Exception:
                pass
            time.sleep(0.5)
    threading.Thread(target=flush, daemon=True).start()
    try:
        if arm not in EX.ARMS:
            rec["status"] = "UNAVAILABLE"; rec["reason"] = "unknown arm"
        else:
            run_cell(arm, mp, ep, out, deadline, cfg, rec, expected)
    except Exception as ex:
        import traceback
        rec["status"] = "FAULT"; rec["reason"] = "%s: %s" % (type(ex).__name__, ex); rec["traceback"] = traceback.format_exc()[-2500:]
    stop[0] = True
    rec["complete_response_s"] = now(); rec["within_deadline"] = rec["complete_response_s"] <= deadline; lm = os.environ.get("GBIDI_LAUNCH_MONO"); timely = rec["within_deadline"]
    if lm:
        try:
            rec["complete_response_from_launch_s"] = time.monotonic() - float(lm); rec["t_start_after_launch_s"] = T_START - float(lm); rec["within_deadline_from_launch"] = rec["complete_response_from_launch_s"] <= deadline; timely = rec["within_deadline_from_launch"]; rec["deadline_classification_clock"] = "launch-relative"
        except ValueError:
            rec["deadline_classification_clock"] = "in-process (launch timestamp unparsable)"
    else:
        rec["deadline_classification_clock"] = "in-process (no launch timestamp)"
    if rec["status"] in ("CERTIFIED", "INCONSISTENT_EVIDENCE_CERTIFIED") and not timely:
        rec["censored"] = True; rec["status_before_deadline_check"] = rec["status"]; rec["status"] = "LATE_OUTPUT"
    rec["maxrss_self_bytes"] = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss; rec["maxrss_children_bytes"] = resource.getrusage(resource.RUSAGE_CHILDREN).ru_maxrss
    atomic_write(os.path.join(out, "cell.json"), json.dumps(rec, indent=1, default=str))
    print(json.dumps({"arm": arm, "status": rec["status"], "complete_response_s": round(rec["complete_response_s"], 3)}))


if __name__ == "__main__":
    main()
