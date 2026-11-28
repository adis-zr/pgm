from fractions import Fraction as F
from itertools import product
import random,time
from prototype import reduction
from prototype.core import brute_force


def check_model(model):
    try:truth=brute_force(model)
    except ValueError:truth=None
    r=reduction.reduce(model)
    if r['status']=='ZERO_EVIDENCE':
        assert truth is None
        return r
    if truth is None:return r  # Arc consistency is intentionally incomplete.
    point=brute_force(r['model']);ints=[[(x,x) for x in row] for row in point]
    lifted,got=reduction.lift(r,ints,point)
    assert got==truth and lifted==[[(x,x) for x in row] for row in truth]
    return r


def test_random_models():
    for seed in range(40):
        rng=random.Random(seed);n=6;cards=[rng.choice([2,3]) for _ in range(n)];fs=[]
        for v in range(n):fs.append({'scope':(v,),'values':[F(rng.randrange(5)) for _ in range(cards[v])]})
        for _ in range(8):
            s=tuple(rng.sample(range(n),rng.choice([2,3])));fs.append({'scope':s,'values':[F(rng.randrange(4)) for _ in product(*(range(cards[v]) for v in s))]})
        ev={rng.randrange(n):0} if seed%2 else {}
        check_model({'cards':cards,'factors':fs,'evidence':ev})


def test_weighted_aliases():
    m={'cards':[3,3,3],'factors':[
        {'scope':(0,1),'values':[F(0),F(2),F(0),F(0),F(0),F(3),F(5),F(0),F(0)]},
        {'scope':(2,1),'values':[F(0),F(0),F(7),F(11),F(0),F(0),F(0),F(13),F(0)]},
        {'scope':(2,),'values':[F(17),F(19),F(23)]}], 'evidence':{}}
    r=check_model(m);assert r['stats']['aliases']==2 and len(r['model']['cards'])==1


def test_contradictory_cycle():
    not_equal=[F(0),F(1),F(1),F(0)]
    m={'cards':[2,2,2],'factors':[{'scope':s,'values':not_equal} for s in [(0,1),(1,2),(2,0)]],'evidence':{}}
    r=check_model(m);assert r['status']=='ZERO_EVIDENCE'


def test_all_fixed_and_empty_factors():
    m={'cards':[2,2],'factors':[{'scope':(0,1),'values':[F(1),F(0),F(0),F(2)]}],'evidence':{0:1}}
    r=check_model(m);assert not r['model']['cards']
    check_model({'cards':[2,3],'factors':[],'evidence':{}})


if __name__=='__main__':
    test_random_models();test_weighted_aliases();test_contradictory_cycle();test_all_fixed_and_empty_factors()
    print('PASS: 40 independent brute-force random models; weighted aliases; contradictory cycle; fixed/isolated cases')
