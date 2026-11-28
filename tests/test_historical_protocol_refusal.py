"""Missing historical paths can never become an accepted preservation comparison."""
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]


class HistoricalProtocolRefusalTests(unittest.TestCase):
    def test_missing_frozen_paths_fail_without_writing_validation(self):
        with tempfile.TemporaryDirectory() as td:
            records = Path(td)
            for name, arguments in (
                ("validate_round.py", ["--records", str(records)]),
                ("run_revision.py", ["review", str(records / "missing_manifest.json")]),
            ):
                with self.subTest(name=name):
                    before = list(records.iterdir())
                    run = subprocess.run([sys.executable, str(ROOT / "research/campaigns/hp" / name), *arguments],
                                         capture_output=True, text=True, timeout=10)
                    self.assertNotEqual(run.returncode, 0)
                    self.assertIn("HISTORICAL_PROTOCOL_ONLY", run.stderr)
                    self.assertNotIn('"all_ok": true', run.stdout)
                    self.assertEqual(list(records.iterdir()), before)


if __name__ == "__main__":
    unittest.main()
