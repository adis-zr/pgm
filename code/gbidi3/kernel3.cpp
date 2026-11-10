// GENERAL_BIDI_COMPLETE_V3 native executor (10 Nov 2026). ONE canonical indexed IR executed through ONE semantic interface:
//     VALUE(node, index)            pure primal evaluation of one entry (never adds a numerator)
//     PULLBACK(node, index, delta)  local adjoint: external-input deltas + owned original-marker contributions
// Node kinds (brief §4): SOURCE (exact factor occurrence), MARKER (one per reduced variable; value 1, pullback -> N[var][state]), CONSTANT,
// GATHER (total checked coordinate map: permutation / broadcast / FIXED slice / response-class map with exact scale), ADD (aligned pointwise sum),
// MUL (pointwise product with explicit per-child axis projection), REDUCE (sum over eliminated axes, ordered remaining axes). LINEAR and REGION are
// Python-side macros lowered to these kinds before execution (documented in gbidi3/ir.py).
// Storage / execution per node (R8: a storage change never changes semantics): STREAM (recompute, zero memo), DENSE (materialized in blocks of
// <= GB3_BLOCK output entries, reserved block by block), SPARSE (support-indexed rows produced by a bounded JOIN block over the node's inputs; a row
// absent from a COMPLETE join has an exactly-zero input), CACHE (byte-capped LRU of complete scalar values keyed by (attempt, node, index)); an
// optional LIST demand hint restricts what a DENSE node stores (reads outside are streamed, never assumed zero).
// Repaired mechanisms preserved from GENERAL_BIDI_V2 (kernel.cpp 88a3e325): explicit frame stack (no host recursion), every allocation reserved
// in exactly one of five categories BEFORE it happens, C-ABI exception containment (bad_alloc -> GB_MEMORY, else GB_FAULT), per-primitive polling
// (POLL_OPS = 4096 charged units), binary64 per-value exact error labels with the [2*DBL_MIN, DBL_MAX/2] range check on EVERY rounded positive result
// and the 2^52 label cap, fp-environment probes, MPFR exponent-range configuration + flag inspection, exact integer reference stream.
// New: multiple additive consumers of one node (every USE edge contributes to the pullback), sparse join blocks with duplicate aggregation and
// sparse reverse scatter, dense blocks, byte-capped LRU with pinned-by-copy frame operands, pending adjoints with PENDING/ACTIVE/DRAINED states,
// early flush under the pending cap and late-increment propagation, one materialized-to-stream downgrade per node per attempt, exact fallback over the
// ORIGINAL evidence-restricted factors.
#include <cstdint>
#include <cstdlib>
#include <cstring>
#include <cmath>
#include <ctime>
#include <cfenv>
#include <cfloat>
#include <vector>
#include <unordered_map>
#include <deque>
#include <list>
#include <algorithm>
#include <atomic>
#include <new>
#include <stdexcept>
#include <gmp.h>
#include <mpfr.h>

static const char* GB3_SCHEDULE = "GENERAL_BIDI_COMPLETE_V3/indexed-ir-frames-blocks-sparse-lru-deltas/v3";
extern "C" const char* gb3_schedule_id() { return GB3_SCHEDULE; }

enum Stop : int { GB_OK = 0, GB_DEADLINE = 1, GB_MEMORY = 2, GB_OVERFLOW = 3, GB_RANGE = 4, GB_BADPROG = 5, GB_FAULT = 6, GB_FPENV = 7, GB_LABEL = 8 };
struct BadProg : std::runtime_error { BadProg(const char* m) : std::runtime_error(m) {} };
static double now_mono() { struct timespec ts; clock_gettime(CLOCK_MONOTONIC, &ts); return ts.tv_sec + 1e-9 * ts.tv_nsec; }
static const uint64_t POLL_OPS = 4096;
static const int64_t GB3_BLOCK = 1024;                         // ordinary block: at most 1,024 OUTPUT entries (brief §8)

enum Kind : int { K_SOURCE = 0, K_MARKER = 1, K_CONSTANT = 2, K_GATHER = 3, K_ADD = 4, K_MUL = 5, K_REDUCE = 6 };
enum Storage : int { S_STREAM = 0, S_DENSE = 1, S_SPARSE = 2, S_CACHE = 3 };

// ------------------------------------------------------------------------------------------------------------ numeric policies (unchanged contract)
struct Dbl {                    // nearest binary64 with EXACT per-value error labels: (1-u)^E v <= vhat <= (1+u)^E v for every performed operation
    struct T { double v; uint64_t e; };
    static bool range_fault; static bool label_fault;
    static const uint64_t E_MAX = (uint64_t)1 << 52;
    static inline void check(double x, uint64_t e) { if (!(x >= 2 * DBL_MIN && x <= DBL_MAX / 2)) range_fault = true; if (e > E_MAX) label_fault = true; }
    static void init(T& x, int) { x.v = 0.0; x.e = 0; }
    static void clear(T&) {}
    static void set_zero(T& x) { x.v = 0.0; x.e = 0; }
    static void set_one(T& x) { x.v = 1.0; x.e = 0; }
    static void set_q(T& x, mpq_t q, int) { (void)q; x.v = 0.0; x.e = 0; }
    static void add(T& r, const T& a, const T& b) { if (a.v == 0.0) { r = b; return; } if (b.v == 0.0) { r = a; return; } T t; t.v = a.v + b.v; t.e = (a.e > b.e ? a.e : b.e) + 1; check(t.v, t.e); r = t; }
    static void mul(T& r, const T& a, const T& b) { if (a.v == 0.0 || b.v == 0.0) { r.v = 0.0; r.e = 0; return; } T t; t.v = a.v * b.v; t.e = a.e + b.e + 1; check(t.v, t.e); r = t; }
    static void copy(T& d, const T& s) { d = s; }
    static bool is_zero(const T& x) { return x.v == 0.0; }
    static bool finite(const T& x) { return std::isfinite(x.v) && x.v >= 0.0; }
    static size_t bytes(int) { return sizeof(T); }
};
bool Dbl::range_fault = false; bool Dbl::label_fault = false;
struct Ival {                   // outward MPFR interval [lo, hi] (the general route)
    struct T { mpfr_t lo, hi; };
    static void init(T& x, int p) { mpfr_init2(x.lo, p); mpfr_init2(x.hi, p); mpfr_set_zero(x.lo, 1); mpfr_set_zero(x.hi, 1); }
    static void clear(T& x) { mpfr_clear(x.lo); mpfr_clear(x.hi); }
    static void set_zero(T& x) { mpfr_set_zero(x.lo, 1); mpfr_set_zero(x.hi, 1); }
    static void set_one(T& x) { mpfr_set_ui(x.lo, 1, MPFR_RNDD); mpfr_set_ui(x.hi, 1, MPFR_RNDU); }
    static void set_q(T& x, mpq_t q, int) { mpfr_set_q(x.lo, q, MPFR_RNDD); mpfr_set_q(x.hi, q, MPFR_RNDU); }
    static void add(T& r, const T& a, const T& b) { mpfr_add(r.lo, a.lo, b.lo, MPFR_RNDD); mpfr_add(r.hi, a.hi, b.hi, MPFR_RNDU); }
    static void mul(T& r, const T& a, const T& b) { mpfr_mul(r.lo, a.lo, b.lo, MPFR_RNDD); mpfr_mul(r.hi, a.hi, b.hi, MPFR_RNDU); }
    static void copy(T& d, const T& s) { mpfr_set(d.lo, s.lo, MPFR_RNDD); mpfr_set(d.hi, s.hi, MPFR_RNDU); }
    static bool is_zero(const T& x) { return mpfr_zero_p(x.hi); }
    static bool finite(const T& x) { return mpfr_number_p(x.lo) && mpfr_number_p(x.hi) && mpfr_sgn(x.lo) >= 0; }
    static size_t bytes(int p) { return 2 * (sizeof(mpfr_t) + 8 * (size_t)((p + 63) / 64)); }
};

// ------------------------------------------------------------------------------------------------------------ program description
struct FactorD { std::vector<int> scope; std::vector<int> card; std::vector<int64_t> stride; int64_t entries; int64_t val_off; };
struct GAxis { int out_pos; int fixed; int64_t cls_off; int64_t ratio_off; };    // per CHILD axis of a GATHER: reads out axis out_pos (or FIXED state when out_pos == -1); optional class map / ratios over the OUT axis raw states
struct NodeD {
    int kind; std::vector<int> axes; std::vector<int64_t> card; int64_t volume;
    int storage; int demand_kind; std::vector<int64_t> demand;                     // demand_kind: 0 FULL, 1 LIST, 2 EMPTY (DENSE only)
    int fid; int var; int64_t val_off;                                             // SOURCE / MARKER / CONSTANT
    std::vector<int> children;                                                     // GATHER (1) / ADD / MUL / REDUCE (1)
    std::vector<GAxis> gaxes;                                                      // GATHER
    std::vector<std::vector<int>> proj;                                            // MUL: per child, per child axis -> out pos ; REDUCE: child axis -> out pos or -1 (eliminated)
    std::vector<int64_t> elim_card;                                                // REDUCE: cardinalities of the eliminated child axes in child-axis order
    std::vector<int64_t> reps_off;                                                 // REDUCE: per child axis, offset into cls of the representative map (core index -> child raw index) or -1 (identity)
    int64_t elim_volume;
    int downgraded;                                                                // 1 once materialized -> STREAM (one per attempt)
    uint32_t uses;                                                                 // number of consumer USE edges (0 for roots)
};
struct Caps { uint64_t values, index, reverse, pending, scratch; };
struct Counters {
    uint64_t value_frames, pullback_frames, frames_combined, max_frame_depth, polls;
    uint64_t mults, adds, lookups, zero_skips;
    uint64_t source_reads, marker_updates, gather_visits, add_visits, mul_rows, reduce_terms;
    uint64_t stream_reevals, reads_outside_demand, regenerated_values;
    uint64_t dense_blocks, entries_materialized, entries_stored_planned, sparse_rows_joined, sparse_output_rows, sparse_join_discarded;
    uint64_t cache_hits, cache_misses, cache_evictions, cache_inserts;
    uint64_t adjoint_adds, slots_drained, early_flushes, late_increments, pending_peak_bytes;
    uint64_t downgrades, root_ops, numerator_adds;
};
static long test_emin = 0, test_emax = 0; static int test_bad_alloc = 0; static uint64_t test_leaf_label = 1; static int test_branch_fault = 0; static int test_ref_fault = 0;

// ------------------------------------------------------------------------------------------------------------ executor
template <class P> struct Exec {
    typedef typename P::T Num;
    int prec; int nvars; std::vector<int64_t> vcard; std::vector<FactorD> F; std::vector<NodeD> N; std::vector<int> roots; std::vector<int64_t> cls;
    std::vector<Num> fvals, ratios, consts; Num scale, Z;
    // storage
    std::vector<std::vector<std::vector<Num>>> dense;       // per node: blocks of values (DENSE); block b holds entries [b*GB3_BLOCK, ...) of the stored sequence
    std::vector<int64_t> dense_done;                        // per node: number of stored entries completed (materialization progress)
    std::vector<std::unordered_map<int64_t, int64_t>> dpos; // per node: LIST demand index -> stored position ; SPARSE: core index -> row
    std::vector<std::vector<Num>> sparse_vals;              // per node: SPARSE row values
    std::vector<std::vector<int64_t>> sparse_idx;           // per node: SPARSE row core indices (sorted after the join)
    std::vector<char> sparse_complete;                      // per node: 1 once the join block finished (absence == exact zero)
    std::vector<std::vector<Num>> adj;                      // per node (materialized): pending adjoint per stored slot
    std::vector<std::vector<uint8_t>> adj_state;            // 0 empty, 1 PENDING(nonzero), 2 ACTIVE, 3 DRAINED
    std::vector<char> adj_alloc;                            // adj array allocated for the node
    std::vector<std::vector<Num>> Nx;                       // per reduced variable: numerators
    // cache (LRU of complete scalar values)
    struct CEntry { int node; int64_t idx; Num v; typename std::list<std::pair<int, int64_t>>::iterator lru; };
    std::unordered_map<uint64_t, CEntry> cache; std::list<std::pair<int, int64_t>> lru; uint64_t cache_bytes = 0, cache_cap = 0;
    // accounting
    Caps caps; uint64_t used_values = 0, used_index = 0, used_reverse = 0, used_pending = 0, used_scratch = 0, peak_scratch = 0, peak_pending = 0; Counters C{}; double deadline; int stop = GB_OK; uint64_t ops_since_poll = 0;
    std::deque<Num> scratch; size_t top = 0;
    std::atomic<uint64_t> snap[8]; int phase_tag = 0; int active_node = -1;
    // ---- explicit frames
    struct Frame { int mode; int nn; int64_t idx; int phase; int i; int last; int64_t t; size_t base; size_t saved_top; std::vector<int64_t> d; std::vector<int8_t> unresolved; Num* dst; };
    std::deque<Frame> frames;                               // deque: push_back never invalidates references to live frames (step() holds one)

    Exec(int p) : prec(p) { P::init(scale, p); P::init(Z, p); for (auto& s : snap) s.store(0); }
    ~Exec() { for (auto& nb : dense) for (auto& b : nb) for (auto& x : b) P::clear(x); for (auto& v : sparse_vals) for (auto& x : v) P::clear(x); for (auto& v : adj) for (auto& x : v) P::clear(x); for (auto& v : Nx) for (auto& x : v) P::clear(x); for (auto& x : fvals) P::clear(x); for (auto& x : ratios) P::clear(x); for (auto& x : consts) P::clear(x); for (auto& x : scratch) P::clear(x); for (auto& kv : cache) P::clear(kv.second.v); P::clear(scale); P::clear(Z); }

    inline void snapshot() { snap[0].store(C.value_frames); snap[1].store(C.pullback_frames); snap[2].store(C.mul_rows); snap[3].store(C.reduce_terms); snap[4].store(frames.size()); snap[5].store((uint64_t)(active_node < 0 ? 0 : active_node)); snap[6].store(used_scratch + used_values + used_index + used_reverse + used_pending); snap[7].store((uint64_t)phase_tag); }
    inline bool poll(uint64_t work) { ops_since_poll += work; if (ops_since_poll >= POLL_OPS) { ops_since_poll = 0; ++C.polls; snapshot(); if (now_mono() > deadline) { stop = GB_DEADLINE; return false; } } return true; }
    bool reserve(uint64_t& used, uint64_t cap, uint64_t bytes) { if (bytes > cap || used > cap - bytes) { stop = GB_MEMORY; return false; } used += bytes; return true; }
    void release(uint64_t& used, uint64_t bytes) { used = used > bytes ? used - bytes : 0; }
    bool frame_alloc(size_t n, size_t& base) {
        if (test_bad_alloc) { test_bad_alloc = 0; throw std::bad_alloc(); }
        base = top; size_t need = top + n;
        if (need > scratch.size()) { uint64_t bytes = (uint64_t)(need - scratch.size()) * P::bytes(prec); if (!reserve(used_scratch, caps.scratch, bytes)) return false; while (scratch.size() < need) { scratch.emplace_back(); P::init(scratch.back(), prec); } }
        top = need; if (used_scratch > peak_scratch) peak_scratch = used_scratch; return true;
    }
    Num& at(size_t i) { return scratch[i]; }

    // ---- indexing helpers
    void digits(const NodeD& n, int64_t idx, std::vector<int64_t>& d) { d.resize(n.card.size()); for (int k = (int)n.card.size() - 1; k >= 0; --k) { d[k] = idx % n.card[k]; idx /= n.card[k]; } }
    static int64_t compose(const std::vector<int64_t>& card, const std::vector<int64_t>& d) { int64_t idx = 0; for (size_t k = 0; k < card.size(); ++k) idx = idx * card[k] + d[k]; return idx; }
    // child index for MUL child ci of node n at digits d
    int64_t mul_child_index(const NodeD& n, int ci, const std::vector<int64_t>& d) const { const NodeD& c = N[n.children[ci]]; int64_t idx = 0; const std::vector<int>& pr = n.proj[ci]; for (size_t k = 0; k < c.card.size(); ++k) idx = idx * c.card[k] + d[pr[k]]; return idx; }
    // child index for REDUCE at out digits d and eliminated tuple t (mixed radix over elim_card)
    int64_t reduce_child_index(const NodeD& n, const std::vector<int64_t>& d, int64_t t) const { const NodeD& c = N[n.children[0]]; int64_t idx = 0; int64_t e[64]; int ne = (int)n.elim_card.size(); for (int k = ne - 1; k >= 0; --k) { e[k] = t % n.elim_card[k]; t /= n.elim_card[k]; } int ei = 0; for (size_t k = 0; k < c.card.size(); ++k) { int p = n.proj[0][k]; int64_t s; if (p >= 0) s = n.reps_off[k] >= 0 ? cls[n.reps_off[k] + d[p]] : d[p]; else s = e[ei++]; idx = idx * c.card[k] + s; } return idx; }
    // GATHER: child index and scale (product of the per-axis ratios at the raw out states)
    int64_t gather_child_index(const NodeD& n, const std::vector<int64_t>& d, Num& sc) { const NodeD& c = N[n.children[0]]; int64_t idx = 0; P::set_one(sc); for (size_t k = 0; k < c.card.size(); ++k) { const GAxis& g = n.gaxes[k]; int64_t s; if (g.out_pos < 0) s = g.fixed; else { int64_t raw = d[g.out_pos]; s = g.cls_off >= 0 ? cls[g.cls_off + raw] : raw; if (g.ratio_off >= 0) { P::mul(sc, sc, ratios[g.ratio_off + raw]); ++C.mults; } } idx = idx * c.card[k] + s; } return idx; }

    // ---- stored value lookup: returns 1 if the entry is available in storage (copied into out), 0 if it must be computed, 2 if proven exact zero (complete sparse)
    int lookup(int nn, int64_t idx, Num& out) {
        const NodeD& n = N[nn];
        if (n.storage == S_DENSE && !n.downgraded) {
            int64_t pos;
            if (n.demand_kind == 0) pos = idx; else if (n.demand_kind == 2) return 0; else { auto it = dpos[nn].find(idx); if (it == dpos[nn].end()) { ++C.reads_outside_demand; return 0; } pos = it->second; }
            if (pos >= dense_done[nn]) return 0;
            ++C.lookups; P::copy(out, dense[nn][pos / GB3_BLOCK][pos % GB3_BLOCK]); return 1;
        }
        if (n.storage == S_SPARSE && sparse_complete[nn]) { auto it = dpos[nn].find(idx); ++C.lookups; if (it == dpos[nn].end()) return 2; P::copy(out, sparse_vals[nn][it->second]); return 1; }
        if (n.storage == S_CACHE) { uint64_t key = ((uint64_t)nn << 48) ^ (uint64_t)idx; auto it = cache.find(key); if (it != cache.end() && it->second.node == nn && it->second.idx == idx) { ++C.cache_hits; ++C.lookups; lru.splice(lru.begin(), lru, it->second.lru); P::copy(out, it->second.v); return 1; } ++C.cache_misses; return 0; }
        return 0;
    }
    void cache_evict_one() { auto back = lru.back(); uint64_t k2 = ((uint64_t)back.first << 48) ^ (uint64_t)back.second; auto it = cache.find(k2); if (it != cache.end()) { P::clear(it->second.v); cache.erase(it); } lru.pop_back(); uint64_t need = P::bytes(prec) + 96; cache_bytes -= need; release(used_values, need); ++C.cache_evictions; }
    void cache_insert(int nn, int64_t idx, const Num& v) {                                      // byte-capped LRU; every entry is reserved in the VALUE category before insertion
        uint64_t key = ((uint64_t)nn << 48) ^ (uint64_t)idx; if (cache.count(key)) return;
        uint64_t need = P::bytes(prec) + 96;                                                                     // value + map node + lru node (documented proxy)
        if (need > cache_cap) return;
        while (cache_bytes + need > cache_cap && !lru.empty()) cache_evict_one();
        while (!lru.empty() && (need > caps.values || used_values > caps.values - need)) cache_evict_one();
        if (need > caps.values || used_values > caps.values - need) return;                                     // the category is full of pinned storage: no insertion (never a stop)
        used_values += need;
        CEntry e; e.node = nn; e.idx = idx; P::init(e.v, prec); P::copy(e.v, v); lru.push_front({nn, idx}); e.lru = lru.begin(); cache.emplace(key, std::move(e)); cache_bytes += need; ++C.cache_inserts;
    }

    // ---- frames. mode 0 VALUE (dst), 1 PULLBACK (h in scratch), 2 VALUE+PULLBACK (both: used for the last streamed child of a MUL pullback row)
    // scratch layouts from base: SOURCE/MARKER/CONSTANT: 1 ; GATHER: sc, h, tmp (3) ; ADD: acc, h, tmp (3) ; MUL(k children): inp[k], pre[k+1], suf[k+1], g, row, sc, h, acc (3k+7)
    // REDUCE: acc, h, tmp (3)
    size_t need_slots(const NodeD& n) const { switch (n.kind) { case K_MUL: return 3 * n.children.size() + 7; case K_GATHER: case K_ADD: case K_REDUCE: return 3; default: return 1; } }
    bool push(int mode, int nn, int64_t idx, Num* dst, const Num* h) {
        const NodeD& n = N[nn]; size_t need = need_slots(n);
        if (!reserve(used_scratch, caps.scratch, 2 * sizeof(Frame) + (n.card.size() + n.children.size()) * sizeof(int64_t))) return false;   // frame record + deque block share (proxy)
        Frame f; f.mode = mode; f.nn = nn; f.idx = idx; f.phase = 0; f.i = 0; f.last = -1; f.t = 0; f.saved_top = top; f.dst = dst; f.unresolved.assign(n.children.size(), 0);
        if (!frame_alloc(need, f.base)) return false;
        digits(n, idx, f.d);
        size_t k = n.children.size();
        if (n.kind == K_MUL) { P::set_zero(at(f.base + 3 * k + 6)); if (mode != 0) P::copy(at(f.base + 3 * k + 5), *h); }
        else if (n.kind == K_GATHER || n.kind == K_ADD || n.kind == K_REDUCE) { P::set_zero(at(f.base)); if (mode != 0) P::copy(at(f.base + 1), *h); }
        if (mode == 0) ++C.value_frames; else { ++C.pullback_frames; if (mode == 2) { ++C.value_frames; ++C.frames_combined; } }
        frames.push_back(std::move(f)); if (frames.size() > C.max_frame_depth) C.max_frame_depth = frames.size();
        active_node = nn; return poll(1);
    }
    void pop() { Frame& f = frames.back(); top = f.saved_top; release(used_scratch, 2 * sizeof(Frame) + (N[f.nn].card.size() + N[f.nn].children.size()) * sizeof(int64_t)); frames.pop_back(); }

    // request a child's VALUE into dst: served from storage, or by pushing a VALUE frame (returns 1 pushed, 0 resolved, -1 stop)
    int child_value(int cn, int64_t cidx, Num& dst) {
        int r = lookup(cn, cidx, dst);
        if (r == 1) return 0;
        if (r == 2) { P::set_zero(dst); return 0; }
        const NodeD& c = N[cn];
        if (c.kind == K_MARKER) { P::set_one(dst); return 0; }
        if (c.kind == K_CONSTANT) { P::copy(dst, consts[c.val_off]); ++C.lookups; return 0; }
        if (c.kind == K_SOURCE) { const FactorD& fa = F[c.fid]; P::copy(dst, fvals[fa.val_off + cidx]); ++C.lookups; ++C.source_reads; return 0; }
        if (c.storage != S_STREAM) ++C.stream_reevals; if (c.storage == S_DENSE || c.storage == S_SPARSE) ++C.regenerated_values;
        return push(0, cn, cidx, &dst, nullptr) ? 1 : -1;
    }
    // VALUE and PULLBACK of child cn at cidx in ONE pass (combined frame, mode 2): stored -> value from storage + delta to its slot; leaf -> direct; else push mode 2
    int child_both(int cn, int64_t cidx, Num& dst, const Num& h) {
        int r = lookup(cn, cidx, dst);
        if (r == 1) return child_pull(cn, cidx, h);
        if (r == 2) { P::set_zero(dst); return 0; }                                                  // complete-sparse absence: an exactly-zero nonnegative polynomial, all its marker derivatives vanish (P3)
        const NodeD& c = N[cn];
        if (c.kind == K_MARKER) { P::set_one(dst); P::add(Nx[c.var][cidx], Nx[c.var][cidx], h); ++C.adds; ++C.numerator_adds; ++C.marker_updates; return 0; }
        if (c.kind == K_CONSTANT) { P::copy(dst, consts[c.val_off]); ++C.lookups; return 0; }
        if (c.kind == K_SOURCE) { P::copy(dst, fvals[F[c.fid].val_off + cidx]); ++C.lookups; ++C.source_reads; return 0; }
        if (c.storage != S_STREAM) ++C.stream_reevals; if (c.storage == S_DENSE || c.storage == S_SPARSE) ++C.regenerated_values;
        return push(2, cn, cidx, &dst, &h) ? 1 : -1;
    }
    // deliver a delta h to child cn at cidx: pending slot (materialized) or immediate PULLBACK frame (returns 1 pushed, 0 done, -1 stop)
    int child_pull(int cn, int64_t cidx, const Num& h) {
        const NodeD& c = N[cn];
        if (c.kind == K_SOURCE || c.kind == K_CONSTANT) return 0;
        if (c.kind == K_MARKER) { P::add(Nx[c.var][cidx], Nx[c.var][cidx], h); ++C.adds; ++C.numerator_adds; ++C.marker_updates; return 0; }
        if (P::is_zero(h)) return 0;
        int64_t slot = -1;
        if (c.storage == S_DENSE && !c.downgraded) { if (c.demand_kind == 0) slot = cidx; else if (c.demand_kind == 1) { auto it = dpos[cn].find(cidx); if (it != dpos[cn].end()) slot = it->second; } if (slot >= dense_done[cn]) slot = -1; }
        else if (c.storage == S_SPARSE && sparse_complete[cn]) { auto it = dpos[cn].find(cidx); if (it == dpos[cn].end()) return 0; slot = it->second; }   // absent row: exact zero value; a zero node has zero marker polynomial along this edge? NO: zero VALUE does not zero the pullback into the children -- handled below
        if (slot >= 0) {
            if (!ensure_adj(cn)) {                                                                 // pending category full: ONE bounded early flush (never nested), then retry; else deliver immediately
                if (flushing || stop != GB_MEMORY) { if (stop == GB_MEMORY) stop = GB_OK; return push(1, cn, cidx, nullptr, &h) ? 1 : -1; }
                stop = GB_OK; if (!flush_all_pending()) return -1;
                if (!ensure_adj(cn)) { stop = GB_OK; return push(1, cn, cidx, nullptr, &h) ? 1 : -1; }
            }
            P::add(adj[cn][slot], adj[cn][slot], h); ++C.adds; ++C.adjoint_adds; if (adj_state[cn][slot] == 3) ++C.late_increments; adj_state[cn][slot] = 1; return 0;
        }
        return push(1, cn, cidx, nullptr, &h) ? 1 : -1;
    }
    bool ensure_adj(int cn) {
        if (adj_alloc[cn]) return true;
        int64_t cnt = stored_count(cn); uint64_t bytes = (uint64_t)cnt * (P::bytes(prec) + 1);
        if (!reserve(used_pending, caps.pending, bytes)) return false;
        adj[cn].resize(cnt); for (auto& x : adj[cn]) P::init(x, prec); adj_state[cn].assign(cnt, 0); adj_alloc[cn] = 1; if (used_pending > peak_pending) peak_pending = used_pending; return true;
    }
    int64_t stored_count(int nn) const { const NodeD& n = N[nn]; if (n.storage == S_DENSE) return dense_done[nn]; if (n.storage == S_SPARSE) return (int64_t)sparse_vals[nn].size(); return 0; }
    int64_t stored_index(int nn, int64_t slot) const { const NodeD& n = N[nn]; if (n.storage == S_DENSE) return n.demand_kind == 0 ? slot : n.demand[slot]; return sparse_idx[nn][slot]; }

    // ---- one scheduling step of the top frame
    // run the frame machine until the stack is back at `floor` (frames below the floor belong to an enclosing computation and are never touched)
    bool run(size_t floor) {
        while (frames.size() > floor) {
            Frame& f = frames.back(); const NodeD& n = N[f.nn]; active_node = f.nn;
            bool done = false;
            if (!step(f, n, done)) return false;
            if (done) { if (f.mode != 1 && n.storage == S_CACHE && f.dst) cache_insert(f.nn, f.idx, *f.dst); pop(); }
        }
        return true;
    }
    void abandon_frames(size_t floor) { while (frames.size() > floor) pop(); }
    int flushing = 0;
    bool step(Frame& f, const NodeD& n, bool& done) {
        size_t k = n.children.size();
        switch (n.kind) {
        case K_SOURCE: { if (f.mode != 1) { const FactorD& fa = F[n.fid]; P::copy(*f.dst, fvals[fa.val_off + f.idx]); ++C.source_reads; } done = true; return poll(1); }
        case K_CONSTANT: { if (f.mode != 1) P::copy(*f.dst, consts[n.val_off]); done = true; return poll(1); }
        case K_MARKER: { if (f.mode != 1) P::set_one(*f.dst); if (f.mode != 0) { P::add(Nx[n.var][f.idx], Nx[n.var][f.idx], at(f.base)); ++C.adds; ++C.numerator_adds; ++C.marker_updates; } done = true; return poll(1); }
        case K_GATHER: {
            const size_t SC = f.base, H = f.base + 1, TMP = f.base + 2; int cn = n.children[0];
            if (f.phase == 0) { ++C.gather_visits; int64_t cidx = gather_child_index(n, f.d, at(SC)); f.t = cidx; f.phase = 1;
                if (f.mode == 2) { P::mul(at(H), at(H), at(SC)); ++C.mults; int r = child_both(cn, cidx, at(TMP), at(H)); if (r < 0) return false; if (r == 1) return true; }
                else if (f.mode == 0) { int r = child_value(cn, cidx, at(TMP)); if (r < 0) return false; if (r == 1) return true; } }
            if (f.phase == 1) { f.phase = 2;
                if (f.mode != 1) { P::mul(*f.dst, at(SC), at(TMP)); ++C.mults; }
                if (f.mode == 1) { P::mul(at(TMP), at(H), at(SC)); ++C.mults; int64_t t = f.t; int r = child_pull(cn, t, at(TMP)); if (r < 0) return false; if (r == 1) return true; } }
            done = true; return poll(1);
        }
        case K_ADD: {
            const size_t ACC = f.base, H = f.base + 1, TMP = f.base + 2; ++C.add_visits;
            // phase 0: values of children one by one (mode 0/2); phase 1: pullbacks (mode 1/2)
            while (f.phase == 0) {
                if (f.i >= (int)k) { if (f.mode != 1) P::copy(*f.dst, at(ACC)); f.phase = (f.mode == 2 ? 2 : 1); f.i = 0; break; }
                if (f.mode == 1) { f.phase = 1; f.i = 0; break; }
                if (f.last == 1) { P::add(at(ACC), at(ACC), at(TMP)); ++C.adds; f.last = -1; f.i++; continue; }
                f.last = 1; int r = (f.mode == 2) ? child_both(n.children[f.i], f.idx, at(TMP), at(H)) : child_value(n.children[f.i], f.idx, at(TMP)); if (r < 0) return false; if (r == 1) return true;
            }
            while (f.phase == 1) {
                if (f.mode == 0 || f.i >= (int)k) { done = true; return poll(1); }
                int ci = f.i; f.i++; int r = child_pull(n.children[ci], f.idx, at(H)); if (r < 0) return false; if (r == 1) return true;
            }
            done = true; return poll(1);
        }
        case K_REDUCE: {
            const size_t ACC = f.base, H = f.base + 1, TMP = f.base + 2; int cn = n.children[0];
            // phase 0: sum child values over eliminated tuples t (mode 0/2); phase 1: pullbacks over t (mode 1/2)
            while (f.phase == 0) {
                if (f.mode == 1) { f.phase = 1; f.t = 0; break; }
                if (f.last == 1) { P::add(at(ACC), at(ACC), at(TMP)); if (test_branch_fault == 2 && f.t == 0) P::add(at(ACC), at(ACC), at(TMP)); ++C.adds; ++C.reduce_terms; f.last = -1; f.t++; if (!poll(1)) return false; }   // fault 2: the first tuple added twice, counter unchanged
                if (f.t >= n.elim_volume) { P::copy(*f.dst, at(ACC)); f.phase = (f.mode == 2 ? 2 : 1); f.t = 0; break; }
                if (test_branch_fault == 1 && f.t == 0) { ++C.reduce_terms; f.t++; continue; }                            // fault 1: the first tuple omitted, counter forged as visited
                int64_t cidx = reduce_child_index(n, f.d, f.t); f.last = 1; int r = (f.mode == 2) ? child_both(cn, cidx, at(TMP), at(H)) : child_value(cn, cidx, at(TMP)); if (r < 0) return false; if (r == 1) return true;
            }
            while (f.phase == 1) {
                if (f.mode == 0 || f.t >= n.elim_volume) { done = true; return poll(1); }
                int64_t cidx = reduce_child_index(n, f.d, f.t); f.t++; int r = child_pull(cn, cidx, at(H)); if (r < 0) return false; if (r == 1) return true; if (!poll(1)) return false;
            }
            done = true; return poll(1);
        }
        case K_MUL: {
            const size_t PRE = f.base + k, SUF = f.base + 2 * k + 1, G = f.base + 3 * k + 2, ROW = f.base + 3 * k + 3, SC = f.base + 3 * k + 4, H = f.base + 3 * k + 5, ACC = f.base + 3 * k + 6; (void)SC;
            if (f.phase == 0) {                                                               // pass 1: stored / leaf inputs; exact zero skips the row (every monomial of the row is zero, so are its marker derivatives)
                bool skip = false;
                for (size_t i = 0; i < k && !skip; ++i) {
                    int cn = n.children[i]; int64_t cidx = mul_child_index(n, (int)i, f.d); Num& dst = at(f.base + i); f.unresolved[i] = 0;
                    const NodeD& c = N[cn];
                    if (c.kind == K_SOURCE || c.kind == K_CONSTANT || c.kind == K_MARKER) { child_value(cn, cidx, dst); if (P::is_zero(dst)) skip = true; }
                    else { int r = lookup(cn, cidx, dst); if (r == 1) { if (P::is_zero(dst)) skip = true; } else if (r == 2) { P::set_zero(dst); skip = true; } else f.unresolved[i] = 1; }
                    if (!poll(1)) return false;
                }
                if (skip) { ++C.zero_skips; done = true; if (f.mode != 1) P::set_zero(*f.dst); return poll(1); }   // an EXACT zero operand: every monomial of this row is zero (P3), so the row's value AND all its marker derivatives are zero; the zero operand itself is a nonnegative polynomial that vanishes at all-one markers, so its own marker derivatives vanish too (no pullback needed)
                f.phase = 1; f.i = 0;
            }
            if (f.phase == 2) { Num& dst = at(f.base + f.i); f.phase = 1; if (P::is_zero(dst)) { ++C.zero_skips; if (f.mode != 1) P::set_zero(*f.dst); done = true; return poll(1); } f.i++; }   // exact-zero operand: every monomial of the row is zero (P3), so are all its marker derivatives
            if (f.phase == 1) {                                                               // pass 2: streamed children one VALUE frame at a time (the LAST one of a pullback row gets a combined frame)
                while (f.i < (int)k && !f.unresolved[f.i]) f.i++;
                if (f.i < (int)k) {
                    int last = -1; for (int j = (int)k - 1; j >= 0; --j) if (f.unresolved[j]) { last = j; break; }
                    if (f.mode != 0 && f.i == last) { f.last = last; f.phase = 3; }
                    else { int cn = n.children[f.i]; int64_t cidx = mul_child_index(n, f.i, f.d); f.phase = 2; int r = child_value(cn, cidx, at(f.base + f.i)); if (r < 0) return false; return true; }
                } else f.phase = 3;
            }
            if (f.phase == 3) {
                ++C.mul_rows;
                if (f.mode == 0) { Num& row = at(ROW); P::set_one(row); for (size_t i = 0; i < k; ++i) { P::mul(row, row, at(f.base + i)); ++C.mults; if (!poll(1)) return false; } P::copy(*f.dst, row); done = true; return poll(1); }
                if (f.last >= 0) {                                                            // combined frame for the last streamed child: g = h * prod(other inputs)
                    int cn = n.children[f.last]; P::set_one(at(f.base + f.last));
                    P::set_one(at(PRE)); for (size_t i = 0; i < k; ++i) { P::mul(at(PRE + i + 1), at(PRE + i), at(f.base + i)); ++C.mults; if (!poll(1)) return false; }
                    P::mul(at(G), at(H), at(PRE + k)); ++C.mults; int64_t cidx = mul_child_index(n, f.last, f.d); f.phase = 6; ++C.stream_reevals;
                    return push(2, cn, cidx, &at(f.base + f.last), &at(G));
                }
                P::set_one(at(PRE)); for (size_t i = 0; i < k; ++i) { P::mul(at(PRE + i + 1), at(PRE + i), at(f.base + i)); ++C.mults; if (!poll(1)) return false; }
                P::set_one(at(SUF + k)); for (size_t i = k; i >= 1; --i) { P::mul(at(SUF + i - 1), at(f.base + i - 1), at(SUF + i)); ++C.mults; if (!poll(1)) return false; }
                if (f.mode == 2) { P::copy(*f.dst, at(PRE + k)); }
                f.phase = 4; f.i = 0; if (!poll(1)) return false;
            }
            if (f.phase == 6) { Num& dst = at(f.base + f.last); int d2 = f.last; f.last = -1; f.unresolved[d2] = 2; f.phase = 3; (void)dst; return true; }
            if (f.phase == 5) { f.phase = 4; f.i++; }
            if (f.phase == 4) {                                                               // scatter h * prod(others) to every child use (prefix/suffix: zero-safe, no division)
                while (f.i < (int)k) {
                    int cn = n.children[f.i]; const NodeD& c = N[cn];
                    if (c.kind != K_SOURCE && c.kind != K_CONSTANT && f.unresolved[f.i] != 2) {
                        P::mul(at(G), at(PRE + f.i), at(SUF + f.i + 1)); P::mul(at(G), at(G), at(H)); C.mults += 2;
                        int64_t cidx = mul_child_index(n, f.i, f.d); f.phase = 5; int r = child_pull(cn, cidx, at(G)); if (r < 0) return false; if (r == 1) return true; f.phase = 4;
                        if (!poll(3)) return false;
                    }
                    f.i++;
                }
                done = true; return poll(1);
            }
            return true;
        }
        }
        return true;
    }
    bool value(int nn, int64_t idx, Num& out) { size_t fl = frames.size(); int r = child_value(nn, idx, out); if (r < 0) return false; if (r == 0) return true; return run(fl); }
    bool pull(int nn, int64_t idx, const Num& h) { size_t fl = frames.size(); int r = child_pull(nn, idx, h); if (r < 0) return false; if (r == 0) return true; return run(fl); }

    // ---- materialization (forward pass in topological order = node index order; children precede consumers)
    bool materialize_dense(int nn) {
        NodeD& n = N[nn]; int64_t cnt = n.demand_kind == 0 ? n.volume : (n.demand_kind == 2 ? 0 : (int64_t)n.demand.size());
        if (n.demand_kind == 1) { if (!reserve(used_index, caps.index, (uint64_t)cnt * 48)) return false; dpos[nn].reserve(cnt); for (int64_t s = 0; s < cnt; ++s) dpos[nn][n.demand[s]] = s; }
        C.entries_stored_planned += cnt; dense_done[nn] = 0;
        for (int64_t b0 = 0; b0 < cnt; b0 += GB3_BLOCK) {
            int64_t bl = std::min<int64_t>(GB3_BLOCK, cnt - b0);
            if (!reserve(used_values, caps.values, (uint64_t)bl * P::bytes(prec) + sizeof(std::vector<Num>))) return false;      // ONE block reserved before it is allocated
            dense[nn].emplace_back(); auto& blk = dense[nn].back(); blk.resize(bl); for (auto& x : blk) P::init(x, prec); ++C.dense_blocks;
            for (int64_t s = 0; s < bl; ++s) { int64_t idx = n.demand_kind == 0 ? b0 + s : n.demand[b0 + s]; if (!value(nn, idx, blk[s])) return false; dense_done[nn] = b0 + s + 1; ++C.entries_materialized; }
        }
        return true;
    }
    // SPARSE join block for REDUCE(MUL(children)) : iterate the rows of the driver child with the smallest KNOWN support, extend over the MUL axes the driver does not
    // determine, evaluate the other inputs (exact zero skips), scatter-add the product into the output row of the REDUCE's kept axes (duplicate aggregation).
    bool materialize_sparse(int nn) {
        NodeD& n = N[nn]; if (n.kind != K_REDUCE) return false; int mn = n.children[0]; const NodeD& m = N[mn]; if (m.kind != K_MUL) return false;
        // known supports: SOURCE children (zeros in the table) and COMPLETE sparse children; choose the driver = smallest known support
        int drv = -1; int64_t best = INT64_MAX; std::vector<int64_t> drows;
        for (size_t i = 0; i < m.children.size(); ++i) { int cn = m.children[i]; const NodeD& c = N[cn]; int64_t cntz = -1;
            if (c.kind == K_SOURCE) { cntz = 0; for (int64_t e = 0; e < c.volume; ++e) { if (!P::is_zero(fvals[F[c.fid].val_off + e])) ++cntz; if (!poll(1)) return false; } }
            else if (c.storage == S_SPARSE && sparse_complete[cn]) cntz = (int64_t)sparse_vals[cn].size();
            if (cntz >= 0 && cntz < best) { best = cntz; drv = (int)i; } }
        if (drv < 0) return false;
        const NodeD& dc = N[m.children[drv]];
        if (!reserve(used_index, caps.index, (uint64_t)best * sizeof(int64_t))) return false;
        if (dc.kind == K_SOURCE) { for (int64_t e = 0; e < dc.volume; ++e) if (!P::is_zero(fvals[F[dc.fid].val_off + e])) drows.push_back(e); } else drows = sparse_idx[m.children[drv]];
        // axes of the MUL not determined by the driver
        std::vector<char> det(m.card.size(), 0); for (size_t k = 0; k < dc.card.size(); ++k) det[m.proj[drv][k]] = 1;
        std::vector<int> freeax; int64_t freevol = 1; for (size_t p = 0; p < m.card.size(); ++p) if (!det[p]) { freeax.push_back((int)p); if (freevol > INT64_MAX / m.card[p]) return false; freevol *= m.card[p]; }
        std::vector<int64_t> d(m.card.size()), dd; size_t sl; if (!frame_alloc(2, sl)) return false; Num& row = at(sl); Num& tmp = at(sl + 1);
        dpos[nn].clear(); sparse_vals[nn].clear(); sparse_idx[nn].clear();
        for (int64_t r = 0; r < (int64_t)drows.size(); ++r) {
            digits(dc, drows[r], dd); for (size_t k = 0; k < dc.card.size(); ++k) d[m.proj[drv][k]] = dd[k];
            for (int64_t t = 0; t < freevol; ++t) {
                int64_t tt = t; for (int q = (int)freeax.size() - 1; q >= 0; --q) { d[freeax[q]] = tt % m.card[freeax[q]]; tt /= m.card[freeax[q]]; }
                P::set_one(row); bool zero = false;
                for (size_t i = 0; i < m.children.size() && !zero; ++i) { int64_t cidx = mul_child_index(m, (int)i, d); if (!value(m.children[i], cidx, tmp)) { top = sl; return false; } if (P::is_zero(tmp)) zero = true; else { P::mul(row, row, tmp); ++C.mults; } if (!poll(1)) { top = sl; return false; } }
                ++C.sparse_rows_joined;
                if (zero) { ++C.zero_skips; continue; }
                // output index of the REDUCE: kept child axes
                int64_t oidx = 0; for (size_t p = 0; p < n.card.size(); ++p) { int src = -1; for (size_t q = 0; q < m.card.size(); ++q) if (n.proj[0][q] == (int)p) { src = (int)q; break; } oidx = oidx * n.card[p] + d[src]; }
                auto it = dpos[nn].find(oidx);
                if (it == dpos[nn].end()) { if (!reserve(used_values, caps.values, P::bytes(prec) + sizeof(int64_t)) || !reserve(used_index, caps.index, 48)) { top = sl; return false; } dpos[nn][oidx] = (int64_t)sparse_vals[nn].size(); sparse_vals[nn].emplace_back(); P::init(sparse_vals[nn].back(), prec); P::copy(sparse_vals[nn].back(), row); sparse_idx[nn].push_back(oidx); ++C.sparse_output_rows; }
                else { P::add(sparse_vals[nn][it->second], sparse_vals[nn][it->second], row); ++C.adds; }
                ++C.mul_rows; ++C.reduce_terms;
            }
        }
        top = sl; sparse_complete[nn] = 1; return true;
    }
    bool downgrade_to_stream(int nn) {   // one materialized -> stream downgrade per node per attempt; discards incomplete numerical state of the node
        NodeD& n = N[nn]; if (n.downgraded) return false; n.downgraded = 1; ++C.downgrades; abandon_frames(0);
        for (auto& b : dense[nn]) { for (auto& x : b) P::clear(x); release(used_values, (uint64_t)b.size() * P::bytes(prec) + sizeof(std::vector<Num>)); } dense[nn].clear(); dense_done[nn] = 0;
        if (n.storage == S_SPARSE) { for (auto& x : sparse_vals[nn]) P::clear(x); release(used_values, (uint64_t)sparse_vals[nn].size() * (P::bytes(prec) + sizeof(int64_t))); release(used_index, (uint64_t)sparse_vals[nn].size() * 48); sparse_vals[nn].clear(); sparse_idx[nn].clear(); sparse_complete[nn] = 0; ++C.sparse_join_discarded; }
        dpos[nn].clear(); n.storage = S_STREAM; stop = GB_OK; return true;
    }

    int forward() {
        phase_tag = 1;
        if (!reserve(used_scratch, caps.scratch, (uint64_t)N.size() * (3 * sizeof(std::vector<Num>) + sizeof(std::unordered_map<int64_t, int64_t>) + 2 * sizeof(std::vector<int64_t>) + 8))) return stop;
        dense.assign(N.size(), {}); dense_done.assign(N.size(), 0); dpos.assign(N.size(), {}); sparse_vals.assign(N.size(), {}); sparse_idx.assign(N.size(), {}); sparse_complete.assign(N.size(), 0); adj.assign(N.size(), {}); adj_state.assign(N.size(), {}); adj_alloc.assign(N.size(), 0);
        Nx.assign(nvars, {}); for (int v = 0; v < nvars; ++v) { if (!reserve(used_reverse, caps.reverse, (uint64_t)vcard[v] * P::bytes(prec))) return stop; Nx[v].resize(vcard[v]); for (auto& x : Nx[v]) P::init(x, prec); }
        cache_cap = caps.values > used_values ? (caps.values - used_values) / 2 : 0;                            // the cache may use at most half of the remaining value category (documented policy)
        for (size_t nn = 0; nn < N.size(); ++nn) {
            NodeD& n = N[nn]; active_node = (int)nn;
            if (n.storage == S_DENSE) { if (!materialize_dense((int)nn)) { if (stop == GB_MEMORY && downgrade_to_stream((int)nn)) continue; return stop; } }
            else if (n.storage == S_SPARSE) { if (!materialize_sparse((int)nn)) { if (stop == GB_MEMORY || stop == GB_OK) { if (downgrade_to_stream((int)nn)) continue; } return stop ? stop : GB_BADPROG; } }
        }
        // Z = scale * prod roots (each root is a scalar node; its value is requested through the same interface)
        P::copy(Z, scale); size_t sl; if (!frame_alloc(1, sl)) return stop; Num& rv = at(sl);
        for (int r : roots) { if (!value(r, 0, rv)) return stop; P::mul(Z, Z, rv); ++C.mults; ++C.root_ops; if (!poll(1)) return stop; }
        top = sl; snapshot(); return GB_OK;
    }

    // flush every PENDING slot of every materialized node in reverse topological order; returns false on a typed stop
    bool flush_all_pending() {
        ++C.early_flushes; flushing = 1;
        for (int nn = (int)N.size() - 1; nn >= 0; --nn) if (adj_alloc[nn]) { if (!drain_node(nn)) { flushing = 0; return false; } }
        flushing = 0; return true;
    }
    bool drain_node(int nn) {
        for (size_t s = 0; s < adj[nn].size(); ++s) {
            if (adj_state[nn][s] != 1) { if (!poll(1)) return false; continue; }
            adj_state[nn][s] = 2;                                                           // ACTIVE: its byte charge stays until consumed
            size_t sl; if (!frame_alloc(1, sl)) return false; P::copy(at(sl), adj[nn][s]); P::set_zero(adj[nn][s]);
            int64_t idx = stored_index(nn, (int64_t)s);
            size_t fl = frames.size();
            if (!push(1, nn, idx, nullptr, &at(sl))) { top = sl; return false; }
            if (!run(fl)) { top = sl; return false; }
            top = sl; adj_state[nn][s] = 3; ++C.slots_drained;
        }
        return true;
    }
    int reverse() {
        phase_tag = 2;
        size_t R = roots.size(); if (!reserve(used_reverse, caps.reverse, (uint64_t)(3 * R + 3) * P::bytes(prec))) return stop;
        std::vector<Num> rv(R), pre(R + 1), suf(R + 1); for (auto& x : rv) P::init(x, prec); for (auto& x : pre) P::init(x, prec); for (auto& x : suf) P::init(x, prec);
        auto rel = [&]() { for (auto& x : rv) P::clear(x); for (auto& x : pre) P::clear(x); for (auto& x : suf) P::clear(x); };
        for (size_t i = 0; i < R; ++i) { if (!value(roots[i], 0, rv[i])) { rel(); return stop; } }
        P::set_one(pre[0]); for (size_t i = 0; i < R; ++i) { P::mul(pre[i + 1], pre[i], rv[i]); ++C.mults; ++C.root_ops; if (!poll(1)) { rel(); return stop; } }
        P::set_one(suf[R]); for (size_t i = R; i >= 1; --i) { P::mul(suf[i - 1], rv[i - 1], suf[i]); ++C.mults; ++C.root_ops; if (!poll(1)) { rel(); return stop; } }
        for (size_t i = 0; i < R; ++i) { Num h; P::init(h, prec); P::mul(h, pre[i], suf[i + 1]); P::mul(h, h, scale); C.mults += 2; C.root_ops += 2; bool ok = pull(roots[i], 0, h); P::clear(h); if (!ok) { rel(); return stop; } }
        rel();
        // final sweep: drain pending slots in reverse topological order (every consumer of a node precedes it)
        for (int nn = (int)N.size() - 1; nn >= 0; --nn) if (adj_alloc[nn]) { active_node = nn; if (!drain_node(nn)) return stop; }
        snapshot(); return GB_OK;
    }
};

// ------------------------------------------------------------------------------------------------------------ C API (type-erased)
struct Handle { int mode; Exec<Ival>* I; Exec<Dbl>* D; long emin, emax; };
static void set_from_double(Dbl::T& dst, double v) { dst.v = v; dst.e = (v == 0.0 ? 0 : test_leaf_label); }
static void set_from_double(Ival::T& dst, double v) { mpfr_set_d(dst.lo, v, MPFR_RNDD); mpfr_set_d(dst.hi, v, MPFR_RNDU); }
struct Reader { const int64_t* p; int64_t n; int64_t i = 0; int64_t rd() { if (i >= n) throw BadProg("program truncated"); return p[i++]; } int rdi() { int64_t v = rd(); if (v < -1 || v > 2147483647LL) throw BadProg("program field outside int32"); return (int)v; } int64_t rdn() { int64_t v = rd(); if (v < 0) throw BadProg("negative count"); return v; } };
static uint64_t ir_bytes_bound(int64_t plen) { return (uint64_t)plen * (sizeof(int64_t) + sizeof(int)) + (uint64_t)plen * 4 * sizeof(std::vector<int>) / 8 + 4096; }

// flat int64 program: [3, nvars, card[nvars]] [nF] per factor: arity, scope..., entries, val_off ; [ncls, cls...] ; [nN] per node: kind, naxes, (var, card)*naxes, storage, demand_kind, ndemand, demand...,
//   kind payload: SOURCE fid | MARKER var | CONSTANT val_off | GATHER child, per child axis: out_pos, fixed, cls_off, ratio_off | ADD nch, children | MUL nch, children, per child per child-axis out_pos | REDUCE child, per child axis: out_pos(-1 = eliminated), reps_off(-1 = identity; else core index -> child raw index through cls)
//   [nroots, roots...]
template <class P> static void parse_prog(Exec<P>& E, const int64_t* prog, int64_t plen, int64_t nfac_vals, int64_t nratio_vals, int64_t nconst_vals) {
    Reader r{prog, plen}; if (r.rd() != 3) throw BadProg("magic"); E.nvars = r.rdi(); if (E.nvars < 0) throw BadProg("nvars"); E.vcard.resize(E.nvars); for (int v = 0; v < E.nvars; ++v) { E.vcard[v] = r.rdn(); if (E.vcard[v] < 1) throw BadProg("card"); }
    int64_t nF = r.rdn(); if (nF > plen) throw BadProg("factor count"); E.F.resize(nF);
    for (int64_t i = 0; i < nF; ++i) { FactorD& f = E.F[i]; int ar = r.rdi(); if (ar < 0) throw BadProg("arity"); f.scope.resize(ar); f.card.resize(ar); f.stride.resize(ar); for (int k = 0; k < ar; ++k) { f.scope[k] = r.rdi(); if (f.scope[k] < 0 || f.scope[k] >= E.nvars) throw BadProg("scope"); f.card[k] = (int)E.vcard[f.scope[k]]; } f.entries = r.rdn(); f.val_off = r.rdn();
        int64_t st = 1; for (int k = ar - 1; k >= 0; --k) { f.stride[k] = st; if (st > INT64_MAX / f.card[k]) throw BadProg("table size overflow"); st *= f.card[k]; } if (st != f.entries || f.val_off > nfac_vals - f.entries) throw BadProg("table size / offset"); }
    int64_t ncls = r.rdn(); if (ncls > plen) throw BadProg("cls count"); E.cls.resize(ncls); for (int64_t i = 0; i < ncls; ++i) E.cls[i] = r.rdn();
    int64_t nN = r.rdn(); if (nN > plen) throw BadProg("node count"); E.N.resize(nN);
    for (int64_t i = 0; i < nN; ++i) { NodeD& n = E.N[i]; n.kind = r.rdi(); if (n.kind < 0 || n.kind > 6) throw BadProg("kind"); int na = r.rdi(); if (na < 0) throw BadProg("naxes"); n.axes.resize(na); n.card.resize(na); n.volume = 1;
        for (int k = 0; k < na; ++k) { n.axes[k] = r.rdi(); n.card[k] = r.rdn(); if (n.card[k] < 1) throw BadProg("axis card"); if (n.volume > INT64_MAX / n.card[k]) throw BadProg("volume exceeds int64"); n.volume *= n.card[k]; }
        n.storage = r.rdi(); if (n.storage < 0 || n.storage > 3) throw BadProg("storage"); n.demand_kind = r.rdi(); if (n.demand_kind < 0 || n.demand_kind > 2) throw BadProg("demand kind"); int64_t nd = r.rdn(); if (nd > plen) throw BadProg("ndemand"); n.demand.resize(nd); int64_t prev = -1; for (int64_t q = 0; q < nd; ++q) { n.demand[q] = r.rd(); if (n.demand[q] <= prev || n.demand[q] >= n.volume) throw BadProg("demand list must be sorted, unique, < volume"); prev = n.demand[q]; }
        if (n.demand_kind == 1 && nd == 0) n.demand_kind = 2; if (n.demand_kind != 1 && nd != 0) throw BadProg("demand list with non-LIST kind"); if (n.storage != S_DENSE && n.demand_kind != 0) throw BadProg("demand hint on a non-DENSE node");
        n.fid = -1; n.var = -1; n.val_off = -1; n.elim_volume = 1; n.downgraded = 0; n.uses = 0;
        switch (n.kind) {
        case K_SOURCE: { n.fid = r.rdi(); if (n.fid < 0 || n.fid >= nF) throw BadProg("fid"); const FactorD& f = E.F[n.fid]; if ((int)f.scope.size() != na) throw BadProg("source axes != scope"); for (int k = 0; k < na; ++k) if (n.axes[k] != f.scope[k] || n.card[k] != f.card[k]) throw BadProg("source axis mismatch"); if (n.storage != S_STREAM) throw BadProg("source storage"); break; }
        case K_MARKER: { n.var = r.rdi(); if (n.var < 0 || n.var >= E.nvars || na != 1 || n.axes[0] != n.var || n.card[0] != E.vcard[n.var]) throw BadProg("marker"); if (n.storage != S_STREAM) throw BadProg("marker storage"); break; }
        case K_CONSTANT: { n.val_off = r.rdn(); if (n.val_off >= nconst_vals || na != 0) throw BadProg("constant"); if (n.storage != S_STREAM) throw BadProg("constant storage"); break; }
        case K_GATHER: { int c = r.rdi(); if (c < 0 || c >= i) throw BadProg("gather child must precede"); n.children = {c}; const NodeD& ch = E.N[c]; n.gaxes.resize(ch.card.size());
            for (size_t k = 0; k < ch.card.size(); ++k) { GAxis& g = n.gaxes[k]; g.out_pos = r.rdi(); g.fixed = r.rdi(); g.cls_off = r.rd(); g.ratio_off = r.rd();
                if (g.out_pos < -1 || g.out_pos >= na) throw BadProg("gather out_pos"); if (g.out_pos < 0) { if (g.fixed < 0 || g.fixed >= ch.card[k] || g.cls_off >= 0 || g.ratio_off >= 0) throw BadProg("gather fixed"); }
                else { int64_t raw = n.card[g.out_pos]; if (g.cls_off >= 0) { if (g.cls_off > ncls - raw) throw BadProg("cls off"); for (int64_t q = 0; q < raw; ++q) if (E.cls[g.cls_off + q] < 0 || E.cls[g.cls_off + q] >= ch.card[k]) throw BadProg("cls value"); } else if (raw != ch.card[k]) throw BadProg("gather identity axis card"); if (g.ratio_off >= 0 && g.ratio_off > nratio_vals - raw) throw BadProg("ratio off"); } }
            E.N[c].uses++; break; }
        case K_ADD: { int nc = r.rdi(); if (nc < 1) throw BadProg("add children"); n.children.resize(nc); for (int q = 0; q < nc; ++q) { n.children[q] = r.rdi(); if (n.children[q] < 0 || n.children[q] >= i) throw BadProg("add child must precede"); const NodeD& ch = E.N[n.children[q]]; if (ch.card != n.card) throw BadProg("add axes not aligned"); E.N[n.children[q]].uses++; } break; }
        case K_MUL: { int nc = r.rdi(); if (nc < 1) throw BadProg("mul children"); n.children.resize(nc); n.proj.resize(nc); for (int q = 0; q < nc; ++q) { n.children[q] = r.rdi(); if (n.children[q] < 0 || n.children[q] >= i) throw BadProg("mul child must precede"); E.N[n.children[q]].uses++; }
            for (int q = 0; q < nc; ++q) { const NodeD& ch = E.N[n.children[q]]; n.proj[q].resize(ch.card.size()); for (size_t k = 0; k < ch.card.size(); ++k) { int p = r.rdi(); if (p < 0 || p >= na || n.card[p] != ch.card[k]) throw BadProg("mul projection"); n.proj[q][k] = p; } } break; }
        case K_REDUCE: { int c = r.rdi(); if (c < 0 || c >= i) throw BadProg("reduce child must precede"); n.children = {c}; const NodeD& ch = E.N[c]; n.proj.resize(1); n.proj[0].resize(ch.card.size()); n.reps_off.assign(ch.card.size(), -1); std::vector<char> seen(na, 0);
            for (size_t k = 0; k < ch.card.size(); ++k) { int p = r.rdi(); int64_t ro = r.rd(); if (p < -1 || p >= na) throw BadProg("reduce map"); n.proj[0][k] = p; n.reps_off[k] = ro;
                if (p >= 0) { if (seen[p]) throw BadProg("reduce kept axis twice"); seen[p] = 1; if (ro < 0) { if (n.card[p] != ch.card[k]) throw BadProg("reduce kept axis card"); } else { if (n.storage == S_SPARSE) throw BadProg("sparse reduce with a core axis"); if (ro > ncls - n.card[p]) throw BadProg("reps off"); for (int64_t q = 0; q < n.card[p]; ++q) if (E.cls[ro + q] < 0 || E.cls[ro + q] >= ch.card[k]) throw BadProg("reps value"); } }
                else { if (ro >= 0) throw BadProg("reps on an eliminated axis"); n.elim_card.push_back(ch.card[k]); if (n.elim_card.size() > 64) throw BadProg("more than 64 eliminated axes in one REDUCE"); if (n.elim_volume > INT64_MAX / ch.card[k]) throw BadProg("elim volume"); n.elim_volume *= ch.card[k]; } }
            for (int p = 0; p < na; ++p) if (!seen[p]) throw BadProg("reduce output axis not produced"); E.N[c].uses++; break; }
        }
    }
    int64_t nr = r.rdn(); if (nr > nN) throw BadProg("roots"); E.roots.resize(nr); for (int64_t i = 0; i < nr; ++i) { E.roots[i] = r.rdi(); if (E.roots[i] < 0 || E.roots[i] >= nN || !E.N[E.roots[i]].card.empty()) throw BadProg("root must be a scalar node"); }
    if (r.i != plen) throw BadProg("trailing program words");
}
template <class P> static int load_values(Exec<P>& E, const char* const* qs, int64_t nfac, int64_t nratio, int64_t nconst, const double* dbl_vals) {
    int64_t total = nfac + nratio + nconst + 1; uint64_t bytes = (uint64_t)total * P::bytes(E.prec); uint64_t maxlen = 0;
    if (!dbl_vals) for (int64_t i = 0; i < total; ++i) { uint64_t l = std::strlen(qs[i]); if (l > maxlen) maxlen = l; if (!E.poll(1)) return GB_DEADLINE; }
    bytes += 2 * (maxlen + 64) + 2 * sizeof(mpq_t);
    if (!E.reserve(E.used_scratch, E.caps.scratch, bytes)) return GB_MEMORY;
    E.fvals.resize(nfac); E.ratios.resize(nratio); E.consts.resize(nconst); mpq_t q; mpq_init(q);
    for (auto& x : E.fvals) P::init(x, E.prec); for (auto& x : E.ratios) P::init(x, E.prec); for (auto& x : E.consts) P::init(x, E.prec);      // K2: EVERY value is initialised BEFORE the (pollable) conversion loop, so a DEADLINE return mid-loop leaves no uninitialised mpfr_t for the destructor
    for (int64_t i = 0; i < total; ++i) {
        typename P::T* dst = i < nfac ? &E.fvals[i] : (i < nfac + nratio ? &E.ratios[i - nfac] : (i < nfac + nratio + nconst ? &E.consts[i - nfac - nratio] : &E.scale));
        if (dbl_vals) set_from_double(*dst, dbl_vals[i]); else { if (mpq_set_str(q, qs[i], 10) != 0) { mpq_clear(q); return GB_BADPROG; } mpq_canonicalize(q); if (mpq_sgn(q) < 0) { mpq_clear(q); return GB_BADPROG; } P::set_q(*dst, q, E.prec); }
        if (!E.poll(1)) { mpq_clear(q); return GB_DEADLINE; }
    }
    mpq_clear(q); return GB_OK;
}
static int fp_env_ok() {
    if (fegetround() != FE_TONEAREST) return 0;
    volatile double one = 1.0, up = 0x1p-54, dn = 0x1p-55, tiny = 0x1p-1022, half = 0.5;
    if ((double)(one + up) != 1.0) return 0; if ((double)(one - dn) != 1.0) return 0; if ((double)(tiny * half) == 0.0) return 0;
    return 1;
}
extern "C" int gb3_fp_env_ok() { return fp_env_ok(); }
extern "C" void gb3_test_exponent_range(long emin, long emax) { test_emin = emin; test_emax = emax; }
extern "C" void gb3_test_inject_bad_alloc(int on) { test_bad_alloc = on; }
extern "C" void gb3_test_leaf_label(unsigned long long e) { test_leaf_label = e ? (uint64_t)e : 1; }
// qualification fault injection (C25): 1 = a REDUCE omits its first eliminated tuple (counter forged as visited); 2 = adds it twice (counter unchanged); the exact oracle must catch both
extern "C" void gb3_test_branch_fault(int mode) { test_branch_fault = mode; }
extern "C" void gb3_test_ref_fault(int mode) { test_ref_fault = mode; }

extern "C" {
Handle* gb3_create(int mode, int prec, const int64_t* prog, int64_t plen, const char* const* qs, const double* dbl_vals, int64_t nfac, int64_t nratio, int64_t nconst, const uint64_t* caps5, double remaining_s, int* err_out) {
    Handle* h = nullptr; int err = GB_OK;
    try {
        h = new Handle(); h->mode = mode; h->I = nullptr; h->D = nullptr; Caps caps{caps5[0], caps5[1], caps5[2], caps5[3], caps5[4]}; double dl = now_mono() + remaining_s;
        if (mode == 0) { mpfr_set_emin(test_emin ? test_emin : mpfr_get_emin_min()); mpfr_set_emax(test_emax ? test_emax : mpfr_get_emax_max()); mpfr_clear_flags(); h->emin = (long)mpfr_get_emin(); h->emax = (long)mpfr_get_emax();
            h->I = new Exec<Ival>(prec); h->I->caps = caps; h->I->deadline = dl; if (!h->I->reserve(h->I->used_index, caps.index, ir_bytes_bound(plen))) throw std::runtime_error("ir"); parse_prog(*h->I, prog, plen, nfac, nratio, nconst); err = load_values(*h->I, qs, nfac, nratio, nconst, nullptr); }
        else { if (!fp_env_ok()) throw std::runtime_error("fpenv"); Dbl::range_fault = false; Dbl::label_fault = false;
            h->D = new Exec<Dbl>(53); h->D->caps = caps; h->D->deadline = dl; if (!h->D->reserve(h->D->used_index, caps.index, ir_bytes_bound(plen))) throw std::runtime_error("ir"); parse_prog(*h->D, prog, plen, nfac, nratio, nconst); err = load_values(*h->D, qs, nfac, nratio, nconst, dbl_vals); }
        if (err != GB_OK) throw std::runtime_error("load");
        return h;
    } catch (const BadProg&) { err = GB_BADPROG; } catch (const std::bad_alloc&) { err = GB_MEMORY; }
      catch (const std::runtime_error& ex) { if (std::strcmp(ex.what(), "fpenv") == 0) err = GB_FPENV; else if (std::strcmp(ex.what(), "ir") == 0) err = GB_MEMORY; else if (err == GB_OK) err = GB_FAULT; } catch (...) { err = GB_FAULT; }
    if (h) { delete h->I; delete h->D; delete h; }
    if (err_out) *err_out = err; return nullptr;
}
void gb3_destroy(Handle* h) { if (!h) return; try { delete h->I; delete h->D; delete h; } catch (...) {} }
static int mpfr_flags_stop() { return (mpfr_overflow_p() || mpfr_underflow_p() || mpfr_nanflag_p() || mpfr_erangeflag_p()) ? GB_RANGE : GB_OK; }
static int dbl_fault() { return Dbl::label_fault ? GB_LABEL : (Dbl::range_fault ? GB_RANGE : GB_OK); }
int gb3_forward(Handle* h) { try { if (h->mode == 1 && !fp_env_ok()) return GB_FPENV; int st = h->mode == 0 ? h->I->forward() : h->D->forward(); if (st == GB_OK && h->mode == 0) st = mpfr_flags_stop(); if (st == GB_OK && h->mode == 1) { st = dbl_fault(); if (st == GB_OK && !Dbl::finite(h->D->Z)) st = GB_RANGE; } return st; } catch (const std::bad_alloc&) { return GB_MEMORY; } catch (...) { return GB_FAULT; } }
int gb3_reverse(Handle* h) { try { if (h->mode == 1 && !fp_env_ok()) return GB_FPENV; int st = h->mode == 0 ? h->I->reverse() : h->D->reverse(); if (st == GB_OK && h->mode == 0) st = mpfr_flags_stop(); if (st == GB_OK && h->mode == 1) st = dbl_fault(); return st; } catch (const std::bad_alloc&) { return GB_MEMORY; } catch (...) { return GB_FAULT; } }
int gb3_mpfr_flags(Handle* h) { (void)h; return (mpfr_overflow_p() ? 1 : 0) | (mpfr_underflow_p() ? 2 : 0) | (mpfr_nanflag_p() ? 4 : 0) | (mpfr_erangeflag_p() ? 8 : 0) | (mpfr_inexflag_p() ? 16 : 0); }
#define CTRS3(E) uint64_t v[48] = {E.C.value_frames, E.C.pullback_frames, E.C.frames_combined, E.C.max_frame_depth, E.C.polls, E.C.mults, E.C.adds, E.C.lookups, E.C.zero_skips, E.C.source_reads, E.C.marker_updates, E.C.gather_visits, E.C.add_visits, E.C.mul_rows, E.C.reduce_terms, E.C.stream_reevals, E.C.reads_outside_demand, E.C.regenerated_values, E.C.dense_blocks, E.C.entries_materialized, E.C.entries_stored_planned, E.C.sparse_rows_joined, E.C.sparse_output_rows, E.C.sparse_join_discarded, E.C.cache_hits, E.C.cache_misses, E.C.cache_evictions, E.C.cache_inserts, E.C.adjoint_adds, E.C.slots_drained, E.C.early_flushes, E.C.late_increments, E.peak_pending, E.C.downgrades, E.C.root_ops, E.C.numerator_adds, E.used_values, E.used_index, E.used_reverse, E.used_pending, E.used_scratch, E.peak_scratch, E.cache_bytes, 0, 0, 0, 0, 0}; std::memcpy(out48, v, sizeof(v));
void gb3_counters(Handle* h, uint64_t* out48) { if (h->mode == 0) { CTRS3((*h->I)) } else { CTRS3((*h->D)) } }
void gb3_snapshot(Handle* h, uint64_t* out8) { if (!h) return; if (h->mode == 0) for (int i = 0; i < 8; ++i) out8[i] = h->I->snap[i].load(); else for (int i = 0; i < 8; ++i) out8[i] = h->D->snap[i].load(); }
// results: Z (lo,hi) then every reduced variable's N[v][a] (lo,hi) as exact tokens (';' separated). MPFR: hex@exp or "0"; binary64: %a@label (Z and N tokens written twice)
int64_t gb3_results_size(Handle* h) {
    try { int64_t total = 1;
        if (h->mode == 0) { Exec<Ival>& E = *h->I; auto len = [&](mpfr_t x) -> int64_t { if (!mpfr_number_p(x) || mpfr_sgn(x) < 0) return -1; if (mpfr_zero_p(x)) return 2; return (int64_t)((mpfr_get_prec(x) + 3) / 4) + 32; }; if (!Ival::finite(E.Z)) return -2; total += len(E.Z.lo) + len(E.Z.hi); for (int v = 0; v < E.nvars; ++v) for (int64_t a = 0; a < E.vcard[v]; ++a) { if (!Ival::finite(E.Nx[v][a])) return -2; total += len(E.Nx[v][a].lo) + len(E.Nx[v][a].hi); } }
        else { Exec<Dbl>& E = *h->D; if (Dbl::range_fault || Dbl::label_fault || !Dbl::finite(E.Z)) return -2; total += 128; for (int v = 0; v < E.nvars; ++v) for (int64_t a = 0; a < E.vcard[v]; ++a) { if (!Dbl::finite(E.Nx[v][a])) return -2; total += 128; } }
        return total; } catch (...) { return -3; }
}
int gb3_results_hex(Handle* h, char* buf, int64_t buflen) {
    try { int64_t p = 0; char tmp[2048]; auto put = [&](const char* s) { int64_t n = (int64_t)std::strlen(s); if (p + n + 2 > buflen) return false; std::memcpy(buf + p, s, n); p += n; buf[p++] = ';'; return true; };
        if (h->mode == 0) { auto hex = [&](mpfr_t x) { if (!mpfr_number_p(x) || mpfr_sgn(x) < 0) return false; if (mpfr_zero_p(x)) { std::snprintf(tmp, sizeof tmp, "0"); return true; } mpfr_exp_t e; char* s = mpfr_get_str(nullptr, &e, 16, 0, x, MPFR_RNDN); std::snprintf(tmp, sizeof tmp, "%s@%ld", s, (long)e); mpfr_free_str(s); return true; };
            Exec<Ival>& E = *h->I; if (!Ival::finite(E.Z)) return -2; for (int v = 0; v < E.nvars; ++v) for (int64_t a = 0; a < E.vcard[v]; ++a) if (!Ival::finite(E.Nx[v][a])) return -2;
            if (!hex(E.Z.lo) || !put(tmp)) return -1; if (!hex(E.Z.hi) || !put(tmp)) return -1; for (int v = 0; v < E.nvars; ++v) for (int64_t a = 0; a < E.vcard[v]; ++a) { if (!hex(E.Nx[v][a].lo) || !put(tmp)) return -1; if (!hex(E.Nx[v][a].hi) || !put(tmp)) return -1; } }
        else { Exec<Dbl>& E = *h->D; if (Dbl::range_fault || Dbl::label_fault || !Dbl::finite(E.Z)) return -2; for (int v = 0; v < E.nvars; ++v) for (int64_t a = 0; a < E.vcard[v]; ++a) if (!Dbl::finite(E.Nx[v][a])) return -2;
            std::snprintf(tmp, sizeof tmp, "%a@%llu", E.Z.v, (unsigned long long)E.Z.e); if (!put(tmp) || !put(tmp)) return -1; for (int v = 0; v < E.nvars; ++v) for (int64_t a = 0; a < E.vcard[v]; ++a) { std::snprintf(tmp, sizeof tmp, "%a@%llu", E.Nx[v][a].v, (unsigned long long)E.Nx[v][a].e); if (!put(tmp) || !put(tmp)) return -1; } }
        buf[p] = 0; return (int)p; } catch (...) { return -3; }
}
// qualification hook (C15): deliver the root adjoint as two deltas w1 then w2 (scaled by the model scale) with optional eviction + regeneration of every
// materialized non-root value between them; exercises exact-once delta ownership, late increments and regeneration through the SAME frame machine. MPFR only.
int gb3_test_split_root(Handle* h, const char* w1, const char* w2, int evict) {
    try { if (h->mode != 0 || h->I->roots.size() != 1) return GB_BADPROG; Exec<Ival>& E = *h->I; int r = E.roots[0];
        mpq_t q; mpq_init(q); Ival::T hw; Ival::init(hw, E.prec);
        for (int pass = 0; pass < 2; ++pass) { mpq_set_str(q, pass == 0 ? w1 : w2, 10); mpq_canonicalize(q); Ival::set_q(hw, q, E.prec); Ival::mul(hw, hw, E.scale);
            if (!E.pull(r, 0, hw)) { mpq_clear(q); Ival::clear(hw); return E.stop; }
            for (int nn = (int)E.N.size() - 1; nn >= 0; --nn) if (E.adj_alloc[nn]) { if (!E.drain_node(nn)) { mpq_clear(q); Ival::clear(hw); return E.stop; } }
            if (pass == 0 && evict) { for (size_t nn = 0; nn < E.N.size(); ++nn) { NodeD& n = E.N[nn]; if ((int)nn == r || n.storage != S_DENSE || n.downgraded) continue; for (int64_t s = 0; s < E.dense_done[nn]; ++s) { int64_t idx = n.demand_kind == 0 ? s : n.demand[s]; Ival::T& slot = E.dense[nn][s / GB3_BLOCK][s % GB3_BLOCK]; Ival::set_zero(slot); E.dense_done[nn] = s; if (!E.value((int)nn, idx, slot)) { mpq_clear(q); Ival::clear(hw); return E.stop; } E.dense_done[nn] = s + 1; ++E.C.regenerated_values; } } } }
        mpq_clear(q); Ival::clear(hw); return mpfr_flags_stop(); } catch (const std::bad_alloc&) { return GB_MEMORY; } catch (...) { return GB_FAULT; }
}

// ------------------------------------------------------------------------------------------------------------ exact integer fallback over the ORIGINAL evidence-restricted factors (brief §11)
struct Mz { mpz_t z; };
struct RefState { int nv; std::vector<int> card; std::vector<FactorD> F; std::vector<Mz> tabs; mpz_t Z; std::vector<std::vector<Mz>> Nx; uint64_t visited; bool done; std::vector<int> x; double deadline; uint64_t used_values, used_scratch, cap_values, cap_scratch, acc_bits_bound; };
RefState* gb3_ref_create(const int64_t* prog, int64_t plen, const char* const* int_vals, double remaining_s, const uint64_t* caps5, int* err_out) {
    RefState* S = nullptr;
    try { double deadline = now_mono() + remaining_s; Reader r{prog, plen};
        S = new RefState(); S->used_values = S->used_scratch = 0; S->cap_values = caps5 ? caps5[0] : UINT64_MAX; S->cap_scratch = caps5 ? caps5[4] : UINT64_MAX;
        auto reserve = [&](uint64_t& used, uint64_t cap, uint64_t bytes) { if (bytes > cap || used > cap - bytes) throw std::runtime_error("refmem"); used += bytes; };
        reserve(S->used_scratch, S->cap_scratch, ir_bytes_bound(plen) + sizeof(RefState));
        S->nv = r.rdi(); if (S->nv < 0) throw BadProg("nv"); S->card.resize(S->nv); for (int i = 0; i < S->nv; ++i) { S->card[i] = r.rdi(); if (S->card[i] < 1) throw BadProg("card"); }
        int64_t nF = r.rdn(); S->F.resize(nF); int64_t tot = 0;
        for (int64_t i = 0; i < nF; ++i) { FactorD& f = S->F[i]; int ar = r.rdi(); if (ar < 0) throw BadProg("arity"); f.scope.resize(ar); f.card.resize(ar); f.stride.resize(ar); for (int k = 0; k < ar; ++k) { f.scope[k] = r.rdi(); if (f.scope[k] < 0 || f.scope[k] >= S->nv) throw BadProg("scope"); } for (int k = 0; k < ar; ++k) f.card[k] = r.rdi(); f.entries = r.rdn(); f.val_off = tot; tot += f.entries; int64_t st = 1; for (int k = ar - 1; k >= 0; --k) { f.stride[k] = st; st *= f.card[k]; } if (st != f.entries) throw BadProg("entries"); }
        if (r.i != plen) throw BadProg("trailing");
        uint64_t tab_bytes = 0; uint64_t prod_bits = 64; int64_t idx = 0;
        for (int64_t i = 0; i < nF; ++i) { uint64_t fmax = 0; for (int64_t e = 0; e < S->F[i].entries; ++e, ++idx) { uint64_t l = std::strlen(int_vals[idx]); tab_bytes += sizeof(mpz_t) + 8 * (l * 42 / 100 / 8 + 2); uint64_t bits = l * 3322 / 1000 + 1; if (bits > fmax) fmax = bits; } prod_bits += fmax; }
        uint64_t total_bits = 1; for (int v = 0; v < S->nv; ++v) total_bits += 64 - __builtin_clzll((unsigned long long)S->card[v]);
        S->acc_bits_bound = prod_bits + total_bits + 1; uint64_t acc_bytes = sizeof(mpz_t) + 8 * (S->acc_bits_bound / 64 + 2); uint64_t nacc = 1; for (int v = 0; v < S->nv; ++v) nacc += (uint64_t)S->card[v];
        reserve(S->used_values, S->cap_values, tab_bytes + nacc * acc_bytes);
        reserve(S->used_scratch, S->cap_scratch, (uint64_t)S->nv * sizeof(int) + sizeof(mpz_t) + 8 * (prod_bits / 64 + 2) + nacc * sizeof(Mz));
        S->tabs.resize(tot); for (int64_t i = 0; i < tot; ++i) { mpz_init(S->tabs[i].z); if (mpz_set_str(S->tabs[i].z, int_vals[i], 10) != 0 || mpz_sgn(S->tabs[i].z) < 0) throw BadProg("value"); if (((i + 1) & 4095) == 0 && now_mono() > deadline) throw std::runtime_error("refdeadline"); }
        mpz_init_set_ui(S->Z, 0); S->Nx.resize(S->nv); for (int v = 0; v < S->nv; ++v) { S->Nx[v].resize(S->card[v]); for (auto& z : S->Nx[v]) mpz_init_set_ui(z.z, 0); }
        S->visited = 0; S->done = false; S->x.assign(S->nv, 0); S->deadline = deadline; return S;
    } catch (const BadProg&) { if (err_out) *err_out = GB_BADPROG; } catch (const std::bad_alloc&) { if (err_out) *err_out = GB_MEMORY; }
      catch (const std::runtime_error& ex) { if (err_out) *err_out = (std::strcmp(ex.what(), "refmem") == 0) ? GB_MEMORY : (std::strcmp(ex.what(), "refdeadline") == 0 ? GB_DEADLINE : GB_FAULT); } catch (...) { if (err_out) *err_out = GB_FAULT; }
    if (S) { for (auto& z : S->tabs) mpz_clear(z.z); delete S; }
    return nullptr;
}
uint64_t gb3_ref_used_values(RefState* S) { return S->used_values; }
uint64_t gb3_ref_used_scratch(RefState* S) { return S->used_scratch; }
int64_t gb3_ref_results_size(RefState* S) { try { int64_t t = 1 + (int64_t)mpz_sizeinbase(S->Z, 10) + 2; for (int v = 0; v < S->nv; ++v) for (int a = 0; a < S->card[v]; ++a) t += (int64_t)mpz_sizeinbase(S->Nx[v][a].z, 10) + 2; return t; } catch (...) { return -3; } }
int gb3_ref_run(RefState* S) {
    try { if (S->done) return GB_OK; mpz_t w; mpz_init(w); uint64_t ops = 0;
        for (;;) { mpz_set_ui(w, 1); bool zero = false;
            for (const FactorD& f : S->F) { int64_t off = 0; for (size_t k = 0; k < f.scope.size(); ++k) off += (int64_t)S->x[f.scope[k]] * f.stride[k]; const Mz& e = S->tabs[f.val_off + off]; if (mpz_sgn(e.z) == 0) { zero = true; break; } mpz_mul(w, w, e.z); if (++ops >= POLL_OPS) { ops = 0; if (now_mono() > S->deadline) { mpz_clear(w); return GB_DEADLINE; } } }
            bool first = (S->visited == 0); int reps = (first && test_ref_fault == 1) ? 0 : ((first && test_ref_fault == 2) ? 2 : 1);
            if (!zero) for (int rr = 0; rr < reps; ++rr) { mpz_add(S->Z, S->Z, w); for (int v = 0; v < S->nv; ++v) { mpz_add(S->Nx[v][S->x[v]].z, S->Nx[v][S->x[v]].z, w); if (++ops >= POLL_OPS) { ops = 0; if (now_mono() > S->deadline) { mpz_clear(w); return GB_DEADLINE; } } } }
            if (S->visited != UINT64_MAX) ++S->visited;
            int v = S->nv - 1; while (v >= 0) { if (++S->x[v] < S->card[v]) break; S->x[v] = 0; --v; }
            if (v < 0) { S->done = true; break; }
            if (++ops >= POLL_OPS) { ops = 0; if (now_mono() > S->deadline) { mpz_clear(w); return GB_DEADLINE; } } }
        mpz_clear(w); return GB_OK; } catch (const std::bad_alloc&) { return GB_MEMORY; } catch (...) { return GB_FAULT; }
}
uint64_t gb3_ref_visited(RefState* S) { return S->visited; }
int gb3_ref_results(RefState* S, char* buf, int64_t buflen) {
    try { int64_t p = 0; auto put = [&](mpz_ptr z) { char* s = mpz_get_str(nullptr, 10, z); int64_t n = (int64_t)std::strlen(s); if (p + n + 2 > buflen) { std::free(s); return false; } std::memcpy(buf + p, s, n); p += n; buf[p++] = ';'; std::free(s); return true; };
        if (!put(S->Z)) return -1; for (int v = 0; v < S->nv; ++v) for (int a = 0; a < S->card[v]; ++a) if (!put(S->Nx[v][a].z)) return -1; buf[p] = 0; return (int)p; } catch (...) { return -3; }
}
void gb3_ref_destroy(RefState* S) { if (!S) return; for (auto& z : S->tabs) mpz_clear(z.z); mpz_clear(S->Z); for (auto& v : S->Nx) for (auto& z : v) mpz_clear(z.z); delete S; }
const char* gb3_mpfr_version() { return mpfr_get_version(); }
const char* gb3_gmp_version() { return gmp_version; }
long gb3_mpfr_emin() { return (long)mpfr_get_emin(); }
long gb3_mpfr_emax() { return (long)mpfr_get_emax(); }
long gb3_mpfr_emin_min() { return (long)mpfr_get_emin_min(); }
long gb3_mpfr_emax_max() { return (long)mpfr_get_emax_max(); }
int64_t gb3_bytes_per_entry(int mode, int prec) { return mode == 0 ? (int64_t)Ival::bytes(prec) : (int64_t)Dbl::bytes(prec); }
int64_t gb3_block_entries() { return GB3_BLOCK; }
} // extern "C"
