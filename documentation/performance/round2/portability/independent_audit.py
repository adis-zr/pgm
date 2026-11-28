"""Independent raw-artifact review of the frozen second performance round."""
from pathlib import Path
from collections import defaultdict
from copy import deepcopy
from fractions import Fraction
import hashlib, json, math, statistics
from gmpy2 import mpq

BASE = Path('/workspace/scratch/226d1e4428b0')
RUN = BASE / 'performance_run_2'
F = json.loads((RUN / 'FREEZE.json').read_text())
A = json.loads((RUN / 'ANALYSIS.json').read_text())
errors = []

def sha(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()

def check(condition, where, reason):
    if not condition:
        errors.append(dict(where=where, reason=reason))
    return bool(condition)

def q(value):
    try:
        return mpq(str(value))
    except ValueError:
        x = Fraction(str(value)); return mpq(x.numerator, x.denominator)

def finite(value):
    return type(value) in (int, float) and math.isfinite(value) and value >= 0

tasks = {t['name']:t for t in F['tasks']}
domains = {}; inventory = {}
for name,t in tasks.items():
    for k in ('model','evidence'):
        check(sha(t[k]) == t[k+'_sha256'], name, 'frozen input hash: '+k)
    with open(t['model']) as stream:
        tokens = (token for line in stream for token in line.split())
        next(tokens); n = int(next(tokens)); cards = [int(next(tokens)) for _ in range(n)]
    ev = list(map(int,Path(t['evidence']).read_text().split()))
    evidence = dict(zip(ev[1::2],ev[2::2])); domains[name] = cards,evidence
    inventory[name] = {(v,s) for v,k in enumerate(cards) if v not in evidence for s in range(k)}

source_files = native_files = artifact_files = 0
for root in F['roots'].values():
    for relative,digest in root['sources'].items():
        source_files += 1; check(sha(Path(root['path'])/relative) == digest, relative, 'frozen source hash')
    for path,digest in root['natives'].items():
        native_files += 1; check(sha(path) == digest, path, 'frozen active native hash')

receipts = [json.loads(s) for s in (RUN/'RECEIPTS.jsonl').read_text().splitlines() if s.strip()]
receipts = [r for r in receipts if r.get('kind')=='RECEIPT']
by_receipt = defaultdict(list)
for r in receipts: by_receipt[r['job']].append(r)
rows = [json.loads(p.read_text()) for p in sorted((RUN/'runs').glob('*/cell.json'))]
keys = [(r['task'],r['arm'],r['replicate']) for r in rows]
expected = {(t,a,r) for t in tasks for a in F['arms'] for r in F['replicates']}
check(len(keys)==len(set(keys))==len(expected)==732 and set(keys)==expected,'matrix','unique complete 732-cell matrix')
check(len(receipts)==732 and set(by_receipt)=={r['job'] for r in rows},'receipts','one-to-one jobs')
charge = sum(r['wall_s'] for r in receipts)
check(charge <= F['scored_ceiling_s'],'budget','charged ceiling')
bykey = {}; complete = {}; published = {}; points = {}; late = []; censored = []
count = pgm_files = 0; intersections = defaultdict(list)
for row in rows:
    job = row['job']; key = (row['task'],row['arm'],row['replicate']); bykey[key]=row
    rs=by_receipt[job]; check(len(rs)==1,job,'unique receipt'); receipt=rs[0]
    check(receipt['jid']==row['receipt_jid'],job,'receipt identity')
    for rk,ck in [('wall_s','wall_s'),('outcome','receipt_outcome'),('returncode','returncode'),('peak_tree_rss_bytes','peak_rss_bytes')]:
        check(receipt[rk]==row[ck],job,'receipt field '+rk)
    check(row['identity_ok'] is True,job,'source identity at execution')
    clean = receipt.get('cleanup_unresolved') is False and receipt.get('group_empty_at_receipt') is True and receipt.get('nested_groups_live_at_receipt')==0
    check(clean,job,'terminal ownership')
    folder=RUN/'runs'/job
    for name,digest in row['artifact_sha256'].items():
        artifact_files += 1; check(sha(folder/name)==digest,job,'artifact '+name)
    outer=clean and receipt['outcome']=='COMPLETED' and receipt['returncode']==0 and 0<receipt['wall_s']<=20
    if outer: check(receipt['peak_tree_rss_bytes']<=3072*(1<<20),job,'completed memory cap')
    rawpath=folder/'result.json'; answer=False
    if row['arm'] in F['contracts'] and rawpath.exists():
        pgm_files += 1; x=json.loads(rawpath.read_text()); contract=F['contracts'][row['arm']]
        task=tasks[row['task']]; seen=set(); pubs={}; good=True
        for k in ('policy','policy_version','epsilon','delta'):
            good &= check(str(x.get(k))==contract[k],job,'public contract '+k)
        good &= check(x['binding']=={k:task[k] for k in ('model_sha256','evidence_sha256')},job,'raw input binding')
        allocation={k:q(contract['delta'])*q(v) for k,v in contract['risk_shares'].items()}
        good &= check({k:q(v) for k,v in x['risk_allocations'].items()}==allocation,job,'risk allocation')
        good &= check(sum(allocation.values())<=q(contract['delta']),job,'total risk')
        for attempt in x.get('attempts',[]):
            good &= check(attempt['backend'] in contract['backends_allowed'],job,'backend admission')
            good &= check(q(attempt['delta'])==allocation[attempt['backend']],job,'attempt risk')
            for cleanup in ('cleanup','cleanup_final','cleanup_interrupt'):
                good &= check(not (attempt.get(cleanup) or {}).get('unresolved'),job,'attempt '+cleanup)
            if 'configuration' in contract:
                good &= check(all((attempt.get('configuration') or {}).get(k)==v for k,v in contract['configuration'].items()),job,'accepted explicit configuration')
        for item in x['answers']:
            coord=(item.get('variable',item.get('var')),item['state'])
            good &= check(coord not in seen,job,'duplicate coordinate'); seen.add(coord)
            if item.get('guarantee')=='NOT_PUBLISHED': continue
            lo,hi,pt=(q(item[k]) for k in ('lo','hi','point'))
            good &= check(0<=lo<=pt<=hi<=1 and max(pt-lo,hi-pt)<=q('1/200'),job,'coordinate geometry')
            if item['guarantee']=='EXACT': good &= check(lo==hi==pt,job,'exact point geometry')
            pubs[coord]=(lo,hi,pt,item['guarantee'])
            intersections[row['task'],coord].append((lo,hi,item['guarantee']))
        good &= check(seen==inventory[row['task']] and len(pubs)==x['published'] and len(seen)==x['K'],job,'original inventory/counts')
        cards,evidence=domains[row['task']]
        for v,k in enumerate(cards):
            if all((v,s) in pubs for s in range(k)):
                good &= check(sum(pubs[v,s][0] for s in range(k))<=1<=sum(pubs[v,s][1] for s in range(k)),job,'simplex enclosure')
        if pubs:
            good &= check(x['positive_mass_witness'] is True,job,'positive mass witness')
        if pubs or x['outcome'] in ('COMPLETE','EXACT'):
            good &= check(x['hard_deadline_respected'] is True and finite(x.get('wall_s')) and x['wall_s']<=19.5,job,'CLI publication deadline')
            if 'api_wall_s' in x:
                good &= check(finite(x['api_wall_s']) and finite(x.get('requested_budget_s')) and 0<x['requested_budget_s']<=19.5 and x['api_wall_s']<=min(x['requested_budget_s'],x['wall_s']) and x.get('api_hard_deadline_respected') is True,job,'API publication deadline')
        elif x['hard_deadline_respected'] is not True:
            good &= check(x['outcome']=='DEADLINE' and x['guarantee']=='NONE' and x['published']==0 and x.get('max_published_radius') is None and finite(x['wall_s']) and x['wall_s']<=receipt['wall_s']<=20 and outer and all(item['guarantee']=='NOT_PUBLISHED' and all(item.get(k) is None for k in ('lo','hi','point')) for item in x['answers']),job,'typed empty late refusal')
            late.append(dict(job=job,wall_s=x['wall_s'],outer_wall_s=receipt['wall_s']))
        count += len(pubs)
        if outer and good: published[key]=pubs
        answer=good and x['outcome'] in ('COMPLETE','EXACT') and len(pubs)==len(inventory[row['task']])
    elif row['arm'].startswith('LIBDAI'):
        mar=folder/'output.MAR'
        if receipt['outcome'] in ('TIMEOUT_KILL','MEMORY_KILL'):
            censored.append(dict(job=job,outcome=receipt['outcome'],output_bytes=mar.stat().st_size if mar.exists() else None))
        elif mar.exists():
            tokens=iter(mar.read_text().split()); cards,evidence=domains[row['task']]
            good=check(next(tokens)=='MAR' and int(next(tokens))==len(cards),job,'MAR header'); values={}
            for v,k in enumerate(cards):
                good &= check(int(next(tokens))==k,job,'MAR cardinality')
                nums=[q(next(tokens)) for _ in range(k)]
                good &= check(all(0<=a<=1 for a in nums) and abs(sum(nums)-1)<=q('1e-7'),job,'MAR probability row')
                if v in evidence: good &= check(all(abs(a-int(s==evidence[v]))<=q('1e-10') for s,a in enumerate(nums)),job,'MAR evidence')
                values.update({(v,s):a for s,a in enumerate(nums)})
            good &= check(next(tokens,None) is None,job,'MAR trailing data'); answer=good
            if good and outer: points[key]=values
    completed=bool(answer and outer); complete[key]=completed
    check(completed==row['complete_within_contract'],job,'independent completion classification')

det_conflicts=pac_conflicts=0
for values in intersections.values():
    det=[(lo,hi) for lo,hi,label in values if not label.startswith('PAC')]
    if det and max(lo for lo,hi in det)>min(hi for lo,hi in det): det_conflicts+=1
    if any(label.startswith('PAC') for _,_,label in values) and max(lo for lo,_,_ in values)>min(hi for _,hi,_ in values):pac_conflicts+=1
check(det_conflicts==0,'geometry','deterministic interval conflicts')
jt_checks=jt_outside=0
for key,pubs in published.items():
    task,arm,rep=key
    jt=next((points[task,'LIBDAI_JT',r] for r in [rep]+[r for r in F['replicates'] if r!=rep] if (task,'LIBDAI_JT',r) in points),None)
    if jt is None: continue
    for coord,(lo,hi,pt,label) in pubs.items():
        jt_checks+=1; jt_outside+=max(lo-jt[coord],jt[coord]-hi,mpq(0))>q('5e-10')
check(jt_outside==0,'geometry','JT numerical exclusions')
sets={a:{t for t in tasks if all(complete[t,a,r] for r in F['replicates'])} for a in F['arms']}
for a,s in sets.items(): check(s==set(A['complete_both'][a]),a,'analyzer completion set agrees')

def pair(candidate,baseline):
    mutual=sets[candidate]&sets[baseline]; ratios=[]; flags=[]; faster=slower=0; per_task={}
    for t in sorted(mutual):
        aw=[bykey[t,candidate,r]['wall_s'] for r in F['replicates']]; bw=[bykey[t,baseline,r]['wall_s'] for r in F['replicates']]
        ratio=statistics.median(aw)/statistics.median(bw); ratios.append(ratio)
        per_task[t]=dict(candidate_walls=aw,baseline_walls=bw,ratio=ratio,speedup=1/ratio)
        faster+=all(a<b for a,b in zip(aw,bw)); slower+=all(a>b for a,b in zip(aw,bw))
        if all(a>1.25*b and a-b>0.1 for a,b in zip(aw,bw)):flags.append(t)
    return dict(mutual=len(mutual),median_wall_ratio=statistics.median(ratios),confirmed_cost_flags=flags,faster_both=faster,slower_both=slower,per_task=per_task)

pairs={name:pair(*arms) for name,arms in {'accepted_vs_parent':('PGM_ACCEPTED','BASE_ACCEPTED'),'automatic_vs_experimental':('PGM_AUTOMATIC','BASE_EXPERIMENTAL'),'automatic_vs_accepted':('PGM_AUTOMATIC','BASE_ACCEPTED'),'automatic_vs_jt':('PGM_AUTOMATIC','LIBDAI_JT')}.items()}
prior=json.loads((BASE/'performance_run_1/ANALYSIS.json').read_text())
union=sets['BASE_ACCEPTED']|sets['BASE_EXPERIMENTAL']
gates=dict(validity=not errors,complete_matrix=len(rows)==len(receipts)==732,
    accepted_preservation=sets['BASE_ACCEPTED']<=sets['PGM_ACCEPTED'],automatic_union_preservation=union<=sets['PGM_AUTOMATIC'],
    previous_automatic50=set(prior['complete_both']['PGM_AUTOMATIC'])<=sets['PGM_AUTOMATIC'],
    accepted_cost=not pairs['accepted_vs_parent']['confirmed_cost_flags'],automatic_cost=not pairs['automatic_vs_experimental']['confirmed_cost_flags'])
partial={}
for name,(candidate,baseline) in {'accepted_vs_parent':('PGM_ACCEPTED','BASE_ACCEPTED'),'automatic_vs_experimental':('PGM_AUTOMATIC','BASE_EXPERIMENTAL'),'automatic_vs_accepted':('PGM_AUTOMATIC','BASE_ACCEPTED')}.items():
    changes=[]
    for task in sorted(tasks):
        for rep in F['replicates']:
            ak,bk=(task,candidate,rep),(task,baseline,rep)
            if complete[ak] and complete[bk]:continue
            aa,bb=published.get(ak,{}),published.get(bk,{})
            if set(aa)!=set(bb):changes.append(dict(task=task,replicate=rep,gained=len(set(aa)-set(bb)),lost=len(set(bb)-set(aa))))
    partial[name]=dict(gained=sum(x['gained'] for x in changes),lost=sum(x['lost'] for x in changes),changes=changes)

prior_partial=[]
for rep in F['replicates']:
    old=json.loads((BASE/'performance_run_1/runs'/f'1qt9__PGM_AUTOMATIC__r{rep}'/'result.json').read_text())
    current=published.get(('1qt9','PGM_AUTOMATIC',rep),{})
    prior_partial.append(dict(task='1qt9',replicate=rep,previous_published=old['published'],current_published=len(current)))

result=dict(review='independent raw-artifact audit',engine_commit=F['roots']['candidate']['commit'],freeze_sha256=sha(RUN/'FREEZE.json'),analysis_sha256=sha(RUN/'ANALYSIS.json'),
    cells=len(rows),unique_keys=len(set(keys)),receipts=len(receipts),charge_s=charge,source_files_checked=source_files,native_files_checked=native_files,artifact_files_checked=artifact_files,
    pgm_result_files=pgm_files,published_coordinate_instances=count,deterministic_conflicts=det_conflicts,pac_conflicts=pac_conflicts,jt_comparisons=jt_checks,jt_outside=jt_outside,
    errors=errors,gates=gates,recommendation='ELIGIBLE opt-in implementation; default promotion separate' if all(gates.values()) else 'HOLD',
    complete_both={a:sorted(s) for a,s in sets.items()},union_count=len(union),union_gains=sorted(sets['PGM_AUTOMATIC']-union),pairs=pairs,
    partial_coordinate_changes=partial,previous_automatic_partial_comparison=prior_partial,censored_comparators=censored,late_empty_refusals=late,
    caveats=['All 61 tasks are exposed; no unseen generalization claim.',
             'Same-host completion preservation is empirical, not a universal preservation guarantee.',
             'Automatic has cost regressions against accepted even when its matched experimental comparison passes.',
             'JT comparison is numerical agreement within 5e-10, not a proof of every large marginal.',
             'Broad latency dominance over libDAI is not established; BP is an uncertified point comparator.',
             'Observed 1qt9 partial answers are lost despite passing completion preservation.',
             'Raw geometry and receipt validation do not independently reprove the algorithms or PAC theorems.'])
out=BASE/'performance2_independent_review.json';out.write_text(json.dumps(result,indent=2,sort_keys=True)+'\n')
lines=['# Independent performance round 2 review','',f"Recommendation: **{result['recommendation']}**.",'',
       f"Frozen engine `{result['engine_commit']}`; {len(rows)} unique cells and receipts; {charge:.6f} charged seconds.",
       f"Checked {pgm_files} PGM result files and {count} published coordinate instances. Errors: {len(errors)}; deterministic conflicts: {det_conflicts}; PAC conflicts (diagnostic): {pac_conflicts}; JT exclusions: {jt_outside} across {jt_checks} comparisons.",'',
       '| Gate | Independent result |','|---|---|']+[f'| {k} | {"PASS" if v else "FAIL"} |' for k,v in gates.items()]
lines+=['', '| Arm | Both-repeat completions |','|---|---:|']+[f'| {a} | {len(s)} |' for a,s in sets.items()]
lines+=['',f"Automatic retains union {len(union)} and prior50; union gains: {result['union_gains']}.",
        f"Automatic/JT median latency ratio: {pairs['automatic_vs_jt']['median_wall_ratio']:.6f}; mutual tasks {pairs['automatic_vs_jt']['mutual']}; faster both {pairs['automatic_vs_jt']['faster_both']}; slower both {pairs['automatic_vs_jt']['slower_both']}.",
        f"Automatic/accepted confirmed cost flags: {pairs['automatic_vs_accepted']['confirmed_cost_flags']}.",
        f"Partial coordinates lost versus same-round experimental: {partial['automatic_vs_experimental']['lost']}; 1qt9 prior automatic comparison: {prior_partial}.",
        f"Censored comparator results: {len(censored)}. Typed late empty deadline refusals: {late}.",'','Caveats:','']+['- '+x for x in result['caveats']]
(BASE/'performance2_independent_review.md').write_text('\n'.join(lines)+'\n')
print(json.dumps({k:result[k] for k in ['recommendation','gates','cells','charge_s','errors','published_coordinate_instances','jt_comparisons','jt_outside']},indent=2))
