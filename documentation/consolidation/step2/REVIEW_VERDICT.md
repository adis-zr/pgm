# Review of consolidation step 1

Reviewed branch: `consolidate/production-layout`, verified remote head `f21b2d30899f50b2223cc91351c23784e7b00d7d`. Main remains `d6d751d5a13cb48d0d8175df744ba2f95eef1b9f`. Source was fetched into a detached checkout. No solver source was edited and no external benchmark was run.

**Verdict: retain the architecture and extraction. Step 1 is substantively implemented, but its qualification is not yet sufficient for acceptance, and step 2 is not executable as submitted.** Resolve the bounded runtime/qualification/preflight findings below inside the next substantive pass, then run the amended preservation experiment. Another architecture rewrite or a report-only closeout round is unnecessary.

## Evidence independently reproduced

- All **69 portable tests and 39 subtests pass** under the new source on Linux, with freshly built Clang 19 kernels and an explicit external native cache.
- All **16 deterministic characterization cases match** the pinned reference. The two wall-limited cases retain the checked invariants.
- The archived Mac response-prefix record differs from this Linux execution in ten witness-bound fields at floating-point rounding scale. The native trajectory/counters remain identical. I regenerated both response-prefix cases through the old `f8197e6` implementation on the same Linux host: **every compared field is identical between old and new**. The cross-platform differences are not evidence of a refactor regression; retain both records and use same-host comparisons for attribution.
- The relocation-stage diff is exactly **156 removed plus 148 added lines across 47 mappings**, consisting of import, path and resource-location changes. This supports the narrow relocation claim, not a claim that every change in the seven-commit branch is purely a file move.
- The accepted default uses the intended targeted engine configuration and one full request-level PAC allocation. The experimental policy retains its separate allocation. The worker/backend seams inspected show no demonstrated wrong marginal, duplicated PAC allowance or changed certificate formula.

## Findings that must be addressed

| ID | Finding | Consequence and required action |
|---|---|---|
| R1 | `runtime/attempts.py:47` skips registry reconciliation when the supervisor has already died. | An injected supervisor SIGKILL leaves its registered worker alive after `kill_owned` returns. This is inherited from the previous implementation, not newly introduced by relocation. Reconcile the owned invocation when terminal cleanup cannot be established, even if the supervisor PID has exited. |
| R2 | Historical alias shims import any installed `pgm` before selecting their own checkout. | An older editable install causes an explicit new-checkout command to fail; another installation can silently supply the wrong revision. Bind compatibility execution to its intended canonical checkout, or explicitly refuse a conflicting already-imported package. |
| R3 | The wheel gate accepts any dictionary-shaped worker result, ignores some native/cache checks, and exits zero after `FAIL`. | Evaluating its exact predicate with all four workers set to exit 1 and return REFUSED still yields PASS. The archived workers themselves did complete, but the gate is not reliable. Assert expected success, inventory, guarantee and branch; make failures propagate to the shell. Exercise the native stream and real cache override. |
| R4 | The inherited-control classifier treats any failure in a statically record-dependent control as BLOCKED. | A new RuntimeError can be hidden as a missing fixture, even when no missing-file evidence exists. Classify the actual failure; static dependencies are diagnostic metadata. Unexpected failures/timeouts must fail required qualification. |
| R5 | One CBI fixture is loaded at module import. | Its absence prevents all 23 test functions from collecting, although 22 do not use it. Isolate the fixture-dependent test and run the portable 22. Document the real H4/CBI fixture overrides; `PGM_RECORDS_ROOT` does not cover them as claimed. |
| B1 | The benchmark freeze still resolves structural build files under deleted `code/cex/newarm` locations and assumes module-local caches. | Clean setup cannot freeze reliably. With the supported external cache, my successful native build is followed by a false “build heat-bath kernel” refusal. Resolve and freeze the actual active source/build/cache artifacts used by each arm. |
| B2 | The submitted step-2 experiment runs no pinned accepted-reference arm on the current host. | Historical cells are useful coverage targets, but cannot isolate a refactor's effect from host/runtime/timing changes. Add a separately pinned, executed reference under the same external contract. |
| B3 | The full experimental preservation target, policy/risk validation and cost comparisons are not executable gates. | A 27/29 check can miss losses elsewhere in the 47-task portfolio success set. Bind the complete prior results, validate the requested policy and publication contract, check partial published rows where a comparator exists, and emit explicit gate decisions. |

The ownership probe cleans up its sleeping child in its own finalizer; no process was deliberately left running. No archived scored-run survivor or wrong probability is inferred from that fault injection.

## Qualification claims to narrow

The 51 archived DGP controls appear genuinely blocked by absent inputs; the classifier defect is not evidence that those 51 concealed a numerical bug. They also have not been proved to pass with those inputs available.

The specialist log contains five failed H4 tests and one CBI **module collection error**, not six independently collected blocked tests. Its coverage loss is larger than that wording suggests. `QUALIFICATION.json` says `all_commands_exit_zero: true` while recording the specialist command's exit 1; the aggregate must accurately describe required, blocked and failed checks. The combined shell currently does not reliably fail when a required check fails.

The wheel excludes production campaign dependencies, but still packages specialist helper scripts. Its archived relocation record says the stream library does not exist; merely including its C++ source does not demonstrate installed stream execution. The specialist import probes are not solver/checker conformance tests. These distinctions should be corrected without deleting useful historical methods.

There are also two copies of the exact UAI parser, in `model.uai` and `algorithms.structural.core`. The public worker uses one; inherited direct entrypoints can use the other. Consolidate their definition or narrow the “one canonical reader” claim. This is a maintainability issue, not a demonstrated numerical regression.

## Step-2 decision

Do not run the submitted four-arm plan unchanged or merge this branch yet. Make a committed pre-run amendment after fixing R1–R5 and the harness preflight. The minimum useful matched experiment is:

1. pinned accepted standalone reference;
2. new public accepted policy;
3. new public experimental policy;
4. libDAI junction tree;
5. libDAI BP.

That is **61 × 5 × 2 = 610 cells**. All 61 are exposed regression inputs. Keep the old55/former-eval6 groups only as historical provenance. Historical accepted successes, current reference successes and the previous 47-task portfolio success set are separate checks. Gains are reported rather than forbidden by an exact-set-equality rule.

If strict same-host experimental-layout timing attribution is also required, execute its pinned old public implementation as a sixth arm and declare the resulting 732-cell matrix before scoring. Otherwise label the experimental comparison with old timings as historical. Do not imply that a five-arm run proves that causal latency claim.

Freeze policy, accuracy, resource, cost and completeness gates before any scored cell. Preserve failed setup evidence rather than deleting smoke outputs. The currently proposed 1.25× plus 0.1-second paired-overhead flag is a **new proposed pre-run criterion**, not part of the submitted plan; adopt or explicitly replace it in the amendment. Preserve the full input suite and libDAI comparison. No rate tuning, per-instance rules, new inference theory or fresh synthetic performance panel is needed.

Once the bounded qualification and preflight checks pass, proceed directly to the amended step-2 run and return repairs plus benchmark evidence together. Keep main unchanged until the resulting preservation decision.

## Review packet

`CODE_REVIEW.md`, `STRUCTURE_REVIEW.md`, and `BENCHMARK_REVIEW.md` contain detailed locations and evidence. Raw local qualification, characterization, same-host response-prefix results and bounded probes are included. Those reviews have separate scopes; the lead review did the native builds and 69-test rerun. The original committed step-1 receipts remain untouched.
