"""ONE strict attempt reconciler for resume (gbidi.pilot) and closeout (gbidi_closeout.report) -- third review H2 / H3.
A planned cell is ACCEPTED only when every fact below is established from the saved artifacts; a missing field is a reason, never permission:
  record:   cell.json exists and (new arms) its arm == planned arm, or (comparators) adapter.json exists with planned_arm == planned and
            producer_arm == the frozen producer for that arm and cell.json's arm == producer_arm;
  task:     record task raw + canonical model / evidence hashes == the manifest case; queries_sha256 == sha256(json.dumps(list(range(nvars))));
            nvars == the case's variable count; expected_task.cell_id == planned cell_id (new arms: in cell.json; comparators: in adapter.json);
  budget:   record deadline_s == planned budget; the config hash == the frozen comparator config (ADP) / rules absent or default (new arms);
  attempt:  exactly one START, one SPAWNED and one RECEIPT with the same jid for this cell's job name (which carries the cell_id), the START's
            cmd names this cell's output directory and model path, START.start_utc >= frozen_utc, receipt.outcome == COMPLETED (or NONZERO_EXIT
            with a typed non-success status), cleanup_unresolved false, group_empty_at_receipt true, nested_groups_live_at_receipt 0;
  output:   for CERTIFIED / COMPLETE: output.MAR exists, its sha256 == the recorded output_sha256 (new arms record it; comparators via adapter.json),
            and the launch-relative delivery time (complete_response_from_launch_s / adapter delivery_from_launch_s) <= budget;
  pins:     the record's kernel binary / source hashes (new arms) == the manifest's.
`status` is DERIVED: the record's status when accepted; otherwise NOT_ACCEPTED (with the reasons). `delivered_valid_output` is reported separately
from `accepted` (a valid delivered output whose lifecycle evidence is incomplete is listed, not counted)."""
from __future__ import annotations
import os, json, hashlib, collections
from gbidi.arm_adapter import PRODUCER_ARM

NEW_ARMS = {"GENERAL_BIDI_V2", "NATIVE_PLAIN_V2", "A1_NO_DEMAND_MASKS", "A2_NO_FUSION", "A3_NO_RESPONSE_VIEWS"}
SUCCESS = {"CERTIFIED", "COMPLETE"}


def sha(p):
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for ch in iter(lambda: f.read(1 << 20), b""):
            h.update(ch)
    return h.hexdigest()


def job_name(c):
    return "cell:%03d:%s:%s:%s:%ds:%s" % (c["index"], c["stage"], c["case"], c["arm"], int(c["budget_s"]), c["cell_id"])


def ledger_index(D):
    led = [json.loads(l) for l in open(os.path.join(D, "GB_LEDGER.jsonl"))] if os.path.exists(os.path.join(D, "GB_LEDGER.jsonl")) else []
    by_job = collections.defaultdict(lambda: {"START": [], "SPAWNED": [], "RECEIPT": []})
    for r in led:
        if r.get("kind") in ("START", "SPAWNED", "RECEIPT") and r.get("job"):
            by_job[r["job"]][r["kind"]].append(r)
    return by_job


def reconcile(D, man, c, idx):
    """returns the reconciled row for planned cell c (idx = ledger_index(D))"""
    od = os.path.join(D, c["out_dir"]); cj = os.path.join(od, "cell.json"); aj = os.path.join(od, "adapter.json"); cs = man["cases"][c["case"]]; job = job_name(c); reasons = []
    row = dict(c, job=job, family=cs["family"], accepted=False, delivered_valid_output=False, status="NOT_ACCEPTED", reasons=reasons)
    if not os.path.exists(cj):
        if os.path.exists(os.path.join(od, "NOT_LAUNCHED.json")):
            row.update(json.load(open(os.path.join(od, "NOT_LAUNCHED.json")))); row["resolution"] = "NOT_LAUNCHED"; return row
        row.update(status="UNLAUNCHED", resolution="EXPLICITLY_UNLAUNCHED"); return row
    rec = json.load(open(cj)); comparator = c["arm"] not in NEW_ARMS; ad = json.load(open(aj)) if os.path.exists(aj) else None
    if rec.get("status") == "NO_RECORD":
        row.update(status="NO_RECORD", resolution="KILLED_NO_RECORD", record_status="NO_RECORD")
    if comparator:
        if ad is None:
            reasons.append("adapter.json missing")
        else:
            if ad.get("planned_arm") != c["arm"] or ad.get("producer_arm") != PRODUCER_ARM.get(c["arm"]):
                reasons.append("adapter arm mapping mismatch")
            if rec.get("arm") != PRODUCER_ARM.get(c["arm"]) and rec.get("status") != "NO_RECORD":
                reasons.append("producer arm %r != frozen producer %r" % (rec.get("arm"), PRODUCER_ARM.get(c["arm"])))
        task = (ad or {}).get("task") or {}; expected = (ad or {}).get("expected_task") or {}; status = (ad or {}).get("status"); delivery = (ad or {}).get("delivery_from_launch_s"); out_sha = (ad or {}).get("output_sha256"); cfg_ok = (c["arm"] != "ADP_REPAIRED") or ((ad or {}).get("config_sha256") == man.get("config_adp_repaired_sha256"))
        if not cfg_ok:
            reasons.append("comparator configuration hash differs from the manifest")
    else:
        if rec.get("arm") != c["arm"]:
            reasons.append("record arm %r != planned %r" % (rec.get("arm"), c["arm"]))
        task = rec.get("task") or {}; expected = rec.get("expected_task") or {}; status = rec.get("status"); delivery = rec.get("complete_response_from_launch_s"); out_sha = (rec.get("certified") or {}).get("output_sha256") or rec.get("output_sha256")
        cfg = rec.get("config") or {}
        if "rules" in cfg and list(cfg["rules"]) != list(man.get("common_rules", [])):
            reasons.append("record configuration (rules) differs from the frozen common rules")
        bk = ((rec.get("backend") or {}).get("build") or {})
        if rec.get("status") not in ("RESOURCE_STOP", "INVALID_INPUT", "TASK_MISMATCH", "NO_RECORD", "FAULT") and bk and bk.get("binary_sha256") != man.get("kernel_binary_sha256"):
            reasons.append("record kernel binary differs from the manifest")
        if rec.get("deadline_classification_clock") not in (None, "launch-relative") and status in SUCCESS:
            reasons.append("success classified on the in-process clock")
    for k in ("raw_model_sha256", "raw_evidence_sha256", "canonical_model_sha256", "canonical_evidence_sha256"):
        if task.get(k) != cs.get(k):
            reasons.append("task %s differs" % k)
    exp_q = hashlib.sha256(json.dumps(list(range(int(cs["variables"])))).encode()).hexdigest()
    if task.get("queries_sha256") != exp_q or task.get("nvars") != int(cs["variables"]):
        reasons.append("query contract / variable count differs")
    if expected.get("cell_id") != c["cell_id"]:
        reasons.append("expected cell id missing or differs")
    if (rec.get("deadline_s") if not comparator else (ad or {}).get("budget_s")) != c["budget_s"]:
        reasons.append("record budget differs from the planned budget")
    S, P, R = idx.get(job, {"START": [], "SPAWNED": [], "RECEIPT": []}).values() if job in idx else ([], [], [])
    if len(S) != 1 or len(P) != 1 or len(R) != 1:
        reasons.append("attempt records START/SPAWNED/RECEIPT = %d/%d/%d (need exactly 1/1/1)" % (len(S), len(P), len(R)))
    else:
        s, p, r = S[0], P[0], R[0]
        if not (s["jid"] == p["jid"] == r["jid"]):
            reasons.append("attempt ids do not match across START/SPAWNED/RECEIPT")
        if s.get("start_utc", "") < man["frozen_utc"]:
            reasons.append("attempt started before the freeze")
        cmd = " ".join(s.get("cmd") or [])
        if c["out_dir"].split("/")[-1] not in cmd or os.path.basename(cs["model_path"]) not in cmd:
            reasons.append("START command does not name this cell's output directory / model")
        if r.get("cleanup_unresolved") or r.get("group_empty_at_receipt") is not True or (r.get("nested_groups_live_at_receipt") or 0) != 0:
            reasons.append("receipt does not establish clean completion of all owned work")
        if status in SUCCESS and r.get("outcome") != "COMPLETED":
            reasons.append("success status with receipt outcome %r" % r.get("outcome"))
        if status not in SUCCESS and r.get("outcome") not in ("COMPLETED", "NONZERO_EXIT", "TIMEOUT_KILL", "MEMORY_KILL"):
            reasons.append("receipt outcome %r is not a terminal attempt outcome" % r.get("outcome"))
        row.update(supervisor_outcome=r.get("outcome"), supervisor_wall_s=r.get("wall_s"), peak_tree_rss_bytes=r.get("peak_tree_rss_bytes"), returncode=r.get("returncode"), jid=r.get("jid"), parent_jid=r.get("parent_jid"))
    mar = os.path.join(od, "output.MAR")
    if status in SUCCESS:
        if not os.path.exists(mar):
            reasons.append("success status without output.MAR")
        elif out_sha is None or sha(mar) != out_sha:
            reasons.append("output.MAR hash not recorded or differs from the record")
        if delivery is None or delivery > c["budget_s"]:
            reasons.append("launch-relative delivery missing or beyond the budget")
        row["delivered_valid_output"] = os.path.exists(mar) and out_sha is not None and sha(mar) == out_sha
    row.update(record_status=status, delivery_from_launch_s=delivery, output_sha256=out_sha, complete_response_s=rec.get("complete_response_s"), phases_s=rec.get("phases_s"), stop=rec.get("stop"), reason=(rec.get("reason") or "")[:300] if isinstance(rec.get("reason"), str) else rec.get("reason"), maxrss_self_bytes=rec.get("maxrss_self_bytes"))
    if not comparator:
        src = rec if "plan" in rec else (rec.get("diagnostic") or {})
        row.update(route=rec.get("route"), precision=rec.get("precision"), max_width_raw=rec.get("max_width"), delivered_max_width=(rec.get("certified") or {}).get("delivered_max_width"), reductions=(src.get("reductions") or {}).get("steps"), free_reduced=(src.get("reductions") or {}).get("free_reduced"), plan_totals=(src.get("plan") or {}).get("totals"), plan_order=((src.get("plan") or {}).get("order") or {}).get("name"),
                   plan_candidates=[{k: x.get(k) for k in ("order", "state", "baseline", "chosen", "mandatory_representable")} for x in (src.get("plan_candidates") or [])], mechanisms=src.get("mechanisms"), node_provenance=[{k: nd.get(k) for k in ("nid", "support_prov", "demand_prov", "view_prov", "fused_by", "downgrade")} for nd in (src.get("plan") or {}).get("nodes", [])], binary64_admission=(src.get("binary64_admission") or {}).get("checks"),
                   attempts=[{k: a.get(k) for k in ("route", "precision", "outcome", "stop", "stop_phase", "create_s", "forward_s", "reverse_s", "refused", "labels", "delta_max", "wall_s")} | {"counters": a.get("counters"), "counters_after_forward": a.get("counters_after_forward")} for a in (src.get("attempts") or [])], reference_fallback=(src.get("reference_fallback") or {}).get("status"), discovery_stop=(src.get("plan") or {}).get("discovery_stop"), diagnostic_present="diagnostic" in rec, live_at_stop=(rec.get("diagnostic") or {}).get("live"), plan_validation=(src.get("plan_validation") or {}).get("status"))
    if reasons:
        row["resolution"] = "NOT_ACCEPTED"; return row
    row.update(accepted=True, status=status, resolution="ACCEPTED"); return row
