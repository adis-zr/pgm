"""CERTIFIED LAYERED CONTRACTION (round 20, 23 Nov 2026; CLAUDE_IMPLEMENTATION_BRIEF.md of the R20 theory packet).

A structural CONSTRUCTOR that recognises a sequence of local blocks joined by MATCHING BINARY CHANNELS, compiles it into a complete elimination order with a checked
volume certificate, and executes that order with the EXISTING certified native executor (cex/newarm/cex_executor.py: compiled nonnegative bucket contraction + zero-safe
all-singleton reverse, binary64 with reciprocal-envelope labels, exact N / Z enclosure, typed stops). The brief's bounded probe (records round20/probe) showed the native
executor runs the packet's checked order on the exposed target in 8.1 s / 574 MiB, so the "planned-exact adapter" is the smallest sufficient integration. Correctness of
every published row rests on the executor's certificate for ANY valid order; this module decides only WHICH order (affordability) and refuses by type otherwise.

Grammar (exact rational predicates on the EVIDENCE-RESTRICTED model; variable ids, scope orientation, model names and table constants play no role):
  constant factor      every entry equal (its value multiplies the global constant; the kernel keeps it, so no scalar is lost)
  channel              two active binary variables, table [a, b; b, a] with a > 0, b > 0, a != b, a + b = 1 (any rational a, b)
  endpoint fragment    one active binary variable left of a 2-axis table, entries positive, unequal, summing to 1: a LOCAL factor
  residual             nonconstant, non-Boolean (values not within {0, 1}), >= 2 active variables, not a channel
  local core           the remaining factors (Boolean constraints, unary weights, fragments) joined by shared active variables
The active channel graph must consist of disjoint PATHS (branching / cycles refuse). Each path c gets an arbitrary index i along it; a valid adjacent-layer matching schedule
forces layer(c, i) = o_c + s_c i with s_c in {-1, +1}; two path positions inside one local core must share a layer. Offsets are eliminated along a spanning forest of these
equalities; the remaining homogeneous sign system is solved EXACTLY (rational RREF, standard nullspace basis); admission requires a separable unit sign basis and at most
MAX_FREE_SIGN_BITS relevant free main-component sign directions, which bounds the search (2^k candidates). Per candidate: translate each core-connected chain group to
minimum layer 0; residual factors must occupy one extreme adjacent layer pair (a low-end anchor reflects the component); fold that terminal pair into one stage; then
VALIDATE independently of the derivation: every nonconstant factor is wholly inside one stage or is an exact channel between adjacent stages, and every boundary's
channels form a matching. The best admitted candidate (lexicographic: interface bits, local product, local volume, signs) yields the order: per component, per stage,
greedy local elimination of the non-interface variables, then the interface (selector) variables in stage order. A primal-graph simulation of THAT order certifies the
maximum product / output volumes and the summed volumes that forecast kernel work and retained bytes; admission compares them with the caps and the live headroom.

Interface: recognize(model, deadline) -> Plan | NotApplicable | RecognitionRefused ; execute(plan, model, deadline, cap_bytes, host_reserved_bytes) -> Result
(intervals, points, Z enclosure as exact rationals, stats) | ExecutorRefused (typed stop) | ZeroEvidence. Rows are published by the caller (integrated.py) as outward
dyadic compactions labelled DETERMINISTIC (EXACT when the enclosure is a point: exact zeros, one-state variables, factorless uniform rows). Z is reported as an ENCLOSURE
[Zhat (1 - K u), Zhat / (1 - K u)] x cancelled scalars (K = the kernel's normalizer label), never as an exact rational point."""
import os, sys, time, math, json
from fractions import Fraction as F
from itertools import product as iproduct
from collections import defaultdict, Counter
HERE = os.path.dirname(os.path.abspath(__file__)); NEWARM = os.path.join(os.path.dirname(os.path.dirname(HERE)), 'cex', 'newarm')
if NEWARM not in sys.path: sys.path.insert(0, NEWARM)
import cex_executor as CX
import ctypes as C

MAX_FREE_SIGN_BITS = 8          # bounded sign search (the brief's limit); the exposed target has 5
U = F(1, 1 << 53)


class NotApplicable(Exception): pass         # outside the recognised family (typed refusal of this OPTIONAL route, never of the task)
class RecognitionRefused(Exception): pass    # recognition allowance / deadline exhausted
class ResourceRefused(Exception): pass       # forecast exceeds the caps or the headroom (refused BEFORE the executor allocates)
class ExecutorRefused(Exception):            # the native executor's typed stop (DEADLINE / MEMORY / RANGE / WIDTH / ...): nothing published, the caller falls back
    def __init__(self, kind, reason, stats=None): super().__init__('%s: %s' % (kind, reason)); self.kind = kind; self.reason = reason; self.stats = stats or {}
class ZeroEvidence(Exception): pass          # the executor's exact zero-evidence outcome


def tnow(): return time.monotonic()


class Plan:
    __slots__ = ('order', 'active', 'n', 'ev', 'cards', 'singletons', 'factorless', 'cancelled_scalar', 'cancelled_count', 'structure', 'volume', 'recognition_s', 'binding')


def _restrict(model, deadline=math.inf):
    """exact evidence restriction (the rule of cex_executor.lower): observed axes are sliced to the observed state; returns per-factor (active scope, table over active axes) with
    cardinality-one axes also removed from the active scope, plus the exact product of factors whose restricted scope is EMPTY (the scalars lower() cancels) and their count"""
    cards = model['cards']; ev = model.get('evidence', {}); facs = []; scalar = F(1); cancelled = 0
    for k, f in enumerate(model['factors']):
        if (k & 63) == 63 and tnow() >= deadline: raise RecognitionRefused('recognition allowance exhausted during evidence restriction')
        sc = tuple(f['scope']); vals = f['values']
        if any(v in ev for v in sc):
            keep = [i for i, v in enumerate(sc) if v not in ev]; data = []
            for a, w in zip(iproduct(*(range(cards[v]) for v in sc)), vals):
                if all(a[i] == ev[v] for i, v in enumerate(sc) if v in ev): data.append(w)
            nsc = tuple(sc[i] for i in keep)
        else: nsc = sc; data = vals
        if not nsc: scalar *= data[0]; cancelled += 1; continue
        facs.append((nsc, data))
    return facs, scalar, cancelled


def _active_table(sc, data, cards):
    """drop cardinality-one axes (they index a single row): active scope + the same entries"""
    act = tuple(v for v in sc if cards[v] > 1)
    return act, data


def _is_channel(act, data, cards):
    if len(act) != 2 or any(cards[v] != 2 for v in act) or len(data) != 4: return False
    a, b, c, d = data
    return a > 0 and b > 0 and a != b and a == d and b == c and a + b == 1


def _rref_nullspace(rows, ncols):
    """exact rational RREF of an integer matrix (list of rows) and its STANDARD nullspace basis (one vector per free column: 1 at the free column, minus the pivot-row
    coefficient at each pivot column); the same canonical basis sympy's Matrix.nullspace() returns, so the separability admission is representation-independent"""
    M = [[F(x) for x in r] for r in rows]; piv = []; r = 0
    for c in range(ncols):
        p = next((i for i in range(r, len(M)) if M[i][c] != 0), None)
        if p is None: continue
        M[r], M[p] = M[p], M[r]; inv = 1 / M[r][c]; M[r] = [x * inv for x in M[r]]
        for i in range(len(M)):
            if i != r and M[i][c] != 0:
                f = M[i][c]; M[i] = [x - f * y for x, y in zip(M[i], M[r])]
        piv.append(c); r += 1
        if r == len(M): break
    free = [c for c in range(ncols) if c not in piv]; basis = []
    for fcol in free:
        v = [F(0)] * ncols; v[fcol] = F(1)
        for i, pc in enumerate(piv): v[pc] = -M[i][fcol]
        basis.append(v)
    return basis, len(piv)


def recognize(model, deadline=math.inf, binding=None):
    t0 = tnow(); cards = model['cards']; n = len(cards); ev = model.get('evidence', {})
    def poll(where):
        if tnow() >= deadline: raise RecognitionRefused('recognition allowance exhausted %s' % where)
    facs, scalar, cancelled = _restrict(model, deadline); poll('after evidence restriction')
    # ---- classify (cheap channel census first: a model without any channel refuses before any large table is inspected)
    tabs = [_active_table(sc, data, cards) for sc, data in facs]
    chan = [i for i, (act, data) in enumerate(tabs) if _is_channel(act, data, cards)]
    if not chan: raise NotApplicable('no exact symmetric binary channel factor')
    const = []; resid = set(); local = []
    for i, (act, data) in enumerate(tabs):
        if (i & 255) == 255: poll('while classifying factors')
        if i in chan: continue
        first = data[0]
        if all(x == first for x in data): const.append(i); continue
        if not act: raise NotApplicable('a nonconstant factor without active variables')     # cannot happen after restriction (data[0] constant) but typed anyway
        if len(act) >= 2 and not all(x == 0 or x == 1 for x in data): resid.add(i); continue
        local.append(i)
    par_all = list(range(n))
    def find(par, x):
        while par[x] != x: par[x] = par[par[x]]; x = par[x]
        return x
    def join(par, a, b): par[find(par, a)] = find(par, b)
    for i, (act, data) in enumerate(tabs):
        if i in const or not act: continue
        for v in act[1:]: join(par_all, act[0], v)
    poll('after component union')
    touched = set(v for i, (act, _) in enumerate(tabs) if i not in const for v in act)
    activevars = [v for v in range(n) if cards[v] > 1 and v not in ev and v in touched]          # variables of nonconstant factors; factorless ones get their exact uniform row
    wg = defaultdict(list)
    for v in activevars: wg[find(par_all, v)].append(v)
    comp_of = {v: find(par_all, v) for v in activevars}; main = max(wg, key=lambda r: len(wg[r]))
    # ---- channel graph: disjoint paths (shared by both proposals)
    vadj = defaultdict(set); transvars = set()
    for i in chan:
        a, b = tabs[i][0]; vadj[a].add(b); vadj[b].add(a); transvars.update((a, b))
    seen = set(); chains = []; pos = {}
    for v in sorted(transvars):
        if v in seen: continue
        comp = {v}; stack = [v]; seen.add(v)
        while stack:
            for y in vadj[stack.pop()] - seen: seen.add(y); comp.add(y); stack.append(y)
        if max(len(vadj[x]) for x in comp) > 2: raise NotApplicable('branching channel graph (a variable with %d channels)' % max(len(vadj[x]) for x in comp))
        ends = [x for x in comp if len(vadj[x]) < 2]
        if not ends: raise NotApplicable('cyclic channel graph')
        x = min(ends); prev = None; chain = []
        while x is not None:
            chain.append(x); nxt = vadj[x] - {prev}; prev, x = x, (min(nxt) if nxt else None)
        if set(chain) != comp: raise NotApplicable('invalid channel walk')
        c = len(chains); chains.append(chain)
        for j, v in enumerate(chain): pos[v] = (c, j)
    Cn = len(chains); poll('after the chain walk')
    def in_main(c): return comp_of[chains[c][0]] == main

    def align(excluded, label):
        """one PROPOSAL: local cores = non-channel factors outside `excluded` joined by shared active variables; `excluded` factors (residuals) must land in one extreme adjacent
        layer pair of their component, which is then folded into one terminal stage. Returns (key, layer, stage, interfaces, locals_, matches, info, diag) or raises NotApplicable.
        Every returned plan has passed the exact locality / adjacency / matching validation, which does not depend on how the proposal was formed."""
        par_loc = list(range(n))
        for i, (act, data) in enumerate(tabs):
            if i in const or not act or i in chan or i in excluded: continue
            for v in act[1:]: join(par_loc, act[0], v)
        members = defaultdict(list)
        for v in activevars: members[find(par_loc, v)].append(v)
        eq = []; gadj = [set() for _ in chains]
        for vs in members.values():
            sel = sorted(v for v in vs if v in pos)
            for v in sel[1:]:
                left, right = pos[sel[0]], pos[v]; eq.append((left, right)); gadj[left[0]].add(right[0]); gadj[right[0]].add(left[0])
        links = [[] for _ in chains]
        for (c, j), (d, k) in eq: links[c].append((d, j, k)); links[d].append((c, k, j))
        forms = [None] * Cn; ngroups = 0
        for c in range(Cn):
            if forms[c] is not None: continue
            forms[c] = [0] * Cn; stack = [c]; ngroups += 1
            while stack:
                q = stack.pop()
                for d, j, k in links[q]:
                    if forms[d] is None: forms[d] = forms[q][:]; forms[d][q] += j; forms[d][d] -= k; stack.append(d)
        poll('after the spanning forest (%s)' % label)
        Brows = []
        for (c, j), (d, k) in eq:
            row = [forms[c][z] - forms[d][z] for z in range(Cn)]; row[c] += j; row[d] -= k; Brows.append(row)
        sign_basis, srank = _rref_nullspace(Brows, Cn) if Brows else ([[F(int(z == c)) for z in range(Cn)] for c in range(Cn)], 0)
        poll('after the exact nullspace (%s)' % label)
        basis = []
        for sb in sign_basis:
            bb = []
            for c in range(Cn): bb.extend([sum(forms[c][z] * sb[z] for z in range(Cn)), sb[c]])
            basis.append(bb)
        owners = {}; sign_dirs = []
        for bi, bvec in enumerate(basis):
            cs = [c for c in range(Cn) if bvec[2 * c + 1] != 0]
            if cs: sign_dirs.append(bi)
            for c in cs:
                if c in owners or abs(bvec[2 * c + 1]) != 1: raise NotApplicable('nonseparable sign nullspace (%s): the bounded alignment refuses' % label)
                owners[c] = bi
        if len(owners) != Cn: raise NotApplicable('a chain sign is forced to zero by the core equalities (%s)' % label)
        backbone = max(sign_dirs, key=lambda bi: sum(len(chains[c]) for c in range(Cn) if basis[bi][2 * c + 1] != 0 and in_main(c)))
        free = [bi for bi in sign_dirs if bi != backbone and any(basis[bi][2 * c + 1] != 0 and len(chains[c]) > 1 and in_main(c) for c in range(Cn))]
        if len(free) > MAX_FREE_SIGN_BITS: raise NotApplicable('%d free main-component sign bits exceed the bounded search (%d) (%s)' % (len(free), MAX_FREE_SIGN_BITS, label))
        groups = []; seen2 = set()
        for c in range(Cn):
            if c in seen2: continue
            stack = [c]; seen2.add(c); cs = []
            while stack:
                d = stack.pop(); cs.append(d)
                for q in gadj[d] - seen2: seen2.add(q); stack.append(q)
            groups.append(cs)
        resid_by_comp = defaultdict(list)
        for i in excluded: resid_by_comp[comp_of[tabs[i][0][0]]].append(i)
        candidates = []; best = None; examined = 0
        for signs in iproduct((-1, 1), repeat=len(free)):
            examined += 1; poll('inside the sign search (%s, candidate %d)' % (label, examined))
            coef = {bi: 1 for bi in sign_dirs}; coef.update(dict(zip(free, signs)))
            x = [sum(basis[bi][j] * coef.get(bi, 0) for bi in range(len(basis))) for j in range(2 * Cn)]
            if any(abs(x[2 * c + 1]) != 1 for c in range(Cn)): continue
            x = [int(t) for t in x]
            for cs in groups:
                low = min(x[2 * c] + j * x[2 * c + 1] for c in cs for j in range(len(chains[c])))
                for c in cs: x[2 * c] -= low
            layer = {}; ok = True
            for vs in members.values():
                ls = {x[2 * pos[v][0]] + pos[v][1] * x[2 * pos[v][0] + 1] for v in vs if v in pos}
                if len(ls) > 1: ok = False; break
                lev = next(iter(ls)) if ls else 0
                for v in vs: layer[v] = lev
            if not ok: continue
            hi = {r: max(layer[v] for v in vs) for r, vs in wg.items()}; fold = set()
            for r, ris in resid_by_comp.items():
                ls = {layer[v] for i in ris for v in tabs[i][0]}
                if max(ls) - min(ls) > 1: ok = False; break
                if len(ls) == 1 and min(ls) not in (0, hi[r]) and hi[r] > 0: pass                 # a residual inside one layer is simply local to it
                elif min(ls) >= max(0, hi[r] - 1): fold.add(r)
                elif max(ls) <= 1:
                    for v in wg[r]: layer[v] = hi[r] - layer[v]                                   # reflect a low-end anchor to the terminal end
                    fold.add(r)
                else: ok = False; break
            if not ok: continue
            stage = {v: (min(l, max(0, hi[comp_of[v]] - 1)) if comp_of[v] in fold else l) for v, l in layer.items()}
            interfaces = defaultdict(set); matches = defaultdict(list); locals_ = defaultdict(list)
            for i, (act, data) in enumerate(tabs):
                if i in const or not act: continue
                r = comp_of[act[0]]; ls = {stage[v] for v in act}
                if len(ls) == 1: locals_[r, next(iter(ls))].append(act); continue
                if i not in chan or len(act) != 2 or max(ls) - min(ls) != 1: ok = False; break
                a, b = sorted(act, key=lambda v: stage[v]); matches[r, stage[a]].append((a, b)); interfaces[r, stage[a]].add(a); interfaces[r, stage[b]].add(b)
            if not ok: continue
            if any(len({a for a, b in ee}) != len(ee) or len({b for a, b in ee}) != len(ee) for ee in matches.values()): continue
            width = max(map(len, interfaces.values()), default=0); maxprod = 1; work = 0
            for key, scopes in locals_.items():
                live = [set(sc) for sc in scopes]; keep = interfaces[key]; elim = set().union(*live) - keep
                while elim:
                    pick = None
                    for v in elim:
                        un = set().union(*(s_ for s_ in live if v in s_)); vol = math.prod(cards[w] for w in un); kk = (vol, vol // cards[v], len(un), v)
                        if pick is None or kk < pick[0]: pick = (kk, v, un)
                    kk, v, un = pick; maxprod = max(maxprod, kk[0]); work += kk[0]; live = [s_ for s_ in live if v not in s_]; live.append(un - {v}); elim.remove(v)
                poll('inside the local cost estimate (%s)' % label)
            info = dict(proposal=label, free_signs=signs, max_interface_bits=width, max_local_product_entries=maxprod, local_elimination_volume_sum=work, folded_components=len(fold)); candidates.append(info)
            key = (width, maxprod, work, signs)
            if best is None or key < best[0]: best = (key, layer, stage, interfaces, locals_, matches, info)
        diag = dict(proposal=label, excluded_factors=len(excluded), local_equalities=len(eq), sign_rank=srank, sign_nullity=len(sign_basis), offset_groups=ngroups, free_main_sign_bits=len(free), sign_assignments_examined=examined, admissible_candidates=len(candidates))
        if best is None: raise NotApplicable('bounded alignment found no admissible plan (%s: %d sign assignments examined)' % (label, examined))
        return best + (diag,)

    # ---- two proposals: (A) every non-channel factor forms local cores (no residual class); (B) the non-Boolean multivariable factors are residuals confined to a folded terminal pair
    results = []; refusals = []
    for excluded, label in (((), 'all_local'), (frozenset(resid), 'residual_terminal')):
        if label == 'residual_terminal' and not resid: break
        try: results.append(align(set(excluded), label))
        except NotApplicable as e: refusals.append(str(e)[:160])
    if not results: raise NotApplicable('; '.join(refusals) if refusals else 'no proposal')
    best = min(results, key=lambda t: t[0])
    _, layer, stage, interfaces, locals_, matches, info, diag = best
    # ---- the elimination order: per component (largest first), per stage, greedy local elimination of the non-interface variables; then the interface variables by (stage, id)
    comps = sorted(wg.values(), key=lambda vs: (-len(vs), min(vs))); order = []
    for vs in comps:
        r = comp_of[vs[0]]; done = []
        for (rr, lev), scopes in sorted(locals_.items(), key=lambda kv: kv[0][1]):
            if rr != r: continue
            live = [set(sc) for sc in scopes]; todo = set().union(*live) - interfaces[rr, lev]
            while todo:
                pick = None
                for v in todo:
                    un = set().union(*(s for s in live if v in s)); vol = math.prod(cards[w] for w in un); kk = (vol, vol // cards[v], len(un), v)
                    if pick is None or kk < pick[0]: pick = (kk, v, un)
                kk, v, un = pick; done.append(v); todo.remove(v); live = [s for s in live if v not in s] + [un - {v}]
            poll('inside the order construction')
        ds = set(done); order += done + sorted((v for v in vs if v not in ds), key=lambda v: (stage[v], v))
    singletons = [v for v in range(n) if v not in ev and cards[v] == 1]; factorless = [v for v in range(n) if v not in ev and cards[v] > 1 and v not in touched]
    full_order = singletons + factorless + order
    if sorted(full_order) != [v for v in range(n) if v not in ev] or len(set(order)) != len(order): raise NotApplicable('order does not cover the unobserved variables exactly (constructor defect, refused)')
    # ---- volume certificate of THAT order on the exact primal graph (independent of how the order was found)
    adj = {v: set() for v in activevars}
    for i, (act, _) in enumerate(tabs):
        if i in const: continue
        for v in act: adj[v] |= set(act) - {v}
    maxp = 0; maxo = 0; sump = 0; sumo = 0
    for k, v in enumerate(order):
        if (k & 63) == 63: poll('inside the volume certificate')
        nb = adj[v]; pv = cards[v] * math.prod(cards[x] for x in nb); maxp = max(maxp, pv); maxo = max(maxo, pv // cards[v]); sump += pv; sumo += pv // cards[v]
        for x in nb: adj[x] = (adj[x] | nb) - {x, v}
        del adj[v]
    P = Plan(); P.order = full_order; P.active = len(order); P.n = n; P.ev = dict(ev); P.cards = list(cards); P.singletons = singletons; P.factorless = factorless; P.cancelled_scalar = scalar; P.cancelled_count = cancelled
    P.structure = dict(channels=len(chan), residuals=len(resid), constants=len(const), local_factors=len(local), chains=Cn, chain_lengths=dict(Counter(len(c) for c in chains)), components=len(wg), main_component_variables=len(wg[main]), stages_main=len({stage[v] for v in wg[main]}), proposals=[r[-1] for r in results], proposal_refusals=refusals, selected=info)
    P.volume = dict(max_product_entries=maxp, max_output_entries=maxo, sum_product_entries=sump, sum_output_entries=sumo, source_entries=sum(len(d) for _, d in facs), active_variables=len(order))
    P.recognition_s = tnow() - t0; P.binding = binding
    return P


ROWS_PER_S_CONSERVATIVE = 20e6     # kernel rows per second assumed for the TIME admission: calibrated BEFORE the freeze from the round-20 probe receipt (33.1 M rows/s on this host, r20_probe_native_executor_order) with a 40 % margin; the kernel's deadline poll is the hard bound
MEMORY_SLACK = 1.25


def forecast(plan, remaining_s):
    """conservative forecast of the native executor's live state and work for THIS order: every message is retained until the reverse releases it at its consumer (one double per
    output entry; the probe measured 1.004 x), plus the converted sources, the reverse contexts of the live frontier (<= 2 x the largest output), the kernel's join / index rows
    (<= 2 x the largest product), the enclosure's Fraction rows; x MEMORY_SLACK + 64 MiB process headroom. Work: forward + reverse rows = 2 x the summed product volume."""
    v = plan.volume; payload = 8 * (v['sum_output_entries'] + v['source_entries'] + 2 * v['max_output_entries'] + 2 * v['max_product_entries'])
    byts = int(payload * MEMORY_SLACK) + (64 << 20) + 1200 * sum(plan.cards)
    rows = 2 * v['sum_product_entries']; secs = rows / ROWS_PER_S_CONSERVATIVE
    return dict(forecast_bytes=byts, forecast_rows=rows, forecast_kernel_s=secs, remaining_s=remaining_s)


class Result:
    __slots__ = ('intervals', 'points', 'Z_lo', 'Z_hi', 'Z_point', 'Z_label', 'stats', 'certificate')


def execute(plan, model, deadline, cap_bytes, host_reserved_bytes):
    """the validated order through the EXISTING certified executor's primitives (build / load / lower / kernel / enclose: identical calls to cex_executor.execute; cex_executor.py is
    unchanged), additionally reading the kernel's normalizer triple (value, binary exponent, label) to form the exact Z ENCLOSURE x the scalars lower() cancels"""
    t0 = tnow(); stats = {'phase': 'build'}
    def guard(where):
        if tnow() >= deadline: raise ExecutorRefused('DEADLINE', 'deadline expired %s' % where, stats)
    guard('at the adapter entry')
    try:
        prov = CX.build(deadline); lib = CX.load(prov); stats['build_s'] = tnow() - t0; stats['phase'] = 'lowering'; t = tnow(); rss0 = CX.rss_bytes()
        hb = cap_bytes - host_reserved_bytes
        if hb <= 0: raise ExecutorRefused('MEMORY', 'host RSS at entry (%d) leaves no capacity under cap %d' % (host_reserved_bytes, cap_bytes), stats)
        B = CX.HostBudget(hb, stats)
        words, vals, meta = CX.lower(model, plan.order, 0.25, deadline, budget=B)
        stats['lowering_s'] = tnow() - t; stats['host_lowering_rss_growth_bytes_measured'] = max(0, CX.rss_bytes() - rss0)
        stats.update({k: v for k, v in meta.items() if k not in ('active', 'evidence', 'cards', 'plan_lists_charge', 'source_scale_shifts_list')}); B.report()
        if meta.get('zero_evidence'): raise ZeroEvidence('a restricted source factor is identically zero')
        if meta['scalar_factors_cancelled'] != plan.cancelled_count: raise ExecutorRefused('BADPLAN', 'cancelled scalar count %d != recognised %d' % (meta['scalar_factors_cancelled'], plan.cancelled_count), stats)
        n = meta['n']; cards = meta['cards']; ev = meta['evidence']; tot = sum(cards)
        arrays_bytes = len(words) * 8 + max(1, len(vals)) * 8 + tot * 8 + n * 16 + 8 + 16 + len(CX.COUNTERS) * 8 + 256; B.charge(arrays_bytes, 'ctypes plan / output arrays'); kcap = hb - B.live
        if kcap <= 0: raise ExecutorRefused('MEMORY', 'host-side charges leave no kernel capacity', stats)
        stats['kernel_cap_bytes'] = kcap; stats['phase'] = 'kernel'; t = tnow(); guard('after lowering')
        W = (C.c_int64 * len(words))(*words); V = (C.c_double * max(1, len(vals)))(*vals)
        N = (C.c_double * tot)(); NE = (C.c_int64 * n)(); NL = (C.c_int64 * n)(); Z = (C.c_double * 1)(); ZM = (C.c_int64 * 2)(); CT = (C.c_uint64 * len(CX.COUNTERS))(); RS = C.create_string_buffer(256)
        with CX._KERNEL_LOCK:
            rc = lib.cex_run(W, len(words), V, len(vals), kcap, float(deadline), 0.25, N, NE, NL, Z, ZM, CT, len(CX.COUNTERS), RS, 256)
        stats['kernel_s'] = tnow() - t; stats['counters'] = {k: int(CT[i]) for i, k in enumerate(CX.COUNTERS)}; stats['kernel_status'] = CX.STOPS.get(rc, 'UNKNOWN_%d' % rc); stats['kernel_reason'] = RS.value.decode(errors='replace')
        if rc == 7: raise ZeroEvidence(stats['kernel_reason'] or 'kernel zero evidence')
        if rc != 0: raise ExecutorRefused(CX.STOPS.get(rc, 'FAULT'), stats['kernel_reason'], stats)
        B.release(len(words) * 8 + max(1, len(vals)) * 8); B.release(meta['plan_lists_charge']); del W, V, words, vals
        stats['phase'] = 'enclosure'; t = tnow(); guard('before the enclosure')
        intervals, points, maxK, maxw = CX.enclose([N[i] for i in range(tot)], [int(x) for x in NE], [int(x) for x in NL], Z[0], int(ZM[0]), int(ZM[1]), cards, ev, stats, deadline, budget=B)
        stats['enclosure_s'] = tnow() - t; stats['max_label_K'] = maxK; stats['max_width_float'] = float(maxw); B.report()
        if maxw > F(1, 100): raise ExecutorRefused('WIDTH', 'delivered width %s exceeds 1/100' % float(maxw), stats)
        zl = int(ZM[1]); delta = zl * U
        if delta >= F(1, 2): raise ExecutorRefused('RANGE', 'normalizer label too large for an enclosure (K=%d)' % zl, stats)
        zhat = F(Z[0]) * F(2) ** int(ZM[0]) * plan.cancelled_scalar / math.prod(cards[v] for v in ev)    # the kernel places each OBSERVED variable in an empty bucket whose output is card[v] (exact, label 0): it cancels in every N / Z ratio and is divided out of Z here
        if zhat <= 0: raise ExecutorRefused('RANGE', 'nonpositive normalizer', stats)
        R = Result(); R.intervals = intervals; R.points = points; R.Z_point = zhat; R.Z_lo = zhat * (1 - delta); R.Z_hi = zhat / (1 - delta); R.Z_label = zl; R.stats = stats
        R.certificate = dict(method='planned_exact_adapter: structural layered order -> compiled_nonnegative_bucket_contraction_all_singleton_reverse (cex_executor primitives, unchanged)', arithmetic='binary64 nearest with reciprocal-envelope labels (u=2^-53); exact N/Z in Python; Bernoulli widening by K=E_N+E_Z; Z enclosure [Zhat(1-Ku), Zhat/(1-Ku)] x cancelled scalars',
                             semantic_plan_sha256=meta['semantic_plan_sha256'], physical_schedule_sha256=meta['physical_schedule_sha256'], kernel={k: prov.get(k) for k in ('source_sha256', 'binary_sha256', 'compiler', 'compiler_version', 'flags', 'schedule_id', 'plan_format')}, max_label_K=maxK, Z_label=zl)
        stats['total_s'] = tnow() - t0; stats['phase'] = 'complete'; guard('before the adapter return')
        return R
    except CX.Stop as e:
        raise ExecutorRefused(e.kind, str(e.reason)[:300], {k: v for k, v in (e.stats or {}).items() if k != 'counters'})
