"""Residual canonicalization after fitting (contract §E.1, E.2).

The corrected recognizer leaves residual pair tables that are near-trivial but
still present, so the graph keeps every edge and the statistic DP (correctly)
refuses them. This module performs the missing step:

  1. Transfer exactly separable or constant residual pairs into unaries.
  2. Bound and CHARGE the removal of the remaining tiny interactions.
  3. Drop those edges, leaving a product residual the DP can consume.

Step 2 is the only approximation and its cost is charged into the single
fit/rounding allowance, never reset.
"""
from __future__ import annotations
import sys
sys.set_int_max_str_digits(0)
from fractions import Fraction as Fr
from dataclasses import dataclass, field
from mdi import arith as A, config as K
from mdi.modes import gauge_split, Declined, _log_enclose


@dataclass
class Canonical:
    """A product residual plus the exact error charged to reach it."""
    unary: dict                  # var -> list of exact rational entries
    dropped_pairs: list          # [(i, j, log_radius)] edges removed
    transferred_pairs: list      # [(i, j)] exactly absorbed, zero error
    kept_pairs: dict             # (i,j) -> table, still interacting
    scale: Fr                    # exact constant pulled out
    nu_extra: Fr                 # ADDITIONAL uniform log error charged here
    detail: dict = field(default_factory=dict)

    def is_product(self) -> bool:
        return not self.kept_pairs


def canonicalize(residual_unary, residual_pairs, card, ctx: A.Ctx,
                 drop_budget: Fr):
    """Turn a fitted residual into a product law where the error permits.

    `drop_budget` is the uniform log-error still available from the single
    fit/rounding allowance. Edges are dropped in increasing order of their own
    log radius, and the running total may never exceed the budget.
    """
    unary = {v: [Fr(x) for x in row] for v, row in residual_unary.items()}
    scale = Fr(1)
    transferred, dropped, kept = [], [], {}
    nu_extra = Fr(0)
    budget = Fr(drop_budget)

    # --- step 1: exact transfers (zero error) ---
    pending = []
    for (i, j), tbl in sorted(residual_pairs.items()):
        t = [Fr(x) for x in tbl]
        di, dj = card[i], card[j]
        if any(x <= 0 for x in t):
            kept[(i, j)] = t                   # zeros stay; not our business
            continue
        t0 = t[0]
        if all(x == t0 for x in t):
            scale *= t0                        # constant: exact
            transferred.append((i, j))
            continue
        try:
            g = gauge_split(t, di, dj)
        except Declined:
            pending.append(((i, j), t))
            continue
        trivial = all(g.H[a][b] == 1 for a in range(di) for b in range(dj))
        if trivial:
            # F = C * u * v exactly: absorb into the endpoint unaries
            scale *= g.C
            for a in range(di):
                unary[i][a] *= g.u[a]
            for b in range(dj):
                unary[j][b] *= g.v[b]
            transferred.append((i, j))
        else:
            pending.append(((i, j), t))

    # --- step 2: bound and charge the remaining tiny interactions ---
    radii = []
    for (i, j), t in pending:
        di, dj = card[i], card[j]
        g = gauge_split(t, di, dj)
        # the interaction is H; removing it costs sup |log H| on the support
        worst = Fr(0)
        for a in range(di):
            for b in range(dj):
                h = Fr(g.H[a][b])
                if h <= 0:
                    worst = None
                    break
                lo, hi = _log_enclose(h, ctx)
                m = max(abs(lo), abs(hi))
                if m > worst:
                    worst = m
            if worst is None:
                break
        if worst is None:
            kept[(i, j)] = t
            continue
        radii.append((worst, (i, j), g))
    radii.sort(key=lambda x: (x[0], x[1]))

    for worst, (i, j), g in radii:
        if nu_extra + worst > budget:
            kept[(i, j)] = [Fr(x) for x in residual_pairs[(i, j)]]
            continue
        # drop H, keep C*u*v exactly
        di, dj = card[i], card[j]
        scale *= g.C
        for a in range(di):
            unary[i][a] *= g.u[a]
        for b in range(dj):
            unary[j][b] *= g.v[b]
        nu_extra += worst
        dropped.append((i, j, worst))

    detail = {"pairs_in": len(residual_pairs),
              "transferred_exactly": len(transferred),
              "dropped_with_charge": len(dropped),
              "kept_interacting": len(kept),
              "nu_extra": str(nu_extra),
              "drop_budget": str(budget),
              "worst_single_radius": str(max((r for r, _, _ in radii), default=Fr(0)))}
    return Canonical(unary=unary, dropped_pairs=dropped,
                     transferred_pairs=transferred, kept_pairs=kept,
                     scale=scale, nu_extra=nu_extra, detail=detail)


def tv_from_total_nu(nu_fit: Fr, nu_drop: Fr) -> Fr:
    """TV <= tanh(nu/2) <= nu/2 on the COMBINED uniform log error.

    The fit error and the drop error add; neither resets the other.
    """
    return K.tanh_upper(Fr(nu_fit) + Fr(nu_drop))
