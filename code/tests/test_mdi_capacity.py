"""Capacity pass (2 November 2026): the vectorized layout computes the same
mathematical objects as the scalar engine and both enclose the exact truth (values
are NOT promised bit-identical; 3 November correction); the exact aggregation agrees
with the sparse exact junction tree;
admission describes the schedules that execute and is decided against the
physical budget; the request object names the policy; the amendment is recorded."""
import os, sys, json, random, tempfile
HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)
from fractions import Fraction as Fr
import pytest
from mdi import (model as M, plan as P, contract as C, arith as A, sparse_jt as SJ, vec_engine as V,
                 capacity as CAP, pipeline as PLN, pricing as PR, plantype as PT, config as K, solve as S, oracle as O)
import mdi.registry  # noqa: F401

pytestmark = pytest.mark.skipif(not V.AVAILABLE, reason="numpy is not available for the vectorized layout")


def _rnd_model(n, k, zeros, seed):
    rnd = random.Random(seed)
    facs = [M.Factor(scope=(v,), card=(k,), table=[Fr(rnd.randint(1, 999), 1000) for _ in range(k)], origin=v) for v in range(n)]
    for v in range(n - 1):
        tab = [Fr(rnd.randint(1, 999), 1000) for _ in range(k * k)]
        if zeros:
            tab[rnd.randrange(k * k)] = Fr(0)
        facs.append(M.Factor(scope=(v, v + 1), card=(k, k), table=tab, origin=100 + v))
    for v in range(0, n - 3, 3):
        facs.append(M.Factor(scope=(v, v + 3), card=(k, k), table=[Fr(rnd.randint(1, 999), 1000) for _ in range(k * k)], origin=200 + v))
    return M.Model(nvars=n, card=[k] * n, factors=facs).validate()


def _plan_of(r):
    adj = P.primal_graph(r.free, r.card, r.factors)
    return P.build_plan("min_fill", P.order_min_fill(r.free, r.card, adj), r.free, r.card, r.factors)


def _run(engine_cls, pl, r, mode, p):
    eng = engine_cls(pl, r.factors, A.Ctx(p), mode=mode)
    roots = [b.idx for b in pl.bags if b.parent == -1]
    for rt in roots:
        eng.upward(rt)
    rv = [eng.root_value(rt) for rt in roots]
    home = {}
    for v in r.free:
        home.setdefault(pl.var_home[v], []).append(v)
    read = {}

    def on_cal(bag):
        for vv in home.get(bag, ()):
            read[vv] = eng.read_marginal(vv)
    for rt in roots:
        eng.downward(rt, on_calibrated=on_cal)
    return eng, rv, read


def test_vectorized_engine_agrees_with_the_scalar_engine_and_both_enclose_the_truth():
    """The vectorized layout computes the SAME mathematical objects as the scalar
    engine (same directed-rounding contexts, same precision, same depth labels,
    same support flags); its rounded VALUES are not promised bit-identical --
    numpy's object reduction order over a transposed, broadcast view differs from
    the scalar engine's flat sequential order on mixed-cardinality / reversed-scope
    bags (3 November 2026 correction: 28 of 30 such cases differed). What the
    contract needs is order-independent: every point value is a directed-rounded
    enclosure of the exact count with the stated depth, so the EXACT truth lies
    inside the published enclosure of both engines, and the two engines' point
    values differ by at most the depth-bounded rounding slack. Checked here on
    models with and without hard zeros, mixed cardinalities and reversed scopes."""
    from mdi import arith as A
    for n, k, z, seed in ((7, 2, False, 1), (9, 3, True, 2), (12, 2, True, 3), (10, 3, True, 4)):
        m = _rnd_model(n, k, z, seed)
        r = M.restrict(m, {})
        pl = _plan_of(r)
        Z, pt = O.exact_all_marginals(r)
        for mode, p in (("P", 64), ("I", 80)):
            es, rvs, rs = _run(C.Engine, pl, r, mode, p)
            ev, rvv, rvd = _run(V.VecEngine, pl, r, mode, p)
            for a, b in zip(rvs, rvv):
                assert a.depth == b.depth and bool(a.support[0]) == bool(b.support[0])
            for v in r.free:
                cs, ss, ds = rs[v]
                cv, sv, dv = rvd[v]
                assert ds == dv and list(ss) == list(sv)
                for a in range(r.card[v]):
                    if not ss[a]:
                        continue
                    if mode == "P":
                        # both are RNDD enclosures of the same exact count at the same depth: within the depth-bounded slack
                        x_s, x_v = A.exact_fr(cs[a]), A.exact_fr(cv[a])
                        assert abs(x_s - x_v) <= max(x_s, x_v) * Fr(1, 2 ** (p - 8))
                    else:
                        # two valid enclosures of the same exact count must OVERLAP
                        lo_s, hi_s = A.exact_fr(cs[a][0]), A.exact_fr(cs[a][1])
                        lo_v, hi_v = A.exact_fr(cv[a][0]), A.exact_fr(cv[a][1])
                        assert lo_v <= hi_v and lo_s <= hi_s and lo_v <= hi_s and lo_s <= hi_v
    # the END-TO-END obligation: the published enclosures of the vectorized pipeline contain the exact truth
    for n, k, z, seed in ((7, 2, False, 1), (9, 3, True, 2), (12, 2, True, 3), (10, 3, True, 4)):
        m = _rnd_model(n, k, z, seed)
        r = M.restrict(m, {})
        Z, pt = O.exact_all_marginals(r)
        res = PLN.solve(m, {}, wall_s=60, cap_bytes=1 << 30, plan_dir=tempfile.mkdtemp(), research_enabled=False)
        assert res.status.startswith("CERTIFIED")
        assert all(Fr(res.intervals[v][a][0]) <= pt[v][a] <= Fr(res.intervals[v][a][1]) for v in pt for a in range(k))


def test_vectorized_exact_aggregation_equals_the_sparse_exact_junction_tree():
    for n, k, z, seed in ((9, 3, True, 5), (12, 2, True, 6), (10, 3, False, 7)):
        m = _rnd_model(n, k, z, seed)
        r = M.restrict(m, {})
        pl = _plan_of(r)
        Z, mg, _jt = SJ.all_marginals([SJ.table_from_factor(f) for f in r.factors], r.card, entry_cap=10 ** 9, order=list(pl.order))
        vx = V.VecExact(pl, r.factors, r.card).run()
        cnt = vx.counts(r.free)
        for v in r.free:
            for a in range(r.card[v]):
                assert Fr(int(cnt.get((v, a), 0)), int(vx.Z)) == mg[v][a] / Z
        # exact marginals against the oracle too
        Zo, pt = O.exact_all_marginals(r)
        for v in r.free:
            for a in range(r.card[v]):
                assert Fr(int(cnt.get((v, a), 0)), int(vx.Z)) == pt[v][a]


def test_admission_describes_the_executing_schedules_and_the_physical_budget():
    """The forecast names the producer's saved order AND the checker's own min-fill
    plan; admission is by remaining wall and RSS cap; the refusal names the stage."""
    m = _rnd_model(14, 3, True, 8)
    r = M.restrict(m, {})
    sel = P.choose_plan(r.free, r.card, r.factors, 64, 8 << 30)
    pp = sel["chosen"][0]
    cp = CAP.checker_plan(r)
    fc = CAP.forecast_identity(pp, cp, r.factors, r.card, r.free)
    assert fc["schedules"]["producer"]["order"] == pp.name and fc["schedules"]["checker"]["order"] == "min_fill"
    assert fc["schedules"]["checker"]["work_entries"] > 0 and fc["bytes"]["peak"] > 0 and fc["exact_root_bits_bound"] > 0
    ok = CAP.admit(fc, 600, 8 << 30, 0)
    assert ok["route"] == "FEASIBLE" and ok["aggregation"] == "FEASIBLE"
    wall = CAP.admit(fc, 1e-6, 8 << 30, 0)
    assert wall["route"] == "WALL_FORECAST_EXCEEDS"
    mem = CAP.admit(fc, 600, 1, 0)
    assert mem["route"] == "RSS_FORECAST_EXCEEDS" and "GiB cap" in mem["route_reason"]
    # the aggregation can be refused while producer + checker fit: the ROUTE is admissible only
    # as the explicit shared-aggregation-only diagnostic; for the CERTIFICATE it is refused
    tight = CAP.admit(fc, fc["seconds"]["producer_and_checker"] + 1e-9, 8 << 30, 0)
    assert tight["route"] == "FEASIBLE" and tight["aggregation"] == "WALL_FORECAST_EXCEEDS", tight
    assert tight["certificate"] == "AGGREGATION_WALL_FORECAST_EXCEEDS" and "cannot satisfy the certificate" in tight["certificate_reason"]
    assert ok["certificate"] == "FEASIBLE"
    feas_c = PR.identity_checker_feasibility(pp, r, None, wall_remaining_s=fc["seconds"]["producer_and_checker"] + 1e-9, rss_cap_bytes=8 << 30)
    assert feas_c["checker"] == "CHECKER_AGGREGATION_WALL_FORECAST_EXCEEDS" and feas_c["admitted_for"] == "certificate"
    feas_d = PR.identity_checker_feasibility(pp, r, None, wall_remaining_s=fc["seconds"]["producer_and_checker"] + 1e-9, rss_cap_bytes=8 << 30,
                                             diagnostic_shared_only=True)
    assert feas_d["checker"] == "FEASIBLE" and feas_d["admitted_for"] == "diagnostic_shared_only"
    # the calibration binds the layout that executes: the scalar fallback never inherits the vectorized rates
    cal_s = CAP.calibration_for_layout("scalar")
    assert cal_s["version"].endswith("-scalar") and cal_s["us_per_entry"]["vec_P"] == CAP.CALIBRATION["us_per_entry"]["scalar_dense"]
    fc_s = CAP.forecast_identity(pp, cp, r.factors, r.card, r.free, cal=cal_s)
    assert fc_s["seconds"]["total"] > 100 * fc["seconds"]["total"] and fc_s["layout"] == "scalar"
    feas = PR.identity_checker_feasibility(pp, r, None, wall_remaining_s=600, rss_cap_bytes=8 << 30)
    assert feas["policy"] == "physical-2026-11-02" and feas["checker"] == "FEASIBLE" and feas["checker_order"] == "min_fill"
    # the exact message bit bounds are monotone up the tree and bound the measured total
    bits = CAP.exact_message_bits(cp, r.factors)
    vx = V.VecExact(cp, r.factors, r.card).run()
    assert int(vx.Z).bit_length() <= max(bits.values()) + 1


def test_shared_aggregation_only_when_the_aggregation_is_not_admitted():
    """When the producer and the interval checker fit but the physical admission
    refuses the exact aggregation, the checker reports the aggregation NOT RUN
    with the admission's reason, and the pipeline's terminal is the contract's
    VERIFIED_SHARED_AGGREGATION_ONLY, never a certificate."""
    m = _rnd_model(16, 3, True, 9)
    r = M.restrict(m, {})
    iv = S.solve(m, {}, eps=Fr(1, 100), mode="P", cap_bytes=1 << 30, deadline_s=60, run_checker=False)["intervals"]
    ok, fails, meta = S.verify_publication(m, {}, iv, eps=Fr(1, 100), deadline_s=600, cap_bytes=1 << 30)
    assert ok and meta["independent_aggregation_checked"] is True and "exact integer junction tree" in meta["independent_aggregation_scope"]
    # inject an admission that refuses only the aggregation
    orig = CAP.admit

    def refuse_aggregation(fc, wall, cap, now=0, **kw):
        out = orig(fc, wall, cap, now, **kw)
        out["aggregation"] = "RSS_FORECAST_EXCEEDS"
        out["aggregation_reason"] = "control: the exact aggregation is refused by the physical budget"
        out["certificate"] = "AGGREGATION_RSS_FORECAST_EXCEEDS"
        out["certificate_reason"] = "control: the complete certified path does not fit"
        return out
    CAP.admit = refuse_aggregation
    try:
        ok2, fails2, meta2 = S.verify_publication(m, {}, iv, eps=Fr(1, 100), deadline_s=600, cap_bytes=1 << 30)
        res = PLN.solve(m, {}, wall_s=120, cap_bytes=1 << 30, plan_dir=tempfile.mkdtemp(), research_enabled=False, diagnostic_shared_only=True)
    finally:
        CAP.admit = orig
    assert not ok2 and meta2["independent_aggregation_checked"] is False and "NOT RUN" in meta2["independent_aggregation_scope"]
    assert "control: the exact aggregation is refused" in meta2["independent_aggregation_scope"]
    assert res.status == "VERIFIED_SHARED_AGGREGATION_ONLY" and not res.intervals, (res.status, res.reason)
    assert res.partial_evidence.get("unverified_producer_rows")


def test_request_v4_names_the_capacity_policy_and_the_amendment_is_recorded():
    assert PT.REQUEST_VERSION == 4 and "capacity" in PT.REQUEST_KEYS
    pol = PT.capacity_policy()
    assert pol["policy"] == "physical-2026-11-02" and pol["calibration"] == CAP.CALIBRATION["version"] and pol["layout"] == "vectorized"
    assert len(K.AMENDMENTS) == 1 and K.AMENDMENTS[0]["date"] == "2026-11-02" and K.CAPS["local_mass_entries"] == 60_000_000_000
    assert K.CAPS["checker_contraction_space"] == 4096
    m = _rnd_model(6, 2, False, 10)
    from mdi.matrix import _write_uai
    mp = _write_uai(m)
    m = M.read_uai(mp)                        # the SAME bytes the replay will read
    d = tempfile.mkdtemp()
    res = PLN.solve(m, {}, wall_s=60, cap_bytes=1 << 30, plan_dir=d, research_enabled=False)
    assert res.status.startswith("CERTIFIED")
    rec = json.load(open(os.path.join(d, next(p["identity"] for p in res.prices if p["name"] == "identity") + ".plan.json")))
    assert rec["request"]["version"] == 4 and rec["request"]["capacity"] == pol
    # a stale policy name is refused at binding
    import copy
    from mdi import replay as RP
    bad = copy.deepcopy(rec)
    bad["request"]["capacity"]["calibration"] = "other-host"
    pb = os.path.join(d, "bad.plan.json")
    json.dump(bad, open(pb, "w"))
    rr = RP.replay(mp, "-", pb)
    assert rr["status"] == "REPLAY_REFUSED" and "capacity" in str(rr.get("reason"))
    assert RP.replay(mp, "-", os.path.join(d, next(p["identity"] for p in res.prices if p["name"] == "identity") + ".plan.json"))["status"] == "REPLAY_VERIFIED"


def test_thirteen_variable_complete_graph_is_certified_under_the_physical_policy():
    n = 13
    facs = [M.Factor(scope=(v,), card=(2,), table=[Fr(1), Fr(1) + Fr(1 + v % 5, 10)], origin=v) for v in range(n)]
    facs += [M.Factor(scope=(i, j), card=(2, 2), table=[Fr(2), Fr(1), Fr(1), Fr(2 + (i + j) % 3)], origin=100 + 13 * i + j)
             for i in range(n) for j in range(i + 1, n)]
    mg = M.Model(nvars=n, card=[2] * n, factors=facs).validate()
    rg = PLN.solve(mg, {}, wall_s=600, cap_bytes=1 << 30, plan_dir=tempfile.mkdtemp(), research_enabled=False)
    assert rg.status.startswith("CERTIFIED"), (rg.status, rg.reason)
    Z, pt = O.exact_all_marginals(M.restrict(mg, {}))
    assert all(Fr(rg.intervals[v][a][0]) <= pt[v][a] <= Fr(rg.intervals[v][a][1]) for v in pt for a in range(2))
    assert rg.checker.get("independent_aggregation_checked") is True
    assert rg.budget["used"]["local_mass_entries"] > 8192
