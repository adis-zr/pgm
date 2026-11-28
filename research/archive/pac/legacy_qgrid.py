"""qgrid (QG) POSITIVE rational grid generator -- reconstructed from the retained historical definition (docs/handoff/historical/v4/experiments/QGRID_REPRODUCTION.md §1;
theory 03_weak_and_query_specific.md Theorem WQ6 / QG09). Review F07 of 13 Nov 2026: the previous manifest excluded this cohort as "signed factors (negative entries)";
that was FALSE -- every table is positive: attractive edge (q,1,1,q), repulsive edge (1,q,q,1), positive field (1,v), negative field (v,1). "Signed" refers to the
coupling SIGN chosen by a hash, not to negative weights. (The repository's dq/ package is a DIFFERENT historical suite: the signed-EXPONENTIAL chain pilot with
irrational loadings; it is reconciled separately.)
Generator (exact ASCII hash rules; verified against the two published checkpoints): for seed s, SHA-256 of 'qgrid-v1|s|edge|r1|c1|r2|c2' (endpoints in lexicographic
coordinate order) -> even = attractive, odd = repulsive; 'qgrid-v1|s|field|r|c' -> even = (1,v), odd = (v,1); 'qgrid-v1|s|pin-order|r|c' and 'qgrid-v1|s|pin-value|r|c'
for the sparse-pin evidence (even = +1 -> state 1, odd = -1 -> state 0). Spin order (-1,+1) = states (0,1); pair-table order (--,-+,+-,++). Vertex ID = r*W + c.
Tasks (historical): corner / centre singletons (COVERED by the all-singleton UAI task), adjacent / far-pair / block JOINT laws, influence, parities (NOT singleton tasks:
typed UNSUPPORTED_TASK_ADAPTER for the primary arms; recorded, never converted). The historical native methods (moment LPs, checkerboard oracle, window transfer) exist
only as prose in the handoff; no executable specialist is recoverable (UNAVAILABLE_BACKEND, concrete reason recorded).
    python cex/pac/legacy_qgrid.py <out_dir>        -> writes the registered instances as UAI files + QGRID_INVENTORY.json (hashes, checkpoints)"""
import sys, os, json, hashlib
from fractions import Fraction as F


def H(text): return int.from_bytes(hashlib.sha256(text.encode('ascii')).digest(), 'big')


def grid_model(L, q, v, seed, H_=None, W=None):
    """open H x W grid (default L x L); returns dict(cards, factors(scope, values as Fractions), evidence={}) in UAI variable order r*W+c"""
    Hh = H_ or L; W = W or L; q = F(q); v = F(v); n = Hh * W; vid = lambda r, c: r * W + c; factors = []
    edges = []
    for r in range(Hh):
        for c in range(W):
            if c + 1 < W: edges.append(((r, c), (r, c + 1)))
            if r + 1 < Hh: edges.append(((r, c), (r + 1, c)))
    edges.sort(key=lambda e: (vid(*e[0]), vid(*e[1])))
    signs = []
    for (r1, c1), (r2, c2) in edges:
        h = H('qgrid-v1|%d|edge|%d|%d|%d|%d' % (seed, r1, c1, r2, c2)); attractive = (h % 2 == 0); signs.append('A' if attractive else 'R')
        factors.append(dict(scope=(vid(r1, c1), vid(r2, c2)), values=[q, F(1), F(1), q] if attractive else [F(1), q, q, F(1)]))
    fsigns = []
    if v != 1:
        for r in range(Hh):
            for c in range(W):
                h = H('qgrid-v1|%d|field|%d|%d' % (seed, r, c)); pos = (h % 2 == 0); fsigns.append('+' if pos else '-')
                factors.append(dict(scope=(vid(r, c),), values=[F(1), v] if pos else [v, F(1)]))
    return dict(cards=[2] * n, factors=factors, evidence={}), dict(edges=edges, edge_signs=signs, field_signs=fsigns)


def sparse_pins(L, seed, protect):
    """sort unprotected vertices by (pin-order hash, ID), take floor(L^2/16), value by the pin-value hash (even +1 -> state 1)"""
    W = L; vid = lambda r, c: r * W + c; cand = [(H('qgrid-v1|%d|pin-order|%d|%d' % (seed, r, c)), vid(r, c), r, c) for r in range(L) for c in range(L) if (r, c) not in protect]
    cand.sort(); k = (L * L) // 16; out = []
    for _, i, r, c in cand[:k]:
        out.append(((r, c), 1 if H('qgrid-v1|%d|pin-value|%d|%d' % (seed, r, c)) % 2 == 0 else 0))
    return out


def checkpoints():
    """the two published generator checkpoints (QGRID_REPRODUCTION.md): first five sorted edges and first five row-major field signs of a 16 x 16 grid, seeds 0 and 1"""
    out = {}
    for seed in (0, 1):
        _, meta = grid_model(16, F(3), F(11, 10), seed)
        out[seed] = dict(first_edges=[(e[0], e[1]) for e in meta['edges'][:5]], edge_signs=meta['edge_signs'][:5], field_signs=meta['field_signs'][:5])
    expected = {0: (['A', 'R', 'R', 'A', 'A'], ['-', '+', '-', '-', '-']), 1: (['A', 'A', 'A', 'A', 'R'], ['+', '+', '-', '+', '+'])}
    ok = all(out[s]['edge_signs'] == expected[s][0] and out[s]['field_signs'] == expected[s][1] for s in (0, 1)) and out[0]['first_edges'] == [((0, 0), (0, 1)), ((0, 0), (1, 0)), ((0, 1), (0, 2)), ((0, 1), (1, 1)), ((0, 2), (0, 3))]
    return ok, out


def write_uai(m, path):
    """exact integer-scaled UAI export + explicit empty-evidence file (cex/pac/uai_export.py); returns the export record"""
    import os as _os, sys as _sys; _sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))
    import uai_export
    return uai_export.write_uai(m, path)


# the registered historical instances (QGRID_REPRODUCTION.md §2-3; 05_INVENTORY_AUDIT): principal 16x16 q=3 v=11/10 seeds 0,1; main screen L in {8,16,32}, q in {3/2,3,9}, v=11/10, seeds 0,1; strips; tiny grids; zero-field planar squares
REGISTERED = (
    [dict(name='qgrid_L16_q3_v11-10_s%d' % s, L=16, q=F(3), v=F(11, 10), seed=s, role='principal (centre (8,8) singleton; radius panels)') for s in (0, 1)]
    + [dict(name='qgrid_L%d_q%s_v11-10_s%d' % (L, str(q).replace('/', '-'), s), L=L, q=q, v=F(11, 10), seed=s, role='main screen') for L in (8, 16, 32) for q in (F(3, 2), F(3), F(9)) for s in (0, 1) if not (L == 16 and q == 3)]
    + [dict(name='qgrid_strip_H32_W%d_q3_v11-10_s0' % W, L=None, H=32, W=W, q=F(3), v=F(11, 10), seed=0, role='strip control') for W in (4, 6, 8)]
    + [dict(name='qgrid_tiny_L%d_q%s_v%s_s0' % (L, str(q).replace('/', '-'), str(v).replace('/', '-')), L=L, q=q, v=v, seed=0, role='tiny grid control') for L in (2, 3) for q in (F(3, 2), F(3), F(9)) for v in (F(1), F(11, 10))]
    + [dict(name='qgrid_tiny_L4_q3_v11-10_s0', L=4, q=F(3), v=F(11, 10), seed=0, role='tiny grid control')]
    + [dict(name='qgrid_zerofield_L%d_q3_v1_s0' % L, L=L, q=F(3), v=F(1), seed=0, role='zero-field planar square control') for L in (8, 16, 32)])


def main(out_dir):
    os.makedirs(out_dir, exist_ok=True); ok, cp = checkpoints(); inv = []
    for spec in REGISTERED:
        if spec.get('L') is not None: m, meta = grid_model(spec['L'], spec['q'], spec['v'], spec['seed'])
        else: m, meta = grid_model(None, spec['q'], spec['v'], spec['seed'], H_=spec['H'], W=spec['W'])
        p = os.path.join(out_dir, spec['name'] + '.uai'); ex = write_uai(m, p)
        inv.append(dict(case_id=spec['name'], model_path=os.path.abspath(p), model_sha256=ex['model_sha256'], evidence_path=ex['evidence_path'], evidence_sha256=ex['evidence_sha256'], export_factor_scalars=ex['factor_scalars'], variables=len(m['cards']), factors=len(m['factors']), L=spec.get('L'), H=spec.get('H', spec.get('L')), W=spec.get('W', spec.get('L')), q=str(spec['q']), v=str(spec['v']), seed=spec['seed'], role=spec['role'], all_entries_positive=all(x > 0 for f in m['factors'] for x in f['values']),
                        tasks=dict(singletons='corner (0,0) and centre (m,m) singleton probabilities: COVERED by the all-original-singleton UAI task (error target 1/100 full width = eps 1/200 point-to-endpoint)', joint_and_parity='adjacent / far-pair / block joint laws, influence, straight / detour parity: NOT singleton tasks -> primary arms UNSUPPORTED_TASK_ADAPTER (recorded)', evidence='no evidence in the unqualified challenge results; sparse-pin evidence variants are additional labelled tasks (generator: sparse_pins)')))
    json.dump(dict(generator='qgrid-v1 hash rules (QGRID_REPRODUCTION.md §1), reconstructed 2026-11-13; this is a NEW labelled generation, not a bitwise replay of the missing historical model files', export='integer-scaled exact UAI (cex/pac/uai_export.py) + explicit empty-evidence file per model (external parser admission: libDAI / Merlin reject slash tokens)', checkpoints_verified=ok, checkpoints=cp, native_specialists='UNAVAILABLE_BACKEND: the historical moment-LP / checkerboard-oracle / window-transfer methods exist only as prose (docs/handoff/historical/v4/methods/GRID_INFERENCE.md); no executable specialist is in the repository; the dq/ package is the signed-exponential CHAIN pilot, not this grid', previous_manifest_error='campaign.py (2026-11-12) excluded qgrid as "signed factors (negative entries)"; every table is positive (verified per instance: all_entries_positive)', instances=inv), open(os.path.join(out_dir, 'QGRID_INVENTORY.json'), 'w'), indent=1)
    print(json.dumps(dict(checkpoints_verified=ok, instances=len(inv), out=out_dir)))


if __name__ == '__main__': main(sys.argv[1])
