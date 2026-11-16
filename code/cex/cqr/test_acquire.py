"""Determinism test: re-derive the UAI 2022 and MC 2024 selections from the inventories (pure functions of the
inventory rows + SALT) and assert they match the committed SELECTION files slot by slot.  Also re-checks a few
inventory invariants that the selection relies on (stratum labels, family rule, salted order).  No inference."""
import json, os, sys
HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, HERE)
import acquire

KEYS_UAI = ('slot', 'status', 'name', 'family', 'byte_sha256', 'evidence_sha256', 'bucket', 'median_bytes', 'candidates')
KEYS_MC = ('slot', 'status', 'name', 'family', 'cnf_sha256', 'bucket', 'median_bytes', 'candidates', 'source_pool', 'odd_index')


def check(sel_path, inv_path, fn, keys):
    sel = json.load(open(sel_path)); inv = json.load(open(inv_path))
    rows = fn(inv); assert len(rows) == len(sel['slots']) == sel['target'], (len(rows), len(sel['slots']), sel['target'])
    for a, b in zip(rows, sel['slots']):
        for k in keys:
            assert a.get(k) == b.get(k), (a['slot'], k, a.get(k), b.get(k))
    n_sel = sum(1 for r in rows if r['status'] == 'SELECTED'); assert n_sel == sel['selected'], (n_sel, sel['selected'])
    return n_sel, len(rows)


def main():
    E = acquire.EXT
    inv = json.load(open(os.path.join(E, 'UAI2022_FINAL_MAR_INVENTORY.json')))
    for m in inv['models']:
        assert m['stratum'] == '|'.join(acquire.stratum_of(m)), m['name']
        assert m['family'] == acquire.family_of(m['name']), (m['name'], m['family'])
        assert acquire.salted(m['byte_sha256']) == acquire.hashlib.sha256((acquire.SALT + '|' + m['byte_sha256']).encode()).hexdigest()
    sel_fam = {}
    u = check(os.path.join(E, 'UAI2022_SELECTION.json'), os.path.join(E, 'UAI2022_FINAL_MAR_INVENTORY.json'), acquire.select_uai, KEYS_UAI)
    for s in json.load(open(os.path.join(E, 'UAI2022_SELECTION.json')))['slots']:
        if s['status'] == 'SELECTED':
            sel_fam[s['family']] = sel_fam.get(s['family'], 0) + 1
            mp_ = s['model_path'] if os.path.exists(s['model_path']) else os.path.join(E, 'uai2022_mar', os.path.basename(s['model_path']))     # the selection recorded the pre-split worktree path; the bytes are verified by sha256 below
            assert os.path.exists(mp_) and os.path.exists(mp_ + '.evid'), s['name']
            assert acquire.sha256_file(mp_)[0] == s['byte_sha256'], s['name']
    assert all(v <= 2 for v in sel_fam.values()), sel_fam
    print('UAI2022 selection re-derived: %d selected of %d slots; families %s' % (u[0], u[1], sel_fam))
    mp = os.path.join(E, 'MC2024_SELECTION.json')
    if os.path.exists(mp):
        m = check(mp, os.path.join(E, 'MC2024_TRACK2_INVENTORY.json'), acquire.select_mc, KEYS_MC)
        fam = {}
        for s in json.load(open(mp))['slots']:
            if s['status'] == 'SELECTED':
                fam[s['family']] = fam.get(s['family'], 0) + 1
                # the raw .cnf.xz archives are not kept in the records tree (LARGE_FILES_NOT_INCLUDED; re-derivable from DOWNLOADS.json): the converted UAI with its conversion sidecar must then exist
                conv = os.path.join(E, 'wmc_uai', s['name'] + '.uai'); assert os.path.exists(s['cnf_xz_path']) or os.path.exists(conv + '.conversion.json'), s['name']       # the two largest converted UAI files (> 8 MiB) are themselves listed-not-included; the sidecar carries their sha256
        assert all(v <= 2 for v in fam.values()), fam
        print('MC2024 selection re-derived: %d selected of %d slots; %d distinct family rows' % (m[0], m[1], len(fam)))
    else:
        print('MC2024_SELECTION.json not present yet')
    print('DETERMINISM_OK')


if __name__ == '__main__':
    main()
