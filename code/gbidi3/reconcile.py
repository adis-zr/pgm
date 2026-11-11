"""ONE strict attempt reconciler for resume (gbidi3.pilot), closeout (gbidi3_closeout.report) and summary extraction (brief §17; repaired after the 10 Nov
review R3a-c / C1-C4). Lifecycle FIRST: a cell with a START is a launched attempt; a launched attempt without a producer record is a typed NO_RECORD (or
LAUNCH_FAILED) row bound to the manifest and its receipt, accepted as a NONCERTIFYING attempt (counted once, never a success); only a cell with no START
and no record is UNLAUNCHED. Task binding = every field of gbidi3.source.TASK_BINDING_FIELDS by positive equality against the manifest case (incl.
orig_card, eps, max_width, canonical_version). Execution binding (successes) = gbidi3.identity.check_execution against the manifest's expectation
(route-specific: native routes bind the kernel binary + source + flags; python exact routes bind their implementation files). START.cmd must equal the
exact expected launch arguments. A planned cell is ACCEPTED as a success only when every fact below is established; a missing field is a reason:
  record:   cell.json exists and (new arms) its arm == planned arm, or (comparators) adapter.json exists with planned_arm == planned and producer_arm ==
            the frozen producer and cell.json's arm == producer_arm;
  task:     record task raw + canonical (legacy) + canonical_v2 model / evidence hashes == the manifest case; queries_sha256 == sha256(json.dumps(range(nvars)));
            nvars == the case's variable count; expected_task.cell_id == planned cell_id;
  budget:   record deadline_s == planned budget; config hash == the frozen comparator config (ADP) / rules absent or == the frozen common rules (new arms);
            FULL config equality for new arms (every non-code execution field);
  attempt:  exactly one START, one SPAWNED and one RECEIPT with the same jid for this cell's job name, the START's cmd names this cell's output directory and
            model path, START.start_utc >= frozen_utc, receipt outcome COMPLETED (or NONZERO_EXIT / TIMEOUT_KILL / MEMORY_KILL with a typed non-success
            status), cleanup_unresolved false, group_empty_at_receipt true, nested_groups_live_at_receipt 0;
  output:   for CERTIFIED / COMPLETE: output.MAR exists, its sha256 == the recorded output_sha256, launch-relative delivery <= budget;
  pins:     the record's kernel binary / source hashes (new arms) == the manifest's.
`status` is DERIVED: the record's status when accepted; otherwise NOT_ACCEPTED (with reasons). `delivered_valid_output` is reported separately from `accepted`."""
from __future__ import annotations
import os, json, hashlib, collections
from gbidi3.arm_adapter import PRODUCER_ARM
from gbidi3 import identity as ID, source as GS

NEW_ARMS = {"GENERAL_BIDI_COMPLETE_V3", "NATIVE_PLAIN_COMPLETE_V3", "A1_NO_DEMAND_MASKS", "A2_NO_FUSION", "A3_NO_RESPONSE_VIEWS"}
SUCCESS = {"CERTIFIED", "COMPLETE"}
TASK_KEYS = ("raw_model_sha256", "raw_evidence_sha256", "canonical_model_sha256", "canonical_evidence_sha256", "canonical_v2_model_sha256", "canonical_v2_evidence_sha256")


def sha(p):
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for ch in iter(lambda: f.read(1 << 20), b""):
            h.update(ch)
    return h.hexdigest()


def job_name(c):
    return "cell:%03d:%s:%s:%s:%ds:%s" % (c["index"], c["stage"], c["case"], c["arm"], int(c["budget_s"]), c["cell_id"])


def owner_evidence(D, child_start, child_receipt, by_job):
    """ATTEMPT-BOUND ownership evidence for a parent-generated terminal receipt (third review H1 / H2). Returns (owner_receipt, reasons). The owner named by
    `written_by_parent` must (1) be an ANCESTOR of the child attempt in the START parent chain of this ledger, or the registered root owner of the child's
    ownership registry (`owner_dir/groups.jsonl` records jid -> parent_jid for every nested supervisor; the root owner is the registry's parentless entry);
    (2) have exactly ONE receipt in this ledger (duplicate / conflicting owner receipts are not evidence); (3) positively establish the closure: its own
    cleanup resolved, no live nested group, owned group empty, every registered nested group of its subtree accounted (registered >= 1 since the child
    itself registered); a kill count of zero is LEGITIMATE (the child may have exited naturally before the cleanup); (4) the child's pid / pgid in the receipt
    must equal its SPAWNED record."""
    reasons = []; owner_jid = child_receipt.get("written_by_parent")
    if not owner_jid:
        return None, ["parent-cleanup receipt names no owner"]
    rows = []
    p = os.path.join(D, "GB_LEDGER.jsonl")
    if os.path.exists(p):
        for l in open(p):
            try:
                rows.append(json.loads(l))
            except ValueError:
                continue
    owner_rc = [r for r in rows if r.get("kind") == "RECEIPT" and r.get("jid") == owner_jid]
    if len(owner_rc) != 1:
        return None, ["owner receipt %s: expected exactly one in this ledger, found %d (missing, duplicate or conflicting ownership evidence)" % (owner_jid[:40], len(owner_rc))]
    owner = owner_rc[0]
    # UNIQUE owner lifecycle (fourth review C): exactly one START (a supervised job always writes its START first) and at most one SPAWNED for the owner; a duplicate /
    # contradictory START is not resolved by dictionary overwrite but rejected
    owner_st = [r for r in rows if r.get("kind") == "START" and r.get("jid") == owner_jid]; owner_sp = [r for r in rows if r.get("kind") == "SPAWNED" and r.get("jid") == owner_jid]
    if len(owner_st) != 1 or len(owner_sp) > 1:
        return owner, ["owner lifecycle %s: expected exactly one START and at most one SPAWNED, found %d / %d (missing or ambiguous owner lifecycle)" % (owner_jid[:40], len(owner_st), len(owner_sp))]
    if owner_sp and owner.get("pgid") is not None and owner_sp[0].get("pgid") != owner.get("pgid"):
        reasons.append("owner receipt pgid differs from its SPAWNED record")
    # ancestry: follow START parent links from the child; also accept the registry's root owner of the child's own registration
    parent_of = {r["jid"]: r.get("parent_jid") for r in rows if r.get("kind") == "START"}
    chain = []; j = child_start.get("parent_jid"); seen = set()
    while j and j not in seen:
        chain.append(j); seen.add(j); j = parent_of.get(j)
    registry_ok = False; reg_path = os.path.join(child_start.get("owner_dir") or "", "groups.jsonl")
    if child_start.get("owner_dir") and os.path.exists(reg_path):
        regs = []
        for l in open(reg_path):
            try:
                regs.append(json.loads(l))
            except ValueError:
                continue
        mine = [g for g in regs if g.get("jid") == child_start.get("jid")]
        if mine:
            rp = {g["jid"]: g.get("parent_jid") for g in regs}; j = mine[0].get("parent_jid"); seen = set()
            while j and j not in seen:
                if j == owner_jid:
                    registry_ok = True
                seen.add(j); j = rp.get(j)
            if mine[0].get("pid") != child_receipt.get("pid") or mine[0].get("pgid") != child_receipt.get("pgid"):
                reasons.append("parent-cleanup receipt pid / pgid differ from the child's registration")
        else:
            reasons.append("the child attempt is not in its own ownership registry")
    if owner_jid not in chain and not registry_ok:
        reasons.append("owner %s is neither an ancestor of the attempt in the START chain nor a registered owner of its group (unrelated ownership evidence)" % owner_jid[:40])
    # POSITIVE, mutually compatible closure fields (fourth review C): missing fields are NOT clean; contradictions between the outcome / detailed live list and the flags are rejected
    def is_int(x):
        return isinstance(x, int) and not isinstance(x, bool)
    live_n = owner.get("nested_groups_live_at_receipt"); reg_n = owner.get("nested_groups_registered"); killed_n = owner.get("nested_groups_killed"); live_list = owner.get("nested_live")
    if owner.get("cleanup_unresolved") is not False or owner.get("group_empty_at_receipt") is not True or not is_int(live_n) or live_n != 0 or not is_int(reg_n) or reg_n < 1 or not is_int(killed_n) or killed_n < 0:
        reasons.append("the owner receipt does not POSITIVELY establish the closure of the owned work (requires explicit cleanup_unresolved false, group_empty_at_receipt true, nested_groups_live_at_receipt == 0, nested_groups_registered >= 1, nested_groups_killed >= 0; missing fields are not clean)")
    oc = str(owner.get("outcome") or "")
    if not oc or oc.startswith("CLEANUP_UNRESOLVED") or oc in ("LAUNCH_FAILED",) or owner.get("outcome_before_cleanup") in (None,) and oc == "":
        reasons.append("owner receipt outcome %r is incompatible with an established cleanup" % oc)
    if isinstance(live_list, list) and live_list:
        reasons.append("owner receipt lists %d live nested group(s) although its live count is zero (contradictory evidence)" % len(live_list))
    return owner, reasons


def ledger_index(D):
    led = [json.loads(l) for l in open(os.path.join(D, "GB_LEDGER.jsonl"))] if os.path.exists(os.path.join(D, "GB_LEDGER.jsonl")) else []
    by_job = collections.defaultdict(lambda: {"START": [], "SPAWNED": [], "RECEIPT": []})
    for r in led:
        if r.get("kind") in ("START", "SPAWNED", "RECEIPT") and r.get("job"):
            by_job[r["job"]][r["kind"]].append(r)
    return by_job


def expected_execution(man, c, rec_or_none):
    """the EXPECTED execution identity of a planned new-arm cell, recomputed from the MANIFEST (arm, budget, frozen cell config, kernel build) and the record's
    declared route / attempt (route and attempt are the record's own declaration; every other field is the manifest's)"""
    cfg = dict((man.get("arms_config", {}).get(c["arm"], {}) or {}).get("cell_config", {}) or {}); cfg["budget_s"] = c["budget_s"]
    route = (rec_or_none or {}).get("route") or ((rec_or_none or {}).get("execution") or {}).get("route"); attempt = ((rec_or_none or {}).get("execution") or {}).get("attempt_id")
    build = man.get("kernel_build") or {}
    exp = {"protocol": ID.PROTOCOL, "arm": c["arm"], "budget_s": float(c["budget_s"]), "config_sha256": ID.config_sha256(cfg), "rules": list(cfg.get("rules", ["exclude", "constants", "separate", "alias", "quotient"])), "route": route, "attempt_id": attempt}
    if route in ID.NATIVE_ROUTES:
        exp["implementation"] = {"kind": "native_kernel", "binary_sha256": man.get("kernel_binary_sha256"), "source_sha256": build.get("source_sha256"), "flags_sha256": ID.sha_bytes(json.dumps(build.get("flags"), sort_keys=True).encode()), "python_sources_sha256": man.get("python_sources_sha256")}
    else:
        exp["implementation"] = {"kind": "python_exact", "python_sources_sha256": man.get("python_sources_sha256")}
    return exp


def expected_launch_cmd(D, man, c, py=None):
    """the EXACT inner command the stage runner launches for this cell (gbidi3.pilot.run); compared argument by argument with START.cmd"""
    from gbidi3 import pilot as PI
    cs = man["cases"][c["case"]]; mp = os.path.join(PI.HERE, cs["model_path"]) if not os.path.isabs(cs["model_path"]) else cs["model_path"]; ep = os.path.join(PI.HERE, cs["evidence_path"]) if not os.path.isabs(cs["evidence_path"]) else cs["evidence_path"]
    out = os.path.join(D, c["out_dir"]); expected = json.dumps({"raw_model_sha256": cs["raw_model_sha256"], "raw_evidence_sha256": cs["raw_evidence_sha256"], "task_id": c["task_id"], "cell_id": c["cell_id"]}); py = py or PI.PY
    if c["arm"] in NEW_ARMS:
        return [py, "-m", "gbidi3.cell", c["arm"], mp, ep, out, "%.3f" % c["budget_s"], json.dumps(PI.CELL_CONFIG), expected]
    cfg_adp = os.path.join(PI.HERE, man["config_adp_repaired_path"]) if man.get("config_adp_repaired_path") else "{}"
    return [py, "-m", "gbidi3.arm_adapter", c["arm"], mp, ep, out, "%.3f" % c["budget_s"], cfg_adp if c["arm"] == "ADP_REPAIRED" else "{}", expected]


def reconcile(D, man, c, idx):
    """returns the reconciled row for planned cell c (idx = ledger_index(D)). Lifecycle is consulted FIRST: a cell whose START exists is a launched attempt
    whatever the producer wrote (review C1-C4); only a cell with no START and no record is UNLAUNCHED."""
    od = os.path.join(D, c["out_dir"]); cj = os.path.join(od, "cell.json"); aj = os.path.join(od, "adapter.json"); cs = man["cases"][c["case"]]; job = job_name(c); reasons = []
    row = dict(c, job=job, family=cs["family"], accepted=False, delivered_valid_output=False, status="NOT_ACCEPTED", reasons=reasons)
    S, P, R = idx.get(job, {"START": [], "SPAWNED": [], "RECEIPT": []}).values() if job in idx else ([], [], [])
    launched = bool(S)
    if not os.path.exists(cj) and not launched:
        if os.path.exists(os.path.join(od, "NOT_LAUNCHED.json")):
            row.update(json.load(open(os.path.join(od, "NOT_LAUNCHED.json")))); row["resolution"] = "NOT_LAUNCHED"; return row
        row.update(status="UNLAUNCHED", resolution="EXPLICITLY_UNLAUNCHED"); return row
    rec = json.load(open(cj)) if os.path.exists(cj) else None; comparator = c["arm"] not in NEW_ARMS; ad = json.load(open(aj)) if os.path.exists(aj) else None
    # ---------------- lifecycle (exactly one START; one SPAWNED unless the launch failed; exactly one terminal RECEIPT; exact launch arguments)
    lifecycle_ok = False; launch_failed = False
    if len(S) != 1 or len(R) != 1 or len(P) > 1:
        reasons.append("attempt records START/SPAWNED/RECEIPT = %d/%d/%d (need exactly 1/<=1/1)" % (len(S), len(P), len(R)))
    else:
        s, r = S[0], R[0]; p = P[0] if P else None
        launch_failed = r.get("outcome_before_cleanup", r.get("outcome")) == "LAUNCH_FAILED" or r.get("outcome") == "LAUNCH_FAILED"
        if not (s["jid"] == r["jid"] and (p is None or p["jid"] == s["jid"])):
            reasons.append("attempt ids do not match across START/SPAWNED/RECEIPT")
        if p is None and not launch_failed:
            reasons.append("no SPAWNED record although the launch did not fail")
        if s.get("start_utc", "") < man["frozen_utc"]:
            reasons.append("attempt started before the freeze")
        try:
            from gbidi3 import pilot as PI
            got_py = (s.get("cmd") or [None])[0]
            if got_py != PI.PY and not launch_failed:
                reasons.append("attempt launched with interpreter %r, not the harness interpreter" % got_py)      # only a typed LAUNCH_FAILED may carry a foreign interpreter path
            exp_cmd = expected_launch_cmd(D, man, c, py=got_py)
            if list(s.get("cmd") or []) != exp_cmd:
                reasons.append("START command differs from the exact expected launch arguments")
        except Exception as ex:
            reasons.append("expected launch command could not be formed: %s" % ex)
        parent_cleanup = r.get("outcome") == "PARENT_CLEANUP_KILL"
        exp_mem = float(c.get("mem_gib", man.get("mem_gib", 8.0)))
        if s.get("mem_cap_gib") is None or float(s.get("mem_cap_gib")) != exp_mem or s.get("timeout_s") is None or abs(float(s.get("timeout_s")) - float(c["budget_s"])) > 1e-9:
            reasons.append("START supervision parameters (memory cap %r / timeout %r) differ from the planned cell" % (s.get("mem_cap_gib"), s.get("timeout_s")))
        if r.get("cleanup_unresolved") or (r.get("group_empty_at_receipt") is not True and not launch_failed and not parent_cleanup) or (launch_failed and r.get("group_empty_at_receipt") not in (None, True)) or (r.get("nested_groups_live_at_receipt") or 0) != 0:
            reasons.append("receipt does not establish clean completion of all owned work")
        if r.get("outcome") not in ("COMPLETED", "NONZERO_EXIT", "TIMEOUT_KILL", "MEMORY_KILL", "LAUNCH_FAILED", "PARENT_CLEANUP_KILL"):
            reasons.append("receipt outcome %r is not a terminal attempt outcome" % r.get("outcome"))
        if parent_cleanup:
            # ONE terminal-receipt contract (second / third review F2 / H1 / H2) WITHOUT changing the pinned supervisor: a parent-generated receipt (wall UNKNOWN,
            # written_by_parent = the owner's jid) is terminal only together with ATTEMPT-BOUND evidence: a UNIQUE owner receipt that is an ancestor / registered
            # owner of this attempt and positively establishes the closure of the owned work; a kill count of zero is legitimate (naturally exited child)
            if r.get("wall_s") is not None:
                reasons.append("parent-cleanup receipt claims a measured wall (the wall of a parent-cleaned attempt is UNKNOWN)")
            if p is not None and (r.get("pid") != p.get("pid") or r.get("pgid") != p.get("pgid")):
                reasons.append("parent-cleanup receipt pid / pgid differ from this attempt's SPAWNED record")
            owner, oreasons = owner_evidence(D, s, r, idx); reasons.extend(oreasons)
            if r.get("cleanup_unresolved"):
                reasons.append("parent-cleanup receipt reports an unresolved cleanup")
            row["cleanup_evidence_reference"] = {"owner_jid": r.get("written_by_parent"), "owner_outcome": (owner or {}).get("outcome"), "owner_nested_registered": (owner or {}).get("nested_groups_registered"), "owner_nested_killed": (owner or {}).get("nested_groups_killed"), "owner_group_empty": (owner or {}).get("group_empty_at_receipt"), "binding": "unique owner receipt + START-chain ancestry or ownership-registry root + pid / pgid of the SPAWNED record"}
        row.update(supervisor_outcome=r.get("outcome"), supervisor_wall_s=r.get("wall_s"), peak_tree_rss_bytes=r.get("peak_tree_rss_bytes"), returncode=r.get("returncode"), jid=r.get("jid"), parent_jid=r.get("parent_jid"), launch_error=r.get("launch_error"))
        lifecycle_ok = not reasons
    # ---------------- a launched attempt without a producer record: a typed NO_RECORD / LAUNCH_FAILED row bound to the manifest and the receipt (noncertifying)
    if rec is None or rec.get("status") == "NO_RECORD":
        kind = "LAUNCH_FAILED" if launch_failed else "NO_RECORD"; pc = bool(S) and len(R) == 1 and R[0].get("outcome") == "PARENT_CLEANUP_KILL"
        row.update(status=kind, record_status=kind, resolution=("LAUNCH_FAILED" if launch_failed else ("PARENT_CLEANUP_KILLED_NO_RECORD" if pc else "KILLED_NO_RECORD")) if lifecycle_ok else "NOT_ACCEPTED", wall_known=(None if not R else (R[0].get("wall_s") is not None)), producer_diagnostics="UNAVAILABLE (the producer wrote no record)", expected_task={"raw_model_sha256": cs["raw_model_sha256"], "raw_evidence_sha256": cs["raw_evidence_sha256"], "cell_id": c["cell_id"], "task_id": c["task_id"]}, delivered_valid_output=False)
        row["accepted"] = lifecycle_ok                                                         # ACCEPTED as a reconciled NONCERTIFYING attempt (counted, charged once); never a success
        return row
    # ---------------- records with a producer file
    if comparator:
        if ad is None:
            reasons.append("adapter.json missing")
        else:
            if ad.get("planned_arm") != c["arm"] or ad.get("producer_arm") != PRODUCER_ARM.get(c["arm"]):
                reasons.append("adapter arm mapping mismatch")
            if rec.get("arm") != PRODUCER_ARM.get(c["arm"]):
                reasons.append("producer arm %r != frozen producer %r" % (rec.get("arm"), PRODUCER_ARM.get(c["arm"])))
        task = (ad or {}).get("task") or {}; expected = (ad or {}).get("expected_task") or {}; status = (ad or {}).get("status"); delivery = (ad or {}).get("delivery_from_launch_s"); out_sha = (ad or {}).get("output_sha256")
        if c["arm"] == "ADP_REPAIRED" and (ad or {}).get("config_sha256") != man.get("config_adp_repaired_sha256"):
            reasons.append("comparator configuration hash differs from the manifest")
        if (ad or {}).get("budget_s") != c["budget_s"]:
            reasons.append("record budget differs from the planned budget")
    else:
        if rec.get("arm") != c["arm"]:
            reasons.append("record arm %r != planned %r" % (rec.get("arm"), c["arm"]))
        task = rec.get("task") or {}; expected = rec.get("expected_task") or {}; status = rec.get("status"); delivery = rec.get("complete_response_from_launch_s"); out_sha = (rec.get("certified") or {}).get("output_sha256") or rec.get("output_sha256")
        frozen_cfg = dict((man.get("arms_config", {}).get(c["arm"], {}) or {}).get("cell_config", {}) or {}); got_cfg = dict(rec.get("config") or {})
        if {k: v for k, v in got_cfg.items() if k != "budget_s"} != {k: v for k, v in frozen_cfg.items() if k != "budget_s"}:
            reasons.append("record configuration differs from the frozen arm configuration (full equality required)")
        if rec.get("deadline_s") != c["budget_s"]:
            reasons.append("record budget differs from the planned budget")
        if status in SUCCESS or status in ("INCONSISTENT_EVIDENCE_CERTIFIED",):
            bad = ID.check_execution(rec.get("execution"), expected_execution(man, c, rec))
            if bad:
                reasons.extend(["execution identity: " + b for b in bad[:4]])
            if rec.get("deadline_classification_clock") != "launch-relative":
                reasons.append("success classified on the in-process clock")
    if not task and status not in SUCCESS and status not in ("INCONSISTENT_EVIDENCE_CERTIFIED",) and not comparator:
        raw = rec.get("task_raw") or {}                                                      # the record never parsed a task (INVALID_INPUT / stop before parsing): bound by the streamed raw hashes of the caller's files
        bad_task = ["raw task hash %s missing or differs (record never parsed its task)" % k for k in ("raw_model_sha256", "raw_evidence_sha256") if raw.get(k) != cs.get(k)]; row["task_binding"] = "RAW_HASHES_ONLY (no parsed task; noncertifying record)"
    else:
        bad_task = ID.check_task(task, dict(cs, queries_sha256=hashlib.sha256(json.dumps(list(range(int(cs["variables"])))).encode()).hexdigest(), nvars=int(cs["variables"]), orig_card=list(cs.get("orig_card") or []), eps=cs.get("eps", "1/200"), max_width=cs.get("max_width", "1/100"), canonical_version=cs.get("canonical_version")), GS.TASK_BINDING_FIELDS); row["task_binding"] = "FULL"
    reasons.extend(bad_task)
    if expected.get("cell_id") != c["cell_id"]:
        reasons.append("expected cell id missing or differs")
    if lifecycle_ok:
        r = R[0]
        if status in SUCCESS and r.get("outcome") != "COMPLETED":
            reasons.append("success status with receipt outcome %r" % r.get("outcome"))
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
        row.update(route=rec.get("route"), precision=rec.get("precision"), max_width_raw=rec.get("max_width"), delivered_max_width=(rec.get("certified") or {}).get("delivered_max_width"), reductions=(src.get("reductions") or {}).get("steps"), free_reduced=(src.get("reductions") or {}).get("free_reduced"), plan_totals=(src.get("plan") or {}).get("totals"), plan_order=(src.get("plan") or {}).get("order"),
                   plan_candidates=src.get("plan_candidates"), mechanisms=src.get("mechanisms"), binary64_admission=src.get("binary64_admission"), attempts=[{k: a.get(k) for k in ("route", "precision", "outcome", "stop", "stop_phase", "create_s", "forward_s", "reverse_s", "labels", "delta_max", "wall_s")} | {"counters": a.get("counters"), "counters_after_forward": a.get("counters_after_forward")} for a in (src.get("attempts") or [])], exact_fallback=(src.get("exact_fallback") or {}).get("status"), discovery_stop=(src.get("plan") or {}).get("discovery_stop"), diagnostic_present="diagnostic" in rec, live_at_stop=(rec.get("diagnostic") or {}).get("live"), plan_validation=(src.get("plan_validation") or {}).get("status"), memory_ledger=src.get("memory_ledger"), clock=src.get("clock"), execution=rec.get("execution"))
    if reasons:
        row["resolution"] = "NOT_ACCEPTED"; return row
    row.update(accepted=True, status=status, resolution="ACCEPTED"); return row
