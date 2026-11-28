"""The frozen EXPERIMENTAL portfolio ``structural-portfolio-1`` (scored commit 3283cfd), moved verbatim.

The ordering is a fixed structural policy. Work forecasts affect scheduling, never certificate validity. Only one
backend runs at a time; each is attempted at most once. A refusal permits another applicable method within the SAME
request deadline. No outcome from another backend or benchmark is consulted.  Nothing in this module's choices,
coefficients, allowance fractions or prospective risk shares may change in the consolidation round.
"""
from __future__ import annotations

from fractions import Fraction as F
import math

NAME = "experimental"
VERSION = "structural-portfolio-1"
NEEDS_FORECAST = True
# Retained native planning rate, not fitted on this experiment. It is an
# optimistic scheduling estimate only, not an accuracy or completion promise.
NATIVE_ROWS_PER_SECOND = 20_000_000
RISK_SHARES = {"structural": F(0), "block": F(1, 2), "quotient": F(1, 4), "response": F(1, 4)}
BACKENDS = ("structural", "block", "quotient", "response")


def candidates(meta, request, remaining):
    """Return ordered candidates and explanations, without allocating a solver."""
    return _candidates(meta, request, remaining, allow_binary_contraction=False)


def _candidates(meta, request, remaining, *, allow_binary_contraction):
    """Shared fixed rules; the automatic policy also admits affordable binary higher-arity contraction."""
    cards = meta["cards"]
    arity = meta.get("max_effective_arity", max(map(len, meta.get("conditioned_scopes", [])), default=0))
    binary = all(c <= 2 for v, c in enumerate(cards) if v not in meta["evidence"])
    pairwise = arity <= 2
    native = meta.get("native_forecast") or {}
    native_work = native.get("sum_product", native.get("work", math.inf))
    native_memory = native.get("native_bytes_estimate", meta.get("native_forecast_memory_bytes", math.inf))
    # Optional estimator refusals retain explicit null fields. They remove the
    # affordability forecast, not the request or any later inference route.
    if native_work is None:
        native_work = math.inf
    if native_memory is None:
        native_memory = math.inf
    native_affordable = native_memory <= request.memory_mib * (1 << 20) and native_work <= NATIVE_ROWS_PER_SECOND * remaining
    groups = meta.get("bipartition_sizes", [])
    stream_steps = sum((1 << min(group)) * sum(group) for group in groups) if groups and all(min(g) < 63 for g in groups) else math.inf
    stream_affordable = bool(meta.get("binary_pairwise_bipartite")) and bool(meta.get("stream_native_admissible", True)) and stream_steps <= NATIVE_ROWS_PER_SECOND * remaining
    positive = meta.get("hard_zero_entries", 0) == 0
    choices = []
    def add(name, reason, fraction=1.0, route="auto"):
        if name not in [c["backend"] for c in choices]:
            choices.append(dict(backend=name, reason=reason, allowance_fraction=fraction, structural_route=route))
    if meta.get("pairwise_forest"):
        add("structural", "evidence-sliced pairwise forest")
    elif stream_affordable:
        add("structural", "admitted binary bipartite streaming work", route="stream")
    elif pairwise and native_affordable:
        add("structural", "pairwise exact contraction physically affordable")
    elif native_affordable and (not binary or allow_binary_contraction):
        reason = ("bounded exact attempt on affordable binary higher-arity factors" if binary
                  else "bounded exact attempt on nonbinary factors")
        add("structural", reason, fraction=0.25)
    elif pairwise and positive and request.mode == "auto":
        add("response", "positive pairwise model; spectral admission checks applicability")
    if not binary and not native_affordable:
        add("quotient", "identity forecast unaffordable; bounded checked state compression", fraction=0.25)
    add("block", "accepted reductions, contraction and certified residual stream")
    add("quotient", "checked quotient alternative after an early refusal")
    if not any(c["backend"] == "structural" for c in choices):
        add("structural", "remaining deterministic alternative")
    if pairwise and positive and request.mode == "auto":
        add("response", "remaining checked Markov alternative")
    return choices


def risk_allocation(request):
    return {k: request.delta * v for k, v in RISK_SHARES.items()}


def record():
    return dict(policy=NAME, policy_version=VERSION, backends=list(BACKENDS), risk_shares={k: str(v) for k, v in RISK_SHARES.items()}, native_rows_per_second=NATIVE_ROWS_PER_SECOND, needs_forecast=NEEDS_FORECAST)
