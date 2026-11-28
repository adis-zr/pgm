"""A layout migration cannot silently substitute its analyzer for frozen evidence."""
import hashlib
from pathlib import Path

import pytest
from benchmarks.external import replay_frozen as replay
from benchmarks.external import run_performance as campaign


def test_frozen_source_requires_full_commit_and_known_protocol():
    freeze = {"schema": "PGM_UNTUNED_PERFORMANCE_2", "roots": {"candidate": {"commit": "a" * 40}}}
    assert replay.source_commit(freeze) == "a" * 40
    freeze["roots"]["candidate"]["commit"] = "main"
    with pytest.raises(ValueError): replay.source_commit(freeze)
    freeze["schema"] = "unknown"
    with pytest.raises(ValueError): replay.source_commit(freeze)


def test_each_frozen_analysis_dependency_must_match(tmp_path):
    directory = tmp_path / "benchmarks/external"; directory.mkdir(parents=True)
    frozen = {"harness_files": {}}
    for name in replay.MODULES:
        (directory / name).write_text(name)
        frozen["harness_files"][name] = hashlib.sha256(name.encode()).hexdigest()
    assert replay.verify_sources(tmp_path, frozen) == frozen["harness_files"]
    for name in replay.MODULES:
        (directory / name).write_text("changed")
        with pytest.raises(ValueError, match=name): replay.verify_sources(tmp_path, frozen)
        (directory / name).write_text(name)


def test_candidate_uses_only_installed_source_root_but_old_baseline_keeps_legacy_path():
    config = {"roots": {key: {"path": "/" + key, "native_cache": "/cache"} for key in ("candidate", "baseline")}, "compilers": {"CC": "/cc", "CXX": "/cxx"}}
    assert campaign.environment(config)["PYTHONPATH"] == "/candidate/src"
    assert campaign.environment(config, "baseline")["PYTHONPATH"] == "/baseline/src:/baseline/code"
