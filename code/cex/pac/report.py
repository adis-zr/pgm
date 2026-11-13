"""Assemble the PAC pass results from SAVED receipts only -- report v2 (repair of review F08 / F11 of 13 Nov 2026; 07 "Required tables").
Tables: inventory reconciliation (incl. the recoverable legacy cohorts with their actual denominators); full case x arm x budget x replicate; per-cohort/budget
completion (deterministic / PAC / heuristic / noncompletion; per-case 0/3..3/3); fresh B0 vs H1 on FULLY OBSERVED groups only (pending groups reported separately, never
as lost or new); comparator quality vs references; matched ablation WITH the recorded range / variance / numerical widths of the last check; failure attribution by
RECORDED quantities (the active bottleneck per run: no completed trial / statistical width (range or variance family) / numerical width (stream-scale underflow) / typed
stop), never a causal conjecture; resource ledger with the ACTUAL supervisor allowance (timeout + 4 s supervisor grace = budget + 5 s).
Reference audit (F08): a reference is used only if its recorded binding (model / evidence sha256) equals the cell's frozen binding and its shape (variables, cardinalities)
equals the model's; candidate rows must have the exact complete shape (every variable, every state) -- a missing or extra coordinate is a MALFORMED candidate, never
truncated into agreement. Categories: R0 exact rational truth (independent brute force); B0 exact-arithmetic enclosure (deterministic enclosure SHARING candidate
lineage, same budget); exact-capacity floating point (LIBDAI_EXACT, MERLIN_CTE, WMB / IJGP at exact capacity): a point, never a truth; heuristic point (LBP, PGMax).
Interval rules (03 §7): with a certified reference interval [L,U] and a point c: upper = max(|c-L|,|c-U|) <= eps confirms; lower = max(L-c, c-U, 0) > eps disproves; else unresolved.
    python cex/pac/report.py <RD>  -> RESULTS_PAC.md, RESULTS_PAC.json, REFERENCE_AUDIT.json"""
import sys, os, json, glob, collections, statistics, hashlib, time, math
from fractions import Fraction as F
HERE = os.path.dirname(os.path.abspath(__file__)); CODE = os.path.dirname(os.path.dirname(HERE)); sys.path.insert(0, os.path.join(CODE, 'cex', 'newarm')); sys.set_int_max_str_digits(0)
import core
EPS = F(1, 200); REPORT_VERSION = 'pac-report-v3 (2026-11-13 completion: native-query scoring for adapted cohorts, cohort-aware tables)'
CANDIDATE_ARMS = ('B0_FROZEN_V14', 'P1_PAC_CONDITIONAL', 'H1_HYBRID', 'A0_POINT', 'A1_CONDITIONAL')
import sys as _sys
EXACT_CAPACITY_ARMS = ('LIBDAI_EXACT', 'MERLIN_CTE')


def load(RD):
    man = json.load(open(os.path.join(RD, 'CAMPAIGN_MANIFEST.json'))); rec = {}
    for rp in glob.glob(os.path.join(RD, 'cells', '*', 'receipt.json')):
        r = json.load(open(rp)); rec[r['cell_id']] = r
    return man, rec


def worker(RD, r):
    p = r.get('worker_output')
    if not p: return {}
    p = os.path.join(RD, p)
    return json.load(open(p)) if os.path.exists(p) else {}


def read_mar(path):
    toks = open(path).read().split()
    if 'MAR' in toks: i = toks.index('MAR') + 1          # Merlin writes 'PR <logZ> (<Z>) STATUS <text> MAR <n> ...'; libDAI / PGMax write 'MAR <n> ...'
    else: i = 0
    n = int(toks[i]); i += 1; rows = []
    for _ in range(n):
        k = int(toks[i]); i += 1; rows.append([F(toks[i + j]) for j in range(k)]); i += k
    return rows


def shape_ok(rows, cards):
    return isinstance(rows, list) and len(rows) == len(cards) and all(isinstance(r, list) and len(r) == k for r, k in zip(rows, cards))


def capacity_of(arm, r):
    """execution capacity: the receipt's tag when recorded; by algorithm for LIBDAI_EXACT / MERLIN_CTE (exact-capacity binary64 points, NOT rigorous)"""
    tag = ((r or {}).get('comparator') or {}).get('execution_capacity')
    if tag: return tag
    if arm in EXACT_CAPACITY_ARMS: return 'exact (by algorithm; tag absent in the receipt)'
    if arm in ('LBP', 'PGMAX_SUMPRODUCT_BP'): return 'approximate'
    return None


def main(RD):
    RD = os.path.abspath(RD); man, rec = load(RD); cells = man['cells']; out = {'report_version': REPORT_VERSION, 'manifest_sha256': hashlib.sha256(open(os.path.join(RD, 'CAMPAIGN_MANIFEST.json'), 'rb').read()).hexdigest()}; L = []; P = L.append
    inv = man['inventory']; core_rows = [r for r in inv if r['cohort'] == 'external_core']
    planned = len(cells); received = len(rec); unrun = [c for c in cells if c['cell_id'] not in rec]
    P('# PAC EMPIRICAL PASS — RESULTS (%s UTC; host %s; receipts read from %s; %s)' % (time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()), man['host']['platform'], 'cells/*/receipt.json', REPORT_VERSION)); P('')
    ap = sorted(glob.glob(os.path.join(RD, 'MANIFEST_AMENDMENT_*artifact_hashes.json'))); am = json.load(open(ap[-1])) if ap else None; pdh = (am or {}).get('per_directory_hashes') or {}
    if not pdh and all('/' in k for k in (man.get('candidate_artifact_hashes') or {})):
        pdh = collections.defaultdict(dict)
        for k, v in man['candidate_artifact_hashes'].items(): d, f = k.split('/', 1); pdh[d][f] = v
    cand = pdh.get('newarm', {}); pac = pdh.get('pac', {}); b0h = pdh.get('b0_frozen_v14', {})
    P('Frozen manifest sha256 (without self): `%s`; root seed `%s`; candidate kernel source `%s` (binary rebuilt here), candidate executor `%s`, PAC engine `%s`; B0 = unchanged v1.4 executor `%s`.' % (man['manifest_sha256_without_self'], man['seeds']['root_seed'], cand.get('cex_kernel.cpp', '')[:16], cand.get('cex_executor.py', '')[:16], pac.get('engine.py', '')[:16], b0h.get('cex_executor.py', '')[:16]))
    P('Planned cells %d, receipts %d, UNRUN %d. %s' % (planned, received, len(unrun), 'COMPLETE MATRIX (of THIS manifest; the requested inventory denominator is Table 1).' if not unrun else 'PARTIAL: %d planned cells have no receipt (listed in RESULTS_PAC.json unrun).' % len(unrun))); P('')
    # ---- table 1
    P('## Table 1 — Inventory reconciliation (the denominator of the requested benchmark is the UNION of registered tasks; this manifest covers the rows marked executed)'); P(''); P('| cohort | intended tasks | available (hash-verified) | missing / unavailable | primary arms | native specialists | executed cells | unrun cells |'); P('|---|---:|---:|---|---|---|---:|---:|')
    coh_cells = collections.defaultdict(list)
    for c in cells: coh_cells[c['cohort']].append(c)
    P('| external_core (46 + 2 missing slots headline) | 48 | %d | %s | B0 / P1 / H1 / A0 / A1 | libDAI EXACT, LBP, WMB, IJGP, PGMax, Merlin CTE | %d | %d |' % (sum(1 for r in core_rows if r['status'] == 'AVAILABLE_HASH_VERIFIED'), ', '.join(r['case_id'] for r in core_rows if r['status'] != 'AVAILABLE_HASH_VERIFIED'), sum(1 for c in coh_cells['external_core'] if c['cell_id'] in rec), sum(1 for c in coh_cells['external_core'] if c['cell_id'] not in rec)))
    sel = [r for r in inv if r['cohort'] == 'selector_transfer_additions']; P('| selector_transfer_additions | 2 | %d | %s | same | same | %d | %d |' % (sum(1 for r in sel if r.get('model_sha256')), ', '.join(r['case_id'] for r in sel if not r.get('model_sha256')) or 'none', sum(1 for c in coh_cells['selector_transfer_additions'] if c['cell_id'] in rec), sum(1 for c in coh_cells['selector_transfer_additions'] if c['cell_id'] not in rec)))
    cbi = man.get('cbi_instances', []); P('| CBI (native contract) | 23 | %d | %s | %s | cbi CLI solve (native) | %d | %d |' % (sum(1 for r in cbi if r['status'].startswith('RETAINED')), ', '.join(r['case_id'] for r in cbi if not r['status'].startswith('RETAINED')) or 'none', 'UAI-table adapter: %s' % ('executed' if any(c['arm'] in CANDIDATE_ARMS for c in coh_cells['CBI']) else 'NOT in this manifest (block/kernel models; see the inventory plan)'), sum(1 for c in coh_cells['CBI'] if c['cell_id'] in rec), sum(1 for c in coh_cells['CBI'] if c['cell_id'] not in rec)))
    for lc in man['legacy_cohorts']:
        if lc['cohort'] in ('CBI',): continue
        n_ex = sum(1 for c in coh_cells.get(lc['cohort'], []) if c['cell_id'] in rec); n_un = sum(1 for c in coh_cells.get(lc['cohort'], []) if c['cell_id'] not in rec)
        P('| %s | %s | — | %s | %s | %s | %d | %d |' % (lc['cohort'], lc.get('tasks', '')[:70], lc.get('status'), lc.get('primary_arms', '')[:80], lc.get('native_specialists', '')[:80], n_ex, n_un))
    P(''); P('Comparators unavailable: %s' % '; '.join('%s: %s' % (k, v[:90]) for k, v in man['arms']['unavailable'].items())); P('')
    # ---- references with BINDING (F08)
    refs = {}; rp = os.path.join(RD, 'REFERENCES_R0.json'); ref_rejected = []
    if os.path.exists(rp):
        for k, v in json.load(open(rp))['references'].items():
            b = v.get('binding') or {}
            if v['kind'] == 'R0_exact_rational': refs[k] = dict(kind='R0_exact_rational', rows=[[F(x) for x in row] for row in v['rows']], binding=b)
            elif v['kind'] == 'R0_zero_evidence': refs[k] = dict(kind='R0_zero_evidence', binding=b)
    b0_ref = {}; b0_binding = {}
    for c in cells:
        r = rec.get(c['cell_id'])
        if r and c['arm'] == 'B0_FROZEN_V14' and r.get('status') == 'COMPLETED':
            w = worker(RD, r); b0_ref[(c['case_id'], c['budget_s'])] = [[(F(a), F(b)) for a, b in row] for row in w['intervals']]; b0_binding[(c['case_id'], c['budget_s'])] = w.get('binding') or {}
    models = {}
    def model_of(c):
        mp = c.get('model_path')
        if not mp or not os.path.exists(mp): return None, None
        if mp not in models: models[mp] = core.read_uai(mp)
        return models[mp]
    # ---- per-run rows
    rows = []
    for c in cells:
        r = rec.get(c['cell_id']); w = worker(RD, r) if r else {}
        row = dict(cohort=c['cohort'], case=c['case_id'], arm=c['arm'], budget=c['budget_s'], rep=c['replicate'], status=(r or {}).get('status', 'NOT_RUN'), outcome=(r or {}).get('outcome', 'NOT_RUN'), guarantee=(r or {}).get('guarantee_type', 'NONE'), wall=(r or {}).get('launch_relative_wall_s'), rss_MB=round(((r or {}).get('supervisor') or {}).get('peak_MB', 0) or 0), seed=c.get('seed'), nonce=(r or {}).get('nonce'), output_sha256=(r or {}).get('output_sha256'), execution_capacity=capacity_of(c['arm'], r) if r else None)
        if r and row['outcome'] == 'NOT_COMPLETED' and c['arm'] == 'MERLIN_CTE':
            pr = os.path.join(r.get('attempt_dir', ''), 'cmp', 'pac_receipt.json'); ad = (json.load(open(pr)).get('adapter') or {}) if os.path.exists(pr) else {}
            ao = str(ad.get('outcome', '')); row['outcome'] = 'INVALID_PLAN_OR_CERTIFICATE' if 'OUTPUT_INVALID' in ao else ('MEMORY' if 'MEMORY' in ao else ('DEADLINE' if 'TIMEOUT' in ao or 'DEADLINE' in ao else ('ZERO_EVIDENCE_OR_UNDERFLOW_UNRESOLVED' if 'ZERO' in ao else 'NOT_COMPLETED'))); row['adapter_outcome'] = ao; row['adapter_reason'] = str(ad.get('reason', ''))[:120]; row['report_stage_remap'] = True
        if r and row['outcome'] == 'PROVED_ZERO_EVIDENCE' and not c['arm'] in CANDIDATE_ARMS: row['outcome'] = 'ZERO_EVIDENCE_OR_UNDERFLOW_UNRESOLVED'; row['report_stage_remap'] = 'comparator zero outcomes are UNRESOLVED (underflow indistinguishable)'
        if w:
            st = w.get('stats') or {}; comps = st.get('components') or []
            row['routes'] = [(x.get('route'), x.get('guarantee')) for x in comps][:6]
            pac = [x for x in comps if str(x.get('route', '')).startswith('pac')]
            if pac: row['pac'] = [dict(trials=(x.get('stats') or {}).get('trials_completed'), U_log10=(x.get('stats') or {}).get('U_root_log10'), cutset=len(((x.get('stats') or {}).get('design') or (x.get('stats') or {}).get('cutset') or {}).get('cutset') or []), certifier=x.get('certifier_per_row', [None])[0] if x.get('certifier_per_row') else None, terminal=(x.get('stats') or {}).get('terminal'), kernel_s=(x.get('stats') or {}).get('kernel_s'), zero_trials=(x.get('stats') or {}).get('zero_trials'), resolved_cells=(x.get('stats') or {}).get('resolved_cells'), last_check=(x.get('stats') or {}).get('last_check')) for x in pac][:3]
            row['stop_reason'] = (w.get('reason') or '')[:120]
            if w.get('status') == 'STOPPED' and w.get('stop_stats'):
                ss = w['stop_stats']; sst = (ss.get('stats') or {}) if isinstance(ss, dict) else {}
                row['stop_component_stats'] = {k: sst.get(k) for k in ('trials_completed', 'U_root_log10', 'terminal', 'kernel_s', 'certify_s', 'trials_per_second', 'Z_estimate_over_U', 'last_check', 'stream_scale_underflow', 'trial_failure', 'resolved_cells', 'positive_trials', 'zero_trials')}
        rows.append(row)
    out['runs'] = rows; out['unrun'] = [dict(case=c['case_id'], arm=c['arm'], budget=c['budget_s'], rep=c['replicate']) for c in unrun]
    # ---- reference audit (F08: binding + shape validated before any arithmetic)
    audit = []; cat = collections.Counter()
    for c in cells:
        r = rec.get(c['cell_id'])
        if not r or r.get('status') != 'COMPLETED' or c['cohort'] not in ('external_core', 'selector_transfer_additions', 'qgrid', 'CBI_UAI', 'SF_small'): continue
        model, binding = model_of(c)
        if model is None: audit.append(dict(case=c['case_id'], arm=c['arm'], budget=c['budget_s'], rep=c['replicate'], reference='NONE', accurate='UNRESOLVED_INPUT_UNAVAILABLE')); cat[(c['arm'], 'UNRESOLVED_INPUT_UNAVAILABLE')] += 1; continue
        cards = model['cards']; frozen_binding = dict(model_sha256=c.get('model_sha256'), evidence_sha256=c.get('evidence_sha256'))
        pts = None; ivs = None; malformed = None
        if c['arm'] in CANDIDATE_ARMS:
            w = worker(RD, r)
            if (w.get('binding') or {}) != frozen_binding: malformed = 'candidate output binding differs from the frozen input'
            else:
                try: pts = [[F(x) for x in rw] for rw in w['points']]; ivs = [[(F(a), F(b)) for a, b in rw] for rw in w['intervals']]
                except Exception: malformed = 'candidate rows unparseable'
                if pts is not None and not (shape_ok(pts, cards) and shape_ok(ivs, cards)): malformed = 'candidate shape differs from the original model (missing / extra coordinates)'
        else:
            mar = (r.get('comparator') or {}).get('output_file')
            if mar and os.path.exists(mar):
                try: pts = read_mar(mar)
                except Exception: malformed = 'comparator output unparseable'
                if pts is not None and not shape_ok(pts, cards): malformed = 'comparator shape differs from the original model'
            else: malformed = 'comparator output file missing'
        if malformed: audit.append(dict(case=c['case_id'], arm=c['arm'], budget=c['budget_s'], rep=c['replicate'], reference='NONE', accurate='MALFORMED_CANDIDATE', reason=malformed)); cat[(c['arm'], 'MALFORMED_CANDIDATE')] += 1; continue
        ref = refs.get(c['case_id']); bref = b0_ref.get((c['case_id'], c['budget_s'])) if c['arm'] != 'B0_FROZEN_V14' else None
        if ref is not None and ref.get('binding') != frozen_binding: ref_rejected.append(dict(case=c['case_id'], reason='R0 reference binding differs from the frozen input', ref_binding=ref.get('binding'))); ref = None
        if ref is not None and ref['kind'] == 'R0_exact_rational' and not shape_ok(ref['rows'], cards): ref_rejected.append(dict(case=c['case_id'], reason='R0 reference shape differs from the model')); ref = None
        if bref is not None and (b0_binding.get((c['case_id'], c['budget_s'])) != frozen_binding or not shape_ok(bref, cards)): bref = None
        if ref and ref['kind'] == 'R0_exact_rational':
            truth = ref['rows']; worst = max(abs(p - t) for pr, tr in zip(pts, truth) for p, t in zip(pr, tr)); cont = all(lo <= t <= hi for ivr, tr in zip(ivs, truth) for (lo, hi), t in zip(ivr, tr)) if ivs else None
            res = 'CONFIRMED_ACCURATE' if worst <= EPS else 'CONFIRMED_INACCURATE'; cat[(c['arm'], res)] += 1
            audit.append(dict(case=c['case_id'], arm=c['arm'], budget=c['budget_s'], rep=c['replicate'], reference='R0_exact_rational', reference_binding=ref['binding'], max_abs_error=float(worst), accurate=res, intervals_contain_truth=cont, coordinates=sum(len(x) for x in truth)))
        elif bref is not None:
            upper = max(max(abs(p - lo), abs(p - hi)) for ivr, pr in zip(bref, pts) for (lo, hi), p in zip(ivr, pr)); lower = max(max(lo - p, p - hi, F(0)) for ivr, pr in zip(bref, pts) for (lo, hi), p in zip(ivr, pr))
            res = 'CONFIRMED_ACCURATE' if upper <= EPS else ('CONFIRMED_INACCURATE' if lower > EPS else 'UNRESOLVED_INTERVAL')
            cont = all(blo >= lo and bhi <= hi for ivr, br in zip(ivs, bref) for (lo, hi), (blo, bhi) in zip(ivr, br)) if ivs else None
            cat[(c['arm'], res)] += 1; audit.append(dict(case=c['case_id'], arm=c['arm'], budget=c['budget_s'], rep=c['replicate'], reference='deterministic enclosure sharing candidate lineage (B0 at the same budget)', error_upper=float(upper), error_lower=float(lower), accurate=res, reference_interval_inside_published=cont, coordinates=sum(len(x) for x in pts), note='containment of the B0 interval inside the candidate interval is NOT a truth test (different widths)'))
        else:
            audit.append(dict(case=c['case_id'], arm=c['arm'], budget=c['budget_s'], rep=c['replicate'], reference='NONE (no bound R0 and no B0 enclosure at this budget)', accurate='UNRESOLVED_NO_REFERENCE')); cat[(c['arm'], 'UNRESOLVED_NO_REFERENCE')] += 1
    out['reference_audit'] = audit; json.dump(dict(report_version=REPORT_VERSION, refs={k: v['kind'] for k, v in refs.items()}, references_rejected=ref_rejected, audit=audit, counts={'%s|%s' % k: v for k, v in cat.items()}, trust_note='a reference agreement is a diagnostic; the PAC guarantee is a property of the lawful procedure (gate), not of any single outcome'), open(os.path.join(RD, 'REFERENCE_AUDIT.json'), 'w'), indent=1, default=str)
    # ---- NATIVE-QUERY scoring of the adapted cohorts (CBI_UAI, SF_small): every COMPLETED candidate publication is mapped through the bound blocks metadata to the
    # native per-coordinate task (legacy_cbi_uai.native_score); state-marginal completion and native completion are reported SEPARATELY; deterministic vs PAC kept distinct
    native_rows = []
    try:
        sys.path.insert(0, HERE); import legacy_cbi_uai as LC
        for c in cells:
            r = rec.get(c['cell_id'])
            if not r or c['cohort'] not in ('CBI_UAI', 'SF_small') or c['arm'] not in CANDIDATE_ARMS or r.get('status') != 'COMPLETED': continue
            w = worker(RD, r); bp = c.get('blocks_path')
            if not bp or not os.path.exists(bp): native_rows.append(dict(case=c['case_id'], arm=c['arm'], budget=c['budget_s'], rep=c['replicate'], native_completion='ADAPTER_REFUSED', reason='blocks metadata missing')); continue
            meta = json.load(open(bp)); rows_ = [[(F(a), F(b)) for a, b in row] for row in w['intervals']]
            inst = None
            src = next((x for x in man.get('inventory', []) if x.get('case_id') == c['case_id']), {})
            if c['cohort'] == 'CBI_UAI' and src.get('source_instance'):
                ip = os.path.join(CODE, 'runs', 'mdi_2026-10-28', 'CBI_LIBRARY_2026-11-06', 'inputs', src['source_instance'])
                if os.path.exists(ip) and hashlib.sha256(open(ip, 'rb').read()).hexdigest() == src.get('source_sha256'): inst = json.load(open(ip))
            sc = LC.native_score(meta, rows_, meta_sha256=c.get('blocks_sha256'), native_width=F(1, 100), instance_json=inst)
            native_rows.append(dict(case=c['case_id'], arm=c['arm'], budget=c['budget_s'], rep=c['replicate'], guarantee=r.get('guarantee_type'), native_completion=sc['native_completion'], max_coordinate_width=sc.get('max_coordinate_width'), native_reference=sc.get('native_reference'), reason=sc.get('reason')))
    except Exception as ex: native_rows.append(dict(error='native scoring failed: %s' % str(ex)[:120]))
    out['native_query_scores'] = native_rows
    if native_rows:
        P('## Table 2b — Adapted cohorts scored on the NATIVE query (per-coordinate probabilities, width 1/100): state-marginal completion vs native completion'); P(''); P('| cohort/case | arm | budget | rep | guarantee | native completion | max coordinate width | native reference |'); P('|---|---|---:|---:|---|---|---:|---|')
        for x in native_rows:
            if 'error' in x: P('| %s | | | | | | | |' % x['error']); continue
            P('| %s | %s | %d | %d | %s | %s | %s | %s |' % (x['case'], x['arm'], x['budget'], x['rep'], x.get('guarantee'), x['native_completion'], ('%.3g' % x['max_coordinate_width']) if x.get('max_coordinate_width') is not None else '—', json.dumps(x.get('native_reference') or x.get('reason') or '')[:80]))
        P('')
    # ---- table 3
    P('## Table 3 — Completion by cohort, budget and arm (run level; per-case k/3 for stochastic arms)'); P(''); P('| cohort | budget | arm | planned | received | PUBLISHED deterministic | PUBLISHED PAC | PUBLISHED unguaranteed (heuristic) | PROVED_ZERO_EVIDENCE | zero-or-underflow (unresolved) | DEADLINE | MEMORY | TOO_WIDE | numerical | invalid/fault | NOT_RUN | per-case 0/3,1/3,2/3,3/3 |'); P('|---|---:|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---|')
    arms_order = ['B0_FROZEN_V14', 'P1_PAC_CONDITIONAL', 'H1_HYBRID', 'A0_POINT', 'A1_CONDITIONAL', 'LIBDAI_EXACT', 'MERLIN_CTE', 'WMB', 'IJGP', 'LBP', 'PGMAX_SUMPRODUCT_BP', 'CBI_NATIVE', 'H4_NATIVE', 'QGRID_NATIVE', 'SF_NATIVE']
    completion = {}
    COH_ORDER = ('external_core', 'selector_transfer_additions', 'qgrid', 'CBI_UAI', 'SF_small', 'CBI', 'H4_native', 'SF_native')
    for coh in sorted({x['cohort'] for x in rows}, key=lambda k: COH_ORDER.index(k) if k in COH_ORDER else 99):
        for budget in man['budgets_s']:
            for arm in arms_order + sorted({x['arm'] for x in rows} - set(arms_order)):
                rs = [x for x in rows if x['cohort'] == coh and x['budget'] == budget and x['arm'] == arm]
                if not rs: continue
                cnt = lambda pred: sum(1 for x in rs if pred(x))
                det = cnt(lambda x: x['outcome'] == 'PUBLISHED' and x['guarantee'] == 'DETERMINISTIC'); pac = cnt(lambda x: x['outcome'] == 'PUBLISHED' and x['guarantee'] == 'PAC'); heur = cnt(lambda x: x['outcome'] == 'PUBLISHED' and x['guarantee'] == 'UNGUARANTEED')
                percase = ''
                if arm in ('P1_PAC_CONDITIONAL', 'H1_HYBRID'):
                    k = collections.Counter(sum(1 for x in rs if x['case'] == cs and x['outcome'] == 'PUBLISHED') for cs in sorted({x['case'] for x in rs})); percase = ','.join(str(k.get(i, 0)) for i in range(4))
                completion[(coh, budget, arm)] = dict(planned=len(rs), received=cnt(lambda x: x['status'] != 'NOT_RUN'), det=det, pac=pac, heur=heur)
                P('| %s | %d | %s | %d | %d | %d | %d | %d | %d | %d | %d | %d | %d | %d | %d | %d | %s |' % (coh, budget, arm, len(rs), cnt(lambda x: x['status'] != 'NOT_RUN'), det, pac, heur, cnt(lambda x: x['outcome'] == 'PROVED_ZERO_EVIDENCE'), cnt(lambda x: x['outcome'] == 'ZERO_EVIDENCE_OR_UNDERFLOW_UNRESOLVED'), cnt(lambda x: x['outcome'] == 'DEADLINE'), cnt(lambda x: x['outcome'] == 'MEMORY'), cnt(lambda x: x['outcome'] == 'TOO_WIDE'), cnt(lambda x: x['outcome'] == 'NUMERICAL_RANGE_OR_PRECISION'), cnt(lambda x: x['outcome'] in ('INVALID_PLAN_OR_CERTIFICATE', 'FAULT')), cnt(lambda x: x['status'] == 'NOT_RUN'), percase))
    P('')
    # ---- table 4: FULLY OBSERVED groups only (F11 / R4)
    P('## Table 4 — Fresh B0 vs H1 (external core): retained / lost / new on FULLY OBSERVED groups (B0 received AND all three H1 replicates received); pending groups listed separately'); P('')
    for budget in man['budgets_s']:
        b0 = {x['case']: x for x in rows if x['arm'] == 'B0_FROZEN_V14' and x['budget'] == budget and x['cohort'] == 'external_core'}
        h1 = collections.defaultdict(list)
        for x in rows:
            if x['arm'] == 'H1_HYBRID' and x['budget'] == budget and x['cohort'] == 'external_core': h1[x['case']].append(x)
        observed = {c for c in b0 if b0[c]['status'] != 'NOT_RUN' and len(h1[c]) == 3 and all(x['status'] != 'NOT_RUN' for x in h1[c])}; pending = sorted(set(b0) - observed)
        b0ok = {c for c in observed if b0[c]['outcome'] == 'PUBLISHED'}; h1_all3 = {c for c in observed if all(x['outcome'] == 'PUBLISHED' for x in h1[c])}; h1_any = {c for c in observed if any(x['outcome'] == 'PUBLISHED' for x in h1[c])}
        lost = sorted(b0ok - h1_all3); new = sorted(h1_all3 - b0ok); retained = sorted(b0ok & h1_all3)
        pairs = []
        for c in retained:
            wb = b0[c]['wall']; wh = statistics.median([x['wall'] for x in h1[c] if x['wall']])
            if wb and wh: pairs.append((c, round(wh / wb, 3), round(wb, 2), round(wh, 2), b0[c]['rss_MB'], round(statistics.median([x['rss_MB'] for x in h1[c]]))))
        P('- **%d s**: fully observed groups %d of %d (pending: %s). B0 published %d; H1 published 3/3 on %d (any seed: %d). Retained %d; LOST (B0 yes, H1 not 3/3): %s; NEW (H1 3/3, B0 no): %s. H1 PAC-guaranteed publications: %d runs.' % (budget, len(observed), len(b0), pending or 'none', len(b0ok), len(h1_all3), len(h1_any), len(retained), lost or 'none', new or 'none', sum(1 for c in observed for x in h1[c] if x['guarantee'] == 'PAC')))
        if pairs:
            rs_ = sorted(p[1] for p in pairs); P('  paired wall ratio H1(median of 3)/B0 over %d retained cases: median %.3f (timeouts censored, never a ratio); per case (case, ratio, B0 s, H1 s, B0 MB, H1 MB): %s' % (len(pairs), rs_[len(rs_) // 2], sorted(pairs, key=lambda t: t[1])))
        out['b0_vs_h1_%d' % int(budget)] = dict(observed=sorted(observed), pending=pending, b0=sorted(b0ok), h1_all3=sorted(h1_all3), h1_any=sorted(h1_any), lost=lost, new=new, pairs=pairs)
    P(''); P('Historical context only (not fresh matched controls): v1.4 32/46 at 20 s, 13/13 on the old 13-case 120 s panel.'); P('')
    # ---- table 5
    P('## Table 5 — Comparators (unguaranteed points; execution capacity tagged per run) and reference audit (binding- and shape-validated references only)'); P(''); P('| arm | budget | published | DEADLINE | MEMORY | invalid/fault | exact-capacity runs | CONFIRMED_ACCURATE | CONFIRMED_INACCURATE | UNRESOLVED (interval) | UNRESOLVED (no reference) | MALFORMED |'); P('|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|')
    for arm in ('LIBDAI_EXACT', 'MERLIN_CTE', 'WMB', 'IJGP', 'LBP', 'PGMAX_SUMPRODUCT_BP', 'B0_FROZEN_V14', 'P1_PAC_CONDITIONAL', 'H1_HYBRID', 'A0_POINT', 'A1_CONDITIONAL'):
        for budget in man['budgets_s']:
            rs = [x for x in rows if x['arm'] == arm and x['budget'] == budget and x['cohort'] in ('external_core', 'selector_transfer_additions', 'qgrid', 'CBI_UAI', 'SF_small')]
            if not rs: continue
            exact_cap = sum(1 for x in rs if x['outcome'] == 'PUBLISHED' and str(x.get('execution_capacity', '')).startswith('exact'))
            au = [a for a in audit if a['arm'] == arm and a['budget'] == budget]
            P('| %s | %d | %d | %d | %d | %d | %d | %d | %d | %d | %d | %d |' % (arm, budget, sum(1 for x in rs if x['outcome'] == 'PUBLISHED'), sum(1 for x in rs if x['outcome'] == 'DEADLINE'), sum(1 for x in rs if x['outcome'] == 'MEMORY'), sum(1 for x in rs if x['outcome'] in ('INVALID_PLAN_OR_CERTIFICATE', 'FAULT')), exact_cap, sum(1 for a in au if a['accurate'] == 'CONFIRMED_ACCURATE'), sum(1 for a in au if a['accurate'] == 'CONFIRMED_INACCURATE'), sum(1 for a in au if a['accurate'] == 'UNRESOLVED_INTERVAL'), sum(1 for a in au if a['accurate'] == 'UNRESOLVED_NO_REFERENCE'), sum(1 for a in au if a['accurate'] == 'MALFORMED_CANDIDATE')))
    P(''); P('References: R0 exact rational truth for %d cases (REFERENCES_R0.json, charged offline job; binding verified against the frozen inputs, %d rejected); B0 exact-arithmetic enclosures (delta 0) at the same budget for %d (case, budget) pairs = certified reference INTERVALS sharing candidate lineage (interval rule of 03 §7); everything else UNRESOLVED. Exact-capacity floating points (libDAI JTREE, Merlin CTE) are points, never truth.' % (sum(1 for v in refs.values() if v['kind'] == 'R0_exact_rational'), len(ref_rejected), len(b0_ref))); P('')
    # ---- table 6: matched ablation WITH widths
    P('## Table 6 — Matched fixed-plan ablation at 120 s (A0_POINT vs A1_CONDITIONAL, same cutset / order / tree seed, residual region fixed)'); P(''); P('| case | A0 outcome | A0 trials | A0 last-check range width (max row) | A0 variance width | A1 outcome | A1 trials | A1 range width | A1 variance width | A1 kernel s | cutset | U log10 | Z/U estimate (A1, estimate only) |'); P('|---|---|---:|---:|---:|---|---:|---:|---:|---:|---:|---:|---:|')
    def wmax(lc, fam):
        if not lc or not isinstance(lc, dict): return None
        w = (lc.get('widths') or {}).get(fam) or {}
        try: return max(float(v) for v in w.values()) if w else None
        except Exception: return None
    for c in sorted({x['case'] for x in rows if x['arm'] == 'A0_POINT'}):
        a0 = next((x for x in rows if x['arm'] == 'A0_POINT' and x['case'] == c), None); a1 = next((x for x in rows if x['arm'] == 'A1_CONDITIONAL' and x['case'] == c), None)
        def info(x):
            if not x: return ('NOT_RUN', None, None, None, None, None, None, None)
            p = (x.get('pac') or [{}])[0]; ss = x.get('stop_component_stats') or {}; lc = p.get('last_check') or ss.get('last_check')
            return (x['outcome'], p.get('trials') or ss.get('trials_completed'), wmax(lc, 'range'), wmax(lc, 'variance'), p.get('kernel_s') or ss.get('kernel_s'), p.get('cutset'), p.get('U_log10') or ss.get('U_root_log10'), ss.get('Z_estimate_over_U'))
        i0 = info(a0); i1 = info(a1); fmt = lambda v: ('%.3g' % v) if isinstance(v, (int, float)) and v is not None else '—'
        P('| %s | %s | %s | %s | %s | %s | %s | %s | %s | %s | %s | %s | %s |' % (c, i0[0], i0[1], fmt(i0[2]), fmt(i0[3]), i1[0], i1[1], fmt(i1[2]), fmt(i1[3]), (round(i1[4], 1) if i1[4] else '—'), i1[5] or i0[5], (round(i1[6] or i0[6], 1) if (i1[6] or i0[6]) else '—'), fmt(i1[7])))
    P(''); P('The variance theorem (§7) is an expected second-moment ordering under the same Q; the widths above are the recorded last certification check of each run (one observation per case); Z/U is a sample ESTIMATE from the lower accumulator, not a certified ratio; U is gauge dependent.'); P('')
    # ---- table 7: attribution by recorded quantities (F11 / R5c)
    P('## Table 7 — Failure attribution of non-published primary runs (external core), by the RECORDED active bottleneck'); P(''); P('| case | budget | arm | rep | outcome | attribution (recorded) |'); P('|---|---:|---|---:|---|---|')
    attr_counts = collections.Counter()
    for x in rows:
        if x['cohort'] != 'external_core' or x['arm'] not in ('B0_FROZEN_V14', 'P1_PAC_CONDITIONAL', 'H1_HYBRID') or x['outcome'] in ('PUBLISHED', 'NOT_RUN'): continue
        ss = x.get('stop_component_stats') or {}; attr = []
        if x['arm'] == 'B0_FROZEN_V14': a = 'frozen deterministic pipeline: %s' % (x.get('stop_reason') or x['outcome'])
        else:
            tr = ss.get('trials_completed'); lc = ss.get('last_check') or {}; wr = wmax(lc, 'range'); wv = wmax(lc, 'variance')
            if ss.get('trial_failure'): a = 'typed trial failure (%s) after %s completed trials' % (ss['trial_failure'].get('kind'), tr)
            elif ss.get('stream_scale_underflow'): a = 'numerical width: dimensionless statistics underflow binary64 at this U_root (%s trials)' % tr
            elif tr in (0, None): a = 'no completed trial before the stop: source / planning / template construction cost or a deterministic route consumed the budget (%s)' % (x.get('stop_reason') or '')[:80]
            elif x['outcome'] == 'DEADLINE' and lc: a = 'statistical width at the deadline: %s trials; last-check max row width range %s / variance %s (both > 1/100); Z/U estimate %s' % (tr, ('%.3g' % wr) if wr is not None else 'n/a', ('%.3g' % wv) if wv is not None else 'n/a', ('%.2g' % ss['Z_estimate_over_U']) if ss.get('Z_estimate_over_U') else 'n/a')
            else: a = '%s: %s' % (x['outcome'], (x.get('stop_reason') or '')[:80])
        attr_counts[a.split(':')[0]] += 1
        P('| %s | %d | %s | %d | %s | %s |' % (x['case'], x['budget'], x['arm'], x['rep'], x['outcome'], a))
    P(''); out['attribution_counts'] = dict(attr_counts)
    # ---- table 8: ledger with the actual allowance
    led = [json.loads(l) for l in open(os.path.join(RD, 'PAC_LEDGER.jsonl')) if l.strip()]; recs = [r for r in led if r.get('kind') == 'RECEIPT']; by = collections.defaultdict(float)
    for r in recs: by[r['scope']] += r['wall_s']
    dev_total = 0.0
    for L_ in glob.glob(os.path.join(RD, 'dev*', 'PAC_LEDGER.jsonl')):
        for l in open(L_):
            r = json.loads(l)
            if r.get('kind') == 'RECEIPT': dev_total += r['wall_s']
    over1 = sum(1 for x in rows if x['wall'] and x['wall'] > x['budget'] + 1.0); over5 = sum(1 for x in rows if x['wall'] and x['wall'] > x['budget'] + 5.0)
    P('## Table 8 — Resource ledger (Python-monotonic receipted wall; every job supervised)'); P(''); P('| scope | receipts | seconds |'); P('|---|---:|---:|')
    for k, v in sorted(by.items()): P('| %s | %d | %.1f |' % (k, sum(1 for r in recs if r['scope'] == k), v))
    P('| development campaigns (dev*/PAC_LEDGER.jsonl, development seeds) | — | %.1f |' % dev_total)
    P('| **total scored + qualification + packaging (this ledger)** | %d | **%.1f** |' % (len(recs), sum(by.values())))
    P(''); P('Resource contract as EXECUTED: supervisor timeout = budget + 1 s and the supervisor adds its own 4 s grace before SIGKILL, so the actual kill threshold is budget + 5 s (ledger START rows: max_permitted_charge_s). Receipts with wall > budget + 1 s: %d; > budget + 5 s: %d. Walls are charged in full; a publication after the budget is never a success (recomputed by the gate).' % (over1, over5))
    P('Prospective ceiling (manifest): scored matrix %.0f s nominal; orchestration %.0f s; total ceiling %.0f s (04 formula). Interactive post-processing is uncharged (UNKNOWN exposure; ISOLATION_NOTE.json).' % (man['ceiling']['scored_matrix_seconds'], man['ceiling']['orchestration_seconds'], man['ceiling']['total_ceiling_seconds']))
    out['completion'] = {'%s|%s|%s' % k: v for k, v in completion.items()}; out['ledger'] = dict(by_scope=dict(by), total=sum(by.values()), dev_total=dev_total, ceiling=man['ceiling'], grace_note='actual kill threshold budget + 5 s', receipts_over_budget_plus_1=over1, receipts_over_budget_plus_5=over5)
    json.dump(out, open(os.path.join(RD, 'RESULTS_PAC.json'), 'w'), indent=1, default=str); open(os.path.join(RD, 'RESULTS_PAC.md'), 'w').write('\n'.join(L) + '\n'); print('written', len(L), 'lines;', len(rows), 'runs;', len(unrun), 'unrun')


if __name__ == '__main__': main(sys.argv[1])
