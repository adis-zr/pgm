"""COMPATIBILITY SHIM (consolidation step 1, 27 Nov 2026; repair R2). The canonical module is `pgm.algorithms.response.response_certificate`; this historical path
re-exports that one module object (patches through the bare name reach the single implementation). Running this file as a script
re-executes the canonical module as __main__ with the same argv. The shim BINDS to its own checkout: the checkout's src is put first on
sys.path before `pgm` is imported, and an already-imported `pgm` from a different root is refused explicitly (never silently used)."""
import importlib as _il, os as _os, sys as _sys
_SRC = _os.path.realpath(_os.path.join(_os.path.dirname(_os.path.abspath(__file__)), '../../..', 'src'))
_loaded = _sys.modules.get('pgm')
if _loaded is not None:
    _root = _os.path.realpath(_os.path.dirname(_os.path.dirname(getattr(_loaded, '__file__', None) or '/')))
    if _root != _SRC:
        raise ImportError('compatibility shim %s: pgm is already imported from %s, not from this checkout (%s); import this checkout first or use a fresh interpreter' % (__file__, _root, _SRC))
else:
    _sys.path.insert(0, _SRC)
    import pgm as _pgm
    if _os.path.realpath(_os.path.dirname(_os.path.dirname(_pgm.__file__))) != _SRC:
        raise ImportError('compatibility shim %s: pgm resolved to %s instead of this checkout (%s)' % (__file__, _pgm.__file__, _SRC))
if __name__ == '__main__':
    import runpy as _rp; _rp.run_module('pgm.algorithms.response.response_certificate', run_name='__main__', alter_sys=True)
else:
    _sys.modules[__name__] = _il.import_module('pgm.algorithms.response.response_certificate')
