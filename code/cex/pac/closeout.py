"""Closeout generator -- v4 (fail-closed with CONTENT and SCHEMA binding; third review R07 / R08): a qualified verdict is emitted ONLY when every prerequisite holds AND
the artifacts are the exact evidence set the gate verified:
  * GATE_RESULT: gate v4, gate_passed AND an EMPTY failure list, manifest_sha256 == sha256 of the manifest on disk, artifact_hashes_sha256 == content hash of the
    manifest's frozen inventory, planned == manifest cells == receipts; the CONTENT-ADDRESSED gated set is re-derived from the receipts on disk (receipt sha256,
    output sha256, status, outcome, guarantee per cell) and must equal the gate's set and digest (a changed output / stale gate is refused);
  * RESULTS_PAC: report v4, manifest sha256 present and equal, gated_set_sha256 equal to the gate's, exactly one run row per planned cell (cell ids, arm, cohort,
    budget, replicate, status, outcome and guarantee verified against the gated set; duplicated / omitted / foreign rows refused), unrun empty, no gated-set mismatch;
  * qualification record: suite v4, EXACTLY the registry's group schema (every expected group present once, no extra, all ok, passed == total == len), its recorded
    candidate identity EQUALS the manifest's frozen candidate hashes AND the files on disk;
  * CAMPAIGN_START binds the manifest sha256 and the frozen-inventory content hash; no amendment file exists; the complete required source inventory is frozen;
  * the verdict is derived PER COHORT / TASK / BUDGET / GUARANTEE from the report's conclusions table and then scoped: external_core is one statement among the cohorts,
    supplementary gains AND losses are reported, delta-0 native tasks and PAC answers are never pooled.
Otherwise UNQUALIFIED / INVALID with every failed prerequisite listed; exit status 1.
    python cex/pac/closeout.py <RD> [--manifest CAMPAIGN_MANIFEST.json] [--qualification PATH]"""
import sys, os, json, time, collections, hashlib, glob
RD = os.path.abspath(sys.argv[1]); HERE = os.path.dirname(os.path.abspath(__file__)); CODE = os.path.dirname(os.path.dirname(HERE)); sys.path.insert(0, HERE)
import registry
QP = sys.argv[sys.argv.index('--qualification') + 1] if '--qualification' in sys.argv else os.path.join(HERE, 'PAC_QUALIFICATION.json')
MN = sys.argv[sys.argv.index('--manifest') + 1] if '--manifest' in sys.argv else 'CAMPAIGN_MANIFEST.json'
CLOSEOUT_VERSION = 'pac-closeout-v4 (2026-11-13 repair 3; fail-closed with content + schema binding; per-cohort scoped verdict)'
L = []; P = L.append; prereq = []
def sha(p):
    h = hashlib.sha256()
    with open(p, 'rb') as f:
        for b in iter(lambda: f.read(1 << 20), b''): h.update(b)
    return h.hexdigest()
def need(path, what):
    if not os.path.exists(path): prereq.append('%s missing (%s)' % (what, path)); return None
    try: return json.load(open(path))
    except Exception as ex: prereq.append('%s unreadable: %s' % (what, str(ex)[:80])); return None
mpath = os.path.join(RD, MN)
R = need(os.path.join(RD, 'RESULTS_PAC.json'), 'RESULTS_PAC.json'); M = need(mpath, 'manifest'); G = need(os.path.join(RD, 'GATE_RESULT.json'), 'gate result'); A = need(os.path.join(RD, 'REFERENCE_AUDIT.json'), 'reference audit'); Q = need(QP, 'qualification record'); ST = need(os.path.join(RD, 'CAMPAIGN_START.json'), 'CAMPAIGN_START')
mh = sha(mpath) if os.path.exists(mpath) else None
cells = (M or {}).get('cells') or []; ncells = len(cells); cell_by_id = {c['cell_id']: c for c in cells}
frozen = (M or {}).get('candidate_artifact_hashes') or {}; ah = hashlib.sha256(json.dumps(frozen, sort_keys=True).encode()).hexdigest() if frozen else None
# ---- receipts recomputed from disk -> the content-addressed set
receipts = {}; rsha = {}
for rp in glob.glob(os.path.join(RD, 'cells', '*', 'receipt.json')):
    try: r = json.load(open(rp)); receipts.setdefault(r.get('cell_id'), []).append(r); rsha[r.get('cell_id')] = sha(rp)
    except Exception: prereq.append('unreadable receipt %s' % rp)
dups = [k for k, v in receipts.items() if len(v) > 1]
unrun_disk = [c['cell_id'] for c in cells if c['cell_id'] not in receipts]; extra_disk = [k for k in receipts if k not in cell_by_id]
completed_disk = sum(1 for k, v in receipts.items() if v[0].get('status') == 'COMPLETED')
if dups: prereq.append('duplicate receipts on disk: %d' % len(dups))
if unrun_disk: prereq.append('matrix incomplete: %d planned cells have no receipt on disk' % len(unrun_disk))
if extra_disk: prereq.append('%d receipts for cells not in the manifest' % len(extra_disk))
disk_set = sorted((dict(cell_id=k, receipt_sha256=rsha[k], output_sha256=v[0].get('output_sha256'), status=v[0].get('status'), outcome=v[0].get('outcome'), guarantee=v[0].get('guarantee_type'), arm=cell_by_id[k]['arm'], cohort=cell_by_id[k]['cohort'], budget_s=cell_by_id[k]['budget_s'], case_id=cell_by_id[k]['case_id'], replicate=cell_by_id[k]['replicate']) for k, v in receipts.items() if k in cell_by_id and len(v) == 1), key=lambda e: e['cell_id'])
disk_digest = hashlib.sha256(json.dumps(disk_set, sort_keys=True).encode()).hexdigest()
# ---- START + frozen identity (complete inventory, no amendments)
if ST is not None:
    if ST.get('manifest_sha256') != mh: prereq.append('CAMPAIGN_START manifest sha256 differs from the manifest on disk')
    if ST.get('artifact_hashes_sha256') != ah: prereq.append('CAMPAIGN_START does not bind the frozen source inventory content hash')
if glob.glob(os.path.join(RD, 'MANIFEST_AMENDMENT_*')): prereq.append('artifact amendment files present (no amendment mechanism in v4)')
want_inv = registry.source_inventory(CODE)
if not frozen: prereq.append('manifest carries no frozen source inventory')
else:
    miss_inv = [k for k in want_inv if k not in frozen]; extra_inv = [k for k in frozen if k not in want_inv]; diff_inv = [k for k in want_inv if k in frozen and frozen[k] != want_inv[k]]
    if miss_inv or extra_inv: prereq.append('frozen source inventory is not the complete required set (%d missing, %d extra)' % (len(miss_inv), len(extra_inv)))
    if diff_inv: prereq.append('frozen source %s differs from the file on disk (%d differ)' % (diff_inv[0], len(diff_inv)))
# ---- gate identity + counts + content
if G is not None:
    if not str(G.get('gate_version', '')).startswith('pac-gate-v4'): prereq.append('gate result produced by a pre-v4 gate (%s): re-gate required' % G.get('gate_version'))
    if G.get('failures'): prereq.append('receipt/certificate gate lists %d failures' % len(G.get('failures')))
    if not G.get('gate_passed'): prereq.append('receipt/certificate gate FAILED')
    if G.get('manifest_sha256') != mh: prereq.append('gate result belongs to a different manifest (%s vs %s)' % (str(G.get('manifest_sha256'))[:16], str(mh)[:16]))
    if G.get('artifact_hashes_sha256') != ah: prereq.append('gate result binds a different frozen source inventory')
    if G.get('planned') != ncells or G.get('receipts') != ncells or G.get('receipts') != len(receipts): prereq.append('gate counts (planned %s, receipts %s) differ from the manifest (%d cells) / disk (%d receipts)' % (G.get('planned'), G.get('receipts'), ncells, len(receipts)))
    if G.get('completed_gated') != completed_disk: prereq.append('gate completed_gated %s differs from COMPLETED receipts on disk %d' % (G.get('completed_gated'), completed_disk))
    gs = G.get('gated_set')
    if not isinstance(gs, list): prereq.append('gate result carries no content-addressed gated set')
    else:
        if sorted(gs, key=lambda e: e['cell_id']) != disk_set or G.get('gated_set_sha256') != disk_digest: prereq.append('the gated set (receipt / output content, status, outcome, guarantee) differs from the receipts and outputs on disk: STALE gate or changed evidence')
# ---- qualification: exact schema + identity
if Q is not None:
    groups = Q.get('groups') or []; names = [g.get('name') for g in groups]
    if not str(Q.get('suite_version', '')).startswith('pac-qualification-v4'): prereq.append('qualification record from a pre-v4 suite (%s)' % Q.get('suite_version'))
    if sorted(names) != sorted(registry.QUALIFICATION_GROUPS) or len(names) != len(set(names)): prereq.append('qualification groups differ from the registry schema (%d present / %d expected; missing %s; extra %s)' % (len(names), len(registry.QUALIFICATION_GROUPS), [n for n in registry.QUALIFICATION_GROUPS if n not in names][:3], [n for n in names if n not in registry.QUALIFICATION_GROUPS][:3]))
    if not Q.get('all_pass') or Q.get('passed') != Q.get('total') or Q.get('total') != len(groups) or not groups or not all(g.get('ok') is True for g in groups): prereq.append('qualification groups not all passed (passed %s / total %s / groups %d / ok %d)' % (Q.get('passed'), Q.get('total'), len(groups), sum(1 for g in groups if g.get('ok'))))
    qs = Q.get('candidate_sources') or {}; want = {k: v for k, v in frozen.items() if registry.scope_of_key(k) == 'candidate'}
    if not want: prereq.append('manifest carries no frozen candidate identity (pac/*, newarm/*)')
    miss = [k for k in want if k not in qs]; diff = [k for k in want if k in qs and qs[k] != want[k]]; extra_q = [k for k in qs if k not in want]
    if miss or diff or extra_q: prereq.append('qualification record identity does not match the frozen candidate (%d missing, %d differing, %d extra; e.g. %s)' % (len(miss), len(diff), len(extra_q), (miss + diff + extra_q)[:1]))
# ---- results: identity, content, rows
runs = (R or {}).get('runs', []); unrun = (R or {}).get('unrun', [])
if R is not None:
    if not str(R.get('report_version', '')).startswith('pac-report-v4'): prereq.append('results produced by a pre-v4 reporter (%s)' % R.get('report_version'))
    if R.get('manifest_sha256') is None or R.get('manifest_sha256') != mh: prereq.append('results manifest identity missing or different')
    if G is not None and R.get('gated_set_sha256') != G.get('gated_set_sha256'): prereq.append('results were not derived from the gated set the gate verified')
    gb = R.get('gate_binding') or {}
    if gb.get('mismatch'): prereq.append('report records %d gated-set mismatches' % len(gb['mismatch']))
    ids_rows = [x.get('cell_id') for x in runs]
    if len(runs) != ncells or len(set(ids_rows)) != len(ids_rows): prereq.append('results rows %d (unique %d) differ from the manifest cells %d' % (len(runs), len(set(ids_rows)), ncells))
    dset = {e['cell_id']: e for e in disk_set}; bad_rows = 0
    for x in runs:
        e = dset.get(x.get('cell_id')); c = cell_by_id.get(x.get('cell_id'))
        if e is None or c is None or x.get('arm') != c['arm'] or x.get('cohort') != c['cohort'] or x.get('budget') != c['budget_s'] or x.get('rep') != c['replicate'] or x.get('status') != e['status'] or x.get('outcome') != e['outcome'] or x.get('guarantee') != e['guarantee']: bad_rows += 1
    if bad_rows: prereq.append('%d results rows do not match the gated receipts (foreign / altered rows)' % bad_rows)
    if unrun or unrun_disk: prereq.append('results report %d unrun / disk %d unrun' % (len(unrun), len(unrun_disk)))
    if not isinstance(R.get('conclusions_by_cohort_budget'), dict): prereq.append('results carry no per-cohort conclusions table')
# ---- the per-cohort conclusions are RE-DERIVED here from the verified rows (never read as data): PAC / deterministic publication counts and H1-vs-B0 new / lost per cohort and budget
def rederive_conclusions(rows_):
    out_ = {}
    cohs = sorted({x['cohort'] for x in rows_}, key=lambda k: registry.COHORTS[k]['order'] if k in registry.COHORTS else 99)
    for coh in cohs:
        for budget in sorted({x['budget'] for x in rows_ if x['cohort'] == coh}):
            bb = [x for x in rows_ if x['cohort'] == coh and x['budget'] == budget]; key = '%s|%d' % (coh, int(budget)); byarm = {}
            for arm in sorted({x['arm'] for x in bb}):
                aa = [x for x in bb if x['arm'] == arm]
                byarm[arm] = dict(planned=len(aa), received=sum(1 for x in aa if x['status'] != 'NOT_RUN'), published_deterministic=sum(1 for x in aa if x['outcome'] == 'PUBLISHED' and x['guarantee'] == 'DETERMINISTIC'), published_pac=sum(1 for x in aa if x['outcome'] == 'PUBLISHED' and x['guarantee'] == 'PAC'), published_unguaranteed=sum(1 for x in aa if x['outcome'] == 'PUBLISHED' and x['guarantee'] == 'UNGUARANTEED'), zero=sum(1 for x in aa if x['outcome'] == 'PROVED_ZERO_EVIDENCE'), refused=sum(1 for x in aa if x['outcome'] not in ('PUBLISHED', 'PROVED_ZERO_EVIDENCE', 'NOT_RUN')))
            b0 = {x['case']: x for x in bb if x['arm'] == 'B0_FROZEN_V14'}; h1 = collections.defaultdict(list)
            for x in bb:
                if x['arm'] == 'H1_HYBRID': h1[x['case']].append(x)
            comp = None
            if b0 or h1:
                nrep = max((len(v) for v in h1.values()), default=0)
                observed = {c_ for c_ in b0 if b0[c_]['status'] != 'NOT_RUN' and len(h1[c_]) == nrep and nrep > 0 and all(x['status'] != 'NOT_RUN' for x in h1[c_])}
                b0ok = {c_ for c_ in observed if b0[c_]['outcome'] == 'PUBLISHED'}; h1all = {c_ for c_ in observed if all(x['outcome'] == 'PUBLISHED' for x in h1[c_])}
                comp = dict(new=sorted(h1all - b0ok), lost=sorted(b0ok - h1all), pending=sorted(set(b0) - observed), observed=len(observed))
            out_[key] = dict(cohort=coh, budget=budget, by_arm=byarm, b0_vs_h1=comp)
    return out_
re_concl = rederive_conclusions(runs) if runs else {}
rep_concl = (R or {}).get('conclusions_by_cohort_budget') or {}
if R is not None:
    for key, cc in re_concl.items():
        rc_ = rep_concl.get(key) or {}
        if {a: {k: v for k, v in d_.items()} for a, d_ in cc['by_arm'].items()} != {a: {k: d_.get(k) for k in ('planned', 'received', 'published_deterministic', 'published_pac', 'published_unguaranteed', 'zero', 'refused')} for a, d_ in (rc_.get('by_arm') or {}).items()}: prereq.append('report conclusions for %s differ from the counts re-derived from the verified rows' % key); break
        if cc['b0_vs_h1'] and ((rc_.get('b0_vs_h1') or {}).get('new') != cc['b0_vs_h1']['new'] or (rc_.get('b0_vs_h1') or {}).get('lost') != cc['b0_vs_h1']['lost']): prereq.append('report B0-vs-H1 new / lost for %s differ from the rows' % key); break
    if set(rep_concl) != set(re_concl): prereq.append('report conclusions cover %d cohort/budget keys, the rows %d' % (len(rep_concl), len(re_concl)))
qualified = not prereq
# ---- SCOPED verdict from the RE-DERIVED per-cohort conclusions (the report's table was checked against them above)
concl = {k: dict(re_concl[k], representation=(rep_concl.get(k) or {}).get('representation', registry.COHORTS.get(re_concl[k]['cohort'], {}).get('representation')), original_task=(rep_concl.get(k) or {}).get('original_task'), pooled_with_uai_numerator=registry.COHORTS.get(re_concl[k]['cohort'], {}).get('pooled_with_uai_numerator'), native=(rep_concl.get(k) or {}).get('native')) for k in re_concl}
gains = []; losses = []; pac_pubs = collections.Counter(); det_pubs = collections.Counter(); native_met = collections.Counter()
for key, cc in concl.items():
    comp = cc.get('b0_vs_h1') or {}
    for c_ in comp.get('new') or []: gains.append('%s %d s: H1 new %s' % (cc['cohort'], cc['budget'], c_))
    for c_ in comp.get('lost') or []: losses.append('%s %d s: H1 lost %s' % (cc['cohort'], cc['budget'], c_))
    for arm, v in (cc.get('by_arm') or {}).items():
        if arm in registry.CANDIDATE_ARMS: pac_pubs[cc['cohort']] += v.get('published_pac', 0); det_pubs[cc['cohort']] += v.get('published_deterministic', 0)
    if cc.get('native'): native_met[cc['cohort']] += cc['native'].get('native_width_met', 0)
pac_total = sum(pac_pubs.values())
if qualified:
    verdict = 'NO EMPIRICAL GAIN IN ANY COHORT' if (pac_total == 0 and not gains) else ('EMPIRICAL CHANGE OBSERVED (gains: %d; losses: %d; PAC publications: %d; a positive result needs 03 §9)' % (len(gains), len(losses), pac_total))
else: verdict = 'UNQUALIFIED / INVALID (prerequisites failed: %s)' % '; '.join(prereq)
inacc = [a for a in (A or {}).get('audit', []) if a.get('accurate') == 'CONFIRMED_INACCURATE']
P('# PAC EMPIRICAL PASS — CLOSEOUT (%s UTC; %s) — %s' % (time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()), CLOSEOUT_VERSION, verdict)); P('')
if M is not None:
    P('Frozen manifest `%s` sha256 `%s` (root seed `%s`), frozen source inventory content hash `%s`, %d cells; receipts on disk %d (COMPLETED %d); gated-set digest (disk) `%s`. Gate: %s (%s; planned %s, receipts %s, gated %s, PAC certificates replayed %s, failures %s). Qualification: %s.' % (MN, mh, (M.get('seeds') or {}).get('root_seed'), ah, ncells, len(receipts), completed_disk, disk_digest, ('PASSED' if G and G.get('gate_passed') and not G.get('failures') else 'FAILED / MISSING'), (G or {}).get('gate_version'), (G or {}).get('planned'), (G or {}).get('receipts'), (G or {}).get('completed_gated'), (G or {}).get('pac_certificates_replayed'), len((G or {}).get('failures', [])), ('%s/%s groups (%s), %s' % (Q.get('passed'), Q.get('total'), Q.get('suite_version'), json.dumps(Q.get('counts') or {}, default=str)[:200]) if Q else 'MISSING'))); P('')
if not qualified:
    P('## 0. PREREQUISITES FAILED — this closeout carries NO qualified empirical verdict'); P('')
    for f in prereq: P('- %s' % f)
    P(''); P('The evidence below is preserved for diagnosis; it must not be cited as a qualified negative or positive empirical answer. STOPPED FOR REVIEW.'); P('')
P('## 1. Conclusions by cohort, original task, budget and guarantee%s' % ('' if qualified else ' — DIAGNOSTIC ONLY (unqualified)')); P('')
P('| cohort | budget | representation | pooled with the UAI numerator? | candidate PAC publications | candidate deterministic publications | H1 new vs B0 | H1 lost vs B0 | native width met |'); P('|---|---:|---|---|---:|---:|---|---|---|')
for key, cc in concl.items():
    pacn = sum(v.get('published_pac', 0) for a, v in (cc.get('by_arm') or {}).items() if a in registry.CANDIDATE_ARMS); detn = sum(v.get('published_deterministic', 0) for a, v in (cc.get('by_arm') or {}).items() if a in registry.CANDIDATE_ARMS); comp = cc.get('b0_vs_h1') or {}
    P('| %s | %d | %s | %s | %d | %d | %s | %s | %s |' % (cc['cohort'], cc['budget'], cc.get('representation'), 'yes' if cc.get('pooled_with_uai_numerator') else 'no (own task)', pacn, detn, comp.get('new') or 'none', comp.get('lost') or 'none', json.dumps((cc.get('native') or {}).get('widths_met_counts')) if cc.get('native') else '—'))
P(''); P('Supplementary gains (every cohort): %s. Supplementary losses: %s. PAC publications by cohort: %s. External-core statement: %s.' % (gains or 'none', losses or 'none', dict(pac_pubs) or 'none', json.dumps({k: v for k, v in concl.items() if k.startswith('external_core')}, default=str)[:600] or 'no external_core cells in this manifest')); P('')
P('Delta-0 native tasks (CBI, H4, SF natives) are reported in their own rows and never pooled with PAC answers; a deterministic mapping of PAC state intervals keeps its PAC delta.'); P('')
P('## 2. Reference audit (diagnostic; binding- and shape-validated references only)'); P('')
cat = collections.Counter((a['arm'], a['accurate']) for a in (A or {}).get('audit', []))
P('References used: %s; rejected for binding/shape: %d. Per arm (accurate / inaccurate / unresolved / malformed): %s. CONFIRMED_INACCURATE publications: %d%s.' % (dict(collections.Counter(v for v in (A or {}).get('refs', {}).values())), len((A or {}).get('references_rejected', [])), {k[0]: dict(acc=cat[(k[0], 'CONFIRMED_ACCURATE')], inacc=cat[(k[0], 'CONFIRMED_INACCURATE')], unres=cat[(k[0], 'UNRESOLVED_NO_REFERENCE')] + cat[(k[0], 'UNRESOLVED_INTERVAL')], malformed=cat[(k[0], 'MALFORMED_CANDIDATE')]) for k in sorted({(a['arm'],) for a in (A or {}).get('audit', [])})}, len(inacc), (' — INVESTIGATE: ' + str(inacc[:5])) if inacc else '')); P('')
P('## 3. What was proved, qualified, measured, and remains unknown'); P('')
P('- Proved (theory packet, unchanged): conditional unbiasedness of exact-plus-residual trials; ratio mixture and variance-sensitive anytime certificates; the factor-max envelope telescoping over the explicit frontier; the finite-precision publication bridge; the deterministic-statistical intersection keeps the simultaneous risk (both sets contain p_j on the statistical event). Proof-to-code map: `PROOF_TO_CODE_PAC_v4.md`.')
P('- Qualified: %s.' % ('; '.join(g['name'] for g in Q['groups'] if g.get('ok')) if Q else 'NONE (record missing)'))
P('- Measured: RESULTS_PAC.md (%d runs, %d unrun).' % (len(runs), len(unrun)))
P('- Not implemented / unknown (optional in the handoff): candidate validation (T§9); the cost oracle as a planner; proposal refinement beyond child-sum propagation and leaf resolution; re-weighting later trials by the smaller U_t; delta = 1e-6 is not empirically verified; the checker trusts the compiled kernel enclosures of large cells after re-execution and the PRNG assumption.'); P('')
P('## 4. Failure attribution (recorded bottlenecks; RESULTS_PAC.md Table 7)'); P('')
for k, v in sorted(((R or {}).get('attribution_counts') or {}).items(), key=lambda kv: -kv[1]): P('- %s: %d runs' % (k, v))
P(''); P('## 5. Isolation, resource contract'); P('')
iso = json.load(open(os.path.join(RD, 'ISOLATION_NOTE.json'))) if os.path.exists(os.path.join(RD, 'ISOLATION_NOTE.json')) else {}
P('Scored cells ran strictly sequentially (pairwise overlaps among scored cells: %d). Charged non-cell jobs overlapping a scored cell: %s. %s No amendment mechanism exists; the frozen identity is bound at START by content hash.' % (len(iso.get('scored_cell_pairwise_overlaps', [])), iso.get('charged_non_cell_jobs_overlapping_scored_cells') or 'none', iso.get('interactive_exposure', '')))
led = (R or {}).get('ledger') or {}
P('Resource contract as executed: actual kill threshold budget + 5 s (supervisor grace); receipts over budget + 1 s: %s, over budget + 5 s: %s; walls charged in full; late publications never count.' % (led.get('receipts_over_budget_plus_1'), led.get('receipts_over_budget_plus_5')))
P(''); P('## 6. Ledger'); P('')
if led: P('Scored + qualification + packaging receipts (this run directory): %.1f s; development campaigns: %.1f s; prospective ceiling %.0f s (scored matrix nominal %.0f s, orchestration %.0f s). Interactive post-processing uncharged (UNKNOWN exposure).' % (led['total'], led['dev_total'], led['ceiling']['total_ceiling_seconds'], led['ceiling']['scored_matrix_seconds'], led['ceiling']['orchestration_seconds']))
P(''); P('## 7. Verdict'); P(''); P('**%s.** %s STOPPED FOR REVIEW.' % (verdict, 'The full planned matrix of THIS manifest was run, gated (content-addressed) and qualified by artifacts bound to this exact candidate, manifest and evidence set; the verdict is scoped per cohort (Section 1).' if qualified else 'No qualified empirical verdict is issued.'))
open(os.path.join(RD, 'CLOSEOUT_PAC.md'), 'w').write('\n'.join(L) + '\n'); print('closeout written:', verdict); sys.exit(0 if qualified else 1)
