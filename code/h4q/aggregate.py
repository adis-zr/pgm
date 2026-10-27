"""Per-sign ranking, designated tail, prefix aggregation and the first qualifying prefix.

Implements the addendum §1 definitions verbatim. Every quantity is an exact Fraction; nothing here touches floats.

    Zpub[sign,j,sigma] = published positive marker mass          (producer publication endpoints)
    Tpub[sign,j]       = exact endpoint sum of the two Zpub
    wpub[j]            = published Gaussian node weight          (node-only; no sign dependence)
    score[sign,j]      = upper(wpub[j]) * upper(Tpub[sign,j])
    denom[sign]        = exact sum of every score for that sign
    order[sign]        = descending score, lexicographic node ties
    omit[sign]         = frozen reverse-traversal 1/10000 allocation

    W[sign,j,sigma]    = [0, upper(wpub[j]) * upper(Zpub[sign,j,sigma])]   for every unresolved node
    D                  = (Tpub*Rpub + [-delta*upper(Zpub), +delta*upper(Zpub)]) cap [0, upper(Zpub)]
    W[sign,j,sigma]    = interval_product(D, wpub[j])                      once processed

`D` is the unweighted accepted count; `W` is the weighted contribution. Unresolved nodes contribute to W, never to D.
PREFIX_ENCLOSURE sums W over ALL nodes at every prefix, so it is a function called by the width test rather than a
phase that runs after deciding to stop; before any node is processed it returns the valid [0,1]."""
from __future__ import annotations
import sys
sys.set_int_max_str_digits(0)
from fractions import Fraction as Fr

MESH64 = 1 << 64
TAIL_PARAM = Fr(1, 10000)
POSITIVE_ALLOWANCE = Fr(1000001000, 1000000000001)
WIDTH_TARGET = Fr(1, 100)
DIFF_WIDTH_TARGET = Fr(1, 50)


class NumericalRefusal(Exception):
    """a named refusal: negative mass, inverted/empty interval, or a denominator inconsistent with valid bounds"""


def _check_iv(iv, name, nonneg=True):
    lo, hi = iv
    if lo > hi: raise NumericalRefusal(f"{name}: inverted interval [{lo},{hi}]")
    if nonneg and lo < 0: raise NumericalRefusal(f"{name}: negative lower endpoint {lo}")
    return lo, hi


def interval_product(a, b):
    """full outward product over all four endpoint pairs (both arguments may be signed)"""
    lo_a, hi_a = a; lo_b, hi_b = b
    ps = (lo_a * lo_b, lo_a * hi_b, hi_a * lo_b, hi_a * hi_b)
    return (min(ps), max(ps))


def endpoint_sum(a, b):
    return (a[0] + b[0], a[1] + b[1])


def floor_mesh(x: Fr) -> Fr:
    n = (x * MESH64).numerator // (x * MESH64).denominator; return Fr(n, MESH64)
def ceil_mesh(x: Fr) -> Fr:
    return -floor_mesh(-x)


class SignState:
    """all per-sign state: masses, weights, scores, order, omissions, contributions and processed set"""
    def __init__(self, sign: int, delta: Fr):
        self.sign = sign; self.delta = Fr(delta)
        self.Zpub = {}          # (node, sigma) -> published marker mass interval
        self.Tpub = {}          # node -> exact endpoint sum
        self.wpub = {}          # node -> published node weight interval (shared across signs; stored per state for locality)
        self.score = {}         # node -> exact upper(w)*upper(T)
        self.denom = Fr(0)
        self.order = []         # descending score, lexicographic node ties
        self.omit = set()
        self.processed = set()
        self.D = {}             # (node, sigma) -> unweighted accepted count, processed nodes only
        self.W = {}             # (node, sigma) -> weighted contribution, EVERY node
        self.prefix_history = []

    # ---- phase 2 output
    def set_node(self, node, Zpub_plus, Zpub_minus, wpub):
        for nm, iv in (("Zpub[+1]", Zpub_plus), ("Zpub[-1]", Zpub_minus), ("wpub", wpub)):
            _check_iv(iv, f"{nm} at node {node}")
        if Zpub_plus[0] <= 0 or Zpub_minus[0] <= 0:
            raise NumericalRefusal(f"node {node}: marker mass lower endpoint not strictly positive "
                                   f"(a numerical zero is not a support proof)")
        self.Zpub[(node, 1)] = Zpub_plus; self.Zpub[(node, -1)] = Zpub_minus
        self.Tpub[node] = endpoint_sum(Zpub_plus, Zpub_minus)
        self.wpub[node] = wpub
        self.score[node] = wpub[1] * self.Tpub[node][1]
        # every node starts unresolved: its weighted contribution is the valid bound, in W (never in D)
        for sigma in (1, -1):
            self.W[(node, sigma)] = (Fr(0), wpub[1] * self.Zpub[(node, sigma)][1])

    # ---- phase 3
    def rank_and_designate_tail(self):
        if not self.score: raise NumericalRefusal("ranking with no nodes")
        self.denom = sum(self.score.values(), Fr(0))
        if self.denom <= 0: raise NumericalRefusal("ranking denominator not positive")
        self.order = sorted(self.score, key=lambda j: (-self.score[j], j[0], j[1]))
        acc = Fr(0); self.omit = set()
        for node in reversed(self.order):
            if acc + self.score[node] <= self.denom * TAIL_PARAM:
                self.omit.add(node); acc += self.score[node]
            else:
                break
        self.tail_accumulated = acc
        return {"denominator": self.denom, "designated_omissions": len(self.omit), "accumulated_score": acc,
                "allocation_is_a_heuristic": True}

    # ---- phase 4, one node
    def process_node(self, node, Rpub):
        """Rpub: {sigma: published response interval}. Uses PRODUCER PUBLICATION endpoints throughout."""
        if node in self.processed: raise NumericalRefusal(f"node {node} processed twice")
        T = self.Tpub[node]; w = self.wpub[node]
        for sigma in (1, -1):
            Zhi = self.Zpub[(node, sigma)][1]
            R = _check_iv(Rpub[sigma], f"Rpub[{sigma}] at {node}", nonneg=False)
            prod = interval_product(T, R)
            allow = self.delta * Zhi
            lo, hi = prod[0] - allow, prod[1] + allow
            lo, hi = max(Fr(0), lo), min(Zhi, hi)
            if lo > hi: raise NumericalRefusal(f"empty accepted-count intersection at {node} marker {sigma}")
            self.D[(node, sigma)] = (lo, hi)
            self.W[(node, sigma)] = interval_product((lo, hi), w)
        self.processed.add(node)

    # ---- the prefix enclosure, callable at any time
    def prefix_enclosure(self):
        """sum W over ALL nodes for each marker, including every unresolved node; then the sharp ratio."""
        Lp = Up = Lm = Um = Fr(0)
        for (node, sigma), iv in self.W.items():
            if sigma == 1: Lp += iv[0]; Up += iv[1]
            else: Lm += iv[0]; Um += iv[1]
        if Lp < 0 or Lm < 0 or Up < Lp or Um < Lm:
            raise NumericalRefusal("aggregated weighted counts inconsistent with valid positive bounds")
        dlo, dhi = Lp + Um, Up + Lm
        if dlo <= 0 or dhi <= 0:
            # before positive lower information exists the conservative enclosure is [0,1]; this is VALID
            return {"enclosure": (Fr(0), Fr(1)), "basis": "no positive lower information yet", "raw": None,
                    "L_plus": Lp, "U_plus": Up, "L_minus": Lm, "U_minus": Um}
        raw = (Lp / dlo, Up / dhi)
        if raw[0] > raw[1]: raise NumericalRefusal("sharp ratio produced an inverted interval")
        # the fixed positive allowance enlarges the finite-grid marginal once, outward, on both sides
        lo, hi = raw[0] - POSITIVE_ALLOWANCE, raw[1] + POSITIVE_ALLOWANCE
        lo, hi = max(Fr(0), lo), min(Fr(1), hi)
        lo, hi = floor_mesh(lo), ceil_mesh(hi)
        return {"enclosure": (lo, hi), "basis": "sharp ratio", "raw": raw,
                "L_plus": Lp, "U_plus": Up, "L_minus": Lm, "U_minus": Um}

    def width(self):
        e = self.prefix_enclosure()["enclosure"]; return e[1] - e[0]

    def qualifies(self):
        return self.width() <= WIDTH_TARGET


def difference(enc_plus, enc_minus):
    """p_plus - p_minus by interval subtraction"""
    return (enc_plus[0] - enc_minus[1], enc_plus[1] - enc_minus[0])


def verify_prefix(state: SignState, claimed_prefix, checker_W):
    """Independent verification of the ACTUAL first qualifying prefix and all unresolved contributions.

    The checker never selects a replacement prefix from its own tighter bounds: it confirms that the producer's
    claimed prefix is the first one that qualifies under the PRODUCER's published quantities, and separately that
    every unresolved contribution it recomputed is contained in the producer's."""
    out = {}
    # 1. every checker-side weighted contribution contained in the producer's
    bad = [k for k, iv in checker_W.items() if not (state.W[k][0] <= iv[0] and iv[1] <= state.W[k][1])]
    out["all_checker_contributions_contained"] = not bad
    out["containment_violations"] = bad[:5]
    # 2. the claimed prefix is exactly the first qualifying one under the producer's own quantities
    replay = SignState(state.sign, state.delta)
    replay.Zpub = dict(state.Zpub); replay.Tpub = dict(state.Tpub); replay.wpub = dict(state.wpub)
    replay.score = dict(state.score); replay.order = list(state.order); replay.omit = set(state.omit)
    for (node, sigma), iv in state.W.items():
        if node not in state.processed: replay.W[(node, sigma)] = iv
    for (node, sigma) in state.W:
        if node in state.processed and (node, sigma) not in replay.W:
            replay.W[(node, sigma)] = (Fr(0), state.wpub[node][1] * state.Zpub[(node, sigma)][1])
    first = None
    for idx, node in enumerate([n for n in state.order if n not in state.omit], start=1):
        if node not in state.processed: break
        for sigma in (1, -1): replay.W[(node, sigma)] = state.W[(node, sigma)]
        replay.processed.add(node)
        if replay.qualifies(): first = idx; break
    out["first_qualifying_prefix_recomputed"] = first
    out["matches_claimed"] = (first == claimed_prefix)
    out["checker_does_not_select_a_replacement_prefix"] = True
    return out
