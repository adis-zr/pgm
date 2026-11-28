"""Certified all-singleton inference on pairwise forests, including discovery.

Source tables are converted directly to directed scaled dyadics; parallel factors
are merged there, never as growing exact rational message products. Nonzero
numbers have a p-bit integer significand and an unbounded integer exponent.
A structural error-label pass chooses p before numerical evaluation. Both
message directions use zero-safe products excluding one neighbor. Publication
rounds directly to a small dyadic grid and constructs exact simplex points.

Under bounded domains/factor arity, O(n) occurrences, O(log n)-bit source words,
and the unit-cost O(log(n/eps))-bit word RAM specified in THEORY.md theorem 4,
all passes, including independent traversal replay, use O(n) word operations.
Python timings are not a proof of that word-RAM bound. Arbitrary input bits,
actual integer arithmetic, hashing and caller parsing have their actual costs.
Replay rereads source structure and uses a different rooting/traversal; it shares
this qualified scaled arithmetic implementation (not implementation diversity).
"""
from fractions import Fraction as F
from math import prod
from dataclasses import dataclass
import time

class UnsupportedError(ValueError):
    def __init__(self,message,stats=None):self.stats=stats or {};super().__init__(message)
class ZeroEvidence(ValueError):
    def __init__(self,message,stats=None):self.stats=stats or {};super().__init__(message)
class DeadlineExceeded(TimeoutError):
    def __init__(self,stats):
        self.stats=stats;super().__init__('forest deadline exceeded')

def _tick(deadline,stats):
    if deadline is not None and time.monotonic()>=deadline:raise DeadlineExceeded(dict(stats))

def _ceil_log2_ratio(n,d):
    k=max(0,n.bit_length()-d.bit_length())
    if n>d<<k:k+=1
    return k

@dataclass(frozen=True)
class D:
    m:int
    e:int
@dataclass(frozen=True)
class I:
    lo:D
    hi:D
    E:int

class Arithmetic:
    def __init__(self,p,deadline=None,dry=False):
        self.p=p;self.deadline=deadline;self.dry=dry
        self.stats={'precision_bits':p,'source_conversions':0,'adds':0,'mults':0,
                    'divisions':0,'rounds':0,'large_gap_additions':0,
                    'max_mantissa_bits':0,'max_temporary_bits':0,
                    'max_exponent_bits':0,'max_abs_exponent':0,'instrumented_integer_bits':0,
                    'integer_multiplications':0,'integer_divmods':0,'integer_additions':0}
        self.z=D(0,0);self.o=D(1<<(p-1),1-p)
        self.zero=I(self.z,self.z,0);self.one=I(self.o,self.o,0)
    def _op(self,name):
        self.stats[name]+=1
        if (sum(self.stats[k] for k in ('source_conversions','adds','mults','divisions'))&255)==0:
            _tick(self.deadline,self.stats)
    def _record(self,m,e,temp=False):
        b=m.bit_length();self.stats['instrumented_integer_bits']+=b+abs(e).bit_length()
        self.stats['max_temporary_bits' if temp else 'max_mantissa_bits']=max(
            self.stats['max_temporary_bits' if temp else 'max_mantissa_bits'],b)
        self.stats['max_exponent_bits']=max(self.stats['max_exponent_bits'],abs(e).bit_length())
        self.stats['max_abs_exponent']=max(self.stats['max_abs_exponent'],abs(e))
    def _round(self,m,e,up):
        self.stats['rounds']+=1
        if not m:return self.z
        self._record(m,e,True)
        shift=m.bit_length()-self.p
        if shift>0:
            remainder=m&((1<<shift)-1);m>>=shift;e+=shift
            if up and remainder:m+=1
            if m.bit_length()>self.p:m>>=1;e+=1
        elif shift<0:m<<=-shift;e+=shift
        self._record(m,e)
        return D(m,e)
    def _ratio(self,n,d,e,up):
        if not n:return self.z
        if d<=0:raise ZeroEvidence('nonpositive denominator',self.stats)
        k=n.bit_length()-d.bit_length()
        if (n < (d<<k)) if k>=0 else ((n<<(-k))<d):k-=1
        shift=k-self.p+1
        if shift>=0:an,ad=n,d<<shift
        else:an,ad=n<<(-shift),d
        self._record(an,e,True);self._record(ad,e,True)
        self.stats['integer_divmods']+=1
        q,r=divmod(an,ad)
        return self._round(q+int(up and bool(r)),e+shift,False)
    def source(self,q):
        self._op('source_conversions')
        if self.dry:return I(self.o,self.o,1)
        q=F(q)
        return I(self._ratio(q.numerator,q.denominator,0,False),
                 self._ratio(q.numerator,q.denominator,0,True),1)
    def _add(self,a,b,up):
        if not a.m:return b
        if not b.m:return a
        if a.e<b.e:a,b=b,a
        gap=a.e-b.e;self.stats['integer_additions']+=1
        if gap>self.p+1:
            self.stats['large_gap_additions']+=1
            return self._round(a.m+int(up),a.e,up)
        return self._round((a.m<<gap)+b.m,b.e,up)
    def add(self,a,b):
        self._op('adds');E=max(a.E,b.E)+1
        if self.dry:return I(self.o,self.o,E)
        return I(self._add(a.lo,b.lo,False),self._add(a.hi,b.hi,True),E)
    def mul(self,a,b):
        self._op('mults');E=a.E+b.E+1
        if self.dry:return I(self.o,self.o,E)
        self.stats['integer_multiplications']+=2
        return I(self._round(a.lo.m*b.lo.m,a.lo.e+b.lo.e,False),
                 self._round(a.hi.m*b.hi.m,a.hi.e+b.hi.e,True),E)
    def div(self,a,b):
        # Terminal normalization only: E now bounds reciprocal quotient error;
        # it must not be reused as a source/product/add relative-error label.
        self._op('divisions')
        if not b.lo.m:raise ZeroEvidence('zero component normalizer',self.stats)
        return I(self._ratio(a.lo.m,b.hi.m,a.lo.e-b.hi.e,False),
                 self._ratio(a.hi.m,b.lo.m,a.hi.e-b.lo.e,True),a.E+b.E+1)
    def sum(self,items):
        out=self.zero
        for x in items:out=self.add(out,x)
        return out


def _countsort(rows,key,n):
    counts=[0]*n
    for row in rows:counts[row[key]]+=1
    running=0
    for i,c in enumerate(counts):counts[i],running=running,running+c
    out=[None]*len(rows)
    for row in rows:
        k=row[key];out[counts[k]]=row;counts[k]+=1
    return out


def recognize(model,deadline=None,reverse=False):
    start=time.monotonic();cards=list(model['cards']);n=len(cards);evinput=model.get('evidence',{});ev=[None]*n
    stats={'source_entries_read':0,'source_factor_occurrences':len(model['factors']),
           'scope_incidences':0,'input_numerator_bits':0,'input_denominator_bits':0,
           'radix_items':0,'recognition_s':0.0,'cards_read':n,'evidence_entries_read':len(evinput),
           'sliced_entries':0,'graph_adjacency_visits':0}
    if any(type(c)is not int or c<1 for c in cards):raise ValueError('invalid domain')
    if any(type(v)is not int or not 0<=v<n or type(a)is not int or not 0<=a<cards[v] for v,a in evinput.items()):raise ValueError('invalid evidence')
    for v,a in evinput.items():ev[v]=a
    free=[v for v in range(n) if ev[v] is None];unary=[[] for _ in cards];pairs=[]
    for f in model['factors']:
        _tick(deadline,stats);scope=tuple(f['scope']);values=f['values']
        if len(set(scope))!=len(scope) or any(type(v)is not int or not 0<=v<n for v in scope):raise ValueError('invalid factor scope')
        if len(values)!=prod(cards[v] for v in scope):raise ValueError('invalid factor length')
        stats['scope_incidences']+=len(scope)
        for i,q in enumerate(values):
            if not isinstance(q,(int,F)) or q<0:raise ValueError('nonnegative exact rational source required')
            q=F(q);stats['source_entries_read']+=1
            stats['input_numerator_bits']+=q.numerator.bit_length();stats['input_denominator_bits']+=q.denominator.bit_length()
            if (i&1023)==0:_tick(deadline,stats)
        remain=[v for v in scope if ev[v] is None]
        if len(remain)>2:raise UnsupportedError('evidence-sliced arity exceeds two',stats)
        # At most two free axes. Enumerate their explicitly required sliced table.
        count=prod(cards[v] for v in remain);sliced=[]
        for code in range(count):
            assn={};cur=code
            for v in reversed(remain):assn[v]=cur%cards[v];cur//=cards[v]
            ix=0
            for v in scope:ix=ix*cards[v]+(ev[v] if ev[v] is not None else assn[v])
            sliced.append(values[ix]);stats['sliced_entries']+=1
            if (code&1023)==0:_tick(deadline,stats)
        if not remain:
            if sliced[0]==0:raise ZeroEvidence('zero evidence-sliced scalar',stats)
        elif len(remain)==1:unary[remain[0]].append(sliced)
        else:
            a,b=remain
            if a>b:
                sliced=[sliced[y*cards[b]+x] for x in range(cards[b]) for y in range(cards[a])]
                a,b=b,a
            pairs.append((a,b,sliced))
    pairs=_countsort(_countsort(pairs,1,n),0,n) if pairs else []
    stats['radix_items']=2*len(pairs);edges=[]
    for a,b,vals in pairs:
        if edges and edges[-1][0]==a and edges[-1][1]==b:edges[-1][2].append(vals)
        else:edges.append((a,b,[vals]))
    adj=[[] for _ in cards]
    for j,(a,b,_) in enumerate(edges):adj[a].append((b,j));adj[b].append((a,j))
    parent=[-2]*n;order=[];roots=[]
    for startv in (reversed(free) if reverse else free):
        if parent[startv]!=-2:continue
        roots.append(startv);parent[startv]=None;todo=[startv]
        while todo:
            v=todo.pop();order.append(v)
            for w,j in (reversed(adj[v]) if reverse else adj[v]):
                stats['graph_adjacency_visits']+=1
                if w==parent[v]:continue
                if parent[w]!=-2:raise UnsupportedError('effective simple graph contains a cycle',stats)
                parent[w]=v;todo.append(w)
            _tick(deadline,stats)
    stats.update(free_variables=len(free),simple_edges=len(edges),components=len(roots),recognition_s=time.monotonic()-start)
    return {'cards':cards,'ev':ev,'free':free,'unary':unary,'edges':edges,'adj':adj,'parent':parent,'order':order,'roots':roots,'stats':stats}


def _compute(plan,A):
    cards=plan['cards'];unary=[None]*len(cards);pair=[]
    for v in plan['free']:
        out=[A.one]*cards[v]
        for vals in plan['unary'][v]:out=[A.mul(a,A.source(q)) for a,q in zip(out,vals)]
        unary[v]=out
    for a,b,occurrences in plan['edges']:
        out=[A.one]*(cards[a]*cards[b])
        for vals in occurrences:out=[A.mul(x,A.source(q)) for x,q in zip(out,vals)]
        pair.append(out)
    messages=[None]*(2*len(plan['edges']));parent=plan['parent'];adj=plan['adj']
    def slot(v,j):return 2*j+int(v!=plan['edges'][j][0])
    def contract(v,w,j,base):
        a,b,_=plan['edges'][j];tab=pair[j];out=[]
        for y in range(cards[w]):
            acc=A.zero
            for x in range(cards[v]):
                ix=x*cards[w]+y if v==a else y*cards[v]+x
                acc=A.add(acc,A.mul(base[x],tab[ix]))
            out.append(acc)
        return out
    for v in reversed(plan['order']):
        par=parent[v]
        if par is None:continue
        base=list(unary[v]);edge=None
        for w,j in adj[v]:
            if w==par:edge=j
            else:base=[A.mul(x,y) for x,y in zip(base,messages[slot(w,j)])]
        messages[slot(v,edge)]=contract(v,par,edge,base)
    beliefs=[None]*len(cards)
    for v in plan['order']:
        neighbors=adj[v];degree=len(neighbors);prefix=[list(unary[v])]
        for w,j in neighbors:prefix.append([A.mul(x,y) for x,y in zip(prefix[-1],messages[slot(w,j)])])
        suffix=[[A.one]*cards[v] for _ in range(degree+1)]
        for i in range(degree-1,-1,-1):
            w,j=neighbors[i];suffix[i]=[A.mul(x,y) for x,y in zip(messages[slot(w,j)],suffix[i+1])]
        beliefs[v]=prefix[-1]
        for i,(w,j) in enumerate(neighbors):
            if parent[w]==v:
                base=[A.mul(x,y) for x,y in zip(prefix[i],suffix[i+1])]
                messages[slot(v,j)]=contract(v,w,j,base)
    normalized=[None]*len(cards);K=1
    for v,row in enumerate(beliefs):
        if row is None:continue
        z=A.sum(row)
        K=max(K,max(x.E+z.E+1 for x in row))
        if not A.dry:normalized[v]=[A.div(x,z) for x in row]
    return normalized,K


def _grid(x,k,up):
    if not x.m:return 0
    shift=x.e+k
    if shift>=0:
        if x.m.bit_length()+shift>k+1:return 1<<k  # clip a proven probability upper bound
        return min(1<<k,x.m<<shift)
    shift=-shift
    if shift>=x.m.bit_length():return int(up)
    q,r=divmod(x.m,1<<shift)
    return min(1<<k,q+int(up and bool(r)))

def _publish(rows,plan,k,epsilon,deadline=None,stats=None):
    denom=1<<k;boxes=[];points=[]
    if stats is not None:stats['passes']+=1
    for v,d in enumerate(plan['cards']):
        _tick(deadline,stats or {})
        if stats is not None:stats['coordinates']+=d;stats['grid_endpoint_conversions']+=2*d;stats['simplex_allocations']+=d
        if plan['ev'][v] is not None:
            a=plan['ev'][v];lo=[denom*int(j==a) for j in range(d)];hi=list(lo)
        else:
            lo=[_grid(x.lo,k,False) for x in rows[v]];hi=[_grid(x.hi,k,True) for x in rows[v]]
        if not all(0<=a<=b<=denom and F(b-a,denom)<=epsilon for a,b in zip(lo,hi)):raise AssertionError('publication width or interval invariant')
        left=denom-sum(lo)
        if left<0 or sum(hi)<denom:raise AssertionError('simplex box is infeasible')
        point=list(lo)
        for j in range(d):take=min(left,hi[j]-point[j]);point[j]+=take;left-=take
        if left:raise AssertionError('simplex allocation failed')
        boxes.append([(F(a,denom),F(b,denom)) for a,b in zip(lo,hi)])
        points.append([F(x,denom) for x in point])
    return boxes,points


def _solve_impl(model,deadline,epsilon,independent_replay,charged):
    start=time.monotonic();epsilon=F(epsilon)
    if not 0<epsilon<=1:raise ValueError('epsilon must lie in (0,1]')
    _tick(deadline,{})
    plan=recognize(model,deadline);charged['recognition']=plan['stats']
    reverse=recognize(model,deadline,True) if independent_replay else None
    if reverse is not None:charged['checker_recognition']=reverse['stats']
    labelstart=time.monotonic();labels=Arithmetic(2,deadline,True)
    charged['label_passes']=[labels.stats];_,K=_compute(plan,labels)
    labelstats=[dict(labels.stats)]
    if reverse is not None:
        labels2=Arithmetic(2,deadline,True);charged['label_passes'].append(labels2.stats)
        _,K2=_compute(reverse,labels2);K=max(K,K2);labelstats.append(dict(labels2.stats))
    label_s=time.monotonic()-labelstart
    p=max(8,1+_ceil_log2_ratio(16*K*epsilon.denominator,epsilon.numerator))
    u=F(1,1<<(p-1));assert K*u<=epsilon/16
    dmax=max(plan['cards'],default=1);gridbits=_ceil_log2_ratio(8*dmax*epsilon.denominator,epsilon.numerator)
    publication={'passes':0,'coordinates':0,'grid_endpoint_conversions':0,'simplex_allocations':0,'max_grid_integer_bits':gridbits+1}
    t=time.monotonic();A=Arithmetic(p,deadline);charged['producer']=A.stats;charged['publication']=publication
    rows,actualK=_compute(plan,A)
    assert actualK<=K
    intervals,points=_publish(rows,plan,gridbits,epsilon/2,deadline,publication);producer_s=time.monotonic()-t
    replay_s=0.0;replaystats=None
    if reverse is not None:
        t=time.monotonic();B=Arithmetic(p,deadline);charged['replay']=B.stats
        checked,Kcheck=_compute(reverse,B)
        assert Kcheck<=K
        checker_intervals,_=_publish(checked,reverse,gridbits,epsilon/2,deadline,publication)
        # The separate numerical replay establishes its own enclosure. Publish
        # the union, so every final interval contains that checked enclosure.
        unions=[None]*len(plan['cards'])
        for v in plan['free']:
            row=[]
            for (lo,hi),(clo,chi) in zip(intervals[v],checker_intervals[v]):
                l=min(lo,clo);h=max(hi,chi)
                row.append(I(D(l.numerator,-(l.denominator.bit_length()-1)),
                             D(h.numerator,-(h.denominator.bit_length()-1)),0))
            unions[v]=row
        intervals,points=_publish(unions,plan,gridbits,epsilon,deadline,publication)
        replaystats=B.stats;replay_s=time.monotonic()-t
    stats={'solver':'scaled_dyadic_forest','recognition':plan['stats'],
           'checker_recognition':reverse['stats'] if reverse else None,
           'label_passes':labelstats,'label_s':label_s,'max_normalization_error_label':K,
           'precision_bits':p,'directed_unit_roundoff':str(u),'delta_bound':str(K*u),
           'grid_bits':gridbits,'publication':publication,'producer':A.stats,'replay':replaystats,
           'producer_s':producer_s,'replay_s':replay_s,'elapsed_s':time.monotonic()-start,
           'output_coordinates':sum(plan['cards']),'independent_replay':independent_replay}
    certificate_start=time.monotonic()
    result={'status':'CERTIFIED_INTERVAL','intervals':intervals,'points':points,'stats':stats,
            'certificate':{'arithmetic':'directed p-bit significands with unbounded binary exponents',
              'precision_choice':'two structural label passes; p>=1+ceil(log2(16*K/epsilon))',
              'source_occurrences_consumed':len(model['factors']),'parallel_factors':'radix grouped; multiplied in scaled outward arithmetic',
              'query_recovery':'both directed tree messages; prefix/suffix neighbor exclusions; all original rows',
              'replay':'fresh source validation and opposite-root traversal; shared qualified arithmetic' if independent_replay else 'not requested',
              'publication':'direct dyadic grid conversion and bulk simplex mass allocation',
              'tolerance':str(epsilon),'scaled_producer_endpoints':[[[x.lo.m,x.lo.e,x.hi.m,x.hi.e,x.E] for x in row] if row is not None else None for row in rows],
              'counter_scope':'interval source/add/mul/div calls; actual significand multiply/divmod/add calls; cumulative bit lengths at rounding and division instrumentation, not a complete bit-operation count',
              'machine_scope':'Theta(n) word operations only under Theorem 4 bounded-domain/occurrence/input-word assumptions; arbitrary integer bits and Python timings remain separately charged'}}
    stats['certificate_coordinates']=sum(plan['cards'])
    stats['certificate_s']=time.monotonic()-certificate_start
    stats['elapsed_s']=time.monotonic()-start
    _tick(deadline,stats)
    return result


def solve(model,deadline=None,epsilon=F(1,200),independent_replay=True):
    """Return certified original singleton rows; deadline is absolute monotonic.

    Every failure carries elapsed_s and all available completed/active phase
    counters in .stats. Sources are immutable during this synchronous solve.
    The final quotient intervals are terminal certificates, not reusable
    arithmetic operands with the pre-normalization multiplicative invariant.
    """
    start=time.monotonic();charged={}
    try:return _solve_impl(model,deadline,epsilon,independent_replay,charged)
    except (DeadlineExceeded,UnsupportedError,ZeroEvidence,ValueError) as exc:
        exc.stats={'completed_or_active_phases':charged,'failure_phase':getattr(exc,'stats',{}),
                   'elapsed_s':time.monotonic()-start}
        raise
