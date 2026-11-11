"""FOURTH-REVIEW REPAIR CONTROLS of GENERAL_BIDI_COMPLETE_V3 (10 Nov 2026, packet 757dc081…; correction brief A-D). Every control first failed or could not be
expressed on the delivered source 7eb9ee96 (reproductions: review_repro_r4/REPRO_R4_RESULTS.json) and passes on the repaired code.
  UA  ONE sparse-driver contract (ir.SPARSE_DRIVER_POLICY) across planner, emitted REDUCE.driver and kernel: the ordinary-default fixture (11 binary variables,
      unary [1,2], 16 positive wide entries, all common reductions, three orders / views / demand / fusion / two-axis) predicts the joined rows the kernel
      visits (16 / 16, not 16 / 2,048) with an exact source oracle; unary / wide permutation; support densities and scopes; an eligible SPARSE-child driver;
      zero products; no driver available (explicit diagnosed downgrade); a planned driver made unavailable (sparse_driver_deviation) and a written driver the
      run-time policy would not choose (sparse_driver_policy_differs, still executed); visited sparse_rows_joined and driver scans are counted AND priced
      (proxy >= adds + mults + source reads); the previous view-wrapper / 511-tree / one- and two-axis controls are retained by re-running their suites
  UB  shared-demand export OWNERSHIP: a successful nonempty restriction keeps a positive retained charge on the ledger (owned by the program), repeated
      compilation replaces the charge exactly once, an export-cap refusal is atomic (no partially changed program, no temporary leak), release_hints
      restores the baseline; through the executor the mutable program's charge is released after validation (the validated copy carries its own
      reservation); the switches / aggregate budgets / union precharge / in-lift polling / FULL-on-exhaustion controls stay in force (SD1 / SD2 / TC1)
  UC  POSITIVE, mutually compatible owner closure evidence on COPIES of a real parent-cleanup ledger: missing closure fields, CLEANUP_UNRESOLVED outcome,
      nonempty nested_live list, missing owner START / SPAWNED, duplicate conflicting owner START, non-integer live count -> rejected with typed reasons;
      the genuine ledger (one kill) and zero-kill closures stay accepted (TE1 / TE2 / SF1 re-run the real natural-exit and live-child recovery / resume)
  UD  direct-API typed error for over-long exponents under the ordinary interpreter digit limit (production cells disable the limit); grammar unchanged
  UE  package inventory and closeout rows name this module"""
from __future__ import annotations
import sys, os, json, time, copy, random, shutil, tracemalloc
import pytest
HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__))); sys.path.insert(0, HERE); sys.path.insert(0, os.path.join(HERE, "tests"))
sys.set_int_max_str_digits(0)
from fractions import Fraction as Fr
from gbidi3 import executor as EX, source as GS, trusted as TR, ir as IR, validate as GV, planner as PL, memory as GM, demand as DM, reconcile as RC
from gbidi3.clock import Clock
from adp import source as SRC
from ext import uai as U
import test_gbidi3_complete as Q
import test_gbidi3_repair2_2026_11_10 as R2
SW = dict(two_axis=True, fusion=True, demand_masks=True, views=False, orders=("original_id",), budget=30)
R2_FIXTURE = os.path.join(HERE, "runs", "mdi_2026-10-28", "GENERAL_BIDI_COMPLETE_V3_2026-11-10", "review_repro_r2", "pilot_parent_cleanup", "run")


def _driver_view(rec):
    c = Q.counters(rec); t = rec["plan"]["totals"]; p = t["predicted"]
    return {"status": rec["status"], "proxy": t["cold_work_proxy"], "ops": c["adds"] + c["mults"] + c["source_reads"], "pred_joined": p["sparse_joined"], "actual_joined": c["sparse_rows_joined"], "pred_scans": p["sparse_driver_scans"], "scans": c["sparse_driver_scans"],
            "zero_skips": c["zero_skips"], "downgrades": c["downgrades"], "deviation": c["sparse_driver_deviation"], "differs": c["sparse_driver_policy_differs"], "cache_hits": c["cache_hits"], "early_flushes": c["early_flushes"],
            "sparse": [(x["nid"], x["axes"], x["prov"].get("sparse_driver")) for x in rec["plan"]["node_table"] if x["kind"] == "REDUCE" and x["storage"] == IR.SPARSE]}


def _schedule_matches(v):
    """the contract: the kernel visits exactly the joined rows the planner priced, scans exactly the operands the planner priced, and the ONE proxy covers the counted primitives"""
    assert v["status"] == "INTERVALS_OK" and v["cache_hits"] == 0 and v["downgrades"] == 0 and v["early_flushes"] == 0 and v["deviation"] == 0 and v["differs"] == 0, v
    assert v["pred_joined"] == v["actual_joined"] and v["pred_scans"] == v["scans"] and v["proxy"] >= v["ops"], v


# ============================================================================================================ UA  one sparse-driver contract (brief A)
def test_UA1_ordinary_default_fixture_predicts_the_joined_rows_the_kernel_visits_and_the_proxy_covers_the_counted_work(tmp_path):
    for n in (8, 11):
        rng = random.Random(386731 + n); positions = rng.sample(range(1 << n), 16); tab = [0] * (1 << n)
        for i, p in enumerate(positions):
            tab[p] = i + 1
        mp, ep = Q.write_uai(str(tmp_path / ("n%d.uai" % n)), [2] * n, [((0,), [1, 2]), (tuple(range(n)), tab)]); truth = Q.truth(mp, ep)[-1]
        rec = Q.run("GENERAL_BIDI_COMPLETE_V3", mp, ep, str(tmp_path / ("n%d" % n)), b64=False, budget=30, rules=list(PL.COMMON_RULES), fallback=False); v = _driver_view(rec)
        assert Q.contained(rec, truth) and (rec.get("reductions") or {}).get("steps") in (0, None) and v["sparse"], v                                   # the ordinary GENERAL path: reductions change nothing, one SPARSE bucket
        _schedule_matches(v); assert v["pred_joined"] == 16 and v["actual_joined"] == 16, v                                                               # the delivered source: 16 predicted / 2,048 visited (the unary drove ten free axes)
        assert any("SOURCE" in (d or "") and "support 16" in (d or "") for _, _, d in v["sparse"]), v["sparse"]                                              # the wide factor's 16 supported rows drive, as priced
    r = rec["plan"]["totals"]; assert r["assumptions"].startswith("CONDITIONAL") and "sparse_driver_deviation" in r["assumptions"] and "sparse_driver_policy_differs" in r["assumptions"]


@pytest.mark.parametrize("n", [5, 8, 11])
def test_UA2_source_order_permutation_does_not_change_the_priced_schedule(tmp_path, n):
    tab = [1, 2] + [0] * ((1 << n) - 2); wide = (tuple(range(n)), tab); unary = ((0,), [1, 0]); views = []
    for order, fac in (("wide_first", [wide, unary]), ("unary_first", [unary, wide])):
        mp, ep = Q.write_uai(str(tmp_path / ("%s.uai" % order)), [2] * n, fac); truth = Q.truth(mp, ep)[-1]
        rec = Q._run_cfg(mp, ep, str(tmp_path / order), rules=[], b64=False, **SW); v = _driver_view(rec); assert Q.contained(rec, truth); _schedule_matches(v); views.append(v)
        assert v["pred_joined"] == 2 and v["actual_joined"] == 2, v                                                                                        # the delivered source visited 2^(n-1) rows here (unary support 1 preferred by absolute count)
    assert views[0]["proxy"] == views[1]["proxy"] and views[0]["actual_joined"] == views[1]["actual_joined"]


@pytest.mark.parametrize("k", [1, 4, 32, 128, 256])
def test_UA3_support_densities_from_one_entry_to_fully_positive(tmp_path, k):
    rng = random.Random(1000 + k); tab = [0] * 256
    for p in rng.sample(range(256), k):
        tab[p] = rng.randint(1, 9)
    mp, ep = Q.write_uai(str(tmp_path / "d.uai"), [2] * 8, [((0,), [1, 2]), (tuple(range(8)), tab)]); truth = Q.truth(mp, ep)[-1]
    rec = Q._run_cfg(mp, ep, str(tmp_path / "d"), rules=[], b64=False, **SW); v = _driver_view(rec); assert Q.contained(rec, truth); _schedule_matches(v)
    if k < 256:
        assert v["sparse"] and v["pred_joined"] == k and v["scans"] == 258, v                                                                             # support k drives with no free axis; both source operands are scanned once (2 + 256)
    else:
        assert not v["sparse"] and v["pred_joined"] == 0, v                                                                                              # a fully positive table: the DENSE alternative is cheaper; no sparse bucket, no scan


def test_UA4_mixed_cardinalities_and_a_partial_scope_drive_from_the_scanned_support(tmp_path):
    rng = random.Random(77); tab = [0] * (3 * 2 * 3 * 2 * 2 * 3)
    for p in rng.sample(range(len(tab)), 7):
        tab[p] = rng.randint(1, 9)
    mp, ep = Q.write_uai(str(tmp_path / "s.uai"), [3, 2, 3, 2, 2, 3, 2, 3], [((0, 1, 2, 3, 4, 5), tab), ((6, 7), [1, 2, 3, 4, 5, 6]), ((5, 6), [2, 1, 1, 2, 3, 1])]); truth = Q.truth(mp, ep)[-1]
    rec = Q._run_cfg(mp, ep, str(tmp_path / "s"), rules=[], b64=False, **SW); v = _driver_view(rec); assert Q.contained(rec, truth); _schedule_matches(v)
    assert v["pred_joined"] == 7 and v["actual_joined"] == 7 and v["sparse"] and "support 7" in v["sparse"][0][2], v


def test_UA5_an_eligible_sparse_child_drives_its_consumer_and_the_estimate_is_disclosed(tmp_path):
    tabA = [0] * 64; tabA[5] = 3
    mp, ep = Q.write_uai(str(tmp_path / "c.uai"), [2] * 10, [((0, 1, 2, 3, 4, 5), tabA), ((5, 6, 7, 8, 9), [i % 7 + 1 for i in range(32)])]); truth = Q.truth(mp, ep)[-1]
    rec = Q._run_cfg(mp, ep, str(tmp_path / "c"), rules=[], b64=False, **SW); v = _driver_view(rec); assert Q.contained(rec, truth); _schedule_matches(v)
    assert any("SPARSE child bucket" in (d or "") for _, _, d in v["sparse"]) and v["pred_joined"] == 17 == v["actual_joined"], v                        # child: 1 row; consumer driven by the child: 1 x 16 free = 16 (the fully positive 32-entry source would cost 32)
    # (b) a planned SPARSE child made unavailable at run time (mutated to STREAM after planning): the kernel applies the SAME policy to the available candidates and COUNTS the deviation
    def downgrade_child(P):
        for n in P.nodes:
            if n.kind == IR.REDUCE and n.storage == IR.SPARSE and n.driver >= 0:
                m = P.nodes[n.children[0]]; ch = P.nodes[m.children[n.driver]]
                if ch.kind == IR.REDUCE:
                    ch.storage = IR.STREAM; ch.demand = "FULL"; ch.driver = -1
    rec = Q._run_cfg(mp, ep, str(tmp_path / "c_dev"), rules=[], b64=False, hooks={"mutate_program": downgrade_child}, **SW); v = _driver_view(rec); assert Q.contained(rec, truth)
    assert v["status"] == "INTERVALS_OK" and v["deviation"] == 1 and v["differs"] == 0 and v["actual_joined"] == 32 and v["pred_joined"] == 17, v          # the policy chose the only available candidate (source, 32 rows); the written child driver was unavailable -> diagnosed, not silent
    # (c) a WRITTEN driver the run-time policy would not choose (the source instead of the cheaper child): executed as written, counted as policy_differs, prediction still met
    def write_source_driver(P):
        for n in P.nodes:
            if n.kind == IR.REDUCE and n.storage == IR.SPARSE and n.driver >= 0 and P.nodes[P.nodes[n.children[0]].children[n.driver]].kind == IR.REDUCE:
                n.driver = 0
    rec = Q._run_cfg(mp, ep, str(tmp_path / "c_dif"), rules=[], b64=False, hooks={"mutate_program": write_source_driver}, **SW); v = _driver_view(rec); assert Q.contained(rec, truth)
    assert v["status"] == "INTERVALS_OK" and v["differs"] == 1 and v["deviation"] == 0 and v["actual_joined"] == 1 + 32, v


def test_UA6_an_overestimated_child_support_keeps_the_written_driver_and_is_counted_not_silently_rescheduled(tmp_path):
    # child bucket over (0,1,2) eliminating 0,1: FOUR joined rows that aggregate into ONE distinct output row (the planner's planned-rows estimate is 4, the run-time support is 1);
    # the consumer's source operand on (2,3) has 2 supported rows: the planner prices the source (2 < 4); at run time the child (1) would be cheaper -> the kernel keeps the WRITTEN driver
    tabA = [0] * 8
    for i in range(4):
        tabA[2 * i] = i + 1                                                                                                                              # (v0, v1, v2=0) for all four (v0, v1)
    mp, ep = Q.write_uai(str(tmp_path / "o.uai"), [2] * 4, [((0, 1, 2), tabA), ((2, 3), [3, 0, 0, 5])]); truth = Q.truth(mp, ep)[-1]
    rec = Q._run_cfg(mp, ep, str(tmp_path / "o"), rules=[], b64=False, **SW); v = _driver_view(rec); assert Q.contained(rec, truth)
    if v["sparse"] and any("SOURCE" in (d or "") for _, _, d in v["sparse"][1:]) and v["differs"] == 1:
        assert v["pred_joined"] == v["actual_joined"] and v["deviation"] == 0 and v["proxy"] >= v["ops"], v                                                # executed as priced; the run-time preference is a DIAGNOSED counter
    else:
        _schedule_matches(v)                                                                                                                             # (the planner may legally find another cheaper plan; then the ordinary contract holds)
    assert "estimate" in rec["plan"]["totals"]["assumptions"]


def test_UA7_zero_products_are_visited_rows_and_counted_before_they_are_skipped(tmp_path):
    tab = [0] * 256
    for i, p in enumerate(random.Random(5).sample(range(128), 8)):
        tab[p] = i + 1
    for i, p in enumerate(random.Random(6).sample(range(128, 256), 8)):
        tab[p] = i + 1
    mp, ep = Q.write_uai(str(tmp_path / "z.uai"), [2] * 8, [((0,), [1, 0]), (tuple(range(8)), tab)]); truth = Q.truth(mp, ep)[-1]
    rec = Q._run_cfg(mp, ep, str(tmp_path / "z"), rules=[], b64=False, **SW); v = _driver_view(rec); assert Q.contained(rec, truth); _schedule_matches(v)
    assert v["pred_joined"] == 16 == v["actual_joined"] and v["zero_skips"] >= 8, v                                                                      # the 8 rows with v0 = 1 are visited (and priced) before the exact-zero unary entry skips them


def test_UA8_no_driver_available_is_an_explicit_diagnosed_downgrade(tmp_path):
    mp, ep = Q.write_uai(str(tmp_path / "st.uai"), [2] * 5, [((0, i), [1, 2, 3, 4]) for i in range(1, 5)]); truth = Q.truth(mp, ep)[-1]; forced = []
    def force(P):
        for n in P.nodes:
            if n.kind == IR.REDUCE and P.nodes[n.children[0]].kind == IR.MUL and all(r is None for r in n.reps) and not any(P.nodes[c].kind == IR.SOURCE for c in P.nodes[n.children[0]].children):
                n.storage = IR.SPARSE; n.demand = "FULL"; n.driver = -1; forced.append(n.nid)
    rec = Q._run_cfg(mp, ep, str(tmp_path / "st"), rules=[], b64=False, hooks={"mutate_program": force}, orders=("min_fill",), two_axis=False, fusion=False, demand_masks=False, views=False, budget=30); v = _driver_view(rec)
    assert forced and Q.contained(rec, truth) and v["status"] == "INTERVALS_OK" and v["downgrades"] == 1 and v["actual_joined"] == 0 and v["deviation"] == 0, v   # markers + DENSE children only: no candidate -> the typed downgrade path, never a silent dense schedule under a sparse label
    # a declared driver that is not an operand of the MUL, or a driver on a non-SPARSE REDUCE, is rejected by the local validator
    S, R, T, plan, _ = Q.plan_program(mp, ep); P = plan.program; red = [n for n in P.nodes if n.kind == IR.REDUCE and P.nodes[n.children[0]].kind == IR.MUL][0]
    red.storage = IR.SPARSE; red.driver = 99
    with pytest.raises(IR.IRError):
        IR.local_semantics(P, T.dom)
    red.storage = IR.DENSE; red.driver = 0
    with pytest.raises(IR.IRError):
        IR.local_semantics(P, T.dom)


def test_UA9_the_contract_is_one_text_shared_by_planner_emission_and_kernel_and_the_flat_format_carries_the_driver():
    assert "support x product of the cardinalities" in IR.SPARSE_DRIVER_POLICY and "lowest operand index" in IR.SPARSE_DRIVER_POLICY and "sparse_driver_deviation" in IR.SPARSE_DRIVER_POLICY
    assert IR.sparse_driver_cost([2, 2, 2], [0], 3) == 12 and IR.sparse_driver_cost([2, 2, 2], [0, 1, 2], 5) == 5 and IR.sparse_driver_cost([3, 2], [], 1) == 6
    src = open(os.path.join(HERE, "gbidi3", "kernel3.cpp")).read(); assert "SPARSE_DRIVER_POLICY" in src and "sparse_driver_policy_differs" in src and "n.sparse_driver = r.rdi()" in src
    assert "sparse-driver-contract" in EX.Lib.get().gb3_schedule_id().decode() and {"sparse_driver_deviation", "sparse_driver_policy_differs", "sparse_driver_scans"} <= set(EX.COUNTER_NAMES)
    P = IR.Program(); s = P.source(0, (0, 1), (2, 2)); mk = P.marker(0, 2); m = P.mul([s, mk]); r = P.reduce(m, {0}, storage=IR.SPARSE, driver=0); P.roots = [r.nid]
    assert r.driver == 0 and IR.program_bytes_bound(P) > 0 and "driver" in IR.Node.__slots__ and "w.append(int(getattr(n, \"driver\", -1)))" in open(os.path.join(HERE, "gbidi3", "ir.py")).read()


# ============================================================================================================ UB  shared-demand export ownership (brief B)
class _RecLedger(GM.Ledger):
    def __init__(self, caps=None, fail_on=None):
        super().__init__(caps); self.events = []; self.fail_on = fail_on; self.n_export = 0
    def reserve(self, cat, nb, what):
        if what.startswith("demand hint export"):
            self.n_export += 1
            if self.fail_on is not None and self.n_export == self.fail_on:
                raise GM.MemoryStop(cat, nb, self.used[cat], self.caps[cat], what)
        self.events.append(("reserve", cat, nb, what)); return super().reserve(cat, nb, what)
    def release(self, cat, nb):
        self.events.append(("release", cat, int(nb), None)); return super().release(cat, nb)


def _lifetime_fixture(n=8000):
    w = [Fr(1)] * n; p0 = tuple(1 if i % 4 == 0 else 0 for i in range(n)); p1 = tuple(1 if i % 4 == 2 else 0 for i in range(n)); z = [Fr(a + b) for a, b in zip(p0, p1)]
    m = U.Model(net_type="MARKOV", nvars=1, card=[n], factors=[U.Factor(scope=(0,), card=(n,), table=w, index=0), U.Factor(scope=(0,), card=(n,), table=z, index=1)]); Rr = SRC.Reduced(EX._ModelAdapter(m), {}); Rr.reduce(()); T = TR.TrustedReduced(Rr); f1, f2 = T.factors
    P = IR.Program(); P.derived = {101: {"kind": "additive_split", "parent": f2.fid, "parts": [p0, p1], "index": 0}, 102: {"kind": "additive_split", "parent": f2.fid, "parts": [p0, p1], "index": 1}}
    f = P.source(f1.fid, (0,), (n,)); mk = P.marker(0, n); s = P.mul([f, mk]); s.storage = IR.DENSE; h1 = P.source(101, (0,), (n,)); h2 = P.source(102, (0,), (n,)); ad = P.addn([P.mul([s, h1]), P.mul([s, h2])]); r = P.reduce(ad, {0}); r.storage = IR.DENSE; P.roots = [r.nid]
    return P, T, {f.fid: f.table for f in T.factors}


def test_UB1_successful_export_keeps_a_positive_retained_charge_owned_by_the_program_until_release(tmp_path):
    P, T, tables = _lifetime_fixture(); led = _RecLedger(); clock = Clock(time.monotonic() + 120, 200); clock.optional_allowance_s = 60
    rec = DM.compile_demand(P, row_cap=10 ** 6, tables=tables, clock=clock, ledger=led)
    hints = [nd for nd in P.nodes if isinstance(nd.demand, tuple)]; assert rec["restricted"] == [2] and len(hints) == 1 and len(hints[0].demand) == 4000 and GV.validate(P, T).record["status"] == "VALID"
    exp = DM.EXPORT_BYTES_PER_INDEX * 4000 + 128
    assert rec["retained_bytes"] == exp and led.used["source_ir_maps_output"] == exp and hints[0].prov["demand_charge_bytes"] == exp and "release_hints" in rec["ownership"], (rec["retained_bytes"], led.used)   # the delivered source: tuple retained, charge 0
    # the export reservation (tuple + sort temporary) was requested while the demand sets were still charged (reserve BEFORE construction), then the sort temporary alone was released
    ev = led.events; i = next(k for k, e in enumerate(ev) if e[0] == "reserve" and e[3].startswith("demand hint export")); live_before = sum(e[2] for e in ev[:i] if e[0] == "reserve") - sum(e[2] for e in ev[:i] if e[0] == "release")
    assert live_before >= DM.Budget.SET_BYTES_PER_INDEX * 4000 and ev[i][2] == exp + 8 * 4000 + 64 and ev[i + 1] == ("release", "source_ir_maps_output", 8 * 4000 + 64, None), (live_before, ev[i], ev[i + 1])
    # repeated compilation on the SAME program replaces the hint: the new charge is held before the previous is released, the ledger holds exactly one charge
    rec2 = DM.compile_demand(P, row_cap=10 ** 6, tables=tables, clock=clock, ledger=led); assert rec2["restricted"] == [2] and led.used["source_ir_maps_output"] == exp and hints[0].prov["demand_charge_bytes"] == exp
    j = max(k for k, e in enumerate(ev) if e[0] == "reserve" and e[3].startswith("demand hint export")); assert ("release", "source_ir_maps_output", exp, None) in ev[j:]                                                   # the REPLACED charge is released after the new one is held
    # end of lifetime: release_hints restores the baseline exactly and zeroes the ownership marks
    assert DM.release_hints(P, led) == exp and led.used["source_ir_maps_output"] == 0 and hints[0].prov["demand_charge_bytes"] == 0 and isinstance(hints[0].demand, tuple)
    assert DM.release_hints(P, led) == 0 and led.used["source_ir_maps_output"] == 0                                                                        # idempotent


def test_UB2_export_refusal_is_atomic_no_partially_changed_program_no_temporary_leak(tmp_path):
    mp, ep, S, T, truth = R2.snap(tmp_path, "two", [3, 3], [((0,), (1, 2, 3)), ((0,), (1, 0, 1)), ((1,), (2, 3, 5)), ((1,), (1, 1, 0))])
    tables = {f.fid: f.table for f in T.factors}
    P = R2._shared_program(T, n_shared=2); led0 = GM.Ledger(); clock = Clock(time.monotonic() + 60, 200); clock.optional_allowance_s = 60; r0 = DM.compile_demand(P, row_cap=10 ** 6, tables=tables, clock=clock, ledger=led0)
    assert len(r0["restricted"]) == 2 and led0.used["source_ir_maps_output"] == r0["retained_bytes"] > 0 and GV.validate(P, T).record["status"] == "VALID"                                            # positive control: two nodes restricted, two charges retained
    for fail_on in (1, 2):                                                                                                                                 # refusal at the FIRST or the SECOND staged export
        P = R2._shared_program(T, n_shared=2); before = [(n.nid, n.demand, dict(n.prov or {})) for n in P.nodes]; led = _RecLedger(fail_on=fail_on); clock = Clock(time.monotonic() + 60, 200); clock.optional_allowance_s = 60
        r = DM.compile_demand(P, row_cap=10 ** 6, tables=tables, clock=clock, ledger=led)
        assert r["stop"] == {"kind": "MEMORY_CATEGORY", "reason": r["stop"]["reason"]} and r["stop"]["reason"].startswith("export:") and r["restricted"] == [] and r["retained_bytes"] == 0, r["stop"]
        assert [(n.nid, n.demand, dict(n.prov or {})) for n in P.nodes] == before and led.used["source_ir_maps_output"] == 0 and GV.validate(P, T).record["status"] == "VALID", (fail_on, led.used)   # nothing applied, every staged charge and every set released
    # a numeric cap that admits the discovery sets but not the export: the same typed refusal, FULL everywhere
    P, T8, tables8 = _lifetime_fixture(); probe = GM.Ledger(); clock = Clock(time.monotonic() + 120, 200); clock.optional_allowance_s = 60; DM.compile_demand(P, row_cap=10 ** 6, tables=tables8, clock=clock, ledger=probe); peak_sets = probe.peak["source_ir_maps_output"]
    P, T8, tables8 = _lifetime_fixture(); led = GM.Ledger(dict(GM.CAPS, source_ir_maps_output=peak_sets - 1)); clock = Clock(time.monotonic() + 120, 200); clock.optional_allowance_s = 60; r = DM.compile_demand(P, row_cap=10 ** 6, tables=tables8, clock=clock, ledger=led)
    assert r["stop"]["kind"] == "MEMORY_CATEGORY" and r["restricted"] == [] and led.used["source_ir_maps_output"] == 0 and all(n.demand == "FULL" for n in P.nodes), r["stop"]


def test_UB3_through_the_executor_the_mutable_programs_charge_is_released_after_validation_and_the_copy_carries_its_own(tmp_path):
    mp, ep = Q.write_uai(str(tmp_path / "sh.uai"), [3], [((0,), [1, 2, 3]), ((0,), [1, 0, 1])]); S, Z, N, rows = Q.truth(mp, ep)
    def mut(Pp):
        S_, R_, T_, plan, _ = Q.plan_program(mp, ep); P2 = R2._shared_program(T_); Pp.nodes = P2.nodes; Pp.roots = P2.roots; Pp.derived = P2.derived
    led = _RecLedger(); g = Q.run("GENERAL_BIDI_COMPLETE_V3", mp, ep, str(tmp_path / "g"), rules=[], b64=False, hooks={"mutate_program": mut}, ledger=led); d = g["demand_all_consumers"]
    assert Q.exact_rows(g, rows) and d["restricted"] == [2] and d["retained_bytes"] > 0, d
    ev = led.events; i_exp = next(k for k, e in enumerate(ev) if e[0] == "reserve" and e[3].startswith("demand hint export")); i_copy = next(k for k, e in enumerate(ev) if e[0] == "reserve" and e[3].startswith("validated executable copy"))
    i_rel = next(k for k, e in enumerate(ev) if k > i_copy and e[0] == "release" and e[2] == d["retained_bytes"])
    assert i_exp < i_copy < i_rel, (i_exp, i_copy, i_rel)                                                                                                 # export charged -> validated copy reserved (its bound includes 40 B per demand index) -> the mutable program's charge released
    assert IR.program_bytes_bound(IR.Program()) < IR.program_bytes_bound(_lifetime_fixture(64)[0]) and "40 * len(n.demand)" in open(os.path.join(HERE, "gbidi3", "ir.py")).read()
    a = Q.run("A1_NO_DEMAND_MASKS", mp, ep, str(tmp_path / "a"), rules=[], b64=False, hooks={"mutate_program": mut}); assert Q.exact_rows(a, rows) and a["demand_all_consumers"]["restricted"] == [] and a["demand_all_consumers"].get("retained_bytes") in (None, 0)   # the switch is honoured


# ============================================================================================================ UC  positive compatible closure evidence (brief C)
def _r2_variant(tmp_path, name, mutate):
    dest = str(tmp_path / name); shutil.copytree(R2_FIXTURE, dest); rows = [json.loads(x) for x in open(os.path.join(R2_FIXTURE, "GB_LEDGER.jsonl"))]
    for r in rows:
        if r["kind"] == "START" and r.get("cmd"):
            r["cmd"] = [x.replace(R2_FIXTURE, dest) for x in r["cmd"]]
    rows = mutate(copy.deepcopy(rows)); open(os.path.join(dest, "GB_LEDGER.jsonl"), "w").write("".join(json.dumps(x) + "\n" for x in rows))
    man = json.load(open(os.path.join(dest, "GB_MANIFEST.json"))); return RC.reconcile(dest, man, man["cells"][0], RC.ledger_index(dest))


def test_UC1_owner_closure_must_be_explicit_typed_and_mutually_compatible_on_copies_of_a_real_cleanup_ledger(tmp_path):
    assert os.path.exists(os.path.join(R2_FIXTURE, "GB_LEDGER.jsonl")), "the real parent-cleanup ledger of the second review reproduction is part of the delivery"
    rows0 = [json.loads(x) for x in open(os.path.join(R2_FIXTURE, "GB_LEDGER.jsonl"))]; child0 = next(x for x in rows0 if x.get("outcome") == "PARENT_CLEANUP_KILL"); owner = child0["written_by_parent"]
    ctrl = _r2_variant(tmp_path, "control", lambda rows: rows); assert ctrl["accepted"] and ctrl["cleanup_evidence_reference"]["owner_nested_killed"] == 1, ctrl["reasons"]        # the genuine lifecycle (one kill) is accepted
    def on_owner(fn):
        def m(rows):
            for r in rows:
                if r.get("kind") == "RECEIPT" and r["jid"] == owner:
                    fn(r)
            return rows
        return m
    def missing(r):
        r.pop("cleanup_unresolved", None); r.pop("nested_groups_live_at_receipt", None)
    def outcome(r):
        r["outcome"] = "CLEANUP_UNRESOLVED"
    def live_list(r):
        r["nested_live"] = [{"jid": child0["jid"], "pgid": child0["pgid"], "pids": [child0["pid"]]}]
    def bool_count(r):
        r["nested_groups_live_at_receipt"] = False
    def string_flag(r):
        r["cleanup_unresolved"] = "false"
    def no_registered(r):
        r["nested_groups_registered"] = 0
    def missing_group_empty(r):
        r.pop("group_empty_at_receipt", None)
    for name, fn, word in (("missing_closure_fields", missing, "POSITIVELY"), ("contradictory_outcome", outcome, "incompatible"), ("contradictory_nested_live", live_list, "contradictory"), ("bool_live_count", bool_count, "POSITIVELY"),
                           ("string_flag", string_flag, "POSITIVELY"), ("zero_registered", no_registered, "POSITIVELY"), ("missing_group_empty", missing_group_empty, "POSITIVELY")):
        r = _r2_variant(tmp_path, name, on_owner(fn)); assert not r["accepted"] and any(word in x for x in r["reasons"]), (name, r["reasons"])
    # owner LIFECYCLE uniqueness: a missing owner START / SPAWNED, or a duplicate contradictory owner START (different parent), is not resolved by dictionary overwrite
    r = _r2_variant(tmp_path, "missing_owner_start", lambda rows: [x for x in rows if not (x["jid"] == owner and x["kind"] in ("START", "SPAWNED"))]); assert not r["accepted"] and any("lifecycle" in x for x in r["reasons"]), r["reasons"]
    def dup_start(rows):
        s0 = next(x for x in rows if x["jid"] == owner and x["kind"] == "START"); return rows + [dict(s0, parent_jid="unrelated-nonexistent-owner")]
    r = _r2_variant(tmp_path, "duplicate_owner_start", dup_start); assert not r["accepted"] and any("lifecycle" in x for x in r["reasons"]), r["reasons"]
    def dup_spawn(rows):
        s0 = next(x for x in rows if x["jid"] == owner and x["kind"] == "SPAWNED"); return rows + [dict(s0, pgid=s0["pgid"] + 1)]
    r = _r2_variant(tmp_path, "duplicate_owner_spawn", dup_spawn); assert not r["accepted"] and any("lifecycle" in x for x in r["reasons"]), r["reasons"]
    def wrong_pid(rows):
        for x in rows:
            if x.get("outcome") == "PARENT_CLEANUP_KILL":
                x["pid"] = x["pid"] + 1
        return rows
    r = _r2_variant(tmp_path, "wrong_pid", wrong_pid); assert not r["accepted"] and any("pid / pgid" in x for x in r["reasons"]), r["reasons"]
    # zero kills remain LEGITIMATE closure evidence (the child may have exited naturally; TE1 re-runs the real natural exit)
    def zero_kills(r):
        r["nested_groups_killed"] = 0
    r = _r2_variant(tmp_path, "zero_kills", on_owner(zero_kills)); assert r["accepted"] and r["cleanup_evidence_reference"]["owner_nested_killed"] == 0, r["reasons"]
    assert "missing fields are NOT clean" in RC.owner_evidence.__doc__ or "missing fields are not clean" in open(os.path.join(HERE, "gbidi3", "reconcile.py")).read()
    import gbidi.supervise as SV; assert not os.popen("cd %s && git status --porcelain -- gbidi/supervise.py" % HERE).read().strip(), "the protected supervisor stays unchanged"


# ============================================================================================================ UD  direct-API typed error for over-long exponents (brief D)
def test_UD1_exponent_length_is_checked_before_int_under_the_ordinary_digit_limit_and_the_grammar_is_unchanged():
    old = sys.get_int_max_str_digits(); sys.set_int_max_str_digits(4300)
    try:
        for tok, cap in (("1e" + "9" * 5000, 1 << 20), ("1e-" + "9" * 5000, 1 << 20), ("2.5E+" + "1" * 4400, 1 << 20), ("0e1000000", 65536)):
            led = GM.Ledger(dict(GM.CAPS, source_ir_maps_output=cap)); g = GS._Guard(led, time.monotonic() + 10)
            with pytest.raises(GS.ParseStop) as ex:                                                                                                     # the delivered source: ValueError('Exceeds the limit (4300 digits)') from int()
                GS.parse_model_bytes(("MARKOV 1 2 1 1 0 2 " + tok + " 1").encode(), g)
            assert ex.value.kind == "MEMORY_CATEGORY" and "exact numeral" in ex.value.reason, (tok[:12], ex.value.reason[:100])
        nb, db = GS.numeral_bits_bound("1e" + "9" * 5000); assert nb >= 1 << 62                                                                       # enormous by construction (no int() of the exponent text)
        for tok, val in (("1e000000000000000000000001", Fr(10)), ("1e" + "0" * 30 + "5", Fr(10) ** 5), ("1e-" + "0" * 20 + "2", Fr(1, 100)), ("1e3", Fr(1000)), ("2.5e-2", Fr(1, 40)), ("1/3", Fr(1, 3)), ("0.25", Fr(1, 4)), ("7.", Fr(7)), (".5", Fr(1, 2))):
            m = GS.parse_model_bytes(("MARKOV 1 2 1 1 0 2 %s 1" % tok).encode(), GS._Guard(GM.Ledger(dict(GM.CAPS, source_ir_maps_output=1 << 20)), time.monotonic() + 10)); assert m.factors[0].table[0] == val, tok   # leading zeros are not significant digits
        for bad in ("1_000", "1e5/3", "e5", "--1", "1e", "0x10", "1e+", "1e-"):
            with pytest.raises(GS.InvalidInput):
                GS.parse_model_bytes(("MARKOV 1 2 1 1 0 2 %s 1" % bad).encode())
    finally:
        sys.set_int_max_str_digits(old)
    # production entry points disable the interpreter digit limit (this is a DIRECT-API correction, not a reproduced production-cell fault)
    for f in ("gbidi3/cell.py", "gbidi3/verify.py", "gbidi3/arm_adapter.py"):
        assert "sys.set_int_max_str_digits(0)" in open(os.path.join(HERE, f)).read(), f


# ============================================================================================================ UE  inventory (brief closeout)
def test_UE1_package_inventory_and_closeout_rows_name_this_module():
    from gbidi3_closeout import package as PK
    assert "tests/test_gbidi3_repair4_2026_11_10.py" in PK.TEST_FILES_DEFAULT
    src = open(os.path.join(HERE, "gbidi3_closeout", "ready_for_review.py")).read(); assert "test_gbidi3_repair4_2026_11_10.py" in src and "FOURTH_REVIEW_ROWS" in src and "gbidi3_repair4_controls_final" in src
    D = os.path.join(HERE, "runs", "mdi_2026-10-28", "GENERAL_BIDI_COMPLETE_V3_2026-11-10")
    if os.path.exists(os.path.join(D, "QUALIFICATION_MANIFEST.json")):
        files, ids = PK.test_inventory(D); assert set(PK.TEST_FILES_DEFAULT) <= set(files) and all(os.path.exists(os.path.join(HERE, f)) for f in files)
