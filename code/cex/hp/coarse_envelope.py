"""Hinton-to-Pearl compiler v0.1 (23 Nov 2026 brief CLAUDE_TEST_PROMPT.md): a GENERIC WEIGHTED COARSE-ENVELOPE compiler, standalone research module.
Untrusted proposers (exact projective profiles, farthest-profile partitions, log-slice centering, one bounded local LP fit) -> an independent source-bound CHECKER
(exact rational unary masses A, cell extrema L / U recomputed from the ORIGINAL entries, product decoder, exact local ratio R) -> the EXISTING certified native executor
(cex/newarm/cex_executor.py primitives, unchanged) on the lower (and optionally upper) coarse model under one deterministic order -> original singleton coordinates
by the one-lower-solve finite-R bound, tightened by the two-envelope ratio when the upper model is admitted; intersections of validated intervals retained across
witnesses (<= 3 partition / gauge witnesses per run). Nothing published without a positive original-mass witness (Z_L > 0). The accepted v2.13.2 dispatch and the
kernel are untouched: this module is only ever run as its own arm.

Semantics: a canonical nonnegative rational model w(x) = s prod_v psi_v(x_v) prod_f f(x_{S_f}); repeated occurrences restricted to the equality diagonal; unary factors,
evidence (as indicators -> fixed variables restricted out) and card-1 variables absorbed; factorless variables collapse to their unary mass (EXACT rows) and a scalar.
Candidate = nonempty state classes + strictly positive rational incidence scales; u_v(a) = psi_v(a) prod_f lambda_fv(a); A_v(c) = sum_{a in c} u_v(a); h_f = f / prod lambda;
L_f(C) / U_f(C) = exact min / max of h_f over the cell; decoder d_v(a|c) = u_v(a) / A_v(c) (normalized uniform on a zero-mass class, no division). Sandwich: w_L <= w <= w_U
pointwise. Local certificate: if every cell is all-zero or all-positive, R = prod_f max_C U/L and w_L <= w <= R w_L; one lower solve gives, for a normalized feature g with
lower-model expectation mu, E_p g in [mu / (mu + R (1 - mu)), R mu / (R mu + 1 - mu)]. Resource contract: 4,096-bit cap on constructed rationals (operand bounds checked
before products), 128 MiB named-container constructor budget (an ESTIMATE, not an RSS bound), polls inside every scan / profile / refinement / graph / decoder / publication
loop, final guard before success, the executor's own kernel cap and deadline. Everything numerical (logs, profiles, LP) is a PROPOSAL; every published number is rebuilt exactly."""
import sys, os, json, time, math, argparse, hashlib, subprocess, threading, queue, resource, itertools
from fractions import Fraction as F
T_PROCESS_START = time.monotonic()
HERE = os.path.dirname(os.path.abspath(__file__)); CODE = os.path.dirname(os.path.dirname(HERE))
for p in (os.path.join(CODE, 'cex', 'newarm'),):
    if p not in sys.path: sys.path.insert(0, p)
import cex_executor as CX
import ctypes as C

VERSION = 'hp-coarse-envelope-v0.2 (2026-11-24 closeout: epsilon-safe points (J-box normalization / midpoints, endpoint radius <= eps verified); total typed refusal with the query inventory fixed before canonicalization; hard-deadline guards at entry, in canonicalization, factorless and final assembly, before success and before the output commit; bounded log of rationals + typed numeric-proposal refusals; exact profiles, approximate profiles, primal graph (vertices / source cliques / fills) and the LP payload charged before construction with polls inside; checked division / growth in the checker, decoder and query recovery; v0.1 2026-11-23 pilot 1)'
U = F(1, 2 ** 53)
BIT_CAP = 4096                       # newly constructed rational numerators / denominators (pilot policy)
CONSTRUCTOR_BYTES = 128 << 20        # admitted constructor workspace (named-container estimate)
USABLE_BYTES = 2560 << 20            # the executor's usable policy (accepted engine)
ROWS_PER_S_CONSERVATIVE = 20e6       # the accepted layered route's conservative kernel rate (admission only)
MAX_WITNESSES = 3
FIT_ALLOWANCE_S = 1.0                # FIT's local proposal incl. worker setup + rationalization
ADMISSION_STOP_S = 3.5               # internal: no new work admitted after this (4.0 s supervisor ceiling)
RATIONALIZE_DEN = 1 << 16
FRAC_BYTES = 128                     # Fraction object estimate (+32 B per 64-bit limb)
GRAPH_ENTRY_BYTES = 128              # one directed adjacency entry of the primal graph (set slot + int), as in the accepted ancestral constructor's physical-graph admission


class Refused(Exception):
    def __init__(self, kind, reason, stats=None): super().__init__(kind, reason); self.kind = kind; self.reason = reason; self.stats = stats or {}
class Defect(Exception): pass


def tnow(): return time.monotonic()
def bits(q): return q.numerator.bit_length() + q.denominator.bit_length()
def frac_bytes(q): return FRAC_BYTES + 32 * ((bits(q) + 63) // 64)
def checked_mul(a, b):
    if a.numerator.bit_length() + b.numerator.bit_length() > BIT_CAP or a.denominator.bit_length() + b.denominator.bit_length() > BIT_CAP: raise Refused('BITS', 'rational product would exceed %d bits' % BIT_CAP)
    return a * b
def checked_add(a, b):
    m = max(a.denominator.bit_length(), b.denominator.bit_length()); n = max(a.numerator.bit_length(), b.numerator.bit_length())
    if n + m + 2 > BIT_CAP or a.denominator.bit_length() + b.denominator.bit_length() > BIT_CAP: raise Refused('BITS', 'rational sum would exceed %d bits' % BIT_CAP)
    return a + b
def checked_div(a, b):
    if b <= 0: raise Defect('division by a nonpositive value')
    if a.numerator.bit_length() + b.denominator.bit_length() > BIT_CAP or a.denominator.bit_length() + b.numerator.bit_length() > BIT_CAP: raise Refused('BITS', 'rational quotient would exceed %d bits' % BIT_CAP)
    return a / b
def csum(xs):
    t = F(0)
    for x in xs: t = checked_add(t, x)
    return t
def flog(q):
    """bounded natural log of a positive rational WITHOUT converting the value to a float (math.log on the big integers; no underflow / overflow for admitted bit sizes)"""
    if q <= 0: raise ValueError('log of a nonpositive value')
    return math.log(q.numerator) - math.log(q.denominator)
class ProposalRefused(Exception): pass    # a numeric proposal (profiles / centering / rationalization) could not be formed: typed, the admitted prior candidate is retained
def strides(cs):
    st = [1] * len(cs)
    for i in range(len(cs) - 2, -1, -1): st[i] = st[i + 1] * cs[i + 1]
    return st


class Budget:
    """charge-before-build accounting of the constructor's named containers (estimate calibrated by sys.getsizeof; NOT an RSS bound); typed MEMORY refusal"""
    def __init__(self, cap): self.cap = cap; self.live = 0; self.peak = 0; self.cumulative = 0
    def charge(self, n, what):
        n = int(n)
        if self.live + n > self.cap: raise Refused('MEMORY', 'constructor budget: %d live + %d for %s > %d' % (self.live, n, what, self.cap))
        self.live += n; self.cumulative += n; self.peak = max(self.peak, self.live); return n
    def release(self, n): self.live = max(0, self.live - int(n))


class Clock:
    def __init__(self, deadline, stats): self.deadline = deadline; self.stats = stats; self.polls = 0
    def poll(self, where):
        self.polls += 1
        if tnow() >= self.deadline: raise Refused('DEADLINE', 'deadline expired ' + where)
    def remaining(self): return self.deadline - tnow()


# ------------------------------------------------------------------ canonical model
class Canon:
    """cards / psi / factors (scope len >= 2, distinct variables, row-major values) / scalar over the RETAINED variables; `orig_of[j]` = original id; `fixed_rows` = EXACT rows of
    removed query variables (card-1 and factorless) keyed by original (var, state); observed variables are restricted out (not queries). zero_mass_certified when a scalar is 0."""
    def __init__(self): self.cards = []; self.psi = []; self.factors = []; self.scalar = F(1); self.orig_of = []; self.fixed_rows = {}; self.zero_mass = False; self.notes = []


def canonicalize(model, clock, budget):
    """model = dict(cards, factors=[dict(scope, values)], evidence) with exact Fractions; returns Canon. Repeated occurrences -> equality diagonal; unaries absorbed; evidence /
    card-1 variables restricted out; factorless variables collapse to scalar + EXACT rows. Nothing here uses floats."""
    clock.poll('at the canonicalization entry'); cards = list(model['cards']); n = len(cards); ev = dict(model.get('evidence', {})); psi = [[F(1)] * c for c in cards]; scalar = F(1); facs = []
    budget.charge(sum(56 + 8 * c + c * FRAC_BYTES for c in cards), 'unary weights')
    for f in model['factors']:
        sc = list(f['scope']); vals = f['values']
        if len(vals) != math.prod(cards[v] for v in sc): raise ValueError('factor shape mismatch')
        uniq = []
        for v in sc:
            if v not in uniq: uniq.append(v)
        if len(uniq) != len(sc):                                   # equality diagonal of repeated occurrences
            st = strides([cards[v] for v in sc]); new = []
            for a in itertools.product(*(range(cards[v]) for v in uniq)):
                pos = {v: x for v, x in zip(uniq, a)}; new.append(F(vals[sum(st[i] * pos[v] for i, v in enumerate(sc))])); clock.poll('in the diagonal restriction')
            sc, vals = uniq, new
        vals = [x if isinstance(x, F) else F(x) for x in vals]
        if any(x < 0 for x in vals): raise ValueError('negative factor entry')
        if not sc: scalar = checked_mul(scalar, vals[0])
        elif len(sc) == 1:
            for a in range(cards[sc[0]]): psi[sc[0]][a] = checked_mul(psi[sc[0]][a], vals[a])
        else: facs.append((tuple(sc), vals))
        clock.poll('after a factor')
    for v, a in ev.items(): psi[v] = [psi[v][b] if b == a else F(0) for b in range(cards[v])]
    # restrict out observed and card-1 variables (their psi at the fixed state is a scalar; factors lose the axis)
    fixed = {v: ev[v] for v in ev}
    for v in range(n):
        if v not in fixed and cards[v] == 1: fixed[v] = 0
    out = []
    for sc, vals in facs:
        keep = [i for i, v in enumerate(sc) if v not in fixed]
        if len(keep) == len(sc): out.append((sc, vals)); continue
        budget.charge(56 + (8 + FRAC_BYTES) * math.prod(cards[sc[i]] for i in keep), 'restricted factor'); cs = [cards[v] for v in sc]; st = strides(cs); new = []
        for a in itertools.product(*(range(cs[i]) for i in keep)):
            idx = 0; j = 0
            for i, v in enumerate(sc):
                if v in fixed: idx += st[i] * fixed[v]
                else: idx += st[i] * a[j]; j += 1
            new.append(vals[idx]); clock.poll('in the evidence restriction')
        nsc = tuple(sc[i] for i in keep)
        if not nsc: scalar = checked_mul(scalar, new[0])
        elif len(nsc) == 1:
            for a in range(cards[nsc[0]]): psi[nsc[0]][a] = checked_mul(psi[nsc[0]][a], new[a])
        else: out.append((nsc, new))
    for j, (v, a) in enumerate(fixed.items()):
        scalar = checked_mul(scalar, psi[v][a])
        if (j & 255) == 255: clock.poll('in the fixed-variable scalars')
    C_ = Canon(); incident = {v: 0 for v in range(n)}
    for sc, _ in out:
        for v in sc: incident[v] += 1
    ren = {}
    for v in range(n):
        if v in fixed:
            if v not in ev: C_.fixed_rows[(v, 0)] = (F(1), 'EXACT')         # card-1 unobserved: exactly 1 (when Z > 0)
            continue
        if incident[v] == 0:                                               # factorless: collapse to unary mass + exact rows (polled: a large factorless domain is real work)
            tot = csum(psi[v]); scalar = checked_mul(scalar, tot)
            for a in range(cards[v]):
                C_.fixed_rows[(v, a)] = (checked_div(psi[v][a], tot) if tot > 0 else None, 'EXACT')
                if (a & 255) == 255: clock.poll('in the factorless rows')
            continue
        if (v & 255) == 255: clock.poll('in the variable retention scan')
        ren[v] = len(C_.cards); C_.cards.append(cards[v]); C_.psi.append(psi[v]); C_.orig_of.append(v)
    C_.factors = [(tuple(ren[v] for v in sc), vals) for sc, vals in out]; C_.scalar = scalar; C_.zero_mass = (scalar == 0); C_.ev = ev; C_.n_orig = n; C_.cards_orig = cards
    return C_


# ------------------------------------------------------------------ checker: coarse envelopes from a candidate
class Coarse:
    __slots__ = ('classes', 'ccards', 'reps', 'u', 'A', 'd', 'L', 'U', 'scales', 'exact', 'R', 'Rf', 'mixed', 'gaps', 'zero_factor', 'all_positive')


def check_candidate(M, classes, scales, clock, budget):
    """classes[v][a] in 0..k_v-1 (nonempty, canonical: class ids in order of first appearance), scales[(fi, axis)][a] > 0 exact. Recomputes EVERYTHING from the source entries."""
    n = len(M.cards); Cz = Coarse(); Cz.classes = classes; Cz.scales = scales
    for v in range(n):
        k = max(classes[v]) + 1
        if sorted(set(classes[v])) != list(range(k)) or len(classes[v]) != M.cards[v]: raise Defect('invalid partition of variable %d' % v)
    Cz.ccards = [max(cl) + 1 for cl in classes]; Cz.reps = [[cl.index(c) for c in range(k)] for cl, k in zip(classes, Cz.ccards)]
    budget.charge(sum((8 + FRAC_BYTES) * (c + k) for c, k in zip(M.cards, Cz.ccards)), 'u / A / decoder')
    u = [list(p) for p in M.psi]
    for fi, (sc, _) in enumerate(M.factors):
        for ax, v in enumerate(sc):
            lam = scales[(fi, ax)]
            if len(lam) != M.cards[v] or any((not isinstance(x, F)) or x <= 0 for x in lam): raise Defect('invalid scale on factor %d axis %d' % (fi, ax))
            for a in range(M.cards[v]): u[v][a] = checked_mul(u[v][a], lam[a])
        clock.poll('in the scale products')
    A = [[F(0)] * k for k in Cz.ccards]
    for v in range(n):
        for a in range(M.cards[v]): A[v][classes[v][a]] = checked_add(A[v][classes[v][a]], u[v][a])
    d = [[checked_div(u[v][a], A[v][classes[v][a]]) if A[v][classes[v][a]] > 0 else F(1, classes[v].count(classes[v][a])) for a in range(M.cards[v])] for v in range(n)]
    Cz.u = u; Cz.A = A; Cz.d = d; Cz.L = []; Cz.U = []; Cz.Rf = []; Cz.mixed = False; Cz.gaps = []; Cz.zero_factor = False; Cz.exact = True; Cz.all_positive = True
    for fi, (sc, vals) in enumerate(M.factors):
        ccs = [Cz.ccards[v] for v in sc]; vol = math.prod(ccs); budget.charge(2 * (56 + (8 + FRAC_BYTES) * vol) + 64 * vol, 'L / U tables + cell bookkeeping of factor %d' % fi)
        L = [None] * vol; Ucell = [None] * vol; cst = strides(ccs); fst = strides([M.cards[v] for v in sc]); lams = [scales[(fi, ax)] for ax in range(len(sc))]
        for idx, x in enumerate(itertools.product(*(range(M.cards[v]) for v in sc))):
            h = vals[idx]
            if h > 0:
                for ax, a in enumerate(x): h = checked_div(h, lams[ax][a])    # exact residual; growth admitted before the division
            else: Cz.all_positive = False
            c = sum(cst[ax] * classes[v][a] for ax, (v, a) in enumerate(zip(sc, x)))
            if L[c] is None or h < L[c]: L[c] = h
            if Ucell[c] is None or h > Ucell[c]: Ucell[c] = h
            if (idx & 255) == 255: clock.poll('in the cell scan of factor %d' % fi)
        Rf = F(1); g = []
        for c in range(vol):
            lo, hi = L[c], Ucell[c]
            if lo != hi: Cz.exact = False
            if hi == 0: g.append(F(0))
            else:
                g.append((hi - lo) / (hi + lo))
                if lo == 0: Cz.mixed = True
                elif hi / lo > Rf: Rf = hi / lo
        if all(x == 0 for x in Ucell): Cz.zero_factor = True
        Cz.L.append(L); Cz.U.append(Ucell); Cz.Rf.append(None if Cz.mixed else Rf); Cz.gaps.append(g)
    Cz.R = None
    if not Cz.mixed:
        R = F(1)
        for r in Cz.Rf: R = checked_mul(R, r)
        Cz.R = R
    return Cz


def coarse_model(M, Cz, side):
    """the coarse model handed to the executor: unary masses A_v + the L (side 0) or U (side 1) tables; evidence none; scalar tracked separately"""
    tabs = Cz.L if side == 0 else Cz.U
    return dict(cards=list(Cz.ccards), evidence={}, factors=[dict(scope=(v,), values=list(Cz.A[v])) for v in range(len(M.cards))] + [dict(scope=sc, values=list(tabs[fi])) for fi, (sc, _) in enumerate(M.factors)])


# ------------------------------------------------------------------ order + executor adapter (the EXISTING certified executor's primitives, unchanged)
def elimination_order(cards, scopes, clock, budget=None):
    """deterministic greedy min-product order on the primal graph (ties: smallest id); returns (order, per-step bucket volumes). The graph is admitted BEFORE it is built: vertex sets, each
    source clique (k(k-1) directed entries) and each elimination fill (m(m-1) entries) are charged before allocation, with the deadline polled at entry, per 64 source cliques, per 64
    candidates of every scan and per elimination; the charge is released when the graph dies."""
    clock.poll('at the order construction entry'); B = budget or Budget(1 << 62); n = len(cards); charged = B.charge(n * (216 + 8) + 56, 'primal graph vertex sets'); adj = [set() for _ in range(n)]
    for i, sc in enumerate(scopes):
        k = len(sc); charged += B.charge(k * (k - 1) * GRAPH_ENTRY_BYTES, 'source clique %d (%d directed entries)' % (i, k * (k - 1)))
        for v in sc: adj[v].update(set(sc) - {v})
        if (i & 63) == 63: clock.poll('in the source cliques')
    alive = set(range(n)); order = []; vols = []
    while alive:
        best = None
        for j, v in enumerate(sorted(alive)):
            p = cards[v] * math.prod(cards[w] for w in adj[v])
            if best is None or p < best[0]: best = (p, v)
            if (j & 63) == 63: clock.poll('in the candidate scan')
        p, v = best; order.append(v); vols.append(p); nb = adj[v]; m = len(nb); new_entries = 0
        for j, w in enumerate(nb):                                               # exact count of the NEW directed entries the fill creates (existing adjacency is not re-charged)
            new_entries += len(nb - {w} - adj[w])
            if (j & 63) == 63: clock.poll('in the fill count')
        charged += B.charge(new_entries * GRAPH_ENTRY_BYTES, 'fill of eliminating %d (%d new directed entries among %d neighbours)' % (v, new_entries, m))
        for w in nb: adj[w] |= nb - {w}; adj[w].discard(v)
        alive.discard(v); adj[v] = set(); clock.poll('in the order construction')
    B.release(charged); return order, vols


class Solve:
    __slots__ = ('N_lo', 'N_hi', 'Z_lo', 'Z_hi', 'p', 'stats', 'order', 'certificate', 'zero')


def run_executor(cmodel, order, scalar, deadline, stats_out, label):
    """lower / upper coarse model through build / load / lower / cex_run / enclose (identical calls to the accepted layered adapter); returns Solve with EXACT rational
    enclosures of every coarse numerator N_v(c), of Z (x the canonical scalar), and the kernel's own ratio enclosures p; ZERO_EVIDENCE -> Solve.zero = True"""
    t0 = tnow(); st = {'phase': 'build', 'label': label}
    def guard(where):
        if tnow() >= deadline: raise Refused('DEADLINE', 'deadline expired %s' % where, st)
    guard('at the executor adapter entry')
    try:
        prov = CX.build(deadline); lib = CX.load(prov); st['build_s'] = tnow() - t0; hb = USABLE_BYTES - CX.rss_bytes()
        if hb <= 0: raise Refused('MEMORY', 'no capacity under the usable policy at the adapter entry', st)
        B = CX.HostBudget(hb, st); t = tnow(); words, vals, meta = CX.lower(cmodel, order, 0.25, deadline, budget=B); st['lowering_s'] = tnow() - t
        S = Solve(); S.order = list(order); S.stats = st
        if meta.get('zero_evidence'): S.zero = True; S.Z_lo = S.Z_hi = F(0); S.N_lo = S.N_hi = None; S.p = None; S.certificate = None; return S
        n = meta['n']; cards = meta['cards']; tot = sum(cards)
        B.charge(len(words) * 8 + max(1, len(vals)) * 8 + tot * 8 + n * 16 + 8 + 16 + len(CX.COUNTERS) * 8 + 256, 'ctypes arrays'); kcap = hb - B.live
        if kcap <= 0: raise Refused('MEMORY', 'host charges leave no kernel capacity', st)
        W = (C.c_int64 * len(words))(*words); V = (C.c_double * max(1, len(vals)))(*vals); N = (C.c_double * tot)(); NE = (C.c_int64 * n)(); NL = (C.c_int64 * n)(); Z = (C.c_double * 1)(); ZM = (C.c_int64 * 2)(); CT = (C.c_uint64 * len(CX.COUNTERS))(); RS = C.create_string_buffer(256)
        guard('before the kernel'); t = tnow()
        with CX._KERNEL_LOCK: rc = lib.cex_run(W, len(words), V, len(vals), kcap, float(deadline), 0.25, N, NE, NL, Z, ZM, CT, len(CX.COUNTERS), RS, 256)
        st['kernel_s'] = tnow() - t; st['counters'] = {k: int(CT[i]) for i, k in enumerate(CX.COUNTERS)}; st['kernel_status'] = CX.STOPS.get(rc, 'UNKNOWN_%d' % rc); st['kernel_reason'] = RS.value.decode(errors='replace')
        if rc == 7: S.zero = True; S.Z_lo = S.Z_hi = F(0); S.N_lo = S.N_hi = None; S.p = None; S.certificate = None; return S
        if rc != 0: raise Refused(CX.STOPS.get(rc, 'FAULT'), st['kernel_reason'], st)
        guard('before the enclosure'); t = tnow()
        Nv = [N[i] for i in range(tot)]; NEv = [int(x) for x in NE]; NLv = [int(x) for x in NL]
        intervals, points, maxK, maxw = CX.enclose(Nv, NEv, NLv, Z[0], int(ZM[0]), int(ZM[1]), cards, {}, st, deadline, budget=B)
        zl = int(ZM[1]); dz = zl * U
        if dz >= F(1, 2): raise Refused('RANGE', 'normalizer label too large (K=%d)' % zl, st)
        zhat = F(Z[0]) * F(2) ** int(ZM[0])
        if zhat <= 0: raise Refused('RANGE', 'nonpositive normalizer', st)
        S.zero = False; S.Z_lo = zhat * (1 - dz) * scalar; S.Z_hi = zhat / (1 - dz) * scalar; S.p = intervals; S.N_lo = []; S.N_hi = []; off = 0
        for v in range(n):
            dn = NLv[v] * U
            if dn >= F(1, 2): raise Refused('RANGE', 'numerator label too large (K=%d)' % NLv[v], st)
            lo = []; hi = []
            for a in range(cards[v]):
                x = F(Nv[off + a]) * F(2) ** NEv[v] * scalar
                if x == 0: lo.append(F(0)); hi.append(F(0))                 # exact zero (kernel operand provenance)
                else: lo.append(x * (1 - dn)); hi.append(x / (1 - dn))
            S.N_lo.append(lo); S.N_hi.append(hi); off += cards[v]
            if (v & 255) == 255: guard('in the numerator enclosure')
        st['enclosure_s'] = tnow() - t; st['max_label_K'] = maxK; st['max_width_float'] = float(maxw); st['Z_label'] = zl; B.report(); st['total_s'] = tnow() - t0
        S.certificate = dict(method='coarse envelope -> compiled_nonnegative_bucket_contraction_all_singleton_reverse (cex_executor primitives, unchanged)', semantic_plan_sha256=meta['semantic_plan_sha256'], physical_schedule_sha256=meta['physical_schedule_sha256'],
                             kernel={k: prov.get(k) for k in ('source_sha256', 'binary_sha256', 'compiler', 'schedule_id', 'plan_format')}, max_label_K=maxK, Z_label=zl)
        guard('before the adapter return'); return S
    except CX.Stop as e:
        raise Refused(e.kind, str(e.reason)[:300], {k: v for k, v in (e.stats or {}).items() if k != 'counters'})


# ------------------------------------------------------------------ proposers (UNTRUSTED: floats, heuristics)
def slice_profiles(M, clock=None, budget=None):
    """per variable, per state: concatenated incident log-slice profiles (each slice centered by its own mean log); charged BEFORE construction per factor (log table, one transient slice,
    the per-axis profile floats appended), polled per axis; (None, reason) when a factor has a zero entry (typed skip). Logs are bounded (flog), never a float of the value."""
    clock = clock or Clock(math.inf, {}); budget = budget or Budget(1 << 62); n = len(M.cards); prof = [[[] for _ in range(M.cards[v])] for v in range(n)]
    for fi, (sc, vals) in enumerate(M.factors):
        clock.poll('before the slice profiles of factor %d' % fi)
        if any(x <= 0 for x in vals): return None, 'factor %d has a zero entry: the positive-log proposer is unavailable' % fi
        vol = len(vals); cs = [M.cards[v] for v in sc]; st = strides(cs)
        budget.charge(vol * 32 + len(sc) * vol * 32 + vol * 32 + sum(cs) * 64, 'log table + per-axis slice profiles of factor %d' % fi)
        logs = [flog(x) for x in vals]
        for ax, v in enumerate(sc):
            others = [i for i in range(len(sc)) if i != ax]; ocs = [cs[i] for i in others]
            for a in range(cs[ax]):
                sl = [logs[a * st[ax] + sum(st[i] * b for i, b in zip(others, o))] for o in itertools.product(*(range(c) for c in ocs))]
                m = sum(sl) / len(sl); prof[v][a].extend(x - m for x in sl)
            clock.poll('after an axis of the slice profiles')
    return prof, None


def farthest_split(prof_states, states, clock=None):
    """states (list of state ids, canonical order) -> two nonempty lists by the farthest-pair-seed rule; one list when the diameter is 0; polled per 64 pairs"""
    clock = clock or Clock(math.inf, {}); best = None; k = 0
    for i in range(len(states)):
        for j in range(i + 1, len(states)):
            dd = max((abs(x - y) for x, y in zip(prof_states[states[i]], prof_states[states[j]])), default=0.0)
            if best is None or dd > best[0]: best = (dd, i, j)
            k += 1
            if (k & 63) == 63: clock.poll('in the farthest-pair scan')
    if best is None or best[0] == 0.0: return [list(states)]
    _, i, j = best; s0, s1 = states[i], states[j]; g0 = []; g1 = []
    for t, s_ in enumerate(states):
        if s_ == s0: g0.append(s_); continue
        if s_ == s1: g1.append(s_); continue
        d0 = max(abs(x - y) for x, y in zip(prof_states[s_], prof_states[s0])); d1 = max(abs(x - y) for x, y in zip(prof_states[s_], prof_states[s1]))
        (g0 if d0 <= d1 else g1).append(s_)                                   # ties -> the seed earlier in canonical order (s0 < s1 by construction)
        if (t & 63) == 63: clock.poll('in the seed assignment')
    return [sorted(g0), sorted(g1)]


def canonical_classes(groups, card):
    """groups (lists of states) -> classes list with ids in order of first appearance along the state order"""
    cl = [None] * card; nxt = 0
    for a in range(card):
        if cl[a] is not None: continue
        g = next(g for g in groups if a in g)
        for s in g: cl[s] = nxt
        nxt += 1
    return cl


def unit_scales(M): return {(fi, ax): [F(1)] * M.cards[v] for fi, (sc, _) in enumerate(M.factors) for ax, v in enumerate(sc)}


def rationalize(theta):
    if not math.isfinite(theta) or abs(theta) > 40: raise ValueError('inadmissible log scale')
    q = F(math.exp(theta)).limit_denominator(RATIONALIZE_DEN)
    if q <= 0 or bits(q) > 128: raise ValueError('inadmissible rationalized scale')
    return q


def centering_scales(M, classes, clock):
    """slice centering: log scale of state a = its slice mean minus the slice mean at the representative of its proposed class (a source scan, no inference)"""
    out = {}
    for fi, (sc, vals) in enumerate(M.factors):
        logs = [flog(x) for x in vals]; cs = [M.cards[v] for v in sc]; st = strides(cs)
        for ax, v in enumerate(sc):
            others = [i for i in range(len(sc)) if i != ax]; ocs = [cs[i] for i in others]; means = []
            for a in range(cs[ax]):
                sl = [logs[a * st[ax] + sum(st[i] * b for i, b in zip(others, o))] for o in itertools.product(*(range(c) for c in ocs))]; means.append(sum(sl) / len(sl))
            reps = {}
            for a in range(cs[ax]): reps.setdefault(classes[v][a], a)
            out[(fi, ax)] = [rationalize(means[a] - means[reps[classes[v][a]]]) for a in range(cs[ax])]
        clock.poll('in the centering scan')
    return out


class LPWorker:
    """ONE supervised, killable child per cell (lp_worker.py: numpy + scipy); the parent enforces the allowance and the global deadline on BOTH the pipe write and the reply wait; status never
    certifies anything"""
    def __init__(self):
        self.p = subprocess.Popen([sys.executable, os.path.join(HERE, 'lp_worker.py')], stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True)
        self.q = queue.Queue(); threading.Thread(target=self._reader, daemon=True).start()
    def _reader(self):
        for line in self.p.stdout: self.q.put(line)
        self.q.put(None)
    def ask(self, task, timeout):
        t_end = tnow() + max(0.0, timeout); payload = json.dumps(task) + '\n'; done = threading.Event()
        def w():
            try: self.p.stdin.write(payload); self.p.stdin.flush()
            except Exception: pass
            done.set()
        threading.Thread(target=w, daemon=True).start()
        if not done.wait(max(0.0, t_end - tnow())): return None
        try: line = self.q.get(timeout=max(0.0, t_end - tnow()))
        except queue.Empty: return None
        return json.loads(line) if line else None
    def kill(self):
        try: self.p.kill(); self.p.wait(timeout=2)
        except Exception: pass


def lp_fit_scales(M, classes, base_scales, clock, allowance_deadline, rec, budget=None):
    """FIT proposal: per positive factor the centered Chebyshev LP (two sparse inequalities per entry, one pinned theta per incidence / class, one center per cell), solved in the
    worker; rationalized; per-factor the smaller EXACT local range (fitted vs FAST) is retained. Returns scales (or None) and fills rec (attempted / refused / per-factor)."""
    t0 = tnow(); w = None; out = dict(base_scales); rec.update(attempted=True, factors=[], worker_setup_s=None)
    try:
        w = LPWorker(); hello = w.ask(dict(kind='hello'), min(allowance_deadline, clock.deadline) - tnow()); rec['worker_setup_s'] = tnow() - t0
        if not hello or hello.get('status') != 'ready': rec['refused'] = 'worker did not start within the allowance'; return None
        for fi, (sc, vals) in enumerate(M.factors):
            clock.poll('before an LP factor'); left = min(allowance_deadline, clock.deadline) - tnow()
            if left <= 0: rec['refused'] = 'allowance exhausted before factor %d' % fi; return None
            cs = [M.cards[v] for v in sc]; params = {}; reps = []; (budget or Budget(1 << 62)).charge(len(vals) * (64 + 24 * len(sc) + 32) + 2048, 'LP payload of factor %d (entries + axis lists + JSON text)' % fi)
            for ax, v in enumerate(sc):
                r = {}
                for a in range(cs[ax]): r.setdefault(classes[v][a], a)
                reps.append(r)
                for a in range(cs[ax]):
                    if r[classes[v][a]] != a: params[(ax, a)] = len(params)
            cells = {}; entries = []
            for idx, x in enumerate(itertools.product(*(range(c) for c in cs))):
                c = tuple(classes[v][a] for v, a in zip(sc, x)); ci = cells.setdefault(c, len(cells))
                entries.append([flog(vals[idx]), [params.get((ax, a), -1) for ax, a in enumerate(x)], ci])
            fr = dict(factor=fi, rows=2 * len(entries), columns=len(params) + len(cells) + 1)
            rec['factors'].append(fr); clock.poll('before the LP solve')
            ans = w.ask(dict(kind='lp', n_params=len(params), n_cells=len(cells), entries=entries, time_limit=max(0.01, left)), left)
            if ans is None: fr['status'] = 'TIMEOUT'; rec['refused'] = 'LP worker timed out on factor %d' % fi; return None
            fr.update(status=ans.get('status'), nit=ans.get('nit'), fun=ans.get('fun'), seconds=ans.get('seconds'))
            if ans.get('status') != 'ok': rec['refused'] = 'LP refused on factor %d: %s' % (fi, ans.get('message', '')[:120]); return None
            th = ans['x']
            try:
                for ax, v in enumerate(sc): out[(fi, ax)] = [rationalize(th[params[(ax, a)]]) if (ax, a) in params else F(1) for a in range(cs[ax])]
            except ValueError as e: fr['status'] = 'RATIONALIZE_REFUSED'; rec['refused'] = 'rationalization refused on factor %d: %s' % (fi, e); return None
        rec['proposal_s'] = tnow() - t0; return out
    finally:
        if w is not None: w.kill()
        rec['elapsed_s'] = tnow() - t0


def per_factor_select(M, classes, cand_scales, base_scales, clock, budget):
    """retain, per factor, the scales with the smaller EXACT local range (ties -> base); both ranges recomputed from the source (the local surrogate only)"""
    out = dict(base_scales); kept = []
    for fi, (sc, vals) in enumerate(M.factors):
        rs = []
        for scl in (base_scales, cand_scales):
            Rf = F(1); cs = [M.cards[v] for v in sc]; cst = strides([max(classes[v]) + 1 for v in sc]); cell = {}
            for idx, x in enumerate(itertools.product(*(range(c) for c in cs))):
                h = vals[idx]
                for ax, a in enumerate(x): h = checked_div(h, scl[(fi, ax)][a])
                c = sum(cst[ax] * classes[v][a] for ax, (v, a) in enumerate(zip(sc, x))); lo, hi = cell.get(c, (h, h)); cell[c] = (min(lo, h), max(hi, h))
                if (idx & 255) == 255: clock.poll('in the per-factor range comparison')
            for lo, hi in cell.values():
                if hi > 0 and lo > 0 and hi / lo > Rf: Rf = hi / lo
            rs.append(Rf)
        if rs[1] < rs[0]:
            for ax in range(len(sc)): out[(fi, ax)] = cand_scales[(fi, ax)]
            kept.append('fit')
        else: kept.append('base')
    return out, kept


def refine(M, Cz, prof, clock):
    """ONE split: the cell of maximum (U-L)/(U+L); its largest nonsingleton class; farthest-profile split (canonical balanced split when all profiles coincide); returns new classes or None"""
    best = None
    for fi, (sc, _) in enumerate(M.factors):
        for c, g in enumerate(Cz.gaps[fi]):
            if best is None or g > best[0]: best = (g, fi, c)
        clock.poll('in the refinement scan')
    if best is None or best[0] == 0: return None, 'no cell with a positive gap'
    g, fi, c = best; sc = M.factors[fi][0]; ccs = [Cz.ccards[v] for v in sc]; cst = strides(ccs); cell = [(c // cst[ax]) % ccs[ax] for ax in range(len(sc))]
    cand = []
    for ax, v in enumerate(sc):
        members = [a for a in range(M.cards[v]) if Cz.classes[v][a] == cell[ax]]
        if len(members) > 1: cand.append((len(members), v, members))
    if not cand: return None, 'the maximum-gap cell is all singletons'
    cand.sort(key=lambda t: (-t[0], t[1])); _, v, members = cand[0]
    groups = farthest_split(prof[v], members, clock) if prof is not None else [list(members)]
    if len(groups) == 1: groups = [members[:len(members) // 2], members[len(members) // 2:]]
    other = [[a for a in range(M.cards[v]) if Cz.classes[v][a] == k] for k in range(Cz.ccards[v]) if k != cell[ax_of(sc, v)]]
    new = list(Cz.classes); new[v] = canonical_classes(other + groups, M.cards[v]); return new, dict(factor=fi, cell=cell, variable=v, split=[len(groups[0]), len(groups[1])], gap=float(g))


def ax_of(sc, v): return list(sc).index(v)


# ------------------------------------------------------------------ query recovery (exact rationals)
def compose_decoder(stages, v_canon, a):
    """stages = list of (classes, Cz) from fine to coarse; returns (class in the coarsest stage, product decoder d(a | c_coarsest))"""
    d = F(1); c = a
    for classes, Cz in stages:
        k = classes[v_canon][c]; d = checked_mul(d, Cz.d[v_canon][c]); c = k
    return c, d


def one_solve_interval(mu_lo, mu_hi, R):
    """[mu/(mu+R(1-mu)), R mu/(R mu + 1 - mu)] on a normalized feature with lower-model expectation in [mu_lo, mu_hi] (both endpoints increasing in mu)"""
    mu_lo = max(F(0), min(F(1), mu_lo)); mu_hi = max(F(0), min(F(1), mu_hi))
    if mu_lo > mu_hi: raise Defect('empty expectation enclosure')
    lo = F(0) if mu_lo == 0 else checked_div(mu_lo, checked_add(mu_lo, checked_mul(R, 1 - mu_lo))); hi = F(1) if mu_hi == 1 else checked_div(checked_mul(R, mu_hi), checked_add(checked_mul(R, mu_hi), 1 - mu_hi))
    return lo, hi


def rows_from_witness(M, stages, SL, SU, R, clock):
    """exact original-coordinate intervals for every retained canonical variable from the lower solve (one-solve finite-R bound when R is finite) and the upper solve (two-envelope
    event / complement ratio by positive weighted sums) when present. Returns {(v_canon, a): (lo, hi)} or raises Defect / Refused."""
    out = {}; classes_top, Cz_top = stages[-1]
    for v in range(len(M.cards)):
        kc = Cz_top.ccards[v]
        for a in range(M.cards[v]):
            c, d = compose_decoder(stages, v, a); lo, hi = F(0), F(1)
            if d == 0: out[(v, a)] = (F(0), F(0)); continue                       # zero-mass state: exact 0 (u = 0)
            if R is not None:
                plo, phi = SL.p[v][c]; mu_lo = checked_mul(d, plo); mu_hi = min(F(1), checked_mul(d, phi))
                lo, hi = one_solve_interval(mu_lo, mu_hi, R)
            if SU is not None and not SU.zero:
                ev_lo = checked_mul(d, SL.N_lo[v][c]); ev_hi = checked_mul(d, SU.N_hi[v][c])
                comp_U = checked_add(csum(SU.N_hi[v][k] for k in range(kc) if k != c), checked_mul(SU.N_hi[v][c], 1 - d))
                comp_L = checked_add(csum(SL.N_lo[v][k] for k in range(kc) if k != c), checked_mul(SL.N_lo[v][c], 1 - d))
                l2 = (F(1) if comp_U == 0 else F(0)) if ev_lo + comp_U == 0 else checked_div(ev_lo, checked_add(ev_lo, comp_U))
                h2 = (F(0) if ev_hi == 0 else F(1)) if ev_hi + comp_L == 0 else checked_div(ev_hi, checked_add(ev_hi, comp_L))
                lo, hi = max(lo, l2), min(hi, h2)
            if lo > hi: raise Defect('empty interval at canonical (%d, %d)' % (v, a))
            out[(v, a)] = (lo, hi)
        clock.poll('in the row recovery')
    return out


def compact_outward(lo, hi, Q=1 << 52):
    L = max(F(0), F(math.floor(lo * Q), Q)); H = min(F(1), F(-((-hi * Q).numerator // (-hi * Q).denominator), Q)); return L, H


def epsilon_safe_points(box, eps):
    """the accepted ancestral decoder's point policy: J_a = [max(L, H - eps), min(H, L + eps)] (nonempty since H - L <= 2 eps); the former greedy simplex candidate (lower endpoints filled
    to sum 1) is clamped into J and normalized WITHIN J when the J box meets the simplex (so an old point already feasible in J is returned unchanged); otherwise the midpoints of the certified
    intervals (their sum need not be 1: the interval sums contain 1). Never changes the enclosing intervals."""
    J = [(max(L, H - eps), min(H, L + eps)) for L, H, _ in box]
    pts = [L for L, H, _ in box]; left = 1 - sum(pts)
    for i, (L, H, _) in enumerate(box):
        take = min(left, H - pts[i]); pts[i] += take; left -= take
    pts = [min(max(p_, jl), jh) for p_, (jl, jh) in zip(pts, J)]
    if sum(jl for jl, _ in J) <= 1 <= sum(jh for _, jh in J):
        s_ = sum(pts)
        if s_ < 1:
            left = 1 - s_
            for i, (jl, jh) in enumerate(J):
                take = min(left, jh - pts[i]); pts[i] += take; left -= take
        elif s_ > 1:
            left = s_ - 1
            for i, (jl, jh) in enumerate(J):
                take = min(left, pts[i] - jl); pts[i] -= take; left -= take
        if sum(pts) != 1: raise Defect('J-box normalization failed')
        return pts, 'J_normalized'
    return [(L + H) / 2 for L, H, _ in box], 'midpoints'


def publish(M, acc, eps, clock):
    """per ORIGINAL retained variable: outward 2^-52 compaction; epsilon-safe points (epsilon_safe_points); acceptance 0 <= lo <= pt <= hi <= 1, width <= 2 eps AND endpoint radius
    max(pt - lo, hi - pt) <= eps on every row; rows failing acceptance stay NOT_PUBLISHED (the whole variable, since the points need the row)"""
    rows = {}
    for v in range(len(M.cards)):
        c = M.cards[v]; box = []
        for a in range(c):
            lo, hi = acc[(v, a)]
            if lo == hi: box.append((lo, hi, 'EXACT'))
            else:
                L, H = compact_outward(lo, hi)
                if not (L <= lo and H >= hi): raise Defect('compaction does not enclose')
                box.append((L, H, 'DETERMINISTIC'))
        s_lo = sum(b[0] for b in box); s_hi = sum(b[1] for b in box)
        if s_lo > 1 or s_hi < 1: raise Defect('row box of canonical variable %d excludes the simplex' % v)
        ok = all(b[1] - b[0] <= 2 * eps for b in box); pts = None
        if ok:
            pts, _ = epsilon_safe_points(box, eps)
            ok = all(b[0] <= p_ <= b[1] and max(p_ - b[0], b[1] - p_) <= eps for b, p_ in zip(box, pts))
        for a in range(c): rows[(M.orig_of[v], a)] = dict(lo=box[a][0], hi=box[a][1], point=pts[a], guarantee=box[a][2]) if ok else None
        clock.poll('in the publication')
    return rows


# ------------------------------------------------------------------ the compiler run
def compile_and_solve(model, budget_s, policy='FAST', eps=F(1, 200), fit_allowance_s=FIT_ALLOWANCE_S, admission_stop_s=ADMISSION_STOP_S, t_start=None, allow_approx=True):
    """policy FAST | FIT; returns the result dict (outcome, guarantee, published, K, answers, Z_enclosure, mechanism, phases_s, wall_s).
    Clocks: `hard` = t_start + budget_s is the HARD deadline (nothing is assembled or published after it; an expired hard deadline during final assembly returns DEADLINE with no rows);
    `adm` = t_start + admission_stop_s stops admitting new construction / solves. A validated partial (retained intersections) is published only when its assembly finishes before `hard`.
    The original query inventory (cards, evidence) is fixed from the input BEFORE canonicalization, so every refusal path returns a typed result with every row NOT_PUBLISHED."""
    t_start = T_PROCESS_START if t_start is None else t_start; hard = t_start + budget_s; adm = t_start + min(budget_s, admission_stop_s)
    out = dict(version=VERSION, policy=policy, budget_s=budget_s, admission_stop_s=admission_stop_s, epsilon=str(eps), phases_s={}, mechanism=dict(witnesses=[], executor_calls=0, proposals={}, refinements=[], t_start_monotonic=t_start), outcome=None, answers=None)
    ph = out['phases_s']; stats = {}; clock = Clock(adm, stats); hclock = Clock(hard, stats); budget = Budget(CONSTRUCTOR_BYTES); mech = out['mechanism']; retained = {}; witnesses = 0; Zenc = None; M = None
    cards_in = list(model['cards']); ev_in = dict(model.get('evidence', {})); inventory = [(v, a) for v in range(len(cards_in)) if v not in ev_in for a in range(cards_in[v])]
    def fin(oc, rows_canon, guarantee=None, note=None):
        """final assembly of every ORIGINAL row (polled against the HARD deadline: an expiry here returns DEADLINE with nothing published); the inventory does not depend on M"""
        out['outcome'] = oc
        if note: mech['note'] = note
        rows = []; pub = 0; gs = set(); fixed = M.fixed_rows if M is not None else {}; pos = mech.get('positive_mass_witness')
        try:
            if oc not in ('DEADLINE',): hclock.poll('at the final assembly entry')
            for j, (v, a) in enumerate(inventory):
                if (j & 255) == 255: hclock.poll('in the final assembly')
                if (v, a) in fixed:
                    val, g = fixed[(v, a)]
                    if val is None or not pos: rows.append(dict(var=v, state=a, guarantee='NOT_PUBLISHED')); gs.add('NOT_PUBLISHED'); continue
                    rows.append(dict(var=v, state=a, lo=str(val), hi=str(val), point=str(val), guarantee=g)); pub += 1; gs.add(g); continue
                r = rows_canon.get((v, a)) if rows_canon else None
                if r is None: rows.append(dict(var=v, state=a, guarantee='NOT_PUBLISHED')); gs.add('NOT_PUBLISHED')
                else: rows.append(dict(var=v, state=a, lo=str(r['lo']), hi=str(r['hi']), point=str(r['point']), guarantee=r['guarantee'])); pub += 1; gs.add(r['guarantee'])
            if oc in ('COMPLETE', 'PARTIAL', 'DEADLINE_PARTIAL') and pub: hclock.poll('before committing the published rows')
        except Refused as e:                                                   # the hard deadline expired during assembly: nothing is published
            mech['late_assembly'] = str(e.reason)[:120]; rows = [dict(var=v, state=a, guarantee='NOT_PUBLISHED') for v, a in inventory]; pub = 0; gs = {'NOT_PUBLISHED'}; out['outcome'] = oc = 'DEADLINE'
        out['answers'] = rows; out['published'] = pub; out['K'] = len(rows)
        out['guarantee'] = guarantee or ('EXACT' if gs <= {'EXACT'} else ('DETERMINISTIC' if gs <= {'EXACT', 'DETERMINISTIC'} else 'PARTIAL'))
        if out['outcome'] == 'COMPLETE' and pub < len(rows): out['outcome'] = 'DEADLINE_PARTIAL' if any(w.get('status') == 'DEADLINE' for w in mech['witnesses']) or clock.remaining() <= 0 else 'PARTIAL'
        if out['outcome'] == 'REFUSED' and pub > 0: out['outcome'] = 'PARTIAL'
        ws = [float(F(r['hi']) - F(r['lo'])) for r in rows if r['guarantee'] != 'NOT_PUBLISHED']; out['max_width'] = max(ws) if ws else None
        mech.update(constructor_budget_peak_bytes=budget.peak, constructor_budget_cumulative_bytes=budget.cumulative, polls=clock.polls + hclock.polls, witnesses_used=witnesses); mech.pop('t_start_monotonic', None)
        out['peak_rss_bytes'] = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss; out['wall_s'] = tnow() - t_start; out['in_process_total_s'] = tnow() - T_PROCESS_START; out['hard_deadline_respected'] = out['wall_s'] <= budget_s; return out
    def finish_ok(rows, note):
        clock.poll('before success'); hclock.poll('before success (hard)'); return fin('COMPLETE', rows, note=note)
    t0 = tnow()
    try:
        hclock.poll('at the compiler entry'); clock.poll('at the compiler entry (admission)')
        M = canonicalize(model, clock, budget); ph['canonicalize'] = tnow() - t0; mech.update(canonical=dict(variables=len(M.cards), factors=len(M.factors), entries=sum(len(v) for _, v in M.factors), removed_fixed=len([k for k in M.fixed_rows]), scalar_bits=bits(M.scalar)))
        if M.zero_mass: mech['positive_mass_witness'] = False; out['Z_enclosure'] = dict(lo='0', hi='0', positive=False); return fin('ZERO_EVIDENCE', {}, note='a canonical scalar is exactly zero: original mass is zero')
        if not M.cards:                                                        # everything collapsed: Z = scalar exactly
            mech['positive_mass_witness'] = True; out['Z_enclosure'] = dict(lo=str(M.scalar), hi=str(M.scalar), positive=True); return finish_ok({}, 'no retained variables: exact scalar normalizer')
        # ---- stage 1: exact projective quotient (joint refinement of complete proportional slice profiles over all incident factors)
        t0 = tnow(); classes1 = exact_profile_classes(M, clock, budget); scales1 = exact_scales(M, classes1, clock)
        Cz1 = check_candidate(M, classes1, scales1, clock, budget); ph['exact_quotient'] = tnow() - t0
        if not Cz1.exact: raise Defect('the exact profile quotient fails the entrywise identity (L != U)')
        if policy == 'FIT': mech['proposals']['fit'] = dict(attempted=False, status='NOT_REACHED')
        reduced = any(k < c for k, c in zip(Cz1.ccards, M.cards)); mech['exact_quotient'] = dict(coarse_cards=Cz1.ccards, reduced=reduced, states=sum(Cz1.ccards), original_states=sum(M.cards))
        M1 = stage_model(M, Cz1)                                               # the quotient as a canonical model (unaries A, tables L = U, same scalar)
        stages = [(classes1, Cz1)]
        order1, vols1 = elimination_order(M1.cards, [sc for sc, _ in M1.factors], clock, budget); mech['exact_quotient'].update(order_volume_sum=sum(vols1), order_volume_max=max(vols1))
        # scheduling rule (frozen): run the exact quotient when it reduced a domain or left only unary / scalar factors AND its forecast is admitted; else try the approximate construction first
        exact_first = (reduced or not M1.factors) and admitted(vols1, clock)
        if exact_first:
            witnesses += 1; t0 = tnow(); SL = run_executor(coarse_model(M, Cz1, 0), order1, M.scalar, adm, stats, 'exact_quotient'); mech['executor_calls'] += 1; ph['exact_solve'] = tnow() - t0
            w = dict(kind='exact_quotient', status='ZERO_EVIDENCE' if SL.zero else 'SOLVED', kernel_s=SL.stats.get('kernel_s'), order_volume_sum=sum(vols1), executor_calls=1, coarse_states=sum(Cz1.ccards), max_bits=max([bits(x) for L in Cz1.L for x in L if x is not None] + [bits(x) for A in Cz1.A for x in A])); mech['witnesses'].append(w)
            if SL.zero: mech['positive_mass_witness'] = False; out['Z_enclosure'] = dict(lo='0', hi='0', positive=False); return fin('ZERO_EVIDENCE', {}, note='the exact quotient has zero mass (upper mass zero certifies original zero mass)')
            mech['positive_mass_witness'] = True; Zenc = (SL.Z_lo, SL.Z_hi); set_Z(out, SL.Z_lo, SL.Z_hi)
            acc = rows_from_witness(M, stages, SL, None, F(1), clock); retained = intersect(retained, acc); rows = publish(M, retained, eps, clock)
            w['published'] = sum(1 for r in rows.values() if r); w['max_width'] = float(max(hi - lo for lo, hi in retained.values())); w['validated_at_s'] = tnow() - t_start
            if all(r is not None for r in rows.values()): return finish_ok(rows, 'exact projective quotient')
            if witnesses >= MAX_WITNESSES or not allow_approx: return fin('PARTIAL', rows, note='exact quotient published a partial answer; witness cap')
        # ---- stage 2: approximate grouping on the exact quotient (positive tables only); numeric proposal failures are typed and never escape
        t0 = tnow()
        try: prof, why = slice_profiles(M1, clock, budget)
        except (ValueError, OverflowError, ZeroDivisionError) as e: prof, why = None, 'profile proposer refused: %s' % str(e)[:80]
        ph['profiles'] = tnow() - t0
        if prof is None:
            mech['proposals']['approximate'] = dict(status='SKIPPED', reason=why)
            return fin('REFUSED', publish(M, retained, eps, clock) if retained else {}, note=('no approximate proposer (%s); exact quotient did not complete' % why) if retained else 'no approximate proposer (%s)' % why)
        budget.charge(sum(c * c * 8 for c in M1.cards), 'pairwise distances')
        classes2 = [canonical_classes(farthest_split(prof[v], list(range(M1.cards[v])), clock), M1.cards[v]) if M1.cards[v] > 1 else [0] for v in range(len(M1.cards))]
        mech['proposals']['partition'] = dict(coarse_cards=[max(c) + 1 for c in classes2])
        # gauge: unit vs cheap centering by the exact local R (ties -> unit; both infinite -> unit; a refused centering proposal -> unit, typed)
        t0 = tnow(); unit = unit_scales(M1); Cu = check_candidate(M1, classes2, unit, clock, budget)
        try: cen = centering_scales(M1, classes2, clock); Cc = check_candidate(M1, classes2, cen, clock, budget); cen_note = None
        except (ValueError, OverflowError, ZeroDivisionError) as e: cen = None; Cc = None; cen_note = 'centering proposal refused: %s' % str(e)[:80]
        ph['gauge_fast'] = tnow() - t0
        pick = 'unit' if (Cc is None or Cc.R is None or (Cu.R is not None and Cu.R <= Cc.R)) else 'centering'
        mech['proposals']['fast_gauge'] = dict(unit_R=fl(Cu.R), centering_R=(fl(Cc.R) if Cc is not None else None), selected=pick, mixed_cells=Cu.mixed, centering_refused=cen_note)
        scales2 = unit if pick == 'unit' else cen; Cz2 = Cu if pick == 'unit' else Cc
        # FAST baseline witness
        res = witness(M, M1, stages, classes2, scales2, Cz2, 'fast_baseline', clock, budget, stats, adm, retained, eps, mech, out)
        witnesses += 1; retained, rows, done, Zenc = res
        if done:
            if policy == 'FIT': mech['proposals']['fit'] = dict(attempted=False, status='BYPASSED: the FAST baseline completed')
            return finish_ok(rows, 'approximate coarse envelope (FAST baseline)')
        fit_rec = dict(attempted=False)
        mech['proposals']['fit'] = fit_rec; refinements_left = 2 if policy == 'FAST' else 1
        if policy == 'FIT' and witnesses < MAX_WITNESSES and retained is not None:
            if clock.remaining() <= 0: fit_rec['refused'] = 'no time left after the baseline'
            else:
                t0 = tnow()
                try: fitted = lp_fit_scales(M1, classes2, scales2, clock, tnow() + fit_allowance_s, fit_rec, budget)
                except (ValueError, OverflowError, ZeroDivisionError) as e: fitted = None; fit_rec['refused'] = 'fit proposal refused: %s' % str(e)[:80]
                ph['fit_proposal'] = tnow() - t0
                if fitted is not None:
                    sel, kept = per_factor_select(M1, classes2, fitted, scales2, clock, budget); fit_rec['kept_per_factor'] = kept
                    if 'fit' in kept:
                        Cf = check_candidate(M1, classes2, sel, clock, budget); fit_rec['local_R_fast'] = fl(Cz2.R); fit_rec['local_R_fit'] = fl(Cf.R)
                        res = witness(M, M1, stages, classes2, sel, Cf, 'fit_gauge', clock, budget, stats, adm, retained, eps, mech, out); witnesses += 1; retained, rows, done, Zenc = res
                        if done: return finish_ok(rows, 'approximate coarse envelope (FIT gauge)')
                        scales2, Cz2 = sel, Cf
                    else: fit_rec['status'] = 'NO_FACTOR_IMPROVED_LOCAL_RANGE'
        # refinement witnesses on the retained gauge (FAST: up to two; FIT: at most one)
        while witnesses < MAX_WITNESSES and refinements_left > 0 and retained is not None:
            refinements_left -= 1; new, info = refine(M1, Cz2, prof, clock)
            if new is None: mech['refinements'].append(dict(stopped=info)); break
            mech['refinements'].append(info); Cz2 = check_candidate(M1, new, scales2, clock, budget); classes2 = new
            res = witness(M, M1, stages, classes2, scales2, Cz2, 'refinement_%d' % len(mech['refinements']), clock, budget, stats, adm, retained, eps, mech, out); witnesses += 1; retained, rows, done, Zenc = res
            if done: return finish_ok(rows, 'approximate coarse envelope after refinement')
        rows = publish(M, retained, eps, clock) if retained else {}
        return fin('PARTIAL' if any(rows.values()) else 'REFUSED', rows, note='witness cap or no affordable split')
    except Refused as e:
        mech['refusal'] = dict(kind=e.kind, reason=str(e.reason)[:300]); mech.setdefault('positive_mass_witness', None)
        rows = {}
        if retained and M is not None and tnow() < hard:                       # a validated partial is published only before the HARD deadline (fin polls it again during assembly)
            try: rows = publish(M, retained, eps, hclock)
            except Refused: rows = {}
            except Defect as d: mech['defect'] = str(d)[:300]; rows = {}
        return fin('DEADLINE' if e.kind == 'DEADLINE' and not any(rows.values()) else ('DEADLINE_PARTIAL' if e.kind == 'DEADLINE' else ('PARTIAL' if any(rows.values()) else 'REFUSED')), rows)
    except Defect as e:
        mech['defect'] = str(e)[:300]; mech.setdefault('positive_mass_witness', None); return fin('CERTIFICATE_DEFECT', {})
    except (ValueError, OverflowError, ZeroDivisionError) as e:                 # an untrusted numeric path or an invalid input reached the boundary: typed, never a crash
        mech['refusal'] = dict(kind='INVALID_OR_NUMERIC', reason=str(e)[:300]); mech.setdefault('positive_mass_witness', None); return fin('REFUSED', {})


def fl(q):
    if q is None: return None
    if bits(q) >= 2000: return 'huge'
    try: return float(q)
    except OverflowError: return 'huge'


def admitted(vols, clock):
    return 2 * sum(vols) / ROWS_PER_S_CONSERVATIVE <= clock.remaining()


def intersect(old, new):
    if not old: return dict(new)
    out = {}
    for k, (lo, hi) in new.items():
        olo, ohi = old[k]; l, h = max(lo, olo), min(hi, ohi)
        if l > h: raise Defect('empty intersection of validated intervals at %s' % (k,))
        out[k] = (l, h)
    return out


def witness(M, M1, stages, classes, scales, Cz, name, clock, budget, stats, adm, retained, eps, mech, out):
    """one partition / gauge witness: lower solve (one-solve bound when R is finite), then the upper solve if still needed and admitted; retained intervals intersected. Returns
    (retained, rows, complete, Zenc). Zero lower mass -> no publication from this witness (typed), zero upper mass -> ZERO_EVIDENCE certified."""
    stg = stages + [(classes, Cz)]; order, vols = elimination_order(Cz.ccards, [sc for sc, _ in M1.factors], clock, budget)
    w = dict(kind=name, coarse_cards=list(Cz.ccards), coarse_states=sum(Cz.ccards), local_R=fl(Cz.R), mixed_cells=Cz.mixed, exact=Cz.exact, order_volume_sum=sum(vols), order_volume_max=max(vols), executor_calls=0, status=None,
             proposal_record=dict(classes=[list(c) for c in classes], scales={'%d:%d' % k: [str(x) for x in v] for k, v in scales.items()}, order=list(order), bucket_volumes=list(vols), max_bits=max([bits(x) for L in Cz.L for x in L if x is not None] + [bits(x) for Ucell in Cz.U for x in Ucell if x is not None] + [bits(x) for A in Cz.A for x in A]))); mech['witnesses'].append(w)
    if Cz.zero_factor:
        w['status'] = 'ZERO_EVIDENCE'; mech['positive_mass_witness'] = False; out['Z_enclosure'] = dict(lo='0', hi='0'); raise Refused('ZERO_MASS', 'an all-zero factor certifies zero original mass')
    if not admitted(vols, clock): w['status'] = 'FORECAST_REFUSED'; raise Refused('FORECAST', 'lower solve forecast %d rows exceeds the remaining time' % (2 * sum(vols)))
    t0 = tnow()
    try: SL = run_executor(coarse_model(M1, Cz, 0), order, M.scalar, adm, stats, name + ':lower')
    except Refused as e: w['status'] = 'EXECUTOR_' + e.kind; raise
    mech['executor_calls'] += 1; w['executor_calls'] += 1; w['lower_kernel_s'] = SL.stats.get('kernel_s'); w['lower_s'] = tnow() - t0
    if SL.zero:
        w['status'] = 'LOWER_ZERO_MASS'
        if Cz.exact: mech['positive_mass_witness'] = False; out['Z_enclosure'] = dict(lo='0', hi='0'); raise Refused('ZERO_MASS', 'the (exact) coarse model has zero mass')
        return retained, (publish(M, retained, eps, clock) if retained else {}), False, None             # a valid envelope state, no witness from this candidate
    mech['positive_mass_witness'] = True; Zlo = SL.Z_lo; Zhi = SL.Z_hi * Cz.R if Cz.R is not None else None
    acc = rows_from_witness(M, stg, SL, None, Cz.R, clock) if Cz.R is not None else None
    if acc is not None:
        retained = intersect(retained, acc); rows = publish(M, retained, eps, clock); w['one_solve_published'] = sum(1 for r in rows.values() if r); w['one_solve_max_width'] = float(max(hi - lo for lo, hi in retained.values()))
        set_Z(out, Zlo, Zhi); w['validated_at_s'] = tnow() - mech['t_start_monotonic']
        if all(r is not None for r in rows.values()): w['status'] = 'COMPLETE_ONE_SOLVE'; return retained, rows, True, (Zlo, Zhi)
    if Cz.exact: w['status'] = 'EXACT_PARTIAL'; return retained, publish(M, retained, eps, clock), False, (Zlo, Zhi)
    if not admitted(vols, clock): w['status'] = 'UPPER_FORECAST_REFUSED'; return retained, (publish(M, retained, eps, clock) if retained else {}), False, (Zlo, Zhi)
    t0 = tnow()
    try: SU = run_executor(coarse_model(M1, Cz, 1), order, M.scalar, adm, stats, name + ':upper')
    except Refused as e:
        w['status'] = 'UPPER_EXECUTOR_' + e.kind
        if e.kind == 'DEADLINE': raise
        return retained, (publish(M, retained, eps, clock) if retained else {}), False, (Zlo, Zhi)
    mech['executor_calls'] += 1; w['executor_calls'] += 1; w['upper_kernel_s'] = SU.stats.get('kernel_s'); w['upper_s'] = tnow() - t0
    if SU.zero: raise Defect('upper mass zero while the lower mass is positive')
    acc2 = rows_from_witness(M, stg, SL, SU, Cz.R, clock); retained = intersect(retained, acc2)
    Zhi2 = SU.Z_hi if Zhi is None else min(Zhi, SU.Z_hi); set_Z(out, Zlo, Zhi2); w['actual_rho'] = fl(SL.Z_lo / SU.Z_hi)
    rows = publish(M, retained, eps, clock); w['two_solve_published'] = sum(1 for r in rows.values() if r); w['max_width'] = float(max(hi - lo for lo, hi in retained.values())); w['validated_at_s'] = tnow() - mech['t_start_monotonic']
    w['status'] = 'COMPLETE_TWO_SOLVE' if all(r is not None for r in rows.values()) else 'PARTIAL'
    return retained, rows, w['status'] == 'COMPLETE_TWO_SOLVE', (Zlo, Zhi2)


def coarse_joint(M1, Cz, side, scalar, cap=1 << 16):
    """exact enumeration of the coarse envelope model (controls only; guarded): returns {coarse assignment: weight}; counted by the caller as a separate contraction"""
    vol = math.prod(Cz.ccards)
    if vol > cap: raise Refused('ENUM', 'coarse joint enumeration %d > %d (controls only)' % (vol, cap))
    out = {}
    tabs = Cz.L if side == 0 else Cz.U
    for c in itertools.product(*(range(k) for k in Cz.ccards)):
        w = scalar
        for v, k in enumerate(c): w *= Cz.A[v][k]
        for fi, (sc, _) in enumerate(M1.factors):
            if w == 0: break
            cst = strides([Cz.ccards[v] for v in sc]); w *= tabs[fi][sum(cst[ax] * c[v] for ax, v in enumerate(sc))]
        out[c] = w
    return out


def feature_bounds(M, M1, stages, Cz, scalar, feature, lower_only=False):
    """bounded local feature h on CANONICAL variables (scope, table over fine states as Fractions): decoded coarse feature tilde g(c_S) = sum g(x_S) prod d(x_v|c_v) with composed
    decoders, masses G / H from the exact coarse joints (tiny enumeration = a separate contraction, counted), the ratio sandwich on g = (h - a) / (b - a), mapped back by a + (b - a) t;
    with the finite local R also the ONE-LOWER-SOLVE interval. Returns dict(interval, one_solve, rho, R, contractions)."""
    sc, table = feature; a = min(table.values()); b = max(table.values())
    if a == b: return dict(interval=(a, a), one_solve=(a, a), rho=None, R=fl(Cz.R), contractions=0, constant=True)
    top_classes = {}; dec = {}
    for v in sc:
        for x in range(M.cards[v]): top_classes[(v, x)], dec[(v, x)] = compose_decoder(stages, v, x)
    kc = [Cz.ccards[v] for v in sc]; g_of = {}
    for c in itertools.product(*(range(k) for k in kc)):
        g = F(0); gc = F(0); ds = F(0)
        for x in itertools.product(*(range(M.cards[v]) for v in sc)):
            if any(top_classes[(v, xv)] != cv for v, xv, cv in zip(sc, x, c)): continue
            d = F(1)
            for v, xv in zip(sc, x): d *= dec[(v, xv)]
            t = (table[x] - a) / (b - a); g += d * t; gc += d * (1 - t); ds += d
        if ds != 1 or g + gc != 1: raise Defect('decoded feature is not normalized on cell %s' % (c,))
        g_of[c] = (g, gc)
    sides = []
    for side in ((0,) if lower_only else (0, 1)):
        J = coarse_joint(M1, Cz, side, scalar); G = F(0); H = F(0)
        for c, w in J.items():
            g, gc = g_of[tuple(c[v] for v in sc)]; G += w * g; H += w * gc
        sides.append((G, H, G + H))
    GL, HL, ZL = sides[0]
    one = None
    if Cz.R is not None and ZL > 0:
        mu = GL / ZL; lo, hi = one_solve_interval(mu, mu, Cz.R); one = (a + (b - a) * lo, a + (b - a) * hi)
    if lower_only: return dict(interval=one, one_solve=one, rho=None, R=fl(Cz.R), contractions=1, Z_L=ZL)
    GU, HU, ZU = sides[1]
    lo = GL / (GL + HU) if GL + HU else F(0); hi = GU / (GU + HL) if GU + HL else F(1)
    iv = (a + (b - a) * lo, a + (b - a) * hi)
    if one is not None: iv = (max(iv[0], one[0]), min(iv[1], one[1]))
    return dict(interval=iv, one_solve=one, two_solve=(a + (b - a) * lo, a + (b - a) * hi), rho=(ZL / ZU if ZU > 0 else None), R=fl(Cz.R), contractions=2, Z_L=ZL, Z_U=ZU, range=(a, b))


def set_Z(out, lo, hi):
    prev = out.get('Z_enclosure')
    if prev and prev.get('lo') not in (None, '0'):
        lo = max(lo, F(prev['lo']))
        if hi is not None and prev.get('hi') is not None: hi = min(hi, F(prev['hi']))
    out['Z_enclosure'] = dict(lo=str(lo), hi=(str(hi) if hi is not None else None), positive=lo > 0); out['Z_log2'] = (math.log2(lo.numerator) - math.log2(lo.denominator)) if lo > 0 else None


def exact_profile_classes(M, clock, budget):
    """states share an exact class iff every incident complete slice is positively proportional (zero slices: a separate signature); hashes = exact tuples. The signatures of EVERY axis
    of every factor are retained simultaneously until the classes are formed: charged BEFORE construction per factor (normalized entries x/s of up to 2 x the source bits, the raw slice
    coexisting with its normalized tuple, tuple slots, per-state lists, index lists), polled inside; the charge is released when the signatures die."""
    n = len(M.cards); sig = [[[] for _ in range(M.cards[v])] for v in range(n)]; charged = 0
    for fi, (sc, vals) in enumerate(M.factors):
        clock.poll('before the profile signatures of factor %d' % fi); cs = [M.cards[v] for v in sc]; st = strides(cs); vol = len(vals); mb = max(bits(x) for x in vals) if vals else 1
        per_entry = 2 * (FRAC_BYTES + 32 * ((2 * mb + 63) // 64)) + 16
        charged += budget.charge(len(sc) * (vol * per_entry + sum(cs) * 120 + vol * 8 + 64), 'exact profile signatures of factor %d (%d axes x %d entries retained simultaneously)' % (fi, len(sc), vol))
        for ax, v in enumerate(sc):
            others = [i for i in range(len(sc)) if i != ax]; ocs = [cs[i] for i in others]; idxs = [sum(st[i] * b for i, b in zip(others, o)) for o in itertools.product(*(range(c) for c in ocs))]
            for a in range(cs[ax]):
                sl = [vals[a * st[ax] + j] for j in idxs]; s_ = next((x for x in sl if x > 0), None)
                sig[v][a].append(('Z',) if s_ is None else tuple(checked_div(x, s_) for x in sl))
                if (a & 15) == 15: clock.poll('in the profile signatures')
            clock.poll('after an axis of the profile signatures')
    classes = []
    for v in range(n):
        key = {}; cl = []
        for a in range(M.cards[v]):
            k = tuple(sig[v][a]); cl.append(key.setdefault(k, len(key)))
        classes.append(cl)
    budget.release(charged)
    return classes


def exact_scales(M, classes, clock):
    """lambda_fv(a) = (first positive entry of a's slice) / (that of its class representative); zero slices and representatives -> 1"""
    out = {}
    for fi, (sc, vals) in enumerate(M.factors):
        cs = [M.cards[v] for v in sc]; st = strides(cs)
        for ax, v in enumerate(sc):
            others = [i for i in range(len(sc)) if i != ax]; ocs = [cs[i] for i in others]; idxs = [sum(st[i] * b for i, b in zip(others, o)) for o in itertools.product(*(range(c) for c in ocs))]
            first = []
            for a in range(cs[ax]):
                first.append(next((vals[a * st[ax] + j] for j in idxs if vals[a * st[ax] + j] > 0), None))
            reps = {}
            for a in range(cs[ax]): reps.setdefault(classes[v][a], a)
            lam = []
            for a in range(cs[ax]):
                r = reps[classes[v][a]]
                lam.append(F(1) if first[a] is None or first[r] is None else checked_div(first[a], first[r]))
            out[(fi, ax)] = lam
        clock.poll('in the exact scales')
    return out


def stage_model(M, Cz):
    """the coarse model as a canonical model for the next stage (unaries A, tables L (= U when exact), scalar carried once by the outer stage)"""
    M1 = Canon(); M1.cards = list(Cz.ccards); M1.psi = [list(a) for a in Cz.A]; M1.factors = [(sc, list(Cz.L[fi])) for fi, (sc, _) in enumerate(M.factors)]; M1.scalar = F(1); M1.orig_of = list(M.orig_of); M1.fixed_rows = {}; return M1


# ------------------------------------------------------------------ CLI
def main():
    ap = argparse.ArgumentParser(); ap.add_argument('--input', required=True); ap.add_argument('--output', required=True); ap.add_argument('--budget', type=float, default=3.85, help='HARD worker deadline from process start (publication allowed until it); new work is admitted only until --admission-stop'); ap.add_argument('--admission-stop', type=float, default=ADMISSION_STOP_S); ap.add_argument('--policy', default='FAST', choices=['FAST', 'FIT'])
    ap.add_argument('--epsilon', default='1/200'); ap.add_argument('--fit-allowance', type=float, default=FIT_ALLOWANCE_S); a = ap.parse_args()
    sys.path.insert(0, os.path.join(CODE, 'cex', 'newarm')); import core as CORE
    t0 = tnow(); model, binding = CORE.read_uai(a.input); tread = tnow() - t0
    out = compile_and_solve(model, a.budget, policy=a.policy, eps=F(a.epsilon), fit_allowance_s=a.fit_allowance, admission_stop_s=a.admission_stop); out['phases_s']['read'] = tread; out['binding'] = binding; out['input'] = os.path.abspath(a.input); out['argv'] = sys.argv[1:]
    out['process_start_to_read_s'] = t0 - T_PROCESS_START
    if tnow() > T_PROCESS_START + a.budget and out['outcome'] not in ('DEADLINE', 'ZERO_EVIDENCE', 'CERTIFICATE_DEFECT'):   # the hard deadline expired before the output commit: nothing is published
        out['mechanism']['late_commit'] = dict(outcome_before=out['outcome'], published_before=out.get('published')); out['outcome'] = 'DEADLINE'; out['answers'] = [dict(var=r['var'], state=r['state'], guarantee='NOT_PUBLISHED') for r in (out.get('answers') or [])]; out['published'] = 0; out['guarantee'] = 'PARTIAL'; out['max_width'] = None
    out['hard_deadline_respected_at_commit'] = tnow() <= T_PROCESS_START + a.budget
    t_ser = tnow(); os.makedirs(os.path.dirname(os.path.abspath(a.output)), exist_ok=True); json.dump(out, open(a.output, 'w'), indent=1, default=str)
    json.dump(dict(solver_wall_s=out['wall_s'], serialize_s=tnow() - t_ser, in_process_total_s=tnow() - T_PROCESS_START, note='the SUPERVISOR receipt is the scored end-to-end measurement'), open(a.output + '.timing.json', 'w'), indent=1)
    m = out['mechanism']; print(json.dumps(dict(outcome=out['outcome'], guarantee=out.get('guarantee'), published=out.get('published'), K=out.get('K'), wall_s=round(out['wall_s'], 3), calls=m.get('executor_calls'), witnesses=[(w.get('kind'), w.get('status')) for w in m.get('witnesses', [])], refusal=m.get('refusal'), defect=m.get('defect')), default=str))


if __name__ == '__main__': main()
