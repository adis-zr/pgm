"""Generates RESULTS.md for the block-contraction experiment from the saved artifacts (result.json per run + the supervisor ledger + the recorded baseline table).
Nothing here changes an answer; it only reads and tabulates. Usage: python report.py RUN_DIR"""

# Source-checkout entry point; production imports never traverse research.
if __package__ in (None, ""):
    import sys as _research_sys
    from pathlib import Path as _ResearchPath
    _research_sys.path.insert(0, str(_ResearchPath(__file__).resolve().parents[3]))
from research.bootstrap import activate as _activate_research
_activate_research()
from research.paths import repo_root as _repo_root, runs_root as _runs_root, records_root as _records_root, source_path as _source_path
import json, glob, os, sys
from fractions import Fraction as F
RD = sys.argv[1]
# recorded incumbent evidence (same host, 20 s, from PANEL_PRESELECTION.md; A1 shard 18 Nov 2026 + PAC campaign 12 Nov 2026)
REC = {
 'DBN_11': 'N1_CQR / B0 / H1 PUBLISHED exact 1.06 s; LIBDAI_EXACT DEADLINE 19.7 s; MERLIN 2.32 s (unguaranteed, accurate)',
 'Promedus_37': 'N1 2.74 s / B0 2.69 s / H1 2.75 s PUBLISHED exact (structural_original); LIBDAI_EXACT 17.3 s; MERLIN 6.21 s',
 'Grids_15': 'B0 11.5 s / H1 11.5 s / N1 12.8 s PUBLISHED exact at 0.62 GiB; LIBDAI MEMORY_KILL; no accurate approximate comparator',
 'ObjectDetection_24': 'all incumbents DEADLINE at 20 s (B0 / H1 PUBLISHED at 25.2 s under 120 s); LIBDAI MEMORY_KILL; WMB 19.8 s unresolved accuracy',
 '1qt9': 'N1 / B0 DEADLINE (B0 2.98 GiB); H1 NUM_RANGE 0.69 s; LIBDAI MEMORY_KILL; WMB 19.8 s unresolved accuracy',
 'BN_12': 'N1 / H1 DEADLINE; B0 DEADLINE at 2.31 GiB; LIBDAI MEMORY_KILL; WMB 19.8 s unresolved accuracy',
 'ObjectDetection_39': 'all incumbents DEADLINE at 20 s (B0 35.3 s at 120 s); LIBDAI MEMORY_KILL; WMB 19.7 s unresolved (confirmation task)',
 'CSP_11': 'N1 / H1 DEADLINE; B0 MEMORY_KILL 15 s; LIBDAI MEMORY_KILL; WMB 19.8 s unresolved (confirmation task)',
}
receipts = {}
for l in open(os.path.join(RD, 'BLOCKRES_LEDGER.jsonl')):
    r = json.loads(l)
    if r.get('kind') == 'RECEIPT': receipts[r['job']] = r
rows = []; mech = []
for p in sorted(glob.glob(RD + '/probe/*/result.json')) + sorted(glob.glob(RD + '/confirm/*/result.json')):
    d = json.load(open(p)); run = os.path.basename(os.path.dirname(p)); sub = os.path.basename(os.path.dirname(os.path.dirname(p))); task, arm = run.split('__', 1)
    seed = d.get('seed', 1); job = 'blockres:%s:%s:%s' % (sub, task, arm.replace('_seed2', '')) + (':seed2' if 'seed2' in arm else '')
    rc = receipts.get(job) or next((v for k, v in receipts.items() if k.startswith('blockres:%s:%s:%s' % (sub, task, arm.split('_')[0])) and ('mb' in k) == ('mb' in arm) and ('seed2' in k) == ('seed2' in arm)), None)
    m = d['mechanism']; ph = d['phases_s']; byg = {}
    for a in d['answers']: byg[a['guarantee']] = byg.get(a['guarantee'], 0) + 1
    construct = sum(ph.get(k, 0) for k in ('read', 'integerize', 'contract', 'query_tables', 'frontier_init'))
    pubs = [a for a in d['answers'] if a['guarantee'] != 'NOT_PUBLISHED']
    maxpt = max((float(F(a['point'])) for a in pubs if a['guarantee'] != 'EXACT'), default=None)
    width = d.get('max_width')
    rows.append(dict(task=task, arm=arm, seed=seed, outcome=d['outcome'] + ((' (' + d['deadline_phase'] + ')') if d.get('deadline_phase') else ''), guarantee=d.get('guarantee'), published='%d / %d' % (d.get('published', 0), d['K']),
                     by=', '.join('%s %d' % (k, v) for k, v in sorted(byg.items()) if k != 'NOT_PUBLISHED') or '-', complete_s=(rc['wall_s'] if rc else None), solve_s=round(d['wall_s'], 2), construct_s=round(construct, 2),
                     peak_gib=(round(rc['peak_tree_rss_bytes'] / 2 ** 30, 2) if rc else None), max_width=('%.2g' % width if width is not None else '-'), max_pub_point=('%.2g' % maxpt if maxpt is not None else '-'), rep=1))
    lim = max(((k, v) for k, v in ph.items()), key=lambda kv: kv[1])
    mech.append(dict(task=task, arm=arm, blocks=m.get('blocks'), sep=m.get('separator_vars'), elim=m.get('eliminated_vars'), NS=m.get('N_S_log2'), E=m.get('root_E_log2'), Bint=m.get('root_B_log2'), other=m.get('root_B_other_log2'), Zhat=m.get('Zhat_log2_DIAGNOSTIC'),
                     Zlo=m.get('Zlo_log2'), Zhi=m.get('Zhi_log2'), construct=round(construct, 2), qrec='%s/%s/%s' % (m.get('interior_queries_recovered'), m.get('interior_queries_failed'), m.get('interior_queries_skipped_window')),
                     draws='%s / %s' % (m.get('ratio_draws'), m.get('signed_draws')), splits=m.get('splits'), limiting='%s %.1f s' % lim, mb=d.get('mb_cap', 0)))
def f1(x): return '-' if x is None else ('%.1f' % x if isinstance(x, float) else str(x))
out = ['# Block contraction for residual inference -- results (19 Nov 2026)', '', 'Per-task table (complete time = supervised wall incl. launch / cleanup; solve = in-process wall; check time: the exact route is self-certifying by exact integer arithmetic and every published approximate interval is an outward enclosure, so no separate checker ran -- see NOTE.md; reference containment of every published answer was verified afterwards against recorded exact answers where they exist: `panel/REFERENCE_CONTAINMENT.txt`). Peak memory = sampled process-tree RSS. Repetitions: 1 per cell unless noted (one seed repeat on BN_12).', '',
       '| task | arm | outcome | guarantee | published / K | by class | complete s | solve s | construct s | peak GiB | max published width | max published point (non-exact) | recorded incumbents at 20 s |', '|---|---|---|---|---|---|---|---|---|---|---|---|---|']
for r in rows: out.append('| %s | %s | %s | %s | %s | %s | %s | %s | %s | %s | %s | %s | %s |' % (r['task'], r['arm'] + (' (seed 2)' if r['seed'] == 2 else ''), r['outcome'], r['guarantee'], r['published'], r['by'], f1(r['complete_s']), r['solve_s'], r['construct_s'], f1(r['peak_gib']), r['max_width'], r['max_pub_point'], REC.get(r['task'], '')))
out += ['', 'Mechanism table. All bound columns are log2 of EXACT integers in the integerized weight units (products of table denominators cleared), so only DIFFERENCES between columns of the same row are meaningful: E = root pointwise sampling cap N_S prod_b max g_b (block arm) / N_S N_Y prod_phi max phi (factorwise arm); B_int = root integrated mass bound (= E unless the mini-bucket option tightened it); other = the SAME root bound computed with the other arm\'s bounds (the tightening ratio is 2^(E - other)); Z-hat = the ratio stream\'s unbiased estimate of Z (DIAGNOSTIC, not a certificate; None when no draw completed); Zlo / Zhi = certified deterministic enclosure of Z at the end. Bound ratios are 2^(difference); they are not timing ratios.', '',
        '| task | arm | mb cap | blocks | separator vars | eliminated vars | log2 N_S | log2 E (root cap) | log2 B_int | log2 other-arm root bound | log2 Z-hat (diag.) | log2 Zlo | log2 Zhi | construct s | interior queries recovered/failed/skipped | ratio / signed draws | splits | limiting phase |', '|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|']
for m in mech: out.append('| %s | %s | %s | %s | %s | %s | %s | %s | %s | %s | %s | %s | %s | %s | %s | %s | %s | %s |' % (m['task'], m['arm'], m['mb'], m['blocks'], m['sep'], m['elim'], f1(m['NS']), f1(m['E']), f1(m['Bint']), f1(m['other']), f1(m['Zhat']), f1(m['Zlo']), f1(m['Zhi']), m['construct'], m['qrec'], m['draws'], m['splits'], m['limiting']))
tot = sum(r['wall_s'] for r in receipts.values()); out += ['', 'Supervised ledger: %d receipts, %.1f s summed elapsed (ceiling 2,400 s). See TIMING_LOG.md for the phase breakdown and the disclosed unsupervised development probes.' % (len(receipts), tot)]
open(os.path.join(RD, 'RESULTS.md'), 'w').write('\n'.join(out) + '\n'); print('\n'.join(out))
