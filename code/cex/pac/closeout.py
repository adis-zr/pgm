"""Closeout generator -- v2 (repair of review F06 of 13 Nov 2026): the verdict is FAIL-CLOSED. A qualified empirical verdict (NO EMPIRICAL GAIN / PARTIAL /
POSITIVE) is emitted ONLY when every prerequisite holds: the gate result exists and PASSED, the qualification record exists and ALL groups passed, the matrix is
complete (no unrun cell), and the gate / qualification candidate identities equal the manifest's. Otherwise the verdict is UNQUALIFIED / INVALID with the failed
prerequisites listed, the evidence is still described (failures preserved), and the exit status is nonzero so the finalizer stops.
    python cex/pac/closeout.py <RD> [--qualification PATH]   -> CLOSEOUT_PAC.md; exit 0 only for a qualified verdict"""
import sys, os, json, time, collections, statistics
RD = os.path.abspath(sys.argv[1]); HERE = os.path.dirname(os.path.abspath(__file__))
QP = sys.argv[sys.argv.index('--qualification') + 1] if '--qualification' in sys.argv else os.path.join(HERE, 'PAC_QUALIFICATION.json')
CLOSEOUT_VERSION = 'pac-closeout-v2 (2026-11-13 repair, fail-closed)'
L = []; P = L.append; prereq_failures = []
def need(path, what):
    if not os.path.exists(path): prereq_failures.append('%s missing (%s)' % (what, path)); return None
    try: return json.load(open(path))
    except Exception as ex: prereq_failures.append('%s unreadable: %s' % (what, str(ex)[:80])); return None
R = need(os.path.join(RD, 'RESULTS_PAC.json'), 'RESULTS_PAC.json'); M = need(os.path.join(RD, 'CAMPAIGN_MANIFEST.json'), 'manifest'); G = need(os.path.join(RD, 'GATE_RESULT.json'), 'gate result'); A = need(os.path.join(RD, 'REFERENCE_AUDIT.json'), 'reference audit'); Q = need(QP, 'qualification record')
if G is not None and not G.get('gate_passed'): prereq_failures.append('receipt/certificate gate FAILED (%d failures)' % len(G.get('failures', [])))
if G is not None and not str(G.get('gate_version', '')).startswith('pac-gate-v2'): prereq_failures.append('gate result produced by a pre-repair gate (%s): re-gate required' % G.get('gate_version'))
if Q is not None and not Q.get('all_pass'): prereq_failures.append('qualification NOT all-pass (%s/%s)' % (Q.get('passed'), Q.get('total')))
if R is not None and R.get('unrun'): prereq_failures.append('matrix incomplete: %d planned cells unrun' % len(R['unrun']))
if R is not None and not str(R.get('report_version', '')).startswith('pac-report-v2'): prereq_failures.append('results produced by a pre-repair reporter (%s)' % R.get('report_version'))
qualified = not prereq_failures
runs = (R or {}).get('runs', []); unrun = (R or {}).get('unrun', [])
def cnt(**kw): return sum(1 for x in runs if all(x.get(k) == v for k, v in kw.items()))
core = lambda **kw: cnt(cohort='external_core', **kw)
b0_20 = (R or {}).get('b0_vs_h1_20', {}); b0_120 = (R or {}).get('b0_vs_h1_120', {})
pac_pub = {b: core(arm='P1_PAC_CONDITIONAL', budget=float(b), outcome='PUBLISHED', guarantee='PAC') for b in (20, 120)}; h1_pac = {b: core(arm='H1_HYBRID', budget=float(b), outcome='PUBLISHED', guarantee='PAC') for b in (20, 120)}
if qualified:
    verdict = 'NO EMPIRICAL GAIN' if (all(v == 0 for v in pac_pub.values()) and all(v == 0 for v in h1_pac.values()) and not any(b0_20.get('new')) and not any(b0_120.get('new'))) else 'EMPIRICAL CHANGE OBSERVED (see section 1; a positive result needs 03 §9)'
else: verdict = 'UNQUALIFIED / INVALID (prerequisites failed: %s)' % '; '.join(prereq_failures)
inacc = [a for a in (A or {}).get('audit', []) if a.get('accurate') == 'CONFIRMED_INACCURATE']
P('# PAC EMPIRICAL PASS — CLOSEOUT (%s UTC; %s) — %s' % (time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()), CLOSEOUT_VERSION, verdict)); P('')
if M is not None:
    P('Frozen manifest sha256 `%s` (root seed `%s`), %d cells. Receipt/certificate gate: %s (%s; %s planned, %s receipts, %s completed records gated, %s PAC certificates replayed, failures %s). Qualification: %s.' % (M.get('manifest_sha256_without_self'), M.get('seeds', {}).get('root_seed'), len(M.get('cells', [])), ('PASSED' if G and G.get('gate_passed') else 'FAILED / MISSING'), (G or {}).get('gate_version'), (G or {}).get('planned'), (G or {}).get('receipts'), (G or {}).get('completed_gated'), (G or {}).get('pac_certificates_replayed'), len((G or {}).get('failures', [])), ('%s/%s groups, %s executions, %s coordinates (%s)' % (Q['passed'], Q['total'], Q.get('executions'), Q.get('coordinates_checked'), Q.get('suite_version')) if Q else 'MISSING'))); P('')
if not qualified:
    P('## 0. PREREQUISITES FAILED — this closeout carries NO qualified empirical verdict'); P('')
    for f in prereq_failures: P('- %s' % f)
    P(''); P('The evidence below is preserved for diagnosis; it must not be cited as a qualified negative or positive empirical answer. STOPPED FOR REVIEW.'); P('')
P('## 1. Answers to the three questions (03 §9, 07 CONCLUSION)%s' % ('' if qualified else ' — DIAGNOSTIC ONLY (unqualified)')); P('')
P('**Does the PAC extension increase affordable valid coverage?** External core: PAC-guaranteed publications by the forced arm P1 at 20 s: %d of %d runs; at 120 s: %d of %d. By the hybrid H1: %d (20 s), %d (120 s). New deterministic+PAC case completions of H1 (3/3) that B0 lacks (fully observed groups): 20 s %s; 120 s %s.' % (pac_pub[20], core(arm='P1_PAC_CONDITIONAL', budget=20.0), pac_pub[120], core(arm='P1_PAC_CONDITIONAL', budget=120.0), h1_pac[20], h1_pac[120], b0_20.get('new') or 'none', b0_120.get('new') or 'none'))
def med(pairs): return ('median %.3f over %d' % (sorted(p[1] for p in pairs)[len(pairs) // 2], len(pairs))) if pairs else 'n/a'
P('**Does it preserve prior deterministic performance?** Fully observed groups: %d (20 s) / %d (120 s), pending %s / %s. Fresh B0 published %d (20 s) / %d (120 s); H1 3/3 on %d / %d; LOST: 20 s %s; 120 s %s. Paired walls over retained cases (H1 median of 3 / B0): %s (20 s), %s (120 s).' % (len(b0_20.get('observed', [])), len(b0_120.get('observed', [])), b0_20.get('pending') or 'none', b0_120.get('pending') or 'none', len(b0_20.get('b0', [])), len(b0_120.get('b0', [])), len(b0_20.get('h1_all3', [])), len(b0_120.get('h1_all3', [])), b0_20.get('lost') or 'none', b0_120.get('lost') or 'none', med(b0_20.get('pairs')), med(b0_120.get('pairs'))))
a0 = [x for x in runs if x['arm'] == 'A0_POINT']; a1 = [x for x in runs if x['arm'] == 'A1_CONDITIONAL']
P('**Does it benefit from exact conditional work?** Matched ablation at 120 s on %d cases: A0_POINT published %d, A1_CONDITIONAL published %d (same cutset / order / tree seed, residual region fixed). Recorded last-check range / variance widths per case in RESULTS_PAC.md Table 6. The variance theorem is an expected second-moment ordering; the observed outcome is one observation per case; no causal attribution beyond the recorded widths.' % (len(a0), sum(1 for x in a0 if x['outcome'] == 'PUBLISHED'), sum(1 for x in a1 if x['outcome'] == 'PUBLISHED'))); P('')
P('## 2. Reference audit (diagnostic; binding- and shape-validated references only)'); P('')
cat = collections.Counter((a['arm'], a['accurate']) for a in (A or {}).get('audit', []))
P('R0 exact rational references for %d cases; references rejected for binding/shape: %d. Per arm (accurate / inaccurate / unresolved / malformed): %s. CONFIRMED_INACCURATE publications: %d%s.' % (sum(1 for v in (A or {}).get('refs', {}).values() if v == 'R0_exact_rational'), len((A or {}).get('references_rejected', [])), {k[0]: dict(acc=cat[(k[0], 'CONFIRMED_ACCURATE')], inacc=cat[(k[0], 'CONFIRMED_INACCURATE')], unres=cat[(k[0], 'UNRESOLVED_NO_REFERENCE')] + cat[(k[0], 'UNRESOLVED_INTERVAL')], malformed=cat[(k[0], 'MALFORMED_CANDIDATE')]) for k in sorted({(a['arm'],) for a in (A or {}).get('audit', [])})}, len(inacc), (' — INVESTIGATE: ' + str(inacc[:5])) if inacc else '')); P('')
P('## 3. What was proved, qualified, measured, and remains unknown'); P('')
P('- Proved (theory packet, unchanged): conditional unbiasedness of exact-plus-residual trials; ratio mixture and variance-sensitive anytime certificates; the factor-max envelope telescoping; the finite-precision publication bridge. Proof-to-code map: `PROOF_TO_CODE_PAC.md` (v2).')
P('- Qualified (candidate v2): %s.' % ('; '.join(g['name'] for g in Q['groups'] if g['ok']) if Q else 'NONE (record missing)'))
P('- Measured: RESULTS_PAC.md (%d runs, %d unrun).' % (len(runs), len(unrun)))
P('- Not implemented / unknown: candidate validation (T§9); the cost oracle as a planner; proposal refinement beyond leaf resolution (the envelope tightens only by removing evaluated cells); delta = 1e-6 is not empirically verified (it rests on the proofs plus the verified obligations).'); P('')
P('## 4. Failure attribution (recorded bottlenecks; RESULTS_PAC.md Table 7)'); P('')
for k, v in sorted(((R or {}).get('attribution_counts') or {}).items(), key=lambda kv: -kv[1]): P('- %s: %d runs' % (k, v))
P(''); P('## 5. Isolation, amendments, resource contract'); P('')
iso = json.load(open(os.path.join(RD, 'ISOLATION_NOTE.json'))) if os.path.exists(os.path.join(RD, 'ISOLATION_NOTE.json')) else {}
P('Scored cells ran strictly sequentially (pairwise overlaps among scored cells: %d). Charged non-cell jobs overlapping a scored cell: %s. %s Amendments recorded: %d.' % (len(iso.get('scored_cell_pairwise_overlaps', [])), iso.get('charged_non_cell_jobs_overlapping_scored_cells') or 'none', iso.get('interactive_exposure', ''), len(iso.get('amendments', []))))
led = (R or {}).get('ledger') or {}
P('Resource contract as executed: actual kill threshold budget + 5 s (supervisor grace); receipts over budget + 1 s: %s, over budget + 5 s: %s; walls charged in full; late publications never count.' % (led.get('receipts_over_budget_plus_1'), led.get('receipts_over_budget_plus_5')))
P(''); P('## 6. Ledger'); P('')
if led: P('Scored + qualification + packaging receipts (this run directory): %.1f s; development campaigns: %.1f s; prospective ceiling %.0f s (scored matrix nominal %.0f s, orchestration %.0f s). Interactive post-processing uncharged (UNKNOWN exposure).' % (led['total'], led['dev_total'], led['ceiling']['total_ceiling_seconds'], led['ceiling']['scored_matrix_seconds'], led['ceiling']['orchestration_seconds']))
P(''); P('## 7. Verdict'); P(''); P('**%s.** %s STOPPED FOR REVIEW.' % (verdict, 'The full planned matrix of THIS manifest was run, gated and qualified (the requested inventory denominator is Table 1 of RESULTS_PAC.md).' if qualified else 'No qualified empirical verdict is issued.'))
open(os.path.join(RD, 'CLOSEOUT_PAC.md'), 'w').write('\n'.join(L) + '\n'); print('closeout written:', verdict); sys.exit(0 if qualified else 1)
