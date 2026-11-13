"""Specification-driven RECEIPT + CERTIFICATE GATE -- candidate v2 (repair of review F05 of 13 Nov 2026).
Authoritative specification = the frozen CAMPAIGN_MANIFEST.json bound to the pre-execution CAMPAIGN_START.json (its sha256 of the manifest file is re-computed and
must agree; the ledger's CAMPAIGN_START row must agree as well) and, when present, the MANIFEST_AMENDMENT (which must reference the same manifest hash).
Checks (every failure listed; exit nonzero on any):
  * manifest: no duplicate planned cell ids; every planned cell has exactly ONE receipt; no receipt outside the plan; receipt fields equal the manifest's;
  * timeliness: RECOMPUTED (launch_relative_wall_s <= budget_s) for every COMPLETED and every PROVED_ZERO_EVIDENCE receipt (the receipt's within_budget flag is never trusted);
  * process: COMPLETED needs supervisor rc 0 / outcome COMPLETED; an output file with the receipted sha256 for EVERY arm (worker.json, MAR file, CBI result);
  * candidate arms: worker status, nonce, seed, arm, epsilon and delta equal the manifest task; the COMPLETE frozen candidate source identity (every frozen key must be
    present and equal); the worker binding equals BOTH the frozen manifest hashes AND the re-hashed input files on disk (output-to-frozen-input binding);
    original-model shape; one-hot evidence rows; the frozen publication contract (core.verify_output);
  * certificate (candidate v2 schema 'pac-certificate-v2'): delta ledger consistency (K_total = certificate K = design K; alphas = family delta / K); for every PAC
    component: design record present, sufficient statistics present, n = trials, U_root > 0, and the hulls / points REPLAYED from the sufficient statistics by
    engine.hulls_from_record equal the recorded exact rows; the lifted exact rows re-published by the frozen core.publish equal the worker's decimals; for exact-cover
    components: resolved_cells >= 1 and guarantee DETERMINISTIC; a legacy v1 certificate (no design / statistics) is UNVERIFIABLE = failure for any PAC guarantee;
  * zero evidence: PROVED_ZERO_EVIDENCE needs a worker output with a recorded proof, supervisor rc 0, status STOPPED, not late, wall <= budget;
  * guarantee / outcome consistency: PUBLISHED <-> COMPLETED; PAC / DETERMINISTIC only with PUBLISHED or a proved timely zero.
Trust boundary: the gate verifies task binding, the lawful statistical construction and the numerical enclosures / stopping predicate; it cannot certify that a particular
random outcome is accurate (the reference audit is a separate diagnostic).
    python cex/pac/gate.py <RD> [--manifest CAMPAIGN_MANIFEST.json] [--out GATE_RESULT.json]  -> exit 0 only if every check passes"""
import sys, os, json, hashlib, glob
HERE = os.path.dirname(os.path.abspath(__file__)); CODE = os.path.dirname(os.path.dirname(HERE))
for p in (os.path.join(CODE, 'cex', 'newarm'), HERE):
    if p not in sys.path: sys.path.insert(0, p)
sys.set_int_max_str_digits(0)
from fractions import Fraction as F
import core
GATE_VERSION = 'pac-gate-v2 (2026-11-13 repair)'
CANDIDATE_ARMS = ('P1_PAC_CONDITIONAL', 'H1_HYBRID', 'A0_POINT', 'A1_CONDITIONAL'); B0 = 'B0_FROZEN_V14'
COMPARATOR_PREFIXES = ('LIBDAI', 'LBP', 'WMB', 'IJGP', 'PGMAX', 'MERLIN')


def sha(p):
    h = hashlib.sha256()
    with open(p, 'rb') as f:
        for b in iter(lambda: f.read(1 << 20), b''): h.update(b)
    return h.hexdigest()


def _fr(x):
    return F(x) if not isinstance(x, (list, tuple)) else (F(x[0]), F(x[1]))


def check_pac_certificate(w, c, man, fail):
    """certificate-specific verification for a candidate-arm COMPLETED worker output"""
    import engine
    cert = w.get('certificate') or {}; cid = c['cell_id']
    if cert.get('certificate_version') != 'pac-certificate-v2':
        if w.get('guarantee_type') == 'PAC': fail(cid, 'PAC guarantee with a legacy / missing certificate: UNVERIFIABLE (no design record / sufficient statistics)')
        else: fail(cid, 'deterministic publication with a legacy / missing certificate schema (v2 requires certificate_version pac-certificate-v2)')
        return
    task = man.get('task') or {}
    if str(cert.get('epsilon')) != str(task.get('epsilon', '1/200')) or str(w.get('epsilon')) != str(task.get('epsilon', '1/200')): fail(cid, 'epsilon differs from the manifest task')
    if w.get('guarantee_type') == 'PAC':
        if str(cert.get('delta')) != str(task.get('delta', '1/1000000')) or str(w.get('delta')) != str(task.get('delta', '1/1000000')): fail(cid, 'delta differs from the manifest task')
    elif str(cert.get('delta')) != '0': fail(cid, 'deterministic certificate with nonzero delta')
    led = cert.get('delta_ledger') or {}; K = cert.get('K_total')
    if not isinstance(K, int) or K < 0 or led.get('coordinates') != K: fail(cid, 'delta ledger K_total inconsistent'); return
    delta = F(str(task.get('delta', '1/1000000')))
    comps = cert.get('components') or []
    if not comps: fail(cid, 'certificate without components'); return
    pac_seen = False
    for comp in comps:
        g = comp.get('guarantee'); route = str(comp.get('route', ''))
        if g == 'PAC':
            pac_seen = True; d = comp.get('design') or {}; R = comp.get('sufficient_statistics')
            if not d or not R: fail(cid, 'PAC component %s without design record / sufficient statistics' % comp.get('component')); continue
            try:
                if d.get('K_total') != K or R.get('K') != K: fail(cid, 'PAC component %s: K differs from the job ledger' % comp.get('component'))
                if F(d['alpha_range']) != delta / (2 * K) or F(d['alpha_variance']) != delta / (2 * K) or F(R['alpha_range']) != delta / (2 * K) or F(R['alpha_variance']) != delta / (2 * K): fail(cid, 'PAC component %s: per-coordinate alpha differs from delta/(2K)' % comp.get('component'))
                if F(d['U_root']) <= 0 or F(R['U_root']) != F(d['U_root']): fail(cid, 'PAC component %s: U_root missing / inconsistent' % comp.get('component'))
                if R.get('n') != comp.get('trials') or not R.get('n'): fail(cid, 'PAC component %s: n differs from trials' % comp.get('component'))
                if list(R.get('l_values') or []) != list(d.get('l_values') or []): fail(cid, 'PAC component %s: l values differ' % comp.get('component'))
                if not isinstance(d.get('cutset'), list) or not isinstance(d.get('order_free'), list): fail(cid, 'PAC component %s: canonical cutset / order missing' % comp.get('component'))
                ok, rows, pts, chosen, widths, bU, vsets = engine.hulls_from_record(R, F(d['epsilon']), F(d['decimal_margin']))
                if not ok: fail(cid, 'PAC component %s: REPLAY of the certificate from the sufficient statistics does not certify' % comp.get('component')); continue
                ivx = comp.get('intervals_exact'); ptx = comp.get('points_exact'); cpr = comp.get('certifier_per_row') or []
                if ivx is None or ptx is None: fail(cid, 'PAC component %s: exact rows missing' % comp.get('component')); continue
                for v in range(len(R['cards'])):
                    if [(str(a), str(b)) for a, b in rows[v]] != [tuple(x) for x in ivx[v]] or [str(x) for x in pts[v]] != list(ptx[v]) or chosen[v] != cpr[v]: fail(cid, 'PAC component %s: replayed row %d differs from the recorded certificate' % (comp.get('component'), v)); break
            except (KeyError, TypeError, ValueError, ZeroDivisionError) as ex: fail(cid, 'PAC component %s: malformed certificate (%s)' % (comp.get('component'), str(ex)[:60]))
        elif g == 'DETERMINISTIC':
            if route.startswith('pac_') and 'exact_cover' in route and not (comp.get('resolved_cells') or 0) >= 1: fail(cid, 'exact-cover component %s without resolved cells' % comp.get('component'))
        else: fail(cid, 'component %s with guarantee %s' % (comp.get('component'), g))
    if w.get('guarantee_type') == 'PAC' and not pac_seen: fail(cid, 'PAC guarantee without any PAC component')
    if w.get('guarantee_type') == 'DETERMINISTIC' and pac_seen: fail(cid, 'DETERMINISTIC guarantee with a PAC component')
    # lifted exact rows -> frozen decimal publication must reproduce the worker's published decimals
    try:
        LI = [[(F(a), F(b)) for a, b in row] for row in cert['lifted_intervals_exact']]; LP = [[F(x) for x in row] for row in cert['lifted_points_exact']]
        eps_t = F(str((man.get('task') or {}).get('epsilon', '1/200'))); core.verify_output(LI, LP, eps_t); di, dp = core.publish(LI, LP, epsilon=eps_t)
        if di != w.get('intervals') or dp != w.get('points'): fail(cid, 'the published decimals are not the frozen publication of the certified exact rows')
    except Exception as ex: fail(cid, 'lifted exact rows: %s' % str(ex)[:80])


def main(RD, manifest_name='CAMPAIGN_MANIFEST.json', out_path=None):
    RD = os.path.abspath(RD); failures = []
    def fail(cid, msg): failures.append((cid, msg))
    mp = os.path.join(RD, manifest_name)
    if not os.path.exists(mp): fail('*', 'manifest %s missing' % manifest_name); return _write(RD, out_path, dict(gate_version=GATE_VERSION, failures=failures, gate_passed=False))
    man = json.load(open(mp)); mh = sha(mp)
    # ---- pre-execution START binding + ledger + amendment
    sp = os.path.join(RD, 'CAMPAIGN_START.json')
    if not os.path.exists(sp): fail('*', 'CAMPAIGN_START.json missing (no pre-execution binding of the manifest)')
    else:
        st = json.load(open(sp))
        if st.get('manifest_sha256') != mh: fail('*', 'CAMPAIGN_START manifest sha256 %s differs from the manifest file on disk %s' % (str(st.get('manifest_sha256'))[:16], mh[:16]))
        if st.get('manifest') not in (None, manifest_name): fail('*', 'CAMPAIGN_START names a different manifest file')
    lp = os.path.join(RD, 'PAC_LEDGER.jsonl'); first_start = None
    if os.path.exists(lp):
        for line in open(lp):
            if not line.strip(): continue
            r = json.loads(line)
            if r.get('kind') == 'CAMPAIGN_START': first_start = r; break
        if first_start is None: fail('*', 'ledger without a CAMPAIGN_START row')
        elif first_start.get('manifest_sha256') != mh: fail('*', 'ledger CAMPAIGN_START manifest sha256 differs from the manifest on disk')
    else: fail('*', 'PAC_LEDGER.jsonl missing')
    frozen_candidate = None; ap = sorted(glob.glob(os.path.join(RD, 'MANIFEST_AMENDMENT_*artifact_hashes.json')))
    if ap:
        am = json.load(open(ap[-1]))
        if am.get('manifest_sha256') != mh: fail('*', 'amendment references a different manifest hash')
        pdh = am.get('per_directory_hashes') or {}
        if 'pac' in pdh and 'newarm' in pdh: frozen_candidate = {'%s/%s' % (d, k): v for d in ('pac', 'newarm') for k, v in pdh[d].items()}
        else: fail('*', 'amendment without per-directory candidate hashes')
    if frozen_candidate is None:
        ch = man.get('candidate_artifact_hashes') or {}
        if isinstance(ch, dict) and all('/' in k for k in ch): frozen_candidate = dict(ch)
        else: fail('*', 'no unambiguous frozen candidate source identity (per-directory keys required)'); frozen_candidate = {}
    # ---- plan integrity
    ids = [c['cell_id'] for c in man['cells']]
    if len(ids) != len(set(ids)): fail('*', 'duplicate planned cell ids in the manifest: %d duplicates' % (len(ids) - len(set(ids))))
    cells = {c['cell_id']: c for c in man['cells']}
    receipts = {}
    for rp in glob.glob(os.path.join(RD, 'cells', '*', 'receipt.json')):
        r = json.load(open(rp)); cid = r.get('cell_id')
        if cid in receipts: fail(cid, 'duplicate receipt: %s and %s' % (receipts[cid]['_path'], rp)); continue
        r['_path'] = rp; receipts[cid] = r
    for cid in cells:
        if cid not in receipts: fail(cid, 'planned cell without receipt (NOT_RUN)')
    for cid in receipts:
        if cid not in cells: fail(cid, 'receipt for a cell not in the frozen manifest')
    task = man.get('task') or {}; EPS = F(str(task.get('epsilon', '1/200'))); models = {}; checked = 0; gated = 0; pac_verified = 0
    for cid, r in receipts.items():
        c = cells.get(cid)
        if not c: continue
        for k in ('case_id', 'arm', 'replicate', 'budget_s', 'seed', 'model_sha256', 'evidence_sha256', 'cohort'):
            if r.get(k) != c.get(k): fail(cid, 'receipt %s differs from the manifest' % k)
        wall = r.get('launch_relative_wall_s'); timely = isinstance(wall, (int, float)) and wall <= float(c['budget_s'])
        sup = r.get('supervisor') or {}
        if r.get('status') == 'COMPLETED':
            checked += 1
            if sup.get('rc') != 0: fail(cid, 'COMPLETED with supervisor rc %s' % sup.get('rc'))
            if sup.get('outcome') != 'COMPLETED': fail(cid, 'COMPLETED with supervisor outcome %s' % sup.get('outcome'))
            if not timely: fail(cid, 'COMPLETED but recomputed launch-relative wall %s > budget %s' % (wall, c['budget_s']))
            if r.get('outcome') != 'PUBLISHED': fail(cid, 'COMPLETED but outcome %s' % r.get('outcome'))
            arm = c['arm']
            if arm in CANDIDATE_ARMS or arm == B0 or arm == 'CBI_NATIVE':
                wp = os.path.join(RD, r.get('worker_output') or 'MISSING')
                if not r.get('worker_output') or not os.path.exists(wp): fail(cid, 'COMPLETED without a worker output file'); continue
                if sha(wp) != r.get('output_sha256'): fail(cid, 'worker output sha256 differs from the receipt'); continue
                w = json.load(open(wp))
                if arm == 'CBI_NATIVE':
                    if w.get('status') != 'CERTIFIED': fail(cid, 'CBI output status %s' % w.get('status'))
                    if r.get('guarantee_type') != 'DETERMINISTIC': fail(cid, 'CBI completed with guarantee %s' % r.get('guarantee_type'))
                    gated += 1; continue
                if w.get('status') != 'COMPLETED': fail(cid, 'worker status %s' % w.get('status'))
                mpth = c.get('model_path')
                if not mpth or not os.path.exists(mpth): fail(cid, 'frozen input file missing on disk'); continue
                if mpth not in models: models[mpth] = core.read_uai(mpth)
                model, binding = models[mpth]
                if binding.get('model_sha256') != c.get('model_sha256') or binding.get('evidence_sha256') != c.get('evidence_sha256'): fail(cid, 'input files on disk differ from the FROZEN manifest hashes (input changed after freeze)')
                if w.get('binding') != binding: fail(cid, 'worker binding differs from the actual input files')
                if w.get('binding') != dict(model_sha256=c.get('model_sha256'), evidence_sha256=c.get('evidence_sha256')): fail(cid, 'worker binding differs from the frozen manifest hashes')
                if arm in CANDIDATE_ARMS:
                    if w.get('nonce') != r.get('nonce'): fail(cid, 'worker nonce differs from the receipt (stale or foreign output)')
                    if w.get('seed') != c.get('seed'): fail(cid, 'worker seed differs from the manifest')
                    if w.get('arm') != arm: fail(cid, 'worker arm differs')
                    if w.get('guarantee_type') not in ('PAC', 'DETERMINISTIC'): fail(cid, 'completed candidate output without a guarantee type')
                    cs = w.get('candidate_sources') or {}
                    missing = [k for k in frozen_candidate if k not in cs]; differ = [k for k in frozen_candidate if k in cs and cs[k] != frozen_candidate[k]]
                    if missing: fail(cid, 'worker candidate source identity incomplete: %d frozen sources not recorded (e.g. %s)' % (len(missing), missing[0]))
                    if differ: fail(cid, 'worker candidate source %s differs from the frozen artifact' % differ[0])
                if r.get('guarantee_type') != w.get('guarantee_type', 'DETERMINISTIC'): fail(cid, 'receipt guarantee_type differs from the worker')
                iv = w.get('intervals'); pts = w.get('points'); cards = model['cards']; ev = model.get('evidence', {})
                okshape = isinstance(iv, list) and isinstance(pts, list) and len(iv) == len(cards) and len(pts) == len(cards) and all(isinstance(row, list) and isinstance(pr, list) and len(row) == k and len(pr) == k for row, pr, k in zip(iv, pts, cards))
                if not okshape: fail(cid, 'output shape differs from the original model'); continue
                try:
                    IV = [[(F(a), F(b)) for a, b in row] for row in iv]; PT = [[F(x) for x in row] for row in pts]; core.verify_output(IV, PT, EPS)
                    for v, a in ev.items():
                        if not all((PT[v][s] == 1 and IV[v][s] == (F(1), F(1))) if s == a else (PT[v][s] == 0 and IV[v][s] == (F(0), F(0))) for s in range(cards[v])): fail(cid, 'observed variable %d not one-hot' % v)
                except Exception as ex: fail(cid, 'publication contract: %s' % str(ex)[:80]); continue
                if arm in CANDIDATE_ARMS:
                    nf = len(failures); check_pac_certificate(w, c, man, fail)
                    if len(failures) == nf and w.get('guarantee_type') == 'PAC': pac_verified += 1
                gated += 1
            elif arm.startswith(COMPARATOR_PREFIXES):
                cmpr = r.get('comparator') or {}; of = cmpr.get('output_file')
                if not of or not os.path.exists(of): fail(cid, 'COMPLETED comparator without its output file'); continue
                if sha(of) != cmpr.get('output_sha256'): fail(cid, 'comparator output sha256 differs from the receipt')
                if r.get('guarantee_type') != 'UNGUARANTEED': fail(cid, 'comparator completed with guarantee %s' % r.get('guarantee_type'))
                gated += 1
            else: fail(cid, 'unknown arm %s' % arm)
        else:
            if r.get('outcome') == 'PUBLISHED': fail(cid, 'non-COMPLETED receipt with outcome PUBLISHED')
            if r.get('outcome') == 'PROVED_ZERO_EVIDENCE':
                if not timely: fail(cid, 'zero-evidence claim after the budget (late proof is not a timely result)')
                if sup.get('rc') != 0: fail(cid, 'zero-evidence claim with supervisor rc %s' % sup.get('rc'))
                wp = os.path.join(RD, r.get('worker_output') or 'MISSING')
                if c['arm'] in CANDIDATE_ARMS:
                    if not r.get('worker_output') or not os.path.exists(wp): fail(cid, 'zero-evidence claim without a worker output')
                    else:
                        w = json.load(open(wp))
                        if w.get('outcome') != 'PROVED_ZERO_EVIDENCE' or not w.get('zero_evidence_proof') or w.get('late_proof'): fail(cid, 'zero-evidence claim without a recorded timely proof')
                elif c['arm'] == B0:
                    if not r.get('worker_output') or not os.path.exists(wp): fail(cid, 'zero-evidence claim without a worker output')
                elif r.get('guarantee_type') in ('PAC', 'DETERMINISTIC'): fail(cid, 'comparator zero outcome cannot carry a guarantee (underflow is indistinguishable)')
            elif r.get('guarantee_type') in ('PAC', 'DETERMINISTIC'): fail(cid, 'guarantee claimed without publication')
    res = dict(gate_version=GATE_VERSION, manifest=manifest_name, manifest_sha256=mh, planned=len(cells), receipts=len(receipts), completed_checked=checked, completed_gated=gated, pac_certificates_replayed=pac_verified, failures=failures, gate_passed=not failures)
    return _write(RD, out_path, res)


def _write(RD, out_path, res):
    out_path = out_path or os.path.join(RD, 'GATE_RESULT.json')
    json.dump(res, open(out_path, 'w'), indent=1); print(json.dumps({k: res.get(k) for k in ('gate_version', 'planned', 'receipts', 'completed_checked', 'completed_gated', 'pac_certificates_replayed', 'gate_passed')}))
    for f in res['failures'][:40]: print('  ', f)
    if len(res['failures']) > 40: print('   ... %d failures total' % len(res['failures']))
    return 0 if res['gate_passed'] else 1


if __name__ == '__main__':
    mn = sys.argv[sys.argv.index('--manifest') + 1] if '--manifest' in sys.argv else 'CAMPAIGN_MANIFEST.json'; op = sys.argv[sys.argv.index('--out') + 1] if '--out' in sys.argv else None
    sys.exit(main(sys.argv[1], mn, op))
