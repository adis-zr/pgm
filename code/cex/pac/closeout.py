"""Closeout generator -- v3 (fail-closed with IDENTITY binding; review R06): a qualified empirical verdict is emitted ONLY when every prerequisite holds AND the
artifacts belong to THIS candidate and THIS manifest:
  * GATE_RESULT: gate_version v3, gate_passed, manifest_sha256 == sha256 of the manifest file on disk, planned == number of manifest cells == receipts,
    completed_gated + non-completed receipts == planned (recomputed from the receipts on disk);
  * qualification record: suite v3, all groups ok, passed == total == len(groups), its recorded candidate identity (pac/*, newarm/*) EQUALS the manifest's frozen
    candidate hashes AND the current files on disk (no stale pass from another revision);
  * RESULTS_PAC: report v3, every planned cell has one run row, the unrun list recomputed from the receipts is empty;
  * CAMPAIGN_START binds the manifest; no unbound artifact amendment exists.
Otherwise the verdict is UNQUALIFIED / INVALID with every failed prerequisite listed; evidence is still described; exit status 1.
    python cex/pac/closeout.py <RD> [--qualification PATH]"""
import sys, os, json, time, collections, hashlib, glob
RD = os.path.abspath(sys.argv[1]); HERE = os.path.dirname(os.path.abspath(__file__)); CODE = os.path.dirname(os.path.dirname(HERE))
QP = sys.argv[sys.argv.index('--qualification') + 1] if '--qualification' in sys.argv else os.path.join(HERE, 'PAC_QUALIFICATION.json')
CLOSEOUT_VERSION = 'pac-closeout-v3 (2026-11-13 completion; fail-closed with identity binding)'
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
mpath = os.path.join(RD, 'CAMPAIGN_MANIFEST.json')
R = need(os.path.join(RD, 'RESULTS_PAC.json'), 'RESULTS_PAC.json'); M = need(mpath, 'manifest'); G = need(os.path.join(RD, 'GATE_RESULT.json'), 'gate result'); A = need(os.path.join(RD, 'REFERENCE_AUDIT.json'), 'reference audit'); Q = need(QP, 'qualification record'); ST = need(os.path.join(RD, 'CAMPAIGN_START.json'), 'CAMPAIGN_START')
mh = sha(mpath) if os.path.exists(mpath) else None
cells = (M or {}).get('cells') or []; ncells = len(cells)
# ---- receipts recomputed from disk
receipts = {}
for rp in glob.glob(os.path.join(RD, 'cells', '*', 'receipt.json')):
    try: r = json.load(open(rp)); receipts.setdefault(r.get('cell_id'), []).append(r)
    except Exception: prereq.append('unreadable receipt %s' % rp)
dups = [k for k, v in receipts.items() if len(v) > 1]
unrun_disk = [c['cell_id'] for c in cells if c['cell_id'] not in receipts]; extra_disk = [k for k in receipts if k not in {c['cell_id'] for c in cells}]
completed_disk = sum(1 for k, v in receipts.items() if v[0].get('status') == 'COMPLETED')
if dups: prereq.append('duplicate receipts on disk: %d' % len(dups))
if unrun_disk: prereq.append('matrix incomplete: %d planned cells have no receipt on disk' % len(unrun_disk))
if extra_disk: prereq.append('%d receipts for cells not in the manifest' % len(extra_disk))
# ---- START + amendments
if ST is not None:
    if ST.get('manifest_sha256') != mh: prereq.append('CAMPAIGN_START manifest sha256 differs from the manifest on disk')
    present = sorted(os.path.basename(x) for x in glob.glob(os.path.join(RD, 'MANIFEST_AMENDMENT_*artifact_hashes.json')))
    if present != sorted(ST.get('bound_amendments') or []): prereq.append('artifact amendments on disk %s differ from those bound at START %s' % (present, ST.get('bound_amendments')))
# ---- gate identity + counts
if G is not None:
    if not str(G.get('gate_version', '')).startswith('pac-gate-v3'): prereq.append('gate result produced by a pre-completion gate (%s): re-gate required' % G.get('gate_version'))
    if not G.get('gate_passed'): prereq.append('receipt/certificate gate FAILED (%d failures)' % len(G.get('failures', [])))
    if G.get('manifest_sha256') != mh: prereq.append('gate result belongs to a different manifest (%s vs %s)' % (str(G.get('manifest_sha256'))[:16], str(mh)[:16]))
    if G.get('planned') != ncells or G.get('receipts') != ncells or G.get('receipts') != len(receipts): prereq.append('gate counts (planned %s, receipts %s) differ from the manifest (%d cells) / disk (%d receipts)' % (G.get('planned'), G.get('receipts'), ncells, len(receipts)))
    if G.get('completed_gated') != completed_disk: prereq.append('gate completed_gated %s differs from COMPLETED receipts on disk %d' % (G.get('completed_gated'), completed_disk))
# ---- qualification identity
frozen = (M or {}).get('candidate_artifact_hashes') or {}
if Q is not None:
    groups = Q.get('groups') or []
    if not str(Q.get('suite_version', '')).startswith('pac-qualification-v3'): prereq.append('qualification record from a pre-completion suite (%s)' % Q.get('suite_version'))
    if not Q.get('all_pass') or Q.get('passed') != Q.get('total') or Q.get('total') != len(groups) or not groups or not all(g.get('ok') for g in groups): prereq.append('qualification groups not all passed (passed %s / total %s / groups %d / ok %d)' % (Q.get('passed'), Q.get('total'), len(groups), sum(1 for g in groups if g.get('ok'))))
    qs = Q.get('candidate_sources') or {}
    want = {k: v for k, v in frozen.items() if k.split('/', 1)[0] in ('pac', 'newarm')}
    if not want: prereq.append('manifest carries no frozen candidate identity (pac/*, newarm/*)')
    miss = [k for k in want if k not in qs]; diff = [k for k in want if k in qs and qs[k] != want[k]]
    if miss or diff: prereq.append('qualification record identity does not match the frozen candidate (%d missing, %d differing; e.g. %s)' % (len(miss), len(diff), (miss + diff)[:1]))
    for k, v in want.items():
        p = os.path.join(CODE, 'cex', k)
        if not os.path.exists(p) or sha(p) != v: prereq.append('frozen candidate source %s differs from the file on disk' % k); break
# ---- results identity
runs = (R or {}).get('runs', []); unrun = (R or {}).get('unrun', [])
if R is not None:
    if not str(R.get('report_version', '')).startswith('pac-report-v3'): prereq.append('results produced by a pre-completion reporter (%s)' % R.get('report_version'))
    if len(runs) != ncells: prereq.append('results rows %d differ from the manifest cells %d' % (len(runs), ncells))
    if unrun or unrun_disk: prereq.append('results report %d unrun / disk %d unrun' % (len(unrun), len(unrun_disk)))
    if R.get('manifest_sha256') not in (None, mh): prereq.append('results belong to a different manifest')
qualified = not prereq
def cnt(**kw): return sum(1 for x in runs if all(x.get(k) == v for k, v in kw.items()))
core_ = lambda **kw: cnt(cohort='external_core', **kw)
b0_20 = (R or {}).get('b0_vs_h1_20', {}); b0_120 = (R or {}).get('b0_vs_h1_120', {})
pac_pub = {b: core_(arm='P1_PAC_CONDITIONAL', budget=float(b), outcome='PUBLISHED', guarantee='PAC') for b in (20, 120)}; h1_pac = {b: core_(arm='H1_HYBRID', budget=float(b), outcome='PUBLISHED', guarantee='PAC') for b in (20, 120)}
if qualified:
    verdict = 'NO EMPIRICAL GAIN' if (all(v == 0 for v in pac_pub.values()) and all(v == 0 for v in h1_pac.values()) and not (b0_20.get('new') or []) and not (b0_120.get('new') or [])) else 'EMPIRICAL CHANGE OBSERVED (see section 1; a positive result needs 03 §9)'
else: verdict = 'UNQUALIFIED / INVALID (prerequisites failed: %s)' % '; '.join(prereq)
inacc = [a for a in (A or {}).get('audit', []) if a.get('accurate') == 'CONFIRMED_INACCURATE']
P('# PAC EMPIRICAL PASS — CLOSEOUT (%s UTC; %s) — %s' % (time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()), CLOSEOUT_VERSION, verdict)); P('')
if M is not None:
    P('Frozen manifest file sha256 `%s` (manifest_sha256_without_self `%s`, root seed `%s`), %d cells; receipts on disk %d (COMPLETED %d). Gate: %s (%s; planned %s, receipts %s, gated %s, PAC certificates replayed %s, failures %s). Qualification: %s.' % (mh, M.get('manifest_sha256_without_self'), (M.get('seeds') or {}).get('root_seed'), ncells, len(receipts), completed_disk, ('PASSED' if G and G.get('gate_passed') else 'FAILED / MISSING'), (G or {}).get('gate_version'), (G or {}).get('planned'), (G or {}).get('receipts'), (G or {}).get('completed_gated'), (G or {}).get('pac_certificates_replayed'), len((G or {}).get('failures', [])), ('%s/%s groups (%s), %s end-to-end executions, %s helper evaluations, %s coordinates' % (Q.get('passed'), Q.get('total'), Q.get('suite_version'), Q.get('executions'), Q.get('helper_evaluations'), Q.get('coordinates_checked')) if Q else 'MISSING'))); P('')
if not qualified:
    P('## 0. PREREQUISITES FAILED — this closeout carries NO qualified empirical verdict'); P('')
    for f in prereq: P('- %s' % f)
    P(''); P('The evidence below is preserved for diagnosis; it must not be cited as a qualified negative or positive empirical answer. STOPPED FOR REVIEW.'); P('')
P('## 1. Answers to the three questions (03 §9, 07 CONCLUSION)%s' % ('' if qualified else ' — DIAGNOSTIC ONLY (unqualified)')); P('')
P('**Does the PAC extension increase affordable valid coverage?** External core: PAC-guaranteed publications by the forced arm P1 at 20 s: %d of %d runs; at 120 s: %d of %d. By the hybrid H1: %d (20 s), %d (120 s). New deterministic+PAC case completions of H1 (3/3) that B0 lacks (fully observed groups): 20 s %s; 120 s %s.' % (pac_pub[20], core_(arm='P1_PAC_CONDITIONAL', budget=20.0), pac_pub[120], core_(arm='P1_PAC_CONDITIONAL', budget=120.0), h1_pac[20], h1_pac[120], b0_20.get('new') or 'none', b0_120.get('new') or 'none'))
def med(pairs): return ('median %.3f over %d' % (sorted(p[1] for p in pairs)[len(pairs) // 2], len(pairs))) if pairs else 'n/a'
P('**Does it preserve prior deterministic performance?** Fully observed groups: %d (20 s) / %d (120 s), pending %s / %s. Fresh B0 published %d (20 s) / %d (120 s); H1 3/3 on %d / %d; LOST: 20 s %s; 120 s %s. Paired walls over retained cases (H1 median of 3 / B0): %s (20 s), %s (120 s).' % (len(b0_20.get('observed', [])), len(b0_120.get('observed', [])), b0_20.get('pending') or 'none', b0_120.get('pending') or 'none', len(b0_20.get('b0', [])), len(b0_120.get('b0', [])), len(b0_20.get('h1_all3', [])), len(b0_120.get('h1_all3', [])), b0_20.get('lost') or 'none', b0_120.get('lost') or 'none', med(b0_20.get('pairs')), med(b0_120.get('pairs'))))
a0 = [x for x in runs if x['arm'] == 'A0_POINT']; a1 = [x for x in runs if x['arm'] == 'A1_CONDITIONAL']
P('**Does it benefit from exact conditional work?** Matched ablation at 120 s on %d cases: A0_POINT published %d, A1_CONDITIONAL published %d (same cutset / order / tree seed, residual region fixed). Recorded last-check widths per case in RESULTS_PAC.md Table 6; one observation per case; no causal attribution beyond the recorded widths.' % (len(a0), sum(1 for x in a0 if x['outcome'] == 'PUBLISHED'), sum(1 for x in a1 if x['outcome'] == 'PUBLISHED'))); P('')
P('## 2. Reference audit (diagnostic; binding- and shape-validated references only)'); P('')
cat = collections.Counter((a['arm'], a['accurate']) for a in (A or {}).get('audit', []))
P('R0 exact rational references for %d cases; references rejected for binding/shape: %d. Per arm (accurate / inaccurate / unresolved / malformed): %s. CONFIRMED_INACCURATE publications: %d%s.' % (sum(1 for v in (A or {}).get('refs', {}).values() if v == 'R0_exact_rational'), len((A or {}).get('references_rejected', [])), {k[0]: dict(acc=cat[(k[0], 'CONFIRMED_ACCURATE')], inacc=cat[(k[0], 'CONFIRMED_INACCURATE')], unres=cat[(k[0], 'UNRESOLVED_NO_REFERENCE')] + cat[(k[0], 'UNRESOLVED_INTERVAL')], malformed=cat[(k[0], 'MALFORMED_CANDIDATE')]) for k in sorted({(a['arm'],) for a in (A or {}).get('audit', [])})}, len(inacc), (' — INVESTIGATE: ' + str(inacc[:5])) if inacc else '')); P('')
P('## 3. What was proved, qualified, measured, and remains unknown'); P('')
P('- Proved (theory packet, unchanged): conditional unbiasedness of exact-plus-residual trials; ratio mixture and variance-sensitive anytime certificates; the factor-max envelope telescoping (now over the explicit frontier); the finite-precision publication bridge. Proof-to-code map: `PROOF_TO_CODE_PAC_v3.md`.')
P('- Qualified: %s.' % ('; '.join(g['name'] for g in Q['groups'] if g['ok']) if Q else 'NONE (record missing)'))
P('- Measured: RESULTS_PAC.md (%d runs, %d unrun).' % (len(runs), len(unrun)))
P('- Not implemented / unknown (optional in the handoff): candidate validation (T§9); the cost oracle as a planner; proposal refinement beyond child-sum propagation and leaf resolution; re-weighting later trials by the smaller U_t; delta = 1e-6 is not empirically verified.'); P('')
P('## 4. Failure attribution (recorded bottlenecks; RESULTS_PAC.md Table 7)'); P('')
for k, v in sorted(((R or {}).get('attribution_counts') or {}).items(), key=lambda kv: -kv[1]): P('- %s: %d runs' % (k, v))
P(''); P('## 5. Isolation, amendments, resource contract'); P('')
iso = json.load(open(os.path.join(RD, 'ISOLATION_NOTE.json'))) if os.path.exists(os.path.join(RD, 'ISOLATION_NOTE.json')) else {}
P('Scored cells ran strictly sequentially (pairwise overlaps among scored cells: %d). Charged non-cell jobs overlapping a scored cell: %s. %s Amendments bound at START: %s.' % (len(iso.get('scored_cell_pairwise_overlaps', [])), iso.get('charged_non_cell_jobs_overlapping_scored_cells') or 'none', iso.get('interactive_exposure', ''), (ST or {}).get('bound_amendments')))
led = (R or {}).get('ledger') or {}
P('Resource contract as executed: actual kill threshold budget + 5 s (supervisor grace); receipts over budget + 1 s: %s, over budget + 5 s: %s; walls charged in full; late publications never count.' % (led.get('receipts_over_budget_plus_1'), led.get('receipts_over_budget_plus_5')))
P(''); P('## 6. Ledger'); P('')
if led: P('Scored + qualification + packaging receipts (this run directory): %.1f s; development campaigns: %.1f s; prospective ceiling %.0f s (scored matrix nominal %.0f s, orchestration %.0f s). Interactive post-processing uncharged (UNKNOWN exposure).' % (led['total'], led['dev_total'], led['ceiling']['total_ceiling_seconds'], led['ceiling']['scored_matrix_seconds'], led['ceiling']['orchestration_seconds']))
P(''); P('## 7. Verdict'); P(''); P('**%s.** %s STOPPED FOR REVIEW.' % (verdict, 'The full planned matrix of THIS manifest was run, gated and qualified by artifacts bound to this exact candidate and manifest (the requested inventory denominator is Table 1 of RESULTS_PAC.md).' if qualified else 'No qualified empirical verdict is issued.'))
open(os.path.join(RD, 'CLOSEOUT_PAC.md'), 'w').write('\n'.join(L) + '\n'); print('closeout written:', verdict); sys.exit(0 if qualified else 1)
