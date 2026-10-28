"""Plan construction, pricing and selection (spec sections 2 step 6, and 8).

Costs are compared BEFORE global solving, using actual region/cell counts,
decomposition assignment counts, lattice counts, marker counts, precision,
memory and independent-checker work. Discovery and failed candidates are
charged. No full original solve acts as a planning oracle.
"""
from __future__ import annotations
import sys, time
sys.set_int_max_str_digits(0)
from fractions import Fraction as Fr
from dataclasses import dataclass, field
from mdi import config as K, model as M, plan as P, regions as R, modes as MD


@dataclass
class Candidate:
    name: str
    kind: str                     # identity | regional | mode_statistic | mode_gf | regional_mode
    radius: Fr                    # certified transformation radius actually charged
    forecast: dict                # symbolic cost forecast
    payload: dict = field(default_factory=dict)
    admitted: bool = True
    reason: str = ""


def price_identity(free, card, factors, bytes_per_entry, cap_bytes):
    """The no-transformation plan: generic elimination on the original model."""
    sel = P.choose_plan(free, card, factors, bytes_per_entry, cap_bytes)
    cands = sel["candidates"]
    best = sel["chosen"][0].stats() if sel["chosen"] else (cands[0][0] if cands else None)
    est = sel["chosen"][1] if sel["chosen"] else (cands[0][1] if cands else None)
    return Candidate(
        name="identity", kind="identity", radius=Fr(0),
        forecast={"plan": best, "bytes": est,
                  "fits": sel["fits"],
                  "arith_ops_lower_bound": (best or {}).get("sum_bag_entries", 0),
                  "note": "exact; no transformation radius charged"},
        payload={"selection": sel}, admitted=bool(sel["fits"]),
        reason="" if sel["fits"] else "no generic ordering fits the byte cap")


class DiscoveryWall(Exception):
    """The discovery wall was reached INSIDE a region, not only between them."""


def price_regional(free, card, factors, queries, levels, bytes_per_entry,
                   cap_bytes, wall_s, log=None):
    # NOTE: argument order here is (free, card, factors) while price_modes takes
    # (free, factors, card), matching each callee. A mismatch between a pricing
    # wrapper and its call site silently became "mode proposal failed" in the
    # first six invocations, so both signatures are now asserted on entry.
    """Discover partitions, merge, and price the resulting coarse model.

    Returns the best admitted regional candidate, plus every rejected one.
    """
    out, t0 = [], time.time()
    assert isinstance(card, dict), ("price_regional expects (free, card, factors) "
                                    "with card a mapping; got %s" % type(card))
    cands = R.propose_partitions(free, card, factors)
    t_level = K.level_radius(levels)
    for c in cands:
        if c["mode"] == "singleton":
            continue
        regs = c["regions"]
        rho_cap = K.region_distortion_budget(t_level, len(regs))
        tb = ta = comps = 0
        crs, rds, skipped = [], [], 0
        aborted = None
        def _dl():
            if time.time() - t0 > wall_s:
                raise DiscoveryWall("discovery wall %.0fs" % wall_s)

        region_of = {}
        for i, rr in enumerate(regs):
            for v in rr:
                region_of[v] = i
        for reg in regs:
            if time.time() - t0 > wall_s:
                aborted = "discovery wall %.0fs" % wall_s
                break
            try:
                rd = R.region_data(reg, card, factors, queries, deadline=_dl)
                cr = R.merge_region(rd, factors, card, rho_cap, queries,
                                    deadline=_dl, region_of=region_of)
            except DiscoveryWall as e:
                aborted = str(e)
                break
            except (R.CapExceeded, R.Declined) as e:
                skipped += 1
                continue
            rds.append(rd); crs.append(cr)
            tb += rd.n_boundary_states(); ta += len(cr.cells); comps += cr.comparisons
        if aborted or not crs:
            out.append(Candidate(name="regional:" + c["mode"], kind="regional",
                                 radius=Fr(0), forecast={"aborted": aborted,
                                 "regions": len(regs), "skipped": skipped},
                                 admitted=False,
                                 reason=aborted or "no region produced cells"))
            continue
        Rlevel = R.level_distortion(crs)
        certified = K.certify_R_against_t(Rlevel, t_level)
        # the coarse model's own elimination cost: cells replace boundary states
        reduction = Fr(ta, tb) if tb else Fr(1)
        cand = Candidate(
            name="regional:" + c["mode"], kind="regional",
            radius=t_level if certified else Fr(0),
            forecast={"regions": len(regs), "skipped": skipped,
                      "boundary_states": tb, "cells": ta,
                      "state_reduction": reduction,
                      "R_level": Rlevel, "certified": certified,
                      "profile_comparisons": comps,
                      "discovery_s": time.time() - t0},
            payload={"partition": c, "coarse": crs, "regions_data": rds},
            admitted=certified and ta < tb,
            reason="" if (certified and ta < tb) else
                   ("R_level %s not certified at t=%s" % (Rlevel, t_level)
                    if not certified else
                    "no state reduction (%d -> %d)" % (tb, ta)))
        out.append(cand)
        if log:
            log("regional", "%s regions=%d states %d->%d certified=%s"
                % (c["mode"], len(regs), tb, ta, certified))
    return out


def price_modes(free, factors, card, queries, ctx, wall_s, log=None):
    """Propose and verify collective modes; price the statistic and GF routes."""
    out, t0 = [], time.time()
    assert isinstance(card, dict), ("price_modes expects (free, factors, card) "
                                    "with card a mapping; got %s" % type(card))
    assert not isinstance(factors, dict), "factors must be a sequence, not a mapping"
    try:
        cands, info = MD.propose_modes(free, factors, card)
    except Exception as e:
        return [Candidate(name="modes", kind="mode_statistic", radius=Fr(0),
                          forecast={"error": "%s: %s" % (type(e).__name__, e)},
                          admitted=False, reason="mode proposal failed")]
    if not cands:
        return [Candidate(name="modes", kind="mode_statistic", radius=Fr(0),
                          forecast=info, admitted=False,
                          reason=info.get("declined", "no mode candidate"))]
    budget = K.RADII["collective_fit_and_rounding"]
    for i, cand in enumerate(cands):
        if time.time() - t0 > wall_s:
            out.append(Candidate(name="modes:%d" % i, kind="mode_statistic",
                                 radius=Fr(0), forecast={"aborted": True},
                                 admitted=False, reason="mode wall exceeded"))
            break
        try:
            res = MD.build_residual(free, factors, card, cand, ctx)
        except Exception as e:
            out.append(Candidate(name="modes:%d" % i, kind="mode_statistic",
                                 radius=Fr(0),
                                 forecast={"kind": cand.kind,
                                           "error": "%s: %s" % (type(e).__name__, e)},
                                 admitted=False, reason="residual construction declined"))
            continue
        tv = MD.tv_from_nu(res.nu)
        ok = tv <= budget
        out.append(Candidate(
            name="modes:%d:%s" % (i, cand.kind), kind="mode_statistic",
            radius=tv if ok else Fr(0),
            forecast={"kind": cand.kind, "signs": cand.signs,
                      "gammas": [str(g) for g in cand.gammas],
                      "nu": res.nu, "tv_bound": tv, "budget": budget,
                      "kept_factors": len(res.kept), "detail": res.detail,
                      "fit_s": time.time() - t0},
            payload={"candidate": cand, "residual": res},
            admitted=ok and not res.kept,
            reason="" if (ok and not res.kept) else
                   ("fit TV %s exceeds the allowance %s" % (tv, budget) if not ok
                    else "%d retained factors: the statistic route needs a pure "
                         "product residual" % len(res.kept))))
        if log:
            log("modes", "%s nu=%s tv=%s admitted=%s"
                % (cand.kind, res.nu, tv, out[-1].admitted))
    return out


def select(candidates, log=None):
    """Choose among admitted candidates. The identity plan is always retained.

    Selection prefers a genuine transformation ONLY when it is admitted and its
    forecast beats identity; a smaller coarse domain that does not reduce work is
    not selected (spec: "do not select solely by cell count").
    """
    identity = next((c for c in candidates if c.kind == "identity"), None)
    admitted = [c for c in candidates if c.admitted and c.kind != "identity"]
    rejected = [c for c in candidates if not c.admitted]
    chosen, why = identity, "identity retained: no admitted transformation"
    best = None
    for c in admitted:
        red = c.forecast.get("state_reduction")
        if red is None:
            continue
        if best is None or red < best.forecast["state_reduction"]:
            best = c
    if best is not None and identity is not None:
        red = best.forecast["state_reduction"]
        # require a material reduction to justify the charged radius and discovery
        if red <= Fr(1, 2):
            chosen = best
            why = ("transformation selected: state reduction %s beats the 1/2 "
                   "threshold" % red)
        else:
            why = ("identity retained: best admitted reduction %s does not "
                   "justify its charged radius and discovery cost" % red)
    elif best is not None:
        chosen, why = best, "identity not admitted; transformation selected"
    if log:
        log("select", why)
    return {"chosen": chosen, "why": why, "admitted": admitted,
            "rejected": [{"name": c.name, "reason": c.reason,
                          "forecast": c.forecast} for c in rejected],
            "all": candidates}
