"""Exact model generator and canonical input bytes (CLAUDE_CODE_SPEC.md "Frozen models and query").

Sites i = 0..n-1, spins x_i in {-1,+1}; weight  exp(sum_i h_i x_i - (sum_i a_i x_i)^2/2) * prod_{i<n-1} psi_i(x_i, x_{i+1}),
psi_i = f_i on equal spins, 1 otherwise; f_i = 9 on even edges, f_odd on odd edges (MAIN 11/9, CONTROL 7/3).
  t_i = 1/2 + (i+1)/(2(n+1)),   a_i = (3/4) sqrt(2/n) t_i,   h_i = t_i/4 + (-1)^i/(1000 n).
sqrt(2/n) must be rational for the pilot sizes: n=32768 gives 1/128 (a_i = 3 t_i/512); n=8 gives 1/2 (a_i = 3 t_i/8).
Evidence: coordinate pins {site: +-1}; the ORIGINAL n stays in the normalisation and the pinned sites keep their loadings and fields
(the statistic AX includes the pinned contributions; this is exactly equivalent to the spec's h'_i = h_i - a_i s_E transformation,
with configuration-independent constants cancelling in the normalised query — see docs/.../witness_response.md section 9)."""
from __future__ import annotations

import sys
sys.set_int_max_str_digits(0)

import hashlib
from fractions import Fraction as Fr

CASES = {"MAIN": Fr(11, 9), "CONTROL": Fr(7, 3)}


def sqrt2_over_n(n: int) -> Fr:
    """Exact rational sqrt(2/n) or ValueError (the pilot sizes 8 and 32768 are exact)."""
    num = Fr(2, n)
    p, q = num.numerator, num.denominator
    rp, rq = int(round(p ** 0.5)), int(round(q ** 0.5))
    if rp * rp != p or rq * rq != q:
        raise ValueError(f"sqrt(2/{n}) is irrational; the pilot requires an exact rational loading scale")
    return Fr(rp, rq)


class Model:
    def __init__(self, n: int, case: str, evidence: dict | None = None, query: int = 0):
        if case not in CASES:
            raise ValueError(case)
        self.n, self.case, self.query = n, case, query
        self.evidence = {int(k): int(v) for k, v in (evidence or {}).items()}
        for i, v in self.evidence.items():
            if not (0 <= i < n) or v not in (-1, 1) or i == query:
                raise ValueError(f"bad pin {i}={v}")
        s = sqrt2_over_n(n)
        self.t = [Fr(1, 2) + Fr(i + 1, 2 * (n + 1)) for i in range(n)]
        self.a = [Fr(3, 4) * s * ti for ti in self.t]
        self.h = [ti / 4 + Fr((-1) ** i, 1000 * n) for i, ti in enumerate(self.t)]
        self.f = [Fr(9) if i % 2 == 0 else CASES[case] for i in range(n - 1)]      # equal-spin factor on edge i (sites i, i+1)

    def canonical_bytes(self) -> bytes:
        """Exact text: header, pins, per-site (h_i, a_i), per-edge equal-spin factor. Hash of these bytes identifies the input."""
        L = [f"DQCHAIN-V1 n={self.n} case={self.case} query={self.query} evidence={','.join(f'{i}:{v:+d}' for i, v in sorted(self.evidence.items())) or 'none'}",
             "weight: exp(sum h_i x_i - (sum a_i x_i)^2/2) * prod psi_i ; psi_i = f_i if x_i == x_{i+1} else 1 ; original n in the normalisation"]
        L += [f"site {i} h={self.h[i]} a={self.a[i]}" for i in range(self.n)]
        L += [f"edge {i} f={self.f[i]}" for i in range(self.n - 1)]
        return ("\n".join(L) + "\n").encode("ascii")

    def sha256(self) -> str:
        return hashlib.sha256(self.canonical_bytes()).hexdigest()

    def write(self, path: str) -> str:
        b = self.canonical_bytes()
        with open(path, "wb") as f:
            f.write(b)
        return hashlib.sha256(b).hexdigest()

    def allowed(self, i: int):
        return (self.evidence[i],) if i in self.evidence else (-1, 1)


def parse_canonical(path: str) -> Model:
    """Independent parser: rebuilds a Model from the canonical bytes and VERIFIES every line against the generating formulas
    (a trusted family label cannot bypass input checking)."""
    txt = open(path, "rb").read().decode("ascii")
    lines = txt.split("\n")
    hdr = lines[0].split()
    assert hdr[0] == "DQCHAIN-V1", "bad header token"
    kv = dict(x.split("=", 1) for x in hdr[1:])
    n, case, query = int(kv["n"]), kv["case"], int(kv["query"])
    ev = {} if kv["evidence"] == "none" else {int(p.split(":")[0]): int(p.split(":")[1]) for p in kv["evidence"].split(",")}
    m = Model(n, case, ev, query)
    if txt.encode("ascii") != m.canonical_bytes():
        # locate the first differing line for the record
        mine = m.canonical_bytes().decode("ascii").split("\n")
        for k, (x, y) in enumerate(zip(lines, mine)):
            if x != y:
                raise ValueError(f"canonical input line {k} does not match the generating formulas: {x!r} vs {y!r}")
        raise ValueError("canonical input differs from the generating formulas")
    return m
