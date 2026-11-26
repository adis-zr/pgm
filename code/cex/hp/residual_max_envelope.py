"""DGP4 residual MAX compilation (theory note DGP4_RESIDUAL_MAX_THEORY.md; brief sections 3-4). With the approximate classes c_v = C_v(x_v) and the ACTUAL dyadic sampling decoder r(x | c) = prod_v r_v(x_v | c_v) FROZEN,
write every fine state as x_v = member_v(c_v, s_v) and compile an upper envelope U(c) >= t(c) = max_{x in c} W_0(x) / r(x | c) by eliminating the residual variables s_v with MAX mini-buckets that RETAIN every class
axis and pass their messages into later buckets (compatibility of fine-state choices is preserved except where the bounded partition separates factors and at the final closure).
  residual target (lemma 1):  H(c, s) = prod_f h_f(x_f(c, s)) prod_v u_v(x_v) / r_v(x_v | c_v)       (h_f = the accepted gauge residual psi_f / prod lambda; u_v = the compensated unary; each ratio once; no kappa)
  local bound (lemma 2):      max_s prod_G F_G <= prod_G max_s F_G                                     (every MAX mini-bucket message m_G(c_i, y) = up[max_{s_i valid for c_i} prod_{f in G} f])
  prefix closure (lemma 3):   after any checked committed prefix, MAX every remaining factor over its residual axes; the product is U(c) >= t(c)
  cap (lemma 4):              W_0(x) <= U(c(x)) r(x | c(x)) <= B q_C(c(x)) r(x | c(x)) with the accepted coarse machinery on the packed upper model (bound kind `target_over_actual_decoder`)
Arithmetic: nonnegative compact dyadics (NORMALIZED 128-bit integer mantissa in [2^127, 2^128), separate signed exponent; exact zero), stored as tuples (e, m) so that Python's lexicographic order IS the numeric order;
source rationals converted UPWARD; a group's product is EXACT (<= 16 x 128 = 2048 mantissa bits) and rounded upward ONCE per output entry; comparisons by (exponent, mantissa) after normalization; the independent stage
checker (`check_stage`) re-derives every valid local assignment from the inputs' own axis semantics and verifies dominance, the exact-once partition, class domains and padding zeros; the final packing (`pack_tables`)
rounds every table upward onto a common per-table dyadic exponent with <= 128-bit integer mantissas (a positive value below the quantum becomes one unit; zero stays zero; the inflation is reported, never assumed small).
Memory: every table is charged to the constructor account BEFORE allocation and OWNED by the compile object until it is released (consumed inputs after a committed stage; everything on refusal / interruption);
the stage peak (old prefix + new outputs + checker temporaries) is admitted before the stage starts. Deadline: polled per table / per 256 cells; ONE midpoint fixed at entry stops new MAX stages (the second
half of the allowance is reserved for closure, checking, packing, the coarse proposal, fine tables and sampler preparation)."""
import math, itertools, time, hashlib
from fractions import Fraction as F
import numpy as np
import coarse_envelope as CE

MBITS = 128; ZERO = (-(1 << 62), 0); TOP = 1 << MBITS; HALF = 1 << (MBITS - 1)
PROFILE_PRODUCTION = dict(V=4096, fanin=16, mantissa_bits=128); ORACLE_WIDTHS = (64, 256, 1024, 4096)
ENTRY_BYTES = 176                                                      # tuple (56) + two ints (<= 128-bit: 44 each) + object-array slot (8) + slack; the named-container estimate charged per entry
PACKED_ENTRY_BYTES = 52                                                # one <= 128-bit int (44) + object-array slot (8): the packed integer tables (DGP5: admitted before allocation)


class RefusedRMAX(Exception):
    def __init__(self, kind, reason): super().__init__(kind, reason); self.kind = kind; self.reason = reason


# ---------------------------------------------------------------- compact dyadics (e, m): value m 2^e; m == 0 exact zero; otherwise 2^127 <= m < 2^128
def norm_up(e, m):
    """upward normalization of a nonnegative (e, m) with an arbitrary-size mantissa onto exactly MBITS bits"""
    if m == 0: return ZERO
    bl = m.bit_length()
    if bl > MBITS:
        sh = bl - MBITS; q = m >> sh
        if q << sh != m: q += 1
        if q == TOP: q = HALF; sh += 1
        return (e + sh, q)
    if bl < MBITS: sh = MBITS - bl; return (e - sh, m << sh)
    return (e, m)


def from_fraction_up(q):
    """the smallest normalized compact dyadic >= the nonnegative rational q"""
    q = F(q)
    if q < 0: raise CE.Defect('negative source entry')
    if q == 0: return ZERO
    n, d = q.numerator, q.denominator; e = n.bit_length() - d.bit_length() - MBITS                  # n / d 2^-e has about MBITS bits
    for _ in range(3):
        num, den = (n << -e, d) if e < 0 else (n, d << e); m = -(-num // den)                        # ceiling
        bl = m.bit_length()
        if bl == MBITS: return (e, m)
        if bl == MBITS + 1 and m == TOP: return (e + 1, HALF)
        e += (bl - MBITS)
    return norm_up(e, m)


def to_fraction(x):
    e, m = x
    return F(m) * (F(2) ** e) if m else F(0)


def mul_exact(a, b):
    """exact product of two compact dyadics (mantissa up to 256 bits; NOT normalized)"""
    if a[1] == 0 or b[1] == 0: return ZERO
    return (a[0] + b[0], a[1] * b[1])


_mul = np.frompyfunc(mul_exact, 2, 1); _norm = np.frompyfunc(lambda x: norm_up(x[0], x[1]), 1, 1)
_mul_exact_frac = np.frompyfunc(lambda a, b: a * b, 2, 1); _ident = np.frompyfunc(lambda x: x, 1, 1)


class Arith:
    """the entry arithmetic: 'compact' (production: normalized 128-bit upward dyadics as (e, m)) or 'exact' (DIAGNOSTIC ONLY: Fractions, no rounding; oracle / controls)"""
    def __init__(self, mode):
        self.mode = mode
        if mode == 'compact': self.zero = ZERO; self.one = (0, 1); self.conv = from_fraction_up; self.mul = _mul; self.norm = _norm; self.is_zero = lambda x: x[1] == 0; self.to_frac = to_fraction; self.ge = ge_exact; self.mul1 = lambda a, b: norm_up(*mul_exact(a, b))
        elif mode == 'exact': self.zero = F(0); self.one = F(1); self.conv = F; self.mul = _mul_exact_frac; self.norm = _ident; self.is_zero = lambda x: x == 0; self.to_frac = F; self.ge = lambda a, b: a >= b; self.mul1 = lambda a, b: a * b
        else: raise CE.Defect('unknown arithmetic mode %r' % mode)
    def frac_prod(self, prod): return prod if self.mode == 'exact' else (F(prod[1]) * F(2) ** prod[0] if prod[1] else F(0))


def lead(x):
    """position of the leading bit of a nonnegative (e, m): value in [2^(lead - 1), 2^lead); None for zero"""
    return (x[0] + x[1].bit_length()) if x[1] else None


def log2_up(x):
    """float log2 of a positive (e, m) within 1 ulp of the mantissa's log2 (the exponent is exact): never a float of a huge rational"""
    return x[0] + math.log2(x[1])


def ge_exact(a, b):
    """a >= b for nonnegative (e, m) pairs with arbitrary-size mantissas. DGP5 repair (finding 1): the leading-bit positions decide first; only when they coincide is the mantissa shift performed, and that shift is
    then bounded by the mantissa bit lengths (never by the exponent gap)"""
    if b[1] == 0: return True
    if a[1] == 0: return False
    la, lb = lead(a), lead(b)
    if la != lb: return la > lb
    ea, ma = a; eb, mb = b
    return (ma << (ea - eb)) >= mb if ea >= eb else ma >= (mb << (eb - ea))


def sum_up(terms):
    """upward normalized sum of nonnegative (e, m) terms with a BOUNDED shift: terms are aligned to (lead_max - MBITS - 8); a term below that grid contributes its ceiling (at least one unit); the result is normalized upward"""
    terms = [t for t in terms if t[1]]
    if not terms: return ZERO
    L = max(lead(t) for t in terms); base = L - MBITS - 8; acc = 0
    for e, m in terms:
        sh = e - base
        if sh >= 0: acc += m << sh
        else:
            g = -sh; q = m >> g; rem = (m != 0) if g >= m.bit_length() else bool(m & ((1 << g) - 1))         # DGP7 repair R2: the remainder test never builds a mask wider than the mantissa (a 2^24 exponent gap allocated a 2 MiB temporary before)
            acc += q + (1 if rem else 0)
    return norm_up(base, acc)


# ---------------------------------------------------------------- tables: axes = sorted tuple of axis ids (2 v = class axis of v, 2 v + 1 = residual axis of v); arr = object array of (e, m) in axis order
class Table:
    __slots__ = ('axes', 'arr', 'tid', 'origin', 'bytes')
    def __init__(self, axes, arr, tid, origin):
        self.axes = tuple(axes); self.arr = arr; self.tid = tid; self.origin = origin; self.bytes = ENTRY_BYTES * int(arr.size) + 128
        assert tuple(sorted(self.axes)) == self.axes and len(set(self.axes)) == len(self.axes) and arr.ndim == len(self.axes), (self.axes, arr.shape)
    def volume(self): return int(self.arr.size)
    def residual_axes(self): return [a for a in self.axes if a & 1]
    def class_axes(self): return [a for a in self.axes if not (a & 1)]


def axis_size(a, ccards, pads): return ccards[a >> 1] if not (a & 1) else pads[a >> 1]


def broadcast_to(T, axes, ccards, pads):
    """view of T.arr aligned to the union `axes` (sorted superset of T.axes) for broadcasting"""
    shape = [axis_size(a, ccards, pads) if a in T.axes else 1 for a in axes]; return T.arr.reshape(shape)


def product_exact(tables, axes, ccards, pads, A=None):
    """exact (unnormalized) product of the tables over the union axes"""
    A = A or Arith('compact'); acc = None
    for T in tables:
        v = broadcast_to(T, axes, ccards, pads); acc = v if acc is None else A.mul(acc, v)
    shape = [axis_size(a, ccards, pads) for a in axes]
    return np.broadcast_to(acc, shape).copy() if acc.shape != tuple(shape) else acc


def max_over(arr, axes, drop):
    """upward-normalized array `arr` over `axes`; MAX over the axis ids in `drop` (lexicographic (e, m) order == numeric order on normalized entries; padded zeros never win against a valid entry)"""
    out = arr; cur = list(axes)
    for a in sorted(drop, reverse=True):
        k = cur.index(a); out = np.maximum.reduce(out, axis=k) if out.shape[k] > 1 else out.reshape([s for i, s in enumerate(out.shape) if i != k]); cur.pop(k)
    return out, tuple(cur)


# ---------------------------------------------------------------- the residual factorization (lemma 1): source tables over (c_v, s_v) axes with padding
def residual_sources(M, classes, Cz, rows, budget, clock, owned, A=None, V=None):
    """-> (tables, pads, members, support_refusal). Pairwise / higher factors: h_f(x) = vals / prod lambda (gauge residual, exactly as check_candidate); unaries: u_v(x) / r_v(x | c_v) (compensated unary over the
    ACTUAL dyadic decoder, once). Every table carries the class AND residual axis of each variable; invalid (c, s) positions are exact zeros. SUPPORT: a positive unary with zero decoder probability refuses."""
    A = A or Arith('compact'); n = len(M.cards); ccards = list(Cz.ccards); members = rows.members; pads = [max(len(members[v][c]) for c in range(ccards[v])) for v in range(n)]; tabs = []; tid = 0
    def pos_of(v):
        m = {}
        for c in range(ccards[v]):
            for s, a in enumerate(members[v][c]): m[a] = (c, s)
        return m
    posv = [pos_of(v) for v in range(n)]
    for fi, (sc, vals) in enumerate(M.factors):
        sc = tuple(sc); axes = tuple(sorted([2 * v for v in sc] + [2 * v + 1 for v in sc])); shape = [axis_size(a, ccards, pads) for a in axes]; vol = math.prod(shape)
        if V is not None and vol > V: raise RefusedRMAX('VOLUME', 'source table of factor %d (%d entries) exceeds the physical cap %d (refused BEFORE allocation)' % (fi, vol, V))      # DGP5 repair (finding 1): volume before allocation
        owned[0] += budget.charge(ENTRY_BYTES * vol + 128, 'residual source table of factor %d (%d entries)' % (fi, vol)); clock.poll('before residual source %d' % fi)
        arr = np.empty(shape, dtype=object); arr.fill(A.zero); fst = CE.strides([M.cards[v] for v in sc]); lams = [Cz.scales[(fi, ax)] for ax in range(len(sc))]
        for idx, x in enumerate(itertools.product(*(range(M.cards[v]) for v in sc))):
            h = vals[idx]
            if h > 0:
                for ax, a in enumerate(x): h = CE.checked_div(h, lams[ax][a])
            key = [0] * len(axes)
            for ax, v in enumerate(sc): c, s = posv[v][x[ax]]; key[axes.index(2 * v)] = c; key[axes.index(2 * v + 1)] = s
            arr[tuple(key)] = A.conv(h) if h > 0 else A.zero
            if (idx & 255) == 255: clock.poll('in residual source %d' % fi)
        tabs.append(Table(axes, arr, tid, ('factor', fi))); tid += 1
    for v in range(n):
        axes = (2 * v, 2 * v + 1); shape = [ccards[v], pads[v]]
        if V is not None and shape[0] * shape[1] > V: raise RefusedRMAX('VOLUME', 'unary ratio table of variable %d (%d entries) exceeds the physical cap %d (refused BEFORE allocation)' % (v, shape[0] * shape[1], V))
        owned[0] += budget.charge(ENTRY_BYTES * shape[0] * shape[1] + 128, 'residual unary ratio table of variable %d' % v)
        arr = np.empty(shape, dtype=object); arr.fill(A.zero)
        for c in range(ccards[v]):
            for s, a in enumerate(members[v][c]):
                u = Cz.u[v][a]
                if u == 0: continue
                r = F(rows.counts[(v, c)][s], rows.Q)
                if r == 0: raise RefusedRMAX('SUPPORT', 'positive unary mass of variable %d state %d has zero decoder probability' % (v, a))
                arr[c, s] = A.conv(CE.checked_div(u, r))
        tabs.append(Table(axes, arr, tid, ('unary_ratio', v))); tid += 1
    return tabs, pads, posv


def valid_mask(axes, ccards, pads, members):
    """boolean array over `axes`: True where every (c_v, s_v) pair present is a valid member position"""
    shape = [axis_size(a, ccards, pads) for a in axes]; ok = np.ones(shape, dtype=bool)
    for a in axes:
        if a & 1:
            v = a >> 1
            if 2 * v not in axes: continue
            ic, is_ = axes.index(2 * v), axes.index(a); m = np.zeros((ccards[v], pads[v]), dtype=bool)
            for c in range(ccards[v]): m[c, :len(members[v][c])] = True
            sh = [1] * len(axes); sh[ic] = ccards[v]; sh[is_] = pads[v]; ok &= m.reshape(sh)
    return ok


# ---------------------------------------------------------------- the compiler
class RMAXCompile:
    """one residual MAX compilation. Lifecycle: sources -> seeds -> stages (per residual variable in the admitted order; each transactional and CHECKED before commit) until the midpoint / completion -> closure -> packing.
    `owned[0]` = the live constructor-account bytes this object owns (released by `release_all`, or transferred to the stream exactly once by `transfer`)."""
    def __init__(self, M, classes, Cz, rows, profile, budget, clock, trace=None, arith='compact'):
        self.A = Arith(arith); self.M = M; self.classes = classes; self.Cz = Cz; self.rows = rows; self.V = int(profile['V']); self.fanin = int(profile['fanin']); assert profile.get('mantissa_bits', 128) == MBITS
        self.budget = budget; self.clock = clock; self.owned = [0]; self.n = len(M.cards); self.ccards = list(Cz.ccards); self.trace = trace if trace is not None else []
        self.active = []; self.plan = []; self.stages_done = 0; self.consumed_messages = 0; self.max_splits = 0; self.work_cells = 0; self.peak_owned = 0; self.closed = None; self.packed = None; self.constants = []
        self.refusals = []; self.midpoint = None; self.residual_order = None; self.seed_record = []; self.checker_receipts = []; self.sum_U_prefix0 = None
    def _bump(self): self.peak_owned = max(self.peak_owned, self.owned[0])
    def release_all(self):
        if self.owned[0]: self.budget.release(self.owned[0]); self.owned[0] = 0
    def transfer(self):
        """ownership of the live bytes passes to the caller exactly once"""
        n = self.owned[0]; self.owned[0] = 0; return n
    def _release_table(self, T): self.budget.release(T.bytes); self.owned[0] -= T.bytes
    # ---- phases
    def build_sources(self):
        self.active, self.pads, self.posv = residual_sources(self.M, self.classes, self.Cz, self.rows, self.budget, self.clock, self.owned, self.A, V=self.V); self._bump(); self.members = self.rows.members; self.next_tid = len(self.active)
        return self
    def build_seeds(self, groups):
        """repaired G2's deterministic groups as seed products with ALL class and residual axes retained; a seed exceeding the physical cap / fan-in keeps its constituent source factors"""
        byf = {T.origin: T for T in self.active if T.origin[0] == 'factor'}
        for g in groups:
            if len(g) < 2: continue
            ts = [byf[('factor', fi)] for fi in g]; axes = tuple(sorted(set(a for T in ts for a in T.axes))); vol = math.prod(axis_size(a, self.ccards, self.pads) for a in axes)
            if vol > self.V or len(ts) > self.fanin: self.seed_record.append(dict(group=list(g), joined=False, volume=vol)); continue
            self.clock.poll('before seed join %s' % (list(g),)); self.owned[0] += self.budget.charge(ENTRY_BYTES * vol + 128, 'seed product %s' % (list(g),)); self._bump()
            arr = self.A.norm(product_exact(ts, axes, self.ccards, self.pads, self.A)); self.work_cells += vol * len(ts); S = Table(axes, arr, self.next_tid, ('seed', tuple(g))); self.next_tid += 1
            receipt = check_stage(ts, S, None, self.ccards, self.pads, self.members, self.clock, self.A, inventory=[T.tid for T in self.active]); self.checker_receipts.append(receipt)
            if not receipt['ok']: self._release_table(S); raise CE.Defect('RMAX seed checker rejected the join %s: %s' % (list(g), receipt.get('why')))
            for T in ts: self.active.remove(T); self._release_table(T)
            self.active.append(S); self.seed_record.append(dict(group=list(g), joined=True, volume=vol, checked=receipt['ok']))
        return self
    def set_order(self):
        order, vols = CE.elimination_order(list(self.M.cards), [tuple(sc) for sc, _ in self.M.factors], self.clock, self.budget); self.residual_order = list(order); return self
    def stage(self, v):
        """one residual bucket: every active table with axis s_v; mini-buckets under BOTH caps; MAX over s_v (valid members only -- padding is zero); check; commit"""
        sv = 2 * v + 1; bucket = [T for T in self.active if sv in T.axes]
        if not bucket: self.plan.append(dict(v=v, groups=[], note='no active table carries s_v')); self.stages_done += 1; return
        bucket.sort(key=lambda T: (-T.volume(), T.tid)); groups = []
        for T in bucket:
            best = None
            for gi, (axes, mem) in enumerate(groups):
                u = tuple(sorted(set(axes) | set(T.axes))); vol = math.prod(axis_size(a, self.ccards, self.pads) for a in u)
                if vol <= self.V and len(mem) < self.fanin and (best is None or vol < best[0]): best = (vol, gi, u)
            if best is None:
                vol = T.volume()
                if vol > self.V: raise RefusedRMAX('VOLUME', 'an individual table (%s, %d entries) exceeds the physical cap %d' % (T.origin, vol, self.V))
                groups.append((T.axes, [T]))
            else: groups[best[1]] = (best[2], groups[best[1]][1] + [T])
        if len(groups) > 1: self.max_splits += len(groups) - 1
        part = check_partition([T.tid for T in bucket], [[T.tid for T in mem] for _, mem in groups])
        if not part['ok']: raise CE.Defect('RMAX stage s_%d: bucket partition: %s' % (v, part['why']))                 # DGP5 (finding 2): the groups are an exact-once partition of the bucket
        # admit the stage's temporary peak (every output + the checker's product workspace) BEFORE building
        out_bytes = sum(ENTRY_BYTES * math.prod(axis_size(a, self.ccards, self.pads) for a in u if a != sv) + 128 for u, _ in groups); peak_extra = max(ENTRY_BYTES * math.prod(axis_size(a, self.ccards, self.pads) for a in u) * 2 for u, _ in groups)
        self.owned[0] += self.budget.charge(out_bytes + peak_extra, 'RMAX stage s_%d outputs + workspace' % v); self._bump(); self.budget.release(peak_extra); self.owned[0] -= peak_extra
        outs = []; rec = dict(v=v, groups=[])
        try:
            for u, mem in groups:
                self.clock.poll('before MAX group of s_%d' % v); P = self.A.norm(product_exact(mem, u, self.ccards, self.pads, self.A)); self.work_cells += math.prod(axis_size(a, self.ccards, self.pads) for a in u) * len(mem)
                # restrict the MAX to valid members of c_v: padded positions are exact zeros by construction (sources) and by induction (products of zeros); the checker verifies this
                R, raxes = max_over(P, u, [sv]); T = Table(raxes, R, self.next_tid, ('message', v, tuple(t.tid for t in mem))); self.next_tid += 1
                receipt = check_stage(mem, T, sv, self.ccards, self.pads, self.members, self.clock, self.A, inventory=[T_.tid for T_ in self.active], bucket_ids=[T_.tid for T_ in bucket]); self.checker_receipts.append(receipt)
                if not receipt['ok']: raise CE.Defect('RMAX stage checker rejected the message of s_%d: %s' % (v, receipt))
                outs.append(T); rec['groups'].append(dict(inputs=[t.tid for t in mem], input_origins=[t.origin for t in mem], union_axes=list(u), output=T.tid, output_axes=list(raxes), volume=int(P.size), consumed_messages=sum(1 for t in mem if t.origin[0] == 'message')))
        except BaseException:
            for T in outs: self._release_table(T)
            self.budget.release(max(0, out_bytes - sum(T.bytes for T in outs))); self.owned[0] -= max(0, out_bytes - sum(T.bytes for T in outs)); raise
        # commit: consumed inputs released, outputs active
        self.budget.release(max(0, out_bytes - sum(T.bytes for T in outs))); self.owned[0] -= max(0, out_bytes - sum(T.bytes for T in outs))
        for T in bucket: self.active.remove(T); self._release_table(T)
        self.consumed_messages += sum(g['consumed_messages'] for g in rec['groups']); self.active.extend(outs); self.plan.append(rec); self.stages_done += 1
    def run_stages(self, midpoint):
        """MAX stages in the admitted residual order while tnow() < midpoint (ONE fixed midpoint; a stage that has started runs to its own check / commit or is discarded by its deadline poll)"""
        self.midpoint = midpoint
        for v in self.residual_order:
            if CE.tnow() >= midpoint: self.refusals.append('midpoint reached before s_%d (prefix depth %d of %d)' % (v, self.stages_done, self.n)); break
            self.stage(v)
        return self
    def closure(self):
        """MAX every remaining table over its residual axes (lemma 3); the product of the closed tables is U(c). DGP5 repair (finding 1): entry poll; every reduced array ADMITTED before allocation (released on failure);
        finding 2: the closed inventory is exactly the active inventory (checked by check_closure_inventory)"""
        self.clock.poll('at the closure entry'); closed = []; charged = 0
        try:
            for T in self.active:
                self.clock.poll('before closure of table %d' % T.tid); ra = T.residual_axes()
                if ra:
                    vol = math.prod(axis_size(a, self.ccards, self.pads) for a in T.axes if a not in ra); n = self.budget.charge(ENTRY_BYTES * vol + 128, 'closed table %d (%d entries)' % (T.tid, vol)); charged += n; self.owned[0] += n; self._bump()
                    R, raxes = max_over(T.arr, T.axes, ra); self.work_cells += T.volume()
                else: R, raxes = T.arr, T.axes
                closed.append(Table(raxes, R, T.tid, ('closed', T.origin)))
            inv = check_closure_inventory(self.active, closed)
            if not inv['ok']: raise CE.Defect('closure inventory: %s' % inv['why'])
            self.checker_receipts.append(dict(inv, cells=0, kind='closure_inventory'))
        except BaseException:
            self.budget.release(charged); self.owned[0] -= charged; raise
        self.closed_bytes = charged; self.closed = closed; self.clock.poll('at the closure exit'); return self
    def sum_U(self, tables=None):
        """exact sum over coarse states of the product of the closed tables (oracle / controls; the oracle cap on the enumeration volume applies)"""
        tables = self.closed if tables is None else tables; vol = math.prod(self.ccards)
        if vol > 1 << 16: return None
        tot = F(0)
        for c in itertools.product(*[range(k) for k in self.ccards]): tot += self.U_at(c, tables)
        return tot
    def U_at(self, c, tables=None):
        tables = self.closed if tables is None else tables; w = F(1)
        for T in tables:
            if not T.axes: w *= self.A.to_frac(T.arr.reshape(-1)[0]); continue
            idx = tuple(c[a >> 1] for a in T.axes); w *= self.A.to_frac(T.arr[idx])
            if w == 0: return F(0)
        for k in self.constants: w *= self.A.to_frac(k)
        return w
    def pack(self):
        """every closed table -> a common per-table dyadic exponent E_t and integer mantissas <= MBITS bits, rounded UPWARD (a positive entry below the quantum becomes 1; zero stays 0); nullary tables become constants
        folded into the smallest coarse table (stable id); inflation reported per table and in total"""
        if self.A.mode != 'compact': raise CE.Defect('packing is defined for the compact production arithmetic only')
        self.clock.poll('at the packing entry')                                                                           # DGP5 repair (finding 1): an expired clock refuses at entry; polls per 256 entries; arrays admitted before allocation
        packed = []; consts = []; infl = []; charged = 0
        try:
            for T in self.closed:
                if not T.axes: consts.append(T.arr.reshape(-1)[0]); continue
                n = self.budget.charge(PACKED_ENTRY_BYTES * T.volume() + 128, 'packed table %d (%d entries)' % (T.tid, T.volume())); charged += n; self.owned[0] += n; self._bump()
                flat = T.arr.reshape(-1); leads = [e + m.bit_length() for e, m in flat if m]
                if not leads: packed.append(dict(axes=T.axes, E=0, ints=np.zeros(T.arr.shape, dtype=object), tid=T.tid, origin=T.origin)); infl.append(dict(tid=T.tid, max_ratio_log2=0.0, sum_ratio_log2=0.0)); continue
                E = max(leads) - MBITS; ints = np.empty(T.arr.shape, dtype=object); worst_log2 = 0.0; lead_old = max(leads); acc_old = 0.0; acc_new = 0.0
                for k_, idx in enumerate(itertools.product(*[range(k) for k in T.arr.shape])):
                    e, m = T.arr[idx]
                    if m == 0: ints[idx] = 0; continue
                    sh = e - E; q = (m << sh) if sh >= 0 else -((-m) >> (-sh))                             # ceiling for right shifts (sh >= -(lead gap) is bounded by the table's own leading-bit spread... a tiny entry becomes one unit)
                    if q == 0: q = 1
                    ints[idx] = int(q)
                    # BOUNDED diagnostics (finding 1): log2 ratios from the exponent (exact integer) + log2 of a <= 128-bit mantissa; sums in a scaled float accumulator relative to the table's leading bit (never a Fraction of a huge power of two)
                    lo_old = e + math.log2(m); lo_new = E + math.log2(q); worst_log2 = max(worst_log2, lo_new - lo_old); acc_old += 2.0 ** max(lo_old - lead_old, -1000.0); acc_new += 2.0 ** max(lo_new - lead_old, -1000.0)
                    if (k_ & 255) == 255: self.clock.poll('in packing table %d' % T.tid)
                packed.append(dict(axes=T.axes, E=E, ints=ints, tid=T.tid, origin=T.origin)); infl.append(dict(tid=T.tid, max_ratio_log2=float(worst_log2), sum_ratio_log2=float(math.log2(acc_new / acc_old)) if acc_old > 0 else 0.0))
        except BaseException:
            self.budget.release(charged); self.owned[0] -= charged; raise
        self.packed_bytes = charged
        if consts:
            k = ZERO if any(x[1] == 0 for x in consts) else (0, 1)
            for x in consts: k = norm_up(*mul_exact(k, x)) if k != ZERO else ZERO
            self.constants = [k]
            if packed:
                j = min(range(len(packed)), key=lambda i: (len(packed[i]['axes']), packed[i]['tid'])); P = packed[j]; e, m = k
                if m == 0: P['ints'] = np.zeros(P['ints'].shape, dtype=object)
                else: P['ints'] = np.array([int(x) * m for x in P['ints'].reshape(-1)], dtype=object).reshape(P['ints'].shape); P['E'] += e; P['folded_constant'] = (e, m)
        self.packed = packed; self.packing = dict(tables=infl, max_ratio_log2=max([x['max_ratio_log2'] for x in infl], default=0.0), sum_ratio_log2_max=max([x['sum_ratio_log2'] for x in infl], default=0.0), nullary_folded=len(consts), diagnostics='bounded log2 (exponent + log2 of <= 128-bit mantissa); DGP5 repair of finding 1'); self.clock.poll('at the packing exit'); return self
    def packed_upper_weight(self, c):
        """exact U_packed(c) from the packed integer tables (the quantity the coarse proposal bounds)"""
        w = F(1)
        for P in self.packed:
            idx = tuple(c[a >> 1] for a in P['axes']); w *= F(int(P['ints'][idx])) * F(2) ** P['E']
            if w == 0: return F(0)
        return w
    def record(self):
        return dict(bound_kind='target_over_actual_decoder', arith=self.A.mode, profile=dict(V=self.V, fanin=self.fanin, mantissa_bits=MBITS), n_fine=self.n, coarse_cards=self.ccards, pads=self.pads, residual_order=self.residual_order, stages_done=self.stages_done, stages_total=self.n, prefix_complete=(self.stages_done == self.n),
                    consumed_messages=self.consumed_messages, max_splits=self.max_splits, work_cells=self.work_cells, seeds=self.seed_record, plan=self.plan, refusals=self.refusals, checker=dict(stages_checked=len(self.checker_receipts), all_ok=all(r['ok'] for r in self.checker_receipts), cells_checked=sum(r['cells'] for r in self.checker_receipts)),
                    closed_tables=[dict(tid=T.tid, axes=list(T.axes), volume=T.volume(), origin=str(T.origin)) for T in (self.closed or [])], packing=getattr(self, 'packing', None), peak_owned_bytes=self.peak_owned, closed_bytes=getattr(self, 'closed_bytes', 0), packed_bytes=getattr(self, 'packed_bytes', 0), plan_sha256=hashlib.sha256(repr((self.residual_order, [(p.get('v'), [(g['inputs'], g['union_axes']) for g in p.get('groups', [])]) for p in self.plan], self.seed_record, self.V, self.fanin)).encode()).hexdigest())


# ---------------------------------------------------------------- the independent stage checker
def check_inventory(inputs, output, inventory=None, bucket_ids=None, eliminated_axis=None):
    """DGP5 repair (finding 2): the EXACT-ONCE inventory conditions of one derivation step, independent of the producer -- (a) the input ids are pairwise distinct; (b) every input id is a member of the active
    inventory the step consumes from; (c) the output id is NOT in that inventory (no reuse of a consumed or live id); (d) the output's recorded origin names exactly the input ids (messages / seeds); (e) when the
    bucket is given (a stage), the inputs are exactly one group of a partition of that bucket: a subset, and every input carries the eliminated axis"""
    ids = [T.tid for T in inputs]
    if len(set(ids)) != len(ids): return dict(ok=False, why='duplicate input id(s) %s' % sorted({i for i in ids if ids.count(i) > 1}))
    if inventory is not None:
        inv = set(inventory)
        if len(inv) != len(list(inventory)): return dict(ok=False, why='the active inventory itself carries a duplicate id')
        missing = [i for i in ids if i not in inv]
        if missing: return dict(ok=False, why='input id(s) %s are not in the active inventory' % missing)
        if output.tid in inv: return dict(ok=False, why='output id %d reuses a live inventory id' % output.tid)
    if output.tid in ids: return dict(ok=False, why='output id %d equals an input id' % output.tid)
    og = output.origin
    if og and og[0] in ('message', 'sum_message', 'max_message', 'seed', 'joint', 'retained') and len(og) >= 3 and isinstance(og[-1], tuple) and tuple(og[-1]) != tuple(ids): return dict(ok=False, why='output origin %s does not name the input ids %s' % (og, ids))
    if bucket_ids is not None:
        bset = set(bucket_ids)
        if not set(ids) <= bset: return dict(ok=False, why='inputs %s are not a subset of the bucket %s' % (ids, sorted(bset)))
        if eliminated_axis is not None and any(eliminated_axis not in T.axes for T in inputs): return dict(ok=False, why='an input does not carry the eliminated axis %d' % eliminated_axis)
    return dict(ok=True)


def check_partition(bucket_ids, group_ids):
    """finding 2: the groups of one elimination step consume every bucket table EXACTLY once (no omission, no duplication across or inside groups)"""
    flat = [i for g in group_ids for i in g]
    if sorted(flat) != sorted(bucket_ids): return dict(ok=False, why='groups %s are not an exact-once partition of the bucket %s' % (group_ids, sorted(bucket_ids)))
    if len(set(flat)) != len(flat): return dict(ok=False, why='an id appears twice across the groups %s' % group_ids)
    return dict(ok=True)


def check_closure_inventory(active, closed):
    """finding 2: the closed inventory is exactly the active inventory, each id exactly once, each closed table carrying exactly its source's class axes"""
    a_ids = [T.tid for T in active]; c_ids = [T.tid for T in closed]
    if len(set(a_ids)) != len(a_ids) or len(set(c_ids)) != len(c_ids): return dict(ok=False, why='duplicate ids in active %s / closed %s' % (a_ids, c_ids))
    if sorted(a_ids) != sorted(c_ids): return dict(ok=False, why='closed ids %s != active ids %s' % (sorted(c_ids), sorted(a_ids)))
    by = {T.tid: T for T in active}
    for C in closed:
        if tuple(C.axes) != tuple(by[C.tid].class_axes()): return dict(ok=False, why='closed table %d axes %s != its source class axes %s' % (C.tid, C.axes, by[C.tid].class_axes()))
    return dict(ok=True)


def check_stage(inputs, output, eliminated_axis, ccards, pads, members, clock, A=None, inventory=None, bucket_ids=None):
    """INDEPENDENT of the producer's broadcasting: for EVERY assignment of the union axes it indexes each input by that input's own axes, forms the EXACT product (<= 16 x 128 mantissa bits), and verifies
    (i) the output entry (at the assignment restricted to the output axes) dominates it; (ii) invalid (c_v, s_v) positions of the inputs are exact zeros; (iii) the output carries exactly the union minus the eliminated
    axis; (iv) the fan-in and class domains; (v) DGP5 (finding 2): the exact-once inventory conditions (check_inventory: distinct input ids bound to the active inventory, a fresh output id, the origin naming the
    inputs, one group of the bucket partition). Returns a receipt (ok, cells, worst slack in bits). Polled at entry and per 256 cells."""
    A = A or Arith('compact'); clock.poll('at the stage checker entry'); union = tuple(sorted(set(a for T in inputs for a in T.axes))); expect = tuple(a for a in union if a != eliminated_axis)
    inv = check_inventory(inputs, output, inventory, bucket_ids, eliminated_axis)
    if not inv['ok']: return dict(ok=False, why='inventory: ' + inv['why'], cells=0)
    if tuple(output.axes) != expect: return dict(ok=False, why='output axes %s != union minus eliminated %s' % (output.axes, expect), cells=0)
    if len(inputs) > 16: return dict(ok=False, why='fan-in %d > 16' % len(inputs), cells=0)
    sizes = [axis_size(a, ccards, pads) for a in union]; opos = [union.index(a) for a in output.axes]; ipos = [[union.index(a) for a in T.axes] for T in inputs]; cells = 0; worst = None
    for T in inputs:                                                                                   # invariant: a table carrying a residual axis s_w carries its class axis c_w (sources by construction; messages keep every class axis)
        for a in T.axes:
            if (a & 1) and (a - 1) not in T.axes: return dict(ok=False, why='input %d carries the residual axis of variable %d without its class axis' % (T.tid, a >> 1), cells=0)
    pairs = [[(T.axes.index(a - 1), T.axes.index(a), a >> 1) for a in T.axes if a & 1] for T in inputs]  # per INPUT: (class position, residual position, variable) of every residual axis IT carries
    for idx, asg in enumerate(itertools.product(*[range(s) for s in sizes])):
        prod = A.one
        for T, pp, prs in zip(inputs, ipos, pairs):
            key = tuple(asg[p] for p in pp); x = T.arr[key]
            if (not A.is_zero(x)) and any(key[js] >= len(members[w][key[jc]]) for jc, js, w in prs): return dict(ok=False, why='nonzero entry at an invalid (class, residual) position in input %d' % T.tid, cells=cells)   # validity restricted to the input's OWN axes
            if A.is_zero(x): prod = A.zero; break
            prod = (prod[0] + x[0], prod[1] * x[1]) if A.mode == 'compact' else prod * x
        o = output.arr[tuple(asg[p] for p in opos)]
        if not A.ge(o, prod): return dict(ok=False, why='output does not dominate the exact product at %s' % (asg,), cells=cells)
        if A.mode == 'compact' and prod[1] and o[1]:
            sl = (o[0] + o[1].bit_length()) - (prod[0] + prod[1].bit_length())
            if worst is None or sl > worst: worst = sl
        cells += 1
        if (idx & 255) == 255: clock.poll('in the RMAX stage checker')
    return dict(ok=True, cells=cells, max_slack_bits_upper=worst, eliminated=eliminated_axis, inputs=[T.tid for T in inputs], output=output.tid)


def check_packing(closed, packed, clock=None):
    """every packed integer entry dominates the closed compact entry (exact, GUARDED comparison: no Fraction of a huge power of two), zeros preserved, positive entries positive; DGP5 (finding 2): the packed inventory
    is exactly the closed non-nullary inventory (each id once); finding 1: polled at entry and per 256 entries when a clock is given"""
    if clock is not None: clock.poll('at the packing checker entry')
    c_ids = [T.tid for T in closed if T.axes]; p_ids = [P['tid'] for P in packed]
    if len(set(p_ids)) != len(p_ids) or sorted(p_ids) != sorted(c_ids): return dict(ok=False, why='packed ids %s != closed ids %s' % (sorted(p_ids), sorted(c_ids)))
    byid = {P['tid']: P for P in packed}; k_ = 0
    for T in closed:
        if not T.axes: continue
        P = byid[T.tid]
        if tuple(P['axes']) != tuple(T.axes) or tuple(P['ints'].shape) != tuple(T.arr.shape): return dict(ok=False, why='packed table %d axes / shape differ from the closed table' % T.tid)
        for idx in itertools.product(*[range(k) for k in T.arr.shape]):
            e, m = T.arr[idx]; q = int(P['ints'][idx]); k_ += 1
            if (m == 0) != (q == 0): return dict(ok=False, why='zero / positive mismatch at %s of table %d' % (idx, T.tid))
            if m and not ge_exact((P['E'], q), (e, m)): return dict(ok=False, why='packed entry below the closed value at %s of table %d' % (idx, T.tid))
            if clock is not None and (k_ & 255) == 255: clock.poll('in the packing checker')
    return dict(ok=True, entries=k_)


# ---------------------------------------------------------------- oracle / control helpers (exact rationals; tiny models only)
def exact_t(M, classes, Cz, rows, cap=1 << 16):
    """t(c) = max_{x in c} W_0(x) / r(x | c) on every coarse state by enumeration (W_0 WITHOUT the scalar), T = sum t"""
    n = len(M.cards)
    if math.prod(M.cards) > cap: raise CE.Refused('ENUM', 'enumeration cap')
    t = {}
    for z in itertools.product(*[range(k) for k in M.cards]):
        w = F(1)
        for v, a in enumerate(z): w *= M.psi[v][a]
        for sc, vals in M.factors:
            idx = 0
            for x in sc: idx = idx * M.cards[x] + z[x]
            w *= vals[idx]
        if w == 0: continue
        c = tuple(classes[v][z[v]] for v in range(n)); r = F(1)
        for v in range(n): r *= F(rows.counts[(v, c[v])][rows.members[v][c[v]].index(z[v])], rows.Q)
        val = w / r
        if val > t.get(c, F(0)): t[c] = val
    return t, sum(t.values())


def enumerate_check_rmax(M, classes, Cz, rows, upper_fn, cap=1 << 16):
    """the DGP4 assertion W_0(z) <= U(c(z)) r(z | c(z)) on EVERY fine state (W_0 without the scalar); returns the worst log2 slack"""
    n = len(M.cards)
    if math.prod(M.cards) > cap: raise CE.Refused('ENUM', 'enumeration cap')
    worst = None; zero = 0
    for z in itertools.product(*[range(k) for k in M.cards]):
        w = F(1)
        for v, a in enumerate(z): w *= M.psi[v][a]
        for sc, vals in M.factors:
            idx = 0
            for x in sc: idx = idx * M.cards[x] + z[x]
            w *= vals[idx]
        c = tuple(classes[v][z[v]] for v in range(n)); r = F(1)
        for v in range(n): r *= F(rows.counts[(v, c[v])][rows.members[v][c[v]].index(z[v])], rows.Q)
        U = upper_fn(c)
        if w > U * r: raise CE.Defect('RMAX envelope violated at %s: W_0 %s > U r %s' % (z, w, U * r))
        if w == 0: zero += 1
        elif U * r > 0:
            sl = math.log2(float(U * r / w)) if (U * r / w).numerator.bit_length() < 1000 else 999.0
            if worst is None or sl < worst: worst = sl
    return dict(ok=True, zero_weight_states=zero, min_log2_slack=worst)
