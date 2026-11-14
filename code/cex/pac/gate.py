"""Specification-driven RECEIPT + CERTIFICATE GATE -- candidate v4 (third adversarial review of 13 Nov 2026: R02 / R03 / R06 / R08).
Authoritative specification = the frozen CAMPAIGN_MANIFEST.json bound to the pre-execution CAMPAIGN_START.json (manifest sha256 AND the content hash of the complete
frozen source inventory; the ledger's first CAMPAIGN_START row must agree). There is NO amendment mechanism: a MANIFEST_AMENDMENT_* file is a provenance failure.
Every check is driven by ONE registry (cex/pac/registry.py): cohorts, arms, representations, validators.
Checks (every failure listed; exit nonzero on any):
  * identity: the manifest's candidate_artifact_hashes must be the COMPLETE required source inventory (registry.SOURCE_SCOPES: cex/pac + cex/newarm, cex/b0_frozen_v14,
    gbidi/supervise.py; .py/.cpp/.sh) and every hash must equal the file on disk; candidate workers must record every candidate-scope key; B0 workers their scope;
  * plan: no duplicate planned ids; exactly one receipt per planned cell; no foreign receipt; receipt fields equal the manifest's; finite nonnegative walls; timeliness RECOMPUTED;
  * process: COMPLETED needs supervisor rc 0 / outcome COMPLETED and an output file with the receipted sha256 (every arm);
  * candidate arms (validator uai_candidate): binding to the frozen input re-hashed on disk; nonce / seed / arm / epsilon / delta; shape; one-hot evidence; publication contract;
    END-TO-END certificate chain (pac-certificate-v4): reduction + partition re-derived from the ORIGINAL model; K from the rebuilt job;
      - PAC components: design bound to the FROZEN policy and the task-derived seeds; DETERMINISTIC REPLAY of the recorded design on the bound component model for the
        recorded number of trials must reproduce the sufficient statistics, frontier and resolved totals EXACTLY (statistics impossible under the law cannot be
        reproduced); the hulls INTERSECTED with the replayed deterministic bounds, the points and certifiers are re-derived and must equal the recorded rows;
      - deterministic covers (exact / partial) and zero proofs: ONE shared verifier (verify_cover): frontier rebuilt, bijection between frontier leaves and
        contribution records, every cell RE-EVALUATED (exact enumeration <= exact_leaf_max_completions, else the compiled kernel re-executed on the bound cell =
        the stated trusted-kernel boundary), the accumulators RE-ACCUMULATED in the recorded order and compared field by field, deterministic rows re-derived;
        a zero proof needs complete coverage (U_t = 0) and every re-derived upper mass equal to zero;
      - frozen executor routes re-executed; the lift of the VERIFIED rows and the frozen decimal publication must equal the worker's output;
  * native arms (validators h4_native / sf_native / cbi_native): binding to the packet / panel / instance, declared task, query shape and labels, requested width,
    guarantee, completed process, fresh attempt identity, deadline;
  * comparators (validator comparator_mar): output file + sha, UNGUARANTEED;
  * zero evidence: a timely, identity-bound, RE-DERIVED proof;
  * output: GATE_RESULT.json carries the CONTENT-ADDRESSED gated set (per cell: receipt sha256, output sha256, status, outcome, guarantee) and its digest; the reporter
    and the closeout must consume exactly that set.
Trust boundary (stated, not expanded): the compiled kernel's enclosure of a cell with more completions than exact_leaf_max_completions is trusted after RE-EXECUTION
on the bound cell; the PRNG's ideal independent unbiased bits are an assumption; the PAC event itself (a lawful realization containing the truth) is NOT verified.
Replay / re-evaluation work is charged to the checker: a replay exceeding the checker budget is a typed UNVERIFIABLE failure, never an acceptance.
    python cex/pac/gate.py <RD> [--manifest CAMPAIGN_MANIFEST.json] [--out GATE_RESULT.json] [--replay-factor 3.0]  -> exit 0 only if every check passes"""
import sys, os, json, hashlib, glob, math, time
HERE = os.path.dirname(os.path.abspath(__file__)); CODE = os.path.dirname(os.path.dirname(HERE))
for p in (os.path.join(CODE, 'cex', 'newarm'), HERE, CODE):
    if p not in sys.path: sys.path.insert(0, p)
sys.set_int_max_str_digits(0)
from fractions import Fraction as F
import core, registry
GATE_VERSION = 'pac-gate-v4 (2026-11-13 repair 3: replayed PAC construction, re-evaluated covers, registry validators, content-addressed gated set)'
CANDIDATE_ARMS = registry.CANDIDATE_ARMS; B0 = 'B0_FROZEN_V14'
REPLAY_FACTOR = 3.0            # checker budget per PAC component replay = REPLAY_FACTOR x the cell budget (charged to the checker; exceeding it is UNVERIFIABLE)


def sha(p):
    h = hashlib.sha256()
    with open(p, 'rb') as f:
        for b in iter(lambda: f.read(1 << 20), b''): h.update(b)
    return h.hexdigest()


def _frows(x): return [[(F(a), F(b)) for a, b in row] for row in x]
def _fpts(x): return [[F(a) for a in row] for row in x]
def _frac_str(x): return '%d/%d' % (x.numerator, x.denominator)
def _canon(x): return json.loads(json.dumps(x, default=str))


# ---------------- shared COVER / CONTRIBUTION verifier (exact cover, partial cover, zero proof)
def verify_cover(cm, cut, order_free, frontier, RT, expect_zero=False, deadline=None):
    """returns (failure message or None, verified dict(T_record, U_t, det_rows, ...)).
    1. the frontier is rebuilt from the recorded resolved leaves + extra expanded nodes; its U_t must equal the record (exact-cover / zero claims need U_t = 0);
    2. the contribution records must be in BIJECTION with the frontier's resolved leaves (same multiset, no duplicates, legal leaves);
    3. every cell is RE-EVALUATED on the bound component model: exact enumeration when the leaf has <= exact_leaf_max_completions completions, else the compiled
       kernel through the production Template (trusted-kernel boundary, stated); the recorded (B0_lo, B0_hi) must enclose the exact mass / equal the re-executed enclosure;
    4. the resolved totals are RE-ACCUMULATED from the re-derived contributions in the recorded order with the production Totals (directed insertion + directed rebase)
       and compared field by field (E, A_lo, A_hi, a_lo, a_hi, A_exact); 5. deterministic rows re-derived from the verified totals and the rebuilt U_t."""
    import engine, contrib
    try:
        cards = cm['cards']; cut = list(cut); fr = frontier or {}; RT = RT or {}
        if sorted(cut + list(order_free or [])) != list(range(len(cards))): return 'design cutset / order is not a partition of the component variables', None
        Tr = engine.Tree.rebuild(cm, cut, fr.get('resolved_leaves') or [], fr.get('extra_expanded') or [], deadline)
        if _frac_str(Tr.U_t) != fr.get('U_t'): return 'frontier record does not rebuild to the recorded U_t', None
        if expect_zero and Tr.U_t != 0: return 'zero / exact-cover claim but the rebuilt frontier is not closed (U_t > 0)', None
        leaves = [tuple(l) for l in (fr.get('resolved_leaves') or [])]
        if len(set(leaves)) != len(leaves): return 'duplicate resolved leaves in the frontier record', None
        for l in leaves:
            if len(l) != len(cut) or any(not (0 <= s_ < cards[v]) for s_, v in zip(l, cut)): return 'illegal resolved leaf %s' % (l,), None
        cells = RT.get('cells')
        if not isinstance(cells, list): return 'resolved totals without a contribution list', None
        cl = [tuple(x.get('leaf') or ()) for x in cells]
        if len(set(cl)) != len(cl): return 'duplicate contribution records', None
        if sorted(cl) != sorted(leaves): return 'contribution records are not in bijection with the frontier leaves (%d records, %d leaves)' % (len(cl), len(leaves)), None
        if expect_zero and not leaves and Tr.u_root != 0: return 'zero claim with no resolved cells but a positive root bound', None
        off = [0]
        for k in cards: off.append(off[-1] + k)
        tmpl = None; free_count = Tr.free_count; exact_leaf = free_count <= engine.POLICY['exact_leaf_max_completions']
        if not exact_leaf and cells: tmpl = engine.Template(cm, cut, list(order_free), deadline=deadline)
        T2 = engine.Totals(off[-1]); checked_exact = 0; checked_kernel = 0; A_lo = F(0); A_hi = F(0)
        for x in cells:
            if deadline is not None and time.monotonic() >= deadline: return 'UNVERIFIABLE: cover re-evaluation exceeded the checker budget', None
            leaf = tuple(x['leaf']); lo, hi = F(x['B0_lo']), F(x['B0_hi']); assign = dict(zip(cut, leaf))
            if lo < 0 or hi < lo: return 'inadmissible contribution bounds for cell %s' % (leaf,), None
            if exact_leaf:
                r = contrib.cell_exact(cm, assign, None, max_completions=engine.POLICY['exact_leaf_max_completions']); ex = r['B0'][0]
                if not (lo <= ex <= hi): return 'recorded cell mass enclosure does not contain the exact mass of cell %s' % (leaf,), None
                if (lo, hi) != (ex, ex): return 'recorded cell mass enclosure of the exactly enumerated cell %s is not the exact value' % (leaf,), None
                B0 = (ex, ex); rows_c = {v: r['B'][v] for v in range(len(cards)) if v not in assign}; checked_exact += 1
            else:
                B0, rows_c, _ctr = engine.kernel_cell(tmpl, assign, deadline, 3 * 1024 ** 3, core.rss_bytes())
                if (B0[0], B0[1]) != (lo, hi): return 'recorded cell mass enclosure differs from the re-executed kernel enclosure of cell %s' % (leaf,), None
                checked_kernel += 1
            if expect_zero and hi != 0: return 'zero claim but cell %s has positive upper mass' % (leaf,), None
            idx, rows_lo, rows_hi = engine.cell_contribution_rows(cards, cut, assign, B0, rows_c, off)
            T2.add_cell(leaf, B0[0], B0[1], rows_lo, rows_hi, idx); A_lo += B0[0]; A_hi += B0[1]
        rec2 = T2.record()
        if F(RT.get('A_exact_lo', '0')) != A_lo or F(RT.get('A_exact_hi', '0')) != A_hi: return 'recorded exact resolved mass differs from the sum of the re-derived cells', None
        if cells:
            for k in ('E', 'A_lo', 'A_hi'):
                if rec2.get(k) != RT.get(k): return 'resolved totals field %s differs from the re-accumulated value' % k, None
            if [float(v) for v in RT.get('a_lo') or []] != rec2['a_lo'] or [float(v) for v in RT.get('a_hi') or []] != rec2['a_hi']: return 'resolved query numerator totals differ from the re-accumulated contributions', None
        if expect_zero and A_hi != 0: return 'zero claim but the verified total upper mass is positive', None
        det_rows = engine.Totals.bounds_from_record(rec2, Tr.U_t, cards, off) if cells else None
        return None, dict(T_record=rec2, U_t=Tr.U_t, det_rows=det_rows, checked_exact=checked_exact, checked_kernel=checked_kernel, free_count=free_count)
    except contrib.CellStop as e: return 'UNVERIFIABLE: cell re-evaluation stopped (%s: %s)' % (e.kind, str(e.reason)[:60]), None
    except engine.EngineStop as e: return 'UNVERIFIABLE: %s' % str(e)[:80], None
    except (KeyError, TypeError, ValueError, ZeroDivisionError, AssertionError) as ex: return 'malformed cover certificate (%s: %s)' % (type(ex).__name__, str(ex)[:60]), None


def _records_equal(R, R2):
    """exact field-by-field equality of two sufficient-statistics records (floats compared as binary64 values, lists elementwise); returns the first differing key"""
    keys = ('n', 'positive_trials', 'zero_trials', 'U_root', 'K', 'alpha_range', 'alpha_variance', 'l_values', 'cards', 'b_lo', 'b_hi', 'e_lo', 'e_hi', 'a_lo', 'a_hi', 'c_lo', 'c_hi', 'd_lo', 'd_hi', 'A_lo', 'A_hi', 'ra_lo', 'ra_hi', 'A_exact_lo', 'A_exact_hi')
    for k in keys:
        a = R.get(k); b = R2.get(k)
        if isinstance(b, list) and b and isinstance(b[0], float): a = [float(x) for x in (a or [])] if isinstance(a, list) else a
        elif isinstance(b, float): a = float(a) if isinstance(a, (int, float)) and not isinstance(a, bool) else a
        if a != b: return k
    return None


def check_pac_certificate(w, c, man, model, fail, deadline_factor=REPLAY_FACTOR):
    """END-TO-END certificate verification for a candidate-arm COMPLETED worker output (candidate v4)"""
    import engine, reduction
    cert = w.get('certificate') or {}; cid = c['cell_id']
    if cert.get('certificate_version') != 'pac-certificate-v4':
        fail(cid, 'publication with a legacy / missing certificate schema (%s): UNVERIFIABLE by the v4 chain check' % cert.get('certificate_version')); return
    task = man.get('task') or {}; eps_t = F(str(task.get('epsilon', '1/200'))); delta = F(str(task.get('delta', '1/1000000')))
    if str(cert.get('epsilon')) != str(task.get('epsilon', '1/200')) or str(w.get('epsilon')) != str(task.get('epsilon', '1/200')): fail(cid, 'epsilon differs from the manifest task')
    if w.get('guarantee_type') == 'PAC':
        if str(cert.get('delta')) != str(task.get('delta', '1/1000000')) or str(w.get('delta')) != str(task.get('delta', '1/1000000')): fail(cid, 'delta differs from the manifest task')
    elif str(cert.get('delta')) != '0': fail(cid, 'deterministic certificate with nonzero delta')
    comps = cert.get('components') or []
    if not comps: fail(cid, 'certificate without components'); return
    cards0 = model['cards']; rm = None; decoder = None; partition = None
    if cert.get('reduced_model') is None:
        if not (len(comps) == 1 and comps[0].get('guarantee') == 'DETERMINISTIC' and comps[0].get('route') in ('forest', 'dag') and list(comps[0].get('variables') or []) == list(range(len(cards0)))): fail(cid, 'certificate without a reduced model but not a whole-model root route'); return
        rm = model; decoder = [dict(kind='identity', variable=v) for v in range(len(cards0))]; partition = [list(range(len(cards0)))]
        if cert.get('decoder') != decoder: fail(cid, 'root-route decoder is not the identity')
        comp_models = {tuple(range(len(cards0))): model}
    else:
        try: red = reduction.reduce(model, deadline=None)
        except Exception as ex: fail(cid, 'reduction re-derivation failed: %s' % str(ex)[:60]); return
        if red.get('status') != 'REDUCED': fail(cid, 're-derived reduction reports %s for a published cell' % red.get('status')); return
        rm = red['model']; decoder = red['decoder']; crm = cert['reduced_model']
        if list(crm.get('cards') or []) != list(rm['cards']) or [(tuple(f['scope']), [str(x) for x in f['values']]) for f in rm['factors']] != [(tuple(f['scope']), list(f['values'])) for f in crm.get('factors') or []]: fail(cid, 'certificate reduced model differs from the re-derived reduction'); return
        if _canon(cert.get('decoder')) != _canon(decoder): fail(cid, 'certificate decoder differs from the re-derived reduction decoder'); return
        try: split = core.components(rm, deadline=None)
        except Exception as ex: fail(cid, 'component split re-derivation failed: %s' % str(ex)[:60]); return
        partition = [old for old, _ in split]
        if [list(p) for p in (cert.get('partition') or [])] != [list(p) for p in partition]: fail(cid, 'certificate partition differs from the re-derived component split'); return
        comp_models = {tuple(old): cm for old, cm in split}
    K_expected = sum(rm['cards']) if cert.get('reduced_model') is not None else 0
    K = cert.get('K_total'); led = cert.get('delta_ledger') or {}
    if K != K_expected or led.get('coordinates') != K_expected: fail(cid, 'K_total %s differs from the sum of cardinalities of the re-derived reduced job (%d)' % (K, K_expected)); return
    verified_rows = [None] * len(rm['cards']); verified_pts = [None] * len(rm['cards']); pac_seen = False
    if [sorted(comp.get('variables') or []) for comp in comps] != [sorted(p) for p in partition]: fail(cid, 'component variable lists differ from the partition'); return
    for comp, old in zip(comps, partition):
        g = comp.get('guarantee'); route = str(comp.get('route', '')); ci = comp.get('component'); cm = comp_models[tuple(old)]; cards = cm['cards']
        ivx = comp.get('intervals_exact'); ptx = comp.get('points_exact')
        if ivx is None or ptx is None: fail(cid, 'component %s: exact rows missing' % ci); return
        try: rows = _frows(ivx); pts = _fpts(ptx)
        except Exception: fail(cid, 'component %s: unparseable exact rows' % ci); return
        if len(rows) != len(cards) or any(len(r_) != k or len(p_) != k for r_, p_, k in zip(rows, pts, cards)): fail(cid, 'component %s: exact rows shape differs from the component model' % ci); return
        if g == 'PAC':
            pac_seen = True; d = comp.get('design') or {}; R = comp.get('sufficient_statistics')
            if not d or not R: fail(cid, 'PAC component %s without design record / sufficient statistics' % ci); return
            try:
                if d.get('K_total') != K or R.get('K') != K: fail(cid, 'PAC component %s: K differs from the job ledger' % ci); return
                if F(d['alpha_range']) != delta / (2 * K) or F(d['alpha_variance']) != delta / (2 * K) or F(R['alpha_range']) != delta / (2 * K) or F(R['alpha_variance']) != delta / (2 * K): fail(cid, 'PAC component %s: per-coordinate alpha differs from delta/(2K)' % ci); return
                if F(d['delta_range']) != delta / 2 or F(d['delta_variance']) != delta / 2: fail(cid, 'PAC component %s: family deltas differ from delta/2' % ci); return
                bad = engine.design_binding_failures(d, engine.POLICY, c.get('seed'), int(ci) if isinstance(ci, int) else 0, eps_t)
                if bad: fail(cid, 'PAC component %s: %s' % (ci, bad[0])); return
                cut = d.get('cutset'); order = d.get('order_free')
                if not isinstance(cut, list) or not isinstance(order, list) or sorted(cut + order) != list(range(len(cards))): fail(cid, 'PAC component %s: design cutset / order is not a partition of the component variables' % ci); return
                T0 = engine.Tree(cm, cut)
                if F(d['U_root']) != T0.u_root or F(R['U_root']) != T0.u_root: fail(cid, 'PAC component %s: U_root differs from the factor-max root bound rebuilt from the component model and cutset' % ci); return
                if list(R.get('cards') or []) != list(cards): fail(cid, 'PAC component %s: statistics cards differ from the component' % ci); return
                n = R.get('n')
                if n != comp.get('trials') or not n: fail(cid, 'PAC component %s: n differs from trials' % ci); return
                # ---- cheap NECESSARY algebraic checks before the replay (a finite list of identities is never sufficient; the replay is the verification):
                # point mode without resolution: every trial has Y_j = T * 1{state_j} so sum Y_j^2 == sum Y_j T per coordinate -> the directed enclosures [c_lo, c_hi] and [d_lo, d_hi] must intersect
                if d.get('mode') == 'point' and not d.get('resolve'):
                    for j in range(len(R['c_lo'])):
                        if float(R['c_hi'][j]) < float(R['d_lo'][j]) or float(R['d_hi'][j]) < float(R['c_lo'][j]): fail(cid, 'PAC component %s: statistics violate the point-mode identity sum Y^2 = sum Y T at coordinate %d (impossible under the recorded law)' % (ci, j)); return
                if float(R['b_lo']) > n: fail(cid, 'PAC component %s: the lower denominator accumulator exceeds the trial count (T <= 1 in the dimensionless scale)' % ci); return
                # ---- DETERMINISTIC REPLAY of the recorded design on the bound component model (charged to the checker)
                budget = float(c.get('budget_s') or 20.0); dl = time.monotonic() + deadline_factor * budget
                rp = engine.replay_component(cm, d, n, K, deadline=dl)
                if rp.get('status') == 'DEADLINE' or str(rp.get('stats', {}).get('terminal')) == 'DEADLINE': fail(cid, 'PAC component %s: UNVERIFIABLE -- the design replay exceeded the checker budget (%.0f s)' % (ci, deadline_factor * budget)); return
                if rp.get('status') != 'PUBLISHED' or rp.get('guarantee') != 'PAC': fail(cid, 'PAC component %s: the replayed design does not publish a PAC result at %d trials (replay: %s / %s)' % (ci, n, rp.get('status'), rp.get('guarantee'))); return
                R2 = rp['stats']['sufficient_statistics']; bad_k = _records_equal(R, R2)
                if bad_k: fail(cid, 'PAC component %s: sufficient statistic %s is NOT reproduced by the replay of the recorded design (statistics not lawful for this construction)' % (ci, bad_k)); return
                if _canon(comp.get('frontier')) != _canon(rp['stats'].get('frontier')): fail(cid, 'PAC component %s: frontier record differs from the replay' % ci); return
                if _canon(comp.get('resolved_totals')) != _canon(rp['stats'].get('resolved_totals')): fail(cid, 'PAC component %s: resolved totals differ from the replay' % ci); return
                det = None
                if rp['stats'].get('resolved_cells', 0) > 0:
                    msg, ver = verify_cover(cm, cut, order, rp['stats']['frontier'], rp['stats']['resolved_totals'], expect_zero=False, deadline=dl)
                    if msg: fail(cid, 'PAC component %s: resolved region of the replay not verifiable: %s' % (ci, msg)); return
                    det = ver['det_rows']
                ok, hrows, hpts, chosen, widths, bU, vsets, compo = engine.hulls_from_record(R, eps_t, F(d['decimal_margin']), det_rows=det)
                if compo['used'] == 'EMPTY_INTERSECTION' or not ok: fail(cid, 'PAC component %s: REPLAY of the certificate (hulls ∩ deterministic bounds) does not certify' % ci); return
                cpr = comp.get('certifier_per_row') or []
                for v in range(len(cards)):
                    if hrows[v] != rows[v] or hpts[v] != pts[v] or chosen[v] != cpr[v]: fail(cid, 'PAC component %s: replayed row %d differs from the recorded exact rows' % (ci, v)); return
                if [rp['intervals'][v] for v in range(len(cards))] != rows or [rp['points'][v] for v in range(len(cards))] != pts: fail(cid, 'PAC component %s: the replay publishes different rows' % ci); return
            except (KeyError, TypeError, ValueError, ZeroDivisionError) as ex: fail(cid, 'PAC component %s: malformed certificate (%s)' % (ci, str(ex)[:60])); return
        elif g == 'DETERMINISTIC':
            if route.startswith('pac_'):
                d = comp.get('design') or {}; fr = comp.get('frontier') or {}; RT = comp.get('resolved_totals') or {}
                if 'uniform_factorless' in route:
                    if cm['factors'] or any(rows[v] != [(F(1, k), F(1, k))] * k for v, k in enumerate(cards)): fail(cid, 'component %s: factorless uniform claim does not match the component' % ci); return
                else:
                    cut = d.get('cutset'); order = d.get('order_free')
                    if not isinstance(cut, list): fail(cid, 'component %s: design cutset missing' % ci); return
                    budget = float(c.get('budget_s') or 20.0); dl = time.monotonic() + deadline_factor * budget
                    msg, ver = verify_cover(cm, cut, order or [], fr, RT, expect_zero=False, deadline=dl)
                    if msg: fail(cid, 'component %s: %s' % (ci, msg)); return
                    if 'exact_cover' in route and ver['U_t'] != 0: fail(cid, 'component %s: exact-cover claim but the verified frontier is not closed' % ci); return
                    if ver['det_rows'] is None: fail(cid, 'component %s: deterministic publication without a positive verified resolved mass' % ci); return
                    if ver['det_rows'] != rows: fail(cid, 'component %s: recorded deterministic rows differ from the bounds re-derived from the VERIFIED contributions and U_t' % ci); return
                    p_ = [engine.feasible_point(rows[v], eps_t - F(d['decimal_margin'])) for v in range(len(cards))]
                    if any(x is None for x in p_) or any(p_[v] != pts[v] for v in range(len(cards))): fail(cid, 'component %s: recorded points are not the feasible simplex points of the rows' % ci); return
            elif route in ('support', 'dag', 'stream', 'forest'):
                try:
                    if route == 'forest':
                        import forest; res = forest.solve(model, deadline=None, independent_replay=True); rr = res['intervals']; rp_ = res['points']
                    elif route == 'dag' and cert.get('reduced_model') is None:
                        import dag; res = dag.execute_plan(dag.plan(model, deadline=None), deadline=None); rr = res['intervals']; rp_ = res['points']
                    else:
                        plan = core._discover_component(cm, None, route); res = core._execute_component(plan, None); rr = res['intervals']; rp_ = res.get('points') or [[(lo + hi) / 2 for lo, hi in row] for row in rr]
                    rr = [[(F(a), F(b)) for a, b in row] for row in rr]; rp_ = [[F(x) for x in row] for row in rp_]
                    if rr != rows or rp_ != pts: fail(cid, 'component %s: re-execution of the frozen %s route does not reproduce the recorded rows' % (ci, route)); return
                except Exception as ex: fail(cid, 'component %s: frozen route %s re-execution failed (%s)' % (ci, route, str(ex)[:60])); return
            else: fail(cid, 'component %s: unknown deterministic route %s' % (ci, route)); return
            core.verify_output(rows, pts, eps_t)
        else: fail(cid, 'component %s with guarantee %s' % (ci, g)); return
        for v, row, q in zip(old, rows, pts): verified_rows[v] = row; verified_pts[v] = q
    if w.get('guarantee_type') == 'PAC' and not pac_seen: fail(cid, 'PAC guarantee without any PAC component'); return
    if w.get('guarantee_type') == 'DETERMINISTIC' and pac_seen: fail(cid, 'DETERMINISTIC guarantee with a PAC component'); return
    try:
        if cert.get('reduced_model') is None: LI, LP = verified_rows, verified_pts
        else: LI, LP = reduction.lift(dict(status='REDUCED', decoder=decoder), verified_rows, verified_pts)
        if [[(str(a), str(b)) for a, b in row] for row in LI] != [[tuple(x) for x in row] for row in cert['lifted_intervals_exact']] or [[str(x) for x in row] for row in LP] != [list(row) for row in cert['lifted_points_exact']]: fail(cid, 'the lift of the VERIFIED component rows differs from the certificate lifted rows'); return
        core.verify_output(LI, LP, eps_t); di, dp = core.publish(LI, LP, epsilon=eps_t)
        if di != w.get('intervals') or dp != w.get('points'): fail(cid, 'the published decimals are not the frozen publication of the VERIFIED lifted rows'); return
    except Exception as ex: fail(cid, 'chain verification: %s' % str(ex)[:80]); return


def verify_zero_proof(model, proof, seed=None, deadline=None):
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
            cut = proof.get('cutset') or []; order = [v for v in range(len(cm['cards'])) if v not in cut]
            msg, ver = verify_cover(cm, cut, order, proof.get('frontier') or {}, proof.get('resolved_totals') or {}, expect_zero=True, deadline=deadline)
            return msg
        return 'unknown proof kind %s' % kind
    except Exception as ex: return 're-derivation error %s: %s' % (type(ex).__name__, str(ex)[:60])


# ---------------- native validators (registry-driven; each binds its own contract)
def _fresh_attempt(path_in_attempt, r):
    """the output must lie inside attempt_<nonce> of THIS receipt"""
    p = os.path.abspath(path_in_attempt)
    while p and p != os.path.dirname(p):
        b = os.path.basename(p)
        if b.startswith('attempt_'): return b[len('attempt_'):] == r.get('nonce')
        p = os.path.dirname(p)
    return False


def validate_h4_native(RD, c, r, w_path, fail):
    cid = c['cell_id']
    try: b = json.load(open(w_path))
    except Exception: fail(cid, 'H4 bundle unreadable'); return False
    packet = c.get('packet'); fz = os.path.join(packet or '', 'inputs', 'FROZEN_NODES.json')
    if not packet or not os.path.exists(fz): fail(cid, 'H4 packet FROZEN_NODES.json missing on disk'); return False
    if sha(fz) != c.get('model_sha256'): fail(cid, 'H4 packet FROZEN_NODES.json differs from the frozen manifest hash'); return False
    Fz = json.load(open(fz)); want_nodes = sorted((d['source_sign'], d['processed_ordinal_1based'], tuple(d['positive_node'])) for d in Fz['nodes'])
    if b.get('arm') != c.get('native_arm') or 'H4_NATIVE_%s' % b.get('arm') != c['arm']: fail(cid, 'H4 bundle arm differs from the cell'); return False
    if b.get('repetition') != c.get('replicate'): fail(cid, 'H4 bundle repetition differs from the cell replicate'); return False
    nodes = b.get('nodes') or []
    if len(nodes) != 6 or sorted((n.get('source_sign'), n.get('ordinal'), tuple(n.get('node') or ())) for n in nodes) != want_nodes: fail(cid, 'H4 bundle nodes differ from the frozen six nodes'); return False
    if not all(n.get('verdict') == 'VERIFIED' for n in nodes) or b.get('all_verified') is not True: fail(cid, 'H4 bundle not fully verified'); return False
    if not _fresh_attempt(w_path, r): fail(cid, 'H4 output is not inside the fresh attempt directory of this receipt'); return False
    for n in nodes:
        vp = os.path.join(os.path.dirname(w_path), n['key'], 'verdict.json')
        if not os.path.exists(vp): fail(cid, 'H4 node %s without a verdict record' % n['key']); return False
        v = json.load(open(vp))
        if v.get('verdict') != 'VERIFIED' or v.get('failed_checks') or v.get('arm') != b.get('arm'): fail(cid, 'H4 node %s verdict record not VERIFIED / wrong arm' % n['key']); return False
        ch = v.get('checks') or {}
        if not ch or not all(x is True for x in ch.values()): fail(cid, 'H4 node %s: a check is not true' % n['key']); return False
    if not isinstance(b.get('complete_wall_s'), (int, float)) or b['complete_wall_s'] > float(c['budget_s']): fail(cid, 'H4 bundle complete wall exceeds the cell budget'); return False
    if r.get('guarantee_type') != 'DETERMINISTIC': fail(cid, 'H4 receipt guarantee must be DETERMINISTIC'); return False
    return True


def validate_sf_native(RD, c, r, w_path, fail):
    cid = c['cell_id']
    try: w = json.load(open(w_path))
    except Exception: fail(cid, 'SF output unreadable'); return False
    if w.get('mode') != 'select' or w.get('status') != 'OK': fail(cid, 'SF output mode / status (%s / %s)' % (w.get('mode'), w.get('status'))); return False
    mp = c.get('model_path') or ''
    if w.get('panel') != os.path.basename(mp) or w.get('input_sha256') != c.get('model_sha256') or not os.path.exists(mp) or sha(mp) != c.get('model_sha256'): fail(cid, 'SF output panel / input hash do not bind to the frozen panel'); return False
    try:
        if F(str(w.get('r'))) != F(str(c.get('sf_r'))) or F(str(w.get('eps'))) != F(str(c.get('sf_eps'))): fail(cid, 'SF coupling / requested width differ from the cell'); return False
    except Exception: fail(cid, 'SF coupling / width unparseable'); return False
    if (w.get('checker') or {}).get('status') != 'VERIFIED': fail(cid, 'SF independent checker not VERIFIED'); return False
    n = w.get('n'); pub = w.get('published'); ivx = w.get('intervals_exact')
    if not (isinstance(n, int) and isinstance(pub, list) and isinstance(ivx, list) and len(pub) == n == len(ivx)): fail(cid, 'SF publication shape differs from the panel dimension'); return False
    try:
        from sf import core as SFC
        q = 1 << SFC.GRID_BITS; wmax = F(0)
        for (lg, hg), (lo, hi) in zip(pub, ivx):
            lg = int(lg); hg = int(hg); lo = F(lo); hi = F(hi)
            if not (0 <= lg <= hg <= q and F(lg, q) <= lo <= hi <= F(hg, q)): fail(cid, 'SF published grid interval does not enclose its exact interval'); return False
            wmax = max(wmax, F(hg - lg, q))
        eps_req = F(str(c['sf_eps']))
        if wmax > eps_req or not (w.get('width_met') or {}).get(str(eps_req)): fail(cid, 'SF requested width %s not met (max %s)' % (eps_req, wmax)); return False
        if F(str(w.get('max_width'))) != wmax: fail(cid, 'SF recorded max width differs from the published intervals'); return False
    except Exception as ex: fail(cid, 'SF publication malformed (%s)' % str(ex)[:60]); return False
    if not isinstance(w.get('child_wall_s'), (int, float)) or w['child_wall_s'] > float(c['budget_s']): fail(cid, 'SF child wall exceeds the cell budget'); return False
    if not _fresh_attempt(w_path, r): fail(cid, 'SF output is not inside the fresh attempt directory of this receipt'); return False
    if r.get('guarantee_type') != 'DETERMINISTIC': fail(cid, 'SF receipt guarantee must be DETERMINISTIC'); return False
    return True


def validate_cbi_native(RD, c, r, w_path, fail):
    cid = c['cell_id']
    try: w = json.load(open(w_path))
    except Exception: fail(cid, 'CBI output unreadable'); return False
    if w.get('status') != 'CERTIFIED': fail(cid, 'CBI output status %s' % w.get('status')); return False
    mp = c.get('model_path') or ''
    if not os.path.exists(mp) or sha(mp) != c.get('model_sha256'): fail(cid, 'CBI frozen instance file missing or differs from the manifest hash'); return False
    try:
        from cbi import model as M
        canon = M.Model.from_json(json.load(open(mp))).sha256()          # the cbi CLI records the CANONICAL-form hash of the instance (external ids restored); re-derived here from the frozen file
    except Exception as ex: fail(cid, 'CBI frozen instance unparseable (%s)' % str(ex)[:60]); return False
    if w.get('model_sha256') not in (canon, c.get('model_sha256')): fail(cid, 'CBI output model hash binds neither the frozen file nor its canonical form'); return False
    ids = (w.get('id_map') or {}).get('external_ids')
    try:
        inst = M.Model.from_json(json.load(open(mp))); want_ids = [inst.ext(i) for i in sorted(inst.blocks)]
    except Exception: want_ids = None
    if want_ids is not None and (ids is None or sorted(ids) != sorted(want_ids)): fail(cid, 'CBI output block id map differs from the frozen instance (%s vs %s)' % (ids, want_ids)); return False
    if want_ids is not None and sorted(int(k) for k in (w.get('intervals') or {}).keys() if str(k).lstrip('-').isdigit()) != sorted(want_ids): fail(cid, 'CBI output query keys are not the instance block ids'); return False
    try:
        if F(str(w.get('requested_width'))) != F(1, 100): fail(cid, 'CBI requested width is not the native 1/100'); return False
    except Exception: fail(cid, 'CBI requested width unparseable'); return False
    sq = w.get('statuses_per_query') or {}; iv = w.get('intervals') or {}
    if not sq or not iv or any(v != 'CERTIFIED' for v in sq.values()) or set(sq) != set(iv): fail(cid, 'CBI per-query statuses / intervals incomplete'); return False
    if not _fresh_attempt(w_path, r): fail(cid, 'CBI output is not inside the fresh attempt directory of this receipt'); return False
    if r.get('guarantee_type') != 'DETERMINISTIC': fail(cid, 'CBI completed with guarantee %s' % r.get('guarantee_type')); return False
    return True


# ---------------- main
def main(RD, manifest_name='CAMPAIGN_MANIFEST.json', out_path=None, replay_factor=REPLAY_FACTOR):
    RD = os.path.abspath(RD); failures = []; t_gate = time.monotonic()
    def fail(cid, msg): failures.append((cid, msg))
    mp = os.path.join(RD, manifest_name)
    if not os.path.exists(mp): fail('*', 'manifest %s missing' % manifest_name); return _write(RD, out_path, dict(gate_version=GATE_VERSION, failures=failures, gate_passed=False))
    man = json.load(open(mp)); mh = sha(mp)
    ch = man.get('candidate_artifact_hashes') or {}
    ah = hashlib.sha256(json.dumps(ch, sort_keys=True).encode()).hexdigest() if ch else None
    # ---- pre-execution START binding + ledger (manifest sha AND frozen-identity content hash)
    sp = os.path.join(RD, 'CAMPAIGN_START.json')
    if not os.path.exists(sp): fail('*', 'CAMPAIGN_START.json missing (no pre-execution binding of the manifest)')
    else:
        st = json.load(open(sp))
        if st.get('manifest_sha256') != mh: fail('*', 'CAMPAIGN_START manifest sha256 %s differs from the manifest file on disk %s' % (str(st.get('manifest_sha256'))[:16], mh[:16]))
        if st.get('manifest') not in (None, manifest_name): fail('*', 'CAMPAIGN_START names a different manifest file')
        if st.get('artifact_hashes_sha256') != ah: fail('*', 'CAMPAIGN_START does not bind the content hash of the frozen source inventory')
    lp = os.path.join(RD, 'PAC_LEDGER.jsonl'); first_start = None
    if os.path.exists(lp):
        for line in open(lp):
            if not line.strip(): continue
            rr = json.loads(line)
            if rr.get('kind') == 'CAMPAIGN_START': first_start = rr; break
        if first_start is None: fail('*', 'ledger without a CAMPAIGN_START row')
        else:
            if first_start.get('manifest_sha256') != mh: fail('*', 'ledger CAMPAIGN_START manifest sha256 differs from the manifest on disk')
            if first_start.get('artifact_hashes_sha256') != ah: fail('*', 'ledger CAMPAIGN_START does not bind the frozen source inventory content hash')
    else: fail('*', 'PAC_LEDGER.jsonl missing')
    if glob.glob(os.path.join(RD, 'MANIFEST_AMENDMENT_*')): fail('*', 'artifact amendment files present: the v4 frozen identity is immutable (no amendment mechanism)')
    # ---- frozen source identity: COMPLETE required inventory, equal to the files on disk
    want = registry.source_inventory(CODE)
    if not isinstance(ch, dict) or not ch or any('/' not in k for k in ch): fail('*', 'manifest candidate_artifact_hashes must be a per-directory map'); ch = {}
    missing_keys = sorted(k for k in want if k not in ch); extra_keys = sorted(k for k in ch if k not in want)
    if missing_keys: fail('*', 'frozen source inventory INCOMPLETE: %d required sources missing (e.g. %s)' % (len(missing_keys), missing_keys[0]))
    if extra_keys: fail('*', 'frozen source inventory lists %d sources that are not in the required scopes (e.g. %s)' % (len(extra_keys), extra_keys[0]))
    differ = sorted(k for k in want if k in ch and ch[k] != want[k])
    if differ: fail('*', 'frozen source %s differs from the file on disk (%d differ)' % (differ[0], len(differ)))
    frozen_candidate = {k: v for k, v in ch.items() if registry.scope_of_key(k) == 'candidate'}
    frozen_b0 = {k: v for k, v in ch.items() if registry.scope_of_key(k) == 'b0_frozen_v14'}
    # ---- plan integrity
    ids = [c['cell_id'] for c in man['cells']]
    if len(ids) != len(set(ids)): fail('*', 'duplicate planned cell ids in the manifest: %d duplicates' % (len(ids) - len(set(ids))))
    cells = {c['cell_id']: c for c in man['cells']}
    for c in man['cells']:
        if c['arm'] not in registry.ARMS: fail(c['cell_id'], 'planned arm %s is not in the registry' % c['arm'])
        if c['cohort'] not in registry.COHORTS: fail(c['cell_id'], 'planned cohort %s is not in the registry' % c['cohort'])
    receipts = {}
    for rp in glob.glob(os.path.join(RD, 'cells', '*', 'receipt.json')):
        r = json.load(open(rp)); cid = r.get('cell_id')
        if cid in receipts: fail(cid, 'duplicate receipt: %s and %s' % (receipts[cid]['_path'], rp)); continue
        r['_path'] = rp; r['_sha'] = sha(rp); receipts[cid] = r
    for cid in cells:
        if cid not in receipts: fail(cid, 'planned cell without receipt (NOT_RUN)')
    for cid in receipts:
        if cid not in cells: fail(cid, 'receipt for a cell not in the frozen manifest')
    task = man.get('task') or {}; EPS = F(str(task.get('epsilon', '1/200'))); models = {}; checked = 0; gated = 0; pac_verified = 0; gated_set = []
    for cid in sorted(receipts):
        r = receipts[cid]; c = cells.get(cid)
        if not c: continue
        gated_set.append(dict(cell_id=cid, receipt_sha256=r['_sha'], output_sha256=r.get('output_sha256'), status=r.get('status'), outcome=r.get('outcome'), guarantee=r.get('guarantee_type'), arm=c['arm'], cohort=c['cohort'], budget_s=c['budget_s'], case_id=c['case_id'], replicate=c['replicate']))
        for k in ('case_id', 'arm', 'replicate', 'budget_s', 'seed', 'model_sha256', 'evidence_sha256', 'cohort'):
            if r.get(k) != c.get(k): fail(cid, 'receipt %s differs from the manifest' % k)
        wall = r.get('launch_relative_wall_s'); timely = isinstance(wall, (int, float)) and not isinstance(wall, bool) and wall == wall and 0 <= wall <= float(c['budget_s'])
        if not (isinstance(wall, (int, float)) and not isinstance(wall, bool) and 0 <= wall < float('inf')): fail(cid, 'receipt wall is not a finite nonnegative number (%s)' % wall)
        sup = r.get('supervisor') or {}; arm = c['arm']; validator = registry.validator_of(arm)
        wp = os.path.join(RD, r['worker_output']) if r.get('worker_output') else None
        if r.get('status') == 'COMPLETED':
            checked += 1
            if sup.get('rc') != 0: fail(cid, 'COMPLETED with supervisor rc %s' % sup.get('rc'))
            if sup.get('outcome') != 'COMPLETED': fail(cid, 'COMPLETED with supervisor outcome %s' % sup.get('outcome'))
            if not timely: fail(cid, 'COMPLETED but recomputed launch-relative wall %s > budget %s' % (wall, c['budget_s']))
            if r.get('outcome') != 'PUBLISHED': fail(cid, 'COMPLETED but outcome %s' % r.get('outcome'))
            if validator == 'comparator_mar':
                cmpr = r.get('comparator') or {}; of = cmpr.get('output_file')
                if not of or not os.path.exists(of): fail(cid, 'COMPLETED comparator without its output file'); continue
                if sha(of) != cmpr.get('output_sha256'): fail(cid, 'comparator output sha256 differs from the receipt')
                if r.get('guarantee_type') != 'UNGUARANTEED': fail(cid, 'comparator completed with guarantee %s' % r.get('guarantee_type'))
                gated += 1; continue
            if not wp or not os.path.exists(wp): fail(cid, 'COMPLETED without a worker output file'); continue
            if sha(wp) != r.get('output_sha256'): fail(cid, 'worker output sha256 differs from the receipt'); continue
            if validator == 'h4_native':
                if validate_h4_native(RD, c, r, wp, fail): gated += 1
                continue
            if validator == 'sf_native':
                if validate_sf_native(RD, c, r, wp, fail): gated += 1
                continue
            if validator == 'cbi_native':
                if validate_cbi_native(RD, c, r, wp, fail): gated += 1
                continue
            if validator != 'uai_candidate': fail(cid, 'no validator for arm %s' % arm); continue
            w = json.load(open(wp))
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
                missing = [k for k in frozen_candidate if k not in cs]; differ_ = [k for k in frozen_candidate if k in cs and cs[k] != frozen_candidate[k]]
                if missing: fail(cid, 'worker candidate source identity incomplete: %d frozen sources not recorded (e.g. %s)' % (len(missing), missing[0]))
                if differ_: fail(cid, 'worker candidate source %s differs from the frozen artifact' % differ_[0])
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
                nf = len(failures); check_pac_certificate(w, c, man, model, fail, deadline_factor=replay_factor)
                if len(failures) == nf and w.get('guarantee_type') == 'PAC': pac_verified += 1
            gated += 1
        else:
            if r.get('outcome') == 'PUBLISHED': fail(cid, 'non-COMPLETED receipt with outcome PUBLISHED')
            if r.get('outcome') == 'PROVED_ZERO_EVIDENCE':
                if not timely: fail(cid, 'zero-evidence claim after the budget (late proof is not a timely result)')
                if sup.get('rc') != 0 or 'KILL' in str(sup.get('outcome')): fail(cid, 'zero-evidence claim with supervisor rc %s / outcome %s' % (sup.get('rc'), sup.get('outcome')))
                if arm in CANDIDATE_ARMS:
                    if not wp or not os.path.exists(wp): fail(cid, 'zero-evidence claim without a worker output')
                    elif sha(wp) != r.get('output_sha256'): fail(cid, 'zero-evidence worker output sha256 differs from the receipt')
                    else:
                        w = json.load(open(wp))
                        if w.get('status') != 'STOPPED' or w.get('outcome') != 'PROVED_ZERO_EVIDENCE' or w.get('late_proof'): fail(cid, 'zero-evidence claim without a recorded timely proof')
                        if w.get('nonce') != r.get('nonce') or w.get('seed') != c.get('seed') or w.get('arm') != arm: fail(cid, 'zero-evidence output nonce / seed / arm differ from the cell')
                        cs = w.get('candidate_sources') or {}
                        if any(k not in cs or cs[k] != v for k, v in frozen_candidate.items()): fail(cid, 'zero-evidence output source identity incomplete or differs from the frozen artifact')
                        mpth = c.get('model_path')
                        if not mpth or not os.path.exists(mpth): fail(cid, 'frozen input file missing on disk')
                        else:
                            if mpth not in models: models[mpth] = core.read_uai(mpth)
                            model, binding = models[mpth]
                            if binding.get('model_sha256') != c.get('model_sha256') or binding.get('evidence_sha256') != c.get('evidence_sha256') or w.get('binding') != binding: fail(cid, 'zero-evidence output binding differs from the frozen input')
                            else:
                                msg = verify_zero_proof(model, w.get('zero_evidence_proof'), seed=c.get('seed'), deadline=time.monotonic() + replay_factor * float(c['budget_s']))
                                if msg: fail(cid, 'zero-evidence proof NOT re-derivable: %s' % msg)
                elif arm == B0:
                    if not wp or not os.path.exists(wp): fail(cid, 'zero-evidence claim without a worker output')
                elif r.get('guarantee_type') in ('PAC', 'DETERMINISTIC'): fail(cid, 'comparator / native zero outcome cannot carry a guarantee (underflow is indistinguishable)')
            elif r.get('guarantee_type') in ('PAC', 'DETERMINISTIC'): fail(cid, 'guarantee claimed without publication')
    gs = hashlib.sha256(json.dumps(gated_set, sort_keys=True).encode()).hexdigest()
    res = dict(gate_version=GATE_VERSION, manifest=manifest_name, manifest_sha256=mh, artifact_hashes_sha256=ah, planned=len(cells), receipts=len(receipts), completed_checked=checked, completed_gated=gated, pac_certificates_replayed=pac_verified, failures=failures, gate_passed=not failures, gated_set=gated_set, gated_set_sha256=gs, gate_wall_s=round(time.monotonic() - t_gate, 3), replay_factor=replay_factor)
    return _write(RD, out_path, res)


def _write(RD, out_path, res):
    out_path = out_path or os.path.join(RD, 'GATE_RESULT.json')
    json.dump(res, open(out_path, 'w'), indent=1); print(json.dumps({k: res.get(k) for k in ('gate_version', 'planned', 'receipts', 'completed_checked', 'completed_gated', 'pac_certificates_replayed', 'gate_passed', 'gated_set_sha256')}))
    for f in res['failures'][:40]: print('  ', f)
    if len(res['failures']) > 40: print('   ... %d more failures' % (len(res['failures']) - 40))
    return 0 if res['gate_passed'] else 1


if __name__ == '__main__':
    mn = sys.argv[sys.argv.index('--manifest') + 1] if '--manifest' in sys.argv else 'CAMPAIGN_MANIFEST.json'; op = sys.argv[sys.argv.index('--out') + 1] if '--out' in sys.argv else None
    rf = float(sys.argv[sys.argv.index('--replay-factor') + 1]) if '--replay-factor' in sys.argv else REPLAY_FACTOR
    sys.exit(main(sys.argv[1], mn, op, rf))
