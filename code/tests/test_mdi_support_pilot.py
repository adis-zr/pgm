"""Bounded pilot (3 November 2026, overseer decision GO_TO_BOUNDED_PILOT_DESIGN): exact
global-support compilation and sparse execution on the identity decomposition. The controls
the overseer's design names: tiny weighted-enumeration controls over categorical domains,
evidence, repeated factors, permuted axes, scalar and disconnected zero evidence, isolated
variables and every singleton; a mask-omission mutation that must fail independent checking
even when every retained row has a witness; the arithmetic label describing the sparse
circuit; the original numeric checks never skipped; the admission rule (strictly positive
bypass, pre-allocation forecast, caps, tenfold reduction) and the charged attempt."""
import os, sys, json, random, tempfile, itertools, glob
HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)
from fractions import Fraction as Fr
import pytest
import numpy as np
from mdi import (model as M, plan as P, pipeline as PLN, oracle as O, preprocess as PRE, capacity as CAP,
                 support as SP, support_check as SC, arith as A, budget as B, program as PG)
import mdi.registry  # noqa: F401

pytestmark = pytest.mark.skipif(not SP.AVAILABLE, reason="numpy is not available for the sparse layout")


def _restricted(m, ev):
    r = M.restrict(m, ev)
    s = PRE.simplify(r)
    if s.impossible is not None:
        return None
    return M.Restricted(model=m, evidence=dict(ev), factors=s.factors, free=list(s.free), card=dict(s.card),
                        constant=r.constant, impossible_factor=None)


def _true_rows(r, pl):
    """Brute force: the projection of every POSITIVE complete assignment onto every bag."""
    free = sorted(r.free)
    pos = []
    for combo in itertools.product(*[range(r.card[v]) for v in free]):
        a = dict(zip(free, combo))
        w = Fr(1)
        for f in r.factors:
            st = f.strides()
            if f.table[sum(a[v] * st[k] for k, v in enumerate(f.scope))] == 0:
                w = Fr(0)
                break
        if w != 0:
            pos.append(a)
    out = {}
    for b in pl.bags:
        bvars = tuple(b.vars)
        shape = tuple(r.card[v] for v in bvars)
        keys = set(int(np.ravel_multi_index(tuple(a[v] for v in bvars), shape)) for a in pos)
        out[b.idx] = np.array(sorted(keys), dtype=np.int64)
    return out, pos


def _perm_chain(n, k=3, seed=0, isolated=False, repeat=False):
    """Near-permutation pair factors (one feasible successor per state, an extra branch
    now and then), triple factors with reversed / permuted scopes, an optional isolated
    variable (no factor touches it) and an optional repeated factor OBJECT."""
    r0 = random.Random(seed)
    facs = [M.Factor(scope=(v,), card=(k,), table=[Fr(r0.randint(1, 5)) for _ in range(k)], origin=v) for v in range(n)]
    for v in range(n - 1):
        tab = [Fr(0)] * (k * k)
        for i in range(k):
            tab[i * k + (i + 1) % k] = Fr(r0.randint(1, 7))
        if v % 3 == 0:
            tab[0] = Fr(2)
        sc = (v, v + 1) if v % 2 == 0 else (v + 1, v)
        if sc == (v + 1, v):
            tab = [tab[i * k + j] for j in range(k) for i in range(k)]     # the same law, axes permuted
        facs.append(M.Factor(scope=sc, card=(k, k), table=tab, origin=100 + v))
    for v in range(0, n - 3, 2):
        facs.append(M.Factor(scope=(v + 3, v, v + 2), card=(k, k, k),
                             table=[Fr(1 + ((i + j + l) % 2)) for i in range(k) for j in range(k) for l in range(k)], origin=200 + v))
    if repeat:
        facs.append(facs[-1])                                             # the same object twice: multiplicity two
    nv = n + (1 if isolated else 0)
    return M.Model(nvars=nv, card=[k] * nv, factors=facs).validate()


def _band_chain(n, k=8, band=2, seed=0):
    """Banded pair factors (each state has `band` feasible successors) and dense triple
    factors: an admitted sparse schedule whose bags have rows with COVERED separator
    projections (another row of the same bag projects to the same separator entries)."""
    r0 = random.Random(seed)
    facs = [M.Factor(scope=(v,), card=(k,), table=[Fr(r0.randint(1, 5)) for _ in range(k)], origin=v) for v in range(n)]
    for v in range(n - 1):
        tab = [Fr(0)] * (k * k)
        for i in range(k):
            for d in range(1, band + 1):
                tab[i * k + (i + d) % k] = Fr(r0.randint(1, 7))
        facs.append(M.Factor(scope=(v, v + 1), card=(k, k), table=tab, origin=100 + v))
    for v in range(n - 2):
        facs.append(M.Factor(scope=(v + 2, v, v + 1), card=(k, k, k),
                             table=[Fr(1 + ((i * j + l) % 3)) for i in range(k) for j in range(k) for l in range(k)], origin=200 + v))
    return M.Model(nvars=n, card=[k] * n, factors=facs).validate()


def test_compiled_support_is_exactly_the_projection_of_the_positive_assignments():
    """Producer compilation AND the checker's independent reconstruction equal the brute-force
    projection on every bag, over categorical domains, evidence, permuted axes, a repeated
    factor object, an isolated variable and mixed cardinalities; the two implementations
    agree with each other (digest) on every model."""
    cases = [(_perm_chain(8, k=3, seed=1), {}), (_perm_chain(8, k=3, seed=2), {4: 1}),
             (_perm_chain(7, k=3, seed=3, isolated=True), {2: 0}), (_perm_chain(7, k=3, seed=4, repeat=True), {}),
             (_perm_chain(9, k=2, seed=5), {0: 1, 8: 0})]
    # mixed cardinalities with zeros
    r0 = random.Random(7)
    cards = [2, 3, 2, 4, 3, 2]
    facs = [M.Factor(scope=(v,), card=(cards[v],), table=[Fr(r0.randint(0, 3)) or Fr(1) for _ in range(cards[v])], origin=v) for v in range(6)]
    for sc in ((1, 0), (2, 3), (3, 1, 4), (5, 4), (0, 5)):
        tab = [Fr(r0.randint(0, 4)) for _ in range(int(np.prod([cards[v] for v in sc])))]
        tab[0] = Fr(1)
        facs.append(M.Factor(scope=sc, card=tuple(cards[v] for v in sc), table=tab, origin=100 + len(facs)))
    cases.append((M.Model(nvars=6, card=cards, factors=facs).validate(), {3: 2}))
    checked = 0
    for m, ev in cases:
        r = _restricted(m, ev)
        assert r is not None
        pl = CAP.checker_plan(r)
        sup = SP.compile_support(pl, r.factors, r.card)
        rows_c, scan, _el = SC.reconstruct_support(pl, r.factors, r.card)
        truth, pos = _true_rows(r, pl)
        assert pos, "the control has positive assignments"
        for b in pl.bags:
            assert np.array_equal(sup.rows[b.idx], truth[b.idx]), ("producer", b.idx, sup.rows[b.idx], truth[b.idx])
            assert np.array_equal(rows_c[b.idx], truth[b.idx]), ("checker", b.idx)
        assert SC.verify_declaration(pl, rows_c, sup.declaration()) == []
        assert scan > 0 and sup.counts()["scan_positions"] > 0
        checked += 1
    assert checked == len(cases)


def test_sparse_engines_preserve_every_singleton_and_the_partition_sum_exactly():
    """Over the compiled rows the sparse exact aggregation returns EXACTLY the oracle's Z and
    counts (zero approximation), and the sparse P / I engines' enclosures contain the exact
    marginals of every singleton, with repeated factors, evidence and permuted axes."""
    for m, ev in ((_perm_chain(8, k=3, seed=11), {}), (_perm_chain(8, k=3, seed=12, repeat=True), {3: 2}),
                  (_perm_chain(7, k=2, seed=13, isolated=True), {})):
        r = _restricted(m, ev)
        pl = CAP.checker_plan(r)
        Z, pt = O.exact_all_marginals(r)
        rows_c, _s, _e = SC.reconstruct_support(pl, r.factors, r.card)
        vx = SC.SparseExact(pl, r.factors, r.card, rows_c).run()
        cnt = vx.counts(r.free)
        for v in r.free:
            for a in range(r.card[v]):
                assert Fr(int(cnt.get((v, a), 0)), int(vx.Z)) == pt[v][a]
        sup = SP.compile_support(pl, r.factors, r.card)
        for mode, p in (("P", 64), ("I", 80)):
            eng = SP.SparseEngine(pl, r.factors, A.Ctx(p), sup, mode=mode)
            roots = [b.idx for b in pl.bags if b.parent == -1]
            for rt in roots:
                eng.upward(rt)
            for rt in roots:
                t = eng.root_value(rt)
                assert t.support[0]
            home = {}
            for v in r.free:
                home.setdefault(pl.var_home[v], []).append(v)
            read = {}

            def oc(bag):
                for vv in home.get(bag, ()):
                    read[vv] = eng.read_marginal(vv)
            for rt in roots:
                eng.downward(rt, on_calibrated=oc)
            for v in r.free:
                counts, seen, depth = read[v]
                if mode == "P":
                    vals = [A.exact_fr(x) if s_ else Fr(0) for x, s_ in zip(counts, seen)]
                    tot = sum(vals)
                    L = A.lam(depth, p)
                    for a in range(r.card[v]):
                        lo, hi = A.marginal_interval(vals[a], tot - vals[a], L)
                        assert lo <= pt[v][a] <= hi
                else:
                    los = [A.exact_fr(x[0]) if s_ else Fr(0) for x, s_ in zip(counts, seen)]
                    his = [A.exact_fr(x[1]) if s_ else Fr(0) for x, s_ in zip(counts, seen)]
                    tl, th = sum(los), sum(his)
                    for a in range(r.card[v]):
                        den = his[a] + tl - los[a]
                        assert los[a] / th <= pt[v][a] <= (his[a] / den if den > 0 else Fr(0)) or pt[v][a] == 0


def test_zero_evidence_is_a_typed_stop_of_compilation_not_a_support():
    """A disconnected unsatisfiable component and a scalar zero evidence stop the compilation
    as a typed SupportError (zero evidence weight) in BOTH implementations; the pipeline still
    proves the zero evidence through its own original-model proof when support is enabled."""
    # component {2,3} unsatisfiable: X2 must equal X3 by one factor and differ by another
    facs = [M.Factor(scope=(0, 1), card=(2, 2), table=[Fr(1), Fr(2), Fr(3), Fr(4)], origin=0),
            M.Factor(scope=(2, 3), card=(2, 2), table=[Fr(1), Fr(0), Fr(0), Fr(1)], origin=1),
            M.Factor(scope=(2, 3), card=(2, 2), table=[Fr(0), Fr(1), Fr(1), Fr(0)], origin=2)]
    m = M.Model(nvars=4, card=[2, 2, 2, 2], factors=facs).validate()
    r = M.restrict(m, {})
    adj = P.primal_graph(r.free, r.card, r.factors)
    pl = P.build_plan("min_fill", P.order_min_fill(r.free, r.card, adj), r.free, r.card, r.factors)
    with pytest.raises(SP.SupportError):
        SP.compile_support(pl, r.factors, r.card)
    with pytest.raises(SP.SupportError):
        SC.reconstruct_support(pl, r.factors, r.card)
    res = PLN.solve(m, {}, wall_s=60, cap_bytes=1 << 30, plan_dir=tempfile.mkdtemp(), research_enabled=False, support_enabled=True)
    assert res.status == "ZERO_EVIDENCE_PROVED", (res.status, res.reason)
    # scalar zero evidence: the observed state has weight zero
    m2 = M.Model(nvars=2, card=[2, 2], factors=[M.Factor(scope=(0,), card=(2,), table=[Fr(1), Fr(0)], origin=0),
                                                M.Factor(scope=(0, 1), card=(2, 2), table=[Fr(1), Fr(1), Fr(1), Fr(1)], origin=1)]).validate()
    res2 = PLN.solve(m2, {0: 1}, wall_s=60, cap_bytes=1 << 30, plan_dir=tempfile.mkdtemp(), research_enabled=False, support_enabled=True)
    assert res2.status == "ZERO_EVIDENCE_PROVED", (res2.status, res2.reason)


def test_pipeline_certifies_through_the_sparse_route_and_labels_the_sparse_circuit():
    """Through the public pipeline with the support route enabled: the program carries the
    compiled support, the executor runs the sparse layout, the checker reconstructs and
    agrees, the exact aggregation runs sparsely, the arithmetic labels describe the SPARSE
    circuit, every saved bound covers the executed meter, the original numeric checks run
    (coordinates checked = every requested coordinate), and the truth is contained; the
    dense invocation of the same model certifies the same truth and the two programs have
    different identities."""
    m = _perm_chain(10, k=3, seed=21)
    ev = {5: 1}
    r = _restricted(m, ev)
    Z, pt = O.exact_all_marginals(r)
    d = tempfile.mkdtemp()
    res = PLN.solve(m, ev, wall_s=120, cap_bytes=1 << 30, plan_dir=d, research_enabled=False, support_enabled=True)
    assert res.status == "CERTIFIED_FALLBACK_ONLY", (res.status, res.reason)
    rec = json.load(open(glob.glob(d + "/*.plan.json")[0]))
    sup = rec["program"]["support"]
    assert sup["compiled"] is True and sup["rows_total"] == sum(sup["rows_per_bag"]) and len(sup["digest"]) == 64
    PG.validate_program(json.loads(json.dumps(rec["program"])))        # the strict parser accepts the block
    pr = next(p for p in res.prices if p["name"] == "identity")
    c = pr["counters"]
    assert "SPARSE circuit" in c["producer_upward_ops"]["note"] and c["producer_upward_ops"]["label"] == "upper_bound"
    assert int(c["support_sparse_schedule_rows"]["value"]) * SP.MIN_REDUCTION_RATIO <= int(c["support_dense_schedule_rows"]["value"])
    ex = res.plan["executed"]
    assert ex["layout"] == "sparse-support" and ex["support"]["rows_total"] == sup["rows_total"]
    assert ex["ops"]["mul"] + ex["ops"]["add"] <= sum(int(c[k]["value"]) for k in ("producer_upward_ops", "producer_downward_ops", "readout_ops"))
    src = res.budget["used_by_source"]
    assert int(c["producer_metered_entries"]["value"]) >= sum(v for k, v in src.items() if "producer" in k)
    assert int(c["checker_metered_entries"]["value"]) >= sum(v for k, v in src.items() if "checker" in k)
    assert any("support compilation" in k for k in src), src           # the compilation is charged
    ck = res.checker
    assert ck["independent_aggregation_checked"] is True and "sparse exact integer junction tree" in ck["independent_aggregation_scope"]
    assert ck["support_reconstructed"]["declared_matches"] is True and ck["support_reconstructed"]["scan_positions"] > 0
    assert ck["coordinates_checked"] == sum(m.card[v] for v in range(m.nvars))
    assert all(Fr(res.intervals[v][a][0]) <= pt[v][a] <= Fr(res.intervals[v][a][1]) for v in pt for a in range(len(pt[v])))
    dense = PLN.solve(m, ev, wall_s=120, cap_bytes=1 << 30, plan_dir=tempfile.mkdtemp(), research_enabled=False)
    assert dense.status == "CERTIFIED_FALLBACK_ONLY"
    assert all(Fr(dense.intervals[v][a][0]) <= pt[v][a] <= Fr(dense.intervals[v][a][1]) for v in pt for a in range(len(pt[v])))
    drec = json.load(open(glob.glob(dense.plan["plan_dir"] + "/*.plan.json")[0])) if dense.plan.get("plan_dir") else None
    if drec is not None:
        assert drec["storage_schedule"]["identity"] != rec["storage_schedule"]["identity"]
        assert "support" not in drec["program"]


def test_mask_omission_mutation_fails_independent_checking_even_with_witnesses():
    """The producer's compiler drops ONE positive row of one bag (every retained row keeps a
    valid witness). The checker's reconstruction disagrees with the declaration (an omitted
    positive row) and the publication is REFUSED, whatever the omitted row's weight; the
    clean counterpart certifies."""
    m = _band_chain(7, k=8, band=2, seed=31)
    ev = {3: 1}
    r = _restricted(m, ev)
    assert SP.support_price(CAP.checker_plan(r), SP.compile_support(CAP.checker_plan(r), r.factors, r.card))["admitted"]
    orig = SP.compile_support

    def dropping(plan, factors, card, **kw):
        sup = orig(plan, factors, card, **kw)
        # omit ONE positive row whose projection onto every incident separator is still
        # covered by another row of the same bag: the producer's own row/message consistency
        # cannot notice it (every retained row keeps a valid witness), so only the checker's
        # independent reconstruction can
        for b in sorted(plan.bags, key=lambda b: -sup.rows[b.idx].size):
            rws = sup.rows[b.idx]
            bvars = tuple(b.vars)
            shape = tuple(int(card[v]) for v in bvars)
            coords = np.unravel_index(rws, shape)
            seps = []
            for nb in ([b.parent] if b.parent >= 0 else []) + list(b.children):
                sep = tuple(sorted(set(bvars) & set(plan.bags[nb].vars)))
                k = np.zeros(rws.size, dtype=np.int64)
                acc = 1
                for v in reversed(sep):
                    k += coords[bvars.index(v)] * acc
                    acc *= int(card[v])
                seps.append(k)
            for i in range(rws.size):
                if all(np.count_nonzero(k == k[i]) >= 2 for k in seps):
                    sup.rows[b.idx] = np.delete(rws, i)
                    return sup
        raise AssertionError("the control model has no row with a covered projection")
    SP.compile_support = dropping
    try:
        SP._SUPPORT_CACHE.clear()
        bad = PLN.solve(m, ev, wall_s=120, cap_bytes=1 << 30, plan_dir=tempfile.mkdtemp(), research_enabled=False, support_enabled=True)
    finally:
        SP.compile_support = orig
        SP._SUPPORT_CACHE.clear()
    assert bad.status == "NUMERICAL_REFUSAL" and not bad.intervals, (bad.status, bad.reason)
    fails = " ".join(str(f) for f in (bad.checker or {}).get("failures", []))
    assert "omitted positive rows" in fails and "declared support is not the independently reconstructed" in fails, (fails, bad.reason)
    clean = PLN.solve(m, ev, wall_s=120, cap_bytes=1 << 30, plan_dir=tempfile.mkdtemp(), research_enabled=False, support_enabled=True)
    assert clean.status == "CERTIFIED_FALLBACK_ONLY"
    # a mutated CHECKER (dropping a row of its own reconstruction) also refuses: the declaration carries more rows
    orig_r = SC.reconstruct_support

    def dropping_r(plan, factors, card, **kw):
        rows, scan, el = orig_r(plan, factors, card, **kw)
        bidx = max(rows, key=lambda i: rows[i].size)
        rows[bidx] = rows[bidx][1:]
        return rows, scan, el
    SC.reconstruct_support = dropping_r
    try:
        bad2 = PLN.solve(m, ev, wall_s=120, cap_bytes=1 << 30, plan_dir=tempfile.mkdtemp(), research_enabled=False, support_enabled=True)
    finally:
        SC.reconstruct_support = orig_r
    assert bad2.status == "NUMERICAL_REFUSAL", (bad2.status, bad2.reason)


def test_admission_rule_bypass_forecast_caps_and_tenfold_threshold_with_the_attempt_charged():
    """(1) a strictly positive law bypasses the mechanism after the input scan (typed
    SUPPORT_BYPASS, nothing compiled, nothing charged); (2) the Boolean working set is
    forecast and refused BEFORE allocation when above the cap; (3) a wall cap stops the
    compilation as a typed SupportError; (4) a law with zeros but below the tenfold reduction
    falls back to the dense identity with the compilation CHARGED and the ratio recorded;
    (5) the dense result is certified in every fallback."""
    # (1) strictly positive
    pos = M.Model(nvars=5, card=[2] * 5, factors=[M.Factor(scope=(v, v + 1), card=(2, 2), table=[Fr(1), Fr(2), Fr(3), Fr(4)], origin=v) for v in range(4)]).validate()
    res = PLN.solve(pos, {}, wall_s=60, cap_bytes=1 << 30, plan_dir=tempfile.mkdtemp(), research_enabled=False, support_enabled=True)
    assert res.status == "CERTIFIED_FALLBACK_ONLY"
    rj = [x for x in res.rejected if x.get("name") == "identity+support"]
    assert rj and rj[0]["typed"] == "SUPPORT_BYPASS"
    assert not any("support compilation" in k for k in res.budget["used_by_source"])
    # (2) forecast above the cap: refused before allocation
    m = _perm_chain(10, k=3, seed=41)
    r = _restricted(m, {})
    pl = CAP.checker_plan(r)
    with pytest.raises(SP.SupportError) as ei:
        SP.compile_support(pl, r.factors, r.card, mem_cap_bytes=8)
    assert "before allocation" in str(ei.value)
    with pytest.raises(SP.SupportError):
        SC.reconstruct_support(pl, r.factors, r.card, mem_cap_bytes=8)
    # (3) wall cap
    with pytest.raises(SP.SupportError) as ei2:
        SP.compile_support(pl, r.factors, r.card, wall_cap_s=0.0)
    assert "cap" in str(ei2.value)
    # (4) zeros but little reduction: a chain with ONE zero entry per pair table
    r0 = random.Random(5)
    facs = [M.Factor(scope=(v,), card=(2,), table=[Fr(1), Fr(1 + v % 3)], origin=v) for v in range(12)]
    facs += [M.Factor(scope=(v, v + 1), card=(2, 2), table=[Fr(2), Fr(1), Fr(1), Fr(3)], origin=100 + v) for v in range(11)]
    facs[-1] = M.Factor(scope=(10, 11), card=(2, 2), table=[Fr(2), Fr(0), Fr(1), Fr(3)], origin=111)
    m2 = M.Model(nvars=12, card=[2] * 12, factors=facs).validate()
    Z, pt = O.exact_all_marginals(M.restrict(m2, {}))
    res2 = PLN.solve(m2, {}, wall_s=60, cap_bytes=1 << 30, plan_dir=tempfile.mkdtemp(), research_enabled=False, support_enabled=True)
    assert res2.status == "CERTIFIED_FALLBACK_ONLY", (res2.status, res2.reason)
    rj2 = [x for x in res2.rejected if x.get("name") == "identity+support"]
    assert rj2 and rj2[0]["typed"] == "SUPPORT_NOT_ADMITTED" and rj2[0]["support_price"]["reduction_ratio"] < SP.MIN_REDUCTION_RATIO
    assert any("support compilation" in k for k in res2.budget["used_by_source"]), res2.budget["used_by_source"]   # the attempt is charged
    assert res2.plan["executed"].get("layout") != "sparse-support"
    assert all(Fr(res2.intervals[v][a][0]) <= pt[v][a] <= Fr(res2.intervals[v][a][1]) for v in pt for a in range(2))
    # (6) the dense invocation never compiles: the selection is explicit per invocation
    res3 = PLN.solve(m, {}, wall_s=60, cap_bytes=1 << 30, plan_dir=tempfile.mkdtemp(), research_enabled=False)
    assert res3.status == "CERTIFIED_FALLBACK_ONLY" and not any(x.get("name") == "identity+support" for x in res3.rejected)
    assert not any("support compilation" in k for k in res3.budget["used_by_source"])


def test_program_parser_refuses_malformed_support_and_binding_refuses_a_tampered_declaration():
    """The strict program parser refuses a support block on a non-identity kind, with unknown
    fields, with inconsistent totals; a record whose declared digest is edited is refused at
    replay (the re-derived support is not the declared one)."""
    from mdi.matrix import _write_uai
    mp = _write_uai(_perm_chain(10, k=3, seed=51))
    m = M.read_uai(mp)                       # the SAME bytes the replay will read
    ev = {5: 1}
    d = tempfile.mkdtemp()
    res = PLN.solve(m, ev, wall_s=120, cap_bytes=1 << 30, plan_dir=d, research_enabled=False, support_enabled=True)
    assert res.status == "CERTIFIED_FALLBACK_ONLY", (res.status, res.reason)
    p = glob.glob(d + "/*.plan.json")[0]
    rec = json.load(open(p))
    assert rec["program"].get("support"), "the control's sparse route was admitted"
    good = json.loads(json.dumps(rec["program"]))
    PG.validate_program(good)
    bad = json.loads(json.dumps(good)); bad["support"]["rows_total"] += 1
    with pytest.raises(PG.ProgramError):
        PG.validate_program(bad)
    bad = json.loads(json.dumps(good)); bad["support"]["extra"] = 1
    with pytest.raises(PG.ProgramError):
        PG.validate_program(bad)
    bad = json.loads(json.dumps(good)); bad["kind"] = "regional"
    with pytest.raises(PG.ProgramError):
        PG.validate_program(bad)
    # replay of the clean record verifies; a tampered digest is refused
    from mdi import replay as RP
    ep = os.path.join(d, "ev.uai.evid")
    with open(ep, "w") as fh:
        fh.write("%d %s\n" % (len(ev), " ".join("%d %d" % (v, st) for v, st in ev.items())))
    rr = RP.replay(mp, ep, p)
    assert rr["status"] == "REPLAY_VERIFIED", rr.get("reason")
    rec2 = json.loads(json.dumps(rec)); rec2["program"]["support"]["digest"] = "0" * 64
    p2 = os.path.join(d, "tampered.plan.json"); json.dump(rec2, open(p2, "w"))
    rr2 = RP.replay(mp, ep, p2)
    assert rr2["status"] != "REPLAY_VERIFIED", rr2


def test_declined_support_persists_a_durable_terminal_record_through_the_public_arm():
    """(pilot review, 3 Nov) A SUPPORT_NOT_ADMITTED rejection record carried a self-referential
    price (`price['checker'] = price`); the arm completed the dense inference and then raised
    RecursionError while saving its terminal record, leaving the durable status STARTED with
    no receipt. The record is now acyclic and JSON-serialisable; the public arm persists the
    terminal record and the receipt; the rejection still names the ratio and the charge."""
    from mdi import arm as ARM
    from mdi.matrix import _write_uai
    facs = [M.Factor(scope=(v,), card=(2,), table=[Fr(1), Fr(1 + v % 3)], origin=v) for v in range(12)]
    facs += [M.Factor(scope=(v, v + 1), card=(2, 2), table=[Fr(2), Fr(1), Fr(1), Fr(3)], origin=100 + v) for v in range(11)]
    facs[-1] = M.Factor(scope=(10, 11), card=(2, 2), table=[Fr(2), Fr(0), Fr(1), Fr(3)], origin=111)
    m = M.Model(nvars=12, card=[2] * 12, factors=facs).validate()
    mp = _write_uai(m)
    ep = mp + ".evid"
    open(ep, "w").write("0\n")
    rd = tempfile.mkdtemp()
    rec = ARM.run_arm("tiny", False, rd, wall=60, model_path=mp, evid_path=ep, support=True)
    assert rec["outcome"] == "CERTIFIED_FALLBACK_ONLY" and rec["arm"] == "support"
    saved = json.load(open(os.path.join(rd, "arm_tiny_support.json")))
    assert saved["outcome"] == "CERTIFIED_FALLBACK_ONLY"
    assert os.path.exists(os.path.join(rd, "arm_tiny_support.receipt.json"))
    rj = [x for x in saved["pipeline"]["rejected"] if x.get("name") == "identity+support"]
    assert rj and rj[0]["typed"] == "SUPPORT_NOT_ADMITTED" and "checker" not in rj[0]["support_price"]
    json.dumps(saved)                                                 # acyclic
    # the admitted case persists too, and its price's checker figures are a copy, not the price itself
    m2 = _perm_chain(10, k=3, seed=61)
    mp2 = _write_uai(m2); ep2 = mp2 + ".evid"; open(ep2, "w").write("1 5 1\n")
    rd2 = tempfile.mkdtemp()
    rec2 = ARM.run_arm("tiny2", False, rd2, wall=60, model_path=mp2, evid_path=ep2, support=True)
    assert rec2["outcome"] == "CERTIFIED_FALLBACK_ONLY" and rec2["pipeline"]["plan"]["executed"]["layout"] == "sparse-support"
    assert json.load(open(os.path.join(rd2, "arm_tiny2_support.json")))["outcome"] == "CERTIFIED_FALLBACK_ONLY"


def test_support_caps_are_enforced_live_in_both_implementations_and_cover_the_metadata():
    """(pilot review) The Boolean forecast counts every retained upward mask, every upward
    separator mask and a projection temporary; both implementations account every allocation
    LIVE (masks, offsets and gathered copies, projection temporaries, int64 rows, metadata
    temporaries) and refuse when the live set exceeds the cap; a cap below the retained masks
    is refused before allocation; the compilation's elapsed time includes its metadata."""
    m = M.Model(nvars=4, card=[2] * 4, factors=[M.Factor(scope=(v, v + 1), card=(2, 2), table=[Fr(1), Fr(0), Fr(1), Fr(1)], origin=v) for v in range(3)]).validate()
    r = _restricted(m, {})
    pl = CAP.checker_plan(r)
    fc = SP.forecast_boolean_bytes(pl, r.card)
    assert fc >= pl.sum_bag_entries + pl.sum_sep_entries           # every retained mask is in the forecast
    with pytest.raises(SP.SupportError) as e1:
        SC.reconstruct_support(pl, r.factors, r.card, mem_cap_bytes=24)
    assert "before allocation" in str(e1.value)
    with pytest.raises(SP.SupportError):
        SP.compile_support(pl, r.factors, r.card, mem_cap_bytes=24)
    # a cap that passes the Boolean forecast but not the live set (int64 rows and temporaries) is refused LIVE
    with pytest.raises(SP.SupportError) as e2:
        SP.compile_support(pl, r.factors, r.card, mem_cap_bytes=fc)
    assert "working-storage cap" in str(e2.value)
    with pytest.raises(SP.SupportError) as e3:
        SC.reconstruct_support(pl, r.factors, r.card, mem_cap_bytes=fc)
    assert "working-storage cap" in str(e3.value)
    # with room, both complete, agree, and the compilation reports a peak above the Boolean forecast
    sup = SP.compile_support(pl, r.factors, r.card)
    rows, scan, el = SC.reconstruct_support(pl, r.factors, r.card)
    assert SC.verify_declaration(pl, rows, sup.declaration()) == []
    assert sup.peak_working_bytes > fc and sup.elapsed_s >= sup.passes_s and sup.metadata_s >= 0
    # the metadata (global separator populations) is inside the wall cap: an expired cap trips during it too
    import time as _t
    big = _perm_chain(10, k=3, seed=71)
    rb = _restricted(big, {})
    plb = CAP.checker_plan(rb)
    with pytest.raises(SP.SupportError):
        SP.compile_support(plb, rb.factors, rb.card, wall_cap_s=0.0)


def test_launcher_never_exceeds_the_run_allowance_including_grace():
    """(pilot review) Initial cells did not check the remaining allowance: with the declared
    10 s durable-write grace, two supervisor timeouts charged 1,220 s against a 1,200 s
    allowance. Now a cell whose full wall plus grace no longer fits the remaining allowance is
    NOT started and marked NOT_RUN_ALLOWANCE_STOP; an initial cell is never shortened."""
    sys.path.insert(0, os.path.join(HERE, "tests"))
    from test_mdi_launch import _synthetic, _factory
    from mdi import launch as L
    tmp = tempfile.mkdtemp()
    pk, pp, pin, bp, b, dummy = _synthetic(tmp, cell_wall=600.0, allowance=1200.0, session_cap=7200.0)
    b["order"] = b["order"][:2]
    b["durable_grace_s"] = 10.0
    json.dump(b, open(bp, "w"))
    rd = os.path.join(tmp, "run")
    L.prepare(rd, b, pin, bp, pp, packet=pk)

    def mocked(cmd, cwd, log_path, deadline_s, mem_limit_kib, env=None, label=""):
        return {"outcome": "TIMEOUT", "returncode": None, "elapsed_s": float(deadline_s), "peak_tree_rss_kib": 1024,
                "peak_tree_procs": 1, "mem_samples": 1, "mem_limitation": None}
    led = L.run_cells(rd, b, cmd_factory=_factory(dummy), supervisor=mocked)
    assert L.charged_cells_s(led) <= led["allowance_s"]
    assert led["cells"][0]["status"] == "CONSUMED" and led["cells"][0]["attempts"][0]["wall_granted_s"] == 600.0
    assert led["cells"][1]["status"] == "NOT_RUN_ALLOWANCE_STOP" and not led["cells"][1]["attempts"]
    assert led["cells"][1]["allowance_stop"]["needed_s"] == 610.0
    # with enough allowance both cells run their full wall
    tmp2 = tempfile.mkdtemp()
    pk2, pp2, pin2, bp2, b2, dummy2 = _synthetic(tmp2, cell_wall=600.0, allowance=1300.0, session_cap=7200.0)
    b2["order"] = b2["order"][:2]; b2["durable_grace_s"] = 10.0; json.dump(b2, open(bp2, "w"))
    rd2 = os.path.join(tmp2, "run"); L.prepare(rd2, b2, pin2, bp2, pp2, packet=pk2)
    led2 = L.run_cells(rd2, b2, cmd_factory=_factory(dummy2), supervisor=mocked)
    assert [c["status"] for c in led2["cells"]] == ["CONSUMED", "CONSUMED"] and L.charged_cells_s(led2) == 1220.0
