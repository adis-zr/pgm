"""Model-driven inference engine: model representation and exact input semantics.

Spec sections 1 and "Exponent safety and zero support". A finite nonnegative
factor graph with exact rational entries. H4 is a model PROVIDER here, not the
constructor that defines the system.
"""
from __future__ import annotations
import sys
sys.set_int_max_str_digits(0)
from fractions import Fraction as Fr
from dataclasses import dataclass, field
import re

# A decimal exponent beyond this triggers a typed range refusal rather than
# materializing an unbounded integer during parsing (spec: exponent safety).
MAX_DECIMAL_EXP = 100000


class InvalidModel(ValueError):
    """Malformed or invalid input. Distinct from a resource limitation."""


class InputRangeRefusal(ValueError):
    """Valid-looking token whose magnitude exceeds the typed input range."""


_NUM = re.compile(r"^[+-]?(\d+\.?\d*|\.\d+)([eE][+-]?\d+)?$")


def exact_decimal(tok: str) -> Fr:
    """Parse a decimal / scientific token as an EXACT decimal rational.

    No intervening binary64 conversion: Fr(float(tok)) would already be wrong.
    """
    if not _NUM.match(tok):
        raise InvalidModel("malformed numeric token %r" % tok)
    s = tok.strip()
    mant, _, exp = s.partition("e") if "e" in s else s.partition("E")
    e = int(exp) if exp else 0
    if abs(e) > MAX_DECIMAL_EXP:
        raise InputRangeRefusal("decimal exponent %d exceeds typed input range %d"
                                % (e, MAX_DECIMAL_EXP))
    if "." in mant:
        ip, _, fp = mant.partition(".")
        digits = (ip or "0") + fp
        e -= len(fp)
    else:
        digits = mant
    neg = digits.startswith("-")
    if digits and digits[0] in "+-":
        digits = digits[1:]
    if not digits:
        raise InvalidModel("malformed numeric token %r" % tok)
    v = Fr(int(digits))
    if e > 0:
        v *= Fr(10) ** e
    elif e < 0:
        v /= Fr(10) ** (-e)
    return -v if neg else v


@dataclass
class Factor:
    """A nonnegative table over `scope`. The FIRST variable in the scope is the
    MOST SIGNIFICANT table index (UAI convention), i.e. the last varies fastest."""
    scope: tuple
    card: tuple
    table: list                     # Fraction, nonnegative
    origin: int = -1                # original file position
    scale: Fr = Fr(1)               # exact removed positive constant (cancels)

    def size(self) -> int:
        n = 1
        for c in self.card:
            n *= c
        return n

    def strides(self) -> tuple:
        st = [1] * len(self.card)
        acc = 1
        for k in range(len(self.card) - 1, -1, -1):
            st[k] = acc
            acc *= self.card[k]
        return tuple(st)

    def at(self, assign: dict) -> Fr:
        st = self.strides()
        off = 0
        for k, v in enumerate(self.scope):
            off += assign[v] * st[k]
        return self.table[off]


@dataclass
class Model:
    """Variable IDs are 0..nvars-1 with cardinalities `card`."""
    nvars: int
    card: list
    factors: list = field(default_factory=list)
    net_type: str = "MARKOV"
    provenance: dict = field(default_factory=dict)

    def validate(self):
        if self.nvars < 1:
            raise InvalidModel("nvars=%d" % self.nvars)
        if len(self.card) != self.nvars:
            raise InvalidModel("cardinality list length %d != nvars %d"
                               % (len(self.card), self.nvars))
        for v, c in enumerate(self.card):
            if not isinstance(c, int) or c < 1:
                raise InvalidModel("variable %d has cardinality %r" % (v, c))
        for f in self.factors:
            if len(f.scope) != len(f.card):
                raise InvalidModel("factor %d scope/card length mismatch" % f.origin)
            if len(set(f.scope)) != len(f.scope):
                raise InvalidModel("factor %d has a duplicate variable in its scope: %s"
                                   % (f.origin, f.scope))
            for k, v in enumerate(f.scope):
                if not (0 <= v < self.nvars):
                    raise InvalidModel("factor %d references variable %d, nvars=%d"
                                       % (f.origin, v, self.nvars))
                if f.card[k] != self.card[v]:
                    raise InvalidModel("factor %d: card %d for variable %d, model says %d"
                                       % (f.origin, f.card[k], v, self.card[v]))
            if len(f.table) != f.size():
                raise InvalidModel("factor %d: table length %d != domain product %d"
                                   % (f.origin, len(f.table), f.size()))
            for t in f.table:
                if t < 0:
                    raise InvalidModel("factor %d has a negative entry %s" % (f.origin, t))
        return self

    # ---- statistics used by the planner and the arithmetic bounds ----
    def zero_count(self) -> int:
        return sum(1 for f in self.factors for t in f.table if t == 0)

    def arity_profile(self) -> dict:
        d = {}
        for f in self.factors:
            d[len(f.scope)] = d.get(len(f.scope), 0) + 1
        return dict(sorted(d.items()))


def read_uai(path: str) -> Model:
    """Read a UAI model file with exact decimal semantics."""
    with open(path, "r") as fh:
        toks = fh.read().split()
    i = 0

    def nxt():
        nonlocal i
        if i >= len(toks):
            raise InvalidModel("unexpected end of model file")
        t = toks[i]; i += 1
        return t

    net_type = nxt()
    if net_type not in ("MARKOV", "BAYES"):
        raise InvalidModel("unknown network type %r" % net_type)
    nvars = int(nxt())
    card = [int(nxt()) for _ in range(nvars)]
    ncliques = int(nxt())
    scopes = []
    for _ in range(ncliques):
        k = int(nxt())
        if k < 1:
            raise InvalidModel("factor with arity %d" % k)
        scopes.append(tuple(int(nxt()) for _ in range(k)))
    factors = []
    for j, sc in enumerate(scopes):
        n = int(nxt())
        cd = tuple(card[v] for v in sc) if all(0 <= v < nvars for v in sc) else None
        if cd is None:
            raise InvalidModel("factor %d references an out-of-range variable: %s" % (j, sc))
        exp = 1
        for c in cd:
            exp *= c
        if n != exp:
            raise InvalidModel("factor %d declares %d entries, domain product is %d"
                               % (j, n, exp))
        factors.append(Factor(scope=sc, card=cd,
                              table=[exact_decimal(nxt()) for _ in range(n)], origin=j))
    if i != len(toks):
        raise InvalidModel("%d trailing tokens in model file" % (len(toks) - i))
    m = Model(nvars=nvars, card=card, factors=factors, net_type=net_type,
              provenance={"path": path, "declared_cliques": ncliques})
    return m.validate()


def read_evidence(path: str, model: Model | None = None) -> dict:
    with open(path, "r") as fh:
        toks = fh.read().split()
    if not toks:
        return {}
    n = int(toks[0])
    rest = toks[1:]
    if len(rest) != 2 * n:
        raise InvalidModel("evidence declares %d pairs but has %d tokens" % (n, len(rest)))
    ev = {}
    for k in range(n):
        v, s = int(rest[2 * k]), int(rest[2 * k + 1])
        if v in ev:
            raise InvalidModel("duplicate evidence variable %d" % v)
        if model is not None:
            if not (0 <= v < model.nvars):
                raise InvalidModel("evidence variable %d out of range (nvars=%d)"
                                   % (v, model.nvars))
            if not (0 <= s < model.card[v]):
                raise InvalidModel("evidence state %d out of domain for variable %d (card %d)"
                                   % (s, v, model.card[v]))
        ev[v] = s
    return ev


@dataclass
class Restricted:
    """Evidence-restricted model. Original variable/state mappings are retained."""
    model: Model
    evidence: dict
    factors: list                 # restricted factors over FREE variables
    free: list                    # sorted free original variable IDs
    card: dict                    # original var -> cardinality (free only)
    constant: Fr                  # product of fully-pinned factor values
    impossible_factor: int | None # origin of a factor that restricted to all-zero

    def free_domain_product(self) -> int:
        q = 1
        for v in self.free:
            q *= self.card[v]
        return q


def restrict(model: Model, ev: dict) -> Restricted:
    """Condition every factor on the evidence, indexing the ORIGINAL table before
    deleting pinned coordinates. Hard zeros are preserved exactly."""
    for v, s in ev.items():
        if not (0 <= v < model.nvars):
            raise InvalidModel("evidence variable %d out of range" % v)
        if not (0 <= s < model.card[v]):
            raise InvalidModel("evidence state %d invalid for variable %d" % (s, v))
    free = [v for v in range(model.nvars) if v not in ev]
    card = {v: model.card[v] for v in free}
    out, const, imp = [], Fr(1), None
    for f in model.factors:
        st = f.strides()
        keep = [k for k in range(len(f.scope)) if f.scope[k] not in ev]
        base = 0
        for k, v in enumerate(f.scope):
            if v in ev:
                base += ev[v] * st[k]
        if not keep:
            val = f.table[base]
            if val == 0:
                imp = f.origin if imp is None else imp
            const *= val
            continue
        nsc = tuple(f.scope[k] for k in keep)
        ncd = tuple(f.card[k] for k in keep)
        n = 1
        for c in ncd:
            n *= c
        nst = [1] * len(ncd)
        acc = 1
        for k in range(len(ncd) - 1, -1, -1):
            nst[k] = acc; acc *= ncd[k]
        tab = [None] * n
        for idx in range(n):
            off, rem = base, idx
            for k in range(len(ncd)):
                d, rem = divmod(rem, nst[k])
                off += d * st[keep[k]]
            tab[idx] = f.table[off]
        if all(t == 0 for t in tab):
            imp = f.origin if imp is None else imp
        out.append(Factor(scope=nsc, card=ncd, table=tab, origin=f.origin))
    return Restricted(model=model, evidence=dict(ev), factors=out, free=free,
                      card=card, constant=const, impossible_factor=imp)
