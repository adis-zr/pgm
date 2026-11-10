"""Frozen EXPERIMENT-ARM ADAPTER for the pinned comparator producers (third review H1). The pinned numerical implementations (adp.cell writes arm
AGGREGATE_DP_V1; bench.cells EXACT writes arm EXACT) are NOT modified. The adapter is the process the supervisor launches for a comparator cell:
  * records the launch-relative clock origin (GBIDI_LAUNCH_MONO from the stage runner; else its own start),
  * snapshots the caller's input bytes (gbidi.source) and the comparator configuration -> task binding (raw / canonical hashes, queries),
  * runs the pinned producer as a child in the SAME process group (so the supervisor's group kill covers it),
  * observes DELIVERY from the launch clock: the moment output.MAR / cell.json appear (polled every 20 ms),
  * writes adapter.json {planned_arm, producer_arm, producer_status, task, config_sha256, output_sha256, delivery_from_launch_s, within_budget_from_launch,
    status (= producer status, re-classified LATE_OUTPUT when the launch-relative delivery exceeds the budget), expected_task}.
The producer's cell.json is left untouched; closeout joins cell.json + adapter.json + the supervisor receipt.
    python -m gbidi.arm_adapter PLANNED_ARM MODEL EVID OUT BUDGET_S CONFIG_PATH EXPECTED_TASK_JSON"""
from __future__ import annotations
import os, sys, json, time, hashlib, subprocess
T0 = time.monotonic()
HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__))); sys.path.insert(0, HERE)
sys.set_int_max_str_digits(0)
from gbidi import source as GS

PY = sys.executable
PRODUCER = {"ADP_REPAIRED": {"arm": "AGGREGATE_DP_V1", "cmd": lambda mp, ep, out, b, cfg: [PY, "-m", "adp.cell", mp, ep, out, "%.3f" % b, cfg], "success": ("CERTIFIED",)},
            "EXACT_LIBDAI": {"arm": "EXACT", "cmd": lambda mp, ep, out, b, cfg: [PY, "-m", "bench.cells", "EXACT", mp, ep, out, "%.3f" % b, "{}"], "success": ("COMPLETE",)}}
PRODUCER_ARM = {k: v["arm"] for k, v in PRODUCER.items()}


def sha(p):
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for ch in iter(lambda: f.read(1 << 20), b""):
            h.update(ch)
    return h.hexdigest()


def main():
    planned, mp, ep, out, budget_s, cfgp = sys.argv[1:7]; budget = float(budget_s); expected = json.loads(sys.argv[7]) if len(sys.argv) > 7 else None; os.makedirs(out, exist_ok=True)
    lm = os.environ.get("GBIDI_LAUNCH_MONO"); launch = float(lm) if lm else T0; spec = PRODUCER[planned]
    rec = {"adapter": "gbidi.arm_adapter v1", "planned_arm": planned, "producer_arm": spec["arm"], "budget_s": budget, "launch_clock": "stage runner (GBIDI_LAUNCH_MONO)" if lm else "adapter start", "adapter_start_after_launch_s": T0 - launch, "expected_task": expected, "config_path": cfgp, "config_sha256": sha(cfgp) if os.path.exists(cfgp) else None, "status": None}
    try:
        S = GS.Snapshot(mp, ep); rec["task"] = dict(S.task)
    except GS.InvalidInput as ex:
        rec.update(status="INVALID_INPUT", reason=ex.reason); json.dump(rec, open(os.path.join(out, "adapter.json"), "w"), indent=1); print(json.dumps({"planned_arm": planned, "status": rec["status"]})); return
    if expected and any(expected.get(k) and expected[k] != rec["task"].get(k) for k in ("raw_model_sha256", "raw_evidence_sha256")):
        rec.update(status="TASK_MISMATCH", reason="caller files differ from the frozen task"); json.dump(rec, open(os.path.join(out, "adapter.json"), "w"), indent=1); print(json.dumps({"planned_arm": planned, "status": rec["status"]})); return
    cj = os.path.join(out, "cell.json"); mar = os.path.join(out, "output.MAR"); seen = {}
    proc = subprocess.Popen(spec["cmd"](mp, ep, out, budget, cfgp), cwd=HERE, env=dict(os.environ, PYTHONPATH=HERE))
    while proc.poll() is None:
        for name, p in (("output.MAR", mar), ("cell.json", cj)):
            if name not in seen and os.path.exists(p):
                seen[name] = time.monotonic() - launch
        time.sleep(0.02)
    for name, p in (("output.MAR", mar), ("cell.json", cj)):
        if name not in seen and os.path.exists(p):
            seen[name] = time.monotonic() - launch
    rec["producer_returncode"] = proc.returncode; rec["producer_exit_from_launch_s"] = time.monotonic() - launch; rec["first_seen_from_launch_s"] = seen
    if not os.path.exists(cj):
        rec.update(status="NO_RECORD", reason="the producer left no cell.json")
    else:
        prod = json.load(open(cj)); rec["producer_status"] = prod.get("status"); rec["producer_complete_response_s"] = prod.get("complete_response_s"); rec["producer_deadline_s"] = prod.get("deadline_s")
        if prod.get("arm") != spec["arm"]:
            rec.update(status="UNEXPECTED_PRODUCER_ARM", reason="producer wrote arm %r" % prod.get("arm"))
        else:
            rec["delivery_from_launch_s"] = seen.get("cell.json"); rec["output_first_seen_from_launch_s"] = seen.get("output.MAR"); rec["within_budget_from_launch"] = (rec["delivery_from_launch_s"] is not None and rec["delivery_from_launch_s"] <= budget)
            rec["status"] = prod.get("status")
            if rec["status"] in spec["success"] and not rec["within_budget_from_launch"]:
                rec["status_before_launch_clock"] = rec["status"]; rec["status"] = "LATE_OUTPUT"; rec["censored"] = True
            if os.path.exists(mar):
                rec["output_sha256"] = sha(mar); rec["output_bytes"] = os.path.getsize(mar)
            if not S.path_still_matches():
                rec["status"] = "TASK_MISMATCH"; rec["reason"] = "caller files changed during the producer run"
    rec["adapter_complete_from_launch_s"] = time.monotonic() - launch
    tmp = os.path.join(out, "adapter.json.tmp")
    with open(tmp, "w") as f:
        json.dump(rec, f, indent=1); f.flush(); os.fsync(f.fileno())
    os.replace(tmp, os.path.join(out, "adapter.json")); print(json.dumps({"planned_arm": planned, "producer_arm": spec["arm"], "status": rec["status"], "delivery_from_launch_s": rec.get("delivery_from_launch_s")}))


if __name__ == "__main__":
    main()
