"""Quotienting pilot (3 November 2026, overseer's decision after the accepted Promedus pair): generic
exact constraint quotienting -- binary equality / complement identification with a signed union-find
PLUS iterative forced-state propagation -- solved on the quotient with the existing identity engines and
restored to every original singleton. Controls: unequal deterministic-factor weights, complement chains,
contradictory relations, forced states, evidence, repeated factors, disconnected components, all-query
restoration, corrupted transformation declarations, the bounded / charged recognition, the dense twin
and replay."""
import os, sys, json, random, tempfile, itertools, glob
HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)
from fractions import Fraction as Fr
import pytest
from mdi import (model as M, plan as P, pipeline as PLN, oracle as O, preprocess as PRE, capacity as CAP,
                 quotient as QT, quotient_check as QC, arith as A, budget as B, program as PG, pricing as PR)
import mdi.registry  # noqa: F401


def _restricted(m, ev):
    r = M.restrict(m, ev)
    s = PRE.simplify(r)
    if s.impossible is not None:
        return None
    return M.Restricted(model=m, evidence=dict(ev), factors=s.factors, free=list(s.free), card=dict(s.card),
                        constant=r.constant, impossible_factor=None)


def _eq(a, b, w0=1, w1=1):
    return M.Factor(scope=(a, b), card=(2, 2), table=[Fr(w0), Fr(0), Fr(0), Fr(w1)], origin=1000 + 31 * a + b)


def _ne(a, b, w01=1, w10=1):
    return M.Factor(scope=(a, b), card=(2, 2), table=[Fr(0), Fr(w01), Fr(w10), Fr(0)], origin=2000 + 31 * a + b)


def _chain_model(n_extra=11, seed=0):
    """Unequal-weight equality (3 / 5), a complement chain (so 0 == 3 by transitivity), a forced unary
    that propagates through a pair factor, a ternary variable that stays, an isolated-ish variable and a
    long alternating equality / complement chain that makes the quotient's schedule much smaller."""
    r0 = random.Random(seed)
    facs = [_eq(0, 1, 3, 5), _ne(1, 2, 2, 7), _ne(2, 3),
            M.Factor(scope=(4,), card=(2,), table=[Fr(0), Fr(4)], origin=3),
            M.Factor(scope=(4, 5), card=(2, 2), table=[Fr(1), Fr(1), Fr(0), Fr(6)], origin=4),
            M.Factor(scope=(3, 6), card=(2, 3), table=[Fr(1), Fr(2), Fr(3), Fr(4), Fr(5), Fr(6)], origin=5),
            M.Factor(scope=(7,), card=(2,), table=[Fr(2), Fr(3)], origin=6),
            M.Factor(scope=(6, 8), card=(3, 2), table=[Fr(1), Fr(2), Fr(3), Fr(1), Fr(2), Fr(3)], origin=7)]
    prev = 3
    for v in range(9, 9 + n_extra):
        facs.append(_ne(prev, v, 1 + v % 3, 2) if v % 2 else _eq(prev, v, 2, 1 + v % 3))
        prev = v
    n = 9 + n_extra
    return M.Model(nvars=n, card=[2, 2, 2, 2, 2, 2, 3, 2, 2] + [2] * n_extra, factors=facs).validate()


def _solve_q(m, ev, **kw):
    return PLN.solve(m, ev, wall_s=120, cap_bytes=1 << 30, plan_dir=tempfile.mkdtemp(), research_enabled=False, quotient_enabled=True, **kw)


def _contained(res, m, ev):
    Z, pt = O.exact_all_marginals(M.restrict(m, ev))
    return all(Fr(res.intervals[v][a][0]) <= pt[v][a] <= Fr(res.intervals[v][a][1]) for v in pt for a in range(len(pt[v])))


def test_recognition_derives_exactly_the_implied_relations_and_both_builders_preserve_z_and_every_marginal():
    """Unequal deterministic weights (3 / 5 on an equality), a complement chain (0 == 3 through two
    complements), a forced unary that propagates, a repeated factor OBJECT (multiplicity two), evidence
    on a related variable, a disconnected component, a ternary variable, an isolated variable: the
    producer's recognition and the checker's re-derivation agree, every declared relation holds on every
    positive assignment (brute force), both quotient builders agree, Z is preserved exactly and every
    restored original marginal equals the oracle's."""
    base = _chain_model(4)
    rep = M.Model(nvars=base.nvars, card=base.card, factors=list(base.factors) + [base.factors[0]]).validate()      # repeated object
    disc = M.Model(nvars=base.nvars + 3, card=list(base.card) + [2, 2, 2],
                   factors=list(base.factors) + [_eq(base.nvars, base.nvars + 1, 2, 9), _ne(base.nvars + 1, base.nvars + 2)]).validate()
    for m, ev in ((base, {}), (base, {3: 1}), (base, {6: 2}), (rep, {}), (disc, {}), (disc, {base.nvars: 0})):
        r = _restricted(m, ev)
        assert r is not None
        decl = QT.recognize(r.factors, r.free, r.card)
        cl = QC.rederive(r.factors, r.free, r.card)
        assert QC.verify_declaration(cl, decl, r.free, r.card) == []
        assert QT.eliminated(decl) > 0
        # every declared relation holds on every positive complete assignment (brute force)
        fixed = {int(v): s for v, s in decl["fixed"].items()}
        merged = {int(v): (a[0], a[1]) for v, a in decl["merged"].items()}
        free = sorted(r.free)
        n_pos = 0
        for combo in itertools.product(*[range(r.card[v]) for v in free]):
            a = dict(zip(free, combo))
            w = Fr(1)
            for f in r.factors:
                st = f.strides()
                w *= f.table[sum(a[v] * st[k] for k, v in enumerate(f.scope))]
                if w == 0:
                    break
            if w == 0:
                continue
            n_pos += 1
            assert all(a[v] == s for v, s in fixed.items())
            assert all(a[v] == (a[rt] ^ pr) for v, (rt, pr) in merged.items())
        assert n_pos > 0
        rq = QT.build_quotient(r, decl)
        rq2 = QC.build_quotient(r, decl)
        assert [(f.scope, [str(x) for x in f.table]) for f in rq.factors] == [(f.scope, [str(x) for x in f.table]) for f in rq2.factors]
        assert rq.constant == rq2.constant
        Z, pt = O.exact_all_marginals(r)
        Zq, ptq = O.exact_all_marginals(rq)
        assert Zq * rq.constant / r.constant == Z                      # the fully determined factors' scalars are in the constant
        iv = QT.restore({v: [(ptq[v][a], ptq[v][a]) for a in range(rq.card[v])] for v in rq.free}, decl, r.free, r.card)
        assert all(iv[v][a][0] == pt[v][a] for v in r.free for a in range(r.card[v]))
        assert QC.check_restoration({v: [(Fr(lo), Fr(hi)) for lo, hi in iv[v]] for v in iv}, decl, r.free, r.card) == []


def test_contradictory_relations_and_forced_contradictions_are_zero_evidence_never_a_certificate():
    """a == b and a != b; a forced state against an equality partner's forced state; a factor zero at the
    forced assignment: recognition reports a contradiction in BOTH implementations and the pipeline (with
    the quotient route enabled) ends ZERO_EVIDENCE_PROVED through its original-model proof, publishing
    nothing."""
    cases = [M.Model(nvars=3, card=[2, 2, 2], factors=[_eq(0, 1), _ne(0, 1), M.Factor(scope=(2,), card=(2,), table=[Fr(1), Fr(2)], origin=9)]).validate(),
             M.Model(nvars=3, card=[2, 2, 2], factors=[_eq(0, 1), M.Factor(scope=(0,), card=(2,), table=[Fr(0), Fr(1)], origin=8),
                                                       M.Factor(scope=(1,), card=(2,), table=[Fr(1), Fr(0)], origin=9), M.Factor(scope=(2,), card=(2,), table=[Fr(1), Fr(2)], origin=10)]).validate(),
             M.Model(nvars=3, card=[2, 2, 2], factors=[_ne(0, 1), _ne(1, 2), _ne(0, 2)]).validate()]
    for m in cases:
        r = _restricted(m, {})
        if r is not None:
            with pytest.raises(QT.Contradiction):
                QT.recognize(r.factors, r.free, r.card)
            with pytest.raises(A.NumericalRefusal):
                QC.rederive(r.factors, r.free, r.card)
        res = _solve_q(m, {})
        assert res.status == "ZERO_EVIDENCE_PROVED" and not res.intervals, (res.status, res.reason)


def test_pipeline_certifies_on_the_quotient_restores_all_queries_and_labels_the_quotient():
    """Through the public pipeline with the quotient route enabled: the program carries the quotient
    block; the executor runs the identity on the quotient and restores every original row; the checker
    re-derives the closure, rebuilds the quotient itself, checks every restored row exactly and runs its
    numerical verification on the quotient; the saved bounds cover the meters; truth containment on every
    original coordinate; the dense twin certifies the same truth with a different executable identity."""
    m = _chain_model(11)
    for ev in ({}, {3: 1}, {6: 2}):
        res = _solve_q(m, ev)
        assert res.status == "CERTIFIED_FALLBACK_ONLY", (ev, res.status, res.reason)
        pr = next(p for p in res.prices if p["name"] == "identity")
        c = pr["counters"]
        assert int(c["quotient_merged_variables"]["value"]) + int(c["quotient_fixed_variables"]["value"]) > 0
        assert int(c["quotient_schedule_rows"]["value"]) * QT.MIN_REDUCTION_RATIO <= int(c["quotient_dense_schedule_rows"]["value"])
        ex = res.plan["executed"]
        assert ex["quotient"]["free"] == int(c["quotient_free_variables"]["value"])
        src = res.budget["used_by_source"]
        assert any("quotient recognition" in k for k in src), src
        assert int(c["producer_metered_entries"]["value"]) >= sum(v for k, v in src.items() if "producer" in k)
        assert int(c["checker_metered_entries"]["value"]) >= sum(v for k, v in src.items() if "checker" in k)
        ck = res.checker
        assert ck["quotient_rederived"]["declared_matches"] is True and ck["quotient_rederived"]["entries_scanned"] > 0
        assert ck["independent_aggregation_checked"] is True
        assert ck["coordinates_checked"] == sum(m.card[v] for v in range(m.nvars))
        assert set(res.intervals) == set(range(m.nvars)) and all(len(res.intervals[v]) == m.card[v] for v in range(m.nvars))
        assert _contained(res, m, ev)
    d = tempfile.mkdtemp()
    resq = PLN.solve(m, {}, wall_s=120, cap_bytes=1 << 30, plan_dir=d, research_enabled=False, quotient_enabled=True)
    recq = json.load(open(glob.glob(d + "/*.plan.json")[0]))
    PG.validate_program(json.loads(json.dumps(recq["program"])))
    d2 = tempfile.mkdtemp()
    dense = PLN.solve(m, {}, wall_s=120, cap_bytes=1 << 30, plan_dir=d2, research_enabled=False)
    assert dense.status == "CERTIFIED_FALLBACK_ONLY" and _contained(dense, m, {})
    recd = json.load(open(glob.glob(d2 + "/*.plan.json")[0]))
    assert "quotient" not in recd["program"] and recd["storage_schedule"]["identity"] != recq["storage_schedule"]["identity"]
    assert not any(x.get("name") == "identity+quotient" for x in dense.rejected)
    assert not any("quotient recognition" in k for k in dense.budget["used_by_source"])


def test_corrupted_transformation_declarations_are_refused_by_the_checker():
    """A declaration with a relation the original factors do not imply, a wrong parity, a wrong forced
    state, or a restoration that does not match the representative: the checker's re-derivation refuses
    each (NUMERICAL_REFUSAL, nothing published); the parser refuses malformed blocks; replay verifies the
    clean record and refuses a tampered digest."""
    m = _chain_model(11)
    r = _restricted(m, {})
    decl = QT.recognize(r.factors, r.free, r.card)
    cl = QC.rederive(r.factors, r.free, r.card)
    assert QC.verify_declaration(cl, decl, r.free, r.card) == []
    # (a) an undeclared-but-true relation omitted is FINE (incomplete quotient is still exact) ...
    partial = json.loads(json.dumps(decl)); partial["merged"].pop("19"); partial["n_free"] += 1
    partial["digest"] = QT._digest({int(k): v for k, v in partial["fixed"].items()}, {int(k): tuple(v) for k, v in partial["merged"].items()})
    assert QC.verify_declaration(cl, partial, r.free, r.card) == []
    # ... but a relation the factors do NOT imply, a wrong parity, a wrong forced state are refused
    bad1 = json.loads(json.dumps(decl)); bad1["merged"]["7"] = [0, 0]           # 7 is unrelated to 0
    bad2 = json.loads(json.dumps(decl)); bad2["merged"]["1"] = [0, 1]           # 1 == 0, not complement
    bad3 = json.loads(json.dumps(decl)); bad3["fixed"]["4"] = 0                 # 4 is forced to 1
    for bad in (bad1, bad2, bad3):
        bad["digest"] = QT._digest({int(k): v for k, v in bad["fixed"].items()}, {int(k): tuple(v) for k, v in bad["merged"].items()})
        assert QC.verify_declaration(cl, bad, r.free, r.card), bad
    # through the pipeline: corrupt the producer's recognizer so it DECLARES a relation the factors do not
    # imply (7 is independent of 0, with unary weights 2 / 3): the quotient keeps positive support, the
    # producer would certify a WRONG marginal for 7 and the correlated 0, and the checker's re-derivation
    # refuses the declaration before any numerical check
    orig = QT.recognize

    def unimplied(factors, free, card, **kw):
        d = orig(factors, free, card, **kw)
        d["merged"]["7"] = [0, 0]
        d["n_free"] -= 1
        d["digest"] = QT._digest({int(k): v for k, v in d["fixed"].items()}, {int(k): tuple(v) for k, v in d["merged"].items()})
        return d
    QT.recognize = unimplied
    try:
        QT._RECOGNITION_CACHE.clear()
        bad = _solve_q(m, {})
    finally:
        QT.recognize = orig
        QT._RECOGNITION_CACHE.clear()
    assert bad.status == "NUMERICAL_REFUSAL" and not bad.intervals, (bad.status, bad.reason)
    fails = " ".join(str(f) for f in (bad.checker or {}).get("failures", [])) + str(bad.reason)
    assert "not implied by the original factors" in fails and "not derivable" in fails, fails
    # a wrong PARITY on an equality collapses the quotient's support: the producer's zero-support claim is
    # refuted by the independent original-model proof and nothing is certified or published
    def wrong_parity(factors, free, card, **kw):
        d = orig(factors, free, card, **kw)
        for v, (rt, pr) in list(d["merged"].items()):
            d["merged"][v] = [rt, 1 - pr]
            break
        d["digest"] = QT._digest({int(k): v for k, v in d["fixed"].items()}, {int(k): tuple(v) for k, v in d["merged"].items()})
        return d
    QT.recognize = wrong_parity
    try:
        QT._RECOGNITION_CACHE.clear()
        bad_p = _solve_q(m, {})
    finally:
        QT.recognize = orig
        QT._RECOGNITION_CACHE.clear()
    assert bad_p.status in ("NUMERICAL_REFUSAL", "ZERO_SUPPORT_UNCHECKED") and not bad_p.intervals, (bad_p.status, bad_p.reason)
    # a corrupted RESTORATION (the producer publishes a merged row without the parity permutation) is refused exactly
    orig_restore = QT.restore

    def bad_restore(iv_q, decl, r_free, card):
        out = orig_restore(iv_q, decl, r_free, card)
        for v, a in decl["merged"].items():
            if int(a[1]) == 1:
                out[int(v)] = list(reversed(out[int(v)]))        # drops the parity on ONE complemented variable
                break
        return out
    QT.restore = bad_restore
    try:
        bad2 = _solve_q(m, {})
    finally:
        QT.restore = orig_restore
    assert bad2.status == "NUMERICAL_REFUSAL" and "restoration" in str(bad2.reason) + " ".join(str(f) for f in (bad2.checker or {}).get("failures", [])), bad2.reason
    # the parser
    d = tempfile.mkdtemp()
    from mdi.matrix import _write_uai
    mp = _write_uai(m)
    mm = M.read_uai(mp)
    res = PLN.solve(mm, {}, wall_s=120, cap_bytes=1 << 30, plan_dir=d, research_enabled=False, quotient_enabled=True)
    assert res.status == "CERTIFIED_FALLBACK_ONLY"
    p = glob.glob(d + "/*.plan.json")[0]
    rec = json.load(open(p))
    good = json.loads(json.dumps(rec["program"]))
    PG.validate_program(good)
    for mut in (lambda q: q["quotient"].__setitem__("extra", 1), lambda q: q["quotient"]["merged"].__setitem__("0", [0, 0]),
                lambda q: q["quotient"]["merged"].__setitem__("3", [0, 2]), lambda q: q.__setitem__("kind", "regional")):
        bad = json.loads(json.dumps(good)); mut(bad)
        with pytest.raises(PG.ProgramError):
            PG.validate_program(bad)
    from mdi import replay as RP
    rr = RP.replay(mp, "-", p)
    assert rr["status"] == "REPLAY_VERIFIED", rr.get("reason")
    rec2 = json.loads(json.dumps(rec)); rec2["program"]["quotient"]["digest"] = "0" * 64
    p2 = os.path.join(d, "tampered.plan.json"); json.dump(rec2, open(p2, "w"))
    assert RP.replay(mp, "-", p2)["status"] != "REPLAY_VERIFIED"


def test_recognition_is_bounded_and_an_unsuccessful_attempt_is_charged_and_falls_back():
    """A strictly positive law (nothing to quotient) -> QUOTIENT_NOT_ADMITTED with the recognition
    charged and the dense identity certified; a law whose quotient does not reach the twofold schedule
    reduction -> QUOTIENT_NOT_ADMITTED with the ratio recorded and charged; a wall cap of zero stops the
    recognition (and the checker's re-derivation) as a typed error; the recognition reaches its fixpoint
    in at most n_free + 2 passes."""
    pos = M.Model(nvars=6, card=[2] * 6, factors=[M.Factor(scope=(v, v + 1), card=(2, 2), table=[Fr(1), Fr(2), Fr(3), Fr(4)], origin=v) for v in range(5)]).validate()
    res = _solve_q(pos, {})
    assert res.status == "CERTIFIED_FALLBACK_ONLY" and _contained(res, pos, {})
    rj = [x for x in res.rejected if x.get("name") == "identity+quotient"]
    assert rj and rj[0]["typed"] == "QUOTIENT_NOT_ADMITTED" and "no forced state" in rj[0]["reason"]
    assert any("quotient recognition" in k for k in res.budget["used_by_source"])
    assert res.plan["executed"].get("quotient") is None
    # one forced variable among many free ones: eliminated > 0 but the schedule shrinks by less than 2x
    facs = [M.Factor(scope=(v, v + 1), card=(2, 2), table=[Fr(1), Fr(2), Fr(3), Fr(4)], origin=v) for v in range(9)]
    facs.append(M.Factor(scope=(9,), card=(2,), table=[Fr(0), Fr(1)], origin=99))
    small = M.Model(nvars=10, card=[2] * 10, factors=facs).validate()
    res2 = _solve_q(small, {})
    assert res2.status == "CERTIFIED_FALLBACK_ONLY" and _contained(res2, small, {})
    rj2 = [x for x in res2.rejected if x.get("name") == "identity+quotient"]
    assert rj2 and rj2[0]["typed"] == "QUOTIENT_NOT_ADMITTED" and rj2[0]["quotient_price"]["reduction_ratio"] < QT.MIN_REDUCTION_RATIO
    assert rj2[0]["quotient_price"]["eliminated"] == {"fixed": 1, "merged": 0}
    # caps
    m = _chain_model(11)
    r = _restricted(m, {})
    with pytest.raises(QT.QuotientError):
        QT.recognize(r.factors, r.free, r.card, wall_cap_s=0.0)
    with pytest.raises(QT.QuotientError):
        QC.rederive(r.factors, r.free, r.card, wall_cap_s=0.0)
    decl = QT.recognize(r.factors, r.free, r.card)
    assert decl["recognition"]["passes"] <= len(r.free) + 2
    charged = []
    QT.recognize(r.factors, r.free, r.card, charge=charged.append)
    assert sum(charged) == decl["recognition"]["entries_scanned"] == sum(f.size() for f in r.factors) * decl["recognition"]["passes"]


def test_checker_reschedules_every_member_of_a_merged_class_under_any_factor_order_and_both_paths_honour_the_deadline():
    """(pilot review) Three equality factors imply x0 = x1 = x2 = x3 and a factor over (x0, x3, x4) then
    forces x4 = 0. The checker re-queued only the two merge arguments, so under a factor order whose last
    merge touches neither x0 nor x3 the forced state was missed and a CORRECT quotient was rejected
    (NUMERICAL_REFUSAL where the baseline certified ten coordinates). Now every member of the merged
    classes reschedules its factors and a confirming full pass closes the fixpoint: all factor orders
    agree with the producer, the pipeline certifies on the quotient with the truth contained, and the
    checker's scan stays within its priced bound. A virtual clock whose last read is past the cap shows
    the FINAL deadline check in both recognition paths."""
    ind = [Fr(0)] * 8
    for a in range(2):
        for b in range(2):
            for c in range(2):
                if c == (1 if a != b else 0):
                    ind[a * 4 + b * 2 + c] = Fr(1 + a + 2 * b)
    f_ind = M.Factor(scope=(0, 3, 4), card=(2, 2, 2), table=ind, origin=7)
    parts = {"e01": _eq(0, 1, 2, 3), "e23": _eq(2, 3, 1, 5), "e12": _eq(1, 2), "ind": f_ind,
             "u4": M.Factor(scope=(4,), card=(2,), table=[Fr(1), Fr(1)], origin=8)}
    names = list(parts)
    orders = list(itertools.permutations(names))
    random.Random(3).shuffle(orders)
    for order in orders[:24] + [("e12", "e23", "e01", "ind", "u4")]:
        m = M.Model(nvars=5, card=[2] * 5, factors=[parts[k] for k in order]).validate()
        r = _restricted(m, {})
        decl = QT.recognize(r.factors, r.free, r.card)
        assert decl["fixed"] == {"4": 0} and set(decl["merged"]) == {"1", "2", "3"}
        cl = QC.rederive(r.factors, r.free, r.card)
        assert QC.verify_declaration(cl, decl, r.free, r.card) == [], order
        _p, chk_bound = PR._quotient_scan_bounds(r.factors, len(r.free))
        assert cl.scanned <= chk_bound, (cl.scanned, chk_bound)
    m = M.Model(nvars=5, card=[2] * 5, factors=[parts[k] for k in ("e12", "e23", "e01", "ind", "u4")]).validate()
    res = _solve_q(m, {})
    assert res.status == "CERTIFIED_FALLBACK_ONLY", (res.status, res.reason)
    assert res.plan["executed"]["quotient"]["fixed"] == 1 and res.plan["executed"]["quotient"]["merged"] == 3
    assert _contained(res, m, {}) and sum(len(v) for v in res.intervals.values()) == 10
    # the final deadline check in both paths (virtual clock: every read 0.0 but the last, which is 1.0)
    import mdi.quotient as QTm, mdi.quotient_check as QCm
    r = _restricted(_chain_model(11), {})
    for mod, fn in ((QTm, lambda: QT.recognize(r.factors, r.free, r.card, wall_cap_s=0.5)),
                    (QCm, lambda: QC.rederive(r.factors, r.free, r.card, wall_cap_s=0.5))):
        orig = mod.time.monotonic
        probe = []
        mod.time.monotonic = lambda: probe.append(1) or 0.0
        try:
            fn()
        finally:
            mod.time.monotonic = orig
        n = len(probe)
        reads = []
        mod.time.monotonic = lambda: reads.append(1) or (1.0 if len(reads) >= n else 0.0)
        try:
            with pytest.raises(QT.QuotientError) as e:
                fn()
            assert "at completion" in str(e.value) or "exceeded" in str(e.value)
        finally:
            mod.time.monotonic = orig
