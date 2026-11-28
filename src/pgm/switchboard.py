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


from .runtime.attempts import run_attempt, ledger_records as _ledger_records, kill_owned as _kill_owned, REFUSAL_OUTCOMES as _REFUSALS      # (compatibility names)


def _consistent_candidate(record):
    """the controller's own check of a returned candidate against its attempt record (the runtime applies the same predicate)"""
    return (record.get("accepted", True) is not False and record.get("outcome") not in _REFUSALS
            and not (record.get("cleanup") or {}).get("unresolved") and not (record.get("cleanup_final") or {}).get("unresolved"))
from .validation.publication import accepted_row as _accepted_row, merge_row, assemble, empty_rows as _empty


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
                result, record = run_attempt(dict(choice, expected_binding=binding), request, attempt_deadline, Path(temporary), number)
                attempts.append(record)
                if result is not None and not _consistent_candidate(record):
                    # defense in depth: a candidate whose terminal attempt state or cleanup record contradicts success is refused
                    record["rejected_inconsistent_candidate"] = True; record["outcome"] = record.get("outcome") if record.get("outcome") in _REFUSALS else "CLEANUP_UNRESOLVED"
                    result = None
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
                    merge_row(chosen, key, row)
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
    rows, outcome, guarantee, published, assembly_error = assemble(inventory, chosen, meta.get("cards"), witness, outcome)
    error = assembly_error or error
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
