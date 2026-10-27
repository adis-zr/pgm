// nfcheck.cpp — INDEPENDENT CHECKER positive-real kernel for the normalization-free diagnostic (CLAUDE_CODE_SPEC.md v1), default 192 bits.
// Fresh implementation; shares only mpiv.hpp primitives + the exact input format with the producer. Opposite sweep order: the checker STORES
// the backward messages and sweeps FORWARD computing F on the fly, marginals, spin means, gradient, the geometric-free finite-path s bound
// (as a backward-then-forward pair in the other order), and the binary-chain covariance/regression moment identity of MOMENT_CHECKER_NOTE.md:
//   v_j = 4 p_j (1−p_j) over the whole p_j interval (max 1/4·4 = 1 when it contains 1/2), ∩[0,1]
//   suffix-only rows W_s(t) = f_j(s,t) u_{j+1}(t) B_{j+1}(t);  e_s = (W_s(+)−W_s(−))/(W_s(+)+W_s(−));  b_j = (e_+ − e_−)/2 ∩ [0, τ_j]
//   w_0 = 0; trace_j = ||a_j||² v_j + 2 a_j·w_j; w_{j+1} = b_j (w_j + a_j v_j);  M = Σ trace_j + ||A m − c||²
// Pins: exact mean, v_j = 0, w_j = 0 at a pinned site; b_j = 0 if the next site is pinned.
#include <cstdio>
#include <unistd.h>
#include <cstdlib>
#include <string>
#include <vector>
#include <fstream>
#include <sstream>
#include <chrono>
#include <gmp.h>
#include <mpfr.h>
#include "mpiv.hpp"

static long g_ops = 0, g_exp = 0;
#define OP(x) do { ++g_ops; x; } while (0)
static double now_s() { static auto t0 = std::chrono::steady_clock::now(); return std::chrono::duration<double>(std::chrono::steady_clock::now() - t0).count(); }
static void die(const std::string& m) { fprintf(stderr, "nfcheck: %s\n", m.c_str()); exit(2); }
static void chk() { if (mpfr_nanflag_p() || mpfr_overflow_p() || mpfr_underflow_p() || mpfr_erangeflag_p() || mpfr_divby0_p()) die("MPFR exceptional flag"); }

struct Site { mpq_t h; std::vector<__mpq_struct> a; int pin; };
struct Model { long n; int r; long query; std::vector<Site> s; std::vector<__mpq_struct> f; std::string id; };
static void qset(mpq_t q, const std::string& s) { mpq_init(q); if (mpq_set_str(q, s.c_str(), 10) != 0) die("bad rational " + s); mpq_canonicalize(q); }
static void parse_number(mpq_t q, const std::string& s) {
  size_t k = s.find("*2^"); if (k == std::string::npos) { qset(q, s); return; }
  mpz_t m; mpz_init(m); if (mpz_set_str(m, s.substr(0, k).c_str(), 10) != 0) die("bad dyadic"); long e = atol(s.c_str() + k + 3);
  mpq_init(q); mpq_set_z(q, m); if (e >= 0) mpq_mul_2exp(q, q, e); else mpq_div_2exp(q, q, -e); mpz_clear(m);
}
// Independent generator (written separately from the producer's; the Python side regenerates a third time and hashes the canonical form)
static void gen(Model& M, long n, long query) {
  if (n != 262144) die("generator bound to n=262144"); M.n = n; M.r = 5; M.query = query; M.id = "NF_WALSH5_MAIN_V1"; M.s.resize(n); M.f.resize(n - 1);
  mpq_t inc; mpq_init(inc);
  for (long i = 0; i < n; i++) { Site& S = M.s[i]; S.pin = 0; S.a.resize(5); mpq_init(S.h);
    mpq_set_ui(inc, (unsigned long)(i + 1), 1000UL * (unsigned long)(n + 1)); mpq_canonicalize(inc); mpq_set_ui(S.h, 1, 4); mpq_add(S.h, S.h, inc);
    unsigned long d = (unsigned long)(i >> 1);
    for (int l = 0; l < 5; l++) { mpq_init(&S.a[l]); long sgn = 1; if (l > 0 && ((d >> (17 - l)) & 1UL)) sgn = -1; mpq_set_si(&S.a[l], sgn, 1024); } }
  for (long i = 0; i < n - 1; i++) { mpq_init(&M.f[i]); if (i & 1) mpq_set_ui(&M.f[i], 11, 9); else mpq_set_ui(&M.f[i], 9, 1); }
  mpq_clear(inc);
}
static void read_file(Model& M, const char* path) {
  std::ifstream in(path); if (!in) die(std::string("cannot open ") + path); std::string tag; in >> tag; if (tag != "NFCHAIN-V1") die("bad header"); in >> M.id >> M.n >> M.r >> M.query;
  if (M.n < 1 || M.r < 1 || M.query < 0 || M.query >= M.n) die("bad dims"); M.s.resize(M.n); M.f.resize(M.n - 1);
  for (long i = 0; i < M.n; i++) { long idx; in >> idx; if (idx != i) die("site idx"); std::string hs; in >> hs; qset(M.s[i].h, hs); M.s[i].a.resize(M.r);
    for (int l = 0; l < M.r; l++) { std::string as; in >> as; mpq_t q; qset(q, as); mpq_init(&M.s[i].a[l]); mpq_set(&M.s[i].a[l], q); mpq_clear(q); } in >> M.s[i].pin; if (M.s[i].pin < -1 || M.s[i].pin > 1) die("pin"); }
  for (long i = 0; i < M.n - 1; i++) { std::string e; long idx; in >> e >> idx; if (e != "e" || idx != i) die("edge idx"); std::string fs; in >> fs; mpq_t q; qset(q, fs); if (mpq_sgn(q) <= 0) die("f<=0"); mpq_init(&M.f[i]); mpq_set(&M.f[i], q); mpq_clear(q); }
  if (!in) die("truncated");
}
struct Msg { IV v[2]; }; static void minit(Msg& m) { iv_init(m.v[0]); iv_init(m.v[1]); }
static void scale2(Msg& m, const int* allowed) {
  mpfr_exp_t e = 0; bool any = false; for (int s = 0; s < 2; s++) if (allowed[s]) { if (!iv_pos(m.v[s])) die("non-positive allowed message"); mpfr_exp_t es = mpfr_get_exp(m.v[s].hi); if (!any || es > e) { e = es; any = true; } }
  long sh = 1 - (long)e; if (!sh) return; for (int s = 0; s < 2; s++) { mpfr_mul_2si(m.v[s].lo, m.v[s].lo, sh, MPFR_RNDD); mpfr_mul_2si(m.v[s].hi, m.v[s].hi, sh, MPFR_RNDU); }
}
static void iv_zero(IV& a) { mpfr_set_zero(a.lo, 1); mpfr_set_zero(a.hi, 1); }

int main(int argc, char** argv) {
  now_s(); long prec = 192, n = 0, query = -1; std::string g, file, out, progress; std::vector<std::string> cen; bool moments = false, allm = false; std::string dump;
  for (int i = 1; i < argc; i++) { std::string a = argv[i];
    if (a == "--prec") prec = atol(argv[++i]); else if (a == "--gen") g = argv[++i]; else if (a == "--n") n = atol(argv[++i]); else if (a == "--query") query = atol(argv[++i]);
    else if (a == "--file") file = argv[++i]; else if (a == "--out") out = argv[++i]; else if (a == "--progress") progress = argv[++i]; else if (a == "--moments") moments = true; else if (a == "--all-marginals") allm = true; else if (a == "--dump") dump = argv[++i];
    else if (a == "--center") { std::string v = argv[++i]; size_t p0 = 0; while (true) { size_t k = v.find(',', p0); cen.push_back(v.substr(p0, k == std::string::npos ? std::string::npos : k - p0)); if (k == std::string::npos) break; p0 = k + 1; } } else die("unknown arg " + a); }
  if (prec < 64 || prec > 4096) die("bad prec"); PREC = prec; mpfr_clear_flags();
  Model M; if (!g.empty()) { if (g != "NF_WALSH5_MAIN_V1") die("unknown generator"); gen(M, n, query); } else if (!file.empty()) read_file(M, file.c_str()); else die("need input");
  if (M.query < 0 || M.query >= M.n) die("query out of range");
  if (!dump.empty()) { FILE* f = fopen(dump.c_str(), "w"); if (!f) die("dump"); fprintf(f, "NFCHAIN-V1 %s %ld %d %ld\n", M.id.c_str(), M.n, M.r, M.query);
    for (long i = 0; i < M.n; i++) { char* hs = mpq_get_str(nullptr, 10, M.s[i].h); fprintf(f, "%ld %s", i, hs); free(hs); for (int l = 0; l < M.r; l++) { char* as = mpq_get_str(nullptr, 10, &M.s[i].a[l]); fprintf(f, " %s", as); free(as); } fprintf(f, " %d\n", M.s[i].pin); }
    for (long i = 0; i < M.n - 1; i++) { char* fs = mpq_get_str(nullptr, 10, &M.f[i]); fprintf(f, "e %ld %s\n", i, fs); free(fs); } fflush(f); fsync(fileno(f)); fclose(f); if (cen.empty()) return 0; }
  if ((int)cen.size() != M.r) die("center dim");
  const long nn = M.n; const int r = M.r;
  std::vector<__mpq_struct> c(r); for (int l = 0; l < r; l++) { mpq_t q; parse_number(q, cen[l]); mpq_init(&c[l]); mpq_set(&c[l], q); mpq_clear(q); }
  { mpq_t s, t; mpq_init(s); mpq_init(t); for (int l = 0; l < r; l++) { mpq_mul(t, &c[l], &c[l]); mpq_add(s, s, t); } mpq_set_ui(t, 66049, 1); if (mpq_cmp(s, t) > 0) die("center norm > 257"); mpq_clear(s); mpq_clear(t); }
  FILE* pf = progress.empty() ? nullptr : fopen(progress.c_str(), "a");
  auto prog = [&](const char* st, const char* ps, long k, const char* w) { if (!pf) return; fprintf(pf, "{\"kernel\":\"nfcheck\",\"stage\":\"%s\",\"pass\":\"%s\",\"sites\":%ld,\"prec\":%ld,\"elapsed_s\":%.3f,\"last_width\":%s}\n", st, ps, k, prec, now_s(), w); fflush(pf); };
  // fields: θ_i = h_i − a_i·(c + s_E); pinned: working loading 0, unary = indicator
  std::vector<__mpq_struct> cs(r); for (int l = 0; l < r; l++) { mpq_init(&cs[l]); mpq_set(&cs[l], &c[l]); }
  for (long i = 0; i < nn; i++) if (M.s[i].pin) for (int l = 0; l < r; l++) { mpq_t t; mpq_init(t); mpq_set(t, &M.s[i].a[l]); if (M.s[i].pin < 0) mpq_neg(t, t); mpq_add(&cs[l], &cs[l], t); mpq_clear(t); }
  std::vector<Msg> U(nn); std::vector<int> allowed(2 * nn, 1); std::vector<IV> asq(nn); mpq_t th, t2, two; mpq_init(th); mpq_init(t2); mpq_init(two); mpq_set_ui(two, 2, 1);
  for (long i = 0; i < nn; i++) { minit(U[i]); iv_init(asq[i]); iv_set_ui(asq[i], 0);
    if (M.s[i].pin) { int bad = M.s[i].pin > 0 ? 0 : 1; allowed[2 * i + bad] = 0; iv_set_ui(U[i].v[1 - bad], 1); iv_zero(U[i].v[bad]); for (int l = 0; l < r; l++) mpq_set_ui(&M.s[i].a[l], 0, 1); continue; }
    mpq_set(th, M.s[i].h); for (int l = 0; l < r; l++) { mpq_mul(t2, &M.s[i].a[l], &cs[l]); mpq_sub(th, th, t2); } mpq_abs(t2, th); if (mpq_cmp(t2, two) >= 0) die("|theta| >= 2 at site " + std::to_string(i));
    IV x; iv_init(x); iv_set_q(x, th); OP(iv_exp(U[i].v[1], x)); g_exp += 2; OP(iv_inv_pos(U[i].v[0], U[i].v[1])); iv_clear(x);
    for (int l = 0; l < r; l++) { IV al, p; iv_init(al); iv_init(p); iv_set_q(al, &M.s[i].a[l]); OP(iv_mul(p, al, al)); OP(iv_add(asq[i], asq[i], p)); iv_clear(al); iv_clear(p); }
    if ((i & 16383) == 0) prog("setup", "fields", i, "\"not available\""); }
  chk();
  std::vector<IV> F(nn > 1 ? nn - 1 : 0); for (long i = 0; i + 1 < nn; i++) { iv_init(F[i]); iv_set_q(F[i], &M.f[i]); }
  // ---- stored BACKWARD messages B_i(s) = Σ_t f_i(s,t) u_{i+1}(t) B_{i+1}(t), B_{n-1} = 1
  std::vector<Msg> B(nn); IV t, t1; iv_init(t); iv_init(t1); int both[2] = {1, 1};
  for (long i = nn - 1; i >= 0; i--) { minit(B[i]);
    if (i == nn - 1) { iv_set_ui(B[i].v[0], 1); iv_set_ui(B[i].v[1], 1); }
    else for (int s = 0; s < 2; s++) { OP(iv_mul_pos(t, F[i], U[i + 1].v[s])); OP(iv_mul_pos(t, t, B[i + 1].v[s])); OP(iv_mul_pos(t1, U[i + 1].v[1 - s], B[i + 1].v[1 - s])); OP(iv_add(B[i].v[s], t, t1)); }
    scale2(B[i], both); if ((i & 16383) == 0) prog("real", "backward_store", nn - i, "\"not available\""); }
  chk();
  // ---- FORWARD sweep: F on the fly, marginal, mean, gradient, moment recursion
  Msg Fc, Fp; minit(Fc); minit(Fp);
  std::vector<IV> gr(r), Am(r), w(r); for (int l = 0; l < r; l++) { iv_init(gr[l]); iv_init(Am[l]); iv_init(w[l]); iv_set_ui(Am[l], 0); iv_set_ui(w[l], 0); }
  IV q, num, den, m, v, one, tr, bj, e0, e1, W0, W1, tmp; iv_init(q); iv_init(num); iv_init(den); iv_init(m); iv_init(v); iv_init(one); iv_init(tr); iv_init(bj); iv_init(e0); iv_init(e1); iv_init(W0); iv_init(W1); iv_init(tmp); iv_set_ui(one, 1); iv_set_ui(tr, 0);
  std::string qlo, qhi, qw = "\"not available\""; std::vector<std::string> allq;
  for (long i = 0; i < nn; i++) {
    for (int s = 0; s < 2; s++) { if (!allowed[2 * i + s]) { iv_zero(Fc.v[s]); continue; }
      if (i == 0) iv_set(Fc.v[s], U[i].v[s]); else { OP(iv_mul_pos(t, F[i - 1], Fp.v[s])); OP(iv_add(t, t, Fp.v[1 - s])); OP(iv_mul_pos(Fc.v[s], U[i].v[s], t)); } }
    scale2(Fc, &allowed[2 * i]);
    OP(iv_mul_pos(num, Fc.v[1], B[i].v[1])); OP(iv_mul_pos(t, Fc.v[0], B[i].v[0])); OP(iv_add(den, num, t)); if (!iv_pos(den)) die("denominator"); OP(iv_div_pos(q, num, den));
    if (mpfr_sgn(q.lo) < 0) mpfr_set_zero(q.lo, 1); if (mpfr_cmp_ui(q.hi, 1) > 0) mpfr_set_ui(q.hi, 1, MPFR_RNDU);
    if (M.s[i].pin) { if (M.s[i].pin > 0) iv_set_ui(q, 1); else iv_set_ui(q, 0); }
    if (i == M.query) { qlo = mpfr_exact(q.lo); qhi = mpfr_exact(q.hi); mpfr_sub(t.hi, q.hi, q.lo, MPFR_RNDU); qw = "\"" + mpfr_exact(t.hi) + "\""; }
    if (allm && nn <= 64) allq.push_back(iv_json(q));
    OP(iv_add(m, q, q)); OP(iv_sub(m, m, one));
    if (!M.s[i].pin) for (int l = 0; l < r; l++) { IV al; iv_init(al); iv_set_q(al, &M.s[i].a[l]); OP(iv_mul(t, al, m)); OP(iv_add(Am[l], Am[l], t)); iv_clear(al); }
    if (moments) {
      // v_i = 4 p (1−p) over the whole interval, ∩[0,1]
      if (M.s[i].pin) iv_set_ui(v, 0); else {
        IV pl, ph, vl, vh; iv_init(pl); iv_init(ph); iv_init(vl); iv_init(vh); mpfr_set(pl.lo, q.lo, MPFR_RNDD); mpfr_set(pl.hi, q.lo, MPFR_RNDU); mpfr_set(ph.lo, q.hi, MPFR_RNDD); mpfr_set(ph.hi, q.hi, MPFR_RNDU);
        OP(iv_sub(t, one, pl)); OP(iv_mul(vl, pl, t)); OP(iv_sub(t, one, ph)); OP(iv_mul(vh, ph, t));
        mpfr_min(v.lo, vl.lo, vh.lo, MPFR_RNDD); mpfr_max(v.hi, vl.hi, vh.hi, MPFR_RNDU);
        if (mpfr_cmp_d(q.lo, 0.5) <= 0 && mpfr_cmp_d(q.hi, 0.5) >= 0) mpfr_set_d(v.hi, 0.25, MPFR_RNDU);     // interior maximum of p(1−p)
        OP(iv_add(v, v, v)); OP(iv_add(v, v, v)); if (mpfr_sgn(v.lo) < 0) mpfr_set_zero(v.lo, 1); if (mpfr_cmp_ui(v.hi, 1) > 0) mpfr_set_ui(v.hi, 1, MPFR_RNDU); iv_clear(pl); iv_clear(ph); iv_clear(vl); iv_clear(vh); }
      if (M.s[i].pin) for (int l = 0; l < r; l++) iv_set_ui(w[l], 0);
      // trace_i = ||a_i||² v_i + 2 a_i·w_i   (before updating w)
      OP(iv_mul(t, asq[i], v)); OP(iv_add(tr, tr, t));
      for (int l = 0; l < r; l++) { IV al; iv_init(al); iv_set_q(al, &M.s[i].a[l]); OP(iv_mul(t, al, w[l])); OP(iv_add(tr, tr, t)); OP(iv_add(tr, tr, t)); iv_clear(al); }
      if (i + 1 < nn) {
        if (M.s[i + 1].pin) iv_set_ui(bj, 0); else {
          // suffix-only conditional rows: W_s(t) = f_i(s,t) u_{i+1}(t) B_{i+1}(t)
          for (int s = 0; s < 2; s++) { IV& Wsame = (s == 1) ? W1 : W0; IV& Wother = (s == 1) ? W0 : W1;
            OP(iv_mul_pos(Wsame, F[i], U[i + 1].v[s])); OP(iv_mul_pos(Wsame, Wsame, B[i + 1].v[s])); OP(iv_mul_pos(Wother, U[i + 1].v[1 - s], B[i + 1].v[1 - s]));
            // e_s = (W_s(+) − W_s(−)) / (W_s(+) + W_s(−)) with W_s(+) = row entry at t=+1
            IV& Wp = (s == 1) ? W1 : W1; IV& Wm = (s == 1) ? W0 : W0; (void)Wp; (void)Wm;
            IV wp, wm; iv_init(wp); iv_init(wm); if (s == 1) { iv_set(wp, Wsame); iv_set(wm, Wother); } else { iv_set(wp, Wother); iv_set(wm, Wsame); }
            OP(iv_sub(num, wp, wm)); OP(iv_add(den, wp, wm)); if (!iv_pos(den)) die("row denominator"); OP(iv_div_pos(s == 1 ? e1 : e0, num, den)); iv_clear(wp); iv_clear(wm); }
          OP(iv_sub(bj, e1, e0)); mpfr_div_2ui(bj.lo, bj.lo, 1, MPFR_RNDD); mpfr_div_2ui(bj.hi, bj.hi, 1, MPFR_RNDU);
          // ∩ [0, τ_i], τ_i = |f_i − 1| / (f_i + 1)
          IV d, sm, tau; iv_init(d); iv_init(sm); iv_init(tau); OP(iv_sub(d, F[i], one)); if (mpfr_sgn(d.lo) < 0) { IV nd; iv_init(nd); iv_neg(nd, d); if (mpfr_sgn(d.hi) > 0) { mpfr_set_zero(d.lo, 1); if (mpfr_cmp(nd.hi, d.hi) > 0) mpfr_set(d.hi, nd.hi, MPFR_RNDU); } else iv_set(d, nd); iv_clear(nd); }
          OP(iv_add(sm, F[i], one)); OP(iv_div_pos(tau, d, sm));
          if (mpfr_sgn(bj.lo) < 0) mpfr_set_zero(bj.lo, 1); if (mpfr_cmp(bj.hi, tau.hi) > 0) mpfr_set(bj.hi, tau.hi, MPFR_RNDU); if (mpfr_cmp(bj.lo, bj.hi) > 0) die("empty b_j ∩ [0,tau] intersection (checking failure)");
          iv_clear(d); iv_clear(sm); iv_clear(tau); }
        // w_{i+1} = b_i (w_i + a_i v_i)
        for (int l = 0; l < r; l++) { IV al; iv_init(al); iv_set_q(al, &M.s[i].a[l]); OP(iv_mul(t, al, v)); OP(iv_add(t, w[l], t)); OP(iv_mul(w[l], bj, t)); iv_clear(al); } }
    }
    for (int s = 0; s < 2; s++) iv_set(Fp.v[s], Fc.v[s]);
    if ((i & 16383) == 0) prog("real", "forward_sweep", i, qw.c_str());
  }
  chk();
  for (int l = 0; l < r; l++) { IV cl; iv_init(cl); iv_set_q(cl, &c[l]); OP(iv_sub(gr[l], cl, Am[l])); iv_clear(cl); if (!iv_finite(gr[l])) die("gradient"); }
  // s_query: forward-first order (L from left in a separate pass, R from right), independent code path
  std::vector<IV> alpha(nn); for (long i = 0; i < nn; i++) { iv_init(alpha[i]); OP(iv_sqrt_pos(alpha[i], asq[i])); }
  IV L, R, S; iv_init(L); iv_init(R); iv_init(S); iv_set_ui(L, 0); iv_set_ui(R, 0);
  auto tau_of = [&](long i, IV& tau) { IV d, sm; iv_init(d); iv_init(sm); OP(iv_sub(d, F[i], one)); if (mpfr_sgn(d.lo) < 0) { IV nd; iv_init(nd); iv_neg(nd, d); if (mpfr_sgn(d.hi) > 0) { mpfr_set_zero(d.lo, 1); if (mpfr_cmp(nd.hi, d.hi) > 0) mpfr_set(d.hi, nd.hi, MPFR_RNDU); } else iv_set(d, nd); iv_clear(nd); } OP(iv_add(sm, F[i], one)); OP(iv_div_pos(tau, d, sm)); iv_clear(d); iv_clear(sm); };
  IV tau; iv_init(tau);
  for (long i = nn - 2; i >= M.query; i--) { tau_of(i, tau); OP(iv_add(t, alpha[i + 1], R)); OP(iv_mul_pos(R, tau, t)); }
  for (long i = 1; i <= M.query; i++) { tau_of(i - 1, tau); OP(iv_add(t, alpha[i - 1], L)); OP(iv_mul_pos(L, tau, t)); }
  OP(iv_add(S, alpha[M.query], L)); OP(iv_add(S, S, R)); chk();
  std::string Mjson = "null";
  if (moments) { IV Mv, nrm; iv_init(Mv); iv_init(nrm); iv_set_ui(nrm, 0); for (int l = 0; l < r; l++) { OP(iv_mul(t, gr[l], gr[l])); OP(iv_add(nrm, nrm, t)); }   // ||A m − c||² = ||g||²
    if (mpfr_sgn(tr.lo) < 0) mpfr_set_zero(tr.lo, 1); if (mpfr_sgn(tr.hi) < 0) die("trace covariance entirely negative"); OP(iv_add(Mv, tr, nrm)); chk(); Mjson = "{\"M\":" + iv_json(Mv) + ",\"trace_cov\":" + iv_json(tr) + ",\"mean_sq\":" + iv_json(nrm) + "}"; }
  std::ostringstream o; o << "{\"kernel\":\"nfcheck\",\"role\":\"checker\",\"prec\":" << prec << ",\"case_id\":\"" << M.id << "\",\"n\":" << nn << ",\"rank\":" << r << ",\"query_index\":" << M.query << ",\"center\":[";
  for (int l = 0; l < r; l++) { char* s = mpq_get_str(nullptr, 10, &c[l]); o << (l ? "," : "") << "\"" << s << "\""; free(s); }
  o << "],\"q_query\":[\"" << qlo << "\",\"" << qhi << "\"],\"gradient\":["; for (int l = 0; l < r; l++) o << (l ? "," : "") << iv_json(gr[l]);
  o << "],\"all_marginals\":"; if (allm) { o << "["; for (size_t k = 0; k < allq.size(); k++) o << (k ? "," : "") << allq[k]; o << "]"; } else o << "null"; o << ",\"s_query\":" << iv_json(S) << ",\"alpha_query\":" << iv_json(alpha[M.query]) << ",\"M_actual\":" << Mjson
    << ",\"counts\":{\"sites\":" << nn << ",\"real_passes\":2,\"moment_fused\":" << (moments ? "true" : "false") << ",\"exp_calls\":" << g_exp << ",\"interval_ops\":" << g_ops << "},\"mpfr_version\":\"" << mpfr_get_version() << "\",\"flags_clean\":true,\"kernel_wall_s\":" << now_s() << "}\n";
  if (out.empty()) fputs(o.str().c_str(), stdout); else { FILE* f = fopen(out.c_str(), "w"); if (!f) die("write"); fputs(o.str().c_str(), f); fflush(f); fsync(fileno(f)); fclose(f); }
  prog("done", "output", nn, qw.c_str()); if (pf) fclose(pf); return 0;
}
