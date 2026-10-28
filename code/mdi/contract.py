"""Generic sum-product contraction with all-marginal readout (spec section 2).

Messages live on separators. Bag assignments are STREAMED. Outgoing messages are
never formed by dividing a belief by an incoming message: zero-safe prefix/suffix
exclusion products are used instead. Error depths are propagated per table.
"""
from __future__ import annotations
import sys
sys.set_int_max_str_digits(0)
from fractions import Fraction as Fr
from dataclasses import dataclass
import gmpy2
from gmpy2 import mpfr
from mdi import arith as A


@dataclass
class Table:
    """A nonnegative message/belief table with a conservative error depth and
    boolean structural support."""
    vars: tuple
    card: tuple
    vals: list              # mpfr (mode P) or (lo,hi) tuples (mode I)
    depth: int              # conservative E dominating every entry
    support: list           # bool per entry; True = possibly positive

    def size(self):
        n = 1
        for c in self.card:
            n *= c
        return n

    def strides(self):
        st = [1] * len(self.card)
        acc = 1
        for k in range(len(self.card) - 1, -1, -1):
            st[k] = acc; acc *= self.card[k]
        return tuple(st)


def _strides(card):
    st = [1] * len(card)
    acc = 1
    for k in range(len(card) - 1, -1, -1):
        st[k] = acc; acc *= card[k]
    return st


class Engine:
    """mode 'P' = certified point (RNDD + depth labels); 'I' = directed interval."""

    def __init__(self, plan, factors, ctx, mode="P", progress=None,
                 cap_bytes=None, deadline=None, conv_cache=None):
        self.plan = plan
        self.factors = factors
        self.ctx = ctx
        self.mode = mode
        self.progress = progress or (lambda *a, **k: None)
        self.cap_bytes = cap_bytes
        self.deadline = deadline
        self.card = plan.card
        self.msg = {}            # (src,dst) -> Table
        self.ops = {"mul": 0, "add": 0, "readout": 0}
        self.peak_entries = 0
        self.peak_live_entries = 0
        # Contract G: cache each exact factor entry's enclosure. The same entry
        # is re-converted once per bag visit otherwise, which on these models is
        # the dominant repeated work. Keyed by precision and exponent range, so a
        # changed context cannot reuse a stale value. Producer and checker pass
        # SEPARATE caches.
        if conv_cache is None:
            from mdi.budget import ConversionCache
            conv_cache = ConversionCache(ctx, label=mode)
        self.conv = conv_cache
        self._bytes_per = 64 if mode == "P" else 128

    # ---------- element helpers ----------
    def _one(self):
        return self.ctx.down(Fr(1)) if self.mode == "P" else (self.ctx.down(Fr(1)),
                                                              self.ctx.up(Fr(1)))

    def _zero(self):
        return mpfr(0) if self.mode == "P" else (mpfr(0), mpfr(0))

    def _enc(self, q):
        if self.mode == "P":
            return self.conv.down(q)
        return (self.conv.down(q), self.conv.up(q))

    def _mul(self, a, b):
        self.ops["mul"] += 1
        return self.ctx.mul_d(a, b) if self.mode == "P" else self.ctx.imul(a, b)

    def _add(self, a, b):
        self.ops["add"] += 1
        return self.ctx.add_d(a, b) if self.mode == "P" else self.ctx.iadd(a, b)

    def _is_zero(self, x):
        return (x == 0) if self.mode == "P" else (x[1] == 0)

    # ---------- the core: one directed message ----------
    def send(self, src, dst):
        """Compute m_{src->dst} by streaming src's assignments.

        Products use a zero-safe exclusion over the incoming messages: all
        incoming except the one from dst. No division anywhere.
        """
        bags = self.plan.bags
        B = bags[src]
        sep = tuple(sorted(set(B.vars) & set(bags[dst].vars)))
        bvars = B.vars
        bcard = tuple(self.card[v] for v in bvars)
        bst = _strides(bcard)
        bpos = {v: k for k, v in enumerate(bvars)}

        scard = tuple(self.card[v] for v in sep)
        sst = _strides(scard)
        ssize = 1
        for c in scard:
            ssize *= c

        # incoming messages to include (all neighbours except dst)
        inc = []
        for nb in ([B.parent] if B.parent >= 0 else []) + list(B.children):
            if nb == dst:
                continue
            t = self.msg.get((nb, src))
            if t is None:
                raise RuntimeError("missing message %d->%d" % (nb, src))
            inc.append(t)

        # owned factors
        own = [self.factors[fi] for fi in B.factors]

        # --- depth accounting, conservative and dominating the loop order ---
        # product over owned factors (each an exact->rounded input, E=1 in mode P)
        # plus incoming message depths; then a sequential sum over the eliminated
        # interior of size `inner`.
        inner = 1
        for v in bvars:
            if v not in sep:
                inner *= self.card[v]
        fac_depths = [1 for _ in own]          # downward conversion of an exact entry
        in_depths = [t.depth for t in inc]
        nmul = max(0, len(fac_depths) + len(in_depths) - 1)
        prod_depth = sum(fac_depths) + sum(in_depths) + nmul
        # sequential summation of `inner` terms: inner-1 rounded additions
        out_depth = prod_depth + max(0, inner - 1)

        if self.mode == "I":
            out = [(mpfr(0), mpfr(0))] * ssize
        else:
            out = [mpfr(0)] * ssize
        out = list(out)
        sup = [False] * ssize

        # precompute per-factor projection strides into the bag index space
        fproj = []
        for f in own:
            st = f.strides()
            fproj.append([(bpos[v], st[k]) for k, v in enumerate(f.scope)])
        iproj = []
        for t in inc:
            st = t.strides()
            iproj.append([(bpos[v], st[k]) for k, v in enumerate(t.vars)])
        sproj = [(bpos[v], sst[k]) for k, v in enumerate(sep)]

        bsize = 1
        for c in bcard:
            bsize *= c
        self.peak_entries = max(self.peak_entries, ssize + self._live_entries())

        # stream every bag assignment
        digits = [0] * len(bvars)
        for flat in range(bsize):
            if self.deadline is not None and (flat & 0xFFF) == 0:
                self.deadline()
            # decode once
            rem = flat
            for k in range(len(bvars)):
                digits[k], rem = divmod(rem, bst[k]) if False else (rem // bst[k], rem % bst[k])
            # factor product (zero-safe: bail out on an exact zero)
            val = self._one()
            dead = False
            for fi, pm in enumerate(fproj):
                off = 0
                for (bk, s) in pm:
                    off += digits[bk] * s
                e = own[fi].table[off]
                if e == 0:
                    dead = True
                    break
                val = self._mul(val, self._enc(e))
            if not dead:
                for ti, pm in enumerate(iproj):
                    off = 0
                    for (bk, s) in pm:
                        off += digits[bk] * s
                    t = inc[ti]
                    if not t.support[off]:
                        dead = True
                        break
                    val = self._mul(val, t.vals[off])
            if dead:
                continue
            soff = 0
            for (bk, s) in sproj:
                soff += digits[bk] * s
            out[soff] = self._add(out[soff], val) if sup[soff] else val
            sup[soff] = True

        t = Table(vars=sep, card=scard, vals=out, depth=out_depth, support=sup)
        self.msg[(src, dst)] = t
        return t

    # ---------- passes ----------
    def _post_order(self, root):
        bags = self.plan.bags
        order, stack = [], [root]
        while stack:
            x = stack.pop()
            order.append(x)
            stack.extend(bags[x].children)
        return list(reversed(order))     # children before parents

    def _live_entries(self):
        return sum(t.size() for t in self.msg.values())

    def _note_live(self):
        e = self._live_entries()
        if e > self.peak_live_entries:
            self.peak_live_entries = e
        return e

    def upward(self, root, keep=None):
        """Post-order upward pass. A child message is FREED as soon as its
        parent has consumed it, so live memory follows the planner's estimate.

        `keep` is a set of (src,dst) pairs the caller still needs; for a
        downward pass the upward messages into each bag are required, so the
        driver passes keep=None only when it will not run a downward pass.
        """
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
        """Drop upward messages from `bag`'s children: they are no longer needed
        once `bag` has produced its own outgoing message."""
        freed = 0
        for c in self.plan.bags[bag].children:
            t = self.msg.pop((c, bag), None)
            if t is not None:
                freed += t.size()
        return freed

    def downward(self, root, on_calibrated=None):
        """Depth-first downward pass.

        Immediately after a bag has both its incoming messages, `on_calibrated`
        is invoked so the driver can read out that bag's variables; the bag's
        messages can then be released. This keeps live memory near the planner's
        peak-live estimate instead of retaining every message.
        """
        bags = self.plan.bags
        n = 0
        # explicit stack of (bag, phase)
        stack = [(root, 0)]
        while stack:
            x, phase = stack.pop()
            if phase == 0:
                if on_calibrated is not None:
                    on_calibrated(x)
                kids = list(bags[x].children)
                for c in kids:
                    self.send(x, c)
                    n += 1
                    self._note_live()
                    if n % 64 == 0:
                        self.progress("downward", n)
                # after sending to all children, this bag's own incoming
                # messages are no longer needed by anyone above it
                stack.append((x, 1))
                for c in reversed(kids):
                    stack.append((c, 0))
            else:
                # release the messages that fed bag x
                if bags[x].parent >= 0:
                    self.msg.pop((bags[x].parent, x), None)
                for c in bags[x].children:
                    self.msg.pop((c, x), None)
        return n

    def root_value(self, root):
        """Contract the root bag completely: the evidence weight of its component."""
        B = self.plan.bags[root]
        # a message to a virtual parent with an empty separator
        saved = B.parent
        self.plan.bags[root].parent = -1
        t = self._contract_to_empty(root)
        self.plan.bags[root].parent = saved
        return t

    def _contract_to_empty(self, root):
        bags = self.plan.bags
        B = bags[root]
        bvars = B.vars
        bcard = tuple(self.card[v] for v in bvars)
        bst = _strides(bcard)
        bpos = {v: k for k, v in enumerate(bvars)}
        inc = []
        for nb in B.children:
            t = self.msg.get((nb, root))
            if t is None:
                raise RuntimeError("missing message %d->%d" % (nb, root))
            inc.append(t)
        own = [self.factors[fi] for fi in B.factors]
        fproj = [[(bpos[v], f.strides()[k]) for k, v in enumerate(f.scope)] for f in own]
        iproj = [[(bpos[v], t.strides()[k]) for k, v in enumerate(t.vars)] for t in inc]
        inner = 1
        for c in bcard:
            inner *= c
        nmul = max(0, len(own) + len(inc) - 1)
        prod_depth = len(own) + sum(t.depth for t in inc) + nmul
        out_depth = prod_depth + max(0, inner - 1)
        acc, any_sup = self._zero(), False
        digits = [0] * len(bvars)
        for flat in range(inner):
            if self.deadline is not None and (flat & 0xFFF) == 0:
                self.deadline()
            rem = flat
            for k in range(len(bvars)):
                digits[k] = rem // bst[k]; rem = rem % bst[k]
            val, dead = self._one(), False
            for fi, pm in enumerate(fproj):
                off = sum(digits[bk] * s for (bk, s) in pm)
                e = own[fi].table[off]
                if e == 0:
                    dead = True; break
                val = self._mul(val, self._enc(e))
            if not dead:
                for ti, pm in enumerate(iproj):
                    off = sum(digits[bk] * s for (bk, s) in pm)
                    if not inc[ti].support[off]:
                        dead = True; break
                    val = self._mul(val, inc[ti].vals[off])
            if dead:
                continue
            acc = self._add(acc, val) if any_sup else val
            any_sup = True
        return Table(vars=(), card=(), vals=[acc if any_sup else self._zero()],
                     depth=out_depth, support=[any_sup])

    # ---------- all-marginal readout ----------
    def read_marginal(self, var):
        """Sum the calibrated belief of var's home bag for EVERY state of var."""
        bags = self.plan.bags
        bi = self.plan.var_home[var]
        B = bags[bi]
        bvars = B.vars
        bcard = tuple(self.card[v] for v in bvars)
        bst = _strides(bcard)
        bpos = {v: k for k, v in enumerate(bvars)}
        inc = []
        for nb in ([B.parent] if B.parent >= 0 else []) + list(B.children):
            t = self.msg.get((nb, bi))
            if t is not None:
                inc.append(t)
        own = [self.factors[fi] for fi in B.factors]
        fproj = [[(bpos[v], f.strides()[k]) for k, v in enumerate(f.scope)] for f in own]
        iproj = [[(bpos[v], t.strides()[k]) for k, v in enumerate(t.vars)] for t in inc]
        vk = bpos[var]
        cv = self.card[var]
        inner = 1
        for c in bcard:
            inner *= c
        per_state_terms = inner // cv
        nmul = max(0, len(own) + len(inc) - 1)
        prod_depth = len(own) + sum(t.depth for t in inc) + nmul
        out_depth = prod_depth + max(0, per_state_terms - 1)

        counts = [self._zero() for _ in range(cv)]
        seen = [False] * cv
        digits = [0] * len(bvars)
        for flat in range(inner):
            if self.deadline is not None and (flat & 0xFFF) == 0:
                self.deadline()
            rem = flat
            for k in range(len(bvars)):
                digits[k] = rem // bst[k]; rem = rem % bst[k]
            val, dead = self._one(), False
            for fi, pm in enumerate(fproj):
                off = sum(digits[bk] * s for (bk, s) in pm)
                e = own[fi].table[off]
                if e == 0:
                    dead = True; break
                val = self._mul(val, self._enc(e))
            if not dead:
                for ti, pm in enumerate(iproj):
                    off = sum(digits[bk] * s for (bk, s) in pm)
                    if not inc[ti].support[off]:
                        dead = True; break
                    val = self._mul(val, inc[ti].vals[off])
            if dead:
                continue
            s = digits[vk]
            counts[s] = self._add(counts[s], val) if seen[s] else val
            seen[s] = True
        self.ops["readout"] += 1
        return counts, seen, out_depth
