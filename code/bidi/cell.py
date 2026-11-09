"""One BIDI pilot cell in a FRESH process (timer starts before imports):
    python -m bidi.cell ARM MODEL.uai EVID.uai.evid OUT_DIR DEADLINE_S CONFIG(json path or literal)
ARM in {BIDI_NATIVE_CERT, BIDI_NATIVE_DUPLICATE_WORK, BIDI_MPFR53_CERT}. Phases: startup_imports, recognize (untrusted plan), then the
trusted executor's phases (parse_bind, validate_structure, range_depth_proofs, convert_verify, kernel_init, kernel_stream, enclose),
publish (exact grid + separate task-bound point verifier). DUPLICATE_WORK runs the complete executor pipeline once with its outputs
DISCARDED (parse through kernel finish; the record is deleted), then the authoritative pipeline from scratch. Status vocabulary follows
adp.cell (CERTIFIED / LATE_OUTPUT / RESOURCE_STOP / ROUTE_LIMITATION / CHECK_FAILED / INCONSISTENT_EVIDENCE_CERTIFIED / FAULT)."""
from __future__ import annotations
import os, sys, json, time, resource, threading
T_START = time.monotonic()
sys.set_int_max_str_digits(0)
HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__))); sys.path.insert(0, HERE)
from bidi import executor as EX
from bidi import recognize as RZ

DEFAULTS = {"lanes_k": 3, "block_steps": 4096, "precision": 53}


def now():
    return time.monotonic() - T_START


def atomic_write(path, data):
    tmp = path + ".tmp"
    with open(tmp, "w") as f:
        f.write(data); f.flush(); os.fsync(f.fileno())
    os.replace(tmp, path)


def run_cell(arm, mp, ep, out, deadline, cfg, rec):
    T_DL = T_START + deadline; rec["phases_s"]["startup_imports"] = now()
    t = now(); plan = RZ.recognize(mp, ep); rec["plan_proposed"] = plan; rec["phases_s"]["recognize"] = now() - t
    factory = EX.MpfrKernel if arm == "BIDI_MPFR53_CERT" else EX.NativeKernel
    if arm == "BIDI_NATIVE_DUPLICATE_WORK":
        # DUPLICATED-WORK control: a complete first pass (same implementation) whose outputs are discarded; nothing of it is reused below
        ph1 = {}; t = now()
        try:
            r1 = EX.execute(mp, ep, plan, out, T_DL, cfg, kernel_factory=factory, record_prefix="discarded_first_pass", phases=ph1)
            rec["first_pass"] = {"status": r1.get("status"), "phases_s": ph1, "wall_s": now() - t, "Z_hex": (r1.get("values_hex") or {}).get("Z")}
        except EX.Refuse as ex:
            rec["first_pass"] = {"status": ex.kind, "reason": ex.reason, "phases_s": ph1, "wall_s": now() - t}
            rec["status"] = "RESOURCE_STOP" if ex.kind == "RESOURCE_STOP" else ex.kind; rec["reason"] = "first (discarded) pass: " + ex.reason; rec["stop"] = {"phase": "first_pass", "kind": ex.kind}; return
        p1 = os.path.join(out, "discarded_first_pass.json")
        if os.path.exists(p1):
            os.remove(p1)                                                                     # discarded: the authoritative pass may not read it
    ph = {}; t = now()
    try:
        r = EX.execute(mp, ep, plan, out, T_DL, cfg, kernel_factory=factory, phases=ph)
    except EX.Refuse as ex:
        rec["phases_s"].update(ph); rec["status"] = "RESOURCE_STOP" if ex.kind == "RESOURCE_STOP" else ex.kind; rec["reason"] = ex.reason; rec["stop"] = {"phase": "executor", "kind": ex.kind, "detail": ex.reason}; return
    rec["phases_s"].update(ph); rec["executor_wall_s"] = now() - t
    rec["task"] = r["task"]; rec["structure"] = r.get("structure"); rec["range_proof"] = r.get("range_proof"); rec["depth"] = r.get("depth"); rec["conversion"] = r.get("conversion"); rec["backend"] = r.get("backend"); rec["kernel"] = r.get("kernel"); rec["values_hex"] = r.get("values_hex"); rec["max_width"] = r.get("max_width")
    if r["status"] == "ZERO_EVIDENCE_PROVED":
        rec["status"] = "INCONSISTENT_EVIDENCE_CERTIFIED"; rec["reason"] = r.get("reason"); return
    t = now(); st = EX.publish(out, mp, ep, r, rec); rec["phases_s"]["publish"] = now() - t; rec["status"] = st
    if st == "CERTIFIED":
        rec["t_first_complete_output_s"] = now()


def main():
    arm, mp, ep, out, deadline_s, cfgp = sys.argv[1:7]; deadline = float(deadline_s); os.makedirs(out, exist_ok=True)
    cfg = dict(DEFAULTS); cfg.update(json.load(open(cfgp)) if os.path.exists(cfgp) else json.loads(cfgp))
    rec = {"arm": arm, "model": mp, "evidence": ep, "deadline_s": deadline, "config": cfg, "phases_s": {}, "status": None, "pid": os.getpid(), "started_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}
    stop = [False]
    def flush():                                                                                 # progress snapshots so a supervisor kill leaves the last known phase
        while not stop[0]:
            try:
                atomic_write(os.path.join(out, "progress.json"), json.dumps({"t_s": now(), "phases_s": rec.get("phases_s"), "status": rec.get("status")}, default=str))
            except Exception:
                pass
            time.sleep(0.5)
    threading.Thread(target=flush, daemon=True).start()
    try:
        if arm not in ("BIDI_NATIVE_CERT", "BIDI_NATIVE_DUPLICATE_WORK", "BIDI_MPFR53_CERT"):
            rec["status"] = "UNAVAILABLE"; rec["reason"] = "unknown arm"
        else:
            run_cell(arm, mp, ep, out, deadline, cfg, rec)
    except Exception as ex:
        import traceback
        rec["status"] = "FAULT"; rec["reason"] = "%s: %s" % (type(ex).__name__, ex); rec["traceback"] = traceback.format_exc()[-2500:]
    stop[0] = True
    rec["complete_response_s"] = now(); rec["within_deadline"] = rec["complete_response_s"] <= deadline
    # review of 9 Nov 2026 (timing boundary): if the launcher recorded CLOCK_MONOTONIC before Popen in BIDI_LAUNCH_MONO, report the elapsed time from
    # BEFORE PROCESS LAUNCH to this point (interpreter start-up and imports before T_START included). complete_response_s stays the in-process figure.
    lm = os.environ.get("BIDI_LAUNCH_MONO")
    if lm:
        try:
            rec["launch_mono"] = float(lm); rec["complete_response_from_launch_s"] = time.monotonic() - float(lm); rec["within_deadline_from_launch"] = rec["complete_response_from_launch_s"] <= deadline
            rec["t_start_after_launch_s"] = T_START - float(lm)
        except ValueError:
            rec["launch_mono"] = "unparsable"
    rec["timing_note"] = "complete_response_s: in-process, from the module's T_START (after interpreter start-up) to before the final record write; complete_response_from_launch_s: from the launcher's pre-Popen monotonic timestamp (when supplied); the supervisor RECEIPT wall (launch through reap) is the conservative whole-job figure"
    if rec["status"] in ("CERTIFIED", "CERTIFIED_TOO_WIDE", "CERTIFIED_WIDTH_ONLY_POINT_INFEASIBLE", "INCONSISTENT_EVIDENCE_CERTIFIED") and not rec["within_deadline"]:
        rec["censored"] = True; rec["status_before_deadline_check"] = rec["status"]; rec["status"] = "LATE_OUTPUT"
    rec["maxrss_self_bytes"] = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss; rec["maxrss_children_bytes"] = resource.getrusage(resource.RUSAGE_CHILDREN).ru_maxrss
    atomic_write(os.path.join(out, "cell.json"), json.dumps(rec, indent=1, default=str))
    print(json.dumps({"arm": arm, "status": rec["status"], "complete_response_s": round(rec["complete_response_s"], 3)}))


if __name__ == "__main__":
    main()
