// cex_kernel.cpp -- compiled nonnegative bucket contraction + all-singleton reverse recovery (certified executor pass, 11 Nov 2026) -- v1.4 (v1.2 repair after
// the adversarial review of 11 Nov 2026: checked arithmetic by OPERAND PROVENANCE, checked integer dimensions, one enforceable allocation boundary,
// deadline checks at entry / phase boundaries / return, exact-rescaling round-trip check, plan format 2 with Python-side exact power-of-two source scaling).
//
// SEMANTICS (preserved exactly from support.py): for the supplied elimination order, bucket i eliminates x = order[i] from the product of its inputs
// (source factor occurrences + child messages assigned to it); m_i(s) = sum_x prod_j f_j(x, s).  Roots are scalar messages; Z = prod roots.
// Reverse: g_i(s) = dZ/dm_i(s) (unnormalized adjoint, nonnegative); for every bag row of bucket i, term = g_i(s) * prod_j f_j; N_x[row x] += term;
// child context g_c(key_c) += g_i(s) * prod_{j != c} f_j via zero-safe prefix/suffix exclusion products (no division). Final p = N/Z in Python (exact).
// Omitting absent sparse rows is justified by complete nonnegative support + the singleton-marker task (the reference's argument); every factor
// occurrence, scope/axis order, evidence slice and decoder are preserved (the plan is bound by the Python side before this kernel runs).
//
// NUMERICS: nearest binary64 (round-to-nearest asserted at entry, at every phase boundary and polled), u = 2^-53, NO fma / reassociation.
// Every stored quantity carries one integer LABEL E per message / context / numerator (max over its entries) with the RECIPROCAL ENVELOPE invariant
//     a^E x <= xhat <= a^-E x,  a = 1-u,
// closed under + and x for NONNEGATIVE operands whose rounded results are NORMAL finite doubles: add E = max(E1,E2)+1, mul E = E1+E2+1. The precondition is
// ENFORCED by the two arithmetic primitives `mul` / `add` (the only arithmetic in this file): a product of two NONZERO operands whose rounded result is zero,
// subnormal, infinite or NaN is a typed RANGE stop (decided from the OPERANDS, never from the rounded result); an exact zero propagates ONLY from an exact
// zero operand (an exact zero source entry or an absent sparse row). Hence a stored 0.0 is an exact zero and an all-zero message is exact zero mass.
// SCALING: every relation carries an integer power-of-two exponent e: true = stored * 2^e; products add exponents; a new message / completed context is
// normalized so its maximum stored entry lies in [1, 2) by ldexp, whose EXACTNESS is checked per entry by round trip (ldexp(y, -shift) == x) and normality;
// sources arrive pre-scaled by the Python side (exact rational power-of-two scaling, so no source magnitude is outside binary64 by construction).
// INTEGERS: every stride / volume / byte / label / exponent sum, difference and negation is computed with overflow-checked arithmetic (__builtin_*_overflow,
// helpers addl / subl); a mixed-radix volume above 2^62 is a typed REPRESENTATION refusal (this kernel addresses rows by 64-bit keys), never a wrapped volume.
// ABI PRECONDITION (v1.4, enforced at the plan parser): a source label lies in [0, 2^40] and a source exponent in [-2^40, 2^40] (the Python side emits labels 0/1
// and exponents bounded by the bit length of its rational inputs); anything else is a typed BADPLAN refusal before any arithmetic.
// MEMORY: ONE allocation boundary: every container in this kernel uses the `Charged` allocator, which charges the exact requested bytes of every heap
// allocation (capacity-based, transient overlap included: a growing vector's new block is charged while the old block is still live) against the cap
// BEFORE calling operator new and refuses (typed MEMORY stop) instead of allocating; deallocations release exactly what was charged. `peak_logical_bytes`
// is therefore the peak of all live native heap bytes requested by the kernel (an instrumented global operator new observes the same number).
// DEADLINE: absolute value of the host's monotonic clock (CLOCK_UPTIME_RAW on Apple = Python's time.monotonic; CLOCK_MONOTONIC elsewhere): checked at
// entry, after parsing, after forward, after reverse and before a successful return; polled every 4096 units of work inside every loop (rows, values, entries).
#include <cstdint>
#include <cstdio>
#include <cstring>
#include <cmath>
#include <cfenv>
#include <ctime>
#include <vector>
#include <unordered_map>
#include <algorithm>
#include <limits>
#include <new>
#include <atomic>

#if defined(__APPLE__)
#define CEX_CLOCK CLOCK_UPTIME_RAW
#else
#define CEX_CLOCK CLOCK_MONOTONIC
#endif
static double now_mono() { timespec ts; if (clock_gettime(CEX_CLOCK, &ts)) return std::numeric_limits<double>::infinity(); return double(ts.tv_sec) + 1e-9 * ts.tv_nsec; }

enum Stop : int { OK = 0, DEADLINE = 1, MEMORY = 2, RANGE = 3, BADPLAN = 4, FPENV = 5, FAULT = 6, ZEROMASS = 7, REPRESENTATION = 8 };
static const double DMIN = std::numeric_limits<double>::min();
static const int64_t VOL_LIMIT = int64_t(1) << 62;
static const int64_t PLAN_FORMAT = 2;
static const int64_t META_LIMIT = int64_t(1) << 40;     // ABI precondition on source labels / exponents

// ---------------- the allocation boundary
struct Ledger { int64_t cap = 0, live = 0, peak = 0, refused_request = 0; uint64_t allocs = 0; bool exceeded = false; };
static Ledger* g_ledger = nullptr;            // set for the duration of ONE cex_run; a concurrent second invocation is refused (atomic busy flag below)
static std::atomic<bool> g_busy{false};
struct CapExceeded {};
template <class T> struct Charged {
    typedef T value_type;
    Charged() noexcept {}
    template <class U> Charged(const Charged<U>&) noexcept {}
    T* allocate(std::size_t n) {
        if (n > std::size_t(-1) / sizeof(T)) throw std::bad_alloc();
        std::size_t b = n * sizeof(T);
        if (!g_ledger || b > (std::size_t)std::numeric_limits<int64_t>::max()) throw std::bad_alloc();
        if ((int64_t)b > g_ledger->cap - g_ledger->live) { g_ledger->exceeded = true; g_ledger->refused_request = (int64_t)b; throw CapExceeded(); }
        T* p = static_cast<T*>(::operator new(b));
        g_ledger->live += (int64_t)b; if (g_ledger->live > g_ledger->peak) g_ledger->peak = g_ledger->live; ++g_ledger->allocs; return p;
    }
    void deallocate(T* p, std::size_t n) noexcept { ::operator delete(p); if (g_ledger) g_ledger->live -= (int64_t)(n * sizeof(T)); }
    template <class U> bool operator==(const Charged<U>&) const noexcept { return true; }
    template <class U> bool operator!=(const Charged<U>&) const noexcept { return false; }
};
template <class T> using vec = std::vector<T, Charged<T>>;
typedef std::unordered_map<uint64_t, vec<uint64_t>, std::hash<uint64_t>, std::equal_to<uint64_t>, Charged<std::pair<const uint64_t, vec<uint64_t>>>> Index;

static inline bool mul_i(int64_t a, int64_t b, int64_t& out) { return !__builtin_mul_overflow(a, b, &out); }
static inline bool add_i(int64_t a, int64_t b, int64_t& out) { return !__builtin_add_overflow(a, b, &out); }

struct Rel {                       // a relation over `scope` (variable ids, in order): dense (values over the mixed-radix volume) or sparse (sorted keys + values)
    vec<int> scope; vec<int64_t> card; vec<int64_t> stride; int64_t vol = 1; bool dense = true;
    vec<uint64_t> keys; vec<double> vals; int64_t exp2 = 0; int64_t label = 0; bool is_message = false; int child = -1; bool freed = false;
};

struct Counters {
    uint64_t forward_rows = 0, reverse_rows = 0, mults = 0, adds = 0, join_index_rows = 0, join_probes = 0, join_rows_generated = 0, dense_rows = 0, sparse_rows = 0,
             rescale_entries = 0, polls = 0, messages_entries = 0, contexts_entries = 0, max_label = 0, buckets_dense = 0, buckets_sparse = 0, conversions = 0;
    int64_t peak_logical_bytes = 0, logical_bytes = 0, peak_join_rows = 0, max_live_message_entries = 0; uint64_t allocations = 0;
};

struct Exec {
    int n = 0; vec<int64_t> card; vec<int> order; vec<Rel> sources; vec<Rel> msgs; vec<vec<int>> bucket_src, bucket_msg;
    vec<int> rank; double deadline = 0; int stop = OK; char reason[200] = {0}; Counters C; uint64_t since_poll = 0; double dense_fill_threshold = 0.25;
    int64_t live_msg_entries = 0; int64_t cap_bytes = 0;
    // ---------------- deadline / rounding environment
    bool check(const char* where) { ++C.polls; if (std::fegetround() != FE_TONEAREST) { stop = FPENV; std::snprintf(reason, sizeof reason, "rounding mode is not nearest at %s", where); return false; } if (now_mono() > deadline) { stop = DEADLINE; std::snprintf(reason, sizeof reason, "deadline expired at %s", where); return false; } return true; }
    bool poll(uint64_t w) { since_poll += w; if (since_poll >= 4096) { since_poll = 0; return check("poll"); } return true; }
    // ---------------- the two arithmetic primitives (nonnegative operands). An exact zero operand yields an exact zero; otherwise the rounded result must be a NORMAL finite double.
    inline bool mul(double a, double b, double& out) {
        if (a == 0.0 || b == 0.0) { out = 0.0; return true; }
        out = a * b; ++C.mults;
        if (!(out >= DMIN) || !std::isfinite(out)) { stop = RANGE; std::snprintf(reason, sizeof reason, "non-normal product (%g) of nonzero operands %g x %g", out, a, b); return false; }
        return true;
    }
    inline bool add(double a, double b, double& out) {   // a, b >= 0 and each either exactly zero or normal: the sum is exact zero or normal unless it overflows
        out = a + b; ++C.adds;
        if (!std::isfinite(out)) { stop = RANGE; std::snprintf(reason, sizeof reason, "non-finite sum (%g) of %g + %g", out, a, b); return false; }
        return true;
    }
    bool addl(int64_t a, int64_t b, int64_t& out, const char* what) { if (!add_i(a, b, out)) { stop = REPRESENTATION; std::snprintf(reason, sizeof reason, "%s: integer overflow", what); return false; } return true; }
    bool subl(int64_t a, int64_t b, int64_t& out, const char* what) { if (__builtin_sub_overflow(a, b, &out)) { stop = REPRESENTATION; std::snprintf(reason, sizeof reason, "%s: integer overflow", what); return false; } return true; }
    void free_rel(Rel& r) { if (r.freed) return; if (r.is_message) live_msg_entries -= (int64_t)r.vals.size(); vec<uint64_t>().swap(r.keys); vec<double>().swap(r.vals); r.freed = true; }
    // exact power-of-two rescaling of a relation so that its maximum stored entry lies in [1, 2): true = stored * 2^exp2 preserved EXACTLY (round trip checked
    // per entry), labels unchanged. An entry whose scaled value is not a normal double reproducing the original under the inverse shift is a RANGE stop.
    bool rescale(Rel& r, int who, const char* what) {
        double mx = 0.0; for (double x : r.vals) if (x > mx) mx = x;
        if (!poll(r.vals.size())) return false;
        if (mx == 0.0) return true;                                        // all-zero: the caller decides (forward: ZEROMASS; context: legitimately zero adjoint)
        if (!std::isfinite(mx)) { stop = RANGE; std::snprintf(reason, sizeof reason, "%s %d: non-finite entry before rescaling", what, who); return false; }
        int e; std::frexp(mx, &e); int shift = 1 - e; if (shift == 0) return true;
        for (double& x : r.vals) {
            if (x == 0.0) continue;
            double y = std::ldexp(x, shift);
            if (!(y >= DMIN) || !std::isfinite(y) || std::ldexp(y, -shift) != x) { stop = RANGE; std::snprintf(reason, sizeof reason, "%s %d: entry %g cannot be rescaled exactly by 2^%d (leaves the normal range or fails the round trip)", what, who, x, shift); return false; }
            x = y;
        }
        C.rescale_entries += r.vals.size(); if (!poll(r.vals.size())) return false; return subl(r.exp2, (int64_t)shift, r.exp2, "rescale exponent");
    }
    // ---------------- join machinery: rows of the bag of a bucket as mixed-radix keys over `bag`
    struct Bag { vec<int> vars; vec<int64_t> card, stride; int64_t vol = 1; vec<int> pos_of; };
    bool make_bag(const vec<Rel*>& ins, int v, Bag& b) {
        vec<int> seen(n, 0);
        for (auto r : ins) for (int w : r->scope) if (!seen[w]) { seen[w] = 1; b.vars.push_back(w); }
        if (!seen[v]) { b.vars.push_back(v); }
        std::sort(b.vars.begin(), b.vars.end(), [&](int a, int c) { if (a == v) return false; if (c == v) return true; return rank[a] < rank[c]; });   // eliminated variable LAST (innermost)
        b.pos_of.assign(n, -1); for (size_t i = 0; i < b.vars.size(); ++i) { b.card.push_back(card[b.vars[i]]); b.pos_of[b.vars[i]] = (int)i; }
        b.stride.assign(b.vars.size(), 1);
        for (int i = (int)b.vars.size() - 2; i >= 0; --i) { if (!mul_i(b.stride[i + 1], b.card[i + 1], b.stride[i]) || b.stride[i] > VOL_LIMIT) { stop = REPRESENTATION; std::snprintf(reason, sizeof reason, "bag of the bucket eliminating variable %d: mixed-radix volume exceeds 2^62 (not addressable by this kernel's 64-bit keys)", v); return false; } }
        if (b.vars.empty()) b.vol = 1; else if (!mul_i(b.stride[0], b.card[0], b.vol) || b.vol > VOL_LIMIT) { stop = REPRESENTATION; std::snprintf(reason, sizeof reason, "bag of the bucket eliminating variable %d: mixed-radix volume exceeds 2^62 (not addressable by this kernel's 64-bit keys)", v); return false; }
        return true;
    }
    static inline int64_t rel_index(const Rel& r, const vec<int>& bagpos_of_relaxis, const int64_t* d) { int64_t k = 0; for (size_t i = 0; i < r.scope.size(); ++i) k += d[bagpos_of_relaxis[i]] * r.stride[i]; return k; }
    static inline int64_t sparse_find(const Rel& r, uint64_t k) { auto it = std::lower_bound(r.keys.begin(), r.keys.end(), k); if (it == r.keys.end() || *it != k) return -1; return (int64_t)(it - r.keys.begin()); }
    static inline void digits(const Bag& b, int64_t idx, int64_t* d) { for (size_t i = 0; i < b.vars.size(); ++i) { d[i] = (idx / b.stride[i]) % b.card[i]; } }
    // sparse support of a bucket: every bag row compatible with all SPARSE inputs (dense inputs are total -> no constraint except exact zeros, applied at evaluation);
    // produced as sorted bag keys (eliminated variable innermost). Hash-join over shared coordinates, smallest relation first. All containers are charged.
    bool support_rows(const vec<Rel*>& ins, const Bag& b, vec<uint64_t>& out, int64_t row_cap) {
        vec<Rel*> sp; for (auto r : ins) if (!r->dense) sp.push_back(r);
        std::sort(sp.begin(), sp.end(), [](Rel* a, Rel* c) { return a->keys.size() < c->keys.size(); });
        vec<int> have(n, 0); vec<uint64_t> rows;
        if (sp.empty()) { stop = BADPLAN; std::snprintf(reason, sizeof reason, "support_rows called without a sparse input"); return false; }
        auto proj = [&](const Rel& r, const vec<int>& relaxes, uint64_t key) {   // key of r -> partial bag key over the given relation axes
            uint64_t k = 0; for (int ax : relaxes) { int64_t dgt = (int64_t)(key / (uint64_t)r.stride[ax]) % r.card[ax]; k += (uint64_t)dgt * (uint64_t)b.stride[b.pos_of[r.scope[ax]]]; } return k; };
        { const Rel& r0 = *sp[0]; vec<int> all(r0.scope.size()); for (size_t i = 0; i < all.size(); ++i) all[i] = (int)i;
          rows.reserve(r0.keys.size());
          for (uint64_t k : r0.keys) { rows.push_back(proj(r0, all, k)); if (!poll(1)) return false; }
          for (int w : r0.scope) have[w] = 1; }
        for (size_t si = 1; si < sp.size(); ++si) {
            const Rel& r = *sp[si]; vec<int> shared_ax, new_ax; for (size_t i = 0; i < r.scope.size(); ++i) (have[r.scope[i]] ? shared_ax : new_ax).push_back((int)i);
            Index index;                                                                     // every node, bucket array and per-key vector is charged by the allocator
            for (uint64_t k : r.keys) { index[proj(r, shared_ax, k)].push_back(proj(r, new_ax, k)); ++C.join_index_rows; if (!poll(1)) return false; }
            vec<uint64_t> out2;
            for (uint64_t row : rows) {
                ++C.join_probes; uint64_t pk = 0; for (int ax : shared_ax) { int bp = b.pos_of[r.scope[ax]]; int64_t dgt = (int64_t)(row / (uint64_t)b.stride[bp]) % b.card[bp]; pk += (uint64_t)dgt * (uint64_t)b.stride[bp]; }
                auto it = index.find(pk); if (it == index.end()) { if (!poll(1)) return false; continue; }
                int64_t need; if (!add_i((int64_t)out2.size(), (int64_t)it->second.size(), need) || need > row_cap) { stop = MEMORY; std::snprintf(reason, sizeof reason, "support rows exceed row cap %lld", (long long)row_cap); return false; }
                for (uint64_t tail : it->second) out2.push_back(row + tail); C.join_rows_generated += it->second.size(); if (!poll(it->second.size())) return false;
            }
            rows.swap(out2); vec<uint64_t>().swap(out2); for (int w : r.scope) have[w] = 1;
            if ((int64_t)rows.size() > C.peak_join_rows) C.peak_join_rows = (int64_t)rows.size(); if (rows.empty()) break;
        }
        // remaining bag variables not covered by any sparse input (dense-only axes and possibly x): expand over them
        vec<int> missing; for (size_t i = 0; i < b.vars.size(); ++i) if (!have[b.vars[i]]) missing.push_back((int)i);
        if (!missing.empty() && !rows.empty()) {
            int64_t mult = 1, total; for (int i : missing) { if (!mul_i(mult, b.card[i], mult) || mult > VOL_LIMIT) { stop = REPRESENTATION; std::snprintf(reason, sizeof reason, "support expansion volume exceeds 2^62"); return false; } }
            if (!mul_i((int64_t)rows.size(), mult, total) || total > row_cap) { stop = MEMORY; std::snprintf(reason, sizeof reason, "expanded support rows exceed row cap %lld", (long long)row_cap); return false; }
            vec<uint64_t> out2; out2.reserve((size_t)total);
            for (uint64_t row : rows) { for (int64_t t = 0; t < mult; ++t) { int64_t tt = t; uint64_t k = row; for (int mi = (int)missing.size() - 1; mi >= 0; --mi) { int i = missing[mi]; k += (uint64_t)(tt % b.card[i]) * (uint64_t)b.stride[i]; tt /= b.card[i]; } out2.push_back(k); } if (!poll(mult)) return false; }
            rows.swap(out2);
        }
        std::sort(rows.begin(), rows.end()); rows.erase(std::unique(rows.begin(), rows.end()), rows.end()); out.swap(rows); return true;
    }
    // ---------------- forward
    bool forward() {
        msgs.resize(n); vec<int64_t> d(64);
        for (int i = 0; i < n; ++i) {
            int v = order[i]; vec<Rel*> ins; for (int s : bucket_src[i]) ins.push_back(&sources[s]); for (int m : bucket_msg[i]) ins.push_back(&msgs[m]);
            Rel& out = msgs[i]; out.is_message = true; out.child = i;
            if (ins.empty()) { // isolated variable without any factor: uniform
                out.scope.clear(); out.vol = 1; out.dense = true; out.vals.assign(1, (double)card[v]); out.exp2 = 0; out.label = 0; C.messages_entries += 1; if (!poll(1)) return false; continue;
            }
            Bag b; if (!make_bag(ins, v, b)) return false; if (b.vars.size() > 62) { stop = BADPLAN; std::snprintf(reason, sizeof reason, "bag of bucket %d has %zu variables (> 62)", i, b.vars.size()); return false; } int xpos = (int)b.vars.size() - 1; int64_t cx = card[v]; int64_t sepvol = b.vol / cx;
            out.scope.assign(b.vars.begin(), b.vars.end() - 1); out.card.assign(b.card.begin(), b.card.end() - 1); out.stride.assign(out.scope.size(), 1);
            for (int k = (int)out.scope.size() - 2; k >= 0; --k) out.stride[k] = out.stride[k + 1] * out.card[k + 1]; out.vol = sepvol;   // sub-products of the checked bag volume
            bool all_dense = true; for (auto r : ins) all_dense = all_dense && r->dense;
            vec<vec<int>> bp(ins.size()); for (size_t j = 0; j < ins.size(); ++j) { bp[j].resize(ins[j]->scope.size()); for (size_t a = 0; a < ins[j]->scope.size(); ++a) bp[j][a] = b.pos_of[ins[j]->scope[a]]; }
            int64_t lab_in = 0, exp_in = 0; for (auto r : ins) { if (!addl(lab_in, r->label, lab_in, "label sum") || !addl(exp_in, r->exp2, exp_in, "exponent sum")) return false; } int k = (int)ins.size();
            if (all_dense) {
                ++C.buckets_dense; out.vals.assign((size_t)sepvol, 0.0); out.dense = true;
                for (int64_t sidx = 0; sidx < sepvol; ++sidx) {
                    double acc = 0.0;
                    for (int64_t x = 0; x < cx; ++x) {
                        int64_t idx = sidx * cx + x; digits(b, idx, d.data()); double w = 1.0; bool z = false;
                        for (size_t j = 0; j < ins.size(); ++j) { double f = ins[j]->vals[rel_index(*ins[j], bp[j], d.data())]; if (f == 0.0) { z = true; break; } if (!mul(w, f, w)) return false; }
                        ++C.forward_rows; ++C.dense_rows;
                        if (z) continue; if (!add(acc, w, acc)) return false;
                    }
                    out.vals[sidx] = acc; if (!poll(cx)) return false;
                }
                int64_t lab, inc; if (!addl((int64_t)k, cx - 1, inc, "message label") || !addl(lab_in, inc, lab, "message label")) return false; out.label = lab;   // k-1 multiplications per term (+1 slack for the initial 1.0 product), up to cx sequential additions
            } else {
                ++C.buckets_sparse; vec<uint64_t> rows; if (!support_rows(ins, b, rows, cap_bytes / 16)) return false;
                C.sparse_rows += rows.size();
                vec<uint64_t> okeys; vec<double> ovals; okeys.reserve(rows.size()); ovals.reserve(rows.size());
                int64_t maxterms = 1, terms = 0; uint64_t cur = ~0ull; double acc = 0.0; bool have_cur = false;
                for (uint64_t key : rows) {
                    digits(b, (int64_t)key, d.data()); uint64_t sk = key - (uint64_t)d[xpos] * (uint64_t)b.stride[xpos]; sk /= (uint64_t)cx;   // separator key = key with x removed (x innermost, stride 1)
                    double w = 1.0; bool z = false;
                    for (size_t j = 0; j < ins.size(); ++j) { const Rel& r = *ins[j]; int64_t ri = rel_index(r, bp[j], d.data()); double f; if (r.dense) f = r.vals[ri]; else { int64_t p = sparse_find(r, (uint64_t)ri); f = p < 0 ? 0.0 : r.vals[p]; } if (f == 0.0) { z = true; break; } if (!mul(w, f, w)) return false; }
                    ++C.forward_rows;
                    if (!poll(1)) return false; if (z) continue;
                    if (have_cur && sk == cur) { if (!add(acc, w, acc)) return false; ++terms; } else { if (have_cur) { okeys.push_back(cur); ovals.push_back(acc); } cur = sk; acc = w; terms = 1; have_cur = true; }
                    if (terms > maxterms) maxterms = terms;
                }
                if (have_cur) { okeys.push_back(cur); ovals.push_back(acc); }
                vec<uint64_t>().swap(rows);
                int64_t lab, inc; if (!addl((int64_t)k, maxterms - 1, inc, "message label") || !addl(lab_in, inc, lab, "message label")) return false; out.label = lab;
                // representation choice from validated density (sepvol * 8 bytes would have to fit a quarter of the cap: sepvol <= cap / 32)
                if (sepvol <= (int64_t)(okeys.size() / dense_fill_threshold) && sepvol <= cap_bytes / 32) {
                    out.vals.assign((size_t)sepvol, 0.0); out.dense = true;
                    for (size_t t = 0; t < okeys.size(); ++t) out.vals[okeys[t]] = ovals[t];
                } else { out.dense = false; out.keys.swap(okeys); out.vals.swap(ovals); }
            }
            // rescale: max stored entry into [1, 2) (exact power-of-two scaling, round trip checked); an all-zero message = exact zero mass in this component
            { double mx = 0.0; for (double x : out.vals) if (x > mx) mx = x; if (mx == 0.0) { stop = ZEROMASS; std::snprintf(reason, sizeof reason, "bucket %d produced an all-zero message: every evaluated row had an exact zero operand -> Z = 0 in this component", i); return false; } }
            out.exp2 = exp_in; if (!rescale(out, i, "message")) return false;
            if (out.label > (int64_t)C.max_label) C.max_label = out.label;
            C.messages_entries += out.vals.size(); live_msg_entries += (int64_t)out.vals.size(); if (live_msg_entries > C.max_live_message_entries) C.max_live_message_entries = live_msg_entries;
            // assign to the bucket of its lowest-ranked separator variable
            if (!out.scope.empty()) { int best = n; for (int w : out.scope) best = std::min(best, rank[w]); bucket_msg[best].push_back(i); }
        }
        return true;
    }
    // ---------------- reverse (all singleton numerators)
    vec<double> Nval; vec<int64_t> Nexp, Nlab; double Zval = 0; int64_t Zexp = 0, Zlab = 0;
    bool reverse() {
        vec<int> roots; for (int i = 0; i < n; ++i) if (msgs[i].scope.empty()) roots.push_back(i);
        // Z = product of roots (exclusion products give each root's adjoint); every product checked
        int R = (int)roots.size(); vec<double> pre(R + 1, 1.0), suf(R + 2, 1.0); vec<int64_t> preL(R + 1, 0), sufL(R + 2, 0), preE(R + 1, 0), sufE(R + 2, 0);
        for (int r = 0; r < R; ++r) { const Rel& m = msgs[roots[r]]; if (!mul(pre[r], m.vals[0], pre[r + 1])) return false; int64_t l1; if (!addl(m.label, 1, l1, "root label") || !addl(preL[r], l1, preL[r + 1], "root label") || !addl(preE[r], m.exp2, preE[r + 1], "root exponent")) return false; if (!poll(1)) return false; }
        for (int r = R - 1; r >= 0; --r) { const Rel& m = msgs[roots[r]]; if (!mul(suf[r + 1], m.vals[0], suf[r])) return false; int64_t l1; if (!addl(m.label, 1, l1, "root label") || !addl(sufL[r + 1], l1, sufL[r], "root label") || !addl(sufE[r + 1], m.exp2, sufE[r], "root exponent")) return false; if (!poll(1)) return false; }
        Zval = pre[R]; Zlab = preL[R]; Zexp = preE[R];
        if (!(Zval >= DMIN)) { stop = RANGE; std::snprintf(reason, sizeof reason, "Z is not a normal double"); return false; }
        vec<Rel> ctx(n);          // ctx[i] = g_i over msgs[i].scope, same representation / keys as msgs[i]
        for (int r = 0; r < R; ++r) { int i = roots[r]; Rel& g = ctx[i]; g.dense = true; g.scope.clear(); g.vol = 1; double gv; if (!mul(pre[r], suf[r + 1], gv)) return false; g.vals.assign(1, gv); int64_t s1; if (!addl(sufL[r + 1], 1, s1, "root context label") || !addl(preL[r], s1, g.label, "root context label") || !addl(preE[r], sufE[r + 1], g.exp2, "root context exponent")) return false; C.contexts_entries += 1; }
        vec<int64_t> noff(n + 1, 0); for (int v = 0; v < n; ++v) if (!addl(noff[v], card[v], noff[v + 1], "numerator offsets")) return false;
        Nval.assign((size_t)noff[n], 0.0); Nexp.assign(n, 0); Nlab.assign(n, 0);
        vec<int64_t> d(64);
        for (int i = n - 1; i >= 0; --i) {
            int v = order[i]; vec<Rel*> ins; for (int s : bucket_src[i]) ins.push_back(&sources[s]); for (int m : bucket_msg[i]) ins.push_back(&msgs[m]);
            Rel& g = ctx[i]; if (g.vals.empty()) { stop = BADPLAN; std::snprintf(reason, sizeof reason, "missing context for bucket %d", i); return false; }
            int64_t gexp = g.exp2;
            if (ins.empty()) { // isolated uniform variable: N_v(x) = g * 1 for each x
                for (int64_t x = 0; x < card[v]; ++x) { Nval[noff[v] + x] = g.vals[0]; } Nexp[v] = gexp; Nlab[v] = g.label; free_rel(g); if (!poll(card[v])) return false; continue;
            }
            Bag b; if (!make_bag(ins, v, b)) return false; if (b.vars.size() > 62) { stop = BADPLAN; std::snprintf(reason, sizeof reason, "bag of bucket %d has %zu variables (> 62)", i, b.vars.size()); return false; } int xpos = (int)b.vars.size() - 1; int64_t cx = card[v]; int k = (int)ins.size();
            vec<vec<int>> bp(ins.size()); for (size_t j = 0; j < ins.size(); ++j) { bp[j].resize(ins[j]->scope.size()); for (size_t a = 0; a < ins[j]->scope.size(); ++a) bp[j][a] = b.pos_of[ins[j]->scope[a]]; }
            int64_t lab_in = 0, exp_in = 0; for (auto r : ins) { if (!addl(lab_in, r->label, lab_in, "label sum") || !addl(exp_in, r->exp2, exp_in, "exponent sum")) return false; }
            // allocate child contexts (same representation as the child message), zero-filled; every allocation charged by the allocator
            for (size_t j = 0; j < ins.size(); ++j) { Rel* r = ins[j]; if (!r->is_message) continue; Rel& gc = ctx[r->child]; if (!gc.vals.empty()) continue; gc.scope = r->scope; gc.card = r->card; gc.stride = r->stride; gc.vol = r->vol; gc.dense = r->dense; if (!r->dense) gc.keys = r->keys; gc.vals.assign(r->vals.size(), 0.0); int64_t ge; if (!addl(gexp, exp_in, ge, "context exponent") || !subl(ge, r->exp2, gc.exp2, "context exponent")) return false; gc.label = 0; C.contexts_entries += gc.vals.size(); }
            if (!addl(gexp, exp_in, Nexp[v], "numerator exponent")) return false; int64_t termlab, t1; if (!addl(lab_in, (int64_t)k + 1, t1, "term label") || !addl(g.label, t1, termlab, "term label")) return false;   // prefix product of k factors from 1.0: k multiplications (+k); times g: +1
            vec<double> fv(k), pre_(k + 1), suf_(k + 1); vec<int64_t> ridx(k);
            // iterate the bag rows: dense if all dense, else the sparse support (recomputed: counted as reverse join work)
            auto visit = [&](int64_t idx) -> bool {
                digits(b, idx, d.data()); double gv; int64_t sk = idx / cx;
                if (g.dense) gv = g.vals[sk]; else { int64_t p = sparse_find(g, (uint64_t)sk); gv = p < 0 ? 0.0 : g.vals[p]; }
                ++C.reverse_rows; if (gv == 0.0) return poll(1);
                for (int j = 0; j < k; ++j) { const Rel& r = *ins[j]; int64_t ri = rel_index(r, bp[j], d.data()); ridx[j] = ri; double f; if (r.dense) f = r.vals[ri]; else { int64_t p = sparse_find(r, (uint64_t)ri); f = p < 0 ? 0.0 : r.vals[p]; } fv[j] = f; }
                // zero-safe prefix / suffix exclusion products: EVERY product is checked by operand provenance (an exact zero operand propagates; a nonzero x nonzero product must be normal)
                pre_[0] = 1.0; for (int j = 0; j < k; ++j) if (!mul(pre_[j], fv[j], pre_[j + 1])) return false;
                suf_[k] = 1.0; for (int j = k - 1; j >= 0; --j) if (!mul(suf_[j + 1], fv[j], suf_[j])) return false;
                double term; if (!mul(gv, pre_[k], term)) return false;
                if (term != 0.0) { double& acc = Nval[noff[v] + d[xpos]]; if (!add(acc, term, acc)) return false; }
                for (int j = 0; j < k; ++j) { const Rel& r = *ins[j]; if (!r.is_message) continue; double excl; if (!mul(pre_[j], suf_[j + 1], excl)) return false; if (excl == 0.0) continue;   // exact zero operand (some other factor of this row is exactly zero)
                    double t; if (!mul(gv, excl, t)) return false;
                    Rel& gc = ctx[r.child]; if (gc.dense) { if (!add(gc.vals[ridx[j]], t, gc.vals[ridx[j]])) return false; } else { int64_t p = sparse_find(gc, (uint64_t)ridx[j]); if (p < 0) { stop = FAULT; std::snprintf(reason, sizeof reason, "context key missing"); return false; } if (!add(gc.vals[p], t, gc.vals[p])) return false; } }
                return poll(1);
            };
            bool all_dense = true; for (auto r : ins) all_dense = all_dense && r->dense;
            int64_t rows_visited = 0;
            if (all_dense) { for (int64_t idx = 0; idx < b.vol; ++idx) { if (!visit(idx)) return false; ++rows_visited; } }
            else { vec<uint64_t> rows; if (!support_rows(ins, b, rows, cap_bytes / 16)) return false; for (uint64_t key : rows) { if (!visit((int64_t)key)) return false; ++rows_visited; } }
            if (!addl(termlab, std::max<int64_t>(0, rows_visited - 1), Nlab[v], "numerator label")) return false;   // sequential accumulation bound: at most rows_visited terms into one numerator entry
            for (size_t j = 0; j < ins.size(); ++j) { Rel* r = ins[j]; if (!r->is_message) continue; Rel& gc = ctx[r->child]; int64_t tl, t2; if (!subl(lab_in, r->label, t2, "context label") || !addl(t2, (int64_t)k + 1, t2, "context label") || !addl(g.label, t2, tl, "context label") || !addl(tl, std::max<int64_t>(0, rows_visited - 1), tl, "context label")) return false; gc.label = std::max(gc.label, tl); if ((int64_t)gc.label > (int64_t)C.max_label) C.max_label = gc.label; }
            if (Nlab[v] > (int64_t)C.max_label) C.max_label = Nlab[v];
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
// plan words (FORMAT 2): 2, n, card[n], norder (=n), order[n], nsrc, then per source: scope_len, scope[...], mode(0 dense/1 sparse), count, [keys count] (sparse),
// label, exp2 (the Python side's exact power-of-two scaling so that the max stored source entry lies in [1,2)); `count` doubles per source follow in `vals`.
int cex_run(const int64_t* plan, int64_t plen, const double* vals, int64_t nvals, int64_t cap_bytes, double deadline_abs, double dense_fill_threshold,
            double* Nout, int64_t* Nexp_out, int64_t* Nlab_out, double* Zout, int64_t* Zmeta, uint64_t* counters, int64_t ncounters, char* reason_out, int64_t reason_len) {
    if (g_busy.exchange(true)) { std::strncpy(reason_out, "concurrent invocation refused (one cex_run at a time)", (size_t)std::max<int64_t>(0, reason_len - 1)); if (reason_len > 0) reason_out[reason_len - 1] = 0; return FAULT; }
    Ledger L; L.cap = cap_bytes; g_ledger = &L;
    int stop = OK; char reason[200] = {0}; Counters C;
    {
        Exec E; E.cap_bytes = cap_bytes; E.deadline = deadline_abs; E.dense_fill_threshold = dense_fill_threshold;
        try {
            if (!E.check("entry")) throw 2;
            int64_t p = 0; auto rd = [&]() -> int64_t { if (p >= plen) throw 1; return plan[p++]; };
            auto bad = [&](const char* what) { E.stop = BADPLAN; std::snprintf(E.reason, sizeof E.reason, "invalid plan: %s", what); throw 2; };
            if (rd() != PLAN_FORMAT) bad("plan format (expected 2)");
            E.n = (int)rd(); if (E.n <= 0 || E.n > 100000) bad("variable count"); E.card.resize(E.n); for (int i = 0; i < E.n; ++i) { E.card[i] = rd(); if (E.card[i] <= 0 || E.card[i] > VOL_LIMIT) bad("cardinality"); }
            int64_t no = rd(); if (no != E.n) bad("order length"); E.order.resize(E.n); vec<int> seen(E.n, 0); for (int i = 0; i < E.n; ++i) { E.order[i] = (int)rd(); if (E.order[i] < 0 || E.order[i] >= E.n || seen[E.order[i]]) bad("order"); seen[E.order[i]] = 1; }
            E.rank.assign(E.n, 0); for (int i = 0; i < E.n; ++i) E.rank[E.order[i]] = i;
            int64_t nsrc = rd(); if (nsrc < 0 || nsrc > plen) bad("source count"); int64_t vp = 0; E.sources.resize(nsrc); E.bucket_src.assign(E.n, {}); E.bucket_msg.assign(E.n, {});
            for (int64_t s = 0; s < nsrc; ++s) {
                Rel& r = E.sources[s]; int64_t sl = rd(); if (sl <= 0 || sl > 60) bad("scope length (scalar factors are cancelled by the caller)"); r.scope.resize(sl); for (int64_t a = 0; a < sl; ++a) { r.scope[a] = (int)rd(); if (r.scope[a] < 0 || r.scope[a] >= E.n) bad("scope"); }
                r.card.resize(sl); for (int64_t a = 0; a < sl; ++a) r.card[a] = E.card[r.scope[a]]; r.stride.assign(sl, 1);
                for (int64_t a = sl - 2; a >= 0; --a) if (!mul_i(r.stride[a + 1], r.card[a + 1], r.stride[a]) || r.stride[a] > VOL_LIMIT) { E.stop = REPRESENTATION; std::snprintf(E.reason, sizeof E.reason, "source %lld: volume exceeds 2^62", (long long)s); throw 2; }
                if (!mul_i(r.stride[0], r.card[0], r.vol) || r.vol > VOL_LIMIT) { E.stop = REPRESENTATION; std::snprintf(E.reason, sizeof E.reason, "source %lld: volume exceeds 2^62", (long long)s); throw 2; }
                int64_t mode = rd(); int64_t cnt = rd(); r.dense = (mode == 0); if (cnt < 0 || cnt > r.vol) bad("source count");
                if (r.dense) { if (cnt != r.vol) bad("dense count"); r.vals.reserve((size_t)cnt); for (int64_t t = 0; t < cnt; ++t) { if (vp >= nvals) bad("values exhausted"); r.vals.push_back(vals[vp++]); if (!E.poll(1)) throw 2; } }
                else { r.keys.reserve((size_t)cnt); r.vals.reserve((size_t)cnt); for (int64_t t = 0; t < cnt; ++t) { int64_t kk = rd(); if (kk < 0 || kk >= r.vol) bad("sparse key"); r.keys.push_back((uint64_t)kk); if (!E.poll(1)) throw 2; } for (int64_t t = 1; t < cnt; ++t) if (r.keys[t] <= r.keys[t - 1]) bad("sparse keys not strictly increasing"); for (int64_t t = 0; t < cnt; ++t) { if (vp >= nvals) bad("values exhausted"); r.vals.push_back(vals[vp++]); if (!E.poll(1)) throw 2; } }
                r.label = rd(); if (r.label < 0 || r.label > META_LIMIT) bad("source label outside [0, 2^40] (ABI precondition)"); r.exp2 = rd(); if (r.exp2 < -META_LIMIT || r.exp2 > META_LIMIT) bad("source exponent outside [-2^40, 2^40] (ABI precondition)");
                for (double x : r.vals) { if (!(x >= 0.0) || !std::isfinite(x) || (x != 0.0 && x < DMIN)) { E.stop = RANGE; std::snprintf(E.reason, sizeof E.reason, "source %lld: value outside the supported binary64 range", (long long)s); throw 2; } } if (!E.poll(r.vals.size())) throw 2; E.C.conversions += r.vals.size();
                if (!E.rescale(r, (int)s, "source")) throw 2;                   // the Python side pre-scales (shift 0 expected); kept as an enforced invariant
                int best = E.n; for (int w : r.scope) best = std::min(best, E.rank[w]); E.bucket_src[best].push_back((int)s);
            }
            if (vp != nvals || p != plen) bad("plan / value length mismatch");
            if (!E.check("after plan parsing")) throw 2;
            if (!E.forward()) throw 2;
            if (!E.check("after forward")) throw 2;
            if (!E.reverse()) throw 2;
            if (!E.check("after reverse")) throw 2;
            int64_t off = 0; for (int v = 0; v < E.n; ++v) { for (int64_t x = 0; x < E.card[v]; ++x) Nout[off + x] = E.Nval[off + x]; Nexp_out[v] = E.Nexp[v]; Nlab_out[v] = E.Nlab[v]; off += E.card[v]; }
            Zout[0] = E.Zval; Zmeta[0] = E.Zexp; Zmeta[1] = E.Zlab;
            if (!E.check("before return")) throw 2;
        } catch (CapExceeded&) { E.stop = MEMORY; std::snprintf(E.reason, sizeof E.reason, "allocation boundary: %lld live + %lld requested exceeds cap %lld", (long long)L.live, (long long)L.refused_request, (long long)L.cap); }
          catch (std::bad_alloc&) { E.stop = MEMORY; std::snprintf(E.reason, sizeof E.reason, "bad_alloc"); }
          catch (int) { if (E.stop == OK) { E.stop = BADPLAN; std::snprintf(E.reason, sizeof E.reason, "plan exhausted early"); } }
          catch (...) { if (E.stop == OK) E.stop = FAULT; }
        stop = E.stop; std::memcpy(reason, E.reason, sizeof reason); C = E.C;
    }   // Exec destroyed here: every container released through the allocator
    C.peak_logical_bytes = L.peak; C.logical_bytes = L.live; C.allocations = L.allocs; g_ledger = nullptr; g_busy = false;
    uint64_t cv[] = {C.forward_rows, C.reverse_rows, C.mults, C.adds, C.join_index_rows, C.join_probes, C.join_rows_generated, C.dense_rows, C.sparse_rows, C.rescale_entries, C.polls, C.messages_entries, C.contexts_entries, C.max_label, C.buckets_dense, C.buckets_sparse, C.conversions, (uint64_t)C.peak_logical_bytes, (uint64_t)C.logical_bytes, (uint64_t)C.peak_join_rows, (uint64_t)C.max_live_message_entries, C.allocations};
    for (int64_t i = 0; i < ncounters && i < (int64_t)(sizeof cv / sizeof cv[0]); ++i) counters[i] = cv[i];
    std::strncpy(reason_out, reason, (size_t)std::max<int64_t>(0, reason_len - 1)); if (reason_len > 0) reason_out[reason_len - 1] = 0;
    return stop;
}
const char* cex_schedule_id() { return "CEX/nonneg-bucket-contraction-all-singleton-reverse/v1.4-checked-metadata-abi-bounds"; }
}
