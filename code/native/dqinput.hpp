// dqinput.hpp — DECLARED SHARED exact-input parser (producer and checker). Reads the canonical DQCHAIN-V1 text and returns exact
// rationals (GMP mpq). It does NOT verify the generating formulas — that is done independently in Python (dq/gate.py for the producer,
// dq/checker.py for the checker); it only parses and rejects malformed/duplicate/missing/extra lines.
#pragma once
#include <gmp.h>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <string>
#include <vector>
#include <fstream>
#include <sstream>
#include <map>

struct Input {
  long n = 0; std::string kase; long query = 0;
  std::map<long, int> pins;                 // site -> +-1
  std::vector<__mpq_struct> h, a, f;       // f has n-1 entries (equal-spin factor of edge i); element type is the mpq struct (mpq_t is an array type, not storable in vectors)
  std::string header;
};

static bool parse_q(mpq_t q, const std::string& s) { if (mpq_set_str(q, s.c_str(), 10) != 0) return false; mpq_canonicalize(q); return true; }

static bool read_input(const char* path, Input& in, std::string& err) {
  std::ifstream fs(path); if (!fs) { err = "cannot open input"; return false; }
  std::string line; long lineno = 0;
  if (!std::getline(fs, line)) { err = "empty"; return false; } lineno++;
  in.header = line;
  std::istringstream hs(line); std::string tok; hs >> tok; if (tok != "DQCHAIN-V1") { err = "bad header token"; return false; }
  while (hs >> tok) {
    size_t eq = tok.find('='); if (eq == std::string::npos) { err = "bad header field"; return false; }
    std::string k = tok.substr(0, eq), v = tok.substr(eq + 1);
    if (k == "n") in.n = atol(v.c_str()); else if (k == "case") in.kase = v; else if (k == "query") in.query = atol(v.c_str());
    else if (k == "evidence") { if (v != "none") { std::istringstream es(v); std::string p; while (std::getline(es, p, ',')) { size_t c = p.find(':'); if (c == std::string::npos) { err = "bad pin"; return false; } long i = atol(p.substr(0, c).c_str()); int s = atoi(p.substr(c + 1).c_str()); if (s != 1 && s != -1 || in.pins.count(i)) { err = "bad pin value/duplicate"; return false; } in.pins[i] = s; } } }
    else { err = "unknown header field " + k; return false; }
  }
  if (in.n < 2) { err = "n too small"; return false; }
  if (!std::getline(fs, line)) { err = "missing weight line"; return false; } lineno++;
  if (line.rfind("weight:", 0) != 0) { err = "missing weight description line"; return false; }
  in.h.resize(in.n); in.a.resize(in.n); in.f.resize(in.n - 1);
  for (long i = 0; i < in.n; i++) { mpq_init(&in.h[i]); mpq_init(&in.a[i]); } for (long i = 0; i < in.n - 1; i++) mpq_init(&in.f[i]);
  std::vector<char> seen_site(in.n, 0), seen_edge(in.n - 1, 0);
  while (std::getline(fs, line)) {
    lineno++; if (line.empty()) continue;
    std::istringstream ls(line); std::string kind; long idx; ls >> kind >> idx;
    if (kind == "site") {
      std::string hs_, as_; ls >> hs_ >> as_; std::string extra; if (ls >> extra) { err = "extra site field line " + std::to_string(lineno); return false; }
      if (idx < 0 || idx >= in.n || seen_site[idx]) { err = "bad/duplicate site index line " + std::to_string(lineno); return false; }
      if (hs_.rfind("h=", 0) != 0 || as_.rfind("a=", 0) != 0 || !parse_q(&in.h[idx], hs_.substr(2)) || !parse_q(&in.a[idx], as_.substr(2))) { err = "bad site rationals line " + std::to_string(lineno); return false; }
      seen_site[idx] = 1;
    } else if (kind == "edge") {
      std::string fs_; ls >> fs_; std::string extra; if (ls >> extra) { err = "extra edge field"; return false; }
      if (idx < 0 || idx >= in.n - 1 || seen_edge[idx]) { err = "bad/duplicate edge index line " + std::to_string(lineno); return false; }
      if (fs_.rfind("f=", 0) != 0 || !parse_q(&in.f[idx], fs_.substr(2)) || mpq_sgn(&in.f[idx]) <= 0) { err = "bad edge factor line " + std::to_string(lineno); return false; }
      seen_edge[idx] = 1;
    } else { err = "unknown line kind at line " + std::to_string(lineno); return false; }
  }
  for (long i = 0; i < in.n; i++) if (!seen_site[i]) { err = "missing site " + std::to_string(i); return false; }
  for (long i = 0; i < in.n - 1; i++) if (!seen_edge[i]) { err = "missing edge " + std::to_string(i); return false; }
  for (auto& kv : in.pins) if (kv.first < 0 || kv.first >= in.n || kv.first == in.query) { err = "pin out of range or on the query"; return false; }
  return true;
}

static void free_input(Input& in) { for (auto& q : in.h) mpq_clear(&q); for (auto& q : in.a) mpq_clear(&q); for (auto& q : in.f) mpq_clear(&q); }
