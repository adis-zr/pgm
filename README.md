# pgm — certified discrete inference

A Python inference library with native execution kernels and one supported entrypoint for original-variable singleton marginals. The automatic switchboard selects among structural exact execution, block contraction and certified importance sampling, checked quotients, and spectrally admitted conditional-response sampling.

The objective is broad end-to-end advantages over libDAI as problems scale, with a fixed general policy. That is an empirical objective, not an achieved universal performance claim. The external benchmark reports wins, losses and refusals separately.

## Python API

```python
from pgm import infer

result = infer("model.uai", budget=20, memory_mib=3072,
               epsilon="1/200", delta="1/1000000")
if result.complete:
    print(result.guarantee, result.probability(variable=0, state=1))
else:
    print(result.outcome, result.to_dict()["published"])
```

Evidence is read from the adjacent `model.uai.evid` file; a missing file means no evidence. By default the request covers every state of every original nonobserved variable. `queries=[(variable, state), ...]` selects original singleton coordinates explicitly; observed coordinates are supported after positive evidence mass is established. Queries are recovered in the original model, not returned in a compressed internal state space.

`mode="auto"` permits all three guarantee classes. `mode="deterministic"` forbids PAC publication; `mode="exact"` publishes only exact represented values. `delta=0` also selects deterministic mode. Finite budgets may produce partial results or typed refusals. The current public API does not silently interpret a joint query, normalizer or expectation as a singleton request; the older CQR finite-query interface is retained separately until it has an explicit common adapter.

The same API is available from the command line:

```bash
python -m pgm --input model.uai --output result.json \
  --budget 20 --memory-mib 3072 --epsilon 1/200 --delta 1/1000000
python -m pgm --capabilities
```

Results contain original coordinate inventory, exact rational endpoint/point strings, guarantees, input hashes, attempt outcomes, resource measurements and the selection reasons. `EXACT` means a point enclosure, not just use of an exact inference algorithm. `DETERMINISTIC` denotes a checked numerical enclosure. `PAC` carries the request's allocated probability allowance. Coordinatewise points need not form an exactly normalized probability vector; their interval box must intersect the simplex. `NOT_PUBLISHED` is never an approximate point answer.

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
| `src/pgm/api.py`, `contracts.py` | Supported API and request/result types |
| `src/pgm/planning.py`, `switchboard.py` | Bounded structural inspection and one automatic policy |
| `src/pgm/backends/` | Process-isolated adapters to retained implementations |
| `src/pgm/registry.py` | Explicit automatic and specialist capability inventory |
| `code/cex/newarm`, `blockres`, `hp` | Retained numerical/algorithm implementations; historical commands are compatibility interfaces |
| `code/cex/cqr`, `code/cbi`, `code/sf`, `code/h4a` | Preserved specialist/query interfaces and research references |
| `tests/` | Portable exact-oracle, resource, publication and API correctness tests |
| `benchmarks/external/` | Frozen external suite, exposure splits and libDAI comparison harness |
| `documentation/` | Architecture, migration scope and independent review |

This is a staged consolidation. Retained algorithms and pinned historical snapshots are not deleted merely because a newer entrypoint does not invoke them. The first stage standardizes selection and lifetime boundaries. Future extraction of numerical modules must preserve these contracts and the external suite.

## Testing and performance evidence

```bash
python -m pytest tests/
```

Synthetic inputs are correctness and adversarial tests only. They never enter the external performance numerator. The performance benchmark uses the entire recovered external suite against libDAI JT and BP, with separately labelled exposed-regression and prospective-evaluation inputs. Run the commands in `benchmarks/external/README.md` after committing source and preparing the comparator/native builds.

The latest DGP10 review retains its conditional-response accuracy mechanism, corrects its diagnostic units and comparator interpretation, and repairs resource/publication boundaries. See `documentation/reviews/`. DGP10's synthetic performance results are not evidence of superiority over libDAI. Historical campaign receipts remain in the separately preserved research records; none is silently reclassified as a result of this public switchboard.
