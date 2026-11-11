// cex_control_driver.cpp -- standalone allocation-instrumented / sanitizer control driver for the kernel (certified executor pass, repair of 11 Nov 2026).
// Includes the kernel source UNCHANGED and overrides the global operator new/delete to count the simultaneous REQUESTED bytes of every heap allocation made
// while cex_run executes (caller-owned plan / output arrays are allocated before tracking). The kernel's own `peak_logical_bytes` must equal this count
// exactly (one allocation boundary), a cap below the footprint must be refused BEFORE allocation (typed MEMORY, nothing live at return), an expired deadline
// must be a typed DEADLINE at entry, and a plan whose mixed-radix volume exceeds 2^62 must be a typed REPRESENTATION refusal (never ZERO_EVIDENCE).
// Built twice by the qualification: strict flags; strict flags + UBSan (-fsanitize=undefined -fno-sanitize-recover=undefined).
//   cex_control_driver <unaries CAP | isolated DEADLINE | growth | star N C | sparse CAP>     -> one JSON line
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <new>
#include <cstddef>
#include <cstdint>
#include <vector>
#include <limits>
#include <string>
struct alignas(std::max_align_t) AuditHeader { size_t bytes; bool tracked; };
static bool audit_on = false;
static size_t audit_live = 0, audit_peak = 0, audit_count = 0;
void* operator new(std::size_t n) {
    auto* h = static_cast<AuditHeader*>(std::malloc(sizeof(AuditHeader) + n));
    if (!h) throw std::bad_alloc();
    h->bytes = n; h->tracked = audit_on;
    if (audit_on) { audit_live += n; ++audit_count; if (audit_live > audit_peak) audit_peak = audit_live; }
    return h + 1;
}
void operator delete(void* p) noexcept {
    if (!p) return;
    auto* h = static_cast<AuditHeader*>(p)-1;
    if (h->tracked) audit_live -= h->bytes;
    std::free(h);
}
void* operator new[](std::size_t n) { return ::operator new(n); }
void operator delete[](void* p) noexcept { ::operator delete(p); }
void operator delete(void* p, std::size_t) noexcept { ::operator delete(p); }
void operator delete[](void* p, std::size_t) noexcept { ::operator delete(p); }
#include KERNEL_PATH

static void run_plan(const char* kind, std::vector<int64_t>& plan, std::vector<double>& vals, int n, int64_t tot, int64_t cap, double deadline) {
    std::vector<double> out(tot); std::vector<int64_t> exp(n), lab(n);
    double z = 0; int64_t zm[2]{}; uint64_t counters[22]{}; char reason[256]{};
    audit_on = true;
    int rc = cex_run(plan.data(), plan.size(), vals.data(), vals.size(), cap, deadline, .25, out.data(), exp.data(), lab.data(), &z, zm, counters, 22, reason, 256);
    audit_on = false;
    std::printf("{\"kind\":\"%s\",\"n\":%d,\"return_code\":%d,\"stop\":\"%s\",\"reason\":\"%s\",\"cap_bytes\":%lld,\"reported_peak_logical_bytes\":%llu,\"reported_live_at_exit\":%llu,\"tracked_native_peak_requested_bytes\":%zu,\"tracked_native_live_at_return\":%zu,\"tracked_allocations\":%zu,\"reported_allocations\":%llu,\"polls\":%llu,\"forward_rows\":%llu,\"Z\":%.17g,\"N0\":%.17g,\"peak_matches\":%s,\"nothing_live\":%s}\n",
        kind, n, rc, rc == 0 ? "OK" : rc == 1 ? "DEADLINE" : rc == 2 ? "MEMORY" : rc == 3 ? "RANGE" : rc == 4 ? "BADPLAN" : rc == 5 ? "FPENV" : rc == 6 ? "FAULT" : rc == 7 ? "ZERO_EVIDENCE" : rc == 8 ? "REPRESENTATION" : "?", reason, (long long)cap,
        (unsigned long long)counters[17], (unsigned long long)counters[18], audit_peak, audit_live, audit_count, (unsigned long long)counters[21], (unsigned long long)counters[10], (unsigned long long)counters[0], z, out[0],
        (audit_peak == counters[17]) ? "true" : "false", (audit_live == 0 && counters[18] == 0) ? "true" : "false");
}

int main(int argc, char** argv) {
    if (argc < 2) return 2;
    std::string mode = argv[1];
    if (mode == "growth") {             // the transient-overlap control: a growing charged vector must charge the new block while the old one is live
        Ledger L; L.cap = 16000; g_ledger = &L; vec<double> v; bool first = true, second = true; const char* why = "";
        audit_on = true;
        try { v.reserve(1000); } catch (CapExceeded&) { first = false; }
        try { v.reserve(2000); } catch (CapExceeded&) { second = false; why = "second reservation refused: 8000 live + 16000 requested > 16000 cap (transient overlap charged)"; }
        audit_on = false; vec<double>().swap(v); g_ledger = nullptr;
        std::printf("{\"kind\":\"charged_vector_growth_transient_overlap\",\"first_allowed\":%s,\"second_allowed\":%s,\"cap_bytes\":16000,\"reported_peak_logical_bytes\":%lld,\"tracked_native_peak_requested_bytes\":%zu,\"refused_request\":%lld,\"note\":\"%s\"}\n", first ? "true" : "false", second ? "true" : "false", (long long)L.peak, audit_peak, (long long)L.refused_request, why);
        return 0;
    }
    if (mode == "rescale_boundary") {   // the local scaling invariant: an entry whose exact power-of-two scaling is NOT exact (rounds up to DBL_MIN) must be a RANGE stop; an exactly scalable tiny entry passes
        Ledger L; L.cap = 1 << 20; g_ledger = &L; Exec E; E.cap_bytes = L.cap; E.deadline = std::numeric_limits<double>::infinity();
        Rel a; a.vals.push_back(4.0); a.vals.push_back(0x1.fffffffffffffp-1021); bool oka = E.rescale(a, 0, "message"); int sa = E.stop; char ra[200]; std::strncpy(ra, E.reason, 200); E.stop = OK; E.reason[0] = 0;
        Rel b; b.vals.push_back(4.0); b.vals.push_back(std::ldexp(1.0, -1000)); bool okb = E.rescale(b, 1, "message"); int sb = E.stop; bool exact_b = okb && b.vals[0] == 1.0 && b.vals[1] == std::ldexp(1.0, -1002) && b.exp2 == 2;
        g_ledger = nullptr;
        std::printf("{\"kind\":\"rescale_boundary\",\"inexact_case_refused\":%s,\"inexact_case_stop\":%d,\"inexact_reason\":\"%s\",\"exact_case_ok\":%s,\"exact_case_stop\":%d,\"exact_case_values_and_exponent_correct\":%s}\n", (!oka && sa == RANGE) ? "true" : "false", sa, ra, okb ? "true" : "false", sb, exact_b ? "true" : "false");
        return 0;
    }
    if (mode == "unaries" || mode == "isolated") {
        bool isolated = mode == "isolated"; int n = isolated ? 10000 : 1000; int64_t cap = std::atoll(argv[2]); double deadline = isolated ? std::atof(argc > 3 ? argv[3] : "0") : std::numeric_limits<double>::infinity();
        std::vector<int64_t> plan{2, n};
        for (int i = 0; i < n; ++i) plan.push_back(isolated ? 1 : 2);
        plan.push_back(n); for (int i = 0; i < n; ++i) plan.push_back(i);
        plan.push_back(isolated ? 0 : n);
        std::vector<double> vals;
        if (!isolated) for (int i = 0; i < n; ++i) { for (int64_t w : {int64_t(1), int64_t(i), int64_t(0), int64_t(2), int64_t(0), int64_t(-1)}) plan.push_back(w); vals.push_back(1.0); vals.push_back(1.0); }   // [1/2,1/2] pre-scaled by 2^1: stored [1,1], exp2 -1
        run_plan(isolated ? "isolated_cardinality_one" : "binary_uniform_unaries", plan, vals, n, isolated ? n : 2 * n, cap, deadline); return 0;
    }
    if (mode == "star") {               // n variables of cardinality c, star of all-one pair factors, centre first: bag volume c^n
        int n = std::atoi(argv[2]); int c = std::atoi(argv[3]);
        std::vector<int64_t> plan{2, n}; for (int i = 0; i < n; ++i) plan.push_back(c); plan.push_back(n); for (int i = 0; i < n; ++i) plan.push_back(i); plan.push_back(n - 1);
        std::vector<double> vals;
        for (int i = 1; i < n; ++i) { plan.push_back(2); plan.push_back(0); plan.push_back(i); plan.push_back(0); plan.push_back((int64_t)c * c); plan.push_back(0); plan.push_back(0); for (int t = 0; t < c * c; ++t) vals.push_back(1.0); }
        run_plan("star_all_ones", plan, vals, n, (int64_t)n * c, 100000000, std::numeric_limits<double>::infinity()); return 0;
    }
    if (mode == "sparse") {             // a sparse-join plan: 12 binary variables, 11 sparse pair factors on a chain (one zero per factor), eliminate ends first
        int n = 12; int64_t cap = std::atoll(argv[2]);
        std::vector<int64_t> plan{2, n}; for (int i = 0; i < n; ++i) plan.push_back(2); plan.push_back(n); for (int i = 0; i < n; ++i) plan.push_back(i); plan.push_back(n - 1);
        std::vector<double> vals;
        for (int i = 0; i + 1 < n; ++i) { plan.push_back(2); plan.push_back(i); plan.push_back(i + 1); plan.push_back(1); plan.push_back(3); plan.push_back(0); plan.push_back(1); plan.push_back(3); plan.push_back(0); plan.push_back(0); vals.push_back(1.0); vals.push_back(1.5); vals.push_back(1.25); }
        run_plan("sparse_chain_join", plan, vals, n, 2 * n, cap, std::numeric_limits<double>::infinity()); return 0;
    }
    return 2;
}
