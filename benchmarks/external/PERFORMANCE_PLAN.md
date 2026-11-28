# Untuned runtime and structural dispatch — first performance round

This round tests general implementation changes after the consolidated baseline
`f664ee7`. It does not reopen consolidation, change the accepted default, or tune
per-model settings. The candidate exposes an explicit `automatic` policy:
`structural-portfolio-2`, using the experimental policy's fixed rates, risk
shares and allowances, with affordable exact-contraction admission extended to
binary higher-arity models. Runtime and inspection improvements apply to both
public policies. Correctness fixtures are synthetic; performance inputs are the
complete 61-task committed external suite.

All 61 inputs are exposed regression tasks, including the historical six
`former_eval6` inputs. No generalization claim is made. The two reference arms
run the consolidated baseline's accepted and experimental policies on the same
host, interpreter, external inputs and native compiler as the candidate. The
other arms are candidate accepted, candidate automatic, libDAI junction tree,
and libDAI loopy BP. BP convergence is not an epsilon certificate. JT agreement
is numerical agreement with its retained serialization allowance, not a proof
of every large-model marginal.

The fixed matrix is 61 tasks × six arms × two repeats = **732 cells**, serial,
with fresh processes. Arm order reverses by task index plus replicate. Each
cell has the existing 20-second outer contract, 3 GiB sampled process-tree RSS,
10-ms sampling, zero supervisor grace, and retained process ownership cleanup.
PGM receives 19.5 seconds, epsilon 1/200 and request delta 1e-6. The scored
ceiling is **14,640 supervisor seconds**. Setup compilation and tiny comparator
qualification are separately recorded; all active binaries are built/warmed
before timing and copied into the packet. No inference result is cached.

The primary preservation gates are candidate accepted versus baseline accepted,
and candidate automatic versus the union of baseline accepted and baseline
experimental. Completion means valid output in both repeats. Historical 45/54
completion targets are also reported, with their original identities, separately
from same-host results: this Linux run is not a repetition on the original Mac.
All result files are checked for binding, original coordinate inventory, exact
rational geometry, positive-mass witness, guarantee labels, prospective risk,
policy configuration, deadlines and terminal cleanup. Deterministic interval
conflicts and available JT exclusions are reported. Malformed returned results
are validity faults; a refused or killed inference remains an observed failure.

Performance reports retain every task, completion gain/loss and end-to-end
latency. Finite timing ratios use mutual both-repeat completions only; timeouts
and refusals are censored. The inherited overhead flag is slower by more than
1.25× and 0.1 seconds in both repeats. Route counts and phase times identify
where the change acts. Size/family tables describe the panel; they establish no
asymptotic scaling law. No benchmark-specific selection or hyperparameter search
is permitted. The full JSON plan is normative and committed before scored runs.

## Execute

Create a detached worktree of `f664ee7`, use the project Python 3.12 environment,
and set `CC`/`CXX` to the qualified native compilers. The comparator must pass
`provenance/qualify_libdai.py`; its qualification binds the executed binary hash.
All setup output is written outside tracked source.

```bash
export PGM_PERFORMANCE_BASELINE_ROOT=/absolute/path/to/baseline
export PGM_LIBDAI=/absolute/path/to/libdai_mar
export PGM_LIBDAI_QUALIFICATION=/absolute/path/to/LIBDAI_QUALIFICATION.json
export PGM_PERFORMANCE_RUN_DIR=/absolute/path/to/new-run
python benchmarks/external/run_performance.py setup
# Commit all implementation, harness and test changes before freezing.
python benchmarks/external/run_performance.py freeze
python benchmarks/external/run_performance.py run
python benchmarks/external/run_performance.py analyze
```

`run --max-cells N` pauses after N additional cells; rerunning `run` resumes the
same immutable freeze. A lock prevents concurrent runners. Atomic per-cell JSON
and the append-only supervisor receipt ledger are authoritative. A launched
cell with no unique terminal receipt is refused for manual reconciliation;
no silently repeated inference is allowed. Source, active native and input
identities are checked before and after each cell. A post-launch identity fault
is retained and stops the campaign. Do not edit frozen source while running.

The resulting packet contains `FREEZE.json`, `setup/`, active `artifacts/`,
`runs/` with every raw output/launch/log/receipt binding, `RECEIPTS.jsonl`,
`CELLS.json`, `ANALYSIS.json`, `PAIRS.csv` and `REPORT.md`. Old campaign data and
its original failures remain untouched.
