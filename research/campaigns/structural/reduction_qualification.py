"""Independent weighted-alias and original-query lift controls."""

# Source-checkout entry point; production imports never traverse research.
if __package__ in (None, ""):
    import sys as _research_sys
    from pathlib import Path as _ResearchPath
    _research_sys.path.insert(0, str(_ResearchPath(__file__).resolve().parents[3]))
from research.bootstrap import activate as _activate_research
_activate_research()
from research.paths import repo_root as _repo_root, runs_root as _runs_root, records_root as _records_root, source_path as _source_path
from pathlib import Path
from fractions import Fraction as F
from itertools import product
import json
import hashlib
import random
import time
import traceback
import pgm.algorithms.structural.reduction as reduction
import pgm.algorithms.structural.core as core
from research.campaigns.structural.qualification import oracle, permute, fingerprint, check_output, implementation_hashes


def model_for(seed):
    rng=random.Random(seed)
    cards=[3,3,3,2]
    h1=list(range(3));h2=list(range(3))
    rng.shuffle(h1);rng.shuffle(h2)
    fs=[]
    for u,v,h in [(0,1,h1),(1,2,h2)]:
        weights=[F(rng.randrange(1,9),rng.randrange(1,9)) for _ in range(3)]
        vals=[weights[a] if b==h[a] else F(0) for a,b in product(range(3),repeat=2)]
        fs.append({'scope':(u,v),'values':vals})
    if seed%3==0:
        fs.append({'scope':fs[0]['scope'],'values':list(fs[0]['values'])})
    witness=[rng.randrange(3),None,None,rng.randrange(2)]
    witness[1]=h1[witness[0]];witness[2]=h2[witness[1]]
    # A factor containing both aliased coordinates must retain its weight once
    # when the two source axes collapse to one reduced axis.
    vals=[]
    for a,b,c in product(range(3),range(3),range(2)):
        w=F(rng.randrange(5),rng.randrange(1,8))
        if (a,b,c)==(witness[0],witness[2],witness[3]):w+=1
        vals.append(w)
    fs.append({'scope':(0,2,3),'values':vals})
    fs.append({'scope':(), 'values':[F(7,13)]})
    evidence={}
    if seed%4==0:evidence[2]=witness[2]
    if seed%7==0:evidence[3]=witness[3]
    return permute({'cards':cards,'factors':fs,'evidence':evidence},rng)


def run():
    hashes_before=implementation_hashes()
    rows=[]
    for seed in range(33000,33080):
        model=model_for(seed)
        row={'seed':seed,'model_sha256':fingerprint(model)}
        try:
            truth=oracle(model)
            assert truth is not None
            reduced=reduction.reduce(model,deadline=time.monotonic()+5)
            assert reduced['status']=='REDUCED'
            exact=oracle(reduced['model'])
            ints=[[(v,v) for v in rr] for rr in exact]
            lifted,points=reduction.lift(reduced,ints,exact)
            assert points==truth
            assert lifted==[[(v,v) for v in rr] for rr in truth]
            result=core.solve(model,deadline=time.monotonic()+5)
            check_output(model,result,truth)
            row['status']='PASS'
            row['aliases']=reduced['stats']['aliases']
            row['states_removed']=reduced['stats']['states_removed']
            row['remaining_variables']=reduced['stats']['remaining_variables']
        except Exception as error:
            row['status']='FAIL';row['error']=repr(error);row['traceback']=traceback.format_exc()
        rows.append(row)
    hashes_after=implementation_hashes()
    stable=hashes_before==hashes_after
    return {'records':rows,'models':len(rows),'passed':sum(x['status']=='PASS' for x in rows),
            'aliases_exercised':sum(x.get('aliases',0) for x in rows),
            'states_removed':sum(x.get('states_removed',0) for x in rows),
            'qualified_hashes':hashes_after,'implementation_stable_during_run':stable,
            'qualification_sha256':hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
            'all_pass':stable and all(x['status']=='PASS' for x in rows),
            'scope':'Exact raw/reduced posterior equality and complete original-query lifting; also integrated pipeline oracle containment.'}


if __name__=='__main__':
    out=run();Path(__file__).with_name('reduction_qualification.json').write_text(json.dumps(out,indent=2)+'\n')
    print(json.dumps({k:v for k,v in out.items() if k!='records'},indent=2))
    for row in out['records']:
        if row['status']!='PASS':print(row)
