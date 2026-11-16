"""Frozen identity of EVERY natively loaded artifact (binaries + build records) the campaign dispatcher can launch (stdlib only).

Closes review finding CQR-09 (16 Nov 2026): the previous check (campaign.kernel_identity_failures) compared only the cex kernel binary with the
`binary_sha256` field of its build record, so replacing BOTH the binary and the record after the freeze (consistent with each other, source hash
unchanged) passed, and the stream kernels / h4 executables / libDAI comparator were not covered at all. Here the manifest freezes, per artifact:

    binary_path, binary_sha256            the bytes actually dlopen'ed / exec'ed
    record_path, record_sha256            the build-record FILE bytes (not just a field of it)
    record_binary_sha256                  the record's own claim about the binary (must equal binary_sha256)
    loader                                the module that loads the artifact

and `failures_vs_frozen` requires, for every tag some planned arm needs, current == frozen on binary AND record file AND inner consistency.
Rebuilds under a frozen identity are prohibited by the dispatcher (cex/cqr/campaign.py re-collects before and after every native cell).

The CQR arms (N1_CQR / G0_CQR / N1_NO_*) load NOTHING native (pure Python + mpmath); this module reports that as an empty requirement.
"""
import os, sys, json, hashlib, importlib.util

# tag -> (binary relative to code dir, record relative to code dir or None, loader relative to code dir)
ARTIFACTS = {
    'newarm_cex':            ('cex/newarm/libcex_kernel.dylib',        'cex/newarm/cex_build.json',           'cex/newarm/cex_executor.py'),
    'newarm_stream':         ('cex/newarm/libstream_kernel.so',        'cex/newarm/stream_build.json',        'cex/newarm/stream_float.py'),
    'b0_frozen_v14_cex':     ('cex/b0_frozen_v14/libcex_kernel.dylib', 'cex/b0_frozen_v14/cex_build.json',    'cex/b0_frozen_v14/cex_executor.py'),
    'b0_frozen_v14_stream':  ('cex/b0_frozen_v14/libstream_kernel.so', 'cex/b0_frozen_v14/stream_build.json', 'cex/b0_frozen_v14/stream_float.py'),
    'h4rect':                ('build/h4rect',                          None,                                  'h4a/arm.py'),
    'h4point':               ('build/h4point',                         None,                                  'h4a/arm.py'),
    'h4pcheck':              ('build/h4pcheck',                        None,                                  'h4a/arm.py'),
    'libdai_mar':            ('bench/libdai/libdai_mar',               None,                                  'bench/cells.py (cell_libdai: arms LIBDAI_EXACT and LBP)'),
    'merlin':                ('__MERLIN__',                            'ext/comparator/MERLIN_PIN.json',      'ext/comparator/merlin_adapter.py (MERLIN_CTE) and bench/cells.py (cell_merlin_ladder: WMB, IJGP)'),
    'pgmax_python':          ('.venv-pgmax/bin/python',                None,                                  'bench/cells.py (cell_pgmax: PGMAX_SUMPRODUCT_BP; the interpreter of the JAX/pgmax environment)'),
}
GROUPS = {'newarm': ('newarm_cex', 'newarm_stream'), 'b0_frozen_v14': ('b0_frozen_v14_cex', 'b0_frozen_v14_stream'),
          'h4': ('h4rect', 'h4point', 'h4pcheck'), 'libdai': ('libdai_mar',), 'merlin': ('merlin',), 'pgmax': ('pgmax_python',)}
# ARM -> EXECUTED ARTIFACTS, derived from the adapters' actual command lines (second review R4): cex/cqr/campaign.py run() routes every comparator arm to
# cex/pac/comparator_cell.py, whose ARMS table maps LIBDAI_EXACT -> bench/cells.py cell_libdai(JTREE) and LBP -> cell_libdai(BP) -- BOTH execute bench/libdai/libdai_mar;
# WMB / IJGP -> cell_merlin_ladder (the Merlin executable bench/cells.MERLIN); MERLIN_CTE -> ext/comparator/merlin_adapter.run_cell (the executable named by MERLIN_PIN.json;
# the two paths are compared by `merlin_paths`); PGMAX_SUMPRODUCT_BP -> cell_pgmax under the .venv-pgmax interpreter.
COMPARATOR_EXECUTABLES = {'LIBDAI_EXACT': ('libdai',), 'LBP': ('libdai',), 'WMB': ('merlin',), 'IJGP': ('merlin',), 'MERLIN_CTE': ('merlin',), 'PGMAX_SUMPRODUCT_BP': ('pgmax',)}
COMPARATOR_ARMS = tuple(COMPARATOR_EXECUTABLES)


def merlin_paths(code_dir):
    """(adapter pin path, bench/cells.py MERLIN constant) -- both must name the same executable; the collection records both"""
    pin = None; cells = None
    try: pin = os.path.expanduser(json.load(open(os.path.join(code_dir, 'ext', 'comparator', 'MERLIN_PIN.json')))['binary']['path'])
    except Exception: pass
    try:
        for line in open(os.path.join(code_dir, 'bench', 'cells.py')):
            if line.startswith('MERLIN = '): cells = line.split('=', 1)[1].strip().strip('"').strip("'"); break
    except Exception: pass
    return pin, cells

B0_ARM = 'B0_FROZEN_V14'
H4_PREFIX = 'H4_NATIVE_'
VERSION = 'kernel_identity_v1 (2026-11-16)'


def sha256_file(p):
    if not p or not os.path.isfile(p): return None
    h = hashlib.sha256()
    with open(p, 'rb') as f:
        for b in iter(lambda: f.read(1 << 20), b''): h.update(b)
    return h.hexdigest()


def _record_inner(p):
    if not p or not os.path.isfile(p): return None
    try:
        d = json.load(open(p))
    except Exception:
        return None
    if not isinstance(d, dict): return None
    if isinstance(d.get('binary'), dict) and d['binary'].get('sha256'): return d['binary']['sha256']       # MERLIN_PIN.json shape
    return d.get('binary_sha256')


def collect(code_dir, artifacts=None):
    """identity of every natively loaded artifact under code_dir (absent files -> None hashes; never raises on absence)"""
    code_dir = os.path.abspath(code_dir); out = {}
    for tag, (binrel, recrel, loader) in (artifacts or ARTIFACTS).items():
        if binrel == '__MERLIN__':
            pin_p, cells_p = merlin_paths(code_dir); bp = pin_p or cells_p or ''; binrel = bp
        else: bp = binrel if os.path.isabs(binrel) else os.path.join(code_dir, binrel)
        rp = os.path.join(code_dir, recrel) if recrel else None
        out[tag] = dict(binary_path=binrel, binary_sha256=sha256_file(bp), record_path=recrel, record_sha256=sha256_file(rp) if rp else None,
                        record_binary_sha256=_record_inner(rp) if rp else None, loader=loader)
        if tag == 'merlin':
            pin_p, cells_p = merlin_paths(code_dir); out[tag]['adapter_paths'] = dict(pin=pin_p, cells=cells_p, consistent=(pin_p == cells_p))
            if cells_p and cells_p != pin_p: out[tag]['cells_binary_sha256'] = sha256_file(cells_p)
    return out


def pac_candidate_arms():
    """the baseline PAC candidate arms (cex/pac/registry.py CANDIDATE_ARMS); reuse an already-bound baseline registry when the caller imported it"""
    m = sys.modules.get('registry')
    if m is not None and hasattr(m, 'CANDIDATE_ARMS'): return tuple(m.CANDIDATE_ARMS)
    m = sys.modules.get('pac_registry_ki')
    if m is None:
        here = os.path.dirname(os.path.abspath(__file__)); p = os.path.join(os.path.dirname(here), 'pac', 'registry.py')
        spec = importlib.util.spec_from_file_location('pac_registry_ki', p); m = importlib.util.module_from_spec(spec); sys.modules['pac_registry_ki'] = m; spec.loader.exec_module(m)
    return tuple(m.CANDIDATE_ARMS)


def tags_needed_by(arm, pac_arms=None):
    """which artifact tags an arm's worker loads; CQR arms (N1_CQR, G0_CQR, N1_NO_*) -> ()"""
    if arm == B0_ARM: return GROUPS['b0_frozen_v14']
    if arm.startswith(H4_PREFIX): return GROUPS['h4']
    if arm in COMPARATOR_EXECUTABLES: return tuple(t for g in COMPARATOR_EXECUTABLES[arm] for t in GROUPS[g])
    if arm in (pac_arms if pac_arms is not None else pac_candidate_arms()): return GROUPS['newarm']
    return ()


def arms_needing(tag, registered_arms=None, pac_arms=None):
    """the registered arms that load `tag`; registered_arms defaults to the baseline candidate arms + B0 + libDAI + the H4 native arm prefix"""
    pac_arms = tuple(pac_arms if pac_arms is not None else pac_candidate_arms())
    arms = list(registered_arms) if registered_arms is not None else list(pac_arms) + [B0_ARM, H4_PREFIX + '*'] + list(COMPARATOR_ARMS)
    return [a for a in arms if tag in tags_needed_by(a, pac_arms)]


def needed_tags(planned_arms, pac_arms=None):
    pac_arms = tuple(pac_arms if pac_arms is not None else pac_candidate_arms()); need = {}
    for a in planned_arms:
        for t in tags_needed_by(a, pac_arms): need.setdefault(t, []).append(a)
    return need


def failures_vs_frozen(frozen, current, planned_arms, pac_arms=None):
    """distinct messages per failure mode, for every tag some planned arm needs:
       FROZEN_ABSENT (manifest has no identity for the tag) / BINARY_ABSENT / BINARY_CHANGED / RECORD_ABSENT / RECORD_CHANGED / RECORD_INCONSISTENT (inner binary_sha256 != binary)"""
    fails = []; frozen = frozen or {}; current = current or {}
    for tag, arms in sorted(needed_tags(planned_arms, pac_arms).items()):
        f = frozen.get(tag); c = current.get(tag) or {}; who = ','.join(sorted(set(arms)))
        if not f: fails.append('%s: FROZEN_ABSENT the manifest carries no frozen identity for %s (needed by %s)' % (tag, tag, who)); continue
        if tag == 'merlin':
            # BOTH adapter bindings (MERLIN_PIN.json for MERLIN_CTE; bench/cells.MERLIN for WMB / IJGP) must name the SAME executable, at freeze and at every later check;
            # an inconsistent configuration is refused outright (third review CQR-R2-05) and the executable each adapter actually runs is compared
            fa = f.get('adapter_paths') or {}; ca = c.get('adapter_paths') or {}
            if not fa or not fa.get('consistent'): fails.append('merlin: ADAPTER_PATHS_INCONSISTENT at freeze (pin %s vs bench/cells %s): an inconsistent Merlin binding never freezes (needed by %s)' % (fa.get('pin'), fa.get('cells'), who)); continue
            if not ca or not ca.get('consistent') or ca.get('pin') != fa.get('pin') or ca.get('cells') != fa.get('cells'): fails.append('merlin: ADAPTER_PATHS_CHANGED the adapter bindings now are pin %s / bench/cells %s, frozen %s (needed by %s)' % (ca.get('pin'), ca.get('cells'), fa.get('pin'), who))
            if c.get('cells_binary_sha256') is not None and c.get('cells_binary_sha256') != f.get('binary_sha256'): fails.append('merlin: BINARY_CHANGED the bench/cells executable %s is %s, frozen %s' % (ca.get('cells'), c['cells_binary_sha256'][:12], str(f.get('binary_sha256'))[:12]))
        if f.get('binary_sha256') is None: fails.append('%s: FROZEN_ABSENT the frozen identity records no binary for %s (%s absent at freeze; needed by %s)' % (tag, tag, f.get('binary_path'), who)); continue
        if c.get('binary_sha256') is None: fails.append('%s: BINARY_ABSENT %s is missing on disk (frozen %s; needed by %s)' % (tag, f.get('binary_path'), f['binary_sha256'][:12], who))
        elif c['binary_sha256'] != f['binary_sha256']: fails.append('%s: BINARY_CHANGED %s is %s, frozen %s (needed by %s)' % (tag, f.get('binary_path'), c['binary_sha256'][:12], f['binary_sha256'][:12], who))
        if f.get('record_path'):
            if f.get('record_sha256') is None: fails.append('%s: FROZEN_ABSENT the frozen identity records no build record for %s (%s absent at freeze)' % (tag, tag, f['record_path']))
            elif c.get('record_sha256') is None: fails.append('%s: RECORD_ABSENT build record %s is missing on disk (frozen %s)' % (tag, f['record_path'], f['record_sha256'][:12]))
            elif c['record_sha256'] != f['record_sha256']: fails.append('%s: RECORD_CHANGED build record %s is %s, frozen %s (a rebuilt or rewritten record; source hashes are not consulted)' % (tag, f['record_path'], c['record_sha256'][:12], f['record_sha256'][:12]))
            if c.get('binary_sha256') is not None and c.get('record_binary_sha256') != c.get('binary_sha256'):
                fails.append('%s: RECORD_INCONSISTENT the record %s claims binary %s but %s is %s' % (tag, f['record_path'], str(c.get('record_binary_sha256'))[:12], f.get('binary_path'), c['binary_sha256'][:12]))
            if f.get('record_binary_sha256') != f.get('binary_sha256'):
                fails.append('%s: FROZEN_INCONSISTENT the frozen record claims binary %s but the frozen binary is %s' % (tag, str(f.get('record_binary_sha256'))[:12], f['binary_sha256'][:12]))
    return fails


def _walk(o, path=''):
    if isinstance(o, dict):
        if 'loaded_binary_path' in o and 'binary_sha256' in o: yield path, o
        for k, v in o.items(): yield from _walk(v, path + '/' + str(k))
    elif isinstance(o, list):
        for i, v in enumerate(o): yield from _walk(v, '%s[%d]' % (path, i))


def _tag_of_loaded(path, group, frozen=None, sha=None):
    """the loaders dlopen a HASH-ADDRESSED copy (cex_executor.load: native_cache/cex_<sha256>.dylib; stream_float: native_cache/stream_<sha256>.so) of the pinned binary,
    so the recorded loaded_binary_path names the kernel by its kind prefix and its digest; the kind decides the tag, the digest is compared by receipt_failures"""
    b = os.path.basename(str(path))
    if 'libcex_kernel' in b or b.startswith('cex_'): return group + '_cex'
    if 'libstream_kernel' in b or b.startswith('stream_'): return group + '_stream'
    # last resort: an exact digest match against a frozen binary of the group identifies the kind
    for tag in (group + '_cex', group + '_stream'):
        if sha and (frozen or {}).get(tag, {}).get('binary_sha256') == sha: return tag
    return None


def receipt_failures(frozen, worker_output_json, arm, pac_arms=None):
    """the loader stamps the build provenance it actually dlopen'ed (cex_executor.py / stream_float.py: {'binary_sha256', 'loaded_binary_path', 'schedule_id'}; carried inside the
    worker output under certificate['build'] or stats/components[...]['build']); every such record must name a frozen binary of the arm's kernel group. Arms loading
    nothing native -> []. A worker output with no provenance record (stopped before loading) is not a failure here (the disk check before/after the cell covers rebuilds)."""
    tags = tags_needed_by(arm, pac_arms)
    if not tags: return []
    group = 'newarm' if tags == GROUPS['newarm'] else ('b0_frozen_v14' if tags == GROUPS['b0_frozen_v14'] else None)
    if group is None: return []                                   # h4 / libDAI executables are exec'ed, not dlopen'ed: no loader provenance exists in their outputs
    fails = []; frozen = frozen or {}
    for path, prov in _walk(worker_output_json or {}):
        tag = _tag_of_loaded(prov.get('loaded_binary_path'), group, frozen, prov.get('binary_sha256'))
        if tag is None: fails.append('%s: the worker loaded an unrecognised native binary %s (at %s)' % (arm, prov.get('loaded_binary_path'), path)); continue
        f = frozen.get(tag) or {}
        if f.get('binary_sha256') is None: fails.append('%s: no frozen identity for %s but the worker loaded it (at %s)' % (arm, tag, path)); continue
        if prov.get('binary_sha256') != f['binary_sha256']: fails.append('%s: the worker loaded %s with sha256 %s, frozen %s (at %s)' % (arm, tag, str(prov.get('binary_sha256'))[:12], f['binary_sha256'][:12], path))
    return fails


def diff(a, b):
    """tags whose identity differs between two collections (any field)"""
    return sorted(t for t in set(a or {}) | set(b or {}) if (a or {}).get(t) != (b or {}).get(t))


if __name__ == '__main__':
    code = sys.argv[1] if len(sys.argv) > 1 else os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    print(json.dumps(collect(code), indent=1))
