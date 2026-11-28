"""Reproduce exact additive-response planning controls; no large execution runs.

Run from the packet root: ``python3 -m research.campaigns.structural.qualify_dag_additive``.
"""

# Source-checkout entry point; production imports never traverse research.
if __package__ in (None, ""):
    import sys as _research_sys
    from pathlib import Path as _ResearchPath
    _research_sys.path.insert(0, str(_ResearchPath(__file__).resolve().parents[3]))
from research.bootstrap import activate as _activate_research
_activate_research()
from research.paths import repo_root as _repo_root, runs_root as _runs_root, records_root as _records_root, source_path as _source_path
from pathlib import Path
import hashlib
import json
import time

from pgm.algorithms.structural import dag
from pgm.algorithms.structural.core import read_uai
from research.campaigns.structural.test_dag import (test_random_dags, test_correlated_additive_closure,
    test_correlated_nonlinear_rejected, test_cycle_not_oriented,
    test_evidence_not_silently_ignored, test_deadline)


def main():
    here=Path(__file__).resolve().parent
    root=here.parent
    import sys
    inputs=Path(sys.argv[1]) if len(sys.argv)>1 else root/'inputs'
    if not inputs.exists():
        source=root/'reading/necessity/BENCHMARK_NECESSITY_AND_ATTAINABILITY_2026-11-11'
    inputs=root/'inputs'
    if not inputs.exists():
        inputs=source/'sweep_r3/code/runs/mdi_2026-10-28/EXTERNAL_SWEEP_2026-11-06/inputs'
    historical=json.loads((here/'dag_plan_controls_heap.json').read_text())
    for test in (test_random_dags,test_correlated_additive_closure,
                 test_correlated_nonlinear_rejected,test_cycle_not_oriented,
                 test_evidence_not_silently_ignored,test_deadline):
        test()
    rows=[]
    for old in historical:
        model,hashes=read_uai(inputs/(old['case']+'.uai'))
        plain=dag.plan(model,deadline=time.monotonic()+10,additive=False)
        plus=dag.plan(model,deadline=time.monotonic()+10)
        assert plain['stats']['scalar_ops_predicted']==old['expected_scalar_ops']
        assert plus['stats']['scalar_ops_predicted']<=plain['stats']['scalar_ops_predicted']
        # Structural source normalization and its error guarantee are unchanged.
        assert plus['delta']==plain['delta'] and plus['cpt']==plain['cpt']
        checks=plus['additive_checks'];s=plus['stats']
        paid=s['additive_recognition_subtractions']+s['additive_recognition_additions']
        row={'case':old['case'],**hashes,
             'status':'PLANS_QUALIFIED_NOT_LARGE_NUMERIC_EXECUTION',
             'prior_audit_execution_ops':old['expected_scalar_ops'],
             'ordinary_execution_ops':plain['stats']['scalar_ops_predicted'],
             'additive_execution_ops':s['scalar_ops_predicted'],
             'execution_ops_saved':plain['stats']['scalar_ops_predicted']-s['scalar_ops_predicted'],
             'additive_discovery_rational_ops':paid,
             'execution_plus_additive_discovery_ops':s['scalar_ops_predicted']+paid,
             'ordinary_planning_s':plain['stats']['planning_s'],
             'additive_planning_s':s['planning_s'],
             'identity_checks':len(checks),
             'identities_accepted':sum(x['accepted'] for x in checks),
             'identities_selected':len(plus['additive_identities']),
             'selected_children':list(plus['additive_identities']),
             'stats':s}
        rows.append(row)
        print(old['case'],row['ordinary_execution_ops'],row['additive_execution_ops'],
              'discovery',paid,'selected',row['identities_selected'],flush=True)
    report={'code_sha256':hashlib.sha256((here/'dag.py').read_bytes()).hexdigest(),
            'qualification':'32 mixed-domain permuted-axis oracle models plus correlated additive/signed, nonlinear rejection, cycle, evidence and deadline controls passed',
            'scope':'12 plan comparisons only. The ordinary mode exactly reproduces historical audited execution counts. Reduced new execution prices are legitimate new constructions, not revisions of those counts. Discovery costs can exceed execution savings and are reported separately; this is no total-work optimality claim.',
            'numeric_contract':'Exact normalized-Q Fraction computation and unchanged raw-model distortion delta. Discovery and all selected decoder +/- operations are counted; comparisons, reads, and elapsed planning are separate.',
            'cases':rows}
    path=here/'dag_additive_controls.json'
    path.write_text(json.dumps(report,indent=2)+'\n')
    print(path)


if __name__=='__main__':main()
