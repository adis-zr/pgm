"""r3 closeout tests (second review): query rejection, reporter fixtures (CONTROL skipped; failed launch), timing/deadline behaviour with
stub workers, trig enclosure on non-dyadic arguments, and the record-count corrections."""
import json
import os
import shutil
import subprocess
import sys
import time
from fractions import Fraction as Fr

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__))); sys.path.insert(0, ROOT)
sys.set_int_max_str_digits(0)
from dq.checker import check_arm, cos_sin_box  # noqa: E402
from dq.supervisor import Journal, run_native  # noqa: E402
from dq.report import write_report  # noqa: E402
from dq.arms import run_arm  # noqa: E402
from dq.model import Model  # noqa: E402

RUN = os.path.join(ROOT, "runs", "dq_pilot_2026-10-26")
if not os.path.exists(os.path.join(RUN, "campaign_state.json")): pytest.skip("saved pilot run not present", allow_module_level=True)


def _recheck(W, inp, cdir, deadline=60):
    os.makedirs(cdir, exist_ok=True); J = Journal(os.path.join(cdir, "events.jsonl")); V = check_arm(W["arm"], inp, W, cdir, J, deadline, 4 << 30, 128); J.close(); return V


# ---------------------------------------------------------------- 1. query binding
def test_checker_refuses_non_zero_query_before_numerical_work(tmp_path):
    m = Model(8, "MAIN", None, query=3); inp = str(tmp_path / "in.txt"); m.write(inp)
    W = json.load(open(os.path.join(RUN, "cells", "MAIN_pair1_D", "witness.json"))); W["query"] = 3; W["n"] = 8
    V = _recheck(W, inp, str(tmp_path / "c"))
    assert V["verdict"] == "REJECTED" and V["failed_checks"] == ["query_is_site_0"] and "kernel" not in V          # no kernel ran
    # input says 0 but witness says 3 (or vice versa) -> also refused
    m0 = Model(8, "MAIN"); inp0 = str(tmp_path / "in0.txt"); m0.write(inp0); W2 = dict(W); W2["query"] = 3
    V2 = _recheck(W2, inp0, str(tmp_path / "c2")); assert V2["verdict"] == "REJECTED" and "query_is_site_0" in V2["failed_checks"]


def test_producer_refuses_non_zero_query(tmp_path):
    R = run_arm("D", "MAIN", 8, str(tmp_path / "arm"), deadline_s=30, evidence=None)
    assert R["status"] in ("VERIFIED", "CERTIFICATE_OR_CHECKER_FAILURE", "CERTIFICATE_DECLINED")
    import dq.arms as A
    orig = A.Model
    class M3(orig):
        def __init__(self, n, case, evidence=None, query=0): super().__init__(n, case, evidence, 3)
    A.Model = M3
    try:
        R3 = run_arm("D", "MAIN", 8, str(tmp_path / "arm3"), deadline_s=30)
    finally:
        A.Model = orig
    assert R3["status"] == "QUERY_NOT_SUPPORTED" and not R3["attempts"]


# ---------------------------------------------------------------- 2. reporter fixtures
def _copy_run(tmp_path, name):
    dst = str(tmp_path / name); shutil.copytree(RUN, dst, ignore=shutil.ignore_patterns("cells")); os.makedirs(os.path.join(dst, "cells"))
    for c in os.listdir(os.path.join(RUN, "cells")):
        os.makedirs(os.path.join(dst, "cells", c)); shutil.copy(os.path.join(RUN, "cells", c, "result.json"), os.path.join(dst, "cells", c, "result.json")) if os.path.exists(os.path.join(RUN, "cells", c, "result.json")) else None
    return dst


def test_report_with_control_skipped(tmp_path):
    dst = _copy_run(tmp_path, "skip"); S = json.load(open(os.path.join(dst, "campaign_state.json")))
    S["cells"] = [c for c in S["cells"] if c["case"] == "MAIN"]; S["stops"].append({"reason": "MAIN_COST_COMPARISON_FAILED_SKIP_CONTROL_TIMING", "elapsed_s": 30.0, "detail": {}})
    json.dump(S, open(os.path.join(dst, "campaign_state.json"), "w"))
    d = write_report(dst); assert d.startswith("NO_GO_FOR_THIS_IMPLEMENTATION (relative")
    txt = open(os.path.join(dst, "REPORT.md")).read(); assert "No CONTROL timing cells: skipped under the frozen stop rule" in txt


def test_report_from_failed_launch(tmp_path):
    src = RUN + "_attempt1_infra_failure"
    if not os.path.exists(os.path.join(src, "campaign_state.json")): pytest.skip("failed-launch record not present")
    dst = str(tmp_path / "fail"); shutil.copytree(src, dst)
    d = write_report(dst); assert d == "CERTIFICATE_OR_CHECKER_FAILURE"; assert os.path.exists(os.path.join(dst, "REPORT.md"))


def test_report_with_no_cells(tmp_path):
    dst = _copy_run(tmp_path, "none"); S = json.load(open(os.path.join(dst, "campaign_state.json"))); S["cells"] = []; S["stops"] = []
    json.dump(S, open(os.path.join(dst, "campaign_state.json"), "w")); d = write_report(dst); assert d.startswith("INCONCLUSIVE")


# ---------------------------------------------------------------- 3. timing / deadlines with stub workers
def test_native_deadline_kills_stub_worker(tmp_path):
    J = Journal(str(tmp_path / "ev.jsonl"))
    rec = run_native([sys.executable, "-c", "import time,signal; signal.signal(signal.SIGTERM, signal.SIG_IGN); time.sleep(30)"], str(tmp_path), J, 1.0, 4 << 30, {"phase": "stub"})
    J.close(); assert rec["kill_reason"] == "deadline" and rec["wall_s"] < 6


def test_checker_refuses_expired_deadline(tmp_path):
    d = os.path.join(RUN, "cells", "MAIN_pair1_D"); W = json.load(open(os.path.join(d, "witness.json")))
    V = _recheck(W, os.path.join(d, "input.txt"), str(tmp_path / "c"), deadline=0.0)
    assert V["verdict"] == "CHECKER_INCOMPLETE" and "expired" in V["reason"] and "kernel" not in V


def test_durable_timer_present_and_drives_row(tmp_path):
    R = run_arm("D", "MAIN", 8, str(tmp_path / "arm"), deadline_s=30)
    assert "durable_complete_wall_s" in R and R["durable_complete_wall_s"] >= R["complete_wall_s"] and os.path.exists(tmp_path / "arm" / "timing_end.json")
    src = open(os.path.join(ROOT, "dq", "campaign.py")).read()
    assert '"complete_wall_s": R.get("durable_complete_wall_s", R["complete_wall_s"])' in src           # campaign rows use the durable timer
    assert "REPORT_CAP_S = 60.0" in src and "timeout=REPORT_CAP_S" in src                              # reporting cap enforced by termination


# ---------------------------------------------------------------- 4. trig enclosure on non-dyadic arguments
@pytest.mark.parametrize("lo,hi", [(Fr(1, 3), Fr(1, 3)), (Fr(22, 7), Fr(22, 7)), (Fr(-5, 3), Fr(-4, 3)), (Fr(355, 226), Fr(355, 226)), (Fr(-1, 7), Fr(1, 11)), (Fr(31, 10), Fr(32, 10))])
def test_cos_sin_box_contains_truth(lo, hi):
    import gmpy2
    from gmpy2 import mpfr, mpq
    (cl, ch), (sl, sh), crit = cos_sin_box(lo, hi, bits=128)
    hi_ctx = gmpy2.context(precision=512)
    for q in (lo, hi, (lo + hi) / 2, lo + (hi - lo) / 3):
        x = hi_ctx.div(mpfr(mpq(q.numerator, q.denominator), 512), 1)
        c, s_ = hi_ctx.cos(x), hi_ctx.sin(x)
        assert cl <= c <= ch and sl <= s_ <= sh, (lo, hi, q)
    if lo == Fr(31, 10): assert 2 in crit and float(cl) == -1.0


# ---------------------------------------------------------------- record corrections
def test_record_counts():
    rr = json.load(open(os.path.join(RUN, "amendments", "repaired_checker_replay.json")))
    assert len(rr["verdicts"]) == 12 and "12 saved witnesses" in rr["what"]
    la = json.load(open(os.path.join(RUN, "amendments", "lock_amendment_1.json"))); assert "12 saved witnesses" in la["saved_record_verification"]["repaired_checker_replay"]
