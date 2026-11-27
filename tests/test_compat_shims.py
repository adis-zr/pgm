"""Repair R2: compatibility shims bind to their own checkout and refuse an incompatible already-imported pgm (fresh subprocesses)."""
import os, subprocess, sys, tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SHIM_DIR = ROOT / "code" / "cex" / "blockres"
SRC = ROOT / "src"


def _fake_pgm(tmp):
    d = Path(tmp) / "fakepgm" / "pgm"; d.mkdir(parents=True)
    (d / "__init__.py").write_text('"""FAKE conflicting pgm: an older installation without pgm.algorithms."""\n__version__ = "0.0.0-fake"\n')
    return str(d.parent)


def _run(code, env_extra=None):
    env = {k: v for k, v in os.environ.items() if k not in ("PYTHONPATH",)}
    env.update(env_extra or {})
    return subprocess.run([sys.executable, "-I", "-c", code], capture_output=True, text=True, env=env, timeout=120)


def test_conflicting_package_earlier_on_sys_path_does_not_win():
    with tempfile.TemporaryDirectory() as tmp:
        fake = _fake_pgm(tmp)
        p = _run("import sys; sys.path.insert(0, %r); sys.path.insert(0, %r); import integrated, pgm; import pgm.algorithms.block.integrated as C; print(pgm.__file__); print(integrated is C)" % (fake, str(SHIM_DIR)))
        assert p.returncode == 0, p.stderr
        out = p.stdout.split()
        assert out[0].startswith(str(SRC)) and out[1] == "True"


def test_already_imported_foreign_pgm_is_refused_explicitly():
    with tempfile.TemporaryDirectory() as tmp:
        fake = _fake_pgm(tmp)
        p = _run("import sys; sys.path.insert(0, %r); import pgm; sys.path.insert(0, %r)\ntry:\n    import integrated; print('NO REFUSAL')\nexcept ImportError as e:\n    print('REFUSED', str(e))" % (fake, str(SHIM_DIR)))
        assert p.returncode == 0 and p.stdout.startswith("REFUSED") and "already imported" in p.stdout, p.stdout + p.stderr


def test_script_entry_without_installed_package_runs_the_checkout():
    env = {k: v for k, v in os.environ.items() if k != "PYTHONPATH"}
    p = subprocess.run([sys.executable, "-I", str(SHIM_DIR / "integrated.py"), "--help"], capture_output=True, text=True, env=env, timeout=120)
    assert p.returncode == 0 and "--schedule" in p.stdout, p.stderr


def test_alias_identity_and_same_checkout_already_imported_is_fine():
    p = _run("import sys; sys.path.insert(0, %r); import pgm; sys.path.insert(0, %r); import integrated, blockres; import pgm.algorithms.block.integrated as C, pgm.algorithms.block.blockres as B; print(integrated is C and blockres is B and integrated.BR is B)" % (str(SRC), str(SHIM_DIR)))
    assert p.returncode == 0 and p.stdout.strip() == "True", p.stderr
