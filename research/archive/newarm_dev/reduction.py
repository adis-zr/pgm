"""Exact support propagation and weighted bijection substitution.

Each source factor is a separate occurrence. The transformations preserve its
product weight on a bijection between positive assignments, except for positive
scalar factors that cancel in every normalized answer. The decoder restores all
original singleton states, including evidence and zero-proved states.

Arc consistency is sound but incomplete; REDUCED does not imply positive Z.
Alias recognition accepts a pair relation only when its whole positive support
is a bijection between the current domains. Its positive weights are retained
as an ordinary unary factor, never silently replaced by one.
"""
from collections import deque
from fractions import Fraction
from itertools import product
from math import prod
import time


class Deadline(TimeoutError):
    def __init__(self, stats):
        self.stats = dict(stats)
        super().__init__('source reduction deadline')


def reduce(model, deadline=None):
    start=time.monotonic();cards=tuple(model['cards']);n=len(cards)
    stats={'source_entries_read':0,'initial_positive_rows':0,'support_rows_visited':0,
           'states_removed':0,'aliases':0,'alias_rows_visited':0,'scalar_factors_cancelled':0,
           'incidence_entries_built':0,'dense_entries_materialized':0,'arc_passes':0}
    ticks=0
    def check(force=False):
        nonlocal ticks
        ticks+=1
        if force or not ticks % 512:
            if deadline is not None and time.monotonic()>=deadline:
                stats['elapsed_s']=time.monotonic()-start;raise Deadline(stats)
    if any(type(d) is not int or d<=0 for d in cards):raise ValueError('invalid cardinality')
    evidence=dict(model.get('evidence',{}))
    if any(type(v) is not int or not 0<=v<n or type(a) is not int or not 0<=a<cards[v]
           for v,a in evidence.items()):raise ValueError('invalid evidence')
    domains={v:({evidence[v]} if v in evidence else set(range(cards[v]))) for v in range(n)}
    # Each old coordinate maps to a state of its current representative. Missing
    # mappings denote proved-zero original states.
    dec=[{'representative':v,'map':{a:a for a in domains[v]}} for v in range(n)]
    factors=[];zero_source=False
    for fi,f in enumerate(model['factors']):
        check(True);scope=tuple(f['scope']);values=f['values']
        if len(set(scope))!=len(scope) or any(type(v) is not int or not 0<=v<n for v in scope):
            raise ValueError('invalid factor scope')
        if len(values)!=prod(cards[v] for v in scope):raise ValueError('factor shape mismatch')
        data={}
        for a,w in zip(product(*(range(cards[v]) for v in scope)),values):
            check();stats['source_entries_read']+=1
            if not isinstance(w,(Fraction,int)) or w<0:raise ValueError('nonnegative exact rationals required')
            if w and all(s in domains[v] for v,s in zip(scope,a)):
                data[a]=Fraction(w);stats['initial_positive_rows']+=1
        if not data:zero_source=True
        factors.append({'scope':scope,'data':data,'source_factor':fi})
    def zero(reason):
        stats['elapsed_s']=time.monotonic()-start
        return {'status':'ZERO_EVIDENCE','reason':reason,'model':None,'decoder':None,'stats':stats}
    if zero_source:return zero('source factor has no positive evidence-compatible row')
    alias_witnesses=[];state_witnesses=[]
    while True:
        check(True);stats['arc_passes']+=1
        incidence={v:set() for v in domains}
        for fi,f in enumerate(factors):
            for v in f['scope']:incidence[v].add(fi);stats['incidence_entries_built']+=1
        queue=deque(range(len(factors)));queued=set(queue)
        while queue:
            check();fi=queue.popleft();queued.discard(fi);f=factors[fi];scope=f['scope']
            supports={v:set() for v in scope};kept={}
            for a,w in f['data'].items():
                check();stats['support_rows_visited']+=1
                if all(s in domains[v] for v,s in zip(scope,a)):
                    kept[a]=w
                    for v,s in zip(scope,a):supports[v].add(s)
            f['data']=kept
            if not kept:return zero('support propagation found an empty factor')
            for v in scope:
                removed=domains[v]-supports[v]
                if removed:
                    stats['states_removed']+=len(removed)
                    state_witnesses.append({'variable':v,'states':sorted(removed),'source_factor':f['source_factor']})
                    domains[v]-=removed
                    if not domains[v]:return zero('empty propagated domain')
                    for gj in incidence[v]:
                        if gj not in queued:queue.append(gj);queued.add(gj)
        if stats['arc_passes']==1:
            stats['initial_arc_forced_beyond_evidence']=sum(len(D)==1 and v not in evidence for v,D in domains.items())
        # Fixed coordinates disappear from factor scopes. Retain their decoder.
        stripped=[]
        for f in factors:
            scope=f['scope'];positions=[i for i,v in enumerate(scope) if len(domains[v])>1]
            new_scope=tuple(scope[i] for i in positions)
            if not new_scope:
                # All remaining assignments to this factor are the same fixed
                # tuple; positivity was established by complete support scan.
                assert len(f['data'])==1
                stats['scalar_factors_cancelled']+=1;continue
            new_data={}
            for a,w in f['data'].items():
                check();key=tuple(a[i] for i in positions)
                assert key not in new_data
                new_data[key]=w
            stripped.append({'scope':new_scope,'data':new_data,'source_factor':f['source_factor']})
        factors=stripped
        candidate=None
        for f in factors:
            check()
            if len(f['scope'])!=2:continue
            u,v=sorted(f['scope'])
            if len(domains[u])!=len(domains[v]) or len(f['data'])!=len(domains[u]):continue
            ui=f['scope'].index(u);vi=f['scope'].index(v)
            mapping={a[ui]:a[vi] for a in f['data']}
            if set(mapping)==domains[u] and set(mapping.values())==domains[v]:
                candidate=u,v,mapping,f['source_factor'];break
        if candidate is None:break
        u,v,h,fi=candidate;inv={b:a for a,b in h.items()}
        alias_witnesses.append({'kept':u,'removed':v,'mapping':dict(h),'source_factor':fi})
        stats['aliases']+=1
        for d in dec:
            if d['representative']==v:
                d['representative']=u
                d['map']={a:inv[s] for a,s in d['map'].items() if s in inv}
        rewritten=[]
        for f in factors:
            scope=f['scope']
            if v not in scope:rewritten.append(f);continue
            new_scope=tuple(dict.fromkeys(u if w==v else w for w in scope))
            vp=scope.index(v);up=scope.index(u) if u in scope else None;data={}
            for a,w in f['data'].items():
                check();stats['alias_rows_visited']+=1
                if a[vp] not in inv:continue
                us=inv[a[vp]]
                if up is not None and a[up]!=us:continue
                assignment=dict(zip(scope,a));assignment[u]=us
                key=tuple(assignment[z] for z in new_scope)
                assert key not in data
                data[key]=w
            if not data:return zero('bijection substitution proves contradictory support')
            rewritten.append({'scope':new_scope,'data':data,'source_factor':f['source_factor']})
        factors=rewritten;del domains[v]
    active=sorted(v for v,D in domains.items() if len(D)>1)
    ids={v:i for i,v in enumerate(active)};states={v:sorted(domains[v]) for v in domains}
    inverse={v:{a:i for i,a in enumerate(states[v])} for v in active}
    out_factors=[]
    for f in factors:
        check(True);scope=f['scope'];values=[]
        for a in product(*(states[v] for v in scope)):
            check();stats['dense_entries_materialized']+=1
            values.append(f['data'].get(a,Fraction(0)))
        out_factors.append({'scope':tuple(ids[v] for v in scope),'values':values})
    decoder=[]
    for old,d in enumerate(dec):
        v=d['representative']
        if v in ids:
            decoder.append({'kind':'alias','variable':ids[v],
                'state_map':[inverse[v].get(d['map'].get(a)) for a in range(cards[old])]})
        else:
            fixed=next(iter(domains[v]));orig=[a for a,s in d['map'].items() if s==fixed]
            assert len(orig)==1
            decoder.append({'kind':'fixed','state':orig[0],'cardinality':cards[old]})
    stats['forced_original_variables_beyond_evidence']=sum(d['kind']=='fixed' and v not in evidence for v,d in enumerate(decoder))
    stats['remaining_variables']=len(active);stats['elapsed_s']=time.monotonic()-start
    return {'status':'REDUCED','model':{'cards':[len(states[v]) for v in active],
             'factors':out_factors,'evidence':{}},'decoder':decoder,'stats':stats,
            'certificate':{'state_removals':state_witnesses,'aliases':alias_witnesses,
                'positive_scalar_rule':'positive source-dependent constants cancel in normalized queries'}}


def lift(reduction_result, intervals, points):
    if reduction_result['status']!='REDUCED':raise ValueError('no posterior for zero evidence')
    out_i=[];out_p=[]
    for d in reduction_result['decoder']:
        if d['kind']=='fixed':
            row=[Fraction(int(a==d['state'])) for a in range(d['cardinality'])]
            out_p.append(row);out_i.append([(x,x) for x in row])
        else:
            v=d['variable'];mapping=d['state_map']
            out_p.append([Fraction(0) if s is None else points[v][s] for s in mapping])
            out_i.append([(Fraction(0),Fraction(0)) if s is None else intervals[v][s] for s in mapping])
    return out_i,out_p
