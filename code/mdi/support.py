"""Exact GLOBAL-SUPPORT compilation and sparse execution (bounded pilot, 3 November 2026;
overseer decision GO_TO_BOUNDED_PILOT_DESIGN, runs/mdi_2026-10-28/PILOT_SUPPORT_2026-11-03/).

The mechanism: on the validated identity decomposition, replace every (restricted,
preprocessed) factor table by the Boolean indicator that its entry is positive; AND the
owned indicators and the children's support messages at each bag; OR (any) out the
eliminated variables for the separator message (upward: which bag assignments extend to a
positive assignment of the subtree); then descend, intersecting each child's upward mask
with the parent's GLOBAL mask projected onto their separator (running intersection makes
that separator sufficient to join an exterior witness with the subtree witness). The final
per-bag masks are exactly the projections of the global positive support onto the bags.
Every positive complete configuration passes every mask, so multiplying the 0/1 masks into
the owned potentials changes no configuration weight: numerical sums and products
restricted to the surviving ROWS preserve Z and every singleton numerator exactly. No
approximation, no state deletion, no change of evidence.

`compile_support` is the PRODUCER'S compilation (it uses the shared layout helper
`vec_engine._bag_view`); the independent checker reconstructs the same recurrences with its
own placement arithmetic in `mdi.support_check` and refuses unless the two agree exactly
(completeness: an omitted positive row is detected structurally, not by weight).

`SparseEngine` is the sparse counterpart of `vec_engine.VecEngine` (modes P and I, the same
gmpy2 directed-rounding contexts, the same depth labels, the same Table interface for root
values and readouts) over the compiled rows only. The numerical work is then proportional
to the feasible rows (Promedus_12: 15,651 rows against 52,002,926 dense), while the Boolean
compilation still scans dense Boolean domains and is CAPPED (wall and working storage) and
CHARGED.
"""
from __future__ import annotations
from fractions import Fraction as Fr
import hashlib
import time
import gmpy2
from gmpy2 import mpfr
from mdi import arith as A
from mdi.contract import Table

try:
    import numpy as np
    AVAILABLE = True
except Exception:          # pragma: no cover
    np = None
    AVAILABLE = False

SUPPORT_WALL_CAP_S = 5.0                 # the pilot's cap on ONE support construction (overseer's design)
SUPPORT_MEM_CAP_BYTES = 512 * (1 << 20)  # ... and on its own working storage
MIN_REDUCTION_RATIO = 10.0               # dense enumerated schedule count / sparse count required to select the route
METHOD = "boolean AND of owned indicators and child support messages, OR over eliminated variables (upward); " \
         "intersection with the parent's global mask projected onto the separator (downward); rows = globally feasible bag assignments"


class SupportError(Exception):
    """A typed stop of support compilation (cap, zero evidence, mismatch)."""


def has_hard_zeros(factors):
    return any(Fr(x) == 0 for f in factors for x in f.table)


def _sep_of(plan, child, parent):
    bags = plan.bags
    return tuple(sorted(set(bags[child].vars) & set(bags[parent].vars)))


def forecast_boolean_bytes(plan, card):
    """Working storage the Boolean compilation needs before any array is allocated:
    three dense Boolean arrays of the largest bag (the running AND, one placed operand,
    the reduction's output or the global mask) plus every retained upward separator
    mask; a conservative estimate measured against the cap BEFORE allocation."""
    bags = plan.bags
    big = max((b.domain(plan.card) for b in bags), default=0)
    seps = sum(b.sep_domain(plan.card) for b in bags if b.parent >= 0)
    return 3 * big + seps


class Support:
    """The compiled global support of a plan: per bag the sorted int64 flat indices (UAI
    order over the bag's sorted variables) of the globally feasible rows."""

    def __init__(self, plan, card, rows, up_counts, scan_positions, elapsed_s, peak_working_bytes, method=METHOD):
        self.plan = plan
        self.card = dict(card)
        self.rows = rows                        # bag idx -> np.int64 array (sorted)
        self.up_counts = up_counts              # nonroot bag idx -> feasible separator entries of its UPWARD (subtree) support
        # the GLOBAL separator populations: the projection of the global rows onto each
        # nonroot separator (identical from the child's and the parent's side), which is
        # exactly the size of every message the sparse engines send over that separator
        self.sep_counts = {}
        for b in plan.bags:
            if b.parent < 0:
                continue
            sep = _sep_of(plan, b.idx, b.parent)
            bvars = tuple(b.vars)
            r = rows[b.idx]
            if r.size == 0:
                self.sep_counts[b.idx] = 0
                continue
            coords = np.unravel_index(r, tuple(int(card[v]) for v in bvars))
            st = _strides_for(sep, card)
            key = np.zeros(r.size, dtype=np.int64)
            for v in sep:
                key += coords[bvars.index(v)] * int(st[v])
            self.sep_counts[b.idx] = int(np.unique(key).size)
        self.scan_positions = int(scan_positions)
        self.elapsed_s = float(elapsed_s)
        self.peak_working_bytes = int(peak_working_bytes)
        self.method = method

    def rows_total(self):
        return int(sum(int(r.size) for r in self.rows.values()))

    def max_rows(self):
        return int(max((int(r.size) for r in self.rows.values()), default=0))

    def rows_per_bag(self):
        return [int(self.rows[b.idx].size) for b in self.plan.bags]

    def digest(self):
        """Content identity of the support: bag index, row count and the rows themselves."""
        h = hashlib.sha256()
        for b in self.plan.bags:
            r = self.rows[b.idx]
            h.update(("bag %d n %d;" % (b.idx, int(r.size))).encode())
            h.update(np.ascontiguousarray(r, dtype=np.int64).tobytes())
        return h.hexdigest()

    def counts(self):
        """The ACTUAL sparse schedule counts the pricing and admission use."""
        bags = self.plan.bags
        sep = sum(self.sep_counts.values())            # every nonroot separator's global population, once
        agg_rows = 0
        n_home = {}
        for v, h in self.plan.var_home.items():
            n_home[h] = n_home.get(h, 0) + 1
        for b in bags:
            n = int(self.rows[b.idx].size)
            agg_rows += n * (1 + len(b.children) + n_home.get(b.idx, 0))
        return {"rows_total": self.rows_total(), "max_rows": self.max_rows(), "rows_per_bag": self.rows_per_bag(),
                "sep_entries": int(sep), "max_sep_entries": int(max(self.sep_counts.values(), default=0)),
                "sep_entries_upward_support": int(sum(self.up_counts.values())),
                "enumerated_schedule_rows": int(agg_rows),
                "scan_positions": self.scan_positions, "compile_s": round(self.elapsed_s, 4),
                "peak_working_bytes": self.peak_working_bytes}

    def declaration(self):
        c = self.counts()
        return {"compiled": True, "digest": self.digest(), "rows_total": c["rows_total"], "max_rows": c["max_rows"],
                "rows_per_bag": c["rows_per_bag"], "sep_entries": c["sep_entries"], "method": self.method}


def dense_enumerated_schedule_rows(plan):
    """The dense counterpart of `Support.counts()['enumerated_schedule_rows']`: every bag's
    domain once per reduction (upward or root, one per child downward, one per home
    variable readout)."""
    n_home = {}
    for v, h in plan.var_home.items():
        n_home[h] = n_home.get(h, 0) + 1
    return int(sum(b.domain(plan.card) * (1 + len(b.children) + n_home.get(b.idx, 0)) for b in plan.bags))


def compile_support(plan, factors, card, deadline=None, charge=None, wall_cap_s=None, mem_cap_bytes=None):
    """The producer's support compilation (see the module docstring). Capped in wall
    (`wall_cap_s`, default SUPPORT_WALL_CAP_S) and in its own working storage
    (`mem_cap_bytes`, default SUPPORT_MEM_CAP_BYTES; the forecast is tested BEFORE any
    allocation and the live set during the passes); polls `deadline()` per bag; charges
    every scanned Boolean position through `charge(n)`. Raises SupportError on a cap or
    when a component root has empty support (zero evidence weight: no normalized result
    exists, the caller's zero-evidence proof decides)."""
    if not AVAILABLE:
        raise SupportError("numpy is not available for support compilation")
    from mdi.vec_engine import _bag_view
    wall_cap_s = SUPPORT_WALL_CAP_S if wall_cap_s is None else float(wall_cap_s)
    mem_cap = SUPPORT_MEM_CAP_BYTES if mem_cap_bytes is None else int(mem_cap_bytes)
    t0 = time.monotonic()
    fc = forecast_boolean_bytes(plan, card)
    if fc > mem_cap:
        raise SupportError("support compilation refused before allocation: the Boolean working set forecasts %d bytes "
                           "against its %d-byte cap" % (fc, mem_cap))
    bags = plan.bags
    fac = {}
    for fi, f in enumerate(factors):
        shape = tuple(int(c) for c in f.card)
        m = np.fromiter((Fr(x) != 0 for x in f.table), dtype=bool, count=len(f.table))
        fac[fi] = m.reshape(shape) if shape else m.reshape(())
    scan = 0
    live = 0
    peak = 0
    up_msg = {}          # child idx -> (sep, mask over sep shape)
    up_mask = {}         # bag idx -> upward mask (retained until its global mask is formed)
    up_counts = {}

    def _tick(n_positions):
        nonlocal scan
        scan += int(n_positions)
        if charge is not None:
            charge(int(n_positions))
        if time.monotonic() - t0 > wall_cap_s:
            raise SupportError("support compilation exceeded its %.1f s cap" % wall_cap_s)
        if deadline is not None:
            deadline()

    def _account(nbytes):
        nonlocal live, peak
        live += int(nbytes)
        peak = max(peak, live)
        if live > mem_cap:
            raise SupportError("support compilation exceeded its %d-byte working-storage cap (%d live)" % (mem_cap, live))

    # ---- upward: subtree feasibility ----
    roots = [b.idx for b in bags if b.parent == -1]
    for rt in roots:
        order, stack = [], [rt]
        while stack:
            x = stack.pop(); order.append(x); stack.extend(bags[x].children)
        for x in reversed(order):
            b = bags[x]
            bvars = tuple(b.vars)
            shape = tuple(int(card[v]) for v in bvars)
            dom = 1
            for c in shape:
                dom *= c
            acc = np.ones(shape, dtype=bool)
            _account(acc.nbytes)
            for fi in b.factors:
                np.logical_and(acc, _bag_view(fac[fi], tuple(factors[fi].scope), bvars), out=acc)
                _tick(dom)
            for c in b.children:
                sep, m = up_msg[c]
                np.logical_and(acc, _bag_view(m, sep, bvars), out=acc)
                _tick(dom)
            up_mask[x] = acc
            if b.parent >= 0:
                sep = _sep_of(plan, x, b.parent)
                axes = tuple(k for k, v in enumerate(bvars) if v not in sep)
                m = np.any(acc, axis=axes) if axes else acc.copy()
                _account(m.nbytes)
                _tick(dom)
                up_msg[x] = (sep, m)
                up_counts[x] = int(np.count_nonzero(m))
                if up_counts[x] == 0:
                    raise SupportError("bag %d has no feasible assignment in its subtree: the evidence has zero weight" % x)
            elif not bool(np.any(acc)):
                raise SupportError("component root %d has empty support: the evidence has zero weight" % x)
    # ---- downward: compatibility with the rest of the model ----
    glob = {}
    rows = {}
    for rt in roots:
        glob[rt] = up_mask.pop(rt)
        stack = [rt]
        while stack:
            x = stack.pop()
            bx = bags[x]
            bxv = tuple(bx.vars)
            gx = glob[x]
            for c in bx.children:
                bc = bags[c]
                bcv = tuple(bc.vars)
                sep = _sep_of(plan, c, x)
                axes = tuple(k for k, v in enumerate(bxv) if v not in sep)
                proj = np.any(gx, axis=axes) if axes else gx
                _tick(gx.size)
                gc = up_mask.pop(c)
                np.logical_and(gc, _bag_view(proj, sep, bcv), out=gc)
                _tick(gc.size)
                glob[c] = gc
                stack.append(c)
            rows[x] = np.flatnonzero(gx).astype(np.int64)
            _tick(gx.size)
            live -= gx.nbytes
            del glob[x]
            if bx.parent >= 0 and x in up_msg:
                live -= up_msg[x][1].nbytes
                del up_msg[x]
    return Support(plan, card, rows, up_counts, scan, time.monotonic() - t0, peak)


# ======================= the sparse two-pass engine (modes P and I) =======================

class SparseTable:
    """A message over a separator stored SPARSELY: `keys` are the sorted flat indices (UAI
    order over the sorted separator variables) of the feasible separator entries, `vals`
    the values at those keys (object array; a (lo, hi) pair of arrays in mode I)."""

    def __init__(self, vars_, keys, vals, depth, support):
        self.vars = tuple(vars_)
        self.keys = keys
        self.vals = vals
        self.depth = int(depth)
        self.support = support

    def size(self):
        return int(self.keys.size)


def _strides_for(vars_, card):
    st = {}
    acc = 1
    for v in reversed(vars_):
        st[v] = acc
        acc *= int(card[v])
    return st


class SparseEngine:
    """Same semantics as `vec_engine.VecEngine` (mode 'P' point with RNDD, mode 'I' directed
    interval; the same contexts, depth labels and support flags) over the compiled rows of
    every bag. Products are gathers of each operand at the rows; separator messages are
    grouped sums over the rows' separator keys. `root_value` and `read_marginal` return the
    scalar-engine Table / (counts, seen, depth) shapes the publication code consumes."""

    layout = "sparse-support"

    def __init__(self, plan, factors, ctx, support, mode="P", progress=None, cap_bytes=None, deadline=None, charge=None):
        if not AVAILABLE:
            raise RuntimeError("numpy is not available for the sparse layout")
        if support.plan is not plan and [tuple(b.vars) for b in support.plan.bags] != [tuple(b.vars) for b in plan.bags]:
            raise A.NumericalRefusal("the compiled support describes another decomposition")
        self.plan = plan
        self.factors = factors
        self.ctx = ctx
        self.mode = mode
        self.support = support
        self.progress = progress or (lambda *a, **k: None)
        self.deadline = deadline
        self.charge = charge
        self.card = plan.card
        self.msg = {}
        self.ops = {"mul": 0, "add": 0, "readout": 0}
        self.peak_live_entries = 0
        self.rows_visited = 0
        self._fac = {}
        self._coords = {}
        self._fac_off = {}
        for b in plan.bags:
            rws = support.rows[b.idx]
            shape = tuple(int(self.card[v]) for v in b.vars)
            self._coords[b.idx] = np.unravel_index(rws, shape) if rws.size else tuple(np.zeros(0, dtype=np.int64) for _ in shape)

    # ---------- operand placement at the rows ----------
    def _factor_offsets(self, bidx, fi):
        key = (bidx, fi)
        off = self._fac_off.get(key)
        if off is None:
            f = self.factors[fi]
            bvars = tuple(self.plan.bags[bidx].vars)
            st = f.strides()
            coords = self._coords[bidx]
            off = np.zeros(self.support.rows[bidx].size, dtype=np.int64)
            for k, v in enumerate(f.scope):
                off += coords[bvars.index(v)] * int(st[k])
            self._fac_off[key] = off
        return off

    def _sep_keys(self, bidx, sep):
        bvars = tuple(self.plan.bags[bidx].vars)
        st = _strides_for(sep, self.card)
        coords = self._coords[bidx]
        key = np.zeros(self.support.rows[bidx].size, dtype=np.int64)
        for v in sep:
            key += coords[bvars.index(v)] * int(st[v])
        return key

    def _enc_factor(self, fi):
        a = self._fac.get(fi)
        if a is not None:
            return a
        f = self.factors[fi]
        down = self.ctx.down
        lo = np.empty(len(f.table), dtype=object)
        for i, q in enumerate(f.table):
            lo[i] = down(q)
        if self.mode == "P":
            a = lo
        else:
            up = self.ctx.up
            hi = np.empty(len(f.table), dtype=object)
            for i, q in enumerate(f.table):
                hi[i] = up(q)
            a = (lo, hi)
        self._fac[fi] = a
        return a

    def _message_positions(self, bidx, t):
        """Position of every row's separator key inside the message's sorted keys."""
        k = self._sep_keys(bidx, t.vars)
        pos = np.searchsorted(t.keys, k)
        pos = np.minimum(pos, max(0, t.keys.size - 1))
        if t.keys.size == 0 or not bool(np.all(t.keys[pos] == k)):
            raise A.NumericalRefusal("a feasible row of bag %d projects outside the support of the incoming message over %s"
                                     % (bidx, t.vars))
        return pos

    def _product(self, bidx, exclude):
        """Product over the bag's rows of its owned factors and every incoming message
        except the one from `exclude`; returns (vals or (lo, hi), depth, n_operands)."""
        B = self.plan.bags[bidx]
        n = int(self.support.rows[bidx].size)
        inc = []
        for nb in ([B.parent] if B.parent >= 0 else []) + list(B.children):
            if nb == exclude:
                continue
            t = self.msg.get((nb, bidx))
            if t is None:
                raise RuntimeError("missing message %d->%d" % (nb, bidx))
            inc.append(t)
        parts_lo, parts_hi = [], []
        for fi in B.factors:
            a = self._enc_factor(fi)
            off = self._factor_offsets(bidx, fi)
            if self.mode == "P":
                parts_lo.append(a[off])
            else:
                parts_lo.append(a[0][off]); parts_hi.append(a[1][off])
        for t in inc:
            pos = self._message_positions(bidx, t)
            if self.mode == "P":
                parts_lo.append(t.vals[pos])
            else:
                parts_lo.append(t.vals[0][pos]); parts_hi.append(t.vals[1][pos])
        n_ops = len(parts_lo)
        prod_depth = len(B.factors) + sum(t.depth for t in inc) + max(0, n_ops - 1)
        if self.deadline is not None:
            self.deadline()
        self.rows_visited += n
        if self.charge is not None:
            self.charge(n)

        def product(parts, cx, one):
            if not parts:
                return np.full(n, one, dtype=object)
            acc = np.array(parts[0], dtype=object, copy=True)
            try:
                with cx:
                    for q in parts[1:]:
                        np.multiply(acc, q, out=acc)
                        self.ops["mul"] += n
            except (gmpy2.OverflowResultError, gmpy2.UnderflowResultError) as e:
                raise A.NumericalRefusal("exponent range exhausted in a sparse product: %s" % type(e).__name__)
            return acc
        if self.mode == "P":
            acc = product(parts_lo, self.ctx.D, self.ctx.down(Fr(1)))
            if n and bool(np.any(acc == 0)):
                raise A.NumericalRefusal("a positive sparse product rounded to zero (underflow)")
            return acc, prod_depth, n_ops
        lo = product(parts_lo, self.ctx.D, self.ctx.down(Fr(1)))
        hi = product(parts_hi, self.ctx.U, self.ctx.up(Fr(1)))
        if n and bool(np.any(lo == 0)):
            raise A.NumericalRefusal("a positive sparse product rounded to zero (underflow)")
        if n and bool(np.any(lo > hi)):
            raise A.NumericalRefusal("inverted interval from a sparse multiplication")
        return (lo, hi), prod_depth, n_ops

    def _grouped_sum(self, vals, group_keys, cx):
        """Sum `vals` over rows sharing a key: returns (sorted unique keys, sums, largest group)."""
        if vals.size == 0:
            return np.zeros(0, dtype=np.int64), np.zeros(0, dtype=object), 0
        keys, inv = np.unique(group_keys, return_inverse=True)
        order = np.argsort(inv, kind="stable")
        starts = np.searchsorted(inv[order], np.arange(keys.size))
        try:
            with cx:
                sums = np.add.reduceat(vals[order], starts)
        except (gmpy2.OverflowResultError, gmpy2.UnderflowResultError) as e:
            raise A.NumericalRefusal("exponent range exhausted in a sparse sum: %s" % type(e).__name__)
        sizes = np.diff(np.append(starts, inv.size))
        self.ops["add"] += int(vals.size - keys.size)
        return keys, np.asarray(sums, dtype=object), int(sizes.max())

    def send(self, src, dst):
        sep = _sep_of(self.plan, src, dst) if self.plan.bags[src].parent == dst else _sep_of(self.plan, dst, src)
        prod, prod_depth, _ = self._product(src, dst)
        skeys = self._sep_keys(src, sep)
        if self.mode == "P":
            keys, vals, biggest = self._grouped_sum(prod, skeys, self.ctx.D)
            out_depth = prod_depth + max(0, biggest - 1)
            t = SparseTable(sep, keys, vals, out_depth, np.ones(keys.size, dtype=bool))
        else:
            keys, lo, biggest = self._grouped_sum(prod[0], skeys, self.ctx.D)
            keys2, hi, _b2 = self._grouped_sum(prod[1], skeys, self.ctx.U)
            out_depth = prod_depth + max(0, biggest - 1)
            t = SparseTable(sep, keys, (lo, hi), out_depth, np.ones(keys.size, dtype=bool))
        self.msg[(src, dst)] = t
        if self.charge is not None:
            self.charge(t.size())
        return t

    def _note_live(self):
        live = sum(m.size() for m in self.msg.values())
        self.peak_live_entries = max(self.peak_live_entries, live)

    def _post_order(self, root):
        bags = self.plan.bags
        order, stack = [], [root]
        while stack:
            x = stack.pop(); order.append(x); stack.extend(bags[x].children)
        return list(reversed(order))

    def upward(self, root, keep=None):
        n = 0
        bags = self.plan.bags
        for b in self._post_order(root):
            if b == root:
                continue
            self.send(b, bags[b].parent)
            n += 1
            self._note_live()
            if n % 64 == 0:
                self.progress("upward", n)
        return n

    def downward(self, root, on_calibrated=None):
        bags = self.plan.bags
        n = 0
        stack = [root]
        if on_calibrated is not None and bags[root].parent < 0:
            on_calibrated(root)
        while stack:
            x = stack.pop()
            kids = list(bags[x].children)
            for c in kids:
                self.send(x, c)
                if on_calibrated is not None:
                    on_calibrated(c)
                n += 1
                self._note_live()
                if n % 64 == 0:
                    self.progress("downward", n)
            if bags[x].parent >= 0:
                self.msg.pop((bags[x].parent, x), None)
            for c in kids:
                self.msg.pop((c, x), None)
            for c in reversed(kids):
                stack.append(c)
        return n

    def root_value(self, root):
        B = self.plan.bags[root]
        saved = B.parent
        B.parent = -1
        try:
            prod, prod_depth, _ = self._product(root, None)
        finally:
            B.parent = saved
        n = int(self.support.rows[root].size)
        out_depth = prod_depth + max(0, n - 1)
        any_sup = n > 0
        if self.mode == "P":
            with self.ctx.D:
                val = np.add.reduce(prod) if n else mpfr(0)
            self.ops["add"] += max(0, n - 1)
            return Table(vars=(), card=(), vals=[val if any_sup else mpfr(0)], depth=out_depth, support=[any_sup])
        with self.ctx.D:
            lo = np.add.reduce(prod[0]) if n else mpfr(0)
        with self.ctx.U:
            hi = np.add.reduce(prod[1]) if n else mpfr(0)
        self.ops["add"] += 2 * max(0, n - 1)
        return Table(vars=(), card=(), vals=[(lo, hi) if any_sup else (mpfr(0), mpfr(0))], depth=out_depth, support=[any_sup])

    def read_marginal(self, var):
        bags = self.plan.bags
        bi = self.plan.var_home[var]
        B = bags[bi]
        missing = [nb for nb in ([B.parent] if B.parent >= 0 else []) + list(B.children) if (nb, bi) not in self.msg]
        if missing:
            raise A.NumericalRefusal("read_marginal(%d) at bag %d is missing messages from %s" % (var, bi, missing))
        prod, prod_depth, _ = self._product(bi, None)
        bvars = tuple(B.vars)
        cv = int(self.card[var])
        states = self._coords[bi][bvars.index(var)]
        if self.mode == "P":
            keys, sums, biggest = self._grouped_sum(prod, states, self.ctx.D)
            counts = [mpfr(0)] * cv
            for k, s in zip(keys.tolist(), sums.tolist()):
                counts[int(k)] = s
            seen = [bool(np.any(states == s)) for s in range(cv)]
        else:
            keys, lo, biggest = self._grouped_sum(prod[0], states, self.ctx.D)
            _k2, hi, _b2 = self._grouped_sum(prod[1], states, self.ctx.U)
            counts = [(mpfr(0), mpfr(0))] * cv
            for k, l, h in zip(keys.tolist(), lo.tolist(), hi.tolist()):
                counts[int(k)] = (l, h)
            seen = [bool(np.any(states == s)) for s in range(cv)]
        out_depth = prod_depth + max(0, biggest - 1)
        self.ops["readout"] += 1
        return counts, seen, out_depth


# ======================= pricing from actual support counts =======================

def sparse_schedule_ops(plan, support, n_home=None):
    """Multiply + add bounds of ONE sparse two-pass run (producer P) and of the sparse exact
    aggregation, from the compiled rows: per reduction (operands - 1) multiplies and at
    most one add per row (grouped sums add rows - keys <= rows)."""
    rows = support.rows
    up_t = down_t = ro_t = 0
    for b in plan.bags:
        n = int(rows[b.idx].size)
        own = len(b.factors)
        nch = len(b.children)
        npar = 1 if b.parent >= 0 else 0
        nh = sum(1 for v, h in plan.var_home.items() if h == b.idx)
        up_t += n * max(0, own + nch - 1) + n                       # upward message or root total
        down_t += nch * (n * max(0, own + npar + nch - 2) + n)      # one message per child
        ro_t += nh * (n * max(0, own + npar + nch - 1) + n)         # one readout per home variable
    prod = up_t + down_t + ro_t
    return {"producer_ops": int(prod), "producer_upward_ops": int(up_t), "producer_downward_ops": int(down_t), "readout_ops": int(ro_t),
            "interval_checker_ops": int(2 * prod), "exact_checker_ops": int(prod)}


def reconstruction_scan_bound(plan):
    """Boolean positions the checker's `support_check.reconstruct_support` ticks: per bag its
    domain per owned factor, per child message, once for its upward projection (nonroot),
    once for its row extraction, and per child once more (the parent-side projection), plus
    each child's domain for the intersection -- the formula the ticks implement."""
    tot = 0
    for b in plan.bags:
        dom = b.domain(plan.card)
        nch = len(b.children)
        tot += dom * (len(b.factors) + nch + (1 if b.parent >= 0 else 0) + 1 + nch)
        tot += sum(plan.bags[c].domain(plan.card) for c in b.children)
    return int(tot)


def support_price(plan, support):
    """Everything the pricing needs, from ACTUAL counts: metered entries per engine, the
    arithmetic bounds, the enumerated schedule rows and the dense/sparse ratio."""
    c = support.counts()
    ops = sparse_schedule_ops(plan, support)
    n_home = {}
    for v, h in plan.var_home.items():
        n_home[h] = n_home.get(h, 0) + 1
    # metered entries, in the unit each engine charges: rows per product + entries per message
    prod_meter = 0
    agg_meter = 0
    for b in plan.bags:
        n = int(support.rows[b.idx].size)
        prod_meter += n * (1 + len(b.children) + n_home.get(b.idx, 0))          # rows visited per product
        agg_meter += n * (1 + len(b.children) + n_home.get(b.idx, 0))
    prod_meter += 2 * c["sep_entries"]                                           # one upward and one downward message per separator, charged by send
    dense_rows = dense_enumerated_schedule_rows(plan)
    ratio = (dense_rows / c["enumerated_schedule_rows"]) if c["enumerated_schedule_rows"] else float("inf")
    return {"counts": c, "ops": ops, "producer_metered_entries": int(prod_meter),
            "interval_checker_metered_entries": int(prod_meter), "exact_checker_metered_entries": int(agg_meter),
            "dense_enumerated_schedule_rows": int(dense_rows), "reduction_ratio": ratio,
            "admitted": bool(ratio >= MIN_REDUCTION_RATIO), "min_reduction_ratio": MIN_REDUCTION_RATIO}


# a process-local, content-keyed cache so the executor's compile reuses discovery's within ONE
# invocation (the pipeline resets it at its entry boundary); the checker never reads it
_SUPPORT_CACHE = {}


def support_cache_key(plan, factors):
    return (tuple(plan.order), tuple((tuple(f.scope), tuple(int(c) for c in f.card),
                                     bytes(1 if Fr(x) == 0 else 0 for x in f.table)) for f in factors))


def compile_support_cached(plan, factors, card, **kw):
    key = support_cache_key(plan, factors)
    hit = _SUPPORT_CACHE.get(key)
    if hit is not None:
        return hit, False
    sup = compile_support(plan, factors, card, **kw)
    _SUPPORT_CACHE[key] = sup
    if len(_SUPPORT_CACHE) > 4:
        _SUPPORT_CACHE.pop(next(iter(_SUPPORT_CACHE)))
    return sup, True
