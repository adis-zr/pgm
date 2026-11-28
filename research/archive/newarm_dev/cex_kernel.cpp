// cex_kernel.cpp -- compiled nonnegative bucket contraction + all-singleton reverse recovery (certified executor pass, 11 Nov 2026).
//
// SEMANTICS (preserved exactly from support.py): for the supplied elimination order, bucket i eliminates x = order[i] from the product of its inputs
// (source factor occurrences + child messages assigned to it); m_i(s) = sum_x prod_j f_j(x, s).  Roots are scalar messages; Z = prod roots.
// Reverse: g_i(s) = dZ/dm_i(s) (unnormalized adjoint, nonnegative); for every bag row of bucket i, term = g_i(s) * prod_j f_j; N_x[row x] += term;
// child context g_c(key_c) += g_i(s) * prod_{j != c} f_j via zero-safe prefix/suffix exclusion products (no division). Final p = N/Z in Python (exact).
// Omitting absent sparse rows is justified by complete nonnegative support + the singleton-marker task (the reference's argument); every factor
// occurrence, scope/axis order, evidence slice and decoder are preserved (the plan is bound by the Python side before this kernel runs).
//
// NUMERICS: nearest binary64 (round-to-nearest asserted at entry and polled), u = 2^-53, NO fma / reassociation (-ffp-contract=off, strict fp model).
// Every stored quantity carries one integer LABEL E per message / context / numerator (max over its entries) with the RECIPROCAL ENVELOPE invariant
//     a^E x <= xhat <= a^-E x,  a = 1-u,
// which is closed under +, x and / (THEORY + prompt section 6): add E = max(E1,E2)+1, mul E = E1+E2+1, positive div E = E1+E2+1; exact power-of-two
// scaling adds nothing (ldexp is exact in normal range). Sequential accumulation of n terms with labels <= Et gives Et + (n-1). Labels are the max over a
// message, which is sound (a weaker envelope). A product/sum of nonzero operands that is not a normal finite double (underflow, overflow, NaN) is a
// RANGE failure (typed stop, never a fabricated zero). Support decisions are exact: a stored 0 arises only from an exact 0 operand.
// SCALING: every message carries an integer power-of-two exponent e: true(s) = stored(s) * 2^e; products add exponents; a new message is normalized so
// its maximum stored entry is in [1, 2). Reverse contexts carry exponents the same way; N and Z carry exponents; Python forms N/Z exactly.
// MEMORY: every allocation is reserved (logical bytes, capacity-based) against a cap BEFORE it happens; messages are released after their last reverse
// use; the peak logical reservation is reported beside the sampled RSS. Deadline: absolute value of the host's monotonic clock (CLOCK_UPTIME_RAW on Apple
// = Python's time.monotonic; CLOCK_MONOTONIC on Linux), polled every 4096 rows.
#include <cstdint>
#include <cstring>
#include <cmath>
#include <cfenv>
#include <ctime>
#include <vector>
#include <unordered_map>
#include <algorithm>
#include <limits>
#include <new>

#if defined(__APPLE__)
#define CEX_CLOCK CLOCK_UPTIME_RAW
#else
#define CEX_CLOCK CLOCK_MONOTONIC
#endif
static double now_mono() { timespec ts; if (clock_gettime(CEX_CLOCK, &ts)) return std::numeric_limits<double>::infinity(); return double(ts.tv_sec) + 1e-9 * ts.tv_nsec; }

enum Stop : int { OK = 0, DEADLINE = 1, MEMORY = 2, RANGE = 3, BADPLAN = 4, FPENV = 5, FAULT = 6, ZEROMASS = 7 };
static const double DMIN = std::numeric_limits<double>::min();

struct Rel {                       // a relation over `scope` (variable ids, in order): dense (values over the mixed-radix volume) or sparse (sorted keys + values)
    std::vector<int> scope; std::vector<int64_t> card; std::vector<int64_t> stride; int64_t vol = 1; bool dense = true;
    std::vector<uint64_t> keys; std::vector<double> vals; int64_t exp2 = 0; int64_t label = 0; bool is_message = false; int child = -1; bool freed = false;
    size_t bytes() const { return keys.capacity() * sizeof(uint64_t) + vals.capacity() * sizeof(double); }
};

struct Counters {
    uint64_t forward_rows = 0, reverse_rows = 0, mults = 0, adds = 0, join_index_rows = 0, join_probes = 0, join_rows_generated = 0, dense_rows = 0, sparse_rows = 0,
             rescale_entries = 0, polls = 0, messages_entries = 0, contexts_entries = 0, max_label = 0, buckets_dense = 0, buckets_sparse = 0, conversions = 0;
    int64_t peak_logical_bytes = 0, logical_bytes = 0, peak_join_rows = 0, max_live_message_entries = 0;
};

struct Exec {
    int n = 0; std::vector<int64_t> card; std::vector<int> order; std::vector<Rel> sources; std::vector<Rel> msgs; std::vector<std::vector<int>> bucket_src, bucket_msg;
    std::vector<int> rank; int64_t cap_bytes = 0; double deadline = 0; int stop = OK; char reason[200] = {0}; Counters C; uint64_t since_poll = 0; double dense_fill_threshold = 0.25;
    int64_t live_msg_entries = 0;
    // ---------------- accounting
    bool reserve(int64_t b) { if (C.logical_bytes + b > cap_bytes) { stop = MEMORY; std::snprintf(reason, sizeof reason, "logical reservation %lld + %lld exceeds cap %lld", (long long)C.logical_bytes, (long long)b, (long long)cap_bytes); return false; } C.logical_bytes += b; if (C.logical_bytes > C.peak_logical_bytes) C.peak_logical_bytes = C.logical_bytes; return true; }
    void release(int64_t b) { C.logical_bytes -= b; if (C.logical_bytes < 0) C.logical_bytes = 0; }
    bool poll(uint64_t w) { since_poll += w; if (since_poll >= 4096) { since_poll = 0; ++C.polls; if (std::fegetround() != FE_TONEAREST) { stop = FPENV; return false; } if (now_mono() > deadline) { stop = DEADLINE; return false; } } return true; }
    template <class V> bool reserve_vec(V& v, size_t n) {         // reserve capacity BEFORE growth (exact element bytes)
        if (v.capacity() >= n) return true; int64_t b = (int64_t)(n - v.capacity()) * (int64_t)sizeof(typename V::value_type); if (!reserve(b)) return false;
        try { v.reserve(n); } catch (std::bad_alloc&) { stop = MEMORY; std::snprintf(reason, sizeof reason, "bad_alloc"); return false; } return true;
    }
    void free_rel(Rel& r) { if (r.freed) return; release((int64_t)r.bytes()); if (r.is_message) live_msg_entries -= (int64_t)r.vals.size(); std::vector<uint64_t>().swap(r.keys); std::vector<double>().swap(r.vals); r.freed = true; }
    static int64_t ceil_log2(int64_t n) { int64_t k = 0; while ((int64_t(1) << k) < n) ++k; return k; }
    // exact power-of-two rescaling of a relation so that its maximum stored entry lies in [1, 2): true = stored * 2^exp2 is preserved exactly; labels unchanged.
    // An entry that would fall below the normal range after scaling is a RANGE stop (the relation's dynamic range exceeds binary64), never a flush to zero.
    bool rescale(Rel& r, int who, const char* what) {
        double mx = 0.0; for (double x : r.vals) if (x > mx) mx = x;
        if (mx == 0.0) return true;                                        // all-zero: the caller decides (forward: ZEROMASS; context: legitimately zero adjoint)
        if (!std::isfinite(mx)) { stop = RANGE; std::snprintf(reason, sizeof reason, "%s %d: non-finite entry before rescaling", what, who); return false; }
        int e; std::frexp(mx, &e); int shift = 1 - e; if (shift == 0) return true;
        for (double& x : r.vals) { if (x != 0.0) { x = std::ldexp(x, shift); if (x < DMIN || !std::isfinite(x)) { stop = RANGE; std::snprintf(reason, sizeof reason, "%s %d: entry leaves the normal range under rescaling (dynamic range of the relation too wide for binary64)", what, who); return false; } } }
        C.rescale_entries += r.vals.size(); r.exp2 -= shift; return true;
    }
    // ---------------- range guard: a product / sum of nonzero finite operands must stay a normal finite double
    inline bool guard(double r, bool nonzero_operands) { if (!std::isfinite(r) || (nonzero_operands && (r == 0.0 || r < DMIN))) { stop = RANGE; std::snprintf(reason, sizeof reason, "non-normal intermediate (%g) from nonzero operands", r); return false; } return true; }
    // ---------------- join machinery: rows of the bag of a bucket as mixed-radix keys over `bag`
    struct Bag { std::vector<int> vars; std::vector<int64_t> card, stride; int64_t vol = 1; std::vector<int> pos_of; };
    Bag make_bag(const std::vector<Rel*>& ins, int v) {
        Bag b; std::vector<int> seen(n, 0);
        for (auto r : ins) for (int w : r->scope) if (!seen[w]) { seen[w] = 1; b.vars.push_back(w); }
        if (!seen[v]) { b.vars.push_back(v); }
        std::sort(b.vars.begin(), b.vars.end(), [&](int a, int c) { if (a == v) return false; if (c == v) return true; return rank[a] < rank[c]; });   // eliminated variable LAST (innermost)
        b.pos_of.assign(n, -1); for (size_t i = 0; i < b.vars.size(); ++i) { b.card.push_back(card[b.vars[i]]); b.pos_of[b.vars[i]] = (int)i; }
        b.stride.assign(b.vars.size(), 1); for (int i = (int)b.vars.size() - 2; i >= 0; --i) b.stride[i] = b.stride[i + 1] * b.card[i + 1];
        b.vol = b.vars.empty() ? 1 : b.stride[0] * b.card[0]; return b;   // caller checks width <= 62 and each card >= 1; a volume beyond 2^62 is refused by the dense path's reservation
    }
    // index of relation r for a bag assignment given by digits d (bag positions)
    static inline int64_t rel_index(const Rel& r, const std::vector<int>& bagpos_of_relaxis, const int64_t* d) { int64_t k = 0; for (size_t i = 0; i < r.scope.size(); ++i) k += d[bagpos_of_relaxis[i]] * r.stride[i]; return k; }
    static inline double rel_value_dense(const Rel& r, int64_t k) { return r.vals[k]; }
    static inline int64_t sparse_find(const Rel& r, uint64_t k) { auto it = std::lower_bound(r.keys.begin(), r.keys.end(), k); if (it == r.keys.end() || *it != k) return -1; return (int64_t)(it - r.keys.begin()); }
    // digits of a dense bag row
    static inline void digits(const Bag& b, int64_t idx, int64_t* d) { for (size_t i = 0; i < b.vars.size(); ++i) { d[i] = (idx / b.stride[i]) % b.card[i]; } }
    // sparse support of a bucket: every bag row compatible with all SPARSE inputs (dense inputs are total -> no constraint except exact zeros, applied at evaluation);
    // produced as sorted bag keys (eliminated variable innermost). Hash-join over shared coordinates, smallest relation first.
    bool support_rows(const std::vector<Rel*>& ins, const Bag& b, std::vector<uint64_t>& out, int64_t row_cap) {
        std::vector<Rel*> sp; for (auto r : ins) if (!r->dense) sp.push_back(r);
        std::sort(sp.begin(), sp.end(), [](Rel* a, Rel* c) { return a->keys.size() < c->keys.size(); });
        std::vector<int> have(n, 0); std::vector<uint64_t> rows; std::vector<int> cols;      // cols: bag positions determined so far
        if (sp.empty()) { stop = BADPLAN; std::snprintf(reason, sizeof reason, "support_rows called without a sparse input"); return false; }
        auto proj = [&](const Rel& r, const std::vector<int>& relaxes, uint64_t key) {   // key of r -> partial bag key over the given relation axes
            uint64_t k = 0; for (int ax : relaxes) { int64_t dgt = (int64_t)(key / (uint64_t)r.stride[ax]) % r.card[ax]; k += (uint64_t)dgt * (uint64_t)b.stride[b.pos_of[r.scope[ax]]]; } return k; };
        { const Rel& r0 = *sp[0]; std::vector<int> all(r0.scope.size()); for (size_t i = 0; i < all.size(); ++i) all[i] = (int)i;
          if (!reserve_vec(rows, r0.keys.size())) return false;
          for (uint64_t k : r0.keys) { rows.push_back(proj(r0, all, k)); if (!poll(1)) return false; }
          for (int w : r0.scope) have[w] = 1; }
        for (size_t si = 1; si < sp.size(); ++si) {
            const Rel& r = *sp[si]; std::vector<int> shared_ax, new_ax; for (size_t i = 0; i < r.scope.size(); ++i) (have[r.scope[i]] ? shared_ax : new_ax).push_back((int)i);
            // index r by its shared-coordinate partial bag key
            std::unordered_map<uint64_t, std::vector<uint64_t>> index; int64_t idx_bytes = (int64_t)r.keys.size() * 48; if (!reserve(idx_bytes)) return false;
            for (uint64_t k : r.keys) { index[proj(r, shared_ax, k)].push_back(proj(r, new_ax, k)); ++C.join_index_rows; if (!poll(1)) return false; }
            std::vector<uint64_t> out2; uint64_t mask_shared = 0; (void)mask_shared;
            // partial bag key restricted to r's shared axes: recompute from the row's digits
            for (uint64_t row : rows) {
                ++C.join_probes; uint64_t pk = 0; for (int ax : shared_ax) { int bp = b.pos_of[r.scope[ax]]; int64_t dgt = (int64_t)(row / (uint64_t)b.stride[bp]) % b.card[bp]; pk += (uint64_t)dgt * (uint64_t)b.stride[bp]; }
                auto it = index.find(pk); if (it == index.end()) { if (!poll(1)) { release(idx_bytes); return false; } continue; }
                if ((int64_t)(out2.size() + it->second.size()) > row_cap) { stop = MEMORY; std::snprintf(reason, sizeof reason, "support rows exceed row cap %lld", (long long)row_cap); release(idx_bytes); return false; }
                if (!reserve_vec(out2, out2.size() + it->second.size())) { release(idx_bytes); return false; }
                for (uint64_t tail : it->second) out2.push_back(row + tail); C.join_rows_generated += it->second.size(); if (!poll(it->second.size())) { release(idx_bytes); return false; }
            }
            release(idx_bytes); release((int64_t)rows.capacity() * 8); rows.swap(out2); for (int w : r.scope) have[w] = 1;
            if ((int64_t)rows.size() > C.peak_join_rows) C.peak_join_rows = (int64_t)rows.size(); if (rows.empty()) break;
        }
        // remaining bag variables not covered by any sparse input (dense-only axes and possibly x): expand over them
        std::vector<int> missing; for (size_t i = 0; i < b.vars.size(); ++i) if (!have[b.vars[i]]) missing.push_back((int)i);
        if (!missing.empty() && !rows.empty()) {
            int64_t mult = 1; for (int i : missing) mult *= b.card[i]; if ((int64_t)rows.size() * mult > row_cap) { stop = MEMORY; std::snprintf(reason, sizeof reason, "expanded support rows exceed row cap"); return false; }
            std::vector<uint64_t> out2; if (!reserve_vec(out2, rows.size() * (size_t)mult)) return false;
            for (uint64_t row : rows) { for (int64_t t = 0; t < mult; ++t) { int64_t tt = t; uint64_t k = row; for (int mi = (int)missing.size() - 1; mi >= 0; --mi) { int i = missing[mi]; k += (uint64_t)(tt % b.card[i]) * (uint64_t)b.stride[i]; tt /= b.card[i]; } out2.push_back(k); } if (!poll(mult)) return false; }
            release((int64_t)rows.capacity() * 8); rows.swap(out2);
        }
        std::sort(rows.begin(), rows.end()); rows.erase(std::unique(rows.begin(), rows.end()), rows.end()); out.swap(rows); return true;
    }
    // ---------------- forward
    bool forward() {
        msgs.resize(n); std::vector<int64_t> d(64);   // bag width <= 64 variables (plan validation: scopes <= 60 and the bag of a bucket is checked below)
        for (int i = 0; i < n; ++i) {
            int v = order[i]; std::vector<Rel*> ins; for (int s : bucket_src[i]) ins.push_back(&sources[s]); for (int m : bucket_msg[i]) ins.push_back(&msgs[m]);
            Rel& out = msgs[i]; out.is_message = true; out.child = i;
            if (ins.empty()) { // isolated variable without any factor: uniform
                out.scope = {}; out.vol = 1; out.dense = true; if (!reserve_vec(out.vals, 1)) return false; out.vals.push_back((double)card[v]); out.exp2 = 0; out.label = 0; C.messages_entries += 1; continue;
            }
            Bag b = make_bag(ins, v); if (b.vars.size() > 62) { stop = BADPLAN; std::snprintf(reason, sizeof reason, "bag of bucket %d has %zu variables (> 62)", i, b.vars.size()); return false; } int xpos = (int)b.vars.size() - 1; int64_t cx = card[v]; int64_t sepvol = b.vol / cx;
            out.scope.assign(b.vars.begin(), b.vars.end() - 1); out.card.assign(b.card.begin(), b.card.end() - 1); out.stride.assign(out.scope.size(), 1);
            for (int k = (int)out.scope.size() - 2; k >= 0; --k) out.stride[k] = out.stride[k + 1] * out.card[k + 1]; out.vol = sepvol;
            bool all_dense = true; for (auto r : ins) all_dense = all_dense && r->dense;
            std::vector<std::vector<int>> bp(ins.size()); for (size_t j = 0; j < ins.size(); ++j) { bp[j].resize(ins[j]->scope.size()); for (size_t a = 0; a < ins[j]->scope.size(); ++a) bp[j][a] = b.pos_of[ins[j]->scope[a]]; }
            int64_t lab_in = 0; for (auto r : ins) lab_in += r->label; int64_t exp_in = 0; for (auto r : ins) exp_in += r->exp2; int k = (int)ins.size();
            if (all_dense) {
                ++C.buckets_dense; if (!reserve_vec(out.vals, (size_t)sepvol)) return false; out.vals.assign((size_t)sepvol, 0.0); out.dense = true;
                for (int64_t sidx = 0; sidx < sepvol; ++sidx) {
                    double acc = 0.0; bool any = false;
                    for (int64_t x = 0; x < cx; ++x) {
                        int64_t idx = sidx * cx + x; digits(b, idx, d.data()); double w = 1.0; bool z = false;
                        for (size_t j = 0; j < ins.size(); ++j) { double f = ins[j]->vals[rel_index(*ins[j], bp[j], d.data())]; if (f == 0.0) { z = true; break; } w *= f; }
                        C.mults += k; ++C.forward_rows; ++C.dense_rows;
                        if (z) continue; if (!guard(w, true)) return false; acc += w; ++C.adds; any = true;
                    }
                    if (any && !guard(acc, true)) return false; out.vals[sidx] = acc; if (!poll(cx)) return false;
                }
                out.label = lab_in + (k - 1) + (cx - 1) + 1;     // k-1 multiplications per term (+1 slack for the initial 1.0 product), up to cx sequential additions
            } else {
                ++C.buckets_sparse; std::vector<uint64_t> rows; if (!support_rows(ins, b, rows, cap_bytes / 16)) return false;
                C.sparse_rows += rows.size();
                // evaluate products row by row; accumulate per separator key (rows sorted: separator-major, x innermost)
                std::vector<uint64_t> okeys; std::vector<double> ovals; if (!reserve_vec(okeys, rows.size()) || !reserve_vec(ovals, rows.size())) return false;
                int64_t maxterms = 1, terms = 0; uint64_t cur = ~0ull; double acc = 0.0; bool have_cur = false;
                for (uint64_t key : rows) {
                    digits(b, (int64_t)key, d.data()); uint64_t sk = key - (uint64_t)d[xpos] * (uint64_t)b.stride[xpos]; sk /= (uint64_t)cx;   // separator key = key with x removed (x innermost, stride 1)
                    double w = 1.0; bool z = false;
                    for (size_t j = 0; j < ins.size(); ++j) { const Rel& r = *ins[j]; int64_t ri = rel_index(r, bp[j], d.data()); double f; if (r.dense) f = r.vals[ri]; else { int64_t p = sparse_find(r, (uint64_t)ri); f = p < 0 ? 0.0 : r.vals[p]; } if (f == 0.0) { z = true; break; } w *= f; }
                    C.mults += k; ++C.forward_rows;
                    if (!poll(1)) return false; if (z) continue; if (!guard(w, true)) return false;
                    if (have_cur && sk == cur) { acc += w; ++C.adds; ++terms; } else { if (have_cur) { if (!guard(acc, true)) return false; okeys.push_back(cur); ovals.push_back(acc); } cur = sk; acc = w; terms = 1; have_cur = true; }
                    if (terms > maxterms) maxterms = terms;
                }
                if (have_cur) { if (!guard(acc, true)) return false; okeys.push_back(cur); ovals.push_back(acc); }
                release((int64_t)rows.capacity() * 8); std::vector<uint64_t>().swap(rows);
                out.label = lab_in + (k - 1) + (maxterms - 1) + 1;
                // representation choice from validated density
                if (sepvol <= (int64_t)(okeys.size() / dense_fill_threshold) && sepvol * 8 <= cap_bytes / 4) {
                    if (!reserve_vec(out.vals, (size_t)sepvol)) return false; out.vals.assign((size_t)sepvol, 0.0); out.dense = true;
                    for (size_t t = 0; t < okeys.size(); ++t) out.vals[okeys[t]] = ovals[t]; release((int64_t)(okeys.capacity() * 8 + ovals.capacity() * 8));
                } else { out.dense = false; out.keys.swap(okeys); out.vals.swap(ovals); }
            }
            // rescale: max stored entry into [1, 2) (exact power-of-two scaling); an all-zero message = exact zero mass in this component
            { double mx = 0.0; for (double x : out.vals) if (x > mx) mx = x; if (mx == 0.0) { stop = ZEROMASS; std::snprintf(reason, sizeof reason, "bucket %d produced an all-zero message: exact zeros only -> Z = 0 in this component", i); return false; } }
            out.exp2 = exp_in; if (!rescale(out, i, "message")) return false;
            if (out.label > (int64_t)C.max_label) C.max_label = out.label;
            C.messages_entries += out.vals.size(); live_msg_entries += (int64_t)out.vals.size(); if (live_msg_entries > C.max_live_message_entries) C.max_live_message_entries = live_msg_entries;
            // assign to the bucket of its lowest-ranked separator variable
            if (!out.scope.empty()) { int best = n; for (int w : out.scope) best = std::min(best, rank[w]); bucket_msg[best].push_back(i); }
        }
        return true;
    }
    // ---------------- reverse (all singleton numerators)
    std::vector<double> Nval; std::vector<int64_t> Nexp, Nlab; double Zval = 0; int64_t Zexp = 0, Zlab = 0;
    bool reverse() {
        std::vector<int> roots; for (int i = 0; i < n; ++i) if (msgs[i].scope.empty()) roots.push_back(i);
        // Z = product of roots (exclusion products give each root's adjoint)
        int R = (int)roots.size(); std::vector<double> pre(R + 1, 1.0), suf(R + 2, 1.0); std::vector<int64_t> preL(R + 1, 0), sufL(R + 2, 0), preE(R + 1, 0), sufE(R + 2, 0);
        for (int r = 0; r < R; ++r) { const Rel& m = msgs[roots[r]]; pre[r + 1] = pre[r] * m.vals[0]; ++C.mults; if (!guard(pre[r + 1], true)) return false; preL[r + 1] = preL[r] + m.label + 1; preE[r + 1] = preE[r] + m.exp2; }
        for (int r = R - 1; r >= 0; --r) { const Rel& m = msgs[roots[r]]; suf[r] = suf[r + 1] * m.vals[0]; ++C.mults; if (!guard(suf[r], true)) return false; sufL[r] = sufL[r + 1] + m.label + 1; sufE[r] = sufE[r + 1] + m.exp2; }
        Zval = pre[R]; Zlab = preL[R]; Zexp = preE[R];
        std::vector<Rel> ctx(n);          // ctx[i] = g_i over msgs[i].scope, same representation / keys as msgs[i]
        std::vector<int64_t> ctx_terms(n, 1);
        for (int r = 0; r < R; ++r) { int i = roots[r]; Rel& g = ctx[i]; g.dense = true; g.scope = {}; g.vol = 1; if (!reserve_vec(g.vals, 1)) return false; g.vals.push_back(pre[r] * suf[r + 1]); ++C.mults; g.label = preL[r] + sufL[r + 1] + 1; g.exp2 = preE[r] + sufE[r + 1]; C.contexts_entries += 1; }
        Nval.assign(0, 0.0); Nexp.assign(n, 0); Nlab.assign(n, 0); std::vector<int64_t> noff(n + 1, 0); for (int v = 0; v < n; ++v) noff[v + 1] = noff[v] + card[v]; Nval.assign((size_t)noff[n], 0.0);
        std::vector<int64_t> d(64);
        for (int i = n - 1; i >= 0; --i) {
            int v = order[i]; std::vector<Rel*> ins; for (int s : bucket_src[i]) ins.push_back(&sources[s]); for (int m : bucket_msg[i]) ins.push_back(&msgs[m]);
            Rel& g = ctx[i]; if (g.vals.empty()) { stop = BADPLAN; std::snprintf(reason, sizeof reason, "missing context for bucket %d", i); return false; }
            int64_t gexp = g.exp2;
            if (ins.empty()) { // isolated uniform variable: N_v(x) = g * 1 for each x
                for (int64_t x = 0; x < card[v]; ++x) { Nval[noff[v] + x] = g.vals[0]; } Nexp[v] = gexp; Nlab[v] = g.label; free_rel(g); continue;
            }
            Bag b = make_bag(ins, v); if (b.vars.size() > 62) { stop = BADPLAN; return false; } int xpos = (int)b.vars.size() - 1; int64_t cx = card[v]; int k = (int)ins.size();
            std::vector<std::vector<int>> bp(ins.size()); for (size_t j = 0; j < ins.size(); ++j) { bp[j].resize(ins[j]->scope.size()); for (size_t a = 0; a < ins[j]->scope.size(); ++a) bp[j][a] = b.pos_of[ins[j]->scope[a]]; }
            int64_t lab_in = 0, exp_in = 0; for (auto r : ins) { lab_in += r->label; exp_in += r->exp2; }
            // allocate child contexts (same representation as the child message), zero-filled
            for (size_t j = 0; j < ins.size(); ++j) { Rel* r = ins[j]; if (!r->is_message) continue; Rel& gc = ctx[r->child]; if (!gc.vals.empty()) continue; gc.scope = r->scope; gc.card = r->card; gc.stride = r->stride; gc.vol = r->vol; gc.dense = r->dense; if (!r->dense) { if (!reserve_vec(gc.keys, r->keys.size())) return false; gc.keys = r->keys; } if (!reserve_vec(gc.vals, r->vals.size())) return false; gc.vals.assign(r->vals.size(), 0.0); gc.exp2 = gexp + exp_in - r->exp2; gc.label = 0; C.contexts_entries += gc.vals.size(); }
            Nexp[v] = gexp + exp_in; int64_t termlab = g.label + lab_in + k + 1;   // prefix product of k factors from 1.0: k multiplications (+k); times g: +1
            std::vector<double> fv(k), pre_(k + 1), suf_(k + 1); std::vector<int64_t> ridx(k);
            // iterate the bag rows: dense if all dense, else the sparse support (recomputed: counted as reverse join work)
            auto visit = [&](int64_t idx) -> bool {
                digits(b, idx, d.data()); double gv; int64_t sk = idx / cx;
                if (g.dense) gv = g.vals[sk]; else { int64_t p = sparse_find(g, (uint64_t)sk); gv = p < 0 ? 0.0 : g.vals[p]; }
                ++C.reverse_rows; if (gv == 0.0) return poll(1);
                for (int j = 0; j < k; ++j) { const Rel& r = *ins[j]; int64_t ri = rel_index(r, bp[j], d.data()); ridx[j] = ri; double f; if (r.dense) f = r.vals[ri]; else { int64_t p = sparse_find(r, (uint64_t)ri); f = p < 0 ? 0.0 : r.vals[p]; } fv[j] = f; }
                // zero-safe prefix / suffix exclusion products (exact zeros propagate as exact zeros; no division)
                pre_[0] = 1.0; for (int j = 0; j < k; ++j) { pre_[j + 1] = pre_[j] * fv[j]; ++C.mults; if (pre_[j + 1] != 0.0 && !guard(pre_[j + 1], true)) return false; }
                suf_[k] = 1.0; for (int j = k - 1; j >= 0; --j) { suf_[j] = suf_[j + 1] * fv[j]; ++C.mults; if (suf_[j] != 0.0 && !guard(suf_[j], true)) return false; }
                double term = gv * pre_[k]; ++C.mults; if (pre_[k] != 0.0 && !guard(term, true)) return false;
                if (term != 0.0) { double& acc = Nval[noff[v] + d[xpos]]; acc += term; ++C.adds; if (!guard(acc, true)) return false; }
                for (int j = 0; j < k; ++j) { const Rel& r = *ins[j]; if (!r.is_message) continue; double excl = pre_[j] * suf_[j + 1]; ++C.mults; if (excl == 0.0) continue; if (!guard(excl, true)) return false; double t = gv * excl; ++C.mults; if (!guard(t, true)) return false;
                    Rel& gc = ctx[r.child]; if (gc.dense) { gc.vals[ridx[j]] += t; } else { int64_t p = sparse_find(gc, (uint64_t)ridx[j]); if (p < 0) { stop = FAULT; std::snprintf(reason, sizeof reason, "context key missing"); return false; } gc.vals[p] += t; } ++C.adds; ctx_terms[r.child]++; }
                return poll(1);
            };
            bool all_dense = true; for (auto r : ins) all_dense = all_dense && r->dense;
            int64_t rows_visited = 0;
            if (all_dense) { for (int64_t idx = 0; idx < b.vol; ++idx) { if (!visit(idx)) return false; ++rows_visited; } }
            else { std::vector<uint64_t> rows; if (!support_rows(ins, b, rows, cap_bytes / 16)) return false; for (uint64_t key : rows) { if (!visit((int64_t)key)) return false; ++rows_visited; } release((int64_t)rows.capacity() * 8); }
            Nlab[v] = termlab + std::max<int64_t>(0, rows_visited - 1);   // sequential accumulation bound: at most rows_visited terms into one numerator entry
            for (size_t j = 0; j < ins.size(); ++j) { Rel* r = ins[j]; if (!r->is_message) continue; Rel& gc = ctx[r->child]; int64_t tl = g.label + lab_in - r->label + k + 1; gc.label = std::max(gc.label, tl + std::max<int64_t>(0, rows_visited - 1)); /* exclusion product: k multiplications; times g: +1; sequential accumulation over the visited rows */ if ((int64_t)gc.label > (int64_t)C.max_label) C.max_label = gc.label; }
            if (Nlab[v] > (int64_t)C.max_label) C.max_label = Nlab[v];
            // guard numerators finite
            for (int64_t x = 0; x < cx; ++x) if (!std::isfinite(Nval[noff[v] + x])) { stop = RANGE; std::snprintf(reason, sizeof reason, "non-finite numerator"); return false; }
            // every child context fed here is now complete (a context has exactly one writer: its consumer bucket): rescale it before it is read as g
            for (auto r : ins) if (r->is_message) { Rel& gc = ctx[r->child]; if (!rescale(gc, r->child, "context")) return false; }
            // release: the context of this bucket and the child messages consumed here have had their final use
            free_rel(g); for (auto r : ins) if (r->is_message) free_rel(*r);
        }
        return true;
    }
};

extern "C" {
// plan words: n, card[n], norder (=n), order[n], nsrc, then per source: scope_len, scope[...], mode(0 dense/1 sparse), count, [keys count] (sparse), values count as doubles follow in `vals`, label
int cex_run(const int64_t* plan, int64_t plen, const double* vals, int64_t nvals, int64_t cap_bytes, double deadline_abs, double dense_fill_threshold,
            double* Nout, int64_t* Nexp_out, int64_t* Nlab_out, double* Zout, int64_t* Zmeta, uint64_t* counters, int64_t ncounters, char* reason_out, int64_t reason_len) {
    if (std::fegetround() != FE_TONEAREST) return FPENV;
    Exec E; E.cap_bytes = cap_bytes; E.deadline = deadline_abs; E.dense_fill_threshold = dense_fill_threshold;
    try {
        int64_t p = 0; auto rd = [&]() -> int64_t { if (p >= plen) throw 1; return plan[p++]; };
        E.n = (int)rd(); if (E.n <= 0 || E.n > 100000) { E.stop = BADPLAN; std::snprintf(E.reason, sizeof E.reason, "invalid plan word"); throw 2; } E.card.resize(E.n); for (int i = 0; i < E.n; ++i) { E.card[i] = rd(); if (E.card[i] <= 0) { E.stop = BADPLAN; std::snprintf(E.reason, sizeof E.reason, "invalid plan word"); throw 2; } }
        int64_t no = rd(); if (no != E.n) { E.stop = BADPLAN; std::snprintf(E.reason, sizeof E.reason, "invalid plan word"); throw 2; } E.order.resize(E.n); std::vector<int> seen(E.n, 0); for (int i = 0; i < E.n; ++i) { E.order[i] = (int)rd(); if (E.order[i] < 0 || E.order[i] >= E.n || seen[E.order[i]]) { E.stop = BADPLAN; std::snprintf(E.reason, sizeof E.reason, "invalid plan word"); throw 2; } seen[E.order[i]] = 1; }
        E.rank.assign(E.n, 0); for (int i = 0; i < E.n; ++i) E.rank[E.order[i]] = i;
        int64_t nsrc = rd(); int64_t vp = 0; E.sources.resize(nsrc); E.bucket_src.assign(E.n, {}); E.bucket_msg.assign(E.n, {});
        for (int64_t s = 0; s < nsrc; ++s) {
            Rel& r = E.sources[s]; int64_t sl = rd(); if (sl < 0 || sl > 60) { E.stop = BADPLAN; std::snprintf(E.reason, sizeof E.reason, "invalid plan word"); throw 2; } r.scope.resize(sl); for (int64_t a = 0; a < sl; ++a) { r.scope[a] = (int)rd(); if (r.scope[a] < 0 || r.scope[a] >= E.n) { E.stop = BADPLAN; std::snprintf(E.reason, sizeof E.reason, "invalid plan word"); throw 2; } }
            r.card.resize(sl); for (int64_t a = 0; a < sl; ++a) r.card[a] = E.card[r.scope[a]]; r.stride.assign(sl, 1); for (int64_t a = sl - 2; a >= 0; --a) r.stride[a] = r.stride[a + 1] * r.card[a + 1]; r.vol = sl ? r.stride[0] * r.card[0] : 1;
            int64_t mode = rd(); int64_t cnt = rd(); r.dense = (mode == 0);
            if (r.dense) { if (cnt != r.vol) { E.stop = BADPLAN; std::snprintf(E.reason, sizeof E.reason, "invalid plan word"); throw 2; } if (!E.reserve_vec(r.vals, cnt)) throw 2; for (int64_t t = 0; t < cnt; ++t) { if (vp >= nvals) { E.stop = BADPLAN; std::snprintf(E.reason, sizeof E.reason, "invalid plan word"); throw 2; } r.vals.push_back(vals[vp++]); } }
            else { if (!E.reserve_vec(r.keys, cnt) || !E.reserve_vec(r.vals, cnt)) throw 2; for (int64_t t = 0; t < cnt; ++t) r.keys.push_back((uint64_t)rd()); for (int64_t t = 1; t < cnt; ++t) if (r.keys[t] <= r.keys[t - 1]) { E.stop = BADPLAN; std::snprintf(E.reason, sizeof E.reason, "invalid plan word"); throw 2; } for (int64_t t = 0; t < cnt; ++t) { if (vp >= nvals) { E.stop = BADPLAN; std::snprintf(E.reason, sizeof E.reason, "invalid plan word"); throw 2; } r.vals.push_back(vals[vp++]); } }
            r.label = rd(); r.exp2 = 0; for (double x : r.vals) { if (!(x >= 0.0) || !std::isfinite(x) || (x != 0.0 && x < DMIN)) { E.stop = RANGE; std::snprintf(E.reason, sizeof E.reason, "source value outside the supported binary64 range"); throw 2; } } E.C.conversions += r.vals.size();
            if (!E.rescale(r, (int)s, "source")) throw 2;                   // sources are brought to max in [1,2) too (exact power-of-two scaling): every stored relation has a bounded magnitude
            if (sl == 0) { E.stop = BADPLAN; std::snprintf(E.reason, sizeof E.reason, "invalid plan word"); throw 2; }   // scalar factors are cancelled by the caller
            int best = E.n; for (int w : r.scope) best = std::min(best, E.rank[w]); E.bucket_src[best].push_back((int)s);
        }
        if (vp != nvals) { E.stop = BADPLAN; std::snprintf(E.reason, sizeof E.reason, "invalid plan word"); throw 2; }
        if (!E.forward()) { } else if (!E.reverse()) { }
        if (E.stop == OK) {
            int64_t off = 0; for (int v = 0; v < E.n; ++v) { for (int64_t x = 0; x < E.card[v]; ++x) Nout[off + x] = E.Nval[off + x]; Nexp_out[v] = E.Nexp[v]; Nlab_out[v] = E.Nlab[v]; off += E.card[v]; }
            Zout[0] = E.Zval; Zmeta[0] = E.Zexp; Zmeta[1] = E.Zlab;
        }
    } catch (std::bad_alloc&) { E.stop = MEMORY; std::snprintf(E.reason, sizeof E.reason, "bad_alloc"); } catch (int) { if (E.stop == OK) { E.stop = BADPLAN; std::snprintf(E.reason, sizeof E.reason, "plan exhausted early"); } } catch (...) { if (E.stop == OK) E.stop = FAULT; }
    uint64_t cv[] = {E.C.forward_rows, E.C.reverse_rows, E.C.mults, E.C.adds, E.C.join_index_rows, E.C.join_probes, E.C.join_rows_generated, E.C.dense_rows, E.C.sparse_rows, E.C.rescale_entries, E.C.polls, E.C.messages_entries, E.C.contexts_entries, E.C.max_label, E.C.buckets_dense, E.C.buckets_sparse, E.C.conversions, (uint64_t)E.C.peak_logical_bytes, (uint64_t)E.C.logical_bytes, (uint64_t)E.C.peak_join_rows, (uint64_t)E.C.max_live_message_entries};
    for (int64_t i = 0; i < ncounters && i < (int64_t)(sizeof cv / sizeof cv[0]); ++i) counters[i] = cv[i];
    std::strncpy(reason_out, E.reason, (size_t)std::max<int64_t>(0, reason_len - 1)); if (reason_len > 0) reason_out[reason_len - 1] = 0;
    return E.stop;
}
const char* cex_schedule_id() { return "CEX/nonneg-bucket-contraction-all-singleton-reverse/v1.1-scaled-sources-messages-contexts"; }
}
