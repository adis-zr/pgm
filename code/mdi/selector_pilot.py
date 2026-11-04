"""OPT-IN PILOT (4 November 2026; disabled by default; NOT part of the accepted selector): complete optional-discovery
accounting, pre-allocation refusal and optional-state lifetime for the frozen selector policy.

Nothing of the accepted snapshot is edited. `enable()` replaces two attributes of `mdi.pipeline` that `_solve` looks up at call
time -- `_select_route` (the selector) and `run_loaded` (the execution boundary) -- with the pilot's versions; `disable()` (or the
`enabled()` context manager) restores them. The admission RULES and the frozen `SELECTOR_POLICY` constants are read, never
changed; the pilot adds (1) NON-OVERLAPPING cost scopes for every optional step -- the pre-window gate, recognition, quotient
construction / planning / pricing / preflight / admission, both support compilations, pricing, program and record creation, the
post-poll tail -- each with its wall, its shared-counter charge delta and the bytes the mechanism reports; (2) a PREFLIGHT before
the quotient's optional dense occupancy probe: a conservative full-occupancy forecast (every message entry at full bits) that, when
it already admits, makes the probe unnecessary, and otherwise a prospective work / byte estimate derived from the checker plan that
DECLINES the candidate before allocating when it exceeds an explicit finite allowance (a missed opportunity, reported);
(3) an optional-state manifest (cache keys created by the probes) and a cleanup before execution that releases every optional
object the selected record does not need, charged and RSS-sampled (an observation: freeing references does not guarantee the
allocator returns pages).

This is infrastructure for LOSS PROTECTION, not a new inference advantage: a complete one-second optional window is an EMPIRICAL
pilot target, not a wall-time theorem; the frozen 20 s window stays the policy; unresolved physical overshoot terms are named in
the block (`unresolved_overshoot`).
"""
from __future__ import annotations
import time, gc, contextlib
from fractions import Fraction as Fr
from mdi import pipeline as PLN, plan as P, capacity as CAPX, budget as B

# pilot parameters (NOT selector policy constants; explicit, opt-in, reported in every block)
PILOT_OPTIONAL_PROBE_ENTRIES = 5_000_000        # prospective object-array ENTRIES the quotient's occupancy probe may materialize (sum of bag domains)
PILOT_OPTIONAL_PROBE_BYTES = 256 << 20          # prospective BYTES of its largest bag-shaped object arrays (two live arrays per bag step)
OBJECT_ARRAY_BYTES_PER_ENTRY = 8 + 32           # one pointer plus one small Python int object per entry (an estimate, not a measurement)

_INSTALLED = [False]
_ORIG = {}
_STATE = {"optional_cache_keys": None, "manifest": None}


def enable():
    if not _INSTALLED[0]:
        _ORIG["_select_route"] = PLN._select_route
        _ORIG["run_loaded"] = PLN.run_loaded
        PLN._select_route = select_route
        PLN.run_loaded = run_loaded
        _INSTALLED[0] = True


def disable():
    if _INSTALLED[0]:
        PLN._select_route = _ORIG["_select_route"]
        PLN.run_loaded = _ORIG["run_loaded"]
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


def _prospective_probe(chk, card):
    doms = [b.domain(card) for b in chk.bags]
    largest = max(doms) if doms else 0
    return {"sum_bag_domains_entries": int(sum(doms)), "largest_bag_entries": int(largest),
            "bytes_estimate": int(2 * largest * OBJECT_ARRAY_BYTES_PER_ENTRY),
            "basis": "the probe materializes, per bag, a full bag-shaped object array (accumulator) and a broadcast operand, multiplies and reduces them between deadline polls; entries = sum of bag domains, bytes = 2 x largest domain x %d (pointer + small int object; an estimate)" % OBJECT_ARRAY_BYTES_PER_ENTRY}


def _quotient_admission_with_preflight(rq, bg, pb, cap_bytes, sc, rej):
    """The quotient identity's planning (polled), its checker plan and PREFLIGHT, then either a probe-free conservative
    admission, a probe within the allowance (the frozen admission), or a DECLINE before allocation."""
    sc.begin("quotient.planning", "optional")
    sel_q = P.choose_plan(rq.free, rq.card, rq.factors, 64, cap_bytes, deadline=pb.deadline_fn("pilot:quotient planning")) if rq.free else None
    if sel_q is None or sel_q["chosen"] is None:
        sc.end(note="no generic ordering fits the byte cap on the quotient (or it has no free variable)", status="not_admitted")
        return None, "no generic ordering fits the byte cap on the quotient (or it has no free variable)"
    qpl, qest = sel_q["chosen"]
    sc.end()
    sc.begin("quotient.preflight", "optional")
    chk = CAPX.checker_plan(rq)
    pb.check("pilot:quotient preflight")
    fc = CAPX.forecast_identity(qpl, chk, rq.factors, rq.card, rq.free, occupancy=None)       # full occupancy: every message entry at full bits
    ad = CAPX.admit(fc, bg.remaining(), cap_bytes, CAPX.rss_current_bytes(), rss_baseline_bytes=CAPX.invocation_baseline_bytes())
    pros = _prospective_probe(chk, rq.card)
    pre = {"conservative_certificate": ad["certificate"], "conservative_forecast_seconds": fc["seconds"], "conservative_forecast_bytes": fc["bytes"],
           "prospective_probe": pros, "allowance": {"entries": PILOT_OPTIONAL_PROBE_ENTRIES, "bytes": PILOT_OPTIONAL_PROBE_BYTES}}
    if ad["certificate"] == "FEASIBLE":
        sc.end(note="conservative full-occupancy forecast admits: the dense occupancy probe is unnecessary (skipped)", bytes_=0)
        pre["decision"] = "admitted_without_probe"
        return {"plan": qpl, "est": qest, "chk": chk, "feasibility": {"checker": "FEASIBLE", "admission": ad, "forecast_seconds": fc["seconds"], "forecast_bytes": fc["bytes"], "occupancy_probe": {"ran": False, "reason": "conservative forecast admitted"}}, "preflight": pre}, None
    if pros["sum_bag_domains_entries"] > PILOT_OPTIONAL_PROBE_ENTRIES or pros["bytes_estimate"] > PILOT_OPTIONAL_PROBE_BYTES:
        sc.end(note="DECLINED before allocation: the conservative forecast does not admit (%s) and the prospective occupancy probe (%d entries, ~%d bytes) exceeds the optional allowance" % (ad["certificate"], pros["sum_bag_domains_entries"], pros["bytes_estimate"]), bytes_=0, status="declined_before_allocation")
        pre["decision"] = "declined_before_allocation"
        rej.append({"name": "identity+quotient", "typed": "QUOTIENT_DECLINED_PREFLIGHT", "phase": "discover",
                    "reason": "pilot preflight: the conservative full-occupancy forecast is %s and the occupancy probe the frozen admission would run (%d object-array entries, ~%d bytes) exceeds the optional allowance (%d entries / %d bytes); the candidate is declined before any allocation -- a possibly MISSED opportunity, reported" % (ad["certificate"], pros["sum_bag_domains_entries"], pros["bytes_estimate"], PILOT_OPTIONAL_PROBE_ENTRIES, PILOT_OPTIONAL_PROBE_BYTES),
                    "preflight": pre})
        return None, "declined before allocation (preflight)"
    sc.end(note="conservative forecast %s; probe within the allowance -> the frozen admission (with probe) runs" % ad["certificate"])
    pre["decision"] = "probe_within_allowance"
    sc.begin("quotient.admission_with_probe", "optional")
    dq = PLN._dense_identity_plan(rq, bg, cap_bytes, rej, deadline_bg=pb, name="identity")
    sc.end(note=("admitted" if dq["admitted"] else "refused: %s" % (rej[-1].get("reason") if rej else "")), bytes_=pros["bytes_estimate"])
    if not dq["admitted"]:
        return None, "refused by the physical admission after the probe"
    dq["preflight"] = pre
    return dq, None


def select_route(r, bg, rejected, cap_bytes, nq, simp, mh, eh, qh, queries, eps, records, prices):
    """The pilot's selector: the frozen policy's decisions with complete, non-overlapping optional cost scopes, the preflight
    and the optional-state manifest. Returns the selector block (compatible with the frozen reporter)."""
    from mdi import quotient as QT, support as SP
    t_sel = time.monotonic()
    sc = _Scopes(bg)
    keys0 = None                              # the optional-state snapshot is taken AFTER the mandatory dense candidate (its occupancy entry is fallback state)
    blk = {"policy": "selector", "pilot": "selector_pilot (opt-in; complete optional accounting, preflight, state lifetime)", "attempts": [], "recommended": "dense",
           "transformed_record": None, "dense_candidate": None, "late_refusal": None, "scopes": sc.rows,
           "pilot_parameters": {"optional_probe_entries": PILOT_OPTIONAL_PROBE_ENTRIES, "optional_probe_bytes": PILOT_OPTIONAL_PROBE_BYTES, "frozen_policy": dict(PLN.K.SELECTOR_POLICY)},
           "window_rule": "the FROZEN policy's window (min(%.1f s, construction allowance remaining - %.1f s)); the pilot changes no constant" % (PLN.SELECTOR_PROBE_WINDOW_S, PLN.SELECTOR_DENSE_RESERVE_S),
           "units": {"wall_s": "monotonic seconds per scope (non-overlapping)", "charged_entries": "shared pricing counter delta per scope (table entries / Boolean positions; a work quota, not a wall)", "bytes": "bytes the mechanism reports or the preflight estimates (never a measured RSS)"},
           "unresolved_overshoot": ["unpolled spans inside scopes: content keys (recognition_key, support_cache_key), build_plan per order, byte_estimate, quotient/support pricing, price_identity_plan, _identity_record / executable_identity, persistence (stage 4), compare (stage 5)",
                                    "the dense occupancy probe's per-bag object-array allocation / multiply / reduce between polls (width-exponential) -- the preflight refuses it above the allowance but does not make it interruptible",
                                    "pre-window optional work (the gate scan) and the post-poll tail (record creation, summary) are measured, not bounded"]}
    PLN._SELECTOR_CURRENT[0] = blk
    # ---- gate (optional work BEFORE the window; measured)
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
    keys0 = _cache_keys()                     # everything created from here on is OPTIONAL state
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
                dq, why = _quotient_admission_with_preflight(rq, bg, pb, cap_bytes, sc, rejected)
                if dq is None:
                    a = _attempt(aq, t0, used0, "NOT_ADMITTED", why, eliminated={"fixed": len(decl["fixed"]), "merged": len(decl["merged"])})
                    if why != "declined before allocation (preflight)":
                        rejected.append({"name": "identity+quotient", "typed": "QUOTIENT_NOT_ADMITTED", "phase": "discover", "reason": a["detail"]})
                else:
                    sc.begin("quotient.pricing", "optional")
                    qprice = QT.quotient_price(ipl, dq["plan"]); qprice["recognition"] = decl["recognition"]; qprice["eliminated"] = {"fixed": len(decl["fixed"]), "merged": len(decl["merged"])}
                    sc.end(note="ratio %.2f" % qprice["reduction_ratio"])
                    if not qprice["admitted"]:
                        a = _attempt(aq, t0, used0, "NOT_ADMITTED", "schedule rows %d quotient vs %d dense (ratio %.2f) below the required %.0f-fold reduction" % (qprice["quotient_schedule_rows"], qprice["dense_schedule_rows"], qprice["reduction_ratio"], QT.MIN_REDUCTION_RATIO), reduction_ratio=qprice["reduction_ratio"])
                        rejected.append({"name": "identity+quotient", "typed": "QUOTIENT_NOT_ADMITTED", "phase": "discover", "reason": a["detail"], "quotient_price": qprice})
                    else:
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
            _finish(blk, sc, keys0, t_sel); raise
        except Exception as e:
            sc.abort("fault", "%s: %s" % (type(e).__name__, e)); _attempt(aq, t0, used0, "IMPLEMENTATION_FAULT", "%s: %s" % (type(e).__name__, e)); _finish(blk, sc, keys0, t_sel); raise
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
                sc.abort("global_stop", str(e)); _attempt(asup, t0, used0, "GLOBAL_STOP", "terminal %s stop inside the support probe: %s" % (e.kind, e), stop_kind=str(e.kind)); _finish(blk, sc, keys0, t_sel); raise
            except Exception as e:
                sc.abort("fault", "%s: %s" % (type(e).__name__, e)); _attempt(asup, t0, used0, "IMPLEMENTATION_FAULT", "%s: %s" % (type(e).__name__, e)); _finish(blk, sc, keys0, t_sel); raise
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
    _finish(blk, sc, keys0, t_sel)
    return blk


def _finish(blk, sc, keys0, t_sel):
    """Close the optional-state manifest and the summaries (also on a global stop)."""
    keys1 = _cache_keys()
    opt = {k: sorted(repr(x)[:60] for x in (keys1[k] - keys0[k])) for k in keys1}
    blk["optional_state_manifest"] = {"new_cache_entries": {k: len(keys1[k] - keys0[k]) for k in keys1}, "new_cache_entry_keys_abbrev": opt,
                                      "retained_bytes_estimate_before_cleanup": _retained_bytes_estimate(),
                                      "note": "cache entries created by the probes (support compilations, recognitions, the quotient's occupancy); released before execution by the pilot's run_loaded unless the selected record needs them"}
    _STATE["optional_cache_keys"] = {k: (keys1[k] - keys0[k]) for k in keys1}
    blk["optional_cost"] = {"optional_wall_s": sc.total("optional"), "mandatory_prefix_wall_s": sc.total("mandatory"),
                            "post_poll_tail_s": round(time.monotonic() - t_sel - sum(r["wall_s"] for r in sc.rows), 6),
                            "note": "optional_wall_s = sum of the optional scopes measured in discovery (gate, probes, pricing, records); the transformed record's persistence and binding (stage 4), the comparison (stage 5) and the cleanup (before execution) are recorded separately by the pipeline / the pilot's run_loaded; charges are quotas, not walls"}
    PLN._summarize_selector_block(blk)


def run_loaded(crec, law, queries, bg, eps, cap_bytes, prog=None, out=None, rejected=None, stages=None, wrap=None):
    """Before the frozen execution boundary: release every optional object the SELECTED record does not need (charged;
    RSS sampled before / after as an observation), then dispatch to the frozen `run_loaded`."""
    from mdi import support as SP, quotient as QT
    blk = PLN._SELECTOR_CURRENT[0]
    if blk is not None and _STATE.get("optional_cache_keys") is not None:
        t0 = time.monotonic(); rss0 = CAPX.rss_current_bytes(); before = _retained_bytes_estimate()
        pg = crec.program or {}
        need_support = bool(pg.get("support")); need_quotient = bool(pg.get("quotient"))
        dropped = {"support": 0, "recognition": 0, "occupancy": 0}; kept = {"support": 0, "recognition": 0, "occupancy": 0}
        for k in list(_STATE["optional_cache_keys"]["support"]):
            if k in SP._SUPPORT_CACHE:
                if need_support and SP._SUPPORT_CACHE[k].digest() == str(pg["support"].get("digest")):
                    kept["support"] += 1
                else:
                    del SP._SUPPORT_CACHE[k]; dropped["support"] += 1
        for k in list(_STATE["optional_cache_keys"]["recognition"]):
            if k in QT._RECOGNITION_CACHE:
                if need_quotient and QT._RECOGNITION_CACHE[k].get("digest") == str(pg["quotient"].get("digest")):
                    kept["recognition"] += 1
                else:
                    del QT._RECOGNITION_CACHE[k]; dropped["recognition"] += 1
        for k in list(_STATE["optional_cache_keys"]["occupancy"]):
            if k in CAPX._OCCUPANCY_CACHE:
                if need_quotient:
                    kept["occupancy"] += 1                                  # the quotient's occupancy result serves its exact aggregation
                else:
                    del CAPX._OCCUPANCY_CACHE[k]; dropped["occupancy"] += 1
        gc.collect()
        rss1 = CAPX.rss_current_bytes()
        blk["cleanup"] = {"wall_s": round(time.monotonic() - t0, 6), "dropped_cache_entries": dropped, "kept_for_execution": kept,
                          "retained_bytes_estimate_before": before, "retained_bytes_estimate_after": _retained_bytes_estimate(),
                          "rss_before_bytes": rss0, "rss_after_bytes": rss1,
                          "note": "freeing Python references and collecting does not guarantee the allocator returns pages: the RSS figures are an observation of the process's current resident set, not a bound; a four-entry cache limit is not a byte bound -- the retained estimate is the objects' own sizes"}
        _STATE["optional_cache_keys"] = None
    return _ORIG["run_loaded"](crec, law, queries, bg, eps, cap_bytes, prog, out=out, rejected=rejected, stages=stages, wrap=wrap)
