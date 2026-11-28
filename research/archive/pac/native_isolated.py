"""ISOLATED execution of an independent native checker for the gate (candidate v4.2; fifth adversarial review R05): the SF / CBI checkers run in a FRESH child process
under a HARD timeout equal to the remaining checker allowance of the cell; a child that outlasts its allowance is killed by the gate and the cell is UNVERIFIABLE (never
an acceptance). Specification in, result out, both JSON; the child imports only from the executing (frozen) repository tree.
    python cex/pac/native_isolated.py SPEC.json OUT.json"""
import sys, os, json
HERE = os.path.dirname(os.path.abspath(__file__)); CODE = os.path.dirname(os.path.dirname(HERE))
if CODE not in sys.path: sys.path.insert(0, CODE)
sys.set_int_max_str_digits(0)


def run(spec):
    kind = spec['kind']
    if kind == 'sf':
        from fractions import Fraction as F
        from sf import core as SFC, check as SFK
        law = SFC.Law.load(spec['panel']); rec = dict(spec['rec'])
        rec['intervals'] = [(F(lo), F(hi)) for lo, hi in rec['intervals']]; rec['published'] = [(int(a), int(b)) for a, b in rec['published']]
        for k in ('N_int', 'Mk_int'):
            if k in rec: rec[k] = [int(x) for x in rec[k]]
        try: out = SFK.check(law, F(spec['r']), rec, bool(spec['claimed_symmetric'])); return dict(ok=bool(out.get('ok')), detail={k: str(v) for k, v in out.items()}, panel_sha256=law.sha256, n=law.n)
        except SFK.CheckFailure as e: return dict(ok=False, failure=str(e)[:240])
    if kind == 'cbi':
        from cbi import verify as V
        out = V.verify(spec['instance'], spec['output']); return dict(ok=bool(out.get('accepted')), reasons=[str(x)[:200] for x in (out.get('reasons') or [])])
    return dict(ok=False, failure='unknown checker kind %r' % (kind,))


if __name__ == '__main__':
    spec = json.load(open(sys.argv[1]))
    try: res = run(spec)
    except Exception as ex: res = dict(ok=False, failure='checker raised %s: %s' % (type(ex).__name__, str(ex)[:200]))
    tmp = sys.argv[2] + '.tmp'; json.dump(res, open(tmp, 'w'), default=str); os.replace(tmp, sys.argv[2])
