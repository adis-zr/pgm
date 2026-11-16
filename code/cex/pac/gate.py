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
    guarantee, completed process, fresh attempt identity, deadline; the native checkers are RE-RUN with their PREMISES enforced (v4.2: SF radius / degree inside the
    reconstructed domain and bound to the route label; H4 witnesses REGENERATED from the frozen node and compared byte for byte, kernels RE-EXECUTED, node weights /
    masses / counts DERIVED from the frozen task); SF / CBI checkers run in an ISOLATED child under a hard timeout;
  * comparators (validator comparator_mar): adapter packet bound to arm / nonce / task hashes / budget / output; WELL-FORMED complete simplex answer for the ORIGINAL
    model (an incomplete answer is never a publication); approximation error is diagnostic only (v4.2);
  * task dependency set (v4.2): model, .evid (present / absent), blocks metadata, packets, witnesses, kernels, adapter packets are hashed into the gated set; report and
    closeout re-hash the SAME enumerated set (gate.task_dependencies);
  * execution semantics (v4.2): ONE predicate (registry.execution_semantics_failure) for statistical publications, deterministic covers, factorless, frozen, root and
    zero-proof families; resolution permitted only by the planned arm (or the empty-cutset closure); design, frontier and contribution records must agree;
  * resource contract (v4.2): every proof route receives the finite allowance; the clock is checked before EVERY accepting return and once more before the gate accepts;
  * identity (v4.2): a required artifact with a null identity never qualifies a manifest planning an arm that needs it; unneeded absent artifacts are listed as unavailable;
  * zero evidence: a timely, identity-bound, RE-DERIVED proof;
  * output: GATE_RESULT.json carries the CONTENT-ADDRESSED gated set (per cell: receipt sha256, output sha256, status, outcome, guarantee) and its digest; the reporter
    and the closeout must consume exactly that set.
Trust boundary (stated, not expanded): the compiled kernel's enclosure of a cell with more completions than exact_leaf_max_completions is trusted after RE-EXECUTION
on the bound cell; the PRNG's ideal independent unbiased bits are an assumption; the PAC event itself (a lawful realization containing the truth) is NOT verified.
Replay / re-evaluation work is charged to the checker: a replay exceeding the checker budget is a typed UNVERIFIABLE failure, never an acceptance.
    python cex/pac/gate.py <RD> [--manifest CAMPAIGN_MANIFEST.json] [--out GATE_RESULT.json] [--replay-factor 3.0]  -> exit 0 only if every check passes"""
import sys, os, json, hashlib, glob, math, time, subprocess, tempfile, shutil
HERE = os.path.dirname(os.path.abspath(__file__)); CODE = os.path.dirname(os.path.dirname(HERE))
for p in (os.path.join(CODE, 'cex', 'newarm'), HERE, CODE):
    if p not in sys.path: sys.path.insert(0, p)
sys.set_int_max_str_digits(0)
from fractions import Fraction as F
import core, registry
GATE_VERSION = 'pac-gate-v4.3 (2026-11-15 repair 6: zero-dimensional reduced jobs verified through the re-derived reduction, ONE effective evidence-path resolver, comparator normalization contract with positive mass and digit-derived tolerance capped at epsilon; v4.2 repair 5: native proof premises + task binding (SF radius domain, H4 witness regeneration / kernel re-execution / derived node weights), complete dependency set incl. .evid / blocks / adapter packets, well-formed task-bound comparator answers, ONE execution-semantics predicate for every terminal family, deadlines on every proof route with isolated native checkers and post-acceptance clock checks, null identities refused)'
CANDIDATE_ARMS = registry.CANDIDATE_ARMS; B0 = 'B0_FROZEN_V14'
REPLAY_FACTOR = 3.0            # checker budget per PAC component replay = REPLAY_FACTOR x the cell budget (charged to the checker; exceeding it is UNVERIFIABLE)
GATE_BUDGET_S = None           # aggregate checker budget for the whole gate run (None = unbounded only when the caller supervises; finalize_v4 passes --gate-budget-s)
class GateBudgetExhausted(Exception): pass
_evidence = {}                 # evidence files consumed by the validators during one gate run: path -> sha256 (hashed into the gated set)


def sha(p):
    h = hashlib.sha256()
    with open(p, 'rb') as f:
        for b in iter(lambda: f.read(1 << 20), b''): h.update(b)
    return h.hexdigest()


_cell_paths = set()            # evidence paths consumed while checking the CURRENT cell (v4.2: recorded per cell even when an earlier cell consumed the same file)


def _ev(path):
    """record an evidence file consumed by a validator (hashed into the gated set; the report / closeout re-hash the same files)"""
    p = os.path.abspath(path); _evidence[p] = sha(p) if os.path.exists(p) else None; _cell_paths.add(p); return _evidence[p]


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
    except (MemoryError, OverflowError, RecursionError) as e: return 'UNVERIFIABLE: checker resource failure %s' % type(e).__name__, None
    except GateBudgetExhausted: raise
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
    # ---- ZERO-DIMENSIONAL remaining job (sixth review F01): an EMPTY component list is legal ONLY when the certificate carries a reduced model and the RE-DERIVED reduction of
    # the ORIGINAL model proves that every variable is fixed (reduced cards [], partition []): the answer is then the decoder's fixed rows, lifted below like every other job
    # (K_total = 0, no PAC component). An empty list without a reduced model, or with a re-derived reduced job that still has variables, is refused.
    if not comps and cert.get('reduced_model') is None: fail(cid, 'certificate without components and without a reduced model (not a zero-dimensional job, not a root route)'); return
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
        if not comps:
            if rm['cards'] or partition: fail(cid, 'certificate without components but the re-derived reduced job still has %d variables in %d components' % (len(rm['cards']), len(partition))); return
            if any(d_.get('kind') != 'fixed' for d_ in decoder): fail(cid, 'zero-dimensional job whose re-derived decoder is not all-fixed'); return
            if w.get('guarantee_type') != 'DETERMINISTIC' or (cert.get('delta_ledger') or {}).get('components_pac') not in (0, None): fail(cid, 'zero-dimensional job must be a DETERMINISTIC publication with no PAC component'); return
    K_expected = sum(rm['cards']) if cert.get('reduced_model') is not None else 0
    K = cert.get('K_total'); led = cert.get('delta_ledger') or {}
    if K != K_expected or led.get('coordinates') != K_expected: fail(cid, 'K_total %s differs from the sum of cardinalities of the re-derived reduced job (%d)' % (K, K_expected)); return
    verified_rows = [None] * len(rm['cards']); verified_pts = [None] * len(rm['cards']); pac_seen = False
    if [sorted(comp.get('variables') or []) for comp in comps] != [sorted(p) for p in partition]: fail(cid, 'component variable lists differ from the partition'); return
    sem_arm = registry.ARM_SEMANTICS.get(c['arm']) or {}
    for comp_index, (comp, old) in enumerate(zip(comps, partition)):
        g = comp.get('guarantee'); route = str(comp.get('route', '')); ci = comp.get('component'); cm = comp_models[tuple(old)]; cards = cm['cards']
        if ci != comp_index: fail(cid, 'component %s: index differs from its position %d in the verified partition' % (ci, comp_index)); return
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
                if ci != comp_index: fail(cid, 'PAC component %s: component index differs from its position %d in the verified partition' % (ci, comp_index)); return
                bad = engine.design_binding_failures(d, engine.POLICY, c.get('seed'), comp_index, eps_t)
                if bad: fail(cid, 'PAC component %s: %s' % (ci, bad[0])); return
                fr_ = comp.get('frontier') or {}; RT_ = comp.get('resolved_totals') or {}
                bad_sem = registry.execution_semantics_failure(c['arm'], 'pac', route=route, design=d, resolved_leaves=len(fr_.get('resolved_leaves') or []), contribution_cells=len(RT_.get('cells') or []), resolved_cells=comp.get('resolved_cells'))
                if bad_sem: fail(cid, 'PAC component %s: EXECUTION SEMANTICS of the planned arm %s violated: %s' % (ci, c['arm'], bad_sem)); return
                if cert.get('arm') != c['arm']: fail(cid, 'certificate arm %s differs from the planned arm %s' % (cert.get('arm'), c['arm'])); return
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
                budget = float(c.get('budget_s') or 20.0); dl = _deadline(deadline_factor * budget)
                try: rp = engine.replay_component(cm, d, n, K, deadline=dl)
                except engine.EngineStop as e: fail(cid, 'PAC component %s: UNVERIFIABLE -- the design replay stopped (%s) within the checker budget %.3g s' % (ci, str(e)[:60], deadline_factor * budget)); return
                except (MemoryError, OverflowError, RecursionError) as e: fail(cid, 'PAC component %s: UNVERIFIABLE -- checker resource failure %s during the replay' % (ci, type(e).__name__)); return
                if rp.get('status') == 'DEADLINE' or str(rp.get('stats', {}).get('terminal')) == 'DEADLINE': fail(cid, 'PAC component %s: UNVERIFIABLE -- the design replay exceeded the checker budget (%.3g s)' % (ci, deadline_factor * budget)); return
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
            if cert.get('arm') != c['arm']: fail(cid, 'certificate arm %s differs from the planned arm %s' % (cert.get('arm'), c['arm'])); return
            d = comp.get('design') or {}; fr = comp.get('frontier') or {}; RT = comp.get('resolved_totals') or {}
            # ---- ONE execution-semantics predicate for EVERY deterministic terminal family (fifth review R04): cover (exact / partial), factorless, frozen executor route, whole-model root route
            if route.startswith('pac_') and 'uniform_factorless' in route: family = 'factorless'
            elif route.startswith('pac_'): family = 'cover'
            elif cert.get('reduced_model') is None: family = 'root'
            else: family = 'frozen'
            bad_sem = registry.execution_semantics_failure(c['arm'], family, route=route, design=d, resolved_leaves=len(fr.get('resolved_leaves') or []), contribution_cells=len(RT.get('cells') or []), resolved_cells=comp.get('resolved_cells'))
            if bad_sem: fail(cid, 'component %s: EXECUTION SEMANTICS of the planned arm %s violated (%s family): %s' % (ci, c['arm'], family, bad_sem)); return
            if route.startswith('pac_'):
                if 'uniform_factorless' in route:
                    if cm['factors'] or any(rows[v] != [(F(1, k), F(1, k))] * k for v, k in enumerate(cards)): fail(cid, 'component %s: factorless uniform claim does not match the component' % ci); return
                else:
                    cut = d.get('cutset'); order = d.get('order_free')
                    if not isinstance(cut, list): fail(cid, 'component %s: design cutset missing' % ci); return
                    budget = float(c.get('budget_s') or 20.0); dl = _deadline(deadline_factor * budget)
                    msg, ver = verify_cover(cm, cut, order or [], fr, RT, expect_zero=False, deadline=dl)
                    if msg: fail(cid, 'component %s: %s' % (ci, msg)); return
                    if 'exact_cover' in route and ver['U_t'] != 0: fail(cid, 'component %s: exact-cover claim but the verified frontier is not closed' % ci); return
                    if ver['det_rows'] is None: fail(cid, 'component %s: deterministic publication without a positive verified resolved mass' % ci); return
                    if ver['det_rows'] != rows: fail(cid, 'component %s: recorded deterministic rows differ from the bounds re-derived from the VERIFIED contributions and U_t' % ci); return
                    p_ = [engine.feasible_point(rows[v], eps_t - F(d['decimal_margin'])) for v in range(len(cards))]
                    if any(x is None for x in p_) or any(p_[v] != pts[v] for v in range(len(cards))): fail(cid, 'component %s: recorded points are not the feasible simplex points of the rows' % ci); return
            elif route in ('support', 'dag', 'stream', 'forest'):
                budget = float(c.get('budget_s') or 20.0); dl = _deadline(deadline_factor * budget)       # bounded deterministic re-execution (never deadline=None)
                try:
                    if route == 'forest':
                        import forest; res = forest.solve(model, deadline=dl, independent_replay=True); rr = res['intervals']; rp_ = res['points']
                    elif route == 'dag' and cert.get('reduced_model') is None:
                        import dag; res = dag.execute_plan(dag.plan(model, deadline=dl), deadline=dl); rr = res['intervals']; rp_ = res['points']
                    else:
                        plan = core._discover_component(cm, dl, route); res = core._execute_component(plan, dl); rr = res['intervals']; rp_ = res.get('points') or [[(lo + hi) / 2 for lo, hi in row] for row in rr]
                    rr = [[(F(a), F(b)) for a, b in row] for row in rr]; rp_ = [[F(x) for x in row] for row in rp_]
                    if rr != rows or rp_ != pts: fail(cid, 'component %s: re-execution of the frozen %s route does not reproduce the recorded rows' % (ci, route)); return
                except GateBudgetExhausted: raise
                except (TimeoutError, MemoryError) as ex: fail(cid, 'component %s: UNVERIFIABLE -- frozen route %s re-execution stopped (%s) within the checker budget' % (ci, route, type(ex).__name__)); return
                except Exception as ex:
                    if 'Deadline' in type(ex).__name__ or 'DEADLINE' in str(ex): fail(cid, 'component %s: UNVERIFIABLE -- frozen route %s re-execution exceeded the checker budget' % (ci, route)); return
                    fail(cid, 'component %s: frozen route %s re-execution failed (%s)' % (ci, route, str(ex)[:60])); return
            else: fail(cid, 'component %s: unknown deterministic route %s' % (ci, route)); return
            core.verify_output(rows, pts, eps_t)
        else: fail(cid, 'component %s with guarantee %s' % (ci, g)); return
        for v, row, q in zip(old, rows, pts): verified_rows[v] = row; verified_pts[v] = q
    if w.get('guarantee_type') == 'PAC' and not pac_seen: fail(cid, 'PAC guarantee without any PAC component'); return
    if rm is not None and len(rm['cards']) > 0 and not comps: fail(cid, 'nonempty reduced job without components'); return
    if w.get('guarantee_type') == 'DETERMINISTIC' and pac_seen: fail(cid, 'DETERMINISTIC guarantee with a PAC component'); return
    try:
        if cert.get('reduced_model') is None: LI, LP = verified_rows, verified_pts
        else: LI, LP = reduction.lift(dict(status='REDUCED', decoder=decoder), verified_rows, verified_pts)
        if [[(str(a), str(b)) for a, b in row] for row in LI] != [[tuple(x) for x in row] for row in cert['lifted_intervals_exact']] or [[str(x) for x in row] for row in LP] != [list(row) for row in cert['lifted_points_exact']]: fail(cid, 'the lift of the VERIFIED component rows differs from the certificate lifted rows'); return
        core.verify_output(LI, LP, eps_t); di, dp = core.publish(LI, LP, epsilon=eps_t)
        if di != w.get('intervals') or dp != w.get('points'): fail(cid, 'the published decimals are not the frozen publication of the VERIFIED lifted rows'); return
    except Exception as ex: fail(cid, 'chain verification: %s' % str(ex)[:80]); return


def _deadline(seconds):
    """per-check deadline capped by the aggregate gate budget; raises GateBudgetExhausted when the aggregate budget is already spent"""
    now = time.monotonic(); d = now + seconds
    if _agg['deadline'] is not None:
        if now >= _agg['deadline']: raise GateBudgetExhausted()
        d = min(d, _agg['deadline'])
    return d
_agg = {'deadline': None}


def _late(deadline):
    """POST-acceptance clock check (fifth review R05): a check that finishes after its allowance is UNVERIFIABLE even when its arithmetic succeeded"""
    if deadline is not None and time.monotonic() > deadline: return True
    if _agg['deadline'] is not None and time.monotonic() > _agg['deadline']: return True
    return False


def _isolated_check(spec, deadline):
    """run an independent native checker in a FRESH child process (cex/pac/native_isolated.py) under a HARD timeout = the remaining allowance; returns (result dict or
    None, failure message or None); a child that outlasts the allowance is killed -> UNVERIFIABLE; never an acceptance after the deadline"""
    remaining = (deadline - time.monotonic()) if deadline is not None else None
    if remaining is not None and remaining <= 0: return None, 'UNVERIFIABLE -- checker allowance exhausted before the isolated checker could start'
    d = tempfile.mkdtemp(prefix='gate_native_'); sp = os.path.join(d, 'spec.json'); op = os.path.join(d, 'out.json')
    try:
        json.dump(spec, open(sp, 'w'), default=str)
        try: pr = subprocess.run([sys.executable, os.path.join(HERE, 'native_isolated.py'), sp, op], capture_output=True, text=True, timeout=remaining, cwd=CODE)
        except subprocess.TimeoutExpired: return None, 'UNVERIFIABLE -- the isolated native checker exceeded its allowance (%.3g s) and was killed' % (remaining or 0)
        if not os.path.exists(op): return None, 'isolated native checker wrote no result (rc %s: %s)' % (pr.returncode, (pr.stderr or '')[-160:])
        res = json.load(open(op))
        if _late(deadline): return None, 'UNVERIFIABLE -- the isolated native checker finished after its allowance'
        return res, None
    finally: shutil.rmtree(d, ignore_errors=True)


def verify_zero_proof(model, proof, seed=None, deadline=None, arm=None):
    """re-derive a structured zero-evidence proof on the ORIGINAL model; returns None when verified, else the reason it is not. The FINITE checker deadline is forwarded to
    EVERY route (forest, reduction, component split, exact component discovery / execution, root bound tree, cover verifier); a route that exceeds it is a typed
    UNVERIFIABLE (never an acceptance); the clock is checked again before the accepting return (fifth review R05). The proof kind must be one the planned arm can
    produce (registry.ARM_SEMANTICS zero_proof_kinds; fifth review R04)."""
    import reduction, engine
    if not isinstance(proof, dict): return 'proof is not a structured record (%r)' % (str(proof)[:40],)
    kind = proof.get('kind')
    if arm is not None:
        bad = registry.execution_semantics_failure(arm, 'zero', zero_kind=kind, cutset=proof.get('cutset'))
        if bad: return bad
    if deadline is not None and time.monotonic() >= deadline: return 'UNVERIFIABLE -- checker allowance exhausted before the zero proof could be re-derived'
    def accept():
        return 'UNVERIFIABLE -- the zero-proof re-derivation finished after its allowance' if _late(deadline) else None
    try:
        if kind == 'forest':
            import forest
            try: forest.solve(model, deadline=deadline, independent_replay=True); return 'forest route publishes a posterior: no zero'
            except forest.ZeroEvidence: return accept()
            except forest.DeadlineExceeded: return 'UNVERIFIABLE -- forest re-derivation exceeded the checker allowance'
            except Exception as ex: return 'forest route does not reproduce the zero (%s)' % type(ex).__name__
        red = reduction.reduce(model, deadline=deadline)
        if kind == 'reduction': return (accept() if red.get('status') == 'ZERO_EVIDENCE' else 'reduction of the original model is not zero-evidence')
        if red.get('status') == 'ZERO_EVIDENCE': return 'the reduction itself is zero: the proof kind %s does not match' % kind
        rm = red['model']
        try: split = core.components(rm, deadline=deadline)
        except ValueError as ex:
            if str(ex) == 'ZERO_EVIDENCE': return (accept() if kind == 'component_restriction' else 'component restriction is zero: kind %s does not match' % kind)
            raise
        if kind == 'component_restriction': return 'component restriction is not zero'
        comp = proof.get('component'); vars_ = proof.get('variables')
        if not isinstance(comp, int) or comp >= len(split) or list(split[comp][0]) != list(vars_ or []): return 'component index / variables do not match the re-derived partition'
        cm = split[comp][1]
        if kind == 'exact_component':
            if math.prod(cm['cards']) <= 1 << 20:
                import contrib
                return (accept() if contrib.cell_exact(cm, {}, deadline, max_completions=1 << 20)['B0'][0] == 0 else 'exact enumeration of the component gives positive mass')
            res = core._execute_component(core._discover_component(cm, deadline, proof.get('route', 'auto')), deadline); return (accept() if res.get('status') == 'ZERO_EVIDENCE' else 'frozen route re-execution does not report zero')
        if kind == 'pac_root_bound':
            T = engine.Tree(cm, proof.get('cutset') or [], deadline); return (accept() if T.u_root == 0 else 'root factor-max bound is positive')
        if kind == 'pac_exact_cover':
            cut = proof.get('cutset') or []; order = [v for v in range(len(cm['cards'])) if v not in cut]
            msg, ver = verify_cover(cm, cut, order, proof.get('frontier') or {}, proof.get('resolved_totals') or {}, expect_zero=True, deadline=deadline)
            return msg if msg else accept()
        return 'unknown proof kind %s' % kind
    except GateBudgetExhausted: raise
    except (TimeoutError, MemoryError) as ex: return 'UNVERIFIABLE -- zero-proof re-derivation stopped (%s) within the checker allowance' % type(ex).__name__
    except Exception as ex:
        if 'Deadline' in type(ex).__name__ or 'DEADLINE' in str(ex) or 'deadline' in str(ex).lower(): return 'UNVERIFIABLE -- zero-proof re-derivation exceeded the checker allowance (%s)' % type(ex).__name__
        if type(ex).__name__ in ('CellStop', 'EngineStop') and getattr(ex, 'kind', getattr(ex, 'outcome', '')) in ('DEADLINE',): return 'UNVERIFIABLE -- zero-proof re-derivation exceeded the checker allowance'
        return 're-derivation error %s: %s' % (type(ex).__name__, str(ex)[:60])


# ---------------- native validators (registry-driven; each RE-RUNS the native numerical checker on hash-bound evidence; review 4 F02)
def _fresh_attempt(path_in_attempt, r):
    """the output must lie inside attempt_<nonce> of THIS receipt"""
    p = os.path.abspath(path_in_attempt)
    while p and p != os.path.dirname(p):
        b = os.path.basename(p)
        if b.startswith('attempt_'): return b[len('attempt_'):] == r.get('nonce')
        p = os.path.dirname(p)
    return False


_H4_CACHES = {}


def _h4_caches(m, grids, deadline):
    """producer (256) and checker (320) caches rebuilt from the canonical model and the frozen grid; memoized within ONE gate process (deterministic construction)"""
    key = (m.canonical_sha256(), tuple(str(x) for x in grids[1].h), tuple(grids[1].J), tuple(grids[1].reps))
    if key not in _H4_CACHES:
        from h4a.emit import Cache
        if deadline is not None and time.monotonic() >= deadline: raise TimeoutError('checker allowance exhausted before the cache rebuild')
        _H4_CACHES[key] = (Cache(m, grids[1], 256), Cache(m, grids[1], 320))
    return _H4_CACHES[key]


def _kernel_json_equal(a, b):
    """kernel records compared field by field EXCEPT the wall-clock field (the only non-deterministic field a kernel writes)"""
    return {k: v for k, v in a.items() if k != 'wall_s'} == {k: v for k, v in b.items() if k != 'wall_s'}


def validate_h4_native(RD, c, r, w_path, fail, deadline=None):
    """H4 six frozen nodes (candidate v4.2; fifth review R01-H4 task binding). For EVERY node of the frozen packet, in the frozen order:
      1. the node record of the bundle must carry the frozen (source sign, ordinal, positive node) AND the DERIVED directory key s{p|m}_r{ordinal} (aliases / swaps refused);
      2. the producer and checker WITNESSES (prod.txt / chk.txt) are REGENERATED from the frozen NodeProblem, grid and caches with the frozen construction and must be
         byte-identical (sha256) to the files on disk -- the numeric evidence is thereby bound to THIS node's task;
      3. the native kernels (build/h4rect / h4point / h4pcheck, identity frozen by content hash in the inventory) are RE-EXECUTED on the bound witnesses and their records
         must equal prod.json / chk.json field by field (wall clock excepted): the checked numeric output belongs to the checked inputs;
      4. h4a.certs.verify_node is RE-RUN on the bound records; 5. the Gaussian node weight (exponent AND enclosure) is DERIVED from the frozen node, the marker masses are
         re-derived (checker direction), the accepted / weighted counts are recomputed from the published quantities and the checker replay, and every mandatory mass /
         count claim of masses.json must equal the derived quantity (stored verdict booleans are never trusted);
    every file consumed is hashed into the gated set; the deadline is checked before every kernel execution and after the last accepting step."""
    cid = c['cell_id']
    try: b = json.load(open(w_path)); _ev(w_path)
    except Exception: fail(cid, 'H4 bundle unreadable'); return False
    packet = c.get('packet'); fz = os.path.join(packet or '', 'inputs', 'FROZEN_NODES.json')
    if not packet or not os.path.exists(fz): fail(cid, 'H4 packet FROZEN_NODES.json missing on disk'); return False
    if sha(fz) != c.get('model_sha256'): fail(cid, 'H4 packet FROZEN_NODES.json differs from the frozen manifest hash'); return False
    _ev(fz); Fz = json.load(open(fz))
    if b.get('arm') != c.get('native_arm') or 'H4_NATIVE_%s' % b.get('arm') != c['arm']: fail(cid, 'H4 bundle arm differs from the cell'); return False
    if b.get('repetition') != c.get('replicate'): fail(cid, 'H4 bundle repetition differs from the cell replicate'); return False
    nodes = b.get('nodes') or []
    frozen_nodes = sorted(Fz['nodes'], key=lambda d_: (0 if d_['source_sign'] == 1 else 1, d_['processed_ordinal_1based']))
    want = [(nd['source_sign'], nd['processed_ordinal_1based'], list(nd['positive_node']), 's%s_r%d' % ('p' if nd['source_sign'] == 1 else 'm', nd['processed_ordinal_1based'])) for nd in frozen_nodes]
    got = [(n.get('source_sign'), n.get('ordinal'), list(n.get('node') or ()), n.get('key')) for n in nodes]
    if len(nodes) != 6 or got != want: fail(cid, 'H4 bundle nodes / directory keys differ from the frozen six nodes in the frozen order (alias or swap refused): %s' % [g_[3] for g_ in got]); return False
    if not _fresh_attempt(w_path, r): fail(cid, 'H4 output is not inside the fresh attempt directory of this receipt'); return False
    if not isinstance(b.get('complete_wall_s'), (int, float)) or b['complete_wall_s'] > float(c['budget_s']): fail(cid, 'H4 bundle complete wall exceeds the cell budget'); return False
    if r.get('guarantee_type') != 'DETERMINISTIC': fail(cid, 'H4 receipt guarantee must be DETERMINISTIC'); return False
    try:
        if CODE not in sys.path: sys.path.insert(0, CODE)
        from h4a.model import Model, NodeProblem
        from h4a.grid import Grid
        from h4a.emit import write_point_witness, write_rect_witness
        from h4a.build import producer_tables, checker_tables
        from h4a import certs
        from h4a.masses import verify_masses, marker_masses, publish_relative, node_weight, accepted_count, weighted_count, replay_counts, verify_counts
        from fractions import Fraction as Fr
        m = Model(128, 1)
        if m.canonical_sha256() != Fz['model_hash']: fail(cid, 'H4 canonical model hash differs from the frozen packet'); return False
        grids = {int(sg): Grid(Fz['frequency_grids'][sg]) for sg in ('1', '-1')}
        arm_ = b['arm']; kernels = {'C': ('h4rect', 'h4rect'), 'PI': ('h4point', 'h4rect'), 'PP': ('h4point', 'h4pcheck')}[arm_]
        for k_ in set(kernels):
            kp = os.path.join(CODE, 'build', k_)
            if not os.path.exists(kp): fail(cid, 'H4 native kernel %s absent: the checker cannot re-execute the numeric evidence' % k_); return False
            _ev(kp)
        try: cprod, cchk = _h4_caches(m, grids, deadline)
        except TimeoutError: fail(cid, 'H4: UNVERIFIABLE -- checker budget exhausted before the cache rebuild'); return False
        d = os.path.dirname(w_path); delta = Fr(Fz['analytic_delta_comp_exact']); tmp = tempfile.mkdtemp(prefix='gate_h4_')
        try:
            for n in nodes:
                key = n['key']; nd = os.path.join(d, key)
                for fn in ('prod.json', 'chk.json', 'masses.json', 'verdict.json', 'prod.txt', 'chk.txt'):
                    fp = os.path.join(nd, fn)
                    if not os.path.exists(fp) or os.path.getsize(fp) == 0: fail(cid, 'H4 node %s: required numeric artifact %s missing' % (key, fn)); return False
                    _ev(fp)
                if deadline is not None and time.monotonic() >= deadline: fail(cid, 'H4 node %s: UNVERIFIABLE -- checker budget exhausted' % key); return False
                prob = NodeProblem(m, Fz['source_site'], n['source_sign'], Fz['target_site'], n['node'], 'E0'); grid = grids[n['source_sign']]
                # (2) witnesses REGENERATED from the frozen task and compared byte for byte with the evidence on disk
                pw = os.path.join(tmp, key + '_prod.txt'); cw = os.path.join(tmp, key + '_chk.txt')
                if arm_ == 'C': write_rect_witness(pw, prob, grid, cprod, producer_tables(prob, 256), 256, 'producer')
                else: write_point_witness(pw, prob, grid, cprod, producer_tables(prob, 256), 'producer')
                if arm_ == 'PP': write_point_witness(cw, prob, grid, cchk, checker_tables(prob, 320), 'checker')
                else: write_rect_witness(cw, prob, grid, cchk, checker_tables(prob, 320), 320, 'checker')
                if sha(pw) != sha(os.path.join(nd, 'prod.txt')): fail(cid, 'H4 node %s: producer witness on disk is NOT the witness of this frozen node / source sign / grid (regenerated witness differs): evidence not bound to the task' % key); return False
                if sha(cw) != sha(os.path.join(nd, 'chk.txt')): fail(cid, 'H4 node %s: checker witness on disk is NOT the witness of this frozen node (regenerated witness differs)' % key); return False
                # (3) kernels RE-EXECUTED on the bound witnesses; records must equal the evidence (wall excepted)
                for role, exe, src, outj, extra in (('producer', kernels[0], pw, 'prod.json', (['--prec', '256'] if arm_ == 'C' else [])), ('checker', kernels[1], cw, 'chk.json', (['--prec', '320', '--forward'] if kernels[1] == 'h4rect' else []))):
                    if deadline is not None and time.monotonic() >= deadline: fail(cid, 'H4 node %s: UNVERIFIABLE -- checker budget exhausted before the %s kernel re-execution' % (key, role)); return False
                    oj = os.path.join(tmp, '%s_%s.json' % (key, role)); rem = (deadline - time.monotonic()) if deadline is not None else None
                    try: pr = subprocess.run([os.path.join(CODE, 'build', exe), '--in', src, '--out', oj, *extra, '--expect-freq', str(Fz['representatives']), '--progress', os.path.join(tmp, 'progress.jsonl')], capture_output=True, text=True, timeout=rem)
                    except subprocess.TimeoutExpired: fail(cid, 'H4 node %s: UNVERIFIABLE -- the %s kernel re-execution exceeded the checker allowance' % (key, role)); return False
                    if pr.returncode != 0 or not os.path.exists(oj): fail(cid, 'H4 node %s: %s kernel re-execution failed (rc %s)' % (key, role, pr.returncode)); return False
                    if not _kernel_json_equal(json.load(open(oj)), certs.load_strict(os.path.join(nd, outj))): fail(cid, 'H4 node %s: %s record %s is NOT the kernel output for this node\'s witness (re-execution differs): numeric evidence not bound to the task' % (key, role, outj)); return False
                # (4) independent publication / containment checker RE-RUN
                v2 = certs.verify_node(arm_, os.path.join(nd, 'prod.json'), os.path.join(nd, 'chk.json'), cprod, cchk, grid, prob)
                if v2.get('verdict') != 'VERIFIED' or v2.get('failed_checks'): fail(cid, 'H4 node %s: RE-RUN of the independent checker does not verify (%s)' % (key, v2.get('failed_checks'))); return False
                v = json.load(open(os.path.join(nd, 'verdict.json')))
                if v.get('verdict') != 'VERIFIED' or v.get('arm') != arm_ or sorted(v.get('checks', {})) != sorted(v2['checks']) or any(v['checks'][k] is not True for k in v['checks']): fail(cid, 'H4 node %s: recorded verdict differs from the re-run check schema' % key); return False
                # (5) masses / node weight / counts DERIVED from the frozen task and compared with every mandatory claim
                mj = json.load(open(os.path.join(nd, 'masses.json')))
                try:
                    wv, wexp = node_weight(prob.node, 256); wc, wexp2 = node_weight(prob.node, 320); assert wexp == wexp2 == -Fr(int(n['node'][0]) ** 2 + int(n['node'][1]) ** 2, 2)
                    if str(mj['node_weight_exponent']) != str(wexp): fail(cid, 'H4 node %s: recorded Gaussian exponent %s differs from the exponent DERIVED from the frozen node %s (%s)' % (key, mj['node_weight_exponent'], n['node'], wexp)); return False
                    if [Fr(x) for x in mj['node_weight_checker_unpadded']] != [wc[0], wc[1]]: fail(cid, 'H4 node %s: checker node-weight enclosure differs from the independently derived MPFR320 enclosure' % key); return False
                    pubw = publish_relative(wv)
                    if [Fr(x) for x in mj['node_weight_published']] != [pubw['pub'][0], pubw['pub'][1]]: fail(cid, 'H4 node %s: published node weight differs from the derived publication of exp(%s)' % (key, wexp)); return False
                    Zc, ec = marker_masses(prob, 320, reverse=True)
                    if any([Fr(x) for x in mj['checker_unpadded'][str(sg)]] != [Zc[sg][0], Zc[sg][1]] for sg in (-1, 1)): fail(cid, 'H4 node %s: checker marker masses differ from the independently re-derived reverse-order MPFR320 masses' % key); return False
                    mprod = dict(markers={sg: dict(pub=[Fr(x) for x in mj['marker_masses_published'][str(sg)]], midpoint=Fr(mj['marker_masses_midpoint'][str(sg)])) for sg in (-1, 1)}, total=dict(pub=[Fr(x) for x in mj['total_published']]), node_weight=dict(pub=[Fr(x) for x in mj['node_weight_published']], exponent=mj['node_weight_exponent']))
                    mchk = dict(markers={sg: [Zc[sg][0], Zc[sg][1]] for sg in (-1, 1)}, node_weight=[wc[0], wc[1]], node_weight_exponent=str(wexp))
                    mv = verify_masses(mprod, mchk)
                    if not all(mv.values()): fail(cid, 'H4 node %s: RE-DERIVED mass verdict fails (%s)' % (key, [k for k, ok in mv.items() if not ok])); return False
                    if Fr(mj['delta_comp']) != delta: fail(cid, 'H4 node %s: delta_comp differs from the frozen analytic allowance' % key); return False
                    Ipub = certs.response_publication(os.path.join(nd, 'prod.json'), arm_); Ichk = certs.response_inner(os.path.join(nd, 'chk.json'), arm_)
                    counts = {sg: {'accepted': accepted_count(mprod['total']['pub'], Ipub[sg], mprod['markers'][sg]['pub'][1], delta)} for sg in (-1, 1)}
                    for sg in (-1, 1): counts[sg]['weighted'] = weighted_count(counts[sg]['accepted'], mprod['node_weight']['pub'])
                    Tchk = (Zc[-1][0] + Zc[1][0], Zc[-1][1] + Zc[1][1]); creplay = {sg: replay_counts(Tchk, Ichk[sg], Zc[sg][1], delta, wc) for sg in (-1, 1)}
                    for sg in (-1, 1):
                        if [Fr(x) for x in mj['accepted_counts'][str(sg)]] != list(counts[sg]['accepted']) or [Fr(x) for x in mj['weighted_counts'][str(sg)]] != list(counts[sg]['weighted']): fail(cid, 'H4 node %s: accepted / weighted count claims (marker %d) differ from the counts recomputed from the published quantities' % (key, sg)); return False
                        if [Fr(x) for x in mj['checker_replayed_accepted'][str(sg)]] != list(creplay[sg]['accepted']) or [Fr(x) for x in mj['checker_replayed_weighted'][str(sg)]] != list(creplay[sg]['weighted']): fail(cid, 'H4 node %s: checker count replay (marker %d) differs from the independent replay' % (key, sg)); return False
                    cv = verify_counts(counts, creplay)
                    if not all(cv.values()): fail(cid, 'H4 node %s: RE-DERIVED count verdict fails (%s)' % (key, [k for k, ok in cv.items() if not ok])); return False
                except (KeyError, TypeError, ValueError, AssertionError) as ex: fail(cid, 'H4 node %s: masses record malformed or not derivable (%s: %s)' % (key, type(ex).__name__, str(ex)[:60])); return False
                if n.get('verdict') != 'VERIFIED': fail(cid, 'H4 node %s: bundle verdict not VERIFIED' % key); return False
            if b.get('all_verified') is not True: fail(cid, 'H4 bundle all_verified flag false'); return False
        finally: shutil.rmtree(tmp, ignore_errors=True)
    except GateBudgetExhausted: raise
    except (MemoryError, OverflowError) as ex: fail(cid, 'H4: UNVERIFIABLE -- checker resource failure %s' % type(ex).__name__); return False
    except Exception as ex: fail(cid, 'H4 checker re-run failed (%s: %s)' % (type(ex).__name__, str(ex)[:80])); return False
    if _late(deadline): fail(cid, 'H4: UNVERIFIABLE -- the validation finished after its allowance'); return False
    return True


def validate_sf_native(RD, c, r, w_path, fail, deadline=None):
    """SF: the panel is re-loaded (hash-bound) and ITS dimension n is the authority; the published grid intervals, exact intervals and the route record are RE-CHECKED by
    sf.check.check on the panel for the cell's coupling and the claimed symmetry; the requested width is checked on the re-derived grid widths"""
    cid = c['cell_id']
    try: w = json.load(open(w_path)); _ev(w_path)
    except Exception: fail(cid, 'SF output unreadable'); return False
    if w.get('mode') != 'select' or w.get('status') != 'OK': fail(cid, 'SF output mode / status (%s / %s)' % (w.get('mode'), w.get('status'))); return False
    mp = c.get('model_path') or ''
    if w.get('panel') != os.path.basename(mp) or not os.path.exists(mp) or sha(mp) != c.get('model_sha256') or w.get('input_sha256') != c.get('model_sha256'): fail(cid, 'SF output panel / input hash do not bind to the frozen panel'); return False
    _ev(mp)
    try:
        if CODE not in sys.path: sys.path.insert(0, CODE)
        from sf import core as SFC, check as SFK
        law = SFC.Law.load(mp); n = law.n
        if law.sha256 != c.get('model_sha256'): fail(cid, 'SF panel re-load hash differs'); return False
        rr = F(str(w.get('r'))); eps_req = F(str(c['sf_eps']))
        if rr != F(str(c.get('sf_r'))) or F(str(w.get('eps'))) != eps_req: fail(cid, 'SF coupling / requested width differ from the cell'); return False
        pub = w.get('published'); ivx = w.get('intervals_exact'); rec = dict(w.get('route_record') or {})
        if not (isinstance(pub, list) and isinstance(ivx, list) and len(pub) == n and len(ivx) == n): fail(cid, 'SF publication shape (%s / %s rows) differs from the PANEL dimension n = %d' % (len(pub) if isinstance(pub, list) else '?', len(ivx) if isinstance(ivx, list) else '?', n)); return False
        for k in ('N_int', 'Mk_int'):
            if k in rec: rec[k] = [int(x) for x in rec[k]]
        for k in ('k', 'N_k', 'Zk_int', 'Z_int', 'scale_int', 'max_bits', 'Z_k'):
            if k in rec and isinstance(rec[k], str):
                try: rec[k] = int(rec[k])
                except ValueError: pass
        rec['intervals'] = [(F(lo), F(hi)) for lo, hi in ivx]; rec['published'] = [(int(lg), int(hg)) for lg, hg in pub]; rec['route'] = w.get('route')
        if deadline is not None and time.monotonic() >= deadline: fail(cid, 'SF: UNVERIFIABLE -- checker budget exhausted'); return False
        # the route label of the output and of the route record must agree (the checker binds the declared radius / degree to the label; fifth review R01)
        if str(w.get('route')) != str((w.get('route_record') or {}).get('route', w.get('route'))): fail(cid, 'SF route label differs between the output and its route record'); return False
        spec = dict(kind='sf', panel=mp, r=str(rr), claimed_symmetric=bool((w.get('symmetry') or {}).get('antipodal_A')), rec=dict(rec, intervals=[[str(lo), str(hi)] for lo, hi in rec['intervals']], published=[[str(a), str(b)] for a, b in rec['published']]))
        res, msg = _isolated_check(spec, deadline)              # ISOLATED child under a hard timeout (fifth review R05); never an acceptance after the allowance
        if msg: fail(cid, 'SF: %s' % msg); return False
        if not res.get('ok'): fail(cid, 'SF RE-RUN of the native checker FAILS: %s' % str(res.get('failure') or 'not ok')[:140]); return False
        if res.get('panel_sha256') != c.get('model_sha256') or res.get('n') != n: fail(cid, 'SF isolated checker did not check the frozen panel'); return False
        if (w.get('checker') or {}).get('status') != 'VERIFIED': fail(cid, 'SF recorded checker status not VERIFIED'); return False
        q = 1 << SFC.GRID_BITS; wmax = max(F(int(hg) - int(lg), q) for lg, hg in pub)
        if wmax > eps_req: fail(cid, 'SF requested width %s not met by the re-derived grid widths (max %s)' % (eps_req, wmax)); return False
        if not (w.get('width_met') or {}).get(str(eps_req)) or F(str(w.get('max_width'))) != wmax: fail(cid, 'SF recorded width fields differ from the re-derived widths'); return False
        if not isinstance(w.get('child_wall_s'), (int, float)) or w['child_wall_s'] > float(c['budget_s']): fail(cid, 'SF child wall exceeds the cell budget'); return False
    except GateBudgetExhausted: raise
    except (MemoryError, OverflowError) as ex: fail(cid, 'SF: UNVERIFIABLE -- checker resource failure %s' % type(ex).__name__); return False
    except Exception as ex: fail(cid, 'SF checker re-run failed (%s: %s)' % (type(ex).__name__, str(ex)[:80])); return False
    if not _fresh_attempt(w_path, r): fail(cid, 'SF output is not inside the fresh attempt directory of this receipt'); return False
    if r.get('guarantee_type') != 'DETERMINISTIC': fail(cid, 'SF receipt guarantee must be DETERMINISTIC'); return False
    if _late(deadline): fail(cid, 'SF: UNVERIFIABLE -- the validation finished after its allowance'); return False
    return True


def validate_cbi_native(RD, c, r, w_path, fail, deadline=None):
    """CBI: the instance is re-loaded (hash-bound); query count, external ids and dimension d come from the INSTANCE; every block carries exactly d coordinate records with
    ordered exact endpoints in [0,1], published grid endpoints enclosing them and width <= 1/100; the cbi library's INDEPENDENT verifier (cbi.verify.verify) is RE-RUN on the
    bound instance and output (proof paths re-derived; published intervals must contain the verifier's enclosures)"""
    cid = c['cell_id']
    try: w = json.load(open(w_path)); _ev(w_path)
    except Exception: fail(cid, 'CBI output unreadable'); return False
    if w.get('status') != 'CERTIFIED': fail(cid, 'CBI output status %s' % w.get('status')); return False
    mp = c.get('model_path') or ''
    if not os.path.exists(mp) or sha(mp) != c.get('model_sha256'): fail(cid, 'CBI frozen instance file missing or differs from the manifest hash'); return False
    _ev(mp)
    try:
        if CODE not in sys.path: sys.path.insert(0, CODE)
        from cbi import model as M, verify as V
        instj = json.load(open(mp)); inst = M.Model.from_json(instj); d = int(instj['d']); want_ids = [inst.ext(i) for i in sorted(inst.blocks)]
        canon = inst.sha256()
        if w.get('model_sha256') not in (canon, c.get('model_sha256')): fail(cid, 'CBI output model hash binds neither the frozen file nor its canonical form'); return False
        ids = (w.get('id_map') or {}).get('external_ids')
        if ids is None or sorted(ids) != sorted(want_ids): fail(cid, 'CBI output block id map differs from the frozen instance (%s vs %s)' % (ids, want_ids)); return False
        if F(str(w.get('requested_width'))) != F(1, 100): fail(cid, 'CBI requested width is not the native 1/100'); return False
        sq = w.get('statuses_per_query') or {}; iv = w.get('intervals') or {}
        if sorted(int(k) for k in sq) != sorted(want_ids) or sorted(int(k) for k in iv) != sorted(want_ids): fail(cid, 'CBI per-query statuses / intervals do not cover exactly the instance blocks'); return False
        if any(v != 'CERTIFIED' for v in sq.values()): fail(cid, 'CBI a per-query status is not CERTIFIED'); return False
        q = 1 << int(w.get('grid_bits') or 0)
        for k, blk in iv.items():
            co = blk.get('coordinates')
            if not isinstance(co, list) or len(co) != d: fail(cid, 'CBI block %s: %s coordinate records for dimension d = %d' % (k, len(co) if isinstance(co, list) else '?', d)); return False
            for jj, x in enumerate(co):
                lo, hi = F(x['exact'][0]), F(x['exact'][1]); lg, hg = int(x['lo']), int(x['hi'])
                if not (0 <= lo <= hi <= 1) or not (0 <= lg <= hg <= q) or not (F(lg, q) <= lo and hi <= F(hg, q)): fail(cid, 'CBI block %s coordinate %d: enclosure malformed' % (k, jj)); return False
                if F(hg - lg, q) > F(1, 100) or F(str(x.get('width', F(hg - lg, q)))) != F(hg - lg, q): fail(cid, 'CBI block %s coordinate %d: width %s exceeds 1/100 or differs from the record' % (k, jj, F(hg - lg, q))); return False
        if deadline is not None and time.monotonic() >= deadline: fail(cid, 'CBI: UNVERIFIABLE -- checker budget exhausted'); return False
        res, msg = _isolated_check(dict(kind='cbi', instance=instj, output=w), deadline)              # ISOLATED child under a hard timeout (fifth review R05)
        if msg: fail(cid, 'CBI: %s' % msg); return False
        if not res.get('ok'): fail(cid, 'CBI RE-RUN of the independent verifier REJECTS the output: %s' % str((res.get('reasons') or [res.get('failure') or '?'])[0])[:120]); return False
    except GateBudgetExhausted: raise
    except (MemoryError, OverflowError) as ex: fail(cid, 'CBI: UNVERIFIABLE -- checker resource failure %s' % type(ex).__name__); return False
    except Exception as ex: fail(cid, 'CBI verifier re-run failed (%s: %s)' % (type(ex).__name__, str(ex)[:80])); return False
    if not _fresh_attempt(w_path, r): fail(cid, 'CBI output is not inside the fresh attempt directory of this receipt'); return False
    if r.get('guarantee_type') != 'DETERMINISTIC': fail(cid, 'CBI completed with guarantee %s' % r.get('guarantee_type')); return False
    if _late(deadline): fail(cid, 'CBI: UNVERIFIABLE -- the validation finished after its allowance'); return False
    return True


def dependency_closure_failures(RD, c, evidence):
    """ONE closure check shared by the report and the closeout (v4.2): every task dependency of the cell must have been hashed by the gate -- matched by BASENAME and CURRENT
    CONTENT HASH against the cell's gated evidence (robust to a relocated copy of the run directory; a dependency whose current bytes differ from every gated entry, or
    which the gate never hashed, is a failure); an ABSENT UAI evidence file is the empty-evidence task and matches a gated entry recorded as None"""
    out = []
    ev = {}
    for k, v in (evidence or {}).items(): ev.setdefault(os.path.basename(k), set()).add(v)
    for dep in task_dependencies(c):
        cur = sha(dep) if os.path.exists(dep) else None; got = ev.get(os.path.basename(dep))
        if got is None: out.append('task dependency %s of cell %s was not hashed by the gate (incomplete dependency closure)' % (os.path.basename(dep), c['cell_id']))
        elif cur not in got: out.append('task dependency %s of cell %s differs from the bytes the gate hashed (changed / replaced / missing)' % (os.path.basename(dep), c['cell_id']))
    return out


def effective_evidence_path(model_path):
    """the ONE effective evidence file of a UAI task: the reader (core.read_uai, the B0 reader, the references, the report) consumes <model_path>.evid, present or absent;
    a manifest that declares a different evidence_path does not identify the reader's input and is REFUSED (sixth review F03)"""
    return model_path + '.evid'


def evidence_declaration_failure(c):
    """None when the cell's declared evidence_path (if any) IS the effective evidence path of its model, else the refusal message"""
    mp = c.get('model_path'); ep = c.get('evidence_path')
    if not mp or ep is None: return None
    if os.path.abspath(ep) != os.path.abspath(effective_evidence_path(mp)): return 'declared evidence_path %s does not identify the reader\'s effective evidence file %s (one effective-input resolver)' % (ep, effective_evidence_path(mp))
    return None


def task_dependencies(c):
    """the COMPLETE task dependency set of a cell (candidate v4.2; fifth review R02): every file the task is DEFINED by -- the model file, its evidence file (UAI
    representation: <model>.evid, present or absent -- an absent file is the empty-evidence task and is recorded as such), the adapter blocks metadata of the adapted
    cohorts, the native packet / panel / instance. ONE enumerator shared by the gate (hashing), the report and the closeout (re-hashing)."""
    deps = []
    mp = c.get('model_path')
    if mp: deps.append(mp)
    rep_ = (registry.COHORTS.get(c.get('cohort')) or {}).get('representation')
    if rep_ == 'uai_table' and mp: deps.append(effective_evidence_path(mp))                 # the EFFECTIVE path (never the declared one): the reader's input
    if c.get('blocks_path'): deps.append(c['blocks_path'])
    return deps


def _bind_task_dependencies(c, fail):
    """hash the task dependency set into the gated set and check the frozen manifest hashes: the model file must equal model_sha256; the UAI evidence file (or its ABSENCE
    = sha256(b'0')) must equal evidence_sha256; the blocks metadata must equal blocks_sha256 (semantic hash of blocks / d / cards)"""
    cid = c['cell_id']; ok = True
    bad_decl = evidence_declaration_failure(c)
    if bad_decl: fail(cid, bad_decl); ok = False
    for dep in task_dependencies(c):
        h = _ev(dep)
        if dep == c.get('model_path'):
            if h != c.get('model_sha256'): fail(cid, 'frozen input file %s differs from the manifest hash or is missing (input changed after freeze)' % os.path.basename(dep)); ok = False
        elif dep == effective_evidence_path(c.get('model_path') or ''):
            cur = h if h is not None else hashlib.sha256(b'0').hexdigest()
            if cur != c.get('evidence_sha256'): fail(cid, 'task EVIDENCE file %s differs from the frozen evidence hash (present / absent / changed): the task on disk is not the frozen task' % os.path.basename(dep)); ok = False
        elif dep == c.get('blocks_path'):
            try:
                meta = json.load(open(dep)); mh_ = hashlib.sha256(json.dumps(dict(blocks=meta['blocks'], d=meta['d'], cards=meta['cards']), sort_keys=True).encode()).hexdigest()
                if mh_ != c.get('blocks_sha256'): fail(cid, 'adapter blocks metadata differs from the frozen blocks hash'); ok = False
            except Exception as ex: fail(cid, 'adapter blocks metadata unreadable (%s)' % type(ex).__name__); ok = False
    return ok


NORMALIZATION_TOL_MAX = F(1, 200)     # a row whose printed digits cannot certify normalization within the task epsilon is not a verifiable answer at that resolution


def _token_half_ulp(tok):
    """half of the decimal unit in the last printed place of a token (the maximal rounding error of a correctly rounded decimal serialization)"""
    t = tok.lower(); mant, exp10 = (t.split('e') + ['0'])[:2]
    digits = len(mant.split('.')[1]) if '.' in mant else 0
    return F(1, 2) * F(1, 10 ** digits) * (F(10) ** int(exp10))


def validate_mar_rows(tokens, cards, ev, mantissa_bits=53, entry_error_ulps=4):
    """ONE comparator answer contract (sixth review F04) shared by the gate and the report: tokens = the MAR file split; returns (rows as Fractions, failure message or None).
    Shape: one row per ORIGINAL variable with card(v) entries. Entries: finite decimals in [0, 1]. Normalization: POSITIVE total mass and |Σ row − 1| ≤ tol where
    tol = min(Σ_i half-ulp(token_i) + k·entry_error_ulps·2^-mantissa_bits, NORMALIZATION_TOL_MAX): the aggregate decimal-serialization error of THIS row's printed digits plus
    the DECLARED per-entry error budget of the comparator's numeric pipeline (registry mantissa_bits / entry_error_ulps: binary64 point pipelines 4 ulps, PGMax float32
    exp-of-log beliefs 64 ulps), never more than the task epsilon --
    it can never become vacuous with the cardinality (an all-zero row, a mis-scaled row, a row off by more than epsilon are refused). Observed variables are point masses
    on their state. No renormalization is applied: the scored vector is the printed vector."""
    try:
        i = tokens.index('MAR') + 1 if 'MAR' in tokens else 0
        n = int(tokens[i]); i += 1; rows = []; raw = []
        for _ in range(n):
            k = int(tokens[i]); i += 1; raw.append(tokens[i:i + k]); rows.append([F(x) for x in tokens[i:i + k]]); i += k
        if i != len(tokens): return None, 'comparator answer carries trailing tokens'
    except (ValueError, IndexError, ZeroDivisionError) as ex: return None, 'comparator answer unparseable or non-finite (%s)' % type(ex).__name__
    if len(rows) != len(cards): return None, 'comparator answer has %d rows for %d variables of the ORIGINAL model: an incomplete answer is not a completed inference' % (len(rows), len(cards))
    for v, (row, toks, k) in enumerate(zip(rows, raw, cards)):
        if len(row) != k: return None, 'comparator answer row %d has %d entries for cardinality %d' % (v, len(row), k)
        if any(t.lower() in ('nan', 'inf', '-inf', '+inf', 'infinity', '-infinity') for t in toks) or any(x < 0 or x > 1 for x in row): return None, 'comparator answer row %d has a non-finite or out-of-range probability' % v
        total = sum(row)
        if total <= 0: return None, 'comparator answer row %d has no probability mass (sum 0): not a distribution' % v
        tol = min(sum(_token_half_ulp(t) for t in toks) + F(k * int(entry_error_ulps), 2 ** int(mantissa_bits)), NORMALIZATION_TOL_MAX)
        if abs(total - 1) > tol: return None, 'comparator answer row %d is not normalized (sum %s; tolerance %s derived from the printed digits and the declared representation, capped at the task epsilon)' % (v, float(total), float(tol))
        if v in ev and row[ev[v]] < 1 - F(1, 10 ** 6): return None, 'comparator answer row %d is not a point mass on the observed state' % v
    return rows, None


def validate_comparator(RD, c, r, fail, model, deadline=None):
    """comparator (UNGUARANTEED) completion (candidate v4.2; fifth review R03): a completed comparator cell counts as a publication ONLY when (1) the adapter packet
    cmp/pac_receipt.json exists inside the fresh attempt of THIS receipt and binds arm, nonce, model / evidence sha256 (= the frozen task), budget and the output
    sha256; (2) the output file exists, is hashed, equals the packet and the receipt; (3) the answer is WELL-FORMED for the ORIGINAL model: exactly one row per variable,
    exactly card(v) finite entries in [0, 1] per row, POSITIVE total mass and normalization within a tolerance derived from the printed digits and capped at the task
    epsilon (validate_mar_rows; sixth review F04: never vacuous with the cardinality), every observed variable a point mass on its observed state. Approximation error against any reference is NOT checked here (diagnostic in the report)."""
    cid = c['cell_id']; cmpr = r.get('comparator') or {}; of = cmpr.get('output_file')
    if not of or not os.path.exists(of): fail(cid, 'COMPLETED comparator without its output file'); return False
    _ev(of)
    if sha(of) != cmpr.get('output_sha256'): fail(cid, 'comparator output sha256 differs from the receipt'); return False
    if r.get('guarantee_type') != 'UNGUARANTEED': fail(cid, 'comparator completed with guarantee %s' % r.get('guarantee_type')); return False
    if not _fresh_attempt(of, r): fail(cid, 'comparator output is not inside the fresh attempt directory of this receipt'); return False
    pk = os.path.join(r.get('attempt_dir') or os.path.dirname(os.path.dirname(of)), 'cmp', 'pac_receipt.json')
    if not os.path.exists(pk): fail(cid, 'comparator adapter packet cmp/pac_receipt.json missing: the answer is not bound to a fresh attempt of this task'); return False
    _ev(pk)
    try: P = json.load(open(pk))
    except Exception: fail(cid, 'comparator adapter packet unreadable'); return False
    if P.get('arm') != c['arm'] or P.get('nonce') != r.get('nonce'): fail(cid, 'comparator adapter packet arm / nonce differ from the planned cell and its receipt'); return False
    if P.get('model_sha256') != c.get('model_sha256') or P.get('evidence_sha256') != c.get('evidence_sha256'): fail(cid, 'comparator adapter packet input hashes differ from the frozen task'); return False
    if not isinstance(P.get('budget_s'), (int, float)) or float(P['budget_s']) != float(c['budget_s']): fail(cid, 'comparator adapter packet budget differs from the cell'); return False
    if P.get('outcome') != 'PUBLISHED' or P.get('output_sha256') != cmpr.get('output_sha256') or P.get('output_sha256') != sha(of) or os.path.basename(str(P.get('output_file') or '')) != os.path.basename(of) or os.path.dirname(os.path.abspath(pk)) != os.path.dirname(os.path.abspath(of)): fail(cid, 'comparator adapter packet does not bind this output (outcome / output sha256 / file name / same attempt directory)'); return False
    if not _fresh_attempt(pk, r): fail(cid, 'comparator adapter packet is not inside the fresh attempt directory of this receipt'); return False
    try: toks = open(of).read().split()
    except Exception as ex: fail(cid, 'comparator answer unreadable (%s)' % type(ex).__name__); return False
    rows, bad = validate_mar_rows(toks, model['cards'], model.get('evidence', {}), mantissa_bits=(registry.ARMS.get(c['arm']) or {}).get('mantissa_bits', 53), entry_error_ulps=(registry.ARMS.get(c['arm']) or {}).get('entry_error_ulps', 4))
    if bad: fail(cid, bad); return False
    if _late(deadline): fail(cid, 'comparator: UNVERIFIABLE -- the validation finished after its allowance'); return False
    return True


def _check_cell(RD, cid, r, c, man, frozen_candidate, frozen_b0, models, failures, fail, EPS, replay_factor, counters):
    """all checks of ONE receipt (extracted so that an aggregate-budget exhaustion is a structured per-cell outcome)"""
    for k in ('case_id', 'arm', 'replicate', 'budget_s', 'seed', 'model_sha256', 'evidence_sha256', 'cohort'):
        if r.get(k) != c.get(k): fail(cid, 'receipt %s differs from the manifest' % k)
    wall = r.get('launch_relative_wall_s'); timely = isinstance(wall, (int, float)) and not isinstance(wall, bool) and wall == wall and 0 <= wall <= float(c['budget_s'])
    if not (isinstance(wall, (int, float)) and not isinstance(wall, bool) and 0 <= wall < float('inf')): fail(cid, 'receipt wall is not a finite nonnegative number (%s)' % wall)
    sup = r.get('supervisor') or {}; arm = c['arm']; validator = registry.validator_of(arm)
    wp = os.path.join(RD, r['worker_output']) if r.get('worker_output') else None
    if r.get('status') == 'COMPLETED':
        counters['checked'] += 1
        if sup.get('rc') != 0: fail(cid, 'COMPLETED with supervisor rc %s' % sup.get('rc'))
        if sup.get('outcome') != 'COMPLETED': fail(cid, 'COMPLETED with supervisor outcome %s' % sup.get('outcome'))
        if not timely: fail(cid, 'COMPLETED but recomputed launch-relative wall %s > budget %s' % (wall, c['budget_s']))
        if r.get('outcome') != 'PUBLISHED': fail(cid, 'COMPLETED but outcome %s' % r.get('outcome'))
        if validator == 'comparator_mar':
            mpth = c.get('model_path')
            if not mpth or not os.path.exists(mpth): fail(cid, 'frozen input file missing on disk'); return
            if not _bind_task_dependencies(c, fail): return
            if mpth not in models: models[mpth] = core.read_uai(mpth)
            model, binding = models[mpth]
            if binding.get('model_sha256') != c.get('model_sha256') or binding.get('evidence_sha256') != c.get('evidence_sha256'): fail(cid, 'input files on disk differ from the FROZEN manifest hashes (input changed after freeze)'); return
            if validate_comparator(RD, c, r, fail, model, deadline=_deadline(replay_factor * float(c['budget_s']))): counters['gated'] += 1
            return
        if not wp or not os.path.exists(wp): fail(cid, 'COMPLETED without a worker output file'); return
        _ev(wp)
        if sha(wp) != r.get('output_sha256'): fail(cid, 'worker output sha256 differs from the receipt'); return
        if validator in ('h4_native', 'sf_native', 'cbi_native') and not _bind_task_dependencies(c, fail): return
        if validator == 'h4_native':
            if validate_h4_native(RD, c, r, wp, fail, deadline=_deadline(replay_factor * float(c['budget_s']))): counters['gated'] += 1
            return
        if validator == 'sf_native':
            if validate_sf_native(RD, c, r, wp, fail, deadline=_deadline(replay_factor * float(c['budget_s']))): counters['gated'] += 1
            return
        if validator == 'cbi_native':
            if validate_cbi_native(RD, c, r, wp, fail, deadline=_deadline(replay_factor * float(c['budget_s']))): counters['gated'] += 1
            return
        if validator != 'uai_candidate': fail(cid, 'no validator for arm %s' % arm); return
        w = json.load(open(wp))
        if w.get('status') != 'COMPLETED': fail(cid, 'worker status %s' % w.get('status'))
        mpth = c.get('model_path')
        if not mpth or not os.path.exists(mpth): fail(cid, 'frozen input file missing on disk'); return
        if not _bind_task_dependencies(c, fail): return                       # model + .evid (present / absent) + blocks metadata hashed into the gated set (fifth review R02)
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
        if not okshape: fail(cid, 'output shape differs from the original model'); return
        try:
            IV = [[(F(a), F(b)) for a, b in row] for row in iv]; PT = [[F(x) for x in row] for row in pts]; core.verify_output(IV, PT, EPS)
            for v, a in ev.items():
                if not all((PT[v][s] == 1 and IV[v][s] == (F(1), F(1))) if s == a else (PT[v][s] == 0 and IV[v][s] == (F(0), F(0))) for s in range(cards[v])): fail(cid, 'observed variable %d not one-hot' % v)
        except Exception as ex: fail(cid, 'publication contract: %s' % str(ex)[:80]); return
        if arm in CANDIDATE_ARMS:
            nf = len(failures); dl_cell = _deadline(replay_factor * float(c['budget_s'])); check_pac_certificate(w, c, man, model, fail, deadline_factor=replay_factor)
            if len(failures) == nf and _late(dl_cell): fail(cid, 'UNVERIFIABLE -- the certificate verification finished after the cell allowance (%.3g s)' % (replay_factor * float(c['budget_s'])))
            if len(failures) == nf and w.get('guarantee_type') == 'PAC': counters['pac_verified'] += 1
        counters['gated'] += 1
    else:
        if r.get('outcome') == 'PUBLISHED': fail(cid, 'non-COMPLETED receipt with outcome PUBLISHED')
        if r.get('outcome') == 'PROVED_ZERO_EVIDENCE':
            if not timely: fail(cid, 'zero-evidence claim after the budget (late proof is not a timely result)')
            if sup.get('rc') != 0 or 'KILL' in str(sup.get('outcome')): fail(cid, 'zero-evidence claim with supervisor rc %s / outcome %s' % (sup.get('rc'), sup.get('outcome')))
            if arm in CANDIDATE_ARMS:
                if not wp or not os.path.exists(wp): fail(cid, 'zero-evidence claim without a worker output')
                elif sha(wp) != r.get('output_sha256'): fail(cid, 'zero-evidence worker output sha256 differs from the receipt')
                else:
                    _ev(wp); w = json.load(open(wp))
                    if w.get('status') != 'STOPPED' or w.get('outcome') != 'PROVED_ZERO_EVIDENCE' or w.get('late_proof'): fail(cid, 'zero-evidence claim without a recorded timely proof')
                    if w.get('nonce') != r.get('nonce') or w.get('seed') != c.get('seed') or w.get('arm') != arm: fail(cid, 'zero-evidence output nonce / seed / arm differ from the cell')
                    cs = w.get('candidate_sources') or {}
                    if any(k not in cs or cs[k] != v for k, v in frozen_candidate.items()): fail(cid, 'zero-evidence output source identity incomplete or differs from the frozen artifact')
                    mpth = c.get('model_path')
                    if not mpth or not os.path.exists(mpth): fail(cid, 'frozen input file missing on disk')
                    elif _bind_task_dependencies(c, fail):
                        if mpth not in models: models[mpth] = core.read_uai(mpth)
                        model, binding = models[mpth]
                        if binding.get('model_sha256') != c.get('model_sha256') or binding.get('evidence_sha256') != c.get('evidence_sha256') or w.get('binding') != binding: fail(cid, 'zero-evidence output binding differs from the frozen input')
                        else:
                            msg = verify_zero_proof(model, w.get('zero_evidence_proof'), seed=c.get('seed'), deadline=_deadline(replay_factor * float(c['budget_s'])), arm=arm)
                            if msg: fail(cid, 'zero-evidence proof NOT re-derivable: %s' % msg)
            elif arm == B0:
                if not wp or not os.path.exists(wp): fail(cid, 'zero-evidence claim without a worker output')
                elif sha(wp) != r.get('output_sha256'): fail(cid, 'zero-evidence worker output sha256 differs from the receipt')
                else: _ev(wp); _bind_task_dependencies(c, fail)
            elif r.get('guarantee_type') in ('PAC', 'DETERMINISTIC'): fail(cid, 'comparator / native zero outcome cannot carry a guarantee (underflow is indistinguishable)')
        elif r.get('guarantee_type') in ('PAC', 'DETERMINISTIC'): fail(cid, 'guarantee claimed without publication')


# ---------------- main
def main(RD, manifest_name='CAMPAIGN_MANIFEST.json', out_path=None, replay_factor=REPLAY_FACTOR, gate_budget_s=GATE_BUDGET_S):
    RD = os.path.abspath(RD); failures = []; t_gate = time.monotonic(); _evidence.clear(); _agg['deadline'] = (t_gate + float(gate_budget_s)) if gate_budget_s else None; exhausted_at = None
    if replay_factor is None or not (replay_factor > 0) or replay_factor != replay_factor: return _write(RD, out_path, dict(gate_version=GATE_VERSION, failures=[('*', 'invalid replay factor %r' % (replay_factor,))], gate_passed=False))
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
    # ---- NULL / invalid identities (fifth review): a required artifact without a valid sha256 never qualifies a manifest that plans an arm needing it; artifacts no planned
    # arm needs are reported as scoped-unavailable (visible in the result), never silently matched as equal None entries
    planned_arms_ = sorted({c_['arm'] for c_ in man.get('cells') or []})
    id_fail, unavailable_artifacts = registry.identity_failures(ch, planned_arms_) if isinstance(ch, dict) and ch else ([], [])
    for f_ in id_fail: fail('*', f_)
    id_fail_disk, _unav2 = registry.identity_failures(want, planned_arms_)
    for f_ in id_fail_disk:
        if f_ not in id_fail: fail('*', 'ON DISK: ' + f_)
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
    task = man.get('task') or {}; EPS = F(str(task.get('epsilon', '1/200'))); models = {}; gated_set = []; counters = dict(checked=0, gated=0, pac_verified=0)
    for cid in sorted(receipts):
        r = receipts[cid]; c = cells.get(cid)
        if not c: continue
        entry = dict(cell_id=cid, receipt_sha256=r['_sha'], output_sha256=r.get('output_sha256'), status=r.get('status'), outcome=r.get('outcome'), guarantee=r.get('guarantee_type'), arm=c['arm'], cohort=c['cohort'], budget_s=c['budget_s'], case_id=c['case_id'], replicate=c['replicate'], evidence={}, verified=False); gated_set.append(entry)
        if exhausted_at is not None: fail(cid, 'UNVERIFIABLE: aggregate gate budget exhausted before this cell was checked'); continue
        _cell_paths.clear(); nf_before = len(failures)
        try: _check_cell(RD, cid, r, c, man, frozen_candidate, frozen_b0, models, failures, fail, EPS, replay_factor, counters)
        except GateBudgetExhausted: exhausted_at = cid; fail(cid, 'UNVERIFIABLE: aggregate gate budget exhausted while checking this cell')
        entry['evidence'] = {(os.path.relpath(k, RD) if k.startswith(RD + os.sep) else k): _evidence[k] for k in sorted(_cell_paths)}; entry['verified'] = (len(failures) == nf_before)
    checked, gated, pac_verified = counters['checked'], counters['gated'], counters['pac_verified']
    # ---- FINAL acceptance clock check (fifth review R05): the whole gate must finish inside its aggregate budget; a late finish is UNVERIFIABLE for the last cell checked
    if _agg['deadline'] is not None and time.monotonic() > _agg['deadline'] and exhausted_at is None and gated_set:
        exhausted_at = gated_set[-1]['cell_id']; fail(exhausted_at, 'UNVERIFIABLE: the gate finished after its aggregate budget (final acceptance clock check)'); gated_set[-1]['verified'] = False
    gs = hashlib.sha256(json.dumps(gated_set, sort_keys=True).encode()).hexdigest()
    res = dict(gate_version=GATE_VERSION, manifest=manifest_name, manifest_sha256=mh, artifact_hashes_sha256=ah, planned=len(cells), receipts=len(receipts), completed_checked=checked, completed_gated=gated, pac_certificates_replayed=pac_verified, failures=failures, gate_passed=not failures, gated_set=gated_set, gated_set_sha256=gs, gate_wall_s=round(time.monotonic() - t_gate, 3), replay_factor=replay_factor, gate_budget_s=gate_budget_s, budget_exhausted_at_cell=exhausted_at, unavailable_artifacts_not_needed_by_planned_arms=unavailable_artifacts, verification_policy='every receipt is checked in cell-id order; a check exceeding its per-component allowance or the aggregate budget is UNVERIFIABLE (a failure); every proof route (PAC replay, cover re-evaluation, zero proofs, frozen re-execution, native checkers in an isolated child under a hard timeout, comparator validation) receives the finite allowance and the clock is checked again before every accepting return and once more before the gate accepts; cells after an aggregate exhaustion are UNVERIFIABLE; the result file is always written; the gated set records every evidence file each validator consumed with its sha256 (task dependency set incl. .evid / blocks / adapter packets / native witnesses / kernels)')
    return _write(RD, out_path, res)


def _write(RD, out_path, res):
    out_path = out_path or os.path.join(RD, 'GATE_RESULT.json')
    json.dump(res, open(out_path, 'w'), indent=1); print(json.dumps({k: res.get(k) for k in ('gate_version', 'planned', 'receipts', 'completed_checked', 'completed_gated', 'pac_certificates_replayed', 'gate_passed', 'gated_set_sha256')}))
    for f in res['failures'][:40]: print('  ', f)
    if len(res['failures']) > 40: print('   ... %d more failures' % (len(res['failures']) - 40))
    return 0 if res['gate_passed'] else 1


if __name__ == '__main__':
    mn = sys.argv[sys.argv.index('--manifest') + 1] if '--manifest' in sys.argv else 'CAMPAIGN_MANIFEST.json'; op = sys.argv[sys.argv.index('--out') + 1] if '--out' in sys.argv else None
    rf = float(sys.argv[sys.argv.index('--replay-factor') + 1]) if '--replay-factor' in sys.argv else REPLAY_FACTOR; gb = float(sys.argv[sys.argv.index('--gate-budget-s') + 1]) if '--gate-budget-s' in sys.argv else GATE_BUDGET_S
    try: rc = main(sys.argv[1], mn, op, rf, gb)
    except Exception as ex:
        import traceback; rc = _write(os.path.abspath(sys.argv[1]), op, dict(gate_version=GATE_VERSION, failures=[('*', 'GATE FAULT: %s: %s' % (type(ex).__name__, str(ex)[:200]))], gate_passed=False, fault_trace=traceback.format_exc()[-2000:]))
    sys.exit(rc)
