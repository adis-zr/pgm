// mpiv.hpp — DECLARED SHARED PRIMITIVE (used by both producer dqchain.cpp and checker dqcheck.cpp).
// Directed-rounded MPFR interval scalars: every operation rounds the lower endpoint down and the upper endpoint up, so an
// enclosure computed by composing these operations contains the exact real value. Complex numbers are rectangles (two intervals).
// Trig enclosures handle extrema inside the argument interval by comparing against directed multiples of pi.
#pragma once
#include <mpfr.h>
#include <gmp.h>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <string>
#include <vector>

struct IV { mpfr_t lo, hi; };
static mpfr_prec_t PREC = 96;

static inline void iv_init(IV& a) { mpfr_init2(a.lo, PREC); mpfr_init2(a.hi, PREC); }
static inline void iv_clear(IV& a) { mpfr_clear(a.lo); mpfr_clear(a.hi); }
static inline void iv_set_ui(IV& a, unsigned long v) { mpfr_set_ui(a.lo, v, MPFR_RNDD); mpfr_set_ui(a.hi, v, MPFR_RNDU); }
static inline void iv_set_q(IV& a, mpq_t q) { mpfr_set_q(a.lo, q, MPFR_RNDD); mpfr_set_q(a.hi, q, MPFR_RNDU); }
static inline void iv_set(IV& a, const IV& b) { mpfr_set(a.lo, b.lo, MPFR_RNDD); mpfr_set(a.hi, b.hi, MPFR_RNDU); }
static inline void iv_add(IV& r, const IV& a, const IV& b) { mpfr_add(r.lo, a.lo, b.lo, MPFR_RNDD); mpfr_add(r.hi, a.hi, b.hi, MPFR_RNDU); }
static inline void iv_sub(IV& r, const IV& a, const IV& b) { mpfr_t t; mpfr_init2(t, PREC); mpfr_sub(t, a.lo, b.hi, MPFR_RNDD); mpfr_sub(r.hi, a.hi, b.lo, MPFR_RNDU); mpfr_set(r.lo, t, MPFR_RNDD); mpfr_clear(t); }
static inline void iv_neg(IV& r, const IV& a) { mpfr_t t; mpfr_init2(t, PREC); mpfr_neg(t, a.hi, MPFR_RNDD); mpfr_neg(r.hi, a.lo, MPFR_RNDU); mpfr_set(r.lo, t, MPFR_RNDD); mpfr_clear(t); }
// general interval product (any signs): min/max over the four directed products
static inline void iv_mul(IV& r, const IV& a, const IV& b) {
  mpfr_t p[4], q[4]; for (int i = 0; i < 4; i++) { mpfr_init2(p[i], PREC); mpfr_init2(q[i], PREC); }
  mpfr_mul(p[0], a.lo, b.lo, MPFR_RNDD); mpfr_mul(p[1], a.lo, b.hi, MPFR_RNDD); mpfr_mul(p[2], a.hi, b.lo, MPFR_RNDD); mpfr_mul(p[3], a.hi, b.hi, MPFR_RNDD);
  mpfr_mul(q[0], a.lo, b.lo, MPFR_RNDU); mpfr_mul(q[1], a.lo, b.hi, MPFR_RNDU); mpfr_mul(q[2], a.hi, b.lo, MPFR_RNDU); mpfr_mul(q[3], a.hi, b.hi, MPFR_RNDU);
  mpfr_set(r.lo, p[0], MPFR_RNDD); for (int i = 1; i < 4; i++) if (mpfr_cmp(p[i], r.lo) < 0) mpfr_set(r.lo, p[i], MPFR_RNDD);
  mpfr_set(r.hi, q[0], MPFR_RNDU); for (int i = 1; i < 4; i++) if (mpfr_cmp(q[i], r.hi) > 0) mpfr_set(r.hi, q[i], MPFR_RNDU);
  for (int i = 0; i < 4; i++) { mpfr_clear(p[i]); mpfr_clear(q[i]); }
}
// product of two NONNEGATIVE intervals (a.lo >= 0, b.lo >= 0): two directed products suffice
static inline void iv_mul_pos(IV& r, const IV& a, const IV& b) { mpfr_t t; mpfr_init2(t, PREC); mpfr_mul(t, a.lo, b.lo, MPFR_RNDD); mpfr_mul(r.hi, a.hi, b.hi, MPFR_RNDU); mpfr_set(r.lo, t, MPFR_RNDD); mpfr_clear(t); }
// quotient a / b with b.lo > 0 (positive divisor); a of any sign
static inline void iv_div_pos(IV& r, const IV& a, const IV& b) {
  mpfr_t t; mpfr_init2(t, PREC);
  if (mpfr_sgn(a.lo) >= 0) mpfr_div(t, a.lo, b.hi, MPFR_RNDD); else mpfr_div(t, a.lo, b.lo, MPFR_RNDD);
  if (mpfr_sgn(a.hi) >= 0) mpfr_div(r.hi, a.hi, b.lo, MPFR_RNDU); else mpfr_div(r.hi, a.hi, b.hi, MPFR_RNDU);
  mpfr_set(r.lo, t, MPFR_RNDD); mpfr_clear(t);
}
static inline void iv_exp(IV& r, const IV& a) { mpfr_t t; mpfr_init2(t, PREC); mpfr_exp(t, a.lo, MPFR_RNDD); mpfr_exp(r.hi, a.hi, MPFR_RNDU); mpfr_set(r.lo, t, MPFR_RNDD); mpfr_clear(t); }
static inline void iv_inv_pos(IV& r, const IV& a) { mpfr_t t; mpfr_init2(t, PREC); mpfr_ui_div(t, 1, a.hi, MPFR_RNDD); mpfr_ui_div(r.hi, 1, a.lo, MPFR_RNDU); mpfr_set(r.lo, t, MPFR_RNDD); mpfr_clear(t); }
static inline void iv_sqrt_pos(IV& r, const IV& a) { mpfr_t t; mpfr_init2(t, PREC); mpfr_sqrt(t, a.lo, MPFR_RNDD); mpfr_sqrt(r.hi, a.hi, MPFR_RNDU); mpfr_set(r.lo, t, MPFR_RNDD); mpfr_clear(t); }
static inline bool iv_pos(const IV& a) { return mpfr_sgn(a.lo) > 0; }
static inline bool iv_finite(const IV& a) { return mpfr_number_p(a.lo) && mpfr_number_p(a.hi) && mpfr_cmp(a.lo, a.hi) <= 0; }

// cos/sin enclosures: endpoint values with both roundings, plus +-1 when a critical point k*pi/2 lies inside [lo, hi].
static void iv_cos_sin(IV& c, IV& s, const IV& x) {
  mpfr_t pl, pu, t, u, kf; mpfr_init2(pl, PREC); mpfr_init2(pu, PREC); mpfr_init2(t, PREC); mpfr_init2(u, PREC); mpfr_init2(kf, PREC);
  mpfr_const_pi(pl, MPFR_RNDD); mpfr_const_pi(pu, MPFR_RNDU);
  // candidate values at the endpoints
  mpfr_t cl[2], cu[2], sl[2], su[2]; for (int i = 0; i < 2; i++) { mpfr_init2(cl[i], PREC); mpfr_init2(cu[i], PREC); mpfr_init2(sl[i], PREC); mpfr_init2(su[i], PREC); }
  mpfr_cos(cl[0], x.lo, MPFR_RNDD); mpfr_cos(cu[0], x.lo, MPFR_RNDU); mpfr_cos(cl[1], x.hi, MPFR_RNDD); mpfr_cos(cu[1], x.hi, MPFR_RNDU);
  mpfr_sin(sl[0], x.lo, MPFR_RNDD); mpfr_sin(su[0], x.lo, MPFR_RNDU); mpfr_sin(sl[1], x.hi, MPFR_RNDD); mpfr_sin(su[1], x.hi, MPFR_RNDU);
  mpfr_min(c.lo, cl[0], cl[1], MPFR_RNDD); mpfr_max(c.hi, cu[0], cu[1], MPFR_RNDU);
  mpfr_min(s.lo, sl[0], sl[1], MPFR_RNDD); mpfr_max(s.hi, su[0], su[1], MPFR_RNDU);
  // critical points m*pi/2 for integers m with x.lo <= m*pi/2 <= x.hi (conservatively: m*pi_lo/2 <= x.hi and m*pi_up/2 >= x.lo)
  mpfr_div_ui(t, pl, 2, MPFR_RNDD); mpfr_div(kf, x.lo, t, MPFR_RNDD); mpfr_floor(kf, kf); long m0 = mpfr_get_si(kf, MPFR_RNDD) - 1;
  mpfr_div_ui(u, pu, 2, MPFR_RNDU); mpfr_div(kf, x.hi, u, MPFR_RNDU); mpfr_ceil(kf, kf); long m1 = mpfr_get_si(kf, MPFR_RNDU) + 1;
  for (long m = m0; m <= m1; m++) {
    // interval for m*pi/2
    mpfr_t a1, a2; mpfr_init2(a1, PREC); mpfr_init2(a2, PREC);
    if (m >= 0) { mpfr_mul_si(a1, pl, m, MPFR_RNDD); mpfr_mul_si(a2, pu, m, MPFR_RNDU); } else { mpfr_mul_si(a1, pu, m, MPFR_RNDD); mpfr_mul_si(a2, pl, m, MPFR_RNDU); }
    mpfr_div_ui(a1, a1, 2, MPFR_RNDD); mpfr_div_ui(a2, a2, 2, MPFR_RNDU);
    bool inside = mpfr_cmp(a2, x.lo) >= 0 && mpfr_cmp(a1, x.hi) <= 0;
    if (inside) {
      long r4 = ((m % 4) + 4) % 4;  // m*pi/2: cos = 1,0,-1,0 ; sin = 0,1,0,-1
      if (r4 == 0) mpfr_set_ui(c.hi, 1, MPFR_RNDU); if (r4 == 2) mpfr_set_si(c.lo, -1, MPFR_RNDD);
      if (r4 == 1) mpfr_set_ui(s.hi, 1, MPFR_RNDU); if (r4 == 3) mpfr_set_si(s.lo, -1, MPFR_RNDD);
    }
    mpfr_clear(a1); mpfr_clear(a2);
  }
  for (int i = 0; i < 2; i++) { mpfr_clear(cl[i]); mpfr_clear(cu[i]); mpfr_clear(sl[i]); mpfr_clear(su[i]); }
  mpfr_clear(pl); mpfr_clear(pu); mpfr_clear(t); mpfr_clear(u); mpfr_clear(kf);
}

// exact serialisation: "m*2^e" with integer m (decimal) and exponent e, exact for finite mpfr values
static std::string mpfr_exact(const mpfr_t x) {
  if (mpfr_zero_p(x)) return "0*2^0";
  mpz_t m; mpz_init(m); mp_exp_t e = mpfr_get_z_2exp(m, x);
  char* s = mpz_get_str(NULL, 10, m); std::string out = std::string(s) + "*2^" + std::to_string((long)e); free(s); mpz_clear(m); return out;
}
static std::string iv_json(const IV& a) { return "[\"" + mpfr_exact(a.lo) + "\",\"" + mpfr_exact(a.hi) + "\"]"; }

// complex rectangle
struct CV { IV re, im; };
static inline void cv_init(CV& z) { iv_init(z.re); iv_init(z.im); }
static inline void cv_clear(CV& z) { iv_clear(z.re); iv_clear(z.im); }
static inline void cv_set(CV& z, const CV& w) { iv_set(z.re, w.re); iv_set(z.im, w.im); }
static inline void cv_add(CV& r, const CV& a, const CV& b) { iv_add(r.re, a.re, b.re); iv_add(r.im, a.im, b.im); }
static inline void cv_mul(CV& r, const CV& a, const CV& b) { // (ar + i ai)(br + i bi)
  IV t1, t2, t3, t4; iv_init(t1); iv_init(t2); iv_init(t3); iv_init(t4);
  iv_mul(t1, a.re, b.re); iv_mul(t2, a.im, b.im); iv_mul(t3, a.re, b.im); iv_mul(t4, a.im, b.re);
  iv_sub(r.re, t1, t2); iv_add(r.im, t3, t4);
  iv_clear(t1); iv_clear(t2); iv_clear(t3); iv_clear(t4);
}
static inline void cv_scale_pos(CV& r, const CV& a, const IV& s) { iv_mul(r.re, a.re, s); iv_mul(r.im, a.im, s); }      // s >= 0 (general mul keeps it safe)
static inline void cv_div_pos(CV& r, const CV& a, const IV& s) { iv_div_pos(r.re, a.re, s); iv_div_pos(r.im, a.im, s); }
static std::string cv_json(const CV& z) { return "{\"re\":" + iv_json(z.re) + ",\"im\":" + iv_json(z.im) + "}"; }
