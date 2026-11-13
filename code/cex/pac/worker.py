"""Fresh-process WORKER for one PAC-pass cell (arms P1_PAC_CONDITIONAL, H1_HYBRID, A0_POINT, A1_CONDITIONAL). Mirrors the frozen harness worker (cex/newarm/evaluate.py
--worker) so the two arms are measured identically: launch-relative ABSOLUTE deadline (the parent's monotonic launch time + budget; mach_absolute_time is system-wide),
source read -> solve -> verify_output -> outward decimal publication -> JSON, every terminal path deadline-checked (a late completion is LATE_OUTPUT at the parent).
Separate fields: guarantee_type {DETERMINISTIC, PAC, NONE}; outcome {PUBLISHED, PROVED_ZERO_EVIDENCE, DEADLINE, MEMORY, NUMERICAL_RANGE_OR_PRECISION, TOO_WIDE,
INVALID_PLAN_OR_CERTIFICATE, FAULT}. Records: seed (domain-separated), nonce, delta ledger, per-component trials / U / certifier / cutset, host RSS peak.
    python cex/pac/worker.py --input CASE.uai --output out.json --arm ARM --deadline ABS --seed SEEDSTR --nonce N [--delta 1/1000000] [--budget S]"""
import argparse, json, os, sys, time, hashlib, resource
from fractions import Fraction as F
sys.set_int_max_str_digits(0)
HERE = os.path.dirname(os.path.abspath(__file__)); NEWARM = os.path.join(os.path.dirname(HERE), 'newarm')
for p in (NEWARM, HERE):
    if p not in sys.path: sys.path.insert(0, p)
import core, solve, engine


def jsonable(x):
    if isinstance(x, F): return str(x)
    if isinstance(x, dict): return {str(k): jsonable(v) for k, v in x.items()}
    if isinstance(x, (tuple, list)): return [jsonable(v) for v in x]
    if isinstance(x, set): return sorted(jsonable(v) for v in x)
    return x


def main():
    ap = argparse.ArgumentParser(); ap.add_argument('--input', required=True); ap.add_argument('--output', required=True); ap.add_argument('--arm', required=True); ap.add_argument('--deadline', type=float, required=True); ap.add_argument('--seed', required=True); ap.add_argument('--nonce', required=True); ap.add_argument('--delta', default='1/1000000'); ap.add_argument('--budget', type=float, default=None)
    a = ap.parse_args(); t = time.monotonic(); delta = F(a.delta)
    out = {'status': 'STARTED', 'arm': a.arm, 'seed': a.seed, 'nonce': a.nonce, 'delta': a.delta, 'epsilon': '1/200', 'deadline_abs': a.deadline, 'budget_s': a.budget, 'guarantee_type': 'NONE', 'outcome': None, 'policy': jsonable(engine.POLICY), 'candidate_sources': {f: hashlib.sha256(open(os.path.join(d, f), 'rb').read()).hexdigest() for d, fs in ((HERE, ('engine.py', 'solve.py', 'contrib.py', 'rig.py', 'worker.py')), (NEWARM, ('cex_executor.py', 'cex_kernel.cpp', 'core.py', 'reduction.py', 'planning.py', 'geometry.py'))) for f in fs}}
    try: resource.setrlimit(resource.RLIMIT_AS, (3 * 1024 ** 3, 3 * 1024 ** 3)); out['memory_policy'] = 'RLIMIT_AS 3 GiB (address space)'
    except (ValueError, OSError) as e: out['memory_policy'] = 'RLIMIT_AS unavailable on this host (%s); the campaign supervisor enforces 3 GiB by SAMPLED process-tree RSS kill (a sampled policy, not a hard bound; shared by every arm)' % e
    try:
        m, binding = core.read_uai(a.input); out['binding'] = binding; out['parse_s'] = time.monotonic() - t
        r = solve.solve(m, a.deadline, a.arm, a.seed, delta)
        out.update({k: r[k] for k in ('intervals', 'points', 'stats', 'decoder', 'certificate', 'guarantee_type', 'outcome')})
        core.verify_output(out['intervals'], out['points']); out['publication_check'] = True
        if sum(__import__('math').log2(d) for d in m['cards']) <= 12:
            truth = core.brute_force(m); assert all(lo <= p <= hi for row, ps in zip(out['intervals'], truth) for (lo, hi), p in zip(row, ps)); out['independent_bruteforce_containment'] = True
        pt = time.monotonic(); out['intervals'], out['points'] = core.publish(out['intervals'], out['points']); out['publication_s'] = time.monotonic() - pt
        if time.monotonic() >= a.deadline: out['status'] = 'STOPPED'; out['outcome'] = 'DEADLINE'; out['guarantee_type'] = 'NONE'; out['reason'] = 'publication completed after the deadline'; out.pop('intervals', None); out.pop('points', None)
        else: out['status'] = 'COMPLETED'
    except ValueError as e:
        if str(e) == 'ZERO_EVIDENCE': out['status'] = 'STOPPED'; out['outcome'] = 'PROVED_ZERO_EVIDENCE'; out['guarantee_type'] = 'DETERMINISTIC'; out['reason'] = 'ZERO_EVIDENCE (deterministic proof: reduction / exact component / zero root bound)'
        else: out['status'] = 'STOPPED'; out['outcome'] = 'INVALID_PLAN_OR_CERTIFICATE'; out['exception_type'] = type(e).__name__; out['reason'] = str(e)[:500]
    except Exception as e:
        out['status'] = 'STOPPED'; out['exception_type'] = type(e).__name__; out['reason'] = str(e)[:500]; st = getattr(e, 'stats', None); out['stop_stats'] = jsonable(st) if st else None
        kind = getattr(e, 'reason', None) if type(e).__name__ == 'ResourceStop' else None
        out['outcome'] = {'DEADLINE': 'DEADLINE', 'MEMORY': 'MEMORY', 'REPRESENTATION': 'MEMORY', 'TOO_WIDE': 'TOO_WIDE', 'NUMERICAL_RANGE_OR_PRECISION': 'NUMERICAL_RANGE_OR_PRECISION', 'RANGE': 'NUMERICAL_RANGE_OR_PRECISION', 'SUPPORT_ROWS_CAP': 'MEMORY', 'INVALID_PLAN_OR_CERTIFICATE': 'INVALID_PLAN_OR_CERTIFICATE'}.get(kind, 'DEADLINE' if type(e).__name__ in ('TimeoutError', 'Deadline') else 'FAULT')
    out['worker_elapsed_s'] = time.monotonic() - t; ru = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss; out['peak_rss_bytes'] = ru if sys.platform == 'darwin' else ru * 1024
    tmp = a.output + '.tmp'; open(tmp, 'w').write(json.dumps(jsonable(out), indent=1)); os.replace(tmp, a.output)


if __name__ == '__main__': main()
