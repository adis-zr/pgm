"""CQR RESULTS REPORT -- counts and rows only (no performance-claim language). Reads the frozen manifest, the receipts (cells/*/receipt.json), the worker outputs, REFERENCES_R0.json
and GATE_RESULT.json (gate binding: the gated set is reconciled with the receipts / CURRENT output bytes / effective task dependencies). Writes RESULTS_CQR.json + RESULTS_CQR.md:
  Table 1  inventory reconciliation per registered cohort (registered / available / unavailable rows / planned / executed / unrun / arms);
  Table 2  per-run rows (cell, cohort, case, arm, budget, rep, status, outcome, guarantee, route, wall, charged work reference / optional, committed compiler operators, bias,
           frontier counts, ratio draws, epochs);
  Table 3  reference audit (per query lo <= truth <= hi and |point - truth| <= eps; normalizer: relative): ACCURATE / INACCURATE_PAC_MISS (PAC) / CONFIRMED_INACCURATE
           (DETERMINISTIC) / INACCURATE_UNGUARANTEED (comparators) / UNDEFINED_AGREES / ZERO_AGREES / UNRESOLVED_NO_REFERENCE / MALFORMED; the same per-singleton check for the
           baseline rows (intervals / points) and the comparator MAR points;
  SEPARATE tables (never pooled): (a) legacy explicit tasks R0 = H1_HYBRID vs N1_CQR vs B0 anchor; (b) new tasks G0_CQR vs N1_CQR; (c) ablations N1 vs N1_NO_*;
           (d) normalizer panel; (e) native outcomes (counts only); (f) comparators (UNGUARANTEED points; accuracy vs reference only);
  Table 4  outcome counts by arm (PUBLISHED-DETERMINISTIC / PUBLISHED-PAC / PROVED_ZERO_EVIDENCE / DEADLINE / MEMORY / FAULT / other);
  Table 5  mechanism attribution per constructed family and regime (operators committed in the N1 certificates, route, outcome; the family's named ablation alongside);
  Table 6  ledger (charged seconds by scope) and the gate binding (gate version, gated_set_sha256).
main(RD, manifest_name, write=False) derives everything without writing (the closeout re-derives and compares the summary).
    python -m research.campaigns.cqr.report <RD> [--manifest NAME]"""
from ._paths import HERE, ROOT, CODE, CEX, PAC, NEWARM, RUNTIME, PY, runs_root, source_path, subprocess_env
import sys, os, json, glob, collections, hashlib, time, importlib.util
sys.set_int_max_str_digits(0)
from ._legacy import load_pac
PR = load_pac('registry'); from pgm.algorithms.structural import core
from fractions import Fraction as F




from . import registry as R
from . import gate as CG
REPORT_VERSION = 'cqr-report-v1.1 (2026-11-19, repair-2 review CQR-AF2-02: explicit --gate / --out-dir for the successor verification path, gate file identity recorded in gate_binding; v1 2026-11-16: counts and rows only; per-query reference audit; separate tables per comparison; mechanism attribution; gate binding re-hashed)'
LEDGER = 'CQR_LEDGER.jsonl'
LEGACY_COHORTS = tuple(k for k, v in PR.COHORTS.items() if v['representation'] == 'uai_table')
NEW_TASK_COHORTS = ('constructed', 'new_uai2022', 'new_wmc2024', 'query_transfer', 'bounded_query_osstar')
NATIVE_COHORTS = tuple(k for k, v in PR.COHORTS.items() if v['representation'] != 'uai_table')
PAC_BASELINE_ROW_ARMS = ('B0_FROZEN_V14',) + tuple(PR.CANDIDATE_ARMS)
VATT = {}            # cell_id -> the gate's VERIFIED attribution (route / class / exact / commits / bias ledger) read from GATE_RESULT.gated_set (R6)
OUTCOME_CLASSES = ('PUBLISHED-DETERMINISTIC', 'PUBLISHED-PAC', 'PUBLISHED-UNGUARANTEED', 'PROVED_ZERO_EVIDENCE', 'DEADLINE', 'MEMORY', 'FAULT', 'other', 'NOT_RUN')


def sha(p):
    h = hashlib.sha256()
    with open(p, 'rb') as f:
        for b in iter(lambda: f.read(1 << 20), b''): h.update(b)
    return h.hexdigest()


def _frac(x):
    try: return F(str(x))
    except Exception: return None


def load(RD, manifest_name, gate_path=None):
    """`gate_path` (repair-2 review CQR-AF2-02): an EXPLICIT gate result file to bind instead of RD/GATE_RESULT.json (the successor verification path passes its own result; the default
    behaviour is unchanged). The receipts / outputs / evidence closure are always reconciled against the run directory RD."""
    man = json.load(open(os.path.join(RD, manifest_name))); rec = {}; shas = {}
    for rp in glob.glob(os.path.join(RD, 'cells', '*', 'receipt.json')):
        r = json.load(open(rp)); rec[r['cell_id']] = r; shas[r['cell_id']] = sha(rp)
    gp = gate_path or os.path.join(RD, 'GATE_RESULT.json'); gb = None; VATT.clear()
    if os.path.exists(gp):
        G = json.load(open(gp)); gs = G.get('gated_set'); mism = []; VATT.update({e.get('cell_id'): e.get('verified_attribution') for e in (gs or []) if isinstance(e, dict) and e.get('verified_attribution')})
        if isinstance(gs, list):
            seen = set(); by_id = {c['cell_id']: c for c in man['cells']}
            for e in gs:
                cid = e.get('cell_id'); seen.add(cid); r = rec.get(cid)
                if r is None: mism.append('gated cell %s has no receipt on disk' % cid); continue
                if shas[cid] != e.get('receipt_sha256') or r.get('output_sha256') != e.get('output_sha256') or r.get('status') != e.get('status') or r.get('outcome') != e.get('outcome') or r.get('guarantee_type') != e.get('guarantee'): mism.append('receipt %s differs from the gated set (stale gate or changed output)' % cid)
                wp = os.path.join(RD, r['worker_output']) if r.get('worker_output') else None
                if wp is not None and (sha(wp) if os.path.exists(wp) else None) != e.get('output_sha256'): mism.append('output bytes of %s differ from the gated hash' % cid)
                of = (r.get('comparator') or {}).get('output_file')
                if of and (not os.path.exists(of) or sha(of) != (r.get('comparator') or {}).get('output_sha256')): mism.append('comparator output bytes of %s differ from the receipt' % cid)
                for rel, h in (e.get('evidence') or {}).items():
                    fp = rel if os.path.isabs(rel) else os.path.join(RD, rel)
                    if (sha(fp) if os.path.exists(fp) else None) != h: mism.append('evidence file %s of cell %s differs from the gated hash or is missing' % (rel, cid))
                c_ = by_id.get(cid)
                if c_ is not None and (r.get('status') == 'COMPLETED' or r.get('outcome') == 'PROVED_ZERO_EVIDENCE'): mism.extend(CG.dependency_closure_failures(RD, c_, e.get('evidence')))
                if e.get('verified') is False and r.get('status') == 'COMPLETED': mism.append('gated entry %s was not verified by the gate' % cid)
            for cid in rec:
                if cid not in seen: mism.append('receipt %s is not in the gated set' % cid)
            gb = dict(gate_version=G.get('gate_version'), gated_set_sha256=G.get('gated_set_sha256'), manifest_sha256=G.get('manifest_sha256'), gate_passed=G.get('gate_passed'), failures=len(G.get('failures') or []), counters=G.get('counters'), mismatch=mism, gate_file=(os.path.relpath(gp, RD) if gate_path else 'GATE_RESULT.json'), gate_file_sha256=sha(gp))
        else: gb = dict(gate_version=G.get('gate_version'), mismatch=['GATE_RESULT carries no gated set'])
    return man, rec, gb


def worker(RD, r):
    p = r.get('worker_output')
    if not p: return {}
    p = os.path.join(RD, p); return json.load(open(p)) if os.path.exists(p) else {}


def outcome_class(row):
    if row['status'] == 'NOT_RUN': return 'NOT_RUN'
    o = row['outcome']; g = row['guarantee']
    if o == 'PUBLISHED': return {'DETERMINISTIC': 'PUBLISHED-DETERMINISTIC', 'PAC': 'PUBLISHED-PAC', 'UNGUARANTEED': 'PUBLISHED-UNGUARANTEED'}.get(g, 'other')
    if o in ('PROVED_ZERO_EVIDENCE', 'DEADLINE', 'MEMORY', 'FAULT'): return o
    return 'other'


def audit_answers(answers, truth_answers, eps, guarantee, is_ratio_rel=False):
    """per-query check of a CQR publication against the exact reference answers (strings; 'UNDEFINED' / 'ZERO_EVIDENCE' typed)"""
    if len(answers) != len(truth_answers): return dict(accurate='MALFORMED', reason='answer count %d differs from the reference %d' % (len(answers), len(truth_answers)))
    contained = True; point_ok = True; worst = F(0); undefined_agree = 0; mism_def = 0
    for a, t in zip(answers, truth_answers):
        st = a.get('status'); lo = a.get('lo'); hi = a.get('hi'); pt = a.get('point')
        if t == 'UNDEFINED':
            if st == 'UNDEFINED' or lo == 'UNDEFINED': undefined_agree += 1
            else: mism_def += 1
            continue
        if st == 'UNDEFINED' or lo == 'UNDEFINED': mism_def += 1; continue
        tv = _frac(t); lo_ = _frac(lo); hi_ = _frac(hi); pt_ = _frac(pt)
        if None in (tv, lo_, hi_, pt_): return dict(accurate='MALFORMED', reason='unparseable answer / reference')
        if not (lo_ <= tv <= hi_): contained = False
        err = abs(pt_ - tv) / (tv if (is_ratio_rel and tv != 0) else 1); worst = max(worst, err)
        if err > eps: point_ok = False
    ok = contained and point_ok and mism_def == 0
    if ok and undefined_agree == len(answers): res = 'UNDEFINED_AGREES'
    elif ok: res = 'ACCURATE'
    else: res = {'PAC': 'INACCURATE_PAC_MISS', 'DETERMINISTIC': 'CONFIRMED_INACCURATE'}.get(guarantee, 'INACCURATE_UNGUARANTEED')
    return dict(accurate=res, intervals_contain_truth=contained, point_within_eps=point_ok, max_error=float(worst), undefined_agree=undefined_agree, definedness_mismatch=mism_def, queries=len(answers))


def audit_rows(ivs, pts, truth_rows, eps, guarantee):
    """per-singleton check of legacy per-variable rows (intervals optional) against the exact per-variable reference rows"""
    if len(pts) != len(truth_rows) or any(len(a) != len(b) for a, b in zip(pts, truth_rows)): return dict(accurate='MALFORMED', reason='row shape differs from the reference')
    worst = F(0); contained = True
    for v in range(len(pts)):
        for s in range(len(pts[v])):
            t = _frac(truth_rows[v][s]); p = _frac(pts[v][s])
            if t is None or p is None: return dict(accurate='MALFORMED', reason='unparseable row entry')
            worst = max(worst, abs(p - t))
            if ivs is not None:
                lo = _frac(ivs[v][s][0]); hi = _frac(ivs[v][s][1])
                if lo is None or hi is None or not (lo <= t <= hi): contained = False
    ok = worst <= eps and contained
    res = 'ACCURATE' if ok else {'PAC': 'INACCURATE_PAC_MISS', 'DETERMINISTIC': 'CONFIRMED_INACCURATE'}.get(guarantee, 'INACCURATE_UNGUARANTEED')
    return dict(accurate=res, intervals_contain_truth=(contained if ivs is not None else None), point_within_eps=(worst <= eps), max_error=float(worst), coordinates=sum(len(x) for x in pts))


def audit_covered_singletons(ivs, pts, smap, eps, guarantee):
    """per-singleton check of legacy rows restricted to the singletons (v,s) the reference task covers (partial query schedules)"""
    worst = F(0); contained = True; n = 0
    for key, t in smap.items():
        v, s = (int(x) for x in key.split(',')); tv = _frac(t); p = _frac(pts[v][s])
        if tv is None or p is None: return dict(accurate='MALFORMED', reason='unparseable row entry')
        worst = max(worst, abs(p - tv)); n += 1
        if ivs is not None:
            lo = _frac(ivs[v][s][0]); hi = _frac(ivs[v][s][1])
            if lo is None or hi is None or not (lo <= tv <= hi): contained = False
    ok = worst <= eps and contained
    res = 'ACCURATE' if ok else {'PAC': 'INACCURATE_PAC_MISS', 'DETERMINISTIC': 'CONFIRMED_INACCURATE'}.get(guarantee, 'INACCURATE_UNGUARANTEED')
    return dict(accurate=res, intervals_contain_truth=(contained if ivs is not None else None), point_within_eps=(worst <= eps), max_error=float(worst), coordinates=n, coverage='partial')


def read_mar(path):
    toks = open(path).read().split(); i = toks.index('MAR') + 1 if 'MAR' in toks else 0
    n = int(toks[i]); i += 1; rows = []
    for _ in range(n):
        k = int(toks[i]); i += 1; rows.append([F(toks[i + j]) for j in range(k)]); i += k
    return rows


def main(RD, manifest_name='CAMPAIGN_MANIFEST.json', write=True, gate_path=None, out_dir=None):
    """`gate_path` / `out_dir` (repair-2 review CQR-AF2-02): the successor verification path binds its OWN gate result and writes RESULTS_CQR.* into its own directory; the original run
    directory is read, never written. Defaults: RD/GATE_RESULT.json and RD (unchanged behaviour)."""
    RD = os.path.abspath(RD); out_dir = os.path.abspath(out_dir) if out_dir else RD; man, rec, gb = load(RD, manifest_name, gate_path); cells = man['cells']; L = []; P = L.append
    out = dict(report_version=REPORT_VERSION, manifest=manifest_name, manifest_sha256=sha(os.path.join(RD, manifest_name)), gate_binding=gb, gated_set_sha256=(gb or {}).get('gated_set_sha256'), registry_version=R.REGISTRY_VERSION)
    unrun = [c for c in cells if c['cell_id'] not in rec]; inv = man['inventory']; inv_by_case = {r.get('case_id'): r for r in inv}
    P('# CQR CAMPAIGN -- RESULTS (%s UTC; %s; %s)' % (time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()), REPORT_VERSION, 'DEV manifest' if man.get('dev') else 'scored manifest')); P('')
    P('Frozen manifest `%s` sha256 `%s` (without self `%s`); root seed `%s`; planned cells %d, receipts %d, UNRUN %d. Counts and rows only: no performance claim is made in this document.' % (manifest_name, out['manifest_sha256'], man.get('manifest_sha256_without_self'), (man.get('seeds') or {}).get('root_seed'), len(cells), len(rec), len(unrun))); P('')
    # ---- Table 1
    P('## Table 1 -- Inventory reconciliation per registered cohort'); P(''); P('| cohort | representation | registered rows | available | unavailable (visible) | arms scheduled | planned cells | executed | unrun |'); P('|---|---|---:|---:|---|---|---:|---:|---:|')
    coh_cells = collections.defaultdict(list)
    for c in cells: coh_cells[c['cohort']].append(c)
    inv_rows = collections.defaultdict(list)
    for r in inv: inv_rows[r['cohort']].append(r)
    reconciliation = {}
    for coh in R.COHORT_ORDER:
        rows_ = inv_rows.get(coh, []); planned_ = coh_cells.get(coh, [])
        if not rows_ and not planned_: continue
        avail = [r for r in rows_ if r.get('model_sha256')]; unav = [r for r in rows_ if not r.get('model_sha256')]; ex_ = sum(1 for c in planned_ if c['cell_id'] in rec); arms_ = sorted({c['arm'] for c in planned_})
        reconciliation[coh] = dict(registered=len(rows_), available=len(avail), unavailable=[dict(case=r.get('case_id'), status=str(r.get('status'))[:80]) for r in unav], planned=len(planned_), executed=ex_, unrun=len(planned_) - ex_, arms=arms_)
        P('| %s | %s | %d | %d | %s | %s | %d | %d | %d |' % (coh, R.COHORTS[coh]['representation'], len(rows_), len(avail), ('; '.join('%s: %s' % (r.get('case_id'), str(r.get('status'))[:40]) for r in unav[:4]) + (' (+%d)' % (len(unav) - 4) if len(unav) > 4 else '')) or 'none', ', '.join(arms_) or '--', len(planned_), ex_, len(planned_) - ex_))
    assert sum(v['planned'] for v in reconciliation.values()) == len(cells), 'Table 1 does not reconcile with the manifest cells'
    out['inventory_reconciliation'] = reconciliation
    P(''); P('Arms unavailable (registry): %s' % '; '.join('%s: %s' % (k, str(v)[:80]) for k, v in (man.get('arms') or {}).get('unavailable', {}).items())); P('')
    # ---- references
    refs = {}; rp = os.path.join(RD, 'REFERENCES_R0.json'); ref_rejected = []
    if os.path.exists(rp):
        RJ = json.load(open(rp)); out['references_manifest_sha256'] = RJ.get('manifest_sha256'); out['references_version'] = RJ.get('references_version'); out['references_file_sha256'] = sha(rp)
        if RJ.get('manifest_sha256') != out['manifest_sha256']: ref_rejected.append(dict(case='*', reason='REFERENCES_R0.json was built for a different manifest; every reference rejected'))
        else:
            for k, v in (RJ.get('references') or {}).items():
                if v.get('kind') in ('R0_exact', 'R0_zero_evidence'):
                    if not v.get('binding_matches_manifest'): ref_rejected.append(dict(case=k, reason='reference binding differs from the frozen input')); continue
                    refs[k] = v
    def eps_of(c):
        tp = c.get('task_params') or {}; return F(str(tp.get('epsilon') or (man.get('task') or {}).get('epsilon', '1/200')))
    # ---- Table 2 per-run rows
    rows = []
    for c in cells:
        r = rec.get(c['cell_id']); w = worker(RD, r) if r else {}
        row = dict(cell_id=c['cell_id'], cohort=c['cohort'], case=c['case_id'], arm=c['arm'], kind=c.get('kind'), budget=c['budget_s'], rep=c['replicate'], status=(r or {}).get('status', 'NOT_RUN'), outcome=(r or {}).get('outcome', 'NOT_RUN'), guarantee=(r or {}).get('guarantee_type', 'NONE'), route=(r or {}).get('route'), wall=(r or {}).get('launch_relative_wall_s'), rss_MB=round(((r or {}).get('supervisor') or {}).get('peak_MB', 0) or 0), nonce=(r or {}).get('nonce'), output_sha256=(r or {}).get('output_sha256'))
        if c['arm'] in R.CQR_ARMS and w:
            cert = w.get('certificate') or {}; wk = cert.get('work') or {}; comp = cert.get('compile') or {}; log = comp.get('log') or {}
            row['work_reference'] = (wk.get('reference') or {}).get('total'); row['work_optional'] = (wk.get('optional') or {}).get('total'); va = VATT.get(c['cell_id'])
            if va:        # VERIFIED attribution (second review R6): route / class / exactness / commits / bias come from the checker, not from the worker's or receipt's own fields
                row['route'] = va.get('route'); row['exact'] = bool(va.get('exact')); row['guarantee_source'] = 'checker-verified attribution recorded in the gated set (R6)'
                row['committed_operators'] = list(va.get('commits') or []); row['bias'] = va.get('compiled_bias'); row['bias_applied_to_original_answers'] = va.get('bias_applied_to_original_answers'); row['bias_interpretation'] = va.get('bias_interpretation')
                row['claimed_route'] = w.get('route'); row['attribution_mismatch'] = (w.get('route') != va.get('route')) or ([str(b) for b in (w.get('bias') or [])] != [str(b) for b in (va.get('compiled_bias') or [])])
            else:
                row['route'] = w.get('route'); row['exact'] = bool(w.get('exact')); row['guarantee_source'] = 'UNVERIFIED: the gate recorded no attribution for this cell (not gated)'
                row['committed_operators'] = [c_.get('op') for c_ in (comp.get('certificates') or []) if c_.get('kind') == 'commit']; row['bias'] = w.get('bias') or cert.get('bias')
            fr = cert.get('frontier') or {}; row['frontier'] = {k: fr.get(k) for k in ('open_cells', 'resolved_cells', 'splits', 'closures')} if fr else None
            row['ratio_draws'] = (cert.get('ratio_stream') or {}).get('t'); row['epochs'] = len(cert.get('epochs') or []); row['stop_reason'] = (w.get('reason') or '')[:120]; row['mode'] = w.get('mode')
            row['reference_progress'] = (cert.get('reference') or {}).get('progress'); row['events'] = len(cert.get('events') or [])
        elif w:
            st = w.get('stats') or {}; comps = st.get('components') or []
            row['routes'] = [(x.get('route'), x.get('guarantee')) for x in comps][:6]; row['stop_reason'] = (w.get('reason') or '')[:120]
        row['outcome_class'] = outcome_class(row); rows.append(row)
    out['runs'] = rows; out['unrun'] = [dict(case=c['case_id'], arm=c['arm'], budget=c['budget_s'], rep=c['replicate']) for c in unrun]
    P('## Table 2 -- Per-run rows'); P(''); P('| # | cohort | case | arm | budget | rep | status | outcome | guarantee | route | wall s | work ref / opt | committed operators | max bias | frontier (open/resolved/splits/closures) | ratio draws | epochs |'); P('|---:|---|---|---|---:|---:|---|---|---|---|---:|---|---|---|---|---:|---:|')
    for i, x in enumerate(rows):
        fr = x.get('frontier') or {}; mb = max((_frac(b) for b in (x.get('bias') or [])), default=None)
        P('| %d | %s | %s | %s | %d | %d | %s | %s | %s | %s | %s | %s | %s | %s | %s | %s | %s |' % (i, x['cohort'], x['case'], x['arm'], x['budget'], x['rep'], x['status'], x['outcome'], x['guarantee'], x.get('route') or ('; '.join('%s' % a for a, _g in (x.get('routes') or [])) or '--'), ('%.2f' % x['wall']) if isinstance(x.get('wall'), (int, float)) else '--', ('%s / %s' % (x.get('work_reference'), x.get('work_optional'))) if x.get('work_reference') is not None else '--', ','.join(x.get('committed_operators') or []) or '--', (str(mb) if mb is not None else '--'), ('%s/%s/%s/%s' % (fr.get('open_cells'), fr.get('resolved_cells'), fr.get('splits'), fr.get('closures'))) if fr else '--', x.get('ratio_draws') if x.get('ratio_draws') is not None else '--', x.get('epochs') if x.get('epochs') is not None else '--'))
    P('')
    # ---- Table 3 reference audit
    audit = []; acat = collections.Counter()
    for c in cells:
        r = rec.get(c['cell_id'])
        if not r or r.get('status') == 'NOT_RUN': continue
        arm = c['arm']; a = dict(cell_id=c['cell_id'], cohort=c['cohort'], case=c['case_id'], arm=arm, budget=c['budget_s'], rep=c['replicate'], guarantee=r.get('guarantee_type'), outcome=r.get('outcome'))
        if r.get('outcome') not in ('PUBLISHED', 'PROVED_ZERO_EVIDENCE'): continue          # a refused / stopped row carries no accuracy claim: its tolerance is NOT parsed (seventh review, CQR-R6-05: a typed INVALID_TASK row stays reportable)
        ref = refs.get(c['case_id']); eps = eps_of(c)
        if ref is None: a['reference'] = 'NONE'; a['accurate'] = 'UNRESOLVED_NO_REFERENCE'; audit.append(a); acat[(arm, a['accurate'])] += 1; continue
        a['reference'] = ref['kind']
        if r.get('outcome') == 'PROVED_ZERO_EVIDENCE':
            a['accurate'] = 'ZERO_AGREES' if ref['kind'] == 'R0_zero_evidence' else ('CONFIRMED_INACCURATE' if R.validator_of(arm) in ('cqr_candidate', 'uai_candidate') else 'INACCURATE_UNGUARANTEED'); a['reason'] = None if a['accurate'] == 'ZERO_AGREES' else 'zero-evidence claim contradicted by the exact reference (Z > 0)'
            audit.append(a); acat[(arm, a['accurate'])] += 1; continue
        if ref['kind'] == 'R0_zero_evidence':
            a['accurate'] = 'CONFIRMED_INACCURATE' if r.get('guarantee_type') in ('PAC', 'DETERMINISTIC') else 'INACCURATE_UNGUARANTEED'; a['reason'] = 'publication on a task whose exact reference has Z = 0 (the positive-mass claim is deterministic)'; audit.append(a); acat[(arm, a['accurate'])] += 1; continue
        w = worker(RD, r)
        if arm in R.CQR_ARMS:
            ans = w.get('answers')
            if not isinstance(ans, list): a['accurate'] = 'MALFORMED'; a['reason'] = 'no answers in the worker output'
            elif (c.get('task_params') or {}).get('normalizer_task'):
                zt = ref.get('normalizer_reference') or ref.get('Z')
                a.update(audit_answers(ans, [zt], eps, r.get('guarantee_type'), is_ratio_rel=True)); a['normalizer'] = True
            else:
                if [x.get('query') for x in ans] != list(ref.get('queries') or []): a['accurate'] = 'MALFORMED'; a['reason'] = 'query names differ from the reference task'
                else: a.update(audit_answers(ans, ref['answers'], eps, r.get('guarantee_type')))
        elif arm in PAC_BASELINE_ROW_ARMS:
            if (w.get('binding') or {}).get('model_sha256') != c.get('model_sha256') or (w.get('binding') or {}).get('evidence_sha256') != c.get('evidence_sha256'): a['accurate'] = 'MALFORMED'; a['reason'] = 'baseline output binding differs from the frozen input'
            elif ref.get('rows') is not None:
                try: a.update(audit_rows(w.get('intervals'), w.get('points'), ref['rows'], eps, r.get('guarantee_type')))
                except Exception as ex: a['accurate'] = 'MALFORMED'; a['reason'] = 'baseline rows unparseable: %s' % type(ex).__name__
            elif ref.get('singleton_map'):
                try: a.update(audit_covered_singletons(w.get('intervals'), w.get('points'), ref['singleton_map'], eps, r.get('guarantee_type'))); a['reason'] = 'partial schedule: the baseline arm answered ALL singletons; audited on the %d singletons the reference task covers' % len(ref['singleton_map'])
                except Exception as ex: a['accurate'] = 'MALFORMED'; a['reason'] = 'baseline rows unparseable: %s' % type(ex).__name__
            else: a['accurate'] = 'UNRESOLVED_NO_REFERENCE'; a['reason'] = 'the reference task declares no singleton query; the baseline arm answered all singletons'
        elif R.validator_of(arm) == 'comparator_mar':
            mar = (r.get('comparator') or {}).get('output_file')
            if ref.get('rows') is None: a['accurate'] = 'UNRESOLVED_NO_REFERENCE'; a['reason'] = 'reference task is not the all-singleton contract'
            elif not mar or not os.path.exists(mar): a['accurate'] = 'MALFORMED'; a['reason'] = 'comparator output missing'
            else:
                try: a.update(audit_rows(None, read_mar(mar), ref['rows'], eps, 'UNGUARANTEED'))
                except Exception as ex: a['accurate'] = 'MALFORMED'; a['reason'] = 'comparator output unparseable: %s' % type(ex).__name__
        else: a['accurate'] = 'UNRESOLVED_NO_REFERENCE'; a['reason'] = 'native arm: own in-invocation checker; no R0 audit defined'
        audit.append(a); acat[(arm, a['accurate'])] += 1
    out['reference_audit'] = audit; out['references_used'] = {k: v['kind'] for k, v in refs.items()}; out['references_rejected'] = ref_rejected
    P('## Table 3 -- Reference audit (exact references only; binding-validated; classification per query: lo <= truth <= hi and |point - truth| <= eps; normalizer: relative)'); P(''); P('| cohort | case | arm | budget | rep | guarantee | outcome | reference | classification | contained | point within eps | max error | undefined agree | reason |'); P('|---|---|---|---:|---:|---|---|---|---|---|---|---:|---:|---|')
    for a in audit: P('| %s | %s | %s | %d | %d | %s | %s | %s | %s | %s | %s | %s | %s | %s |' % (a['cohort'], a['case'], a['arm'], a['budget'], a['rep'], a.get('guarantee'), a.get('outcome'), a.get('reference'), a.get('accurate'), a.get('intervals_contain_truth', '--'), a.get('point_within_eps', '--'), ('%.3g' % a['max_error']) if a.get('max_error') is not None else '--', a.get('undefined_agree', '--'), (a.get('reason') or '')[:90]))
    P(''); P('References: %d exact / zero-evidence references bound to this manifest; rejected: %d. Classes per arm: %s' % (len(refs), len(ref_rejected), json.dumps({'%s|%s' % k: v for k, v in sorted(acat.items())}))); P('')
    # ---- separate comparison tables
    by = collections.defaultdict(list)
    for x in rows: by[(x['cohort'], x['case'], x['budget'], x['arm'])].append(x)
    def cell_str(xs):
        if not xs: return '--'
        return '; '.join('%s/%s%s' % (x['outcome'], x['guarantee'], (' [%s]' % x['route']) if x.get('route') else '') for x in xs)
    def case_budgets(cohs):
        return sorted({(x['cohort'], x['case'], x['budget']) for x in rows if x['cohort'] in cohs}, key=lambda t: (R.COHORTS[t[0]]['order'], t[1], t[2]))
    P('## Table (a) -- Legacy explicit tasks: R0 = H1_HYBRID (repaired baseline, all-singleton contract) vs N1_CQR vs the B0 anchor (SEPARATE from every other table)'); P(''); P('| cohort | case | budget | B0_FROZEN_V14 | H1_HYBRID (R0) | N1_CQR | G0_CQR |'); P('|---|---|---:|---|---|---|---|')
    ta = []
    for coh, cs, b in case_budgets(LEGACY_COHORTS):
        rr = dict(cohort=coh, case=cs, budget=b, B0=cell_str(by.get((coh, cs, b, 'B0_FROZEN_V14'))), H1=cell_str(by.get((coh, cs, b, 'H1_HYBRID'))), N1=cell_str(by.get((coh, cs, b, 'N1_CQR'))), G0=cell_str(by.get((coh, cs, b, 'G0_CQR')))); ta.append(rr)
        P('| %s | %s | %d | %s | %s | %s | %s |' % (coh, cs, b, rr['B0'], rr['H1'], rr['N1'], rr['G0']))
    if not ta: P('| (no legacy explicit-task cells in this manifest) | | | | | | |')
    out['table_a_legacy'] = ta; P('')
    P('## Table (b) -- New tasks: G0_CQR (general reference core) vs N1_CQR (candidate); baseline arms alongside when scheduled (all-singleton answers on the SAME .uai, ignoring the query spec)'); P(''); P('| cohort | case | budget | task (declared) | G0_CQR | N1_CQR | H1_HYBRID | B0_FROZEN_V14 |'); P('|---|---|---:|---|---|---|---|---|')
    tb = []
    for coh, cs, b in case_budgets(NEW_TASK_COHORTS):
        c0 = next((c for c in cells if c['case_id'] == cs), {}); tp = c0.get('task_params') or {}
        rr = dict(cohort=coh, case=cs, budget=b, task='%s %s%s' % (tp.get('mode'), ','.join(tp.get('query_kinds') or []) or 'all_singletons', ' normalizer' if tp.get('normalizer_task') else ''), G0=cell_str(by.get((coh, cs, b, 'G0_CQR'))), N1=cell_str(by.get((coh, cs, b, 'N1_CQR'))), H1=cell_str(by.get((coh, cs, b, 'H1_HYBRID'))), B0=cell_str(by.get((coh, cs, b, 'B0_FROZEN_V14')))); tb.append(rr)
        P('| %s | %s | %d | %s | %s | %s | %s | %s |' % (coh, cs, b, rr['task'], rr['G0'], rr['N1'], rr['H1'], rr['B0']))
    if not tb: P('| (no new-task cells in this manifest) | | | | | | | |')
    out['table_b_new_tasks'] = tb; P('')
    abl = sorted(a for a in R.CQR_ARMS if a.startswith('N1_NO_'))
    P('## Table (c) -- Ablations: N1_CQR vs the named feature ablations (same case / budget)'); P(''); P('| cohort | case | budget | N1_CQR | ' + ' | '.join(abl) + ' |'); P('|---|---|---:|---|' + '---|' * len(abl))
    tc = []
    for coh, cs, b in sorted({(x['cohort'], x['case'], x['budget']) for x in rows if x['arm'] in abl}, key=lambda t: (R.COHORTS[t[0]]['order'], t[1], t[2])):
        rr = dict(cohort=coh, case=cs, budget=b, N1=cell_str(by.get((coh, cs, b, 'N1_CQR'))), ablations={a: cell_str(by.get((coh, cs, b, a))) for a in abl}); tc.append(rr)
        P('| %s | %s | %d | %s | %s |' % (coh, cs, b, rr['N1'], ' | '.join(rr['ablations'][a] for a in abl)))
    if not tc: P('| (no ablation cells in this manifest) | | | | ' + ' | ' * (len(abl) - 1) + '|')
    out['table_c_ablations'] = tc; P('')
    P('## Table (d) -- Normalizer panel (Z with relative error; separate contract; never pooled)'); P(''); P('| cohort | case | budget | arm | outcome | guarantee | route | audit vs exact Z |'); P('|---|---|---:|---|---|---|---|---|')
    td = []
    for x in rows:
        if x.get('kind') != 'cqr_normalizer' and x['cohort'] != 'normalizer_dis': continue
        au = next((a for a in audit if a['cell_id'] == x['cell_id']), {}); rr = dict(cohort=x['cohort'], case=x['case'], budget=x['budget'], arm=x['arm'], outcome=x['outcome'], guarantee=x['guarantee'], route=x.get('route'), audit=au.get('accurate')); td.append(rr)
        P('| %s | %s | %d | %s | %s | %s | %s | %s |' % (x['cohort'], x['case'], x['budget'], x['arm'], x['outcome'], x['guarantee'], x.get('route') or '--', au.get('accurate') or '--'))
    if not td: P('| (no normalizer cells in this manifest) | | | | | | | |')
    out['table_d_normalizer'] = td; P('')
    P('## Table (e) -- Native outcomes (own contracts; counts only)'); P(''); P('| cohort | arm | budget | planned | received | PUBLISHED | DEADLINE | other |'); P('|---|---|---:|---:|---:|---:|---:|---:|')
    te = {}
    for coh in NATIVE_COHORTS:
        for arm in sorted({x['arm'] for x in rows if x['cohort'] == coh}):
            for b in man['budgets_s']:
                xs = [x for x in rows if x['cohort'] == coh and x['arm'] == arm and x['budget'] == b]
                if not xs: continue
                d = dict(planned=len(xs), received=sum(1 for x in xs if x['status'] != 'NOT_RUN'), published=sum(1 for x in xs if x['outcome'] == 'PUBLISHED'), deadline=sum(1 for x in xs if x['outcome'] == 'DEADLINE')); d['other'] = d['received'] - d['published'] - d['deadline']; te['%s|%s|%d' % (coh, arm, int(b))] = d
                P('| %s | %s | %d | %d | %d | %d | %d | %d |' % (coh, arm, b, d['planned'], d['received'], d['published'], d['deadline'], d['other']))
    if not te: P('| (no native cells in this manifest) | | | | | | | |')
    out['table_e_native'] = te; P('')
    P('## Table (f) -- Comparators (UNGUARANTEED points; accuracy vs the exact reference only; never pooled with guaranteed publications)'); P(''); P('| arm | budget | planned | published | DEADLINE | MEMORY | other | ACCURATE | INACCURATE_UNGUARANTEED | UNRESOLVED | MALFORMED |'); P('|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|')
    tf = {}
    for arm in PR.COMPARATOR_ARMS:
        for b in man['budgets_s']:
            xs = [x for x in rows if x['arm'] == arm and x['budget'] == b]
            if not xs: continue
            au = [a for a in audit if a['arm'] == arm and a['budget'] == b]
            d = dict(planned=len(xs), published=sum(1 for x in xs if x['outcome'] == 'PUBLISHED'), deadline=sum(1 for x in xs if x['outcome'] == 'DEADLINE'), memory=sum(1 for x in xs if x['outcome'] == 'MEMORY'), accurate=sum(1 for a in au if a['accurate'] == 'ACCURATE'), inaccurate=sum(1 for a in au if a['accurate'] == 'INACCURATE_UNGUARANTEED'), unresolved=sum(1 for a in au if a['accurate'].startswith('UNRESOLVED')), malformed=sum(1 for a in au if a['accurate'] == 'MALFORMED'))
            d['other'] = len(xs) - d['published'] - d['deadline'] - d['memory']; tf['%s|%d' % (arm, int(b))] = d
            P('| %s | %d | %d | %d | %d | %d | %d | %d | %d | %d | %d |' % (arm, b, d['planned'], d['published'], d['deadline'], d['memory'], d['other'], d['accurate'], d['inaccurate'], d['unresolved'], d['malformed']))
    if not tf: P('| (no comparator cells in this manifest) | | | | | | | | | | |')
    out['table_f_comparators'] = tf; P('')
    # ---- Table 4 outcome counts by arm
    P('## Table 4 -- Outcome counts by arm'); P(''); P('| arm | planned | received | ' + ' | '.join(OUTCOME_CLASSES[:-1]) + ' |'); P('|---|---:|---:|' + '---:|' * (len(OUTCOME_CLASSES) - 1))
    by_arm = {}
    for arm in sorted({x['arm'] for x in rows}, key=lambda a: (0 if a in R.CQR_ARMS else 1, a)):
        xs = [x for x in rows if x['arm'] == arm]; cnt = collections.Counter(x['outcome_class'] for x in xs)
        by_arm[arm] = dict(planned=len(xs), received=sum(1 for x in xs if x['status'] != 'NOT_RUN'), **{k: cnt.get(k, 0) for k in OUTCOME_CLASSES})
        P('| %s | %d | %d | %s |' % (arm, len(xs), by_arm[arm]['received'], ' | '.join(str(cnt.get(k, 0)) for k in OUTCOME_CLASSES[:-1])))
    out['outcome_counts_by_arm'] = by_arm; P('')
    # ---- Table 5 mechanism attribution (constructed cohort)
    P('## Table 5 -- Mechanism attribution per constructed family and regime (operators committed in the N1_CQR certificate; route; outcome; the family\'s named ablation alongside)'); P(''); P('| family | regime | case | budget | N1 committed operators | N1 route | N1 outcome | G0 outcome | named ablation | ablation outcome |'); P('|---|---|---|---:|---|---|---|---|---|---|')
    t5 = []
    for x in rows:
        if x['cohort'] != 'constructed' or x['arm'] != 'N1_CQR': continue
        ir = inv_by_case.get(x['case'], {}); fam = ir.get('family') or x['case'].split('_')[0]; reg = ir.get('regime') or ('near_miss' if 'near_miss' in x['case'] else ('favorable' if 'favorable' in x['case'] else '?'))
        abl_arm = R.ABLATION_OF_FAMILY.get(fam); g0 = by.get(('constructed', x['case'], x['budget'], 'G0_CQR')); ab = by.get(('constructed', x['case'], x['budget'], abl_arm)) if abl_arm else None
        rr = dict(family=fam, regime=reg, case=x['case'], budget=x['budget'], rep=x['rep'], committed=x.get('committed_operators'), route=x.get('route'), outcome='%s/%s' % (x['outcome'], x['guarantee']), g0=cell_str(g0), ablation=abl_arm, ablation_outcome=cell_str(ab), mechanism=ir.get('mechanism')); t5.append(rr)
        P('| %s | %s | %s | %d | %s | %s | %s | %s | %s | %s |' % (fam, reg, x['case'], x['budget'], ','.join(x.get('committed_operators') or []) or '--', x.get('route') or '--', rr['outcome'], rr['g0'], abl_arm or '--', rr['ablation_outcome']))
    if not t5: P('| (no constructed N1_CQR cells in this manifest) | | | | | | | | | |')
    out['mechanism_attribution'] = t5; P('')
    # ---- Table 6 ledger + gate binding
    lp = os.path.join(RD, LEDGER); by_scope = collections.defaultdict(float); nrec = collections.Counter()
    if os.path.exists(lp):
        for line in open(lp):
            try: rr = json.loads(line)
            except Exception: continue
            if rr.get('kind') == 'RECEIPT' and isinstance(rr.get('wall_s'), (int, float)): by_scope[rr.get('scope')] += rr['wall_s']; nrec[rr.get('scope')] += 1
    over1 = sum(1 for x in rows if isinstance(x.get('wall'), (int, float)) and x['wall'] > x['budget'] + 1.0); over5 = sum(1 for x in rows if isinstance(x.get('wall'), (int, float)) and x['wall'] > x['budget'] + 5.0)
    P('## Table 6 -- Resource ledger (%s; receipted wall by scope) and gate binding' % LEDGER); P(''); P('| scope | receipts | seconds |'); P('|---|---:|---:|')
    for k, v in sorted(by_scope.items()): P('| %s | %d | %.1f |' % (k, nrec[k], v))
    P('| **total (this ledger)** | %d | **%.1f** |' % (sum(nrec.values()), sum(by_scope.values()))); P('')
    P('Receipts with wall > budget + 1 s: %d; > budget + 5 s: %d. Prospective ceiling (manifest): scored matrix %.0f s nominal, verification %.0f s, orchestration %.0f s, total %.0f s.' % (over1, over5, man['ceiling']['scored_matrix_seconds'], man['ceiling']['verification_stage_seconds'], man['ceiling']['orchestration_seconds'], man['ceiling']['total_ceiling_seconds'])); P('')
    P('### gate_binding'); P('')
    if gb: P('Gate: %s; gate_passed %s; failures %d; gated_set_sha256 `%s`; manifest bound %s; counters %s; mismatches with the receipts / outputs / dependencies on disk: %s.' % (gb.get('gate_version'), gb.get('gate_passed'), gb.get('failures') or 0, gb.get('gated_set_sha256'), gb.get('manifest_sha256') == out['manifest_sha256'], json.dumps(gb.get('counters')), gb.get('mismatch') or 'none'))
    else: P('No GATE_RESULT.json in the run directory: this report is UNGATED (diagnostic only).')
    P('')
    out['ledger'] = dict(by_scope=dict(by_scope), receipts=dict(nrec), total=sum(by_scope.values()), receipts_over_budget_plus_1=over1, receipts_over_budget_plus_5=over5, ceiling=man['ceiling'])
    out['summary'] = dict(cells=len(cells), receipts=len(rec), unrun=len(unrun), outcome_counts_by_arm=by_arm, audit_counts={'%s|%s' % k: v for k, v in sorted(acat.items())}, gated_set_sha256=out['gated_set_sha256'], confirmed_inaccurate=[a['cell_id'] for a in audit if a.get('accurate') == 'CONFIRMED_INACCURATE'], references=len(refs), references_rejected=len(ref_rejected))
    out['summary_sha256'] = hashlib.sha256(json.dumps(out['summary'], sort_keys=True, default=str).encode()).hexdigest()
    P('Summary digest `%s` (cells %d, receipts %d, unrun %d, CONFIRMED_INACCURATE %d).' % (out['summary_sha256'], len(cells), len(rec), len(unrun), len(out['summary']['confirmed_inaccurate'])))
    if write:
        json.dump(out, open(os.path.join(out_dir, 'RESULTS_CQR.json'), 'w'), indent=1, default=str); open(os.path.join(out_dir, 'RESULTS_CQR.md'), 'w').write('\n'.join(L) + '\n')
        print('written', len(L), 'lines;', len(rows), 'runs;', len(unrun), 'unrun; audit', dict(collections.Counter(a['accurate'] for a in audit)))
    out['_markdown'] = L
    return out


if __name__ == '__main__':
    mn = sys.argv[sys.argv.index('--manifest') + 1] if '--manifest' in sys.argv else 'CAMPAIGN_MANIFEST.json'; gp_ = sys.argv[sys.argv.index('--gate') + 1] if '--gate' in sys.argv else None; od_ = sys.argv[sys.argv.index('--out-dir') + 1] if '--out-dir' in sys.argv else None
    main(sys.argv[1], mn, gate_path=gp_, out_dir=od_)
