"""General-residual owned-statistic DP (contract §E.5).

The product-residual DP multiplies unary tables only. This one runs on a VALID
ELIMINATION SCHEDULE, so a residual with retained pair or higher-arity factors
is admissible.

Each variable's integer statistic is inserted EXACTLY ONCE, at the bag that
eliminates it (when it is forgotten). A message is indexed by (separator
assignment, accumulated statistic), so joining two children convolves their
DISJOINT forgotten statistics exactly, with no second rounding. The signed
quadratic exponential is applied only at the root.
"""
from __future__ import annotations
import sys
sys.set_int_max_str_digits(0)
from fractions import Fraction as Fr
from mdi import arith as A, config as K, collective as CO


class Declined(Exception):
    pass


def _strides(card):
    st = [1] * len(card)
    acc = 1
    for k in range(len(card) - 1, -1, -1):
        st[k] = acc
        acc *= card[k]
    return st


def run(plan, factors, card, cand, Q, queries, ctx: A.Ctx, deadline=None,
        cap_states=None):
    """Contract the residual on `plan`, carrying integer statistics.

    Returns (Z_interval, marker_intervals, meta). Masses stay NONNEGATIVE; the
    signed exponential enters only at the root.
    """
    if cand.rank != 1:
        raise Declined("general-residual DP implemented for rank 1 in this build")
    cap = cap_states or K.CAPS["local_mass_entries"]
    kq = CO.round_features(cand, sorted(card), Q)[0]
    bags = plan.bags
    roots = [b.idx for b in bags if b.parent == -1]
    if len(roots) != 1:
        raise Declined("general-residual DP needs a single component; got %d"
                       % len(roots))

    # messages[(child,parent)] = {(sep_assignment, statistic): weight}
    messages = {}
    marks = {}            # (child,parent) -> {(var,state): {key: weight}}
    inserted = set()      # every variable's statistic inserted exactly once

    def post_order(root):
        seq, stack = [], [root]
        while stack:
            x = stack.pop()
            seq.append(x)
            stack.extend(bags[x].children)
        return list(reversed(seq))

    def send(src, dst_or_none):
        b = bags[src]
        bvars = b.vars
        bcard = tuple(card[v] for v in bvars)
        bst = _strides(bcard)
        bpos = {v: k for k, v in enumerate(bvars)}
        sep = b.separator if dst_or_none is not None else ()
        scard = tuple(card[v] for v in sep)
        sst = _strides(scard)
        own = [factors[fi] for fi in b.factors]
        fproj = [[(bpos[v], f.strides()[k]) for k, v in enumerate(f.scope)]
                 for f in own]
        inc = []
        for c in b.children:
            t = messages.get((c, src))
            if t is None:
                raise Declined("missing message %d->%d" % (c, src))
            inc.append((c, t))
        # the variables this bag forgets: its own eliminated variable
        forget = [v for v in bvars if v not in sep]
        for v in forget:
            if v in inserted:
                raise Declined("variable %d's statistic would be inserted twice"
                               % v)
        bsize = 1
        for c in bcard:
            bsize *= c
        out = {}
        out_marks = {}
        digits = [0] * len(bvars)
        for flat in range(bsize):
            if deadline is not None and (flat & 0xFFF) == 0:
                deadline()
            rem = flat
            for k in range(len(bvars)):
                digits[k] = rem // bst[k]
                rem %= bst[k]
            w = Fr(1)
            dead = False
            for fi, pm in enumerate(fproj):
                off = 0
                for (bk, s) in pm:
                    off += digits[bk] * s
                e = own[fi].table[off]
                if e == 0:
                    dead = True
                    break
                w *= e
            if dead:
                continue
            # this bag's own forgotten statistics, inserted ONCE here
            local_stat = 0
            for v in forget:
                local_stat += kq[v][digits[bpos[v]]]
            soff = 0
            for k, v in enumerate(sep):
                soff += digits[bpos[v]] * sst[k]
            # join the children: convolve their DISJOINT statistics exactly
            partials = [((), Fr(1), 0)]
            for (c, tab) in inc:
                cb = bags[c]
                cst = _strides(tuple(card[v] for v in cb.separator))
                coff = 0
                for k, v in enumerate(cb.separator):
                    coff += digits[bpos[v]] * cst[k]
                nxt = []
                for (_, pw, ps) in partials:
                    for (ck, cs), cw in tab.items():
                        if ck != coff:
                            continue
                        nxt.append(((), pw * cw, ps + cs))
                partials = nxt
                if not partials:
                    break
            for (_, pw, ps) in partials:
                key = (soff, ps + local_stat)
                val = w * pw
                out[key] = out.get(key, Fr(0)) + val
            # markers: a variable forgotten here, or carried from a child
            for v in forget:
                if v not in queries:
                    continue
                st = digits[bpos[v]]
                for (_, pw, ps) in partials:
                    key = (soff, ps + local_stat)
                    mk = out_marks.setdefault((v, st), {})
                    mk[key] = mk.get(key, Fr(0)) + w * pw
            for (c, tab) in inc:
                cmk = marks.get((c, src), {})
                cb = bags[c]
                cst = _strides(tuple(card[v] for v in cb.separator))
                coff = 0
                for k, v in enumerate(cb.separator):
                    coff += digits[bpos[v]] * cst[k]
                for (v, st), tabm in cmk.items():
                    for (ck, cs), cw in tabm.items():
                        if ck != coff:
                            continue
                        # the sibling weights that accompany this marker
                        for (_, pw, ps) in partials:
                            pass
                        key = (soff, cs + local_stat)
                        mk = out_marks.setdefault((v, st), {})
                        mk[key] = mk.get(key, Fr(0)) + w * cw
            if len(out) > cap:
                raise Declined("message support %d exceeded the %d cap"
                               % (len(out), cap))
        for v in forget:
            inserted.add(v)
        return out, out_marks

    order = post_order(roots[0])
    for b in order:
        if deadline is not None:
            deadline()
        if b == roots[0]:
            continue
        msg, mk = send(b, bags[b].parent)
        messages[(b, bags[b].parent)] = msg
        marks[(b, bags[b].parent)] = mk
    root_msg, root_marks = send(roots[0], None)

    missing = [v for v in sorted(card) if v not in inserted]
    if missing:
        raise Declined("variables %s never had their statistic inserted"
                       % missing[:5])

    # apply the signed quadratic exponential at the ROOT only
    s_k, g_k = cand.signs[0], cand.gammas[0]
    import gmpy2

    def wfac(stat):
        S = Fr(stat, Q)
        x = Fr(s_k) * g_k * S * S / 2
        with ctx.D:
            lo = gmpy2.exp(gmpy2.mpfr(gmpy2.mpq(x.numerator, x.denominator)))
        with ctx.U:
            hi = gmpy2.exp(gmpy2.mpfr(gmpy2.mpq(x.numerator, x.denominator)))
        return A.exact_fr(lo), A.exact_fr(hi)

    cache = {}
    Zlo = Zhi = Fr(0)
    for (soff, stat), wv in root_msg.items():
        if stat not in cache:
            cache[stat] = wfac(stat)
        lo, hi = cache[stat]
        Zlo += wv * lo
        Zhi += wv * hi
    out_marks = {}
    for key, tab in root_marks.items():
        mlo = mhi = Fr(0)
        for (soff, stat), wv in tab.items():
            if stat not in cache:
                cache[stat] = wfac(stat)
            lo, hi = cache[stat]
            mlo += wv * lo
            mhi += wv * hi
        out_marks[key] = (mlo, mhi)
    meta = {"statistics_inserted": len(inserted),
            "root_support": len(root_msg),
            "distinct_statistics": len({s for _, s in root_msg}),
            "Q": Q, "retained_factors_handled": len(factors),
            "note": "each variable's statistic inserted exactly once at the bag "
                    "that forgets it; joins convolve disjoint statistics with no "
                    "second rounding; the signed exponential applies at the root"}
    return (Zlo, Zhi), out_marks, meta
