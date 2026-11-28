"""Untuned structural portfolio with domain-independent exact-contraction admission.

The structural backend accepts higher-arity binary factors as well as categorical
ones.  When the existing physical work and memory forecast admits that attempt,
this policy gives either kind the same quarter-allowance bounded attempt before
the accepted block engine.  It changes no forecast rate, risk share, constructor,
certificate or fallback rule from structural-portfolio-1.  Affordable pairwise
and forest/stream routes retain their earlier precedence.
"""
from __future__ import annotations

from . import experimental

NAME = "automatic"
VERSION = "structural-portfolio-2"
NEEDS_FORECAST = experimental.NEEDS_FORECAST
NATIVE_ROWS_PER_SECOND = experimental.NATIVE_ROWS_PER_SECOND
RISK_SHARES = dict(experimental.RISK_SHARES)
BACKENDS = experimental.BACKENDS


def candidates(meta, request, remaining):
    return experimental._candidates(meta, request, remaining, allow_binary_contraction=True)


def risk_allocation(request):
    return {key: request.delta * share for key, share in RISK_SHARES.items()}


def record():
    result = experimental.record()
    result.update(policy=NAME, policy_version=VERSION,
                  exact_contraction_admission="same physical work/memory predicate for binary and nonbinary higher-arity factors")
    return result
