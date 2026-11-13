"""Input law, validation, bit convention, exact kernel integers, tails, publication grid, scouts, cost proxies, selector."""
from __future__ import annotations
from fractions import Fraction as Fr
from math import comb
import hashlib, json
import numpy as np

GRID_BITS = 80                                   # publication grid 2^-80, outward rounding
BIT_CONVENTION = "coordinate i (0-based, i = 0..n-1) <-> bit i of the integer mask; bit set <-> x_i = +1; bit clear <-> x_i = -1"
R_GRID = [Fr(1), Fr(1) - Fr(1, 2 ** 24), Fr(1) - Fr(1, 2 ** 12), Fr(1, 2), Fr(1, 64), Fr(1, 128), Fr(1, 256), Fr(0)]
R_PRIORITY = [Fr(1), Fr(1, 64), Fr(1, 128), Fr(1, 256), Fr(1) - Fr(1, 2 ** 24), Fr(1) - Fr(1, 2 ** 12), Fr(0), Fr(1, 2)]
WIDTHS = [Fr(1, 100), Fr(1, 20)]
ROUTE_ORDER = ["S0", "S1", "F0", "F1", "F2", "F3", "E", "W"]
EPS_GRID_SLACK = Fr(1, 2 ** (GRID_BITS - 1))     # 2^(1-P): outward rounding adds at most this to a width


def r_label(r):
    r = Fr(r)
    if r == 1: return "r=1"
    if r == 0: return "r=0"
    if r == 1 - Fr(1, 2 ** 24): return "r=1-2^-24"
    if r == 1 - Fr(1, 2 ** 12): return "r=1-2^-12"
    return "r=%d/%d" % (r.numerator, r.denominator)


class InputError(ValueError):
    pass


class Law:
    """Validated coupled-block input. Rows are integer masks (BIT_CONVENTION); weights positive integers; duplicate rows
    (within A or within B) are REJECTED; every mask lies in [0, 2^n)."""

    def __init__(self, n, A, B, source=None):
        self.n = int(n)
        if self.n < 1 or self.n > 63:
            raise InputError("n must be in 1..63 (packed-word model); got %d" % self.n)
        self.A_rows, self.A_w = self._rows(A, "A"); self.B_rows, self.B_w = self._rows(B, "B")
        self.A0 = int(sum(self.A_w)); self.B0 = int(sum(self.B_w))
        self.mA = len(self.A_rows); self.mB = len(self.B_rows)
        self.X = np.array(self.A_rows, dtype=np.uint64); self.Y = np.array(self.B_rows, dtype=np.uint64)
        self.full = (1 << self.n) - 1
        self.source = source

    def _rows(self, rows, name):
        if not rows:
            raise InputError("%s is empty" % name)
        masks, ws, seen = [], [], set()
        for x, w in rows:
            x = int(x); w = int(w)
            if not (0 <= x <= (1 << self.n) - 1):
                raise InputError("%s row %d outside [0, 2^n)" % (name, x))
            if w <= 0:
                raise InputError("%s row %d has non-positive weight %d" % (name, x, w))
            if x in seen:
                raise InputError("%s has a duplicate row %d (combine or reject before normalization: REJECTED)" % (name, x))
            seen.add(x); masks.append(x); ws.append(w)
        return masks, ws

    @staticmethod
    def load(path):
        d = json.load(open(path))
        law = Law(d["n"], d["A"], d["B"], source=path)
        law.sha256 = hashlib.sha256(open(path, "rb").read()).hexdigest()
        return law

    def pi_plus_int(self):
        """Σ_{x: x_i = +1} a(x) for every i (numerators of the ignore-bridge marginals pi(X_i = +1); denominator A0)."""
        out = [0] * self.n
        for x, a in zip(self.A_rows, self.A_w):
            i = 0; xx = x
            while xx:
                if xx & 1:
                    out[i] += a
                xx >>= 1; i += 1
        return out

    def antipodal(self):
        """VERIFIED from rows and weights: pi(x) = pi(-x) exactly, i.e. for every (x, a) in A the antipode (full ^ x) is in A with
        the same weight. Returns (bool, reason)."""
        d = dict(zip(self.A_rows, self.A_w))
        for x, a in d.items():
            if d.get(self.full ^ x) != a:
                return False, "row %d: antipode %s" % (x, "absent" if (self.full ^ x) not in d else "has a different weight")
        return True, "every row's antipode is present with the same weight (%d rows)" % len(d)

    def overlap_int(self):
        """P_0 numerator: Σ_{x in A∩B} a(x) b(x) (denominator A0 B0); and the intersection size."""
        bd = dict(zip(self.B_rows, self.B_w)); s = 0; k = 0
        for x, a in zip(self.A_rows, self.A_w):
            b = bd.get(x)
            if b is not None:
                s += a * b; k += 1
        return s, k


# ------------------------------------------------------------------ exact kernel integers and tails
def uv(r):
    r = Fr(r)
    if not (0 <= r <= 1):
        raise InputError("r must lie in [0, 1]")
    return r.numerator, r.denominator


def kappa_int(n, u, v, d):
    """K_r(x,y) * v^n at Hamming distance d: (v+u)^(n-d) (v-u)^d (evaluated directly; no 0/0 at r = 1)."""
    return (v + u) ** (n - d) * (v - u) ** d


def tau(n, k, r):
    """Generic tail Σ_{d=k+1}^n C(n,d) r^d (exact rational)."""
    r = Fr(r)
    return sum((comb(n, d) * r ** d for d in range(k + 1, n + 1)), Fr(0))


def eta_parity(n, k, r):
    """Parity-refined tails under VERIFIED antipodal symmetry of A: (eta_Z = even degrees > k, eta_M = odd degrees > k)."""
    r = Fr(r)
    ez = sum((comb(n, d) * r ** d for d in range(k + 1, n + 1) if d % 2 == 0), Fr(0))
    em = sum((comb(n, d) * r ** d for d in range(k + 1, n + 1) if d % 2 == 1), Fr(0))
    return ez, em


def lower_bound_Z(n, r, symmetric):
    """Z_r >= (1-r)^n always; >= (1-r^2)^(n/2) under verified antipodal symmetry (rational when n is even)."""
    r = Fr(r)
    if symmetric and n % 2 == 0:
        return (1 - r * r) ** (n // 2), "(1-r^2)^(n/2) (verified antipodal symmetry)"
    return (1 - r) ** n, "(1-r)^n (generic)"


def N_k(n, k):
    return sum(comb(n, d) for d in range(0, k + 1))


# ------------------------------------------------------------------ publication
def publish(lo, hi):
    """Exact rational [lo, hi] -> outward-rounded grid integers (lo_g, hi_g) with endpoints lo_g/2^P, hi_g/2^P clipped to [0, 1]."""
    lo, hi = Fr(lo), Fr(hi)
    assert lo <= hi
    q = 1 << GRID_BITS
    lo_g = (lo * q).numerator // (lo * q).denominator                 # floor
    hi_g = -((-hi * q).numerator // (-hi * q).denominator)           # ceil
    return max(0, lo_g), min(q, hi_g)


def width_of(lo_g, hi_g):
    return Fr(hi_g - lo_g, 1 << GRID_BITS)


# ------------------------------------------------------------------ scouts (input metadata, r, eps, overlap, verified symmetry only)
def sparse_scout(n, r, h, Pint0, A0B0, eps_star):
    """Prospective bound rho_h <= U_bar/(R_bar + U_bar) with R_bar = P_0 kappa_0, U_bar = (1-P_0) kappa_{h+1}; needs P_0 > 0, h < n."""
    u, v = uv(r)
    if Pint0 <= 0:
        return {"qualified": False, "reason": "P_0 = 0 (no overlap): no prospective sparse bound", "rho_bar": None}
    if h >= n:
        return {"qualified": False, "reason": "h >= n", "rho_bar": None}
    Rbar = Pint0 * kappa_int(n, u, v, 0); Ubar = (A0B0 - Pint0) * kappa_int(n, u, v, h + 1)
    rho = Fr(Ubar, Rbar + Ubar)
    return {"qualified": bool(rho <= eps_star), "rho_bar": str(rho), "rho_bar_float": float(rho), "reason": "rho_bar <= eps_star" if rho <= eps_star else "rho_bar > eps_star"}


def spectral_scout(n, r, k, symmetric, eps_star):
    """Sufficient condition: L > eta_Z and (eta_Z + eta_M)/(L - eta_Z) <= eps_star (L and the tails per symmetry)."""
    r = Fr(r)
    if k >= n:
        return {"qualified": True, "reason": "k >= n: exact", "width_bound": "0"}
    L, Lhow = lower_bound_Z(n, r, symmetric)
    if symmetric and n % 2 == 0:
        ez, em = eta_parity(n, k, r); how = "parity-refined tails"
    else:
        ez = em = tau(n, k, r); how = "generic tail (both)"
    if L <= ez:
        return {"qualified": False, "reason": "L <= eta_Z", "L": str(L), "L_how": Lhow, "eta_Z": str(ez), "eta_M": str(em), "tails": how, "width_bound": None}
    wb = (ez + em) / (L - ez)
    return {"qualified": bool(wb <= eps_star), "reason": "width bound <= eps_star" if wb <= eps_star else "width bound > eps_star", "L": str(L), "L_how": Lhow,
            "eta_Z": str(ez), "eta_M": str(em), "tails": how, "width_bound": str(wb), "width_bound_float": float(wb)}


# ------------------------------------------------------------------ cost proxies (frozen; operation estimates, not runtime predictors)
def W_admitted(n, mA):
    ops = (n + 2) * n * (1 << n) + n * mA
    mem = 5 * 8 * (1 << n)
    ok = n <= 24 and ops <= 1.1e10 and mem <= 2 * (1 << 30)
    return ok, {"ops_estimate": ops, "memory_estimate_bytes": mem, "rule": "n <= 24 and (n+2) n 2^n + n m_A <= 1.1e10 and 5 int64 arrays of 2^n <= 2 GiB"}


def cost_proxy(route, n, mA, mB, symmetric_used):
    """One-pass structural estimates (Part B); doubled for the independent reconstruction pass (S, F, E); W = C(W) + one-pass C(E)
    because W's frozen checker is pair reconstruction. W's own formula is CORRECTED to the degree-filtered implementation:
    (n+2) n 2^n + n m_A (recorded before any timed outcome)."""
    mmin = min(mA, mB)
    if route[0] == "S":
        h = int(route[1]); one = mmin * N_k(n, h) + n * mA; return 2 * one, one
    if route[0] == "F":
        k = int(route[1]); one = (mA + mB) * N_k(n, k) + n * mA; return 2 * one, one
    if route == "E":
        one = ((mA // 2) if symmetric_used else mA) * mB + n * mA; return 2 * one, one
    if route == "W":
        oneW = (n + 2) * n * (1 << n) + n * mA; oneE = mA * mB + n * mA; return oneW + oneE, oneW
    raise ValueError(route)


def select(law, r, eps, symmetric, Pint0, log=None):
    """The frozen online selector. Returns (route, params, decision record). Uses only input metadata, r, eps, the overlap mass and
    the VERIFIED symmetry. Endpoints take precedence."""
    r = Fr(r); eps = Fr(eps); n = law.n
    rec = {"eps": str(eps), "eps_star": str(eps - EPS_GRID_SLACK), "r": str(r), "symmetric": bool(symmetric), "P0": str(Fr(Pint0, law.A0 * law.B0)), "scouts": {}, "proxies": {}}
    if r == 0:
        rec["route"] = "PI"; rec["reason"] = "endpoint r = 0: the law is pi; return its marginals directly"; return "PI", {}, rec
    if r == 1:
        if Pint0 <= 0:
            rec["route"] = "REJECT"; rec["reason"] = "endpoint r = 1 with empty A∩B: the law is undefined"; return "REJECT", {}, rec
        rec["route"] = "S0"; rec["reason"] = "endpoint r = 1: exact sparse intersection"; return "S0", {"h": 0}, rec
    eps_star = eps - EPS_GRID_SLACK
    cands = []
    for h in (0, 1):
        sc = sparse_scout(n, r, h, Pint0, law.A0 * law.B0, eps_star); rec["scouts"]["S%d" % h] = sc
        if sc["qualified"]:
            cands.append("S%d" % h)
    for k in range(0, 4):
        if k > n:
            continue
        sc = spectral_scout(n, r, k, symmetric, eps_star); rec["scouts"]["F%d" % k] = sc
        if sc["qualified"]:
            cands.append("F%d" % k)
    cands.append("E")
    wa, winfo = W_admitted(n, law.mA); rec["W_admission"] = {"admitted": wa, **winfo}
    if wa:
        cands.append("W")
    for c in cands:
        rec["proxies"][c] = cost_proxy(c, n, law.mA, law.mB, symmetric)[0]
    best = min(cands, key=lambda c: (rec["proxies"][c], ROUTE_ORDER.index(c)))
    rec["qualified"] = cands; rec["route"] = best; rec["reason"] = "smallest doubled proxy among qualified / admitted routes; ties by S0,S1,F0,F1,F2,F3,E,W"
    params = {"h": int(best[1])} if best[0] == "S" else ({"k": int(best[1])} if best[0] == "F" else {})
    return best, params, rec
