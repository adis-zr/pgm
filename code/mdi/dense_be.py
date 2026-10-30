"""Dense junction-tree contraction with a pluggable value algebra (spec §11).

This is the CHECKER's own aggregation. It differs from the producer's sparse
contraction (`sparse_jt`) in data layout (dense flat arrays over bag domains,
UAI stride order), in schedule construction (the validated min-fill bag tree
from `plan.build_plan`, a permitted shared structural primitive), and in code.
It differs from `contract.Engine` in carrying exact values -- rationals,
exact-endpoint intervals, complex rectangles or statistic distributions --
rather than MPFR points with depth labels.

Statistic insertion follows §7.1: a variable's integer statistic is inserted
exactly once, at the point where that variable is summed out (or kept for
readout), so along every root-to-readout path each variable is inserted once.
"""
from __future__ import annotations
import sys
sys.set_int_max_str_digits(0)
from fractions import Fraction as Fr
from mdi import config as K, plan as P, model as M
from mdi.sparse_jt import stat_add, _bits_ok


class DenseError(Exception):
    pass


class _ScopeShell:
    """Scope and cardinality only: what the validated bag-tree builder needs.
    It never allocates a table."""
    __slots__ = ("scope", "card", "origin", "table")

    def __init__(self, scope, card, origin):
        self.scope = tuple(scope)
        self.card = tuple(card)
        self.origin = origin
        self.table = None


def _strides(card):
    st = [1] * len(card)
    acc = 1
    for k in range(len(card) - 1, -1, -1):
        st[k] = acc
        acc *= card[k]
    return st


# ----------------------------------------------------------------- algebras

class RationalAlg:
    name = "rational"
    zero = Fr(0)

    @staticmethod
    def one():
        return Fr(1)

    @staticmethod
    def mul(a, b):
        return a * b

    @staticmethod
    def add(a, b):
        return a + b

    @staticmethod
    def is_zero(a):
        return a == 0

    @staticmethod
    def check(a, cap):
        if not _bits_ok(a, cap):
            raise DenseError("a rational reached %d bits, above the %d-bit cap"
                             % (max(a.numerator.bit_length(),
                                    a.denominator.bit_length()), cap))

    @staticmethod
    def shift(a, s):
        return a


class IntervalAlg:
    name = "interval"
    zero = (Fr(0), Fr(0))

    @staticmethod
    def one():
        return (Fr(1), Fr(1))

    @staticmethod
    def mul(a, b):
        return (a[0] * b[0], a[1] * b[1])

    @staticmethod
    def add(a, b):
        return (a[0] + b[0], a[1] + b[1])

    @staticmethod
    def is_zero(a):
        return a[1] == 0

    @staticmethod
    def check(a, cap):
        for q in a:
            if not _bits_ok(q, cap):
                raise DenseError("an interval endpoint reached %d bits, above "
                                 "the %d-bit cap"
                                 % (max(q.numerator.bit_length(),
                                        q.denominator.bit_length()), cap))

    @staticmethod
    def shift(a, s):
        return a


class ComplexAlg:
    """Rectangles (re_lo, re_hi, im_lo, im_hi); the product is the hull of
    the corner products, computed HERE (not via collective._cmul) so the
    checker's complex arithmetic is its own."""
    name = "complex"
    zero = (Fr(0), Fr(0), Fr(0), Fr(0))

    @staticmethod
    def one():
        return (Fr(1), Fr(1), Fr(0), Fr(0))

    @staticmethod
    def mul(a, b):
        arl, arh, ail, aih = a
        brl, brh, bil, bih = b
        rr = (arl * brl, arl * brh, arh * brl, arh * brh)
        ii = (ail * bil, ail * bih, aih * bil, aih * bih)
        ri = (arl * bil, arl * bih, arh * bil, arh * bih)
        ir = (ail * brl, ail * brh, aih * brl, aih * brh)
        return (min(rr) - max(ii), max(rr) - min(ii),
                min(ri) + min(ir), max(ri) + max(ir))

    @staticmethod
    def add(a, b):
        return (a[0] + b[0], a[1] + b[1], a[2] + b[2], a[3] + b[3])

    @staticmethod
    def is_zero(a):
        return a[0] == a[1] == a[2] == a[3] == 0

    @staticmethod
    def check(a, cap):
        for q in a:
            if not _bits_ok(q, cap):
                raise DenseError("a complex corner reached %d bits, above the "
                                 "%d-bit cap"
                                 % (max(q.numerator.bit_length(),
                                        q.denominator.bit_length()), cap))

    @staticmethod
    def shift(a, s):
        return a


class StatAlg:
    """Values are {statistic: exact mass}; statistics are integers or tuples
    (one per mode). The product convolves, the sum adds pointwise, and
    `shift` adds a variable's statistic to every key."""
    name = "statistic"

    @staticmethod
    def size(a):
        return len(a)

    def __init__(self, support_cap, rank=1):
        self.support_cap = support_cap
        self.rank = rank
        self.zero = {}

    def one(self):
        return {(0,) * self.rank if self.rank > 1 else 0: Fr(1)}

    def mul(self, a, b):
        out = {}
        for sa, wa in a.items():
            for sb, wb in b.items():
                k = stat_add(sa, sb)
                if k not in out and len(out) >= self.support_cap:
                    raise DenseError("a convolved statistic support reached "
                                     "the %d cap" % self.support_cap)
                out[k] = out.get(k, Fr(0)) + wa * wb
        return out

    def add(self, a, b):
        out = dict(a)
        for s, w in b.items():
            out[s] = out.get(s, Fr(0)) + w
        if len(out) > self.support_cap:
            raise DenseError("a summed statistic support reached the %d cap"
                             % self.support_cap)
        return out

    @staticmethod
    def is_zero(a):
        return not a

    @staticmethod
    def check(a, cap):
        for w in a.values():
            if not _bits_ok(w, cap):
                raise DenseError("a statistic mass reached %d bits, above the "
                                 "%d-bit cap"
                                 % (max(w.numerator.bit_length(),
                                        w.denominator.bit_length()), cap))

    @staticmethod
    def shift(a, s):
        return {stat_add(k, s): w for k, w in a.items()}


# ------------------------------------------------------------ the engine

class DenseJT:
    """`factors`: list of (scope tuple, dense value list in UAI stride order).
    `card`: {var: cardinality}. `alg`: a value algebra. `stat_insert`:
    {var: [statistic per state]} for StatAlg."""

    def __init__(self, factors, card, alg=RationalAlg, deadline=None,
                 entry_cap=None, bit_cap=None, stat_insert=None, order=None,
                 charge=None):
        self.card = dict(card)
        self.alg = alg
        self.deadline = deadline
        self.charge = charge          # charge(n) every 64 entries visited
        self._visited = 0
        self.entry_cap = entry_cap or K.CAPS["local_mass_entries"]
        self.bit_cap = bit_cap or K.CAPS["rational_bit_length"]
        self.stat_insert = stat_insert
        self.ops = {"mul": 0, "add": 0}
        self.peak_live_entries = 0
        free = sorted({v for sc, _t in factors for v in sc})
        # the validated bag tree (a permitted shared structural primitive)
        shells = []
        for sc, tab in factors:
            sc = tuple(sc)
            cd = tuple(self.card[v] for v in sc)
            n = 1
            for c in cd:
                n *= c
            if len(tab) != n:
                raise DenseError("dense table over %s has %d entries, domain %d"
                                 % (sc, len(tab), n))
            # a SCOPE shell for the bag-tree builder: no dummy dense table
            shells.append(_ScopeShell(sc, cd, len(shells)))
        adj = P.primal_graph(free, self.card, shells)
        if order is None:
            order = P.order_min_fill(free, self.card, adj)
        self.plan = P.build_plan("checker_min_fill", list(order), free,
                                 self.card, shells)
        for b in self.plan.bags:
            if b.domain(self.card) > self.entry_cap:
                raise DenseError("bag %s has domain %d, above the %d-entry cap"
                                 % (b.vars, b.domain(self.card), self.entry_cap))
        # dense lists are copied; a LazyTable (compact view) is kept as is and
        # indexed by flat offset inside the bag loops
        self.tables = [(tuple(sc), tab if hasattr(tab, "at_digits") else list(tab))
                       for sc, tab in factors]
        self.msg = {}
        self.root_total = {}

    def rebind(self, factors):
        """Replace table contents keeping scopes and the validated bag tree."""
        if len(factors) != len(self.tables):
            raise DenseError("rebind: table count changed")
        new = []
        for (sc_old, _t), (sc, tab) in zip(self.tables, factors):
            if tuple(sc_old) != tuple(sc):
                raise DenseError("rebind: table scope changed")
            new.append((tuple(sc), tab if hasattr(tab, "at_digits") else list(tab)))
        self.tables = new
        self.msg = {}
        self.root_total = {}
        self._belief = {}
        return self

    def _tick(self, k):
        self._visited += 1
        if self.charge is not None and (self._visited & 0x3F) == 0:
            self.charge(64)
        if self.deadline is not None and (k & 0xFF) == 0:
            self.deadline()

    def _product_table(self, bidx, exclude):
        """Dense product over the bag of owned tables and incoming messages
        (all neighbours except `exclude`), as a flat list."""
        A = self.alg
        b = self.plan.bags[bidx]
        bvars = b.vars
        bcard = [self.card[v] for v in bvars]
        bst = _strides(bcard)
        bpos = {v: k for k, v in enumerate(bvars)}
        n = 1
        for c in bcard:
            n *= c
        parts = []
        for fi in b.factors:
            sc, tab = self.tables[fi]
            st = _strides([self.card[v] for v in sc])
            parts.append(([(bpos[v], st[k]) for k, v in enumerate(sc)], tab))
        nbs = ([b.parent] if b.parent >= 0 else []) + list(b.children)
        for nb in nbs:
            if nb == exclude:
                continue
            m = self.msg.get((nb, bidx))
            if m is None:
                raise DenseError("missing message %d->%d" % (nb, bidx))
            sc, tab = m
            st = _strides([self.card[v] for v in sc])
            parts.append(([(bpos[v], st[k]) for k, v in enumerate(sc)], tab))
        out = [None] * n
        digits = [0] * len(bvars)
        for flat in range(n):
            self._tick(flat)
            rem = flat
            for k in range(len(bvars)):
                digits[k] = rem // bst[k]
                rem %= bst[k]
            val = A.one()
            dead = False
            for proj, tab in parts:
                off = 0
                for bk, s in proj:
                    off += digits[bk] * s
                e = tab[off]
                if A.is_zero(e):
                    dead = True
                    break
                self.ops["mul"] += 1
                val = A.mul(val, e)
            if dead:
                out[flat] = A.zero
                continue
            A.check(val, self.bit_cap)
            out[flat] = val
        return bvars, bcard, bst, out

    def _sum_to(self, bvars, bcard, bst, vals, keep):
        """Sum the dense bag table down to the variables `keep` (a subset of
        bvars, in sorted order), inserting the statistic of every variable
        summed out."""
        A = self.alg
        keep = tuple(keep)
        kcard = [self.card[v] for v in keep]
        kst = _strides(kcard)
        kpos = [(bvars.index(v), kst[k]) for k, v in enumerate(keep)]
        gone = [(k, v) for k, v in enumerate(bvars) if v not in set(keep)]
        n = 1
        for c in kcard:
            n *= c
        out = [A.zero] * n
        seen = [False] * n
        digits = [0] * len(bvars)
        for flat, val in enumerate(vals):
            if A.is_zero(val):
                continue
            self._tick(flat)
            rem = flat
            for k in range(len(bvars)):
                digits[k] = rem // bst[k]
                rem %= bst[k]
            if self.stat_insert is not None:
                for k, v in gone:
                    val = A.shift(val, self.stat_insert[v][digits[k]])
            off = 0
            for bk, s in kpos:
                off += digits[bk] * s
            if seen[off]:
                self.ops["add"] += 1
                val = A.add(out[off], val)
            A.check(val, self.bit_cap)
            out[off] = val
            seen[off] = True
        return keep, out

    def _note_live(self):
        sz = getattr(self.alg, "size", None)
        tabs = [t for _sc, t in self.msg.values()] + \
            [b[3] for b in getattr(self, "_belief", {}).values()]
        if sz is None:
            e = sum(len(t) for t in tabs)
        else:
            e = sum(sum(sz(x) for x in t if not self.alg.is_zero(x)) for t in tabs)
        if e > self.peak_live_entries:
            self.peak_live_entries = e

    def release_belief(self, bidx):
        getattr(self, "_belief", {}).pop(bidx, None)

    def run(self, downward=True):
        bags = self.plan.bags
        roots = [b.idx for b in bags if b.parent < 0]
        for rt in roots:
            seq, stack = [], [rt]
            while stack:
                x = stack.pop()
                seq.append(x)
                stack.extend(bags[x].children)
            for bidx in reversed(seq):
                b = bags[bidx]
                bvars, bcard, bst, vals = self._product_table(bidx, b.parent)
                if b.parent >= 0:
                    keep, out = self._sum_to(bvars, bcard, bst, vals, b.separator)
                    self.msg[(bidx, b.parent)] = (keep, out)
                else:
                    keep, out = self._sum_to(bvars, bcard, bst, vals, ())
                    self.root_total[bidx] = out[0]
                self._note_live()
        if downward:
            for rt in roots:
                stack = [rt]
                while stack:
                    x = stack.pop()
                    for c in bags[x].children:
                        bvars, bcard, bst, vals = self._product_table(x, c)
                        keep, out = self._sum_to(bvars, bcard, bst, vals,
                                                 bags[c].separator)
                        self.msg[(x, c)] = (keep, out)
                        self._note_live()
                        stack.append(c)
        return self

    def total(self):
        A = self.alg
        Z = A.one()
        for rt, t in self.root_total.items():
            if A.is_zero(t):
                return None
            Z = A.mul(Z, t)
            A.check(Z, self.bit_cap)      # the final component product too
        return Z

    def component_root(self, var):
        b = self.plan.var_home[var]
        while self.plan.bags[b].parent >= 0:
            b = self.plan.bags[b].parent
        return b

    def component_total(self, var):
        return self.root_total[self.component_root(var)]

    def marginal(self, var):
        """Calibrated single-variable table: list over var's states. The home
        bag's belief is computed once and shared by its home variables."""
        A = self.alg
        bidx = self.plan.var_home[var]
        cache = getattr(self, "_belief", None)
        if cache is None:
            cache = self._belief = {}
        if bidx not in cache:
            cache[bidx] = self._product_table(bidx, None)
            self._note_live()
        bvars, bcard, bst, vals = cache[bidx]
        keep, out = self._sum_to(bvars, bcard, bst, vals, (var,))
        if self.stat_insert is not None:
            out = [A.shift(x, self.stat_insert[var][a]) if not A.is_zero(x) else x
                   for a, x in enumerate(out)]
        return out


def exact_marginals(factors, card, deadline=None, entry_cap=None, order=None,
                    charge=None):
    """Exact rational Z and counts relative to the GLOBAL Z, like
    sparse_jt.all_marginals but through this engine."""
    jt = DenseJT(factors, card, RationalAlg, deadline=deadline,
                 entry_cap=entry_cap, order=order, charge=charge).run()
    Z = jt.total()
    if Z is None or Z <= 0:
        raise DenseError("the model has zero total weight")
    out = {}
    for v in jt.plan.free:
        m = jt.marginal(v)
        scale = Z / jt.component_total(v)
        out[v] = [x * scale for x in m]
    return Z, out, jt
