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
    orig = B.Budget.__init__

    def patched(self, wall_s, limits=None, rss_fn=None, rss_limit=None, **kw):
        lim = dict(limits or {}); lim["local_mass_entries"] = 1
        orig(self, wall_s, limits=lim, rss_fn=rss_fn, rss_limit=rss_limit, **kw)
    B.Budget.__init__ = patched
    try:
        rt = PLN.solve(M.read_uai(w(TINY)), {}, wall_s=60, cap_bytes=1 << 30, plan_dir=tempfile.mkdtemp(), research_enabled=False)
    finally:
        B.Budget.__init__ = orig
    assert rt.status == "RESOURCE_STOP" and rt.budget["used"].get("local_mass_entries", 0) > 1 and not rt.intervals


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
    assert len({f.origin for f in m2.factors}) == 2
