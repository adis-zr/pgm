# cbi — coupled-block inference (first usable pass, 6 November 2026)

Certified singleton marginals for models made of **binary block tables joined by the full-coordinate product kernel**
K_r(x, y) = Π_j (1 + r x_j y_j), 0 ≤ r ≤ 1 (r = 1 is hard equality). Every published interval is an exact rational enclosure of the
true marginal, rounded outward to the 2^−80 grid, and comes with a certificate an independent verifier re-derives from the raw model.

## Model format (JSON)

```json
{"d": 24,
 "bit_convention": "coordinate j (0-based) <-> bit j of the state mask; bit set <-> x_j = +1",
 "blocks": [{"id": 0, "rows": [5, 17, 4094], "weights": [3, 1, 2]}, {"id": 1, "rows": [5, 9], "weights": [1, 1]}],
 "edges":  [{"u": 0, "v": 1, "r": "1/64"}],
 "meta":   {"cluster_hints": [[0, 1]]}}
```
* `rows` are the allowed states of a block as integer masks (unique; `0 ≤ row < 2^d`); `weights` are positive integers or rationals.
* `edges` carry rational couplings `r` in [0, 1]; parallel edges are fused exactly ((1+rs)^d K_{(r+s)/(1+rs)}); only the product kernel
  is accepted (`"kernel": "product"` implied); coordinate maps between blocks are **rejected** (UNSUPPORTED_INPUT).
* `meta.cluster_hints` (optional): candidate strong-island clusters; every hint is verified from the supports and couplings before use.

## API

```python
from cbi import model as M, api
m = M.Model.load("examples/example_model.json")
result = api.solve(m, queries="all", requested_width="1/100", limits={})      # queries: "all" or a list of block ids
check  = api.verify(m, result)                                               # {"accepted": bool, "reasons": [...]}
```
`result["status"]` ∈ {CERTIFIED, VALID_BUT_TOO_WIDE, INFEASIBLE (with a zero-partition proof), UNSUPPORTED_INPUT, RESOURCE_LIMIT};
`result["intervals"][block]["coordinates"][j]` = `{"lo", "hi"}` grid integers (divide by 2^80) plus the exact rational endpoints;
`result["certificate"][block]` = mode (TREE_MESSAGE / EXACT_VE / REGION_SURROGATE / COARSE_REGION[+SURROGATE]), region H, fixed outside
states ξ, operators per inside edge, θ / d / b / η / ρ coefficients, the Theorem-1 iterates z, the regional [l,u] and the solver info;
`result["plan"]` = reductions, cluster proposals (verified / rejected with reasons), every attempt with its escalation;
`result["timings"]` = phase walls. A timeout or RESOURCE_LIMIT is a work limit, never a mathematical statement.

Limits (all optional): `max_entries` (dense elimination cap, default 2^20), `exact_direct_entries` (solve the whole component exactly
when it prices below this, default 2^14), `degrees` ([0,1,2,3]), `radii` ([0,1]), `max_region_radius` (2), `max_attempts` (8),
`max_time_s` (120), `T_iterations` (64), `force_exact`, `no_coarsening`.

## CLI

```
python -m cbi.cli solve examples/example_model.json --queries all --width 1/100 --out result.json
python -m cbi.cli verify examples/example_model.json result.json
```

## What runs inside

1. **Exact reductions**: hard components (r = 1) contracted (empty intersection ⇒ INFEASIBLE proof); parallel edges fused; coordinates
   constant on one endpoint's support absorbed as exact unary tilts; separable edges removed. All exact; scalars dropped.
2. **Coarsening (Theorem 3)**: clusters (hints or components of r ≥ 1 − 2^−8, ≤ 8 blocks) verified — connectivity, nonempty intersection,
   C_i, Γ_i over ALL nontrivial internal cuts (enumerated exactly), exp(Ω_i) from the seam coordinates that vary, ρ_i; accepted when
   ρ_i ≤ ε/8; the coarse law has one block per island.
3. **Planning** (input only, never a reference): forest components and cheaply priced components are solved exactly on the whole component
   (zero transport); otherwise a radius-1 region (Theorem 1) with fixed outside states, crossing factors kept exactly as tilts, and the
   cheapest prospectively qualified operator per inside edge (exact / positive degree-k surrogate / degree-k enclosure / sparse radius-h);
   escalation raises degrees, enlarges the region, or goes exact while limits permit. Every attempt is recorded and counted.
4. **Transport (Theorem 1)**: θ_e = tanh(s_e atanh r_e) on the TRUE kernels, d_v, b_v ≤ ρ_v + (1−ρ_v)β_v, F(z) iterated from 1 (every
   iterate valid); published [l − z_v, u + z_v].
5. **Arithmetic**: positive integer weights; kernels as integers at scale v^d'; messages as dyadic interval vectors rounded outward to
   96 bits; distance histograms by 30-bit limb splitting (float64 exact); publication on the 2^−80 grid.
6. **Verification**: separate code paths (sorted/source-major exact transfer, subset-axis moments via the §3 identities, min-degree VE,
   own cluster certificates) re-derive everything from the raw model and accept iff every published interval contains the verifier's
   own enclosure. Shared proof-critical helpers are listed in `cbi/verify.py`'s docstring.

Not implemented in this pass: the anchored Theorem-4 transfer, the nonbacktracking (Theorem-2) comparison, hard surrogate factors,
coordinate maps, non-product kernels. See the pass report under `runs/mdi_2026-10-28/CBI_LIBRARY_2026-11-06/`.
