"""Bind a research subprocess to the exact package tree named by --code-root.

The supervisor uses the calling harness's environment. The worker starts in
isolated Python mode and imports pgm/research only from the requested checkout.
Historical layouts must use their own restored harness, never an installed pgm.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib
import json
import os
from pathlib import Path
import runpy
import sys


def _target(root, entry):
    root = Path(root).resolve()
    package = root / 'src' / 'pgm'
    if not (package / '__init__.py').is_file():
        raise ValueError('unsupported target layout: expected src/pgm; restore and run the historical packet\'s own harness: ' + str(root))
    entry = Path(entry).resolve()
    if not entry.is_relative_to(root) or not entry.is_file():
        raise ValueError('entry point is absent or outside the requested source root: ' + str(entry))
    if not (entry.is_relative_to(root / 'src') or entry.is_relative_to(root / 'research')):
        raise ValueError('entry point is outside the target src/research trees: ' + str(entry))
    return root, entry


def bound_source_command(root, command):
    """Wrap an explicit Python file command; preserve its arguments and interpreter."""
    if len(command) < 2 or str(command[1]).startswith('-'):
        raise ValueError('target binding requires an explicit Python entry-point file')
    root, entry = _target(root, command[1])
    return [str(command[0]), '-I', str(Path(__file__).resolve()),
            '--root', str(root), '--entry', str(entry), '--', *map(str, command[2:])]


def supervisor_environment(env):
    """Resolve the supervisor from this harness, independently of the worker target."""
    from research.paths import repo_root
    root = repo_root()
    result = dict(env)
    result['PYTHONPATH'] = os.pathsep.join((str(root / 'src'), str(root)))
    for name in ('PYTHONHOME', 'PYTHONSTARTUP'):
        result.pop(name, None)
    return result


def require_local_source(root):
    """In-process policy/generator imports can describe only this checkout."""
    actual = Path(__file__).resolve().parents[1]
    if Path(root).resolve() != actual:
        raise ValueError('in-process manifest source differs from its loaded checkout; run the target checkout\'s own manifest command: ' + str(root))
    return actual


def checked_structural_build(root):
    """Read an already built native artifact, checking its bytes against the target source."""
    from pgm.runtime.resources import native_cache_dir
    owner = Path(root).resolve() / 'src/pgm/algorithms/structural'
    cache = Path(native_cache_dir(owner))
    record = cache / 'cex_build.json'
    binary = cache / 'libcex_kernel.dylib'
    if not record.is_file() or not binary.is_file():
        raise ValueError('native preflight requires the target kernel to be built before freezing: ' + str(cache))
    result = json.loads(record.read_text())
    digest = lambda p: hashlib.sha256(p.read_bytes()).hexdigest()
    if result.get('source_sha256') != digest(owner / 'cex_kernel.cpp'):
        raise ValueError('native cache record belongs to a different target kernel source')
    if result.get('binary_sha256') != digest(binary):
        raise ValueError('native cache binary does not match its checked build record')
    return result


def result_native_build(output):
    """The worker's actual consumed native record, not an unrelated cache's latest record."""
    path = Path(output)
    if not path.is_file():
        return None
    return (json.loads(path.read_text()).get('mechanism') or {}).get('native_build')


def checked_heatbath_build(root):
    """Read optional heat-bath provenance without importing/building the native module."""
    from pgm.runtime.resources import native_cache_dir
    owner = Path(root).resolve() / 'src/pgm/algorithms/response'
    cache = Path(native_cache_dir(owner))
    record = cache / 'heatbath_build.json'
    if not record.is_file():
        return None
    result = json.loads(record.read_text())
    library = result.get('library', '')
    if not library or Path(library).name != library:
        raise ValueError('invalid heat-bath library name in native cache record')
    binary = cache / library
    digest = lambda p: hashlib.sha256(p.read_bytes()).hexdigest()
    if result.get('source_sha256') != digest(owner / 'heatbath_native.c'):
        raise ValueError('heat-bath cache record belongs to a different target source')
    if not binary.is_file() or result.get('binary_sha256') != digest(binary):
        raise ValueError('heat-bath cache binary does not match its checked build record')
    return result


def _assert_origins(root):
    allowed = {'pgm': root / 'src' / 'pgm', 'research': root / 'research'}
    for name, module in tuple(sys.modules.items()):
        prefix = name.partition('.')[0]
        if prefix not in allowed:
            continue
        file = getattr(module, '__file__', None)
        locations = list(getattr(module, '__path__', ()))
        if file:
            locations.append(file)
        if not locations or any(not Path(p).resolve().is_relative_to(allowed[prefix]) for p in locations):
            raise RuntimeError('foreign source imported for %s: %s (target %s)' % (name, locations, allowed[prefix]))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', required=True)
    parser.add_argument('--entry', required=True)
    parser.add_argument('arguments', nargs=argparse.REMAINDER)
    args = parser.parse_args()
    root, entry = _target(args.root, args.entry)
    _assert_origins(root)
    # -I ignores inherited PYTHONPATH/user site; these explicit roots precede any
    # system-installed packages. Third-party dependencies remain available.
    sys.path[:0] = [str(root / 'src'), str(root)]
    importlib.invalidate_caches()
    importlib.import_module('pgm')
    _assert_origins(root)
    arguments = args.arguments[1:] if args.arguments[:1] == ['--'] else args.arguments
    sys.argv = [str(entry), *arguments]
    os.chdir(root)
    try:
        base = root / 'src' if entry.is_relative_to(root / 'src') else root
        module = '.'.join(entry.relative_to(base).with_suffix('').parts)
        runpy.run_module(module, run_name='__main__', alter_sys=True)
    finally:
        _assert_origins(root)


if __name__ == '__main__':
    main()
