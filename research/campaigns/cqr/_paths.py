"""Research-only locations; the installed CQR implementation does not import this."""
from pathlib import Path
from research.bootstrap import activate
from research.paths import repo_root, runs_root, source_path, subprocess_env

activate()
ROOT = str(repo_root())
HERE = str(Path(__file__).resolve().parent)
CODE = str(repo_root() / 'code')
CEX = str(repo_root() / 'research' / 'archive')
PAC = str(Path(CEX) / 'pac')
NEWARM = str(Path(source_path('pgm.algorithms.structural.core')).parent)
RUNTIME = str(Path(source_path('pgm.algorithms.cqr.task')).parent)
PYTHON_ENV = subprocess_env
PY = __import__('sys').executable
PYTHON_COMMAND_PREFIX = (PY, '-m')
