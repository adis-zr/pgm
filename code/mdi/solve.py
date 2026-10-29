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
from mdi import config as K


def PRE_MOD():
    from mdi import preprocess as PRE
    return PRE


class Deadline(Exception):
    pass


class MemoryStop(Exception):
    pass


# ru_maxrss units differ by platform: bytes on darwin, KiB on linux. Probe once
# against the OS rather than guessing from the magnitude of the value.
def _probe_rss_scale():
    r = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    if sys.platform == "darwin":
        return 1
    return 1024

_RSS_SCALE = _probe_rss_scale()


def _rss_bytes():
    """Peak resident set of THIS process, in bytes (a high-water mark)."""
    return resource.getrusage(resource.RUSAGE_SELF).ru_maxrss * _RSS_SCALE


def rss_scale():
    return _RSS_SCALE


def _mk_deadline(t_end, cap_bytes, baseline=None,
                 allow_oversized=False):
    """Outer deadline plus a memory cap measured on the WHOLE process RSS.

    `baseline` is the RSS already in use when the solve began (interpreter,
    imported modules, the parsed model). The cap applies to the whole process,
    but a cap smaller than the baseline would fire immediately and meaninglessly,
    so the effective threshold is max(cap, baseline + cap/8) and the record
    states which applied.
    """
    base = _rss_bytes() if baseline is None else baseline
    # A declared cap is a LIMIT, never a starting point to be raised. Enlarging
    # it when the process already exceeds it meant an oversized process was
    # granted extra headroom precisely when it should have refused.
    eff = cap_bytes
    if cap_bytes and cap_bytes <= base and allow_oversized:
        # the caller will refuse after reporting its estimate; keep the
        # DECLARED cap so nothing is silently granted extra headroom
        eff = cap_bytes
    elif cap_bytes and cap_bytes <= base:
        raise MemoryStop(
            "the process already holds %d bytes, at or above the declared cap "
            "%d, so no work may begin; a declared cap is never enlarged "
            "because the current process is oversized" % (base, cap_bytes))

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
          plan_bytes_per_entry=None, preprocess=True):
    """Compute every singleton marginal under `evidence` with certified intervals."""
    t0 = time.time()
    stages = {}
    prog = progress or (lambda *a, **k: None)
    t_end = t0 + deadline_s
    rss_baseline = _rss_bytes()
    out = {"mode": mode, "eps": str(eps), "nvars": model.nvars,
           "evidence_vars": len(evidence), "stages": stages}
    # A declared cap at or below the process baseline is a refusal, but the
    # caller is owed the CONCRETE planning estimate that justifies it, so the
    # refusal is deferred until after planning rather than raised here. The
    # cap itself is never enlarged.
    _baseline_over_cap = bool(cap_bytes and cap_bytes <= rss_baseline)
    dl = _mk_deadline(t_end, cap_bytes, rss_baseline,
                      allow_oversized=True)

    # ---------- stage: input conversion ----------
    ts = time.time()
    model.validate()
    r = M.restrict(model, evidence)
    stages["input_conversion_s"] = time.time() - ts

    # ---------- stage: common exact preprocessing (contract C) ----------
    # Identical in every arm, so it improves the baseline the research routes
    # must beat. Zero approximation error; the checker rederives each identity
    # from the original bytes. On Pedigree_11 this removes 22 positive constants
    # and splits 13 exactly separable pairs, taking min_fill from width 24 to 20
    # and the largest bag from 33,554,432 to 2,097,152.
    ts = time.time()
    pre_scale = Fr(1)
    pre_identity = None
    if preprocess:
        from mdi import preprocess as PRE
        try:
            simp = PRE.simplify(r)
            PRE.verify_identities(r, simp)
            if simp.impossible is not None:
                out.update({"outcome": "ZERO_EVIDENCE_PROVED",
                            "reason": "factor %d is identically zero" % simp.impossible,
                            "elapsed_s": time.time() - t0})
                return out
            r = M.Restricted(model=model, evidence=dict(evidence),
                             factors=simp.factors, free=list(simp.free),
                             card=dict(simp.card), constant=r.constant,
                             impossible_factor=None)
            pre_scale = simp.scale
            pre_identity = simp.identity()
        except PRE.PreprocessError as e:
            out.update({"outcome": "NUMERICAL_REFUSAL",
                        "reason": "exact preprocessing failed its own identity "
                                  "check: %s" % e,
                        "elapsed_s": time.time() - t0})
            return out
    stages["preprocess_s"] = time.time() - ts
    out["preprocess"] = pre_identity
    out["preprocess_scale"] = str(pre_scale)
    prog("input", "%d free vars" % len(r.free))

    out["free_vars"] = len(r.free)
    out["zeros_after_evidence"] = sum(1 for f in r.factors for t in f.table
                                      if t == 0)

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
    if _baseline_over_cap:
        # the declared cap is at or below what the process already holds. The
        # cap is NEVER enlarged for that; refuse, with the concrete estimate.
        best = sel["candidates"][0]
        out.update({"outcome": "RESOURCE_BOUND",
                    "reason": "the process already holds %d bytes, at or above "
                              "the declared cap %d, so no work may begin; a "
                              "declared cap is never enlarged because the "
                              "current process is oversized"
                              % (rss_baseline, cap_bytes),
                    "best_candidate": best[0], "best_estimate": best[1],
                    "cap_bytes": cap_bytes,
                    "baseline_rss_bytes": rss_baseline,
                    "elapsed_s": time.time() - t0})
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
    B, Q, T = _exponent_bounds(r)
    out["exponent_bounds"] = {"B_sum_neg_log2_min_positive": B,
                              "Q_free_domain_log2": Q,
                              "T_sum_log2_max_entry": T,
                              "note": "lower side 2^-(B+Q), upper side 2^(T+Q); "
                                      "both are needed, and a guard is added"}
    guard = 256
    emin = -(B + Q + guard)
    emax = (T + Q + guard)
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
        # Total evidence weight: the product over components, times the exact
        # pinned constant, TIMES the exact scale that preprocessing removed.
        # `pre_scale` was recorded but never applied, so unary [2,2] reported
        # an original weight near 2 where the truth is 4. Marginals were
        # unaffected because the scale cancels in a ratio, but the published
        # normalizer was wrong by exactly that factor.
        Zlo, Zhi = Fr(r.constant) * Fr(pre_scale), Fr(r.constant) * Fr(pre_scale)
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
            # A checker that stopped before establishing containment has
            # verified NOTHING. Naming it VERIFIED_PARTIAL implied a verified
            # subset that no record identified.
            out["checker"] = {"status": "VERIFICATION_INCOMPLETE",
                              "reason": str(e),
                              "verified_coordinates": 0,
                              "verified_subset": None,
                              "note": "stopped before containment; no coordinate "
                                      "was independently verified"}
            out.update({"outcome": "RESOURCE_STOP",
                        "reason": "producer completed all requested enclosures "
                                  "but independent verification did not finish: "
                                  "%s" % e,
                        "producer_complete": True,
                        "independently_verified": False,
                        "elapsed_s": time.time() - t0})
            return out
    else:
        # Checking was DISABLED. The producer's own enclosures are not a
        # verification, so this must not be labelled verified.
        out["checker"] = {"status": "NOT_RUN",
                          "reason": "run_checker=False",
                          "verified_coordinates": 0}
        out.update({"outcome": "PRODUCER_COMPLETE_UNCHECKED",
                    "producer_complete": True,
                    "independently_verified": False,
                    "elapsed_s": time.time() - t0,
                    "peak_rss_bytes": _rss_bytes()})
        return out
    # `independently_verified` means the AGGREGATION itself was checked by a
    # second implementation. When the free joint space exceeded the declared
    # enumeration cap, producer and checker shared C.Engine's aggregate logic,
    # so a common-mode fault was undetectable -- and the run still returned
    # VERIFIED_ALL_MARGINALS with independently_verified=True. The label now
    # follows what actually ran.
    _agg_ok = bool((out.get("checker") or {}).get(
        "independent_aggregation_checked"))
    if _agg_ok:
        out.update({"outcome": "VERIFIED_ALL_MARGINALS",
                    "producer_complete": True,
                    "independently_verified": True,
                    "elapsed_s": time.time() - t0,
                    "peak_rss_bytes": _rss_bytes()})
    else:
        out.update({
            "outcome": "VERIFIED_SHARED_AGGREGATION_ONLY",
            "reason": "every coordinate passed interval containment, but the "
                      "independent AGGREGATION check could not run: the free "
                      "joint space exceeds the declared enumeration cap, so "
                      "producer and checker share one aggregate "
                      "implementation and a common-mode aggregation fault "
                      "would not be detected. This is NOT the contract's "
                      "complete independently verified status.",
            "producer_complete": True,
            "independently_verified": False,
            "elapsed_s": time.time() - t0,
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
    """Input-derived exponent bounds for the compiled schedule.

    B bounds a nonzero partial product/sum from BELOW by 2^-B: with mu_f the
    smallest strictly positive entry of factor f and mu_f >= 2^-B_f, correct
    ownership gives prod >= 2^-sum(B_f).

    A partial product can also be LARGE, so the upper side needs its own bound:
    with nu_f the largest entry and nu_f <= 2^T_f, a product over all factors is
    at most 2^sum(T_f), and summing over at most Q assignments multiplies by Q.
    Using only the lower bound (as a first version did) clamps emax far too
    tightly and makes a dense model refuse spuriously.
    """
    B = 0
    T = 0
    for f in r.factors:
        pos = [t for t in f.table if t > 0]
        if not pos:
            continue
        mu, nu = min(pos), max(pos)
        bf = 0
        x = Fr(mu)
        while x < 1 and bf <= (1 << 20):
            x *= 2; bf += 1
        B += bf
        tf = 0
        y = Fr(nu)
        while y > 1 and tf <= (1 << 20):
            y /= 2; tf += 1
        T += tf
    Q = 0
    for v in r.free:
        c = r.card[v]
        k = 0
        while (1 << k) < c:
            k += 1
        Q += k
    return B, Q, T


def validate_output_schema(model, evidence, iv, eps):
    """Contract B.1: validate the complete output schema BEFORE numerical work.

    Exact variable/state key sets, ordered finite rational endpoints inside
    [0,1], widths within eps, and full original-query coverage. Previously a
    missing row surfaced as a KeyError from deep inside the contraction, and a
    malformed row was only noticed after the expensive work had been done.
    """
    problems = []
    if not isinstance(iv, dict):
        return ["output is not a mapping from variable to interval rows"]
    want = set(range(model.nvars))
    got = set(iv)
    missing = sorted(want - got)
    extra = sorted(got - want)
    if missing:
        problems.append("missing output rows for variables %s" % missing[:8])
    if extra:
        problems.append("output rows for unknown variables %s" % extra[:8])
    for v in sorted(want & got):
        rows = iv[v]
        try:
            n = len(rows)
        except TypeError:
            problems.append("variable %d: output row is not a sequence" % v)
            continue
        if n != model.card[v]:
            problems.append("variable %d: %d states, model says %d"
                            % (v, n, model.card[v]))
            continue
        for a, pair in enumerate(rows):
            try:
                lo, hi = pair
            except (TypeError, ValueError):
                problems.append("variable %d state %d: not an endpoint pair" % (v, a))
                continue
            try:
                lo = Fr(lo); hi = Fr(hi)
            except (TypeError, ValueError):
                problems.append("variable %d state %d: endpoints are not exact "
                                "rationals" % (v, a))
                continue
            if lo > hi:
                problems.append("variable %d state %d: inverted endpoints "
                                "[%s, %s]" % (v, a, lo, hi))
            if lo < 0 or hi > 1:
                problems.append("variable %d state %d: endpoints outside [0,1] "
                                "[%s, %s]" % (v, a, lo, hi))
            if hi - lo > Fr(eps):
                problems.append("variable %d state %d: width %s exceeds eps %s"
                                % (v, a, hi - lo, eps))
        if v in evidence:
            st = evidence[v]
            for a, pair in enumerate(rows):
                lo, hi = Fr(pair[0]), Fr(pair[1])
                want_pt = Fr(1) if a == st else Fr(0)
                if lo != want_pt or hi != want_pt:
                    problems.append("variable %d state %d: observed variable not "
                                    "restored as an exact point mass" % (v, a))
    return problems


def _check(model, evidence, iv, eps, pl, p, cap_bytes, t_end, prog):
    """Independent interval contraction, rebuilt from the ORIGINAL model.

    Shares the validated decomposition and MPFR primitives (permitted), but
    rebuilds messages, support, counts and normalization independently, and
    never consumes producer values.
    """
    schema = validate_output_schema(model, evidence, iv, eps)
    if schema:
        raise A.NumericalRefusal("output schema invalid: %s" % "; ".join(schema[:4]))
    r = M.restrict(model, evidence)
    # the checker applies the SAME exact preprocessing and rederives its
    # identities from the original factors (never from the producer's output)
    try:
        from mdi import preprocess as PRE
        _simp = PRE.simplify(r)
        PRE.verify_identities(r, _simp)
        if _simp.impossible is None:
            r = M.Restricted(model=model, evidence=dict(evidence),
                             factors=_simp.factors, free=list(_simp.free),
                             card=dict(_simp.card), constant=r.constant,
                             impossible_factor=None)
    except Exception as e:
        raise A.NumericalRefusal("checker could not reproduce the exact "
                                 "preprocessing identities: %s" % e)
    # EXPLICIT zero-evidence check. Previously this relied on a numerical
    # positivity side effect, so a publication whose conditioning event has
    # probability zero could be accepted when that side effect did not fire.
    if r.impossible_factor is not None:
        raise A.NumericalRefusal(
            "checker refuses: restricted factor %d is identically zero, so the "
            "conditioning event has probability zero and no conditional "
            "distribution exists" % r.impossible_factor)
    if r.constant == 0:
        raise A.NumericalRefusal(
            "checker refuses: a fully pinned factor evaluates to exactly zero, "
            "so the conditioning event has probability zero")
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
    dl = _mk_deadline(t_end, cap_bytes, _rss_bytes())
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
    # INDEPENDENT CROSS-CHECK of the aggregation itself. The checker runs the
    # producer's C.Engine, so a defect in Engine.send/read_marginal would be
    # invisible to it: fresh values through the same aggregate implementation
    # are not the specified independence. Where the free domain is small
    # enough, recompute every marginal by DIRECT exact enumeration of the
    # preprocessed factors -- a different implementation with no shared
    # aggregation -- and require the engine's intervals to contain it.
    _indep = None
    _q = 1
    for v in r.free:
        _q *= r.card[v]
        if _q > K.CAPS["region_tuple_assignments"]:
            _q = None
            break
    if _q is not None:
        import itertools as _it
        order = sorted(r.free)
        _Z = Fr(0)
        _cnt = {}
        # Check the shared deadline BEFORE the loop and INSIDE it. Checking
        # only afterward meant all 4,096 assignments ran even when the
        # supplied callback was already expired at loop entry: the refusal
        # came after the overrun instead of bounding it.
        dl()
        _seen = 0
        for combo in _it.product(*[range(r.card[v]) for v in order]):
            _seen += 1
            if (_seen & 0xFF) == 0:
                dl()
            a = dict(zip(order, combo))
            wt = Fr(1)
            for f in r.factors:
                st = f.strides()
                off = sum(a[vv] * st[k] for k, vv in enumerate(f.scope))
                e = f.table[off]
                if e == 0:
                    wt = Fr(0)
                    break
                wt *= e
            if wt == 0:
                continue
            _Z += wt
            for vv in order:
                _cnt[(vv, a[vv])] = _cnt.get((vv, a[vv]), Fr(0)) + wt
        if _Z > 0:
            _indep = (_Z, _cnt)

    fails, nchk = [], 0
    for v in r.free:
        dl()
        counts, seen, depth = cread[v]
        los = [A.exact_fr(x[0]) if s else Fr(0) for x, s in zip(counts, seen)]
        his = [A.exact_fr(x[1]) if s else Fr(0) for x, s in zip(counts, seen)]
        tl, th = sum(los), sum(his)
        if th <= 0:
            raise A.NumericalRefusal("checker: zero total at variable %d" % v)
        # STRUCTURAL support, from the boolean flags rather than the numbers:
        # a state whose support is False contributes exactly zero, and if only
        # ONE state has support its probability is exactly 1. Deriving this
        # numerically gave [1 - 2^-85, 1] for a unary [0, 1/3], so the
        # producer's exact [1, 1] failed containment and a structurally
        # certain answer was refused.
        sup_states = [a for a in range(len(los)) if seen[a] and his[a] > 0]
        for a in range(len(los)):
            if not (seen[a] and his[a] > 0):
                clo = chi = Fr(0)          # structural zero, exactly
            elif len(sup_states) == 1:
                clo = chi = Fr(1)          # structural one, exactly
            else:
                other_lo = tl - los[a]
                clo = los[a] / th if los[a] > 0 else Fr(0)
                den = his[a] + other_lo
                chi = (his[a] / den) if den > 0 else Fr(0)
            if chi > 1:
                chi = Fr(1)
            if clo > chi:
                raise A.NumericalRefusal("checker produced an inverted interval")
            if _indep is not None:
                _Z, _cnt = _indep
                _q_exact = _cnt.get((v, a), Fr(0)) / _Z
                if not (clo <= _q_exact <= chi):
                    fails.append({
                        "var": v, "state": a,
                        "reason": "the engine's enclosure [%s, %s] does NOT "
                                  "contain the independently enumerated exact "
                                  "probability %s; the shared aggregation is "
                                  "wrong" % (clo, chi, _q_exact)})
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
    # The independent AGGREGATION cross-check only runs below the declared
    # enumeration cap. Above it, producer and checker share C.Engine's
    # aggregate logic, so a common-mode fault is invisible: the same injected
    # readout fault rejected at 12 binary variables and CERTIFIED (.75, .25)
    # at 13 against a uniform truth. The caller must be told, so this is
    # reported as a FACT about the check that ran, not left implicit.
    meta = {"checker_precision_bits": cp, "coordinates_checked": nchk,
            "independent_plan_rebuilt": True, "mode": "I",
            "shares": "validated decomposition + MPFR primitives",
            "borrows_producer_values": False,
            "independent_aggregation_checked": _indep is not None,
            "independent_aggregation_scope":
                ("direct exact enumeration of every free assignment"
                 if _indep is not None else
                 "NOT RUN: the free joint space exceeds the declared "
                 "enumeration cap, so producer and checker share the same "
                 "aggregate implementation and a common-mode aggregation "
                 "fault would not be detected")}
    del eng
    return (not fails), fails, meta


def verify_publication(model, evidence, iv, eps=Fr(1, 100), mode="I",
                       deadline_s=None, cap_bytes=None):
    """Standalone checker entry point (used by the rejection tests).

    `deadline_s` and `cap_bytes` carry the SHARED budget. They were hard-wired
    to a 300-second horizon and a 2 GiB cap, so identity checking ran outside
    the caller's budget entirely: an 80 ms checker under a 20 ms complete
    deadline still certified."""
    schema = validate_output_schema(model, evidence, iv, eps)
    if schema:
        return False, [{"reason": "output schema invalid",
                        "problems": schema[:8]}], {
            "independent_aggregation_checked": False,
            "rejected_before_checking": "output schema invalid"}
    r = M.restrict(model, evidence)
    if r.impossible_factor is not None or r.constant == 0:
        return False, [{"reason": "zero evidence weight: no conditional "
                                  "distribution exists, so any published "
                                  "conditional marginal is invalid"}], {
            "independent_aggregation_checked": False,
            "rejected_before_checking": "zero evidence weight"}
    # Build the reference plan on the SAME factor list `_check` will rebuild on,
    # i.e. after the common exact preprocessing. Building it on the raw factors
    # made the shapes differ and `_check` refused with "rebuilt a different
    # decomposition" on any model that preprocessing simplifies.
    try:
        _simp = PRE_MOD().simplify(r)
        PRE_MOD().verify_identities(r, _simp)
        rr = M.Restricted(model=model, evidence=dict(evidence),
                          factors=_simp.factors, free=list(_simp.free),
                          card=dict(_simp.card), constant=r.constant,
                          impossible_factor=None)
    except Exception as e:
        return False, [{"reason": "checker could not reproduce the exact "
                                  "preprocessing identities: %s" % e}], {
            "independent_aggregation_checked": False,
            "rejected_before_checking": "preprocessing identities"}
    adj = P.primal_graph(rr.free, rr.card, rr.factors)
    pl = P.build_plan("min_fill", P.order_min_fill(rr.free, rr.card, adj),
                      rr.free, rr.card, rr.factors)
    try:
        _cap = cap_bytes if cap_bytes is not None else (1 << 31)
        _end = (time.time() + float(deadline_s)) if deadline_s is not None \
            else (time.time() + 300)
        ok, fails, cmeta = _check(model, evidence, iv, eps, pl, 64, _cap,
                                  _end, lambda *a: None)
    except A.NumericalRefusal as e:
        # A refusal is a REJECTION of the publication, reported as such. Letting
        # it propagate made a caller see an exception rather than "not verified",
        # which is how a globally contradictory model (every factor individually
        # nonzero, Z = 0) escaped this entry point.
        return False, [{"reason": "checker refused: %s" % e}], {
            "independent_aggregation_checked": False,
            "refused": str(e)}
    # The checker's metadata is RETURNED, not discarded. `ok, fails, _` threw
    # away `independent_aggregation_checked`, so every caller had to guess
    # whether the independent check had actually run -- and the pipeline then
    # substituted {"kind": "identity"} and downgraded results whose exact
    # independent check HAD run and passed.
    #
    # A standalone success must also not be unqualified when the required
    # independent path was skipped.
    if ok and not cmeta.get("independent_aggregation_checked"):
        fails = list(fails) + [{
            "reason": "every coordinate passed interval containment, but the "
                      "independent AGGREGATION check did not run on this "
                      "input, so this is NOT an independently verified result",
            "independent_aggregation_checked": False}]
        ok = False
    return ok, fails, cmeta
