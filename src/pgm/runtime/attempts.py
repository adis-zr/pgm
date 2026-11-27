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


def kill_owned(process, ledger):
    """Let the supervisor reconcile first; emergency cleanup uses its registry.

    A leader exiting before our first RSS sample cannot hide its orphaned child:
    ownership is a process group recorded by the supervisor, not a sampled PID
    ancestry. Never signal the caller's process group.
    """
    if process.poll() is None:
        process.terminate()
        try:
            process.wait(timeout=0.25)
        except subprocess.TimeoutExpired:
            # The supervisor may itself be stuck during cleanup. Reconcile only
            # the groups registered under this invocation's START identity.
            from .supervision import implementation
            supervisor = implementation()
            records = ledger_records(ledger, tolerate_partial=True)
            starts = [r for r in records if r.get("kind") == "START"]
            if starts:
                own = starts[-1]
                registrations = ledger_records(Path(own["owner_dir"]) / "groups.jsonl", tolerate_partial=True)
                parents = {r["jid"]: r.get("parent_jid") for r in registrations}
                def owned(jid):
                    visited = set()
                    while jid is not None and jid not in visited:
                        if jid == own["jid"]:
                            return True
                        visited.add(jid)
                        jid = parents.get(jid)
                    return False
                groups = {r["pgid"] for r in records if r.get("kind") == "SPAWNED"}
                groups.update(r["pgid"] for r in registrations if owned(r["jid"]))
                for pgid in groups:
                    supervisor.kill_group_and_wait(pgid, wait_s=0.1)
            process.kill()
            process.wait(timeout=1)


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
        # Cleanup is part of the charged attempt and precedes every acceptance.
        kill_owned(process, ledger)
        ended = time.monotonic()
        record.update(wall_s=ended-start, returncode=process.returncode)
        records = ledger_records(ledger)
        receipts = [r for r in records if r.get("kind") == "RECEIPT"]
        receipt = receipts[-1] if receipts else None
        record["supervisor_receipt"] = receipt
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
            kill_owned(process, ledger)
        if stderr.exists():
            with stderr.open("rb") as f:
                f.seek(max(0, stderr.stat().st_size-1200))
                record["stderr_tail"] = f.read().decode(errors="replace")
        record["wall_s"] = time.monotonic()-start
