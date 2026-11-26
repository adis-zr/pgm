"""DGP5 joint conditional construction, part 2: the coefficient witnesses of ONE conditional update (theory note section 3, 5; brief section 7). For the family F = (z, u) (u = the candidate context, every parent sampled
before z) with every OTHER conditional frozen, q = theta(z | u) q_-:
    b(F) >= MAX_{x \\ F} W_0(x) / q_-(x)          -- MAX elimination outside F (every group MAX)
    a(F) >= SUM_{x \\ F} W_0(x)^2 / q_-(x)        -- SUM-upper elimination outside F (exactly one group SUMs per elimination, the others MAX: sum prod <= sum(one group) prod max(others))
Sources: the target factors (unaries + factors of the parent canonical model, converted upward; squared for a) and the RECIPROCAL proposal factors D / c of every conditional except the updated one (once in both passes).
The retained family volume and every union table obey V_coef = 4,096 and the fan-in; the frozen elimination order restricted to the variables outside F; the final retained product is admitted and checked. The inherited
coefficient b_0 = B_current theta_current (EXACT bounded pair (e - 40, m c): up to 168 mantissa bits) is intersected POINTWISE with the fresh b (two independently valid upper bounds; lemma L3); the old cap certificate is
kept separately. For every ACTUAL candidate law: B = max b / theta, S = min(sum a / theta, B^2, gamma S_ref) upward (gamma = max theta_current / theta from the actual counts). Every byte is charged before allocation and
released on refusal; a pass that cannot finish inside its deadline raises RefusedJoint('ALLOWANCE') with everything released."""
import math, itertools, hashlib
from fractions import Fraction as F
import numpy as np
import coarse_envelope as CE
import residual_max_envelope as RM
from residual_max_envelope import ZERO, norm_up, from_fraction_up, to_fraction, mul_exact, ge_exact, sum_up, lead, log2_up
import joint_proposal as JP
from joint_proposal import JTable, D, D_BITS, ENTRY_BYTES, RefusedJoint, vol_of


def reciprocal_table(cond, cards, tid, budget, clock, owned):
    """D / c(z | u) as an upward compact table over sorted(parents + z) (the parent-row layout is row-major over cond.parents in sampling order; re-laid out onto sorted axes)"""
    axes = tuple(sorted(cond.parents + (cond.z,))); vol = vol_of(axes, cards)
    owned[0] += budget.charge(ENTRY_BYTES * vol + 128, 'reciprocal proposal table of variable %d (%d entries)' % (cond.z, vol)); clock.poll('before reciprocal table of %d' % cond.z)
    arr = np.empty([cards[v] for v in axes], dtype=object); layout = cond.parents + (cond.z,); perm = [layout.index(v) for v in axes]
    src = np.empty([cards[v] for v in layout], dtype=object); flat = cond.counts.reshape(-1)
    for i, c in enumerate(flat.tolist()): src.reshape(-1)[i] = from_fraction_up(F(D, int(c)))
    arr[...] = np.transpose(src, perm); return JTable(axes, arr, tid, ('reciprocal', cond.z))


def coefficient_pass(M_par, prop, z, parents, order, mode, profile, budget, clock, deadline_fn=None):
    """one pass: mode 'max' -> b(F), mode 'sum' -> a(F); F = sorted(parents + z); returns (table over F in the (u..., z) COUNTS layout, record); every owned byte released on failure"""
    assert mode in ('max', 'sum'); owned = [0]; cards = list(M_par.cards); t0 = CE.tnow(); Fax = tuple(sorted(tuple(parents) + (z,)))
    if vol_of(Fax, cards) > profile['V_family']: raise RefusedJoint('VOLUME', 'the family (%d entries) exceeds the retained family cap %d' % (vol_of(Fax, cards), profile['V_family']))
    try:
        srcs = JP.source_tables(M_par, budget, clock, owned, V=profile['V_coef'], power=(2 if mode == 'sum' else 1)); tid = len(srcs)
        for v in prop.order:
            if v == z: continue
            srcs.append(reciprocal_table(prop.conds[v], cards, tid, budget, clock, owned)); tid += 1
        comp = JP.JointCompile(cards, srcs, order, profile['V_coef'], profile['fanin'], budget, clock, mode, retain=Fax, owned=owned); comp.run(deadline_fn); T = comp.retained_product()
        # re-lay the retained product (sorted axes) into the COUNTS layout (parents in sampling order, z last)
        layout = tuple(parents) + (z,); perm = [Fax.index(v) for v in layout]; arr = np.ascontiguousarray(np.transpose(T.arr, perm)).reshape(-1, cards[z])
        rec = comp.record(); rec.update(seconds=CE.tnow() - t0, family=list(Fax), family_volume=int(arr.size), owned_bytes=owned[0], source_tables=len(srcs), reciprocals=len(srcs) - len(M_par.cards) - len(M_par.factors))
        return arr, rec, owned
    except BaseException:
        if owned[0]: budget.release(owned[0]); owned[0] = 0
        raise


def inherited_b(prop, cond_ctx):
    """b_0(F) = B_current theta_current(F) as EXACT pairs (e - 40, m c) on the candidate context (theta_current = the replicated current conditional on that context); never rounded"""
    e, m = prop.B; out = np.empty(cond_ctx.counts.shape, dtype=object)
    for idx, c in np.ndenumerate(cond_ctx.counts): out[idx] = (e - D_BITS, m * int(c)) if m else ZERO
    return out


def intersect_b(b_fresh, b_inherited):
    """pointwise minimum of two valid upper tables (exact comparison; entries keep their own representation)"""
    out = np.empty(b_fresh.shape, dtype=object)
    for idx in np.ndindex(*b_fresh.shape):
        x, y = b_fresh[idx], b_inherited[idx]; out[idx] = y if (y[1] == 0 or (x[1] and ge_exact(x, y))) else x
    return out


def C_min_of(b):
    """C_min = max_u sum_z b(z, u) upward (feasibility of the fixed-cap problem: theta_z >= b_z / C)"""
    best = ZERO
    for r in range(b.shape[0]):
        s = sum_up(list(b[r]))
        if s > best: best = s
    return best


class WitnessPacket:
    """the common coefficient packet of one family on one frozen q_-: b (intersected with the inherited coefficient), a, C_min, provenance; every candidate law of this family is scored against it"""
    def __init__(self, z, parents, b, a, b_fresh, rec_b, rec_a, cond_ctx, prop):
        self.z = z; self.parents = tuple(parents); self.b = b; self.a = a; self.b_fresh = b_fresh; self.rec_b = rec_b; self.rec_a = rec_a; self.cond_ctx = cond_ctx; self.prop = prop; self.Cmin = C_min_of(b)
        self.sha256 = hashlib.sha256(repr((z, self.parents, [(e, str(m)) for e, m in b.reshape(-1)], [(e, str(m)) for e, m in a.reshape(-1)])).encode()).hexdigest()
    def record(self):
        return dict(z=self.z, parents=list(self.parents), family_volume=int(self.b.size), log2_Cmin=(log2_up(self.Cmin) if self.Cmin[1] else -math.inf), b_pass=self.rec_b, a_pass=self.rec_a, sha256=self.sha256, inherited_entries_used=int(sum(1 for x, y in zip(self.b.reshape(-1), self.b_fresh.reshape(-1)) if x is not y)))


def build_packet(M_par, prop, z, parents, order, profile, budget, clock, deadline_fn=None, inherit=True):
    """both passes on the candidate context (parents) of conditional z; the current conditional replicated onto that context; b intersected with the inherited coefficient when `inherit`"""
    cards = list(M_par.cards); cur = prop.conds[z]; ctx = cur if tuple(cur.parents) == tuple(parents) else cur.replicate(tuple(parents), cards)
    b_fresh, rec_b, own_b = coefficient_pass(M_par, prop, z, parents, order, 'max', profile, budget, clock, deadline_fn)
    try: a, rec_a, own_a = coefficient_pass(M_par, prop, z, parents, order, 'sum', profile, budget, clock, deadline_fn)
    except BaseException:
        if own_b[0]: budget.release(own_b[0]); own_b[0] = 0
        raise
    b = intersect_b(b_fresh, inherited_b(prop, ctx)) if inherit else b_fresh
    pk = WitnessPacket(z, parents, b, a, b_fresh, rec_b, rec_a, ctx, prop); pk.owned = own_b[0] + own_a[0]; own_b[0] = 0; own_a[0] = 0; pk.release = lambda: budget.release(pk.owned); return pk


def witnesses_of(pk, cond, S_ref=None, gamma_ok=True):
    """the ACTUAL candidate law's checked witnesses: B = max b / theta, S = min(sum a / theta, B^2[, gamma S_ref]) (compact upward); gamma from the actual counts of the replicated current conditional; S_ref = a compact pair"""
    import check_joint as CJ
    B = CJ.cap_of(pk.b, cond); S_a = CJ.moment_of(pk.a, cond); S_B2 = norm_up(*mul_exact(B, B)) if B[1] else ZERO; cands = [('sum_a_over_theta', S_a), ('B_squared', S_B2)]; g = None
    if gamma_ok and S_ref is not None and S_ref[1]:
        g = CJ.gamma_of(pk.cond_ctx, cond); cands.append(('gamma_S_ref', norm_up(*mul_exact(S_ref, from_fraction_up(g)))))
    S_name, S = min(((n, s) for n, s in cands if s[1]), key=lambda t: t[1]) if any(s[1] for _, s in cands) else ('zero', ZERO)
    return dict(B=B, S=S, S_witness=S_name, log2_B=(log2_up(B) if B[1] else -math.inf), log2_S=(log2_up(S) if S[1] else -math.inf), log2_S_sum_a=(log2_up(S_a) if S_a[1] else -math.inf), log2_B2=(log2_up(S_B2) if S_B2[1] else -math.inf), gamma=(str(g) if g is not None else None))
