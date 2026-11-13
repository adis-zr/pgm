"""Assemble the PAC pass results from SAVED receipts only (07 "Required tables"): inventory reconciliation; full case x arm x budget x replicate table; per-cohort/budget
completion (deterministic / PAC / heuristic / noncompletion; run-level rates; per-case 0/3..3/3); fresh B0 vs H1 (retained / lost / new; paired walls and memory where both
completed; censored timeouts never become ratios); comparator quality vs references; matched ablation; failure attribution by recorded quantities; resource ledger.
References: R0 exact rational truth (brute force for <= 12 bits of state space, computed here, charged separately as offline reference); independent deterministic enclosure
(B0's certified output when published: shares no lineage with the PAC estimator's randomness but shares the planner/kernel -> labelled 'deterministic enclosure sharing
candidate lineage'); exact-capacity floating point (LIBDAI_EXACT, MERLIN_CTE, WMB/IJGP at exact capacity); heuristic point (LBP, PGMax, approximate WMB/IJGP).
Interval rules (03 §7): with a certified reference interval [L,U] and a point c: upper = max(|c-L|,|c-U|) <= eps confirms; lower = max(L-c, c-U, 0) > eps disproves; else unresolved.
    python cex/pac/report.py <RD>  -> RESULTS_PAC.md, RESULTS_PAC.json, REFERENCE_AUDIT.json"""
import sys, os, json, glob, collections, statistics, hashlib, time, math
from fractions import Fraction as F
HERE = os.path.dirname(os.path.abspath(__file__)); CODE = os.path.dirname(os.path.dirname(HERE)); sys.path.insert(0, os.path.join(CODE, 'cex', 'newarm')); sys.set_int_max_str_digits(0)
import core
EPS = F(1, 200)


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
    toks = open(path).read().split(); i = 1 if toks[0] == 'MAR' else 0; n = int(toks[i]); i += 1; rows = []
    for _ in range(n):
        k = int(toks[i]); i += 1; rows.append([F(toks[i + j]) for j in range(k)]); i += k
    return rows


def main(RD):
    RD = os.path.abspath(RD); man, rec = load(RD); cells = man['cells']; out = {}; L = []; P = L.append
    inv = man['inventory']; by_status = collections.Counter(r['status'] for r in inv); core_rows = [r for r in inv if r['cohort'] == 'external_core']
    planned = len(cells); received = len(rec); unrun = [c for c in cells if c['cell_id'] not in rec]
    P('# PAC EMPIRICAL PASS — RESULTS (%s UTC; host %s; receipts read from %s)' % (time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()), man['host']['platform'], 'cells/*/receipt.json')); P('')
    ap = os.path.join(RD, 'MANIFEST_AMENDMENT_1_artifact_hashes.json'); am = json.load(open(ap)) if os.path.exists(ap) else None; cand = (am['per_directory_hashes']['newarm'] if am else {}); b0h = (am['per_directory_hashes']['b0_frozen_v14'] if am else {})
    P('Frozen manifest sha256 (without self): `%s`; root seed `%s`; candidate kernel source `%s` (binary rebuilt here), candidate executor `%s`, PAC engine `%s`; B0 = unchanged v1.4 executor `%s` (per-directory identities: MANIFEST_AMENDMENT_1; the manifest flat dict collided across directories).' % (man['manifest_sha256_without_self'], man['seeds']['root_seed'], cand.get('cex_kernel.cpp', '')[:16], cand.get('cex_executor.py', '')[:16], (am['per_directory_hashes']['pac'].get('engine.py', '')[:16] if am else ''), b0h.get('cex_executor.py', '')[:16]))
    P('Planned cells %d, receipts %d, UNRUN %d. %s' % (planned, received, len(unrun), 'COMPLETE MATRIX.' if not unrun else 'PARTIAL: %d planned cells have no receipt (listed in RESULTS_PAC.json unrun).' % len(unrun))); P('')
    # ---- table 1: inventory reconciliation
    P('## Table 1 — Inventory reconciliation'); P(''); P('| cohort | intended | available (hash-verified) | missing / unavailable | unsupported adapter (primary arms) | executed cells | unrun cells |'); P('|---|---:|---:|---|---|---:|---:|')
    coh_cells = collections.defaultdict(list)
    for c in cells: coh_cells[c['cohort']].append(c)
    P('| external_core (46 + 2 missing slots headline) | 48 | %d | %s | — | %d | %d |' % (sum(1 for r in core_rows if r['status'] == 'AVAILABLE_HASH_VERIFIED'), ', '.join(r['case_id'] for r in core_rows if r['status'] != 'AVAILABLE_HASH_VERIFIED'), sum(1 for c in coh_cells['external_core'] if c['cell_id'] in rec), sum(1 for c in coh_cells['external_core'] if c['cell_id'] not in rec)))
    sel = [r for r in inv if r['cohort'] == 'selector_transfer_additions']; P('| selector_transfer_additions | 2 | %d | %s | — | %d | %d |' % (sum(1 for r in sel if r.get('model_sha256')), ', '.join(r['case_id'] for r in sel if not r.get('model_sha256')) or 'none', sum(1 for c in coh_cells['selector_transfer_additions'] if c['cell_id'] in rec), sum(1 for c in coh_cells['selector_transfer_additions'] if c['cell_id'] not in rec)))
    cbi = man.get('cbi_instances', []); P('| CBI (native contract) | 23 | %d | %s | primary UAI arms: UNSUPPORTED_TASK_ADAPTER (block/kernel models) | %d | %d |' % (sum(1 for r in cbi if r['status'].startswith('RETAINED')), ', '.join(r['case_id'] for r in cbi if not r['status'].startswith('RETAINED')) or 'none', sum(1 for c in coh_cells['CBI'] if c['cell_id'] in rec), sum(1 for c in coh_cells['CBI'] if c['cell_id'] not in rec)))
    for lc in man['legacy_cohorts']:
        if lc['cohort'] in ('CBI',): continue
        P('| %s | %s | — | %s | %s | 0 | 0 |' % (lc['cohort'], lc.get('tasks', '')[:60], lc.get('status'), lc.get('primary_arms', '')[:70]))
    P(''); P('Comparators unavailable: %s' % '; '.join('%s: %s' % (k, v[:90]) for k, v in man['arms']['unavailable'].items())); P('')
    # ---- references: R0 exact rational truth from the CHARGED offline job (REFERENCES_R0.json); B0's exact-arithmetic enclosures (delta = 0) where B0 published = certified
    # reference INTERVALS of category 'deterministic enclosure sharing candidate lineage' (same planner/kernel lineage as H1's deterministic components; independent of PAC randomness)
    refs = {}; rp = os.path.join(RD, 'REFERENCES_R0.json')
    if os.path.exists(rp):
        for k, v in json.load(open(rp))['references'].items():
            if v['kind'] == 'R0_exact_rational': refs[k] = dict(kind='R0_exact_rational', rows=[[F(x) for x in row] for row in v['rows']])
            elif v['kind'] == 'R0_zero_evidence': refs[k] = dict(kind='R0_zero_evidence')
    b0_ref = {}
    for c in cells:
        r = rec.get(c['cell_id'])
        if r and c['arm'] == 'B0_FROZEN_V14' and r.get('status') == 'COMPLETED':
            w = worker(RD, r); b0_ref[(c['case_id'], c['budget_s'])] = [[(F(a), F(b)) for a, b in row] for row in w['intervals']]
    # ---- table 2 + per-run rows
    rows = []
    for c in cells:
        r = rec.get(c['cell_id']); w = worker(RD, r) if r else {}
        row = dict(cohort=c['cohort'], case=c['case_id'], arm=c['arm'], budget=c['budget_s'], rep=c['replicate'], status=(r or {}).get('status', 'NOT_RUN'), outcome=(r or {}).get('outcome', 'NOT_RUN'), guarantee=(r or {}).get('guarantee_type', 'NONE'), wall=(r or {}).get('launch_relative_wall_s'), rss_MB=round(((r or {}).get('supervisor') or {}).get('peak_MB', 0) or 0), seed=c.get('seed'), nonce=(r or {}).get('nonce'), output_sha256=(r or {}).get('output_sha256'))
        if r and row['outcome'] == 'NOT_COMPLETED' and c['arm'] == 'MERLIN_CTE':
            # report-stage refinement (the frozen wrapper mapped every non-completed Merlin CTE adapter outcome to NOT_COMPLETED): read the adapter's own typed outcome
            pr = os.path.join(r.get('attempt_dir', ''), 'cmp', 'pac_receipt.json'); ad = (json.load(open(pr)).get('adapter') or {}) if os.path.exists(pr) else {}
            ao = str(ad.get('outcome', '')); row['outcome'] = 'INVALID_PLAN_OR_CERTIFICATE' if 'OUTPUT_INVALID' in ao else ('MEMORY' if 'MEMORY' in ao else ('DEADLINE' if 'TIMEOUT' in ao or 'DEADLINE' in ao else 'NOT_COMPLETED')); row['adapter_outcome'] = ao; row['adapter_reason'] = str(ad.get('reason', ''))[:120]; row['report_stage_remap'] = True
        if w:
            st = w.get('stats') or {}; comps = st.get('components') or []
            row['routes'] = [(x.get('route'), x.get('guarantee')) for x in comps][:6]
            pac = [x for x in comps if str(x.get('route', '')).startswith('pac')]
            if pac: row['pac'] = [dict(trials=(x.get('stats') or {}).get('trials_completed'), U_log10=(x.get('stats') or {}).get('U_root_log10'), cutset=len(((x.get('stats') or {}).get('cutset') or {}).get('cutset') or []), certifier=x.get('certifier_per_row', [None])[0] if x.get('certifier_per_row') else None, terminal=(x.get('stats') or {}).get('terminal'), kernel_s=(x.get('stats') or {}).get('kernel_s'), zero_trials=(x.get('stats') or {}).get('zero_trials')) for x in pac][:3]
            row['stop_reason'] = (w.get('reason') or '')[:120]
            if w.get('status') == 'STOPPED' and w.get('stop_stats'): ss = w['stop_stats']; row['stop_component_stats'] = {k: (ss.get('stats') or {}).get(k) for k in ('trials_completed', 'U_root_log10', 'terminal', 'kernel_s', 'certify_s', 'trials_per_second', 'Z_estimate_over_U')} if isinstance(ss, dict) else None
        rows.append(row)
    out['runs'] = rows; out['unrun'] = [dict(case=c['case_id'], arm=c['arm'], budget=c['budget_s'], rep=c['replicate']) for c in unrun]
    # ---- reference audit of completed outputs
    audit = []; cat = collections.Counter()
    for c in cells:
        r = rec.get(c['cell_id'])
        if not r or r.get('status') != 'COMPLETED' or c['cohort'] not in ('external_core', 'selector_transfer_additions'): continue
        pts = None; ivs = None
        if c['arm'] in ('B0_FROZEN_V14', 'P1_PAC_CONDITIONAL', 'H1_HYBRID', 'A0_POINT', 'A1_CONDITIONAL'):
            w = worker(RD, r); pts = [[F(x) for x in rw] for rw in w['points']]; ivs = [[(F(a), F(b)) for a, b in rw] for rw in w['intervals']]
        else:
            mar = (r.get('comparator') or {}).get('output_file')
            if mar and os.path.exists(mar):
                try: pts = read_mar(mar)
                except Exception: pts = None
        if pts is None: continue
        ref = refs.get(c['case_id']); bref = b0_ref.get((c['case_id'], c['budget_s'])) if c['arm'] != 'B0_FROZEN_V14' else None
        if ref and ref['kind'] == 'R0_exact_rational':
            truth = ref['rows']; worst = max(abs(p - t) for pr, tr in zip(pts, truth) for p, t in zip(pr, tr)); cont = all(lo <= t <= hi for ivr, tr in zip(ivs, truth) for (lo, hi), t in zip(ivr, tr)) if ivs else None
            res = 'CONFIRMED_ACCURATE' if worst <= EPS else 'CONFIRMED_INACCURATE'; cat[(c['arm'], res)] += 1
            audit.append(dict(case=c['case_id'], arm=c['arm'], budget=c['budget_s'], rep=c['replicate'], reference='R0_exact_rational', max_abs_error=float(worst), accurate=res, intervals_contain_truth=cont, coordinates=sum(len(x) for x in truth)))
        elif bref is not None and len(bref) == len(pts) and all(len(a) == len(b) for a, b in zip(bref, pts)):
            # interval rule (03 §7): true error in [max(L-c, c-U, 0), max(|c-L|, |c-U|)] per coordinate
            upper = max(max(abs(p - lo), abs(p - hi)) for ivr, pr in zip(bref, pts) for (lo, hi), p in zip(ivr, pr)); lower = max(max(lo - p, p - hi, F(0)) for ivr, pr in zip(bref, pts) for (lo, hi), p in zip(ivr, pr))
            res = 'CONFIRMED_ACCURATE' if upper <= EPS else ('CONFIRMED_INACCURATE' if lower > EPS else 'UNRESOLVED_INTERVAL')
            cont = all(blo >= lo and bhi <= hi for ivr, br in zip(ivs, bref) for (lo, hi), (blo, bhi) in zip(ivr, br)) if ivs else None     # reference interval inside the published interval: coverage conditional on B0's certificate
            cat[(c['arm'], res)] += 1; audit.append(dict(case=c['case_id'], arm=c['arm'], budget=c['budget_s'], rep=c['replicate'], reference='deterministic enclosure sharing candidate lineage (B0 at the same budget)', error_upper=float(upper), error_lower=float(lower), accurate=res, reference_interval_inside_published=cont, coordinates=sum(len(x) for x in pts)))
        else:
            audit.append(dict(case=c['case_id'], arm=c['arm'], budget=c['budget_s'], rep=c['replicate'], reference='NONE (no R0 and no B0 enclosure at this budget)', accurate='UNRESOLVED_NO_REFERENCE')); cat[(c['arm'], 'UNRESOLVED_NO_REFERENCE')] += 1
    out['reference_audit'] = audit; json.dump(dict(refs={k: v['kind'] for k, v in refs.items()}, audit=audit, counts={'%s|%s' % k: v for k, v in cat.items()}), open(os.path.join(RD, 'REFERENCE_AUDIT.json'), 'w'), indent=1, default=str)
    # ---- table 3: completion per cohort / budget / arm
    P('## Table 3 — Completion by cohort, budget and arm (run level; per-case k/3 for stochastic arms)'); P(''); P('| cohort | budget | arm | planned | received | PUBLISHED deterministic | PUBLISHED PAC | PUBLISHED unguaranteed (heuristic) | PROVED_ZERO_EVIDENCE | DEADLINE | MEMORY | TOO_WIDE | numerical | invalid/fault | NOT_RUN | per-case 0/3,1/3,2/3,3/3 |'); P('|---|---:|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---|')
    arms_order = ['B0_FROZEN_V14', 'P1_PAC_CONDITIONAL', 'H1_HYBRID', 'A0_POINT', 'A1_CONDITIONAL', 'LIBDAI_EXACT', 'MERLIN_CTE', 'WMB', 'IJGP', 'LBP', 'PGMAX_SUMPRODUCT_BP', 'CBI_NATIVE']
    completion = {}
    for coh in ('external_core', 'selector_transfer_additions', 'CBI'):
        for budget in man['budgets_s']:
            for arm in arms_order:
                rs = [x for x in rows if x['cohort'] == coh and x['budget'] == budget and x['arm'] == arm]
                if not rs: continue
                cnt = lambda pred: sum(1 for x in rs if pred(x))
                det = cnt(lambda x: x['outcome'] == 'PUBLISHED' and x['guarantee'] == 'DETERMINISTIC'); pac = cnt(lambda x: x['outcome'] == 'PUBLISHED' and x['guarantee'] == 'PAC'); heur = cnt(lambda x: x['outcome'] == 'PUBLISHED' and x['guarantee'] == 'UNGUARANTEED')
                percase = ''
                if arm in ('P1_PAC_CONDITIONAL', 'H1_HYBRID'):
                    k = collections.Counter(sum(1 for x in rs if x['case'] == cs and x['outcome'] == 'PUBLISHED') for cs in sorted({x['case'] for x in rs})); percase = ','.join(str(k.get(i, 0)) for i in range(4))
                completion[(coh, budget, arm)] = dict(planned=len(rs), received=cnt(lambda x: x['status'] != 'NOT_RUN'), det=det, pac=pac, heur=heur)
                P('| %s | %d | %s | %d | %d | %d | %d | %d | %d | %d | %d | %d | %d | %d | %d | %s |' % (coh, budget, arm, len(rs), cnt(lambda x: x['status'] != 'NOT_RUN'), det, pac, heur, cnt(lambda x: x['outcome'] == 'PROVED_ZERO_EVIDENCE'), cnt(lambda x: x['outcome'] == 'DEADLINE'), cnt(lambda x: x['outcome'] == 'MEMORY'), cnt(lambda x: x['outcome'] == 'TOO_WIDE'), cnt(lambda x: x['outcome'] == 'NUMERICAL_RANGE_OR_PRECISION'), cnt(lambda x: x['outcome'] in ('INVALID_PLAN_OR_CERTIFICATE', 'FAULT')), cnt(lambda x: x['status'] == 'NOT_RUN'), percase))
    P('')
    # ---- table 4: B0 vs H1 (fresh), retained / lost / new, paired walls where both completed
    P('## Table 4 — Fresh B0 vs H1 (external core): retained / lost / new deterministic successes; paired observations only where both completed'); P('')
    for budget in man['budgets_s']:
        b0 = {x['case']: x for x in rows if x['arm'] == 'B0_FROZEN_V14' and x['budget'] == budget and x['cohort'] == 'external_core'}
        h1 = collections.defaultdict(list)
        for x in rows:
            if x['arm'] == 'H1_HYBRID' and x['budget'] == budget and x['cohort'] == 'external_core': h1[x['case']].append(x)
        b0ok = {c for c, x in b0.items() if x['outcome'] == 'PUBLISHED'}; h1_all3 = {c for c, xs in h1.items() if len(xs) == 3 and all(x['outcome'] == 'PUBLISHED' for x in xs)}; h1_any = {c for c, xs in h1.items() if any(x['outcome'] == 'PUBLISHED' for x in xs)}
        lost = sorted(b0ok - h1_all3); new = sorted(h1_all3 - b0ok); retained = sorted(b0ok & h1_all3)
        pairs = []
        for c in retained:
            wb = b0[c]['wall']; wh = statistics.median([x['wall'] for x in h1[c] if x['wall']])
            if wb and wh: pairs.append((c, round(wh / wb, 3), round(wb, 2), round(wh, 2), b0[c]['rss_MB'], round(statistics.median([x['rss_MB'] for x in h1[c]]))))
        P('- **%d s**: B0 published %d; H1 published 3/3 on %d (any seed: %d). Retained %d; LOST (B0 yes, H1 not 3/3): %s; NEW (H1 3/3, B0 no): %s. H1 PAC-guaranteed publications: %d runs.' % (budget, len(b0ok), len(h1_all3), len(h1_any), len(retained), lost or 'none', new or 'none', sum(1 for xs in h1.values() for x in xs if x['guarantee'] == 'PAC')))
        if pairs:
            rs_ = sorted(p[1] for p in pairs); P('  paired wall ratio H1(median of 3)/B0 over %d retained cases: median %.3f (timeouts censored, never a ratio); per case (case, ratio, B0 s, H1 s, B0 MB, H1 MB): %s' % (len(pairs), rs_[len(rs_) // 2], sorted(pairs, key=lambda t: t[1])))
        out['b0_vs_h1_%d' % int(budget)] = dict(b0=sorted(b0ok), h1_all3=sorted(h1_all3), h1_any=sorted(h1_any), lost=lost, new=new, pairs=pairs)
    P(''); P('Historical context only (not fresh matched controls): v1.4 32/46 at 20 s, 13/13 on the old 13-case 120 s panel.'); P('')
    # ---- table 5: comparator quality
    P('## Table 5 — Comparators (unguaranteed points; exact-capacity vs approximate tagged per run) and reference audit'); P(''); P('| arm | budget | published | DEADLINE | MEMORY | invalid/fault | exact-capacity runs | CONFIRMED_ACCURATE | CONFIRMED_INACCURATE | UNRESOLVED (interval) | UNRESOLVED (no reference) |'); P('|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|')
    for arm in ('LIBDAI_EXACT', 'MERLIN_CTE', 'WMB', 'IJGP', 'LBP', 'PGMAX_SUMPRODUCT_BP', 'B0_FROZEN_V14', 'P1_PAC_CONDITIONAL', 'H1_HYBRID'):
        for budget in man['budgets_s']:
            rs = [x for x in rows if x['arm'] == arm and x['budget'] == budget and x['cohort'] in ('external_core', 'selector_transfer_additions')]
            if not rs: continue
            exact_cap = sum(1 for c in cells if c['arm'] == arm and c['budget_s'] == budget and ((rec.get(c['cell_id']) or {}).get('comparator') or {}).get('execution_capacity') == 'exact')
            au = [a for a in audit if a['arm'] == arm and a['budget'] == budget]
            P('| %s | %d | %d | %d | %d | %d | %d | %d | %d | %d | %d |' % (arm, budget, sum(1 for x in rs if x['outcome'] == 'PUBLISHED'), sum(1 for x in rs if x['outcome'] == 'DEADLINE'), sum(1 for x in rs if x['outcome'] == 'MEMORY'), sum(1 for x in rs if x['outcome'] in ('INVALID_PLAN_OR_CERTIFICATE', 'FAULT')), exact_cap, sum(1 for a in au if a['accurate'] == 'CONFIRMED_ACCURATE'), sum(1 for a in au if a['accurate'] == 'CONFIRMED_INACCURATE'), sum(1 for a in au if a['accurate'] == 'UNRESOLVED_INTERVAL'), sum(1 for a in au if a['accurate'] == 'UNRESOLVED_NO_REFERENCE')))
    P(''); P('References: R0 exact rational truth for %d cases (REFERENCES_R0.json, charged offline job); B0 exact-arithmetic enclosures (delta 0) at the same budget for %d (case, budget) pairs = certified reference INTERVALS sharing candidate lineage (interval rule of 03 §7: upper <= eps confirms, lower > eps disproves, else UNRESOLVED); everything else UNRESOLVED (no reference). Containment of the reference interval inside a PAC interval is recorded per run in REFERENCE_AUDIT.json (coverage conditional on B0 certificate).' % (sum(1 for v in refs.values() if v['kind'] == 'R0_exact_rational'), len(b0_ref))); P('')
    # ---- table 6: matched ablation
    P('## Table 6 — Matched fixed-plan ablation at 120 s (A0_POINT vs A1_CONDITIONAL, same cutset / order / tree seed)'); P(''); P('| case | A0 outcome | A0 trials | A0 var width (row 0, last check) | A1 outcome | A1 trials | A1 var width | A1 kernel s | cutset | U log10 |'); P('|---|---|---:|---:|---|---:|---:|---:|---:|---:|')
    for c in sorted({x['case'] for x in rows if x['arm'] == 'A0_POINT'}):
        a0 = next((x for x in rows if x['arm'] == 'A0_POINT' and x['case'] == c), None); a1 = next((x for x in rows if x['arm'] == 'A1_CONDITIONAL' and x['case'] == c), None)
        def info(x):
            if not x: return ('NOT_RUN', None, None, None, None, None)
            p = (x.get('pac') or [{}])[0]; ss = x.get('stop_component_stats') or {}
            return (x['outcome'], p.get('trials') or ss.get('trials_completed'), None, p.get('kernel_s') or ss.get('kernel_s'), p.get('cutset'), p.get('U_log10') or ss.get('U_root_log10'))
        i0 = info(a0); i1 = info(a1); P('| %s | %s | %s | %s | %s | %s | %s | %s | %s | %s |' % (c, i0[0], i0[1], i0[2], i1[0], i1[1], i1[2], (round(i1[3], 1) if i1[3] else None), i1[4] or i0[4], (round(i1[5] or i0[5], 1) if (i1[5] or i0[5]) else None)))
    P(''); P('The variance theorem (section 7) is an expected second-moment ordering under the same Q; observed completion and width differences are one observation per case.'); P('')
    # ---- table 7: failure attribution (recorded quantities)
    P('## Table 7 — Failure attribution of non-published primary runs (external core), from recorded quantities'); P(''); P('| case | budget | arm | rep | outcome | attribution (recorded) |'); P('|---|---:|---|---:|---|---|')
    for x in rows:
        if x['cohort'] != 'external_core' or x['arm'] not in ('B0_FROZEN_V14', 'P1_PAC_CONDITIONAL', 'H1_HYBRID') or x['outcome'] in ('PUBLISHED', 'NOT_RUN'): continue
        ss = x.get('stop_component_stats') or {}; attr = []
        if x['arm'] == 'B0_FROZEN_V14': attr.append('frozen deterministic pipeline: %s' % (x.get('stop_reason') or x['outcome']))
        else:
            if ss.get('terminal') == 'DEADLINE' and (ss.get('trials_completed') or 0) > 0: attr.append('statistical width at the deadline: %s trials, U/Z ~ %s (envelope looseness), %.0f trials/s' % (ss.get('trials_completed'), ('%.2g' % (1 / ss['Z_estimate_over_U'])) if ss.get('Z_estimate_over_U') else 'n/a', ss.get('trials_per_second') or 0))
            elif ss.get('trials_completed') == 0 or ss.get('trials_completed') is None: attr.append('no completed trial: source/planning/template construction cost or deterministic route consumed the budget (%s)' % (x.get('stop_reason') or '')[:80])
            else: attr.append('%s: %s' % (x['outcome'], (x.get('stop_reason') or '')[:80]))
        P('| %s | %d | %s | %d | %s | %s |' % (x['case'], x['budget'], x['arm'], x['rep'], x['outcome'], '; '.join(attr)))
    P('')
    # ---- table 8: ledger
    led = [json.loads(l) for l in open(os.path.join(RD, 'PAC_LEDGER.jsonl')) if l.strip()]; recs = [r for r in led if r.get('kind') == 'RECEIPT']; by = collections.defaultdict(float)
    for r in recs: by[r['scope']] += r['wall_s']
    dev_total = 0.0
    for L_ in glob.glob(os.path.join(RD, 'dev*', 'PAC_LEDGER.jsonl')):
        for l in open(L_):
            r = json.loads(l)
            if r.get('kind') == 'RECEIPT': dev_total += r['wall_s']
    P('## Table 8 — Resource ledger (Python-monotonic receipted wall; every job supervised)'); P(''); P('| scope | receipts | seconds |'); P('|---|---:|---:|')
    for k, v in sorted(by.items()): P('| %s | %d | %.1f |' % (k, sum(1 for r in recs if r['scope'] == k), v))
    P('| development campaigns (dev*/PAC_LEDGER.jsonl, development seeds) | — | %.1f |' % dev_total)
    P('| **total scored + qualification + packaging (this ledger)** | %d | **%.1f** |' % (len(recs), sum(by.values())))
    P(''); P('Prospective ceiling (manifest): scored matrix %.0f s nominal; orchestration %.0f s; total ceiling %.0f s (04 formula). Actual scored consumption above. Interactive post-processing is uncharged (UNKNOWN exposure).' % (man['ceiling']['scored_matrix_seconds'], man['ceiling']['orchestration_seconds'], man['ceiling']['total_ceiling_seconds']))
    out['completion'] = {'%s|%s|%s' % k: v for k, v in completion.items()}; out['ledger'] = dict(by_scope=dict(by), total=sum(by.values()), dev_total=dev_total, ceiling=man['ceiling'])
    json.dump(out, open(os.path.join(RD, 'RESULTS_PAC.json'), 'w'), indent=1, default=str); open(os.path.join(RD, 'RESULTS_PAC.md'), 'w').write('\n'.join(L) + '\n'); print('written', len(L), 'lines;', len(rows), 'runs;', len(unrun), 'unrun')


if __name__ == '__main__': main(sys.argv[1])
