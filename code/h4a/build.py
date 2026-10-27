"""Build and certify one node's FFBS tables, phases, weights and positive marker masses (producer direction and
checker's opposite direction). Emits the exact witness records consumed by the native kernels.

Producer (backward factorization, NUMERICAL_THEOREM.md §1):
  F_1(a,b) = v0(a) v1(b) psi01(a,b);  F_i(a,b) = v_i(b) psi_{i-1,i}(a,b) sum_c F_{i-1}(c,a) psi_{i-2,i}(c,b)
  r(a,b) = F_{n-1}(a,b)/Z ;  p_i(c|a,b) = F_{i+1}(c,a) psi_{i,i+2}(c,b) / sum_d (...)
Checker (forward factorization, same file):
  B_{n-1}=1 ; B_i(a,b) = sum_c v_{i+1}(c) psi_{i,i+1}(b,c) psi_{i-1,i+1}(a,c) B_{i+1}(b,c)
  t_i(c|a,b) = v_i(c) psi_{i-1,i}(b,c) psi_{i-2,i}(a,c) B_i(b,c) / B_{i-1}(a,b)   [numerator weights normalized by their own sum]
  s(a,b) = v0(a) v1(b) psi01(a,b) B_1(a,b) / Z
All prefix/suffix layers use a common exact power-of-two scale; no interval division by a dependent sum during propagation."""
from __future__ import annotations
import sys
sys.set_int_max_str_digits(0)
from fractions import Fraction as Fr
import gmpy2
from h4a.tables import MP, fr, store_row, store_phase, exact_phase_one, MESH, EPS_P, EPS_PHI, EPS_LAM
from h4a.grid import PI_LO, PI_HI, Grid

S2 = (-1, 1)                      # declared binary state order: - then +
P4 = ((-1, -1), (-1, 1), (1, -1), (1, 1))     # declared pair order (--),(-+),(+-),(++)

def _unary_iv(M: MP, prob, i: int, x: int, sqrt_cache):
    """exact-rational field part + irrational sqrt(beta/n) j u part, enclosed outward; v_i(x) = exp(x * a_i)"""
    arg = M.q(prob.field[i] * x)
    for (beta, j, u) in prob.node_coef[i]:
        if j == 0: continue
        sb = sqrt_cache[beta]                                  # enclosure of sqrt(beta/n)
        t = M.mul(sb, M.q(Fr(j) * u * x))
        arg = M.add(arg, t)
    return M.exp(arg)

def sqrt_cache_for(M: MP, n: int, betas):
    return {b: M.sqrt(M.q(Fr(b) / n)) for b in betas}

def _scale_layer(M: MP, arr):
    """common exact power-of-two scale bringing the largest upper endpoint into [1/2,1); returns (scaled, exponent)"""
    hi = None
    for v in arr.values():
        if v is None: continue
        if hi is None or v[1] > hi: hi = v[1]
    assert hi is not None and hi > 0
    e = -int(gmpy2.get_exp(hi))                                # upper endpoint into [1/2,1)
    return {k: (None if v is None else M.scale2(v, e)) for k, v in arr.items()}, e

def producer_tables(prob, prec=256):
    """returns dict with rows (ints/2^53 + exact L1 bounds), terminal row, and the exact scaled prefix layers for masses"""
    M = MP(prec); m = prob.m; n = m.n
    sc = sqrt_cache_for(M, n, [b for b, _ in prob.POS_LOCAL and [(bb, 0) for bb, _ in []]] or [b for _, b in prob.POS_LOCAL])
    sc = sqrt_cache_for(M, n, [beta for (_, beta) in prob.POS_LOCAL])
    v = [{x: _unary_iv(M, prob, i, x, sc) for x in prob.allowed[i]} for i in range(n)]
    # ---- prefix layers F_i over allowed (a,b) = (x_{i-1}, x_i)
    F = []; exps = []
    cur = {}
    for a in prob.allowed[0]:
        for b in prob.allowed[1]:
            cur[(a, b)] = M.mul_pos(M.mul_pos(v[0][a], v[1][b]), M.q(m.psi(0, 1, a, b)))
    cur, e = _scale_layer(M, cur); F.append(cur); exps.append(e)
    for i in range(2, n):
        nxt = {}
        for a in prob.allowed[i - 1]:
            for b in prob.allowed[i]:
                acc = None
                for c in prob.allowed[i - 2]:
                    t = F[-1].get((c, a))
                    if t is None: continue
                    t = M.mul_pos(t, M.q(m.psi(i - 2, i, c, b)))
                    acc = t if acc is None else M.add(acc, t)
                if acc is None: nxt[(a, b)] = None; continue
                nxt[(a, b)] = M.mul_pos(M.mul_pos(v[i][b], M.q(m.psi(i - 1, i, a, b))), acc)
        nxt, e = _scale_layer(M, nxt); F.append(nxt); exps.append(e)
    # ---- terminal row r(a,b) = F_{n-1}(a,b)/Z  (four states max, exact division of the scaled layer)
    last = F[-1]
    tot = None
    for k in P4:
        t = last.get(k)
        if t is not None: tot = t if tot is None else M.add(tot, t)
    term_enc = []; term_idx = []
    for idx, k in enumerate(P4):
        t = last.get(k)
        if t is None: continue
        q = M.div_pos(t, tot); term_enc.append((fr(q[0]), fr(q[1]))); term_idx.append(idx)
    term_ints, term_l1 = store_row(term_enc, term_idx, 4)
    # ---- interior rows p_i(c|a,b), i = 0..n-3 ; context (a,b) = (x_{i+1}, x_{i+2})
    rows = []
    for i in range(n - 3 + 1):
        per_ctx = {}
        for a in prob.allowed[i + 1]:
            for b in prob.allowed[i + 2]:
                encs = []; idxs = []
                wts = []
                for c in prob.allowed[i]:
                    Fv = F[i + 1 - 1].get((c, a)) if i + 1 >= 1 else None
                    Fv = F[i].get((c, a))                     # F_{i+1} layer index: F[j] holds F_{j+1}
                    if Fv is None: continue
                    w = M.mul_pos(Fv, M.q(m.psi(i, i + 2, c, b)))
                    wts.append((c, w))
                if not wts: continue
                s = None
                for _, w in wts: s = w if s is None else M.add(s, w)
                for c, w in wts:
                    q = M.div_pos(w, s); encs.append((fr(q[0]), fr(q[1]))); idxs.append(0 if c < 0 else 1)
                ints, l1 = store_row(encs, idxs, 2)
                per_ctx[(a, b)] = (ints, l1)
        rows.append(per_ctx)
    return {"M": M, "v": v, "F": F, "exps": exps, "rows": rows, "terminal": (term_ints, term_l1), "prec": prec}

def checker_tables(prob, prec=320):
    """opposite direction: suffix arrays B_i, forward conditional rows t_i (i=2..n-1), initial-pair law s(a,b)"""
    M = MP(prec); m = prob.m; n = m.n
    sc = sqrt_cache_for(M, n, [beta for (_, beta) in prob.POS_LOCAL])
    v = [{x: _unary_iv(M, prob, i, x, sc) for x in prob.allowed[i]} for i in range(n)]
    B = {}; exps = {}
    cur = {}
    for a in prob.allowed[n - 2]:
        for b in prob.allowed[n - 1]: cur[(a, b)] = M.q(Fr(1))
    B[n - 1] = cur; exps[n - 1] = 0
    for i in range(n - 2, 0, -1):
        nxt = {}
        for a in prob.allowed[i - 1]:
            for b in prob.allowed[i]:
                acc = None
                for c in prob.allowed[i + 1]:
                    t = B[i + 1].get((b, c))
                    if t is None: continue
                    w = M.mul_pos(M.mul_pos(v[i + 1][c], M.q(m.psi(i, i + 1, b, c))), M.q(m.psi(i - 1, i + 1, a, c)))
                    w = M.mul_pos(w, t)
                    acc = w if acc is None else M.add(acc, w)
                nxt[(a, b)] = acc
        nxt, e = _scale_layer(M, nxt); B[i] = nxt; exps[i] = e
    rows = {}
    for i in range(2, n):
        per_ctx = {}
        for a in prob.allowed[i - 2]:
            for b in prob.allowed[i - 1]:
                wts = []
                for c in prob.allowed[i]:
                    Bv = B[i].get((b, c))
                    if Bv is None: continue
                    w = M.mul_pos(M.mul_pos(v[i][c], M.q(m.psi(i - 1, i, b, c))), M.q(m.psi(i - 2, i, a, c)))
                    w = M.mul_pos(w, Bv)
                    wts.append((c, w))
                if not wts: continue
                s = None
                for _, w in wts: s = w if s is None else M.add(s, w)
                encs = []; idxs = []
                for c, w in wts:
                    q = M.div_pos(w, s); encs.append((fr(q[0]), fr(q[1]))); idxs.append(0 if c < 0 else 1)
                ints, l1 = store_row(encs, idxs, 2)
                per_ctx[(a, b)] = (ints, l1)
        rows[i] = per_ctx
    # initial pair law s(a,b) at the common B_1 scale
    wts = {}
    for a in prob.allowed[0]:
        for b in prob.allowed[1]:
            t = B[1].get((a, b))
            if t is None: continue
            wts[(a, b)] = M.mul_pos(M.mul_pos(M.mul_pos(v[0][a], v[1][b]), M.q(m.psi(0, 1, a, b))), t)
    s = None
    for w in wts.values(): s = w if s is None else M.add(s, w)
    encs = []; idxs = []
    for idx, k in enumerate(P4):
        if k not in wts: continue
        q = M.div_pos(wts[k], s); encs.append((fr(q[0]), fr(q[1]))); idxs.append(idx)
    init_ints, init_l1 = store_row(encs, idxs, 4)
    return {"M": M, "v": v, "B": B, "exps": exps, "rows": rows, "initial": (init_ints, init_l1), "prec": prec, "init_weights": wts}
