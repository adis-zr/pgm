// dqchain — PRODUCER for the direct chain-query pilot (CLAUDE_CODE_SPEC.md).
// Two-state chain, directed-rounded MPFR intervals (mpiv.hpp). Every printed enclosure CONTAINS the exact real value; the
// arithmetic-error contract is established by the enclosure widths (checked against the frozen budgets by the Python wrapper).
//   forward:  alpha_i(x) = u_i(x) * sum_{x'} alpha_{i-1}(x') K_{i-1}(x',x),  normalised by s_i = sum_x alpha_i(x)
//   backward: beta_i(x)  = sum_{x'} K_i(x,x') u_{i+1}(x') beta_{i+1}(x'),    normalised by its sum
//   P(x_i = x) = alpha_i(x) beta_i(x) / sum_x alpha_i beta_i ;  m_i = P(+)-P(-) ;  q_0 = P(x_0 = +)
// Centre: c_{t+1} = c_t - step * mid(grad_t), grad = c - sum a_i m_i, rounded to the 2^-64 grid; stop after STEPS updates (frozen).
// Fourier (mode F): complex forward chains for the two markers x_0 = +-1 with unary rotations e^{i w a_i x}, scaled by the REAL
// chain's normalisers s_i (no complex division); phi_s(w) = sum_x gamma^s_{n-1}(x) / sum_x alpha_{n-1}(x).
// Usage: dqchain INPUT OUT.json --mode D|F --fbits F [--steps 17 --step 2/5 --freq-h p/q --J J --progress PATH]
#include "mpiv.hpp"
#include "dqinput.hpp"
#include "dqcommon.hpp"
#include <cmath>

static Progress PROG;
static long PASSES_TOTAL = 0, PASS_NO = 0;

struct Chain {
  const Input& in; long n;
  std::vector<IV> h, a, f;              // exact rationals enclosed at PREC
  std::vector<int> pin;                 // 0 free, +-1 pinned
  Chain(const Input& I) : in(I), n(I.n) {
    h.resize(n); a.resize(n); f.resize(n - 1); pin.assign(n, 0);
    for (long i = 0; i < n; i++) { iv_init(h[i]); iv_set_q(h[i], (mpq_ptr)&I.h[i]); iv_init(a[i]); iv_set_q(a[i], (mpq_ptr)&I.a[i]); }
    for (long i = 0; i < n - 1; i++) { iv_init(f[i]); iv_set_q(f[i], (mpq_ptr)&I.f[i]); }
    for (auto& kv : I.pins) pin[kv.first] = kv.second;
  }
  // unary weights u_i(+), u_i(-) for centre c (exact mpfr): theta_i = h_i - a_i c ; forbidden state -> 0
  void unary(const mpfr_t c, std::vector<IV>& up, std::vector<IV>& um) {
    IV cI, t, e; iv_init(cI); iv_init(t); iv_init(e); mpfr_set(cI.lo, c, MPFR_RNDD); mpfr_set(cI.hi, c, MPFR_RNDU);
    for (long i = 0; i < n; i++) {
      iv_mul(t, a[i], cI); iv_sub(t, h[i], t); iv_exp(e, t);
      iv_set(up[i], e); iv_inv_pos(um[i], e);
      if (pin[i] == -1) iv_set_ui(up[i], 0); if (pin[i] == 1) iv_set_ui(um[i], 0);
    }
    iv_clear(cI); iv_clear(t); iv_clear(e);
  }
};

// one real forward/backward pass. Messages are scaled by EXACT powers of two (mpfr_mul_2si is exact), never divided by a dependent
// interval sum: an interval normalisation alpha/(alpha_+ + alpha_-) doubles the relative width at every site and overflows after ~100 sites.
// Outputs: means m_i, q0 = P(x_0=+), the scaling exponents e_i (for the complex chains) and the scaled final total T = sum_x alpha_{n-1}(x).
static long pow2_exponent(const IV& a, const IV& b) { mpfr_t t; mpfr_init2(t, PREC); mpfr_add(t, a.hi, b.hi, MPFR_RNDU); long e = mpfr_zero_p(t) ? 0 : (long)mpfr_get_exp(t); mpfr_clear(t); return e; }
static inline void iv_scale2(IV& a, long e) { mpfr_mul_2si(a.lo, a.lo, e, MPFR_RNDD); mpfr_mul_2si(a.hi, a.hi, e, MPFR_RNDU); }
static void real_pass(Chain& C, const std::vector<IV>& up, const std::vector<IV>& um, std::vector<IV>& m, IV& q0, std::vector<long>* sexp, IV* Tfinal, const char* phase, long iter) {
  long n = C.n; PASS_NO++;
  std::vector<IV> ap(n), am(n); for (long i = 0; i < n; i++) { iv_init(ap[i]); iv_init(am[i]); }
  IV t1, t2, t3; iv_init(t1); iv_init(t2); iv_init(t3);
  iv_set(ap[0], up[0]); iv_set(am[0], um[0]); { long e = pow2_exponent(ap[0], am[0]); iv_scale2(ap[0], -e); iv_scale2(am[0], -e); if (sexp) (*sexp)[0] = e; }
  for (long i = 1; i < n; i++) {
    iv_mul_pos(t1, ap[i - 1], C.f[i - 1]); iv_add(t1, t1, am[i - 1]); iv_mul_pos(ap[i], up[i], t1);
    iv_mul_pos(t2, am[i - 1], C.f[i - 1]); iv_add(t2, t2, ap[i - 1]); iv_mul_pos(am[i], um[i], t2);
    long e = pow2_exponent(ap[i], am[i]); iv_scale2(ap[i], -e); iv_scale2(am[i], -e); if (sexp) (*sexp)[i] = e;
    if ((i & 4095) == 0) PROG.line(phase, i, PASS_NO, PASSES_TOTAL, iter, -1, "fwd");
  }
  if (Tfinal) iv_add(*Tfinal, ap[n - 1], am[n - 1]);
  IV bp, bm, nbp, nbm, Pp, Pm, den; iv_init(bp); iv_init(bm); iv_init(nbp); iv_init(nbm); iv_init(Pp); iv_init(Pm); iv_init(den);
  iv_set_ui(bp, 1); iv_set_ui(bm, 1);
  for (long i = n - 1; i >= 0; i--) {
    iv_mul_pos(Pp, ap[i], bp); iv_mul_pos(Pm, am[i], bm); iv_add(den, Pp, Pm);
    iv_div_pos(Pp, Pp, den); iv_div_pos(Pm, Pm, den); iv_sub(m[i], Pp, Pm);
    if (i == 0) iv_set(q0, Pp);
    if (i > 0) {
      iv_mul_pos(t1, up[i], bp); iv_mul_pos(t2, um[i], bm);
      iv_mul_pos(t3, t1, C.f[i - 1]); iv_add(nbp, t3, t2);
      iv_mul_pos(t3, t2, C.f[i - 1]); iv_add(nbm, t3, t1);
      long e = pow2_exponent(nbp, nbm); iv_scale2(nbp, -e); iv_scale2(nbm, -e); iv_set(bp, nbp); iv_set(bm, nbm);
      if ((i & 4095) == 0) PROG.line(phase, i, PASS_NO, PASSES_TOTAL, iter, -1, "bwd");
    }
  }
  for (long i = 0; i < n; i++) { iv_clear(ap[i]); iv_clear(am[i]); }
  iv_clear(t1); iv_clear(t2); iv_clear(t3); iv_clear(bp); iv_clear(bm); iv_clear(nbp); iv_clear(nbm); iv_clear(Pp); iv_clear(Pm); iv_clear(den);
}

// gradient g = c - sum a_i m_i  (interval)
static void gradient(Chain& C, const mpfr_t c, const std::vector<IV>& m, IV& g) {
  IV acc, t; iv_init(acc); iv_init(t); iv_set_ui(acc, 0);
  for (long i = 0; i < C.n; i++) { iv_mul(t, C.a[i], m[i]); iv_add(acc, acc, t); }
  IV cI; iv_init(cI); mpfr_set(cI.lo, c, MPFR_RNDD); mpfr_set(cI.hi, c, MPFR_RNDU); iv_sub(g, cI, acc);
  iv_clear(acc); iv_clear(t); iv_clear(cI);
}

// complex pass for frequency w (exact rational k*h).  phi_s(w) = E_Q[1{x_0=s} e^{i w AX}] = (sum_x gamma^s_{n-1}(x)) / T.
// NUMERICS (the point of this routine): the complex messages are propagated as POINT values (round-to-nearest at PREC bits) and the
// error is carried as ONE nonnegative scalar s_i (RoundUp) with the invariant  |gamma_hat_i(x) - gamma_i(x)| <= s_i * alpha_i(x)
// componentwise, where alpha_i is the exact real chain (same exponent scaling).  Rectangle interval arithmetic cannot be used here: the
// wrapping effect on signed quantities multiplies widths by a constant factor per site and overflows after a few thousand sites.
// Recursion (D = diag(v_+, v_-), v_x = u_x e^{i w a_i x}, M = [[f,1],[1,f]], all nonnegative moduli):
//   e_i = 2^-e [ fl(D^ M^ g^) - D^ M^ g^ ] + 2^-e [ (D^ M^ - D M) g^ ] + 2^-e D M e_{i-1}
//   |D M e_{i-1}| <= s_{i-1} |D| M alpha_{i-1} = s_{i-1} 2^e alpha_i ;  |g^| <= (1+s_{i-1}) alpha_{i-1} ;
//   |D^ - D| <= dD |D| with dD = du (1+de) + de, du = relative half-width of the u-interval, de = angle half-width + 2^(1-PREC) (cos, sin rounded);
//   |M^ - M| <= df M with df = relative half-width of the f-interval;  local rounding <= cr 2^-PREC |D^||M^||g^| with cr = 8
//   (two real mults for f*g, two adds, four mults + two adds for the complex product, each a relative 2^-PREC perturbation; 8 is generous).
//   => s_i = s_{i-1} + (1+s_{i-1}) [ df(1+dD) + dD + cr 2^-PREC (1+dD)(1+df) ]   (RoundUp)
// Final: phi = (sum_x gamma(x))/T with |sum_x e(x)| <= s T_hi; returned as a rigorous rectangle.
static void complex_pass(Chain& C, const std::vector<IV>& up, const std::vector<IV>& um, const std::vector<long>& sexp, const IV& T, const IV& w, CV& phip, CV& phim, long freq_idx, const char* phase, mpfr_t s_out) {
  long n = C.n; PASS_NO++;
  mpfr_t gPp_re, gPp_im, gPm_re, gPm_im, gMp_re, gMp_im, gMm_re, gMm_im;      // point messages: P = marker x_0=+, M = marker x_0=-; second letter = component
  mpfr_t nPp_re, nPp_im, nPm_re, nPm_im, nMp_re, nMp_im, nMm_re, nMm_im;
  mpfr_t ubar_p, ubar_m, fbar, ang, cs, sn, vp_re, vp_im, vm_re, vm_im, t1, t2, t3, t4, tre, tim;
  mpfr_t* all[] = {&gPp_re,&gPp_im,&gPm_re,&gPm_im,&gMp_re,&gMp_im,&gMm_re,&gMm_im,&nPp_re,&nPp_im,&nPm_re,&nPm_im,&nMp_re,&nMp_im,&nMm_re,&nMm_im,&ubar_p,&ubar_m,&fbar,&ang,&cs,&sn,&vp_re,&vp_im,&vm_re,&vm_im,&t1,&t2,&t3,&t4,&tre,&tim};
  for (auto p : all) mpfr_init2(*p, PREC);
  // error bookkeeping (RoundUp)
  mpfr_t s, du, de, df, dD, inc, one_s, eps, tmpu; mpfr_t* err[] = {&s,&du,&de,&df,&dD,&inc,&one_s,&eps,&tmpu}; for (auto p : err) mpfr_init2(*p, PREC);
  mpfr_set_ui(s, 0, MPFR_RNDU);
  mpfr_set_ui(eps, 1, MPFR_RNDU); mpfr_div_2ui(eps, eps, PREC, MPFR_RNDU);               // 2^-PREC
  IV angI, csI, snI; iv_init(angI); iv_init(csI); iv_init(snI);
  auto relhw = [&](mpfr_t out, const IV& x) { mpfr_sub(out, x.hi, x.lo, MPFR_RNDU); mpfr_div_2ui(out, out, 1, MPFR_RNDU); mpfr_div(out, out, x.lo, MPFR_RNDU); };   // (hi-lo)/(2 lo), x.lo > 0
  auto mid = [&](mpfr_t out, const IV& x) { mpfr_add(out, x.lo, x.hi, MPFR_RNDN); mpfr_div_2ui(out, out, 1, MPFR_RNDN); };
  auto site_setup = [&](long i) {
    // point unaries, point factor, point rotation; and the local perturbation bound inc
    mid(ubar_p, up[i]); mid(ubar_m, um[i]); if (i > 0) mid(fbar, C.f[i - 1]);
    iv_mul(angI, w, C.a[i]); mid(ang, angI); mpfr_cos(cs, ang, MPFR_RNDN); mpfr_sin(sn, ang, MPFR_RNDN);
    mpfr_mul(vp_re, ubar_p, cs, MPFR_RNDN); mpfr_mul(vp_im, ubar_p, sn, MPFR_RNDN); mpfr_mul(vm_re, ubar_m, cs, MPFR_RNDN); mpfr_mul(vm_im, ubar_m, sn, MPFR_RNDN); mpfr_neg(vm_im, vm_im, MPFR_RNDN);
    // du = max relative half-width of the two u intervals (a pinned state has u = 0 exactly: skip it)
    mpfr_set_ui(du, 0, MPFR_RNDU);
    if (mpfr_sgn(up[i].lo) > 0) { relhw(tmpu, up[i]); mpfr_max(du, du, tmpu, MPFR_RNDU); }
    if (mpfr_sgn(um[i].lo) > 0) { relhw(tmpu, um[i]); mpfr_max(du, du, tmpu, MPFR_RNDU); }
    // de = angle half-width + 2^(1-PREC)
    mpfr_sub(de, angI.hi, angI.lo, MPFR_RNDU); mpfr_div_2ui(de, de, 1, MPFR_RNDU); mpfr_mul_2ui(tmpu, eps, 1, MPFR_RNDU); mpfr_add(de, de, tmpu, MPFR_RNDU);
    // dD = du(1+de) + de
    mpfr_add_ui(tmpu, de, 1, MPFR_RNDU); mpfr_mul(dD, du, tmpu, MPFR_RNDU); mpfr_add(dD, dD, de, MPFR_RNDU);
    // df
    if (i > 0) relhw(df, C.f[i - 1]); else mpfr_set_ui(df, 0, MPFR_RNDU);
    // inc = df(1+dD) + dD + 8 eps (1+dD)(1+df)
    mpfr_add_ui(tmpu, dD, 1, MPFR_RNDU); mpfr_mul(inc, df, tmpu, MPFR_RNDU); mpfr_add(inc, inc, dD, MPFR_RNDU);
    mpfr_add_ui(one_s, df, 1, MPFR_RNDU); mpfr_mul(one_s, one_s, tmpu, MPFR_RNDU); mpfr_mul_ui(one_s, one_s, 8, MPFR_RNDU); mpfr_mul(one_s, one_s, eps, MPFR_RNDU); mpfr_add(inc, inc, one_s, MPFR_RNDU);
  };
  auto cmul = [&](mpfr_t rre, mpfr_t rim, mpfr_t are, mpfr_t aim, mpfr_t bre, mpfr_t bim) {   // (a)(b), round to nearest
    mpfr_mul(t1, are, bre, MPFR_RNDN); mpfr_mul(t2, aim, bim, MPFR_RNDN); mpfr_mul(t3, are, bim, MPFR_RNDN); mpfr_mul(t4, aim, bre, MPFR_RNDN);
    mpfr_sub(rre, t1, t2, MPFR_RNDN); mpfr_add(rim, t3, t4, MPFR_RNDN);
  };
  // site 0: markers
  site_setup(0);
  mpfr_set(gPp_re, vp_re, MPFR_RNDN); mpfr_set(gPp_im, vp_im, MPFR_RNDN); mpfr_set_ui(gPm_re, 0, MPFR_RNDN); mpfr_set_ui(gPm_im, 0, MPFR_RNDN);
  mpfr_set_ui(gMp_re, 0, MPFR_RNDN); mpfr_set_ui(gMp_im, 0, MPFR_RNDN); mpfr_set(gMm_re, vm_re, MPFR_RNDN); mpfr_set(gMm_im, vm_im, MPFR_RNDN);
  for (auto p : all) if (p == &gPp_re || p == &gPp_im || p == &gPm_re || p == &gPm_im || p == &gMp_re || p == &gMp_im || p == &gMm_re || p == &gMm_im) mpfr_mul_2si(*p, *p, -sexp[0], MPFR_RNDN);
  mpfr_set(s, dD, MPFR_RNDU);                                                               // |e_0| <= dD alpha_0
  for (long i = 1; i < n; i++) {
    site_setup(i);
    // new(+) = v(+) [f g(+) + g(-)] ; new(-) = v(-) [g(+) + f g(-)]   for both marker chains
    mpfr_mul(tre, fbar, gPp_re, MPFR_RNDN); mpfr_mul(tim, fbar, gPp_im, MPFR_RNDN); mpfr_add(tre, tre, gPm_re, MPFR_RNDN); mpfr_add(tim, tim, gPm_im, MPFR_RNDN); cmul(nPp_re, nPp_im, vp_re, vp_im, tre, tim);
    mpfr_mul(tre, fbar, gPm_re, MPFR_RNDN); mpfr_mul(tim, fbar, gPm_im, MPFR_RNDN); mpfr_add(tre, tre, gPp_re, MPFR_RNDN); mpfr_add(tim, tim, gPp_im, MPFR_RNDN); cmul(nPm_re, nPm_im, vm_re, vm_im, tre, tim);
    mpfr_mul(tre, fbar, gMp_re, MPFR_RNDN); mpfr_mul(tim, fbar, gMp_im, MPFR_RNDN); mpfr_add(tre, tre, gMm_re, MPFR_RNDN); mpfr_add(tim, tim, gMm_im, MPFR_RNDN); cmul(nMp_re, nMp_im, vp_re, vp_im, tre, tim);
    mpfr_mul(tre, fbar, gMm_re, MPFR_RNDN); mpfr_mul(tim, fbar, gMm_im, MPFR_RNDN); mpfr_add(tre, tre, gMp_re, MPFR_RNDN); mpfr_add(tim, tim, gMp_im, MPFR_RNDN); cmul(nMm_re, nMm_im, vm_re, vm_im, tre, tim);
    mpfr_mul_2si(gPp_re, nPp_re, -sexp[i], MPFR_RNDN); mpfr_mul_2si(gPp_im, nPp_im, -sexp[i], MPFR_RNDN); mpfr_mul_2si(gPm_re, nPm_re, -sexp[i], MPFR_RNDN); mpfr_mul_2si(gPm_im, nPm_im, -sexp[i], MPFR_RNDN);
    mpfr_mul_2si(gMp_re, nMp_re, -sexp[i], MPFR_RNDN); mpfr_mul_2si(gMp_im, nMp_im, -sexp[i], MPFR_RNDN); mpfr_mul_2si(gMm_re, nMm_re, -sexp[i], MPFR_RNDN); mpfr_mul_2si(gMm_im, nMm_im, -sexp[i], MPFR_RNDN);
    // s_i = s + (1+s) inc
    mpfr_add_ui(one_s, s, 1, MPFR_RNDU); mpfr_mul(one_s, one_s, inc, MPFR_RNDU); mpfr_add(s, s, one_s, MPFR_RNDU);
    if ((i & 4095) == 0) PROG.line(phase, i, PASS_NO, PASSES_TOTAL, -1, freq_idx, "cplx");
  }
  // phi = (g(+) + g(-)) / T  with |error of the sum| <= s*T_hi + 2 eps (|g(+)| + |g(-)|)  (the two adds)
  auto finish = [&](CV& phi, mpfr_t a_re, mpfr_t a_im, mpfr_t b_re, mpfr_t b_im) {
    mpfr_add(tre, a_re, b_re, MPFR_RNDN); mpfr_add(tim, a_im, b_im, MPFR_RNDN);
    mpfr_t rad, mag; mpfr_init2(rad, PREC); mpfr_init2(mag, PREC);
    mpfr_mul(rad, s, T.hi, MPFR_RNDU);
    mpfr_abs(mag, a_re, MPFR_RNDU); mpfr_abs(t1, a_im, MPFR_RNDU); mpfr_add(mag, mag, t1, MPFR_RNDU); mpfr_abs(t1, b_re, MPFR_RNDU); mpfr_add(mag, mag, t1, MPFR_RNDU); mpfr_abs(t1, b_im, MPFR_RNDU); mpfr_add(mag, mag, t1, MPFR_RNDU);
    mpfr_mul(mag, mag, eps, MPFR_RNDU); mpfr_mul_2ui(mag, mag, 1, MPFR_RNDU); mpfr_add(rad, rad, mag, MPFR_RNDU);
    IV num; iv_init(num);
    mpfr_sub(num.lo, tre, rad, MPFR_RNDD); mpfr_add(num.hi, tre, rad, MPFR_RNDU); iv_div_pos(phi.re, num, T);
    mpfr_sub(num.lo, tim, rad, MPFR_RNDD); mpfr_add(num.hi, tim, rad, MPFR_RNDU); iv_div_pos(phi.im, num, T);
    iv_clear(num); mpfr_clear(rad); mpfr_clear(mag);
  };
  finish(phip, gPp_re, gPp_im, gPm_re, gPm_im); finish(phim, gMp_re, gMp_im, gMm_re, gMm_im);
  if (s_out) mpfr_set(s_out, s, MPFR_RNDU);
  for (auto p : all) mpfr_clear(*p); for (auto p : err) mpfr_clear(*p); iv_clear(angI); iv_clear(csI); iv_clear(snI);
}

static std::string qstr(const mpq_t q) { char* s = mpq_get_str(NULL, 10, q); std::string r(s); free(s); return r; }

int main(int argc, char** argv) {
  if (argc < 3) { fprintf(stderr, "usage\n"); return 2; }
  const char* inpath = argv[1]; const char* outpath = argv[2];
  std::string mode = "D"; long fbits = 80, steps = 17, J = 3; std::string stepq = "2/5", freqh = "1"; const char* progress = nullptr;
  for (int i = 3; i < argc; i++) { std::string k = argv[i]; if (k == "--mode") mode = argv[++i]; else if (k == "--fbits") fbits = atol(argv[++i]); else if (k == "--steps") steps = atol(argv[++i]); else if (k == "--step") stepq = argv[++i]; else if (k == "--freq-h") freqh = argv[++i]; else if (k == "--J") J = atol(argv[++i]); else if (k == "--progress") progress = argv[++i]; else { fprintf(stderr, "bad arg %s\n", argv[i]); return 2; } }
  PREC = fbits + 16;   // all magnitudes here are below 2^16, so this gives >= fbits fractional bits
  if (progress) PROG.open(progress);
  double W0 = mono_now(), C0 = cpu_now();
  std::string json = "{\n";
  // ---- parse
  PhaseTimer tp("parse"); Input in; std::string err;
  if (!read_input(inpath, in, err)) { fprintf(stderr, "INPUT_PARSE_FAILED: %s\n", err.c_str()); return 3; }
  Chain C(in); long n = C.n;
  json += "\"mode\":\"" + mode + "\",\"n\":" + std::to_string(n) + ",\"case\":\"" + in.kase + "\",\"query\":" + std::to_string(in.query) + ",\"fbits\":" + std::to_string(fbits) + ",\"mpfr_prec\":" + std::to_string(PREC) + ",\"steps\":" + std::to_string(steps) + ",\"step\":\"" + stepq + "\",";
  json += "\"phase_parse\":{\"wall_s\":" + std::to_string(tp.wall()) + ",\"cpu_s\":" + std::to_string(tp.cpu()) + "},";
  PASSES_TOTAL = steps + 1 + (mode == "F" ? J : 0);
  // ---- centre construction
  PhaseTimer tc("center");
  mpq_t stepQ; mpq_init(stepQ); mpq_set_str(stepQ, stepq.c_str(), 10); mpq_canonicalize(stepQ);
  IV stepI; iv_init(stepI); iv_set_q(stepI, stepQ);
  mpfr_t c; mpfr_init2(c, PREC); mpfr_set_ui(c, 0, MPFR_RNDN);
  std::vector<IV> up(n), um(n), m(n); for (long i = 0; i < n; i++) { iv_init(up[i]); iv_init(um[i]); iv_init(m[i]); }
  IV q0, g, gmid, upd; iv_init(q0); iv_init(g); iv_init(gmid); iv_init(upd);
  std::string iters = "[";
  std::string q_res_only;                                   // q_0 of the residual-only law (c = 0): the first pass
  mpfr_t half, gw, gm, tmp; mpfr_init2(half, PREC); mpfr_init2(gw, PREC); mpfr_init2(gm, PREC); mpfr_init2(tmp, PREC);
  for (long t = 0; t < steps; t++) {
    C.unary(c, up, um);
    real_pass(C, up, um, m, q0, nullptr, nullptr, "center", t);
    if (t == 0) q_res_only = iv_json(q0);
    gradient(C, c, m, g);
    // midpoint (nearest) and half-width (up)
    mpfr_add(gm, g.lo, g.hi, MPFR_RNDN); mpfr_div_2ui(gm, gm, 1, MPFR_RNDN);
    mpfr_sub(gw, g.hi, g.lo, MPFR_RNDU); mpfr_div_2ui(gw, gw, 1, MPFR_RNDU);
    // c_new = c - step*gm, rounded to the 2^-64 grid (nearest)
    mpfr_mul_q(tmp, gm, stepQ, MPFR_RNDN); mpfr_sub(tmp, c, tmp, MPFR_RNDN);
    mpfr_mul_2ui(tmp, tmp, 64, MPFR_RNDN); mpfr_rint(tmp, tmp, MPFR_RNDN); mpfr_div_2ui(tmp, tmp, 64, MPFR_RNDN);
    iters += std::string(t ? "," : "") + "{\"iter\":" + std::to_string(t) + ",\"c\":\"" + mpfr_exact(c) + "\",\"grad\":" + iv_json(g) + ",\"grad_halfwidth_upper\":\"" + mpfr_exact(gw) + "\",\"c_next\":\"" + mpfr_exact(tmp) + "\"}";
    mpfr_set(c, tmp, MPFR_RNDN);
    { char buf[96]; snprintf(buf, sizeof buf, "iter_done|grad_abs<=%.3e", mpfr_get_d(gw, MPFR_RNDU) + fabs(mpfr_get_d(gm, MPFR_RNDN))); PROG.line("center", n, PASS_NO, PASSES_TOTAL, t, -1, buf); }
  }
  json += "\"center\":{\"c\":\"" + mpfr_exact(c) + "\",\"c_grid\":\"2^-64\",\"iterations\":" + iters + "],\"wall_s\":" + std::to_string(tc.wall()) + ",\"cpu_s\":" + std::to_string(tc.cpu()) + "},";
  json += "\"q0_residual_only_c0\":" + q_res_only + ",";
  // ---- final real pass at the stored centre: q0, residual, normalisers
  PhaseTimer tf("final_real");
  std::vector<long> sexp(n); IV Tfin; iv_init(Tfin);
  C.unary(c, up, um);
  real_pass(C, up, um, m, q0, &sexp, &Tfin, "final_real", -1);
  gradient(C, c, m, g);      // residual c - E_Q AX
  IV rabs; iv_init(rabs); // |g| enclosure
  { mpfr_t a1, a2; mpfr_init2(a1, PREC); mpfr_init2(a2, PREC); mpfr_abs(a1, g.lo, MPFR_RNDU); mpfr_abs(a2, g.hi, MPFR_RNDU); mpfr_max(rabs.hi, a1, a2, MPFR_RNDU);
    if (mpfr_sgn(g.lo) <= 0 && mpfr_sgn(g.hi) >= 0) mpfr_set_ui(rabs.lo, 0, MPFR_RNDD); else { mpfr_abs(a1, g.lo, MPFR_RNDD); mpfr_abs(a2, g.hi, MPFR_RNDD); mpfr_min(rabs.lo, a1, a2, MPFR_RNDD); } mpfr_clear(a1); mpfr_clear(a2); }
  { char buf[96]; snprintf(buf, sizeof buf, "final|residual_abs<=%.3e|q0_hw<=%.1e", mpfr_get_d(rabs.hi, MPFR_RNDU), mpfr_get_d(q0.hi, MPFR_RNDU) - mpfr_get_d(q0.lo, MPFR_RNDD)); PROG.line("final_real", n, PASS_NO, PASSES_TOTAL, -1, -1, buf); }
  json += "\"final\":{\"q0\":" + iv_json(q0) + ",\"residual\":" + iv_json(g) + ",\"residual_abs\":" + iv_json(rabs) + ",\"wall_s\":" + std::to_string(tf.wall()) + ",\"cpu_s\":" + std::to_string(tf.cpu()) + "},";
  // ---- Fourier (mode F)
  if (mode == "F") {
    PhaseTimer tF("fourier");
    mpq_t hq; mpq_init(hq); mpq_set_str(hq, freqh.c_str(), 10); mpq_canonicalize(hq);
    IV hI; iv_init(hI); iv_set_q(hI, hq);
    // prefactor h/sqrt(2 pi)
    IV pi2, pref, two; iv_init(pi2); iv_init(pref); iv_init(two); iv_set_ui(two, 2);
    mpfr_const_pi(pi2.lo, MPFR_RNDD); mpfr_const_pi(pi2.hi, MPFR_RNDU); iv_mul_pos(pi2, pi2, two); iv_sqrt_pos(pi2, pi2); iv_div_pos(pref, hI, pi2);
    // zero frequency: phi_+(0) = q0, phi_-(0) = 1 - q0 (exact relation), weight 1, no phase
    IV accP, accM, one, qm; iv_init(accP); iv_init(accM); iv_init(one); iv_init(qm); iv_set_ui(one, 1); iv_sub(qm, one, q0);
    iv_set(accP, q0); iv_set(accM, qm);
    std::string freqs = "[";
    CV phip, phim, ph, prod; cv_init(phip); cv_init(phim); cv_init(ph); cv_init(prod);
    IV w, wsq, wt, ang, cI; iv_init(w); iv_init(wsq); iv_init(wt); iv_init(ang); iv_init(cI); mpfr_set(cI.lo, c, MPFR_RNDD); mpfr_set(cI.hi, c, MPFR_RNDU);
    for (long k = 1; k <= J; k++) {
      iv_set_ui(w, (unsigned long)k); iv_mul_pos(w, w, hI);                       // w = k h
      mpfr_t serr; mpfr_init2(serr, PREC);
      complex_pass(C, up, um, sexp, Tfin, w, phip, phim, k, "fourier", serr);
      // weight 2 e^{-w^2/2} (conjugate pair), phase e^{-i w c}
      iv_mul_pos(wsq, w, w); mpfr_div_2ui(wsq.lo, wsq.lo, 1, MPFR_RNDD); mpfr_div_2ui(wsq.hi, wsq.hi, 1, MPFR_RNDU); iv_neg(wsq, wsq); iv_exp(wt, wsq); iv_mul_pos(wt, wt, two);
      iv_mul(ang, w, cI); iv_neg(ang, ang); iv_cos_sin(ph.re, ph.im, ang);
      cv_mul(prod, phip, ph); iv_mul(prod.re, prod.re, wt); iv_add(accP, accP, prod.re);
      cv_mul(prod, phim, ph); iv_mul(prod.re, prod.re, wt); iv_add(accM, accM, prod.re);
      freqs += std::string(k > 1 ? "," : "") + "{\"k\":" + std::to_string(k) + ",\"w\":" + iv_json(w) + ",\"phi_plus\":" + cv_json(phip) + ",\"phi_minus\":" + cv_json(phim) + ",\"weight2\":" + iv_json(wt) + ",\"propagated_relative_error_s\":\"" + mpfr_exact(serr) + "\"}";
      mpfr_clear(serr);
      PROG.line("fourier", n, PASS_NO, PASSES_TOTAL, -1, k, "freq_done");
    }
    iv_mul(accP, accP, pref); iv_mul(accM, accM, pref);
    json += "\"fourier\":{\"h\":\"" + freqh + "\",\"J\":" + std::to_string(J) + ",\"prefactor\":" + iv_json(pref) + ",\"frequencies\":" + freqs + "],\"Ghat_plus\":" + iv_json(accP) + ",\"Ghat_minus\":" + iv_json(accM) + ",\"wall_s\":" + std::to_string(tF.wall()) + ",\"cpu_s\":" + std::to_string(tF.cpu()) + "},";
    mpq_clear(hq);
  }
  json += "\"passes\":" + std::to_string(PASS_NO) + ",\"total_wall_s\":" + std::to_string(mono_now() - W0) + ",\"total_cpu_s\":" + std::to_string(cpu_now() - C0) + "\n}\n";
  FILE* fo = fopen(outpath, "w"); if (!fo) { fprintf(stderr, "cannot write output\n"); return 4; } fputs(json.c_str(), fo); fclose(fo);
  PROG.line("done", n, PASS_NO, PASSES_TOTAL, -1, -1, "ok"); PROG.close();
  return 0;
}
