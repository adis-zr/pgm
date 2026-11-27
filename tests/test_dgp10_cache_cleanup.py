"""Certificate setup must return its log-cache reservations on every exit."""
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

from pgm.algorithms.quotient import coarse_envelope as CE
from pgm.algorithms.response import spectral_heatbath_run as runner
from pgm.algorithms.response import spectral_witness as witness


class CertificateCacheCleanupTests(unittest.TestCase):
    def test_setup_refusals_release_already_charged_cache(self):
        for kind in ("DEADLINE", "MEMORY", "INTERNAL"):
            with self.subTest(kind=kind), tempfile.TemporaryDirectory() as td:
                model = Path(td) / "model.uai"
                output = Path(td) / "result.json"
                model.write_text("MARKOV\n2\n2 2\n1\n2 0 1\n4\n1 1 1 1.01\n")
                original_get = witness.LogCache.get
                charged = []

                def fail_after_reservation(cache, value):
                    result = original_get(cache, value)
                    if cache.tag == "certificate log cache":
                        charged.append(cache.owned)
                        if kind == "INTERNAL":
                            raise ValueError("injected certificate setup failure")
                        raise CE.Refused(kind, "injected certificate setup refusal")
                    return result

                argv = ["test", "--input", str(model), "--output", str(output),
                        "--budget", "10", "--admission-stop", "9", "--policy", "revised"]
                with patch.object(witness.LogCache, "get", fail_after_reservation), patch.object(sys, "argv", argv):
                    runner.main()
                result = json.loads(output.read_text())
                mechanism = result["mechanism"]
                self.assertEqual(len(charged), 1)
                self.assertGreater(charged[0], 0)
                self.assertEqual(mechanism["refusal"]["kind"], kind)
                self.assertEqual(result["published"], 0)
                self.assertEqual(mechanism["constructor_live_at_end_bytes"], mechanism["canonical_charge_bytes"])
                self.assertTrue(mechanism["constructor_live_ledger_identity"])


if __name__ == "__main__":
    unittest.main()
