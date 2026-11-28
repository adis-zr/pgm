from pathlib import Path
import os,subprocess,time,json,shutil,hashlib
repo=Path('/workspace/scratch/226d1e4428b0/pgm-step2-review')
out=Path('/workspace/scratch/226d1e4428b0/performance2_qualification')
py='/workspace/scratch/226d1e4428b0/step2-review-venv/bin/python'
source=subprocess.check_output(['git','rev-parse','HEAD'],cwd=repo,text=True).strip()
assert not subprocess.check_output(['git','status','--porcelain'],cwd=repo,text=True).strip()
q=out/'libdai'; q.mkdir(exist_ok=True)
shutil.copy2(repo/'benchmarks/external/provenance/qualify_libdai.py',q/'qualify_libdai.py')
commands=[
 ('pytest',[py,'-m','pytest','tests','-q','-rA','-p','no:cacheprovider']),
 ('parity_generate',[py,'tests/parity/generate_reference.py',str(out/'parity.json')]),
 ('parity_compare',[py,'tests/parity/compare.py',str(out/'parity.json'),'--reference',str(repo/'documentation/performance/round1/development/baseline_parity.json'),'--report',str(out/'SAME_HOST_PARITY.json')]),
 ('dgp10',[py,'code/cex/hp/check_dgp10.py',str(out/'DGP10_CONTROLS.json')]),
 ('libdai',[py,str(q/'qualify_libdai.py')]),
 ('setup',[py,'benchmarks/external/run_performance.py','setup','--run-dir','/workspace/scratch/226d1e4428b0/performance_run_2','--baseline-root','/workspace/scratch/226d1e4428b0/pgm-performance-baseline','--qualification',str(q/'LIBDAI_QUALIFICATION.json')])]
records=[]
for label,command in commands:
 start=time.monotonic()
 with (out/(label+'.log')).open('w') as log:
  p=subprocess.run(command,cwd=repo,env=os.environ,stdout=log,stderr=subprocess.STDOUT)
 record={'phase':label,'command':command,'source_commit':source,'returncode':p.returncode,'wall_s':time.monotonic()-start,'log':label+'.log'}
 records.append(record)
 (out/'COMMANDS.json').write_text(json.dumps(records,indent=2)+'\n')
 print(json.dumps(record),flush=True)
 if p.returncode: raise SystemExit(p.returncode)
 if label=='dgp10' and not json.loads((out/'DGP10_CONTROLS.json').read_text())['all_ok']: raise SystemExit('DGP10 controls failed')
assert not subprocess.check_output(['git','status','--porcelain'],cwd=repo,text=True).strip()
result={'source_commit':source,'clean_before_and_after':True,'all_commands_passed':True,'qualification_wall_s':sum(r['wall_s'] for r in records),'same_host_parity':json.loads((out/'SAME_HOST_PARITY.json').read_text())['verdict'],'dgp10':{k:v for k,v in json.loads((out/'DGP10_CONTROLS.json').read_text()).items() if k!='controls'},'libdai':{k:v for k,v in json.loads((q/'LIBDAI_QUALIFICATION.json').read_text()).items() if k!='checks'},'commands':records}
(out/'QUALIFICATION.json').write_text(json.dumps(result,indent=2)+'\n')
print(json.dumps({'qualification':'PASS','source_commit':source,'wall_s':result['qualification_wall_s']}),flush=True)
