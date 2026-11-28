"""The retired tree is completely accounted for and historical archives stay immutable."""
from copy import deepcopy
import importlib.util
import json
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("migration_verifier", ROOT / "tests/qualification/verify_migration.py")
VERIFIER = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(VERIFIER)


class MigrationManifestTests(unittest.TestCase):
    def test_complete_inventory_and_preserved_archives(self):
        # Runtime files may evolve after migration; the strict CLI verifies snapshot hashes
        # at migration closeout. Historical archives must always retain their exact bytes.
        result = VERIFIER.verify(ROOT, check_destination_hashes=False)
        self.assertTrue(result["all_ok"], result["issues"])
        self.assertEqual(result["code_dispositions"], 485)
        self.assertEqual(result["preserved_copies"], 8)

    def test_missing_disposition_is_rejected(self):
        data = json.loads((ROOT / VERIFIER.MANIFEST).read_text())
        data["entries"] = [r for r in data["entries"] if r["old"] != "code/.gitkeep"]
        result = VERIFIER.verify(ROOT, data, check_destination_hashes=False)
        self.assertFalse(result["all_ok"])
        self.assertIn("code dispositions do not exactly cover the baseline inventory", result["issues"])

    def test_wrong_original_hash_is_rejected(self):
        data = deepcopy(json.loads((ROOT / VERIFIER.MANIFEST).read_text()))
        row = next(r for r in data["entries"] if r["old"] == "code/.gitkeep")
        row["old_sha256"] = "0" * 64
        result = VERIFIER.verify(ROOT, data, check_destination_hashes=False)
        self.assertFalse(result["all_ok"])
        self.assertIn("source hash differs from baseline git blob: code/.gitkeep", result["issues"])


if __name__ == "__main__":
    unittest.main()
