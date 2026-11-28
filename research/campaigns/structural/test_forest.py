"""Independent joint-enumeration controls and reproducible forest scaling."""

# Source-checkout entry point; production imports never traverse research.
if __package__ in (None, ""):
    import sys as _research_sys
    from pathlib import Path as _ResearchPath
    _research_sys.path.insert(0, str(_ResearchPath(__file__).resolve().parents[3]))
from research.bootstrap import activate as _activate_research
_activate_research()
from research.paths import repo_root as _repo_root, runs_root as _runs_root, records_root as _records_root, source_path as _source_path
from fractions import Fraction as F
from itertools import product
from pathlib import Path
from math import prod
import argparse, hashlib, json, random, time
import pgm.algorithms.structural.forest as forest


def oracle(model):
    cards=model['cards'];ev=model.get('evidence',{});rows=[[F(0) for _ in range(d)] for d in cards];z=F(0)
    for xs in product(*(range(d) for d in cards)):
        if any(xs[v]!=x for v,x in ev.items()):continue
        weight=F(1)
        for f in model['factors']:
            ix=0
            for v in f['scope']:ix=ix*cards[v]+xs[v]
            weight*=f['values'][ix]
        z+=weight
        for v,x in enumerate(xs):rows[v][x]+=weight
    return None if not z else [[x/z for x in row] for row in rows]


def check(model,epsilon=F(1,200)):
    exact=oracle(model)
    try:r=forest.solve(model,epsilon=epsilon)
    except forest.ZeroEvidence:
        assert exact is None
        return False
    assert exact is not None
    for truth,intervals,points in zip(exact,r['intervals'],r['points']):
        assert sum(points)==1
        for q,(lo,hi),point in zip(truth,intervals,points):
            assert 0<=lo<=q<=hi<=1 and lo<=point<=hi
            assert hi-lo<=epsilon and abs(point-q)<=epsilon
    assert r['stats']['producer']['max_mantissa_bits']<=r['stats']['precision_bits']
    return True


def random_model(rng):
    n=rng.randrange(1,8);cards=[rng.randrange(1,4) for _ in range(n)];ids=list(range(n));rng.shuffle(ids);factors=[]
    def factor(scope):
        if rng.random()<.5:scope=tuple(reversed(scope))
        vals=[F(rng.randrange(0,15),rng.randrange(1,12)) for _ in range(prod(cards[v] for v in scope))]
        factors.append({'scope':scope,'values':vals})
    for i,v in enumerate(ids):
        if rng.random()<.8:factor((v,))
        if i and rng.random()<.85:
            w=ids[rng.randrange(i)]
            for _ in range(rng.randrange(1,4)):factor((v,w))
    if rng.random()<.3:factor(())
    return {'cards':cards,'factors':factors,'evidence':{v:rng.randrange(d) for v,d in enumerate(cards) if rng.random()<.3}}


def chain(n,shape='chain',observed=False):
    fs=[{'scope':(v,),'values':[F(1,3),F(2,3)]} for v in range(n)]
    fs += [{'scope':(0 if shape=='star' else v-1,v),'values':[F(2),F(1),F(1),F(2)]} for v in range(1,n)]
    return {'cards':[2]*n,'factors':fs,'evidence':{v:0 for v in range(0,n,2)} if observed else {}}


def run(scale=False):
    start=time.monotonic();rng=random.Random(831472);positive=zero=0
    for i in range(180):
        passed=check(random_model(rng),[F(1,200),F(1,1000),F(1,3),F(1,2**60)][i%4])
        positive+=int(passed);zero+=int(not passed)
    controls=[]
    # Evidence reduces a genuinely higher-arity factor to a reversed unequal-domain pair.
    models=[{'cards':[2,3,2],'factors':[{'scope':(2,1,0),'values':[F(i+1,7) for i in range(12)]}],'evidence':{1:2}},
            {'cards':[3,2],'factors':[],'evidence':{0:1,1:0}},
            {'cards':[],'factors':[{'scope':(),'values':[F(3,5)]}],'evidence':{}},
            {'cards':[2,3],'factors':[],'evidence':{}},
            {'cards':[2],'factors':[{'scope':(0,),'values':[F(0),F(0)]}],'evidence':{}},
            {'cards':[2],'factors':[{'scope':(),'values':[F(0)]}],'evidence':{}}]
    for i,m in enumerate(models):controls.append({'name':'edge_case_'+str(i),'positive':check(m)})
    huge=chain(5)
    huge['factors'] += [{'scope':(v,),'values':[F(1<<10000),F(1,1<<10000)]} for v in range(5)]
    assert check(huge)
    hr=forest.solve(huge)
    controls.append({'name':'source_exponents_10000','max_abs_exponent':hr['stats']['producer']['max_abs_exponent'],
                     'source_bits':hr['stats']['recognition']['input_numerator_bits']+hr['stats']['recognition']['input_denominator_bits'],
                     'large_gap_additions':hr['stats']['producer']['large_gap_additions'],
                     'output_denominator_bits':max(x.denominator.bit_length() for row in hr['points'] for x in row)})
    # An exponent of size 10^9 must not create an integer with 10^9 bits.
    a=forest.Arithmetic(32);big=forest.D(1<<31,10**9);small=forest.D(1<<31,-10**9)
    lo=a._add(big,small,False);hi=a._add(big,small,True)
    assert lo==big and hi.m==(1<<31)+1 and hi.e==big.e
    assert forest._grid(small,20,False)==0 and forest._grid(small,20,True)==1
    controls.append({'name':'exponent_gap_two_billion','max_temporary_bits':a.stats['max_temporary_bits']})
    cycle={'cards':[2]*3,'factors':[{'scope':e,'values':[F(1)]*4} for e in [(0,1),(1,2),(2,0)]],'evidence':{}}
    try:forest.solve(cycle);raise AssertionError('accepted cycle')
    except forest.UnsupportedError:pass
    cycle['evidence']={0:1};assert check(cycle)
    try:forest.solve(chain(2),deadline=time.monotonic()-1);raise AssertionError('accepted expired deadline')
    except forest.DeadlineExceeded as exc:assert exc.stats['elapsed_s']>=0
    deadline_model=chain(500)
    dt=time.monotonic()
    try:forest.solve(deadline_model,deadline=dt+.002);raise AssertionError('missed short deadline')
    except forest.DeadlineExceeded as exc:
        assert time.monotonic()-dt<1 and exc.stats['elapsed_s']>0
    scaling=[]
    if scale:
        for shape in ('chain','star'):
            for n in (16,64,256,1024,4096):
                r=forest.solve(chain(n,shape),deadline=time.monotonic()+60)
                s=r['stats'];pro=s['producer'];rep=s['replay'];labels=s['label_passes']
                schedule=sum(sum(p[k] for k in ('source_conversions','adds','mults','divisions')) for p in labels+[pro,rep])
                scaling.append({'shape':shape,'n':n,'elapsed_s':s['elapsed_s'],'precision_bits':s['precision_bits'],
                                'K':s['max_normalization_error_label'],'arithmetic_schedule_calls':schedule,
                                'arithmetic_calls_per_n':schedule/n,'source_entries_per_scan':s['recognition']['source_entries_read'],
                                'max_temporary_bits':pro['max_temporary_bits'],'max_exponent_bits':pro['max_exponent_bits'],
                                'publication_coordinates':s['publication']['coordinates']})
        for n in (256,1024):
            r=forest.solve(chain(n,observed=True))
            scaling.append({'shape':'evidence_chain','n':n,'elapsed_s':r['stats']['elapsed_s'],'free_variables':r['stats']['recognition']['free_variables'],
                            'precision_bits':r['stats']['precision_bits'],'source_entries_per_scan':r['stats']['recognition']['source_entries_read']})
    receipt={'status':'PASS','random_seed':831472,'random_cases':180,'random_positive':positive,'random_zero_mass':zero,
             'controls':controls,'scaling':scaling,'total_test_s':time.monotonic()-start,
             'source_sha256':hashlib.sha256(Path(forest.__file__).read_bytes()).hexdigest(),
             'test_sha256':hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
             'oracle':'independent full-joint Fraction enumeration; every original coordinate checked',
             'scope':'empirical correctness and scaling controls; Theta(n) is a scoped word-RAM theorem, not inferred from Python timings'}
    dest=Path(__file__).with_name('FOREST_QUALIFICATION.json');dest.write_text(json.dumps(receipt,indent=2)+'\n')
    print(json.dumps(receipt,indent=2))
    return receipt

if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--scale',action='store_true');args=parser.parse_args();run(args.scale)
