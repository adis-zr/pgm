"""Fresh-process WORKER for one PAC-pass cell (arms P1_PAC_CONDITIONAL, H1_HYBRID, A0_POINT, A1_CONDITIONAL) -- candidate v2.
Launch-relative ABSOLUTE deadline (the parent's monotonic launch time + budget; mach_absolute_time is system-wide); source read -> solve -> verify_output -> outward
decimal publication -> JSON. EVERY terminal outcome is deadline-checked, including PROVED_ZERO_EVIDENCE (review F09): a zero proof completed after the deadline is
reported as DEADLINE with the proof recorded as `late_proof` (not a valid within-budget result). Typed executor RANGE stops are classified NUMERICAL_RANGE_OR_PRECISION,
never FAULT. Records: binding (sha256 of the actual input files), seed (domain-separated), nonce, delta ledger, the complete candidate source identity (every imported
module of cex/pac and cex/newarm), the certificate with design records and sufficient statistics, host RSS peak.
    python cex/pac/worker.py --input CASE.uai --output out.json --arm ARM --deadline ABS --seed SEEDSTR --nonce N [--delta 1/1000000] [--budget S]"""
import argparse, json, os, sys, time, hashlib, resource, glob
from fractions import Fraction as F
sys.set_int_max_str_digits(0)
HERE = os.path.dirname(os.path.abspath(__file__)); NEWARM = os.path.join(os.path.dirname(HERE), 'newarm')
for p in (NEWARM, HERE):
    if p not in sys.path: sys.path.insert(0, p)
import core, solve, engine, support
WORKER_VERSION = 'pac-worker-v3 (2026-11-13 completion)'


def jsonable(x):
    if isinstance(x, F): return str(x)
    if isinstance(x, dict): return {str(k): jsonable(v) for k, v in x.items()}
    if isinstance(x, (tuple, list)): return [jsonable(v) for v in x]
    if isinstance(x, set): return sorted(jsonable(v) for v in x)
    if isinstance(x, float) and x != x: return None
    return x


def candidate_sources():
    """sha256 of EVERY .py / .cpp source in cex/pac and cex/newarm (complete candidate identity, keyed by directory/file)"""
    out = {}
    for d, tag in ((HERE, 'pac'), (NEWARM, 'newarm')):
        for p in sorted(glob.glob(os.path.join(d, '*.py')) + glob.glob(os.path.join(d, '*.cpp'))):
            out['%s/%s' % (tag, os.path.basename(p))] = hashlib.sha256(open(p, 'rb').read()).hexdigest()
    return out


OUTCOME_OF_STOP = {'DEADLINE': 'DEADLINE', 'MEMORY': 'MEMORY', 'REPRESENTATION': 'MEMORY', 'SUPPORT_ROWS_CAP': 'MEMORY', 'TOO_WIDE': 'TOO_WIDE', 'NUMERICAL_RANGE_OR_PRECISION': 'NUMERICAL_RANGE_OR_PRECISION', 'RANGE': 'NUMERICAL_RANGE_OR_PRECISION', 'WIDTH': 'NUMERICAL_RANGE_OR_PRECISION', 'FPENV': 'NUMERICAL_RANGE_OR_PRECISION', 'INVALID_PLAN_OR_CERTIFICATE': 'INVALID_PLAN_OR_CERTIFICATE', 'BADPLAN': 'INVALID_PLAN_OR_CERTIFICATE'}


def main():
    ap = argparse.ArgumentParser(); ap.add_argument('--input', required=True); ap.add_argument('--output', required=True); ap.add_argument('--arm', required=True); ap.add_argument('--deadline', type=float, required=True); ap.add_argument('--seed', required=True); ap.add_argument('--nonce', required=True); ap.add_argument('--delta', default='1/1000000'); ap.add_argument('--budget', type=float, default=None)
    a = ap.parse_args(); t = time.monotonic(); delta = F(a.delta)
    out = {'status': 'STARTED', 'worker_version': WORKER_VERSION, 'arm': a.arm, 'seed': a.seed, 'nonce': a.nonce, 'delta': a.delta, 'epsilon': '%d/%d' % (engine.POLICY['epsilon'].numerator, engine.POLICY['epsilon'].denominator), 'deadline_abs': a.deadline, 'budget_s': a.budget, 'guarantee_type': 'NONE', 'outcome': None, 'policy': jsonable(engine.POLICY), 'candidate_sources': candidate_sources()}
    try: resource.setrlimit(resource.RLIMIT_AS, (3 * 1024 ** 3, 3 * 1024 ** 3)); out['memory_policy'] = 'RLIMIT_AS 3 GiB (address space)'
    except (ValueError, OSError) as e: out['memory_policy'] = 'RLIMIT_AS unavailable on this host (%s); the campaign supervisor enforces 3 GiB by SAMPLED process-tree RSS kill (a sampled policy, not a hard bound; shared by every arm)' % e
    late = lambda: time.monotonic() >= a.deadline
    try:
        m, binding = core.read_uai(a.input); out['binding'] = binding; out['parse_s'] = time.monotonic() - t
        r = solve.solve(m, a.deadline, a.arm, a.seed, delta)
        out.update({k: r[k] for k in ('intervals', 'points', 'stats', 'decoder', 'certificate', 'guarantee_type', 'outcome')})
        core.verify_output(out['intervals'], out['points'], engine.POLICY['epsilon']); out['publication_check'] = True
        if sum(__import__('math').log2(d) for d in m['cards']) <= 12:
            truth = core.brute_force(m); out['independent_bruteforce_containment'] = all(lo <= p <= hi for row, ps in zip(out['intervals'], truth) for (lo, hi), p in zip(row, ps))
            if not out['independent_bruteforce_containment']: out['containment_violation'] = 'the published enclosure does NOT contain the brute-force truth (retained for investigation; a PAC run may legitimately miss with probability <= delta)'
        pt = time.monotonic(); out['intervals'], out['points'] = core.publish(out['intervals'], out['points'], epsilon=engine.POLICY['epsilon']); out['publication_s'] = time.monotonic() - pt
        if late(): out['status'] = 'STOPPED'; out['outcome'] = 'DEADLINE'; out['guarantee_type'] = 'NONE'; out['reason'] = 'publication completed after the deadline'; out['late_publication'] = True; out.pop('intervals', None); out.pop('points', None)
        else: out['status'] = 'COMPLETED'
    except solve.ZeroEvidence as e:
        out['status'] = 'STOPPED'; out['zero_evidence_proof'] = jsonable(e.proof); out['stop_stats'] = jsonable(dict(core_trace=e.trace))
        if late(): out['outcome'] = 'DEADLINE'; out['guarantee_type'] = 'NONE'; out['reason'] = 'zero-evidence proof completed after the deadline (not a valid within-budget result)'; out['late_proof'] = True
        else: out['outcome'] = 'PROVED_ZERO_EVIDENCE'; out['guarantee_type'] = 'DETERMINISTIC'; out['reason'] = 'ZERO_EVIDENCE (deterministic proof kind %s)' % e.proof.get('kind')
    except Exception as e:
        out['status'] = 'STOPPED'; out['exception_type'] = type(e).__name__; out['reason'] = str(e)[:500]; st = getattr(e, 'stats', None); out['stop_stats'] = jsonable(st) if st else None
        kind = getattr(e, 'reason', None) if isinstance(e, support.ResourceStop) else (getattr(e, 'kind', None) if type(e).__name__ in ('Stop', 'CellStop') else None)
        out['outcome'] = OUTCOME_OF_STOP.get(kind, 'DEADLINE' if (type(e).__name__ in ('TimeoutError', 'Deadline', 'DeadlineExceeded') or late()) else ('NUMERICAL_RANGE_OR_PRECISION' if isinstance(e, (OverflowError, ZeroDivisionError)) or type(e).__name__ == 'RangeStop' else ('INVALID_PLAN_OR_CERTIFICATE' if isinstance(e, (ValueError, AssertionError)) else 'FAULT')))
        if out['outcome'] == 'FAULT': out['fault_note'] = 'an unclassified exception: investigate (never counted as a refusal of the model)'
    out['worker_elapsed_s'] = time.monotonic() - t; ru = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss; out['peak_rss_bytes'] = ru if sys.platform == 'darwin' else ru * 1024
    tmp = a.output + '.tmp'; open(tmp, 'w').write(json.dumps(jsonable(out), indent=1)); os.replace(tmp, a.output)


if __name__ == '__main__': main()
