"""Fresh-process WORKER for one CQR cell. Launch-relative absolute deadline; source read (SHARED reader; '<model>.evid'; optional '<model>.query.json'); solve under the
named arm; EVERY terminal outcome deadline-checked; typed outcomes: PUBLISHED (DETERMINISTIC | PAC), PROVED_ZERO_EVIDENCE, DEADLINE, MEMORY, FAULT. Records: binding
(sha256 of the consumed files), task identity, seed, nonce, the complete candidate source identity (cex/cqr + cex/newarm core reader), the certificate, publication
in BOTH forms: `answers` (per original query: lo, hi, point, status) and -- when the task is the legacy all-singleton contract -- `intervals` / `points` rows per original
variable (outward 8-digit decimals, simplex rows) so the legacy comparators / references apply unchanged.
    python cex/cqr/worker.py --input CASE.uai --output out.json --arm ARM --deadline ABS --seed S --nonce N [--budget B] [--mode MODE]"""
import argparse, json, os, sys, time, hashlib, resource
from fractions import Fraction as F
sys.set_int_max_str_digits(0)
HERE = os.path.dirname(os.path.abspath(__file__)); CODE = os.path.dirname(os.path.dirname(HERE)); NEWARM = os.path.join(os.path.dirname(HERE), 'newarm')
for p in (HERE, NEWARM):
    if p not in sys.path: sys.path.insert(0, p)
import task as TK, solve as SV
WORKER_VERSION = 'cqr-worker-v1 (2026-11-16)'


def jsonable(x):
    if isinstance(x, F): return str(x)
    if isinstance(x, dict): return {str(k): jsonable(v) for k, v in x.items()}
    if isinstance(x, (tuple, list)): return [jsonable(v) for v in x]
    if isinstance(x, set): return sorted(jsonable(v) for v in x)
    if isinstance(x, float) and x != x: return None
    return x


def candidate_sources():
    """the CQR candidate identity scope: registry.cqr_source_inventory (ONE definition; production modules of cex/cqr + the shared reader cex/newarm/core.py)"""
    import registry as _r
    return _r.cqr_source_inventory(CODE)


def legacy_rows(task, pub, eps):
    """rows per ORIGINAL variable from an all-singleton publication: intervals (lo, hi) and the feasible point, exact Fractions"""
    cards = task['model']['cards']; idx = {}
    for j, q in enumerate(task['queries']):
        o = q.output or {}
        if o.get('kind') == 'singleton': idx[(o['variable'], o['state'])] = j
    iv = []; pt = []
    for v in range(len(cards)):
        row_i = []; row_p = []
        for s in range(cards[v]):
            j = idx[(v, s)]; lo, hi = pub['bounds'][j]; row_i.append((F(lo), F(hi))); row_p.append(F(pub['point'][j]))
        iv.append(row_i); pt.append(row_p)
    return iv, pt


def main():
    ap = argparse.ArgumentParser(); ap.add_argument('--input', required=True); ap.add_argument('--output', required=True); ap.add_argument('--arm', required=True); ap.add_argument('--deadline', type=float, required=True)
    ap.add_argument('--seed', required=True); ap.add_argument('--nonce', required=True); ap.add_argument('--budget', type=float, default=None); ap.add_argument('--mode', default=None)
    a = ap.parse_args(); t = time.monotonic()
    out = dict(status='STARTED', worker_version=WORKER_VERSION, solver_version=SV.SOLVER_VERSION, arm=a.arm, seed=a.seed, nonce=a.nonce, deadline_abs=a.deadline, budget_s=a.budget, candidate_sources=candidate_sources(), host_pid=os.getpid())
    try: resource.setrlimit(resource.RLIMIT_AS, (3 * 1024 ** 3, 3 * 1024 ** 3)); out['memory_policy'] = 'RLIMIT_AS 3 GiB'
    except (ValueError, OSError) as e: out['memory_policy'] = 'RLIMIT_AS unavailable (%s); the supervisor enforces 3 GiB by sampled process-tree RSS' % e
    late = lambda: time.monotonic() >= a.deadline
    try:
        task = TK.load_task(a.input, mode=a.mode); out['binding'] = task['binding']; out['task_identity'] = TK.task_identity(task); out['mode'] = task['mode']; out['epsilon'] = str(task['epsilon']); out['delta'] = str(task['delta'])
        out['queries'] = [q.to_json() | dict(name=q.name) for q in task['queries']] if len(task['queries']) <= 64 else dict(count=len(task['queries']), all_singletons=task['all_singletons'])
        out['parse_s'] = time.monotonic() - t
        r = SV.solve(task, a.deadline, a.arm, a.seed)
        out['outcome'] = r['outcome']; out['guarantee_type'] = r['guarantee_type']; out['certificate'] = r['certificate']; out['stats'] = r['stats']
        if r['outcome'] == 'PROVED_ZERO_EVIDENCE':
            out['zero_evidence_proof'] = r['zero_proof']; out['status'] = 'STOPPED'
            if late(): out['outcome'] = 'DEADLINE'; out['guarantee_type'] = 'NONE'; out['late_proof'] = True; out['reason'] = 'zero-evidence proof completed after the deadline'
            else: out['reason'] = 'ZERO_EVIDENCE (%s)' % r['zero_proof'].get('kind')
        else:
            pub = r['publication']; eps = task['epsilon']
            if (task.get('query_spec') or {}).get('normalizer_task'): out['answers'] = [dict(query='Z', lo=str(pub['bounds'][0][0]), hi=str(pub['bounds'][0][1]), point=str(pub['point'][0]), status='OK', contract='relative error %s: point in [(1-eps) U, (1+eps) L]' % task['epsilon'])]
            else: out['answers'] = [dict(query=task['queries'][j].name, lo=str(lo), hi=str(hi), point=str(pub['point'][j]), status=('UNDEFINED' if lo == 'UNDEFINED' else 'OK')) for j, (lo, hi) in enumerate(pub['bounds'])]
            out['route'] = pub['route']; out['bias'] = r.get('bias')
            if task['all_singletons'] and all(x[0] != 'UNDEFINED' for x in pub['bounds']):
                import core
                iv, pt = legacy_rows(task, pub, eps); core.verify_output(iv, pt, eps); out['publication_check'] = True
                pt_ = time.monotonic(); out['intervals'], out['points'] = core.publish(iv, pt, epsilon=eps); out['publication_s'] = time.monotonic() - pt_
            if late(): out['status'] = 'STOPPED'; out['outcome'] = 'DEADLINE'; out['guarantee_type'] = 'NONE'; out['reason'] = 'publication completed after the deadline'; out['late_publication'] = True; out.pop('intervals', None); out.pop('points', None); out.pop('answers', None)
            else: out['status'] = 'COMPLETED'
    except SV.Stop as e:
        out['status'] = 'STOPPED'; out['outcome'] = e.kind; out['guarantee_type'] = 'NONE'; out['reason'] = '%s %s' % (e.kind, json.dumps(jsonable(e.info))[:200])
    except MemoryError:
        out['status'] = 'STOPPED'; out['outcome'] = 'MEMORY'; out['guarantee_type'] = 'NONE'; out['reason'] = 'MemoryError'
    except Exception as e:
        out['status'] = 'STOPPED'; out['exception_type'] = type(e).__name__; out['reason'] = str(e)[:500]; out['guarantee_type'] = 'NONE'
        out['outcome'] = 'DEADLINE' if late() else ('NUMERICAL_RANGE_OR_PRECISION' if isinstance(e, (OverflowError, ZeroDivisionError)) else 'FAULT')
        if out['outcome'] == 'FAULT': out['fault_note'] = 'an unclassified exception: investigate (never a refusal of the model)'
    out['worker_elapsed_s'] = time.monotonic() - t; ru = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss; out['peak_rss_bytes'] = ru if sys.platform == 'darwin' else ru * 1024
    tmp = a.output + '.tmp'; open(tmp, 'w').write(json.dumps(jsonable(out), indent=1, default=str)); os.replace(tmp, a.output)


if __name__ == '__main__': main()
