from pathlib import Path
import collections,hashlib,json
ROOT=Path(__file__).resolve().parent
PACKET=ROOT/'external_benchmark_packet'
def sha(p): return hashlib.file_digest(p.open('rb'),'sha256').hexdigest()
old=json.loads((PACKET/'results/FREEZE.json').read_text())
rows=[]
for task in old['tasks']:
    t=dict(task)
    for key in ('model','evidence'):
        p=PACKET/'inputs'/t['cohort']/Path(t[key]).name
        assert sha(p)==t[key+'_sha256']
        t[key]=str(p.relative_to(ROOT))
    t['historical_cohort']=t.pop('cohort')
    t['split']='exposed_regression'
    t['task_id']=hashlib.sha256((t['model_sha256']+'\n'+t['evidence_sha256']).encode()).hexdigest()
    t['exposure']='Executed in prior external benchmark; available for development and regression, never an unseen evaluation claim.'
    rows.append(t)
assert len(rows)==55 and len({x['task_id'] for x in rows})==55
manifest={'schema':'CONSOLIDATION_EXTERNAL_INPUTS_V1','status':'INPUT_IDENTITIES_FIXED; ENGINE_FREEZE_PENDING','tasks':rows,'unseen_eval':[],'unseen_status':'No unseen task admitted yet; candidate inventory is separate and requires prior-exposure audit.','known_missing_slots':old['unavailable_historical_slots'],'source_packet_sha256':sha(ROOT/'EXTERNAL_BENCHMARK_EVIDENCE_2026-11-26.zip'),'original_frozen_engine':old['engine_commit'],'synthetic_performance_inputs':0}
(ROOT/'INPUT_MANIFEST.json').write_text(json.dumps(manifest,indent=2)+'\n')
inv=json.loads((PACKET/'data_provenance/INVENTORY.json').read_text())['cases']
seen={(t['model_sha256'],t['evidence_sha256']) for t in rows}
candidates=[r for r in inv if not r.get('duplicate_of') and (r['raw_model_sha256'],r['raw_evidence_sha256']) not in seen]
proposal={'status':'CANDIDATE_POOL_ONLY_NOT_ADMITTED_UNSEEN','candidates':candidates,'count':len(candidates),'families':dict(collections.Counter(r['family'] for r in candidates)),'selection_rule_proposal':'After excluding known prior execution/development exposures by model+evidence binding, select smallest SHA256(CONSOLIDATION-EXTERNAL-HOLDOUT-V1\\nraw_model_sha256\\nraw_evidence_sha256) per source family, before any solver execution. This is within-family task generalization, not unseen-family generalization.','limits':'Prior complete project exposure ledger is not recovered. Absence from prior55 does not prove never evaluated before.'}
(ROOT/'HOLDOUT_CANDIDATES.json').write_text(json.dumps(proposal,indent=2)+'\n')
print(json.dumps({'exposed':len(rows),'candidate_pool':len(candidates),'admitted_unseen':0}))
