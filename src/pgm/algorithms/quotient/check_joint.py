"""DGP5 independent checks of the joint construction (brief section 11): every check re-derives its quantity from the inputs' OWN axes (never the producer's broadcasting) in exact arithmetic (compact pairs with
exact big-integer products / sums) and is INDEPENDENT of campaign labels. Stage checks: dominance of a MAX / SUM / product output over the exact combination of its inputs at EVERY assignment of the union axes;
exact-once inventory (distinct ids bound to the active inventory, a fresh output id, the origin naming the inputs, the groups one partition of the bucket). Seed rows: positive counts summing to D, the row
inequality (D - k) P_z <= M c_z at every entry. Witness: B(theta) = max b / theta and S(theta) = sum a / theta recomputed; actual cap W_0 <= B q on EVERY fine state by enumeration (tiny models; ORACLE / CONTROLS);
exact b* / a* by enumeration (Fractions) for the slack diagnostics. The exact-rational REFERENCE functions here (ref_*) replace the brief's absent joint_reference.py fixture; they do not qualify production compact
arithmetic by themselves -- the D42+ controls pair them against the production path on identical inputs."""
import math, itertools
from fractions import Fraction as F
import numpy as np
from pgm.algorithms.quotient import coarse_envelope as CE
from pgm.algorithms.quotient import residual_max_envelope as RM
from pgm.algorithms.quotient.residual_max_envelope import ZERO, norm_up, from_fraction_up, to_fraction, mul_exact, ge_exact, sum_up, MBITS


def _exact_prod(entries):
    e = 0; m = 1
    for x in entries:
        if x[1] == 0: return ZERO
        e += x[0]; m *= x[1]
    return (e, m)


def _exact_sum(entries):
    """DGP6 repair (finding 5: compact SUM growth): the former exact sum aligned every term to the SMALLEST exponent (m << spread: two 128-bit terms with exponent spread 2^24 allocated 2^24 bits). The checker now uses the
    separately proved BOUNDED upward sum `residual_max_envelope.sum_up` (terms aligned to lead_max - MBITS - 8; a term below the grid contributes its ceiling, at least one unit): the SUM message must dominate this UPPER bound,
    a stricter (sufficient) condition than dominating the exact sum. Growth is refused typed beyond 1,048,576 terms."""
    entries = [x for x in entries if x[1]]
    if not entries: return ZERO
    if len(entries) > (1 << 20): raise CE.Refused('GROWTH', 'the checker sum has %d terms' % len(entries))
    return sum_up(entries)


def expected_sources(M_par, prop, z=None, power=1, cards=None):
    """DGP6 repair (finding 1: independent source binding): the EXPECTED raw-source inventory of a coefficient / circuit pass derived from the canonical target and the proposal ALONE (never from the producer's table list):
    every unary psi_v^power and factor^power of M_par (sorted axes; row-major re-laid), and the reciprocal D / c of EVERY conditional except z (z = None: every conditional). Returns [(role, key, axes, exact_fn)] with exact_fn(idx) the
    exact rational value at a multi-index over `axes`."""
    from pgm.algorithms.quotient import joint_proposal as JP
    cards = list(cards or M_par.cards); out = []
    for v in range(len(cards)): out.append(('unary', v, (v,), (lambda psi: (lambda idx: F(psi[idx[0]]) ** power))(M_par.psi[v])))
    for fi, (sc, vals) in enumerate(M_par.factors):
        sc = tuple(sc); axes = tuple(sorted(sc)); st = CE.strides([cards[v] for v in sc])
        def fn(idx, sc=sc, axes=axes, vals=vals, st=st): return F(vals[sum(st[i] * idx[axes.index(v)] for i, v in enumerate(sc))]) ** power
        out.append(('factor', fi, axes, fn))
    for v in prop.order:
        if v == z: continue
        c = prop.conds[v]; axes = tuple(sorted(c.parents + (c.z,))); layout = c.parents + (c.z,)
        def fr(idx, c=c, axes=axes, layout=layout): return F(JP.D, int(c.counts[sum(c.pstrides[p_] * idx[axes.index(p_)] for p_ in c.parents) if c.parents else 0, idx[axes.index(c.z)]]))
        out.append(('reciprocal', v, axes, fr))
    return out


def certify_sources(M_par, prop, tables, z=None, power=1, cards=None, sample=64, rng_seed=7):
    """DGP6 repair (finding 1): bind the producer's source tables to the EXPECTED inventory by role, axes and VALUES (never ids): every expected source present exactly once; every table maps to one expected source; each table's
    compact entries dominate the exact expected value (upward) at every entry when the table has <= `sample` x 16 entries, else at `sample` deterministic positions + the extremes; omitted / duplicated / wrong-axis / wrong-value
    tables are rejected. Returns a receipt."""
    import random
    cards = list(cards or M_par.cards); exp = expected_sources(M_par, prop, z, power, cards); by_key = {}
    for T in tables:
        role = T.origin[0]; key = T.origin[1] if len(T.origin) > 1 else None; k = ('unary', key) if role == 'unary' else ('factor', key) if role == 'factor' else ('reciprocal', key) if role == 'reciprocal' else (role, key)
        if k in by_key: return dict(ok=False, why='duplicate source %s' % (k,))
        by_key[k] = T
    missing = [(r, k) for r, k, _, _ in exp if (r, k) not in by_key]; extra = [k for k in by_key if k not in {(r, kk) for r, kk, _, _ in exp}]
    if missing: return dict(ok=False, why='missing expected source(s) %s' % missing[:4])
    if extra: return dict(ok=False, why='unexpected source(s) %s' % extra[:4])
    checked = 0; rng = random.Random(rng_seed)
    for role, key, axes, fn in exp:
        T = by_key[(role, key)]
        if tuple(T.axes) != tuple(axes): return dict(ok=False, why='source %s axes %s != expected %s' % ((role, key), T.axes, axes))
        shape = [cards[v] for v in axes]; n = int(np.prod(shape)) if shape else 1; idxs = list(itertools.product(*[range(k) for k in shape])) if n <= sample * 16 else [tuple(rng.randrange(k) for k in shape) for _ in range(sample)] + [tuple(0 for _ in shape), tuple(k - 1 for k in shape)]
        for idx in idxs:
            ex = fn(idx); got = T.arr[idx] if shape else T.arr.reshape(-1)[0]
            if (ex == 0) != (got[1] == 0): return dict(ok=False, why='source %s zero / positive mismatch at %s' % ((role, key), idx))
            if ex > 0 and to_fraction(got) < ex: return dict(ok=False, why='source %s underbounds the expected value at %s' % ((role, key), idx))
            checked += 1
    return dict(ok=True, sources=len(exp), entries_checked=checked, roles=dict(unary=sum(1 for r, _, _, _ in exp if r == 'unary'), factor=sum(1 for r, _, _, _ in exp if r == 'factor'), reciprocal=sum(1 for r, _, _, _ in exp if r == 'reciprocal')), power=power, excluded=z)


def check_inventory(inputs, output, inventory=None, bucket_ids=None, eliminated=None):
    ids = [T.tid for T in inputs]
    if len(set(ids)) != len(ids): return dict(ok=False, why='duplicate input id(s) %s' % sorted({i for i in ids if ids.count(i) > 1}))
    if inventory is not None:
        inv = set(inventory)
        if len(inv) != len(list(inventory)): return dict(ok=False, why='the active inventory carries a duplicate id')
        missing = [i for i in ids if i not in inv]
        if missing: return dict(ok=False, why='input id(s) %s not in the active inventory' % missing)
        if output.tid in inv: return dict(ok=False, why='output id %d reuses a live inventory id' % output.tid)
    if output.tid in ids: return dict(ok=False, why='output id equals an input id')
    og = output.origin
    if og and len(og) >= 3 and isinstance(og[-1], tuple) and tuple(og[-1]) != tuple(ids): return dict(ok=False, why='output origin %s does not name the input ids %s' % (og, ids))
    if bucket_ids is not None:
        if not set(ids) <= set(bucket_ids): return dict(ok=False, why='inputs %s are not a subset of the bucket %s' % (ids, sorted(bucket_ids)))
        if eliminated is not None and any(eliminated not in T.axes for T in inputs): return dict(ok=False, why='an input does not carry the eliminated variable %d' % eliminated)
    return dict(ok=True)


def check_stage(inputs, output, eliminated, cards, agg, clock, inventory=None, bucket_ids=None, P=None, scalars=None, rho=None):
    """agg 'max' / 'sum': output over union minus eliminated dominates max / sum over the eliminated variable of the EXACT product of the inputs; agg 'product': output over the union dominates the exact product
    (times the exact product of `scalars`). For agg 'sum' with the producer's normalized product P supplied, P is ALSO checked to dominate the exact product (P is the retained family table of the seed)."""
    clock.poll('at the joint stage checker entry'); union = tuple(sorted(set(a for T in inputs for a in T.axes))); expect = tuple(a for a in union if a != eliminated) if eliminated is not None else union
    inv = check_inventory(inputs, output, inventory, bucket_ids, eliminated)
    if not inv['ok']: return dict(ok=False, why='inventory: ' + inv['why'], cells=0)
    if tuple(output.axes) != expect: return dict(ok=False, why='output axes %s != expected %s' % (output.axes, expect), cells=0)
    if len(inputs) > 16: return dict(ok=False, why='fan-in %d > 16' % len(inputs), cells=0)
    sizes = [cards[a] for a in union]; opos = [union.index(a) for a in output.axes]; ipos = [[union.index(a) for a in T.axes] for T in inputs]; cells = 0; worst = None
    sc = _exact_prod(scalars) if scalars else (0, 1); slack_ok = None; slack_why = None; slack_cells = 0
    if rho is not None and (agg != 'max' or tuple(rho.shape) != tuple(sizes)): return dict(ok=False, why='slack array offered for a non-MAX stage or with the wrong shape %s' % (getattr(rho, 'shape', None),), cells=0)
    if agg in ('max', 'product'):
        for idx, asg in enumerate(itertools.product(*[range(s) for s in sizes])):
            prod = (0, 1)
            for T, pp in zip(inputs, ipos):
                x = T.arr[tuple(asg[p] for p in pp)]
                if x[1] == 0: prod = ZERO; break
                prod = (prod[0] + x[0], prod[1] * x[1])
            if agg == 'product' and prod[1] and sc[1]: prod = (prod[0] + sc[0], prod[1] * sc[1])
            elif agg == 'product' and not sc[1]: prod = ZERO
            o = output.arr[tuple(asg[p] for p in opos)]
            if not ge_exact(o, prod): return dict(ok=False, why='output does not dominate the exact %s at %s' % (agg, asg), cells=cells)
            if rho is not None and slack_ok is not False:                                                                        # DGP7 (brief section 3): the residual slack rho(x_u) must satisfy M(x_{u \ v}) rho(x_u) >= the EXACT input product at every cell (the atom is dropped, the stage proof stands)
                r = rho[asg]; bound = (o[0] + r[0], o[1] * r[1]) if (o[1] and r[1]) else ZERO
                if prod[1] and (not ge_exact(bound, prod)): slack_ok = False; slack_why = 'residual slack: M rho < the exact input product at %s' % (asg,)
                elif (not isinstance(r, tuple)) or len(r) != 2 or r[1] < 0 or (r[1] and not ge_exact((0, 1), r)): slack_ok = False; slack_why = 'residual slack outside the exact closed interval [0, 1] at %s (DGP9 repair of the original DGP7 finding F2: the DGP8 test compared against the compact pair (1, 1) = 2)' % (asg,)
                else: slack_cells += 1
            if prod[1] and o[1]:
                sl = RM.lead(o) - RM.lead(prod)
                if worst is None or sl > worst: worst = sl
            cells += 1
            if (idx & 255) == 255: clock.poll('in the joint stage checker')
    else:
        ei = union.index(eliminated); rest = [a for a in union if a != eliminated]; rsizes = [cards[a] for a in rest]
        for idx, rasg in enumerate(itertools.product(*[range(s) for s in rsizes])):
            terms = []
            for z in range(cards[eliminated]):
                asg = list(rasg); asg.insert(ei, z); prod = (0, 1)
                for T, pp in zip(inputs, ipos):
                    x = T.arr[tuple(asg[p] for p in pp)]
                    if x[1] == 0: prod = ZERO; break
                    prod = (prod[0] + x[0], prod[1] * x[1])
                if P is not None:
                    pz = P[tuple(asg)]
                    if not ge_exact(pz, prod): return dict(ok=False, why='the family table does not dominate the exact product at %s' % (asg,), cells=cells)
                terms.append(prod)
            tot = _exact_sum(terms); o = output.arr[tuple(rasg[rest.index(a)] for a in output.axes)] if output.axes else output.arr.reshape(-1)[0]
            if not ge_exact(o, tot): return dict(ok=False, why='the SUM message does not dominate the exact sum at %s' % (rasg,), cells=cells)
            if tot[1] and o[1]:
                sl = RM.lead(o) - RM.lead(tot)
                if worst is None or sl > worst: worst = sl
            cells += cards[eliminated]
            if (idx & 255) == 255: clock.poll('in the joint stage checker (sum)')
    if rho is not None and slack_ok is None: slack_ok = True
    return dict(ok=True, cells=cells, max_slack_bits_upper=worst, agg=agg, eliminated=eliminated, inputs=[T.tid for T in inputs], output=output.tid, slack_ok=slack_ok, slack_why=slack_why, slack_cells=slack_cells)


def check_seed_rows(Pm, Mf, counts, k, clock):
    """every row: counts positive integers summing to D; (D - k) P_z <= M c_z exactly (the row inequality P_z <= M theta_z D / (D - k)); a zero M has every P zero"""
    from pgm.algorithms.quotient.joint_proposal import D
    clock.poll('at the seed row checker entry'); n = Pm.shape[0]
    for ri in range(n):
        c = counts[ri]
        if int(c.sum()) != D or (c < 1).any(): return dict(ok=False, why='row %d is not a positive law summing to D' % ri, cells=ri * k)
        M = Mf[ri]
        for z in range(k):
            P = Pm[ri, z]
            if M[1] == 0:
                if P[1] != 0: return dict(ok=False, why='row %d: zero M with a positive P' % ri, cells=ri * k + z)
                continue
            if P[1] == 0: continue
            if not ge_exact((M[0], M[1] * int(c[z])), (P[0], P[1] * (D - k))): return dict(ok=False, why='row %d state %d: (D - k) P > M c' % (ri, z), cells=ri * k + z)
        if (ri & 255) == 255: clock.poll('in the seed row checker')
    return dict(ok=True, cells=n * k, kind='seed_rows')


# ---------------------------------------------------------------- witnesses of an actual law (compact, upward)
def cap_of(b_arr, cond):
    """B(theta) = max_F b(F) / theta(F) upward: b (e, m) x D / c -> (e, ceil(m D / c)) normalized; b in the (u..., z) layout matching cond.counts"""
    from pgm.algorithms.quotient.joint_proposal import D
    best = ZERO; flat_b = b_arr.reshape(-1); flat_c = cond.counts.reshape(-1)
    for i in range(flat_b.size):
        e, m = flat_b[i]
        if m == 0: continue
        c = int(flat_c[i]); q = -((-(m * D)) // c); x = norm_up(e, q)
        if x > best: best = x
    return best


def moment_of(a_arr, cond):
    """S(theta) = sum_F a(F) / theta(F) upward"""
    from pgm.algorithms.quotient.joint_proposal import D
    flat_a = a_arr.reshape(-1); flat_c = cond.counts.reshape(-1); terms = []
    for i in range(flat_a.size):
        e, m = flat_a[i]
        if m == 0: continue
        c = int(flat_c[i]); terms.append(norm_up(e, -((-(m * D)) // c)))
    return sum_up(terms)


def gamma_of(cond_old, cond_new):
    """gamma = max_F theta_old / theta_new from the ACTUAL positive counts (cond_old on the same context -- replicated if needed)"""
    r = F(0)
    for co, cn in zip(cond_old.counts.reshape(-1).tolist(), cond_new.counts.reshape(-1).tolist()):
        q = F(int(co), int(cn))
        if q > r: r = q
    return r


# ---------------------------------------------------------------- exact references (Fractions; tiny models; ORACLE / CONTROLS ONLY)
def ref_W0(M_par, x):
    w = F(1)
    for v, a in enumerate(x): w *= M_par.psi[v][a]
    for sc, vals in M_par.factors:
        idx = 0
        for v in sc: idx = idx * M_par.cards[v] + x[v]
        w *= vals[idx]
    return w


def ref_enumerate(M_par, cap=1 << 16):
    cards = list(M_par.cards)
    if math.prod(cards) > cap: raise CE.Refused('ENUM', 'enumeration cap')
    states = list(itertools.product(*[range(k) for k in cards])); W = [ref_W0(M_par, x) for x in states]; return states, W


def ref_check_law(M_par, prop, cap=1 << 16):
    """W_0(x) <= B q(x) on EVERY fine state; the law is normalized; returns the tight cap R* = max W_0 / q, Z_0, S_0 = sum W_0^2 / q, the worst slack log2(B q / W_0)"""
    states, W = ref_enumerate(M_par, cap); B = to_fraction(prop.B); tot = F(0); Rstar = F(0); S0 = F(0); Z0 = F(0); viol = 0; slack = None
    for x, w in zip(states, W):
        q = prop.q_exact(x); tot += q; Z0 += w
        if w == 0: continue
        if q == 0: viol += 1; continue
        if w > B * q: viol += 1
        Rstar = max(Rstar, w / q); S0 += w * w / q
        s = math.log2(float(B * q / w)) if (B * q / w).numerator.bit_length() < 1000 else 999.0
        if slack is None or s < slack: slack = s
    return dict(normalized=(tot == 1), violations=viol, log2_B=float(math.log2(B)) if B > 0 else -math.inf, log2_Rstar=(float(math.log2(Rstar)) if Rstar > 0 else -math.inf), log2_Z0=(float(math.log2(Z0)) if Z0 > 0 else -math.inf), log2_S0=(float(math.log2(S0)) if S0 > 0 else -math.inf), min_log2_slack=slack, Z0=Z0, Rstar=Rstar, S0=S0)


def ref_coefficients(M_par, prop, z, parents, cap=1 << 16):
    """EXACT b*(F) = max_{x \\ F} W_0 / q_-, a*(F) = sum_{x \\ F} W_0^2 / q_- with q_- = q / theta_z (every conditional except z); F = (parents..., z) in the counts layout"""
    states, W = ref_enumerate(M_par, cap); cards = list(M_par.cards); c = prop.conds[z]; shape = (math.prod(cards[p] for p in parents) if parents else 1, cards[z]); b = [[F(0)] * shape[1] for _ in range(shape[0])]; a = [[F(0)] * shape[1] for _ in range(shape[0])]
    st = {}; s_ = 1
    for p in reversed(parents): st[p] = s_; s_ *= cards[p]
    for x, w in zip(states, W):
        if w == 0: continue
        q = prop.q_exact(x); row_old = sum(c.pstrides[p] * x[p] for p in c.parents); th = F(int(c.counts[row_old, x[z]]), 1 << 40); qm = q / th
        row = sum(st[p] * x[p] for p in parents); val = w / qm
        if val > b[row][x[z]]: b[row][x[z]] = val
        a[row][x[z]] += w * w / qm
    return b, a


def lg_bounded(q):
    """float log2 of a positive Fraction from bit lengths + the leading 53 bits (never float(huge))"""
    n, d = q.numerator, q.denominator; sn = max(0, n.bit_length() - 53); sd = max(0, d.bit_length() - 53); return (sn - sd) + math.log2(n >> sn) - math.log2(d >> sd)


def ref_witness_check(b_arr, a_arr, b_ref, a_ref):
    """every bounded coefficient dominates its exact counterpart; slack in bits (max over entries; bounded log2) and the mass ratio of a"""
    worst_b = 0.0; worst_a = 0.0; viol = 0; tot_a = F(0); tot_ref = F(0)
    for i in range(b_arr.shape[0]):
        for j in range(b_arr.shape[1]):
            bb = to_fraction(b_arr[i, j]); aa = to_fraction(a_arr[i, j])
            if bb < b_ref[i][j] or aa < a_ref[i][j]: viol += 1
            if b_ref[i][j] > 0 and bb > 0: worst_b = max(worst_b, lg_bounded(bb / b_ref[i][j]))
            if a_ref[i][j] > 0 and aa > 0: worst_a = max(worst_a, lg_bounded(aa / a_ref[i][j]))
            tot_a += aa; tot_ref += a_ref[i][j]
    return dict(violations=viol, max_slack_b_bits=worst_b, max_slack_a_bits=worst_a, log2_sum_a_over_ref=(lg_bounded(tot_a / tot_ref) if tot_ref > 0 and tot_a > 0 else None))


# ---------------------------------------------------------------- vectorized float oracle (log2 domain; <= 2^16 states): the pure-law quantities used by the DGP5 oracle harness
def oracle_states(M_par, cap=1 << 16):
    cards = list(M_par.cards); n = len(cards)
    if math.prod(cards) > cap: raise CE.Refused('ENUM', 'enumeration cap')
    states = np.array(list(itertools.product(*[range(k) for k in cards])), dtype=np.int64); return states


def oracle_logW0(M_par, states):
    """log2 W_0 (without the scalar) per state from float tables of the exact factors (entries rounded to double: a DIAGNOSTIC quantity within ~n ulps); -inf for a zero entry"""
    n = len(M_par.cards); lw = np.zeros(states.shape[0])
    for v in range(n):
        tab = np.array([float(x) if x > 0 else 0.0 for x in M_par.psi[v]]); 
        with np.errstate(divide='ignore'): lw += np.log2(tab)[states[:, v]]
    for sc, vals in M_par.factors:
        sc = tuple(sc); st = CE.strides([M_par.cards[v] for v in sc]); idx = np.zeros(states.shape[0], dtype=np.int64)
        for ax, v in enumerate(sc): idx += states[:, v] * st[ax]
        tab = np.array([float(x) if x > 0 else 0.0 for x in vals])
        with np.errstate(divide='ignore'): lw += np.log2(tab)[idx]
    return lw


def oracle_law_quantities(prop, states, logW0):
    """R* = max W_0 / q, Z_0, S_0 = sum W_0^2 / q, M2 = S_0 / Z_0^2, max analyzed X = max W_0 / (B q) (floats in log2; the exact W_0 <= B q check is done in exact arithmetic by ref_check_law on small models)"""
    from pgm.algorithms.quotient import joint_proposal as JP
    logc, _ = prop.logq_bits(states) if False else (None, None); n = len(prop.cards); lq = np.zeros(states.shape[0])
    for v in prop.order:
        c = prop.conds[v]; rows = c.row_index(states); lq += np.log2(c.counts[rows, states[:, v]].astype(float))
    lq -= JP.D_BITS * n; fin = np.isfinite(logW0); lwq = logW0[fin] - lq[fin]; lZ = _logsumexp2(logW0[fin]); lS0 = _logsumexp2(2 * logW0[fin] - lq[fin]); lR = float(lwq.max()) if lwq.size else -np.inf
    return dict(log2_Z0=lZ, log2_Rstar=lR, log2_S0=lS0, log2_M2=lS0 - 2 * lZ, log2_Rstar_over_Z0=lR - lZ, log2_B=prop.log2_B(), log2_B_over_Z0=prop.log2_B() - lZ, log2_B_over_Rstar=prop.log2_B() - lR, log2_S_over_S0=prop.log2_S() - lS0, max_log2_X=lR - prop.log2_B(), total_q_log2=_logsumexp2(lq))


def _logsumexp2(a):
    a = np.asarray(a, dtype=float); a = a[np.isfinite(a)]
    if a.size == 0: return -np.inf
    m = float(a.max()); return m + math.log2(float(np.exp2(a - m).sum()))


def oracle_exact_coefficients(prop, states, logW0, z, parents, cards):
    """exact-arithmetic-free (float log2) b* and a* over the family (parents..., z): the oracle counterfactual coefficient packet; returns log2 arrays in the counts layout"""
    from pgm.algorithms.quotient import joint_proposal as JP
    n = len(cards); lq = np.zeros(states.shape[0])
    for v in prop.order:
        if v == z: continue
        c = prop.conds[v]; rows = c.row_index(states); lq += np.log2(c.counts[rows, states[:, v]].astype(float))
    lq -= JP.D_BITS * (n - 1); st = {}; s_ = 1
    for p in reversed(parents): st[p] = s_; s_ *= cards[p]
    row = np.zeros(states.shape[0], dtype=np.int64)
    for p in parents: row += states[:, p] * st[p]
    R = s_; K = cards[z]; lb = np.full((R, K), -np.inf); la = np.full((R, K), -np.inf); fin = np.isfinite(logW0); lv = logW0 - lq; la_terms = 2 * logW0 - lq
    for r in range(R):
        for k in range(K):
            m = fin & (row == r) & (states[:, z] == k)
            if m.any(): lb[r, k] = float(lv[m].max()); la[r, k] = _logsumexp2(la_terms[m])
    return lb, la
