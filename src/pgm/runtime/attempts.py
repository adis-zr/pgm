"""One supervised backend attempt: owned process group, process-tree memory, absolute deadline, terminal receipt.

Moved from the first-stage switchboard unchanged in semantics: each attempt runs ``pgm.backends.worker`` under
the retained owned-tree supervisor (``pgm.supervision``, zero grace); acceptance requires an on-time exit, a
terminal COMPLETED receipt with empty owned and nested groups, and a bounded output file.  Cleanup is part of
the charged attempt and precedes every acceptance.
"""
from __future__ import annotations

from fractions import Fraction as F
import json
import os
from pathlib import Path
import subprocess
import sys
import time
import uuid

import psutil

from .. import policies


def ledger_records(path, *, tolerate_partial=False):
    """Read durable supervisor records; a trailing interrupted write is refused."""
    if not path.exists():
        return []
    records = []
    for line in path.read_text().splitlines():
        if not line.strip():
            continue
        try:
            records.append(json.loads(line))
        except ValueError:
            if not tolerate_partial:
                raise
    return records


def _utc_epoch(text):
    import calendar
    try:
        return calendar.timegm(time.strptime(text, "%Y-%m-%dT%H:%M:%SZ"))
    except (TypeError, ValueError):
        return None


def owned_groups(ledger):
    """This invocation's DURABLE ownership: the SPAWNED groups of the attempt ledger and every nested registration whose
    parent chain leads to this START (the supervisor's `<owner_dir>/groups.jsonl`).  Returns {pgid: identity} with the
    recorded leader pid and INCARNATION (creation time), plus whether a valid terminal receipt already establishes cleanup."""
    records = ledger_records(ledger, tolerate_partial=True)
    starts = [r for r in records if r.get("kind") == "START"]
    groups = {}
    for r in records:
        if r.get("kind") == "SPAWNED" and r.get("pgid") is not None:
            groups[r["pgid"]] = dict(pid=r.get("pid"), jid=r.get("jid"), create_time=r.get("leader_create_time"), spawned=_utc_epoch(r.get("spawn_utc")), source="SPAWNED")
    own = starts[-1] if starts else None
    if own is not None and own.get("owner_dir"):
        registrations = ledger_records(Path(own["owner_dir"]) / "groups.jsonl", tolerate_partial=True)
        parents = {r.get("jid"): r.get("parent_jid") for r in registrations}
        def owned(jid):
            visited = set()
            while jid is not None and jid not in visited:
                if jid == own["jid"]:
                    return True
                visited.add(jid)
                jid = parents.get(jid)
            return False
        for r in registrations:
            if r.get("pgid") is not None and owned(r.get("jid")):
                groups.setdefault(r["pgid"], dict(pid=r.get("pid"), jid=r.get("jid"), create_time=r.get("leader_create_time"), spawned=_utc_epoch(r.get("utc")), source="registry"))
    receipts = [r for r in records if r.get("kind") == "RECEIPT" and own is not None and r.get("jid") == own.get("jid")]
    receipt = receipts[-1] if receipts else None
    established = bool(receipt and receipt.get("cleanup_unresolved") is False and receipt.get("group_empty_at_receipt") is True
                       and receipt.get("nested_groups_live_at_receipt") == 0)
    return groups, established, receipt


INCARNATION_TOLERANCE_S = 0.01


def _verified_members(pgid, identity):
    """POSITIVE identification of the live members of a recorded group: the leader by its recorded incarnation (pid AND creation
    time); every other member by a parent chain to an already verified member, created no earlier than the leader.  A group id
    reused by a newer unrelated process (different creation time), a missing / malformed recorded identity, or a member without
    a verified parent chain is UNVERIFIED and is never signalled.  -> (verified, unverified, refusal_reason)"""
    from .supervise import group_members
    members = group_members(pgid)
    if not members:
        return [], [], None
    leader_pid = identity.get("pid"); recorded = identity.get("create_time")
    if not isinstance(leader_pid, int) or not isinstance(recorded, (int, float)):
        return [], sorted(members), "no recorded incarnation identity (pid + creation time) for this group"
    procs = {}
    for pid in members:
        try:
            procs[pid] = psutil.Process(pid)
        except psutil.Error:
            pass
    verified = set()
    try:
        if leader_pid in procs and abs(procs[leader_pid].create_time() - recorded) <= INCARNATION_TOLERANCE_S:
            verified.add(leader_pid)
    except psutil.Error:
        pass
    changed = True
    while changed:
        changed = False
        for pid, p in procs.items():
            if pid in verified:
                continue
            try:
                if p.ppid() in verified and p.create_time() >= recorded - INCARNATION_TOLERANCE_S:
                    verified.add(pid); changed = True
            except psutil.Error:
                pass
    unverified = sorted(pid for pid in members if pid not in verified)
    reason = None
    if unverified:
        reason = ("recorded leader incarnation is not alive: group id %d is held by a different process" % pgid) if leader_pid not in verified else "members without a verified parent chain to the owned leader"
    return sorted(verified), unverified, reason


def _kill_pids_and_wait(pids, wait_s):
    """signal POSITIVELY identified processes individually (never the whole group) and wait for them to disappear"""
    processes = []; unverified = set()
    for pid in pids:
        try:
            process = psutil.Process(pid)
            process.kill()             # psutil checks the captured process incarnation before signalling
            processes.append(process)
        except (psutil.NoSuchProcess, ProcessLookupError):
            pass
        except (psutil.AccessDenied, PermissionError):
            unverified.add(pid)        # inability to signal/inspect must remain unresolved
    deadline = time.monotonic() + wait_s
    while True:
        alive = set(unverified)
        for process in processes:
            try:
                if process.is_running() and process.status() != psutil.STATUS_ZOMBIE:
                    alive.add(process.pid)
            except psutil.NoSuchProcess:
                pass                  # ordinary exit between the liveness and status reads
            except psutil.AccessDenied:
                alive.add(process.pid)
        remaining = deadline - time.monotonic()
        if not alive or remaining <= 0:
            return sorted(alive)
        time.sleep(min(0.02, remaining))


def kill_owned(process, ledger, wait_s=0.5):
    """Terminate the supervisor if it is still running, then reconcile this invocation's durable ownership whenever a valid
    terminal receipt does not establish cleanup -- including when the supervisor has already exited or was killed.  A valid
    terminal receipt (owned tree empty, nothing unresolved) CLOSES ownership: no later scan or signal from its registrations.
    Otherwise every recorded group is checked member by member against the recorded process incarnation; only positively
    identified processes are signalled, individually; unverified members are reported and leave the attempt UNRESOLVED
    (fail closed).  Never signals the caller's own process group.  Returns the cleanup record (`unresolved` non-empty means
    success must be refused)."""
    record = dict(supervisor_alive_at_entry=process.poll() is None, receipt_established=False, groups=[], killed=[], unresolved=[], identity_refused=[])
    if process.poll() is None:
        process.terminate()
        try:
            process.wait(timeout=0.25)
        except subprocess.TimeoutExpired:
            pass
    own_pgid = os.getpgrp()
    try:
        groups, established, _receipt = owned_groups(ledger)
    except (OSError, ValueError, KeyError) as e:
        groups, established = {}, False
        record["ledger_error"] = str(e)[:200]
    record["receipt_established"] = established
    if not established:
        for pgid, identity in groups.items():
            if pgid == own_pgid:
                record["identity_refused"].append(dict(pgid=pgid, reason="caller's own process group")); continue
            verified, unverified, reason = _verified_members(pgid, identity)
            entry = dict(pgid=pgid, source=identity.get("source"), leader_pid=identity.get("pid"), recorded_create_time=identity.get("create_time"), verified=verified, unverified=unverified)
            if unverified:
                record["identity_refused"].append(dict(pgid=pgid, pids=unverified, reason=reason))
                record["unresolved"].append(dict(pgid=pgid, pids=unverified, reason="unverified members not signalled: " + str(reason)))
            if verified:
                still = _kill_pids_and_wait(verified, wait_s)
                entry["killed"] = [pid for pid in verified if pid not in still]; record["killed"] += entry["killed"]
                if still:
                    record["unresolved"].append(dict(pgid=pgid, pids=still, reason="identified processes survived the signal"))
            record["groups"].append(entry)
    if process.poll() is None:
        process.kill()
        try:
            process.wait(timeout=1)
        except subprocess.TimeoutExpired:
            record["unresolved"].append(dict(pgid=None, pids=[process.pid], reason="supervisor did not exit"))
    return record


REFUSAL_OUTCOMES = frozenset(("NOT_STARTED", "DEADLINE", "MEMORY", "BACKEND_EXIT", "OUTPUT_REFUSED", "CLEANUP_UNRESOLVED"))


def accepted_candidate(record):
    """the single terminal acceptance predicate: a staged candidate is accepted only when the attempt's terminal state and BOTH
    cleanup records (post-run and final) are consistent with success"""
    return (record.get("outcome") not in REFUSAL_OUTCOMES and not (record.get("cleanup") or {}).get("unresolved")
            and not (record.get("cleanup_final") or {}).get("unresolved") and (record.get("cleanup_final") or {}).get("unresolved") is not None)


def run_attempt(choice, request, deadline, directory, number):
    binding = choice.get("expected_binding")
    backend = choice["backend"]
    output = directory / (str(number) + "-" + backend + ".json")
    stderr = directory / (str(number) + "-" + backend + ".stderr")
    # A surrounding supervisor must still find this nested receipt after the
    # request's TemporaryDirectory is deleted.
    ledger_root = Path(os.environ.get("GBIDI_OWNER_DIR", str(directory)))
    ledger = ledger_root / ("api-" + uuid.uuid4().hex + ".jsonl")
    policy = policies.get(getattr(request, "policy", policies.DEFAULT_POLICY))
    delta = request.delta * policy.RISK_SHARES.get(backend, F(0))
    worker = [sys.executable, "-m", "pgm.backends.worker", "--backend", backend,
              "--input", str(request.model), "--output", str(output), "--deadline", repr(deadline),
              "--epsilon", str(request.epsilon), "--delta", str(delta), "--seed", str(request.seed),
              "--memory-mib", str(request.memory_mib), "--mode", request.mode,
              "--structural-route", choice["structural_route"], "--policy", policy.NAME]
    if choice.get("configuration"):
        worker += ["--configuration", json.dumps(choice["configuration"], sort_keys=True)]
    if binding:
        worker += ["--expected-binding", json.dumps(binding, sort_keys=True)]
    env = os.environ.copy()
    src = str(Path(__file__).resolve().parents[2])
    env["PYTHONPATH"] = src + os.pathsep + env.get("PYTHONPATH", "")
    for key in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS", "NUMEXPR_NUM_THREADS"):
        env[key] = "1"
    start = time.monotonic()
    record = dict({k: v for k, v in choice.items() if k != "expected_binding"}, delta=str(delta), started_s=start, allowance_s=max(0, deadline-start),
                  outcome="NOT_STARTED", peak_tree_rss_bytes=0, wall_s=0.0)
    if start >= deadline:
        record["outcome"] = "DEADLINE"
        return None, record
    process = None; candidate = None
    try:
        cmd = [sys.executable, "-m", "pgm.supervision", "--ledger", str(ledger),
               "--scope", "public-api", "--job", str(number) + "-" + backend,
               "--timeout", repr(max(0.0, deadline-start)), "--interval", "0.01",
               "--mem-gib", repr(request.memory_mib / 1024), "--", *worker]
        with stderr.open("wb") as log:
            process = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=log, env=env)
            while process.poll() is None:
                rss = psutil.Process().memory_info().rss
                try:
                    root = psutil.Process(process.pid)
                    for child in [root] + root.children(recursive=True):
                        try:
                            rss += child.memory_info().rss
                        except psutil.Error:
                            pass
                except psutil.Error:
                    pass
                record["peak_tree_rss_bytes"] = max(record["peak_tree_rss_bytes"], rss)
                now = time.monotonic()
                if rss > request.memory_mib * (1 << 20) or now >= deadline:
                    record["outcome"] = "MEMORY" if rss > request.memory_mib * (1 << 20) else "DEADLINE"
                    record["cleanup_interrupt"] = kill_owned(process, ledger)
                    break
                time.sleep(min(0.01, max(0, deadline-now)))
        # Cleanup is part of the charged attempt and precedes every acceptance (durable ownership reconciled even when the
        # supervisor already exited).  Nothing is returned from inside this block: the candidate is STAGED only.
        record["cleanup"] = kill_owned(process, ledger)
        ended = time.monotonic()
        record.update(wall_s=ended-start, returncode=process.returncode)
        records = ledger_records(ledger)
        receipts = [r for r in records if r.get("kind") == "RECEIPT"]
        receipt = receipts[-1] if receipts else None
        record["supervisor_receipt"] = receipt
        if record["cleanup"]["unresolved"]:
            record.update(outcome="CLEANUP_UNRESOLVED", reason="owned process groups could not be reconciled")
        elif record["outcome"] != "NOT_STARTED":
            pass
        elif ended > deadline:
            record["outcome"] = "DEADLINE"
        elif not (process.returncode == 0 and receipt
                  and receipt.get("outcome") == "COMPLETED"
                  and receipt.get("group_empty_at_receipt") is True
                  and receipt.get("nested_groups_live_at_receipt") == 0
                  and receipt.get("cleanup_unresolved") is False):
            reason = receipt.get("outcome", "MISSING_RECEIPT") if receipt else "MISSING_RECEIPT"
            record.update(outcome="MEMORY" if reason == "MEMORY_KILL" else "BACKEND_EXIT", reason=reason)
        elif not output.exists() or output.stat().st_size > request.memory_mib * (1 << 18):
            record["outcome"] = "OUTPUT_REFUSED"
        else:
            staged = json.loads(output.read_text())
            record.update(outcome=staged.get("outcome", "REFUSED"), published=staged.get("published", 0),
                          guarantee=staged.get("guarantee"), mechanism=staged.get("mechanism"),
                          worker_wall_s=staged.get("wall_s"), worker_timings=staged.get("runtime_timings"))
            candidate = staged
    except (OSError, ValueError, subprocess.SubprocessError) as e:
        record.update(outcome="BACKEND_EXIT", reason=str(e)[:250]); candidate = None
    # ---- TERMINAL ACCEPTANCE: final cleanup and final accounting are known before the ONE acceptance decision.
    if process is not None:
        final = kill_owned(process, ledger)
        record["cleanup_final"] = final
        if final["unresolved"]:
            record.update(outcome="CLEANUP_UNRESOLVED", reason="owned process groups could not be reconciled at exit")
    else:
        record["cleanup_final"] = dict(unresolved=[], note="no supervisor process was started")
    if stderr.exists():
        with stderr.open("rb") as f:
            f.seek(max(0, stderr.stat().st_size-1200))
            record["stderr_tail"] = f.read().decode(errors="replace")
    record["wall_s"] = time.monotonic()-start
    record["accepted"] = bool(candidate is not None and accepted_candidate(record))
    if candidate is not None and not record["accepted"]:
        record["staged_candidate_rejected"] = dict(outcome=candidate.get("outcome"), published=candidate.get("published"), reason="terminal attempt state or cleanup contradicts success")
    return (candidate if record["accepted"] else None), record
