"""Automatic dispatch broadens applicability, not budgets or guarantee rules."""
from fractions import Fraction

import pytest

from pgm import policies
from pgm.contracts import InferenceRequest
from pgm.policies import automatic, experimental


def metadata(*, cardinality=2, arity=3, work=100, memory=1 << 20):
    return dict(cards=[cardinality] * 4, evidence={}, max_effective_arity=arity,
                native_forecast=dict(sum_product=work, native_bytes_estimate=memory),
                pairwise_forest=False, binary_pairwise_bipartite=False,
                hard_zero_entries=0)


def request(mode="auto"):
    return InferenceRequest("unused.uai", budget=20, memory_mib=256,
                            mode=mode, policy="experimental")


@pytest.mark.parametrize("mode", ["auto", "deterministic", "exact"])
def test_affordable_binary_higher_arity_gets_bounded_structural_attempt(mode):
    meta, req = metadata(), request(mode)
    old = experimental.candidates(meta, req, 10)
    new = automatic.candidates(meta, req, 10)
    assert [c["backend"] for c in old] == ["block", "quotient", "structural"]
    assert [c["backend"] for c in new] == ["structural", "block", "quotient"]
    assert new[0]["allowance_fraction"] == Fraction(1, 4)
    assert new[0]["structural_route"] == "auto"
    assert new[1:] == old[:2]
    assert "binary higher-arity" in new[0]["reason"]


@pytest.mark.parametrize("work,memory", [
    (200_000_001, 1 << 20), (100, (256 << 20) + 1),
    (None, 1 << 20), (100, None), (None, None),
])
def test_unavailable_forecasts_preserve_the_prior_fallbacks(work, memory):
    meta, req = metadata(work=work, memory=memory), request()
    assert automatic.candidates(meta, req, 10) == experimental.candidates(meta, req, 10)


@pytest.mark.parametrize("cardinality,arity,forest,stream", [
    (3, 3, False, False), (3, 2, False, False),
    (2, 2, False, False), (2, 2, True, False),
    (2, 2, False, True), (3, 2, True, False),
])
def test_existing_early_routes_keep_their_order_and_allowances(cardinality, arity, forest, stream):
    meta, req = metadata(cardinality=cardinality, arity=arity), request()
    meta.update(pairwise_forest=forest, binary_pairwise_bipartite=stream,
                bipartition_sizes=[[2, 2]] if stream else [])
    assert automatic.candidates(meta, req, 10) == experimental.candidates(meta, req, 10)


def test_work_and_memory_boundaries_use_the_existing_inclusive_predicate():
    meta = metadata(work=automatic.NATIVE_ROWS_PER_SECOND * 10, memory=256 << 20)
    first = automatic.candidates(meta, request(), 10)[0]
    assert first["backend"] == "structural" and first["allowance_fraction"] == 0.25


def test_policy_registration_does_not_promote_or_reallocate_risk():
    assert policies.DEFAULT_POLICY == "accepted"
    assert policies.get("automatic") is automatic
    assert automatic.VERSION != experimental.VERSION
    assert automatic.NATIVE_ROWS_PER_SECOND == experimental.NATIVE_ROWS_PER_SECOND
    assert automatic.risk_allocation(request()) == experimental.risk_allocation(request())
    assert sum(automatic.risk_allocation(request()).values()) == request().delta
    assert automatic.record()["policy"] == "automatic"
