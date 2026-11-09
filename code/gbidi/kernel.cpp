// GENERAL_BIDI_V1 native executor (9 Nov 2026): one indexed sum-product bucket program over CORE classes with exact response views, demand
// lists, fused (streamed, zero-memo) children, zero-safe local reverse into original-marker numerators, category memory accounting and
// in-loop deadline polling. Two arithmetic policies share the code by template: outward MPFR intervals (general route) and nearest binary64
// (optional route; the Python executor admits it only after the range / depth proof of the ACTUAL plan). No division anywhere.
//
// Program (metadata from Python, nothing allocated before gb_create):
//   node n: eliminated variable x (card xc), inputs (F fid | M child), scope vars (sorted), per scope axis: raw card, cls[raw]->class, reps[class]->raw,
//   ratio[raw] (exact rational -> Num), radix = classes per axis, core_entries = prod radix, consumer node (or -1 = component root),
//   materialize flag (else fused: values recomputed on demand by its consumer, zero memo), optional demand list (sorted core indices; empty = FULL).
//   factor f: scope vars, cards, strides, entries (Num).
// Value of core entry idx of n (digits over classes -> representative raw states): sum_a prod_inputs input(raw assignment with x=a).
//   F input: table[offset(raw)]; M input child c: ratio_c(raw restricted to c.scope) * core_c[class index of raw] (or recomputed if fused).
// Reverse (reverse node order): adj of a materialized entry drains to its inputs with prefix/suffix sibling products; N[x][a] += adj * row.
// Deltas: a materialized node's adjoint array is its pending delta store; it is drained exactly once when the node is processed (its single
// consumer is finished); gb_test_split_root lets qualification inject two root deltas separately with value eviction in between.
#include <cstdint>
#include <cstdlib>
#include <cstring>
#include <cmath>
#include <ctime>
#include <vector>
#include <unordered_map>
#include <deque>
#include <algorithm>
#include <gmp.h>
#include <mpfr.h>

static const char* GB_SCHEDULE = "GENERAL_BIDI_V1/bucket-core-views-demand-fused-localreverse/v1";
extern "C" const char* gb_schedule_id() { return GB_SCHEDULE; }

enum Stop : int { GB_OK = 0, GB_DEADLINE = 1, GB_MEMORY = 2, GB_OVERFLOW = 3, GB_RANGE = 4, GB_BADPROG = 5 };

static double now_mono() { struct timespec ts; clock_gettime(CLOCK_MONOTONIC, &ts); return ts.tv_sec + 1e-9 * ts.tv_nsec; }

// ------------------------------------------------------------------------------------------------------------ numeric policies
struct Dbl {                    // nearest binary64 (optional route)
    typedef double T;
    static void init(T& x, int) { x = 0.0; }
    static void clear(T&) {}
    static void set_zero(T& x) { x = 0.0; }
    static void set_one(T& x) { x = 1.0; }
    static void set_q(T& x, mpq_t q, int) { (void)q; x = 0.0; }        // never used: the binary64 route receives Python-verified doubles (dbl_vals)
    static void add(T& r, const T& a, const T& b) { r = a + b; }
    static void mul(T& r, const T& a, const T& b) { r = a * b; }
    static bool is_zero(const T& x) { return x == 0.0; }
    static bool finite(const T& x) { return std::isfinite(x) && x >= 0.0; }
    static size_t bytes(int) { return sizeof(double); }
};
struct Ival {                   // outward MPFR interval [lo, hi]
    struct T { mpfr_t lo, hi; };
    static void init(T& x, int p) { mpfr_init2(x.lo, p); mpfr_init2(x.hi, p); mpfr_set_zero(x.lo, 1); mpfr_set_zero(x.hi, 1); }
    static void clear(T& x) { mpfr_clear(x.lo); mpfr_clear(x.hi); }
    static void set_zero(T& x) { mpfr_set_zero(x.lo, 1); mpfr_set_zero(x.hi, 1); }
    static void set_one(T& x) { mpfr_set_ui(x.lo, 1, MPFR_RNDD); mpfr_set_ui(x.hi, 1, MPFR_RNDU); }
    static void set_q(T& x, mpq_t q, int) { mpfr_set_q(x.lo, q, MPFR_RNDD); mpfr_set_q(x.hi, q, MPFR_RNDU); }
    static void add(T& r, const T& a, const T& b) { mpfr_add(r.lo, a.lo, b.lo, MPFR_RNDD); mpfr_add(r.hi, a.hi, b.hi, MPFR_RNDU); }
    static void mul(T& r, const T& a, const T& b) { mpfr_mul(r.lo, a.lo, b.lo, MPFR_RNDD); mpfr_mul(r.hi, a.hi, b.hi, MPFR_RNDU); }
    static bool is_zero(const T& x) { return mpfr_zero_p(x.hi); }
    static bool finite(const T& x) { return mpfr_number_p(x.lo) && mpfr_number_p(x.hi) && mpfr_sgn(x.lo) >= 0; }
    static size_t bytes(int p) { return 2 * (sizeof(mpfr_t) + 8 * (size_t)((p + 63) / 64)); }
};

// ------------------------------------------------------------------------------------------------------------ program description (shared)
struct FactorD { std::vector<int> scope; std::vector<int> card; std::vector<int64_t> stride; int64_t entries; int64_t val_off; };
struct AxisD { int var; int nraw; std::vector<int> cls; std::vector<int> reps; int64_t ratio_off; };
struct InputD { int kind; int ref; };                                   // kind 0 = F, 1 = M
struct NodeD { int x; int xc; std::vector<InputD> inputs; std::vector<int> scope; std::vector<AxisD> axes; std::vector<int64_t> radix; int64_t core; int consumer; bool materialize; std::vector<int64_t> demand; std::vector<int> fpos_cache; };

struct Caps { uint64_t values, index, reverse, pending, scratch; };
struct Counters { uint64_t rows, mults, adds, lookups, fused_reevals, entries_materialized, entries_demanded, adj_increments, deltas_drained, recomputations, polls; };

template <class P> struct Exec {
    typedef typename P::T Num;
    int prec; std::vector<FactorD> F; std::vector<NodeD> N; std::vector<Num> fvals, ratios;    // factor entries and view ratios (converted)
    std::vector<std::vector<Num>> values;      // per node (materialized): one slot per demanded entry (dense when FULL)
    std::vector<std::unordered_map<int64_t, int64_t>> dpos;   // demand index -> slot
    std::vector<std::vector<Num>> adj;         // per node (materialized): pending adjoint deltas per slot
    std::vector<std::vector<Num>> Nx;          // per node: numerators of its eliminated variable (xc)
    Num scale, Z; std::vector<int> roots;
    Caps caps; uint64_t used_values = 0, used_index = 0, used_reverse = 0, used_scratch = 0; Counters C{}; double deadline; int stop = GB_OK; uint64_t ops_since_poll = 0;
    std::deque<Num> scratch; size_t top = 0;   // frame scratch: bump allocator over a deque (references stay valid when it grows)
    bool evict_test = false;

    Exec(int p) : prec(p) { P::init(scale, p); P::init(Z, p); }
    ~Exec() { for (auto& v : values) for (auto& x : v) P::clear(x); for (auto& v : adj) for (auto& x : v) P::clear(x); for (auto& v : Nx) for (auto& x : v) P::clear(x); for (auto& x : fvals) P::clear(x); for (auto& x : ratios) P::clear(x); for (auto& x : scratch) P::clear(x); P::clear(scale); P::clear(Z); }

    inline bool poll() { if (++ops_since_poll >= 4096) { ops_since_poll = 0; ++C.polls; if (now_mono() > deadline) { stop = GB_DEADLINE; return false; } } return true; }
    bool reserve(uint64_t& used, uint64_t cap, uint64_t bytes) { if (used + bytes > cap) { stop = GB_MEMORY; return false; } used += bytes; return true; }
    size_t frame_alloc(size_t n) { size_t base = top; top += n; while (scratch.size() < top) { scratch.emplace_back(); P::init(scratch.back(), prec); used_scratch += P::bytes(prec); } return base; }
    Num& at(size_t i) { return scratch[i]; }

    // digits of a core index over the node's radix (last axis fastest)
    void digits(const NodeD& n, int64_t idx, std::vector<int>& d) { d.resize(n.radix.size()); for (int k = (int)n.radix.size() - 1; k >= 0; --k) { d[k] = (int)(idx % n.radix[k]); idx /= n.radix[k]; } }

    // raw state of variable w for consumer n's entry digits with x = a
    inline int raw_of(const NodeD& n, const std::vector<int>& d, int a, int w) const { if (w == n.x) return a; for (size_t k = 0; k < n.scope.size(); ++k) if (n.scope[k] == w) return n.axes[k].reps[d[k]]; return -1; }

    // value of child c at the raw assignment implied by (n, d, a): scale (product of c's ratios) and class index
    bool child_value(int cn, const NodeD& n, const std::vector<int>& d, int a, Num& out, int depth);

    // row = prod of inputs of n at (d, a); writes each input value into inp[]; returns false on stop
    bool row_inputs(const NodeD& n, const std::vector<int>& d, int a, std::vector<Num*>& inp, int depth) {
        for (size_t i = 0; i < n.inputs.size(); ++i) {
            const InputD& in = n.inputs[i]; Num& dst = *inp[i];
            if (in.kind == 0) {
                const FactorD& f = F[in.ref]; int64_t off = 0;
                for (size_t k = 0; k < f.scope.size(); ++k) off += (int64_t)raw_of(n, d, a, f.scope[k]) * f.stride[k];
                ++C.lookups; copy(dst, fvals[f.val_off + off]);
            } else {
                if (!child_value(in.ref, n, d, a, dst, depth + 1)) return false;
            }
            if (!poll()) return false;
        }
        return true;
    }
    static void copy(Num& dst, const Num& src);

    // forward value of entry idx of node n (recomputed; used for fused nodes and for materialization)
    bool entry_value(int nn, int64_t idx, Num& out, int depth) {
        const NodeD& n = N[nn]; std::vector<int> d; digits(n, idx, d); size_t k = n.inputs.size(); size_t saved = top; size_t base = frame_alloc(k + 1);
        std::vector<Num*> inp(k); for (size_t i = 0; i < k; ++i) inp[i] = &at(base + i);
        Num& row = at(base + k); P::set_zero(out); bool ok = true;
        for (int a = 0; a < n.xc && ok; ++a) {
            if (!row_inputs(n, d, a, inp, depth)) { ok = false; break; }
            P::set_one(row); for (size_t i = 0; i < k; ++i) { P::mul(row, row, *inp[i]); ++C.mults; }
            P::add(out, out, row); ++C.adds; ++C.rows;
        }
        top = saved; return ok;
    }

    int slot_of(int nn, int64_t idx) const { const NodeD& n = N[nn]; if (n.demand.empty()) return (int64_t)idx < (int64_t)values[nn].size() ? (int)idx : -1; auto it = dpos[nn].find(idx); return it == dpos[nn].end() ? -1 : (int)it->second; }

    int forward();
    int reverse();
    bool pullback(int nn, int64_t idx, const Num& h, int depth);
};

template <> void Exec<Dbl>::copy(double& dst, const double& src) { dst = src; }
template <> void Exec<Ival>::copy(Ival::T& dst, const Ival::T& src) { mpfr_set(dst.lo, src.lo, MPFR_RNDD); mpfr_set(dst.hi, src.hi, MPFR_RNDU); }

template <class P> bool Exec<P>::child_value(int cn, const NodeD& n, const std::vector<int>& d, int a, Num& out, int depth) {
    const NodeD& c = N[cn]; int64_t cidx = 0; size_t saved = top; size_t b = frame_alloc(2); Num& sc = at(b); P::set_one(sc);
    for (size_t k = 0; k < c.scope.size(); ++k) { int raw = raw_of(n, d, a, c.scope[k]); const AxisD& ax = c.axes[k]; cidx = cidx * c.radix[k] + ax.cls[raw]; P::mul(sc, sc, ratios[ax.ratio_off + raw]); ++C.mults; }
    bool ok = true;
    if (c.materialize) {
        int s = slot_of(cn, cidx); ++C.lookups;
        if (s < 0) P::set_zero(out);                                          // outside the materialization set (proved zero, or read only by rows with a proved-zero sibling): exact 0 contribution
        else { P::mul(out, sc, values[cn][s]); ++C.mults; }
    } else {
        Num& v = at(b + 1); ++C.fused_reevals;
        if (!entry_value(cn, cidx, v, depth + 1)) ok = false; else { P::mul(out, sc, v); ++C.mults; }
    }
    top = saved; return ok;
}

template <class P> int Exec<P>::forward() {
    values.assign(N.size(), {}); dpos.assign(N.size(), {}); Nx.assign(N.size(), {});
    for (size_t nn = 0; nn < N.size(); ++nn) {
        NodeD& n = N[nn]; Nx[nn].resize(n.xc); for (auto& x : Nx[nn]) P::init(x, prec);
        if (!reserve(used_reverse, caps.reverse, (uint64_t)n.xc * P::bytes(prec))) return stop;
        if (!n.materialize) continue;
        int64_t cnt = n.demand.empty() ? n.core : (int64_t)n.demand.size();
        if (!reserve(used_values, caps.values, (uint64_t)cnt * P::bytes(prec))) return stop;
        if (!n.demand.empty() && !reserve(used_index, caps.index, (uint64_t)cnt * 16)) return stop;
        values[nn].resize(cnt); for (auto& x : values[nn]) P::init(x, prec);
        if (!n.demand.empty()) for (int64_t s = 0; s < cnt; ++s) dpos[nn][n.demand[s]] = s;
        C.entries_demanded += cnt;
        for (int64_t s = 0; s < cnt; ++s) {
            int64_t idx = n.demand.empty() ? s : n.demand[s];
            if (!entry_value((int)nn, idx, values[nn][s], 0)) return stop;
            ++C.entries_materialized;
        }
    }
    // Z = scale * prod roots
    copy(Z, scale);
    for (int r : roots) { if (!N[r].materialize) { size_t saved = top; Num& v = at(frame_alloc(1)); if (!entry_value(r, 0, v, 0)) { top = saved; return stop; } P::mul(Z, Z, v); top = saved; } else P::mul(Z, Z, values[r][0]); ++C.mults; }
    return GB_OK;
}

template <class P> bool Exec<P>::pullback(int nn, int64_t idx, const Num& h, int depth) {
    // drains ONE delta h into entry idx of node nn: N[x][a] += h * row(a); each input i receives h * scale_i * prod_{j != i} inputs
    const NodeD& n = N[nn]; std::vector<int> d; digits(n, idx, d); size_t k = n.inputs.size(); size_t saved = top; size_t base = frame_alloc(3 * k + 5);
    std::vector<Num*> inp(k); for (size_t i = 0; i < k; ++i) inp[i] = &at(base + i);
    std::vector<Num*> pre(k + 1), suf(k + 1); for (size_t i = 0; i <= k; ++i) { pre[i] = &at(base + k + i); suf[i] = &at(base + 2 * k + 1 + i); }
    Num& g = at(base + 3 * k + 2); Num& row = at(base + 3 * k + 3); Num& sc = at(base + 3 * k + 4);
    for (int a = 0; a < n.xc; ++a) {
        if (!row_inputs(n, d, a, inp, depth)) { top = saved; return false; }
        P::set_one(*pre[0]); for (size_t i = 0; i < k; ++i) { P::mul(*pre[i + 1], *pre[i], *inp[i]); ++C.mults; }
        P::set_one(*suf[k]); for (size_t i = k; i >= 1; --i) { P::mul(*suf[i - 1], *inp[i - 1], *suf[i]); ++C.mults; }
        P::mul(row, h, *pre[k]); ++C.mults; P::add(Nx[nn][a], Nx[nn][a], row); ++C.adds; ++C.adj_increments;
        for (size_t i = 0; i < k; ++i) {
            const InputD& in = n.inputs[i]; if (in.kind == 0) continue;
            P::mul(g, *pre[i], *suf[i + 1]); P::mul(g, g, h); C.mults += 2;                                   // adjoint of the child's (scaled) value
            const NodeD& c = N[in.ref]; int64_t cidx = 0; P::set_one(sc);
            for (size_t kk = 0; kk < c.scope.size(); ++kk) { int raw = raw_of(n, d, a, c.scope[kk]); const AxisD& ax = c.axes[kk]; cidx = cidx * c.radix[kk] + ax.cls[raw]; P::mul(sc, sc, ratios[ax.ratio_off + raw]); ++C.mults; }
            P::mul(g, g, sc); ++C.mults;                                                                        // adjoint of the child's CORE entry (scale is the view's exact factor)
            if (c.materialize) { int s = slot_of(in.ref, cidx); if (s >= 0) { P::add(adj[in.ref][s], adj[in.ref][s], g); ++C.adds; ++C.adj_increments; } }
            else { ++C.recomputations; if (!pullback(in.ref, cidx, g, depth + 1)) { top = saved; return false; } }
        }
        if (!poll()) { top = saved; return false; }
    }
    top = saved; return true;
}

template <class P> int Exec<P>::reverse() {
    adj.assign(N.size(), {});
    for (size_t nn = 0; nn < N.size(); ++nn) if (N[nn].materialize) { adj[nn].resize(values[nn].size()); for (auto& x : adj[nn]) P::init(x, prec); if (!reserve(used_reverse, caps.reverse, (uint64_t)values[nn].size() * P::bytes(prec))) return stop; }
    // root adjoints: scale * prod of the OTHER roots (prefix / suffix)
    size_t R = roots.size(); std::vector<Num> rv(R), pre(R + 1), suf(R + 1); for (auto& x : rv) P::init(x, prec); for (auto& x : pre) P::init(x, prec); for (auto& x : suf) P::init(x, prec);
    for (size_t i = 0; i < R; ++i) { if (N[roots[i]].materialize) copy(rv[i], values[roots[i]][0]); else if (!entry_value(roots[i], 0, rv[i], 0)) return stop; }
    P::set_one(pre[0]); for (size_t i = 0; i < R; ++i) P::mul(pre[i + 1], pre[i], rv[i]); P::set_one(suf[R]); for (size_t i = R; i >= 1; --i) P::mul(suf[i - 1], rv[i - 1], suf[i]);
    for (size_t i = 0; i < R; ++i) { size_t saved = top; Num& h = at(frame_alloc(1)); P::mul(h, pre[i], suf[i + 1]); P::mul(h, h, scale); int r = roots[i]; if (N[r].materialize) P::add(adj[r][0], adj[r][0], h); else if (!pullback(r, 0, h, 0)) { top = saved; return stop; } top = saved; }
    for (auto& x : rv) P::clear(x); for (auto& x : pre) P::clear(x); for (auto& x : suf) P::clear(x);
    for (int nn = (int)N.size() - 1; nn >= 0; --nn) {
        if (!N[nn].materialize) continue;
        for (size_t s = 0; s < values[nn].size(); ++s) {
            if (P::is_zero(adj[nn][s])) continue;
            int64_t idx = N[nn].demand.empty() ? (int64_t)s : N[nn].demand[s];
            if (!pullback(nn, idx, adj[nn][s], 0)) return stop; ++C.deltas_drained;
        }
    }
    return GB_OK;
}

// ------------------------------------------------------------------------------------------------------------ C API (type-erased)
struct Handle { int mode; Exec<Ival>* I; Exec<Dbl>* D; };
static void set_from_double(double& dst, double v) { dst = v; }
static void set_from_double(Ival::T& dst, double v) { mpfr_set_d(dst.lo, v, MPFR_RNDD); mpfr_set_d(dst.hi, v, MPFR_RNDU); }

static void parse_prog(const int64_t* prog, int64_t plen, std::vector<FactorD>& F, std::vector<NodeD>& N, std::vector<int>& roots) {
    // flat int64 program: [nF] then per factor: arity, scope..., card..., entries, val_off ; [nN] then per node: x, xc, nin, (kind, ref)*nin, nscope, scope..., per axis: nraw, cls[nraw], nreps, reps[nreps], ratio_off ; core, consumer, materialize, ndemand, demand... ; [nroots] roots...
    int64_t p = 0; int64_t nF = prog[p++]; F.resize(nF);
    for (int64_t i = 0; i < nF; ++i) { FactorD& f = F[i]; int ar = (int)prog[p++]; f.scope.resize(ar); f.card.resize(ar); f.stride.resize(ar); for (int k = 0; k < ar; ++k) f.scope[k] = (int)prog[p++]; for (int k = 0; k < ar; ++k) f.card[k] = (int)prog[p++]; f.entries = prog[p++]; f.val_off = prog[p++]; int64_t st = 1; for (int k = ar - 1; k >= 0; --k) { f.stride[k] = st; st *= f.card[k]; } }
    int64_t nN = prog[p++]; N.resize(nN);
    for (int64_t i = 0; i < nN; ++i) { NodeD& n = N[i]; n.x = (int)prog[p++]; n.xc = (int)prog[p++]; int nin = (int)prog[p++]; n.inputs.resize(nin); for (int k = 0; k < nin; ++k) { n.inputs[k].kind = (int)prog[p++]; n.inputs[k].ref = (int)prog[p++]; } int ns = (int)prog[p++]; n.scope.resize(ns); n.axes.resize(ns); n.radix.resize(ns);
        for (int k = 0; k < ns; ++k) n.scope[k] = (int)prog[p++];
        for (int k = 0; k < ns; ++k) { AxisD& ax = n.axes[k]; ax.var = n.scope[k]; ax.nraw = (int)prog[p++]; ax.cls.resize(ax.nraw); for (int r = 0; r < ax.nraw; ++r) ax.cls[r] = (int)prog[p++]; int nr = (int)prog[p++]; ax.reps.resize(nr); for (int r = 0; r < nr; ++r) ax.reps[r] = (int)prog[p++]; ax.ratio_off = prog[p++]; n.radix[k] = nr; }
        n.core = prog[p++]; n.consumer = (int)prog[p++]; n.materialize = prog[p++] != 0; int64_t nd = prog[p++]; n.demand.resize(nd); for (int64_t r = 0; r < nd; ++r) n.demand[r] = prog[p++]; }
    int64_t nr = prog[p++]; roots.resize(nr); for (int64_t i = 0; i < nr; ++i) roots[i] = (int)prog[p++];
    (void)plen;
}

// values: nq rationals as decimal strings "num/den" (factor entries then ratios then scale), converted per policy.
template <class P> static int load_values(Exec<P>& E, const char* const* qs, int64_t nfac_vals, int64_t nratio_vals, const double* dbl_vals) {
    E.fvals.resize(nfac_vals); E.ratios.resize(nratio_vals); mpq_t q; mpq_init(q);
    for (int64_t i = 0; i < nfac_vals + nratio_vals + 1; ++i) {
        typename P::T* dst = i < nfac_vals ? &E.fvals[i] : (i < nfac_vals + nratio_vals ? &E.ratios[i - nfac_vals] : &E.scale);
        P::init(*dst, E.prec);
        if (dbl_vals) { set_from_double(*dst, dbl_vals[i]); } else { if (mpq_set_str(q, qs[i], 10) != 0) { mpq_clear(q); return GB_BADPROG; } mpq_canonicalize(q); P::set_q(*dst, q, E.prec); }
    }
    mpq_clear(q); E.used_values += (uint64_t)(nfac_vals + nratio_vals) * P::bytes(E.prec); return GB_OK;
}

extern "C" {

// remaining_s: seconds from NOW (the kernel's own CLOCK_MONOTONIC) until the deadline -- never an absolute timestamp from another clock
Handle* gb_create(int mode, int prec, const int64_t* prog, int64_t plen, const char* const* qs, const double* dbl_vals, int64_t nfac_vals, int64_t nratio_vals, const uint64_t* caps5, double remaining_s) {
    Handle* h = (Handle*)std::calloc(1, sizeof(Handle)); h->mode = mode; Caps caps{caps5[0], caps5[1], caps5[2], caps5[3], caps5[4]}; double deadline_mono = now_mono() + remaining_s;
    if (mode == 0) { h->I = new Exec<Ival>(prec); parse_prog(prog, plen, h->I->F, h->I->N, h->I->roots); h->I->caps = caps; h->I->deadline = deadline_mono; if (load_values(*h->I, qs, nfac_vals, nratio_vals, nullptr) != GB_OK) { delete h->I; std::free(h); return nullptr; } }
    else { h->D = new Exec<Dbl>(53); parse_prog(prog, plen, h->D->F, h->D->N, h->D->roots); h->D->caps = caps; h->D->deadline = deadline_mono; if (load_values(*h->D, qs, nfac_vals, nratio_vals, dbl_vals) != GB_OK) { delete h->D; std::free(h); return nullptr; } }
    return h;
}
void gb_destroy(Handle* h) { if (!h) return; delete h->I; delete h->D; std::free(h); }
int gb_forward(Handle* h) { return h->mode == 0 ? h->I->forward() : h->D->forward(); }
int gb_reverse(Handle* h) { return h->mode == 0 ? h->I->reverse() : h->D->reverse(); }
void gb_counters(Handle* h, uint64_t* out16) { Counters& C = h->mode == 0 ? h->I->C : h->D->C; uint64_t uv = h->mode == 0 ? h->I->used_values : h->D->used_values, ui = h->mode == 0 ? h->I->used_index : h->D->used_index, ur = h->mode == 0 ? h->I->used_reverse : h->D->used_reverse, us = h->mode == 0 ? h->I->used_scratch : h->D->used_scratch;
    uint64_t v[16] = {C.rows, C.mults, C.adds, C.lookups, C.fused_reevals, C.entries_materialized, C.entries_demanded, C.adj_increments, C.deltas_drained, C.recomputations, C.polls, uv, ui, ur, us, 0}; std::memcpy(out16, v, sizeof(v)); }

// results: MPFR mode -> decimal strings via mpfr_get_str are lossy; we export EXACT dyadic representations: mantissa (hex) and exponent per endpoint.
// For simplicity and exactness we export each endpoint as an mpfr_t -> Python reads via mpfr_get_str in base 16 with full precision (exact).
int gb_num_nodes(Handle* h) { return (int)(h->mode == 0 ? h->I->N.size() : h->D->N.size()); }
int gb_node_xc(Handle* h, int nn) { return h->mode == 0 ? h->I->N[nn].xc : h->D->N[nn].xc; }
// writes Z (lo,hi) then every node's N[x][a] (lo,hi) as hex strings into buf (';' separated). Double mode: Python float.hex() compatible via "%a".
int gb_results_hex(Handle* h, char* buf, int64_t buflen) {
    int64_t p = 0;
    auto put = [&](const char* s) { int64_t n = (int64_t)std::strlen(s); if (p + n + 2 > buflen) return false; std::memcpy(buf + p, s, n); p += n; buf[p++] = ';'; return true; };
    char tmp[2048];
    if (h->mode == 0) {
        auto hex = [&](mpfr_t x) { if (mpfr_zero_p(x)) { std::snprintf(tmp, sizeof tmp, "0"); return; } mpfr_exp_t e; char* s = mpfr_get_str(nullptr, &e, 16, 0, x, MPFR_RNDN); std::snprintf(tmp, sizeof tmp, "%s@%ld", s, (long)e); mpfr_free_str(s); };
        hex(h->I->Z.lo); if (!put(tmp)) return -1; hex(h->I->Z.hi); if (!put(tmp)) return -1;
        for (size_t nn = 0; nn < h->I->N.size(); ++nn) for (int a = 0; a < h->I->N[nn].xc; ++a) { hex(h->I->Nx[nn][a].lo); if (!put(tmp)) return -1; hex(h->I->Nx[nn][a].hi); if (!put(tmp)) return -1; }
    } else {
        std::snprintf(tmp, sizeof tmp, "%a", h->D->Z); if (!put(tmp)) return -1; if (!put(tmp)) return -1;
        for (size_t nn = 0; nn < h->D->N.size(); ++nn) for (int a = 0; a < h->D->N[nn].xc; ++a) { std::snprintf(tmp, sizeof tmp, "%a", h->D->Nx[nn][a]); if (!put(tmp)) return -1; if (!put(tmp)) return -1; }
    }
    buf[p] = 0; return (int)p;
}

// qualification hook: inject the root adjoint as two separate deltas w1 then w2 (decimal rationals) with optional eviction of every materialized
// non-root value between them (forcing recomputation), instead of one coalesced root adjoint. Requires forward() done; replaces reverse().
int gb_test_split_root(Handle* h, const char* w1, const char* w2, int evict) {
    if (h->mode != 0 || h->I->roots.size() != 1) return GB_BADPROG;
    Exec<Ival>& E = *h->I; int r = E.roots[0]; E.adj.assign(E.N.size(), {});
    for (size_t nn = 0; nn < E.N.size(); ++nn) if (E.N[nn].materialize) { E.adj[nn].resize(E.values[nn].size()); for (auto& x : E.adj[nn]) Ival::init(x, E.prec); }
    mpq_t q; mpq_init(q); Ival::T hw; Ival::init(hw, E.prec); E.top = 0;
    for (int pass = 0; pass < 2; ++pass) {
        mpq_set_str(q, pass == 0 ? w1 : w2, 10); mpq_canonicalize(q); Ival::set_q(hw, q, E.prec); Ival::mul(hw, hw, E.scale);
        if (!E.pullback(r, 0, hw, 0)) { mpq_clear(q); Ival::clear(hw); return E.stop; } ++E.C.deltas_drained;
        for (int nn = (int)E.N.size() - 1; nn >= 0; --nn) { if (!E.N[nn].materialize || nn == r) continue; for (size_t s = 0; s < E.values[nn].size(); ++s) { if (Ival::is_zero(E.adj[nn][s])) continue; int64_t idx = E.N[nn].demand.empty() ? (int64_t)s : E.N[nn].demand[s]; if (!E.pullback(nn, idx, E.adj[nn][s], 0)) { mpq_clear(q); Ival::clear(hw); return E.stop; } Ival::set_zero(E.adj[nn][s]); ++E.C.deltas_drained; } }
        if (pass == 0 && evict) {                                            // evict every materialized non-root value and recompute it (values are pure; numerators untouched)
            for (size_t nn = 0; nn < E.N.size(); ++nn) { if (!E.N[nn].materialize || (int)nn == r) continue; for (size_t s = 0; s < E.values[nn].size(); ++s) { int64_t idx = E.N[nn].demand.empty() ? (int64_t)s : E.N[nn].demand[s]; Ival::set_zero(E.values[nn][s]); if (!E.entry_value((int)nn, idx, E.values[nn][s], 0)) { mpq_clear(q); Ival::clear(hw); return E.stop; } ++E.C.recomputations; } }
        }
    }
    mpq_clear(q); Ival::clear(hw); return GB_OK;
}

// ------------------------------------------------------------------------------------------------------------ exact integer reference stream (GB-07)
// Enumerates every assignment of the reduced variables, multiplies every factor occurrence (integer tables after per-factor denominator clearing),
// accumulates Z and every N[x][a] in mpz; the common scale cancels in N/Z. Polls the deadline; returns GB_DEADLINE with the visited count.
struct Mz { mpz_t z; };
struct RefState { int nv; std::vector<int> card; std::vector<FactorD> F; std::vector<Mz> tabs; mpz_t Z; std::vector<std::vector<Mz>> Nx; uint64_t visited; uint64_t total; double deadline; };
RefState* gb_ref_create(const int64_t* prog, int64_t plen, const char* const* int_vals, double remaining_s) { double deadline = now_mono() + remaining_s;
    RefState* S = new RefState(); int64_t p = 0; S->nv = (int)prog[p++]; S->card.resize(S->nv); for (int i = 0; i < S->nv; ++i) S->card[i] = (int)prog[p++];
    int64_t nF = prog[p++]; S->F.resize(nF); int64_t tot = 0;
    for (int64_t i = 0; i < nF; ++i) { FactorD& f = S->F[i]; int ar = (int)prog[p++]; f.scope.resize(ar); f.card.resize(ar); f.stride.resize(ar); for (int k = 0; k < ar; ++k) f.scope[k] = (int)prog[p++]; for (int k = 0; k < ar; ++k) f.card[k] = (int)prog[p++]; f.entries = prog[p++]; f.val_off = tot; tot += f.entries; int64_t st = 1; for (int k = ar - 1; k >= 0; --k) { f.stride[k] = st; st *= f.card[k]; } }
    S->tabs.resize(tot); for (int64_t i = 0; i < tot; ++i) { mpz_init(S->tabs[i].z); mpz_set_str(S->tabs[i].z, int_vals[i], 10); }
    mpz_init_set_ui(S->Z, 0); S->Nx.resize(S->nv); for (int v = 0; v < S->nv; ++v) { S->Nx[v].resize(S->card[v]); for (auto& z : S->Nx[v]) mpz_init_set_ui(z.z, 0); }
    S->visited = 0; S->total = 1; for (int v = 0; v < S->nv; ++v) S->total *= (uint64_t)S->card[v]; S->deadline = deadline; (void)plen; return S;
}
int gb_ref_run(RefState* S) {
    std::vector<int> x(S->nv, 0); mpz_t w; mpz_init(w); uint64_t polls = 0;
    for (uint64_t it = S->visited; it < S->total; ++it) {
        uint64_t r = it; for (int v = S->nv - 1; v >= 0; --v) { x[v] = (int)(r % S->card[v]); r /= S->card[v]; }
        mpz_set_ui(w, 1); bool zero = false;
        for (const FactorD& f : S->F) { int64_t off = 0; for (size_t k = 0; k < f.scope.size(); ++k) off += (int64_t)x[f.scope[k]] * f.stride[k]; const Mz& e = S->tabs[f.val_off + off]; if (mpz_sgn(e.z) == 0) { zero = true; break; } mpz_mul(w, w, e.z); }
        if (!zero) { mpz_add(S->Z, S->Z, w); for (int v = 0; v < S->nv; ++v) mpz_add(S->Nx[v][x[v]].z, S->Nx[v][x[v]].z, w); }
        S->visited = it + 1;
        if (++polls >= 4096) { polls = 0; if (now_mono() > S->deadline) { mpz_clear(w); return GB_DEADLINE; } }
    }
    mpz_clear(w); return GB_OK;
}
uint64_t gb_ref_visited(RefState* S) { return S->visited; }
int gb_ref_results(RefState* S, char* buf, int64_t buflen) {
    int64_t p = 0; auto put = [&](mpz_ptr z) { char* s = mpz_get_str(nullptr, 10, z); int64_t n = (int64_t)std::strlen(s); if (p + n + 2 > buflen) { std::free(s); return false; } std::memcpy(buf + p, s, n); p += n; buf[p++] = ';'; std::free(s); return true; };
    if (!put(S->Z)) return -1; for (int v = 0; v < S->nv; ++v) for (int a = 0; a < S->card[v]; ++a) if (!put(S->Nx[v][a].z)) return -1; buf[p] = 0; return (int)p;
}
void gb_ref_destroy(RefState* S) { if (!S) return; for (auto& z : S->tabs) mpz_clear(z.z); mpz_clear(S->Z); for (auto& v : S->Nx) for (auto& z : v) mpz_clear(z.z); delete S; }

const char* gb_mpfr_version() { return mpfr_get_version(); }
const char* gb_gmp_version() { return gmp_version; }
long gb_mpfr_emin() { return (long)mpfr_get_emin(); }
long gb_mpfr_emax() { return (long)mpfr_get_emax(); }

} // extern "C"
