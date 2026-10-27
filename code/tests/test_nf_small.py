"""One-command tiny validation for the normalization-free diagnostic (CLAUDE_CODE_SPEC.md §6 Stage A).
NF_RUN_DIR (env) → results are written as JSON into <NF_RUN_DIR>/validation/. NF_BUILD_DIR defaults to code/build."""
import os, sys, json, pathlib
HERE = pathlib.Path(__file__).resolve().parent.parent; sys.path.insert(0, str(HERE))
import pytest
from nf.validate import run_fixture, rejection_suite, FIXTURES

BUILD = os.environ.get("NF_BUILD_DIR", str(HERE / "build"))
OUT = pathlib.Path(os.environ.get("NF_RUN_DIR", "/tmp/nf_validation")) / "validation"

@pytest.mark.parametrize("name", list(FIXTURES))
def test_fixture_against_256bit_enumeration(name):
    res = run_fixture(name, BUILD, str(OUT / name)); (OUT / name).mkdir(parents=True, exist_ok=True)
    json.dump(res, open(OUT / name / "result.json", "w"), indent=1, default=str)
    assert res["all_ok"], {k: v for k, v in res["checks"].items() if not v}

def test_rejections_for_intended_reasons():
    res = rejection_suite(BUILD, str(OUT / "rejections")); json.dump(res, open(OUT / "rejections" / "result.json", "w"), indent=1, default=str)
    assert res["all_ok"], {k: v for k, v in res.items() if k != "all_ok"}
