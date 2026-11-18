"""OFFLINE REFERENCES for the CQR campaign (outside the per-inference deadline; charged separately under the supervisor). For every distinct executable case of the manifest
(model_path, query_path) the task is read by the SHARED reader (cex/cqr/task.load_task: model + <model>.evid + optional <model>.query.json) and, when the free state space has at
most 2^bits joint assignments, the INDEPENDENT oracle (cex/cqr/oracle.enumerate_truth: original tables, original queries, exact rationals) is run under a per-case wall cap:
  R0_exact          -- per original query the exact answer as a string ('UNDEFINED' for a ratio with zero denominator), Z, and -- for all-singleton tasks -- the per-variable rows
                       (so the baseline arms' intervals / points and the comparators' MAR points are audited on the same truth); normalizer tasks: the reference answer is Z;
  R0_zero_evidence  -- Z = 0 (every query ZERO_EVIDENCE);
  NONE              -- typed reason: free state space above the cap, per-case wall cap exceeded, input unavailable, reader failure.
Every record carries the binding (sha256 of model / .evid / .query.json as the reader saw them) and the task identity. Written ATOMICALLY after every case (an abort never loses
completed work); an existing artifact is resumed only when it was built for THIS manifest (manifest_sha256).
    python cex/cqr/references.py <RD> [--manifest NAME] [--bits 20] [--cap-s 300]"""
import sys, os, json, time, math, hashlib
HERE = os.path.dirname(os.path.abspath(__file__)); CEX = os.path.dirname(HERE); CODE = os.path.dirname(CEX); NEWARM = os.path.join(CEX, 'newarm')
for _p in (CODE, NEWARM, HERE):
    if _p in sys.path: sys.path.remove(_p)
    sys.path.insert(0, _p)
sys.set_int_max_str_digits(0)
from fractions import Fraction as F
import task as TK, oracle as OR
REFERENCES_VERSION = 'cqr-references-v1 (2026-11-16: independent oracle on the original task incl. the frozen query spec; per-case cap polled every 4,096 assignments and once more at completion; manifest-bound; atomic)'


def _write_atomic(path, obj):
    tmp = path + '.tmp'
    with open(tmp, 'w') as fh: json.dump(obj, fh, indent=1, default=str); fh.flush(); os.fsync(fh.fileno())
    os.replace(tmp, path)


def reference_for_case(model_path, bits, cap):
    t = time.monotonic()
    if not model_path or not os.path.exists(model_path): return dict(kind='NONE', reason='input not available on disk')
    try:
        task = TK.load_task(model_path)
    except Exception as ex: return dict(kind='NONE', reason='reader failed: %s: %s' % (type(ex).__name__, str(ex)[:120]))
    m = task['model']; ev = m.get('evidence', {}); free_bits = sum(math.log2(m['cards'][v]) for v in range(len(m['cards'])) if v not in ev)
    rec = dict(binding=task['binding'], task_identity=TK.task_identity(task), mode=task['mode'], epsilon=str(task['epsilon']), delta=str(task['delta']), queries=[q.name for q in task['queries']], all_singletons=bool(task['all_singletons']), normalizer_task=bool((task.get('query_spec') or {}).get('normalizer_task')), free_bits=free_bits)
    if free_bits > bits: return dict(rec, kind='NONE', reason='free state space 2^%.1f exceeds the brute-force cap 2^%d' % (free_bits, bits))
    try: tr = OR.enumerate_truth(m, task['queries'], deadline=t + cap, max_assignments=1 << bits)
    except Exception as ex: return dict(rec, kind='NONE', reason='oracle failed: %s: %s' % (type(ex).__name__, str(ex)[:120]), construction_s=time.monotonic() - t)
    el = time.monotonic() - t
    if tr is None: return dict(rec, kind='NONE', reason='oracle exceeded the per-case cap %.0f s (or the assignment cap)' % cap, construction_s=el)
    if el > cap: return dict(rec, kind='NONE', reason='oracle exceeded the per-case cap %.0f s (detected at completion; soft cooperative cap)' % cap, construction_s=el)
    if tr['Z'] == 0: return dict(rec, kind='R0_zero_evidence', Z='0', construction_s=el, assignments=tr.get('assignments'))
    answers = [str(a) if isinstance(a, F) else str(a) for a in tr['answers']]
    out = dict(rec, kind='R0_exact', Z=str(tr['Z']), answers=answers, construction_s=el, assignments=tr.get('assignments'))
    if rec['normalizer_task']: out['normalizer_reference'] = str(tr['Z'])
    # per-variable rows for all-singleton tasks (the legacy audit of intervals / points / MAR rows); singleton map for partial schedules
    smap = {}
    for j, q in enumerate(task['queries']):
        sv = TK.singleton_indicator_of(q, m['cards'])        # placement derived from the TABLE (CQR-S1-01)
        if sv is not None: smap['%d,%d' % sv] = answers[j]
    out['singleton_map'] = smap
    if task['all_singletons']:
        cards = m['cards']
        try: out['rows'] = [[smap['%d,%d' % (v, s)] for s in range(cards[v])] for v in range(len(cards))]
        except KeyError: out['rows'] = None
    return out


def main(RD, manifest_name='CAMPAIGN_MANIFEST.json', bits=20, cap=300.0):
    RD = os.path.abspath(RD); man = json.load(open(os.path.join(RD, manifest_name))); outp = os.path.join(RD, 'REFERENCES_R0.json'); t0 = time.monotonic()
    mh_now = hashlib.sha256(open(os.path.join(RD, manifest_name), 'rb').read()).hexdigest(); refs = {}
    if os.path.exists(outp):
        try:
            old = json.load(open(outp)); refs = (old.get('references') or {}) if old.get('manifest_sha256') == mh_now else {}
        except Exception: refs = {}
    cases = {}
    for c in man['cells']:
        key = c['case_id']
        if key in cases: continue
        cases[key] = dict(model_path=c.get('model_path'), query_path=c.get('query_path'), model_sha256=c.get('model_sha256'), evidence_sha256=c.get('evidence_sha256'), query_sha256=c.get('query_sha256'), cohort=c.get('cohort'))
    def record():
        _write_atomic(outp, dict(references_version=REFERENCES_VERSION, utc=time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()), manifest=manifest_name, manifest_sha256=mh_now, bits_cap=bits, per_case_cap_s=cap, total_s=time.monotonic() - t0, cases=len(cases), references=refs))
    for cid, info in cases.items():
        if cid in refs: continue
        r = reference_for_case(info['model_path'], bits, cap)
        fb = dict(model_sha256=info['model_sha256'], evidence_sha256=info['evidence_sha256'], query_sha256=info['query_sha256'])
        r['frozen_binding'] = fb; r['binding_matches_manifest'] = (r.get('binding') == fb); r['cohort'] = info['cohort']
        if r.get('binding') is not None and not r['binding_matches_manifest']: r['kind'] = 'NONE'; r['reason'] = 'reader binding differs from the frozen manifest hashes (input changed after freeze); reference withheld'
        refs[cid] = r; record()
        print(cid, r['kind'], round(r.get('construction_s', 0), 2), (r.get('reason') or '')[:80], flush=True)
    record()
    print(json.dumps({k: v['kind'] for k, v in refs.items()}))


if __name__ == '__main__':
    bits = int(sys.argv[sys.argv.index('--bits') + 1]) if '--bits' in sys.argv else 20; cap = float(sys.argv[sys.argv.index('--cap-s') + 1]) if '--cap-s' in sys.argv else 300.0
    mn = sys.argv[sys.argv.index('--manifest') + 1] if '--manifest' in sys.argv else 'CAMPAIGN_MANIFEST.json'; main(sys.argv[1], mn, bits, cap)
