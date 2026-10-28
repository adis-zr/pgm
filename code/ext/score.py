"""Scorer for the external comparison. Separate from solver execution.

Validates output structure, then computes Hellinger error against a released
reference. Malformed probabilities are REPORTED, never silently repaired.
"""
from __future__ import annotations
from fractions import Fraction as Fr
import math

# Decimal-reference rounding handling, applied IDENTICALLY to every method.
# The released .uai.MAR files carry finitely many decimals, so a reference row
# need not sum to exactly 1. We renormalize the REFERENCE row by its own sum
# when that sum is within REF_SUM_TOL of 1, and record the largest deviation.
# We never renormalize a method's output to improve its score.
REF_SUM_TOL = Fr(1, 1000)
OUT_SUM_TOL = 1e-6


def validate_output(rows, model, ev, name="output"):
    """Structural checks: keys, finiteness, nonnegativity, normalization, evidence."""
    issues = []
    if len(rows) != model.nvars:
        issues.append("row count %d != nvars %d" % (len(rows), model.nvars))
        return issues
    worst_sum = 0.0
    for v, r in enumerate(rows):
        if len(r) != model.card[v]:
            issues.append("var %d: %d states, model says %d" % (v, len(r), model.card[v]))
            continue
        s = 0.0
        for st, x in enumerate(r):
            fx = float(x)
            if not math.isfinite(fx):
                issues.append("var %d state %d: non-finite %r" % (v, st, x))
            elif fx < 0:
                issues.append("var %d state %d: negative %r" % (v, st, x))
            s += fx
        if abs(s - 1.0) > OUT_SUM_TOL:
            issues.append("var %d: sums to %.12g" % (v, s))
        worst_sum = max(worst_sum, abs(s - 1.0))
        if v in ev:
            # observed variable must be the corresponding point mass
            want = ev[v]
            if abs(float(r[want]) - 1.0) > 1e-6:
                issues.append("observed var %d state %d has mass %.12g, expected 1"
                              % (v, want, float(r[want])))
    return issues


def ref_rounding_report(ref_rows):
    worst = Fr(0)
    for r in ref_rows:
        s = sum(r)
        d = abs(s - 1)
        if d > worst:
            worst = d
    return worst


def normalize_reference(ref_rows):
    """Renormalize each reference row by its own sum (decimal rounding handling)."""
    out = []
    for r in ref_rows:
        s = sum(r)
        assert s > 0, "reference row sums to zero"
        assert abs(s - 1) <= REF_SUM_TOL, ("reference row far from normalized", float(s))
        out.append([x / s for x in r])
    return out


def hellinger(p, q):
    """H = sqrt(0.5 * sum_s (sqrt(p_s) - sqrt(q_s))^2); p,q are float lists."""
    acc = 0.0
    for a, b in zip(p, q):
        d = math.sqrt(max(a, 0.0)) - math.sqrt(max(b, 0.0))
        acc += d * d
    return math.sqrt(0.5 * acc)


def score(rows, ref_rows, model, ev, exclude_observed=True):
    """Score a method's output against a released reference.

    Per the brief, H_i is computed for UNOBSERVED variables. Observed variables
    are point masses in both files and carry no information; they are counted
    separately so the accounting stays complete.
    """
    refn = normalize_reference(ref_rows)
    per = []
    max_h, sum_h, n = 0.0, 0.0, 0
    max_abs, max_abs_at = 0.0, None
    max_h_at = None
    obs_mismatch = 0
    for v in range(model.nvars):
        p = [float(x) for x in rows[v]]
        q = [float(x) for x in refn[v]]
        h = hellinger(p, q)
        ae = max(abs(a - b) for a, b in zip(p, q))
        if v in ev:
            if ae > 1e-6:
                obs_mismatch += 1
            per.append({"var": v, "observed": True, "hellinger": h, "max_abs": ae})
            if not exclude_observed:
                pass
            continue
        per.append({"var": v, "observed": False, "hellinger": h, "max_abs": ae})
        n += 1
        sum_h += h
        if h > max_h:
            max_h, max_h_at = h, v
        if ae > max_abs:
            max_abs, max_abs_at = ae, v
    nlog2 = (-math.log2(max_h)) if max_h > 0 else float("inf")
    return {
        "unobserved_scored": n,
        "observed_excluded": model.nvars - n,
        "observed_point_mass_mismatches": obs_mismatch,
        "max_hellinger": max_h,
        "max_hellinger_var": max_h_at,
        "mean_hellinger": (sum_h / n) if n else 0.0,
        "max_coord_abs_error": max_abs,
        "max_coord_abs_error_var": max_abs_at,
        "neg_log2_max_hellinger": nlog2,
        "per_var": per,
    }
