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
mastermind_03_08_04-0015 (cap 2^22 by the ladder, 121 splits) drew only zero-weight samples (9,216 of 9,216): the proposal's support misses the model's: proposal overlap, not
memory. or_chain_53 (cap 2^24, 47 splits) has 97.5 % zero weights and ESS 4.6 of 167,936 draws: proposal concentration, as or_chain_132.

