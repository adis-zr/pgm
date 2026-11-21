"""Round-15 controls (integrated v2.9.2): (W1) a block whose OPTIONAL dense precomputation window has expired keeps all its queries through the shared representation (Kq == K, no
window skips, complete and contained vs the oracle); (W2) the same model with the window open uses dense tables and agrees; (R1) the reviewer's transient reproducer: the observed
array payload during the rescaling loop is within the plan on the star (production _rescale instrumented). Independent oracle = cex/cqr/oracle."""
import sys, os, json, random, time, math
from fractions import Fraction as F
HERE = os.path.dirname(os.path.abspath(__file__)); CODE = os.path.dirname(os.path.dirname(HERE))
for p in (HERE, os.path.join(CODE, 'cex', 'cqr'), os.path.join(CODE, 'cex', 'newarm')):
    if p not in sys.path: sys.path.insert(0, p)
import numpy as np
import integrated as IG, blockres as BR, oracle, task as T
OUT = sys.argv[1]; TMP = os.path.join(os.path.dirname(OUT), 'ctl_models'); os.makedirs(TMP, exist_ok=True); rows = []; rng = random.Random(1501)
def say(r): r['ok'] = bool(r['ok']); rows.append(r); print(json.dumps(r, default=str)[:420])
def write_uai(name, cards, factors, evidence=None):
    p = os.path.join(TMP, name + '.uai'); lines = ['MARKOV', str(len(cards)), ' '.join(map(str, cards)), str(len(factors))]
    for sc, _ in factors: lines.append('%d %s' % (len(sc), ' '.join(map(str, sc))))
    for sc, vals in factors: lines.append(str(len(vals))); lines.append(' '.join(str(v) for v in vals))
    open(p, 'w').write('\n'.join(lines) + '\n'); ev = evidence or {}; open(p + '.evid', 'w').write(('%d ' % len(ev)) + ' '.join('%d %d' % kv for kv in ev.items()) + '\n'); return p
def rnd(n, zeros=0.0, lo=1, hi=9): return [0 if rng.random() < zeros else rng.randint(lo, hi) for _ in range(n)]
def truth(p):
    t = T.load_task(p); r = oracle.truth(t['model'], t['queries'], max_assignments=1 << 20, max_table=1 << 20); return t, r, {(q.output['variable'], q.output['state']): a for q, a in zip(t['queries'], r['answers'])}
def contained(res, tv):
    n = 0; miss = []
    for a in res['answers']:
        if a['guarantee'] == 'NOT_PUBLISHED': continue
        n += 1; tr = tv[(a['var'], a['state'])]; lo, hi = F(a['lo']), F(a['hi'])
        if not (F(0) <= lo <= hi <= 1) or not (lo <= tr <= hi): miss.append((a['var'], a['state'], str(lo), str(hi), str(tr)))
    return n, miss
nS = 6; cards = [2] * nS + [3] * (2 * nS); facs = []
for i in range(nS):
    for j in range(i + 1, nS): facs.append(((i, j), rnd(4, zeros=0.15)))
    y0, y1 = nS + 2 * i, nS + 2 * i + 1; facs.append(((i, y0), rnd(6, zeros=0.1))); facs.append(((y0, y1), rnd(9)))
p = write_uai('w1_window', cards, facs, evidence={nS + 3: 1}); t, _, tv = truth(p)
# W1: construct_share so small that the window closes right after construction: every interior block must take the SHARED path (none skipped), Kq == K, complete, contained
orig_rec = IG.recover_query_table_float
def slow_recover(*a, **k): time.sleep(0.25); return orig_rec(*a, **k)                       # each dense per-variable replay costs 0.25 s, so the 0.6 s window (construct_share 0.05 x 12 s) closes after the first block(s)
IG.recover_query_table_float = slow_recover
try: r1 = IG.solve(p, 12.0, force_approx=True, table_cap=1 << 3, enum_cap=1 << 4, mb_cap=1 << 10, route='pac', schedule='targeted', construct_share=0.05)
finally: IG.recover_query_table_float = orig_rec
m1 = r1['mechanism']; n1, miss1 = contained(r1, tv)
say(dict(control='W1_expired_dense_window_keeps_all_queries_via_shared', outcome=r1['outcome'], Kq=m1.get('Kq'), K=r1['K'], window_skipped=m1.get('interior_queries_skipped_window'), blocks_window_to_shared=m1.get('blocks_window_to_shared'), shared_blocks=m1.get('shared_blocks'), dense_blocks=m1.get('dense_blocks'), published=n1, misses=len(miss1), unrecovered=len(r1.get('unrecovered_interior_vars') or []), ok=(m1.get('Kq') == r1['K'] and m1.get('interior_queries_skipped_window') == 0 and (m1.get('blocks_window_to_shared') or 0) > 0 and not miss1 and n1 == r1['K'])))
# W2: default window: dense path, same model, complete and contained; point estimates agree with W1 within 2 eps
r2 = IG.solve(p, 12.0, force_approx=True, table_cap=1 << 3, enum_cap=1 << 4, mb_cap=1 << 10, route='pac', schedule='targeted'); m2 = r2['mechanism']; n2, miss2 = contained(r2, tv)
agree = all(abs(F(a['point']) - F(b['point'])) <= F(1, 100) for a, b in zip(r1['answers'], r2['answers']) if a['guarantee'] != 'NOT_PUBLISHED' and b['guarantee'] != 'NOT_PUBLISHED')
say(dict(control='W2_open_window_dense_same_model_agrees', outcome=r2['outcome'], representation=m2.get('response_representation'), blocks_window_to_shared=m2.get('blocks_window_to_shared'), published=n2, misses=len(miss2), points_agree_within_2eps=agree, ok=(not miss2 and n2 == r2['K'] and agree and (m2.get('blocks_window_to_shared') or 0) == 0)))
# R1: the reviewer's star: observed payload during the rescaling loop <= plan
cards_s = [2] * 12 + [8]; blocks_s = [IG.FT((i, 12), np.ones((2, 8)), 0, F(0)) for i in range(12)]; plan = IG.mb_plan([b.scope for b in blocks_s], cards_s, 1 << 14); mb = IG.MBFloat(blocks_s, cards_s, 1 << 14, math.inf); mids = {id(r) for _, _, r in mb.fwd}
orig = IG._rescale; peaks = []
def observe(P, e):
    fr = sys._getframe(1); res = orig(P, e)
    if fr.f_code.co_name == 'backward_derivatives':
        loc = fr.f_locals; arrays = [r.M for _, _, r in mb.fwd if r.M is not None] + [d.M for mid, d in loc['D'].items() if mid in mids] + list(loc['outs'].values()) + [P, res[0]]       # P = the raw array being rescaled (popped from outs, still alive in the caller)
        backing = {}
        for a in arrays:
            while isinstance(a.base, np.ndarray): a = a.base
            backing[id(a)] = a
        peaks.append(sum(a.nbytes for a in backing.values()))
    return res
IG._rescale = observe
try: IG.backward_derivatives(mb, cards_s, math.inf, release=True)
finally: IG._rescale = orig
say(dict(control='R1_reviewer_star_observed_rescaling_payload_within_plan', planned=plan['reverse_live_bytes'], observed_peak=max(peaks), observations=len(peaks), ok=(max(peaks) <= plan['reverse_live_bytes'])))
summary = dict(utc=time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()), version=IG.VERSION, all_ok=all(r['ok'] for r in rows), rows=rows); json.dump(summary, open(OUT, 'w'), indent=1, default=str)
print('ALL_OK' if summary['all_ok'] else 'FAILURES', sum(1 for r in rows if not r['ok']), 'of', len(rows))
