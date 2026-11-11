"""Generic scopes-only candidate construction; prices are scalar forecasts."""
import math,heapq,time

def order_and_price(model, deadline=None):
    cards=model['cards'];n=len(cards);adj={v:set() for v in range(n)};visits=0;t=time.monotonic()
    for f in model['factors']:
        for v in f['scope']:adj[v].update(set(f['scope'])-{v})
    def score(v):
        nonlocal visits
        if deadline is not None and time.monotonic()>=deadline:raise TimeoutError('order scoring deadline')
        nb=sorted(adj[v]);fill=0;volume=cards[v]
        for i,u in enumerate(nb):
            volume*=cards[u]
            for w in nb[i+1:]:
                visits+=1
                if visits%4096==0 and deadline is not None and time.monotonic()>=deadline:raise TimeoutError('order scoring deadline')
                if w not in adj[u]:fill+=cards[u]*cards[w]
        return fill,volume,v
    cur={v:score(v) for v in adj};heap=[(s,v) for v,s in cur.items()];heapq.heapify(heap);alive=set(adj);order=[];capped=False
    while alive:
        if deadline and time.monotonic()>deadline:capped=True;order.extend(sorted(alive));break
        key,v=heapq.heappop(heap)
        if v not in alive or cur[v]!=key:continue
        alive.remove(v);order.append(v);nb=adj[v]
        for u in nb:adj[u].update(nb-{u});adj[u].discard(v)
        touched=set(nb)
        for u in nb:touched.update(adj[u])
        for u in touched&alive:cur[u]=score(u);heapq.heappush(heap,(cur[u],u))
    return order,dict(order_pair_visits=visits,order_capped=capped,planning_s=time.monotonic()-t,**price(model,order,deadline=deadline))

def price(model,order,deadline=None):
    cards=model['cards'];fs=[set(f['scope']) for f in model['factors'] if f['scope']];ops=0;peak=0;rows=0
    for v in order:
        if deadline is not None and time.monotonic()>=deadline:raise TimeoutError('order price deadline')
        hit=[s for s in fs if v in s];bag=set().union(*hit) if hit else {v};vol=math.prod(cards[u] for u in bag)
        # One marker per variable; forward + conservative constant-factor reverse.
        ops+=max(1,len(hit))*vol+(vol-vol//cards[v]);rows+=vol;peak=max(peak,vol)
        fs=[s for s in fs if v not in s]+[bag-{v}]
    return dict(scalar_forecast=5*ops+sum(cards),dense_bag_rows=rows,peak_bag=peak)
