from pathlib import Path
import hashlib,json,re,zipfile,collections
ROOT=Path(__file__).resolve().parent
WS=ROOT.parent
PACKET=ROOT/'external_benchmark_packet'
def sha(p): return hashlib.file_digest(p.open('rb'),'sha256').hexdigest()
# No source-inventory metadata is treated as a solver exposure by itself.
# Scan every available DGP review and supplied DGP10 records for known hashes.
scan_roots=sorted(p for p in WS.iterdir() if p.is_dir() and re.match(r'dgp\d+(?:_closeout)?_review$',p.name))
known={};scanned=[]
rx=re.compile(r'(?<![a-fA-F0-9])[a-fA-F0-9]{64}(?![a-fA-F0-9])')
for root in scan_roots:
 for p in sorted(root.rglob('*')):
  if not p.is_file() or p.suffix.lower() not in ('.json','.jsonl','.md','.txt','.csv','.py','.sh') or p.stat().st_size>50*1024**2:continue
  if any(x in p.parts for x in ('.git','__pycache__')):continue
  raw=p.read_text(errors='replace');found=set(x.lower() for x in rx.findall(raw))
  if found:
   rel=str(p.relative_to(WS));scanned.append({'path':rel,'sha256':sha(p),'hashes_found':len(found)})
   for h in found:known.setdefault(h,[]).append(rel)
# Prior actual benchmark arms use exactly the55 frozen model/evidence pairs.
prior=json.loads((PACKET/'results/FREEZE.json').read_text())['tasks']
for t in prior:
 for k in ('model_sha256','evidence_sha256'):known.setdefault(t[k],[]).append('prior_external_benchmark/FREEZE.tasks:'+t['name'])
# Shared trivial evidence hashes would exclude unrelated models. Disjointness is
# enforced on model bytes/canonical model, then checked on full task identities.
candidates=json.loads((ROOT/'HOLDOUT_CANDIDATES.json').read_text())['candidates']
exclusions=[];eligible=[]
for r in candidates:
 matches={k:known[r[k]] for k in ('raw_model_sha256','canonical_model_sha256') if r.get(k) in known}
 if matches: exclusions.append({'case':r['case'],'family':r['family'],'model_sha256':r['raw_model_sha256'],'evidence_sha256':r['raw_evidence_sha256'],'matched_exposure_sources':matches})
 else:eligible.append(r)
key=lambda r:hashlib.sha256(('CONSOLIDATION-EXTERNAL-HOLDOUT-V1\n'+r['raw_model_sha256']+'\n'+r['raw_evidence_sha256']).encode()).hexdigest()
byfamily=collections.defaultdict(list)
for r in eligible:byfamily[r['family']].append(r)
selected=[min(v,key=key) for _,v in sorted(byfamily.items())]
rows=[]
for r in selected:
 archive=ROOT/'sources'/('uai2022_tuning.zip' if r['archive']=='uai2022_tuning' else 'uai2022_final.zip')
 with zipfile.ZipFile(archive) as z:
  dest=ROOT/'holdout_inputs';dest.mkdir(exist_ok=True)
  paths={}
  for keyname,outkey,expected in [('model_path','model',r['raw_model_sha256']),('evidence_path','evidence',r['raw_evidence_sha256'])]:
   suffix=Path(r[keyname]).name
   matches=[n for n in z.namelist() if Path(n).name==suffix]
   assert len(matches)==1,(r['case'],keyname,matches)
   b=z.read(matches[0]);assert hashlib.sha256(b).hexdigest()==expected
   p=dest/suffix;p.write_bytes(b);paths[outkey]=str(p.relative_to(ROOT))
 rows.append({'name':r['case'],'family':r['family'],'model':paths['model'],'evidence':paths['evidence'],'model_sha256':r['raw_model_sha256'],'evidence_sha256':r['raw_evidence_sha256'],'canonical_model_sha256':r['canonical_model_sha256'],'canonical_evidence_sha256':r['canonical_evidence_sha256'],'split':'prospective_external_eval','historical_cohort':'prospective_external_eval','selection_key':key(r),'source_url':r['source_url'],'source_archive_sha256':sha(archive),'task_id':hashlib.sha256((r['raw_model_sha256']+'\n'+r['raw_evidence_sha256']).encode()).hexdigest()})
out={'schema':'CONSOLIDATION_EXTERNAL_HOLDOUT_V1','status':'FROZEN_BEFORE_ANY_SOLVER_EXECUTION','claim':'Not previously scored or used in development in the available records; incomplete historical records prevent an absolute never-seen claim. Family metadata was available; this is held-out tasks in known families, not held-out families.','rule':'Exclude candidates whose raw or canonical model hash occurs in any available DGP review record/code/protocol or prior55 benchmark input manifest. Select minimum SHA256(CONSOLIDATION-EXTERNAL-HOLDOUT-V1\\nraw_model_sha256\\nraw_evidence_sha256) per remaining source family. Shared trivial evidence alone does not mark an unrelated model exposed.','source_candidate_pool':len(candidates),'excluded_count':len(exclusions),'eligible_count':len(eligible),'tasks':rows,'families_without_eligible':sorted(set(r['family'] for r in candidates)-set(byfamily)),'exclusions':exclusions,'exposure_scan_files':scanned,'prior_external_manifest_sha256':sha(PACKET/'results/FREEZE.json'),'candidate_inventory_sha256':sha(ROOT/'HOLDOUT_CANDIDATES.json'),'implementation_blinding':'Names and input contents withheld from parent implementation agent until production source freeze; benchmark preparation agent executes no solvers.'}
(ROOT/'HOLDOUT_FREEZE.json').write_text(json.dumps(out,indent=2)+'\n')
print(json.dumps({'selected_count':len(rows),'family_count':len(byfamily),'excluded':len(exclusions),'eligible':len(eligible),'exposure_scan_files':len(scanned),'freeze_sha256':sha(ROOT/'HOLDOUT_FREEZE.json')}))
