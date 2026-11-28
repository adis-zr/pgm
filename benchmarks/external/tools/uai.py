"""Lossless UAI model / evidence / MAR reader-writer for the external comparison.

Scope: ordinary input plumbing only. No model tailoring, no factor removal, no
zero softening, no quantization, no hand-designed decomposition.

Factor-table order is the UAI standard: the LAST variable in a factor's scope
varies fastest (row-major over the scope in declaration order).
"""
from __future__ import annotations
from fractions import Fraction as Fr
from dataclasses import dataclass, field
import re


@dataclass
class Factor:
    scope: tuple          # variable indices, declaration order
    card: tuple           # cardinalities aligned with scope
    table: list           # Fraction values, last-variable-fastest
    index: int = -1       # original position in the file

    def size(self):
        n = 1
        for c in self.card:
            n *= c
        return n

    def strides(self):
        """stride[k] = number of table entries per unit step of scope[k]."""
        st = [1] * len(self.card)
        acc = 1
        for k in range(len(self.card) - 1, -1, -1):
            st[k] = acc
            acc *= self.card[k]
        return tuple(st)

    def at(self, assign: dict):
        off = 0
        for k, v in enumerate(self.scope):
            off += assign[v] * self.strides()[k]
        return self.table[off]


@dataclass
class Model:
    net_type: str
    nvars: int
    card: list
    factors: list = field(default_factory=list)

    def check(self):
        assert self.net_type in ("MARKOV", "BAYES"), self.net_type
        assert len(self.card) == self.nvars
        for c in self.card:
            assert c >= 1
        for f in self.factors:
            assert len(f.scope) == len(f.card)
            for k, v in enumerate(f.scope):
                assert 0 <= v < self.nvars, (v, self.nvars)
                assert f.card[k] == self.card[v], ("card mismatch", v, f.card[k], self.card[v])
            assert len(f.table) == f.size(), ("table size", f.index, len(f.table), f.size())
            for t in f.table:
                assert t >= 0, ("negative factor entry", f.index)


def _tokens(text: str):
    # UAI is whitespace-delimited; tolerate arbitrary newlines/spacing.
    for t in text.split():
        yield t


def read_model(path: str) -> Model:
    with open(path, "r") as fh:
        text = fh.read()
    it = _tokens(text)
    net_type = next(it)
    nvars = int(next(it))
    card = [int(next(it)) for _ in range(nvars)]
    ncliques = int(next(it))
    scopes = []
    for _ in range(ncliques):
        k = int(next(it))
        sc = tuple(int(next(it)) for _ in range(k))
        scopes.append(sc)
    factors = []
    for i, sc in enumerate(scopes):
        n = int(next(it))
        cd = tuple(card[v] for v in sc)
        exp = 1
        for c in cd:
            exp *= c
        assert n == exp, ("declared table length != product of cardinalities", i, n, exp)
        tab = [Fr(next(it)) for _ in range(n)]
        factors.append(Factor(scope=sc, card=cd, table=tab, index=i))
    rest = list(it)
    assert not rest, ("trailing tokens in model file", rest[:5])
    m = Model(net_type=net_type, nvars=nvars, card=card, factors=factors)
    m.check()
    return m


def read_evidence(path: str) -> dict:
    """UAI evidence: '<count> <var> <val> ...' (possibly on one line)."""
    with open(path, "r") as fh:
        toks = fh.read().split()
    if not toks:
        return {}
    n = int(toks[0])
    rest = toks[1:]
    assert len(rest) == 2 * n, ("evidence token count", n, len(rest))
    ev = {}
    for i in range(n):
        v = int(rest[2 * i]); s = int(rest[2 * i + 1])
        assert v not in ev, ("duplicate evidence variable", v)
        ev[v] = s
    return ev


def read_mar(path: str):
    """Read a UAI MAR file. Returns (list-of-lists of Fraction, raw_decimal_strings).

    Files may carry a leading 'PR' block (archived Merlin outputs do); the MAR
    section is located by its own 'MAR' keyword.
    """
    with open(path, "r") as fh:
        toks = fh.read().split()
    try:
        k = toks.index("MAR")
    except ValueError:
        raise AssertionError("no MAR section in %s" % path)
    toks = toks[k + 1:]
    nvars = int(toks[0])
    pos = 1
    out, raw = [], []
    for _ in range(nvars):
        c = int(toks[pos]); pos += 1
        vals = toks[pos:pos + c]; pos += c
        assert len(vals) == c, "truncated MAR row"
        raw.append(list(vals))
        out.append([Fr(v) for v in vals])
    assert pos == len(toks), ("trailing tokens in MAR file", len(toks) - pos)
    return out, raw


def write_mar(path: str, rows, header_pr: str | None = None, fmt="%.6f"):
    """Write standard UAI MAR. rows is a list of per-variable float lists,
    INCLUDING observed variables as point masses (brief: original task fidelity)."""
    parts = []
    if header_pr is not None:
        parts.append("PR\n%s\n" % header_pr)
    parts.append("MAR\n")
    body = [str(len(rows))]
    for r in rows:
        body.append(str(len(r)))
        for v in r:
            body.append(fmt % v)
    parts.append(" ".join(body) + "\n")
    with open(path, "w") as fh:
        fh.write("".join(parts))


def restrict_evidence(model: Model, ev: dict):
    """Lossless evidence restriction: condition each factor on observed values.

    Returns (factors, kept_scope_map). Zeros are PRESERVED exactly; no softening.
    Variables are NOT renumbered -- the mapping to original indices is kept.
    """
    out = []
    for f in model.factors:
        obs = [(k, v) for k, v in enumerate(f.scope) if v in ev]
        if not obs:
            out.append(f)
            continue
        free_k = [k for k in range(len(f.scope)) if f.scope[k] not in ev]
        new_scope = tuple(f.scope[k] for k in free_k)
        new_card = tuple(f.card[k] for k in free_k)
        st = f.strides()
        base = 0
        for k, v in obs:
            s = ev[v]
            assert 0 <= s < f.card[k], ("evidence state out of domain", v, s, f.card[k])
            base += s * st[k]
        n = 1
        for c in new_card:
            n *= c
        tab = [None] * n
        # enumerate free assignments in the new (last-fastest) order
        nst = [1] * len(new_card)
        acc = 1
        for k in range(len(new_card) - 1, -1, -1):
            nst[k] = acc; acc *= new_card[k]
        for idx in range(n):
            off = base
            rem = idx
            for k in range(len(new_card)):
                d = rem // nst[k]; rem = rem % nst[k]
                off += d * st[free_k[k]]
            tab[idx] = f.table[off]
        out.append(Factor(scope=new_scope, card=new_card, table=tab, index=f.index))
    return out
