"""Public scheduling POLICIES, separated from the guarantee MODE.

A policy decides which backend adapters may run, in which order, with which allowance fraction and which
prospective risk share.  It never changes a certificate: every backend proves its own rows within the
allowance and delta it is handed, and the controller's publication geometry is policy-independent.

* ``accepted`` (default): the accepted engine (block contraction / PAC, v2.13.2) through the common contract
  with its verified accepted schedule / route configuration; one attempt, the request's available allowance,
  the full requested delta when PAC is permitted; no optional quotient / spectral exploration.
* ``experimental``: the frozen ``structural-portfolio-1`` switchboard of the scored commit 3283cfd, with its
  choices, coefficients, allowance fractions and prospective backend risk shares unchanged.
* ``automatic``: the same portfolio, additionally admitting a bounded structural attempt on physically
  affordable binary higher-arity models using the existing categorical admission rule.
"""
from __future__ import annotations

from . import accepted, experimental, automatic

POLICIES = {accepted.NAME: accepted, experimental.NAME: experimental, automatic.NAME: automatic}
DEFAULT_POLICY = accepted.NAME


def get(name: str):
    try:
        return POLICIES[name]
    except KeyError:
        raise ValueError("policy must be one of %s" % sorted(POLICIES)) from None


def names():
    return tuple(sorted(POLICIES))
