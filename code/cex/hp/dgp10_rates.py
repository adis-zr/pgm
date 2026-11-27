"""DGP10: the FROZEN RESPONSE work-rate model from the RESPONSE_SCREEN development streams (observer ON) under runs/screen -- the SAME rule as DGP9 / dgp9_rates.py (per class (n, max card): floor = 0.9 x the minimum measured native
steps / s; global floor = 0.9 x the overall minimum), written BEFORE the main experiment into RESPONSE_RATES.json. The HB_R file (HEATBATH_RATES.json = the exact DGP9 bytes) is NEVER touched. Also records the measured response-tail cost data
(snapshot / certificate seconds per group) behind the frozen tail constants. usage: dgp10_rates.py [--records RD]"""
import os, sys, json, glob, time
RD = os.environ.get('DGP10_RD', '/Users/adis/Workspace/pgm-records/code/runs/mdi_2026-10-28/DGP10_QUERY_RESPONSE')
def main():
    rd = sys.argv[sys.argv.index('--records') + 1] if '--records' in sys.argv else RD; rows = []
    for p in sorted(glob.glob(os.path.join(rd, 'runs', 'screen', '*', 'result.json'))):
        d = json.load(open(p)); m = d.get('mechanism') or {}; ds = m.get('dev_stream'); w = m.get('witness') or {}
        if not ds or not ds.get('steps_per_second'): continue
        c = json.load(open(os.path.join(os.path.dirname(p), 'cell.json')))['cell']; n = w.get('n') or c.get('n'); card = c.get('card') or (max(w['cards']) if w.get('cards') else None); ob = ds.get('observer') or {}
        rows.append(dict(cell=os.path.basename(os.path.dirname(p)), task=c.get('task'), n=n, card=card, chain=ds.get('chain'), observer_on=ds.get('observer_on'), steps_per_s=ds['steps_per_second'], seconds=ds['seconds'], steps=ds['steps'], fast_path_share=ds.get('fast_path_share'), exact_fallbacks=(ds.get('counters') or {}).get('exact_fallbacks'), checkpoint_overhead_s=ds.get('checkpoint_overhead_s'), certificate_seconds=ob.get('certificate_seconds'), seconds_per_group=ob.get('seconds_per_group'), groups=ob.get('groups'), certified=ob.get('certified'), checker_calls=ob.get('checker_calls'), witness_s=(d.get('phases_s') or {}).get('witness'), burn_in_steps=(m.get('burn_in') or {}).get('steps')))
    classes = {}
    for r in rows:
        if r['n'] is None or r['card'] is None or r['chain'] != 'native' or not r['observer_on']: continue
        k = '%d_%d' % (r['n'], r['card']); cc = classes.setdefault(k, dict(n=r['n'], card=r['card'], measured=[], cells=[], checkpoint_overhead_s=[], certificate_seconds=[])); cc['measured'].append(r['steps_per_s']); cc['cells'].append(r['cell']); cc['checkpoint_overhead_s'].append(r['checkpoint_overhead_s']); cc['certificate_seconds'].append(r['certificate_seconds'])
    for cc in classes.values(): cc['steps_per_s_floor'] = 0.9 * min(cc['measured']); cc['steps_per_s_min'] = min(cc['measured']); cc['steps_per_s_max'] = max(cc['measured']); cc['certificate_seconds_max'] = max([x for x in cc['certificate_seconds'] if x is not None] or [None]) if any(x is not None for x in cc['certificate_seconds']) else None
    native = [r['steps_per_s'] for r in rows if r['chain'] == 'native' and r['observer_on']]; floor = 0.9 * min(native) if native else None
    out = dict(utc=time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()), arm='RESPONSE', rule='per class (n, max card): floor = 0.9 x the minimum measured native steps / s over the RESPONSE_SCREEN development streams (observer ON); global floor = 0.9 x the overall minimum; frozen before the main experiment; plans the global checkpoints of the RESPONSE arm only (HB_R uses the exact DGP9 file)', classes=classes, floor_steps_per_s=floor, cells=rows, n_cells=len(rows), tail_cost_data=dict(seconds_per_group_max=max([r['seconds_per_group'] for r in rows if r.get('seconds_per_group') is not None] or [None]) if any(r.get('seconds_per_group') is not None for r in rows) else None))
    json.dump(out, open(os.path.join(rd, 'RESPONSE_RATES.json'), 'w'), indent=1); print(json.dumps(dict(classes={k: round(v['steps_per_s_floor']) for k, v in classes.items()}, floor=floor, n=len(rows), tail=out['tail_cost_data'])))
if __name__ == '__main__': main()
