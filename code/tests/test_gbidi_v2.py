"""Qualification controls for GENERAL_BIDI_V2 (actual entry points: gbidi.executor.execute / publish, gbidi.verify, the kernel, gbidi.cell, gbidi.pilot,
gbidi.supervise, gbidi_closeout). Every numerical check compares ALL original singleton numerators with an INDEPENDENT exact truth (the brute-force
oracle bidi.oracle, or a closed form). Every control named after a review finding ASSERTS THAT THE TARGETED TRANSITION FIRED (counters / provenance /
typed stop), then checks truth and failure behaviour -- a no-op pass is a failure here. Finding keys: F1..F6 (first review), R2-01..R2-10 (second)."""
from __future__ import annotations
import sys, os, json, time, random, subprocess, ctypes, copy, signal, zlib
sys.set_int_max_str_digits(0)
HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__))); sys.path.insert(0, HERE)
from fractions import Fraction as Fr
import pytest
from gbidi import executor as EX, plan as PL, source as GS, validate as GV
from adp.engine import View
from bidi import oracle as OR
from ext import uai as U

PY = sys.executable; ENV = dict(os.environ, PYTHONPATH=HERE)
ARMS = list(EX.ARMS)


def write_uai(path, card, factors, ev=None, tokens=None):
    lines = ["MARKOV", str(len(card)), " ".join(map(str, card)), str(len(factors))] + ["%d %s" % (len(sc), " ".join(map(str, sc))) for sc, _ in factors]
    for i, (_, tab) in enumerate(factors):
        lines.append("%d %s" % (len(tab), " ".join(tokens[i] if tokens and tokens[i] else ["%d/%d" % (Fr(x).numerator, Fr(x).denominator) for x in tab])))
    open(path, "w").write("\n".join(lines) + "\n"); ev = ev or {}
    open(path + ".evid", "w").write("%d %s\n" % (len(ev), " ".join("%d %d" % (v, s) for v, s in ev.items()))); return path, path + ".evid"


def rnd_model(seed, card, scopes, zeros=0.0, lo=1, hi=99):
    r = random.Random(seed); facs = []
    for sc in scopes:
        n = 1
        for v in sc:
            n *= card[v]
        facs.append((tuple(sc), [Fr(0) if r.random() < zeros else Fr(r.randint(lo, hi), 100) for _ in range(n)]))
    return facs


def run(arm, mp, ep, out, b64=True, budget=60, hooks=None, rules=None, fallback=True):
    cfg = {"budget_s": budget, "allow_binary64": b64, "reference_fallback": fallback}
    if rules is not None:
        cfg["rules"] = rules
    return EX.execute(arm, mp, ep, out, time.monotonic() + budget, cfg, test_hooks=hooks)


def truth_rows(model, ev):
    Z, N = OR.brute(model, ev); return Z, ({v: [N[v][s] / Z for s in range(model.card[v])] for v in range(model.nvars)} if Z else None)


def contained(rec, truth):
    return all(Fr(a) <= truth[int(v)][s] <= Fr(b) for v, row in rec["certified_intervals"].items() for s, (a, b) in enumerate(row))


def truth_inside(rec, model, ev):
    Z, T = truth_rows(model, ev)
    if Z == 0:
        return rec["status"] == "ZERO_EVIDENCE_PROVED"
    assert rec["status"] == "INTERVALS_OK", rec.get("status")
    return all(len(rec["certified_intervals"][str(v)]) == model.card[v] for v in range(model.nvars)) and contained(rec, T)


def publish(out, mp, ep, rec):
    cell = {"phases_s": {}}; st = EX.publish(out, mp, ep, rec, cell, time.monotonic() + 30); return st, cell


def chain_exact(n, pair, unary_at, unary):
    pair = [[Fr(pair[0]), Fr(pair[1])], [Fr(pair[2]), Fr(pair[3])]]; un = [[Fr(1), Fr(1)] for _ in range(n)]; un[unary_at] = [Fr(unary[0]), Fr(unary[1])]
    fwd = [None] * n; fwd[0] = [un[0][a] for a in range(2)]
    for i in range(1, n):
        fwd[i] = [un[i][b] * sum(fwd[i - 1][a] * pair[a][b] for a in range(2)) for b in range(2)]
    bwd = [None] * n; bwd[n - 1] = [Fr(1), Fr(1)]
    for i in range(n - 2, -1, -1):
        bwd[i] = [sum(pair[a][b] * un[i + 1][b] * bwd[i + 1][b] for b in range(2)) for a in range(2)]
    Z = sum(fwd[n - 1]); return {v: [fwd[v][a] * bwd[v][a] / Z for a in range(2)] for v in range(n)}


def star_model(path, n):
    lines = ["MARKOV", str(n), " ".join(["2"] * n), str(n - 1)] + ["2 0 %d" % v for v in range(1, n)] + ["4 1 2 3 4"] * (n - 1); open(path, "w").write("\n".join(lines) + "\n"); open(path + ".evid", "w").write("0\n")
    Z = 3 ** (n - 1) + 7 ** (n - 1); truth = {0: [Fr(3 ** (n - 1), Z), Fr(7 ** (n - 1), Z)]}
    for v in range(1, n):
        truth[v] = [Fr(3 ** (n - 2) + 3 * 7 ** (n - 2), Z), Fr(2 * 3 ** (n - 2) + 4 * 7 ** (n - 2), Z)]
    return path, path + ".evid", truth


# ============================================================================================================ generality: every input class x every arm x both routes
CASES = {"nonbinary_chain": ([3, 2, 4, 3], [(0, 1), (1, 2), (2, 3), (3,)], 0.0, {}), "high_arity": ([2, 3, 2, 2], [(0, 1, 2), (1, 2, 3), (0, 3)], 0.0, {}), "odd_cycle_nonbinary": ([3, 3, 3], [(0, 1), (1, 2), (2, 0), (0,)], 0.0, {}),
         "zeros_cycle": ([2, 3, 2, 2], [(0, 1), (1, 2), (2, 3), (3, 0), (1, 3)], 0.3, {}), "evidence_high_arity": ([2, 2, 3, 2, 2], [(0, 1, 2), (2, 3, 4), (0, 4), (1,)], 0.1, {1: 1, 4: 0}), "disconnected_isolated": ([2, 3, 2, 2, 3], [(0, 1), (2, 3), (2,)], 0.0, {}),
         "duplicate_occurrences": ([2, 2], [(0,), (0,), (0, 1), (0, 1)], 0.0, {}), "scalar_and_unary_only": ([2, 3], [(), (0,), (1,), ()], 0.0, {}), "dense_grid_like": ([2] * 6, [(0, 1), (1, 2), (3, 4), (4, 5), (0, 3), (1, 4), (2, 5)], 0.0, {}), "kite_evidence_zero": ([2, 2, 2, 2], [(0, 1), (0, 2), (1, 2), (2, 3), (3,)], 0.4, {3: 0})}


@pytest.mark.parametrize("name", list(CASES))
@pytest.mark.parametrize("arm", ARMS)
def test_every_arm_encloses_exact_truth_on_every_input_class(tmp_path, name, arm):
    card, scopes, zeros, ev = CASES[name]; facs = rnd_model(zlib.crc32(name.encode()) % 1000, card, scopes, zeros); mp, ep = write_uai(str(tmp_path / "m.uai"), card, facs, ev); model = U.read_model(mp)
    for b64 in (True, False):
        rec = run(arm, mp, ep, str(tmp_path / ("%s_%s" % (arm, b64))), b64=b64); assert truth_inside(rec, model, ev), (name, arm, b64)
        if rec["status"] == "INTERVALS_OK" and rec.get("plan", {}).get("nodes"):
            assert rec["plan_validation"]["status"] == "VALID"
    rec = run(arm, mp, ep, str(tmp_path / (arm + "_raw")), b64=True, rules=[]); assert truth_inside(rec, model, ev), (name, arm, "rules=[]")   # the kernel path with nothing reduced away


# ============================================================================================================ F1: binary64 labels are the whole-execution proof
def test_F1_streamed_chain_binary64_contains_truth_with_kernel_labels(tmp_path, monkeypatch):
    """the reviewer's 22-variable near-unit chain: the planner's own memory downgrades stream 16 nodes; the old K_acc=4 bound gave CERTIFIED intervals
    EXCLUDING truth. Now the kernel tracks exact labels (E_N ~ 6.6e4 here) and the enclosure contains [49/100, 51/100]; delivered intervals too."""
    n = 22; b = "1.000000000000000001"; tgt = 5
    mp, ep = write_uai(str(tmp_path / "c.uai"), [2] * n, [((tgt,), ["0.49", "0.51"])] + [((i, i + 1), ["1", b, b, "1"]) for i in range(n - 1)], tokens=[["0.49", "0.51"]] + [["1", b, b, "1"]] * (n - 1))
    truth = chain_exact(n, ["1", b, b, "1"], tgt, ["0.49", "0.51"]); assert truth[tgt] == [Fr(49, 100), Fr(51, 100)]
    monkeypatch.setattr(PL, "CAPS", dict(PL.CAPS, value_cache=1150))
    rec = run("NATIVE_PLAIN_V2", mp, ep, str(tmp_path / "o"), b64=True, rules=list(PL.COMMON_RULES))
    assert rec["route"] == "binary64" and sum(1 for nd in rec["plan"]["nodes"] if nd["downgrade"]) >= 10, "the transition (memory downgrade -> streaming) must fire"
    att = rec["attempts"][-1]; assert att["labels"]["E_N_max"] > 10 ** 4 and att["counters"]["stream_reevals"] > 5 * 10 ** 4 and att["counters"]["max_frame_depth"] >= 15
    assert contained(rec, truth)
    st, cell = publish(str(tmp_path / "o"), mp, ep, rec); assert st == "CERTIFIED" and cell["point_check"]["status"] == "POINT_VERIFIED"
    deliv = {str(r["var"]): r["intervals"] for r in json.load(open(tmp_path / "o" / "intervals.json"))["intervals"]}; assert contained({"certified_intervals": deliv}, truth)
    m = run("NATIVE_PLAIN_V2", mp, ep, str(tmp_path / "m"), b64=False, rules=list(PL.COMMON_RULES)); assert contained(m, truth) and m["route"] == "mpfr"      # rigorous route on the SAME streamed schedule under the same cap
    assert sum(1 for nd in m["plan"]["nodes"] if nd["downgrade"]) >= 10 and m["attempts"][-1]["counters"]["used_values_bytes"] <= 1150
    f = EX.execute("NATIVE_PLAIN_V2", mp, ep, str(tmp_path / "f"), time.monotonic() + 60, {"budget_s": 60, "allow_binary64": False, "rules": list(PL.COMMON_RULES)}, test_hooks={"force_stream": True}); assert contained(f, truth)
    for v, row in rec["certified_intervals"].items():
        for s, (a, x) in enumerate(row):
            ma, mb = [Fr(t) for t in m["certified_intervals"][v][s]]; assert not (Fr(x) < ma or Fr(a) > mb)


def test_F1_label_void_or_range_fault_selects_the_rigorous_route(tmp_path):
    """leaves near the binary64 range edge: the kernel's per-operation range check fires -> typed RANGE -> MPFR; and a forged label budget (delta >= 1/2) is refused."""
    big = ["%d" % (2 ** 500)] * 4; mp, ep = write_uai(str(tmp_path / "r.uai"), [2, 2, 2], [((0, 1), [Fr(1)] * 4), ((1, 2), [Fr(1)] * 4), ((0, 2), [Fr(1)] * 4)], tokens=[big, big, big]); model = U.read_model(mp)
    rec = run("NATIVE_PLAIN_V2", mp, ep, str(tmp_path / "r"), b64=True, rules=[])
    assert rec["route"] == "mpfr" and truth_inside(rec, model, {}) and (rec["binary64_admission"]["checks"][-1].startswith("range envelope outside") or any(a.get("refused", {}).get("kind") == "RANGE" for a in rec["attempts"]))


# ============================================================================================================ F2 / SB-01: the planner is untrusted
def test_F2_mutated_proposals_are_rejected_before_execution_and_unchanged_certifies(tmp_path):
    mp, ep = write_uai(str(tmp_path / "t.uai"), [2, 2], [((0, 1), [1, 2, 3, 4]), ((0, 1), [1, 1, 1, 2])]); model = U.read_model(mp); Z, T = truth_rows(model, {}); assert Z == 14
    orig = PL.plan
    def mutant(mode):
        def proposed(R, cfg, deadline=None, caps=None, **kw):
            P, table = orig(R, cfg, deadline, caps, **kw)
            if mode == "omit_factor":
                nd = next(n for n in P.nodes if sum(k == "F" for k, r in n.inputs) >= 2); nd.inputs.pop(next(i for i in reversed(range(len(nd.inputs))) if nd.inputs[i][0] == "F"))
            elif mode == "duplicate_factor":
                nd = P.nodes[0]; nd.inputs.append(nd.inputs[0])
            elif mode == "forge_view":
                nd = next(n for n in P.nodes if n.scope); w = nd.scope[0]; nd.views[w] = View([0, 0], [0], [Fr(1), Fr(1)]); nd.radix = tuple(len(nd.views[x].reps) for x in nd.scope); nd.core_entries = 1; nd.demand = "FULL"; nd._support_out = None
            elif mode == "forge_ratio":
                nd = next(n for n in P.nodes if n.scope); w = nd.scope[0]; nd.views[w] = View([0, 0], [0], [Fr(1), Fr(5)]); nd.radix = tuple(len(nd.views[x].reps) for x in nd.scope); nd.core_entries = 1; nd.demand = "FULL"; nd._support_out = None
            elif mode == "drop_consumer_edge":
                nd = next(n for n in P.nodes if any(k == "M" for k, r in n.inputs)); nd.inputs = [x for x in nd.inputs if x[0] != "M"]
            elif mode == "wrong_scope":
                nd = next(n for n in P.nodes if n.scope); nd.scope = (); nd.radix = (); nd.core_entries = 1; nd.views = {}
            return P, table
        return proposed
    for mode in ("omit_factor", "duplicate_factor", "forge_view", "forge_ratio", "drop_consumer_edge", "wrong_scope"):
        PL.plan = mutant(mode)
        try:
            with pytest.raises(EX.Refuse) as e:
                run("GENERAL_BIDI_V2", mp, ep, str(tmp_path / mode), b64=False)
            assert e.value.kind == "REJECTED" and "validation" in e.value.reason, (mode, e.value.reason)
            assert not os.path.exists(tmp_path / mode / "output.MAR")
        finally:
            PL.plan = orig
    rec = run("GENERAL_BIDI_V2", mp, ep, str(tmp_path / "ok"), b64=False); assert contained(rec, T); st, cell = publish(str(tmp_path / "ok"), mp, ep, rec); assert st == "CERTIFIED"


def test_F2_wrong_storage_set_changes_work_not_the_answer(tmp_path):
    """a forged stored set (a STORAGE decision) is served by streaming: reads_outside_demand > 0 and the answer is still exact"""
    mp, ep = write_uai(str(tmp_path / "t.uai"), [2, 3, 2], rnd_model(5, [2, 3, 2], [(0, 1), (1, 2), (0, 2)])); model = U.read_model(mp); Z, T = truth_rows(model, {}); orig = PL.plan
    def proposed(R, cfg, deadline=None, caps=None, **kw):
        P, table = orig(R, cfg, deadline, caps, **kw); nd = next(n for n in P.nodes if n.scope and n.materialize); nd.demand = [0]; nd.demand_prov = "FORGED"; return P, table
    PL.plan = proposed
    try:
        rec = run("A2_NO_FUSION", mp, ep, str(tmp_path / "f"), b64=False, rules=[])
    finally:
        PL.plan = orig
    assert rec["attempts"][-1]["counters"]["reads_outside_demand"] > 0 and contained(rec, T)


def test_F2_validator_accepts_every_normal_plan_and_detects_each_corruption_class(tmp_path):
    card = [2, 3, 2, 2]; facs = rnd_model(31, card, [(0, 1), (1, 2), (2, 3), (0, 3), (1, 3)], zeros=0.2); mp, ep = write_uai(str(tmp_path / "v.uai"), card, facs)
    from adp import source as SRC
    m = U.read_model(mp); R = SRC.Reduced(EX._ModelAdapter(m), {}); R.reduce([], deadline=None); T = GV.TrustedReduced(R); P, _ = PL.plan(R, dict(EX.ARMS["GENERAL_BIDI_V2"], bytes_per_entry=96)); assert GV.validate(P, T).record["status"] == "VALID" and T.unchanged(R)
    nd = next(n for n in P.nodes if n.scope); w = nd.scope[0]; v = nd.views[w]; bad = View(list(v.cls), list(v.reps), [q * 2 if i == 0 else q for i, q in enumerate(v.ratio)])
    old = nd.views[w]; nd.views[w] = bad
    with pytest.raises(GV.Invalid):
        GV.validate(P, T)
    nd.views[w] = old; assert GV.validate(P, T).record["status"] == "VALID"
    R.factors[0].table[0] += 1; assert not T.unchanged(R)                                                      # an in-place mutation of the live object is detected


# ============================================================================================================ F3 / R2-05: resource categories, exceptions, frames
@pytest.mark.parametrize("kind", ["frames_scratch_publication", "pending_adjoints", "source_ir_maps_output", "reverse_pinned", "value_cache"])
def test_F3_every_category_cap_is_enforced_with_a_typed_memory_stop(tmp_path, monkeypatch, kind):
    """ORDINARY FULL-storage plan (no forged LIST): a one-byte cap on ANY category stops the native route with a typed MEMORY stop. The exact
    fallback is capped by the SAME categories (values: tables + accumulators; scratch: IR + odometer + product + export): with a one-byte value or
    scratch cap it cannot run either and the cell ends in a typed RESOURCE_STOP with its diagnostics; pending / reverse / index caps do not bind the
    fallback, which then completes exactly."""
    mp, ep = write_uai(str(tmp_path / "t.uai"), [2, 2], [((0, 1), [1, 2, 3, 4]), ((0,), [2, 1])]); model = U.read_model(mp); Z, T = truth_rows(model, {})
    monkeypatch.setattr(PL, "CAPS", dict(PL.CAPS, **{kind: 1}))
    if kind in ("pending_adjoints", "reverse_pinned", "source_ir_maps_output"):
        rec = run("NATIVE_PLAIN_V2", mp, ep, str(tmp_path / kind), b64=False, rules=[])
        assert rec["attempts"][0]["stop"] == "MEMORY" and rec.get("stop", {}).get("kind") == "MEMORY", (kind, rec.get("stop"), rec["attempts"])
        assert rec["precision"] == "exact_integer_reference" and contained(rec, T) and rec["reference_fallback"]["used_bytes"]["values"] > 0
    else:
        with pytest.raises(EX.Refuse) as e:
            run("NATIVE_PLAIN_V2", mp, ep, str(tmp_path / kind), b64=False, rules=[])
        r = e.value.rec; assert e.value.kind == "RESOURCE_STOP" and r["attempts"][0]["stop"] == "MEMORY" and r["stop"]["phase"] == "reference_fallback" and r["stop"]["kind"] == "MEMORY", (kind, r.get("stop"))
        assert "diagnostic_record.json" in os.listdir(tmp_path / kind) and not os.path.exists(tmp_path / kind / "checked_record.json")


def test_F3_ordinary_full_plan_index_category_is_charged(tmp_path, monkeypatch):
    """the parsed IR of an ordinary FULL plan is reserved in the source/IR category before parsing: a one-byte cap stops at create (V1/V2 reported 0 index bytes)"""
    mp, ep = write_uai(str(tmp_path / "t.uai"), [2, 2], [((0, 1), [1, 2, 3, 4]), ((0,), [2, 1])]); model = U.read_model(mp); Z, T = truth_rows(model, {})
    rec = run("NATIVE_PLAIN_V2", mp, ep, str(tmp_path / "n"), b64=False, rules=[]); assert rec["attempts"][-1]["counters"]["used_index_bytes"] > 0 and contained(rec, T)
    monkeypatch.setattr(PL, "CAPS", dict(PL.CAPS, source_ir_maps_output=1)); rec = run("NATIVE_PLAIN_V2", mp, ep, str(tmp_path / "c"), b64=False, rules=[])
    assert rec["attempts"][0]["stop"] == "MEMORY" and rec["attempts"][0]["stop_phase"] == "create" and rec["precision"] == "exact_integer_reference" and contained(rec, T)


def test_F3_fallback_reserves_tables_accumulators_and_export(tmp_path, monkeypatch):
    """the exact fallback's own reservations: value category = tables + accumulators (bound), scratch = IR + odometer + product + export (exact size)"""
    from gbidi import validate as GV
    card = [3, 2, 2]; facs = rnd_model(5, card, [(0, 1), (1, 2), (0, 2)], zeros=0.2); mp, ep = write_uai(str(tmp_path / "r.uai"), card, facs); model = U.read_model(mp)
    from adp import source as SRC
    R = SRC.Reduced(EX._ModelAdapter(model), {}); R.reduce([], deadline=time.monotonic() + 1); T = GV.TrustedReduced(R)
    fb = EX.reference_stream(T, time.monotonic() + 10, dict(PL.CAPS)); assert fb["status"] == "COMPLETE" and fb["used_bytes"]["values"] > 0 and fb["used_bytes"]["export"] > 0
    fb2 = EX.reference_stream(T, time.monotonic() + 10, dict(PL.CAPS, value_cache=fb["used_bytes"]["values"] - 1)); assert fb2["status"] == "MEMORY"
    fb3 = EX.reference_stream(T, time.monotonic() + 10, dict(PL.CAPS, frames_scratch_publication=fb["used_bytes"]["scratch"] + fb["used_bytes"]["export"] - 1)); assert fb3["status"] == "MEMORY"


def test_R2_05_bad_alloc_is_a_typed_memory_stop_not_a_process_abort(tmp_path):
    mp, ep = write_uai(str(tmp_path / "t.uai"), [2, 2], [((0, 1), [1, 2, 3, 4])]); model = U.read_model(mp); Z, T = truth_rows(model, {}); L = EX.Lib.get(); L.gb_test_inject_bad_alloc(1)
    try:
        rec = run("NATIVE_PLAIN_V2", mp, ep, str(tmp_path / "b"), b64=False, rules=[])
    finally:
        L.gb_test_inject_bad_alloc(0)
    assert rec["attempts"][0]["stop"] == "MEMORY" and rec["precision"] == "exact_integer_reference" and contained(rec, T)


def test_R2_04_deep_streamed_chain_runs_on_explicit_frames_under_the_default_stack(tmp_path):
    """the reviewer's 50,000-node cardinality-1 chain segfaulted the recursive kernel under an 8 MiB stack. DETERMINISTIC activation: the qualification
    hook forces every non-root node to be streamed (a legal storage choice; the validator still checks the plan), so frame depth = chain length on
    every platform regardless of the optional discovery clock."""
    child = tmp_path / "child.py"; n = 50000; mp = str(tmp_path / "chain.uai")
    open(mp, "w").write("\n".join(["MARKOV", str(n), " ".join(["1"] * n), str(n - 1)] + ["2 %d %d" % (i, i + 1) for i in range(n - 1)] + ["1 1"] * (n - 1)) + "\n"); open(mp + ".evid", "w").write("0\n")
    child.write_text("import sys,json,time,resource; sys.path.insert(0,%r); sys.set_int_max_str_digits(0)\nfrom gbidi import executor as E\nr=E.execute('GENERAL_BIDI_V2',%r,%r,%r,time.monotonic()+90,{'budget_s':90,'allow_binary64':False,'reference_fallback':False,'rules':[]},test_hooks={'force_stream':True})\nprint(json.dumps({'status':r['status'],'depth':r['attempts'][-1]['counters']['max_frame_depth'],'fused':r['plan']['totals']['fused'],'stack':resource.getrlimit(resource.RLIMIT_STACK)[0],'valid':r['plan_validation']['status'],'rows_one':all(a=='1' and b=='1' for row in r['certified_intervals'].values() for a,b in row)}))\n" % (HERE, mp, mp + ".evid", str(tmp_path / "out")))
    r = subprocess.run([PY, str(child)], capture_output=True, text=True, timeout=300, env=ENV); assert r.returncode == 0, r.stderr[-500:]
    o = json.loads(r.stdout.strip().splitlines()[-1]); assert o["status"] == "INTERVALS_OK" and o["depth"] == n and o["fused"] == n - 1 and o["valid"] == "VALID" and o["rows_one"] and o["stack"] <= 16 << 20


def test_R2_04_policy_observation_deep_chain_without_forcing(tmp_path):
    """the SAME source under the normal policy: whatever the optional clock decides, the answer is exact and typed (a policy observation, not the depth control)"""
    n = 5000; mp = str(tmp_path / "chain.uai"); open(mp, "w").write("\n".join(["MARKOV", str(n), " ".join(["1"] * n), str(n - 1)] + ["2 %d %d" % (i, i + 1) for i in range(n - 1)] + ["1 1"] * (n - 1)) + "\n"); open(mp + ".evid", "w").write("0\n")
    rec = run("GENERAL_BIDI_V2", mp, mp + ".evid", str(tmp_path / "o"), b64=False, rules=[], fallback=False); assert rec["status"] == "INTERVALS_OK" and all(a == "1" == b for row in rec["certified_intervals"].values() for a, b in row) and rec["plan_validation"]["status"] == "VALID"


def test_R2_05_source_free_bucket_polls_the_deadline():
    L = EX.Lib.get(); c = ctypes; n = 100000; prog = [0, 1, 0, n, 0, 0, 1, -1, 1, 0, 0, 0]
    a = (c.c_int64 * len(prog))(*prog); qs = (c.c_char_p * 1)(b"1/1"); dbl = (c.c_double * 1)(1.0); caps = (c.c_uint64 * 5)(2 << 30, 2 << 30, 1 << 30, 512 << 20, 512 << 20); err = c.c_int(0)
    h = L.gb_create(1, 53, a, len(prog), qs, dbl, 0, 0, caps, 0.0, c.byref(err)); assert h
    st = L.gb_forward(h); cnt = (c.c_uint64 * 32)(); L.gb_counters(h, cnt); L.gb_destroy(h)
    assert st == 1 and cnt[15] >= 1 and cnt[0] < n, (st, cnt[0], cnt[15])


def test_frame_scratch_cap_stops_a_deep_stream_typed(tmp_path, monkeypatch):
    n = 2000; mp = str(tmp_path / "c.uai"); open(mp, "w").write("\n".join(["MARKOV", str(n), " ".join(["1"] * n), str(n - 1)] + ["2 %d %d" % (i, i + 1) for i in range(n - 1)] + ["1 1"] * (n - 1)) + "\n"); open(mp + ".evid", "w").write("0\n")
    monkeypatch.setattr(PL, "CAPS", dict(PL.CAPS, frames_scratch_publication=200_000))
    with pytest.raises(EX.Refuse) as e:
        run("GENERAL_BIDI_V2", mp, mp + ".evid", str(tmp_path / "o"), b64=False, rules=[], fallback=False)
    assert e.value.kind == "RESOURCE_STOP" and "MEMORY" in e.value.reason and e.value.rec["attempts"][-1]["stop"] == "MEMORY"


# ============================================================================================================ F4: fusion price = complete all-query path
def test_F4_fusion_price_counts_reverse_regeneration_and_matches_executed_work(tmp_path):
    mp, ep = write_uai(str(tmp_path / "t.uai"), [2, 2], [((0, 1), [1, 2, 3, 5]), ((1,), [7, 11])]); model = U.read_model(mp); Z, T = truth_rows(model, {}); assert Z == 105
    on = run("GENERAL_BIDI_V2", mp, ep, str(tmp_path / "on"), b64=False, rules=[], fallback=False); off = run("A2_NO_FUSION", mp, ep, str(tmp_path / "off"), b64=False, rules=[], fallback=False)
    assert contained(on, T) and contained(off, T) and on["plan"]["totals"]["fused"] == 1 and off["plan"]["totals"]["fused"] == 0
    price = next(nd["cost"]["fusion_price"] for nd in on["plan"]["nodes"] if nd["cost"].get("fusion_price"))
    assert price["fused"] != price["stored"], "the two alternatives must be priced differently (V1 reported equal proxies 52 / 52)"
    con, coff = on["attempts"][-1]["counters"], off["attempts"][-1]["counters"]
    assert con["primal_rows"] > coff["primal_rows"] and con["stream_reevals"] > 0 and coff["stream_reevals"] == 0          # fusion really regenerates rows
    assert on["plan"]["totals"]["cold_work_proxy"] <= off["plan"]["totals"]["cold_work_proxy"]                              # the chosen option is the cheaper one BY THE PRICE
    assert con["mults"] <= coff["mults"] + 2                                                                                 # and the executed arithmetic agrees within the root constant


def test_F4_many_read_child_is_not_fused_and_bijective_child_is(tmp_path):
    from adp import source as SRC
    card = [2] * 9; facs = [((0, 1), [Fr(1), Fr(2), Fr(3), Fr(4)]), ((1, 2, 3, 4, 5, 6, 7, 8), [Fr(i % 5 + 1) for i in range(256)])]; mp, ep = write_uai(str(tmp_path / "m.uai"), card, facs)
    m = U.read_model(mp); R = SRC.Reduced(EX._ModelAdapter(m), {}); R.reduce([], deadline=None); P, _ = PL.plan(R, dict(EX.ARMS["GENERAL_BIDI_V2"], bytes_per_entry=96)); n0 = next(nd for nd in P.nodes if nd.x == 0); assert not n0.fused and P.mechanisms["fusion"]["edges_declined_by_policy"] >= 1
    card = [2] * 4; facs = rnd_model(1, card, [(0, 1), (1, 2), (2, 3)]); mp, ep = write_uai(str(tmp_path / "c.uai"), card, facs)
    m = U.read_model(mp); R = SRC.Reduced(EX._ModelAdapter(m), {}); R.reduce([], deadline=None); P, _ = PL.plan(R, dict(EX.ARMS["GENERAL_BIDI_V2"], bytes_per_entry=96)); assert P.totals()["fused"] >= 1


# ============================================================================================================ F5: diagnostics survive every typed stop
def test_F5_deadline_memory_and_rejection_keep_plan_attempts_counters_and_diagnostic_file(tmp_path, monkeypatch):
    n = 18; card = [2] * n; facs = rnd_model(9, card, [(i, j) for i in range(n) for j in range(i + 1, n)]); mp, ep = write_uai(str(tmp_path / "dl.uai"), card, facs)
    with pytest.raises(EX.Refuse) as e:
        EX.execute("NATIVE_PLAIN_V2", mp, ep, str(tmp_path / "dl"), time.monotonic() + 0.3, {"budget_s": 0.3, "allow_binary64": False, "reference_fallback": True, "rules": []})
    r = e.value.rec; assert e.value.kind == "RESOURCE_STOP" and r["plan"]["totals"]["nodes"] == 18 and r["attempts"][-1]["stop"] == "DEADLINE" and r["attempts"][-1]["counters"]["primal_rows"] > 0 and r["plan_validation"]["status"] == "VALID"
    d = json.load(open(tmp_path / "dl" / "diagnostic_record.json")); assert d["NOTE"].startswith("NONCERTIFYING") and d["status"] == "RESOURCE_STOP" and d["attempts"][-1]["counters"]["primal_rows"] == r["attempts"][-1]["counters"]["primal_rows"]
    assert not os.path.exists(tmp_path / "dl" / "checked_record.json")
    out = str(tmp_path / "cell"); subprocess.run([PY, "-m", "gbidi.cell", "NATIVE_PLAIN_V2", mp, ep, out, "0.5", json.dumps({"rules": [], "allow_binary64": False})], cwd=HERE, env=ENV, capture_output=True, timeout=120)
    c = json.load(open(os.path.join(out, "cell.json"))); assert c["status"] == "RESOURCE_STOP" and c["diagnostic"]["attempts"][-1]["counters"]["primal_rows"] > 0 and c["diagnostic"]["plan"]["totals"]["nodes"] == 18
    p = json.load(open(os.path.join(out, "progress.json"))); assert "live" in p and p["NOTE"].startswith("NONCERTIFYING")


# ============================================================================================================ F6: fixtures that activate what they name
def test_F6_split_root_deltas_with_eviction_on_a_model_with_non_root_stored_values(tmp_path):
    """m = lambda0 + 3 lambda1 realised with a NON-root stored node (chain 0-1-2): the root delta is injected as 2/5 then 3/5 with every stored
    non-root value zeroed and regenerated between them; Z = 20, N = (5, 15) scaled; the eviction loop must actually regenerate values."""
    mp, ep = write_uai(str(tmp_path / "m.uai"), [2, 2, 2], [((0,), [1, 3]), ((0, 1), [1, 1, 1, 1]), ((1, 2), [1, 1, 1, 1]), ((), [5])]); model = U.read_model(mp); Z, T = truth_rows(model, {})
    rec = run("A2_NO_FUSION", mp, ep, str(tmp_path / "s"), b64=False, hooks={"split_root": ("2/5", "3/5", True)}, rules=[])
    c = rec["attempts"][-1]["counters"]; stored_nonroot = sum(nd["cost"]["entries"] for nd in rec["plan"]["nodes"] if nd["materialize"] and nd["consumer"] is not None)
    assert stored_nonroot >= 2 and c["slots_drained"] >= 2 and c["value_frames"] >= c["entries_stored_planned"] + stored_nonroot, c   # regeneration happened
    assert contained(rec, T) and Fr(rec["certified_intervals"]["0"][0][1]) - Fr(rec["certified_intervals"]["0"][0][0]) < Fr(1, 10 ** 12)
    rec2 = run("A2_NO_FUSION", mp, ep, str(tmp_path / "s2"), b64=False, rules=[]); assert contained(rec2, T)


def test_F6_response_views_fire_on_a_nonbipartite_nonbinary_model_and_reduce_core_volume(tmp_path):
    """odd cycle 0-1-2 (NONbipartite), cardinalities [2,3,2]. Bucket of 0 (inputs f(0,1), f(2,0); scope {1,2}): along axis 1 the only input containing
    variable 1 is f(0,1), whose rows for states 0 and 1 of variable 1 are proportional ((1,2) and (2,4)) while state 2 ((5,7)) is not -> the response
    view stores 2 classes for 3 raw states (core 4 instead of 6). f(1,2) is NOT proportional along variable 1, so the shared quotient rule cannot
    absorb it (rules=[] here anyway); the raw marker of variable 1 stays outside the view (it is eliminated later, in its own bucket)."""
    tab01 = [Fr(x) for x in [1, 2, 5, 2, 4, 7]]; tab12 = [Fr(x) for x in [1, 2, 3, 5, 4, 1]]; tab20 = [Fr(x) for x in [1, 2, 3, 4]]
    mp, ep = write_uai(str(tmp_path / "v.uai"), [2, 3, 2], [((0, 1), tab01), ((1, 2), tab12), ((2, 0), tab20)]); model = U.read_model(mp); Z, T = truth_rows(model, {})
    on = run("GENERAL_BIDI_V2", mp, ep, str(tmp_path / "on"), b64=False, rules=[]); off = run("A3_NO_RESPONSE_VIEWS", mp, ep, str(tmp_path / "off"), b64=False, rules=[])
    assert contained(on, T) and contained(off, T)
    assert on["mechanisms"]["views"]["compressed_axes"] >= 1 and any(p == "COMPRESSED" for nd in on["plan"]["nodes"] for p in nd["view_prov"].values())
    assert on["plan"]["totals"]["planned_core_entries"] < off["plan"]["totals"]["planned_core_entries"] and off["mechanisms"]["views"]["state"] == "DISABLED"
    assert on["plan_validation"]["entrywise_checks"] > 0                                                    # the validator actually re-proved the view identity


def test_F6_demand_restriction_fires_and_reduces_stored_entries(tmp_path):
    facs = [((0, 1), [Fr(x) for x in [1, 2, 3, 4, 5, 6]]), ((1, 2), [Fr(x) for x in [0, 1, 2, 3, 4, 0]]), ((0, 2), [Fr(x) for x in [1, 2, 3, 1]]), ((2,), [Fr(1), Fr(3)])]
    mp, ep = write_uai(str(tmp_path / "d.uai"), [2, 3, 2], facs); model = U.read_model(mp); Z, T = truth_rows(model, {})
    on = run("A2_NO_FUSION", mp, ep, str(tmp_path / "on"), b64=False, rules=[]); off = run("NATIVE_PLAIN_V2", mp, ep, str(tmp_path / "off"), b64=False, rules=[])
    assert contained(on, T) and contained(off, T)
    assert on["mechanisms"]["demand"]["nodes_restricted"] + sum(1 for nd in on["plan"]["nodes"] if nd["demand_prov"] == "SUPPORT_RESTRICTED") >= 1
    assert on["attempts"][-1]["counters"]["entries_stored_planned"] < off["attempts"][-1]["counters"]["entries_stored_planned"]


def test_F6_fusion_must_activate_on_the_cycle_fixture(tmp_path):
    card = [2, 3, 2, 3, 2]; facs = rnd_model(77, card, [(0, 1), (1, 2), (2, 3), (3, 4), (4, 0)]); mp, ep = write_uai(str(tmp_path / "f.uai"), card, facs); model = U.read_model(mp); Z, T = truth_rows(model, {})
    on = run("GENERAL_BIDI_V2", mp, ep, str(tmp_path / "on"), b64=False, rules=[]); off = run("A2_NO_FUSION", mp, ep, str(tmp_path / "off"), b64=False, rules=[])
    assert contained(on, T) and contained(off, T) and on["plan"]["totals"]["fused_by_policy"] >= 1 and on["attempts"][-1]["counters"]["stream_reevals"] > 0 and off["plan"]["totals"]["fused"] == 0
    assert on["plan"]["totals"]["stored_entries"] < off["plan"]["totals"]["stored_entries"]


def test_F6_forged_result_token_is_caught_by_the_simplex_consistency_check(tmp_path, monkeypatch):
    """an actually FORGED kernel export (one numerator scaled) must be refused by the row consistency check and the route abandoned"""
    mp, ep = write_uai(str(tmp_path / "p.uai"), [2, 3], rnd_model(21, [2, 3], [(0, 1), (1,)])); model = U.read_model(mp); Z, T = truth_rows(model, {})
    orig = EX.mpfr_hex_to_fr; calls = {"n": 0}
    def forged(s):
        calls["n"] += 1; v = orig(s); return v * 3 if calls["n"] == 3 else v
    monkeypatch.setattr(EX, "mpfr_hex_to_fr", forged)
    rec = run("NATIVE_PLAIN_V2", mp, ep, str(tmp_path / "p"), b64=False, rules=[], fallback=False)         # the forged p=64 export is refused; the clean p=128 attempt certifies
    a0 = rec["attempts"][0]; assert str(a0.get("outcome", "")).startswith("ENCLOSURE_INCONSISTENT") and a0["refused"]["kind"] == "UNSOUND_ROUTE" and rec["precision"] == 128 and contained(rec, T)


# ============================================================================================================ R2-01 / R2-07: immutable task snapshot, strict grammar
def test_R2_01_file_replaced_after_parse_cannot_be_certified_under_the_new_identity(tmp_path):
    mp = str(tmp_path / "r.uai"); ep = mp + ".evid"; open(mp, "w").write("MARKOV\n1\n2\n1\n1 0\n2 1 3\n"); open(ep, "w").write("0\n")
    orig = GS.Snapshot.__init__
    def racing(self, m, e):
        orig(self, m, e); open(m, "w").write("MARKOV\n1\n2\n1\n1 0\n2 3 1\n")
    GS.Snapshot.__init__ = racing
    try:
        rec = run("GENERAL_BIDI_V2", mp, ep, str(tmp_path / "o"), b64=False, rules=[])
    finally:
        GS.Snapshot.__init__ = orig
    assert rec["task"]["raw_model_sha256"] != EX.sha_file(mp), "the record is bound to the PARSED bytes, not to the path's current bytes"
    st, cell = publish(str(tmp_path / "o"), mp, ep, rec); assert st == "CHECK_FAILED" and not os.path.exists(tmp_path / "o" / "output.MAR")
    open(mp, "w").write("MARKOV\n1\n2\n1\n1 0\n2 1 3\n"); rec = run("GENERAL_BIDI_V2", mp, ep, str(tmp_path / "o2"), b64=False, rules=[]); open(mp, "w").write("MARKOV\n1\n2\n1\n1 0\n2 3 1\n")
    st, cell = publish(str(tmp_path / "o2"), mp, ep, rec); assert st == "CHECK_FAILED"                                      # replaced between execution and publication
    open(mp, "w").write("MARKOV\n1\n2\n1\n1 0\n2 1 3\n"); rec = run("GENERAL_BIDI_V2", mp, ep, str(tmp_path / "o3"), b64=False, rules=[]); st, cell = publish(str(tmp_path / "o3"), mp, ep, rec)
    assert st == "CERTIFIED" and U.read_mar(str(tmp_path / "o3" / "output.MAR"))[0][0] == [Fr(1, 4), Fr(3, 4)]


@pytest.mark.parametrize("name,text", [("negative_factor_count", "MARKOV\n1\n2\n-1\n"), ("negative_arity", "MARKOV\n1\n2\n1\n-1\n1 5\n"), ("duplicate_scope", "MARKOV\n1\n2\n1\n2 0 0\n4 1 2 2 4\n"), ("zero_cardinality", "MARKOV\n1\n0\n0\n"),
                                       ("scope_out_of_range", "MARKOV\n1\n2\n1\n1 3\n2 1 1\n"), ("negative_entry", "MARKOV\n1\n2\n1\n1 0\n2 1 -3\n"), ("trailing", "MARKOV\n1\n2\n0\n7\n"), ("table_length", "MARKOV\n1\n2\n1\n1 0\n3 1 1 1\n")])
def test_R2_07_malformed_input_is_a_typed_refusal_never_certified(tmp_path, name, text):
    mp = str(tmp_path / "m.uai"); open(mp, "w").write(text); open(mp + ".evid", "w").write("0\n")
    with pytest.raises(EX.Refuse) as e:
        run("GENERAL_BIDI_V2", mp, mp + ".evid", str(tmp_path / "o"), b64=False)
    assert e.value.kind == "INVALID_INPUT"
    out = str(tmp_path / "cell"); subprocess.run([PY, "-m", "gbidi.cell", "GENERAL_BIDI_V2", mp, mp + ".evid", out, "5", "{}"], cwd=HERE, env=ENV, capture_output=True, timeout=60); assert json.load(open(os.path.join(out, "cell.json")))["status"] == "INVALID_INPUT"


def test_R2_07_valid_scalar_factors_and_bad_evidence(tmp_path):
    mp = str(tmp_path / "s.uai"); open(mp, "w").write("MARKOV\n1\n2\n2\n0\n1 0\n1 2.5\n2 1 3\n"); open(mp + ".evid", "w").write("0\n")
    rec = run("GENERAL_BIDI_V2", mp, mp + ".evid", str(tmp_path / "o"), b64=False); assert rec["certified_intervals"]["0"] == [["1/4", "1/4"], ["3/4", "3/4"]]
    for ev in ("1 0 5\n", "1 3 0\n", "2 0 0 0 1\n", "1 0 1 9\n"):
        open(mp + ".evid", "w").write(ev)
        with pytest.raises(EX.Refuse) as e:
            run("GENERAL_BIDI_V2", mp, mp + ".evid", str(tmp_path / "e"), b64=False)
        assert e.value.kind == "INVALID_INPUT"


# ============================================================================================================ R2-02: baseline before discovery; representability; shared allowance
def test_R2_02_star_600_general_certifies_on_the_cheap_order_within_20s(tmp_path):
    mp, ep, truth = star_model(str(tmp_path / "star.uai"), 600); t = time.monotonic(); cell = {"phases_s": {}}
    rec = EX.execute("GENERAL_BIDI_V2", mp, ep, str(tmp_path / "g"), time.monotonic() + 20, {"budget_s": 20, "allow_binary64": False, "reference_fallback": True, "rules": list(PL.COMMON_RULES)}, phases=cell["phases_s"])
    assert rec["status"] == "INTERVALS_OK" and rec["plan"]["order"]["name"] == "min_prospective_bag_volume" and contained(rec, truth) and time.monotonic() - t < 15
    tab = {c["order"]: c for c in rec["plan_candidates"]}; assert tab["original"]["mandatory_representable"] is False and "exceeds int64" in tab["original"]["mandatory_not_representable_reason"] and tab["min_volume"]["baseline"] is True
    st, cell = publish(str(tmp_path / "g"), mp, ep, rec); assert st == "CERTIFIED" and cell["point_check"]["status"] == "POINT_VERIFIED"
    p = run("NATIVE_PLAIN_V2", mp, ep, str(tmp_path / "p"), b64=False, budget=20); assert contained(p, truth)


def test_R2_02_forced_original_order_on_the_65_star_is_a_typed_route_limitation(tmp_path, monkeypatch):
    mp, ep, truth = star_model(str(tmp_path / "s65.uai"), 65); monkeypatch.setitem(EX.ARMS, "GENERAL_BIDI_V2", dict(EX.ARMS["GENERAL_BIDI_V2"], orders=["original"]))
    with pytest.raises(EX.Refuse) as e:
        run("GENERAL_BIDI_V2", mp, ep, str(tmp_path / "o"), b64=False, rules=[], budget=5)
    assert e.value.kind == "ROUTE_LIMITATION" and "NOT_REPRESENTABLE" in e.value.reason and e.value.rec["plan_candidates_error"]["kind"] == "NOT_REPRESENTABLE"


def test_R2_02_expired_discovery_clock_keeps_the_baseline_and_an_expired_inspect_refuses_to_spend(tmp_path):
    from adp import source as SRC
    mp, ep, truth = star_model(str(tmp_path / "s.uai"), 40); m = U.read_model(mp); R = SRC.Reduced(EX._ModelAdapter(m), {}); R.reduce([], deadline=None)
    P, table = PL.plan(R, dict(EX.ARMS["GENERAL_BIDI_V2"], bytes_per_entry=96), deadline=time.monotonic() - 1)     # the shared wall is already over
    tab = {c["order"]: c for c in table}
    assert P.representable() is None and P.order_info["name"] == "min_prospective_bag_volume" and tab["min_volume"]["baseline"] is True and tab["min_volume"]["state"] == "COMPLETE_MANDATORY_ONLY" and tab["min_fill"]["state"] == "ORDER_INCOMPLETE_DISCOVERY_WALL" and tab["original"]["state"] == "COMPLETE_MANDATORY_ONLY"
    ins = PL.Inspect(1_000_000, deadline=time.monotonic() - 1)
    with pytest.raises(PL.PlanStop):
        for _ in range(2):
            ins.spend(999_999)


def test_R2_02_metadata_cap_during_adjacency_keeps_the_original_candidate(tmp_path, monkeypatch):
    from adp import source as SRC
    mp, ep = write_uai(str(tmp_path / "t.uai"), [2, 2], [((0, 1), [1, 2, 3, 5]), ((1,), [7, 11])]); m = U.read_model(mp); R = SRC.Reduced(EX._ModelAdapter(m), {}); monkeypatch.setattr(PL, "METADATA_UPDATE_CAP", 1)
    P, table = PL.plan(R, dict(EX.ARMS["GENERAL_BIDI_V2"], bytes_per_entry=96)); assert P.order_info["name"] == "original_id" and any(c.get("state", "").startswith("ORDER_INCOMPLETE_METADATA_CAP") for c in table)


def test_SB_02_interrupted_view_pass_leaves_consistent_metadata(tmp_path, monkeypatch):
    from adp import source as SRC
    mp, ep = write_uai(str(tmp_path / "t.uai"), [2, 2, 2], [((0, 1, 2), [Fr(x) for x in [1, 2, 2, 4, 3, 7, 6, 14]])]); m = U.read_model(mp); R = SRC.Reduced(EX._ModelAdapter(m), {}); R.reduce([], deadline=None)
    monkeypatch.setattr(PL, "ROW_INSPECTION_CAP", 8); T = GV.TrustedReduced(R); P, _ = PL.plan(R, dict(EX.ARMS["GENERAL_BIDI_V2"], orders=["original"], bytes_per_entry=96)); nd = P.nodes[0]
    assert tuple(nd.radix) == tuple(len(nd.views[w].reps) for w in nd.scope) and nd.core_entries == PL.prod(nd.radix) and GV.validate(P, T).record["status"] == "VALID"


# ============================================================================================================ R2-06: numerical environment
def test_R2_06_upward_rounding_refuses_binary64_and_mpfr_still_certifies(tmp_path):
    libc = ctypes.CDLL(None); libc.fesetround.argtypes = [ctypes.c_int]; libc.fesetround.restype = ctypes.c_int; libc.fegetround.restype = ctypes.c_int
    mp, ep = write_uai(str(tmp_path / "t.uai"), [2, 2], [((0, 1), [1, 2, 3, 4]), ((0, 1), [1, 1, 1, 2])]); model = U.read_model(mp); Z, T = truth_rows(model, {}); old = libc.fegetround()
    up = 0x400000 if (sys.platform == "darwin" and os.uname().machine == "arm64") else 0x800
    assert libc.fesetround(up) == 0
    try:
        rec = run("NATIVE_PLAIN_V2", mp, ep, str(tmp_path / "u"), b64=True, rules=[], fallback=False)
    finally:
        libc.fesetround(old)
    assert rec["route"] == "mpfr" and any(a["route"] == "binary64" and a.get("refused", {}).get("kind") == "FP_ENV" for a in rec["attempts"]) and contained(rec, T)
    rec = run("NATIVE_PLAIN_V2", mp, ep, str(tmp_path / "n"), b64=True, rules=[], fallback=False); assert rec["route"] == "binary64" and contained(rec, T)


def test_R2_06_mpfr_exponent_overflow_and_underflow_are_typed_range_stops_without_a_precision_ladder(tmp_path):
    L = EX.Lib.get()
    def model(stem, toks):
        p = str(tmp_path / (stem + ".uai")); open(p, "w").write("MARKOV\n2\n2 2\n2\n2 0 1\n2 0 1\n4 " + " ".join(toks) + "\n4 " + " ".join(toks) + "\n"); open(p + ".evid", "w").write("0\n"); return p, p + ".evid"
    try:
        L.gb_test_exponent_range(0, 5); mp, ep = model("ov", ["100", "100", "300", "200"])
        with pytest.raises(EX.Refuse) as e:
            run("NATIVE_PLAIN_V2", mp, ep, str(tmp_path / "ov"), b64=False, fallback=False)
        assert e.value.kind == "NUMERIC_RANGE" and len(e.value.rec["attempts"]) == 1 and e.value.rec["attempts"][0]["stop"] == "RANGE"
        L.gb_test_exponent_range(-5, 0); mp, ep = model("un", ["0.0000000001", "0.0000000001", "0.0000000003", "0.0000000002"])
        with pytest.raises(EX.Refuse) as e:
            run("NATIVE_PLAIN_V2", mp, ep, str(tmp_path / "un"), b64=False, fallback=False)
        assert e.value.kind == "NUMERIC_RANGE" and len(e.value.rec["attempts"]) == 1
    finally:
        L.gb_test_exponent_range(0, 0)
    mp, ep = model("base", ["100", "100", "300", "200"]); rec = run("NATIVE_PLAIN_V2", mp, ep, str(tmp_path / "b"), b64=False); assert rec["certified_intervals"]["0"] == [["2/15", "2/15"], ["13/15", "13/15"]]


# ============================================================================================================ reference stream, deadlines, empty / degenerate, publication protocol
def test_reference_stream_is_a_resumable_odometer_with_growable_export(tmp_path, monkeypatch):
    from adp import source as SRC
    card = [3, 2, 2]; facs = rnd_model(5, card, [(0, 1), (1, 2), (0, 2)], zeros=0.2); mp, ep = write_uai(str(tmp_path / "r.uai"), card, facs); model = U.read_model(mp)
    R = SRC.Reduced(EX._ModelAdapter(model), {}); R.reduce([], deadline=time.monotonic() + 1); fb = EX.reference_stream(GV.TrustedReduced(R), time.monotonic() + 10); Z, N = OR.brute(model, {}); assert fb["status"] == "COMPLETE"
    assert all(fb["N"][v][s] / fb["Z"] == N[v][s] / Z for v in range(3) for s in range(card[v]))
    # 63 isolated binary variables (2^63 assignments): typed DEADLINE with a visited count, not a false 'visited None' nor a count gate
    mp2, ep2 = write_uai(str(tmp_path / "c63.uai"), [2] * 63, []); monkeypatch.setattr(PL, "CAPS", dict(PL.CAPS, reverse_pinned=1))
    with pytest.raises(EX.Refuse) as e:
        EX.execute("NATIVE_PLAIN_V2", mp2, ep2, str(tmp_path / "c63"), time.monotonic() + 1.0, {"budget_s": 1.0, "allow_binary64": False, "reference_fallback": True, "rules": []})
    st = e.value.rec["stop"]; assert st["phase"] == "reference_fallback" and st["kind"] == "DEADLINE" and "visited None" not in st["detail"] and e.value.rec["reference_fallback"]["visited"] > 0
    # 16,000-state unary with 1e300 entries: the 4 MiB V1 export buffer overflowed into an IndexError; now growable -> COMPLETE and exact
    n = 16000; mp3 = str(tmp_path / "big.uai"); open(mp3, "w").write("MARKOV\n1\n%d\n1\n1 0\n%d %s\n" % (n, n, " ".join(["1e300"] * n))); open(mp3 + ".evid", "w").write("0\n")
    monkeypatch.setattr(PL, "CAPS", dict(PL.CAPS, reverse_pinned=1)); rec = EX.execute("NATIVE_PLAIN_V2", mp3, mp3 + ".evid", str(tmp_path / "big"), time.monotonic() + 30, {"budget_s": 30, "allow_binary64": False, "reference_fallback": True, "rules": []})
    assert rec["precision"] == "exact_integer_reference" and all(Fr(a) == Fr(1, n) for a, _ in rec["certified_intervals"]["0"])


def test_deadline_inside_the_native_stream_is_a_typed_resource_stop_with_counters(tmp_path):
    n = 18; card = [2] * n; facs = rnd_model(9, card, [(i, j) for i in range(n) for j in range(i + 1, n)]); mp, ep = write_uai(str(tmp_path / "dl.uai"), card, facs)
    with pytest.raises(EX.Refuse) as e:
        EX.execute("NATIVE_PLAIN_V2", mp, ep, str(tmp_path / "dl"), time.monotonic() + 0.05, {"budget_s": 0.05, "allow_binary64": False, "reference_fallback": True, "rules": []})
    assert e.value.kind == "RESOURCE_STOP" and "DEADLINE" in e.value.reason and e.value.rec["attempts"][-1]["counters"]["polls"] >= 1


def test_kernel_deadline_is_relative_and_a_generous_budget_completes(tmp_path):
    n = 14; card = [2] * n; facs = rnd_model(4, card, [(i, j) for i in range(n) for j in range(i + 1, n)]); mp, ep = write_uai(str(tmp_path / "k.uai"), card, facs)
    rec = EX.execute("NATIVE_PLAIN_V2", mp, ep, str(tmp_path / "ok"), time.monotonic() + 60, {"budget_s": 60, "allow_binary64": False, "reference_fallback": False, "rules": []}); assert rec["status"] == "INTERVALS_OK" and rec["attempts"][-1]["counters"]["polls"] >= 1
    with pytest.raises(EX.Refuse) as e:
        EX.execute("NATIVE_PLAIN_V2", mp, ep, str(tmp_path / "dl"), time.monotonic() + 0.001, {"budget_s": 0.001, "allow_binary64": False, "reference_fallback": False, "rules": []})
    assert "DEADLINE" in e.value.reason


def test_SB_03_empty_query_task_goes_through_the_same_separate_verifier(tmp_path):
    mp = str(tmp_path / "e.uai"); open(mp, "w").write("MARKOV\n0\n\n1\n0\n1 2.5\n"); open(mp + ".evid", "w").write("0\n")
    rec = run("GENERAL_BIDI_V2", mp, mp + ".evid", str(tmp_path / "e")); assert rec["status"] == "INTERVALS_OK" and rec["certified_intervals"] == {} and Fr(rec["Z_exact"]) == Fr(5, 2)
    st, cell = publish(str(tmp_path / "e"), mp, mp + ".evid", rec); assert st == "CERTIFIED" and cell["point_check"]["status"] == "POINT_VERIFIED" and open(tmp_path / "e" / "output.MAR").read() == "MAR\n0\n"
    open(mp, "w").write("MARKOV\n0\n\n1\n0\n1 0\n"); rec = run("GENERAL_BIDI_V2", mp, mp + ".evid", str(tmp_path / "e0")); assert rec["status"] == "ZERO_EVIDENCE_PROVED"
    mp2, ep2 = write_uai(str(tmp_path / "u.uai"), [3, 2], [((0,), [1, 2, 3]), ((1,), [1, 1])]); rec = run("NATIVE_PLAIN_V2", mp2, ep2, str(tmp_path / "u")); assert rec["certified_intervals"]["0"] == [["1/6", "1/6"], ["1/3", "1/3"], ["1/2", "1/2"]]


def test_G_J_zeros_inconsistency_duplicates(tmp_path):
    mp, ep = write_uai(str(tmp_path / "eq.uai"), [2, 2], [((0, 1), [1, 0, 0, 1])], {0: 0, 1: 1}); rec = run("GENERAL_BIDI_V2", mp, ep, str(tmp_path / "eq")); assert rec["status"] == "ZERO_EVIDENCE_PROVED"
    mp, ep = write_uai(str(tmp_path / "z2.uai"), [2, 2], [((0,), [0, 2]), ((0, 1), [1, 1, 3, 0])]); rec = run("GENERAL_BIDI_V2", mp, ep, str(tmp_path / "z2"), b64=False); assert rec["certified_intervals"]["1"] == [["1", "1"], ["0", "0"]]
    mp, ep = write_uai(str(tmp_path / "d.uai"), [2], [((0,), [1, 2]), ((0,), [1, 2])]); rec = run("GENERAL_BIDI_V2", mp, ep, str(tmp_path / "d")); assert rec["certified_intervals"]["0"] == [["1/5", "1/5"], ["4/5", "4/5"]]


def test_shared_reductions_have_a_valid_marked_interpretation(tmp_path):
    eq = [Fr(1), Fr(0), Fr(0), Fr(1)]; r1 = [Fr(1), Fr(2), Fr(3), Fr(2), Fr(4), Fr(6)]
    facs = [((0, 1), eq), ((2, 3), r1), ((1, 4), [Fr(x) for x in [1, 2, 1, 2, 3, 6]]), ((4,), [Fr(0), Fr(1), Fr(1)]), ((3, 5), [Fr(x) for x in [1, 1, 2, 2, 3, 3]]), ((5,), [Fr(2), Fr(3)]), ((), [Fr(1, 2)])]
    card = [2, 2, 2, 3, 3, 2]; mp, ep = write_uai(str(tmp_path / "s.uai"), card, facs); model = U.read_model(mp)
    for arm in ("GENERAL_BIDI_V2", "NATIVE_PLAIN_V2"):
        rec = run(arm, mp, ep, str(tmp_path / arm)); assert truth_inside(rec, model, {}) and (set(rec["reductions"]["steps"]) >= {"alias", "quotient", "exclude"} or rec["reductions"]["free_reduced"] < 6)


# ============================================================================================================ cells, binding, publication, harness (H2 / H3 / R2-08 / R2-09)
@pytest.mark.parametrize("arm", ARMS)
def test_cell_process_certifies_binds_and_classifies_on_the_launch_clock(tmp_path, arm):
    card = [2, 3, 2]; facs = rnd_model(12, card, [(0, 1), (1, 2), (0, 2)]); mp, ep = write_uai(str(tmp_path / "m.uai"), card, facs, {2: 1}); model = U.read_model(mp); Z, N = OR.brute(model, {2: 1})
    out = str(tmp_path / arm); exp = json.dumps({"raw_model_sha256": EX.sha_file(mp), "raw_evidence_sha256": EX.sha_file(ep)})
    subprocess.run([PY, "-m", "gbidi.cell", arm, mp, ep, out, "60", "{}", exp], cwd=HERE, env=dict(ENV, GBIDI_LAUNCH_MONO="%.9f" % time.monotonic()), capture_output=True, timeout=300); r = json.load(open(os.path.join(out, "cell.json")))
    assert r["status"] == "CERTIFIED" and r["deadline_classification_clock"] == "launch-relative" and r["point_check"]["status"] == "POINT_VERIFIED" and r["task"]["raw_evidence_sha256"] == EX.sha_file(ep)
    rows, _ = U.read_mar(os.path.join(out, "output.MAR")); assert all(sum(Fr(x) for x in rows[v]) == 1 and all(abs(Fr(rows[v][s]) - N[v][s] / Z) < Fr(1, 200) for s in range(card[v])) for v in range(3))
    out2 = str(tmp_path / (arm + "_mismatch")); subprocess.run([PY, "-m", "gbidi.cell", arm, mp, ep, out2, "60", "{}", json.dumps({"raw_model_sha256": "0" * 64})], cwd=HERE, env=ENV, capture_output=True, timeout=120)
    assert json.load(open(os.path.join(out2, "cell.json")))["status"] == "TASK_MISMATCH"


def test_O_binding_and_publication_rejections(tmp_path):
    card = [2, 2]; facs = rnd_model(13, card, [(0, 1), (0,)]); mp, ep0 = write_uai(str(tmp_path / "m.uai"), card, facs, {0: 0}); ep1 = str(tmp_path / "m1.evid"); open(ep1, "w").write("1 0 1\n")
    o0 = str(tmp_path / "o0"); subprocess.run([PY, "-m", "gbidi.cell", "GENERAL_BIDI_V2", mp, ep0, o0, "60", "{}"], cwd=HERE, env=ENV, capture_output=True, timeout=120); r0 = json.load(open(os.path.join(o0, "cell.json"))); assert r0["status"] == "CERTIFIED"; rec0 = json.load(open(os.path.join(o0, "checked_record.json")))
    cell = {"phases_s": {}}; o2 = str(tmp_path / "o2"); os.makedirs(o2); assert EX.publish(o2, mp, ep1, rec0, cell, time.monotonic() + 10) == "CHECK_FAILED"
    op = str(tmp_path / "pc.json"); subprocess.run([PY, "-m", "gbidi.verify", os.path.join(o0, "checked_record.json"), os.path.join(o0, "output.MAR"), mp, ep1, op], cwd=HERE, env=ENV, capture_output=True); assert json.load(open(op))["status"] == "POINT_REJECTED"
    for mut in ("status", "missing_row", "extra_row", "short_row"):
        bad = json.loads(json.dumps(rec0)); d = str(tmp_path / ("b_" + mut)); os.makedirs(d)
        if mut == "status":
            bad["status"] = "REJECTED"
        elif mut == "missing_row":
            del bad["certified_intervals"]["1"]
        elif mut == "extra_row":
            bad["certified_intervals"]["5"] = [["0", "1"], ["0", "1"]]
        else:
            bad["certified_intervals"]["1"] = bad["certified_intervals"]["1"][:1]
        cell = {"phases_s": {}}; assert EX.publish(d, mp, ep0, bad, cell, time.monotonic() + 10) == "CHECK_FAILED"
    mar = os.path.join(o0, "output.MAR"); toks = open(mar).read().split(); i = next(k for k, t in enumerate(toks) if "." in t); toks[i] = "0.5x"; alt = str(tmp_path / "alt.MAR"); open(alt, "w").write(" ".join(toks) + "\n")
    subprocess.run([PY, "-m", "gbidi.verify", os.path.join(o0, "checked_record.json"), alt, mp, ep0, op], cwd=HERE, env=ENV, capture_output=True); assert json.load(open(op))["status"] == "POINT_REJECTED"


def test_R2_08_supervisor_completion_means_the_owned_group_is_empty(tmp_path):
    import psutil
    pidfile = str(tmp_path / "pid.txt"); leader = str(tmp_path / "leader.py"); open(leader, "w").write("import subprocess,sys,time\np=subprocess.Popen([sys.executable,'-c','import time; time.sleep(5)'])\nopen(sys.argv[1],'w').write(str(p.pid))\ntime.sleep(0.10)\n")
    led = str(tmp_path / "ledger.jsonl"); cmd = [PY, "-m", "gbidi.supervise", "--ledger", led, "--scope", "test", "--job", "leader-exits-first", "--timeout", "3", "--stdout", str(tmp_path / "c.log"), "--stderr", str(tmp_path / "c.log"), "--", PY, leader, pidfile]
    s = subprocess.run(cmd, capture_output=True, text=True, timeout=30, cwd=HERE, env=ENV); pid = int(open(pidfile).read())
    alive = psutil.pid_exists(pid) and psutil.Process(pid).status() != psutil.STATUS_ZOMBIE
    if alive:
        os.kill(pid, signal.SIGKILL)
    rc = [json.loads(x) for x in open(led) if json.loads(x)["kind"] == "RECEIPT"][-1]
    assert not alive and rc["descendants_after_leader_exit"] >= 1 and rc["group_empty_at_receipt"] is True and rc["outcome"] == "COMPLETED_LEADER_EXIT_SURVIVORS_KILLED" and rc["cleanup_unresolved"] is False
    led2 = str(tmp_path / "l2.jsonl"); subprocess.run([PY, "-m", "gbidi.supervise", "--ledger", led2, "--scope", "test", "--job", "plain", "--timeout", "3", "--", PY, "-c", "print(1)"], capture_output=True, timeout=30, cwd=HERE, env=ENV)
    rc2 = [json.loads(x) for x in open(led2) if json.loads(x)["kind"] == "RECEIPT"][-1]; assert rc2["outcome"] == "COMPLETED" and rc2["group_empty_at_receipt"] is True and rc2["descendants_after_leader_exit"] == 0


def test_R2_09_manifest_identity_reconciliation_rejects_forged_ids_aliases_and_duplicates(tmp_path):
    from gbidi import pilot as PI
    man = {"seed": PI.SEED, "commit": "c" * 40, "kernel_binary_sha256": "k" * 64, "config_adp_repaired_sha256": "f" * 64, "cases": {}, "cells": []}
    for c in PI.inventory():
        man["cases"][c] = {"canonical_model_sha256": "m" + c, "canonical_evidence_sha256": "e" + c, "raw_model_sha256": "rm" + c, "raw_evidence_sha256": "re" + c}
    for i, c in enumerate(PI.order()):
        tid, cid = PI.canonical_task(man["cases"][c["case"]], c, man["config_adp_repaired_sha256"], man["kernel_binary_sha256"], man["commit"]); man["cells"].append(dict(c, index=i, task_id=tid, cell_id=cid, out_dir="cells/%s/%03d__%s" % (c["stage"], i, tid)))
    assert PI.reconcile_manifest(man) is None
    mut = copy.deepcopy(man); mut["cells"][1]["out_dir"] = mut["cells"][0]["out_dir"]; assert PI.reconcile_manifest(mut) is not None
    mut = copy.deepcopy(man); mut["cells"][1]["cell_id"] = mut["cells"][0]["cell_id"]; assert PI.reconcile_manifest(mut) is not None
    mut = copy.deepcopy(man); mut["cells"][0]["task_id"] = "not-the-task-id"; assert PI.reconcile_manifest(mut) is not None
    mut = copy.deepcopy(man); mut["config_adp_repaired_sha256"] = "g" * 64; assert PI.reconcile_manifest(mut) is not None                     # the configuration is part of the task identity


def _plan_cell(arm, budget=20.0, cell_id="c1", case="X"):
    return {"index": 0, "stage": "primary_breadth", "arm": arm, "case": case, "budget_s": budget, "kind": "primary", "task_id": "t", "cell_id": cell_id, "out_dir": "cells/a", "max_permitted_charge_s": budget + 6}


def _ledger_chain(D, job, outcome="COMPLETED", start="2026-11-10T00:00:01Z", out_dir="cells/a", model="m.uai", wall=0.5, pieces=("START", "SPAWNED", "RECEIPT")):
    rows = []
    if "START" in pieces:
        rows.append({"kind": "START", "jid": "j1", "job": job, "scope": "matrix_primary_breadth", "start_utc": start, "cmd": ["python", "-m", "x", model, "e", out_dir], "max_permitted_charge_s": 26})
    if "SPAWNED" in pieces:
        rows.append({"kind": "SPAWNED", "jid": "j1", "job": job, "pid": 1, "pgid": 1})
    if "RECEIPT" in pieces:
        rows.append({"kind": "RECEIPT", "jid": "j1", "job": job, "scope": "matrix_primary_breadth", "start_utc": start, "outcome": outcome, "wall_s": wall, "returncode": 0, "cleanup_unresolved": False, "group_empty_at_receipt": True, "nested_groups_live_at_receipt": 0})
    open(os.path.join(D, "GB_LEDGER.jsonl"), "w").write("".join(json.dumps(r) + "\n" for r in rows))


def test_R2_09_closeout_reconciler_accepts_only_a_fully_bound_attempt(tmp_path):
    """the ONE reconciler (resume + closeout): same-arm same-input stale 120 s record for a 20 s task, wrong queries, missing expected ids, receipt
    without START/SPAWNED, output substitution, in-process clock -> NOT accepted with reasons; the fully bound attempt -> accepted; comparators go
    through the adapter mapping (AGGREGATE_DP_V1 / EXACT producers) with launch-relative delivery."""
    from gbidi import reconcile as RC
    from gbidi_closeout import report as R
    import hashlib
    D = str(tmp_path); od = os.path.join(D, "cells", "a"); os.makedirs(od); rm, re_ = "rm", "re"; nvars = 2; qsha = hashlib.sha256(json.dumps([0, 1]).encode()).hexdigest()
    case = {"family": "F", "raw_model_sha256": rm, "raw_evidence_sha256": re_, "canonical_model_sha256": "cm", "canonical_evidence_sha256": "ce", "variables": nvars, "model_path": "m.uai"}
    man = {"frozen_utc": "2026-11-10T00:00:00Z", "cases": {"X": case}, "cells": [_plan_cell("NATIVE_PLAIN_V2")], "kernel_binary_sha256": "kb", "config_adp_repaired_sha256": "cfg", "common_rules": list(PL.COMMON_RULES)}
    task = {"raw_model_sha256": rm, "raw_evidence_sha256": re_, "canonical_model_sha256": "cm", "canonical_evidence_sha256": "ce", "nvars": nvars, "queries_sha256": qsha}
    open(os.path.join(od, "output.MAR"), "w").write("MAR\n2 2 0.5 0.5 2 0.5 0.5\n"); osha = RC.sha(os.path.join(od, "output.MAR")); job = RC.job_name(man["cells"][0])
    good = {"arm": "NATIVE_PLAIN_V2", "status": "CERTIFIED", "deadline_s": 20.0, "task": task, "expected_task": {"cell_id": "c1"}, "complete_response_s": 0.2, "complete_response_from_launch_s": 0.3, "deadline_classification_clock": "launch-relative", "output_sha256": osha, "backend": {"build": {"binary_sha256": "kb"}}, "config": {"allow_binary64": True}}
    def check(rec, ledger_kw=None, **man_kw):
        json.dump(rec, open(os.path.join(od, "cell.json"), "w")); _ledger_chain(D, job, **(ledger_kw or {})); m2 = dict(man, **man_kw); return R.cells_ledger(D, m2)[0]
    row = check(good); assert row["accepted"] and row["status"] == "CERTIFIED" and row["resolution"] == "ACCEPTED" and row["delivered_valid_output"], row["reasons"]
    stale = dict(good, deadline_s=120.0, complete_response_s=99.0, complete_response_from_launch_s=99.1, task=dict(task, queries_sha256="wrong"), config={"rules": []}); del stale["expected_task"]
    row = check(stale, ledger_kw={"pieces": ("RECEIPT",)}); assert not row["accepted"] and row["status"] == "NOT_ACCEPTED" and any("budget" in r for r in row["reasons"]) and any("query" in r for r in row["reasons"]) and any("cell id" in r for r in row["reasons"]) and any("START/SPAWNED/RECEIPT" in r for r in row["reasons"])
    row = check(dict(good, arm="OTHER_ARM")); assert not row["accepted"] and any("arm" in r for r in row["reasons"])
    row = check(dict(good, task=dict(task, raw_model_sha256="other"))); assert not row["accepted"]
    row = check(dict(good, output_sha256="0" * 64)); assert not row["accepted"] and any("output.MAR" in r for r in row["reasons"])
    row = check(dict(good, deadline_classification_clock="in-process (no launch timestamp)")); assert not row["accepted"]
    row = check(good, ledger_kw={"outcome": "LAUNCH_FAILED"}); assert not row["accepted"] and any("outcome" in r for r in row["reasons"])
    row = check(good, ledger_kw={"start": "2026-11-09T00:00:00Z"}); assert not row["accepted"]
    row = check(good, kernel_binary_sha256="other"); assert not row["accepted"] and any("kernel" in r for r in row["reasons"])
    # comparator through the adapter
    man["cells"] = [_plan_cell("ADP_REPAIRED")]; job = RC.job_name(man["cells"][0])
    prod = {"arm": "AGGREGATE_DP_V1", "status": "CERTIFIED", "deadline_s": 20.0, "complete_response_s": 0.2}; json.dump(prod, open(os.path.join(od, "cell.json"), "w"))
    _ledger_chain(D, job); row = R.cells_ledger(D, man)[0]; assert not row["accepted"] and any("adapter" in r for r in row["reasons"])                 # no adapter record -> not accepted (V2 before: UNBOUND)
    ad = {"planned_arm": "ADP_REPAIRED", "producer_arm": "AGGREGATE_DP_V1", "budget_s": 20.0, "task": task, "expected_task": {"cell_id": "c1"}, "status": "CERTIFIED", "delivery_from_launch_s": 0.4, "output_sha256": osha, "config_sha256": "cfg"}
    json.dump(ad, open(os.path.join(od, "adapter.json"), "w")); row = R.cells_ledger(D, man)[0]; assert row["accepted"] and row["status"] == "CERTIFIED" and row["delivery_from_launch_s"] == 0.4, row["reasons"]
    json.dump(dict(ad, delivery_from_launch_s=20.5), open(os.path.join(od, "adapter.json"), "w")); row = R.cells_ledger(D, man)[0]; assert not row["accepted"] and any("delivery" in r for r in row["reasons"])
    json.dump(dict(ad, config_sha256="other"), open(os.path.join(od, "adapter.json"), "w")); row = R.cells_ledger(D, man)[0]; assert not row["accepted"]
    man["cells"] = [_plan_cell("EXACT_LIBDAI")]; job = RC.job_name(man["cells"][0]); json.dump({"arm": "EXACT", "status": "COMPLETE", "deadline_s": 20.0}, open(os.path.join(od, "cell.json"), "w")); _ledger_chain(D, job)
    json.dump(dict(ad, planned_arm="EXACT_LIBDAI", producer_arm="EXACT", status="COMPLETE"), open(os.path.join(od, "adapter.json"), "w")); row = R.cells_ledger(D, man)[0]; assert row["accepted"] and row["status"] == "COMPLETE", row["reasons"]


def test_H4_repeated_stage_attempts_are_each_charged_once_with_their_own_children(tmp_path):
    from gbidi import pilot as PI
    from gbidi_closeout import report as R
    D = str(tmp_path); rows = []
    for jid, scope, job, wall, beg, end, parent in (("o1", "stage_outer_primary_breadth", "stage_runner:primary_breadth", 10.0, 0, 10, None), ("c1", "matrix_primary_breadth", "cell:one", 5.0, 1, 6, "o1"), ("o2", "stage_outer_primary_breadth", "stage_runner:primary_breadth", 8.0, 20, 28, None), ("c2", "matrix_primary_breadth", "cell:two", 4.0, 21, 25, "o2")):
        b = "2026-11-10T00:00:%02dZ" % beg; e = "2026-11-10T00:00:%02dZ" % end
        rows += [{"kind": "START", "jid": jid, "scope": scope, "job": job, "start_utc": b, "max_permitted_charge_s": 30, "parent_jid": parent}, {"kind": "RECEIPT", "jid": jid, "scope": scope, "job": job, "start_utc": b, "end_utc": e, "wall_s": wall, "outcome": "COMPLETED", "cleanup_unresolved": False, "parent_jid": parent}]
    open(os.path.join(D, "GB_LEDGER.jsonl"), "w").write("".join(json.dumps(x) + "\n" for x in rows))
    total, by, unresolved, extra = PI.charged(D); assert total == 18.0 and not unresolved and [o["parent_remainder_s"] for o in extra["outer_attempts"]] == [5.0, 4.0]
    B = R.budget(D, {"frozen_utc": "2026-11-10T00:00:00Z", "ceiling_s": 100}, []); assert B["total_charged_s"] == 18.0 and B["compliance"].startswith("every start")
    rows2 = [r for r in rows if not (r["kind"] == "RECEIPT" and r["jid"] == "o1")]; open(os.path.join(D, "GB_LEDGER.jsonl"), "w").write("".join(json.dumps(x) + "\n" for x in rows2))
    total, by, unresolved, extra = PI.charged(D); assert unresolved and total == 5 + 4 + 4 + 30 and R.budget(D, {"frozen_utc": "2026-11-10T00:00:00Z", "ceiling_s": 100}, [])["compliance"] == "QUALIFIED"   # an outer attempt without receipt: max permitted, QUALIFIED


def test_median_is_the_ordinary_median():
    from gbidi_closeout import report as R
    assert R.median([1, 2, 3, 4]) == 2.5 and R.median([3, 1, 2]) == 2 and R.median([]) is None


# ============================================================================================================ counters against hand-enumerated schedules; binary64 vs MPFR on medium models
def test_counters_match_a_hand_enumerated_two_node_schedule(tmp_path):
    """f(0,1) = [1,2,3,5], g(1) = [7,11]; min-volume order eliminates 0 then 1; no fusion (A2). Hand enumeration of the implemented schedule:
    FORWARD  node 0 (x=0, scope {1}, input f): 2 stored entries x 2 rows, 1 input -> 4 row products (4 mults, 4 adds, 4 lookups);
             node 1 (root, inputs g, M0): 1 entry x 2 rows; per row: g load, M0 stored read = view scale (1 mult) x value (1 mult), 2 row-product mults -> 8 mults;
             Z = scale x root: 1 mult.                                                             forward mults 13, primal_rows 6, value_frames 3.
    REVERSE  root seed: pre (1), suf (1), h = pre x suf (1) x scale (1) -> 4 root mults, 1 adjoint add;
             drain root slot: 2 rows; per row: M0 read (2 mults), prefix 2, suffix 2, row = h x pre (1), scatter to M0: pre x suf (1) x h (1) x view scale (1 mult inside child_index_scale) x sc (1) = 4 -> 11 mults; numerator add 1, adjoint add 1 per row;
             drain node-0 slots: 2 slots x 2 rows; per row: prefix 1, suffix 1, row 1 -> 3 mults, 1 numerator add.             reverse mults 4 + 22 + 12 = 38.
    TOTAL mults 51, adds 4 (fwd) + 2 (root rows) + 2 (root adjoint adds) + 1 (seed) + 4 (node-0 rows) + ... = see asserted identities below."""
    mp, ep = write_uai(str(tmp_path / "t.uai"), [2, 2], [((0, 1), [1, 2, 3, 5]), ((1,), [7, 11])]); rec = run("A2_NO_FUSION", mp, ep, str(tmp_path / "o"), b64=False, rules=[], fallback=False); c = rec["attempts"][-1]["counters"]
    assert [nd["x"] for nd in rec["plan"]["nodes"]] == [0, 1] and rec["plan"]["totals"]["fused"] == 0
    assert c["primal_rows"] == 6 and c["reverse_rows"] == 6 and c["value_frames"] == 3 and c["pullback_frames"] == 3 and c["entries_stored_planned"] == 3 and c["entries_materialized"] == 3 and c["stream_reevals"] == 0 and c["reads_outside_demand"] == 0
    assert c["numerator_adds"] == 6 and c["adjoint_adds"] == 1 + 2 and c["slots_drained"] == 3 and c["root_ops"] == 1 + 4 and c["lookups"] == 4 + 2 * 2 + 2 * 2 + 4
    assert c["mults"] == (4 + 8 + 1) + (4 + 2 * 11 + 4 * 3) == 51, c
    assert c["adds"] == 4 + 2 + 1 + (2 + 2) + 4, c                                              # fwd rows 6; root seed 1; root rows: numerator 2 + adjoint 2; node-0 rows: numerator 4
    assert rec["plan"]["totals"]["cold_work_proxy"] >= c["mults"] // 4                           # the proxy is a conservative count of the same schedule, not a time


def test_binary64_labels_agree_with_mpfr_on_medium_models_and_the_grid(tmp_path):
    card = [4] * 10; facs = rnd_model(31, card, [(0, 1, 2), (2, 3, 4), (4, 5, 6), (6, 7, 8), (8, 9, 0), (1, 5, 9), (3, 7)]); mp, ep = write_uai(str(tmp_path / "m.uai"), card, facs)
    for arm in ("NATIVE_PLAIN_V2", "GENERAL_BIDI_V2"):
        b = run(arm, mp, ep, str(tmp_path / (arm + "_b")), b64=True, rules=[]); m = run(arm, mp, ep, str(tmp_path / (arm + "_m")), b64=False, rules=[])
        assert b["route"] == "binary64" and m["route"] == "mpfr" and b["attempts"][-1]["counters"]["primal_rows"] > 10 ** 3 and b["attempts"][-1]["labels"]["E_N_max"] > 0
        for v, row in b["certified_intervals"].items():
            for s, (a, x) in enumerate(row):
                ma, mb = [Fr(t) for t in m["certified_intervals"][v][s]]; assert not (Fr(x) < ma or Fr(a) > mb), (arm, v, s)
    card = [2] * 16; facs = rnd_model(32, card, [(i, i + 1) for i in range(15)] + [(i, i + 4) for i in range(12)] + [(v,) for v in range(16)]); mp, ep = write_uai(str(tmp_path / "g.uai"), card, facs); model = U.read_model(mp)
    rec = run("GENERAL_BIDI_V2", mp, ep, str(tmp_path / "g"), b64=True, rules=[]); assert rec["route"] == "binary64" and truth_inside(rec, model, {})


def test_synthetic_memory_downgrade_transition_fires_and_stays_exact(tmp_path, monkeypatch):
    card = [2] * 12; facs = rnd_model(8, card, [(i, i + 1) for i in range(11)] + [(i, i + 3) for i in range(9)]); mp, ep = write_uai(str(tmp_path / "m.uai"), card, facs); model = U.read_model(mp)
    monkeypatch.setattr(PL, "CAPS", dict(PL.CAPS, value_cache=3000))
    rec = run("NATIVE_PLAIN_V2", mp, ep, str(tmp_path / "o"), b64=False, rules=[]); assert rec["plan"]["totals"]["fused_by_memory"] >= 1 and rec["attempts"][-1]["counters"]["stream_reevals"] > 0 and truth_inside(rec, model, {})


# ============================================================================================================ third review: V2-V1 .. H4 controls
def test_V2_V1_proposal_payload_substitution_cannot_reach_execution(tmp_path):
    """validation and execution read the SAME immutable trusted payload: a proposal whose factor table / scale / scope / cardinality were replaced is
    simply not what gets executed (the trusted snapshot is), an in-place mutation of the live reduced object is detected and REJECTED, and the
    unchanged proposal certifies exactly."""
    mp, ep = write_uai(str(tmp_path / "t.uai"), [2, 2], [((0, 1), [1, 2, 3, 4]), ((0, 1), [1, 1, 1, 2])]); truth = {0: [Fr(3, 14), Fr(11, 14)], 1: [Fr(2, 7), Fr(5, 7)]}; orig = PL.plan
    for mode in ("unchanged", "replace_factor_table", "replace_scale_zero", "replace_scope", "replace_card", "mutate_R_in_place"):
        def altered(R, *a, mode=mode, **k):
            P, T = orig(R, *a, **k)
            if mode == "replace_factor_table":
                fid = sorted(P.fac)[1]; f = copy.deepcopy(P.fac[fid]); f.table = [Fr(1)] * 4; P.fac = dict(P.fac); P.fac[fid] = f
            elif mode == "replace_scale_zero":
                P.R = copy.deepcopy(P.R); P.R.scale = Fr(0)
            elif mode == "replace_scope":
                fid = sorted(P.fac)[1]; f = copy.deepcopy(P.fac[fid]); f.scope = (1, 0); P.fac = dict(P.fac); P.fac[fid] = f
            elif mode == "replace_card":
                fid = sorted(P.fac)[1]; f = copy.deepcopy(P.fac[fid]); f.card = (1, 4); P.fac = dict(P.fac); P.fac[fid] = f
            elif mode == "mutate_R_in_place":
                R.factors[1].table[:] = [Fr(1)] * 4
            return P, T
        PL.plan = altered
        try:
            if mode == "mutate_R_in_place":
                with pytest.raises(EX.Refuse) as e:
                    run("GENERAL_BIDI_V2", mp, ep, str(tmp_path / mode), b64=False)
                assert e.value.kind == "REJECTED" and "mutated" in e.value.reason; continue
            rec = run("GENERAL_BIDI_V2", mp, ep, str(tmp_path / mode), b64=False); assert rec["status"] == "INTERVALS_OK" and contained(rec, truth), mode
            st, cell = publish(str(tmp_path / mode), mp, ep, rec); assert st == "CERTIFIED" and cell["point_check"]["status"] == "POINT_VERIFIED"
            assert rec["plan_validation"]["trusted_content_sha256"] == rec["trusted_source"]["content_sha256"]
        finally:
            PL.plan = orig


def test_V2_V2_product_zero_classes_with_different_zero_witnesses_are_valid(tmp_path):
    mp, ep = write_uai(str(tmp_path / "z.uai"), [2, 3], [((0, 1), [0, 1, 1, 0, 2, 2]), ((0, 1), [1, 0, 3, 2, 0, 4])]); model = U.read_model(mp); Z, T = truth_rows(model, {}); assert Z == 11
    for rules in ([], list(PL.COMMON_RULES)):
        rec = run("GENERAL_BIDI_V2", mp, ep, str(tmp_path / ("r%d" % len(rules))), b64=False, rules=rules); assert contained(rec, T) and (rec.get("plan_validation") or {"status": "VALID"})["status"] == "VALID"   # the common rules may fold everything (no plan)
    # but a zero state merged with a NONZERO state is still rejected
    orig = PL.plan
    def forged(R, *a, **k):
        P, Tb = orig(R, *a, **k); nd = next(n for n in P.nodes if n.scope); w = nd.scope[0]; n = len(R.dom[w]); nd.views[w] = View([0] * n, [0], [Fr(1)] * n); nd.radix = tuple(len(nd.views[x].reps) for x in nd.scope); nd.core_entries = 1; nd.demand = "FULL"; nd._support_out = None; return P, Tb
    PL.plan = forged
    try:
        with pytest.raises(EX.Refuse) as e:
            run("GENERAL_BIDI_V2", mp, ep, str(tmp_path / "forged"), b64=False, rules=[])
        assert e.value.kind == "REJECTED"
    finally:
        PL.plan = orig


def test_V2_P1_mandatory_orders_survive_an_expired_optional_clock_above_the_poll_boundary(tmp_path):
    from adp import source as SRC
    for n in (65, 80):
        mp, ep, truth = star_model(str(tmp_path / ("s%d.uai" % n)), n); m = U.read_model(mp); R = SRC.Reduced(EX._ModelAdapter(m), {}); R.reduce([], deadline=None)
        P, table = PL.plan(R, dict(EX.ARMS["GENERAL_BIDI_V2"], bytes_per_entry=80), deadline=time.monotonic() - 1, hard_deadline=time.monotonic() + 30)
        tab = {c["order"]: c for c in table}; assert P.order_info["name"] == "min_prospective_bag_volume" and P.order_info["updates"] > PL.POLL_UNITS and tab["min_fill"]["state"] == "ORDER_INCOMPLETE_DISCOVERY_WALL" and tab["original"]["mandatory_representable"] is False
        with pytest.raises(PL.PlanStop) as e:
            PL.plan(R, dict(EX.ARMS["GENERAL_BIDI_V2"], bytes_per_entry=80), deadline=None, hard_deadline=time.monotonic() - 1)
        assert e.value.kind == "CELL_DEADLINE"
    # end to end: the reductions consume the shared allowance, planning still finds the cheap order within the cell deadline
    mp, ep, truth = star_model(str(tmp_path / "s80e.uai"), 80); orig = EX.SRC.Reduced.reduce
    def slow(self, *a, **k):
        r = orig(self, *a, **k); time.sleep(1.1); return r
    EX.SRC.Reduced.reduce = slow
    try:
        rec = EX.execute("GENERAL_BIDI_V2", mp, ep, str(tmp_path / "e2e"), time.monotonic() + 20, {"budget_s": 20, "allow_binary64": False, "reference_fallback": True})
    finally:
        EX.SRC.Reduced.reduce = orig
    assert rec["status"] == "INTERVALS_OK" and rec["plan"]["order"]["name"] == "min_prospective_bag_volume" and contained(rec, truth) and {c["order"]: c.get("state") for c in rec["plan_candidates"]}["min_fill"] == "ORDER_INCOMPLETE_DISCOVERY_WALL"


def test_RT_poll_quantum_holds_on_a_3000_unary_program():
    L = EX.Lib.get(); c = ctypes; nf = 3000; prog = [nf]
    for i in range(nf):
        prog += [1, 0, 1, 1, i]
    prog += [1, 0, 1, nf]
    for i in range(nf):
        prog += [0, i]
    prog += [0, 1, -1, 1, 0, 0, 1, 0]
    a = (c.c_int64 * len(prog))(*prog); qs = (c.c_char_p * (nf + 1))(*([b"1/1"] * (nf + 1))); d = (c.c_double * (nf + 1))(*([1.0] * (nf + 1))); caps = (c.c_uint64 * 5)(*([1 << 28] * 5)); err = c.c_int()
    h = L.gb_create(1, 53, a, len(prog), qs, d, nf, 0, caps, 0.0, c.byref(err)); assert h, err.value
    st = L.gb_forward(h); cnt = EX._counters(L, h); L.gb_destroy(h)
    assert st == 1 and cnt["polls"] >= 1 and cnt["lookups"] + nf + 1 + 1 <= 4096 + 1, cnt                                 # conversion units (nf+1) + push (1) + loads before the first poll <= quantum


def test_native_label_cap_and_range_fault_branches_fire(tmp_path):
    """genuine native label / range controls: (a) forced leaf labels of 2^51 make the kernel's label cap fault -> typed RANGE -> MPFR; (b) with the
    range envelope bypassed (qualification hook), 1e-200 leaves multiplied four times underflow -> the kernel's per-operation range check faults ->
    RANGE -> MPFR certifies; (c) a forced leaf label making (E_N + E_Z) u >= 1/2 is refused as UNSOUND_ROUTE -> MPFR."""
    L = EX.Lib.get(); card = [2, 2, 2]; facs = rnd_model(3, card, [(0, 1), (1, 2), (0, 2)]); mp, ep = write_uai(str(tmp_path / "m.uai"), card, facs); model = U.read_model(mp); Z, T = truth_rows(model, {})
    L.gb_test_leaf_label(1 << 51)
    try:
        rec = run("NATIVE_PLAIN_V2", mp, ep, str(tmp_path / "cap"), b64=True, rules=[], fallback=False)
    finally:
        L.gb_test_leaf_label(1)
    assert rec["route"] == "mpfr" and rec["attempts"][0]["route"] == "binary64" and rec["attempts"][0].get("refused", {}).get("kind") == "RANGE" and rec["attempts"][0].get("stop") == "RANGE" and contained(rec, T)
    L.gb_test_leaf_label(1 << 49)
    try:
        rec = run("NATIVE_PLAIN_V2", mp, ep, str(tmp_path / "void"), b64=True, rules=[], fallback=False)
    finally:
        L.gb_test_leaf_label(1)
    assert rec["route"] == "mpfr" and rec["attempts"][0].get("refused", {}).get("kind") == "UNSOUND_ROUTE" and rec["attempts"][0]["labels"]["E_N_max"] >= (1 << 49) and rec["attempts"][0]["delta_max"] >= 0.5 and contained(rec, T)
    L.gb_test_leaf_label(1 << 48)                                                                      # delta 0.44 < 1/2: admitted but TOO_WIDE -> MPFR (the enclosure stays sound, just useless)
    try:
        rec = run("NATIVE_PLAIN_V2", mp, ep, str(tmp_path / "wide"), b64=True, rules=[], fallback=False)
    finally:
        L.gb_test_leaf_label(1)
    assert rec["route"] == "mpfr" and rec["attempts"][0]["outcome"] == "TOO_WIDE" and 0.4 < rec["attempts"][0]["delta_max"] < 0.5 and contained(rec, T)
    tiny = ["%s" % Fr(1, 10 ** 200)] * 4; mp2, ep2 = write_uai(str(tmp_path / "u.uai"), [2, 2, 2], [((0, 1), [Fr(1)] * 4), ((1, 2), [Fr(1)] * 4), ((0, 2), [Fr(1)] * 4), ((0, 1), [Fr(1)] * 4)], tokens=[tiny, tiny, tiny, tiny]); model2 = U.read_model(mp2); Z2, T2 = truth_rows(model2, {})
    rec = EX.execute("NATIVE_PLAIN_V2", mp2, ep2, str(tmp_path / "under"), time.monotonic() + 60, {"budget_s": 60, "allow_binary64": True, "rules": [], "reference_fallback": False}, test_hooks={"skip_range_envelope": True})
    assert rec["attempts"][0]["route"] == "binary64" and rec["attempts"][0].get("stop") == "RANGE" and rec["attempts"][0]["stop_phase"] == "forward" and rec["route"] == "mpfr" and contained(rec, T2)


def test_H3_nested_supervisors_owned_tree_is_reconciled(tmp_path):
    """the reviewer's two-real-supervisor control: the outer leader exits while the inner supervisor's worker (own session) is alive; the ROOT owner
    kills + reaps the registered nested group and writes the missing nested receipt (PARENT_CLEANUP_KILL); nothing survives the outer receipt."""
    import psutil
    leaf = str(tmp_path / "leaf.json"); outer_led = str(tmp_path / "outer.jsonl"); inner_led = str(tmp_path / "inner.jsonl")
    leafcode = "import os,time,json;open(%r,'w').write(json.dumps({'pid':os.getpid(),'pgid':os.getpgrp()}));time.sleep(4)" % leaf
    inner = [PY, "-m", "gbidi.supervise", "--ledger", inner_led, "--scope", "inner", "--job", "inner", "--timeout", "1", "--", PY, "-c", leafcode]
    leadercode = "import subprocess,time,os;subprocess.Popen(%r,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL);p=%r\nt=time.monotonic()\nwhile not os.path.exists(p) and time.monotonic()-t<2:time.sleep(.01)\ntime.sleep(.1)\n" % (inner, leaf)
    r = subprocess.run([PY, "-m", "gbidi.supervise", "--ledger", outer_led, "--scope", "stage_outer_test", "--job", "stage_runner:test", "--timeout", "3", "--", PY, "-c", leadercode], capture_output=True, text=True, timeout=40, cwd=HERE, env=ENV)
    ident = json.load(open(leaf)); pid = ident["pid"]
    alive = psutil.pid_exists(pid) and psutil.Process(pid).status() != psutil.STATUS_ZOMBIE
    if alive:
        os.kill(pid, signal.SIGKILL)
    rc = [json.loads(x) for x in open(outer_led) if json.loads(x)["kind"] == "RECEIPT"][-1]; inner_rows = [json.loads(x) for x in open(inner_led)]
    assert not alive and ident["pgid"] != rc["pgid"] and rc["nested_groups_registered"] == 1 and rc["nested_groups_killed"] == 1 and rc["nested_groups_live_at_receipt"] == 0 and rc["cleanup_unresolved"] is False
    assert [x["kind"] for x in inner_rows] == ["START", "SPAWNED", "RECEIPT"] and inner_rows[-1]["outcome"] == "PARENT_CLEANUP_KILL" and inner_rows[-1]["written_by_parent"] == rc["jid"]
    # the ordinary nested completion: both receipts, parent_jid linkage, nothing killed
    o2 = str(tmp_path / "o2.jsonl"); i2 = str(tmp_path / "i2.jsonl")
    subprocess.run([PY, "-m", "gbidi.supervise", "--ledger", o2, "--scope", "stage_outer_test", "--job", "stage_runner:ok", "--timeout", "10", "--", PY, "-m", "gbidi.supervise", "--ledger", i2, "--scope", "inner", "--job", "inner", "--timeout", "5", "--", PY, "-c", "print(1)"], capture_output=True, timeout=40, cwd=HERE, env=ENV)
    ro = [json.loads(x) for x in open(o2) if json.loads(x)["kind"] == "RECEIPT"][-1]; ri = [json.loads(x) for x in open(i2) if json.loads(x)["kind"] == "RECEIPT"][-1]
    assert ro["outcome"] == "COMPLETED" and ro["nested_groups_killed"] == 0 and ri["outcome"] == "COMPLETED" and ri["parent_jid"] == ro["jid"]


def test_H1_all_primary_arms_end_to_end_through_harness_resume_and_closeout(tmp_path):
    """tiny qualification manifest (marked qualification_unfrozen; never a campaign): one tiny case x the four primary arms + the three ablation arms,
    run by gbidi.pilot.run under a REAL outer gbidi.supervise (the production composition), then resumed (no relaunch, no RESUME_CONFLICT), then
    closed out: every row ACCEPTED through the one reconciler with launch-relative delivery; comparators via the adapter with their pinned producers."""
    from gbidi import pilot as PI, reconcile as RC
    from gbidi_closeout import report as R
    D = str(tmp_path / "run"); os.makedirs(D); inputs = tmp_path / "inputs"; inputs.mkdir()
    card = [2, 3, 2]; facs = rnd_model(12, card, [(0, 1), (1, 2), (0, 2)]); dec = lambda q: "%d.%02d" % divmod(q.numerator * (100 // q.denominator), 100)      # the pinned producers read DECIMAL tokens (as the panel inputs are)
    mp, ep = write_uai(str(inputs / "X.uai"), card, facs, {2: 1}, tokens=[[dec(x) for x in tab] for _, tab in facs]); model = U.read_model(mp); Z, N = OR.brute(model, {2: 1})
    cfg_adp = os.path.join(HERE, "runs", "mdi_2026-10-28", "AGGREGATE_DP_CENSUS_2026-11-08", "CONFIG_new_arm.json"); br = json.load(open(os.path.join(HERE, "gbidi", "BUILD_RECORD.json")))
    import hashlib
    canon = lambda p: hashlib.sha256((" ".join(open(p).read().split())).encode()).hexdigest()
    case = {"family": "F", "model_path": mp, "evidence_path": ep, "raw_model_sha256": EX.sha_file(mp), "raw_evidence_sha256": EX.sha_file(ep), "canonical_model_sha256": canon(mp), "canonical_evidence_sha256": canon(ep), "variables": 3}
    src = ["gbidi/executor.py", "gbidi/kernel.cpp", "gbidi/pilot.py", "gbidi/reconcile.py", "gbidi/arm_adapter.py", "gbidi/supervise.py", "adp/cell.py", "bench/cells.py"]
    man = {"pass": "QUALIFICATION_E2E", "qualification_unfrozen": True, "frozen_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(time.time() - 2)), "commit": "unfrozen", "branch": "test", "seed": PI.SEED, "source_files_sha256": {f: EX.sha_file(os.path.join(HERE, f)) for f in src}, "kernel_binary_sha256": br["binary_sha256"], "config_adp_repaired_path": os.path.relpath(cfg_adp, HERE), "config_adp_repaired_sha256": EX.sha_file(cfg_adp), "common_rules": list(PL.COMMON_RULES),
           "ceiling_s": 28800.0, "closeout_reserve_s": 0.0, "cases": {"X": case}, "unavailable_slots": [], "cells": []}
    arms = ["GENERAL_BIDI_V2", "NATIVE_PLAIN_V2", "ADP_REPAIRED", "EXACT_LIBDAI", "A1_NO_DEMAND_MASKS", "A2_NO_FUSION", "A3_NO_RESPONSE_VIEWS"]
    for i, arm in enumerate(arms):
        c = {"stage": "primary_breadth" if i < 4 else "ablation_breadth", "arm": arm, "case": "X", "budget_s": 20.0, "kind": "primary" if i < 4 else "ablation"}; tid, cid = PI.canonical_task(case, c, man["config_adp_repaired_sha256"], br["binary_sha256"], man["commit"])
        man["cells"].append(dict(c, index=i, task_id=tid, cell_id=cid, producer_arm=arm if arm in PI.GB_ARMS else PI.PRODUCER_ARM[arm], out_dir="cells/%s/%03d__X__%s__20s__%s" % (c["stage"], i, arm, tid), max_permitted_charge_s=26.0))
    json.dump(man, open(os.path.join(D, "GB_MANIFEST.json"), "w")); assert PI.reconcile_manifest(man) is None
    def stage(name):
        return subprocess.run([PY, "-m", "gbidi.supervise", "--ledger", os.path.join(D, "GB_LEDGER.jsonl"), "--scope", "stage_outer_" + name, "--job", "stage_runner:" + name, "--timeout", "600", "--cwd", HERE, "--env", "PYTHONPATH=" + HERE, "--", PY, "-m", "gbidi.pilot", "run", D, name], capture_output=True, text=True, timeout=900, cwd=HERE, env=ENV)
    r1 = stage("primary_breadth"); assert "STOP" not in r1.stdout, r1.stdout[-800:] + r1.stderr[-800:]
    r2 = stage("ablation_breadth"); assert "STOP" not in r2.stdout, r2.stdout[-800:]
    rows = R.cells_ledger(D, man); assert all(r["accepted"] for r in rows), [(r["arm"], r["reasons"]) for r in rows if not r["accepted"]]
    assert {r["arm"]: r["status"] for r in rows} == {a: ("COMPLETE" if a == "EXACT_LIBDAI" else "CERTIFIED") for a in arms} and all(r["delivery_from_launch_s"] is not None and r["delivery_from_launch_s"] <= 20 for r in rows)
    for r in rows:                                                                                    # every arm's delivered rows are within 1/200 of the exact posterior
        pts, _ = U.read_mar(os.path.join(D, r["out_dir"], "output.MAR")); assert all(abs(Fr(pts[v][s]) - N[v][s] / Z) < Fr(1, 200) for v in range(3) for s in range(card[v])), r["arm"]
    led1 = open(os.path.join(D, "GB_LEDGER.jsonl")).read()
    r3 = stage("primary_breadth"); assert "RESUME_CONFLICT" not in r3.stdout and "STOP" not in r3.stdout, r3.stdout[-500:]                # resume: nothing relaunched
    led2 = open(os.path.join(D, "GB_LEDGER.jsonl")).read(); assert led2.count('"kind": "START"') == led1.count('"kind": "START"') + 1       # only the new outer start
    rows2 = R.cells_ledger(D, man); assert all(r["accepted"] for r in rows2)
    total, by, unresolved, extra = PI.charged(D); assert not unresolved and len(extra["outer_attempts"]) == 3 and all(o["parent_remainder_s"] is not None for o in extra["outer_attempts"]) and all(o["receipt"] for o in extra["outer_attempts"])
    B = R.budget(D, man, rows2); assert B["compliance"].startswith("every start") and B["total_charged_s"] == pytest.approx(total, abs=2e-3)
    # a stale record for the wrong budget (same arm, same inputs) is a RESUME_CONFLICT, never silently reused
    cj = os.path.join(D, man["cells"][1]["out_dir"], "cell.json"); rec1 = json.load(open(cj)); rec1["deadline_s"] = 120.0; json.dump(rec1, open(cj, "w"))
    r4 = stage("primary_breadth"); assert "RESUME_CONFLICT" in r4.stdout and json.load(open(os.path.join(D, "RUN_STOPPED.json")))["status"] == "RESUME_CONFLICT"
