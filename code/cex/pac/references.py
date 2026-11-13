"""OFFLINE REFERENCES for the PAC pass (03 §6: offline reference construction is outside the per-inference deadline and charged separately): R0 exact rational truth by brute
force for every inventory case whose state space has at most 2^BITS joint assignments (default 2^20 with a wall cap per case), with source/evidence hashes and construction
cost. Writes REFERENCES_R0.json. Run under the supervisor (scope pac_offline_reference).
    python cex/pac/references.py <RD> [--bits 20] [--cap-s 300]"""
import sys, os, json, time, math, hashlib
HERE = os.path.dirname(os.path.abspath(__file__)); CODE = os.path.dirname(os.path.dirname(HERE)); sys.path.insert(0, os.path.join(CODE, 'cex', 'newarm')); sys.set_int_max_str_digits(0)
from fractions import Fraction as F
from itertools import product
import core


def brute(model, deadline):
    cards = model['cards']; ev = model.get('evidence', {}); out = [[F(0)] * d for d in cards]; z = F(0); n = 0
    free = [v for v in range(len(cards)) if v not in ev]
    for xs in product(*(range(cards[v]) for v in free)):
        n += 1
        if n % 4096 == 0 and time.monotonic() >= deadline: return None
        x = dict(ev); x.update(zip(free, xs)); w = F(1)
        for f in model['factors']:
            i = 0
            for v in f['scope']: i = i * cards[v] + x[v]
            w *= f['values'][i]
            if w == 0: break
        if w == 0: continue
        z += w
        for v in range(len(cards)): out[v][x[v]] += w
    if not z: return 'ZERO'
    return [[str(a / z) for a in row] for row in out]


def main(RD, bits=20, cap=300.0):
    man = json.load(open(os.path.join(RD, 'CAMPAIGN_MANIFEST.json'))); refs = {}; t0 = time.monotonic()
    for r in man['inventory']:
        if not r.get('model_path') or not os.path.exists(r['model_path']): continue
        m, b = core.read_uai(r['model_path']); free_bits = sum(math.log2(m['cards'][v]) for v in range(len(m['cards'])) if v not in m.get('evidence', {}))
        if free_bits > bits: refs[r['case_id']] = dict(kind='NONE', reason='free state space 2^%.1f exceeds the brute-force cap 2^%d' % (free_bits, bits), binding=b); continue
        t = time.monotonic(); res = brute(m, t + cap)
        if res is None: refs[r['case_id']] = dict(kind='NONE', reason='brute force exceeded the per-case cap %.0f s' % cap, binding=b, construction_s=time.monotonic() - t)
        elif res == 'ZERO': refs[r['case_id']] = dict(kind='R0_zero_evidence', binding=b, construction_s=time.monotonic() - t)
        else: refs[r['case_id']] = dict(kind='R0_exact_rational', rows=res, binding=b, construction_s=time.monotonic() - t, free_bits=free_bits)
        print(r['case_id'], refs[r['case_id']]['kind'], round(refs[r['case_id']].get('construction_s', 0), 2), flush=True)
    json.dump(dict(utc=time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()), bits_cap=bits, per_case_cap_s=cap, total_s=time.monotonic() - t0, references=refs), open(os.path.join(RD, 'REFERENCES_R0.json'), 'w'), indent=1)
    print(json.dumps({k: v['kind'] for k, v in refs.items()}))


if __name__ == '__main__':
    bits = int(sys.argv[sys.argv.index('--bits') + 1]) if '--bits' in sys.argv else 20; cap = float(sys.argv[sys.argv.index('--cap-s') + 1]) if '--cap-s' in sys.argv else 300.0; main(os.path.abspath(sys.argv[1]), bits, cap)
