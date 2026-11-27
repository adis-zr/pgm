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
    recorded leader pid and spawn time, plus whether a valid terminal receipt already establishes cleanup."""
    records = ledger_records(ledger, tolerate_partial=True)
    starts = [r for r in records if r.get("kind") == "START"]
    groups = {}
    for r in records:
        if r.get("kind") == "SPAWNED" and r.get("pgid") is not None:
            groups[r["pgid"]] = dict(pid=r.get("pid"), jid=r.get("jid"), spawned=_utc_epoch(r.get("spawn_utc")), source="SPAWNED")
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
                groups.setdefault(r["pgid"], dict(pid=r.get("pid"), jid=r.get("jid"), spawned=_utc_epoch(r.get("utc")), source="registry"))
    receipts = [r for r in records if r.get("kind") == "RECEIPT" and own is not None and r.get("jid") == own.get("jid")]
    receipt = receipts[-1] if receipts else None
    established = bool(receipt and receipt.get("cleanup_unresolved") is False and receipt.get("group_empty_at_receipt") is True
                       and receipt.get("nested_groups_live_at_receipt") == 0)
    return groups, established, receipt


def _identity_members(pgid, identity, slack_s=5.0):
    """the live members of a recorded group that are OURS: created no earlier than the recorded spawn (a reused pgid of an
    unrelated, older process is never signalled); -> (ours, foreign)"""
    from .supervise import group_members
    ours, foreign = [], []
    spawned = identity.get("spawned")
    for pid in group_members(pgid):
        try:
            created = psutil.Process(pid).create_time()
        except psutil.Error:
            continue
        if spawned is None or created >= spawned - slack_s:
            ours.append(pid)
        else:
            foreign.append(pid)
    return ours, foreign


def kill_owned(process, ledger, wait_s=0.5):
    """Terminate the supervisor if it is still running, then RECONCILE this invocation's durable ownership whenever a valid
    terminal receipt does not establish cleanup -- including when the supervisor has already exited or was killed (repair R1).
    Only this invocation's registered groups and their descendants are signalled, after an identity check against the recorded
    spawn; a stale reused pgid is reported, not signalled.  Bounded; returns the cleanup record (`unresolved` non-empty means
    success must be refused).  Never signals the caller's own process group."""
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
    from .supervise import kill_group_and_wait, group_members
    for pgid, identity in groups.items():
        if pgid == own_pgid:
            record["identity_refused"].append(dict(pgid=pgid, reason="caller's own process group"))
            continue
        ours, foreign = _identity_members(pgid, identity)
        entry = dict(pgid=pgid, source=identity.get("source"), leader_pid=identity.get("pid"), live_at_entry=ours, foreign=foreign)
        if foreign:
            record["identity_refused"].append(dict(pgid=pgid, pids=foreign, reason="members older than the recorded spawn (reused group id)"))
        if ours:
            kill_group_and_wait(pgid, wait_s=wait_s)
            still = [pid for pid in group_members(pgid) if pid in ours]
            entry["killed"] = [pid for pid in ours if pid not in still]
            record["killed"] += entry["killed"]
            if still:
                record["unresolved"].append(dict(pgid=pgid, pids=still))
        record["groups"].append(entry)
    if process.poll() is None:
        process.kill()
        try:
            process.wait(timeout=1)
        except subprocess.TimeoutExpired:
            record["unresolved"].append(dict(pgid=None, pids=[process.pid], reason="supervisor did not exit"))
    return record


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
    process = None
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
                    kill_owned(process, ledger)
                    break
                time.sleep(min(0.01, max(0, deadline-now)))
        # Cleanup is part of the charged attempt and precedes every acceptance (durable ownership reconciled even when the
        # supervisor already exited; unresolved ownership refuses success).
        record["cleanup"] = kill_owned(process, ledger)
        ended = time.monotonic()
        record.update(wall_s=ended-start, returncode=process.returncode)
        records = ledger_records(ledger)
        receipts = [r for r in records if r.get("kind") == "RECEIPT"]
        receipt = receipts[-1] if receipts else None
        record["supervisor_receipt"] = receipt
        if record["cleanup"]["unresolved"]:
            record.update(outcome="CLEANUP_UNRESOLVED", reason="owned process groups could not be reconciled")
            return None, record
        if record["outcome"] != "NOT_STARTED":
            return None, record
        if ended > deadline:
            record["outcome"] = "DEADLINE"
            return None, record
        if not (process.returncode == 0 and receipt
                and receipt.get("outcome") == "COMPLETED"
                and receipt.get("group_empty_at_receipt") is True
                and receipt.get("nested_groups_live_at_receipt") == 0
                and receipt.get("cleanup_unresolved") is False):
            reason = receipt.get("outcome", "MISSING_RECEIPT") if receipt else "MISSING_RECEIPT"
            record.update(outcome="MEMORY" if reason == "MEMORY_KILL" else "BACKEND_EXIT", reason=reason)
            return None, record
        if not output.exists() or output.stat().st_size > request.memory_mib * (1 << 18):
            record["outcome"] = "OUTPUT_REFUSED"
            return None, record
        result = json.loads(output.read_text())
        record.update(outcome=result.get("outcome", "REFUSED"), published=result.get("published", 0),
                      guarantee=result.get("guarantee"), mechanism=result.get("mechanism"),
                      worker_wall_s=result.get("wall_s"))
        return result, record
    except (OSError, ValueError, subprocess.SubprocessError) as e:
        record.update(outcome="BACKEND_EXIT", reason=str(e)[:250], wall_s=time.monotonic()-start)
        return None, record
    finally:
        if process is not None:
            final = kill_owned(process, ledger)
            record["cleanup_final"] = final
            if final["unresolved"] and record.get("outcome") not in ("CLEANUP_UNRESOLVED",):
                record.update(outcome="CLEANUP_UNRESOLVED", reason="owned process groups could not be reconciled at exit")
        if stderr.exists():
            with stderr.open("rb") as f:
                f.seek(max(0, stderr.stat().st_size-1200))
                record["stderr_tail"] = f.read().decode(errors="replace")
        record["wall_s"] = time.monotonic()-start
