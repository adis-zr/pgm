"""The retained law Q through the EXISTING sparse path: pipeline.solve(masked model, evidence, route_policy="support").
Exposes the certified singleton enclosures under Q, the exact retained mass R (the checker's independent exact aggregation,
reconciled to original weight units through the exposed scale metadata) and the route that executed. A masked model whose
retained set is empty returns ZERO_EVIDENCE_PROVED: that is a certificate-route refusal (an inconsistent retained model does
not make the original positive model inconsistent)."""
from __future__ import annotations
from fractions import Fraction as Fr
import os, time, tempfile
from mdi import pipeline as PLN
import mdi.registry  # noqa: F401


def solve_retained(masked, ev, wall_s, cap_bytes, plan_dir=None, route_policy="support", progress=None):
    t0 = time.monotonic()
    res = PLN.solve(masked, ev, queries=None, wall_s=wall_s, cap_bytes=cap_bytes, research_enabled=False, route_policy=route_policy,
                    plan_dir=plan_dir or tempfile.mkdtemp(), progress=progress)
    out = {"status": res.status, "reason": res.reason, "wall_s": round(time.monotonic() - t0, 6), "stages": res.stages,
           "checker_status": (res.checker or {}).get("status"), "coordinates_checked": (res.checker or {}).get("coordinates_checked"),
           "independent_aggregation_scope": (res.checker or {}).get("independent_aggregation_scope"),
           "exact_total": (res.checker or {}).get("exact_total"), "executed": (res.plan.get("executed") or {}) if res.plan else {},
           "support": None, "rejected_typed": [x.get("typed") for x in (res.rejected or [])], "budget_used_by_source": (res.budget or {}).get("used_by_source"),
           "intervals": None, "R": None, "R_units": None}
    ex = out["executed"] if isinstance(out["executed"], dict) else {}
    out["executed"] = {k: ex.get(k) for k in ("evaluator", "ops", "layout", "peak_live_message_entries", "support") if k in ex}
    out["route"] = "support" if ex.get("support") else ("dense" if res.status.startswith("CERTIFIED") else None)
    out["support_price"] = next((x.get("support_price") for x in (res.rejected or []) if isinstance(x, dict) and x.get("support_price")), None)
    if res.status.startswith("CERTIFIED"):
        out["intervals"] = {int(v): [[str(lo), str(hi)] for lo, hi in rows] for v, rows in res.intervals.items()}
        zt = out["exact_total"]
        if zt and zt.get("Z_original_units") is not None:
            out["R"] = zt["Z_original_units"]; out["R_units"] = "original weight units (reconciled: Z_aggregate / aggregate_scale_denominator * preprocess_scale * restricted_constant)"
            out["R_kind"] = "exact (independent exact aggregation of the checker)"
    elif res.status == "ZERO_EVIDENCE_PROVED":
        out["refusal"] = "INCONSISTENT_RETENTION: the retained set is empty (R = 0); the certificate route refuses; the original positive model is unaffected"
    out["plan_summary"] = {k: res.plan.get(k) for k in ("kind", "executed_kind", "route_policy", "why")} if res.plan else None
    return out, res
