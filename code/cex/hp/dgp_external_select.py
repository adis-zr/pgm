"""Frozen external-panel selection of DENSE_GENERIC_PAC_INTEGRATION_1 (brief section 8, 'Existing external panel: up to eight tasks'). Metadata rule, stated before any new solver run:
ELIGIBLE = a registry case (EXTERNAL_SWEEP_2026-11-06/INVENTORY.json, dedup by canonical sha) with max_arity <= 2 (pairwise + unary), zero_fraction == 0 (every table entry positive), cycle rank >= 1 after
evidence restriction, and NO recorded certified completion at the 20 s contract by an accepted in-library arm (census CANDIDATE_CENSUS_draft.json: resolved_20s_by_in_library_arm == false). PRIORITY = min-fill induced width of the
evidence-restricted primal graph (computed here, recorded), descending; FAMILY CAP = 2 per benchmark family, filled in priority order with ties broken by the fixed hash order sha256(name); at most 8.
Exposure label: 'exposed' when any arm previously ran the instance (census), else 'unexposed'. Protein instances fail the positivity clause (4-26 exact zeros each) and are listed as the shortfall reason."""
import sys, os, json, hashlib, time
HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(HERE)), 'cex', 'newarm'))
RD = '/Users/adis/Workspace/pgm-records/code/runs/mdi_2026-10-28/DENSE_GENERIC_PAC_INTEGRATION_1'

def induced_width_minfill(model):
    cards = model['cards']; ev = model.get('evidence', {}); adj = {v: set() for v in range(len(cards)) if v not in ev}
    for f in model['factors']:
        sc = [v for v in f['scope'] if v not in ev]
        for i in sc:
            for j in sc:
                if i != j: adj[i].add(j)
    width = 0; live = set(adj)
    while live:
        best = None
        for v in live:
            nb = adj[v] & live; fill = sum(1 for i in nb for j in nb if i < j and j not in adj[i])
            key = (fill, len(nb), v)
            if best is None or key < best[0]: best = (key, v)
        v = best[1]; nb = adj[v] & live; width = max(width, len(nb))
        for i in nb:
            for j in nb:
                if i != j: adj[i].add(j)
        live.remove(v)
    return width

def main():
    import core as CORE
    census = json.load(open(os.path.join(RD, 'external/CANDIDATE_CENSUS_draft.json'))); cands = []
    for c in census['eligible']:
        if c.get('resolved_20s_by_in_library_arm') is not False: continue
        mp = c['model_path'] if os.path.isabs(c['model_path']) else os.path.join('/Users/adis/Workspace/pgm-records', c['model_path']); model, binding = CORE.read_uai(mp); iw = induced_width_minfill(model); K = sum(model['cards'][v] for v in range(len(model['cards'])) if v not in model['evidence'])
        cands.append(dict(name=c['case'], family=c['family'], model=mp, model_sha256=binding['model_sha256'], evid_sha256=binding['evidence_sha256'], registry_model_sha256=c.get('raw_model_sha256'), variables=len(model['cards']), K=K, cards=sorted(set(model['cards'])), pairwise_factors=sum(1 for f in model['factors'] if len(f['scope']) == 2), evidence=len(model['evidence']), induced_width_minfill=iw, exposure=('exposed' if c.get('exposed') else 'unexposed'), hash_order=hashlib.sha256(c['case'].encode()).hexdigest()))
    cands.sort(key=lambda x: (-x['induced_width_minfill'], x['hash_order'])); per = {}; chosen = []
    for x in cands:
        if per.get(x['family'], 0) >= 2 or len(chosen) >= 8: continue
        per[x['family']] = per.get(x['family'], 0) + 1; chosen.append(x)
    sel = dict(rule=__doc__, census_sha256=hashlib.sha256(open(os.path.join(RD, 'external/CANDIDATE_CENSUS_draft.json'), 'rb').read()).hexdigest(), candidates_unresolved=cands, selected=chosen, n_selected=len(chosen), shortfall=(8 - len(chosen)), shortfall_reasons=['Protein (8 instances): 4-26 exact zeros each fail the positivity clause; never completed by any in-library arm; excluded by the frozen rule, not substituted'] if len(chosen) < 8 else [], utc=time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()))
    json.dump(sel, open(os.path.join(RD, 'external/EXTERNAL_SELECTION.json'), 'w'), indent=1)
    for x in chosen: print(x['name'], x['family'], 'n', x['variables'], 'K', x['K'], 'iw', x['induced_width_minfill'], x['exposure'], x['model_sha256'][:12])
    print('selected', len(chosen), 'of', len(cands), 'unresolved candidates')

if __name__ == '__main__': main()
