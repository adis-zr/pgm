"""Structural response construction with deterministic enclosures.

The forest constructor has a scoped matched family theorem. The general
candidate selection is heuristic and makes no intrinsic-optimality claim.
"""
from fractions import Fraction as F
from itertools import product
from pathlib import Path
import hashlib, math, time

def read_uai(path):
    raw=Path(path).read_bytes(); epath=Path(str(path)+'.evid')
    eb=epath.read_bytes() if epath.exists() else b'0'
    ts=iter(raw.decode().split()); kind=next(ts); assert kind in ('MARKOV','BAYES')
    n=int(next(ts)); cards=[int(next(ts)) for _ in range(n)]; assert all(d>0 for d in cards)
    scopes=[tuple(int(next(ts)) for _ in range(int(next(ts)))) for _ in range(int(next(ts)))]
    factors=[]
    for s in scopes:
        assert len(s)==len(set(s)) and all(0<=v<n for v in s)
        k=int(next(ts)); assert k==math.prod(cards[v] for v in s)
        vs=[F(next(ts)) for _ in range(k)]; assert all(v>=0 for v in vs)
        factors.append(dict(scope=s,values=vs))
    assert next(ts,None) is None
    es=iter(map(int,eb.split())); k=next(es); evidence={}
    for _ in range(k):
        v,a=next(es),next(es);assert 0<=v<n and 0<=a<cards[v] and v not in evidence;evidence[v]=a
    assert next(es,None) is None
    return dict(cards=cards,factors=factors,evidence=evidence),dict(model_sha256=hashlib.sha256(raw).hexdigest(),evidence_sha256=hashlib.sha256(eb).hexdigest())

def components(model, deadline=None):
    """Evidence restriction, positive scalar cancellation, exact component split."""
    cards=model['cards'];ev=model.get('evidence',{}); factors=[];free=set(range(len(cards)))-set(ev)
    adj={v:set() for v in free}
    for f in model['factors']:
        if deadline is not None and time.monotonic()>=deadline:raise TimeoutError('component restriction deadline')
        s=f['scope'];ns=tuple(v for v in s if v not in ev);vs=[]
        for xs,w in zip(product(*(range(cards[v]) for v in s)),f['values']):
            if all(v not in ev or ev[v]==x for v,x in zip(s,xs)):vs.append(w)
        if not ns:
            if vs[0]==0:raise ValueError('ZERO_EVIDENCE')
            continue
        factors.append(dict(scope=ns,values=vs))
        for v in ns:adj[v].update(set(ns)-{v})
    out=[]
    while free:
        if deadline is not None and time.monotonic()>=deadline:raise TimeoutError('component split deadline')
        todo=[min(free)];seen=set(todo);free-=seen
        while todo:
            for w in adj[todo.pop()]-seen:seen.add(w);free.discard(w);todo.append(w)
        old=sorted(seen);mapping={v:i for i,v in enumerate(old)}
        fs=[dict(scope=tuple(mapping[v] for v in f['scope']),values=f['values']) for f in factors if f['scope'][0] in seen]
        out.append((old,dict(cards=[cards[v] for v in old],factors=fs,evidence={})))
    return out

def brute_force(model):
    cards=model['cards'];out=[[F(0) for _ in range(d)] for d in cards];z=F(0)
    for x in product(*(range(d) for d in cards)):
        if any(x[v]!=a for v,a in model.get('evidence',{}).items()):continue
        w=F(1)
        for f in model['factors']:
            i=0
            for v in f['scope']:i=i*cards[v]+x[v]
            w*=f['values'][i]
        z+=w
        for v,a in enumerate(x):out[v][a]+=w
    if not z:raise ValueError('ZERO_EVIDENCE')
    return [[a/z for a in row] for row in out]

def verify_output(intervals, points, epsilon=F(1,200)):
    assert len(intervals)==len(points)
    for row,p in zip(intervals,points):
        assert len(row)==len(p) and sum(p)==1
        for (lo,hi),q in zip(row,p):
            assert 0<=lo<=hi<=1 and hi-lo<=2*epsilon
            assert lo<=q<=hi and max(abs(q-lo),abs(q-hi))<=epsilon
    return True

def _dag_forecast(stats):
    return sum(stats.get(k,0) for k in ('scalar_ops_predicted','normalization_adds','normalization_divisions','additive_recognition_subtractions','additive_recognition_additions'))

def _discover_component(m, deadline, route='auto', inherited_dag=None):
    import dag,planning,geometry
    from collections import deque
    t=time.monotonic();discovery=[];candidates=[];dp=inherited_dag
    allowance=lambda: min(deadline if deadline is not None else float('inf'),time.monotonic()+2)
    try:order,ostats=planning.order_and_price(m,deadline=allowance())
    except TimeoutError:
        # A cheap complete valid order remains available after an optional search.
        order=list(range(len(m['cards'])));vol=math.prod(m['cards'])
        ostats=dict(scalar_forecast=5*(len(m['factors'])+len(order)+1)*max(1,len(order))*vol,
                    order_capped=True,forecast_kind='coarse full-product upper forecast after planning timeout')
    geo=geometry.discover(m,deadline=allowance())
    if geo:
        try:
            gp=planning.price(m,geo['order'],deadline=allowance())
            if gp['scalar_forecast']<ostats['scalar_forecast']:order=geo['order'];ostats.update(gp)
            discovery.append(dict(kind='geometry',stats=geo['stats']))
        except TimeoutError:discovery.append(dict(kind='geometry',declined='pricing deadline'))
    candidates.append((ostats['scalar_forecast'],'support'))
    discovery.append(dict(kind='support',stats=ostats))
    if route in ('auto','dag'):
        try:
            if dp is None:dp=dag.plan(m,deadline=allowance())
            ds=dp['stats'];cost=_dag_forecast(ds)
            candidates.append((cost,'dag'));discovery.append(dict(kind='dag',stats=ds,reused=inherited_dag is not None))
        except (ValueError,TimeoutError) as e:discovery.append(dict(kind='dag',declined=str(e)))
    g={v:set() for v in range(len(m['cards']))};valid=all(d==2 for d in m['cards'])
    for f in m['factors']:
        if len(f['scope'])>2:valid=False;break
        if len(f['scope'])==2:a,b=f['scope'];g[a].add(b);g[b].add(a)
    color={}
    if valid:
        for a in g:
            if a in color:continue
            color[a]=0;q=deque([a])
            while q:
                v=q.popleft()
                for w in g[v]:
                    if w not in color:color[w]=1-color[v];q.append(w)
                    elif color[w]==color[v]:valid=False
    if valid:
        size=min(sum(c==0 for c in color.values()),sum(c==1 for c in color.values()))
        cost=(1<<size)*(8*len(g)+4)+sum(len(f['values']) for f in m['factors'])
        candidates.append((cost,'stream'));discovery.append(dict(kind='stream',conditioned_variables=size,scalar_forecast=cost))
    chosen=min(candidates)[1] if route=='auto' else route
    if chosen=='dag' and dp is None:raise ValueError('requested DAG route unavailable')
    cost=next((c for c,k in candidates if k==chosen),float('inf'))
    discovery.append(dict(candidate_selection='minimum scalar forecast; not a bit-work or global optimum',candidates=candidates,planning_wall_s=time.monotonic()-t))
    return dict(model=m,kind=chosen,forecast=cost,dag=dp,order=order,discovery=discovery)

def _execute_component(plan,deadline):
    import dag,support,stream,stream_float
    if plan['kind']=='dag':return dag.execute_plan(plan['dag'],deadline=deadline)
    if plan['kind']=='support':return support.solve(plan['model'],deadline=deadline,order=plan['order'])
    ft=time.monotonic()
    try:return stream_float.solve(plan['model'],deadline=deadline)
    except stream_float.RangeError as e:
        plan['discovery'].append(dict(kind='binary64_attempt',status='range_refusal',wall_s=time.monotonic()-ft,reason=str(e),stats=getattr(e,'stats',None)))
        return stream.solve(plan['model'],deadline=deadline)

def solve(model, deadline=None, route='auto'):
    trace={'phase':'entry','completed_components':[],'component_plans':[]}
    try:return _solve(model,deadline,route,trace)
    except Exception as e:
        e.stats={'core_trace':trace,'last_attempt':getattr(e,'stats',None)}
        raise

def _solve(model, deadline, route, trace):
    import dag,reduction
    t=time.monotonic()
    def check(stage):
        if deadline is not None and time.monotonic()>=deadline:raise TimeoutError(stage+' deadline')
    check('entry');cards=model['cards']
    if any(type(d) is not int or d<1 for d in cards):raise ValueError('invalid cardinality')
    for f in model['factors']:
        check('source validation');s=f['scope']
        if len(s)!=len(set(s)) or any(type(v) is not int or not 0<=v<len(cards) for v in s):raise ValueError('invalid scope')
        if len(f['values'])!=math.prod(cards[v] for v in s) or any(w<0 for w in f['values']):raise ValueError('invalid source values')
    if any(type(v) is not int or not 0<=v<len(cards) or type(a) is not int or not 0<=a<cards[v] for v,a in model.get('evidence',{}).items()):raise ValueError('invalid evidence')
    original_cards=list(cards);raw_plan=None;root_discovery=[]
    if route=='auto':
        import forest
        ft=time.monotonic();trace['phase']='forest discovery and execution'
        try:
            result=forest.solve(model,deadline=deadline,independent_replay=True)
            verify_output(result['intervals'],result['points']);check('forest publication')
            return dict(intervals=result['intervals'],points=result['points'],stats=dict(reduction={'not_attempted':'complete forest computation'},total_s=time.monotonic()-t,root_discovery=[dict(kind='forest',wall_s=time.monotonic()-ft)],components=[dict(variables=list(range(len(cards))),route='forest',discovery=[dict(kind='forest',recognition=result['stats']['recognition'])],stats=result['stats'],certificate=result['certificate'])]),decoder=[dict(kind='identity',variable=v) for v in range(len(cards))],necessity=dict(explicit_output_fields=sum(cards),scope='Omega(K) explicit output writes; matched Theta(n) only for Theorem 4 fixed-domain/fixed-tolerance/word-input forest family',intrinsic_optimality='MATCHED_IN_THEOREM_4_SCOPE_ONLY'),status='EXACT_OR_ENCLOSED_PROTOTYPE')
        except forest.UnsupportedError as e:root_discovery.append(dict(kind='forest',declined=str(e),wall_s=time.monotonic()-ft,stats=getattr(e,'stats',None)))
        except forest.ZeroEvidence:raise ValueError('ZERO_EVIDENCE')
    trace['root_discovery']=root_discovery;trace['phase']='identity planning'
    # Retain the identity representation: a sound reduction can hide structure.
    if route in ('auto','dag'):
        rt=time.monotonic()
        try:
            raw_plan=dag.plan(model,deadline=min(deadline if deadline is not None else float('inf'),time.monotonic()+2))
            rs=raw_plan['stats'];raw_cost=_dag_forecast(rs)
            root_discovery.append(dict(kind='identity_source_dag',scalar_forecast=raw_cost,wall_s=time.monotonic()-rt))
        except (ValueError,TimeoutError) as e:root_discovery.append(dict(kind='identity_source_dag',declined=str(e),wall_s=time.monotonic()-rt))
    if raw_plan is not None and route=='dag':
        result=dag.execute_plan(raw_plan,deadline=deadline);verify_output(result['intervals'],result['points']);check('forced DAG publication')
        return dict(intervals=result['intervals'],points=result['points'],stats=dict(reduction={'not_attempted':'forced valid identity DAG'},total_s=time.monotonic()-t,root_discovery=root_discovery,components=[dict(variables=list(range(len(cards))),route='dag',discovery=root_discovery,stats=result['stats'],certificate=result['certificate'])]),decoder=[dict(kind='identity',variable=v) for v in range(len(cards))],necessity=dict(explicit_output_fields=sum(cards),intrinsic_optimality='OPEN'),status='EXACT_OR_ENCLOSED_PROTOTYPE')
    trace['phase']='reduction';reduced=reduction.reduce(model,deadline=deadline)
    trace['reduction']=reduced['stats']
    if reduced.get('status')=='ZERO_EVIDENCE':raise ValueError('ZERO_EVIDENCE')
    rm=reduced['model'];split=components(rm,deadline=deadline);split_s=time.monotonic()-t
    check('source');planned=[]
    unchanged=(len(rm['cards'])==len(cards) and not model.get('evidence') and
               not any(reduced['stats'].get(k,0) for k in ('aliases','states_removed','scalar_factors_cancelled')))
    for old,m in split:
        trace['phase']='component planning';check('component planning')
        inherited=raw_plan if unchanged and len(split)==1 and old==list(range(len(cards))) else None
        planned.append((old,_discover_component(m,deadline,route,inherited)))
        p=planned[-1][1]
        trace['component_plans'].append(dict(variables=len(old),route=p['kind'],forecast=p['forecast'],discovery=p['discovery']))
    reduced_cost=sum(p['forecast'] for _,p in planned)
    use_raw=raw_plan is not None and (route=='dag' or raw_cost<=reduced_cost)
    root_discovery.append(dict(kind='representation_selection',chosen='identity_source_dag' if use_raw else 'reduced_components',identity_forecast=raw_cost if raw_plan is not None else None,reduced_forecast=reduced_cost,selection_scope='heuristic scalar forecast; all discovery charged'))
    records=[]
    trace['phase']='execution'
    if use_raw:
        result=dag.execute_plan(raw_plan,deadline=deadline);intervals=result['intervals'];points=result['points']
        records.append(dict(variables=list(range(len(cards))),route='dag',discovery=root_discovery,stats=result['stats'],certificate=result['certificate']))
        trace['completed_components'].append(dict(route='dag',variables=len(cards),stats=result['stats']))
        decoder=[dict(kind='identity',variable=v) for v in range(len(cards))]
    else:
        intervals=[None]*len(rm['cards']);points=[None]*len(intervals)
        for old,p in planned:
            check('component execution');ct=time.monotonic();result=_execute_component(p,deadline)
            if result.get('status')=='ZERO_EVIDENCE':raise ValueError('ZERO_EVIDENCE')
            rows=result['intervals'];ps=result.get('points')
            if ps is None:ps=[[(lo+hi)/2 for lo,hi in row] for row in rows]
            assert len(rows)==len(old) and len(ps)==len(old)
            for v,row,q in zip(old,rows,ps):intervals[v]=row;points[v]=q
            records.append(dict(variables=old,route=p['kind'],discovery=p['discovery'],execution_wall_s=time.monotonic()-ct,stats=result.get('stats'),certificate=result.get('certificate')))
            trace['completed_components'].append(dict(route=p['kind'],variables=len(old),stats=result.get('stats')))
        assert len(intervals)==len(rm['cards']) and all(len(row)==d for row,d in zip(intervals,rm['cards']))
        verify_output(intervals,points)
        intervals,points=reduction.lift(reduced,intervals,points);decoder=reduced['decoder']
    assert len(intervals)==len(original_cards) and all(len(row)==d for row,d in zip(intervals,original_cards))
    verify_output(intervals,points);check('publication')
    return dict(intervals=intervals,points=points,stats=dict(reduction=reduced['stats'],split_s=split_s,total_s=time.monotonic()-t,components=records,root_discovery=root_discovery),decoder=decoder,reduction_certificate=reduced.get('certificate'),necessity=dict(explicit_output_fields=sum(original_cards),scope='Omega(K) writes for the explicit original singleton output; not a numerical time lower bound',intrinsic_optimality='OPEN'),status='EXACT_OR_ENCLOSED_PROTOTYPE')

def publish(intervals, points, digits=8):
    """Outward decimal endpoints and exact grid simplex points."""
    scale=10**digits;out=[];ps=[]
    def fmt(x):return str(x//scale)+'.'+str(x%scale).zfill(digits)
    for row,p in zip(intervals,points):
        base=[(x*scale).numerator//(x*scale).denominator for x in p]
        residual=scale-sum(base);assert 0<=residual<=len(p)
        ids=sorted(range(len(p)),key=lambda i:p[i]*scale-base[i],reverse=True)
        for i in ids[:residual]:base[i]+=1
        ps.append([fmt(x) for x in base]);rr=[]
        for lo,hi in row:
            a=lo*scale;b=hi*scale
            rr.append([fmt(a.numerator//a.denominator),fmt(-(-b.numerator//b.denominator))])
        out.append(rr)
    verify_output([[(F(a),F(b)) for a,b in row] for row in out],[[F(x) for x in row] for row in ps])
    return out,ps
