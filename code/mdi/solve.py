"""Top-level solve(): plan, contract, publish, and independently check.

Spec sections 1-4. Reference marginals never enter planning, arithmetic,
precision choice or stopping.
"""
from __future__ import annotations
import sys, time, os, resource
sys.set_int_max_str_digits(0)
from fractions import Fraction as Fr
import gmpy2
from gmpy2 import mpfr
from mdi import model as M, plan as P, arith as A, contract as C


class Deadline(Exception):
    pass


class MemoryStop(Exception):
    pass


def _rss_bytes():
    r = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    return r if r > 1 << 40 else r * 1024      # darwin reports bytes, linux KiB


def _mk_deadline(t_end, cap_bytes, baseline=None):
    """Outer deadline plus a memory cap measured on the WHOLE process RSS.

    `baseline` is the RSS already in use when the solve began (interpreter,
    imported modules, the parsed model). The cap applies to the whole process,
    but a cap smaller than the baseline would fire immediately and meaninglessly,
    so the effective threshold is max(cap, baseline + cap/8) and the record
    states which applied.
    """
    base = _rss_bytes() if baseline is None else baseline
    eff = cap_bytes
    if cap_bytes and cap_bytes <= base:
        eff = base + max(cap_bytes // 8, 1 << 24)

    def check():
        if time.time() > t_end:
            raise Deadline("outer deadline exceeded")
        if eff:
            cur = _rss_bytes()
            if cur > eff:
                raise MemoryStop("process RSS %d exceeded effective cap %d "
                                 "(declared %d, baseline %d)" % (cur, eff, cap_bytes, base))
    check.effective_cap = eff
    check.baseline = base
    return check


def solve(model, evidence, eps=Fr(1, 100), mode="P", cap_bytes=8 * (1 << 30),
          deadline_s=600.0, p_min=64, progress=None, run_checker=True,
          plan_bytes_per_entry=None):
    """Compute every singleton marginal under `evidence` with certified intervals."""
    t0 = time.time()
    stages = {}
    prog = progress or (lambda *a, **k: None)
    t_end = t0 + deadline_s
    rss_baseline = _rss_bytes()
    dl = _mk_deadline(t_end, cap_bytes, rss_baseline)

    # ---------- stage: input conversion ----------
    ts = time.time()
    model.validate()
    r = M.restrict(model, evidence)
    stages["input_conversion_s"] = time.time() - ts
    prog("input", "%d free vars" % len(r.free))

    out = {"mode": mode, "eps": str(eps), "nvars": model.nvars,
           "free_vars": len(r.free), "evidence_vars": len(evidence),
           "stages": stages, "zeros_after_evidence":
               sum(1 for f in r.factors for t in f.table if t == 0)}

    # an all-zero restricted factor proves zero evidence weight immediately
    if r.impossible_factor is not None:
        out.update({"outcome": "ZERO_EVIDENCE_PROVED",
                    "reason": "restricted factor %d is identically zero" % r.impossible_factor,
                    "elapsed_s": time.time() - t0})
        return out
    if r.constant == 0:
        out.update({"outcome": "ZERO_EVIDENCE_PROVED",
                    "reason": "a fully pinned factor evaluates to exactly zero",
                    "elapsed_s": time.time() - t0})
        return out

    # ---------- stage: planning ----------
    ts = time.time()
    bpe = plan_bytes_per_entry or (64 if mode == "P" else 128)
    sel = P.choose_plan(r.free, r.card, r.factors, bpe, cap_bytes)
    stages["planning_s"] = time.time() - ts
    out["plan_candidates"] = sel["candidates"]
    if not sel["fits"]:
        best = sel["candidates"][0]
        out.update({"outcome": "RESOURCE_BOUND",
                    "reason": "no generic ordering fits the byte cap",
                    "best_candidate": best[0], "best_estimate": best[1],
                    "cap_bytes": cap_bytes, "elapsed_s": time.time() - t0})
        return out
    pl, est = sel["chosen"]
    out["plan"] = pl.stats()
    out["plan_estimate"] = est
    prog("plan", "%s w=%d largest_bag=%d est=%.2f GiB"
         % (pl.name, pl.induced_width, pl.largest_bag_entries,
            est["estimate_bytes"] / (1 << 30)))

    # ---------- precision selection (before expensive work) ----------
    # conservative depth bound from the compiled schedule
    E_max = _compiled_depth_bound(pl, r)
    out["compiled_depth_bound"] = E_max
    try:
        p = A.choose_precision(E_max, eps, p_min)
    except A.NumericalRefusal as e:
        out.update({"outcome": "NUMERICAL_REFUSAL", "reason": str(e),
                    "elapsed_s": time.time() - t0})
        return out
    out["precision_bits"] = p
    # exponent range from input-derived bounds
    B, Q = _exponent_bounds(r)
    out["exponent_bounds"] = {"B_sum_neg_log2_min_positive": B,
                              "Q_free_domain_log2": Q}
    guard = 64
    emin = -(B + Q + guard)
    emax = (B + Q + guard)
    try:
        ctx = A.Ctx(p, emin=emin, emax=emax)
    except Exception:
        ctx = A.Ctx(p)
    out["mpfr"] = {"version": gmpy2.mpfr_version(), "precision": p,
                   "emin": ctx.emin, "emax": ctx.emax}
    out["memory"] = {"declared_cap_bytes": cap_bytes,
                     "rss_baseline_bytes": rss_baseline,
                     "effective_cap_bytes": dl.effective_cap,
                     "note": "whole-process RSS via getrusage; peak is a high-water "
                             "mark, so a short spike between checks is still captured, "
                             "but the value includes interpreter and module memory."}

    # ---------- stage: contraction ----------
    ts = time.time()
    try:
        eng = C.Engine(pl, r.factors, ctx, mode=mode,
                       progress=lambda ph, n: prog(ph, "%d messages" % n),
                       cap_bytes=cap_bytes, deadline=dl)
        nup = ndn = 0
        roots = []
        seen_comp = set()
        for b in pl.bags:
            if b.parent == -1:
                roots.append(b.idx)
        for rt in roots:
            nup += eng.upward(rt)
        stages["upward_s"] = time.time() - ts
        prog("upward", "done, %d messages" % nup)

        # ---------- global positivity BEFORE publishing anything ----------
        ts = time.time()
        comp_weights = []
        for rt in roots:
            t = eng.root_value(rt)
            comp_weights.append((rt, t))
        stages["evidence_weight_s"] = time.time() - ts
        zero_comp = [rt for rt, t in comp_weights if not t.support[0]]
        if zero_comp:
            out.update({"outcome": "ZERO_EVIDENCE_PROVED",
                        "reason": "component rooted at bag %d has exact false root support"
                                  % zero_comp[0],
                        "components": len(roots), "elapsed_s": time.time() - t0})
            return out
        # numeric positivity of every component
        for rt, t in comp_weights:
            v = t.vals[0]
            lo = v if mode == "P" else v[0]
            if lo <= 0:
                out.update({"outcome": "NUMERICAL_REFUSAL",
                            "reason": "component at bag %d has no certified positive "
                                      "lower bound (inconclusive, NOT impossibility)" % rt,
                            "elapsed_s": time.time() - t0})
                return out
        # total evidence weight interval (product over components x exact constant)
        Zlo, Zhi = Fr(r.constant), Fr(r.constant)
        for rt, t in comp_weights:
            L = A.lam(t.depth, p)
            if mode == "P":
                v = A.exact_fr(t.vals[0])
                Zlo *= v; Zhi *= v / L
            else:
                Zlo *= A.exact_fr(t.vals[0][0]); Zhi *= A.exact_fr(t.vals[0][1])
        out["evidence_weight_interval"] = (Zlo, Zhi)
        out["components"] = len(roots)

        # ---------- downward pass with INTERLEAVED readout ----------
        # Each bag's variables are read the moment that bag is calibrated, so
        # its messages can be freed straight after: live memory then follows the
        # planner's peak-live estimate instead of retaining every message.
        ts = time.time()
        collected = {}
        home_vars = {}
        for v in r.free:
            home_vars.setdefault(pl.var_home[v], []).append(v)

        def _on_calibrated(bag):
            for vv in home_vars.get(bag, ()):
                dl()
                collected[vv] = eng.read_marginal(vv)

        for rt in roots:
            ndn += eng.downward(rt, on_calibrated=_on_calibrated)
        stages["downward_s"] = time.time() - ts
        out["peak_live_message_entries"] = eng.peak_live_entries
        prog("downward", "done, %d messages, %d marginals read"
             % (ndn, len(collected)))
        missing = [v for v in r.free if v not in collected]
        if missing:
            raise A.NumericalRefusal(
                "readout missed %d variables (first %s)" % (len(missing), missing[:5]))

        # ---------- stage: publication ----------
        ts = time.time()
        iv, raw = {}, {}
        prod_half = eps / 2
        expand = eps / 8
        for v in r.free:
            dl()
            counts, seen, depth = collected[v]
            L = A.lam(depth, p)
            if mode == "P":
                vals = [A.exact_fr(x) if s else Fr(0) for x, s in zip(counts, seen)]
                tot = sum(vals)
                if tot <= 0:
                    raise A.NumericalRefusal("variable %d has zero total count" % v)
                rows = []
                for a in range(len(vals)):
                    Aa = vals[a]
                    Cc = tot - Aa
                    rows.append(A.marginal_interval(Aa, Cc, L))
            else:
                los = [A.exact_fr(x[0]) if s else Fr(0) for x, s in zip(counts, seen)]
                his = [A.exact_fr(x[1]) if s else Fr(0) for x, s in zip(counts, seen)]
                tl, th = sum(los), sum(his)
                if th <= 0:
                    raise A.NumericalRefusal("variable %d has zero upper total" % v)
                rows = []
                for a in range(len(los)):
                    # outward ratio with a proved positive denominator
                    den_hi = th - his[a] + his[a]
                    lo = los[a] / th if th > 0 else Fr(0)
                    other_lo = tl - los[a]
                    hi = his[a] / (his[a] + other_lo) if (his[a] + other_lo) > 0 else Fr(0)
                    if los[a] == 0:
                        lo = Fr(0)
                    if hi > 1:
                        hi = Fr(1)
                    if lo > hi:
                        raise A.NumericalRefusal("inverted raw interval at var %d state %d" % (v, a))
                    rows.append((lo, hi))
            raw[v] = rows
            pub = []
            for (lo, hi) in rows:
                if lo == hi and (lo == 0 or lo == 1):
                    pub.append((lo, hi))                 # structural exactness kept
                else:
                    if hi - lo > prod_half:
                        raise A.NumericalRefusal(
                            "raw producer width %s exceeds eps/2 at var %d" % (hi - lo, v))
                    pub.append(A.publish(lo, hi, expand, eps))
            iv[v] = pub
        # restore observed variables as exact point masses (positivity established)
        for v, st in evidence.items():
            iv[v] = [(Fr(1), Fr(1)) if s == st else (Fr(0), Fr(0))
                     for s in range(model.card[v])]
        stages["publication_s"] = time.time() - ts
        out["intervals"] = iv
        out["raw_intervals"] = raw
        out["ops"] = dict(eng.ops)
        out["max_width"] = max((hi - lo) for rows in iv.values() for lo, hi in rows)
        out["peak_rss_bytes"] = _rss_bytes()
        del eng
    except Deadline as e:
        out.update({"outcome": "TIMEOUT", "reason": str(e),
                    "elapsed_s": time.time() - t0, "peak_rss_bytes": _rss_bytes()})
        return out
    except MemoryStop as e:
        out.update({"outcome": "MEMORY_STOP", "reason": str(e),
                    "elapsed_s": time.time() - t0, "peak_rss_bytes": _rss_bytes()})
        return out
    except A.NumericalRefusal as e:
        out.update({"outcome": "NUMERICAL_REFUSAL", "reason": str(e),
                    "elapsed_s": time.time() - t0, "peak_rss_bytes": _rss_bytes()})
        return out

    # ---------- stage: independent checker ----------
    if run_checker:
        ts = time.time()
        try:
            ok, fails, cmeta = _check(model, evidence, iv, eps, pl, p, cap_bytes,
                                      t_end, prog)
            stages["checking_s"] = time.time() - ts
            out["checker"] = {"status": "VERIFIED" if ok else "FAILED",
                              "containment_failures": len(fails),
                              "failures": fails[:8], **cmeta}
            if not ok:
                out.update({"outcome": "NUMERICAL_REFUSAL",
                            "reason": "independent checker rejected %d coordinates" % len(fails),
                            "elapsed_s": time.time() - t0})
                return out
        except (Deadline, MemoryStop) as e:
            stages["checking_s"] = time.time() - ts
            out["checker"] = {"status": "INCOMPLETE", "reason": str(e)}
            out.update({"outcome": "VERIFIED_PARTIAL",
                        "reason": "producer completed but the checker could not finish: %s" % e,
                        "elapsed_s": time.time() - t0})
            return out
    out.update({"outcome": "VERIFIED_ALL_MARGINALS", "elapsed_s": time.time() - t0,
                "peak_rss_bytes": _rss_bytes()})
    return out


def _compiled_depth_bound(pl, r):
    """Conservative E bound dominating the actual loop and reduction order.

    Each message: product over owned factors and incoming messages, then a
    SEQUENTIAL sum over the eliminated interior. Depths accumulate up the tree.
    """
    bags = pl.bags
    card = pl.card
    own = {}
    for b in bags:
        own[b.idx] = len(b.factors)
    depth = {}
    # process children before parents
    order = sorted(range(len(bags)), key=lambda i: -i)
    for b in bags:
        pass
    def rec(i, seen):
        if i in depth:
            return depth[i]
        if i in seen:
            raise P.PlanError("cycle while bounding depth")
        seen.add(i)
        kids = [rec(c, seen) for c in bags[i].children]
        n_in = len(kids)
        nmul = max(0, own[i] + n_in - 1)
        prod = own[i] + sum(kids) + nmul
        inner = 1
        for v in bags[i].vars:
            if v not in bags[i].separator:
                inner *= card[v]
        depth[i] = prod + max(0, inner - 1)
        return depth[i]
    worst = 0
    for b in bags:
        worst = max(worst, rec(b.idx, set()))
    # the readout adds one more product+sum layer at a home bag
    extra = 0
    for b in bags:
        inner = 1
        for v in b.vars:
            inner *= card[v]
        nb = (1 if b.parent >= 0 else 0) + len(b.children)
        nmul = max(0, own[b.idx] + nb - 1)
        d = own[b.idx] + sum(depth[c] for c in b.children) + \
            (depth.get(b.parent, 0) if b.parent >= 0 else 0) + nmul + max(0, inner - 1)
        extra = max(extra, d)
    return max(worst, extra)


def _exponent_bounds(r):
    """B = sum over factors of B_f with mu_f >= 2^-B_f; Q = log2 of free domain."""
    B = 0
    for f in r.factors:
        pos = [t for t in f.table if t > 0]
        if not pos:
            continue
        mu = min(pos)
        # smallest integer B_f with mu >= 2^-B_f
        bf = 0
        x = Fr(mu)
        while x < 1:
            x *= 2; bf += 1
            if bf > 1 << 20:
                break
        B += bf
    Q = 0
    for v in r.free:
        c = r.card[v]
        k = 0
        while (1 << k) < c:
            k += 1
        Q += k
    return B, Q


def _check(model, evidence, iv, eps, pl, p, cap_bytes, t_end, prog):
    """Independent interval contraction, rebuilt from the ORIGINAL model.

    Shares the validated decomposition and MPFR primitives (permitted), but
    rebuilds messages, support, counts and normalization independently, and
    never consumes producer values.
    """
    r = M.restrict(model, evidence)
    # independent re-derivation of the bag tree from the same order
    adj = P.primal_graph(r.free, r.card, r.factors)
    pl2 = P.build_plan(pl.name, list(pl.order), r.free, r.card, r.factors)
    P.validate_plan(pl2, r.factors)
    # independent binding checks
    if pl2.induced_width != pl.induced_width or len(pl2.bags) != len(pl.bags):
        raise A.NumericalRefusal("checker rebuilt a different decomposition")
    for v in r.free:
        if v not in pl2.var_home:
            raise A.NumericalRefusal("checker found no home bag for variable %d" % v)
    cp = max(80, p + 16)
    ctx = A.Ctx(cp)
    dl = _mk_deadline(t_end, cap_bytes)
    eng = C.Engine(pl2, r.factors, ctx, mode="I", deadline=dl,
                   progress=lambda ph, n: prog("check-" + ph, "%d" % n))
    roots = [b.idx for b in pl2.bags if b.parent == -1]
    for rt in roots:
        eng.upward(rt)
    for rt in roots:
        t = eng.root_value(rt)
        if not t.support[0] or t.vals[0][0] <= 0:
            raise A.NumericalRefusal("checker could not establish component positivity")
    chome = {}
    for v in r.free:
        chome.setdefault(pl2.var_home[v], []).append(v)
    cread = {}

    def _c_on_cal(bag):
        for vv in chome.get(bag, ()):
            dl()
            cread[vv] = eng.read_marginal(vv)

    for rt in roots:
        eng.downward(rt, on_calibrated=_c_on_cal)
    cmissing = [v for v in r.free if v not in cread]
    if cmissing:
        raise A.NumericalRefusal("checker readout missed %d variables" % len(cmissing))
    fails, nchk = [], 0
    for v in r.free:
        dl()
        counts, seen, depth = cread[v]
        los = [A.exact_fr(x[0]) if s else Fr(0) for x, s in zip(counts, seen)]
        his = [A.exact_fr(x[1]) if s else Fr(0) for x, s in zip(counts, seen)]
        tl, th = sum(los), sum(his)
        if th <= 0:
            raise A.NumericalRefusal("checker: zero total at variable %d" % v)
        for a in range(len(los)):
            other_lo = tl - los[a]
            clo = los[a] / th if los[a] > 0 else Fr(0)
            den = his[a] + other_lo
            chi = (his[a] / den) if den > 0 else Fr(0)
            if chi > 1:
                chi = Fr(1)
            if clo > chi:
                raise A.NumericalRefusal("checker produced an inverted interval")
            plo, phi = iv[v][a]
            nchk += 1
            # the published interval must contain the checker's enclosure
            if not (plo <= clo and chi <= phi):
                # structural exactness is allowed to match exactly
                if not (plo == phi == clo == chi):
                    fails.append({"var": v, "state": a,
                                  "published": [str(plo), str(phi)],
                                  "checker": [str(clo), str(chi)]})
            if not (0 <= plo <= phi <= 1):
                fails.append({"var": v, "state": a, "reason": "endpoints not ordered in [0,1]"})
            if phi - plo > eps:
                fails.append({"var": v, "state": a, "reason": "width exceeds eps"})
    # evidence restoration and key coverage
    for v, st in evidence.items():
        for s in range(model.card[v]):
            nchk += 1
            want = (Fr(1), Fr(1)) if s == st else (Fr(0), Fr(0))
            if tuple(iv[v][s]) != want:
                fails.append({"var": v, "state": s, "reason": "evidence not restored exactly"})
    for v in range(model.nvars):
        if v not in iv or len(iv[v]) != model.card[v]:
            fails.append({"var": v, "reason": "missing or wrong-length output row"})
    meta = {"checker_precision_bits": cp, "coordinates_checked": nchk,
            "independent_plan_rebuilt": True, "mode": "I",
            "shares": "validated decomposition + MPFR primitives",
            "borrows_producer_values": False}
    del eng
    return (not fails), fails, meta


def verify_publication(model, evidence, iv, eps=Fr(1, 100), mode="I"):
    """Standalone checker entry point (used by the rejection tests)."""
    r = M.restrict(model, evidence)
    adj = P.primal_graph(r.free, r.card, r.factors)
    pl = P.build_plan("min_fill", P.order_min_fill(r.free, r.card, adj),
                      r.free, r.card, r.factors)
    ok, fails, _ = _check(model, evidence, iv, eps, pl, 64, 1 << 31,
                          time.time() + 300, lambda *a: None)
    return ok, fails
