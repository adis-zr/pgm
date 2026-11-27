"""DGP6 global construction, part 3: the INDEPENDENT certifier of the scalar circuits (brief section 4a). Given the canonical target identity (M_par), the ACTUAL proposal counts and the structural CircuitPlan, it re-derives the
expected raw sources (every unary / factor of W_0 at the plan's power once; one reciprocal per conditional once; values and axes from the target / counts, never from the producer), re-evaluates every product (exact big-int),
every reduction (MAX by exact comparison; SUM by the separately proved bounded upward sum) and the closure, verifies the producer's compact value dominates it, and returns upward B / S bound to the model / graph / count
identities. Blind to arm names. Exact-rational references (<= 4,096 states) and vectorized floating enumeration (<= 65,536 states) for the oracle: true max weight, M2, per-query moments."""
import math, itertools, hashlib
from fractions import Fraction as F
import numpy as np
from pgm.algorithms.quotient import coarse_envelope as CE
from pgm.algorithms.quotient import residual_max_envelope as RM
from pgm.algorithms.quotient.residual_max_envelope import ZERO, norm_up, from_fraction_up, to_fraction, mul_exact, ge_exact, sum_up, lead, log2_up
from pgm.algorithms.quotient import joint_proposal as JP
from pgm.algorithms.quotient.joint_proposal import D, D_BITS, vol_of
from pgm.algorithms.quotient import check_joint as CJ
from pgm.algorithms.quotient.global_circuit import _bcast, ENTRY_C


def _exact_entry(nd, M_par, prop, idx, cards):
    """the exact rational value of a source leaf at a multi-index over its sorted axes (derived from the target / counts, independent of the producer)"""
    if nd['role'] == 'unary': return F(M_par.psi[nd['key']][idx[0]]) ** nd['power']
    if nd['role'] == 'factor':
        sc, vals = M_par.factors[nd['key']]; sc = tuple(sc); axes = nd['axes']; st = CE.strides([cards[v] for v in sc]); return F(vals[sum(st[j] * idx[axes.index(v)] for j, v in enumerate(sc))]) ** nd['power']
    c = prop.conds[nd['key']]; axes = nd['axes']; row = sum(c.pstrides[p_] * idx[axes.index(p_)] for p_ in c.parents) if c.parents else 0; return F(D, int(c.counts[row, idx[axes.index(c.z)]]))


def _source_checks(nd, plan, M_par, prop, exp_roles, seen):
    role = nd.get('role')
    if role not in seen: return 'unknown source role %r' % role
    if nd['key'] in seen[role]: return 'source %s %s occurs twice in the plan' % (role, nd['key'])
    if nd['key'] not in exp_roles[role]: return 'source %s %s is not in the expected inventory' % (role, nd['key'])
    axes = tuple(nd['axes'])
    if role == 'reciprocal' and axes != tuple(sorted(prop.conds[nd['key']].parents + (nd['key'],))): return 'reciprocal %d axes %s do not match the actual conditional' % (nd['key'], axes)
    if role == 'factor' and axes != tuple(sorted(M_par.factors[nd['key']][0])): return 'factor %d axes %s do not match the target' % (nd['key'], axes)
    if role == 'unary' and axes != (nd['key'],): return 'unary %d axes %s' % (nd['key'], axes)
    if role != 'reciprocal' and nd.get('power') != plan.power: return 'source power %s != plan power %d' % (nd.get('power'), plan.power)
    if role == 'reciprocal' and nd.get('power') != 1: return 'reciprocal power %s != 1' % (nd.get('power'),)
    if nd.get('omitted'): return 'source %s %s is marked omitted (no value)' % (role, nd['key'])
    return None


def expected_plan(plan, M_par, prop, order_elim, kind, clock=None, budget=None):
    """DGP7 repair R1: the certifier REBUILDS the structural plan of the claimed proof kind from the target (cards, factor scopes), the actual proposal (sampling order, parents) and the elimination order -- cap = power 1 / all MAX;
    moment = power 2 / SUM at group 0 of every stage -- with the submitted plan's caps V / fan-in, and compares structural identities; the submitted plan's SUM / MAX labels, powers, constants and closure are never trusted.
    DGP9 repair (original DGP7 finding F4b): the reconstruction is ADMITTED under the caller's budget and POLLED at entry (the DGP8 code allocated the expected plan without admission even at zero headroom); the caller releases it."""
    from pgm.algorithms.quotient.global_circuit import CircuitPlan
    power = 1 if kind == 'cap' else 2; cards = list(M_par.cards); scopes = [tuple(sc) for sc, _ in M_par.factors]; parents = {int(v): tuple(prop.conds[v].parents) for v in prop.order}
    return CircuitPlan(cards, list(prop.order), parents, scopes, power, list(order_elim), plan.V, plan.fanin, clock=clock, budget=budget)


def structural_checks(plan, kind, cards):
    """R1 structural rules independent of the producer: every reduce's cardinality equals cards[axis]; the aggregation per stage = all MAX (cap) or SUM exactly at the first group of every eliminated variable (moment); const_card only in the
    moment plan; non-reciprocal source powers equal the proof power; every eliminated variable's stage consumes exactly the live tables carrying it (a complete, non-overlapping partition); nothing remains after the last stage"""
    stages = {}
    for i, nd in enumerate(plan.nodes):
        if nd['op'] == 'reduce':
            if nd.get('m') != cards[nd['axis']]: return 'reduce %d: cardinality %s != cards[%d] = %d' % (i, nd.get('m'), nd['axis'], cards[nd['axis']])
            stages.setdefault(nd['axis'], []).append(nd['agg'])
        elif nd['op'] == 'const_card' and kind == 'cap': return 'const_card node %d in a cap plan' % i
        elif nd['op'] == 'source' and nd['role'] != 'reciprocal' and nd.get('power') != (1 if kind == 'cap' else 2): return 'source %d power %s != the %s proof power' % (i, nd.get('power'), kind)
    for v, aggs in stages.items():
        if kind == 'cap' and any(a_ != 'max' for a_ in aggs): return 'cap proof: variable %d has a non-MAX group' % v
        if kind == 'moment' and (aggs[0] != 'sum' or any(a_ != 'max' for a_ in aggs[1:])): return 'moment proof: variable %d groups %s (SUM must be exactly the first group)' % (v, aggs)
    live = {i for i, nd in enumerate(plan.nodes) if nd['op'] == 'source'}
    for st in plan.stages:
        v = st['v']; carrying = {j for j in live if v in plan.nodes[j].get('axes', ())}; consumed = []
        for g in st.get('groups', []): consumed += list(g['inputs'])
        if sorted(consumed) != sorted(carrying): return 'variable %d: the stage consumes %s but the live tables carrying it are %s (incomplete / overlapping partition)' % (v, sorted(consumed), sorted(carrying))
        live -= set(consumed); live |= {g['reduce'] for g in st.get('groups', []) if g['out_axes']}
    if live: return 'tables never eliminated: %s' % sorted(live)[:6]
    return None


def certify(plan, M_par, prop, producer_value, clock, budget=None, graph_sha=None, order_elim=None, kind=None):
    """-> receipt(ok, value (compact upward), log2, why, roles, cells, identities). DGP7 repair R1: `kind` ('cap' | 'moment') is the proof the CALLER claims; when `order_elim` is given the certifier rebuilds the expected structural plan
    of that kind and requires the submitted plan's structural identity to equal it (an all-MAX plan labelled moment is rejected before any arithmetic); the structural rules (stages, complete partitions, aggregation ownership, powers,
    constants, closure) are checked in every case. Independent re-derivation of the whole circuit in compact arithmetic from the EXPECTED sources (inventory = every unary / factor of the
    target at the plan's power exactly once + one reciprocal per conditional of the ACTUAL proposal; values / axes from the target and the counts, never from the producer; each source materialized lazily inside its
    consuming product and dropped after it); every product is checked for exact multiplicity, axis containment and the fan-in / volume caps, every reduction for its axis map, the closure for its scalar inventory; the live
    set is bounded by the plan's peak; the producer's value must dominate the re-derivation"""
    cards = list(M_par.cards); A = RM.Arith('compact'); vals = {}; cells = 0; owned = 0; charged = {}; t0 = CE.tnow()
    kind = kind or ('cap' if plan.power == 1 else 'moment')
    if kind not in ('cap', 'moment'): return dict(ok=False, why='unknown proof kind %r' % kind)
    if plan.power != (1 if kind == 'cap' else 2): return dict(ok=False, why='plan power %d does not match the claimed %s proof' % (plan.power, kind))
    if order_elim is not None:
        exp = expected_plan(plan, M_par, prop, order_elim, kind, clock, budget=budget); ps = plan.structural_sha256() if hasattr(plan, 'structural_sha256') else plan.sha256; exp_sha = exp.sha256; exp.release(); exp = None       # DGP9 (F4b): admitted, compared, released
        if ps != exp_sha: return dict(ok=False, why='the submitted plan\'s structure does not match the independently rebuilt %s proof plan (sha %s != %s)' % (kind, ps[:12], exp_sha[:12]))
        if ps != plan.sha256: return dict(ok=False, why='the submitted plan\'s recorded sha256 does not match its own structure')
    why = structural_checks(plan, kind, cards)
    if why: return dict(ok=False, why='structure: ' + why)
    exp_roles = dict(unary=set(range(len(cards))), factor=set(range(len(M_par.factors))), reciprocal=set(prop.order)); seen = dict(unary=set(), factor=set(), reciprocal=set()); consumed = set()
    def admit(i, n_):
        nonlocal owned
        if budget is not None: budget.charge(n_, 'certifier node %d' % i); charged[i] = n_; owned += n_
    def drop(j):
        nonlocal owned
        vals[j] = None
        if j in charged: budget.release(charged[j]); owned -= charged.pop(j)
    try:
        for i, nd in enumerate(plan.nodes):
            op = nd['op']
            if op == 'source': continue
            if op == 'const_card': vals[i] = np.array(from_fraction_up(F(nd['value'])), dtype=object).reshape(())
            elif op == 'product':
                u = tuple(nd['axes']); vol = vol_of(u, cards)
                if len(nd['inputs']) > plan.fanin or vol > plan.V: return dict(ok=False, why='product %d violates fan-in / volume' % i)
                if len(set(nd['inputs'])) != len(nd['inputs']): return dict(ok=False, why='product %d uses an input twice' % i)
                for j in nd['inputs']:
                    if j in consumed: return dict(ok=False, why='product %d consumes node %d twice' % (i, j))
                    if not set(plan.nodes[j]['axes']) <= set(u): return dict(ok=False, why='product %d input %d axes %s outside the union %s' % (i, j, plan.nodes[j]['axes'], u))
                    if plan.nodes[j]['op'] == 'source':
                        why = _source_checks(plan.nodes[j], plan, M_par, prop, exp_roles, seen)
                        if why: return dict(ok=False, why=why)
                        seen[plan.nodes[j]['role']].add(plan.nodes[j]['key']); axes = tuple(plan.nodes[j]['axes']); admit(j, ENTRY_C * vol_of(axes, cards) + 128); clock.poll('certifier source %d' % j); arr = np.empty([cards[a] for a in axes], dtype=object)
                        for k_, idx in enumerate(itertools.product(*[range(cards[a]) for a in axes])):
                            x = _exact_entry(plan.nodes[j], M_par, prop, idx, cards); arr[idx] = A.conv(x) if x > 0 else ZERO; cells += 1
                            if (k_ & 255) == 255: clock.poll('certifier source %d' % j)
                        vals[j] = arr
                    elif vals.get(j) is None: return dict(ok=False, why='product %d consumes node %d before it exists' % (i, j))
                admit(i, ENTRY_C * vol * 2 + 128); clock.poll('certifier product %d' % i); acc = None
                for j in nd['inputs']:
                    v_ = _bcast(vals[j], plan.nodes[j]['axes'], u, cards); acc = v_ if acc is None else A.mul(acc, v_)
                vals[i] = A.norm(np.broadcast_to(acc, [cards[a] for a in u]).copy()); cells += vol * len(nd['inputs'])
                for j in nd['inputs']: consumed.add(j); drop(j)
            elif op == 'reduce':
                j = nd['input']
                if j in consumed or vals.get(j) is None: return dict(ok=False, why='reduce %d consumes node %d twice / before it exists' % (i, j))
                x = vals[j]; inax = plan.nodes[j]['axes']
                if nd['axis'] not in inax or tuple(nd['axes']) != tuple(a for a in inax if a != nd['axis']): return dict(ok=False, why='reduce %d axis map mismatch' % i)
                ax = inax.index(nd['axis']); admit(i, ENTRY_C * vol_of(nd['axes'], cards) + 128); clock.poll('certifier reduce %d' % i)
                if nd['agg'] == 'max': out = np.maximum.reduce(x, axis=ax) if x.shape[ax] > 1 else x.reshape([s_ for k_, s_ in enumerate(x.shape) if k_ != ax])
                elif nd['agg'] == 'sum':
                    mv = np.moveaxis(x, ax, -1); flat = mv.reshape(-1, mv.shape[-1]); res = np.empty(flat.shape[0], dtype=object)
                    for r in range(flat.shape[0]): res[r] = sum_up(list(flat[r]))
                    out = res.reshape(mv.shape[:-1])
                else: return dict(ok=False, why='reduce %d: unknown aggregation %r' % (i, nd['agg']))
                if not isinstance(out, np.ndarray): sc_ = np.empty((), dtype=object); sc_[()] = out; out = sc_
                vals[i] = out; cells += int(x.size); consumed.add(j); drop(j)
            elif op == 'closure':
                used = list(nd['inputs'])
                if len(set(used)) != len(used): return dict(ok=False, why='closure uses a scalar twice')
                live_scalars = [k for k, v in vals.items() if v is not None and k not in consumed and plan.nodes[k]['op'] in ('reduce', 'const_card') and not plan.nodes[k].get('axes')]
                if set(used) != set(live_scalars): return dict(ok=False, why='closure inventory %s != live scalars %s' % (sorted(used), sorted(live_scalars)))
                val = (0, 1)
                for j in used:
                    x = vals[j].reshape(-1)[0] if isinstance(vals[j], np.ndarray) else vals[j]
                    if x[1] == 0: val = ZERO; break
                    val = norm_up(*mul_exact(val, x))
                vals[i] = val
            else: return dict(ok=False, why='unknown node op %r' % op)
        for role in ('unary', 'factor', 'reciprocal'):
            if seen[role] != exp_roles[role]: return dict(ok=False, why='expected %s inventory %s != plan %s' % (role, sorted(exp_roles[role]), sorted(seen[role])))
        left = [k for k, v in vals.items() if v is not None and k not in consumed and plan.nodes[k].get('axes')]
        if left: return dict(ok=False, why='tables remain unconsumed after the plan: %s' % left[:8])
        val = vals[plan.closure]
        if producer_value is not None and not ge_exact(producer_value, val): return dict(ok=False, why='the producer value does not dominate the independent re-derivation', producer=(producer_value[0], str(producer_value[1])[:20]), independent=(val[0], str(val[1])[:20]))
        ident = hashlib.sha256(repr((plan.sha256, [(v, prop.conds[v].sha256) for v in prop.order], [[str(x) for x in ps] for ps in M_par.psi], [[list(sc), [str(x) for x in vv]] for sc, vv in M_par.factors])).encode()).hexdigest()
        return dict(ok=True, value=val, log2=(log2_up(val) if val[1] else -math.inf), cells=cells, seconds=CE.tnow() - t0, roles={k: len(v) for k, v in seen.items()}, identity=ident, plan_sha256=plan.sha256, graph_sha256=graph_sha, units=('W_0' if plan.power == 1 else 'W_0^2'), kind=kind, structure_rebuilt=(order_elim is not None))
    finally:
        if budget is not None and owned: budget.release(owned)


def mutate_omit(plan, role, key):
    """a plan with one source leaf removed (for the omitted-source control): the structural plan is rebuilt WITHOUT that leaf so dominance can still be computed; the certifier must reject it on the inventory"""
    import copy; p2 = copy.copy(plan); p2.nodes = [dict(nd) for nd in plan.nodes]; idx = next(i for i, nd in enumerate(p2.nodes) if nd['op'] == 'source' and nd['role'] == role and nd['key'] == key)
    p2.nodes[idx] = dict(op='source', role=role, key=key, axes=plan.nodes[idx]['axes'], power=plan.nodes[idx]['power'], omitted=True, **({'layout': plan.nodes[idx]['layout']} if 'layout' in plan.nodes[idx] else {})); return p2, idx


# ---------------------------------------------------------------- references (oracle / controls)
def ref_exact_BS(M_par, prop, cap=1 << 12):
    """EXACT rational B* = max W_0 / q and S* = sum W_0^2 / q by enumeration (<= 4,096 states)"""
    states, W = CJ.ref_enumerate(M_par, cap); Bst = F(0); Sst = F(0); Z0 = F(0)
    for x, w in zip(states, W):
        Z0 += w
        if w == 0: continue
        q = prop.q_exact(x); Bst = max(Bst, w / q); Sst += w * w / q
    return dict(B_star=Bst, S_star=Sst, Z0=Z0, log2_B_star=(float(CJ.lg_bounded(Bst)) if Bst > 0 else -math.inf), log2_S_star=(float(CJ.lg_bounded(Sst)) if Sst > 0 else -math.inf), log2_Z0=(float(CJ.lg_bounded(Z0)) if Z0 > 0 else -math.inf))


def float_law_quantities(prop, states, logW0, G=None, mu=None):
    """vectorized floating enumeration (<= 65,536 states): log2 B* (true max weight), log2 S*, log2 Z0, log2 M2 = S* / Z0^2, per-query second moments V_j = sum p^2 / q (g_j - mu_j)^2 (floating DIAGNOSTICS)"""
    q = CJ.oracle_law_quantities(prop, states, logW0); out = dict(log2_Z0=q['log2_Z0'], log2_B_star=q['log2_Rstar'], log2_S_star=q['log2_S0'], log2_M2=q['log2_M2'], log2_B_star_over_Z0=q['log2_Rstar_over_Z0'], max_log2_X=q['max_log2_X'])
    if G is not None and mu is not None:
        n = len(prop.cards); lq = np.zeros(states.shape[0])
        for v in prop.order:
            c = prop.conds[v]; rows = c.row_index(states); lq += np.log2(c.counts[rows, states[:, v]].astype(float))
        lq -= D_BITS * n; fin = np.isfinite(logW0)
        lw = np.where(fin, 2 * (logW0 - q['log2_Z0']) - lq, -np.inf); m = lw[fin].max(); wq = np.where(fin, np.exp2(lw - m), 0.0); Vj = (wq[:, None] * (G - mu[None, :]) ** 2).sum(axis=0) * (2.0 ** m)
        out.update(V_j_max=float(Vj.max()), V_j_median=float(np.median(Vj)), log2_V_j_max=(float(np.log2(Vj.max())) if Vj.max() > 0 else None))
    return out
