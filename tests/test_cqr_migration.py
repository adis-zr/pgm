"""Finite-query CQR contracts exercised through the installed-package namespace."""
from fractions import Fraction
import json
import os
from pathlib import Path
import subprocess
import sys
import time

import pytest

from pgm.specialists import cqr
from pgm.algorithms.cqr import checker, oracle, structural, task as task_module


def _model(tmp_path, queries, values=(1, 2, 3, 4), normalizer=False):
    path = tmp_path / 'query.uai'
    path.write_text('MARKOV\n2\n2 2\n1\n2 0 1\n4\n' + ' '.join(map(str, values)) + '\n')
    spec = dict(mode='EXACT_RATIONAL', epsilon='1/200', delta='0', queries=queries)
    if normalizer:
        spec['normalizer_task'] = True
    Path(str(path) + '.query.json').write_text(json.dumps(spec))
    return path


def _solve_and_check(path):
    task = cqr.load_task(path)
    arm = 'N1_NO_STRUCTURAL'
    result = cqr.solve(task, time.monotonic() + 5, arm, 'migration')
    assert result['outcome'] == 'PUBLISHED'
    pub = result['publication']
    normalizer = bool((task.get('query_spec') or {}).get('normalizer_task'))
    names = ['Z'] if normalizer else [q.name for q in task['queries']]
    worker = dict(result, status='COMPLETED', arm=arm,
                  binding=task['binding'], task_identity=task_module.task_identity(task),
                  mode=task['mode'], epsilon=str(task['epsilon']), delta=str(task['delta']),
                  route=pub['route'], exact=bool(pub.get('exact')),
                  answers=[dict(query=name, lo=str(lo), hi=str(hi), point=str(point),
                                status='UNDEFINED' if lo == 'UNDEFINED' else 'OK')
                           for name, (lo, hi), point in zip(names, pub['bounds'], pub['point'])])
    # Match the serialized worker/certificate boundary, independently of campaign tools.
    worker = json.loads(json.dumps(worker, default=str))
    failures, _ = checker.check_worker_output(str(path), worker, arm=arm, deadline=time.monotonic() + 5)
    assert failures == []
    truth = oracle.enumerate_truth(task['model'], task['queries'], max_assignments=4)
    expected = [truth['Z']] if normalizer else truth['answers']
    assert list(pub['point']) == expected
    assert [(a, a) for a in expected] == list(pub['bounds'])
    return task, result


def test_joint_parity_conditional_and_bounded_table_keep_semantics(tmp_path):
    path = _model(tmp_path, [
        dict(kind='joint', assign={'0': 1, '1': 1}),
        dict(kind='parity', variables=[0, 1], bit=1),
        dict(kind='conditional', event={'0': 1}, given={'1': 0}),
        dict(kind='table', table=dict(name='bounded reward', kind='expectation',
             f=dict(scope=[0, 1], values=['0', '1/2', '1', '1/4']), output={'kind': 'table'})),
    ])
    task, result = _solve_and_check(path)
    assert not task['all_singletons']
    assert [q.kind for q in task['queries']] == ['expectation', 'expectation', 'ratio', 'expectation']
    assert result['publication']['point'] == [Fraction(2, 5), Fraction(1, 2), Fraction(3, 4), Fraction(1, 2)]
    model, refusal = structural.model_from_task(task)
    assert model is None and 'not a singleton indicator' in refusal


def test_undefined_conditional_remains_typed(tmp_path):
    path = _model(tmp_path, [dict(kind='conditional', event={'0': 1}, given={'1': 1})], values=(1, 0, 3, 0))
    _, result = _solve_and_check(path)
    assert result['publication']['point'] == ['UNDEFINED']


def test_normalizer_is_not_coerced_to_singletons(tmp_path):
    path = _model(tmp_path, [], normalizer=True)
    task, result = _solve_and_check(path)
    assert task['queries'] == [] and not task['all_singletons']
    assert result['publication']['point'] == [Fraction(10)]


def test_cqr_import_is_namespaced_and_does_not_edit_path(tmp_path):
    # Run outside the checkout with only the package location, as a wheel installation would.
    package_root = str(Path(__import__('pgm').__file__).resolve().parents[1])
    program = r'''
import sys, types
names = ('task', 'solve', 'checker', 'compiler', 'frontier', 'core', 'oracle', 'structural')
sentinels = {name: types.ModuleType(name) for name in names}
sys.modules.update(sentinels)
before = list(sys.path)
from pgm.specialists import cqr
modules = cqr.modules()
assert [m.__name__ for m in modules] == ['pgm.algorithms.cqr.task', 'pgm.algorithms.cqr.solve', 'pgm.algorithms.cqr.checker']
assert all(sys.modules[name] is value for name, value in sentinels.items())
assert sys.path == before
assert not any(name == 'research' or name.startswith('research.') for name in sys.modules)
assert 'N1_CQR' in cqr.arms() and 'G0_CQR' in cqr.arms()
'''
    env = dict(os.environ, PYTHONPATH=package_root)
    completed = subprocess.run([sys.executable, '-c', program], cwd=tmp_path, env=env,
                               capture_output=True, text=True, timeout=10)
    assert completed.returncode == 0, completed.stdout + completed.stderr


def test_expired_cqr_request_keeps_typed_deadline(tmp_path):
    path = _model(tmp_path, [dict(kind='parity', variables=[0, 1], bit=0)])
    task = cqr.load_task(path)
    _, solver, _ = cqr.modules()
    with pytest.raises(solver.Stop) as stopped:
        cqr.solve(task, time.monotonic() - 1, 'N1_NO_STRUCTURAL', 'migration')
    assert stopped.value.kind == 'DEADLINE'
