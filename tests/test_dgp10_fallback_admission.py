"""Coprime denominators require quadratic-cardinality fallback admission."""
from fractions import Fraction
import math
from pathlib import Path
import sys
import time
import tracemalloc
from types import SimpleNamespace
import unittest

from pgm.algorithms.quotient import coarse_envelope as CE
from pgm.algorithms.response import heatbath_exact as exact
from pgm.algorithms.response import heatbath_native as native


def coprime_model():
    denominators = []
    candidate = (1 << 1024) + 1
    while len(denominators) < 64:
        if all(math.gcd(candidate, d) == 1 for d in denominators):
            denominators.append(candidate)
        candidate += 2
    weights = [Fraction(d - 1, d) for d in denominators]
    return SimpleNamespace(n=1, cards=[64], psi=[weights], pairs=[], incident=[[]])


class FallbackAdmissionTests(unittest.TestCase):
    def test_common_denominator_work_is_admitted_before_weights(self):
        model = coprime_model()
        estimate = native.fallback_bytes_estimate_one(model, 0)
        # Input storage is outside the traced region.  Integerization alone
        # exceeds the old allowance before cumulative/refinement work starts.
        tracemalloc.start()
        try:
            integer_weights, total = exact.integerize(model.psi[0])
            _, peak = tracemalloc.get_traced_memory()
        finally:
            tracemalloc.stop()
        self.assertGreater(peak, 100_000)
        self.assertGreaterEqual(estimate, peak)
        self.assertEqual(total, sum(integer_weights))

        visited = []
        model.weights_exact = lambda state, site: visited.append(site) or model.psi[site]
        chain = native.NativeChain.__new__(native.NativeChain)
        chain.m = model
        chain.ctx = None
        chain.budget = CE.Budget(100_000)
        chain.clock = CE.Clock(time.monotonic() + 10, {})
        chain.fb_est = [estimate]
        chain.state = lambda: [0]

        class PendingDecision:
            @staticmethod
            def hb_unresolved(context, uniform):
                uniform._obj.value = 1 << 52
                return 0

        chain.lib = PendingDecision()
        with self.assertRaises(CE.Refused) as caught:
            chain._resolve()
        self.assertEqual(caught.exception.kind, "MEMORY")
        self.assertEqual(visited, [])
        self.assertEqual(chain.budget.live, 0)


if __name__ == "__main__":
    unittest.main()
