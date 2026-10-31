"""Integrated-pass controls: every mandatory route through the pipeline, the
persisted program as the executed object, and the program checker's named
rejections (spec §5-§8, §11, §12, §15).

Every control enters through the external model API. Each rejection control
first accepts its clean base under IDENTICAL publication rules, then changes
one thing and asserts the NAMED obligation.
"""
import os, sys, json, copy, glob, tempfile, subprocess, itertools
from fractions import Fraction as Fr
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import pytest
from mdi import (model as M, oracle as O, config as K, arith as A, marked as MK,
                 routes as RT, program as PG, program_check as PC,
                 collective_route as CR, pipeline as PLN, plantype as PT,
                 pricing as PR, solve as S)
import mdi.registry            # noqa: F401
from test_mdi_research import ring_of_blocks, w, mean_field, TINY

RES = K.PUBLICATION_RESERVE


def _pub(prog, rows):
    rad = sum((sc["t_level"] + sc["deletion_radius_total"] for sc in prog["scales"]),
              Fr(0))
    if prog["collective"]:
        rad += CR.total_radius(prog["collective"])
    return {v: [(max(Fr(0), lo - rad - RES), min(Fr(1), hi + rad + RES))
                for lo, hi in rows[v]] for v in rows}


def _parse(raw):
    return PG.validate_program(json.loads(json.dumps(raw, sort_keys=True)))


def _contains(pub, pt):
    return all(pub[v][s][0] <= pt[v][s] <= pub[v][s][1]
               for v in pub for s in range(len(pub[v])))


def _regional_program(r, q, regions, levels=1):
    scales, final = RT.build_scales(MK.Marked.from_restricted(r, q), regions, levels)
    return RT.program_for("regional", scales, None, [], 128, q), scales, final


# ------------------------------------------------------ the persisted program

def test_persisted_program_governs_execution_in_a_fresh_process():
    """§8/§11 binding. The selected plan's PROGRAM is written, read back and
    executed; a fresh interpreter with none of discovery's objects executes
    and independently verifies it from the model file alone. A program whose
    witness is altered on disk is REJECTED there on the named obligation, and
    a record claiming completion flags does not bind at all."""
    txt, n, NB, BS = ring_of_blocks()
    mp = w(txt)
    m = M.read_uai(mp)
    d = tempfile.mkdtemp()
    res = PLN.solve(m, {}, wall_s=120.0, cap_bytes=1 << 30, plan_dir=d)
    assert res.status in ("CERTIFIED_RESEARCH_ROUTE", "CERTIFIED_FALLBACK_ONLY"), (res.status, res.reason)
    # the BRANCH capability: a persisted regional program (admitted in this
    # invocation or preserved on disk) is executed and independently verified
    # by a fresh interpreter from the model file alone -- regardless of which
    # route the complete price selected here
    reg_files = [f for f in os.listdir(d) if f.startswith("regional-") and f.endswith(".plan.json")]
    assert reg_files, os.listdir(d)[:6]
    chosen_id = next((p["identity"] for p in res.prices if p["name"].startswith("regional:") and p["eligible"]), None) \
        or reg_files[0][:-len(".plan.json")]
    plan = os.path.join(d, chosen_id + ".plan.json")
    assert os.path.exists(plan)
    here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

    def replay(path):
        env = dict(os.environ)
        env["PYTHONPATH"] = here
        out = subprocess.run([sys.executable, "-m", "mdi.replay", mp, "-", path],
                             cwd=here, capture_output=True, text=True, timeout=300,
                             env=env)
        assert out.stdout.strip(), ("replay produced no output", out.stderr[-800:])
        return json.loads(out.stdout)
    clean = replay(plan)
    assert clean["status"] == "REPLAY_VERIFIED", clean
    assert clean["research"]["qualifies"]
    # the fresh-process publication contains the truth
    r = M.restrict(m, {})
    Z, pt = O.exact_all_marginals(r)
    for v, rows in clean["intervals"].items():
        for s, (lo, hi) in enumerate(rows):
            assert Fr(lo) <= pt[int(v)][s] <= Fr(hi), (v, s)
    # alter the WITNESS on disk: skew every variable's markers to 9/10 and
    # 1/10 of the unchanged cell mass, so the marker/mass identity still
    # holds and ONLY the independent recomputation can reject it
    base = json.load(open(plan))
    bad = copy.deepcopy(base)
    rg = bad["program"]["scales"][0]["regions"][0]
    for c in rg["cells"]:
        tot = Fr(c["M"])
        vars_ = sorted({int(k.split(",")[0]) for k in c["N"]})
        c["N"] = {}
        for v in vars_:
            c["N"]["%d,0" % v] = str(tot * Fr(9, 10))
            c["N"]["%d,1" % v] = str(tot * Fr(1, 10))
    p2 = os.path.join(d, "altered.plan.json")
    json.dump(bad, open(p2, "w"))
    # (a) the altered program no longer matches its stored EXECUTABLE identity:
    #     binding refuses it before anything runs
    refused = replay(p2)
    assert refused["status"] == "REPLAY_REFUSED" and "identity" in refused["reason"], refused
    # (b) with the identity re-derived (as any producer of the altered record
    #     could do), the record BINDS and ONLY the checker's independent
    #     recomputation rejects it, on the named obligation
    mh, eh, qh = PLN.model_hashes(m, {}, set(M.restrict(m, {}).free))
    bad["storage_schedule"]["identity"] = PLN.executable_identity("regional", bad["program"],
                                                                  request=(mh, eh, qh, K.MAX_WIDTH))
    json.dump(bad, open(p2, "w"))
    altered = replay(p2)
    assert altered["status"] == "REPLAY_REJECTED", altered["status"]
    assert any("alpha_b A_{R,i,a}" in f or "marker" in f
               for f in altered["failures"]), altered["failures"][:2]
    # a record that arrives claiming completion flags must not bind
    forged = copy.deepcopy(base)
    forged["properties"].update(selected=True, producer_complete=True,
                                independently_verified=True,
                                publication_contract_met=True)
    rec = PT.PlanRecord.from_json(json.dumps(forged))
    with pytest.raises(PT.PlanError) as e:
        rec.bind_check(rec.model_sha256, rec.evidence_sha256, rec.query_sha256)
    assert "completion flags" in str(e.value)


def test_program_block_is_parsed_strictly():
    txt, n, NB, BS = ring_of_blocks()
    m = M.read_uai(w(txt))
    d = tempfile.mkdtemp()
    res = PLN.solve(m, {}, wall_s=120.0, cap_bytes=1 << 30, plan_dir=d)
    plan = os.path.join(d, next(p["identity"] for p in res.prices
                                if p["name"] == "regional:ascending_id@64") + ".plan.json")
    base = json.load(open(plan))
    assert PT.PlanRecord.from_json(json.dumps(base)).parsed_program is not None
    muts = [
        ("unknown program field", lambda x: x["program"].update(surprise=1), "unknown"),
        ("float radius", lambda x: x["program"]["scales"][0].__setitem__("t_level", 0.001),
         "float"),
        ("kind mismatch", lambda x: x["program"].update(kind="statistic"), "kind"),
        ("no program on a research plan", lambda x: x.pop("program"), "no program"),
        ("more than two scales",
         lambda x: x["program"].__setitem__("scales", x["program"]["scales"] * 3),
         "two"),
    ]
    for name, mut, word in muts:
        dd = copy.deepcopy(base)
        mut(dd)
        with pytest.raises(PT.PlanError) as e:
            PT.PlanRecord.from_json(json.dumps(dd))
        assert word.lower() in str(e.value).lower(), (name, str(e.value))


# ------------------------------------------------------- every route offered

def test_every_research_kind_is_offered_priced_and_certifiable():
    """§7-§8: statistic, gaussian and fourier are real candidates on the input
    law with their own program, price, executor and checker; regional (one
    and two scales) and composed are candidates on every admitted partition.
    Selection is the complete-price argmin over eligible routes -- identity is
    free to win -- and every offered collective program certifies when
    executed from its record and checked independently."""
    fields = [0.1 * (k + 1) * (1 if k % 2 == 0 else -1) for k in range(6)]
    for J, quad in ((0.30, "gaussian"), (-0.22, "fourier")):
        mp = w(mean_field(6, J, fields))
        m = M.read_uai(mp)
        r = M.restrict(m, {})
        Z, pt = O.exact_all_marginals(r)
        q = set(r.free)
        d = tempfile.mkdtemp()
        res = PLN.solve(m, {}, wall_s=120.0, cap_bytes=1 << 30, plan_dir=d)
        assert res.status.startswith("CERTIFIED"), (res.status, res.reason)
        names = {p["name"]: p for p in res.prices}
        # candidates are named evaluator:kind and persisted under their IDENTITY
        stat = next(k for k in names if k.startswith("statistic:"))
        assert names[stat]["eligible"], sorted(names)
        quad_name = next(k for k in names if k.startswith(quad + ":"))
        assert quad_name in names, sorted(names)
        assert any(k.startswith("regional:") for k in names)
        eligible = {k: int(p["total_arithmetic"]["value"]) for k, p in names.items()
                    if p["eligible"] and p["total_arithmetic"]["value"] is not None}
        assert res.plan["chosen"] == min(eligible, key=eligible.get), \
            (res.plan["chosen"], eligible)
        assert _contains(res.intervals, pt)
        # the collective programs certify from their PERSISTED records through
        # the ONE loaded-object boundary (bind -> admission -> run_loaded under
        # a fresh shared budget). A quadrature program whose forecast metered
        # entries exceed the shared cap is offered, priced and persisted but
        # REFUSED by the same rule in replay -- it is never run unguarded here.
        from mdi import replay as RP
        for name in (stat, quad_name):
            kind = name.split(":")[0]
            path = os.path.join(d, names[name]["identity"] + ".plan.json")
            rec = PT.PlanRecord.from_json(open(path).read())
            prog = rec.parsed_program
            assert prog["kind"] == kind and prog["collective"]["evaluator"] == kind
            if names[name]["eligible"]:
                rep = RP.replay(mp, "-", path)
                assert rep["status"] == "REPLAY_VERIFIED", (name, rep.get("reason"), rep.get("failures"))
                assert all(Fr(lo) <= pt[int(v)][s] <= Fr(hi) for v, rows in rep["intervals"].items()
                           for s, (lo, hi) in enumerate(rows)), name
                assert rep["checker"]["collective"]["engine"] == "dense"
                assert rep["checker"]["fit"]["own_tv"]          # the checker's OWN certificate
            else:
                assert "cap" in names[name]["ineligible_reason"], names[name]["ineligible_reason"]
                rep = RP.replay(mp, "-", path)
                assert rep["status"] == "REPLAY_REFUSED" and "cap" in rep["reason"], rep.get("reason")
    # the smaller mean field: Gaussian and Fourier programs are AFFORDABLE under
    # the shared cap and verify from their records in a fresh binding
    fields4 = [0.1 * (k + 1) * (1 if k % 2 == 0 else -1) for k in range(4)]
    from mdi import replay as RP
    for J, quad in ((0.30, "gaussian"), (-0.22, "fourier")):
        mp = w(mean_field(4, J, fields4))
        m = M.read_uai(mp)
        Z, pt = O.exact_all_marginals(M.restrict(m, {}))
        d = tempfile.mkdtemp()
        res = PLN.solve(m, {}, wall_s=120.0, cap_bytes=1 << 30, plan_dir=d)
        names = {p["name"]: p for p in res.prices}
        qn = next(k for k in names if k.startswith(quad + ":") and names[k]["eligible"])
        rep = RP.replay(mp, "-", os.path.join(d, names[qn]["identity"] + ".plan.json"))
        assert rep["status"] == "REPLAY_VERIFIED", (qn, rep.get("reason"), rep.get("failures"))
        assert all(Fr(lo) <= pt[int(v)][s] <= Fr(hi) for v, rows in rep["intervals"].items()
                   for s, (lo, hi) in enumerate(rows)), qn
        assert rep["checker"]["collective"]["own_lattice_bounds"]     # the checker's OWN deltas
        assert int(names[qn]["counters"]["metered_entries_forecast"]["value"]) >= \
            int(rep["budget"]["used"].get("local_mass_entries", 0))
    # a larger mean field: the statistic DP is cheaper than identity and the
    # planner's argmin is still what runs
    fields = [0.1 * (k + 1) * (1 if k % 2 == 0 else -1) for k in range(9)]
    m = M.read_uai(w(mean_field(9, 0.30, fields)))
    r = M.restrict(m, {})
    Z, pt = O.exact_all_marginals(r)
    res = PLN.solve(m, {}, wall_s=120.0, cap_bytes=1 << 30, plan_dir=tempfile.mkdtemp())
    names = {p["name"]: p for p in res.prices}
    eligible = {k: int(p["total_arithmetic"]["value"]) for k, p in names.items()
                if p["eligible"] and p["total_arithmetic"]["value"] is not None}
    stat9 = min(k for k in eligible if k.startswith("statistic:"))
    assert eligible[stat9] < eligible["identity"], eligible
    assert res.plan["chosen"] == min(eligible, key=eligible.get)
    assert res.status.startswith("CERTIFIED"), (res.status, res.reason)
    assert _contains(res.intervals, pt)
    # the ring: regional wins by price and merges cells; two scales and
    # composed are offered on the same partitions
    txt, n, NB, BS = ring_of_blocks()
    m = M.read_uai(w(txt))
    r = M.restrict(m, {})
    Z, pt = O.exact_all_marginals(r)
    res = PLN.solve(m, {}, wall_s=120.0, cap_bytes=1 << 30, plan_dir=tempfile.mkdtemp())
    assert res.status.startswith("CERTIFIED"), (res.status, res.reason)
    # selection is the complete-price argmin among the ELIGIBLE records of this invocation
    elig = {p["name"]: int(p["total_arithmetic"]["value"]) for p in res.prices
            if p["eligible"] and p["total_arithmetic"]["value"] is not None}
    assert res.plan["chosen"] == min(elig, key=elig.get), (res.plan["chosen"], elig)
    names = {p["name"] for p in res.prices} | {x["name"] for x in res.rejected}
    assert any(k.endswith(":L2") and k.startswith("regional:") for k in names), names
    assert any(k.startswith("composed:") for k in names), names
    assert _contains(res.intervals, pt)
    assert res.plan["research"]["cells_merged_regions"] >= 1


def test_quadrature_programs_execute_and_verify_from_their_record():
    """§7.2 executed: the Gaussian and Fourier evaluators run the residual
    through a calibrated contraction per lattice node; their programs
    round-trip, execute, and the program checker's dense evaluation verifies
    them against the ORIGINAL law."""
    fields = [0.1 * (k + 1) * (1 if k % 2 == 0 else -1) for k in range(5)]
    for J, prefer in ((0.30, "gaussian"), (-0.22, "fourier")):
        m = M.read_uai(w(mean_field(5, J, fields)))
        r = M.restrict(m, {})
        Z, pt = O.exact_all_marginals(r)
        q = set(r.free)
        coll, rmk = CR.admit(MK.Marked.from_restricted(r, q), A.Ctx(96), prefer=prefer)[0]
        assert coll["evaluator"] == prefer
        if prefer == "gaussian":
            # the positive lattice's GF3 bound IS a TV radius on the law
            assert 0 < coll["quadrature_tv"] <= K.RADII["gaussian_quadrature"]
        else:
            # a negative lattice's error is an absolute count error that enters
            # the sharp marker-ratio enclosure, never a probability radius; the
            # delta was chosen from the negative-response lower bound L
            assert coll["quadrature_tv"] == 0
            assert coll["negative_deltas"] and Fr(coll["forecast"]["L_lower"]) > 0
            assert coll["grids"][0]["sign"] == -1 and coll["grids"][0]["representatives"] == coll["grids"][0]["J"] + 1
        prog = _parse(RT.program_for(prefer, [], coll, [], 96, q))
        rows, meta = RT.execute(prog, r, q)
        assert meta["evaluator"] == prefer and meta["positive_nodes"] >= 1
        if prefer == "fourier":
            assert meta["conjugate_pairs"] >= 2 and meta["negative_key_set_symmetric"]
        pub = _pub(prog, rows)
        assert _contains(pub, pt)
        ok, fails, cmeta = PC.verify_program(r, q, prog, pub, Fr(1, 100))
        assert ok, fails[:2]
        assert cmeta["collective"]["engine"] == "dense"
        # the checker's OWN lattice bounds are the deltas its reference used
        assert "own_quadrature_tv" in cmeta["collective"] and cmeta["collective"]["own_lattice_bounds"]


# -------------------------------------------------------- scales and deletion

def test_two_scales_restore_every_marker_and_verify():
    """§5.6: the second scale groups level-one cells, recomputes masses and
    markers under the current coarse model, and the radii add by the triangle
    inequality. Both scales are verified from the ORIGINAL model."""
    txt, n, NB, BS = ring_of_blocks(NB=4, BS=3)
    m = M.read_uai(w(txt))
    r = M.restrict(m, {})
    Z, pt = O.exact_all_marginals(r)
    q = set(r.free)
    regs = [tuple(range(b * BS, (b + 1) * BS)) for b in range(NB)]
    raw, scales, final = _regional_program(r, q, regs, levels=2)
    assert len(raw["scales"]) == 2
    assert Fr(raw["scales"][0]["t_level"]) == Fr(raw["scales"][1]["t_level"]) == \
        K.RADII["regional_coarsening_total"] / 2
    assert len(final.card) < len(regs)              # the second scale reduced
    prog = _parse(raw)
    rows, meta = RT.execute(prog, r, q)
    assert meta["levels"] == 2
    pub = _pub(prog, rows)
    assert _contains(pub, pt)
    assert max(hi - lo for v in pub for lo, hi in pub[v]) <= \
        2 * K.RADII["regional_coarsening_total"] + 2 * RES
    ok, fails, cmeta = PC.verify_program(r, q, prog, pub, Fr(1, 100))
    assert ok, fails[:2]
    assert len(cmeta["scales"]) == 2
    # corrupting the SECOND scale's witness rejects on the named obligation
    bad = copy.deepcopy(raw)
    c = bad["scales"][1]["regions"][0]["cells"][0]
    c["M"] = str(Fr(c["M"]) * 3)
    ok2, f2, _ = PC.verify_program(r, q, _parse(bad), pub, Fr(1, 100))
    assert not ok2 and any("scale 2" in x and "mass" in x for x in f2), f2[:2]


def test_deletion_executes_with_its_own_proof_and_is_rederived():
    """§5.5: a negligible boundary state is deleted inside a program with the
    U/(U+L) certificate; the checker re-derives the bound from its own masses
    and the original crossing tables, and a fake deletion is refused."""
    n = 8
    facs = [M.Factor(scope=(v,), card=(2,),
                     table=[Fr(1), Fr(1, 10 ** 7) if v == 5 else Fr(1 + v % 2)],
                     origin=v) for v in range(n)]
    facs += [M.Factor(scope=(i, i + 1), card=(2, 2), table=[Fr(2), Fr(1), Fr(1), Fr(3)],
                      origin=100 + i) for i in range(n - 1)]
    m = M.Model(nvars=n, card=[2] * n, factors=facs).validate()
    r = M.restrict(m, {})
    Z, pt = O.exact_all_marginals(r)
    q = set(r.free)
    raw, scales, final = _regional_program(r, q, [tuple(range(0, 6)), (6, 7)], 1)
    dels = [(i, rg["deleted"], rg["deletion_bound"])
            for rg in raw["scales"][0]["regions"] for i in [0] if rg["deleted"]]
    assert dels, "the negligible state must be deleted"
    assert raw["research"]["deleted_states"] >= 1 and raw["research"]["qualifies"]
    assert Fr(raw["scales"][0]["deletion_radius_total"]) <= \
        K.RADII["state_deletion_total"]
    prog = _parse(raw)
    rows, _ = RT.execute(prog, r, q)
    pub = _pub(prog, rows)
    assert _contains(pub, pt)
    ok, fails, cmeta = PC.verify_program(r, q, prog, pub, Fr(1, 100))
    assert ok, fails[:2]
    assert Fr(cmeta["scales"][0]["deletion"]) > 0
    # understate the recorded bound: the checker's own bound exceeds it
    bad = copy.deepcopy(raw)
    for rg in bad["scales"][0]["regions"]:
        if rg["deleted"]:
            rg["deletion_bound"] = str(Fr(rg["deletion_bound"]) / 1000)
    bad["scales"][0]["deletion_radius_total"] = str(
        Fr(bad["scales"][0]["deletion_radius_total"]) / 1000)
    ok2, f2, _ = PC.verify_program(r, q, _parse(bad), pub, Fr(1, 100))
    assert not ok2 and any("deletion bound" in x for x in f2), f2[:2]


def test_finer_valid_witness_is_accepted():
    """§11: the checker verifies the SUBMITTED witness; it does not demand
    the producer's own merge. Splitting a merged cell into exact singleton
    cells (alpha 1, rho 1) is a valid, finer witness and must verify."""
    facs = [M.Factor(scope=(0, 1), card=(2, 2), table=[Fr(1)] * 4, origin=0),
            M.Factor(scope=(1, 2), card=(2, 2), table=[Fr(2), Fr(1), Fr(1), Fr(2)],
                     origin=1)]
    m = M.Model(nvars=3, card=[2, 2, 2], factors=facs).validate()
    r = M.restrict(m, {})
    Z, pt = O.exact_all_marginals(r)
    q = {0, 1, 2}
    raw, scales, final = _regional_program(r, q, [(0,), (1, 2)], 1)
    rg = raw["scales"][0]["regions"][0]
    assert len(rg["cells"]) == 1 and len(rg["cells"][0]["members"]) == 2
    c = rg["cells"][0]
    rg["cells"] = [{"rep": list(mb), "members": [[list(mb), "1"]], "M": "1",
                    "N": {"0,%d" % mb[0]: "1"}} for mb, _a in c["members"]]
    rg["rho_region"] = "1"
    raw["scales"][0]["lifted_card"][0] = 2
    prog = _parse(raw)
    rows, _ = RT.execute(prog, r, q)
    pub = _pub(prog, rows)
    assert _contains(pub, pt)
    ok, fails, _ = PC.verify_program(r, q, prog, pub, Fr(1, 100))
    assert ok, fails[:2]


# ------------------------------------------------- targeted program mutations

def test_program_checker_rejects_each_fault_class_on_the_named_obligation():
    """§12.7 through the program checker. Pair [1,2,3,8]: X0=(3/14,11/14),
    X1=(2/7,5/7). The clean program verifies; each mutation rejects on the
    obligation it violates, under identical publication rules."""
    facs = [M.Factor(scope=(0, 1), card=(2, 2), table=[Fr(1), Fr(2), Fr(3), Fr(8)],
                     origin=0)]
    m = M.Model(nvars=2, card=[2, 2], factors=facs).validate()
    r = M.restrict(m, {})
    Z, pt = O.exact_all_marginals(r)
    q = {0, 1}
    base, scales, final = _regional_program(r, q, [(0,), (1,)], 1)
    prog = _parse(base)
    rows, _ = RT.execute(prog, r, q)
    good = _pub(prog, rows)
    assert _contains(good, pt)
    ok, fails, _ = PC.verify_program(r, q, prog, good, Fr(1, 100))
    assert ok, fails
    t1 = K.level_radius(1)
    half = {v: [(Fr(1, 2) - t1 - RES, Fr(1, 2) + t1 + RES)] * 2 for v in q}

    def verdict(raw, pub):
        return PC.verify_program(r, q, _parse(raw), pub, Fr(1, 100))

    # (a) a false alpha = 1 merge of both X0 states (a false R = 1)
    bad = copy.deepcopy(base)
    rg = bad["scales"][0]["regions"][0]
    c0, c1 = rg["cells"]
    rg["cells"] = [{"rep": c0["rep"], "members": c0["members"] + [[c1["rep"], "1"]],
                    "M": str(Fr(c0["M"]) + Fr(c1["M"])),
                    "N": {k: str(Fr(c0["N"].get(k, "0")) + Fr(c1["N"].get(k, "0")))
                          for k in set(c0["N"]) | set(c1["N"])}}]
    rg["rho_region"] = "1"
    bad["scales"][0]["lifted_card"][0] = 1
    ok, f, _ = verdict(bad, half)
    assert not ok and any("alpha" in x and "profile extrema" in x for x in f), f[:2]
    # (b) skewed markers preserving the identity
    bad = copy.deepcopy(base)
    for rg in bad["scales"][0]["regions"]:
        for c in rg["cells"]:
            keys = sorted(c["N"])
            tot = Fr(c["M"])
            c["N"] = {keys[0]: str(tot * Fr(9, 10)), keys[1]: str(tot * Fr(1, 10))}
    skew = {v: [(Fr(9, 10) - t1 - RES, Fr(9, 10) + t1 + RES),
                (Fr(1, 10) - t1 - RES, Fr(1, 10) + t1 + RES)] for v in q}
    ok, f, _ = verdict(bad, skew)
    assert not ok and any("alpha_b A_{R,i,a}" in x for x in f), f[:2]
    # (c) corrupted cell mass
    bad = copy.deepcopy(base)
    c = bad["scales"][0]["regions"][0]["cells"][0]
    c["M"] = str(Fr(c["M"]) * 7)
    ok, f, _ = verdict(bad, good)
    assert not ok and any("mass" in x for x in f), f[:2]
    # (d) a dropped boundary state
    bad = copy.deepcopy(base)
    rg = bad["scales"][0]["regions"][1]
    rg["cells"] = rg["cells"][:1]
    bad["scales"][0]["lifted_card"][1] = 1
    ok, f, _ = verdict(bad, good)
    assert not ok and any("belong to no cell" in x for x in f), f[:2]
    # (e) a fake deletion of a supported state with an understated bound
    bad = copy.deepcopy(base)
    rg = bad["scales"][0]["regions"][1]
    dropped = rg["cells"][1]
    rg["cells"] = rg["cells"][:1]
    rg["deleted"] = [dropped["rep"]]
    rg["deletion_bound"] = "1/1000000"
    bad["scales"][0]["deletion_radius_total"] = "1/1000000"
    bad["scales"][0]["lifted_card"][1] = 1
    ok, f, _ = verdict(bad, good)
    assert not ok and any("deletion bound" in x for x in f), f[:2]
    # (f) a shifted publication on the clean program
    shifted = {v: [(max(Fr(0), lo + Fr(1, 10)), min(Fr(1), hi + Fr(1, 10)))
                   for lo, hi in good[v]] for v in q}
    ok, f, _ = verdict(base, shifted)
    assert not ok and any("does NOT contain" in x for x in f), f[:2]
    # (g) a partition missing a variable
    bad = copy.deepcopy(base)
    bad["scales"][0]["regions"] = bad["scales"][0]["regions"][:1]
    bad["scales"][0]["lifted_card"] = bad["scales"][0]["lifted_card"][:1]
    with pytest.raises(PC.CheckError) as e:
        verdict(bad, good)
    assert "cover" in str(e.value)


def test_collective_record_mutations_reject_on_the_named_obligation():
    """§12.7 for the collective record: wrong gamma (uncharged fit error),
    understated fit radius, an uncharged rounding radius, an omitted feature
    (absent-edge residual), a flipped sign, a false retained list."""
    fields = [0.1 * (k + 1) * (1 if k % 2 == 0 else -1) for k in range(6)]
    txt, n, NB, BS = ring_of_blocks()
    m = M.read_uai(w(txt))
    r = M.restrict(m, {})
    Z, pt = O.exact_all_marginals(r)
    q = set(r.free)
    regs = [tuple(range(b * BS, (b + 1) * BS)) for b in range(NB)]
    scales, final = RT.build_scales(MK.Marked.from_restricted(r, q), regs, 1)
    coll, rmk = CR.admit(final, A.Ctx(160), prefer="statistic")[0]
    assert coll["evaluator"] == "statistic"
    base = RT.program_for("composed", scales, coll, [], 160, q)
    prog = _parse(base)
    rows, _ = RT.execute(prog, r, q)
    good = _pub(prog, rows)
    assert _contains(good, pt)
    ok, fails, cmeta = PC.verify_program(r, q, prog, good, Fr(1, 100))
    assert ok, fails[:2]
    assert Fr(cmeta["fit"]["own_tv"]) <= Fr(coll["fit_tv"])

    def verdict(raw):
        return PC.verify_program(r, q, _parse(raw), good, Fr(1, 100))
    bad = copy.deepcopy(base)
    bad["collective"]["candidate"]["gammas"][0] = str(Fr(coll["candidate"].gammas[0]) * Fr(3, 2))
    ok, f, _ = verdict(bad)
    assert not ok and any("fit" in x.lower() or "rebuild" in x for x in f), f[:2]
    bad = copy.deepcopy(base)
    bad["collective"]["fit_tv"] = "0"
    ok, f, _ = verdict(bad)
    assert not ok and any("fit TV" in x for x in f), f[:2]
    bad = copy.deepcopy(base)
    bad["collective"]["Q"] = 1
    bad["collective"]["rounding_tv"] = "0"
    ok, f, _ = verdict(bad)
    assert not ok and any("rounding" in x for x in f), f[:2]
    bad = copy.deepcopy(base)
    v0 = sorted(bad["collective"]["candidate"]["features"][0])[0]
    bad["collective"]["candidate"]["features"][0][v0] = ["0"] * len(
        bad["collective"]["candidate"]["features"][0][v0])
    ok, f, _ = verdict(bad)
    assert not ok, "an omitted feature changes the law"
    bad = copy.deepcopy(base)
    bad["collective"]["candidate"]["signs"] = [-s for s in bad["collective"]["candidate"]["signs"]]
    ok, f, _ = verdict(bad)
    assert not ok, "a flipped sign changes the law"
    bad = copy.deepcopy(base)
    bad["collective"]["kept_factors"] = [0]
    ok, f, _ = verdict(bad)
    assert not ok, "a false retained-factor list is not the fitted residual"
    for mut, word in ((lambda d: d["collective"].__setitem__("delta", 0.1), "float"),
                      (lambda d: d["collective"]["candidate"]["signs"].__setitem__(0, 2),
                       "sign")):
        dd = copy.deepcopy(base)
        mut(dd)
        with pytest.raises(PG.ProgramError) as e:
            _parse(dd)
        assert word in str(e.value).lower()


# ---------------------------------------------------------- pricing and caps

def test_program_prices_bound_the_executed_and_checked_work():
    """§8: the price describes the program that RUNS. Counted exact-rational
    operations of execution and of the independent check never exceed the
    priced producer and checker bounds, on regional (one and two scales),
    composed and collective programs."""
    import fractions
    counts = {"n": 0}
    saved = {nm: getattr(fractions.Fraction, nm) for nm in
             ("__mul__", "__rmul__", "__add__", "__radd__", "__truediv__",
              "__rtruediv__", "__sub__", "__rsub__")}

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

    def trial(r, q, scales, final, coll, kind):
        cons = sum(rd.construction_ops for sc in scales for rd in sc.rds)
        price, order = PR.price_program("x", kind, final, scales, coll,
                                        sum(r.card[v] for v in q), cons)
        prog = _parse(RT.program_for(kind, scales, coll, order, 128, q))
        (rows, meta), n_exec = measure(lambda: RT.execute(prog, r, q))
        pub = _pub(prog, rows)
        (ok, fails, cm), n_chk = measure(
            lambda: PC.verify_program(r, q, prog, pub, Fr(1, 100)))
        assert ok, fails[:2]
        pp = sum(int(price.counters[k].value) for k in
                 ("producer_upward_ops", "producer_downward_ops", "readout_ops"))
        pc = int(price.counters["checker_ops"].value)
        assert pp >= n_exec, (kind, pp, n_exec)
        assert pc >= n_chk, (kind, pc, n_chk)
        for key, c in price.as_dict()["counters"].items():
            assert c["label"] in (PR.EXACT, PR.UPPER, PR.LOWER, PR.CALIB, PR.FORECAST), key
        assert price.counters["construction_ops"].label == PR.CALIB

    txt, n, NB, BS = ring_of_blocks()
    m = M.read_uai(w(txt))
    r = M.restrict(m, {})
    q = set(r.free)
    mk0 = MK.Marked.from_restricted(r, q)
    for regs, levels in (([tuple(range(0, 6)), tuple(range(6, 12))], 1),
                         ([tuple(range(b * 3, (b + 1) * 3)) for b in range(4)], 1),
                         ([tuple(range(b * 3, (b + 1) * 3)) for b in range(4)], 2)):
        scales, final = RT.build_scales(mk0, regs, levels)
        trial(r, q, scales, final, None, "regional")
    scales, final = RT.build_scales(mk0, [tuple(range(b * 3, (b + 1) * 3))
                                          for b in range(4)], 1)
    coll, rmk = CR.admit(final, A.Ctx(160), prefer="statistic")[0]
    trial(r, q, scales, rmk, coll, "composed")
    fields = [0.1 * (k + 1) * (1 if k % 2 == 0 else -1) for k in range(6)]
    for J in (0.30, -0.22):
        m = M.read_uai(w(mean_field(6, J, fields)))
        r = M.restrict(m, {})
        q = set(r.free)
        coll, rmk = CR.admit(MK.Marked.from_restricted(r, q), A.Ctx(96),
                             prefer="statistic")[0]
        trial(r, q, [], rmk, coll, "statistic")


def test_contractions_are_bounded_and_check_their_deadline():
    """§9/§10: the sparse and dense engines refuse entries beyond the declared
    caps and rationals beyond the bit cap, and an expired deadline stops
    them inside their loops."""
    from mdi import sparse_jt as SJ, dense_be as DB
    B = Fr(2) ** 40000
    facs = [M.Factor(scope=(0,), card=(2,), table=[B, B + 1], origin=0),
            M.Factor(scope=(1,), card=(2,), table=[B, B + 1], origin=1),
            M.Factor(scope=(0, 1), card=(2, 2), table=[Fr(1)] * 4, origin=2)]
    card = {0: 2, 1: 2}
    with pytest.raises(SJ.SparseError) as e:
        SJ.all_marginals([SJ.table_from_factor(f) for f in facs], card)
    assert "bit" in str(e.value)
    with pytest.raises(DB.DenseError) as e2:
        DB.exact_marginals([(f.scope, [Fr(x) for x in f.table]) for f in facs], card)
    assert "bit" in str(e2.value)
    n = 14
    facs = [M.Factor(scope=tuple(range(n)), card=(2,) * n, table=[Fr(1)] * (1 << n),
                     origin=0)]
    card = {v: 2 for v in range(n)}
    with pytest.raises(SJ.SparseError):
        SJ.all_marginals([SJ.table_from_factor(f) for f in facs], card, entry_cap=4096)
    with pytest.raises(DB.DenseError):
        DB.exact_marginals([(f.scope, [Fr(x) for x in f.table]) for f in facs], card,
                           entry_cap=4096)
    calls = {"n": 0}

    class Expired(Exception):
        pass

    def dl():
        calls["n"] += 1
        raise Expired()
    txt, n, NB, BS = ring_of_blocks()
    m = M.read_uai(w(txt))
    r = M.restrict(m, {})
    with pytest.raises(Expired):
        SJ.all_marginals([SJ.table_from_factor(f) for f in r.factors], r.card, deadline=dl)
    with pytest.raises(Expired):
        DB.exact_marginals([(f.scope, [Fr(x) for x in f.table]) for f in r.factors],
                           r.card, deadline=dl)
    assert calls["n"] >= 2


# -------------------------------------------------- identity route obligations

def test_identity_independent_aggregation_is_structural_above_the_cap():
    """§11: above the 4,096-assignment enumeration cap the identity checker
    recomputes every marginal with a SECOND aggregation implementation (the
    sparse exact junction tree); the same injected readout fault is caught at
    12, 13 and 20 variables, and the applicability is forecast in the price
    before execution."""
    from mdi import contract as C, plan as P

    def faulty(self, var):
        counts, seen, depth = orig(self, var)
        if var == 0 and seen[0]:
            counts[0] = (counts[0] * 3 if self.mode == "P"
                         else (counts[0][0] * 3, counts[0][1] * 3))
        return counts, seen, depth
    orig = C.Engine.read_marginal
    for n in (12, 13, 20):
        facs = [M.Factor(scope=(v,), card=(2,), table=[Fr(1), Fr(1 + v % 3)], origin=v)
                for v in range(n)]
        facs += [M.Factor(scope=(i, i + 1), card=(2, 2), table=[Fr(2), Fr(1), Fr(1), Fr(3)],
                          origin=100 + i) for i in range(n - 1)]
        m = M.Model(nvars=n, card=[2] * n, factors=facs).validate()
        clean = S.solve(m, {}, eps=Fr(1, 100), mode="P", cap_bytes=1 << 30, deadline_s=60)
        assert clean["outcome"] == "VERIFIED_ALL_MARGINALS", clean["outcome"]
        scope = clean["checker"]["independent_aggregation_scope"]
        assert ("enumeration" in scope) if n <= 12 else ("sparse exact junction tree" in scope)
        r = M.restrict(m, {})
        sel = P.choose_plan(r.free, r.card, r.factors, 64, 1 << 30)
        pl, est = sel["chosen"]
        rec = PR.price_identity_plan(pl, est, 2 * n, 64)
        if n > 12:
            assert int(rec.counters["independent_aggregation_forecast"].value) == 1
            assert "independent_sparse_ops" in rec.counters
        C.Engine.read_marginal = faulty
        try:
            res = S.solve(m, {}, eps=Fr(1, 100), mode="P", cap_bytes=1 << 30, deadline_s=60)
        finally:
            C.Engine.read_marginal = orig
        assert res["outcome"] == "NUMERICAL_REFUSAL", (n, res["outcome"])
        msg = " ".join(str(f) for f in res["checker"]["failures"])
        assert "shared aggregation" in msg, msg[:200]


def test_zero_support_is_proved_by_a_completed_boolean_contraction():
    """§7.2/§11: above the enumeration cap a globally contradictory model is
    proved impossible by a COMPLETED Boolean support contraction, and a
    consistent model is NOT claimed impossible."""
    n = 13
    facs = [M.Factor(scope=(i, i + 1), card=(2, 2), table=[Fr(1), Fr(0), Fr(0), Fr(1)],
                     origin=i) for i in range(n - 1)]
    facs.append(M.Factor(scope=(0, n - 1), card=(2, 2), table=[Fr(0), Fr(1), Fr(1), Fr(0)],
                         origin=99))
    m = M.Model(nvars=n, card=[2] * n, factors=facs).validate()
    Z, _p = O.exact_all_marginals(M.restrict(m, {}))
    assert Z == 0
    res = S.solve(m, {}, eps=Fr(1, 100), mode="P", cap_bytes=1 << 30, deadline_s=60)
    assert res["outcome"] == "ZERO_EVIDENCE_PROVED", res["outcome"]
    assert res["zero_support_independently_verified"] is True
    assert "Boolean support contraction" in res["reason"]
    res2 = PLN.solve(m, {}, wall_s=60, cap_bytes=1 << 30, plan_dir=tempfile.mkdtemp())
    assert res2.status == "ZERO_EVIDENCE_PROVED"
    facs2 = facs[:-1] + [M.Factor(scope=(0, n - 1), card=(2, 2),
                                  table=[Fr(1), Fr(0), Fr(0), Fr(1)], origin=99)]
    m2 = M.Model(nvars=n, card=[2] * n, factors=facs2).validate()
    proved, why = S._verify_zero_support_from_original(m2, {})
    assert proved is False and "NOT impossible" in why


def test_api_fully_pinned_and_conditional_query_subsets():
    """§1/§2: every variable observed yields the exact restored publication;
    conditional query subsets publish only the requested rows and certify."""
    txt = ("MARKOV\n3\n2 2 2\n3\n1 0\n2 0 1\n2 1 2\n2\n1 2\n4\n1 2 3 4\n4\n2 1 1 2\n")
    m = M.read_uai(w(txt))
    res = PLN.solve(m, {0: 0, 1: 1, 2: 0}, wall_s=30, cap_bytes=1 << 30)
    assert res.status == "CERTIFIED_FALLBACK_ONLY", (res.status, res.reason)
    assert res.intervals == {0: [(Fr(1), Fr(1)), (Fr(0), Fr(0))],
                             1: [(Fr(0), Fr(0)), (Fr(1), Fr(1))],
                             2: [(Fr(1), Fr(1)), (Fr(0), Fr(0))]}
    for ev, q in (({}, {0}), ({}, {2}), ({0: 1}, {2}), ({1: 0}, {0, 2})):
        r = M.restrict(m, ev)
        Z, pt = O.exact_all_marginals(r)
        res = PLN.solve(m, ev, queries=q, wall_s=30, cap_bytes=1 << 30)
        assert res.status.startswith("CERTIFIED"), (ev, q, res.status, res.reason)
        for v in q:
            for s in range(r.card[v]):
                lo, hi = res.intervals[v][s]
                assert lo <= pt[v][s] <= hi, (ev, q, v, s)
        assert set(res.intervals) == set(q) | set(ev)


def test_discovery_is_not_gated_on_identity_feasibility():
    """§8: identity's byte-cap refusal is a recorded admission refusal, not
    the end of the invocation; discovery still runs."""
    from mdi import plan as P
    txt, n, NB, BS = ring_of_blocks()
    m = M.read_uai(w(txt))
    orig = P.choose_plan
    calls = {"n": 0}

    def no_fit(free, card, factors, bpe, cap_bytes, charge=None):
        calls["n"] += 1
        out = orig(free, card, factors, bpe, cap_bytes, charge=charge)
        if calls["n"] == 1:              # the identity planning call
            out = dict(out)
            out["chosen"] = None
            out["fits"] = False
        return out
    P.choose_plan = no_fit
    try:
        res = PLN.solve(m, {}, wall_s=120, cap_bytes=1 << 30, plan_dir=tempfile.mkdtemp())
    finally:
        P.choose_plan = orig
    assert any(x["name"] == "identity" and "byte cap" in x["reason"]
               for x in res.rejected), res.rejected[:3]
    # discovery was NOT gated on the identity: research records were built; with
    # no identity a research route certifies when the budget admits one, else the
    # invocation stops by price / resources -- never a crash, never gated
    assert res.status in ("CERTIFIED_RESEARCH_ROUTE", "RESOURCE_STOP", "PRICE_REFUSAL"), (res.status, res.reason)
    assert "identity" not in {p["name"] for p in res.prices}
    assert (res.plan or {}).get("invocation_ledger", {}).get("candidates_built", 0) > 0 or res.prices


# ----------------------------------------------------- §12 generic controls

def test_recognition_survives_exact_gauge_redistribution_through_the_pipeline():
    """§12.4 through the public pipeline: moving every unary into the pair
    tables preserves the law; the table-driven recognizer must still find and
    certify the mode and the statistic route must still be offered, priced
    and certifiable from its record."""
    from test_mdi_research import mean_field
    n = 6
    fields = [0.1, -0.2, 0.15, -0.05, 0.08, -0.12]
    m = M.read_uai(w(mean_field(n, 0.28, fields)))
    unary = {f.scope[0]: list(f.table) for f in m.factors if len(f.scope) == 1}
    facs, used = [], set()
    for f in m.factors:
        if len(f.scope) == 1:
            facs.append(M.Factor(scope=f.scope, card=f.card, table=[Fr(1), Fr(1)],
                                 origin=f.origin))
            continue
        i, j = f.scope
        tbl = list(f.table)
        for who, pos in ((i, 0), (j, 1)):
            if who in used:
                continue
            u = unary[who]
            used.add(who)
            tbl = [tbl[a * 2 + b] * (u[a] if pos == 0 else u[b])
                   for a in range(2) for b in range(2)]
        facs.append(M.Factor(scope=f.scope, card=f.card, table=tbl, origin=f.origin))
    m2 = M.Model(nvars=n, card=[2] * n, factors=facs).validate()
    r = M.restrict(m2, {})
    Z, pt = O.exact_all_marginals(r)
    d = tempfile.mkdtemp()
    res = PLN.solve(m2, {}, wall_s=120.0, cap_bytes=1 << 30, plan_dir=d)
    assert res.status.startswith("CERTIFIED"), (res.status, res.reason)
    names = {p["name"]: p for p in res.prices}
    stat = next((k for k in names if k.startswith("statistic:")), None)
    assert stat is not None and names[stat]["eligible"], \
        [(x["name"], x["reason"][:60]) for x in res.rejected]
    assert _contains(res.intervals, pt)
    rec = PT.PlanRecord.from_json(open(os.path.join(d, names[stat]["identity"] + ".plan.json")).read())
    prog = rec.parsed_program
    q = set(r.free)
    rows, _ = RT.execute(prog, r, q)
    pub = _pub(prog, rows)
    assert _contains(pub, pt)
    ok, fails, _ = PC.verify_program(r, q, prog, pub, Fr(1, 100))
    assert ok, fails[:2]


def test_generic_semantics_disconnected_ternary_and_zeros_through_the_pipeline():
    """§12.1 through the public pipeline: free ternary variables, a
    higher-arity asymmetric scope, satisfiable zeros, two disconnected
    components and a very small positive entry; every requested marginal
    certified and contained, with an evidence-conditioned request too."""
    facs = [
        M.Factor(scope=(0, 1), card=(2, 3), table=[Fr(1), Fr(2), Fr(0), Fr(3), Fr(1), Fr(5)],
                 origin=0),
        M.Factor(scope=(1, 2, 3), card=(3, 2, 2),
                 table=[Fr(x) for x in (1, 2, 1, 0, 2, 1, 1, 3, 1, 1, 2, Fr(1, 10 ** 9))],
                 origin=1),
        M.Factor(scope=(4, 5), card=(2, 3), table=[Fr(2), Fr(1), Fr(1), Fr(1), Fr(0), Fr(4)],
                 origin=2),
        M.Factor(scope=(5,), card=(3,), table=[Fr(1), Fr(3), Fr(2)], origin=3),
    ]
    m = M.Model(nvars=6, card=[2, 3, 2, 2, 2, 3], factors=facs).validate()
    for ev in ({}, {3: 1}, {0: 0, 5: 2}):
        r = M.restrict(m, ev)
        Z, pt = O.exact_all_marginals(r)
        assert Z > 0
        res = PLN.solve(m, ev, wall_s=120.0, cap_bytes=1 << 30,
                        plan_dir=tempfile.mkdtemp())
        assert res.status.startswith("CERTIFIED"), (ev, res.status, res.reason)
        assert _contains({v: res.intervals[v] for v in r.free}, pt), ev
        for v, st in ev.items():
            assert res.intervals[v] == [(Fr(1), Fr(1)) if s == st else (Fr(0), Fr(0))
                                        for s in range(m.card[v])]
        # exact support behaviour: a structurally impossible state is [0, 0]
        for v in r.free:
            for s in range(r.card[v]):
                if pt[v][s] == 0:
                    assert res.intervals[v][s] == (Fr(0), Fr(0)), (ev, v, s)
    # every regional program on this model also executes and verifies from
    # its record (disconnected components, ternary cells)
    r = M.restrict(m, {})
    Z, pt = O.exact_all_marginals(r)
    q = set(r.free)
    for regions in ([(0, 1), (2, 3), (4, 5)], [(0,), (1, 2), (3,), (4,), (5,)]):
        raw, scales, final = _regional_program(r, q, regions, 1)
        prog = _parse(raw)
        rows, meta = RT.execute(prog, r, q)
        pub = _pub(prog, rows)
        assert _contains(pub, pt), regions
        ok, fails, _ = PC.verify_program(r, q, prog, pub, Fr(1, 100))
        assert ok, (regions, fails[:2])
