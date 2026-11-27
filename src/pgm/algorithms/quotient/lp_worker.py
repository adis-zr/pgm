"""Supervised LP worker for the FIT proposer (one child per cell; killed by the parent at its allowance). JSON lines on stdin / stdout.
{"kind":"hello"} -> {"status":"ready", "import_s":..}
{"kind":"lp", "n_params":P, "n_cells":Q, "entries":[[logf, [param_or_-1 per axis], cell], ...], "time_limit":s}
  -> {"status":"ok", "x":[theta...], "fun":t, "nit":n, "seconds":s, "nnz":..} | {"status":"refused"|"failed", "message":..}
Variables: P incidence log scales (one state per incidence / class pinned to 0 = absent), Q cell centers, one range t >= 0. Two sparse inequalities per entry:
  -sum theta - b_c - t/2 <= -log f ;  sum theta + b_c - t/2 <= log f.   Storage is admitted BEFORE the matrix is built (nonzero count). The float optimum is a PROPOSAL only."""
import sys, json, time
t0 = time.monotonic()
import numpy as np
import scipy.sparse as sp
from scipy.optimize import linprog
IMPORT_S = time.monotonic() - t0
NNZ_CAP = 1 << 22

def solve(task):
    P, Q = task['n_params'], task['n_cells']; E = task['entries']; ncol = P + Q + 1; nrow = 2 * len(E)
    nnz = sum(2 * (sum(1 for p in ax if p >= 0) + 2) for _, ax, _ in E)
    if nnz > NNZ_CAP or nrow * 16 + ncol * 16 + nnz * 24 > (64 << 20): return dict(status='refused', message='LP storage %d nonzeros / %d rows exceeds the admitted workspace' % (nnz, nrow), nnz=nnz)
    rows = []; cols = []; data = []; b = np.empty(nrow); r = 0
    for logf, ax, c in E:
        idx = [p for p in ax if p >= 0]
        for sign in (1, -1):              # sign=1: -sum theta - b - t/2 <= -logf ; sign=-1: sum theta + b - t/2 <= logf
            for p in idx: rows.append(r); cols.append(p); data.append(-sign)
            rows.append(r); cols.append(P + c); data.append(-sign); rows.append(r); cols.append(P + Q); data.append(-0.5); b[r] = -sign * logf; r += 1
    A = sp.csr_matrix((np.array(data, dtype=float), (np.array(rows), np.array(cols))), shape=(nrow, ncol)); cobj = np.zeros(ncol); cobj[-1] = 1.0
    t = time.monotonic(); res = linprog(cobj, A_ub=A, b_ub=b, bounds=[(None, None)] * (P + Q) + [(0, None)], method='highs', options={'time_limit': float(task['time_limit'])}); dt = time.monotonic() - t
    if not res.success or res.x is None or not np.all(np.isfinite(res.x)): return dict(status='failed', message=str(res.message)[:200], seconds=dt, nnz=nnz)
    return dict(status='ok', x=[float(v) for v in res.x[:P]], fun=float(res.fun), nit=int(res.nit), seconds=dt, nnz=nnz)

for line in sys.stdin:
    task = json.loads(line)
    if task.get('kind') == 'hello': out = dict(status='ready', import_s=IMPORT_S)
    else:
        try: out = solve(task)
        except Exception as e: out = dict(status='failed', message=repr(e)[:200])
    sys.stdout.write(json.dumps(out) + '\n'); sys.stdout.flush()
