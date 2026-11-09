"""Conformance and adversarial controls for AGGREGATE_DP_V1 (qualification before any outcome collection).

Exact oracles: brute-force enumeration (adp.oracle). Semantic controls: every original coordinate, not only normalizers.
Adversarial: altered certificates must be REJECTED by the independent checker for the specific violated condition.
"""
from __future__ import annotations
import sys, os, json, copy, tempfile, subprocess, time
sys.set_int_max_str_digits(0)
HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__))); sys.path.insert(0, HERE)
from fractions import Fraction as Fr
import pytest
import numpy as np
from mdi import model as M, arith as A
from adp import source as SRC, oracle as O, engine as EN, publish as PB, checker as CK

PY = sys.executable


def solve_exact_check(m, ev, cfg, p=64):
    """Producer run -> (status, R, P, X, enclosures, roots)."""
    R = SRC.Reduced(m, ev); R.reduce(cfg["rules"])
    if R.zero_proof:
        return "ZERO", R, None, None, None, None
    P = EN.Program(R, cfg); X = EN.Executor(P, p, cfg); X.forward(); X.backward(); enc, roots, Emax = X.enclosures()
    return "OK", R, P, X, enc, roots


def original_rows(R, enc):
    out = {}
    for v in range(R.nvars):
        row = []
        for e in R.dec[v]:
            if e[0] == "C":
                row.append((e[1], e[1]))
            else:
                iv = enc[e[1]][R.dom[e[1]].index(e[2])]; row.append((e[3] * iv[0], e[3] * iv[1]))
        out[v] = row
    return out


CONFIGS = {"full": dict(EN.DEFAULTS), "lazy_scalar": dict(EN.DEFAULTS, batched=False), "identity_views": dict(EN.DEFAULTS, views=False), "no_memo": dict(EN.DEFAULTS, batched=False, memo=False),
           "no_rules": dict(EN.DEFAULTS, rules=[]), "sparse_everywhere": dict(EN.DEFAULTS, dense_core_cap_entries=1), "sparse_capped_to_lazy": dict(EN.DEFAULTS, dense_core_cap_entries=1, sparse_rows_cap=3),
           "tiny_cache": dict(EN.DEFAULTS, batched=False, lazy_cache_entries=2), "no_sparse": dict(EN.DEFAULTS, sparse=False)}


@pytest.mark.parametrize("name", sorted(CONFIGS))
def test_every_original_coordinate_enclosed_on_600_random_models(name):
    """Nonbinary domains, arity >= 3, zeros, constants, separable / bijection factors, duplicate scopes, evidence, components."""
    cfg = CONFIGS[name]; n_ok = 0; n_zero = 0
    for seed in range(600):
        m, ev = O.gen(seed); Z, N = O.brute(m, ev); st, R, P, X, enc, roots = solve_exact_check(m, ev, cfg)
        if Z == 0:
            if st == "ZERO":
                n_zero += 1; continue
            zp = R.scale
            for z, _ in roots.values():
                zp *= A.exact_fr(z)
            assert zp == 0; n_zero += 1; continue
        assert st == "OK"
        zp = R.scale
        for z, _ in roots.values():
            zp *= A.exact_fr(z)
        assert 0 < zp <= Z
        rows = original_rows(R, enc)
        for v in range(m.nvars):
            for s in range(m.card[v]):
                L, U = rows[v][s]; truth = N[v][s] / Z
                assert L <= truth <= U, (seed, v, s, L, truth, U)
                assert U - L < Fr(1, 10 ** 9)
        n_ok += 1
    assert n_ok > 400 and n_zero > 20


def test_disconnected_components_isolated_and_observed_variables():
    card = [2, 3, 2, 4, 2]; ev = {4: 1}
    facs = [M.Factor(scope=(0, 1), card=(2, 3), table=[Fr(x) for x in [1, 2, 3, 0, 1, 1]], origin=0), M.Factor(scope=(2,), card=(2,), table=[Fr(3), Fr(1)], origin=1), M.Factor(scope=(4,), card=(2,), table=[Fr(1), Fr(5)], origin=2)]
    m = M.Model(nvars=5, card=card, factors=facs); m.validate(); Z, N = O.brute(m, ev)
    for cfg in (CONFIGS["full"], CONFIGS["no_rules"], CONFIGS["lazy_scalar"]):
        st, R, P, X, enc, roots = solve_exact_check(m, ev, cfg); rows = original_rows(R, enc)
        for v in range(5):
            for s in range(card[v]):
                L, U = rows[v][s]; assert L <= N[v][s] / Z <= U, (v, s)
        if "quotient" in cfg["rules"]:
            assert rows[3] == [(Fr(1, 4), Fr(1, 4))] * 4        # isolated: proved uniform by the quotient rule (exact decoder)
        assert rows[4] == [(Fr(0), Fr(0)), (Fr(1), Fr(1))]       # observed: point mass


def test_equal_messages_different_derivatives_three_quarters_not_one_half():
    """phi(X,B) rows (1,2),(1,0): both messages equal 2 at unit markers; P(X=0) = 3/4, not 1/2."""
    m = M.Model(nvars=2, card=[2, 2], factors=[M.Factor(scope=(0, 1), card=(2, 2), table=[Fr(1), Fr(2), Fr(1), Fr(0)], origin=0)]); m.validate()
    for cfg in CONFIGS.values():
        st, R, P, X, enc, roots = solve_exact_check(m, {}, cfg); rows = original_rows(R, enc)
        assert rows[0][0][0] <= Fr(3, 4) <= rows[0][0][1] and rows[0][0][1] - rows[0][0][0] < Fr(1, 10 ** 12)
        assert not (rows[0][0][0] <= Fr(1, 2) <= rows[0][0][1])


def test_normalized_cpt_leaf_with_queried_child_is_not_cancelled():
    """P(C|A) normalized rows: sum_c P(c|a) lambda_c = 1 only at unit markers; the child's marginal must come out right."""
    m = M.Model(nvars=2, card=[2, 3], factors=[M.Factor(scope=(0,), card=(2,), table=[Fr(3, 10), Fr(7, 10)], origin=0), M.Factor(scope=(0, 1), card=(2, 3), table=[Fr(1, 2), Fr(1, 4), Fr(1, 4), Fr(1, 10), Fr(1, 10), Fr(8, 10)], origin=1)]); m.validate()
    Z, N = O.brute(m, {})
    for cfg in CONFIGS.values():
        st, R, P, X, enc, roots = solve_exact_check(m, {}, cfg); rows = original_rows(R, enc)
        for s in range(3):
            assert rows[1][s][0] <= N[1][s] / Z <= rows[1][s][1]


def test_zero_normalizer_is_inconsistent_evidence_not_marginals():
    m = M.Model(nvars=2, card=[2, 2], factors=[M.Factor(scope=(0, 1), card=(2, 2), table=[Fr(0), Fr(1), Fr(0), Fr(0)], origin=0), M.Factor(scope=(1,), card=(2,), table=[Fr(1), Fr(0)], origin=1)]); m.validate()
    R = SRC.Reduced(m, {}); R.reduce(SRC.ALL_RULES); assert R.zero_proof is not None
    R2 = SRC.Reduced(m, {}); R2.reduce([]); P = EN.Program(R2, CONFIGS["no_rules"]); X = EN.Executor(P, 64, CONFIGS["no_rules"]); X.forward()
    assert all(A.exact_fr(z) == 0 for z, _ in X.root_values().values())


def test_tiny_denominator_and_precision_restart():
    """A law whose normalizer is ~1e-60: 64-bit MPFR points must still enclose (wide exponent range), no silent zero."""
    tiny = Fr(1, 10 ** 60); m = M.Model(nvars=2, card=[2, 2], factors=[M.Factor(scope=(0, 1), card=(2, 2), table=[tiny, 2 * tiny, 3 * tiny, tiny], origin=0)]); m.validate(); Z, N = O.brute(m, {})
    for p in (64, 128):
        st, R, P, X, enc, roots = solve_exact_check(m, {}, CONFIGS["full"], p=p); rows = original_rows(R, enc)
        for v in range(2):
            for s in range(2):
                assert rows[v][s][0] <= N[v][s] / Z <= rows[v][s][1]


def test_quotient_with_nonuniform_decoder_weights():
    """States 1 and 2 of X have proportional rows (ratio 3): merged; decoder weights 1/4, 3/4 within the class."""
    m = M.Model(nvars=2, card=[3, 2], factors=[M.Factor(scope=(0, 1), card=(3, 2), table=[Fr(1), Fr(5), Fr(2), Fr(4), Fr(6), Fr(12)], origin=0)]); m.validate(); Z, N = O.brute(m, {})
    R = SRC.Reduced(m, {}); R.reduce(["quotient"]); assert any(s[0] == "quotient" for s in R.steps) and len(R.dom[0]) == 2
    st, R, P, X, enc, roots = solve_exact_check(m, {}, CONFIGS["full"]); rows = original_rows(R, enc)
    for s in range(3):
        assert rows[0][s][0] <= N[0][s] / Z <= rows[0][s][1]


def test_repeated_use_of_one_core_entry_accumulates_adjoints():
    """A child message consumed in a bucket with several eliminated states referencing the same core entry (via a view)."""
    m = M.Model(nvars=3, card=[3, 2, 2], factors=[M.Factor(scope=(0, 1), card=(3, 2), table=[Fr(1), Fr(2), Fr(2), Fr(4), Fr(3), Fr(1)], origin=0), M.Factor(scope=(1, 2), card=(2, 2), table=[Fr(1), Fr(3), Fr(2), Fr(2)], origin=1), M.Factor(scope=(0, 2), card=(3, 2), table=[Fr(1), Fr(1), Fr(2), Fr(2), Fr(1), Fr(5)], origin=2)]); m.validate()
    Z, N = O.brute(m, {})
    for cfg in CONFIGS.values():
        st, R, P, X, enc, roots = solve_exact_check(m, {}, cfg); rows = original_rows(R, enc)
        for v in range(3):
            for s in range(m.card[v]):
                assert rows[v][s][0] <= N[v][s] / Z <= rows[v][s][1], (v, s)


def test_publication_counterexample_width_only_insufficient():
    L = list(map(Fr, [".33", ".33", ".32"])); U = list(map(Fr, [".34", ".34", ".33"]))
    pts, rep = PB.publish_rows({0: list(zip(L, U))}, [3]); assert pts is None and rep["status"] == "CERTIFIED_WIDTH_ONLY_POINT_INFEASIBLE"
    L2 = list(map(Fr, [".33", ".33", ".328"])); U2 = list(map(Fr, [".336", ".336", ".334"]))
    pts, rep = PB.publish_rows({0: list(zip(L2, U2))}, [3]); assert pts is not None and rep["status"] == "CERTIFIED"
    p = [Fr(x) for x in pts[0]]; assert sum(p) == 1 and all(max(abs(q - l), abs(q - u)) <= Fr(1, 200) for q, l, u in zip(p, L2, U2))


# ---------------------------------------------------------------------------- the checker: acceptance and adversarial rejection
def _cell(model_dir, m, ev, cfg_json="{}", deadline=60):
    mp = os.path.join(model_dir, "m.uai"); O.write_uai(mp, m, ev); out = os.path.join(model_dir, "out")
    subprocess.run([PY, "-m", "adp.cell", mp, mp + ".evid", out, str(deadline), cfg_json], cwd=HERE, env=dict(os.environ, PYTHONPATH=HERE), check=False, capture_output=True)
    return json.load(open(os.path.join(out, "cell.json"))), out


def _decimal_model(seed):
    """random model whose values are finite decimals (so it round-trips through a UAI file)."""
    import random
    rng = random.Random(seed); n = rng.randint(2, 5); card = [rng.choice([2, 3, 4]) for _ in range(n)]; facs = []
    for j in range(rng.randint(1, n + 1)):
        k = rng.randint(1, min(3, n)); sc = tuple(rng.sample(range(n), k)); cd = tuple(card[v] for v in sc)
        tab = [Fr(rng.choice([0, 1, 2, 5, 25, 125, 4]), rng.choice([1, 4, 10, 100])) if rng.random() < 0.85 else Fr(0) for _ in range(SRC.prod(cd))]
        if all(t == 0 for t in tab):
            tab[0] = Fr(1)
        facs.append(M.Factor(scope=sc, card=cd, table=tab, origin=j))
    ev = {v: rng.randrange(card[v]) for v in range(n) if rng.random() < 0.25}
    m = M.Model(nvars=n, card=card, factors=facs); m.validate(); return m, ev


def test_cell_end_to_end_certified_against_brute_force(tmp_path):
    done = 0
    for seed in range(12):
        m, ev = _decimal_model(seed); Z, N = O.brute(m, ev); d = tmp_path / ("s%d" % seed); d.mkdir(); rec, out = _cell(str(d), m, ev)
        if Z == 0:
            assert rec["status"] in ("INCONSISTENT_EVIDENCE_CERTIFIED",), rec["status"]; continue
        assert rec["status"] == "CERTIFIED", (seed, rec["status"], rec.get("reason"), rec.get("stop"))
        from ext import uai as U
        rows, _ = U.read_mar(os.path.join(out, "output.MAR")); iv = json.load(open(os.path.join(out, "intervals.json")))["intervals"]
        for v in range(m.nvars):
            for s in range(m.card[v]):
                t = N[v][s] / Z; L, Uu = Fr(iv[v]["intervals"][s][0]), Fr(iv[v]["intervals"][s][1]); assert L <= t <= Uu; assert abs(Fr(rows[v][s]) - t) <= Fr(1, 200)
        done += 1
    assert done >= 6


def _run_checker_on(cert, mp, ep):
    with tempfile.TemporaryDirectory() as d:
        cp = os.path.join(d, "c.json"); op = os.path.join(d, "o.json"); json.dump(cert, open(cp, "w"), default=str)
        subprocess.run([PY, "-m", "adp.checker", cp, op, "60", mp, ep, "ALL"], cwd=HERE, env=dict(os.environ, PYTHONPATH=HERE), capture_output=True)
        return json.load(open(op))


def _certificate_for(tmp_path, seed=3):
    m, ev = _decimal_model(seed)
    while True:
        Z, N = O.brute(m, ev)
        if Z > 0 and len(ev) < m.nvars:
            break
        seed += 100; m, ev = _decimal_model(seed)
    d = tmp_path / ("c%d" % seed); d.mkdir(); rec, out = _cell(str(d), m, ev); assert rec["status"] == "CERTIFIED", rec
    cert = json.load(open(os.path.join(out, "certificate.json"))); return m, ev, cert, out


@pytest.fixture(scope="module")
def good(tmp_path_factory):
    return _certificate_for(tmp_path_factory.mktemp("good"))


def test_checker_accepts_the_honest_certificate(good):
    m, ev, cert, out = good; r = _run_checker_on(cert, cert["model_path"], cert["evidence_path"]); assert r["status"] == "INTERVALS_OK", r


def _mutants(cert):
    """(name, mutated certificate, expected rejection substring)"""
    c0 = cert
    def mut(fn):
        c = copy.deepcopy(c0); fn(c); return c
    outs = []
    outs.append(("missing_factor_occurrence", mut(lambda c: c["plan"]["nodes"][0]["inputs"].pop(0) if c["plan"]["nodes"][0]["inputs"] else None), "bucket inputs"))
    outs.append(("extra_duplicated_occurrence", mut(lambda c: c["plan"]["nodes"][0]["inputs"].append(c["plan"]["nodes"][0]["inputs"][0])), "bucket inputs"))
    outs.append(("wrong_source_bytes", mut(lambda c: c["source"].__setitem__("raw_model_sha256", "0" * 64)), "source"))
    outs.append(("wrong_domain_cardinality", mut(lambda c: c["reduced"]["orig_card"].__setitem__(0, c["reduced"]["orig_card"][0] + 1)), "cardinalities"))
    outs.append(("invented_fixation", mut(lambda c: c["reduced"]["steps"].insert(len([s for s in c["reduced"]["steps"] if s[0] == "pinned"]), ["exclude", int(sorted(c["reduced"]["dom"])[0]), int(c["reduced"]["dom"][sorted(c["reduced"]["dom"])[0]][0]), int(c["reduced"]["factors"][0]["fid"])])), "exclude"))
    outs.append(("evidence_version", mut(lambda c: c["reduced"]["evidence"].__setitem__(str(sorted(c["reduced"]["dom"])[0]), 0)), "evidence"))
    outs.append(("reduced_hash_forged", mut(lambda c: c["reduced"].__setitem__("reduced_hash", "f" * 64)), "reduced model"))
    # view tampering: change a class map or a ratio
    def tamper_view(c):
        for nd in c["plan"]["nodes"]:
            for w, vw in nd["views"].items():
                if len(vw["cls"]) >= 2:
                    vw["cls"][0], vw["cls"][1] = vw["cls"][1], vw["cls"][0]; return
        for k, vw in c["plan"]["source_views"].items():
            if len(vw["cls"]) >= 2:
                vw["ratio"][0] = "2/1"; return
    outs.append(("modified_response_class_map", mut(tamper_view), "view"))
    def tamper_ratio(c):
        for k, vw in c["plan"]["source_views"].items():
            vw["ratio"][0] = "7/3"; return
    outs.append(("modified_response_ratio", mut(tamper_ratio), "view"))
    def tamper_order(c):
        o = c["plan"]["order"]
        if len(o) >= 2:
            o[0], o[1] = o[1], o[0]
    outs.append(("order_not_matching_nodes", mut(tamper_order), "eliminated variable"))
    def tamper_queries(c):
        c["expected_queries"] = c["expected_queries"][:-1]
    outs.append(("caller_query_list_truncated", mut(tamper_queries), "query"))
    def tamper_const(c):
        for s in c["reduced"]["steps"]:
            if s[0] == "const":
                s[3] = "3/7"; return
        c["reduced"]["steps"].append(["const", int(c["reduced"]["factors"][0]["fid"]), "x", "1", 1])
    outs.append(("constant_fold_wrong_value", mut(tamper_const), "const"))
    return outs


def test_checker_rejects_every_mutant_for_its_specific_condition(good):
    m, ev, cert, out = good; rejected = {}
    for name, mc, needle in _mutants(cert):
        r = _run_checker_on(mc, cert["model_path"], cert["evidence_path"]); rejected[name] = (r["status"], r.get("reason"))
        assert r["status"] in ("REJECTED", "CHECKER_FAULT"), (name, r)
        if r["status"] == "REJECTED":
            assert needle.lower() in (r.get("reason") or "").lower(), (name, r.get("reason"))
    assert sum(1 for s, _ in rejected.values() if s == "REJECTED") >= 10, rejected


def test_point_verification_rejects_altered_mar(good):
    m, ev, cert, out = good; chk = [f for f in os.listdir(out) if f.startswith("checker_p") and f.endswith(".json")][0]
    mar = os.path.join(out, "output.MAR"); txt = open(mar).read().split()
    # alter one probability by 0.02 (keeping it a valid decimal): must be rejected (outside its interval / eps)
    i = next(k for k in range(3, len(txt)) if "." in txt[k] and 0.02 < float(txt[k]) < 0.98); q = Fr(txt[i]) + Fr(1, 50); txt[i] = PB.dyadic_decimal(PB.floor_grid(q, 60), 60) if False else str(float(q))
    bad = os.path.join(out, "bad.MAR"); open(bad, "w").write(" ".join(txt[:2]) + "\n" + " ".join(txt[2:]) + "\n")
    op = os.path.join(out, "pc_bad.json")
    subprocess.run([PY, "-m", "adp.checker", "--verify-point", os.path.join(out, chk), bad, cert["model_path"], cert["evidence_path"], op], cwd=HERE, env=dict(os.environ, PYTHONPATH=HERE), capture_output=True)
    r = json.load(open(op)); assert r["status"] == "POINT_REJECTED", r
    op2 = os.path.join(out, "pc_good.json")
    subprocess.run([PY, "-m", "adp.checker", "--verify-point", os.path.join(out, chk), mar, cert["model_path"], cert["evidence_path"], op2], cwd=HERE, env=dict(os.environ, PYTHONPATH=HERE), capture_output=True)
    assert json.load(open(op2))["status"] == "POINT_VERIFIED"


def test_fabricated_sparse_support_is_rejected_by_own_join():
    """The checker builds its OWN complete support; a producer cannot declare rows. Here we check the engine's sparse result equals the
    dense result on a zero-bearing model (same program, both formats) -- a forged omission would show as an enclosure miss."""
    for seed in range(40):
        m, ev = O.gen(seed); Z, N = O.brute(m, ev)
        if Z == 0 or not any(t == 0 for f in m.factors for t in f.table):
            continue
        a = solve_exact_check(m, ev, dict(EN.DEFAULTS, dense_core_cap_entries=1)); b = solve_exact_check(m, ev, dict(EN.DEFAULTS, sparse=False))
        if a[0] != "OK":
            continue
        ra = original_rows(a[1], a[4]); rb = original_rows(b[1], b[4])
        for v in range(m.nvars):
            for s in range(m.card[v]):
                t = N[v][s] / Z; assert ra[v][s][0] <= t <= ra[v][s][1] and rb[v][s][0] <= t <= rb[v][s][1]


def test_noncanonical_fixed_state_values_rejected_in_steps(good):
    m, ev, cert, out = good
    for bad in ("1", 1.0, True, [1], -1, 10 ** 9):
        c = copy.deepcopy(cert); v = int(sorted(c["reduced"]["dom"])[0]); fid = int(c["reduced"]["factors"][0]["fid"])
        c["reduced"]["steps"].insert(len([s for s in c["reduced"]["steps"] if s[0] == "pinned"]), ["exclude", v, bad, fid])
        r = _run_checker_on(c, cert["model_path"], cert["evidence_path"]); assert r["status"] in ("REJECTED", "CHECKER_FAULT"), (bad, r)


# ---------------------------------------------------------------------------- review 2026-11-08: regression controls for the four findings
REVIEW_CONFIGS = {"no_rules_no_sparse": dict(EN.DEFAULTS, rules=[], sparse=False), "no_rules_lazy": dict(EN.DEFAULTS, rules=[], batched=False),
                  "no_rules_lazy_tiny_cache": dict(EN.DEFAULTS, rules=[], batched=False, lazy_cache_entries=2), "no_rules_tiny_value_cap": dict(EN.DEFAULTS, rules=[], sparse=False, value_bytes_cap=4096),
                  "no_rules_no_memo": dict(EN.DEFAULTS, rules=[], batched=False, memo=False)}


def test_review_F2_zero_class_along_eliminated_variable_masks_values():
    """f(X=0,B=0)=1, f(X=0,B=1)=0, f(X=1,B=0)=2, f(X=1,B=1)=0: eliminating X then B, the message along B has a zero class at B=1 with
    unit ratios; the producer must return Z = 3 and P(B) = [1, 0] in every non-sparse format (was Z = 6, [1/2, 1/2])."""
    m = M.Model(nvars=2, card=[2, 2], factors=[M.Factor(scope=(0, 1), card=(2, 2), table=[Fr(1), Fr(0), Fr(2), Fr(0)], origin=0)]); m.validate(); Z, N = O.brute(m, {})
    for name, cfg in REVIEW_CONFIGS.items():
        st, R, P, X, enc, roots = solve_exact_check(m, {}, cfg); zp = R.scale
        for z, _ in roots.values():
            zp *= A.exact_fr(z)
        assert 0 < zp <= Z and Z - zp < Fr(1, 10 ** 12), (name, zp, Z)
        rows = original_rows(R, enc)
        for v in range(2):
            for s in range(2):
                assert rows[v][s][0] <= N[v][s] / Z <= rows[v][s][1], (name, v, s, rows[v][s])


@pytest.mark.parametrize("name", sorted(REVIEW_CONFIGS))
def test_review_zero_bearing_random_models_in_non_sparse_formats(name):
    """The zero-class path is reachable only with the exclude rule off and the sparse format off (or abandoned): 400 random models."""
    cfg = REVIEW_CONFIGS[name]; n_ok = 0
    for seed in range(400):
        m, ev = O.gen(seed); Z, N = O.brute(m, ev); st, R, P, X, enc, roots = solve_exact_check(m, ev, cfg)
        if Z == 0:
            if st == "OK":
                zp = R.scale
                for z, _ in roots.values():
                    zp *= A.exact_fr(z)
                assert zp == 0
            continue
        assert st == "OK"; rows = original_rows(R, enc)
        for v in range(m.nvars):
            for s in range(m.card[v]):
                L, U = rows[v][s]; t = N[v][s] / Z; assert L <= t <= U, (name, seed, v, s)
        n_ok += 1
    assert n_ok > 300


def test_review_F3_forced_lazy_400_chain_no_recursion_and_tiny_value_cap_downgrade():
    n = 400; facs = [M.Factor(scope=(i, i + 1), card=(2, 2), table=[Fr(3, 10), Fr(7, 10), Fr(3, 5), Fr(2, 5)], origin=i) for i in range(n - 1)]
    ch = M.Model(nvars=n, card=[2] * n, factors=facs); ch.validate()
    # memo of 2 entries per node = the fan-out of a binary chain: linear time. A value cap that dense cores exhaust leaves the downgraded tail
    # of the chain WITHOUT memo room, so its cost is exponential in the number of uncached nodes (allowed by the contract: eviction changes cost,
    # never the answer); the cap below admits ~388 dense cores and downgrades ~12 nodes (2^12 recomputations).
    mp = EN.mpfr_bytes(64)
    for cfg in (dict(EN.DEFAULTS, rules=[], batched=False), dict(EN.DEFAULTS, rules=[], batched=False, lazy_cache_entries=2), dict(EN.DEFAULTS, rules=[], sparse=False, value_bytes_cap=388 * 2 * mp)):
        R = SRC.Reduced(ch, {}); R.reduce(cfg["rules"]); P = EN.Program(R, cfg); X = EN.Executor(P, 64, cfg); X.forward(); X.backward(); enc, roots, _ = X.enclosures()
        for v in (0, 199, 399):
            for a in range(2):
                assert enc[v][a][1] - enc[v][a][0] < Fr(1, 10 ** 12)
        if "value_bytes_cap" in cfg and cfg["value_bytes_cap"] != EN.DEFAULTS["value_bytes_cap"]:
            assert X.c.get("downgraded_to_lazy", 0) >= 10 and X.c["peak_scratch_bytes"] <= cfg["value_bytes_cap"]
    # the SAME chain through the fresh-process cell with the checker (checker lazy path is iterative too)
    with tempfile.TemporaryDirectory() as d:
        rec, out = _cell(d, ch, {}, json.dumps({"rules": [], "batched": False}), deadline=300)
        assert rec["status"] == "CERTIFIED", (rec["status"], rec.get("reason"), rec.get("stop"))


def test_review_one_entry_memo_still_exact_on_a_short_chain():
    """memo of ONE entry per node (maximal eviction + recomputation) on a 12-variable chain: exact answer, exponential work bounded by 2^12."""
    n = 12; facs = [M.Factor(scope=(i, i + 1), card=(2, 2), table=[Fr(3, 10), Fr(7, 10), Fr(3, 5), Fr(2, 5)], origin=i) for i in range(n - 1)]
    ch = M.Model(nvars=n, card=[2] * n, factors=facs); ch.validate(); Z, N = O.brute(ch, {})
    cfg = dict(EN.DEFAULTS, rules=[], batched=False, lazy_cache_entries=1); R = SRC.Reduced(ch, {}); R.reduce([]); P = EN.Program(R, cfg); X = EN.Executor(P, 64, cfg); X.forward(); X.backward(); enc, roots, _ = X.enclosures()
    rows = original_rows(R, enc)
    for v in range(n):
        for s in range(2):
            assert rows[v][s][0] <= N[v][s] / Z <= rows[v][s][1]
    assert X.c["lazy_evictions"] > 0


def test_review_lazy_memo_and_adjoint_bytes_are_accounted():
    m, ev = O.gen(5); cfg = dict(EN.DEFAULTS, rules=[], batched=False); R = SRC.Reduced(m, ev); R.reduce([]); P = EN.Program(R, cfg); X = EN.Executor(P, 64, cfg); X.forward()
    entries = sum(len(c.lazy or {}) for c in X.cores.values() if c.fmt == "lazy"); assert entries > 0 and X.bytes_vals == entries * X.lazy_entry_bytes
    X.backward(); assert X.bytes_adj == 0 and not X.pending


def test_review_F1_point_verifier_binds_source_and_requires_full_intervals_ok_record(tmp_path):
    m1 = M.Model(nvars=1, card=[2], factors=[M.Factor(scope=(0,), card=(2,), table=[Fr(1, 4), Fr(3, 4)], origin=0)]); m1.validate()
    m2 = M.Model(nvars=1, card=[2], factors=[M.Factor(scope=(0,), card=(2,), table=[Fr(3, 4), Fr(1, 4)], origin=0)]); m2.validate()
    d1 = tmp_path / "a"; d1.mkdir(); d2 = tmp_path / "b"; d2.mkdir(); r1, o1 = _cell(str(d1), m1, {}); r2, o2 = _cell(str(d2), m2, {}); assert r1["status"] == r2["status"] == "CERTIFIED"
    chk = [f for f in os.listdir(o1) if f.startswith("checker_p") and f.endswith(".json")][0]; mp2 = os.path.join(str(d2), "m.uai"); mp1 = os.path.join(str(d1), "m.uai")
    def vp(chk_json, mar, model, tag, evid=None):
        op = str(tmp_path / ("pc_%s.json" % tag)); subprocess.run([PY, "-m", "adp.checker", "--verify-point", chk_json, mar, model, evid or (model + ".evid"), op], cwd=HERE, env=dict(os.environ, PYTHONPATH=HERE), capture_output=True); return json.load(open(op))
    r = vp(os.path.join(o1, chk), os.path.join(o1, "output.MAR"), mp2, "wrong"); assert r["status"] == "POINT_REJECTED" and "different task" in r["reason"]
    rej = json.load(open(os.path.join(o1, chk))); rej["status"] = "REJECTED"; rp = str(tmp_path / "rej.json"); json.dump(rej, open(rp, "w"))
    r = vp(rp, os.path.join(o1, "output.MAR"), mp1, "rej"); assert r["status"] == "POINT_REJECTED" and "INTERVALS_OK" in r["reason"]
    emp = json.load(open(os.path.join(o1, chk))); emp["certified_intervals"]["0"] = []; ep = str(tmp_path / "emp.json"); json.dump(emp, open(ep, "w"))
    r = vp(ep, os.path.join(o1, "output.MAR"), mp1, "emp"); assert r["status"] == "POINT_REJECTED" and "wrong length" in r["reason"]
    assert vp(os.path.join(o1, chk), os.path.join(o1, "output.MAR"), mp1, "ok")["status"] == "POINT_VERIFIED"


def test_review_step_type_validation_rejects_with_specific_reason(good):
    m, ev, cert, out = good
    for bad in ("1", 1.0, True, [1], {"a": 1}):
        c = copy.deepcopy(cert); v = int(sorted(c["reduced"]["dom"])[0]); fid = int(c["reduced"]["factors"][0]["fid"])
        c["reduced"]["steps"].insert(len([s for s in c["reduced"]["steps"] if s[0] == "pinned"]), ["exclude", v, bad, fid])
        r = _run_checker_on(c, cert["model_path"], cert["evidence_path"]); assert r["status"] == "REJECTED" and "JSON integer" in (r.get("reason") or ""), (bad, r)


def test_review2_cross_evidence_substitution_is_refused_at_checking_and_publication(tmp_path):
    """Same model, two evidence files (x=0 / x=1). A genuine, unchanged checker record for evidence x=0 must be refused by publish() for the
    x=1 task, by the point verifier for the x=1 task, and by the checker CLI when the caller names evidence x=1 for the x=0 certificate."""
    from adp import cell as CELL
    m = M.Model(nvars=2, card=[2, 2], factors=[M.Factor(scope=(0, 1), card=(2, 2), table=[Fr(1), Fr(2), Fr(3), Fr(4)], origin=0)]); m.validate()
    mp = str(tmp_path / "m.uai"); O.write_uai(mp, m, {0: 0}); ep0 = mp + ".evid"; ep1 = str(tmp_path / "m1.uai.evid"); open(ep1, "w").write("1 0 1\n")
    env = dict(os.environ, PYTHONPATH=HERE); o0 = str(tmp_path / "out0"); o1 = str(tmp_path / "out1")
    subprocess.run([PY, "-m", "adp.cell", mp, ep0, o0, "60", "{}"], cwd=HERE, env=env, capture_output=True); assert json.load(open(os.path.join(o0, "cell.json")))["status"] == "CERTIFIED"
    subprocess.run([PY, "-m", "adp.cell", mp, ep1, o1, "60", "{}"], cwd=HERE, env=env, capture_output=True); r1 = json.load(open(os.path.join(o1, "cell.json"))); assert r1["status"] == "CERTIFIED"
    from ext import uai as U
    assert [float(x) for x in U.read_mar(os.path.join(o1, "output.MAR"))[0][0]] == [0.0, 1.0]            # the x=1 task's own answer
    chk0 = json.load(open(os.path.join(o0, "checker_p64.json")))
    # (a) publication for the x=1 task with the x=0 record
    rec = {"model": mp, "evidence": ep1, "phases_s": {}, "source": SRC.canonical_source_hashes(mp, ep1)}; rec["task"] = CELL.task_of(rec, m); o2 = str(tmp_path / "out2"); os.makedirs(o2)
    st = CELL.publish(o2, m, chk0, rec, "_p64"); assert st == "CHECK_FAILED" and "bound to the caller's task" in rec["reason"] and not os.path.exists(os.path.join(o2, "output.MAR"))
    # (b) point verifier for the x=1 task with the x=0 record and the x=0 answer
    op = str(tmp_path / "pc.json"); subprocess.run([PY, "-m", "adp.checker", "--verify-point", os.path.join(o0, "checker_p64.json"), os.path.join(o0, "output.MAR"), mp, ep1, op], cwd=HERE, env=env, capture_output=True)
    r = json.load(open(op)); assert r["status"] == "POINT_REJECTED" and "different task" in r["reason"]
    # (c) checker CLI: the x=0 certificate checked against the caller's x=1 evidence
    op2 = str(tmp_path / "chk.json"); subprocess.run([PY, "-m", "adp.checker", os.path.join(o0, "certificate.json"), op2, "60", mp, ep1, "ALL"], cwd=HERE, env=env, capture_output=True)
    r = json.load(open(op2)); assert r["status"] == "REJECTED" and ("different model / evidence file" in r["reason"] or "source binding" in r["reason"])
    # (d) a stale record left in the output directory is removed before the checker runs
    o3 = str(tmp_path / "out3"); os.makedirs(o3); json.dump(chk0, open(os.path.join(o3, "checker_p64.json"), "w"))
    subprocess.run([PY, "-m", "adp.cell", mp, ep1, o3, "60", "{}"], cwd=HERE, env=env, capture_output=True); r3 = json.load(open(os.path.join(o3, "cell.json")))
    assert r3["status"] == "CERTIFIED" and [float(x) for x in U.read_mar(os.path.join(o3, "output.MAR"))[0][0]] == [0.0, 1.0] and r3["checker"]["task"]["raw_evidence_sha256"] == rec["task"]["raw_evidence_sha256"]
