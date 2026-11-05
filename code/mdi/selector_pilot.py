"""OPT-IN PILOT (4 November 2026; disabled by default; NOT part of the accepted selector): observed planning-cost
accounting, pre-allocation refusal and optional-state lifetime for the frozen selector policy.

This separately pinned pilot changes pipeline.py through opt-in hooks; the accepted snapshot remains separate. `enable()` replaces two attributes of `mdi.pipeline` that `_solve` looks up at call
time -- `_select_route` (the selector) and `run_loaded` (the execution boundary) -- with the pilot's versions; `disable()` (or the
`enabled()` context manager) restores them. The admission RULES and the frozen `SELECTOR_POLICY` constants are read, never
changed; the pilot adds (1) NON-OVERLAPPING observations for named planning steps -- the pre-window gate, recognition, quotient
construction / planning / pricing / preflight / admission, both support compilations, pricing, program and record creation, the
discovery gap -- named scopes report wall, shared-counter charge delta and the bytes the mechanism reports; the enclosing interval retains unassigned time; (2) a PREFLIGHT before
the quotient's optional dense occupancy probe: a conservative full-occupancy forecast (every message entry at full bits) that, when
it already admits, makes the probe unnecessary, and otherwise DECLINES the candidate without starting that occupancy probe (a missed opportunity, reported);
prospective work / byte estimates are context only, not storage bounds;
(3) an optional-state manifest (cache keys created by the probes) and a cleanup before execution that releases every optional
object the selected record does not need, charged and RSS-sampled (an observation: freeing references does not guarantee the
allocator returns pages).

The optional scopes form a diagnostic subtotal, not exact incremental E. The planning envelope includes mandatory
work and unassigned gaps from selector entry to cleanup completion before execution (or at pre-execution abandonment).
Complete supervised invocation time remains the experimental outcome.

This is infrastructure for LOSS PROTECTION, not a new inference advantage: a complete one-second optional window is an EMPIRICAL
pilot target, not a wall-time theorem; the frozen 20 s window stays the policy; unresolved physical overshoot terms are named in
the block (`unresolved_overshoot`).
"""
from __future__ import annotations
import time, gc, contextlib
from fractions import Fraction as Fr
from mdi import pipeline as PLN, plan as P, capacity as CAPX, budget as B

# Pilot policy for the quotient's OPTIONAL dense occupancy probe (repair of 4 Nov 2026): the conservative full-occupancy forecast
# either admits (then the probe is unnecessary) or the candidate is DECLINED -- a possibly missed opportunity, reported. No
# entry / byte "allowance" is used as a storage bound: summed bag domains omit operand multiplicity and the largest-bag byte figure
# omits converted factors, retained separators and other live optional state. Those figures are REPORTED as context only
# (`prospective_probe`), in their own units (domain entries; operand-weighted entries; an object-array byte estimate).
OBJECT_ARRAY_BYTES_PER_ENTRY = 8 + 32           # one pointer plus one small Python int object per entry (an estimate, not a measurement)

_INSTALLED = [False]
_ORIG = {}
_STATE = {"baseline_keys": None, "blk": None, "open_record": None, "released": False}


def enable():
    """Install the pilot: the selector, the execution boundary and the opt-in lifecycle hooks of `mdi.pipeline._PILOT_HOOKS`
    (binding-time admission, per-record stage-4 begin / end incl. failed exits, selection, terminal)."""
    if not _INSTALLED[0]:
        _ORIG["_select_route"] = PLN._select_route
        _ORIG["run_loaded"] = PLN.run_loaded
        PLN._select_route = select_route
        PLN.run_loaded = run_loaded
        PLN._PILOT_HOOKS.update({"admission": _hook_admission, "record_begin": _hook_record_begin, "record_end": _hook_record_end,
                                 "select_begin": _hook_select_begin, "select_end": _hook_select_end, "selected": _hook_selected, "terminal": _hook_terminal})
        _INSTALLED[0] = True


def disable():
    if _INSTALLED[0]:
        PLN._select_route = _ORIG["_select_route"]
        PLN.run_loaded = _ORIG["run_loaded"]
        PLN._PILOT_HOOKS.clear()
        _INSTALLED[0] = False


@contextlib.contextmanager
def enabled():
    enable()
    try:
        yield
    finally:
        disable()


class _Scopes:
    """Sequential, non-overlapping cost scopes: wall seconds (monotonic), shared-counter charge delta, reported bytes."""

    def __init__(self, bg):
        self.bg = bg
        self.rows = []
        self._open = None

    def begin(self, name, kind):
        assert self._open is None, "scopes must not overlap"
        self._open = {"scope": name, "kind": kind, "t0": time.monotonic(), "used0": int(self.bg.used.get("pricing_entries", 0)), "bytes": None, "note": None}

    def end(self, note=None, bytes_=None, status="done"):
        s = self._open; self._open = None
        s["wall_s"] = round(time.monotonic() - s.pop("t0"), 6)
        s["charged_entries"] = int(self.bg.used.get("pricing_entries", 0)) - s.pop("used0")
        s["status"] = status
        if note is not None:
            s["note"] = str(note)[:240]
        if bytes_ is not None:
            s["bytes"] = bytes_
        self.rows.append(s)
        return s

    def abort(self, status, note):
        if self._open is not None:
            self.end(note=note, status=status)

    def total(self, kind=None):
        return round(sum(r["wall_s"] for r in self.rows if kind is None or r["kind"] == kind), 6)


def _cache_keys():
    from mdi import support as SP, quotient as QT
    return {"support": set(SP._SUPPORT_CACHE), "recognition": set(QT._RECOGNITION_CACHE), "occupancy": set(CAPX._OCCUPANCY_CACHE)}


def _retained_bytes_estimate():
    """Bytes of the optional objects the caches retain (rows arrays, declarations, occupancy dicts): an estimate from the
    objects' own sizes, not a measurement of RSS."""
    from mdi import support as SP, quotient as QT
    b = 0
    for sup in SP._SUPPORT_CACHE.values():
        try:
            b += sum(int(a.nbytes) for a in sup.rows.values())
        except Exception:
            pass
    b += sum(len(str(d)) for d in QT._RECOGNITION_CACHE.values())
    b += sum(len(occ) * 64 for occ, _n in CAPX._OCCUPANCY_CACHE.values() if occ)
    return b


def _prospective_probe(chk, card, factors):
    """Context figures for the quotient's dense occupancy probe, in DISTINCT units; none is a complete allowance."""
    doms = [b.domain(card) for b in chk.bags]
    largest = max(doms) if doms else 0
    owned = {}
    for f in factors:
        h = chk.var_home.get(min(f.scope, key=lambda v: chk.order.index(v))) if hasattr(chk, "var_home") and f.scope else None
    # operand multiplicity per bag: every owned factor occurrence and every child message is one multiply over the bag domain
    n_owned = {}
    for b in chk.bags:
        n_owned[b.idx] = 0
    for f in factors:
        if not f.scope:
            continue
        first = min(f.scope, key=lambda v: chk.order.index(v))
        hb = next((b.idx for b in chk.bags if b.eliminated == first), None)
        if hb is not None:
            n_owned[hb] += 1
    weighted = sum(b.domain(card) * (n_owned.get(b.idx, 0) + len(b.children)) for b in chk.bags)
    return {"sum_bag_domains_entries": int(sum(doms)), "operand_weighted_entries": int(weighted), "largest_bag_entries": int(largest),
            "largest_two_arrays_bytes_estimate": int(2 * largest * OBJECT_ARRAY_BYTES_PER_ENTRY),
            "retained_separator_entries": int(sum(sum(1 for _ in ()) for _ in ())) + int(getattr(chk, "sum_sep_entries", 0)),
            "units": "domain entries; operand-weighted entries (multiplies, incl. repeated factor occurrences and child messages); bytes of the two largest live object arrays (pointer + small int, an estimate). NOT included: converted factor arrays, retained separator messages, other live optional state, temporaries -- so none of these is a live-byte bound or a complete work allowance"}


def _conservative_admission(qpl, chk, rq, bg, cap_bytes):
    """The conservative full-occupancy forecast (`forecast_identity(..., occupancy=None)`: every retained message entry at full
    bits; the seconds forecast does not depend on occupancy) and the existing physical admission on it."""
    fc = CAPX.forecast_identity(qpl, chk, rq.factors, rq.card, rq.free, occupancy=None)
    ad = CAPX.admit(fc, bg.remaining(), cap_bytes, CAPX.rss_current_bytes(), rss_baseline_bytes=CAPX.invocation_baseline_bytes())
    return fc, ad


def _quotient_admission_with_preflight(rq, qpl, qest, bg, pb, cap_bytes, sc, rej):
    """The quotient identity's checker plan and PREFLIGHT (the ratio check has already passed): a probe-free conservative admission,
    or a DECLINE before allocation. The frozen admission's dense occupancy probe over the quotient is never started by the pilot."""
    sc.begin("quotient.preflight", "optional")
    chk = CAPX.checker_plan(rq)
    pb.check("pilot:quotient preflight")
    fc, ad = _conservative_admission(qpl, chk, rq, bg, cap_bytes)
    pros = _prospective_probe(chk, rq.card, rq.factors)
    pre = {"conservative_certificate": ad["certificate"], "conservative_forecast_seconds": fc["seconds"], "conservative_forecast_bytes": fc["bytes"], "prospective_probe_context": pros,
           "rule": "conservative full-occupancy forecast admits -> no probe; otherwise DECLINE (unbudgeted occupancy): a possibly missed opportunity, reported"}
    if ad["certificate"] == "FEASIBLE":
        sc.end(note="conservative full-occupancy forecast admits: the dense occupancy probe is unnecessary (skipped)", bytes_=0)
        pre["decision"] = "admitted_without_probe"
        return {"plan": qpl, "est": qest, "chk": chk, "feasibility": _feas_from(fc, ad), "preflight": pre}, None
    sc.end(note="DECLINED before allocation: the conservative forecast does not admit (%s) and the occupancy probe the frozen admission would run is unbudgeted" % ad["certificate"], bytes_=0, status="declined_before_allocation")
    pre["decision"] = "declined_before_allocation"
    rej.append({"name": "identity+quotient", "typed": "QUOTIENT_DECLINED_PREFLIGHT", "phase": "discover",
                "reason": "pilot preflight: the conservative full-occupancy forecast is %s and the occupancy probe the frozen admission would run (%d domain entries, %d operand-weighted entries, ~%d bytes for its two largest arrays, other live state uncounted) is unbudgeted; the candidate is declined before any allocation -- a possibly MISSED opportunity, reported"
                          % (ad["certificate"], pros["sum_bag_domains_entries"], pros["operand_weighted_entries"], pros["largest_two_arrays_bytes_estimate"]), "preflight": pre})
    return None, "declined before allocation (preflight)"


def _feas_from(fc, ad):
    return {"checker": "FEASIBLE", "largest_bag": None, "policy": "physical-2026-11-02 (pilot: conservative full-occupancy, no probe)", "calibration": fc.get("calibration"), "layout": fc.get("layout"),
            "forecast_seconds": fc["seconds"], "forecast_bytes": fc["bytes"], "exact_root_bits_bound": fc.get("exact_root_bits_bound"),
            "occupancy_probe": {"ran": False, "entries_visited_charged": 0, "mean_nonzero_fraction": None, "reason": "conservative forecast admitted; the pilot never starts the dense occupancy probe on a quotient"},
            "admission": ad, "admitted_for": "certificate"}


def _hook_admission(pl, r, chk, bg, cap_bytes, prog):
    """Binding-time admission of a TRANSFORMED record (pipeline._reprice_loaded): the same preflight on the REBUILT plan and factors.
    A quotient record admitted without a probe in discovery must not become an unguarded probe here: conservative forecast admits ->
    feasibility without probe; otherwise an explicit refusal (the record becomes ineligible; the dense record stands). Support records
    run over the dense factors whose occupancy result already exists (cache hit) -> default path."""
    blk = _STATE.get("blk")
    if not prog.get("quotient"):
        return None
    t0 = time.monotonic(); used0 = int(bg.used.get("pricing_entries", 0)) if bg is not None else 0
    fc, ad = _conservative_admission(pl, chk, r, bg, cap_bytes)
    rec = {"scope": "bind.quotient_admission", "kind": "optional", "wall_s": round(time.monotonic() - t0, 6), "charged_entries": (int(bg.used.get("pricing_entries", 0)) - used0) if bg is not None else None,
           "bytes": 0, "status": "admitted_without_probe" if ad["certificate"] == "FEASIBLE" else "refused_unbudgeted_probe", "note": "conservative full-occupancy forecast at binding: %s" % ad["certificate"]}
    if blk is not None:
        blk.setdefault("binding_scopes", []).append(rec)
    if ad["certificate"] == "FEASIBLE":
        return _feas_from(fc, ad)
    f = _feas_from(fc, ad); f["checker"] = ad["certificate"]; f["checker_reason"] = "pilot preflight at binding: the conservative forecast does not admit and the occupancy probe is unbudgeted (declined, no allocation)"
    return f


def select_route(r, bg, rejected, cap_bytes, nq, simp, mh, eh, qh, queries, eps, records, prices):
    """The pilot's selector: the frozen constants with scoped planning-cost observations, an enclosing planning interval, the preflight
    and the optional-state manifest. Returns the selector block (compatible with the frozen reporter). Every exit -- normal,
    probe fallback, global stop, fault -- passes through `_finish` (try / finally)."""
    t_sel = time.monotonic()
    sc = _Scopes(bg)
    ctx = {"keys0": None}
    _STATE.update({"baseline_keys": None, "released": False, "open_record": None,
                   "phase_started_monotonic": t_sel})
    blk = {"policy": "selector", "pilot": "selector_pilot (opt-in; scoped accounting, planning envelope, preflight, state lifetime)", "attempts": [], "recommended": "dense",
           "transformed_record": None, "dense_candidate": None, "late_refusal": None, "scopes": sc.rows,
           "pilot_parameters": {"optional_occupancy_probe": "never started by the pilot: conservative full-occupancy forecast admits or the candidate is declined", "frozen_policy": dict(PLN.K.SELECTOR_POLICY)},
           "window_rule": "the FROZEN policy's window (min(%.1f s, construction allowance remaining - %.1f s)); the pilot changes no constant" % (PLN.SELECTOR_PROBE_WINDOW_S, PLN.SELECTOR_DENSE_RESERVE_S),
           "units": {"wall_s": "monotonic seconds per scope (non-overlapping)", "charged_entries": "shared pricing counter delta per scope (table entries / Boolean positions; a work quota, not a wall)", "bytes": "bytes the mechanism reports or the preflight estimates (never a measured RSS)"},
           "unresolved_overshoot": ["unpolled spans inside scopes: content keys (recognition_key, support_cache_key), build_plan per order, byte_estimate, quotient/support pricing, price_identity_plan, _identity_record / executable_identity, persistence (stage 4), compare (stage 5)",
                                    "the mandatory dense occupancy probe remains unchanged; the quotient occupancy probe is never started by the pilot; other unpolled primitives are measured, not bounded",
                                    "pre-window optional work (the gate scan) and the post-poll tail (record creation, summary) are measured, not bounded"]}
    PLN._SELECTOR_CURRENT[0] = blk; _STATE["blk"] = blk
    try:
        return _select_route_body(r, bg, rejected, cap_bytes, nq, simp, mh, eh, qh, queries, eps, records, prices, blk, sc, ctx)
    except B.BudgetExceeded as e:
        sc.abort("global_stop", "terminal %s stop: %s" % (e.kind, e)); raise          # a stop in an outer step (gate, dense candidate, records) is finalized with its kind
    except BaseException as e:
        sc.abort("fault", "%s: %s" % (type(e).__name__, e)); raise
    finally:
        _finish(blk, sc, ctx["keys0"], t_sel)          # EVERY exit closes the open scope, the manifest and the summaries


def _select_route_body(r, bg, rejected, cap_bytes, nq, simp, mh, eh, qh, queries, eps, records, prices, blk, sc, ctx):
    from mdi import quotient as QT, support as SP
    transformed = None
    # ---- gate (optional work BEFORE the window; measured; a stop inside it is finalized by the enclosing finally)
    sc.begin("gate", "optional")
    zeros = 0; total = 0
    for f in r.factors:
        n = int(f.size()); total += n; zeros += sum(1 for x in f.table if x == 0)
    bg.charge("pricing_entries", total, "selector gate")
    sc.end(note="exact-zero scan")
    blk["gate"] = {"zero_entries": zeros, "table_entries": total, "verdict": "bypass" if zeros == 0 else "probe"}
    # ---- the dense candidate (MANDATORY prefix; reused by the fallback; measured here for the split, not optional)
    sc.begin("dense.candidate", "mandatory")
    dp = PLN._dense_identity_plan(r, bg, cap_bytes, rejected)
    ipl, iest, chk, feas = dp["plan"], dp["est"], dp["chk"], dp["feasibility"]
    built = PLN._identity_program(ipl, r, eps, queries, rejected) if ipl is not None and dp["admitted"] else None
    sc.end(note="dense planning, checker plan, physical admission (incl. the dense occupancy probe where zeros exist), program")
    ctx["keys0"] = _cache_keys(); _STATE["baseline_keys"] = {k: set(v) for k, v in ctx["keys0"].items()}      # everything created from here on is OPTIONAL state
    dense_total_s = float((feas or {}).get("forecast_seconds", {}).get("total") or 0.0) if dp["admitted"] else None
    blk["dense_candidate"] = ("admitted (forecast %.1f s)" % dense_total_s if dp["admitted"] else ("refused: %s" % (rejected[-1].get("reason") if rejected else "no plan"))[:240])
    blk["prefix_elapsed_at_probe_start_s"] = round(bg.elapsed(), 6)      # includes parse, preprocess, the gate and the dense candidate
    if zeros == 0:
        blk["skipped"] = "gate: the restricted law has no exact zero; neither transformation can apply"
    elif ipl is None:
        blk["skipped"] = "no dense reference plan fits the byte cap: the probes' ratios have no reference"
    else:
        cons_left = float(bg.phase_limits.get("construction", 0.0)) - bg.phase_used("construction")
        window = min(PLN.SELECTOR_PROBE_WINDOW_S, cons_left - PLN.SELECTOR_DENSE_RESERVE_S)
        need = window + (dense_total_s or 0.0) + PLN.SELECTOR_WALL_MARGIN_S
        blk["window_s"] = round(window, 3)
        blk["precondition"] = {"remaining_wall_s": round(bg.remaining(), 3), "needed_s": round(need, 3), "dense_forecast_total_s": dense_total_s, "construction_allowance_left_s": round(cons_left, 3)}
        if window <= 0:
            blk["skipped"] = "insufficient construction allowance: %.3f s left, %.1f s reserved for the dense candidate" % (cons_left, PLN.SELECTOR_DENSE_RESERVE_S)
        elif bg.remaining() < need:
            blk["skipped"] = "insufficient remaining wall: %.1f s < window %.1f s + dense forecast %s s + %.1f s margin" % (bg.remaining(), window, dense_total_s, PLN.SELECTOR_WALL_MARGIN_S)
    if blk.get("skipped"):
        rejected.append({"name": "selector", "typed": "SELECTOR_SKIPPED", "phase": "discover", "reason": blk["skipped"]})
    transformed = None
    if not blk.get("skipped"):
        probe_end = PLN._PROBE_CLOCK[0]() + window
        pb = PLN._ProbeBudget(bg, probe_end, window)
        PLN._SELECTOR_PROBE[0] = pb

        def _start(mech):
            a = {"mechanism": mech, "verdict": "STARTED", "wall_s": None, "charged_entries": None, "detail": "started; not finalized"}
            blk["attempts"].append(a); return a

        def _attempt(a, t0, used0, verdict, detail, **extra):
            a.update({"verdict": verdict, "wall_s": round(time.monotonic() - t0, 4), "charged_entries": int(bg.used.get("pricing_entries", 0)) - used0, "detail": str(detail)[:300]}); a.update(extra); return a

        def _charge(where):
            return lambda n: bg.charge("pricing_entries", n, where)
        # ================= probe 1: quotient =================
        t0 = time.monotonic(); used0 = int(bg.used.get("pricing_entries", 0)); contradiction = False
        aq = _start("quotient")
        try:
            sc.begin("quotient.recognition", "optional")
            decl, _fresh = QT.recognize_cached(r.factors, r.free, r.card, deadline=pb.deadline_fn("pilot:quotient recognition"), charge=_charge("quotient recognition"))
            sc.end(note="eliminated %d" % QT.eliminated(decl))
            if QT.eliminated(decl) == 0:
                a = _attempt(aq, t0, used0, "NOT_ADMITTED", "no forced state and no binary equality / complement relation is implied by the factor zeros", recognition=decl["recognition"])
                rejected.append({"name": "identity+quotient", "typed": "QUOTIENT_NOT_ADMITTED", "phase": "discover", "reason": a["detail"]})
            else:
                sc.begin("quotient.construction", "optional")
                rq = QT.build_quotient(r, decl, deadline=pb.deadline_fn("pilot:quotient construction"), charge=_charge("quotient construction"))
                sc.end(note="quotient tables: %d entries" % sum(int(f.size()) for f in rq.factors), bytes_=sum(int(f.size()) for f in rq.factors) * 48)
                sc.begin("quotient.planning", "optional")
                sel_q = P.choose_plan(rq.free, rq.card, rq.factors, 64, cap_bytes, deadline=pb.deadline_fn("pilot:quotient planning")) if rq.free else None
                if sel_q is None or sel_q["chosen"] is None:
                    sc.end(note="no generic ordering fits the byte cap on the quotient (or it has no free variable)", status="not_admitted")
                    a = _attempt(aq, t0, used0, "NOT_ADMITTED", "no generic ordering fits the byte cap on the quotient (or it has no free variable)", eliminated={"fixed": len(decl["fixed"]), "merged": len(decl["merged"])})
                    rejected.append({"name": "identity+quotient", "typed": "QUOTIENT_NOT_ADMITTED", "phase": "discover", "reason": a["detail"]})
                    dq = None; qprice = None
                else:
                    qpl, qest = sel_q["chosen"]; sc.end()
                    # CHEAP FIRST (as the accepted selector): the twofold schedule-row check precedes any physical admission work
                    sc.begin("quotient.pricing", "optional")
                    qprice = QT.quotient_price(ipl, qpl); qprice["recognition"] = decl["recognition"]; qprice["eliminated"] = {"fixed": len(decl["fixed"]), "merged": len(decl["merged"])}
                    sc.end(note="ratio %.2f" % qprice["reduction_ratio"])
                    dq = None
                    if not qprice["admitted"]:
                        a = _attempt(aq, t0, used0, "NOT_ADMITTED", "schedule rows %d quotient vs %d dense (ratio %.2f) below the required %.0f-fold reduction" % (qprice["quotient_schedule_rows"], qprice["dense_schedule_rows"], qprice["reduction_ratio"], QT.MIN_REDUCTION_RATIO), reduction_ratio=qprice["reduction_ratio"])
                        rejected.append({"name": "identity+quotient", "typed": "QUOTIENT_NOT_ADMITTED", "phase": "discover", "reason": a["detail"], "quotient_price": qprice})
                    else:
                        dq, why = _quotient_admission_with_preflight(rq, qpl, qest, bg, pb, cap_bytes, sc, rejected)
                        if dq is None:
                            a = _attempt(aq, t0, used0, "NOT_ADMITTED", why, eliminated={"fixed": len(decl["fixed"]), "merged": len(decl["merged"])}, reduction_ratio=qprice["reduction_ratio"])
                if dq is not None:
                    if True:
                        sc.begin("quotient.program_record", "optional")
                        rej_q = []
                        bq = PLN._identity_program(dq["plan"], rq, eps, queries, rej_q)
                        if bq is None:
                            sc.end(status="not_admitted", note="no usable precision")
                            a = _attempt(aq, t0, used0, "NOT_ADMITTED", "no usable precision on the quotient: %s" % (rej_q[-1].get("reason") if rej_q else ""))
                            rejected.append({"name": "identity+quotient", "typed": "QUOTIENT_NOT_ADMITTED", "phase": "discover", "reason": a["detail"]})
                        else:
                            qprog, qp, qemin, qemax = bq
                            transformed = PLN._identity_record("identity", r, rq, dq["plan"], dq["est"], dq["chk"], qprog, qp, qemin, qemax, nq, simp, mh, eh, qh, queries, eps, bg, qdecl=decl, qprice=qprice)
                            sc.end(note="quotient identity program and record")
                            pb.check("pilot:after quotient record")              # the post-record poll (the tail of this probe is measured by the scope)
                            a = _attempt(aq, t0, used0, "ADMITTED", "ratio %.2f (%d fixed, %d merged, %d free of %d); admission %s" % (qprice["reduction_ratio"], len(decl["fixed"]), len(decl["merged"]), decl["n_free"], len(r.free), dq["preflight"]["decision"]),
                                         reduction_ratio=qprice["reduction_ratio"], eliminated=qprice["eliminated"], recognition=decl["recognition"], preflight=dq["preflight"]["decision"])
                            blk["recommended"] = "quotient"
        except QT.Contradiction as e:
            transformed = None; sc.abort("contradiction", str(e)); contradiction = True
            a = _attempt(aq, t0, used0, "CONTRADICTION", "NOT a certificate: the derived relations admit no positive configuration (%s); probing stops; the dense candidate's zero-evidence proof decides" % str(e)[:120])
            rejected.append({"name": "identity+quotient", "typed": "QUOTIENT_CONTRADICTION", "phase": "discover", "reason": a["detail"]})
        except QT.QuotientError as e:
            transformed = None; sc.abort("refusal", str(e)); a = _attempt(aq, t0, used0, "REFUSAL", "recognition did not complete: %s" % e)
            rejected.append({"name": "identity+quotient", "typed": "QUOTIENT_REFUSAL", "phase": "discover", "reason": a["detail"]})
        except PLN.ProbeExhausted as e:
            transformed = None; sc.abort("probe_exhausted", str(e)); a = _attempt(aq, t0, used0, "PROBE_EXHAUSTED", str(e))
            rejected.append({"name": "identity+quotient", "typed": "SELECTOR_PROBE_EXHAUSTED", "phase": "discover", "reason": a["detail"]})
        except B.BudgetExceeded as e:
            sc.abort("global_stop", str(e)); _attempt(aq, t0, used0, "GLOBAL_STOP", "terminal %s stop inside the quotient probe: %s" % (e.kind, e), stop_kind=str(e.kind))
            raise
        except Exception as e:
            sc.abort("fault", "%s: %s" % (type(e).__name__, e)); _attempt(aq, t0, used0, "IMPLEMENTATION_FAULT", "%s: %s" % (type(e).__name__, e)); raise
        # ================= probe 2: support =================
        if transformed is None and not contradiction and built is not None:
            t0 = time.monotonic(); used0 = int(bg.used.get("pricing_entries", 0)); asup = _start("support")
            try:
                if pb.remaining_window_s() <= 0:
                    raise PLN.ProbeExhausted("the selector's %.1f s probe window is spent before the support probe" % window)
                sc.begin("support.compile_producer_order", "optional")
                sup, _f1 = SP.compile_support_cached(ipl, r.factors, r.card, deadline=pb.deadline_fn("pilot:support compilation"), charge=_charge("support compilation"))
                sc.end(note="rows %d" % sup.counts()["rows_total"], bytes_={"live_accounted_peak": sup.counts().get("peak_working_bytes"), "retained_rows_bytes": sum(int(a_.nbytes) for a_ in sup.rows.values())})
                sc.begin("support.pricing", "optional")
                sprice = SP.support_price(ipl, sup); sc.end(note="ratio %.1f" % sprice["reduction_ratio"])
                if not sprice["admitted"]:
                    a = _attempt(asup, t0, used0, "NOT_ADMITTED", "schedule rows %d sparse vs %d dense (ratio %.1f) below the required %.0f-fold reduction" % (sprice["counts"]["enumerated_schedule_rows"], sprice["dense_enumerated_schedule_rows"], sprice["reduction_ratio"], SP.MIN_REDUCTION_RATIO), reduction_ratio=sprice["reduction_ratio"])
                    rejected.append({"name": "identity+support", "typed": "SUPPORT_NOT_ADMITTED", "phase": "discover", "reason": a["detail"], "support_price": {k: v for k, v in sprice.items() if k not in ("counts", "checker")}})
                else:
                    if list(chk.order) != list(ipl.order):
                        sc.begin("support.compile_checker_order", "optional")
                        try:
                            sup_c, _f2 = SP.compile_support_cached(chk, r.factors, r.card, deadline=pb.deadline_fn("pilot:support compilation (checker order)"), charge=_charge("support compilation"))
                        except SP.SupportError as e:
                            sc.end(status="late_refusal", note=str(e)); raise PLN._LateSupportRefusal("the checker-order compilation did not complete after the producer-order compilation was admitted (ratio %.1f): %s" % (sprice["reduction_ratio"], e))
                        sc.end(note="rows %d" % sup_c.counts()["rows_total"], bytes_={"retained_rows_bytes": sum(int(a_.nbytes) for a_ in sup_c.rows.values())})
                        sprice["checker"] = SP.support_price(chk, sup_c); sprice["checker_compiled_separately"] = True
                    else:
                        sprice["checker"] = {k: v for k, v in sprice.items() if k != "checker"}; sprice["checker_compiled_separately"] = False
                    sprice["compile_wall_s"] = round(time.monotonic() - t0, 4)
                    pb.check("pilot:support pricing")
                    sc.begin("support.program_record", "optional")
                    sprog, sp_, semin, semax = built; sprog = dict(sprog); sprog["support"] = sup.declaration()
                    transformed = PLN._identity_record("identity", r, r, ipl, iest, chk, sprog, sp_, semin, semax, nq, simp, mh, eh, qh, queries, eps, bg, support_note=sprice)
                    sc.end(note="support identity program and record")
                    pb.check("pilot:after support record")
                    a = _attempt(asup, t0, used0, "ADMITTED", "ratio %.1f (%d sparse rows vs %d dense; checker order %s)" % (sprice["reduction_ratio"], sprice["counts"]["enumerated_schedule_rows"], sprice["dense_enumerated_schedule_rows"], "compiled separately" if sprice["checker_compiled_separately"] else "same as the producer's"), reduction_ratio=sprice["reduction_ratio"], checker_compiled_separately=sprice["checker_compiled_separately"])
                    blk["recommended"] = "support"
            except PLN._LateSupportRefusal as e:
                transformed = None; a = _attempt(asup, t0, used0, "LATE_REFUSAL", str(e)); rejected.append({"name": "identity+support", "typed": "SUPPORT_REFUSAL", "phase": "discover", "reason": a["detail"]})
            except SP.SupportError as e:
                transformed = None; sc.abort("refusal", str(e)); a = _attempt(asup, t0, used0, "REFUSAL", "support compilation did not complete: %s" % e); rejected.append({"name": "identity+support", "typed": "SUPPORT_REFUSAL", "phase": "discover", "reason": a["detail"]})
            except PLN.ProbeExhausted as e:
                transformed = None; sc.abort("probe_exhausted", str(e)); a = _attempt(asup, t0, used0, "PROBE_EXHAUSTED", str(e)); rejected.append({"name": "identity+support", "typed": "SELECTOR_PROBE_EXHAUSTED", "phase": "discover", "reason": a["detail"]})
            except B.BudgetExceeded as e:
                sc.abort("global_stop", str(e)); _attempt(asup, t0, used0, "GLOBAL_STOP", "terminal %s stop inside the support probe: %s" % (e.kind, e), stop_kind=str(e.kind)); raise
            except Exception as e:
                sc.abort("fault", "%s: %s" % (type(e).__name__, e)); _attempt(asup, t0, used0, "IMPLEMENTATION_FAULT", "%s: %s" % (type(e).__name__, e)); raise
        elif transformed is None and not contradiction and built is None:
            blk["attempts"].append({"mechanism": "support", "verdict": "NOT_PROBED", "wall_s": 0.0, "charged_entries": 0, "detail": "no admitted dense identity program to compile the support of"})
    blk["transformed_record_discarded_after_creation"] = (transformed is None and any(s_["scope"].endswith("program_record") and s_["status"] == "done" for s_ in sc.rows))
    # ---- the records (the dense record creation is MANDATORY when alone, EXTRA when a transformed record exists)
    sc.begin("dense.record", "optional" if transformed is not None else "mandatory")
    if transformed is not None:
        records.append(transformed); prices.append(transformed[1]); blk["transformed_record"] = transformed[0].identity_key
    if built is not None:
        dprog, dp_, demin, demax = built
        dname = "identity:dense" if transformed is not None else "identity"
        drec, dprice, dpay = PLN._identity_record(dname, r, r, ipl, iest, chk, dict(dprog), dp_, demin, demax, nq, simp, mh, eh, qh, queries, eps, bg)
        records.append((drec, dprice, dpay)); prices.append(dprice); blk["dense_record"] = drec.identity_key
    sc.end(note="dense identity record (named identity:dense when a transformed record exists)")
    return blk


def _finish(blk, sc, keys0, t_sel):
    """Close the open scope (if any), the discovery-time optional-state manifest and the summaries -- on EVERY exit of the selector
    (normal, charged fallback, global stop, fault). Idempotent."""
    if "optional_cost" in blk:
        return
    sc.abort("unfinished", "closed by the selector's finally (the mechanism did not return)")
    keys1 = _cache_keys()
    base = keys0 if keys0 is not None else {k: set() for k in keys1}
    if keys0 is None:
        blk["optional_state_note"] = "the stop occurred before the dense candidate was built: no optional-state baseline exists; every cache entry present is attributed to the (mandatory) dense path"
    new = {k: (keys1[k] - base[k]) if keys0 is not None else set() for k in keys1}
    blk["optional_state_manifest"] = {"new_cache_entries_discovery": {k: len(v) for k, v in new.items()}, "new_cache_entry_keys_abbrev": {k: sorted(repr(x)[:60] for x in v) for k, v in new.items()},
                                      "retained_bytes_estimate_before_cleanup": _retained_bytes_estimate(),
                                      "note": "cache entries created by the probes during DISCOVERY; entries created later (binding re-derivation) are added by the record hooks; everything not needed by the selected record is released by the cleanup hook before execution or on the terminal"}
    blk["optional_cost"] = {"optional_wall_s": sc.total("optional"), "mandatory_prefix_wall_s": sc.total("mandatory"),
                            "post_poll_tail_s": round(time.monotonic() - t_sel - sum(r["wall_s"] for r in sc.rows), 6),
                            "note": "optional_wall_s = sum of the optional scopes measured in DISCOVERY; binding-time scopes (`binding_scopes`, per record incl. failed exits), the selection scope and the cleanup are recorded by the lifecycle hooks; `total_optional_wall_s` is added at the terminal; charges are quotas, not walls; unknown measurements stay null; legacy post_poll_tail_s is the aggregate discovery gap, not an isolated post-poll primitive"}
    PLN._summarize_selector_block(blk)


# ---------------------------------------------------------------- lifecycle hooks (installed by enable())
def _hook_record_begin(rec):
    blk = _STATE.get("blk")
    if blk is None:
        return
    pg = rec.program or {}
    _STATE["open_record"] = {"name": rec.name, "transformed": bool(pg.get("quotient") or pg.get("support")), "t0": time.monotonic(), "keys0": _cache_keys(),
                             "used0": None}


def _hook_record_end(rec, status):
    """Stage 4 per record, on EVERY exit (bound / ineligible / late refusal / refusal / stop): the record's complete
    persistence + read-back + restriction + binding wall, and the cache entries it created (added to the optional manifest)."""
    blk = _STATE.get("blk"); o = _STATE.get("open_record")
    if blk is None or o is None:
        return
    keys1 = _cache_keys(); new = {k: len(keys1[k] - o["keys0"][k]) for k in keys1}
    row = {"scope": "stage4.record", "record": o["name"], "kind": "optional" if (o["transformed"] or any(x.get("record") != o["name"] and x.get("kind") == "optional" for x in blk.get("record_scopes", []))) else "mandatory",
           "status": status, "wall_s": round(time.monotonic() - o["t0"], 6), "new_cache_entries": new,
           "note": "complete stage-4 wall of this record incl. serialization, write, read-back, the law's restriction, binding re-derivation and its final deadline check; recorded whether or not binding returned"}
    if o["transformed"]:
        row["kind"] = "optional"
    else:
        # the dense record is optional work only when a transformed record also exists in this invocation
        row["kind"] = "optional" if blk.get("transformed_record") else "mandatory"
    blk.setdefault("record_scopes", []).append(row)
    if any(new.values()):
        m = blk.setdefault("optional_state_manifest", {}); m.setdefault("new_cache_entries_binding", {}).setdefault(o["name"], new)
    _STATE["open_record"] = None


def _hook_select_begin():
    blk = _STATE.get("blk")
    if blk is not None:
        blk["_select_t0"] = time.monotonic()


def _hook_select_end(cmp):
    blk = _STATE.get("blk")
    if blk is not None and "_select_t0" in blk:
        blk["selection_scope"] = {"wall_s": round(time.monotonic() - blk.pop("_select_t0"), 6), "compared": [x["name"] for x in cmp["all"]], "kind": "optional" if len(cmp["all"]) > 1 else "mandatory"}


def _hook_selected(crec):
    """Release every optional object the SELECTED record does not need, before the frozen execution boundary."""
    _release(crec.program or {}, reason="selected")


def _hook_terminal(out):
    """On every terminal: release optional state not yet released (abandonment paths), close the selection scope, add the totals."""
    blk = _STATE.get("blk")
    if blk is None:
        return
    if "_select_t0" in blk:
        blk["selection_scope"] = {"wall_s": round(time.monotonic() - blk.pop("_select_t0"), 6), "compared": None, "kind": "optional", "status": "abandoned"}
    if not _STATE.get("released"):
        _release({}, reason="terminal:%s" % out.status)
    opt = blk.get("optional_cost", {}).get("optional_wall_s") or 0.0
    rs = sum(r["wall_s"] for r in blk.get("record_scopes", []) if r["kind"] == "optional")
    bs = sum(r["wall_s"] for r in blk.get("binding_scopes", []))
    ss = (blk.get("selection_scope") or {}).get("wall_s", 0.0) if (blk.get("selection_scope") or {}).get("kind") == "optional" else 0.0
    cl = (blk.get("cleanup") or {}).get("wall_s", 0.0)
    blk["total_optional_wall_s"] = round(opt + rs + ss + cl, 6)
    blk["optional_scopes_subtotal_wall_s"] = blk["total_optional_wall_s"]
    blk["total_optional_note"] = ("Legacy field: a scoped subtotal, NOT complete incremental optional cost E. It omits inter-scope gaps and can include mandatory dense binding after a transformed record fails. "
                                  "Binding scopes are inside record scopes and are not added again. planning_envelope_wall_s measures the enclosing planning interval, including mandatory work and unassigned gaps; neither field is a counterfactual overhead theorem.")
    _STATE["blk"] = None


def _release(pg, reason):
    from mdi import support as SP, quotient as QT
    blk = _STATE.get("blk"); base = _STATE.get("baseline_keys")
    if blk is None:
        return
    t0 = time.monotonic(); rss0 = CAPX.rss_current_bytes(); before = _retained_bytes_estimate()
    need_support = bool(pg.get("support")); need_quotient = bool(pg.get("quotient"))
    dropped = {"support": 0, "recognition": 0, "occupancy": 0}; kept = {"support": 0, "recognition": 0, "occupancy": 0}
    if base is not None:
        for k in list(SP._SUPPORT_CACHE):
            if k in base["support"]:
                continue
            if need_support and SP._SUPPORT_CACHE[k].digest() == str(pg["support"].get("digest")):
                kept["support"] += 1
            else:
                del SP._SUPPORT_CACHE[k]; dropped["support"] += 1
        for k in list(QT._RECOGNITION_CACHE):
            if k in base["recognition"]:
                continue
            if need_quotient and QT._RECOGNITION_CACHE[k].get("digest") == str(pg["quotient"].get("digest")):
                kept["recognition"] += 1
            else:
                del QT._RECOGNITION_CACHE[k]; dropped["recognition"] += 1
        for k in list(CAPX._OCCUPANCY_CACHE):
            if k in base["occupancy"]:
                continue
            if need_quotient:
                kept["occupancy"] += 1
            else:
                del CAPX._OCCUPANCY_CACHE[k]; dropped["occupancy"] += 1
    gc.collect()
    after = _retained_bytes_estimate(); rss1 = CAPX.rss_current_bytes()
    blk["cleanup"] = {"reason": reason, "wall_s": round(time.monotonic() - t0, 6), "dropped_cache_entries": dropped, "kept_for_execution": kept,
                      "retained_bytes_estimate_before": before, "retained_bytes_estimate_after": after, "rss_before_bytes": rss0, "rss_after_bytes": rss1,
                      "baseline_known": base is not None,
                      "note": "LOGICAL release of every optional cache entry (created after the dense candidate, in discovery OR at binding) not needed by the selected record; freeing references and collecting does not guarantee the allocator returns pages -- the RSS figures are an observation, the byte estimate is the objects' own sizes"}
    _STATE["released"] = True
    # Close before execution, or at pre-execution abandonment. This enclosing interval includes
    # mandatory dense work, inter-scope bookkeeping, and both cleanup observations above.
    # It does not isolate counterfactual E or prove a time/space bound.
    ended = time.monotonic()
    started = _STATE.get("phase_started_monotonic")
    envelope = None if started is None else ended - started
    known = (sum(r["wall_s"] for r in blk.get("scopes", [])) +
             sum(r["wall_s"] for r in blk.get("record_scopes", [])) +
             (blk.get("selection_scope") or {}).get("wall_s", 0.0) + blk["cleanup"]["wall_s"])
    blk["planning_envelope_wall_s"] = None if envelope is None else round(envelope, 6)
    blk["planning_scopes_wall_s"] = round(known, 6)
    blk["planning_unassigned_wall_s"] = None if envelope is None else round(envelope - known, 6)
    blk["planning_envelope_note"] = ("Observed selector-entry to cleanup-completion interval, before execution or at pre-execution abandonment. Includes mandatory work and all gaps; not complete invocation time or exact optional E. "
                                     "Unassigned is the enclosing interval minus non-overlapping top-level scopes; tiny signed residuals can reflect six-decimal scope rounding. Nested binding scopes are not added.")


def run_loaded(crec, law, queries, bg, eps, cap_bytes, prog=None, out=None, rejected=None, stages=None, wrap=None):
    """The execution boundary: the cleanup now runs in the `selected` hook (before this call); this wrapper only guarantees the
    release happened (idempotent) and dispatches to the frozen `run_loaded`."""
    if _STATE.get("blk") is not None and not _STATE.get("released"):
        _release(crec.program or {}, reason="run_loaded")
    return _ORIG["run_loaded"](crec, law, queries, bg, eps, cap_bytes, prog, out=out, rejected=rejected, stages=stages, wrap=wrap)
