"""Regression for the positive periodic grid (GF1) and the negative grid (GF2).

A graph-only check: for the Chapter 05 grids the engine constructs, the
weighted sum Q+(s) = h/sqrt(2 pi) sum_{|j|<=K} e^{-(jh)^2/2 + sqrt(beta) j h s}
must lie within (1 -/+ d) e^{beta s^2/2} for every sampled |s| <= R, and
|Q-(s) - e^{-a s^2/2}| < e. Evaluated in 200-bit MPFR on a dense sample of s;
this is a numerical REGRESSION of the proved inequalities, not a proof.

    python -m benchmark.gf_grid_regression

The file in the overseer packet was not available on this machine; this is
the build's own regression for the same property, labelled as such.
"""
from __future__ import annotations
import sys, os, json
sys.set_int_max_str_digits(0)
from fractions import Fraction as Fr
HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)
import gmpy2
from gmpy2 import mpfr


def _q(x):
    return gmpy2.mpq(x.numerator, x.denominator)


def check_gf1(beta, R, d, samples=257):
    from mdi import collective as CO
    g = CO.gf1_grid(beta, R, d)
    gmpy2.get_context().precision = 200
    h = _q(Fr(g["h"]))
    sb = gmpy2.sqrt(mpfr(_q(beta)))
    c = h / gmpy2.sqrt(2 * gmpy2.const_pi())
    worst = mpfr(0)
    for i in range(samples):
        s = mpfr(_q(-R + 2 * R * Fr(i, samples - 1)))
        acc = mpfr(0)
        for j in range(-g["K"], g["K"] + 1):
            z = mpfr(j) * h
            acc += gmpy2.exp(-z * z / 2 + sb * z * s)
        Q = c * acc
        ex = gmpy2.exp(mpfr(_q(beta)) * s * s / 2)
        ratio = Q / ex
        worst = max(worst, abs(ratio - 1))
    return {"grid": {k: (str(v) if isinstance(v, Fr) else v) for k, v in g.items() if k in ("t", "m", "T", "b", "K", "h", "nodes", "tol")},
            "worst_relative_error": float(worst), "bound_d": float(d), "ok": worst < mpfr(_q(d))}


def check_gf2(a, R, e, samples=257):
    from mdi import collective as CO
    g = CO.gf2_grid(a, R, e)
    gmpy2.get_context().precision = 200
    h = _q(Fr(g["h"]))
    sa = gmpy2.sqrt(mpfr(_q(a)))
    c = h / gmpy2.sqrt(2 * gmpy2.const_pi())
    worst = mpfr(0)
    for i in range(samples):
        s = mpfr(_q(-R + 2 * R * Fr(i, samples - 1)))
        acc = mpfr(0)
        for j in range(-g["J"], g["J"] + 1):
            z = mpfr(j) * h
            acc += gmpy2.exp(-z * z / 2) * gmpy2.cos(sa * z * s)
        Q = c * acc
        ex = gmpy2.exp(-mpfr(_q(a)) * s * s / 2)
        worst = max(worst, abs(Q - ex))
    coef_sum = c * sum(gmpy2.exp(-(mpfr(j) * h) ** 2 / 2) for j in range(-g["J"], g["J"] + 1))
    return {"grid": {k: (str(v) if isinstance(v, Fr) else v) for k, v in g.items() if k in ("t", "m", "T", "b", "J", "h", "nodes", "representatives", "tol")},
            "worst_absolute_error": float(worst), "bound_e": float(e), "coefficient_sum": float(coef_sum),
            "ok": worst < mpfr(_q(e)) and coef_sum <= 1 + mpfr(_q(e))}


def run():
    cases = {
        "chain positive mode (beta=0.48818, R=0.328056, d=1/1024)": check_gf1(Fr(48818, 100000), Fr(328056, 1000000), Fr(1, 1024)),
        "chain negative mode (a=0.90903, R=0.700684, e~1.3e-6)": check_gf2(Fr(90903, 100000), Fr(700684, 1000000), Fr(13, 10 ** 7)),
        "wide positive (beta=1, R=4, d=1/64)": check_gf1(Fr(1), Fr(4), Fr(1, 64)),
        "wide negative (a=1, R=4, e=1/256)": check_gf2(Fr(1), Fr(4), Fr(1, 256)),
    }
    cases["ok"] = all(v["ok"] for v in cases.values())
    return cases


if __name__ == "__main__":
    out = run()
    print(json.dumps(out, indent=1, default=str))
    sys.exit(0 if out["ok"] else 1)
