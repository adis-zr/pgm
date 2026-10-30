"""Integrated-revision controls (r16): compact factors end to end, the whole
portfolio as persisted programs, owned restoration, dry-run costs, the §6
menu, mixed Gaussian/Fourier integration.

Every control enters through the external API; rejection controls pass their
clean base first under identical publication rules and assert the NAMED
obligation.
"""
import os, sys, json, copy, math, tempfile, subprocess
from fractions import Fraction as Fr
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import pytest
from mdi import (model as M, oracle as O, config as K, arith as A, marked as MK,
                 routes as RT, program as PG, program_check as PC, factors as FX,
                 collective_route as CR, collective_jt as CJ, pipeline as PLN,
                 plantype as PT, pricing as PR, sparse_jt as SJ, dense_be as DB,
                 modes as MD, solve as S)
import mdi.registry            # noqa: F401
from test_mdi_research import ring_of_blocks, w, mean_field, TINY

RES = K.PUBLICATION_RESERVE
HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _pair(J):
    e = math.exp(J)
    D = 10 ** 6
    return [Fr(round(e * D), D), Fr(round(D / e), D), Fr(round(D / e), D), Fr(round(e * D), D)]


def _pub(prog, rows):
    rad = sum((sc["t_level"] + sc["deletion_radius_total"] for sc in prog["scales"]), Fr(0))
    if prog["collective"]:
        rad += CR.total_radius(prog["collective"])
    return {v: [(max(Fr(0), lo - rad - RES), min(Fr(1), hi + rad + RES))
                for lo, hi in rows[v]] for v in rows}


def _parse(raw):
    return PG.validate_program(json.loads(json.dumps(raw, sort_keys=True)))


def _contains(pub, pt):
    return all(Fr(pub[v][s][0]) <= pt[v][s] <= Fr(pub[v][s][1])
               for v in pub for s in range(len(pub[v])))


def _replay(mp, plan, timeout=300):
    env = dict(os.environ)
    env["PYTHONPATH"] = HERE
    out = subprocess.run([sys.executable, "-m", "mdi.replay", mp, "-", plan], cwd=HERE,
                         capture_output=True, text=True, timeout=timeout, env=env)
    assert out.stdout.strip(), out.stderr[-800:]
    return json.loads(out.stdout)


# ------------------------------------------------------------ B. compactness

def test_projected_views_compose_and_are_never_expanded():
    """A view indexes the ORIGINAL table through composed offset maps; iterating
    it is refused; its entries equal the dense product at every assignment."""
    txt, n, NB, BS = ring_of_blocks()
    m = M.read_uai(w(txt))
    r = M.restrict(m, {})
    q = set(r.free)
    regs = [tuple(range(b * BS, (b + 1) * BS)) for b in range(NB)]
    scales, final = RT.build_scales(MK.Marked.from_restricted(r, q), regs, 2)
    l1 = scales[0].lifted
    assert all(FX.is_view(f) for f in l1.factors) and l1.factors
    for f in l1.factors:
        with pytest.raises(FX.ViewError):
            list(f.table)
        assert len(f.table) == f.size()
        # the view at (c_i, c_j) is the original table at the representatives
        for flat in range(f.size()):
            digits = []
            rem = flat
            for stv in f.strides():
                digits.append(rem // stv)
                rem %= stv
            a = {v: d for v, d in zip(f.scope, digits)}
            assert f.table[flat] == f.at(a)
            orig_a = {}
            for v, c in a.items():
                rep = scales[0].coarse[v].cells[c].rep
                for k, bv in enumerate(scales[0].rds[v].boundary):
                    orig_a[bv] = rep[k]
            assert f.at(a) == f.base.at(orig_a)
    # the second scale composes maps on top of the first scale's views
    l2 = scales[1].lifted
    assert all(FX.is_view(f) and f.base is not None for f in l2.factors) or not l2.factors
    assert all(f.base in [g.base for g in l1.factors] for f in l2.factors)


def test_engines_consume_compact_factors_without_enumeration():
    """Both engines contract a model whose crossing is a LARGE view (above the
    old 4,096 kernel cap) without materializing it, as long as the bag domain
    fits; the exact result agrees with the oracle."""
    # 3 regions of 16 cells each, crossing over all three: 4,096 entries
    # as a view; with a 4th region of 2 cells the view would be 8,192
    facs = [M.Factor(scope=(0, 1, 2), card=(4, 4, 4),
                     table=[Fr(1 + (i * 7 + 3) % 11) for i in range(64)], origin=0),
            M.Factor(scope=(3,), card=(2,), table=[Fr(1), Fr(3)], origin=1),
            M.Factor(scope=(2, 3), card=(4, 2), table=[Fr(1 + i % 3) for i in range(8)], origin=2)]
    m = M.Model(nvars=4, card=[4, 4, 4, 2], factors=facs).validate()
    r = M.restrict(m, {})
    Z, pt = O.exact_all_marginals(r)
    views = [FX.as_view(f) for f in r.factors]
    tabs = [SJ.lazy_from_factor(f) for f in views]
    Z2, mg, jt = SJ.all_marginals(tabs, r.card)
    assert Z2 == Z
    for v in r.free:
        for a in range(r.card[v]):
            assert mg[v][a] / Z2 == pt[v][a]
    dense_tabs = [(f.scope, FX.LazyTable(f.card, [f.offsets[v] for v in f.scope], f.base.table))
                  for f in views]
    Z3, mg3, djt = DB.exact_marginals(dense_tabs, r.card)
    assert Z3 == Z
    for v in r.free:
        for a in range(r.card[v]):
            assert mg3[v][a] / Z3 == pt[v][a]
    # a bag that needs more than the entry cap is refused for its SCHEDULE cost
    with pytest.raises(SJ.SparseError) as e:
        SJ.all_marginals(tabs, r.card, entry_cap=32)
    assert "cap" in str(e.value)


def test_external_compact_construction_is_priced_not_expanded():
    """The Pedigree/Promedus partitions that r15 refused at the dense
    lifted-crossing cap now BUILD compactly and are refused by the schedule
    price, with no Cartesian expansion anywhere."""
    p = "/tmp/tep/three_external_problems/inputs/Pedigree_11"
    if not os.path.exists(p + ".uai"):
        pytest.skip("external inputs not extracted")
    from mdi import regions as R
    m = M.read_uai(p + ".uai")
    ev = M.read_evidence(p + ".uai.evid", m)
    r = M.restrict(m, ev)
    q = set(r.free)
    c = [c for c in R.propose_partitions(r.free, r.card, r.factors) if c["mode"] != "singleton"][0]
    scales, final = RT.build_scales(MK.Marked.from_restricted(r, q), [tuple(x) for x in c["regions"]], 1)
    assert all(FX.is_view(f) for f in final.factors)
    assert max(f.size() for f in final.factors) > K.CAPS["aggregated_kernel_entries"]
    price, order = PR.price_program("r", "regional", final, scales, None, sum(r.card[v] for v in q),
                                    sum(rd.construction_ops for sc in scales for rd in sc.rds))
    assert not price.eligible and "cap" in price.ineligible_reason


# ------------------------------------------------- A. the whole portfolio

def test_identity_program_governs_solve_and_replays_fresh():
    """The identity record carries order, precision and exponent range; mdi.solve
    takes them from the program (no replanning); a fresh process replays it;
    an order that is not a valid schedule, or a precision below the depth
    bound, is a typed refusal."""
    mp = w(TINY)
    m = M.read_uai(mp)
    d = tempfile.mkdtemp()
    res = PLN.solve(m, {}, wall_s=60.0, cap_bytes=1 << 30, plan_dir=d)
    assert res.plan["chosen"] == "identity"
    rec = PT.PlanRecord.from_json(open(os.path.join(d, "identity.plan.json")).read())
    prog = rec.parsed_program
    assert prog["kind"] == "identity" and prog["order"] and prog["arithmetic"]["mode"] == "P"
    sub = {"order": prog["order"], "precision": prog["precision"],
           "emin": prog["arithmetic"]["emin"], "emax": prog["arithmetic"]["emax"]}
    out = S.solve(m, {}, eps=Fr(1, 100), mode="P", cap_bytes=1 << 30, deadline_s=60,
                  run_checker=False, program=sub)
    assert out["outcome"] == "PRODUCER_COMPLETE_UNCHECKED"
    assert out["program_settings"]["order"] == prog["order"]
    assert out["program_settings"]["precision"] == prog["precision"]
    bad = dict(sub, order=list(reversed(sub["order"]))[:-1])
    assert S.solve(m, {}, eps=Fr(1, 100), run_checker=False, program=bad)["outcome"] == "NUMERICAL_REFUSAL"
    low = dict(sub, precision=8)
    assert S.solve(m, {}, eps=Fr(1, 100), run_checker=False, program=low)["outcome"] == "NUMERICAL_REFUSAL"
    rep = _replay(mp, os.path.join(d, "identity.plan.json"))
    assert rep["status"] == "REPLAY_VERIFIED", rep


def test_loaded_record_roles_and_costs_are_bound():
    """Selection consumes only loaded records: the price is re-derived from
    the program and must match the recorded counters; the executor and
    checker are resolved FROM the record and must be the registered ones."""
    txt, n, NB, BS = ring_of_blocks()
    mp = w(txt)
    m = M.read_uai(mp)
    d = tempfile.mkdtemp()
    res = PLN.solve(m, {}, wall_s=120.0, cap_bytes=1 << 30, plan_dir=d)
    assert res.status == "CERTIFIED_RESEARCH_ROUTE"
    # every surviving record's counters equal the re-derived price
    r = M.restrict(m, {})
    from mdi import preprocess as PRE
    simp = PRE.simplify(r)
    rr = M.Restricted(model=m, evidence={}, factors=simp.factors, free=list(simp.free),
                      card=dict(simp.card), constant=r.constant, impossible_factor=None)
    for p in res.prices:
        rec = PT.PlanRecord.from_json(open(os.path.join(d, p["name"].replace(":", "_") + ".plan.json")).read())
        price = PLN._reprice_loaded(rec, rr, set(rr.free), sum(rr.card[v] for v in rr.free), simp, 1 << 30)
        assert PLN._price_disagrees(rec.cost_counters, price) is None, p["name"]
    assert "regional:ascending_id@64" == res.plan["chosen"]
    # a record whose recorded counters disagree with its program is refused
    base = json.load(open(os.path.join(d, "regional_ascending_id@64.plan.json")))
    bad = copy.deepcopy(base)
    bad["cost_counters"]["producer_schedule_ops"]["value"] = 1
    rec = PT.PlanRecord.from_json(json.dumps(bad))
    price = PLN._reprice_loaded(rec, rr, set(rr.free), sum(rr.card[v] for v in rr.free), simp, 1 << 30)
    assert "producer_schedule_ops" in PLN._price_disagrees(rec.cost_counters, price)
    # a record naming a role its kind does not run is refused by the pipeline
    bad2 = copy.deepcopy(base)
    bad2["executor_id"] = "mdi.registry:pipeline_identity_executor"
    assert PLN._resolve_role(bad2["executor_id"]) is not PT.dispatch_pipeline("regional")
    # the research label follows the CHECKER's verified transformation
    assert res.checker["verified_research"]["cells_merged_regions"] == res.plan["research"]["cells_merged_regions"] >= 1


def test_persisted_claims_of_completion_do_not_bind():
    txt, n, NB, BS = ring_of_blocks()
    m = M.read_uai(w(txt))
    d = tempfile.mkdtemp()
    PLN.solve(m, {}, wall_s=120.0, cap_bytes=1 << 30, plan_dir=d)
    base = json.load(open(os.path.join(d, "identity.plan.json")))
    for flag in ("selected", "producer_complete", "independently_verified"):
        bad = copy.deepcopy(base)
        bad["properties"]["selected"] = True
        bad["properties"]["producer_complete"] = flag != "selected"
        bad["properties"]["independently_verified"] = flag == "independently_verified"
        rec = PT.PlanRecord.from_json(json.dumps(bad))
        with pytest.raises(PT.PlanError) as e:
            rec.bind_check(rec.model_sha256, rec.evidence_sha256, rec.query_sha256)
        assert "completion flags" in str(e.value)


# ------------------------------------------------- D. owned restoration

def test_checker_owns_the_final_restoration():
    """The two-unary shared-readout fault rejects by the original-query
    containment obligation while its clean counterpart passes."""
    facs = [M.Factor(scope=(0,), card=(2,), table=[Fr(1), Fr(1)], origin=0),
            M.Factor(scope=(1,), card=(2,), table=[Fr(1), Fr(1)], origin=1)]
    m = M.Model(nvars=2, card=[2, 2], factors=facs).validate()
    r = M.restrict(m, {})
    q = {0, 1}
    scales, final = RT.build_scales(MK.Marked.from_restricted(r, q), [(0,), (1,)], 1)
    prog = _parse(RT.program_for("regional", scales, None, [], 128, q))
    rows, _ = RT.execute(prog, r, q)
    good = _pub(prog, rows)
    ok, fails, meta = PC.verify_program(r, q, prog, good, Fr(1, 100))
    assert ok, fails
    assert "checker-owned sharp marker-ratio restoration" in meta["method"]
    orig = MK.read_original

    def faulty(marked, Z, counts):
        out = orig(marked, Z, counts)
        return {v: [(lo * Fr(9, 5), hi * Fr(9, 5)) if s == 0 else (lo / 5, hi / 5)
                    for s, (lo, hi) in enumerate(rws)] for v, rws in out.items()}
    MK.read_original = faulty
    try:
        rows, _ = RT.execute(prog, r, q)
        pub = _pub(prog, rows)
        ok2, f2, _ = PC.verify_program(r, q, prog, pub, Fr(1, 100))
    finally:
        MK.read_original = orig
    assert Fr(pub[0][0][0]) > Fr(4, 5)                    # the fault published ~0.9
    assert not ok2 and any("does NOT contain" in x for x in f2), f2[:2]


# ---------------------------------------------------- E. dry-run costs

def test_dry_run_prices_cover_counted_work_on_every_route():
    """Priced producer and checker bounds (dry runs with the metering algebra
    plus counted extras) cover the counted Fraction operations on chain,
    branched, disconnected, nonuniform-feature and quadrature programs."""
    import fractions
    counts = {"n": 0}
    saved = {nm: getattr(fractions.Fraction, nm) for nm in
             ("__mul__", "__rmul__", "__add__", "__radd__", "__truediv__", "__rtruediv__",
              "__sub__", "__rsub__")}

    def wrap(fn):
        def w_(self, other, *a):
            counts["n"] += 1
            return fn(self, other, *a)
        return w_

    def measure(fn):
        for nm, f in saved.items():
            setattr(fractions.Fraction, nm, wrap(f))
        counts["n"] = 0
        try:
            out = fn()
        finally:
            for nm, f in saved.items():
                setattr(fractions.Fraction, nm, f)
        return out, counts["n"]

    def star(n):
        facs = [M.Factor(scope=(v,), card=(2,), table=[Fr(1), Fr(1 + v % 3)], origin=v) for v in range(n)]
        facs += [M.Factor(scope=(0, i), card=(2, 2), table=[Fr(2), Fr(1), Fr(1), Fr(3 if i % 2 else 2)],
                          origin=100 + i) for i in range(1, n)]
        return M.Model(nvars=n, card=[2] * n, factors=facs).validate()

    def chain3(n):
        facs = [M.Factor(scope=(v,), card=(3,), table=[Fr(1), Fr(2), Fr(1 + v % 2)], origin=v) for v in range(n)]
        facs += [M.Factor(scope=(i, i + 1), card=(3, 3), table=[Fr(x) for x in (2, 1, 1, 1, 3, 1, 1, 1, 2)],
                          origin=100 + i) for i in range(n - 1)]
        return M.Model(nvars=n, card=[3] * n, factors=facs).validate()

    def disc(n):
        facs = [M.Factor(scope=(v,), card=(2,), table=[Fr(1), Fr(1 + v % 2)], origin=v) for v in range(n)]
        facs += [M.Factor(scope=(i, i + 1), card=(2, 2), table=[Fr(2), Fr(1), Fr(1), Fr(3)], origin=100 + i)
                 for i in range(n - 1) if i != n // 2 - 1]
        return M.Model(nvars=n, card=[2] * n, factors=facs).validate()
    fields4 = [0.1 * (k + 1) * (1 if k % 2 == 0 else -1) for k in range(4)]
    cases = [("star7", star(7), "statistic", None), ("ternary5", chain3(5), "statistic", None),
             ("disconnected6", disc(6), "statistic", None),
             ("star7-regional", star(7), "regional", [(0, 1), (2, 3), (4, 5, 6)]),
             ("gaussian4", M.read_uai(w(mean_field(4, 0.30, fields4))), "gaussian", None),
             ("fourier4", M.read_uai(w(mean_field(4, -0.22, fields4))), "fourier", None)]
    for label, m, kind, regs in cases:
        r = M.restrict(m, {})
        q = set(r.free)
        mk0 = MK.Marked.from_restricted(r, q)
        if kind == "regional":
            coll = None
            scales, final = RT.build_scales(mk0, regs, 1)
        else:
            coll, final = CR.admit(mk0, A.Ctx(96), prefer=kind)[0]
            scales = []
        cons = sum(rd.construction_ops for sc in scales for rd in sc.rds)
        price, order = PR.price_program("x", kind, final, scales, coll, sum(r.card[v] for v in q), cons)
        prog = _parse(RT.program_for(kind, scales, coll, order or [], 96, q))
        (rows, meta), n_exec = measure(lambda: RT.execute(prog, r, q))
        pub = _pub(prog, rows)
        (ok, fails, cm), n_chk = measure(lambda: PC.verify_program(r, q, prog, pub, Fr(1, 100)))
        assert ok, (label, fails[:2])
        pp = sum(int(price.counters[k].value) for k in ("producer_upward_ops", "producer_downward_ops", "readout_ops"))
        pc = int(price.counters["checker_ops"].value)
        assert pp >= n_exec, (label, pp, n_exec)
        assert pc >= n_chk, (label, pc, n_chk)
        assert price.counters["transcendental_evaluations"].label == PR.UPPER
        if meta.get("peak_live_entries") is not None:
            assert int(price.counters["peak_live_message_entries"].value) >= meta["peak_live_entries"], label


def test_dry_run_statistic_supports_are_exact_and_the_final_product_is_bounded():
    """The metering algebra carries exact occupied supports: the priced
    support equals the executed one; the final component product is
    bit-bounded like every intermediate."""
    facs = [M.Factor(scope=(v,), card=(2,), table=[Fr(1), Fr(1 + v % 2)], origin=v) for v in range(6)]
    facs += [M.Factor(scope=(i, i + 1), card=(2, 2), table=[Fr(2), Fr(1), Fr(1), Fr(3)], origin=100 + i)
             for i in range(5) if i != 2]
    m = M.Model(nvars=6, card=[2] * 6, factors=facs).validate()
    r = M.restrict(m, {})
    q = set(r.free)
    coll, rmk = CR.admit(MK.Marked.from_restricted(r, q), A.Ctx(96), prefer="statistic")[0]
    price, order = PR.price_program("x", "statistic", rmk, [], coll, 12, 0)
    prog = _parse(RT.program_for("statistic", [], coll, order or [], 96, q))
    rows, meta = RT.execute(prog, r, q)
    assert meta["statistic_support"] <= int(price.counters["statistic_support_bound"].value)
    B = Fr(2) ** 40000
    facs = [M.Factor(scope=(0,), card=(2,), table=[B, B + 1], origin=0),
            M.Factor(scope=(1,), card=(2,), table=[B, B + 1], origin=1)]
    card = {0: 2, 1: 2}
    with pytest.raises(SJ.SparseError) as e:
        SJ.all_marginals([SJ.table_from_factor(f) for f in facs], card)
    assert "bit" in str(e.value)
    with pytest.raises(DB.DenseError) as e2:
        DB.exact_marginals([(f.scope, [Fr(x) for x in f.table]) for f in facs], card)
    assert "bit" in str(e2.value)


# ----------------------------------------------- C. the collective menu

def test_menu_proposes_block_combined_and_masked_modes_and_coarse_Q():
    """§6: a two-block signed model yields block, combined-sign and masked
    proposals; every certified candidate is offered to every applicable
    evaluator; Q is the coarsest admissible dyadic grid from the proved bound
    (the composed ring takes Q = 2^14 where r15's menu jumped to 2^16)."""
    n = 6
    facs = [M.Factor(scope=(v,), card=(2,), table=[Fr(1), Fr(1) + Fr(v, 20)], origin=v) for v in range(n)]
    for i in range(n):
        for j in range(i + 1, n):
            J = 0.25 if (i < 3 and j < 3) else (-0.20 if (i >= 3 and j >= 3) else 0.05)
            facs.append(M.Factor(scope=(i, j), card=(2, 2), table=_pair(J), origin=100 + 10 * i + j))
    m = M.Model(nvars=n, card=[2] * n, factors=facs).validate()
    r = M.restrict(m, {})
    cands, info = MD.propose_modes(r.free, r.factors, r.card)
    kinds = {c.kind for c in cands}
    assert "block_rank1" in kinds and "lowrank_combined" in kinds
    assert any(set(c.signs) == {1, -1} for c in cands), "a mixed-sign combined candidate"
    assert any(k.endswith("_mask1") for k in kinds), "the residual-mask search ran"
    q = set(r.free)
    Z, pt = O.exact_all_marginals(r)
    adm = CR.admit(MK.Marked.from_restricted(r, q), A.Ctx(96))
    evs = {c["evaluator"] for c, _ in adm}
    assert {"statistic", "mixed"} <= evs, evs
    vec = [x for x in adm if x[0]["evaluator"] == "statistic" and x[0]["candidate"].rank == 2][0]
    coll, rmk = vec
    prog = _parse(RT.program_for("statistic", [], coll, [], 96, q))
    rows, meta = RT.execute(prog, r, q)
    pub = _pub(prog, rows)
    assert _contains(pub, pt)
    ok, fails, cm = PC.verify_program(r, q, prog, pub, Fr(1, 100))
    assert ok, fails[:2]
    # coarse admissible Q on the composed ring
    txt, nn, NB, BS = ring_of_blocks()
    mr = M.read_uai(w(txt))
    rr = M.restrict(mr, {})
    scales, final = RT.build_scales(MK.Marked.from_restricted(rr, set(rr.free)),
                                    [(0, 1, 2, 3, 6, 9), (4, 5), (7, 8), (10, 11)], 1)
    cq = CR.admit(final, A.Ctx(160), prefer="statistic")[0][0]
    assert cq["Q"] < (1 << 16) and cq["Q_attempts"][-1]["admissible"]
    assert all(not a["admissible"] for a in cq["Q_attempts"][:-1])


def test_mixed_gaussian_fourier_program_executes_and_is_rechecked():
    """§7.2 complete on a small admissible mixed-sign control: full positive
    mass pass, conjugate pairing, marker-ratio stopping with omitted-node
    allowances, independent recheck of the retained nodes, containment."""
    facs = [M.Factor(scope=(v,), card=(2,), table=[Fr(1), Fr(1) + Fr(10 * (v + 1), 100)], origin=v)
            for v in range(3)]
    for (i, j), J in (((0, 1), 0.15), ((0, 2), 0.05), ((1, 2), -0.05)):
        facs.append(M.Factor(scope=(i, j), card=(2, 2), table=_pair(J), origin=10 + i * 3 + j))
    m = M.Model(nvars=3, card=[2] * 3, factors=facs).validate()
    r = M.restrict(m, {})
    q = set(r.free)
    Z, pt = O.exact_all_marginals(r)
    adm = CR.admit(MK.Marked.from_restricted(r, q), A.Ctx(96))
    mixed = [x for x in adm if x[0]["evaluator"] == "mixed"]
    assert mixed, [c["evaluator"] for c, _ in adm]
    coll, rmk = mixed[0]
    assert set(coll["candidate"].signs) == {1, -1}
    assert Fr(coll["forecast"]["L_lower"]) > 0 and coll["negative_deltas"]
    prog = _parse(RT.program_for("mixed", [], coll, [], 96, q))
    num_eps = K.MAX_WIDTH - 2 * CR.total_radius(prog["collective"]) - RES
    rows, meta = RT.execute(prog, r, q, num_eps=num_eps)
    assert meta["evaluator"] == "mixed"
    assert meta["negative_key_set_symmetric"] and meta["conjugate_pairs"] >= 2
    assert meta["processed_positive_nodes"] + meta["omitted_positive_nodes"] == meta["positive_nodes"]
    assert meta["omitted_positive_nodes"] > 0, "the marker-ratio rule stopped early"
    pub = _pub(prog, rows)
    assert _contains(pub, pt)
    assert max(hi - lo for v in pub for lo, hi in pub[v]) <= K.MAX_WIDTH
    ok, fails, cm = PC.verify_program(r, q, prog, pub, Fr(1, 100), exec_record=meta)
    assert ok, fails[:2]
    assert cm["rechecked_retained_nodes"] == meta["processed_positive_nodes"]
    # the record's lattice deltas are re-derived by the checker; a corrupted
    # positive radius rejects
    bad = copy.deepcopy(RT.program_for("mixed", [], coll, [], 96, q))
    bad["collective"]["quadrature_tv"] = "0"
    ok2, f2, _ = PC.verify_program(r, q, _parse(bad), pub, Fr(1, 100), exec_record=meta)
    assert not ok2 and any("lattice" in x or "rebuild" in x for x in f2), f2[:2]


def test_pure_fourier_delta_comes_from_the_negative_response_bound():
    """A Fourier delta is not a probability radius: it is chosen from
    L = exp(-Y_max) so the sharp ratio's worst width fits the numerical
    allowance, and the publication is NOT widened by it."""
    fields = [0.1 * (k + 1) * (1 if k % 2 == 0 else -1) for k in range(4)]
    m = M.read_uai(w(mean_field(4, -0.22, fields)))
    r = M.restrict(m, {})
    q = set(r.free)
    Z, pt = O.exact_all_marginals(r)
    coll, rmk = CR.admit(MK.Marked.from_restricted(r, q), A.Ctx(96), prefer="fourier")[0]
    assert coll["quadrature_tv"] == 0
    L = Fr(coll["forecast"]["L_lower"])
    num_eps = K.MAX_WIDTH - 2 * K.RADII["collective_fit_and_rounding"] - 2 * K.RADII["gaussian_quadrature"] - RES
    assert Fr(coll["negative_deltas"][0]) <= L * num_eps / 4
    prog = _parse(RT.program_for("fourier", [], coll, [], 96, q))
    rows, meta = RT.execute(prog, r, q, num_eps=num_eps)
    pub = _pub(prog, rows)
    assert _contains(pub, pt)
    ok, fails, cm = PC.verify_program(r, q, prog, pub, Fr(1, 100), exec_record=meta)
    assert ok, fails[:2]
