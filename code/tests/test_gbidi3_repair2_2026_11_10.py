"""SECOND-REVIEW REPAIR CONTROLS of GENERAL_BIDI_COMPLETE_V3 (10 Nov 2026, packet 4c9d8046…; correction brief sections A-G). Every control first failed
or could not be expressed on the delivered source b960ae1e (reproductions: review_repro_r2/REPRO_R2_RESULTS.json) and passes on the repaired code.
  SA  coordinate-domain typing: a class-space axis is never consumed as raw (permutations 2 / 3 states, pass-through collision, shared consumers, weighted
      views, both coverage routes, both arithmetic routes); the exact-jet oracle multiplies independent roots and lifts decoder constants correctly
  SB  compositional cold recurrences: streamed branching trees (exact equality of every predicted row class with the kernel's counters), retained
      counterpart, the two-axis candidate retained beside the one-axis plan and ranked by the ONE cost (conflict-with-views fixture + positive activation)
  SC  sparse reverse under pending pressure: the same support-indexed pullback immediately, multiple outputs, external adjoints, late increments,
      nonbinary supports; every generic entry path labelled
  SD  one all-consumer demand contract: the arm switch is honoured for every program shape, one aggregate row / wall budget, reserve-before-build, FULL on
      exhaustion, multi-node shared case
  SE  resource / polling transitions: fallback bit growth bounded before growth, native reallocation peaks and scoped temporaries, validator strided and
      polled, parser / hashing cumulative polling, binary64 admission and trusted re-check under the deadline
  SF  parent-generated terminal receipts: real stage interruption, UNKNOWN wall never used in arithmetic, envelope charge, reconciled noncertifying,
      resume without relaunch, closeout"""
from __future__ import annotations
import sys, os, json, time, copy, signal, subprocess, tracemalloc, types, itertools
import pytest
HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__))); sys.path.insert(0, HERE); sys.path.insert(0, os.path.join(HERE, "tests"))
sys.set_int_max_str_digits(0)
from fractions import Fraction as Fr
from gbidi3 import executor as EX, source as GS, trusted as TR, ir as IR, validate as GV, planner as PL, memory as GM, oracle as OR, demand as DM, reconcile as RC, pilot as PI
from gbidi3.clock import Clock, PlanStop
from adp import source as SRC
from ext import uai as U
import test_gbidi3_complete as Q
import test_gbidi3_repair_2026_11_10 as RT
PY = sys.executable; ENV = dict(os.environ, PYTHONPATH=HERE)


def snap(tmp_path, name, card, fs, rules=()):
    mp, ep = Q.write_uai(str(tmp_path / (name + ".uai")), card, [(sc, list(t)) for sc, t in fs]); S = GS.Snapshot(mp, ep); R = SRC.Reduced(EX._ModelAdapter(S.model), dict(S.ev)); R.reduce(tuple(rules)); T = TR.TrustedReduced(R); Z, N, rows = OR.rows(S.model, S.ev)
    return mp, ep, S, T, {v: list(r) for v, r in enumerate(rows)}


def finish(P, kids, elim):
    m = P.mul(kids); r = P.reduce(m, elim); P.roots = [r.nid]; return P


def both_routes_refuse(mp, ep, build, tmp_path, tag):
    for b64 in (False, True):
        def mut(P2):
            p = build(); P2.nodes = p.nodes; P2.roots = p.roots; P2.derived = p.derived
        with pytest.raises(EX.Refuse) as ex:
            Q.run("GENERAL_BIDI_COMPLETE_V3", mp, ep, str(tmp_path / ("%s_bad%d" % (tag, b64))), rules=[], b64=b64, fallback=False, hooks={"mutate_program": mut})
        assert ex.value.kind == "REJECTED" and "coordinate" in ex.value.reason, (tag, ex.value.reason)
        assert not os.path.exists(str(tmp_path / ("%s_bad%d" % (tag, b64)) / "output.MAR"))


def both_routes_certify(mp, ep, build, truth, tmp_path, tag):
    for b64 in (False, True):
        def mut(P2):
            p = build(); P2.nodes = p.nodes; P2.roots = p.roots; P2.derived = p.derived
        rec = Q.run("GENERAL_BIDI_COMPLETE_V3", mp, ep, str(tmp_path / ("%s_ok%d" % (tag, b64))), rules=[], b64=b64, hooks={"mutate_program": mut}); st, cell = Q.publish(str(tmp_path / ("%s_ok%d" % (tag, b64))), mp, ep, rec)
        assert st == "CERTIFIED" and Q.contained(rec, truth), (tag, b64, st, cell.get("publication"))


# ============================================================================================================ SA  coordinate-domain typing (brief A)
def test_SA1_reviewer_singleton_permutation_is_rejected_and_its_lawful_expansion_certifies(tmp_path):
    mp, ep, S, T, truth = snap(tmp_path, "perm2", [2, 2], [((0, 1), (1, 2, 3, 4))]); fid = T.factors[0].fid
    def build(legal):
        P = IR.Program(); f = P.source(fid, (0, 1), (2, 2)); ma = P.marker(0, 2); r = P.reduce(P.mul([f, ma]), (0,), reps={1: ((1, 0), (1, 0), (Fr(1), Fr(1)))})
        if legal:
            r = P.gather(r, (1,), (2,), gaxes=[{"out_pos": 0, "cls": (1, 0), "ratio": (Fr(1), Fr(1))}])
        mb = P.marker(1, 2); return finish(P, [r, mb], (1,))
    with pytest.raises(TR.Invalid) as ex:
        GV.validate(build(False), T)
    assert "coordinate" in ex.value.reason and "CLASS" in ex.value.reason
    V = GV.validate(build(True), T); assert V.record["status"] == "VALID" and RT.jet_rows(V) == truth
    both_routes_refuse(mp, ep, lambda: build(False), tmp_path, "perm2"); both_routes_certify(mp, ep, lambda: build(True), truth, tmp_path, "perm2")


def test_SA2_multi_state_permutation_pass_through_collision_shared_consumers_and_weighted_views(tmp_path):
    # (a) 3-state cyclic permutation of a kept axis, consumed raw -> rejected; expanded -> exact
    f3 = (1, 2, 3, 4, 5, 6, 7, 8, 10); mp, ep, S, T, truth = snap(tmp_path, "perm3", [3, 3], [((0, 1), f3)]); fid = T.factors[0].fid
    def perm3(legal, passthrough=False):
        P = IR.Program(); f = P.source(fid, (0, 1), (3, 3)); ma = P.marker(0, 3); r = P.reduce(P.mul([f, ma]), (0,), reps={1: ((1, 2, 0), (2, 0, 1), (Fr(1), Fr(1), Fr(1)))})
        if passthrough:
            r = P.gather(r, (1,), (3,), gaxes=[{"out_pos": 0}])                                                  # identity GATHER: keeps the class space (an intermediate of equal cardinality)
        if legal:
            r = P.gather(r, (1,), (3,), gaxes=[{"out_pos": 0, "cls": (2, 0, 1), "ratio": (Fr(1), Fr(1), Fr(1))}])
        mb = P.marker(1, 3); return finish(P, [r, mb], (1,))
    for pt in (False, True):
        with pytest.raises(TR.Invalid) as ex:
            GV.validate(perm3(False, pt), T)
        assert "coordinate" in ex.value.reason, (pt, ex.value.reason)
        V = GV.validate(perm3(True, pt), T); assert RT.jet_rows(V) == truth
    both_routes_refuse(mp, ep, lambda: perm3(False, True), tmp_path, "perm3pt"); both_routes_certify(mp, ep, lambda: perm3(True, True), truth, tmp_path, "perm3pt")
    # (b) shared consumers of ONE class-space message (additive split of a unary h on B): one consumer expands, the other reads raw -> rejected; both expand -> exact
    fh = (2, 3, 5); mp2, ep2, S2, T2, truth2 = snap(tmp_path, "shared", [3, 3], [((0, 1), f3), ((1,), fh)]); fid2 = [f for f in T2.factors if f.scope == (0, 1)][0].fid; hid = [f for f in T2.factors if f.scope == (1,)][0].fid
    def shared(illegal_second):
        P = IR.Program(); P.derived = {101: {"kind": "additive_split", "parent": hid, "parts": [(2, 0, 0), (0, 3, 5)], "index": 0}, 102: {"kind": "additive_split", "parent": hid, "parts": [(2, 0, 0), (0, 3, 5)], "index": 1}}
        f = P.source(fid2, (0, 1), (3, 3)); ma = P.marker(0, 3); msg = P.reduce(P.mul([f, ma]), (0,), reps={1: ((1, 2, 0), (2, 0, 1), (Fr(1), Fr(1), Fr(1)))}); msg.storage = IR.DENSE
        g1 = P.gather(msg, (1,), (3,), gaxes=[{"out_pos": 0, "cls": (2, 0, 1), "ratio": (Fr(1), Fr(1), Fr(1))}]); h1 = P.source(101, (1,), (3,)); mb = P.marker(1, 3)
        c1 = P.mul([g1, h1, mb], axes=(1,), card=(3,)); use2 = msg if illegal_second else P.gather(msg, (1,), (3,), gaxes=[{"out_pos": 0, "cls": (2, 0, 1), "ratio": (Fr(1), Fr(1), Fr(1))}]); h2 = P.source(102, (1,), (3,)); mb2 = mb
        c2 = P.mul([use2, h2, mb2], axes=(1,), card=(3,))
        # marker B appears in both products: ADD operands must carry identical marker sets -> use ONE marker through both branches is not allowed (double multiplication); so each branch gets the marker and the ADD covers it exactly once
        add = P.addn([c1, c2]); root = P.reduce(add, {1}); root.storage = IR.DENSE; P.roots = [root.nid]; return P
    with pytest.raises(TR.Invalid) as ex:
        GV.validate(shared(True), T2)
    assert "coordinate" in ex.value.reason or "ADD" in ex.value.reason, ex.value.reason
    V2 = GV.validate(shared(False), T2); assert V2.record["status"] == "VALID" and RT.jet_rows(V2) == truth2
    both_routes_refuse(mp2, ep2, lambda: shared(True), tmp_path, "shared"); both_routes_certify(mp2, ep2, lambda: shared(False), truth2, tmp_path, "shared")
    # (c) weighted nontrivial view (two proportional rows, ratio 2): legal with its GATHER (nonunit lawful weight), illegal raw use (card 2 vs 3 AND class space)
    fw = (1, 2, 3, 2, 4, 6, 5, 7, 11); mp3, ep3, S3, T3, truth3 = snap(tmp_path, "weighted", [3, 3], [((0, 1), fw)]); fid3 = T3.factors[0].fid
    def weighted(legal):
        P = IR.Program(); f = P.source(fid3, (0, 1), (3, 3)); mb = P.marker(1, 3); r = P.reduce(P.mul([f, mb]), (1,), reps={0: ((0, 2), (0, 0, 1), (Fr(1), Fr(2), Fr(1)))})
        if legal:
            r = P.gather(r, (0,), (3,), gaxes=[{"out_pos": 0, "cls": (0, 0, 1), "ratio": (Fr(1), Fr(2), Fr(1))}])
        else:
            r = P.gather(r, (0,), (2,), gaxes=[{"out_pos": 0}])                                                   # identity pass-through keeps the 2-class space; raw marker of card 3 cannot meet it
            ma = P.marker(0, 3); return finish(P, [r, ma], (0,))
        ma = P.marker(0, 3); return finish(P, [r, ma], (0,))
    with pytest.raises((TR.Invalid, IR.IRError)):
        GV.validate(weighted(False), T3)
    V3 = GV.validate(weighted(True), T3); assert RT.jet_rows(V3) == truth3 and V3.record["entrywise_checks"] > 0
    both_routes_certify(mp3, ep3, lambda: weighted(True), truth3, tmp_path, "weighted")
    # (d) the production planner's own views still certify (nothing legal was forbidden): every C04-class fixture through the default arm
    mp4, ep4 = Q.write_uai(str(tmp_path / "c04.uai"), [2, 2], [((0, 1), [1, 1, 2, 2]), ((1,), [0, 1])]); S4, Z4, N4, rows4 = Q.truth(mp4, ep4)
    rec = Q.run("A2_NO_FUSION", mp4, ep4, str(tmp_path / "c04"), rules=[], b64=False); assert Q.exact_rows(rec, rows4) and rec["mechanisms"]["views"]["compressed_axes"] >= 1


def test_SA3_coordinate_types_survive_copying_demand_maps_and_serialization(tmp_path):
    mp, ep, S, T, truth = snap(tmp_path, "perm2", [2, 2], [((0, 1), (1, 2, 3, 4))]); fid = T.factors[0].fid
    P = IR.Program(); f = P.source(fid, (0, 1), (2, 2)); ma = P.marker(0, 2); r = P.reduce(P.mul([f, ma]), (0,), reps={1: ((1, 0), (1, 0), (Fr(1), Fr(1)))}); r.storage = IR.DENSE
    g = P.gather(r, (1,), (2,), gaxes=[{"out_pos": 0, "cls": (1, 0), "ratio": (Fr(1), Fr(1))}]); mb = P.marker(1, 2); finish(P, [g, mb], (1,))
    V = GV.validate(P, T); types_ = IR.coordinate_domains(V.P, T.dom); assert types_[r.nid][0] != "RAW" and types_[g.nid][0] == "RAW"                 # the frozen executable copy carries the same typing
    DM.compile_demand(V.P, tables={x.fid: x.table for x in T.factors}); assert IR.coordinate_domains(V.P, T.dom) == types_                              # demand maps do not change coordinate domains
    prog, qs, nfac, nratio, nconst = IR.flatten(V); assert nratio >= 1                                                                                 # the class map / ratio are serialized (the kernel receives the expansion, never the bare class rows)
    # a mutation after validation cannot reach execution (the executable copy is frozen)
    rec = Q.run("GENERAL_BIDI_COMPLETE_V3", mp, ep, str(tmp_path / "frozen"), rules=[], b64=False, hooks={"mutate_program": lambda P2: (P2.__setattr__("nodes", copy.deepcopy(P.nodes)), P2.__setattr__("roots", list(P.roots))), "after_validate": lambda P2: P2.nodes.__getitem__(g.nid).__setattr__("gaxes", ({"out_pos": 0},))}); assert Q.exact_rows(rec, truth)


def test_SA4_exact_jet_oracle_multiplies_independent_roots_and_lifts_decoder_constants(tmp_path):
    mp, ep, S, T, truth = snap(tmp_path, "disc", [2, 2], [((0,), (1, 3)), ((1,), (2, 3))]); P = IR.Program()
    for f in T.factors:
        n = P.source(f.fid, f.scope, f.card); m = P.marker(f.scope[0], f.card[0]); r = P.reduce(P.mul([n, m]), f.scope); P.roots.append(r.nid)
    V = GV.validate(P, T); assert RT.jet_rows(V) == truth == {0: [Fr(1, 4), Fr(3, 4)], 1: [Fr(2, 5), Fr(3, 5)]}
    # production programs with FIXED (evidence) and ALIASED original variables: the decoder carries constants and eta-weighted class entries
    mp2, ep2 = Q.write_uai(str(tmp_path / "fx.uai"), [2, 3, 2, 2], [((0, 1), [1, 2, 3, 4, 5, 6]), ((1, 2), [1, 0, 2, 0, 3, 0]), ((2, 3), [1, 0, 0, 1])], {0: 1}); S2, Z2, N2, rows2 = Q.truth(mp2, ep2)
    S_, R_, T2, plan, _ = Q.plan_program(mp2, ep2, rules=Q.RULES_ALL); V2 = GV.validate(plan.program, T2); got = RT.jet_rows(V2)
    assert got == {v: list(r) for v, r in enumerate(rows2)}, (got, rows2)
    assert any(e[0] == "C" for v in T2.dec for e in T2.dec[v]) and T2.nvars_reduced < 4                                                          # constants (fixed variable) and aliased / excluded variables are present in this fixture
    # disconnected components with a scalar factor and a zero-free component: product rule again
    mp3, ep3 = Q.write_uai(str(tmp_path / "d3.uai"), [2, 3, 2], [((0,), [1, 3]), ((1, 2), [1, 2, 3, 4, 5, 6]), ((), [Fr(5, 8)])]); S3, Z3, N3, rows3 = Q.truth(mp3, ep3)
    S_, R_, T3, plan3, _ = Q.plan_program(mp3, ep3); V3 = GV.validate(plan3.program, T3); assert len(V3.P.roots) >= 2 and RT.jet_rows(V3) == {v: list(r) for v, r in enumerate(rows3)}


def test_SA5_mutation_enumeration_is_the_finite_set_it_claims_and_still_finds_no_accepted_wrong_program(tmp_path):
    card = [3, 2, 3, 2]; facs = Q.rnd_model(20, card, [(0, 1), (1, 2), (2, 3), (0, 3)], zeros=0.2); mp, ep = Q.write_uai(str(tmp_path / "m.uai"), card, facs); S, Z, N, rows = Q.truth(mp, ep); truth = {v: list(r) for v, r in enumerate(rows)}
    S_, R_, T, plan, cands = Q.plan_program(mp, ep, two_axis=False); P = plan.program; muts = RT._mutations(P)
    labels = sorted({m[0].split("@")[0] for m in muts}); assert len(muts) >= 60 and "reps_forge" in labels and "reps_perm" in labels and "proj_swap" in labels, (len(muts), labels)
    rej, ok, wrong = RT._adversarial(P, T, truth); assert not wrong and rej + ok == len(muts)
    # the reviewer's single-field reps substitution class is now part of the enumerated set: every kept axis gets a permutation forgery
    kept = sum(1 for n in P.nodes if n.kind == IR.REDUCE for k, r in enumerate(n.rmap) if r >= 0); assert sum(1 for m in muts if m[0].startswith("reps_perm")) == kept


# ============================================================================================================ SB  compositional cold recurrences + two-axis alternative (brief B)
def _tree(h):
    edges = []; nxt = [0]
    def build(d):
        if not d:
            q = nxt[0]; nxt[0] += 1; return q
        l = build(d - 1); r = build(d - 1); q = nxt[0]; nxt[0] += 1; edges.extend([(l, q), (r, q)]); return q
    build(h); return [2] * nxt[0], [(sc, [1, 2, 3, 5]) for sc in edges]


def _ve_truth(card, facs):
    """exact normalized singleton rows by variable elimination in Fractions (independent of the planner / kernel; used where brute force is too large)"""
    def ve(fixed):
        tabs = []
        for sc, tab in facs:
            tabs.append((tuple(sc), {idx: Fr(tab[sum(idx[j] * (int(__import__("math").prod(card[v] for v in sc[j + 1:]))) for j in range(len(sc)))]) for idx in itertools.product(*(range(card[v]) for v in sc))}))
        for v in range(len(card)):
            keep = [t for t in tabs if v not in t[0]]; mine = [t for t in tabs if v in t[0]]
            if not mine:
                continue
            scope = tuple(sorted(set(u for t in mine for u in t[0]) - {v})); out = {}
            for idx in itertools.product(*(range(card[u]) for u in scope)):
                asg = dict(zip(scope, idx)); tot = Fr(0)
                for s in ([fixed[v]] if v in fixed else range(card[v])):
                    asg[v] = s; w = Fr(1)
                    for sc, t in mine:
                        w *= t[tuple(asg[u] for u in sc)]
                    tot += w
                out[idx] = tot
            tabs = keep + [(scope, out)]
        z = Fr(1)
        for sc, t in tabs:
            z *= t[()]
        return z
    Z = ve({}); return {v: [ve({v: s}) / Z for s in range(card[v])] for v in range(len(card))}


def _classes(rec):
    a = rec["attempts"][-1]; fw = a["counters_after_forward"]; c = a["counters"]; p = rec["plan"]["totals"]["predicted"]
    return {"forward": (p["forward_rows"], fw["reduce_terms"]), "reverse_value": (p["reverse_value_rows"], c["reverse_value_terms"]), "reverse_combined": (p["reverse_combined_rows"], c["combined_terms"]), "reverse_pull": (p["reverse_pull_rows"], c["reverse_tuples"]), "sparse_pull": (p["sparse_pull_rows"], c["sparse_reverse_rows"])}


@pytest.mark.parametrize("h", [1, 2, 3, 4, 5])
def test_SB1_streamed_branching_tree_every_predicted_row_class_equals_the_kernel_counter(tmp_path, h):
    card, facs = _tree(h); mp, ep = Q.write_uai(str(tmp_path / "t.uai"), card, facs); rows = _ve_truth(card, facs)
    if h <= 3:
        S, Z, N, brute = Q.truth(mp, ep); assert {v: list(r) for v, r in enumerate(brute)} == rows                                                     # the elimination oracle agrees with brute force where brute force is affordable
    sw = dict(views=False, demand_masks=False, fusion=False, two_axis=False, orders=("original_id",))
    cold = Q._run_cfg(mp, ep, str(tmp_path / "cold"), rules=[], b64=True, budget=60, ledger=GM.Ledger(dict(GM.CAPS, value_cache_blocks=1)), **sw); assert Q.contained(cold, rows)
    cl = _classes(cold); assert all(p == c for p, c in cl.values()), cl                                                                              # EXACT equality on every class incl. the backward-phase VALUE reconstruction
    assert cl["reverse_value"][0] > cl["forward"][0] and Q.counters(cold)["downgrades"] == 0, cl                                                     # the reverse reconstruction exceeds the forward work (the omitted term) and the plan foresaw every stream (no kernel downgrade)
    t = cold["plan"]["totals"]; assert t["cold_work_proxy"] >= Q.counters(cold)["adds"] + Q.counters(cold)["mults"] and t["cost_model"].startswith("compositional")
    # retained counterpart (default caps): every message materialized; reverse work = stored entries drained once, no reconstruction
    ret = Q._run_cfg(mp, ep, str(tmp_path / "ret"), rules=[], b64=True, budget=60, **sw); assert Q.exact_rows(ret, rows) or Q.contained(ret, rows)
    cr = _classes(ret); assert all(p == c for p, c in cr.values()), cr; assert cr["reverse_value"][1] == 0 and ret["plan"]["totals"]["cold_work_proxy"] < cold["plan"]["totals"]["cold_work_proxy"]


def test_SB2_recurrence_holds_on_sparse_shared_and_mixed_retention_programs(tmp_path):
    n = 3; f = [1 + (i % 17) for i in range(9)]; g = [(1 + a if a == b else 0) for a in range(3) for b in range(3)]; mp, ep = Q.write_uai(str(tmp_path / "sp.uai"), [3, 3, 3], [((0, 1), f), ((1, 2), g), ((2,), [1, 2, 3])]); S, Z, N, rows = Q.truth(mp, ep)
    rec = Q._run_cfg(mp, ep, str(tmp_path / "s"), rules=[], b64=False, views=False, two_axis=False, fusion=False, orders=("original_id",)); cl = _classes(rec); assert Q.exact_rows(rec, rows) and all(p == c for p, c in cl.values()), cl
    card = [3, 3, 3, 3]; facs = Q.rnd_model(22, card, [(0, 1), (1, 2), (2, 3), (0, 3)]); mp2, ep2 = Q.write_uai(str(tmp_path / "m.uai"), card, facs); S2, Z2, N2, rows2 = Q.truth(mp2, ep2)
    for cap in (GM.CAPS["value_cache_blocks"], 2000, 1):
        rec = Q.run("GENERAL_BIDI_COMPLETE_V3", mp2, ep2, str(tmp_path / ("c%d" % cap)), rules=[], b64=False, ledger=GM.Ledger(dict(GM.CAPS, value_cache_blocks=cap))); cl = _classes(rec)
        assert Q.tight(rec, rows2) and all(p == c for p, c in cl.values()), (cap, cl)                                                              # mixed retention under a cap the PLAN decides: still exact
    # the n=3 / 10 / 25 fusion regression (first review) keeps its ordering under the compositional model
    for n in (3, 10, 25):
        f = [1 + (i % 17) for i in range(n * n)]; g = [(1 + a if a == b else 0) for a in range(n) for b in range(n)]; h = [1 + b for b in range(n)]; mpn, epn = Q.write_uai(str(tmp_path / ("d%d.uai" % n)), [n, n, n], [((0, 1), f), ((1, 2), g), ((2,), h)])
        unf = Q._run_cfg(mpn, epn, str(tmp_path / ("u%d" % n)), rules=[], b64=False, views=False, two_axis=False, fusion=False, orders=("original_id",)); mod = Q._run_cfg(mpn, epn, str(tmp_path / ("m%d" % n)), rules=[], b64=False, views=False, two_axis=False, fusion=True, orders=("original_id",))
        assert mod["plan"]["totals"]["cold_work_proxy"] <= unf["plan"]["totals"]["cold_work_proxy"] and RT.work(Q.counters(mod)) <= RT.work(Q.counters(unf))
        assert all(p == c for p, c in _classes(mod).values()) and all(p == c for p, c in _classes(unf).values())


@pytest.mark.parametrize("n", [4, 8, 16, 32])
def test_SB3_two_axis_alternative_is_retained_and_the_one_axis_plan_with_its_view_wins_by_the_one_cost(tmp_path, n):
    f = [a + 1 for a in range(n)] + [2 * (a + 1) if a < n - 1 else 3 * (a + 1) for a in range(n)]; mp, ep = Q.write_uai(str(tmp_path / "p.uai"), [2, n], [((0, 1), f)]); S, Z, N, rows = Q.truth(mp, ep)
    one = Q._run_cfg(mp, ep, str(tmp_path / "one"), rules=[], b64=False, two_axis=False, fusion=True); two = Q._run_cfg(mp, ep, str(tmp_path / "two"), rules=[], b64=False, two_axis=True, fusion=True)
    assert Q.exact_rows(one, rows) and Q.exact_rows(two, rows)
    ch = [c for c in two["plan_candidates"] if c.get("chosen")][0]; alt = [c for c in two["plan_candidates"] if c.get("cutset") == "two_axis" and c.get("state") == "COMPLETE"]
    assert ch["cutset"] == "one_axis" and alt and alt[0]["totals"]["cold_work_proxy"] > ch["totals"]["cold_work_proxy"], (ch["cutset"], ch["totals"]["cold_work_proxy"], [a["totals"]["cold_work_proxy"] for a in alt])   # both complete alternatives recorded; the cheaper one-axis plan (with its compressed view) wins
    assert two["plan"]["totals"]["cold_work_proxy"] == one["plan"]["totals"]["cold_work_proxy"] and two["mechanisms"]["views"]["compressed_axes"] >= 1 and two["mechanisms"]["two_axis"]["chosen"] == 0 and two["mechanisms"]["two_axis"]["declined"] >= 1
    assert RT.work(Q.counters(two)) == RT.work(Q.counters(one))                                                                                      # the executed work equals the one-axis plan's (the dearer representation is not executed)


def test_SB4_positive_two_axis_activation_still_wins_where_it_is_cheaper_and_every_alternative_is_recorded(tmp_path):
    for dcard in (2, 3, 5):
        mp, ep = Q._c16_model(str(tmp_path / ("c16_%d.uai" % dcard)), dcard); S, Z, N, rows = Q.truth(mp, ep)
        two = Q._run_cfg(mp, ep, str(tmp_path / ("two%d" % dcard)), rules=[], b64=False, two_axis=True, fusion=False); assert Q.exact_rows(two, rows)
        ch = [c for c in two["plan_candidates"] if c.get("chosen")][0]; cs = {c.get("cutset") for c in two["plan_candidates"] if c.get("state") == "COMPLETE"}
        assert cs == {"one_axis", "two_axis"} and ch["cutset"] == "two_axis" and two["mechanisms"]["two_axis"]["chosen"] >= 1, (ch["cutset"], cs, two["mechanisms"]["two_axis"])
        one_cost = min(c["totals"]["cold_work_proxy"] for c in two["plan_candidates"] if c.get("state") == "COMPLETE" and c.get("cutset") == "one_axis"); assert ch["totals"]["cold_work_proxy"] <= one_cost
        nt = two["plan"]["node_table"]; assert [n for n in nt if n["kind"] == "REDUCE" and n.get("prov", {}).get("two_axis") is True and len(nt[n["children"][0]]["axes"]) - len(n["axes"]) == 2]
    # UNKNOWN rule: a count beyond the declared bound ranks after every known candidate (deterministic), never a crash
    view = {"dom": {0: (0, 1), 1: (0, 1)}, "factors": [(0, (0, 1), (2, 2), (Fr(1), Fr(2), Fr(3), Fr(4)))], "scale": Fr(1)}; clock = Clock(time.monotonic() + 5, 20); B = PL.Builder(view, PL.ARMS["GENERAL_BIDI_COMPLETE_V3"], clock); pl = PL.Plan("original_id", [0, 1]); pl.roots = B.build([0, 1], pl)
    B.storage_pass(pl, 64, PL.CAPS); t = PL.totals(B, pl, 64); assert t["cold_work_proxy"] is not None and t["unknown"] is False
    old = PL.COUNT_BOUND; PL.COUNT_BOUND = 1
    try:
        t2 = PL.totals(B, pl, 64); assert t2["cold_work_proxy"] is None and t2["unknown"] is True
    finally:
        PL.COUNT_BOUND = old


# ============================================================================================================ SC  sparse reverse under pending pressure (brief C)
def test_SC1_tight_pending_capacity_keeps_the_support_indexed_reverse_on_every_entry_path(tmp_path):
    n = 14; K = 1 << n; t = [0] * K; t[0] = 3; t[-1] = 5; mp, ep = Q.write_uai(str(tmp_path / "s.uai"), [2] * n, [(tuple(range(n)), t)]); S, Z, N, rows = Q.truth(mp, ep)
    for cap in (512 << 20, 200, 1):
        r = Q.run("GENERAL_BIDI_COMPLETE_V3", mp, ep, str(tmp_path / ("c%d" % cap)), rules=[], b64=False, ledger=GM.Ledger(dict(GM.CAPS, pending_adjoints=cap)), fallback=False); fw = r["attempts"][-1]["counters_after_forward"]; c = Q.counters(r)
        # FIXTURE CHANGE (third review repair, 2026-11-10): the support-indexed pullback is now an EXPLICIT frame of the frame machine (one per drained slot), counted as a
        # pullback frame: 1 sparse-pull frame + 2 MUL pullback frames = 3 reverse frames for the single stored output (the reverse source reads stay exactly 2)
        assert Q.exact_rows(r, rows) and fw["sparse_rows_joined"] == 2 and c["source_reads"] - fw["source_reads"] == 2 and c["pullback_frames"] - fw["pullback_frames"] == 3 and c["sparse_reverse_rows"] == 2 and c["reverse_tuples"] == 0 and c["sparse_reverse_generic"] == 0, (cap, c)
        if cap == 1:
            assert c["sparse_reverse_immediate"] >= 1 and c["early_flushes"] >= 1                                                                    # the immediate path used the SAME support-indexed operation
    # multiple outputs + external adjoints + shared uses: the diagonal chain's sparse message (3 outputs, consumed by a parent product with other operands) under caps 1 / 200
    f = [1 + (i % 17) for i in range(9)]; g = [(1 + a if a == b else 0) for a in range(3) for b in range(3)]; mp2, ep2 = Q.write_uai(str(tmp_path / "d.uai"), [3, 3, 3], [((0, 1), f), ((1, 2), g), ((2,), [1, 2, 3])]); S2, Z2, N2, rows2 = Q.truth(mp2, ep2)
    base = None
    for cap in (512 << 20, 200, 1):
        r = Q._run_cfg(mp2, ep2, str(tmp_path / ("d%d" % cap)), rules=[], b64=False, views=False, two_axis=False, fusion=False, orders=("original_id",), ledger=GM.Ledger(dict(GM.CAPS, pending_adjoints=cap)), fallback=False); c = Q.counters(r)
        assert Q.exact_rows(r, rows2) and c["sparse_reverse_rows"] == 3 and c["sparse_reverse_generic"] == 0, (cap, c)
        base = base or c["source_reads"]; assert c["source_reads"] == base                                                                           # identical reverse reads whatever the pending capacity
    # late increments under a small (not minimal) cap on a cyclic model: exact-once deltas, answer exact
    card = [3, 3, 3, 3]; facs = Q.rnd_model(22, card, [(0, 1), (1, 2), (2, 3), (0, 3)]); mp3, ep3 = Q.write_uai(str(tmp_path / "m.uai"), card, facs); S3, Z3, N3, rows3 = Q.truth(mp3, ep3)
    r = Q.run("GENERAL_BIDI_COMPLETE_V3", mp3, ep3, str(tmp_path / "late"), rules=[], b64=False, ledger=GM.Ledger(dict(GM.CAPS, pending_adjoints=600)), fallback=False); c = Q.counters(r); assert Q.tight(r, rows3) and (c["early_flushes"] >= 1 or c["immediate_pullback_frames"] >= 1)
    # nonbinary supports (ternary 5 axes, 3 supported rows) at cap 1
    card = [3] * 5; tab = [0] * 243; tab[0] = 1; tab[121] = 2; tab[242] = 4; mp4, ep4 = Q.write_uai(str(tmp_path / "t.uai"), card, [((0, 1, 2, 3, 4), tab), ((0,), [1, 2, 3])]); S4, Z4, N4, rows4 = Q.truth(mp4, ep4)
    r = Q.run("GENERAL_BIDI_COMPLETE_V3", mp4, ep4, str(tmp_path / "tern"), rules=[], b64=False, ledger=GM.Ledger(dict(GM.CAPS, pending_adjoints=1)), fallback=False); c = Q.counters(r); fw = r["attempts"][-1]["counters_after_forward"]
    assert Q.exact_rows(r, rows4) and c["sparse_reverse_rows"] == 3 and c["reverse_tuples"] == 0 and c["source_reads"] - fw["source_reads"] <= 6
    # the labelled generic fallback counter exists on both entry paths (queued drain and immediate) and is zero whenever the CSR is retained
    assert "sparse_reverse_generic" in EX.COUNTER_DEFINITIONS and "sparse_reverse_immediate" in EX.COUNTER_DEFINITIONS and "immediate_pullback_frames" in EX.COUNTER_DEFINITIONS


# ============================================================================================================ SD  one all-consumer demand contract (brief D)
def _shared_program(T, n_shared=1):
    """w(X) shared by two additive consumers (RF5); with n_shared = 2 a SECOND shared message v(Y) feeds two more consumers through a joint root"""
    fw = [f for f in T.factors if f.table == (Fr(1), Fr(2), Fr(3))][0]; fh = [f for f in T.factors if f.table == (Fr(1), Fr(0), Fr(1))][0]
    P = IR.Program(); P.derived = {101: {"kind": "additive_split", "parent": fh.fid, "parts": [(1, 0, 0), (0, 0, 1)], "index": 0}, 102: {"kind": "additive_split", "parent": fh.fid, "parts": [(1, 0, 0), (0, 0, 1)], "index": 1}}
    w = P.source(fw.fid, fw.scope, fw.card); mk = P.marker(0, 3); shared = P.mul([w, mk]); shared.storage = IR.DENSE
    h1 = P.source(101, fh.scope, fh.card); h2 = P.source(102, fh.scope, fh.card); c1 = P.mul([shared, h1]); c2 = P.mul([shared, h2]); add = P.addn([c1, c2]); root = P.reduce(add, {0}); root.storage = IR.DENSE; P.roots = [root.nid]
    if n_shared == 2:
        fv = [f for f in T.factors if f.table == (Fr(2), Fr(3), Fr(5))][0]; fk = [f for f in T.factors if f.table == (Fr(1), Fr(1), Fr(0))][0]
        P.derived.update({103: {"kind": "additive_split", "parent": fk.fid, "parts": [(1, 0, 0), (0, 1, 0)], "index": 0}, 104: {"kind": "additive_split", "parent": fk.fid, "parts": [(1, 0, 0), (0, 1, 0)], "index": 1}})
        v = P.source(fv.fid, fv.scope, fv.card); mk2 = P.marker(1, 3); sh2 = P.mul([v, mk2]); sh2.storage = IR.DENSE; k1 = P.source(103, fk.scope, fk.card); k2 = P.source(104, fk.scope, fk.card)
        d1 = P.mul([sh2, k1]); d2 = P.mul([sh2, k2]); add2 = P.addn([d1, d2]); root2 = P.reduce(add2, {1}); root2.storage = IR.DENSE; P.roots.append(root2.nid)
    return P


def test_SD1_demand_switch_is_honoured_for_shared_programs_under_every_arm_and_the_compiler_records_itself(tmp_path):
    mp, ep = Q.write_uai(str(tmp_path / "sh.uai"), [3], [((0,), [1, 2, 3]), ((0,), [1, 0, 1])]); S, Z, N, rows = Q.truth(mp, ep)
    def mut(P):
        S_, R_, T_, plan, _ = Q.plan_program(mp, ep); P2 = _shared_program(T_); P.nodes = P2.nodes; P.roots = P2.roots; P.derived = P2.derived
    out = {}
    for arm in ("GENERAL_BIDI_COMPLETE_V3", "A1_NO_DEMAND_MASKS", "NATIVE_PLAIN_COMPLETE_V3", "A2_NO_FUSION", "A3_NO_RESPONSE_VIEWS"):
        rec = Q.run(arm, mp, ep, str(tmp_path / arm), rules=[], b64=False, hooks={"mutate_program": mut}); d = rec["demand_all_consumers"]; out[arm] = d
        assert Q.exact_rows(rec, rows) and d["optional_enabled"] == rec["mechanisms_enabled"]["demand_masks"] and "phase_s" in d, (arm, d)
        if rec["mechanisms_enabled"]["demand_masks"]:
            assert d["restricted"] == [2] and d["entries_saved"] == 1 and d["rows_inspected"] >= 1 and d["peak_live_bytes"] > 0 and Q.counters(rec)["reads_outside_demand"] == 0
        else:
            assert d["restricted"] == [] and d["entries_saved"] == 0 and all(n["demand"] == "FULL" for n in rec["plan"]["node_table"]), (arm, d)      # disabled arms keep FULL optional demand (truth unchanged)
    # no-op shared case (every consumer reads every entry): compiler runs, restricts nothing, records it
    mp2, ep2 = Q.write_uai(str(tmp_path / "noop.uai"), [3], [((0,), [1, 2, 3]), ((0,), [1, 1, 1])]); S2, Z2, N2, rows2 = Q.truth(mp2, ep2)
    def mut2(P):
        S_, R_, T_, plan, _ = Q.plan_program(mp2, ep2); fw = [f for f in T_.factors if f.table == (Fr(1), Fr(2), Fr(3))][0]; fh = [f for f in T_.factors if f.table == (Fr(1), Fr(1), Fr(1))][0]
        P2 = IR.Program(); P2.derived = {101: {"kind": "additive_split", "parent": fh.fid, "parts": [(1, 1, 0), (0, 0, 1)], "index": 0}, 102: {"kind": "additive_split", "parent": fh.fid, "parts": [(1, 1, 0), (0, 0, 1)], "index": 1}}
        w = P2.source(fw.fid, fw.scope, fw.card); mk = P2.marker(0, 3); sh = P2.mul([w, mk]); sh.storage = IR.DENSE; h1 = P2.source(101, fh.scope, fh.card); h2 = P2.source(102, fh.scope, fh.card); add = P2.addn([P2.mul([sh, h1]), P2.mul([sh, h2])]); root = P2.reduce(add, {0}); root.storage = IR.DENSE; P2.roots = [root.nid]
        P.nodes = P2.nodes; P.roots = P2.roots; P.derived = P2.derived
    rec = Q.run("GENERAL_BIDI_COMPLETE_V3", mp2, ep2, str(tmp_path / "noop"), rules=[], b64=False, hooks={"mutate_program": mut2}); assert Q.exact_rows(rec, rows2) and rec["demand_all_consumers"]["restricted"] == [] and rec["demand_all_consumers"]["rows_inspected"] >= 1
    # multi-node shared case: two shared messages, both restricted, exact
    mp3, ep3 = Q.write_uai(str(tmp_path / "two.uai"), [3, 3], [((0,), [1, 2, 3]), ((0,), [1, 0, 1]), ((1,), [2, 3, 5]), ((1,), [1, 1, 0])]); S3, Z3, N3, rows3 = Q.truth(mp3, ep3)
    def mut3(P):
        S_, R_, T_, plan, _ = Q.plan_program(mp3, ep3); P2 = _shared_program(T_, 2); P.nodes = P2.nodes; P.roots = P2.roots; P.derived = P2.derived
    rec = Q.run("GENERAL_BIDI_COMPLETE_V3", mp3, ep3, str(tmp_path / "two"), rules=[], b64=False, hooks={"mutate_program": mut3}); d = rec["demand_all_consumers"]
    assert Q.exact_rows(rec, rows3) and len(d["shared_nodes"]) == 2 and len(d["restricted"]) == 2 and d["entries_saved"] == 2 and Q.counters(rec)["reads_outside_demand"] == 0, d


def test_SD2_one_aggregate_row_and_wall_budget_with_reserve_before_build_and_full_on_exhaustion(tmp_path):
    n = 1000; depth = 40; m = U.Model(net_type="MARKOV", nvars=1, card=[n], factors=[U.Factor(scope=(0,), card=(n,), table=[Fr(1)] * n, index=0), U.Factor(scope=(0,), card=(n,), table=[Fr(2)] * n, index=1)])
    R = SRC.Reduced(EX._ModelAdapter(m), {}); R.reduce(()); T = TR.TrustedReduced(R); f1, f2 = T.factors
    def build():
        P = IR.Program(); P.derived = {101: {"kind": "additive_split", "parent": f2.fid, "parts": [(1,) * n, (1,) * n], "index": 0}, 102: {"kind": "additive_split", "parent": f2.fid, "parts": [(1,) * n, (1,) * n], "index": 1}}
        f = P.source(f1.fid, (0,), (n,)); mk = P.marker(0, n); sh = P.mul([f, mk]); sh.storage = IR.DENSE
        for k in range(depth):
            sh = P.gather(sh, (0,), (n,), gaxes=[{"out_pos": 0}]); sh.storage = IR.DENSE
        h1 = P.source(101, (0,), (n,)); h2 = P.source(102, (0,), (n,)); add = P.addn([P.mul([sh, h1]), P.mul([sh, h2])]); r = P.reduce(add, {0}); r.storage = IR.DENSE; P.roots = [r.nid]; return P
    tables = {f.fid: f.table for f in T.factors}
    # (1) row cap 1,000 (aggregate): the compiler stops at the first lift it cannot afford, charges the shared rows it did inspect, restricts nothing
    P = build(); clock = Clock(time.monotonic() + 60, 20); clock.row_cap = n; clock.begin_optional(); led = GM.Ledger(); tracemalloc.start(); rec = DM.compile_demand(P, row_cap=clock.remaining_rows(), tables=tables, clock=clock, ledger=led); peak = tracemalloc.get_traced_memory()[1]; tracemalloc.stop()
    assert rec["restricted"] == [] and rec["skipped_cap"] and clock.rows == rec["rows_inspected"] >= 1 and clock.rows <= n and peak < 200_000 and GV.validate(P, T).record["status"] == "VALID", (rec, clock.record(), peak)
    assert led.used["source_ir_maps_output"] == 0 and rec["peak_live_bytes"] > 0                                                                      # every live set was reserved and released
    # (2) an expired optional allowance stops the refinement BEFORE any set is built (nothing restricted; typed stop recorded)
    P = build(); clock = Clock(time.monotonic() + 60, 20); clock.optional_allowance_s = 0; clock.begin_optional(); time.sleep(0.002); rec = DM.compile_demand(P, row_cap=10 ** 6, tables=tables, clock=clock, ledger=GM.Ledger())
    assert rec["stop"] and rec["stop"]["kind"] == "DISCOVERY_WALL" and rec["restricted"] == [] and rec["rows_inspected"] == 0 and clock.expired
    # (3) default budget: the 49-node shared program IS compiled: 47,000 rows charged to the shared row cap, every set reserved before it was built, result exact
    P = build(); clock = Clock(time.monotonic() + 60, 20); clock.begin_optional(); led = GM.Ledger(); tracemalloc.start(); rec = DM.compile_demand(P, row_cap=clock.remaining_rows(), tables=tables, clock=clock, ledger=led); peak = tracemalloc.get_traced_memory()[1]; tracemalloc.stop()
    assert rec["stop"] is None and clock.rows == rec["rows_inspected"] == 49 * n + 1 and rec["peak_live_bytes"] >= 48 * n and peak <= 2 * rec["peak_live_bytes"] + 300_000, (rec["rows_inspected"], rec["peak_live_bytes"], peak)   # 49 use edges (root 1 + 48 lifts of 1,000 indices): every lifted index is a charged row; traced peak within the reserved live sets
    assert GV.validate(P, T).record["status"] == "VALID" and led.used["source_ir_maps_output"] == 0
    # (4) a ledger that cannot hold one set: typed MEMORY stop, nothing restricted, nothing left charged
    P = build(); clock = Clock(time.monotonic() + 60, 20); clock.begin_optional(); led = GM.Ledger(dict(GM.CAPS, source_ir_maps_output=10_000)); rec = DM.compile_demand(P, row_cap=10 ** 6, tables=tables, clock=clock, ledger=led)
    assert rec["stop"] and rec["stop"]["kind"] == "MEMORY_CATEGORY" and rec["restricted"] == [] and led.used["source_ir_maps_output"] == 0


# ============================================================================================================ SE  resource / polling transitions (brief E)
def _primes(k):
    p = 2; pr = []
    while len(pr) < k:
        if all(p % q for q in pr if q * q <= p):
            pr.append(p)
        p += 1
    return pr


def test_SE1_fallback_bit_growth_is_bounded_before_growth_and_the_legal_run_restores_the_exact_scale(tmp_path):
    pr = _primes(1000); m = U.Model(net_type="MARKOV", nvars=1, card=[1000], factors=[U.Factor(scope=(0,), card=(1000,), table=[Fr(1, q) for q in pr], index=0)]); S = types.SimpleNamespace(model=m, ev={})
    EX.Lib.get(); led = GM.Ledger(dict(GM.CAPS, frames_scratch_pub=1 << 20)); tracemalloc.start(); r = EX.exact_fallback(S, time.monotonic() + 60, led); peak = tracemalloc.get_traced_memory()[1]; tracemalloc.stop()
    assert r["status"] == "MEMORY" and r["phase"] == "preparation" and peak < 200_000 and r["allocated_before_stop"] < (1 << 20), (r, peak)      # refused BEFORE the cleared integers exist (lcm bits = sum of 1,000 prime bit lengths)
    led = GM.Ledger(); r = EX.exact_fallback(S, time.monotonic() + 60, led); assert r["status"] == "COMPLETE" and r["Z"] == sum(m.factors[0].table, Fr(0)) and r["N"][0] == list(m.factors[0].table) and Fr(r["scale_restored"]) * 1 == Fr(r["scale_restored"])
    # a model whose rationals have small common denominators is NOT over-reserved: the actual lcm (3) is used, not the 2 x 50,000-bit worst case
    m2 = U.Model(net_type="MARKOV", nvars=1, card=[20000], factors=[U.Factor(scope=(0,), card=(20000,), table=[Fr(1 + (i % 2), 3) for i in range(20000)], index=0)]); S2 = types.SimpleNamespace(model=m2, ev={}); led = GM.Ledger(dict(GM.CAPS, frames_scratch_pub=16 << 20))
    r2 = EX.exact_fallback(S2, time.monotonic() + 60, led); assert r2["status"] == "COMPLETE" and r2["Z"] == sum(m2.factors[0].table, Fr(0))
    # deadline inside the preparation loops (cumulative counter): typed DEADLINE with the work count
    r3 = EX.exact_fallback(S, time.monotonic() - 1, GM.Ledger()); assert r3["status"] == "DEADLINE" and r3["phase"] == "preparation"


def test_SE2_native_reallocation_peaks_are_charged_and_failed_sparse_construction_leaves_no_ghost_charge(tmp_path):
    cpp = tmp_path / "probe.cpp"; exe = tmp_path / "probe"; src = open(os.path.join(os.path.dirname(HERE), "docs", "review-received-2026-11-10-general-bidi-v3-integrated-repair", "audit", "resources", "native_memory_probe.cpp")).read()
    cpp.write_text(src.replace('#include "../../source/code/gbidi3/kernel3.cpp"', '#include "%s/gbidi3/kernel3.cpp"' % HERE))
    rb = subprocess.run(["clang++", "-std=c++17", "-O2", "-ffp-model=strict", "-ffp-contract=off", "-I/opt/homebrew/include", "-L/opt/homebrew/lib", "-o", str(exe), str(cpp), "-lmpfr", "-lgmp"], capture_output=True, text=True, timeout=300); assert rb.returncode == 0, rb.stderr[-1500:]
    r = json.loads(subprocess.run([str(exe)], capture_output=True, text=True, timeout=60).stdout)
    g = r["grow_reallocation_peak"]; assert g["ok"] is False and g["observed_peak_allocation_bytes"] <= g["cap"] and g["charged_used"] == 128, g                   # 128 old + 256 new > 256: refused BEFORE allocating; nothing grew
    s = r["sparse_map_and_failure_cleanup"]; assert s["materialize_ok"] is False and s["stop"] == 2 and s["index_charged_after_downgrade"] == 0 and s["index_rows_retained_after_downgrade"] == 0, s   # scoped temporaries released on the failure path
    # integration: a failing sparse join at several index caps leaves zero charge after the downgrade and the answer stays exact (first review RE4 widened)
    n = 10; K = 1 << n; tab = [0] * K; tab[0] = 3; tab[K - 1] = 5; mp, ep = Q.write_uai(str(tmp_path / "s.uai"), [2] * n, [(tuple(range(n)), tab), ((0,), [1, 2])]); S, Z, N, rows = Q.truth(mp, ep)
    full = Q.run("GENERAL_BIDI_COMPLETE_V3", mp, ep, str(tmp_path / "full"), rules=[], b64=False); host = full["memory_ledger"]["used"]["source_ir_maps_output"]
    for cap in (1, 100, 300, 600):
        rec = Q.run("GENERAL_BIDI_COMPLETE_V3", mp, ep, str(tmp_path / ("cap%d" % cap)), rules=[], b64=False, ledger=GM.Ledger(dict(GM.CAPS, source_ir_maps_output=host + cap))); c = Q.counters(rec)
        assert Q.exact_rows(rec, rows) and (c.get("downgrades", 0) >= 1 and c.get("used_index_bytes", 0) <= 1 or rec.get("route") == "exact_fallback"), (cap, c.get("downgrades"), c.get("used_index_bytes"), rec.get("route"))


def test_SE3_validator_work_is_strided_polled_and_the_final_deadline_is_checked_before_VALID(tmp_path):
    n = 200; m = U.Model(net_type="MARKOV", nvars=2, card=[n, n], factors=[U.Factor(scope=(0, 1), card=(n, n), table=[Fr(1)] * (n * n), index=0)]); R = SRC.Reduced(EX._ModelAdapter(m), {}); R.reduce(()); T = TR.TrustedReduced(R)
    def build():
        P = IR.Program(); f = P.source(T.factors[0].fid, (0, 1), (n, n)); a = P.marker(0, n); mul = P.mul([f, a]); r = P.reduce(mul, (0,), reps={1: ((0,), tuple([0] * n), tuple([Fr(1)] * n))}); g = P.gather(r, (1,), (n,), gaxes=[{"out_pos": 0, "cls": tuple([0] * n), "ratio": tuple([Fr(1)] * n)}]); b = P.marker(1, n); z = P.reduce(P.mul([g, b]), (1,)); P.roots = [z.nid]; return P
    t = time.monotonic()
    with pytest.raises(TR.Invalid) as ex:
        GV.validate(build(), T, deadline=t + 0.001)
    assert "DEADLINE" in ex.value.reason and time.monotonic() - t < 0.25                                                                             # stops within a few polling quanta of the 1 ms deadline (not after 0.5 s of full-table rescans)
    V = GV.validate(build(), T, deadline=time.monotonic() + 30); rec = V.record
    assert rec["status"] == "VALID" and rec["checks"] >= rec["view_entries_inspected"] + rec["entrywise_checks"] and rec["view_entries_inspected"] == n * n                   # every inspected entry / coefficient is one ticked unit; one strided traversal of the 40,000-entry table
    Z, N, rows = OR.rows(m, {}); assert RT.jet_rows(V) == {v: list(r) for v, r in enumerate(rows)}
    # the production planner's own 200x200 view through the executor stays exact and bounded
    mp, ep = Q.write_uai(str(tmp_path / "v.uai"), [n, n], [((0, 1), [1] * (n * n))]); S, Zt, Nt, rows2 = Q.truth(mp, ep); r = Q.run("GENERAL_BIDI_COMPLETE_V3", mp, ep, str(tmp_path / "v"), rules=[], b64=False); assert Q.exact_rows(r, rows2) and r["plan_validation"]["checks"] >= 40000


def test_SE4_parser_hashing_admission_and_trusted_recheck_poll_cumulatively(tmp_path, monkeypatch):
    n = 50000; data = ("MARKOV 1 2 " + str(n) + " " + "1 0 " * n + "2 1 2 " * n).encode(); st = {"calls": 0, "expired": False, "polls": []}
    orig_r = GS._rational_token
    class DeadlineClock:
        def __call__(self):
            st["polls"].append(st["calls"]); return 2.0 if st["expired"] else 0.0
    def counted(*a):
        st["calls"] += 1; st["expired"] = True; return orig_r(*a)
    monkeypatch.setattr(GS.time, "monotonic", DeadlineClock()); monkeypatch.setattr(GS, "_rational_token", counted)
    with pytest.raises(GS.ParseStop) as ex:
        GS.parse_model_bytes(data, GS._Guard(GM.Ledger(), 1.0))
    monkeypatch.undo()
    assert ex.value.kind == "DEADLINE" and st["calls"] <= GS.POLL_TOKENS + 1 and st["calls"] >= 1, (st["calls"], len(st["polls"]))                 # the first poll AFTER the expiring rational comes within one 4,096-unit quantum, across 1,500 small factors
    # canonical hashing: cumulative ticks (one per entry) -> an expired deadline is seen within one quantum
    m = GS.parse_model_bytes(data); g = GS._Guard(None, time.monotonic() - 1); g.count = 0
    with pytest.raises(GS.ParseStop):
        GS.canonical_v2_model(m, g)
    assert g.count <= GS.POLL_TOKENS + 2
    # binary64 admission under the deadline; trusted identity re-check reserved + bounded
    with pytest.raises(TimeoutError):
        EX.binary64_admission(["1/3"] * 10000, deadline=time.monotonic() - 1)
    mp, ep = Q.write_uai(str(tmp_path / "m.uai"), [3, 3], Q.rnd_model(5, [3, 3], [(0, 1)])); S = GS.Snapshot(mp, ep); R = SRC.Reduced(EX._ModelAdapter(S.model), {}); R.reduce(()); T = TR.TrustedReduced(R); led = GM.Ledger()
    assert T.unchanged(R, ledger=led, deadline=time.monotonic() + 5) is True and led.used["source_ir_maps_output"] == 0
    with pytest.raises(TimeoutError):
        T.unchanged(R, ledger=led, deadline=time.monotonic() - 1)
    with pytest.raises(GM.MemoryStop):
        T.unchanged(R, ledger=GM.Ledger(dict(GM.CAPS, source_ir_maps_output=1)))
    # a zero-evidence proof is accepted only after the independent replay (the replay record is present on a ZERO_EVIDENCE_PROVED result)
    mpz, epz = Q.write_uai(str(tmp_path / "z.uai"), [2, 2], [((0, 1), [1, 0, 0, 1])], {0: 0, 1: 1}); rec = Q.run("GENERAL_BIDI_COMPLETE_V3", mpz, epz, str(tmp_path / "z")); assert rec["status"] == "ZERO_EVIDENCE_PROVED" and rec.get("source_replay") is not None


# ============================================================================================================ SF  parent-generated terminal receipts (brief F)
def _stage(D, name, extra_env=None, timeout="600"):
    return subprocess.run([PY, "-m", "gbidi.supervise", "--ledger", os.path.join(D, "GB_LEDGER.jsonl"), "--scope", "stage_outer_" + name, "--job", "stage_runner:" + name, "--timeout", timeout, "--cwd", HERE, "--env", "PYTHONPATH=" + HERE] + sum([["--env", "%s=%s" % kv] for kv in (extra_env or {}).items()], []) + ["--", PY, "-m", "gbidi3.pilot", "run", D, name], capture_output=True, text=True, cwd=HERE, env=ENV, timeout=900)


def test_SF1_interrupted_stage_runner_parent_cleanup_receipt_is_charged_as_an_envelope_reconciled_and_resumed_without_relaunch(tmp_path):
    from gbidi3_closeout import report as RP
    D = str(tmp_path / "run"); os.makedirs(D); n = 20000; mp = tmp_path / "synthetic.uai"; ep = tmp_path / "synthetic.uai.evid"
    mp.write_text("\n".join(["MARKOV", str(n), " ".join(["2"] * n), str(n - 1)] + ["2 %d %d" % (i, i + 1) for i in range(n - 1)] + ["4 1 2 3 4"] * (n - 1)) + "\n"); ep.write_text("")
    S = GS.Snapshot(str(mp), str(ep)); cs = RT._case(S, str(mp), str(ep), n)
    man = RT._manifest(tmp_path, {"synthetic": cs}, [{"stage": "review", "arm": "GENERAL_BIDI_COMPLETE_V3", "case": "synthetic", "budget_s": 20.0, "kind": "primary"}]); json.dump(man, open(os.path.join(D, "GB_MANIFEST.json"), "w"), indent=1); led = os.path.join(D, "GB_LEDGER.jsonl")
    cmd = [PY, "-m", "gbidi.supervise", "--ledger", led, "--scope", "stage_outer_review", "--job", "stage_runner:review", "--timeout", "60", "--cwd", HERE, "--env", "PYTHONPATH=" + HERE, "--", PY, "-m", "gbidi3.pilot", "run", D, "review"]
    p = subprocess.Popen(cmd, cwd=HERE, env=ENV, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True); killed = None
    try:
        for _ in range(6000):
            rows = []
            if os.path.exists(led):
                try:
                    rows = [json.loads(x) for x in open(led)]
                except json.JSONDecodeError:
                    rows = []
                starts = [r for r in rows if r["kind"] == "START"]; spawn = [r for r in rows if r["kind"] == "SPAWNED"]
                if len(starts) >= 2 and len(spawn) >= 2:
                    reg = os.path.join(starts[0]["owner_dir"], "groups.jsonl")
                    if os.path.exists(reg) and len(open(reg).read().splitlines()) >= 2:
                        killed = spawn[0]["pid"]
                        try:
                            os.kill(killed, signal.SIGKILL)
                        except ProcessLookupError:
                            killed = None
                        break
            if p.poll() is not None:
                break
            time.sleep(0.002)
        out, err = p.communicate(timeout=120)
    finally:
        if p.poll() is None:
            p.kill(); p.wait()
    assert killed is not None, "the stage runner finished before the nested cell registered (the synthetic task is meant to run for tens of seconds)"
    rows = [json.loads(x) for x in open(led)]; rc = [r for r in rows if r["kind"] == "RECEIPT"]; cell_rc = [r for r in rc if r["job"].startswith("cell:")]; outer_rc = [r for r in rc if r["job"] == "stage_runner:review"]
    assert len(cell_rc) == 1 and cell_rc[0]["outcome"] == "PARENT_CLEANUP_KILL" and cell_rc[0]["wall_s"] is None and cell_rc[0]["cleanup_unresolved"] is False and cell_rc[0]["written_by_parent"] == outer_rc[0]["jid"], cell_rc   # the UNCHANGED pinned supervisor's receipt; the owner receipt is its evidence reference
    assert outer_rc and outer_rc[0]["outcome"] != "COMPLETED" and outer_rc[0]["cleanup_unresolved"] is False and outer_rc[0]["group_empty_at_receipt"] is True and outer_rc[0]["nested_groups_killed"] >= 1 and outer_rc[0]["nested_groups_live_at_receipt"] == 0
    # charging: no arithmetic on the unknown wall; the attempt is charged at its envelope; the outer attempt is charged WHOLE (no manufactured remainder)
    total, by, unresolved, extra = PI.charged(D); c = man["cells"][0]
    assert not unresolved and extra["unknown_wall_receipts"] and extra["unknown_wall_receipts"][0]["envelope_s"] == c["budget_s"] + 4.0 and extra["unknown_wall_receipts"][0]["envelope_known"] is True
    assert total == pytest.approx(extra["measured_s"] + extra["envelope_s"], abs=1e-6) and extra["envelope_s"] >= c["budget_s"] + 4.0 and any(o.get("charged", "").startswith("whole outer wall") for o in extra["outer_attempts"]) and extra["measured_s"] == 0.0
    # reconciliation: typed noncertifying observation, accepted; status / closeout work; resume relaunches nothing
    row = RC.reconcile(D, man, c, RC.ledger_index(D)); assert row["accepted"] and row["status"] == "NO_RECORD" and row["resolution"] == "PARENT_CLEANUP_KILLED_NO_RECORD" and row["delivered_valid_output"] is False and row["wall_known"] is False and row["cleanup_evidence_reference"]["owner_jid"] == outer_rc[0]["jid"]
    B = RP.budget(D, man, RP.cells_ledger(D, man)); assert B["total_charged_s"] == pytest.approx(total)
    led1 = open(led).read(); r2 = _stage(D, "review"); assert "RESUME_CONFLICT" not in r2.stdout and "STOP:" not in r2.stdout, r2.stdout[-600:]
    led2 = open(led).read(); assert led2.count('"kind": "START"') == led1.count('"kind": "START"') + 1 and led2.count("cell:") == led1.count("cell:")   # exactly one new START (the stage runner), no new cell attempt
    # a forged cell.json claiming success for the killed attempt is NOT accepted (the parent receipt contradicts it); a parent receipt claiming a measured wall is NOT accepted
    cj = os.path.join(D, c["out_dir"], "cell.json"); good = json.load(open(cj)); forged = dict(good, status="CERTIFIED", task=dict(S.task), execution={"route": "mpfr"}, deadline_s=20.0, config=PI.CELL_CONFIG, complete_response_from_launch_s=1.0, deadline_classification_clock="launch-relative")
    json.dump(forged, open(cj, "w")); r = RC.reconcile(D, man, c, RC.ledger_index(D)); json.dump(good, open(cj, "w")); assert not r["accepted"]
    idx = RC.ledger_index(D); bad = copy.deepcopy(idx); bad[RC.job_name(c)]["RECEIPT"][0]["wall_s"] = 3.0; r = RC.reconcile(D, man, c, bad); assert not r["accepted"] and any("parent-cleanup receipt" in x for x in r["reasons"])
    bad = copy.deepcopy(idx); bad[RC.job_name(c)]["RECEIPT"][0]["written_by_parent"] = "nobody"; r = RC.reconcile(D, man, c, bad); assert not r["accepted"] and any("owner receipt" in x for x in r["reasons"])                   # no evidence reference -> not accepted


def test_SF2_charging_handles_null_nonfinite_duplicate_and_unresolved_receipts_without_arithmetic_on_unknowns(tmp_path):
    D = str(tmp_path); rows = []
    def S(jid, scope, job, parent=None, cap=24.0):
        rows.append({"kind": "START", "jid": jid, "scope": scope, "job": job, "start_utc": "2026-11-10T00:00:00Z", "max_permitted_charge_s": cap, "parent_jid": parent})
    def Rc(jid, job, wall, **kw):
        rows.append(dict({"kind": "RECEIPT", "jid": jid, "job": job, "wall_s": wall, "outcome": "COMPLETED", "cleanup_unresolved": False}, **kw))
    S("o1", "stage_outer_x", "stage_runner:x"); S("c1", "matrix_x", "cell:one", "o1"); S("c2", "matrix_x", "cell:two", "o1"); S("c3", "matrix_x", "cell:three", "o1", cap=10.0)
    Rc("c1", "cell:one", 5.0); Rc("c2", "cell:two", None, outcome="PARENT_CLEANUP_KILL", wall_known=False, written_by_parent="o1"); Rc("c3", "cell:three", float("nan")); Rc("o1", "stage_runner:x", 30.0)
    open(os.path.join(D, "GB_LEDGER.jsonl"), "w").write("\n".join(json.dumps(r) for r in rows) + "\n")
    total, by, unresolved, extra = PI.charged(D)
    assert extra["measured_s"] == 5.0 and {u["job"] for u in extra["unknown_wall_receipts"]} == {"cell:two", "cell:three"} and extra["envelope_s"] == 24.0 + 10.0 + 30.0 and total == pytest.approx(5.0 + 24.0 + 10.0 + 30.0) and not unresolved
    assert extra["outer_attempts"][0]["charged"].startswith("whole outer wall") and extra["outer_attempts"][0]["parent_remainder_s"] is None
    # a null wall WITHOUT an envelope is unresolved (listed), never silently zero
    rows.append({"kind": "START", "jid": "c4", "scope": "matrix_x", "job": "cell:four", "start_utc": "2026-11-10T00:00:00Z", "max_permitted_charge_s": None}); rows.append({"kind": "RECEIPT", "jid": "c4", "job": "cell:four", "wall_s": None, "outcome": "PARENT_CLEANUP_KILL", "cleanup_unresolved": False})
    open(os.path.join(D, "GB_LEDGER.jsonl"), "w").write("\n".join(json.dumps(r) for r in rows) + "\n"); total2, by2, unresolved2, extra2 = PI.charged(D); assert [u["job"] for u in unresolved2] == ["cell:four"] and total2 == pytest.approx(total)
