"""R1 cost model of the unified planner (brief CLAUDE_UNIFIED_SCHEDULING_CALIBRATION_REVISION, 24 Nov 2026, section 4): per cost block a declared NONNEGATIVE affine model
predicted_seconds = intercept + sum_j coefficient_j * work_count_j, fitted ONCE by unweighted nonnegative least squares (scipy.optimize.nnls, deterministic active set) over completed
measurements of the frozen 32-model development panel, columns scaled by their maximum observed value before the fit and transformed back. Forecasts, not bounds.
Features (fixed): for a canonical model / exact parent with retained variables n, cardinalities d_v, factor table lengths m_f: E = sum m_f + sum d_v; A = sum |scope_f| m_f + sum d_v;
G = n^2 + sum |scope_f| (|scope_f| - 1); Ddist = sum_v d_v^2 sum_{f contains v} (m_f / d_v); ell = max(1, ceil(B / 64)) with B the maximum `bits` of factors + unaries. For a built
representation: V = 2 sum_product of its admitted physical order, E_phys = source_entries, S_phys = sum coarse_cards. K = retained original coordinates recovered, J = complete original
inventory incl. fixed rows, h = decoder stages, U = sum_v card_v coarse_card_v when an upper witness participates (else 0).
Blocks and regressors: exact_construction [A ell, G]; fast_construction [A ell, Ddist, G]; refine_construction [A ell, Ddist, G]; native_host [E_phys ell, S_phys]; native_kernel [V];
recovery [K ell, K h ell, U ell]; final [J]. R0 = the legacy estimator (coarse_envelope-era PHASE_RATES.json rates through unified_planner.est_*), reproduced unchanged."""
import json, math, os, hashlib
HERE = os.path.dirname(os.path.abspath(__file__))
R1_PATH = os.path.join(HERE, 'PHASE_RATES_R1.json')
BLOCKS = {'exact_construction': ['A_ell', 'G'], 'fast_construction': ['A_ell', 'Ddist', 'G'], 'refine_construction': ['A_ell', 'Ddist', 'G'], 'native_host': ['Ephys_ell', 'S_phys'], 'native_kernel': ['V'], 'recovery': ['K_ell', 'K_h_ell', 'U_ell'], 'final': ['J']}
FINALIZE_RESERVE_S = 0.05


def bits_of(q): return q.numerator.bit_length() + q.denominator.bit_length()


def model_features(M, clock=None):
    """E, A, G, Ddist, ell for a canonical model (coarse_envelope.Canon); ell from an admitted scan of factors + unaries (polled)"""
    n = len(M.cards); E = sum(len(v) for _, v in M.factors) + sum(M.cards); A = sum(len(sc) * len(v) for sc, v in M.factors) + sum(M.cards); G = n * n + sum(len(sc) * (len(sc) - 1) for sc, _ in M.factors)
    per_v = [0] * n
    for sc, v in M.factors:
        for x in sc: per_v[x] += len(v) // M.cards[x]
    Dd = sum(M.cards[v] ** 2 * per_v[v] for v in range(n)); B = 1
    for i, (sc, vals) in enumerate(M.factors):
        for j, x in enumerate(vals):
            b = bits_of(x)
            if b > B: B = b
            if clock is not None and (j & 1023) == 1023: clock.poll('in the rational-size scan')
    for ps in M.psi:
        for x in ps:
            b = bits_of(x)
            if b > B: B = b
    return dict(E=E, A=A, G=G, Ddist=Dd, ell=max(1, math.ceil(B / 64)), B_bits=B, n=n)


def ell_bits(B): return max(1, math.ceil(B / 64))


def regressors(block, f):
    """the regressor vector of a block from a feature dict"""
    ell = f.get('ell', 1)
    if block == 'exact_construction': return [f['A'] * ell, f['G']]
    if block in ('fast_construction', 'refine_construction'): return [f['A'] * ell, f['Ddist'], f['G']]
    if block == 'native_host': return [f['E_phys'] * ell, f['S_phys']]
    if block == 'native_kernel': return [f['V']]
    if block == 'recovery': return [f['K'] * ell, f['K'] * f['h'] * ell, f.get('U', 0) * ell]
    if block == 'final': return [f['J']]
    raise KeyError(block)


class R1:
    def __init__(self, path=None):
        path = path or R1_PATH; self.path = path; d = json.load(open(path)); self.d = d
        if not d.get('frozen') or d.get('status') != 'FITTED': raise RuntimeError('PHASE_RATES_R1.json is not a frozen fitted model (status %s)' % d.get('status'))
        self.coef = {b: d['blocks'][b] for b in BLOCKS}; self.sha256 = d.get('sha256')
    def predict(self, block, f):
        c = self.coef[block]; xs = regressors(block, f); return c['intercept'] + sum(a * x for a, x in zip(c['coefficients'], xs))
    def predict_parts(self, block, f):
        c = self.coef[block]; xs = regressors(block, f); return dict(intercept=c['intercept'], **{n: a * x for n, a, x in zip(BLOCKS[block], c['coefficients'], xs)})
    def solve_cost(self, f):
        """remaining cost of ONE native action incl. its original-query recovery and exactly one final tail: host + kernel + recovery + max(reserve, final)"""
        host = self.predict('native_host', f); kern = self.predict('native_kernel', f); rec = self.predict('recovery', f); fin = max(FINALIZE_RESERVE_S, self.predict('final', f))
        return host + kern + rec + fin, dict(native_host=host, native_kernel=kern, recovery=rec, final_tail=fin)
    def construction_cost(self, block, f): return self.predict(block, f), self.predict_parts(block, f)


def fit_nnls(rows, block):
    """rows = list of (features dict, seconds) COMPLETED measurements of one block; returns the coefficient record (intercept + per-regressor coefficient in natural units), residuals and diagnostics.
    Columns scaled by their maximum observed value (intercept column = 1 unscaled); all-zero columns dropped with coefficient fixed at 0; scipy.optimize.nnls (deterministic)."""
    import numpy as np
    from scipy.optimize import nnls
    import scipy
    names = BLOCKS[block]; X = np.array([[1.0] + [float(x) for x in regressors(block, f)] for f, _ in rows]); y = np.array([float(s) for _, s in rows])
    keep = [0] + [j + 1 for j in range(len(names)) if np.any(X[:, j + 1] != 0)]; dropped = [names[j] for j in range(len(names)) if (j + 1) not in keep]
    Xk = X[:, keep]; scale = np.ones(len(keep))
    for k in range(1, len(keep)): scale[k] = Xk[:, k].max()
    Xs = Xk / scale; coef_s, rnorm = nnls(Xs, y); coef = coef_s / scale
    full = [0.0] * len(names)
    for idx, k in enumerate(keep[1:]): full[k - 1] = float(coef[idx + 1])
    pred = X @ np.array([coef[0]] + full); res = y - pred
    return dict(intercept=float(coef[0]), coefficients=full, regressors=names, dropped_all_zero=dropped, n=len(rows), rank=int(np.linalg.matrix_rank(Xs)), columns_retained=len(keep), rank_deficient=bool(np.linalg.matrix_rank(Xs) < len(keep)),
                residual_norm=float(rnorm), residuals=[float(r) for r in res], predictions=[float(p) for p in pred], measured=[float(v) for v in y], mean_abs_error=float(np.mean(np.abs(res))), signed_bias=float(np.mean(res)), column_scale=[float(s) for s in scale], solver='scipy.optimize.nnls %s' % scipy.__version__)


def file_sha256(path): return hashlib.sha256(open(path, 'rb').read()).hexdigest()
