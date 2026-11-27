from pathlib import Path
from fractions import Fraction
from itertools import product
import json, subprocess, hashlib, platform, time
ROOT=Path(__file__).resolve().parent
BIN=ROOT/'libdai_mar'
OUT=ROOT/'qualification'
OUT.mkdir(exist_ok=True)
CASES=[
 ('asymmetric_chain',[2,3,2],[([2,0],[1,3,2,8]),([1,0],[2,1,4,3,2,9]),([1],[2,3,5])],{}),
 ('asymmetric_evidence',[2,3,2],[([2,0],[1,3,2,8]),([1,0],[2,1,4,3,2,9]),([1],[2,3,5])],{1:2}),
 ('isolated_and_fixed',[2,3,2],[([0],[2,3])],{2:1}),
 ('hard_zeros',[2,2,2],[([0,1],[1,0,0,1]),([1,2],[1,2,4,8]),([0],[2,5])],{}),
 ('positive_scalar',[2,2],[([],[7]),([0],[1,4]),([1],[2,3])],{}),
]
def write(name,cards,factors,ev):
 p=OUT/(name+'.uai'); e=OUT/(name+'.uai.evid')
 lines=['MARKOV',str(len(cards)),' '.join(map(str,cards)),str(len(factors))]
 lines += [' '.join(map(str,[len(s)]+s)) for s,v in factors]
 for s,v in factors: lines += [str(len(v)),' '.join(map(str,v))]
 p.write_text('\n'.join(lines)+'\n'); e.write_text(' '.join(map(str,[len(ev)]+[x for k,v in sorted(ev.items()) for x in [k,v]]))+'\n')
 return p,e

def oracle(cards,factors,ev):
 den=Fraction(0); nums=[[Fraction(0) for _ in range(c)] for c in cards]
 for x in product(*map(range,cards)):
  if any(x[i]!=v for i,v in ev.items()):continue
  w=Fraction(1)
  for scope,vals in factors:
   ix=0
   for i in scope:ix=ix*cards[i]+x[i]
   w*=Fraction(str(vals[ix]))
  den+=w
  for i,v in enumerate(x):nums[i][v]+=w
 return [[v/den for v in vs] for vs in nums]

def readmar(p,cards):
 a=p.read_text().split(); assert a[0]=='MAR' and int(a[1])==len(cards); j=2; rows=[]
 for c in cards:
  assert int(a[j])==c; j+=1; rows.append(list(map(float,a[j:j+c]))); j+=c
 assert j==len(a)
 return rows
rows=[]
for name,cards,fac,ev in CASES:
 p,e=write(name,cards,fac,ev); truth=oracle(cards,fac,ev)
 for arm,alg in [('JTREE','JTREE[inference=SUMPROD,updates=HUGIN,maxmem=8589934592]'),('BP','BP[inference=SUMPROD,updates=SEQMAX,logdomain=0,tol=1e-9,maxiter=10000,damping=0.0,maxtime=2]')]:
  mar=OUT/(name+'_'+arm+'.MAR');side=OUT/(name+'_'+arm+'.json')
  proc=subprocess.run([str(BIN),str(p),str(e),str(mar),str(side),alg],capture_output=True,text=True,timeout=5)
  err=None
  if proc.returncode==0:
   got=readmar(mar,cards);err=max(abs(got[i][j]-float(truth[i][j])) for i,c in enumerate(cards) for j in range(c))
  rows.append(dict(case=name,arm=arm,returncode=proc.returncode,max_abs_error=err,pass_=proc.returncode==0 and err<1e-8,stdout=proc.stdout,stderr=proc.stderr))
p,e=write('impossible_evidence',[2,2],[([0],[1,0]),([1],[2,3])],{0:1})
proc=subprocess.run([str(BIN),str(p),str(e),str(OUT/'zero.MAR'),str(OUT/'zero.json'),'JTREE[inference=SUMPROD,updates=HUGIN]'],capture_output=True,text=True,timeout=5)
rows.append(dict(case='impossible_evidence',returncode=proc.returncode,pass_=proc.returncode==5 and json.loads((OUT/'zero.json').read_text())['status']=='ZERO_PARTITION'))
res=dict(all_ok=all(r['pass_'] for r in rows),n=len(rows),checks=rows,binary_sha256=hashlib.sha256(BIN.read_bytes()).hexdigest())
(ROOT/'LIBDAI_QUALIFICATION.json').write_text(json.dumps(res,indent=2)+'\n')
print(json.dumps(res,indent=2))
