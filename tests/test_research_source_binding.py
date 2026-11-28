"""Foreign source labels cannot cause probes to run this checkout's algorithms."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from research.paths import repo_root
from research.probe_binding import bind_source, historical_command


class ResearchSourceBindingTests(unittest.TestCase):
    def test_current_source_continues_without_a_foreign_label(self):
        self.assertEqual(bind_source(repo_root(), "dgp6_probes.py"), str(repo_root()))

    def test_all_six_probe_entrypoints_refuse_missing_foreign_runtime(self):
        with tempfile.TemporaryDirectory() as td:
            foreign = Path(td)
            env = os.environ.copy()
            env["PYTHONPATH"] = str(repo_root() / "src")
            for number in (4, 5, 6, 7, 8, 9):
                with self.subTest(number=number):
                    output = foreign / f"result{number}.json"
                    run = subprocess.run([sys.executable, str(repo_root() / f"research/campaigns/hp/dgp{number}_probes.py"),
                                          "--source", str(foreign), "--output", str(output)],
                                         capture_output=True, text=True, env=env, timeout=10)
                    self.assertNotEqual(run.returncode, 0)
                    self.assertIn("SOURCE_BINDING_REFUSED", run.stderr)
                    self.assertFalse(output.exists(), "must not publish a mislabeled current-code report")

    def test_isolated_target_module_wins_over_foreign_pythonpath(self):
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            target = base / "target"
            modules = target / "code/cex/hp"
            modules.mkdir(parents=True)
            (modules / "coarse_envelope.py").write_text("VALUE = 'requested source'\n")
            foreign = base / "foreign"
            foreign.mkdir()
            (foreign / "coarse_envelope.py").write_text("raise RuntimeError('wrong checkout executed')\n")
            probe = base / "probe.py"
            probe.write_text("import sys\nsys.path.insert(0, " + repr(str(foreign)) + ")\nimport coarse_envelope\nprint(coarse_envelope.VALUE)\n")
            command, env = historical_command(target, probe, [])
            env["PYTHONPATH"] = str(foreign)
            run = subprocess.run(command, cwd=target, env=env, capture_output=True, text=True, timeout=10)
            self.assertEqual(run.returncode, 0, run.stderr)
            self.assertEqual(run.stdout.strip(), "requested source")

    def test_transitive_local_import_cannot_fall_back_to_foreign_tree(self):
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            target = base / "target"
            modules = target / "code/cex/hp"
            modules.mkdir(parents=True)
            foreign = base / "foreign"
            foreign.mkdir()
            (foreign / "outside_only.py").write_text("VALUE = 'must not execute'\n")
            (modules / "coarse_envelope.py").write_text("import outside_only\n")
            probe = base / "probe.py"
            probe.write_text("import sys\nsys.path.insert(0, " + repr(str(foreign)) + ")\nimport coarse_envelope\n")
            command, env = historical_command(target, probe, [])
            run = subprocess.run(command, cwd=target, env=env, capture_output=True, text=True, timeout=10)
            self.assertNotEqual(run.returncode, 0)
            self.assertIn("requested source lacks required local module: outside_only", run.stderr)


if __name__ == "__main__":
    unittest.main()
