from pathlib import Path
from fractions import Fraction as F
import collections,hashlib,itertools,json,sys,os

HERE=Path(__file__).resolve().parent
REPO=Path(os.environ.get('PGM_REVIEW_ROOT', HERE.parents[3]))
DATA=Path(os.environ.get('PGM_AUDIT_DATA_ROOT', HERE))
sys.path.insert(0,str(REPO/'benchmarks/external'))
import run_suite as h
RUNS={
 'original':DATA/'PGM_STEP2_RUN_2026-11-27_f74f7f3/step2-preservation-v1',
 'supplement':DATA/'PGM_STEP2_SUPPLEMENT_RUN_step2-supplement-v1/step2-supplement-v1',
}
sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
summary={}; all_intervals=collections.defaultdict(list); jt_by_task={}
LABELS={'EXACT','DETERMINISTIC','DETERMINISTIC_RESIDUAL','PAC','PAC_EB','PAC_MARKOV','PAC_MARKOV_RESPONSE'}
for campaign,root in RUNS.items():
 freeze=json.load(open(root/'FREEZE.json')); rows=[json.loads(x)for x in(root/'CELLS.jsonl').read_text().splitlines()if x.strip()]
 receipts=[json.loads(x)for x in(root/'RECEIPTS.jsonl').read_text().splitlines()if x.strip()];receipts=[r for r in receipts if r['kind']=='RECEIPT']
 ri=collections.defaultdict(list)
 for r in receipts:ri[r['job']].append(r)
 tasks={t['name']:dict(t)for t in freeze['tasks']}; metadata={};faults=[];checks=[];pubcount=0;rawcount=0;marcount=0;kept={};geometry_faults=[];contract_faults=[];maxradius=F(0)
 def bad(job,msg):faults.append({'job':job,'fault':msg})
 for name,t in tasks.items():
  for field in ['model','evidence']:
   t[field]=str(REPO/t[field+'_relative'])
   if sha(Path(t[field]))!=t[field+'_sha256']:bad(name,'input hash '+field)
  tok=iter(Path(t['model']).read_text().split());next(tok);n=int(next(tok));cards=[int(next(tok))for _ in range(n)]
  evs=list(map(int,Path(t['evidence']).read_text().split()));assert len(evs)==1+2*evs[0];ev=dict(zip(evs[1::2],evs[2::2]));assert len(ev)==evs[0]
  metadata[name]=(cards,ev,{(v,a)for v,k in enumerate(cards)if v not in ev for a in range(k)})
 expected={(t,a,r)for t in tasks for a in freeze['arms']for r in freeze['replicates']}
 expected|={(x['task'],x['arm'],x['replicate'])for x in freeze.get('replay_cells',[])}
 got=[(r['task'],r['arm'],r['replicate'])for r in rows]
 if len(set(got))!=len(got):bad(campaign,'duplicate cell keys')
 if set(got)!=expected:bad(campaign,'matrix incomplete/extra')
 for row in rows:
  name,arm,rep=row['task'],row['arm'],row['replicate'];job=row['job'];folder=root/'runs'/job;t=tasks[name];cards,ev,inventory=metadata[name]
  if len(ri[job])!=1:bad(job,'terminal receipt count');continue
  receipt=ri[job][0]
  for ck,rk in [('wall_s','wall_s'),('returncode','returncode'),('receipt_outcome','outcome'),('peak_rss_bytes','peak_tree_rss_bytes')]:
   if row[ck]!=receipt[rk]:bad(job,'receipt mismatch '+ck)
  if receipt.get('cleanup_unresolved'):bad(job,'outer unresolved cleanup')
  launch=json.load(open(folder/'launch.json'))
  if launch['engine_commit']!=freeze['engine_commit']:bad(job,'launch commit')
  if launch['arm']!=arm or launch['replicate']!=rep:bad(job,'launch arm/replicate')
  for field in ['model_sha256','evidence_sha256']:
   if row[field]!=t[field]or launch['task'][field]!=t[field]:bad(job,'launch/cell binding '+field)
  if campaign=='supplement'and not row.get('arm_closure_ok'):bad(job,'supplement closure')
  raw=folder/'result.json';mar=folder/'output.MAR';success=False
  if arm.startswith('PGM') and raw.exists():
   rawcount+=1;d=json.load(open(raw));pub={};seen=[];rf=[]
   for ans in d.get('answers',[]):
    key=ans.get('variable',ans.get('var')),ans.get('state');seen.append(key)
    if key not in inventory:rf.append('unknown coordinate')
    label=ans.get('guarantee')
    if label in ['NOT_PUBLISHED','NONE']or(label is None and all(ans.get(x)is None for x in ['lo','hi','point'])):continue
    if label not in LABELS:rf.append('unknown label');continue
    try:l,u,p=(F(str(ans[x]))for x in ['lo','hi','point'])
    except Exception:rf.append('bad rational');continue
    radius=max(p-l,u-p);maxradius=max(radius,maxradius)
    if not(0<=l<=p<=u<=1)or radius>F(1,200):rf.append('geometry/radius')
    if label=='EXACT'and not l==u==p:rf.append('nonpoint EXACT')
    pub[key]=(l,u,p,label)
   if len(set(seen))!=len(seen)or set(seen)!=inventory:rf.append('inventory/duplicate')
   if d.get('K')!=len(inventory)or d.get('published')!=len(pub):rf.append('counts')
   if pub and d.get('positive_mass_witness')is not True:rf.append('positive mass witness')
   if d.get('binding')!={'model_sha256':t['model_sha256'],'evidence_sha256':t['evidence_sha256']}:rf.append('result binding')
   for v,k in enumerate(cards):
    if v in ev:continue
    lower=sum((pub.get((v,a),(F(0),F(1)))[0]for a in range(k)),F(0));upper=sum((pub.get((v,a),(F(0),F(1)))[1]for a in range(k)),F(0))
    if not lower<=1<=upper:rf.append('simplex')
   if rf:geometry_faults.append({'job':job,'faults':sorted(set(rf))})
   pubcount+=len(pub);kept[name,arm,rep]=pub
   if row.get('published')!=len(pub):bad(job,'cell/raw publication count')
   check=h.check_pgm(raw,t,freeze['contracts'].get(arm),freeze['budget_s'])
   if not check['output_valid']:bad(job,'producer reader geometry disagreement')
   if not check['contract_valid']:contract_faults.append({'job':job,'faults':check['contract_faults']})
   # Recheck prospective request risk independently of the shared harness reader.
   if d.get('risk_allocations')is not None:
    risks={k:F(x)for k,x in d['risk_allocations'].items()}
    if any(x<0 for x in risks.values())or sum(risks.values())>F(1,1000000):bad(job,'risk allocation')
    for a in d.get('attempts')or[]:
     if a.get('delta')is not None and F(a['delta'])!=risks.get(a['backend'],F(0)):bad(job,'attempt risk allocation')
   if campaign=='supplement':
    for a in d.get('attempts')or[]:
     if a.get('outcome')=='CLEANUP_UNRESOLVED'or any((a.get(k)or{}).get('unresolved')for k in ['cleanup','cleanup_final']):bad(job,'nested unresolved cleanup')
   success=not rf and check['contract_valid']and len(pub)==len(inventory)and d.get('outcome')in['COMPLETE','EXACT']
   for key,val in pub.items():all_intervals[name,key].append((campaign,arm,rep,*val))
  elif not arm.startswith('PGM')and mar.exists():
   marcount+=1;tokens=iter(mar.read_text().split());mf=[];pts={}
   if next(tokens)!='MAR'or int(next(tokens))!=len(cards):mf.append('header')
   for v,k in enumerate(cards):
    if int(next(tokens))!=k:mf.append('cardinality')
    pp=[F(next(tokens))for _ in range(k)]
    if not all(0<=x<=1 for x in pp)or abs(sum(pp)-1)>F(1,10000000):mf.append('point geometry')
    if v in ev and any(abs(x-int(a==ev[v]))>F(1,10**10)for a,x in enumerate(pp)):mf.append('evidence')
    pts.update({(v,a):x for a,x in enumerate(pp)})
   if next(tokens,None)is not None:mf.append('trailing tokens')
   if mf:bad(job,'MAR '+str(mf))
   success=not mf
   if arm=='LIBDAI_JT'and row.get('complete_within_contract'):jt_by_task[name,rep]=pts
  success=bool(success and receipt['outcome']=='COMPLETED'and receipt['returncode']==0 and receipt['wall_s']<=20 and not receipt.get('cleanup_unresolved')and row.get('identity_ok'))
  if success!=row.get('complete_within_contract'):bad(job,'recomputed completion')
  checks.append(dict(task=name,arm=arm,replicate=rep,complete=success))
 sets={arm:sorted(name for name in tasks if all(any(c['task']==name and c['arm']==arm and c['replicate']==r and c['complete']for c in checks)for r in freeze['replicates']))for arm in freeze['arms']}
 summary[campaign]=dict(cells=len(rows),terminal_receipts=len(receipts),charge_s=sum(r['wall_s']for r in receipts),raw_pgm_results=rawcount,raw_mar_results=marcount,published_coordinates=pubcount,max_radius=str(maxradius),geometry_faults=geometry_faults,contract_faults=contract_faults,faults=faults,completion_counts={k:len(v)for k,v in sets.items()},completion_sets=sets,identity_failures=[r['job']for r in rows if not r['identity_ok']])
 # Save parsed PGM intervals transiently for JT comparison after both campaigns load.
 summary[campaign]['_published']=kept
 print(campaign,len(rows),pubcount,len(faults),len(geometry_faults),len(contract_faults),flush=True)
det=[];pac=[]
for key,entries in all_intervals.items():
 ds=[e for e in entries if not e[-1].startswith('PAC')]
 if ds and max(e[3]for e in ds)>min(e[4]for e in ds):det.append(str(key))
 if any(e[-1].startswith('PAC')for e in entries)and max(e[3]for e in entries)>min(e[4]for e in entries):pac.append(str(key))
for campaign,s in summary.items():
 comparisons=0;coords=0;outside=[];maxgap=F(0)
 for (name,arm,rep),pub in s.pop('_published').items():
  points=jt_by_task.get((name,rep))or jt_by_task.get((name,1))
  if not points or not pub:continue
  comparisons+=1
  for key,(lo,hi,p,label)in pub.items():
   x=points[key];gap=max(lo-x,x-hi,F(0));maxgap=max(maxgap,gap);coords+=1
   if gap>F(5,10**10):outside.append(dict(task=name,arm=arm,replicate=rep,coordinate=key,gap=str(gap)))
 s['jt_comparison']={'outputs':comparisons,'coordinates':coords,'outside':outside,'max_gap':str(maxgap),'allowance':'1/2000000000'}
summary['cross_campaign_compatibility']={'coordinate_groups':len(all_intervals),'deterministic_disjoint':det,'pac_disjoint':pac}
(HERE/'RAW_AUDIT.json').write_text(json.dumps(summary,indent=2)+'\n')
print(json.dumps({k:{kk:vv for kk,vv in v.items()if kk not in ['completion_sets']}for k,v in summary.items()},indent=2))
