"""Untuned structural portfolio with incumbent-first optional compression.

The structural backend accepts higher-arity binary factors as well as categorical
ones.  When the existing physical work and memory forecast admits that attempt,
this policy gives either kind the same quarter-allowance bounded attempt before
the accepted block engine.  Failure of that dense identity forecast is not
evidence that quotient construction will repay its cost: optional compression
therefore follows the block engine, with the ordinary remaining-budget fallback
allowance.  Existing early structural and checked response routes keep their
precedence.  Forecast rates, prospective risk shares and certificates are unchanged.
"""
from __future__ import annotations

from . import experimental

NAME = "automatic"
VERSION = "structural-portfolio-3"
NEEDS_FORECAST = experimental.NEEDS_FORECAST
NATIVE_ROWS_PER_SECOND = experimental.NATIVE_ROWS_PER_SECOND
RISK_SHARES = dict(experimental.RISK_SHARES)
BACKENDS = experimental.BACKENDS


def candidates(meta, request, remaining):
    choices = experimental._candidates(meta, request, remaining, allow_binary_contraction=True)
    block_index = next(i for i, choice in enumerate(choices) if choice["backend"] == "block")
    quotient_index = next(i for i, choice in enumerate(choices) if choice["backend"] == "quotient")
    if quotient_index < block_index:
        # A rejected or unaffordable dense forecast says nothing about the cost
        # or quality of a representation we have not constructed.  Keep the
        # incumbent's remaining allowance intact; compression remains available
        # if the incumbent returns early without completing all requested rows.
        deferred = dict(choices.pop(quotient_index),
                        reason="checked quotient alternative after the incumbent block attempt",
                        allowance_fraction=1.0)
        choices.insert(block_index, deferred)  # block shifted left by the pop
    return choices


def risk_allocation(request):
    return {key: request.delta * share for key, share in RISK_SHARES.items()}


def record():
    result = experimental.record()
    result.update(policy=NAME, policy_version=VERSION,
                  exact_contraction_admission="same physical work/memory predicate for binary and nonbinary higher-arity factors",
                  compression_precedence="after the incumbent block attempt, using the remaining request allowance")
    return result
