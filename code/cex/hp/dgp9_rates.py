"""DGP9: the FROZEN work-rate model from the screen's development streams (HB_SCREEN cells under runs/screen; brief: 'use the same end-to-end budgets and freeze costs, build/cache policy, rates and checkpoints before scoring'). Same rule
as DGP8 (dgp8_rates.py): per class (n, max card) floor = 0.9 x the minimum measured steps / s; global floor = 0.9 x the overall minimum; written BEFORE the main experiment; the heat-bath arms REQUIRE the file (a missing requested
file is a typed cell failure). Also records the measured per-checkpoint overhead (flush + rows) per class -- the cost datum behind the frozen plan constants. usage: dgp9_rates.py [--records RD]"""
import os, sys, json, glob, time
RD = os.environ.get('DGP9_RD', '/Users/adis/Workspace/pgm-records/code/runs/mdi_2026-10-28/DGP9_SPECTRAL_HEATBATH_CONTINUATION')
def main():
    rd = sys.argv[sys.argv.index('--records') + 1] if '--records' in sys.argv else RD; rows = []
    for p in sorted(glob.glob(os.path.join(rd, 'runs', 'screen', '*', 'result.json'))):
        d = json.load(open(p)); m = d.get('mechanism') or {}; ds = m.get('dev_stream'); w = m.get('witness') or {}
        if not ds or not ds.get('steps_per_second'): continue
        c = json.load(open(os.path.join(os.path.dirname(p), 'cell.json')))['cell']; n = w.get('n') or c.get('n'); card = c.get('card') or (max(w['cards']) if w.get('cards') else None)
        rows.append(dict(cell=os.path.basename(os.path.dirname(p)), task=c.get('task'), n=n, card=card, chain=ds.get('chain'), steps_per_s=ds['steps_per_second'], seconds=ds['seconds'], steps=ds['steps'], fast_path_share=ds.get('fast_path_share'), exact_fallbacks=(ds.get('counters') or {}).get('exact_fallbacks'), checkpoint_overhead_s=ds.get('checkpoint_overhead_s'), checkpoint_overhead_rows=ds.get('checkpoint_overhead_rows'), witness_s=(d.get('phases_s') or {}).get('witness'), burn_in_steps=(m.get('burn_in') or {}).get('steps')))
    classes = {}
    for r in rows:
        if r['n'] is None or r['card'] is None or r['chain'] != 'native': continue
        k = '%d_%d' % (r['n'], r['card']); cc = classes.setdefault(k, dict(n=r['n'], card=r['card'], measured=[], cells=[], checkpoint_overhead_s=[])); cc['measured'].append(r['steps_per_s']); cc['cells'].append(r['cell']); cc['checkpoint_overhead_s'].append(r['checkpoint_overhead_s'])
    for cc in classes.values(): cc['steps_per_s_floor'] = 0.9 * min(cc['measured']); cc['steps_per_s_min'] = min(cc['measured']); cc['steps_per_s_max'] = max(cc['measured']); cc['checkpoint_overhead_s_max'] = max(x for x in cc['checkpoint_overhead_s'] if x is not None) if any(x is not None for x in cc['checkpoint_overhead_s']) else None
    native = [r['steps_per_s'] for r in rows if r['chain'] == 'native']; floor = 0.9 * min(native) if native else None
    out = dict(utc=time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()), rule='per class (n, max card): floor = 0.9 x the minimum measured native steps / s over the screen development streams; global floor = 0.9 x the overall minimum; frozen before the main experiment; a forecast only plans checkpoints (it never admits unmeasured sampling); the exact-chain fallback uses the runner constant', classes=classes, floor_steps_per_s=floor, cells=rows, n_cells=len(rows))
    json.dump(out, open(os.path.join(rd, 'HEATBATH_RATES.json'), 'w'), indent=1); print(json.dumps(dict(classes={k: round(v['steps_per_s_floor']) for k, v in classes.items()}, floor=floor, n=len(rows), checkpoint_overhead_max={k: v['checkpoint_overhead_s_max'] for k, v in classes.items()})))
if __name__ == '__main__': main()
