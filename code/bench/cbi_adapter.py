"""Native-CBI adapter for binary unary/pairwise table models (campaign spec section 4 / section 11), with an INDEPENDENT checker.

What it does (all exact, all charged inside the CBI cell):
  1. applies the evidence by slicing every factor at the observed states (exact rationals);
  2. propagates FIXED variables: a variable whose combined unary has exactly one positive state is fixed (equivalent to evidence) and sliced
     out; two zero states => Z = 0 (INFEASIBLE with the witness factor list);
  3. combines factors with identical remaining scopes entrywise; absorbs unaries;
  4. pairwise factors F = [[a,b],[c,d]] on binary (u, v):
        * all four positive: cross-ratio C = ad/(bc). C == 1: separable (rank one), absorbed as unaries. Otherwise C must be a rational
          square after a GLOBALLY consistent choice of bit flips (attractive edges C >= 1 need equal flip parity, repulsive opposite; a
          frustrated cycle => unsupported). With t = sqrt(C) >= 1: r = (t-1)/(t+1), g_0 = 1, g_1 = c t / a, h_0 = a/(1+r), h_1 = b/(1-r),
          F_xy = g_x h_y K_r(x, y) with K_r the d = 1 native kernel [[1+r, 1-r], [1-r, 1+r]] (states in flipped order);
        * only the diagonal positive (b = c = 0): exact equality r = 1 with weights (a, d) absorbed as a unary on u;
        * any other zero pattern: unsupported ("incompatible zero pattern");
  5. emits the native model: one block per free variable, d = 1, rows subset of {0, 1} (row 1 <-> x = +1 <-> flipped state 1), positive
     integer weights (the rational unaries scaled by one common denominator per block: a positive scalar), edges with rational r in [0, 1].
Nonbinary free variables, factors of arity >= 3 after slicing, non-decimal / non-rational numbers and an adapter work cap are rejected
with precise reasons ("the current adapter does not support ..."). Original variable ids are the EXTERNAL block ids (negative-free here,
but the library's id map is used regardless). Query mapping: P(v = s) for the ORIGINAL state s of an unobserved variable v is the CBI
coordinate event x = +1 when (s XOR flip_v) == 1, else its complement: publish [1 - u, 1 - l].

The CERTIFICATE the adapter emits (`identities`) lists, per original factor occurrence, how it was consumed; `check_adapter` re-derives
every claim from the RAW model + evidence files with its own code (no shared helpers beyond the UAI reader): factor identities entrywise over
all allowed assignments, the flip bijection, the block weights as products of the declared unary contributions, the query map."""
from __future__ import annotations
from fractions import Fraction as Fr
import math, json, sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from ext import uai as U

WORK_CAP_ENTRIES = 5_000_000          # adapter work limit (table entries touched); refused beyond with reason "adapter work limit"


class Unsupported(Exception):
    pass


def _isqrt_exact(n):
    r = math.isqrt(n); return r if r * r == n else None


def _sqrt_rational(q: Fr):
    a = _isqrt_exact(q.numerator); b = _isqrt_exact(q.denominator)
    return None if a is None or b is None else Fr(a, b)


def adapt(model: U.Model, ev: dict):
    """Returns (native_json, cert) or raises Unsupported / returns ('INFEASIBLE', witness)."""
    n = model.nvars; work = 0
    for f in model.factors:
        work += f.size()
    if work > WORK_CAP_ENTRIES:
        raise Unsupported("adapter work limit: %d table entries > %d" % (work, WORK_CAP_ENTRIES))
    # ---- 1. slice evidence; 2. fixed-variable propagation (iterated)
    fixed = dict(ev)                                   # var -> state
    unary = {v: None for v in range(n)}                # v -> [Fr]*card (combined unary potential), None = no unary yet
    pair = []                                          # (u, v, table[2][2] as Fr) remaining pairwise factors (after slicing)
    higher = []                                        # remaining arity >= 3 after slicing
    consumed = []                                      # identities: how each original factor occurrence was handled
    def slice_factor(f, fx):
        sc = [v for v in f.scope if v not in fx]
        if not sc:
            return (), [f.at({v: fx[v] for v in f.scope})]
        tab = []
        import itertools
        for conf in itertools.product(*[range(model.card[v]) for v in sc]):
            a = dict(zip(sc, conf)); a.update({v: fx[v] for v in f.scope if v in fx}); tab.append(f.at(a))
        return tuple(sc), tab
    pending = list(model.factors); const_scalars = []
    changed = True; rounds = 0
    while changed:
        changed = False; rounds += 1
        nxt = []
        for f in pending:
            sc, tab = slice_factor(f, fixed)
            if len(sc) == 0:
                if tab[0] == 0:
                    return "INFEASIBLE", {"reason": "factor %d is zero at the fixed / observed assignment" % f.index, "factor": f.index, "fixed": {str(k): v for k, v in fixed.items()}}
                const_scalars.append(str(tab[0])); consumed.append({"factor": f.index, "role": "constant", "value": str(tab[0]), "fixed_at": {str(v): fixed[v] for v in f.scope}}); continue
            if len(sc) == 1:
                v = sc[0]
                if model.card[v] != 2:
                    raise Unsupported("nonbinary domains: variable %d has %d states (the current adapter supports binary variables only)" % (v, model.card[v]))
                unary[v] = tab if unary[v] is None else [x * y for x, y in zip(unary[v], tab)]
                consumed.append({"factor": f.index, "role": "unary", "var": v, "table": [str(x) for x in tab], "fixed_at": {str(w): fixed[w] for w in f.scope if w in fixed}})
                pos = [s for s in range(2) if unary[v][s] > 0]
                if not pos:
                    return "INFEASIBLE", {"reason": "variable %d has no positive unary state after slicing" % v, "var": v}
                if len(pos) == 1 and v not in fixed:
                    fixed[v] = pos[0]; changed = True; consumed.append({"role": "fixed_by_unary", "var": v, "state": pos[0]})
                continue
            nxt.append(f)
        pending = nxt
        if changed:
            # unaries of newly fixed variables become constants; restart slicing of everything still pending with the new fixed set
            for v in list(unary):
                if v in fixed and unary[v] is not None:
                    const_scalars.append(str(unary[v][fixed[v]])); unary[v] = None
    for f in pending:
        sc, tab = slice_factor(f, fixed)
        if len(sc) >= 3:
            raise Unsupported("remaining high arity: factor %d keeps %d free variables after slicing (the current adapter supports arity <= 2)" % (f.index, len(sc)))
        u, v = sc
        if model.card[u] != 2 or model.card[v] != 2:
            raise Unsupported("nonbinary domains: factor %d couples variables with %d x %d states" % (f.index, model.card[u], model.card[v]))
        pair.append((u, v, tab, f.index))
    free = [v for v in range(n) if v not in fixed]
    for v in free:
        if model.card[v] != 2:
            raise Unsupported("nonbinary domains: free variable %d has %d states" % (v, model.card[v]))
    # ---- 3. combine identical scopes
    byscope = {}
    for u, v, tab, fi in pair:
        key = (min(u, v), max(u, v))
        if u > v:
            tab = [tab[0], tab[2], tab[1], tab[3]]                        # transpose to (min, max) order
        byscope.setdefault(key, []).append((tab, fi))
    merged = {}
    for key, lst in byscope.items():
        t = [Fr(1)] * 4
        for tab, fi in lst:
            t = [x * y for x, y in zip(t, tab)]
        merged[key] = (t, [fi for _, fi in lst])
    # ---- 4. classify pairs: separable / equality / coupling with cross ratio; parity constraints for flips
    parent = {v: v for v in free}; par = {v: 0 for v in free}          # union-find with parity (flip difference)
    def find(x):
        p = 0
        while parent[x] != x:
            p ^= par[x]; x = parent[x]
        return x, p
    def union(a, b, want):                                              # want = flip_a XOR flip_b
        ra, pa = find(a); rb, pb = find(b)
        if ra == rb:
            return (pa ^ pb) == want
        parent[ra] = rb; par[ra] = pa ^ pb ^ want; return True
    kinds = {}
    for (u, v), (t, fis) in merged.items():
        a, b, c, d = t
        if all(x > 0 for x in t):
            C = (a * d) / (b * c)
            if C == 1:
                kinds[(u, v)] = ("separable", t, fis); continue
            if _sqrt_rational(C if C >= 1 else 1 / C) is None:
                raise Unsupported("nonsquare rational cross-ratio: factor(s) %s on (%d,%d) have ad/(bc) = %s whose square root is irrational (no exact unary-gauge representation by the native kernel)" % (fis, u, v, C))
            if not union(u, v, 0 if C >= 1 else 1):
                raise Unsupported("inconsistent sign gauges: the attractive / repulsive pattern around (%d,%d) is a frustrated cycle (no global bit-flip makes every cross-ratio >= 1)" % (u, v))
            kinds[(u, v)] = ("coupling", t, fis)
        elif b == 0 and c == 0 and a > 0 and d > 0:
            if not union(u, v, 0):
                raise Unsupported("inconsistent sign gauges: equality factor on (%d,%d) conflicts with the flip parity of its cycle" % (u, v))
            kinds[(u, v)] = ("equality", t, fis)
        else:
            raise Unsupported("incompatible zero pattern: factor(s) %s on (%d,%d) have table %s (only all-positive or diagonal-only tables are representable by the native kernel)" % (fis, u, v, [str(x) for x in t]))
    flip = {v: find(v)[1] for v in free}                                 # canonical: roots unflipped
    # ---- 5. build native blocks and edges
    W = {v: ([Fr(1), Fr(1)] if unary[v] is None else list(unary[v])) for v in free}      # in ORIGINAL state order
    edges = []; identities = []
    for (u, v), (kind, t, fis) in kinds.items():
        a, b, c, d = t
        if kind == "separable":
            # F_xy = (a, c)_x * (1, b/a)_y
            gu = [a, c]; gv = [Fr(1), b / a]
            W[u] = [W[u][0] * gu[0], W[u][1] * gu[1]]; W[v] = [W[v][0] * gv[0], W[v][1] * gv[1]]
            identities.append({"factors": fis, "scope": [u, v], "kind": "separable", "gauge_u": [str(x) for x in gu], "gauge_v": [str(x) for x in gv]}); continue
        if kind == "equality":
            W[u] = [W[u][0] * a, W[u][1] * d]; edges.append({"u": u, "v": v, "r": "1"})
            identities.append({"factors": fis, "scope": [u, v], "kind": "equality", "gauge_u": [str(a), str(d)], "r": "1", "note": "F = diag(a,d) = (a,d)_x [x == y]; K_1(x,y) = 2 [x == y] in d = 1 (scalar 1/2 dropped)"}); continue
        # coupling in FLIPPED coordinates: reorder the table so that the cross-ratio is >= 1
        fu, fv = flip[u], flip[v]
        tf = [t[((x ^ fu) << 1) | (y ^ fv)] for x in range(2) for y in range(2)]       # tf[(x,y)] = F(x ^ fu, y ^ fv): entries in flipped order
        a_, b_, c_, d_ = tf
        C = (a_ * d_) / (b_ * c_); tt = _sqrt_rational(C); assert tt is not None and C >= 1
        r = (tt - 1) / (tt + 1); g = [Fr(1), c_ * tt / a_]; h = [a_ / (1 + r), b_ / (1 - r)]
        for x in range(2):
            for y in range(2):
                K = (1 + r) if x == y else (1 - r)
                assert tf[(x << 1) | y] == g[x] * h[y] * K, "internal: factor identity failed"
        # gauges are indexed by FLIPPED state; map back to original state order for the block weights (W is in original order)
        W[u] = [W[u][s] * g[s ^ fu] for s in range(2)]; W[v] = [W[v][s] * h[s ^ fv] for s in range(2)]
        edges.append({"u": u, "v": v, "r": str(r)})
        identities.append({"factors": fis, "scope": [u, v], "kind": "coupling", "flipped_table": [str(x) for x in tf], "cross_ratio": str(C), "t": str(tt), "r": str(r),
                           "gauge_u_flipped": [str(x) for x in g], "gauge_v_flipped": [str(x) for x in h]})
    blocks = []
    for v in free:
        w = W[v]
        rows = [s ^ flip[v] for s in range(2) if w[s] > 0]                 # row = flipped state; x = +1 <-> row 1
        ws = [w[s] for s in range(2) if w[s] > 0]
        if not rows:
            return "INFEASIBLE", {"reason": "variable %d has no positive weight" % v, "var": v}
        den = 1
        for x in ws:
            den = den * x.denominator // math.gcd(den, x.denominator)
        blocks.append({"id": v, "rows": rows, "weights": [int(x * den) for x in ws]})
    native = {"d": 1, "bit_convention": "coordinate 0 <-> bit 0; bit set <-> x = +1 <-> FLIPPED original state 1", "blocks": blocks, "edges": edges,
              "meta": {"adapter": "bench.cbi_adapter d=1 binary pairwise", "n_original_vars": n}}
    cert = {"evidence": {str(k): v for k, v in ev.items()}, "fixed": {str(k): v for k, v in fixed.items()}, "flip": {str(v): flip[v] for v in free}, "free": free,
            "identities": identities, "consumed": consumed, "constant_scalars_dropped": len(const_scalars), "unary_weights_rational": {str(v): [str(x) for x in W[v]] for v in free},
            "query_map": "P(v = s) = P(x_v = +1) if (s XOR flip_v) == 1 else 1 - P(x_v = +1); observed / fixed variables are point masses",
            "stats": {"free_vars": len(free), "fixed_by_propagation": len(fixed) - len(ev), "edges": len(edges), "equality_edges": sum(1 for e in edges if e["r"] == "1"), "separable_pairs": sum(1 for i in identities if i["kind"] == "separable"), "rounds": rounds}}
    return native, cert


def map_intervals(model, ev, cert, result):
    """Original-variable MAR intervals from the CBI result: rows per original variable, [lo, hi] per original state (Fractions)."""
    Q = 1 << result["grid_bits"]; fixed = {int(k): v for k, v in cert["fixed"].items()}; flip = {int(k): v for k, v in cert["flip"].items()}
    rows = {}
    for v in range(model.nvars):
        if v in fixed:
            rows[v] = [[Fr(1 if s == fixed[v] else 0)] * 2 for s in range(model.card[v])]; continue
        iv = result["intervals"].get(str(v))
        if iv is None:
            rows[v] = None; continue
        c = iv["coordinates"][0]; l, u = Fr(int(c["lo"]), Q), Fr(int(c["hi"]), Q)            # P(x_v = +1) = P(flipped state 1)
        p1 = (l, u); p0 = (1 - u, 1 - l)                                                        # flipped state 0 / 1
        if flip[v] == 0:
            rows[v] = [list(p0), list(p1)]
        else:
            rows[v] = [list(p1), list(p0)]                                                      # original state s <-> flipped state s ^ 1
    return rows


# ------------------------------------------------------------------ INDEPENDENT checker
def prove_forced(m, ev):
    """Replays, from the RAW factors and the evidence only, every state exclusion the adapter may rely on: a variable v is FORCED to state s
    when, after slicing every factor at the currently justified fixed set, the product over the factors whose remaining scope is exactly {v}
    is zero at every other state; a variable with no positive state proves Z = 0. Iterated to a fixpoint. Returns (fixed, zero_partition_witness)."""
    import itertools
    fixed = dict(ev); witness = None; changed = True
    def zero_constant():
        for f in m.factors:
            if all(u in fixed for u in f.scope) and f.at({u: fixed[u] for u in f.scope}) == 0:
                return {"factor": f.index, "reason": "factor is zero at the fixed / observed assignment"}
        return None
    while changed:
        witness = zero_constant()
        if witness is not None:
            return fixed, witness
        changed = False
        for v in range(m.nvars):
            if v in fixed:
                continue
            prod = [Fr(1)] * m.card[v]; touched = False
            for f in m.factors:
                if v not in f.scope:
                    continue
                others = [u for u in f.scope if u != v and u not in fixed]
                if others:
                    continue                                                     # not a unary slice yet
                touched = True
                for sv in range(m.card[v]):
                    a = {u: fixed[u] for u in f.scope if u in fixed}; a[v] = sv; prod[sv] *= f.at(a)
            if not touched:
                continue
            pos = [sv for sv in range(m.card[v]) if prod[sv] > 0]
            if not pos:
                return fixed, {"var": v, "reason": "no positive state after slicing at the proved fixed set"}
            if len(pos) == 1:
                fixed[v] = pos[0]; changed = True
    return fixed, zero_constant()


def check_adapter(model_path, evid_path, native, cert, result=None):
    """Re-derives the global weight identity from the RAW files: W_external(x, e) = const * W_native(T(x)) over all allowed assignments, as a
    product of checked LOCAL identities, plus the bijection T (bit flips, PROVED fixed variables) and the query mapping. Nothing declared by the
    producer is taken as a premise: fixed states are re-proved (prove_forced), the native edge list must correspond EXACTLY (as a list, with
    multiplicities) to the non-separable merged pairwise scopes, blocks must be exactly the free variables with valid rows / weights, flips
    must be bits, and every original factor occurrence must be consumed exactly once. Raises AssertionError on the first failure."""
    m = U.read_model(model_path); ev = U.read_evidence(evid_path)
    # --- declared structure must be well-formed before anything is trusted
    assert isinstance(cert.get("fixed"), dict) and isinstance(cert.get("flip"), dict) and isinstance(cert.get("free"), list), "certificate structure"
    fixed = {int(k): int(v) for k, v in cert["fixed"].items()}; flip = {int(k): int(v) for k, v in cert["flip"].items()}; free = [int(v) for v in cert["free"]]
    assert all(0 <= v < m.nvars and 0 <= s < m.card[v] for v, s in fixed.items()), "a fixed state is out of range"
    assert all(ev[k] == fixed.get(k) for k in ev), "evidence not contained in the fixed set"
    # --- FORCED states are PROVED from the raw factors, never read from the certificate
    proved, zw = prove_forced(m, ev)
    assert zw is None, "the original model has Z = 0 under the evidence (%s); no marginal certificate may be published" % zw
    assert fixed == proved, "declared fixed set %s differs from the independently proved fixed set %s" % (sorted(fixed.items()), sorted(proved.items()))
    assert sorted(free) == sorted(v for v in range(m.nvars) if v not in fixed) and len(set(free)) == len(free), "free set is not the complement of the fixed set"
    assert all(m.card[v] == 2 for v in free), "a free variable is not binary"
    assert sorted(flip) == sorted(free) and all(x in (0, 1) for x in flip.values()), "flip map must assign a bit to exactly the free variables"
    # --- native blocks: exactly the free variables, unique, rows a nonempty subset of {0,1}, positive integer weights
    assert native.get("d") == 1, "native d must be 1 for this adapter"
    ids = [b["id"] for b in native["blocks"]]; assert len(ids) == len(set(ids)) and sorted(ids) == sorted(free), "blocks are not exactly the free variables (duplicates or mismatch)"
    blocks = {b["id"]: b for b in native["blocks"]}
    for v, b in blocks.items():
        assert b["rows"] and all(r in (0, 1) for r in b["rows"]) and len(set(b["rows"])) == len(b["rows"]), "block %d rows" % v
        assert len(b["weights"]) == len(b["rows"]) and all(isinstance(w, int) and not isinstance(w, bool) and w > 0 for w in b["weights"]), "block %d weights" % v
    # --- every original factor occurrence consumed exactly once (counted over the DECLARED lists, before any dict construction)
    seen = {}
    for c in cert["consumed"]:
        if "factor" in c:
            seen[c["factor"]] = seen.get(c["factor"], 0) + 1
    for i in cert["identities"]:
        for fi in i["factors"]:
            seen[fi] = seen.get(fi, 0) + 1
    assert sorted(seen) == list(range(len(m.factors))) and all(v == 1 for v in seen.values()), "factor occurrences are not covered exactly once"
    # --- rebuild the unary product per free variable from the RAW factors (own slicing) and the declared gauges
    import itertools
    unary = {v: [Fr(1), Fr(1)] for v in free}
    def sliced(f):
        sc = [v for v in f.scope if v not in fixed]; tab = {}
        for conf in itertools.product(*[range(m.card[v]) for v in sc]):
            a = dict(zip(sc, conf)); a.update({v: fixed[v] for v in f.scope if v in fixed}); tab[conf] = f.at(a)
        return sc, tab
    pairs = {}
    for f in m.factors:
        sc, tab = sliced(f)
        if len(sc) == 0:
            assert tab[()] > 0, "a constant factor is zero at the fixed assignment"
        elif len(sc) == 1:
            v = sc[0]; unary[v] = [unary[v][s] * tab[(s,)] for s in range(2)]
        else:
            assert len(sc) == 2, "a factor keeps arity >= 3"
            u, v = sc; key = (min(u, v), max(u, v))
            t = [tab[(x, y)] if u < v else tab[(y, x)] for x in range(2) for y in range(2)]
            pairs.setdefault(key, []).append((f.index, t))
    # --- declared identities: exactly one per merged scope (as a LIST: duplicates rejected), each checked ENTRYWISE in original coordinates
    scopes_decl = [tuple(int(x) for x in i["scope"]) for i in cert["identities"]]
    assert len(scopes_decl) == len(set(scopes_decl)) and all(len(sc) == 2 and sc[0] < sc[1] for sc in scopes_decl), "declared identity scopes must be distinct ordered pairs"
    decl = {sc: i for sc, i in zip(scopes_decl, cert["identities"])}
    assert set(decl) == set(pairs), "declared pair identities do not match the raw pairwise scopes after slicing"
    # --- native edge LIST must correspond exactly to the non-separable identities: valid endpoints, no self-loops, no duplicates, no extras
    raw_edges = native["edges"]
    for e in raw_edges:
        assert isinstance(e.get("u"), int) and isinstance(e.get("v"), int) and e["u"] in blocks and e["v"] in blocks and e["u"] != e["v"], "native edge with invalid endpoints %r" % (e,)
    edge_keys = [(min(e["u"], e["v"]), max(e["u"], e["v"])) for e in raw_edges]
    assert len(edge_keys) == len(set(edge_keys)), "duplicate native edge occurrence"
    expected_edges = {sc for sc, i in decl.items() if i["kind"] in ("coupling", "equality")}
    assert set(edge_keys) == expected_edges, "native edge set %s differs from the declared non-separable pair scopes %s (extra or missing interactions)" % (sorted(set(edge_keys) - expected_edges), sorted(expected_edges - set(edge_keys)))
    edges = {k: Fr(e["r"]) for k, e in zip(edge_keys, raw_edges)}
    for (u, v), lst in pairs.items():
        assert sorted(fi for fi, _ in lst) == sorted(decl[(u, v)]["factors"]), "factor list for (%d,%d)" % (u, v)
        t = [Fr(1)] * 4
        for _, tt in lst:
            t = [x * y for x, y in zip(t, tt)]
        i = decl[(u, v)]
        if i["kind"] == "separable":
            gu = [Fr(x) for x in i["gauge_u"]]; gv = [Fr(x) for x in i["gauge_v"]]
            for x in range(2):
                for y in range(2):
                    assert t[(x << 1) | y] == gu[x] * gv[y], "separable identity (%d,%d)" % (u, v)
            unary[u] = [unary[u][s] * gu[s] for s in range(2)]; unary[v] = [unary[v][s] * gv[s] for s in range(2)]
        elif i["kind"] == "equality":
            a, b, c, d = t; assert b == 0 and c == 0 and a > 0 and d > 0 and edges.get((u, v)) == 1, "equality identity (%d,%d)" % (u, v)
            assert [Fr(x) for x in i["gauge_u"]] == [a, d]; unary[u] = [unary[u][0] * a, unary[u][1] * d]
            assert flip[u] == flip[v], "equality endpoints must share the flip (x == y preserved)"
        elif i["kind"] == "coupling":
            r = Fr(i["r"]); assert edges.get((u, v)) == r and 0 <= r < 1, "coupling edge (%d,%d)" % (u, v)
            g = [Fr(x) for x in i["gauge_u_flipped"]]; h = [Fr(x) for x in i["gauge_v_flipped"]]; fu, fv = flip[u], flip[v]
            assert all(x > 0 for x in g + h), "gauges must be positive"
            for x in range(2):
                for y in range(2):
                    K = (1 + r) if ((x ^ fu) == (y ^ fv)) else (1 - r)              # kernel acts on FLIPPED states
                    assert t[(x << 1) | y] == g[x ^ fu] * h[y ^ fv] * K, "coupling identity (%d,%d) at (%d,%d)" % (u, v, x, y)
            unary[u] = [unary[u][s] * g[s ^ fu] for s in range(2)]; unary[v] = [unary[v][s] * h[s ^ fv] for s in range(2)]
        else:
            raise AssertionError("unknown identity kind %r" % i["kind"])
    # --- block weights = the rebuilt unary products up to one positive scalar per block, rows = flipped positive states
    for v in free:
        b = blocks[v]; w = unary[v]; rows = [s ^ flip[v] for s in range(2) if w[s] > 0]
        assert b["rows"] == rows, "block %d rows" % v
        ws = [w[s] for s in range(2) if w[s] > 0]; bw = [Fr(x) for x in b["weights"]]
        assert len(ws) == len(bw) and all(ws[k] * bw[0] == ws[0] * bw[k] for k in range(len(ws))), "block %d weights are not proportional to the unary product" % v
    out = {"factors_checked": len(m.factors), "pairs_checked": len(pairs), "free": len(free), "fixed": len(fixed), "forced_states_proved": len(fixed) - len(ev), "native_edges": len(raw_edges)}
    if result is not None:
        # query BINDING: the native result must be for exactly the free variables (external ids), and the published per-original-state
        # intervals must be the flip-mapped CBI coordinate intervals; fixed variables are point masses
        assert sorted(int(q) for q in result.get("requested_queries", [])) == sorted(free), "native result was not requested for exactly the free variables"
        assert (result.get("id_map") or {}).get("external_ids") == sorted(free), "native id map is not the free-variable list"
        rows = map_intervals(m, ev, cert, result); Q = 1 << result["grid_bits"]
        for v in free:
            if str(v) not in result["intervals"]:
                continue
            c = result["intervals"][str(v)]["coordinates"][0]; l, u = Fr(int(c["lo"]), Q), Fr(int(c["hi"]), Q)
            exp1 = [l, u] if flip[v] == 0 else [1 - u, 1 - l]
            assert rows[v][1] == exp1 and rows[v][0] == [1 - exp1[1], 1 - exp1[0]], "query map for variable %d" % v
        out["query_map_checked"] = True
    return out
