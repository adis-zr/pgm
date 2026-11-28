# Untuned switchboard — second external performance round

This prospective round follows the first round at `d33d40a`. It tests one
scheduling change: retain the affordable structural paths, then let the incumbent
block method run before optional quotient construction. An unaffordable dense
identity forecast is not evidence that constructing a quotient will repay its
cost. `policy="automatic"` records `structural-portfolio-3`; rates, prospective
risk shares, precision requirements and numerical kernels remain fixed. The
accepted default is unchanged. Common-runtime deadline and output repairs are
qualified before the freeze. No benchmark-name rule or per-input tuning is used.

The original first-round freeze, raw records and validity FAIL remain unchanged.
The new plan is `PERFORMANCE_ROUND2_PLAN.json`, committed before scored execution.

## Complete matrix and contract

Run all 61 committed external tasks with six arms and two fresh-process repeats:
**732 cells**, serial, with arm order reversed by task index plus replicate.
Reference accepted and experimental policies run at consolidation baseline
`f664ee7` on the same host and interpreter. Candidate accepted and automatic run
at the new frozen commit. libDAI junction tree and loopy BP remain the external
comparators. All inputs are exposed regression tasks; no unseen claim is made.

Every cell receives 20 seconds, 3 GiB sampled process-tree RSS, 10-ms sampling
and zero supervisor grace. PGM receives a 19.5-second internal publication
allowance, epsilon 1/200 and request delta 1e-6. The scored ceiling is **14,640
supervisor seconds**. Native compilation and tiny qualification occur in setup,
with active bytes hashed and archived before timing. No inference answer is
cached. All parsing, construction, discarded work, inference, certification and
cleanup inside a timed request count toward its end-to-end cost.

## Prospective validity semantics

A comparator terminated by the supervisor with TIMEOUT_KILL or MEMORY_KILL has
not returned an accepted answer. Its partial `MAR` or side file is retained as
censored diagnostic bytes and is not parsed into a claimed answer or a finite
latency denominator. A completed comparator with malformed output is still a
validity failure. Input/source identities, raw artifact hashes, unique terminal
receipts and cleanup remain mandatory in every case.

Every published coordinate or completing status must have a finite, nonboolean
CLI wall within 19.5 seconds, even when its deadline flag says true. When API
timing fields are recorded, the API wall must be finite and within its recorded
positive request budget, that budget cannot exceed the CLI allowance, and an
API deadline flag must be true. Contradictory timestamps fail without added
tolerance or grace.

PGM's inner deadline remains a hard **publication** deadline. A truthful late
return can be a valid refusal only when it says DEADLINE/NONE, publishes zero
rows, retains the complete original inventory and binding, marks every answer
NOT_PUBLISHED without numerical payload, has clean attempt and outer ownership
receipts, and finishes under the outer 20-second contract. The internal/CLI time
and `hard_deadline_respected=false` are preserved as diagnostics. Such a result
never counts as a completion. Every other publication or contract fault remains
invalid; a single late published coordinate fails. This rule is declared before
this round and does not relabel the earlier 19.502556-second refusal.

## Bundle release gates

All gates must pass:

1. Valid identities, bindings, cleanup, receipts and claimed outputs; no
   deterministic interval conflicts or JT exclusions under the existing 5e-10
   serialization allowance.
2. All 732 cells recorded within the declared ceiling.
3. Candidate accepted preserves every same-round baseline-accepted completion.
4. Automatic preserves the union of the two same-round baseline policies.
5. Automatic preserves all **50** first-round automatic both-repeat completions.
   Their recorded analysis, freeze, model/evidence bindings and source commit are
   hash-bound. This is a historical coverage target; no controlled timing claim
   against the prior candidate is possible with this six-arm matrix.
6. No confirmed cost flag for candidate accepted versus baseline accepted.
7. No confirmed cost flag for automatic versus baseline experimental.

A cost flag requires a slowdown exceeding both 1.25× and 0.1 seconds in **both**
matched repeats. Finite ratios require mutual both-repeat completion. Failure of
any gate produces HOLD, not a passing implementation bundle. Default promotion
remains a separate decision. Historical Mac accepted45/experimental54 coverage
is still reported separately from this same-host test.

Broad speed dominance over libDAI remains a separate research outcome. Release
eligibility does not establish it. Report all coverage losses and gains, timing
pairs, RSS, dispatch and phase costs, variable-count groups 1–100/101–1000/1001+,
family groups and point-only BP diagnostics. Per-replicate changes in partial
certified coordinates are reported separately. The heterogeneous panel alone
cannot establish an asymptotic scaling law.

## Run and reproduce

Use the committed `run_performance.py` setup/freeze/run/analyze commands from the
first-round instructions with a **new** run directory. Setup requires qualified
`CC`/`CXX`, `PGM_LIBDAI`, `PGM_LIBDAI_QUALIFICATION`, and a detached `f664ee7`
checkout in `PGM_PERFORMANCE_BASELINE_ROOT`. The default directory for this round
is `benchmark_runs/untuned-runtime-2`.

The freeze binds the new protocol, both source closures, native/compiler/Python
identities, all inputs, the historical preservation records and each policy
contract. Runtime edits require a new freeze. Resume never silently reruns a
launched cell. Original raw output and receipt bytes are preserved. Portable
analysis resolves source paths within a restored checkout and still verifies
all original hashes; another host's inference timing needs a new setup/freeze.
