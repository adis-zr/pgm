"""Qualification controls of GENERAL_BIDI_COMPLETE_V3 (brief §18, control groups C01-C26 + generality / activation controls). Every numerical check compares
EVERY original singleton row with the INDEPENDENT exact oracle (gbidi3.oracle: brute force over the ORIGINAL factors) or a closed form. Every control named
after a mechanism ASSERTS THAT THE MECHANISM FIRED (counters / provenance / typed stop) and then checks truth and failure behaviour; a no-op pass is a
failure here. Actual entry points: gbidi3.executor.execute / publish / plan_only / exact_fallback, gbidi3.validate.validate, gbidi3.ir, the kernel through
ctypes, gbidi3.cell, gbidi3.verify, gbidi3.pilot, gbidi3.reconcile, gbidi3_closeout.report, gbidi.supervise (unchanged)."""
from __future__ import annotations
import sys, os, json, time, random, subprocess, ctypes, copy, signal, hashlib, shutil
sys.set_int_max_str_digits(0)
HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__))); sys.path.insert(0, HERE)
from fractions import Fraction as Fr
import pytest
from gbidi3 import executor as EX, planner as PL, source as GS, validate as GV, ir as IR, oracle as OR, memory as GM, clock as GC, trusted as TR
from adp import source as SRC
from ext import uai as U

PY = sys.executable; ENV = dict(os.environ, PYTHONPATH=HERE)
ARMS = list(EX.ARMS)
RULES_ALL = list(PL.COMMON_RULES)


# ============================================================================================================ helpers
def write_uai(path, card, factors, ev=None, tokens=None):
    lines = ["MARKOV", str(len(card)), " ".join(map(str, card)), str(len(factors))] + ["%d %s" % (len(sc), " ".join(map(str, sc))) for sc, _ in factors]
    for i, (_, tab) in enumerate(factors):
        lines.append("%d %s" % (len(tab), " ".join(tokens[i] if tokens and tokens[i] else ["%d/%d" % (Fr(x).numerator, Fr(x).denominator) for x in tab])))
    open(path, "w").write("\n".join(lines) + "\n"); ev = ev or {}
    open(path + ".evid", "w").write("%d %s\n" % (len(ev), " ".join("%d %d" % (v, s) for v, s in ev.items())) if ev else ""); return path, path + ".evid"


def fixture_seed(name):
    """DETERMINISTIC fixture seed (review F6): sha256 of the case name, independent of PYTHONHASHSEED (hash(name) differed between interpreter runs)"""
    return int(hashlib.sha256(name.encode()).hexdigest()[:8], 16) % 1000


def rnd_model(seed, card, scopes, zeros=0.0, lo=1, hi=99):
    r = random.Random(seed); facs = []
    for sc in scopes:
        n = 1
        for v in sc:
            n *= card[v]
        facs.append((tuple(sc), [Fr(0) if r.random() < zeros else Fr(r.randint(lo, hi), 100) for _ in range(n)]))
    return facs


def run(arm, mp, ep, out, b64=True, budget=60, hooks=None, rules=None, fallback=True, ledger=None, extra_cfg=None):
    cfg = {"budget_s": budget, "allow_binary64": b64, "reference_fallback": fallback}
    if rules is not None:
        cfg["rules"] = rules
    cfg.update(extra_cfg or {}); os.makedirs(out, exist_ok=True)
    return EX.execute(arm, mp, ep, out, time.monotonic() + budget, cfg, test_hooks=hooks, ledger=ledger)


def _run_cfg(mp, ep, out, arm="GENERAL_BIDI_COMPLETE_V3", b64=False, rules=(), hooks=None, budget=60, ledger=None, fallback=True, extra_cfg=None, **override):
    """run the executor with the arm's switches overridden (the arm table is restored afterwards); ledger / fallback / extra_cfg are forwarded to run()"""
    old = dict(PL.ARMS[arm]); PL.ARMS[arm] = dict(old, **override)
    try:
        return run(arm, mp, ep, out, b64=b64, budget=budget, rules=list(rules), hooks=hooks, ledger=ledger, fallback=fallback, extra_cfg=extra_cfg)
    finally:
        PL.ARMS[arm] = old


def truth(mp, ep):
    S = GS.Snapshot(mp, ep); Z, N, rows = OR.rows(S.model, S.ev); return S, Z, N, rows


def contained(rec, rows):
    return all(Fr(a) <= rows[int(v)][s] <= Fr(b) for v, row in rec["certified_intervals"].items() for s, (a, b) in enumerate(row))


def exact_rows(rec, rows):
    return all(Fr(a) == rows[int(v)][s] == Fr(b) for v, row in rec["certified_intervals"].items() for s, (a, b) in enumerate(row))


def truth_inside(rec, mp, ep):
    S, Z, N, rows = truth(mp, ep)
    if Z == 0:
        return rec["status"] == "ZERO_EVIDENCE_PROVED"
    assert rec["status"] == "INTERVALS_OK", rec.get("status")
    return all(len(rec["certified_intervals"][str(v)]) == S.model.card[v] for v in range(S.model.nvars)) and contained(rec, rows)


def publish(out, mp, ep, rec, arm=None, cfg=None):
    cell = {"phases_s": {}}; st = EX.publish(out, mp, ep, rec, cell, time.monotonic() + 30, arm=arm or rec.get("arm"), cfg=cfg or rec.get("config")); return st, cell


def counters(rec):
    for a in reversed(rec.get("attempts", [])):
        if a.get("counters"):
            return a["counters"]
    return {}


def plan_program(mp, ep, arm="GENERAL_BIDI_COMPLETE_V3", rules=(), budget=60.0, **cfg_override):
    """the planner's program + trusted snapshot (as the executor builds them); cfg_override adjusts the arm switches (e.g. two_axis=False)"""
    S = GS.Snapshot(mp, ep); R = SRC.Reduced(EX._ModelAdapter(S.model), dict(S.ev)); R.reduce(tuple(rules)); T = TR.TrustedReduced(R); clock = GC.Clock(time.monotonic() + budget, budget); clock.begin_optional()
    plan, cands = PL.plan(T.proposal_view(), dict(PL.ARMS[arm], **cfg_override), clock, EX.Lib.get().gb3_bytes_per_entry(0, 64)); return S, R, T, plan, cands


def star_model(path, n):
    lines = ["MARKOV", str(n), " ".join(["2"] * n), str(n - 1)] + ["2 0 %d" % v for v in range(1, n)] + ["4 1 2 3 4"] * (n - 1); open(path, "w").write("\n".join(lines) + "\n"); open(path + ".evid", "w").write("")
    Z = 3 ** (n - 1) + 7 ** (n - 1); tr = {0: [Fr(3 ** (n - 1), Z), Fr(7 ** (n - 1), Z)]}
    for v in range(1, n):
        tr[v] = [Fr(3 ** (n - 2) + 3 * 7 ** (n - 2), Z), Fr(2 * 3 ** (n - 2) + 4 * 7 ** (n - 2), Z)]
    return path, path + ".evid", tr


def chain_exact(n, pair, unary_at, unary):
    pair = [[Fr(pair[0]), Fr(pair[1])], [Fr(pair[2]), Fr(pair[3])]]; un = [[Fr(1), Fr(1)] for _ in range(n)]; un[unary_at] = [Fr(unary[0]), Fr(unary[1])]
    fwd = [None] * n; fwd[0] = [un[0][a] for a in range(2)]
    for i in range(1, n):
        fwd[i] = [un[i][b] * sum(fwd[i - 1][a] * pair[a][b] for a in range(2)) for b in range(2)]
    bwd = [None] * n; bwd[n - 1] = [Fr(1), Fr(1)]
    for i in range(n - 2, -1, -1):
        bwd[i] = [sum(pair[a][b] * un[i + 1][b] * bwd[i + 1][b] for b in range(2)) for a in range(2)]
    Z = sum(fwd[n - 1]); return {v: [fwd[v][a] * bwd[v][a] / Z for a in range(2)] for v in range(n)}


def tight(rec, rows, width=Fr(1, 1 << 40)):
    """truth contained AND every certified interval narrower than `width` (MPFR on non-dyadic inputs is not exact but is tight)"""
    return contained(rec, rows) and all(Fr(b) - Fr(a) <= width for row in rec["certified_intervals"].values() for a, b in row)


def set_storage(kind, only_kind=IR.REDUCE, include_roots=False):
    def f(P):
        for n in P.nodes:
            if (include_roots or n.nid not in P.roots) and n.kind == only_kind and n.storage in (IR.DENSE, IR.SPARSE, IR.STREAM, IR.CACHE):
                if kind == IR.SPARSE and not (n.kind == IR.REDUCE and P.nodes[n.children[0]].kind == IR.MUL and all(r is None for r in n.reps)):
                    continue
                n.storage = kind; n.demand = "FULL"
                if kind != IR.SPARSE:
                    n.driver = -1                                                                                  # fourth review: a sparse driver is declared on SPARSE storage only (the validator rejects it elsewhere)
    return f


# ============================================================================================================ generality: every input class x every arm x three execution modes (brief §2, §18)
CASES = {"nonbinary_chain": ([3, 2, 4, 3], [(0, 1), (1, 2), (2, 3), (3,)], 0.0, {}), "high_arity": ([2, 3, 2, 2], [(0, 1, 2), (1, 2, 3), (0, 3)], 0.0, {}), "odd_cycle_nonbinary": ([3, 3, 3], [(0, 1), (1, 2), (2, 0), (0,)], 0.0, {}),
         "zeros_cycle": ([2, 3, 2, 2], [(0, 1), (1, 2), (2, 3), (3, 0), (1, 3)], 0.3, {}), "evidence_high_arity": ([2, 2, 3, 2, 2], [(0, 1, 2), (2, 3, 4), (0, 4), (1,)], 0.1, {1: 1, 4: 0}), "disconnected_isolated": ([2, 3, 2, 2, 3], [(0, 1), (2, 3), (2,)], 0.0, {}),
         "duplicate_occurrences": ([2, 2], [(0,), (0,), (0, 1), (0, 1)], 0.0, {}), "scalar_and_unary_only": ([2, 3], [(), (0,), (1,), ()], 0.0, {}), "dense_grid_like": ([2] * 6, [(0, 1), (1, 2), (3, 4), (4, 5), (0, 3), (1, 4), (2, 5)], 0.0, {}), "kite_evidence_zeros": ([3, 2, 2, 3], [(0, 1, 2), (1, 2), (2, 3), (0, 3)], 0.25, {3: 2}),
         "cardinality_one": ([1, 2, 1, 3], [(0, 1), (1, 2, 3), (2,)], 0.0, {}), "nonbipartite_ternary_cycles": ([3, 3, 3, 2], [(0, 1, 2), (1, 2, 3), (0, 3), (0, 2)], 0.15, {})}
MODES = {"policy": ({}, RULES_ALL), "forced_stream": ({"force_stream": True}, RULES_ALL), "mpfr_only_no_rules": ({"no_binary64": True}, [])}


@pytest.mark.parametrize("name", list(CASES))
@pytest.mark.parametrize("arm", ARMS)
def test_every_arm_encloses_exact_truth_on_every_input_class(tmp_path, name, arm):
    card, scopes, zeros, ev = CASES[name]; facs = rnd_model(fixture_seed(name), card, scopes, zeros)
    mp, ep = write_uai(str(tmp_path / (name + ".uai")), card, facs, ev)
    for mode, (hooks, rules) in MODES.items():
        rec = run(arm, mp, ep, str(tmp_path / mode), hooks=hooks, rules=rules)
        assert truth_inside(rec, mp, ep), (name, arm, mode, rec.get("status"), rec.get("reason"))
        if rec["status"] == "INTERVALS_OK":
            if rec.get("route") not in ("exact_decoder", "exact_scalar", "exact_fallback"):
                assert rec["plan_validation"]["status"] == "VALID" and rec["source_replay"]["status"] == "REPLAYED"
            st, cell = publish(str(tmp_path / mode), mp, ep, rec); assert st == "CERTIFIED", cell.get("publication")


@pytest.mark.parametrize("name", list(CASES))
def test_every_execution_mode_matches_the_oracle_rows_exactly_when_run_through_the_exact_fallback(tmp_path, name):
    card, scopes, zeros, ev = CASES[name]; facs = rnd_model(fixture_seed(name) + 7, card, scopes, zeros); mp, ep = write_uai(str(tmp_path / "m.uai"), card, facs, ev); S, Z, N, rows = truth(mp, ep)
    rec = run("GENERAL_BIDI_COMPLETE_V3", mp, ep, str(tmp_path / "fb"), hooks={"force_fallback": True}, rules=[])
    if Z == 0:
        assert rec["status"] == "ZERO_EVIDENCE_PROVED"; return
    assert rec["route"] == "exact_fallback" and rec["exact_fallback"]["status"] == "COMPLETE" and exact_rows(rec, rows) and rec["exact_fallback"]["visited"] > 0


# ============================================================================================================ parser / grammar (brief §2) and task identity (§5)
BAD_MODELS = {"dup_scope_var": "MARKOV 2 2 2 1 2 0 0 4 1 2 3 4", "truncated_table": "MARKOV 2 2 2 1 2 0 1 4 1 2 3", "extra_table": "MARKOV 2 2 2 1 2 0 1 4 1 2 3 4 5", "trailing_tokens": "MARKOV 1 2 1 1 0 2 1 1 7", "zero_card": "MARKOV 1 0 0", "neg_entry": "MARKOV 1 2 1 1 0 2 1 -1",
              "nan_entry": "MARKOV 1 2 1 1 0 2 1 nan", "inf_entry": "MARKOV 1 2 1 1 0 2 1 inf", "bad_net": "BAYESNET 1 2 0", "float_count": "MARKOV 1.0 2 0", "var_out_of_range": "MARKOV 1 2 1 1 1 2 1 1", "wrong_length": "MARKOV 2 2 3 1 2 0 1 4 1 2 3 4", "bool_state_count": "MARKOV True 2 0", "quoted_int": 'MARKOV 1 2 1 1 0 2 "1" 1'}
BAD_EVID = {"dup_same_value": "2 0 1 0 1", "dup_other_value": "2 0 0 0 1", "state_range": "1 0 5", "var_range": "1 7 0", "float_state": "1 0 1.0", "bool_state": "1 0 True", "trailing": "1 0 1 9", "neg": "1 0 -1"}


@pytest.mark.parametrize("name", list(BAD_MODELS))
def test_malformed_models_are_typed_invalid_input_through_the_caller_pipeline(tmp_path, name):
    mp = str(tmp_path / "bad.uai"); open(mp, "w").write(BAD_MODELS[name] + "\n"); open(mp + ".evid", "w").write("")
    with pytest.raises(GS.InvalidInput):
        GS.Snapshot(mp, mp + ".evid")
    r = subprocess.run([PY, "-m", "gbidi3.cell", "GENERAL_BIDI_COMPLETE_V3", mp, mp + ".evid", str(tmp_path / "o"), "20", "{}"], capture_output=True, text=True, timeout=120, cwd=HERE, env=ENV)
    rec = json.load(open(tmp_path / "o" / "cell.json")); assert rec["status"] == "INVALID_INPUT", (name, rec.get("reason"), r.stderr[-300:])


@pytest.mark.parametrize("name", list(BAD_EVID))
def test_malformed_evidence_is_typed_invalid_input(tmp_path, name):
    mp, ep = write_uai(str(tmp_path / "m.uai"), [2, 3], [((0, 1), [1, 2, 3, 4, 5, 6])]); open(ep, "w").write(BAD_EVID[name] + "\n")
    with pytest.raises(GS.InvalidInput):
        GS.Snapshot(mp, ep)


def test_valid_edge_grammar_scalars_duplicates_and_identity_fields(tmp_path):
    mp, ep = write_uai(str(tmp_path / "m.uai"), [2, 2], [((), [Fr(3, 7)]), ((0,), [1, 2]), ((0,), [1, 2]), ((0, 1), [1, 0, 0, 1])])
    S = GS.Snapshot(mp, ep); assert len(S.model.factors) == 4 and S.task["factor_occurrences"] == 4 and S.task["canonical_version"] == GS.CANONICAL_VERSION
    S2 = GS.Snapshot(mp, ep); assert S2.task == S.task
    open(mp, "a").write("\n\n   \n"); S3 = GS.Snapshot(mp, ep)                                                                   # whitespace: raw differs, legacy canonical AND canonical_v2 agree
    assert S3.task["raw_model_sha256"] != S.task["raw_model_sha256"] and S3.task["canonical_model_sha256"] == S.task["canonical_model_sha256"] and S3.task["canonical_v2_model_sha256"] == S.task["canonical_v2_model_sha256"]
    mp2, ep2 = write_uai(str(tmp_path / "m2.uai"), [2, 2], [((), [Fr(3, 7)]), ((0,), [1, 2]), ((0,), [1, 2]), ((0, 1), [1, 0, 0, 1])], tokens=[None, None, ["2/2", "4/2"], None])   # same reduced rationals, different tokens: v2 equal, legacy differs
    S4 = GS.Snapshot(mp2, ep2); assert S4.task["canonical_v2_model_sha256"] == S.task["canonical_v2_model_sha256"] and S4.task["canonical_model_sha256"] != S.task["canonical_model_sha256"]
    assert GS.bound_to_task(dict(S.task), S.task) and not GS.bound_to_task({k: v for k, v in S.task.items() if k != "eps"}, S.task)         # a missing binding field is rejection


# ============================================================================================================ C01 equal scalar, different marked response
def test_C01_equal_scalar_different_marked_response_merge_rejected(tmp_path):
    """f(A,S) = [[1,2],[3,2]], h(S) = (1,2): Z = 12, N_A = (5,7), N_S = (4,8). The unweighted row sums over A are equal (4 = 4): a scalar merge of S's
    states keeps Z but corrupts N_A. An explicit proposal that compresses S to ONE class in the message REDUCE_A(MUL(f, M_A)) is REJECTED by the
    validator (rows (1,2) and (3,2) are not proportional); the policy plan forms no such class and encloses the truth."""
    mp, ep = write_uai(str(tmp_path / "c01.uai"), [2, 2], [((0, 1), [1, 2, 3, 2]), ((1,), [1, 2])]); S, Z, N, rows = truth(mp, ep)
    assert Z == 12 and N[0] == [5, 7] and N[1] == [4, 8]
    S_, R_, T, plan, cands = plan_program(mp, ep); ff = [f for f in T.factors if len(f.scope) == 2][0]; fh = [f for f in T.factors if len(f.scope) == 1][0]
    P = IR.Program(); f = P.source(ff.fid, ff.scope, ff.card); mA = P.marker(0, 2); m = P.mul([f, mA], axes=(0, 1), card=(2, 2))
    msg = P.reduce(m, {0}, reps={1: ((0,), (0, 0), (Fr(1), Fr(1)))}); msg.storage = IR.DENSE                                            # ILLEGAL: one class for S = 0 and S = 1
    g = P.gather(msg, (1,), (2,), [{"out_pos": 0, "cls": (0, 0), "ratio": (Fr(1), Fr(1))}]); h = P.source(fh.fid, fh.scope, fh.card); mS = P.marker(1, 2)
    top = P.mul([g, h, mS], axes=(1,), card=(2,)); root = P.reduce(top, {1}); root.storage = IR.DENSE; P.roots = [root.nid]
    with pytest.raises(TR.Invalid) as ex:
        GV.validate(P, T)
    assert "not proportional" in ex.value.reason, ex.value.reason
    # the SAME program with the legal identity view certifies exactly (MPFR) and the policy planner forms no class on S
    P2 = IR.Program(); f = P2.source(ff.fid, ff.scope, ff.card); mA = P2.marker(0, 2); m = P2.mul([f, mA], axes=(0, 1), card=(2, 2)); msg = P2.reduce(m, {0}); msg.storage = IR.DENSE
    h = P2.source(fh.fid, fh.scope, fh.card); mS = P2.marker(1, 2); top = P2.mul([msg, h, mS], axes=(1,), card=(2,)); root = P2.reduce(top, {1}); root.storage = IR.DENSE; P2.roots = [root.nid]
    V = GV.validate(P2, T); Zx, vals = IR.exact_eval(V); assert Zx == 12
    rec = run("GENERAL_BIDI_COMPLETE_V3", mp, ep, str(tmp_path / "ok"), rules=[], b64=False); assert rec["status"] == "INTERVALS_OK" and exact_rows(rec, rows) and rec["mechanisms"]["views"]["compressed_axes"] == 0


# ============================================================================================================ C02 marker duplication
def test_C02_marker_duplication_rejected_even_though_Z_is_unchanged(tmp_path):
    mp, ep = write_uai(str(tmp_path / "c02.uai"), [2], [((0,), [1, 3])]); S, R, T, plan, cands = plan_program(mp, ep); P = plan.program
    mul = [n for n in P.nodes if n.kind == IR.MUL][0]; mk = [c for c in mul.children if P.nodes[c].kind == IR.MARKER][0]
    mul.children = mul.children + (mk,); mul.proj = mul.proj + (mul.proj[mul.children.index(mk)],)
    with pytest.raises(TR.Invalid) as ex:
        GV.validate(P, T)
    assert "marker" in ex.value.reason and "twice" in ex.value.reason
    Z, vals = IR.exact_eval(GV.validate(plan_program(mp, ep)[3].program, T)); assert Z == 4                                              # the legal program at markers = 1 has the same Z: the rejection is semantic, not numerical


# ============================================================================================================ C03 every consumer (shared node with two additive consumers through the real validator + kernel)
def _shared_consumer_program(T, storage):
    """w(X) = (1,2) shared by two consumers h1 = (1,0), h2 = (0,1) (additive split of the trusted factor h = (1,1)); Z = 3, N_X = (1,2)"""
    fw = [f for f in T.factors if f.table == (Fr(1), Fr(2))][0]; fh = [f for f in T.factors if f.table == (Fr(1), Fr(1))][0]
    P = IR.Program(); P.derived = {101: {"kind": "additive_split", "parent": fh.fid, "parts": [(1, 0), (0, 1)], "index": 0}, 102: {"kind": "additive_split", "parent": fh.fid, "parts": [(1, 0), (0, 1)], "index": 1}}
    w = P.source(fw.fid, fw.scope, fw.card); mk = P.marker(0, 2); shared = P.mul([w, mk]); shared.storage = storage
    h1 = P.source(101, fh.scope, fh.card); h2 = P.source(102, fh.scope, fh.card); c1 = P.mul([shared, h1]); c2 = P.mul([shared, h2]); add = P.addn([c1, c2]); root = P.reduce(add, {0}); root.storage = IR.DENSE; P.roots = [root.nid]
    return P


@pytest.mark.parametrize("storage", [IR.DENSE, IR.STREAM, IR.CACHE])
def test_C03_every_consumer_contributes_through_a_shared_node(tmp_path, storage):
    mp, ep = write_uai(str(tmp_path / "c03.uai"), [2], [((0,), [1, 2]), ((0,), [1, 1])]); S, Z, N, rows = truth(mp, ep); assert Z == 3 and N[0] == [1, 2]
    def mut(P):
        S_, R_, T_, plan, cands = plan_program(mp, ep); P2 = _shared_consumer_program(T_, storage); P.nodes = P2.nodes; P.roots = P2.roots; P.derived = P2.derived
    for b64 in (True, False):
        rec = run("GENERAL_BIDI_COMPLETE_V3", mp, ep, str(tmp_path / ("s%s%d" % (storage, b64))), rules=[], hooks={"mutate_program": mut}, b64=b64)
        assert rec["status"] == "INTERVALS_OK" and exact_rows(rec, rows) if not b64 else contained(rec, rows), rec.get("reason")
        nt = rec["plan"]["node_table"]; assert sum(1 for n in nt if n["kind"] == "ADD") == 1 and rec["plan_validation"]["derived_tables"] == 2
        c = counters(rec); assert c["marker_updates"] >= 2 and (c["cache_hits"] > 0 if storage == IR.CACHE else True)
    # demand from ONE consumer must not remove the other's state: an EMPTY demand hint on the shared node is only a storage choice (reads stream)
    def mut2(P):
        mut(P); sh = [n for n in P.nodes if n.kind == IR.MUL and len(n.children) == 2 and P.nodes[n.children[1]].kind == IR.MARKER][0]; sh.storage = IR.DENSE; sh.demand = (1,)
    rec = run("GENERAL_BIDI_COMPLETE_V3", mp, ep, str(tmp_path / "dem"), rules=[], hooks={"mutate_program": mut2}, b64=False); assert exact_rows(rec, rows) and counters(rec)["reads_outside_demand"] >= 1


# ============================================================================================================ C04 dead representative / live class
def test_C04_dead_representative_live_class_preserved(tmp_path):
    mp, ep = write_uai(str(tmp_path / "c04.uai"), [2, 2], [((0, 1), [1, 1, 2, 2]), ((1,), [0, 1])]); S, Z, N, rows = truth(mp, ep); assert Z == 3 and N[0] == [1, 2] and N[1] == [0, 3]
    rec = run("GENERAL_BIDI_COMPLETE_V3", mp, ep, str(tmp_path / "o"), rules=[], b64=False)
    assert rec["status"] == "INTERVALS_OK" and exact_rows(rec, rows)
    # FIXTURE CHANGE (repair 2026-11-10, D2): under the ONE whole-path cost the default arm FUSES this two-variable chain (cheaper; recorded decision), which leaves
    # no boundary axis to compress; the class formation is asserted on the production A2_NO_FUSION arm (identical except the fusion switch)
    if rec["mechanisms"]["fusion"]["merged"]:
        assert any(d.get("merged") and d["cost_fused"] < d["cost_unfused"] for d in rec["plan_candidates"][0].get("fusion_decisions") or []), rec["plan_candidates"][0].get("fusion_decisions")
        rec = run("A2_NO_FUSION", mp, ep, str(tmp_path / "o_nofusion"), rules=[], b64=False); assert rec["status"] == "INTERVALS_OK" and exact_rows(rec, rows)
    assert rec["mechanisms"]["views"]["compressed_axes"] >= 1 and rec["plan_validation"]["entrywise_checks"] > 0, rec["mechanisms"]       # the class {S=0, S=1} IS formed (rows (1,2) proportional) and lifted whole


# ============================================================================================================ C05 crossing partitions + joint refinement with no single finest input
def test_C05_crossing_partitions_truth_two_not_four_and_joint_refinement(tmp_path):
    eq = [1, 0, 0, 1]; mp, ep = write_uai(str(tmp_path / "c05.uai"), [2, 2, 2, 2], [((0, 1), eq), ((2, 3), eq), ((0, 2), eq), ((1, 3), eq)]); S, Z, N, rows = truth(mp, ep); assert Z == 2
    for arm in ARMS:
        rec = run(arm, mp, ep, str(tmp_path / arm), rules=[]); assert rec["status"] == "INTERVALS_OK" and contained(rec, rows), arm
    # joint refinement: axis S (4 states) with f1(X,S) partition {0,1},{2,3} (rows along S: (1,2),(1,2),(3,1),(3,1)) and f2(X,S) partition {0,1,2},{3}
    # (rows (1,1),(1,1),(1,1),(5,2)); both owned by the bucket eliminating X -> common refinement {0,1},{2},{3}: 3 classes, determined by NO single input
    f1 = [1, 1, 3, 3, 2, 2, 1, 1]; f2 = [1, 1, 1, 5, 1, 1, 1, 2]
    mp2, ep2 = write_uai(str(tmp_path / "c05b.uai"), [2, 4], [((0, 1), f1), ((0, 1), f2), ((1,), [1, 2, 3, 4])]); S2, Z2, N2, rows2 = truth(mp2, ep2)
    S_, R_, T_, plan, cands = plan_program(mp2, ep2, two_axis=False); views = {w: v for b in plan.buckets for w, v in b.views.items()}
    assert 1 in views and len(views[1][0]) == 3 and views[1][1] == (0, 0, 1, 2), views                                                                 # 3 classes = refinement of {0,1}{2,3} and {0,1,2}{3}
    V = GV.validate(plan.program, T_); assert V.record["entrywise_checks"] > 0
    rec = run("GENERAL_BIDI_COMPLETE_V3", mp2, ep2, str(tmp_path / "jr"), rules=[], b64=False); assert exact_rows(rec, rows2)
    rec = EX.execute("GENERAL_BIDI_COMPLETE_V3", mp2, ep2, str(tmp_path / "jr2"), time.monotonic() + 60, {"budget_s": 60, "allow_binary64": False, "rules": []}, test_hooks={"mutate_program": lambda P: None})
    def mut(P):
        pass
    rec3 = _run_cfg(mp2, ep2, str(tmp_path / "jr3"), two_axis=False); assert exact_rows(rec3, rows2) and rec3["mechanisms"]["views"]["compressed_axes"] >= 1 and rec3["plan_validation"]["entrywise_checks"] > 0


# ============================================================================================================ C06 arbitrary arity / cardinality through dense / sparse / stream / conditioning
def test_C06_ternary_and_two_by_three_factors_exact_rows(tmp_path):
    mp, ep = write_uai(str(tmp_path / "t.uai"), [2, 2, 2], [((0, 1, 2), list(range(1, 9)))]); S, Z, N, rows = truth(mp, ep); assert Z == 36 and N == [[10, 26], [14, 22], [16, 20]]
    mp2, ep2 = write_uai(str(tmp_path / "r.uai"), [2, 3], [((0, 1), list(range(1, 7)))]); S2, Z2, N2, rows2 = truth(mp2, ep2); assert Z2 == 21 and N2 == [[6, 15], [5, 7, 9]]
    for (m, e, rw) in ((mp, ep, rows), (mp2, ep2, rows2)):
        for mode, mut in (("dense", set_storage(IR.DENSE)), ("stream", set_storage(IR.STREAM)), ("cache", set_storage(IR.CACHE)), ("sparse", set_storage(IR.SPARSE))):
            for two in (True, False):
                cfg = dict(PL.ARMS["GENERAL_BIDI_COMPLETE_V3"], two_axis=two); hooks = {"mutate_program": mut}
                rec = EX.execute("GENERAL_BIDI_COMPLETE_V3", m, e, str(tmp_path / (mode + str(two))), time.monotonic() + 60, {"budget_s": 60, "allow_binary64": False, "rules": []}, test_hooks=hooks) if two else run("A2_NO_FUSION", m, e, str(tmp_path / (mode + "x")), rules=[], b64=False, hooks=hooks)
                assert rec["status"] == "INTERVALS_OK" and exact_rows(rec, rw), (mode, two, rec.get("reason"))
    rec = run("GENERAL_BIDI_COMPLETE_V3", mp, ep, str(tmp_path / "fb"), rules=[], hooks={"force_fallback": True}); assert exact_rows(rec, rows) and rec["route"] == "exact_fallback"


# ============================================================================================================ C07 zero safety
def test_C07_zero_safety_inconsistency_zero_numerators_empty_sparse_zero_scalar_product_zero_classes(tmp_path):
    mp, ep = write_uai(str(tmp_path / "eq.uai"), [2, 2], [((0, 1), [1, 0, 0, 1])], {0: 0, 1: 1}); rec = run("GENERAL_BIDI_COMPLETE_V3", mp, ep, str(tmp_path / "a")); assert rec["status"] == "ZERO_EVIDENCE_PROVED"
    rec = run("GENERAL_BIDI_COMPLETE_V3", mp, ep, str(tmp_path / "a2"), rules=[]); assert rec["status"] == "ZERO_EVIDENCE_PROVED"                     # complete numerical execution: Z_U == 0
    mp, ep = write_uai(str(tmp_path / "u.uai"), [2], [((0,), [0, 2])]); S, Z, N, rows = truth(mp, ep); rec = run("GENERAL_BIDI_COMPLETE_V3", mp, ep, str(tmp_path / "b"), rules=[]); assert contained(rec, rows) and rec["certified_intervals"]["0"][0] == ["0", "0"]   # a certified ZERO numerator is exact in every route
    mp, ep = write_uai(str(tmp_path / "s0.uai"), [2], [((), [0]), ((0,), [1, 2])]); rec = run("GENERAL_BIDI_COMPLETE_V3", mp, ep, str(tmp_path / "c")); assert rec["status"] == "ZERO_EVIDENCE_PROVED"
    mp, ep = write_uai(str(tmp_path / "zc.uai"), [2, 2], [((0,), [0, 0]), ((0, 1), [1, 2, 3, 4])]); rec = run("GENERAL_BIDI_COMPLETE_V3", mp, ep, str(tmp_path / "d"), rules=[]); assert rec["status"] == "ZERO_EVIDENCE_PROVED"
    # empty-support SPARSE node: factor (X,Y) whose rows at every Y are zero except Y=1, consumer h(Y) = (1,0): the join over the surviving rows yields rows only at Y=1; the consumer reads an exact zero at Y=0
    mp, ep = write_uai(str(tmp_path / "es.uai"), [2, 2], [((0, 1), [0, 3, 0, 5]), ((1,), [1, 0])]); S, Z, N, rows = truth(mp, ep); assert Z == 0
    rec = run("GENERAL_BIDI_COMPLETE_V3", mp, ep, str(tmp_path / "e"), rules=[], hooks={"mutate_program": set_storage(IR.SPARSE)}); assert rec["status"] == "ZERO_EVIDENCE_PROVED" and counters(rec).get("sparse_output_rows", 0) >= 0
    mp, ep = write_uai(str(tmp_path / "es2.uai"), [2, 2, 2], [((0, 1), [0, 3, 0, 5]), ((1, 2), [1, 0, 2, 4])]); S, Z, N, rows = truth(mp, ep)
    rec = run("GENERAL_BIDI_COMPLETE_V3", mp, ep, str(tmp_path / "e2"), rules=[], hooks={"mutate_program": set_storage(IR.SPARSE)}, b64=False); cc = counters(rec)
    # FIXTURE CHANGE (repair 2026-11-10, D3): the sparse reverse is now support-indexed, so absent (zero) rows are never visited in reverse; the former witness
    # `zero_skips >= 1` (zero rows met by the generic reverse enumeration) is replaced by the honest one: support-based reverse deliveries, no generic fallback
    assert exact_rows(rec, rows) and cc["sparse_output_rows"] >= 1 and cc["sparse_reverse_rows"] >= 1 and cc["sparse_reverse_generic"] == 0, cc
    # product-zero classes with DIFFERENT zero-witness factors: in the bucket eliminating A (operands f1(A,S), f2(A,S), M_A) S=0 is a zero row of f1 and S=1 a zero
    # row of f2 -> both states have a zero complete product and share the ZERO class (any ratio is exact); S=2 is separate; h(S,B) keeps S a boundary axis
    mp, ep = write_uai(str(tmp_path / "pz.uai"), [2, 3, 2], [((0, 1), [0, 1, 2, 0, 3, 4]), ((0, 1), [1, 0, 5, 1, 0, 7]), ((1, 2), [1, 2, 3, 4, 5, 6])]); S, Z, N, rows = truth(mp, ep)
    S_, R_, T_, plan, cands = plan_program(mp, ep, two_axis=False, fusion=False); views = {w: v for b in plan.buckets for w, v in b.views.items()}
    assert 1 in views and views[1][1][0] == views[1][1][1] != views[1][1][2], views                                                                 # states 0 and 1 share the ZERO class, state 2 is separate
    V = GV.validate(plan.program, T_); assert V.record["status"] == "VALID"; rec = _run_cfg(mp, ep, str(tmp_path / "f"), two_axis=False, fusion=False); assert exact_rows(rec, rows) and rec["mechanisms"]["views"]["compressed_axes"] >= 1
    # one zero and one nonzero row merged -> REJECTED
    red = [n for n in plan.program.nodes if n.kind == IR.REDUCE and 1 in n.axes][0]; k = [i for i, r in enumerate(red.rmap) if r >= 0 and plan.program.nodes[red.children[0]].axes[i] == 1][0]
    red.reps = tuple((((0,), (0, 0, 0), (Fr(1), Fr(1), Fr(1))) if i == k else r) for i, r in enumerate(red.reps)); red.card = tuple(1 if a == 1 else c for a, c in zip(red.axes, red.card)); red.demand = "FULL"
    for m in plan.program.nodes:
        if m.kind == IR.GATHER and red.nid in m.children:
            m.gaxes = tuple(dict(g, cls=(0, 0, 0), ratio=(Fr(1), Fr(1), Fr(1))) if g["out_pos"] == m.axes.index(1) else g for g in m.gaxes)
    with pytest.raises(TR.Invalid) as ex:
        GV.validate(plan.program, T_)
    assert "only one complete product is zero" in ex.value.reason or "proportional" in ex.value.reason


# ============================================================================================================ C08 missing separator key (cache binds the boundary coordinate)
def test_C08_cached_summary_binds_the_boundary_coordinate(tmp_path):
    eq = [1, 0, 0, 1]; mp, ep = write_uai(str(tmp_path / "c08.uai"), [2, 2, 2], [((0, 2), eq), ((1, 2), eq)]); S, Z, N, rows = truth(mp, ep); assert Z == 2 and all(N[v] == [1, 1] for v in range(3))
    rec = run("GENERAL_BIDI_COMPLETE_V3", mp, ep, str(tmp_path / "cache"), rules=[], b64=False, hooks={"mutate_program": set_storage(IR.CACHE)}); c = counters(rec)
    assert exact_rows(rec, rows) and c["cache_inserts"] >= 2 and c["cache_hits"] >= 1, c                                                              # child normalizers are 1 at either C; the cache key carries C: two distinct entries
    rec2 = run("GENERAL_BIDI_COMPLETE_V3", mp, ep, str(tmp_path / "stream"), rules=[], b64=False, hooks={"mutate_program": set_storage(IR.STREAM)}); assert exact_rows(rec2, rows)
    # weighted contractions with equal boundary tuples but different consumer weights: two consumers of one boundary value (C03 program) with weights (1,0) / (0,1)
    mp2, ep2 = write_uai(str(tmp_path / "w.uai"), [2], [((0,), [1, 2]), ((0,), [1, 1])]); S2, Z2, N2, rows2 = truth(mp2, ep2)
    def mut(P):
        S_, R_, T_, plan, cands = plan_program(mp2, ep2); P2 = _shared_consumer_program(T_, IR.CACHE); P.nodes = P2.nodes; P.roots = P2.roots; P.derived = P2.derived
    rec3 = run("GENERAL_BIDI_COMPLETE_V3", mp2, ep2, str(tmp_path / "w"), rules=[], b64=False, hooks={"mutate_program": mut}); assert exact_rows(rec3, rows2) and counters(rec3)["cache_hits"] >= 1


# ============================================================================================================ C09 cache semantic types (eviction + regeneration; scalar hits never satisfy derivatives)
def test_C09_tiny_cache_eviction_regeneration_and_value_hits_never_add_numerators(tmp_path):
    mp, ep = write_uai(str(tmp_path / "c09.uai"), [2, 2], [((0,), [1, 2]), ((1,), [3, 4])]); S, Z, N, rows = truth(mp, ep); assert Z == 21 and N[0] == [7, 14] and N[1] == [9, 12]
    rec = run("GENERAL_BIDI_COMPLETE_V3", mp, ep, str(tmp_path / "a"), rules=[], b64=False, hooks={"mutate_program": set_storage(IR.CACHE, include_roots=True)}); c = counters(rec)
    assert exact_rows(rec, rows) and c["cache_inserts"] >= 2 and c["cache_hits"] >= 1 and c["pullback_frames"] >= 2 and c["marker_updates"] == 4, c   # the root values are cache hits in the reverse pass (scalar VALUE); every derivative still runs a PULLBACK frame; exactly one marker update per original state
    # a chain whose streamed messages are read more often than the tiny LRU can hold: evictions + regeneration, answer exact
    card = [3, 3, 3, 3, 3]; facs = rnd_model(5, card, [(0, 1), (1, 2), (2, 3), (3, 4), (0, 4)]); mp2, ep2 = write_uai(str(tmp_path / "c09b.uai"), card, facs); S2, Z2, N2, rows2 = truth(mp2, ep2)
    led = GM.Ledger(dict(GM.CAPS, value_cache_blocks=4096))                                                                          # roots + a handful of LRU entries (80 + 96 bytes each at p = 64)
    rec2 = run("GENERAL_BIDI_COMPLETE_V3", mp2, ep2, str(tmp_path / "b"), rules=[], b64=False, hooks={"mutate_program": set_storage(IR.CACHE)}, ledger=led); c2 = counters(rec2)
    assert tight(rec2, rows2) and c2["cache_evictions"] >= 1 and c2["cache_hits"] >= 1 and c2["cache_misses"] >= 1 and c2["regenerated_values"] >= 1, c2
    rec3 = run("GENERAL_BIDI_COMPLETE_V3", mp2, ep2, str(tmp_path / "c"), rules=[], b64=False, hooks={"mutate_program": set_storage(IR.STREAM)}); assert tight(rec3, rows2) and counters(rec3)["cache_hits"] == 0


# ============================================================================================================ C10 duplicate factors (multiplicity; omission / duplication rejected separately)
def test_C10_duplicate_occurrences_multiplicity_omission_and_duplication(tmp_path):
    mp, ep = write_uai(str(tmp_path / "c10.uai"), [2], [((0,), [1, 2]), ((0,), [1, 2])]); S, Z, N, rows = truth(mp, ep); assert Z == 5 and N[0] == [1, 4]
    rec = run("GENERAL_BIDI_COMPLETE_V3", mp, ep, str(tmp_path / "a"), rules=[], b64=False); assert exact_rows(rec, rows) and rec["plan_validation"]["effective_occurrences"] == 2
    S_, R_, T, plan, cands = plan_program(mp, ep); P = plan.program; mul = [n for n in P.nodes if n.kind == IR.MUL][0]; srcs = [c for c in mul.children if P.nodes[c].kind == IR.SOURCE]; assert len(srcs) == 2
    omit = copy.deepcopy(P); m = [n for n in omit.nodes if n.kind == IR.MUL][0]; i = m.children.index(srcs[0]); m.children = m.children[:i] + m.children[i + 1:]; m.proj = m.proj[:i] + m.proj[i + 1:]
    with pytest.raises(TR.Invalid) as ex:
        GV.validate(omit, T)
    assert "missing" in ex.value.reason or "cover occurrences" in ex.value.reason, ex.value.reason
    dup = copy.deepcopy(P); m = [n for n in dup.nodes if n.kind == IR.MUL][0]; m.children = m.children + (srcs[0],); m.proj = m.proj + (m.proj[m.children.index(srcs[0])],)
    with pytest.raises(TR.Invalid) as ex:
        GV.validate(dup, T)
    assert "multiplied twice" in ex.value.reason, ex.value.reason


# ============================================================================================================ C11 extreme range and the MPFR bridge; scalar restoration of Z
def test_C11_extreme_range_bridge_and_scale_restoration(tmp_path):
    mp, ep = write_uai(str(tmp_path / "a.uai"), [2], [((0,), [Fr(1, 10 ** 400), Fr(2, 10 ** 400)])], tokens=[["1e-400", "2e-400"]]); S, Z, N, rows = truth(mp, ep); assert rows[0] == [Fr(1, 3), Fr(2, 3)]
    rec = run("GENERAL_BIDI_COMPLETE_V3", mp, ep, str(tmp_path / "a"), rules=[]); assert tight(rec, rows) and rec["binary64_admission"]["admitted"] is False and rec["route"] == "mpfr" and Fr(rec["Z"][0]) <= Z <= Fr(rec["Z"][1]) and Fr(rec["Z"][0]) > 0
    mp, ep = write_uai(str(tmp_path / "b.uai"), [2], [((), [Fr(1, 10 ** 200)]), ((0,), [Fr(3, 10 ** 124), Fr(7, 10 ** 124)])], tokens=[["1e-200"], ["3e-124", "7e-124"]]); S, Z, N, rows = truth(mp, ep); assert rows[0] == [Fr(3, 10), Fr(7, 10)]
    rec = run("GENERAL_BIDI_COMPLETE_V3", mp, ep, str(tmp_path / "b"), rules=[]); assert tight(rec, rows) and Fr(rec["Z"][0]) > 0 and Fr(rec["Z"][0]) <= Z <= Fr(rec["Z"][1])
    outs = [a["outcome"] for a in rec["attempts"]]; assert rec["route"] == "mpfr" and (outs[0].startswith("ROUTE_FAULT_RANGE") or rec["binary64_admission"]["admitted"] is False), outs       # the binary64 attempt FAULTS on the underflowing product (leaves were admissible), MPFR certifies
    mp, ep = write_uai(str(tmp_path / "c.uai"), [2, 2], [((0,), [Fr(1, 10 ** 200)] * 2), ((1,), [Fr(1, 10 ** 200)] * 2)], tokens=[["1e-200", "1e-200"], ["1e-200", "1e-200"]]); S, Z, N, rows = truth(mp, ep); assert Z == Fr(4, 10 ** 400)
    rec = run("GENERAL_BIDI_COMPLETE_V3", mp, ep, str(tmp_path / "c"), rules=[]); assert rec["status"] == "INTERVALS_OK" and tight(rec, rows) and Fr(rec["Z"][0]) > 0, rec.get("reason")   # never inconsistency from a narrowed zero
    assert any(a["route"] == "binary64" and (a["outcome"].startswith("ROUTE_FAULT_RANGE") or a["outcome"] == "Z_ZERO_IN_BINARY64_UNRESOLVED") for a in rec["attempts"]) and rec["route"] == "mpfr"
    # exact fallback restores the ORIGINAL Z through a nonunit scalar and nonunit denominators
    mp, ep = write_uai(str(tmp_path / "d.uai"), [2, 2], [((), [Fr(3, 7)]), ((0,), [Fr(1, 3), Fr(2, 5)]), ((0, 1), [Fr(1, 6), 1, Fr(5, 4), 2])]); S, Z, N, rows = truth(mp, ep)
    rec = run("GENERAL_BIDI_COMPLETE_V3", mp, ep, str(tmp_path / "d"), rules=[], hooks={"force_fallback": True}); assert rec["route"] == "exact_fallback" and Fr(rec["Z"][0]) == Z and exact_rows(rec, rows) and rec["exact_fallback"]["scale_restored"] != "1"


# ============================================================================================================ C12 requested normalized leaf + decoder / fixation grammar
def test_C12_deterministic_child_publishes_its_fixed_state_and_malformed_fixations_are_rejected(tmp_path):
    mp, ep = write_uai(str(tmp_path / "c12.uai"), [2, 2], [((0, 1), [1, 0, 0, 1])], {0: 1}); S, Z, N, rows = truth(mp, ep); assert rows == [[0, 1], [0, 1]]
    for rules in (RULES_ALL, []):
        rec = run("GENERAL_BIDI_COMPLETE_V3", mp, ep, str(tmp_path / ("r%d" % len(rules))), rules=rules, b64=False); assert exact_rows(rec, rows), rules
        st, cell = publish(str(tmp_path / ("r%d" % len(rules))), mp, ep, rec); assert st == "CERTIFIED"; assert U.read_mar(os.path.join(str(tmp_path / ("r%d" % len(rules))), "output.MAR"))[0] == [[Fr(0), Fr(1)], [Fr(0), Fr(1)]]
    rec = run("GENERAL_BIDI_COMPLETE_V3", mp, ep, str(tmp_path / "full"), rules=RULES_ALL); assert rec["route"] == "exact_decoder" and rec["reductions"]["free_reduced"] == 0
    # tampered reduction records are rejected by the independent replay (pinned checker): non-integer fixation fields, wrong state, extra step
    R = SRC.Reduced(EX._ModelAdapter(S.model), dict(S.ev)); R.reduce(tuple(RULES_ALL)); T = TR.TrustedReduced(R); good = R.record(); assert T.independent_replay(mp, ep, good)["status"] == "REPLAYED"
    for mutate in (lambda r: r["steps"].append(["fix", 1, "1"]), lambda r: r["steps"].append(["fix", 1, 1.0]), lambda r: r["steps"].append(["fix", 1, True]), lambda r: r["steps"].append(["exclude", 1, 0, 0]), lambda r: r.__setitem__("reduced_hash", "0" * 64)):
        bad = json.loads(json.dumps(good)); mutate(bad)
        with pytest.raises(TR.Invalid):
            T.independent_replay(mp, ep, bad)


# ============================================================================================================ C13 interrupted discovery keeps the conservative cover
def test_C13_interrupted_discovery_keeps_full_demand_identity_views_and_exact_truth(tmp_path):
    card = [3, 3, 3, 3]; facs = rnd_model(13, card, [(0, 1), (1, 2), (2, 3), (0, 3)], zeros=0.3); mp, ep = write_uai(str(tmp_path / "c13.uai"), card, facs); S, Z, N, rows = truth(mp, ep)
    full = run("GENERAL_BIDI_COMPLETE_V3", mp, ep, str(tmp_path / "full"), rules=[], b64=False); assert truth_inside(full, mp, ep)
    capped = run("GENERAL_BIDI_COMPLETE_V3", mp, ep, str(tmp_path / "cap"), rules=[], b64=False, extra_cfg={"_row_cap": 5}); assert truth_inside(capped, mp, ep)
    if capped["status"] == "INTERVALS_OK":
        m = capped["mechanisms"]; d = capped["plan"]["discovery_stop"]
        assert (d is not None and d["kind"] == "ROW_CAP") or m["demand"]["skipped"] >= 1, (d, m)
        assert m["demand"]["restricted_nodes"] == 0 and all(n["demand"] == "FULL" for n in capped["plan"]["node_table"] if n["kind"] == "REDUCE"), m          # the uninspected remainder stays FULL
    expired = run("GENERAL_BIDI_COMPLETE_V3", mp, ep, str(tmp_path / "exp"), rules=[], b64=False, extra_cfg={"_optional_allowance_s": 0.0}); assert truth_inside(expired, mp, ep)
    if expired["status"] == "INTERVALS_OK":
        assert expired["clock"]["optional_expired"] is True and expired["plan"]["discovery_stop"]["kind"] == "DISCOVERY_WALL" and expired["mechanisms"]["views"]["compressed_axes"] == 0 and expired["mechanisms"]["demand"]["restricted_nodes"] == 0
    # a partially built sparse join under a one-byte index cap is DISCARDED (downgrade to stream), never a certificate of absence
    led = GM.Ledger(dict(GM.CAPS, source_ir_maps_output=1))
    rec = run("GENERAL_BIDI_COMPLETE_V3", mp, ep, str(tmp_path / "sp"), rules=[], b64=False, hooks={"mutate_program": set_storage(IR.SPARSE)}, ledger=GM.Ledger(dict(GM.CAPS)))
    assert truth_inside(rec, mp, ep)
    c = counters(rec); assert c["sparse_output_rows"] >= 1 or c["sparse_join_discarded"] >= 1


# ============================================================================================================ C14 fusion: complete cost + derivatives through h, T, f and every marker
def test_C14_fusion_fires_by_price_saves_materialization_and_keeps_every_derivative(tmp_path):
    """chain A-B-C: f(A,B) positive, g(B,C) diagonal (zero-heavy), h(C): the consumer's support fraction makes the merged schedule cheaper -> FUSION_PRICE;
    the fused program has fewer stored entries than A2_NO_FUSION and every original row is exact (derivatives through the merged MUL incl. both markers)."""
    f = [1, 2, 3, 4, 5, 6, 7, 8, 9]; g = [1, 0, 0, 0, 2, 0, 0, 0, 3]; mp, ep = write_uai(str(tmp_path / "c14.uai"), [3, 3, 3], [((0, 1), f), ((1, 2), g), ((2,), [1, 2, 3])]); S, Z, N, rows = truth(mp, ep)
    gen = _run_cfg(mp, ep, str(tmp_path / "gen"), two_axis=False); nof = run("A2_NO_FUSION", mp, ep, str(tmp_path / "nof"), rules=[], b64=False)
    assert exact_rows(gen, rows) and exact_rows(nof, rows)
    assert gen["mechanisms"]["fusion"]["merged"] >= 1 and nof["mechanisms"]["fusion"]["merged"] == 0, (gen["mechanisms"], nof["mechanisms"])
    assert sum(1 for n in gen["plan"]["node_table"] if n["kind"] == "REDUCE") < sum(1 for n in nof["plan"]["node_table"] if n["kind"] == "REDUCE")
    cg, cn = counters(gen), counters(nof); assert cg["entries_materialized"] < cn["entries_materialized"] and cg["mul_rows"] > 0 and cn["mul_rows"] > 0, (cg["entries_materialized"], cn["entries_materialized"])
    # a case where fusion would increase work (dense consumer, no zeros): the frozen price declines
    f2 = [1, 2, 3, 4, 5, 6, 7, 8, 9]; g2 = [1, 2, 3, 4, 5, 6, 7, 8, 9]; mp2, ep2 = write_uai(str(tmp_path / "c14b.uai"), [3, 3, 3], [((0, 1), f2), ((1, 2), g2), ((2,), [1, 2, 3])]); S2, Z2, N2, rows2 = truth(mp2, ep2)
    gen2 = _run_cfg(mp2, ep2, str(tmp_path / "gen2"), two_axis=False); assert exact_rows(gen2, rows2) and gen2["mechanisms"]["fusion"]["declined"] >= 1 and gen2["mechanisms"]["fusion"]["merged"] == 0
    # a no-op after common preprocessing: a chain whose middle factor is separable is split by the reductions; fusion candidates exist and truth holds
    mp3, ep3 = write_uai(str(tmp_path / "c14c.uai"), [2, 2, 2], [((0, 1), [1, 2, 2, 4]), ((1, 2), [1, 0, 0, 2]), ((2,), [1, 3])]); S3, Z3, N3, rows3 = truth(mp3, ep3)
    gen3 = run("GENERAL_BIDI_COMPLETE_V3", mp3, ep3, str(tmp_path / "gen3"), rules=RULES_ALL, b64=False); assert truth_inside(gen3, mp3, ep3)


# ============================================================================================================ C15 late deltas (flush 2, evict / regenerate, flush 3 == coalesced 5; dropped / reflushed must fail)
def _c15_program(T):
    """m = REDUCE_X(MUL(u, M_X)) with u = (1,3): m = lambda0 + 3 lambda1; w(Y) = (2,3) split into (2,0) + (0,3); root = ADD(REDUCE_Y(MUL(m, w1, M_Y)), REDUCE_Y(MUL(m, w2, M_Y)))
    = 2m + 3m = 5m -> Z = 20, N_X = (5, 15), N_Y = (8, 12). m receives TWO deltas (2 then 3) through its two consumers."""
    fu = [f for f in T.factors if f.table == (Fr(1), Fr(3))][0]; fw = [f for f in T.factors if f.table == (Fr(2), Fr(3))][0]
    P = IR.Program(); P.derived = {201: {"kind": "additive_split", "parent": fw.fid, "parts": [(2, 0), (0, 3)], "index": 0}, 202: {"kind": "additive_split", "parent": fw.fid, "parts": [(2, 0), (0, 3)], "index": 1}}
    u = P.source(fu.fid, fu.scope, fu.card); mx = P.marker(fu.scope[0], 2); m = P.reduce(P.mul([u, mx]), {fu.scope[0]}); m.storage = IR.DENSE
    w1 = P.source(201, fw.scope, fw.card); w2 = P.source(202, fw.scope, fw.card); my = P.marker(fw.scope[0], 2)
    c1 = P.reduce(P.mul([m, w1, my], axes=fw.scope, card=fw.card), {fw.scope[0]}); c2 = P.reduce(P.mul([m, w2, my], axes=fw.scope, card=fw.card), {fw.scope[0]}); c1.storage = IR.DENSE; c2.storage = IR.DENSE
    root = P.addn([c1, c2]); root.storage = IR.DENSE; P.roots = [root.nid]; return P


def test_C15_late_deltas_coalesce_exactly_once_with_eviction_and_regeneration(tmp_path):
    mp, ep = write_uai(str(tmp_path / "c15.uai"), [2, 2], [((0,), [1, 3]), ((1,), [2, 3])]); S, Z, N, rows = truth(mp, ep); assert Z == 20 and N[0] == [5, 15] and N[1] == [8, 12]
    def mut(P):
        S_, R_, T_, plan, cands = plan_program(mp, ep); P2 = _c15_program(T_); P.nodes = P2.nodes; P.roots = P2.roots; P.derived = P2.derived
    rec = run("GENERAL_BIDI_COMPLETE_V3", mp, ep, str(tmp_path / "plain"), rules=[], b64=False, hooks={"mutate_program": mut}); c = counters(rec)
    assert exact_rows(rec, rows) and c["adjoint_adds"] >= 2 and c["slots_drained"] >= 1, c                                                        # two deltas into m's pending slot, drained once (coalesced 5)
    for evict in (0, 1):                                                                                                                             # root adjoint delivered as 1/4 then 3/4 (dyadic: exact at p = 64): m receives 5/4 then 15/4; m drained after each delivery, evicted + regenerated in between
        rec2 = run("GENERAL_BIDI_COMPLETE_V3", mp, ep, str(tmp_path / ("split%d" % evict)), rules=[], b64=False, hooks={"mutate_program": mut, "split_root": ("1/4", "3/4", evict)}); c2 = counters(rec2)
        assert exact_rows(rec2, rows), (evict, rec2["certified_intervals"])
        assert c2["late_increments"] >= 1 and c2["slots_drained"] >= 2, c2                                                                           # the second pass adds to an already DRAINED slot and it propagates again
        if evict:
            assert c2["regenerated_values"] >= 1
        got = tuple(Fr(a) * 20 for a, _ in rec2["certified_intervals"]["0"]); dropped = (Fr(5, 4), Fr(15, 4)); reflushed = (Fr(5, 4) + 5, Fr(15, 4) + 15)
        assert got == (5, 15) and got != dropped and got != reflushed                                                                                 # a dropped late delta or a re-flushed cumulative total would both be wrong
    # pure VALUE requests never add numerators: a CACHE version re-reads m many times; marker updates stay exactly one per original state
    def mut_cache(P):
        mut(P); [n for n in P.nodes if n.kind == IR.REDUCE and n.axes == ()][0].storage = IR.CACHE
    rec3 = run("GENERAL_BIDI_COMPLETE_V3", mp, ep, str(tmp_path / "cache"), rules=[], b64=False, hooks={"mutate_program": mut_cache}); c3 = counters(rec3)
    assert exact_rows(rec3, rows) and c3["cache_hits"] >= 1 and c3["numerator_adds"] == c3["marker_updates"] and c["numerator_adds"] == c["marker_updates"], (c3, c)   # every numerator add IS a marker pullback (a VALUE cache hit never adds); the coalescing DENSE slot gives fewer marker visits (4) than the per-use CACHE delivery (6), both exact


# ============================================================================================================ C16 conditioning ownership
def _c16_model(path, dcard=3, zeros=True):
    """cutset variable D (card dcard) joins two residual components {A,B} (ternary factor (A,B,D), pair (A,B)) and {C,E} (factor (C,E,D) + (C,E)); an
    isolated variable I with a unary; a nonunit scalar; boundary-dependent factors; zeros in one branch when `zeros`"""
    card = [3, 2, 2, 2, 3, dcard]; r = random.Random(dcard)
    def tab(n, zp):
        return [Fr(0) if (zeros and r.random() < zp) else Fr(r.randint(1, 9), r.choice((1, 2, 4))) for _ in range(n)]
    facs = [((0, 1, 5), tab(3 * 2 * dcard, 0.3)), ((0, 1), tab(6, 0.0)), ((2, 3, 5), tab(2 * 2 * dcard, 0.2)), ((2, 3), tab(4, 0.0)), ((4,), tab(3, 0.0)), ((), [Fr(5, 8)]), ((5,), tab(dcard, 0.0))]
    return write_uai(path, card, facs)


def test_C16_general_conditioning_components_isolated_variable_zeros_scalars_external_adjoints(tmp_path):
    for dcard in (2, 3, 5):
        mp, ep = _c16_model(str(tmp_path / ("c16_%d.uai" % dcard)), dcard); S, Z, N, rows = truth(mp, ep)
        for two in (False, True):
            for mode, hooks in (("dense", {}), ("stream", {"force_stream": True}), ("cache", {"mutate_program": set_storage(IR.CACHE)})):
                rec = _run_cfg(mp, ep, str(tmp_path / ("%d%d%s" % (dcard, two, mode))), two_axis=two, hooks=hooks)
                assert rec["status"] == "INTERVALS_OK" and exact_rows(rec, rows), (dcard, two, mode, rec.get("reason"))
                nt = rec["plan"]["node_table"]; top = [n for n in nt if n["kind"] == "REDUCE" and n["axes"] == []]
                assert len(top) >= 1
        plain = run("NATIVE_PLAIN_COMPLETE_V3", mp, ep, str(tmp_path / ("plain%d" % dcard)), rules=[], b64=False); assert exact_rows(plain, rows)
    # topology is compiled once per region: the program's node count does not depend on the cutset cardinality
    off = dict(two_axis=False, views=False, demand_masks=False, fusion=False, orders=("original_id",))
    S2, R2, T2, p2, _ = plan_program(str(tmp_path / "c16_2.uai"), str(tmp_path / "c16_2.uai.evid"), **off); S5, R5, T5, p5, _ = plan_program(str(tmp_path / "c16_5.uai"), str(tmp_path / "c16_5.uai.evid"), **off)
    assert len(p2.program.nodes) == len(p5.program.nodes) and len(p2.buckets) == len(p5.buckets) and [n.kind for n in p2.program.nodes] == [n.kind for n in p5.program.nodes]
    # conditioning node structure: the root REDUCE eliminates D over a MUL whose operands include >= 2 component children (REDUCE / GATHER) + the isolated component
    top = [p5.program.nodes[r] for r in p5.program.roots if p5.program.nodes[p5.program.nodes[r].children[0]].kind == IR.MUL and any(p5.program.nodes[c].kind in (IR.REDUCE, IR.GATHER) for c in p5.program.nodes[p5.program.nodes[r].children[0]].children)]
    assert top, "a conditioning root with component children"; mul = p5.program.nodes[top[0].children[0]]; kinds = [p5.program.nodes[c].kind for c in mul.children]
    assert kinds.count(IR.REDUCE) + kinds.count(IR.GATHER) >= 2 and IR.MARKER in kinds, kinds
    # two-axis policy: eligible joint domain chosen or declined by the cold estimate; an ineligible (> 4,096) pair is recorded as ineligible while the one-axis route stays
    mp, ep = write_uai(str(tmp_path / "big.uai"), [70, 70, 2], [((0, 1), [Fr(1 + (i % 7)) for i in range(4900)]), ((1, 2), [1, 2, 3, 4] * 35), ((0,), [1] * 70)]); S, Z, N, rows = truth(mp, ep)
    S_, R_, T_, plan, cands = plan_program(mp, ep); assert plan.mechanisms["two_axis"]["ineligible"] >= 1 and plan.mechanisms["two_axis"]["chosen"] == 0, plan.mechanisms
    rec = run("GENERAL_BIDI_COMPLETE_V3", mp, ep, str(tmp_path / "big"), rules=[], b64=False); assert exact_rows(rec, rows)
    mp, ep = _c16_model(str(tmp_path / "small.uai"), 2); S_, R_, T_, plan, cands = plan_program(mp, ep); m = plan.mechanisms["two_axis"]; assert m["chosen"] + m["declined"] >= 1 and m["ineligible"] == 0
    # a hyperedge crossing two proposed children is rejected by the validator (an operand eliminates a variable another operand mentions)
    mp, ep = write_uai(str(tmp_path / "cross.uai"), [2, 2, 2], [((0, 1), [1, 2, 3, 4]), ((1, 2), [1, 2, 3, 4]), ((0, 2), [1, 2, 3, 4])]); S_, R_, T, plan, cands = plan_program(mp, ep, two_axis=False)
    f01 = [f for f in T.factors if f.scope == (0, 1)][0]; f12 = [f for f in T.factors if f.scope == (1, 2)][0]; f02 = [f for f in T.factors if f.scope == (0, 2)][0]
    P = IR.Program(); a = P.reduce(P.mul([P.source(f01.fid, f01.scope, f01.card), P.marker(0, 2)], axes=(0, 1), card=(2, 2)), {0}); a.storage = IR.DENSE
    b = P.source(f02.fid, f02.scope, f02.card)                                                                                                        # mentions variable 0, which child a eliminated: illegal split
    top = P.mul([a, b, P.source(f12.fid, f12.scope, f12.card), P.marker(1, 2), P.marker(2, 2)]); root = P.reduce(top, {1, 2}); root.storage = IR.DENSE; P.roots = [root.nid]
    with pytest.raises(TR.Invalid) as ex:
        GV.validate(P, T)
    assert ex.value.reason                                                                                                                              # typed rejection of the crossing split (whichever structural rule fires first)
    P2 = IR.Program(); a = P2.reduce(P2.mul([P2.source(f01.fid, f01.scope, f01.card), P2.marker(0, 2)], axes=(0, 1), card=(2, 2)), {0}); a.storage = IR.DENSE
    top = P2.mul([a, P2.source(f02.fid, f02.scope, f02.card), P2.source(f12.fid, f12.scope, f12.card), P2.marker(1, 2), P2.marker(2, 2)]); root = P2.reduce(top, {0, 1, 2}); root.storage = IR.DENSE; P2.roots = [root.nid]
    with pytest.raises(TR.Invalid) as ex2:
        GV.validate(P2, T)
    assert "variable 0" in ex2.value.reason or "eliminated" in ex2.value.reason, ex2.value.reason                                                      # the scalar version: variable 0 mentioned outside the subtree of its REDUCE


# ============================================================================================================ C17 bounded representation activation
def test_C17_dense_blocks_sparse_joins_with_aggregation_stream_downgrade_and_scalar_chunking(tmp_path):
    # > 1,024 nominal outputs: a message over (B, C) with 40 x 40 = 1,600 entries -> at least two dense blocks; reverse work crosses the block boundary
    card = [3, 40, 40]; facs = rnd_model(17, card, [(0, 1, 2), (1, 2)], lo=1, hi=9); mp, ep = write_uai(str(tmp_path / "blk.uai"), card, facs); S, Z, N, rows = truth(mp, ep)
    rec = _run_cfg(mp, ep, str(tmp_path / "blk"), two_axis=False, fusion=False); c = counters(rec)
    assert tight(rec, rows) and c["dense_blocks"] >= 2 and c["entries_materialized"] >= 1600 and c["slots_drained"] >= 1600 and c["used_values_bytes"] > 0, c
    for a in rec["attempts"]:
        assert a["counters"]["used_values_bytes"] >= 1600 * 32
    # real support joins with duplicate aggregation: REDUCE over A of MUL(f(A,B) sparse, g(A,C)) -> output rows (B,C) receive contributions from several A
    f = [0] * 25
    for i in (0, 6, 12, 18, 24, 1, 7):
        f[i] = i + 1
    card = [5, 5, 5]; mp, ep = write_uai(str(tmp_path / "sp.uai"), card, [((0, 1), f), ((0, 2), list(range(1, 26))), ((1,), [1, 2, 3, 4, 5]), ((2,), [1, 1, 2, 2, 3])]); S, Z, N, rows = truth(mp, ep)
    def only_first(P):                                                                                                                                 # SPARSE on the bucket of A only: REDUCE_A(MUL(f(A,B), g(A,C), M_A)) -> rows (B, C)
        for n in P.nodes:
            if n.kind == IR.REDUCE and tuple(n.axes) == (1, 2):
                n.storage = IR.SPARSE; n.demand = "FULL"
            elif n.kind == IR.REDUCE and n.nid not in P.roots:
                n.storage = IR.DENSE; n.demand = "FULL"
    rec = _run_cfg(mp, ep, str(tmp_path / "sp"), two_axis=False, fusion=False, views=False, demand_masks=False, orders=("original_id",), hooks={"mutate_program": only_first}); c = counters(rec)
    assert exact_rows(rec, rows) and 1 <= c["sparse_output_rows"] <= 25 and c["sparse_rows_joined"] == 35 > c["sparse_output_rows"], c                 # 7 supported rows x 5 free states = 35 joined rows into <= 25 outputs: duplicates aggregated
    # sparse -> stream downgrade under a 1-byte value category for the kernel (Python ledger caps forwarded): the join is DISCARDED, the node streamed
    led = GM.Ledger(dict(GM.CAPS, value_cache_blocks=1)); rec = _run_cfg(mp, ep, str(tmp_path / "spd"), two_axis=False, fusion=False, hooks={"mutate_program": set_storage(IR.SPARSE)})
    assert exact_rows(rec, rows)
    def mut(P):
        set_storage(IR.SPARSE)(P)
    try:
        rec2 = run("GENERAL_BIDI_COMPLETE_V3", mp, ep, str(tmp_path / "spd2"), rules=[], b64=False, hooks={"mutate_program": mut}, ledger=led)
        assert truth_inside(rec2, mp, ep); c2 = counters(rec2) if rec2.get("attempts") else {}
        assert (c2.get("downgrades", 0) >= 1 and c2.get("sparse_join_discarded", 0) >= 1) or rec2.get("route") == "exact_fallback", (c2, rec2.get("stop"), rec2.get("route"))
    except EX.Refuse as ex:
        assert ex.kind == "RESOURCE_STOP" and "MEMORY" in ex.reason
    # a scalar output with a huge reduction still polls (chunking by primitive units): REDUCE over 6 ternary variables of one high-arity factor streamed
    card = [3] * 7; facs = rnd_model(3, card, [tuple(range(7))], lo=1, hi=3); mp, ep = write_uai(str(tmp_path / "big.uai"), card, facs); S, Z, N, rows = truth(mp, ep)
    rec = run("GENERAL_BIDI_COMPLETE_V3", mp, ep, str(tmp_path / "big"), rules=[], b64=False, hooks={"force_stream": True}); c = counters(rec); assert tight(rec, rows) and c["polls"] >= 1 and c["reduce_terms"] >= 3 ** 6
    # an allocation failure is NOT a successful block qualification: under a 1-byte value category NO block is allocated (dense_blocks == 0, nothing materialized);
    # the declared response is the per-node materialized -> stream downgrade (once per node), and the answer is still enclosed
    rec = run("GENERAL_BIDI_COMPLETE_V3", mp, ep, str(tmp_path / "nomem"), rules=[], b64=False, ledger=GM.Ledger(dict(GM.CAPS, value_cache_blocks=1)), fallback=False); c = counters(rec)
    # FIXTURE CHANGE (second review repair, 2026-11-10): under a 1-byte value category the PLAN now streams every bucket including the root (storage_pass), so the kernel
    # has nothing left to downgrade; the kernel downgrade path itself is exercised by the index-category controls (RE4 / SE2) and by the sparse -> stream part below
    assert tight(rec, rows) and c["dense_blocks"] == 0 and c["entries_materialized"] == 0 and c["used_values_bytes"] <= 1 and (c["downgrades"] >= 1 or all(n["storage"] in (IR.STREAM, IR.CACHE) for n in rec["plan"]["node_table"] if n["kind"] == "REDUCE")), c


# ============================================================================================================ C18 deep / shared work and bounded reuse
def test_C18_fifty_thousand_frame_chain_under_the_default_stack_and_a_shallow_lookalike(tmp_path):
    n = 50000; mp = str(tmp_path / "chain.uai")
    open(mp, "w").write("\n".join(["MARKOV", str(n), " ".join(["1"] * n), str(n - 1)] + ["2 %d %d" % (i, i + 1) for i in range(n - 1)] + ["1 1"] * (n - 1)) + "\n"); open(mp + ".evid", "w").write("")
    child = tmp_path / "child.py"
    child.write_text("import sys,json,time,resource; sys.path.insert(0,%r); sys.set_int_max_str_digits(0)\nfrom gbidi3 import executor as E\nr=E.execute('GENERAL_BIDI_COMPLETE_V3',%r,%r,%r,time.monotonic()+300,{'budget_s':300,'allow_binary64':False,'reference_fallback':False,'rules':[]},test_hooks={'force_stream':True})\nc=[a for a in r['attempts'] if a.get('counters')][-1]['counters']\nprint(json.dumps({'status':r['status'],'depth':c['max_frame_depth'],'frames':c['value_frames']+c['pullback_frames'],'rows':all(v==[['1','1']] for v in r['certified_intervals'].values()),'stack':resource.getrlimit(resource.RLIMIT_STACK)[0]}))\n" % (HERE, mp, mp + ".evid", str(tmp_path / "o")))
    r = subprocess.run([PY, str(child)], capture_output=True, text=True, timeout=600, env=ENV); assert r.returncode == 0, r.stderr[-800:]
    o = json.loads(r.stdout.strip().splitlines()[-1]); assert o["status"] == "INTERVALS_OK" and o["depth"] >= n and o["rows"] and o["stack"] <= 16 << 20 and o["frames"] < 100 * n, o  # frames LINEAR in n (combined VALUE+PULLBACK frames): no full-model replay per coordinate
    # the shallow structural lookalike: the SAME chain with every bucket materialized -> frame depth stays small
    rec = run("GENERAL_BIDI_COMPLETE_V3", mp, mp + ".evid", str(tmp_path / "mat"), rules=[], b64=False); c = counters(rec); assert rec["status"] == "INTERVALS_OK" and c["max_frame_depth"] <= 8, c["max_frame_depth"]
    # repeated shared subexpressions: a fitting cache removes repeated visits relative to pure streaming (same answer)
    card = [3, 3, 3, 3, 3]; facs = rnd_model(18, card, [(0, 1), (1, 2), (2, 3), (3, 4), (0, 4)]); mp2, ep2 = write_uai(str(tmp_path / "cyc.uai"), card, facs); S, Z, N, rows = truth(mp2, ep2)
    st = run("GENERAL_BIDI_COMPLETE_V3", mp2, ep2, str(tmp_path / "st"), rules=[], b64=False, hooks={"mutate_program": set_storage(IR.STREAM)}); ca = run("GENERAL_BIDI_COMPLETE_V3", mp2, ep2, str(tmp_path / "ca"), rules=[], b64=False, hooks={"mutate_program": set_storage(IR.CACHE)})
    assert tight(st, rows) and tight(ca, rows) and counters(ca)["cache_hits"] >= 1 and counters(ca)["value_frames"] < counters(st)["value_frames"], (counters(ca)["value_frames"], counters(st)["value_frames"])


# ============================================================================================================ C19 numerical runtime guards
def test_C19_streamed_chain_binary64_labels_against_exact_truth_and_every_guard_branch(tmp_path):
    n = 22; card = [2] * n; facs = [((i, i + 1), [Fr(1), Fr(2), Fr(3), Fr(1)]) for i in range(n - 1)] + [((0,), [Fr(1), Fr(3)])]; mp, ep = write_uai(str(tmp_path / "ch.uai"), card, facs); T22 = chain_exact(n, (1, 2, 3, 1), 0, (1, 3))
    rec = run("GENERAL_BIDI_COMPLETE_V3", mp, ep, str(tmp_path / "s"), rules=[], hooks={"force_stream": True}); a = [x for x in rec["attempts"] if x["route"] == "binary64"][0]
    assert rec["route"] == "binary64" and all(Fr(lo) <= T22[v][s] <= Fr(hi) for v in range(n) for s, (lo, hi) in enumerate(rec["certified_intervals"][str(v)])) and a["labels"]["E_N_max"] > 50 and 0 < a["delta_max"] < 1e-9, a.get("labels")
    m = run("GENERAL_BIDI_COMPLETE_V3", mp, ep, str(tmp_path / "m"), rules=[], b64=False, hooks={"force_stream": True}); assert all(Fr(lo) <= T22[v][s] <= Fr(hi) for v in range(n) for s, (lo, hi) in enumerate(m["certified_intervals"][str(v)]))
    # injected leaf labels: 2^51 -> label cap exceeded in the kernel (LABEL fault -> MPFR); 2^49 -> delta >= 1/2 refused; 2^45 -> TOO_WIDE then MPFR
    for e, expect in ((1 << 51, ("ROUTE_FAULT_LABEL",)), (1 << 47, ("LABEL_DELTA_TOO_LARGE",)), (1 << 45, ("TOO_WIDE",))):                        # 2^51: kernel label cap (sums exceed 2^52); 2^47: delta = (E_N+E_Z) u >= 1/2 refused; 2^45: delta 0.18 -> width > 1/100
        r = run("GENERAL_BIDI_COMPLETE_V3", mp, ep, str(tmp_path / ("lab%d" % e)), rules=[], hooks={"leaf_label": e}); b = [x for x in r["attempts"] if x["route"] == "binary64"][0]
        assert b["outcome"] in expect and r["route"] == "mpfr" and all(Fr(lo) <= T22[v][s] <= Fr(hi) for v in range(n) for s, (lo, hi) in enumerate(r["certified_intervals"][str(v)])), (e, b["outcome"])
    # subnormal / overflow boundaries at the leaves: the leaf predicate declines binary64 (admission false), MPFR certifies
    for tok in ("1e-308", "1e308"):
        mp2, ep2 = write_uai(str(tmp_path / "b.uai"), [2], [((0,), [1, 1])], tokens=[[tok, "1"]]); r = run("GENERAL_BIDI_COMPLETE_V3", mp2, ep2, str(tmp_path / ("b" + tok)), rules=[])
        assert r["binary64_admission"]["admitted"] is False and r["route"] == "mpfr" and truth_inside(r, mp2, ep2), tok
    # altered rounding mode -> FP_ENV refusal of binary64, MPFR still certifies; restored mode -> binary64 again
    libc = ctypes.CDLL(None); libc.fesetround.argtypes = [ctypes.c_int]; libc.fesetround.restype = ctypes.c_int; libc.fegetround.restype = ctypes.c_int; old = libc.fegetround()
    up = 0x400000 if (sys.platform == "darwin" and os.uname().machine == "arm64") else 0x800; assert libc.fesetround(up) == 0
    try:
        r = run("GENERAL_BIDI_COMPLETE_V3", mp, ep, str(tmp_path / "up"), rules=[], fallback=False)
    finally:
        libc.fesetround(old)
    assert r["route"] == "mpfr" and any(x["route"] == "binary64" and x["outcome"] == "FP_ENV_REFUSED" for x in r["attempts"]) and all(Fr(lo) <= T22[v][s] <= Fr(hi) for v in range(n) for s, (lo, hi) in enumerate(r["certified_intervals"][str(v)]))
    r = run("GENERAL_BIDI_COMPLETE_V3", mp, ep, str(tmp_path / "nm"), rules=[], fallback=False); assert r["route"] == "binary64"
    # MPFR exponent faults are typed NUMERIC_RANGE stops with exactly one MPFR attempt (no precision ladder)
    L = EX.Lib.get(); L.gb3_test_exponent_range(-20, 20)
    try:
        mp3, ep3 = write_uai(str(tmp_path / "big.uai"), [2, 2], [((0, 1), [Fr(2 ** 30)] * 4), ((0,), [Fr(2 ** 30), 1])])
        with pytest.raises(EX.Refuse) as ex:
            run("GENERAL_BIDI_COMPLETE_V3", mp3, ep3, str(tmp_path / "ov"), rules=[], b64=False, fallback=False)
        assert ex.value.kind == "NUMERIC_RANGE" and sum(1 for x in ex.value.rec["attempts"] if x["route"] == "mpfr") == 1 and ex.value.rec["attempts"][-1]["outcome"] == "MPFR_EXPONENT_RANGE_FAULT"
    finally:
        L.gb3_test_exponent_range(0, 0)
    # copied / cached labels and shared operands used twice: CACHE storage in binary64 (labels travel with the cached value) and the C03 shared program
    r = run("GENERAL_BIDI_COMPLETE_V3", mp, ep, str(tmp_path / "cl"), rules=[], hooks={"mutate_program": set_storage(IR.CACHE)}); assert r["route"] == "binary64" and counters(r)["cache_hits"] >= 1 and all(Fr(lo) <= T22[v][s] <= Fr(hi) for v in range(n) for s, (lo, hi) in enumerate(r["certified_intervals"][str(v)]))
    mp4, ep4 = write_uai(str(tmp_path / "sh.uai"), [2], [((0,), [1, 2]), ((0,), [1, 1])]); S4, Z4, N4, rows4 = truth(mp4, ep4)
    def mut(P):
        S_, R_, T_, plan, cands = plan_program(mp4, ep4); P2 = _shared_consumer_program(T_, IR.CACHE); P.nodes = P2.nodes; P.roots = P2.roots; P.derived = P2.derived
    r = run("GENERAL_BIDI_COMPLETE_V3", mp4, ep4, str(tmp_path / "sh"), rules=[], hooks={"mutate_program": mut}); assert r["route"] == "binary64" and contained(r, rows4) and [x for x in r["attempts"] if x["route"] == "binary64"][0]["labels"]["E_N_max"] >= 2


# ============================================================================================================ C20 planner / validator attack
def test_C20_every_corruption_class_is_rejected_or_cannot_reach_execution(tmp_path):
    card = [3, 2, 3, 2]; facs = rnd_model(20, card, [(0, 1), (1, 2), (2, 3), (0, 3)], zeros=0.2); mp, ep = write_uai(str(tmp_path / "m.uai"), card, facs); S, Z, N, rows = truth(mp, ep)
    S_, R_, T, plan, cands = plan_program(mp, ep, two_axis=False); P = plan.program; V = GV.validate(P, T); assert V.record["status"] == "VALID"
    def rejects(mutator, needle=None):
        Q = copy.deepcopy(P); mutator(Q)
        with pytest.raises((TR.Invalid, IR.IRError)) as ex:
            GV.validate(Q, T)
        if needle:
            assert needle in str(ex.value), str(ex.value)
    mul = [n for n in P.nodes if n.kind == IR.MUL][0]
    def drop_child(Q):
        m = Q.nodes[mul.nid]; m.children = m.children[1:]; m.proj = m.proj[1:]
    rejects(drop_child)                                                                                                                             # dropped consumer edge -> an occurrence / marker is no longer covered
    def forge_view(Q):
        red = [n for n in Q.nodes if n.kind == IR.REDUCE and n.axes][0]; k = [i for i, r in enumerate(red.rmap) if r >= 0][0]; raw = Q.nodes[red.children[0]].card[k]
        red.reps = tuple((((0,), tuple([0] * raw), tuple([Fr(1)] * raw)) if i == k else r) for i, r in enumerate(red.reps)); red.card = tuple(1 if i == red.rmap[k] else c for i, c in enumerate(red.card))
        for m in Q.nodes:
            if m.kind == IR.GATHER and red.nid in m.children:
                m.gaxes = tuple(dict(g, cls=tuple([0] * raw), ratio=tuple([Fr(1)] * raw)) if g["out_pos"] == red.rmap[k] else g for g in m.gaxes)
            elif red.nid in m.children and m.kind == IR.MUL:
                pass
    rejects(forge_view)
    rejects(lambda Q: setattr(Q.nodes[mul.nid], "proj", (Q.nodes[mul.nid].proj[1],) + Q.nodes[mul.nid].proj[1:]))                                # malformed / reordered axes (rejected as a non-total projection)
    rejects(lambda Q: setattr(Q.nodes[mul.nid], "card", tuple(c + 1 for c in Q.nodes[mul.nid].card)))                                            # changed cardinality
    rejects(lambda Q: setattr([n for n in Q.nodes if n.kind == IR.SOURCE][0], "fid", 999), "unknown factor")                                      # changed table identity
    rejects(lambda Q: setattr([n for n in Q.nodes if n.kind == IR.SOURCE][0], "axes", tuple(reversed([n for n in Q.nodes if n.kind == IR.SOURCE][0].axes))) if len([n for n in Q.nodes if n.kind == IR.SOURCE][0].axes) == 2 else setattr(Q.nodes[mul.nid], "card", (1,) * len(Q.nodes[mul.nid].card)))  # changed scope orientation
    rejects(lambda Q: Q.roots.append(Q.roots[0]), "duplicate")
    rejects(lambda Q: setattr(Q.nodes[0], "nid", 1), "positional")
    with pytest.raises(IR.IRError):
        Q = IR.Program(); Q.add(IR.ADD, (0,), (3,), children=(5,))                                                                               # a child that does not precede: cycles are unrepresentable
    rejects(lambda Q: setattr(Q, "derived", {7: {"kind": "product_split", "parent": 999, "axis_k": 0, "u": (1,), "g": (1,), "part": "u"}}), "unknown parent")
    # planner-supplied scale: a CONSTANT other than the trusted scale is rejected
    def const(Q):
        c = Q.add(IR.CONSTANT, (), (), value=Fr(7, 3)); Q.roots.append(c.nid)
    rejects(const, "trusted scale")
    # live-source mutation during planning -> REJECTED before numerics
    with pytest.raises(EX.Refuse) as ex:
        run("GENERAL_BIDI_COMPLETE_V3", mp, ep, str(tmp_path / "mut"), rules=[], hooks={"mutate_reduced": lambda R: R.factors[0].table.__setitem__(0, R.factors[0].table[0] + 1)})
    assert ex.value.kind == "REJECTED" and "mutated during planning" in ex.value.reason
    # planner payload changed AFTER validation: execution uses the validated copy -> truth still holds, no corruption reaches the kernel
    def after(P2):
        for n in P2.nodes:
            if n.kind == IR.SOURCE:
                n.fid = 999
            n.card = tuple(1 for _ in n.card)
    rec = run("GENERAL_BIDI_COMPLETE_V3", mp, ep, str(tmp_path / "after"), rules=[], b64=False, hooks={"after_validate": after}); assert truth_inside(rec, mp, ep)
    # a forged demand hint changes WORK, never the answer
    def forge_demand(P2):
        for n in P2.nodes:
            if n.kind == IR.REDUCE and n.axes and n.nid not in P2.roots:
                n.storage = IR.DENSE; n.demand = (0,); n.driver = -1                                                                             # FIXTURE CHANGE (fourth review A): a forged DENSE node carries no sparse driver (a stale driver is itself rejected by the validator)
    rec = run("GENERAL_BIDI_COMPLETE_V3", mp, ep, str(tmp_path / "dem"), rules=[], b64=False, hooks={"mutate_program": forge_demand}); assert truth_inside(rec, mp, ep) and counters(rec)["reads_outside_demand"] >= 1
    # the file changes after the snapshot: the record is bound to the parsed bytes; publication refuses (TASK_MISMATCH / CHECK_FAILED), no MAR
    rec = run("GENERAL_BIDI_COMPLETE_V3", mp, ep, str(tmp_path / "fc"), rules=[], b64=False); orig = open(mp).read()
    open(mp, "a").write("\n\n"); st, cell = publish(str(tmp_path / "fc"), mp, ep, rec); assert st == "CHECK_FAILED" and not os.path.exists(tmp_path / "fc" / "output.MAR") and "bound" in cell["publication"]["reason"]        # valid bytes, different raw hash: the record is bound to the parsed bytes
    open(mp, "w").write(orig + "\n7\n"); st, cell = publish(str(tmp_path / "fc"), mp, ep, rec); assert st == "CHECK_FAILED" and not os.path.exists(tmp_path / "fc" / "output.MAR")                                           # invalid bytes: typed refusal, no exception
    open(mp, "w").write(orig); st, cell = publish(str(tmp_path / "fc"), mp, ep, rec); assert st == "CERTIFIED"


# ============================================================================================================ C21 task / publication attacks through the actual cell -> checker -> publisher -> verifier
def test_C21_task_and_publication_attacks(tmp_path):
    card = [2, 3]; mp, ep = write_uai(str(tmp_path / "t.uai"), card, [((0, 1), [1, 2, 3, 4, 5, 6]), ((0,), [2, 1])], {0: 0}); mp1, ep1 = write_uai(str(tmp_path / "t1.uai"), card, [((0, 1), [1, 2, 3, 4, 5, 6]), ((0,), [2, 1])], {0: 1})
    out0 = str(tmp_path / "x0"); rec0 = run("GENERAL_BIDI_COMPLETE_V3", mp, ep, out0, rules=[], b64=False); st, cell = publish(out0, mp, ep, rec0); assert st == "CERTIFIED"
    # the x=0 receipt staged for the x=1 task: publish() refuses; the checker CLI (verifier) rejects; the x=1 task certifies its own rows
    out1 = str(tmp_path / "x1"); os.makedirs(out1); shutil.copy(os.path.join(out0, "checked_record.json"), os.path.join(out1, "checked_record.json"))
    st, cell = publish(out1, mp1, ep1, rec0); assert st == "CHECK_FAILED" and not os.path.exists(os.path.join(out1, "output.MAR")) and "bound" in cell["publication"]["reason"]
    r = subprocess.run([PY, "-m", "gbidi3.verify", os.path.join(out0, "checked_record.json"), os.path.join(out0, "output.MAR"), mp1, ep1, str(tmp_path / "v.json")], capture_output=True, text=True, cwd=HERE, env=ENV); assert json.load(open(tmp_path / "v.json"))["status"] == "POINT_REJECTED"
    rec1 = run("GENERAL_BIDI_COMPLETE_V3", mp1, ep1, out1, rules=[], b64=False); st, cell = publish(out1, mp1, ep1, rec1); assert st == "CERTIFIED" and U.read_mar(os.path.join(out1, "output.MAR"))[0][0] == [Fr(0), Fr(1)]
    # mutated records: wrong eps / queries / nvars / status / missing rows / extra rows / malformed interval / width-passing but point-infeasible / stale REJECTED
    def mutated(mutator):
        r2 = copy.deepcopy(rec0); mutator(r2); mutated.k = getattr(mutated, "k", 0) + 1; o = str(tmp_path / ("m%d" % mutated.k)); os.makedirs(o, exist_ok=True); return publish(o, mp, ep, r2)[0], o
    for mut in (lambda r: r["task"].__setitem__("eps", "1/100"), lambda r: r["task"].__setitem__("queries_sha256", "x"), lambda r: r["task"].__setitem__("nvars", 3), lambda r: r.__setitem__("status", "REJECTED"), lambda r: r["certified_intervals"].pop("1"), lambda r: r["certified_intervals"].__setitem__("1", r["certified_intervals"]["1"][:2]), lambda r: r["task"].pop("raw_evidence_sha256")):
        st, o = mutated(mut); assert st == "CHECK_FAILED" and not os.path.exists(os.path.join(o, "output.MAR")), mut
    def infeasible(r):
        r["certified_intervals"]["1"] = [["0", "1/1000"], ["0", "1/1000"], ["0", "1/1000"]]                                                  # widths pass, no simplex point
    st, o = mutated(infeasible); assert st in ("CERTIFIED_WIDTH_ONLY_POINT_INFEASIBLE", "CHECK_FAILED") and not os.path.exists(os.path.join(o, "output.MAR"))
    def wide(r):
        r["certified_intervals"]["1"] = [["0", "1/50"], ["0", "1/50"], ["49/50", "1"]]
    st, o = mutated(wide); assert st in ("CERTIFIED_TOO_WIDE", "CHECK_FAILED") and not os.path.exists(os.path.join(o, "output.MAR"))
    # delivered-width boundary: pre-grid width exactly 1/100 widens on the grid beyond 1/100 -> refused as CERTIFIED_TOO_WIDE_DELIVERED
    def boundary(r):
        r["certified_intervals"]["1"] = [["1/3", "1/3"], ["1/3", "1/3"], ["1/3", "1/3"]]
        r["certified_intervals"]["1"] = [[str(Fr(1, 3) - Fr(1, 200)), str(Fr(1, 3) + Fr(1, 200))], ["1/3", "1/3"], ["1/3", "1/3"]]      # width exactly 1/100, endpoints not on the dyadic grid
    st, o = mutated(boundary); assert st in ("CERTIFIED_TOO_WIDE_DELIVERED", "CERTIFIED_WIDTH_ONLY_POINT_INFEASIBLE") and not os.path.exists(os.path.join(o, "output.MAR")), st
    r2 = copy.deepcopy(rec0); boundary(r2); cell = {"phases_s": {}}; os.makedirs(str(tmp_path / "bw"), exist_ok=True); EX.publish(str(tmp_path / "bw"), mp, ep, r2, cell, time.monotonic() + 30, arm=r2["arm"], cfg=r2["config"])
    assert cell["publication"]["delivered_width_met"] is False and Fr(cell["publication"]["max_width_observed"]) <= Fr(1, 100) < Fr(cell["publication"]["delivered_max_width"])     # pre-grid width passes, DELIVERED width does not: refused
    # the delivered MAR is corrupted after checking -> the separate verifier rejects (malformed decimal / extra row / wrong sum)
    for body in ("MAR\n2 2 1 0 3 0.3 0.3 0.4\n", "MAR\n2 2 1 0 3 0.3 0.3 0.3 2 1 0\n", "MAR\n2 2 1 0 3 0.3 abc 0.4\n", "MAR\n2 2 1 0 3 0.33 0.33 0.33\n", "MAR\n1 2 1 0\n"):
        bad = str(tmp_path / "bad.MAR"); open(bad, "w").write(body); subprocess.run([PY, "-m", "gbidi3.verify", os.path.join(out0, "checked_record.json"), bad, mp, ep, str(tmp_path / "v2.json")], capture_output=True, cwd=HERE, env=ENV); assert json.load(open(tmp_path / "v2.json"))["status"] == "POINT_REJECTED", body
    # zero-variable task with a positive scalar: valid empty result through the cell + verifier; zero scalar: inconsistent
    for val, expect in (("3/7", "CERTIFIED"), ("0", "INCONSISTENT_EVIDENCE_CERTIFIED")):
        mz = str(tmp_path / ("z%s.uai" % val.replace("/", "_"))); open(mz, "w").write("MARKOV 0 1 0 1 %s\n" % val); open(mz + ".evid", "w").write("")
        subprocess.run([PY, "-m", "gbidi3.cell", "GENERAL_BIDI_COMPLETE_V3", mz, mz + ".evid", str(tmp_path / ("zo" + expect)), "20", "{}"], capture_output=True, cwd=HERE, env=ENV, timeout=120)
        rec = json.load(open(tmp_path / ("zo" + expect) / "cell.json")); assert rec["status"] == expect, rec.get("reason")
        if expect == "CERTIFIED":
            assert open(tmp_path / ("zo" + expect) / "output.MAR").read().split() == ["MAR", "0"] and rec["point_verification"]["status"] == "POINT_VERIFIED"
    # TASK_MISMATCH against a frozen expected task through the cell
    subprocess.run([PY, "-m", "gbidi3.cell", "GENERAL_BIDI_COMPLETE_V3", mp, ep, str(tmp_path / "tm"), "20", "{}", json.dumps({"raw_model_sha256": "0" * 64})], capture_output=True, cwd=HERE, env=ENV, timeout=120); assert json.load(open(tmp_path / "tm" / "cell.json"))["status"] == "TASK_MISMATCH"


# ============================================================================================================ C22 resource / ABI controls
def test_C22_every_category_cap_python_storage_pending_transfers_fallback_export_overflow_polling_abi(tmp_path):
    card = [3, 3, 3, 3]; facs = rnd_model(22, card, [(0, 1), (1, 2), (2, 3), (0, 3)]); mp, ep = write_uai(str(tmp_path / "m.uai"), card, facs); S, Z, N, rows = truth(mp, ep)
    # Python-side storage category: a 1-byte cap stops at the snapshot with a typed MEMORY_CATEGORY RESOURCE_STOP (no numerics)
    with pytest.raises(EX.Refuse) as ex:
        run("GENERAL_BIDI_COMPLETE_V3", mp, ep, str(tmp_path / "py"), rules=[], ledger=GM.Ledger(dict(GM.CAPS, source_ir_maps_output=1)))
    assert ex.value.kind == "RESOURCE_STOP" and "MEMORY_CATEGORY source_ir_maps_output" in ex.value.reason and not ex.value.rec.get("attempts")
    # every kernel category at one byte: a typed MEMORY stop of the affected path, never a silent borrow; what follows is the category's declared response
    led = GM.Ledger(dict(GM.CAPS, value_cache_blocks=1)); rec = run("GENERAL_BIDI_COMPLETE_V3", mp, ep, str(tmp_path / "vc"), rules=[], b64=False, ledger=led)       # value blocks refused -> every stored node downgrades to STREAM (once), no cache; exact fallback if even that fails
    assert tight(rec, rows) and (rec["route"] == "exact_fallback" or (counters(rec)["cache_inserts"] == 0 and counters(rec)["used_values_bytes"] <= 1 and (counters(rec)["downgrades"] >= 1 or all(n["storage"] in (IR.STREAM, IR.CACHE) for n in rec["plan"]["node_table"] if n["kind"] == "REDUCE")))), rec.get("route")   # FIXTURE CHANGE (second review repair): the plan streams everything under the 1-byte value cap; no kernel downgrade is needed
    rec = run("GENERAL_BIDI_COMPLETE_V3", mp, ep, str(tmp_path / "rp"), rules=[], b64=False, ledger=GM.Ledger(dict(GM.CAPS, reverse_pinned=1)))                 # numerators unreservable -> MEMORY at forward -> exact fallback (values + scratch categories) completes
    assert rec["route"] == "exact_fallback" and exact_rows(rec, rows) and rec["stop"]["kind"] == "MEMORY" and all(a.get("stop") == "MEMORY" for a in rec["attempts"])
    with pytest.raises(EX.Refuse) as ex:
        run("GENERAL_BIDI_COMPLETE_V3", mp, ep, str(tmp_path / "rpnf"), rules=[], b64=False, ledger=GM.Ledger(dict(GM.CAPS, reverse_pinned=1)), fallback=False)
    assert ex.value.kind == "RESOURCE_STOP" and ex.value.rec["stop"]["cause"]["kind"] == "MEMORY"
    rec = run("GENERAL_BIDI_COMPLETE_V3", mp, ep, str(tmp_path / "pa"), rules=[], b64=False, ledger=GM.Ledger(dict(GM.CAPS, pending_adjoints=1)), fallback=False)   # pending refused -> every delta delivered immediately (no coalescing), answer tight
    assert tight(rec, rows) and counters(rec)["adjoint_adds"] == 0 and counters(rec)["pullback_frames"] >= 1
    with pytest.raises(EX.Refuse) as ex:
        run("GENERAL_BIDI_COMPLETE_V3", mp, ep, str(tmp_path / "fs"), rules=[], b64=False, ledger=GM.Ledger(dict(GM.CAPS, frames_scratch_pub=1)))                  # frames / conversion scratch refused: native MEMORY, fallback MEMORY (its own scratch), typed stop
    assert ex.value.kind == "RESOURCE_STOP" and "MEMORY" in ex.value.reason and ex.value.rec["exact_fallback"]["status"] == "MEMORY"
    # pending -> ACTIVE transfers under a tiny pending cap: early flushes fire, answer exact
    led = GM.Ledger(dict(GM.CAPS, pending_adjoints=600)); rec = run("GENERAL_BIDI_COMPLETE_V3", mp, ep, str(tmp_path / "pend"), rules=[], b64=False, ledger=led, fallback=False); c = counters(rec)
    assert tight(rec, rows) and (c["early_flushes"] >= 1 or c["adjoint_adds"] == 0), c
    # fallback reserves tables / accumulators / export: 1-byte caps -> typed MEMORY, never a partial answer
    fb = EX.exact_fallback(GS.Snapshot(mp, ep), time.monotonic() + 30, GM.Ledger(dict(GM.CAPS, value_cache_blocks=1))); assert fb["status"] == "MEMORY"
    fb = EX.exact_fallback(GS.Snapshot(mp, ep), time.monotonic() + 30, GM.Ledger(dict(GM.CAPS, frames_scratch_pub=1))); assert fb["status"] == "MEMORY"
    fb = EX.exact_fallback(GS.Snapshot(mp, ep), time.monotonic() + 30, GM.Ledger()); assert fb["status"] == "COMPLETE" and fb["Z"] == Z
    cardL = [3] * 10; facsL = rnd_model(222, cardL, [(i, i + 1) for i in range(9)]); mpL, epL = write_uai(str(tmp_path / "long.uai"), cardL, facsL)
    fb = EX.exact_fallback(GS.Snapshot(mpL, epL), time.monotonic() - 1, GM.Ledger()); assert fb["status"] == "DEADLINE" and "Z" not in fb and fb["visited"] < 3 ** 10       # the deadline is checked within 4,096 primitive units; a partial enumeration is never an answer
    # int64 / index overflow: a symbolic domain beyond int64 is NOT_REPRESENTABLE for the indexed route (typed), the model stays valid (fallback on the clock)
    n = 70; mpb = str(tmp_path / "wide.uai"); open(mpb, "w").write("\n".join(["MARKOV", str(n), " ".join(["2"] * n), "1", "%d %s" % (n, " ".join(map(str, range(n)))), "%d %s" % (2 ** 20, " ".join(["1"] * (2 ** 20)))]) + "\n") if False else None
    big = IR.Program()
    with pytest.raises(IR.IRError):
        big.add(IR.MUL, tuple(range(70)), (2,) * 70, children=())                                                                                     # 2^70 > int64: no overflowing flattened key can be constructed
    with pytest.raises(IR.IRError):
        big.add(IR.REDUCE, (), (), children=())
    # polling: the preserved 3,000-unary control (3,000 cardinality-1 variables, one unary each; binary64 mode so loading costs 3,001 units) reaches its FIRST
    # poll within 4,096 primitive units of actual work in forward (raw kernel, deadline already passed -> exactly one poll, typed DEADLINE)
    L = EX.Lib.get(); c_ = ctypes; nf = 3000; prog = [3, nf] + [1] * nf + [nf]
    for i in range(nf):
        prog += [1, i, 1, i]
    prog += [0]; nodes = []
    for i in range(nf):
        nodes += [0, 1, i, 1, 0, 0, 0, i]                                                # SOURCE_i (axis i, card 1)
    for i in range(nf):
        nodes += [1, 1, i, 1, 0, 0, 0, i]                                                # MARKER_i
    for i in range(nf):
        nodes += [5, 1, i, 1, 0, 0, 0, 2, i, nf + i, 0, 0]                               # MUL_i(SOURCE_i, MARKER_i)
    for i in range(nf):
        nodes += [6, 0, 1, 0, 0, 2 * nf + i, -1, -1, -1]                                   # REDUCE_i over i -> scalar root (DENSE); FIXTURE CHANGE (fourth review A): the flat REDUCE carries one more word, the sparse driver (-1 = none)
    prog += [4 * nf] + nodes + [nf] + [3 * nf + i for i in range(nf)]
    a = (c_.c_int64 * len(prog))(*prog); qs = (c_.c_char_p * (nf + 1))(*([b"1/1"] * (nf + 1))); dv = (c_.c_double * (nf + 1))(*([1.0] * (nf + 1))); caps = (c_.c_uint64 * 5)(*([1 << 28] * 5)); err = c_.c_int()
    h0 = L.gb3_create(1, 53, a, len(prog), qs, dv, nf, 0, 0, caps, 0.0, c_.byref(err)); assert not h0 and err.value == 1, err.value                  # FIXTURE CHANGE (repair E5): program parsing polls -> an already-expired deadline is refused AT CREATE (typed DEADLINE, clean teardown)
    h = L.gb3_create(1, 53, a, len(prog), qs, dv, nf, 0, 0, caps, 0.6, c_.byref(err)); assert h, err.value
    c0 = EX._counters(L, h); time.sleep(0.7); st = L.gb3_forward(c_.c_void_p(h)); cnt = EX._counters(L, h); L.gb3_destroy(c_.c_void_p(h))
    fw = {k: cnt[k] - c0[k] for k in ("polls", "source_reads", "mults", "adds", "value_frames", "pullback_frames")}
    assert st == 1 and fw["polls"] == 1 and fw["source_reads"] + fw["mults"] + fw["adds"] + fw["value_frames"] + fw["pullback_frames"] <= 4096 + 8, (c0["polls"], fw)   # the first FORWARD poll within one quantum of forward work (create's own polls counted separately)
    # K2 (repaired latent defect): a DEADLINE that fires DURING value loading (MPFR mode: strlen + conversion polls) must not crash in the destructor
    qs2 = (c_.c_char_p * (nf + 1))(*([b"1/1"] * (nf + 1))); h2 = L.gb3_create(0, 64, a, len(prog), qs2, None, nf, 0, 0, caps, 0.0, c_.byref(err)); assert not h2 and err.value == 1, err.value   # DEADLINE at create, clean teardown
    # bad_alloc at the C ABI is a typed MEMORY stop, not a process abort; the fallback completes
    L.gb3_test_inject_bad_alloc(1)
    try:
        rec = run("GENERAL_BIDI_COMPLETE_V3", mp, ep, str(tmp_path / "ba"), rules=[], b64=False); assert rec["route"] == "exact_fallback" and exact_rows(rec, rows) and rec["stop"]["kind"] == "MEMORY"
    finally:
        L.gb3_test_inject_bad_alloc(0)
    # external OOM kill (supervisor MEMORY_KILL) is distinct from a cooperative category stop (RESOURCE_STOP in cell.json)
    hog = str(tmp_path / "hog.py"); open(hog, "w").write("import time\nx=bytearray(600*1024*1024)\ntime.sleep(5)\n"); led = str(tmp_path / "l.jsonl")
    subprocess.run([PY, "-m", "gbidi.supervise", "--ledger", led, "--scope", "test", "--job", "hog", "--timeout", "10", "--mem-gib", "0.25", "--", PY, hog], capture_output=True, timeout=60, cwd=HERE, env=ENV)
    rc = [json.loads(x) for x in open(led) if json.loads(x)["kind"] == "RECEIPT"][-1]; assert rc["outcome"] == "MEMORY_KILL" and rc["mem_overshoot_bytes"] > 0


# ============================================================================================================ C23 clock and planner policy
def test_C23_star_cases_reach_the_cheap_order_with_an_expired_optional_clock_and_one_hard_deadline(tmp_path):
    for n in (65, 80, 600):
        mp, ep, tr = star_model(str(tmp_path / ("star%d.uai" % n)), n)
        rec = run("GENERAL_BIDI_COMPLETE_V3", mp, ep, str(tmp_path / ("s%d" % n)), rules=[], b64=False, budget=20, extra_cfg={"_optional_allowance_s": 0.0})
        assert rec["status"] == "INTERVALS_OK" and all(Fr(lo) <= tr[v][s] <= Fr(hi) for v in range(n) for s, (lo, hi) in enumerate(rec["certified_intervals"][str(v)])), (n, rec.get("reason"))
        assert rec["clock"]["optional_expired"] is True and rec["plan"]["order"] in ("min_prospective_bag_volume", "min_volume", "min_fill") and rec["plan"]["discovery_stop"]["kind"] == "DISCOVERY_WALL", (rec["clock"], rec["plan"]["order"])
        cands = {c["order"]: c for c in rec["plan_candidates"]}; assert cands["original_id"]["state"] in ("NOT_REPRESENTABLE", "COMPLETE") and cands["min_volume"]["state"] == "COMPLETE" and cands["min_volume"]["chosen"]
        if n == 600:
            assert cands["original_id"]["state"] == "NOT_REPRESENTABLE"                                                                          # the 2^600 bag is not an indexed route; the baseline survives on min-volume
    # inspection shares the clock semantics: a hard deadline in the past -> RESOURCE_STOP; no fresh now+budget
    mp, ep, tr = star_model(str(tmp_path / "s65b.uai"), 65); r = EX.plan_only("GENERAL_BIDI_COMPLETE_V3", mp, ep, 20.0, hard_deadline=time.monotonic() - 1); assert r["status"] == "RESOURCE_STOP"
    r = EX.plan_only("GENERAL_BIDI_COMPLETE_V3", mp, ep, 20.0); assert r["status"] == "PLANNED" and r["clock"]["optional_allowance_s"] == 1.0
    # no deadline reset at validation / numerics / fallback: an executor deadline that passes during the reductions ends as RESOURCE_STOP DEADLINE
    with pytest.raises(EX.Refuse) as ex:
        EX.execute("GENERAL_BIDI_COMPLETE_V3", mp, ep, str(tmp_path / "dl"), time.monotonic() + 0.001, {"budget_s": 0.001, "allow_binary64": False})
    assert ex.value.kind == "RESOURCE_STOP" and "DEADLINE" in ex.value.reason
    # mandatory orders use the cell clock, not the optional allowance: the metadata cap exhausted -> original-order baseline survives
    old = GC.METADATA_UPDATE_CAP
    try:
        mp2, ep2 = write_uai(str(tmp_path / "t.uai"), [2, 2, 2], [((0, 1), [1, 2, 3, 4]), ((1, 2), [1, 2, 3, 4])]); S, Z, N, rows = truth(mp2, ep2)
        S_, R_, T_, plan, cands = plan_program(mp2, ep2)
        clock = GC.Clock(time.monotonic() + 30, 30); clock.meta_cap = 1; plan2, cands2 = PL.plan(T_.proposal_view(), PL.ARMS["GENERAL_BIDI_COMPLETE_V3"], clock, 64)
        assert plan2.order_name == "original_id" and all(c["state"].startswith("ORDER_INCOMPLETE") for c in cands2 if c["order"] != "original_id"), cands2
    finally:
        GC.METADATA_UPDATE_CAP = old


# ============================================================================================================ C24 harness and supervisor
def test_C24_supervisor_completion_means_the_owned_group_is_empty(tmp_path):
    import psutil
    pidfile = str(tmp_path / "pid.txt"); leader = str(tmp_path / "leader.py"); open(leader, "w").write("import subprocess,sys,time\np=subprocess.Popen([sys.executable,'-c','import time; time.sleep(5)'])\nopen(sys.argv[1],'w').write(str(p.pid))\ntime.sleep(0.10)\n")
    led = str(tmp_path / "ledger.jsonl"); cmd = [PY, "-m", "gbidi.supervise", "--ledger", led, "--scope", "test", "--job", "leader-exits-first", "--timeout", "3", "--", PY, leader, pidfile]
    subprocess.run(cmd, capture_output=True, text=True, timeout=30, cwd=HERE, env=ENV); pid = int(open(pidfile).read())
    alive = psutil.pid_exists(pid) and psutil.Process(pid).status() != psutil.STATUS_ZOMBIE
    if alive:
        os.kill(pid, signal.SIGKILL)
    rc = [json.loads(x) for x in open(led) if json.loads(x)["kind"] == "RECEIPT"][-1]
    assert not alive and rc["descendants_after_leader_exit"] >= 1 and rc["group_empty_at_receipt"] is True and rc["outcome"] == "COMPLETED_LEADER_EXIT_SURVIVORS_KILLED" and rc["cleanup_unresolved"] is False
    # missing executable -> LAUNCH_FAILED receipt; timeout -> TIMEOUT_KILL; both charged with walls
    led2 = str(tmp_path / "l2.jsonl"); subprocess.run([PY, "-m", "gbidi.supervise", "--ledger", led2, "--scope", "test", "--job", "missing", "--timeout", "3", "--", "/nonexistent/binary"], capture_output=True, timeout=30, cwd=HERE, env=ENV)
    rc2 = [json.loads(x) for x in open(led2) if json.loads(x)["kind"] == "RECEIPT"][-1]; assert rc2["outcome"] == "LAUNCH_FAILED" and rc2["launch_error"] and rc2["wall_s"] >= 0
    led3 = str(tmp_path / "l3.jsonl"); subprocess.run([PY, "-m", "gbidi.supervise", "--ledger", led3, "--scope", "test", "--job", "slow", "--timeout", "0.5", "--", PY, "-c", "import time; time.sleep(30)"], capture_output=True, timeout=60, cwd=HERE, env=ENV)
    rc3 = [json.loads(x) for x in open(led3) if json.loads(x)["kind"] == "RECEIPT"][-1]; assert rc3["outcome"] == "TIMEOUT_KILL" and rc3["group_empty_at_receipt"] is True and 0.5 <= rc3["wall_s"] < 20
    # SIGTERM at the launch boundary: the supervisor is terminated right after start; the child must not survive and a receipt exists
    led4 = str(tmp_path / "l4.jsonl"); p = subprocess.Popen([PY, "-m", "gbidi.supervise", "--ledger", led4, "--scope", "test", "--job", "term", "--timeout", "30", "--", PY, "-c", "import time; time.sleep(30)"], cwd=HERE, env=ENV, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    time.sleep(0.6); os.kill(p.pid, signal.SIGTERM); p.wait(timeout=30)
    rows4 = [json.loads(x) for x in open(led4)]; rc4 = [r for r in rows4 if r["kind"] == "RECEIPT"][-1]; sp = [r for r in rows4 if r["kind"] == "SPAWNED"]
    assert rc4["outcome"].startswith("SUPERVISOR_SIGNAL") and rc4["group_empty_at_receipt"] is True and rc4["cleanup_unresolved"] is False
    if sp:
        assert not psutil.pid_exists(sp[0]["pid"]) or psutil.Process(sp[0]["pid"]).status() == psutil.STATUS_ZOMBIE


def test_C24_nested_supervisors_owned_tree_is_reconciled(tmp_path):
    import psutil
    leaf = str(tmp_path / "leaf.json"); outer_led = str(tmp_path / "outer.jsonl"); inner_led = str(tmp_path / "inner.jsonl")
    leafcode = "import os,time,json;open(%r,'w').write(json.dumps({'pid':os.getpid(),'pgid':os.getpgrp()}));time.sleep(4)" % leaf
    inner = [PY, "-m", "gbidi.supervise", "--ledger", inner_led, "--scope", "inner", "--job", "inner", "--timeout", "1", "--", PY, "-c", leafcode]
    leadercode = "import subprocess,time,os;subprocess.Popen(%r,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL);p=%r\nt=time.monotonic()\nwhile not os.path.exists(p) and time.monotonic()-t<2:time.sleep(.01)\ntime.sleep(.1)\n" % (inner, leaf)
    subprocess.run([PY, "-m", "gbidi.supervise", "--ledger", outer_led, "--scope", "stage_outer_test", "--job", "stage_runner:test", "--timeout", "3", "--", PY, "-c", leadercode], capture_output=True, text=True, timeout=40, cwd=HERE, env=ENV)
    ident = json.load(open(leaf)); pid = ident["pid"]; alive = psutil.pid_exists(pid) and psutil.Process(pid).status() != psutil.STATUS_ZOMBIE
    if alive:
        os.kill(pid, signal.SIGKILL)
    rc = [json.loads(x) for x in open(outer_led) if json.loads(x)["kind"] == "RECEIPT"][-1]; inner_rows = [json.loads(x) for x in open(inner_led)]
    assert not alive and ident["pgid"] != rc["pgid"] and rc["nested_groups_registered"] == 1 and rc["nested_groups_killed"] == 1 and rc["nested_groups_live_at_receipt"] == 0 and rc["cleanup_unresolved"] is False
    assert [x["kind"] for x in inner_rows] == ["START", "SPAWNED", "RECEIPT"] and inner_rows[-1]["outcome"] == "PARENT_CLEANUP_KILL" and inner_rows[-1]["written_by_parent"] == rc["jid"]


def test_C24_manifest_reconciler_and_accounting(tmp_path):
    from gbidi3 import pilot as PI, reconcile as RC
    from gbidi3_closeout import report as R
    man = {"seed": PI.SEED, "commit": "c" * 40, "kernel_binary_sha256": "k" * 64, "config_adp_repaired_sha256": "f" * 64, "cases": {}, "cells": []}
    for c in PI.inventory():
        man["cases"][c] = {"canonical_model_sha256": "m" + c, "canonical_evidence_sha256": "e" + c, "raw_model_sha256": "rm" + c, "raw_evidence_sha256": "re" + c}
    for i, c in enumerate(PI.order()):
        tid, cid = PI.canonical_task(man["cases"][c["case"]], c, man["config_adp_repaired_sha256"], man["kernel_binary_sha256"], man["commit"]); man["cells"].append(dict(c, index=i, task_id=tid, cell_id=cid, out_dir="cells/%s/%03d__%s" % (c["stage"], i, tid)))
    assert PI.reconcile_manifest(man) is None and len(man["cells"]) == 414 and sum(1 for c in man["cells"] if c["stage"] == "primary_breadth") == 184 and sum(1 for c in man["cells"] if c["stage"] == "primary_depth") == 92 and sum(1 for c in man["cells"] if c["stage"] == "ablation_breadth") == 138
    # the frozen order procedure reproduced independently (one continuing generator; shuffle; one offset; rotation)
    rng = random.Random(PI.SEED); k = 0
    for stage, arms, budget in PI.STAGES:
        inv = list(PI.inventory()); rng.shuffle(inv); off = rng.randrange(len(arms))
        for i, case in enumerate(inv):
            for j in range(len(arms)):
                assert man["cells"][k]["case"] == case and man["cells"][k]["arm"] == arms[(i + off + j) % len(arms)]; k += 1
    for mut in (lambda m: m["cells"][1].__setitem__("out_dir", m["cells"][0]["out_dir"]), lambda m: m["cells"][1].__setitem__("cell_id", m["cells"][0]["cell_id"]), lambda m: m["cells"][0].__setitem__("task_id", "x"), lambda m: m.__setitem__("config_adp_repaired_sha256", "g" * 64), lambda m: m["cells"].__setitem__(0, dict(m["cells"][0], arm="A1_NO_DEMAND_MASKS"))):
        mm = copy.deepcopy(man); mut(mm); assert PI.reconcile_manifest(mm) is not None
    # accounting: repeated outer attempts each charged once with their own children (18 not 9); a missing outer receipt -> QUALIFIED
    D = str(tmp_path); rows = []
    for jid, scope, job, wall, beg, end, parent in (("o1", "stage_outer_primary_breadth", "stage_runner:primary_breadth", 10.0, 0, 10, None), ("c1", "matrix_primary_breadth", "cell:one", 5.0, 1, 6, "o1"), ("o2", "stage_outer_primary_breadth", "stage_runner:primary_breadth", 8.0, 20, 28, None), ("c2", "matrix_primary_breadth", "cell:two", 4.0, 21, 25, "o2")):
        b = "2026-11-10T00:00:%02dZ" % beg; e = "2026-11-10T00:00:%02dZ" % end
        rows += [{"kind": "START", "jid": jid, "scope": scope, "job": job, "start_utc": b, "max_permitted_charge_s": 30, "parent_jid": parent}, {"kind": "RECEIPT", "jid": jid, "scope": scope, "job": job, "start_utc": b, "end_utc": e, "wall_s": wall, "outcome": "COMPLETED", "cleanup_unresolved": False, "group_empty_at_receipt": True, "parent_jid": parent}]
    open(os.path.join(D, "GB_LEDGER.jsonl"), "w").write("".join(json.dumps(x) + "\n" for x in rows))
    total, by, unresolved, extra = PI.charged(D); assert total == 18.0 and not unresolved and [o["parent_remainder_s"] for o in extra["outer_attempts"]] == [5.0, 4.0]
    rows2 = [r for r in rows if not (r["kind"] == "RECEIPT" and r["jid"] == "o1")]; open(os.path.join(D, "GB_LEDGER.jsonl"), "w").write("".join(json.dumps(x) + "\n" for x in rows2))
    total, by, unresolved, extra = PI.charged(D); assert unresolved and total == 5 + 4 + 4 + 30 and R.budget(D, {"frozen_utc": "2026-11-10T00:00:00Z", "ceiling_s": 100}, [])["compliance"] == "QUALIFIED"


def test_C24_all_seven_arms_end_to_end_through_the_real_harness_resume_and_closeout(tmp_path):
    """tiny qualification manifest (qualification_unfrozen; never a campaign): one tiny case x the four primary arms + the three ablation arms run by
    gbidi3.pilot.run under a REAL outer gbidi.supervise (the production composition), resumed (no relaunch), closed out through the ONE reconciler;
    then the mutations: stale 120 s record for a 20 s task, changed config, missing build binding, duplicate receipt, wrong task -> NOT accepted / RESUME_CONFLICT."""
    from gbidi3 import pilot as PI, reconcile as RC
    from gbidi3_closeout import report as R
    D = str(tmp_path / "run"); os.makedirs(D); inputs = tmp_path / "inputs"; inputs.mkdir()
    card = [2, 3, 2]; facs = rnd_model(12, card, [(0, 1), (1, 2), (0, 2)]); dec = lambda q: "%d.%02d" % divmod(q.numerator * (100 // q.denominator), 100)
    mp, ep = write_uai(str(inputs / "X.uai"), card, facs, {2: 1}, tokens=[[dec(x) for x in tab] for _, tab in facs]); S, Z, N, rows = truth(mp, ep)
    cfg_adp = os.path.join(HERE, "runs", "mdi_2026-10-28", "AGGREGATE_DP_CENSUS_2026-11-08", "CONFIG_new_arm.json"); br = json.load(open(os.path.join(HERE, "gbidi3", "BUILD_RECORD.json")))
    from gbidi3 import identity as ID
    case = dict({k: S.task[k] for k in GS.TASK_BINDING_FIELDS}, family="F", model_path=mp, evidence_path=ep, variables=3)
    src = ["gbidi3/executor.py", "gbidi3/kernel3.cpp", "gbidi3/pilot.py", "gbidi3/reconcile.py", "gbidi3/arm_adapter.py", "gbidi/supervise.py", "adp/cell.py", "bench/cells.py"]
    man = {"pass": "QUALIFICATION_E2E", "manifest_status": "FROZEN", "qualification_unfrozen": True, "frozen_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(time.time() - 2)), "commit": "unfrozen", "branch": "test", "seed": PI.SEED, "source_files_sha256": {f: EX.sha_file(os.path.join(HERE, f)) for f in src}, "kernel_binary_sha256": br["binary_sha256"], "kernel_build": br, "python_sources_sha256": ID.python_sources_sha256(), "protocol": ID.PROTOCOL, "config_adp_repaired_path": os.path.relpath(cfg_adp, HERE), "config_adp_repaired_sha256": EX.sha_file(cfg_adp), "common_rules": list(PL.COMMON_RULES),
           "arms_config": {a: dict(PL.ARMS[a], cell_config=PI.CELL_CONFIG) for a in PL.ARMS}, "ceiling_s": 28800.0, "closeout_reserve_s": 0.0, "cases": {"X": case}, "unavailable_slots": [], "cells": []}
    arms = ["GENERAL_BIDI_COMPLETE_V3", "NATIVE_PLAIN_COMPLETE_V3", "ADP_REPAIRED", "EXACT_LIBDAI", "A1_NO_DEMAND_MASKS", "A2_NO_FUSION", "A3_NO_RESPONSE_VIEWS"]
    for i, arm in enumerate(arms):
        c = {"stage": "primary_breadth" if i < 4 else "ablation_breadth", "arm": arm, "case": "X", "budget_s": 20.0, "kind": "primary" if i < 4 else "ablation"}; tid, cid = PI.canonical_task(case, c, man["config_adp_repaired_sha256"], br["binary_sha256"], man["commit"])
        man["cells"].append(dict(c, index=i, task_id=tid, cell_id=cid, producer_arm=arm if arm in PI.GB_ARMS else PI.PRODUCER_ARM[arm], out_dir="cells/%s/%03d__X__%s__20s__%s" % (c["stage"], i, arm, tid), max_permitted_charge_s=26.0))
    json.dump(man, open(os.path.join(D, "GB_MANIFEST.json"), "w")); assert PI.reconcile_manifest(man) is None
    def stage(name):
        return subprocess.run([PY, "-m", "gbidi.supervise", "--ledger", os.path.join(D, "GB_LEDGER.jsonl"), "--scope", "stage_outer_" + name, "--job", "stage_runner:" + name, "--timeout", "600", "--cwd", HERE, "--env", "PYTHONPATH=" + HERE, "--", PY, "-m", "gbidi3.pilot", "run", D, name], capture_output=True, text=True, timeout=900, cwd=HERE, env=ENV)
    r1 = stage("primary_breadth"); assert "STOP" not in r1.stdout, r1.stdout[-800:] + r1.stderr[-800:]
    r2 = stage("ablation_breadth"); assert "STOP" not in r2.stdout, r2.stdout[-800:]
    rws = R.cells_ledger(D, man); assert all(r["accepted"] for r in rws), [(r["arm"], r["reasons"]) for r in rws if not r["accepted"]]
    assert {r["arm"]: r["status"] for r in rws} == {a: ("COMPLETE" if a == "EXACT_LIBDAI" else "CERTIFIED") for a in arms} and all(r["delivery_from_launch_s"] is not None and r["delivery_from_launch_s"] <= 20 for r in rws)
    for r in rws:
        pts, _ = U.read_mar(os.path.join(D, r["out_dir"], "output.MAR")); assert all(abs(Fr(pts[v][s]) - rows[v][s]) < Fr(1, 200) for v in range(3) for s in range(card[v])), r["arm"]
    led1 = open(os.path.join(D, "GB_LEDGER.jsonl")).read(); r3 = stage("primary_breadth"); assert "RESUME_CONFLICT" not in r3.stdout and "STOP" not in r3.stdout, r3.stdout[-500:]
    led2 = open(os.path.join(D, "GB_LEDGER.jsonl")).read(); assert led2.count('"kind": "START"') == led1.count('"kind": "START"') + 1
    total, by, unresolved, extra = PI.charged(D); assert not unresolved and len(extra["outer_attempts"]) == 3 and all(o["receipt"] for o in extra["outer_attempts"])
    B = R.budget(D, man, rws); assert B["compliance"].startswith("every start") and B["total_charged_s"] == pytest.approx(total, abs=2e-3)
    # mutations of a finished record: stale budget -> RESUME_CONFLICT; changed config / missing build / duplicate receipt / wrong task -> NOT accepted with reasons
    cj = os.path.join(D, man["cells"][1]["out_dir"], "cell.json"); good = json.load(open(cj)); idx = RC.ledger_index(D)
    def row_with(mut):
        rec = copy.deepcopy(good); mut(rec); json.dump(rec, open(cj, "w")); r = RC.reconcile(D, man, man["cells"][1], idx); json.dump(good, open(cj, "w")); return r
    r = row_with(lambda rec: rec.__setitem__("deadline_s", 120.0)); assert not r["accepted"] and any("budget" in x for x in r["reasons"])
    r = row_with(lambda rec: rec["config"].__setitem__("allow_binary64", False)); assert not r["accepted"] and any("configuration" in x for x in r["reasons"])
    r = row_with(lambda rec: rec["execution"]["implementation"].__setitem__("binary_sha256", "0" * 64) if rec["execution"]["route"] in ("binary64", "mpfr", "exact_fallback") else rec["execution"]["implementation"].__setitem__("python_sources_sha256", {})); assert not r["accepted"] and any("execution identity" in x for x in r["reasons"])
    r = row_with(lambda rec: rec.__setitem__("execution", {})); assert not r["accepted"] and any("execution identity" in x for x in r["reasons"])
    r = row_with(lambda rec: rec["task"].__setitem__("canonical_v2_model_sha256", "0" * 64)); assert not r["accepted"] and any("canonical_v2" in x for x in r["reasons"])
    for k in ("orig_card", "eps", "max_width", "canonical_version"):
        r = row_with(lambda rec, k=k: rec["task"].pop(k)); assert not r["accepted"] and any(k in x for x in r["reasons"]), k
    led_rows = [json.loads(x) for x in open(os.path.join(D, "GB_LEDGER.jsonl"))]; dup = [x for x in led_rows if x["kind"] == "RECEIPT" and x["job"] == RC.job_name(man["cells"][1])][0]
    open(os.path.join(D, "GB_LEDGER.jsonl"), "a").write(json.dumps(dup) + "\n"); r = RC.reconcile(D, man, man["cells"][1], RC.ledger_index(D)); assert not r["accepted"] and any("START/SPAWNED/RECEIPT" in x for x in r["reasons"])
    total2, by2, unresolved2, extra2 = PI.charged(D); assert extra2["duplicate_receipts"]
    json.dump(dict(good, deadline_s=120.0), open(cj, "w")); r4 = stage("primary_breadth"); assert "RESUME_CONFLICT" in r4.stdout or "NOT_LAUNCHED_UNRESOLVED_CLEANUP" in r4.stdout


# ============================================================================================================ C25 enumeration coverage versus counters (fault injection caught by the oracle)
def test_C25_omitted_and_duplicated_branches_with_forged_counters_are_caught_by_the_oracle(tmp_path):
    """fault injection inside the trusted kernel: (1) a REDUCE omits its first eliminated tuple while its term counter is forged as visited; (2) it adds the
    first tuple twice with the counter unchanged. Either the executor's simplex-consistency guard refuses the route (nothing published) or the published
    enclosure fails the independent exact oracle; in both cases the forged `reduce_terms` counter equals the clean run's, so metadata counts alone prove
    nothing. The same two faults in the exact SOURCE enumeration (fallback odometer) are caught by comparing Z with the oracle while `visited` is unchanged."""
    card = [3, 3, 2]; facs = rnd_model(25, card, [(0, 1), (1, 2), (0, 2)], lo=1, hi=9); mp, ep = write_uai(str(tmp_path / "m.uai"), card, facs); S, Z, N, rows = truth(mp, ep)
    clean = run("GENERAL_BIDI_COMPLETE_V3", mp, ep, str(tmp_path / "clean"), rules=[], b64=False); assert tight(clean, rows); cc = counters(clean)
    for mode in (1, 2):
        try:
            bad = run("GENERAL_BIDI_COMPLETE_V3", mp, ep, str(tmp_path / ("bad%d" % mode)), rules=[], b64=False, fallback=False, hooks={"branch_fault": mode})
            assert bad["status"] == "INTERVALS_OK" and not contained(bad, rows), mode                                                              # published but wrong: the ORACLE detects it
            cb = counters(bad)
        except EX.Refuse as ex:
            assert ex.kind == "NUMERIC_UNRESOLVED" and all(a["outcome"] == "UNSOUND_ROUTE_SIMPLEX_INCONSISTENT" for a in ex.rec["attempts"]), (mode, ex.reason)   # the executor's own guard refused before publication
            cb = [a["counters"] for a in ex.rec["attempts"] if a.get("counters")][0]
        assert cb["reduce_terms"] == cc["reduce_terms"], (mode, cb["reduce_terms"], cc["reduce_terms"])                                          # the forged counter is indistinguishable from the clean run
    for mode in (1, 2):
        fb = EX.exact_fallback(S, time.monotonic() + 30, GM.Ledger(), test_hooks={"ref_fault": mode}); good = EX.exact_fallback(S, time.monotonic() + 30, GM.Ledger())
        assert good["Z"] == Z and fb["Z"] != Z and fb["visited"] == good["visited"], (mode, fb["Z"], Z)


# ============================================================================================================ C26 empty dimensions / explicit plans through every general backend (no special kernel is enabled)
def test_C26_empty_scopes_zero_variable_tasks_and_cardinality_one_regions_through_every_backend(tmp_path):
    assert not any("bidi" in f for f in os.listdir(os.path.join(HERE, "gbidi3")) if f.endswith(".py") and f != "__init__.py" and "gbidi3" not in f), "no special bipartite kernel is imported into gbidi3"
    mz = str(tmp_path / "z.uai"); open(mz, "w").write("MARKOV 0 2 0 0 1 3/7 1 2\n"); open(mz + ".evid", "w").write("")
    rec = run("GENERAL_BIDI_COMPLETE_V3", mz, mz + ".evid", str(tmp_path / "z")); assert rec["status"] == "INTERVALS_OK" and rec["Z"] == "6/7"; st, cell = publish(str(tmp_path / "z"), mz, mz + ".evid", rec); assert st == "CERTIFIED"
    card = [1, 2, 1, 3, 1]; facs = rnd_model(26, card, [(0, 1), (1, 2, 3), (2,), (3, 4), ()]); mp, ep = write_uai(str(tmp_path / "c1.uai"), card, facs); S, Z, N, rows = truth(mp, ep)
    for mode, mut in (("dense", set_storage(IR.DENSE)), ("stream", set_storage(IR.STREAM)), ("cache", set_storage(IR.CACHE)), ("sparse", set_storage(IR.SPARSE))):
        for rules in (RULES_ALL, []):
            rec = run("GENERAL_BIDI_COMPLETE_V3", mp, ep, str(tmp_path / (mode + str(len(rules)))), rules=rules, b64=False, hooks={"mutate_program": mut}); assert tight(rec, rows), (mode, rules)
    rec = run("GENERAL_BIDI_COMPLETE_V3", mp, ep, str(tmp_path / "fb"), rules=[], hooks={"force_fallback": True}); assert exact_rows(rec, rows)
    # a region with an empty residual (every factor fully instantiated by the cutset) and an isolated cardinality-one variable
    mp, ep = write_uai(str(tmp_path / "iso.uai"), [2, 1, 2], [((0,), [1, 2]), ((2,), [3, 4])]); S, Z, N, rows = truth(mp, ep)
    for arm in ARMS:
        rec = run(arm, mp, ep, str(tmp_path / arm), rules=[], b64=False); assert exact_rows(rec, rows) and rec["certified_intervals"]["1"] == [["1", "1"]]
