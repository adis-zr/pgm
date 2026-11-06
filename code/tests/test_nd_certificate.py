"""Conformance suite for the two-channel discarded-mass certificate (isolated branch nd-certificate-2026-11-05). Every
control enumerates at most 4,096 complete states. The tests validate the IMPLEMENTATION against the supplied proofs
(theory handoff of 5 Nov 2026); they do not replace the proofs."""
import os, sys, json, itertools, random, tempfile
HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)
from fractions import Fraction as Fr
import pytest
from mdi import model as M, pipeline as PLN
import mdi.registry  # noqa: F401
from nd import twochannel as TC, masks as MK, certificate_check as CC, retained as RT, transfer as TR, generate as GEN

MAX_STATES = 4096


def brute(model, ev, occ, masks):
    """Exact (R, D, Z, retained numerators, full numerators) by enumeration of the restricted model (<= 4,096 states)."""
    free = [v for v in range(model.nvars) if v not in ev]
    n = 1
    for v in free:
        n *= model.card[v]
    assert n <= MAX_STATES
    R = D = Fr(0); numR = {}; numP = {}
    scal = Fr(1)
    for f in model.factors:
        if all(v in ev for v in f.scope):
            scal *= f.at({v: ev[v] for v in f.scope})
    for a in itertools.product(*[range(model.card[v]) for v in free]):
        asg = dict(ev); asg.update(dict(zip(free, a)))
        w = scal; viol = False
        for o, mk in zip(occ, masks):
            st = [1] * len(o["card"]); acc = 1
            for k in range(len(o["card"]) - 1, -1, -1):
                st[k] = acc; acc *= o["card"][k]
            off = sum(asg[v] * s for v, s in zip(o["scope"], st))
            w *= o["table"][off]; viol |= off in set(mk["removed"])
        if w == 0:
            continue
        if viol:
            D += w
        else:
            R += w
            for v in free:
                numR[(v, asg[v])] = numR.get((v, asg[v]), Fr(0)) + w
        for v in free:
            numP[(v, asg[v])] = numP.get((v, asg[v]), Fr(0)) + w
    return R, D, R + D, numR, numP


def run_cert(model, ev, G, K=4096, masks=None):
    occ, sc = MK.restricted_occurrences(model, ev)
    mk = MK.apply_masks(occ, Fr(G)) if masks is None else masks
    free = [v for v in range(model.nvars) if v not in ev]; card = {v: model.card[v] for v in free}
    cert = TC.run_certificate(occ, mk, sc, free, card, K=K)
    return occ, mk, sc, cert


def F(scope, table, origin, card=None):
    card = card or tuple(2 for _ in scope)
    return M.Factor(scope=tuple(scope), card=tuple(card), table=[Fr(x) for x in table], origin=origin)


# ------------------------------------------------------------------ 1. exact algebra
def test_pair_semiring_laws_and_monotonicity():
    rng = random.Random(3)
    P = lambda: (Fr(rng.randint(0, 9), rng.randint(1, 5)), Fr(rng.randint(0, 9), rng.randint(1, 5)))
    for _ in range(200):
        a, b, c = P(), P(), P()
        assert TC.pair_add(a, b) == TC.pair_add(b, a) and TC.pair_mul(a, b) == TC.pair_mul(b, a)
        assert TC.pair_mul(TC.pair_mul(a, b), c) == TC.pair_mul(a, TC.pair_mul(b, c))
        assert TC.pair_mul(a, TC.pair_add(b, c)) == TC.pair_add(TC.pair_mul(a, b), TC.pair_mul(a, c))
        assert TC.pair_mul(a, (Fr(1), Fr(0))) == a and TC.pair_add(a, (Fr(0), Fr(0))) == a
        # total channel is a homomorphism; monotone coordinatewise
        assert sum(TC.pair_mul(a, b)) == sum(a) * sum(b)
        a2 = (a[0] + Fr(1, 3), a[1] + Fr(1, 7))
        m1, m2 = TC.pair_mul(a, b), TC.pair_mul(a2, b)
        assert m1[0] <= m2[0] and m1[1] <= m2[1]


# ------------------------------------------------------------------ 2. no deletion: U == 0 even with forced splits
def test_no_deletion_discarded_channel_identically_zero_with_splits():
    rng = random.Random(5)
    facs = [F((0, 1), [rng.randint(1, 9) for _ in range(4)], 0), F((0, 2), [rng.randint(1, 9) for _ in range(4)], 1), F((0, 3), [rng.randint(1, 9) for _ in range(4)], 2), F((1, 2, 3), [rng.randint(1, 9) for _ in range(8)], 3)]
    m = M.Model(nvars=4, card=[2] * 4, factors=facs).validate()
    occ, sc = MK.restricted_occurrences(m, {}); mk = [{"origin": o["origin"], "removed": []} for o in occ]
    R, D, Z, _, _ = brute(m, {}, occ, mk)
    cert = TC.run_certificate(occ, mk, sc, [0, 1, 2, 3], {v: 2 for v in range(4)}, K=8)       # K=8 admits every input factor (max domain 8) and forces splits at variable 0
    assert cert["stats"]["split_buckets"] >= 1 and cert["U"] == 0 and cert["V"] >= R and D == 0
    exact = TC.run_certificate(occ, mk, sc, [0, 1, 2, 3], {v: 2 for v in range(4)}, K=4096)
    assert exact["V"] == R and exact["U"] == 0 and exact["stats"]["split_buckets"] == 0


# ------------------------------------------------------------------ 3. independent unary example (Proposition 3)
def test_independent_unary_exact_D():
    eta = Fr(1, 7); n = 10
    m = M.Model(nvars=n, card=[2] * n, factors=[F((v,), [1, eta], v) for v in range(n)]).validate()
    occ, sc = MK.restricted_occurrences(m, {}); mk = [{"origin": o["origin"], "removed": [1]} for o in occ]
    cert = TC.run_certificate(occ, mk, sc, list(range(n)), {v: 2 for v in range(n)})
    assert cert["V"] == 1 and cert["U"] == (1 + eta) ** n - 1 and cert["stats"]["split_buckets"] == 0
    R, D, Z, _, _ = brute(m, {}, occ, mk)
    assert (R, D) == (Fr(1), (1 + eta) ** n - 1)


# ------------------------------------------------------------------ 4. overlapping violations counted once
def test_overlapping_violations_counted_once():
    facs = [F((0, 1), [1, 2, 3, Fr(1, 1000)], 0), F((1, 2), [4, Fr(1, 1000), 5, 6], 1), F((0, 2), [Fr(1, 1000), 7, 8, 9], 2)]
    m = M.Model(nvars=3, card=[2] * 3, factors=facs).validate()
    occ, mk, sc, cert = run_cert(m, {}, 100)
    assert all(len(x["removed"]) == 1 for x in mk)
    R, D, Z, _, _ = brute(m, {}, occ, mk)
    assert cert["V"] == R and cert["U"] == D and D > 0
    # a per-factor union bound would overcount the configuration violating two masks at once
    per_factor = sum(sum(o["table"][i] for i in x["removed"]) for o, x in zip(occ, mk))
    assert cert["U"] <= Z


# ------------------------------------------------------------------ 5. a deliberately split bound: valid, loose, exact when unsplit
def test_split_bound_is_valid_and_exact_without_split():
    eta = Fr(1, 10)
    facs = [F((0, 1), [1, 1, 1, eta], 0), F((0, 2), [1, 1, 1, eta], 1)]
    m = M.Model(nvars=3, card=[2] * 3, factors=facs).validate()
    occ, sc = MK.restricted_occurrences(m, {}); mk = [{"origin": o["origin"], "removed": [3]} for o in occ]
    R, D, Z, _, _ = brute(m, {}, occ, mk)
    split = TC.run_certificate(occ, mk, sc, [0, 1, 2], {v: 2 for v in range(3)}, K=4, order=[0, 1, 2])   # eliminating 0 first with K=4 forces the two factors apart
    exact = TC.run_certificate(occ, mk, sc, [0, 1, 2], {v: 2 for v in range(3)}, K=4096)
    assert split["stats"]["split_buckets"] >= 1 and split["V"] >= R and split["U"] >= D and split["U"] > D
    assert exact["V"] == R and exact["U"] == D
    # the theory's two-identical-occurrence example: separate groups give (1, 2 eta + eta^2)
    occ2 = [{"scope": (0,), "card": (2,), "table": [Fr(1), eta], "origin": 0, "orig_positions": [0, 1]}, {"scope": (0,), "card": (2,), "table": [Fr(1), eta], "origin": 1, "orig_positions": [0, 1]}]
    mk2 = [{"origin": 0, "removed": [1]}, {"origin": 1, "removed": [1]}]
    ex2 = TC.run_certificate(occ2, mk2, [], [0], {0: 2})
    assert (ex2["V"], ex2["U"]) == (Fr(1), eta ** 2)                     # first-fit keeps them together: exact
    assert TC.pair_mul((Fr(1), eta), (Fr(1), eta)) == (Fr(1), 2 * eta + eta ** 2)   # the split product of the theory's example


# ------------------------------------------------------------------ 6. evidence, scalar occurrences
def test_evidence_and_scalar_occurrences():
    facs = [F((0, 1), [1, 2, Fr(1, 500), 3], 0), F((1, 2), [Fr(1, 400), 4, 5, 6], 1), F((2,), [7, 8], 2), F((3,), [Fr(1, 3), 9], 3), F((3, 0), [1, 1, 1, Fr(1, 900)], 4)]
    m = M.Model(nvars=4, card=[2] * 4, factors=facs).validate()
    ev = {3: 1}
    occ, mk, sc, cert = run_cert(m, ev, 100)
    assert sc == [(3, Fr(9))]
    R, D, Z, _, _ = brute(m, ev, occ, mk)
    assert cert["V"] == R and cert["U"] == D and cert["n_scalars"] == 1


# ------------------------------------------------------------------ 7. inconsistent retention
def test_inconsistent_retention_refuses_at_the_retained_solve():
    facs = [F((0, 1), [1, Fr(1, 1000), Fr(1, 1000), 1], 0), F((0,), [Fr(1, 1000), 1], 1), F((1,), [1, Fr(1, 1000)], 2)]
    m = M.Model(nvars=2, card=[2, 2], factors=facs).validate()
    occ, mk, sc, cert = run_cert(m, {}, 100)
    R, D, Z, _, _ = brute(m, {}, occ, mk)
    assert R == 0 and cert["V"] == 0 and cert["U"] == D == Z
    masked = MK.masked_model(m, occ, mk)
    out, res = RT.solve_retained(masked, {}, wall_s=60, cap_bytes=1 << 30)
    assert res.status == "ZERO_EVIDENCE_PROVED" and out["refusal"].startswith("INCONSISTENT_RETENTION")
    assert Z > 0                                                           # the original positive model is unaffected


# ------------------------------------------------------------------ 8. duplicate occurrences
def test_duplicate_occurrences_each_retained_separately():
    f = F((0, 1), [1, 2, 3, Fr(1, 1000)], 0)
    facs = [f, F((0, 1), [1, 2, 3, Fr(1, 1000)], 1), F((1, 2), [1, 1, 1, 2], 2)]
    m = M.Model(nvars=3, card=[2] * 3, factors=facs).validate()
    occ, mk, sc, cert = run_cert(m, {}, 100)
    R, D, Z, _, _ = brute(m, {}, occ, mk)
    assert cert["V"] == R and cert["U"] == D and cert["n_occurrences"] == 3
    # the same configuration violates both duplicates: in channel one exactly once (D is the brute-force sum)
    assert D == Fr(1, 1000) ** 2 * (1 + 2)


# ------------------------------------------------------------------ 9. disconnected components (pair product, never a plain sum)
def test_disconnected_components_pair_multiplied():
    eta = Fr(1, 100)
    facs = [F((0,), [1, eta], 0), F((1,), [1, eta], 1)]
    m = M.Model(nvars=2, card=[2, 2], factors=facs).validate()
    occ, sc = MK.restricted_occurrences(m, {}); mk = [{"origin": 0, "removed": [1]}, {"origin": 1, "removed": [1]}]
    cert = TC.run_certificate(occ, mk, sc, [0, 1], {0: 2, 1: 2})
    assert (cert["V"], cert["U"]) == (Fr(1), 2 * eta + eta ** 2)          # not eta + eta
    R, D, Z, _, _ = brute(m, {}, occ, mk)
    assert (R, D) == (cert["V"], cert["U"])


# ------------------------------------------------------------------ 10. scaling (denominator clearing)
def test_denominator_clearing_scale_and_original_units():
    facs = [F((0, 1), [Fr(1, 3), Fr(2, 7), Fr(5, 11), Fr(1, 3000)], 0), F((1, 2), [Fr(1, 13), Fr(1), Fr(3, 2), Fr(1, 4)], 1), F((2,), [Fr(2, 9), Fr(1, 9)], 2)]
    m = M.Model(nvars=3, card=[2] * 3, factors=facs).validate()
    occ, mk, sc, cert = run_cert(m, {}, 100)
    R, D, Z, _, _ = brute(m, {}, occ, mk)
    import math
    C = 1
    for o in occ:
        L = 1
        for x in o["table"]:
            L = L * x.denominator // math.gcd(L, x.denominator)
        C *= L
    assert int(cert["C"]) == C and Fr(int(cert["V_int"]), C) == R == cert["V"] and Fr(int(cert["U_int"]), C) == D == cert["U"]


# ------------------------------------------------------------------ 11. sharp interval endpoints (Proposition 4)
def test_sharp_mixture_endpoints_attained():
    eta = Fr(1, 9)
    m = M.Model(nvars=1, card=[2], factors=[F((0,), [1, eta], 0)]).validate()
    occ, sc = MK.restricted_occurrences(m, {}); mk = [{"origin": 0, "removed": [1]}]
    R, D, Z, numR, numP = brute(m, {}, occ, mk)
    rho = TR.rho_of(R, D)
    lo0, hi0 = TR.transfer_interval(Fr(1), Fr(1), rho)       # retained law: x=0 with probability exactly 1
    lo1, hi1 = TR.transfer_interval(Fr(0), Fr(0), rho)
    assert lo0 == numP[(0, 0)] / Z and hi1 == numP[(0, 1)] / Z          # both endpoints ATTAINED
    assert hi0 == 1 and lo1 == 0
    # the general containment and the width formula on a 3-variable model with widths
    facs = [F((0, 1), [1, 2, 3, Fr(1, 1000)], 0), F((1, 2), [4, Fr(1, 1000), 5, 6], 1)]
    m2 = M.Model(nvars=3, card=[2] * 3, factors=facs).validate()
    occ2, mk2, sc2, cert2 = run_cert(m2, {}, 100)
    R2, D2, Z2, numR2, numP2 = brute(m2, {}, occ2, mk2)
    rho2 = TR.rho_of(R2, cert2["U"])
    for (v, a), nP in numP2.items():
        q = numR2.get((v, a), Fr(0)) / R2
        w = Fr(1, 500); l, u = max(Fr(0), q - w), min(Fr(1), q + w)
        tl, tu = TR.transfer_interval(l, u, rho2)
        assert tl <= nP / Z2 <= tu and tu - tl == (1 - rho2) * (u - l) + rho2
    # the exact-R form [N/(R+U), (N+U)/(R+U)]
    for (v, a), nR in numR2.items():
        tl, tu = TR.transfer_interval(nR / R2, nR / R2, rho2)
        assert tl == nR / (R2 + cert2["U"]) and tu == (nR + cert2["U"]) / (R2 + cert2["U"])


# ------------------------------------------------------------------ 12. mask rule: ties, nesting, no gap
def test_gap_rule_ties_nesting_and_no_gap():
    assert MK.gap_removed([Fr(1), Fr(1, 100)], Fr(100)) == ([1], Fr(1, 100))             # tie: v2 == G v1 is eligible
    assert MK.gap_removed([Fr(1), Fr(1, 99)], Fr(100)) == ([], None)
    assert MK.gap_removed([Fr(1), Fr(1, 100), Fr(1, 10 ** 6), Fr(0)], Fr(100)) == ([1, 2], Fr(1, 100))   # the LARGEST j; zeros never listed
    assert MK.gap_removed([Fr(1), Fr(1, 100), Fr(1, 10 ** 6)], Fr(10000)) == ([2], Fr(1, 10 ** 6))
    m = M.read_uai(os.path.join(HERE, "runs/mdi_2026-10-28/ND_CERTIFICATE_2026-11-05/inputs/Promedus_12_L1e-4.uai"))
    ev = M.read_evidence(os.path.join(HERE, "runs/mdi_2026-10-28/ND_CERTIFICATE_2026-11-05/inputs/Promedus_12_L1e-4.uai.evid"), m)
    occ, sc = MK.restricted_occurrences(m, ev)
    a = MK.apply_masks(occ, Fr(10000)); b = MK.apply_masks(occ, Fr(100))
    assert all(set(x["removed"]) <= set(y["removed"]) for x, y in zip(a, b))              # G=100 removes a superset, occurrence by occurrence
    assert all(x["positive_entries"] > len(x["removed"]) for x in a + b)                   # every affected factor keeps a positive entry


# ------------------------------------------------------------------ 13. end to end on a tiny model: retained solve, exact R, transfer containment, checker, tampering
def test_end_to_end_tiny_with_checker_and_tampering():
    rng = random.Random(11)
    facs = [F((0, 1), [1, 2, 3, Fr(1, 1000)], 0), F((1, 2), [4, Fr(1, 1000), 5, 6], 1), F((2, 3), [1, 1, Fr(1, 2000), 2], 2), F((3, 0), [2, 1, 1, 3], 3), F((4, 2), [1, Fr(1, 5000), 1, 1], 4)]
    m = M.Model(nvars=5, card=[2] * 5, factors=facs).validate()
    tmp = tempfile.mkdtemp()
    GEN.write_uai(m, os.path.join(tmp, "t.uai")); open(os.path.join(tmp, "t.uai.evid"), "w").write("1 4 0\n")
    m = M.read_uai(os.path.join(tmp, "t.uai")); ev = M.read_evidence(os.path.join(tmp, "t.uai.evid"), m)
    occ, mk, sc, cert = run_cert(m, ev, 100)
    R, D, Z, numR, numP = brute(m, ev, occ, mk)
    assert cert["V"] == R and cert["U"] == D
    chk = CC.check(os.path.join(tmp, "t.uai"), os.path.join(tmp, "t.uai.evid"), 100, cert)
    assert chk["both_channels_match"] and chk["V"] == R and chk["U"] == D
    masked = MK.masked_model(m, occ, mk)
    out, res = RT.solve_retained(masked, ev, wall_s=60, cap_bytes=1 << 30)
    assert res.status.startswith("CERTIFIED") and Fr(out["R"]) == R, (out["R"], R)
    rho = TR.rho_of(Fr(out["R"]), cert["U"])
    ex, rd, summ = TR.transfer_publication(out["intervals"], ev, {v: 2 for v in range(5)}, rho)
    for (v, a), nP in numP.items():
        assert ex[v][a][0] <= nP / Z <= ex[v][a][1] and rd[v][a][0] <= nP / Z <= rd[v][a][1]
    assert ex[4] == [[Fr(1), Fr(1)], [Fr(0), Fr(0)]]                                      # observed coordinate stays exact
    # tampering: U, order, group membership
    for field, mut in (("U_int", lambda r: str(int(r["U_int"]) - 1)), ("order", lambda r: list(reversed(r["order"]))),):
        bad = json.loads(json.dumps(cert, default=str)); bad[field] = mut(bad)
        with pytest.raises(CC.CheckFailure):
            CC.check(os.path.join(tmp, "t.uai"), os.path.join(tmp, "t.uai.evid"), 100, bad)
    bad = json.loads(json.dumps(cert, default=str))
    g = bad["schedule"][0]["groups"][0]; g["member_fids"] = g["member_fids"][::-1] if len(g["member_fids"]) > 1 else g["member_fids"] + [[0, 99]]
    with pytest.raises(CC.CheckFailure):
        CC.check(os.path.join(tmp, "t.uai"), os.path.join(tmp, "t.uai.evid"), 100, bad)
