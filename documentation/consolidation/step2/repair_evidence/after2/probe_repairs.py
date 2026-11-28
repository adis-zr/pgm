"""Bounded independent probes. Only our own sleeper may be signalled; all children cleaned on exit."""
import copy, importlib.util, json, os, subprocess, sys, tempfile, time
from pathlib import Path
from unittest.mock import patch

ROOT = Path(os.environ.get('PGM_REVIEW_ROOT', Path(__file__).resolve().parents[2] / 'pgm-step2-review'))
sys.path[:0] = [str(ROOT/'src'), str(ROOT/'code')]
from pgm.runtime.attempts import kill_owned
from pgm.runtime import attempts
from pgm import switchboard
from pgm.contracts import InferenceRequest


def stale_registration_probe(terminal_receipt):
    with tempfile.TemporaryDirectory() as d:
        victim = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(30)'], start_new_session=True)
        dead = subprocess.Popen([sys.executable, '-c', 'pass']); dead.wait()
        try:
            # Controlled stand-in for a newer process reusing a previously registered numeric pgid.
            ledger = Path(d)/'ledger.jsonl'
            rows = [dict(kind='START', jid='old-attempt', owner_dir=d),
                    dict(kind='SPAWNED', jid='old-attempt', pid=victim.pid, pgid=victim.pid, spawn_utc='2000-01-01T00:00:00Z')]
            if terminal_receipt:
                rows.append(dict(kind='RECEIPT', jid='old-attempt', outcome='COMPLETED', cleanup_unresolved=False,
                                 group_empty_at_receipt=True, nested_groups_live_at_receipt=0))
            ledger.write_text(''.join(json.dumps(r)+'\n' for r in rows))
            record = kill_owned(dead, ledger)
            try: victim.wait(timeout=1)
            except subprocess.TimeoutExpired: pass
            return dict(terminal_receipt=terminal_receipt, unrelated_newer_process_killed=victim.returncode is not None,
                        returncode=victim.returncode, cleanup=record)
        finally:
            if victim.poll() is None: victim.kill()
            victim.wait()


def final_cleanup_probe():
    binding={'model_sha256':'model','evidence_sha256':'evidence'}
    class FakeProcess:
        returncode=0
        pid=123456789
        def __init__(self, cmd, **kwargs):
            ledger=Path(cmd[cmd.index('--ledger')+1]); output=Path(cmd[cmd.index('--output')+1])
            ledger.write_text(json.dumps(dict(kind='RECEIPT', outcome='COMPLETED', cleanup_unresolved=False,
                                  group_empty_at_receipt=True, nested_groups_live_at_receipt=0))+'\n')
            output.write_text(json.dumps(dict(outcome='COMPLETE', binding=binding, positive_mass_witness=True,
                answers=[dict(variable=0,var=0,state=a,lo='1/2',hi='1/2',point='1/2',guarantee='EXACT') for a in range(2)],
                published=2,guarantee='EXACT',wall_s=.01)))
        def poll(self): return self.returncode
    calls=[]
    def cleanup(*args, **kwargs):
        calls.append(1)
        return dict(unresolved=[] if len(calls)==1 else [dict(pgid=123456789,pids=[123456789])])
    choice=dict(backend='block', structural_route='auto', allowance_fraction=1)
    meta=dict(binding=binding,cards=[2],evidence={})
    with patch.object(attempts.subprocess,'Popen',FakeProcess), patch.object(attempts,'kill_owned',cleanup), \
         patch.object(switchboard,'inspect_model',return_value=meta), patch.object(switchboard,'candidate_plan',return_value=[choice]):
        result=switchboard.solve(InferenceRequest('/unused/model.uai')).to_dict()
    return dict(cleanup_calls=len(calls), outcome=result['outcome'],published=result['published'],attempt_outcome=result['attempts'][0]['outcome'],
                cleanup_final=result['attempts'][0]['cleanup_final'])


def wheel_inventory_probe():
    spec=importlib.util.spec_from_file_location('qualification_tests', ROOT/'tests/test_qualification_tools.py')
    mod=importlib.util.module_from_spec(spec); spec.loader.exec_module(mod)
    r, W=mod.passing_receipt()
    original=W.verdict(r)
    for row in r['steps']['worker_block']['result']['answers']:
        row['state']=0
    duplicated=W.verdict(r)
    return dict(original=original, duplicated_state_keys=duplicated)


if __name__=='__main__':
    out=dict(stale_without_receipt=stale_registration_probe(False),stale_with_terminal_receipt=stale_registration_probe(True),
             final_cleanup=final_cleanup_probe(),wheel_inventory=wheel_inventory_probe())
    print(json.dumps(out,indent=2))
