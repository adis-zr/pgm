"""Conformance controls for the sparse / Fourier bridge (branch sf-bridge-2026-11-06): mathematical conformance against exhaustive
pair sums on small instances, not runtime cells. Covers: arbitrary supports with nonuniform positive integer weights; r = 0 and r = 1;
overlap / disjoint-support endpoint rejection; generic and antipodal inputs; all singleton identities (S_h, F_k incl. k = n exact, E, W)
against exhaustive pair sums; retained mass and omitted-bound inequalities; signed truncated row weights; Z_k <= 0 refusal; a valid
ratio certificate with 0 < Z_k <= eta_Z; outward rounding on the 2^-80 grid; duplicate rows; missing query coordinates; tampering with
weights, moments, symmetry, residual bounds and output intervals; an ASYMMETRIC case (sign and bit-order mistakes cannot hide)."""
import os, sys, json, random, itertools, tempfile
from pathlib import Path
HERE = str(Path(__file__).resolve().parents[2])
from fractions import Fraction as Fr
from math import comb
import pytest
import numpy as np
from pgm.algorithms.sf import core as C, routes as RT, check as CK

from research.campaigns.sf import generate as GEN

def brute(law, r):
    """Exhaustive pair sums: (Zint, Nint, exact P_i) at the common scale A0 B0 v^n, plus per-distance retained data."""
    n = law.n; u, v = C.uv(r)
    Z = 0; N = [0] * n; byd = {}
    for x, a in zip(law.A_rows, law.A_w):
        for y, b in zip(law.B_rows, law.B_w):
            d = bin(x ^ y).count("1"); w = a * b * C.kappa_int(n, u, v, d); Z += w
            byd.setdefault(d, [0, 0, [0] * n]); byd[d][0] += a * b; byd[d][1] += w
            for i in range(n):
                if (x >> i) & 1:
                    N[i] += w; byd[d][2][i] += w
    return Z, N, byd


def law_of(n, A, B):
    return C.Law(n, A, B)


def rnd_law(n, mA, mB, seed, weights=True):
    rng = random.Random(seed)
    A = {}; B = {}
    while len(A) < mA:
        A[rng.randrange(1 << n)] = rng.randint(1, 9) if weights else 1
    while len(B) < mB:
        B[rng.randrange(1 << n)] = rng.randint(1, 9) if weights else 1
    return law_of(n, list(A.items()), list(B.items()))


def antipodal_law(n, half, mB, seed):
    rng = random.Random(seed); full = (1 << n) - 1
    zs = []; seen = set()
    while len(zs) < half:
        z = rng.randrange(1 << n)
        if z in seen or (full ^ z) in seen:
            continue
        zs.append(z); seen.add(z)
    A = []
    for z in zs:
        w = rng.randint(1, 5); A += [(z, w), (full ^ z, w)]
    B = {}
    while len(B) < mB:
        B[rng.randrange(1 << n)] = rng.randint(1, 5)
    return law_of(n, A, list(B.items()))


RS = [Fr(0), Fr(1, 3), Fr(1, 2), Fr(7, 8), Fr(1) - Fr(1, 1024), Fr(1)]


def test_exact_routes_match_exhaustive_pairs_generic_and_antipodal_and_asymmetric():
    for law, name in ((rnd_law(6, 9, 7, 1), "generic"), (antipodal_law(6, 5, 8, 2), "antipodal"), (law_of(5, [(0b10110, 3), (0b00001, 1), (0b11000, 2)], [(0b10110, 1), (0b01111, 4), (0b00011, 2)]), "asymmetric")):
        sym, _ = law.antipodal()
        assert sym == (name == "antipodal")
        for r in RS:
            Z, N, _ = brute(law, r)
            if Z == 0:
                continue
            e = RT.route_E(law, r, sym); w = RT.route_W(law, r)
            assert e["status"] == "OK" and e["Z_int"] == Z and e["N_int"] == N, (name, r)
            assert w["status"] == "OK" and w["Z_int"] == Z and w["N_int"] == N, (name, r)
            fn = RT.route_F(law, r, law.n, sym)                                   # k = n is exact
            assert fn["status"] == "OK" and all(lo == hi == Fr(N[i], Z) for i, (lo, hi) in enumerate(fn["intervals"])), (name, r)
            for rec in (e, w, fn):
                rec["published"] = [C.publish(lo, hi) for lo, hi in rec["intervals"]]
                assert CK.check(law, r, rec, sym)["ok"]


def test_sparse_routes_retained_mass_omitted_bound_and_enclosure():
    law = rnd_law(6, 12, 10, 3)
    for r in (Fr(1, 2), Fr(7, 8), Fr(1) - Fr(1, 1024)):
        Z, N, byd = brute(law, r)
        for h in (0, 1):
            s = RT.route_S(law, r, h)
            if s["status"] != "OK":
                assert all(d > h for d in byd), "S%d rejected although retained pairs exist" % h; continue
            R_true = sum(byd[d][1] for d in byd if d <= h); D_true = Z - R_true
            assert s["R_int"] == R_true and s["P_int"] == sum(byd[d][0] for d in byd if d <= h)
            assert 0 <= D_true <= s["U_int"], "omitted-mass bound violated"
            for i in range(law.n):
                lo, hi = s["intervals"][i]; assert lo <= Fr(N[i], Z) <= hi
            s["published"] = [C.publish(lo, hi) for lo, hi in s["intervals"]]
            assert CK.check(law, r, s, False)["ok"]
    # h = n gives U = 0 and the exact answer
    full = RT.route_S(law_of(3, [(0, 1), (7, 2)], [(0, 3), (7, 1), (5, 2)]), Fr(1, 2), 0)
    assert full["status"] == "OK"


def test_fourier_truncation_enclosure_and_tails_generic_and_parity():
    for law, sym in ((rnd_law(6, 10, 9, 4), False), (antipodal_law(6, 4, 9, 5), True)):
        assert law.antipodal()[0] == sym
        for r in (Fr(1, 3), Fr(1, 8), Fr(1, 32)):
            Z, N, _ = brute(law, r)
            for k in range(0, 4):
                f = RT.route_F(law, r, k, sym)
                assert f["status"] == "OK"
                Zq = Fr(f["Zk_int"], f["scale_int"]); Zr = Fr(Z, law.A0 * law.B0 * r.denominator ** law.n)
                ez, em = (C.eta_parity(law.n, k, r) if sym else (C.tau(law.n, k, r), C.tau(law.n, k, r)))
                assert abs(Zr - Zq) <= ez
                for i in range(law.n):
                    Mq = Fr(f["Mk_int"][i], f["scale_int"]); Mi = Fr(2 * N[i] - Z, law.A0 * law.B0 * r.denominator ** law.n)
                    assert abs(Mi - Mq) <= em
                    lo, hi = f["intervals"][i]; assert lo <= Fr(N[i], Z) <= hi, (sym, r, k, i)
                f["published"] = [C.publish(lo, hi) for lo, hi in f["intervals"]]
                assert CK.check(law, r, f, sym)["ok"]
        if sym:
            # odd alpha moments vanish under verified symmetry
            for S in range(1, 1 << law.n):
                if bin(S).count("1") % 2 == 1:
                    assert sum(a * (1 - 2 * (bin(x & S).count("1") % 2)) for x, a in zip(law.A_rows, law.A_w)) == 0


def test_signed_truncated_rows_Zk_refusal_and_small_positive_Zk_certificate():
    # a law where the degree-1 truncation makes g_1(x) negative for some row and Z_1 <= 0: refusal, not an error
    law = law_of(2, [(0b00, 1)], [(0b11, 1)])           # x = (-1,-1), y = (+1,+1): beta_1 = beta_2 = +1; g_1(x) = 1 - r - r
    f = RT.route_F(law, Fr(3, 4), 1, False)
    assert f["status"] == "REFUSE" and f["Zk_int"] <= 0
    # Z_k > 0 but Z_k <= eta_Z: still a valid (wide) certificate, published
    f2 = RT.route_F(law, Fr(9, 20), 1, False)             # g_1 = 1 - 9/10 = 1/10 > 0 ; tau_{2,1}(9/20) = 81/400 >= 1/10 : 0 < Z_1 <= eta_Z
    assert f2["status"] == "OK" and 0 < Fr(f2["Zk_int"], f2["scale_int"]) <= f2["eta_Z"]
    Z, N, _ = brute(law, Fr(9, 20))
    for i in range(2):
        lo, hi = f2["intervals"][i]; assert lo <= Fr(N[i], Z) <= hi
    assert any(hi - lo > Fr(1, 100) for lo, hi in f2["intervals"])          # wide: fails the width contract, still valid


def test_endpoints_overlap_disjoint_rejection_and_pi():
    law = law_of(4, [(0b0001, 2), (0b0110, 1)], [(0b1000, 1), (0b1111, 3)])          # disjoint
    assert C.select(law, Fr(1), Fr(1, 100), False, law.overlap_int()[0])[0] == "REJECT"
    assert RT.route_S(law, Fr(1), 0)["status"] == "REJECT" and RT.route_E(law, Fr(1), False)["status"] == "REJECT"
    law2 = law_of(4, [(0b0001, 2), (0b0110, 1)], [(0b0001, 5), (0b1111, 3)])        # overlapping
    s = RT.route_S(law2, Fr(1), 0); Z, N, _ = brute(law2, Fr(1))
    assert s["status"] == "OK" and s["U_int"] == 0 and all(lo == hi == Fr(N[i], Z) for i, (lo, hi) in enumerate(s["intervals"]))
    assert C.select(law2, Fr(1), Fr(1, 100), False, law2.overlap_int()[0])[0] == "S0"
    p = RT.route_PI(law2); assert C.select(law2, Fr(0), Fr(1, 100), False, 0)[0] == "PI"
    assert [lo for lo, hi in p["intervals"]] == [Fr(2, 3), Fr(1, 3), Fr(1, 3), Fr(0)]
    p["published"] = [C.publish(lo, hi) for lo, hi in p["intervals"]]; assert CK.check(law2, Fr(0), p, False)["ok"]


def test_outward_rounding_grid_and_width_slack():
    lo, hi = Fr(1, 3), Fr(2, 3)
    lg, hg = C.publish(lo, hi); q = 1 << C.GRID_BITS
    assert Fr(lg, q) <= lo and hi <= Fr(hg, q) and Fr(hg - lg, q) - (hi - lo) <= C.EPS_GRID_SLACK
    assert C.publish(Fr(-1, 7), Fr(9, 7)) == (0, q)
    assert C.publish(Fr(1, 2), Fr(1, 2)) == (q // 2, q // 2)


def test_duplicate_rows_and_missing_coordinates_and_bad_weights():
    with pytest.raises(C.InputError):
        C.Law(3, [(1, 1), (1, 2)], [(2, 1)])
    with pytest.raises(C.InputError):
        C.Law(3, [(1, 1)], [(2, 0)])
    with pytest.raises(C.InputError):
        C.Law(3, [(9, 1)], [(2, 1)])
    law = rnd_law(4, 5, 5, 6); r = Fr(1, 4); sym = False
    e = RT.route_E(law, r, sym); e["published"] = [C.publish(lo, hi) for lo, hi in e["intervals"]]
    bad = dict(e); bad["intervals"] = e["intervals"][:-1]; bad["published"] = e["published"][:-1]
    with pytest.raises(CK.CheckFailure):
        CK.check(law, r, bad, sym)


def test_tampering_is_detected():
    law = antipodal_law(6, 4, 9, 7); sym = True; r = Fr(1, 8)
    f = RT.route_F(law, r, 2, sym); f["published"] = [C.publish(lo, hi) for lo, hi in f["intervals"]]
    assert CK.check(law, r, f, sym)["ok"]
    muts = {"moments": lambda d: d.__setitem__("Zk_int", d["Zk_int"] + 1),
            "numerator": lambda d: d["Mk_int"].__setitem__(0, d["Mk_int"][0] - 1),
            "residual": lambda d: d.__setitem__("eta_M", d["eta_M"] / 2),
            "interval": lambda d: d["intervals"].__setitem__(1, (d["intervals"][1][0] + Fr(1, 10 ** 6), d["intervals"][1][1])),
            "published": lambda d: d["published"].__setitem__(2, (d["published"][2][0] + 1, d["published"][2][1]))}
    for name, mut in muts.items():
        bad = json.loads(json.dumps({k: v for k, v in f.items() if k != "wall"}, default=str))
        bad["intervals"] = [(Fr(a), Fr(b)) for a, b in bad["intervals"]]; bad["published"] = [(int(a), int(b)) for a, b in bad["published"]]
        bad["Zk_int"] = int(bad["Zk_int"]); bad["Mk_int"] = [int(x) for x in bad["Mk_int"]]; bad["eta_Z"] = Fr(bad["eta_Z"]); bad["eta_M"] = Fr(bad["eta_M"])
        mut(bad)
        with pytest.raises(CK.CheckFailure):
            CK.check(law, r, bad, sym)
    # symmetry claim tampering: claim symmetric on a generic law
    g = rnd_law(6, 8, 8, 8); fg = RT.route_F(g, r, 2, True); fg["published"] = [C.publish(lo, hi) for lo, hi in fg["intervals"]]
    with pytest.raises(CK.CheckFailure):
        CK.check(g, r, fg, True)
    # weight tampering: a different law than the one checked
    law_t = C.Law(6, [(x, (w + 1 if i == 0 else w)) for i, (x, w) in enumerate(zip(law.A_rows, law.A_w))], list(zip(law.B_rows, law.B_w)))
    e = RT.route_E(law, r, sym); e["published"] = [C.publish(lo, hi) for lo, hi in e["intervals"]]
    with pytest.raises(CK.CheckFailure):
        CK.check(law_t, r, e, law_t.antipodal()[0])
    # S tampering
    s = RT.route_S(law, Fr(1) - Fr(1, 64), 1); s["published"] = [C.publish(lo, hi) for lo, hi in s["intervals"]]
    assert CK.check(law, Fr(1) - Fr(1, 64), s, sym)["ok"]
    s["U_int"] -= 1
    with pytest.raises(CK.CheckFailure):
        CK.check(law, Fr(1) - Fr(1, 64), s, sym)


def test_scouts_are_sufficient_on_small_instances_and_generator_is_deterministic():
    law = antipodal_law(8, 6, 12, 9); sym = True
    for r in (Fr(1, 16), Fr(1, 64)):
        for k in range(0, 4):
            sc = C.spectral_scout(law.n, r, k, sym, Fr(1, 100) - C.EPS_GRID_SLACK)
            f = RT.route_F(law, r, k, sym)
            if sc["qualified"]:
                assert f["status"] == "OK" and max(hi - lo for lo, hi in f["intervals"]) <= Fr(1, 100)
    Pint, _ = law.overlap_int()
    for r in (Fr(1) - Fr(1, 2 ** 12),):
        for h in (0, 1):
            sc = C.sparse_scout(law.n, r, h, Pint, law.A0 * law.B0, Fr(1, 100) - C.EPS_GRID_SLACK)
            s = RT.route_S(law, r, h)
            if sc["qualified"]:
                assert s["status"] == "OK" and s["rho"] <= Fr(1, 100)
    g1 = GEN.generate({"name": "t", "n": 10, "m": 32, "kind": "antipodal", "p": "3/4", "seed": 0}); g2 = GEN.generate({"name": "t", "n": 10, "m": 32, "kind": "antipodal", "p": "3/4", "seed": 0})
    assert g1["A"] == g2["A"] and g1["B"] == g2["B"]
    lawg = C.Law(10, g1["A"], g1["B"]); assert lawg.antipodal()[0] and len(set(x for x, _ in g1["A"]) & set(y for y, _ in g1["B"])) >= 4
    ones = sum(bin(x).count("1") for x, _ in g1["B"]); assert 0.6 < ones / (32 * 10) < 0.9             # Bernoulli-3/4 bits (two exact stream bits)
