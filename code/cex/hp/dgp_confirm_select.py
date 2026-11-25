"""Frozen confirmation selection (EVALUATION_FREEZE confirmation_rule): up to 6 tasks = the first two FULL-vs-BASE gains (task order), the first two FULL-vs-BASE losses, then vacant slots filled by fixed hash order
sha256(name) among the DENSE tasks (er50, clique, external), deduplicated. Writes RD/CONFIRM_MANIFEST.json. usage: dgp_confirm_select.py"""
import sys, os, json, hashlib, time
RD = '/Users/adis/Workspace/pgm-records/code/runs/mdi_2026-10-28/DENSE_GENERIC_PAC_INTEGRATION_1'
res = json.load(open(os.path.join(RD, 'main/RESULTS_main_primary.json'))); man = json.load(open(os.path.join(RD, 'MAIN_MANIFEST.json'))); meta = {t['name']: t for t in man['tasks']}
by = {}
for r in res['results']: by.setdefault(r['task'], {})[r['arm']] = r
order = [t['name'] for t in man['tasks']]; gains = [t for t in order if by[t]['FULL']['complete'] and not by[t]['BASE']['complete']]; losses = [t for t in order if by[t]['BASE']['complete'] and not by[t]['FULL']['complete']]
chosen = []
for t in gains[:2] + losses[:2]:
    if t not in chosen: chosen.append(t)
dense = sorted([t for t in order if (meta[t].get('topology') in ('er50', 'clique')) or meta[t].get('panel') == 'external'], key=lambda t: hashlib.sha256(t.encode()).hexdigest())
for t in dense:
    if len(chosen) >= 6: break
    if t not in chosen: chosen.append(t)
sel = dict(rule=__doc__, gains_first_two=gains[:2], losses_first_two=losses[:2], all_gains=gains, all_losses=losses, fill_hash_order=[t for t in chosen if t not in gains[:2] + losses[:2]], selected=chosen, tasks=[meta[t] for t in chosen], arms=['BASE', 'UPAC', 'FULL'], seeds=[2, 3], order='reversed per task', utc=time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()))
json.dump(sel, open(os.path.join(RD, 'CONFIRM_MANIFEST.json'), 'w'), indent=1); print(json.dumps({k: v for k, v in sel.items() if k not in ('tasks', 'rule')}))
