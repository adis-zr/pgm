"""Unnormalized CELL CONTRIBUTION API (handoff 02, "The implementation-critical new API"): for a partial assignment (cell) C of the ORIGINAL model under its
original evidence, return rigorous enclosures of
    B0(C) = sum_{x in C} W(x)          and     Bj(C) = sum_{x in C} W(x) f_j(x)   for every original singleton indicator f_j,
on ONE common fixed target scale (the original source's product, including every positive scalar factor, cell-dependent constant, fixed-state contribution and
observed variable), with original-state decoding. Nothing is cancelled: the frozen deterministic pipeline's reduction/lowering cancel positive scalars because
they are irrelevant to a NORMALIZED answer; here two cells with identical conditional posteriors and 1000x different masses must come out 1000x apart.

Two evaluators, both exact in their scale bookkeeping:
  * `cell_exact`  : exact rational enumeration of the cell's completions (qualification oracle; also used in production for tiny residual cells).
  * `cell_kernel` : the frozen compiled contraction kernel (cex_kernel v1.4, unchanged binary) on the cell-restricted factor occurrences. The kernel returns
                    N_x = stored * 2^Nexp with label E_N and Z = stored * 2^Zexp with label E_Z in ITS internal gauge, where every source was scaled by the
                    Python side's exact power of two 2^shift_a AND the kernel carries -shift_a in each source's exponent word (plan format 2), so the kernel's
                    Z * 2^Zexp and N * 2^Nexp are already in the restricted model's own scale; the product of the restricted exact scalar factors that
                    `restrict` removed is multiplied back exactly (control: kernel enclosures contain the exact enumeration on random cells with 10^+-3 scales). The reciprocal-envelope label gives the enclosure [Z (1-u)^E, Z (1-u)^-E] (one-sided bounds computed exactly as rationals via
                    Bernoulli: (1-u)^E >= 1 - E u, (1-u)^-E <= 1/(1-E u) for E u < 1).
Both return the same record shape: {'B0': (lo, hi), 'B': {original_var: [(lo, hi) per original state]}, 'scale': 'original source product', 'cell': ...,
'exact': bool, 'route': ..., 'stats': {...}}, with Fractions throughout; cut variables (assigned in the cell) have Bj = B0 on the assigned state and 0 elsewhere;
observed variables (evidence) are treated as assigned by the cell; a cell with no completion of positive weight has B0 = (0, 0) exactly (a proved zero cell).
Rows satisfy sum_states Bj = B0 mathematically; the enclosures are per-coordinate and the identity is checked on the exact evaluator."""
import sys, os, math, time
from fractions import Fraction as F
from itertools import product
HERE = os.path.dirname(os.path.abspath(__file__)); NEWARM = os.path.join(os.path.dirname(HERE), 'newarm')
if NEWARM not in sys.path: sys.path.insert(0, NEWARM)
U_ROUND = F(1, 2 ** 53)


class CellStop(Exception):
    def __init__(self, kind, reason, stats=None):
        super().__init__('%s: %s' % (kind, reason)); self.kind = kind; self.reason = reason; self.stats = dict(stats or {})


def restrict(model, cell):
    """exact restriction of every factor occurrence to the assignments fixed by `cell` (a dict var -> state; evidence is merged in). Returns the reduced
    model over the FREE variables (renumbered), the list of removed exact positive scalars (factors whose whole scope is fixed), the free-variable map and the
    merged assignment. Zero-weight fixed factors make the cell a proved zero cell (returns None model)."""
    cards = model['cards']; n = len(cards); fixed = dict(model.get('evidence', {})); fixed.update(cell)
    for v, a in fixed.items():
        if not (0 <= v < n and 0 <= a < cards[v]): raise ValueError('cell assigns an invalid state')
    free = [v for v in range(n) if v not in fixed]; idx = {v: i for i, v in enumerate(free)}
    out = []; scalars = []; zero = False; entries = 0
    for f in model['factors']:
        sc = tuple(f['scope']); vals = f['values']; keep = [i for i, v in enumerate(sc) if v not in fixed]; newsc = tuple(idx[sc[i]] for i in keep)
        data = []
        for a, w in zip(product(*(range(cards[v]) for v in sc)), vals):
            entries += 1
            if all(a[i] == fixed[v] for i, v in enumerate(sc) if v in fixed):
                data.append(w if isinstance(w, F) else F(w))
        if not newsc:
            if data[0] == 0: zero = True
            else: scalars.append(data[0])
        else: out.append(dict(scope=newsc, values=data))
    red = None if zero else dict(cards=[cards[v] for v in free], factors=out, evidence={})
    return red, scalars, free, fixed, entries


def cell_exact(model, cell, deadline=None, max_completions=1 << 22):
    """exact rational enumeration of the cell (qualification oracle; production for tiny cells). Deadline-checked; refuses cells with more completions than
    `max_completions` (typed stop, never an approximation)."""
    t0 = time.monotonic(); cards = model['cards']; n = len(cards)
    red, scalars, free, fixed, entries = restrict(model, cell); scale = math.prod(scalars, start=F(1))
    B = {v: [F(0)] * cards[v] for v in range(n)}
    if red is None:
        return dict(B0=(F(0), F(0)), B={v: [(F(0), F(0))] * cards[v] for v in range(n)}, scale='original source product', cell=dict(fixed), exact=True, route='exact_zero_cell', stats=dict(entries=entries, completions=0, wall_s=time.monotonic() - t0))
    m = math.prod(red['cards'], start=1)
    if m > max_completions: raise CellStop('CELL_TOO_LARGE', 'exact enumeration refused: %d completions' % m)
    B0 = F(0); k = 0
    for x in product(*(range(c) for c in red['cards'])):
        k += 1
        if deadline is not None and k % 4096 == 0 and time.monotonic() >= deadline: raise CellStop('DEADLINE', 'exact cell enumeration deadline')
        w = scale
        for f in red['factors']:
            i = 0
            for v in f['scope']: i = i * red['cards'][v] + x[v]
            w *= f['values'][i]
            if w == 0: break
        if w == 0: continue
        B0 += w
        for i, v in enumerate(free): B[v][x[i]] += w
    for v, a in fixed.items(): B[v][a] = B0
    for v in range(n): assert sum(B[v]) == B0, 'row conservation'
    return dict(B0=(B0, B0), B={v: [(x, x) for x in B[v]] for v in range(n)}, scale='original source product', cell=dict(fixed), exact=True, route='exact_enumeration', stats=dict(entries=entries, completions=m, wall_s=time.monotonic() - t0))


def envelope(x, E):
    """exact rational enclosure of the true value from a stored double x (as Fraction) with reciprocal-envelope label E: a^E x <= true <= a^-E x, a = 1 - u.
    Bernoulli: a^E >= 1 - E u; a^-E <= 1/(1 - E u) when E u < 1 (else refuse)."""
    d = E * U_ROUND
    if d >= 1: raise CellStop('RANGE', 'label too large for an enclosure (E=%d)' % E)
    if x == 0: return (F(0), F(0))
    return (x * (1 - d), x / (1 - d))


def cell_kernel(model, cell, deadline=None, cap_bytes=3 * 1024 ** 3, host_reserved_bytes=0, order=None, dense_fill_threshold=0.25):
    """the frozen compiled kernel on the restricted model; the gauge is undone exactly (sum of lowering shifts) and the removed exact scalars are multiplied
    back; per-coordinate enclosures from the labels. Returns the common record. Typed stops propagate as CellStop (kind preserved)."""
    import cex_executor as X, planning
    t0 = time.monotonic(); cards = model['cards']; n = len(cards)
    red, scalars, free, fixed, entries = restrict(model, cell); scale = math.prod(scalars, start=F(1))
    if red is None:
        return dict(B0=(F(0), F(0)), B={v: [(F(0), F(0))] * cards[v] for v in range(n)}, scale='original source product', cell=dict(fixed), exact=True, route='exact_zero_cell', stats=dict(entries=entries, wall_s=time.monotonic() - t0))
    if not free:                                                     # fully assigned cell: exact product
        return cell_exact(model, cell, deadline)
    if not red['factors']:                                           # free variables without any factor: uniform, exact
        return cell_exact(model, cell, deadline) if math.prod(red['cards']) <= (1 << 22) else _uniform_cell(model, red, scale, free, fixed, entries, t0)
    if order is None:
        order, _ = planning.order_and_price(red, deadline=deadline)
    prov = X.build(deadline); lib = X.load(prov); import ctypes as C
    B = X.HostBudget(max(1, cap_bytes - host_reserved_bytes), {})
    words, vals, meta = X.lower(red, order, dense_fill_threshold, deadline, budget=B)
    if meta.get('zero_evidence'):
        return dict(B0=(F(0), F(0)), B={v: [(F(0), F(0))] * cards[v] for v in range(n)}, scale='original source product', cell=dict(fixed), exact=True, route='kernel_lowering_zero', stats=dict(entries=entries, wall_s=time.monotonic() - t0))
    shifts = meta['source_scale_shifts_list'] if 'source_scale_shifts_list' in meta else None
    if shifts is None: raise CellStop('BADPLAN', 'lowering did not expose the per-source shifts (cex_executor must be the PAC-aware v1.5+)')
    tot = sum(red['cards']); nn = meta['n']
    W = (C.c_int64 * len(words))(*words); V = (C.c_double * max(1, len(vals)))(*vals); N = (C.c_double * tot)(); NE = (C.c_int64 * nn)(); NL = (C.c_int64 * nn)(); Z = (C.c_double * 1)(); ZM = (C.c_int64 * 2)(); CT = (C.c_uint64 * len(X.COUNTERS))(); RS = C.create_string_buffer(256)
    kcap = max(1, cap_bytes - host_reserved_bytes - B.live)
    with X._KERNEL_LOCK:
        rc = lib.cex_run(W, len(words), V, len(vals), kcap, float('inf') if deadline is None else deadline, dense_fill_threshold, N, NE, NL, Z, ZM, CT, len(X.COUNTERS), RS, 256)
    counters = {k: int(CT[i]) for i, k in enumerate(X.COUNTERS)}
    if rc == 7:
        return dict(B0=(F(0), F(0)), B={v: [(F(0), F(0))] * cards[v] for v in range(n)}, scale='original source product', cell=dict(fixed), exact=True, route='kernel_zero_mass', stats=dict(entries=entries, counters=counters, wall_s=time.monotonic() - t0))
    if rc != 0: raise CellStop(X.STOPS.get(rc, 'FAULT'), RS.value.decode(errors='replace'), dict(counters=counters))
    gauge = scale                                                     # the kernel carries every source's exact power-of-two scale in its exponent words (plan format 2: exp2 = -shift; true = stored * 2^exp2), so Z 2^Zexp and N 2^Nexp are ALREADY in the restricted model's scale; only the removed exact scalars are multiplied back. The shift list is recorded (stats) and checked by control, not applied.
    zv = F(Z[0]) * F(2) ** int(ZM[0]) * gauge; zlab = int(ZM[1]); B0 = envelope(zv, zlab)
    out = {v: None for v in range(n)}; off = 0
    for i in range(nn):
        c = red['cards'][i]; row = []
        for a in range(c):
            nv = F(N[off + a]) * F(2) ** int(NE[i]) * gauge; row.append(envelope(nv, int(NL[i])))
        out[free[i]] = row; off += c
    for v, a in fixed.items(): out[v] = [B0 if s == a else (F(0), F(0)) for s in range(cards[v])]
    return dict(B0=B0, B=out, scale='original source product', cell=dict(fixed), exact=False, route='compiled_kernel', stats=dict(entries=entries, counters=counters, lowering=meta.get('semantic_plan_sha256'), K_Z=zlab, max_label=max(int(x) for x in NL) if nn else 0, source_shifts_sum=sum(shifts), wall_s=time.monotonic() - t0, host_budget_peak=B.peak))


def _uniform_cell(model, red, scale, free, fixed, entries, t0):
    m = math.prod(red['cards']); B0 = scale * m; cards = model['cards']; out = {}
    for i, v in enumerate(free): out[v] = [(B0 / red['cards'][i], B0 / red['cards'][i])] * red['cards'][i]
    for v, a in fixed.items(): out[v] = [(B0, B0) if s == a else (F(0), F(0)) for s in range(cards[v])]
    return dict(B0=(B0, B0), B=out, scale='original source product', cell=dict(fixed), exact=True, route='uniform_free_block', stats=dict(entries=entries, wall_s=time.monotonic() - t0))
