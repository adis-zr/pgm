"""Backend review controls (3 November 2026): structural independence of the vectorized
checker on the ACTUAL executing path, the integer-scaling authority, deadline / RSS
enforcement inside whole-array operations, calibration bound to the executing layout,
and the certificate-versus-diagnostic admission."""
import os, sys, json, random, tempfile, time
HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)
from fractions import Fraction as Fr
import pytest
from mdi import (model as M, plan as P, solve as S, pipeline as PLN, vec_engine as V, capacity as CAP,
                 pricing as PR, preprocess as PRE, oracle as O, budget as B)
import mdi.registry  # noqa: F401

pytestmark = pytest.mark.skipif(not V.AVAILABLE, reason="numpy is not available for the vectorized layout")


def _model(n=14, k=3, seed=21):
    rnd = random.Random(seed)
    facs = [M.Factor(scope=(v,), card=(k,), table=[Fr(rnd.randint(1, 999), 1000) for _ in range(k)], origin=v) for v in range(n)]
    for v in range(n - 1):
        tab = [Fr(rnd.randint(1, 999), 1000) for _ in range(k * k)]
        tab[rnd.randrange(k * k)] = Fr(0)
        facs.append(M.Factor(scope=(v, v + 1), card=(k, k), table=tab, origin=100 + v))
    for v in range(0, n - 3, 3):
        facs.append(M.Factor(scope=(v, v + 3), card=(k, k), table=[Fr(rnd.randint(1, 999), 1000) for _ in range(k * k)], origin=200 + v))
    return M.Model(nvars=n, card=[k] * n, factors=facs).validate()


def test_vectorized_path_catches_producer_corruption_and_exact_corruption_both_ways():
    """The pipeline's producer AND interval checker run `engine_class()` (the
    vectorized layout). A readout corruption injected into that class -- affecting
    both -- is caught only by the independent exact aggregation (VecExact); a
    corruption injected into VecExact's readout is caught by the interval
    checker's containment. The clean counterpart certifies."""
    m = _model()
    E = S.engine_class()
    assert E is V.VecEngine
    clean = PLN.solve(m, {}, wall_s=120, cap_bytes=1 << 30, plan_dir=tempfile.mkdtemp(), research_enabled=False)
    assert clean.status.startswith("CERTIFIED") and "exact integer junction tree" in clean.checker["independent_aggregation_scope"]
    orig = E.read_marginal

    def faulty(self, var):
        counts, seen, depth = orig(self, var)
        if var == 0 and seen[0]:
            counts[0] = counts[0] * 3 if self.mode == "P" else (counts[0][0] * 3, counts[0][1] * 3)
        return counts, seen, depth
    E.read_marginal = faulty
    try:
        r = PLN.solve(m, {}, wall_s=120, cap_bytes=1 << 30, plan_dir=tempfile.mkdtemp(), research_enabled=False)
    finally:
        E.read_marginal = orig
    assert r.status == "NUMERICAL_REFUSAL" and not r.intervals
    # the pipeline records the checker's failures (truncated to 200 characters each); the
    # refusal names variable 0 state 0, the corrupted coordinate
    assert any("var': 0" in str(f) and "state': 0" in str(f) for f in r.checker["failures"]), r.checker["failures"][:2]
    origc = V.VecExact.counts

    def badcounts(self, free):
        c = origc(self, free)
        for a in range(3):
            if (1, a) in c:
                c[(1, a)] = c[(1, a)] * 2
        return c
    V.VecExact.counts = badcounts
    try:
        r2 = PLN.solve(m, {}, wall_s=120, cap_bytes=1 << 30, plan_dir=tempfile.mkdtemp(), research_enabled=False)
    finally:
        V.VecExact.counts = origc
    assert r2.status == "NUMERICAL_REFUSAL" and not r2.intervals
    assert any("var': 1" in str(f) for f in r2.checker["failures"])


def test_integer_scaling_preserves_every_conditional_marginal_and_factor_multiplicity():
    """D_f = lcm of f's denominators clears them; replacing f by D_f f multiplies every
    configuration's weight by the same positive constant, which cancels from every
    marginal; hard zeros stay zero; a factor listed twice is scaled twice. Checked
    against the exact oracle on models with repeated factor objects and evidence."""
    rnd = random.Random(5)
    k = 3
    shared = M.Factor(scope=(1, 2), card=(k, k), table=[Fr(rnd.randint(1, 99), 7 * 11) for _ in range(k * k)], origin=50)
    facs = [M.Factor(scope=(v,), card=(k,), table=[Fr(rnd.randint(1, 99), 13) for _ in range(k)], origin=v) for v in range(5)]
    facs += [shared, shared, M.Factor(scope=(0, 1), card=(k, k), table=[Fr(0)] + [Fr(rnd.randint(1, 9), 5) for _ in range(k * k - 1)], origin=60),
             M.Factor(scope=(3, 4), card=(k, k), table=[Fr(rnd.randint(1, 9), 3) for _ in range(k * k)], origin=61)]
    m = M.Model(nvars=5, card=[k] * 5, factors=facs).validate()
    for ev in ({}, {4: 1}):
        r0 = M.restrict(m, ev)
        simp = PRE.simplify(r0)
        r = M.Restricted(model=m, evidence=ev, factors=simp.factors, free=list(simp.free), card=dict(simp.card), constant=r0.constant, impossible_factor=None)
        pl = CAP.checker_plan(r)
        vx = V.VecExact(pl, r.factors, r.card).run()
        cnt = vx.counts(r.free)
        Z, pt = O.exact_all_marginals(r0)
        for v in r.free:
            for a in range(k):
                assert Fr(int(cnt.get((v, a), 0)), int(vx.Z)) == pt[v][a], (ev, v, a)
        assert vx.scale_bits > 0


def test_deadline_and_rss_are_enforced_inside_whole_array_operations():
    """A deadline that expires mid-engine stops the vectorized producer / checker and
    the exact aggregation within one whole-array operation; a memory cap below the
    live set stops it as a MEMORY stop; neither publishes."""
    m = _model(16, 3, 9)
    r = M.restrict(m, {})
    pl = CAP.checker_plan(r)
    from mdi import arith as A
    calls = {"n": 0}

    class Stop(Exception):
        pass

    def dl():
        calls["n"] += 1
        if calls["n"] > 3:
            raise Stop()
    eng = V.VecEngine(pl, r.factors, A.Ctx(64), mode="P", deadline=dl)
    with pytest.raises(Stop):
        for rt in [b.idx for b in pl.bags if b.parent == -1]:
            eng.upward(rt)
    assert calls["n"] == 4 and len(eng.msg) <= 3
    calls["n"] = 0
    vx = V.VecExact(pl, r.factors, r.card, deadline=dl)
    with pytest.raises(Stop):
        vx.run()
    assert calls["n"] == 4
    # the pipeline's own enforcement: a 1-byte cap is a memory stop before any publication
    rs = PLN.solve(m, {}, wall_s=60, cap_bytes=1, plan_dir=tempfile.mkdtemp(), research_enabled=False)
    assert not rs.status.startswith("CERTIFIED") and not rs.intervals


def test_calibration_is_bound_to_the_executing_layout():
    pol = __import__("mdi.plantype", fromlist=["x"]).capacity_policy()
    assert pol["layout"] == CAP.executing_layout() == "vectorized"
    cal_v = CAP.calibration_for_layout("vectorized")
    cal_s = CAP.calibration_for_layout("scalar")
    assert cal_v["version"] != cal_s["version"] and cal_s["us_per_entry"]["vec_P"] >= 100 * cal_v["us_per_entry"]["vec_P"]
    # a record priced under the scalar calibration is refused here, where the vectorized layout executes
    m = _model(6, 2, 3)
    from mdi.matrix import _write_uai
    from mdi import replay as RP
    mp = _write_uai(m)
    mm = M.read_uai(mp)
    d = tempfile.mkdtemp()
    res = PLN.solve(mm, {}, wall_s=60, cap_bytes=1 << 30, plan_dir=d, research_enabled=False)
    plan = os.path.join(d, next(p["identity"] for p in res.prices if p["name"] == "identity") + ".plan.json")
    rec = json.load(open(plan))
    assert rec["request"]["capacity"]["layout"] == "vectorized"
    rec["request"]["capacity"]["calibration"] = cal_s["version"]
    rec["request"]["capacity"]["layout"] = "scalar"
    pb = os.path.join(d, "scalar_priced.plan.json")
    json.dump(rec, open(pb, "w"))
    rr = RP.replay(mp, "-", pb)
    assert rr["status"] == "REPLAY_REFUSED" and "capacity" in str(rr.get("reason"))


def test_certificate_admission_requires_the_complete_checking_path():
    """For the certified comparison a route whose exact aggregation is forecast
    infeasible is refused BEFORE any work (it cannot satisfy the certificate);
    the shared-aggregation-only run is an explicit diagnostic and is labelled
    VERIFIED_SHARED_AGGREGATION_ONLY, never a certificate."""
    m = _model(16, 3, 9)
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
        t = time.time()
        cert = PLN.solve(m, {}, wall_s=120, cap_bytes=1 << 30, plan_dir=tempfile.mkdtemp(), research_enabled=False)
        el = time.time() - t
        diag = PLN.solve(m, {}, wall_s=120, cap_bytes=1 << 30, plan_dir=tempfile.mkdtemp(), research_enabled=False, diagnostic_shared_only=True)
    finally:
        CAP.admit = orig
    # certified comparison: refused before work, typed, naming the aggregation
    assert cert.status == "PRICE_REFUSAL" and not cert.intervals and el < 30, (cert.status, cert.reason)
    assert "AGGREGATION" in str(cert.reason)
    # explicit diagnostic: runs, verified containment, honest terminal, nothing certified
    assert diag.status == "VERIFIED_SHARED_AGGREGATION_ONLY" and not diag.intervals
    assert diag.partial_evidence.get("unverified_producer_rows")
    feas = next(p.get("feasibility") for p in diag.prices if p["name"] == "identity")
    assert feas["admitted_for"] == "diagnostic_shared_only"
    # the flag never leaks into the next invocation
    nxt = PLN.solve(_model(6, 2, 3), {}, wall_s=60, cap_bytes=1 << 30, plan_dir=tempfile.mkdtemp(), research_enabled=False)
    assert next(p.get("feasibility") for p in nxt.prices if p["name"] == "identity")["admitted_for"] == "certificate"
