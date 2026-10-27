// dqcheck — INDEPENDENT CHECKER numerical kernel for the direct chain-query pilot.
// Shares with the producer ONLY the declared primitives mpiv.hpp (directed MPFR intervals) and dqinput.hpp (exact-input parser) and the
// progress helper.  Everything numerical is written separately and in the OPPOSITE sweep order:
//   * real pass: BACKWARD messages beta first (stored), then a forward sweep that forms every marginal from alpha_i beta_i on the fly;
//     scaling by exact powers of two chosen from the beta messages (not the producer's alpha exponents);
//   * complex pass: BACKWARD complex messages from site n-1 to 0, marker applied at site 0:  phi_s(w) = v_0(s) [M c_1]_s / T_real;
//     point messages with ONE rigorously propagated relative error scalar against the exact backward real chain (amendments/NUMERICAL_PROOF_REPAIR.md; c_r = 16).
// Inputs: canonical input, exact centre "m*2^e", frequency spacing h (rational) and J.  Output: its own enclosures of q0, residual, phi_k.
// Usage: dqcheck INPUT OUT.json --center STR --fbits F [--freq-h p/q --J J --progress PATH]
#include "mpiv.hpp"
#include "dqinput.hpp"
#include "dqcommon.hpp"

static Progress PROG; static long PASS_NO = 0, PASSES_TOTAL = 0;

static bool parse_dyadic(mpfr_t out, const std::string& s) {
  size_t p = s.find("*2^"); if (p == std::string::npos) return false;
  mpz_t m; mpz_init(m); if (mpz_set_str(m, s.substr(0, p).c_str(), 10) != 0) { mpz_clear(m); return false; }
  long e = atol(s.substr(p + 3).c_str()); mpfr_set_z_2exp(out, m, e, MPFR_RNDN); mpz_clear(m); return true;
}

struct Site { IV h, a; };

int main(int argc, char** argv) {
  if (argc < 3) return 2;
  const char* inpath = argv[1]; const char* outpath = argv[2];
  std::string cstr; long fbits = 128, J = 0; std::string freqh = "1"; const char* progress = nullptr;
  for (int i = 3; i < argc; i++) { std::string k = argv[i]; if (k == "--center") cstr = argv[++i]; else if (k == "--fbits") fbits = atol(argv[++i]); else if (k == "--freq-h") freqh = argv[++i]; else if (k == "--J") J = atol(argv[++i]); else if (k == "--progress") progress = argv[++i]; else return 2; }
  PREC = fbits + 16; if (progress) PROG.open(progress);
  double W0 = mono_now(), C0 = cpu_now();
  Input in; std::string err; if (!read_input(inpath, in, err)) { fprintf(stderr, "INPUT_PARSE_FAILED: %s\n", err.c_str()); return 3; }
  long n = in.n; PASSES_TOTAL = 1 + J;
  mpfr_t c; mpfr_init2(c, PREC); if (!parse_dyadic(c, cstr)) { fprintf(stderr, "bad centre\n"); return 2; }
  // check the centre is on the 2^-64 grid exactly
  { mpfr_t t; mpfr_init2(t, PREC); mpfr_mul_2ui(t, c, 64, MPFR_RNDN); if (!mpfr_integer_p(t)) { fprintf(stderr, "centre not on the 2^-64 grid\n"); return 5; } mpfr_clear(t); }
  std::vector<IV> h(n), a(n), f(n - 1), wp(n), wm(n);          // unary weights w_x = exp(x(h_i - a_i c)), pins -> 0
  std::vector<int> pin(n, 0); for (auto& kv : in.pins) pin[kv.first] = kv.second;
  IV cI, t, e; iv_init(cI); iv_init(t); iv_init(e); mpfr_set(cI.lo, c, MPFR_RNDD); mpfr_set(cI.hi, c, MPFR_RNDU);
  for (long i = 0; i < n; i++) { iv_init(h[i]); iv_init(a[i]); iv_init(wp[i]); iv_init(wm[i]); iv_set_q(h[i], &in.h[i]); iv_set_q(a[i], &in.a[i]);
    iv_mul(t, a[i], cI); iv_sub(t, h[i], t); iv_exp(e, t); iv_set(wp[i], e); iv_inv_pos(wm[i], e); if (pin[i] == -1) iv_set_ui(wp[i], 0); if (pin[i] == 1) iv_set_ui(wm[i], 0); }
  for (long i = 0; i < n - 1; i++) { iv_init(f[i]); iv_set_q(f[i], &in.f[i]); }
  // ---- backward real messages: b_i(x) = sum_{x'} K_i(x,x') w_{i+1}(x') b_{i+1}(x'), b_{n-1} = 1; stored, scaled by 2^{-g_i}
  PhaseTimer tr("real"); PASS_NO++;
  std::vector<IV> bp(n), bm(n); std::vector<long> gexp(n, 0); for (long i = 0; i < n; i++) { iv_init(bp[i]); iv_init(bm[i]); }
  iv_set_ui(bp[n - 1], 1); iv_set_ui(bm[n - 1], 1);
  IV t1, t2, t3, t4; iv_init(t1); iv_init(t2); iv_init(t3); iv_init(t4);
  auto exp2of = [&](const IV& x, const IV& y) { mpfr_t s; mpfr_init2(s, PREC); mpfr_add(s, x.hi, y.hi, MPFR_RNDU); long ex = mpfr_zero_p(s) ? 0 : (long)mpfr_get_exp(s); mpfr_clear(s); return ex; };
  auto sc2 = [&](IV& x, long ex) { mpfr_mul_2si(x.lo, x.lo, ex, MPFR_RNDD); mpfr_mul_2si(x.hi, x.hi, ex, MPFR_RNDU); };
  for (long i = n - 2; i >= 0; i--) {
    iv_mul_pos(t1, wp[i + 1], bp[i + 1]); iv_mul_pos(t2, wm[i + 1], bm[i + 1]);          // t1 = w(+)b(+), t2 = w(-)b(-)
    iv_mul_pos(t3, t1, f[i]); iv_add(bp[i], t3, t2);                                       // b_i(+) = f t1 + t2
    iv_mul_pos(t4, t2, f[i]); iv_add(bm[i], t1, t4);                                       // b_i(-) = t1 + f t2
    long ex = exp2of(bp[i], bm[i]); sc2(bp[i], -ex); sc2(bm[i], -ex); gexp[i] = ex;
    if ((i & 4095) == 0) PROG.line("check_real", i, PASS_NO, PASSES_TOTAL, -1, -1, "bwd");
  }
  // T_real (scaled total) = sum_x w_0(x) b_0(x) * 2^{-g_0 adjustments}: with the complex chain scaled identically this cancels; keep T = w0.b0
  IV T; iv_init(T); iv_mul_pos(t1, wp[0], bp[0]); iv_mul_pos(t2, wm[0], bm[0]); iv_add(T, t1, t2);
  IV q0; iv_init(q0); iv_div_pos(q0, t1, T);
  // forward sweep for marginals and residual: alpha_i(x) = w_i(x) sum_{x'} alpha_{i-1}(x') K_{i-1}(x', x)
  IV ap, am, nap, nam, Pp, Pm, den, mi, acc; iv_init(ap); iv_init(am); iv_init(nap); iv_init(nam); iv_init(Pp); iv_init(Pm); iv_init(den); iv_init(mi); iv_init(acc); iv_set_ui(acc, 0);
  iv_set(ap, wp[0]); iv_set(am, wm[0]);
  for (long i = 0; i < n; i++) {
    if (i > 0) { iv_mul_pos(t1, ap, f[i - 1]); iv_add(t1, t1, am); iv_mul_pos(nap, wp[i], t1); iv_mul_pos(t2, am, f[i - 1]); iv_add(t2, t2, ap); iv_mul_pos(nam, wm[i], t2); long ex = exp2of(nap, nam); sc2(nap, -ex); sc2(nam, -ex); iv_set(ap, nap); iv_set(am, nam); }
    iv_mul_pos(Pp, ap, bp[i]); iv_mul_pos(Pm, am, bm[i]); iv_add(den, Pp, Pm); iv_div_pos(Pp, Pp, den); iv_div_pos(Pm, Pm, den); iv_sub(mi, Pp, Pm);
    iv_mul(t3, a[i], mi); iv_add(acc, acc, t3);
    if ((i & 4095) == 0) PROG.line("check_real", i, PASS_NO, PASSES_TOTAL, -1, -1, "fwd");
  }
  IV resid, rabs; iv_init(resid); iv_init(rabs); iv_sub(resid, cI, acc);
  { mpfr_t a1, a2; mpfr_init2(a1, PREC); mpfr_init2(a2, PREC); mpfr_abs(a1, resid.lo, MPFR_RNDU); mpfr_abs(a2, resid.hi, MPFR_RNDU); mpfr_max(rabs.hi, a1, a2, MPFR_RNDU);
    if (mpfr_sgn(resid.lo) <= 0 && mpfr_sgn(resid.hi) >= 0) mpfr_set_ui(rabs.lo, 0, MPFR_RNDD); else { mpfr_abs(a1, resid.lo, MPFR_RNDD); mpfr_abs(a2, resid.hi, MPFR_RNDD); mpfr_min(rabs.lo, a1, a2, MPFR_RNDD); } mpfr_clear(a1); mpfr_clear(a2); }
  std::string json = "{\n\"checker\":\"dqcheck\",\"n\":" + std::to_string(n) + ",\"fbits\":" + std::to_string(fbits) + ",\"mpfr_prec\":" + std::to_string(PREC) + ",\"center\":\"" + mpfr_exact(c) + "\",";
  json += "\"q0\":" + iv_json(q0) + ",\"residual\":" + iv_json(resid) + ",\"residual_abs\":" + iv_json(rabs) + ",\"phase_real\":{\"wall_s\":" + std::to_string(tr.wall()) + ",\"cpu_s\":" + std::to_string(tr.cpu()) + "},";
  // ---- complex backward passes
  if (J > 0) {
    PhaseTimer tF("complex");
    mpq_t hq; mpq_init(hq); mpq_set_str(hq, freqh.c_str(), 10); mpq_canonicalize(hq); IV hI; iv_init(hI); iv_set_q(hI, hq);
    std::string freqs = "[";
    mpfr_t eps; mpfr_init2(eps, PREC); mpfr_set_ui(eps, 1, MPFR_RNDU); mpfr_div_2ui(eps, eps, PREC, MPFR_RNDU);
    for (long k = 1; k <= J; k++) {
      PASS_NO++;
      IV w; iv_init(w); iv_set_ui(w, (unsigned long)k); iv_mul_pos(w, w, hI);
      // point backward complex messages d_i(x) (re, im) and error scalar s with |d_hat - d| <= s * b_i (exact real backward message, same scaling)
      mpfr_t dp_re, dp_im, dm_re, dm_im, np_re, np_im, nm_re, nm_im, fbar, ubp, ubm, ang, cs, sn, vp_re, vp_im, vm_re, vm_im, x1, x2, x3, x4, s, du, de, dD, df, inc, tmp, one_s;
      mpfr_t* all[] = {&dp_re,&dp_im,&dm_re,&dm_im,&np_re,&np_im,&nm_re,&nm_im,&fbar,&ubp,&ubm,&ang,&cs,&sn,&vp_re,&vp_im,&vm_re,&vm_im,&x1,&x2,&x3,&x4,&s,&du,&de,&dD,&df,&inc,&tmp,&one_s};
      for (auto p : all) mpfr_init2(*p, PREC);
      IV angI; iv_init(angI);
      auto relhw = [&](mpfr_t out, const IV& x) { mpfr_sub(out, x.hi, x.lo, MPFR_RNDU); mpfr_div_2ui(out, out, 1, MPFR_RNDU); mpfr_div(out, out, x.lo, MPFR_RNDU); };
      auto mid = [&](mpfr_t out, const IV& x) { mpfr_add(out, x.lo, x.hi, MPFR_RNDN); mpfr_div_2ui(out, out, 1, MPFR_RNDN); };
      auto setup = [&](long i) {   // v_i(x) point values and the local perturbation bound dD (amendment 1, eq. 1); dM handled by caller per edge
        mid(ubp, wp[i]); mid(ubm, wm[i]); iv_mul(angI, w, a[i]); mid(ang, angI); mpfr_cos(cs, ang, MPFR_RNDN); mpfr_sin(sn, ang, MPFR_RNDN);
        mpfr_mul(vp_re, ubp, cs, MPFR_RNDN); mpfr_mul(vp_im, ubp, sn, MPFR_RNDN); mpfr_mul(vm_re, ubm, cs, MPFR_RNDN); mpfr_mul(vm_im, ubm, sn, MPFR_RNDN); mpfr_neg(vm_im, vm_im, MPFR_RNDN);
        mpfr_set_ui(du, 0, MPFR_RNDU); if (mpfr_sgn(wp[i].lo) > 0) { relhw(tmp, wp[i]); mpfr_max(du, du, tmp, MPFR_RNDU); } if (mpfr_sgn(wm[i].lo) > 0) { relhw(tmp, wm[i]); mpfr_max(du, du, tmp, MPFR_RNDU); }
        mpfr_t A, B, Cc; mpfr_init2(A, PREC); mpfr_init2(B, PREC); mpfr_init2(Cc, PREC);
        mpfr_add_ui(tmp, du, 1, MPFR_RNDU); mpfr_mul(A, tmp, eps, MPFR_RNDU); mpfr_add(A, A, du, MPFR_RNDU);
        mpfr_sub(de, angI.hi, angI.lo, MPFR_RNDU); mpfr_div_2ui(de, de, 1, MPFR_RNDU); mpfr_abs(tmp, ang, MPFR_RNDU); mpfr_mul(tmp, tmp, eps, MPFR_RNDU); mpfr_add(de, de, tmp, MPFR_RNDU);
        mpfr_mul_2ui(B, de, 1, MPFR_RNDU); mpfr_mul_2ui(tmp, eps, 1, MPFR_RNDU); mpfr_add(B, B, tmp, MPFR_RNDU);
        mpfr_add_ui(tmp, du, 1, MPFR_RNDU); mpfr_mul(Cc, tmp, eps, MPFR_RNDU); mpfr_mul_2ui(Cc, Cc, 1, MPFR_RNDU); mpfr_add_ui(tmp, eps, 1, MPFR_RNDU); mpfr_mul(Cc, Cc, tmp, MPFR_RNDU);
        mpfr_add(dD, A, B, MPFR_RNDU); mpfr_add(dD, dD, Cc, MPFR_RNDU);
        mpfr_clear(A); mpfr_clear(B); mpfr_clear(Cc);
      };
      auto cmul = [&](mpfr_t rre, mpfr_t rim, mpfr_t are, mpfr_t aim, mpfr_t bre, mpfr_t bim) { mpfr_mul(x1, are, bre, MPFR_RNDN); mpfr_mul(x2, aim, bim, MPFR_RNDN); mpfr_mul(x3, are, bim, MPFR_RNDN); mpfr_mul(x4, aim, bre, MPFR_RNDN); mpfr_sub(rre, x1, x2, MPFR_RNDN); mpfr_add(rim, x3, x4, MPFR_RNDN); };
      // d_{n-1} = 1 (no unary at the last site in the backward recursion: it is applied when stepping)
      mpfr_set_ui(dp_re, 1, MPFR_RNDN); mpfr_set_ui(dp_im, 0, MPFR_RNDN); mpfr_set_ui(dm_re, 1, MPFR_RNDN); mpfr_set_ui(dm_im, 0, MPFR_RNDN); mpfr_set_ui(s, 0, MPFR_RNDU);
      for (long i = n - 2; i >= 0; i--) {
        setup(i + 1); mid(fbar, f[i]); relhw(df, f[i]); mpfr_add_ui(tmp, df, 1, MPFR_RNDU); mpfr_mul(tmp, tmp, eps, MPFR_RNDU); mpfr_add(df, df, tmp, MPFR_RNDU);     // dM = df + eps(1+df)
        // y(x') = v_{i+1}(x') d_{i+1}(x') ; d_i(+) = f y(+) + y(-) ; d_i(-) = y(+) + f y(-)
        cmul(np_re, np_im, vp_re, vp_im, dp_re, dp_im);        // y(+)
        cmul(nm_re, nm_im, vm_re, vm_im, dm_re, dm_im);        // y(-)
        mpfr_mul(x1, fbar, np_re, MPFR_RNDN); mpfr_add(dp_re, x1, nm_re, MPFR_RNDN); mpfr_mul(x1, fbar, np_im, MPFR_RNDN); mpfr_add(dp_im, x1, nm_im, MPFR_RNDN);
        mpfr_mul(x1, fbar, nm_re, MPFR_RNDN); mpfr_add(dm_re, np_re, x1, MPFR_RNDN); mpfr_mul(x1, fbar, nm_im, MPFR_RNDN); mpfr_add(dm_im, np_im, x1, MPFR_RNDN);
        mpfr_mul_2si(dp_re, dp_re, -gexp[i], MPFR_RNDN); mpfr_mul_2si(dp_im, dp_im, -gexp[i], MPFR_RNDN); mpfr_mul_2si(dm_re, dm_re, -gexp[i], MPFR_RNDN); mpfr_mul_2si(dm_im, dm_im, -gexp[i], MPFR_RNDN);
        // s_i = s + (1+s)[ dM(1+dD) + dD + 16 eps (1+dD)(1+dM) ]   (amendment 1, eq. 4; c_r = 16)
        mpfr_add_ui(tmp, dD, 1, MPFR_RNDU); mpfr_mul(inc, df, tmp, MPFR_RNDU); mpfr_add(inc, inc, dD, MPFR_RNDU);
        mpfr_add_ui(one_s, df, 1, MPFR_RNDU); mpfr_mul(one_s, one_s, tmp, MPFR_RNDU); mpfr_mul_ui(one_s, one_s, 16, MPFR_RNDU); mpfr_mul(one_s, one_s, eps, MPFR_RNDU); mpfr_add(inc, inc, one_s, MPFR_RNDU);
        mpfr_add_ui(one_s, s, 1, MPFR_RNDU); mpfr_mul(one_s, one_s, inc, MPFR_RNDU); mpfr_add(s, s, one_s, MPFR_RNDU);
        if ((i & 4095) == 0) PROG.line("check_complex", i, PASS_NO, PASSES_TOTAL, -1, k, "bwd");
      }
      // marker at site 0: phi_+ = v_0(+) d_0(+) / T ; phi_- = v_0(-) d_0(-) / T, with |error| <= (s + dD_0 (1+s) + 4 eps(1+..)) * w_0(x) b_0(x)
      setup(0);
      CV php, phm; cv_init(php); cv_init(phm);
      auto finish = [&](CV& out, mpfr_t vre, mpfr_t vim, mpfr_t dre, mpfr_t dim, const IV& wb) {
        cmul(x1, x2, vre, vim, dre, dim);
        mpfr_t rad, mag; mpfr_init2(rad, PREC); mpfr_init2(mag, PREC);
        // relative error of v_0 d_0: (1+dD)(1+s)(1+4eps) - 1  <= dD + s + dD s + 4 eps (1+dD)(1+s)
        mpfr_add_ui(mag, dD, 1, MPFR_RNDU); mpfr_add_ui(tmp, s, 1, MPFR_RNDU); mpfr_mul(mag, mag, tmp, MPFR_RNDU); mpfr_mul_ui(tmp, eps, 4, MPFR_RNDU); mpfr_add_ui(tmp, tmp, 1, MPFR_RNDU); mpfr_mul(mag, mag, tmp, MPFR_RNDU); mpfr_sub_ui(mag, mag, 1, MPFR_RNDU);
        mpfr_mul(rad, mag, wb.hi, MPFR_RNDU);                     // absolute error <= rel * |w_0 b_0| (exact real product's upper bound)
        IV num; iv_init(num); mpfr_sub(num.lo, x1, rad, MPFR_RNDD); mpfr_add(num.hi, x1, rad, MPFR_RNDU); iv_div_pos(out.re, num, T);
        mpfr_sub(num.lo, x2, rad, MPFR_RNDD); mpfr_add(num.hi, x2, rad, MPFR_RNDU); iv_div_pos(out.im, num, T); iv_clear(num); mpfr_clear(rad); mpfr_clear(mag);
      };
      IV wb0p, wb0m; iv_init(wb0p); iv_init(wb0m); iv_mul_pos(wb0p, wp[0], bp[0]); iv_mul_pos(wb0m, wm[0], bm[0]);
      finish(php, vp_re, vp_im, dp_re, dp_im, wb0p); finish(phm, vm_re, vm_im, dm_re, dm_im, wb0m);
      freqs += std::string(k > 1 ? "," : "") + "{\"k\":" + std::to_string(k) + ",\"w\":" + iv_json(w) + ",\"phi_plus\":" + cv_json(php) + ",\"phi_minus\":" + cv_json(phm) + ",\"propagated_relative_error_s\":\"" + mpfr_exact(s) + "\"}";
      for (auto p : all) mpfr_clear(*p); iv_clear(angI); iv_clear(w); cv_clear(php); cv_clear(phm); iv_clear(wb0p); iv_clear(wb0m);
      PROG.line("check_complex", 0, PASS_NO, PASSES_TOTAL, -1, k, "freq_done");
    }
    json += "\"complex\":{\"h\":\"" + freqh + "\",\"J\":" + std::to_string(J) + ",\"frequencies\":" + freqs + "],\"wall_s\":" + std::to_string(tF.wall()) + ",\"cpu_s\":" + std::to_string(tF.cpu()) + "},";
    mpq_clear(hq); mpfr_clear(eps);
  }
  json += "\"passes\":" + std::to_string(PASS_NO) + ",\"total_wall_s\":" + std::to_string(mono_now() - W0) + ",\"total_cpu_s\":" + std::to_string(cpu_now() - C0) + "\n}\n";
  FILE* fo = fopen(outpath, "w"); if (!fo) return 4; fputs(json.c_str(), fo); fclose(fo); PROG.close();
  return 0;
}
