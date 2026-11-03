"""Vectorized LAYOUT of the identity route's two engines (capacity pass, 2 November 2026).

The arithmetic is unchanged: the SAME gmpy2 directed-rounding contexts (`arith.Ctx.D`
/ `.U`), the same precision and exponent range, the same conservative depth labels,
the same zero-safe support semantics and the same SEQUENTIAL summation order over a
bag's interior (numpy's object-dtype `add.reduce` accumulates in index order, so
every rounded sum is bit-for-bit the value `contract.Engine` computes; the shipped
control `test_vectorized_engine_is_bit_identical_to_the_scalar_engine` asserts it).
Only the data layout differs: bag products and separator sums are whole-array
operations on numpy object arrays of `mpfr` instead of a Python loop over flat
indices, which is what makes the 600-second physical budget reachable on bags of
millions of entries (measured: 0.07-0.17 us per bag entry against 30-100 us).

`VecExact` is the independent exact aggregation in the same layout over
`gmpy2.mpz`: every factor is pre-scaled by the least common multiple of its
denominators (a positive constant per factor, so every conditional marginal is
unchanged and Z and the counts carry the same scale), products and sums are exact
integers, and the result is the (Z, counts) pair `solve._check` compares the
interval enclosures against.
"""
from __future__ import annotations
from fractions import Fraction as Fr
import math
import gmpy2
from gmpy2 import mpfr, mpz
from mdi import arith as A
from mdi.contract import Table, _strides

try:
    import numpy as np
    AVAILABLE = True
except Exception:          # pragma: no cover
    np = None
    AVAILABLE = False


def _bag_view(arr, scope, bag_vars):
    """A table over `scope` (array shaped by its cardinalities, scope order) as a
    broadcastable view over the bag's axes (bag_vars order; absent vars size 1)."""
    pos = {v: k for k, v in enumerate(scope)}
    axes = [pos[v] for v in bag_vars if v in pos]
    a = arr.transpose(axes) if axes != list(range(len(axes))) else arr
    shape = [arr.shape[pos[v]] if v in pos else 1 for v in bag_vars]
    return a.reshape(shape)


class VecEngine:
    """Same interface and semantics as `contract.Engine` (mode 'P' point with
    RNDD, mode 'I' directed interval), vectorized."""

    def __init__(self, plan, factors, ctx, mode="P", progress=None, cap_bytes=None,
                 deadline=None, conv_cache=None, charge=None):
        if not AVAILABLE:
            raise RuntimeError("numpy is not available for the vectorized layout")
        self.charge = charge
        self.plan = plan
        self.factors = factors
        self.ctx = ctx
        self.mode = mode
        self.progress = progress or (lambda *a, **k: None)
        self.cap_bytes = cap_bytes
        self.deadline = deadline
        self.card = plan.card
        self.msg = {}                   # (src, dst) -> Table (vals: object array / pair of arrays)
        self.ops = {"mul": 0, "add": 0, "readout": 0}
        self.peak_entries = 0
        self.peak_live_entries = 0
        self._fac = {}                  # factor index -> converted array (mode P) / (lo, hi) arrays
        self.layout = "vectorized"

    # ---------- element helpers ----------
    def _one(self):
        return self.ctx.down(Fr(1)) if self.mode == "P" else (self.ctx.down(Fr(1)), self.ctx.up(Fr(1)))

    def _zero(self):
        return mpfr(0) if self.mode == "P" else (mpfr(0), mpfr(0))

    def _enc_factor(self, fi):
        a = self._fac.get(fi)
        if a is not None:
            return a
        f = self.factors[fi]
        shape = tuple(int(c) for c in f.card)
        down = self.ctx.down
        lo = np.empty(len(f.table), dtype=object)
        for i, q in enumerate(f.table):
            lo[i] = down(q)
        lo = lo.reshape(shape) if shape else lo.reshape(())
        if self.mode == "P":
            a = lo
        else:
            up = self.ctx.up
            hi = np.empty(len(f.table), dtype=object)
            for i, q in enumerate(f.table):
                hi[i] = up(q)
            a = (lo, hi.reshape(shape) if shape else hi.reshape(()))
        self._fac[fi] = a
        return a

    def _mul_arrays(self, acc, part, cx, inplace=False):
        """acc x part under the directed context `cx`; with `inplace` (acc is a
        private full-shape array) the product is written into acc so the
        transient is one array, not two. The deadline / RSS check is polled
        before every whole-array operation (a bag product of up to 16.8 M
        entries is a few seconds of work; the poll bounds the overrun to one
        such operation, which the terminal's budget check then records)."""
        if self.deadline is not None:
            self.deadline()
        try:
            with cx:
                if inplace and acc.shape == np.broadcast_shapes(acc.shape, part.shape):
                    np.multiply(acc, part, out=acc)
                    out = acc
                else:
                    out = acc * part
        except (gmpy2.OverflowResultError, gmpy2.UnderflowResultError) as e:
            raise A.NumericalRefusal("exponent range exhausted in a product: %s" % type(e).__name__)
        self.ops["mul"] += int(out.size)
        return out

    def _sum_axes(self, arr, axes, cx):
        if self.deadline is not None:
            self.deadline()
        if not axes:
            return arr
        n_terms = 1
        for ax in axes:
            n_terms *= arr.shape[ax]
        try:
            with cx:
                out = np.asarray(arr.sum(axis=tuple(axes)), dtype=object)
        except (gmpy2.OverflowResultError, gmpy2.UnderflowResultError) as e:
            raise A.NumericalRefusal("exponent range exhausted in a sum: %s" % type(e).__name__)
        self.ops["add"] += int(out.size) * max(0, n_terms - 1)
        return out

    def _check_underflow(self, prod, parts_nonzero):
        """A positive product that rounded to zero is a refusal, exactly as the
        scalar engine refuses it; `parts_nonzero` is the broadcast mask of
        entries whose every operand is positive."""
        bad = (prod == 0) & parts_nonzero
        if bool(np.any(bad)):
            raise A.NumericalRefusal("product underflowed to zero")

    # ---------- the core: one bag product ----------
    def _product(self, bidx, exclude):
        """Product over bag `bidx` of its owned factors and every incoming
        message except the one from `exclude`; returns (bag_vars, prod or
        (lo, hi), alive mask, product depth, number of operands)."""
        bags = self.plan.bags
        B = bags[bidx]
        bvars = tuple(B.vars)
        shape = tuple(self.card[v] for v in bvars)
        inc = []
        for nb in ([B.parent] if B.parent >= 0 else []) + list(B.children):
            if nb == exclude:
                continue
            t = self.msg.get((nb, bidx))
            if t is None:
                raise RuntimeError("missing message %d->%d" % (nb, bidx))
            inc.append(t)
        own = list(B.factors)
        parts_lo, parts_hi, alive = [], [], None
        for fi in own:
            a = self._enc_factor(fi)
            f = self.factors[fi]
            if self.mode == "P":
                v = _bag_view(a, tuple(f.scope), bvars)
                parts_lo.append(v)
                m = (v != 0)
            else:
                v_lo = _bag_view(a[0], tuple(f.scope), bvars)
                v_hi = _bag_view(a[1], tuple(f.scope), bvars)
                parts_lo.append(v_lo); parts_hi.append(v_hi)
                m = (v_hi != 0)
            alive = m if alive is None else (alive & m)
        for t in inc:
            if self.mode == "P":
                v = _bag_view(t.vals, tuple(t.vars), bvars)
                parts_lo.append(v)
            else:
                parts_lo.append(_bag_view(t.vals[0], tuple(t.vars), bvars))
                parts_hi.append(_bag_view(t.vals[1], tuple(t.vars), bvars))
            m = _bag_view(t.support, tuple(t.vars), bvars)
            alive = m if alive is None else (alive & m)
        if alive is None:
            alive = np.ones(shape, dtype=bool)
        else:
            alive = np.broadcast_to(alive, shape)
        n_ops = len(parts_lo)
        fac_depths = len(own)
        in_depths = sum(t.depth for t in inc)
        nmul = max(0, len(own) + len(inc) - 1)
        prod_depth = fac_depths + in_depths + nmul
        if self.deadline is not None:
            self.deadline()
        zero = mpfr(0)

        def product(parts, cx, one):
            # the first operand is broadcast ONCE into a private full-shape array;
            # every further operand multiplies into it in place (one transient)
            if not parts:
                return np.full(shape, one, dtype=object)
            acc = np.array(np.broadcast_to(parts[0], shape), dtype=object)      # private copy
            for q in parts[1:]:
                acc = self._mul_arrays(acc, q, cx, inplace=True)
            # dead entries (a zero factor entry or an unsupported message) are exact zeros
            np.copyto(acc, zero, where=~alive)
            return acc
        if self.mode == "P":
            acc = product(parts_lo, self.ctx.D, self.ctx.down(Fr(1)))
            self._check_underflow(acc, alive)
            return bvars, acc, alive, prod_depth, n_ops
        lo = product(parts_lo, self.ctx.D, self.ctx.down(Fr(1)))
        self._check_underflow(lo, alive)
        hi = product(parts_hi, self.ctx.U, self.ctx.up(Fr(1)))
        if bool(np.any(lo > hi)):
            raise A.NumericalRefusal("inverted interval from multiplication")
        return bvars, (lo, hi), alive, prod_depth, n_ops

    def send(self, src, dst):
        bags = self.plan.bags
        B = bags[src]
        sep = tuple(sorted(set(B.vars) & set(bags[dst].vars)))
        bvars, prod, alive, prod_depth, _ = self._product(src, dst)
        interior_axes = [k for k, v in enumerate(bvars) if v not in sep]
        inner = 1
        for k in interior_axes:
            inner *= self.card[bvars[k]]
        out_depth = prod_depth + max(0, inner - 1)
        sup = np.any(alive, axis=tuple(interior_axes)) if interior_axes else alive.copy()
        if self.mode == "P":
            vals = self._sum_axes(prod, interior_axes, self.ctx.D)
            if bool(np.any((vals == 0) & sup)):
                raise A.NumericalRefusal("a separator sum underflowed to zero")
        else:
            lo = self._sum_axes(prod[0], interior_axes, self.ctx.D)
            hi = self._sum_axes(prod[1], interior_axes, self.ctx.U)
            vals = (lo, hi)
        scard = tuple(self.card[v] for v in sep)
        t = Table(vars=sep, card=scard, vals=vals, depth=out_depth, support=np.asarray(sup, dtype=bool))
        self.msg[(src, dst)] = t
        if self.charge is not None:
            self.charge(t.size())
        return t

    # ---------- passes (identical to contract.Engine) ----------
    def _post_order(self, root):
        bags = self.plan.bags
        order, stack = [], [root]
        while stack:
            x = stack.pop()
            order.append(x)
            stack.extend(bags[x].children)
        return list(reversed(order))

    def _live_entries(self):
        return sum(t.size() for t in self.msg.values())

    def _note_live(self):
        e = self._live_entries()
        if e > self.peak_live_entries:
            self.peak_live_entries = e
        return e

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

    def free_consumed_upward(self, bag):
        freed = 0
        for c in self.plan.bags[bag].children:
            t = self.msg.pop((c, bag), None)
            if t is not None:
                freed += t.size()
        return freed

    def downward(self, root, on_calibrated=None):
        """Depth-first downward pass with EARLY release: once bag x has sent to
        every child (and `on_calibrated(c)` has read each child's home
        variables while the child is calibrated), none of x's incoming
        messages is needed by anything that follows -- the messages into x
        are released immediately, not after x's whole subtree. Live memory
        during the pass is then the upward messages of unprocessed subtrees
        plus the downward frontier, instead of every message ever sent
        (measured on Grids_11: 12.5 GiB -> within the 8 GiB cap)."""
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
            # every message INTO x has now served its last use
            if bags[x].parent >= 0:
                self.msg.pop((bags[x].parent, x), None)
            for c in kids:
                self.msg.pop((c, x), None)
            for c in reversed(kids):
                stack.append(c)
        return n

    def root_value(self, root):
        """Contract the root bag completely (children only, as the scalar
        engine does); returns a scalar-style Table."""
        B = self.plan.bags[root]
        saved = B.parent
        self.plan.bags[root].parent = -1
        try:
            bvars, prod, alive, prod_depth, _ = self._product(root, None)
        finally:
            self.plan.bags[root].parent = saved
        inner = 1
        for v in bvars:
            inner *= self.card[v]
        out_depth = prod_depth + max(0, inner - 1)
        any_sup = bool(np.any(alive))
        axes = list(range(len(bvars)))
        if self.mode == "P":
            acc = self._sum_axes(prod, axes, self.ctx.D) if axes else prod
            val = acc.item() if isinstance(acc, np.ndarray) else acc
            return Table(vars=(), card=(), vals=[val if any_sup else mpfr(0)], depth=out_depth, support=[any_sup])
        lo = self._sum_axes(prod[0], axes, self.ctx.D) if axes else prod[0]
        hi = self._sum_axes(prod[1], axes, self.ctx.U) if axes else prod[1]
        lo = lo.item() if isinstance(lo, np.ndarray) else lo
        hi = hi.item() if isinstance(hi, np.ndarray) else hi
        return Table(vars=(), card=(), vals=[(lo, hi) if any_sup else (mpfr(0), mpfr(0))], depth=out_depth, support=[any_sup])

    def read_marginal(self, var):
        bags = self.plan.bags
        bi = self.plan.var_home[var]
        B = bags[bi]
        missing = [nb for nb in ([B.parent] if B.parent >= 0 else []) + list(B.children) if (nb, bi) not in self.msg]
        if missing:
            raise A.NumericalRefusal(
                "read_marginal(%d) at bag %d is missing messages from %s, so the belief is NOT calibrated "
                "and its marginal would be wrong" % (var, bi, missing))
        bvars, prod, alive, prod_depth, _ = self._product(bi, None)
        vk = bvars.index(var)
        cv = self.card[var]
        inner = 1
        for v in bvars:
            inner *= self.card[v]
        per_state_terms = inner // cv
        out_depth = prod_depth + max(0, per_state_terms - 1)
        other = [k for k in range(len(bvars)) if k != vk]
        seen_arr = np.any(alive, axis=tuple(other)) if other else alive
        seen = [bool(seen_arr[s]) for s in range(cv)]
        if self.mode == "P":
            c = self._sum_axes(prod, other, self.ctx.D) if other else prod
            counts = [c[s] if seen[s] else mpfr(0) for s in range(cv)]
        else:
            lo = self._sum_axes(prod[0], other, self.ctx.D) if other else prod[0]
            hi = self._sum_axes(prod[1], other, self.ctx.U) if other else prod[1]
            counts = [(lo[s], hi[s]) if seen[s] else (mpfr(0), mpfr(0)) for s in range(cv)]
        self.ops["readout"] += 1
        return counts, seen, out_depth


# ====================== the independent EXACT aggregation, vectorized ======================

class VecExact:
    """Exact integer junction-tree aggregation over numpy object arrays of mpz,
    on the given plan: upward and downward passes over dense bag domains (zeros
    kept as exact mpz(0), so hard zeros cost nothing numerically and the
    support is the nonzero mask). Factors are pre-scaled by the LCM of their
    denominators; Z and every count carry the same scale."""

    def __init__(self, plan, factors, card, deadline=None, charge=None):
        if not AVAILABLE:
            raise RuntimeError("numpy is not available for the vectorized layout")
        self.plan = plan
        self.card = dict(card)
        self.deadline = deadline
        self.charge = charge
        self.msg = {}
        self.ops = {"mul": 0, "add": 0}
        self.peak_live_entries = 0
        self.entries_visited = 0
        self.max_bits = 0
        self.scale_bits = 0
        self._fac = {}
        self.factors = factors
        for fi, f in enumerate(factors):
            L = 1
            for q in f.table:
                d = Fr(q).denominator
                L = L * d // math.gcd(L, d)
            self.scale_bits = max(self.scale_bits, L.bit_length())
            arr = np.empty(len(f.table), dtype=object)
            for i, q in enumerate(f.table):
                arr[i] = mpz(int(Fr(q) * L))
            shape = tuple(int(c) for c in f.card)
            self._fac[fi] = arr.reshape(shape) if shape else arr.reshape(())

    def _product(self, bidx, exclude):
        B = self.plan.bags[bidx]
        bvars = tuple(B.vars)
        shape = tuple(self.card[v] for v in bvars)
        parts = [_bag_view(self._fac[fi], tuple(self.factors[fi].scope), bvars) for fi in B.factors]
        for nb in ([B.parent] if B.parent >= 0 else []) + list(B.children):
            if nb == exclude:
                continue
            t = self.msg.get((nb, bidx))
            if t is None:
                raise RuntimeError("missing message %d->%d" % (nb, bidx))
            parts.append(_bag_view(t[1], tuple(t[0]), bvars))
        if not parts:
            acc = np.full(shape, mpz(1), dtype=object)
        else:
            acc = np.array(np.broadcast_to(parts[0], shape), dtype=object)       # private copy, one transient
            for q in parts[1:]:
                np.multiply(acc, q, out=acc)
                self.ops["mul"] += int(acc.size)
        if self.deadline is not None:
            self.deadline()
        self.entries_visited += int(acc.size)
        if self.charge is not None:
            self.charge(int(acc.size))
        return bvars, acc

    CHUNK_ENTRIES = 1 << 20          # the largest exact product transient materialized at once

    def _parts(self, bidx, exclude):
        B = self.plan.bags[bidx]
        bvars = tuple(B.vars)
        parts = [_bag_view(self._fac[fi], tuple(self.factors[fi].scope), bvars) for fi in B.factors]
        for nb in ([B.parent] if B.parent >= 0 else []) + list(B.children):
            if nb == exclude:
                continue
            t = self.msg.get((nb, bidx))
            if t is None:
                raise RuntimeError("missing message %d->%d" % (nb, bidx))
            parts.append(_bag_view(t[1], tuple(t[0]), bvars))
        return bvars, parts

    def _reduce(self, bidx, exclude, keep_axes):
        """Exact product over the bag reduced (summed) to `keep_axes`, CHUNKED
        along the first summed axis so that no transient exceeds
        CHUNK_ENTRIES: the sum is exact, so the chunk order is immaterial."""
        bvars, parts = self._parts(bidx, exclude)
        shape = tuple(self.card[v] for v in bvars)
        dom = 1
        for c in shape:
            dom *= c
        sum_axes = tuple(k for k in range(len(bvars)) if k not in keep_axes)
        if self.deadline is not None:
            self.deadline()
        self.entries_visited += dom * max(1, len(parts))
        if self.charge is not None:
            self.charge(dom)

        def product(ps, shp):
            if not ps:
                return np.full(shp, mpz(1), dtype=object)
            acc = np.array(np.broadcast_to(ps[0], shp), dtype=object)
            for q in ps[1:]:
                np.multiply(acc, q, out=acc)
                self.ops["mul"] += int(acc.size)
                if self.deadline is not None:
                    self.deadline()          # polled between whole-array operations (each <= CHUNK_ENTRIES)
            return acc
        if dom <= self.CHUNK_ENTRIES or not sum_axes:
            acc = product(parts, shape)
            out = np.asarray(acc.sum(axis=sum_axes), dtype=object) if sum_axes else acc
            self.ops["add"] += int(np.size(out)) * max(0, dom // max(1, int(np.size(out))) - 1)
            return bvars, out
        k0 = sum_axes[0]
        rest = tuple(k if k < k0 else k - 1 for k in sum_axes[1:])      # axes after dropping k0
        sub_shape = shape[:k0] + shape[k0 + 1:]
        out = None
        for i in range(shape[k0]):
            if self.deadline is not None:
                self.deadline()              # polled per chunk
            sl = [np.take(q, i if q.shape[k0] > 1 else 0, axis=k0) for q in parts]
            acc = product(sl, sub_shape)
            red = np.asarray(acc.sum(axis=rest), dtype=object) if rest else acc
            self.ops["add"] += int(np.size(red)) * max(0, int(acc.size) // max(1, int(np.size(red))) - 1)
            if out is None:
                out = red
            else:
                np.add(out, red, out=out)
                self.ops["add"] += int(np.size(out))
        return bvars, out

    def send(self, src, dst):
        bags = self.plan.bags
        sep = tuple(sorted(set(bags[src].vars) & set(bags[dst].vars)))
        bvars_all = tuple(bags[src].vars)
        keep = tuple(k for k, v in enumerate(bvars_all) if v in sep)
        bvars, out = self._reduce(src, dst, keep)
        out = np.asarray(out, dtype=object)
        self.msg[(src, dst)] = (sep, out)
        live = sum(int(np.size(m[1])) for m in self.msg.values())
        self.peak_live_entries = max(self.peak_live_entries, live)
        return out

    def run(self):
        bags = self.plan.bags
        roots = [b.idx for b in bags if b.parent == -1]
        self.Z = mpz(1)
        comp = {}
        for rt in roots:
            order, stack = [], [rt]
            while stack:
                x = stack.pop(); order.append(x); stack.extend(bags[x].children)
            for b in reversed(order):
                if b != rt:
                    self.send(b, bags[b].parent)
            bvars, z = self._reduce(rt, None, ())
            z = mpz(z.item() if isinstance(z, np.ndarray) else z)
            comp[rt] = z
            self.Z *= z
            self.max_bits = max(self.max_bits, int(z).bit_length())
        self.component_total = comp
        return self

    def _downward_with_readout(self, free):
        """Downward pass with early release; each home variable's count row is
        read at the moment its bag is calibrated, before the messages into the
        bag are released."""
        bags = self.plan.bags
        home = {}
        for v in free:
            home.setdefault(self.plan.var_home[v], []).append(v)
        rows = {}

        def read(bidx):
            for v in home.get(bidx, ()):
                bvars_all = tuple(bags[bidx].vars)
                vk = bvars_all.index(v)
                _bv, row = self._reduce(bidx, None, (vk,))
                rows[v] = np.asarray(row, dtype=object)
        for rt in self.component_total:
            read(rt)
            stack = [rt]
            while stack:
                x = stack.pop()
                kids = list(bags[x].children)
                for c in kids:
                    self.send(x, c)
                    read(c)
                if bags[x].parent >= 0:
                    self.msg.pop((bags[x].parent, x), None)
                for c in kids:
                    self.msg.pop((c, x), None)
                for c in reversed(kids):
                    stack.append(c)
        return rows

    def counts(self, free):
        """{(v, a): count} on the GLOBAL scale (each variable's home-bag belief
        rescaled by the other components' totals), with Z = product of the
        component totals."""
        bags = self.plan.bags
        out = {}
        comp_of = {}
        for rt, z in self.component_total.items():
            stack = [rt]
            while stack:
                x = stack.pop(); comp_of[x] = rt; stack.extend(bags[x].children)
        rows = self._downward_with_readout(free)
        for v in free:
            bi = self.plan.var_home[v]
            row = rows[v]
            scale = self.Z // self.component_total[comp_of[bi]]
            for a in range(self.card[v]):
                c = mpz(row[a]) * scale
                if c != 0:
                    out[(v, a)] = c
        return out
