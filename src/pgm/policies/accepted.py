"""The ACCEPTED compatibility policy: the accepted engine, its benchmarked configuration, nothing else.

The configuration below is the one the accepted engine was benchmarked with (the external benchmark of the
accepted engine at pgm 7f28259: "accepted PGM v2.13.2, historical targeted schedule"; the DGP6-DGP9 BASE /
REPAIRED / INCUMBENT arms carried the same frozen base ``route='auto', proposal='mb', schedule='targeted',
table_cap=2^18, enum_cap=2^16, mb_cap=2^24, batch=1024``).  It is recorded explicitly here because
``integrated.solve``'s own defaults (``schedule='baseline'``) do NOT reproduce the accepted arm.  The four
exact constructors (support closure, signed evidence expansion, layered contraction, ancestral response) run
at the engine's shipped defaults (all enabled), as in the accepted arm.

The policy hands the backend the request's whole remaining work allowance after the controller's mandatory
inspection (lexical validation, binding, inventory) and keeps the controller's final publication reserve; it
spends the request's full delta on the single PAC-capable backend (mode auto) and zero otherwise.  It performs
no optional forecast, quotient or spectral exploration and reserves no risk for backends it never invokes.
"""
from __future__ import annotations

from fractions import Fraction as F

NAME = "accepted"
VERSION = "accepted-engine-v2.13.2-targeted/1"
NEEDS_FORECAST = False          # the optional min-product physical forecast is exploration this policy does not use
RISK_SHARES = {"block": F(1)}   # the whole requested delta goes to the single PAC-capable backend
BACKENDS = ("block",)
# the accepted engine configuration (passed explicitly to the block adapter; recorded in every result)
ACCEPTED_CONFIGURATION = dict(
    engine="blockres-integrated v2.13.2 (code/cex/blockres/integrated.py at the frozen parent)",
    schedule="targeted", proposal="mb", table_cap=1 << 18, enum_cap=1 << 16, mb_cap=1 << 24, batch=1024,
    crosscheck=True, constructors="engine defaults (support_closure, evidence_expansion, layered_contraction, ancestral_response all enabled)",
    route_by_mode={"auto": "auto", "deterministic": "exact", "exact": "exact"},
    provenance="external benchmark of the accepted engine (benchmarks/external/reference/PRIOR_PRIMARY_REPORT.md: main 7f28259, historical targeted schedule); DGP6-DGP9 frozen base arm (run_dgp8.FROZEN['base'])",
)


def candidates(meta, request, remaining):
    """One candidate: the accepted engine with its full allowance; the structural route string is unused by it."""
    return [dict(backend="block", reason="accepted compatibility policy: the accepted engine with its benchmarked configuration", allowance_fraction=1.0, structural_route="auto", configuration=dict(ACCEPTED_CONFIGURATION))]


def risk_allocation(request):
    """delta share per backend this policy may invoke (sums to the request delta when PAC is permitted)"""
    return {k: request.delta * v for k, v in RISK_SHARES.items()}


def record():
    return dict(policy=NAME, policy_version=VERSION, backends=list(BACKENDS), risk_shares={k: str(v) for k, v in RISK_SHARES.items()}, configuration=ACCEPTED_CONFIGURATION, needs_forecast=NEEDS_FORECAST)
