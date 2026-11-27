"""One resource-owned controller over isolated retained algorithms.

The controller owns the request-level absolute deadline, the risk budget, the
original inventory and the final publication boundary.  WHICH backends run, in
which order, with which allowance fraction and which prospective delta share is
the selected public POLICY (``pgm.policies``): ``accepted`` (default) runs the
accepted engine once with its benchmarked configuration; ``experimental`` is
the frozen ``structural-portfolio-1`` switchboard.  Only one backend runs at a
time; each is attempted at most once; a refusal permits the policy's next
candidate within the SAME request deadline.  No outcome from another backend
or benchmark is consulted.
"""
from __future__ import annotations
from fractions import Fraction as F
from pathlib import Path
import json
import os
import subprocess
import sys
import tempfile
import time
import math
import psutil

from .contracts import InferenceRequest, InferenceResult
from .planning import inspect_model, PlanningRefused
from . import policies
from .policies import experimental as _experimental

# Compatibility names of the frozen experimental portfolio (tests and the review reference them here).
POLICY_VERSION = _experimental.VERSION
NATIVE_ROWS_PER_SECOND = _experimental.NATIVE_ROWS_PER_SECOND
RISK_SHARES = _experimental.RISK_SHARES
FINAL_RESERVE_SECONDS = 0.15


def candidate_plan(meta, request, remaining, policy=None):
    """Ordered candidates of the selected public policy (default: the request's policy), without allocating a solver."""
    return policies.get(policy or getattr(request, "policy", policies.DEFAULT_POLICY)).candidates(meta, request, remaining)


def _ledger_records(path, *, tolerate_partial=False):
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


def _kill_owned(process, ledger):
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
            records = _ledger_records(ledger, tolerate_partial=True)
            starts = [r for r in records if r.get("kind") == "START"]
            if starts:
                own = starts[-1]
                registrations = _ledger_records(Path(own["owner_dir"]) / "groups.jsonl", tolerate_partial=True)
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
    backend = choice["backend"]
    output = directory / (str(number) + "-" + backend + ".json")
    stderr = directory / (str(number) + "-" + backend + ".stderr")
    # A surrounding supervisor must still find this nested receipt after the
    # request's TemporaryDirectory is deleted.
    import uuid
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
    env = os.environ.copy()
    src = str(Path(__file__).resolve().parent.parent)
    env["PYTHONPATH"] = src + os.pathsep + env.get("PYTHONPATH", "")
    for key in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS", "NUMEXPR_NUM_THREADS"):
        env[key] = "1"
    start = time.monotonic()
    record = dict(choice, delta=str(delta), started_s=start, allowance_s=max(0, deadline-start),
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
                    _kill_owned(process, ledger)
                    break
                time.sleep(min(0.01, max(0, deadline-now)))
        # Cleanup is part of the charged attempt and precedes every acceptance.
        _kill_owned(process, ledger)
        ended = time.monotonic()
        record.update(wall_s=ended-start, returncode=process.returncode)
        records = _ledger_records(ledger)
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
            _kill_owned(process, ledger)
        if stderr.exists():
            with stderr.open("rb") as f:
                f.seek(max(0, stderr.stat().st_size-1200))
                record["stderr_tail"] = f.read().decode(errors="replace")
        record["wall_s"] = time.monotonic()-start


def _empty(inventory):
    return [{"variable": v, "var": v, "state": a, "guarantee": "NOT_PUBLISHED"} for v, a in inventory]


def _accepted_row(raw, mode, epsilon):
    label = raw.get("guarantee", "NOT_PUBLISHED")
    if label == "NOT_PUBLISHED" or (mode == "exact" and label != "EXACT") or (mode == "deterministic" and label == "PAC"):
        return None
    if label not in {"EXACT", "DETERMINISTIC", "PAC"}:
        raise ValueError("unrecognized published guarantee")
    lo, hi, point = (F(raw[k]) for k in ("lo", "hi", "point"))
    if not 0 <= lo <= point <= hi <= 1 or max(point-lo, hi-point) > epsilon:
        raise ValueError("invalid published enclosure")
    if label == "EXACT" and lo != hi:
        raise ValueError("inexact EXACT publication")
    return dict(raw, lo=str(lo), hi=str(hi), point=str(point))


def solve(request: InferenceRequest) -> InferenceResult:
    start = time.monotonic()
    deadline = start + request.budget
    work_deadline = deadline - min(FINAL_RESERVE_SECONDS, request.budget / 10)
    policy = policies.get(request.policy)
    inventory, binding, attempts, chosen, meta = list(request.queries or ()), {}, [], {}, {}
    witness = False
    outcome = "REFUSED"
    error = None
    try:
        meta = inspect_model(request.model, deadline=work_deadline, memory_bytes=request.memory_mib << 20, forecast=policy.NEEDS_FORECAST)
        binding = meta["binding"]
        cards, evidence = meta["cards"], meta["evidence"]
        inventory = list(request.queries) if request.queries is not None else [(v,a) for v,c in enumerate(cards) if v not in evidence for a in range(c)]
        if any(v < 0 or v >= len(cards) or a < 0 or a >= cards[v] for v,a in inventory):
            raise PlanningRefused("INVALID_TASK", "query outside original model domain", inventory=inventory, metadata=meta)
        query_set = set(inventory)
        choices = candidate_plan(meta, request, max(0, work_deadline-time.monotonic()))          # dispatches to the request's policy (tests may substitute the plan)
        with tempfile.TemporaryDirectory(prefix="pgm-infer-") as temporary:
            for number, choice in enumerate(choices):
                now = time.monotonic()
                if now >= work_deadline:
                    break
                attempt_deadline = now + (work_deadline-now) * choice["allowance_fraction"]
                result, record = run_attempt(choice, request, attempt_deadline, Path(temporary), number)
                attempts.append(record)
                if result is None:
                    outcome = record["outcome"]
                    continue
                if result.get("binding") != binding:
                    raise ValueError("input identity changed across an inference attempt")
                outcome = result.get("outcome", "REFUSED")
                if outcome == "ZERO_EVIDENCE":
                    chosen = {}; witness = False
                    break
                if result.get("positive_mass_witness") is True:
                    witness = True
                    for v,a in inventory:
                        if v in evidence:
                            value = str(int(a == evidence[v]))
                            chosen[(v,a)] = dict(variable=v,var=v,state=a,lo=value,hi=value,point=value,guarantee="EXACT")
                for raw in result.get("answers", []):
                    key = (raw.get("variable", raw.get("var")), raw.get("state"))
                    if key not in query_set:
                        continue
                    row = _accepted_row(raw, request.mode, request.epsilon)
                    if row is None:
                        continue
                    prior = chosen.get(key)
                    if prior is not None and max(F(prior["lo"]),F(row["lo"])) > min(F(prior["hi"]),F(row["hi"])):
                        raise ValueError("conflicting certified coordinate enclosures")
                    rank = {"EXACT": 0, "DETERMINISTIC": 1, "PAC": 2}
                    score = (rank[row["guarantee"]], F(row["hi"])-F(row["lo"]))
                    if prior is None or score < (rank[prior["guarantee"]], F(prior["hi"])-F(prior["lo"])):
                        chosen[key] = row
                if witness and len(chosen) == len(inventory):
                    outcome = "COMPLETE"
                    break
    except PlanningRefused as e:
        outcome = getattr(e,"kind","REFUSED"); error = str(e)
        if request.queries is None:
            inventory = list(getattr(e, "metadata", {}).get("unobserved_inventory", getattr(e,"inventory", inventory)) or inventory)
    except (OSError, ValueError, StopIteration, OverflowError) as e:
        outcome = "INVALID_TASK" if not binding else "CERTIFICATE_DEFECT"
        error = str(e)[:500]; chosen = {}
    rows = [chosen.get((v,a), dict(variable=v,var=v,state=a,guarantee="NOT_PUBLISHED")) for v,a in inventory]
    # Different individually sound partial boxes must still form a feasible
    # delivered box. Missing/unrequested states retain [0,1], never zero mass.
    if meta.get("cards"):
        by_variable = {}
        for row in rows:
            if row["guarantee"] != "NOT_PUBLISHED":
                by_variable.setdefault(row["variable"], []).append(row)
        for variable, group in by_variable.items():
            lower = sum((F(r["lo"]) for r in group), F(0))
            upper = sum((F(r["hi"]) for r in group), F(0)) + meta["cards"][variable]-len(group)
            if not lower <= 1 <= upper:
                outcome = "CERTIFICATE_DEFECT"; error = "combined coordinate box misses the simplex"
                rows = _empty(inventory); chosen = {}; break
    labels = {r["guarantee"] for r in rows if r["guarantee"] != "NOT_PUBLISHED"}
    published = sum(r["guarantee"] != "NOT_PUBLISHED" for r in rows)
    if witness and published == len(inventory) and outcome not in {"CERTIFICATE_DEFECT", "INVALID_TASK", "ZERO_EVIDENCE"}:
        outcome = "COMPLETE"
    elif published:
        outcome = "PARTIAL"
    elif outcome == "COMPLETE":
        outcome = "REFUSED"
    guarantee = ("EXACT" if labels <= {"EXACT"} else "DETERMINISTIC" if labels <= {"EXACT","DETERMINISTIC"} else "PAC") if outcome == "COMPLETE" else "PARTIAL" if published else "NONE"
    result = dict(api_version="1", policy=policy.NAME, policy_version=policy.VERSION, policy_record=policy.record(), outcome=outcome, guarantee=guarantee,
                  input=str(request.model), binding=binding, epsilon=str(request.epsilon), delta=str(request.delta),
                  mode=request.mode, seed=request.seed, K=len(inventory), published=published, answers=rows,
                  positive_mass_witness=witness, backend=attempts[-1]["backend"] if attempts else None,
                  attempts=attempts, requested_budget_s=request.budget, memory_mib=request.memory_mib,
                  risk_allocations={k:str(v) for k,v in policy.risk_allocation(request).items()},
                  error=error, planning={k:v for k,v in meta.items() if k not in {"inventory","all_inventory","unobserved_inventory","cards","evidence","conditioned_scopes","scopes"}},
                  max_published_radius=max((float(max(F(r["point"])-F(r["lo"]),F(r["hi"])-F(r["point"]))) for r in rows if r["guarantee"] != "NOT_PUBLISHED"), default=None))
    now = time.monotonic()
    if now > deadline:
        result.update(outcome="DEADLINE", guarantee="NONE", published=0, answers=_empty(inventory), max_published_radius=None)
    result.update(wall_s=now-start, hard_deadline_respected=now <= deadline)
    return InferenceResult(result)
