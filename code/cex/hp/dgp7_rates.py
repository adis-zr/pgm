"""DGP7 development-panel calibration of the FROZEN nonnegative affine time blocks of residual_local.predicted_work_s (brief section 7: 'Fit nonnegative affine time blocks on a declared development panel covering local volumes through
65,536, active counts 2/4, atom counts 1/4/16, cardinalities 2-32 and representative compact bit widths. Separate fixed setup, floating cell work, compact multiplication/division/comparison, context sampling and output preparation.
Freeze coefficients before evaluation.'). Panel: SYNTHETIC windows (no model needed): a region R of |R| variables with cardinality card (volume <= 65,536), an active block A of 2 / 4 consecutive sampling-order variables at the end
of R, 1 / 4 / 16 random atoms (compact upward values in (0, 1] with the production 128-bit mantissas, scopes touching A, no later variable), positive random conditionals on parents inside R for the old law and for a G1-like target
(one extra parent), a Proposal over R for the context draws. Per window: fit_window seconds (floating: context weights + table + sweeps + quantization), local_kernel seconds (compact: two passes), context sampling seconds (the
sampled mode forced on a non-parent-closed C). Fits by nonnegative least squares: t_fit = s0 + f1 x vol x (sweeps x |A| + |J| + 4); t_kernel = k0 + c1 x vol x (2 + |A| + |J|); t_ctx = x0 + x1 x N_C draws; the frozen coefficients are
the fitted values x the 90th-percentile observed / predicted ratio (conservative: a forecast skips windows, never refuses an attempt). usage: dgp7_rates.py OUT.json"""
import sys, os, json, time, math, random
sys.path[:0] = [os.path.dirname(os.path.abspath(__file__)), os.path.join(os.path.dirname(os.path.abspath(__file__)), '../blockres'), os.path.join(os.path.dirname(os.path.abspath(__file__)), '../newarm')]
from fractions import Fraction as F
import numpy as np
from scipy.optimize import nnls
import coarse_envelope as CE, joint_proposal as JP, residual_bank as RB, residual_local as RL, check_residual as CR
from residual_max_envelope import from_fraction_up, norm_up, MBITS
D = JP.D


def rand_cond(rng, z, parents, cards):
    rows = JP.vol_of(tuple(parents), cards); k = cards[z]; counts = np.zeros((rows, k), dtype=np.int64)
    for r in range(rows):
        w = np.array([rng.random() ** 2 + 1e-3 for _ in range(k)]); w = w / w.sum(); c = 1 + np.floor((D - k) * w).astype(np.int64); c[0] += D - c.sum(); counts[r] = c
    return JP.Conditional(z, tuple(parents), counts, cards)


def rand_atom(rng, axes, cards, aid, version):
    shape = [cards[a] for a in axes]; arr = np.empty(shape, dtype=object)
    for idx in np.ndindex(*shape):
        x = rng.random()
        arr[idx] = from_fraction_up(F(1)) if x < 0.1 else norm_up(-MBITS - 1 - rng.randint(0, 12), (1 << MBITS) + rng.getrandbits(MBITS))      # a mix of unit cells and values in (2^-14, 1) with full 128-bit mantissas (never above one: production atoms are clipped at ONE)
    return RB.Atom(aid, axes, arr, dict(kind='synthetic'), 1.0, -1.0, version)


def one_window(rng, card, nR, nA, nJ, seed):
    """a synthetic window: 2 'outside' variables precede the region in sampling order (so that C is NOT parent-closed when a context variable takes an outside parent -> the sampled context mode is exercised); the region R is
    the exact union of A, the old / target parents of A and the atom scopes (the kernel's structural rule)"""
    n_out = 2; n = nR + n_out; cards = [card] * n; order = list(range(n)); pos = {v: i for i, v in enumerate(order)}; Rcand = order[n_out:]; A = order[n - nA:]
    conds_old = {}; targets = {}
    for v in order:
        earlier = order[:pos[v]]; par_old = tuple(sorted(rng.sample(earlier, min(len(earlier), rng.randint(0, 2))), key=lambda x: pos[x])) if earlier else ()
        conds_old[v] = rand_cond(rng, v, par_old, cards)
        if v in A:
            extra = [w for w in earlier if w not in par_old and w in Rcand]; par_new = tuple(sorted(par_old + ((rng.choice(extra),) if extra and JP.vol_of(par_old, cards) * card * card <= 4096 else ()), key=lambda x: pos[x])); targets[v] = par_new
    prop = JP.Proposal(cards, conds_old, order, norm_up(0, 1), norm_up(0, 1), dict(kind='synthetic'))
    atoms = []
    for j in range(nJ):
        a_touch = rng.choice(A); others = [w for w in Rcand if pos[w] <= pos[a_touch] and w != a_touch]; k = rng.randint(0, min(2, len(others))); axes = tuple(sorted([a_touch] + rng.sample(others, k)))
        atoms.append(rand_atom(rng, axes, cards, j, 0))
    def region_of(atoms_):
        R_ = set(A)
        for v in A: R_ |= set(conds_old[v].parents) | set(targets[v])
        for a in atoms_: R_ |= set(a.axes)
        return sorted(R_, key=lambda x: pos[x])
    while atoms and JP.vol_of(tuple(region_of(atoms)), cards) > 65536: atoms.pop()                       # the production region cap: drop atoms until the union fits (a panel row never exceeds 65,536 states)
    if JP.vol_of(tuple(region_of(atoms)), cards) > 65536: raise ValueError('families alone exceed the region cap')
    R = region_of(atoms); C = [x for x in R if x not in A]
    if any(pos[x] >= pos[A[0]] for x in C): raise ValueError('prefix violated by construction')
    state = RB.ResidualState('synthetic', 'synthetic', prop, prop.B, prop.B, prop.B, CE.Budget(CE.CONSTRUCTOR_BYTES))
    for a in atoms: a.verified = True; state.atoms[a.aid] = a
    window = dict(A=list(A), R=list(R), C=list(C), atoms=[a.aid for a in atoms], vol=JP.vol_of(tuple(R), cards), bank_version=0, target_parents={v: targets[v] for v in A}, max_vol=65536, whole_model_region=(len(R) == n), score=1.0, predicted_work_s=0.0)
    clk = CE.Clock(time.monotonic() + 600, {}); rng_np = np.random.default_rng(seed)
    t0 = time.monotonic(); asg = RL.region_assignments(R, cards); rpos = {x: i for i, x in enumerate(R)}; nu, crec = RL.context_weights(prop, C, cards, order, rng_np, asg, rpos, 1024, mode='auto'); t_ctx = time.monotonic() - t0
    t0 = time.monotonic(); fit = RL.fit_window(prop, window, atoms, cards, order, 'auto', rng_np, 1.1, clock=clk); t_fit = time.monotonic() - t0
    conds_new = fit.get('conds_new') if fit.get('status') == 'CANDIDATE' else None
    t0 = time.monotonic(); k = CR.local_kernel(state, window, [a.aid for a in atoms], conds_old, conds_new, cards, order, clk, want_rho=True); t_kernel = time.monotonic() - t0
    return dict(card=card, nR=len(R), nA=nA, nJ=len(atoms), nJ_requested=nJ, vol=window['vol'], N_C=JP.vol_of(tuple(C), cards), t_ctx=t_ctx, ctx_mode=crec.get('mode'), t_fit=t_fit, sweeps=fit.get('sweeps'), fit_status=fit.get('status'), t_kernel=t_kernel, kernel_ok=k.get('ok'), kernel_cells=k.get('cells'), kernel_why=k.get('why'))


def main():
    rng = random.Random(7); rows = []; panel = []
    for card, nR in ((2, 8), (2, 12), (2, 16), (2, 16), (4, 4), (4, 6), (4, 8), (4, 8), (8, 3), (8, 4), (8, 5), (8, 5), (16, 3), (16, 4), (16, 4), (32, 2), (32, 3), (32, 3)):
        for nA in (2, 4):
            if nA > nR: continue
            for nJ in (1, 4, 16): panel.append((card, nR, nA, nJ))
    for i, (card, nR, nA, nJ) in enumerate(panel):
        try: r = one_window(rng, card, nR, nA, nJ, 1000 + i); rows.append(r); print(json.dumps(r, default=str), flush=True)
        except Exception as e: import traceback; rows.append(dict(card=card, nR=nR, nA=nA, nJ=nJ, error=repr(e)[:200], tb=traceback.format_exc()[-600:])); print('ERROR', card, nR, nA, nJ, repr(e)[:200], flush=True)
    ok = [r for r in rows if 'error' not in r and r.get('kernel_ok')]
    def fit_block(X, y):
        coef, res = nnls(np.array(X, dtype=float), np.array(y, dtype=float)); pred = np.array(X) @ coef; ratio = np.array(y) / np.maximum(pred, 1e-9); return coef, float(np.percentile(ratio, 90)), float(np.median(ratio)), float(ratio.max())
    sw = RL.PROFILE_RESIDUAL['sweeps']
    Xf = [[1.0, r['vol'] * (sw * r['nA'] + r['nJ'] + 4)] for r in ok]; cf, qf, mf, xf = fit_block(Xf, [r['t_fit'] for r in ok])
    Xk = [[1.0, r['vol'] * (2 + r['nA'] + r['nJ'])] for r in ok]; ck, qk, mk, xk = fit_block(Xk, [r['t_kernel'] for r in ok])
    samp = [r for r in ok if r['ctx_mode'] and r['ctx_mode'].startswith('sampled')]; Xc = [[1.0, 1024.0] for r in samp] if samp else [[1.0, 1024.0]]; cc, qc, mc, xc = fit_block(Xc, [r['t_ctx'] for r in samp] if samp else [0.0])
    frozen = dict(t_setup_s=float(cf[0] * qf + ck[0] * qk), t_float_cell_s=float(cf[1] * qf), t_compact_cell_s=float(ck[1] * qk), t_context_sample_s=float(cc[1] * qc) if samp else RL.PROFILE_RESIDUAL['t_context_sample_s'], t_output_s=0.002,
                  rule='nonnegative least squares per block x the 90th-percentile observed / predicted ratio of that block (conservative); setup = the two intercepts; output preparation 2 ms fixed', panel=len(ok), fits=dict(fit=dict(coef=[float(x) for x in cf], p90_ratio=qf, median_ratio=mf, max_ratio=xf), kernel=dict(coef=[float(x) for x in ck], p90_ratio=qk, median_ratio=mk, max_ratio=xk), context=dict(coef=[float(x) for x in cc], p90_ratio=qc, n=len(samp))))
    json.dump(dict(rows=rows, frozen=frozen, sweeps_profile=sw, utc=time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())), open(sys.argv[1], 'w'), indent=1, default=str); print('FROZEN', json.dumps(frozen, default=str))


if __name__ == '__main__': main()
