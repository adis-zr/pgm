"""SIGNED EVIDENCE EXPANSION as an exact algebraic operator (round 19, 21 Nov 2026; SPEC.md of the R19 packet).

Family recognised in this round (exact rational identities on the ORIGINAL model, child-first scopes): binary variables, exactly one normalised child factor per variable --
  root prior         (r,)            values (1 - p, p)
  noisy-OR gate      (c, root, prev) failure entries [1, t_prev, t_root, t_root t_prev] and success entries their complements; prev an accumulator => t_prev = 0, prev a root => any t_prev
  terminal           (y, parent)     [a, b, 1 - a, 1 - b], 0 < a <= 1, 0 <= b <= a; parent an accumulator => b = 0; parent a root => b / a is that root's inhibition; a = the leak-failure
All and only the terminals are observed, positive. Every accumulator has exactly one consumer and belongs to exactly one terminal chain (no shared subchains, no cycles); roots may be
shared across chains and may recur inside a chain. Anything else is NotApplicable (a refusal of this OPTIONAL route, never of the task).

Operator (Heckerman 1989 / inclusion-exclusion, exact integers). With priors p_i, chain-j failure probability q_j(d) = lambda_j prod_i theta_ji^{d_i} (repeated causes multiply into theta_ji)
and findings all positive:   Z = sum_{S subset findings} (-1)^|S| Q(S),   Q(S) = (prod_{j in S} lambda_j) prod_i [(1 - p_i) + p_i prod_{j in S} theta_ji].
Root i, state 1: replace its affine factor by p_i prod_{j in S} theta_ji in every term. Accumulator Y (a prefix of chain j) state 0:
   N(Y = 0, E) = sum_{S subset findings \\ {j}} (-1)^|S| [ E(a_Y(D) prod_{l in S} q_l(D)) - Q(S u {j}) ]      (terminal-zero implies prefix-zero; shared activation variables are never double counted).
Common denominator: each root's denominator = lcm(prior denominators) x every inhibition denominator touching that root; x all leak denominators. Every term is then an integer over that
denominator (checked, not truncated). Signed sums run inside this executor only; nothing signed reaches support_closure, MBFloat or the PAC kernels.

Interface: recognize(model, queries, binding, deadline) -> Plan | NotApplicable | RecognitionRefused ; estimate(plan) -> dict ; execute(plan, deadline, workspace_budget) -> ExactOriginalMasses
| ZeroEvidence | ResourceRefused | DeadlineRefused | InvariantFailure (an implementation defect to investigate, never a fallback)."""
import time
from fractions import Fraction as F
from math import prod, lcm, inf
from collections import Counter


class NotApplicable(Exception): pass          # the model is outside the recognised family (typed refusal of this optional route)
class RecognitionRefused(Exception): pass     # recognition allowance / deadline exhausted
class ResourceRefused(Exception): pass        # projected workspace exceeds the budget (refused BEFORE materialisation)
class DeadlineRefused(Exception): pass        # deadline during evaluation (state released by the caller; nothing published)
class ZeroEvidence(Exception): pass           # exact: Znum == 0
class InvariantFailure(Exception): pass       # negative / non-integral / out-of-range exact quantity: a defect, reported as such


def tnow(): return time.monotonic()


class Plan:
    """checked parameters of the recognised family, copied out of the original model (closure may rewrite the model afterwards; this plan is immutable)"""
    __slots__ = ('n', 'roots', 'rid', 'priors', 'findings', 'leaks', 'chains', 'coeff', 'gate_of', 'gates', 'ev', 'binding', 'recognition_s', 'root_den', 'global_den')


def recognize(model, queries, binding, deadline):
    t0 = tnow(); cards = model['cards']; n = len(cards); ev = model.get('evidence', {}); facs = model['factors']
    if any(c != 2 for c in cards): raise NotApplicable('nonbinary variable')
    if len(facs) != n: raise NotApplicable('factor count %d != variables %d (one child factor per variable required)' % (len(facs), n))
    if any(v != 1 for v in ev.values()): raise NotApplicable('negative / internal evidence value')
    if any(len(f['scope']) not in (1, 2, 3) for f in facs): raise NotApplicable('factor arity outside {1, 2, 3}')
    priors = {}; gates = {}; terminals = {}; children = set(); uses = Counter()
    for k, f in enumerate(facs):
        if tnow() >= deadline: raise RecognitionRefused('recognition allowance exhausted at factor %d of %d' % (k, n))
        sc = tuple(f['scope']); vs = f['values']; child = sc[0]
        if child in children: raise NotApplicable('variable %d is the child of two factors' % child)
        children.add(child)
        if len(sc) == 1:
            if vs[0] + vs[1] != 1: raise NotApplicable('prior on %d does not normalise' % child)
            priors[child] = (vs[0], vs[1])
        elif len(sc) == 3:
            tp, th = vs[1], vs[2]
            if vs != [F(1), tp, th, th * tp, F(0), 1 - tp, 1 - th, 1 - th * tp]: raise NotApplicable('ternary factor on %d is not a child-first noisy-OR gate' % child)
            if not (0 <= th <= 1 and 0 <= tp <= 1): raise NotApplicable('gate parameter outside [0, 1]')
            gates[child] = (sc[1], sc[2], th, tp); uses.update(sc[1:])
        else:
            a, b, c, d = vs
            if not (a + c == 1 and b + d == 1): raise NotApplicable('binary factor on %d does not normalise child-first' % child)
            if not (0 < a <= 1 and 0 <= b <= a): raise NotApplicable('terminal on %d outside the family (a = %s, b = %s)' % (child, a, b))
            terminals[child] = (sc[1], a, b / a); uses.update(sc[1:])
    if children != set(range(n)): raise NotApplicable('some variable has no child factor')
    if set(terminals) != set(ev): raise NotApplicable('observed set != terminal set')
    for g, (root, prev, th, tp) in gates.items():
        if root not in priors: raise NotApplicable('gate %d: position 1 is not a root (unsupported axis layout refused)' % g)
        if prev not in priors and not (prev in gates and tp == 0): raise NotApplicable('gate %d: previous is an accumulator with nonzero inhibition' % g)
    if any(uses[g] != 1 for g in gates): raise NotApplicable('an accumulator has %s consumers' % sorted({uses[g] for g in gates if uses[g] != 1}))
    if any(uses[t] != 0 for t in terminals): raise NotApplicable('a terminal is consumed by another factor')
    roots = sorted(priors); rid = {r: i for i, r in enumerate(roots)}; findings = sorted(terminals); chains = []; coeffs = []; leaks = []; Dr = [1] * len(roots); seen_gates = set(); gate_of = {}
    for j, y in enumerate(findings):
        if tnow() >= deadline: raise RecognitionRefused('recognition allowance exhausted while walking chains')
        parent, leak, theta = terminals[y]; leaks.append(leak); coeff = {}; chain = []
        if parent in priors: coeff[parent] = theta; Dr[rid[parent]] *= theta.denominator
        else:
            if theta != 0: raise NotApplicable('terminal %d on an accumulator has nonzero inhibition' % y)
            cur = parent; back = []; seen = set(); base_theta = None
            while cur in gates:
                if cur in seen or cur in seen_gates: raise NotApplicable('shared or cyclic accumulator %d' % cur)
                seen.add(cur); seen_gates.add(cur); gate_of[cur] = j; root, prev, th, tp = gates[cur]; back.append((cur, root, th)); Dr[rid[root]] *= th.denominator; cur = prev; base_theta = tp
            if cur not in priors: raise NotApplicable('chain base %d is not a root' % cur)
            coeff[cur] = base_theta; Dr[rid[cur]] *= base_theta.denominator; chain = [(None, cur, base_theta)] + list(reversed(back))
            for _, root, th in reversed(back): coeff[root] = coeff.get(root, F(1)) * th
        chains.append(chain); coeffs.append(coeff)
    if seen_gates != set(gates): raise NotApplicable('%d accumulators belong to no observed chain' % (len(gates) - len(seen_gates)))
    P = Plan(); P.n = n; P.roots = roots; P.rid = rid; P.priors = priors; P.findings = findings; P.leaks = leaks; P.chains = chains; P.gates = gates; P.gate_of = gate_of; P.ev = dict(ev); P.binding = dict(binding)
    P.coeff = [[coeffs[j].get(r, F(1)) for r in roots] for j in range(len(findings))]
    P.root_den = [lcm(a.denominator, b.denominator) * d for (a, b), d in zip((priors[r] for r in roots), Dr)]; P.global_den = prod(x.denominator for x in leaks) * prod(P.root_den)
    P.recognition_s = tnow() - t0
    return P


def estimate(plan):
    """subset count, work and a conservative RETAINED-byte forecast of the exponential state (per subset: one Fraction per root + one int per root + three scalars; ints of root_den size)"""
    m = len(plan.findings); n = len(plan.roots); g = len(plan.gates); subsets = 1 << m
    root_bits = max(1, max(d.bit_length() for d in plan.root_den)); frac_bytes = 2 * (28 + (root_bits + 7) // 8) + 56; int_bytes = 28 + (root_bits + 7) // 8 + 8
    retained = subsets * (n * (frac_bytes + int_bytes) + 3 * (28 + (plan.global_den.bit_length() + 7) // 8) + 160)
    return dict(subsets=subsets, findings=m, roots=n, gates=g, work_touches=(m * n + g) * subsets, common_denominator_bits=plan.global_den.bit_length(), max_root_denominator_bits=root_bits, retained_bytes_estimate=retained)


class ExactOriginalMasses:
    __slots__ = ('Znum', 'D', 'num', 'stats')
    def __init__(self, Znum, D, num, stats): self.Znum = Znum; self.D = D; self.num = num; self.stats = stats     # num: {original var: (state, integer numerator of that state)}


def execute(plan, deadline, workspace_budget):
    t0 = tnow(); est = estimate(plan)
    if est['retained_bytes_estimate'] > workspace_budget: raise ResourceRefused('projected retained state %d B > workspace budget %d B (2^%d subsets x %d roots)' % (est['retained_bytes_estimate'], workspace_budget, est['findings'], est['roots']))
    roots = plan.roots; rid = plan.rid; m = len(plan.findings); subsets = 1 << m; root_den = plan.root_den; leak_den = prod(x.denominator for x in plan.leaks); global_den = plan.global_den
    p0int = [int(plan.priors[r][0] * den) for r, den in zip(roots, root_den)]; p1int = [int(plan.priors[r][1] * den) for r, den in zip(roots, root_den)]
    for r, den in zip(roots, root_den):
        if plan.priors[r][0] * den != int(plan.priors[r][0] * den) or plan.priors[r][1] * den != int(plan.priors[r][1] * den): raise InvariantFailure('prior of %d not integral over its denominator' % r)
    coeff = plan.coeff; leaks = plan.leaks
    theta_sets = [[F(1)] * len(roots)]; leak_sets = [F(1)]; term_products = []; terms = []; zero_counts = []; factors = []
    Znum = 0; root_num = [0] * len(roots); B = [0] * m
    for mask in range(subsets):
        if (mask & 63) == 0 and tnow() >= deadline: raise DeadlineRefused('deadline inside the subset sum (%d of %d)' % (mask, subsets))
        if mask:
            bit = mask & -mask; j = bit.bit_length() - 1; prev = mask ^ bit
            theta_sets.append([a * b for a, b in zip(theta_sets[prev], coeff[j])]); leak_sets.append(leak_sets[prev] * leaks[j])
        ts = theta_sets[mask]; tt = []
        for a, b, x in zip(p0int, p1int, ts):
            bx = b * x
            if bx.denominator != 1: raise InvariantFailure('root factor not integral over the common denominator')
            tt.append(a + int(bx))
        zeros = sum(1 for x in tt if x == 0); pnz = prod(x for x in tt if x); P = 0 if zeros else pnz
        lnf = leak_sets[mask] * leak_den
        if lnf.denominator != 1: raise InvariantFailure('leak product not integral over the leak denominator')
        ln = int(lnf); term = P * ln; sgn = -1 if mask.bit_count() % 2 else 1; Znum += sgn * term
        for r, (tr, br, th) in enumerate(zip(tt, p1int, ts)):
            if zeros == 0: other = P // tr
            elif zeros == 1 and tr == 0: other = pnz
            else: continue
            root_num[r] += sgn * ln * other * int(br * th)
        for j in range(m):
            if mask & (1 << j): B[j] -= sgn * term
        terms.append(term); term_products.append(pnz); zero_counts.append(zeros); factors.append(tt)
    if Znum == 0: raise ZeroEvidence('exact evidence mass is zero')
    if Znum < 0: raise InvariantFailure('negative normalizer numerator')
    normalizer_s = tnow() - t0
    gate_zero = {g: 0 for g in plan.gates}
    for j, chain in enumerate(plan.chains):
        if not chain: continue
        for mask in range(subsets):
            if mask & (1 << j): continue
            if (mask & 63) == 0 and tnow() >= deadline: raise DeadlineRefused('deadline inside the prefix sums (chain %d)' % j)
            sgn = -1 if mask.bit_count() % 2 else 1; ln = int(leak_sets[mask] * leak_den); tt = list(factors[mask]); nz = zero_counts[mask]; P = term_products[mask]; partial = {}
            for g, root, th in chain:
                r = rid[root]; partial[r] = partial.get(r, F(1)) * th; f = p1int[r] * theta_sets[mask][r] * partial[r]
                if f.denominator != 1: raise InvariantFailure('prefix factor not integral over the common denominator')
                new = p0int[r] + int(f); old = tt[r]
                if old: P //= old
                else: nz -= 1
                if new: P *= new
                else: nz += 1
                tt[r] = new
                if g is not None: gate_zero[g] += sgn * ln * (0 if nz else P)
        for g, root, th in chain:
            if g is not None: gate_zero[g] -= B[j]
    if any(not (0 <= x <= Znum) for x in root_num) or any(not (0 <= x <= Znum) for x in gate_zero.values()): raise InvariantFailure('a numerator is outside [0, Znum]')
    num = {r: (1, v) for r, v in zip(roots, root_num)}; num.update({g: (0, v) for g, v in gate_zero.items()})
    if len(num) != plan.n - len(plan.ev): raise InvariantFailure('recovered %d variables, expected %d' % (len(num), plan.n - len(plan.ev)))
    stats = dict(est, normalizer_numerator_bits=Znum.bit_length(), cancellation_bits=(max(x.bit_length() for x in terms) - Znum.bit_length()), normalizer_and_root_queries_s=normalizer_s, prefix_queries_s=tnow() - t0 - normalizer_s)
    del theta_sets, leak_sets, term_products, terms, zero_counts, factors
    return ExactOriginalMasses(Znum, global_den, num, stats)


def dyadic_rows(masses, queries, grid_log2=40):
    """outward dyadic enclosures of every requested ORIGINAL coordinate from the exact masses: lo = floor(2^g N / Z) / 2^g, hi = ceil(...) / 2^g, point = midpoint; DETERMINISTIC (EXACT when lo == hi)"""
    Q = 1 << grid_log2; Z = masses.Znum; rows = {}
    for j, (x, s) in enumerate(queries):
        st, nn = masses.num[x]
        if s != st: nn = Z - nn
        lo = (nn * Q) // Z; hi = -((-nn * Q) // Z)
        rows[j] = dict(lo=F(lo, Q), hi=F(hi, Q), point=F(lo + hi, 2 * Q), guarantee=('EXACT' if lo == hi else 'DETERMINISTIC'))
    return rows
