#!/usr/bin/env python3
"""Negative replay controls on independent hardlink/copy trees; no inference.

Each changed file is unlinked before rewriting, so original checkout bytes and
frozen raw evidence remain untouched. The code tree and run must be restored
outside the original creator-source directories before running this control.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys


def sha(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def link_or_copy(source, destination):
    try:
        os.link(source, destination)
        return destination
    except OSError:
        return shutil.copy2(source, destination)


def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--code-checkout',type=Path,required=True)
    ap.add_argument('--run-dir',type=Path,required=True)
    ap.add_argument('--output-dir',type=Path,required=True)
    args=ap.parse_args()
    code=args.code_checkout.resolve(); run=args.run_dir.resolve(); output=args.output_dir.resolve()
    output.mkdir(parents=True,exist_ok=False)
    frozen=json.loads((run/'FREEZE.json').read_text())
    creator=Path(frozen['roots']['candidate']['path'])
    previous=frozen['previous_candidate_reference']
    cases=[
        ('analyzer','benchmarks/external/analyze_performance.py','Restored analysis dependency differs'),
        ('validity','benchmarks/external/benchmark_validity.py','Restored analysis dependency differs'),
        ('reader','benchmarks/external/run_suite.py','Restored analysis dependency differs'),
        ('previous_analysis',str(Path(previous['analysis_path']).relative_to(creator)),'Relocated previous-candidate reference failed'),
        ('previous_freeze',str(Path(previous['freeze_path']).relative_to(creator)),'Relocated previous-candidate reference failed')]
    parent_hashes={relative:sha(code/relative) for _,relative,_ in cases}
    protected={name:sha(run/name) for name in ('FREEZE.json','RECEIPTS.jsonl')}
    results=[]
    for name,relative,expected_error in cases:
        root=output/name
        cloned=root/'source'
        shutil.copytree(code,cloned,copy_function=link_or_copy,symlinks=True,
                        ignore=shutil.ignore_patterns('.git','__pycache__','.pytest_cache','benchmark_runs'))
        target=cloned/relative
        altered=target.read_bytes()+b'\n# injected replay corruption\n'
        target.unlink(); target.write_bytes(altered)
        wrapper=cloned/'documentation/performance/round2/portability/replay_analysis.py'
        result_dir=root/'result'
        command=[sys.executable,str(wrapper),'--code-checkout',str(cloned),'--run-dir',str(run),'--output-dir',str(result_dir)]
        process=subprocess.run(command,capture_output=True,text=True)
        receipt=json.loads((result_dir/'REPLAY_RECEIPT.json').read_text())
        ok=process.returncode==2 and receipt.get('replay_ok') is False and expected_error in receipt.get('error','')
        results.append(dict(case=name,passed=ok,returncode=process.returncode,error=receipt.get('error'),
                            creator_parent_unchanged=sha(code/relative)==parent_hashes[relative]))
        if not ok: raise AssertionError(results[-1])
    unchanged=all(sha(code/relative)==digest for relative,digest in parent_hashes.items()) and all(sha(run/name)==digest for name,digest in protected.items())
    record=dict(passed=all(r['passed'] for r in results) and unchanged,checks=results,
                original_source_and_evidence_unchanged=unchanged,protected_sha256=protected)
    (output/'MUTATION_CONTROLS.json').write_text(json.dumps(record,indent=2,sort_keys=True)+'\n')
    print(json.dumps(record,indent=2))
    return 0 if record['passed'] else 1


if __name__=='__main__':
    raise SystemExit(main())
