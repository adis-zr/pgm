"""OFFLINE REFERENCES for the PAC pass -- v4 (03 §6: offline reference construction is outside the per-inference deadline and charged separately; review R06 / B3):
representation-DISPATCHED by the registry: UAI-table rows get R0 exact rational truth by brute force when the free state space has at most 2^BITS joint assignments
(per-case wall cap); CBI block instances get the cbi exact variable-elimination reference when affordable; SF panels and H4 packets carry their own in-invocation
checkers and are recorded as typed UNAVAILABLE_FOR_R0 (not an error). Every completed reference is written ATOMICALLY as it is produced (REFERENCES_R0.json rewritten
through a temp file after each case): an abort never loses completed work; an unsupported / failing case is a typed per-case record, never an abort of the job.
    python cex/pac/references.py <RD> [--manifest CAMPAIGN_MANIFEST.json] [--bits 20] [--cap-s 300]"""
import sys, os, json, time, math, hashlib
HERE = os.path.dirname(os.path.abspath(__file__)); CODE = os.path.dirname(os.path.dirname(HERE)); sys.path.insert(0, os.path.join(CODE, 'cex', 'newarm')); sys.path.insert(0, HERE); sys.path.insert(0, CODE); sys.set_int_max_str_digits(0)
from fractions import Fraction as F
from itertools import product
import core, registry
REFERENCES_VERSION = 'pac-references-v4.2 (2026-11-14 repair 5: executable task set incl. native CBI instances; manifest-bound; per-case cap enforced at completion too)'
# PER-CASE CAP GRANULARITY (stated honestly; fifth review R05): the brute-force clock is polled every 4,096 assignments, the cbi exact reference between whole marginal calls,
# and ONCE MORE after the last call; a case whose construction exceeded cap_s is typed NONE even when its arithmetic completed (never an R0 reference); the whole stage runs
# under the supervisor's hard cap (offline_reference_total_seconds), which is the only HARD limit


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


def _write_atomic(path, obj):
    tmp = path + '.tmp'
    with open(tmp, 'w') as fh: json.dump(obj, fh, indent=1); fh.flush(); os.fsync(fh.fileno())
    os.replace(tmp, path)


def reference_for_row(r, bits, cap):
    """one inventory row -> a typed reference record (never raises for a supported-or-not representation; unexpected errors are typed too)"""
    coh = registry.COHORTS.get(r.get('cohort')); rep = coh['representation'] if coh else None
    mp = r.get('model_path'); t = time.monotonic()
    if not mp or not os.path.exists(mp): return dict(kind='NONE', reason='input not available on disk (status %s)' % r.get('status'), representation=rep)
    try:
        if rep == 'uai_table':
            m, b = core.read_uai(mp); free_bits = sum(math.log2(m['cards'][v]) for v in range(len(m['cards'])) if v not in m.get('evidence', {}))
            if free_bits > bits: return dict(kind='NONE', reason='free state space 2^%.1f exceeds the brute-force cap 2^%d' % (free_bits, bits), binding=b, representation=rep)
            res = brute(m, t + cap)
            if res is None: return dict(kind='NONE', reason='brute force exceeded the per-case cap %.0f s' % cap, binding=b, construction_s=time.monotonic() - t, representation=rep)
            if res == 'ZERO': return dict(kind='R0_zero_evidence', binding=b, construction_s=time.monotonic() - t, representation=rep)
            if time.monotonic() - t > cap: return dict(kind='NONE', reason='brute force exceeded the per-case cap %.0f s (detected at completion; soft cooperative cap)' % cap, binding=b, construction_s=time.monotonic() - t, representation=rep)
            return dict(kind='R0_exact_rational', rows=res, binding=b, construction_s=time.monotonic() - t, free_bits=free_bits, representation=rep)
        if rep == 'cbi_block_json':
            from cbi import model as M, exact as EX
            inst = M.Model.from_json(json.load(open(mp))); b = dict(model_sha256=hashlib.sha256(open(mp, 'rb').read()).hexdigest()); out = {}
            for bi in sorted(inst.blocks):
                if time.monotonic() - t > cap: return dict(kind='NONE', reason='cbi exact reference exceeded the per-case cap %.0f s' % cap, binding=b, representation=rep)
                marg, _ = EX.marginal(inst.blocks, inst.edges, bi, max_entries=1 << 22); probs, Z = EX.coordinate_probabilities(inst.blocks, bi, marg, inst.d)
                out[str(inst.ext(bi))] = [str(x) for x in probs]
            if time.monotonic() - t > cap: return dict(kind='NONE', reason='cbi exact reference exceeded the per-case cap %.0f s (detected at completion; soft cooperative cap)' % cap, binding=b, construction_s=time.monotonic() - t, representation=rep)
            return dict(kind='R0_cbi_exact_coordinates', coordinates=out, binding=b, construction_s=time.monotonic() - t, representation=rep)
        if rep in ('sf_panel_json', 'h4_frozen_packet'): return dict(kind='UNAVAILABLE_FOR_R0', reason='%s: the native invocation carries its own independent checker; no offline R0 reference is defined' % rep, representation=rep)
        return dict(kind='UNSUPPORTED_REPRESENTATION', reason='cohort %s has no reference method in the registry' % r.get('cohort'), representation=rep)
    except Exception as ex: return dict(kind='NONE', reason='reference construction failed: %s: %s' % (type(ex).__name__, str(ex)[:120]), representation=rep, construction_s=time.monotonic() - t)


def main(RD, manifest_name='CAMPAIGN_MANIFEST.json', bits=20, cap=300.0):
    man = json.load(open(os.path.join(RD, manifest_name))); refs = {}; t0 = time.monotonic(); outp = os.path.join(RD, 'REFERENCES_R0.json')
    mh_now = hashlib.sha256(open(os.path.join(RD, manifest_name), 'rb').read()).hexdigest()
    if os.path.exists(outp):
        try:
            old = json.load(open(outp)); refs = (old.get('references') or {}) if old.get('manifest_sha256') == mh_now else {}      # v4.2: an existing artifact is RESUMED only when it was built for THIS manifest; a foreign artifact is rebuilt
        except Exception: refs = {}
    rows_all = list(man['inventory']) + [dict(x, cohort=x.get('cohort', 'CBI')) for x in man.get('cbi_instances') or []]      # the SAME executable task set the producer schedules cells from (review 4 F05): inventory rows + native CBI instances
    executable = {c['case_id'] for c in man['cells']}
    for r in rows_all:
        cid = r.get('case_id')
        if cid in refs or cid not in executable: continue
        refs[cid] = reference_for_row(r, bits, cap)
        _write_atomic(outp, dict(references_version=REFERENCES_VERSION, utc=time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()), manifest_sha256=mh_now, bits_cap=bits, per_case_cap_s=cap, total_s=time.monotonic() - t0, references=refs))
        print(cid, refs[cid]['kind'], round(refs[cid].get('construction_s', 0), 2), flush=True)
    if not os.path.exists(outp) or json.load(open(outp)).get('manifest_sha256') != mh_now: _write_atomic(outp, dict(references_version=REFERENCES_VERSION, utc=time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()), manifest_sha256=mh_now, bits_cap=bits, per_case_cap_s=cap, total_s=time.monotonic() - t0, references=refs))
    print(json.dumps({k: v['kind'] for k, v in refs.items()}))


if __name__ == '__main__':
    bits = int(sys.argv[sys.argv.index('--bits') + 1]) if '--bits' in sys.argv else 20; cap = float(sys.argv[sys.argv.index('--cap-s') + 1]) if '--cap-s' in sys.argv else 300.0
    mn = sys.argv[sys.argv.index('--manifest') + 1] if '--manifest' in sys.argv else 'CAMPAIGN_MANIFEST.json'; main(os.path.abspath(sys.argv[1]), mn, bits, cap)
