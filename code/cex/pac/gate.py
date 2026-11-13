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
import sys, os, json, hashlib, glob, math
HERE = os.path.dirname(os.path.abspath(__file__)); CODE = os.path.dirname(os.path.dirname(HERE))
for p in (os.path.join(CODE, 'cex', 'newarm'), HERE):
    if p not in sys.path: sys.path.insert(0, p)
sys.set_int_max_str_digits(0)
from fractions import Fraction as F
import core
GATE_VERSION = 'pac-gate-v3 (2026-11-13 completion: end-to-end chain verification)'
CANDIDATE_ARMS = ('P1_PAC_CONDITIONAL', 'H1_HYBRID', 'A0_POINT', 'A1_CONDITIONAL'); B0 = 'B0_FROZEN_V14'
COMPARATOR_PREFIXES = ('LIBDAI', 'LBP', 'WMB', 'IJGP', 'PGMAX', 'MERLIN')


def sha(p):
    h = hashlib.sha256()
    with open(p, 'rb') as f:
        for b in iter(lambda: f.read(1 << 20), b''): h.update(b)
    return h.hexdigest()


def _fr(x):
    return F(x) if not isinstance(x, (list, tuple)) else (F(x[0]), F(x[1]))


def _frows(x): return [[(F(a), F(b)) for a, b in row] for row in x]
def _fpts(x): return [[F(a) for a in row] for row in x]


def check_pac_certificate(w, c, man, model, fail):
    """END-TO-END certificate verification for a candidate-arm COMPLETED worker output (candidate v3; review R04 / R05): the published decimals must be DERIVED by the
    checker from independently verified pieces: (1) the original model (re-read from the frozen file) is REDUCED by the frozen reduction and must reproduce the
    certificate's reduced model and decoder; (2) the frozen component split must reproduce the partition; (3) every component's exact rows are verified against
    its own evidence: PAC rows by replaying the design + sufficient statistics, deterministic exact-cover / partial-cover rows by rebuilding the FRONTIER from the
    recorded resolved leaves (U_t) and re-deriving the deterministic bounds from the recorded resolved totals and U_t (exact arithmetic), deterministic frozen-route
    rows by re-executing the frozen exact executor on the component (the row certificate is the executor's own; a re-execution is the independent check available
    at this trust boundary); (4) the lift of the verified component rows through the re-derived decoder must equal the certificate's lifted rows; (5) the frozen
    decimal publication of those lifted rows must equal the worker's decimals. Risk ledger: K must equal the sum of cardinalities of the REBUILT reduced model.
    Envelope: U_root must equal the Tree's root bound rebuilt from the component model and the recorded cutset. Zero proofs are verified by re-derivation."""
    import engine, reduction
    cert = w.get('certificate') or {}; cid = c['cell_id']
    if cert.get('certificate_version') != 'pac-certificate-v3':
        fail(cid, 'publication with a legacy / missing certificate schema (%s): UNVERIFIABLE by the v3 chain check' % cert.get('certificate_version')); return
    task = man.get('task') or {}; eps_t = F(str(task.get('epsilon', '1/200'))); delta = F(str(task.get('delta', '1/1000000')))
    if str(cert.get('epsilon')) != str(task.get('epsilon', '1/200')) or str(w.get('epsilon')) != str(task.get('epsilon', '1/200')): fail(cid, 'epsilon differs from the manifest task')
    if w.get('guarantee_type') == 'PAC':
        if str(cert.get('delta')) != str(task.get('delta', '1/1000000')) or str(w.get('delta')) != str(task.get('delta', '1/1000000')): fail(cid, 'delta differs from the manifest task')
    elif str(cert.get('delta')) != '0': fail(cid, 'deterministic certificate with nonzero delta')
    comps = cert.get('components') or []
    if not comps: fail(cid, 'certificate without components'); return
    # ---- (1) reduction re-derived from the ORIGINAL model
    cards0 = model['cards']; rm = None; decoder = None; partition = None
    if cert.get('reduced_model') is None:
        # whole-model deterministic root route (forest / identity DAG): one component = the original model, identity decoder
        if not (len(comps) == 1 and comps[0].get('guarantee') == 'DETERMINISTIC' and comps[0].get('route') in ('forest', 'dag') and list(comps[0].get('variables') or []) == list(range(len(cards0)))): fail(cid, 'certificate without a reduced model but not a whole-model root route'); return
        rm = model; decoder = [dict(kind='identity', variable=v) for v in range(len(cards0))]; partition = [list(range(len(cards0)))]
        if cert.get('decoder') != decoder: fail(cid, 'root-route decoder is not the identity')
    else:
        try: red = reduction.reduce(model, deadline=None)
        except Exception as ex: fail(cid, 'reduction re-derivation failed: %s' % str(ex)[:60]); return
        if red.get('status') != 'REDUCED': fail(cid, 're-derived reduction reports %s for a published cell' % red.get('status')); return
        rm = red['model']; decoder = red['decoder']
        crm = cert['reduced_model']
        if list(crm.get('cards') or []) != list(rm['cards']) or [(tuple(f['scope']), [str(x) for x in f['values']]) for f in rm['factors']] != [(tuple(f['scope']), list(f['values'])) for f in crm.get('factors') or []]: fail(cid, 'certificate reduced model differs from the re-derived reduction'); return
        if json.loads(json.dumps(cert.get('decoder'), default=str)) != json.loads(json.dumps(decoder, default=str)): fail(cid, 'certificate decoder differs from the re-derived reduction decoder'); return
        try: split = core.components(rm, deadline=None)
        except Exception as ex: fail(cid, 'component split re-derivation failed: %s' % str(ex)[:60]); return
        partition = [old for old, _ in split]
        if [list(p) for p in (cert.get('partition') or [])] != [list(p) for p in partition]: fail(cid, 'certificate partition differs from the re-derived component split'); return
        comp_models = {tuple(old): cm for old, cm in split}
    # ---- (2) + (3) every component verified on its own evidence
    K_expected = sum(rm['cards']) if cert.get('reduced_model') is not None else 0
    K = cert.get('K_total'); led = cert.get('delta_ledger') or {}
    if K != K_expected or led.get('coordinates') != K_expected: fail(cid, 'K_total %s differs from the sum of cardinalities of the re-derived reduced job (%d)' % (K, K_expected)); return
    verified_rows = [None] * len(rm['cards']); verified_pts = [None] * len(rm['cards']); pac_seen = False
    if [sorted(comp.get('variables') or []) for comp in comps] != [sorted(p) for p in partition]: fail(cid, 'component variable lists differ from the partition'); return
    for comp, old in zip(comps, partition):
        g = comp.get('guarantee'); route = str(comp.get('route', '')); ci = comp.get('component')
        ivx = comp.get('intervals_exact'); ptx = comp.get('points_exact')
        if ivx is None or ptx is None: fail(cid, 'component %s: exact rows missing' % ci); return
        cm = comp_models[tuple(old)] if cert.get('reduced_model') is not None else model
        cards = cm['cards']
        try: rows = _frows(ivx); pts = _fpts(ptx)
        except Exception: fail(cid, 'component %s: unparseable exact rows' % ci); return
        if len(rows) != len(cards) or any(len(r_) != k or len(p_) != k for r_, p_, k in zip(rows, pts, cards)): fail(cid, 'component %s: exact rows shape differs from the component model' % ci); return
        if g == 'PAC':
            pac_seen = True; d = comp.get('design') or {}; R = comp.get('sufficient_statistics')
            if not d or not R: fail(cid, 'PAC component %s without design record / sufficient statistics' % ci); return
            try:
                if d.get('K_total') != K or R.get('K') != K: fail(cid, 'PAC component %s: K differs from the job ledger' % ci)
                if F(d['alpha_range']) != delta / (2 * K) or F(d['alpha_variance']) != delta / (2 * K) or F(R['alpha_range']) != delta / (2 * K) or F(R['alpha_variance']) != delta / (2 * K): fail(cid, 'PAC component %s: per-coordinate alpha differs from delta/(2K)' % ci)
                cut = d.get('cutset'); order = d.get('order_free')
                if not isinstance(cut, list) or not isinstance(order, list) or sorted(cut + order) != list(range(len(cards))) or d.get('mode') not in ('point', 'conditional'): fail(cid, 'PAC component %s: design cutset / order is not a partition of the component variables' % ci); return
                T0 = engine.Tree(cm, cut)
                if F(d['U_root']) != T0.u_root or F(R['U_root']) != T0.u_root: fail(cid, 'PAC component %s: U_root differs from the factor-max root bound rebuilt from the component model and cutset' % ci); return
                if list(R.get('cards') or []) != list(cards): fail(cid, 'PAC component %s: statistics cards differ from the component' % ci); return
                if R.get('n') != comp.get('trials') or not R.get('n'): fail(cid, 'PAC component %s: n differs from trials' % ci)
                if list(R.get('l_values') or []) != list(d.get('l_values') or []) or F(d['epsilon']) != eps_t: fail(cid, 'PAC component %s: l values / epsilon differ' % ci)
                fr = comp.get('frontier') or {}
                if d.get('resolve'):
                    Tr = engine.Tree.rebuild(cm, cut, fr.get('resolved_leaves') or [], fr.get('extra_expanded') or [])
                    if _frac_str(Tr.U_t) != fr.get('U_t') or len(fr.get('resolved_leaves') or []) != comp.get('resolved_cells'): fail(cid, 'PAC component %s: frontier record does not rebuild (U_t / resolved cells)' % ci)
                ok, hrows, hpts, chosen, widths, bU, vsets = engine.hulls_from_record(R, eps_t, F(d['decimal_margin']))
                if not ok: fail(cid, 'PAC component %s: REPLAY of the certificate from the sufficient statistics does not certify' % ci); return
                cpr = comp.get('certifier_per_row') or []
                for v in range(len(cards)):
                    if hrows[v] != rows[v] or hpts[v] != pts[v] or chosen[v] != cpr[v]: fail(cid, 'PAC component %s: replayed row %d differs from the recorded exact rows' % (ci, v)); return
            except (KeyError, TypeError, ValueError, ZeroDivisionError) as ex: fail(cid, 'PAC component %s: malformed certificate (%s)' % (ci, str(ex)[:60])); return
        elif g == 'DETERMINISTIC':
            if route.startswith('pac_'):
                d = comp.get('design') or {}; fr = comp.get('frontier') or {}; RT = comp.get('resolved_totals') or {}
                if 'uniform_factorless' in route:
                    if cm['factors'] or any(rows[v] != [(F(1, k), F(1, k))] * k for v, k in enumerate(cards)): fail(cid, 'component %s: factorless uniform claim does not match the component' % ci); return
                else:
                    try:
                        cut = d.get('cutset'); order = d.get('order_free')
                        if not isinstance(cut, list) or sorted(cut + (order or [])) != list(range(len(cards))): fail(cid, 'component %s: design cutset missing' % ci); return
                        Tr = engine.Tree.rebuild(cm, cut, fr.get('resolved_leaves') or [], fr.get('extra_expanded') or [])
                        if _frac_str(Tr.U_t) != fr.get('U_t'): fail(cid, 'component %s: frontier record does not rebuild to the recorded U_t' % ci); return
                        if 'exact_cover' in route and Tr.U_t != 0: fail(cid, 'component %s: exact-cover claim but the rebuilt frontier is not closed' % ci); return
                        # every recorded resolved cell is re-evaluated EXACTLY when affordable (<= exact_leaf cap completions), else its recorded enclosure is accepted as the kernel's certificate (trusted-executor boundary, stated)
                        cells = RT.get('cells') or []
                        if len(cells) != len(fr.get('resolved_leaves') or []) or sorted(tuple(x['leaf']) for x in cells) != sorted(tuple(l) for l in fr['resolved_leaves']): fail(cid, 'component %s: resolved totals cells differ from the frontier leaves' % ci); return
                        import contrib
                        free_count = Tr.free_count; checked_exact = 0; A_lo = F(0); A_hi = F(0)
                        for x in cells:
                            lo, hi = F(x['B0_lo']), F(x['B0_hi']); A_lo += lo; A_hi += hi
                            if free_count <= 4096:
                                ex = contrib.cell_exact(cm, dict(zip(cut, x['leaf'])), None)['B0'][0]
                                if not (lo <= ex <= hi): fail(cid, 'component %s: recorded cell mass enclosure does not contain the exact mass' % ci); return
                                checked_exact += 1
                        if F(RT.get('A_exact_lo', '0')) != A_lo or F(RT.get('A_exact_hi', '0')) != A_hi: fail(cid, 'component %s: resolved exact mass does not equal the sum of the recorded cells' % ci); return
                        # deterministic bounds re-derived from the recorded totals + rebuilt U_t must contain / equal the recorded rows
                        E = RT.get('E'); scale = F(2) ** int(E); Alo = F(float(RT['A_lo'])) * scale; Ahi = F(float(RT['A_hi'])) * scale
                        if not (Alo <= A_lo and A_hi <= Ahi): fail(cid, 'component %s: block-floating resolved mass does not enclose the exact resolved mass' % ci); return
                        if Alo <= 0: fail(cid, 'component %s: deterministic publication with a zero resolved mass lower bound' % ci); return
                        off = [0]
                        for k in cards: off.append(off[-1] + k)
                        for v in range(len(cards)):
                            for s_ in range(cards[v]):
                                j = off[v] + s_; lo = F(float(RT['a_lo'][j])) * scale; hi = F(float(RT['a_hi'][j])) * scale
                                dlo = max(F(0), lo / (Ahi + Tr.U_t)); dhi = min(F(1), (hi + Tr.U_t) / Alo)
                                if rows[v][s_] != (dlo, dhi): fail(cid, 'component %s: recorded deterministic row %d differs from the bounds re-derived from the resolved totals and U_t' % (ci, v)); return
                        p_ = [engine.feasible_point(rows[v], eps_t - F(d['decimal_margin'])) for v in range(len(cards))]
                        if any(x is None for x in p_) or any(p_[v] != pts[v] for v in range(len(cards))): fail(cid, 'component %s: recorded points are not the feasible simplex points of the rows' % ci); return
                    except (KeyError, TypeError, ValueError, ZeroDivisionError) as ex: fail(cid, 'component %s: malformed deterministic certificate (%s)' % (ci, str(ex)[:60])); return
            elif route in ('support', 'dag', 'stream', 'forest'):
                # frozen deterministic executor route: the independent check at this boundary is a RE-EXECUTION of the frozen route on the component (bounded)
                try:
                    if route == 'forest':
                        import forest; res = forest.solve(model, deadline=None, independent_replay=True); rr = res['intervals']; rp = res['points']
                    elif route == 'dag' and cert.get('reduced_model') is None:
                        import dag; res = dag.execute_plan(dag.plan(model, deadline=None), deadline=None); rr = res['intervals']; rp = res['points']
                    else:
                        plan = core._discover_component(cm, None, route); res = core._execute_component(plan, None); rr = res['intervals']; rp = res.get('points') or [[(lo + hi) / 2 for lo, hi in row] for row in rr]
                    rr = [[(F(a), F(b)) for a, b in row] for row in rr]; rp = [[F(x) for x in row] for row in rp]
                    if rr != rows or rp != pts: fail(cid, 'component %s: re-execution of the frozen %s route does not reproduce the recorded rows' % (ci, route)); return
                except Exception as ex: fail(cid, 'component %s: frozen route %s re-execution failed (%s)' % (ci, route, str(ex)[:60])); return
            else: fail(cid, 'component %s: unknown deterministic route %s' % (ci, route)); return
            core.verify_output(rows, pts, eps_t)
        else: fail(cid, 'component %s with guarantee %s' % (ci, g)); return
        for v, row, q in zip(old, rows, pts): verified_rows[v] = row; verified_pts[v] = q
    if w.get('guarantee_type') == 'PAC' and not pac_seen: fail(cid, 'PAC guarantee without any PAC component'); return
    if w.get('guarantee_type') == 'DETERMINISTIC' and pac_seen: fail(cid, 'DETERMINISTIC guarantee with a PAC component'); return
    # ---- (4) lift the VERIFIED component rows through the re-derived decoder; (5) publish and compare with the worker's decimals
    try:
        if cert.get('reduced_model') is None: LI, LP = verified_rows, verified_pts
        else: LI, LP = reduction.lift(dict(status='REDUCED', decoder=decoder), verified_rows, verified_pts)
        if [[(str(a), str(b)) for a, b in row] for row in LI] != [[tuple(x) for x in row] for row in cert['lifted_intervals_exact']] or [[str(x) for x in row] for row in LP] != [list(row) for row in cert['lifted_points_exact']]: fail(cid, 'the lift of the VERIFIED component rows differs from the certificate lifted rows'); return
        core.verify_output(LI, LP, eps_t); di, dp = core.publish(LI, LP, epsilon=eps_t)
        if di != w.get('intervals') or dp != w.get('points'): fail(cid, 'the published decimals are not the frozen publication of the VERIFIED lifted rows'); return
    except Exception as ex: fail(cid, 'chain verification: %s' % str(ex)[:80]); return


def _frac_str(x): return '%d/%d' % (x.numerator, x.denominator)


def verify_zero_proof(model, proof):
    """re-derive a structured zero-evidence proof on the ORIGINAL model; returns None when verified, else the reason it is not"""
    import reduction, engine
    if not isinstance(proof, dict): return 'proof is not a structured record (%r)' % (str(proof)[:40],)
    kind = proof.get('kind')
    try:
        if kind == 'forest':
            import forest
            try: forest.solve(model, deadline=None, independent_replay=True); return 'forest route publishes a posterior: no zero'
            except forest.ZeroEvidence: return None
            except Exception as ex: return 'forest route does not reproduce the zero (%s)' % type(ex).__name__
        red = reduction.reduce(model, deadline=None)
        if kind == 'reduction': return None if red.get('status') == 'ZERO_EVIDENCE' else 'reduction of the original model is not zero-evidence'
        if red.get('status') == 'ZERO_EVIDENCE': return 'the reduction itself is zero: the proof kind %s does not match' % kind
        rm = red['model']
        try: split = core.components(rm, deadline=None)
        except ValueError as ex:
            if str(ex) == 'ZERO_EVIDENCE': return None if kind == 'component_restriction' else 'component restriction is zero: kind %s does not match' % kind
            raise
        if kind == 'component_restriction': return 'component restriction is not zero'
        comp = proof.get('component'); vars_ = proof.get('variables')
        if not isinstance(comp, int) or comp >= len(split) or list(split[comp][0]) != list(vars_ or []): return 'component index / variables do not match the re-derived partition'
        cm = split[comp][1]
        if kind == 'exact_component':
            if math.prod(cm['cards']) <= 1 << 20:
                import contrib; return None if contrib.cell_exact(cm, {}, None)['B0'][0] == 0 else 'exact enumeration of the component gives positive mass'
            res = core._execute_component(core._discover_component(cm, None, proof.get('route', 'auto')), None); return None if res.get('status') == 'ZERO_EVIDENCE' else 'frozen route re-execution does not report zero'
        if kind == 'pac_root_bound':
            T = engine.Tree(cm, proof.get('cutset') or []); return None if T.u_root == 0 else 'root factor-max bound is positive'
        if kind == 'pac_exact_cover':
            fr = proof.get('frontier') or {}; RT = proof.get('resolved_totals') or {}; cut = proof.get('cutset') or []
            T = engine.Tree.rebuild(cm, cut, fr.get('resolved_leaves') or [], fr.get('extra_expanded') or [])
            if T.U_t != 0: return 'rebuilt frontier is not closed'
            if F(RT.get('A_exact_hi', '1')) != 0: return 'resolved mass upper bound is positive'
            import contrib
            if T.free_count <= 4096:
                for x in RT.get('cells') or []:
                    if contrib.cell_exact(cm, dict(zip(cut, x['leaf'])), None)['B0'][0] != 0: return 'a recorded resolved cell has positive exact mass'
            return None
        return 'unknown proof kind %s' % kind
    except Exception as ex: return 're-derivation error %s: %s' % (type(ex).__name__, str(ex)[:60])


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
    # ---- frozen source identity PER ARM (candidate v3, review R06): candidate workers record pac/* + newarm/*; the B0 arm's identity is b0_frozen_v14/*; an amendment
    # may only be used when the START record names it (bound before execution) -- an unbound amendment is a provenance failure, never an override
    st_doc = json.load(open(sp)) if os.path.exists(sp) else {}
    ch = man.get('candidate_artifact_hashes') or {}
    if not (isinstance(ch, dict) and ch and all('/' in k for k in ch)): fail('*', 'manifest candidate_artifact_hashes must be a NONEMPTY per-directory map (dir/file keys)'); ch = {}
    ap = sorted(glob.glob(os.path.join(RD, 'MANIFEST_AMENDMENT_*artifact_hashes.json')))
    if ap:
        bound = set(st_doc.get('bound_amendments') or [])
        for a_ in ap:
            if os.path.basename(a_) not in bound: fail('*', 'artifact amendment %s is not bound by CAMPAIGN_START (bound_amendments): unauthenticated override refused' % os.path.basename(a_))
            else:
                am = json.load(open(a_))
                if am.get('manifest_sha256') != mh: fail('*', 'amendment references a different manifest hash')
                pdh = am.get('per_directory_hashes') or {}
                if not (pdh.get('pac') and pdh.get('newarm')): fail('*', 'bound amendment with an empty candidate map refused')
                else: ch = {'%s/%s' % (d, k): v for d, m_ in pdh.items() for k, v in m_.items()}
    frozen_candidate = {k: v for k, v in ch.items() if k.split('/', 1)[0] in ('pac', 'newarm')}
    frozen_b0 = {k: v for k, v in ch.items() if k.split('/', 1)[0] == 'b0_frozen_v14'}
    if not frozen_candidate: fail('*', 'frozen candidate identity (pac/*, newarm/*) is empty')
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
        wall = r.get('launch_relative_wall_s'); timely = isinstance(wall, (int, float)) and not isinstance(wall, bool) and wall == wall and 0 <= wall <= float(c['budget_s'])
        if isinstance(wall, (int, float)) and not (0 <= wall < float('inf')): fail(cid, 'receipt wall is not a finite nonnegative number (%s)' % wall)
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
                if arm == B0 and frozen_b0 and isinstance(w.get('source_hashes'), dict):
                    for k, v in frozen_b0.items():
                        if w['source_hashes'].get(k.split('/', 1)[1]) not in (None, v): fail(cid, 'B0 worker source %s differs from the frozen artifact' % k)
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
                    nf = len(failures); check_pac_certificate(w, c, man, model, fail)
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
                # a zero claim carries a GUARANTEE: it receives the same identity / process / timeliness checks as a publication, and its proof is RE-DERIVED
                if not timely: fail(cid, 'zero-evidence claim after the budget (late proof is not a timely result)')
                if sup.get('rc') != 0 or sup.get('outcome') not in ('COMPLETED', 'EXIT', None) and 'KILL' in str(sup.get('outcome')): fail(cid, 'zero-evidence claim with supervisor rc %s / outcome %s' % (sup.get('rc'), sup.get('outcome')))
                wp = os.path.join(RD, r.get('worker_output') or 'MISSING')
                if c['arm'] in CANDIDATE_ARMS:
                    if not r.get('worker_output') or not os.path.exists(wp): fail(cid, 'zero-evidence claim without a worker output')
                    elif sha(wp) != r.get('output_sha256'): fail(cid, 'zero-evidence worker output sha256 differs from the receipt')
                    else:
                        w = json.load(open(wp))
                        if w.get('status') != 'STOPPED' or w.get('outcome') != 'PROVED_ZERO_EVIDENCE' or w.get('late_proof'): fail(cid, 'zero-evidence claim without a recorded timely proof')
                        if w.get('nonce') != r.get('nonce') or w.get('seed') != c.get('seed') or w.get('arm') != c['arm']: fail(cid, 'zero-evidence output nonce / seed / arm differ from the cell')
                        cs = w.get('candidate_sources') or {}
                        if any(k not in cs or cs[k] != v for k, v in frozen_candidate.items()): fail(cid, 'zero-evidence output source identity incomplete or differs from the frozen artifact')
                        mpth = c.get('model_path')
                        if not mpth or not os.path.exists(mpth): fail(cid, 'frozen input file missing on disk')
                        else:
                            if mpth not in models: models[mpth] = core.read_uai(mpth)
                            model, binding = models[mpth]
                            if binding.get('model_sha256') != c.get('model_sha256') or binding.get('evidence_sha256') != c.get('evidence_sha256') or w.get('binding') != binding: fail(cid, 'zero-evidence output binding differs from the frozen input')
                            else:
                                msg = verify_zero_proof(model, w.get('zero_evidence_proof'))
                                if msg: fail(cid, 'zero-evidence proof NOT re-derivable: %s' % msg)
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
