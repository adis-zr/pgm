"""CBI coupled-block instances -> explicit-table UAI models + NATIVE-QUERY scoring (candidate v3; review R08 / B2).
A CBI instance (cbi/model.py) has blocks b with explicit supports (rows = integer masks over d coordinates, positive integer weights) and edges (u, v, r) with the
FULL-coordinate product kernel; K_r(x_u, x_v) * v^d = (v+u)^(d - dist) (v-u)^dist (cbi.arith.kappa_int; u/v = r in lowest terms; dist = Hamming distance) is an
explicit m_u x m_v INTEGER table. The block law is therefore an explicit-table factor model: one variable per block (cardinality m_b = support size), a unary factor
(the weights), one pairwise factor per edge; the dropped positive scalar v^-d per edge is irrelevant to normalized answers and recorded.
NATIVE TASK: per-coordinate probabilities P(x_bj = +1) for every block, interval width <= 1/100, delta 0 (cbi CLI). It is a LINEAR image of the block singleton
marginal: p_bj = sum over rows with bit j set of P(row). `native_enclosures` maps a COMPLETE, SHAPE-VALIDATED set of state enclosures (one interval per block, per row,
in the exported row order, bound to the exported blocks metadata by hash) to coordinate enclosures by summation; `native_score` then decides the NATIVE completion
(every coordinate width <= 1/100) separately from the UAI state-marginal completion, and compares with the native exact reference (cbi.exact) when the instance is
small enough. A truncated / permuted / wrongly bound input is REFUSED (never zip-truncated).
Feasibility: instances whose total explicit entries exceed MAX_ENTRIES are typed UNSUPPORTED_TASK_ADAPTER (explicit rendering too large; the kernel is implicit natively).
    python cex/pac/legacy_cbi_uai.py <cbi_inputs_dir> <out_dir>   -> UAI files (integer tables + empty evidence) + <case>.blocks.json + CBI_UAI_INVENTORY.json"""
import sys, os, json, hashlib, math
from fractions import Fraction as F
HERE = os.path.dirname(os.path.abspath(__file__)); CODE = os.path.dirname(os.path.dirname(HERE)); sys.path.insert(0, CODE); sys.path.insert(0, HERE)
MAX_ENTRIES = 4_000_000; NATIVE_WIDTH = F(1, 100)


class AdapterError(ValueError): pass


def render(inst):
    from cbi import model as M, arith as A
    m = M.Model.from_json(inst); d = m.d; ids = sorted(m.blocks)
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
    meta = dict(blocks=[dict(id=m.ext(b), internal=b, rows=list(m.blocks[b].rows)) for b in ids], d=d, cards=cards, dropped_scalars=dropped, external_block_ids=[m.ext(b) for b in ids])      # ids are the EXTERNAL block ids of the instance (sparse / reordered / negative allowed); `internal` is the UAI variable index
    return dict(cards=cards, factors=factors, evidence={}), entries, 'RENDERED', meta


def meta_sha(meta): return hashlib.sha256(json.dumps(dict(blocks=[dict(id=b['id'], internal=b.get('internal', i), rows=b['rows']) for i, b in enumerate(meta['blocks'])], d=meta['d'], cards=meta['cards']), sort_keys=True).encode()).hexdigest()


def native_enclosures(meta, rows_enclosures, meta_sha256=None):
    """COMPLETE state enclosures -> native coordinate enclosures. rows_enclosures: list over blocks (exported order) of lists over rows of (lo, hi) exact Fractions.
    Refuses: wrong number of blocks, a block with the wrong number of rows, non-interval entries, lo > hi, values outside [0, 1], metadata hash mismatch."""
    if meta_sha256 is not None and meta_sha(meta) != meta_sha256: raise AdapterError('blocks metadata hash does not match the bound export')
    blocks = meta['blocks']; d = int(meta['d'])
    if not isinstance(rows_enclosures, (list, tuple)) or len(rows_enclosures) != len(blocks): raise AdapterError('expected %d block rows, got %s' % (len(blocks), len(rows_enclosures) if isinstance(rows_enclosures, (list, tuple)) else type(rows_enclosures).__name__))
    out = {}
    for blk, row in zip(blocks, rows_enclosures):
        if not isinstance(row, (list, tuple)) or len(row) != len(blk['rows']): raise AdapterError('block %s: expected %d state enclosures, got %s' % (blk['id'], len(blk['rows']), len(row) if isinstance(row, (list, tuple)) else '?'))
        ivs = []
        for iv in row:
            if not (isinstance(iv, (list, tuple)) and len(iv) == 2): raise AdapterError('block %s: a state enclosure is not a pair' % blk['id'])
            lo, hi = F(iv[0]), F(iv[1])
            if not (0 <= lo <= hi <= 1): raise AdapterError('block %s: invalid state enclosure [%s, %s]' % (blk['id'], lo, hi))
            ivs.append((lo, hi))
        out[blk['id']] = [(sum(lo for (lo, hi), x in zip(ivs, blk['rows']) if (x >> j) & 1), min(F(1), sum(hi for (lo, hi), x in zip(ivs, blk['rows']) if (x >> j) & 1))) for j in range(d)]
    return out


def native_score(meta, rows_enclosures, meta_sha256=None, native_width=NATIVE_WIDTH, instance_json=None, native_widths=None, guarantee=None):
    """returns dict(native_completion in {NATIVE_WIDTH_MET, STATE_ROWS_ONLY_WIDTH_EXCEEDED, ADAPTER_REFUSED}, per requested native width the met flag, coordinate enclosures
    keyed by EXTERNAL block id, max width, reference comparison). `native_widths`: every width of the cohort's native contract (SF: 1/100 AND 1/20) is scored separately;
    `guarantee` is carried through unchanged (a deterministic mapping of PAC state intervals keeps their PAC delta: it never satisfies a delta-0 native task)."""
    try: enc = native_enclosures(meta, rows_enclosures, meta_sha256)
    except AdapterError as e: return dict(native_completion='ADAPTER_REFUSED', reason=str(e))
    widths = {b: [float(hi - lo) for lo, hi in row] for b, row in enc.items()}; wmax_exact = max(hi - lo for row in enc.values() for lo, hi in row); wmax = float(wmax_exact)
    nw = [F(x) for x in (native_widths or (native_width,))]
    met = {str(w): bool(wmax_exact <= w) for w in nw}
    rec = dict(native_completion='NATIVE_WIDTH_MET' if met[str(nw[0])] else 'STATE_ROWS_ONLY_WIDTH_EXCEEDED', native_width=str(nw[0]), native_widths_met=met, max_coordinate_width=wmax, guarantee=guarantee, delta_note=('PAC state intervals mapped deterministically keep their PAC delta (not a delta-0 native result)' if guarantee == 'PAC' else 'deterministic state intervals -> deterministic native enclosures (delta 0)'), coordinates={str(b): [(str(lo), str(hi)) for lo, hi in row] for b, row in enc.items()})
    if instance_json is not None:
        try:
            from cbi import model as M, exact as EX
            inst = M.Model.from_json(instance_json); contained = True; cmp = 0
            for b, row in enc.items():
                bi = inst.internal(b)                                                  # b is the EXTERNAL id (meta.blocks[].id); the exact reference is keyed internally
                marg, _ = EX.marginal(inst.blocks, inst.edges, bi, max_entries=1 << 22); probs, Z = EX.coordinate_probabilities(inst.blocks, bi, marg, inst.d)
                for j, (lo, hi) in enumerate(row):
                    cmp += 1
                    if not (lo <= probs[j] <= hi): contained = False
            rec['native_reference'] = dict(kind='cbi exact (variable elimination, exact rationals)', coordinates_compared=cmp, contains_truth=contained)
        except Exception as ex: rec['native_reference'] = dict(kind='cbi exact', status='UNAVAILABLE: %s' % str(ex)[:80])
    return rec


def native_point_score(meta, rows_points, meta_sha256=None, instance_json=None):
    """comparator (unguaranteed) points mapped to the native coordinates: p_bj = sum of the state points with bit j; scored as UNGUARANTEED ESTIMATES against the cbi exact
    reference (max abs error) -- never as a width / completion"""
    if meta_sha256 is not None and meta_sha(meta) != meta_sha256: return dict(native_completion='ADAPTER_REFUSED', reason='blocks metadata hash does not match the bound export')
    blocks = meta['blocks']; d = int(meta['d'])
    if not isinstance(rows_points, (list, tuple)) or len(rows_points) != len(blocks) or any(len(r) != len(b['rows']) for r, b in zip(rows_points, blocks)): return dict(native_completion='ADAPTER_REFUSED', reason='point rows do not match the blocks')
    pts = {blk['id']: [sum(F(p) for p, x in zip(row, blk['rows']) if (x >> j) & 1) for j in range(d)] for blk, row in zip(blocks, rows_points)}
    rec = dict(native_completion='UNGUARANTEED_ESTIMATE', coordinates={str(b): [str(x) for x in row] for b, row in pts.items()})
    if instance_json is not None:
        try:
            from cbi import model as M, exact as EX
            inst = M.Model.from_json(instance_json); worst = F(0); cmp = 0
            for b, row in pts.items():
                bi = inst.internal(b); marg, _ = EX.marginal(inst.blocks, inst.edges, bi, max_entries=1 << 22); probs, Z = EX.coordinate_probabilities(inst.blocks, bi, marg, inst.d)
                for j, x in enumerate(row): cmp += 1; worst = max(worst, abs(x - probs[j]))
            rec['native_reference'] = dict(kind='cbi exact (variable elimination, exact rationals)', coordinates_compared=cmp, max_abs_error=float(worst))
        except Exception as ex: rec['native_reference'] = dict(kind='cbi exact', status='UNAVAILABLE: %s' % str(ex)[:80])
    return rec


def main(inputs, out_dir):
    import uai_export
    os.makedirs(out_dir, exist_ok=True); inv = []
    for fn in sorted(os.listdir(inputs)):
        if not fn.endswith('.json'): continue
        inst = json.load(open(os.path.join(inputs, fn))); name = fn[:-5]; src_sha = hashlib.sha256(open(os.path.join(inputs, fn), 'rb').read()).hexdigest()
        res = render(inst); model, entries, status = res[0], res[1], res[2]
        rec = dict(case_id='cbi_uai_' + name, cohort='CBI_UAI', source=fn, source_sha256=src_sha, explicit_entries=entries, status=status, native_task='per-coordinate probabilities P(x_bj=+1) for all blocks, width 1/100, delta 0 (cbi CLI solve)', conversion='UAI all-singleton rows -> p_bj = sum over rows with bit j (linear image; enclosure by summation; NATIVE width checked separately)', task='all original singleton marginals (block states) -> native coordinates')
        if model is not None:
            meta = res[3]; p = os.path.join(out_dir, rec['case_id'] + '.uai'); ex = uai_export.write_uai(model, p)
            rec.update(model_path=os.path.abspath(p), model_sha256=ex['model_sha256'], evidence_path=ex['evidence_path'], evidence_sha256=ex['evidence_sha256'], cards=model['cards'], export_factor_scalars=ex['factor_scalars'], dropped_kernel_scalars=meta['dropped_scalars'])
            bp = os.path.join(out_dir, rec['case_id'] + '.blocks.json'); json.dump(meta, open(bp, 'w')); rec['blocks_path'] = os.path.abspath(bp); rec['blocks_sha256'] = meta_sha(meta); rec['external_block_ids'] = meta['external_block_ids']
        inv.append(rec)
    json.dump(dict(adapter='cbi -> explicit-table UAI (legacy_cbi_uai.py v4, 2026-11-13: external block ids preserved; both SF widths scored)', max_entries=MAX_ENTRIES, export='integer-scaled exact UAI + empty evidence (uai_export)', instances=inv), open(os.path.join(out_dir, 'CBI_UAI_INVENTORY.json'), 'w'), indent=1)
    print(json.dumps(dict(rendered=sum(1 for r in inv if r['status'] == 'RENDERED'), unsupported=sum(1 for r in inv if r['status'] != 'RENDERED'), out=out_dir)))


if __name__ == '__main__': main(sys.argv[1], sys.argv[2])
