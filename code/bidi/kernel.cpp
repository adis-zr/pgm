// BIDI_NATIVE_CERT kernel: complete conditioned sum-product stream for a binary bipartite pairwise model (9 Nov 2026 pilot).
//
// Model: W(x,y) = kappa * prod_i phi_i(x_i) * prod_j rho_j(y_j) * prod_{i,j} psi_ij(x_i, y_j), x in {0,1}^m, y in {0,1}^n.
// For every y (enumerated exactly once): A_i(a;y) = phi_i(a) prod_j psi_ij(a,y_j); H_i = A_i(0)+A_i(1); B = kappa prod_j rho_j(y_j);
//   T = B prod_i H_i;  Z += T;  NY[j][y_j] += T;  NX[i][a] += (B * C_minus_i) * A_i(a)  with C_minus_i = prod_{l!=i} H_l by prefix/suffix.
// Representation: one CURRENT-LEAF product tree per (i,a) and one for B; a Gray-code step flips one y bit and overwrites the affected
// leaf and its ancestors from their current children (no ratio updates, no division anywhere). The y space is split into 2^k lanes by
// the TOP k bits (fixed per lane); every lane runs the same Gray sequence over the LOW n-k bits in lockstep, so the inner loops run
// over contiguous lane arrays (SIMD across lanes). No 2^n-entry table, no term list, no reverse tape: storage is O((2m+1)*2P*lanes).
// Arithmetic: binary64, round-to-nearest-even, +,* only (no FMA: compiled with -ffp-contract=off -ffp-model=strict). Every operation
// is a binary + or * so the error-depth labels of the certificate (E_sum = max+1, E_prod = sum+1) apply literally.
// Counters count operations analytically per step (no per-operation instrumentation in the hot loop).
#include <cstdint>
#include <cstdlib>
#include <cstring>
#include <cmath>
#include <cfenv>
#include <cfloat>
#include <new>

extern "C" {

static const char* SCHEDULE_ID = "BIDI_NATIVE_CERT/gray-lanes-currentleaf-tree-prefixsuffix/v1";   // arithmetic schedule UNCHANGED by the 9 Nov review repair (scratch allocation + diagnostic counters only)
static const char* KERNEL_REVISION = "r2-2026-11-09-review-repair";
const char* bidi_kernel_revision() { return KERNEL_REVISION; }

const char* bidi_schedule_id() { return SCHEDULE_ID; }

// Floating-point environment / build checks. Returns 0 if all pass; otherwise a bitmask of failed checks.
//  1: sizeof(double) != 8      2: FLT_RADIX != 2        4: DBL_MANT_DIG != 53     8: rounding mode != FE_TONEAREST
// 16: FLT_EVAL_METHOD != 0    32: ties-to-even identity failed (1 + 2^-53 must round to 1; 1 + 2^-53 + 2^-105 must round up)
// 64: contraction detected (a*b+c differs from separately rounded product then sum)   128: subnormals flushed (denormal arithmetic altered)
uint32_t bidi_fp_env_check() {
    uint32_t bad = 0;
    if (sizeof(double) != 8) bad |= 1;
    if (FLT_RADIX != 2) bad |= 2;
    if (DBL_MANT_DIG != 53) bad |= 4;
    if (fegetround() != FE_TONEAREST) bad |= 8;
#if defined(FLT_EVAL_METHOD)
    if (FLT_EVAL_METHOD != 0) bad |= 16;
#endif
    volatile double one = 1.0, tiny = 0x1p-53, tinier = 0x1p-105;
    volatile double r1 = one + tiny;                 // exact tie -> even -> 1.0
    volatile double r2 = (one + tinier) + tiny;      // 1 + 2^-105 is 1.0 (rounds to 1), so this is again a tie; use a different witness:
    volatile double r3 = one + (tiny + tinier);      // tiny+tinier is exact (2^-53 + 2^-105), above the tie -> rounds up to 1 + 2^-52
    if (r1 != 1.0) bad |= 32;
    if (r3 != 1.0 + 0x1p-52) bad |= 32;
    (void)r2;
    // contraction witness: a*b+c with values where fma and separate rounding differ
    volatile double a = 1.0 + 0x1p-27, b = 1.0 - 0x1p-27, c = -1.0;
    volatile double p = a * b;                        // rounded product
    volatile double s_sep = p + c;                    // separately rounded
    volatile double s_fused = a * b + c;              // would be fma(a,b,c) under contraction
    if (s_sep != s_fused) bad |= 64;
    volatile double sub = 0x1p-1060, two = 2.0;       // subnormal arithmetic must be exact here
    volatile double sub2 = sub * two;
    if (sub2 != 0x1p-1059) bad |= 128;
    return bad;
}

struct State {
    uint32_t m, n, k, lanes, P, nodes, logP;          // P = leaves per tree (power of two >= n+1), nodes = 2P (index 0 unused)
    uint32_t nlow;                                    // n - k low bits enumerated by Gray code
    uint64_t steps_total, step;                       // steps_total = 2^nlow configurations per lane; step = configurations done per lane
    uint64_t ylow;                                    // current low-bit assignment (common to all lanes)
    // source tables (host order): phi[i*2+a], rho[j*2+b], psi[((i*n)+j)*4 + a*2 + b], kappa
    double* phi; double* rho; double* psi; double kappa;
    // trees: tree index q in [0, 2m) is (i,a) = (q>>1, q&1); q = 2m is the B tree. node value at tree[(q*nodes + t)*lanes + lane]
    double* tree;
    // per-lane accumulators
    double* ZL;        // [lanes]
    double* NYlow;     // [nlow*2*lanes]  index ((j*2)+b)*lanes + lane
    double* NX;        // [m*2*lanes]     index ((i*2)+a)*lanes + lane
    // scratch per lane: T is lanes-wide regardless of m (review F2: BC was aliased as T and had only max(1, m*lanes) entries -> heap overflow for m = 0, lanes > 1)
    double* H; double* pre; double* suf; double* BC; double* A0; double* A1; double* T;   // H/BC/A0/A1: max(1,m)*lanes; pre/suf: (m+1)*lanes; T: lanes
    // counters (analytic)
    uint64_t configs_visited, mults, adds, leaf_updates;
};

static double* alloc_d(size_t n) { double* p = (double*)std::malloc(sizeof(double) * (n ? n : 1)); if (p) std::memset(p, 0, sizeof(double) * (n ? n : 1)); return p; }

static void free_state(State* S) {
    if (!S) return;
    std::free(S->phi); std::free(S->rho); std::free(S->psi); std::free(S->tree); std::free(S->ZL); std::free(S->NYlow); std::free(S->NX);
    std::free(S->H); std::free(S->pre); std::free(S->suf); std::free(S->BC); std::free(S->A0); std::free(S->A1); std::free(S->T); std::free(S);
}

static inline uint32_t next_pow2(uint32_t x) { uint32_t p = 1; while (p < x) p <<= 1; return p; }

static inline void set_leaf(State* S, uint32_t q, uint32_t leaf, const double* vals_per_lane /* lanes values */) {
    double* base = S->tree + ((size_t)q * S->nodes + (S->P + leaf)) * S->lanes;
    for (uint32_t l = 0; l < S->lanes; ++l) base[l] = vals_per_lane[l];
}

// recompute ancestors of leaf `leaf` in tree q from CURRENT children
static inline void update_ancestors(State* S, uint32_t q, uint32_t leaf) {
    const uint32_t L = S->lanes; double* T = S->tree + (size_t)q * S->nodes * L;
    uint32_t t = (S->P + leaf) >> 1;
    while (t >= 1) {
        double* out = T + (size_t)t * L; const double* c0 = T + (size_t)(2 * t) * L; const double* c1 = T + (size_t)(2 * t + 1) * L;
        for (uint32_t l = 0; l < L; ++l) out[l] = c0[l] * c1[l];
        if (t == 1) break; t >>= 1;
    }
}

// Build all trees for the current y (initial configuration of every lane): full recompute of every internal node.
static bool build_trees(State* S) {
    const uint32_t L = S->lanes, P = S->P, nodes = S->nodes, m = S->m, n = S->n;
    double* tmp = (double*)std::malloc(sizeof(double) * L);
    if (!tmp) return false;
    for (uint32_t q = 0; q <= 2 * m; ++q) {
        // leaf 0
        for (uint32_t l = 0; l < L; ++l) tmp[l] = (q < 2 * m) ? S->phi[(q >> 1) * 2 + (q & 1)] : S->kappa;
        set_leaf(S, q, 0, tmp);
        for (uint32_t j = 0; j < n; ++j) {
            for (uint32_t l = 0; l < L; ++l) {
                uint32_t yj = (j < S->nlow) ? (uint32_t)((S->ylow >> j) & 1u) : (uint32_t)((l >> (j - S->nlow)) & 1u);
                tmp[l] = (q < 2 * m) ? S->psi[(((size_t)(q >> 1) * n) + j) * 4 + (q & 1) * 2 + yj] : S->rho[j * 2 + yj];
            }
            set_leaf(S, q, 1 + j, tmp);
        }
        for (uint32_t j = n + 1; j < P; ++j) { for (uint32_t l = 0; l < L; ++l) tmp[l] = 1.0; set_leaf(S, q, j, tmp); }   // exact padding
        double* T = S->tree + (size_t)q * nodes * L;
        for (uint32_t t = P - 1; t >= 1; --t) {
            double* out = T + (size_t)t * L; const double* c0 = T + (size_t)(2 * t) * L; const double* c1 = T + (size_t)(2 * t + 1) * L;
            for (uint32_t l = 0; l < L; ++l) out[l] = c0[l] * c1[l];
            if (t == 1) break;
        }
    }
    std::free(tmp);
    S->mults += (uint64_t)(2 * m + 1) * (P - 1) * L;                 // initialization products are counted too
    return true;
}

// m, n <= 60; k <= n; returns NULL on invalid sizes or allocation failure.
State* bidi_create(uint32_t m, uint32_t n, uint32_t k, const double* phi, const double* rho, const double* psi, double kappa) {
    if (m > 60 || n > 60 || k > n || k > 12) return nullptr;
    State* S = (State*)std::calloc(1, sizeof(State)); if (!S) return nullptr;
    S->m = m; S->n = n; S->k = k; S->lanes = 1u << k; S->nlow = n - k; S->P = next_pow2(n + 1); S->nodes = 2 * S->P;
    S->logP = 0; while ((1u << S->logP) < S->P) ++S->logP;
    S->steps_total = (uint64_t)1 << S->nlow; S->step = 0; S->ylow = 0; S->kappa = kappa;
    size_t L = S->lanes;
    S->phi = alloc_d((size_t)m * 2); S->rho = alloc_d((size_t)n * 2); S->psi = alloc_d((size_t)m * n * 4);
    S->tree = alloc_d((size_t)(2 * m + 1) * S->nodes * L);
    S->ZL = alloc_d(L); S->NYlow = alloc_d((size_t)S->nlow * 2 * L); S->NX = alloc_d((size_t)m * 2 * L);
    const size_t m1 = m ? m : 1;                                      // every per-row scratch has at least one row; T is lanes-wide independently of m
    S->H = alloc_d(m1 * L); S->pre = alloc_d((size_t)(m + 1) * L); S->suf = alloc_d((size_t)(m + 1) * L); S->BC = alloc_d(m1 * L); S->A0 = alloc_d(m1 * L); S->A1 = alloc_d(m1 * L); S->T = alloc_d(L);
    if (!S->phi || !S->rho || !S->psi || !S->tree || !S->ZL || !S->NYlow || !S->NX || !S->H || !S->pre || !S->suf || !S->BC || !S->A0 || !S->A1 || !S->T) { free_state(S); return nullptr; }
    if (m) std::memcpy(S->phi, phi, sizeof(double) * m * 2);
    if (n) std::memcpy(S->rho, rho, sizeof(double) * n * 2);
    if (m && n) std::memcpy(S->psi, psi, sizeof(double) * m * n * 4);
    if (!build_trees(S)) { free_state(S); return nullptr; }
    return S;
}

void bidi_destroy(State* S) { free_state(S); }

// process the CURRENT configuration of every lane: accumulate Z, NY (low bits), NX
static inline void accumulate_current(State* S) {
    const uint32_t L = S->lanes, m = S->m, nodes = S->nodes;
    const double* troot = S->tree + (size_t)1 * L;                       // root of tree q at tree[(q*nodes + 1)*L + lane]
    // A values and H
    for (uint32_t i = 0; i < m; ++i) {
        const double* r0 = S->tree + ((size_t)(2 * i) * nodes + 1) * L; const double* r1 = S->tree + ((size_t)(2 * i + 1) * nodes + 1) * L;
        double* a0 = S->A0 + (size_t)i * L; double* a1 = S->A1 + (size_t)i * L; double* h = S->H + (size_t)i * L;
        for (uint32_t l = 0; l < L; ++l) { a0[l] = r0[l]; a1[l] = r1[l]; h[l] = r0[l] + r1[l]; }
    }
    // prefix / suffix products of H (pre[0] = suf[m] = 1 exactly)
    for (uint32_t l = 0; l < L; ++l) { S->pre[l] = 1.0; S->suf[(size_t)m * L + l] = 1.0; }
    for (uint32_t i = 0; i < m; ++i) {
        const double* p = S->pre + (size_t)i * L; double* pn = S->pre + (size_t)(i + 1) * L; const double* h = S->H + (size_t)i * L;
        for (uint32_t l = 0; l < L; ++l) pn[l] = p[l] * h[l];
    }
    for (uint32_t i = m; i >= 1; --i) {
        const double* s = S->suf + (size_t)i * L; double* sn = S->suf + (size_t)(i - 1) * L; const double* h = S->H + (size_t)(i - 1) * L;
        for (uint32_t l = 0; l < L; ++l) sn[l] = h[l] * s[l];
    }
    // T = B * pre[m]; Z, NY
    const double* B = S->tree + ((size_t)(2 * m) * nodes + 1) * L; const double* pm = S->pre + (size_t)m * L;
    double* T = S->T;                                                    // dedicated lanes-wide scratch (review F2)
    for (uint32_t l = 0; l < L; ++l) { T[l] = B[l] * pm[l]; S->ZL[l] = S->ZL[l] + T[l]; }
    for (uint32_t j = 0; j < S->nlow; ++j) {
        uint32_t yj = (uint32_t)((S->ylow >> j) & 1u); double* acc = S->NYlow + ((size_t)j * 2 + yj) * L;
        for (uint32_t l = 0; l < L; ++l) acc[l] = acc[l] + T[l];
    }
    // NX[i][a] += (B * C_minus_i) * A_i(a),  C_minus_i = pre[i] * suf[i+1]
    for (uint32_t i = 0; i < m; ++i) {
        const double* p = S->pre + (size_t)i * L; const double* s = S->suf + (size_t)(i + 1) * L; const double* a0 = S->A0 + (size_t)i * L; const double* a1 = S->A1 + (size_t)i * L;
        double* n0 = S->NX + ((size_t)i * 2 + 0) * L; double* n1 = S->NX + ((size_t)i * 2 + 1) * L;
        for (uint32_t l = 0; l < L; ++l) { double c = p[l] * s[l]; double bc = B[l] * c; n0[l] = n0[l] + bc * a0[l]; n1[l] = n1[l] + bc * a1[l]; }
    }
    (void)troot;
    S->configs_visited += L;
    // analytic operation count for this configuration block (per lane): H adds m; pre m mults; suf m mults; T 1 mult; Z 1 add; NY nlow adds;
    // NX per i: c (1 mult), bc (1 mult), 2 mults, 2 adds  => 6m+1 mults, 3m+1+nlow adds  (review K2: the frozen kernel counted 7m+1 mults)
    S->mults += (uint64_t)L * (6ull * m + 1ull); S->adds += (uint64_t)L * (3ull * m + 1ull + S->nlow);
}

// Gray step: flip low bit j (j = ctz(step)) in every tree (leaf 1+j), recompute ancestors.
static inline void gray_flip(State* S, uint32_t j) {
    const uint32_t L = S->lanes, m = S->m, n = S->n; S->ylow ^= ((uint64_t)1 << j); const uint32_t yj = (uint32_t)((S->ylow >> j) & 1u);
    for (uint32_t q = 0; q <= 2 * m; ++q) {
        double v = (q < 2 * m) ? S->psi[(((size_t)(q >> 1) * n) + j) * 4 + (q & 1) * 2 + yj] : S->rho[j * 2 + yj];
        double* leaf = S->tree + ((size_t)q * S->nodes + (S->P + 1 + j)) * L;
        for (uint32_t l = 0; l < L; ++l) leaf[l] = v;
        update_ancestors(S, q, 1 + j);
    }
    S->leaf_updates += (uint64_t)(2 * m + 1) * L; S->mults += (uint64_t)(2 * m + 1) * S->logP * L;
}

// Advance up to max_steps configurations per lane. Returns the number of configurations (per lane) processed in this call; 0 when done.
uint64_t bidi_step(State* S, uint64_t max_steps) {
    if (!S) return 0; uint64_t done = 0;
    while (done < max_steps && S->step < S->steps_total) {
        if (S->step > 0) {
            uint32_t j = (uint32_t)__builtin_ctzll(S->step);          // Gray code: configuration t differs from t-1 in bit ctz(t)
            gray_flip(S, j);
        }
        accumulate_current(S);
        ++S->step; ++done;
    }
    return done;
}

int bidi_done(State* S) { return S && S->step >= S->steps_total; }

// Final SEQUENTIAL lane reduction (lane 0 first). Z: sum of lane Z; NY[j][b]: low j from NYlow sums; top j from the lanes whose fixed
// bit (j - nlow) equals b, summing the SAME lane Z accumulators (bitwise identical to what per-lane NY accumulation would have produced).
// Returns 1 if every configuration was visited exactly once (step == 2^nlow and configs_visited == 2^n), else 0.
int bidi_finish(State* S, double* Z, double* NX, double* NY, uint64_t* counters /* [5]: configs, mults, adds, leaf_updates, lanes */) {
    if (!S) return 0; const uint32_t L = S->lanes, m = S->m, n = S->n;
    double z = 0.0; for (uint32_t l = 0; l < L; ++l) z = z + S->ZL[l]; *Z = z;
    for (uint32_t i = 0; i < m; ++i) for (uint32_t a = 0; a < 2; ++a) { double acc = 0.0; const double* p = S->NX + ((size_t)i * 2 + a) * L; for (uint32_t l = 0; l < L; ++l) acc = acc + p[l]; NX[i * 2 + a] = acc; }
    for (uint32_t j = 0; j < n; ++j) for (uint32_t b = 0; b < 2; ++b) {
        double acc = 0.0;
        if (j < S->nlow) { const double* p = S->NYlow + ((size_t)j * 2 + b) * L; for (uint32_t l = 0; l < L; ++l) acc = acc + p[l]; }
        else { for (uint32_t l = 0; l < L; ++l) if (((l >> (j - S->nlow)) & 1u) == b) acc = acc + S->ZL[l]; }
        NY[j * 2 + b] = acc;
    }
    // exact reduction count: Z: L adds; NX: 2m rows x L; low-bit NY: 2(n-k) rows x L; top-bit NY: each of the k bits visits L/2 lanes per state = L adds per bit
    uint64_t red_adds = L + (uint64_t)m * 2 * L + (uint64_t)S->nlow * 2 * L + (uint64_t)S->k * L;   // (review K2: the frozen kernel counted 2L per top bit)
    counters[0] = S->configs_visited; counters[1] = S->mults; counters[2] = S->adds + red_adds; counters[3] = S->leaf_updates; counters[4] = L;
    return (S->step == S->steps_total && S->configs_visited == (S->steps_total << S->k)) ? 1 : 0;
}

uint64_t bidi_configs_visited(State* S) { return S ? S->configs_visited : 0; }
// FORMULA ESTIMATE of the kernel's double storage (not malloc accounting, not RSS): trees + accumulators + scratch + source tables
uint64_t bidi_bytes_allocated(State* S) {
    if (!S) return 0; size_t L = S->lanes, m = S->m, n = S->n, m1 = m ? m : 1;
    return sizeof(double) * ((size_t)(2 * m + 1) * S->nodes * L + L + (size_t)S->nlow * 2 * L + (size_t)m * 2 * L + 4 * m1 * L + 2 * (size_t)(m + 1) * L + L + (m ? m * 2 : 1) + (n ? n * 2 : 1) + ((m && n) ? (size_t)m * n * 4 : 1));
}

// Debug aid for qualification only: the current low-bit assignment (so a test can record the visited configurations)
uint64_t bidi_current_ylow(State* S) { return S ? S->ylow : 0; }
uint32_t bidi_tree_leaves(State* S) { return S ? S->P : 0; }

} // extern "C"
