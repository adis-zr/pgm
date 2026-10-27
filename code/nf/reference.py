"""256-bit exhaustive positive-weight enumeration for the fixed tiny fixtures: residual Q at a center, the full target mu, singleton
marginals, projected means, center gradient, and the actual moment M = E_Q||A_F X_F - c||^2 (centred, exact elimination of pins)."""
from __future__ import annotations
import sys
sys.set_int_max_str_digits(0)
from fractions import Fraction as Fr
from itertools import product
from .ivpy import IvCtx
from .model import Model

def enumerate_laws(M: Model, c, prec=256, drop_energy_constant=True):
    C = IvCtx(prec); n, r = M.n, M.r; free = [i for i in range(n) if M.pin[i] == 0]; sE = M.s_E()
    cs = [c[l] + sE[l] for l in range(r)]
    # residual fields (exact rationals) and target exponent: h_F·x − ||A_F x_F + s_E||²/2 (+ constant dropped: ||s_E||²/2 is spin independent)
    acc = {"Q": [C.ui(0)] * 1, "mu": [C.ui(0)]}
    Zq = C.ui(0); Zmu = C.ui(0); numQ = [C.ui(0)] * n; numMu = [C.ui(0)] * n; Mnum = C.ui(0); AmQ = [C.ui(0)] * r
    for bits in product((-1, 1), repeat=len(free)):
        x = [0] * n
        for i, b in zip(free, bits): x[i] = b
        for i in range(n):
            if M.pin[i]: x[i] = M.pin[i]
        edge = Fr(1)
        for i in range(n - 1):
            if x[i] == x[i + 1]: edge *= M.f[i]
        theta_q = sum(((M.h[i] - sum(M.A[l][i] * cs[l] for l in range(r))) * x[i] for i in free), Fr(0))
        Ax = [sum(M.A[l][i] * x[i] for i in free) for l in range(r)]           # free statistic A_F x_F
        y = [Ax[l] + sE[l] for l in range(r)]                                   # full statistic
        e_mu = sum((M.h[i] * x[i] for i in free), Fr(0)) - sum(yy * yy for yy in y) / 2
        if drop_energy_constant: e_mu += sum(s * s for s in sE) / 2
        wq = C.q(edge) * C.q(theta_q).exp(); wm = C.q(edge) * C.q(e_mu).exp()
        Zq = Zq + wq; Zmu = Zmu + wm
        for i in range(n):
            if x[i] == 1: numQ[i] = numQ[i] + wq; numMu[i] = numMu[i] + wm
        z2 = sum(((Ax[l] - c[l]) ** 2 for l in range(r)), Fr(0)); Mnum = Mnum + wq * C.q(z2)
        for l in range(r): AmQ[l] = AmQ[l] + wq * C.q(Ax[l])
    q = [numQ[i].div_pos(Zq) for i in range(n)]; p = [numMu[i].div_pos(Zmu) for i in range(n)]
    for i in range(n):                       # pinned sites: exact singleton answers (the enumerated ratio is an interval around 1 or 0)
        if M.pin[i]: q[i] = p[i] = C.ui(1 if M.pin[i] > 0 else 0)
    Mact = Mnum.div_pos(Zq); Am = [AmQ[l].div_pos(Zq) for l in range(r)]
    g = [C.q(c[l]) - Am[l] for l in range(r)]
    return {"q": q, "p": p, "M": Mact, "gradient": g, "A_mean": Am, "states": 2 ** len(free), "prec": prec, "energy_constant_dropped": drop_energy_constant}
