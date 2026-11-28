"""Frozen confirmation selection (EVALUATION_FREEZE confirmation_rule): up to 6 tasks = the first two FULL-vs-BASE gains (task order), the first two FULL-vs-BASE losses, then vacant slots filled by fixed hash order
sha256(name) among the DENSE tasks (er50, clique, external), deduplicated. Writes RD/CONFIRM_MANIFEST.json. usage: dgp_confirm_select.py"""

# Source-checkout entry point; production imports never traverse research.
if __package__ in (None, ""):
    import sys as _research_sys
    from pathlib import Path as _ResearchPath
    _research_sys.path.insert(0, str(_ResearchPath(__file__).resolve().parents[3]))
from research.bootstrap import activate as _activate_research
_activate_research()
from research.paths import repo_root as _repo_root, runs_root as _runs_root, records_root as _records_root, source_path as _source_path
import sys, os, json, hashlib, time
RD = str(_runs_root() / 'mdi_2026-10-28/DENSE_GENERIC_PAC_INTEGRATION_1')
A = json.load(open(os.path.join(RD, 'ANALYSIS.json')))  # the (repaired) primary analysis: BASE / DET frozen cells + UPAC / FULL cells
res = dict(results=[dict(task=r['task'], arm=a, complete=r[a]['complete']) for r in A['table'] for a in ('BASE', 'DET', 'UPAC', 'FULL') if r.get(a)]); man = json.load(open(os.path.join(RD, 'MAIN_MANIFEST.json'))); meta = {t['name']: t for t in man['tasks']}
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
