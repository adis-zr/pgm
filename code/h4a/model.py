"""Exact H4 model construction and binding (reference/H4_DEFINITION.md section 1; TABLES_AND_DOMAIN.md).
Everything is exact Fraction/int; no float enters the model, pins, grid or node fields."""
from __future__ import annotations
import sys
sys.set_int_max_str_digits(0)
import hashlib, json
from fractions import Fraction as Fr

def H(seed: int, tag: str, *args: int) -> int:
    s = "|".join(["strong-compact-v1", str(seed), tag] + [str(a) for a in args])
    return int.from_bytes(hashlib.sha256(s.encode("ascii")).digest(), "big")

def loading(seed: int, i: int, ell: int, b: int = 20) -> Fr:
    t = H(seed, "load", i, ell) % (1 << 18)
    m = (1 << (b - 1)) + 1 + 2 * (t // (1 << (20 - b)))
    sign = 1 if ell == 0 else (1 if H(seed, "load-sign", i, ell) % 2 == 0 else -1)
    return Fr(sign * m, 1 << b)

def field_int(seed: int, i: int) -> int:
    return H(seed, "field", i) % 17 - 4

def sigma_of(seed: int, i: int) -> int:
    return 1 if H(seed, "edge", i) % 2 == 0 else -1

class Model:
    """H4 variant: global columns 0..3, beta = (3,2,-2,-2), 20-bit loadings, width-2 residual."""
    BETA = (Fr(3), Fr(2), Fr(-2), Fr(-2))
    COLUMNS = (0, 1, 2, 3)
    def __init__(self, n: int, seed: int, b: int = 20):
        assert n >= 4 and n % 2 == 0
        self.n, self.seed, self.b = n, seed, b
        self.u = [[loading(seed, i, ell, b) for ell in self.COLUMNS] for i in range(n)]
        self.a = [field_int(seed, i) for i in range(n)]
        self.h = [Fr(self.a[i], 16 * n) for i in range(n)]
        self.sigma = [sigma_of(seed, i) for i in range(n - 2 + 1)][: n - 1]
        self.factors = []                                     # (i, j, table) with table over (--),(-+),(+-),(++)
        for i in range(n - 1):                                # adjacent: 9 when x_i x_{i+1} == sigma_i
            tbl = [Fr(9) if (si * sj == self.sigma[i]) else Fr(1) for si in (-1, 1) for sj in (-1, 1)]
            self.factors.append((i, i + 1, tbl))
        for i in range(n - 2):                                # distance two: 3 when x_i x_{i+2} == -sigma_i sigma_{i+1}
            want = -self.sigma[i] * self.sigma[i + 1]
            tbl = [Fr(3) if (si * sj == want) else Fr(1) for si in (-1, 1) for sj in (-1, 1)]
            self.factors.append((i, i + 2, tbl))
        self.adj = {(i, j): t for i, j, t in self.factors}
    # --- bindings
    def canonical_obj(self):
        return {"Lambda": "9", "a": self.a, "b": self.b, "bags": [[i, i + 1, i + 2] for i in range(self.n - 2)],
                "beta": [str(x) for x in self.BETA], "columns": list(self.COLUMNS),
                "factors": [{"scope": [i, j], "table": [str(x) for x in t]} for i, j, t in self.factors],
                "family": "strong-compact-v1", "fields": [str(x) for x in self.h], "generator": "strong-compact-v1",
                "loadings": [[str(x) for x in row] for row in self.u], "model_id": f"H4-n{self.n}-s{self.seed}",
                "n": self.n, "residual": "width2", "seed": self.seed, "sigma": self.sigma, "variant": "H4"}
    def canonical_sha256(self):
        return hashlib.sha256(json.dumps(self.canonical_obj(), sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    def factor_pairs_at(self, i):
        """residual factors whose LARGER endpoint is i: (i-1,i) adjacent and (i-2,i) distance-two"""
        out = []
        if i >= 1: out.append((i - 1, i, self.adj[(i - 1, i)]))
        if i >= 2: out.append((i - 2, i, self.adj[(i - 2, i)]))
        return out
    def psi(self, i, j, xi, xj) -> Fr:
        t = self.adj.get((i, j))
        if t is None: return Fr(1)
        return t[(0 if xi < 0 else 2) + (0 if xj < 0 else 1)]

def ehalf_pins(m: Model):
    """Ehalf: sites other than 0 and n/2 sorted by (H(seed,'pin-order',i), i); pin the first (n-2)/2."""
    n = m.n; cand = [i for i in range(n) if i not in (0, n // 2)]
    cand.sort(key=lambda i: (H(m.seed, "pin-order", i), i))
    sel = cand[: (n - 2) // 2]
    return {i: (1 if H(m.seed, "pin-value", i) % 2 == 0 else -1) for i in sel}

class NodeProblem:
    """One (source sign, positive node) H4 positive-node law: exact pins, exact per-site fields, exact phase angles.

    Positive columns are local 0,1 (global 0,1; beta 3,2); negative columns are local 0,1 (global 2,3; beta -2,-2).
    Free-site field  a_i = h_i + sum_{pos c} beta_c t_E,c u_ic / n + sum_{pos c} sqrt(beta_c/n) j_c u_ic
    Pinned site      field = h_i only (the extra free-site fields are absent).   [IMPLEMENTATION_CONTRACT.md §1]
    Negative phase   theta_i(k,x) = x * sqrt(2/n) * (h2 k2 u_i2 + h3 k3 u_i3)    [NUMERICAL_THEOREM.md scope]
    """
    POS_LOCAL = ((0, Fr(3)), (1, Fr(2)))        # (global column, beta)
    NEG_LOCAL = ((2, Fr(2)), (3, Fr(2)))        # |beta| = 2 for both negative modes (a=2 in the grid records)
    def __init__(self, model: Model, source_site: int, source_sign: int, target_site: int, node, context="E0", extra_pins=None):
        self.m = model; self.q = target_site; self.node = tuple(int(j) for j in node); self.context = context
        self.pins = {source_site: int(source_sign)}
        if context == "Ehalf": self.pins.update(ehalf_pins(model))
        if extra_pins: self.pins.update({int(k): int(v) for k, v in extra_pins.items()})
        assert self.q not in self.pins, "target must be free"
        n = model.n
        self.allowed = [((self.pins[i],) if i in self.pins else (-1, 1)) for i in range(n)]
        self.free = [i for i in range(n) if i not in self.pins]
        # exact evidence statistic per positive column and the free-site extra field
        self.tE = {}
        for c, beta in self.POS_LOCAL:
            self.tE[c] = sum((Fr(self.pins[i]) * model.u[i][c] for i in self.pins), Fr(0))
        self.field = []
        for i in range(n):
            f = model.h[i]
            if i not in self.pins:
                for c, beta in self.POS_LOCAL: f += beta * self.tE[c] * model.u[i][c] / n
            self.field.append(f)
        # the sqrt(beta/n) j_c u_ic part is irrational: keep its exact rational coefficient per site
        self.node_coef = []                       # list over sites of [(beta_c, j_c, u_ic)] for free sites only
        for i in range(n):
            if i in self.pins: self.node_coef.append([]); continue
            self.node_coef.append([(beta, self.node[idx], model.u[i][c]) for idx, (c, beta) in enumerate(self.POS_LOCAL)])
    def phase_rational(self, k2: int, k3: int, i: int):
        """exact rational r with theta_i(k,x) = x * sqrt(2/n) * r  (r = h2 k2 u_i2 + h3 k3 u_i3)"""
        raise NotImplementedError      # supplied by the grid module (needs exact h values)
