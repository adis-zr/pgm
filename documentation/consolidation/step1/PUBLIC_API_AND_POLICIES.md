# Public API, default policy and intentional behavior changes (consolidation step 1)

## One API, one CLI

```python
from pgm import infer
result = infer("model.uai", budget=20, memory_mib=3072, epsilon="1/200", delta="1/1000000",
               seed=1, mode="auto", queries=None, policy="accepted")
```

```bash
python -m pgm --input model.uai --output result.json --budget 20 --memory-mib 3072 \
    --epsilon 1/200 --delta 1/1000000 [--mode auto|deterministic|exact] [--policy accepted|experimental]
pgm ...            # console script of the installed wheel
python -m pgm --capabilities
```

`InferenceRequest(model, budget, memory_mib, epsilon, delta, seed, mode, queries, policy)` is immutable and validated;
`InferenceResult` keeps the result dictionary and exposes `complete`, `outcome`, `guarantee`, `policy`, `probability(v, a)`,
`to_dict()`.  Evidence is the adjacent `model.uai.evid`; a missing file is no evidence.  Queries default to every state of
every original nonobserved variable (`queries=[(variable, state), ...]` restricts the inventory; observed variables may be
requested and are exact 0 / 1 once positive mass is witnessed).

## Guarantee mode (unchanged meaning)

| mode | permitted labels | meaning |
|---|---|---|
| `exact` | EXACT | exact represented point (`lo == point == hi`) |
| `deterministic` (or `delta = 0`) | EXACT, DETERMINISTIC | checked enclosure `[lo, hi]` with an epsilon-safe point, no sampling risk |
| `auto` | EXACT, DETERMINISTIC, PAC | PAC rows spend the request's delta allowance (never more; the result records `risk_allocations`) |

Labels are never weakened or strengthened by the controller: a request's mode filters rows; a legacy fixed-tolerance
enclosure wider than epsilon is withheld, not promoted; EXACT requires zero width; published rows require a positive-mass
witness; enclosures of one coordinate from different attempts must intersect (else `CERTIFICATE_DEFECT`); the assembled
per-variable interval box must meet the simplex (missing states keep `[0, 1]`).  Coordinatewise safe points are not promised
to form a normalized vector; the interval box is simplex-feasible.  Z semantics, zero-evidence (`ZERO_EVIDENCE`,
`positive_mass_witness = False`), refusal inventories (every coordinate typed on every exit) and typed failures are unchanged.

## Policy (new, orthogonal to mode)

| policy | version | what it schedules | PAC risk allocation |
|---|---|---|---|
| `accepted` (DEFAULT) | `accepted-engine-v2.13.2-targeted/1` | the accepted engine only (`pgm.algorithms.block`), through the common contract, with its benchmarked configuration passed explicitly: schedule `targeted`, proposal `mb`, table_cap 2^18, enum_cap 2^16, mb_cap 2^24, batch 1024, crosscheck, engine-default constructors, route auto / exact / exact by mode; the full remaining work allowance after the common bounded inspection; the full requested delta when PAC is permitted; no optional physical forecast, no quotient / spectral exploration; no reserved risk for backends it never invokes | block 1 |
| `experimental` | `structural-portfolio-1` | the frozen portfolio of the scored commit `3283cfd`, moved verbatim (choices, coefficients, allowance fractions, 20e6 rows/s forecast rate, risk shares) | structural 0, block 1/2, quotient 1/4, response 1/4 |

Every result records `policy`, `policy_version`, `policy_record` (the full configuration above) and `risk_allocations`.
Every worker attempt records the policy and the explicit configuration it received (`attempts[*].configuration`).
Provenance of the accepted configuration: `benchmarks/external/reference/PRIOR_PRIMARY_REPORT.md` (main `7f28259`,
"historical targeted schedule") and the DGP6-DGP9 frozen base arm (`run_dgp8.FROZEN['base']`).  `integrated.solve`'s own
defaults (schedule `baseline`) do NOT reproduce the accepted arm; the policy passes the configuration explicitly.

## Intentional behavior changes (separated from the arithmetic-preserving extraction)

1. **Default policy** (commit `c5b7708`, "Step 1 (1/5)"): a request that names no policy now runs the accepted engine with
   its benchmarked configuration.  At `f8197e6` the default was the structural portfolio (`structural-portfolio-1`).  The
   portfolio is retained unchanged under `policy="experimental"`.  This is the compatibility objective of the brief; step 2
   must test preservation on the external inputs before `accepted` is promoted on `main`.
2. **Result record**: new keys `policy`, `policy_version`, `policy_record`, `risk_allocations`; attempts carry `delta`
   (the attempt's share), `policy`, `configuration`, `expected_binding` is checked by the worker (typed `BINDING` refusal).
3. **Binding refusal reports the inventory**: a worker whose parsed source differs from the controller's binding refuses
   typed (`BINDING`) with every original coordinate `NOT_PUBLISHED` (no row invented).
4. **Response solver record**: the callable solver returns the same record the CLI wrote (mechanism resource fields,
   `peak_rss_bytes`, `phases_s` mirrored after the one authoritative sample; `argv` is the option list, not `sys.argv`).

Everything else is extraction: arithmetic kernels, message ordering, update formulas, certificate formulas and frozen
cost coefficients are byte-identical (`qualification/03_algorithms/relocation_diff_summary.txt`: 304 changed lines, all
import / sys.path / location lines), confirmed by the pinned characterization reference (`tests/parity/reference_f8197e6.json`;
16 deterministic cases with exact rational bounds / points / labels / bindings / witnesses / refusals / Z enclosures /
ledger identity / risk accounting, 2 wall-limited invariants, 2 fixed-work 75,000-step native response prefixes) --
IDENTICAL after every extraction commit and at the final state.

## Request-level ownership (unchanged)

The controller owns the original inventory and binding, the absolute monotonic deadline, the aggregate sampled
process-tree memory, the PAC allowance split and the final publication.  Each attempt runs the isolated worker under the
owned-tree supervisor (zero grace); acceptance requires an on-time exit, a terminal `COMPLETED` receipt with empty owned
and nested groups, and a bounded output.  Cleanup receipts precede acceptance; the one authoritative final timestamp
suppresses late assembled answers; the CLI output-commit guard is unchanged.
