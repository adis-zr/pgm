"""FIFTH-REVIEW REPAIR CONTROLS of GENERAL_BIDI_COMPLETE_V3 (10 Nov 2026, packet ea26bde7…; correction brief A-C). Every control first failed or could not be
expressed on the delivered f73d70c2 (reproductions: review_repro_r5/before/) and passes on the repaired code.
  VA  hint-memory release is LEDGER-authorized, never proposal-authorized: retained demand-hint charges are held by trusted Lease records issued by the ledger
      in a private registry keyed by the program object (demand.HINT_LEASES); node.prov["demand_charge_bytes"] is reporting only. Controls: the reviewer's
      genuine / forged shared-replacement and ordinary-tree cases (unrelated live baseline survives; forged 10**9 / 300,000 claims release nothing); copied
      program and foreign ledger own nothing (a foreign lease is refused); repeated replacement consumes the previous lease exactly once; repeated release is
      idempotent; refusal at either staged export is atomic with every staged lease released; the executor's normal handoff and typed-stop exits leave no
      outstanding lease; over-release is recorded as an invariant failure, never silently granted; answers unchanged
  VB  native driver-discovery temporaries are RESERVED before construction: no support vector (the scan tracks the written candidate and the policy winner), one
      reusable coverage mask reserved under a scoped charge; at zero index headroom the kernel refuses with a typed MEMORY stop BEFORE allocating or scanning;
      with just-sufficient discovery capacity the scan runs and the later driver reservation refuses with everything released; with sufficient capacity the join
      completes; an expired deadline inside the scan releases everything; the default sparse fixture, the sparse-child driver, the downgraded-child deviation
      and the policy-differs controls keep their counted schedule (no return to dense enumeration, no silent schedule change)
  VC  inventory: package / closeout name this module"""
from __future__ import annotations
import sys, os, json, time, copy, subprocess, shutil
import pytest
HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__))); sys.path.insert(0, HERE); sys.path.insert(0, os.path.join(HERE, "tests"))
sys.set_int_max_str_digits(0)
from fractions import Fraction as Fr
from gbidi3 import executor as EX, trusted as TR, ir as IR, validate as GV, planner as PL, memory as GM, demand as DM
from gbidi3.clock import Clock
import test_gbidi3_complete as Q
import test_gbidi3_repair2_2026_11_10 as R2
import test_gbidi3_repair4_2026_11_10 as U4
PROBE = os.path.join(HERE, "runs", "mdi_2026-10-28", "GENERAL_BIDI_COMPLETE_V3_2026-11-10", "review_repro_r5", "driver_scan_alloc_probe_caps.cpp")
SRC = "source_ir_maps_output"


def _clock():
    c = Clock(time.monotonic() + 120, 200); c.optional_allowance_s = 60; return c


# ============================================================================================================ VA  ledger-authorized release (brief A)
def test_VA1_forged_provenance_releases_nothing_on_the_shared_replacement_witness_and_the_unrelated_baseline_survives():
    for forged in (False, True):
        P, T, tables = U4._lifetime_fixture(8000); led = GM.Ledger(); base = led.lease(SRC, 1_000_000, "unrelated still-live caller bytes")
        if forged:
            P.nodes[2].prov = dict(P.nodes[2].prov or {}, demand_charge_bytes=300_000)                                                              # the reviewer's forged PREVIOUS charge: a claim the ledger never issued
        assert GV.validate(P, T).record["status"] == "VALID"
        rec = DM.compile_demand(P, row_cap=10 ** 6, tables=tables, clock=_clock(), ledger=led)
        assert rec["restricted"] == [2] and rec["retained_bytes"] == 160_128 and led.used[SRC] == 1_000_000 + 160_128 and DM.owned_hint_bytes(P, led) == 160_128, (forged, led.used)   # delivered source: 860,128 when forged
        assert DM.release_hints(P, led) == 160_128 and led.used[SRC] == 1_000_000 and DM.owned_hint_bytes(P, led) == 0 and led.leases_live == 1 and led.over_release == [], (forged, led.used)   # delivered source: 700,000 when forged
        assert DM.release_hints(P, led) == 0 and led.used[SRC] == 1_000_000                                                                      # idempotent: a consumed lease releases nothing
        assert GV.validate(P, T).record["status"] == "VALID" and led.release_lease(base) == 1_000_000 and led.used[SRC] == 0 and led.leases_live == 0


def test_VA2_forged_provenance_on_a_valid_ordinary_tree_releases_nothing_through_the_production_executor(tmp_path):
    class Events(GM.Ledger):
        def __init__(self):
            super().__init__(); self.events = []
        def release(self, cat, n):
            self.events.append((cat, int(n), self.used[cat])); return super().release(cat, n)
    mp, ep = Q.write_uai(str(tmp_path / "tree.uai"), [2, 2], [((0, 1), [1, 2, 3, 5])]); S, Z, N, rows = Q.truth(mp, ep); out = {}
    for forged in (False, True):
        led = Events()
        def mutate(P):
            P.nodes[0].prov = dict(P.nodes[0].prov or {}, demand_charge_bytes=10 ** 9)                                                          # metadata-only mutation of a VALID tree (no shared-demand compile ever runs)
        g = Q.run("GENERAL_BIDI_COMPLETE_V3", mp, ep, str(tmp_path / ("forged" if forged else "control")), rules=[], b64=False, hooks={"mutate_program": mutate} if forged else {}, ledger=led)
        assert g["status"] == "INTERVALS_OK" and Q.exact_rows(g, rows) and g.get("demand_all_consumers") is None and g["hint_leases_released_bytes"] == 0, g.get("hint_leases_released_bytes")
        assert not any(cat == SRC and n >= 10 ** 6 for cat, n, _ in led.events) and led.over_release == [] and led.leases_live == 0, led.events          # delivered source: a 1,000,000,000-byte release against 110,749 live bytes
        out[forged] = led.used[SRC]
    assert out[True] >= out[False] - 1024, out                                                                                                         # the forged run keeps (at least) the control's live source charges (the annotation costs 400 B of provenance)


def test_VA3_copied_program_and_foreign_ledger_own_nothing_and_a_foreign_lease_is_refused():
    P, T, tables = U4._lifetime_fixture(8000); led = GM.Ledger(); rec = DM.compile_demand(P, row_cap=10 ** 6, tables=tables, clock=_clock(), ledger=led)
    assert rec["retained_bytes"] == 160_128 and led.used[SRC] == 160_128
    P2 = copy.deepcopy(P); other = GM.Ledger(); other.lease(SRC, 500_000, "unrelated bytes of another ledger")
    assert P2.nodes[2].prov["demand_charge_bytes"] == 160_128 and DM.owned_hint_bytes(P2, led) == 0 and DM.owned_hint_bytes(P2, other) == 0                 # the copy carries the ANNOTATION but no lease
    assert DM.release_hints(P2, other) == 0 and other.used[SRC] == 500_000 and DM.release_hints(P2, led) == 0 and led.used[SRC] == 160_128             # neither ledger releases anything for the copy
    assert DM.owned_hint_bytes(P, other) == 0 and DM.release_hints(P, other) == 0 and other.used[SRC] == 500_000                                        # the ORIGINAL program under a foreign ledger owns nothing there
    lease = list(DM._owned(P, led).values())[0]
    with pytest.raises(GM.LeaseError):
        other.release_lease(lease)                                                                                                                  # a lease issued by `led` cannot be spent on `other`
    assert other.used[SRC] == 500_000 and lease.live
    assert DM.release_hints(P, led) == 160_128 and led.used[SRC] == 0 and led.leases_live == 0 and not lease.live and DM.release_hints(P, led) == 0


def test_VA4_repeated_replacement_consumes_the_previous_lease_exactly_once_and_refusal_at_either_staged_output_is_atomic(tmp_path):
    P, T, tables = U4._lifetime_fixture(8000); led = GM.Ledger(); base = led.lease(SRC, 1_000_000, "baseline")
    for k in range(3):
        rec = DM.compile_demand(P, row_cap=10 ** 6, tables=tables, clock=_clock(), ledger=led)
        assert rec["restricted"] == [2] and led.used[SRC] == 1_000_000 + 160_128 and DM.owned_hint_bytes(P, led) == 160_128 and led.leases_live == 2, (k, led.used, led.leases_live)   # exactly one outstanding hint lease after every replacement
    P.nodes[2].prov["demand_charge_bytes"] = 999_999_999                                                                                             # a forged annotation on the CURRENT hint changes nothing at the next replacement
    rec = DM.compile_demand(P, row_cap=10 ** 6, tables=tables, clock=_clock(), ledger=led); assert led.used[SRC] == 1_000_000 + 160_128 and DM.owned_hint_bytes(P, led) == 160_128 and led.over_release == []
    assert DM.release_hints(P, led) == 160_128 and led.used[SRC] == 1_000_000 and led.leases_live == 1
    # refusal at the first or the second staged export of a two-node shared program: nothing applied, every staged lease released, no outstanding lease
    mp, ep, S, T2, truth = R2.snap(tmp_path, "two", [3, 3], [((0,), (1, 2, 3)), ((0,), (1, 0, 1)), ((1,), (2, 3, 5)), ((1,), (1, 1, 0))]); tables2 = {f.fid: f.table for f in T2.factors}
    class Failing(GM.Ledger):
        def __init__(self, fail_on):
            super().__init__(); self.fail_on = fail_on; self.n = 0
        def lease(self, cat, nb, what):
            if what.startswith("demand hint export") and "sort" not in what:
                self.n += 1
                if self.n == self.fail_on:
                    raise GM.MemoryStop(cat, nb, self.used[cat], self.caps[cat], what)
            return super().lease(cat, nb, what)
    for fail_on in (1, 2):
        P2 = R2._shared_program(T2, n_shared=2); before = [(n.nid, n.demand, dict(n.prov or {})) for n in P2.nodes]; led2 = Failing(fail_on); led2.lease(SRC, 777, "baseline")
        r = DM.compile_demand(P2, row_cap=10 ** 6, tables=tables2, clock=_clock(), ledger=led2)
        assert r["stop"]["kind"] == "MEMORY_CATEGORY" and r["stop"]["reason"].startswith("export:") and r["restricted"] == [] and r["retained_bytes"] == 0, r["stop"]
        assert [(n.nid, n.demand, dict(n.prov or {})) for n in P2.nodes] == before and led2.used[SRC] == 777 and led2.leases_live == 1 and DM.owned_hint_bytes(P2, led2) == 0 and led2.over_release == [], (fail_on, led2.used, led2.leases_live)
    P2 = R2._shared_program(T2, n_shared=2); led2 = GM.Ledger(); r = DM.compile_demand(P2, row_cap=10 ** 6, tables=tables2, clock=_clock(), ledger=led2)
    assert len(r["restricted"]) == 2 and led2.leases_live == 2 and led2.used[SRC] == r["retained_bytes"] == DM.owned_hint_bytes(P2, led2) > 0 and GV.validate(P2, T2).record["status"] == "VALID"   # genuine two-node export: two leases
    assert DM.release_hints(P2, led2) == r["retained_bytes"] and led2.used[SRC] == 0 and led2.leases_live == 0


def test_VA5_executor_handoff_and_typed_stop_leave_no_outstanding_lease_and_the_switch_holds(tmp_path):
    mp, ep = Q.write_uai(str(tmp_path / "sh.uai"), [3], [((0,), [1, 2, 3]), ((0,), [1, 0, 1])]); S, Z, N, rows = Q.truth(mp, ep)
    def mut(Pp):
        S_, R_, T_, plan, _ = Q.plan_program(mp, ep); P2 = R2._shared_program(T_); Pp.nodes = P2.nodes; Pp.roots = P2.roots; Pp.derived = P2.derived
    led = GM.Ledger(); g = Q.run("GENERAL_BIDI_COMPLETE_V3", mp, ep, str(tmp_path / "g"), rules=[], b64=False, hooks={"mutate_program": mut}, ledger=led); d = g["demand_all_consumers"]
    assert Q.exact_rows(g, rows) and d["restricted"] == [2] and d["retained_bytes"] > 0 and g["hint_leases_released_bytes"] == d["retained_bytes"] and led.leases_live == 0 and led.over_release == [], (d, led.leases_live)
    # a validation refusal AFTER the shared-demand compile (a bad derived witness): the typed stop consumes the mutable program's lease
    def bad(Pp):
        mut(Pp); Pp.derived[102] = dict(Pp.derived[102], index=0)                                                                                   # both split members name the same part: the split no longer covers the parent -> REJECTED by the validator AFTER compile_demand restricted the shared node (its lease is live at the stop)
    led = GM.Ledger()
    with pytest.raises(EX.Refuse) as ex:
        Q.run("GENERAL_BIDI_COMPLETE_V3", mp, ep, str(tmp_path / "bad"), rules=[], b64=False, hooks={"mutate_program": bad}, ledger=led, fallback=False)
    assert ex.value.kind == "REJECTED" and ex.value.rec["hint_leases_released_bytes"] > 0 and led.leases_live == 0 and led.over_release == [], (ex.value.reason[:100], led.leases_live)
    a = Q.run("A1_NO_DEMAND_MASKS", mp, ep, str(tmp_path / "a"), rules=[], b64=False, hooks={"mutate_program": mut}); assert Q.exact_rows(a, rows) and a["demand_all_consumers"]["restricted"] == [] and a["hint_leases_released_bytes"] == 0
    # over-release is an INVARIANT FAILURE recorded in the ledger report, never silently granted capacity
    led = GM.Ledger(); led.reserve(SRC, 100, "x"); led.release(SRC, 300); assert led.used[SRC] == 0 and led.over_release == [(SRC, 300, 100)] and led.report()["over_release_events"] == [(SRC, 300, 100)]
    assert "release_lease" in open(os.path.join(HERE, "gbidi3", "demand.py")).read() and 'prov.get("demand_charge_bytes") or 0)' not in open(os.path.join(HERE, "gbidi3", "demand.py")).read().replace("if (n.prov or {}).get", "")   # no release path reads the annotation as a byte count


# ============================================================================================================ VB  reserve-before-build of the driver discovery (brief B)
def _build_probe(tmp_path):
    exe = str(tmp_path / "driver_scan_alloc_probe"); from gbidi3 import build as GB
    flags = [f for f in GB.FLAGS if f not in ("-fPIC", "-shared")]
    p = subprocess.run(["clang++"] + flags + ["-o", exe, PROBE], capture_output=True, text=True, timeout=300)
    assert p.returncode == 0, p.stderr[-800:]
    return exe


def _probe(exe, nf, icap, dl="20"):
    p = subprocess.run([exe, str(nf), str(icap), dl], capture_output=True, text=True, timeout=120); assert p.returncode == 0, p.stderr[-400:]; return json.loads(p.stdout.strip().splitlines()[-1])


def test_VB1_zero_headroom_refuses_before_any_allocation_or_scan_and_sufficient_capacity_completes_and_releases(tmp_path):
    exe = _build_probe(tmp_path)
    for nf in (10_000, 100_000):
        r = _probe(exe, nf, 0)                                                                                                                       # the reviewer's zero-headroom control (delivered source: 80,008 / 800,008 B allocated before the refusal)
        assert r["ok"] is False and r["stop"] == 2 and r["alloc_calls"] == 0 and r["tracked_peak_bytes"] == 0 and r["largest_unreserved_allocation"] == 0 and r["driver_scan_entries"] == 0 and r["used_index_at_exit"] == 0, r
    r = _probe(exe, 10_000, 65)                                                                                                                      # just the discovery capacity (1-byte mask + 64): the scan RUNS under its reservation, the later driver reservation refuses, everything is released
    assert r["ok"] is False and r["stop"] == 2 and r["driver_scan_entries"] == 20_000 and r["used_index_at_exit"] == 0 and r["largest_unreserved_allocation"] <= 1, r
    r = _probe(exe, 10_000, 1 << 30, "-1")                                                                                                           # cancellation: an already-expired deadline stops inside the scan with every scoped charge released
    assert r["ok"] is False and r["stop"] == 1 and r["used_index_at_exit"] == 0 and r["largest_unreserved_allocation"] <= 1, r
    # (the reviewer's hand-built descriptor harness has no per-node join state, so the SUCCESS path is qualified through the executor in VB2: the default sparse fixture
    #  completes with the join's retained index charge as the only live index bytes)
    src = open(os.path.join(HERE, "gbidi3", "kernel3.cpp")).read(); assert "std::vector<int64_t> supp(" not in src and "disc_guard" in src and "written_supp" in src


def test_VB2_the_driver_schedule_counters_and_deviation_controls_are_unchanged_by_the_discovery_rewrite(tmp_path):
    n = 11; import random; rng = random.Random(386731 + n); positions = rng.sample(range(1 << n), 16); tab = [0] * (1 << n)
    for i, p in enumerate(positions):
        tab[p] = i + 1
    mp, ep = Q.write_uai(str(tmp_path / "n11.uai"), [2] * n, [((0,), [1, 2]), (tuple(range(n)), tab)]); truth = Q.truth(mp, ep)[-1]
    rec = Q.run("GENERAL_BIDI_COMPLETE_V3", mp, ep, str(tmp_path / "n11"), b64=False, budget=30, rules=list(PL.COMMON_RULES), fallback=False); v = U4._driver_view(rec); assert Q.contained(rec, truth); U4._schedule_matches(v)
    assert v["pred_joined"] == 16 == v["actual_joined"] and v["scans"] == 2 + (1 << n) and Q.counters(rec)["used_index_bytes"] > 0, v                   # 16 = 16, every operand scanned exactly once, and the completed join keeps only its retained index charge (the discovery temporaries are released)
    tabA = [0] * 64; tabA[5] = 3
    mp, ep = Q.write_uai(str(tmp_path / "c.uai"), [2] * 10, [((0, 1, 2, 3, 4, 5), tabA), ((5, 6, 7, 8, 9), [i % 7 + 1 for i in range(32)])]); truth = Q.truth(mp, ep)[-1]
    rec = Q._run_cfg(mp, ep, str(tmp_path / "c"), rules=[], b64=False, **U4.SW); v = U4._driver_view(rec); assert Q.contained(rec, truth); U4._schedule_matches(v); assert v["pred_joined"] == 17 == v["actual_joined"]
    def downgrade_child(P):
        for nd in P.nodes:
            if nd.kind == IR.REDUCE and nd.storage == IR.SPARSE and nd.driver >= 0:
                m = P.nodes[nd.children[0]]; ch = P.nodes[m.children[nd.driver]]
                if ch.kind == IR.REDUCE:
                    ch.storage = IR.STREAM; ch.demand = "FULL"; ch.driver = -1
    rec = Q._run_cfg(mp, ep, str(tmp_path / "c_dev"), rules=[], b64=False, hooks={"mutate_program": downgrade_child}, **U4.SW); v = U4._driver_view(rec); assert Q.contained(rec, truth)
    assert v["status"] == "INTERVALS_OK" and v["deviation"] == 1 and v["differs"] == 0 and v["actual_joined"] == 32, v                                   # written child unavailable -> policy over the available candidates, diagnosed
    def write_source_driver(P):
        for nd in P.nodes:
            if nd.kind == IR.REDUCE and nd.storage == IR.SPARSE and nd.driver >= 0 and P.nodes[P.nodes[nd.children[0]].children[nd.driver]].kind == IR.REDUCE:
                nd.driver = 0
    rec = Q._run_cfg(mp, ep, str(tmp_path / "c_dif"), rules=[], b64=False, hooks={"mutate_program": write_source_driver}, **U4.SW); v = U4._driver_view(rec); assert Q.contained(rec, truth)
    assert v["status"] == "INTERVALS_OK" and v["differs"] == 1 and v["deviation"] == 0 and v["actual_joined"] == 33, v                                   # written driver executed as written, counted
    # a tight index cap through the executor: the sparse join is refused / downgraded with a typed path and zero index charge, answer exact (RE4 / SE2 family)
    mp, ep = Q.write_uai(str(tmp_path / "t.uai"), [2] * 6, [((0,), [1, 2]), (tuple(range(6)), [0] * 60 + [1, 2, 3, 4])]); S, Z, N, rows = Q.truth(mp, ep)
    host = Q.run("GENERAL_BIDI_COMPLETE_V3", mp, ep, str(tmp_path / "t0"), rules=[], b64=False)["memory_ledger"]["peak"][SRC]
    rec = Q.run("GENERAL_BIDI_COMPLETE_V3", mp, ep, str(tmp_path / "t1"), rules=[], b64=False, ledger=GM.Ledger(dict(GM.CAPS, source_ir_maps_output=host + 32))); c = Q.counters(rec)
    assert Q.exact_rows(rec, rows) and (c.get("downgrades", 0) >= 1 and c.get("used_index_bytes", 0) <= 1 or rec.get("route") == "exact_fallback"), (c.get("downgrades"), c.get("used_index_bytes"), rec.get("route"))
    assert "estimate" in rec["plan"]["totals"]["assumptions"] and "policy_differs" in rec["plan"]["totals"]["assumptions"] and "without any counter" in rec["plan"]["totals"]["assumptions"]


# ============================================================================================================ VC  inventory
def test_VC1_package_inventory_and_closeout_rows_name_this_module():
    from gbidi3_closeout import package as PK
    assert "tests/test_gbidi3_repair5_2026_11_10.py" in PK.TEST_FILES_DEFAULT
    src = open(os.path.join(HERE, "gbidi3_closeout", "ready_for_review.py")).read(); assert "test_gbidi3_repair5_2026_11_10.py" in src and "FIFTH_REVIEW_ROWS" in src and "gbidi3_repair5_controls_final" in src
    D = os.path.join(HERE, "runs", "mdi_2026-10-28", "GENERAL_BIDI_COMPLETE_V3_2026-11-10")
    if os.path.exists(os.path.join(D, "QUALIFICATION_MANIFEST.json")):
        files, ids = PK.test_inventory(D); assert set(PK.TEST_FILES_DEFAULT) <= set(files) and all(os.path.exists(os.path.join(HERE, f)) for f in files)
