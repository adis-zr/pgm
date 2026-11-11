"""Independent whole-joint tests of source-DAG response computation."""
from fractions import Fraction as F
from itertools import product
import random
import time
from prototype import dag


def oracle(model):
    cs=model['cards']; out=[[F(0) for _ in range(d)] for d in cs]; z=F(0)
    for a in product(*(range(d) for d in cs)):
        w=F(1)
        for f in model['factors']:
            i=0
            for v in f['scope']: i=i*cs[v]+a[v]
            w*=f['values'][i]
        z+=w
        for v,s in enumerate(a):out[v][s]+=w
    return [[x/z for x in row] for row in out]


def generated(seed):
    rng=random.Random(seed); n=6; topo=list(range(n));rng.shuffle(topo)
    cs=[rng.choice([2,3]) for _ in range(n)];fs=[]
    for vi,v in enumerate(topo):
        parents=[u for u in topo[:vi] if rng.random()<.6]
        scope=parents+[v]; table={}
        for pa in product(*(range(cs[u]) for u in parents)):
            weights=[rng.randrange(5) for _ in range(cs[v])]
            if not sum(weights):weights[0]=1
            scale=F(rng.randrange(999999,1000002),1000000)
            for s,w in enumerate(weights):table[pa+(s,)]=scale*F(w,sum(weights))
        perm=list(scope);rng.shuffle(perm);vals=[]
        for aa in product(*(range(cs[u]) for u in perm)):
            assign=dict(zip(perm,aa)); vals.append(table[tuple(assign[u] for u in scope)])
        fs.append({'scope':tuple(perm),'values':vals})
    rng.shuffle(fs)
    return {'cards':cs,'factors':fs,'evidence':{}}


def test_random_dags():
    for seed in range(32):
        model=generated(seed); truth=oracle(model); result=dag.solve(model)
        assert len(result['intervals'])==len(truth)
        for tr,ir,pr in zip(truth,result['intervals'],result['points']):
            assert sum(pr)==1
            for p,(lo,hi),x in zip(tr,ir,pr):
                assert lo<=p<=hi and abs(x-p)<=F(1,200)
                assert hi-lo<=F(1,100)


def test_cycle_not_oriented():
    m={'cards':[2,2],'factors':[{'scope':(0,1),'values':[F(1,2)]*4}]*2,'evidence':{}}
    try:dag.solve(m)
    except dag.Unsupported:return
    assert False


def test_evidence_not_silently_ignored():
    m=generated(100);m['evidence']={0:1}
    try:dag.solve(m)
    except dag.Unsupported:return
    assert False


def test_deadline():
    try:dag.solve(generated(2),deadline=time.monotonic()-1)
    except dag.Deadline:return
    assert False


def correlated_response(nonlinear=False):
    """U=X and V=X: their singleton laws do not determine a general response."""
    values=[]
    for u,v in product(range(2),repeat=2):
        p=F(u*v) if nonlinear else F(1,10)+F(u,5)+F(3*v,10)
        values.extend((1-p,p))
    return {'cards':[2]*4,'evidence':{},'factors':[
        {'scope':(0,),'values':[F(1,2)]*2},
        {'scope':(0,1),'values':[F(1),F(0),F(0),F(1)]},
        {'scope':(0,2),'values':[F(1),F(0),F(0),F(1)]},
        {'scope':(1,2,3),'values':values}]}


def test_correlated_additive_closure():
    model=correlated_response();p=dag.plan(model);out=dag.execute_plan(p)
    assert not p['independent'][3]
    assert 3 in p['additive_identities'] and 3 not in p['joint_plans']
    assert out['points']==oracle(model)
    assert out['points'][3][1]==F(7,20)
    assert any(c<0 for terms in p['additive_identities'][3]['terms'] for _,_,c in terms)
    assert p['additive_identities'][3]['checked_coordinates']==8
    plain=dag.solve(model,additive=False)
    assert out['points']==plain['points']
    assert out['stats']['scalar_ops_predicted']<plain['stats']['scalar_ops_predicted']
    assert out['stats']['additions']+out['stats']['multiplications']==out['stats']['scalar_ops_predicted']


def test_correlated_nonlinear_rejected():
    model=correlated_response(nonlinear=True);p=dag.plan(model);out=dag.execute_plan(p)
    assert not p['independent'][3]
    assert 3 not in p['additive_identities'] and 3 in p['joint_plans']
    check=next(x for x in p['additive_checks'] if x['child']==3)
    assert not check['accepted'] and check['rejection_witness'] is not None
    assert check['comparisons']>0 and check['subtractions']>0
    assert out['points']==oracle(model)
    # The correlated value is 1/2; substituting independent marginals gives 1/4.
    assert out['points'][3][1]==F(1,2)


if __name__=='__main__':
    test_random_dags();test_cycle_not_oriented();test_evidence_not_silently_ignored();test_deadline()
    test_correlated_additive_closure();test_correlated_nonlinear_rejected()
    print('PASS: 32 permuted-axis mixed-domain exact-oracle DAGs; correlated additive/signed and nonlinear rejection; cycle/evidence/deadline controls')
