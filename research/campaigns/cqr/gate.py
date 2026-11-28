"""CQR RECEIPT / CERTIFICATE GATE -- fail-closed, content-addressed (composition over the FROZEN baseline gate cex/pac/gate.py, which is imported for the baseline arms and
never edited). For every receipt: receipt == manifest cell, finite wall (<= budget when COMPLETED), supervisor rc / outcome, worker output sha == receipt, the COMPLETE task
dependency set hashed into the gated set (the reader's EFFECTIVE files only: model, <model>.evid present / absent, <model>.query.json present / absent) and compared with the
frozen hashes; CQR arms: candidate_sources == the frozen cqr scope (cqr/*.py + newarm/core.py; zero missing / differing / extra), nonce / seed / arm, then the INDEPENDENT
end-to-end checker cex/cqr/checker.py (compiler chain replay, frontier / draw replay, publication rule, exact reference re-enumeration, zero proofs) under REPLAY_FACTOR x the
cell budget; a 'UNVERIFIABLE' failure is recorded as such (never an acceptance). Baseline arms: cex/pac/gate._check_cell with the frozen pac/newarm candidate and b0 subsets.
An aggregate budget (--gate-budget-s) stops the gating; every ungated cell FAILS 'UNVERIFIABLE -- aggregate verification budget exhausted'. GATE_RESULT.json: gate_version,
gate_passed, failures, counters, gated_set (+ gated_set_sha256 over the sorted receipt / output / dependency hashes), gate_wall_s, budget_exhausted_at_cell. Exit 1 if not passed.
    python -m research.campaigns.cqr.gate <RD> [--manifest NAME] [--out PATH] [--replay-factor 3.0] [--gate-budget-s S]"""
from ._paths import HERE, ROOT, CODE, CEX, PAC, NEWARM, RUNTIME, PY, runs_root, source_path, subprocess_env
import sys, os, json, hashlib, glob, time, importlib.util
sys.set_int_max_str_digits(0)
from ._legacy import load_pac
PR = load_pac('registry'); from pgm.algorithms.structural import core
from fractions import Fraction as F
from pgm.algorithms.cqr import checker as CK; from pgm.algorithms.cqr import task as TK
from research.campaigns.cqr import kernel_identity as KI
_F = F
_attrib = {}            # cell_id -> the checker's authoritative attribution (route / class / exact / bias ledger / commits), written into the gated set for the report




from . import registry as R
from ._legacy import load_pac
PG = load_pac('gate')
GATE_VERSION = 'cqr-gate-v1.2 (2026-11-19, repair-2 review CQR-AF2-01: the global preflight extracted into global_preflight() for reuse by the successor verification path -- no semantic change; v1.1 2026-11-17, structured review CQR-S1-03: loaded-kernel provenance (worker-recorded digests vs the frozen identity) validated for every arm with native tags incl. the CQR arms; attribution carried from the checker\'s VERIFIED facts; v1 2026-11-16: independent CQR checker per cell under REPLAY_FACTOR x budget; published answers bound to the certified publication; frozen cqr scope identity; effective-file dependency closure incl. .query.json; baseline arms through the frozen pac gate v4.3 _check_cell; aggregate budget -> structured UNVERIFIABLE)'
REPLAY_FACTOR = 3.0
LEDGER = 'CQR_LEDGER.jsonl'
ZERO_HASH = hashlib.sha256(b'0').hexdigest()


class GateBudgetExhausted(Exception): pass


def sha(p):
    h = hashlib.sha256()
    with open(p, 'rb') as f:
        for b in iter(lambda: f.read(1 << 20), b''): h.update(b)
    return h.hexdigest()


_evidence = {}; _cell_paths = set(); _agg = {'deadline': None}


def _ev(path):
    p = os.path.abspath(path); _evidence[p] = sha(p) if os.path.exists(p) else None; _cell_paths.add(p); return _evidence[p]


def _deadline(seconds):
    now = time.monotonic(); d = now + seconds
    if _agg['deadline'] is not None:
        if now >= _agg['deadline']: raise GateBudgetExhausted()
        d = min(d, _agg['deadline'])
    return d


def _late(deadline):
    if deadline is not None and time.monotonic() > deadline: return True
    return _agg['deadline'] is not None and time.monotonic() > _agg['deadline']


def cqr_scope(ch): return {k: v for k, v in (ch or {}).items() if R.is_cqr_scope_key(k)}


def effective_paths(model_path):
    mp = os.path.abspath(model_path); return mp, mp + '.evid', mp + '.query.json'


def task_dependencies(c):
    """the COMPLETE task dependency set of a cell: the model file, the reader's EFFECTIVE evidence file (<model>.evid, present or absent), the EFFECTIVE query spec
    (<model>.query.json, present or absent), the adapter blocks metadata when declared. ONE enumerator shared by the gate (hashing), the report and the closeout (re-hashing)."""
    mp = c.get('model_path')
    if not mp: return []
    mp, ep, qp = effective_paths(mp); deps = [mp, ep, qp]
    if c.get('blocks_path'): deps.append(c['blocks_path'])
    return deps


def dependency_closure_failures(RD, c, evidence):
    out = []; ev = {}
    for k, v in (evidence or {}).items(): ev.setdefault(os.path.basename(k), set()).add(v)
    for dep in task_dependencies(c):
        cur = sha(dep) if os.path.exists(dep) else None; got = ev.get(os.path.basename(dep))
        if got is None: out.append('task dependency %s of cell %s was not hashed by the gate (incomplete dependency closure)' % (os.path.basename(dep), c['cell_id']))
        elif cur not in got: out.append('task dependency %s of cell %s differs from the bytes the gate hashed (changed / replaced / missing)' % (os.path.basename(dep), c['cell_id']))
    return out


def bind_task_dependencies(c, fail):
    """hash model / .evid / .query.json (present or absent) into the gated set and compare with the frozen manifest hashes (absent .evid = sha256(b'0'); absent query = None)"""
    cid = c['cell_id']; ok = True; mp = c.get('model_path')
    if not mp: fail(cid, 'cell without a model path'); return False
    mp, ep, qp = effective_paths(mp)
    if c.get('evidence_path') is not None and os.path.abspath(c['evidence_path']) != ep: fail(cid, 'declared evidence_path does not identify the reader\'s effective evidence file %s' % os.path.basename(ep)); ok = False
    if c.get('query_path') is not None and os.path.abspath(c['query_path']) != qp: fail(cid, 'declared query_path does not identify the reader\'s effective query spec %s' % os.path.basename(qp)); ok = False
    hm = _ev(mp)
    if hm != c.get('model_sha256'): fail(cid, 'frozen input file %s differs from the manifest hash or is missing (input changed after freeze)' % os.path.basename(mp)); ok = False
    he = _ev(ep)
    if (he if he is not None else ZERO_HASH) != c.get('evidence_sha256'): fail(cid, 'task EVIDENCE file %s differs from the frozen evidence hash (present / absent / changed): the task on disk is not the frozen task' % os.path.basename(ep)); ok = False
    hq = _ev(qp)
    if hq != c.get('query_sha256'): fail(cid, 'task QUERY SPEC %s differs from the frozen query hash (present / absent / changed): the task on disk is not the frozen task' % os.path.basename(qp)); ok = False
    if c.get('blocks_path'): _ev(c['blocks_path'])
    return ok


def _rat_eq(a, b):
    """two tolerance spellings denote the same exact rational (the same semantics as the task parser; CQR-R6-03). Identical spellings are always equal (an INVALID_TASK cell's
    declaration and its on-disk spec may both carry an unparsable value such as 1/0: the binding still holds and the refusal is reported as such); otherwise both must parse to the
    same rational"""
    if str(a) == str(b): return True
    try: return F(str(a)) == F(str(b))
    except (ValueError, ZeroDivisionError, TypeError): return False


def _manifest_task_for(c, man):
    """the FROZEN task declaration the worker output must match (review CQR-04): the row's frozen query spec (mode / epsilon / delta / normalizer) when one exists, else the
    campaign default (PAC_EPS, all singletons, no normalizer)"""
    tp = c.get('task_params') or {}
    if c.get('query_sha256') and tp: return dict(epsilon=str(tp.get('epsilon')), delta=str(tp.get('delta')), mode=tp.get('mode', 'PAC_EPS'), normalizer_task=bool(tp.get('normalizer_task')))
    t = man.get('task') or {}; return dict(epsilon=str(t.get('epsilon', '1/200')), delta=str(t.get('delta', '1/1000000')), mode='PAC_EPS', normalizer_task=False)


def _identity_failures(cs, frozen_cqr):
    missing = [k for k in frozen_cqr if k not in cs]; differ = [k for k in frozen_cqr if k in cs and cs[k] != frozen_cqr[k]]; extra = [k for k in cs if k not in frozen_cqr]
    return missing, differ, extra


def answers_binding_failures(w, c):
    """the top-level `answers` list (what the report audits) must be the certificate's verified publication: one entry per query, lo / hi / point equal to publication.bounds /
    publication.point as exact strings, status UNDEFINED iff the bound is UNDEFINED; normalizer tasks: the single entry 'Z'. (The checker verifies the certificate; this binds the
    published answers to it -- an answers list the checker never reads could otherwise differ from the certified bounds.)"""
    out = []; cert = w.get('certificate') or {}; pub = cert.get('publication') or {}; ans = w.get('answers'); bounds = pub.get('bounds'); point = pub.get('point')
    if not isinstance(ans, list) or not isinstance(bounds, list) or not isinstance(point, list): return ['answers / certificate publication missing or malformed']
    if len(ans) != len(bounds) or len(bounds) != len(point): return ['answers count %d differs from the certified publication %d' % (len(ans), len(bounds))]
    normalizer = bool((c.get('task_params') or {}).get('normalizer_task'))
    for j, (a, (lo, hi), pt) in enumerate(zip(ans, bounds, point)):
        if normalizer and a.get('query') != 'Z': out.append('normalizer answer not labelled Z'); break
        if str(a.get('lo')) != str(lo) or str(a.get('hi')) != str(hi) or str(a.get('point')) != str(pt): out.append('answer %d (lo / hi / point) differs from the certified publication' % j); break
        if (a.get('status') == 'UNDEFINED') != (str(lo) == 'UNDEFINED'): out.append('answer %d definedness status differs from the certified publication' % j); break
    return out


def _check_cqr_cell(RD, cid, r, c, man, frozen_cqr, failures, fail, replay_factor, counters):
    for k in ('case_id', 'arm', 'replicate', 'budget_s', 'seed', 'model_sha256', 'evidence_sha256', 'query_sha256', 'cohort', 'kind'):
        if r.get(k) != c.get(k): fail(cid, 'receipt %s differs from the manifest' % k)
    wall = r.get('launch_relative_wall_s'); finite = isinstance(wall, (int, float)) and not isinstance(wall, bool) and wall == wall and 0 <= wall < float('inf')
    if not finite: fail(cid, 'receipt wall is not a finite nonnegative number (%s)' % wall)
    timely = finite and wall <= float(c['budget_s'])
    sup = r.get('supervisor') or {}; arm = c['arm']; wp = os.path.join(RD, r['worker_output']) if r.get('worker_output') else None
    # the task on disk must be the frozen task (model / .evid / .query.json) and the frozen task declaration must be the one the row recorded
    deps_ok = bind_task_dependencies(c, fail)
    if deps_ok and c.get('query_sha256'):
        try:
            spec = json.load(open(effective_paths(c['model_path'])[2])); qs = spec.get('queries') or []; tp = c.get('task_params') or {}
            if str(spec.get('mode', 'PAC_EPS')) != str(tp.get('mode')) or not _rat_eq(spec.get('epsilon', '1/200'), tp.get('epsilon')) or not _rat_eq(spec.get('delta', '1/1000000'), tp.get('delta')) or bool(spec.get('normalizer_task')) != bool(tp.get('normalizer_task')): fail(cid, 'the frozen task declaration (mode / epsilon / delta / normalizer) differs from the query spec on disk'); deps_ok = False
        except Exception as ex: fail(cid, 'query spec unreadable: %s' % type(ex).__name__); deps_ok = False
    status = r.get('status'); outcome = r.get('outcome')
    if wp is not None and os.path.exists(wp) and sha(wp) != r.get('output_sha256'): fail(cid, 'worker output sha256 differs from the receipt'); return
    if status == 'COMPLETED':
        counters['checked'] += 1; counters['cqr_checked'] += 1
        if sup.get('rc') != 0: fail(cid, 'COMPLETED with supervisor rc %s' % sup.get('rc'))
        if sup.get('outcome') != 'COMPLETED': fail(cid, 'COMPLETED with supervisor outcome %s' % sup.get('outcome'))
        if not timely: fail(cid, 'COMPLETED but recomputed launch-relative wall %s > budget %s' % (wall, c['budget_s']))
        if outcome != 'PUBLISHED': fail(cid, 'COMPLETED but outcome %s' % outcome)
        if not wp or not os.path.exists(wp): fail(cid, 'COMPLETED without a worker output file'); return
        _ev(wp); w = json.load(open(wp))
        if w.get('status') != 'COMPLETED' or w.get('outcome') != 'PUBLISHED': fail(cid, 'worker status / outcome %s / %s differ from the receipt' % (w.get('status'), w.get('outcome')))
        if w.get('late_publication'): fail(cid, 'worker records a late publication')
        if w.get('nonce') != r.get('nonce'): fail(cid, 'worker nonce differs from the receipt (stale or foreign output)')
        if w.get('seed') != c.get('seed'): fail(cid, 'worker seed differs from the manifest')
        if w.get('arm') != arm: fail(cid, 'worker arm differs from the planned arm')
        if w.get('guarantee_type') not in ('PAC', 'DETERMINISTIC'): fail(cid, 'completed CQR output without a guarantee type (%s)' % w.get('guarantee_type'))
        if r.get('guarantee_type') != w.get('guarantee_type'): fail(cid, 'receipt guarantee_type differs from the worker')
        if r.get('route') != w.get('route'): fail(cid, 'receipt route differs from the worker')
        if not (w.get('answers') or (w.get('intervals') is not None)): fail(cid, 'published without answers')
        for m in answers_binding_failures(w, c): fail(cid, 'answers: ' + m)
        missing, differ, extra = _identity_failures(w.get('candidate_sources') or {}, frozen_cqr)
        if missing: fail(cid, 'worker candidate source identity incomplete: %d frozen cqr sources not recorded (e.g. %s)' % (len(missing), missing[0]))
        if differ: fail(cid, 'worker candidate source %s differs from the frozen artifact' % differ[0])
        if extra: fail(cid, 'worker records %d sources outside the frozen cqr scope (e.g. %s)' % (len(extra), extra[0]))
        if not deps_ok: return
        mt = _manifest_task_for(c, man); dl = _deadline(replay_factor * float(c['budget_s'])); nf = len(failures)
        try: fails, info = CK.check_worker_output(c['model_path'], w, mt, arm, deadline=dl)
        except Exception as ex: fails, info = ['CHECKER FAULT: %s: %s' % (type(ex).__name__, str(ex)[:160])], {}
        for m in fails:
            if 'UNVERIFIABLE' in str(m): counters['unverifiable'] += 1; fail(cid, 'UNVERIFIABLE -- %s' % m)
            else: fail(cid, 'checker: %s' % m)
        if len(failures) == nf and _late(dl): fail(cid, 'UNVERIFIABLE -- the certificate verification finished after the cell allowance (%.3g s)' % (replay_factor * float(c['budget_s']))); counters['unverifiable'] += 1
        if len(failures) == nf:
            # the proof class is DERIVED by the checker from the validated route (review CQR-04): receipt and worker labels must equal it; the report consumes the receipt
            cls_, _ex = CK.guarantee_class_of_route(info.get('route')); att = info.get('attribution') or {}
            if r.get('guarantee_type') != cls_ or w.get('guarantee_type') != cls_: fail(cid, 'receipt / worker guarantee %s / %s differ from the class %s derived from route %s' % (r.get('guarantee_type'), w.get('guarantee_type'), cls_, info.get('route')))
            elif r.get('exact') not in (None, bool(_ex)) or bool(w.get('exact')) != bool(_ex): fail(cid, 'exact flag differs from the class derived from route %s' % info.get('route'))
            # report-facing attribution (second review R6): the receipt's and the worker's route / bias must equal the VERIFIED certificate's (the checker's authoritative attribution)
            if r.get('route') != att.get('route') or w.get('route') != att.get('route'): fail(cid, 'receipt / worker route %s / %s differ from the verified certificate route %s' % (r.get('route'), w.get('route'), att.get('route')))
            cb = att.get('compiled_bias')
            if cb is not None and ([str(_F(b)) for b in (r.get('bias') or [])] != [str(_F(b)) for b in cb] or [str(_F(b)) for b in (w.get('bias') or [])] != [str(_F(b)) for b in cb]): fail(cid, 'receipt / worker bias ledger differs from the verified certificate ledger %s' % cb)
            if cb is None and (r.get('bias') or w.get('bias')): fail(cid, 'receipt / worker carry a bias ledger but the verified certificate has no compiled model')
            _attrib[cid] = att
        if len(failures) == nf:
            counters['gated'] += 1; counters['cqr_verified'] += 1
            if w.get('guarantee_type') == 'PAC': counters['pac_verified'] += 1
        return
    if outcome == 'PUBLISHED': fail(cid, 'non-COMPLETED receipt with outcome PUBLISHED')
    if outcome == 'PROVED_ZERO_EVIDENCE':
        counters['zero_checked'] += 1
        if not timely: fail(cid, 'zero-evidence claim after the budget (late proof is not a timely result)')
        if sup.get('rc') != 0 or 'KILL' in str(sup.get('outcome')): fail(cid, 'zero-evidence claim with supervisor rc %s / outcome %s' % (sup.get('rc'), sup.get('outcome')))
        if not wp or not os.path.exists(wp): fail(cid, 'zero-evidence claim without a worker output'); return
        _ev(wp); w = json.load(open(wp))
        if w.get('status') != 'STOPPED' or w.get('outcome') != 'PROVED_ZERO_EVIDENCE' or w.get('late_proof'): fail(cid, 'zero-evidence claim without a recorded timely proof')
        if w.get('nonce') != r.get('nonce') or w.get('seed') != c.get('seed') or w.get('arm') != arm: fail(cid, 'zero-evidence output nonce / seed / arm differ from the cell')
        if r.get('guarantee_type') != w.get('guarantee_type') or w.get('guarantee_type') != 'DETERMINISTIC': fail(cid, 'zero-evidence proof must carry the DETERMINISTIC guarantee in both the worker and the receipt')
        missing, differ, extra = _identity_failures(w.get('candidate_sources') or {}, frozen_cqr)
        if missing or differ or extra: fail(cid, 'zero-evidence output source identity incomplete or differs from the frozen cqr scope')
        if not deps_ok: return
        mt = _manifest_task_for(c, man); dl = _deadline(replay_factor * float(c['budget_s'])); nf = len(failures)
        try: fails, info = CK.check_worker_output(c['model_path'], w, mt, arm, deadline=dl)
        except Exception as ex: fails = ['CHECKER FAULT: %s: %s' % (type(ex).__name__, str(ex)[:160])]
        for m in fails:
            if 'UNVERIFIABLE' in str(m): counters['unverifiable'] += 1; fail(cid, 'UNVERIFIABLE -- zero proof: %s' % m)
            else: fail(cid, 'zero-evidence proof NOT re-derivable: %s' % m)
        if len(failures) == nf and _late(dl): fail(cid, 'UNVERIFIABLE -- the zero-proof verification finished after the cell allowance'); counters['unverifiable'] += 1
        if len(failures) == nf: counters['zero_verified'] += 1
        return
    if r.get('guarantee_type') in ('PAC', 'DETERMINISTIC'): fail(cid, 'guarantee claimed without publication')
    if status in ('LATE_OUTPUT',) and outcome != 'DEADLINE': fail(cid, 'late output not classified DEADLINE')
    if wp and os.path.exists(wp): _ev(wp)


def global_preflight(RD, manifest_name, man, mh, fail, inventory_on_disk, kernel_on_disk):
    """the frozen gate's GLOBAL PREFLIGHT (extracted verbatim from main for the successor verification path, repair-2 review CQR-AF2-01; main calls it with the code on disk):
    frozen kernel identity vs `kernel_on_disk` for every tag a planned arm loads; CAMPAIGN_START binds the manifest and the frozen inventory content hash; the ledger's first row is a
    CAMPAIGN_START binding the same hashes; no MANIFEST_AMENDMENT_* file; the frozen inventory is the COMPLETE required set and equals `inventory_on_disk`; registry identity failures
    (frozen and on disk); planned ids unique, arms / cohorts registered; receipts on disk unique per cell, exactly the planned set (missing = NOT_RUN failure, unknown = failure).
    Returns dict(ch, ah, frozen_cqr, frozen_candidate, frozen_b0, cells, receipts, unavailable_artifacts, differ) -- `differ` = frozen keys whose on-disk hash differs (main fails on any)."""
    ch = man.get('candidate_artifact_hashes') or {}; ah = hashlib.sha256(json.dumps(ch, sort_keys=True).encode()).hexdigest() if ch else None
    planned_arms = sorted({c['arm'] for c in (man.get('cells') or [])})
    if not man.get('kernel_identity'): fail('*', 'manifest carries no frozen kernel_identity (every natively loaded binary + build record; review CQR-09)')
    else:
        # the identity ON DISK at gate time must equal the frozen one for every tag a planned arm loads (launch/resume compare it too; closeout compares it again)
        for m_ in KI.failures_vs_frozen(man['kernel_identity'], kernel_on_disk, planned_arms): fail('*', 'kernel identity at gate: ' + m_)
    sp = os.path.join(RD, 'CAMPAIGN_START.json')
    if not os.path.exists(sp): fail('*', 'CAMPAIGN_START.json missing (no pre-execution binding of the manifest)')
    else:
        st = json.load(open(sp))
        if st.get('manifest_sha256') != mh: fail('*', 'CAMPAIGN_START manifest sha256 %s differs from the manifest file on disk %s' % (str(st.get('manifest_sha256'))[:16], mh[:16]))
        if st.get('manifest') not in (None, manifest_name): fail('*', 'CAMPAIGN_START names a different manifest file')
        if st.get('artifact_hashes_sha256') != ah: fail('*', 'CAMPAIGN_START does not bind the content hash of the frozen source inventory')
    lp = os.path.join(RD, LEDGER); first_start = None
    if os.path.exists(lp):
        for line in open(lp):
            if not line.strip(): continue
            try: rr = json.loads(line)
            except Exception: continue
            if rr.get('kind') == 'CAMPAIGN_START': first_start = rr; break
        if first_start is None: fail('*', 'ledger without a CAMPAIGN_START row')
        else:
            if first_start.get('manifest_sha256') != mh: fail('*', 'ledger CAMPAIGN_START manifest sha256 differs from the manifest on disk')
            if first_start.get('artifact_hashes_sha256') != ah: fail('*', 'ledger CAMPAIGN_START does not bind the frozen source inventory content hash')
    else: fail('*', '%s missing' % LEDGER)
    if glob.glob(os.path.join(RD, 'MANIFEST_AMENDMENT_*')): fail('*', 'artifact amendment files present: the frozen identity is immutable (no amendment mechanism)')
    # ---- frozen source identity: the COMPLETE inventory (baseline scopes + cqr scope), equal to the files on disk
    want = inventory_on_disk
    if not isinstance(ch, dict) or not ch or any('/' not in k for k in ch): fail('*', 'manifest candidate_artifact_hashes must be a per-directory map'); ch = {}
    missing_keys = sorted(k for k in want if k not in ch); extra_keys = sorted(k for k in ch if k not in want)
    if missing_keys: fail('*', 'frozen source inventory INCOMPLETE: %d required sources missing (e.g. %s)' % (len(missing_keys), missing_keys[0]))
    if extra_keys: fail('*', 'frozen source inventory lists %d sources that are not in the required scopes (e.g. %s)' % (len(extra_keys), extra_keys[0]))
    differ = sorted(k for k in want if k in ch and ch[k] != want[k])
    planned_arms_ = sorted({c_['arm'] for c_ in man.get('cells') or []})
    id_fail, unavailable_artifacts = PR.identity_failures(ch, planned_arms_) if isinstance(ch, dict) and ch else ([], [])
    for f_ in id_fail: fail('*', f_)
    id_fail_disk, _u = PR.identity_failures(want, planned_arms_)
    for f_ in id_fail_disk:
        if f_ not in id_fail: fail('*', 'ON DISK: ' + f_)
    frozen_cqr = cqr_scope(ch)
    if not frozen_cqr: fail('*', 'manifest carries no frozen cqr scope (cqr/*.py + newarm/core.py)')
    frozen_candidate = {k: v for k, v in ch.items() if PR.scope_of_key(k) == 'candidate'}
    frozen_b0 = {k: v for k, v in ch.items() if PR.scope_of_key(k) == 'b0_frozen_v14'}
    # ---- plan integrity
    ids = [c['cell_id'] for c in man['cells']]
    if len(ids) != len(set(ids)): fail('*', 'duplicate planned cell ids in the manifest: %d duplicates' % (len(ids) - len(set(ids))))
    cells = {c['cell_id']: c for c in man['cells']}
    for c in man['cells']:
        if c['arm'] not in R.ARMS: fail(c['cell_id'], 'planned arm %s is not in the registry' % c['arm'])
        if c['cohort'] not in R.COHORTS: fail(c['cell_id'], 'planned cohort %s is not in the registry' % c['cohort'])
    receipts = {}
    for rp in glob.glob(os.path.join(RD, 'cells', '*', 'receipt.json')):
        r = json.load(open(rp)); cid = r.get('cell_id')
        if cid in receipts: fail(cid, 'duplicate receipt: %s and %s' % (receipts[cid]['_path'], rp)); continue
        r['_path'] = rp; r['_sha'] = sha(rp); receipts[cid] = r
    for cid in cells:
        if cid not in receipts: fail(cid, 'planned cell without receipt (NOT_RUN)')
    for cid in receipts:
        if cid not in cells: fail(cid, 'receipt for a cell not in the frozen manifest')
    return dict(ch=ch, ah=ah, frozen_cqr=frozen_cqr, frozen_candidate=frozen_candidate, frozen_b0=frozen_b0, cells=cells, receipts=receipts, unavailable_artifacts=unavailable_artifacts, differ=differ)


def main(RD, manifest_name='CAMPAIGN_MANIFEST.json', out_path=None, replay_factor=REPLAY_FACTOR, gate_budget_s=None):
    RD = os.path.abspath(RD); failures = []; t_gate = time.monotonic(); _evidence.clear(); PG._evidence.clear(); exhausted_at = None
    _agg['deadline'] = (t_gate + float(gate_budget_s)) if gate_budget_s else None; PG._agg['deadline'] = _agg['deadline']
    if replay_factor is None or not (replay_factor > 0) or replay_factor != replay_factor: return _write(RD, out_path, dict(gate_version=GATE_VERSION, failures=[('*', 'invalid replay factor %r' % (replay_factor,))], gate_passed=False))
    def fail(cid, msg): failures.append((cid, msg))
    mp = os.path.join(RD, manifest_name)
    if not os.path.exists(mp): fail('*', 'manifest %s missing' % manifest_name); return _write(RD, out_path, dict(gate_version=GATE_VERSION, failures=failures, gate_passed=False))
    man = json.load(open(mp)); mh = sha(mp)
    if man.get('schema') != 'cqr_campaign_manifest_v1': fail('*', 'manifest schema %s is not cqr_campaign_manifest_v1' % man.get('schema'))
    pf = global_preflight(RD, manifest_name, man, mh, fail, R.full_inventory(CODE), KI.collect(CODE))
    if pf['differ']: fail('*', 'frozen source %s differs from the file on disk (%d differ)' % (pf['differ'][0], len(pf['differ'])))
    ch = pf['ch']; ah = pf['ah']; frozen_cqr = pf['frozen_cqr']; frozen_candidate = pf['frozen_candidate']; frozen_b0 = pf['frozen_b0']; cells = pf['cells']; receipts = pf['receipts']; unavailable_artifacts = pf['unavailable_artifacts']
    task = man.get('task') or {}; EPS = F(str(task.get('epsilon', '1/200'))); models = {}; gated_set = []
    counters = dict(checked=0, gated=0, pac_verified=0, cqr_checked=0, cqr_verified=0, zero_checked=0, zero_verified=0, unverifiable=0, baseline_checked=0)
    _attrib.clear()
    for cid in sorted(receipts):
        r = receipts[cid]; c = cells.get(cid)
        if not c: continue
        entry = dict(cell_id=cid, receipt_sha256=r['_sha'], output_sha256=r.get('output_sha256'), status=r.get('status'), outcome=r.get('outcome'), guarantee=r.get('guarantee_type'), arm=c['arm'], cohort=c['cohort'], budget_s=c['budget_s'], case_id=c['case_id'], replicate=c['replicate'], kind=c.get('kind'), evidence={}, verified=False, verified_attribution=_attrib.get(cid)); gated_set.append(entry)
        if exhausted_at is not None: fail(cid, 'UNVERIFIABLE -- aggregate verification budget exhausted before this cell was checked'); continue
        _cell_paths.clear(); PG._cell_paths.clear(); nf_before = len(failures)
        try:
            if R.validator_of(c['arm']) == 'cqr_candidate': _check_cqr_cell(RD, cid, r, c, man, frozen_cqr, failures, fail, replay_factor, counters)
            else:
                n0 = counters['checked']; bind_task_dependencies(c, fail)              # the EFFECTIVE dependency set incl. .query.json for every arm (the baseline enumerator knows only its own cohorts)
                PG._check_cell(RD, cid, r, c, man, frozen_candidate, frozen_b0, models, failures, fail, EPS, replay_factor, counters)
                counters['baseline_checked'] += counters['checked'] - n0
            # LOADED-KERNEL PROVENANCE for EVERY arm whose worker may dlopen a native kernel (structured review CQR-S1-03: the CQR arms load the newarm kernels through the structural backend;
            # the recorded loaded artifact of the worker output -- not the disk at check time -- is compared with the frozen identity)
            if man.get('kernel_identity') and r.get('worker_output') and os.path.exists(os.path.join(RD, r['worker_output'])) and KI.tags_needed_by(c['arm']):
                try: w_ = json.load(open(os.path.join(RD, r['worker_output'])))
                except (ValueError, OSError): w_ = None
                if w_ is not None:
                    for m_ in KI.receipt_failures(man['kernel_identity'], w_, c['arm']): fail(cid, 'loaded kernel provenance: ' + m_)
                    if R.validator_of(c['arm']) == 'cqr_candidate': counters['cqr_provenance_checked'] = counters.get('cqr_provenance_checked', 0) + 1
        except (GateBudgetExhausted, PG.GateBudgetExhausted): exhausted_at = cid; fail(cid, 'UNVERIFIABLE -- aggregate verification budget exhausted while checking this cell')
        entry['verified_attribution'] = _attrib.get(cid)                     # the checker's authoritative attribution (R6), known only after the check
        paths = set(_cell_paths) | set(PG._cell_paths)
        for p_ in PG._cell_paths: _evidence[p_] = PG._evidence.get(p_)
        entry['evidence'] = {(os.path.relpath(k, RD) if k.startswith(RD + os.sep) else k): _evidence.get(k) for k in sorted(paths)}; entry['verified'] = (len(failures) == nf_before)
    if _agg['deadline'] is not None and time.monotonic() > _agg['deadline'] and exhausted_at is None and gated_set:
        exhausted_at = gated_set[-1]['cell_id']; fail(exhausted_at, 'UNVERIFIABLE -- the gate finished after its aggregate budget (final acceptance clock check)'); gated_set[-1]['verified'] = False
    gs = hashlib.sha256(json.dumps(gated_set, sort_keys=True).encode()).hexdigest()
    res = dict(gate_version=GATE_VERSION, manifest=manifest_name, manifest_sha256=mh, artifact_hashes_sha256=ah, planned=len(cells), receipts=len(receipts), completed_checked=counters['checked'], completed_gated=counters['gated'], counters=counters, failures=failures, gate_passed=not failures, gated_set=gated_set, gated_set_sha256=gs,
               gate_wall_s=round(time.monotonic() - t_gate, 3), replay_factor=replay_factor, gate_budget_s=gate_budget_s, budget_exhausted_at_cell=exhausted_at, unavailable_artifacts_not_needed_by_planned_arms=unavailable_artifacts, checker_version=CK.CHECKER_VERSION, baseline_gate_version=PG.GATE_VERSION,
               verification_policy='every receipt is checked in cell-id order; CQR cells by the independent checker under replay_factor x budget; baseline cells by the frozen pac gate; a check exceeding its allowance or the aggregate budget is UNVERIFIABLE (a failure, never an acceptance); the gated set hashes every receipt, output and effective task dependency')
    return _write(RD, out_path, res)


def _write(RD, out_path, res):
    out_path = out_path or os.path.join(RD, 'GATE_RESULT.json')
    json.dump(res, open(out_path, 'w'), indent=1); print(json.dumps({k: res.get(k) for k in ('gate_version', 'planned', 'receipts', 'completed_checked', 'completed_gated', 'counters', 'gate_passed', 'gated_set_sha256', 'gate_wall_s')}, default=str)[:600])
    for f in res['failures'][:40]: print('  ', str(f)[:300])
    if len(res['failures']) > 40: print('   ... %d more failures' % (len(res['failures']) - 40))
    return 0 if res['gate_passed'] else 1


if __name__ == '__main__':
    mn = sys.argv[sys.argv.index('--manifest') + 1] if '--manifest' in sys.argv else 'CAMPAIGN_MANIFEST.json'; op = sys.argv[sys.argv.index('--out') + 1] if '--out' in sys.argv else None
    rf = float(sys.argv[sys.argv.index('--replay-factor') + 1]) if '--replay-factor' in sys.argv else REPLAY_FACTOR; gb = float(sys.argv[sys.argv.index('--gate-budget-s') + 1]) if '--gate-budget-s' in sys.argv else None
    try: rc = main(sys.argv[1], mn, op, rf, gb)
    except Exception as ex:
        import traceback; rc = _write(os.path.abspath(sys.argv[1]), op, dict(gate_version=GATE_VERSION, failures=[('*', 'GATE FAULT: %s: %s' % (type(ex).__name__, str(ex)[:200]))], gate_passed=False, fault_trace=traceback.format_exc()[-2000:]))
    sys.exit(rc)
