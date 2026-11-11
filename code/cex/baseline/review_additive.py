"""Independent controls for signed additive responses with correlated parents."""
from fractions import Fraction as F
from itertools import product
from pathlib import Path
from math import prod
import random,json,time,hashlib
import dag

def oracle(m):
 states=list(product(*(range(d) for d in m['cards'])));weights=[]
 for x in states:
  w=F(1)
  for f in m['factors']:
   ix=sum(x[v]*prod(m['cards'][u] for u in f['scope'][j+1:]) for j,v in enumerate(f['scope']))
   w*=f['values'][ix]
  weights.append(w)
 z=sum(weights)
 return [[sum(w for x,w in zip(states,weights) if x[v]==a)/z for a in range(d)] for v,d in enumerate(m['cards'])]

def instance(seed,nonlinear=False,perturb=False):
 rng=random.Random(seed);cards=[2]*5;fs=[]
 for child,parents,fn in [(0,(),lambda p:F(3,7)),(1,(0,),lambda p:F(1,5)+F(1,2)*p[0]),(2,(0,),lambda p:F(7,10)-F(2,5)*p[0]),(3,(1,2),lambda p:F(3,10)+F(1,5)*p[0]-F(1,10)*p[1]+(F(1,20)*p[0]*p[1] if nonlinear else 0)),(4,(3,1),lambda p:F(1,2)-F(1,5)*p[0]+F(1,10)*p[1])]:
  values=[]
  for p in product(*(range(cards[v]) for v in parents)):
   q=fn(p);row=[1-q,q]
   if perturb:row=[a*(1+F(sum(p)+child,10**6)) for a in row]
   values.extend(row)
  fs.append({'scope':parents+(child,),'values':values})
 renamed=list(range(5));rng.shuffle(renamed);out=[]
 for f in fs:
  axis=list(f['scope']);rng.shuffle(axis);vals=[]
  for a in product(range(2),repeat=len(axis)):
   old=dict(zip(axis,a));ix=sum(old[v]*2**(len(f['scope'])-j-1) for j,v in enumerate(f['scope']))
   vals.append(f['values'][ix])
  out.append({'scope':tuple(renamed[v] for v in axis),'values':vals})
 rng.shuffle(out)
 return {'cards':cards,'evidence':{},'factors':out},renamed

rows=[]
for seed in range(12):
 for nonlinear,perturb in [(False,False),(True,False),(False,True)]:
  m,names=instance(seed,nonlinear,perturb);truth=oracle(m);p=dag.plan(m,time.monotonic()+3);r=dag.execute_plan(p,time.monotonic()+3)
  assert all(lo<=q<=hi for ints,qs in zip(r['intervals'],truth) for (lo,hi),q in zip(ints,qs))
  assert r['stats']['additions']+r['stats']['multiplications']==r['stats']['scalar_ops_predicted']
  if not perturb:assert r['points']==truth
  assert not p['independent'][names[3]] and not p['independent'][names[4]]
  assert names[4] in p['additive_identities']
  if nonlinear:assert names[3] not in p['additive_identities']
  else:assert names[3] in p['additive_identities']
  coeff=[c for ident in p['additive_identities'].values() for terms in ident['terms'] for _,_,c in terms]
  assert any(c<0 for c in coeff)
  rows.append({'seed':seed,'nonlinear':nonlinear,'raw_perturbation':perturb,'containment':True,'signed_coefficients':True,'correlated_parent_additive_used':True,'scalar_counts_match':True})
out={'controls':rows,'passed':len(rows),'dag_sha256':hashlib.sha256(Path(dag.__file__).read_bytes()).hexdigest(),'scope':'independent exact whole-joint oracle; shuffled IDs/factors/axes; correlated parents; signed additive recursion; nonlinear rejection; raw normalization perturbations'}
Path(__file__).with_name('REVIEW_ADDITIVE_RESULTS.json').write_text(json.dumps(out,indent=2)+'\n')
print(json.dumps({'passed':len(rows),'dag_sha256':out['dag_sha256']}))
