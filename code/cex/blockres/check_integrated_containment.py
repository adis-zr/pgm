"""Containment of ACTUAL PAC_EB publications against the independent exact oracle: the two small approximate-route models run long enough to publish (round 3)."""
import sys, os, json, time
from fractions import Fraction as F
HERE = os.path.dirname(os.path.abspath(__file__)); CODE = os.path.dirname(os.path.dirname(HERE))
for p in (HERE, os.path.join(CODE, 'cex', 'cqr'), os.path.join(CODE, 'cex', 'newarm')):
    if p not in sys.path: sys.path.insert(0, p)
import integrated as IG, oracle, task as T
OUT = sys.argv[1]; TMP = os.path.join(os.path.dirname(OUT), 'ctl_models'); EPS = F(1, 200); rows = []
for name, fn, kw, budget in (('complete_separator_14_cap256_40s', 'c7_complete_sep.uai', dict(table_cap=1 << 6, enum_cap=1 << 4, mb_cap=256), 40.0), ('product_interior_10_cap64_30s', 'c4_product_interior.uai', dict(table_cap=1 << 2, enum_cap=1 << 4, mb_cap=64), 30.0)):
    p = os.path.join(TMP, fn); t = T.load_task(p); r = oracle.truth(t['model'], t['queries'], max_assignments=1 << 20, max_table=1 << 20)
    tv = {(q.output['variable'], q.output['state']): a for q, a in zip(t['queries'], r['answers'])}; res = IG.solve(p, budget, force_approx=True, **kw); n = 0; miss = []; worst = F(0); widths = []
    for a in res['answers']:
        if a['guarantee'] == 'NOT_PUBLISHED': continue
        n += 1; tr = tv[(a['var'], a['state'])]; lo, hi, pt = F(a['lo']), F(a['hi']), F(a['point']); widths.append(float(hi - lo))
        if not (lo <= tr <= hi) or abs(pt - tr) > EPS: miss.append(dict(var=a['var'], state=a['state'], lo=float(lo), hi=float(hi), truth=float(tr)))
        worst = max(worst, abs(pt - tr))
    m = res['mechanism']; rows.append(dict(control=name, outcome=res['outcome'], published=n, K=res['K'], misses=len(miss), worst_abs_error=float(worst), max_width=(max(widths) if widths else None), ok=bool(n > 0 and not miss), detail=miss[:4],
                                       draws=m.get('draws'), X_mean=m.get('X_mean'), median_width_all=m.get('median_width'), wall_s=round(res['wall_s'], 1))); print(json.dumps(rows[-1], default=str)[:400])
summary = dict(utc=time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()), version=IG.VERSION, all_ok=all(r['ok'] for r in rows), rows=rows); json.dump(summary, open(OUT, 'w'), indent=1, default=str)
print('ALL_OK' if summary['all_ok'] else 'FAILURES', sum(1 for r in rows if not r['ok']), 'of', len(rows))
