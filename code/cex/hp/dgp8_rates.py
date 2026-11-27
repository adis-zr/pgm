"""DGP8: the FROZEN work-rate model from the Stage A development streams (brief section 6, Stage A item 3: 'measure bounded native throughput at predeclared short lengths on a development stream ... Freeze the resulting work-rate model
before guard runs'). Reads the Stage A cells' result.json (runner --dev-stream) under runs/screen/, groups by class (n, max card), takes the FLOOR per class = 0.9 x the minimum measured steps / s (conservative: a forecast that
under-predicts the rate only shortens the planned checkpoints; it never admits more sampling than measured), a global floor = 0.9 x the minimum over every eligible input, and writes HEATBATH_RATES.json with the per-cell evidence.
usage: dgp8_rates.py [--records RD]"""
import os, sys, json, glob, time, hashlib
RD = '/Users/adis/Workspace/pgm-records/code/runs/mdi_2026-10-28/DGP8_SPECTRAL_HEATBATH'
def main():
    rd = sys.argv[sys.argv.index('--records') + 1] if '--records' in sys.argv else RD; rows = []
    for p in sorted(glob.glob(os.path.join(rd, 'runs', 'screen', '*', 'result.json'))):
        d = json.load(open(p)); m = d.get('mechanism') or {}; ds = m.get('dev_stream'); w = m.get('witness') or {}
        if not ds or not ds.get('steps_per_second'): continue
        n = w.get('n'); cards = [int(x) for x in (w.get('cards') or [])] if w.get('cards') else None; card = (max(cards) if cards else int(d.get('input', '').split('_c')[1].split('_')[0]) if '_c' in d.get('input', '') else None)
        rows.append(dict(cell=os.path.basename(os.path.dirname(p)), input=os.path.basename(d.get('input', '')), n=n, card=card, steps_per_s=ds['steps_per_second'], seconds=ds['seconds'], steps=ds['steps'], fast_path_share=ds.get('fast_path_share'), exact_fallbacks=(ds.get('counters') or {}).get('exact_fallbacks'), witness_s=(d.get('phases_s') or {}).get('witness'), burn_in_steps=(m.get('burn_in') or {}).get('steps')))
    classes = {}
    for r in rows:
        if r['n'] is None or r['card'] is None: continue
        k = '%d_%d' % (r['n'], r['card']); c = classes.setdefault(k, dict(n=r['n'], card=r['card'], measured=[], cells=[])); c['measured'].append(r['steps_per_s']); c['cells'].append(r['cell'])
    for c in classes.values(): c['steps_per_s_floor'] = 0.9 * min(c['measured']); c['steps_per_s_min'] = min(c['measured']); c['steps_per_s_max'] = max(c['measured'])
    floor = 0.9 * min(r['steps_per_s'] for r in rows) if rows else None
    out = dict(utc=time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()), rule='per class (n, max card): floor = 0.9 x the minimum measured steps / s over the Stage A development streams; global floor = 0.9 x the overall minimum; frozen before the guard runs; a forecast only plans checkpoints (it never admits unmeasured sampling)', classes=classes, floor_steps_per_s=floor, cells=rows, n_cells=len(rows))
    json.dump(out, open(os.path.join(rd, 'HEATBATH_RATES.json'), 'w'), indent=1); print(json.dumps(dict(classes={k: round(v['steps_per_s_floor']) for k, v in classes.items()}, floor=floor, n=len(rows))))
if __name__ == '__main__': main()
