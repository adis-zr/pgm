"""THIRD-REVIEW REPAIR CONTROLS of GENERAL_BIDI_COMPLETE_V3 (10 Nov 2026, packet c5e9578e…; correction brief A-G). Every control first failed or could not be
expressed on the delivered source f182a5c7 (reproductions: review_repro_r3/REPRO_R3_RESULTS.json) and passes on the repaired code.
  TA  sparse reverse without native recursion: deep retained-sparse equality chains (25k / 50k) under a one-byte pending cap and the DEFAULT stack certify;
      mixed queued / immediate; typed cap / deadline stops; both arithmetic routes; the 14-axis pressure control keeps 2 reverse reads
  TB  cold pricing over the EMITTED operand schedule: viewed retained child behind a STREAM GATHER (3-variable witness at every cap), the recursive
      wrapper family, all-retained controls, the old 511-tree and (2,32) alternatives -- all four row classes exact
  TC  shared-demand allocation: union reserved while cur + lifted are live (deterministic allocation-order observation), in-lift expiry, FULL on failure,
      ledger back to baseline, arm switch retained
  TD  exact numeral construction bounded BEFORE expansion: compact exponents (positive / negative), ordinary tokens, zero / cancellation, cap boundary,
      expired deadline; grammar documented
  TE  attempt-bound ownership evidence: naturally exited child (zero kills) accepted and resumed without relaunch; unrelated / duplicate / missing /
      unresolved-live owner rejected; deeper valid ownership chain accepted; ordinary live-child kill still accepted
  TF  proof-scope: the weighted class-times-class product passes coordinate typing alone and is rejected by the full validator (cardinality restriction);
      the lawful expansion-before-product certifies; the independent-root oracle agrees
  TG  package inventory derives from the qualification manifest (every suite module incl. this one)"""
from __future__ import annotations
import sys, os, json, time, copy, signal, subprocess, tracemalloc, itertools, shutil
import pytest
HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__))); sys.path.insert(0, HERE); sys.path.insert(0, os.path.join(HERE, "tests"))
sys.set_int_max_str_digits(0)
from fractions import Fraction as Fr
from gbidi3 import executor as EX, source as GS, trusted as TR, ir as IR, validate as GV, planner as PL, memory as GM, oracle as OR, demand as DM, reconcile as RC, pilot as PI
from gbidi3.clock import Clock, PlanStop
from gbidi.supervise import group_members
from adp import source as SRC
from ext import uai as U
import test_gbidi3_complete as Q
import test_gbidi3_repair_2026_11_10 as RT
import test_gbidi3_repair2_2026_11_10 as R2
PY = sys.executable; ENV = dict(os.environ, PYTHONPATH=HERE)
CHILD = os.path.join(HERE, "runs", "mdi_2026-10-28", "GENERAL_BIDI_COMPLETE_V3_2026-11-10", "review_repro_r3", "deep_sparse_child.py")


# ============================================================================================================ TA  deep sparse reverse without recursion (brief A)
@pytest.mark.parametrize("n,cap,b64", [(25000, 1, "1"), (50000, 1, "1"), (25000, 1, "0"), (25000, 200, "1")])
def test_TA1_deep_retained_sparse_chain_under_pending_pressure_certifies_on_the_default_stack(tmp_path, n, cap, b64):
    t = time.monotonic(); p = subprocess.run([PY, CHILD, str(n), str(cap), str(tmp_path), b64], capture_output=True, text=True, timeout=600, cwd=HERE, env=ENV)
    assert p.returncode == 0, (n, cap, b64, p.returncode, p.stderr[-400:])                                                                            # no signal exit (the delivered source: SIGSEGV at 25k / 50k with cap 1)
    r = json.loads(p.stdout.strip().splitlines()[-1]); assert r["status"] == "INTERVALS_OK" and r["truth"] is True and r["stack_limit"] <= 16 << 20, r
    assert r["sparse_reverse_rows"] == 2 * (n - 1) + 2 and (r["sparse_reverse_immediate"] >= 1 if cap < 1000 else r["sparse_reverse_immediate"] == 0), r   # support-indexed throughout: 2 retained rows per bucket; immediate deliveries only under pressure


def test_TA2_typed_stops_and_the_shallow_pressure_control_survive_the_frame_rewrite(tmp_path):
    n = 4000; mp, ep = Q.write_uai(str(tmp_path / "c.uai"), [2] * n, [((i, i + 1), [1, 0, 0, 1]) for i in range(n - 1)]); truth = {v: [Fr(1, 2), Fr(1, 2)] for v in range(n)}
    sw = dict(views=False, fusion=False, two_axis=False, demand_masks=False, orders=("original_id",)); hooks = {"mutate_program": Q.set_storage(IR.SPARSE, include_roots=True)}
    # scratch category too small for the continuation frames: typed MEMORY stop (fallback off -> RESOURCE_STOP), never a crash
    with pytest.raises(EX.Refuse) as ex:
        Q._run_cfg(mp, ep, str(tmp_path / "scratch"), rules=[], b64=True, hooks=hooks, ledger=GM.Ledger(dict(GM.CAPS, pending_adjoints=1, frames_scratch_pub=1 << 16)), fallback=False, **sw)
    assert ex.value.kind == "RESOURCE_STOP" and "MEMORY" in ex.value.reason, ex.value.reason
    # deadline inside the reverse: typed DEADLINE stop
    with pytest.raises(EX.Refuse) as ex:
        Q._run_cfg(mp, ep, str(tmp_path / "dl"), rules=[], b64=True, hooks=hooks, ledger=GM.Ledger(dict(GM.CAPS, pending_adjoints=1)), fallback=False, budget=0.02, **sw)
    assert ex.value.kind == "RESOURCE_STOP" and "DEADLINE" in ex.value.reason, ex.value.reason
    # ordinary cap and queued-only path: exact, max frame depth stays small
    r = Q._run_cfg(mp, ep, str(tmp_path / "ok"), rules=[], b64=False, hooks=hooks, fallback=False, **sw); c = Q.counters(r); assert Q.exact_rows(r, truth) and c["sparse_reverse_immediate"] == 0 and c["max_frame_depth"] <= 4
    # the 14-axis pressure control: still 2 reverse reads at every pending cap, on both routes
    K = 1 << 14; t = [0] * K; t[0] = 3; t[-1] = 5; mp2, ep2 = Q.write_uai(str(tmp_path / "s.uai"), [2] * 14, [(tuple(range(14)), t)]); S, Z, N, rows = Q.truth(mp2, ep2)
    for cap in (512 << 20, 1):
        for b64 in (False, True):
            r = Q.run("GENERAL_BIDI_COMPLETE_V3", mp2, ep2, str(tmp_path / ("p%d%d" % (cap, b64))), rules=[], b64=b64, ledger=GM.Ledger(dict(GM.CAPS, pending_adjoints=cap)), fallback=False); fw = r["attempts"][-1]["counters_after_forward"]; c = Q.counters(r)
            assert Q.contained(r, rows) and c["source_reads"] - fw["source_reads"] == 2 and c["sparse_reverse_rows"] == 2 and c["reverse_tuples"] == 0 and c["sparse_reverse_generic"] == 0, (cap, b64, c)


# ============================================================================================================ TB  cold pricing over the emitted schedule (brief B)
def _classes(rec):
    a = rec["attempts"][-1]; fw = a["counters_after_forward"]; c = a["counters"]; p = rec["plan"]["totals"]["predicted"]
    return [p["forward_rows"], p["reverse_value_rows"], p["reverse_pull_rows"] + p["sparse_pull_rows"], p["reverse_combined_rows"]], [fw["reduce_terms"], c["reverse_value_terms"], c["reverse_tuples"] + c["sparse_reverse_rows"], c["combined_terms"]]


def test_TB1_viewed_retained_child_behind_a_stream_gather_is_priced_exactly_at_every_cap(tmp_path):
    mp, ep = Q.write_uai(str(tmp_path / "m.uai"), [2, 2, 2], [((0, 2), [1, 2, 3, 5]), ((1, 2), [1, 2, 3, 6])]); S, Z, N, rows = Q.truth(mp, ep); seen = set()
    for cap in (160, 240, 320, 400, 1024):
        rec = Q._run_cfg(mp, ep, str(tmp_path / ("c%d" % cap)), rules=[], b64=False, two_axis=False, fusion=False, demand_masks=False, orders=("original_id",), ledger=GM.Ledger(dict(GM.CAPS, value_cache_blocks=cap))); c = Q.counters(rec); pred, got = _classes(rec)
        assert Q.exact_rows(rec, rows) and pred == got and c["downgrades"] == 0 and c["cache_hits"] == 0 and c["early_flushes"] == 0, (cap, pred, got, c["downgrades"])
        assert any(x["kind"] == "GATHER" and x["storage"] == IR.STREAM for x in rec["plan"]["node_table"]) and rec["mechanisms"]["views"]["compressed_axes"] >= 1          # the view wrapper IS in the executed program
        seen.add(tuple(x["storage"] for x in rec["plan"]["node_table"] if x["kind"] == "REDUCE"))
    assert len(seen) >= 2                                                                                                                             # several retention mixes (streamed / cached / dense children) were priced


@pytest.mark.parametrize("h", [1, 2, 3, 4])
def test_TB2_recursive_view_wrapper_family_all_four_row_classes_exact_and_the_proxy_covers_the_counted_work(tmp_path, h):
    card = [3]; fac = []; child = 0
    for _ in range(h):
        leaf = len(card); card.append(2); root = len(card); card.append(3); fac.extend([((child, root), [1, 2, 3, 2, 5, 7, 3, 7, 11]), ((leaf, root), [1, 2, 3, 2, 4, 6])]); child = root
    mp, ep = Q.write_uai(str(tmp_path / "h.uai"), card, fac); rows = R2._ve_truth(card, fac)
    rec = Q._run_cfg(mp, ep, str(tmp_path / "r"), rules=[], b64=False, two_axis=False, fusion=False, demand_masks=False, orders=("original_id",), budget=60, ledger=GM.Ledger(dict(GM.CAPS, value_cache_blocks=104 * (h + 1) + 8))); c = Q.counters(rec); pred, got = _classes(rec)
    assert Q.exact_rows(rec, rows) and pred == got and c["downgrades"] == 0 and c["cache_hits"] == 0, (h, pred, got)
    assert rec["plan"]["totals"]["cold_work_proxy"] >= c["adds"] + c["mults"] + c["source_reads"] and rec["plan"]["totals"]["cost_model"].startswith("compositional") and "assumptions" in rec["plan"]["totals"]   # the proxy covers the counted arithmetic + reads under its stated assumptions
    full = Q._run_cfg(mp, ep, str(tmp_path / "full"), rules=[], b64=False, two_axis=False, fusion=False, demand_masks=False, orders=("original_id",), budget=60); pf, gf = _classes(full); assert Q.exact_rows(full, rows) and pf == gf and gf[1] == 0   # all-retained counterpart: no reconstruction


def test_TB3_previous_cost_controls_still_hold_under_the_schedule_aware_recurrence(tmp_path):
    # the old 511-variable streamed tree (h = 3 here for time), the (2,32) one-/two-axis alternative, and a fused candidate: every class exact, both alternatives recorded
    card, facs = R2._tree(3); mp, ep = Q.write_uai(str(tmp_path / "t.uai"), card, facs); rows = R2._ve_truth(card, facs)
    cold = Q._run_cfg(mp, ep, str(tmp_path / "cold"), rules=[], b64=True, budget=60, ledger=GM.Ledger(dict(GM.CAPS, value_cache_blocks=1)), views=False, demand_masks=False, fusion=False, two_axis=False, orders=("original_id",)); pred, got = _classes(cold); assert Q.contained(cold, rows) and pred == got
    n = 32; f = [a + 1 for a in range(n)] + [2 * (a + 1) if a < n - 1 else 3 * (a + 1) for a in range(n)]; mp2, ep2 = Q.write_uai(str(tmp_path / "p.uai"), [2, n], [((0, 1), f)]); S, Z, N, rows2 = Q.truth(mp2, ep2)
    two = Q._run_cfg(mp2, ep2, str(tmp_path / "two"), rules=[], b64=False, two_axis=True, fusion=True); ch = [c for c in two["plan_candidates"] if c.get("chosen")][0]; alt = [c for c in two["plan_candidates"] if c.get("cutset") == "two_axis" and c.get("state") == "COMPLETE"]
    assert Q.exact_rows(two, rows2) and ch["cutset"] == "one_axis" and alt and alt[0]["totals"]["cold_work_proxy"] > ch["totals"]["cold_work_proxy"]; pred, got = _classes(two); assert pred == got
    for n3 in (3, 10):
        f3 = [1 + (i % 17) for i in range(n3 * n3)]; g3 = [(1 + a if a == b else 0) for a in range(n3) for b in range(n3)]; mp3, ep3 = Q.write_uai(str(tmp_path / ("d%d.uai" % n3)), [n3, n3, n3], [((0, 1), f3), ((1, 2), g3), ((2,), [1 + b for b in range(n3)])])
        unf = Q._run_cfg(mp3, ep3, str(tmp_path / ("u%d" % n3)), rules=[], b64=False, views=False, two_axis=False, fusion=False, orders=("original_id",)); mod = Q._run_cfg(mp3, ep3, str(tmp_path / ("m%d" % n3)), rules=[], b64=False, views=False, two_axis=False, fusion=True, orders=("original_id",))
        assert mod["plan"]["totals"]["cold_work_proxy"] <= unf["plan"]["totals"]["cold_work_proxy"] and _classes(mod)[0] == _classes(mod)[1] and _classes(unf)[0] == _classes(unf)[1]


# ============================================================================================================ TC  shared-demand allocation order and in-lift polling (brief C)
def _shared_fixture(n):
    m = U.Model(net_type="MARKOV", nvars=1, card=[n], factors=[U.Factor(scope=(0,), card=(n,), table=[Fr(1)] * n, index=0), U.Factor(scope=(0,), card=(n,), table=[Fr(2)] * n, index=1)])
    R = SRC.Reduced(EX._ModelAdapter(m), {}); R.reduce(()); T = TR.TrustedReduced(R); f1, f2 = T.factors
    P = IR.Program(); P.derived = {101: {"kind": "additive_split", "parent": f2.fid, "parts": [(1,) * n, (1,) * n], "index": 0}, 102: {"kind": "additive_split", "parent": f2.fid, "parts": [(1,) * n, (1,) * n], "index": 1}}
    f = P.source(f1.fid, (0,), (n,)); mk = P.marker(0, n); sh = P.mul([f, mk]); sh.storage = IR.DENSE
    h1 = P.source(101, (0,), (n,)); h2 = P.source(102, (0,), (n,)); add = P.addn([P.mul([sh, h1]), P.mul([sh, h2])]); r = P.reduce(add, {0}); r.storage = IR.DENSE; P.roots = [r.nid]; return P, T


def test_TC1_union_is_reserved_before_it_is_built_and_one_large_lift_expires_internally(tmp_path):
    n = 40000; P, T = _shared_fixture(n); tables = {f.fid: f.table for f in T.factors}; assert GV.validate(P, T).record["status"] == "VALID"
    # (1) in-lift expiry: a 40,000-index lift under a 1 ms optional allowance stops INSIDE the lift (typed DISCOVERY_WALL), nothing applied
    clock = Clock(time.monotonic() + 60, 20); clock.row_cap = n + 1; clock.optional_allowance_s = 0.001; clock.begin_optional(); t = time.monotonic(); r = DM.compile_demand(P, row_cap=n + 1, clock=clock, ledger=GM.Ledger(), tables=tables)
    assert r["stop"] and r["stop"]["kind"] == "DISCOVERY_WALL" and clock.expired and r["restricted"] == [] and all(x.demand == "FULL" for x in P.nodes) and time.monotonic() - t < 0.5, (r["stop"], clock.record())
    # (2) allocation order at the union boundary: the union's reservation is REQUESTED while the live traced bytes still hold cur + lifted and BEFORE the union exists
    P, T = _shared_fixture(n)
    class RecordingLedger(GM.Ledger):
        def __init__(self, caps):
            super().__init__(caps); self.events = []
        def reserve(self, cat, nb, what):
            cur, peak = tracemalloc.get_traced_memory(); self.events.append({"request": nb, "used_before": self.used[cat], "traced_before": cur, "what": what}); return super().reserve(cat, nb, what)
    led = RecordingLedger(dict(GM.CAPS)); clock = Clock(time.monotonic() + 60, 200); clock.row_cap = 10 ** 6; clock.optional_allowance_s = 60; tracemalloc.start(); r = DM.compile_demand(P, row_cap=10 ** 6, clock=clock, ledger=led, tables=tables); cur, peak = tracemalloc.get_traced_memory(); tracemalloc.stop()
    unions = [e for e in led.events if e["what"].startswith("demand set (%d indices)" % n) and e["used_before"] >= DM.Budget.SET_BYTES_PER_INDEX * n]   # a union request made while a lift temporary of n indices is already charged
    assert unions and r["stop"] is None and r["restricted"] == [] and led.used["source_ir_maps_output"] == 0, (len(unions), r["stop"], led.used)
    assert peak <= r["peak_live_bytes"] + 400_000, (peak, r["peak_live_bytes"])                                                                       # the traced peak is covered by the compiler's own live-set accounting (proxy, not RSS)
    # (3) a cap that fails exactly at the union request: typed MEMORY stop, FULL everywhere, ledger back to zero, no union was built beyond the reservation point
    P, T = _shared_fixture(n); cap = DM.Budget.SET_BYTES_PER_INDEX * n + 512 + 256 + 400; led = RecordingLedger(dict(GM.CAPS, source_ir_maps_output=cap)); clock = Clock(time.monotonic() + 60, 200); clock.row_cap = 10 ** 6; clock.optional_allowance_s = 60
    r = DM.compile_demand(P, row_cap=10 ** 6, clock=clock, ledger=led, tables=tables); assert r["stop"]["kind"] == "MEMORY_CATEGORY" and r["restricted"] == [] and led.used["source_ir_maps_output"] == 0 and all(x.demand == "FULL" for x in P.nodes)
    # (4) through the executor on both arms the behaviour is unchanged (enabled restricts, disabled keeps FULL) on the small shared witness
    mp, ep = Q.write_uai(str(tmp_path / "sh.uai"), [3], [((0,), [1, 2, 3]), ((0,), [1, 0, 1])]); S, Z, N, rows = Q.truth(mp, ep)
    def mut(Pp):
        S_, R_, T_, plan, _ = Q.plan_program(mp, ep); P2 = R2._shared_program(T_); Pp.nodes = P2.nodes; Pp.roots = P2.roots; Pp.derived = P2.derived
    g = Q.run("GENERAL_BIDI_COMPLETE_V3", mp, ep, str(tmp_path / "g"), rules=[], b64=False, hooks={"mutate_program": mut}); a = Q.run("A1_NO_DEMAND_MASKS", mp, ep, str(tmp_path / "a"), rules=[], b64=False, hooks={"mutate_program": mut})
    assert Q.exact_rows(g, rows) and Q.exact_rows(a, rows) and g["demand_all_consumers"]["restricted"] == [2] and a["demand_all_consumers"]["restricted"] == []


# ============================================================================================================ TD  exact numerals bounded before expansion (brief D)
def test_TD1_compact_exponent_numerals_are_refused_before_expansion_and_ordinary_tokens_parse(tmp_path):
    for tok in ("1e1000000", "1e100000", "1e-1000000", "2.5e+300000", "1E900000"):
        data = ("MARKOV 1 2 1 1 0 2 %s 1" % tok).encode(); led = GM.Ledger(dict(GM.CAPS, source_ir_maps_output=65536)); g = GS._Guard(led, time.monotonic() + 60); tracemalloc.start()
        with pytest.raises(GS.ParseStop) as ex:
            GS.parse_model_bytes(data, g)
        peak = tracemalloc.get_traced_memory()[1]; tracemalloc.stop()
        assert ex.value.kind == "MEMORY_CATEGORY" and "exact numeral" in ex.value.reason and peak < 50_000, (tok, ex.value.reason[:120], peak)        # refused BEFORE the big integer exists (the delivered source built 3.3 M bits and charged 1.8 KB)
    for tok, val in (("1/3", Fr(1, 3)), ("0.25", Fr(1, 4)), ("3", Fr(3)), ("1e3", Fr(1000)), ("2.5e-2", Fr(1, 40)), ("0e5", Fr(0)), ("0.000", Fr(0)), (".5", Fr(1, 2)), ("7.", Fr(7)), ("+1.5", Fr(3, 2)), ("10/4", Fr(5, 2)), ("1E2", Fr(100))):
        led = GM.Ledger(dict(GM.CAPS, source_ir_maps_output=65536)); m = GS.parse_model_bytes(("MARKOV 1 2 1 1 0 2 %s 1" % tok).encode(), GS._Guard(led, time.monotonic() + 60)); assert m.factors[0].table[0] == val and led.used["source_ir_maps_output"] < 4096, (tok, led.used)
    # a moderately large but admissible numeral is charged by its bit bound (cancellation 1e300/1e300 is still built exactly then normalized: the bound covers the unreduced form)
    led = GM.Ledger(); m = GS.parse_model_bytes(b"MARKOV 1 2 1 1 0 2 1e300 1", GS._Guard(led, time.monotonic() + 60)); assert m.factors[0].table[0] == Fr(10) ** 300 and led.used["source_ir_maps_output"] > 300
    # grammar: underscores / spaces / malformed forms are INVALID_INPUT (documented restriction: UAI numerals are decimal / exponent / a/b only), not expansion
    for bad in ("1_000", "1e5/3", "1.5/2", "e5", "--1", "1e", "0x10"):
        with pytest.raises(GS.InvalidInput):
            GS.parse_model_bytes(("MARKOV 1 2 1 1 0 2 %s 1" % bad).encode())
    # cap boundary: the same token passes under a cap that admits its bound and is refused one byte below
    nb, db = GS.numeral_bits_bound("1e20000"); need = (nb + db) // 8 * 3 + 2 * len("1e20000") - GS.RATIONAL_BYTES; base = GS.Snapshot.__name__ and 0
    small = GM.Ledger(dict(GM.CAPS, source_ir_maps_output=1 << 20)); GS.parse_model_bytes(b"MARKOV 1 2 1 1 0 2 1e20000 1", GS._Guard(small, time.monotonic() + 60)); used = small.used["source_ir_maps_output"]
    with pytest.raises(GS.ParseStop):
        GS.parse_model_bytes(b"MARKOV 1 2 1 1 0 2 1e20000 1", GS._Guard(GM.Ledger(dict(GM.CAPS, source_ir_maps_output=used - 1)), time.monotonic() + 60))
    # expired deadline during a long numeral's conversion work is polled (units of 4,096 bits)
    g = GS._Guard(None, time.monotonic() - 1)
    with pytest.raises(GS.ParseStop) as ex:
        GS._rational_token("1e50000", "x", g)
    assert ex.value.kind == "DEADLINE"
    # canonical serialization of an admitted big rational is reserved before it is formatted
    m = GS.parse_model_bytes(b"MARKOV 1 2 1 1 0 2 1e3000 1"); g = GS._Guard(GM.Ledger(dict(GM.CAPS, source_ir_maps_output=200)), time.monotonic() + 60)
    with pytest.raises(GS.ParseStop):
        GS.canonical_v2_model(m, g)
    # through the executor: a typed RESOURCE_STOP, never a Python error
    mp = str(tmp_path / "big.uai"); open(mp, "w").write("MARKOV 1 2 1 1 0 2 1e1000000 1\n"); open(mp + ".evid", "w").write("")
    with pytest.raises(EX.Refuse) as ex:
        EX.execute("GENERAL_BIDI_COMPLETE_V3", mp, mp + ".evid", str(tmp_path / "x"), time.monotonic() + 20, {"budget_s": 20}, ledger=GM.Ledger(dict(GM.CAPS, source_ir_maps_output=1 << 20)))
    assert ex.value.kind == "RESOURCE_STOP" and "exact numeral" in ex.value.reason
    # the repaired lcm fallback and cumulative parser polling controls stay in force (first / second review)
    assert "lcm" in open(os.path.join(HERE, "gbidi3", "executor.py")).read() and "cumulative" in GS._Guard.tick.__doc__


# ============================================================================================================ TE  attempt-bound ownership evidence (brief E)
def _stage(D, name, timeout="60"):
    return subprocess.run([PY, "-m", "gbidi.supervise", "--ledger", os.path.join(D, "GB_LEDGER.jsonl"), "--scope", "stage_outer_" + name, "--job", "stage_runner:" + name, "--timeout", timeout, "--cwd", HERE, "--env", "PYTHONPATH=" + HERE, "--", PY, "-m", "gbidi3.pilot", "run", D, name], capture_output=True, text=True, cwd=HERE, env=ENV, timeout=600)


def test_TE1_naturally_exited_child_before_parent_cleanup_is_accepted_zero_kills_and_resumes_without_relaunch(tmp_path):
    D = str(tmp_path / "run"); os.makedirs(D); mp = tmp_path / "s.uai"; ep = tmp_path / "s.uai.evid"; mp.write_text("MARKOV\n1\n2\n1\n1 0\n2 1 2\n"); ep.write_text("")
    S = GS.Snapshot(str(mp), str(ep)); cs = RT._case(S, str(mp), str(ep), 1); man = RT._manifest(tmp_path, {"synthetic": cs}, [{"stage": "review", "arm": "GENERAL_BIDI_COMPLETE_V3", "case": "synthetic", "budget_s": 0.001, "kind": "primary"}]); json.dump(man, open(os.path.join(D, "GB_MANIFEST.json"), "w"), indent=1); led = os.path.join(D, "GB_LEDGER.jsonl")
    cmd = [PY, "-m", "gbidi.supervise", "--ledger", led, "--scope", "stage_outer_review", "--job", "stage_runner:empty_group", "--timeout", "20", "--cwd", HERE, "--env", "PYTHONPATH=" + HERE, "--", PY, "-m", "gbidi3.pilot", "run", D, "review"]
    p = subprocess.Popen(cmd, cwd=HERE, env=ENV, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True); paused = stage = sp = None; empty = False
    try:
        for _ in range(8000):
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
                        paused = starts[1]["supervisor_pid"]; stage = spawn[0]["pid"]; sp = spawn[1]
                        try:
                            os.kill(paused, signal.SIGSTOP)
                        except ProcessLookupError:
                            paused = None
                        break
            if p.poll() is not None:
                break
            time.sleep(0.001)
        if paused is None:
            pytest.skip("the inner supervisor finished before it could be paused (timing-dependent fixture); the real lifecycle is also exercised by SF1")
        for _ in range(5000):
            if not group_members(sp["pgid"]):
                empty = True; break
            time.sleep(0.001)
        assert empty, "the cell did not exit naturally"
        os.kill(stage, signal.SIGKILL); out, err = p.communicate(timeout=60)
    finally:
        if p.poll() is None:
            p.kill(); p.wait()
        if paused:
            try:
                os.kill(paused, signal.SIGKILL)
            except ProcessLookupError:
                pass
    rows = [json.loads(x) for x in open(led)]; rc = [r for r in rows if r["kind"] == "RECEIPT"]; cell_rc = [r for r in rc if r["job"].startswith("cell:")][0]; owner = [r for r in rc if r["job"] == "stage_runner:empty_group"][0]
    assert cell_rc["outcome"] == "PARENT_CLEANUP_KILL" and cell_rc["wall_s"] is None and owner["nested_groups_registered"] == 1 and owner["nested_groups_killed"] == 0 and owner["nested_groups_live_at_receipt"] == 0 and owner["group_empty_at_receipt"] is True
    c = man["cells"][0]; row = RC.reconcile(D, man, c, RC.ledger_index(D)); assert row["accepted"] and row["status"] == "RESOURCE_STOP" and row["cleanup_evidence_reference"]["owner_nested_killed"] == 0, row["reasons"]   # proved empty, zero kills: accepted as the typed noncertifying attempt it is
    total, by, unresolved, extra = PI.charged(D); assert not unresolved and extra["unknown_wall_receipts"] and extra["measured_s"] == 0.0
    led1 = open(led).read(); r2 = _stage(D, "review"); assert "RESUME_CONFLICT" not in r2.stdout and "STOP:" not in r2.stdout, r2.stdout[-500:]
    led2 = open(led).read(); assert led2.count('"kind": "START"') == led1.count('"kind": "START"') + 1 and led2.count("cell:") == led1.count("cell:")


def test_TE2_owner_evidence_is_unique_and_bound_to_the_attempts_ownership_chain(tmp_path):
    # a REAL stage-kill run (live child, one kill) as the positive control; every adversarial variant operates on a COPY of its files
    D = str(tmp_path / "run"); os.makedirs(D); n = 20000; mp = tmp_path / "c.uai"; ep = tmp_path / "c.uai.evid"
    mp.write_text("\n".join(["MARKOV", str(n), " ".join(["2"] * n), str(n - 1)] + ["2 %d %d" % (i, i + 1) for i in range(n - 1)] + ["4 1 2 3 4"] * (n - 1)) + "\n"); ep.write_text("")
    S = GS.Snapshot(str(mp), str(ep)); cs = RT._case(S, str(mp), str(ep), n); man = RT._manifest(tmp_path, {"synthetic": cs}, [{"stage": "review", "arm": "GENERAL_BIDI_COMPLETE_V3", "case": "synthetic", "budget_s": 20.0, "kind": "primary"}]); json.dump(man, open(os.path.join(D, "GB_MANIFEST.json"), "w"), indent=1); led = os.path.join(D, "GB_LEDGER.jsonl")
    cmd = [PY, "-m", "gbidi.supervise", "--ledger", led, "--scope", "stage_outer_review", "--job", "stage_runner:review", "--timeout", "60", "--cwd", HERE, "--env", "PYTHONPATH=" + HERE, "--", PY, "-m", "gbidi3.pilot", "run", D, "review"]
    p = subprocess.Popen(cmd, cwd=HERE, env=ENV, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True); killed = None
    try:
        for _ in range(8000):
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
        p.communicate(timeout=120)
    finally:
        if p.poll() is None:
            p.kill(); p.wait()
    assert killed is not None; c = man["cells"][0]; row = RC.reconcile(D, man, c, RC.ledger_index(D)); assert row["accepted"] and row["resolution"] == "PARENT_CLEANUP_KILLED_NO_RECORD", row["reasons"]
    orig = [json.loads(x) for x in open(led)]; owner = next(x for x in orig if x["kind"] == "RECEIPT" and x["job"] == "stage_runner:review"); child_rc = next(x for x in orig if x["kind"] == "RECEIPT" and x["job"].startswith("cell:"))
    def variant(name, mutate):
        dest = str(tmp_path / name); shutil.copytree(D, dest); rows = copy.deepcopy(orig)
        for r in rows:
            if r["kind"] == "START" and r.get("cmd"):
                r["cmd"] = [x.replace(D, dest) for x in r["cmd"]]
        rows = mutate(rows); open(os.path.join(dest, "GB_LEDGER.jsonl"), "w").write("".join(json.dumps(x) + "\n" for x in rows)); return RC.reconcile(dest, man, c, RC.ledger_index(dest))
    assert variant("control", lambda rows: rows)["accepted"]
    # unrelated GENUINE owner: a complete foreign lifecycle appended, the child receipt pointed at it -> not an ancestor / registered owner -> rejected
    foreign = [dict(copy.deepcopy(x), jid=x["jid"].replace("stage_runner:review", "stage_runner:other"), job="stage_runner:other") for x in orig if x["jid"] == owner["jid"]]
    def unrelated(rows):
        rows = rows + foreign
        for r in rows:
            if r.get("outcome") == "PARENT_CLEANUP_KILL":
                r["written_by_parent"] = foreign[0]["jid"]
        return rows
    r = variant("unrelated", unrelated); assert not r["accepted"] and any("unrelated" in x or "ancestor" in x for x in r["reasons"]), r["reasons"]
    # duplicate conflicting owner receipt -> not unique -> rejected
    def dup(rows):
        bad = copy.deepcopy(owner); bad["cleanup_unresolved"] = True; bad["group_empty_at_receipt"] = False; bad["nested_groups_live_at_receipt"] = 1; return rows + [bad]
    r = variant("dup", dup); assert not r["accepted"] and any("exactly one" in x for x in r["reasons"]), r["reasons"]
    r = variant("missing", lambda rows: [x for x in rows if not (x["kind"] == "RECEIPT" and x["jid"] == owner["jid"])]); assert not r["accepted"] and any("found 0" in x for x in r["reasons"])
    def live(rows):
        for x in rows:
            if x["kind"] == "RECEIPT" and x["jid"] == owner["jid"]:
                x["nested_groups_live_at_receipt"] = 1
        return rows
    r = variant("live", live); assert not r["accepted"] and any("closure" in x for x in r["reasons"])
    def wrong_pid(rows):
        for x in rows:
            if x.get("outcome") == "PARENT_CLEANUP_KILL":
                x["pid"] = x["pid"] + 1
        return rows
    r = variant("pid", wrong_pid); assert not r["accepted"] and any("pid / pgid" in x for x in r["reasons"])
    # deeper VALID ownership chain: the owner is the GRANDPARENT (an outer attempt whose START chain reaches the child); accepted when its receipt is unique and establishes the closure
    def deeper(rows):
        outer = {"kind": "START", "jid": "outer:x|20261110T000000Z|1", "scope": "stage_outer_root", "job": "outer:x", "start_utc": "2026-11-10T00:00:00Z", "cmd": [], "parent_jid": None, "max_permitted_charge_s": 100.0}
        outer_rc = dict(copy.deepcopy(owner), jid=outer["jid"], job="outer:x", parent_jid=None)
        for x in rows:
            if x["kind"] == "START" and x["jid"] == owner["jid"]:
                x["parent_jid"] = outer["jid"]
            if x.get("outcome") == "PARENT_CLEANUP_KILL":
                x["written_by_parent"] = outer["jid"]
        return [outer] + rows + [outer_rc]
    r = variant("deeper", deeper); assert r["accepted"] and r["cleanup_evidence_reference"]["owner_jid"] == "outer:x|20261110T000000Z|1", r["reasons"]


# ============================================================================================================ TF  proof-scope correction (brief F)
def test_TF1_weighted_class_product_passes_coordinate_typing_alone_but_the_full_validator_rejects_it_and_the_lawful_expansion_certifies(tmp_path):
    mp, ep, S, T, truth = R2.snap(tmp_path, "cp", [2, 2, 2], [((0, 1), (1, 2, 3, 6)), ((2, 1), (2, 4, 5, 10))])
    def build(expand_first):
        P = IR.Program(); msgs = []; w = ((0,), (0, 0), (Fr(1), Fr(2)))
        for f, v in zip(T.factors, (0, 2)):
            src = P.source(f.fid, f.scope, f.card); mark = P.marker(v, 2); m = P.mul([src, mark]); r = P.reduce(m, (v,), reps={1: w})
            if expand_first:
                r = P.gather(r, (1,), (2,), gaxes=[{"out_pos": 0, "cls": w[1], "ratio": w[2]}])
            msgs.append(r)
        m = P.mul(msgs)
        if not expand_first:
            m = P.gather(m, (1,), (2,), gaxes=[{"out_pos": 0, "cls": w[1], "ratio": w[2]}])
        bm = P.marker(1, 2); root = P.reduce(P.mul([m, bm]), (1,)); P.roots = [root.nid]; return P
    IR.coordinate_domains(build(False), T.dom)                                                                                                        # coordinate rules ALONE accept it (the proof-scope gap I12 overstated)
    with pytest.raises(TR.Invalid) as ex:
        GV.validate(build(False), T)
    assert "cardinality" in ex.value.reason                                                                                                            # the full validator rejects it through the non-REDUCE raw-cardinality restriction
    V = GV.validate(build(True), T); assert RT.jet_rows(V) == truth; R2.both_routes_certify(mp, ep, lambda: build(True), truth, tmp_path, "cp")
    # the only identical-CLASS products the full grammar can pass are singleton permutations, whose ratios are provably unit
    P = IR.Program(); f = P.source(T.factors[0].fid, (0, 1), (2, 2)); ma = P.marker(0, 2); r = P.reduce(P.mul([f, ma]), (0,), reps={1: ((1, 0), (1, 0), (Fr(1), Fr(1)))}); g = P.gather(r, (1,), (2,), gaxes=[{"out_pos": 0, "cls": (1, 0), "ratio": (Fr(1), Fr(1))}])
    f2 = P.source(T.factors[1].fid, (2, 1), (2, 2)); mc = P.marker(2, 2); r2 = P.reduce(P.mul([f2, mc]), (2,), reps={1: ((1, 0), (1, 0), (Fr(1), Fr(1)))}); g2 = P.gather(r2, (1,), (2,), gaxes=[{"out_pos": 0, "cls": (1, 0), "ratio": (Fr(1), Fr(1))}]); mb = P.marker(1, 2); root = P.reduce(P.mul([g, g2, mb]), (1,)); P.roots = [root.nid]
    assert RT.jet_rows(GV.validate(P, T)) == truth
    with pytest.raises(TR.Invalid):
        P2 = IR.Program(); f = P2.source(T.factors[0].fid, (0, 1), (2, 2)); ma = P2.marker(0, 2); P2.reduce(P2.mul([f, ma]), (0,), reps={1: ((1, 0), (1, 0), (Fr(1), Fr(3)))}); P2.roots = [P2.reduce(P2.nodes[-1], (1,)).nid]; GV.validate(P2, T)   # a permutation with a non-unit ratio is not a witness
    notes = open(os.path.join(HERE, "runs", "mdi_2026-10-28", "GENERAL_BIDI_COMPLETE_V3_2026-11-10", "PROOF_NOTES_COORDINATE_TYPING_AND_COLD_RECURRENCES.md")).read(); assert "I12" in notes and "raw-cardinality restriction" in notes and "unit ratios" in notes


# ============================================================================================================ TG  package inventory (brief G)
def test_TG1_package_inventory_derives_from_the_qualification_manifest_and_names_every_suite_module():
    from gbidi3_closeout import package as PK
    assert "tests/test_gbidi3_repair2_2026_11_10.py" in PK.TEST_FILES_DEFAULT and "tests/test_gbidi3_repair3_2026_11_10.py" in PK.TEST_FILES_DEFAULT
    D = os.path.join(HERE, "runs", "mdi_2026-10-28", "GENERAL_BIDI_COMPLETE_V3_2026-11-10")
    if os.path.exists(os.path.join(D, "QUALIFICATION_MANIFEST.json")):
        files, ids = PK.test_inventory(D); assert set(PK.TEST_FILES_DEFAULT) <= set(files) and all(os.path.exists(os.path.join(HERE, f)) for f in files)
