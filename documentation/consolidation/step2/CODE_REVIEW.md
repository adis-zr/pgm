# Step 1 runtime and implementation review

Reviewed detached `f21b2d3` against `f8197e6`, concentrating on the runtime, worker/input/adapter seams, accepted policy, publication, relocation and alias behavior. The checkout and solver sources were not modified. The full test rerun is being recorded separately by the lead reviewer; this report claims only the two bounded probes below and source inspection.

## Findings

### S1 — Historical entry points can run an unrelated installed implementation (P2; introduced by Step 1)

Source: `code/cex/blockres/integrated.py:5–12`, with the same generated pattern in the other relocated-module shims.

The shim first imports any available `pgm`, and adds its own checkout's `src` only if that import fails. Consequently, invoking a historical script by its explicit path does not bind execution to the code at that path. An existing installed or editable `pgm` takes precedence. If that installation predates the relocation, the historical entry point fails before executing. If it contains the canonical module at another revision, the shim silently uses that other revision, including its module globals and arithmetic. This undermines the stated compatibility and source-identity guarantees; the explicit `PYTHONPATH` in the new qualification harness masks it.

Reproduced using the available venv, which has the older consolidation checkout installed editable:

```sh
/workspace/scratch/226d1e4428b0/consolidation-venv/bin/python -I \
  /workspace/scratch/226d1e4428b0/pgm-step1-review/code/cex/blockres/integrated.py --help
```

It fails with `ModuleNotFoundError: No module named 'pgm.algorithms'`, followed by the shim's `run_module` ImportError. The `-I` ensures no external `PYTHONPATH` selects this checkout; site-installed packages remain visible. Evidence: `probes/SHIM.stderr`.

Required fix before claiming historical entrypoint compatibility: bind source-checkout shims to their own canonical source tree, or explicitly detect and refuse a differently rooted imported `pgm`. Preserve the one-module-object alias within the selected implementation. Add a subprocess control with a deliberately conflicting importable `pgm` to prove both no silent revision substitution and the intended standalone checkout behavior.

### S2 — Cleanup skips registered workers when the supervisor has already died (P2; inherited, not a Step 1 regression)

Source: `src/pgm/runtime/attempts.py:40–75`, especially line 47. The equivalent old `_kill_owned` implementation exists in `f8197e6:src/pgm/switchboard.py`.

All emergency registry reconciliation is inside the `process.poll() is None` branch, and further inside the terminate-timeout branch. If the supervisor has already exited abruptly, `kill_owned` returns immediately even though its recorded worker group remains alive. `run_attempt` calls this helper before acceptance and again in its `finally`, so neither call repairs this case. A missing receipt refuses publication, but it does not enforce the declared owned-work cleanup or stop its ongoing computation after API return.

The probe starts the real retained supervisor around a 30-second sleeping child, waits for its durable SPAWNED record, kills only that supervisor, then calls the actual `kill_owned`. The registered child is alive both before and after the helper. The probe explicitly kills the owned group in its own `finally`, so no process was left behind by this review.

Reproduce:

```sh
PYTHONPATH=/workspace/scratch/226d1e4428b0/pgm-step1-review/src:/workspace/scratch/226d1e4428b0/pgm-step1-review/code \
  /workspace/scratch/226d1e4428b0/consolidation-venv/bin/python \
  /workspace/scratch/226d1e4428b0/step1_review/probes/probe_runtime_ownership.py
```

Evidence: `probes/RUNTIME_OWNERSHIP.json`: supervisor return code `-9`, child present before and after, `leaked: true`.

This is not evidence of an erroneous probability or a scored-run survivor. It is a remaining resource contract defect that should be repaired before claiming robust request ownership. Reconcile the durable registered subtree when supervisor completion cannot establish cleanup, regardless of whether the supervisor PID is still running. Continue to restrict signals to that invocation's registered groups and do not return a success if cleanup cannot be established.

## Positive findings and scope

- The accepted policy explicitly carries the historical targeted schedule and cap configuration. It invokes only the block adapter and assigns that sole PAC-capable attempt the full requested delta; the experimental portfolio retains its prospective disjoint shares. I found no repeated-attempt risk-budget reuse in the public controller.
- The worker parses the exact model once, captures original coordinates before adapter execution, checks the expected binding, and passes the same parsed object and binding through the new block and response seams. No source reread is needed in those adapter paths.
- The accepted block implementation's non-import changes inspected here are the optional parsed-model/binding seam. The arithmetic, certificate calculation and route logic in that implementation are unchanged. The response CLI extraction adds an in-memory result path and mirrors finalizer fields; no changed mathematical formula was identified in that extraction.
- The normalization boundary validates rational probability geometry, refuses duplicate/unexpected coordinates, preserves guarantee strength, requires positive mass, and checks simplex feasibility. Controller assembly separately checks cross-attempt consistency and performs final deadline suppression after assembly.
- Worker writes remain physically after the staged final clock sample. Public acceptance additionally requires a timely completed supervisor receipt and parent finalization, so a late write cannot become a public success through the inspected path.
- Backend memory globals remain request-isolated by worker processes. Direct adapter calls mutate those module globals, so they remain private low-level interfaces; I found no claim that concurrent in-process direct adapter calls are supported.

## Nonblocking maintainability note

`pgm.model.uai.read_uai` and `pgm.algorithms.structural.core.read_uai` currently retain separate copies of the exact parser. The default worker uses the former and inherited direct solver paths still use the latter. Their inspected semantics agree, but the claim in `model/uai.py` that every retained implementation reads through the one canonical parser is stronger than the code. Either use one function or narrow that statement; future validation fixes otherwise need to be kept in sync. This is not a demonstrated numerical regression.

## Disposition

No wrong marginal or PAC certificate was demonstrated. S1 is a reproducible new compatibility/source-binding regression. S2 is a reproducible inherited ownership defect still relevant to the consolidated runtime contract. Both can be fixed without changing inference arithmetic or benchmark policy. This review performed no benchmark run and no solver edits.
