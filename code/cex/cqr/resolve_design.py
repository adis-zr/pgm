#!/usr/bin/env python
"""resolve_design.py -- MATERIALIZE the PROPOSED scored-campaign design (benchmark_expansion.txt sections 3-7, 9; BENCHMARK_DESIGN_DRAFT.json)
into a RESOLVED manifest: PROPOSED_RESOLVED_NOT_FROZEN_NOT_LAUNCHED.

This script runs NO solver, NO inference, NO timing. It only reads frozen inputs (the design draft, the preserved legacy dev manifest, the
acquired external selections, the baseline availability record, the generator / registry / task-language sources), hashes files on disk,
parses model headers / evidence with the SHARED reader (cex/newarm/core.read_uai) where a public rule needs cardinalities and free variables,
and writes ONE JSON + ONE Markdown file under --out. Nothing else is created; no existing file is modified. Freezing requires a SEPARATE
decision after review; this output is not an executable scored manifest and its cells are not scheduled.

Public rules materialized here (every tie rule is stated in the output):
  * task identity   semantic_task_id = sha256(model_sha256 | evidence_sha256 | query_sha256-or-'all_singletons' | epsilon | delta | mode)
                    representation_id = sha256(representation_kind | model_sha256 | evidence_sha256 | transformation_sha256-or-'')
                    run_id = sha256(semantic_task_id | arm | budget_s | seed_index | ENVIRONMENT_PLACEHOLDER)   (only on RESOLVED cells)
  * salted order    key(model) = sha256(SALT + '|' + model_sha256) ascending; SALT = sha256 of the received prompt file (packet SHA256SUMS)
  * query transfer  h(name,k) = int(sha256(SALT|name|k), 16); v1 = free[h1 mod |free|] state h4 mod card; v2 = free[h2 mod |free|] (v2 != v1:
                    smallest forward shift t >= 0), state h5 mod card; v3 = free[h3 mod |free|] (not in {v1,v2}: smallest forward shift);
                    Q_cond = P(v1 = s1 | v2 = s2); Q_bounded = parity over {v1,v2,v3} with bit h8 mod 2 if all three binary, else joint over
                    (v1, v3) with states h6 mod card(v1), h7 mod card(v3). free = ORIGINAL variables not in the original evidence.
  * constructed     slot index i over the 96 slots in (family, n, regime, seed_index) order; r = i mod 8; query kind = KINDS[r mod 4];
                    evidence regime = EVIDENCE[r div 4]; KINDS = selected_singleton, all_singletons, selected_pair_joint, parity_or_modular_sum;
                    EVIDENCE = no_evidence, nontrivial_evidence.
"""
import argparse, json, hashlib, os, sys, lzma, datetime, importlib.util
from collections import Counter, OrderedDict

HERE = os.path.dirname(os.path.abspath(__file__))              # <code>/cex/cqr
CODE = os.path.dirname(os.path.dirname(HERE))                  # <code>
NEWARM = os.path.join(os.path.dirname(HERE), 'newarm')
for _p in (HERE, NEWARM):
    if _p not in sys.path: sys.path.insert(0, _p)
import core                                                    # the SHARED UAI reader (cex/newarm/core.py)
import solve as _cqr_solve                                     # noqa: F401 -- must be imported BEFORE the registry so that 'solve' is cex/cqr/solve.py (the registry inserts cex/pac first)
import generators as GEN
_spec = importlib.util.spec_from_file_location('cqr_registry', os.path.join(HERE, 'registry.py')); REG = importlib.util.module_from_spec(_spec); _spec.loader.exec_module(REG)

SCHEMA = 'proposed_scored_manifest/v1 (resolved from proposed_benchmark_design/v1)'
STATUS = 'PROPOSED_RESOLVED_NOT_FROZEN_NOT_LAUNCHED'
FREEZE_STATEMENT = ('This manifest RESOLVES the proposed design against the inputs available on disk on the date recorded. It is NOT frozen and NOT launched: '
                    'no seed root, no environment identity, no arm artifact identity and no scored input hash is asserted as final. Freezing (writing the query files, '
                    'generating the held-out constructed inputs, binding R0/N1/G0/B0 artifact identities, the environment and the seed root) requires a SEPARATE '
                    'decision after review of this document. No cell listed here is scheduled by this file.')
ENV_PLACEHOLDER = 'ENVIRONMENT_IDENTITY_PENDING_FREEZE'
SALT_EXPECTED = '9ad09647fa9ee82e18e308fd6c5171b26f048b4891204b6446b54087b7508b31'
EPS, DELTA, MODE = '1/200', '1/1000000', 'PAC_EPS'
KINDS = ('selected_singleton', 'all_singletons', 'selected_pair_joint', 'parity_or_modular_sum')
EVIDENCE = ('no_evidence', 'nontrivial_evidence')
LEGACY_EXPLICIT_COHORTS = ('external_core', 'qgrid', 'CBI_UAI', 'SF_small')
NATIVE_COHORTS = ('CBI', 'H4_native', 'SF_native')
ESTABLISHED_ARMS = ('LIBDAI_EXACT', 'LBP', 'WMB', 'IJGP', 'PGMAX_SUMPRODUCT_BP', 'MERLIN_CTE')
DEEP_CONSTRUCTED_N, DEEP_CONSTRUCTED_SEED_INDEX = 64, 0        # DECLARED HERE (the draft fixes only 'one per family, regimes balanced'); flagged for review in the gaps
ABLATION_N, ABLATION_SEED_INDEX = 32, 0                        # given by the design: one predeclared size/seed per family, both regimes


# ----------------------------------------------------------------------------------------------------------------------------- helpers
def sha256_bytes(b): return hashlib.sha256(b).hexdigest()
def sha256_file(p):
    h = hashlib.sha256()
    with open(p, 'rb') as f:
        for chunk in iter(lambda: f.read(1 << 20), b''): h.update(chunk)
    return h.hexdigest()
def sha256_str(s): return hashlib.sha256(s.encode()).hexdigest()
def canonical(spec): return json.dumps(spec, sort_keys=True, separators=(',', ':'))
def qsha(spec): return sha256_str(canonical(spec))
def semantic_id(model_sha, ev_sha, query_sha_or_all, eps, delta, mode):
    if not model_sha or not ev_sha: return None
    return sha256_str('|'.join([model_sha, ev_sha, query_sha_or_all, str(eps), str(delta), str(mode)]))
def representation_id(kind, model_sha, ev_sha, transformation_sha=''):
    if not model_sha or not ev_sha: return None
    return sha256_str('|'.join([kind, model_sha, ev_sha, transformation_sha or '']))
def salted_key(salt, model_sha): return sha256_str(salt + '|' + model_sha)
def h_name(salt, name, k): return int(sha256_str('%s|%s|%d' % (salt, name, k)), 16)


def uai_header_cards(path):
    """cardinalities from the UAI header only (chunked token scan); used ONLY to classify a pool as binary / nonbinary. The shared reader
    core.read_uai is used for every model whose free variables a public rule needs."""
    buf = b''
    with open(path, 'rb') as f:
        while True:
            chunk = f.read(1 << 16)
            if not chunk: break
            buf += chunk; toks = buf.split()
            if len(toks) >= 2:
                if toks[0] not in (b'MARKOV', b'BAYES'): raise ValueError('not a UAI file: %s' % path)
                n = int(toks[1])
                if len(toks) >= n + 3: return [int(x) for x in toks[2:2 + n]]
    raise ValueError('header incomplete: %s' % path)


class ModelCache:
    def __init__(self): self.c = {}
    def read(self, path):
        if path not in self.c: self.c[path] = core.read_uai(path)
        return self.c[path]


def disk_status(path, expected_sha, base):
    if not path: return dict(on_disk='NO_PATH', resolved_path=None, sha256_on_disk=None)
    p = path if os.path.isabs(path) else os.path.join(base, path)
    if not os.path.exists(p): return dict(on_disk='MISSING', resolved_path=p, sha256_on_disk=None)
    h = sha256_file(p)
    return dict(on_disk=('MATCH' if h == expected_sha else 'CHANGED'), resolved_path=p, sha256_on_disk=h)


def query_transfer_specs(salt, name, cards, evidence, n_original):
    """the public query-transfer rule (module docstring); returns (conditional spec, bounded spec, selection record) -- NO files written"""
    free = [v for v in range(n_original) if v not in evidence]
    rec = dict(name=name, n_original=n_original, n_free=len(free), evidence_count=len(evidence))
    if len(free) < 3: rec['status'] = 'UNAVAILABLE_FEWER_THAN_3_FREE_VARIABLES'; return None, None, rec
    def pick(k, exclude):
        base = h_name(salt, name, k) % len(free); t = 0
        while free[(base + t) % len(free)] in exclude: t += 1
        return free[(base + t) % len(free)], t
    v1, t1 = pick(1, set()); s1 = h_name(salt, name, 4) % cards[v1]
    v2, t2 = pick(2, {v1}); s2 = h_name(salt, name, 5) % cards[v2]
    v3, t3 = pick(3, {v1, v2})
    cond = dict(kind='conditional', event={str(v1): s1}, given={str(v2): s2})
    if all(cards[v] == 2 for v in (v1, v2, v3)):
        bounded = dict(kind='parity', variables=sorted([v1, v2, v3]), bit=h_name(salt, name, 8) % 2); bkind = 'parity'
    else:
        bounded = dict(kind='joint', assign={str(v1): h_name(salt, name, 6) % cards[v1], str(v3): h_name(salt, name, 7) % cards[v3]}); bkind = 'joint'
    rec.update(status='RESOLVED', v1=v1, v2=v2, v3=v3, cards=[cards[v1], cards[v2], cards[v3]], shifts=dict(v1=t1, v2=t2, v3=t3), bounded_kind=bkind)
    spec_c = dict(mode=MODE, queries=[cond], epsilon=EPS, delta=DELTA)
    spec_b = dict(mode=MODE, queries=[bounded], epsilon=EPS, delta=DELTA)
    return spec_c, spec_b, rec


def inline_spec(spec):
    return dict(query_spec=spec, query_canonical_json=canonical(spec), query_sha256=qsha(spec), canonical_rule="json.dumps(spec, sort_keys=True, separators=(',', ':')) with no trailing newline; the freeze step writes exactly query_canonical_json to <model>.uai.query.json")


def original_singletons_spec(n_original):
    """all ORIGINAL-literal singleton marginals of a converted WCNF: singleton(v, a) for v < n_original, a in {0,1}; auxiliaries excluded"""
    return dict(mode=MODE, queries=[dict(kind='singleton', variable=v, state=a) for v in range(n_original) for a in (0, 1)], epsilon=EPS, delta=DELTA)


# ----------------------------------------------------------------------------------------------------------------------------- main
def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--out', required=True)
    ap.add_argument('--packet', default='/Users/adis/Workspace/pgm/docs/handoff-received-2026-11-15-cqr/packet')
    ap.add_argument('--legacy-manifest', default='/Users/adis/Workspace/pgm-repair-2026-11-13/code/runs/mdi_2026-10-28/PAC_REPAIR_2026-11-13/admission_v6/manifest_full_dev_v42/CAMPAIGN_MANIFEST_dev.json')
    ap.add_argument('--legacy-code', default='/Users/adis/Workspace/pgm-repair-2026-11-13/code', help='base for relative model paths of the legacy manifest')
    ap.add_argument('--cqr-run', default=os.path.join(CODE, 'runs/mdi_2026-10-28/CQR_2026-11-15'))
    a = ap.parse_args()
    out_dir = a.out if os.path.isabs(a.out) else os.path.join(CODE, a.out); os.makedirs(out_dir, exist_ok=True)
    mismatches = []; gaps = []; notes = []
    def mismatch(s): mismatches.append(s); print('MISMATCH:', s)

    # ---- inputs (read-only) and their hashes
    paths = dict(draft=os.path.join(a.packet, 'BENCHMARK_DESIGN_DRAFT.json'), expansion=os.path.join(a.packet, 'benchmark_expansion.txt'), build_script=os.path.join(a.packet, 'build_benchmark_design.py'),
                 prompt=os.path.join(a.packet, 'CLAUDE_CQR_IMPLEMENTATION_AND_BENCHMARK_PROMPT.txt'), legacy_manifest=a.legacy_manifest,
                 uai_selection=os.path.join(a.cqr_run, 'external/UAI2022_SELECTION.json'), mc_selection=os.path.join(a.cqr_run, 'external/MC2024_SELECTION.json'),
                 uai_inventory=os.path.join(a.cqr_run, 'external/UAI2022_FINAL_MAR_INVENTORY.json'), mc_inventory=os.path.join(a.cqr_run, 'external/MC2024_TRACK2_INVENTORY.json'),
                 downloads=os.path.join(a.cqr_run, 'external/DOWNLOADS.json'), conversion_results=os.path.join(a.cqr_run, 'external/wmc_uai/CONVERSION_RESULTS.json'),
                 baseline_availability=os.path.join(a.cqr_run, 'baselines/BASELINE_AVAILABILITY.json'),
                 generators_py=os.path.join(HERE, 'generators.py'), registry_py=os.path.join(HERE, 'registry.py'), task_py=os.path.join(HERE, 'task.py'), core_py=os.path.join(NEWARM, 'core.py'), this_script=os.path.abspath(__file__))
    input_hashes = {k: dict(path=p, sha256=sha256_file(p), bytes=os.path.getsize(p)) for k, p in paths.items()}
    SALT = input_hashes['prompt']['sha256']
    if SALT != SALT_EXPECTED: mismatch('SALT: sha256 of the prompt file %s != the recorded selection salt %s' % (SALT, SALT_EXPECTED))
    draft = json.load(open(paths['draft'])); legacy = json.load(open(paths['legacy_manifest'])); uai_sel = json.load(open(paths['uai_selection'])); mc_sel = json.load(open(paths['mc_selection']))
    conv = json.load(open(paths['conversion_results'])); avail = json.load(open(paths['baseline_availability']))
    for nm, sel in (('UAI2022_SELECTION', uai_sel), ('MC2024_SELECTION', mc_sel)):
        if sel.get('salt') != SALT: mismatch('%s salt %s != SALT' % (nm, sel.get('salt')))
    generator_sha = input_hashes['generators_py']['sha256']
    legacy_task = legacy['task']
    if legacy_task.get('epsilon') != EPS or legacy_task.get('delta') != DELTA: mismatch('legacy task contract %s != (%s, %s)' % (legacy_task, EPS, DELTA))
    cache = ModelCache()
    draft_primary_ids = [s['slot_id'] for s in draft['primary_task_slots']]; draft_by_id = {s['slot_id']: s for s in draft['primary_task_slots']}

    # =========================================================================================== PRIMARY (A): 105 legacy explicit rows + 16 historic unavailable rows
    legacy_rows = []; historic_unavailable = []
    for r in legacy['inventory']:
        if r['cohort'] in NATIVE_COHORTS: continue
        if r['cohort'] in LEGACY_EXPLICIT_COHORTS and r.get('model_sha256'):
            ds = disk_status(r.get('model_path'), r['model_sha256'], a.legacy_code); es = disk_status(r.get('evidence_path'), r.get('evidence_sha256'), a.legacy_code)
            slot_id = 'legacy/%s/%s' % (r['cohort'], r['case_id'])
            if slot_id not in draft_by_id: mismatch('legacy row %s not among the draft primary slots' % slot_id)
            elif draft_by_id[slot_id]['legacy_model_sha256'] != r['model_sha256']: mismatch('draft legacy_model_sha256 differs for %s' % slot_id)
            if r.get('evidence_path') and r.get('model_path') and r['evidence_path'] != r['model_path'] + '.evid': mismatch('%s: evidence_path is not model_path + .evid (the shared reader reads model_path + .evid)' % slot_id)
            row = OrderedDict(slot_id=slot_id, population='primary', group='A_legacy_explicit', cohort=r['cohort'], case_id=r['case_id'], name=r['case_id'], family=r.get('family'), legacy_status=r['status'],
                              model_path=ds['resolved_path'], evidence_path=(es['resolved_path'] if r.get('evidence_path') else None), model_sha256=r['model_sha256'], evidence_sha256=r.get('evidence_sha256'),
                              model_on_disk=ds['on_disk'], model_sha256_on_disk=ds['sha256_on_disk'], evidence_on_disk=es['on_disk'], evidence_sha256_on_disk=es['sha256_on_disk'],
                              representation_kind='uai_table', task='all original singleton marginals under original evidence', query='all_singletons', query_sha256=None, epsilon=EPS, delta=DELTA, mode=MODE,
                              is_core46=(r['cohort'] == 'external_core'), comparison=['R0', 'N1'], legacy_extra={k: r[k] for k in ('generator', 'source_instance', 'source_sha256', 'panel', 'panel_sha256', 'blocks_sha256', 'native_specialists') if k in r})
            row['semantic_task_id'] = semantic_id(row['model_sha256'], row['evidence_sha256'], 'all_singletons', EPS, DELTA, MODE)
            row['representation_id'] = representation_id('uai_table', row['model_sha256'], row['evidence_sha256'])
            row['availability'] = 'RESOLVED' if (ds['on_disk'] == 'MATCH' and es['on_disk'] == 'MATCH') else 'UNAVAILABLE_INPUT'
            if row['availability'] != 'RESOLVED': gaps.append(dict(kind='legacy_input', slot_id=slot_id, model_on_disk=ds['on_disk'], evidence_on_disk=es['on_disk']))
            legacy_rows.append(row)
        else:
            ds = disk_status(r.get('model_path'), r.get('model_sha256'), a.legacy_code)
            historic_unavailable.append(OrderedDict(slot_id='legacy_historic_unavailable/%s/%s' % (r['cohort'], r['case_id']), cohort=r['cohort'], case_id=r['case_id'], legacy_status=r['status'], note=r.get('note') or r.get('provenance'),
                                                    model_path=r.get('model_path'), model_sha256=r.get('model_sha256'), model_on_disk=ds['on_disk'], source_instance=r.get('source_instance'), source_sha256=r.get('source_sha256'),
                                                    counted_in_241=False, scheduled=False, visibility='kept visible as a historic unavailable row (benchmark_expansion section 1)'))
    if len(legacy_rows) != 105: mismatch('legacy explicit rows: %d != 105' % len(legacy_rows))
    core46 = [r for r in legacy_rows if r['is_core46']]
    if len(core46) != 46: mismatch('core rows: %d != 46' % len(core46))
    if len(historic_unavailable) != 16: notes.append('historic unavailable legacy rows found: %d (expected 2 inaccessible external_core + 2 selector_transfer_additions + 9 CBI_UAI + 3 SF_small = 16)' % len(historic_unavailable))
    for hr in historic_unavailable:
        if hr['model_on_disk'] in ('MISSING', 'CHANGED'):
            gaps.append(dict(kind='legacy_historic_row_input', slot_id=hr['slot_id'], model_on_disk=hr['model_on_disk'], legacy_status=hr['legacy_status'],
                             statement='historic legacy row %s (%s) has a recorded model_path that is %s on disk and a null recorded hash; it stays a historic unavailable row (not in the 241, no cells), exactly as in the preserved manifest' % (hr['case_id'], hr['legacy_status'], hr['model_on_disk'])))

    # =========================================================================================== PRIMARY (B): 96 constructed slots (DEFERRED; no files generated)
    constructed = []; i = 0
    for fid in GEN.FAMILIES:
        for n in (32, 64):
            for regime in ('favorable', 'near_miss'):
                for seed_index in (0, 1):
                    draft_id = 'mechanism/%s/n%d/%s/seed%d' % (fid, n, 'premise_valid' if regime == 'favorable' else 'near_miss', seed_index)
                    d = draft_by_id.get(draft_id)
                    if d is None: mismatch('constructed slot %s not in the draft' % draft_id)
                    r = i % 8
                    constructed.append(OrderedDict(slot_id='constructed/%s/n%d/%s/seed_index%d' % (fid, n, regime, seed_index), draft_slot_id=draft_id, population='primary', group='B_constructed', cohort='constructed', slot_index=i,
                                                   family_id=fid, family=(d or {}).get('family'), n=n, regime=regime, draft_regime=('premise_valid' if regime == 'favorable' else 'near_miss (draft: perturbed/near-miss)'), seed_index=seed_index, seed=None,
                                                   heldout_performance_family=(fid in GEN.RESERVED_PERFORMANCE_FAMILIES), generator='cex/cqr/generators.py generate(family, n, regime, seed)', generator_sha256=generator_sha, generator_version=GEN.GENERATOR_VERSION,
                                                   materialization='DEFERRED_UNTIL_HELDOUT_SEED_ROOT_FIXED', query_schedule=dict(rule='r = slot_index mod 8; query_kind = KINDS[r mod 4]; evidence_regime = EVIDENCE[r div 4]', r=r, query_kind=KINDS[r % 4], evidence_regime=EVIDENCE[r // 4]),
                                                   ablation_arm=REG.ABLATION_OF_FAMILY[fid], draft_ablation_label=(d or {}).get('ablation'), representation_kind='uai_table+query_spec', model_sha256=None, evidence_sha256=None, query_sha256=None,
                                                   semantic_task_id=None, representation_id=None, epsilon=EPS, delta=DELTA, mode=None, comparison=['G0', 'N1'], availability='DEFERRED_GENERATION'))
                    i += 1
    if len(constructed) != 96: mismatch('constructed slots: %d != 96' % len(constructed))

    # =========================================================================================== PRIMARY (C): 24 external slots
    def draft_uai_id(slot):
        card, ar, z, b = slot.split('|')
        return 'external/uai2022/%s/%s/%s/%s' % (card, 'at_most_2' if ar == 'arity<=2' else 'above_2', 'zero_free' if z == 'zero-free' else 'has_zero', b)
    uai_rows = []
    for s in uai_sel['slots']:
        did = draft_uai_id(s['slot'])
        if did not in draft_by_id: mismatch('UAI slot %s has no draft slot %s' % (s['slot'], did))
        row = OrderedDict(slot_id='external/uai2022/' + s['slot'], draft_slot_id=did, population='primary', group='C_external_uai2022', cohort='new_uai2022', stratum=s['stratum'], bucket=s['bucket'], selection_status=s['status'],
                          representation_kind='uai_table', task='all original singleton marginals with the official evidence', query='all_singletons', query_sha256=None, epsilon=EPS, delta=DELTA, mode=MODE, comparison=['G0', 'N1'], r0_reported_alongside=True)
        if s['status'] == 'SELECTED':
            mp = s['model_path']; ep = s['evidence_path']
            ok = os.path.exists(mp) and os.path.exists(ep)
            msha = sha256_file(mp) if os.path.exists(mp) else None; esha = sha256_file(ep) if os.path.exists(ep) else None
            row.update(name=s['name'], family=s['family'], model_path=mp, evidence_path=ep, model_sha256=msha, evidence_sha256=esha, selection_byte_sha256=s['byte_sha256'], selection_evidence_sha256=s['evidence_sha256'],
                       model_on_disk=('MATCH' if msha == s['byte_sha256'] else ('MISSING' if msha is None else 'CHANGED')), evidence_on_disk=('MATCH' if esha == s['evidence_sha256'] else ('MISSING' if esha is None else 'CHANGED')),
                       normalized_model_evidence_sha256=s['normalized_model_evidence_sha256'], n_vars=s['n_vars'], n_factors=s['n_factors'], evidence_count=s['evidence_count'], max_arity_nonconstant=s['max_arity_nonconstant'], file_bytes=s['file_bytes'],
                       cardinality_class=s['stratum'].split('|')[0])
            if ep != mp + '.evid': mismatch('UAI %s: evidence_path != model_path + .evid' % s['name'])
            row['semantic_task_id'] = semantic_id(msha, esha, 'all_singletons', EPS, DELTA, MODE); row['representation_id'] = representation_id('uai_table', msha, esha)
            row['availability'] = 'RESOLVED' if (ok and row['model_on_disk'] == 'MATCH' and row['evidence_on_disk'] == 'MATCH') else 'UNAVAILABLE_INPUT'
            if row['availability'] != 'RESOLVED': gaps.append(dict(kind='external_uai_input', slot_id=row['slot_id'], model_on_disk=row['model_on_disk'], evidence_on_disk=row['evidence_on_disk']))
        else:
            row.update(name=None, model_sha256=None, evidence_sha256=None, semantic_task_id=None, representation_id=None, availability='UNAVAILABLE_INPUT', unavailable_reason=s['status'], note=s.get('note'), archive_models_in_stratum=s.get('archive_models_in_stratum'))
        uai_rows.append(row)
    if len(uai_rows) != 16: mismatch('UAI slots: %d != 16' % len(uai_rows))
    uai_resolved = [r for r in uai_rows if r['availability'] == 'RESOLVED']
    if len(uai_resolved) != 6: mismatch('UAI resolved: %d != 6' % len(uai_resolved))
    gaps.append(dict(kind='external_uai_empty_strata', count=sum(1 for r in uai_rows if r['availability'] != 'RESOLVED'), slots=[r['slot_id'] for r in uai_rows if r['availability'] != 'RESOLVED'],
                     statement='10 of the 16 UAI 2022 FINAL MAR strata slots are UNAVAILABLE_STRATUM_EMPTY (6 strata have no archive model; the binary|arity>2|zero-free stratum has only legacy duplicates); the predeclared round-robin was NOT applied; the slots stay visible and unfilled'))

    mc_by_name = {s['name']: s for s in mc_sel['slots']}; wmc_rows = []
    for c in conv['conversions']:
        s = mc_by_name.get(c['name']); b, k = c['slot'].split('|'); did = 'external/wmc2024/family_slot%s/%s' % (k, b)
        if did not in draft_by_id: mismatch('WMC slot %s has no draft slot %s' % (c['slot'], did))
        sidecar = json.load(open(c['sidecar'])) if os.path.exists(c['sidecar']) else None
        msha = sha256_file(c['uai_path']) if os.path.exists(c['uai_path']) else None; esha = sha256_file(c['evid_path']) if os.path.exists(c['evid_path']) else None
        ssha = sha256_file(c['sidecar']) if os.path.exists(c['sidecar']) else None
        xz_sha = sha256_file(c['cnf_xz_path']) if os.path.exists(c['cnf_xz_path']) else None
        dec_sha = sha256_bytes(lzma.open(c['cnf_xz_path'], 'rb').read()) if os.path.exists(c['cnf_xz_path']) else None
        n_orig = sidecar['n_original_vars'] if sidecar else None; n_aux = sidecar['n_auxiliary_vars'] if sidecar else None
        spec = original_singletons_spec(n_orig) if n_orig else None
        row = OrderedDict(slot_id='external/wmc2024/' + c['slot'], draft_slot_id=did, population='primary', group='C_external_wmc2024', cohort='new_wmc2024', bucket=b, bucket_position=int(k), selection_status=(s or {}).get('status'),
                          name=c['name'], family=(s or {}).get('family'), family_mapped=(s or {}).get('family_mapped'), draft_family_slot_note='family_slot in the draft id is POSITIONAL here: the organizer family mapping covers 5/200 instances only (MC2024_SELECTION.coverage_deficit); rows are instance-level',
                          representation_kind='uai_table_converted_wcnf', model_path=c['uai_path'], evidence_path=c['evid_path'], conversion_sidecar_path=c['sidecar'], model_sha256=msha, evidence_sha256=esha, conversion_sidecar_sha256=ssha,
                          conversion_uai_sha256_recorded=c['uai_sha256'], model_on_disk=('MATCH' if msha == c['uai_sha256'] else ('MISSING' if msha is None else 'CHANGED')), evidence_on_disk=('PRESENT' if esha else 'MISSING'), sidecar_on_disk=('PRESENT' if ssha else 'MISSING'),
                          source_cnf_xz_path=c['cnf_xz_path'], source_cnf_sha256_recorded=c['cnf_sha256'], source_cnf_xz_sha256_on_disk=xz_sha, source_cnf_decompressed_sha256_on_disk=dec_sha,
                          source_cnf_sha256_matches=('xz_bytes' if xz_sha == c['cnf_sha256'] else ('decompressed_bytes' if dec_sha == c['cnf_sha256'] else 'NO_MATCH')),
                          n_original=n_orig, n_auxiliary=n_aux, n_total_vars=(sidecar or {}).get('n_total_vars'), n_factors=c['n_factors'], table_entries=c['table_entries'], conversion_status=c['status'],
                          conversion_certificate=c.get('certificate'), conversion_pointwise_check=(c.get('pointwise_check') or {}).get('status'), cardinality_class='binary',
                          task='all ORIGINAL-literal singleton marginals (auxiliary OR-gate variables excluded); weighted counts preserved by the conversion certificate', query='original_singletons',
                          query_spec_rule="{'kind':'singleton','variable':v,'state':a} for v in range(n_original) for a in (0,1); mode PAC_EPS; epsilon 1/200; delta 1/1000000; canonical dump json.dumps(spec, sort_keys=True, separators=(',', ':'))",
                          query_count=(2 * n_orig if n_orig else None), query_sha256=(qsha(spec) if spec else None), query_spec_inlined=False, epsilon=EPS, delta=DELTA, mode=MODE, comparison=['G0', 'N1'], r0_reported_alongside=True,
                          selection_bias_note=mc_sel.get('selection_bias_note'))
        row['semantic_task_id'] = semantic_id(msha, esha, row['query_sha256'] or 'original_singletons', EPS, DELTA, MODE); row['representation_id'] = representation_id('uai_table_converted_wcnf', msha, esha, ssha)
        row['availability'] = 'RESOLVED' if (row['model_on_disk'] == 'MATCH' and esha and ssha and c['status'] == 'CONVERTED') else 'UNAVAILABLE_INPUT'
        if row['availability'] != 'RESOLVED': gaps.append(dict(kind='external_wmc_input', slot_id=row['slot_id'], model_on_disk=row['model_on_disk'], conversion_status=c['status']))
        if row['source_cnf_sha256_matches'] == 'NO_MATCH': mismatch('WMC %s: recorded cnf_sha256 matches neither the .xz bytes nor the decompressed bytes on disk' % c['name'])
        wmc_rows.append(row)
    if len(wmc_rows) != 8: mismatch('WMC slots: %d != 8' % len(wmc_rows))
    notes.append('WMC query specs are NOT inlined (up to 20,000 singleton entries); query_sha256 is the sha256 of the canonical dump of the spec produced by query_spec_rule, which the freeze step regenerates byte-identically')

    # =========================================================================================== pools + salted orders
    legacy_pool = []
    for r in legacy_rows:
        if r['availability'] != 'RESOLVED': continue
        cards = uai_header_cards(r['model_path'])
        legacy_pool.append(dict(slot_id=r['slot_id'], name=r['name'], cohort=r['cohort'], model_sha256=r['model_sha256'], evidence_sha256=r['evidence_sha256'], model_path=r['model_path'], n_vars=len(cards), cardinality_class=('binary' if all(c == 2 for c in cards) else 'nonbinary'), key=salted_key(SALT, r['model_sha256']), n_original=len(cards), is_core46=r['is_core46']))
    legacy_pool.sort(key=lambda x: x['key'])
    uai_pool = [dict(slot_id=r['slot_id'], name=r['name'], cohort='new_uai2022', model_sha256=r['model_sha256'], evidence_sha256=r['evidence_sha256'], model_path=r['model_path'], n_vars=r['n_vars'], cardinality_class=r['cardinality_class'], key=salted_key(SALT, r['model_sha256']), n_original=r['n_vars']) for r in uai_resolved]
    uai_pool.sort(key=lambda x: x['key'])
    wmc_pool = [dict(slot_id=r['slot_id'], name=r['name'], cohort='new_wmc2024', model_sha256=r['model_sha256'], evidence_sha256=r['evidence_sha256'], model_path=r['model_path'], n_vars=r['n_total_vars'], cardinality_class='binary', key=salted_key(SALT, r['model_sha256']), n_original=r['n_original']) for r in wmc_rows if r['availability'] == 'RESOLVED']
    wmc_pool.sort(key=lambda x: x['key'])
    for p in wmc_pool:   # confirm 'binary' from the header (the conversion rule states cardinality 2 everywhere)
        if any(c != 2 for c in uai_header_cards(p['model_path'])): mismatch('WMC %s: non-binary cardinality in the converted UAI header' % p['name'])
    external_pool = sorted(uai_pool + wmc_pool, key=lambda x: x['key'])
    pools_record = {nm: [dict(rank=i, name=p['name'], cohort=p['cohort'], cardinality_class=p['cardinality_class'], salted_key=p['key'], model_sha256=p['model_sha256']) for i, p in enumerate(pool)] for nm, pool in (('legacy_105', legacy_pool), ('new_uai2022_resolved', uai_pool), ('new_wmc2024', wmc_pool), ('external_combined', external_pool))}

    def balanced_pick(pool, k_each=2):
        bins = [p for p in pool if p['cardinality_class'] == 'binary']; nons = [p for p in pool if p['cardinality_class'] == 'nonbinary']
        chosen = bins[:k_each] + nons[:k_each]; fill_note = None
        if len(nons) < k_each:
            need = k_each - len(nons); extra = bins[k_each:k_each + need]; chosen += extra; fill_note = 'pool lacks %d nonbinary model(s); the next %d binary model(s) by salted order were taken instead: %s' % (need, len(extra), [e['name'] for e in extra])
        if len(bins) < k_each:
            need = k_each - len(bins); extra = nons[k_each:k_each + need]; chosen += extra; fill_note = (fill_note or '') + ' pool lacks %d binary model(s); the next %d nonbinary were taken: %s' % (need, len(extra), [e['name'] for e in extra])
        chosen.sort(key=lambda x: x['key'])
        return chosen, fill_note

    # =========================================================================================== PRIMARY (D): 16 query-transfer slots
    qt_legacy, qt_note_l = balanced_pick(legacy_pool); qt_ext, qt_note_e = balanced_pick(external_pool)
    qt_sources = sorted(qt_legacy, key=lambda x: x['key']) + sorted(qt_ext, key=lambda x: x['key'])
    if len(qt_sources) != 8: mismatch('query-transfer source models: %d != 8' % len(qt_sources))
    qt_rows = []; qt_selection_records = []
    for mi, src in enumerate(qt_sources):
        model, binding = cache.read(src['model_path'])
        if binding['model_sha256'] != src['model_sha256'] or binding['evidence_sha256'] != src['evidence_sha256']: mismatch('query-transfer source %s: shared-reader hashes differ from the recorded ones' % src['name'])
        spec_c, spec_b, rec = query_transfer_specs(SALT, src['name'], model['cards'], model['evidence'], src['n_original']); rec.update(source_slot_id=src['slot_id'], cohort=src['cohort'], salted_key=src['key'], model_slot=mi); qt_selection_records.append(rec)
        for qi, (label, spec, draft_label) in enumerate((('selected_conditional_event', spec_c, 'selected_conditional_event'), ('pair_joint_or_parity', spec_b, 'pair_joint_or_modular_sum'))):
            did = 'query_transfer/model_slot%d/%s' % (mi, draft_label)
            if did not in draft_by_id: mismatch('query-transfer slot %s not in the draft' % did)
            row = OrderedDict(slot_id='query_transfer/%s/%s/%s' % (src['cohort'], src['name'], label), draft_slot_id=did, population='primary', group='D_query_transfer', cohort='query_transfer', source_slot_id=src['slot_id'], source_cohort=src['cohort'], name=src['name'], model_slot=mi,
                              query_index=qi, query_label=label, representation_kind='uai_table+query_spec', model_path=src['model_path'], evidence_path=src['model_path'] + '.evid', model_sha256=src['model_sha256'], evidence_sha256=src['evidence_sha256'],
                              salted_key=src['key'], epsilon=EPS, delta=DELTA, mode=MODE, comparison=['G0', 'N1'], new_independent_model=False, selection=rec)
            if spec is None:
                row.update(query_sha256=None, semantic_task_id=None, representation_id=None, availability='UNAVAILABLE_INPUT', unavailable_reason=rec['status'])
            else:
                row.update(inline_spec(spec)); row['semantic_task_id'] = semantic_id(src['model_sha256'], src['evidence_sha256'], row['query_sha256'], EPS, DELTA, MODE)
                row['representation_id'] = representation_id('uai_table+query_spec', src['model_sha256'], src['evidence_sha256'], row['query_sha256']); row['availability'] = 'RESOLVED'
            qt_rows.append(row)
    if len(qt_rows) != 16: mismatch('query-transfer slots: %d != 16' % len(qt_rows))
    qt_rule = dict(source_models='4 legacy (first 2 binary + first 2 nonbinary by salted order over the 105 legacy explicit rows with model file MATCH) + 4 new external (first 2 binary + first 2 nonbinary by salted order over the 6 resolved UAI + 8 converted WMC)',
                   order='sha256(SALT|model_sha256) ascending; for WMC model_sha256 is the sha256 of the CONVERTED .uai (the representation every arm reads); the source CNF sha256 is recorded separately on the slot',
                   cardinality_class='binary iff every UAI header cardinality == 2 (header scan); free variables and states via core.read_uai', legacy_fill_note=qt_note_l, external_fill_note=qt_note_e,
                   queries='per source model: conditional event P(v1=s1 | v2=s2) and parity over {v1,v2,v3} (all binary) else joint over (v1,v3); indices by h(name,k) (module docstring); each query is its own semantic task (16 slots)',
                   declared_by_this_resolver='the received rule fixes v1/v2/v3 (h1..h3), s1 (h4), s2 (h5) and the parity-vs-joint dispatch; this resolver DECLARES the remaining details: collision rule = smallest forward shift in the free list, parity bit = h(name,8) mod 2, joint states = h(name,6) mod card(v1) and h(name,7) mod card(v3); confirm before freeze',
                   files='NOT written here; the freeze step writes query_canonical_json byte-identically to <model>.uai.query.json (model files are the frozen inputs; the query file sits beside them or in a declared query directory)')

    # =========================================================================================== CLOSEST-METHOD panels: 12 source models -> 12 normalizer_dis + 12 bounded_query_osstar
    closest_sources = legacy_pool[:4] + uai_pool[:4] + wmc_pool[:4]
    if len(uai_pool) < 4: mismatch('UAI pool has %d < 4 resolved models for the closest panel' % len(uai_pool))
    dis_status = avail['arms']['DIS']['status']; os_status = avail['arms']['OS_STAR']['status']
    dis_impl = 'AVAILABLE_BINARY_UNDER_EMULATION_NOT_QUALIFIED' if (dis_status == 'AVAILABLE_BINARY' and not avail['arms']['DIS']['levels'].get('qualified')) else dis_status
    dis_cell_status = 'UNAVAILABLE_PENDING_ADAPTER_QUALIFICATION' if dis_impl == 'AVAILABLE_BINARY_UNDER_EMULATION_NOT_QUALIFIED' else ('RESOLVED' if dis_status == 'AVAILABLE_QUALIFIED' else 'UNAVAILABLE_' + dis_status)
    os_cell_status = 'UNAVAILABLE_NO_IMPLEMENTATION' if os_status == 'UNAVAILABLE_NO_IMPLEMENTATION' else ('RESOLVED' if os_status == 'AVAILABLE_QUALIFIED' else 'UNAVAILABLE_' + os_status)
    norm_spec = dict(mode=MODE, normalizer_task=True, queries=[], epsilon=EPS, delta=DELTA); norm_inline = inline_spec(norm_spec)
    closest_rows = []
    for ci, src in enumerate(closest_sources):
        cohort_rank = ci % 4; deep = cohort_rank < 2
        model, binding = cache.read(src['model_path'])
        if binding['model_sha256'] != src['model_sha256']: mismatch('closest source %s: reader hash differs' % src['name'])
        _, spec_b, rec = query_transfer_specs(SALT, src['name'], model['cards'], model['evidence'], src['n_original'])
        base = dict(population='closest', source_slot_id=src['slot_id'], source_cohort=src['cohort'], name=src['name'], cohort_rank=cohort_rank, salted_key=src['key'], model_path=src['model_path'], evidence_path=src['model_path'] + '.evid',
                    model_sha256=src['model_sha256'], evidence_sha256=src['evidence_sha256'], deep_panel=deep, derived_task=True, new_independent_model=False)
        nrow = OrderedDict(slot_id='closest/normalizer_dis/%s/%s' % (src['cohort'], src['name']), **base); nrow.update(cohort='normalizer_dis', contract='Z with RELATIVE error 1/200 and delta 1e-6: certify c only if L > 0 and c in [(1-eps) U, (1+eps) L]; query-only cancellation of unknown component normalizers and TV-only surrogates DISABLED for N1',
                                                                                                                      representation_kind='uai_table+query_spec(normalizer)', normalizer_task=True, epsilon=EPS, delta=DELTA, mode=MODE, arms=['N1_CQR', 'DIS'], dis_implementation_status=dis_impl, dis_cell_status=dis_cell_status)
        nrow.update(norm_inline); nrow['semantic_task_id'] = semantic_id(src['model_sha256'], src['evidence_sha256'], nrow['query_sha256'], EPS, DELTA, MODE); nrow['representation_id'] = representation_id('uai_table+query_spec(normalizer)', src['model_sha256'], src['evidence_sha256'], nrow['query_sha256']); nrow['availability'] = 'RESOLVED'
        brow = OrderedDict(slot_id='closest/bounded_query_osstar/%s/%s' % (src['cohort'], src['name']), **base); brow.update(cohort='bounded_query_osstar', contract='bounded expectation (indicator of the parity / joint event) with additive error 1/200, delta 1e-6; OS* = exact sampling + separately qualified fixed-sample bounded-mean wrapper (draw count fixed before drawing; DEADLINE if not attained)',
                                                                                                                             representation_kind='uai_table+query_spec', epsilon=EPS, delta=DELTA, mode=MODE, arms=['N1_CQR', 'OSSTAR'], osstar_implementation_status=os_status, osstar_cell_status=os_cell_status, selection=rec)
        if spec_b is None: brow.update(query_sha256=None, semantic_task_id=None, representation_id=None, availability='UNAVAILABLE_INPUT', unavailable_reason=rec['status'])
        else:
            brow.update(inline_spec(spec_b)); brow['semantic_task_id'] = semantic_id(src['model_sha256'], src['evidence_sha256'], brow['query_sha256'], EPS, DELTA, MODE); brow['representation_id'] = representation_id('uai_table+query_spec', src['model_sha256'], src['evidence_sha256'], brow['query_sha256']); brow['availability'] = 'RESOLVED'
        closest_rows += [nrow, brow]
    if len(closest_rows) != 24: mismatch('closest rows: %d != 24' % len(closest_rows))
    closest_rule = dict(sources='first 4 legacy, first 4 resolved UAI, first 4 WMC by salted order (sha256(SALT|model_sha256)); the 4 legacy are the first 4 regardless of cardinality class (the draft balances only the query-transfer pool)',
                        deep_panel='the first 2 per cohort by salted order (6 models -> 6 DIS + 6 OS* tasks at 120 s)', normalizer_query_spec=norm_inline,
                        bounded_query='the parity / joint query of the same public query-transfer rule applied to the source model (coincides with the query-transfer pair_joint_or_parity task where the same model is selected there: same semantic_task_id, reported once)',
                        dis=dict(status_in_BASELINE_AVAILABILITY=dis_status, implementation_status=dis_impl, cells=dis_cell_status, note='DIS binary runs only under docker --platform linux/amd64 (Rosetta) inside the colima VM; no adapter for the relative-error/risk contract has been qualified; its cells are visible planned slots, NOT scheduled'),
                        osstar=dict(status_in_BASELINE_AVAILABILITY=os_status, cells=os_cell_status, note='no author implementation located; no independent reimplementation written; cells are visible planned slots, NOT scheduled'))
    gaps.append(dict(kind='closest_method_arm', arm='DIS', status=dis_impl, cells_marked=dis_cell_status, statement='DIS author binary executes only under x86-64 emulation (docker/Rosetta in colima); nothing is built or qualified; the normalizer-contract adapter (relative error, risk, anytime intervals) is not qualified'))
    gaps.append(dict(kind='closest_method_arm', arm='OSSTAR', status=os_status, cells_marked=os_cell_status, statement='no OS* implementation (author or labelled independent) exists in this program; the exact-draw bounded-mean wrapper is unqualified'))

    # =========================================================================================== ESTABLISHED comparators: 24 tasks (8 legacy, 8 UAI (6 + 2 unavailable), 8 WMC), 120 s half = first 4 per cohort
    est_rows = []
    def est_row(src, cohort, rank, deep):
        if src is None:
            return OrderedDict(slot_id='established/%s/UNAVAILABLE_slot%d' % (cohort, rank), population='established', source_cohort=cohort, rank=rank, name=None, model_sha256=None, evidence_sha256=None, semantic_task_id=None, representation_id=None,
                               availability='UNAVAILABLE_INPUT', unavailable_reason='the resolved UAI 2022 pool has only 6 models (10 strata slots empty); this comparator slot stays visible and unfilled', deep_120s=deep, arms=list(ESTABLISHED_ARMS))
        q_all = 'all_singletons' if cohort != 'new_wmc2024' else None
        wrow = next((w for w in wmc_rows if w['slot_id'] == src['slot_id']), None)
        qsh = wrow['query_sha256'] if wrow else None
        row = OrderedDict(slot_id='established/%s/%s' % (cohort, src['name']), population='established', source_slot_id=src['slot_id'], source_cohort=cohort, rank=rank, name=src['name'], salted_key=src['key'], model_path=src['model_path'], evidence_path=src['model_path'] + '.evid',
                          model_sha256=src['model_sha256'], evidence_sha256=src['evidence_sha256'], representation_kind=('uai_table_converted_wcnf' if wrow else 'uai_table'),
                          task=('all ORIGINAL-literal singleton marginals; comparator output on auxiliary variables is ignored by the scorer' if wrow else 'all original singleton marginals under original evidence (compatible comparator task)'),
                          query=('original_singletons' if wrow else 'all_singletons'), query_sha256=qsh, epsilon=EPS, delta=DELTA, mode=MODE, arms=list(ESTABLISHED_ARMS), guarantee='UNGUARANTEED (empirical binary64 / float32 points; not certified completions)', deep_120s=deep)
        row['semantic_task_id'] = semantic_id(src['model_sha256'], src['evidence_sha256'], qsh or q_all, EPS, DELTA, MODE); row['representation_id'] = representation_id(row['representation_kind'], src['model_sha256'], src['evidence_sha256'], (wrow or {}).get('conversion_sidecar_sha256', ''))
        row['availability'] = 'RESOLVED'; return row
    for cohort, pool in (('legacy', legacy_pool), ('new_uai2022', uai_pool), ('new_wmc2024', wmc_pool)):
        for rank in range(8): est_rows.append(est_row(pool[rank] if rank < len(pool) else None, cohort, rank, deep=(rank < 4)))
    if len(est_rows) != 24: mismatch('established rows: %d != 24' % len(est_rows))
    est_unavail = [r['slot_id'] for r in est_rows if r['availability'] != 'RESOLVED']
    if est_unavail: gaps.append(dict(kind='established_comparator_input', slots=est_unavail, statement='the UAI pool has 6 resolved models, so 2 of the 8 new-UAI comparator slots are UNAVAILABLE (12 cells at 20 s); their 120 s half is unaffected (first 4 per cohort)'))
    pgmax = avail['arms']['LEGACY']['arms'].get('PGMAX_SUMPRODUCT_BP', {})
    pgmax_link = os.path.join(CODE, '.venv-pgmax'); pgmax_py = os.path.join(pgmax_link, 'bin', 'python')
    pgmax_now = dict(availability_file_status=pgmax.get('status'), venv_symlink_exists=os.path.islink(pgmax_link) or os.path.isdir(pgmax_link), venv_symlink_target=(os.readlink(pgmax_link) if os.path.islink(pgmax_link) else None), interpreter_exists=os.path.exists(pgmax_py))
    gaps.append(dict(kind='established_comparator_arm', arm='PGMAX_SUMPRODUCT_BP', detail=pgmax_now, statement='BASELINE_AVAILABILITY.json recorded UNAVAILABLE_NOT_FOUND (no .venv-pgmax in this worktree at that time); a symlink to the main worktree venv now exists (not a worktree-local build, not re-qualified; no import or run performed here). PGMax cells are listed RESOLVED on that basis and must be re-verified at freeze.'))
    est_rule = dict(tasks='first 8 per cohort by salted order over legacy_105 / new_uai2022_resolved / new_wmc2024; one run at 20 s with all 6 arms; the 120 s half = the first 4 per cohort (12 tasks x 6 arms)',
                    arms=list(ESTABLISHED_ARMS), arm_identities={k: avail['arms']['LEGACY']['arms'][k] for k in ('libDAI_binary', 'Merlin_binary') if k in avail['arms']['LEGACY']['arms']}, verification=False, note='unguaranteed empirical points; availability and output-shape failures stay visible; comparators are not run on parity / conditional / native tasks')

    # =========================================================================================== NATIVE population: 90 slots (CBI 23 from cbi_instances, H4 3 + SF 64 from inventory)
    native_arm_of = {}
    for c in legacy['cells']:
        if c['cohort'] in NATIVE_COHORTS: native_arm_of.setdefault((c['cohort'], c['case_id']), c['arm'])
    native_rows = []
    native_src = [r for r in legacy['cbi_instances']] + [r for r in legacy['inventory'] if r['cohort'] in ('H4_native', 'SF_native')]
    for r in native_src:
        ds = disk_status(r.get('model_path'), r.get('model_sha256'), a.legacy_code); arm = native_arm_of.get((r['cohort'], r['case_id']))
        if arm is None: mismatch('native slot %s/%s has no legacy cell arm' % (r['cohort'], r['case_id']))
        kind = {'CBI': 'native_cbi_instance_json', 'H4_native': 'native_h4_frozen_nodes_packet', 'SF_native': 'native_sf_panel_json'}[r['cohort']]
        ev = r.get('evidence_sha256') or sha256_bytes(b'')
        row = OrderedDict(slot_id='native/%s/%s' % (r['cohort'], r['case_id']), population='native', cohort=r['cohort'], case_id=r['case_id'], arm=arm, legacy_status=r['status'], query_contract=r['task'], representation_kind=kind,
                          model_path=ds['resolved_path'], model_sha256=r.get('model_sha256'), evidence_sha256=r.get('evidence_sha256'), model_on_disk=ds['on_disk'], model_sha256_on_disk=ds['sha256_on_disk'],
                          native_extra={k: r[k] for k in ('native_arm', 'packet', 'sf_r', 'sf_eps', 'panel', 'layer', 'meta') if k in r}, budgets_s=[20, 120], repeats=1,
                          pairing_note='native and explicit views of the same CBI / SF law are paired representation studies, not independent wins (benchmark_expansion section 2)')
        row['semantic_task_id'] = semantic_id(r.get('model_sha256'), ev, 'native_contract:' + r['task'], 'native', 'native', 'NATIVE_CONTRACT'); row['representation_id'] = representation_id(kind, r.get('model_sha256'), ev)
        row['availability'] = 'RESOLVED' if ds['on_disk'] == 'MATCH' else 'UNAVAILABLE_INPUT'
        if row['availability'] != 'RESOLVED': gaps.append(dict(kind='native_input', slot_id=row['slot_id'], model_on_disk=ds['on_disk']))
        native_rows.append(row)
    nc = Counter(r['cohort'] for r in native_rows)
    if len(native_rows) != 90 or nc != Counter(CBI=23, H4_native=3, SF_native=64): mismatch('native slots %s != CBI 23 / H4 3 / SF 64' % dict(nc))
    notes.append('native semantic ids use the literal placeholders epsilon=delta="native" and mode="NATIVE_CONTRACT": every native contract carries its own width / risk in query_contract (CBI width 1/100 delta 0; SF per-panel width; H4 historical conditional width 1/100)')

    # =========================================================================================== CELLS
    primary_rows = legacy_rows + constructed + uai_rows + wmc_rows + qt_rows
    if len(primary_rows) != 241: mismatch('primary slots: %d != 241' % len(primary_rows))
    if sorted(r.get('draft_slot_id', r['slot_id']) for r in primary_rows) != sorted(draft_primary_ids): mismatch('primary slot ids do not match the draft primary_task_slots one-to-one')
    cells = []
    def add_cell(stage, block, row, arm, budget, repeat, availability, arm_status=None):
        tid = row['slot_id']; cid = sha256_str('|'.join([stage, block, tid, arm, str(budget), str(repeat)]))[:16]
        sid = row.get('semantic_task_id'); rid = sha256_str('|'.join([sid, arm, str(budget), str(repeat), ENV_PLACEHOLDER])) if (sid and availability == 'RESOLVED') else None
        cells.append(OrderedDict(cell_id=cid, stage=stage, block=block, task_id=tid, cohort=row.get('cohort'), semantic_task_id=sid, representation_id=row.get('representation_id'), arm=arm, budget_s=budget, repeat=repeat, seed_index=repeat, availability=availability, arm_status=arm_status, run_id=rid))
    def avail_of(row): return row['availability']
    def primary_arms(row): return [REG.R0_ARM if row['group'] == 'A_legacy_explicit' else 'G0_CQR', 'N1_CQR']
    # ---- Stage A (20 s)
    for row in primary_rows:
        for arm in primary_arms(row):
            for rep in range(3): add_cell('A_20s', 'primary_paired', row, arm, 20, rep, avail_of(row))
    for row in legacy_rows: add_cell('A_20s', 'historical_B0', row, REG.B0_ARM, 20, 0, avail_of(row))
    for row in native_rows: add_cell('A_20s', 'native', row, row['arm'], 20, 0, avail_of(row))
    for row in closest_rows:
        for arm in row['arms']:
            for rep in range(3):
                if arm == 'N1_CQR': add_cell('A_20s', 'closest_methods', row, arm, 20, rep, avail_of(row))
                else:
                    st = row['dis_cell_status'] if arm == 'DIS' else row['osstar_cell_status']
                    add_cell('A_20s', 'closest_methods', row, arm, 20, rep, ('RESOLVED' if st == 'RESOLVED' else 'UNAVAILABLE_ARM') if avail_of(row) == 'RESOLVED' else avail_of(row), arm_status=st)
    for row in est_rows:
        for arm in ESTABLISHED_ARMS: add_cell('A_20s', 'established_comparators', row, arm, 20, 0, avail_of(row), arm_status=(pgmax_now['availability_file_status'] + '; symlink now present, unverified' if arm == 'PGMAX_SUMPRODUCT_BP' else None))
    ablation_rows = [c for c in constructed if c['n'] == ABLATION_N and c['seed_index'] == ABLATION_SEED_INDEX]
    if len(ablation_rows) != 24: mismatch('ablation tasks: %d != 24' % len(ablation_rows))
    for row in ablation_rows:
        for rep in range(3): add_cell('A_20s', 'matched_ablation_additional_arm', row, row['ablation_arm'], 20, rep, avail_of(row))
    # ---- Stage B (120 s)
    deep_constructed = []
    for fi, fid in enumerate(GEN.FAMILIES):
        regime = 'favorable' if fi % 2 == 0 else 'near_miss'
        deep_constructed.append(next(c for c in constructed if c['family_id'] == fid and c['n'] == DEEP_CONSTRUCTED_N and c['regime'] == regime and c['seed_index'] == DEEP_CONSTRUCTED_SEED_INDEX))
    deep_external = [next(r for r in uai_rows if r['slot_id'] == p['slot_id']) for p in uai_pool[:4]] + [next(r for r in wmc_rows if r['slot_id'] == p['slot_id']) for p in wmc_pool[:4]]
    qt_sorted = sorted(qt_rows, key=lambda r: (r['salted_key'], r['query_index'])); deep_qt = qt_sorted[:4]
    deep_primary = core46 + deep_constructed + deep_external + deep_qt
    if len(deep_primary) != 70: mismatch('deep primary tasks: %d != 70' % len(deep_primary))
    deep_ids = {r['slot_id'] for r in deep_primary}
    for row in deep_primary:
        for arm in primary_arms(row):
            for rep in range(3): add_cell('B_120s', 'primary_paired', row, arm, 120, rep, avail_of(row))
    for row in core46: add_cell('B_120s', 'historical_B0', row, REG.B0_ARM, 120, 0, avail_of(row))
    for row in native_rows: add_cell('B_120s', 'native', row, row['arm'], 120, 0, avail_of(row))
    for row in closest_rows:
        if not row['deep_panel']: continue
        for arm in row['arms']:
            for rep in range(3):
                if arm == 'N1_CQR': add_cell('B_120s', 'closest_methods', row, arm, 120, rep, avail_of(row))
                else:
                    st = row['dis_cell_status'] if arm == 'DIS' else row['osstar_cell_status']
                    add_cell('B_120s', 'closest_methods', row, arm, 120, rep, ('RESOLVED' if st == 'RESOLVED' else 'UNAVAILABLE_ARM') if avail_of(row) == 'RESOLVED' else avail_of(row), arm_status=st)
    for row in est_rows:
        if not row['deep_120s']: continue
        for arm in ESTABLISHED_ARMS: add_cell('B_120s', 'established_comparators', row, arm, 120, 0, avail_of(row))
    not_planned_120 = [r['slot_id'] for r in primary_rows if r['slot_id'] not in deep_ids]
    deep_rule = dict(core='all 46 external_core legacy tasks', constructed='one per family: n=%d, seed_index=%d, regime favorable for even family index (M01, M03, ...) and near_miss for odd (M02, M04, ...) -> 6/6; n and seed_index are DECLARED HERE (the draft fixes only "one per family, regimes balanced") and need reviewer confirmation before freeze' % (DEEP_CONSTRUCTED_N, DEEP_CONSTRUCTED_SEED_INDEX),
                     external='first 4 resolved UAI + first 4 WMC by salted order', query_transfer='the 16 query-transfer slots ordered by (salted key of the source model, query_index); the first 4 = both queries of the first 2 source models',
                     not_planned_at_120='every other primary task keeps a visible NOT_PLANNED_AT_120 row (count %d); not a failure and not a success' % len(not_planned_120))
    if len(cells) != len({c['cell_id'] for c in cells}): mismatch('duplicate cell_id')
    # ---- run_id coincidences: distinct planned cells that denote the SAME run (same semantic task, arm, budget, seed) -- by construction the closest bounded query of a
    #      source model that is also a query-transfer source IS that query-transfer task; the draft counts both cells; a freeze must execute once and record the reuse
    by_run = {}
    for c in cells:
        if c['run_id']: by_run.setdefault(c['run_id'], []).append(c)
    dup_groups = [grp for grp in by_run.values() if len(grp) > 1]
    duplicate_runs = dict(cells_sharing_a_run_id=sum(len(g) for g in dup_groups), distinct_shared_run_ids=len(dup_groups), redundant_cells_if_executed_once=sum(len(g) - 1 for g in dup_groups),
                          groups=[dict(run_id=g[0]['run_id'], semantic_task_id=g[0]['semantic_task_id'], arm=g[0]['arm'], budget_s=g[0]['budget_s'], seed_index=g[0]['seed_index'], cells=[(c['stage'], c['block'], c['task_id']) for c in g]) for g in dup_groups],
                          statement='these cells are counted as planned slots exactly as the draft counts them; they denote one run each (the OS*-panel bounded query of a source model equals its query-transfer bounded query: same model, evidence, query table, epsilon, delta, mode). At freeze: execute once per run_id and record the reuse on the second cell, or amend the design; the nominal seconds above include the redundant cells')

    # ---- stage tables, totals, allowances (compared to the draft; mismatches recorded, never fudged)
    stage_rows = OrderedDict()
    for st, dkey in (('A_20s', '20s_broad'), ('B_120s', '120s_preselected')):
        rows = OrderedDict()
        for c in cells:
            if c['stage'] != st: continue
            b = rows.setdefault(c['block'], dict(role=c['block'], cells=0, nominal_s=0, budget_s=c['budget_s'], tasks=set(), arms=set(), by_availability=Counter()))
            b['cells'] += 1; b['nominal_s'] += c['budget_s']; b['tasks'].add(c['task_id']); b['arms'].add(c['arm']); b['by_availability'][c['availability']] += 1
        for b in rows.values(): b['tasks'] = len(b['tasks']); b['arms'] = sorted(b['arms']); b['by_availability'] = dict(b['by_availability'])
        drows = {r['role']: r for r in draft['stage_rows'][dkey]}
        for role, b in rows.items():
            d = drows.get(role)
            if d is None: mismatch('%s block %s not in the draft' % (st, role)); continue
            b['draft_cells'] = d['cells']; b['draft_nominal_s'] = d['nominal_s']; b['draft_tasks'] = d['tasks']; b['verification'] = d['verification']
            if (b['cells'], b['nominal_s'], b['tasks']) != (d['cells'], d['nominal_s'], d['tasks']): mismatch('%s/%s: cells %d nominal %d tasks %d vs draft %d / %d / %d' % (st, role, b['cells'], b['nominal_s'], b['tasks'], d['cells'], d['nominal_s'], d['tasks']))
        for role in drows:
            if role not in rows: mismatch('%s: draft block %s has no cells here' % (st, role))
        stage_rows[st] = dict(draft_key=dkey, blocks=list(rows.values()), cells=sum(b['cells'] for b in rows.values()), nominal_s=sum(b['nominal_s'] for b in rows.values()))
    total_cells = sum(s['cells'] for s in stage_rows.values()); nominal = sum(s['nominal_s'] for s in stage_rows.values())
    unguaranteed_s = sum(c['budget_s'] for c in cells if c['block'] == 'established_comparators')
    fixed = draft['fixed_stage_allowances_s']; fixed_total = sum(fixed.values())
    allowance = OrderedDict(solver_nominal_s=nominal, per_child_cleanup_kill_s=5 * total_cells, verification_s=3 * (nominal - unguaranteed_s), unguaranteed_established_comparator_s=unguaranteed_s, fixed_allowances_s=fixed, fixed_total_s=fixed_total)
    allowance['total_allowance_s'] = allowance['solver_nominal_s'] + allowance['per_child_cleanup_kill_s'] + allowance['verification_s'] + fixed_total
    allowance['formula'] = '%d + %d*5 + 3*(%d - %d) + %d = %d' % (nominal, total_cells, nominal, unguaranteed_s, fixed_total, allowance['total_allowance_s'])
    allowance['statement'] = 'ALLOWANCES (hard upper allocations), not runtime forecasts or predictions; no implicit second-matrix contingency is reserved'
    expect = dict(cells=2701, nominal_s=124020, stage_A_cells=2001, stage_B_cells=700, unguaranteed_s=11520, total_allowance_s=493025, per_child=13505, verification=337500, fixed=18000)
    got = dict(cells=total_cells, nominal_s=nominal, stage_A_cells=stage_rows['A_20s']['cells'], stage_B_cells=stage_rows['B_120s']['cells'], unguaranteed_s=unguaranteed_s, total_allowance_s=allowance['total_allowance_s'], per_child=allowance['per_child_cleanup_kill_s'], verification=allowance['verification_s'], fixed=fixed_total)
    for k in expect:
        if got[k] != expect[k]: mismatch('total %s: %s != draft %s' % (k, got[k], expect[k]))
    if draft['totals']['total_allowance_s'] != 493025 or draft['totals']['cells'] != 2701: mismatch('draft totals themselves differ from the expected 2701 / 493025: %s' % draft['totals'])
    verification = dict(expected_from_draft=expect, computed=got, all_match=all(got[k] == expect[k] for k in expect), mismatches=list(mismatches))
    # stage allowance split per the draft (14,400 s build/qualification/references + 1,800 report in Stage A; 1,800 report in Stage B)
    stageA_fixed = fixed['availability_build'] + fixed['qualification'] + fixed['offline_references'] + fixed['report_closeout_package'] // 2; stageB_fixed = fixed['report_closeout_package'] // 2
    def stage_alloc(st, fx):
        s = stage_rows[st]; ung = sum(c['budget_s'] for c in cells if c['stage'] == st and c['block'] == 'established_comparators')
        return dict(nominal_s=s['nominal_s'], cleanup_s=5 * s['cells'], verification_s=3 * (s['nominal_s'] - ung), fixed_s=fx, total_s=s['nominal_s'] + 5 * s['cells'] + 3 * (s['nominal_s'] - ung) + fx)
    allowance['per_stage'] = dict(A_20s=stage_alloc('A_20s', stageA_fixed), B_120s=stage_alloc('B_120s', stageB_fixed))
    for st, dkey in (('A_20s', '20s_broad'), ('B_120s', '120s_preselected')):
        if allowance['per_stage'][st]['total_s'] != draft['stage_totals'][dkey]['total_allowance_s']: mismatch('stage %s allowance %d != draft %d' % (st, allowance['per_stage'][st]['total_s'], draft['stage_totals'][dkey]['total_allowance_s']))

    # ---- counts: source models / semantic tasks / representations / cells, SEPARATELY
    def distinct(rows, key): return len({r[key] for r in rows if r.get(key)})
    all_rows = primary_rows + native_rows + closest_rows + est_rows
    def pop_counts(rows):
        c = Counter(r['availability'] for r in rows); return dict(slots=len(rows), resolved=c.get('RESOLVED', 0), unavailable=c.get('UNAVAILABLE_INPUT', 0), deferred=c.get('DEFERRED_GENERATION', 0), source_models_resolved=distinct(rows, 'model_sha256'), semantic_tasks_resolved=distinct(rows, 'semantic_task_id'), representations_resolved=distinct(rows, 'representation_id'))
    counts = OrderedDict(
        populations=OrderedDict(primary_A_legacy_explicit=pop_counts(legacy_rows), primary_B_constructed=pop_counts(constructed), primary_C_external_uai2022=pop_counts(uai_rows), primary_C_external_wmc2024=pop_counts(wmc_rows), primary_D_query_transfer=pop_counts(qt_rows),
                                primary_total=pop_counts(primary_rows), native=pop_counts(native_rows), closest_normalizer_dis=pop_counts([r for r in closest_rows if r['cohort'] == 'normalizer_dis']), closest_bounded_query_osstar=pop_counts([r for r in closest_rows if r['cohort'] == 'bounded_query_osstar']), established=pop_counts(est_rows),
                                legacy_historic_unavailable_rows=dict(rows=len(historic_unavailable), counted_in_241=False, scheduled=False)),
        source_models=OrderedDict(explicit_resolved_distinct_model_sha256=distinct(legacy_rows + uai_rows + wmc_rows, 'model_sha256'), legacy_explicit=distinct(legacy_rows, 'model_sha256'), new_uai2022=distinct(uai_rows, 'model_sha256'), new_wmc2024_converted=distinct(wmc_rows, 'model_sha256'),
                                  new_wmc2024_source_cnf=distinct(wmc_rows, 'source_cnf_sha256_recorded'), native_distinct_input_files=distinct(native_rows, 'model_sha256'), native_by_cohort={k: distinct([r for r in native_rows if r['cohort'] == k], 'model_sha256') for k in NATIVE_COHORTS},
                                  constructed_deferred_slots_not_yet_models=len(constructed), external_unavailable_slots=sum(1 for r in uai_rows if r['availability'] != 'RESOLVED'),
                                  query_transfer_and_closest_reuse_existing_models=True, note='query-transfer, closest-method and established rows reuse source models already counted; CBI_UAI / SF_small explicit renderings and CBI / SF native inputs are different representations of the same laws (paired, not independent)'),
        semantic_tasks=OrderedDict(resolved_distinct=distinct(all_rows, 'semantic_task_id'), by_population={k: distinct(v, 'semantic_task_id') for k, v in (('primary', primary_rows), ('native', native_rows), ('closest', closest_rows), ('established', est_rows))},
                                   shared_between_populations=len([s for s, n in Counter(r['semantic_task_id'] for r in all_rows if r.get('semantic_task_id')).items() if n > 1]), unresolved_slots=sum(1 for r in all_rows if not r.get('semantic_task_id'))),
        representations=OrderedDict(resolved_distinct=distinct(all_rows, 'representation_id'), by_kind=dict(Counter(r.get('representation_kind') for r in all_rows if r.get('representation_id')))),
        cells=OrderedDict(total=total_cells, by_stage={k: v['cells'] for k, v in stage_rows.items()}, by_availability=dict(Counter(c['availability'] for c in cells)), by_block={('%s/%s' % k): v for k, v in Counter((c['stage'], c['block']) for c in cells).items()},
                          by_arm=dict(Counter(c['arm'] for c in cells)), run_ids_assigned=sum(1 for c in cells if c['run_id']), distinct_run_ids=len(by_run), cells_sharing_a_run_id=duplicate_runs['cells_sharing_a_run_id'], not_planned_at_120_primary_tasks=len(not_planned_120)))

    # ---- remaining materialization gaps
    if dup_groups: gaps.append(dict(kind='duplicate_planned_runs', count_cells=duplicate_runs['cells_sharing_a_run_id'], redundant_cells=duplicate_runs['redundant_cells_if_executed_once'], nominal_s_of_redundant_cells=sum(sum(c['budget_s'] for c in g[1:]) for g in dup_groups), statement=duplicate_runs['statement']))
    gaps.insert(0, dict(kind='heldout_seeds', statement='the 96 constructed slots have seed=null: the held-out seed root is chosen after the policy is fixed (reviewer-owned or independent script); materialization DEFERRED_UNTIL_HELDOUT_SEED_ROOT_FIXED; the four reserved families M03/M05/M09/M12 must not be executed for tuning', generator_sha256=generator_sha))
    gaps.insert(1, dict(kind='constructed_query_schedule_application', statement='generators.generate() emits a family-default query spec; applying the published slot schedule (query kind x evidence regime) is part of the deferred materialization and must be implemented and covered by tiny exact enumeration before freeze; KINDS/EVIDENCE are recorded per slot'))
    gaps.append(dict(kind='circuit_artifact', row=draft['unavailable_circuit_row'], statement='CIRCUIT_ARTIFACT_PENDING: no qualified fixed trained-model/query archive; kept as an explicit unavailable row, zero cells'))
    gaps.append(dict(kind='environment_identity', placeholder=ENV_PLACEHOLDER, statement='run_id binds a placeholder environment identity; host/kernel/compiler/venv identities are bound at freeze; historic timings are not reusable without qualification'))
    gaps.append(dict(kind='arm_artifact_identities', statement='R0 (=%s), B0 (=%s), N1_CQR / G0_CQR / ablation source identities are NOT frozen here; the current cqr source inventory is recorded for reference only' % (REG.R0_ARM, REG.B0_ARM), cqr_source_inventory_now=REG.cqr_source_inventory(CODE)))
    gaps.append(dict(kind='deep_constructed_choice', statement='n=%d / seed_index=%d for the 12 Stage-B constructed tasks is a declaration made by this resolver, not by the draft; confirm or amend before freeze' % (DEEP_CONSTRUCTED_N, DEEP_CONSTRUCTED_SEED_INDEX)))
    gaps.append(dict(kind='wmc_representation_cost', statement='the converted WMC inputs random_179 (30.4 MB, 900,727 factors) and random_185 (17.6 MB) take ~10 s / ~6 s and ~1.0 / 0.6 GB just to parse with the shared exact-rational reader; parsing is charged inside the 20 s / 120 s budget and the 3 GiB sampled RSS contract, so these cells may stop at parse; this is recorded, not pre-judged'))
    gaps.append(dict(kind='legacy_pool_cardinality_classification', statement='binary/nonbinary classification of the 105-model legacy pool used a UAI header scan (not core.read_uai) because four CBI_UAI renderings are 65-164 MB; the 8 selected query-transfer and 12 closest models were parsed with core.read_uai'))
    if not any(g['kind'] == 'legacy_input' for g in gaps): notes.append('all 105 legacy explicit model and evidence files are present on disk with MATCHING sha256; the two selector_transfer_additions rows (Promedus_11 / Promedus_16; historic UNAVAILABLE_INPUT, null hash) are MISSING on disk and remain historic unavailable rows')

    identity_rule = OrderedDict(semantic_task_id="sha256(model_sha256 | evidence_sha256 | query_sha256-or-'all_singletons' | epsilon | delta | mode) with '|' separators; WMC uses query_sha256 of the original-singleton spec; native uses 'native_contract:<task>' and placeholder epsilon/delta/mode (see notes)",
                                representation_id="sha256(representation_kind | model_sha256 | evidence_sha256 | transformation_sha256-or-'') -- transformation = conversion sidecar sha256 (WMC) or query_sha256 (query-spec views)",
                                run_id="sha256(semantic_task_id | arm | budget_s | seed_index | '%s') -- assigned only on RESOLVED cells; the placeholder is replaced at freeze" % ENV_PLACEHOLDER,
                                cell_id='sha256(stage | block | task_id | arm | budget_s | repeat)[:16]; task_id = slot_id (stable string, exists for unresolved slots too)',
                                seed_index='= repeat index (0..2) on 3-repeat blocks, 0 on single-run blocks; the actual seeds derive from the frozen seed root at freeze',
                                salted_order='sha256(SALT|model_sha256) ascending, SALT = sha256 of the received prompt file = %s' % SALT, h_name='int(sha256(SALT|name|k), 16); name = case_id (legacy) / archive name (UAI) / instance name (WMC)')
    out = OrderedDict(schema=SCHEMA, status=STATUS, freeze_statement=FREEZE_STATEMENT, generated_utc=datetime.datetime.now(datetime.timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ'), worktree=CODE, draft_status=draft['status'], draft_date=draft['date_utc'],
                      inputs=input_hashes, salt=SALT, identity_rule=identity_rule, contracts=dict(primary=draft['primary_contract'], normalizer=draft['normalizer_contract'], legacy_task=legacy_task, resource_contract=draft['resource_contract']),
                      arms=OrderedDict(R0=REG.R0_ARM, B0=REG.B0_ARM, N1='N1_CQR', G0='G0_CQR', ablation_of_family=REG.ABLATION_OF_FAMILY, established=list(ESTABLISHED_ARMS), closest=dict(DIS=dis_impl, OSSTAR=os_status), native=sorted({r['arm'] for r in native_rows}),
                                       registry_version=REG.REGISTRY_VERSION, cqr_arm_feature_flags={k: v['feature_flags'] for k, v in REG.CQR_ARMS.items()}, unavailable_arms=REG.UNAVAILABLE_ARMS),
                      counts=counts, verification_against_draft=verification, allowances=allowance, stage_tables=stage_rows,
                      rules=OrderedDict(constructed_schedule=dict(KINDS=list(KINDS), EVIDENCE=list(EVIDENCE), rule='r = slot_index mod 8; query_kind = KINDS[r mod 4]; evidence_regime = EVIDENCE[r div 4]; slot_index enumerates (family, n, regime, seed_index) in that nesting order, 0..95; each family receives all 8 combinations once'),
                                        query_transfer=qt_rule, closest=closest_rule, established=est_rule, deep_primary_120s=deep_rule, ablation=dict(tasks='the 24 constructed slots with n=%d, seed_index=%d (both regimes per family)' % (ABLATION_N, ABLATION_SEED_INDEX), arm='registry.ABLATION_OF_FAMILY[family]', repeats=3)),
                      salted_pools=pools_record, query_transfer_selection=qt_selection_records, duplicate_planned_runs=duplicate_runs,
                      populations=OrderedDict(primary=primary_rows, legacy_historic_unavailable_rows=historic_unavailable, native=native_rows, closest=closest_rows, established=est_rows, not_planned_at_120_primary_task_ids=not_planned_120, circuit_row=dict(draft['unavailable_circuit_row'], cells=0)),
                      cells=cells, materialization_gaps=gaps, notes=notes, mismatches=mismatches)
    jpath = os.path.join(out_dir, 'PROPOSED_SCORED_MANIFEST.json'); open(jpath, 'w').write(json.dumps(out, indent=1) + '\n')
    write_md(os.path.join(out_dir, 'PROPOSED_SCORED_MANIFEST.md'), out)
    print(json.dumps(dict(status=STATUS, json=jpath, md=jpath[:-5] + '.md', cells=total_cells, nominal_s=nominal, total_allowance_s=allowance['total_allowance_s'], totals_match_draft=verification['all_match'], mismatches=len(mismatches), gaps=len(gaps)), indent=1))
    return 0 if not mismatches else 2


def write_md(path, out):
    L = []; w = L.append
    w('# PROPOSED scored manifest (resolved) -- %s' % out['status']); w('')
    w('Generated %s from the design draft `%s` (`%s`). %s' % (out['generated_utc'], out['draft_status'], out['inputs']['draft']['path'], out['freeze_statement'])); w('')
    w('SALT (every salted order; sha256 of the received prompt file): `%s`' % out['salt']); w('')
    w('## Task identity'); w('')
    for k, v in out['identity_rule'].items(): w('- **%s**: %s' % (k, v))
    w(''); w('## Populations (slots / resolved / unavailable / deferred; distinct source models / semantic tasks / representations among the resolved)'); w('')
    w('| population | slots | resolved | unavailable | deferred | source models | semantic tasks | representations |'); w('|---|---|---|---|---|---|---|---|')
    for k, v in out['counts']['populations'].items():
        if 'slots' not in v: w('| %s | %d rows (not counted in 241, not scheduled) | | | | | | |' % (k, v['rows'])); continue
        w('| %s | %d | %d | %d | %d | %d | %d | %d |' % (k, v['slots'], v['resolved'], v['unavailable'], v['deferred'], v['source_models_resolved'], v['semantic_tasks_resolved'], v['representations_resolved']))
    w(''); sm = out['counts']['source_models']
    w('Source models (distinct model_sha256, resolved): explicit %d = legacy %d + new UAI %d + converted WMC %d (source CNFs %d); native input files %d (%s); constructed slots not yet models: %d; external unavailable slots: %d. %s' % (
        sm['explicit_resolved_distinct_model_sha256'], sm['legacy_explicit'], sm['new_uai2022'], sm['new_wmc2024_converted'], sm['new_wmc2024_source_cnf'], sm['native_distinct_input_files'], sm['native_by_cohort'], sm['constructed_deferred_slots_not_yet_models'], sm['external_unavailable_slots'], sm['note']))
    st = out['counts']['semantic_tasks']; w(''); w('Semantic tasks (distinct, resolved): %d (%s); shared between populations: %d; unresolved slots: %d. Representations (distinct, resolved): %d by kind %s.' % (st['resolved_distinct'], st['by_population'], st['shared_between_populations'], st['unresolved_slots'], out['counts']['representations']['resolved_distinct'], out['counts']['representations']['by_kind']))
    cc = out['counts']['cells']; w(''); w('Cells: %d (%s); by availability %s; run_ids assigned (RESOLVED only): %d, distinct %d (%d cells share a run_id with another planned cell -- see duplicate_planned_runs); primary tasks with a NOT_PLANNED_AT_120 row: %d.' % (cc['total'], cc['by_stage'], cc['by_availability'], cc['run_ids_assigned'], cc['distinct_run_ids'], cc['cells_sharing_a_run_id'], cc['not_planned_at_120_primary_tasks']))
    w(''); w('## Arms'); w('')
    ar = out['arms']; w('R0 = `%s` (105 legacy), G0 = `%s` (136 new), N1 = `%s`, B0 = `%s`; established comparators %s; closest DIS: %s, OS*: %s; native arms %s; ablation arm per family: %s' % (ar['R0'], ar['G0'], ar['N1'], ar['B0'], ar['established'], ar['closest']['DIS'], ar['closest']['OSSTAR'], ar['native'], ar['ablation_of_family']))
    w(''); w('## Stage tables (cells and NOMINAL solver seconds; availability of the cells in each block)'); w('')
    for stn, s in out['stage_tables'].items():
        w('### %s (draft `%s`): %d cells, %d nominal s' % (stn, s['draft_key'], s['cells'], s['nominal_s'])); w('')
        w('| block | tasks | arms | budget s | cells | nominal s | draft cells / nominal | verification | availability |'); w('|---|---|---|---|---|---|---|---|---|')
        for b in s['blocks']: w('| %s | %d | %s | %d | %d | %d | %s / %s | %s | %s |' % (b['role'], b['tasks'], ', '.join(b['arms']), b['budget_s'], b['cells'], b['nominal_s'], b.get('draft_cells'), b.get('draft_nominal_s'), b.get('verification'), b['by_availability']))
        w('')
    v = out['verification_against_draft']; w('## Verification against the draft totals'); w('')
    w('expected %s' % v['expected_from_draft']); w(''); w('computed %s' % v['computed']); w(''); w('**all_match = %s**' % v['all_match'])
    if v['mismatches']:
        w(''); w('Mismatches (recorded, not fudged):')
        for m in v['mismatches']: w('- %s' % m)
    w(''); al = out['allowances']; w('## Allowances (hard upper allocations -- NOT runtime predictions)'); w('')
    w('- %s' % al['statement']); w('- formula: `%s`' % al['formula'])
    w('- solver nominal %d s; per-child cleanup/kill %d s; verification %d s (3 x (nominal - %d unguaranteed established-comparator s)); fixed %s = %d s' % (al['solver_nominal_s'], al['per_child_cleanup_kill_s'], al['verification_s'], al['unguaranteed_established_comparator_s'], al['fixed_allowances_s'], al['fixed_total_s']))
    for stn, p in al['per_stage'].items(): w('- %s: nominal %d + cleanup %d + verification %d + fixed %d = **%d s**' % (stn, p['nominal_s'], p['cleanup_s'], p['verification_s'], p['fixed_s'], p['total_s']))
    w('- total **%d s** (%.2f h)' % (al['total_allowance_s'], al['total_allowance_s'] / 3600))
    w(''); w('## Selection rules materialized'); w('')
    for k, v in out['rules'].items(): w('- **%s**: `%s`' % (k, json.dumps(v, default=str)[:1500]))
    w(''); w('### Query-transfer source models (8) and the resolved queries'); w('')
    w('| cohort | name | n_original | free | v1,v2,v3 | cards | bounded kind | status |'); w('|---|---|---|---|---|---|---|---|')
    for r in out['query_transfer_selection']: w('| %s | %s | %s | %s | %s | %s | %s | %s |' % (r['cohort'], r['name'], r['n_original'], r['n_free'], (r.get('v1'), r.get('v2'), r.get('v3')), r.get('cards'), r.get('bounded_kind'), r['status']))
    w(''); w('### Closest-method source models (12; deep panel = first 2 per cohort)'); w('')
    w('| cohort | name | deep | normalizer task | bounded query |'); w('|---|---|---|---|---|')
    cl = out['populations']['closest']
    for i in range(0, len(cl), 2): w('| %s | %s | %s | %s | %s |' % (cl[i]['source_cohort'], cl[i]['name'], cl[i]['deep_panel'], cl[i]['query_sha256'][:12], (cl[i + 1].get('query_canonical_json') or cl[i + 1].get('unavailable_reason'))))
    w(''); w('### Established comparator tasks (24; 120 s half = first 4 per cohort)'); w('')
    w('| cohort | rank | name | availability | 120 s |'); w('|---|---|---|---|---|')
    for r in out['populations']['established']: w('| %s | %d | %s | %s | %s |' % (r['source_cohort'], r['rank'], r['name'], r['availability'], r['deep_120s']))
    w(''); w('### External slots'); w('')
    w('| slot | status | name | family | model sha256 (disk) | evidence | n vars / original | aux |'); w('|---|---|---|---|---|---|---|---|')
    for r in out['populations']['primary']:
        if r['group'].startswith('C_'): w('| %s | %s | %s | %s | %s | %s | %s | %s |' % (r['slot_id'], r['availability'] + ('' if r['availability'] == 'RESOLVED' else ' (%s)' % r.get('unavailable_reason')), r.get('name'), r.get('family'), (r.get('model_sha256') or '')[:16], r.get('evidence_on_disk'), r.get('n_vars') or r.get('n_original'), r.get('n_auxiliary', '')))
    w(''); w('### Legacy rows'); w('')
    lc = Counter((r['cohort'], r['model_on_disk'], r['evidence_on_disk']) for r in out['populations']['primary'] if r['group'] == 'A_legacy_explicit')
    for k, n in sorted(lc.items()): w('- %s: model %s, evidence %s: %d rows' % (k[0], k[1], k[2], n))
    w('- historic unavailable rows kept visible (not in the 241, not scheduled): %d' % len(out['populations']['legacy_historic_unavailable_rows']))
    for r in out['populations']['legacy_historic_unavailable_rows']: w('  - %s: %s (on disk: %s)' % (r['slot_id'], r['legacy_status'][:90], r['model_on_disk']))
    w(''); w('### Constructed slots (96, DEFERRED)'); w('')
    w('generator `cex/cqr/generators.py` sha256 `%s`; seeds null; schedule: %s' % (out['inputs']['generators_py']['sha256'], out['rules']['constructed_schedule']['rule'])); w('')
    w('| slot_index | family | n | regime | seed_index | held-out perf. family | query kind | evidence | ablation arm |'); w('|---|---|---|---|---|---|---|---|---|')
    for r in out['populations']['primary']:
        if r['group'] == 'B_constructed': w('| %d | %s | %d | %s | %d | %s | %s | %s | %s |' % (r['slot_index'], r['family_id'], r['n'], r['regime'], r['seed_index'], r['heldout_performance_family'], r['query_schedule']['query_kind'], r['query_schedule']['evidence_regime'], r['ablation_arm']))
    w(''); w('## Materialization gaps (everything NOT resolvable now)'); w('')
    for g in out['materialization_gaps']: w('- **%s**: %s' % (g['kind'], g.get('statement') or json.dumps({k: v for k, v in g.items() if k != 'kind'}, default=str)[:600]))
    w(''); w('## Notes'); w('')
    for n in out['notes']: w('- %s' % n)
    w(''); w('## Inputs (read-only) and hashes'); w('')
    for k, v in out['inputs'].items(): w('- %s: `%s` %d B `%s`' % (k, v['path'], v['bytes'], v['sha256']))
    open(path, 'w').write('\n'.join(L) + '\n')


if __name__ == '__main__':
    sys.exit(main())
