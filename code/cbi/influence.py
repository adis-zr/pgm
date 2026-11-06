"""The ORIGINAL-LAW influence system, kept SEPARATE from the simplified computational graph of Q.

Nodes: the blocks of the hard-contracted model with every verified cluster merged into one node. Edges: every original seam between
two nodes, with s_e = coordinates of the kernel mask varying on BOTH endpoints' ORIGINAL (hard-contracted) supports -- retained OR
discarded states; parallel seams between the same two nodes add inside tanh: A_CD <= tanh(sum_e s_e atanh r_e) (Part I (I)).
exp(2 L) = prod ((1+r)/(1-r))^{s_e} exactly in rationals, tanh(L) = (E-1)/(E+1). The solver may delete an edge of Q that became a
unary factor or a constant; the influence edge stays. Each node carries its retention defect rho (0 for ordinary blocks)."""
from __future__ import annotations
from fractions import Fraction as Fr
from cbi import model as M


def varying_mask(block):
    o = 0; a = (1 << 63) - 1
    for x in block.rows:
        o |= x; a &= x
    return o & ~a


class Influence:
    def __init__(self, m2: M.Model, cmap: dict, rho: dict):
        """m2: the hard-contracted model (full masks); cmap: m2 block id -> node id (cluster representative or itself); rho: node -> rho_i."""
        self.nodes = sorted(set(cmap.values()))
        self.rho = {n: Fr(rho.get(n, 0)) for n in self.nodes}
        vary = {b: varying_mask(blk) for b, blk in m2.blocks.items()}
        acc = {}                                                  # (a, b) -> exp(2L) product
        self.seams = {}
        for e in m2.edges:
            a, b = cmap[e.u], cmap[e.v]
            if a == b or e.r == 0:
                continue
            s = bin(vary[e.u] & vary[e.v] & e.mask).count("1")
            if s == 0:
                continue
            k = (min(a, b), max(a, b))
            if e.r >= 1:
                acc[k] = None                                     # hard seam between nodes: theta = 1
            elif acc.get(k, Fr(1)) is not None:
                acc[k] = acc.get(k, Fr(1)) * ((1 + e.r) / (1 - e.r)) ** s
            self.seams.setdefault(k, []).append({"edge": [e.u, e.v], "r": str(e.r), "s_orig": s})
        self.theta = {k: (Fr(1) if E is None else (E - 1) / (E + 1)) for k, E in acc.items()}
        self.adj = {n: {} for n in self.nodes}
        for (a, b), th in self.theta.items():
            self.adj[a][b] = th; self.adj[b][a] = th

    def components(self):
        seen = set(); out = []
        for n in self.nodes:
            if n in seen:
                continue
            stack = [n]; comp = []
            while stack:
                x = stack.pop()
                if x in seen:
                    continue
                seen.add(x); comp.append(x); stack.extend(self.adj[x])
            out.append(sorted(comp))
        return out

    def ball(self, q, radius):
        H = {q}; frontier = {q}
        for _ in range(radius):
            nxt = set()
            for v in frontier:
                nxt |= set(self.adj[v])
            frontier = nxt - H; H |= nxt
        return H

    def record(self):
        return {"nodes": self.nodes, "theta": {"%d-%d" % k: str(v) for k, v in self.theta.items()}, "seams": {"%d-%d" % k: v for k, v in self.seams.items()}, "rho": {str(k): str(v) for k, v in self.rho.items() if v > 0}}
