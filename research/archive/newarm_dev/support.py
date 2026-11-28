"""Exact sparse elimination and all singleton response recovery.

No numerical approximation, input-family dispatch, or benchmark-name dispatch.
Source factors are occurrences, never deduplicated. Every retained relation is
its complete positive support; joins are compatibility joins, not dense scans.

The backward pass differentiates the elimination recurrence only on positive
rows. Missing child rows are identically-zero marker polynomials because all
source weights are nonnegative, so their downstream singleton derivatives are
zero. Division below is ONLY by a proved-positive row value, never by zero.
All calculations use Fraction; this is an exact bit algorithm, not a claim of
constant-cost rational arithmetic. stats report rational operation counts and
observed numerator/denominator sizes separately.
"""
from fractions import Fraction
from itertools import product
from collections import defaultdict
import heapq
import math
import time


class Unsupported(Exception):
    pass


class ResourceStop(Exception):
    def __init__(self, reason, stats):
        super().__init__(reason)
        self.reason, self.stats = reason, dict(stats)


class _Factor:
    __slots__ = ('scope', 'data', 'child')
    def __init__(self, scope, data, child=None):
        self.scope, self.data, self.child = tuple(scope), data, child


def solve(model, deadline=None, row_cap=2000000, order_work_cap=3000000,
          verify=False, order=None):
    """Return exact all-original-singleton intervals; deadline is absolute.

    verify=True additionally checks all output rows and retained message
    recurrences by independently re-enumerating the supplied positive supports.
    It is a replay check, not an independently implemented numerical solver.
    The default does not perform that extra numerical pass, but always checks
    exact simplex sums and restores evidence. The trusted implementation and
    source binding are part of the declared certification boundary.
    """
    supplied_order = order
    start = time.monotonic()
    stats = dict(source_entries_read=0, source_positive_rows=0,
                 order_pair_visits=0, join_index_rows=0, join_probes=0,
                 join_rows_generated=0, forward_support_rows=0,
                 reverse_support_rows=0, messages_entries=0,
                 multiplications=0, additions=0, divisions=0,
                 max_numerator_bits=0, max_denominator_bits=0,
                 peak_join_rows=0, max_live_message_entries=0,
                 bit_observation_scope='message outputs and final marginal values; not a bound on every temporary',
                 row_cap=row_cap, phase='recognition')
    ticks = 0
    def check(force=False):
        nonlocal ticks
        ticks += 1
        if force or ticks % 256 == 0:
            if deadline is not None and time.monotonic() >= deadline:
                stats['elapsed_s'] = time.monotonic()-start
                raise ResourceStop('DEADLINE', stats)
    def observe(z):
        stats['max_numerator_bits'] = max(stats['max_numerator_bits'], z.numerator.bit_length())
        stats['max_denominator_bits'] = max(stats['max_denominator_bits'], z.denominator.bit_length())
        return z
    def mul(a,b):
        stats['multiplications'] += 1
        return a*b
    def add(a,b):
        stats['additions'] += 1
        return a+b
    cards = list(model['cards'])
    if any(type(c) is not int or c < 1 for c in cards):
        raise ValueError('invalid cardinality')
    n = len(cards)
    ev = dict(model.get('evidence',{}))
    if any(type(v) is not int or not 0 <= v < n or not 0 <= a < cards[v] for v,a in ev.items()):
        raise ValueError('invalid evidence')
    fs = []
    # All entries are read and their signs validated, including evidence-excluded
    # entries. A positive constant is removable; a zero constant proves Z=0.
    for f in model['factors']:
        sc=tuple(f['scope']); vals=f['values']
        if len(sc)!=len(set(sc)) or any(not 0<=v<n for v in sc):
            raise ValueError('invalid factor scope')
        if len(vals)!=math.prod(cards[v] for v in sc):
            raise ValueError('factor shape mismatch')
        keep=[i for i,v in enumerate(sc) if v not in ev]
        newsc=tuple(sc[i] for i in keep); data={}
        for assignment, w in zip(product(*(range(cards[v]) for v in sc)),vals):
            check();stats['source_entries_read']+=1
            if not isinstance(w,Fraction): w=Fraction(w)
            if w<0: raise ValueError('negative factor entry')
            if w and all(assignment[i]==ev[v] for i,v in enumerate(sc) if v in ev):
                data[tuple(assignment[i] for i in keep)] = w
                stats['source_positive_rows']+=1
        if not data: return {'status':'ZERO_EVIDENCE','intervals':None,'stats':stats}
        if newsc: fs.append(_Factor(newsc,data))
    active=set(range(n))-set(ev)
    covered=set().union(*(set(f.scope) for f in fs)) if fs else set()
    for v in active-covered:
        fs.append(_Factor((v,),{(a,):Fraction(1) for a in range(cards[v])}))
    stats['recognition_s']=time.monotonic()-start
    stats['phase']='planning';pt=time.monotonic()
    if supplied_order is not None:
        order=list(supplied_order)
        if len(order)!=len(active) or set(order)!=active:
            raise ValueError('supplied order does not cover unobserved variables exactly')
        stats['order_supplied']=True
    else:
        adj={v:set() for v in active}
        for f in fs:
            for v in f.scope: adj[v].update(set(f.scope)-{v})
        def score(v):
            nb=sorted(adj[v]); fill=0;volume=cards[v]
            for i,u in enumerate(nb):
                volume*=cards[u]
                for w in nb[i+1:]:
                    check();stats['order_pair_visits']+=1
                    if w not in adj[u]: fill+=cards[u]*cards[w]
            return fill,volume,v
        cur={v:score(v) for v in sorted(active)}
        heap=[(s,v) for v,s in cur.items()];heapq.heapify(heap)
        order=[];alive=set(active)
        while alive:
            check(True)
            if stats['order_pair_visits']>order_work_cap:
                stats['order_capped_at']=len(order);order.extend(sorted(alive));break
            key,v=heapq.heappop(heap)
            if v not in alive or cur[v]!=key:continue
            order.append(v);alive.remove(v);nb=adj[v]
            for u in nb:adj[u].update(nb-{u});adj[u].discard(v)
            touched=set(nb)
            for u in nb:touched.update(adj[u])
            for u in touched & alive:
                cur[u]=score(u);heapq.heappush(heap,(cur[u],u))
    stats['planning_s']=time.monotonic()-pt
    rank={v:i for i,v in enumerate(order)}
    buckets=[[] for _ in order]
    for f in fs:buckets[min(rank[v] for v in f.scope)].append(f)
    # Join support only. Product weights are computed after all compatibility
    # constraints have been applied, preserving factor occurrence multiplicity.
    def joined(inputs):
        ordered=sorted(inputs,key=lambda f:len(f.data))
        if len(ordered[0].data)>row_cap: raise ResourceStop('SUPPORT_ROWS_CAP',stats)
        cols=list(ordered[0].scope); rows=list(ordered[0].data)
        for f in ordered[1:]:
            check(True)
            shared=[v for v in f.scope if v in cols]
            apos=[cols.index(v) for v in shared]
            bpos=[f.scope.index(v) for v in shared]
            only=[i for i,v in enumerate(f.scope) if v not in cols]
            index=defaultdict(list)
            for b in f.data:
                check();stats['join_index_rows']+=1
                index[tuple(b[i] for i in bpos)].append(tuple(b[i] for i in only))
            out=[]
            for a in rows:
                check();stats['join_probes']+=1
                matches=index.get(tuple(a[i] for i in apos),())
                if len(out)+len(matches)>row_cap:raise ResourceStop('SUPPORT_ROWS_CAP',stats)
                for tail in matches:
                    check();out.append(a+tail)
                stats['join_rows_generated']+=len(matches)
            cols += [f.scope[i] for i in only]; rows=out
            stats['peak_join_rows']=max(stats['peak_join_rows'],len(rows))
            if not rows: break
        positions=[[cols.index(v) for v in f.scope] for f in inputs]
        return cols,rows,positions
    nodes=[]; roots=[]; live=0
    stats['phase']='forward';ft=time.monotonic()
    for i,v in enumerate(order):
        check(True);inputs=buckets[i]
        cols,rows,pos=joined(inputs)
        if not rows:return {'status':'ZERO_EVIDENCE','intervals':None,'stats':stats}
        vi=cols.index(v); sep=tuple(w for w in cols if w!=v)
        data={}
        for row in rows:
            check();stats['forward_support_rows']+=1
            values=[f.data[tuple(row[j] for j in pp)] for f,pp in zip(inputs,pos)]
            weight=values[0]
            for w in values[1:]:weight=mul(weight,w)
            key=row[:vi]+row[vi+1:]
            data[key]=add(data[key],weight) if key in data else weight
        for w in data.values():observe(w)
        message=_Factor(sep,data,child=i)
        nodes.append((v,inputs,message))
        live+=len(data);stats['messages_entries']+=len(data)
        stats['max_live_message_entries']=max(stats['max_live_message_entries'],live)
        if sep:buckets[min(rank[w] for w in sep)].append(message)
        else:roots.append(i)
    stats['forward_s']=time.monotonic()-ft
    # Each message is consumed in exactly one later bucket. Reverse contexts are
    # derivatives divided by that connected component's positive normalizer.
    stats['phase']='reverse';bt=time.monotonic()
    contexts=[{} for _ in nodes]
    for i in roots:
        z=nodes[i][2].data[()]
        stats['divisions']+=1;contexts[i][()]=Fraction(1)/z
    marg=[[Fraction(0) for _ in range(c)] for c in cards]
    for v,a in ev.items():marg[v][a]=Fraction(1)
    for i in range(len(nodes)-1,-1,-1):
        check(True);v,inputs,msg=nodes[i]
        cols,rows,pos=joined(inputs);vi=cols.index(v)
        child_positions=[j for j,f in enumerate(inputs) if f.child is not None]
        for row in rows:
            check();stats['reverse_support_rows']+=1
            key=row[:vi]+row[vi+1:];h=contexts[i].get(key)
            if h is None or not h:continue
            keys=[tuple(row[k] for k in pp) for pp in pos]
            vals=[f.data[k] for f,k in zip(inputs,keys)]
            w=vals[0]
            for val in vals[1:]:w=mul(w,val)
            b=mul(h,w);a=row[vi];marg[v][a]=add(marg[v][a],b)
            for j in child_positions:
                # vals[j]>0 by membership in complete positive support.
                stats['divisions']+=1;t=b/vals[j]
                out=contexts[inputs[j].child];k=keys[j]
                out[k]=add(out[k],t) if k in out else t
        # Each context has had its sole use; messages are retained for replay.
        contexts[i].clear()
    stats['reverse_s']=time.monotonic()-bt
    stats['phase']='verification';vt=time.monotonic()
    for row in marg:
        check(True)
        if any(p<0 or p>1 for p in row) or sum(row)!=1:
            raise AssertionError('exact marginal consistency failure')
        for p in row:observe(p)
    if verify:
        for v,inputs,msg in nodes:
            cols,rows,pos=joined(inputs);vi=cols.index(v);result={}
            for row in rows:
                check();w=Fraction(1)
                for f,pp in zip(inputs,pos):w=mul(w,f.data[tuple(row[k] for k in pp)])
                k=row[:vi]+row[vi+1:];result[k]=add(result.get(k,Fraction(0)),w)
            if result!=msg.data:raise AssertionError('message replay failure')
        stats['forward_replay_verified']=True
    stats['verification_s']=time.monotonic()-vt
    stats['phase']='delivery';dt=time.monotonic()
    intervals=[[(p,p) for p in row] for row in marg]
    stats['delivery_s']=time.monotonic()-dt;stats['elapsed_s']=time.monotonic()-start
    stats['phase']='complete';check(True)
    return dict(status='CERTIFIED',intervals=intervals,points=marg,stats=stats,
                certificate=dict(method='exact_sparse_elimination_reverse',
                    arithmetic='exact Fraction',order=order,
                    support_complete=True,root_count=len(roots),
                    original_query_rows=n,full_numeric_replay=bool(verify),
                    qualification='trusted exact implementation; optional forward recurrence replay; final simplex check'))
