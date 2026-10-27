"""Positive marker masses, Gaussian node weight and accepted marker counts (CLAUDE_CODE_SPEC.md §5,
NUMERICAL_THEOREM.md §8 'Fixed positive-mass publication and replay' and eq. (16)-(17)).

Producer: marker-retaining positive transfer at MPFR256, forward site order, exact power-of-two layer scaling with
checked integer cumulative exponents; publish the exact interval midpoint times [1-2^-200, 1+2^-200]; add the two
marker boxes by exact endpoint addition for the total.
Checker: the same transfer independently reconstructed in REVERSE site order at MPFR320; its UNPADDED interval must be
contained in the producer publication (never pad the checker and demand containment).
Node weight: exponent -(y0^2+y1^2)/2 assembled exactly; same relative-publication rule.
Accepted count, eq. (17): (T_pub * I_pub,sigma + [-delta*Z_sigma^+, +delta*Z_sigma^+]) cap [0, Z_sigma^+], using the
full outward interval product including negative endpoints of the Fourier interval."""
from __future__ import annotations
import sys
sys.set_int_max_str_digits(0)
from fractions import Fraction as Fr
import gmpy2
from h4a.tables import MP, fr
from h4a.build import _unary_iv, sqrt_cache_for, P4

S_PUB = Fr(1, 1 << 200)

def _layer_scale(M, arr):
    hi = None
    for v in arr.values():
        if v is None: continue
        if hi is None or v[1] > hi: hi = v[1]
    if hi is None or not hi > 0: raise ValueError("empty or non-positive mass layer")
    e = -int(gmpy2.get_exp(hi))
    return {k: (None if v is None else M.scale2(v, e)) for k, v in arr.items()}, e

def marker_masses(prob, prec, reverse=False):
    """Z_sigma for sigma = -1, +1 as exact rational intervals, with the full-scale power of two restored exactly.
    reverse=False: forward site order (producer).  reverse=True: reverse site order (independent checker)."""
    M = MP(prec); m = prob.m; n = m.n
    sc = sqrt_cache_for(M, n, [beta for (_, beta) in prob.POS_LOCAL])
    v = [{x: _unary_iv(M, prob, i, x, sc) for x in prob.allowed[i]} for i in range(n)]
    exps = 0
    # state: (x_{i-1}, x_i, marker) with marker in {-1,0,+1}; 0 = target not yet visited
    if not reverse:
        cur = {}
        for a in prob.allowed[0]:
            for b in prob.allowed[1]:
                mk = 0
                if prob.q == 0: mk = a
                if prob.q == 1: mk = b
                cur[(a, b, mk)] = M.mul_pos(M.mul_pos(v[0][a], v[1][b]), M.q(m.psi(0, 1, a, b)))
        cur, e = _layer_scale(M, cur); exps += e
        for i in range(2, n):
            nxt = {}
            for (c, a, mk), val in cur.items():
                if val is None: continue
                for b in prob.allowed[i]:
                    mk2 = b if i == prob.q else mk
                    w = M.mul_pos(val, M.q(m.psi(i - 2, i, c, b)))
                    w = M.mul_pos(w, M.mul_pos(v[i][b], M.q(m.psi(i - 1, i, a, b))))
                    k = (a, b, mk2)
                    nxt[k] = w if k not in nxt else M.add(nxt[k], w)
            cur, e = _layer_scale(M, nxt); exps += e
    else:
        cur = {}
        for a in prob.allowed[n - 2]:
            for b in prob.allowed[n - 1]:
                mk = 0
                if prob.q == n - 2: mk = a
                if prob.q == n - 1: mk = b
                cur[(a, b, mk)] = M.mul_pos(M.mul_pos(v[n - 2][a], v[n - 1][b]), M.q(m.psi(n - 2, n - 1, a, b)))
        cur, e = _layer_scale(M, cur); exps += e
        for i in range(n - 3, -1, -1):
            nxt = {}
            for (a, b, mk), val in cur.items():
                if val is None: continue
                for c in prob.allowed[i]:
                    mk2 = c if i == prob.q else mk
                    w = M.mul_pos(val, M.q(m.psi(i, i + 2, c, b)))
                    w = M.mul_pos(w, M.mul_pos(v[i][c], M.q(m.psi(i, i + 1, c, a))))
                    k = (c, a, mk2)
                    nxt[k] = w if k not in nxt else M.add(nxt[k], w)
            cur, e = _layer_scale(M, nxt); exps += e
    out = {}
    for sg in (-1, 1):
        tot = None
        for (a, b, mk), val in cur.items():
            if val is None or mk != sg: continue
            tot = val if tot is None else M.add(tot, val)
        if tot is None: raise ValueError(f"marker {sg} has empty support; a numerical zero is not a support proof")
        lo, hi = fr(tot[0]), fr(tot[1])
        if not lo > 0: raise ValueError(f"marker {sg} mass lower endpoint not strictly positive")
        scale = Fr(2) ** (-exps)      # undo the accumulated layer scaling exactly
        out[sg] = (lo * scale, hi * scale)
    return out, exps

def publish_relative(iv):
    """exact midpoint m, published as [m(1-2^-200), m(1+2^-200)]"""
    mid = (iv[0] + iv[1]) / 2
    return {"midpoint": mid, "pub": (mid * (1 - S_PUB), mid * (1 + S_PUB))}

def node_weight(node, prec):
    """w_y = exp(-(y0^2+y1^2)/2); the exponent is exact in the frozen domain"""
    M = MP(prec)
    e = -Fr(int(node[0]) ** 2 + int(node[1]) ** 2, 2)
    iv = M.exp(M.q(e))
    return (fr(iv[0]), fr(iv[1])), e

def accepted_count(T_pub, I_pub, Zsig_pub_hi, delta):
    """eq. (17): (T * I + [-delta*Z^+, delta*Z^+]) cap [0, Z^+], full outward product including negative endpoints"""
    prods = [T_pub[0] * I_pub[0], T_pub[0] * I_pub[1], T_pub[1] * I_pub[0], T_pub[1] * I_pub[1]]
    lo, hi = min(prods), max(prods)
    lo -= delta * Zsig_pub_hi; hi += delta * Zsig_pub_hi
    return (max(Fr(0), lo), min(Zsig_pub_hi, hi))

def verify_masses(prod, chk):
    """checker's UNPADDED intervals must be contained in the producer's relative publications"""
    out = {}
    for sg in (-1, 1):
        p = prod["markers"][sg]["pub"]; c = chk["markers"][sg]
        out[f"marker_{sg}_unpadded_checker_contained"] = p[0] <= c[0] and c[1] <= p[1]
        out[f"marker_{sg}_producer_mass_positive"] = prod["markers"][sg]["midpoint"] > 0
    tp = prod["total"]["pub"]; tc = (chk["markers"][-1][0] + chk["markers"][1][0], chk["markers"][-1][1] + chk["markers"][1][1])
    out["total_unpadded_checker_contained"] = tp[0] <= tc[0] and tc[1] <= tp[1]
    wp = prod["node_weight"]["pub"]; wc = chk["node_weight"]
    out["node_weight_unpadded_checker_contained"] = wp[0] <= wc[0] and wc[1] <= wp[1]
    out["node_weight_exponent_identical"] = str(prod["node_weight"]["exponent"]) == str(chk["node_weight_exponent"])
    return out
