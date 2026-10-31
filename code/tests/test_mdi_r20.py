"""r20: the independent proof boundary, saved-program authority, the
execution / resource contract and the request object (shipped tests)."""
import sys, os, json, copy, time, tempfile
sys.set_int_max_str_digits(0)
HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, "tests"))
from fractions import Fraction as Fr
import pytest
from mdi import (model as M, oracle as O, pipeline as PLN, replay as RP, collective as CO, marked as MK,
                 program_check as PC, plantype as PT, budget as B, solve as S, arith as A,
                 collective_route as CR, modes as MO, residual as RS, pricing as PR, plan as P, matrix as MX)
from test_mdi_research import w, mean_field, TINY

F4 = [0.1 * (k + 1) * (1 if k % 2 == 0 else -1) for k in range(4)]


def _mf4(J=0.30):
    return w(mean_field(4, J, F4))


def _solve(mp, **kw):
    d = tempfile.mkdtemp()
    res = PLN.solve(M.read_uai(mp), kw.pop("evidence", {}), wall_s=300, cap_bytes=1 << 30, plan_dir=d, **kw)
    return res, d


def _plan(res, d, name):
    p = next(x for x in res.prices if x["name"] == name)
    return os.path.join(d, p["identity"] + ".plan.json")


# ------------------------------------------------ layer 1: the proof boundary

def test_gf_sufficient_conditions_are_direct_integer_rules():
    """The checker's GF1/GF2 verifier applies the Chapter 05 sufficient
    conditions to the LOADED integers and never calls a grid constructor."""
    import inspect
    src = inspect.getsource(CO.gf_sufficient_conditions)
    # no CALL to a constructor (the docstring may name them)
    assert "gf1_grid(" not in src and "gf2_grid(" not in src and "gf3_eta(" not in src
    beta, R = Fr(1, 10), Fr(3)
    g1 = CO.gf1_grid(beta, R, Fr(1, 1000))
    assert CO.gf_sufficient_conditions(g1, beta, R) is None
    bad = dict(g1); bad["K"] = 0; bad["nodes"] = 1; bad["signed_frequencies"] = 1; bad["representatives"] = 1
    assert CO.gf_sufficient_conditions(bad, beta, R) is not None
    g2 = CO.gf2_grid(beta, R, Fr(1, 1000))
    assert CO.gf_sufficient_conditions(g2, beta, R) is None
    bad2 = dict(g2); bad2["T"] = 0; bad2["J"] = 0; bad2["nodes"] = 1; bad2["signed_frequencies"] = 1; bad2["representatives"] = 1
    msg = CO.gf_sufficient_conditions(bad2, beta, R)
    assert msg is not None and "2t" in msg
    # GF3: (1 - eta)^2 B <= (1 + eta)^2 A on the positive tolerances
    assert CO.gf3_transfer_holds(CO.gf3_eta([Fr(1, 1000)]), [Fr(1, 1000)])
    assert not CO.gf3_transfer_holds(CO.gf3_eta([Fr(1, 1000)]) / 4, [Fr(1, 1000)])


def test_checker_owns_level_zero_and_rejects_a_shared_initial_marker_swap():
    mp = "verifier/r17_triangle.uai"
    m = M.read_uai(mp)
    r = M.restrict(m, {})
    own = PC.own_level_zero(r, set(r.free))
    assert PC.verify_level_zero(own, MK.Marked.from_restricted(r, set(r.free))) is None
    plan = os.path.join(HERE, "verifier", "r17_triangle_lowrank_combined.plan.json")
    clean = RP.replay(mp, "-", plan)
    assert clean["status"] == "REPLAY_VERIFIED", clean.get("reason")
    assert sum(len(v) for v in clean["intervals"].values()) == 6
    orig = MK.Marked.from_restricted

    def swapped(r_, q, *a, **k):
        mk = orig(r_, q, *a, **k)
        for v in list(mk.queries()):
            if mk.orig_card[v] == 2:
                mk.marks[(v, 0)], mk.marks[(v, 1)] = mk.marks[(v, 1)], mk.marks[(v, 0)]
        return mk
    MK.Marked.from_restricted = swapped
    try:
        bad = RP.replay(mp, "-", plan)
    finally:
        MK.Marked.from_restricted = orig
    txt = str(bad.get("reason")) + " ".join(bad.get("failures") or [])
    assert bad["status"] == "REPLAY_REJECTED", bad.get("reason")
    assert "observable" in txt or "marker" in txt


def test_consistent_gf2_one_frequency_fault_is_refused_by_the_independent_grid_proof():
    m = MX._chain3()
    mp = MX._write_uai(m)
    Z, pt = O.exact_all_marginals(M.restrict(m, {}))
    orig = CO.gf2_grid

    def one_freq(a, R, e):
        g = orig(a, R, e)
        g.update(T=0, J=0, nodes=1, signed_frequencies=1, representatives=1)
        return g
    CO.gf2_grid = one_freq
    try:
        res, d = _solve(mp)
        plan = _plan(res, d, "mixed:lowrank_combined")
        rep = RP.replay(mp, "-", plan)
    finally:
        CO.gf2_grid = orig
    assert rep["status"] == "REPLAY_REJECTED", rep.get("reason")
    healthy = RP.replay(mp, "-", plan)
    assert healthy["status"] != "REPLAY_VERIFIED"


# ------------------------------------------- layer 2: saved-program authority

def test_strict_residual_is_constructed_explicitly_with_a_full_fit_proof():
    m = M.read_uai(_mf4(0.30))
    r = M.restrict(m, {})
    adm = CR.admit(MK.Marked.from_restricted(r, set(r.free)), A.Ctx(96), prefer="statistic")
    strict = [(c, rmk) for c, rmk in adm if c["candidate"].kind == "lowrank_rank1_forest_strict"]
    assert strict, [c["candidate"].kind for c, _ in adm]
    c, rmk = strict[0]
    pairs = sorted(tuple(f.scope) for f in rmk.factors if len(f.scope) == 2)
    assert pairs == sorted(tuple(p) for p in c["candidate"].masked)
    assert c["fit_tv"] + c["rounding_tv"] < Fr(5, 10000)
    assert c["dropped_pairs"] == [] or all(Fr(x[2]) == 0 for x in c["dropped_pairs"] if len(x) > 2)


def test_canonical_identity_keeps_each_mode_as_one_tuple():
    Q = 4
    f = {0: [Fr(-1, 8), Fr(1, 8)], 1: [Fr(-3, 8), Fr(3, 8)]}
    g = {0: [Fr(-1, 8), Fr(1, 8)], 1: [Fr(1, 4), Fr(-1, 4)]}
    base = {"evaluator": "statistic", "Q": Q, "deltas": None, "kept_factors": [], "dropped_pairs": []}
    exe = {"order": [0, 1], "precision": 96, "arithmetic": {"mode": "E"}, "checker": {"strategy": "dense_min_fill"}}
    cA = MO.ModeCandidate(signs=[1], gammas=[Fr(1, 2)], features=[f], kind="lowrank_rank1")
    cB = MO.ModeCandidate(signs=[1], gammas=[Fr(1, 2)], features=[{v: [-x for x in row] for v, row in f.items()}], kind="lowrank_rank1")
    idA, kA = CR.canonical_identity(dict(base, candidate=cA), (), executable=exe)
    idB, kB = CR.canonical_identity(dict(base, candidate=cB), (), executable=exe)
    assert [mm[:3] for mm in kA["modes"]] == [mm[:3] for mm in kB["modes"]]      # same law up to sign
    assert idA != idB                                                             # different rounded statistics
    cP = MO.ModeCandidate(signs=[1, 1], gammas=[Fr(1, 2), Fr(1, 3)], features=[f, g], kind="lowrank_combined")
    cPp = MO.ModeCandidate(signs=[1, 1], gammas=[Fr(1, 3), Fr(1, 2)], features=[g, f], kind="lowrank_combined")
    cSw = MO.ModeCandidate(signs=[1, 1], gammas=[Fr(1, 3), Fr(1, 2)], features=[f, g], kind="lowrank_combined")
    idP = CR.canonical_identity(dict(base, candidate=cP), (), executable=exe)[0]
    assert idP == CR.canonical_identity(dict(base, candidate=cPp), (), executable=exe)[0]
    assert idP != CR.canonical_identity(dict(base, candidate=cSw), (), executable=exe)[0]


def test_request_object_governs_binding_and_replay():
    mp = _mf4(0.30)
    res, d = _solve(mp, max_width=Fr(1, 10000))
    plan = _plan(res, d, res.plan["chosen"])
    base = json.load(open(plan))
    assert base["request"]["version"] == PT.REQUEST_VERSION and base["request"]["width"] == "1/10000"
    noid = copy.deepcopy(base); noid["storage_schedule"].pop("identity")
    p1 = os.path.join(d, "noid.plan.json"); json.dump(noid, open(p1, "w"))
    r1 = RP.replay(mp, "-", p1)
    assert r1["status"] == "REPLAY_REFUSED" and "identity" in r1["reason"]
    noreq = copy.deepcopy(base); noreq.pop("request")
    p2 = os.path.join(d, "noreq.plan.json"); json.dump(noreq, open(p2, "w"))
    assert RP.replay(mp, "-", p2)["status"] == "REPLAY_REFUSED"
    hi = copy.deepcopy(base); hi["numerical"]["precision"] = 8192; hi["request"]["precision"] = 8192
    if hi.get("program"):
        hi["program"]["precision"] = 8192
    p3 = os.path.join(d, "prec.plan.json"); json.dump(hi, open(p3, "w"))
    r3 = RP.replay(mp, "-", p3)
    assert r3["status"] == "REPLAY_REFUSED" and "4096" in r3["reason"]
    # the record's width governs: a different request width is refused, none replays the record's own
    assert RP.replay(mp, "-", plan, eps=Fr(1, 100))["status"] == "REPLAY_REFUSED"
    ok = RP.replay(mp, "-", plan)
    assert ok["status"] == "REPLAY_VERIFIED" and ok["request_width"] == "1/10000" and ok["request"]["width"] == "1/10000"


def test_unknown_query_is_a_named_schema_outcome():
    res = PLN.solve(M.read_uai(_mf4()), {}, queries={99}, wall_s=60, cap_bytes=1 << 30, plan_dir=tempfile.mkdtemp())
    assert res.status == "INVALID_INPUT" and "99" in res.reason


# ------------------------------------------ layer 3: execution / resource contract

def test_identity_checker_applicability_is_decided_before_admission():
    n = 13
    facs = [M.Factor(scope=(v,), card=(2,), table=[Fr(1), Fr(1) + Fr(1 + v % 5, 10)], origin=v) for v in range(n)]
    facs += [M.Factor(scope=(i, j), card=(2, 2), table=[Fr(2), Fr(1), Fr(1), Fr(2 + (i + j) % 3)], origin=100 + 13 * i + j)
             for i in range(n) for j in range(i + 1, n)]
    mg = M.Model(nvars=n, card=[2] * n, factors=facs).validate()
    t = time.time()
    rg = PLN.solve(mg, {}, wall_s=600, cap_bytes=1 << 30, plan_dir=tempfile.mkdtemp(), research_enabled=False)
    assert rg.status == "PRICE_REFUSAL" and "CHECKER_CAP_PROVED" in rg.reason and "8192" in rg.reason, rg.reason
    assert time.time() - t < 20
    assert not rg.intervals


def test_identity_runs_under_the_shared_entry_meter():
    """The identity's producer AND checker charge the one shared meter (r21):
    the pipeline forecasts both in the meter's unit and refuses a cap of one
    before work; the registered roles under a cap between the producer's and
    the producer-plus-checker's entries stop in VERIFICATION with the
    producer's entries charged; the normal cap verifies."""
    from mdi import registry as RG, law as LAW, oracle as O
    m = M.read_uai(_mf4(0.30))
    rn = PLN.solve(m, {3: 1}, wall_s=60, cap_bytes=1 << 30, plan_dir=tempfile.mkdtemp(), research_enabled=False)
    src = rn.budget["used_by_source"]
    prod = sum(v for k, v in src.items() if "producer" in k)
    chk = sum(v for k, v in src.items() if "checker" in k)
    assert rn.status.startswith("CERTIFIED") and prod > 0 and chk > 0
    fc = next(int(p["counters"]["metered_entries_forecast"]["value"]) for p in rn.prices if p["name"] == "identity")
    assert fc >= prod + chk                                  # forecast in the meter's own unit
    orig = B.Budget.__init__

    def patched(self, wall_s, limits=None, rss_fn=None, rss_limit=None, **kw):
        lim = dict(limits or {}); lim["local_mass_entries"] = 1
        orig(self, wall_s, limits=lim, rss_fn=rss_fn, rss_limit=rss_limit, **kw)
    B.Budget.__init__ = patched
    try:
        rt = PLN.solve(M.read_uai(w(TINY)), {}, wall_s=60, cap_bytes=1 << 30, plan_dir=tempfile.mkdtemp(), research_enabled=False)
    finally:
        B.Budget.__init__ = orig
    assert rt.status in ("PRICE_REFUSAL", "RESOURCE_STOP") and not rt.intervals      # refused BEFORE work
    law4 = LAW.OriginalLaw.freeze(m, {3: 1}, {0, 1, 2})
    for cap, want_stage in ((1, "producer"), (prod + chk - 1, "checker"), (10 ** 6, None)):
        bgr = B.Budget(60, limits={"local_mass_entries": cap})
        own = law4.restriction()
        ctx = {"model": law4.model, "evidence": dict(law4.evidence), "eps": Fr(1, 100) - Fr(1, 10 ** 6), "cap_bytes": 1 << 30,
               "remaining": bgr.remaining, "restricted": own.r, "queries": {0, 1, 2}, "budget": bgr, "program": None,
               "progress": lambda *a, **k: None}
        stage = "producer"
        try:
            iv = RG.pipeline_identity_executor(ctx)
            stage = "checker"
            ok, fails, meta = RG.pipeline_identity_checker(law4.model, dict(law4.evidence), iv, Fr(1, 100), deadline_s=60,
                                                           cap_bytes=1 << 30,
                                                           charge=lambda n: bgr.charge("local_mass_entries", n, "identity checker entries"))
            assert want_stage is None and ok, (cap, fails)
        except B.BudgetExceeded:
            assert stage == want_stage, (cap, stage)
            if stage == "checker":
                assert bgr.used["local_mass_entries"] > prod


def test_exhausted_deadline_is_never_renewed():
    m = M.read_uai(w(TINY))
    out = S.solve(m, {}, eps=Fr(1, 100), mode="P", cap_bytes=1 << 30, deadline_s=0.0)
    assert out["outcome"] == "RESOURCE_STOP"
    out2 = S.solve(m, {}, eps=Fr(1, 100), mode="P", cap_bytes=1 << 30, deadline_s=-3.0)
    assert out2["outcome"] == "RESOURCE_STOP"


def test_budget_clock_is_injectable_and_phases_are_charged():
    t = [100.0]
    bg = B.Budget(10.0, clock=lambda: t[0])
    bg.enter("parse")
    t[0] += 4.0
    assert abs(bg.elapsed() - 4.0) < 1e-9
    t[0] += 7.0
    with pytest.raises(B.BudgetExceeded):
        bg.check("late")


def test_transcendental_counter_is_monotone_and_counts_trig():
    import gmpy2
    snap = A.transcendental_snapshot()
    A.T.sin(gmpy2.mpfr(1))
    A.reset_transcendental_calls()          # a no-op: nothing is erased
    since = A.transcendental_since(snap)
    assert since["sin"] == 1 and since["total"] == 1


def test_replay_zero_support_terminal_says_the_plan_was_not_verified():
    mp = _mf4(0.30)
    res, d = _solve(mp)
    plan = _plan(res, d, res.plan["chosen"])
    m = M.read_uai(mp)
    z = M.Model(nvars=m.nvars, card=list(m.card), factors=list(m.factors) + [
        M.Factor(scope=(0,), card=(2,), table=[Fr(1), Fr(0)], origin=999)]).validate()
    mpz = MX._write_uai(z)
    evz = mpz + ".evid"
    open(evz, "w").write("1 0 1\n")
    rep = RP.replay(mpz, evz, plan)
    assert rep["status"] in ("REPLAY_ZERO_EVIDENCE_PROVED", "REPLAY_REFUSED")
    if rep["status"] == "REPLAY_ZERO_EVIDENCE_PROVED":
        assert rep["supplied_program_verified"] is False


def test_planning_memory_sampler_reports_unavailable_not_zero():
    from mdi import planning as PLAN
    assert PLAN._tree_rss_bytes(2 ** 22 + 12345) is None


def test_input_schema_violations_are_typed_outcomes():
    facs = [M.Factor(scope=(0,), card=(2,), table=[Fr(1), Fr(-1)], origin=0)]
    m = M.Model(nvars=1, card=[2], factors=facs)
    res = PLN.solve(m, {}, wall_s=30, cap_bytes=1 << 30, plan_dir=tempfile.mkdtemp())
    assert res.status == "INVALID_INPUT" and "negative" in res.reason
    facs = [M.Factor(scope=(0,), card=(2,), table=[Fr(1), Fr(2)], origin=-1),
            M.Factor(scope=(0,), card=(2,), table=[Fr(1), Fr(2)], origin=-1)]
    m2 = M.Model(nvars=1, card=[2], factors=facs)
    res2 = PLN.solve(m2, {}, wall_s=60, cap_bytes=1 << 30, plan_dir=tempfile.mkdtemp())
    assert res2.status.startswith("CERTIFIED"), res2.reason
    # occurrence identities live on the FROZEN law; the caller's objects are never mutated
    assert [f.origin for f in res2.law.model.factors] == [0, 1]
    assert all(f.origin == -1 for f in m2.factors)
    # the same Factor object listed twice is two occurrences: same exact law as two equal copies
    from mdi import law as LAW
    f = M.Factor(scope=(0,), card=(2,), table=[Fr(1), Fr(2)])
    la = LAW.OriginalLaw.freeze(M.Model(nvars=1, card=[2], factors=[f, f]).validate(), {}, {0})
    lb = LAW.OriginalLaw.freeze(m2, {}, {0})
    assert la.equal_law(lb) and isinstance(la.model.factors[0].table, tuple) and f.origin == -1


# ------------------------------------------------ r21: immutable law, effective request, one terminal path

def test_checker_reference_is_the_frozen_law_not_the_producers_working_input():
    """r21 (R20 review, blocking finding): a fault confined to producer
    execution rewrites the producer's WORKING unary tables after binding; the
    checker's reference is derived from the immutable frozen law, so the
    wrong publication is rejected on the named containment obligation. The
    same wrong calculation on an isolated copy is rejected too, and the frozen
    law refuses mutation outright."""
    from mdi import routes as RT, law as LAW
    mp = "verifier/r17_triangle.uai"
    m = M.read_uai(mp)
    Z, pt = O.exact_all_marginals(M.restrict(m, {}))
    res, d = _solve(mp)
    plan = _plan(res, d, "statistic:lowrank_combined")
    clean = RP.replay(mp, "-", plan)
    assert clean["status"] == "REPLAY_VERIFIED" and clean["stages"].get("checker_restriction_s") is not None
    orig = RT.execute

    def faulty(prog, r, queries, **kw):
        for f in r.factors:
            if len(f.scope) == 1:
                for i in range(len(f.table)):
                    f.table[i] = Fr(1)
        return orig(prog, r, queries, **kw)
    RT.execute = faulty
    try:
        bad = RP.replay(mp, "-", plan)
    finally:
        RT.execute = orig
    assert bad["status"] == "REPLAY_REJECTED" and "does NOT contain" in " ".join(bad.get("failures") or [])
    assert not bad.get("intervals")

    def frozen(prog, r, queries, **kw):
        r.model.factors[0].table[0] = Fr(9)            # raises: tuple table
        return orig(prog, r, queries, **kw)
    RT.execute = frozen
    try:
        fz = RP.replay(mp, "-", plan)
    finally:
        RT.execute = orig
    assert fz["status"] == "REPLAY_REJECTED" and "tuple" in str(fz.get("reason"))
    law = LAW.OriginalLaw.freeze(m, {}, set(M.restrict(m, {}).free))
    a, b = law.restriction(), law.restriction()
    a.r.factors[0].table[0] = Fr(99)
    assert b.r.factors[0].table[0] != Fr(99) and isinstance(law.model.factors[0].table, tuple)


def test_effective_request_v3_binds_limits_mode_and_exponents():
    mp = _mf4(0.30)
    d = tempfile.mkdtemp()
    res = PLN.solve(M.read_uai(mp), {}, wall_s=20, cap_bytes=1 << 30, plan_dir=d, research_enabled=False)
    plan = _plan(res, d, "identity")
    base = json.load(open(plan))
    eff = base["request"]["limits"]["effective"]
    assert eff["wall_s"] == 20.0 and eff["rss_bytes"] == (1 << 30) and base["request"]["limits"]["frozen"]["arm_wall_s"] == 600.0
    clean = RP.replay(mp, "-", plan)
    assert clean["status"] == "REPLAY_VERIFIED" and clean["budget"]["tightened"], clean["budget"]
    # a 900 s caller runs under the frozen 600 s and the ask is recorded
    big = PLN.solve(M.read_uai(mp), {}, wall_s=900, cap_bytes=1 << 30, plan_dir=tempfile.mkdtemp(), research_enabled=False)
    assert big.budget["effective_limits"]["wall_s"] == 600.0 and big.budget["requested_by_caller"]["wall_s"] == 900.0

    def mut(label, fn):
        b = copy.deepcopy(base); fn(b)
        p2 = os.path.join(d, label + ".plan.json"); json.dump(b, open(p2, "w"))
        return RP.replay(mp, "-", p2)
    assert mut("e1", lambda b: b["request"]["limits"]["effective"].__setitem__("local_mass_entries", 1))["status"] == "REPLAY_REFUSED"
    assert mut("w0", lambda b: b["request"]["limits"]["effective"].__setitem__("wall_s", 0))["status"] == "REPLAY_REFUSED"
    assert mut("b1", lambda b: b["request"]["limits"]["effective"].__setitem__("rss_bytes", 1))["status"] == "REPLAY_RESOURCE_STOP"
    assert mut("nl", lambda b: b["request"].__setitem__("limits", None))["status"] == "REPLAY_REFUSED"
    assert mut("md", lambda b: b["request"].__setitem__("arithmetic_mode", "Q"))["status"] == "REPLAY_REFUSED"
    assert mut("ex", lambda b: (b["request"].__setitem__("emin", 0), b["request"].__setitem__("emax", 0)))["status"] == "REPLAY_REFUSED"
    assert mut("af", lambda b: b["request"]["limits"]["effective"].__setitem__("wall_s", 601))["status"] == "REPLAY_REFUSED"


def test_early_proofs_past_the_wall_are_resource_outcomes_with_partial_evidence():
    class Clock:
        t = 1000.0

        def __call__(self):
            return Clock.t
    saved = B.DEFAULT_CLOCK[0]
    B.DEFAULT_CLOCK[0] = Clock()
    try:
        z = M.Model(nvars=2, card=[2, 2], factors=[M.Factor(scope=(0,), card=(2,), table=[Fr(1), Fr(0)], origin=0),
                                                   M.Factor(scope=(0, 1), card=(2, 2), table=[Fr(1), Fr(2), Fr(3), Fr(4)], origin=1)]).validate()
        orig = PLN.zero_evidence_proof

        def slow(*a, **k):
            Clock.t += 0.150
            return orig(*a, **k)
        PLN.zero_evidence_proof = slow
        try:
            rz = PLN.solve(z, {0: 1}, wall_s=0.050, cap_bytes=1 << 30, plan_dir=tempfile.mkdtemp())
        finally:
            PLN.zero_evidence_proof = orig
        assert rz.status == "RESOURCE_STOP" and rz.partial_evidence["status_before_limit_check"] == "ZERO_EVIDENCE_PROVED"
        origp = PLN.positive_evidence_proof

        def slowp(*a, **k):
            Clock.t += 0.150
            return origp(*a, **k)
        PLN.positive_evidence_proof = slowp
        try:
            rp = PLN.solve(M.read_uai(_mf4()), {0: 0, 1: 1, 2: 0, 3: 1}, wall_s=0.050, cap_bytes=1 << 30, plan_dir=tempfile.mkdtemp())
        finally:
            PLN.positive_evidence_proof = origp
        assert rp.status == "RESOURCE_STOP" and not rp.intervals and rp.partial_evidence["status_before_limit_check"] == "CERTIFIED_FALLBACK_ONLY"
    finally:
        B.DEFAULT_CLOCK[0] = saved


def test_arm_timing_is_one_clock_with_a_separate_receipt():
    from mdi import arm as ARM
    mp = _mf4(0.30)
    evp = mp + ".e0"
    open(evp, "w").write("0\n")
    rd = tempfile.mkdtemp()
    rec = ARM.run_arm("mf4", False, rd, wall=60, model_path=mp, evid_path=evp)
    saved = json.load(open(os.path.join(rd, "arm_mf4_baseline.json")))
    receipt = json.load(open(os.path.join(rd, "arm_mf4_baseline.receipt.json")))
    assert rec["outcome"].startswith("CERTIFIED") and saved["elapsed_s"] == rec["elapsed_s"] and 0 <= saved["elapsed_s"] < 60
    assert "elapsed_s_including_durable_write" not in saved and saved["receipt_path"] == "arm_mf4_baseline.receipt.json"
    assert receipt["within_wall"] is True and receipt["elapsed_s_including_durable_write"] >= saved["elapsed_s"]


# ------------------------------------------------ r22: read-only canonical law, incumbent retention, event ledger

def test_canonical_law_refuses_attribute_replacement_and_the_r21_fault_is_rejected():
    """The r21 review's fault: ordinary ATTRIBUTE replacement of factor tables
    on the canonical model reachable through the producer's Restricted. The
    canonical types are recursively read-only, so the producer's fault is a
    typed program refusal and no wrong publication is certified."""
    from mdi import routes as RT, law as LAW, preprocess as PRE
    mp = "verifier/r17_triangle.uai"
    m = M.read_uai(mp)
    res, d = _solve(mp)
    plan = _plan(res, d, "statistic:lowrank_combined")
    orig = RT.execute

    def faulty(prog, r, queries, **kw):
        for f in r.model.factors:
            if len(f.scope) == 1:
                f.table = tuple(Fr(1) for _ in f.table)
        r0 = M.restrict(r.model, r.evidence)
        simp = PRE.simplify(r0)
        return orig(prog, M.Restricted(model=r.model, evidence=r.evidence, factors=simp.factors, free=list(simp.free),
                                       card=dict(simp.card), constant=r0.constant, impossible_factor=None), queries, **kw)
    RT.execute = faulty
    try:
        bad = RP.replay(mp, "-", plan)
    finally:
        RT.execute = orig
    assert bad["status"] == "REPLAY_REJECTED" and "read-only" in str(bad.get("reason")) and not bad.get("intervals")
    assert RP.replay(mp, "-", plan)["status"] == "REPLAY_VERIFIED"
    law = LAW.OriginalLaw.freeze(m, {}, set(M.restrict(m, {}).free))
    for fn in (lambda: setattr(law.model.factors[0], "table", ()), lambda: setattr(law.model, "factors", ()),
               lambda: setattr(law.model, "card", ()), lambda: setattr(law, "model", None),
               lambda: law.model.factors.__setitem__(0, None), lambda: law.evidence.__setitem__(0, 1)):
        with pytest.raises((TypeError, AttributeError)):
            fn()
    assert law.verify_authority() is None
    # tuple-table caller factors with default duplicate ids are canonicalized like list tables
    ft = M.Factor(scope=(0,), card=(2,), table=(Fr(1), Fr(4)))
    la = LAW.OriginalLaw.freeze(M.Model(nvars=1, card=[2], factors=[ft, ft]).validate(), {}, {0})
    lb = LAW.OriginalLaw.freeze(M.Model(nvars=1, card=[2], factors=[M.Factor(scope=(0,), card=(2,), table=[Fr(1), Fr(4)]),
                                                                    M.Factor(scope=(0,), card=(2,), table=[Fr(1), Fr(4)])]).validate(), {}, {0})
    assert la.equal_law(lb) and ft.origin == -1
    r1 = PLN.solve(M.Model(nvars=1, card=[2], factors=[ft, ft]).validate(), {}, wall_s=30, cap_bytes=1 << 30, plan_dir=tempfile.mkdtemp())
    assert r1.status.startswith("CERTIFIED") and Fr(r1.intervals[0][1][0]) <= Fr(16, 17) <= Fr(r1.intervals[0][1][1])


def test_incumbent_survives_a_later_local_construction_stop_but_not_a_global_stop():
    from mdi import routes as RT
    from test_mdi_research import ring_of_blocks
    mpr = w(ring_of_blocks()[0])

    class Clock:
        t = 1000.0

        def __call__(self):
            return Clock.t
    saved = B.DEFAULT_CLOCK[0]
    orig = RT.build_scales
    fired = {"n": 0}

    def late(*a, **k):
        fired["n"] += 1
        if fired["n"] == 1:
            Clock.t += 31.0
        return orig(*a, **k)
    B.DEFAULT_CLOCK[0] = Clock()
    RT.build_scales = late
    try:
        ri = PLN.solve(M.read_uai(mpr), {}, wall_s=600, cap_bytes=1 << 30, plan_dir=tempfile.mkdtemp())
    finally:
        RT.build_scales = orig
        B.DEFAULT_CLOCK[0] = saved
    led = ri.plan["invocation_ledger"]
    assert ri.status.startswith("CERTIFIED") and ri.plan["discovery_complete"] is False
    assert led["candidates_admitted_during_discovery"] >= 1
    assert any(p["eligible"] and p["name"] != "identity" for p in ri.prices)
    assert not [s for s in ri.budget["stops"] if not str(s.get("kind", "")).startswith("phase:")]
    fired["n"] = 0

    def late_global(*a, **k):
        fired["n"] += 1
        if fired["n"] == 1:
            Clock.t += 700.0
        return orig(*a, **k)
    B.DEFAULT_CLOCK[0] = Clock()
    RT.build_scales = late_global
    try:
        rg = PLN.solve(M.read_uai(mpr), {}, wall_s=600, cap_bytes=1 << 30, plan_dir=tempfile.mkdtemp())
    finally:
        RT.build_scales = orig
        B.DEFAULT_CLOCK[0] = saved
    assert rg.status == "RESOURCE_STOP" and not rg.intervals


def test_construction_events_are_counted_once_and_closed():
    from test_mdi_research import ring_of_blocks
    mpr = w(ring_of_blocks()[0])
    res = PLN.solve(M.read_uai(mpr), {}, wall_s=400, cap_bytes=1 << 30, plan_dir=tempfile.mkdtemp())
    led = res.plan["invocation_ledger"]
    evs = led["construction_events"]
    assert evs and all(e["status"] != "running" for e in evs)
    done = [e for e in evs if e.get("construction_ops_measured")]
    uniq = sum(e["construction_ops_measured"] for e in done)
    naive = sum(e["construction_ops_measured"] * max(1, len(e["referenced_by"])) for e in done)
    assert any(len(e["referenced_by"]) > 1 for e in done) and uniq < naive
    assert led["construction_ops_measured"] == uniq
    assert all(a["construction_event"] is not None for a in led["attempts"]
               if a["kind"] == "candidate" and a["name"].startswith(("regional", "composed")))


def test_planning_cli_parses_eps_as_an_option_not_a_problem():
    from mdi import planning as PLAN
    assert PLAN.parse_cli(["RUNDIR", "Grids_11", "--eps", "1/200"]) == ("RUNDIR", ["Grids_11"], Fr(1, 200))
    with pytest.raises(SystemExit):
        PLAN.parse_cli(["RUNDIR", "Grids_11", "1/200"])
