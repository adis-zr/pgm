# Bounded completion: gate and supplement review

Reviewed head `0fe5f9cfcdb759c95c71cc76e537fd7b5727911b`, repair `9966821de97aaf6d2464e7069e822c2e46c10ca0`, supplement freeze `2bb9631f1f7d469bd8d270075492a66709c2e809`.

**Decision within this scope: the previously identified protocol and gate findings are closed. No additional merge blocker was found.** The original failed identity record remains intact; the separately declared supplement provides the repaired-runtime preservation evidence and the clean incident replay. Runtime safety and raw-coordinate verification are separate concurrent reviews.

## Independently reproduced

`RECOMPUTATION.json` records an independent computation from the committed compact supplement cells, complete terminal receipts, original analysis and recovered historical extract:

- Exactly 245 expected, observed and unique cell keys; no missing or extra cells.
- Exactly 245 terminal receipts; elapsed time, process outcome, return code, RSS and cleanup status agree with every compact cell.
- Charge **1,626.1058695330576 seconds**, below the prospectively declared 4,900 seconds.
- No failed recorded source identities or arm-closure checks. Every terminal receipt establishes an empty owned group, zero live nested groups and no unresolved cleanup.
- Accepted completes the same 45 tasks and experimental the same 54 tasks as the original run; no lost, gained or one-repeat-only task.
- The supplement's completion targets equal the original analysis, and both original FREEZE and ANALYSIS hashes match their recorded bindings.
- The one replay is DBN_11 / LIBDAI_BP / repeat 1, valid and complete in **1.9016795419884147 seconds** under the original comparator build/contract.
- The recovered 122 historical cells all bind to current model/evidence hashes. The historical 47-task success set has no loss in the supplemented experimental results.

The supplement declaration was committed in `9966821` before execution. Its actual freeze at `2bb9631` follows the committed raw-archive addition. The first freeze refusal is retained and accurately attributes the refusal to the untracked raw archive; it contains no scored cells. The current production source, tests and benchmark runner/analyzer have no diff from the qualification repair commit or the actual scored freeze. The archived qualification log states **109 passed, 39 subtests passed**; this is producer evidence, not a separate full qualification run by this reviewer.

## Targeted gate checks

I ran `tests/test_benchmark_validator.py` and the non-native-probe cases in `tests/test_benchmark_harness.py`: **21 passed, 2 native setup cases deselected**. Log: `TARGETED_TESTS.log`. No solver benchmark was executed and no implementation source was edited.

The exact-incident allowlist now removes only issue strings whose full job key is listed in `INCIDENTS.json` with evidence and disposition. The negative controls prove that no allowlist, or an additional unrelated failure, keeps the adjudicated gate failed. Original validity remains FAIL. The recorded entry explicitly acknowledges that the documentation-only attribution was not mechanically preserved, and chooses a clean replay rather than pretending otherwise.

The legacy internal-wall exception now applies only to non-completing statuses; a completing result past the 19.5-second allowance fails its contract. The amendment correctly acknowledges the four partial-publishing cases. The public reader now rejects CLEANUP_UNRESOLVED and nonempty cleanup/cleanup_final unresolved records.

`arm_closure_ok` now compares each pinned arm's source and active native hash inventories before and after a cell, and records differences on mismatch. Public arms check their actual active native inventories in addition to the checkout-wide source guard. This closes the previous omission of reference-root rechecks. The supplement only scores the two new public arms and the one BP replay, as declared.

## Promotion interpretation

The old `promotion_decision: HOLD` is not evidence that the supplement failed. It is computed from the deliberately preserved original strict validity failure and original 18 cost flags. Do not rewrite that history. If the runtime and raw reviews also pass, record a separate final reviewer decision accepting the supplemented preservation evidence and the known, explained consolidation overhead. That is consistent with the prospectively advisory overhead rule and the agreed separation of consolidation from broad speed optimization.

The existing 18 flags and timer decomposition remain part of the baseline. They neither establish a mathematical regression nor disappear because this cleanup review passes. No new policy, rates, model-specific routing or inference algorithm is warranted to close this phase.
