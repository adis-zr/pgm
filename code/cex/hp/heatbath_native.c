// DGP8 SPECTRAL_HEATBATH, part 2b (DGP9 REPAIRED): the NATIVE exact-decision heat-bath fast path (brief section 3). Every transition: an exactly uniform site (random bits; rejection when n is not a power of two -- BOUNDED: after
// REJECT_CAP rejections inside one batch the kernel returns to the host with a poll request), the k conditional weights as binary64 products of the incident factor values (the host stores the nearest binary64 of the EXACT
// power-of-two NORMALIZED rationals -- every stored value <= 1 -- and admits the kernel only after proving that every weight, prefix product, cumulative sum and nonzero threshold product lies in the normal binary64 range; see
// heatbath_native.py), an OUTWARD relative error bound eps on every weight ((2 m + 4) u, m = number of incident factors + 1 for the unary, u = 2^-53, widened), outward cumulative intervals, a 53-bit uniform U = u53 / 2^53 with
// U in [u53, u53 + 1) / 2^53, the decision a = min{a : U S < C_a} taken ONLY when it is the same for every value inside the intervals (T_hi < Clo[a] and T_lo >= Chi[a - 1]); otherwise the step is left UNRESOLVED and control returns
// to the host, which refines the SAME bit stream exactly (heatbath_exact.decide_exact) and applies the result through hb_apply. Counters: one completed random-site update = one step (null moves count), committed together with the
// state change; occupation by last-change timestamps (hb_set_recording / hb_flush). RNG: xoshiro256** seeded by splitmix64 from the 64-bit seed. hb_bytes counts EVERY allocation of the context (DGP9: incl. inc_start).
// DGP10 (QUERY RESPONSE, brief sections 3-4; theory sections 3-6): an OPTIONAL CONDITIONAL-RESPONSE OBSERVER. At a committed update of a QUERIED site i the kernel encloses the EXACT conditional q_a = W_a / S of every state a
// from the SAME outward weight / sum bounds the decision used (W_a in [wl_a, wh_a], S in [Slo, Shi] -- proved normal by the host's range witness): two reciprocals per update rlo = RN(1/Shi)(1 - 2u) <= 1/Shi and
// rhi = RN(1/Slo)(1 + 4u) >= 1/Slo, then per state qlo_a = RN(RN(wl_a rlo)(1 - 2u)) <= q_a and qhi_a = RN(RN(wh_a rhi)(1 + 4u)) >= q_a (each rounding covered by the (1 -+ 2u / 4u) factors on normal values; the constants
// 1 - 2u, 1 + 4u are exact binary64), quantized OUTWARD to the grid 2^-32 with one extra unit on each side (L = max(0, floor(qlo 2^32) - 1), U = min(2^32, ceil(qhi 2^32) + 1); the scaling by 2^32 is exact) and ACCUMULATED in
// unsigned 128-bit sums per queried coordinate: first_lo += L, first_hi += U, second_hi += max((L - C)^2, (U - C)^2) with the FIXED dyadic center C = round(2^32 / k) (ties to the smaller integer; frozen by the host before
// sampling), differences widened to 128 bits BEFORE squaring. One committed visit contributes EXACTLY once: a resolved step observes inside hb_run after its commit; an UNRESOLVED step observes inside hb_apply (the host's exact
// fallback) from the UNCHANGED per-step workspace (hb_inspect refuses while a decision is pending); a null move observes; a rejected site index / an abandoned batch observes nothing. Burn-in observes nothing (hb_observer_start
// is called by the host together with hb_set_recording). Per queried site a visit counter and the predeclared LOCAL checkpoint plan M_1 < ... < M_J: when the counter reaches M_j the kernel copies the site's sums into its ONE
// immutable latest-snapshot buffer (count, j, sums) -- only completed snapshots are publishable; the current partial sums are diagnostics. With local counts < 2^63 the first sums stay below 2^95 and the squared sums below
// 2^127 (no overflow possible inside the contract; a counter reaching 2^62 invalidates the observer typed instead of wrapping). Memory O(Q + n): the host admits hb_observer_bytes before hb_observer_setup allocates.
#include <stdint.h>
#include <stdlib.h>
#include <string.h>
#include <math.h>

#define REJECT_CAP 65536

typedef struct { uint64_t s[4]; } rng_t;
static inline uint64_t rotl(uint64_t x, int k) { return (x << k) | (x >> (64 - k)); }
static uint64_t splitmix64(uint64_t *x) { uint64_t z = (*x += 0x9E3779B97F4A7C15ULL); z = (z ^ (z >> 30)) * 0xBF58476D1CE4E5B9ULL; z = (z ^ (z >> 27)) * 0x94D049BB133111EBULL; return z ^ (z >> 31); }
static void rng_seed(rng_t *r, uint64_t seed) { uint64_t x = seed; for (int i = 0; i < 4; i++) r->s[i] = splitmix64(&x); }
static inline uint64_t rng_next(rng_t *r) { const uint64_t result = rotl(r->s[1] * 5, 7) * 9; const uint64_t t = r->s[1] << 17; r->s[2] ^= r->s[0]; r->s[3] ^= r->s[1]; r->s[1] ^= r->s[2]; r->s[0] ^= r->s[3]; r->s[2] ^= t; r->s[3] = rotl(r->s[3], 45); return result; }

typedef struct {
    int n; int *cards; int *off;              // off[i] = offset of variable i in the flattened per-state arrays
    double *psi;                               // unary weights, flattened by off
    int nf; int *fi; int *fj; int *fki; int *fkj; long long *foff; double *fvals;   // pair factors: scopes, cardinalities, offsets into fvals (row-major over (i, j))
    int *inc_start; int *inc_f; int *inc_role; // incident lists per variable (CSR)
    int *state; long long t;                   // the current state and the committed step counter
    long long *occ; long long *start; int recording;   // occupation counts (flattened by off) and last-change timestamps
    rng_t rng; uint64_t bits; int nbits;       // the random bit buffer
    long long resolved, unresolved, null_moves, site_rejections;
    int kmax; double *w, *clo, *chi;           // per-step workspace
    int unresolved_site; uint64_t unresolved_u53;
    int poll_request; long long batch_rejections;   // DGP9: bounded site rejection -> poll request to the host
    // ---- DGP10 observer
    int observe, obs_configured, nq, J; int *qidx; int *qsite; int *qoff; uint32_t *center; long long *visits; int *next_cp; long long *plan;
    unsigned __int128 *first_lo, *first_hi, *second_hi;                  // per queried coordinate (qoff[qi] + a)
    long long *snap_count; int *snap_j; unsigned __int128 *snap_first_lo, *snap_first_hi, *snap_second_hi;   // the latest COMPLETED local checkpoint per queried site (snap_j = -1: none)
    long long obs_committed, obs_snapshots; int obs_valid, obs_invalid_code; int pending_k; double pending_eps; int pending_obs;
    size_t obs_bytes;
} hb_t;

static inline uint64_t get_bits(hb_t *h, int k) {
    if (k == 0) return 0;
    if (h->nbits < k) { h->bits = rng_next(&h->rng); h->nbits = 64; }
    uint64_t v = h->bits & ((k == 64) ? ~0ULL : ((1ULL << k) - 1)); h->bits >>= k; h->nbits -= k; return v;
}

hb_t *hb_create(int n, const int *cards, const double *psi, int nf, const int *fi, const int *fj, const double *fvals, const long long *foff, uint64_t seed) {
    hb_t *h = (hb_t *)calloc(1, sizeof(hb_t)); h->n = n; h->cards = (int *)malloc(sizeof(int) * n); memcpy(h->cards, cards, sizeof(int) * n);
    h->off = (int *)malloc(sizeof(int) * (n + 1)); h->off[0] = 0; for (int i = 0; i < n; i++) h->off[i + 1] = h->off[i] + cards[i];
    int D = h->off[n]; h->psi = (double *)malloc(sizeof(double) * D); memcpy(h->psi, psi, sizeof(double) * D);
    h->nf = nf; h->fi = (int *)malloc(sizeof(int) * nf); h->fj = (int *)malloc(sizeof(int) * nf); h->fki = (int *)malloc(sizeof(int) * nf); h->fkj = (int *)malloc(sizeof(int) * nf); h->foff = (long long *)malloc(sizeof(long long) * (nf + 1));
    memcpy(h->fi, fi, sizeof(int) * nf); memcpy(h->fj, fj, sizeof(int) * nf); memcpy(h->foff, foff, sizeof(long long) * (nf + 1));
    for (int f = 0; f < nf; f++) { h->fki[f] = cards[fi[f]]; h->fkj[f] = cards[fj[f]]; }
    h->fvals = (double *)malloc(sizeof(double) * foff[nf]); memcpy(h->fvals, fvals, sizeof(double) * foff[nf]);
    int *cnt = (int *)calloc(n, sizeof(int)); for (int f = 0; f < nf; f++) { cnt[fi[f]]++; cnt[fj[f]]++; }
    h->inc_start = (int *)malloc(sizeof(int) * (n + 1)); h->inc_start[0] = 0; for (int i = 0; i < n; i++) h->inc_start[i + 1] = h->inc_start[i] + cnt[i];
    h->inc_f = (int *)malloc(sizeof(int) * h->inc_start[n]); h->inc_role = (int *)malloc(sizeof(int) * h->inc_start[n]); int *fill = (int *)calloc(n, sizeof(int));
    for (int f = 0; f < nf; f++) { int a = fi[f], b = fj[f]; h->inc_f[h->inc_start[a] + fill[a]] = f; h->inc_role[h->inc_start[a] + fill[a]] = 0; fill[a]++; h->inc_f[h->inc_start[b] + fill[b]] = f; h->inc_role[h->inc_start[b] + fill[b]] = 1; fill[b]++; }
    free(cnt); free(fill);
    h->state = (int *)calloc(n, sizeof(int)); h->occ = (long long *)calloc(D, sizeof(long long)); h->start = (long long *)calloc(n, sizeof(long long)); h->recording = 0; h->t = 0;
    h->kmax = 0; for (int i = 0; i < n; i++) if (cards[i] > h->kmax) h->kmax = cards[i];
    h->w = (double *)malloc(sizeof(double) * h->kmax); h->clo = (double *)malloc(sizeof(double) * h->kmax); h->chi = (double *)malloc(sizeof(double) * h->kmax);
    rng_seed(&h->rng, seed); h->bits = 0; h->nbits = 0; h->unresolved_site = -1; h->poll_request = 0; h->batch_rejections = 0;
    h->observe = 0; h->obs_configured = 0; h->nq = 0; h->J = 0; h->qidx = NULL; h->qsite = NULL; h->qoff = NULL; h->center = NULL; h->visits = NULL; h->next_cp = NULL; h->plan = NULL; h->first_lo = h->first_hi = h->second_hi = NULL;
    h->snap_count = NULL; h->snap_j = NULL; h->snap_first_lo = h->snap_first_hi = h->snap_second_hi = NULL; h->obs_committed = 0; h->obs_snapshots = 0; h->obs_valid = 1; h->obs_invalid_code = 0; h->pending_k = 0; h->pending_eps = 0.0; h->pending_obs = 0; h->obs_bytes = 0;
    return h;
}

static void observer_free(hb_t *h) {
    free(h->qidx); free(h->qsite); free(h->qoff); free(h->center); free(h->visits); free(h->next_cp); free(h->plan); free(h->first_lo); free(h->first_hi); free(h->second_hi); free(h->snap_count); free(h->snap_j); free(h->snap_first_lo); free(h->snap_first_hi); free(h->snap_second_hi);
    h->qidx = NULL; h->qsite = NULL; h->qoff = NULL; h->center = NULL; h->visits = NULL; h->next_cp = NULL; h->plan = NULL; h->first_lo = h->first_hi = h->second_hi = NULL; h->snap_count = NULL; h->snap_j = NULL; h->snap_first_lo = h->snap_first_hi = h->snap_second_hi = NULL; h->obs_configured = 0; h->observe = 0; h->obs_bytes = 0;
}

void hb_free(hb_t *h) { if (!h) return; observer_free(h); free(h->cards); free(h->off); free(h->psi); free(h->fi); free(h->fj); free(h->fki); free(h->fkj); free(h->foff); free(h->fvals); free(h->inc_start); free(h->inc_f); free(h->inc_role); free(h->state); free(h->occ); free(h->start); free(h->w); free(h->clo); free(h->chi); free(h); }
void hb_set_state(hb_t *h, const int *x) { memcpy(h->state, x, sizeof(int) * h->n); }
void hb_get_state(hb_t *h, int *x) { memcpy(x, h->state, sizeof(int) * h->n); }
long long hb_steps(hb_t *h) { return h->t; }
void hb_counters(hb_t *h, long long *out) { out[0] = h->resolved; out[1] = h->unresolved; out[2] = h->null_moves; out[3] = h->site_rejections; }
void hb_set_recording(hb_t *h) { h->recording = 1; for (int i = 0; i < h->n; i++) h->start[i] = h->t; memset(h->occ, 0, sizeof(long long) * h->off[h->n]); }
void hb_flush(hb_t *h, long long *out) { for (int i = 0; i < h->n; i++) { h->occ[h->off[i] + h->state[i]] += h->t - h->start[i]; h->start[i] = h->t; } memcpy(out, h->occ, sizeof(long long) * h->off[h->n]); }
int hb_unresolved(hb_t *h, uint64_t *u53) { *u53 = h->unresolved_u53; return h->unresolved_site; }
int hb_take_poll_request(hb_t *h) { int r = h->poll_request; h->poll_request = 0; return r; }
// qualification hook (controls only; never called by the runner): replace the random bit buffer so the NEXT draws are the given bits (forces ambiguous prefixes -> the exact fallback path with a pending observation)
void hb_inject_bits(hb_t *h, uint64_t bits, int nbits) { h->bits = bits; h->nbits = nbits; }
// every allocation of the context: struct, cards (n), off (n + 1), fi / fj / fki / fkj (4 nf), inc_start (n + 1), inc_f / inc_role (2 x incidence), foff (nf + 1), psi (D), fvals, w / clo / chi (3 kmax), state (n ints), occ (D), start (n)
size_t hb_bytes(hb_t *h) { return sizeof(hb_t) + sizeof(int) * (size_t)(h->n + (h->n + 1) + h->nf * 4 + (h->n + 1) + h->inc_start[h->n] * 2 + h->n) + sizeof(long long) * (size_t)(h->nf + 1 + h->off[h->n] + h->n) + sizeof(double) * (size_t)(h->off[h->n] + h->foff[h->nf] + 3 * h->kmax) + h->obs_bytes; }

// ---- DGP10 observer: setup (the host admits hb_observer_bytes_for first), start / stop, state, snapshots
size_t hb_observer_bytes_for(int n, int nq, int Q, int J) { return sizeof(int) * (size_t)(n + nq + nq + 1 + nq + nq) + sizeof(uint32_t) * (size_t)nq + sizeof(long long) * (size_t)(nq + J + nq) + 16 * (size_t)(3 * Q + 3 * Q); }
int hb_observer_setup(hb_t *h, int nq, const int *qsites, const uint32_t *centers, int J, const long long *plan) {
    if (h->obs_configured || nq <= 0 || J <= 0 || J > 4096) return -1;
    for (int j = 1; j < J; j++) if (plan[j] <= plan[j - 1]) return -2;         // the plan must be strictly increasing
    if (plan[0] < 1) return -2;
    h->qidx = (int *)malloc(sizeof(int) * h->n); for (int i = 0; i < h->n; i++) h->qidx[i] = -1;
    h->qsite = (int *)malloc(sizeof(int) * nq); h->qoff = (int *)malloc(sizeof(int) * (nq + 1)); h->center = (uint32_t *)malloc(sizeof(uint32_t) * nq); h->visits = (long long *)calloc(nq, sizeof(long long)); h->next_cp = (int *)calloc(nq, sizeof(int)); h->plan = (long long *)malloc(sizeof(long long) * J);
    memcpy(h->plan, plan, sizeof(long long) * J); h->J = J; h->qoff[0] = 0;
    for (int q = 0; q < nq; q++) { int i = qsites[q]; if (i < 0 || i >= h->n || h->qidx[i] >= 0) { observer_free(h); return -3; } h->qidx[i] = q; h->qsite[q] = i; h->center[q] = centers[q]; h->qoff[q + 1] = h->qoff[q] + h->cards[i]; }
    int Q = h->qoff[nq]; h->nq = nq;
    h->first_lo = (unsigned __int128 *)calloc(Q, sizeof(unsigned __int128)); h->first_hi = (unsigned __int128 *)calloc(Q, sizeof(unsigned __int128)); h->second_hi = (unsigned __int128 *)calloc(Q, sizeof(unsigned __int128));
    h->snap_count = (long long *)calloc(nq, sizeof(long long)); h->snap_j = (int *)malloc(sizeof(int) * nq); for (int q = 0; q < nq; q++) h->snap_j[q] = -1;
    h->snap_first_lo = (unsigned __int128 *)calloc(Q, sizeof(unsigned __int128)); h->snap_first_hi = (unsigned __int128 *)calloc(Q, sizeof(unsigned __int128)); h->snap_second_hi = (unsigned __int128 *)calloc(Q, sizeof(unsigned __int128));
    h->obs_configured = 1; h->observe = 0; h->obs_valid = 1; h->obs_invalid_code = 0; h->obs_committed = 0; h->obs_snapshots = 0; h->obs_bytes = hb_observer_bytes_for(h->n, nq, Q, J); return Q;
}
void hb_observer_start(hb_t *h) { if (!h->obs_configured) return; int Q = h->qoff[h->nq]; for (int c = 0; c < Q; c++) { h->first_lo[c] = 0; h->first_hi[c] = 0; h->second_hi[c] = 0; h->snap_first_lo[c] = 0; h->snap_first_hi[c] = 0; h->snap_second_hi[c] = 0; } for (int q = 0; q < h->nq; q++) { h->visits[q] = 0; h->next_cp[q] = 0; h->snap_count[q] = 0; h->snap_j[q] = -1; } h->observe = 1; h->obs_valid = 1; h->obs_invalid_code = 0; h->obs_committed = 0; h->obs_snapshots = 0; }
void hb_observer_stop(hb_t *h) { h->observe = 0; }
// out[0] = configured, out[1] = observing, out[2] = valid, out[3] = invalid code, out[4] = committed observations, out[5] = completed snapshots, out[6] = nq, out[7] = Q
void hb_observer_state(hb_t *h, long long *out) { out[0] = h->obs_configured; out[1] = h->observe; out[2] = h->obs_valid; out[3] = h->obs_invalid_code; out[4] = h->obs_committed; out[5] = h->obs_snapshots; out[6] = h->nq; out[7] = (h->obs_configured ? h->qoff[h->nq] : 0); }
static inline void put128(unsigned __int128 v, uint64_t *dst) { dst[0] = (uint64_t)v; dst[1] = (uint64_t)(v >> 64); }
// the latest COMPLETED snapshot of queried site q: count / j (-1 = none) and k x (lo, hi) limbs of first_lo / first_hi / second_hi; returns k
int hb_observer_snapshot(hb_t *h, int q, long long *count, int *j, uint64_t *first_lo, uint64_t *first_hi, uint64_t *second_hi) {
    if (!h->obs_configured || q < 0 || q >= h->nq) return -1;
    int k = h->cards[h->qsite[q]]; *count = h->snap_count[q]; *j = h->snap_j[q];
    for (int a = 0; a < k; a++) { int c = h->qoff[q] + a; put128(h->snap_first_lo[c], first_lo + 2 * a); put128(h->snap_first_hi[c], first_hi + 2 * a); put128(h->snap_second_hi[c], second_hi + 2 * a); }
    return k;
}
// the CURRENT partial sums (diagnostic only; never publishable through the fixed-count theorem); returns k
int hb_observer_current(hb_t *h, int q, long long *count, uint64_t *first_lo, uint64_t *first_hi, uint64_t *second_hi) {
    if (!h->obs_configured || q < 0 || q >= h->nq) return -1;
    int k = h->cards[h->qsite[q]]; *count = h->visits[q];
    for (int a = 0; a < k; a++) { int c = h->qoff[q] + a; put128(h->first_lo[c], first_lo + 2 * a); put128(h->first_hi[c], first_hi + 2 * a); put128(h->second_hi[c], second_hi + 2 * a); }
    return k;
}

// the conditional-response observation of ONE committed visit of queried site i (k states; eps = the step's weight error bound): outward enclosures of every exact conditional from the step's workspace, Q32 quantization,
// uint128 accumulation, the local checkpoint snapshot
static inline void observe(hb_t *h, int i, int k, double eps) {
    const double u = ldexp(1.0, -53); const double S32 = 4294967296.0; int q = h->qidx[i]; uint32_t C = h->center[q];
    double Slo = h->clo[k - 1], Shi = h->chi[k - 1];
    double rlo = (1.0 / Shi) * (1.0 - 2.0 * u), rhi = (1.0 / Slo) * (1.0 + 4.0 * u);
    for (int a = 0; a < k; a++) {
        double wl = h->w[a] * (1.0 - eps), wh = h->w[a] * (1.0 + eps);
        double qlo = (wl * rlo) * (1.0 - 2.0 * u), qhi = (wh * rhi) * (1.0 + 4.0 * u);
        if (!(qlo >= 0.0) || !(qhi <= 2.0) || qlo != qlo || qhi != qhi) { h->obs_valid = 0; h->obs_invalid_code = 1; h->observe = 0; return; }       // outside the proved range: typed invalidation (never silent)
        double fl = floor(qlo * S32), fh = ceil(qhi * S32);
        uint64_t L = (fl <= 1.0) ? 0 : ((uint64_t)fl - 1); uint64_t U = (fh >= 4294967295.0) ? 4294967296ULL : ((uint64_t)fh + 1);
        unsigned __int128 dL = (L > C) ? (unsigned __int128)(L - C) : (unsigned __int128)(C - L); unsigned __int128 dU = (U > C) ? (unsigned __int128)(U - C) : (unsigned __int128)(C - U);
        unsigned __int128 sq = (dL > dU) ? dL * dL : dU * dU; int c = h->qoff[q] + a;
        h->first_lo[c] += L; h->first_hi[c] += U; h->second_hi[c] += sq;
    }
    h->visits[q] += 1; h->obs_committed += 1;
    if (h->visits[q] >= (1LL << 62)) { h->obs_valid = 0; h->obs_invalid_code = 2; h->observe = 0; return; }                                           // the counter bound (unreachable inside the contract; never wraps)
    if (h->next_cp[q] < h->J && h->visits[q] == h->plan[h->next_cp[q]]) {
        for (int a = 0; a < k; a++) { int c = h->qoff[q] + a; h->snap_first_lo[c] = h->first_lo[c]; h->snap_first_hi[c] = h->first_hi[c]; h->snap_second_hi[c] = h->second_hi[c]; }
        h->snap_count[q] = h->visits[q]; h->snap_j[q] = h->next_cp[q]; h->next_cp[q] += 1; h->obs_snapshots += 1;
    }
}

static inline void commit(hb_t *h, int i, int a) {
    int old = h->state[i]; h->t += 1;
    if (h->recording && a != old) { h->occ[h->off[i] + old] += (h->t - 1) - h->start[i]; h->start[i] = h->t - 1; }
    if (a == old) h->null_moves++;
    h->state[i] = a;
}

// the host applies an exactly decided fallback step (the decision came from heatbath_exact.decide_exact on the same u53 + refinement bits); DGP10: the pending observation of that visit is committed HERE from the unchanged workspace
void hb_apply(hb_t *h, int i, int a) {
    commit(h, i, a); h->unresolved_site = -1;
    if (h->pending_obs) { h->pending_obs = 0; if (h->observe && h->qidx != NULL && h->qidx[i] >= 0) observe(h, i, h->pending_k, h->pending_eps); }
}

// exactly uniform site; -1 when REJECT_CAP rejections accumulated in this batch (the host polls and calls hb_run again: the bit stream continues exactly where it stopped)
static inline int select_site(hb_t *h) {
    int n = h->n; int bits = 0; while ((1 << bits) < n) bits++;
    if ((n & (n - 1)) == 0) return (int)get_bits(h, bits);
    for (;;) { int r = (int)get_bits(h, bits); if (r < n) return r; h->site_rejections++; if (++h->batch_rejections >= REJECT_CAP) { h->batch_rejections = 0; h->poll_request = 1; return -1; } }
}

// returns the number of steps completed (== steps unless an UNRESOLVED decision stopped the batch early -- then hb_unresolved gives the site and u53 and the host must call hb_apply before the next hb_run -- or a poll request
// stopped it -- then hb_take_poll_request returns 1 and the host polls the clock)
long long hb_run(hb_t *h, long long steps) {
    const double u = ldexp(1.0, -53); h->batch_rejections = 0;
    for (long long s = 0; s < steps; s++) {
        if (h->unresolved_site >= 0 || h->poll_request) return s;
        int i = select_site(h); if (i < 0) return s;
        int k = h->cards[i]; int m = h->inc_start[i + 1] - h->inc_start[i];
        for (int a = 0; a < k; a++) h->w[a] = h->psi[h->off[i] + a];
        for (int e = h->inc_start[i]; e < h->inc_start[i + 1]; e++) {
            int f = h->inc_f[e]; const double *v = h->fvals + h->foff[f];
            if (h->inc_role[e] == 0) { int kj = h->fkj[f]; int xb = h->state[h->fj[f]]; for (int a = 0; a < k; a++) h->w[a] *= v[(long long)a * kj + xb]; }
            else { int kj = h->fkj[f]; int xa = h->state[h->fi[f]]; for (int b = 0; b < k; b++) h->w[b] *= v[(long long)xa * kj + b]; }
        }
        // outward relative error of every weight: (m + 1) conversions (<= u each) + m multiplications (<= u each) -> (2 m + 1) u; widened to eps = (2 m + 4) u (covers the widening roundings); valid because the host PROVED every
        // operand and result normal (power-of-two normalized tables; all-assignment range witness)
        double eps = (2.0 * m + 4.0) * u; double clo = 0.0, chi = 0.0;
        for (int a = 0; a < k; a++) { double wl = h->w[a] * (1.0 - eps), wh = h->w[a] * (1.0 + eps); clo += wl; chi += wh; h->clo[a] = clo * (1.0 - (a + 2) * u); h->chi[a] = chi * (1.0 + (a + 2) * u); }
        double Slo = h->clo[k - 1], Shi = h->chi[k - 1];
        uint64_t u53 = get_bits(h, 53); double Ulo = (double)u53 * u, Uhi = (double)(u53 + 1) * u;
        double Tlo = Ulo * Slo * (1.0 - 2.0 * u), Thi = Uhi * Shi * (1.0 + 2.0 * u);
        // exact rule a* = min{a : U S < C_a}; with intervals: cond1(a) = (a == k - 1) || Thi < Clo[a]  (for the last state U S < S holds exactly since U < 1), cond2(a) = (a == 0) || Tlo >= Chi[a - 1];
        // a = the smallest index with cond1; decided iff cond2(a) (then every value in the intervals gives the same a*)
        int a = 0; while (a < k - 1 && !(Thi < h->clo[a])) a++;
        int ok = (a == 0) || (Tlo >= h->chi[a - 1]);
        if (!ok) { h->unresolved_site = i; h->unresolved_u53 = u53; h->unresolved++; h->pending_k = k; h->pending_eps = eps; h->pending_obs = 1; return s; }
        h->resolved++; commit(h, i, a);
        if (h->observe && h->qidx[i] >= 0) observe(h, i, k, eps);
    }
    return steps;
}

// ---- exactness qualification support: the host can ask for the weights / intervals of a given site at the current state (no RNG consumption); DGP10: REFUSED (-1) while an unresolved decision keeps the workspace pending
int hb_inspect(hb_t *h, int i, double *w_out, double *clo_out, double *chi_out) {
    if (h->unresolved_site >= 0) return -1;
    const double u = ldexp(1.0, -53); int k = h->cards[i]; int m = h->inc_start[i + 1] - h->inc_start[i];
    for (int a = 0; a < k; a++) h->w[a] = h->psi[h->off[i] + a];
    for (int e = h->inc_start[i]; e < h->inc_start[i + 1]; e++) {
        int f = h->inc_f[e]; const double *v = h->fvals + h->foff[f];
        if (h->inc_role[e] == 0) { int kj = h->fkj[f]; int xb = h->state[h->fj[f]]; for (int a = 0; a < k; a++) h->w[a] *= v[(long long)a * kj + xb]; }
        else { int kj = h->fkj[f]; int xa = h->state[h->fi[f]]; for (int b = 0; b < k; b++) h->w[b] *= v[(long long)xa * kj + b]; }
    }
    double eps = (2.0 * m + 4.0) * u; double clo = 0.0, chi = 0.0;
    for (int a = 0; a < k; a++) { double wl = h->w[a] * (1.0 - eps), wh = h->w[a] * (1.0 + eps); clo += wl; chi += wh; w_out[a] = h->w[a]; clo_out[a] = clo * (1.0 - (a + 2) * u); chi_out[a] = chi * (1.0 + (a + 2) * u); }
    return k;
}

// the observation enclosure of site i at the CURRENT state (qualification: the differential control against exact conditionals; no RNG consumption, no accumulation); refused while pending; -> L[a], U[a] as the kernel would record
int hb_observe_inspect(hb_t *h, int i, uint64_t *L_out, uint64_t *U_out) {
    if (h->unresolved_site >= 0) return -1;
    const double u = ldexp(1.0, -53); const double S32 = 4294967296.0; int k = h->cards[i]; int m = h->inc_start[i + 1] - h->inc_start[i];
    for (int a = 0; a < k; a++) h->w[a] = h->psi[h->off[i] + a];
    for (int e = h->inc_start[i]; e < h->inc_start[i + 1]; e++) {
        int f = h->inc_f[e]; const double *v = h->fvals + h->foff[f];
        if (h->inc_role[e] == 0) { int kj = h->fkj[f]; int xb = h->state[h->fj[f]]; for (int a = 0; a < k; a++) h->w[a] *= v[(long long)a * kj + xb]; }
        else { int kj = h->fkj[f]; int xa = h->state[h->fi[f]]; for (int b = 0; b < k; b++) h->w[b] *= v[(long long)xa * kj + b]; }
    }
    double eps = (2.0 * m + 4.0) * u; double clo = 0.0, chi = 0.0;
    for (int a = 0; a < k; a++) { double wl = h->w[a] * (1.0 - eps), wh = h->w[a] * (1.0 + eps); clo += wl; chi += wh; h->clo[a] = clo * (1.0 - (a + 2) * u); h->chi[a] = chi * (1.0 + (a + 2) * u); }
    double Slo = h->clo[k - 1], Shi = h->chi[k - 1]; double rlo = (1.0 / Shi) * (1.0 - 2.0 * u), rhi = (1.0 / Slo) * (1.0 + 4.0 * u);
    for (int a = 0; a < k; a++) {
        double wl = h->w[a] * (1.0 - eps), wh = h->w[a] * (1.0 + eps); double qlo = (wl * rlo) * (1.0 - 2.0 * u), qhi = (wh * rhi) * (1.0 + 4.0 * u);
        double fl = floor(qlo * S32), fh = ceil(qhi * S32); L_out[a] = (fl <= 1.0) ? 0 : ((uint64_t)fl - 1); U_out[a] = (fh >= 4294967295.0) ? 4294967296ULL : ((uint64_t)fh + 1);
    }
    return k;
}
