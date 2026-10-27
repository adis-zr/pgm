"""Exact model definitions: the frozen MAIN generator (third independent regeneration, in Python), the four fixed fixtures, the NFCHAIN-V1
canonical text, and exact geometry verification of the MAIN generator facts listed in CLAUDE_CODE_SPEC.md §2."""
from __future__ import annotations
import sys
sys.set_int_max_str_digits(0)
import hashlib
from fractions import Fraction as Fr
from dataclasses import dataclass, field

@dataclass
class Model:
    case_id: str; n: int; r: int; query: int
    h: list; A: list            # h[i] Fr; A[l][i] Fr
    f: list                     # f[i] Fr, i = 0..n-2 (equal-spin factor)
    pin: list = None            # pin[i] in {0,+1,-1}
    def __post_init__(self):
        if self.pin is None: self.pin = [0] * self.n
        assert 0 <= self.query < self.n and self.pin[self.query] == 0, "query must be a free site"
    def canonical_lines(self):
        yield f"NFCHAIN-V1 {self.case_id} {self.n} {self.r} {self.query}"
        for i in range(self.n):
            yield f"{i} {self.h[i]} " + " ".join(str(self.A[l][i]) for l in range(self.r)) + f" {self.pin[i]}"
        for i in range(self.n - 1):
            yield f"e {i} {self.f[i]}"
    def canonical_bytes(self): return ("\n".join(self.canonical_lines()) + "\n").encode()
    def sha256(self): return hashlib.sha256(self.canonical_bytes()).hexdigest()
    def write(self, path):
        b = self.canonical_bytes(); open(path, "wb").write(b); return hashlib.sha256(b).hexdigest(), len(b)
    def s_E(self):
        return [sum((Fr(self.pin[i]) * self.A[l][i] for i in range(self.n) if self.pin[i]), Fr(0)) for l in range(self.r)]

def alternating_edges(n): return [Fr(9) if i % 2 == 0 else Fr(11, 9) for i in range(n - 1)]

def main_walsh5(n=262144, query=131072):
    """NF_WALSH5_MAIN_V1 exactly as in CLAUDE_CODE_SPEC.md §2 (zero-based; bit(d, 17-ell) of d = floor(i/2))."""
    assert n == 262144 and query == n // 2
    h = [Fr(1, 4) + Fr(i + 1, 1000 * (n + 1)) for i in range(n)]
    A = [[Fr(1, 1024)] * n] + [[Fr(-1, 1024) if ((i // 2) >> (17 - l)) & 1 else Fr(1, 1024) for i in range(n)] for l in (1, 2, 3, 4)]
    return Model("NF_WALSH5_MAIN_V1", n, 5, query, h, A, alternating_edges(n))

def fixture_signed(evidence=False):
    n = 12
    A = [[Fr(1, 16)] * n, [Fr((-1) ** i, 16) for i in range(n)], [Fr((-1) ** (i // 2), 32) for i in range(n)]]
    h = [Fr(2 * i - 11, 50) for i in range(n)]
    pin = [0] * n
    if evidence: pin[0], pin[7], pin[11] = 1, -1, 1
    return Model("FIX_SIGNED_EVIDENCE" if evidence else "FIX_SIGNED", n, 3, 5, h, A, alternating_edges(n), pin)

def fixture_zero_loading():
    n = 6; return Model("FIX_ZERO_LOADING", n, 3, 3, [Fr(2 * i - 5, 50) for i in range(n)], [[Fr(0)] * n for _ in range(3)], alternating_edges(n))

def fixture_unbalanced():
    tau = Fr(1, 10000); return Model("FIX_UNBALANCED", 2, 1, 0, [Fr(0), Fr(1)], [[Fr(1, 100), Fr(100)]], [(1 + tau) / (1 - tau)])

FIXTURE_CENTERS = {"FIX_SIGNED": [Fr(3, 8), Fr(-1, 4), Fr(1, 8)], "FIX_SIGNED_EVIDENCE": [Fr(3, 8), Fr(-1, 4), Fr(1, 8)],
                   "FIX_ZERO_LOADING": [Fr(0)] * 3, "FIX_UNBALANCED": [Fr(1, 200)]}

def verify_main_geometry(M: Model):
    """Exact verification of the §2 facts from the generated entries (counts as work; charged)."""
    n, r = M.n, M.r; S = [[0] * r for _ in range(r)]
    sgn = [[1 if M.A[l][i] > 0 else -1 for i in range(n)] for l in range(r)]
    for i in range(n):
        for l in range(r):
            if abs(M.A[l][i]) != Fr(1, 1024): raise ValueError("entry magnitude")
            for m in range(l, r): S[l][m] += sgn[l][i] * sgn[m][i]
    gram = [[Fr(S[min(l, m)][max(l, m)], 1024 * 1024) for m in range(r)] for l in range(r)]
    ok_gram = all(gram[l][m] == (Fr(1, 4) if l == m else 0) for l in range(r) for m in range(r))
    alpha2 = {sum(M.A[l][i] ** 2 for l in range(r)) for i in range(n)}
    ok_alpha = alpha2 == {Fr(5, 1048576)}
    taus = {(Fr(abs(M.f[i] - 1)) / (M.f[i] + 1), i % 2) for i in range(n - 1)}
    ok_tau = taus == {(Fr(4, 5), 0), (Fr(1, 10), 1)}
    t1, t2 = Fr(4, 5), Fr(1, 10); K = (1 + t1) * (1 + t2) / (1 - t1 * t2); ok_K = K == Fr(99, 46)
    V = K * sum(gram[l][l] for l in range(r)); ok_V = V == Fr(495, 184)
    row_sum = 2 * t2; ok_row = row_sum <= Fr(1, 5)
    # block diameter: strong pairs (2d, 2d+1) have identical columns, so D = 2 max(||a_i + a_j||, ||a_i - a_j||) = 2*||2a|| = 4 alpha
    ok_pairs = all(all(M.A[l][2 * d] == M.A[l][2 * d + 1] for l in range(r)) for d in range(n // 2))
    types = len({tuple(sgn[l][i] for l in range(r)) for i in range(n)}); segments = 1 + sum(1 for i in range(1, n) if any(sgn[l][i] != sgn[l][i - 1] for l in range(r)))
    ok_h = all(M.h[i] == Fr(1, 4) + Fr(i + 1, 1000 * (n + 1)) for i in range(n)) and all(abs(M.h[i]) <= Fr(1, 3) for i in range(n))
    return {"AAt_quarter_identity": ok_gram, "alpha2_5_over_2^20": ok_alpha, "tau_strong_4/5_weak_1/10": ok_tau, "K_99/46": ok_K, "V_495/184": ok_V,
            "block_row_sum_le_1/5": ok_row, "block_diameter_le_4alpha_pair_columns_equal": ok_pairs, "loading_types": types, "contiguous_segments": segments,
            "fields_formula_and_|h|<=1/3": ok_h, "all_ok": all([ok_gram, ok_alpha, ok_tau, ok_K, ok_V, ok_row, ok_pairs, ok_h, types == 16, segments == 16]),
            "exact": {"K": str(K), "V": str(V), "alpha2": "5/1048576", "row_sum": str(row_sum)}}
