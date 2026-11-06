"""Deterministic instance families (SHA-256 counter streams; exact integer draws) for conformance and the experiment: chain, branching
tree, cycle, ladder, open mesh (weak), strong-island mesh (Part I §7: 2p x 2q blocks, 2x2 islands with >= `common` shared rows,
internal r_int, seam r_seam), and the near-hard cyclic island with leaves. Supports are asymmetric (independent draws per block) with
nonuniform positive integer weights; no antipodality anywhere."""
from __future__ import annotations
from fractions import Fraction as Fr
import hashlib


class Stream:
    def __init__(self, tag):
        self.tag = tag; self.ctr = 0; self.buf = 0; self.nbits = 0

    def bits(self, k):
        out = 0
        for _ in range(k):
            if self.nbits == 0:
                self.buf = int.from_bytes(hashlib.sha256(("%s|%d" % (self.tag, self.ctr)).encode()).digest(), "big"); self.ctr += 1; self.nbits = 256
            self.nbits -= 1; out = (out << 1) | ((self.buf >> self.nbits) & 1)
        return out

    def below(self, n):
        """Uniform integer in [0, n) by rejection (exact)."""
        k = max(1, (n - 1).bit_length())
        while True:
            x = self.bits(k)
            if x < n:
                return x


def support(stream, d, m, must_include=()):
    rows = set(must_include)
    while len(rows) < m:
        rows.add(stream.bits(d))
    rows = sorted(rows)
    return rows, [1 + stream.below(9) for _ in rows]


def _blocks(name, d, ids, m, seed, common_groups=None):
    """common_groups: {group_key: [ids]} -> every block of a group includes the group's `common` rows."""
    blocks = {}; commons = {}
    if common_groups:
        for g, (members, k) in common_groups.items():
            cs = Stream("%s|common|%s|%d" % (name, g, seed)); commons[g] = set()
            while len(commons[g]) < k:
                commons[g].add(cs.bits(d))
    for b in ids:
        inc = set()
        if common_groups:
            for g, (members, k) in common_groups.items():
                if b in members:
                    inc |= commons[g]
        rows, w = support(Stream("%s|block|%d|%d" % (name, b, seed)), d, m, inc)
        blocks[b] = {"id": b, "rows": rows, "weights": w}
    return blocks


def chain(n, d, m, couplings, seed, name="chain"):
    blocks = _blocks(name, d, range(n), m, seed)
    edges = [{"u": i, "v": i + 1, "r": str(Fr(couplings[i % len(couplings)]))} for i in range(n - 1)]
    return {"d": d, "blocks": list(blocks.values()), "edges": edges, "meta": {"family": name, "n": n, "m": m, "seed": seed}}


def tree(n, d, m, couplings, seed, name="tree"):
    """Branching tree: block i (i >= 1) attaches to parent (i-1)//2 (binary heap shape)."""
    blocks = _blocks(name, d, range(n), m, seed)
    edges = [{"u": (i - 1) // 2, "v": i, "r": str(Fr(couplings[i % len(couplings)]))} for i in range(1, n)]
    return {"d": d, "blocks": list(blocks.values()), "edges": edges, "meta": {"family": name, "n": n, "m": m, "seed": seed}}


def cycle(n, d, m, r, seed, name="cycle", leaves=0, r_leaf=None):
    blocks = _blocks(name, d, range(n + leaves), m, seed)
    edges = [{"u": i, "v": (i + 1) % n, "r": str(Fr(r))} for i in range(n)]
    for k in range(leaves):
        edges.append({"u": k % n, "v": n + k, "r": str(Fr(r_leaf))})
    return {"d": d, "blocks": list(blocks.values()), "edges": edges, "meta": {"family": name, "n": n, "m": m, "seed": seed}}


def mesh(p, q, d, m, r, seed, name="mesh", periodic=False):
    ids = list(range(p * q)); blocks = _blocks(name, d, ids, m, seed); edges = []
    for i in range(p):
        for j in range(q):
            b = i * q + j
            if j + 1 < q or periodic:
                edges.append({"u": b, "v": i * q + (j + 1) % q, "r": str(Fr(r))})
            if i + 1 < p or periodic:
                edges.append({"u": b, "v": ((i + 1) % p) * q + j, "r": str(Fr(r))})
    return {"d": d, "blocks": list(blocks.values()), "edges": edges, "meta": {"family": name, "p": p, "q": q, "m": m, "seed": seed, "periodic": periodic}}


def island_mesh(p2, q2, d, m, common, r_int, r_seam, seed, name="island_mesh", hints=True):
    """2p x 2q mesh of blocks partitioned into 2x2 islands (block (i,j) belongs to island (i//2, j//2)); island internal edges r_int,
    seam edges r_seam; every island's four supports share >= `common` rows (drawn per island)."""
    p, q = p2 * 2, q2 * 2; ids = list(range(p * q))
    groups = {}
    for i in range(p):
        for j in range(q):
            groups.setdefault("%d_%d" % (i // 2, j // 2), [[], common])[0].append(i * q + j)
    blocks = _blocks(name, d, ids, m, seed, {g: (mem, k) for g, (mem, k) in groups.items()})
    edges = []
    for i in range(p):
        for j in range(q):
            b = i * q + j
            if j + 1 < q:
                edges.append({"u": b, "v": b + 1, "r": str(Fr(r_int if (j // 2) == ((j + 1) // 2) else r_seam))})
            if i + 1 < p:
                edges.append({"u": b, "v": b + q, "r": str(Fr(r_int if (i // 2) == ((i + 1) // 2) else r_seam))})
    meta = {"family": name, "p": p, "q": q, "m": m, "common": common, "r_int": str(Fr(r_int)), "r_seam": str(Fr(r_seam)), "seed": seed}
    if hints:
        meta["cluster_hints"] = [sorted(mem) for mem, k in groups.values()]
    return {"d": d, "blocks": list(blocks.values()), "edges": edges, "meta": meta}
