"""Package the PAC EMPIRICAL PASS deliverable (07 RETURN CONTRACT): candidate source (cex/pac, cex/newarm, cex/b0_frozen_v14, the unchanged supervisor), the complete run
directory (manifest, ledger, every cell receipt + worker output + attempt logs, qualification, reports, reference audit), the received handoff identity, the inventory of raw
inputs by hash (raw inputs themselves are NOT redistributed), the proof-to-code map; an integrity record outside the archive; the packaging job's receipt as a sidecar.
Excludes binaries / caches / __pycache__ (rebuild from source with the recorded flags) and the per-comparator snapshot MAR copies (their final output.MAR is kept).
    python cex/pac/package.py <RD> <OUT.zip>"""
import os, sys, json, time, hashlib, zipfile, tempfile, subprocess
HERE = os.path.dirname(os.path.abspath(__file__)); CODE = os.path.dirname(os.path.dirname(HERE)); DOCS = os.path.join(os.path.dirname(CODE), 'docs')
SKIP_DIRS = ('__pycache__', 'native_cache'); SKIP_SUFFIX = ('.dylib', '.so', '.pyc')


def sha(p):
    h = hashlib.sha256()
    with open(p, 'rb') as f:
        for b in iter(lambda: f.read(1 << 20), b''): h.update(b)
    return h.hexdigest()


def main(RD, out):
    RD = os.path.abspath(RD); out = os.path.abspath(out)
    if os.path.exists(out): raise SystemExit('refuse: %s exists' % out)
    hashes = {}; n = 0
    with zipfile.ZipFile(out, 'w', zipfile.ZIP_DEFLATED) as z:
        def add(path, arc):
            nonlocal n
            z.write(path, arc); hashes[arc] = sha(path); n += 1
        def add_tree(root, arcroot, skip=lambda p: False):
            for dp, dns, fns in os.walk(root):
                dns[:] = sorted(d for d in dns if d not in SKIP_DIRS)
                for fn in sorted(fns):
                    p = os.path.join(dp, fn)
                    if fn.endswith(SKIP_SUFFIX) or skip(p): continue
                    add(p, os.path.join(arcroot, os.path.relpath(p, root)))
        for d in ('pac', 'newarm', 'b0_frozen_v14'): add_tree(os.path.join(CODE, 'cex', d), 'code/cex/' + d)
        add(os.path.join(CODE, 'gbidi', 'supervise.py'), 'code/gbidi/supervise.py'); add(os.path.join(CODE, 'bench', 'cells.py'), 'code/bench/cells.py'); add(os.path.join(CODE, 'bench', 'pgmax_mar.py'), 'code/bench/pgmax_mar.py'); add(os.path.join(CODE, 'bench', 'libdai', 'libdai_mar.cpp'), 'code/bench/libdai/libdai_mar.cpp'); add(os.path.join(CODE, 'ext', 'comparator', 'merlin_adapter.py'), 'code/ext/comparator/merlin_adapter.py'); add(os.path.join(CODE, 'ext', 'comparator', 'MERLIN_PIN.json'), 'code/ext/comparator/MERLIN_PIN.json'); add(os.path.join(CODE, 'ext', 'uai.py'), 'code/ext/uai.py')
        add_tree(RD, 'run_dir/' + os.path.basename(RD), skip=lambda p: os.path.basename(p).startswith('snapshot_') or '/dev' in p.replace(RD, '') and 'PAC_LEDGER' not in p and 'MANIFEST' not in p)
        H = os.path.join(DOCS, 'handoff-received-2026-11-12-pac-empirical')
        for f in ('CLAUDE_PAC_IMPLEMENT_AND_FULL_BENCHMARK_PROMPT.txt', 'RECEIVED_SHA256.txt'): add(os.path.join(H, f), 'received/' + f)
        for f in os.listdir(os.path.join(H, 'PAC_EMPIRICAL_HANDOFF_2026-11-12')):
            p = os.path.join(H, 'PAC_EMPIRICAL_HANDOFF_2026-11-12', f)
            if os.path.isfile(p) and f.endswith(('.txt', '.json')): add(p, 'received/PAC_EMPIRICAL_HANDOFF_2026-11-12/' + f)
        git = subprocess.run(['git', '-C', CODE, 'rev-parse', 'HEAD'], capture_output=True, text=True).stdout.strip(); branch = subprocess.run(['git', '-C', CODE, 'branch', '--show-current'], capture_output=True, text=True).stdout.strip()
        z.writestr('MEMBER_SHA256.json', json.dumps({'git_head_at_packaging': git, 'branch': branch, 'members': hashes}, indent=1, sort_keys=True))
    with zipfile.ZipFile(out) as z: bad = z.testzip(); names = z.namelist()
    tmp = tempfile.mkdtemp(prefix='pac_pkg_')
    with zipfile.ZipFile(out) as z: z.extractall(tmp)
    ok = all(sha(os.path.join(tmp, a)) == h for a, h in hashes.items())
    rec = {'zip': out, 'bytes': os.path.getsize(out), 'sha256': sha(out), 'members': n + 1, 'namelist': len(names), 'testzip_first_bad': bad, 'extraction_member_hashes_verified': ok, 'utc': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()), 'git_head_at_packaging': git, 'branch': branch, 'excluded': 'binaries / native caches / __pycache__ (rebuild from source with cex_build.json flags); comparator checkpoint snapshot MAR copies; development-campaign cell directories (their ledgers and manifests are included); raw benchmark inputs (identities in CAMPAIGN_MANIFEST.json inventory)'}
    json.dump(rec, open(os.path.join(RD, 'PACKAGE_RECORD_PAC.json'), 'w'), indent=1); json.dump(rec, open(out + '.integrity.json', 'w'), indent=1); print(json.dumps(rec, indent=1))


if __name__ == '__main__': main(sys.argv[1], sys.argv[2])
