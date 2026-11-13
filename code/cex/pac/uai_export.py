"""Exact UAI export shared by the generated cohorts (candidate v3; review R08 / B3). Every factor table is written as INTEGERS: the table is multiplied by the
least common denominator of its entries (a positive per-factor scalar, irrelevant to any normalized answer; the scalars are RECORDED so the unnormalized scale is
recoverable). This is exact for every rational table and parseable by every planned reader (admission control: libDAI JTREE and Merlin cte both reject Fraction
slash tokens; see runs/.../admission/EXTERNAL_PARSER_ADMISSION.json). An explicit empty-evidence file ('0') is written next to every model unless evidence is given."""
import hashlib, math, os
from fractions import Fraction as F


def write_uai(model, path, evidence=None):
    """write MODEL.uai (integer tables) and MODEL.uai.evid; returns dict(model_sha256, evidence_sha256, factor_scalars=[per-factor multiplier as str], evidence_path)"""
    cards = model['cards']; lines = ['MARKOV', str(len(cards)), ' '.join(str(c) for c in cards), str(len(model['factors']))]
    lines += ['%d %s' % (len(f['scope']), ' '.join(str(v) for v in f['scope'])) for f in model['factors']]
    scalars = []
    for f in model['factors']:
        vals = [x if isinstance(x, F) else F(x) for x in f['values']]
        D = 1
        for x in vals: D = D * x.denominator // math.gcd(D, x.denominator)
        ints = [int(x * D) for x in vals]; assert all(F(i, D) == x for i, x in zip(ints, vals)); scalars.append(str(F(1, D)))
        lines.append(str(len(ints))); lines.append(' '.join(str(i) for i in ints))
    data = ('\n'.join(lines) + '\n').encode(); open(path, 'wb').write(data)
    ev = dict(evidence or model.get('evidence') or {})
    etxt = ('%d %s\n' % (len(ev), ' '.join('%d %d' % (v, a) for v, a in sorted(ev.items())))) if ev else '0\n'
    epath = str(path) + '.evid'; open(epath, 'w').write(etxt)
    return dict(model_sha256=hashlib.sha256(data).hexdigest(), evidence_sha256=hashlib.sha256(etxt.encode()).hexdigest(), evidence_path=os.path.abspath(epath), factor_scalars=scalars, note='each factor written as integers = table * 1/scalar; the recorded per-factor scalar restores the original table (positive constants cancel in normalized answers)')
