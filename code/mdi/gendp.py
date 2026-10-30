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
# SUPERSEDED (r15): not on any pipeline path; the general-residual statistic DP is collective_jt.statistic_evaluate over sparse_jt / dense_be with the statistic algebra.
# Retained for the direct controls that document its history.

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
    """Contract the residual, handling DISCONNECTED components.

    A retained hard constraint can split the residual graph. Refusing outright
    made the composed route decline whenever its retained factors disconnected
    the model, so the constraint was effectively unusable. Independent
    components multiply: Z = prod Z_c, and a marker in component c scales by
    the other components' totals.
    """
    roots = [b.idx for b in plan.bags if b.parent == -1]
    if len(roots) <= 1:
        return _run_component(plan, factors, card, cand, Q, queries, ctx,
                              deadline=deadline, cap_states=cap_states)
    # ---- DISCONNECTED residual, done correctly ----
    # Multiplying already-integrated component totals is WRONG: the collective
    # statistic S = sum_i f_i(z_i) sums over every variable, so
    # exp(-gamma S^2 / 2) couples all of them and a product of per-component
    # totals drops the cross terms of S^2. (That error published X3 at 0.5
    # against a true 0.3556.)
    #
    # The correct construction keeps each component's UNINTEGRATED statistic
    # distribution A_c(s), CONVOLVES them into the distribution of the total
    # statistic, and applies exp(sign*gamma*(s/Q)^2/2) once to that total. A
    # marked distribution replaces its own component in the same convolution,
    # so every cross term is retained.
    import copy as _copy
    comps = []
    for rt in roots:
        seen, stack = [], [rt]
        while stack:
            x = stack.pop()
            seen.append(x)
            stack.extend(plan.bags[x].children)
        comps.append(sorted(seen))
    var_comp, fac_comp = {}, {}
    for ci, bidx in enumerate(comps):
        for b in bidx:
            for v in plan.bags[b].vars:
                if v in var_comp and var_comp[v] != ci:
                    raise Declined("variable %d spans two components" % v)
                var_comp[v] = ci
            for fi in plan.bags[b].factors:
                if fi in fac_comp and fac_comp[fi] != ci:
                    raise Declined("factor %d spans two components" % fi)
                fac_comp[fi] = ci
    missing = [fi for fi in range(len(factors)) if fi not in fac_comp]
    if missing:
        raise Declined("factors %s belong to no component, so the residual "
                       "law would be incomplete" % missing[:4])

    cap = cap_states or K.CAPS["local_mass_entries"]
    per = []
    for ci, bidx in enumerate(comps):
        sub = _copy.copy(plan)
        remap = {b: k for k, b in enumerate(bidx)}
        newbags = []
        for b in bidx:
            nb = _copy.copy(plan.bags[b])
            nb.idx = remap[b]
            nb.parent = remap.get(plan.bags[b].parent, -1)
            nb.children = [remap[c] for c in plan.bags[b].children]
            newbags.append(nb)
        sub.bags = newbags
        sub.var_home = {v: remap[h] for v, h in plan.var_home.items()
                        if h in remap}
        q_sub = {v for v in queries if var_comp.get(v) == ci}
        acc, macc, cmeta = _run_component(
            sub, factors, card, cand, Q, q_sub, ctx, deadline=deadline,
            cap_states=cap_states, raw_statistics=True)
        if not acc:
            raise Declined("component %d has an empty statistic distribution"
                           % ci)
        per.append((acc, macc))

    def convolve(a, b):
        # The cap is enforced DURING construction and the deadline is checked
        # inside the loop. Testing `len(out) > cap` only after the full double
        # loop meant two 16-state components under a cap of 20 allocated all
        # 31 keys and performed 256 multiply/add pairs before refusing, with
        # no interior callback -- a correct result is not a resource-bounded
        # implementation.
        out = {}
        done = 0
        for sa, wa in a.items():
            if wa == 0:
                continue
            for sb, wb in b.items():
                if wb == 0:
                    continue
                k = sa + sb
                if k not in out and len(out) >= cap:
                    raise Declined(
                        "the convolved statistic support reached the declared "
                        "%d cap during construction (after %d products), so "
                        "this candidate is refused before completing it"
                        % (cap, done))
                nv = out.get(k, Fr(0)) + wa * wb
                # the DISCONNECTED convolution needs the same bit bound as the
                # connected accumulators: 40,001-bit input ratios returned
                # 80,130-bit masses against the declared 65,536-bit cap
                if (nv.numerator.bit_length() > K.CAPS["rational_bit_length"]
                        or nv.denominator.bit_length()
                        > K.CAPS["rational_bit_length"]):
                    raise Declined(
                        "a convolved statistic weight reached %d bits, above "
                        "the declared %d-bit cap"
                        % (max(nv.numerator.bit_length(),
                               nv.denominator.bit_length()),
                           K.CAPS["rational_bit_length"]))
                out[k] = nv
                done += 1
                if deadline is not None and (done & 0xFF) == 0:
                    deadline()
        return out

    # the TOTAL statistic distribution
    total = {0: Fr(1)}
    for acc, _m in per:
        total = convolve(total, acc)
        if deadline is not None:
            deadline()
    # a marked total replaces its own component's distribution
    marked_total = {}
    for ci, (acc, macc) in enumerate(per):
        for key, mdist in macc.items():
            cur = {0: Fr(1)}
            for cj, (acc2, _m2) in enumerate(per):
                cur = convolve(cur, mdist if cj == ci else acc2)
                if deadline is not None:
                    deadline()
            marked_total[key] = cur

    # apply the signed exponential ONCE, to the total statistic
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
    for stat, wv in total.items():
        if stat not in cache:
            cache[stat] = wfac(stat)
        lo, hi = cache[stat]
        Zlo += wv * lo
        Zhi += wv * hi
        for _b in (Zlo, Zhi):
            if (_b.numerator.bit_length() > K.CAPS["rational_bit_length"]
                    or _b.denominator.bit_length()
                    > K.CAPS["rational_bit_length"]):
                raise Declined(
                    "the weighted total reached %d bits, above the declared "
                    "%d-bit cap"
                    % (max(_b.numerator.bit_length(),
                           _b.denominator.bit_length()),
                       K.CAPS["rational_bit_length"]))
    if Zhi <= 0:
        raise Declined("the convolved total has nonpositive weight")
    out_marks = {}
    for key, dist in marked_total.items():
        mlo = mhi = Fr(0)
        for stat, wv in dist.items():
            if stat not in cache:
                cache[stat] = wfac(stat)
            lo, hi = cache[stat]
            mlo += wv * lo
            mhi += wv * hi
        out_marks[key] = (mlo, mhi)
    return (Zlo, Zhi), out_marks, {
        "components": len(comps),
        "multi_component": True,
        "total_statistic_support": len(total),
        "method": "per-component UNINTEGRATED statistic distributions "
                  "convolved, with exp(sign*gamma*(s/Q)^2/2) applied once to "
                  "the TOTAL statistic, so every cross term of S^2 is kept"}


def _run_component(plan, factors, card, cand, Q, queries, ctx: A.Ctx,
                   deadline=None, cap_states=None, raw_statistics=False):
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

    # CUMULATIVE work counter. The per-child counter reset before reaching
    # its callback threshold, so on a 14-leaf star every individual product
    # stayed below it and 420 ordinary plus 5,096 marked updates completed
    # with ZERO callbacks after an expired deadline. Small products repeated
    # many times must not evade the clock.
    work = {"n": 0}

    def tick(k=1):
        work["n"] += k
        if deadline is not None and (work["n"] & 0xFF) == 0:
            deadline()

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
            local_stat = 0
            for v in forget:
                local_stat += kq[v][digits[bpos[v]]]
            soff = 0
            for k, v in enumerate(sep):
                soff += digits[bpos[v]] * sst[k]

            # ---- the child offsets at this bag assignment ----
            coffs = []
            for (c, tab) in inc:
                cb = bags[c]
                cst = _strides(tuple(card[v] for v in cb.separator))
                o = 0
                for k, v in enumerate(cb.separator):
                    o += digits[bpos[v]] * cst[k]
                coffs.append(o)

            # ---- ORDINARY join: convolve every child's unmarked
            # distribution, AGGREGATING BY STATISTIC after each child.
            #
            # This was a LIST of (weight, statistic) pairs extended per child
            # and merged only at the end, so a 14-leaf binary star built
            # 16,384 simultaneous histories (65,532 appends) to represent just
            # 15 distinct statistic values -- exponential intermediate work
            # that directly defeats the statistic compression the
            # representation exists for. A dict keyed by the running
            # statistic keeps the state at the true support size.
            partials = {0: Fr(1)}
            for ci, (c, tab) in enumerate(inc):
                nxt = {}
                done = 0
                for ps, pw in partials.items():
                    for (ck, cs), cw in tab.items():
                        if ck != coffs[ci]:
                            continue
                        k2 = ps + cs
                        # Check BEFORE inserting a new key, and check the
                        # deadline inside the pair loop. Testing
                        # `len(partials) > cap` only after the whole child
                        # product meant a [2,16,16] model under a cap of 20
                        # built all 256 keys and performed all 256
                        # multiply-adds before refusing, with no interior
                        # callback.
                        if k2 not in nxt and len(nxt) >= cap:
                            raise Declined(
                                "the ordinary join reached the declared %d "
                                "statistic cap during construction (after %d "
                                "products at child %d)" % (cap, done, ci))
                        nxt[k2] = nxt.get(k2, Fr(0)) + pw * cw
                        done += 1
                        tick()
                partials = nxt
                if not partials:
                    break
                if deadline is not None:
                    deadline()          # child boundary
            for ps, pw in partials.items():
                key = (soff, ps + local_stat)
                # the FINAL accumulator is bounded too: the guards protected
                # only the temporary `nxt`, so two admissible 15-key supports
                # combined into 30 final keys under a cap of 16 before refusal
                if key not in out and len(out) >= cap:
                    raise Declined(
                        "the final message accumulator reached the declared "
                        "%d cap during construction" % cap)
                nv = out.get(key, Fr(0)) + w * pw
                if (nv.numerator.bit_length() > K.CAPS["rational_bit_length"]
                        or nv.denominator.bit_length()
                        > K.CAPS["rational_bit_length"]):
                    raise Declined(
                        "an accumulated message weight reached %d bits, above "
                        "the declared %d-bit cap"
                        % (max(nv.numerator.bit_length(),
                               nv.denominator.bit_length()),
                           K.CAPS["rational_bit_length"]))
                out[key] = nv
                tick()

            # ---- MARKED join: exactly ONE child supplies its marked
            # distribution and EVERY OTHER child supplies its ordinary one.
            #
            # The previous code multiplied a child's marked mass by `w` alone,
            # dropping every sibling's contribution. On a star with three
            # leaves that made the marked masses sum to 7 instead of the
            # correct 91, while the partition function stayed right.
            for v in forget:
                if v not in queries:
                    continue
                st = digits[bpos[v]]
                for ps, pw in partials.items():
                    key = (soff, ps + local_stat)
                    mk = out_marks.setdefault((v, st), {})
                    mk[key] = mk.get(key, Fr(0)) + w * pw
            for mi, (mc, mtab) in enumerate(inc):
                cmk = marks.get((mc, src), {})
                if not cmk:
                    continue
                # the product of the OTHER children's ordinary distributions
                # same aggregation for the OTHER children's product
                others = {0: Fr(1)}
                for ci, (c, tab) in enumerate(inc):
                    if ci == mi:
                        continue
                    nxt = {}
                    done = 0
                    for ps, pw in others.items():
                        for (ck, cs), cw in tab.items():
                            if ck != coffs[ci]:
                                continue
                            k2 = ps + cs
                            # same bounded insertion for the MARKED join
                            if k2 not in nxt and len(nxt) >= cap:
                                raise Declined(
                                    "the marked join reached the declared %d "
                                    "statistic cap during construction (after "
                                    "%d products)" % (cap, done))
                            nxt[k2] = nxt.get(k2, Fr(0)) + pw * cw
                            done += 1
                            tick()
                    others = nxt
                    if not others:
                        break
                    if deadline is not None:
                        deadline()      # marked child boundary
                if not others:
                    continue
                for (v, st), tabm in cmk.items():
                    mk = out_marks.setdefault((v, st), {})
                    for (ck, cs), cw in tabm.items():
                        if ck != coffs[mi]:
                            continue
                        for os, ow in others.items():
                            key = (soff, cs + os + local_stat)
                            mk[key] = mk.get(key, Fr(0)) + w * cw * ow
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

    # Every variable THIS component owns must have had its statistic inserted
    # exactly once. Checking against the whole model's variable set made a
    # disconnected component fail on the other components' variables.
    own_vars = sorted({v for b in bags for v in b.vars})
    missing = [v for v in own_vars if v not in inserted]
    if missing:
        raise Declined("variables %s never had their statistic inserted"
                       % missing[:5])
    extra = [v for v in sorted(inserted) if v not in own_vars]
    if extra:
        raise Declined("variables %s had a statistic inserted but are not in "
                       "this component" % extra[:5])

    if raw_statistics:
        # Return the UNINTEGRATED statistic distribution A_c(s) and the marked
        # distributions, WITHOUT applying exp(sign*gamma*(s/Q)^2/2). The
        # caller convolves components and applies the exponential to the TOTAL
        # statistic, which is what keeps the cross terms of S^2.
        acc = {}
        for (soff, stat), wv in root_msg.items():
            acc[stat] = acc.get(stat, Fr(0)) + wv
        macc = {}
        for key, tab in root_marks.items():
            d = {}
            for (soff, stat), wv in tab.items():
                d[stat] = d.get(stat, Fr(0)) + wv
            macc[key] = d
        own = sorted({v for b in bags for v in b.vars})
        return acc, macc, {"variables": own, "support": len(acc)}

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
