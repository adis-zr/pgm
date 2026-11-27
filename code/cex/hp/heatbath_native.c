// DGP8 SPECTRAL_HEATBATH, part 2b: the NATIVE exact-decision heat-bath fast path (brief section 3). Every transition: an exactly uniform site (random bits; rejection when n is not a power of two), the k conditional weights as
// binary64 products of the incident factor values (the stored doubles are the nearest binary64 of the exact rationals; the host passes the per-table relative conversion bound), an OUTWARD relative error bound eps on every weight
// ((2 m + 4) u, m = number of incident factors + 1 for the unary, u = 2^-53, widened), outward cumulative intervals, a 53-bit uniform U = u53 / 2^53 with U in [u53, u53 + 1) / 2^53, the decision a = min{a : U S < C_a} taken ONLY when
// it is the same for every value inside the intervals (T_hi < Clo[a] and T_lo >= Chi[a - 1]); otherwise the step is left UNRESOLVED and control returns to the host, which refines the SAME bit stream exactly (heatbath_exact.decide_exact)
// and applies the result through hb_apply. Counters: one completed random-site update = one step (null moves count), committed together with the state change; occupation by last-change timestamps (hb_set_recording / hb_flush).
// RNG: xoshiro256** seeded by splitmix64 from the 64-bit seed (documented; the host records the seed). No floating softmax; no D40 rounding; no dependence on a target probability.
#include <stdint.h>
#include <stdlib.h>
#include <string.h>
#include <math.h>

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
    rng_seed(&h->rng, seed); h->bits = 0; h->nbits = 0; h->unresolved_site = -1;
    return h;
}

void hb_free(hb_t *h) { if (!h) return; free(h->cards); free(h->off); free(h->psi); free(h->fi); free(h->fj); free(h->fki); free(h->fkj); free(h->foff); free(h->fvals); free(h->inc_start); free(h->inc_f); free(h->inc_role); free(h->state); free(h->occ); free(h->start); free(h->w); free(h->clo); free(h->chi); free(h); }
void hb_set_state(hb_t *h, const int *x) { memcpy(h->state, x, sizeof(int) * h->n); }
void hb_get_state(hb_t *h, int *x) { memcpy(x, h->state, sizeof(int) * h->n); }
long long hb_steps(hb_t *h) { return h->t; }
void hb_counters(hb_t *h, long long *out) { out[0] = h->resolved; out[1] = h->unresolved; out[2] = h->null_moves; out[3] = h->site_rejections; }
void hb_set_recording(hb_t *h) { h->recording = 1; for (int i = 0; i < h->n; i++) h->start[i] = h->t; memset(h->occ, 0, sizeof(long long) * h->off[h->n]); }
void hb_flush(hb_t *h, long long *out) { for (int i = 0; i < h->n; i++) { h->occ[h->off[i] + h->state[i]] += h->t - h->start[i]; h->start[i] = h->t; } memcpy(out, h->occ, sizeof(long long) * h->off[h->n]); }
int hb_unresolved(hb_t *h, uint64_t *u53) { *u53 = h->unresolved_u53; return h->unresolved_site; }
size_t hb_bytes(hb_t *h) { return sizeof(hb_t) + sizeof(int) * (size_t)(h->n * 3 + 1 + h->nf * 4 + h->inc_start[h->n] * 2) + sizeof(long long) * (size_t)(h->nf + 1 + h->off[h->n] + h->n) + sizeof(double) * (size_t)(h->off[h->n] + h->foff[h->nf] + 3 * h->kmax); }

static inline void commit(hb_t *h, int i, int a) {
    int old = h->state[i]; h->t += 1;
    if (h->recording && a != old) { h->occ[h->off[i] + old] += (h->t - 1) - h->start[i]; h->start[i] = h->t - 1; }
    if (a == old) h->null_moves++;
    h->state[i] = a;
}

// the host applies an exactly decided fallback step (the decision came from heatbath_exact.decide_exact on the same u53 + refinement bits)
void hb_apply(hb_t *h, int i, int a) { commit(h, i, a); h->unresolved_site = -1; }

static inline int select_site(hb_t *h) {
    int n = h->n; int bits = 0; while ((1 << bits) < n) bits++;
    if ((n & (n - 1)) == 0) return (int)get_bits(h, bits);
    for (;;) { int r = (int)get_bits(h, bits); if (r < n) return r; h->site_rejections++; }
}

// returns the number of steps completed (== steps unless an UNRESOLVED decision stopped the batch early; then hb_unresolved gives the site and u53 and the host must call hb_apply before the next hb_run)
long long hb_run(hb_t *h, long long steps) {
    const double u = ldexp(1.0, -53);
    for (long long s = 0; s < steps; s++) {
        if (h->unresolved_site >= 0) return s;
        int i = select_site(h); int k = h->cards[i]; int m = h->inc_start[i + 1] - h->inc_start[i];
        for (int a = 0; a < k; a++) h->w[a] = h->psi[h->off[i] + a];
        for (int e = h->inc_start[i]; e < h->inc_start[i + 1]; e++) {
            int f = h->inc_f[e]; const double *v = h->fvals + h->foff[f];
            if (h->inc_role[e] == 0) { int kj = h->fkj[f]; int xb = h->state[h->fj[f]]; for (int a = 0; a < k; a++) h->w[a] *= v[(long long)a * kj + xb]; }
            else { int kj = h->fkj[f]; int xa = h->state[h->fi[f]]; for (int b = 0; b < k; b++) h->w[b] *= v[(long long)xa * kj + b]; }
        }
        // outward relative error of every weight: (m + 1) conversions (<= u each) + m multiplications (<= u each) -> (2 m + 1) u; widened to eps = (2 m + 4) u (covers the widening roundings)
        double eps = (2.0 * m + 4.0) * u; double clo = 0.0, chi = 0.0;
        for (int a = 0; a < k; a++) { double wl = h->w[a] * (1.0 - eps), wh = h->w[a] * (1.0 + eps); clo += wl; chi += wh; h->clo[a] = clo * (1.0 - (a + 2) * u); h->chi[a] = chi * (1.0 + (a + 2) * u); }
        double Slo = h->clo[k - 1], Shi = h->chi[k - 1];
        uint64_t u53 = get_bits(h, 53); double Ulo = (double)u53 * u, Uhi = (double)(u53 + 1) * u;
        double Tlo = Ulo * Slo * (1.0 - 2.0 * u), Thi = Uhi * Shi * (1.0 + 2.0 * u);
        // exact rule a* = min{a : U S < C_a}; with intervals: cond1(a) = (a == k - 1) || Thi < Clo[a]  (for the last state U S < S holds exactly since U < 1), cond2(a) = (a == 0) || Tlo >= Chi[a - 1];
        // a = the smallest index with cond1; decided iff cond2(a) (then every value in the intervals gives the same a*)
        int a = 0; while (a < k - 1 && !(Thi < h->clo[a])) a++;
        int ok = (a == 0) || (Tlo >= h->chi[a - 1]);
        if (!ok) { h->unresolved_site = i; h->unresolved_u53 = u53; h->unresolved++; return s; }
        h->resolved++; commit(h, i, a);
    }
    return steps;
}

// ---- exactness qualification support: the host can ask for the weights / intervals of a given site at the current state (no RNG consumption)
void hb_inspect(hb_t *h, int i, double *w_out, double *clo_out, double *chi_out) {
    const double u = ldexp(1.0, -53); int k = h->cards[i]; int m = h->inc_start[i + 1] - h->inc_start[i];
    for (int a = 0; a < k; a++) h->w[a] = h->psi[h->off[i] + a];
    for (int e = h->inc_start[i]; e < h->inc_start[i + 1]; e++) {
        int f = h->inc_f[e]; const double *v = h->fvals + h->foff[f];
        if (h->inc_role[e] == 0) { int kj = h->fkj[f]; int xb = h->state[h->fj[f]]; for (int a = 0; a < k; a++) h->w[a] *= v[(long long)a * kj + xb]; }
        else { int kj = h->fkj[f]; int xa = h->state[h->fi[f]]; for (int b = 0; b < k; b++) h->w[b] *= v[(long long)xa * kj + b]; }
    }
    double eps = (2.0 * m + 4.0) * u; double clo = 0.0, chi = 0.0;
    for (int a = 0; a < k; a++) { double wl = h->w[a] * (1.0 - eps), wh = h->w[a] * (1.0 + eps); clo += wl; chi += wh; w_out[a] = h->w[a]; clo_out[a] = clo * (1.0 - (a + 2) * u); chi_out[a] = chi * (1.0 + (a + 2) * u); }
}
