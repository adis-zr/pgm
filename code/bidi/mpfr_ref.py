"""MPFR-53 round-to-nearest reference implementation of the SAME conditioned stream schedule as bidi/kernel.cpp (lanes by top k bits,
Gray code over the low bits, current-leaf product trees of P leaves, prefix/suffix exclusion products, per-lane accumulators, sequential
lane reduction). Used (a) in qualification to compare bitwise with the native kernel on tiny models (same schedule + same rounding => same
binary64 values when no subnormal/overflow occurs) and (b) as the BIDI_MPFR53_CERT diagnostic arm. One numeric pass; Python per-state loop
(deliberately: this is the object/dispatch-cost comparator). Interface mirrors the native bridge: create / step / done / finish."""
from __future__ import annotations
import gmpy2
from gmpy2 import mpfr


class Ref:
    def __init__(self, m, n, k, phi, rho, psi, kappa, precision=53):
        assert k <= n and k <= 12
        self.ctx = gmpy2.context(precision=precision, round=gmpy2.RoundToNearest, trap_overflow=True, trap_underflow=True, trap_invalid=True, trap_divzero=True)
        gmpy2.set_context(self.ctx)
        self.m, self.n, self.k, self.L, self.nlow = m, n, k, 1 << k, n - k
        P = 1
        while P < n + 1:
            P <<= 1
        self.P = P; self.steps_total = 1 << self.nlow; self.step = 0; self.ylow = 0
        c = lambda x: mpfr(x)
        self.phi = [[c(phi[i * 2 + a]) for a in range(2)] for i in range(m)]; self.rho = [[c(rho[j * 2 + b]) for b in range(2)] for j in range(n)]
        self.psi = [[[[c(psi[((i * n) + j) * 4 + a * 2 + b]) for b in range(2)] for a in range(2)] for j in range(n)] for i in range(m)]; self.kappa = c(kappa)
        self.ZL = [mpfr(0)] * self.L; self.NYlow = [[[mpfr(0)] * self.L for _ in range(2)] for _ in range(self.nlow)]; self.NX = [[[mpfr(0)] * self.L for _ in range(2)] for _ in range(m)]
        self.tree = [[[mpfr(0)] * self.L for _ in range(2 * P)] for _ in range(2 * m + 1)]
        self.configs_visited = 0; self.mults = 0; self.adds = 0
        for q in range(2 * m + 1):
            for l in range(self.L):
                self._leaf_set(q, 0, l, self.phi[q >> 1][q & 1] if q < 2 * m else self.kappa)
                for j in range(n):
                    yj = (self.ylow >> j) & 1 if j < self.nlow else (l >> (j - self.nlow)) & 1
                    self._leaf_set(q, 1 + j, l, self.psi[q >> 1][j][q & 1][yj] if q < 2 * m else self.rho[j][yj])
                for j in range(n + 1, P):
                    self._leaf_set(q, j, l, mpfr(1))
            T = self.tree[q]
            for t in range(P - 1, 0, -1):
                T[t] = [T[2 * t][l] * T[2 * t + 1][l] for l in range(self.L)]; self.mults += self.L

    def _leaf_set(self, q, leaf, l, v):
        self.tree[q][self.P + leaf][l] = v

    def _update_ancestors(self, q, leaf):
        T = self.tree[q]; t = (self.P + leaf) >> 1
        while t >= 1:
            T[t] = [T[2 * t][l] * T[2 * t + 1][l] for l in range(self.L)]; self.mults += self.L
            if t == 1:
                break
            t >>= 1

    def _flip(self, j):
        self.ylow ^= (1 << j); yj = (self.ylow >> j) & 1
        for q in range(2 * self.m + 1):
            v = self.psi[q >> 1][j][q & 1][yj] if q < 2 * self.m else self.rho[j][yj]
            for l in range(self.L):
                self.tree[q][self.P + 1 + j][l] = v
            self._update_ancestors(q, 1 + j)

    def _accumulate(self):
        m, L = self.m, self.L
        A0 = [self.tree[2 * i][1] for i in range(m)]; A1 = [self.tree[2 * i + 1][1] for i in range(m)]
        H = [[A0[i][l] + A1[i][l] for l in range(L)] for i in range(m)]; self.adds += m * L
        pre = [[mpfr(1)] * L]
        for i in range(m):
            pre.append([pre[i][l] * H[i][l] for l in range(L)]); self.mults += L
        suf = [None] * (m + 1); suf[m] = [mpfr(1)] * L
        for i in range(m, 0, -1):
            suf[i - 1] = [H[i - 1][l] * suf[i][l] for l in range(L)]; self.mults += L
        B = self.tree[2 * m][1]; T = [B[l] * pre[m][l] for l in range(L)]; self.mults += L
        self.ZL = [self.ZL[l] + T[l] for l in range(L)]; self.adds += L
        for j in range(self.nlow):
            yj = (self.ylow >> j) & 1; acc = self.NYlow[j][yj]; self.NYlow[j][yj] = [acc[l] + T[l] for l in range(L)]; self.adds += L
        for i in range(m):
            for l in range(L):
                c = pre[i][l] * suf[i + 1][l]; bc = B[l] * c
                self.NX[i][0][l] = self.NX[i][0][l] + bc * A0[i][l]; self.NX[i][1][l] = self.NX[i][1][l] + bc * A1[i][l]; self.mults += 4; self.adds += 2
        self.configs_visited += L

    def step_n(self, max_steps):
        gmpy2.set_context(self.ctx); done = 0
        while done < max_steps and self.step < self.steps_total:
            if self.step > 0:
                self._flip((self.step & -self.step).bit_length() - 1)
            self._accumulate(); self.step += 1; done += 1
        return done

    def done(self):
        return self.step >= self.steps_total

    def finish(self):
        gmpy2.set_context(self.ctx); m, n, L = self.m, self.n, self.L
        Z = mpfr(0)
        for l in range(L):
            Z = Z + self.ZL[l]; self.adds += 1
        NX = []
        for i in range(m):
            for a in range(2):
                acc = mpfr(0)
                for l in range(L):
                    acc = acc + self.NX[i][a][l]; self.adds += 1
                NX.append(acc)
        NY = []
        for j in range(n):
            for b in range(2):
                acc = mpfr(0)
                if j < self.nlow:
                    for l in range(L):
                        acc = acc + self.NYlow[j][b][l]; self.adds += 1
                else:
                    for l in range(L):
                        if ((l >> (j - self.nlow)) & 1) == b:
                            acc = acc + self.ZL[l]; self.adds += 1
                NY.append(acc)
        complete = (self.step == self.steps_total and self.configs_visited == (self.steps_total << self.k))
        return Z, NX, NY, {"configs": self.configs_visited, "lanes": L, "mults": self.mults, "adds": self.adds}, complete
