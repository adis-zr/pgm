# Independent public API review

Scope: the new `pgm` request/result API, structural planner, adapters, resource ownership, request-level risk allocation and publication boundary. This is a correctness review with tiny fixtures, not an external performance benchmark or a claim that the switchboard has demonstrated scaling advantages.

## Findings and disposition

1. **Combined partial boxes could miss the simplex.** Two separately valid partial backend results can supply state 0 = 4/5 and state 1 = 4/5. Each backend's unknown other state leaves a feasible box; the combined full row does not. The controller now checks the assembled per-variable box with missing states left at [0,1] and suppresses the result on inconsistency. The regression constructs both inputs through the real backend normalizer.
2. **Explicit query inventory was overwritten on a planning refusal.** The planner's complete inventory replaced the caller's requested subset. The controller now preserves explicit queries, including when the deadline expires before parsing.
3. **Backend COMPLETE survived guarantee filtering.** Exact-mode requests could discard every deterministic/PAC coordinate yet inherit COMPLETE and an empty-set EXACT label. Completion is now recomputed from the requested inventory, positive-mass witness and published coordinates. All three weaker-mode combinations are tested.
4. **Sampled ancestry could miss an orphan.** The original parent monitor recorded descendants only during its 10 ms RSS polls. A worker that spawned a child and immediately exited could leave unowned work after the parent accepted output. Each attempt now runs through the retained `gbidi.supervise` ownership protocol, via `pgm.supervision` with zero deadline grace. Completion requires a terminal COMPLETED receipt, empty direct and registered nested groups, and an on-time attempt. Parent deadline/RSS cancellation lets that supervisor reconcile, with bounded emergency cleanup restricted to the registered attempt subtree. A real fast-exit orphan is killed and its result refused.
5. **Nested receipt lifetime.** When the API itself runs under a supervisor, its attempt ledgers live under the inherited ownership directory rather than the temporary request directory. An actual nested invocation verifies that the outer supervisor finds the completed receipt after request cleanup, and writes no substitute cleanup receipt.
6. **Invalid query classification.** Domain-invalid queries now report INVALID_TASK before launching a worker, rather than CERTIFICATE_DEFECT after model binding.

The process change is in `src/pgm/supervision.py` and the `run_attempt`/`_kill_owned` portion of `src/pgm/switchboard.py`. The parent implemented the controller inventory/geometry/completion fixes. No numerical inference mathematics or benchmark-specific dispatch rules were changed by this review agent.

## Independent checks

`tests/test_public_api.py`: 21 checks pass. They include a real asymmetric two-variable model independently enumerated with rational arithmetic (Z = 47), evidence and explicit observed-coordinate queries, zero-mass nonpublication, exact endpoint/radius containment, request-level risk allocations, mode filtering, combined simplex feasibility, explicit inventory retention, final timestamp suppression, a real insufficient-memory refusal, fast-exit orphan cleanup, timeout cleanup, and nested ledger persistence.

The combined API/backend/planning/conflict suite passes 42/42 (1.51 s); the API suite itself passes 21/21 (1.44 s). One initial test launch used an incorrect relative interpreter path and did not run tests. Three deliberately failing mode-filtering regressions exposed finding 3 before the parent corrected it. No external benchmark was run.

## Scope limits

- The public contract certifies requested coordinates. Combined point estimates need not form a normalized probability vector merely because their interval box intersects the simplex. A stronger vector promise would require a final J-box simplex step or explicit withholding; this distinction was sent to the parent for documentation/policy.
- Process RSS enforcement is sampled, with the API parent's resident memory included. It is not an allocator-level proof preventing every transient peak. Timing checks suppress late publication and cleanup is charged; this is not an operating-system real-time scheduling guarantee.
- The retained engines remain responsible for their local certificates. The controller allocates fixed disjoint failure-budget shares summing to the request delta, never accepts a weaker requested guarantee, and uses the union bound when choosing among certified backend results. The tests do not re-prove all inherited engines.
