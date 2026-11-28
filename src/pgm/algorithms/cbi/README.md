# cbi — coupled-block inference (first usable pass, 6 November 2026; repaired after review the same day)

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
from . import model as M, api
m = M.Model.load("examples/example_model.json")
result = api.solve(m, queries="all", requested_width="1/100", limits={})      # queries: "all" or a list of block ids
check  = api.verify(m, result)                                               # {"accepted": bool, "reasons": [...]}
```
`result["status"]` ∈ {CERTIFIED, VALID_BUT_TOO_WIDE, INFEASIBLE (with a zero-partition proof), UNSUPPORTED_INPUT, RESOURCE_LIMIT};
`result["intervals"][block]["coordinates"][j]` = `{"lo", "hi"}` grid integers (divide by 2^80) plus the exact rational endpoints;
`result["certificate"][block]` = a pointer to a shared proof record plus the block's node, mode and transport radius; `result["proofs"][id]` =
the proof itself (one per component or region, shared by every query it covers): kind (forest_batched / region), region H, fixed outside
states ξ, operators per inside edge, θ / d / b / η / ρ coefficients, the DYADIC Theorem-1 iterates z (upward-rounded on the 2^−64 grid, with
the recorded rounding bound), the node intervals and the solver info;
`result["plan"]` = reductions, cluster proposals (verified / rejected with reasons), every attempt with its escalation;
`result["timings"]` = phase walls. A timeout or RESOURCE_LIMIT is a work limit, never a mathematical statement.

Limits (all optional): `max_entries` (dense elimination cap, default 2^20), `exact_direct_entries` (solve the whole component exactly
when it prices below this, default 2^14), `degrees` ([0,1,2,3]), `radii` ([0,1]), `max_region_radius` (2), `max_attempts` (8),
`max_time_s` (120), `T_iterations` (64), `force_exact`, `no_coarsening`.

## CLI

```
python -m pgm.algorithms.cbi.cli solve examples/example_model.json --queries all --width 1/100 --out result.json
python -m pgm.algorithms.cbi.cli verify examples/example_model.json result.json
```

## What runs inside

1. **Exact reductions**: hard components (r = 1) contracted (empty intersection ⇒ INFEASIBLE proof); parallel edges fused; coordinates
   constant on one endpoint's support absorbed as exact unary tilts; separable edges removed. All exact; scalars dropped.
2. **Coarsening (Theorem 3)**: clusters (hints or components of r ≥ 1 − 2^−8, ≤ 8 blocks) verified — connectivity, nonempty intersection,
   C_i, Γ_i over ALL nontrivial internal cuts (enumerated exactly), exp(Ω_i) from the kernel coordinates varying on the ORIGINAL support of
   each seam member (retained and discarded states), ρ_i; the coarse law has one block per island. Both the coarse and the plain candidate
   systems are considered; the narrower complete certificate is published.
2b. **Influence system** (`cbi/influence.py`): the ORIGINAL-LAW influence graph (every seam kept, θ from original supports, ρ per node) is kept
   separate from the simplified computational graph of Q and is the only input to components, regions, boundary terms and the zero-transport test.
3. **Planning** (input only, never a reference): forest components and cheaply priced components are solved exactly on the whole component
   (zero transport); otherwise a radius-1 region (Theorem 1) with fixed outside states, crossing factors kept exactly as tilts, and the
   cheapest prospectively qualified operator per inside edge (exact / positive degree-k surrogate / degree-k enclosure / sparse radius-h);
   escalation raises degrees, enlarges the region, or goes exact while limits permit. Every attempt is recorded and counted. Forest
   components are solved in one batched two-pass schedule for all their queries; an APPROXIMATE candidate (cheapest prospectively
   qualified operator per edge) is tried first when its work estimate is below the exact candidate's and kept iff every node meets the
   width, otherwise the exact candidate is used; both candidates are recorded in the proof.
4. **Transport (Theorem 1)**: θ_e = tanh(s_e atanh r_e) on the TRUE kernels, d_v, b_v ≤ ρ_v + (1−ρ_v)β_v, F(z) = min(1, c + Az) iterated
   from 1 as the DYADIC recurrence on the 2^−64 grid: coefficients rounded UP to the grid, every coordinate of every iterate rounded UP
   (clipped at 1), so every rounded iterate is a valid bound (monotone G ≥ F, G(1) ≤ 1); the rounding bound δ Σ_j L^j (+ coefficient
   rounding) is recorded in `proofs[id].dyadic`; published [l − z_v, u + z_v] with z_v the final grid iterate. Zero transport when the
   whole influence component is solved exactly.
5. **Arithmetic**: positive integer weights; kernels as integers at scale v^d'; messages as dyadic interval vectors rounded outward to
   96 bits; distance histograms by 30-bit limb splitting (float64 exact); publication on the 2^−80 grid.
6. **Verification**: own code paths for hard contraction, cluster certificates (own cuts, own Ω over original supports), influence θ,
   simplification, tilts, Theorem-1 iteration, transfers (distance-major bincount exact transfer, subset-axis moments, min-degree VE); operator
   domains validated; every requested query must be covered with consistent statuses; accepts iff every published interval contains the
   verifier's own enclosure. Each shared proof record is verified ONCE (own batched two-pass forest schedule; own dyadic replay with
   independently reconstructed coefficients) and reused for every query that points to it. Shared proof-critical helpers are listed in `cbi/verify.py`'s docstring.

Not implemented in this pass: the anchored Theorem-4 transfer, the nonbacktracking (Theorem-2) comparison, hard surrogate factors,
coordinate maps, non-product kernels. See the pass report under `runs/mdi_2026-10-28/CBI_LIBRARY_2026-11-06/`.
