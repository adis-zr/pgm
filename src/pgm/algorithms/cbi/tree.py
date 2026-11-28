"""TREE_MESSAGE: message passing with enclosures on a forest (the reduced graph or a region graph), one operator per directed edge
(the same operator both ways unless the plan says otherwise). Prefix / suffix products give every excluded-neighbour cavity without
division. Root-only or all-block beliefs; coordinate events normalized by (B). Scales are dropped (positive scalars)."""
from __future__ import annotations
from fractions import Fraction as Fr
import numpy as np
from . import arith as A, transfer as T


def _key(a, b):
    return (min(a, b), max(a, b))


class TreeSolver:
    def __init__(self, blocks, edges, ops, log=None, deadline=None):
        """blocks: {id: Block}; edges: [Edge]; ops: {(min,max): op} with op = ("exact",) | ("sparse", h) | ("fourier", k)."""
        self.blocks = blocks; self.edges = {_key(e.u, e.v): e for e in edges}; self.ops = ops
        self.adj = {b: [] for b in blocks}
        for e in edges:
            self.adj[e.u].append(e.v); self.adj[e.v].append(e.u)
        self.msg = {}                 # (from, to) -> IVec over `to` rows
        self.minfo = {}
        self.weights = {b: A.IVec.exact(blk.w).normalize() for b, blk in blocks.items()}
        self.log = log if log is not None else []; self.deadline = deadline

    def _send(self, frm, to):
        if (frm, to) in self.msg:
            return self.msg[(frm, to)]
        cav = self.weights[frm]
        for w in self.adj[frm]:
            if w != to:
                cav = cav.mul(self._send(w, frm))
        e = self.edges[_key(frm, to)]; op = self.ops[_key(frm, to)]
        m, info = T.apply(op, cav, self.blocks[frm].rows, self.blocks[to].rows, e.mask, e.r, deadline=self.deadline)
        self.msg[(frm, to)] = m; self.minfo[(frm, to)] = {**info, "cavity_bits": cav.bits(), "msg_bits": m.bits()}
        return m

    def belief(self, v):
        """Root belief with an EXPLICIT post-order (no recursion): inward messages toward v in leaf-to-root order."""
        order = []; stack = [(v, None)]
        while stack:
            x, p = stack.pop(); order.append((x, p))
            for w in self.adj[x]:
                if w != p:
                    stack.append((w, x))
        for x, p in reversed(order):
            if p is not None and (x, p) not in self.msg:
                cav = self.weights[x]
                for w in self.adj[x]:
                    if w != p:
                        cav = cav.mul(self.msg[(w, x)])
                e = self.edges[_key(x, p)]; op = self.ops[_key(x, p)]
                m, info = T.apply(op, cav, self.blocks[x].rows, self.blocks[p].rows, e.mask, e.r, deadline=self.deadline)
                self.msg[(x, p)] = m; self.minfo[(x, p)] = {**info, "cavity_bits": cav.bits(), "msg_bits": m.bits()}
        b = self.weights[v]
        for w in self.adj[v]:
            b = b.mul(self.msg[(w, v)])
        return b

    def all_beliefs(self):
        """Two passes: root every component at its smallest block, send inward, then outward with prefix/suffix cavity products."""
        seen = set(); out = {}
        for root in sorted(self.blocks):
            if root in seen:
                continue
            order = []; stack = [(root, None)]
            while stack:
                x, p = stack.pop(); seen.add(x); order.append((x, p))
                for w in self.adj[x]:
                    if w != p:
                        stack.append((w, x))
            for x, p in reversed(order):            # inward
                if p is not None:
                    self._send(x, p)
            for x, p in order:                      # outward with prefix / suffix products
                nb = [w for w in self.adj[x]]
                inc = [self.msg[(w, x)] for w in nb]          # all incoming exist now (parent's outward message sent before x)
                n = len(nb)
                pre = [None] * (n + 1); pre[0] = self.weights[x]
                for i in range(n):
                    pre[i + 1] = pre[i].mul(inc[i])
                suf = [None] * (n + 1); suf[n] = A.ones(len(self.blocks[x].rows))
                for i in range(n - 1, -1, -1):
                    suf[i] = inc[i].mul(suf[i + 1])
                out[x] = pre[n]
                for i, w in enumerate(nb):
                    if (x, w) not in self.msg:
                        cav = pre[i].mul(suf[i + 1])
                        e = self.edges[_key(x, w)]; op = self.ops[_key(x, w)]
                        m, info = T.apply(op, cav, self.blocks[x].rows, self.blocks[w].rows, e.mask, e.r, deadline=self.deadline)
                        self.msg[(x, w)] = m; self.minfo[(x, w)] = {**info, "cavity_bits": cav.bits(), "msg_bits": m.bits()}
        return out


def coordinate_intervals(belief, rows, d):
    """For every coordinate j: enclosure of P(x_j = +1) from the belief enclosure by (B)."""
    R = np.asarray(rows, dtype=np.uint64); out = []
    for j in range(d):
        sel = ((R >> np.uint64(j)) & np.uint64(1)).astype(bool)
        LA, UA = belief.masked_mass(sel); LC, UC = belief.masked_mass(~sel)
        out.append(A.normalize_event(LA, UA, LC, UC))
    return out
