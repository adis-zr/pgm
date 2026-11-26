"""DGP6 repair (finding 9: reproduction / accounting): packet-relative and explicit-root resolution of input (model / evidence) paths recorded in manifests and cells. A recorded path is used as-is when it exists; otherwise its
tail after the records marker `code/runs/mdi_2026-10-28/` is resolved against (1) the packet's own records root (the directory holding the round's PROTOCOL.md, or its parent `runs/mdi_2026-10-28` when the packet is one round
directory), (2) every root in the environment variable DGP_ROOTS (colon-separated: explicit historical roots such as a restored pgm-records checkout), (3) the default workstation root. A path that cannot be resolved raises
InputUnresolved with the candidates tried -- never a silent substitute. The sha256 of the resolved file is checked against the manifest when given."""
import os, hashlib
MARKER = 'code/runs/mdi_2026-10-28/'; DEFAULT_ROOT = '/Users/adis/Workspace/pgm-records/code/runs/mdi_2026-10-28'


class InputUnresolved(Exception): pass


def roots(records_root=None):
    out = []
    if records_root:
        rr = os.path.abspath(records_root); out.append(rr); par = os.path.dirname(rr)
        if os.path.basename(par) == 'mdi_2026-10-28': out.append(par)
    for r in (os.environ.get('DGP_ROOTS') or '').split(':'):
        if r: out.append(os.path.abspath(r))
    out.append(DEFAULT_ROOT); return out


def resolve_input(path, records_root=None, sha256=None):
    """-> the existing file path for a recorded input path; raises InputUnresolved listing every candidate tried"""
    cands = []
    if path and os.path.exists(path): cands.append(path)
    else:
        tail = path.split(MARKER, 1)[1] if MARKER in (path or '') else os.path.basename(path or '')
        for r in roots(records_root):
            for c in (os.path.join(r, tail), os.path.join(r, os.path.basename(tail))):
                if os.path.exists(c) and c not in cands: cands.append(c)
    for c in cands:
        if sha256 is None or hashlib.sha256(open(c, 'rb').read()).hexdigest() == sha256: return c
    raise InputUnresolved('input %r not resolved (sha256 %s); roots tried %s; candidates %s' % (path, (sha256 or '')[:12], roots(records_root), cands))


def relocation_test(manifest_tasks, records_root, fake_prefix='/nonexistent/workstation/pgm-records/code/runs/mdi_2026-10-28/'):
    """rewrite every task path onto a non-existent workstation prefix and resolve it back through the packet / DGP_ROOTS: returns the per-task result (used by the packet validator and the restored-packet test)"""
    out = []
    for t in manifest_tasks:
        tail = t['model'].split(MARKER, 1)[1] if MARKER in t['model'] else os.path.basename(t['model']); fake = fake_prefix + tail
        try: p = resolve_input(fake, records_root, t.get('model_sha256')); out.append(dict(name=t['name'], resolved=p, ok=True))
        except InputUnresolved as e: out.append(dict(name=t['name'], ok=False, error=str(e)[:200]))
    return out
