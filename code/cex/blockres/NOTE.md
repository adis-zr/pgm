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

## 6. The integrated method (round 3, 19 Nov 2026): `integrated.py`

Representation (Lemma F). Every table is stored as M * 2^e with M binary64, max M in [1, 2), plus a scalar rho with: exact entry in [M (1 - rho), M (1 + rho)] 2^e for every
entry, and M = 0 iff the exact entry is 0. (i) Exact integer -> float: shift by k so that the maximum is < 2^1000; if k > 0 every nonzero entry must keep >= 64 bits
(else the float path is REFUSED, typed NUMERIC_RANGE_REFUSED); float(int) is correctly rounded; rho = u + 2^-63 (u = 2^-53). (ii) Product of k tables: rho' = prod (1 + rho_i)
(1 + u)^(k-1) - 1. (iii) Sum of n nonnegative terms in any order: rho' = (1 + rho)(1 + u)^(n-1) - 1. (iv) max / min: rho unchanged (the extremum of the floats is the float
of an entry; the bound holds entrywise). (v) Rescaling by a power of two is exact; a nonzero entry below 2^-900 of its table maximum REFUSES the path (no subnormals; zeros
stay exact). Controls: all entries of all block tables and an eliminated message verified inside their bounds by exact rational arithmetic (CONTROLS_INT_FINAL.json).

Proposal and cap. The mini-bucket pass of section 5 is run on the float block tables: the summed mini-bucket of each bucket defines q(x_i | x_>i), the maxed ones the bound;
U_cap = (product of the scalar messages) * (1 + rho_U)(1 + rho_W) >= U_exact (1 + rho_W). Sampling is in the log domain: log2 p_a = sum over the summed mini-bucket of
(log2 M + e); probabilities below 2^-900 of the row maximum are truncated to 0 (missed mass <= U * |S| * 2^-900, inside eps_num); the draw is numpy cumsum + searchsorted on
the float probabilities, and log2 q(x) is accumulated from the same floats. The weight used in the certificate is X = 2^(log2 z - log2 q - log2 U_cap), clipped to 1, where
log2 z is the sum over blocks of (log2 M_b[s_b] + e_b). The code asserts log2 X <= 2^-30 on every draw (the injected 40-bit cap reduction is refused on the first draw).
Exactness statements that survive the float path: X > 0 observed implies z(s) > 0 (every rho < 1), so Z > 0 (the positive-mass witness); U_cap = 0 implies Z = 0 (float
zeros are exact zeros, nothing is truncated inside tables).

The direct marginal certificate. For query j with conditional response f_j in [0, 1] (separator indicator, or the interior ratio M_Q 2^(e_Q) / M_G 2^(e_G) clipped to [0,1])
and a candidate m, Y_t(m) = X_t (f_jt - m) in [-1, 1] with E_q[Y(m)] = (Z / U_cap)(mu_j - m) exactly for the ANALYSED law (q = the float conditionals as exact dyadic
rationals, X = z / (q U_cap) exact). The implemented quantities differ from the analysed ones by a relative bias bounded by eps_num = rho_W + rho_f + |S| 2^-50 (realized
draw law vs analysed law) + |S| 2^-900 (truncation) + 2^-40, recorded per run (2^-34.7 on BN_12) and added to the certificate as a shift allowance Lambda eps_num on the center.
Confidence sequence: predictable-plug-in empirical Bernstein (Waudby-Smith & Ramdas 2020, Theorem 2; for bounded variables in [0, 1], here applied to (Y + 1)/2):
    0 in CS_t(m)  <=>  | sum_i lambda_i Y_i(m) | <= 2 ln(2/alpha) + 2 sum_i psi_E(lambda_i) (Y_i(m) - mhat_{i-1}(m))^2 + Lambda eps_num,
psi_E(l) = (-ln(1 - l) - l) / 4, mhat_{i-1}(m) = sum_{j<i} Y_j(m) / i, lambda_i in [0, 0.9] predictable (from the running variance at the running estimate; any predictable
choice in [0, 1) is valid for every fixed m, so no union over m is needed: the confidence set C_t = {m in [0, 1] : 0 in CS_t(m)} is valid because the sequence Y_t(mu_j) has
mean exactly 0 and the CS for THAT fixed sequence fails with probability <= alpha, time-uniformly). Because Y_i(m) is affine in m, both sides are quadratics in m with
m-free coefficients (A - m B and c + 2(P - 2 m Q + m^2 R)), so C_t is [0, 1] minus at most two open root intervals; the code publishes its convex hull (a superset) when the
hull is at most 2 eps wide, at risk alpha = delta / K per query; the K sets hold simultaneously with probability >= 1 - delta (union bound). All sums are widened by
(1 + 2^-30) >= (1 + u)^(t + 10) for t < 2^20 draws, the square root by (1 + 2^-40), and the hull by 2^-45 outward. No separate normalizer lower bound enters.
Normalizer baseline. The same draws feed a PrPl-EB confidence sequence for E[X] = Z / U_cap (the WMB-IS-style finite-sample bound on Z with the unweighted max
mini-bucket proposal); it is reported, not used for publication.

Scope not covered: weighted (Hoelder) mini-buckets; shared backward recovery (the float replay per interior variable was fast enough on both tasks: 0.05-0.09 s, all 42 / 24
interior variables recovered, none failed); ratio / conditional queries.

## 7. Round 4 (19 Nov 2026): the numerical kernel repaired; conservative inversion; batch loop; lambda schedules (`integrated.py` v2)

Two defects reproduced by the overseer in v1, and their repairs.
(a) Rounding allowances vanished: v1 propagated relative-error bounds as binary64 expressions such as (1 + rho)(1 + u)^(n-1) - 1 with u = 2^-53, where 1 + u rounds to 1.
    v2 keeps every rho as an exact Fraction; products use rho' = prod (1 + rho_i)(1 + u)^(k-1) - 1 and sums of n nonnegative terms rho' = (1 + rho)(1 + u)^(n-1) - 1 exactly, and
    a bound becomes a float only by rounding UP at the point of use (`fup`). Control R1: the exact table [2^53, 1] summed in binary64 has absolute error 1 and the v2 bound
    allows 2.0000000000000004 >= 1 (v1 allowed 1/128).
(b) Underflow before the range check: v1 multiplied tables whose nonzero entries individually passed the 2^-900 range test, so a positive product could underflow to a float
    zero that `_rescale` then treated as exact. v2 attaches to every table its dynamic range R (bits from the maximum to the smallest nonzero entry) and PRE-CHECKS every
    product: sum of the operands' R must not exceed 1000, so the smallest positive product is >= 2^-1000 x the product of maxima, a normal float; otherwise the float path is
    REFUSED (typed NUMERIC_RANGE_REFUSED) before any value is formed. Hence a float zero is an exact zero, and the two exact statements of section 6 (witness, U = 0 => Z = 0)
    hold. Control R2: a strictly positive two-variable model whose products span 1802 bits is refused, never ZERO_EVIDENCE; R2b: the same model at 802 bits computes and
    its publications contain the oracle truth. On BN_12 the largest product range is 29 bits, on ObjectDetection_24 under 60.
Conservative inversion. The accumulators A, B, P, R, Lambda, Psi (nonnegative sums over t terms) are widened by the factor (1 + (t + 2) u)(1 + 2^-40) (any summation order of
nonnegative terms; depends on the actual t, no fixed horizon); Q (signed) by (t + 2) u times the accumulated |terms|. The feasibility |A - m B| <= c + 2 (P - 2 m Q + m^2 R) is
split at m0 = A / B into two convex quadratics h_side(m) = aq m^2 + bq m + cq with every coefficient rounded outward (toward keeping more); each quadratic's excluded set
{h < 0} is bounded by evaluating an UPPER bound h_up (nextafter after every operation) and bisecting from verified-kept points, so the excluded interval found is a subset of
the true one and the returned set is a superset of the analysed confidence set. Control C6: on 30 random accumulator states the returned set contains the set computed by
exact rational arithmetic on a 4001-point grid.
The widening eps_num is derived from the tracked exact bounds (`numerical_widening`): rho_X <= (1 + rho_tab)(1 + rho_logz)(1 + rho_q)(1 + rho_U)(1 + rho_exp) - 1 with the
log-domain terms bounded by |log2 M| <= 1, |e| <= 1000, 1 / ln 2 <= 1.45, the proposal's n_sep steps each contributing q1 log-lookups, one exp2, one row sum of <= maxcard
terms and two logs; rho_f from the query and block tables; the realized-vs-analysed law term 4 n_sep (maxcard + 2) u; truncation n_sep 2^-900; eps_num = 2 rho_X + rho_f +
law + trunc (2^-32.0 on BN_12). The certificate center is shifted by Lambda eps_num and the variance term by 8 eps_num Psi. The runtime cap assertion tolerates exactly the
proved relative error of the implemented X over the analysed X <= 1 (log2(1 + 2 rho_X)), nothing more; the largest observed log2 X on BN_12 was -0.0 (i.e. a weight at the
cap) and on ObjectDetection_24 -2.06.
Batch loop. Draws are generated in batches of 1,024; lambda_t and the plug-in mean mhat are computed from the pre-batch state and held fixed within the batch. Both are
therefore predictable (they depend on draws 1..t_pre only) for every draw of the batch, which is all Theorem 2 requires; the plug-in mean is coarser than per-draw, which
affects efficiency only. Per-draw cost: 0.006 ms on BN_12 (65x over v1's per-draw Python loop; 6,700x over the exact-integer path of round 2).
Lambda schedules. 'baseline': lambda_t = min(0.9, sqrt(2 ln(2/alpha) / (v_t t ln(t + 1)))) (the general-purpose rate). 'targeted': lambda_t = 2 E[X] eps / (v_t + 2 E[X] eps)
(the overseer's accuracy-targeted heuristic, from maximizing lambda E[X] eps - 2 psi_E(lambda) v), clipped to [1e-4, 0.9]; E[X] and v_t are pre-batch running estimates.
Both are predictable; the guarantee is identical; only the speed differs. Measured on BN_12 (section RESULTS_INTEGRATED_V2.md): baseline 106 / 158 published at 20 s with
maximum remaining width 0.0116; targeted 158 / 158 published at 6.7 s (three seeds). The baseline's lambda had decayed to 0.009 by t = 3 x 10^6 while the targeted one sat at
0.21: the general-purpose schedule was indeed wasting samples at this accuracy target, as the overseer's 5x discrepancy between the two extrapolations suggested.
What the proof now establishes: every published interval is a valid 1 - delta simultaneous confidence set under the analysed sampling law with the implemented-versus-
analysed bias bounded by exact rational arithmetic and added explicitly; the float path refuses rather than computes whenever a positive value could be lost; set inversion
is conservative. What the runs show: BN_12 complete in 6.7 s with mutual consistency across seeds, schedules and proposal caps; no independent exact BN_12 reference exists
on record (disclosed in round 3). Not covered: weighted mini-buckets; ratio / conditional queries; a compiled (non-numpy) kernel.

## 8. Round 5 (19 Nov 2026): the scale gap (`integrated.py` v2.1)

Defect (overseer's reproducer: one factor 2^E [[1,3],[3,9]], E = 2^24; exact marginals 1/4, 3/4): `numerical_widening` assumed |log2 M| <= 1 and |e| <= 1000 and the
implementation enforced neither. The log tables stored log2 M + e, so a scale exponent of 2^24 entered float logarithms whose ulp at that magnitude is 2^-29: the measured
bias of the implemented X(f - mu) was 24.8x the declared allowance (the cap assertion still passed; no BN_12 publication is shown false).
Repair. (i) Every power-of-two exponent is now an exact integer and is cancelled before any float logarithm: the proposal's row tables hold log2 M only (within a row all
states share the same tables, so the row's exponent sum cancels in the normalization exactly); the blocks' log tables hold log2 M only, with E_z = sum_b e_b an exact
integer; the scalar mini-bucket messages contribute a float part log2 M in [0, 1) and an exact integer E_U. The single combination E_tot = E_z - E_U is exact (refused if
|E_tot| >= 2^50), and log2 X = (logz_f - logq - logU_f) + E_tot is formed once, with every float operand bounded by tracked range bits. (ii) The widening is derived from the
ACTUAL magnitudes: |log2 M| <= R (the table's range bits, tracked), the row log-sums <= sum of the row tables' R, |log2 p_a| <= 901 by truncation, |log2 tot| <= log2 n; each
log2 call contributes u(|value| + 1), each partial sum u times its magnitude bound, exp2 4u relative (libm within 2 ulps assumed), a row sum (n - 1) u; absolute log2 errors
are accumulated as exact Fractions and converted by 2^d - 1 <= 1.45 d (1 + d) (refused if the total exceeds 1/4). Two budgets are kept apart: rho_cap (tables vs exact
integers, float rows vs exact row products, scalar messages, implementation) widens the cap so that z_exact / (q_an U_cap) <= 1; rho_X (implemented vs analysed X) enters
eps_num = 2 rho_X + rho_f + law + trunc. Control R4 (E = 2^18 in the committed suite; 2^24 takes minutes to parse from its decimal UAI encoding, which cost this round 204 s
of budget in a timed-out control run): implemented X vs the analysed X = z / (q_an U_cap) in 80-digit decimal over all four assignments, worst relative error 1.96e-16 against
the declared rho_X = 1.90e-12 (ratio 1.0e-4; before the repair the same control failed by 5e11); the run publishes the four marginals and contains the truth; BN_12 eps_num
moves from 2^-32.0 to 2^-37.9 because the stated magnitudes replace the assumed ones.

## 9. Round 7 (19 Nov 2026): the exact route for unsplit constructions (`integrated.py` v2.2)

Split census. The mini-bucket pass now records every bucket that was split (`mb_splits`, `mb_split_steps`); exactness is decided from this record, never inferred from the
sampled weights. Census at proposal cap 2^24: BN_12 9 splits, BN_15 22, Promedus_14 23, ObjectDetection_24 6, CSP_13 0, MILDEW 0, 1npl refused before the pass.
The exact route (taken when splits = 0, `--route auto`). An unsplit pass is exact bucket elimination on the separator model, so Z = product of the scalar messages
(an FT scalar with exact rho). The marginals come from one shared backward pass, the arithmetic-circuit differential (Darwiche 2003; the same operation as the
all-singleton reverse pass of cex_kernel.cpp): D(final scalars) = 1 and, at each forward step (v, bucket, R), for every f in the bucket
    D_f(x_f) = sum over (union of the bucket's scopes) minus scope(f) of  D_R(union minus v) x prod_{g in bucket, g != f} g,
formed zero-safely with prefix / suffix products (no division), range-pre-checked and rho-exact like every other FT operation. For the input block table g_b this gives
D_b(s_b) = dZ / dg_b(s_b) = the product of all other blocks summed over the rest of the separator. Separator variable x: N(x = v) = sum_{s_b : s_b[x] = v} g_b D_b for any
block containing x. Interior variable x of block b: N(x = v) = sum over the block's variables except x of [prod of the block's ORIGINAL (evidence-restricted) factors] x D_b,
computed by a fresh greedy variable elimination that retains x (`ve_retain`); this replaces the per-variable replay with x retained, whose intermediate tables (scope x card(x)
x card(v)) exceeded the memory cap on MILDEW's two large-cardinality variables, because D_b lets the boundary variables be summed out early. Publication: the exact rational
enclosure [N (1 - rho_N) / (Z (1 + rho_Z)), N (1 + rho_N) / (Z (1 - rho_Z))] from the float values and exact rho bounds, intersected with [0, 1], labelled
DETERMINISTIC_EXACT_ROUTE (delta = 0); a zero numerator is an exact zero (float zeros are exact under the pre-check). Z.M > 0 with rho_Z < 1 is the positive-mass witness.
Independent cross-check. The existing certified executor (cex/newarm/cex_executor.py, binary64 kernel with reciprocal-envelope labels) is run on the discovered separator
model (the exact rational block tables, renumbered) with the discovered elimination order; its separator-variable intervals must overlap ours, else the route returns
INVESTIGATE and publishes nothing (control E6: every block derivative scaled by 1.5 is caught: 28 / 28 separator coordinates disjoint). Controls E1-E4: 217 deterministic
publications on four small models (complete ternary separator with hard zeros and evidence, mixed cardinalities, unary factors, a factorless variable) all contain the oracle
truth, widths <= 1.6e-12; E5: a split construction stays on the PAC route.
Measured: MILDEW COMPLETE 616 / 616 in 9.5 s (exact route 5.3 s of it, almost all in the 30 interior retained eliminations), max width 2.4e-13, rho_Z 1.4e-14, executor
cross-check CERTIFIED with 130 / 130 separator coordinates overlapping; the round-6 PAC route had left 186 coordinates unrecovered. CSP_13: the exact route is REFUSED
('table dynamic range exceeds 2^900' inside the backward pass: a derivative table spans more than 900 bits), so the method falls back to the PAC route and completes 258 / 258
in 6.1 s as before -- deterministic CSP_13 needs either an exact-integer backward pass or a split-mantissa representation for the derivative tables (not done). BN_12 and
BN_15 are split constructions and keep the PAC route unchanged (6.7 s / 7.4 s).

## 10. Round 8 (19-20 Nov 2026): three repairs of the exact route; the weighted mini-bucket proposal (`integrated.py` v2.3)

A1 Root derivatives. The forward pass returns scalar roots r_1..r_m (one per connected component of the separator model plus free-variable multiplicities), Z = prod r_i,
and dZ/dr_i = prod_{j != i} r_j. v2.2 initialized every root derivative to 1 (correct only for m = 1), which scaled every component's numerators by the OTHER components'
normalizers (the overseer's reproducer: unary [1, 3] and [2, 5] gave centers 1/28, 3/28, 2/28, 5/28 for truths 1/4, 3/4, 2/7, 5/7). v2.3 forms the root derivatives as
zero-safe prefix / suffix products of FT scalars (exact rho, range-checked, the final product included in the accounting); a zero root is refused before any normalized
publication (Z = 0 is ZERO_EVIDENCE). Controls (cross-check DISABLED, so correctness does not rest on the second implementation): two components; three ternary-clique
components with pendant interior variables and unequal normalizers; a zero-mass component; constant factors with a factorless variable. All contained / typed.
A2 A requested cross-check must succeed. v2.2 accepted an executor ERROR with zero compared coordinates as success. v2.3 requires status CERTIFIED, a row for EVERY published
separator coordinate (required = compared, missing = 0) and no disjoint interval; otherwise the route returns CROSSCHECK_FAILED (typed) and publishes nothing; in auto mode
the qualified PAC route runs instead. `NCEX.Stop` is read through `.kind` / `.reason`. Control: a broken executor loader -> 0 deterministic publications, PAC fallback in auto.
The cross-check shares the contracted blocks and covers separator coordinates only; the oracle controls remain the correctness evidence for interior answers.
A3 Compaction. Every deterministic enclosure is widened outward onto the dyadic grid Q = 2^52 in exact integer arithmetic (L = floor(Q lo) / Q, H = ceil(Q hi) / Q,
intersected with [0, 1]) and the publication width rechecked (none of MILDEW's 616 exceeded 2 eps). The guarantee label of the run is derived from the row labels
(DETERMINISTIC / EXACT / PAC). Serialization is timed separately; the SUPERVISOR receipt is the scored end-to-end measurement. MILDEW: result 127,813 bytes (was 57.4 MB),
solver 2.22 s, serialization 0.0025 s, supervisor receipt 2.37 s end to end (was 23.30 s), max width 2.40e-13, cross-check 130 / 130, 616 / 616 DETERMINISTIC.
Weighted mini-buckets (Liu, Fisher & Ihler 2015). On the SAME partition and order as the reference max pass (replayed by tagged scope signatures), each split bucket's
groups r get weights w_r in [0.05, 1] summing to 1 (fixed policy: equal weights, then for two groups the best of a 5-point grid by the bucket's total log2 bound; the (1, 0, ..)
limit is the old construction and is a separate arm); messages M_r = (sum_x F_r^(1/w_r))^(w_r) computed in the log domain (log-sum-exp is 1-Lipschitz, so the input error is NOT
amplified across levels; the float operations are bounded at magnitude <= Rsum / w_min and tracked as exact Fractions, rounded up onto a 2^-200 grid to keep them finite);
proposal row q_i = sum_r w_r p_r with p_r = F_r^(1/w_r) / sum_a F_a^(1/w_r), the FULL mixture row normalized and sampled by one CDF (the analysed law = the float row as
exact dyadics). Cap: Hoelder sum_x prod_r F_r <= prod_r M_r and weighted AM-GM prod_r (F_r / M_r) = prod_r p_r^(w_r) <= q_i, telescoping to z / q <= U_wmb. Selection by
CONSTRUCTION information only: the proposal with the smaller certified log U is frozen before any draw (a cap belongs to its proposal). Controls: exhaustive normalization,
support of every positive assignment, and z_exact / (q_an U_cap) <= 1 on every assignment (80-digit decimal) for four tiny models incl. conflicting hard zeros, a 2^300 common
rescale and mixed cardinalities; end-to-end containment; injected understated cap refused.
Measured: with bounded weights (w >= 0.05) the weighted bound was LARGER than the max bound on ObjectDetection_24 (log2 U 3925.6 vs 3914.1: the grid's best weights were
(0.15, 0.85) at every split bucket), so the max proposal was selected and the ObjectDetection_24 result is unchanged (118 vs 114 / 1,260 published with the two seeds' noise);
on the control models the tightening was 0.26-0.39 bits. The Promedus_14 weighted construction was MEMORY-KILLED at 3.0 GiB (the group-product log tables at cap 2^24 are
built densely); its baseline is reproduced (ESS 1.84, largest share 66.5 %, 83.2 % zero weights, 1.49 M draws). The round cap (300 s) was reached before the three-seed matched
comparison; the single-seed matched pair on ObjectDetection_24 is the only proposal measurement of this round.

## 11. Round 9 (20 Nov 2026): proof-to-code note for the changed numerical operations (`integrated.py` v2.4)

(A) Scalar products. `ft_scalar_product` now rescales after EVERY multiplication: M <- M m_i exactly in binary64 up to one rounding, then M <- M 2^-k with k = floor(log2 M) (exact), e <- e + k.
The mantissa stays in [1, 2) for any number of factors (the overseer's 1,800 x 1.5 reproducer overflowed before), the exponent is an exact integer, and the bound is the same
prod (1 + rho_i)(1 + u)^(n-1) - 1 in exact rationals. The empty product is the exact 1; an exact-zero factor gives the exact zero (and the root-derivative pass refuses a zero root before
any normalized publication: Z = 0 is ZERO_EVIDENCE). Control: (3/2)^1800 vs the exact rational, inside the allowance; 40 disconnected components with 2^40-scaled normalizers through
the exact route: all 80 marginals contained.
(B) Certified cap comparison. A proposal's certified log2 cap is  logU_f + log2(1 + rho_cap) + E  with logU_f the float part (sum of log2 of the scalar roots' mantissas), E the exact
integer exponent sum and rho_cap the full widening actually used by that proposal's sampler and certificate (tables, rows, stored-message envelopes, implementation). Two proposals are
compared as (E_wmb - E_mb) [exact integer, refused above 2^50] plus the difference of the two bounded float parts; the smaller certified cap is frozen before any draw; its widening
travels with it (the stream reads rho_cap from the SELECTED proposal's widening). Control D2: with a 4 % envelope injected into every weighted message the raw weighted cap is still
0.388 bits smaller but the certified one is larger, and the max proposal is selected.
(B) Conversions, audited. Relative <-> log2 conversions are the two inequalities 2^d - 1 <= 1.45 d (1 + d) for 0 <= d <= 1/4 and log2(1 + r) <= 1.45 r for 0 <= r <= 1; both are now
functions that CHECK their domain and refuse the candidate otherwise (`rel_from_log`, `log_from_rel`); no bound is converted back and forth more than once per level. The weighted
power sum (sum_x F^(1/w))^w is positively homogeneous of degree 1 in its inputs, so a common multiplicative envelope (1 +- grho) on all inputs passes through UNCHANGED in exact
arithmetic: the stored message's envelope is (1 + grho)(1 + rho_float) - 1 with rho_float the FLOAT error of the log-domain evaluation alone (member log2 lookups, the row log-sum,
subtraction of the row maximum, division by the float weight, exp2 within 2 ulps, the row sum, log2 of the sum, multiplication by w, addition of the maximum: every term bounded at its
actual magnitude, with 1 / w <= 20 from the admitted domain), converted ONCE by rel_from_log; the pass-through replaces v2.3's repeated conversions that inflated rhoU to 3e24 on
ObjectDetection_24. Hoelder and the weighted AM-GM hold for the EXACT power sums of the STORED tables at every level, so the certified cap chain is
(1 + rho_tab)(1 + rel(rows))(prod_messages (1 + rho_float))(1 + rho_X) - 1, refused above 1/2. The round-8 statement that the 11.5-bit loss on ObjectDetection_24 was due to the weight
floor compared RAW bounds; with v2.4's widening the weighted candidate's certified cap on the small controls is within 10^-11 of its raw cap, and the ObjectDetection_24 comparison is
NOT re-run this round (no WMB construction in the sweep).
(C) Weights. Every weight is an exact Fraction >= 1/20, a bucket's weights sum to 1 exactly (asserted), the sampler receives float(w) and the error analysis uses the exact w; a bucket with
more than 20 groups makes the candidate INELIGIBLE (typed) and the max proposal is used (the overseer's K_22 unit-factor reproducer). The float weight's rounding is included in d_M.
(D) The maintained end-to-end weighted control now asserts that WMB was SELECTED (certified diff -0.388 bits on the mixed-cardinality 2^300-rescaled model) and every publication contains
the oracle truth, at the LABELLED relaxed tolerance eps = 1/20 for fast coverage; the sweep contract stays eps = 1/200. W4 reports requested vs selected proposals.

## 12. Round 10 (20 Nov 2026): compact conservative error bounds; byte-budgeted query recovery (`integrated.py` v2.5)

Correction of the round-9 diagnosis (reviewer's measurements, confirmed by a phase probe on or_chain_53: contraction 0.19 s / 95 MiB, float conversion 0.22 s, recovery of 637
per-variable tables = 817 MiB of floats): the memory kills were in interior-query RECOVERY and STACKING, and the exact-route stalls in the EXACT-FRACTION rounding allowances.
Compact bounds. Every rounding allowance is now a small Fraction: (1 + u)^k - 1 <= k u + (k u)^2 (from (1 + u)^k <= e^(ku) <= 1 + x + x^2 for x = k u <= 1, refused beyond), and
prod (1 + rho_i) - 1 <= S + S^2 with S = sum rho_i <= 1 (same inequality; refused beyond), rounded up onto the 2^-200 grid. Both replace exact powers whose numerators had
k x 53 bits (k up to the union-table size 2^20) and exact products over hundreds of factors. The bounds are weaker by at most a factor (1 + S) and remain upper bounds, so
every certificate statement of sections 6-11 is unchanged; the recorded widenings grow by less than a part in 10^-10 on the development cases.
Recovery. Per block, ONE (|g_b|, K_b) float array is preallocated and the replay's columns are written into it directly (the per-variable table is released immediately; no
np.stack copy). A global byte budget bounds the retained tables (CORRECTION, round 11: the submitted v2.5 constant `RECOVERY_BYTE_BUDGET` is 512 MiB; the exposed-case records of round 10 were produced with 640 MiB and the final code has 512 MiB; the stored responses of every successful exposed case fit under both, so the difference does not explain any result); interior variables whose columns would exceed it are typed RESOURCE (NOT_PUBLISHED), so a large
model degrades to a partial answer instead of a memory kill. Sharing of the backward computation across a block's interior variables (one differential per block instead of a
replay per variable) is NOT done in this round; the forward prefix is shared as before.
Deadline. The backward differential checks the deadline per factor as well as per step.

## 13. Round 11 (20 Nov 2026): publication guard, compact root allowance, exact-first ordering, memory policy, shared recovery (`integrated.py` v2.6)

F1 Guarded deterministic ratios. `interval_ratio` returns None unless the denominator enclosure's LOWER endpoint z (1 - rho_Z) is strictly positive (rho_Z >= 1 is UNRESOLVED, never
ZERO_EVIDENCE and never a division); a zero numerator is the exact zero only because float zeros are exact zeros; a numerator envelope reaching zero from above gives the valid
unresolved [0, 1]. Every publication passes `valid_publication`: exact 0 <= lo <= hi <= 1 and width <= 2 eps, applied before AND after the outward dyadic compaction, and asserted
once more over every PAC publication. The reviewer's valid-envelope adversary (root rho 3/4 -> comb 21/16) now yields a typed refusal of the exact route with nothing published
(control F1_wide_envelope_above_1_after_comb); the half and 1/100 envelopes publish only the ratios that stay within 2 eps, all contained. Zero numerators publish the exact 0;
zero global mass is ZERO_EVIDENCE; a compaction that would widen a borderline interval past 2 eps is rejected.
F2 The scalar-root allowance is ONE comb(rho_1..rho_m, pow1pu(m)) (denominator <= 201 bits for 40 / 200 / 400 roots, measured 200-201), replacing the per-root exact product.
Ordering. Float conversion -> memory plan -> mini-bucket FORWARD construction only -> split census -> exact route (forward messages + one backward pass) -> only if that does not
publish: PAC preparation (recovery representation, sampler log tables with the forward message mantissas released, widening, certificate). The exact route no longer pays for
PAC query matrices or sampler tables; the same overall deadline governs both routes (no second budget).
Memory policy. One dry-run planner (`mb_plan`, scopes only) estimates, per cap of the fixed ladder (requested 2^24, then 2^22 .. 2^10), the forward message bytes, the largest
single-step product workspace (x2) and the sampler log bytes; the plan must fit base (live float tables + integer factors + 160 MiB process headroom) + forward + step peak and
base + logs + recovery budget + 64 MiB batch temporaries within a usable ceiling of 2.5 GiB of the 3 GiB contract; the first fitting cap is frozen before any table is built; none
fitting is a typed MEMORY_POLICY_REFUSED. Dense precomputed responses are retained only while the 512 MiB recovery budget allows (cheapest blocks first); every other block takes
the SHARED path. The batch size halves (minimum 32) until B x (3 x largest shared union table + 4 x K_q) fits 384 MiB; lambda and the plug-in mean are predictable per batch as
before. A smaller cap changes the proposal law and its certified cap together (both frozen before sampling) and can worsen statistical efficiency; it is a resource choice.
Shared recovery, exact route (`block_numerators_exact`). Per block: forward FT elimination of the interior variables in the recorded order with the boundary retained; root
derivatives D_r = sum_{boundary minus scope r} D_b x prod_{others} (zero-safe prefix / suffix); then at each step (v, bucket, R) in reverse, N_v(a) = sum over (union minus v) of
[prod bucket] x D_R  (one pass per block instead of one retained elimination per variable) and member derivatives by prefix / suffix products; rho through comb / pow1pu; the
deadline is polled per step and per member. Identity: this is the arithmetic-circuit differential of the block's elimination with the outward message as the root seed.
Shared recovery, PAC route (`SharedBlock.responses`). For a batch of sampled separator assignments, the block's original factors are restricted to the sampled boundary values
(a gather), the interior elimination is run in batched float arithmetic with per-sample power-of-two rescaling, the per-sample root r(s) = g_b(s_b) and the reverse pass give
N_v(a | s) for every interior v; the response f = N_v(a | s) / r(s) is exactly the conditional expectation P(x_v = a | separator = s) used by the dense representation (control:
identical to the dense ratio on all 2,112 supported assignment-columns of a 6-variable ternary-interior model; on unsupported rows the weight is exactly zero so the response is
irrelevant). Its arithmetic allowance rho_f = comb(factor rhos, pow1pu(ops))^2 (numerator and denominator) with ops the data-independent operation count of the block's
elimination, carried into eps_num like the dense rho_f. Memory per batch: B x the block's largest union table (bounded by the batch policy); no |g_b| x K_b array is ever formed.

### 13a. Post-freeze resource patches v2.7 / v2.7.1 (20 Nov 2026) and what the frozen panel showed

The frozen v2.6 panel (pgm 6bbda68) still memory-killed mastermind_03_08_04-0003 and or_chain_53 at 3.0 GiB. Phase probes (records round11/probe_phases_*.txt) located the peak
in `prepare_sampler`: the forward message mantissas (1,024 / 1,319 MiB) and the sampler log tables (1,042 / 1,321 MiB) coexisted (peaks 2,675 / 3,165 MiB), whereas the v2.6
memory plan had assumed the forward tables were released first. v2.7 (pgm 4770856) interleaves the release: a max-group member's mantissa is freed as soon as its log table
exists, a summed member's right after its log table is built; the backward pass frees derivatives per step; the memory policy also estimates the exact-route peak
(base + 2 x forward + 3 x step workspace) and skips the exact route with a typed MEMORY_POLICY_SKIPPED when it does not fit. v2.7 wrongly also freed the forward MESSAGE
mantissas in the backward pass, which the PAC fallback still needs when the exact route is refused after its backward pass (CSP_13 crashed: TypeError in prepare_sampler).
v2.7.1 (pgm 7ee66d1) keeps them, and makes a deadline inside a shared-response batch abandon only that batch: the completed batches, the certificate state and the intervals
published at the last check are retained and reported (v2.6 / v2.7 raised Deadline out of the loop and reported draws = None). Both patches change resource timing and
reporting only: no bound, estimator, publication test or proposal law changed; controls 9/9 + 13/13 + 15/15 pass on v2.6, v2.7 and v2.7.1. Panel cells rerun on the patches are
labelled post-freeze in the records (round11/panel_v27, round11/panel_v271); the frozen result stands in round11/panel.
Measured on the three former memory kills (v2.7.1): all three now run to the deadline under 2.6 GiB with every requested coordinate in the certificate (Kq = K); none completes.
mastermind_03_08_04-0003 is unsplit at cap 2^24 (exact proposal, X = 1 on every draw) and published 3,082 / 4,504 PAC coordinates from 6,144 draws; its deficit is the shared
response cost: 15 shared blocks (8 with 114 interior variables and union tables of 2,048 entries) cost 2.0 s per 1,024-draw batch = ~500 draws/s against ~140,000 draws/s on
the dense path. The sampled boundary assignments repeat heavily (0.2-3 % distinct per batch on this case, 0.6-1.1 % on or_chain_53, 25-84 % on mastermind-0015; diagnostic
`shared_unique_boundary_fraction`), so evaluating each distinct boundary assignment once per batch would cut this cost by one to two orders of magnitude; NOT implemented this
round. Its exact route was eligible (no splits) but skipped by the peak estimate (3,045 MiB > 2,560); a chunked backward pass would make it a deterministic candidate.
mastermind_03_08_04-0015 (cap 2^22 by the ladder, 121 splits) drew only zero-weight samples (9,216 of 9,216): no positive-weight draw was OBSERVED in that run (poor overlap; NOT a demonstrated support hole; corrected after the round-11 review), not
memory. or_chain_53 (cap 2^24, 47 splits) has 97.5 % zero weights and ESS 4.6 of 167,936 draws: proposal concentration, as or_chain_132.

## 14. Round 12 (20 Nov 2026): the shared path under the range lemma; live-workspace accounting; active-row / unique-boundary evaluation (`integrated.py` v2.8)

Authorization: the round-11 adversarial review (records round12/BLOCKRES_R11_ADVERSARIAL_REVIEW.md): "one bounded repair pass covering the numerical defect, live-workspace accounting
and bounded deadline checks, then test active-row/unique-boundary recovery on mastermind-0003 and the two other shared targets".
Defect (reviewer's reproducer, confirmed on v2.7.1 under receipt r12_repro_underflow_v271): `SharedBlock.responses` multiplied batched tables and rescaled AFTERWARDS, so a positive
product that rounds to zero in binary64 (four factors normalised to (2^-600, 1) / (1, 2^-600): product 2^-1200 on both states) became an exact zero response; the certificate then
published [0, 1.4e-4] for a marginal equal to 1/2. Counting operations in rho_f does not cover this: the relative-error lemma for a float product requires the RANGE condition
first (sum of the operands' range bits <= 1000, so the smallest positive product >= 2^-1000 x the maximum, far above the subnormal range).
Repair (the same discipline as the FT kernel, per sample): every live batched array carries per-sample range bits R (its smallest nonzero entry >= 2^-R of its row maximum; rows
rescaled to a maximum in [1, 2) by exact powers of two; non-finite rows refused); before EVERY product (forward bucket, root, backward bucket x derivative) the per-sample sum
of the operands' R must be <= RANGE_BUDGET or the batch raises RangeRefused; the final ratio N_v(a | s) / r(s) is formed with an exact ldexp of the integer exponent difference
and a response above 1 + 2 rho_f + 2^-40 is a certificate defect (assert). A data-independent PREFLIGHT at construction refuses a block whose restricted ORIGINAL factors of one
elimination step already exceed the budget (the reviewer's case: 2,404 bits), typing the block's queries NUMERIC_RANGE_REFUSED before any draw; a refusal raised in the stream
abandons that batch only: the certificate holds the completed batches, whose publications stand, and the outcome is the typed refusal (control P1). Nothing is clipped or
skipped silently. Lemma (unchanged): for mantissas with range bits R_i and sum R_i <= 1000, every positive product is >= 2^-1000 >= 2^-1021 (normal), so each rounding is a
relative (1 + u) factor and comb / pow1pu apply; a float zero is then an exact zero. Controls: U1 (adversary -> NUMERIC_RANGE_REFUSED, 0 false publications), U2 (same structure at
2^200: computes on the shared path, 8/8 contained), U3 (shared responses vs an INDEPENDENT exact-rational enumeration over the original integer factors on all 32 boundary rows x 27
columns: worst 5.5e-17 against rho_f 7.5e-15; zero-mass rows have root exactly 0).
Memory (reviewer's measurement confirmed: 30 / 131 MiB measured against a 3.2 / 3.4 MiB formula): the formula B x 3 x largest union ignored the restricted factor copies, the stored
forward products and messages, and the derivatives alive across the trace. v2.8 (a) no longer stores the forward product P (rebuilt from the prefix products in the backward pass),
computes derivatives only for messages (never for original factors) and drops each derivative when consumed; (b) simulates the trace at construction (scopes only) and bounds the
simultaneously live floats per sample: all restricted factors + all messages + the derivatives crossing each backward step + that step's workspace ((2k + 5) x |union| + |v|),
exposed as `bytes_per_sample`; (c) ONE per-batch budget (BATCH_BUDGET = 384 MiB, also the term used in the memory plan's PAC peak) covers the response matrix and the
certificate's temporaries (7 x K_q floats per draw) plus the shared workspace: the batch halves (down to 1) until it fits, a typed MEMORY_POLICY_REFUSED if even one draw does not,
and shared blocks are evaluated in MICROBATCHES of `chunk` rows sized to the remainder; (d) the executor cross-check runs under a JOINT budget (host_reserved_bytes = the
process's peak RSS at entry). Controls: tracemalloc peak of responses() <= B x bytes_per_sample on the reviewer's 15 / 40-step chains (13.7 / 51.4 MiB measured against 20.1 / 57.8
MiB planned) and on a random block. The 2.5 GiB usable ceiling, the dense budget and the headroom are module constants so a control can inject them: M2 injects a usable limit
between the planned peaks of caps 2^12 and 2^10 on a 16-variable model and checks that the ladder actually descends (8 caps tried, 2^10 chosen, 5 splits), the run reaches the
sampler and publishes contained intervals, and the CHOSEN proposal passes an exhaustive support / cap validation over all 65,536 separator assignments.
Deadline: `responses(S, deadline)` polls before every forward and backward step (control D1: raises within 0.13 s where the full evaluation takes 0.83 s); a Deadline inside a shared
block abandons that batch and keeps the completed ones.
Active rows / unique boundaries (the reviewer's two exact shortcuts): shared responses are evaluated only for rows with X > 0 (every certificate term involving the response is
X f or X^2 f, so the zero response on a zero-weight row changes nothing; the row still enters the certificate with the batch's predictable lambda and plug-in mean, and the draw
count is unchanged); among the active rows each DISTINCT boundary assignment of the block is evaluated once and scattered back to the sample order (the response is the same
Rao-Blackwellized conditional expectation). Control A1: identical response matrix on the active rows and bit-identical certificate state against the full evaluation on the same
300 draws (180 active, 2 distinct boundary rows, 2 microbatches). The maintained suite check_integrated_v2.py is adapted to the lazy sampler lifecycle (10/10 FAST).
Corrections to round 11 prose (recorded in round11/RESULTS_ROUND11.md): all 9,216 zero weights on mastermind-0015 show that no positive-weight draw was OBSERVED in that run, not
that the proposal's support misses the target's; the BN_12 forced-shared ablation was compared with the dense run (158 / 158 overlapping intervals), not with an exact reference.

## 15. Round 13 (20-21 Nov 2026): the exact route executes under the contract for unsplit constructions (`integrated.py` v2.9)

Authorization: the round-12 adversarial review (records round12/BLOCKRES_R12_ADVERSARIAL_REVIEW.md, sha256 2a96e5c8...): close round 12 as a negative performance result, make the
two resource corrections narrowly, correct the forecast prose, and take "one bounded architectural attempt" at executing the discovered unsplit exact computation within the
contract on mastermind-0003 (tile large contractions, manage trace lifetimes / recomputation, keep the PAC fallback and the cross-check; do not hard-code the case, disable the
cross-check or raise the usable limit).
Measured cause of the skip (round13/probe_*): the v2.8 estimate base + 2 x forward + 3 x step peak = 3,045 MiB came from (a) keeping every forward table through the reverse walk
and (b) an UNTILED step workspace: the largest step of mastermind-0003 has k = 11 members over a 2^24-entry union, so its (2k + 3) union-sized prefix / suffix / product arrays need
3,200 MiB alone (the next four steps 1,664 MiB each); an unguarded run of the old reverse pass was MEMORY_KILLED at 3.3 GiB inside the first large step (receipt
r13_probe_exact_route_phases_mastermind_0003). The forward live set is small (64 MiB peak) and the cross-check alone fits (8.2 s, +280 MiB; receipt r13_probe_crosscheck_...).
Tiling (`tiled_member_derivatives`). At a reverse step the derivative of member i is sum over (union minus scope_i) of D_R x prod_{j != i} A_j. The union axes are split into LEADING
axes (enumerated one index at a time) and TRAILING axes (processed whole), with the trailing block chosen so that (2k + 3) trailing-sized arrays fit TILE_BUDGET (256 MiB): for every
leading index the prefix / suffix products and the k member products are formed on the trailing tile and reduced over the trailing axes outside scope_i; the result is ACCUMULATED
into the output at the leading indices that belong to scope_i (summed over the leading axes that do not). Because scopes are sorted tuples (as every FT scope), a member's
variables appear in union order and its leading / trailing split follows the union's. Identity: the same multiset of nonnegative products is summed in a different order, so the
value is identical in exact arithmetic and the rounding bound pow1pu(nsum - 1) (nsum - 1 additions of nonnegative terms, each a relative (1 + u)) holds for any summation order;
the range pre-check is unchanged (the operands are the same tables). Control T1: 548 random (member, tile) cases incl. tiles that split a member's scope, 1 to 48 tiles, worst
relative difference 6.4e-16 against the untiled computation.
Lifetimes (as written in round 13; CORRECTED in section 16): v2.9 freed a message's mantissa at ITS OWN reverse step, so between its consumer's step and its own step the
mantissa and the derivative coexisted; the round-13 claim that the live bytes equal the forward total was false for that policy (reviewer: 320 MiB of message payload against a
168 MiB plan on DBN_14). The rest of this paragraph is superseded by section 16. The memory plan therefore estimates the exact route as base + forward + TILE_BUDGET + block tables
+ 64 MiB (`reverse_live_bytes` = forward bytes; mastermind-0003: 1,592 MiB, observed process peak 1,958 MiB including the cross-check's native kernel, 1,680 MiB before it = the
construction peak). The forward tables are gone after a released reverse pass: if the exact route is then refused or fails its cross-check, the (deterministic) construction is
REBUILT for the PAC fallback (`mb_rebuilt_for_pac`, control T3: cross-check INVESTIGATE on a corrupted derivative -> rebuild -> PAC COMPLETE, contained). Control T2: the released /
tiled exact route publishes intervals IDENTICAL to the unreleased / untiled computation on three models (all contained); T4: the traced peak of the released reverse pass is within
the plan.
Result on mastermind-0003 (receipt r13_probe_solve_exact_mastermind_0003_v29, frozen settings, 19.5 s budget, 3 GiB): COMPLETE 4,504 / 4,504 DETERMINISTIC in 12.99 s (contract
0.72, float convert 1.04, construction 0.80, reverse pass 1.92, block numerators 0.65, executor cross-check 7.69 s CERTIFIED on all 272 separator coordinates), peak RSS 1,958
MiB, widths median 5.6e-12 / max 9.4e-10. This is the first full 20-second completion on a formerly failing exposed case; it is exposed development evidence (the instance was
seen in rounds 9-12), not transfer evidence. The cross-check is 59 % of the wall time.
Shared-path corrections (reviewer's findings 1-2 and the exponent point): `fixed_workspace_bytes` = 16 KiB + 1 KiB x (factors + 6 steps + columns) accounts for the allocation
overhead that does not scale with B (array objects, views, dicts, lists); the batch and microbatch policy uses fixed + B x payload (control S1: traced peaks 7.2 KiB / 503 KiB /
53.9 MiB against 25.9 KiB / 859 KiB / 61.0 MiB planned at B = 1 / 1 / 128); this is array-payload accounting plus an explicit overhead term, backed by the process headroom and
enforced end to end only by the supervisor. The deadline is polled at entry and before every factor gather (control S2: an expired deadline permits zero gathers). The exponent
difference is converted with a checked domain (|e| < 2^30, typed refusal) and asserted <= 1023 (by the range lemma N_v / r >= 2^-1001, so a true ratio <= 1 never needs a larger
exponent); the only floor is at -2200, where ldexp of any mantissa below 2^80 is exactly 0, and the absolute error of an underflowed final ratio (<= 2^-1021) is added to rho_f.
Forecast correction (round 12 records): the "170-270 s" figure was elapsed x (width / target)^2, a square-root-law heuristic; the recorded targeted-schedule trajectory fits
a + b / (n + c) and projects about 85-119 s; neither is a measured completion time, and 170-270 s against a 20 s contract is 8.5-13.5x, not 17-27x.

## 16. Round 14 (21 Nov 2026): the reverse lifetime invariant, proved and simulated; a fresh generalization panel (`integrated.py` v2.9.1)

Authorization: the round-13 adversarial review (records round14/BLOCKRES_R13_ADVERSARIAL_REVIEW.md, sha256 c2b62c5e...): "make the narrow lifetime-accounting correction and retain
the existing completion under the same budget; freeze that build; run a small, explicitly budgeted fresh generalization panel".
Defect (confirmed on v2.9 under receipt r14_repro_lifetime_v29 with the reviewer's star: plan 688 B, simultaneous message payload 640 + 640 = 1,280 B): a message's mantissa was
released at its own reverse step, but its derivative is created at its CONSUMER's reverse step, which comes earlier in the reverse walk; both arrays coexisted in between.
Repair (v2.9.1): the mantissa is released right after the consumer step has used it, which is its only reader in the reverse walk (the step producing the message uses D_R and the
bucket members' mantissas, never R's own). Invariant: at reverse step s (steps > s processed), a message m created at c(m) and consumed at k(m) > c(m) has only its derivative alive
when c(m) <= s < k(m), only its mantissa alive when k(m) <= s, and neither when c(m) > s; so the persistent payload at s is the prefix sum of message sizes up to s, maximal at the
start = the forward total. The plan now SIMULATES this per step (`mb_plan.reverse_live_bytes`) and adds the TRANSIENT of the step being processed: the members' derivative outputs
(the tiled helper allocates them in full before its tile loop; their mantissas are still alive at that moment) and the rescale copy of the largest member; the scalar roots'
8-byte mantissas and derivatives are counted (the roots are not released). The exact-route estimate is base + reverse_live + TILE_BUDGET (tile scratch) + block tables (the input
derivatives) + 64 MiB headroom; mastermind-0003 stays admitted (persistent 1,024 MiB + transients). Controls (check_round13.py T5, round 14): the production reverse pass is
instrumented per step for mantissas not released, message derivatives in D, the outputs being created and the rescale copy, on the reviewer's star, a 14-variable ring and
c7_complete_sep: the largest simultaneous payload equals the plan exactly (1,704 / 504 / 229,784 B) and no message ever has mantissa and derivative alive together; T4 passes with the
plan's own numbers. This is an array-payload invariant (NumPy object / list / dict overhead is charged to the headroom, as for the shared path); the supervisor enforces the contract.
The reviewer's DBN_14 measurement (320 MiB) is addressed by construction: with release at the consumer step the two 160 MiB sets cannot coexist. The six preservation cases and
mastermind-0003 are rerun on the frozen v2.9.1 (round14/preservation).
Fresh panel. Pools: uai14 prob (142 names), uai2022 final MAR (88), uai2022 tuning MAR (120), MC2024 WMC conversions (26); 230 distinct models by sha256. Exposure census
(round14/selection/EXPOSURE_CENSUS.json): a ripgrep of every name over code/runs and docs (33 s, complete, excluding the pool directories themselves) classifies a name as EXPOSED
if it occurs in any file that is not a pool enumeration (inventories, selection candidate lists, hash manifests, archive scans, package-exclusion lists, download / conversion
logs): 83 exposed (every instance ever planned, run, inspected or named in a note or review), 155 fresh in 7 families. Selection (seed 20261121, before any run): family = the
leading alphabetic token; seeded family order, round-robin at most two per family, 8 instances, model-sha256 dedup, seeded run order; a first draft that treated blockmap
sub-families as separate families was superseded before any run and is recorded in the manifest. Both arms (incumbent N1_CQR bank arm, identical supervision), alternating order.
Declared cap 900 s (the round-9 / round-11 sweep caps; none was named in the review).

## 17. Round 15 (21 Nov 2026): the reverse transient closed; window-expired blocks keep their queries (`integrated.py` v2.9.2)

Authorization: the round-14 adversarial review (records round15/BLOCKRES_R14_ADVERSARIAL_REVIEW.md, sha256 28e198b1...): finish the output-lifetime correction without changing a
bound, estimator, proposal or certificate; correct the failure diagnosis; one bounded recovery-scheduling experiment on blockmap_10_03-0009; no broad sweep.
Transient (reviewer's Finding 1, confirmed on v2.9.1 under receipt r15_repro_transient_v291: observed 2,216 B against a 1,704 B plan on the 13-variable star; 484 vs 332 MiB on
DBN_14 in the review): inside a reverse step the raw member outputs returned by the tiled helper were all retained while the rescaled derivatives accumulated in D. v2.9.2 CONSUMES
each raw output as soon as its rescaled copy exists (pop before rescale, delete after), so raw outputs still waiting plus rescaled derivatives already made never exceed the sum of
the member sizes plus the one copy in flight, which is exactly the plan's transient term. The T5 liveness control now OBSERVES the rescaling loop: it instruments the production
`_rescale`, deduplicates every live array by its ultimate NumPy base (forward mantissas, message derivatives, raw outputs still held, the rescaled result) after every call, and
requires the peak to be within the plan (star 1,576 / 1,704 B; ring 472 / 504; c7_complete_sep 164,248 / 229,784), in addition to the entry-time check and zero mantissa /
derivative coexistence. Round-15 control R1 is the reviewer's reproducer verbatim. No bound, estimator, proposal or publication test changed.
Recovery window. The dense precomputation of interior responses is OPTIONAL (a speed path when it fits the 512 MiB budget) and runs inside the construction window (construct_share
x budget); v2.5-v2.9.1 SKIPPED every interior block reached after the window closed, so its queries never entered the certificate (blockmap_10_03-0009: 2,495 variables, 4,990
coordinates, round 14). v2.9.2 gives such a block its shared representation instead (construction is a scopes-only simulation, microseconds per block): every requested query is
eligible for certification; the dense budget and window are unchanged; `blocks_window_to_shared` records the count. Control W1 slows the dense replay so the window closes after
the first block: 5 blocks go shared, Kq = K, complete and contained; W2 (window open) stays dense and agrees. This is the completion of the round-11 requirement "all requested
queries eligible for certification"; whether the shared path then finishes within the contract is a measurement (round15/RESULTS_ROUND15.md).
Diagnosis corrections (round 14 records): linkage_13's 275 publications are EXACT (fully eliminated components; its PAC stream published 0 of 1,883; ESS 1.46); blockmap published
4,754 PAC + 264 EXACT and 4,990 coordinates were excluded by the window (not 5,254; ESS 5,799, every admitted coordinate certified; the stream stopped at 16.9 s because the
admitted set was finished): a recovery-SCHEDULING failure, not concentration. Hence FOUR poor-overlap fresh cases (two or_chains, linkage, mastermind_03_08_05-0003), one
scheduling case, one favourable-overlap completion (ObjectDetection_43: ESS 99.2 % of draws, one split, no zero weights), one integer-route completion (Promedus_36).

## 18. Round 16 (21 Nov 2026): shared-block responses reused across batches (`integrated.py` v2.9.3)

Authorization: the round-15 adversarial review (records round16/BLOCKRES_R15_ADVERSARIAL_REVIEW.md, sha256 83f384d4...): "implement byte-budgeted response reuse across batches,
verify identical certificate state on a fixed draw sequence, and run one exposed blockmap test under the unchanged contract"; fold in the observer and phase-label corrections.
Finding (reviewer's replay of the recorded blockmap prefix): all 949 positive-weight draws of the 15,872 carried the SAME full separator assignment, so every shared block
re-evaluated the same boundary in every batch; the within-batch `np.unique` forgot it between batches.
Mechanism (`evaluate_shared`): per shared block an entry map keyed by the block's FULL boundary assignment holds the response row f_b(s) already computed in an earlier batch; a
hit substitutes that row, a miss runs the unchanged certified computation (microbatched, deadline polled on the miss) and stores the new rows while the retained bytes stay under
RESPONSE_CACHE_BUDGET (64 MiB, counted in the memory plan's PAC peak; no eviction; keyed by object identity of the immutable block within this model / evidence / construction).
Correctness: f_b(s) is a deterministic function of (block, s) with the block-constant envelope rho_f; reusing the stored value IS the same certified response, so no importance
weight, proposal law, predictable lambda, risk allocation or certificate update changes; every draw (zero-weight and repeated alike) still enters the certificate. Failures are never
cached: a refusal or deadline raised inside the computation propagates before any row is stored (the stored rows of a chunked miss are written only after every chunk succeeded).
Controls (check_round16.py): C1 a fixed 12-batch draw sequence replayed with and without the cache gives bit-identical response matrices for every batch and bit-identical
Certificate state (110 hits, 10 misses = 10 entries); C2 budget 0 disables it identically; C3 a refusal on the second chunk of a miss stores nothing; C4 an expired deadline on a
miss evaluates nothing; C5 end-to-end shared solve complete and contained with 3,969 hits / 7 misses; R1 the corrected transient observer (the array being rescaled included) equals
the plan exactly (1,704 B). The round-12 P1 control now injects at the shared-evaluation call and its M2 control zeroes the cache budget with the other PAC-peak terms.
Corrections (round 15 records): the T5 / R1 observers undercounted by the array being rescaled (1,704 B = plan, not 1,576); blockmap phases 4.3 s contraction + conversion (not 6 s);
0.063 is the last-checked width at 18.97 s; "eligibility versus partial publication is a reporting-policy choice" is withdrawn: it is an execution decision (doubling the
coordinates raised the log risk term 3.1 % while draws fell 5.8x: the penalty is response work coupled to every certificate update, not simultaneous validity).

## 19. Round 17 (21 Nov 2026): cache resource corrections; the control crash; the engine frozen as the baseline (`integrated.py` v2.9.4)

Authorization: the round-16 adversarial review (records round17/BLOCKRES_R16_ADVERSARIAL_REVIEW.md, sha256 7d71bc4c...): three local corrections, then freeze the engine and move the
main effort to proposal / partition quality on or_chain_186, or_chain_209, linkage_13 and mastermind_03_08_05-0003.
(1) Cache charge. v2.9.3 charged K_b x 8 + 8 x |boundary| + 128 bytes per entry, which omitted the ndarray object, the tuple and its int objects and the dictionary's capacity: under an
injected 512 KiB budget the reviewer measured 754,792 B of retained containers and arrays (851,396 B of object graph) against a 524,248 B charge. v2.9.4 charges the RETAINED objects
per entry (`cache_entry_bytes`): sys.getsizeof(row) + row payload + sys.getsizeof(key) + the key's int objects + 96 B of dictionary share (CPython grows a dict by doubling into a new
table while the old one is alive: 2 x the (index + entry) slot x 2 tables) + the empty dict for the first entry. Control K1 (the reviewer's 4,096-boundary block, 512 KiB budget):
1,658 entries admitted, charged 523,992 B, the reviewer's lower bound (maps + keys + rows, ints excluded) 365,840 B and the full identity-deduplicated object graph 438,824 B, both
under the budget; responses exact. This is a per-entry object account, not a whole-process bound; the supervisor enforces the contract.
(2) Optional reservation. v2.9.3 added the 64 MiB cache constant to every candidate PAC peak in cap admission, so an optional optimisation could lower the proposal cap or refuse an
admissible route (reviewer: an unsplit four-cycle admitted at 2^24 without the reservation was refused at every cap with it). v2.9.4 reserves NOTHING for the cache in the plan; after
the mandatory plan is admitted, the per-solve allowance is min(constant, USABLE - planned PAC peak) when the solve has shared blocks and 0 otherwise (`response_cache_budget_bytes`).
Controls K3a (the reviewer's planner regression: same cap with and without the constant) and K3b (a shared solve reports an allowance within the remaining capacity and stays under it;
a dense solve reports 0).
(3) Deadline. `evaluate_shared` polls at entry, so an all-hit call with an expired deadline raises like a miss (K2, warmed cache); the miss-path poll is kept (C4 now tests it with a
clock that expires after entry).
(4) The shipped round-15 control: the observer correction of round 16 placed `backing = {}` after a comment marker, so `check_round15.py` raised NameError on the frozen v2.9.3 and the
round-16 statement "79 controls pass on the frozen build" was FALSE: 76 passed and the round-15 suite crashed (receipt r16_r15_controls_1 NONZERO_EXIT; the grep that summarised the
suites matched nothing for it and I did not notice). Restored; the round-16 records are corrected. On v2.9.4 every suite has a result file: 83 controls (round-17 4, round-16 6,
round-15 3, round-13/14 12, round-12 11, round-11 15, exact-route 9, weighted 13, numerical 10).
Round-16 reporting corrections: round 14 had median width 0.0100028 at 82,944 draws (just above 0.01) and published at the next check (92,160); `extrapolated_s_median_width` 14.6 s is
a square-root-law estimate of the TOTAL active stream-plus-check duration (about 5.4 s beyond the spent duration), excluding start-up, not "14.6 s more".
Engine freeze. v2.9.4 is the baseline engine for the proposal / partition research the reviews call for; blockmap_10_03-0009 stays an exposed regression target (264 / 10,008, no
completion), not a prerequisite.

### 19a. Closeout of the implementation pass (21 Nov 2026): v2.9.4 at pgm 03f7d76 is the frozen research baseline

Accepted by the round-17 adversarial review (83/83 controls rerun independently; 752 publications of the independent exact-enumeration audit contained; archive identities and the
eight completions verified). KNOWN LIMITATION, recorded and not repaired: the response-cache charge (`cache_entry_bytes`) covers the per-ENTRY retained objects (row array + payload,
key tuple + ints, dictionary share) but not the outer map of per-block maps nor the empty per-block maps themselves; with 1,500 small block caches the reviewer measured 681,180 B
retained against 524,020 B charged. The counter is therefore a per-entry account, NOT a strict whole-cache memory bound; it does not affect response correctness or any recorded run
(blockmap: 30 entries), and the supervisor enforces the process contract. No standalone round for it.
Fixed by this closeout: (baseline) this commit's integrated.py (sha256 in CODE_IDENTITY_round_blockres_r17.json), its guarantees, and the working structural routes (the incumbent's
integer / structural executors remain the fast paths on cases such as Promedus_36); (evidence) Round 9 is a closed negative evaluation, Round 14 supplies ONE fresh-instance transfer
result (ObjectDetection_43, development-represented family), and the exposed repairs of rounds 10-17 are not generalization evidence; (next objective) diagnose the lost dependencies
in the four poor-overlap cases (or_chain_186, or_chain_209, linkage_13, mastermind_03_08_05-0003), justify one construction, then one bounded implementation experiment; no winning
proposal intervention is established; (blockmap) an exposed regression target in the ledger, not a prerequisite.

## 20. Round 18 (21 Nov 2026): exact support closure before the partition (`integrated.py` v2.10, `support_closure.py`)

Authorization: the overseer's R18 theoretic pass (records round18/R18_SUPPORT_CLOSURE/: diagnosis, proof, prototype, 312-case checker, brief). Decision: implement ONE general constructor
in front of the engine: exact support propagation, batched factor-implied bijection quotienting, weight-preserving substitution, to a fixed point; run the unchanged engine on the
reduced model; decode every original requested coordinate. Preserve v2.9.4 as the comparator (`--no-support-closure`).
Construction (`support_closure.py`; the `gac` / `quotient` primitives keep the prototype's signatures so its independent exhaustive checker runs against the production module: 312/312).
Support propagation: a state of v is deleted only when some incident factor has no positive row with that state whose other states are in their current domains. Every globally
positive assignment supplies a supporting row in every factor, so by induction over deletions every positive assignment survives; an empty support is exact ZERO_EVIDENCE; a
nonempty closure proves nothing about positivity (Mackworth 1977). Bijection quotient: a pair (u, v) of a factor's scope is an alias only when the factor's complete positive pair
projection is the graph of a bijection between the FULL current domains (n distinct keys inside a domain of size n). All recognised bijections are composed into components with
one representative and explicit permutations; where two composed maps disagree on a representative state that state is deleted (no positive completion). Substitution rewrites every
factor OCCURRENCE through the maps (diagonalising scope variables that share a representative, dropping rows inconsistent with the maps), keeps rational weights, multiplies a factor
that became constant over its full reduced domain into an exact positive scalar c, never merges duplicate occurrences, and checks every reduced entry (zeros included) against the
source table through the maps. Decoder: every original variable is a fixed value, or a state of one representative under an explicit permutation, so original positive
assignments correspond one-to-one with reduced ones and w(D(y)) = c w'(y): Z = c Z' and N_j = c sum_y w'(y) f_j(D(y)); an original singleton coordinate decodes to EXACT 1 / 0
(fixed), EXACT 0 (outside the representative's image) or its representative's row (same enclosure, same guarantee: deterministic query recovery, no new statistical event).
Placement and bounds: after read_uai and before integerization, contraction and the memory plan. A declared optional allowance of SUPPORT_CLOSURE_SHARE_S = 0.5 s inside the worker
budget and a SUPPORT_CLOSURE_BYTE_CEILING = 128 MiB live-byte estimate (rows, domains, maps, decoder, rewritten tables; count-based, conservative); a deadline or ceiling raises a
typed ClosureRefused and the engine continues on the ORIGINAL model with the time charged (mechanism.support_closure.status = SKIPPED: ...). The denominator stays the original K;
`effective_K` records the reduced one. Nothing decoded is published without the positive-mass witness; a fully contracted reduced model reports Z = c x (constant blocks x factorless
multiplicity / scale). The PAC route on a reduced model is the same route on the same kind of model (the closure changes the model, not the sampler); its publications decode as
above. First integration: the transformed-versus-original choice is made before any sampling (no stream combination).
Controls (check_round18.py, closure ON; the nine frozen-path suites set SUPPORT_CLOSURE_DEFAULT = False and still pass 83/83): S1 weighted 3-state bijection; S2 inconsistent cycle ->
ZERO_EVIDENCE, nothing published (oracle agrees); S3 partly consistent permutation cycle (2 representative states removed, 6 EXACT-0 rows, all contained); S4 evidence propagation fixes
two variables with proven-zero states; S5 two aliases in one ternary factor + a duplicated weighted occurrence (weights multiplied); S6 exact scalar 14/15 and Z = 98/5 equal to the
oracle's; S7 factorless multiplicity (uniform 1/4) and Z; S8 zero global mass with a fixed variable publishes nothing; S9 an injected 1 us allowance -> typed SKIP, original PAC route,
contained; S10 all-original expansion (K 21 from effective 7, each coordinate once, alias rows identical); S11 a reduced model that still needs PAC: contained, comparator agrees;
S12 the nine frozen suites rerun with the closure ON show 0 containment misses (8 path-expectation failures, as expected: dense / shared paths vanish when the closure contracts
the control model). Development probe (receipt r18_probe_mastermind05_closure, not a scored cell): mastermind_03_08_05-0003 EXACT 7,294 / 7,294 in 1.77 s end to end, 55 MiB, closure
0.095 s (2,806 deletions, 2,925 fixed, 563 relations, 278 representatives, 257 factors, 556 effective coordinates), 0 separator variables, no draws.

### 20a. Round 18 measured (v2.10.1, pgm ced5776; 21 Nov 2026)

v2.10.1: the closure allowance runs from the closure's own start (v2.10 anchored it at worker start, so MILDEW's 0.64 s read consumed it and the closure was refused at entry); the
deadline is polled at entry and per factor while the support rows are materialised. Scored cells of the first pass (v2.10) are kept as round18/*_v210_superseded.
PRIMARY PREDICTION PASSED: mastermind_03_08_05-0003 EXACT 7,294 / 7,294 on seeds 1, 2, 3, byte-identical answers (fingerprint 0baff9a7ef6b80c2), supervisor 1.64 / 1.68 / 1.67 s,
process-tree peak 56 MiB, signature exactly as predicted (2,806 deleted states, 2,925 fixed non-observed variables, 563 bijection relations, 278 representatives, 257 factors, 556
effective coordinates, 6 rounds, 0.096 s), 0 separator variables, no draws, positive witness from the fully contracted exact route, Z reported; every original variable's two
points sum to 1; all 7,294 points equal the overseer's prototype. Comparator (same build, --no-support-closure = the v2.9.4 path): 0 / 7,294 in 19.5 s at 2.4 GiB (131k draws, no
positive weight). Incumbent N1_CQR (round-14 receipt, same digests): DEADLINE, 0.
Other targets (closure ON vs OFF): or_chain_186 2 / 2,138 (one variable fixed by propagation; PAC 0; ESS 4.5) vs 0; linkage_13 426 / 2,158 (the closure fixes the 177
singleton-domain variables already present in the input and 5 aliases, so 426 EXACT coordinates publish where v2.9.4 published 275 exact-component ones; PAC 0 of 1,971; ESS 13.4
vs 1.5) vs 275; or_chain_209 0 / 1,698 (nothing to close; ESS 11.7) vs 0. No completion gain, as predicted; the EXACT rows are fixed-state recovery, not statistical progress.
PRESERVATION PASSED: BN_12 6.64, BN_15 7.35, CSP_13 6.11 s PAC; MILDEW 2.52, Alchemy_11 1.28, DBN_14 10.34 s deterministic (cross-checks CERTIFIED); ObjectDetection_43 6.00 s PAC;
mastermind_03_08_04-0003 now EXACT 4,504 / 4,504 in 0.90 s through the closure (1,452 fixed, 634 relations, 310 representatives) instead of the 13.1 s exact route + cross-check;
every new interval overlaps its round-17 counterpart (0 disjoint). Measured cost of the declared allowance: MILDEW's closure (100-state tables) exceeds 0.5 s in the substitution
step and is refused after 0.63 s charged (the engine then runs the original route and completes); the allowance was NOT changed, per the brief. The closure is IDENTITY on CSP_13
and DBN_14 (0.02 / 0.01 s) and APPLIED-with-no-change-of-route on BN_12 / BN_15 / Alchemy_11 / ObjectDetection_43 (0.015-0.22 s).
Evidence limits: one exposed target; the construction's correctness rests on the proof in the R18 packet, the 312-case exhaustive oracle (run against the production module) and
the 12 integration controls, not on an independent exact oracle for the large model; the comparator is the v2.9.4 code path inside the v2.10.1 build, not the 03f7d76 binary
(the frozen-build references are the round-14 cells and the overseer's Linux baseline); the exact-route + executor cross-check path is now exercised on the panel by MILDEW,
Alchemy_11 and DBN_14 only. Budget: 659.3 s charged against a self-declared 600 s (the v2.10 -> v2.10.1 rerun added ~185 s); disclosed, not hidden.

## 21. Round 19 (21 Nov 2026): signed evidence expansion as an exact algebraic operator (`integrated.py` v2.11, `signed_evidence.py`)

Authorization: SPEC.md of the R19 packet (records round19/PACKET/, packet sha256 489a24fe...): implement the independent-root noisy-OR chain family through a small algebraic-operator
interface (recognize / estimate / execute), recognised on the ORIGINAL model before closure and executed right after it, finalised directly on the original queries; bounded campaign of
sixteen scored cells under a declared 1,200 s; v2.10.1 (ced5776) is the comparator.
Family (exact rational identities, child-first scopes): binary; one normalised child factor per variable -- root prior (1 - p, p); ternary noisy-OR gate (c, root, prev) with failure
entries [1, t_prev, t_root, t_root t_prev] and success complements, prev an accumulator => t_prev = 0; terminal (y, parent) [a, b, 1 - a, 1 - b], 0 < a <= 1, 0 <= b <= a, parent an
accumulator => b = 0, parent a root => b / a its inhibition. All and only terminals observed, positive. Every accumulator has one consumer and lies in one chain; roots may be shared
and recur. Anything else -> NotApplicable (a refusal of this OPTIONAL route). Axis layouts other than child-first are refused, never transposed.
Operator (Heckerman 1989): Z = sum_S (-1)^|S| Q(S), Q(S) = prod_{j in S} lambda_j prod_i [(1 - p_i) + p_i prod_{j in S} theta_ji]; root i state 1 by replacing its affine factor with
p_i prod theta_ji; accumulator Y of chain j state 0 by N(Y = 0, E) = sum_{S not containing j} (-1)^|S| [E(a_Y prod_{l in S} q_l) - Q(S u {j})], the prefix walk changing only the
affected cause's cumulative inhibition (division-free zero handling). Common denominator = prod over roots of lcm(prior denominators) x every inhibition denominator touching the root,
x all leak denominators; every term is an integer over it (CHECKED, never truncated). Signed sums live only inside this executor; nothing signed reaches support_closure, MBFloat,
WMBFloat or the PAC kernels. Output: lo = floor(2^40 N / Z) / 2^40, hi = ceil(...) / 2^40, point the midpoint, DETERMINISTIC (EXACT when lo = hi); each original coordinate once; the
two points of a binary variable sum to 1; no PAC risk spent. Znum = 0 -> ZERO_EVIDENCE with no normalised row; a negative / non-integral / out-of-range quantity -> InvariantFailure
-> CERTIFICATE_DEFECT (never hidden behind the fallback).
Integration (`integrated.solve`): read once -> recognise on the original model (EVIDENCE_RECOGNITION_S = 0.1 s, charged) and retain the immutable plan -> support closure as before
(its exact-zero behaviour kept) -> execute the plan under the remaining global deadline and a workspace budget min(EVIDENCE_WORKSPACE_BUDGET = 256 MiB, USABLE - current RSS), refusing
BEFORE materialisation when the projected retained state (2^m subsets x roots Fractions + ints) exceeds it -> its own finalizer `finish_expansion_` (original queries, no closure
decoder, no scalar; a real code path, not a label) -> otherwise release and continue the existing route with the remaining budget. Enabled for routes auto / exact; skipped for
explicit PAC, force_approx and construct_only. `--no-evidence-expansion` = the accepted R18 comparator path; with `--no-support-closure` as well = the v2.9.4 path. The ten
existing suites set EVIDENCE_EXPANSION_DEFAULT = False (they exercise their own mechanisms).
Verification: the packet's three portable checks pass (41 files verified; reference tiny checks; independent structure + 80/120-digit Z on both OR inputs); the packet's exhaustive
oracle PORTED to call the production module (check_round19_oracle.py: 3 constructed + 3 supplied fixtures, Z and every coordinate exact); check_round19.py T1-T7 (12 controls): the three
supplied fixtures end to end; a recognised model with nonidentity closure and scalar 16/25 returns the original Z once; recognised exact zero (executor branch with closure off and
dispatch with closure on) publishes nothing, a valid nonbinary model falls back; near-match gate, shared accumulator and negative evidence refuse and fall back contained; interrupted
recognition, projected resource refusal and a deadline inside evaluation fall back contained with no signed rows; renumbering + factor permutation give equivalent answers and a
permuted axis layout refuses; both switches, force_approx and construct_only reach their mechanisms. The ten frozen-path suites: 95/95 with the operator off.

### 21a. Round 19 measured (v2.11, pgm a73938a; 21 Nov 2026)

BOTH PREDICTIONS PASSED. or_chain_186.fg: 2,138 / 2,138 original coordinates on seeds 1, 2, 3, byte-identical (fingerprint 920e0225...), DETERMINISTIC (2,136 dyadic enclosures of
width 2^-40 + 2 EXACT points), supervisor 0.78 / 0.73 / 0.72 s, process-tree peak 56-57 MiB, 128 subsets, 474 roots / 595 gates / 7 findings, recognition 5 ms, evaluation 0.49 s
(normalizer + roots 0.30, prefixes 0.18), output 0.03 s, common denominator 9,590 bits, cancellation 32 bits, no draws. or_chain_209.fg: 1,698 / 1,698 on seeds 1, 2, 3, byte-identical
(16df67f4...), DETERMINISTIC, supervisor 2.91 / 2.90 / 2.86 s, peak 85 MiB, 1,024 subsets, 348 / 501 / 10, evaluation 2.68 s (1.58 + 1.08), denominator 6,583 bits, cancellation 38
bits. Every cell's Z and every dyadic endpoint equal the packet's exact reference (tools/compare_candidate.py, six cells). The accepted R18 comparator on the same digests: 2 / 2,138
and 0 / 1,698 at 19.5 s and 1.9-2.1 GiB (poor-overlap PAC); the incumbent: DEADLINE.
Preservation: all nine retained within contract with 0 disjoint intervals against the accepted R18 receipts (BN_12 6.76 s, BN_15 7.49, CSP_13 6.25 PAC; MILDEW 2.66, Alchemy_11 1.41,
DBN_14 10.64 deterministic; mastermind-0003 1.04 s and mastermind-05 1.66 s EXACT through the closure; ObjectDetection_43 6.19 PAC). The operator is NOT_APPLICABLE on all nine
(nonbinary variables, factor count != variables, or evidence value 0) at 0-5 ms recognition cost each; the closure and the existing routes behave exactly as in round 18.
linkage_13 (coverage): 426 / 2,158, unchanged from R18 (operator NOT_APPLICABLE: nonbinary; closure APPLIED; PAC ESS 13.4). No improvement predicted, none observed.
Budget: 180.4 s of the declared 1,200 s (33 receipts: controls 100.3 s incl. the ten frozen suites once each and four runs of the new suite, probes 5.4 s, OR cells 10.9 s,
preservation 44.1 s, linkage 19.7 s). No repair of the engine was needed after freezing; the four reruns of the new suite were fixture corrections (a fixture helper misuse, a
deadline injection that never fired on a 4-subset model, a route expectation on a model the closure fully contracts, a construct-only fixture the closure also contracted).
Evidence limits: two exposed targets (seen since round 14); the large models are not independently enumerated; the certificate rests on the checked exact identities (integrality
asserted, bounds on every numerator asserted), the ported exhaustive oracle on six tiny models, the twelve integration controls and equality with the packet's independent reference
(itself cross-checked against 80 / 120-digit decimal normalizers). No held-out transfer claim; no linkage gain; only the independent-root noisy-OR chain family is recognised.

### 21b. Round 19b (21 Nov 2026): bounded execution of the signed route (`integrated.py` v2.11.1)

Authorization: the R19 review's CLAUDE_FOLLOWUP.md (review zip sha256 5c779360...; records round19b/REVIEW_PACKET/): one narrow production-boundary repair, 300 s declared. Three
reproduced defects of v2.11 (receipt r19b_repro_bounds_v211: a 2-root / 1-finding / 3,000-gate model admitted at 7,848 B while allocating 1.46 MB; returned masses after 31 ms against a
1 ms deadline; a 1,000-root / 1,000-terminal model RECOGNIZED after 363 ms against the 0.1 s allowance; and `ru_maxrss` subtracted from USABLE_BYTES as bytes though Linux reports KiB).
Repair: (1) `estimate(plan, n_queries)` models the SIMULTANEOUS live state with CPython object sizes (integer limbs + containers) in two phases and admits by their max + 64 KiB: the
exponential phase = the plan's m x n coefficient matrix + per-subset theta Fractions / leak Fraction / root-factor ints / two term ints + the signed accumulators (root, B, gate) at
global-denominator + m + 1 bits + the prefix temporaries; the output phase = plan + accumulators + the numerator mapping + one row (~1,100 B) per original coordinate -- the O(g B) and
O(K) terms the old formula lacked. The exponential state is released before the masses are returned and the rows are built. (2) deadline polls inside the chain walk (per 256 gates),
per row of the coefficient matrix, per 1,024 roots in the root loop, per 256 gates in the prefix walk, before each chain's terminal correction, at execute() entry and end, per 512 rows
and at the end of `dyadic_rows`; a structural guard refuses more than MAX_FINDINGS = 40 findings before any allocation (2^m subsets cannot fit any admissible workspace). (3) headroom
in BYTES on the running platform: `rss_bytes_now()` = psutil current RSS, else `rusage_to_bytes(ru_maxrss, platform)` (bytes on darwin, KiB x 1024 elsewhere); the allowance stays
min(256 MiB, USABLE - rss). (4) a Deadline/Resource refusal at or beyond the global deadline returns the established DEADLINE outcome with nothing published instead of starting
fallback work. Polling is cooperative (a single big-integer primitive is not interruptible); the supervisor remains the hard limit.
Controls (check_round19b.py, real work, not injected exceptions): B1 the 3,000-gate model: estimate 10.1 MB (exponential phase 4.7 MB, output phase 10.0 MB) covers the traced peak
4.0 MB of execute + rows; half the estimate is refused before materialisation (traced peak 2.7 KB); B2 a 1 ms deadline expires inside the real prefix walk at gate 255 after 1.7 ms,
no masses; B3 the 1,000 x 1,000 model is refused structurally in 4 ms; B4 unit conversion (1,024 KiB -> 1,048,576 B on Linux; identity on darwin), current RSS <= converted peak, an
injected USABLE just above the RSS grants a budget <= 4 KiB and refuses, USABLE below the RSS grants 0 and refuses, the existing route completes both; B5 the supplied fixtures, the
exact-zero fixture and the nonunit-scalar fixture unchanged; B6 an expired deadline at dyadic_rows builds no row, and a clock that expires right after execute() inside a real solve
returns DEADLINE with 0 published and no fallback phases. Reviewer's reproducer on v2.11.1 (receipt r19b_repro_bounds_v2111b): RESOURCE_REFUSED at the old budget; DEADLINE_REFUSED
at 1 ms; NOTAPPLICABLE (structural) for 1,000 findings. The round-19 suite (12), the production oracle (6) and the ten frozen suites (95) pass on v2.11.1.
Measured on frozen v2.11.1 (pgm 25b8376; records round19b/): or_chain_186 2,138 / 2,138 and or_chain_209 1,698 / 1,698 DETERMINISTIC on three supervised repeats each, 0.73-0.79 s and
2.89-2.91 s, 58 / 86 MiB tree peak; Z and every 2^-40 endpoint identical to round 19 and to the packet reference (tools/compare_candidate.py); the revised estimates are 12.9 MiB
(exponential phase) and 64.7 MiB against the 256 MiB allowance with 49 / 48 MiB RSS at admission. The nine accepted completions retained (0 disjoint vs round 19; PAC cells differ only
in their sampled points, deterministic cells byte-identical). 159.4 s charged of the declared 300 s (33 receipts). No engine change after the freeze.

### 21c. Round 19b closeout (21 Nov 2026): final deadline guards in the signed route (`integrated.py` v2.11.2)

Authorization: the R19b review (closeout zip sha256 8e8771a7...; records round19b/CLOSEOUT_PACKET/) accepted the six OR cells, the nine preservation cells and the resource repair, and
supplied one tested patch for the last unguarded stretch: after `dyadic_rows`' final check, `finish_expansion_` still validated every row, converted Z and ran `BR.finish` before
returning COMPLETE without reading the clock again, and `recognize` recorded its elapsed time without comparing it to the allowance (the reviewer's real-work probe on the 3,000-gate
model returned all 6,004 rows after 196 ms against a 190 ms budget). Applied verbatim (`git apply`, clean on dcc3b48): a poll every 256 rows while validating the original answers, a
final guard after the answer finalization before success is returned, and a final guard at the end of recognition; all three use the existing typed refusals, so the dispatcher returns
the established DEADLINE outcome with nothing published and no fallback work. No change to arithmetic, output values, the memory policy or the fallback algorithms.
Verification (receipts r19b_closeout_*): the reviewer's `check_finalization.py` on dcc3b48 reproduces the finding (COMPLETE 12 / 12 after the clock expires behind the row builder and
behind BR.finish; recognition RECOGNIZED at an expired final read); on v2.11.2 all_guards_hold = true (DEADLINE, 0 published, no fallback phases, RECOGNITION_REFUSED) and the ordinary
solve's Z and all 12 answer rows are identical to the reviewer's before-record and to the local run on dcc3b48. check_round19b (6) and check_round19 (12) pass; the production oracle
(6) passes. Per the closeout instruction no scored cell or full-suite rerun; the ten frozen-path suites run with the operator off and do not reach the patched lines. The bounded-execution
engineering pass is CLOSED; the eleven accepted completions stand.

### 22. Round 20 (23 Nov 2026): certified layered contraction (`layered_contraction.py`, `integrated.py` v2.12)

Authorization: CLAUDE_IMPLEMENTATION_BRIEF.md of the R20 theory packet (zip sha256 7e63816d...; records round20/R20_PACKET/). The theory pass diagnosed linkage_13 as an allele /
selector model whose nonconstant factors split into 7 components (773 / 65 / 40 / 3 / 2 / 1 / 1 active variables), the main one a sequence of 19 locus stages joined by MATCHING binary
channels [9/10, 1/10; 1/10, 9/10], at most 20 selector bits per interface, eight soft penetrance factors coupling the last two loci; a checked elimination order (local allele elimination
per stage, then the selectors stage by stage, the final two loci folded into one terminal block so the last selectors are eliminated inside it) has maximum product 2^21 and output 2^20.
Backend decision by the brief's bounded probe (receipt r20_probe_native_executor_order, records round20/probe/): the EXISTING certified native executor (cex/newarm/cex_executor.py, unchanged)
runs the packet's 885-variable order + the 177 one-state variables on linkage_13 in 8.14 s / 574 MiB tree peak (kernel 8.02 s, 132.6 M forward + 132.6 M reverse rows, 532 MB logical
peak, max label 1.2e8 -> width 2.7e-8), CERTIFIED, so the "planned-exact adapter" is the smallest sufficient integration; the research NumPy transfer prototype was not ported.
Constructor (`layered_contraction.recognize`): exact rational predicates on the evidence-restricted model (constant / channel [a, b; b, a] with a, b > 0, a != b, a + b = 1 for ANY rational
a, b / endpoint fragment / residual = nonconstant non-Boolean multivariable non-channel / local core); the channel graph must be disjoint paths; the affine chain alignment of the packet's
DISCOVERY_PROOF (layer(c, i) = o_c + s_c i; local-core equalities; offsets eliminated along a spanning forest; the homogeneous sign system solved by an exact rational RREF with the standard
nullspace basis -- no sympy; separable unit basis required; <= MAX_FREE_SIGN_BITS = 8 free main-component sign directions -> <= 256 candidates) run as TWO proposals -- (A) every non-channel
factor forms local cores, (B) the residuals are excluded from the cores and must occupy one extreme adjacent layer pair, reflected if at the low end and folded into one terminal stage --
each candidate VALIDATED against the tables independently of its derivation (every nonconstant factor wholly inside one stage or an exact channel between adjacent stages; every boundary a
matching); the best admitted candidate (interface bits, local product, local volume, signs) gives the order (per component, per stage greedy local elimination, then the interface variables
by stage); a primal-graph simulation of THAT order certifies max product / output and the summed volumes. No model name, hash, variable id, locus count or table constant is a rule; hashes
are provenance only. Linkage_13: recognised in 0.27-0.28 s (allowance LAYERED_RECOGNITION_S 1.0 s): 390 channels, 8 residuals, 31 chains, proposal A refuses ("a chain sign is forced to
zero"), proposal B: 260 equalities, sign rank 22 / nullity 9, 5 free bits, 32 examined, 16 admissible, selected 20 bits / 2^21 / 2^20, 885 active + 177 one-state = the 1,062-variable order;
reversed ids, a seeded random relabel and channels changed to 4/5 / 1/5 give the same bounds (structure controls, not transfer evidence). Limits (explicit): residuals outside an extreme
adjacent pair refuse; translation is normalised per core-connected group (the bounded search is not complete over all valid alignments); the brief's six-sector reduction is NOT implemented.
Admission (`forecast`): bytes = 1.25 x 8 x (summed output entries + source entries + 2 x max output + 2 x max product) + 64 MiB + 1,200 B per coordinate, against min(LAYERED_BYTE_CAP 1,536 MiB,
USABLE_BYTES - current RSS) -- calibrated on the probe (messages retained until their consumer: 1.004 x the summed output); time = 2 x summed product entries / ROWS_PER_S_CONSERVATIVE
(20 M rows/s = the probe's 33.1 M rows/s with a 40 % margin) against the remaining deadline; both are refusals BEFORE the executor allocates; the kernel's own hard-charged cap and deadline poll
remain the hard bounds. Execution (`layered_contraction.execute`): the executor's primitives exactly as cex_executor.execute (build / load / lower / kernel / enclose), plus the kernel's
normalizer triple (value, binary exponent, label K_Z) read into the Z ENCLOSURE [Zhat (1 - K_Z u), Zhat / (1 - K_Z u)] x the scalars lower() cancels / prod card of the observed variables
(the kernel gives each observed variable an empty bucket of mass card[v], exact, label 0: it cancels in every N / Z). Z is never an exact point (out['Z_enclosure'], out['Z_log2']); the
cancelled-scalar count is cross-checked against the recogniser's. Rows: the executor's exact enclosures compacted outward on the 2^-52 grid (DETERMINISTIC; EXACT for point enclosures),
one-state and factorless variables published EXACTLY 1 / uniform after checking the executor's enclosure contains that value; every row passes valid_publication with the point inside.
Dispatch (`integrated.py`): recognition on the ORIGINAL evidence-restricted model before closure and only when the signed route recognised nothing; execution right after closure on the
original model object (the closure returns a new reduced model; the plan is bound to the original by the executor's semantic hash); typed refusals (NotApplicable / RecognitionRefused /
ResourceRefused / the executor's typed stops) fall back to the existing route; a refusal at the global deadline returns DEADLINE with nothing published; ZeroEvidence -> ZERO_EVIDENCE;
an acceptance-test failure -> CERTIFICATE_DEFECT. --no-layered-contraction / layered_contraction=False = the v2.11.2 comparator path; the twelve existing suites switch it off.
Controls (check_round20.py, 6, real work, receipt r20_new_controls_4; three harness reruns kept: a summary key, a deadline test that the time forecast refused before the kernel (fixed by an
optimistic injected rate so the kernel's poll is what stops it), and the observed-variable factor in Z): L1 the packet's 16 tiny fixtures end to end (every coordinate and Z contained, closure
APPLIED on each, one decoder); L2 twelve generated chain models (channels 7/10 and 2/3, hard zeros, weighted nonbinary locals, births / deaths, terminal coupling -> proposal B, low-end anchor ->
reflection, evidence on a local / a selector / both, one-state + factorless -> EXACT rows, renaming + factor reversal + axis permutation -> same bounds, every pair overlapping); L3 typed refusals
with the existing route completing (no channel, branching, cycle, residual spanning nonadjacent layers); L4 bounds on real work on a 17-bit / 8-layer model (27.8 M rows, 1.9 s kernel): the
forecast covers the kernel's hard-charged peak (215 MB >= 112 MB) and rows, a real deadline inside the kernel -> DEADLINE with nothing published and no fallback phases, an injected byte cap and an
injected rate refuse BEFORE the executor and the existing route completes, a clock expiring after the executor -> DEADLINE; L5 the switch (in process and --no-layered-contraction) reproduces the
v2.11.2 path; L6 the exposed target's structure and its three representation variants. check_round19 (12), check_round19b (6), the oracle (6) and the ten frozen-path suites (103) pass.
Measured on frozen v2.12 (pgm 769f9cd; records round20/): linkage_13 COMPLETE 2,158 / 2,158 DETERMINISTIC on three separately supervised repeats (8.74-9.08 s end to end incl.
recognition 0.27-0.28 s, closure 0.07 s, executor 8.2-8.4 s of which kernel 8.1-8.3 s; 584 MiB tree peak; 179 EXACT + 1,979 DETERMINISTIC rows, max width 2.7e-8; Z enclosure relative
width 8.6e-13, log2 Z -252.5959, containing the research prototype's Zhat; all 426 previously published EXACT rows enclosed; all 249 independently exact small-component coordinates
enclosed; every row overlaps the research candidate interval), byte-identical across repeats. The same-build --no-layered-contraction comparator reproduces the accepted partial result
(426 / 2,158 DEADLINE_PARTIAL, 19.7 s, 1,082 MiB, the 426 EXACT rows identical to R19). All eleven accepted completions retained (0 disjoint intervals; deterministic cells byte-identical;
the layered constructor NOT_APPLICABLE on the nine in 0-3 ms and SKIPPED on the two or_chains, which the signed route still takes). 298.1 s charged of the declared 400 s (42 receipts).
No engine change after the freeze. Twelve of twelve exposed panel cases now complete; this is an engineering milestone on exposed targets, not transfer evidence (TRANSFER_PROTOCOL.md is
a separately frozen experiment).

### 22b. Round 20b (23 Nov 2026): admission closeout of the layered constructor (`layered_contraction.py`, `integrated.py` v2.12.1)

Authorization: the R20 review's CLAUDE_CLOSEOUT_AND_TRANSFER.md (review zip sha256 b0a21558...; records round20b/REVIEW_PACKET/). The review accepted the twelve-of-twelve exposed result
and reproduced two admission defects (no incorrect probability or normalizer found; 826 independent exact enclosures): (1) the volume certificate used the RECOGNITION graph (nonconstant
factors, active variables, the active order) while cex_executor.lower drops a factor only when its evidence-restricted scope is EMPTY, so scoped constant tables remain physical sources --
a 28-variable / 1,516-entry constant-clique model (every row 1/2, Z = 2^27) forecast 12 rows / 64 MiB, was admitted, and lost the incumbent's 0.26 s EXACT completion to a 19.9 s DEADLINE
at 1,051 MiB; (2) the exact RREF, the matrix construction and the local-cost / order loops polled only after whole operations -- a 161-variable Boolean clique refused 2.09 s after a 0.2 s
allowance, a 221-variable one was still running at 6 s. Repair, forecast-only: the PHYSICAL volume certificate walks every retained evidence-restricted source scope (scoped constants and
one-state axes included) in the FULL native bucket order (one-state / factorless variables first, then the active order; each observed variable an empty bucket of mass card[v], one entry);
its volumes bound the kernel's dense forward rows and retained messages (they equal the reviewer's exact lowered-scope simulation on the 12-variable probe: 4,096 / 2,048 / 8,190 / 4,095;
on linkage 133,980,384 product entries vs 133,816,021 kernel forward rows and 66,863,593 output entries vs 66,819,670 live messages). The recognition-graph volumes remain as a diagnostic
(plan.volume_recognition). Recognition bounds: cooperative polls per pivot column and per 64 rows of the exact RREF, per 64 rows of the sign-system construction, per 16 candidate scans of
the local-cost and order loops, inside the component / core unions, equalities, chain walk, physical-graph construction and certificate, and a final guard before the plan is returned;
storage admission by cell count (MAX_EXACT_CELLS = 2^19) before the offset forms (Cn x Cn) and the sign system (|eq| x Cn) are allocated; a candidate whose cheapest available local step
exceeds LOCAL_PRODUCT_CUTOFF = 2^36 entries is abandoned at once (the Boolean cliques now refuse in 12 / 80 / 168 ms against 50 / 200 / 500 ms allowances). Unchanged: arithmetic, the
executor and kernel, query recovery, dispatch, the recognition predicates, the sign-search policy and -- verified -- the selected linkage order (the executor's semantic plan hash of model +
order equals the frozen round-20 certificate's). integrated.py changes only the VERSION string and records the diagnostic volumes.
Controls (check_round20b.py, 6, real work, receipt r20b_new_controls_1): A1 the physical certificate equals the reviewer's lowered-scope simulation; the 28-variable fixture is refused BEFORE
the executor (forecast 10.1 GiB / 53.7 s) and the incumbent publishes 56 / 56 EXACT with Z = 2^27 in 0.07 s; the 24-variable fixture at 1.8 s likewise (48 / 48 EXACT); A2 the Boolean
cliques (70 / 161 / 221 variables) refuse within the allowance; A3 a 1000 x 600 sign system refuses before allocation (14 KB traced), a real 725-chain model refuses by the dimension guard in
12 ms; A4 the reviewer's 80-model exact enumeration on this host (62 enclosed / 10 zero / 8 refused, 806 coordinates) + extreme scales 2^+-4000 + RANGE on a 2^-2000 internal range; A5 the
linkage order identical to round 20, the physical certificate covers the stored kernel counters, the forecast (764 MiB / 13.4 s) admits; A6 the diagnostic volumes equal round 20. The round-20
suite (6), round-19 (12), round-19b (6) and the oracle (6) pass; the ten frozen-path suites switch every constructor off and do not reach the changed module (not rerun; the engine files they
exercise are unchanged). The reviewer's 28-variable fixture under the normal contract on this build: operator off EXACT 56 / 56 in 0.13 s supervised; operator ON EXACT 56 / 56 in 0.13 s
supervised (typed RESOURCE_REFUSED before the executor, incumbent completes).
Measured on frozen v2.12.1 (pgm a646e84; records round20b/): ONE integrated linkage_13 confirmation (receipt sweep:round20b/linkage_confirmation): COMPLETE 2,158 / 2,158 DETERMINISTIC in
9.02 s / 585 MiB; rows and Z enclosure BYTE-IDENTICAL to the three frozen round-20 repeats (fingerprint 025f3dd4...), the executor's semantic plan hash and physical schedule hash equal the
round-20 certificate's, kernel forward rows identical (133,816,021); the physical forecast 764 MiB / 13.4 s admitted (round 20's recognition-graph forecast was 763 MiB / 13.4 s: the omitted
scoped constants add 0.1 % here and 2^22 x on the constant cliques). 19.2 s charged of the declared 120 s (7 receipts). The round-20 scored cells stand untouched. The bounded-admission
engineering pass is CLOSED; the next experiment is the separately frozen twelve-case transfer protocol.

### 23. Round 21 (23 Nov 2026): held-out transfer trial of the layered constructor (no code change; pgm 9da484c adds transfer_gen.py / run_transfer.py only)

Protocol (TRANSFER_PROTOCOL.md of the R20 packet + the R20 review's clarifications) FROZEN before any outcome (records round21/TRANSFER_PROTOCOL_FROZEN.md, TRANSFER_MANIFEST.json, commit
eac2ecdf7): same build (engine identical to a646e84), arms new = default / base = --no-layered-contraction (proven = v2.11.2 on three deterministic fixtures and by the round-20 comparator),
12 inputs: 4 natural UAI-2014 linkage instances by a seeded rule over the exposure census (linkage_20 / 23 / 24 / 26; exclusions recorded; headers only inspected), 4 generated eligible /
plausible pedigree-style models (G1 easy .. G4 near-budget) and 4 generated boundary cases from transfer_gen.py seed 20261123 (declared parameter sets), 600 s ceiling, gates >= 2 new
completions among the 8 eligible / plausible, no lost completion, no invalid publication. Result (24 cells, 227.9 s; 240.2 s charged incl. setup): NEW completions 2 of 8 -- linkage_20
(natural: 2,205 / 2,205 DETERMINISTIC in 12.9 s / 711 MiB, 19 interface bits, max product 1.26e7, kernel 11.6 s, forecast 1,199 MiB / 18.1 s admitted against 18.6 s remaining; base 586 / 2,205
DEADLINE_PARTIAL) and G3 (generated: 1,776 / 1,776 in 0.74 s / 82 MiB; base 1,598 / 1,776); NO lost completion (12 / 12); the constructor refused linkage_23 (15 free main-component sign bits
> the bounded search of 8), linkage_24, linkage_26 and G4 ('a chain sign is forced to zero by the core equalities' in both proposals) in 0.09-0.42 s, after which the new arm reproduced the base
arm's partial exactly; G1 / G2 complete in both arms (G2: 0.25 s vs 8.1 s); boundary: B1 (branching) and B4 (no channel) refused in <= 1 ms, B2 (interior residual) refused in 6 ms, all three
completed EXACT by the existing route in both arms; B3 (broken bulk symmetry) COMPLETED by the layered route in 0.19 s (proposal A admits a soft interior local factor) vs the base exact route
1.54 s / 327 MiB. Every published row in all 8 natural cells is consistent with the rounded UAI 2014 .MAR reference (0 outside); 0 disjoint pairs across arms on every task. Gate wording: the
preregistered 'per-variable points sum to 1' is STRICTER than the engine's established convention (interval midpoints whose per-variable interval sums contain 1): under the literal wording two
BASE cells (G3, B3: v2.11.2's PAC / exact midpoints) and 7 of the 9 accepted round-19b preservation cells are flagged, under the established semantics none; the new arm passes both readings.
Natural-distribution transfer: ONE new natural completion (linkage_20) of four; the gate's 'two' is met only when the generated G3 is counted, so the primary gate passes as 'one natural + one
synthetic'. Coverage limits made explicit by the refusals: the bounded affine alignment (<= 8 free sign bits; per-group translation; the 'forced zero sign' condition) misses three of four fresh
linkage pedigrees whose structure the constructor targets -- a concrete, measured gap for the next theory pass, not a numerical defect.

### 24. Round 22 (23 Nov 2026): normalized ancestral responses (`ancestral_response.py`, `integrated.py` v2.13)

Authorization: CLAUDE_IMPLEMENTATION_BRIEF.md of the R22 theory packet (zip sha256 76c7f889...; records round22/R22_PACKET/). Construction (THEOREMS.md): exact multiplexer / founder /
uniform-rooted selector-path roles on the ORIGINAL model by entrywise table identities; alleles of residual factors or evidence + their full ancestor closure retained; every other allele erased
with its founder mass as an exact scalar (implicit weight 1 per state when no unary; unary products exact; a unary on a multiplexer child is residual); on each recognised path the prefix
before the earliest needed node erased and replaced by a uniform prior at the boundary (a path with no needed node keeps its last node); the removed coordinates recovered by sparse affine
Walsh responses (g_child = (g_p0 + g_p1)/2 + chi_sel (g_p0 - g_p1)/2; retained alleles as indicators; erased-prefix characters transported by the XOR-of-edge-paths rule, rho_e = 2 theta_e - 1;
removed selectors (1 - rho E chi_b)/2) evaluated from Boolean query auxiliaries (parity Y = xor(A); mixed Y = 1[X_r = a and xor(A) = 1]) appended to the retained core and solved ONCE by the
UNCHANGED native executor through the layered route's adapter (deterministic weighted-min-product order on the full augmented physical graph, exact volume certificate incl. factors per bucket,
the layered forecast formula + decode state admitted against min(1,536 MiB, USABLE - RSS) and the remaining deadline BEFORE layered recognition is attempted; the signed route keeps precedence);
exact signed affine interval decode, [0, 1] intersection, outward 2^-52 compaction, points in the epsilon-safe J intervals when their product meets the simplex (else midpoints); Z = executor
enclosure x cancelled scalars (the appended erasure scalar included once). Bounded: a 1.0 s construction allowance polled inside the role scan, founder products, topological order, ancestry
closure, path walks, response merges, transport, query construction, order scoring and certificate; storage guards (2^20 predicate checks, 2^18 live terms, 2^18 query entries, 8,192-bit
integers, 128 MiB named containers) charged before growth; typed refusals (NotApplicable / RecognitionRefused / ResourceRefused / ZeroMass) fall back; a refusal at the global deadline returns
DEADLINE. --no-ancestral-response = the v2.12.1 comparator path; the fourteen existing suites switch it off. G4 (round-21 bytes, development run): the constructor reproduces the packet's
automatic signature exactly (72 retained / 530 + 334 erased / 196 founder masses / 168 auxiliaries; 240 native variables; 777,999 summed product entries, max 186,624, output 274,559; the
decoder, transport and query sets identical to auto_normalized_G4.json; scalar identical) in 0.08 s; end to end COMPLETE 2,448 / 2,448 DETERMINISTIC (136 EXACT), max width 7.8e-11, Z relative
width 2.2e-13, all 108 round-21 exact rows enclosed, every row overlapping the packet's research result, in 0.45 s / 57 MiB in process.
Controls (check_round22.py, 11, real work, receipt r22_new_controls_3; the first run (r22_new_controls_1) was TIMEOUT-KILLED at 304 s because three brute-force fixtures had 24 binary variables --
a harness defect, retained; the second crashed on a summary key): C1 the packet's 24 oracle models through the production route (444 coordinates + 24 Z contained, retained sets as asserted);
C2 implicit root multiplicity / duplicated founder unaries (scalar 18 vs 6 with an opaque root factor); C3 child likelihood and evidence retain their variables; C4 a duplicated multiplexer
refuses by type, a duplicated channel retains its path, the existing route completes both; C5 negative rho (theta 1/5) and multi-position terms, the T = 3 model overlapping the accepted arm on
every coordinate; C6 zero founder mass -> typed refusal -> ZERO_EVIDENCE by the existing route, a zero residual -> executor ZERO_EVIDENCE, 0 rows; C7 relabeling (ids, axes, order): same counts,
every pair overlapping; C8 query-entry / live-term / byte caps refuse on G4 before any allocation, an injected integrated cap refuses before the executor; C9 a 1 ms allowance refuses inside the
role scan in 1.2 ms, a clock expiring after the executor -> DEADLINE with 0 published and no fallback phases, an expired decode deadline refuses; C10 all 2,448 G4 coordinates once in order, an
evidence model excludes the observed variable; C11 the switch (in process, CLI) reproduces the v2.12.1 path and --no-layered-contraction leaves the ancestral route on. The packet's six exact
checks, its reference-runner check and its 24-model oracle pass on this host (the oracle needs an interpreter whose time.monotonic is CLOCK_UPTIME_RAW: Python 3.9 reports 'deadline expired at
entry' against the unchanged kernel; the venv's 3.12 passes -- a packet-portability note, not an engine defect). check_round20b (6), check_round20 (6), check_round19 (12), check_round19b (6),
the oracle (6), check_exact_route (13), check_round18 (12), check_round17 (4), check_round16 (6), check_round15 (3) pass on v2.13; the remaining five frozen-path suites were NOT rerun (budget).
Measured on frozen v2.13 (pgm 2509243; records round22/): PRIMARY PASSED -- G4 COMPLETE 2,448 / 2,448 DETERMINISTIC (136 EXACT) on three supervised repeats, byte-identical rows and Z
(fingerprint a35b96e7...), 0.56-0.75 s / 60-62 MiB, max width 7.8e-11, Z relative width 1.8e-13, all 108 round-21 exact rows enclosed, every row overlapping the packet's research result;
the same-build --no-ancestral-response comparator reproduces the accepted 108 / 2,448 partial (20.15 s, 1,426 MiB). PRESERVATION: G3 retained (1,776 / 1,776 via the ancestral route in 0.51 s,
0 disjoint vs round 21); **linkage_20 LOST** (586 / 2,205 DEADLINE_PARTIAL vs 2,205 / 2,205 in round 21): the ancestral constructor recognised the model (1,121 of 1,160 variables retained, 967
residual factors, no path cut) and was correctly REFUSED by its physical forecast (max product 2.0e14 entries), but the construction + certificate cost 0.544 s before that refusal, and the
layered route -- admitted in round 21 with a 0.5 s margin (forecast 18.1 s vs 18.6 s remaining) -- was then refused on time (18.1 s vs 17.9 s remaining); the engine fell back to the PAC route.
A dispatch-ordering / admission-margin regression, not a numerical defect; no code change after the freeze (the brief forbids lowering the time-admission constant or widening scope after
outcomes). The twelve-case exposed-panel preservation pass was NOT run: the first control-suite launch was timeout-killed at 304 s (oversized brute-force fixtures) and consumed the budget
(395.2 s of 400 charged). STOPPED FOR REVIEW with the lost completion and the unrun preservation pass as the open items.

### 24b. Round 22b (23 Nov 2026): closeout of the ancestral route (`integrated.py` v2.13.1, `ancestral_response.py`)

Authorization: the R22 review's CLAUDE_CLOSEOUT_BRIEF.md (zip sha256 0fc98a57...; records round22b/REVIEW_PACKET/). The review accepted the G4 construction and result (24 more oracle models,
504 coordinates) and withheld acceptance of v2.13 as the default for three items. (1) Incumbent precedence (the reviewer's patch, applied verbatim): the layered route recognises, admits and
executes BEFORE the ancestral constructor is attempted; the ancestral route runs only after a nonterminal layered refusal (structural, bounded recognition, forecast or executor), binds to
model_orig (the closure may have rewritten model), decodes to original coordinates with its own scalar once; a global deadline before or after its construction returns DEADLINE with no
rows and no fallback; LC.RecognitionRefused is handled at the route boundary; the signed route keeps first precedence; the flags stay independent. Round 22's linkage_20 loss was the ancestral
construction cost (0.544 s) consuming the layered route's 0.49 s admission margin -- with precedence restored the ancestral route performs no work before a terminal layered result.
(2) Bounded execution of the constructor: the restriction helper's typed refusal is translated to this module's RecognitionRefused; the selector-path witness is COMPACT (one edge list per
path, (path, position, cut) per removed node, edge parities by index ranges, the per-node transport rho reused for single-node runs) and charged with the role tables and the selector graph
BEFORE the walk (the 400-selector fixture under a 1,000 B cap now refuses at the first charge with a 3.8 KB traced peak, vs 1.54 MB before); sparse merges are admitted (live terms) and charged
(subset-length-aware term cost, temporaries + stored) before they are built; transported polynomials and the physical adjacency are charged before construction; transport products and
coefficients are bit-checked; polls inside component discovery, path traversal, prefix witness, sparse merges (per 1,024 terms), transport, query-table generation, physical graph fills, order
scoring (per 64 candidates / eliminations) and per-term decoding (a clock expiring 100 us after the path-walk entry is observed in the traversal after 0.25 ms; one expiring inside a merge is
observed there). Charged bytes cover the traced construction peak on the 400-path fixture (2.05x), a 374-term response tree (1.25x) and G4 (2.06x) -- an estimate of named allocations, not an
RSS proof. The G4 construction is UNCHANGED (decoder, transport, queries, scalar and the 777,999-entry certificate identical to round 22). (3) Harness: brute-force fixtures assert <= 2^16
assignments before enumeration; every control child runs under a 20 s supervisor cap; AR-targeted controls disable the layered route explicitly, dispatch controls use the default.
Controls: check_round22b.py (6, real work: D1 the reviewer's three probes as production regressions; D2 sparse-response stress + charge coverage; D3 default dispatch on G4 -- layered refuses
(forced-zero chain sign), ancestral applies, rows / Z byte-identical to round 22, plan hash equal; D4 a real nonidentity-closure model through the production kernel binds to the original
model (closure scalar 1/2 not reapplied; 8 / 8 rows; Z encloses 2); D5 a real layered success (G3) bypasses the ancestral constructor (DEFERRED, no construction phase); D6 the harness guard);
the reviewer's 17 dispatch control-flow checks and the original-binding control ported to the production module; check_round22 (11, AR-targeted; C6 adapted: under default dispatch the closure
establishes zero evidence first, the constructor's own ZeroMass refusal is tested directly); check_round11 (15), check_round12 (11), check_round13 (12) pass. check_integrated_v2 (~53 s) and
check_wmb (~40 s) exceed the 20 s per-child cap by construction and were NOT run (they switch every constructor off; the modules they exercise are byte-identical to the accepted build).
Control charges overran the 80 s reserve (see the round record): a 24 s timeout kill of check_integrated_v2 and three harness reruns.
Measured on frozen v2.13.1 (pgm 9d42679; records round22b/): ALL GATES PASSED. linkage_20 RESTORED: 2,205 / 2,205 DETERMINISTIC on two supervised confirmations (12.46 / 12.31 s, 714 MiB)
through the layered plan with the ancestral constructor DEFERRED (no construction phase), rows and Z identical to round 21, semantic plan and physical schedule hashes equal, admission margin
back to 0.5 s. G4 2,448 / 2,448 in 0.63 s byte-identical to the frozen round-22 result (the layered route refuses first in 0.09 s, the ancestral plan hash unchanged). G3 1,776 / 1,776 via the
layered route in 0.74 s, identical to its round-21 rows (0 disjoint vs the round-22 ancestral rows too). The twelve-case exposed panel: all twelve complete within contract, 0 disjoint vs the
accepted round-20 references, the eight deterministic / exact / signed cells byte-identical, linkage_13 identical via the layered route (AR DEFERRED), the four PAC cells under their established
semantics. 196.2 s charged of the 400 s ceiling (29 receipts; the 80 s control reserve was overrun to 113.1 s, disclosed). The bounded-execution engineering pass of the ancestral route is
CLOSED; v2.13.1 is proposed as the default engine; the exposed panel is thirteen of thirteen (twelve + G4) complete.

