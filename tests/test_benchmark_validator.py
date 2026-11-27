"""STEP2_AMENDMENT_1 mutation controls: the harness validator rejects a wrong policy, an invalid risk allocation, a late
publication, a backend outside the policy and conflicting deterministic intervals (handcrafted artifacts; no solver run)."""
import importlib.util, json, sys
from fractions import Fraction as F
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("run_suite", ROOT / "benchmarks/external/run_suite.py"); h = importlib.util.module_from_spec(spec); sys.modules["run_suite"] = h; spec.loader.exec_module(h)
spec2 = importlib.util.spec_from_file_location("analyze_suite", ROOT / "benchmarks/external/analyze_suite.py"); A = importlib.util.module_from_spec(spec2); spec2.loader.exec_module(A)
FIX = ROOT / "tests/parity/fixtures/asym2.uai"


def task(tmp):
    ev = tmp / "asym2.uai.evid"; ev.write_text("0\n")
    return dict(name="asym2", model=str(FIX), evidence=str(ev), model_sha256=h.sha(FIX), evidence_sha256=h.sha(ev), split="exposed_regression", historical_cohort="t", historical_group="old55")


def rows():
    cards = h.metadata(dict(model=str(FIX), evidence=str(FIX.parent / "zero_mass.uai.evid")))[0] if False else [2, 2]
    out = []
    for v in range(2):
        for a in range(2):
            out.append(dict(variable=v, var=v, state=a, lo="1/2", hi="1/2", point="1/2", guarantee="EXACT"))
    return out


def public_result(t, **over):
    d = dict(outcome="COMPLETE", guarantee="EXACT", K=4, published=4, answers=rows(), positive_mass_witness=True, binding=dict(model_sha256=t["model_sha256"], evidence_sha256=t["evidence_sha256"]),
             policy="accepted", policy_version="accepted-engine-v2.13.2-targeted/1", epsilon="1/200", delta="1/1000000", hard_deadline_respected=True, mode="auto", wall_s=0.2,
             risk_allocations={"block": "1/1000000"}, attempts=[dict(backend="block", outcome="COMPLETE", configuration=dict(schedule="targeted", proposal="mb", table_cap=262144, enum_cap=65536, mb_cap=16777216, batch=1024, crosscheck=True))])
    d.update(over); return d


def write(tmp, d):
    p = tmp / "result.json"; p.write_text(json.dumps(d)); return p


def test_valid_accepted_result_passes_contract(tmp_path):
    t = task(tmp_path); c = h.check_pgm(write(tmp_path, public_result(t)), t, h.CONTRACTS["PGM_ACCEPTED"])
    assert c["output_valid"] and c["contract_valid"] and c["all_queries_returned"], c


@pytest.mark.parametrize("mutation,expected", [
    (dict(policy="experimental"), "policy"),
    (dict(policy_version="accepted-engine-v2.13.2-targeted/2"), "policy_version"),
    (dict(risk_allocations={"block": "1/500000"}), "risk allocations"),
    (dict(risk_allocations={"block": "1/2000000", "quotient": "1/2000000"}), "risk allocations"),
    (dict(hard_deadline_respected=False), "hard deadline"),
    (dict(attempts=[dict(backend="quotient", outcome="COMPLETE", configuration={})]), "backend outside the policy"),
    (dict(epsilon="1/100"), "epsilon/delta"),
    (dict(attempts=[dict(backend="block", outcome="NOT_STARTED", configuration=dict(schedule="targeted", proposal="mb", table_cap=262144, enum_cap=65536, mb_cap=16777216, batch=1024, crosscheck=True))]), "unresolved attempt"),
    (dict(attempts=[dict(backend="block", outcome="COMPLETE", configuration=dict(schedule="baseline", proposal="mb", table_cap=262144, enum_cap=65536, mb_cap=16777216, batch=1024, crosscheck=True))]), "attempt configuration"),
])
def test_contract_mutations_are_rejected(tmp_path, mutation, expected):
    t = task(tmp_path); c = h.check_pgm(write(tmp_path, public_result(t, **mutation)), t, h.CONTRACTS["PGM_ACCEPTED"])
    assert not c["contract_valid"] and any(expected in f for f in c["contract_faults"]), c["contract_faults"]
    assert not (c["all_queries_returned"] and c["contract_valid"])


def test_geometry_mutations_are_rejected(tmp_path):
    t = task(tmp_path)
    bad = public_result(t); bad["answers"][0].update(hi="3/4")
    c = h.check_pgm(write(tmp_path, bad), t, h.CONTRACTS["PGM_ACCEPTED"]); assert "nonpoint exact row" in c["validation_faults"]
    bad = public_result(t); bad["answers"].pop()
    c = h.check_pgm(write(tmp_path, bad), t, h.CONTRACTS["PGM_ACCEPTED"]); assert "query inventory mismatch" in c["validation_faults"]
    bad = public_result(t); bad["guarantee"] = "PAC"; bad["answers"][0].update(guarantee="PAC", lo="0", hi="1", point="1/2")
    c = h.check_pgm(write(tmp_path, bad), t, h.CONTRACTS["PGM_ACCEPTED"]); assert "invalid probability geometry" in c["validation_faults"]


def test_legacy_reference_contract(tmp_path):
    t = task(tmp_path)
    d = dict(outcome="EXACT", guarantee="EXACT", K=4, published=4, answers=rows(), positive_mass_witness=True, binding=dict(model_sha256=t["model_sha256"], evidence_sha256=t["evidence_sha256"]), wall_s=0.1,
             argv=["--input", "m", "--output", "r", "--budget", "19.5", "--seed", "1", "--epsilon", "1/200", "--delta", "1/1000000", "--schedule", "targeted", "--route", "auto", "--proposal", "mb"],
             schedule="targeted", route_requested="auto", proposal="mb", epsilon="1/200", delta="1/1000000")
    c = h.check_pgm(write(tmp_path, d), t, h.CONTRACTS["PGM_REFERENCE"]); assert c["contract_valid"] and c["all_queries_returned"]
    d["schedule"] = "baseline"; d["argv"][d["argv"].index("targeted")] = "baseline"
    c = h.check_pgm(write(tmp_path, d), t, h.CONTRACTS["PGM_REFERENCE"]); assert not c["contract_valid"]


def test_analyzer_detects_deterministic_conflicts_and_late_publication(tmp_path):
    t = task(tmp_path); root = tmp_path / "run"; (root / "runs").mkdir(parents=True)
    freeze = dict(tasks=[dict(t, model_relative=None, evidence_relative=None)], arms=["PGM_REFERENCE", "PGM_ACCEPTED", "LIBDAI_JT"], replicates=[1], pairs={"same_round_accepted": ["PGM_ACCEPTED", "PGM_REFERENCE"], "jt_vs_accepted": ["PGM_ACCEPTED", "LIBDAI_JT"], "same_round_experimental": ["PGM_ACCEPTED", "PGM_REFERENCE"]},
                  contracts=h.CONTRACTS, budget_s=20, engine_commit="x", old_reference_engine=h.REFERENCE_COMMIT, roots={"PGM_EXPERIMENTAL_REF": dict(commit="3283cfd")}, scored_ceiling_s=100, cost_criterion={}, gates={})
    (root / "FREEZE.json").write_text(json.dumps(freeze))
    cells = []; receipts = []
    def cell(arm, result=None, mar=None, wall=0.2, late=False):
        job = "exposed_regression__asym2__%s__r1" % arm; d = root / "runs" / job; d.mkdir()
        if result is not None: (d / "result.json").write_text(json.dumps(result))
        if mar is not None: (d / "output.MAR").write_text(mar); (d / "side.json").write_text(json.dumps(dict(converged=True)))
        receipts.append(dict(kind="RECEIPT", job=job, wall_s=wall, returncode=0, outcome="COMPLETED", peak_tree_rss_bytes=1, cleanup_unresolved=False))
        chk = h.check_pgm(d / "result.json", t, h.CONTRACTS.get(arm)) if result is not None else h.check_libdai(d, t)
        row = dict(job=job, task="asym2", arm=arm, replicate=1, split="exposed_regression", historical_group="old55", historical_cohort="t", model_sha256=t["model_sha256"], evidence_sha256=t["evidence_sha256"], wall_s=wall, budget_s=20, receipt_outcome="COMPLETED", returncode=0, peak_rss_bytes=1, identity_ok=True)
        row.update(chk); row["complete_within_contract"] = bool(chk["all_queries_returned"] and chk["contract_valid"] and not late); row["converged_within_contract"] = row["complete_within_contract"]; cells.append(row)
    ref = dict(outcome="EXACT", guarantee="EXACT", K=4, published=4, answers=rows(), positive_mass_witness=True, binding=dict(model_sha256=t["model_sha256"], evidence_sha256=t["evidence_sha256"]), wall_s=0.1,
               argv=["--budget", "19.5", "--epsilon", "1/200", "--delta", "1/1000000", "--schedule", "targeted", "--route", "auto", "--proposal", "mb"], schedule="targeted", route_requested="auto", proposal="mb", epsilon="1/200", delta="1/1000000")
    acc = public_result(t); acc["answers"][0].update(lo="3/4", hi="3/4", point="3/4"); acc["answers"][1].update(lo="1/4", hi="1/4", point="1/4")     # deterministic rows contradicting the reference's exact 1/2
    cell("PGM_REFERENCE", ref); cell("PGM_ACCEPTED", acc); cell("LIBDAI_JT", mar="MAR 2 2 0.5 0.5 2 0.5 0.5\n")
    (root / "CELLS.jsonl").write_text("\n".join(json.dumps(c) for c in cells) + "\n"); (root / "RECEIPTS.jsonl").write_text("\n".join(json.dumps(r) for r in receipts) + "\n")
    f, rws, result = A.analyze(root)
    assert result["deterministic_conflicts"] and result["gates"]["validity"]["decision"] == "FAIL"
    assert any("excludes the JT point" in i for i in result["validation_issues"])            # the accepted rows 3/4 / 1/4 miss the JT point 1/2
    # late publication: the receipt says the cell overran the contract -> not complete; a cell claiming completion is a validity issue
    for r in receipts:
        if "PGM_ACCEPTED" in r["job"]: r["wall_s"] = 20.5
    (root / "RECEIPTS.jsonl").write_text("\n".join(json.dumps(r) for r in receipts) + "\n")
    f, rws, result = A.analyze(root)
    assert any("Recomputed completion disagrees" in i or "Cell/receipt disagreement" in i for i in result["validation_issues"])


def test_amendment_2_internal_wall_rule_guards_late_publication_only(tmp_path):
    t = task(tmp_path)
    base = dict(outcome="DEADLINE_PARTIAL", guarantee="PARTIAL", K=4, published=0, answers=[dict(var=v, state=a, guarantee="NOT_PUBLISHED") for v in range(2) for a in range(2)], positive_mass_witness=None,
                binding=dict(model_sha256=t["model_sha256"], evidence_sha256=t["evidence_sha256"]), wall_s=19.55, argv=["--budget", "19.5", "--epsilon", "1/200", "--delta", "1/1000000", "--schedule", "targeted", "--route", "auto", "--proposal", "mb"],
                schedule="targeted", route_requested="auto", proposal="mb", epsilon="1/200", delta="1/1000000")
    c = h.check_pgm(write(tmp_path, base), t, h.CONTRACTS["PGM_REFERENCE"]); assert c["contract_valid"] and not c["all_queries_returned"]      # non-publishing deadline cell: no fault
    assert c["legacy_internal_wall_past_allowance"] is True                                                                       # recorded as a diagnostic
    late = dict(base, outcome="EXACT", guarantee="EXACT", published=4, answers=rows(), positive_mass_witness=True, wall_s=19.6)
    c = h.check_pgm(write(tmp_path, late), t, h.CONTRACTS["PGM_REFERENCE"]); assert c["contract_valid"] and c["legacy_internal_wall_past_allowance"] is True   # the legacy engine's own contract; completion still requires the outer receipt <= 20 s
    pub = public_result(t, hard_deadline_respected=False)
    c = h.check_pgm(write(tmp_path, pub), t, h.CONTRACTS["PGM_ACCEPTED"]); assert not c["contract_valid"]                                 # the new public arms are held to hard_deadline_respected
