"""CQR CLOSEOUT -- fail-closed. A 'DEVELOPMENT ADMISSION QUALIFIED' verdict is printed ONLY when every prerequisite holds; otherwise every failed prerequisite is listed and the
exit status is 1. Prerequisites: manifest + GATE_RESULT.json + RESULTS_CQR.json present; gate_passed with an EMPTY failure list; the LATEST ledger receipt with scope
'cqr_finalize_gate' is COMPLETED rc 0; the report binds the latest gate (RESULTS_CQR.json gated_set_sha256 == GATE_RESULT.json gated_set_sha256) and is not older than it;
CAMPAIGN_START binds the manifest and the frozen inventory content hash; no amendment file; the frozen inventory equals the files on disk; the qualification record:
suite_version startswith 'cqr-qualification', groups == registry.QUALIFICATION_GROUPS exactly (each once, no extra), all ok, passed == total == len(groups), all_pass,
candidate_sources == the frozen cqr scope of the manifest (zero missing / differing / extra); the report is RE-DERIVED from the current raw records (report.main(write=False))
and its summary (run rows, outcome counts, audit classes, digest) must equal RESULTS_CQR.json; any CONFIRMED_INACCURATE (a deterministic publication / zero claim contradicting
an exact reference) => INVESTIGATE (exit 1; never a verdict). Writes CLOSEOUT_CQR.md with the verdict and the counts by arm.
    python cex/cqr/closeout.py <RD> [--manifest NAME] [--qualification PATH (default cex/cqr/CQR_QUALIFICATION.json)] [--out PATH]"""
import sys, os, json, time, hashlib, glob, collections, contextlib, io, importlib.util
HERE = os.path.dirname(os.path.abspath(__file__)); CEX = os.path.dirname(HERE); CODE = os.path.dirname(CEX); PAC = os.path.join(CEX, 'pac'); NEWARM = os.path.join(CEX, 'newarm')
for _p in (CODE, NEWARM, PAC):
    if _p in sys.path: sys.path.remove(_p)
    sys.path.insert(0, _p)
sys.set_int_max_str_digits(0)
import registry as PR
if HERE in sys.path: sys.path.remove(HERE)
sys.path.insert(0, HERE)


def load_module(name, path):
    if name in sys.modules: return sys.modules[name]
    spec = importlib.util.spec_from_file_location(name, path); m = importlib.util.module_from_spec(spec); sys.modules[name] = m; spec.loader.exec_module(m); return m


R = load_module('cqr_registry', os.path.join(HERE, 'registry.py'))
KI = load_module('cqr_kernel_identity', os.path.join(HERE, 'kernel_identity.py'))
RP = load_module('cqr_report', os.path.join(HERE, 'report.py'))
CLOSEOUT_VERSION = 'cqr-closeout-v1.1 (2026-11-16; complete semantic attribution compared in the published JSON domain)'
LEDGER = 'CQR_LEDGER.jsonl'


def sha(p):
    h = hashlib.sha256()
    with open(p, 'rb') as f:
        for b in iter(lambda: f.read(1 << 20), b''): h.update(b)
    return h.hexdigest()


def main(RD, MN='CAMPAIGN_MANIFEST.json', QP=None, OUTP=None):
    RD = os.path.abspath(RD); QP = QP or os.path.join(HERE, 'CQR_QUALIFICATION.json'); OUTP = OUTP or os.path.join(RD, 'CLOSEOUT_CQR.md'); prereq = []; L = []; P = L.append
    def need(path, what):
        if not os.path.exists(path): prereq.append('%s missing (%s)' % (what, path)); return None
        try: return json.load(open(path))
        except Exception as ex: prereq.append('%s unreadable: %s' % (what, str(ex)[:80])); return None
    mpath = os.path.join(RD, MN); M = need(mpath, 'manifest'); G = need(os.path.join(RD, 'GATE_RESULT.json'), 'gate result'); RES = need(os.path.join(RD, 'RESULTS_CQR.json'), 'RESULTS_CQR.json'); Q = need(QP, 'qualification record'); ST = need(os.path.join(RD, 'CAMPAIGN_START.json'), 'CAMPAIGN_START')
    mh = sha(mpath) if os.path.exists(mpath) else None; cells = (M or {}).get('cells') or []; frozen = (M or {}).get('candidate_artifact_hashes') or {}; ah = hashlib.sha256(json.dumps(frozen, sort_keys=True).encode()).hexdigest() if frozen else None
    if M is not None and M.get('schema') != 'cqr_campaign_manifest_v1': prereq.append('manifest schema %s is not cqr_campaign_manifest_v1' % M.get('schema'))
    receipts = {}
    for rp in glob.glob(os.path.join(RD, 'cells', '*', 'receipt.json')):
        try: r = json.load(open(rp)); receipts.setdefault(r.get('cell_id'), []).append(r)
        except Exception: prereq.append('unreadable receipt %s' % rp)
    dups = [k for k, v in receipts.items() if len(v) > 1]; unrun = [c['cell_id'] for c in cells if c['cell_id'] not in receipts]; extra = [k for k in receipts if k not in {c['cell_id'] for c in cells}]
    if dups: prereq.append('duplicate receipts on disk: %d' % len(dups))
    if unrun: prereq.append('matrix incomplete: %d planned cells have no receipt on disk' % len(unrun))
    if extra: prereq.append('%d receipts for cells not in the manifest' % len(extra))
    # ---- START + frozen identity
    if ST is not None:
        if ST.get('manifest_sha256') != mh: prereq.append('CAMPAIGN_START manifest sha256 differs from the manifest on disk')
        if ST.get('artifact_hashes_sha256') != ah: prereq.append('CAMPAIGN_START does not bind the frozen source inventory content hash')
    if glob.glob(os.path.join(RD, 'MANIFEST_AMENDMENT_*')): prereq.append('artifact amendment files present (no amendment mechanism)')
    want_inv = R.full_inventory(CODE)
    if not frozen: prereq.append('manifest carries no frozen source inventory')
    else:
        miss_inv = [k for k in want_inv if k not in frozen]; extra_inv = [k for k in frozen if k not in want_inv]; diff_inv = [k for k in want_inv if k in frozen and frozen[k] != want_inv[k]]
        if miss_inv or extra_inv: prereq.append('frozen source inventory is not the complete required set (%d missing, %d extra)' % (len(miss_inv), len(extra_inv)))
        if diff_inv: prereq.append('frozen source %s differs from the file on disk (%d differ)' % (diff_inv[0], len(diff_inv)))
        for f_ in PR.identity_failures(frozen, sorted({c['arm'] for c in cells}))[0]: prereq.append(f_)
    frozen_cqr = {k: v for k, v in frozen.items() if R.is_cqr_scope_key(k)}
    # ---- frozen kernel identity (every natively loaded binary + build record; review CQR-09): manifest vs disk NOW, and the START binding of its content hash
    ki = M.get('kernel_identity')
    if not ki: prereq.append('manifest carries no frozen kernel_identity')
    else:
        for m_ in KI.failures_vs_frozen(ki, KI.collect(CODE), sorted({c['arm'] for c in cells})): prereq.append('kernel identity at closeout: ' + m_)
        kh = hashlib.sha256(json.dumps(ki, sort_keys=True).encode()).hexdigest()
        if ST is not None and ST.get('kernel_identity_sha256') not in (None, kh): prereq.append('CAMPAIGN_START kernel identity hash differs from the manifest')
        if ST is not None and ST.get('kernel_identity_sha256') is None: prereq.append('CAMPAIGN_START does not bind the kernel identity')
        L.append('kernel identity: %d frozen tags; tags needed by the planned arms verified against disk at closeout: %s' % (len(ki), ', '.join(sorted(KI.needed_tags(sorted({c['arm'] for c in cells})))) or 'none (no planned arm loads a native artifact)'))
    # ---- gate
    if G is not None:
        if not str(G.get('gate_version', '')).startswith('cqr-gate-v1'): prereq.append('gate result produced by an unknown gate (%s)' % G.get('gate_version'))
        if G.get('failures'): prereq.append('gate lists %d failures (first: %s)' % (len(G['failures']), str(G['failures'][0])[:160]))
        if not G.get('gate_passed'): prereq.append('receipt/certificate gate FAILED')
        if G.get('manifest_sha256') != mh: prereq.append('gate result belongs to a different manifest')
        if G.get('artifact_hashes_sha256') != ah: prereq.append('gate result binds a different frozen source inventory')
        if G.get('planned') != len(cells) or G.get('receipts') != len(cells) or G.get('receipts') != len(receipts): prereq.append('gate counts (planned %s, receipts %s) differ from the manifest (%d) / disk (%d)' % (G.get('planned'), G.get('receipts'), len(cells), len(receipts)))
        gs = G.get('gated_set')
        if not isinstance(gs, list): prereq.append('gate result carries no content-addressed gated set')
        elif G.get('gated_set_sha256') != hashlib.sha256(json.dumps(gs, sort_keys=True).encode()).hexdigest(): prereq.append('gated set digest does not match the gated set')
    # ---- LATEST verification-stage attempt
    lp = os.path.join(RD, LEDGER); attempts = []; by_scope = collections.defaultdict(float)
    if os.path.exists(lp):
        for line in open(lp):
            try: row = json.loads(line)
            except Exception: continue
            if row.get('kind') != 'RECEIPT': continue
            if isinstance(row.get('wall_s'), (int, float)): by_scope[row.get('scope')] += row['wall_s']
            if row.get('scope') == 'cqr_finalize_gate': attempts.append(row)
    else: prereq.append('%s missing' % LEDGER)
    if not attempts: prereq.append('no supervised verification-stage receipt (scope cqr_finalize_gate) in the ledger: the gate was not run under the chain')
    elif not (attempts[-1].get('outcome') == 'COMPLETED' and attempts[-1].get('returncode') == 0): prereq.append('the LATEST verification-stage attempt (%s) ended %s with rc %s: a failed retry invalidates the closeout until the gate is re-run successfully' % (attempts[-1].get('job'), attempts[-1].get('outcome'), attempts[-1].get('returncode')))
    # ---- report binds the latest gate
    gp = os.path.join(RD, 'GATE_RESULT.json'); rp_ = os.path.join(RD, 'RESULTS_CQR.json')
    if RES is not None and G is not None:
        if RES.get('gated_set_sha256') is None or RES.get('gated_set_sha256') != G.get('gated_set_sha256'): prereq.append('RESULTS_CQR.json does not bind the gated set of GATE_RESULT.json (report not regenerated after the latest gate)')
        if os.path.getmtime(rp_) < os.path.getmtime(gp): prereq.append('RESULTS_CQR.json is older than GATE_RESULT.json')
        if RES.get('manifest_sha256') != mh: prereq.append('results manifest identity differs')
        if (RES.get('gate_binding') or {}).get('mismatch'): prereq.append('report records %d gated-set mismatches' % len(RES['gate_binding']['mismatch']))
        if not str(RES.get('report_version', '')).startswith('cqr-report-v1'): prereq.append('results produced by an unknown reporter (%s)' % RES.get('report_version'))
    # ---- qualification record
    if Q is not None:
        groups = Q.get('groups') or []; names = [g.get('name') for g in groups]
        if not str(Q.get('suite_version', '')).startswith('cqr-qualification'): prereq.append('qualification record from a foreign suite (%s)' % Q.get('suite_version'))
        if names != list(R.QUALIFICATION_GROUPS) and sorted(names) != sorted(R.QUALIFICATION_GROUPS) or len(names) != len(set(names)) or len(names) != len(R.QUALIFICATION_GROUPS): prereq.append('qualification groups differ from the registry schema (%d present / %d expected; missing %s; extra %s)' % (len(names), len(R.QUALIFICATION_GROUPS), [n for n in R.QUALIFICATION_GROUPS if n not in names][:3], [n for n in names if n not in R.QUALIFICATION_GROUPS][:3]))
        if not Q.get('all_pass') or Q.get('passed') != Q.get('total') or Q.get('total') != len(groups) or not groups or not all(g.get('ok') is True for g in groups): prereq.append('qualification groups not all passed (passed %s / total %s / groups %d / ok %d)' % (Q.get('passed'), Q.get('total'), len(groups), sum(1 for g in groups if g.get('ok') is True)))
        qs = Q.get('candidate_sources') or {}
        if not frozen_cqr: prereq.append('manifest carries no frozen cqr scope identity')
        miss = [k for k in frozen_cqr if k not in qs]; diff = [k for k in frozen_cqr if k in qs and qs[k] != frozen_cqr[k]]; extra_q = [k for k in qs if k not in frozen_cqr]
        if miss or diff or extra_q: prereq.append('qualification record identity does not match the frozen cqr scope (%d missing, %d differing, %d extra; e.g. %s)' % (len(miss), len(diff), len(extra_q), (miss + diff + extra_q)[:1]))
        if Q.get('suite_sha256') != R.suite_sha256(CODE): prereq.append('qualification record was produced by a different suite file (suite_sha256 %s vs the current cex/cqr/qualification.py %s): the suite that qualified the candidate must be the one on disk' % (str(Q.get('suite_sha256'))[:12], R.suite_sha256(CODE)[:12]))
    # ---- re-derive the report and compare the summary
    RR = None
    if M is not None:
        try:
            with contextlib.redirect_stdout(io.StringIO()): RR = RP.main(RD, MN, write=False)
        except Exception as ex: prereq.append('report re-derivation from the current raw records failed: %s: %s' % (type(ex).__name__, str(ex)[:120]))
    if RR is not None and RES is not None:
        if RR.get('summary_sha256') != RES.get('summary_sha256') or RR.get('summary') != RES.get('summary'): prereq.append('RESULTS_CQR.json summary (outcome counts / audit classes / gated set / unrun) differs from the summary RE-DERIVED from the current raw records')
        # the COMPLETE semantic attribution of a run row (third review CQR-R2-06): every report-facing field that carries a claim about the proof is bound to its re-derived value;
        # only presentation / timing fields (wall, stop_reason text, event counts) are outside the comparison
        SEMANTIC_RUN_FIELDS = ('cell_id', 'case', 'arm', 'cohort', 'budget', 'rep', 'status', 'outcome', 'guarantee', 'route', 'output_sha256', 'exact', 'bias', 'bias_applied_to_original_answers', 'bias_interpretation',
                               'committed_operators', 'guarantee_source', 'claimed_route', 'attribution_mismatch', 'mode', 'outcome_class', 'kind', 'work_reference', 'work_optional', 'reference_progress', 'ratio_draws', 'epochs', 'frontier', 'routes')
        # compared in the domain the report is PUBLISHED in (the JSON serialization report.main writes, default=str): the in-memory re-derivation carries tuples / Fractions that the
        # file carries as lists / strings; a non-canonical comparison refused the honest admission_v8 report (attempt 7, C12) on 13 baseline rows whose `routes` are tuple pairs
        core_run = lambda x: json.loads(json.dumps({k: x.get(k) for k in SEMANTIC_RUN_FIELDS}, sort_keys=True, default=str))
        if sorted((core_run(x) for x in RES.get('runs') or []), key=lambda x: str(x['cell_id'])) != sorted((core_run(x) for x in RR.get('runs') or []), key=lambda x: str(x['cell_id'])): prereq.append('report run rows differ from the rows RE-DERIVED from the current raw records')
        if RR.get('references_file_sha256') != RES.get('references_file_sha256'): prereq.append('REFERENCES_R0.json differs from the artifact the report was derived from')
    if RR is not None:
        inacc = [a for a in RR.get('reference_audit') or [] if a.get('accurate') == 'CONFIRMED_INACCURATE']
        if inacc: prereq.append('INVESTIGATE: %d DETERMINISTIC publications / zero claims are contradicted by an exact reference (two exact artifacts disagree, whichever is wrong): %s' % (len(inacc), [(a['arm'], a['case']) for a in inacc][:4]))
    qualified = not prereq
    counts = (RR or RES or {}).get('outcome_counts_by_arm') or {}
    verdict = 'DEVELOPMENT ADMISSION QUALIFIED' if qualified else ('INVESTIGATE' if any(p.startswith('INVESTIGATE') for p in prereq) else 'UNQUALIFIED')
    P('# CQR CAMPAIGN -- CLOSEOUT (%s UTC; %s) -- %s' % (time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()), CLOSEOUT_VERSION, verdict)); P('')
    P('Manifest `%s` sha256 `%s`%s; frozen inventory content hash `%s`; cells %d; receipts %d; gate %s (%s; gated set `%s`); qualification %s; latest cqr_finalize_gate attempt: %s.' % (MN, mh, ' (DEV manifest)' if (M or {}).get('dev') else '', ah, len(cells), len(receipts), 'PASSED' if (G and G.get('gate_passed') and not G.get('failures')) else 'FAILED / MISSING', (G or {}).get('gate_version'), (G or {}).get('gated_set_sha256'), ('%s (%s/%s)' % (Q.get('suite_version'), Q.get('passed'), Q.get('total')) if Q else 'MISSING'), ('%s rc %s' % (attempts[-1].get('outcome'), attempts[-1].get('returncode'))) if attempts else 'none')); P('')
    if not qualified:
        P('## Prerequisites failed -- NO qualified verdict'); P('')
        for f in prereq: P('- %s' % f)
        P('')
    P('## Counts by arm (from the %s)' % ('re-derived report' if RR else 'report on disk')); P(''); P('| arm | planned | received | ' + ' | '.join(RP.OUTCOME_CLASSES[:-1]) + ' |'); P('|---|---:|---:|' + '---:|' * (len(RP.OUTCOME_CLASSES) - 1))
    for arm, d in counts.items(): P('| %s | %d | %d | %s |' % (arm, d.get('planned', 0), d.get('received', 0), ' | '.join(str(d.get(k, 0)) for k in RP.OUTCOME_CLASSES[:-1])))
    P(''); P('Reference audit classes: %s' % json.dumps(((RR or RES or {}).get('summary') or {}).get('audit_counts'))); P('')
    P('## Ledger'); P(''); P('Charged seconds by scope (%s): %s; total %.1f s.' % (LEDGER, json.dumps({k: round(v, 1) for k, v in sorted(by_scope.items())}), sum(by_scope.values()))); P('')
    P('## Verdict'); P(''); P('**%s.** %s' % (verdict, ('Every prerequisite holds: complete matrix of THIS manifest, gate passed under the chain, report bound to the latest gate and re-derived equal, qualification record bound to the frozen cqr scope, no deterministic contradiction. Counts only; no performance claim. STOPPED FOR REVIEW.' if qualified else 'No qualified verdict is issued; the reasons are listed above. STOPPED FOR REVIEW.')))
    open(OUTP, 'w').write('\n'.join(L) + '\n')
    print('closeout:', verdict, ('(%d reasons)' % len(prereq)) if prereq else '', json.dumps({a: {k: d.get(k, 0) for k in ('PUBLISHED-DETERMINISTIC', 'PUBLISHED-PAC', 'PROVED_ZERO_EVIDENCE', 'DEADLINE', 'MEMORY', 'FAULT', 'other')} for a, d in counts.items()}))
    for f in prereq: print('  -', f[:240])
    return 0 if qualified else 1


if __name__ == '__main__':
    RD = sys.argv[1]; QP = sys.argv[sys.argv.index('--qualification') + 1] if '--qualification' in sys.argv else None; MN = sys.argv[sys.argv.index('--manifest') + 1] if '--manifest' in sys.argv else 'CAMPAIGN_MANIFEST.json'; OP = sys.argv[sys.argv.index('--out') + 1] if '--out' in sys.argv else None
    sys.exit(main(RD, MN, QP, OP))
