# pgm — certified discrete inference

A Python inference library with native execution kernels and one supported entrypoint for original-variable singleton marginals. The default `accepted` policy runs the established block-contraction engine, including its exact and certified importance-sampling routes. The opt-in `experimental` switchboard also selects structural execution, checked quotients, and spectrally admitted conditional-response sampling under the same public contract.

The objective is broad end-to-end advantages over libDAI as problems scale, with a fixed general policy. That is an empirical objective, not an achieved universal performance claim. The external benchmark reports wins, losses and refusals separately.

**Original Mac consolidation experiment.** On the 61 exposed external tasks, the accepted policy and its pinned reference both complete 45 tasks; the experimental policy and its pinned reference both complete 54. The repaired-runtime supplement retains those sets. All 29 historical accepted successes and all 47 historical experimental successes are preserved. The experimental arm includes all 25 libDAI junction-tree completions and 29 additional tasks; on the 25 shared completions its median wall-time ratio to JT is 1.34, with individual speedups up to 28.17x. Broad latency dominance remains future work. See [the consolidation acceptance record](documentation/consolidation/ACCEPTANCE.md) for the independent review, incident disposition, known overhead and exact evidence identities.

## Python API

```python
from pgm import infer

result = infer("model.uai", budget=20, memory_mib=3072,
               epsilon="1/200", delta="1/1000000", policy="accepted")
if result.complete:
    print(result.guarantee, result.policy, result.probability(variable=0, state=1))
else:
    print(result.outcome, result.to_dict()["published"])
```

Evidence is read from the adjacent `model.uai.evid` file; a missing file means no evidence. By default the request covers every state of every original nonobserved variable. `queries=[(variable, state), ...]` restricts the inventory.

`mode="auto"` permits all three guarantee classes. `mode="deterministic"` forbids PAC publication; `mode="exact"` publishes only exact represented values. `delta=0` also selects deterministic mode.

`policy` selects the public scheduling policy, separately from the guarantee mode: `"accepted"` (the DEFAULT since consolidation step 1) runs the accepted engine v2.13.2 through the common contract with its benchmarked configuration; `"experimental"` runs the frozen `structural-portfolio-1` of the scored commit `3283cfd`. Every result records `policy`, `policy_version`, the full `policy_record` and the PAC `risk_allocations`. See `documentation/consolidation/step1/PUBLIC_API_AND_POLICIES.md`.

The same API is available from the command line:

```bash
python -m pgm --input model.uai --output result.json \
  --budget 20 --memory-mib 3072 --epsilon 1/200 --delta 1/1000000 --policy accepted
python -m pgm --capabilities
```

Results contain the original coordinate inventory, exact rational endpoint/point strings, guarantees, input hashes, attempt outcomes, resource measurements and the selection reasons. `EXACT` means a point; `DETERMINISTIC` a checked enclosure with an epsilon-safe point; `PAC` an enclosure that spends the request's delta allowance.

The opt-in candidate `policy="automatic"` (`structural-portfolio-3`) extends the experimental policy's bounded exact attempt to binary higher-order factors when the existing physical forecast admits it, and defers optional quotient construction until after the incumbent block attempt. It retains the existing rates, bounded structural allowance and prospective risk allocation. The accepted default and frozen experimental ordering remain available as references. See [the implementation scope](documentation/performance/round2/IMPLEMENTATION.md) and the separately frozen full-suite plan in `benchmarks/external/PERFORMANCE_ROUND2_PLAN.md`. Performance and preservation are empirical gates; the default is unchanged.

Results additionally record the complete proposed dispatch order and whether each candidate was attempted. `phase_timings` separates inspection, policy planning, supervised attempts and publication preparation; attempts carry worker parse, adapter and normalization timings. These timers are nested diagnostics, not additive replacements for the end-to-end wall time. Admission, output and cleanup remain charged to the same request deadline.

## Installation and native builds

Use Python 3.12 or newer:

```bash
python3.12 -m venv .venv
.venv/bin/pip install -e .
```

The numerical dependencies are NumPy, gmpy2, SciPy and psutil. Linux and macOS require native builds appropriate to the host; the historical tracked binaries are not portable between architectures. The certified C++ and heat-bath kernels require Clang's original strict floating-point flags. Set `CC` and `CXX` to compatible Clang executables and run `python -m pgm.build` before timed use. Build identities and source hashes are recorded by the retained builders. Build/setup time is reported separately in benchmarks; construction and recognition inside an inference call are charged.

## Repository structure

| Location | Role |
|---|---|
| `src/pgm/api.py`, `contracts.py`, `__main__.py` | Supported API, request/result types, CLI |
| `src/pgm/policies/` | Explicit public policies: `accepted` (default), frozen `experimental`, candidate `automatic` |
| `src/pgm/switchboard.py`, `planning/`, `runtime/`, `validation/` | Controller, bounded inspection, supervised attempts, common publication |
| `src/pgm/model/uai.py` | The one input boundary (exact reader, binding, original inventory) |
| `src/pgm/backends/` | Explicit process-isolated adapters (structural, block, quotient, response) and the worker |
| `src/pgm/algorithms/` | The canonical implementations: structural, block (accepted engine), quotient, response, with their native sources and build records |
| `src/pgm/specialists/`, `registry.py` | Explicit specialist entrypoints (CQR, CBI, SF, H4) and the capability registry |
| `code/` | Historical layout: alias shims at the relocated paths, campaign tooling, specialists, frozen snapshots, evidence (`research/CLASSIFICATION.json`) |
| `tests/` | Portable exact-oracle, resource, publication, API, boundary and parity tests |
| `benchmarks/external/` | Frozen external suite, exposure history, libDAI harness with explicit policy arms, the step-2 plan |
| `documentation/` | Architecture, reviews, consolidation step 1 (manifest, path map, capability matrix, blocked controls, qualification) |

Production implementations live under `src/pgm`; historical paths delegate through compatibility shims. Specialist methods retain explicit interfaces and capability status; they are not all automatically selected by the default policy. Research snapshots and their evidence remain available for provenance. Future performance changes must preserve the public contracts and the full external suite.

## Testing and performance evidence

```bash
python -m pytest tests/
```

Synthetic inputs are correctness and adversarial tests only. They never enter the external performance numerator. The performance benchmark uses the entire recovered external suite against libDAI JT and BP. All 61 current tasks are exposed regression inputs; the original manifests preserve earlier cohort roles. Any new unseen-evaluation claim requires a separately selected and frozen external cohort. Run the commands in [the benchmark instructions](benchmarks/external/README.md) after committing source and preparing the comparator/native builds.

The latest DGP10 review retains its conditional-response accuracy mechanism, corrects its diagnostic units and comparator interpretation, and repairs resource/publication boundaries. See `documentation/reviews/`. DGP10's synthetic performance results are not evidence of superiority over libDAI. Historical campaign receipts remain in the separately preserved research records; none is silently reclassified as a result of this public switchboard.
