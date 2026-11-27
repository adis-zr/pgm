"""DGP10: build the layout in which the CARRIED DGP9 review probes (byte-identical scripts from the packet, plus the four documented interface adaptations) run against a given code root -- path plumbing by two symlinks
(dgp9_review/code/pgm-d1932cf -> CODE_ROOT, dgp9_review/records/DGP9_SPECTRAL_HEATBATH_CONTINUATION -> the restored DGP9 records) and the repaired kernel source copied next to the native probes (they compile the kernel from their own
directory). usage: dgp10_probes_layout.py --packet PKT --code-root ROOT --records-dgp9 DIR --out LAYOUT [--adapted ADAPTED_DIR]  (ADAPTED_DIR = the directory holding the adapted probe copies + ADAPTATIONS.md; default = the packet's originals)"""
import os, sys, shutil, argparse, hashlib, json, glob
def sha(p): return hashlib.sha256(open(p, 'rb').read()).hexdigest()
def main():
    ap = argparse.ArgumentParser(); ap.add_argument('--packet', required=True); ap.add_argument('--code-root', required=True); ap.add_argument('--records-dgp9', required=True); ap.add_argument('--out', required=True); ap.add_argument('--adapted', default=None); a = ap.parse_args()
    out = os.path.abspath(a.out); shutil.rmtree(out, ignore_errors=True); os.makedirs(os.path.join(out, 'dgp9_review', 'code')); os.makedirs(os.path.join(out, 'dgp9_review', 'records'))
    os.symlink(os.path.abspath(a.code_root), os.path.join(out, 'dgp9_review', 'code', 'pgm-d1932cf')); os.symlink(os.path.abspath(a.records_dgp9), os.path.join(out, 'dgp9_review', 'records', 'DGP9_SPECTRAL_HEATBATH_CONTINUATION'))
    inv = {}
    for audit in ('spectral_audit', 'native_audit', 'repair_audit', 'markov_audit', 'records_audit', 'theory_audit'):
        d = os.path.join(out, 'dgp9_review', audit); os.makedirs(d)
        for p in glob.glob(os.path.join(a.packet, 'dgp9_review', audit, '*.py')) + glob.glob(os.path.join(a.packet, 'dgp9_review', audit, '*.uai')):
            src = p
            if a.adapted and os.path.exists(os.path.join(a.adapted, 'dgp9_review', audit, os.path.basename(p))): src = os.path.join(a.adapted, 'dgp9_review', audit, os.path.basename(p))
            shutil.copyfile(src, os.path.join(d, os.path.basename(p))); inv[audit + '/' + os.path.basename(p)] = dict(sha256=sha(src), packet_sha256=sha(p), adapted=(sha(src) != sha(p)))
    shutil.copyfile(os.path.join(a.code_root, 'code', 'cex', 'hp', 'heatbath_native.c'), os.path.join(out, 'dgp9_review', 'native_audit', 'heatbath_native.c')); inv['native_audit/heatbath_native.c'] = dict(sha256=sha(os.path.join(a.code_root, 'code', 'cex', 'hp', 'heatbath_native.c')), source='the code root\'s kernel source (the probes compile from their own directory)')
    if a.adapted and os.path.exists(os.path.join(a.adapted, 'ADAPTATIONS.md')): shutil.copyfile(os.path.join(a.adapted, 'ADAPTATIONS.md'), os.path.join(out, 'ADAPTATIONS.md'))
    json.dump(dict(code_root=os.path.abspath(a.code_root), records_dgp9=os.path.abspath(a.records_dgp9), packet=os.path.abspath(a.packet), files=inv, adapted=[k for k, v in inv.items() if v.get('adapted')]), open(os.path.join(out, 'LAYOUT.json'), 'w'), indent=1); print(json.dumps(dict(files=len(inv), adapted=[k for k, v in inv.items() if v.get('adapted')])))
if __name__ == '__main__': main()
