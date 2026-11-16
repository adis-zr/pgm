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
from mdi import budget as _BUDGET


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


def engine_class():
    """The dense engine class `_engine_for` instantiates on this host (the
    fault-injection controls patch THIS class, so the fault lands in the engine
    that actually executes)."""
    try:
        from mdi import vec_engine as V
        if V.AVAILABLE:
            return V.VecEngine
    except ImportError:
        pass
    return C.Engine


def _engine_for(plan, factors, ctx, **kw):
    """The dense engine in the layout that executes (2 November 2026, physical
    capacity policy): the vectorized layout (`vec_engine.VecEngine`, the same
    directed-rounding arithmetic and depth labels over numpy object arrays; its
    rounded values need not match the scalar engine's bit for bit, its enclosures
    are valid by the order-independent depth argument) when numpy is available,
    else the scalar `contract.Engine`."""
    try:
        from mdi import vec_engine as V
        if V.AVAILABLE:
            return V.VecEngine(plan, factors, ctx, **kw)
    except ImportError:
        pass
    return C.Engine(plan, factors, ctx, **kw)


def _exact_aggregation(r, pl2, dl, charge, cap_bytes, t_end):
    """The independent EXACT aggregation of the identity checker: the vectorized
    exact integer junction tree (`vec_engine.VecExact`) on the checker's own
    min-fill plan when the physical budget admits it (mdi.capacity forecast
    against the remaining wall and the RSS cap), else the sparse exact junction
    tree bounded by the meter's backstop. Returns ((Z, counts), scope) or None
    when the aggregation is not admitted (reported NOT RUN, never a pass)."""
    from mdi import capacity as CAP
    remaining = t_end - _BUDGET.DEFAULT_CLOCK[0]()
    # the same bounded occupancy probe the admission used (charged to the shared meter)
    occ = None
    if any(Fr(x) == 0 for f in r.factors for x in f.table):
        try:
            occ, _n = CAP.occupancy_probe(pl2, r.factors, r.card, deadline=dl, charge=charge)
        except ImportError:
            occ = None
    fc = CAP.forecast_identity(pl2, pl2, r.factors, r.card, r.free, occupancy=occ)
    ad = CAP.admit(fc, remaining, cap_bytes, CAP.rss_current_bytes(), rss_baseline_bytes=CAP.invocation_baseline_bytes(),
                   remaining_only=True)                 # the producer and the interval checker have already run
    if ad["aggregation"] != "FEASIBLE":
        return None, ("NOT RUN: the exact aggregation is not admitted by the physical budget: %s" % ad["aggregation_reason"])
    try:
        from mdi import vec_engine as V
        vec = V.AVAILABLE
    except ImportError:
        vec = False
    if vec:
        vx = V.VecExact(pl2, r.factors, r.card, deadline=dl, charge=charge).run()
        cnt = vx.counts(r.free)
        return (Fr(int(vx.Z)), {k: Fr(int(v)) for k, v in cnt.items()}), (
            "vectorized exact integer junction tree (a second aggregation implementation), %d entries visited, "
            "order %s, %d-bit total" % (vx.entries_visited, list(pl2.order)[:8], int(vx.Z).bit_length()))
    from mdi import sparse_jt as _SJ
    _tabs = [_SJ.table_from_factor(f, deadline=dl) for f in r.factors]
    _touched = {v for f in r.factors for v in f.scope}
    for v in r.free:
        if v not in _touched:
            _tabs.append(_SJ.Table((v,), {(c,): Fr(1) for c in range(r.card[v])}))
    try:
        _Z2, _mg, _jt = _SJ.all_marginals(_tabs, r.card, deadline=dl, entry_cap=K.CAPS["local_mass_entries"],
                                          order=list(pl2.order), charge=charge)
    except _SJ.SparseError:
        return None, "NOT RUN: the sparse exact junction tree refused (entry or bit backstop)"
    _cnt2 = {(v, a): _mg[v][a] for v in r.free for a in range(r.card[v]) if _mg[v][a] != 0}
    return (_Z2, _cnt2), ("sparse exact junction tree (a second aggregation implementation), %d entries built, order %s"
                          % (_jt.ops["entries_built"], _jt.order[:8]))


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
        if _BUDGET.DEFAULT_CLOCK[0]() > t_end:
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
          plan_bytes_per_entry=None, preprocess=True, program=None, charge=None):
    """Compute every singleton marginal under `evidence` with certified intervals.

    `program` (optional) is a PERSISTED identity program: {"order": [...],
    "precision": p, "emin": e, "emax": E}. When given, the elimination order
    and the arithmetic settings are TAKEN FROM IT -- planning and precision
    selection are not rerun -- and the plan built from that order must
    validate against the preprocessed factors; a program that does not
    describe a runnable schedule is a typed refusal.
    """
    t0 = _BUDGET.DEFAULT_CLOCK[0]()
    stages = {}
    prog = progress or (lambda *a, **k: None)
    t_end = t0 + deadline_s
    rss_baseline = _rss_bytes()
    out = {"mode": mode, "eps": str(eps), "nvars": model.nvars,
           "evidence_vars": len(evidence), "stages": stages}
    if deadline_s <= 0:
        # an EXHAUSTED shared deadline is never renewed: no work starts
        out.update({"outcome": "RESOURCE_STOP",
                    "reason": "the shared deadline was exhausted before the identity executor "
                              "started (%.3f s remaining)" % deadline_s,
                    "elapsed_s": 0.0, "peak_rss_bytes": rss_baseline})
        return out
    # A declared cap at or below the process baseline is a refusal, but the
    # caller is owed the CONCRETE planning estimate that justifies it, so the
    # refusal is deferred until after planning rather than raised here. The
    # cap itself is never enlarged.
    _baseline_over_cap = bool(cap_bytes and cap_bytes <= rss_baseline)
    dl = _mk_deadline(t_end, cap_bytes, rss_baseline,
                      allow_oversized=True)

    # ---------- stage: input conversion ----------
    ts = _BUDGET.DEFAULT_CLOCK[0]()
    model.validate()
    r = M.restrict(model, evidence)
    stages["input_conversion_s"] = _BUDGET.DEFAULT_CLOCK[0]() - ts

    # ---------- stage: common exact preprocessing (contract C) ----------
    # Identical in every arm, so it improves the baseline the research routes
    # must beat. Zero approximation error; the checker rederives each identity
    # from the original bytes. On Pedigree_11 this removes 22 positive constants
    # and splits 13 exactly separable pairs, taking min_fill from width 24 to 20
    # and the largest bag from 33,554,432 to 2,097,152.
    ts = _BUDGET.DEFAULT_CLOCK[0]()
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
                            "elapsed_s": _BUDGET.DEFAULT_CLOCK[0]() - t0})
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
                        "elapsed_s": _BUDGET.DEFAULT_CLOCK[0]() - t0})
            return out
    stages["preprocess_s"] = _BUDGET.DEFAULT_CLOCK[0]() - ts
    out["preprocess"] = pre_identity
    out["preprocess_scale"] = str(pre_scale)
    prog("input", "%d free vars" % len(r.free))

    out["free_vars"] = len(r.free)
    out["zeros_after_evidence"] = sum(1 for f in r.factors for t in f.table
                                      if t == 0)

    # a zero-evidence claim from the restriction passes through the common
    # original-model proof (the named factor re-derived from the original
    # tables at the evidence); an unproved claim is a refusal, not a terminal
    if r.impossible_factor is not None or r.constant == 0:
        from mdi import pipeline as _PLN
        proof = _PLN.zero_evidence_proof(model, evidence, r)
        out.update({"outcome": "ZERO_EVIDENCE_PROVED" if proof.get("proved") else "NUMERICAL_REFUSAL",
                    "reason": proof["reason"], "checker": proof,
                    "elapsed_s": _BUDGET.DEFAULT_CLOCK[0]() - t0})
        return out

    from mdi.guard import numerical_entry
    numerical_entry("solve.solve:identity-producer")
    # ---------- the quotienting pilot (3 Nov 2026): the declared constraint quotient governs ----------
    _r_orig = r
    _qdecl = (program or {}).get("quotient") if program is not None else None
    if _qdecl:
        from mdi import quotient as QT
        ts_q = _BUDGET.DEFAULT_CLOCK[0]()
        try:
            _d, _fresh = QT.recognize_cached(r.factors, r.free, r.card, deadline=dl, charge=charge)
        except QT.Contradiction as e:
            out.update({"outcome": "NUMERICAL_REFUSAL", "reason": "the declared quotient's recognition found a contradiction: %s" % e,
                        "elapsed_s": _BUDGET.DEFAULT_CLOCK[0]() - t0})
            return out
        except QT.QuotientError as e:
            out.update({"outcome": "NUMERICAL_REFUSAL", "reason": "the executor could not recognize the declared quotient: %s" % e,
                        "elapsed_s": _BUDGET.DEFAULT_CLOCK[0]() - t0})
            return out
        if _d["digest"] != str(_qdecl.get("digest")) or _d["fixed"] != {str(k): int(v) for k, v in _qdecl["fixed"].items()} \
                or _d["merged"] != {str(k): [int(v[0]), int(v[1])] for k, v in _qdecl["merged"].items()}:
            out.update({"outcome": "NUMERICAL_REFUSAL", "reason": "the executor's recognition differs from the program's declared quotient",
                        "elapsed_s": _BUDGET.DEFAULT_CLOCK[0]() - t0})
            return out
        try:
            r = QT.build_quotient(r, _d, deadline=dl)        # polled; the meter's saved bound covers the recognition scan, construction is not metered
        except QT.Contradiction as e:
            out.update({"outcome": "NUMERICAL_REFUSAL", "reason": "quotient construction: %s" % e, "elapsed_s": _BUDGET.DEFAULT_CLOCK[0]() - t0})
            return out
        stages["quotient_s"] = _BUDGET.DEFAULT_CLOCK[0]() - ts_q
        out["quotient"] = {"fixed": len(_d["fixed"]), "merged": len(_d["merged"]), "free": len(r.free), "recognition": _d["recognition"],
                           "reused_from_discovery": not _fresh, "constant_after_quotient": str(r.constant)}
        prog("quotient", "%d fixed, %d merged, %d free" % (len(_d["fixed"]), len(_d["merged"]), len(r.free)))
    # ---------- stage: planning ----------
    ts = _BUDGET.DEFAULT_CLOCK[0]()
    bpe = plan_bytes_per_entry or (64 if mode == "P" else 128)
    if program is not None:
        # the persisted program GOVERNS: build the recorded order, validate it
        order = [int(x) for x in program["order"]]
        if sorted(order) != sorted(r.free):
            out.update({"outcome": "NUMERICAL_REFUSAL",
                        "reason": "the persisted identity order does not name the "
                                  "preprocessed free variables",
                        "elapsed_s": _BUDGET.DEFAULT_CLOCK[0]() - t0})
            return out
        try:
            pl = P.build_plan("program", order, r.free, r.card, r.factors)
        except P.PlanError as e:
            out.update({"outcome": "NUMERICAL_REFUSAL",
                        "reason": "the persisted identity order is not a valid "
                                  "schedule: %s" % e, "elapsed_s": _BUDGET.DEFAULT_CLOCK[0]() - t0})
            return out
        est = P.byte_estimate(pl, bpe)
        sel = {"chosen": (pl, est), "candidates": [(pl.stats(), est)],
               "fits": est["estimate_bytes"] <= cap_bytes}
    else:
        sel = P.choose_plan(r.free, r.card, r.factors, bpe, cap_bytes)
    stages["planning_s"] = _BUDGET.DEFAULT_CLOCK[0]() - ts
    out["plan_candidates"] = sel["candidates"]
    if not sel["fits"]:
        best = sel["candidates"][0]
        out.update({"outcome": "RESOURCE_BOUND",
                    "reason": "no generic ordering fits the byte cap",
                    "best_candidate": best[0], "best_estimate": best[1],
                    "cap_bytes": cap_bytes, "elapsed_s": _BUDGET.DEFAULT_CLOCK[0]() - t0})
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
                    "elapsed_s": _BUDGET.DEFAULT_CLOCK[0]() - t0})
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
                    "elapsed_s": _BUDGET.DEFAULT_CLOCK[0]() - t0})
        return out
    if program is not None:
        # the recorded precision must be at least what the schedule's depth
        # bound requires; it is then USED, not rechosen
        rp = int(program["precision"])
        if rp < p:
            out.update({"outcome": "NUMERICAL_REFUSAL",
                        "reason": "the persisted precision %d is below the %d bits "
                                  "the schedule's depth bound requires" % (rp, p),
                        "elapsed_s": _BUDGET.DEFAULT_CLOCK[0]() - t0})
            return out
        p = rp
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
    if program is not None and program.get("emin") is not None:
        # the recorded exponent range must cover the input-derived one
        if int(program["emin"]) > emin or int(program["emax"]) < emax:
            out.update({"outcome": "NUMERICAL_REFUSAL",
                        "reason": "the persisted exponent range [%s, %s] does not "
                                  "cover the input-derived [%d, %d]"
                                  % (program["emin"], program["emax"], emin, emax),
                        "elapsed_s": _BUDGET.DEFAULT_CLOCK[0]() - t0})
            return out
        emin, emax = int(program["emin"]), int(program["emax"])
    try:
        ctx = A.Ctx(p, emin=emin, emax=emax)
    except Exception:
        ctx = A.Ctx(p)
    out["program_settings"] = {"order": list(pl.order), "precision": p,
                               "emin": ctx.emin, "emax": ctx.emax}
    out["mpfr"] = {"version": gmpy2.mpfr_version(), "precision": p,
                   "emin": ctx.emin, "emax": ctx.emax}
    out["memory"] = {"declared_cap_bytes": cap_bytes,
                     "rss_baseline_bytes": rss_baseline,
                     "effective_cap_bytes": dl.effective_cap,
                     "note": "whole-process RSS via getrusage; peak is a high-water "
                             "mark, so a short spike between checks is still captured, "
                             "but the value includes interpreter and module memory."}

    # ---------- stage: contraction ----------
    ts = _BUDGET.DEFAULT_CLOCK[0]()
    try:
        _declared = (program or {}).get("support") if program is not None else None
        if _declared:
            # the bounded pilot (3 Nov 2026): the program declares a compiled global support;
            # the executor compiles it itself (cached within the invocation, charged), refuses
            # unless the compilation IS the declared one, and runs the SPARSE engine over it
            from mdi import support as SP
            ts_s = _BUDGET.DEFAULT_CLOCK[0]()
            try:
                sup, _fresh = SP.compile_support_cached(pl, r.factors, r.card, deadline=dl, charge=charge)
            except SP.SupportError as e:
                raise A.NumericalRefusal("the executor could not compile the program's declared support: %s" % e)
            stages["support_compile_s"] = _BUDGET.DEFAULT_CLOCK[0]() - ts_s
            if sup.digest() != str(_declared.get("digest")) or sup.rows_per_bag() != [int(x) for x in _declared.get("rows_per_bag", [])]:
                raise A.NumericalRefusal("the executor's support compilation differs from the program's declared support")
            out["support"] = sup.counts()
            out["support"]["reused_from_discovery"] = not _fresh
            eng = SP.SparseEngine(pl, r.factors, ctx, sup, mode=mode,
                                  progress=lambda ph, n: prog(ph, "%d messages" % n), deadline=dl, charge=charge)
        else:
            eng = _engine_for(pl, r.factors, ctx, mode=mode,
                              progress=lambda ph, n: prog(ph, "%d messages" % n),
                              cap_bytes=cap_bytes, deadline=dl, charge=charge)
        out["engine_layout"] = getattr(eng, "layout", "scalar")
        nup = ndn = 0
        roots = []
        seen_comp = set()
        for b in pl.bags:
            if b.parent == -1:
                roots.append(b.idx)
        for rt in roots:
            nup += eng.upward(rt)
        stages["upward_s"] = _BUDGET.DEFAULT_CLOCK[0]() - ts
        prog("upward", "done, %d messages" % nup)

        # ---------- global positivity BEFORE publishing anything ----------
        ts = _BUDGET.DEFAULT_CLOCK[0]()
        comp_weights = []
        for rt in roots:
            t = eng.root_value(rt)
            comp_weights.append((rt, t))
        stages["evidence_weight_s"] = _BUDGET.DEFAULT_CLOCK[0]() - ts
        zero_comp = [rt for rt, t in comp_weights if not t.support[0]]
        if zero_comp:
            # A DEFINITIVE NEGATIVE RESULT needs a checked witness, exactly as
            # a marginal enclosure does. This returned ZERO_EVIDENCE_PROVED on
            # the producer's own root support with ZERO checker calls:
            # corrupting only that producer result made unary [1,2] -- whose Z
            # is exactly 3 and whose marginals are (1/3, 2/3) -- claim a
            # mathematical impossibility.
            #
            # The witness is verified INDEPENDENTLY from the original
            # restricted model by Boolean support elimination over the
            # preprocessed factors: the model has zero weight only if every
            # free assignment is killed by some factor's structural zero. A
            # resource refusal and a mathematical impossibility proof are
            # different results, so when the proof cannot be checked the
            # outcome is named unchecked rather than proved.
            # Reconstruct the checker's operands from the IMMUTABLE ORIGINAL
            # model and evidence. Passing `r` handed the helper the very
            # Factor objects the producer's Engine retains: zeroing one
            # working table inside Engine.upward made unary [1,2] -- still
            # [1,2] in the original model, Z = 3 -- return
            # ZERO_EVIDENCE_PROVED with
            # zero_support_independently_verified=True. Calling producer
            # working data "original" in a comment does not make it original.
            proved, why = _verify_zero_support_from_original(
                model, evidence, deadline=dl)
            if proved:
                out.update({
                    "outcome": "ZERO_EVIDENCE_PROVED",
                    "reason": "component rooted at bag %d has exact false "
                              "root support, INDEPENDENTLY verified: %s"
                              % (zero_comp[0], why),
                    "zero_support_independently_verified": True,
                    "components": len(roots),
                    "elapsed_s": _BUDGET.DEFAULT_CLOCK[0]() - t0})
            else:
                out.update({
                    "outcome": "ZERO_SUPPORT_UNCHECKED",
                    "reason": "the producer reported false root support at bag "
                              "%d, but that claim could NOT be independently "
                              "verified (%s). A mathematical impossibility is "
                              "not claimed."
                              % (zero_comp[0], why),
                    "zero_support_independently_verified": False,
                    "components": len(roots),
                    "elapsed_s": _BUDGET.DEFAULT_CLOCK[0]() - t0})
            return out
        # numeric positivity of every component
        for rt, t in comp_weights:
            v = t.vals[0]
            lo = v if mode == "P" else v[0]
            if lo <= 0:
                out.update({"outcome": "NUMERICAL_REFUSAL",
                            "reason": "component at bag %d has no certified positive "
                                      "lower bound (inconclusive, NOT impossibility)" % rt,
                            "elapsed_s": _BUDGET.DEFAULT_CLOCK[0]() - t0})
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
        ts = _BUDGET.DEFAULT_CLOCK[0]()
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
        stages["downward_s"] = _BUDGET.DEFAULT_CLOCK[0]() - ts
        out["peak_live_message_entries"] = eng.peak_live_entries
        prog("downward", "done, %d messages, %d marginals read"
             % (ndn, len(collected)))
        missing = [v for v in r.free if v not in collected]
        if missing:
            raise A.NumericalRefusal(
                "readout missed %d variables (first %s)" % (len(missing), missing[:5]))

        # ---------- stage: publication ----------
        ts = _BUDGET.DEFAULT_CLOCK[0]()
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
        if _qdecl:
            # RESTORE every original free variable from the quotient's rows: the representative keeps its
            # row, a merged variable's state s is the representative's s XOR parity, a fixed variable is
            # the exact point mass (zero approximation; the checker verifies this exactly)
            from mdi import quotient as QT
            iv = QT.restore(iv, _d, _r_orig.free, _r_orig.card)
        # restore observed variables as exact point masses (positivity established)
        for v, st in evidence.items():
            iv[v] = [(Fr(1), Fr(1)) if s == st else (Fr(0), Fr(0))
                     for s in range(model.card[v])]
        stages["publication_s"] = _BUDGET.DEFAULT_CLOCK[0]() - ts
        out["intervals"] = iv
        out["raw_intervals"] = raw
        out["ops"] = dict(eng.ops)
        out["max_width"] = max((hi - lo) for rows in iv.values() for lo, hi in rows)
        out["peak_rss_bytes"] = _rss_bytes()
        del eng
    except Deadline as e:
        out.update({"outcome": "TIMEOUT", "reason": str(e),
                    "elapsed_s": _BUDGET.DEFAULT_CLOCK[0]() - t0, "peak_rss_bytes": _rss_bytes()})
        return out
    except MemoryStop as e:
        out.update({"outcome": "MEMORY_STOP", "reason": str(e),
                    "elapsed_s": _BUDGET.DEFAULT_CLOCK[0]() - t0, "peak_rss_bytes": _rss_bytes()})
        return out
    except A.NumericalRefusal as e:
        out.update({"outcome": "NUMERICAL_REFUSAL", "reason": str(e),
                    "elapsed_s": _BUDGET.DEFAULT_CLOCK[0]() - t0, "peak_rss_bytes": _rss_bytes()})
        return out

    # ---------- stage: independent checker ----------
    if run_checker:
        ts = _BUDGET.DEFAULT_CLOCK[0]()
        try:
            ok, fails, cmeta = _check(model, evidence, iv, eps, pl, p, cap_bytes,
                                      t_end, prog)
            stages["checking_s"] = _BUDGET.DEFAULT_CLOCK[0]() - ts
            out["checker"] = {"status": "VERIFIED" if ok else "FAILED",
                              "containment_failures": len(fails),
                              "failures": fails[:8], **cmeta}
            if not ok:
                out.update({"outcome": "NUMERICAL_REFUSAL",
                            "reason": "independent checker rejected %d coordinates" % len(fails),
                            "elapsed_s": _BUDGET.DEFAULT_CLOCK[0]() - t0})
                return out
        except (Deadline, MemoryStop) as e:
            stages["checking_s"] = _BUDGET.DEFAULT_CLOCK[0]() - ts
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
                        "elapsed_s": _BUDGET.DEFAULT_CLOCK[0]() - t0})
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
                    "elapsed_s": _BUDGET.DEFAULT_CLOCK[0]() - t0,
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
                    "elapsed_s": _BUDGET.DEFAULT_CLOCK[0]() - t0,
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
            "elapsed_s": _BUDGET.DEFAULT_CLOCK[0]() - t0,
            "peak_rss_bytes": _rss_bytes()})
    return out


def _verify_zero_support_from_original(model, evidence, deadline=None):
    """Rebuild the restriction from the IMMUTABLE original model, then verify.

    The producer's Engine retains the Factor objects it was constructed with,
    so those tables are mutable producer state, not an independent operand.
    This re-reads the original model, re-applies the evidence with its own
    deep copy of every table, independently re-derives the preprocessing
    identities it relies on, and only then runs the support proof.
    """
    import copy as _copy
    base = M.restrict(model, dict(evidence))
    frozen = []
    for f in base.factors:
        frozen.append(M.Factor(scope=tuple(f.scope), card=tuple(f.card),
                               table=[Fr(x) for x in f.table],
                               origin=f.origin,
                               scale=getattr(f, "scale", Fr(1))))
    snap = M.Restricted(model=model, evidence=dict(evidence), factors=frozen,
                        free=list(base.free), card=dict(base.card),
                        constant=base.constant,
                        impossible_factor=base.impossible_factor)
    if snap.impossible_factor is not None:
        wf = None
        for f in frozen:
            if f.origin == snap.impossible_factor:
                wf = f
                break
        if wf is not None and all(Fr(t) == 0 for t in wf.table):
            return True, ("original factor %d is identically zero in the "
                          "re-read model" % snap.impossible_factor)
    if snap.constant == 0:
        return True, "a fully pinned original factor evaluates to exactly zero"
    return _verify_zero_support(snap, deadline=deadline)


def _verify_zero_support(r, deadline=None):
    """Independently verify that the restricted model has ZERO total weight.

    Boolean support elimination over the ORIGINAL preprocessed factors, with
    its own loop: an assignment survives only if every factor entry it selects
    is nonzero. The model is impossible exactly when no assignment survives.

    Bounded: where the free joint space is small enough the check is exact by
    enumeration; otherwise a structural sufficient condition is tried (a
    factor that is identically zero, or a variable with no supported state).
    When neither applies the claim is reported UNVERIFIED rather than proved.
    """
    from mdi import config as _K
    import itertools as _it
    # (a) an identically zero factor is a complete witness at any size
    for f in r.factors:
        if all(Fr(t) == 0 for t in f.table):
            return True, ("original factor %d on scope %s is identically zero"
                          % (getattr(f, "origin", -1), tuple(f.scope)))
    # (b) a variable with no supported state is a complete witness
    for v in sorted(r.card):
        alive = False
        for st in range(r.card[v]):
            ok = True
            for f in r.factors:
                if len(f.scope) != 1 or f.scope[0] != v:
                    continue
                if Fr(f.table[st]) == 0:
                    ok = False
                    break
            if ok:
                alive = True
                break
        if not alive:
            return True, ("variable %d has no supported state in any unary "
                          "factor" % v)
    # (c) a COMPLETED Boolean support contraction (§7.2): OR/AND elimination
    # over the factor supports on the checker's own sparse junction tree. It
    # costs elimination work rather than enumeration, and it is a complete
    # proof either way: a False total means NO assignment survives; a True
    # total exhibits positive support (the model is NOT impossible).
    joint = 1
    for v in sorted(r.card):
        joint *= r.card[v]
    if joint > _K.CAPS["region_tuple_assignments"]:
        try:
            from mdi import sparse_jt as _SJ
            tabs = []
            touched = {v for f in r.factors for v in f.scope}
            for f in r.factors:
                t = _SJ.table_from_factor(f, deadline=deadline)
                tabs.append(_SJ.Table(t.scope, {k: True for k in t.entries}))
            for v in sorted(r.card):
                if v not in touched:
                    tabs.append(_SJ.Table((v,), {(c,): True
                                                 for c in range(r.card[v])}))
            jt = _SJ.SparseJT(tabs, r.card, _SJ.Boolean, deadline=deadline,
                              entry_cap=_K.CAPS["checker_contraction_space"]
                              ).run(downward=False)
            alive = jt.total()
            if alive is None or not alive:
                return True, ("completed Boolean support contraction over %d "
                              "variables found no surviving assignment"
                              % len(r.card))
            return False, ("completed Boolean support contraction exhibits a "
                           "surviving assignment, so the model is NOT impossible")
        except _SJ.SparseError as e:
            return False, ("the free joint space exceeds the %d-assignment "
                           "enumeration cap and the Boolean support "
                           "contraction refused (%s); no structural witness "
                           "applies" % (_K.CAPS["region_tuple_assignments"], e))
    order = sorted(r.card)
    seen = 0
    for combo in _it.product(*[range(r.card[v]) for v in order]):
        seen += 1
        if deadline is not None and (seen & 0xFF) == 0:
            deadline()
        a = dict(zip(order, combo))
        alive = True
        for f in r.factors:
            st = f.strides()
            off = sum(a[v] * st[k] for k, v in enumerate(f.scope))
            if Fr(f.table[off]) == 0:
                alive = False
                break
        if alive:
            return False, ("assignment %s has strictly positive weight, so "
                           "the model is NOT impossible"
                           % {k: a[k] for k in order[:6]})
    return True, ("exhaustive support elimination over %d free assignments "
                  "found no surviving assignment" % joint)


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


def _check(model, evidence, iv, eps, pl, p, cap_bytes, t_end, prog,
           checker_precision=None, charge=None, support_declared=None, producer_order=None, quotient_declared=None):
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
    _r_orig = r
    _qmeta = None
    if quotient_declared:
        # the quotienting pilot (3 Nov 2026): the checker RE-DERIVES the closure of forced states and
        # binary relations from the ORIGINAL restricted, preprocessed factors with its own implementation,
        # refuses any declared relation it cannot derive, REBUILDS the quotient tables itself, checks the
        # restoration of every original row exactly, and runs its numerical verification on ITS quotient
        from mdi import quotient as _QT, quotient_check as _QC
        _dl0 = _mk_deadline(t_end, cap_bytes, _rss_bytes())
        try:
            _cl = _QC.rederive(r.factors, r.free, r.card, deadline=_dl0, charge=charge)
        except _QT.QuotientError as e:
            raise A.NumericalRefusal("checker could not re-derive the declared quotient: %s" % e)
        _bad = _QC.verify_declaration(_cl, quotient_declared, r.free, r.card)
        if _bad:
            raise A.NumericalRefusal("checker refuses: the program's declared quotient is not implied by the original factors (%s)" % "; ".join(_bad[:4]))
        _rfails = _QC.check_restoration(iv, quotient_declared, r.free, r.card)
        if _rfails:
            raise A.NumericalRefusal("checker refuses: %d published rows are not the exact restoration of their representative (%s)"
                                     % (len(_rfails), str(_rfails[:2])[:200]))
        r = _QC.build_quotient(r, quotient_declared, deadline=_dl0)
        _qmeta = {"rederived_fixed": len(_cl.fixed), "rederived_relations": len(_cl.rep), "entries_scanned": int(_cl.scanned),
                  "seconds": round(_cl.seconds, 4), "declared_matches": True, "quotient_free": len(r.free),
                  "restoration_checked_rows": len(_r_orig.free)}
        # the checker's OWN min-fill schedule over the quotient's representatives
        _adjq = P.primal_graph(r.free, r.card, r.factors)
        pl = P.build_plan("min_fill", P.order_min_fill(r.free, r.card, _adjq), r.free, r.card, r.factors)
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
    # INPUT-TABLE INTERPRETATION (3 November 2026): the checker verifies, with its
    # own stride arithmetic, that the shared vectorized layout helper addresses the
    # same original table entries it does, on every factor and on a bag ordering
    # different from the scope; a disagreement is a refusal before any arithmetic
    try:
        from mdi import vec_engine as _V
        if _V.AVAILABLE:
            _bad = _V.verify_layout_interpretation(r.factors, r.card)
            if _bad:
                raise A.NumericalRefusal("checker refuses: the layout helper's axis interpretation of %d factor table(s) "
                                         "differs from the checker's stride arithmetic: %s" % (len(_bad), _bad[0]))
    except ImportError:
        pass
    cp = max(80, p + 16) if checker_precision is None else int(checker_precision)
    if cp < 8:
        raise A.NumericalRefusal("checker precision %d is not usable" % cp)
    ctx = A.Ctx(cp)
    dl = _mk_deadline(t_end, cap_bytes, _rss_bytes())
    _crows = None
    if support_declared:
        # the bounded pilot (3 Nov 2026): the program declares a compiled support. The checker
        # RECONSTRUCTS the support recurrences itself (its own placement arithmetic and
        # traversal; charged to its meter; capped) and refuses unless the reconstruction is
        # exactly the declared support -- completeness, including omitted entries -- then runs
        # its interval contraction and its exact aggregation over ITS OWN rows.
        from mdi import support as _SP, support_check as _SC
        # the declaration is made on the PRODUCER's saved order; when the checker's own
        # order differs, the completeness check reconstructs on the producer's order and the
        # checker's numerical passes use a second reconstruction on its own plan (both
        # charged and capped); when the orders agree one reconstruction serves both
        _porder = [int(x) for x in (producer_order or [])]
        try:
            if _porder and _porder != [int(x) for x in pl2.order]:
                _plp = P.build_plan("program", _porder, r.free, r.card, r.factors)
                _prow, _pscan, _pel = _SC.reconstruct_support(_plp, r.factors, r.card, deadline=dl, charge=charge)
                _bad = _SC.verify_declaration(_plp, _prow, support_declared)
                del _prow
            else:
                _plp = pl2
                _pscan = _pel = 0
            _cstats = {}
            _crows, _cscan, _cel = _SC.reconstruct_support(pl2, r.factors, r.card, deadline=dl, charge=charge, stats=_cstats)
            if _plp is pl2:
                _bad = _SC.verify_declaration(pl2, _crows, support_declared)
        except _SP.SupportError as e:
            raise A.NumericalRefusal("checker could not reconstruct the declared support: %s" % e)
        except P.PlanError as e:
            raise A.NumericalRefusal("checker could not rebuild the producer's declared order: %s" % e)
        if _bad:
            raise A.NumericalRefusal("checker refuses: the program's declared support is not the independently reconstructed "
                                     "global support (%s)" % "; ".join(_bad[:4]))
        _cscan += _pscan
        _cel += _pel
        _cs = _SP.Support(pl2, r.card, _crows, {}, _cscan, _cel, 0)
        eng = _SP.SparseEngine(pl2, r.factors, ctx, _cs, mode="I", deadline=dl,
                               progress=lambda ph, n: prog("check-" + ph, "%d" % n), charge=charge)
    else:
        eng = _engine_for(pl2, r.factors, ctx, mode="I", deadline=dl,
                          progress=lambda ph, n: prog("check-" + ph, "%d" % n),
                          charge=charge)                 # the checker's messages hit the SHARED meter
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
                if charge is not None:
                    charge(256)                 # enumeration assignments are metered entries
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
        if charge is not None and (_seen & 0xFF):
            charge(_seen & 0xFF)                # the partial batch is flushed
        if _Z > 0:
            _indep = (_Z, _cnt)
    _indep_scope = ("direct exact enumeration of every free assignment"
                    if _indep is not None else None)
    _not_run = ("NOT RUN: the free joint space exceeds the declared enumeration cap and the exact "
                "aggregation did not run, so producer and checker share the same aggregate "
                "implementation and a common-mode aggregation fault would not be detected")
    if _indep is None:
        # ABOVE the enumeration cap: a STRUCTURAL second implementation. The
        # sparse exact junction tree (sparse_jt) shares no aggregation code
        # with C.Engine -- different data layout, schedule construction and
        # arithmetic (exact integers) -- so its marginals are an independent
        # recomputation at elimination cost rather than enumeration cost. It
        # is admitted against the PHYSICAL budget (mdi.capacity, AMENDMENTS[0]);
        # when the forecast or the run exceeds it, the independent check is
        # reported as NOT RUN, never as a pass.
        # The interval engine's own retained state (converted factor tables,
        # message dictionary) has served its last use -- every readout row is in
        # `cread` -- so it is released BEFORE the aggregation's admission reads
        # the current resident set: a stage's forecast competes with what is
        # actually still live, not with a finished engine's caches.
        for _attr in ("_fac", "msg"):
            _d = getattr(eng, _attr, None)
            if isinstance(_d, dict):
                _d.clear()
        import gc as _gc
        _gc.collect()
        try:
            if _crows is not None:
                # the sparse EXACT aggregation over the checker's own reconstructed rows
                from mdi import support_check as _SC2
                _vx = _SC2.SparseExact(pl2, r.factors, r.card, _crows, deadline=dl, charge=charge).run()
                _cnt = _vx.counts(r.free)
                _agg = (Fr(int(_vx.Z)), {k: Fr(int(v)) for k, v in _cnt.items()})
                _agg_scope = ("sparse exact integer junction tree over the checker's own reconstructed global support (a second "
                              "aggregation implementation), %d rows, %d entries visited, order %s, %d-bit total"
                              % (sum(int(x.size) for x in _crows.values()), _vx.entries_visited, list(pl2.order)[:8], int(_vx.Z).bit_length()))
            else:
                _agg, _agg_scope = _exact_aggregation(r, pl2, dl, charge, cap_bytes, t_end)
            if _agg is not None:
                _indep, _indep_scope = _agg, _agg_scope
            else:
                _not_run = _agg_scope
        except _BUDGET.BudgetExceeded:
            raise                                   # a shared-meter stop is a RESOURCE outcome, never "not run"
        except (A.NumericalRefusal, MemoryError) as _e:
            _indep = None
            _not_run = "NOT RUN: the exact aggregation refused: %s" % str(_e)[:160]
        except Exception as _e:        # a refusal of the independent path
            if isinstance(_e, (Deadline, MemoryStop)):
                raise
            _indep = None
            _not_run = "NOT RUN: %s: %s" % (type(_e).__name__, str(_e)[:160])

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
    if _qmeta is not None:
        # the merged / fixed variables' coordinates, checked EXACTLY against their representatives' rows
        nchk += sum(int(_r_orig.card[v]) for v in _r_orig.free if v not in set(r.free))
    # The independent AGGREGATION cross-check only runs below the declared
    # enumeration cap. Above it, producer and checker share C.Engine's
    # aggregate logic, so a common-mode fault is invisible: the same injected
    # readout fault rejected at 12 binary variables and CERTIFIED (.75, .25)
    # at 13 against a uniform truth. The caller must be told, so this is
    # reported as a FACT about the check that ran, not left implicit.
    # EXPOSURE (isolated experimental branch nd-certificate-2026-11-05; additive metadata only): the independent
    # aggregation's exact total with its scale metadata, so a caller can reconcile it to ORIGINAL weight units:
    # W(x) = restricted_constant * preprocess_scale * prod(simplified factors)(x); the junction-tree aggregations
    # scale every simplified factor by the LCM of its denominators (VecExact / SparseExact), the enumeration path
    # does not. Z_original_units = Z_aggregate / aggregate_scale_denominator * preprocess_scale * restricted_constant
    # (not reconciled when a quotient was declared: the quotient's own constant is then in play).
    _zmeta = None
    if _indep is not None:
        _Zs, _cnts = _indep
        _den = 1
        if not str(_indep_scope).startswith("direct exact enumeration"):
            import math as _math
            for _f in r.factors:
                _L = 1
                for _qv in _f.table:
                    _dq = Fr(_qv).denominator
                    _L = _L * _dq // _math.gcd(_L, _dq)
                _den *= _L
        _zmeta = {"Z_aggregate": str(_Zs), "aggregate_scale_denominator": str(_den), "preprocess_scale": str(_simp.scale),
                  "restricted_constant": str(_r_orig.constant), "scope": _indep_scope,
                  "Z_original_units": (str(Fr(_Zs) / _den * _simp.scale * _r_orig.constant) if _qmeta is None else None),
                  "counts_original_units": ({"%d:%d" % (int(k[0]), int(k[1])): str(Fr(v) / _den * _simp.scale * _r_orig.constant) for k, v in _cnts.items()}
                                            if _qmeta is None else None),
                  "note": "exact rationals as strings; counts are the exact unnormalized numerators of each free coordinate; None when a quotient was declared"}
    meta = {"checker_precision_bits": cp, "coordinates_checked": nchk, "exact_total": _zmeta,
            "independent_plan_rebuilt": True, "mode": "I",
            "shares": "validated decomposition + MPFR primitives" + (" + the sparse engine class over the checker's OWN reconstructed rows" if _crows is not None else ""),
            "borrows_producer_values": False,
            "quotient_rederived": _qmeta,
            "support_reconstructed": (None if _crows is None else {"rows_total": int(sum(int(x.size) for x in _crows.values())),
                                                                   "scan_positions": int(_cscan), "seconds": round(_cel, 4), "declared_matches": True,
                                                                   # the checker reconstruction's own reservation peak (persisted from 3 Nov closeout on;
                                                                   # the pair's run_record predates it)
                                                                   "peak_working_bytes": int(_cstats.get("peak_working_bytes", 0))}),
            # every normalizing division above is guarded: a zero upper total
            # is a refusal (raised), and a ratio is formed only when its
            # denominator is proved positive; so reaching this point proves
            # every denominator used was positive
            "positive_denominators": True,
            "independent_aggregation_checked": _indep is not None,
            "independent_aggregation_scope":
                (_indep_scope if _indep is not None else _not_run)}
    del eng
    return (not fails), fails, meta


def verify_publication(model, evidence, iv, eps=Fr(1, 100), mode="I",
                       deadline_s=None, cap_bytes=None, checker_precision=None, charge=None, program=None):
    """Standalone checker entry point (used by the rejection tests).

    `deadline_s` and `cap_bytes` carry the SHARED budget. They were hard-wired
    to a 300-second horizon and a 2 GiB cap, so identity checking ran outside
    the caller's budget entirely: an 80 ms checker under a 20 ms complete
    deadline still certified."""
    from mdi.guard import numerical_entry
    numerical_entry('solve.verify_publication:identity-checker')
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
        _end = (_BUDGET.DEFAULT_CLOCK[0]() + float(deadline_s)) if deadline_s is not None \
            else (_BUDGET.DEFAULT_CLOCK[0]() + 300)
        ok, fails, cmeta = _check(model, evidence, iv, eps, pl, 64, _cap,
                                  _end, lambda *a: None,
                                  checker_precision=checker_precision, charge=charge,
                                  support_declared=((program or {}).get("support") if program is not None else None),
                                  producer_order=((program or {}).get("order") if program is not None else None),
                                  quotient_declared=((program or {}).get("quotient") if program is not None else None))
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
