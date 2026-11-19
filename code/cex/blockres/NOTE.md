# Block contraction for residual inference -- proof note (19 Nov 2026)

Scope: the experimental backend `code/cex/blockres/blockres.py` (version `blockres-v1`). Everything below is for the finite task language of the CQR manuscript
restricted to the legacy contract: nonnegative rational factor tables, evidence, all original singleton marginals, eps = 1/200, delta = 1e-6. Nothing here is novel as
mathematics: the construction is bounded-width partial variable elimination (a cutset / join-graph decomposition), the integrated bounds are mini-bucket bounds (Dechter
and Rish), and the estimators are the CQR manuscript's ratio and signed-residual streams with a changed sampling law. The note states exactly what the code does.

## 1. Exact partition and query reconstruction

Integerize: every factor table phi_a is multiplied by the lcm d_a of its denominators; evidence restricts scopes. Then w(x) = (1 / prod d_a) prod_a phi_a^int(x_a) with
integer phi^int, and Z, every numerator and every ratio are unchanged by the common scalar (it cancels in every published quantity; the normalizer is reported with it).
Variables touched by no factor after restriction contribute the multiplicity card(x) to Z and have the uniform marginal 1 / card(x) (exact, published as EXACT).

Partial elimination: starting from the integer factors, repeatedly eliminate the variable v whose bucket union scope has the smallest table (<= table_cap entries and
<= BYTE_CAP bytes), replacing the bucket by its exact integer sum-product g = sum_v prod(bucket). Every original factor is consumed exactly once, so when the loop stops
the surviving functions {g_b} induce a partition of the original factors into blocks b (the factors absorbed into g_b), with Y_b = variables eliminated into g_b and
S = union of the surviving scopes. By associativity and distributivity of sum-product:

    for every s in S-assignments:   z(s) := sum over y of prod_a phi_a(s, y) = prod_b g_b(s_b)          (exact integers)

Interior query: for x in Y_b and state v, replay block b's own elimination with x retained (same order, same buckets, x skipped) from the cached live set at x's step;
the result g_bx(s_b, x) satisfies sum_x g_bx(s_b, x) = g_b(s_b) and

    N_(x=v) := sum_{s} g_bx(s_b, v) prod_{a != b} g_a(s_a),      mu_(x=v) = N_(x=v) / Z,      Z = sum_s z(s).

The code evaluates the summand at a separator assignment s as z(s) * g_bx(s_b, v) / g_b(s_b) (an exact integer because g_b | z and g_bx <= g_b; when g_b(s_b) = 0 the
summand is 0 and no division happens: g_b = 0 implies g_bx = 0 for every v). Separator query (x in S): f(s) = 1{s_x = v}, N = sum_s z(s) f(s). Exact separator enumeration
(root N_S <= enum_cap) therefore yields exact rationals for every query (published EXACT). Queried interior variables whose replay would exceed the cap or the
construction window are reported NOT_PUBLISHED (counted as `interior_queries_failed / skipped`); the fallback for them is the existing CQR solver, not this backend.

## 2. Cell bounds actually used (prefix cells C over a fixed separator order; N_C = number of completions)

Mass (exact integers): L_C = N_C prod_b min_{s in C} g_b(s_b) <= sum_{s in C} z(s) <= N_C prod_b max_{s in C} g_b(s_b) =: E_C. The max / min are over the slice of the
stored table g_b consistent with the cell's assigned variables (variables of b's scope not yet assigned range freely), so they are exact.

Pointwise query range (interior x in block b): on the support {g_b(s_b) > 0} inside C, rho_lo <= g_bx(s_b, v) / g_b(s_b) <= rho_hi, computed from OUTWARD float mantissas
(Lemma N) of the integer tables and converted exactly to rationals (floats are dyadic rationals). Where g_b = 0 the summand is 0, so the range only needs to hold on the
support; a cell whose slice is entirely zero gets the range [0, 0] (and L_C = E_C = 0). Separator query: [1, 1] / [0, 0] once x is assigned, else [0, 1].

Residual cap for a fixed candidate c_j (interior j in block b): H_bj(C) >= max_{s_b in C} |g_bx(s_b, v) - c_j g_b(s_b)| from the outward mantissas with the candidate
enclosed outward (Lemma N); when the float bound is negligible relative to the table scale the code decides EXACTLY (integer arithmetic on the slice) whether the
residual is identically zero; the cap of the cell is a_C = N_C max_j cap_j with cap_j = H_bj(C) prod_{a != b} max_C g_a (interior) or prod_a max_C g_a * max(|lo - c_j|,
|hi - c_j|) (separator). Zero caps are typed exact zeros, never rounded tiny floats; a cell with a_C = 0 has residual identically zero on all its completions.

Optional mini-bucket integrated bound (`--mb-cap`): eliminate the free separator variables of C in the fixed order; a bucket whose joint scope exceeds the cap is split
into mini-buckets, one summed and the others maxed (upper) / minned (lower). Exact when no split occurs; otherwise the classical mini-bucket inequality. It replaces
B_C (upper) and L_C (lower) in the DETERMINISTIC route only. It is never used as a sampling cap (point 1 below).

Ablation (`--bounds factorwise`): the same partition, evaluator, controller, laws and risk allocation, with max_C g_b replaced by N_{Y_b} prod_{phi in b} max_C phi
(the frozen CQR frontier's bound of the same cell's mass: product of per-factor extrema with the interior free), interior ranges [0, 1], residual cap max^old * max(c,
1 - c). Both arms are valid certificates; they differ only in tightness.

## 3. Probability law of the estimators (the four substantive points of the brief)

(1) What is sampled. A cell C with probability E_C / U, U = sum_C E_C, then s uniform on the N_C completions; q(s) = E_C / (U N_C). The evaluated contribution is the
INTEGRATED z(s) = prod_b g_b(s_b) (the full interior sum), never a full assignment. Importance weight W = z(s) / q(s) = z(s) N_C U / E_C <= U because z(s) <= prod_b
max_C g_b = E_C / N_C on C. So the pointwise cap for THIS law is U = sum_C N_C prod_b max_C g_b; the code asserts W <= U on every draw (the control
`underestimated_bound_refused` injects E_C = 1 and the assertion fires). An integrated bound (mini-bucket B_C < E_C) is NOT a cap for z(s) / q(s): a cell can hold a
single s with z(s) close to E_C / N_C while sum_{s in C} z(s) is far below E_C. Hence B_C is confined to the deterministic route and E_C drives the laws.
E[W] = sum_s z(s) = Z (over s with q(s) > 0; cells with E_C = 0 have z = 0 on all completions). T_t = A + W_t has mean Z, Y_tj = a_j + W_t f_j(s_t) has mean N_j, where
A, a_j are the exactly resolved (closed-cell) mass and numerators. The conditional range of Y_tj - mu_j T_t is at most U, so the manuscript's normal-mixture boundary
with V_t = sum b_t^2 U_t^2 / 4 and predictable dyadic weights b_t = 2^floor(log2 (U*/U_t)^2) applies verbatim (Theorem 6.2 of the CQR manuscript, `numerics.boundary_upper`
outward); the per-interval risk is delta / 2 / (K + 1) (K query intervals plus one Z interval).

(2) Signed residual. For a candidate c fixed in an epoch, R_j(s) = z(s)(f_j(s) - c_j) has sum S_j = N_j - c_j Z. The law draws C with probability a_C / E (E = sum_C a_C over
cells with a_C > 0), s uniform in C, and the contribution Y_j = d_j + R_j(s) N_C E / a_C with d_j the resolved residual; |R_j N_C E / a_C| <= E by the cap. E[Y_j] = S_j
exactly over the omitted-zero law: cells with a_C = 0 are omitted and contribute 0 to S_j. This stream is used ONLY to test |S_j| <= eps Z_lo with Z_lo a certified lower
bound (resolved mass + sum L_C, or the ratio stream's own Z interval), never to estimate Z. Acceptance publishes [c_j - eps, c_j + eps]: |mu_j - c_j| = |S_j| / Z <= |S_j| /
Z_lo <= eps. Epochs: risk delta / (2 e (e + 1)) / K for epoch e (sum over e <= delta / 2); a new epoch resets statistics (restarts are separate epochs with their own
risk, never pooled). If E = 0 the residual is identically zero on every open cell and S_j equals the resolved residual exactly: a deterministic test (no risk spent).

(3) Zeros. const = 0 after restriction, or every surviving function identically zero, or sum_C E_C = 0 with no resolved mass, is ZERO_EVIDENCE (typed). A zero g_b(s_b)
zeroes the summand; conditional responses are only formed on the support; a zero residual cap is decided exactly. A query whose numerator is exactly zero publishes
the exact 0 only through the exact or deterministic routes (an interval [0, hi] with hi <= 2 eps is a legitimate deterministic publication, not a claim of exact zero).

(4) Numerics. All tables, z(s), resolved sums, stream statistics and candidate values are exact integers / Fractions; the only floats are inside BOUNDS. Lemma N: for an
integer n >= 0 and shift k (chosen so n >> k < 2^1000), lo = max(0, nextafter(float(n >> k), -inf)) and up = nextafter(float((n >> k) + 1), +inf) satisfy lo * 2^k <= n <=
up * 2^k, and exact zeros map to exact zeros in both. Ratios lo / up and products are widened by 4 u (u = 2^-53) per operation and the result converted exactly to a
Fraction; the candidate c_j is enclosed in [c (1 - 4u), c (1 + 4u)]. Every published interval is therefore an outward enclosure of a quantity the integer arithmetic
defines exactly, and the final answer is the midpoint of the certified interval (within eps of the truth by construction). The normalizer scale 1 / prod d_a cancels
in every published ratio. Agreement of two floating computations is nowhere used as evidence.

## 4. What the proof establishes versus what the experiment shows

Established: exactness of the partition and reconstruction; validity of every bound and of both streams' confidence sequences under their stated laws; soundness of the
ablation as a certificate. The deterministic route's correctness does not depend on tightness. Not established: any claim that the bounds are tight enough to publish
within a budget; that is the empirical question, answered negatively in RESULTS.md. Unsupported scope: ratio / conditional queries, non-singleton query tables,
EXACT_RATIONAL mode with positive-width stopping; interior queries beyond the replay cap are NOT_PUBLISHED (fallback = the existing CQR solver, unchanged).

## 5. Additions of the diagnostic round (19 Nov 2026, after the overseer's reading)

Positive-mass witness (correctness repair). Every publication of a marginal presupposes Z > 0. The code now publishes (EXACT, DETERMINISTIC, PAC) only after one of
these EXACT facts: a closed cell with positive mass, an open cell with L_C > 0, an evaluated separator assignment with z(s) > 0 (then Z >= z(s) > 0), or an exact
enumeration / full elimination with Z > 0. Marginals of eliminated components and factorless variables are deferred until such a witness exists; without one they are
withheld (`withheld_without_witness`). Control: two contradictory parity factors on 12 variables + an independent unary [1, 2] + a factorless variable (Z = 0): nothing
is published; with an enumerable separator the outcome is ZERO_EVIDENCE. Note that a sampled Z estimate is never a witness; the ratio stream's lower confidence bound
is used only as a PAC lower bound inside the PAC acceptance rule.

Mini-bucket proposal (prior art: Liu, Fisher, Ihler 2015, weighted mini-bucket importance sampling; here the plain max variant on the separator model {g_b}).
Elimination order x_1..x_m (min bucket size). Bucket B_i = current functions containing x_i, partitioned into mini-buckets Q_i1, Q_i2, ... of joint scope <= cap;
lambda_i1 = sum_{x_i} prod_{Q_i1} g (summed), lambda_ik = max_{x_i} prod_{Q_ik} g (k >= 2); messages join later buckets; U = product of the scalar messages.
Every function in a bucket is either an original g_b or a message, and every non-scalar message appears in exactly one later bucket, so
    prod_i prod_{g in B_i} g(x) = z(x) * prod_{non-scalar lambda} lambda(x).
Proposal (sampled in reverse order): q(x_i | x_>i) = prod_{Q_i1} g(x_i, x_>i) / lambda_i1(x_>i) (uniform if lambda_i1 = 0, in which case z(x) = 0 for every completion).
Then z(x) / q(x) = prod_{scalar lambda_i1} lambda_i1 * prod_{i, k >= 2, non-scalar} [prod_{Q_ik} g(x) / lambda_ik(x)] * prod_{i, k >= 2, scalar} prod_{Q_ik} g(x)
<= prod_{all scalar lambda} = U, since each bracket is <= 1 (lambda_ik is a max) and each scalar lambda_ik >= its summand. q(x) = 0 implies z(x) = 0. The same
partition with min in place of max gives L_mb <= Z. The ratio stream uses the constant cap U (b_t = 1, V = t U^2 / 4); the signed stream uses the per-query cap
U * max(|lo_j - c_j|, |hi_j - c_j|) with [lo_j, hi_j] the global range bound of f_j (interior: root conditional-response range; separator: [0, 1]). Acceptance is the
unchanged rule |S_j| <= eps Z_lo with Z_lo = max(L_mb, sum of z over DISTINCT evaluated assignments, ratio lower confidence bound). The code asserts z(x)/q(x) <= U
and |Y_j| <= cap_j on every draw; the injected-cap control (U >> 40) is refused on the first draw.
