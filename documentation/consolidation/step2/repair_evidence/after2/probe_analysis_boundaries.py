"""No solver executions: synthetic records exercise analysis exception boundaries."""
from pathlib import Path
import os,sys,json,tempfile,importlib.util
repo=Path(os.environ.get('PGM_REVIEW_ROOT', Path(__file__).resolve().parents[2]/'pgm-step2-review'))
sys.path.insert(0,str(repo/'benchmarks/external'))
import run_suite as h
import analyze_suite as A
with tempfile.TemporaryDirectory(prefix='step2-analysis-review-') as td:
 root=Path(td); (root/'runs').mkdir(); ev=root/'model.uai.evid';ev.write_text('0\n'); model=repo/'tests/parity/fixtures/asym2.uai'
 t=dict(name='synthetic_test',model=str(model),evidence=str(ev),model_sha256=h.sha(model),evidence_sha256=h.sha(ev),historical_group='old55')
 binding={k:t[k] for k in ['model_sha256','evidence_sha256']}
 answers=[dict(variable=v,state=a,lo='1/2',hi='1/2',point='1/2',guarantee='EXACT') for v in range(2) for a in range(2)]
 base=dict(outcome='EXACT',guarantee='EXACT',K=4,published=4,answers=answers,positive_mass_witness=True,binding=binding,wall_s=.1)
 ref=dict(base,argv=h.CONTRACTS['PGM_REFERENCE']['argv_required'],**h.CONTRACTS['PGM_REFERENCE']['recorded'])
 acc=dict(base,policy='accepted',policy_version=h.CONTRACTS['PGM_ACCEPTED']['policy_version'],epsilon='1/200',delta='1/1000000',hard_deadline_respected=True,risk_allocations={'block':'1/1000000'},attempts=[dict(backend='block',outcome='COMPLETE',configuration=h.CONTRACTS['PGM_ACCEPTED']['configuration'])])
 arms=['PGM_REFERENCE','PGM_ACCEPTED'];f=dict(tasks=[t],arms=arms,replicates=[1],pairs={'same_round_accepted':arms[::-1],'same_round_experimental':arms[::-1]},contracts=h.CONTRACTS,budget_s=20,engine_commit='SYNTHETIC',cost_criterion={},gates={})
 (root/'FREEZE.json').write_text(json.dumps(f));cells=[];receipts=[]
 for arm,d in zip(arms,[ref,acc]):
  job='unrelated_identity_failure_'+arm;folder=root/'runs'/job;folder.mkdir();p=folder/'result.json';p.write_text(json.dumps(d));checked=h.check_pgm(p,t,h.CONTRACTS[arm])
  r=dict(job=job,task=t['name'],arm=arm,replicate=1,identity_ok=False,wall_s=.2,returncode=0,receipt_outcome='COMPLETED',peak_rss_bytes=1,complete_within_contract=False,**checked);cells.append(r)
  receipts.append(dict(kind='RECEIPT',job=job,wall_s=.2,returncode=0,outcome='COMPLETED',peak_tree_rss_bytes=1,cleanup_unresolved=False))
 (root/'CELLS.jsonl').write_text('\n'.join(json.dumps(x) for x in cells)+'\n');(root/'RECEIPTS.jsonl').write_text('\n'.join(json.dumps(x) for x in receipts)+'\n')
 _,_,result=A.analyze(root)
 # Separately expose the late-success reader semantics (outer completion uses its receipt elsewhere).
 lp=root/'late_legacy.json';late=dict(ref,wall_s=19.6);lp.write_text(json.dumps(late));chk=h.check_pgm(lp,t,h.CONTRACTS['PGM_REFERENCE'])
 out=dict(synthetic_no_solver_executed=True,identity_failures=result['gates']['validity']['identity_failures'],ordinary_validity=result['gates']['validity']['decision'],exception_validity=result['gates']['validity_excluding_operator_identity_incident']['decision'],late_complete_reader={k:chk[k] for k in ['contract_valid','all_queries_returned','legacy_internal_wall_past_allowance']})
 bad_cleanup=dict(acc,attempts=[dict(backend='block',outcome='CLEANUP_UNRESOLVED',configuration=h.CONTRACTS['PGM_ACCEPTED']['configuration'])]); cp=root/'cleanup.json';cp.write_text(json.dumps(bad_cleanup));qc=h.check_pgm(cp,t,h.CONTRACTS['PGM_ACCEPTED']);out['cleanup_unresolved_attempt_reader']={k:qc[k] for k in ['contract_valid','all_queries_returned','contract_faults']};print(json.dumps(out,indent=2))
