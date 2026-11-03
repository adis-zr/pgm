"""Integrated pass of 3 November 2026 (second review of the capacity build): independent
input-table interpretation, actual allocation / tile schedules, guarded occupancy probe,
schedule-derived prices with remaining-work admission."""
import os, sys, json, random, tempfile
HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)
from fractions import Fraction as Fr
import pytest
import numpy as np
from mdi import (model as M, plan as P, solve as S, pipeline as PLN, vec_engine as V, capacity as CAP,
                 pricing as PR, oracle as O, budget as B)
import mdi.registry  # noqa: F401

pytestmark = pytest.mark.skipif(not V.AVAILABLE, reason="numpy is not available for the vectorized layout")


def _chain(n, k=2, pair=(2, 1, 1, 3), unary=None, seed=0):
    rnd = random.Random(seed)
    facs = [M.Factor(scope=(v,), card=(k,), table=(list(unary) if unary else [Fr(1), Fr(1 + v % 3)] if k == 2 else [Fr(rnd.randint(1, 9)) for _ in range(k)]), origin=v) for v in range(n)]
    facs += [M.Factor(scope=(v, v + 1), card=(k, k), table=[Fr(x) for x in pair] if k == 2 else [Fr(rnd.randint(1, 9)) for _ in range(k * k)], origin=100 + v) for v in range(n - 1)]
    return M.Model(nvars=n, card=[k] * n, factors=facs).validate()


def test_shared_layout_fault_is_refused_by_the_checkers_own_interpretation():
    """A transpose inside the shared layout helper changes which variable each
    factor-table axis describes. The checker's exact aggregation now addresses
    every table entry by its own stride arithmetic, and the checker verifies the
    helper against it before any arithmetic: the pipeline REFUSES (on asymmetric
    tables where the fault changes the law, and by the layout verification on
    every table), never certifying wrong marginals. The clean counterpart
    certifies."""
    m = _chain(13, pair=(3, 1, 2, 4), unary=[Fr(1), Fr(1)])
    Z, pt = O.exact_all_marginals(M.restrict(m, {}))
    clean = PLN.solve(m, {}, wall_s=120, cap_bytes=1 << 30, plan_dir=tempfile.mkdtemp(), research_enabled=False)
    assert clean.status.startswith("CERTIFIED") and all(Fr(clean.intervals[v][a][0]) <= pt[v][a] <= Fr(clean.intervals[v][a][1]) for v in pt for a in range(2))
    orig = V._bag_view

    def swapped(arr, scope, bag_vars):
        out = orig(arr, scope, bag_vars)
        if len(scope) == 2 and out.ndim >= 2:
            ax = [i for i, s in enumerate(out.shape) if s > 1]
            if len(ax) == 2:
                return out.swapaxes(ax[0], ax[1])
        return out
    V._bag_view = swapped
    try:
        bad = PLN.solve(m, {}, wall_s=120, cap_bytes=1 << 30, plan_dir=tempfile.mkdtemp(), research_enabled=False)
        # the symmetric-table variant (the fault does not change the law): still refused, by the layout verification
        bad_sym = PLN.solve(_chain(13), {}, wall_s=120, cap_bytes=1 << 30, plan_dir=tempfile.mkdtemp(), research_enabled=False)
    finally:
        V._bag_view = orig
    assert bad.status == "NUMERICAL_REFUSAL" and not bad.intervals, (bad.status, bad.reason)
    assert bad_sym.status == "NUMERICAL_REFUSAL" and not bad_sym.intervals and "axis interpretation" in str(bad_sym.reason or "") + " ".join(str(f) for f in (bad_sym.checker or {}).get("failures", []))
    # the verification itself, in isolation
    r = M.restrict(m, {})
    assert V.verify_layout_interpretation(r.factors, r.card) == []
    V._bag_view = swapped
    try:
        assert V.verify_layout_interpretation(r.factors, r.card)
    finally:
        V._bag_view = orig


def test_exact_engine_tiles_to_its_declared_chunk_and_forecast_bounds_it():
    """With the chunk lowered to 2^12 for the control, a 2^16-entry binary bag:
    every product array the exact engine allocates (including single-operand
    tiles, which numpy never multiplies) is at most the chunk -- tiling runs
    over summed AND kept axes -- the engine reports its largest transient, the
    forecast's tile bounds it, and the arithmetic result is exact."""
    n = 16
    facs = [M.Factor(scope=tuple(range(n)), card=(2,) * n, table=[Fr(1 + (i % 5)) for i in range(1 << n)], origin=0)]
    m = M.Model(nvars=n, card=[2] * n, factors=facs).validate()
    r = M.restrict(m, {})
    pl = CAP.checker_plan(r)
    saved = V.VecExact.CHUNK_ENTRIES
    V.VecExact.CHUNK_ENTRIES = 1 << 12
    try:
        vx = V.VecExact(pl, r.factors, r.card).run()
        cnt = vx.counts(r.free)
        assert vx.max_transient_entries <= (1 << 12), vx.max_transient_entries
        assert max(CAP.exact_tile_entries(b, r.card, chunk=1 << 12) for b in pl.bags) >= vx.max_transient_entries
        assert max(CAP.exact_tile_entries(b, r.card, chunk=1 << 12) for b in pl.bags) <= (1 << 12)
    finally:
        V.VecExact.CHUNK_ENTRIES = saved
    tot = sum(Fr(x) for x in facs[0].table)
    half = sum(Fr(facs[0].table[i]) for i in range(1 << n) if (i >> (n - 1)) == 0)
    assert Fr(int(cnt[(0, 0)]), int(vx.Z)) == half / tot
    Z, pt = O.exact_all_marginals(r)
    assert all(Fr(int(cnt.get((v, a), 0)), int(vx.Z)) == pt[v][a] for v in r.free for a in range(2))


def test_exact_forecast_counts_retained_upward_messages_and_the_actual_tile():
    """The exact engine RETAINS every upward message through the downward pass;
    the memory forecast must count them all (never a parent-frees-child
    simulation) plus the actual tile; on a 64-variable chain the forecast is at
    least the retained message bytes measured on the engine."""
    m = _chain(64)
    r = M.restrict(m, {})
    pl = CAP.checker_plan(r)
    vx = V.VecExact(pl, r.factors, r.card).run()
    retained_entries = sum(int(np.size(mm[1])) for mm in vx.msg.values())
    retained_bytes = sum(sys.getsizeof(int(x)) + 8 for mm in vx.msg.values() for x in mm[1].ravel())
    fc_bytes, _ = CAP.exact_peak_bytes(pl, r.factors)
    assert retained_entries == len([b for b in pl.bags if b.parent >= 0]) * 2
    assert fc_bytes >= retained_bytes, (fc_bytes, retained_bytes)
    # with occupancy 1.0 everywhere the forecast equals the full-bits count
    fc2, _ = CAP.exact_peak_bytes(pl, r.factors, occupancy={b.idx: 1.0 for b in pl.bags})
    assert fc2 == fc_bytes


def test_occupancy_probe_is_guarded_by_the_invocation_budget():
    """An expired budget stops the pre-admission occupancy probe before any work,
    as a typed budget stop (never a FEASIBLE verdict computed unguarded); a live
    budget lets it run and charges it."""
    m = _chain(13, unary=[Fr(1), Fr(0)])
    r = M.restrict(m, {})
    sel = P.choose_plan(r.free, r.card, r.factors, 64, 1 << 30)
    bg = B.Budget(wall_s=0.0, limits={"pricing_entries": 10 ** 9})
    with pytest.raises(B.BudgetExceeded):
        PR.identity_checker_feasibility(sel["chosen"][0], r, bg, wall_remaining_s=bg.remaining(), rss_cap_bytes=1 << 30)
    CAP._OCCUPANCY_CACHE.clear()
    bg2 = B.Budget(wall_s=60.0, limits={"pricing_entries": 10 ** 9})
    f = PR.identity_checker_feasibility(sel["chosen"][0], r, bg2, wall_remaining_s=bg2.remaining(), rss_cap_bytes=1 << 30)
    assert f["occupancy_probe"]["ran"] and bg2.used.get("pricing_entries", 0) > 0


def test_saved_metered_upper_bounds_cover_executed_work_in_the_same_unit():
    """The saved producer and checker metered-entry bounds are derived from the
    schedules the engines execute (messages, enumeration, every exact
    reduction); on clean models in both regimes (enumeration below the cap, exact
    aggregation above it) the executed meter never exceeds the saved bound, and
    the two are compared in the SAME unit (metered entries)."""
    for n, k in ((13, 2), (6, 3), (16, 2)):
        m = _chain(n, k=k, seed=n)
        res = PLN.solve(m, {}, wall_s=120, cap_bytes=1 << 30, plan_dir=tempfile.mkdtemp(), research_enabled=False)
        assert res.status.startswith("CERTIFIED"), (n, k, res.status, res.reason)
        c = next(p["counters"] for p in res.prices if p["name"] == "identity")
        src = res.budget["used_by_source"]
        prod = sum(v for kk, v in src.items() if "producer" in kk)
        chk = sum(v for kk, v in src.items() if "checker" in kk)
        assert int(c["producer_metered_entries"]["value"]) >= prod, (n, k, c["producer_metered_entries"]["value"], prod)
        assert int(c["checker_metered_entries"]["value"]) >= chk, (n, k, c["checker_metered_entries"]["value"], chk)
        assert int(c["metered_entries_forecast"]["value"]) >= res.budget["used"]["local_mass_entries"]


def test_later_admission_reserves_only_remaining_work():
    """After the producer and the interval checker have run, the exact
    aggregation's admission reserves ITS work only: a remaining wall that covers
    the aggregation but not the whole route admits it (remaining_only), while the
    initial admission (the whole route) would have refused."""
    m = _chain(16, k=3, seed=5)
    r = M.restrict(m, {})
    pl = CAP.checker_plan(r)
    fc = CAP.forecast_identity(pl, pl, r.factors, r.card, r.free)
    wall = fc["seconds"]["exact_X"] * 1.5 + 1e-6
    assert wall < fc["seconds"]["total"]
    initial = CAP.admit(fc, wall, 8 << 30, 0)
    later = CAP.admit(fc, wall, 8 << 30, 0, remaining_only=True)
    assert initial["aggregation"] == "WALL_FORECAST_EXCEEDS"
    assert later["aggregation"] == "FEASIBLE" and "remaining work" not in later["aggregation_reason"] or later["aggregation"] == "FEASIBLE"


def _random_sparse_model(seed, n_lo, n_hi):
    """Binary models with random pair / triple tables (the same stream as
    scripts/repro3_checker_bound.py, so the seeds name the same models)."""
    r0 = random.Random(seed)
    n = r0.randint(n_lo, n_hi)
    k = 2
    facs = [M.Factor(scope=(v,), card=(k,), table=[Fr(r0.randint(1, 9)) for _ in range(k)], origin=v) for v in range(n)]
    for _ in range(n + r0.randint(2, 10)):
        sc = tuple(sorted(r0.sample(range(n), r0.choice([2, 2, 3]))))
        facs.append(M.Factor(scope=sc, card=(k,) * len(sc), table=[Fr(r0.randint(1, 9)) for _ in range(k ** len(sc))], origin=100 + len(facs)))
    return M.Model(nvars=n, card=[k] * n, factors=facs).validate()


def test_checker_bound_is_derived_from_the_checkers_own_schedule_and_counts_one_probe():
    """(second review, item 3, residual) The checker executes its OWN min-fill plan;
    its saved bound was derived from the PRODUCER's plan, so on min-degree producers
    above the enumeration cap the bound fell below execution (seeds 26 / 42 / 55:
    1,304 < 1,312, 2,192 < 2,224, 1,468 < 1,510 on the 3 Nov build). The occupancy
    probe is the checker's charged work and was outside the bound, and it ran three
    times per invocation (identity-keyed cache) while the record said once. Now: the
    bound names the checker's schedule and covers execution, the probe is charged
    exactly once per invocation and is inside the checker's bound; a law without
    hard zeros prices no probe."""
    # (a) non-min-fill producer above the enumeration cap, min-fill checker schedule larger
    seen_non_min_fill = 0
    for seed in (26, 42, 55, 19):
        m = _random_sparse_model(seed, 17, 24)
        r = M.restrict(m, {})
        pp = P.choose_plan(r.free, r.card, r.factors, 64, 8 << 30)["chosen"][0]
        if pp.name == "min_fill":
            continue
        seen_non_min_fill += 1
        res = PLN.solve(m, {}, wall_s=120, cap_bytes=1 << 30, plan_dir=tempfile.mkdtemp(), research_enabled=False)
        assert res.status.startswith("CERTIFIED"), (seed, res.status, res.reason)
        pr = next(p for p in res.prices if p["name"] == "identity")
        c = pr["counters"]
        src = res.budget["used_by_source"]
        chk = sum(v for kk, v in src.items() if "checker" in kk)
        assert int(c["checker_metered_entries"]["value"]) >= chk, (seed, pp.name, c["checker_metered_entries"]["value"], chk)
        assert "min_fill" in c["checker_metered_entries"]["note"] and "min_fill" in c["independent_sparse_ops"]["note"]
        assert pr["feasibility"]["checker_order"] == "min_fill"
        assert "occupancy probe" not in " ".join(src), src           # no hard zeros: no probe ran, none priced
        assert "0 entries" in c["checker_metered_entries"]["note"]
    assert seen_non_min_fill >= 3
    # (b) hard zeros: the probe is charged ONCE per invocation (not three times) and is inside the bound
    m = _chain(13, unary=[Fr(1), Fr(0)])
    r = M.restrict(m, {})
    cp = CAP.checker_plan(r)
    one_probe = sum(b.domain(cp.card) for b in cp.bags if b.parent >= 0)
    res = PLN.solve(m, {}, wall_s=120, cap_bytes=1 << 30, plan_dir=tempfile.mkdtemp(), research_enabled=False)
    assert res.status.startswith("CERTIFIED"), (res.status, res.reason)
    src = res.budget["used_by_source"]
    probe_charged = sum(v for kk, v in src.items() if "occupancy probe" in kk)
    assert probe_charged == one_probe, (probe_charged, one_probe)
    c = next(p["counters"] for p in res.prices if p["name"] == "identity")
    chk = sum(v for kk, v in src.items() if "checker" in kk)
    assert int(c["checker_metered_entries"]["value"]) >= chk + probe_charged - sum(
        v for kk, v in src.items() if "checker" in kk and "probe" in kk), (c["checker_metered_entries"]["value"], chk, probe_charged)
    assert int(c["metered_entries_forecast"]["value"]) >= res.budget["used"]["local_mass_entries"]
    # the cache is content-keyed: a fresh factor list with the same content is a hit; a different zero mask is not
    from mdi import preprocess as PRE
    s1 = PRE.simplify(M.restrict(m, {}))
    assert CAP.occupancy_probe(cp, s1.factors, r.card)[1] == 0                 # reused, nothing charged
    m2 = _chain(13, unary=[Fr(1), Fr(1)])
    s2 = PRE.simplify(M.restrict(m2, {}))
    assert CAP.occupancy_probe(CAP.checker_plan(M.restrict(m2, {})), s2.factors, r.card)[1] > 0
