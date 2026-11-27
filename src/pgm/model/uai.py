"""The canonical EXACT UAI reader and the request-local bound model.

``read_uai`` is the retained exact parser, defined ONCE here: ``pgm.algorithms.structural.core.read_uai`` is this
function (the former duplicate body was removed in the step-1 repair pass), so the public worker, the accepted engine
(``blockres.core.read_uai``) and the inherited direct entrypoints (quotient / response CLIs) all read through it: exact ``Fraction`` factor values, hard zeros and tiny rationals preserved,
validated scopes (distinct in-range variables, table length = product of cardinalities), observed variables from
the adjacent ``.evid`` file (a missing file is the canonical byte string ``b'0'``), and the binding = SHA-256 of the
exact model and evidence bytes.  ``load_bound`` parses ONCE per worker, checks the binding against the controller's
expectation (source identity across the process boundary) and fixes the ORIGINAL query inventory before any
backend can refuse.  Parsing is charged to the request like every other work (it happens inside the attempt's
deadline and memory supervision).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from fractions import Fraction as F
import hashlib
import math
from pathlib import Path


class SourceRefused(Exception):
    """A typed refusal of the input itself (kind: INVALID_TASK | BINDING | MEMORY)."""

    def __init__(self, kind: str, reason: str, bound=None):
        self.kind, self.reason, self.bound = kind, reason, bound          # `bound`: the parsed model when the source itself was valid (BINDING), so the refusal still reports the original inventory
        super().__init__(reason)


def read_uai(path):
    """Exact UAI model + binding (the retained reader, byte-for-byte semantics of newarm core.read_uai)."""
    raw = Path(path).read_bytes(); epath = Path(str(path) + '.evid')
    eb = epath.read_bytes() if epath.exists() else b'0'
    ts = iter(raw.decode().split()); kind = next(ts); assert kind in ('MARKOV', 'BAYES')
    n = int(next(ts)); cards = [int(next(ts)) for _ in range(n)]; assert all(d > 0 for d in cards)
    scopes = [tuple(int(next(ts)) for _ in range(int(next(ts)))) for _ in range(int(next(ts)))]
    factors = []
    for s in scopes:
        assert len(s) == len(set(s)) and all(0 <= v < n for v in s)
        k = int(next(ts)); assert k == math.prod(cards[v] for v in s)
        vs = [F(next(ts)) for _ in range(k)]; assert all(v >= 0 for v in vs)
        factors.append(dict(scope=s, values=vs))
    assert next(ts, None) is None
    es = iter(map(int, eb.split())); k = next(es); evidence = {}
    for _ in range(k):
        v, a = next(es), next(es); assert 0 <= v < n and 0 <= a < cards[v] and v not in evidence; evidence[v] = a
    assert next(es, None) is None
    return dict(cards=cards, factors=factors, evidence=evidence), dict(model_sha256=hashlib.sha256(raw).hexdigest(), evidence_sha256=hashlib.sha256(eb).hexdigest())


def original_inventory(model, observed=False):
    """the ORIGINAL singleton coordinates: every state of every nonobserved variable (observed=True adds the observed variables' states)"""
    ev = model.get('evidence', {})
    return [(v, a) for v, card in enumerate(model['cards']) if observed or v not in ev for a in range(card)]


@dataclass(frozen=True)
class BoundModel:
    """the request-local validated input: exact model, binding, original inventories"""
    path: Path
    model: dict = field(repr=False)
    binding: dict
    inventory: list                 # nonobserved original coordinates (the modern backend convention)
    all_inventory: list             # every original coordinate incl. observed variables

    @property
    def cards(self): return self.model['cards']

    @property
    def evidence(self): return self.model['evidence']


def load_bound(path, expected_binding=None, memory_bytes=None):
    """Parse exactly once; refuse a binding that differs from the controller's expectation; fix the inventory first."""
    path = Path(path)
    if memory_bytes is not None:
        try:
            size = path.stat().st_size
        except OSError as e:
            raise SourceRefused('INVALID_TASK', 'cannot read %s: %s' % (path.name, e)) from e
        # the exact reader materializes every token (bytes -> str -> list -> Fractions): refuse before reading a source the request cannot hold
        if size * 12 > memory_bytes:
            raise SourceRefused('MEMORY', 'source bytes %d exceed the attempt memory allowance for exact parsing' % size)
    try:
        model, binding = read_uai(path)
    except (AssertionError, ValueError, StopIteration, UnicodeDecodeError, ZeroDivisionError) as e:
        raise SourceRefused('INVALID_TASK', 'invalid UAI source: %s' % (str(e)[:200] or type(e).__name__)) from e
    except OSError as e:
        raise SourceRefused('INVALID_TASK', 'cannot read %s: %s' % (path.name, e)) from e
    if memory_bytes is not None and sum(model['cards']) * 256 > memory_bytes:
        raise SourceRefused('MEMORY', 'original query inventory exceeds memory allowance')
    bound = BoundModel(path=path, model=model, binding=binding, inventory=original_inventory(model), all_inventory=original_inventory(model, observed=True))
    if expected_binding is not None and dict(expected_binding) != binding:
        raise SourceRefused('BINDING', 'source identity differs from the controller binding (model %s vs %s; evidence %s vs %s)' % (binding['model_sha256'][:12], str(expected_binding.get('model_sha256'))[:12], binding['evidence_sha256'][:12], str(expected_binding.get('evidence_sha256'))[:12]), bound=bound)
    return bound
