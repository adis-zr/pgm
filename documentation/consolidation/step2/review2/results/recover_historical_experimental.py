from pathlib import Path
import hashlib,json,os
ROOT=Path(__file__).resolve().parents[2]
P=Path(os.environ.get('PGM_PRIOR_RUN', ROOT/'step2_prior_evidence/extracted/benchmark_runs/consolidation-v1-repaired'))
N=Path(os.environ.get('PGM_REVIEW_ROOT', ROOT/'pgm-step2-review'))/'documentation/consolidation/step2/run'
PRIOR_ARCHIVE=Path(os.environ.get('PGM_PRIOR_ARCHIVE', ROOT/'step2_prior_evidence/PGM_CONSOLIDATION_EVIDENCE_2026-11-27.zip'))
O=Path(__file__).parent
sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
f=json.load(open(P/'FREEZE.json')); nf=json.load(open(N/'FREEZE.json'))
rows=[json.loads(x) for x in (P/'CELLS.jsonl').read_text().splitlines() if x.strip()]
rr=[r for r in rows if r['arm']=='PGM']
assert len(rr)==122
nt={t['name']:t for t in nf['tasks']}
newrows=[json.loads(x) for x in (N/'CELLS_COMPACT.jsonl').read_text().splitlines() if x.strip()]
nb={(r['task'],r['arm'],r['replicate']):r for r in newrows}
keys=['job','task','arm','replicate','split','historical_cohort','model_sha256','evidence_sha256','wall_s','budget_s','receipt_outcome','returncode','peak_rss_bytes','identity_ok','output_valid','validation_faults','solver_outcome','guarantee','published','K','all_queries_returned','max_published_radius','max_published_width','backend','solver_wall_s','complete_within_contract']
cells=[]
for r in rr:
 for k in ['model_sha256','evidence_sha256']:assert r[k]==nt[r['task']][k]
 x={k:r.get(k) for k in keys}
 for name in ['result.json','LAUNCH.json','CELL.json']:
  p=P/'runs'/r['job']/name
  if p.exists():x[name+'_sha256']=sha(p)
 cells.append(x)
by={(r['task'],r['replicate']):r for r in rr}
old={t['name'] for t in f['tasks'] if all(by[t['name'],rep]['complete_within_contract'] for rep in f['replicates'])}
assert len(old)==47
extract={'schema':'RECOVERED_HISTORICAL_EXPERIMENTAL_CELLS_V1','source_engine_commit':f['engine_commit'],'source_archive':{'filename':'PGM_CONSOLIDATION_EVIDENCE_2026-11-27.zip','sha256':sha(PRIOR_ARCHIVE)},'source_files':{name:sha(P/name) for name in ['CELLS.jsonl','FREEZE.json','ANALYSIS.json','RECEIPTS.jsonl']},'note':'Recovered scored historical observations, not reruns. Timing is from another host and must not be used as same-host latency evidence. Every model/evidence hash matches the current frozen suite. Compact fields copied, not inferred. Raw result hash included where present.','cells':cells,'complete_both':sorted(old)}
(O/'HISTORICAL_3283CFD_122_CELLS.json').write_text(json.dumps(extract,indent=2)+'\n')
comparison={'schema':'HISTORICAL_EXPERIMENTAL_REVIEW_COMPARISON_V1','source_extract_sha256':sha(O/'HISTORICAL_3283CFD_122_CELLS.json'),'current_source_commit':nf['engine_commit'],'current_freeze_sha256':sha(N/'FREEZE.json'),'current_compact_cells_sha256':sha(N/'CELLS_COMPACT.jsonl'),'matched_tasks':len(nt),'matched_cell_model_evidence_identities':len(rr),'historical_completed_both':len(old),'arms':{}}
for arm in ['PGM_EXPERIMENTAL','PGM_EXPERIMENTAL_REF','PGM_ACCEPTED']:
 ns={t for t in nt if all(nb[t,arm,r]['complete_within_contract'] for r in nf['replicates'])}
 comparison['arms'][arm]={'complete_both':len(ns),'retained':sorted(old&ns),'lost':sorted(old-ns),'gained':sorted(ns-old),'historical_preservation': 'PASS' if not (old-ns) else 'FAIL'}
(O/'HISTORICAL_3283CFD_COMPARISON.json').write_text(json.dumps(comparison,indent=2)+'\n')
print(json.dumps(comparison,indent=2))
