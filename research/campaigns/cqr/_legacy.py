"""Isolated compatibility for the byte-preserved PAC research snapshot.

This is deliberately outside pgm. Bare snapshot imports are scoped to each call;
no archived module or import-path mutation is left installed in the caller. The
snapshot bytes are never rewritten and cannot become the current CQR solver.
"""
from contextlib import contextmanager
from functools import wraps
from importlib import import_module, util
from pathlib import Path
import sys
import threading
from ._paths import PAC

_LOCK = threading.RLock()
_CACHE = {}
_ARCHIVE_MODULES = {}
_STRUCTURAL = ('core', 'forest', 'dag', 'support', 'stream', 'stream_float',
               'cex_executor', 'reduction', 'planning', 'geometry')
_MISSING = object()


@contextmanager
def snapshot_context():
    with _LOCK:
        # Canonical modules use relative imports and retain their own identities.
        aliases = {name: import_module('pgm.algorithms.structural.' + name)
                   for name in _STRUCTURAL}
        names = {p.stem for p in Path(PAC).glob('*.py')} | set(aliases)
        before = {name: sys.modules.get(name, _MISSING) for name in names}
        path_before = list(sys.path)
        sys.modules.update(aliases)
        sys.modules.update(_ARCHIVE_MODULES)
        sys.path.insert(0, PAC)
        try:
            yield
        finally:
            for name in names:
                module = sys.modules.get(name)
                file = getattr(module, '__file__', None)
                if file and Path(file).resolve().parent == Path(PAC).resolve():
                    _ARCHIVE_MODULES[name] = module
                old = before[name]
                if old is _MISSING:
                    sys.modules.pop(name, None)
                else:
                    sys.modules[name] = old
            sys.path[:] = path_before


def _module(name):
    if name not in _CACHE:
        path = Path(PAC) / (name + '.py')
        if not path.is_file():
            raise FileNotFoundError('archived PAC research component unavailable: ' + str(path))
        with snapshot_context():
            if name != 'registry':
                sys.modules['registry'] = _module('registry')
            spec = util.spec_from_file_location('research.archive.pac.' + name, path)
            module = util.module_from_spec(spec)
            spec.loader.exec_module(module)
            _CACHE[name] = module
    return _CACHE[name]


class ArchivedModule:
    def __init__(self, name):
        object.__setattr__(self, '_name', name)

    def __getattr__(self, key):
        with snapshot_context():
            value = getattr(_module(self._name), key)
        if not callable(value) or isinstance(value, type):
            return value
        @wraps(value)
        def call(*args, **kwargs):
            with snapshot_context():
                return value(*args, **kwargs)
        return call

    def __setattr__(self, key, value):
        with snapshot_context():
            setattr(_module(self._name), key, value)


def load_pac(name):
    return ArchivedModule(name)
