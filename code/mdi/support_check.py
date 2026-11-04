"""The INDEPENDENT CHECKER'S side of support compilation (bounded pilot, 3 November 2026).

Two obligations the overseer's design names:

1. COMPLETENESS of the producer's masks. A witness for every retained row would not detect
   an omitted positive row, so the checker RECONSTRUCTS the support recurrences itself --
   with its own placement arithmetic (`vec_engine._bag_view_checker`, UAI stride offsets;
   never the shared transpose/reshape helper the producer's compiler uses) and its own
   traversal -- and refuses unless the reconstruction agrees with the program's declared
   support EXACTLY (per-bag row counts and the content digest), i.e. including omitted
   entries. The checker's numerical passes then run over ITS OWN rows, never the producer's.

2. An independent EXACT aggregation over the supported rows (`SparseExact`, gmpy2 mpz on
   the checker's rows; a second aggregation implementation, separate from
   `support.SparseEngine`), producing the (Z, counts) pair the interval enclosures are
   compared against, as `vec_engine.VecExact` does on the dense path.
"""
from __future__ import annotations
from fractions import Fraction as Fr
import hashlib
import math
import time
from gmpy2 import mpz
from mdi import arith as A

try:
    import numpy as np
    AVAILABLE = True
except Exception:          # pragma: no cover
    np = None
    AVAILABLE = False


class SupportMismatch(A.NumericalRefusal):
    """The producer's declared support and the checker's reconstruction differ."""


def _offsets_on_bag(scope, card, bag_vars, shape, probe=None):
    """The checker's OWN placement: for a table over `scope`, the flat table offset of
    every bag coordinate (UAI order: first scope variable most significant), as a dense
    int64 array over the bag's shape (axes of variables outside the scope have size 1).
    Accumulated IN PLACE (one int64 array of the placement plus one per-variable index
    temporary and its product at a time; never a second full-size array); `probe()` is
    called after every allocation so a control can observe the actual buffers."""
    strides = {}
    acc = 1
    for v in reversed(scope):
        strides[v] = acc
        acc *= int(card[v])
    offs = np.zeros(tuple(int(card[v]) if v in strides else 1 for v in bag_vars), dtype=np.int64)
    if probe is not None:
        probe()
    for k, v in enumerate(bag_vars):
        if v in strides:
            idx = np.arange(int(card[v]), dtype=np.int64).reshape([int(card[v]) if j == k else 1 for j in range(len(bag_vars))])
            term = idx * strides[v]
            if probe is not None:
                probe()
            np.add(offs, term, out=offs)                  # broadcasting add in place: no second full-size array
            del idx, term
    return offs


def reconstruct_support(plan, factors, card, deadline=None, charge=None, wall_cap_s=None, mem_cap_bytes=None, probe=None, stats=None):
    """The checker's reconstruction of the global support: the same AND / OR / intersect
    recurrences, written independently (table placement by explicit offsets gathered from
    the flat table; separator projections by `np.any` over the eliminated axes after an
    explicit transpose to [separator axes, eliminated axes]; a breadth-first downward pass).
    Returns {bag idx: sorted int64 rows}, the scan-position count and the elapsed seconds.
    Capped like the producer's compilation: the Boolean forecast BEFORE any allocation and
    EVERY allocation of the passes accounted live -- the retained upward masks, the upward
    separator masks, the int64 offset arrays and gathered copies of every placement, the
    projection's reshape copy and output, the int64 rows -- released when freed; the wall
    cap and `deadline()` polled per operation."""
    from mdi import support as SP
    if not AVAILABLE:
        raise SP.SupportError("numpy is not available for support reconstruction")
    wall_cap_s = SP.SUPPORT_WALL_CAP_S if wall_cap_s is None else float(wall_cap_s)
    mem_cap = SP.SUPPORT_MEM_CAP_BYTES if mem_cap_bytes is None else int(mem_cap_bytes)
    t0 = time.monotonic()
    fc = SP.forecast_boolean_bytes(plan, card)
    if fc > mem_cap:
        raise SP.SupportError("support reconstruction refused before allocation: %d bytes forecast against the %d-byte cap" % (fc, mem_cap))
    bags = plan.bags
    scan = 0
    live = 0
    peak = 0

    def _probe():
        if probe is not None:
            probe(live)                                   # the accounted live set at this moment, for a control to compare with the actual buffers

    def _tick(n):
        nonlocal scan
        scan += int(n)
        if charge is not None:
            charge(int(n))
        if time.monotonic() - t0 > wall_cap_s:
            raise SP.SupportError("support reconstruction exceeded its %.1f s cap" % wall_cap_s)
        if deadline is not None:
            deadline()
        _probe()

    def _account(nbytes):
        """RESERVE before the allocation; refuse when the reservation would exceed the cap."""
        nonlocal live, peak
        if live + int(nbytes) > mem_cap:
            raise SP.SupportError("support reconstruction exceeded its %d-byte working-storage cap (%d live + %d requested)" % (mem_cap, live, int(nbytes)))
        live += int(nbytes)
        peak = max(peak, live)

    def _release(nbytes):
        """Release only after the last reference to the storage is dropped (the caller `del`s
        every alias first); probed so a control can catch a release that outruns the buffers."""
        nonlocal live
        live -= int(nbytes)
        _probe()

    # the flat factor indicator masks: retained for the whole reconstruction (reserved first)
    _account(sum(len(f.table) for f in factors))
    flat = {fi: np.fromiter((Fr(x) != 0 for x in f.table), dtype=bool, count=len(f.table)) for fi, f in enumerate(factors)}

    def placed(mask_flat, scope, bag_vars, shape):
        n = 1
        for v in bag_vars:
            n *= int(card[v]) if v in scope else 1
        # reserved BEFORE any of it exists: the int64 offsets (8n), every index / product
        # temporary of the offset construction (each at most 8n; two live at a time -> 16n),
        # the gather's internal index copy (8n) and the gathered Boolean copy (n): 32n is a
        # conservative bound on the simultaneous peak of this operation
        _account(32 * n)
        offs = _offsets_on_bag(scope, card, bag_vars, shape, probe=_probe)
        out = mask_flat[offs]                             # gathered by the checker's own offsets
        _probe()
        del offs
        _release(31 * n)                                  # everything but the gathered copy is gone
        return out, n

    def project(mask, bag_vars, sep):
        keep = [k for k, v in enumerate(bag_vars) if v in sep]
        drop = [k for k, v in enumerate(bag_vars) if v not in sep]
        if not drop:
            _account(int(mask.size))
            return mask.copy(), int(mask.size)
        out_n = 1
        for k in keep:
            out_n *= int(mask.shape[k])
        _account(int(mask.size) + out_n)                  # the reshape copy of the transposed view AND the output, reserved first
        t = mask.transpose(keep + drop).reshape(tuple(mask.shape[k] for k in keep) + (-1,))
        out = np.any(t, axis=-1)
        _probe()
        del t                                             # the copy's last reference goes before its release
        _release(int(mask.size))
        return out, out_n

    # upward, by explicit recursion depth order (leaves first) rather than a reversed stack
    depth = {}
    roots = [b.idx for b in bags if b.parent == -1]
    for rt in roots:
        depth[rt] = 0
        frontier = [rt]
        while frontier:
            x = frontier.pop(0)
            for c in bags[x].children:
                depth[c] = depth[x] + 1
                frontier.append(c)
    by_depth = sorted(depth, key=lambda x: -depth[x])
    up = {}
    upmsg = {}
    for x in by_depth:
        b = bags[x]
        bvars = tuple(b.vars)
        shape = tuple(int(card[v]) for v in bvars)
        _account(int(np.prod(shape)) if shape else 1)     # the bag's upward mask, retained until its global mask is formed
        acc = np.ones(shape, dtype=bool)
        for fi in b.factors:
            pl_, nb = placed(flat[fi], tuple(factors[fi].scope), bvars, shape)
            acc &= pl_
            del pl_
            _release(nb)
            _tick(acc.size)
        for c in b.children:
            sep, m = upmsg[c]
            pl_, nb = placed(m.reshape(-1), sep, bvars, shape)
            del m
            acc &= pl_
            del pl_
            _release(nb)
            _tick(acc.size)
        up[x] = acc
        if b.parent >= 0:
            sep = tuple(sorted(set(bvars) & set(bags[b.parent].vars)))
            m, _nb = project(acc, bvars, sep)             # retained for the parent (accounted inside)
            _tick(acc.size)
            upmsg[x] = (sep, m)
            if not bool(m.any()):
                raise SP.SupportError("checker: bag %d has no feasible subtree assignment (zero evidence weight)" % x)
            del m                                         # no alias outlives the dict's reference
        elif not bool(acc.any()):
            raise SP.SupportError("checker: component root %d has empty support (zero evidence weight)" % x)
        del acc
    # downward, breadth first
    rows = {}
    glob = {}
    for rt in roots:
        glob[rt] = up.pop(rt)
        frontier = [rt]
        while frontier:
            x = frontier.pop(0)
            bx = bags[x]
            bxv = tuple(bx.vars)
            gx = glob[x]
            n_rows = int(np.count_nonzero(gx))           # no allocation; sizes the reservation
            _account(8 * n_rows)                          # the int64 rows: an output, reserved before flatnonzero allocates it
            r = np.flatnonzero(gx.reshape(-1))
            if r.dtype != np.int64:
                _account(8 * n_rows)
                r2 = r.astype(np.int64)
                del r
                _release(8 * n_rows)
                r = r2
            rows[x] = r
            _tick(gx.size)
            for c in bx.children:
                bc = bags[c]
                bcv = tuple(bc.vars)
                sep = tuple(sorted(set(bcv) & set(bxv)))
                pr, nb = project(gx, bxv, sep)
                _tick(gx.size)
                pl_, nb2 = placed(pr.reshape(-1), sep, bcv, tuple(int(card[v]) for v in bcv))
                del pr
                _release(nb)
                gc = up.pop(c)
                gc &= pl_
                del pl_
                _release(nb2)
                _tick(gc.size)
                glob[c] = gc
                del gc                                    # no alias outlives the dict's reference
                frontier.append(c)
            gx_bytes = int(gx.size)
            del glob[x]
            del gx                                        # the mask's last reference, then the release
            _release(gx_bytes)
            if x in upmsg:
                mb = int(upmsg[x][1].size)
                del upmsg[x]
                _release(mb)
    if stats is not None:
        stats["peak_working_bytes"] = peak
        stats["scan_positions"] = scan
    elapsed = time.monotonic() - t0
    if elapsed > wall_cap_s:                              # the FINAL deadline check on the complete elapsed time
        raise SP.SupportError("support reconstruction exceeded its %.1f s cap (%.3f s elapsed at completion)" % (wall_cap_s, elapsed))
    if deadline is not None:
        deadline()
    return rows, scan, elapsed


def support_digest(plan, rows):
    h = hashlib.sha256()
    for b in plan.bags:
        r = rows[b.idx]
        h.update(("bag %d n %d;" % (b.idx, int(r.size))).encode())
        h.update(np.ascontiguousarray(r, dtype=np.int64).tobytes())
    return h.hexdigest()


def verify_declaration(plan, rows, declared):
    """The producer's declared support (program['support']) against the checker's
    reconstruction: per-bag row counts and the content digest must agree EXACTLY. Returns
    the list of disagreements (empty when complete and identical)."""
    bad = []
    per = [int(rows[b.idx].size) for b in plan.bags]
    dec = list(declared.get("rows_per_bag") or [])
    if len(dec) != len(per):
        bad.append("declared %d bags, reconstructed %d" % (len(dec), len(per)))
    else:
        for i, (a, b) in enumerate(zip(dec, per)):
            if int(a) != b:
                bad.append("bag %d: declared %d rows, reconstructed %d (%s)" % (i, int(a), b, "omitted positive rows" if b > int(a) else "rows without a witness"))
                if len(bad) >= 6:
                    break
    if int(declared.get("rows_total") or -1) != sum(per):
        bad.append("declared rows_total %s, reconstructed %d" % (declared.get("rows_total"), sum(per)))
    d = support_digest(plan, rows)
    if str(declared.get("digest")) != d:
        bad.append("declared support digest %s differs from the reconstruction %s" % (str(declared.get("digest"))[:16], d[:16]))
    return bad


class SparseExact:
    """Exact integer aggregation over the CHECKER'S rows (gmpy2 mpz; every factor scaled to
    integers by the LCM of its denominators as `VecExact` does): upward messages as grouped
    sums over separator keys, a downward pass with per-home-variable readouts, all on the
    sparse rows. Placement by the checker's own offsets (`_offsets_on_bag`), gathered per
    row; messages looked up by sorted-key search."""

    def __init__(self, plan, factors, card, rows, deadline=None, charge=None):
        self.plan = plan
        self.factors = factors
        self.card = dict(card)
        self.rows = rows
        self.deadline = deadline
        self.charge = charge
        self.msg = {}
        self.ops = {"mul": 0, "add": 0}
        self.entries_visited = 0
        self.scale_bits = 0
        self._fac = {}
        for fi, f in enumerate(factors):
            L = 1
            for q in f.table:
                d = Fr(q).denominator
                L = L * d // math.gcd(L, d)
            self.scale_bits = max(self.scale_bits, L.bit_length())
            arr = np.empty(len(f.table), dtype=object)
            for i, q in enumerate(f.table):
                arr[i] = mpz(int(Fr(q) * L))
            self._fac[fi] = arr
        self._coords = {}
        for b in plan.bags:
            r = rows[b.idx]
            shape = tuple(int(self.card[v]) for v in b.vars)
            self._coords[b.idx] = np.unravel_index(r, shape) if r.size else tuple(np.zeros(0, dtype=np.int64) for _ in shape)

    def _keys(self, bidx, vars_):
        bvars = tuple(self.plan.bags[bidx].vars)
        acc = 1
        st = {}
        for v in reversed(vars_):
            st[v] = acc
            acc *= int(self.card[v])
        k = np.zeros(self.rows[bidx].size, dtype=np.int64)
        for v in vars_:
            k += self._coords[bidx][bvars.index(v)] * int(st[v])
        return k

    def _product(self, bidx, exclude):
        B = self.plan.bags[bidx]
        bvars = tuple(B.vars)
        n = int(self.rows[bidx].size)
        parts = []
        for fi in B.factors:
            f = self.factors[fi]
            off = self._keys(bidx, tuple(f.scope))              # the factor's own UAI stride keys ARE its flat offsets
            parts.append(self._fac[fi][off])
        for nb in ([B.parent] if B.parent >= 0 else []) + list(B.children):
            if nb == exclude:
                continue
            t = self.msg.get((nb, bidx))
            if t is None:
                raise RuntimeError("missing message %d->%d" % (nb, bidx))
            keys, vals = t
            sep = self._sep(nb, bidx)
            k = self._keys(bidx, sep)
            pos = np.searchsorted(keys, k)
            pos = np.minimum(pos, max(0, keys.size - 1))
            if keys.size == 0 or not bool(np.all(keys[pos] == k)):
                raise A.NumericalRefusal("checker: a row of bag %d projects outside the incoming message's support" % bidx)
            parts.append(vals[pos])
        if self.deadline is not None:
            self.deadline()
        self.entries_visited += n * max(1, len(parts))
        if self.charge is not None:
            self.charge(n)
        if not parts:
            return np.full(n, mpz(1), dtype=object)
        acc = np.array(parts[0], dtype=object, copy=True)
        for q in parts[1:]:
            np.multiply(acc, q, out=acc)
            self.ops["mul"] += n
        return acc

    def _sep(self, a, b):
        return tuple(sorted(set(self.plan.bags[a].vars) & set(self.plan.bags[b].vars)))

    def _group(self, vals, keys_rows):
        if vals.size == 0:
            return np.zeros(0, dtype=np.int64), np.zeros(0, dtype=object)
        keys, inv = np.unique(keys_rows, return_inverse=True)
        order = np.argsort(inv, kind="stable")
        starts = np.searchsorted(inv[order], np.arange(keys.size))
        sums = np.add.reduceat(vals[order], starts)
        self.ops["add"] += int(vals.size - keys.size)
        return keys, np.asarray(sums, dtype=object)

    def send(self, src, dst):
        sep = self._sep(src, dst)
        prod = self._product(src, dst)
        keys, vals = self._group(prod, self._keys(src, sep))
        self.msg[(src, dst)] = (keys, vals)
        return keys.size

    def run(self):
        bags = self.plan.bags
        roots = [b.idx for b in bags if b.parent == -1]
        self.Z = mpz(1)
        self.component_total = {}
        for rt in roots:
            order, stack = [], [rt]
            while stack:
                x = stack.pop(); order.append(x); stack.extend(bags[x].children)
            for b in reversed(order):
                if b != rt:
                    self.send(b, bags[b].parent)
            prod = self._product(rt, None)
            z = mpz(np.add.reduce(prod)) if prod.size else mpz(0)
            self.ops["add"] += max(0, int(prod.size) - 1)
            self.component_total[rt] = z
            self.Z *= z
        return self

    def counts(self, free):
        bags = self.plan.bags
        home = {}
        for v in free:
            home.setdefault(self.plan.var_home[v], []).append(v)
        comp_of = {}
        for rt in self.component_total:
            stack = [rt]
            while stack:
                x = stack.pop(); comp_of[x] = rt; stack.extend(bags[x].children)
        out = {}

        def read(bidx):
            for v in home.get(bidx, ()):
                prod = self._product(bidx, None)
                bvars = tuple(bags[bidx].vars)
                keys, vals = self._group(prod, self._coords[bidx][bvars.index(v)])
                scale = self.Z // self.component_total[comp_of[bidx]]
                for k, c in zip(keys.tolist(), vals.tolist()):
                    c = mpz(c) * scale
                    if c != 0:
                        out[(v, int(k))] = c
        for rt in self.component_total:
            read(rt)
            stack = [rt]
            while stack:
                x = stack.pop()
                for c in bags[x].children:
                    self.send(x, c)
                    read(c)
                if bags[x].parent >= 0:
                    self.msg.pop((bags[x].parent, x), None)
                for c in bags[x].children:
                    self.msg.pop((c, x), None)
                stack.extend(bags[x].children)
        return out
