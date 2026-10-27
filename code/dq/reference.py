"""Exhaustive reference for tiny models (n <= 8, at most 256 assignments): independently enclosed ORIGINAL-model quantities with
directed MPFR (gmpy2 contexts) — never used on the primary inputs.  Returns boxes (lo, hi) as Fractions."""
from __future__ import annotations

import sys
sys.set_int_max_str_digits(0)

from fractions import Fraction as Fr
from itertools import product

import gmpy2
from gmpy2 import mpfr, mpq

from dq.model import Model


def _box(x: Fr, bits):
    dn = gmpy2.context(precision=bits, round=gmpy2.RoundDown); up = gmpy2.context(precision=bits, round=gmpy2.RoundUp)
    q = mpq(x.numerator, x.denominator); return gmpy2.mpfr(q, bits, dn), gmpy2.mpfr(q, bits, up)


def _fr(x): q = mpq(x); return Fr(int(q.numerator), int(q.denominator))


def _cos_sin_box(tl, th, bits):
    """Directed enclosure of cos and sin over [tl, th]: endpoint values with both roundings plus +-1 where a critical point m*pi/2 lies inside."""
    dn = gmpy2.context(precision=bits, round=gmpy2.RoundDown); up = gmpy2.context(precision=bits, round=gmpy2.RoundUp)
    cl = min(dn.cos(tl), dn.cos(th)); ch = max(up.cos(tl), up.cos(th)); sl = min(dn.sin(tl), dn.sin(th)); sh = max(up.sin(tl), up.sin(th))
    pl, pu = dn.const_pi(), up.const_pi()
    import math
    m0 = int(math.floor(float(tl) / (float(pl) / 2))) - 1; m1 = int(math.ceil(float(th) / (float(pu) / 2))) + 1
    for mm in range(m0, m1 + 1):
        a1 = dn.mul(pl if mm >= 0 else pu, mm) / 2; a2 = up.mul(pu if mm >= 0 else pl, mm) / 2
        if a2 >= tl and a1 <= th:
            r4 = mm % 4
            if r4 == 0: ch = mpfr(1)
            if r4 == 2: cl = mpfr(-1)
            if r4 == 1: sh = mpfr(1)
            if r4 == 3: sl = mpfr(-1)
    return cl, ch, sl, sh


def enumerate_reference(m: Model, c: Fr | None = None, freqs: list | None = None, bits: int = 256) -> dict:
    """All configurations satisfying the pins.  Original weight w(x) = exp(h.x - (a.x)^2/2) prod psi; residual law at centre c:
    rho_c(x) = exp((h - a c).x) prod psi.  Returns p0 = mu(x_0 = +), q0 = Q_c(x_0=+), E_Q AX, G = E_Q exp(-(AX-c)^2/2), and
    phi_s(w) = E_Q[1{x_0=s} e^{i w AX}] for requested frequencies (rectangles)."""
    n = m.n; assert n <= 8
    dn = gmpy2.context(precision=bits, round=gmpy2.RoundDown); up = gmpy2.context(precision=bits, round=gmpy2.RoundUp)
    sites = [m.allowed(i) for i in range(n)]
    c = Fr(0) if c is None else Fr(c)
    rows = []
    for x in product(*sites):
        hx = sum((m.h[i] * x[i] for i in range(n)), Fr(0)); ax = sum((m.a[i] * x[i] for i in range(n)), Fr(0))
        psi = Fr(1)
        for i in range(n - 1):
            if x[i] == x[i + 1]: psi *= m.f[i]
        rows.append((x, hx, ax, psi))
    def ebox(e: Fr):   # exp of an exact rational as a box
        lo, hi = _box(e, bits); return dn.exp(lo), up.exp(hi)
    # original weights, residual weights at c, g factor
    W = []; R = []; GF = []
    for x, hx, ax, psi in rows:
        plo, phi = _box(psi, bits)
        wl, wh = ebox(hx - ax * ax / 2); W.append((dn.mul(wl, plo), up.mul(wh, phi)))
        rl, rh = ebox(hx - ax * c); R.append((dn.mul(rl, plo), up.mul(rh, phi)))
        gl, gh = ebox(-((ax - c) ** 2) / 2); GF.append((gl, gh))
    def ratio(num_idx):
        """box of sum_{idx in num} W / sum W for a list of weights"""
        pass
    def sumbox(items):
        lo = mpfr(0, bits); hi = mpfr(0, bits)
        for a, b in items: lo = dn.add(lo, a); hi = up.add(hi, b)
        return lo, hi
    def divbox(a, b):  # a, b positive boxes
        return dn.div(a[0], b[1]), up.div(a[1], b[0])
    Wt = sumbox(W); Rt = sumbox(R)
    plus = [k for k, (x, *_rest) in enumerate(rows) if x[m.query] == 1]
    p0 = divbox(sumbox([W[k] for k in plus]), Wt)
    q0 = divbox(sumbox([R[k] for k in plus]), Rt)
    # E_Q AX (signed): sum R_k ax_k / Rt with ax exact
    num_lo = mpfr(0, bits); num_hi = mpfr(0, bits)
    for k, (x, hx, ax, psi) in enumerate(rows):
        al, ah = _box(ax, bits)
        if ax >= 0: num_lo = dn.add(num_lo, dn.mul(R[k][0], al)); num_hi = up.add(num_hi, up.mul(R[k][1], ah))
        else: num_lo = dn.add(num_lo, dn.mul(R[k][1], al)); num_hi = up.add(num_hi, up.mul(R[k][0], ah))
    EAX = (dn.div(num_lo, Rt[1]) if num_lo >= 0 else dn.div(num_lo, Rt[0]), up.div(num_hi, Rt[0]) if num_hi >= 0 else up.div(num_hi, Rt[1]))
    G = divbox(sumbox([(dn.mul(R[k][0], GF[k][0]), up.mul(R[k][1], GF[k][1])) for k in range(len(rows))]), Rt)
    out = {"p0": (_fr(p0[0]), _fr(p0[1])), "q0": (_fr(q0[0]), _fr(q0[1])), "E_Q_AX": (_fr(EAX[0]), _fr(EAX[1])), "G": (_fr(G[0]), _fr(G[1])), "c": c, "assignments": len(rows)}
    out["N_plus"] = divbox(sumbox([(dn.mul(R[k][0], GF[k][0]), up.mul(R[k][1], GF[k][1])) for k in plus]), Rt)
    out["N_plus"] = (_fr(out["N_plus"][0]), _fr(out["N_plus"][1]))
    if freqs:
        out["phi"] = {}
        for w in freqs:
            w = Fr(w); accs = {1: [mpfr(0, bits)] * 4, -1: [mpfr(0, bits)] * 4}   # re_lo, re_hi, im_lo, im_hi
            for k, (x, hx, ax, psi) in enumerate(rows):
                s = x[m.query]
                tl, th = _box(w * ax, bits)
                cl2, ch2, sl2, sh2 = _cos_sin_box(tl, th, bits)
                rl, rh = R[k]
                a = accs[s]
                a[0] = dn.add(a[0], dn.mul(rl, cl2) if cl2 >= 0 else dn.mul(rh, cl2)); a[1] = up.add(a[1], up.mul(rh, ch2) if ch2 >= 0 else up.mul(rl, ch2))
                a[2] = dn.add(a[2], dn.mul(rl, sl2) if sl2 >= 0 else dn.mul(rh, sl2)); a[3] = up.add(a[3], up.mul(rh, sh2) if sh2 >= 0 else up.mul(rl, sh2))
            res = {}
            for s in (1, -1):
                a = accs[s]
                re = (dn.div(a[0], Rt[1]) if a[0] >= 0 else dn.div(a[0], Rt[0]), up.div(a[1], Rt[0]) if a[1] >= 0 else up.div(a[1], Rt[1]))
                im = (dn.div(a[2], Rt[1]) if a[2] >= 0 else dn.div(a[2], Rt[0]), up.div(a[3], Rt[0]) if a[3] >= 0 else up.div(a[3], Rt[1]))
                res[s] = {"re": (_fr(re[0]), _fr(re[1])), "im": (_fr(im[0]), _fr(im[1]))}
            out["phi"][str(w)] = res
    return out
