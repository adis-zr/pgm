"""FAMILY B (diagnostic spec): the existing MDI transformations -- exact constraint QUOTIENT and compiled global SUPPORT -- scheduled
INDEPENDENTLY on one case under a diagnostic-only wrapper, 30 s / 8 GiB per (case, mechanism), in a fresh process.

Phase 1 STRUCTURAL (existing routines called directly; production gates intervened and NAMED):
  intervened: selector exact-zero gate (bypassed: the routine runs on zero-free laws too and records 'no relation / no support reduction'),
              selector probe window (20 s) and remaining-wall precondition (window + dense forecast + 30 s margin), the 5 s per-routine wall
              caps (QUOTIENT_WALL_CAP_S / SUPPORT_WALL_CAP_S raised to the 30 s cell cap), dense-reference byte-cap gating for the SUPPORT
              ordering (when no generic ordering fits the 8 GiB byte cap, the min-fill ordering is still produced with the cap removed so the
              support can be compiled and measured -- structural potential only; recorded).
  remaining:  SUPPORT_MEM_CAP_BYTES (512 MiB working storage of the compilation), the routines' own algorithms and refusals (Contradiction,
              QuotientError, SupportError), MIN_REDUCTION_RATIO (reported as the production admission verdict, not applied as a stop).
Phase 2 EXECUTION (only when the structural phase found something and time remains): the existing route end-to-end through mdi.arm.run_arm with
  route policy quotient / support (its own admission incl. MIN_REDUCTION_RATIO and the dense-identity checker forecast, construction through
  publication and independent checking), wall = remaining of the 30 s. A no-seed / no-op / inapplicable result is RECORDED, never omitted.
    python bench/transform_probe.py MECH MODEL.uai EVID.uai.evid OUT_DIR CAP_S"""
from __future__ import annotations
import os, sys, json, time, math
T0 = time.monotonic()
sys.set_int_max_str_digits(0)
HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__))); sys.path.insert(0, HERE)
from fractions import Fraction as Fr


def now():
    return time.monotonic() - T0


def dl(cap):
    def f():
        if now() > cap:
            raise TimeoutError("diagnostic cap %.0f s" % cap)
    return f


def atomic(path, obj):
    tmp = path + ".tmp"; json.dump(obj, open(tmp, "w"), indent=1, default=str); os.replace(tmp, path)


def main():
    mech, mp, ep, out, cap = sys.argv[1], sys.argv[2], sys.argv[3], sys.argv[4], float(sys.argv[5]); os.makedirs(out, exist_ok=True)
    rec = {"mechanism": mech, "model": mp, "evidence": ep, "cap_s": cap, "phases_s": {}, "gates_intervened": [], "gates_remaining": [], "structural": {}, "execution": None, "status": None}
    from mdi import model as MM, preprocess as PRE, quotient as QT, support as SP, plan as P
    rec["phases_s"]["startup_imports"] = now(); t = now()
    m = MM.read_uai(mp); ev = MM.read_evidence(ep, m); r0 = MM.restrict(m, ev); rec["phases_s"]["parse_restrict"] = now() - t
    rec["sizes"] = {"variables": m.nvars, "evidence": len(ev), "free_after_restriction": len(r0.free), "restricted_factors": len(r0.factors), "restricted_entries": sum(int(f.size()) for f in r0.factors)}
    if r0.impossible_factor is not None or r0.constant == 0:
        rec["status"] = "ZERO_EVIDENCE_RESTRICTION"; rec["structural"] = {"note": "restriction claims zero evidence weight; no transformation applies"}; atomic(os.path.join(out, "probe.json"), rec); return
    t = now()
    try:
        simp = PRE.simplify(r0); PRE.verify_identities(r0, simp)
    except PRE.PreprocessError as e:
        rec["status"] = "PREPROCESSING_REFUSED"; rec["structural"] = {"note": "exact preprocessing refused by its own verification: %s" % str(e)[:200]}; rec["phases_s"]["preprocess"] = now() - t; atomic(os.path.join(out, "probe.json"), rec); return
    rec["phases_s"]["preprocess"] = now() - t
    if simp.impossible is not None:
        rec["status"] = "ZERO_EVIDENCE_PREPROCESS"; rec["structural"] = {"note": "preprocessing found an identically zero factor"}; atomic(os.path.join(out, "probe.json"), rec); return
    r = MM.Restricted(model=m, evidence=ev, factors=simp.factors, free=list(simp.free), card=dict(simp.card), constant=r0.constant, impossible_factor=None)
    zeros = sum(1 for f in r.factors for x in f.table if x == 0); tot = sum(int(f.size()) for f in r.factors)
    rec["sizes"].update({"free_after_preprocess": len(r.free), "preprocessed_factors": len(r.factors), "preprocessed_entries": tot, "exact_zeros_preprocessed": zeros})
    rec["gates_intervened"].append({"gate": "selector exact-zero gate", "production_verdict": "bypass" if zeros == 0 else "probe", "action": "bypassed: the routine runs regardless"})
    rec["gates_intervened"].append({"gate": "selector probe window / remaining-wall precondition (20 s window + dense forecast + 30 s margin)", "action": "not applied (diagnostic wrapper)"})
    cap_bytes = 8 << 30; charged = [0]
    def charge(n):
        charged[0] += int(n)
    # dense reference ordering (needed for the ratio of both mechanisms)
    t = now()
    try:
        sel_d = P.choose_plan(r.free, r.card, r.factors, 64, cap_bytes, deadline=dl(cap))
    except TimeoutError as e:
        rec["status"] = "TIMEOUT_DENSE_PLANNING"; rec["phases_s"]["dense_planning"] = now() - t; atomic(os.path.join(out, "probe.json"), rec); return
    rec["phases_s"]["dense_planning"] = now() - t; dense_plan = sel_d["chosen"][0] if sel_d["chosen"] else None
    rec["structural"]["dense_reference"] = {"ordering_fits_8GiB_byte_cap": dense_plan is not None, "candidates": len(sel_d.get("candidates", [])), "best_forecast": (str(sel_d["candidates"][0][1])[:200] if sel_d.get("candidates") and dense_plan is None else None)}
    if dense_plan is None:
        # the generic ordering is still produced with the cap removed so the structural measurement can proceed (NAMED intervention)
        try:
            sel_u = P.choose_plan(r.free, r.card, r.factors, 64, 1 << 62, deadline=dl(cap)); dense_plan = sel_u["chosen"][0] if sel_u["chosen"] else None
            rec["gates_intervened"].append({"gate": "dense-reference byte cap (8 GiB) for the ordering", "action": "removed for the STRUCTURAL phase only (ordering produced with an unbounded cap); execution phase keeps the production cap", "ordering_obtained": dense_plan is not None})
        except TimeoutError:
            dense_plan = None
    if mech == "quotient":
        t = now()
        try:
            decl = QT.recognize(r.factors, r.free, r.card, deadline=dl(cap), charge=charge, wall_cap_s=cap)
            rec["gates_intervened"].append({"gate": "QUOTIENT_WALL_CAP_S", "production": QT.QUOTIENT_WALL_CAP_S, "diagnostic": cap})
            rec["structural"]["recognition"] = {"status": "complete", "seconds": now() - t, "fixed": len(decl["fixed"]), "merged": len(decl["merged"]), "free_before": len(r.free), "free_after": decl.get("n_free"), "recognition": decl.get("recognition"), "entries_charged": charged[0]}
            if QT.eliminated(decl) == 0:
                rec["structural"]["verdict"] = "NO_RELATION (no forced state and no equality / complement relation implied by the exact zeros)"; rec["status"] = "STRUCTURAL_NO_OP"
            else:
                t2 = now(); rq = QT.build_quotient(r, decl, deadline=dl(cap), charge=charge); rec["phases_s"]["quotient_construction"] = now() - t2
                rec["structural"]["quotient"] = {"free": len(rq.free), "factors": len(rq.factors), "entries": sum(int(f.size()) for f in rq.factors)}
                t3 = now(); sel_q = P.choose_plan(rq.free, rq.card, rq.factors, 64, cap_bytes, deadline=dl(cap)) if rq.free else None; rec["phases_s"]["quotient_planning"] = now() - t3
                if dense_plan is not None and sel_q is not None and sel_q["chosen"] is not None:
                    price = QT.quotient_price(dense_plan, sel_q["chosen"][0]); rec["structural"]["price"] = {k: (v if not isinstance(v, dict) else v) for k, v in price.items()}
                    rec["structural"]["verdict"] = "ADMITTED_BY_RATIO" if price["admitted"] else "BELOW_MIN_REDUCTION_RATIO (%.2f < %.0f)" % (price["reduction_ratio"], QT.MIN_REDUCTION_RATIO)
                else:
                    rec["structural"]["verdict"] = "NO_ORDERING_FITS (quotient or dense ordering missing under the byte cap)"
                rec["gates_remaining"].append({"gate": "quotient.MIN_REDUCTION_RATIO = %.0f" % QT.MIN_REDUCTION_RATIO, "role": "production admission; REPORTED here, not applied as a stop"})
                rec["status"] = "STRUCTURAL_MEASURED"
        except QT.Contradiction as e:
            rec["structural"]["verdict"] = "CONTRADICTION (the derived relations admit no positive configuration): %s" % str(e)[:120]; rec["status"] = "STRUCTURAL_CONTRADICTION"
        except QT.QuotientError as e:
            rec["structural"]["verdict"] = "REFUSAL: %s" % str(e)[:160]; rec["status"] = "STRUCTURAL_REFUSED"
        except TimeoutError as e:
            rec["structural"]["verdict"] = "TIMEOUT in recognition / construction at the %.0f s cap" % cap; rec["status"] = "STRUCTURAL_TIMEOUT"
        rec["phases_s"]["structural_total"] = now() - t
    elif mech == "support":
        t = now(); rec["gates_remaining"].append({"gate": "SUPPORT_MEM_CAP_BYTES = %d" % SP.SUPPORT_MEM_CAP_BYTES, "role": "the compilation's own working-storage cap (kept)"})
        rec["gates_intervened"].append({"gate": "SUPPORT_WALL_CAP_S", "production": SP.SUPPORT_WALL_CAP_S, "diagnostic": cap})
        rec["structural"]["has_hard_zeros"] = bool(SP.has_hard_zeros(r.factors))
        if dense_plan is None:
            rec["structural"]["verdict"] = "NO_ORDERING (no generic elimination ordering obtainable even with the byte cap removed within the cap)"; rec["status"] = "STRUCTURAL_NO_ORDERING"
        else:
            try:
                sup = SP.compile_support(dense_plan, r.factors, r.card, deadline=dl(cap), charge=charge, wall_cap_s=cap)
                price = SP.support_price(dense_plan, sup); rec["structural"]["price"] = {k: v for k, v in price.items() if k not in ("checker",)}
                rec["structural"]["compilation"] = {"status": "complete", "seconds": now() - t, "positions_charged": charged[0]}
                rec["structural"]["verdict"] = "ADMITTED_BY_RATIO" if price["admitted"] else "BELOW_MIN_REDUCTION_RATIO (%.2f < %.0f)" % (price["reduction_ratio"], SP.MIN_REDUCTION_RATIO)
                rec["gates_remaining"].append({"gate": "support.MIN_REDUCTION_RATIO = %.0f" % SP.MIN_REDUCTION_RATIO, "role": "production admission; REPORTED, not applied as a stop"})
                rec["status"] = "STRUCTURAL_MEASURED"
            except SP.SupportError as e:
                rec["structural"]["verdict"] = "REFUSAL: %s" % str(e)[:200]; rec["status"] = "STRUCTURAL_REFUSED"
            except TimeoutError:
                rec["structural"]["verdict"] = "TIMEOUT in support compilation at the %.0f s cap" % cap; rec["status"] = "STRUCTURAL_TIMEOUT"
        rec["phases_s"]["structural_total"] = now() - t
    atomic(os.path.join(out, "probe.json"), rec)
    # ---------------- phase 2: the existing route executed end-to-end (its own admission), inside the remaining cap
    remaining = cap - now() - 0.5
    verdict = rec["structural"].get("verdict", "")
    if rec["status"] == "STRUCTURAL_MEASURED" and remaining > 2.0:
        from mdi import arm as ARM
        t = now(); rr = ARM.run_arm("probe", False, out, eps=Fr(1, 100), wall=remaining, cap=cap_bytes, model_path=mp, evid_path=ep, support=(mech == "support"), quotient=(mech == "quotient"))
        pl = ((rr.get("pipeline") or {}).get("plan") or {}); sel = pl.get("selector") if isinstance(pl, dict) else None
        rec["execution"] = {"route_policy": mech, "wall_given_s": remaining, "outcome": rr.get("outcome"), "reason": str(rr.get("reason"))[:300], "elapsed_s": rr.get("elapsed_s"), "stages": rr.get("stages"), "executed_kind": pl.get("executed_kind"), "chosen": pl.get("chosen"),
                            "rejected_typed": [x.get("typed") for x in ((rr.get("pipeline") or {}).get("rejected") or [])], "final_max_width": rr.get("final_max_width"), "contract_met": rr.get("contract_met"), "independently_verified": rr.get("independently_verified"), "peak_rss_bytes": rr.get("peak_rss_bytes"),
                            "note": "the production route policy applies ITS admission (MIN_REDUCTION_RATIO, dense-identity checker forecast under the production byte cap); a refusal here with structural potential above is a residual gate", "phase_s": now() - t}
        rec["gates_remaining"].append({"gate": "route-policy admission inside mdi.pipeline (ratio + checker feasibility forecast + byte cap)", "role": "applied in the execution phase"})
    else:
        rec["execution"] = {"attempted": False, "why": ("structural phase found nothing to execute (%s)" % verdict) if rec["status"] != "STRUCTURAL_MEASURED" else "insufficient remaining cap (%.1f s)" % remaining}
    rec["complete_response_s"] = now(); atomic(os.path.join(out, "probe.json"), rec); print(json.dumps({"mech": mech, "status": rec["status"], "verdict": verdict[:80], "exec": (rec["execution"] or {}).get("outcome")}))


if __name__ == "__main__":
    main()
