"""Normative exact-rational scalar reference for DGP10.

This module does not certify a model, Markov kernel, source range, variance
witness, observation sum, or risk allocation. Its caller must establish those
inputs. It checks the scalar implication used AFTER those obligations hold.

API
---
exp_interval(x, bits=80, budget=None) -> Interval(Fraction, Fraction)
log_interval(x, bits=80, budget=None) -> Interval(Fraction, Fraction)
verify_two_point_rho(eta, z0, z1, p1, tilt, rho, ...) -> dict
two_point_rho_upper(eta, z0, z1, p1, tilt, ...) -> Fraction
verify_moment_upper(M, eta, B, y_upper, U, negative_tilt, delta,
                    rho=None, ...) -> dict
verify_mean_radius(M, eta, V, C, positive_tilt, rho, delta,
                   radius=None, ...) -> dict

For moment inversion, Y is in [0,B], y_upper encloses its observed mean,
and U is the proposed upper bound on E Y. negative_tilt MUST be negative.
If rho is omitted, a bounded exact bisection supplies a checked rho.

For the mean certificate, Z is centered, |Z|<=C and Var Z<=V. The two-point
majorant has support {-V/C,C}, with probability V/(V+C^2) at C. The returned
radius_upper is a rigorous two-sided radius at failure allowance delta.
If radius is supplied, acceptance additionally requires it to cover that
computed bound. For V=0 the conservative zero-mass second state is retained.

All scalar proof arithmetic is Fraction arithmetic. Exponentials and logs
are enclosed by Taylor/atanh series with rigorous tails, range reduction and
outward dyadic rounding. The sqrt-free 2x2 PSD check uses upper entries.
There is no binary64 acceptance decision. Optional NumPy self-tests are only
advisory diagnostics and are labelled as such.

The limits below bound this reference. They are not a substitute for the
engine's allocation/accounting contract. A rejected or refused check never
authorizes a certificate. Runtime deadlines can be supplied through Budget.
"""
from __future__ import annotations

from dataclasses import dataclass
from fractions import Fraction as F
import json
import math
from pathlib import Path
import time


class ReferenceRefusal(Exception):
    def __init__(self, kind: str, reason: str):
        super().__init__(reason)
        self.kind, self.reason = kind, reason


@dataclass
class Budget:
    max_steps: int = 100_000
    max_input_bits: int = 8192
    max_internal_bits: int = 262_144
    max_series_terms: int = 256
    max_range_shifts: int = 4096
    deadline: float | None = None
    steps: int = 0

    def tick(self, label: str = "scalar operation") -> None:
        self.steps += 1
        if self.steps > self.max_steps:
            raise ReferenceRefusal("REFERENCE_LIMIT", "step limit at " + label)
        if self.deadline is not None and time.monotonic() > self.deadline:
            raise ReferenceRefusal("DEADLINE", "reference deadline at " + label)

    def growth(self, numerator_bits: int, denominator_bits: int) -> None:
        self.tick("arithmetic admission")
        if max(numerator_bits, denominator_bits) > self.max_internal_bits:
            raise ReferenceRefusal("REFERENCE_LIMIT", "predicted rational growth")


@dataclass(frozen=True)
class Interval:
    lo: F
    hi: F

    def __post_init__(self):
        if self.lo > self.hi:
            raise AssertionError("reversed interval")

    def strings(self) -> dict:
        return {"lo": str(self.lo), "hi": str(self.hi)}


def _budget(b: Budget | None) -> Budget:
    return b if b is not None else Budget()


def _q(x, b: Budget) -> F:
    b.tick("input")
    if isinstance(x, bool) or not isinstance(x, (F, int, str)):
        raise ReferenceRefusal("INPUT", "use Fraction, integer or exact string; no implicit float")
    if isinstance(x, str) and len(x) > 20_000:
        raise ReferenceRefusal("INPUT", "input string too long")
    try:
        x = F(x)
    except (ValueError, ZeroDivisionError) as e:
        raise ReferenceRefusal("INPUT", "invalid rational") from e
    if max(abs(x.numerator).bit_length(), x.denominator.bit_length()) > b.max_input_bits:
        raise ReferenceRefusal("INPUT", "input rational bit limit")
    return x


def _nb(x: F) -> int:
    return max(1, abs(x.numerator).bit_length())


def _db(x: F) -> int:
    return x.denominator.bit_length()


def _add(x: F, y: F, b: Budget) -> F:
    b.growth(max(_nb(x)+_db(y), _nb(y)+_db(x))+1, _db(x)+_db(y))
    return x+y


def _sub(x: F, y: F, b: Budget) -> F:
    return _add(x, -y, b)


def _mul(x: F, y: F, b: Budget) -> F:
    b.growth(_nb(x)+_nb(y), _db(x)+_db(y))
    return x*y


def _div(x: F, y: F, b: Budget) -> F:
    if y == 0:
        raise ReferenceRefusal("INPUT", "division by zero")
    b.growth(_nb(x)+_db(y), _db(x)+_nb(y))
    return x/y


def _dyadic(x: F, bits: int, up: bool, b: Budget) -> F:
    b.growth(_nb(x)+bits+1, _db(x)+bits+1)
    num=x.numerator << bits
    n=-((-num)//x.denominator) if up else num//x.denominator
    return F(n, 1 << bits)


def _precision(bits: int) -> None:
    if not isinstance(bits, int) or not 16 <= bits <= 256:
        raise ReferenceRefusal("INPUT", "precision must be 16..256 bits")


def exp_interval(x, bits: int = 80, budget: Budget | None = None) -> Interval:
    """Rigorous enclosure; |x|<=64. Relative width is checked against 2^-bits."""
    b=_budget(budget);_precision(bits);x=_q(x,b)
    if abs(x)>64:
        raise ReferenceRefusal("INPUT", "exponential argument exceeds reference cap 64")
    if x==0:
        return Interval(F(1),F(1))
    if x<0:
        q=exp_interval(-x,bits,b)
        return Interval(_div(F(1),q.hi,b),_div(F(1),q.lo,b))
    shifts=0;y=x
    while y>F(1,2):
        b.tick("exponential range reduction");shifts+=1
        if shifts>b.max_range_shifts:
            raise ReferenceRefusal("REFERENCE_LIMIT", "exponential shift limit")
        y=_div(y,F(2),b)
    work=bits+2*shifts+24
    yl=_dyadic(y,work,False,b);yu=_dyadic(y,work,True,b)
    sl=su=tl=tu=F(1);tol=F(1,1 << (work+4));tail=None
    for k in range(1,b.max_series_terms+1):
        tl=_div(_mul(tl,yl,b),F(k),b);tu=_div(_mul(tu,yu,b),F(k),b)
        sl=_add(sl,tl,b);su=_add(su,tu,b)
        first=_div(_mul(tu,yu,b),F(k+1),b)
        ratio=_div(yu,F(k+2),b)
        tail=_div(first,_sub(F(1),ratio,b),b)
        if tail<=tol:break
    else:
        raise ReferenceRefusal("REFERENCE_LIMIT", "exponential series limit")
    lo=_dyadic(sl,work,False,b);hi=_dyadic(_add(su,tail,b),work,True,b)
    for _ in range(shifts):
        b.tick("exponential interval square")
        lo=_dyadic(_mul(lo,lo,b),work,False,b)
        hi=_dyadic(_mul(hi,hi,b),work,True,b)
    if _sub(hi,lo,b)>_mul(lo,F(1,1<<bits),b):
        raise ReferenceRefusal("REFERENCE_LIMIT", "requested exponential precision not reached")
    return Interval(lo,hi)


def _log_unit(y: F, bits: int, b: Budget) -> Interval:
    """Enclose log(y), 1<=y<=2, using 2*atanh((y-1)/(y+1))."""
    if not F(1)<=y<=F(2):raise AssertionError("unit log range")
    if y==1:return Interval(F(0),F(0))
    z=_div(_sub(y,F(1),b),_add(y,F(1),b),b);z2=_mul(z,z,b)
    power=z;total=F(0);tol=F(1,1<<(bits+4));tail=None
    for j in range(b.max_series_terms):
        total=_add(total,_div(_mul(F(2),power,b),F(2*j+1),b),b)
        power=_mul(power,z2,b)
        tail=_div(_mul(F(2),power,b),_mul(F(2*j+3),_sub(F(1),z2,b),b),b)
        if tail<=tol:return Interval(total,_add(total,tail,b))
    raise ReferenceRefusal("REFERENCE_LIMIT", "log series limit")


def log_interval(x, bits: int = 80, budget: Budget | None = None) -> Interval:
    """Rigorous absolute enclosure of log(x), x>0, with bounded binary reduction."""
    b=_budget(budget);_precision(bits);x=_q(x,b)
    if x<=0:raise ReferenceRefusal("INPUT", "logarithm needs positive input")
    if x==1:return Interval(F(0),F(0))
    k=x.numerator.bit_length()-x.denominator.bit_length()
    if abs(k)>b.max_range_shifts:
        raise ReferenceRefusal("REFERENCE_LIMIT", "log range-reduction limit")
    scale=F(1<<k) if k>=0 else F(1,1<<(-k))
    y=_div(x,scale,b)
    if y<1:k-=1;y=_mul(y,F(2),b)
    elif y>=2:k+=1;y=_div(y,F(2),b)
    if abs(k)>b.max_range_shifts:
        raise ReferenceRefusal("REFERENCE_LIMIT", "log range-reduction limit")
    work=bits+abs(k).bit_length()+16
    yl=_dyadic(y,work,False,b);yu=_dyadic(y,work,True,b)
    llo=_log_unit(yl,work,b).lo;lhi=_log_unit(yu,work,b).hi
    l2=_log_unit(F(2),work,b)
    if k>=0:
        lo=_add(_mul(F(k),l2.lo,b),llo,b);hi=_add(_mul(F(k),l2.hi,b),lhi,b)
    else:
        lo=_add(_mul(F(k),l2.hi,b),llo,b);hi=_add(_mul(F(k),l2.lo,b),lhi,b)
    return Interval(_dyadic(lo,bits,False,b),_dyadic(hi,bits,True,b))


def _two_point_entries(eta: F,z0: F,z1: F,p1: F,t: F,bits: int,b: Budget):
    if not 0<eta<=1 or not 0<=p1<=1:
        raise ReferenceRefusal("INPUT", "eta or proxy probability out of range")
    lam=_sub(F(1),eta,b);p0=_sub(F(1),p1,b)
    e0=exp_interval(_mul(t,z0,b),bits,b);e1=exp_interval(_mul(t,z1,b),bits,b)
    d0=_mul(e0.hi,_add(lam,_mul(eta,p0,b),b),b)
    d1=_mul(e1.hi,_add(lam,_mul(eta,p1,b),b),b)
    off2=_mul(_mul(_mul(eta,eta,b),_mul(p0,p1,b),b),_mul(e0.hi,e1.hi,b),b)
    return d0,d1,off2,max(e0.hi,e1.hi),e0,e1


def _psd(rho: F,entries,b: Budget) -> dict:
    d0,d1,off2,_,e0,e1=entries
    s0=_sub(rho,d0,b);s1=_sub(rho,d1,b)
    det=_sub(_mul(s0,s1,b),off2,b)
    return dict(accepted=(rho>0 and s0>=0 and s1>=0 and det>=0),
                diagonal_slack_0=str(s0),diagonal_slack_1=str(s1),
                determinant_slack=str(det),exp_0=e0.strings(),exp_1=e1.strings())


def verify_two_point_rho(eta,z0,z1,p1,tilt,rho,*,bits=80,budget=None) -> dict:
    b=_budget(budget)
    try:
        vals=[_q(x,b) for x in (eta,z0,z1,p1,tilt,rho)]
        eta,z0,z1,p1,t,rho=vals
        out=_psd(rho,_two_point_entries(eta,z0,z1,p1,t,bits,b),b)
        out.update(rho=str(rho),steps=b.steps)
        return out
    except ReferenceRefusal as e:
        return dict(accepted=False,refusal=e.kind,reason=e.reason,steps=b.steps)


def two_point_rho_upper(eta,z0,z1,p1,tilt,*,bits=80,budget=None) -> F:
    """Bounded proposal+verification; returns a proved upper norm, never just an eigenvalue guess."""
    b=_budget(budget);_precision(bits)
    eta,z0,z1,p1,t=[_q(x,b) for x in (eta,z0,z1,p1,tilt)]
    entries=_two_point_entries(eta,z0,z1,p1,t,bits,b)
    lo=F(0);hi=entries[3]
    if not _psd(hi,entries,b)['accepted']:raise AssertionError("operator-norm initial upper bound")
    tol=_mul(max(F(1),hi),F(1,1<<bits),b)
    for _ in range(bits+4):
        if _sub(hi,lo,b)<=tol:break
        mid=_div(_add(lo,hi,b),F(2),b)
        if _psd(mid,entries,b)['accepted']:hi=mid
        else:lo=mid
    if not _psd(hi,entries,b)['accepted']:raise AssertionError("final rho failed")
    return hi


def _common(M,eta,delta,b):
    if isinstance(M,bool) or not isinstance(M,int) or not 1<=M<=(1<<63)-1:
        raise ReferenceRefusal("INPUT", "M must be a positive integer at most 2^63-1")
    eta=_q(eta,b);delta=_q(delta,b)
    if not 0<eta<=1 or not 0<delta<1:
        raise ReferenceRefusal("INPUT", "eta or delta outside valid range")
    return eta,delta


def verify_moment_upper(M,eta,B,y_upper,U,negative_tilt,delta,*,rho=None,bits=80,budget=None) -> dict:
    """Check one-sided upper confidence endpoint for E[Y], Y in [0,B].

    Acceptance is a scalar implication at allowance delta. The caller must
    cover center/checkpoint/query selection and nonstationary coupling.
    """
    b=_budget(budget)
    try:
        eta,delta=_common(M,eta,delta,b)
        B,y,U,t=[_q(x,b) for x in (B,y_upper,U,negative_tilt)]
        if B<0 or not 0<=y<=B or not 0<=U<=B or t>=0:
            raise ReferenceRefusal("INPUT", "bounded-moment arguments or tilt sign invalid")
        if U==B:
            return dict(accepted=True,mode='support',upper_mean=str(U),steps=b.steps)
        if B==0:raise AssertionError("zero support was already handled")
        p1=_div(U,B,b)
        rr=two_point_rho_upper(eta,F(0),B,p1,t,bits=bits,budget=b) if rho is None else _q(rho,b)
        proof=verify_two_point_rho(eta,F(0),B,p1,t,rr,bits=bits,budget=b)
        if not proof['accepted']:
            return dict(accepted=False,reason='rho not verified',rho=str(rr),proof=proof,steps=b.steps)
        lr=log_interval(rr,bits,b);ld=log_interval(delta,bits,b)
        lhs=_mul(F(M),_sub(lr.hi,_mul(t,y,b),b),b)
        accepted=lhs<=ld.lo
        return dict(accepted=accepted,upper_mean=str(U),rho=str(rr),
                    log_probability_upper=str(lhs),log_delta_lower=str(ld.lo),
                    proof=proof,steps=b.steps)
    except ReferenceRefusal as e:
        return dict(accepted=False,refusal=e.kind,reason=e.reason,steps=b.steps)


def verify_mean_radius(M,eta,V,C,positive_tilt,rho,delta,*,radius=None,bits=80,budget=None) -> dict:
    """Check centered two-sided mean radius from the Hermite proxy.

    V and C are deterministic or separately certified bounds. This routine
    does not allocate the risk of the variance certificate. The 2/delta term
    accounts for the two tails, not for queries/checkpoints/centers.
    """
    b=_budget(budget)
    try:
        eta,delta=_common(M,eta,delta,b)
        v,c,t,rr=[_q(x,b) for x in (V,C,positive_tilt,rho)]
        rad=None if radius is None else _q(radius,b)
        if v<0 or c<0 or t<=0 or rr<=0 or (rad is not None and rad<0):
            raise ReferenceRefusal("INPUT", "mean-radius arguments invalid")
        c2=_mul(c,c,b)
        if v>c2:
            raise ReferenceRefusal("INPUT", "variance bound exceeds C^2; explicitly clamp it first")
        if c==0:
            return dict(accepted=(v==0 and rr>=1),mode='constant',radius_upper='0',rho=str(rr),steps=b.steps)
        z0=-_div(v,c,b);p1=_div(v,_add(v,c2,b),b)
        proof=verify_two_point_rho(eta,z0,c,p1,t,rr,bits=bits,budget=b)
        if not proof['accepted']:
            return dict(accepted=False,reason='rho not verified',rho=str(rr),proof=proof,steps=b.steps)
        lr=log_interval(rr,bits,b);pen=log_interval(_div(F(2),delta,b),bits,b)
        required=_div(_add(lr.hi,_div(pen.hi,F(M),b),b),t,b)
        required=max(F(0),required)
        return dict(accepted=(rad is None or rad>=required),radius_upper=str(required),
                    rho=str(rr),log_rho_upper=str(lr.hi),log_two_over_delta_upper=str(pen.hi),
                    supplied_radius=None if rad is None else str(rad),proof=proof,steps=b.steps)
    except ReferenceRefusal as e:
        return dict(accepted=False,refusal=e.kind,reason=e.reason,steps=b.steps)


def self_test() -> dict:
    checks={}
    checks['exp_zero_exact']=exp_interval(0)==Interval(F(1),F(1))
    checks['log_one_exact']=log_interval(1)==Interval(F(0),F(0))
    eta=F(1,4);v=F(1,100);c=F(1,2);t=F(1,10);p1=v/(v+c*c)
    rho=two_point_rho_upper(eta,-v/c,c,p1,t)
    good=verify_mean_radius(1_000_000,eta,v,c,t,rho,F(1,1_000_000))
    bad=verify_mean_radius(1_000_000,eta,v,c,t,F(1),F(1,1_000_000))
    checks['valid_mean_certificate_accepted']=good['accepted']
    checks['lowered_rho_rejected']=not bad['accepted']
    radius=F(good['radius_upper'])
    checks['explicit_radius_accepted']=verify_mean_radius(1_000_000,eta,v,c,t,rho,F(1,1_000_000),radius=radius)['accepted']
    checks['lowered_radius_rejected']=not verify_mean_radius(1_000_000,eta,v,c,t,rho,F(1,1_000_000),radius=radius/2)['accepted']
    moment=verify_moment_upper(1_000_000,eta,F(1),F(1,100),F(1,50),F(-1,10),F(1,1_000_000))
    moment_bad=verify_moment_upper(1_000_000,eta,F(1),F(1,100),F(1,200),F(-1,10),F(1,1_000_000))
    checks['valid_moment_endpoint_accepted']=moment['accepted']
    checks['too_small_moment_endpoint_rejected']=not moment_bad['accepted']
    checks['support_endpoint_accepted']=verify_moment_upper(1,eta,1,1,1,-1,F(1,100))['accepted']
    checks['constant_observable_accepted']=verify_mean_radius(1,eta,0,0,1,1,F(1,100),radius=0)['accepted']
    checks['budget_refusal_is_not_acceptance']=not verify_mean_radius(10,eta,v,c,t,rho,F(1,100),budget=Budget(max_steps=1))['accepted']
    advisory=[]
    try:
        import numpy as np
        z=np.array([-.25,0.,.25]);p=np.array([.25,.5,.25]);vv=F(1,32);cc=F(1,4);tt=F(1,5)
        for ee in [F(1),F(1,2),F(1,10),F(1,100)]:
            rr=two_point_rho_upper(ee,-vv/cc,cc,vv/(vv+cc*cc),tt)
            D=np.diag(np.exp(float(tt)*z/2));b=np.sqrt(p);Q=(1-float(ee))*np.eye(3)+float(ee)*np.outer(b,b)
            eigen=float(np.linalg.eigvalsh(D@Q@D)[-1]);ok=eigen<=float(rr)+1e-13
            advisory.append(dict(eta=str(ee),actual_trinary_norm=eigen,certified_proxy_norm_upper=str(rr),ok=bool(ok)))
    except ImportError:
        advisory=[{'skipped':'NumPy absent; exact scalar self-tests still ran'}]
    return dict(all_ok=all(checks.values()),checks=checks,valid_mean=good,invalid_mean=bad,
                valid_moment=moment,invalid_moment=moment_bad,
                advisory_scope='Binary64 tiny-law diagnostics only; never part of checker acceptance.',
                advisory=advisory)


if __name__=='__main__':
    result=self_test()
    Path(__file__).with_name('REFERENCE_CHECKED_TILT_SELFTEST.json').write_text(json.dumps(result,indent=2)+'\n')
    print(json.dumps({'all_ok':result['all_ok'],'checks':result['checks'],'advisory':result['advisory']},indent=2))
    if not result['all_ok']:raise SystemExit(1)
