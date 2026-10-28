"""Signed collective mode discovery and verification (spec section 6).

Consumes ACTUAL factor values, never a family name. Floating point proposes;
exact rationals and directed enclosures certify. Every candidate is checked
against every affected input factor, including MISSING pair edges.
"""
from __future__ import annotations
import sys
sys.set_int_max_str_digits(0)
from fractions import Fraction as Fr
from dataclasses import dataclass, field
import math
from mdi import config as K
from mdi import arith as A
from mdi.model import Factor


class Declined(Exception):
    pass


# ---------------------- 6.1 exact gauge transfer ----------------------

@dataclass
class Gauge:
    """Phi = C * u(a) * v(b) * H(a,b) exactly, with H(a,0)=H(0,b)=1.

    u and v are absorbed into the endpoint unary factors; C is retained in the
    identity record. Equivalent redistributions of unary fields across pair
    tables must not hide a recognizable interaction, which is exactly what this
    removes.
    """
    C: Fr
    u: list                 # u(a), a in range(d_i); u(0)=1
    v: list                 # v(b); v(0)=1
    H: list                 # H[a][b], first row and column all 1


def gauge_split(table, di, dj) -> Gauge:
    """Exact rational split of a STRICTLY POSITIVE pair table."""
    def ent(a, b):
        return Fr(table[a * dj + b])
    C = ent(0, 0)
    if C <= 0:
        raise Declined("gauge split needs a positive reference entry")
    u = [ent(a, 0) / C for a in range(di)]
    v = [ent(0, b) / C for b in range(dj)]
    H = []
    for a in range(di):
        row = []
        for b in range(dj):
            num = ent(a, b) * C
            den = ent(a, 0) * ent(0, b)
            if den <= 0:
                raise Declined("gauge split needs positive reference rows")
            row.append(num / den)
        H.append(row)
    # identity check: Phi == C*u*v*H exactly
    for a in range(di):
        for b in range(dj):
            if C * u[a] * v[b] * H[a][b] != ent(a, b):
                raise AssertionError("gauge split identity failed")
    return Gauge(C=C, u=u, v=v, H=H)


def walsh_J(table) -> float:
    """Binary +-1 log-Walsh coupling J = (1/4) log (p++ p-- / (p+- p-+)).

    PROPOSAL ONLY: generally irrational. State order is (0,1) = (-1,+1).
    """
    p00, p01, p10, p11 = (float(table[0]), float(table[1]),
                          float(table[2]), float(table[3]))
    if min(p00, p01, p10, p11) <= 0:
        raise Declined("Walsh coupling needs a strictly positive table")
    return 0.25 * math.log((p11 * p00) / (p01 * p10))


# ---------------------- 6.1 candidate generation ----------------------

@dataclass
class ModeCandidate:
    """W'(z) = b(z) exp{ 1/2 sum_k s_k gamma_k ( sum_i f_ki(z_i) )^2 }"""
    signs: list             # s_k in {-1,+1}
    gammas: list            # exact rational gamma_k > 0
    features: list          # features[k][i] -> list over states: f_ki(a), rational
    kind: str               # how it was proposed
    rank: int = 0

    def __post_init__(self):
        self.rank = len(self.signs)


def _pair_matrix(free, factors, card):
    """Gauge-removed interaction tables keyed by variable pair.

    Returns (Hs, unary_absorb, constants, zero_pairs) where Hs[(i,j)] is the
    exact H table and unary_absorb[i][a] accumulates the transferred gauges.
    Pairs whose table contains a zero are EXCLUDED from mode fitting and stay in
    the residual unchanged.
    """
    Hs, consts, zero_pairs = {}, {}, set()
    raw = {}                    # scope -> PRODUCT of every factor on that scope
    absorb = {v: [Fr(1)] * card[v] for v in free}
    for f in factors:
        if len(f.scope) != 2:
            continue
        i, j = f.scope
        if i not in absorb or j not in absorb:
            continue
        if i > j:
            # Normalize the scope order so (j,i) combines with (i,j). The source
            # table is indexed table[a*card[j] + b] with a over variable i and b
            # over variable j; the target must be indexed [b*card[i] + a]. The
            # previous comprehension iterated the wrong extents and produced 4 of
            # 6 entries wrong on a 3x2 reversed scope.
            di, dj = card[i], card[j]          # i is FIRST in the source scope
            tb = [None] * (di * dj)
            for a in range(di):
                for b in range(dj):
                    tb[b * di + a] = f.table[a * dj + b]
            f = Factor(scope=(j, i), card=(dj, di), table=tb, origin=f.origin)
            i, j = j, i
        di, dj = card[i], card[j]
        if any(t == 0 for t in f.table):
            zero_pairs.add((i, j))
            continue
        key = (i, j)
        if key in raw:
            # REPEATED pair factor on the same scope: the model's interaction is
            # the PRODUCT of all such factors. A dict assignment here silently
            # discarded every factor after the first, so nu certified a model
            # that was not the input (two [1,1,1,4] factors became one, moving a
            # marginal from 17/19 to 5/7).
            raw[key] = [a * b for a, b in zip(raw[key], f.table)]
        else:
            raw[key] = list(f.table)
    for (i, j), tbl in sorted(raw.items()):
        di, dj = card[i], card[j]
        if any(t == 0 for t in tbl):
            zero_pairs.add((i, j))
            continue
        g = gauge_split(tbl, di, dj)
        Hs[(i, j)] = g.H
        consts[(i, j)] = g.C
        for a in range(di):
            absorb[i][a] *= g.u[a]
        for b in range(dj):
            absorb[j][b] *= g.v[b]
    return Hs, absorb, consts, zero_pairs


def propose_modes(free, factors, card, max_rank=None):
    """A finite menu: constant/proportional row proposals, block-constant from
    repeated profiles, and at most two bounded low-rank fits per residual mask.

    Binary variables only for the quadratic-form proposal; categorical support
    uses reference-state contrasts, implemented for the binary case here and
    declined otherwise with a recorded reason.
    """
    max_rank = max_rank or K.CAPS["mode_rank_total"]
    binary = all(card[v] == 2 for v in free)
    Hs, absorb, consts, zero_pairs = _pair_matrix(free, factors, card)
    info = {"pairs_with_zero_excluded": len(zero_pairs),
            "gauge_removed_pairs": len(Hs), "binary": binary}
    if not binary:
        return [], {**info, "declined": "categorical mode fitting not implemented "
                                        "in this build; residual keeps all factors"}
    if not Hs:
        return [], {**info, "declined": "no strictly positive pair factors"}

    idx = {v: k for k, v in enumerate(sorted(free))}
    n = len(idx)
    if n > K.CAPS["feature_contrast_dim"]:
        return [], {**info, "declined": "feature dimension %d exceeds cap" % n}

    # Build the symmetric coupling matrix from gauge-removed tables.
    # For binary +-1 with H(0,0)=H(0,1)=H(1,0)=1, H(1,1) carries the whole
    # interaction: log H(1,1) = 4J in the spin parameterization.
    Jm = [[0.0] * n for _ in range(n)]
    present = []
    for (i, j), H in Hs.items():
        h11 = float(H[1][1])
        if h11 <= 0:
            continue
        J = 0.25 * math.log(h11)
        a, b = idx[i], idx[j]
        Jm[a][b] = Jm[b][a] = J
        present.append(((i, j), J))
    if not present:
        return [], {**info, "declined": "all gauge-removed interactions are trivial"}

    cands = []

    # ---- proposal 1: constant / proportional interaction rows ----
    Js = [J for _, J in present]
    Jmin, Jmax = min(Js), max(Js)
    spread = (Jmax - Jmin)
    scale = max(abs(Jmax), abs(Jmin), 1e-300)
    if spread <= 1e-9 * scale and abs(Jmax) > 1e-12:
        # a single uniform coupling across the present edges: rank-1 mode with
        # f_i = 1 on every variable in the support of those edges
        Jc = Fr(round(Jmax * 10 ** 12), 10 ** 12)
        s = 1 if Jc > 0 else -1
        # (gamma/2)(sum_i f_i)^2 = (gamma/2)*sum f_i^2 + gamma*sum_{i<j} f_i f_j,
        # so a uniform pair coupling J needs gamma = |J|. Using 2|J| doubled the
        # coupling and made the residual retain an OPPOSING interaction.
        gam = abs(Jc)
        if gam > 0:
            vs = sorted({v for (i, j), _ in present for v in (i, j)})
            feat = {v: [Fr(-1), Fr(1)] if v in vs else [Fr(0), Fr(0)] for v in free}
            cands.append(ModeCandidate(signs=[s], gammas=[gam], features=[feat],
                                       kind="constant_rows"))

    # ---- proposal 2: block-constant from repeated profiles ----
    prof = {}
    for v in sorted(free):
        row = tuple(sorted(round(Jm[idx[v]][idx[w]], 12) for w in sorted(free) if w != v))
        prof.setdefault(row, []).append(v)
    if 1 < len(prof) <= 4:
        info["repeated_profile_blocks"] = len(prof)

    # ---- proposal 3: bounded low-rank fits, allowing the diagonal to be free ----
    # Fit J ~ sum_k s_k g_k w_k w_k^T on OFF-DIAGONAL entries only, letting the
    # diagonal complete freely: forcing it to zero can turn a rank-one
    # complete-graph interaction into a full-rank matrix.
    try:
        vecs = _power_fits(Jm, n, max_rank)
    except Exception as e:
        vecs = []
        info["lowrank_error"] = "%s: %s" % (type(e).__name__, e)
    npos = nneg = 0
    for (lamb, w) in vecs:
        s = 1 if lamb > 0 else -1
        if s > 0 and npos >= K.CAPS["mode_rank_positive"]:
            continue
        if s < 0 and nneg >= K.CAPS["mode_rank_negative"]:
            continue
        g = abs(lamb)
        if g <= 0:
            continue
        # The eigenvector w is UNIT normalized, so lambda already absorbs the
        # feature scale: for a uniform coupling J the fixed point is lambda = J*n
        # with w_k = 1/sqrt(n). Rounding the features to +-1 while keeping
        # |lambda| as gamma therefore double-counted the normalization and
        # reported gamma = |J|*n instead of |J| (1.8000 for J=0.30, n=6).
        #
        # Keep the eigenvector's own scale in the features instead: with
        # f_k = w_k * sqrt(gamma_raw) the induced coupling is
        # gamma * f_i * f_j = lambda * w_i * w_j, which is the fitted matrix
        # entry. We therefore set gamma = 1 in units of the scaled features.
        D = 10 ** 6
        import math as _m
        scale = _m.sqrt(g)
        feat = {}
        inv = {k: v for v, k in idx.items()}
        mx = max(abs(w[k]) for k in range(n)) or 1.0
        for k in range(n):
            c = Fr(round(w[k] * scale / mx * D), D)
            feat[inv[k]] = [-c, c]
        # gamma restores the normalization removed by dividing out mx
        gq = Fr(max(1, round(mx * mx * D)), D)
        cands.append(ModeCandidate(signs=[s], gammas=[gq], features=[feat],
                                   kind="lowrank_rank1"))
        if s > 0:
            npos += 1
        else:
            nneg += 1
        if len(cands) >= max_rank:
            break
    return cands, info


def _power_fits(Jm, n, kmax, iters=None):
    """Deterministic power iteration with a FREE diagonal. Proposal only.

    B.5: the previous loop mutated `lam` while accumulating the Rayleigh
    quotient that defines it, so the matrix changed underneath its own quadratic
    form and the iteration did not converge to the completion it claimed. The
    diagonal completion is now FIXED from the previous iterate while the new
    Rayleigh quantity is evaluated, then updated once per sweep.
    """
    iters = iters or K.CAPS["mode_fit_iterations"]
    Mx = [row[:] for row in Jm]
    out = []
    for _ in range(min(kmax, 2)):
        v = [1.0 / math.sqrt(n)] * n
        lam = 0.0
        for _ in range(iters):
            lam_fixed = lam              # frozen for this whole sweep
            w = []
            for a in range(n):
                acc = 0.0
                for b in range(n):
                    m = Mx[a][b] if a != b else lam_fixed * v[a] * v[a]
                    acc += m * v[b]
                w.append(acc)
            nrm = math.sqrt(sum(x * x for x in w))
            if nrm <= 1e-300:
                return out
            vn = [x / nrm for x in w]
            # Rayleigh quotient with the SAME fixed diagonal completion and the
            # NEW vector; nothing is mutated while it is accumulated
            num = 0.0
            for a in range(n):
                for b in range(n):
                    m = Mx[a][b] if a != b else lam_fixed * vn[a] * vn[a]
                    num += vn[a] * m * vn[b]
            v, lam = vn, num
        if abs(lam) < 1e-12:
            break
        out.append((lam, v[:]))
        for a in range(n):
            for b in range(n):
                if a != b:
                    Mx[a][b] -= lam * v[a] * v[b]
    return out


# ---------------------- 6.2 residual construction and nu ----------------------

@dataclass
class Residual:
    """b(z) plus the certified uniform error bound nu."""
    unary: dict               # var -> list of exact rational entries
    pairs: dict               # (i,j) -> exact rational table (strictly positive)
    kept: list                # factor indices kept UNCHANGED in b
    nu: Fr                    # sum of absolute log-error bounds
    const_log: Fr             # recorded factor-wide constant (removed)
    detail: dict


def _log_enclose(q: Fr, ctx: A.Ctx):
    """Directed enclosure of log(q) for an exact positive rational."""
    import gmpy2
    if q <= 0:
        raise Declined("log of a nonpositive value")
    with ctx.D:
        lo = gmpy2.log(gmpy2.mpq(q.numerator, q.denominator))
    with ctx.U:
        hi = gmpy2.log(gmpy2.mpq(q.numerator, q.denominator))
    return A.exact_fr(lo), A.exact_fr(hi)


def build_residual(free, factors, card, cand: ModeCandidate, ctx: A.Ctx,
                   round_bits=40):
    """Construct the residual and certify nu.

    For EVERY pair, including absent input pairs, bound
        | log Phi_ij - G_ij - log residual_ij |
    after removing an explicitly recorded factor-wide constant, and do the
    corresponding unary check. nu is the SUM of those absolute bounds.

    Zero-containing and higher-arity factors stay unchanged in b and cancel on
    common support.
    """
    Hs, absorb, consts, zero_pairs = _pair_matrix(free, factors, card)
    binary = all(card[v] == 2 for v in free)
    if not binary:
        raise Declined("residual construction implemented for binary variables here")

    # G_ij(a,b) and D_i(a) induced by the modes
    def G(i, j, a, b):
        acc = Fr(0)
        for k in range(cand.rank):
            fi = cand.features[k].get(i)
            fj = cand.features[k].get(j)
            if fi is None or fj is None:
                continue
            acc += cand.signs[k] * cand.gammas[k] * fi[a] * fj[b]
        return acc

    def D(i, a):
        acc = Fr(0)
        for k in range(cand.rank):
            fi = cand.features[k].get(i)
            if fi is None:
                continue
            acc += cand.signs[k] * cand.gammas[k] * fi[a] * fi[a]
        return acc / 2

    scale = Fr(1, 1 << round_bits)

    def rround(x: Fr) -> Fr:
        """Round an exact rational onto a dyadic grid (explicit, recorded)."""
        return Fr(round(x / scale)) * scale

    nu = Fr(0)
    detail = {"pairs_checked": 0, "absent_pairs_checked": 0, "unaries_checked": 0,
              "zero_pairs_kept": len(zero_pairs)}

    # all variable pairs that any mode couples, plus all present positive pairs
    coupled = set()
    for k in range(cand.rank):
        vs = [v for v, f in cand.features[k].items() if any(x != 0 for x in f)]
        for a in range(len(vs)):
            for b in range(a + 1, len(vs)):
                i, j = sorted((vs[a], vs[b]))
                coupled.add((i, j))
    for (i, j) in Hs:
        coupled.add(tuple(sorted((i, j))))

    res_pairs = {}
    for (i, j) in sorted(coupled):
        H = Hs.get((i, j)) or Hs.get((j, i))
        absent = H is None
        if absent:
            detail["absent_pairs_checked"] += 1
            # Phi_ij == 1 identically for an absent edge
            logPhi = lambda a, b: (Fr(0), Fr(0))
        else:
            detail["pairs_checked"] += 1
        tbl = []
        worst = Fr(0)
        for a in range(card[i]):
            for b in range(card[j]):
                if absent:
                    lp_lo = lp_hi = Fr(0)
                else:
                    lp_lo, lp_hi = _log_enclose(Fr(H[a][b]), ctx)
                g = G(i, j, a, b)
                # residual table approximates Phi * exp(-G): build it on the grid
                # target log value is log Phi - g
                tgt_lo, tgt_hi = lp_lo - g, lp_hi - g
                mid = (tgt_lo + tgt_hi) / 2
                # choose a positive rational whose log encloses near mid
                rv = _exp_rational(mid, ctx, round_bits)
                rl_lo, rl_hi = _log_enclose(rv, ctx)
                e = max(abs(tgt_hi - rl_lo), abs(tgt_lo - rl_hi))
                if e > worst:
                    worst = e
                tbl.append(rv)
        res_pairs[(i, j)] = tbl
        nu += worst

    # unary: original unary product times transferred gauges times exp(-D_i)
    res_unary = {}
    base_unary = {v: [Fr(1)] * card[v] for v in free}
    for f in factors:
        if len(f.scope) == 1 and f.scope[0] in base_unary:
            v = f.scope[0]
            for a in range(card[v]):
                base_unary[v][a] *= Fr(f.table[a])
    for v in sorted(free):
        detail["unaries_checked"] += 1
        worst = Fr(0)
        row = []
        zero_support = [a for a in range(card[v]) if base_unary[v][a] * absorb[v][a] == 0]
        for a in range(card[v]):
            tgt = base_unary[v][a] * absorb[v][a]
            if tgt == 0:
                row.append(Fr(0))           # zero support stays EXACT
                continue
            lo, hi = _log_enclose(tgt, ctx)
            d = D(v, a)
            tl, th = lo - d, hi - d
            mid = (tl + th) / 2
            rv = _exp_rational(mid, ctx, round_bits)
            rl, rh = _log_enclose(rv, ctx)
            e = max(abs(th - rl), abs(tl - rh))
            if e > worst:
                worst = e
            row.append(rv)
        res_unary[v] = row
        nu += worst

    kept = [fi for fi, f in enumerate(factors)
            if len(f.scope) > 2 or any(t == 0 for t in f.table)]
    const_log = Fr(0)
    for (i, j), c in consts.items():
        lo, hi = _log_enclose(c, ctx)
        const_log += (lo + hi) / 2
    return Residual(unary=res_unary, pairs=res_pairs, kept=kept, nu=nu,
                    const_log=const_log, detail=detail)


def _exp_rational(x: Fr, ctx: A.Ctx, bits=40) -> Fr:
    """A strictly positive rational near exp(x), on an explicit dyadic grid."""
    import gmpy2
    with ctx.D:
        v = gmpy2.exp(gmpy2.mpfr(gmpy2.mpq(x.numerator, x.denominator)))
    q = A.exact_fr(v)
    if q <= 0:
        raise Declined("exp underflowed to zero")
    scale = Fr(1, 1 << bits)
    r = Fr(round(q / scale)) * scale
    if r <= 0:
        r = scale
    return r


def tv_from_nu(nu: Fr) -> Fr:
    """TV(P,P') <= tanh(nu/2) <= nu/2 (exact rational upper bound)."""
    return K.tanh_upper(nu)
