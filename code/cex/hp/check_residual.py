"""DGP7 RESIDUAL_JOINT, part 3: the INDEPENDENT local kernel (theory sections 4, 6; brief section 6) and the exact-rational references. The kernel receives the checked bank state, the selected atom ids, the ACTUAL old / new counts of the
active conditionals and the structural window; it validates scopes, inventory, positivity, row sums, G1 legality (parents earlier in sampling order; table <= 4,096), the prefix condition (every region variable outside A precedes A),
the bank version and the units; it builds the compact upward local target Fhat >= q_old,A prod_J rho from those inputs alone (never a producer table; a hash is an identity, not an inequality); it scans the region in tiles of <= 256
assignments with polls, computing the unchanged-law cap K_ref = max Fhat / q_old,A, the new-law cap K_new = max Fhat / q_new,A, B_ref = envelope_B K_ref, B_new = envelope_B K_new (upward), the optional moment record envelope_B^2 max_c T_2(c)
(valid global upper bound; an exact parent-closed weighted average when requested), and the replacement rho_new = upward((envelope_B / B_new) Fhat / q_new,A) clipped at one ONLY after the exact scaled inequality envelope_B Fhat <= B_new
q_new is established cellwise. Gates: 10 B_new <= 11 B_ref and 10 B_new <= 11 initial_seed_cap by EXACT comparison (no float reserve is a proof). Every array is admitted before allocation; division never shifts by an exponent gap
(div_up). An identically zero Fhat is the typed zero-mass result (no division by B_new = 0). References: exact Fractions on tiny windows (K, T_2, parent-closed weighted moment) and the global residual identity W_0 <= B q prod rho on
every state of a <= 4,096-state model."""
import math, itertools, hashlib
from fractions import Fraction as F
import numpy as np
import coarse_envelope as CE
import residual_max_envelope as RM
from residual_max_envelope import ZERO, norm_up, from_fraction_up, to_fraction, mul_exact, ge_exact, sum_up, log2_up, MBITS
from joint_proposal import vol_of, D, D_BITS, ENTRY_BYTES, Conditional
from residual_bank import div_up, ONE, RefusedResidual
import check_joint as CJ
TILE = 256; V_FAMILY = 4096


def _exact_pair_mul(a, b): return ZERO if (a[1] == 0 or b[1] == 0) else (a[0] + b[0], a[1] * b[1])


def _sq_up(x): return norm_up(*mul_exact(x, x)) if x[1] else ZERO


def validate_window(state, window, atom_ids, conds_old, conds_new, cards, order):
    """structural validation (brief section 6): active A consecutive in sampling order; region R = A + old / new parents + atom scopes; prefix: R \\ A precedes A; every atom touches A, is live / verified / unconsumed, scope <= R;
    new conditionals: positive counts summing to D, parents earlier in sampling order, table <= 4,096, parents = the frozen target parents; bank version matches"""
    pos = {v: i for i, v in enumerate(order)}; A = list(window['A'])
    if len(A) not in (2, 4) or any(pos[A[i + 1]] != pos[A[i]] + 1 for i in range(len(A) - 1)): return 'A must be 2 or 4 CONSECUTIVE sampling-order variables'
    if window.get('bank_version') != state.version: return 'bank version %s != state version %d' % (window.get('bank_version'), state.version)
    if getattr(state, 'law', None) is not None and any(conds_old[v].sha256 != state.law.conds[v].sha256 for v in A): return 'the old conditionals of the window do not match the bank law identity (rebinding the atoms to other counts is rejected)'
    for key, mine in (('model_identity', getattr(state, 'model_identity', None)), ('seed_proof_identity', getattr(state, 'seed_proof_identity', None)), ('law_identity', getattr(state, 'law_identity', None))):      # DGP8 repair (DGP7 review: bank identity): a window planned against another bank never consumes this one's atoms
        if key in window and window[key] != mine: return 'the window was planned against another bank (%s mismatch)' % key
    atoms = []
    for aid in atom_ids:
        a = state.atoms.get(aid)
        if a is None: return 'atom %s not in the bank' % aid
        if a.consumed: return 'atom %d already consumed' % aid
        if not a.verified: return 'atom %d not verified' % aid
        if not (set(a.axes) & set(A)): return 'atom %d touches no active variable' % aid
        if max(pos[x] for x in a.axes) > pos[A[-1]]: return 'atom %d contains a variable sampled after the window' % aid
        if a.arr is None: return 'atom %d has no array (released)' % aid
        for x in a.arr.reshape(-1):                                                                              # DGP8 repair (DGP7 review: bank range): every consumed value is a compact pair in [0, 1] -- re-checked at consumption, never assumed
            if (not isinstance(x, tuple)) or len(x) != 2 or x[1] < 0 or (x[1] and not ge_exact(ONE, x)): return 'atom %d carries a value outside [0, 1] (or a malformed entry)' % aid
        atoms.append(a)
    R = set(A)
    for v in A:
        R |= set(conds_old[v].parents)
        if conds_new is not None: R |= set(conds_new[v].parents)
    for a in atoms: R |= set(a.axes)
    R = tuple(sorted(R, key=lambda x: pos[x]))
    if tuple(R) != tuple(window['R']): return 'region %s != the window\'s declared region %s' % (R, tuple(window['R']))
    if any(pos[x] >= pos[A[0]] for x in R if x not in A): return 'a region variable outside A does not precede the window (prefix condition)'
    if vol_of(R, cards) > window.get('max_vol', 65536): return 'region volume %d exceeds the cap' % vol_of(R, cards)
    for v in A:
        c = conds_old[v]
        if c.z != v or (c.counts < 1).any() or (c.counts.sum(axis=1) != D).any(): return 'old conditional of %d is not a positive law summing to D' % v
        if any(pos[p] >= pos[v] for p in c.parents): return 'old conditional of %d has a non-earlier parent' % v
        if conds_new is not None:
            cn = conds_new[v]
            if cn.z != v or (cn.counts < 1).any() or (cn.counts.sum(axis=1) != D).any(): return 'new conditional of %d is not a positive law summing to D' % v
            if any(pos[p] >= pos[v] for p in cn.parents): return 'new conditional of %d has a non-earlier parent (G1 legality)' % v
            if cn.counts.size > V_FAMILY: return 'new conditional of %d has %d entries > %d' % (v, cn.counts.size, V_FAMILY)
            if tuple(cn.parents) != tuple(window['target_parents'][v]): return 'new conditional of %d is not on the frozen target parents' % v
            if not set(cn.parents) <= set(R): return 'new parents of %d outside the region' % v
    return None


def local_kernel(state, window, atom_ids, conds_old, conds_new, cards, order, clock, budget=None, tile=TILE, want_rho=True, context_weights_exact=None, expected_identity=None):
    """-> receipt. conds_new None = the same-law case (q_new = q_old). `context_weights_exact`: optional dict {context key -> Fraction} for the parent-closed weighted moment (independently recomputed by the caller's reference).
    `expected_identity`: the consuming stream's own model identity (DGP8 repair, DGP7 review: bank identity) -- the bank must have been built for it."""
    t0 = CE.tnow()
    if expected_identity is not None and getattr(state, 'model_identity', None) != expected_identity: return dict(ok=False, why='identity: the bank was built for another model (%s != %s)' % (str(getattr(state, 'model_identity', None))[:16], str(expected_identity)[:16]))
    why = validate_window(state, window, atom_ids, conds_old, conds_new, cards, order)
    if why: return dict(ok=False, why='structure: ' + why)
    pos = {v: i for i, v in enumerate(order)}; A = list(window['A']); R = tuple(window['R']); C = [x for x in R if x not in A]; vol = vol_of(R, cards); sizes = [cards[x] for x in R]; rpos = {x: i for i, x in enumerate(R)}
    atoms = [state.atoms[aid] for aid in atom_ids]; B_env = state.envelope_B; seed_cap = state.initial_seed_cap
    if B_env[1] == 0: return dict(ok=False, why='envelope_B is zero')
    owned = 0
    def admit(n, what):
        nonlocal owned
        if budget is not None: budget.charge(n, what); owned += n
    try:
        admit(ENTRY_BYTES * vol + 128, 'kernel Fhat (%d entries)' % vol)
        if want_rho: admit(ENTRY_BYTES * vol + 128, 'kernel rho_new (%d entries)' % vol)
        admit(ENTRY_BYTES * vol_of(tuple(C), cards) * 2 + 256, 'kernel per-context T2 accumulators')
        Fhat = np.empty(vol, dtype=object); rho_new = np.empty(vol, dtype=object) if want_rho else None
        # per-context T2 accumulators (upward sums at the end): collect the terms per context (bounded: <= vol terms total)
        cstr = CE.strides([cards[x] for x in C]) if C else []; nC = vol_of(tuple(C), cards); terms_new = [[] for _ in range(nC)]
        K_ref = ZERO; K_new = ZERO; zero_all = True; cells = 0
        # pass 1: Fhat, K_ref, K_new. Index arithmetic in numpy (region assignments, per-cell flat atom indices, per-cell conditional counts from the ACTUAL tables); only the compact big-integer arithmetic is per cell
        asg = (np.indices(sizes).reshape(len(R), -1).T.astype(np.int64) if R else np.zeros((1, 0), dtype=np.int64))
        atom_vals = []
        for a in atoms:
            stv = CE.strides([cards[x] for x in a.axes]); flat = np.zeros(vol, dtype=np.int64)
            for j, x in enumerate(a.axes): flat += asg[:, rpos[x]] * stv[j]
            atom_vals.append(a.arr.reshape(-1)[flat])
        def counts_of(cond):
            row = np.zeros(vol, dtype=np.int64)
            for p_ in cond.parents: row += asg[:, rpos[p_]] * cond.pstrides[p_]
            return cond.counts[row, asg[:, rpos[cond.z]]]
        cnt_old = [counts_of(conds_old[v]) for v in A]; cnt_new = ([counts_of(conds_new[v]) for v in A] if conds_new is not None else cnt_old); eA = -D_BITS * len(A)
        ckeys = np.zeros(vol, dtype=np.int64)
        for j, x in enumerate(C): ckeys += asg[:, rpos[x]] * cstr[j]
        for i in range(vol):
            mo = 1
            for c_ in cnt_old: mo *= int(c_[i])
            mn = mo if conds_new is None else math.prod(int(c_[i]) for c_ in cnt_new)
            qo = (eA, mo); qn = (eA, mn); fe = eA; fm = mo
            for av in atom_vals:
                x = av[i]
                if x[1] == 0: fm = 0; break
                fe += x[0]; fm *= x[1]
            fh = norm_up(fe, fm) if fm else ZERO; Fhat[i] = fh
            if fh[1]:
                zero_all = False; r_ref = div_up(fh, qo); r_new = div_up(fh, qn)
                if ge_exact(r_ref, K_ref): K_ref = r_ref
                if ge_exact(r_new, K_new): K_new = r_new
                terms_new[int(ckeys[i])].append(div_up(_sq_up(fh), qn))
            cells += 1
            if (i & (tile - 1)) == tile - 1: clock.poll('kernel pass 1 tile %d' % (i // tile))
        if zero_all: return dict(ok=True, zero_target=True, why='the checked local target Fhat is identically zero: the envelope proves zero target mass (typed zero-mass result; no epoch, no division by B_new = 0)', cells=cells, seconds=CE.tnow() - t0)
        B_ref = norm_up(*mul_exact(B_env, K_ref)); B_new = norm_up(*mul_exact(B_env, K_new))
        # gates by EXACT comparison: 10 B_new <= 11 B_ref ; 10 B_new <= 11 initial_seed_cap
        ten_new = (B_new[0], 10 * B_new[1]); gate_ref = ge_exact((B_ref[0], 11 * B_ref[1]), ten_new); gate_seed = ge_exact((seed_cap[0], 11 * seed_cap[1]), ten_new)
        T2_max = ZERO
        for ck in range(nC):
            t = sum_up(terms_new[ck]) if terms_new[ck] else ZERO
            if ge_exact(t, T2_max): T2_max = t
            if (ck & (tile - 1)) == tile - 1: clock.poll('kernel T2 context %d' % ck)
        moment_bound = norm_up(*mul_exact(_sq_up(B_env), T2_max)) if T2_max[1] else ZERO                     # S(q_new) <= envelope_B^2 sum_c q(c) T2(c) <= envelope_B^2 max_c T2(c): W <= B_env q_rest Fhat prod(others) and sum_{x \\ R} q_rest = q(c)
        weighted = None
        if context_weights_exact is not None:
            acc = F(0)
            for ck in range(nC):
                w = context_weights_exact.get(ck, F(0))
                if w and terms_new[ck]: acc += w * sum(to_fraction(x) for x in terms_new[ck])
            weighted = dict(log2_weighted_T2=(float(CJ.lg_bounded(acc)) if acc > 0 else -math.inf), log2_bound=(float(CJ.lg_bounded(acc * to_fraction(B_env) ** 2)) if acc > 0 else -math.inf), note='exact parent-closed context weights supplied by the caller: a VALID global second-moment bound only when those weights are the exact current-proposal marginal of C')
        # pass 2: rho_new = (B_env / B_new) Fhat / q_new, clipped at one only after the exact envelope_B Fhat <= B_new q_new
        clipped = 0
        if want_rho and not zero_all:
            scale = div_up(B_env, B_new)
            for i in range(vol):
                fh = Fhat[i]
                if fh[1] == 0: rho_new[i] = ZERO; continue
                mn = 1
                for c_ in cnt_new: mn *= int(c_[i])
                qn = (eA, mn); lhs = _exact_pair_mul(B_env, fh); rhs = _exact_pair_mul(B_new, qn)
                if not ge_exact(rhs, lhs): return dict(ok=False, why='rho_new > 1 exactly at cell %d (B_new does not dominate envelope_B Fhat / q_new)' % i)
                r = norm_up(*mul_exact(scale, div_up(fh, qn)))
                if ge_exact(r, ONE): r = ONE; clipped += 1
                rho_new[i] = r
                if (i & (tile - 1)) == tile - 1: clock.poll('kernel pass 2 tile %d' % (i // tile))
            rho_new = rho_new.reshape(sizes); rho_new.setflags(write=False)
        ident = hashlib.sha256(repr((state.model_identity, state.seed_proof_identity, state.version, sorted(atom_ids), [(v, conds_old[v].sha256) for v in A], [(v, conds_new[v].sha256) for v in A] if conds_new is not None else None, tuple(R), (B_env[0], str(B_env[1])))).encode()).hexdigest()
        return dict(ok=True, zero_target=False, K_ref=K_ref, K_new=K_new, B_ref=B_ref, B_new=B_new, log2_K_ref=log2_up(K_ref), log2_K_new=log2_up(K_new), log2_B_ref=log2_up(B_ref), log2_B_new=log2_up(B_new), gate_ref_ok=gate_ref, gate_seed_ok=gate_seed, T2_max=T2_max, log2_T2_max=(log2_up(T2_max) if T2_max[1] else -math.inf), moment_bound=moment_bound, log2_moment_bound=(log2_up(moment_bound) if moment_bound[1] else -math.inf), weighted_moment=weighted, rho_new=rho_new, rho_new_clipped=clipped, cells=cells, region=list(R), region_volume=vol, whole_model_region=(len(R) == len(cards)), identity=ident, same_law=(conds_new is None), seconds=CE.tnow() - t0, units='Fhat, K in W_0 / q units (dimensionless ratios of the envelope); B in W_0 units; moment bound in W_0^2')
    finally:
        if budget is not None and owned: budget.release(owned)


# ---------------------------------------------------------------- exact-rational references (tiny windows / models)
def ref_local_exact(state, window, atom_ids, conds_old, conds_new, cards, order, context_weights=None):
    """EXACT K_ref, K_new, T_2(c) and (optionally) the parent-closed weighted moment by Fraction enumeration over the region; the kernel's compact values must dominate these"""
    pos = {v: i for i, v in enumerate(order)}; A = list(window['A']); R = tuple(window['R']); C = [x for x in R if x not in A]; sizes = [cards[x] for x in R]; rpos = {x: i for i, x in enumerate(R)}; atoms = [state.atoms[a] for a in atom_ids]
    Kr = F(0); Kn = F(0); T2 = {}; cstr = CE.strides([cards[x] for x in C]) if C else []
    for asg in itertools.product(*[range(s) for s in sizes]):
        qo = F(1); qn = F(1)
        for v in A:
            c = conds_old[v]; row = sum(c.pstrides[p_] * asg[rpos[p_]] for p_ in c.parents) if c.parents else 0; qo *= F(int(c.counts[row, asg[rpos[v]]]), D)
            cn = (conds_new or conds_old)[v]; rown = sum(cn.pstrides[p_] * asg[rpos[p_]] for p_ in cn.parents) if cn.parents else 0; qn *= F(int(cn.counts[rown, asg[rpos[v]]]), D)
        f = qo
        for a in atoms: f *= to_fraction(a.arr[tuple(asg[rpos[x]] for x in a.axes)])
        if f == 0: continue
        Kr = max(Kr, f / qo); Kn = max(Kn, f / qn); ck = sum(cstr[j] * asg[rpos[x]] for j, x in enumerate(C)) if C else 0; T2[ck] = T2.get(ck, F(0)) + f * f / qn
    out = dict(K_ref=Kr, K_new=Kn, T2=T2, T2_max=(max(T2.values()) if T2 else F(0)))
    if context_weights is not None: out['weighted_T2'] = sum(context_weights.get(ck, F(0)) * t for ck, t in T2.items())
    return out


def ref_envelope_exact(M_par, prop, atoms, B, cap=1 << 12):
    """the GLOBAL residual identity on every state of a <= 4,096-state model: W_0(x) <= B q(x) prod_j rho_j(x_{R_j}) (Fractions); returns violations and the worst slack"""
    states, W = CJ.ref_enumerate(M_par, cap); Bf = to_fraction(B); viol = 0; worst = None; checked = 0; n_zero_rho = 0
    for x, w in zip(states, W):
        q = prop.q_exact(x); prod = F(1)
        for a in atoms:
            r = to_fraction(a.arr[tuple(x[v] for v in a.axes)]); prod *= r
            if r == 0: n_zero_rho += 1
        bound = Bf * q * prod; checked += 1
        if w > bound: viol += 1
        elif w > 0 and bound > 0:
            s = float(CJ.lg_bounded(bound / w)); worst = s if worst is None else min(worst, s)
    return dict(violations=viol, states=checked, min_log2_slack=worst, zero_rho_cells_hit=n_zero_rho)


def parent_closed(prop, C):
    """C is parent-closed in the CURRENT proposal DAG iff every parent of every c in C lies in C"""
    Cs = set(C); return all(set(prop.conds[c].parents) <= Cs for c in C)


def exact_context_marginal(prop, C, cards):
    """{context key -> Fraction} of the exact current-proposal marginal of a PARENT-CLOSED C (the product of its conditionals); keys use CE.strides over C in the given order"""
    cstr = CE.strides([cards[x] for x in C]); out = {}
    for asg in itertools.product(*[range(cards[x]) for x in C]):
        p = F(1)
        for j, c in enumerate(C):
            cond = prop.conds[c]; row = sum(cond.pstrides[p_] * asg[C.index(p_)] for p_ in cond.parents) if cond.parents else 0; p *= F(int(cond.counts[row, asg[j]]), D)
        out[sum(cstr[j] * asg[j] for j in range(len(C)))] = p
    return out
