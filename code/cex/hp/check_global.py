"""COMPATIBILITY SHIM (consolidation step 1, 27 Nov 2026). The canonical module is `pgm.algorithms.quotient.check_global`; this historical path re-exports
that one module object (patches through the bare name reach the single implementation). Running this file as a script re-executes the
canonical module as __main__ with the same argv. Production code must import the canonical name."""
import importlib as _il, os as _os, sys as _sys
try:
    import pgm as _pgm
except ImportError:
    _sys.path.insert(0, _os.path.normpath(_os.path.join(_os.path.dirname(_os.path.abspath(__file__)), '../../..', 'src')))
if __name__ == '__main__':
    import runpy as _rp; _rp.run_module('pgm.algorithms.quotient.check_global', run_name='__main__', alter_sys=True)
else:
    _sys.modules[__name__] = _il.import_module('pgm.algorithms.quotient.check_global')
