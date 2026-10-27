"""Independent 512-bit directed enumeration reference for the tiny fixtures (Stage A).
Enumerates every compatible configuration of the positive-node law Q, forming
   f_sigma(k) = E_Q[ 1{X_q=sigma} exp(i sum_j theta_j(k,X_j)) ],  normalized by the TOTAL positive mass,
and the weighted response sum_k lambda_k Re f_sigma(k). No message passing is used: this is a direct sum."""
from __future__ import annotations
import sys
sys.set_int_max_str_digits(0)
from fractions import Fraction as Fr
from itertools import product
from h4a.tables import MP, fr
from h4a.grid import PI_LO, PI_HI

def enumerate_reference(prob, grid, prec=512, sqrt2n=None):
    M = MP(prec); m = prob.m; n = m.n
    sc = {beta: M.sqrt(M.q(Fr(beta) / n)) for (_, beta) in prob.POS_LOCAL}
    s2n = M.sqrt(M.q(Fr(2, n)))                     # sqrt(2/n) for the negative phase
    free = prob.free
    # exact unary weight enclosure per site/spin
    def unary(i, x):
        arg = M.q(prob.field[i] * x)
        for (beta, j, u) in prob.node_coef[i]:
            if j == 0: continue
            arg = M.add(arg, M.mul(sc[beta], M.q(Fr(j) * u * x)))
        return M.exp(arg)
    U = [{x: unary(i, x) for x in prob.allowed[i]} for i in range(n)]
    reps = grid.reps; h2, h3 = grid.h[0], grid.h[1]
    Ztot = None; Zsig = {-1: None, 1: None}
    acc = {(sg, idx): [None, None] for sg in (-1, 1) for idx in range(len(reps))}
    for bits in product(*[prob.allowed[i] for i in range(n)]):
        x = list(bits)
        w = M.q(Fr(1))
        for i in range(n): w = M.mul_pos(w, U[i][x[i]])
        for (i, j, tbl) in m.factors: w = M.mul_pos(w, M.q(m.psi(i, j, x[i], x[j])))
        Ztot = w if Ztot is None else M.add(Ztot, w)
        sg = x[prob.q]
        Zsig[sg] = w if Zsig[sg] is None else M.add(Zsig[sg], w)
        # phase: theta = sqrt(2/n) * sum_i x_i (h2 k2 u_i2 + h3 k3 u_i3)
        for idx, (k2, k3, mult) in enumerate(reps):
            r = sum((Fr(x[i]) * (h2 * k2 * m.u[i][2] + h3 * k3 * m.u[i][3]) for i in range(n)), Fr(0))
            ang = M.mul(s2n, M.q(r))
            c, s = M.cos_sin(ang)
            cr = M.mul(w, c); ci = M.mul(w, s)
            a = acc[(sg, idx)]
            a[0] = cr if a[0] is None else M.add(a[0], cr)
            a[1] = ci if a[1] is None else M.add(a[1], ci)
    out = {}
    for sg in (-1, 1):
        ch = []
        for idx in range(len(reps)):
            a = acc[(sg, idx)]
            if a[0] is None: ch.append(((Fr(0), Fr(0)), (Fr(0), Fr(0)))); continue
            re = M.div_pos(a[0], Ztot); im = M.div_pos(a[1], Ztot)
            ch.append(((fr(re[0]), fr(re[1])), (fr(im[0]), fr(im[1]))))
        out[sg] = ch
    # weighted response with exact lambda enclosures
    lam = []
    for (k2, k3, mult) in reps:
        e = -((h2 * k2) ** 2 + (h3 * k3) ** 2) / 2
        pref = M.div_pos(M.mul_pos(M.q(h2 * h3), M.q(Fr(mult))), (M.q(2 * PI_LO)[0], M.q(2 * PI_HI)[1]))
        lam.append(M.mul_pos(pref, M.exp(M.q(e))))
    resp = {}
    for sg in (-1, 1):
        tot = None
        for idx in range(len(reps)):
            re = out[sg][idx][0]
            t = M.mul((M.q(re[0])[0], M.q(re[1])[1]), lam[idx])
            tot = t if tot is None else M.add(tot, t)
        resp[sg] = (fr(tot[0]), fr(tot[1]))
    Zt = (fr(Ztot[0]), fr(Ztot[1]))
    Zs = {sg: (fr(Zsig[sg][0]), fr(Zsig[sg][1])) for sg in (-1, 1)}
    return {"channels": out, "response": resp, "Z_total": Zt, "Z_sigma": Zs, "lambda_total": (fr(sum_iv(M, lam)[0]), fr(sum_iv(M, lam)[1])), "prec": prec}

def sum_iv(M, lst):
    t = None
    for v in lst: t = v if t is None else M.add(t, v)
    return t
