"""Independent exhaustive oracle for support propagation + bijection quotient (the R18 packet checker, verbatim except for the two paths taken from argv: MODULE OUT).

Uses the reducer's public primitives, but no reducer helper for enumeration,
weight evaluation, assignment decoding, normalizers, or marginal queries.
"""
import hashlib, importlib.util, itertools, json, random, time, sys
from fractions import Fraction as F
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
SOURCE=Path(sys.argv[1])
spec=importlib.util.spec_from_file_location('under_test',SOURCE)
M=importlib.util.module_from_spec(spec);spec.loader.exec_module(M)

def reduce(cards,evidence,factors):
    domains={i:({evidence[i]} if i in evidence else set(range(c))) for i,c in enumerate(cards)}
    decoders={i:(i,{x:x for x in d}) for i,d in domains.items()}
    scalar=F(1);fs=[(tuple(s),dict(rs)) for s,rs in factors]
    for _ in range(50):
        before=(len(domains),sum(map(len,domains.values())),len(fs))
        fs,_=M.gac(domains,fs)
        nd,nf,maps,st=M.quotient(domains,fs)
        scalar*=F(st['constant_multiplier'])
        for i,(r,oldmap) in list(decoders.items()):
            if r is not None:
                newroot,newmap=maps[r]
                decoders[i]=(newroot,{a:oldmap[b] for a,b in newmap.items()})
        domains,fs=nd,nf
        if (len(domains),sum(map(len,domains.values())),len(fs))==before:
            return domains,fs,decoders,scalar
    raise AssertionError('unexpected failure to reach fixed point')

def weight(x,factors):
    w=F(1)
    for scope,rows in factors:w*=rows.get(tuple(x[i] for i in scope),F(0))
    return w

def check(name,cards,evidence,factors):
    original={}
    for x in itertools.product(*(range(c) for c in cards)):
        if any(x[v]!=a for v,a in evidence.items()):continue
        w=weight(x,factors)
        if w:original[x]=w
    z=sum(original.values(),F(0))
    try:domains,fs,decoders,scalar=reduce(cards,evidence,factors)
    except ValueError as e:
        assert z==0,(name,'false zero evidence',str(e))
        return dict(name=name,zero_mass=True,refused=str(e),positive_assignments=0)
    roots=sorted(domains);decoded={};reduced_z=F(0);expanded_z=F(0)
    by_original=[{a:F(0) for a in range(c)} for c in cards]
    by_reduced=[{a:F(0) for a in range(c)} for c in cards]
    for x,w in original.items():
        for i,a in enumerate(x):by_original[i][a]+=w
    rows_checked=0
    for ys in itertools.product(*(sorted(domains[r]) for r in roots)):
        y=dict(zip(roots,ys));w=weight(y,fs);reduced_z+=w
        x=tuple(mp[None] if r is None else mp[y[r]] for i,(r,mp) in sorted(decoders.items()))
        assert all(x[v]==a for v,a in evidence.items()),(name,'evidence decoder')
        assert weight(x,factors)==scalar*w,(name,'pointwise weight mismatch',x,w,scalar)
        rows_checked+=1
        if w:
            assert x not in decoded,(name,'non-injective positive decoder')
            decoded[x]=scalar*w;expanded_z+=scalar*w
            for i,a in enumerate(x):by_reduced[i][a]+=scalar*w
    assert decoded==original,(name,'positive support correspondence')
    assert scalar*reduced_z==z==expanded_z,(name,'normalizer/multiplicity')
    assert by_original==by_reduced,(name,'query numerator mismatch')
    if z:
        assert all(by_original[i][a]/z==by_reduced[i][a]/expanded_z for i,c in enumerate(cards) for a in range(c))
    return dict(name=name,zero_mass=(z==0),positive_assignments=len(original),reduced_assignment_rows=rows_checked,
                query_coordinates=sum(cards),scalar=str(scalar),normalizer=str(z),reduced_variables=len(domains))

def f(scope,rows):return tuple(scope),{tuple(a):F(w) for a,w in rows if w}

def cases():
    yield 'factorless_multiplicity',[2,3,2],{},[]
    yield 'weighted_bijection',[3,3],{},[f((0,1),[((0,2),F(1,3)),((1,0),F(2,5)),((2,1),F(7,11))])]
    yield 'weighted_bijection_evidence',[3,3,2],{1:0},[f((0,1),[((0,2),F(1,3)),((1,0),F(2,5)),((2,1),F(7,11))])]
    yield 'weighted_equalities_repeated_scopes',[2,2,2],{},[
        f((0,1),[((0,0),F(1,3)),((1,1),F(3,2))]),
        f((1,2),[((0,0),F(5,7)),((1,1),F(7,5))]),
        f((0,2),[((0,0),2),((0,1),5),((1,0),7),((1,1),11)])]
    eq=f((0,1),[((0,0),1),((1,1),1)])
    yield 'inconsistent_binary_cycle',[2,2,2],{},[eq,f((1,2),[((0,0),1),((1,1),1)]),f((0,2),[((0,1),1),((1,0),1)])]
    yield 'partially_consistent_permutation_cycle',[3,3,3],{},[
        f((0,1),[((0,0),1),((1,1),2),((2,2),3)]),
        f((1,2),[((0,0),1),((1,1),1),((2,2),1)]),
        f((0,2),[((0,0),5),((1,2),7),((2,1),11)])]
    yield 'empty_zero_factor',[2,2],{},[f((0,1),[])]
    yield 'positive_scalar',[2,3],{},[f((),[((),F(7,3))])]
    yield 'zero_scalar',[2,3],{},[f((),[])]
    yield 'all_fixed',[2,2],{0:1},[eq]
    yield 'same_values_not_bijection',[2,2],{},[f((0,1),[(a,1) for a in itertools.product(range(2),repeat=2)])]
    yield 'ternary_implied_pair',[2,2,2],{},[f((0,1,2),[(a,F(1+2*a[2],3)) for a in itertools.product(range(2),repeat=3) if a[0]==a[1]])]
    rng=random.Random(20261121)
    for k in range(300):
        n=rng.randrange(2,6);cards=[rng.randrange(1,4) for _ in range(n)];fs=[]
        for j in range(rng.randrange(0,8)):
            scope=tuple(rng.sample(range(n),rng.randrange(0,min(3,n)+1)))
            rows=[]
            for a in itertools.product(*(range(cards[i]) for i in scope)):
                w=F(rng.choice([0,0,0,1,2,3,5]),rng.choice([1,2,3,5]));rows.append((a,w))
            fs.append(f(scope,rows))
        ev={i:rng.randrange(c) for i,c in enumerate(cards) if rng.random()<.15}
        yield 'random_%03d'%k,cards,ev,fs

if __name__=='__main__':
    t=time.monotonic();results=[]
    for case in cases():results.append(check(*case))
    report=dict(source_sha256=hashlib.sha256(SOURCE.read_bytes()).hexdigest(),seed=20261121,
                checks=len(results),positive_mass_cases=sum(not r['zero_mass'] for r in results),
                zero_mass_cases=sum(r['zero_mass'] for r in results),
                original_positive_assignments=sum(r['positive_assignments'] for r in results),
                reduced_assignment_rows=sum(r.get('reduced_assignment_rows',0) for r in results),
                original_query_coordinates=sum(r.get('query_coordinates',0) for r in results),
                elapsed_seconds=time.monotonic()-t,status='PASS',results=results)
    Path(sys.argv[2]).write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps({k:v for k,v in report.items() if k!='results'},indent=2))
