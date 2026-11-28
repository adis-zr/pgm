from pathlib import Path
import collections, hashlib, json, statistics, os
ROOT=Path(__file__).resolve().parents[2]
P=Path(os.environ.get('PGM_REVIEW_ROOT', ROOT/'pgm-step2-review'))/'documentation/consolidation/step2/run'
A=json.load(open(P/'ANALYSIS.json')); F=json.load(open(P/'FREEZE.json'))
rows=[json.loads(x) for x in (P/'CELLS_COMPACT.jsonl').read_text().splitlines()]
receipts=[json.loads(x) for x in (P/'RECEIPTS.jsonl').read_text().splitlines()]
terminal=[r for r in receipts if r.get('kind')=='END']
if not terminal:
 print('receipt kinds',collections.Counter(x.get('kind') for x in receipts))
 terminal=[r for r in receipts if 'wall_s' in r]
by={(r['task'],r['arm'],r['replicate']):r for r in rows}
expected={(t['name'],arm,rep) for t in F['tasks'] for arm in F['arms'] for rep in F['replicates']}
assert len(by)==len(rows)==len(expected)==732 and set(by)==expected
end={r['job']:r for r in terminal}
assert len(end)==len(terminal)==732
mismatch=[]
for row in rows:
 r=end[row['job']]
 for a,b in [('wall_s','wall_s'),('receipt_outcome','outcome'),('returncode','returncode'),('peak_rss_bytes','peak_tree_rss_bytes')]:
  if row.get(a)!=r.get(b): mismatch.append([row['job'],a,row.get(a),r.get(b)])
sets={arm:{t['name'] for t in F['tasks'] if all(by[(t['name'],arm,rep)]['complete_within_contract'] for rep in F['replicates'])} for arm in F['arms']}
assert {arm:sorted(x) for arm,x in sets.items()}==A['groups']['all61']['complete_both']
pairs={}
for name,(ca,co) in F['pairs'].items():
 mutual=sets[ca]&sets[co]; vals=[]
 for t in sorted(mutual):
  wa=[by[t,ca,r]['wall_s'] for r in F['replicates']]; wb=[by[t,co,r]['wall_s'] for r in F['replicates']]
  vals.append({'task':t,'candidate':statistics.median(wa),'comparator':statistics.median(wb),'ratio':statistics.median(wa)/statistics.median(wb),'ratios':[a/b for a,b in zip(wa,wb)],'differences':[a-b for a,b in zip(wa,wb)]})
 med=statistics.median(x['ratio'] for x in vals)
 assert med==A['pairs'][name]['median_ratio_on_mutual']
 pairs[name]={'mutual':len(mutual),'candidate_only':sorted(sets[ca]-sets[co]),'comparator_only':sorted(sets[co]-sets[ca]),'median_ratio':med,'faster_both':sum(all(r<1 for r in x['ratios']) for x in vals),'slower_both':sum(all(r>1 for r in x['ratios']) for x in vals),'mixed':sum(min(x['ratios'])<=1<=max(x['ratios']) for x in vals),'values':vals}
flags=[x for x in pairs['same_round_accepted']['values'] if all(r>1.25 for r in x['ratios']) and all(d>.1 for d in x['differences'])]
assert {x['task'] for x in flags}=={x['task'] for x in A['cost_flags']}
assert sum((r.get('published') or 0) for r in rows if r['arm'].startswith('PGM'))==A['geometry']['published_coordinate_instances']
D=A['overhead_decomposition']; workers=[]
for d in D:
 for rep,(w,r,o,receipt_diff) in enumerate(zip(d['candidate_worker_wall_s'],d['comparator_internal_wall_s'],d['common_contract_overhead_s'],d['differences_s']),1):
  workers.append({'task':d['task'],'rep':rep,'worker_minus_reference_internal':w-r,'common_overhead':o,'receipt_difference':receipt_diff,'outside_residual':receipt_diff-o-(w-r),'flagged':d['task'] in {x['task'] for x in flags}})
bytask={x['task']:x for x in pairs['same_round_accepted']['values']}
slow=[x['ratio'] for x in bytask.values() if x['comparator']>2]
latency={str(th):{arm:sum(all(by[t,arm,r]['wall_s']<=th for r in F['replicates']) for t in sets[arm]) for arm in F['arms']} for th in [.1,.5,1,2,5,10,20]}
summary={'scope':'Recompute committed compact cells, terminal receipts and analytical aggregates; raw coordinate artifacts not present in repository so cannot independently replay all geometry or JT comparisons.',
 'source_sha256':{n:hashlib.sha256((P/n).read_bytes()).hexdigest() for n in ['CELLS_COMPACT.jsonl','RECEIPTS.jsonl','ANALYSIS.json','FREEZE.json']},'counts':{arm:len(x) for arm,x in sets.items()},'receipt_mismatches':mismatch,'terminal_receipts':len(terminal),'charge_s':sum(r['wall_s'] for r in terminal),'completion_sets':{k:sorted(v) for k,v in sets.items()},'pairs':pairs,'cost_flags':flags,'workers':workers,'reference_over2s':{'tasks':len(slow),'median_ratio':statistics.median(slow)},'latency':latency,
 'common_overhead_summary':{'min':min(x['common_overhead'] for x in workers),'median':statistics.median(x['common_overhead'] for x in workers),'max':max(x['common_overhead'] for x in workers)},
 'worker_difference_summary':{'min':min(x['worker_minus_reference_internal'] for x in workers),'median':statistics.median(x['worker_minus_reference_internal'] for x in workers),'max':max(x['worker_minus_reference_internal'] for x in workers)},
 'guarantees_complete':{arm:dict(collections.Counter(by[t,arm,1].get('guarantee') for t in ss)) for arm,ss in sets.items()},'identity_failures':[r['job'] for r in rows if not r['identity_ok']],'published_coordinate_instances_sum':sum((r.get('published') or 0) for r in rows if r['arm'].startswith('PGM')),'analytical_jt_comparison_outputs':len(A['jt_agreement']),'analytical_jt_coordinate_instances':sum(r['coordinates'] for r in A['jt_agreement']),'analytical_jt_partials':sum(r['partial'] for r in A['jt_agreement'])}
(Path(__file__).parent/'RECOMPUTED_RESULTS.json').write_text(json.dumps(summary,indent=2)+'\n')
print(json.dumps({k:v for k,v in summary.items() if k not in ['workers','pairs','completion_sets','source_sha256']},indent=2))
print('PAIR SUMMARY',json.dumps({k:{kk:vv for kk,vv in v.items() if kk!='values'} for k,v in pairs.items()},indent=2))
print('BIGGEST WORKER DIFFS',json.dumps(sorted(workers,key=lambda x:x['worker_minus_reference_internal'],reverse=True)[:10],indent=2))
