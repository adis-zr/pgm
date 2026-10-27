// h4rect.cpp — CACHED RECTANGULAR INTERVAL kernel: arm C's producer (256-bit) and the common interval checker (320-bit).
// Same mathematical object as the point kernel: normalized joint marker channels and the weighted Fourier response, via the
// SAME stochastic FFBS recurrence (eq. 1-2) but with directed MPFR rectangular complex intervals instead of binary64 points.
// Phases/weights arrive as certified MPFR interval endpoints (exact "m*2^e" dyadics) in a source-independent cache that is
// constructed once per cold bundle and reused across both source signs; rows are per node/sign.
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <string>
#include <vector>
#include <chrono>
#include <unistd.h>
#include <gmp.h>
#include <mpfr.h>

static mpfr_prec_t PREC = 256;
static double now_s() { static auto t0 = std::chrono::steady_clock::now(); return std::chrono::duration<double>(std::chrono::steady_clock::now() - t0).count(); }
static void die(const char* m) { fprintf(stderr, "h4rect: %s\n", m); exit(2); }

struct IV { mpfr_t lo, hi; };
static void iv_init(IV& a) { mpfr_init2(a.lo, PREC); mpfr_init2(a.hi, PREC); mpfr_set_zero(a.lo, 1); mpfr_set_zero(a.hi, 1); }
static void iv_set(IV& r, const IV& a) { mpfr_set(r.lo, a.lo, MPFR_RNDD); mpfr_set(r.hi, a.hi, MPFR_RNDU); }
static void iv_add(IV& r, const IV& a, const IV& b) { mpfr_t t; mpfr_init2(t, PREC); mpfr_add(t, a.lo, b.lo, MPFR_RNDD); mpfr_add(r.hi, a.hi, b.hi, MPFR_RNDU); mpfr_set(r.lo, t, MPFR_RNDD); mpfr_clear(t); }
static void iv_sub(IV& r, const IV& a, const IV& b) { mpfr_t t; mpfr_init2(t, PREC); mpfr_sub(t, a.lo, b.hi, MPFR_RNDD); mpfr_sub(r.hi, a.hi, b.lo, MPFR_RNDU); mpfr_set(r.lo, t, MPFR_RNDD); mpfr_clear(t); }
static void iv_mul(IV& r, const IV& a, const IV& b) {
  mpfr_t p[4], q[4]; for (int i = 0; i < 4; i++) { mpfr_init2(p[i], PREC); mpfr_init2(q[i], PREC); }
  mpfr_mul(p[0], a.lo, b.lo, MPFR_RNDD); mpfr_mul(p[1], a.lo, b.hi, MPFR_RNDD); mpfr_mul(p[2], a.hi, b.lo, MPFR_RNDD); mpfr_mul(p[3], a.hi, b.hi, MPFR_RNDD);
  mpfr_mul(q[0], a.lo, b.lo, MPFR_RNDU); mpfr_mul(q[1], a.lo, b.hi, MPFR_RNDU); mpfr_mul(q[2], a.hi, b.lo, MPFR_RNDU); mpfr_mul(q[3], a.hi, b.hi, MPFR_RNDU);
  mpfr_set(r.lo, p[0], MPFR_RNDD); for (int i = 1; i < 4; i++) if (mpfr_cmp(p[i], r.lo) < 0) mpfr_set(r.lo, p[i], MPFR_RNDD);
  mpfr_set(r.hi, q[0], MPFR_RNDU); for (int i = 1; i < 4; i++) if (mpfr_cmp(q[i], r.hi) > 0) mpfr_set(r.hi, q[i], MPFR_RNDU);
  for (int i = 0; i < 4; i++) { mpfr_clear(p[i]); mpfr_clear(q[i]); }
}
static void iv_mul_nonneg(IV& r, const IV& a, const IV& b) { mpfr_t t; mpfr_init2(t, PREC); mpfr_mul(t, a.lo, b.lo, MPFR_RNDD); mpfr_mul(r.hi, a.hi, b.hi, MPFR_RNDU); mpfr_set(r.lo, t, MPFR_RNDD); mpfr_clear(t); }
struct CV { IV re, im; };
static void cv_init(CV& z) { iv_init(z.re); iv_init(z.im); }
// complex product (ar+i ai)(br+i bi) with rectangular outward arithmetic
static void cv_mul(CV& r, const CV& a, const CV& b) {
  IV t1, t2, t3, t4; iv_init(t1); iv_init(t2); iv_init(t3); iv_init(t4);
  iv_mul(t1, a.re, b.re); iv_mul(t2, a.im, b.im); iv_mul(t3, a.re, b.im); iv_mul(t4, a.im, b.re);
  iv_sub(r.re, t1, t2); iv_add(r.im, t3, t4);
  for (IV* p : {&t1,&t2,&t3,&t4}) { mpfr_clear(p->lo); mpfr_clear(p->hi); }
}
static void cv_scale(CV& r, const CV& a, const IV& s) { iv_mul(r.re, a.re, s); iv_mul(r.im, a.im, s); }
static void cv_add(CV& r, const CV& a, const CV& b) { iv_add(r.re, a.re, b.re); iv_add(r.im, a.im, b.im); }

// exact dyadic "m*2^e" parsing/serialisation
static void set_dyadic(mpfr_t x, const char* s, mpfr_rnd_t rnd) {
  std::string v(s); size_t k = v.find("*2^"); if (k == std::string::npos) die("bad dyadic");
  mpz_t m; mpz_init(m); if (mpz_set_str(m, v.substr(0, k).c_str(), 10) != 0) die("bad mantissa");
  long e = atol(v.c_str() + k + 3);
  mpfr_set_z(x, m, rnd); if (e >= 0) mpfr_mul_2si(x, x, e, rnd); else mpfr_div_2si(x, x, -e, rnd);
  mpz_clear(m);
}
static std::string mpfr_exact(const mpfr_t x) {
  if (mpfr_zero_p(x)) return "0*2^0";
  mpz_t m; mpz_init(m); mpfr_exp_t e = mpfr_get_z_2exp(m, x);
  char* s = mpz_get_str(nullptr, 10, m); std::string out = std::string(s) + "*2^" + std::to_string((long)e);
  free(s); mpz_clear(m); return out;
}
static std::string iv_json(const IV& a) { return "[\"" + mpfr_exact(a.lo) + "\",\"" + mpfr_exact(a.hi) + "\"]"; }

int main(int argc, char** argv) {
  now_s();
  const char* in = nullptr; const char* out = nullptr; const char* prog = nullptr; long expect = -1; int fwd = 0;
  for (int i = 1; i < argc; i++) { std::string a = argv[i];
    if (a == "--in") in = argv[++i]; else if (a == "--out") out = argv[++i]; else if (a == "--prec") PREC = atol(argv[++i]);
    else if (a == "--progress") prog = argv[++i]; else if (a == "--expect-freq") expect = atol(argv[++i]); else if (a == "--forward") fwd = 1; else die("unknown arg"); }
  if (!in || !out) die("need --in/--out");
  if (PREC != 256 && PREC != 320) die("precision must be the frozen 256 (producer) or 320 (checker)");
  mpfr_set_emin(-16384); mpfr_set_emax(16384); mpfr_clear_flags();
  FILE* f = fopen(in, "r"); if (!f) die("cannot open input");
  char tag[32]; long n, q, nk, mc, prec_decl;
  if (fscanf(f, "%31s", tag) != 1 || strcmp(tag, "H4RECT-V1")) die("bad header");
  if (fscanf(f, "%ld %ld %ld %ld %ld", &n, &q, &nk, &prec_decl, &mc) != 5) die("bad header fields");
  if (n < 4 || n > 128) die("n outside domain"); if (nk < 1 || nk > 512) die("F outside domain");
  if (expect > 0 && nk != expect) die("frequency count mismatch");
  std::vector<std::vector<int>> allowed(n);
  std::vector<IV> rowp((size_t)n * 4 * 2); for (auto& v : rowp) iv_init(v);
  std::vector<char> seen_row((size_t)n * 4, 0);
  std::vector<IV> term(4); for (auto& v : term) iv_init(v);
  std::vector<CV> ph((size_t)nk * n * 2); for (auto& z : ph) cv_init(z);
  std::vector<CV> pht((size_t)nk * 4); for (auto& z : pht) cv_init(z);
  std::vector<char> seen_pht((size_t)nk * 4, 0), seen_lam(nk, 0);
  std::vector<IV> lam(nk); for (auto& v : lam) iv_init(v);
  char b1[512], b2[512], b3[512], b4[512];
  while (fscanf(f, "%31s", tag) == 1) {
    if (!strcmp(tag, "ALLOWED")) { long i, c; if (fscanf(f, "%ld %ld", &i, &c) != 2 || i < 0 || i >= n || c < 1 || c > 2) die("bad ALLOWED");
      allowed[i].clear(); for (long j = 0; j < c; j++) { long s; if (fscanf(f, "%ld", &s) != 1) die("bad spin"); allowed[i].push_back((int)s); } }
    else if (!strcmp(tag, "ROW")) { long i, ia, ib; if (fscanf(f, "%ld %ld %ld %511s %511s %511s %511s", &i, &ia, &ib, b1, b2, b3, b4) != 7) die("bad ROW");
      long nb = (long)(fwd ? allowed[i - 1].size() : allowed[i + 2].size()); long idx = ia * nb + ib; if (idx < 0 || idx >= 4) die("row ctx range");
      IV& p0 = rowp[((size_t)i * 4 + idx) * 2 + 0]; IV& p1 = rowp[((size_t)i * 4 + idx) * 2 + 1];
      set_dyadic(p0.lo, b1, MPFR_RNDD); set_dyadic(p0.hi, b2, MPFR_RNDU); set_dyadic(p1.lo, b3, MPFR_RNDD); set_dyadic(p1.hi, b4, MPFR_RNDU);
      if (mpfr_sgn(p0.lo) < 0 || mpfr_sgn(p1.lo) < 0) die("negative probability endpoint");
      seen_row[(size_t)i * 4 + idx] = 1; }
    else if (!strcmp(tag, "TERM")) { for (int s = 0; s < 4; s++) { if (fscanf(f, "%511s %511s", b1, b2) != 2) die("bad TERM");
        set_dyadic(term[s].lo, b1, MPFR_RNDD); set_dyadic(term[s].hi, b2, MPFR_RNDU); if (mpfr_sgn(term[s].lo) < 0) die("negative terminal endpoint"); } }
    else if (!strcmp(tag, "PH")) { long k, i, x; if (fscanf(f, "%ld %ld %ld %511s %511s %511s %511s", &k, &i, &x, b1, b2, b3, b4) != 7) die("bad PH");
      CV& z = ph[((size_t)k * n + i) * 2 + x];
      set_dyadic(z.re.lo, b1, MPFR_RNDD); set_dyadic(z.re.hi, b2, MPFR_RNDU); set_dyadic(z.im.lo, b3, MPFR_RNDD); set_dyadic(z.im.hi, b4, MPFR_RNDU); }
    else if (!strcmp(tag, "PHT")) { long k, a, b; if (fscanf(f, "%ld %ld %ld %511s %511s %511s %511s", &k, &a, &b, b1, b2, b3, b4) != 7) die("bad PHT");
      size_t idx = (size_t)k * 4 + a * 2 + b; CV& z = pht[idx];
      set_dyadic(z.re.lo, b1, MPFR_RNDD); set_dyadic(z.re.hi, b2, MPFR_RNDU); set_dyadic(z.im.lo, b3, MPFR_RNDD); set_dyadic(z.im.hi, b4, MPFR_RNDU); seen_pht[idx] = 1; }
    else if (!strcmp(tag, "LAM")) { long k; if (fscanf(f, "%ld %511s %511s", &k, b1, b2) != 3) die("bad LAM");
      set_dyadic(lam[k].lo, b1, MPFR_RNDD); set_dyadic(lam[k].hi, b2, MPFR_RNDU); if (mpfr_sgn(lam[k].lo) < 0) die("negative Fourier weight"); seen_lam[k] = 1; }
    else die("unknown record");
  }
  fclose(f);
  for (long k = 0; k < nk; k++) if (!seen_lam[k]) die("missing weight");
  if (!fwd) { for (long i = 0; i <= n - 3; i++) { long na = (long)allowed[i + 1].size(), nb = (long)allowed[i + 2].size();
    for (long ia = 0; ia < na; ia++) for (long ib = 0; ib < nb; ib++) if (!seen_row[(size_t)i * 4 + ia * nb + ib]) die("missing reachable row"); } }
  else { for (long i = 2; i <= n - 1; i++) { long na = (long)allowed[i - 2].size(), nb = (long)allowed[i - 1].size();
    for (long ia = 0; ia < na; ia++) for (long ib = 0; ib < nb; ib++) if (!seen_row[(size_t)i * 4 + ia * nb + ib]) die("missing reachable forward row"); } }
  FILE* pf = prog ? fopen(prog, "a") : nullptr;
  std::vector<CV> outc((size_t)nk * 2); for (auto& z : outc) cv_init(z);
  for (int mi = 0; mi < 2; mi++) {
    int msign = (mi == 0) ? -1 : 1;
    for (long k = 0; k < nk; k++) {
     if (fwd) {
      // independent opposite direction: G_n = 1; G_i(a,b) = sum_c t_i(c|a,b) phi_i(c) b_i(c) G_{i+1}(b,c)
      CV G[4]; bool Gok[4] = {false,false,false,false};
      for (int t = 0; t < 4; t++) cv_init(G[t]);
      { long i = n - 1; long na = (long)allowed[i - 2].size(), nb = (long)allowed[i - 1].size();
        for (long ia = 0; ia < na; ia++) for (long ib = 0; ib < nb; ib++) {
          long idx = ia * nb + ib; CV s; cv_init(s); bool first = true;
          for (long ic = 0; ic < (long)allowed[i].size(); ic++) {
            int c = allowed[i][ic]; if (i == q && c != msign) continue;
            IV& p = rowp[((size_t)i * 4 + idx) * 2 + (c < 0 ? 0 : 1)];
            if (mpfr_zero_p(p.lo) && mpfr_zero_p(p.hi)) continue;
            CV w; cv_init(w); cv_scale(w, ph[((size_t)k * n + i) * 2 + (c < 0 ? 0 : 1)], p);
            if (first) { iv_set(s.re, w.re); iv_set(s.im, w.im); first = false; } else cv_add(s, s, w);
            mpfr_clear(w.re.lo); mpfr_clear(w.re.hi); mpfr_clear(w.im.lo); mpfr_clear(w.im.hi);
          }
          iv_set(G[idx].re, s.re); iv_set(G[idx].im, s.im); Gok[idx] = !first;
          mpfr_clear(s.re.lo); mpfr_clear(s.re.hi); mpfr_clear(s.im.lo); mpfr_clear(s.im.hi); } }
      for (long i = n - 2; i >= 2; i--) {
        CV N[4]; bool Nok[4] = {false,false,false,false}; for (int t = 0; t < 4; t++) cv_init(N[t]);
        long na = (long)allowed[i - 2].size(), nb = (long)allowed[i - 1].size(), ncs = (long)allowed[i].size();
        for (long ia = 0; ia < na; ia++) for (long ib = 0; ib < nb; ib++) {
          long idx = ia * nb + ib; CV s; cv_init(s); bool first = true;
          for (long ic = 0; ic < ncs; ic++) {
            int c = allowed[i][ic]; if (i == q && c != msign) continue;
            IV& p = rowp[((size_t)i * 4 + idx) * 2 + (c < 0 ? 0 : 1)];
            if (mpfr_zero_p(p.lo) && mpfr_zero_p(p.hi)) continue;
            long pidx = ib * ncs + ic; if (pidx < 0 || pidx >= 4 || !Gok[pidx]) continue;
            CV z; cv_init(z); cv_mul(z, ph[((size_t)k * n + i) * 2 + (c < 0 ? 0 : 1)], G[pidx]);
            CV w; cv_init(w); cv_scale(w, z, p);
            if (first) { iv_set(s.re, w.re); iv_set(s.im, w.im); first = false; } else cv_add(s, s, w);
            for (CV* pz : {&z,&w}) { mpfr_clear(pz->re.lo); mpfr_clear(pz->re.hi); mpfr_clear(pz->im.lo); mpfr_clear(pz->im.hi); }
          }
          iv_set(N[idx].re, s.re); iv_set(N[idx].im, s.im); Nok[idx] = !first;
          mpfr_clear(s.re.lo); mpfr_clear(s.re.hi); mpfr_clear(s.im.lo); mpfr_clear(s.im.hi); }
        for (int t = 0; t < 4; t++) { iv_set(G[t].re, N[t].re); iv_set(G[t].im, N[t].im); Gok[t] = Nok[t];
          mpfr_clear(N[t].re.lo); mpfr_clear(N[t].re.hi); mpfr_clear(N[t].im.lo); mpfr_clear(N[t].im.hi); } }
      long ta = (long)allowed[0].size(), tb = (long)allowed[1].size();
      CV fsum; cv_init(fsum); bool first = true;
      for (long ia = 0; ia < ta; ia++) for (long ib = 0; ib < tb; ib++) {
        int sa = allowed[0][ia], sb = allowed[1][ib];
        long sl = (sa < 0 ? 0 : 2) + (sb < 0 ? 0 : 1);
        if (mpfr_zero_p(term[sl].lo) && mpfr_zero_p(term[sl].hi)) continue;
        if (q == 0 && sa != msign) continue;
        if (q == 1 && sb != msign) continue;
        long idx = ia * tb + ib; if (idx < 0 || idx >= 4 || !Gok[idx]) continue;
        size_t pidx = (size_t)k * 4 + (size_t)(sa < 0 ? 0 : 1) * 2 + (sb < 0 ? 0 : 1); if (!seen_pht[pidx]) die("missing initial phase");
        CV z; cv_init(z); cv_mul(z, pht[pidx], G[idx]);
        CV w; cv_init(w); cv_scale(w, z, term[sl]);
        if (first) { iv_set(fsum.re, w.re); iv_set(fsum.im, w.im); first = false; } else cv_add(fsum, fsum, w);
        for (CV* pz : {&z,&w}) { mpfr_clear(pz->re.lo); mpfr_clear(pz->re.hi); mpfr_clear(pz->im.lo); mpfr_clear(pz->im.hi); } }
      iv_set(outc[(size_t)k * 2 + mi].re, fsum.re); iv_set(outc[(size_t)k * 2 + mi].im, fsum.im);
      mpfr_clear(fsum.re.lo); mpfr_clear(fsum.re.hi); mpfr_clear(fsum.im.lo); mpfr_clear(fsum.im.hi);
      for (int t = 0; t < 4; t++) { mpfr_clear(G[t].re.lo); mpfr_clear(G[t].re.hi); mpfr_clear(G[t].im.lo); mpfr_clear(G[t].im.hi); }
      if (pf && (k % 64 == 0)) { fprintf(pf, "{\"kernel\":\"h4rect\",\"dir\":\"forward\",\"prec\":%ld,\"marker\":%d,\"freq\":%ld,\"of\":%ld,\"elapsed_s\":%.3f}\n", (long)PREC, msign, k, nk, now_s()); fflush(pf); }
      continue;
     }
      CV H[4]; bool Hok[4] = {false,false,false,false};
      for (int t = 0; t < 4; t++) cv_init(H[t]);
      long na = (long)allowed[1].size(), nb = (long)allowed[2].size();
      for (long ia = 0; ia < na; ia++) for (long ib = 0; ib < nb; ib++) {
        long idx = ia * nb + ib; CV s; cv_init(s); bool first = true;
        for (long ic = 0; ic < (long)allowed[0].size(); ic++) {
          int c = allowed[0][ic]; if (0 == q && c != msign) continue;
          IV& p = rowp[((size_t)0 * 4 + idx) * 2 + (c < 0 ? 0 : 1)];
          if (mpfr_zero_p(p.lo) && mpfr_zero_p(p.hi)) continue;
          CV w; cv_init(w); cv_scale(w, ph[((size_t)k * n + 0) * 2 + (c < 0 ? 0 : 1)], p);
          if (first) { iv_set(s.re, w.re); iv_set(s.im, w.im); first = false; } else { cv_add(s, s, w); }
          mpfr_clear(w.re.lo); mpfr_clear(w.re.hi); mpfr_clear(w.im.lo); mpfr_clear(w.im.hi);
        }
        iv_set(H[idx].re, s.re); iv_set(H[idx].im, s.im); Hok[idx] = !first;
        mpfr_clear(s.re.lo); mpfr_clear(s.re.hi); mpfr_clear(s.im.lo); mpfr_clear(s.im.hi);
      }
      for (long i = 1; i <= n - 3; i++) {
        CV N[4]; bool Nok[4] = {false,false,false,false}; for (int t = 0; t < 4; t++) cv_init(N[t]);
        long nna = (long)allowed[i + 1].size(), nnb = (long)allowed[i + 2].size();
        long pna = (long)allowed[i].size(), pnb = (long)allowed[i + 1].size();
        for (long ia = 0; ia < nna; ia++) for (long ib = 0; ib < nnb; ib++) {
          long idx = ia * nnb + ib; CV s; cv_init(s); bool first = true;
          for (long ic = 0; ic < pna; ic++) {
            int c = allowed[i][ic]; if (i == q && c != msign) continue;
            IV& p = rowp[((size_t)i * 4 + idx) * 2 + (c < 0 ? 0 : 1)];
            if (mpfr_zero_p(p.lo) && mpfr_zero_p(p.hi)) continue;
            long pidx = ic * pnb + ia; if (!Hok[pidx]) continue;
            CV z; cv_init(z); cv_mul(z, ph[((size_t)k * n + i) * 2 + (c < 0 ? 0 : 1)], H[pidx]);
            CV w; cv_init(w); cv_scale(w, z, p);
            if (first) { iv_set(s.re, w.re); iv_set(s.im, w.im); first = false; } else { cv_add(s, s, w); }
            for (CV* pz : {&z,&w}) { mpfr_clear(pz->re.lo); mpfr_clear(pz->re.hi); mpfr_clear(pz->im.lo); mpfr_clear(pz->im.hi); }
          }
          iv_set(N[idx].re, s.re); iv_set(N[idx].im, s.im); Nok[idx] = !first;
          mpfr_clear(s.re.lo); mpfr_clear(s.re.hi); mpfr_clear(s.im.lo); mpfr_clear(s.im.hi);
        }
        for (int t = 0; t < 4; t++) { iv_set(H[t].re, N[t].re); iv_set(H[t].im, N[t].im); Hok[t] = Nok[t];
          mpfr_clear(N[t].re.lo); mpfr_clear(N[t].re.hi); mpfr_clear(N[t].im.lo); mpfr_clear(N[t].im.hi); }
      }
      long ta = (long)allowed[n - 2].size(), tb = (long)allowed[n - 1].size();
      CV fsum; cv_init(fsum); bool first = true;
      for (long ia = 0; ia < ta; ia++) for (long ib = 0; ib < tb; ib++) {
        int sa = allowed[n - 2][ia], sb = allowed[n - 1][ib];
        long sl = (sa < 0 ? 0 : 2) + (sb < 0 ? 0 : 1);
        if (mpfr_zero_p(term[sl].lo) && mpfr_zero_p(term[sl].hi)) continue;
        if (q == n - 2 && sa != msign) continue;
        if (q == n - 1 && sb != msign) continue;
        long idx = ia * tb + ib; if (!Hok[idx]) continue;
        size_t pidx = (size_t)k * 4 + (size_t)(sa < 0 ? 0 : 1) * 2 + (sb < 0 ? 0 : 1); if (!seen_pht[pidx]) die("missing terminal phase");
        CV z; cv_init(z); cv_mul(z, pht[pidx], H[idx]);
        CV w; cv_init(w); cv_scale(w, z, term[sl]);
        if (first) { iv_set(fsum.re, w.re); iv_set(fsum.im, w.im); first = false; } else cv_add(fsum, fsum, w);
        for (CV* pz : {&z,&w}) { mpfr_clear(pz->re.lo); mpfr_clear(pz->re.hi); mpfr_clear(pz->im.lo); mpfr_clear(pz->im.hi); }
      }
      iv_set(outc[(size_t)k * 2 + mi].re, fsum.re); iv_set(outc[(size_t)k * 2 + mi].im, fsum.im);
      mpfr_clear(fsum.re.lo); mpfr_clear(fsum.re.hi); mpfr_clear(fsum.im.lo); mpfr_clear(fsum.im.hi);
      for (int t = 0; t < 4; t++) { mpfr_clear(H[t].re.lo); mpfr_clear(H[t].re.hi); mpfr_clear(H[t].im.lo); mpfr_clear(H[t].im.hi); }
      if (pf && (k % 64 == 0)) { fprintf(pf, "{\"kernel\":\"h4rect\",\"prec\":%ld,\"marker\":%d,\"freq\":%ld,\"of\":%ld,\"elapsed_s\":%.3f}\n", (long)PREC, msign, k, nk, now_s()); fflush(pf); }
    }
  }
  IV resp[2];
  for (int mi = 0; mi < 2; mi++) { iv_init(resp[mi]); bool first = true;
    for (long k = 0; k < nk; k++) { IV t; iv_init(t); iv_mul(t, lam[k], outc[(size_t)k * 2 + mi].re);
      if (first) { iv_set(resp[mi], t); first = false; } else iv_add(resp[mi], resp[mi], t);
      mpfr_clear(t.lo); mpfr_clear(t.hi); } }
  if (mpfr_nanflag_p() || mpfr_overflow_p() || mpfr_divby0_p() || mpfr_erangeflag_p()) die("MPFR exceptional flag raised");
  FILE* o = fopen(out, "w"); if (!o) die("cannot write output");
  fprintf(o, "{\"kernel\":\"h4rect\",\"prec\":%ld,\"n\":%ld,\"q\":%ld,\"nfreq\":%ld,\"wall_s\":%.6f,\"channels\":[", (long)PREC, n, q, nk, now_s());
  for (long k = 0; k < nk; k++) for (int mi = 0; mi < 2; mi++) {
    if (k || mi) fprintf(o, ",");
    fprintf(o, "{\"k\":%ld,\"marker\":%d,\"re\":%s,\"im\":%s}", k, mi == 0 ? -1 : 1, iv_json(outc[(size_t)k * 2 + mi].re).c_str(), iv_json(outc[(size_t)k * 2 + mi].im).c_str());
  }
  fprintf(o, "],\"response\":[{\"marker\":-1,\"iv\":%s},{\"marker\":1,\"iv\":%s}],\"mpfr_version\":\"%s\"}\n", iv_json(resp[0]).c_str(), iv_json(resp[1]).c_str(), mpfr_get_version());
  fflush(o); fsync(fileno(o)); fclose(o);
  if (pf) fclose(pf);
  return 0;
}
