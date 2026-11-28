"""H4 remains a fixed arithmetic specialist with no historical path dependency."""
from fractions import Fraction as F
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

from pgm.algorithms.h4 import kernels
from pgm.specialists import h4a


def test_h4_availability_error_preserves_shared_specialist_catch_contract(tmp_path, monkeypatch):
    from pgm.specialists import cbi, cqr, sf
    from pgm.specialists.errors import SpecialistUnavailable

    assert h4a.SpecialistUnavailable is cbi.SpecialistUnavailable is cqr.SpecialistUnavailable is sf.SpecialistUnavailable is SpecialistUnavailable
    monkeypatch.setenv("PGM_NATIVE_CACHE", str(tmp_path / "missing"))
    with pytest.raises(SpecialistUnavailable) as failure:
        kernels.kernel_path("h4point")
    assert isinstance(failure.value, kernels.KernelUnavailable)
    assert failure.value.kind == "UNAVAILABLE" and "not built" in str(failure.value)


def test_h4_public_facade_uses_package_owned_math_without_path_mutation():
    before = list(sys.path)
    model = h4a.model().Model(4, 0)
    assert model.canonical_sha256() == "eb63731c286606e0ceb9e59ed5daa38f857bbda44cf7da168d7da0c97d370f6c"
    assert h4a.model().__name__ == "pgm.algorithms.h4.model"
    assert h4a.masses().__name__ == "pgm.algorithms.h4.masses"
    assert h4a.arm_main().__module__ == "pgm.algorithms.h4.arm"
    assert sys.path == before


def test_h4_default_and_override_cache_are_external(tmp_path, monkeypatch):
    monkeypatch.delenv("PGM_NATIVE_CACHE", raising=False)
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "xdg"))
    assert kernels.cache_root() == tmp_path / "xdg/pgm/native_cache/h4"
    monkeypatch.setenv("PGM_NATIVE_CACHE", str(tmp_path / "explicit"))
    report = h4a.available()
    assert not report["available"] and set(report["missing_kernels"]) == set(kernels.KERNELS)
    assert Path(report["build_dir"]).is_relative_to(tmp_path / "explicit")
    monkeypatch.setenv("PGM_NATIVE_CACHE", str(Path(kernels.__file__).parent))
    with pytest.raises(kernels.KernelUnavailable, match="outside"):
        kernels.cache_root()


def test_h4_cache_validates_build_records_and_detects_changed_binaries(tmp_path, monkeypatch):
    monkeypatch.setenv("PGM_NATIVE_CACHE", str(tmp_path / "cache"))
    calls = []

    def compiler(command, **kwargs):
        calls.append(command)
        if "--version" in command:
            return subprocess.CompletedProcess(command, 0, "fixture compiler 1.0\n", "")
        if "-o" in command:
            assert "-fno-fast-math" in command and "-ffp-contract=off" in command
            binary = Path(command[command.index("-o") + 1])
            assert binary.is_relative_to(tmp_path)
            binary.write_bytes(b"fixture native output")
            binary.chmod(0o755)
            return subprocess.CompletedProcess(command, 0, "", "")
        return subprocess.CompletedProcess(command, 0, json.dumps(dict(env="ok", probes=[dict(ok=True)])), "")

    monkeypatch.setattr(kernels.subprocess, "run", compiler)
    built = kernels.build_all()
    assert built["all_ok"] and h4a.available()["available"]
    count = len(calls)
    kernels.build_all()
    assert len(calls) == count
    binary = kernels.kernel_path("h4point")
    binary.write_bytes(b"changed executable")
    assert h4a.available()["missing_kernels"] == ["h4point"]
    with pytest.raises(kernels.KernelUnavailable):
        kernels.kernel_path("h4point")
    kernels.build_all()
    assert len(calls) == count + 3 and h4a.available()["available"]


def test_h4_rejects_false_probe_json_even_when_process_succeeds(tmp_path, monkeypatch):
    monkeypatch.setenv("PGM_NATIVE_CACHE", str(tmp_path / "cache"))

    def compiler(command, **kwargs):
        if "--version" in command:
            return subprocess.CompletedProcess(command, 0, "fixture compiler 1.0\n", "")
        if "-o" in command:
            binary = Path(command[command.index("-o") + 1])
            binary.write_bytes(b"fixture native output"); binary.chmod(0o755)
            return subprocess.CompletedProcess(command, 0, "", "")
        return subprocess.CompletedProcess(command, 0, json.dumps(dict(env="ok", probes=[dict(ok=False)])), "")

    monkeypatch.setattr(kernels.subprocess, "run", compiler)
    with pytest.raises(kernels.KernelUnavailable, match="incomplete floating-point probes"):
        kernels.build_all(["h4point"])
    assert not (kernels.build_dir() / "h4point.json").exists()


def test_h4_changed_compiler_bytes_invalidate_same_named_cache(tmp_path, monkeypatch):
    compiler = tmp_path / "cxx"
    compiler.write_text("first compiler"); compiler.chmod(0o755)
    monkeypatch.setenv("CXX", str(compiler))
    monkeypatch.setenv("PGM_NATIVE_CACHE", str(tmp_path / "cache"))
    first = kernels._identity()
    first_dir = kernels.build_dir()
    compiler.write_text("second compiler version")
    second = kernels._identity()
    assert first["compiler"] == second["compiler"]
    assert first["compiler_files"][0]["resolved"] == second["compiler_files"][0]["resolved"]
    assert first["compiler_files"][0]["binary_sha256"] != second["compiler_files"][0]["binary_sha256"]
    assert first_dir != kernels.build_dir()


def run_tiny_witness(directory):
    """Exercise all native roles and their containment checks without a private packet."""
    from pgm.algorithms.h4.model import Model, NodeProblem
    from pgm.algorithms.h4.grid import Grid
    from pgm.algorithms.h4.emit import Cache, write_point_witness, write_rect_witness
    from pgm.algorithms.h4.build import producer_tables, checker_tables
    from pgm.algorithms.h4 import certs

    directory = Path(directory); directory.mkdir(parents=True, exist_ok=True)
    model = Model(4, 0)
    problem = NodeProblem(model, 0, 1, 2, [0, 0])
    grid = Grid([dict(h="1/2", J=0, a=2, R_tot=1, c_max=1, s=1, t=1)] * 2,
                representatives_expected=1)
    producer, checker = producer_tables(problem, 256), checker_tables(problem, 320)
    pc, cc = Cache(model, grid, 256), Cache(model, grid, 320)
    write_point_witness(directory / "p.txt", problem, grid, pc, producer, "producer")
    write_point_witness(directory / "c.txt", problem, grid, cc, checker, "checker")
    write_rect_witness(directory / "rp.txt", problem, grid, pc, producer, 256, "producer")
    write_rect_witness(directory / "rc.txt", problem, grid, cc, checker, 320, "checker")
    for name, stem, extra in [("h4point", "p", []), ("h4pcheck", "c", []),
                              ("h4rect", "rp", ["--prec", "256"]),
                              ("h4rect", "rc", ["--prec", "320", "--forward"])]:
        result = subprocess.run([str(kernels.kernel_path(name)), "--in", str(directory / (stem + ".txt")),
                                 "--out", str(directory / (stem + ".json")), "--expect-freq", "1", *extra],
                                capture_output=True, text=True, timeout=10)
        assert result.returncode == 0, result.stderr
    checks = {}
    for arm, prod, chk in [("C", "rp", "rc"), ("PI", "p", "rc"), ("PP", "p", "c")]:
        checks[arm] = certs.verify_node(arm, directory / (prod + ".json"),
                                       directory / (chk + ".json"), pc, cc, grid, problem)
        assert checks[arm]["verdict"] == "VERIFIED", checks[arm]
    # At zero frequency the marker masses form a probability distribution.
    point = json.loads((directory / "p.json").read_text())
    assert abs(sum((certs.fb(row["re"]) for row in point["channels"]), F(0)) - 1) <= 2 * certs.E_CH
    return dict(all_ok=True, roles=4, verdicts={arm: result["verdict"] for arm, result in checks.items()})


@pytest.mark.skipif(os.environ.get("PGM_TEST_H4_NATIVE") != "1",
                    reason="explicit native setup required: set PGM_TEST_H4_NATIVE=1 with C++/MPFR/GMP development dependencies")
def test_h4_host_build_and_actual_witnesses_leave_source_unchanged(tmp_path):
    source = Path(kernels.__file__).parent
    before = {str(path.relative_to(source)): hashlib.sha256(path.read_bytes()).hexdigest()
              for path in source.rglob("*") if path.is_file() and "__pycache__" not in path.parts}
    kernels.build_all()
    assert not kernels.build_dir().is_relative_to(source)
    assert run_tiny_witness(tmp_path / "witness")["all_ok"]
    after = {str(path.relative_to(source)): hashlib.sha256(path.read_bytes()).hexdigest()
             for path in source.rglob("*") if path.is_file() and "__pycache__" not in path.parts}
    assert after == before
