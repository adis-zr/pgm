"""Import isolation and timing diagnostics must preserve the public contract."""
import json
import os
from pathlib import Path
import subprocess
import sys
import time
from fractions import Fraction
from types import SimpleNamespace

import pytest


ROOT = Path(__file__).resolve().parents[1]


def fresh_python(source):
    env = dict(os.environ, PYTHONPATH=str(ROOT / "src"))
    return subprocess.run([sys.executable, "-c", source], env=env,
                          text=True, capture_output=True, check=True)


def test_supervisor_import_does_not_load_inference_api_or_contracts():
    result = fresh_python(
        "import sys, pgm, pgm.supervision; "
        "assert 'pgm.api' not in sys.modules; "
        "assert 'pgm.contracts' not in sys.modules; "
        "assert 'pgm.switchboard' not in sys.modules; "
        "assert not any(n.startswith('pgm.algorithms.') for n in sys.modules)"
    )
    assert result.returncode == 0


def test_lazy_public_exports_keep_identity_and_discovery():
    fresh_python(
        "import pgm; "
        "assert set(pgm.__all__) <= set(dir(pgm)); "
        "from pgm import infer, InferenceRequest, InferenceResult, capabilities; "
        "from pgm.api import infer as canonical_infer; "
        "from pgm.contracts import InferenceRequest as request, InferenceResult as result; "
        "from pgm.registry import capabilities as canonical_capabilities; "
        "assert infer is canonical_infer is pgm.infer; "
        "assert InferenceRequest is request and InferenceResult is result; "
        "assert capabilities is canonical_capabilities; "
        "assert not hasattr(pgm, 'missing_public_object'); "
        "namespace = {}; exec('from pgm import *', namespace); "
        "assert all(namespace[n] is getattr(pgm, n) for n in pgm.__all__)"
    )


@pytest.mark.parametrize("refuse", [False, True])
def test_worker_timings_survive_success_and_typed_refusal(tmp_path, monkeypatch, refuse):
    from pgm.backends import worker
    from pgm.validation.publication import AdapterRefused

    model = tmp_path / "uniform.uai"
    model.write_text("MARKOV\n1\n2\n1\n1 0\n2\n1 1\n")
    args = SimpleNamespace(
        input=model, output=tmp_path / "result.json", backend="block",
        deadline=time.monotonic() + 5, epsilon=Fraction(1, 200),
        delta=Fraction(1, 1000000), seed=1, memory_bytes=256 << 20,
        memory_mib=256, mode="auto", structural_route="auto",
        configuration=None, policy="accepted", expected_binding=None,
    )

    def adapter(bound, context):
        if refuse:
            raise AdapterRefused("MEMORY", "injected admission refusal")
        return dict(outcome="COMPLETE", positive_mass_witness=True,
                    binding=bound.binding, mechanism={},
                    answers=[dict(var=0, state=a, lo="1/2", hi="1/2",
                                  point="1/2", guarantee="EXACT") for a in range(2)])

    monkeypatch.setitem(worker.BACKENDS, "block", adapter)
    worker.run(args)
    result = json.loads(args.output.read_text())
    timings = result["runtime_timings"]
    assert set(timings) == ({"source_parse_s", "adapter_s"} if refuse else
                            {"source_parse_s", "adapter_s", "normalization_s"})
    assert all(value >= 0 for value in timings.values())
    assert result["K"] == 2
    assert result["outcome"] == ("MEMORY" if refuse else "COMPLETE")
    assert result["published"] == (0 if refuse else 2)
