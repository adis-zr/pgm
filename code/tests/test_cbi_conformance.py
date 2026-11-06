"""Conformance controls for the cbi library (branch cbi-library-2026-11-06). Exact truth by brute-force / exact VE on small instances;
every published interval must contain it; the independent verifier must accept; adversarial controls must be rejected or refused."""
import os, sys, json, random, itertools, copy
HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)
from fractions import Fraction as Fr
import pytest
import numpy as np
from cbi import model as M, api, exact as EX, arith as A, transfer as T, tree as TR, region as RG, coarse as CO, generators as G, plan as PL, influence as IN

Q = 1 << A.GRID_BITS


def rnd(d, nb, edges, seed, m=5, common=0):
    rng = random.Random(seed); blocks = []; cm = sorted(rng.sample(range(1 << d), common)) if common else []
    for b in range(nb):
        rows = sorted(set(cm) | set(rng.sample(range(1 << d), m))); blocks.append({"id": b, "rows": rows, "weights": [rng.randint(1, 9) for _ in rows]})
    return {"d": d, "blocks": blocks, "edges": [{"u": u, "v": v, "r": str(Fr(r))} for u, v, r in edges]}


def truth(obj):
    m = M.Model.from_json(obj); red = M.reduce_model(m)
    if red.infeasible:
        return None
    out = {}
    for q in m.blocks:
        rq = red.orig_to_red[q]; marg, _ = EX.marginal(red.blocks, red.edges, rq, max_entries=1 << 24); Z = sum(marg)
        out[q] = [Fr(sum(w for x, w in zip(red.blocks[rq].rows, marg) if (x >> j) & 1), Z) for j in range(m.d)]
    return out


def brute_truth(obj):
    """Independent of exact.py: full joint enumeration."""
    m = M.Model.from_json(obj); ids = sorted(m.blocks); Z = 0; num = {b: [0] * m.d for b in ids}
    for combo in itertools.product(*[range(len(m.blocks[b].rows)) for b in ids]):
        w = 1
        st = {b: m.blocks[b].rows[i] for b, i in zip(ids, combo)}
        for b, i in zip(ids, combo):
            w *= m.blocks[b].w[i]
        for e in m.edges:
            if e.r == 1:
                if st[e.u] != st[e.v]:
                    w = 0; break
                w *= 2 ** m.d
            else:
                dd = bin(st[e.u] ^ st[e.v]).count("1"); u, v = A.uv(e.r); w *= A.kappa_int(m.d, u, v, dd)
        if w == 0:
            continue
        Z += w
        for b in ids:
            for j in range(m.d):
                if (st[b] >> j) & 1:
                    num[b][j] += w
    return None if Z == 0 else {b: [Fr(x, Z) for x in num[b]] for b in ids}


def contained(res, tr):
    n = 0; fails = 0
    for q, iv in res["intervals"].items():
        for j, row in enumerate(iv["coordinates"]):
            n += 1
            if not (Fr(int(row["lo"]), Q) <= tr[int(q)][j] <= Fr(int(row["hi"]), Q)):
                fails += 1
    return n, fails


def run(obj, width="1/100", limits=None, queries="all"):
    res = api.solve(obj, queries, width, limits or {}); tr = truth(obj)
    if tr is not None and res["status"] in ("CERTIFIED", "VALID_BUT_TOO_WIDE"):
        n, f = contained(res, tr); assert f == 0, (f, n)
        for q, iv in res["intervals"].items():
            assert Fr(iv["max_width"]) == max(Fr(int(r["hi"]) - int(r["lo"]), Q) for r in iv["coordinates"])
    ver = api.verify(obj, res); assert ver["accepted"], ver["reasons"][-3:]
    return res, tr


def test_structures_exact_and_mixed_couplings():
    cases = {"two_blocks": rnd(5, 2, [(0, 1, Fr(1, 3))], 1, m=6),
             "chain": rnd(5, 4, [(0, 1, Fr(1, 3)), (1, 2, Fr(7, 8)), (2, 3, Fr(1, 16))], 1, m=6),
             "spoke": rnd(5, 5, [(0, 1, Fr(1, 3)), (0, 2, Fr(1, 2)), (0, 3, Fr(9, 10)), (0, 4, Fr(1, 50))], 2, m=5),
             "branching_tree": rnd(6, 6, [(0, 1, Fr(1, 5)), (0, 2, Fr(1, 2)), (0, 3, Fr(9, 10)), (3, 4, Fr(1, 40)), (3, 5, Fr(1, 3))], 7, m=7),
             "four_cycle": rnd(6, 4, [(0, 1, Fr(1, 32)), (1, 2, Fr(1, 2)), (2, 3, Fr(1, 32)), (3, 0, Fr(1, 7))], 2, m=6),
             "ladder_2x3": rnd(6, 6, [(0, 1, Fr(1, 40)), (1, 2, Fr(1, 40)), (3, 4, Fr(1, 40)), (4, 5, Fr(1, 40)), (0, 3, Fr(1, 9)), (1, 4, Fr(1, 40)), (2, 5, Fr(1, 40))], 9, m=6),
             "open_mesh_3x3": G.mesh(3, 3, 6, 6, Fr(1, 64), 3), "periodic_mesh_3x3": G.mesh(3, 3, 5, 5, Fr(1, 64), 4, periodic=True)}
    for name, obj in cases.items():
        res, tr = run(obj)
        assert res["status"] in ("CERTIFIED", "VALID_BUT_TOO_WIDE"), (name, res["status"])
        if name in ("two_blocks", "chain", "spoke", "branching_tree", "four_cycle"):
            assert res["status"] == "CERTIFIED" and all(c["mode"] in ("TREE_MESSAGE", "EXACT_VE") for c in res["certificate"].values()), name
    bt = brute_truth(cases["chain"]); assert bt == truth(cases["chain"])            # exact VE agrees with full enumeration


def test_enclosure_operators_contain_truth_on_trees():
    obj = rnd(6, 6, [(0, 1, Fr(1, 5)), (0, 2, Fr(1, 2)), (0, 3, Fr(9, 10)), (3, 4, Fr(1, 40)), (3, 5, Fr(1, 3))], 7, m=7)
    m = M.Model.from_json(obj); red = M.reduce_model(m); tr = truth(obj)
    base = {(min(e.u, e.v), max(e.u, e.v)) for e in red.edges}
    for op in [("sparse", 0), ("sparse", 1), ("sparse", 2), ("fourier", 0), ("fourier", 1), ("fourier", 2), ("fourier", 3), ("fourier", 6), ("poly", 2)]:
        if op[0] == "poly" and any(T.surrogate_eta(e.s(), e.r, 2) is None for e in red.edges):
            continue
        ops = {k: op for k in base}; ts = TR.TreeSolver(red.blocks, red.edges, ops); bel = ts.all_beliefs()
        for b in red.blocks:
            iv = TR.coordinate_intervals(bel[b], red.blocks[b].rows, 6)
            if op[0] != "poly":
                for j in range(6):
                    assert iv[j][0] <= tr[b][j] <= iv[j][1], (op, b, j)
    # sparse radius >= 2 enumerates every distance through h (flip masks counted)
    e = red.edges[0]; cav = A.IVec.exact(red.blocks[e.u].w)
    _, info = T.transfer_sparse(cav, red.blocks[e.u].rows, red.blocks[e.v].rows, e.mask, e.r, 2)
    from math import comb
    assert info["flip_masks"] == sum(comb(e.s(), j) for j in range(3))


def test_hard_components_redundant_cycle_internal_soft_parallel_and_infeasible():
    obj = rnd(5, 5, [(0, 1, 1), (1, 2, 1), (2, 3, 1), (3, 0, 1), (0, 2, 1), (1, 3, Fr(1, 2)), (2, 4, Fr(1, 8)), (0, 4, Fr(1, 3))], 5, m=6, common=4)
    res, tr = run(obj)
    assert res["status"] == "CERTIFIED"
    red = M.reduce_model(M.Model.from_json(obj))
    assert set(red.blocks) == {0, 4} and len(red.edges) == 1 and any("parallel_edges_fused" in x for x in red.log)
    assert brute_truth(obj) == truth(obj)
    bad = copy.deepcopy(obj); bad["blocks"][1]["rows"] = [x for x in range(32) if x not in obj["blocks"][0]["rows"]][:5]; bad["blocks"][1]["weights"] = [1] * 5
    res = api.solve(bad, "all", "1/100"); assert res["status"] == "INFEASIBLE" and api.verify(bad, res)["accepted"] and brute_truth(bad) is None
    # softened version of the same input is feasible
    soft = copy.deepcopy(bad); soft["edges"][0]["r"] = "1/2"; soft["edges"][1]["r"] = "1/2"
    assert api.solve(soft, "all", "1/100")["status"] in ("CERTIFIED", "VALID_BUT_TOO_WIDE")


def test_separable_absorption_is_exact():
    obj = rnd(5, 3, [(0, 1, Fr(1, 3)), (1, 2, Fr(2, 5))], 8, m=4)
    obj["blocks"][2]["rows"] = [0b10101, 0b10100, 0b10001]; obj["blocks"][2]["weights"] = [2, 3, 5]      # coordinates 2 and 4 constant
    red = M.reduce_model(M.Model.from_json(obj)); assert any("absorbed_unary" in x for x in red.log)
    assert brute_truth(obj) == truth(obj)
    res, tr = run(obj); assert res["status"] == "CERTIFIED"


def test_region_surrogate_theorem1_and_supersolution_semantics():
    obj = G.mesh(3, 3, 6, 8, Fr(1, 64), 3); m = M.Model.from_json(obj); red = M.reduce_model(m); tr = truth(obj)
    m2, o2r, _, _, _, _ = M.contract_hard(m); infl = IN.Influence(m2, {b: b for b in m2.blocks}, {})
    H = {4, 1, 3, 5, 7}; adj = M.adjacency(red); xi = {u: RG.fixed_outside_state(red.blocks[u]) for v in H for u in adj[v] if u not in H}
    ops = {(min(e.u, e.v), max(e.u, e.v)): ("poly", 1) for e in red.edges if e.u in H and e.v in H}
    cert = RG.certify(infl, red, H, xi, ops, 4)
    assert all(lo <= tr[4][j] <= hi for j, (lo, hi) in enumerate(cert["intervals_exact"])) and cert["iterations"] > 0
    coef = RG.coefficients(infl, red, H, ops)
    z, _ = RG.iterate(infl, H, coef); assert RG.check_supersolution(infl, H, coef, z)[0]
    # a valid certificate with saturated leaves z = 1 and a smaller root error
    z1 = {v: (Fr(1) if v != 4 else Fr(1, 2)) for v in H}; assert RG.check_supersolution(infl, H, coef, z1)[0]
    # an unfinished iteration starting at ZERO is NOT a certificate (not a supersolution)
    z0 = {v: Fr(0) for v in H}; assert not RG.check_supersolution(infl, H, coef, z0)[0]
    # every iterate from one is nonincreasing and valid
    zs = [{v: Fr(1) for v in H}]
    for _ in range(5):
        zs.append(RG.F_apply(infl, H, coef, zs[-1]))
    for a, b in zip(zs, zs[1:]):
        assert all(b[v] <= a[v] for v in H)
    # a hard / nonpositive surrogate is rejected: degree-0 truncation at r = 1/2 on 6 coordinates has tau >= (1-r)^6
    assert T.surrogate_eta(6, Fr(1, 2), 0) is None
    strong_edge = M.Edge(0, 1, Fr(1, 2), 63)
    with pytest.raises(RG.SurrogateError):
        red_s = M.Reduced(6, {0: red.blocks[0], 1: red.blocks[1]}, [strong_edge], {}, {}); infl_s = IN.Influence(M.Model(6, {0: m.blocks[0], 1: m.blocks[1]}, [strong_edge]), {0: 0, 1: 1}, {})
        RG.coefficients(infl_s, red_s, {0, 1}, {(0, 1): ("poly", 0)})
    # the exact-identity case with strong interactions bypasses the vacuous influence bound: no transport when nothing is approximated
    strong = rnd(5, 4, [(0, 1, Fr(9, 10)), (1, 2, Fr(19, 20)), (2, 3, Fr(9, 10))], 12, m=5)
    res, trs = run(strong); assert res["status"] == "CERTIFIED" and all(Fr(c["z_query"]) == 0 for c in res["certificate"].values())


def test_coarsening_theorem3_premises_and_rejections():
    d = 5; eI = Fr(1) - Fr(1, 2 ** 12); eS = Fr(1, 64); rng = random.Random(11); common = sorted(rng.sample(range(1 << d), 6)); blocks = []
    for b in range(4):
        rows = sorted(set(common) | set(rng.sample(range(1 << d), 4))); blocks.append({"id": b, "rows": rows, "weights": [rng.randint(1, 9) for _ in rows]})
    for b in (4, 5):
        rows = sorted(rng.sample(range(1 << d), 7)); blocks.append({"id": b, "rows": rows, "weights": [rng.randint(1, 9) for _ in rows]})
    obj = {"d": d, "blocks": blocks, "edges": [{"u": u, "v": v, "r": str(r)} for u, v, r in [(0, 1, eI), (1, 2, eI), (2, 3, eI), (3, 0, eI), (0, 4, eS), (2, 5, eS)]]}
    res, tr = run(obj); assert res["status"] == "CERTIFIED" and all(c["mode"] == "COARSE_REGION" for c in res["certificate"].values())
    c = res["plan"]["clusters"]["verified"][0]; assert c["cuts_enumerated"] == 7 and Fr(c["Gamma_i"]) == ((1 - eI) / (1 + eI)) ** 2
    m2 = M.Model.from_json(obj)
    with pytest.raises(ValueError):                   # absent intersection
        bad = copy.deepcopy(obj); bad["blocks"][3]["rows"] = [x for x in range(32) if x not in common][:5]; bad["blocks"][3]["weights"] = [1] * 5
        CO.verify_cluster(M.Model.from_json(bad), [0, 1, 2, 3])
    with pytest.raises(ValueError):                   # not connected internally
        CO.verify_cluster(m2, [0, 2])
    with pytest.raises(ValueError):                   # hard edge inside
        hb = copy.deepcopy(obj); hb["edges"][0]["r"] = "1"; CO.verify_cluster(M.Model.from_json(hb), [0, 1, 2, 3])
    # island mesh 4x4 with hints vs automatic proposal
    im = G.island_mesh(2, 2, 6, 6, 3, eI, Fr(1, 64), 0); res, tr = run(im); assert res["status"] == "CERTIFIED"
    im2 = copy.deepcopy(im); im2["meta"].pop("cluster_hints"); res2, _ = run(im2); assert res2["status"] == "CERTIFIED" and res2["plan"]["clusters"]["proposal"].startswith("automatic")


def test_fixed_outside_state_is_consistent_per_block_and_triangle_region_uses_dense_ve():
    obj = G.mesh(3, 3, 6, 8, Fr(1, 64), 3); res, tr = run(obj, limits={"exact_direct_entries": 1})
    for q, c in res["certificate"].items():
        xi = res["proofs"][c["proof"]]["xi"]; assert len(xi) == len(set(xi))                      # one state per outside block
    tri = rnd(5, 4, [(0, 1, Fr(1, 8)), (1, 2, Fr(1, 8)), (2, 0, Fr(1, 8)), (0, 3, Fr(1, 8))], 6, m=5)
    res, tr = run(tri); assert res["status"] == "CERTIFIED"
    assert any((p.get("solver_info") or {}).get("regional_solver") == "dense_ve" for p in res["proofs"].values())


def test_input_rejections_and_statuses():
    assert api.solve({"d": 3, "blocks": [{"id": 0, "rows": [1, 1], "weights": [1, 1]}], "edges": []}, "all", "1/100")["status"] == "UNSUPPORTED_INPUT"
    assert api.solve({"d": 3, "blocks": [{"id": 0, "rows": [1], "weights": [0]}], "edges": []}, "all", "1/100")["status"] == "UNSUPPORTED_INPUT"
    assert api.solve({"d": 3, "blocks": [{"id": 0, "rows": [9], "weights": [1]}], "edges": []}, "all", "1/100")["status"] == "UNSUPPORTED_INPUT"
    assert api.solve({"d": 3, "blocks": [{"id": 0, "rows": [1], "weights": [1]}, {"id": 1, "rows": [2], "weights": [1]}], "edges": [{"u": 0, "v": 1, "r": "1/2", "kernel": "ising"}]}, "all", "1/100")["status"] == "UNSUPPORTED_INPUT"
    assert api.solve({"d": 3, "blocks": [{"id": 0, "rows": [1], "weights": [1]}, {"id": 1, "rows": [2], "weights": [1]}], "edges": [{"u": 0, "v": 1, "r": "1/2", "coordinate_map": [1, 0, 2]}]}, "all", "1/100")["status"] == "UNSUPPORTED_INPUT"
    assert api.solve({"d": 3, "blocks": [{"id": 0, "rows": [1], "weights": [1]}], "edges": [{"u": 0, "v": 7, "r": "1/2"}]}, "all", "1/100")["status"] == "UNSUPPORTED_INPUT"
    # too wide: a weak-ish cycle region with a tiny dense limit stays VALID_BUT_TOO_WIDE, never a false CERTIFIED
    obj = G.mesh(3, 3, 5, 5, Fr(1, 8), 4, periodic=True); res, tr = run(obj, limits={"max_entries": 2000, "exact_direct_entries": 1})
    assert res["status"] in ("VALID_BUT_TOO_WIDE", "RESOURCE_LIMIT")
    # resource limit on a dense component
    res = api.solve(obj, "all", "1/100", {"max_entries": 10, "exact_direct_entries": 1, "max_region_radius": 1})
    assert res["status"] in ("RESOURCE_LIMIT", "VALID_BUT_TOO_WIDE")


def test_tampering_detected_by_verifier():
    obj = G.mesh(3, 3, 6, 8, Fr(1, 64), 3); res, tr = run(obj, limits={"exact_direct_entries": 1, "max_entries": 2000, "max_region_radius": 1})
    q = "4"
    assert Fr(res["certificate"][q]["z_query"]) > 0 and res["certificate"][q]["mode"] == "REGION_SURROGATE"      # a genuine transport certificate
    assert res["proofs"][res["certificate"][q]["proof"]]["iterations"] > 1
    # EXTRA iterations of a stationary recurrence reproduce the same z: that is a legitimate certificate, not a tamper
    more = json.loads(json.dumps(res, default=str)); more["proofs"][res["certificate"][q]["proof"]]["iterations"] += 5; assert api.verify(obj, more)["accepted"]
    pid = res["certificate"][q]["proof"]
    muts = {"interval_lo": lambda r: r["intervals"][q]["coordinates"][0].__setitem__("lo", r["intervals"][q]["coordinates"][0]["lo"] + 1),
            "interval_hi": lambda r: r["intervals"][q]["coordinates"][1].__setitem__("hi", r["intervals"][q]["coordinates"][1]["hi"] - 1),
            "z": lambda r: r["proofs"][pid].__setitem__("z_grid", {k: int(v) // 2 for k, v in r["proofs"][pid]["z_grid"].items()}),
            "iterations": lambda r: r["proofs"][pid].__setitem__("iterations", 1),            # fewer iterations than the declared (converged) z: replay mismatch
            "theta": lambda r: r["proofs"][pid]["theta"].__setitem__(next(iter(r["proofs"][pid]["theta"])), "1/1000000"),
            "d": lambda r: r["proofs"][pid]["d"].__setitem__(next(iter(r["proofs"][pid]["d"])), "0"),
            "xi": lambda r: r["proofs"][pid]["xi"].__setitem__(next(iter(r["proofs"][pid]["xi"])), 999999),
            "ops": lambda r: r["proofs"][pid]["inside_ops"].__setitem__(next(iter(r["proofs"][pid]["inside_ops"])), ["poly", 0]),
            "proof_pointer": lambda r: r["certificate"][q].__setitem__("proof", "P_missing"),
            "status": lambda r: r["statuses_per_query"].__setitem__(q, "CERTIFIED" if r["statuses_per_query"][q] != "CERTIFIED" else "VALID_BUT_TOO_WIDE")}
    for name, mut in muts.items():
        bad = json.loads(json.dumps(res, default=str)); mut(bad)
        assert not api.verify(obj, bad)["accepted"], name
    # tampering with the model's weights / couplings against a result from another model
    obj2 = copy.deepcopy(obj); obj2["blocks"][4]["weights"][0] += 1; assert not api.verify(obj2, res)["accepted"]
    obj3 = copy.deepcopy(obj); obj3["edges"][0]["r"] = "1/63"; assert not api.verify(obj3, res)["accepted"]
    # coarsening tampering: rho / Gamma
    im = G.island_mesh(2, 2, 6, 6, 3, Fr(1) - Fr(1, 2 ** 12), Fr(1, 64), 0); res2, _ = run(im)
    bad = json.loads(json.dumps(res2, default=str)); bad["plan"]["clusters"]["verified"][0]["rho_i"] = "1/1000000000"; assert not api.verify(im, bad)["accepted"]
    bad = json.loads(json.dumps(res2, default=str)); bad["plan"]["clusters"]["verified"][0]["Gamma_i"] = "0"; assert not api.verify(im, bad)["accepted"]


def test_movement_case_and_width_adaptation():
    """A reference-measurable case whose marginals move from the uncoupled prior by more than half the requested width, and a width
    request that changes the plan."""
    obj = G.mesh(3, 3, 6, 8, Fr(1, 16), 21); tr = truth(obj); m = M.Model.from_json(obj)
    pi = {b: [Fr(sum(w for x, w in zip(blk.rows, blk.w) if (x >> j) & 1), sum(blk.w)) for j in range(m.d)] for b, blk in m.blocks.items()}
    mv = max(abs(tr[b][j] - pi[b][j]) for b in tr for j in range(m.d)); assert mv > Fr(1, 200), float(mv)
    r1, _ = run(obj, "1/100", {"exact_direct_entries": 1}); r2, _ = run(obj, "1/20", {"exact_direct_entries": 1})
    a1 = [a for t in r1["plan"]["queries"]["4"]["trials"] for a in t["attempts"]]; a2 = [a for t in r2["plan"]["queries"]["4"]["trials"] for a in t["attempts"]]
    assert len(a1) >= len(a2)                                                   # the stricter width needs at least as many attempts


# ------------------------------------------------------------------ the reviewer's counterexamples (6 Nov 2026 review) must be contained AFTER the repair
CE = json.load(open(os.path.join(HERE, "runs/mdi_2026-10-28/CBI_LIBRARY_2026-11-06/repair_2026-11-06/counterexamples.json")))


def test_review_counterexamples_contained_and_verified():
    for name, (q, j) in (("CE1", (0, 0)), ("CE2", (2, 0)), ("CE3", (2, 0))):
        obj = CE[name]; res = api.solve(obj, [q], "1/100"); tr = brute_truth(obj)[q][j]
        row = res["intervals"][str(q)]["coordinates"][j]; lo, hi = Fr(int(row["lo"]), Q), Fr(int(row["hi"]), Q)
        assert lo <= tr <= hi, (name, float(lo), float(hi), float(tr))
        assert api.verify(obj, res)["accepted"], name
    # CE1: Omega over the ORIGINAL support gives rho = 1/2 and the cluster is accepted but the coarse certificate is wide; the plain
    # system certifies exactly through the whole component
    res = api.solve(CE["CE1"], [0], "1/100"); c = res["certificate"]["0"]
    assert res["status"] == "CERTIFIED" and c["system"] == "plain" and Fr(res["intervals"]["0"]["coordinates"][0]["exact"][0]) <= Fr(1, 2) <= Fr(res["intervals"]["0"]["coordinates"][0]["exact"][1])
    assert any(Fr(x["rho_i"]) == Fr(1, 2) for x in res["plan"]["clusters"]["verified"])
    # CE2: the influence edge 0-2 survives although Q's edge is absorbed; transport is needed for the outside query
    res = api.solve(CE["CE2"], [2], "1/100"); c = res["certificate"]["2"]
    trial_coarse = next(t for t in res["plan"]["queries"]["2"]["trials"] if t["system"] == "coarse")
    assert any(Fr(a.get("z_query", "0")) > 0 for a in trial_coarse["attempts"] if a["status"] == "OK")


def test_verifier_rejects_malformed_operator_and_missing_queries():
    obj = rnd(5, 2, [(0, 1, Fr(1, 2))], 3, m=2); obj["blocks"][0]["weights"] = [1, 1]; obj["blocks"][1]["weights"] = [1, 3]
    res, tr = run(obj, queries=[0])
    pid = res["certificate"]["0"]["proof"]
    bad = json.loads(json.dumps(res, default=str)); bad["proofs"][pid]["inside_ops"] = {k: ["sparse", -2] for k in bad["proofs"][pid]["inside_ops"]}
    assert not api.verify(obj, bad)["accepted"]
    bad = json.loads(json.dumps(res, default=str)); bad["intervals"] = {}
    assert not api.verify(obj, bad)["accepted"]
    bad = json.loads(json.dumps(res, default=str)); bad["requested_queries"] = []
    assert not api.verify(obj, bad)["accepted"]
    bad = json.loads(json.dumps(res, default=str)); bad["statuses_per_query"] = {}
    assert not api.verify(obj, bad)["accepted"]
    # every requested query must be present with a consistent status
    res2, _ = run(obj, queries=[0, 1]); bad = json.loads(json.dumps(res2, default=str)); del bad["intervals"]["1"]
    assert not api.verify(obj, bad)["accepted"]


def test_parser_rejects_silent_reinterpretation():
    for bad in ({"d": 3, "blocks": [{"id": 0, "rows": [0, 1], "weights": [1]}], "edges": []},
                {"d": 3, "blocks": [{"id": 0, "rows": [0, 1], "weights": []}], "edges": []},
                {"d": 3, "blocks": [{"id": 0, "rows": [0.5, 1], "weights": [1, 1]}], "edges": []},
                {"d": 3, "blocks": [{"id": 0, "rows": ["1", 2], "weights": [1, 1]}], "edges": []},
                {"d": 3, "blocks": [{"id": 0, "rows": [1], "weights": [1]}, {"id": 1, "rows": [2], "weights": [1]}], "edges": [{"u": 0, "v": 1, "r": "1/2"}], "meta": {"cluster_hints": [[0, 1, 2, 3, 4, 5, 6, 7, 8]]}}):
        assert api.solve(bad, "all", "1/100")["status"] == "UNSUPPORTED_INPUT", bad
    # a Model object supplied directly is validated too
    mm = M.Model(3, {0: M.Block(0, [1, 1], [1, 1])}, [])
    assert api.solve(mm, "all", "1/100")["status"] == "UNSUPPORTED_INPUT"


# ------------------------------------------------------------------ the second review (6 Nov 2026): checker arithmetic range, cluster partition, disconnected forests, final-plan admission, hints, arguments
def _tamper_near_one(res, q, rho):
    bad = json.loads(json.dumps(res, default=str)); elo, ehi = 1 - rho, Fr(1); lg, hg = A.publish(elo, ehi)
    bad["intervals"][q]["coordinates"][0] = {"lo": lg, "hi": hg, "exact": [str(elo), str(ehi)], "width": str(Fr(hg - lg, Q))}
    w = Fr(hg - lg, Q); bad["intervals"][q]["max_width"] = str(w); bad["intervals"][q]["max_width_float"] = float(w); bad["intervals"][q]["width_met"] = bool(w <= Fr(1, 100))
    return bad


def test_checker_arbitrary_precision_products_across_fixed_width_boundaries():
    for Mw in (1 << 31, 1 << 32, (1 << 63) - 1, 1 << 64):
        obj = {"d": 1, "blocks": [{"id": 0, "rows": [0, 1], "weights": [Mw, 1]}, {"id": 1, "rows": [0, 1], "weights": [Mw, 1]}], "edges": [{"u": 0, "v": 1, "r": "1/2"}], "meta": {"cluster_hints": [[0, 1]]}}
        res = api.solve(obj, [0], "1/100"); tr = brute_truth(obj)[0][0]
        row = res["intervals"]["0"]["coordinates"][0]; assert Fr(int(row["lo"]), Q) <= tr <= Fr(int(row["hi"]), Q)
        assert api.verify(obj, res)["accepted"], Mw                                            # the honest near-zero interval verifies
        if res["certificate"]["0"]["system"] == "coarse":
            assert not api.verify(obj, _tamper_near_one(res, "0", Fr(res["certificate"]["0"]["z_query"])))["accepted"], Mw     # the near-one tamper is rejected


def test_checker_rejects_overlapping_or_malformed_certificate_clusters():
    obj = {"d": 1, "blocks": [{"id": 0, "rows": [0, 1], "weights": [1, 1]}, {"id": 1, "rows": [0, 1], "weights": [1, 3]}, {"id": 2, "rows": [0, 1], "weights": [1, 1]}], "edges": [{"u": 0, "v": 1, "r": "1/2"}, {"u": 0, "v": 2, "r": "4095/4097"}]}
    res = api.solve(obj, [0], "1/100"); assert brute_truth(obj)[0][0] == Fr(5, 8) and api.verify(obj, res)["accepted"]
    m2 = M.Model.from_json(obj); c1 = CO.verify_cluster(m2, [0, 1]); c2 = CO.verify_cluster(m2, [0, 2]); rho2 = Fr(c2["rho_i"])
    bad = json.loads(json.dumps(res, default=str)); bad["plan"]["clusters"]["verified"] = [{k: v for k, v in c.items() if k not in ("coarse_rows", "coarse_weights")} for c in (c1, c2)]
    zg = -((-rho2 * (1 << RG.Z_BITS)).numerator // (-rho2 * (1 << RG.Z_BITS)).denominator)
    bad["proofs"] = {"PX": {"kind": "region", "system": "coarse", "mode": "COARSE_REGION", "H": [0], "xi": {}, "inside_ops": {}, "theta": {}, "d": {"0": "0"}, "beta": {"0": "0"}, "b": {"0": str(rho2)}, "eta": {}, "rho": {"0": str(rho2)}, "z_grid": {"0": zg}, "z_grid_bits": RG.Z_BITS, "iterations": 1, "nodes": {"0": [["0", "1"]]}}}
    bad["certificate"]["0"] = {"proof": "PX", "node": 0, "system": "coarse", "mode": "COARSE_REGION", "H": [0], "z_query": str(Fr(zg, 1 << RG.Z_BITS)), "iterations": 1}
    bad["intervals"]["0"]["node"] = 0; elo, ehi = Fr(1, 2) - rho2, Fr(1, 2) + rho2; lg, hg = A.publish(elo, ehi)
    bad["intervals"]["0"]["coordinates"][0] = {"lo": lg, "hi": hg, "exact": [str(elo), str(ehi)], "width": str(Fr(hg - lg, Q))}
    w = Fr(hg - lg, Q); bad["intervals"]["0"]["max_width"] = str(w); bad["intervals"]["0"]["max_width_float"] = float(w); bad["intervals"]["0"]["width_met"] = True; bad["statuses_per_query"] = {"0": "CERTIFIED"}; bad["status"] = "CERTIFIED"
    assert not api.verify(obj, bad)["accepted"]
    # duplicate member inside one cluster, unknown member, oversized cluster
    for cl in ([[0, 0, 1]], [[0, 9]], [list(range(9))]):
        b2 = json.loads(json.dumps(res, default=str)); b2["plan"]["clusters"]["verified"] = [{"cluster": c_, "rho_i": "1/2", "C_i": "1/2", "Gamma_i": "1", "expOmega_i": "1"} for c_ in cl]
        assert not api.verify(obj, b2)["accepted"], cl


def test_disconnected_computational_forest_verifies():
    obj = {"d": 6, "blocks": [{"id": 0, "rows": [0, 1], "weights": [1, 1]}, {"id": 1, "rows": [0, 2], "weights": [1, 1]}, {"id": 2, "rows": list(range(64)), "weights": [1] * 64}, {"id": 3, "rows": list(range(64)), "weights": [1] * 64}],
           "edges": [{"u": 0, "v": 1, "r": "4095/4097"}, {"u": 0, "v": 2, "r": "1/4"}, {"u": 2, "v": 3, "r": "1/4096"}]}
    res = api.solve(obj, [2], "1/100"); tr = truth(obj)
    assert res["status"] == "CERTIFIED" and any(v[0] in ("fourier", "sparse") for v in res["proofs"][res["certificate"]["2"]["proof"]]["inside_ops"].values())
    assert contained(res, tr)[1] == 0 and api.verify(obj, res)["accepted"]


def test_final_plan_admission_cannot_be_bypassed():
    obj = {"d": 1, "blocks": [{"id": 0, "rows": [0, 1], "weights": [1, 1]}, {"id": 1, "rows": [0, 1], "weights": [1, 2]}], "edges": [{"u": 0, "v": 1, "r": "1/2"}]}
    res = api.solve(obj, [0], "1/100", {"max_pairs_per_edge": 1, "force_exact": True}); assert res["status"] == "RESOURCE_LIMIT"
    res = api.solve(obj, [0], "1/100", {"max_pairs_per_edge": 1}); assert res["status"] in ("RESOURCE_LIMIT", "VALID_BUT_TOO_WIDE", "CERTIFIED")
    for t in res["plan"]["queries"]["0"]["trials"]:
        for a in t["attempts"]:
            if a["status"] == "OK":
                assert all(v[0] != "exact" for v in a["ops"].values())


def test_hints_mapped_through_hard_contraction_and_malformed_arguments():
    obj = {"d": 2, "blocks": [{"id": 0, "rows": [0, 1], "weights": [1, 1]}, {"id": 1, "rows": [0, 1], "weights": [1, 1]}, {"id": 2, "rows": [0, 2], "weights": [1, 1]}], "edges": [{"u": 0, "v": 1, "r": "1"}, {"u": 1, "v": 2, "r": "4095/4097"}], "meta": {"cluster_hints": [[0, 1, 2]]}}
    res = api.solve(obj, [0], "1/100"); assert res["status"] == "CERTIFIED" and res["plan"]["clusters"]["proposed"] == [[0, 2]] and api.verify(obj, res)["accepted"]
    tr = truth(obj); assert contained(res, tr)[1] == 0
    base = {"d": 1, "blocks": [{"id": 0, "rows": [0], "weights": [1]}], "edges": []}
    assert api.solve(base, "all", "1/0")["status"] == "UNSUPPORTED_INPUT"
    assert api.solve(base, "all", "abc")["status"] == "UNSUPPORTED_INPUT"
    assert api.solve(base, "all", "2")["status"] == "UNSUPPORTED_INPUT"
    assert api.solve({"d": 1, "blocks": [{"id": 0, "rows": [0], "weights": ["x"]}], "edges": []}, "all", "1/100")["status"] == "UNSUPPORTED_INPUT"
    assert api.solve({"d": 1, "blocks": [{"id": 0, "rows": [0], "weights": [1]}, {"id": 1, "rows": [0], "weights": [1]}], "edges": [{"u": 0, "v": 1, "r": "1/0"}]}, "all", "1/100")["status"] == "UNSUPPORTED_INPUT"
    assert api.solve(base, "all", "1/100", {"bogus": 1})["status"] == "UNSUPPORTED_INPUT"
    assert api.solve(base, "all", "1/100", {"degrees": [-1]})["status"] == "UNSUPPORTED_INPUT"
    assert api.solve(base, ["x"], "1/100")["status"] == "UNSUPPORTED_INPUT"
    assert api.solve(obj, [0], "1/100", {"max_time_s": 1e-9})["status"] == "RESOURCE_LIMIT"
