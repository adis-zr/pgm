"""DGP6 repair (finding 9: reproduction / accounting): packet-relative and explicit-root resolution of input (model / evidence) paths recorded in manifests and cells. A recorded path is used as-is when it exists; otherwise its
tail after the records marker `code/runs/mdi_2026-10-28/` is resolved against (1) the packet's own records root (the directory holding the round's PROTOCOL.md, or its parent `runs/mdi_2026-10-28` when the packet is one round
directory), (2) every root in the environment variable DGP_ROOTS (colon-separated: explicit historical roots such as a restored pgm-records checkout), (3) the configured records root. A path that cannot be resolved raises
InputUnresolved with the candidates tried -- never a silent substitute. The sha256 of the resolved file is checked against the manifest when given."""

# Source-checkout entry point; production imports never traverse research.
if __package__ in (None, ""):
    import sys as _research_sys
    from pathlib import Path as _ResearchPath
    _research_sys.path.insert(0, str(_ResearchPath(__file__).resolve().parents[3]))
from research.bootstrap import activate as _activate_research
_activate_research()
from research.paths import repo_root as _repo_root, runs_root as _runs_root, records_root as _records_root, source_path as _source_path
import os, hashlib
MARKER = 'code/runs/mdi_2026-10-28/'; REPO_MARKER = 'pgm-records/'; DEFAULT_ROOT = str(_runs_root() / 'mdi_2026-10-28')


class InputUnresolved(Exception): pass


def _repo_root_of(p):
    """the records REPOSITORY root above p (the first ancestor holding code/runs), or None"""
    q = os.path.abspath(p)
    for _ in range(10):
        if os.path.isdir(os.path.join(q, 'code', 'runs')): return q
        nq = os.path.dirname(q)
        if nq == q: break
        q = nq
    return None


def roots(records_root=None):
    """the records-tree roots (directories standing for code/runs/mdi_2026-10-28): the packet root, its parent when it is the mdi directory, every DGP_ROOTS entry (and its code/runs/mdi_2026-10-28 when the entry is a repository root), the configured records root"""
    out = []
    if records_root:
        rr = os.path.abspath(records_root); out.append(rr); par = os.path.dirname(rr)
        if os.path.basename(par) == 'mdi_2026-10-28': out.append(par)
    for r in (os.environ.get('DGP_ROOTS') or '').split(':'):
        if r:
            r = os.path.abspath(r); out.append(r); sub = os.path.join(r, 'code', 'runs', 'mdi_2026-10-28')
            if os.path.isdir(sub): out.append(sub)
    out.append(DEFAULT_ROOT); return out


def repo_roots(records_root=None):
    """the records REPOSITORY roots (for inputs recorded outside code/runs/mdi_2026-10-28, e.g. the accepted preservation inputs under docs/): above the packet, above every DGP_ROOTS entry (or the entry itself), above the default root"""
    out = []
    for p in ([records_root] if records_root else []) + [r for r in (os.environ.get('DGP_ROOTS') or '').split(':') if r] + [DEFAULT_ROOT]:
        r0 = _repo_root_of(p)
        if r0 and r0 not in out: out.append(r0)
    return out


def resolve_input(path, records_root=None, sha256=None):
    """-> the existing file path for a recorded input path; raises InputUnresolved listing every candidate tried. Rules in order: the recorded path itself; the tail after code/runs/mdi_2026-10-28/ under every records root (also the
    packet-relative form when the tail starts with the packet's own directory name, and the bare basename); the tail after pgm-records/ under every repository root; the bare basename under every records root"""
    cands = []
    def add(c):
        if os.path.exists(c) and c not in cands: cands.append(c)
    if path and os.path.exists(path): cands.append(path)
    else:
        path = path or ''
        if MARKER in path:
            tail = path.split(MARKER, 1)[1]
            for r in roots(records_root):
                add(os.path.join(r, tail))
                if tail.startswith(os.path.basename(r) + '/'): add(os.path.join(os.path.dirname(r), tail))
        if REPO_MARKER in path:
            tail2 = path.split(REPO_MARKER, 1)[1]
            for r in repo_roots(records_root): add(os.path.join(r, tail2))
        for r in roots(records_root): add(os.path.join(r, os.path.basename(path)))
    for c in cands:
        if sha256 is None or hashlib.sha256(open(c, 'rb').read()).hexdigest() == sha256: return c
    raise InputUnresolved('input %r not resolved (sha256 %s); roots tried %s; repository roots %s; candidates %s' % (path, (sha256 or '')[:12], roots(records_root), repo_roots(records_root), cands))


def relocation_test(manifest_tasks, records_root, fake_prefix='/nonexistent/workstation/pgm-records/code/runs/mdi_2026-10-28/'):
    """rewrite every task path onto a non-existent workstation prefix (the records tail when the path lies under code/runs/mdi_2026-10-28/, the repository tail otherwise) and resolve it back through the packet / DGP_ROOTS: returns the per-task
    result (used by the packet validator and the restored-packet test)"""
    out = []; fake_repo = fake_prefix.split('code/runs/')[0] if 'code/runs/' in fake_prefix else '/nonexistent/workstation/pgm-records/'
    for t in manifest_tasks:
        p = t['model']
        if MARKER in p: fake = fake_prefix + p.split(MARKER, 1)[1]
        elif REPO_MARKER in p: fake = fake_repo + p.split(REPO_MARKER, 1)[1]
        else: fake = fake_prefix + os.path.basename(p)
        try: r = resolve_input(fake, records_root, t.get('model_sha256')); out.append(dict(name=t['name'], fake=fake, resolved=r, ok=True))
        except InputUnresolved as e: out.append(dict(name=t['name'], fake=fake, ok=False, error=str(e)[:300]))
    return out
