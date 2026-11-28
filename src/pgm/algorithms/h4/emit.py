"""Certified cache + per-node table construction and witness emission for all three arms.

Source-independent cache (per cold bundle, reused across both source signs, identical policy in C/PI/PP):
  site phases phi_i(k,x) for every site i, both spins x, all 265 representatives;
  combined boundary-pair phases for the producer's terminal pair (n-2,n-1) and the checker's initial pair (0,1),
  each certified DIRECTLY from the summed exact angle;  Fourier weights lambda_k.
Its identity binds n, loadings, exact grid spacings/order/multiplicities, angle convention, precision and policy.
Sign-specific rows/unaries/masks are rebuilt per node."""
from __future__ import annotations
import sys
sys.set_int_max_str_digits(0)
import hashlib, json
from fractions import Fraction as Fr
from pgm.algorithms.h4.tables import MP, fr, store_phase, store_row, exact_phase_one, MESH, EPS_PHI, EPS_LAM, EPS_P
from pgm.algorithms.h4.grid import PI_LO, PI_HI
import struct

def _d(x: Fr):  return x
def dyadic_str(x: Fr) -> str:
    """exact 'm*2^e' for a dyadic rational"""
    n, d = x.numerator, x.denominator
    assert d & (d - 1) == 0, "not dyadic"
    e = -(d.bit_length() - 1)
    return f"{n}*2^{e}"

DY = 1 << 320
def out_dy(x: Fr, up: bool = False) -> str:
    """outward dyadic representative of an exact rational on the 2^-320 grid: floor for a lower endpoint, ceil for an
    upper endpoint, so the emitted interval always contains the true enclosure"""
    y = x * DY
    n = (-((-y.numerator) // y.denominator)) if up else (y.numerator // y.denominator)
    return f"{n}*2^-320"

def f64_bits(x: Fr) -> str:
    """nearest binary64 of an exact rational, as 16 hex digits (ties to even via Python float round-trip of the fraction)"""
    v = float(x)
    assert v == v and abs(v) != float("inf")
    if v == 0.0: v = 0.0            # canonicalise -0 to +0
    return struct.pack(">d", v).hex()

def f64_value(bits_hex: str) -> Fr:
    v = struct.unpack(">d", bytes.fromhex(bits_hex))[0]
    return Fr(v)

class Cache:
    """source-independent certified phase/weight cache"""
    def __init__(self, model, grid, prec: int, n_override=None):
        self.model = model; self.grid = grid; self.prec = prec
        M = MP(prec); self.M = M; n = model.n
        s2n = M.sqrt(M.q(Fr(2, n)))                           # sqrt(2/n), enclosed
        self.site = {}; self.site_iv = {}; self.site_err = Fr(0); self.worst_phase_err = Fr(0)
        h2, h3 = grid.h[0], grid.h[1]
        for ki, (k2, k3, mult) in enumerate(grid.reps):
            for i in range(n):
                r_pos = h2 * k2 * model.u[i][2] + h3 * k3 * model.u[i][3]     # exact rational
                for x in (-1, 1):
                    if k2 == 0 and k3 == 0:
                        p, err = exact_phase_one(); civ = (Fr(1), Fr(1)); siv = (Fr(0), Fr(0))
                    else:
                        ang = M.mul(s2n, M.q(Fr(x) * r_pos))
                        c, s = M.cos_sin(ang)
                        civ = (fr(c[0]), fr(c[1])); siv = (fr(s[0]), fr(s[1]))
                        p, err = store_phase(civ, siv)
                    self.site[(ki, i, x)] = p; self.site_iv[(ki, i, x)] = (civ, siv)
                    if err > self.worst_phase_err: self.worst_phase_err = err
        # combined boundary-pair phases, certified from the SUMMED angle (never a product of stored phases)
        self.pair = {}; self.pair_iv = {}
        for which, (ia, ib) in (("term", (n - 2, n - 1)), ("init", (0, 1))):
            for ki, (k2, k3, mult) in enumerate(grid.reps):
                ra = h2 * k2 * model.u[ia][2] + h3 * k3 * model.u[ia][3]
                rb = h2 * k2 * model.u[ib][2] + h3 * k3 * model.u[ib][3]
                for xa in (-1, 1):
                    for xb in (-1, 1):
                        if k2 == 0 and k3 == 0:
                            p, err = exact_phase_one(); civ = (Fr(1), Fr(1)); siv = (Fr(0), Fr(0))
                        else:
                            ang = M.mul(s2n, M.q(Fr(xa) * ra + Fr(xb) * rb))
                            c, s = M.cos_sin(ang)
                            civ = (fr(c[0]), fr(c[1])); siv = (fr(s[0]), fr(s[1]))
                            p, err = store_phase(civ, siv)
                        self.pair[(which, ki, xa, xb)] = p; self.pair_iv[(which, ki, xa, xb)] = (civ, siv)
                        if err > self.worst_phase_err: self.worst_phase_err = err
        # Fourier weights: nearest binary64; exact enclosure for the error predicate
        self.lam_bits = []; self.lam_iv = []
        tot_lo = Fr(0); tot_hi = Fr(0); self.lam_l1 = Fr(0)
        for (k2, k3, mult) in grid.reps:
            e = -((h2 * k2) ** 2 + (h3 * k3) ** 2) / 2
            pref_lo = h2 * h3 * mult / (2 * PI_HI); pref_hi = h2 * h3 * mult / (2 * PI_LO)
            ex = M.exp(M.q(e)); lo = pref_lo * fr(ex[0]); hi = pref_hi * fr(ex[1])
            b = f64_bits((lo + hi) / 2); v = f64_value(b)
            assert v >= 0
            self.lam_bits.append(b); self.lam_iv.append((lo, hi))
            tot_lo += lo; tot_hi += hi; self.lam_l1 += max(abs(v - lo), abs(v - hi))
        self.lam_true_total = (tot_lo, tot_hi)
        self.lam_stored_total = sum((f64_value(b) for b in self.lam_bits), Fr(0))
        self.checks = {
            "phase_unit_disk_and_L1_le_2^-48": self.worst_phase_err <= EPS_PHI,
            "worst_phase_L1_error": str(self.worst_phase_err),
            "weights_nonnegative": all(f64_value(b) >= 0 for b in self.lam_bits),
            "true_weight_total_le_2": tot_hi <= 2,
            "stored_weight_total_le_2": self.lam_stored_total <= 2,
            "weight_total_L1_le_2^-48": self.lam_l1 <= EPS_LAM,
            "weight_total_L1": str(self.lam_l1),
            "representatives": len(grid.reps),
            "zero_frequency_phase_exact": self.site[(0, 0, 1)] == (MESH, 0),
        }
        self.identity = hashlib.sha256(json.dumps({
            "n": n, "prec": prec, "loadings": [[str(x) for x in row] for row in model.u],
            "h": [str(x) for x in grid.h], "J": grid.J, "reps": grid.reps,
            "angle_convention": "theta_i(k,x) = x*sqrt(2/n)*(h2 k2 u_i2 + h3 k3 u_i3)",
            "boundary_pairs": ["term:(n-2,n-1)", "init:(0,1)"],
            "construction_policy": "directed MPFR; certified midpoint; shrink 1-2^-50; mesh 2^-53 ties-to-even; zero freq exact (1,0)",
            "kernel_version": "h4a-emit-v1"}, sort_keys=True, separators=(",", ":")).encode()).hexdigest()

def write_point_witness(path, prob, grid, cache: Cache, tabs, kind="producer"):
    """kind='producer' -> H4POINT-V1 (backward rows + terminal row/phases); 'checker' -> H4PCHECK-V1 (forward rows + initial)"""
    n = prob.m.n; reps = grid.reps
    lines = []
    tag = "H4POINT-V1" if kind == "producer" else "H4PCHECK-V1"
    lines.append(f"{tag} {n} {prob.q} {len(reps)} {tabs['prec']} 2")
    for i in range(n):
        al = prob.allowed[i]; lines.append("ALLOWED %d %d %s" % (i, len(al), " ".join(str(s) for s in al)))
    if kind == "producer":
        for i, per_ctx in enumerate(tabs["rows"]):
            na = prob.allowed[i + 1]; nb = prob.allowed[i + 2]
            for ia, a in enumerate(na):
                for ib, b in enumerate(nb):
                    rec = per_ctx.get((a, b))
                    if rec is None: continue
                    ints, l1 = rec[0], rec[1]; lines.append(f"ROW {i} {ia} {ib} {ints[0]} {ints[1]}")
        ti, tl1 = tabs["terminal"][0], tabs["terminal"][1]; lines.append("TERM %d %d %d %d" % tuple(ti))
    else:
        for i in range(2, n):
            per_ctx = tabs["rows"].get(i, {})
            na = prob.allowed[i - 2]; nb = prob.allowed[i - 1]
            for ia, a in enumerate(na):
                for ib, b in enumerate(nb):
                    rec = per_ctx.get((a, b))
                    if rec is None: continue
                    ints, l1 = rec[0], rec[1]; lines.append(f"ROW {i} {ia} {ib} {ints[0]} {ints[1]}")
        ii, il1 = tabs["initial"][0], tabs["initial"][1]; lines.append("TERM %d %d %d %d" % tuple(ii))   # ABSOLUTE 4-slot order (--),(-+),(+-),(++)
    for ki in range(len(reps)):
        for i in range(n):
            for xi, x in enumerate((-1, 1)):
                if x not in prob.allowed[i]: 
                    pass
                p = cache.site[(ki, i, x)]
                lines.append(f"PH {ki} {i} {xi} {p[0]} {p[1]}")
    which = "term" if kind == "producer" else "init"
    for ki in range(len(reps)):
        for ja, xa in enumerate((-1, 1)):
            for jb, xb in enumerate((-1, 1)):
                p = cache.pair[(which, ki, xa, xb)]
                lines.append(f"PHT {ki} {ja} {jb} {p[0]} {p[1]}")
    for ki, b in enumerate(cache.lam_bits): lines.append(f"LAM {ki} {b}")
    open(path, "w").write("\n".join(lines) + "\n")
    return len("\n".join(lines)) + 1

def write_rect_witness(path, prob, grid, cache: Cache, tabs, prec, kind="producer"):
    """Interval arm (C's producer and the C/PI interval checker): emits the TRUE directed-MPFR enclosures produced by
    the table construction — row probability intervals, phase rectangles and Fourier-weight intervals — NOT the
    quantized point values the point kernels consume. Feeding C degenerate intervals around the quantized values would
    make it an enclosure of the rounded surrogate and would understate its cost (review finding 1).

    kind='producer' uses the backward factorization (rows i=0..n-3 + terminal pair); kind='checker' uses the
    INDEPENDENT opposite-direction construction (forward rows i=2..n-1 + initial pair), so the C/PI checker is a
    separate implementation rather than the producer at higher precision (review finding 1b)."""
    n = prob.m.n; reps = grid.reps; lines = [f"H4RECT-V1 {n} {prob.q} {len(reps)} {prec} 2"]
    for i in range(n):
        al = prob.allowed[i]; lines.append("ALLOWED %d %d %s" % (i, len(al), " ".join(str(s) for s in al)))
    if kind == "producer":
        for i, per_ctx in enumerate(tabs["rows"]):
            na = prob.allowed[i + 1]; nb = prob.allowed[i + 2]
            for ia, a in enumerate(na):
                for ib, b in enumerate(nb):
                    rec = per_ctx.get((a, b))
                    if rec is None: continue
                    enc = rec[2]
                    e0 = enc.get(0, (Fr(0), Fr(0))); e1 = enc.get(1, (Fr(0), Fr(0)))
                    lines.append(f"ROW {i} {ia} {ib} {out_dy(e0[0])} {out_dy(e0[1], up=True)} {out_dy(e1[0])} {out_dy(e1[1], up=True)}")
        bkey = "terminal"; which = "term"
    else:
        for i in range(2, n):
            per_ctx = tabs["rows"].get(i, {})
            na = prob.allowed[i - 2]; nb = prob.allowed[i - 1]
            for ia, a in enumerate(na):
                for ib, b in enumerate(nb):
                    rec = per_ctx.get((a, b))
                    if rec is None: continue
                    enc = rec[2]
                    e0 = enc.get(0, (Fr(0), Fr(0))); e1 = enc.get(1, (Fr(0), Fr(0)))
                    lines.append(f"ROW {i} {ia} {ib} {out_dy(e0[0])} {out_dy(e0[1], up=True)} {out_dy(e1[0])} {out_dy(e1[1], up=True)}")
        bkey = "initial"; which = "init"
    benc = tabs[bkey][2]
    parts = []
    for sl in range(4):
        iv = benc.get(sl, (Fr(0), Fr(0))); parts.append(f"{out_dy(iv[0])} {out_dy(iv[1], up=True)}")
    lines.append("TERM " + " ".join(parts))
    for ki in range(len(reps)):
        for i in range(n):
            for xi, x in enumerate((-1, 1)):
                cre, cim = cache.site_iv[(ki, i, x)]
                lines.append(f"PH {ki} {i} {xi} {out_dy(cre[0])} {out_dy(cre[1], up=True)} {out_dy(cim[0])} {out_dy(cim[1], up=True)}")
    for ki in range(len(reps)):
        for ja, xa in enumerate((-1, 1)):
            for jb, xb in enumerate((-1, 1)):
                cre, cim = cache.pair_iv[(which, ki, xa, xb)]
                lines.append(f"PHT {ki} {ja} {jb} {out_dy(cre[0])} {out_dy(cre[1], up=True)} {out_dy(cim[0])} {out_dy(cim[1], up=True)}")
    for ki, (lo, hi) in enumerate(cache.lam_iv):
        lines.append(f"LAM {ki} {out_dy(lo)} {out_dy(hi, up=True)}")
    open(path, "w").write("\n".join(lines) + "\n")
    return len("\n".join(lines)) + 1
