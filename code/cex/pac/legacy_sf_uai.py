"""SF bridge coupled two-block law -> explicit-table UAI (candidate v3; review R07/R08). A panel {n, A: [[mask, w]...], B: [[mask, w]...]} with coupling r in [0, 1]
is the law W(a, b) = w_A(a) w_B(b) K_r(a, b) with the FULL-coordinate product kernel K_r(a,b) * v^n = (v+u)^(n-dist) (v-u)^dist (u/v = r lowest terms; dist = Hamming
distance on the n coordinates) -- the same kernel integers as cbi.arith.kappa_int. Rendered as two variables (cardinality m_A, m_B), two unary factors (weights) and one
m_A x m_B pairwise integer table; dropped scalar v^-n recorded. The native task (per-coordinate probabilities of the coupled law at each r, width eps) is the SAME linear
image as the CBI adapter (legacy_cbi_uai.native_enclosures / native_score) with blocks metadata {A rows, B rows}. Only panels within MAX_ENTRIES are rendered
(small_control: 128 x 128); the n=24 m=4096 panels are UNSUPPORTED_TASK_ADAPTER."""
import sys, os, json, hashlib
from fractions import Fraction as F
HERE = os.path.dirname(os.path.abspath(__file__)); CODE = os.path.dirname(os.path.dirname(HERE)); sys.path.insert(0, CODE); sys.path.insert(0, HERE)
MAX_ENTRIES = 4_000_000


def kappa(n, u, v, dist): return (v + u) ** (n - dist) * (v - u) ** dist


def render_panel(panel_path, out_dir, couplings=None):
    import uai_export
    from sf import core as SFC
    P = json.load(open(panel_path)); n = int(P['n']); A = [(int(x), int(w)) for x, w in P['A']]; B = [(int(x), int(w)) for x, w in P['B']]; name = os.path.basename(panel_path)[:-5]
    os.makedirs(out_dir, exist_ok=True); rows = []
    for r in (couplings or [x for x in SFC.R_PRIORITY]):
        r = F(r); u, v = r.numerator, r.denominator
        if len(A) * len(B) + len(A) + len(B) > MAX_ENTRIES: rows.append(dict(case_id='sf_uai_%s_r%s' % (name, str(r).replace('/', '-')), status='UNSUPPORTED_TASK_ADAPTER (explicit table too large)')); continue
        vals = [F(kappa(n, u, v, bin(a ^ b).count('1'))) for a, _ in A for b, _ in B]
        model = dict(cards=[len(A), len(B)], factors=[dict(scope=(0,), values=[F(w) for _, w in A]), dict(scope=(1,), values=[F(w) for _, w in B]), dict(scope=(0, 1), values=vals)], evidence={})
        cid = 'sf_uai_%s_r%s' % (name, str(r).replace('/', '-')); p = os.path.join(out_dir, cid + '.uai'); ex = uai_export.write_uai(model, p)
        meta = dict(blocks=[dict(id=0, rows=[a for a, _ in A]), dict(id=1, rows=[b for b, _ in B])], d=n, cards=model['cards'], dropped_scalars=['v^-%d (r=%s)' % (n, r)])
        bp = os.path.join(out_dir, cid + '.blocks.json'); json.dump(meta, open(bp, 'w'))
        rows.append(dict(case_id=cid, model_path=os.path.abspath(p), model_sha256=ex['model_sha256'], evidence_path=ex['evidence_path'], evidence_sha256=ex['evidence_sha256'], blocks_path=os.path.abspath(bp), blocks_sha256=hashlib.sha256(json.dumps(dict(blocks=meta['blocks'], d=meta['d'], cards=meta['cards']), sort_keys=True).encode()).hexdigest(), panel=name, panel_sha256=hashlib.sha256(open(panel_path, 'rb').read()).hexdigest(), sf_r=str(r), task='two-block state marginals -> NATIVE per-coordinate probabilities at coupling r=%s (legacy_cbi_uai.native_score; native widths 1/100 and 1/20 scored separately)' % r, native_specialists='sf/invoke.py select (SF_native cohort)', export_factor_scalars=ex['factor_scalars']))
    return rows


if __name__ == '__main__': print(json.dumps(render_panel(sys.argv[1], sys.argv[2]), indent=1)[:2000])
