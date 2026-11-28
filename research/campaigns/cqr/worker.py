"""Fresh-process WORKER for one CQR cell. Launch-relative absolute deadline; source read (SHARED reader; '<model>.evid'; optional '<model>.query.json'); solve under the
named arm; EVERY terminal outcome deadline-checked; typed outcomes: PUBLISHED (DETERMINISTIC | PAC), PROVED_ZERO_EVIDENCE, DEADLINE, MEMORY, FAULT. Records: binding
(sha256 of the consumed files), task identity, seed, nonce, the complete candidate source identity (cex/cqr + cex/newarm core reader), the certificate, publication
in BOTH forms: `answers` (per original query: lo, hi, point, status) and -- when the task is the legacy all-singleton contract -- `intervals` / `points` rows per original
variable (outward 8-digit decimals, simplex rows) so the legacy comparators / references apply unchanged.
    python -m research.campaigns.cqr.worker --input CASE.uai --output out.json --arm ARM --deadline ABS --seed S --nonce N [--budget B] [--mode MODE]"""
from ._paths import HERE, ROOT, CODE, CEX, PAC, NEWARM, RUNTIME, PY, runs_root, source_path, subprocess_env
import argparse, json, os, sys, time, hashlib, resource
from fractions import Fraction as F
sys.set_int_max_str_digits(0)
from pgm.algorithms.cqr import task as TK; from pgm.algorithms.cqr import solve as SV
from pgm.algorithms.cqr import diag as DG
WORKER_VERSION = 'cqr-worker-v2.1 (2026-11-17, structured review: table-derived legacy rows; monotonic clock origin in the sidecar; v2.0: diagnostics sidecar <output>.diag.json + journal created BEFORE parsing and finalized on every outcome (survives graceful deadlines and hard kills as a durable prefix); structural routes; cumulative-credit reference scheduling)'


def jsonable(x):
    if isinstance(x, F): return str(x)
    if isinstance(x, dict): return {str(k): jsonable(v) for k, v in x.items()}
    if isinstance(x, (tuple, list)): return [jsonable(v) for v in x]
    if isinstance(x, set): return sorted(jsonable(v) for v in x)
    if isinstance(x, float) and x != x: return None
    return x


def candidate_sources():
    """the CQR candidate identity scope: registry.cqr_source_inventory (ONE definition; production modules of cex/cqr + the shared reader cex/newarm/core.py)"""
    from research.campaigns.cqr import registry as _r
    return _r.cqr_source_inventory(CODE)


def legacy_rows(task, pub, eps):
    """rows per ORIGINAL variable from an all-singleton publication: intervals (lo, hi) and the feasible point, exact Fractions"""
    cards = task['model']['cards']; idx = {}
    for j, q in enumerate(task['queries']):
        sv = TK.singleton_indicator_of(q, cards)             # placement derived from the TABLE, never from the output metadata (structured review CQR-S1-01)
        if sv is not None: idx[sv] = j
    iv = []; pt = []
    for v in range(len(cards)):
        row_i = []; row_p = []
        for s in range(cards[v]):
            j = idx[(v, s)]; lo, hi = pub['bounds'][j]; row_i.append((F(lo), F(hi))); row_p.append(F(pub['point'][j]))
        iv.append(row_i); pt.append(row_p)
    return iv, pt


def main():
    ap = argparse.ArgumentParser(); ap.add_argument('--input', required=True); ap.add_argument('--output', required=True); ap.add_argument('--arm', required=True); ap.add_argument('--deadline', type=float, required=True)
    ap.add_argument('--seed', required=True); ap.add_argument('--nonce', required=True); ap.add_argument('--budget', type=float, default=None); ap.add_argument('--mode', default=None); ap.add_argument('--cap-bytes', type=int, default=None); ap.add_argument('--fault-inject', default=None)
    ap.add_argument('--no-diag', action='store_true', help='no diagnostics sidecar (in-process controls only; production cells always carry one)')
    a = ap.parse_args(); t = time.monotonic()
    out = dict(status='STARTED', worker_version=WORKER_VERSION, solver_version=SV.SOLVER_VERSION, arm=a.arm, seed=a.seed, nonce=a.nonce, deadline_abs=a.deadline, budget_s=a.budget, candidate_sources=candidate_sources(), host_pid=os.getpid())
    # ---- the DIAGNOSTICS SIDECAR (eighth-round revision, section 2): created BEFORE parsing, outside the publication file, atomically rewritten at bounded intervals and finalized on
    # every outcome; a hard kill leaves the last checkpoint + the durable journal prefix (freshness recorded inside). Never consulted by the certificate or the checker.
    D = None; dpath = (a.output[:-5] if a.output.endswith('.json') else a.output) + '.diag.json'
    if not a.no_diag:
        try: D = DG.Diagnostics(dpath, dict(arm=a.arm, seed=a.seed, nonce=a.nonce, input=os.path.basename(a.input), deadline_abs=a.deadline, budget_s=a.budget, worker_version=WORKER_VERSION, solver_version=SV.SOLVER_VERSION, pid=os.getpid(), monotonic_t0=t, clock='time.monotonic() of this host: elapsed_s + monotonic_t0 is comparable with a supervisor\'s monotonic kill time (CQR-S1-06)'), t, a.deadline); D.state['deadline']['budget_s'] = a.budget; D.phase('parse')
        except OSError as ex: out['diag_error'] = 'sidecar unavailable: %s' % str(ex)[:120]; D = None
    out['diag_sidecar'] = dpath if D is not None else None
    def finish(status, outcome, reason=None):
        if D is not None:
            try: out['diag'] = D.final(status, outcome, reason)
            except Exception as ex: out['diag_error'] = 'final checkpoint failed: %s' % str(ex)[:120]
    try: resource.setrlimit(resource.RLIMIT_AS, (3 * 1024 ** 3, 3 * 1024 ** 3)); out['memory_policy'] = 'RLIMIT_AS 3 GiB'
    except (ValueError, OSError) as e: out['memory_policy'] = 'RLIMIT_AS unavailable (%s); the supervisor enforces 3 GiB by sampled process-tree RSS' % e
    late = lambda: time.monotonic() >= a.deadline
    try:
        try: task = TK.load_task(a.input, mode=a.mode)
        except (ValueError, ZeroDivisionError, TypeError, KeyError, json.JSONDecodeError) as e:
            # the task is outside the supported input domain (mode / tolerance / query schema / malformed rational such as 1/0): a typed refusal BEFORE any inference (fifth review, CQR-R4-03); never a FAULT
            out.update(status='STOPPED', outcome='INVALID_TASK', guarantee_type='NONE', reason='INVALID_TASK: %s' % str(e)[:400], worker_elapsed_s=time.monotonic() - t); finish('STOPPED', 'INVALID_TASK', str(e)[:200])
            tmp = a.output + '.tmp'; open(tmp, 'w').write(json.dumps(jsonable(out), indent=1, default=str)); os.replace(tmp, a.output); return
        out['binding'] = task['binding']; out['task_identity'] = TK.task_identity(task); out['mode'] = task['mode']; out['epsilon'] = str(task['epsilon']); out['delta'] = str(task['delta'])
        out['queries'] = [q.to_json() | dict(name=q.name) for q in task['queries']] if len(task['queries']) <= 64 else dict(count=len(task['queries']), all_singletons=task['all_singletons'])
        out['parse_s'] = time.monotonic() - t
        kw = {}
        if D is not None: kw['diag'] = D; D.cost('parse', out['parse_s']); D.set('identity', task_identity=out['task_identity'], mode=task['mode'], queries=len(task['queries'])); D.phase('solve')
        if a.cap_bytes is not None: kw['cap_bytes'] = a.cap_bytes; out['memory_policy'] = (out.get('memory_policy') or '') + '; solver optional-work cancellation cap %d bytes (CLI)' % a.cap_bytes
        if a.fault_inject:
            fi = json.loads(a.fault_inject) if a.fault_inject.strip().startswith('{') else a.fault_inject          # dict(op, where, k) = mid-operator injection (after factor / query / decoder construction, before or after the atomic swap)
            kw['fault_inject'] = fi; out['fault_injected'] = fi
        r = SV.solve(task, a.deadline, a.arm, a.seed, **kw)
        out['outcome'] = r['outcome']; out['guarantee_type'] = r['guarantee_type']; out['certificate'] = r['certificate']; out['stats'] = r['stats']
        if r['outcome'] == 'PROVED_ZERO_EVIDENCE':
            out['zero_evidence_proof'] = r['zero_proof']; out['status'] = 'STOPPED'
            if late(): out['outcome'] = 'DEADLINE'; out['guarantee_type'] = 'NONE'; out['late_proof'] = True; out['reason'] = 'zero-evidence proof completed after the deadline'
            else: out['reason'] = 'ZERO_EVIDENCE (%s)' % r['zero_proof'].get('kind')
            finish('STOPPED', out['outcome'], out['reason'])
        else:
            pub = r['publication']; eps = task['epsilon']
            if (task.get('query_spec') or {}).get('normalizer_task'): out['answers'] = [dict(query='Z', lo=str(pub['bounds'][0][0]), hi=str(pub['bounds'][0][1]), point=str(pub['point'][0]), status='OK', contract='relative error %s: point in [(1-eps) U, (1+eps) L]' % task['epsilon'])]
            else: out['answers'] = [dict(query=task['queries'][j].name, lo=str(lo), hi=str(hi), point=str(pub['point'][j]), status=('UNDEFINED' if lo == 'UNDEFINED' else 'OK')) for j, (lo, hi) in enumerate(pub['bounds'])]
            out['route'] = pub['route']; out['bias'] = r.get('bias'); out['exact'] = bool(pub.get('exact'))
            if task['all_singletons'] and all(x[0] != 'UNDEFINED' for x in pub['bounds']):
                from pgm.algorithms.structural import core
                iv, pt = legacy_rows(task, pub, eps); core.verify_output(iv, pt, eps); out['publication_check'] = True
                pt_ = time.monotonic(); out['legacy_digits'] = TK.legacy_digits(eps); out['intervals'], out['points'] = core.publish(iv, pt, digits=out['legacy_digits'], epsilon=eps); out['publication_s'] = time.monotonic() - pt_
            if D is not None: D.cost('publication', out.get('publication_s') or 0.0)
            if late(): out['status'] = 'STOPPED'; out['outcome'] = 'DEADLINE'; out['guarantee_type'] = 'NONE'; out['reason'] = 'publication completed after the deadline'; out['late_publication'] = True; out.pop('intervals', None); out.pop('points', None); out.pop('answers', None)
            else: out['status'] = 'COMPLETED'
            finish(out['status'], out['outcome'], out.get('reason') or out.get('route'))
    except SV.Stop as e:
        out['status'] = 'STOPPED'; out['outcome'] = e.kind; out['guarantee_type'] = 'NONE'; out['reason'] = '%s %s' % (e.kind, json.dumps(jsonable(e.info))[:200])
        out['scheduling'] = jsonable(e.info)                 # reference progress / work ledgers at the typed stop (instrumentation; never a claim)
        finish('STOPPED', e.kind, out['reason'])
    except MemoryError:
        out['status'] = 'STOPPED'; out['outcome'] = 'MEMORY'; out['guarantee_type'] = 'NONE'; out['reason'] = 'MemoryError'; finish('STOPPED', 'MEMORY', 'MemoryError')
    except Exception as e:
        out['status'] = 'STOPPED'; out['exception_type'] = type(e).__name__; out['reason'] = str(e)[:500]; out['guarantee_type'] = 'NONE'
        out['outcome'] = 'DEADLINE' if late() else ('NUMERICAL_RANGE_OR_PRECISION' if isinstance(e, (OverflowError, ZeroDivisionError)) else 'FAULT')
        if out['outcome'] == 'FAULT': out['fault_note'] = 'an unclassified exception: investigate (never a refusal of the model)'
        finish('STOPPED', out['outcome'], '%s: %s' % (type(e).__name__, str(e)[:200]))
    out['worker_elapsed_s'] = time.monotonic() - t; ru = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss; out['peak_rss_bytes'] = ru if sys.platform == 'darwin' else ru * 1024
    if D is not None and 'diag' not in out: finish(out.get('status'), out.get('outcome'), out.get('reason'))
    tmp = a.output + '.tmp'; open(tmp, 'w').write(json.dumps(jsonable(out), indent=1, default=str)); os.replace(tmp, a.output)


if __name__ == '__main__': main()
