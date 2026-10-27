// nfchain.cpp — PRODUCER positive-real kernel for the normalization-free certificate clearance diagnostic (CLAUDE_CODE_SPEC.md v1).
// Fresh code for this diagnostic (26/27 Oct 2026). Shares only mpiv.hpp (standard directed MPFR interval primitives + exact serialisation).
// Does NOT reuse the complex direct-query kernel, its proof, or its |c|<=64 domain.
//
//   nfchain --prec 128 (--gen NF_WALSH5_MAIN_V1 --n 262144 --query 131072 | --file NFCHAIN-V1-path) --center c0 [c1 ...]
//           --out result.json [--progress progress.txt] [--moments]
//
// Residual law Q_c(x) ∝ Π_i f_i^{[x_i=x_{i+1}]} · exp(Σ_i θ_i x_i),  θ_i = h_i − a_i·c  (exact mpq, |θ_i| < 2 enforced, ||c||² ≤ 257² enforced).
// Unary weights u_i(+1)=exp(θ_i) (directed), u_i(−1)=1/u_i(+1) (outward reciprocal).  Pinned site: allowed state only, unary 1 / exact 0,
// working loading 0, free fields shifted by −a_j·s_E with s_E = Σ_pinned a_i x_i (exact).  Forward F_i(s)=u_i(s)Σ_t f_{i-1}(t,s)F_{i-1}(t);
// backward B_i(s)=Σ_t f_i(s,t)u_{i+1}(t)B_{i+1}(t); q_i = F_i(+)B_i(+)/(F_i(+)B_i(+)+F_i(−)B_i(−)); common exact power-of-two scaling only.
// Gradient g = c − Σ_i a_i m_i (signed interval accumulation), m_i = 2q_i − 1.  s_query by the nonnegative finite-path recurrence
// L_i = τ_{i-1}(α_{i-1}+L_{i-1}), R_i = τ_i(α_{i+1}+R_{i+1}), s = α+L+R, τ = |f−1|/(f+1).  --moments: centred vector/scalar moment transfer
// (MOMENT_CHECKER_NOTE.md producer recurrence) giving M = E_Q||A_F X_F − c||².
#include <cstdio>
#include <unistd.h>
#include <cstdlib>
#include <cstring>
#include <string>
#include <vector>
#include <fstream>
#include <sstream>
#include <chrono>
#include <gmp.h>
#include <mpfr.h>
#include "mpiv.hpp"

static long g_ops = 0, g_exp = 0, g_inv = 0;
#define OP(x) do { ++g_ops; x; } while (0)
static double now_s() { static auto t0 = std::chrono::steady_clock::now(); return std::chrono::duration<double>(std::chrono::steady_clock::now() - t0).count(); }
static void die(const std::string& m) { fprintf(stderr, "nfchain: %s\n", m.c_str()); exit(2); }

struct Site { mpq_t h; std::vector<__mpq_struct> a; int pin; };   // pin: 0 free, +1 / -1 pinned
struct Model { long n; int r; long query; std::vector<Site> s; std::vector<__mpq_struct> f; std::string id; };

static void q_init_set_str(mpq_t q, const std::string& s) { mpq_init(q); if (mpq_set_str(q, s.c_str(), 10) != 0) die("bad rational '" + s + "'"); mpq_canonicalize(q); }

// exact dyadic "m*2^e" or rational "p/q" → mpq
static void parse_number(mpq_t q, const std::string& s) {
  size_t k = s.find("*2^");
  if (k == std::string::npos) { q_init_set_str(q, s); return; }
  mpz_t m; mpz_init(m); if (mpz_set_str(m, s.substr(0, k).c_str(), 10) != 0) die("bad dyadic " + s); long e = atol(s.c_str() + k + 3);
  mpq_init(q); mpq_set_z(q, m); if (e >= 0) mpq_mul_2exp(q, q, e); else mpq_div_2exp(q, q, -e); mpz_clear(m);
}

static void gen_walsh5(Model& M, long n, long query) {
  if (n != 262144) die("generator NF_WALSH5_MAIN_V1 is bound to n = 262144");
  M.n = n; M.r = 5; M.query = query; M.id = "NF_WALSH5_MAIN_V1"; M.s.resize(n); M.f.resize(n - 1);
  for (long i = 0; i < n; i++) {
    Site& S = M.s[i]; S.pin = 0; S.a.resize(5);
    mpq_init(S.h); mpq_set_ui(S.h, 1, 4); mpq_t t; mpq_init(t); mpq_set_ui(t, (unsigned long)(i + 1), 1000UL * (unsigned long)(n + 1)); mpq_canonicalize(t); mpq_add(S.h, S.h, t); mpq_clear(t);
    long d = i / 2;
    for (int l = 0; l < 5; l++) { mpq_init(&S.a[l]); int neg = (l == 0) ? 0 : (int)((d >> (17 - l)) & 1); mpq_set_si(&S.a[l], neg ? -1 : 1, 1024); }
  }
  for (long i = 0; i < n - 1; i++) { mpq_init(&M.f[i]); if (i % 2 == 0) mpq_set_ui(&M.f[i], 9, 1); else mpq_set_ui(&M.f[i], 11, 9); }
}

// NFCHAIN-V1: line1 "NFCHAIN-V1 id n r query"; then n lines "i h a0 .. a_{r-1} pin"; then n-1 lines "e i f"
static void read_file(Model& M, const char* path) {
  std::ifstream in(path); if (!in) die(std::string("cannot open ") + path);
  std::string tag; in >> tag; if (tag != "NFCHAIN-V1") die("bad header"); in >> M.id >> M.n >> M.r >> M.query;
  if (M.n < 1 || M.r < 1 || M.query < 0 || M.query >= M.n) die("bad dimensions");
  M.s.resize(M.n); M.f.resize(M.n - 1);
  for (long i = 0; i < M.n; i++) {
    long idx; in >> idx; if (idx != i) die("site index mismatch"); std::string hs; in >> hs; q_init_set_str(M.s[i].h, hs); M.s[i].a.resize(M.r);
    for (int l = 0; l < M.r; l++) { std::string as; in >> as; mpq_t q; q_init_set_str(q, as); mpq_init(&M.s[i].a[l]); mpq_set(&M.s[i].a[l], q); mpq_clear(q); }
    in >> M.s[i].pin; if (M.s[i].pin != 0 && M.s[i].pin != 1 && M.s[i].pin != -1) die("bad pin");
  }
  for (long i = 0; i < M.n - 1; i++) { std::string e; long idx; in >> e >> idx; if (e != "e" || idx != i) die("edge index mismatch"); std::string fs; in >> fs; mpq_t q; q_init_set_str(q, fs); if (mpq_sgn(q) <= 0) die("edge factor must be positive"); mpq_init(&M.f[i]); mpq_set(&M.f[i], q); mpq_clear(q); }
  if (!in) die("truncated input");
}

struct Msg { IV v[2]; };   // state index 0 ↔ x=−1, 1 ↔ x=+1
static void msg_init(Msg& m) { iv_init(m.v[0]); iv_init(m.v[1]); }

static bool iv_ok(const IV& a) { return iv_finite(a); }
static void check_flags(const char* where) {
  if (mpfr_nanflag_p() || mpfr_overflow_p() || mpfr_underflow_p() || mpfr_erangeflag_p() || mpfr_divby0_p()) die(std::string("MPFR exceptional flag raised in ") + where);
}
// common exact power-of-two scaling: bring max upper endpoint of the allowed states into [1,2)
static void scale_msg(Msg& m, const int* allowed, std::vector<IV*> extra) {
  mpfr_exp_t e = 0; bool any = false;
  for (int s = 0; s < 2; s++) if (allowed[s]) { if (!iv_pos(m.v[s])) die("non-positive message for an allowed state"); mpfr_exp_t es = mpfr_get_exp(m.v[s].hi); if (!any || es > e) { e = es; any = true; } }
  if (!any) die("no allowed state");
  long sh = 1 - (long)e; if (sh == 0) return;
  for (int s = 0; s < 2; s++) { mpfr_mul_2si(m.v[s].lo, m.v[s].lo, sh, MPFR_RNDD); mpfr_mul_2si(m.v[s].hi, m.v[s].hi, sh, MPFR_RNDU); }
  for (IV* x : extra) { mpfr_mul_2si(x->lo, x->lo, sh, MPFR_RNDD); mpfr_mul_2si(x->hi, x->hi, sh, MPFR_RNDU); }
}

int main(int argc, char** argv) {
  long prec = 128, n = 0, query = -1; std::string gen, file, out, progress; std::vector<std::string> center; bool moments = false, moments_only = false, allm = false; std::string dump;
  for (int i = 1; i < argc; i++) {
    std::string a = argv[i];
    if (a == "--prec") prec = atol(argv[++i]); else if (a == "--gen") gen = argv[++i]; else if (a == "--n") n = atol(argv[++i]); else if (a == "--query") query = atol(argv[++i]);
    else if (a == "--file") file = argv[++i]; else if (a == "--out") out = argv[++i]; else if (a == "--progress") progress = argv[++i]; else if (a == "--moments") moments = true; else if (a == "--moments-only") { moments = true; moments_only = true; } else if (a == "--all-marginals") allm = true; else if (a == "--dump") dump = argv[++i];
    else if (a == "--center") { std::string v = argv[++i]; size_t p0 = 0; while (true) { size_t k = v.find(',', p0); center.push_back(v.substr(p0, k == std::string::npos ? std::string::npos : k - p0)); if (k == std::string::npos) break; p0 = k + 1; } }
    else die("unknown argument " + a);
  }
  now_s();
  if (prec < 64 || prec > 4096) die("bad precision"); PREC = prec; mpfr_clear_flags();
  Model M;
  if (!gen.empty()) { if (gen != "NF_WALSH5_MAIN_V1") die("unknown generator"); gen_walsh5(M, n, query); } else if (!file.empty()) read_file(M, file.c_str()); else die("need --gen or --file");
  if (M.query < 0 || M.query >= M.n) die("query index out of range");
  if (!dump.empty()) { // canonical NFCHAIN-V1 text of the model this kernel actually holds (for hash binding against the lock)
    FILE* f = fopen(dump.c_str(), "w"); if (!f) die("cannot write dump"); fprintf(f, "NFCHAIN-V1 %s %ld %d %ld\n", M.id.c_str(), M.n, M.r, M.query);
    for (long i = 0; i < M.n; i++) { char* hs = mpq_get_str(nullptr, 10, M.s[i].h); fprintf(f, "%ld %s", i, hs); free(hs); for (int l = 0; l < M.r; l++) { char* as = mpq_get_str(nullptr, 10, &M.s[i].a[l]); fprintf(f, " %s", as); free(as); } fprintf(f, " %d\n", M.s[i].pin); }
    for (long i = 0; i < M.n - 1; i++) { char* fs = mpq_get_str(nullptr, 10, &M.f[i]); fprintf(f, "e %ld %s\n", i, fs); free(fs); }
    fflush(f); fsync(fileno(f)); fclose(f); if (center.empty()) return 0; }
  if ((int)center.size() != M.r) die("center dimension != rank");
  std::vector<__mpq_struct> c(M.r); for (int l = 0; l < M.r; l++) { mpq_t q; parse_number(q, center[l]); mpq_init(&c[l]); mpq_set(&c[l], q); mpq_clear(q); }
  // domain: ||c||^2 <= 257^2 exactly
  { mpq_t nc, t; mpq_init(nc); mpq_init(t); for (int l = 0; l < M.r; l++) { mpq_mul(t, &c[l], &c[l]); mpq_add(nc, nc, t); } mpq_set_ui(t, 257 * 257, 1); if (mpq_cmp(nc, t) > 0) die("center norm exceeds 257"); mpq_clear(nc); mpq_clear(t); }
  const long nn = M.n; const int r = M.r;
  FILE* pf = progress.empty() ? nullptr : fopen(progress.c_str(), "a");
  auto prog = [&](const char* stage, const char* pass, long sites, const char* width) { if (!pf) return; fprintf(pf, "{\"kernel\":\"nfchain\",\"stage\":\"%s\",\"pass\":\"%s\",\"sites\":%ld,\"prec\":%ld,\"elapsed_s\":%.3f,\"last_width\":%s}\n", stage, pass, sites, prec, now_s(), width); fflush(pf); };
  prog("setup", "fields", 0, "\"not available\"");

  // exact evidence statistic s_E and tilted fields θ_i = h_i − a_i·(c + s_E) for free sites (pinned: working loading 0, field 0)
  std::vector<__mpq_struct> sE(r); for (int l = 0; l < r; l++) { mpq_init(&sE[l]); }
  for (long i = 0; i < nn; i++) if (M.s[i].pin) for (int l = 0; l < r; l++) { mpq_t t; mpq_init(t); mpq_set(t, &M.s[i].a[l]); if (M.s[i].pin < 0) mpq_neg(t, t); mpq_add(&sE[l], &sE[l], t); mpq_clear(t); }
  std::vector<__mpq_struct> cs(r); for (int l = 0; l < r; l++) { mpq_init(&cs[l]); mpq_add(&cs[l], &c[l], &sE[l]); }
  std::vector<Msg> U(nn); std::vector<int> allowed(2 * nn, 1); std::vector<IV> alpha(nn);           // unary weights, allowed states, column norms (working)
  mpq_t theta, t2, two; mpq_init(theta); mpq_init(t2); mpq_init(two); mpq_set_ui(two, 2, 1);
  for (long i = 0; i < nn; i++) {
    msg_init(U[i]); iv_init(alpha[i]);
    if (M.s[i].pin) { allowed[2 * i + (M.s[i].pin > 0 ? 0 : 1)] = 0; iv_set_ui(U[i].v[M.s[i].pin > 0 ? 1 : 0], 1); mpfr_set_zero(U[i].v[M.s[i].pin > 0 ? 0 : 1].lo, 1); mpfr_set_zero(U[i].v[M.s[i].pin > 0 ? 0 : 1].hi, 1); iv_set_ui(alpha[i], 0); for (int l = 0; l < r; l++) mpq_set_ui(&M.s[i].a[l], 0, 1); continue; }
    mpq_set(theta, M.s[i].h); for (int l = 0; l < r; l++) { mpq_mul(t2, &M.s[i].a[l], &cs[l]); mpq_sub(theta, theta, t2); }
    mpq_abs(t2, theta); if (mpq_cmp(t2, two) >= 0) die("tilted field magnitude >= 2 at site " + std::to_string(i) + " (outside the proof domain)");
    IV th; iv_init(th); iv_set_q(th, theta); OP(iv_exp(U[i].v[1], th)); g_exp += 2; OP(iv_inv_pos(U[i].v[0], U[i].v[1])); g_inv++; iv_clear(th);
    if (!iv_pos(U[i].v[1]) || !iv_pos(U[i].v[0]) || !iv_ok(U[i].v[0]) || !iv_ok(U[i].v[1])) die("bad unary weight");
    IV sq, tq; iv_init(sq); iv_init(tq); iv_set_ui(sq, 0);
    for (int l = 0; l < r; l++) { IV al; iv_init(al); iv_set_q(al, &M.s[i].a[l]); OP(iv_mul(tq, al, al)); OP(iv_add(sq, sq, tq)); iv_clear(al); }
    OP(iv_sqrt_pos(alpha[i], sq)); iv_clear(sq); iv_clear(tq);
    if ((i & 16383) == 0) prog("setup", "fields", i, "\"not available\"");
  }
  check_flags("fields");
  std::vector<IV> F(nn - 1 > 0 ? nn - 1 : 0); for (long i = 0; i < nn - 1; i++) { iv_init(F[i]); iv_set_q(F[i], &M.f[i]); }
  // ---- forward pass (stored)
  std::vector<Msg> Fw(nn); IV t, t1; iv_init(t); iv_init(t1);
  for (long i = 0; i < nn; i++) {
    msg_init(Fw[i]);
    for (int s = 0; s < 2; s++) {
      if (!allowed[2 * i + s]) { mpfr_set_zero(Fw[i].v[s].lo, 1); mpfr_set_zero(Fw[i].v[s].hi, 1); continue; }
      if (i == 0) iv_set(Fw[i].v[s], U[i].v[s]);
      else { // Σ_t f_{i-1}(t,s) F_{i-1}(t): equal state gets factor f, other gets 1
        OP(iv_mul_pos(t, F[i - 1], Fw[i - 1].v[s])); OP(iv_add(t, t, Fw[i - 1].v[1 - s])); OP(iv_mul_pos(Fw[i].v[s], U[i].v[s], t)); }
    }
    scale_msg(Fw[i], &allowed[2 * i], {});
    if ((i & 16383) == 0) prog("real", "forward", i, "\"not available\"");
  }
  check_flags("forward");
  // ---- backward pass with marginals, gradient accumulation and query
  std::vector<std::string> allq; std::string sq_json = "null";
  Msg B, Bn; msg_init(B); msg_init(Bn); iv_set_ui(B.v[0], 1); iv_set_ui(B.v[1], 1);   // B_{n-1} = 1 (empty suffix)
  std::vector<IV> g(r); for (int l = 0; l < r; l++) { iv_init(g[l]); iv_set_q(g[l], &c[l]); }
  IV qq, num, den, m2, am; iv_init(qq); iv_init(num); iv_init(den); iv_init(m2); iv_init(am); std::string q_query_lo, q_query_hi; std::string q_width = "\"not available\"";
  if (!moments_only) for (long i = nn - 1; i >= 0; i--) {
    if (i < nn - 1) { // B_i(s) = Σ_t f_i(s,t) u_{i+1}(t) B_{i+1}(t)
      for (int s = 0; s < 2; s++) { OP(iv_mul_pos(t, U[i + 1].v[s], Bn.v[s])); OP(iv_mul_pos(t, t, F[i])); OP(iv_mul_pos(t1, U[i + 1].v[1 - s], Bn.v[1 - s])); OP(iv_add(B.v[s], t, t1)); }
      int both[2] = {1, 1}; scale_msg(B, both, {});
    }
    // marginal q_i = F(+)B(+) / (F(+)B(+) + F(−)B(−))
    OP(iv_mul_pos(num, Fw[i].v[1], B.v[1])); OP(iv_mul_pos(t, Fw[i].v[0], B.v[0])); OP(iv_add(den, num, t));
    if (!iv_pos(den)) die("non-positive marginal denominator"); OP(iv_div_pos(qq, num, den));
    if (mpfr_sgn(qq.lo) < 0) mpfr_set_zero(qq.lo, 1); if (mpfr_cmp_ui(qq.hi, 1) > 0) mpfr_set_ui(qq.hi, 1, MPFR_RNDU);   // clip to [0,1] (valid for a probability)
    if (M.s[i].pin) { if (M.s[i].pin > 0) iv_set_ui(qq, 1); else iv_set_ui(qq, 0); }
    if (i == M.query) { q_query_lo = mpfr_exact(qq.lo); q_query_hi = mpfr_exact(qq.hi); mpfr_sub(t.hi, qq.hi, qq.lo, MPFR_RNDU); q_width = "\"" + mpfr_exact(t.hi) + "\""; }
    if (allm && nn <= 64) allq.insert(allq.begin(), iv_json(qq));
    // m = 2q − 1 ; g_l −= a_l m
    OP(iv_add(m2, qq, qq)); IV one; iv_init(one); iv_set_ui(one, 1); OP(iv_sub(m2, m2, one)); iv_clear(one);
    if (!M.s[i].pin) for (int l = 0; l < r; l++) { IV al; iv_init(al); iv_set_q(al, &M.s[i].a[l]); OP(iv_mul(am, al, m2)); OP(iv_sub(g[l], g[l], am)); iv_clear(al); }
    for (int s = 0; s < 2; s++) iv_set(Bn.v[s], B.v[s]);
    if ((i & 16383) == 0) prog("real", "backward", nn - i, q_width.c_str());
  }
  check_flags("backward");
  if (!moments_only) for (int l = 0; l < r; l++) if (!iv_ok(g[l])) die("gradient component not finite/ordered");
  // ---- s_query by the nonnegative finite-path recurrence (τ_i = |f_i−1|/(f_i+1), outward)
  std::vector<IV> tau(nn - 1 > 0 ? nn - 1 : 0);
  for (long i = 0; i < nn - 1; i++) { iv_init(tau[i]); IV one, d, s; iv_init(one); iv_init(d); iv_init(s); iv_set_ui(one, 1); OP(iv_sub(d, F[i], one)); if (mpfr_sgn(d.lo) < 0) { IV nd; iv_init(nd); iv_neg(nd, d); if (mpfr_sgn(d.hi) > 0) { mpfr_set_zero(d.lo, 1); if (mpfr_cmp(nd.hi, d.hi) > 0) mpfr_set(d.hi, nd.hi, MPFR_RNDU); } else iv_set(d, nd); iv_clear(nd); } OP(iv_add(s, F[i], one)); OP(iv_div_pos(tau[i], d, s)); iv_clear(one); iv_clear(d); iv_clear(s); }
  IV L, R, sq; iv_init(L); iv_init(R); iv_init(sq); iv_set_ui(L, 0); iv_set_ui(R, 0);
  if (!moments_only) { for (long i = 1; i <= M.query; i++) { OP(iv_add(t, alpha[i - 1], L)); OP(iv_mul_pos(L, tau[i - 1], t)); }
  for (long i = nn - 2; i >= M.query; i--) { OP(iv_add(t, alpha[i + 1], R)); OP(iv_mul_pos(R, tau[i], t)); }
  OP(iv_add(sq, alpha[M.query], L)); OP(iv_add(sq, sq, R)); sq_json = iv_json(sq); }
  check_flags("s_query");
  // ---- optional centred moment transfer (producer recurrence of MOMENT_CHECKER_NOTE.md)
  std::string Mjson = "null"; long moment_sites = 0;
  if (moments) {
    Msg Fm, Tm; msg_init(Fm); msg_init(Tm); std::vector<Msg> Um(r); for (int l = 0; l < r; l++) msg_init(Um[l]);
    // dummy empty-path state (single state, index 1): F=1, U=−c, T=||c||²
    IV Fd, Td; iv_init(Fd); iv_init(Td); iv_set_ui(Fd, 1); iv_set_ui(Td, 0); std::vector<IV> Ud(r);
    for (int l = 0; l < r; l++) { iv_init(Ud[l]); IV cl; iv_init(cl); iv_set_q(cl, &c[l]); iv_neg(Ud[l], cl); OP(iv_mul(t, cl, cl)); OP(iv_add(Td, Td, t)); iv_clear(cl); }
    IV Fb, Tb, dot, asq; iv_init(Fb); iv_init(Tb); iv_init(dot); iv_init(asq); std::vector<IV> Ub(r); for (int l = 0; l < r; l++) iv_init(Ub[l]);
    for (long i = 0; i < nn; i++) {
      Msg Fn, Tn; msg_init(Fn); msg_init(Tn); std::vector<Msg> Un(r); for (int l = 0; l < r; l++) msg_init(Un[l]);
      for (int s = 0; s < 2; s++) {
        if (!allowed[2 * i + s]) { mpfr_set_zero(Fn.v[s].lo, 1); mpfr_set_zero(Fn.v[s].hi, 1); mpfr_set_zero(Tn.v[s].lo, 1); mpfr_set_zero(Tn.v[s].hi, 1); for (int l = 0; l < r; l++) { mpfr_set_zero(Un[l].v[s].lo, 1); mpfr_set_zero(Un[l].v[s].hi, 1); } continue; }
        if (i == 0) { iv_set(Fb, Fd); iv_set(Tb, Td); for (int l = 0; l < r; l++) iv_set(Ub[l], Ud[l]); }
        else { OP(iv_mul_pos(Fb, F[i - 1], Fm.v[s])); OP(iv_add(Fb, Fb, Fm.v[1 - s])); OP(iv_mul(Tb, F[i - 1], Tm.v[s])); OP(iv_add(Tb, Tb, Tm.v[1 - s]));
               for (int l = 0; l < r; l++) { OP(iv_mul(Ub[l], F[i - 1], Um[l].v[s])); OP(iv_add(Ub[l], Ub[l], Um[l].v[1 - s])); } }
        double x = (s == 1) ? 1.0 : -1.0;
        OP(iv_mul_pos(Fn.v[s], U[i].v[s], Fb));
        iv_set_ui(dot, 0); iv_set_ui(asq, 0);
        for (int l = 0; l < r; l++) { IV al, xa; iv_init(al); iv_init(xa); iv_set_q(al, &M.s[i].a[l]); if (x < 0) iv_neg(xa, al); else iv_set(xa, al);
          OP(iv_mul(t, xa, Ub[l])); OP(iv_add(dot, dot, t)); OP(iv_mul(t, al, al)); OP(iv_add(asq, asq, t));
          OP(iv_mul(t, xa, Fb)); OP(iv_add(t, Ub[l], t)); OP(iv_mul(Un[l].v[s], U[i].v[s], t)); iv_clear(al); iv_clear(xa); }
        OP(iv_add(t, dot, dot)); OP(iv_add(t, Tb, t)); OP(iv_mul(t1, asq, Fb)); OP(iv_add(t, t, t1)); OP(iv_mul(Tn.v[s], U[i].v[s], t));
      }
      std::vector<IV*> extra; for (int s = 0; s < 2; s++) { extra.push_back(&Tn.v[s]); for (int l = 0; l < r; l++) extra.push_back(&Un[l].v[s]); }
      scale_msg(Fn, &allowed[2 * i], extra);
      for (int s = 0; s < 2; s++) { iv_set(Fm.v[s], Fn.v[s]); iv_set(Tm.v[s], Tn.v[s]); for (int l = 0; l < r; l++) iv_set(Um[l].v[s], Un[l].v[s]); }
      moment_sites++;
      if ((i & 16383) == 0) prog("moments", "centred_transfer", i, "\"not available\"");
    }
    IV Ts, Fs, Mv; iv_init(Ts); iv_init(Fs); iv_init(Mv); OP(iv_add(Ts, Tm.v[0], Tm.v[1])); OP(iv_add(Fs, Fm.v[0], Fm.v[1])); if (!iv_pos(Fs)) die("non-positive total mass"); OP(iv_div_pos(Mv, Ts, Fs));
    if (mpfr_sgn(Mv.hi) < 0) die("moment interval entirely negative (empty intersection with [0,inf))"); if (mpfr_sgn(Mv.lo) < 0) mpfr_set_zero(Mv.lo, 1);
    check_flags("moments"); Mjson = iv_json(Mv);
  }
  // ---- output
  std::ostringstream o; o << "{\"kernel\":\"nfchain\",\"role\":\"producer\",\"prec\":" << prec << ",\"case_id\":\"" << M.id << "\",\"n\":" << nn << ",\"rank\":" << r << ",\"query_index\":" << M.query
    << ",\"center\":["; for (int l = 0; l < r; l++) { char* s = mpq_get_str(nullptr, 10, &c[l]); o << (l ? "," : "") << "\"" << s << "\""; free(s); }
  o << "],\"q_query\":" << (moments_only ? std::string("null") : "[\"" + q_query_lo + "\",\"" + q_query_hi + "\"]") << ",\"gradient\":"; if (moments_only) o << "null"; else { o << "["; for (int l = 0; l < r; l++) o << (l ? "," : "") << iv_json(g[l]); o << "]"; }
  o << ",\"all_marginals\":"; if (allm && !moments_only) { o << "["; for (size_t k = 0; k < allq.size(); k++) o << (k ? "," : "") << allq[k]; o << "]"; } else o << "null";
  o << ",\"s_query\":" << sq_json << ",\"alpha_query\":" << iv_json(alpha[M.query]) << ",\"M_actual\":" << Mjson
    << ",\"counts\":{\"sites\":" << nn << ",\"real_passes\":" << (moments_only ? 0 : 2) << ",\"moment_pass_sites\":" << moment_sites << ",\"exp_calls\":" << g_exp << ",\"reciprocals\":" << g_inv << ",\"interval_ops\":" << g_ops << "}"
    << ",\"mpfr_version\":\"" << mpfr_get_version() << "\",\"gmp_version\":\"" << gmp_version << "\",\"flags_clean\":true,\"kernel_wall_s\":" << now_s() << "}\n";
  if (out.empty()) fputs(o.str().c_str(), stdout); else { FILE* f = fopen(out.c_str(), "w"); if (!f) die("cannot write output"); fputs(o.str().c_str(), f); fflush(f); fsync(fileno(f)); fclose(f); }
  prog("done", "output", nn, q_width.c_str()); if (pf) fclose(pf);
  return 0;
}
