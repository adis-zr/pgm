"""Round-17 controls (integrated v2.9.4): (K1) the reviewer's 4,096-boundary shared block under an injected 512 KiB cache budget: the RETAINED objects (sys.getsizeof lower bound over
the maps, keys and rows, excluding int objects, as the reviewer measured; and the full identity-deduplicated object graph) must be <= the budget, responses exact; (K2) a warmed cache
called with an expired deadline raises at entry (no hits returned); (K3) the reviewer's planner regression: an unsplit construction admitted without the cache stays admitted (same
cap) with the cache constant at its default, and a solve with shared blocks reports a per-solve cache allowance <= the remaining capacity (0 when nothing is shared)."""
import sys, os, json, math, time, gc
from fractions import Fraction as F
HERE = os.path.dirname(os.path.abspath(__file__)); CODE = os.path.dirname(os.path.dirname(HERE))
for p in (HERE, os.path.join(CODE, 'cex', 'cqr'), os.path.join(CODE, 'cex', 'newarm')):
    if p not in sys.path: sys.path.insert(0, p)
import numpy as np
import integrated as IG, blockres as BR
IG.SUPPORT_CLOSURE_DEFAULT = False          # (round 18) this suite exercises the FROZEN comparator path (v2.9.4 behaviour); the closure has its own suite, check_round18.py
OUT = sys.argv[1]; rows = []
def say(r): r['ok'] = bool(r['ok']); rows.append(r); print(json.dumps(r, default=str)[:420])
# K1
n = 4096; cards = [2, n]; v = 1 + np.arange(n) % 3; factor = IG.FT((0, 1), np.stack([v, 5 - v]).astype(float), 0, F(0)); blk = BR.Fn((1,), np.full(n, 5, dtype=object), [0], [0])
sb = IG.SharedBlock(blk, [factor], [0], cards, {1: 0}); S = np.arange(n, dtype=np.int64).reshape(-1, 1); cache = dict(entries={}, bytes=0, budget=512 << 10)
f, stats = IG.evaluate_shared(sb, S, np.arange(n), 64, math.inf, cache); exact = np.array_equal(f, np.column_stack([v / 5, 1 - v / 5])); ent = cache['entries'][id(sb)]
lower = sys.getsizeof(cache['entries']) + sys.getsizeof(ent) + sum(sys.getsizeof(k) + sys.getsizeof(row) for k, row in ent.items())
seen = set(); total = 0
def walk(o):
    global total
    if id(o) in seen: return
    seen.add(id(o)); total += sys.getsizeof(o)
    if isinstance(o, dict):
        for k, val in o.items(): walk(k); walk(val)
    elif isinstance(o, (tuple, list)):
        for x in o: walk(x)
    elif isinstance(o, np.ndarray): total += o.nbytes
walk(cache['entries'])
say(dict(control='K1_retained_cache_objects_within_injected_budget', budget=cache['budget'], charged=cache['bytes'], entries=len(ent), misses=stats['misses'], retained_lower_bound_excl_ints=lower, retained_object_graph=total, responses_exact=exact, ok=(exact and lower <= cache['budget'] and total <= cache['budget'] and cache['bytes'] <= cache['budget'] and len(ent) > 0)))
# K2
hit_rows = np.array([k[0] for k in ent], dtype=np.int64).reshape(-1, 1); raised = None
try: IG.evaluate_shared(sb, hit_rows, np.arange(len(hit_rows)), 64, -math.inf, cache)
except IG.Deadline as e: raised = str(e)
say(dict(control='K2_warmed_cache_expired_deadline_raises_at_entry', raised=raised, warmed_entries=len(ent), ok=(raised == 'shared_entry')))
# K3a: planner regression (reviewer's): the cache constant must not change cap admission
scopes = [(0, 1), (1, 2), (2, 3), (0, 3)]; cards4 = [2] * 4; plan = IG.mb_plan(scopes, cards4, 1 << 24); base = IG.USABLE_BYTES - IG.RECOVERY_BYTE_BUDGET - IG.BATCH_BUDGET - plan['log_bytes'] - (32 << 20)
saved = IG.RESPONSE_CACHE_BUDGET; IG.RESPONSE_CACHE_BUDGET = 0
try: cap0, plan0, _ = IG.memory_plan(scopes, cards4, 1 << 24, base)
finally: IG.RESPONSE_CACHE_BUDGET = saved
cap1, plan1, _ = IG.memory_plan(scopes, cards4, 1 << 24, base)
say(dict(control='K3a_optional_cache_never_changes_cap_admission', cap_without_cache=cap0, cap_with_default_cache=cap1, splits=(plan0 or {}).get('splits'), ok=(cap0 == cap1 == (1 << 24) and (plan0 or {}).get('splits') == 0)))
# K3b: a solve with shared blocks reports a per-solve allowance <= min(constant, remaining capacity); a solve without shared blocks reports 0
TMP = os.path.join(os.path.dirname(OUT), 'ctl_models'); p = os.path.join(TMP, 'c16_reuse.uai'); savedb = IG.RECOVERY_BYTE_BUDGET; IG.RECOVERY_BYTE_BUDGET = 0
try: r = IG.solve(p, 8.0, force_approx=True, table_cap=1 << 3, enum_cap=1 << 4, mb_cap=1 << 10, route='pac', schedule='targeted')
finally: IG.RECOVERY_BYTE_BUDGET = savedb
m = r['mechanism']; mp = m.get('memory_policy') or {}; remaining = IG.USABLE_BYTES - (mp.get('base_bytes', 0) + mp.get('planned_log_bytes', 0) + 0 + IG.BATCH_BUDGET)
r2 = IG.solve(p, 8.0, force_approx=True, table_cap=1 << 3, enum_cap=1 << 4, mb_cap=1 << 10, route='pac', schedule='targeted'); m2 = r2['mechanism']
say(dict(control='K3b_per_solve_cache_allowance_from_remaining_capacity', shared_blocks=m.get('shared_blocks'), allowance=m.get('response_cache_budget_bytes'), remaining_capacity=remaining, constant=IG.RESPONSE_CACHE_BUDGET, dense_run_shared_blocks=m2.get('shared_blocks'), dense_run_allowance=m2.get('response_cache_budget_bytes'), cache_bytes=(m.get('shared_rows') or {}).get('cache_bytes'), ok=(m.get('shared_blocks', 0) > 0 and 0 < m.get('response_cache_budget_bytes', -1) <= min(IG.RESPONSE_CACHE_BUDGET, remaining) and m2.get('response_cache_budget_bytes') == 0 and (m.get('shared_rows') or {}).get('cache_bytes', 1 << 60) <= m.get('response_cache_budget_bytes', 0) and r['outcome'] == 'COMPLETE')))
summary = dict(utc=time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()), version=IG.VERSION, all_ok=all(r['ok'] for r in rows), rows=rows); json.dump(summary, open(OUT, 'w'), indent=1, default=str)
print('ALL_OK' if summary['all_ok'] else 'FAILURES', sum(1 for r in rows if not r['ok']), 'of', len(rows))
