"""Exact sparse junction-tree contraction (spec §4, §11).

A SECOND implementation of sum-product aggregation, independent of
`contract.Engine`: tables are sparse dictionaries of exact rationals keyed by
assignment tuples, the elimination order is min-degree over the table scopes,
and messages are formed by multiplying every table touching the eliminated
variable and summing it out. Upward and downward passes are both run, so every
variable's marginal is read once from a calibrated bag -- one pass for all
requested outputs, not one elimination per target.

Three semirings share the schedule code:
  * `rational`  : exact nonnegative sum-product;
  * `boolean`   : OR / AND support contraction (the completed Boolean support
                  contraction §7.2 asks for; True iff some assignment survives);
  * `statistic` : sum-product where each table entry is a distribution over an
                  INTEGER statistic, inserted once per variable when that
                  variable is forgotten and convolved at joins (§7.1).

Everything is bounded: a declared entry cap on every intermediate table, the
rational bit cap on every entry, and a deadline callback inside every loop.
The only shared material with the other implementations is the validated
scope structure and Python's exact rational type, which the contract permits.
"""
from __future__ import annotations
import sys
sys.set_int_max_str_digits(0)
from fractions import Fraction as Fr
from mdi import config as K


class SparseError(Exception):
    """A structural or resource refusal of this contraction."""


def _bits_ok(q: Fr, cap) -> bool:
    return (q.numerator.bit_length() <= cap
            and q.denominator.bit_length() <= cap)


class Table:
    """scope: tuple of variables; entries: {assignment tuple: value}."""
    __slots__ = ("scope", "entries")

    def __init__(self, scope, entries):
        self.scope = tuple(scope)
        self.entries = entries

    def __len__(self):
        return len(self.entries)


def table_from_factor(f, deadline=None):
    """Dense factor -> sparse exact table (zeros dropped)."""
    st = f.strides()
    n = 1
    for c in f.card:
        n *= c
    ent = {}
    for flat in range(n):
        if deadline is not None and (flat & 0xFF) == 0:
            deadline()
        rem = flat
        key = []
        for k in range(len(f.card)):
            d, rem = divmod(rem, st[k])
            key.append(d)
        v = f.table[flat]
        if v != 0:
            ent[tuple(key)] = Fr(v)
    return Table(f.scope, ent)


def table_from_callable(scope, card, fn, deadline=None, cap=None):
    """Build a sparse table by evaluating `fn(assignment dict)` on the scope,
    e.g. a compact projected crossing's `value`; zeros are dropped and the
    size is admitted BEFORE anything is materialized."""
    import itertools
    n = 1
    for v in scope:
        n *= card[v]
    if cap is not None and n > cap:
        raise SparseError("a table over %s needs %d entries, above the %d cap"
                          % (tuple(scope), n, cap))
    ent = {}
    k = 0
    for combo in itertools.product(*[range(card[v]) for v in scope]):
        k += 1
        if deadline is not None and (k & 0xFF) == 0:
            deadline()
        v = fn(dict(zip(scope, combo)))
        if v != 0:
            ent[tuple(combo)] = Fr(v)
    return Table(scope, ent)


# ---------------------------------------------------------------- semirings

class Rational:
    name = "rational"

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
    def check_bits(a, cap):
        if not _bits_ok(a, cap):
            raise SparseError("an exact rational reached %d bits, above the "
                              "declared %d-bit cap"
                              % (max(a.numerator.bit_length(),
                                     a.denominator.bit_length()), cap))


class Boolean:
    name = "boolean"

    @staticmethod
    def one():
        return True

    @staticmethod
    def mul(a, b):
        return bool(a) and bool(b)

    @staticmethod
    def add(a, b):
        return bool(a) or bool(b)

    @staticmethod
    def is_zero(a):
        return not a

    @staticmethod
    def check_bits(a, cap):
        return None


def stat_add(sa, sb):
    """Statistic keys are scalars or tuples (one entry per mode)."""
    if isinstance(sa, tuple):
        return tuple(x + y for x, y in zip(sa, sb))
    return sa + sb


class Statistic:
    """Entries are {statistic: exact mass}, the statistic an integer (or a
    tuple of integers, one per signed mode). Product = convolution; sum =
    pointwise addition. The support of every entry is capped."""
    name = "statistic"

    def __init__(self, support_cap, rank=1):
        self.support_cap = support_cap
        self.rank = rank

    def one(self):
        return {(0,) * self.rank if self.rank > 1 else 0: Fr(1)}

    def mul(self, a, b):
        out = {}
        for sa, wa in a.items():
            for sb, wb in b.items():
                k = stat_add(sa, sb)
                if k not in out and len(out) >= self.support_cap:
                    raise SparseError(
                        "a convolved statistic support reached the declared "
                        "%d cap" % self.support_cap)
                out[k] = out.get(k, Fr(0)) + wa * wb
        return out

    def add(self, a, b):
        out = dict(a)
        for s, w in b.items():
            out[s] = out.get(s, Fr(0)) + w
            if len(out) > self.support_cap:
                raise SparseError(
                    "a summed statistic support reached the declared %d cap"
                    % self.support_cap)
        return out

    @staticmethod
    def is_zero(a):
        return not a

    @staticmethod
    def check_bits(a, cap):
        for w in a.values():
            if not _bits_ok(w, cap):
                raise SparseError("a statistic mass reached %d bits, above "
                                  "the declared %d-bit cap"
                                  % (max(w.numerator.bit_length(),
                                         w.denominator.bit_length()), cap))


class Interval:
    """Entries are (lo, hi) exact rational pairs, lo >= 0. Sum and product
    are outward because the endpoints are exact: the only approximation is
    the one carried in by the caller's enclosed tilts."""
    name = "interval"

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
    def check_bits(a, cap):
        for q in a:
            if not _bits_ok(q, cap):
                raise SparseError("an interval endpoint reached %d bits, above "
                                  "the declared %d-bit cap"
                                  % (max(q.numerator.bit_length(),
                                         q.denominator.bit_length()), cap))


class Complex:
    """Entries are complex rectangles (re_lo, re_hi, im_lo, im_hi) with exact
    rational corners; the product is the rectangle hull of the four corner
    products (collective._cmul). Zero is the exact origin rectangle."""
    name = "complex"

    @staticmethod
    def one():
        return (Fr(1), Fr(1), Fr(0), Fr(0))

    @staticmethod
    def mul(a, b):
        from mdi.collective import _cmul
        return _cmul(a, b)

    @staticmethod
    def add(a, b):
        return (a[0] + b[0], a[1] + b[1], a[2] + b[2], a[3] + b[3])

    @staticmethod
    def is_zero(a):
        return a[0] == a[1] == a[2] == a[3] == 0

    @staticmethod
    def check_bits(a, cap):
        for q in a:
            if not _bits_ok(q, cap):
                raise SparseError("a complex corner reached %d bits, above the "
                                  "declared %d-bit cap"
                                  % (max(q.numerator.bit_length(),
                                         q.denominator.bit_length()), cap))


# ------------------------------------------------------------ the contraction

class SparseJT:
    """Build the bucket tree for `tables` over `card` and run both passes.

    `entry_cap` bounds every intermediate table; `bit_cap` bounds every
    rational. `deadline` is called inside the loops. `order` may be supplied
    (e.g. a persisted program's order); otherwise min-degree over the table
    scopes is used, which differs from the dense engine's min-fill portfolio
    and is therefore a genuinely different schedule.
    """

    def __init__(self, tables, card, semiring=Rational, entry_cap=None,
                 bit_cap=None, deadline=None, order=None, charge=None):
        self.tables = list(tables)
        self.card = dict(card)
        self.S = semiring
        self.entry_cap = entry_cap or K.CAPS["local_mass_entries"]
        self.bit_cap = bit_cap or K.CAPS["rational_bit_length"]
        self.deadline = deadline
        self.charge = charge          # charge(n) every 64 built entries
        self.ops = {"mul": 0, "add": 0, "entries_built": 0}
        self.peak_live_entries = 0
        self.free = sorted({v for t in self.tables for v in t.scope})
        for t in self.tables:
            for v in t.scope:
                if v not in self.card:
                    raise SparseError("table scope names variable %d with no "
                                      "cardinality" % v)
        self.order = list(order) if order is not None else self._min_degree()
        if sorted(self.order) != self.free:
            raise SparseError("the elimination order does not cover exactly "
                              "the table variables")
        self._build_tree()

    # ---- schedule ----
    def _min_degree(self):
        adj = {v: set() for v in self.free}
        for t in self.tables:
            for a in t.scope:
                for b in t.scope:
                    if a != b:
                        adj[a].add(b)
        remaining = set(self.free)
        order = []
        while remaining:
            best = None
            for v in sorted(remaining):
                nb = adj[v] & remaining
                cost = 1
                for u in nb | {v}:
                    cost *= self.card[u]
                key = (cost, len(nb), v)
                if best is None or key < best[0]:
                    best = (key, v)
            v = best[1]
            nb = adj[v] & remaining
            for a in nb:
                adj[a] |= nb
                adj[a].discard(a)
            remaining.discard(v)
            order.append(v)
        return order

    def _build_tree(self):
        pos = {v: i for i, v in enumerate(self.order)}
        adj = {v: set() for v in self.free}
        for t in self.tables:
            for a in t.scope:
                for b in t.scope:
                    if a != b:
                        adj[a].add(b)
        remaining = set(self.free)
        bags = []           # dict: idx, vars, elim, parent, children, tables, sep
        for v in self.order:
            nb = {x for x in adj[v] if x in remaining and x != v}
            bags.append({"idx": len(bags), "vars": tuple(sorted(nb | {v})),
                         "elim": v, "parent": -1, "children": [],
                         "tables": [], "sep": ()})
            for x in nb:
                adj[x] |= nb
                adj[x].discard(x)
            remaining.discard(v)
        for b in bags:
            rest = [x for x in b["vars"] if x != b["elim"]]
            if rest:
                p = min(rest, key=lambda x: pos[x])
                b["parent"] = pos[p]
                b["sep"] = tuple(sorted(rest))
                bags[b["parent"]]["children"].append(b["idx"])
        for ti, t in enumerate(self.tables):
            if not t.scope:
                # a scalar table is owned by the first bag (any bag is valid)
                bags[0]["tables"].append(ti) if bags else None
                continue
            v = min(t.scope, key=lambda x: pos[x])
            b = bags[pos[v]]
            if not set(t.scope) <= set(b["vars"]):
                raise SparseError("ownership failure: scope %s not inside bag "
                                  "%s" % (t.scope, b["vars"]))
            b["tables"].append(ti)
        self.bags = bags
        self.roots = [b["idx"] for b in bags if b["parent"] < 0]
        self.home = {}
        for b in bags:
            for v in b["vars"]:
                self.home.setdefault(v, b["idx"])
        self.largest_bag = max((self._dom(b["vars"]) for b in bags), default=1)

    def _dom(self, vs):
        n = 1
        for v in vs:
            n *= self.card[v]
        return n

    # ---- primitives ----
    def _tick(self):
        self.ops["entries_built"] += 1
        n = self.ops["entries_built"]
        if self.charge is not None and (n & 0x3F) == 0:
            self.charge(64)
        if self.deadline is not None and (n & 0xFF) == 0:
            self.deadline()

    def multiply(self, t1: Table, t2: Table) -> Table:
        S = self.S
        sc1, sc2 = t1.scope, t2.scope
        out_sc = tuple(sorted(set(sc1) | set(sc2)))
        pos = {v: k for k, v in enumerate(out_sc)}
        shared = [v for v in sc1 if v in set(sc2)]
        p1 = {v: k for k, v in enumerate(sc1)}
        p2 = {v: k for k, v in enumerate(sc2)}
        idx = {}
        for a2, v2 in t2.entries.items():
            key = tuple(a2[p2[v]] for v in shared)
            idx.setdefault(key, []).append((a2, v2))
        out = {}
        only2 = [v for v in sc2 if v not in p1]
        for a1, v1 in t1.entries.items():
            key = tuple(a1[p1[v]] for v in shared)
            for a2, v2 in idx.get(key, ()):
                self._tick()
                kk = [0] * len(out_sc)
                for v, k in p1.items():
                    kk[pos[v]] = a1[k]
                for v in only2:
                    kk[pos[v]] = a2[p2[v]]
                k = tuple(kk)
                self.ops["mul"] += 1
                val = S.mul(v1, v2)
                if S.is_zero(val):
                    continue
                if k in out:
                    self.ops["add"] += 1
                    val = S.add(out[k], val)
                elif len(out) >= self.entry_cap:
                    raise SparseError(
                        "a product table over %s reached the declared "
                        "%d-entry cap" % (out_sc, self.entry_cap))
                S.check_bits(val, self.bit_cap)
                out[k] = val
        return Table(out_sc, out)

    def marginalize(self, t: Table, var) -> Table:
        S = self.S
        if var not in t.scope:
            return t
        k = t.scope.index(var)
        out_sc = tuple(v for v in t.scope if v != var)
        out = {}
        for a, v in t.entries.items():
            self._tick()
            key = a[:k] + a[k + 1:]
            if key in out:
                self.ops["add"] += 1
                nv = S.add(out[key], v)
                S.check_bits(nv, self.bit_cap)
                out[key] = nv
            else:
                out[key] = v
        return Table(out_sc, out)

    def insert_statistic(self, t: Table, var, kq_of_state):
        """Statistic semiring only: multiply every entry by the delta
        distribution at this variable's integer statistic, exactly once."""
        k = t.scope.index(var)
        out = {}
        for a, dist in t.entries.items():
            self._tick()
            s0 = kq_of_state[a[k]]
            out[a] = {stat_add(s, s0): w for s, w in dist.items()}
        return Table(t.scope, out)

    # ---- passes ----
    def _bag_product(self, bidx, exclude=None):
        b = self.bags[bidx]
        acc = Table((), {(): self.S.one()})
        for ti in b["tables"]:
            acc = self.multiply(acc, self.tables[ti])
        for c in b["children"]:
            if c == exclude:
                continue
            m = self.msg.get((c, bidx))
            if m is None:
                raise SparseError("missing message %d->%d" % (c, bidx))
            acc = self.multiply(acc, m)
        if b["parent"] >= 0 and exclude != b["parent"] and exclude is not None:
            m = self.msg.get((b["parent"], bidx))
            if m is None:
                raise SparseError("missing message %d->%d" % (b["parent"], bidx))
            acc = self.multiply(acc, m)
        return acc

    def _sum_out(self, acc, vars_to_remove, stat_insert):
        """Insert each removed variable's statistic (statistic semiring) and
        marginalize it. A variable is inserted exactly where it is forgotten,
        so along any root-to-readout path every variable is inserted once."""
        for v in vars_to_remove:
            if stat_insert is not None and v in acc.scope:
                acc = self.insert_statistic(acc, v, stat_insert[v])
            acc = self.marginalize(acc, v)
        return acc

    def _send_up(self, bidx, stat_insert=None):
        b = self.bags[bidx]
        acc = self._bag_product(bidx)
        if b["parent"] >= 0:
            acc = self._sum_out(acc, [v for v in b["vars"] if v not in b["sep"]],
                                stat_insert)
            self.msg[(bidx, b["parent"])] = acc
        else:
            acc = self._sum_out(acc, list(b["vars"]), stat_insert)
            self.root_total[bidx] = acc.entries.get((), None)
        self._note_live()

    def _send_down(self, bidx, child, stat_insert=None):
        """m_{bidx->child}: own tables x parent message x other children,
        summed to the child's separator. Zero-safe exclusion, no division.
        Every variable summed out here (the bag's own eliminated variable and
        any separator variable not shared with the child) is inserted here:
        none of them was inserted on this side of the tree before."""
        b = self.bags[bidx]
        acc = Table((), {(): self.S.one()})
        for ti in b["tables"]:
            acc = self.multiply(acc, self.tables[ti])
        if b["parent"] >= 0:
            m = self.msg.get((b["parent"], bidx))
            if m is None:
                raise SparseError("missing message %d->%d" % (b["parent"], bidx))
            acc = self.multiply(acc, m)
        for c in b["children"]:
            if c == child:
                continue
            m = self.msg.get((c, bidx))
            if m is None:
                raise SparseError("missing message %d->%d" % (c, bidx))
            acc = self.multiply(acc, m)
        sep = set(self.bags[child]["sep"])
        acc = self._sum_out(acc, [v for v in b["vars"] if v not in sep],
                            stat_insert)
        self.msg[(bidx, child)] = acc
        self._note_live()

    def _note_live(self):
        e = sum(len(m.entries) for m in self.msg.values())
        if e > self.peak_live_entries:
            self.peak_live_entries = e

    def _post_order(self, root):
        seq, stack = [], [root]
        while stack:
            x = stack.pop()
            seq.append(x)
            stack.extend(self.bags[x]["children"])
        return list(reversed(seq))

    def run(self, stat_insert=None, downward=True):
        """Upward (and downward) passes over every component.

        `stat_insert` (statistic semiring): {var: [k per state]} -- each
        variable's integer statistic is inserted exactly once, at the bag
        that eliminates it.
        """
        self.msg = {}
        self.root_total = {}
        self.stat_insert = stat_insert
        for rt in self.roots:
            for b in self._post_order(rt):
                self._send_up(b, stat_insert)
        if downward:
            for rt in self.roots:
                stack = [rt]
                while stack:
                    x = stack.pop()
                    for c in self.bags[x]["children"]:
                        self._send_down(x, c, stat_insert)
                        stack.append(c)
        return self

    def component_of(self, var):
        b = self.home[var]
        while self.bags[b]["parent"] >= 0:
            b = self.bags[b]["parent"]
        return b

    def marginal(self, var) -> Table:
        """The calibrated single-variable table at var's home bag: its
        entries sum to the component's total (rational semiring)."""
        bidx = self.home[var]
        b = self.bags[bidx]
        acc = Table((), {(): self.S.one()})
        for ti in b["tables"]:
            acc = self.multiply(acc, self.tables[ti])
        if b["parent"] >= 0:
            m = self.msg.get((b["parent"], bidx))
            if m is None:
                raise SparseError("marginal(%d): bag %d has no parent message, "
                                  "so its belief is NOT calibrated" % (var, bidx))
            acc = self.multiply(acc, m)
        for c in b["children"]:
            m = self.msg.get((c, bidx))
            if m is None:
                raise SparseError("marginal(%d): bag %d is missing message "
                                  "from %d" % (var, bidx, c))
            acc = self.multiply(acc, m)
        si = getattr(self, "stat_insert", None)
        acc = self._sum_out(acc, [v for v in b["vars"] if v != var], si)
        if si is not None and var in acc.scope:
            # the readout variable is kept, so its own statistic enters here:
            # along every path each variable is inserted exactly once
            acc = self.insert_statistic(acc, var, si[var])
        return acc

    def total(self):
        """Product of the component totals (rational semiring)."""
        Z = self.S.one()
        for rt in self.roots:
            t = self.root_total.get(rt)
            if t is None or self.S.is_zero(t):
                return None
            Z = self.S.mul(Z, t)
        return Z


def all_marginals(tables, card, deadline=None, entry_cap=None, order=None,
                  charge=None):
    """Convenience: exact rational Z and {var: [count per state]} where each
    count/Z is the exact marginal. Counts are per component total; they are
    rescaled so every count is relative to the GLOBAL Z."""
    jt = SparseJT(tables, card, Rational, entry_cap=entry_cap,
                  deadline=deadline, order=order, charge=charge).run()
    Z = jt.total()
    if Z is None or Z <= 0:
        raise SparseError("the model has zero total weight")
    out = {}
    for v in jt.free:
        m = jt.marginal(v)
        comp_total = jt.root_total[jt.component_of(v)]
        scale = Z / comp_total
        row = [Fr(0)] * card[v]
        for a, w in m.entries.items():
            row[a[0]] = w * scale
        out[v] = row
    return Z, out, jt
