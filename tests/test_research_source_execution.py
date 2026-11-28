"""Cheap adversarial checks for research source identity (no inference or native work)."""
import os
from pathlib import Path
import subprocess
import sys

import pytest

from research.source_execution import (bound_source_command, supervisor_environment,
                                      require_local_source, checked_structural_build)


def _tree(path, marker):
    package = path / 'src' / 'pgm'
    package.mkdir(parents=True)
    (package / '__init__.py').write_text('MARKER = ' + repr(marker) + '\n')
    research = path / 'research'
    research.mkdir()
    (research / '__init__.py').write_text('MARKER = ' + repr(marker) + '\n')
    entry = research / 'entry.py'
    entry.write_text('import pgm, research, sys\nprint(pgm.MARKER, research.MARKER, sys.argv[1])\n')
    return entry


def test_requested_tree_wins_over_foreign_pythonpath_and_working_directory(tmp_path):
    target = tmp_path / 'target'; foreign = tmp_path / 'foreign'
    entry = _tree(target, 'TARGET'); _tree(foreign, 'FOREIGN')
    command = bound_source_command(target, [sys.executable, str(entry), 'argument preserved'])
    env = dict(os.environ, PYTHONPATH=os.pathsep.join((str(foreign / 'src'), str(foreign))))
    completed = subprocess.run(command, cwd=foreign, env=env, capture_output=True, text=True, timeout=10)
    assert completed.returncode == 0, completed.stderr
    assert completed.stdout.strip() == 'TARGET TARGET argument preserved'


def test_foreign_entry_and_legacy_layout_fail_before_launch(tmp_path):
    target = tmp_path / 'target'; foreign = tmp_path / 'foreign'
    _tree(target, 'TARGET'); entry = _tree(foreign, 'FOREIGN')
    with pytest.raises(ValueError, match='outside'):
        bound_source_command(target, [sys.executable, str(entry)])
    legacy = tmp_path / 'legacy'; legacy.mkdir()
    with pytest.raises(ValueError, match='historical packet'):
        bound_source_command(legacy, [sys.executable, str(entry)])


def test_foreign_package_redirection_is_detected(tmp_path):
    target = tmp_path / 'target'; foreign = tmp_path / 'foreign'
    entry = _tree(target, 'TARGET'); _tree(foreign, 'FOREIGN')
    (target / 'src/pgm/__init__.py').write_text('__path__ = [' + repr(str(foreign / 'src/pgm')) + ']\n')
    completed = subprocess.run(bound_source_command(target, [sys.executable, str(entry), 'x']),
                               capture_output=True, text=True, timeout=10)
    assert completed.returncode != 0
    assert 'foreign source imported for pgm' in completed.stderr


def test_supervisor_and_worker_source_bindings_are_separate():
    env = supervisor_environment({'PYTHONPATH': '/foreign/site', 'PYTHONHOME': '/foreign', 'OMP_NUM_THREADS': '1'})
    assert '/foreign' not in env['PYTHONPATH']
    assert 'PYTHONHOME' not in env
    assert env['OMP_NUM_THREADS'] == '1'


def test_package_entry_preserves_relative_imports(tmp_path):
    target = tmp_path / 'target'
    entry = _tree(target, 'TARGET')
    (target / 'research/sibling.py').write_text('VALUE = 42\n')
    entry.write_text('from .sibling import VALUE\nprint(VALUE)\n')
    completed = subprocess.run(bound_source_command(target, [sys.executable, str(entry)]),
                               capture_output=True, text=True, timeout=10)
    assert completed.returncode == 0, completed.stderr
    assert completed.stdout.strip() == '42'


def test_in_process_manifest_cannot_label_a_foreign_checkout(tmp_path):
    assert require_local_source(Path(__file__).resolve().parents[1])
    with pytest.raises(ValueError, match='loaded checkout'):
        require_local_source(tmp_path)


def test_native_record_is_bound_to_target_bytes_without_building(tmp_path, monkeypatch):
    import hashlib
    import json
    from pgm.runtime import resources
    target = tmp_path / 'target'
    source = target / 'src/pgm/algorithms/structural/cex_kernel.cpp'
    source.parent.mkdir(parents=True)
    source.write_bytes(b'target source')
    cache = tmp_path / 'cache'; cache.mkdir()
    binary = cache / 'libcex_kernel.dylib'; binary.write_bytes(b'compiled target')
    record = {'source_sha256': hashlib.sha256(source.read_bytes()).hexdigest(),
              'binary_sha256': hashlib.sha256(binary.read_bytes()).hexdigest()}
    (cache / 'cex_build.json').write_text(json.dumps(record))
    monkeypatch.setattr(resources, 'native_cache_dir', lambda owner: cache)
    assert checked_structural_build(target) == record
    source.write_bytes(b'foreign source')
    with pytest.raises(ValueError, match='different target'):
        checked_structural_build(target)
