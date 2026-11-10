// GENERAL_BIDI_V2 native executor (repair of 9-10 Nov 2026 after two adversarial reviews). One indexed sum-product bucket program over CORE classes
// with exact response views, materialization sets, streamed (zero-memo) children, zero-safe local reverse into original-marker numerators.
//
// What changed from V1 (each item answers a reproduced review finding):
//   * NO native recursion: VALUE and PULLBACK run on ONE explicit frame stack (std::vector<Frame>) whose frames and scratch are reserved in the
//     frames/scratch category BEFORE they are pushed; exhaustion is a typed GB_MEMORY stop, never a machine-stack fault (R2-04).
//   * every allocation is reserved in its category before it happens (values, index maps, reverse = numerators + root scratch, pending = adjoint
//     arrays, scratch = frames + program/source values); a cap is a typed GB_MEMORY stop (F3).
//   * every extern "C" entry catches std::bad_alloc (-> GB_MEMORY) and any other C++ exception (-> GB_FAULT) and leaves no half-built state (R2-05).
//     GMP/MPFR allocation failure is NOT catchable (GMP aborts by design); the category caps bound those allocations; disclosed.
//   * the deadline poll is charged to the actual primitive work (rows with zero inputs, conversions, frame pushes, root products) (R2-05, R5).
//   * the materialization set ("demand") is a STORAGE hint only: a read outside it is served by streaming (counted), never assumed zero; a row with an
//     exactly-zero input (source entry or child value) is skipped in both passes (exact: every monomial of that row is 0, so are all its marker
//     derivatives). A forged or wrong demand list therefore cannot change the answer, only the work (F2, GB-03).
//   * binary64 values carry EXACT error labels E tracked through every performed operation (sum max+1, product sum+1, leaf 1) and every
//     rounded result is range-checked; the executor turns (E_N + E_Z) u into the enclosure: the whole-execution proof, not a planner forecast (F1).
//   * binary64 mode checks the ambient rounding mode / flush-to-zero with live probes before executing (R2-06); MPFR mode configures the widest
//     supported exponent range, clears the flags and turns overflow / underflow / NaN / erange into a typed GB_RANGE stop; exported endpoints are
//     checked finite (R2-06).
//   * the program parser bounds-checks every read against plen and every narrowing conversion (GB_BADPROG).
//   * counters are DEFINED events (see Counters below and gbidi/executor.py COUNTER_DEFINITIONS); a live snapshot (atomics written at each poll)
//     is readable from another thread while the kernel runs (F5 / R2-10).
//   * exact integer reference stream: mixed-radix odometer (no assignment-count gate), checked / growable export (R3, R4).
// Closeout of 10 Nov 2026 (third review): the parsed program IR, the per-node containers, frame-vector CAPACITY growth and the mpq conversion
// temporaries are reserved before allocation (index / scratch categories); the reference stream takes the same five caps and reserves its tables,
// accumulators and a conservative bound on every product before running; every bulk loop polls PER PRIMITIVE (the deadline is checked within
// 4,096 charged units + one indivisible MPFR/GMP primitive); a qualification hook forces an initial leaf label (native label-cap branch control).
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
#include <algorithm>
#include <atomic>
#include <new>
#include <stdexcept>
#include <gmp.h>
#include <mpfr.h>

static const char* GB_SCHEDULE = "GENERAL_BIDI_V2/bucket-core-views-storage-hint-explicit-frames-localreverse/v2";
extern "C" const char* gb_schedule_id() { return GB_SCHEDULE; }

enum Stop : int { GB_OK = 0, GB_DEADLINE = 1, GB_MEMORY = 2, GB_OVERFLOW = 3, GB_RANGE = 4, GB_BADPROG = 5, GB_FAULT = 6, GB_FPENV = 7 };
struct BadProg : std::runtime_error { BadProg(const char* m) : std::runtime_error(m) {} };

static double now_mono() { struct timespec ts; clock_gettime(CLOCK_MONOTONIC, &ts); return ts.tv_sec + 1e-9 * ts.tv_nsec; }
static const uint64_t POLL_OPS = 4096;

// ------------------------------------------------------------------------------------------------------------ numeric policies
struct Dbl {                    // nearest binary64 with EXACT per-value error labels (optional route). Every value carries E such that, under
                                // correct nearest rounding with every performed operation's result normal, (1-u)^E v <= vhat <= (1+u)^E v (numerics_and_validation
                                // §4): converted leaf E=1, exact constants / exact zeros E=0, sum max+1, product sum+1; exact operations (x+0, x*0) keep labels.
                                // The per-operation range check (rounded result in [2*DBL_MIN, DBL_MAX/2] or exactly 0) is the first-failing-operation premise.
    struct T { double v; uint64_t e; };
    static bool range_fault;
    static const uint64_t E_MAX = (uint64_t)1 << 52;                                       // beyond this delta = E*u >= 1/2: the enclosure is void anyway
    static inline void check(double x, uint64_t e) { if (!(x >= 2 * DBL_MIN && x <= DBL_MAX / 2) || e > E_MAX) range_fault = true; }
    static void init(T& x, int) { x.v = 0.0; x.e = 0; }
    static void clear(T&) {}
    static void set_zero(T& x) { x.v = 0.0; x.e = 0; }
    static void set_one(T& x) { x.v = 1.0; x.e = 0; }
    static void set_q(T& x, mpq_t q, int) { (void)q; x.v = 0.0; x.e = 0; }               // never used: binary64 receives Python-verified doubles
    static void add(T& r, const T& a, const T& b) { if (a.v == 0.0) { r = b; return; } if (b.v == 0.0) { r = a; return; } T t; t.v = a.v + b.v; t.e = (a.e > b.e ? a.e : b.e) + 1; check(t.v, t.e); r = t; }
    static void mul(T& r, const T& a, const T& b) { if (a.v == 0.0 || b.v == 0.0) { r.v = 0.0; r.e = 0; return; } T t; t.v = a.v * b.v; t.e = a.e + b.e + 1; check(t.v, t.e); r = t; }
    static void copy(T& d, const T& s) { d = s; }
    static bool is_zero(const T& x) { return x.v == 0.0; }
    static bool finite(const T& x) { return std::isfinite(x.v) && x.v >= 0.0; }
    static size_t bytes(int) { return sizeof(T); }
};
bool Dbl::range_fault = false;
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
struct AxisD { int var; int nraw; std::vector<int> cls; std::vector<int> reps; int64_t ratio_off; };
struct InputD { int kind; int ref; };                                   // kind 0 = F, 1 = M
struct NodeD { int x; int xc; std::vector<InputD> inputs; std::vector<int> scope; std::vector<AxisD> axes; std::vector<int64_t> radix; int64_t core; int consumer; bool materialize; int demand_kind; std::vector<int64_t> demand; int nfac_inputs; };
// demand_kind: 0 = FULL (store every core entry), 1 = LIST (store exactly these core indices; reads outside are streamed), 2 = EMPTY (store nothing)

struct Caps { uint64_t values, index, reverse, pending, scratch; };
// Counter DEFINITIONS (exact event counts of the implemented schedule; interval ops count ONE logical operation = two endpoint operations in MPFR):
struct Counters {
    uint64_t primal_rows;            // row products formed inside VALUE frames (first evaluations AND regenerations)
    uint64_t reverse_rows;           // row products formed inside PULLBACK frames
    uint64_t rows_skipped_zero;      // rows skipped because an input was exactly zero (both passes)
    uint64_t mults, adds;            // logical multiplications / additions actually performed (rows, scales, prefix/suffix, roots, Z)
    uint64_t lookups;                // source table loads + materialized slot loads
    uint64_t value_frames;           // VALUE frames pushed (= entry evaluations requested, incl. materialization)
    uint64_t pullback_frames;        // PULLBACK frames pushed (= entry pullbacks requested)
    uint64_t stream_reevals;         // VALUE frames pushed for a NON-stored entry (streamed node or read outside the storage set)
    uint64_t reads_outside_demand;   // reads of a materialized node's entry that was not stored (served by streaming)
    uint64_t entries_materialized;   // stored entries whose evaluation completed
    uint64_t entries_stored_planned; // stored slots allocated
    uint64_t numerator_adds;         // additions into an original-marker numerator N[x][a]
    uint64_t adjoint_adds;           // additions into a stored adjoint slot (pending delta)
    uint64_t slots_drained;          // stored adjoint slots drained (nonzero) in reverse order
    uint64_t polls;                  // deadline polls
    uint64_t max_frame_depth;        // deepest frame stack
    uint64_t root_ops;               // root prefix/suffix/Z multiplications (included in mults as well)
};

static long test_emin = 0, test_emax = 0; static int test_bad_alloc = 0; static uint64_t test_leaf_label = 1;
template <class P> struct Exec {
    typedef typename P::T Num;
    int prec; std::vector<FactorD> F; std::vector<NodeD> N; std::vector<Num> fvals, ratios;
    std::vector<std::vector<Num>> values;      // per node (materialized): one slot per stored entry
    std::vector<std::unordered_map<int64_t, int64_t>> dpos;   // demand index -> slot (LIST kind)
    std::vector<std::vector<Num>> adj;         // per node (materialized): pending adjoint deltas per slot
    std::vector<std::vector<Num>> Nx;          // per node: numerators of its eliminated variable
    Num scale, Z; std::vector<int> roots;
    Caps caps; uint64_t used_values = 0, used_index = 0, used_reverse = 0, used_pending = 0, used_scratch = 0, peak_scratch = 0; Counters C{}; double deadline; int stop = GB_OK; uint64_t ops_since_poll = 0;
    std::deque<Num> scratch; size_t top = 0;   // frame scratch: bump allocator over a deque (references stay valid when it grows); charged
    std::atomic<uint64_t> snap[8];             // live snapshot written at each poll: primal_rows, reverse_rows, value_frames, pullback_frames, depth, active node, used_scratch, phase

    // ---- explicit frames (one per requested entry VALUE or PULLBACK); phases: 0 gather stored inputs, 1 gather streamed inputs, 2 streamed child returned,
    //      3 row ready, 4 (pullback) scatter to children, 5 (pullback) streamed child pullback returned
    struct Frame { int mode; int nn; int64_t idx; int a; int i; int phase; int last; size_t base; size_t saved_top; std::vector<int> d; std::vector<int8_t> unresolved; Num* dst; };
    // mode 0 VALUE (dst = entry value); mode 1 PULLBACK (h = incoming delta); mode 2 VALUE+PULLBACK (both: the child's rows are formed once and serve the
    // parent's product AND the child's own pullback; used for the LAST streamed message input of a pullback row, whose adjoint does not depend on its value)
    std::vector<Frame> frames; int phase_tag = 0;

    Exec(int p) : prec(p) { P::init(scale, p); P::init(Z, p); for (auto& s : snap) s.store(0); }
    ~Exec() { for (auto& v : values) for (auto& x : v) P::clear(x); for (auto& v : adj) for (auto& x : v) P::clear(x); for (auto& v : Nx) for (auto& x : v) P::clear(x); for (auto& x : fvals) P::clear(x); for (auto& x : ratios) P::clear(x); for (auto& x : scratch) P::clear(x); P::clear(scale); P::clear(Z); }

    inline void snapshot(int active) { snap[0].store(C.primal_rows); snap[1].store(C.reverse_rows); snap[2].store(C.value_frames); snap[3].store(C.pullback_frames); snap[4].store(frames.size()); snap[5].store((uint64_t)(active < 0 ? 0 : active)); snap[6].store(used_scratch); snap[7].store((uint64_t)phase_tag); }
    inline bool poll(uint64_t work, int active) { ops_since_poll += work; if (ops_since_poll >= POLL_OPS) { ops_since_poll = 0; ++C.polls; snapshot(active); if (now_mono() > deadline) { stop = GB_DEADLINE; return false; } } return true; }
    bool reserve(uint64_t& used, uint64_t cap, uint64_t bytes) { if (bytes > cap || used > cap - bytes) { stop = GB_MEMORY; return false; } used += bytes; return true; }
    bool frame_alloc(size_t n, size_t& base) {                      // RESERVE before growing the scratch deque
        if (test_bad_alloc) { test_bad_alloc = 0; throw std::bad_alloc(); }
        base = top; size_t need = top + n;
        if (need > scratch.size()) { uint64_t bytes = (uint64_t)(need - scratch.size()) * P::bytes(prec); if (!reserve(used_scratch, caps.scratch, bytes)) return false; while (scratch.size() < need) { scratch.emplace_back(); P::init(scratch.back(), prec); } }
        top = need; if (used_scratch > peak_scratch) peak_scratch = used_scratch; return true;
    }
    Num& at(size_t i) { return scratch[i]; }

    void digits(const NodeD& n, int64_t idx, std::vector<int>& d) { d.resize(n.radix.size()); for (int k = (int)n.radix.size() - 1; k >= 0; --k) { d[k] = (int)(idx % n.radix[k]); idx /= n.radix[k]; } }
    inline int raw_of(const NodeD& n, const std::vector<int>& d, int a, int w) const { if (w == n.x) return a; for (size_t k = 0; k < n.scope.size(); ++k) if (n.scope[k] == w) return n.axes[k].reps[d[k]]; return -1; }
    int64_t slot_of(int nn, int64_t idx) const { const NodeD& n = N[nn]; if (!n.materialize) return -1; if (n.demand_kind == 0) return idx < (int64_t)values[nn].size() ? idx : -1; if (n.demand_kind == 2) return -1; auto it = dpos[nn].find(idx); return it == dpos[nn].end() ? -1 : it->second; }
    // child core index + view scale for consumer n's row (d, a); the scale (product over the child's scope axes of the view ratios) is written into sc
    void child_index_scale(int cn, const NodeD& n, const std::vector<int>& d, int a, int64_t& cidx, Num& sc) {
        const NodeD& c = N[cn]; cidx = 0; P::set_one(sc);
        for (size_t k = 0; k < c.scope.size(); ++k) { int raw = raw_of(n, d, a, c.scope[k]); const AxisD& ax = c.axes[k]; cidx = cidx * c.radix[k] + ax.cls[raw]; P::mul(sc, sc, ratios[ax.ratio_off + raw]); ++C.mults; ops_since_poll++; }
    }
    int64_t child_index(int cn, const NodeD& n, const std::vector<int>& d, int a) const { const NodeD& c = N[cn]; int64_t cidx = 0; for (size_t k = 0; k < c.scope.size(); ++k) { int raw = raw_of(n, d, a, c.scope[k]); cidx = cidx * c.radix[k] + c.axes[k].cls[raw]; } return cidx; }

    // frame scratch layouts (Num slots from base): VALUE: inp[k], row, acc, sc ; PULLBACK / VALUE+PULLBACK: inp[k], pre[k+1], suf[k+1], g, row, sc, h, acc
    bool push(int mode, int nn, int64_t idx, Num* dst, const Num* h) {
        const NodeD& n = N[nn]; size_t k = n.inputs.size(); size_t need = mode == 0 ? k + 3 : 3 * k + 7;
        if (!reserve(used_scratch, caps.scratch, sizeof(Frame) + (n.radix.size() + k) * sizeof(int))) return false;         // the frame record itself
        Frame f; f.mode = mode; f.nn = nn; f.idx = idx; f.a = 0; f.i = 0; f.phase = 0; f.last = -1; f.saved_top = top; f.dst = dst; f.unresolved.assign(k, 0);
        if (!frame_alloc(need, f.base)) return false;
        digits(n, idx, f.d);
        if (mode == 0) { P::set_zero(at(f.base + k + 1)); ++C.value_frames; } else { P::copy(at(f.base + 3 * k + 5), *h); P::set_zero(at(f.base + 3 * k + 6)); ++C.pullback_frames; if (mode == 2) ++C.value_frames; }
        if (frames.size() == frames.capacity()) { size_t ncap = frames.capacity() ? 2 * frames.capacity() : 16; if (!reserve(used_scratch, caps.scratch, (uint64_t)(ncap - frames.capacity()) * sizeof(Frame))) return false; frames.reserve(ncap); }   // CAPACITY growth is charged (retained after pop)
        frames.push_back(std::move(f)); if (frames.size() > C.max_frame_depth) C.max_frame_depth = frames.size();
        return poll(1, nn);
    }
    void pop() { Frame& f = frames.back(); top = f.saved_top; used_scratch -= sizeof(Frame) + (N[f.nn].radix.size() + N[f.nn].inputs.size()) * sizeof(int); frames.pop_back(); }   // the vector capacity stays reserved

    // run the frame machine until the stack is empty; returns false on a typed stop
    bool run() {
        while (!frames.empty()) {
            Frame& f = frames.back(); const NodeD& n = N[f.nn]; size_t k = n.inputs.size();
            if (f.a >= n.xc) { if (f.mode == 0) P::copy(*f.dst, at(f.base + k + 1)); else if (f.mode == 2) P::copy(*f.dst, at(f.base + 3 * k + 6)); pop(); continue; }
            if (!step(f, n, k)) return false;
        }
        return true;
    }

    // one scheduling step for the top frame f (row f.a of node n)
    bool step(Frame& f, const NodeD& n, size_t k) {
        const size_t ROW = f.mode == 0 ? f.base + k : f.base + 3 * k + 3, SC = f.mode == 0 ? f.base + k + 2 : f.base + 3 * k + 4;
        if (f.phase == 0) {                                                                     // pass 1: factor loads + stored child loads; an exact zero skips the row (GB-03)
            bool skip = false;
            for (size_t i = 0; i < k && !skip; ++i) {
                const InputD& in = n.inputs[i]; Num& dst = at(f.base + i); f.unresolved[i] = 0;
                if (in.kind == 0) { const FactorD& fa = F[in.ref]; int64_t off = 0; for (size_t q = 0; q < fa.scope.size(); ++q) off += (int64_t)raw_of(n, f.d, f.a, fa.scope[q]) * fa.stride[q]; ++C.lookups; P::copy(dst, fvals[fa.val_off + off]); if (P::is_zero(dst)) skip = true; }
                else { int64_t cidx = child_index(in.ref, n, f.d, f.a); int64_t s = slot_of(in.ref, cidx); if (s >= 0) { Num& sc = at(SC); child_index_scale(in.ref, n, f.d, f.a, cidx, sc); ++C.lookups; P::mul(dst, sc, values[in.ref][s]); ++C.mults; if (P::is_zero(dst)) skip = true; } else f.unresolved[i] = 1; }
                if (!poll(1, f.nn)) return false;                                                   // PER input: the quantum is checked within 4096 charged units
            }
            if (!poll(1, f.nn)) return false;
            if (skip) { ++C.rows_skipped_zero; f.a++; f.i = 0; return true; }
            f.phase = 1; f.i = 0;
        }
        if (f.phase == 2) {                                                                     // a streamed child VALUE returned into inp[f.i]: apply the saved view scale
            Num& dst = at(f.base + f.i); P::mul(dst, at(SC), dst); ++C.mults; f.phase = 1;
            if (P::is_zero(dst)) { ++C.rows_skipped_zero; f.a++; f.i = 0; f.phase = 0; return true; }
            f.i++;
        }
        if (f.phase == 1) {                                                                     // pass 2: streamed / outside-storage children, one VALUE frame at a time
            while (f.i < (int)k && !f.unresolved[f.i]) f.i++;
            if (f.i < (int)k) {
                int last = -1; for (int j = (int)k - 1; j >= 0; --j) if (f.unresolved[j]) { last = j; break; }
                if (f.mode != 0 && f.i == last) { f.last = last; f.phase = 3; }                   // pullback: the last streamed child gets a combined frame (its adjoint needs only the OTHER inputs)
                else {
                    const InputD& in = n.inputs[f.i]; int64_t cidx; child_index_scale(in.ref, n, f.d, f.a, cidx, at(SC));
                    if (N[in.ref].materialize) ++C.reads_outside_demand; ++C.stream_reevals; f.phase = 2;
                    return push(0, in.ref, cidx, &at(f.base + f.i), nullptr);
                }
            } else f.phase = 3;
        }
        if (f.phase == 3) {                                                                     // every input of row f.a is resolved
            if (f.mode == 0) {
                Num& row = at(ROW); P::set_one(row); for (size_t i = 0; i < k; ++i) { P::mul(row, row, at(f.base + i)); ++C.mults; if (!poll(1, f.nn)) return false; }
                P::add(at(f.base + k + 1), at(f.base + k + 1), row); ++C.adds; ++C.primal_rows; f.a++; f.i = 0; f.phase = 0; return poll(1, f.nn);
            }
            const size_t PRE = f.base + k, SUF = f.base + 2 * k + 1, G = f.base + 3 * k + 2, H = f.base + 3 * k + 5, ACC = f.base + 3 * k + 6;
            if (f.last >= 0) {                                                                  // combined frame for the last streamed child: g = h * prod(other inputs) * view scale
                const InputD& in = n.inputs[f.last]; P::set_one(at(f.base + f.last));
                P::set_one(at(PRE)); for (size_t i = 0; i < k; ++i) { P::mul(at(PRE + i + 1), at(PRE + i), at(f.base + i)); ++C.mults; if (!poll(1, f.nn)) return false; }
                int64_t cidx; child_index_scale(in.ref, n, f.d, f.a, cidx, at(SC)); P::mul(at(G), at(H), at(PRE + k)); P::mul(at(G), at(G), at(SC)); C.mults += 2;
                if (N[in.ref].materialize) ++C.reads_outside_demand; ++C.stream_reevals; f.phase = 6;
                return push(2, in.ref, cidx, &at(f.base + f.last), &at(G));
            }
            P::set_one(at(PRE)); for (size_t i = 0; i < k; ++i) { P::mul(at(PRE + i + 1), at(PRE + i), at(f.base + i)); ++C.mults; if (!poll(1, f.nn)) return false; }
            P::set_one(at(SUF + k)); for (size_t i = k; i >= 1; --i) { P::mul(at(SUF + i - 1), at(f.base + i - 1), at(SUF + i)); ++C.mults; if (!poll(1, f.nn)) return false; }
            if (f.mode == 2) { P::add(at(ACC), at(ACC), at(PRE + k)); ++C.adds; ++C.primal_rows; }
            P::mul(at(ROW), at(H), at(PRE + k)); ++C.mults; P::add(Nx[f.nn][f.a], Nx[f.nn][f.a], at(ROW)); ++C.adds; ++C.numerator_adds; ++C.reverse_rows;
            f.phase = 4; f.i = 0; if (!poll(2, f.nn)) return false;
        }
        if (f.phase == 6) {                                                                     // the combined child frame returned its value into inp[last] (unscaled): scale it, then finish the row normally
            Num& dst = at(f.base + f.last); P::mul(dst, at(SC), dst); ++C.mults; int done = f.last; f.last = -1; f.unresolved[done] = 2; f.phase = 3;
            if (P::is_zero(dst)) { ++C.rows_skipped_zero; f.a++; f.i = 0; f.phase = 0; for (auto& u : f.unresolved) if (u == 2) u = 0; return true; }
            return true;                                                                        // re-enter phase 3 on the next step (no last child now)
        }
        if (f.phase == 5) { f.phase = 4; f.i++; }                                              // a streamed child PULLBACK returned
        if (f.phase == 4) {                                                                     // scatter h * (other inputs) * view scale to every message input
            const size_t PRE = f.base + k, SUF = f.base + 2 * k + 1, G = f.base + 3 * k + 2, H = f.base + 3 * k + 5;
            while (f.i < (int)k) {
                const InputD& in = n.inputs[f.i];
                if (in.kind == 1 && f.unresolved[f.i] != 2) {
                    P::mul(at(G), at(PRE + f.i), at(SUF + f.i + 1)); P::mul(at(G), at(G), at(H)); C.mults += 2;
                    int64_t cidx; child_index_scale(in.ref, n, f.d, f.a, cidx, at(SC)); P::mul(at(G), at(G), at(SC)); ++C.mults;
                    int64_t s = slot_of(in.ref, cidx);
                    if (s >= 0) { P::add(adj[in.ref][s], adj[in.ref][s], at(G)); ++C.adds; ++C.adjoint_adds; }
                    else { if (N[in.ref].materialize) ++C.reads_outside_demand; f.phase = 5; return push(1, in.ref, cidx, nullptr, &at(G)); }
                    if (!poll(4, f.nn)) return false;
                }
                f.i++;
            }
            for (auto& u : f.unresolved) if (u == 2) u = 0;
            f.a++; f.i = 0; f.phase = 0; return poll(1, f.nn);
        }
        return true;
    }

    // evaluate one entry / drain one delta synchronously through the frame machine
    bool value(int nn, int64_t idx, Num& out) { if (!push(0, nn, idx, &out, nullptr)) return false; return run(); }
    bool pull(int nn, int64_t idx, const Num& h) { if (!push(1, nn, idx, nullptr, &h)) return false; return run(); }

    int forward() {
        phase_tag = 1;
        if (!reserve(used_scratch, caps.scratch, (uint64_t)N.size() * (3 * sizeof(std::vector<Num>) + sizeof(std::unordered_map<int64_t, int64_t>)) + (uint64_t)N.size() * sizeof(std::vector<Num>))) return stop;   // per-node containers (values, dpos, Nx, adj)
        values.assign(N.size(), {}); dpos.assign(N.size(), {}); Nx.assign(N.size(), {});
        for (size_t nn = 0; nn < N.size(); ++nn) {
            NodeD& n = N[nn];
            if (!reserve(used_reverse, caps.reverse, (uint64_t)n.xc * P::bytes(prec))) return stop;
            Nx[nn].resize(n.xc); for (auto& x : Nx[nn]) P::init(x, prec);
            if (!n.materialize || n.demand_kind == 2) continue;
            int64_t cnt = n.demand_kind == 0 ? n.core : (int64_t)n.demand.size();
            if (!reserve(used_values, caps.values, (uint64_t)cnt * P::bytes(prec))) return stop;
            if (n.demand_kind == 1 && !reserve(used_index, caps.index, (uint64_t)cnt * 48)) return stop;             // unordered_map node estimate
            values[nn].resize(cnt); for (auto& x : values[nn]) P::init(x, prec);
            if (n.demand_kind == 1) { dpos[nn].reserve(cnt); for (int64_t s = 0; s < cnt; ++s) dpos[nn][n.demand[s]] = s; }
            C.entries_stored_planned += cnt;
            for (int64_t s = 0; s < cnt; ++s) {
                int64_t idx = n.demand_kind == 0 ? s : n.demand[s];
                if (!value((int)nn, idx, values[nn][s])) return stop;
                ++C.entries_materialized;
            }
        }
        P::copy(Z, scale);                                                                      // Z = scale * prod roots (roots: materialized scalar nodes, validated by parse_prog)
        for (int r : roots) { int64_t s = slot_of(r, 0); if (s < 0) return stop = GB_BADPROG; P::mul(Z, Z, values[r][s]); ++C.mults; ++C.root_ops; if (!poll(1, -1)) return stop; }
        snapshot(-1); return GB_OK;
    }

    int reverse() {
        phase_tag = 2;
        adj.assign(N.size(), {});
        for (size_t nn = 0; nn < N.size(); ++nn) if (N[nn].materialize && !values[nn].empty()) { if (!reserve(used_pending, caps.pending, (uint64_t)values[nn].size() * P::bytes(prec))) return stop; adj[nn].resize(values[nn].size()); for (auto& x : adj[nn]) P::init(x, prec); }
        size_t R = roots.size(); if (!reserve(used_reverse, caps.reverse, (uint64_t)(3 * R + 3) * P::bytes(prec))) return stop;
        std::vector<Num> rv(R), pre(R + 1), suf(R + 1); for (auto& x : rv) P::init(x, prec); for (auto& x : pre) P::init(x, prec); for (auto& x : suf) P::init(x, prec);
        auto release = [&]() { for (auto& x : rv) P::clear(x); for (auto& x : pre) P::clear(x); for (auto& x : suf) P::clear(x); };
        for (size_t i = 0; i < R; ++i) { int64_t s = slot_of(roots[i], 0); if (s < 0) { release(); return stop = GB_BADPROG; } P::copy(rv[i], values[roots[i]][s]); }
        P::set_one(pre[0]); for (size_t i = 0; i < R; ++i) { P::mul(pre[i + 1], pre[i], rv[i]); ++C.mults; ++C.root_ops; if (!poll(1, -1)) { release(); return stop; } } P::set_one(suf[R]); for (size_t i = R; i >= 1; --i) { P::mul(suf[i - 1], rv[i - 1], suf[i]); ++C.mults; ++C.root_ops; if (!poll(1, -1)) { release(); return stop; } }
        for (size_t i = 0; i < R; ++i) { Num h; P::init(h, prec); P::mul(h, pre[i], suf[i + 1]); P::mul(h, h, scale); C.mults += 2; C.root_ops += 2; int64_t s = slot_of(roots[i], 0); P::add(adj[roots[i]][s], adj[roots[i]][s], h); ++C.adds; ++C.adjoint_adds; P::clear(h); if (!poll(3, -1)) { release(); return stop; } }
        release();
        for (int nn = (int)N.size() - 1; nn >= 0; --nn) {                                       // each stored adjoint slot is drained exactly once, after its single consumer finished
            if (!N[nn].materialize) continue;
            for (size_t s = 0; s < values[nn].size(); ++s) {
                if (P::is_zero(adj[nn][s])) { if (!poll(1, nn)) return stop; continue; }
                int64_t idx = N[nn].demand_kind == 0 ? (int64_t)s : N[nn].demand[s];
                if (!pull(nn, idx, adj[nn][s])) return stop; ++C.slots_drained;
            }
        }
        snapshot(-1); return GB_OK;
    }
};

// ------------------------------------------------------------------------------------------------------------ C API (type-erased)
struct Handle { int mode; Exec<Ival>* I; Exec<Dbl>* D; long emin, emax; };
static void set_from_double(Dbl::T& dst, double v) { dst.v = v; dst.e = (v == 0.0 ? 0 : test_leaf_label); }
static void set_from_double(Ival::T& dst, double v) { mpfr_set_d(dst.lo, v, MPFR_RNDD); mpfr_set_d(dst.hi, v, MPFR_RNDU); }

struct Reader { const int64_t* p; int64_t n; int64_t i = 0; int64_t rd() { if (i >= n) throw BadProg("program truncated"); return p[i++]; } int rdi() { int64_t v = rd(); if (v < -1 || v > 2147483647LL) throw BadProg("program field outside int32"); return (int)v; } int64_t rdn() { int64_t v = rd(); if (v < 0) throw BadProg("negative count"); return v; } };

static uint64_t ir_bytes_bound(int64_t plen) { return (uint64_t)plen * (sizeof(int64_t) + sizeof(int)) + (uint64_t)plen * 4 * sizeof(std::vector<int>) / 8 + 4096; }   // conservative: every word -> one int64 stride/one int + amortised vector headers
static void parse_prog(const int64_t* prog, int64_t plen, std::vector<FactorD>& F, std::vector<NodeD>& N, std::vector<int>& roots, int64_t nfac_vals, int64_t nratio_vals) {
    // flat int64 program: [nF] per factor: arity, scope..., card..., entries, val_off ; [nN] per node: x, xc, nin, (kind, ref)*nin, nscope, scope..., per axis: nraw, cls[nraw], nreps, reps[nreps], ratio_off ; core, consumer, materialize, demand_kind, ndemand, demand... ; [nroots] roots...
    Reader r{prog, plen}; int64_t nF = r.rdn(); if (nF > plen) throw BadProg("factor count"); F.resize(nF);
    for (int64_t i = 0; i < nF; ++i) { FactorD& f = F[i]; int ar = r.rdi(); if (ar < 0) throw BadProg("arity"); f.scope.resize(ar); f.card.resize(ar); f.stride.resize(ar); for (int k = 0; k < ar; ++k) f.scope[k] = r.rdi(); for (int k = 0; k < ar; ++k) { f.card[k] = r.rdi(); if (f.card[k] < 1) throw BadProg("card"); } f.entries = r.rdn(); f.val_off = r.rdn();
        int64_t st = 1; for (int k = ar - 1; k >= 0; --k) { f.stride[k] = st; if (st > INT64_MAX / f.card[k]) throw BadProg("table size overflow"); st *= f.card[k]; } if (st != f.entries || f.val_off > nfac_vals - f.entries) throw BadProg("table size / offset"); }
    int64_t nN = r.rdn(); if (nN > plen) throw BadProg("node count"); N.resize(nN);
    for (int64_t i = 0; i < nN; ++i) { NodeD& n = N[i]; n.x = r.rdi(); n.xc = r.rdi(); if (n.xc < 1) throw BadProg("xc"); int nin = r.rdi(); if (nin < 0) throw BadProg("nin"); n.inputs.resize(nin); n.nfac_inputs = 0;
        for (int k = 0; k < nin; ++k) { n.inputs[k].kind = r.rdi(); n.inputs[k].ref = r.rdi(); if (n.inputs[k].kind == 0) { if (n.inputs[k].ref < 0 || n.inputs[k].ref >= nF) throw BadProg("factor ref"); ++n.nfac_inputs; } else if (n.inputs[k].kind == 1) { if (n.inputs[k].ref < 0 || n.inputs[k].ref >= i) throw BadProg("message ref must precede its consumer"); } else throw BadProg("input kind"); }
        int ns = r.rdi(); if (ns < 0) throw BadProg("nscope"); n.scope.resize(ns); n.axes.resize(ns); n.radix.resize(ns);
        for (int k = 0; k < ns; ++k) n.scope[k] = r.rdi();
        int64_t core = 1;
        for (int k = 0; k < ns; ++k) { AxisD& ax = n.axes[k]; ax.var = n.scope[k]; ax.nraw = r.rdi(); if (ax.nraw < 1) throw BadProg("nraw"); ax.cls.resize(ax.nraw); for (int q = 0; q < ax.nraw; ++q) ax.cls[q] = r.rdi(); int nr = r.rdi(); if (nr < 1 || nr > ax.nraw) throw BadProg("nreps"); ax.reps.resize(nr); for (int q = 0; q < nr; ++q) { ax.reps[q] = r.rdi(); if (ax.reps[q] < 0 || ax.reps[q] >= ax.nraw) throw BadProg("rep"); } for (int q = 0; q < ax.nraw; ++q) if (ax.cls[q] < 0 || ax.cls[q] >= nr) throw BadProg("cls"); ax.ratio_off = r.rdn(); if (ax.ratio_off > nratio_vals - ax.nraw) throw BadProg("ratio offset"); n.radix[k] = nr; if (core > INT64_MAX / nr) throw BadProg("core volume exceeds int64"); core *= nr; }
        n.core = r.rdn(); if (n.core != core) throw BadProg("core != product of radices"); n.consumer = r.rdi(); if (n.consumer != -1 && n.consumer <= i) throw BadProg("consumer must follow"); n.materialize = r.rd() != 0; n.demand_kind = r.rdi(); if (n.demand_kind < 0 || n.demand_kind > 2) throw BadProg("demand kind");
        int64_t nd = r.rdn(); if (nd > plen) throw BadProg("ndemand"); n.demand.resize(nd); int64_t prev = -1; for (int64_t q = 0; q < nd; ++q) { n.demand[q] = r.rd(); if (n.demand[q] <= prev || n.demand[q] >= core) throw BadProg("demand list must be sorted, unique, < core"); prev = n.demand[q]; }
        if (n.demand_kind == 1 && nd == 0) n.demand_kind = 2; if (n.demand_kind != 1 && nd != 0) throw BadProg("demand list with non-LIST kind"); }
    int64_t nr = r.rdn(); if (nr > nN) throw BadProg("roots"); roots.resize(nr); for (int64_t i = 0; i < nr; ++i) { roots[i] = r.rdi(); if (roots[i] < 0 || roots[i] >= nN || N[roots[i]].consumer != -1 || !N[roots[i]].scope.empty() || !N[roots[i]].materialize) throw BadProg("root must be a materialized scalar node without consumer"); }
    if (r.i != plen) throw BadProg("trailing program words");
}

template <class P> static int load_values(Exec<P>& E, const char* const* qs, int64_t nfac_vals, int64_t nratio_vals, const double* dbl_vals) {
    uint64_t bytes = (uint64_t)(nfac_vals + nratio_vals + 1) * P::bytes(E.prec); uint64_t maxlen = 0;
    if (!dbl_vals) for (int64_t i = 0; i < nfac_vals + nratio_vals + 1; ++i) { uint64_t l = std::strlen(qs[i]); if (l > maxlen) maxlen = l; if (!E.poll(1, -1)) return GB_DEADLINE; }
    bytes += 2 * (maxlen + 64) + 2 * sizeof(mpq_t);                                                                    // the mpq conversion temporary (digits -> limbs; bounded by the longest token)
    if (!E.reserve(E.used_scratch, E.caps.scratch, bytes)) return GB_MEMORY;                                             // source values + conversion temporary live in the frames/scratch/source category
    E.fvals.resize(nfac_vals); E.ratios.resize(nratio_vals); mpq_t q; mpq_init(q);
    for (int64_t i = 0; i < nfac_vals + nratio_vals + 1; ++i) {
        typename P::T* dst = i < nfac_vals ? &E.fvals[i] : (i < nfac_vals + nratio_vals ? &E.ratios[i - nfac_vals] : &E.scale);
        if (i < nfac_vals + nratio_vals) P::init(*dst, E.prec);                                                           // scale was initialised by the constructor (V1 leaked one init)
        if (dbl_vals) { set_from_double(*dst, dbl_vals[i]); } else { if (mpq_set_str(q, qs[i], 10) != 0) { mpq_clear(q); return GB_BADPROG; } mpq_canonicalize(q); if (mpq_sgn(q) < 0) { mpq_clear(q); return GB_BADPROG; } P::set_q(*dst, q, E.prec); }
        if (!E.poll(1, -1)) { mpq_clear(q); return GB_DEADLINE; }
    }
    mpq_clear(q); return GB_OK;
}

// ambient binary64 environment probes (the nearest-rounding theorem's premise): rounding mode + two live rounding tests + no flush-to-zero
static int fp_env_ok() {
    if (fegetround() != FE_TONEAREST) return 0;
    volatile double one = 1.0, up = 0x1p-54, dn = 0x1p-55, tiny = 0x1p-1022, half = 0.5;
    if ((double)(one + up) != 1.0) return 0;             // upward would give 1 + 2^-52
    if ((double)(one - dn) != 1.0) return 0;             // downward / toward-zero would give 1 - 2^-53
    if ((double)(tiny * half) == 0.0) return 0;          // flush-to-zero
    return 1;
}
extern "C" int gb_fp_env_ok() { return fp_env_ok(); }
// qualification hooks (process-local; never used by cells): override the exponent range configured at the next MPFR create; inject one std::bad_alloc
extern "C" void gb_test_exponent_range(long emin, long emax) { test_emin = emin; test_emax = emax; }
extern "C" void gb_test_inject_bad_alloc(int on) { test_bad_alloc = on; }
extern "C" void gb_test_leaf_label(unsigned long long e) { test_leaf_label = e ? (uint64_t)e : 1; }   // qualification: forces the label of every converted leaf (native label-cap branch)

extern "C" {

// remaining_s: seconds from NOW (the kernel's own CLOCK_MONOTONIC). err_out receives a Stop code on failure (nullptr returned).
Handle* gb_create(int mode, int prec, const int64_t* prog, int64_t plen, const char* const* qs, const double* dbl_vals, int64_t nfac_vals, int64_t nratio_vals, const uint64_t* caps5, double remaining_s, int* err_out) {
    Handle* h = nullptr; int err = GB_OK;
    try {
        h = new Handle(); h->mode = mode; h->I = nullptr; h->D = nullptr; Caps caps{caps5[0], caps5[1], caps5[2], caps5[3], caps5[4]}; double deadline_mono = now_mono() + remaining_s;
        if (mode == 0) {
            mpfr_set_emin(test_emin ? test_emin : mpfr_get_emin_min()); mpfr_set_emax(test_emax ? test_emax : mpfr_get_emax_max()); mpfr_clear_flags(); h->emin = (long)mpfr_get_emin(); h->emax = (long)mpfr_get_emax();
            h->I = new Exec<Ival>(prec); h->I->caps = caps; h->I->deadline = deadline_mono; if (!h->I->reserve(h->I->used_index, caps.index, ir_bytes_bound(plen))) throw std::runtime_error("ir"); parse_prog(prog, plen, h->I->F, h->I->N, h->I->roots, nfac_vals, nratio_vals); err = load_values(*h->I, qs, nfac_vals, nratio_vals, nullptr);
        } else {
            if (!fp_env_ok()) throw std::runtime_error("fpenv"); Dbl::range_fault = false;
            h->D = new Exec<Dbl>(53); h->D->caps = caps; h->D->deadline = deadline_mono; if (!h->D->reserve(h->D->used_index, caps.index, ir_bytes_bound(plen))) throw std::runtime_error("ir"); parse_prog(prog, plen, h->D->F, h->D->N, h->D->roots, nfac_vals, nratio_vals); err = load_values(*h->D, qs, nfac_vals, nratio_vals, dbl_vals);
        }
        if (err != GB_OK) throw std::runtime_error("load");
        return h;
    } catch (const BadProg&) { err = GB_BADPROG; }
      catch (const std::bad_alloc&) { err = GB_MEMORY; }
      catch (const std::runtime_error& ex) { if (std::strcmp(ex.what(), "fpenv") == 0) err = GB_FPENV; else if (std::strcmp(ex.what(), "ir") == 0) err = GB_MEMORY; else if (err == GB_OK) err = GB_FAULT; }
      catch (...) { err = GB_FAULT; }
    if (h) { delete h->I; delete h->D; delete h; }
    if (err_out) *err_out = err; return nullptr;
}
void gb_destroy(Handle* h) { if (!h) return; try { delete h->I; delete h->D; delete h; } catch (...) {} }
static int mpfr_flags_stop() { return (mpfr_overflow_p() || mpfr_underflow_p() || mpfr_nanflag_p() || mpfr_erangeflag_p()) ? GB_RANGE : GB_OK; }
int gb_forward(Handle* h) { try { if (h->mode == 1 && !fp_env_ok()) return GB_FPENV; int st = h->mode == 0 ? h->I->forward() : h->D->forward(); if (st == GB_OK && h->mode == 0) st = mpfr_flags_stop(); if (st == GB_OK && h->mode == 1 && (Dbl::range_fault || !Dbl::finite(h->D->Z))) st = GB_RANGE; return st; } catch (const std::bad_alloc&) { return GB_MEMORY; } catch (...) { return GB_FAULT; } }
int gb_reverse(Handle* h) { try { if (h->mode == 1 && !fp_env_ok()) return GB_FPENV; int st = h->mode == 0 ? h->I->reverse() : h->D->reverse(); if (st == GB_OK && h->mode == 0) st = mpfr_flags_stop(); if (st == GB_OK && h->mode == 1 && Dbl::range_fault) st = GB_RANGE; return st; } catch (const std::bad_alloc&) { return GB_MEMORY; } catch (...) { return GB_FAULT; } }
int gb_mpfr_flags(Handle* h) { (void)h; return (mpfr_overflow_p() ? 1 : 0) | (mpfr_underflow_p() ? 2 : 0) | (mpfr_nanflag_p() ? 4 : 0) | (mpfr_erangeflag_p() ? 8 : 0) | (mpfr_inexflag_p() ? 16 : 0); }

#define CTRS(E) uint64_t v[32] = {E.C.primal_rows, E.C.reverse_rows, E.C.rows_skipped_zero, E.C.mults, E.C.adds, E.C.lookups, E.C.value_frames, E.C.pullback_frames, E.C.stream_reevals, E.C.reads_outside_demand, E.C.entries_materialized, E.C.entries_stored_planned, E.C.numerator_adds, E.C.adjoint_adds, E.C.slots_drained, E.C.polls, E.C.max_frame_depth, E.C.root_ops, E.used_values, E.used_index, E.used_reverse, E.used_pending, E.used_scratch, E.peak_scratch, 0, 0, 0, 0, 0, 0, 0, 0}; std::memcpy(out32, v, sizeof(v));
void gb_counters(Handle* h, uint64_t* out32) { if (h->mode == 0) { CTRS((*h->I)) } else { CTRS((*h->D)) } }
// live snapshot (atomics written at each poll): primal_rows, reverse_rows, value_frames, pullback_frames, frame_depth, active_node, used_scratch, phase (1 fwd 2 rev)
void gb_snapshot(Handle* h, uint64_t* out8) { if (!h) return; if (h->mode == 0) for (int i = 0; i < 8; ++i) out8[i] = h->I->snap[i].load(); else for (int i = 0; i < 8; ++i) out8[i] = h->D->snap[i].load(); }
int gb_num_nodes(Handle* h) { return (int)(h->mode == 0 ? h->I->N.size() : h->D->N.size()); }

// results: Z (lo,hi) then every node's N[x][a] (lo,hi) as EXACT hex strings (';' separated). Returns bytes written, -1 if buflen is insufficient
// (the caller retries with a larger buffer), -2 if an endpoint is not a finite nonnegative number (typed RANGE failure: nothing is exported).
// exact export size needed by gb_results_hex (bytes incl. separators and the terminator); -2 on a non-finite endpoint
int64_t gb_results_size(Handle* h) {
    try {
        int64_t total = 1;
        if (h->mode == 0) { Exec<Ival>& E = *h->I; auto len = [&](mpfr_t x) -> int64_t { if (!mpfr_number_p(x) || mpfr_sgn(x) < 0) return -1; if (mpfr_zero_p(x)) return 2; return (int64_t)((mpfr_get_prec(x) + 3) / 4) + 32; };
            if (!Ival::finite(E.Z)) return -2; total += len(E.Z.lo) + len(E.Z.hi);
            for (size_t nn = 0; nn < E.N.size(); ++nn) for (int a = 0; a < E.N[nn].xc; ++a) { if (!Ival::finite(E.Nx[nn][a])) return -2; total += len(E.Nx[nn][a].lo) + len(E.Nx[nn][a].hi); } }
        else { Exec<Dbl>& E = *h->D; if (Dbl::range_fault || !Dbl::finite(E.Z)) return -2; total += 2 * 64; for (size_t nn = 0; nn < E.N.size(); ++nn) for (int a = 0; a < E.N[nn].xc; ++a) { if (!Dbl::finite(E.Nx[nn][a])) return -2; total += 2 * 64; } }
        return total;
    } catch (...) { return -3; }
}
int gb_results_hex(Handle* h, char* buf, int64_t buflen) {
    try {
        int64_t p = 0; char tmp[2048];
        auto put = [&](const char* s) { int64_t n = (int64_t)std::strlen(s); if (p + n + 2 > buflen) return false; std::memcpy(buf + p, s, n); p += n; buf[p++] = ';'; return true; };
        if (h->mode == 0) {
            auto hex = [&](mpfr_t x) { if (!mpfr_number_p(x) || mpfr_sgn(x) < 0) return false; if (mpfr_zero_p(x)) { std::snprintf(tmp, sizeof tmp, "0"); return true; } mpfr_exp_t e; char* s = mpfr_get_str(nullptr, &e, 16, 0, x, MPFR_RNDN); std::snprintf(tmp, sizeof tmp, "%s@%ld", s, (long)e); mpfr_free_str(s); return true; };
            Exec<Ival>& E = *h->I;
            for (size_t nn = 0; nn < E.N.size(); ++nn) for (int a = 0; a < E.N[nn].xc; ++a) if (!Ival::finite(E.Nx[nn][a])) return -2;
            if (!Ival::finite(E.Z)) return -2;
            if (!hex(E.Z.lo) || !put(tmp)) return -1; if (!hex(E.Z.hi) || !put(tmp)) return -1;
            for (size_t nn = 0; nn < E.N.size(); ++nn) for (int a = 0; a < E.N[nn].xc; ++a) { if (!hex(E.Nx[nn][a].lo) || !put(tmp)) return -1; if (!hex(E.Nx[nn][a].hi) || !put(tmp)) return -1; }
        } else {
            Exec<Dbl>& E = *h->D;
            if (!Dbl::finite(E.Z)) return -2;
            for (size_t nn = 0; nn < E.N.size(); ++nn) for (int a = 0; a < E.N[nn].xc; ++a) if (!Dbl::finite(E.Nx[nn][a])) return -2;
            if (Dbl::range_fault) return -2;
            std::snprintf(tmp, sizeof tmp, "%a@%llu", E.Z.v, (unsigned long long)E.Z.e); if (!put(tmp)) return -1; if (!put(tmp)) return -1;
            for (size_t nn = 0; nn < E.N.size(); ++nn) for (int a = 0; a < E.N[nn].xc; ++a) { std::snprintf(tmp, sizeof tmp, "%a@%llu", E.Nx[nn][a].v, (unsigned long long)E.Nx[nn][a].e); if (!put(tmp)) return -1; if (!put(tmp)) return -1; }
        }
        buf[p] = 0; return (int)p;
    } catch (...) { return -3; }
}

// qualification hook: inject the root adjoint as two separate deltas w1 then w2 with optional eviction (zero + recompute) of every stored non-root value
// between them. Requires forward() done; replaces reverse(). Exercises exact-once delta ownership + regeneration through the SAME frame machine.
int gb_test_split_root(Handle* h, const char* w1, const char* w2, int evict) {
    try {
        if (h->mode != 0 || h->I->roots.size() != 1) return GB_BADPROG;
        Exec<Ival>& E = *h->I; int r = E.roots[0]; E.adj.assign(E.N.size(), {});
        for (size_t nn = 0; nn < E.N.size(); ++nn) if (E.N[nn].materialize) { E.adj[nn].resize(E.values[nn].size()); for (auto& x : E.adj[nn]) Ival::init(x, E.prec); }
        mpq_t q; mpq_init(q); Ival::T hw; Ival::init(hw, E.prec); E.top = 0;
        for (int pass = 0; pass < 2; ++pass) {
            mpq_set_str(q, pass == 0 ? w1 : w2, 10); mpq_canonicalize(q); Ival::set_q(hw, q, E.prec); Ival::mul(hw, hw, E.scale);
            if (!E.pull(r, 0, hw)) { mpq_clear(q); Ival::clear(hw); return E.stop; } ++E.C.slots_drained;
            for (int nn = (int)E.N.size() - 1; nn >= 0; --nn) { if (!E.N[nn].materialize || nn == r) continue; for (size_t s = 0; s < E.values[nn].size(); ++s) { if (Ival::is_zero(E.adj[nn][s])) continue; int64_t idx = E.N[nn].demand_kind == 0 ? (int64_t)s : E.N[nn].demand[s]; if (!E.pull(nn, idx, E.adj[nn][s])) { mpq_clear(q); Ival::clear(hw); return E.stop; } Ival::set_zero(E.adj[nn][s]); ++E.C.slots_drained; } }
            if (pass == 0 && evict) {
                for (size_t nn = 0; nn < E.N.size(); ++nn) { if (!E.N[nn].materialize || (int)nn == r) continue; for (size_t s = 0; s < E.values[nn].size(); ++s) { int64_t idx = E.N[nn].demand_kind == 0 ? (int64_t)s : E.N[nn].demand[s]; Ival::set_zero(E.values[nn][s]); if (!E.value((int)nn, idx, E.values[nn][s])) { mpq_clear(q); Ival::clear(hw); return E.stop; } } }
            }
        }
        mpq_clear(q); Ival::clear(hw); return mpfr_flags_stop();
    } catch (const std::bad_alloc&) { return GB_MEMORY; } catch (...) { return GB_FAULT; }
}

// ------------------------------------------------------------------------------------------------------------ exact integer reference stream (GB-07)
// Mixed-radix odometer over the reduced variables (no assignment-count gate; the visited counter saturates at UINT64_MAX), every factor occurrence
// multiplied in mpz after per-factor denominator clearing; Z and every N[x][a] in mpz. Polls charged per factor visit.
struct Mz { mpz_t z; };
struct RefState { int nv; std::vector<int> card; std::vector<FactorD> F; std::vector<Mz> tabs; mpz_t Z; std::vector<std::vector<Mz>> Nx; uint64_t visited; bool done; std::vector<int> x; double deadline; uint64_t used_values, used_scratch, cap_values, cap_scratch, acc_bits_bound; };
// caps5 as for gb_create: tables + accumulators are charged to the VALUE category, the IR / odometer / product temporary / export to the SCRATCH category;
// every mpz is reserved at its CONSERVATIVE bound before allocation: table entry <= digits*0.42+1 limbs; product w <= sum over factors of max entry bits;
// accumulators <= product bits + bits(total assignments) + 1. The export buffer size is computed exactly by gb_ref_results_size (Python reserves it).
RefState* gb_ref_create(const int64_t* prog, int64_t plen, const char* const* int_vals, double remaining_s, const uint64_t* caps5, int* err_out) {
    RefState* S = nullptr;
    try {
        double deadline = now_mono() + remaining_s; Reader r{prog, plen};
        S = new RefState(); S->used_values = S->used_scratch = 0; S->cap_values = caps5 ? caps5[0] : UINT64_MAX; S->cap_scratch = caps5 ? caps5[4] : UINT64_MAX;
        auto reserve = [&](uint64_t& used, uint64_t cap, uint64_t bytes) { if (bytes > cap || used > cap - bytes) throw std::runtime_error("refmem"); used += bytes; };
        reserve(S->used_scratch, S->cap_scratch, ir_bytes_bound(plen) + sizeof(RefState));
        S->nv = r.rdi(); if (S->nv < 0) throw BadProg("nv"); S->card.resize(S->nv); for (int i = 0; i < S->nv; ++i) { S->card[i] = r.rdi(); if (S->card[i] < 1) throw BadProg("card"); }
        int64_t nF = r.rdn(); S->F.resize(nF); int64_t tot = 0;
        for (int64_t i = 0; i < nF; ++i) { FactorD& f = S->F[i]; int ar = r.rdi(); if (ar < 0) throw BadProg("arity"); f.scope.resize(ar); f.card.resize(ar); f.stride.resize(ar); for (int k = 0; k < ar; ++k) { f.scope[k] = r.rdi(); if (f.scope[k] < 0 || f.scope[k] >= S->nv) throw BadProg("scope"); } for (int k = 0; k < ar; ++k) f.card[k] = r.rdi(); f.entries = r.rdn(); f.val_off = tot; tot += f.entries; int64_t st = 1; for (int k = ar - 1; k >= 0; --k) { f.stride[k] = st; st *= f.card[k]; } if (st != f.entries) throw BadProg("entries"); }
        if (r.i != plen) throw BadProg("trailing");
        // table bytes bound from the decimal token lengths; product bound from the per-factor maximum entry bits
        uint64_t tab_bytes = 0; uint64_t prod_bits = 64; int64_t idx = 0;
        for (int64_t i = 0; i < nF; ++i) { uint64_t fmax = 0; for (int64_t e = 0; e < S->F[i].entries; ++e, ++idx) { uint64_t l = std::strlen(int_vals[idx]); tab_bytes += sizeof(mpz_t) + 8 * (l * 42 / 100 / 8 + 2); uint64_t bits = l * 3322 / 1000 + 1; if (bits > fmax) fmax = bits; } prod_bits += fmax; }
        uint64_t total_bits = 1; for (int v = 0; v < S->nv; ++v) { total_bits += 64 - __builtin_clzll((unsigned long long)S->card[v]); }
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
uint64_t gb_ref_used_values(RefState* S) { return S->used_values; }
uint64_t gb_ref_used_scratch(RefState* S) { return S->used_scratch; }
int64_t gb_ref_results_size(RefState* S) { try { int64_t t = 1 + (int64_t)mpz_sizeinbase(S->Z, 10) + 2; for (int v = 0; v < S->nv; ++v) for (int a = 0; a < S->card[v]; ++a) t += (int64_t)mpz_sizeinbase(S->Nx[v][a].z, 10) + 2; return t; } catch (...) { return -3; } }
int gb_ref_run(RefState* S) {
    try {
        if (S->done) return GB_OK;
        mpz_t w; mpz_init(w); uint64_t ops = 0;
        for (;;) {
            mpz_set_ui(w, 1); bool zero = false;
            for (const FactorD& f : S->F) { int64_t off = 0; for (size_t k = 0; k < f.scope.size(); ++k) off += (int64_t)S->x[f.scope[k]] * f.stride[k]; const Mz& e = S->tabs[f.val_off + off]; if (mpz_sgn(e.z) == 0) { zero = true; break; } mpz_mul(w, w, e.z); if (++ops >= POLL_OPS) { ops = 0; if (now_mono() > S->deadline) { mpz_clear(w); return GB_DEADLINE; } } }
            if (!zero) { mpz_add(S->Z, S->Z, w); for (int v = 0; v < S->nv; ++v) { mpz_add(S->Nx[v][S->x[v]].z, S->Nx[v][S->x[v]].z, w); if (++ops >= POLL_OPS) { ops = 0; if (now_mono() > S->deadline) { mpz_clear(w); return GB_DEADLINE; } } } }
            if (S->visited != UINT64_MAX) ++S->visited;
            int v = S->nv - 1; while (v >= 0) { if (++S->x[v] < S->card[v]) break; S->x[v] = 0; --v; }      // odometer (resumable: S->x persists across deadline returns)
            if (v < 0) { S->done = true; break; }
            if (++ops >= POLL_OPS) { ops = 0; if (now_mono() > S->deadline) { mpz_clear(w); return GB_DEADLINE; } }
        }
        mpz_clear(w); return GB_OK;
    } catch (const std::bad_alloc&) { return GB_MEMORY; } catch (...) { return GB_FAULT; }
}
uint64_t gb_ref_visited(RefState* S) { return S->visited; }
int gb_ref_results(RefState* S, char* buf, int64_t buflen) {
    try {
        int64_t p = 0; auto put = [&](mpz_ptr z) { char* s = mpz_get_str(nullptr, 10, z); int64_t n = (int64_t)std::strlen(s); if (p + n + 2 > buflen) { std::free(s); return false; } std::memcpy(buf + p, s, n); p += n; buf[p++] = ';'; std::free(s); return true; };
        if (!put(S->Z)) return -1; for (int v = 0; v < S->nv; ++v) for (int a = 0; a < S->card[v]; ++a) if (!put(S->Nx[v][a].z)) return -1; buf[p] = 0; return (int)p;
    } catch (...) { return -3; }
}
void gb_ref_destroy(RefState* S) { if (!S) return; for (auto& z : S->tabs) mpz_clear(z.z); mpz_clear(S->Z); for (auto& v : S->Nx) for (auto& z : v) mpz_clear(z.z); delete S; }

const char* gb_mpfr_version() { return mpfr_get_version(); }
const char* gb_gmp_version() { return gmp_version; }
long gb_mpfr_emin() { return (long)mpfr_get_emin(); }
long gb_mpfr_emax() { return (long)mpfr_get_emax(); }
long gb_mpfr_emin_min() { return (long)mpfr_get_emin_min(); }
long gb_mpfr_emax_max() { return (long)mpfr_get_emax_max(); }
// bytes charged per stored value by the kernel (the planner uses the SAME number): mode 0 MPFR interval at precision prec, mode 1 binary64 with label
int64_t gb_bytes_per_entry(int mode, int prec) { return mode == 0 ? (int64_t)Ival::bytes(prec) : (int64_t)Dbl::bytes(prec); }

} // extern "C"
