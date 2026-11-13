"""CBI coupled-block instances -> explicit-table UAI models (semantic adapter for the review's F07 "CBI had no candidate comparison").
A CBI instance (cbi/model.py) has blocks b with explicit supports (rows = integer masks over d coordinates, positive integer weights) and edges (u, v, r) with the
FULL-coordinate product kernel K_r(x_u, x_v) = prod_j k_r(x_uj, x_vj), which equals, up to the positive scalar v^-d per edge (cbi.arith.kappa_int: K times v^d =
(v+u)^(d - dist) (v-u)^dist with u/v = r in lowest terms and dist = Hamming distance on the d coordinates), an explicit m_u x m_v table. The block law is therefore an
explicit-table factor model: one variable per block (cardinality m_b = support size), a unary factor (the weights), one pairwise factor per edge. The native CBI task
(per-coordinate probabilities P(x_bj = +1) of every queried block, width 1/100, delta 0) is a LINEAR image of the block singleton marginal: p_bj = sum over rows with
bit j set of P(row). The UAI all-singleton output (enclosures per row) yields an enclosure of every p_bj by summation (the width may grow with the number of rows; it is
recorded, never hidden), so the UAI arms can be compared with the native specialist on the SAME task after this stated conversion.
Feasibility: the explicit pairwise tables have m_u * m_v entries; instances whose total explicit entries exceed MAX_ENTRIES are typed UNSUPPORTED_TASK_ADAPTER (explicit
rendering too large; the kernel is implicit in the native representation). Scalars dropped: v^-d per edge (a positive constant; irrelevant to normalized answers; recorded).
    python cex/pac/legacy_cbi_uai.py <cbi_inputs_dir> <out_dir>   -> UAI files + CBI_UAI_INVENTORY.json"""
import sys, os, json, hashlib, math
from fractions import Fraction as F
HERE = os.path.dirname(os.path.abspath(__file__)); CODE = os.path.dirname(os.path.dirname(HERE)); sys.path.insert(0, CODE)
MAX_ENTRIES = 4_000_000


def render(inst):
    from cbi import model as M, arith as A
    m = M.Model.from_json(inst); d = m.d; n = len(m.blocks); ids = sorted(m.blocks)
    cards = [len(m.blocks[b].rows) for b in ids]; factors = []
    for b in ids: factors.append(dict(scope=(b,), values=[F(int(w)) for w in m.blocks[b].w]))
    entries = sum(cards); dropped = []
    for e in m.edges:
        bu, bv = m.blocks[e.u], m.blocks[e.v]; dp = bin(e.mask).count('1'); u, v = A.uv(e.r); kap = [F(A.kappa_int(dp, u, v, dd)) for dd in range(dp + 1)]
        entries += len(bu.rows) * len(bv.rows)
        if entries > MAX_ENTRIES: return None, entries, 'UNSUPPORTED_TASK_ADAPTER: explicit pairwise tables exceed %d entries (implicit product kernel)' % MAX_ENTRIES
        vals = []
        for x in bu.rows:
            for y in bv.rows: vals.append(kap[bin((x ^ y) & e.mask).count('1')])
        factors.append(dict(scope=(e.u, e.v), values=vals)); dropped.append('v^-%d (edge %d-%d, r=%s)' % (dp, e.u, e.v, e.r))
    return dict(cards=cards, factors=factors, evidence={}, blocks=[dict(id=b, rows=list(m.blocks[b].rows)) for b in ids], d=d), entries, 'RENDERED'


def write_uai(model, path):
    lines = ['MARKOV', str(len(model['cards'])), ' '.join(str(c) for c in model['cards']), str(len(model['factors']))] + ['%d %s' % (len(f['scope']), ' '.join(str(v) for v in f['scope'])) for f in model['factors']]
    for f in model['factors']: lines.append(str(len(f['values']))); lines.append(' '.join(str(x) for x in f['values']))
    data = ('\n'.join(lines) + '\n').encode(); open(path, 'wb').write(data); return hashlib.sha256(data).hexdigest()


def coordinate_enclosures(model_meta, rows_enclosures):
    """from UAI all-singleton enclosures (per block variable: list of (lo, hi) per row) to the native per-coordinate enclosures p_bj = sum_{rows with bit j} P(row)"""
    out = {}
    for blk, row in zip(model_meta['blocks'], rows_enclosures):
        d = model_meta['d']; out[blk['id']] = [(sum(lo for (lo, hi), x in zip(row, blk['rows']) if (x >> j) & 1), min(F(1), sum(hi for (lo, hi), x in zip(row, blk['rows']) if (x >> j) & 1))) for j in range(d)]
    return out


def main(inputs, out_dir):
    os.makedirs(out_dir, exist_ok=True); inv = []
    for fn in sorted(os.listdir(inputs)):
        if not fn.endswith('.json'): continue
        inst = json.load(open(os.path.join(inputs, fn))); name = fn[:-5]; src_sha = hashlib.sha256(open(os.path.join(inputs, fn), 'rb').read()).hexdigest()
        model, entries, status = render(inst)
        rec = dict(case_id='cbi_uai_' + name, source=fn, source_sha256=src_sha, explicit_entries=entries, status=status, native_task='per-coordinate probabilities P(x_bj=+1) for all blocks, width 1/100, delta 0 (cbi CLI solve)', conversion='UAI all-singleton rows -> p_bj = sum over rows with bit j (linear image; enclosure by summation; recorded width)')
        if model is not None:
            p = os.path.join(out_dir, rec['case_id'] + '.uai'); rec['model_path'] = os.path.abspath(p); rec['model_sha256'] = write_uai(model, p); rec['evidence_sha256'] = hashlib.sha256(b'0').hexdigest(); rec['cards'] = model['cards']
            json.dump(dict(blocks=model['blocks'], d=model['d']), open(os.path.join(out_dir, rec['case_id'] + '.blocks.json'), 'w'))
        inv.append(rec)
    json.dump(dict(adapter='cbi -> explicit-table UAI (legacy_cbi_uai.py, 2026-11-13)', max_entries=MAX_ENTRIES, dropped_scalars='v^-d per edge (positive constants; irrelevant to normalized answers)', instances=inv), open(os.path.join(out_dir, 'CBI_UAI_INVENTORY.json'), 'w'), indent=1)
    print(json.dumps(dict(rendered=sum(1 for r in inv if r['status'] == 'RENDERED'), unsupported=sum(1 for r in inv if r['status'] != 'RENDERED'), out=out_dir)))


if __name__ == '__main__': main(sys.argv[1], sys.argv[2])
