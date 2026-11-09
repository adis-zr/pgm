"""Qualification controls for the BIDI pilot (kernel, executor, MPFR reference, cell, publication, binding). Every numerical check compares
against the brute-force exact rational oracle (bidi.oracle) or against exact rational bounds; native vs MPFR-53 bitwise agreement is a
complementary control, not an independence claim (same schedule). Tiny synthetic models only; no benchmark input is read."""
from __future__ import annotations
import sys, os, json, time, random, subprocess, ctypes, shutil
sys.set_int_max_str_digits(0)
HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__))); sys.path.insert(0, HERE)
from fractions import Fraction as Fr
import pytest
from bidi import executor as EX, recognize as RZ, oracle as OR, mpfr_ref as MR
from ext import uai as U

PY = sys.executable; ENV = dict(os.environ, PYTHONPATH=HERE)


def dec(q):
    """exact decimal string of a rational with denominator dividing 10^6"""
    q = Fr(q); assert (10 ** 6) % q.denominator == 0; return "%d.%06d" % (q.numerator * (10 ** 6 // q.denominator) // 10 ** 6, q.numerator * (10 ** 6 // q.denominator) % 10 ** 6)


def write_uai(path, nvars, factors, ev=None, card=None):
    """factors: list of (scope tuple, table list of Fractions with denominators | 10^6)"""
    card = card or [2] * nvars
    lines = ["MARKOV", str(nvars), " ".join(map(str, card)), str(len(factors))]
    for sc, _ in factors:
        lines.append("%d %s" % (len(sc), " ".join(map(str, sc))))
    for _, tab in factors:
        lines.append("%d %s" % (len(tab), " ".join(dec(x) for x in tab)))
    open(path, "w").write("\n".join(lines) + "\n")
    ev = ev or {}
    open(path + ".evid", "w").write("%d %s\n" % (len(ev), " ".join("%d %d" % (v, s) for v, s in ev.items())))
    return path, path + ".evid"


def rnd_bipartite(seed, X, Y, zeros=0.0, absent=0.0, scalar=False, flip_orientation=True, lo=1, hi=999):
    r = random.Random(seed); facs = []
    if scalar:
        facs.append(((), [Fr(r.randint(lo, hi), 1000)]))
    for v in X + Y:
        facs.append(((v,), [Fr(0) if r.random() < zeros else Fr(r.randint(lo, hi), 1000) for _ in range(2)]))
    for a in X:
        for b in Y:
            if r.random() < absent:
                continue
            sc = (a, b) if (not flip_orientation or r.random() < 0.5) else (b, a)
            facs.append((sc, [Fr(0) if r.random() < zeros else Fr(r.randint(lo, hi), 1000) for _ in range(4)]))
    return facs


def truth_inside(rec, model, ev):
    Z, N = OR.brute(model, ev)
    if Z == 0:
        return rec["status"] == "ZERO_EVIDENCE_PROVED"
    for v in range(model.nvars):
        for s, (a, b) in enumerate(rec["certified_intervals"][str(v)]):
            if not (Fr(a) <= N[v][s] / Z <= Fr(b)):
                return False
    return True


def run_exec(mp, ep, out, k=1, block=3, factory=EX.NativeKernel, plan=None, conv=EX.to_binary64):
    os.makedirs(out, exist_ok=True); plan = plan or RZ.recognize(mp, ep)
    return EX.execute(mp, ep, plan, out, time.monotonic() + 60, {"lanes_k": k, "block_steps": block}, kernel_factory=factory, conv=conv)


# ------------------------------------------------------------------------------------------------------------ exactness vs oracle
CASES = [  # (seed, X, Y, zeros, absent, scalar, evidence)
    (1, [0, 1, 2], [3, 4], 0.0, 0.0, False, {}), (2, [0, 2, 4], [1, 3], 0.0, 0.0, False, {}),               # positive; relabelled sides
    (3, [0, 1, 2, 3], [4], 0.0, 0.0, True, {}), (4, [0], [1, 2, 3, 4], 0.0, 0.3, False, {}),                # unequal sides, scalar, absent edges
    (5, [0, 1, 2], [3, 4, 5], 0.25, 0.0, False, {}), (6, [0, 1], [2, 3], 0.4, 0.2, True, {}),               # zeros
    (7, [0, 1, 2], [3, 4], 0.0, 0.0, False, {0: 1, 4: 0}), (8, [0, 1], [2, 3, 4], 0.3, 0.0, False, {2: 1}),  # evidence (x side / y side)
    (9, [0, 1, 2, 3, 4, 5], [], 0.0, 0.0, False, {}), (10, [], [0, 1, 2], 0.0, 0.0, True, {}),            # unary-only (empty y), empty x
    (11, [0, 1, 2, 3], [4, 5, 6, 7, 8], 0.1, 0.1, False, {3: 0}),                                        # larger: 2^5 configs, tails with k=1,2
]


@pytest.mark.parametrize("seed,X,Y,zeros,absent,scalar,ev", CASES)
@pytest.mark.parametrize("k", [0, 1, 2])
def test_native_enclosures_contain_exact_truth_and_match_mpfr53_bitwise(tmp_path, seed, X, Y, zeros, absent, scalar, ev, k):
    nv = len(X) + len(Y); mp, ep = write_uai(str(tmp_path / "m.uai"), nv, rnd_bipartite(seed, X, Y, zeros, absent, scalar), ev)
    model = U.read_model(mp); kk = min(k, max(0, min(len(X), len(Y)) if (X and Y) else min(len(X), len(Y))))
    plan = RZ.recognize(mp, ep); assert plan["kind"] == RZ.PLAN_KIND
    rn = run_exec(mp, ep, str(tmp_path / "n"), k=kk, block=3)
    assert truth_inside(rn, model, ev), rn["status"]
    if rn["status"] == "INTERVALS_OK":
        assert rn["kernel"]["complete"] and rn["kernel"]["configs_visited"] == 2 ** len(rn["structure"]["y_side"])
        # every row of the exact oracle sums to Z; every published row's intervals are consistent
        Z, N = OR.brute(model, ev); assert all(sum(N[v]) == Z for v in range(nv))
        rm = run_exec(mp, ep, str(tmp_path / "r"), k=kk, block=3, factory=EX.MpfrKernel)
        assert rm["values_hex"] == rn["values_hex"], "native and MPFR-53 nearest differ bitwise on the same schedule"
        assert rm["certified_intervals"] == rn["certified_intervals"]
        # evidence rows are exact one-hot in the forbidden state
        for v, s in ev.items():
            assert rn["certified_intervals"][str(v)][1 - s] == ["0", "0"]


def test_zero_normalizer_is_proved_not_inferred_from_underflow(tmp_path):
    # evidence x0=1 and a unary [a, 0]: every weight is exactly zero -> structural zero (a factor without a positive entry after evidence)
    facs = [((0,), [Fr(1, 2), Fr(0)]), ((1,), [Fr(1, 4), Fr(3, 4)]), ((0, 1), [Fr(1, 8), Fr(1, 8), Fr(1, 8), Fr(1, 8)])]
    mp, ep = write_uai(str(tmp_path / "m.uai"), 2, facs, {0: 1}); r = run_exec(mp, ep, str(tmp_path / "o"))
    assert r["status"] == "ZERO_EVIDENCE_PROVED" and "no positive entry" in r["reason"]
    # Z = 0 by cancellation of supports (pair factor zero exactly where the unaries are positive): computed Z == 0.0 is a PROOF under the range bound
    facs = [((0,), [Fr(1), Fr(0)]), ((1,), [Fr(0), Fr(1)]), ((0, 1), [Fr(1), Fr(0), Fr(1), Fr(1)])]
    mp, ep = write_uai(str(tmp_path / "m2.uai"), 2, facs); r = run_exec(mp, ep, str(tmp_path / "o2"))
    assert r["status"] == "ZERO_EVIDENCE_PROVED" and "exactly 0" in r["reason"]
    Z, _ = OR.brute(U.read_model(mp), {}); assert Z == 0


# ------------------------------------------------------------------------------------------------------------ coverage / lanes / Gray
def test_lane_partition_and_gray_traversal_visit_every_configuration_exactly_once(tmp_path):
    for n, k in [(1, 0), (3, 1), (5, 2), (6, 3), (4, 4), (7, 0)]:
        X = [0]; Y = list(range(1, n + 1)); mp, ep = write_uai(str(tmp_path / ("m%d_%d.uai" % (n, k))), n + 1, rnd_bipartite(40 + n, X, Y))
        plan = dict(RZ.recognize(mp, ep), x_side=X, y_side=Y); model = U.read_model(mp); ev = {}; S = EX.validate_structure(model, ev, plan); phi, rho, psi, kappa, _ = EX.convert_tables(S)   # explicit sides so n is as intended
        K = EX.NativeKernel(); K.create(S["m"], S["n"], k, phi, rho, psi, kappa); seen = []
        while not K.done():
            K.step(1); seen.append(int(K.lib.bidi_current_ylow(K.S)))
        Z, NX, NY, c, ok = K.finish(); K.destroy()
        assert ok and c["configs"] == 2 ** n and sorted(seen) == list(range(2 ** (n - k))) and len(seen) == 2 ** (n - k)
        assert all(bin(a ^ b).count("1") == 1 for a, b in zip(seen, seen[1:]))                              # Gray: consecutive low patterns differ in one bit
        Zt, Nt = OR.brute(model, ev); assert abs(Fr(Z) - Zt) <= Fr(1, 10 ** 9) * Zt


def test_block_sizes_and_tails_do_not_change_the_result(tmp_path):
    mp, ep = write_uai(str(tmp_path / "m.uai"), 7, rnd_bipartite(77, [0, 1, 2], [3, 4, 5, 6], zeros=0.15)); vals = set()
    for block in (1, 3, 5, 16, 4096):
        r = run_exec(mp, ep, str(tmp_path / ("b%d" % block)), k=2, block=block); vals.add(json.dumps(r["values_hex"]))
    assert len(vals) == 1


# ------------------------------------------------------------------------------------------------------------ conversion / range / precision contract
def test_converted_source_check_halfway_cases_and_rejections():
    u = Fr(1, 2 ** 53)
    for q in [Fr(1), Fr(1, 3), Fr(7, 10 ** 6), Fr(2 ** 53 + 1, 2 ** 53), Fr(2 ** 53 + 3, 2 ** 53), Fr(2 ** 54 + 2, 2 ** 53), Fr(10 ** 300), Fr(1, 10 ** 300), Fr(3, 2 ** 1030)]:
        x = EX.to_binary64_checked(q, "t"); assert (1 - u) * q <= Fr(x) <= (1 + u) * q
    assert EX.to_binary64_checked(Fr(2 ** 53 + 1, 2 ** 53), "t") == 1.0                                       # exact tie -> even
    assert EX.to_binary64_checked(Fr(2 ** 53 + 3, 2 ** 53), "t") == 1.0 + 2 ** -51                          # tie -> even (upper neighbour is even)
    assert EX.to_binary64_checked(Fr(0), "t") == 0.0
    with pytest.raises(EX.Refuse) as e:
        EX.to_binary64_checked(Fr(10 ** 400), "t")
    assert e.value.kind == "ROUTE_LIMITATION"
    with pytest.raises(EX.Refuse):
        EX.verify_binary64(Fr(0), 1e-300, "t")                                                             # zero must convert to exact zero
    with pytest.raises(EX.Refuse):
        EX.verify_binary64(Fr(1, 3), float("nan"), "t")
    with pytest.raises(EX.Refuse):
        EX.to_binary64_checked(Fr(1, 10 ** 400), "t")                                                         # positive -> zero conversion fails
    with pytest.raises(EX.Refuse):
        EX.to_binary64_checked(Fr(-1, 2), "t")


def test_range_proof_rejects_out_of_range_sources_and_admits_uneven_magnitudes_inside(tmp_path):
    # inside: entries spanning 1e-90 .. 1e90 on a tiny model (v = 3): L = 1e-180-ish, 2^v U = 8e180 -> normal binary64
    facs = [((0,), [Fr(1, 10 ** 90), Fr(10 ** 90)]), ((1,), [Fr(10 ** 90), Fr(1, 10 ** 90)]), ((2,), [Fr(1), Fr(1)]), ((0, 2), [Fr(1), Fr(2), Fr(3), Fr(4)]), ((1, 2), [Fr(2), Fr(1), Fr(1), Fr(2)])]
    mp = str(tmp_path / "m.uai"); lines = ["MARKOV", "3", "2 2 2", str(len(facs))] + ["%d %s" % (len(sc), " ".join(map(str, sc))) for sc, _ in facs] + ["%d %s" % (len(t), " ".join(str(x.numerator) if x.denominator == 1 else "0." + "0" * (len(str(x.denominator)) - 2) + "1" for x in t)) for _, t in facs]
    open(mp, "w").write("\n".join(lines) + "\n"); open(mp + ".evid", "w").write("0\n")
    r = run_exec(mp, mp + ".evid", str(tmp_path / "o")); assert r["status"] == "INTERVALS_OK" and truth_inside(r, U.read_model(mp), {})
    # outside: 1e-200 entries on two factors -> L = 1e-400 < DBL_MIN -> typed ROUTE_LIMITATION (not a mathematical refusal)
    facs2 = [((0,), [Fr(1, 10 ** 200), Fr(1)]), ((1,), [Fr(1, 10 ** 200), Fr(1)]), ((0, 1), [Fr(1), Fr(1), Fr(1), Fr(1)])]
    mp2 = str(tmp_path / "m2.uai"); lines = ["MARKOV", "2", "2 2", "3"] + ["%d %s" % (len(sc), " ".join(map(str, sc))) for sc, _ in facs2] + ["%d %s" % (len(t), " ".join("1" if x == 1 else "0." + "0" * 199 + "1" for x in t)) for _, t in facs2]
    open(mp2, "w").write("\n".join(lines) + "\n"); open(mp2 + ".evid", "w").write("0\n")
    with pytest.raises(EX.Refuse) as e:
        run_exec(mp2, mp2 + ".evid", str(tmp_path / "o2"))
    assert e.value.kind == "ROUTE_LIMITATION" and "RANGE" in e.value.reason


def test_depth_labels_and_delta_rejection():
    d = EX.depth_labels(22, 22, 3, 32, True); assert d["E_term"] >= d["E_T"] and d["e"] == 2 * d["E_N"] and d["E_N"] > 2 ** 19
    delta = EX.certificate_delta(d["e"]); assert 0 < delta < Fr(1, 10 ** 9)
    with pytest.raises(EX.Refuse) as e:
        EX.certificate_delta(2 ** 53)
    assert "PRECISION" in e.value.reason
    # enclosure lemma on exact values: q = N/Z with N, Z perturbed by (1+-u)^E stays inside
    u = Fr(1, 2 ** 53); E = 1000; Z = Fr(7, 3); N = Fr(2, 3); q = N / Z
    for fz, fn in [((1 - u) ** E, (1 + u) ** E), ((1 + u) ** E, (1 - u) ** E)]:
        Zh, Nh = Z * fz, N * fn; r = Nh / Zh; dlt = Fr(2 * E) * u
        assert (1 - dlt) * r <= q <= r / (1 - dlt)


def test_fp_environment_check_detects_a_changed_rounding_mode():
    K = EX.NativeKernel(); assert K.fp_mask == 0
    libc = ctypes.CDLL(None); libc.fesetround.argtypes = [ctypes.c_int]; libc.fegetround.restype = ctypes.c_int
    FE_UPWARD = 0x00400000 if sys.platform == "darwin" else 0x800; orig = libc.fegetround()
    try:
        assert libc.fesetround(FE_UPWARD) == 0
        assert K.lib.bidi_fp_env_check() & 8
    finally:
        libc.fesetround(orig)
    assert K.lib.bidi_fp_env_check() == 0


def test_build_record_binding_rejects_an_altered_kernel_or_schedule(tmp_path, monkeypatch):
    br = json.load(open(EX.BUILD_RECORD)); bad = dict(br, binary_sha256="0" * 64); p = str(tmp_path / "BUILD_RECORD.json"); json.dump(bad, open(p, "w"))
    monkeypatch.setattr(EX, "BUILD_RECORD", p)
    with pytest.raises(EX.Refuse) as e:
        EX.NativeKernel()
    assert e.value.kind == "FP_ENV" and "binary" in e.value.reason
    bad2 = dict(br, source_sha256="0" * 64); json.dump(bad2, open(p, "w"))
    with pytest.raises(EX.Refuse) as e:
        EX.NativeKernel()
    assert "schedule altered" in e.value.reason


# ------------------------------------------------------------------------------------------------------------ untrusted inputs / mutants
def test_recognizer_claims_cannot_bypass_structure_validation(tmp_path):
    mp, ep = write_uai(str(tmp_path / "m.uai"), 5, rnd_bipartite(21, [0, 1, 2], [3, 4])); plan = RZ.recognize(mp, ep)
    bad = dict(plan, x_side=[0, 1, 3], y_side=[2, 4])                                                      # a pair factor would fall inside one side
    with pytest.raises(EX.Refuse) as e:
        run_exec(mp, ep, str(tmp_path / "a"), plan=bad)
    assert e.value.kind == "ROUTE_LIMITATION" and "inside one side" in e.value.reason
    bad = dict(plan, x_side=[0, 1], y_side=[3, 4])                                                         # variable 2 missing
    with pytest.raises(EX.Refuse) as e:
        run_exec(mp, ep, str(tmp_path / "b"), plan=bad)
    assert e.value.kind == "REJECTED" and "partition" in e.value.reason
    with pytest.raises(EX.Refuse):
        run_exec(mp, ep, str(tmp_path / "c"), plan={"kind": "ROUTE_LIMITATION", "reason": "x"})
    # a non-bipartite model is refused by the executor even if the recognizer lies
    facs = rnd_bipartite(22, [0, 1], [2, 3]) + [((0, 1), [Fr(1), Fr(2), Fr(3), Fr(4)])]
    mp2, ep2 = write_uai(str(tmp_path / "m2.uai"), 4, facs); assert RZ.recognize(mp2, ep2)["kind"] == "ROUTE_LIMITATION"
    with pytest.raises(EX.Refuse):
        run_exec(mp2, ep2, str(tmp_path / "d"), plan=dict(plan, x_side=[0, 1], y_side=[2, 3]))
    # higher arity and non-binary are typed limitations
    facs = rnd_bipartite(23, [0, 1], [2]) + [((0, 1, 2), [Fr(1)] * 8)]; mp3, ep3 = write_uai(str(tmp_path / "m3.uai"), 3, facs); assert "arity" in RZ.recognize(mp3, ep3)["reason"]
    mp4, ep4 = write_uai(str(tmp_path / "m4.uai"), 2, [((0,), [Fr(1), Fr(2), Fr(3)]), ((1,), [Fr(1), Fr(1)])], card=[3, 2]); assert "non-binary" in RZ.recognize(mp4, ep4)["reason"]


def test_duplicated_factors_are_merged_with_occurrence_accounting_and_match_the_oracle(tmp_path):
    facs = rnd_bipartite(31, [0, 1], [2, 3]); facs += [facs[0], facs[-1], ((3, 0), [Fr(1, 2), Fr(1, 4), Fr(1, 8), Fr(1)])]       # duplicate unary, duplicate pair, re-oriented extra pair
    mp, ep = write_uai(str(tmp_path / "m.uai"), 4, facs); r = run_exec(mp, ep, str(tmp_path / "o"))
    assert r["structure"]["owned"]["merged_duplicate_pairs"] == 2 and r["structure"]["owned"]["merged_duplicate_unaries"] == 1 and sum(r["structure"]["owned"][k] for k in ("scalar", "unary", "pair")) == len(facs)
    assert truth_inside(r, U.read_model(mp), {})


class _Mutant(EX.NativeKernel):
    MODE = None
    def finish(self):
        Z, NX, NY, c, ok = super().finish()
        if self.MODE == "incomplete":
            return Z, NX, NY, dict(c, configs=c["configs"] - 1), False
        if self.MODE == "duplicate":
            return Z, NX, NY, dict(c, configs=c["configs"] + 1), ok
        if self.MODE == "corrupt_numerator":
            NX = list(NX); NX[0] = NX[0] * 1.01; return Z, NX, NY, c, ok
        if self.MODE == "nonfinite":
            return float("inf"), NX, NY, c, ok
        return Z, NX, NY, c, ok


@pytest.mark.parametrize("mode,needle", [("incomplete", "incomplete"), ("duplicate", "miscounted"), ("corrupt_numerator", "corrupted"), ("nonfinite", "non-finite")])
def test_executor_rejects_omitted_duplicated_corrupted_or_nonfinite_results(tmp_path, mode, needle):
    mp, ep = write_uai(str(tmp_path / "m.uai"), 5, rnd_bipartite(51, [0, 1, 2], [3, 4])); _Mutant.MODE = mode
    with pytest.raises(EX.Refuse) as e:
        run_exec(mp, ep, str(tmp_path / "o"), factory=_Mutant)
    assert e.value.kind == "REJECTED" and needle in e.value.reason


def test_altered_conversion_is_caught_by_the_exact_entry_check(tmp_path):
    mp, ep = write_uai(str(tmp_path / "m.uai"), 4, rnd_bipartite(52, [0, 1], [2, 3]))
    def bad_conv(q):
        return float(q) * (1 + 2 ** -40) if q != 0 else 0.0                                               # a double-rounded / wrong conversion
    with pytest.raises(EX.Refuse) as e:
        run_exec(mp, ep, str(tmp_path / "o"), conv=bad_conv)
    assert "violates the (1+-u) bound" in e.value.reason


# ------------------------------------------------------------------------------------------------------------ cells, publication, binding
def _cell(arm, mp, ep, out, budget="60", cfg="{}"):
    subprocess.run([PY, "-m", "bidi.cell", arm, mp, ep, out, budget, cfg], cwd=HERE, env=ENV, capture_output=True, timeout=300)
    return json.load(open(os.path.join(out, "cell.json")))


def test_cells_of_all_three_bidi_arms_certify_a_tiny_model_within_eps_of_the_oracle(tmp_path):
    ev = {4: 1}; mp, ep = write_uai(str(tmp_path / "m.uai"), 6, rnd_bipartite(61, [0, 1, 2], [3, 4, 5], zeros=0.1), ev); model = U.read_model(mp); Z, N = OR.brute(model, ev)
    for arm in ("BIDI_NATIVE_CERT", "BIDI_NATIVE_DUPLICATE_WORK", "BIDI_MPFR53_CERT"):
        out = str(tmp_path / arm); r = _cell(arm, mp, ep, out)
        assert r["status"] == "CERTIFIED", (arm, r.get("reason"), r.get("stop"))
        rows, _ = U.read_mar(os.path.join(out, "output.MAR")); assert len(rows) == 6
        for v in range(6):
            assert sum(Fr(x) for x in rows[v]) == 1 and all(abs(Fr(rows[v][s]) - N[v][s] / Z) < Fr(1, 200) for s in range(2))
        assert rows[4] == [Fr(0), Fr(1)]                                                                      # evidence row exact one-hot
        assert r["point_check"]["status"] == "POINT_VERIFIED" and r["task"]["raw_evidence_sha256"] == EX.sha_file(ep)
        if arm == "BIDI_NATIVE_DUPLICATE_WORK":
            assert r["first_pass"]["status"] == "INTERVALS_OK" and not os.path.exists(os.path.join(out, "discarded_first_pass.json"))
        if arm == "BIDI_MPFR53_CERT":
            assert "MPFR" in r["backend"]["build"]["backend"]


def test_cross_evidence_record_is_refused_at_publication_and_point_verification(tmp_path):
    """F5 analogue: a genuine record for evidence x0=0 must not publish for the x0=1 task; the point verifier must reject it; a stale record /
    MAR left in the directory must not survive into the x0=1 cell's output."""
    facs = rnd_bipartite(71, [0, 1], [2, 3]); mp, ep0 = write_uai(str(tmp_path / "m.uai"), 4, facs, {0: 0}); ep1 = str(tmp_path / "m1.evid"); open(ep1, "w").write("1 0 1\n")
    o0 = str(tmp_path / "o0"); r0 = _cell("BIDI_NATIVE_CERT", mp, ep0, o0); assert r0["status"] == "CERTIFIED"
    rec0 = json.load(open(os.path.join(o0, "checked_record.json"))); cell = {"phases_s": {}}; o2 = str(tmp_path / "o2"); os.makedirs(o2)
    assert EX.publish(o2, mp, ep1, rec0, cell) == "CHECK_FAILED" and "bound to the caller's task" in cell["reason"] and not os.path.exists(os.path.join(o2, "output.MAR"))
    op = str(tmp_path / "pc.json"); subprocess.run([PY, "-m", "adp.checker", "--verify-point", os.path.join(o0, "checked_record.json"), os.path.join(o0, "output.MAR"), mp, ep1, op], cwd=HERE, env=ENV, capture_output=True)
    assert json.load(open(op))["status"] == "POINT_REJECTED"
    o3 = str(tmp_path / "o3"); os.makedirs(o3); shutil.copy(os.path.join(o0, "checked_record.json"), o3); shutil.copy(os.path.join(o0, "output.MAR"), o3)
    r3 = _cell("BIDI_NATIVE_CERT", mp, ep1, o3); assert r3["status"] == "CERTIFIED" and r3["task"]["raw_evidence_sha256"] == EX.sha_file(ep1)
    rows, _ = U.read_mar(os.path.join(o3, "output.MAR")); assert rows[0] == [Fr(0), Fr(1)]


def test_publication_refuses_tampered_records_rows_and_malformed_numbers(tmp_path):
    mp, ep = write_uai(str(tmp_path / "m.uai"), 4, rnd_bipartite(81, [0, 1], [2, 3])); o = str(tmp_path / "o"); r = _cell("BIDI_NATIVE_CERT", mp, ep, o); assert r["status"] == "CERTIFIED"
    rec = json.load(open(os.path.join(o, "checked_record.json")))
    # (a) stale / rejected status
    bad = dict(rec, status="REJECTED"); cell = {"phases_s": {}}; assert EX.publish(str(tmp_path / "a"), mp, ep, bad, cell) == "CHECK_FAILED" if os.makedirs(str(tmp_path / "a")) is None else True
    # (b) missing row / extra row / wrong length
    bad = json.loads(json.dumps(rec)); del bad["certified_intervals"]["3"]; os.makedirs(str(tmp_path / "b")); cell = {"phases_s": {}}; assert EX.publish(str(tmp_path / "b"), mp, ep, bad, cell) == "CHECK_FAILED" and "rows" in cell["reason"]
    bad = json.loads(json.dumps(rec)); bad["certified_intervals"]["7"] = [["0", "1"], ["0", "1"]]; os.makedirs(str(tmp_path / "c")); cell = {"phases_s": {}}; assert EX.publish(str(tmp_path / "c"), mp, ep, bad, cell) == "CHECK_FAILED"
    bad = json.loads(json.dumps(rec)); bad["certified_intervals"]["1"] = bad["certified_intervals"]["1"][:1]; os.makedirs(str(tmp_path / "d")); cell = {"phases_s": {}}; assert EX.publish(str(tmp_path / "d"), mp, ep, bad, cell) == "CHECK_FAILED"
    # (c) the point verifier rejects an altered delivered MAR (a digit changed) and a malformed number
    mar = os.path.join(o, "output.MAR"); txt = open(mar).read(); toks = txt.split(); i = next(k for k, t in enumerate(toks) if "." in t); toks[i] = toks[i][:-1] + ("1" if toks[i][-1] != "1" else "2"); alt = str(tmp_path / "alt.MAR"); open(alt, "w").write(" ".join(toks) + "\n")
    op = str(tmp_path / "pc.json"); subprocess.run([PY, "-m", "adp.checker", "--verify-point", os.path.join(o, "checked_record.json"), alt, mp, ep, op], cwd=HERE, env=ENV, capture_output=True); assert json.load(open(op))["status"] == "POINT_REJECTED"
    toks[i] = "0.5x"; open(alt, "w").write(" ".join(toks) + "\n"); subprocess.run([PY, "-m", "adp.checker", "--verify-point", os.path.join(o, "checked_record.json"), alt, mp, ep, op], cwd=HERE, env=ENV, capture_output=True); assert json.load(open(op))["status"] == "POINT_REJECTED"
    # (d) a record whose intervals were corrupted on disk after publication: the delivered MAR no longer verifies against it
    rec2 = json.loads(json.dumps(rec)); rec2["certified_intervals"]["0"] = [["0.9", "0.95"], ["0.05", "0.1"]]; p2 = str(tmp_path / "rec2.json"); json.dump(rec2, open(p2, "w"))
    subprocess.run([PY, "-m", "adp.checker", "--verify-point", p2, mar, mp, ep, op], cwd=HERE, env=ENV, capture_output=True); assert json.load(open(op))["status"] == "POINT_REJECTED"


def test_deadline_inside_the_stream_is_a_typed_resource_stop_with_progress(tmp_path):
    mp, ep = write_uai(str(tmp_path / "m.uai"), 13, rnd_bipartite(91, [0, 1, 2, 3, 4, 5], list(range(6, 13))))
    r = _cell("BIDI_NATIVE_CERT", mp, ep, str(tmp_path / "o"), budget="0.0001")
    assert r["status"] in ("RESOURCE_STOP", "LATE_OUTPUT") and not os.path.exists(os.path.join(str(tmp_path / "o"), "output.MAR")) or r["status"] == "LATE_OUTPUT"
    if r["status"] == "RESOURCE_STOP":
        assert "configurations visited" in r["reason"] or "DEADLINE" in json.dumps(r.get("stop"))


def test_kernel_refuses_out_of_range_sizes():
    K = EX.NativeKernel()
    with pytest.raises(EX.Refuse):
        K.create(61, 2, 0, [1.0] * 122, [1.0] * 4, [1.0] * (61 * 2 * 4), 1.0)
    with pytest.raises(EX.Refuse):
        K.create(2, 2, 3, [1.0] * 4, [1.0] * 4, [1.0] * 16, 1.0)                                                # k > n


# ============================================================================================ review of 9 Nov 2026: F1 / F2 / K2 / timing controls
REV = os.path.join(HERE, "runs", "mdi_2026-10-28", "BIDI_NATIVE_PILOT_2026-11-09", "review_2026-11-09", "fixtures")


def _fixture(name):
    return os.path.join(REV, name + ".uai"), os.path.join(REV, name + ".evid")


@pytest.mark.skipif(not os.path.exists(REV), reason="review fixtures not present")
@pytest.mark.parametrize("arm", ["BIDI_MPFR53_CERT", "BIDI_NATIVE_CERT"])
def test_review_F1_out_of_range_sources_are_typed_limitations_not_wrong_certificates(tmp_path, arm):
    """F1(a): scalar 1e-200 x unary [3e-124, 7e-124]; exact marginal [0.3, 0.7]; the frozen MPFR arm published ~[0.5, 0.5] CERTIFIED + POINT_VERIFIED
    (binary64 narrowing into the subnormal range). F1(b): two unaries [1e-200, 1e-200]; exact Z = 4e-400 > 0; the frozen MPFR arm published
    INCONSISTENT_EVIDENCE_CERTIFIED. After the repair every binary64-returning backend must pass the exact normal-range predicate first."""
    for name, truth in (("subnormal_wrong_marginal", [Fr(3, 10), Fr(7, 10)]), ("positive_underflow", None)):
        mp, ep = _fixture(name); out = str(tmp_path / (arm + "_" + name)); r = _cell(arm, mp, ep, out)
        assert r["status"] == "ROUTE_LIMITATION" and "RANGE" in (r.get("reason") or ""), (arm, name, r.get("status"), r.get("reason"))
        assert not os.path.exists(os.path.join(out, "output.MAR")) and not os.path.exists(os.path.join(out, "checked_record.json"))
        assert r["status"] != "INCONSISTENT_EVIDENCE_CERTIFIED"
        Z, N = OR.brute(U.read_model(mp), {}); assert Z > 0                                            # the exact truth has positive mass: a false inconsistency would be wrong
    # safe-range positive control on the same arm still certifies within eps of the exact marginal
    mp, ep = _fixture("normal_control"); out = str(tmp_path / (arm + "_normal")); r = _cell(arm, mp, ep, out); assert r["status"] == "CERTIFIED", r.get("reason")
    rows, _ = U.read_mar(os.path.join(out, "output.MAR")); assert abs(Fr(rows[0][0]) - Fr(3, 10)) < Fr(1, 200) and abs(Fr(rows[0][1]) - Fr(7, 10)) < Fr(1, 200)
    # a GENUINE zero-mass model (structural: a factor without a positive entry after evidence) still proves inconsistency on this arm
    facs = [((0,), [Fr(1, 2), Fr(0)]), ((1,), [Fr(1, 4), Fr(3, 4)]), ((0, 1), [Fr(1, 8), Fr(1, 8), Fr(1, 8), Fr(1, 8)])]
    mp2, ep2 = write_uai(str(tmp_path / "z.uai"), 2, facs, {0: 1}); r = _cell(arm, mp2, ep2, str(tmp_path / (arm + "_zero"))); assert r["status"] == "INCONSISTENT_EVIDENCE_CERTIFIED"
    Z, _ = OR.brute(U.read_model(mp2), {0: 1}); assert Z == 0


def test_review_F2_explicit_empty_X_plan_with_multiple_lanes_through_validation_and_native_setup(tmp_path):
    """F2: the valid plan X = [], Y = [0, 1] (two binary unaries [1,2], [3,4], scalar 1) passed validate_structure and overflowed the native T scratch
    for k >= 1 (frozen kernel: BC aliased as T with max(1, m*lanes) = 1 entry). Repaired: lanes-wide T; exact truth Z = 21, NY_0 = (7, 14), NY_1 = (9, 12)."""
    facs = [((), [Fr(1)]), ((0,), [Fr(1), Fr(2)]), ((1,), [Fr(3), Fr(4)])]
    mp, ep = write_uai(str(tmp_path / "m.uai"), 2, facs); model = U.read_model(mp)
    for k in (1, 2, 0):
        plan = {"kind": RZ.PLAN_KIND, "x_side": [], "y_side": [0, 1]}                                   # EXPLICIT plan: the default recognizer would put the isolated variables on X
        r = run_exec(mp, ep, str(tmp_path / ("k%d" % k)), k=min(k, 2), block=1, plan=plan)
        assert r["structure"]["m"] == 0 and r["structure"]["n"] == 2 and r["kernel"]["lanes"] == (1 << min(k, 2)) and r["kernel"]["complete"]
        assert float.fromhex(r["values_hex"]["Z"]) == 21.0 and [float.fromhex(x) for x in r["values_hex"]["NY"]] == [7.0, 14.0, 9.0, 12.0] and r["values_hex"]["NX"] == []
        assert truth_inside(r, model, {})
        for v, row in r["certified_intervals"].items():
            for s, (a, b) in enumerate(row):
                assert Fr(a) <= OR.brute(model, {})[1][int(v)][s] / Fr(21) <= Fr(b)
    # empty Y (n = 0, k must be 0) and the empty model
    plan = {"kind": RZ.PLAN_KIND, "x_side": [0, 1], "y_side": []}; r = run_exec(mp, ep, str(tmp_path / "ey"), k=0, block=1, plan=plan)
    assert r["structure"]["n"] == 0 and float.fromhex(r["values_hex"]["Z"]) == 21.0 and [float.fromhex(x) for x in r["values_hex"]["NX"]] == [7.0, 14.0, 9.0, 12.0]
    K = EX.NativeKernel(); K.create(0, 0, 0, [], [], [], 2.5); assert not K.done(); assert K.step(5) == 1 and K.done()                # the empty model has ONE configuration (2^0)
    Z, NX, NY, c, ok = K.finish(); K.destroy(); assert ok and Z == 2.5 and NX == [] and NY == [] and c["configs"] == 1
    mp0 = str(tmp_path / "empty.uai"); open(mp0, "w").write("MARKOV\n0\n\n1\n0\n1 2.5\n"); open(mp0 + ".evid", "w").write("0\n")
    with pytest.raises(EX.Refuse) as e:
        EX.execute(mp0, mp0 + ".evid", {"kind": RZ.PLAN_KIND, "x_side": [], "y_side": []}, str(tmp_path / "e0"), time.monotonic() + 10, {"lanes_k": 0, "block_steps": 1})
    assert "no variables" in e.value.reason


def _closed_form_ops(m, n, k):
    K = 1 << n; L = 1 << k; P = 1
    while P < n + 1:
        P <<= 1
    d = P.bit_length() - 1
    return L * (2 * m + 1) * (P - 1) + (K - L) * (2 * m + 1) * d + K * (6 * m + 1), K * (3 * m + 1 + n - k) + L * (1 + 2 * m + 2 * (n - k) + k)


@pytest.mark.parametrize("m,n,k", [(1, 1, 0), (2, 3, 1), (3, 2, 2), (0, 2, 1), (4, 4, 3), (3, 5, 0), (22, 3, 3), (1, 0, 0)])
def test_review_K2_native_counters_equal_independent_mpfr_counts_and_closed_form(tmp_path, m, n, k):
    """The frozen kernel over-counted 7m+1 (not 6m+1) multiplications per configuration and 2L (not L) additions per top Y bit. The repaired
    counters must equal (a) the MPFR reference's independently counted operations (it increments at every arithmetic statement) and (b) the
    closed form of the source schedule including initialization and final reductions."""
    r = random.Random(100 + m * 7 + n * 3 + k); phi = [r.uniform(0.5, 1.5) for _ in range(2 * m)]; rho = [r.uniform(0.5, 1.5) for _ in range(2 * n)]; psi = [r.uniform(0.5, 1.5) for _ in range(m * n * 4)]
    K = EX.NativeKernel(); K.create(m, n, k, phi, rho, psi, 1.0)
    while not K.done():
        K.step(3)
    Zn, NXn, NYn, cn, okn = K.finish(); K.destroy()
    M = EX.MpfrKernel(); M.create(m, n, k, phi, rho, psi, 1.0)
    while not M.done():
        M.step(3)
    Zm, NXm, NYm, cm, okm = M.finish()
    assert okn and okm and cn["configs"] == cm["configs"] == (1 << n)
    assert (cn["mults"], cn["adds"]) == (cm["mults"], cm["adds"]) == _closed_form_ops(m, n, k), ((cn["mults"], cn["adds"]), (cm["mults"], cm["adds"]), _closed_form_ops(m, n, k))
    assert Zn.hex() == float(Zm).hex() and [x.hex() for x in NXn] == [float(x).hex() for x in NXm] and [x.hex() for x in NYn] == [float(x).hex() for x in NYm]


def test_review_timing_boundary_from_before_process_launch_is_recorded(tmp_path):
    """Prospective: the launcher's pre-Popen CLOCK_MONOTONIC (BIDI_LAUNCH_MONO) yields complete_response_from_launch_s >= in-process complete_response_s;
    interpreter start-up + imports before T_START are positive; both within the deadline on tiny work."""
    mp, ep = write_uai(str(tmp_path / "m.uai"), 5, rnd_bipartite(5, [0, 1, 2], [3, 4])); out = str(tmp_path / "o")
    t0 = time.monotonic(); env = dict(ENV, BIDI_LAUNCH_MONO="%.9f" % t0)
    subprocess.run([PY, "-m", "bidi.cell", "BIDI_NATIVE_CERT", mp, ep, out, "30", "{}"], cwd=HERE, env=env, capture_output=True, timeout=120); outer = time.monotonic() - t0
    r = json.load(open(os.path.join(out, "cell.json"))); assert r["status"] == "CERTIFIED"
    assert r["t_start_after_launch_s"] > 0 and r["complete_response_from_launch_s"] >= r["complete_response_s"] + r["t_start_after_launch_s"] - 1e-6
    assert r["complete_response_from_launch_s"] <= outer and r["within_deadline_from_launch"]
