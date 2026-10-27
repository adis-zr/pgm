"""Independent complete-query certificate verifier for the closeout repair.

This is a DISTINCT path. It never calls the producer's SignState.qualifies(), prefix_enclosure() or
rank_and_designate_tail() for any substantive calculation: scores, ordering, ties, the designated tail, unresolved
contributions, D, W, the prefix search, the final ratio, allowance, clipping, outward rounding and the difference are
all recomputed here from exact rationals.

It verifies SAVED outputs; it never recomputes a saved response. Masses and weights absent from the records are
reconstructed once (see repair_masses.py) and that reuse is labelled.

Rejection controls (production entry, each with a named check):
  empty/truncated checker evidence, a missing unresolved node, wrong order/tie, wrong omission set, altered D or W,
  a false first-prefix claim, a changed final endpoint, and lower<=upper on EVERY raw channel coordinate and response.
"""
from __future__ import annotations
import sys, os, json, glob
sys.set_int_max_str_digits(0)
from fractions import Fraction as Fr

MESH64 = 1 << 64
TAIL = Fr(1, 10000)
ALLOWANCE = Fr(1000001000, 1000000000001)
WIDTH = Fr(1, 100)
E_PUB = Fr(1, 1 << 30)
E_INT = Fr(1, 1 << 36)


class CertificateFailure(Exception):
    """a saved publication fails a required mathematical containment, or a reconstruction disagrees"""


def fx(s: str) -> Fr:
    m, e = s.split("*2^"); return Fr(int(m)) * (Fr(2) ** int(e))

def fb(h: str) -> Fr:
    import struct; return Fr(struct.unpack(">d", bytes.fromhex(h))[0])

def _floor(x): n = (x * MESH64).numerator // (x * MESH64).denominator; return Fr(n, MESH64)
def _ceil(x): return -_floor(-x)

def iprod(a, b):
    ps = (a[0]*b[0], a[0]*b[1], a[1]*b[0], a[1]*b[1]); return (min(ps), max(ps))


# ---------------- raw-interval order predicate (independent of radius/width/containment) ----------------
def check_raw_order(path, kind):
    """lower <= upper for EVERY raw channel coordinate and response. Run BEFORE any radius/width/containment test."""
    J = json.load(open(path)); bad = []
    for ch in J["channels"]:
        for comp in ("re", "im"):
            v = ch[comp]
            if kind == "interval":
                lo, hi = fx(v[0]), fx(v[1])
                if not lo <= hi: bad.append((ch["k"], ch["marker"], comp, str(lo), str(hi)))
            else:
                x = fb(v)
                if x != x: bad.append((ch["k"], ch["marker"], comp, "NaN", "NaN"))
    for r in J["response"]:
        if kind == "interval":
            lo, hi = fx(r["iv"][0]), fx(r["iv"][1])
            if not lo <= hi: bad.append(("response", r["marker"], "iv", str(lo), str(hi)))
        else:
            x = fb(r["bits"])
            if x != x: bad.append(("response", r["marker"], "bits", "NaN", "NaN"))
    return {"file": os.path.basename(path), "kind": kind, "coordinates_checked": 2 * len(J["channels"]) + len(J["response"]),
            "inversions": bad, "ok": not bad}


# ---------------- independent reconstruction of ranking, tail, contributions, prefix ----------------
class IndependentVerifier:
    """recomputes everything from (node -> published mass/weight) and (processed node -> published response)"""

    def __init__(self, sign, delta):
        self.sign = sign; self.delta = Fr(delta)
        self.Z = {}      # (node, sigma) -> producer published mass interval
        self.W_pub = {}  # node -> producer published weight interval
        self.Zc = {}     # (node, sigma) -> checker UNPADDED mass
        self.Wc = {}     # node -> checker unpadded weight

    def add_node(self, node, Zp, Zm, w, Zcp=None, Zcm=None, wc=None):
        for nm, iv in (("Z+", Zp), ("Z-", Zm), ("w", w)):
            if not iv[0] <= iv[1]: raise CertificateFailure(f"{nm} inverted at {node}")
            if iv[0] <= 0: raise CertificateFailure(f"{nm} lower endpoint not strictly positive at {node}")
        self.Z[(node, 1)] = Zp; self.Z[(node, -1)] = Zm; self.W_pub[node] = w
        if Zcp is not None: self.Zc[(node, 1)] = Zcp; self.Zc[(node, -1)] = Zcm; self.Wc[node] = wc

    # --- independent score / order / tail, NOT the producer's
    def scores(self):
        out = {}
        for nd in self.W_pub:
            T_hi = self.Z[(nd, 1)][1] + self.Z[(nd, -1)][1]      # independently summed total
            out[nd] = self.W_pub[nd][1] * T_hi
        return out

    def order_and_tail(self):
        sc = self.scores()
        denom = sum(sc.values(), Fr(0))
        if denom <= 0: raise CertificateFailure("ranking denominator not positive")
        order = sorted(sc, key=lambda j: (-sc[j], j[0], j[1]))   # descending score, lexicographic ties
        omit = set(); acc = Fr(0)
        for nd in reversed(order):
            if acc + sc[nd] <= denom * TAIL: omit.add(nd); acc += sc[nd]
            else: break
        return {"scores": sc, "denominator": denom, "order": order, "omit": omit, "accumulated": acc}

    # --- independent D and W from the CHECKER's own quantities
    def checker_DW(self, node, R_inner):
        if node not in self.Wc: raise CertificateFailure(f"no checker evidence for {node}")
        Tc = (self.Zc[(node, -1)][0] + self.Zc[(node, 1)][0], self.Zc[(node, -1)][1] + self.Zc[(node, 1)][1])
        out = {}
        for sg in (1, -1):
            Zhi = self.Zc[(node, sg)][1]
            p = iprod(Tc, R_inner[sg]); a = self.delta * Zhi
            lo, hi = max(Fr(0), p[0] - a), min(Zhi, p[1] + a)
            if lo > hi: raise CertificateFailure(f"empty checker D at {node} marker {sg}")
            out[sg] = {"D": (lo, hi), "W": iprod((lo, hi), self.Wc[node])}
        return out

    def producer_DW(self, node, R_pub):
        T = (self.Z[(node, -1)][0] + self.Z[(node, 1)][0], self.Z[(node, -1)][1] + self.Z[(node, 1)][1])
        out = {}
        for sg in (1, -1):
            Zhi = self.Z[(node, sg)][1]
            p = iprod(T, R_pub[sg]); a = self.delta * Zhi
            lo, hi = max(Fr(0), p[0] - a), min(Zhi, p[1] + a)
            if lo > hi: raise CertificateFailure(f"empty producer D at {node} marker {sg}")
            out[sg] = {"D": (lo, hi), "W": iprod((lo, hi), self.W_pub[node])}
        return out

    # --- independent prefix enclosure over ALL nodes
    def enclosure(self, Wmap):
        Lp = Up = Lm = Um = Fr(0)
        for (nd, sg), iv in Wmap.items():
            if sg == 1: Lp += iv[0]; Up += iv[1]
            else: Lm += iv[0]; Um += iv[1]
        dlo, dhi = Lp + Um, Up + Lm
        if dlo <= 0 or dhi <= 0: return (Fr(0), Fr(1))
        raw = (Lp / dlo, Up / dhi)
        if raw[0] > raw[1]: raise CertificateFailure("inverted sharp ratio")
        lo, hi = raw[0] - ALLOWANCE, raw[1] + ALLOWANCE
        lo, hi = max(Fr(0), lo), min(Fr(1), hi)
        return (_floor(lo), _ceil(hi))

    def unresolved_W(self, node, sg):
        return (Fr(0), self.W_pub[node][1] * self.Z[(node, sg)][1])

    def replay_prefix(self, order, omit, responses):
        """find the FIRST prefix meeting the original width contract, under PRODUCER publications only.
        The checker's tighter bounds are never used to choose a prefix."""
        Wmap = {(nd, sg): self.unresolved_W(nd, sg) for nd in self.W_pub for sg in (1, -1)}
        processable = [nd for nd in order if nd not in omit]
        widths = []
        for idx, nd in enumerate(processable, start=1):
            if nd not in responses: return {"first": None, "widths": widths, "exhausted_evidence_at": idx}
            dw = self.producer_DW(nd, responses[nd])
            for sg in (1, -1): Wmap[(nd, sg)] = dw[sg]["W"]
            e = self.enclosure(Wmap); wd = e[1] - e[0]; widths.append((idx, wd))
            if wd <= WIDTH:
                return {"first": idx, "enclosure": e, "widths": widths, "W_at_stop": Wmap}
        return {"first": None, "widths": widths, "enclosure": self.enclosure(Wmap), "W_at_stop": Wmap}
