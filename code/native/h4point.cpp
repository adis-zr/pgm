// h4point.cpp — POINT producer kernel (arms PI and PP), binary64 stochastic FFBS contraction.
// Implements NUMERICAL_THEOREM.md eq. (1)-(2) exactly as the analyzed instruction sequence:
//   H_{-1}=1 ; H_i(a,b) = sum_c p_i(c|a,b) phi_i(k,c) b_i(c) H_{i-1}(c,a)   i=0..n-3
//   f(k)    = sum_{a,b} r(a,b) phi_term(k,a,b) b(a) b(b) H_{n-3}(a,b)
// Per nonzero term: 4 real multiplies + 1 subtract + 1 add for the complex product, then 2 real multiplies by p;
// terms summed sequentially in declared state order (first assigned, then added). No FMA, no reassociation, no libm.
// Input: a binary witness of certified tables (ints over 2^53) and phases (ints over 2^53). Output: exact bit patterns.
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <cstdint>
#include <cmath>
#include <cfenv>
#include <cfloat>
#include <string>
#include <vector>
#include <chrono>
#include <unistd.h>

#if defined(__x86_64__)
#include <xmmintrin.h>
#endif

static double now_s() { static auto t0 = std::chrono::steady_clock::now(); return std::chrono::duration<double>(std::chrono::steady_clock::now() - t0).count(); }
static void die(const char* m) { fprintf(stderr, "h4point: %s\n", m); exit(2); }

// ---------- environment probes (IMPLEMENTATION_CONTRACT.md §2) ----------
static volatile double g_v1 = 1.0, g_vhalf = 0.5, g_v3 = 3.0;
static uint64_t bits(double x) { uint64_t u; memcpy(&u, &x, 8); return u; }
static double frombits(uint64_t u) { double x; memcpy(&x, &u, 8); return x; }
struct Probe { const char* name; uint64_t got, want; bool ok; };
static std::vector<Probe> run_probes() {
  std::vector<Probe> P;
  volatile double sub = frombits(1);                        // smallest subnormal 2^-1074
  double r1 = sub * g_v1;                   P.push_back({"subnormal_times_one", bits(r1), bits(frombits(1)), bits(r1) == 1});
  volatile double nrm = frombits(0x0010000000000000ULL);    // smallest normal 2^-1022
  double r2 = nrm * g_vhalf;                P.push_back({"smallest_normal_half", bits(r2), 0x0008000000000000ULL, bits(r2) == 0x0008000000000000ULL});
  double r3 = sub * g_vhalf;                P.push_back({"subnormal_half_to_zero", bits(r3), 0, bits(r3) == 0});
  volatile double three_sub = frombits(3);                  // 3 * 2^-1074
  double r4 = three_sub * g_vhalf;          P.push_back({"three_sub_half_ties_even", bits(r4), 2, bits(r4) == 2});
  volatile double e53 = frombits(0x3CA0000000000000ULL);    // 2^-53
  double r5 = g_v1 + e53;                   P.push_back({"one_plus_2^-53_is_one", bits(r5), bits(1.0), r5 == 1.0});
  volatile double one_p52 = frombits(0x3FF0000000000001ULL);// 1 + 2^-52
  double r6 = one_p52 + e53;                P.push_back({"1p2^-52_plus_2^-53", bits(r6), 0x3FF0000000000002ULL, bits(r6) == 0x3FF0000000000002ULL});
  volatile double a = 1.0 + ldexp(1.0, -27), b = 1.0 - ldexp(1.0, -27);
  double prod = a * b; double r7 = prod - g_v1;   P.push_back({"unfused_product_minus_one_is_zero", bits(r7), 0, r7 == 0.0});
  return P;
}
static bool env_ok(std::string& why) {
  if (FLT_RADIX != 2 || DBL_MANT_DIG != 53 || sizeof(double) != 8) { why = "binary64 format"; return false; }
  if (DBL_MIN_EXP != -1021 || DBL_MAX_EXP != 1024) { why = "exponent macros"; return false; }
#ifdef FLT_EVAL_METHOD
  if (FLT_EVAL_METHOD != 0) { why = "FLT_EVAL_METHOD != 0"; return false; }
#endif
  if (fegetround() != FE_TONEAREST) { why = "rounding mode not FE_TONEAREST"; return false; }
#if defined(__x86_64__)
  unsigned csr = _mm_getcsr(); if (csr & 0x8000) { why = "FTZ set"; return false; } if (csr & 0x0040) { why = "DAZ set"; return false; }
#endif
  return true;
}

// ---------- witness input ----------
// text format (exact integers only):
//  H4POINT-V1 <n> <q> <nfreq> <prec> <marker_count>
//  ALLOWED <i> <count> <s1> [s2]            (declared order - then +)
//  ROW <i> <ctxa> <ctxb> <m0> <m1>          interior row p_i(c|a,b): mantissas over 2^53, index 0 = -, 1 = +
//  TERM <m00> <m01> <m10> <m11>             terminal row r(a,b) over (--),(-+),(+-),(++)
//  PH <k> <i> <x> <cr> <ci>                 site phase, mantissas over 2^53
//  PHT <k> <a> <b> <cr> <ci>                combined terminal-pair phase, directly certified
//  LAM <k> <bits16>                         Fourier weight as a binary64 bit pattern
struct Row { int32_t m[2]; };
struct Tables {
  long n, q, nfreq, prec;
  std::vector<std::vector<int>> allowed;                    // per site, declared order
  std::vector<std::vector<Row>> rows;                       // rows[i][ctx] with ctx = 2*ia + ib over allowed index
  std::vector<double> rowp;                                 // flattened probabilities as doubles
  std::vector<int64_t> term;                                // 4 mantissas (0 for forbidden)
  std::vector<double> ph_re, ph_im;                         // [k][i][xi] site phases
  std::vector<double> pht_re, pht_im;                       // [k][a][b] terminal-pair phases
  std::vector<double> lam;
};
static const double TWO53 = 9007199254740992.0;             // 2^53
static inline double from_mesh(int64_t m) { return (double)m / TWO53; }   // exact: |m| <= 2^53

int main(int argc, char** argv) {
  now_s();
  const char* in = nullptr; const char* out = nullptr; const char* prog = nullptr; int reps_expect = -1;
  bool probes_only = false;
  for (int i = 1; i < argc; i++) {
    std::string a = argv[i];
    if (a == "--in") in = argv[++i]; else if (a == "--out") out = argv[++i]; else if (a == "--progress") prog = argv[++i];
    else if (a == "--expect-freq") reps_expect = atoi(argv[++i]); else if (a == "--probes-only") probes_only = true;
    else die("unknown argument");
  }
  std::string why;
  if (!env_ok(why)) { fprintf(stderr, "h4point: environment rejection: %s\n", why.c_str()); return 3; }
  auto probes = run_probes();
  for (auto& p : probes) if (!p.ok) { fprintf(stderr, "h4point: probe failed: %s got %016llx want %016llx\n", p.name, (unsigned long long)p.got, (unsigned long long)p.want); return 3; }
  if (probes_only) { printf("{\"probes\":["); for (size_t i = 0; i < probes.size(); i++) printf("%s{\"name\":\"%s\",\"bits\":\"%016llx\",\"ok\":true}", i ? "," : "", probes[i].name, (unsigned long long)probes[i].got); printf("],\"env\":\"ok\"}\n"); return 0; }
  if (!in || !out) die("need --in and --out");
  FILE* f = fopen(in, "r"); if (!f) die("cannot open input");
  Tables T; char tag[32];
  if (fscanf(f, "%31s", tag) != 1 || strcmp(tag, "H4POINT-V1") != 0) die("bad header");
  long mcount;
  if (fscanf(f, "%ld %ld %ld %ld %ld", &T.n, &T.q, &T.nfreq, &T.prec, &mcount) != 5) die("bad header fields");
  if (T.n < 4 || T.n > 128) die("n outside admitted domain");
  if (T.nfreq < 1 || T.nfreq > 512) die("frequency count outside F<=512");
  if (reps_expect > 0 && T.nfreq != reps_expect) die("frequency count differs from the frozen expectation");
  T.allowed.assign(T.n, {});
  T.rows.assign(T.n, {});
  T.term.assign(4, 0);
  long nk = T.nfreq;
  T.ph_re.assign(nk * T.n * 2, 0.0); T.ph_im.assign(nk * T.n * 2, 0.0);
  T.pht_re.assign(nk * 4, 0.0); T.pht_im.assign(nk * 4, 0.0);
  T.lam.assign(nk, 0.0);
  std::vector<char> seen_lam(nk, 0), seen_pht(nk * 4, 0), seen_ph((size_t)nk * T.n * 2, 0);
  std::vector<std::vector<char>> seen_row(T.n);
  while (fscanf(f, "%31s", tag) == 1) {
    if (!strcmp(tag, "ALLOWED")) {
      long i, c; if (fscanf(f, "%ld %ld", &i, &c) != 2 || i < 0 || i >= T.n || c < 1 || c > 2) die("bad ALLOWED");
      T.allowed[i].clear();
      for (long j = 0; j < c; j++) { long s; if (fscanf(f, "%ld", &s) != 1 || (s != -1 && s != 1)) die("bad spin"); T.allowed[i].push_back((int)s); }
    } else if (!strcmp(tag, "ROW")) {
      long i, ia, ib; int64_t m0, m1;
      if (fscanf(f, "%ld %ld %ld %lld %lld", &i, &ia, &ib, (long long*)&m0, (long long*)&m1) != 5) die("bad ROW");
      if (i < 0 || i > T.n - 3) die("row index");
      if (m0 < 0 || m1 < 0 || m0 + m1 != (int64_t)TWO53) die("row not exactly stochastic");
      { long nc = (long)T.allowed[i].size();
        if (nc == 1) { int c = T.allowed[i][0]; int64_t mf = (c < 0) ? m1 : m0;
          if (mf != 0) die("forbidden state has nonzero probability (lost structural zero)"); } }
      long na = (long)T.allowed[i + 1].size(), nb = (long)T.allowed[i + 2].size();
      if (ia < 0 || ia >= na || ib < 0 || ib >= nb) die("row context out of range");
      long idx = ia * nb + ib;
      if (T.rowp.empty()) T.rowp.assign((size_t)T.n * 4 * 2, -1.0);
      if (seen_row[i].empty()) seen_row[i].assign(4, 0);
      if (idx < 0 || idx >= 4) die("row context index out of layout range");
      if (seen_row[i][idx]) die("duplicate conditional-row record");
      seen_row[i][idx] = 1;
      // probabilities stored as exact doubles (m/2^53 with |m| <= 2^53 is exact)
      T.rowp[((size_t)i * 4 + idx) * 2 + 0] = from_mesh(m0);
      T.rowp[((size_t)i * 4 + idx) * 2 + 1] = from_mesh(m1);
    } else if (!strcmp(tag, "TERM")) {
      int64_t a, b, c, d;
      if (fscanf(f, "%lld %lld %lld %lld", (long long*)&a, (long long*)&b, (long long*)&c, (long long*)&d) != 4) die("bad TERM");
      if (a < 0 || b < 0 || c < 0 || d < 0 || a + b + c + d != (int64_t)TWO53) die("terminal row not exactly stochastic");
      T.term[0] = a; T.term[1] = b; T.term[2] = c; T.term[3] = d;
    } else if (!strcmp(tag, "PH")) {
      long k, i, x; int64_t cr, ci;
      if (fscanf(f, "%ld %ld %ld %lld %lld", &k, &i, &x, (long long*)&cr, (long long*)&ci) != 5) die("bad PH");
      if (k < 0 || k >= nk || i < 0 || i >= T.n || (x != 0 && x != 1)) die("PH index");
      if (seen_ph[((size_t)k * T.n + i) * 2 + x]) die("duplicate site-phase record");
      seen_ph[((size_t)k * T.n + i) * 2 + x] = 1;
      if ((__int128)cr * cr + (__int128)ci * ci > (__int128)9007199254740992LL * 9007199254740992LL) die("phase outside the unit disk");
      T.ph_re[(k * T.n + i) * 2 + x] = from_mesh(cr); T.ph_im[(k * T.n + i) * 2 + x] = from_mesh(ci);
    } else if (!strcmp(tag, "PHT")) {
      long k, a, b; int64_t cr, ci;
      if (fscanf(f, "%ld %ld %ld %lld %lld", &k, &a, &b, (long long*)&cr, (long long*)&ci) != 5) die("bad PHT");
      if (k < 0 || k >= nk || a < 0 || a > 1 || b < 0 || b > 1) die("PHT index");
      if ((__int128)cr * cr + (__int128)ci * ci > (__int128)9007199254740992LL * 9007199254740992LL) die("boundary-pair phase outside the unit disk");
      long idx = k * 4 + a * 2 + b;
      if (seen_pht[idx]) die("duplicate boundary-pair phase record");
      T.pht_re[idx] = from_mesh(cr); T.pht_im[idx] = from_mesh(ci); seen_pht[idx] = 1;
    } else if (!strcmp(tag, "LAM")) {
      long k; char hex[32];
      if (fscanf(f, "%ld %31s", &k, hex) != 2 || k < 0 || k >= nk) die("bad LAM");
      if (seen_lam[k]) die("duplicate Fourier-weight record");
      uint64_t u = strtoull(hex, nullptr, 16); double v = frombits(u);
      if (!(v >= 0.0) || !std::isfinite(v)) die("Fourier weight must be finite and nonnegative");
      T.lam[k] = v; seen_lam[k] = 1;
    } else die("unknown record");
  }
  fclose(f);
  for (long k = 0; k < nk; k++) if (!seen_lam[k]) die("missing Fourier weight");
  for (long i = 0; i < T.n; i++) if (T.allowed[i].empty()) die("missing ALLOWED record");
  for (long k = 0; k < nk; k++) for (long i = 0; i < T.n; i++) for (int x = 0; x < 2; x++)
    if (!seen_ph[((size_t)k * T.n + i) * 2 + x]) die("missing a required site-phase record");
  for (long i = 0; i <= T.n - 3; i++) {
    long na = (long)T.allowed[i + 1].size(), nb = (long)T.allowed[i + 2].size();
    if (seen_row[i].empty()) die("missing interior conditional rows for a site");
    for (long ia = 0; ia < na; ia++) for (long ib = 0; ib < nb; ib++)
      if (!seen_row[i][ia * nb + ib]) die("missing a reachable interior conditional row");
  }
  { long ta = (long)T.allowed[T.n - 2].size(), tb = (long)T.allowed[T.n - 1].size();
    for (long ia = 0; ia < ta; ia++) for (long ib = 0; ib < tb; ib++) {
      int sa = T.allowed[T.n - 2][ia], sb = T.allowed[T.n - 1][ib];
      long sl = (sa < 0 ? 0 : 2) + (sb < 0 ? 0 : 1);
      if (T.term[sl] < 0) die("terminal row entry missing");
    }
    for (long k = 0; k < nk; k++) for (long ia = 0; ia < ta; ia++) for (long ib = 0; ib < tb; ib++)
      if (!seen_pht[k * 4 + ia * 2 + ib]) die("missing a required terminal-pair phase");
  }
  // ---------- contraction ----------
  // state index within a layer: (ia, ib) over allowed indices of sites (i+1, i+2)
  FILE* pf = prog ? fopen(prog, "a") : nullptr;
  std::vector<double> out_re(nk * 2, 0.0), out_im(nk * 2, 0.0);     // [k][marker] marker 0 = -, 1 = +
  long ops = 0;
  for (int mi = 0; mi < 2; mi++) {
    int msign = (mi == 0) ? -1 : 1;
    for (long k = 0; k < nk; k++) {
      // H over contexts of sites (i+1, i+2)
      // every one of the four slots must be initialised: with a pinned boundary site the allowed-list loops below
      // cover fewer than four, and an uninitialised slot could be read through Hok[pidx] (review item 3).
      double Hre[4], Him[4]; bool Hok[4];
      for (int t = 0; t < 4; t++) { Hre[t] = 0.0; Him[t] = 0.0; Hok[t] = false; }
      // i = 0: H_0(a,b) = sum_c p_0(c|a,b) phi_0(k,c) b_0(c) * 1
      long na = (long)T.allowed[1].size(), nb = (long)T.allowed[2].size();
      for (long ia = 0; ia < na; ia++) for (long ib = 0; ib < nb; ib++) {
        long idx = ia * nb + ib; double sre = 0.0, sim = 0.0; bool first = true;
        for (long ic = 0; ic < (long)T.allowed[0].size(); ic++) {
          int c = T.allowed[0][ic];
          double p = T.rowp[(0 * 4 + idx) * 2 + (c < 0 ? 0 : 1)];
          if (0 == T.q && c != msign) continue;                     // marker mask, exactly once
          if (p == 0.0) continue;
          double zr = T.ph_re[(k * T.n + 0) * 2 + (c < 0 ? 0 : 1)], zi = T.ph_im[(k * T.n + 0) * 2 + (c < 0 ? 0 : 1)];
          // complex product with incoming 1: four real multiplies with a=1 -> keep the explicit sequence
          double ar = 1.0, ai = 0.0;
          double t1 = zr * ar, t2 = zi * ai, t3 = zr * ai, t4 = zi * ar;
          double pr = t1 - t2, pi = t3 + t4;
          double wr = pr * p, wi = pi * p; ops += 8;
          if (first) { sre = wr; sim = wi; first = false; } else { sre = sre + wr; sim = sim + wi; ops += 2; }
        }
        Hre[idx] = sre; Him[idx] = sim; Hok[idx] = !first;
      }
      // i = 1 .. n-3
      for (long i = 1; i <= T.n - 3; i++) {
        double Nre[4], Nim[4]; bool Nok[4];
        for (int t = 0; t < 4; t++) { Nre[t] = 0.0; Nim[t] = 0.0; Nok[t] = false; }
        long nna = (long)T.allowed[i + 1].size(), nnb = (long)T.allowed[i + 2].size();
        long pna = (long)T.allowed[i].size(), pnb = (long)T.allowed[i + 1].size();
        for (long ia = 0; ia < nna; ia++) for (long ib = 0; ib < nnb; ib++) {
          long idx = ia * nnb + ib; double sre = 0.0, sim = 0.0; bool first = true;
          for (long ic = 0; ic < pna; ic++) {
            int c = T.allowed[i][ic];
            double p = T.rowp[(i * 4 + idx) * 2 + (c < 0 ? 0 : 1)];
            if (i == T.q && c != msign) continue;
            if (p == 0.0) continue;
            // incoming H_{i-1}(c, a): context of sites (i, i+1) = (c, allowed[i+1][ia])
            long pidx = ic * pnb + ia;
            if (!Hok[pidx]) continue;
            double ar = Hre[pidx], ai = Him[pidx];
            double zr = T.ph_re[(k * T.n + i) * 2 + (c < 0 ? 0 : 1)], zi = T.ph_im[(k * T.n + i) * 2 + (c < 0 ? 0 : 1)];
            double t1 = zr * ar, t2 = zi * ai, t3 = zr * ai, t4 = zi * ar;
            double pr = t1 - t2, pi = t3 + t4;
            double wr = pr * p, wi = pi * p; ops += 8;
            if (first) { sre = wr; sim = wi; first = false; } else { sre = sre + wr; sim = sim + wi; ops += 2; }
          }
          Nre[idx] = sre; Nim[idx] = sim; Nok[idx] = !first;
        }
        for (int t = 0; t < 4; t++) { Hre[t] = Nre[t]; Him[t] = Nim[t]; Hok[t] = Nok[t]; }
      }
      // terminal: f = sum_{a,b} r(a,b) phi_term(k,a,b) b(a) b(b) H_{n-3}(a,b)
      long ta = (long)T.allowed[T.n - 2].size(), tb = (long)T.allowed[T.n - 1].size();
      double fre = 0.0, fim = 0.0; bool first = true;
      for (long ia = 0; ia < ta; ia++) for (long ib = 0; ib < tb; ib++) {
        int sa = T.allowed[T.n - 2][ia], sb = T.allowed[T.n - 1][ib];
        long sl = (sa < 0 ? 0 : 2) + (sb < 0 ? 0 : 1);
        double p = from_mesh(T.term[sl]);
        if (p == 0.0) continue;
        if (T.q == T.n - 2 && sa != msign) continue;
        if (T.q == T.n - 1 && sb != msign) continue;
        long idx = ia * tb + ib;
        if (!Hok[idx]) continue;
        double ar = Hre[idx], ai = Him[idx];
        long pidx = k * 4 + (sa < 0 ? 0 : 1) * 2 + (sb < 0 ? 0 : 1);   // phases are keyed by ABSOLUTE spin
        if (!seen_pht[pidx]) die("missing terminal-pair phase");
        double zr = T.pht_re[pidx], zi = T.pht_im[pidx];
        double t1 = zr * ar, t2 = zi * ai, t3 = zr * ai, t4 = zi * ar;
        double pr = t1 - t2, pi = t3 + t4;
        double wr = pr * p, wi = pi * p; ops += 8;
        if (first) { fre = wr; fim = wi; first = false; } else { fre = fre + wr; fim = fim + wi; ops += 2; }
      }
      out_re[k * 2 + mi] = fre; out_im[k * 2 + mi] = fim;
      if (pf && (k % 64 == 0)) { fprintf(pf, "{\"kernel\":\"h4point\",\"marker\":%d,\"freq\":%ld,\"of\":%ld,\"elapsed_s\":%.3f}\n", msign, k, nk, now_s()); fflush(pf); }
    }
  }
  // ---------- weighted response: sequential dot product in declared frequency order ----------
  double resp[2];
  for (int mi = 0; mi < 2; mi++) {
    double s = 0.0; bool first = true;
    for (long k = 0; k < nk; k++) {
      double t = T.lam[k] * out_re[k * 2 + mi]; ops += 1;
      if (first) { s = t; first = false; } else { s = s + t; ops += 1; }
    }
    resp[mi] = s;
  }
  if (fegetround() != FE_TONEAREST) die("rounding mode changed during execution");
  FILE* o = fopen(out, "w"); if (!o) die("cannot write output");
  fprintf(o, "{\"kernel\":\"h4point\",\"n\":%ld,\"q\":%ld,\"nfreq\":%ld,\"ops\":%ld,\"wall_s\":%.6f,\"channels\":[", T.n, T.q, T.nfreq, ops, now_s());
  for (long k = 0; k < nk; k++) for (int mi = 0; mi < 2; mi++) {
    if (k || mi) fprintf(o, ",");
    fprintf(o, "{\"k\":%ld,\"marker\":%d,\"re\":\"%016llx\",\"im\":\"%016llx\"}", k, mi == 0 ? -1 : 1,
            (unsigned long long)bits(out_re[k * 2 + mi]), (unsigned long long)bits(out_im[k * 2 + mi]));
  }
  fprintf(o, "],\"response\":[{\"marker\":-1,\"bits\":\"%016llx\"},{\"marker\":1,\"bits\":\"%016llx\"}],\"probes_ok\":true}\n",
          (unsigned long long)bits(resp[0]), (unsigned long long)bits(resp[1]));
  fflush(o); fsync(fileno(o)); fclose(o);
  if (pf) fclose(pf);
  return 0;
}
