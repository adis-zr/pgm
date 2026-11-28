"""Bounded, read-only structural inspection for the public switchboard.

The inspector never constructs an inference model or normalizes a factor. Its
facts can screen a backend; the backend still checks its own applicability.
Numeric tokens are validated lexically, so a positive tiny decimal is never
mistaken for zero because of a floating-point conversion.
"""
from __future__ import annotations

import hashlib
import math
from pathlib import Path
import re
import time


class PlanningRefused(Exception):
    """A typed inspection failure, retaining the inventory when available."""

    def __init__(self, kind, reason, inventory=None, metadata=None):
        self.kind = kind
        self.reason = reason
        self.inventory = inventory if inventory is not None else []
        self.metadata = metadata if metadata is not None else {}
        super().__init__(f"{kind}: {reason}")


_WORDS = re.compile(rb"\S+")
_INT = re.compile(rb"[+]?[0-9]+\Z")
_SIGNED_INT = re.compile(rb"[+-]?[0-9]+\Z")
_DECIMAL = re.compile(rb"[+-]?(?:[0-9]+(?:\.[0-9]*)?|\.[0-9]+)(?:[eE][+-]?[0-9]+)?\Z")
_SPACE = b" \t\r\n\v\f"


class _Context:
    def __init__(self, deadline, memory_bytes):
        self.deadline = deadline
        self.cap = memory_bytes
        self.used = 0
        self.meta = {}
        self.inventory = []

    def fail(self, kind, reason):
        raise PlanningRefused(kind, reason, self.inventory, self.meta)

    def poll(self, stage, deadline=None):
        if time.monotonic() >= (self.deadline if deadline is None else deadline):
            self.fail("DEADLINE", stage)

    def charge(self, amount, stage):
        if amount < 0 or amount > self.cap - self.used:
            self.fail("MEMORY", f"{stage}: {amount} bytes against {self.cap-self.used} remaining")
        self.used += amount


class _Tokens:
    def __init__(self, path, context):
        self.path = Path(path)
        self.context = context
        self.chunk_size = min(65536, max(128, context.cap // 128))
        self.max_token_chars = min(65536, max(128, context.cap // 64))
        self.digest = hashlib.sha256()
        self.bytes_read = 0
        self._iterator = self._tokens()

    def _tokens(self):
        carry = b""
        try:
            with self.path.open("rb") as stream:
                while True:
                    self.context.poll("while reading source bytes")
                    block = stream.read(self.chunk_size)
                    if not block:
                        if carry:
                            yield carry
                        return
                    self.digest.update(block)
                    self.bytes_read += len(block)
                    data = carry + block
                    carry = b""
                    for match in _WORDS.finditer(data):
                        token = match.group()
                        if len(token) > self.max_token_chars:
                            self.context.fail("BITS", "numeric/source token exceeds admitted character count")
                        if match.end() == len(data) and data[-1:] not in _SPACE:
                            carry = token
                            break
                        yield token
        except OSError as exc:
            self.context.fail("INVALID_TASK", f"cannot read {self.path.name}: {exc}")

    def next(self, what):
        self.context.poll("while parsing " + what)
        try:
            return next(self._iterator)
        except StopIteration:
            self.context.fail("INVALID_TASK", "truncated " + what)

    def integer(self, what, limit=None):
        token = self.next(what)
        if not _INT.fullmatch(token):
            self.context.fail("INVALID_TASK", "invalid integer for " + what)
        significant = token.lstrip(b"+0") or b"0"
        if len(significant) > 19:
            self.context.fail("BITS", "integer exceeds 63-bit inspection domain: " + what)
        value = int(significant)
        if value > (1 << 63) - 1:
            self.context.fail("BITS", "integer exceeds 63-bit inspection domain: " + what)
        if limit is not None and value > limit:
            self.context.fail("INVALID_TASK", "out-of-range " + what)
        return value

    def finish(self):
        self.context.poll("at source end")
        if next(self._iterator, None) is not None:
            self.context.fail("INVALID_TASK", "unexpected trailing source token")


def _number(token, context):
    """Return (exactly_zero, conservative numerator+denominator bit estimate)."""
    if token.isdigit():
        # Most external factor tables contain many literal 0/1 entries.
        # Their lexical validation and the SAME conservative payload estimate
        # need no regular expression, exponent split or decimal reconstruction.
        zero = not token.strip(b"0")
        negative = False
        bits = 4 * (len(token) + 1)
    elif b"/" in token:
        parts = token.split(b"/")
        if len(parts) != 2 or not all(_SIGNED_INT.fullmatch(p) for p in parts):
            context.fail("INVALID_TASK", "invalid rational factor value")
        numerator, denominator = parts
        num = numerator.lstrip(b"+-0")
        den = denominator.lstrip(b"+-0")
        if not den:
            context.fail("INVALID_TASK", "zero rational denominator")
        negative = numerator.startswith(b"-") != denominator.startswith(b"-")
        zero = not num
        bits = 4 * (max(1, len(num)) + len(den))
    else:
        if not _DECIMAL.fullmatch(token):
            context.fail("INVALID_TASK", "invalid decimal factor value")
        # Decimal points without exponents do not require case folding or
        # exponent parsing.  The regex above still defines the accepted grammar.
        if b"e" in token or b"E" in token:
            mantissa, separator, exponent = token.lower().partition(b"e")
        else:
            mantissa, separator, exponent = token, b"", b""
        exponent_value = 0
        if separator:
            significant = exponent.lstrip(b"+-0") or b"0"
            if len(significant) > 9:
                context.fail("BITS", "decimal exponent exceeds admitted rational bit estimate")
            exponent_value = int(significant) * (-1 if exponent.startswith(b"-") else 1)
        digits = mantissa.lstrip(b"+-").replace(b".", b"")
        zero = not digits.strip(b"0")
        negative = mantissa.startswith(b"-")
        fractional_digits = len(mantissa.partition(b".")[2])
        bits = 4 * (max(1, len(digits)) + abs(exponent_value - fractional_digits) + 1)
    if negative and not zero:
        context.fail("INVALID_TASK", "negative factor value")
    if bits > min(1 << 20, max(128, context.cap // 16)):
        context.fail("BITS", "factor value exceeds admitted rational bit estimate")
    return zero, bits


def _evidence(path, explicit, cards, context):
    if not explicit and not path.exists():
        return {}, hashlib.sha256(b"0").hexdigest(), 0
    tokens = _Tokens(path, context)
    count = tokens.integer("evidence count", len(cards))
    context.charge(count * 112, "evidence map")
    evidence = {}
    for _ in range(count):
        variable = tokens.integer("evidence variable", len(cards)-1)
        state = tokens.integer("evidence state", cards[variable]-1)
        if variable in evidence:
            context.fail("INVALID_TASK", "duplicate evidence variable")
        evidence[variable] = state
    tokens.finish()
    return evidence, tokens.digest.hexdigest(), tokens.bytes_read


def _structure(cards, evidence, scopes, source_entries, context):
    n = len(cards)
    context.charge(n * 512 + 128, "structural graph vertices and union-find")
    parent = list(range(n))
    sizes = [1] * n

    def find(v):
        while parent[v] != v:
            parent[v] = parent[parent[v]]
            v = parent[v]
        return v

    def union(u, v):
        u, v = find(u), find(v)
        if u == v:
            return False
        if sizes[u] < sizes[v]:
            u, v = v, u
        parent[v] = u
        sizes[u] += sizes[v]
        return True

    factor_forest = True
    pairwise = all(len(scope) <= 2 for scope in scopes)
    edges = set()
    for scope in scopes:
        context.poll("while inspecting factor graph")
        if len(scope) > 1:
            for v in scope[1:]:
                if not union(scope[0], v):
                    factor_forest = False
        if pairwise and len(scope) == 2:
            edge = (min(scope), max(scope))
            if edge not in edges:
                context.charge(192, "unique pair edge and adjacency")
                edges.add(edge)
    free = []
    for v in range(n):
        if (v & 255) == 0:
            context.poll("while listing free variables")
        if v not in evidence:
            free.append(v)
    groups = {}
    for v in free:
        if (v & 255) == 0:
            context.poll("while grouping components")
        groups.setdefault(find(v), []).append(v)
    result = dict(forest_factor_graph=factor_forest, pairwise_forest=False,
                  effective_pairwise=pairwise, component_sizes=[len(g) for g in groups.values()],
                  binary_pairwise=False, binary_pairwise_bipartite=False, bipartition_sizes=[], stream_work=None,
                  stream_native_admissible=False)
    if not pairwise:
        return result
    adjacency = {v: [] for v in free}
    for edge_index, (u, v) in enumerate(edges):
        if (edge_index & 255) == 0:
            context.poll("while building pair adjacency")
        adjacency[u].append(v)
        adjacency[v].append(u)
    result["simple_edges"] = len(edges)
    result["pairwise_forest"] = len(edges) == len(free) - len(groups)
    if any(cards[v] != 2 for v in free):
        return result
    result["binary_pairwise"] = True
    colors = {}
    pairs = []
    valid = True
    work = source_entries
    native_memory = 0
    event_max = 0
    native_ok = True
    for start in free:
        if start in colors:
            continue
        colors[start] = 0
        stack = [start]
        counts = [0, 0]
        while stack:
            context.poll("while checking bipartiteness")
            v = stack.pop()
            counts[colors[v]] += 1
            for w in adjacency[v]:
                if w not in colors:
                    colors[w] = 1 - colors[v]
                    stack.append(w)
                elif colors[w] == colors[v]:
                    valid = False
        m, k = sorted(counts)
        pairs.append([m, k])
        if m > 62:
            native_ok = False
            work = None
            continue
        if work is not None:
            work += (1 << m) * (8 * (m + k) + 4)
        treebase = 1 << m.bit_length()
        event = (2*k+1)*(2*treebase) + (1 << m)*((2*k+1)*(treebase.bit_length()+1)+8*k+2*m+8)
        memory = 2*k*(2*treebase*16+128) + 4*m*k*8 + 256*(m+k+1)
        event_max = max(event_max, event)
        native_memory = max(native_memory, memory)
        native_ok &= (k <= 2**28 and m*k <= ((1 << 31)-1)//4 and event < 1 << 64
                      and memory <= min(512 << 20, context.cap))
    result.update(binary_pairwise_bipartite=valid, bipartition_sizes=pairs,
                  stream_work=work if valid else None,
                  stream_native_admissible=bool(valid and native_ok),
                  stream_native_memory_bytes=native_memory,
                  stream_native_event_bound=event_max)
    return result


def _forecast(cards, evidence, scopes, source_entries, context, deadline):
    """Optional guarded min-product order; estimates are not correctness facts."""
    context.poll("before optional physical forecast", deadline)
    free = [v for v in range(len(cards)) if v not in evidence]
    context.charge(len(free) * 256, "optional primal graph vertices")
    adj = {v: set() for v in free}
    for scope in scopes:
        context.poll("optional source cliques", deadline)
        for u in scope:
            context.poll("optional source clique row", deadline)
            for v in scope:
                if u != v and v not in adj[u]:
                    context.charge(64, "optional primal graph edge")
                    adj[u].add(v)
    order, sp, so, mp, mo = [], 0, 0, 0, 0
    while adj:
        best = None
        for v, neighbors in adj.items():
            context.poll("optional order candidate", deadline)
            volume = cards[v]
            for u in neighbors:
                volume *= cards[u]
                if volume > (1 << 63)-1:
                    context.fail("FORECAST", "physical volume exceeds 63-bit inspection forecast")
            candidate = (volume, v)
            if best is None or candidate < best:
                best = candidate
        product, v = best
        out = product // cards[v]
        sp += product; so += out; mp = max(mp, product); mo = max(mo, out)
        neighbors = adj[v]
        for u in neighbors:
            context.poll("optional fill admission", deadline)
            for w in neighbors:
                if u != w and w not in adj[u]:
                    context.charge(64, "optional fill edge")
                    adj[u].add(w)
            adj[u].discard(v)
        del adj[v]
        order.append(v)
    states = sum(cards[v] for v in free)
    # Same physical payload expression as the existing HP forecast, documented
    # here without importing its native/scipy stack. This is an estimate only.
    estimated_bytes = 10 * (so + source_entries + 2*mo + 2*mp) + (64 << 20) + 1200*states
    return dict(order=order, sum_product=sp, max_product=mp, sum_output=so,
                max_output=mo, source_entries=source_entries, states=states,
                native_bytes_estimate=estimated_bytes,
                note="scope-only min-product forecast; not a support-size or runtime certificate")


def inspect_model(path, evidence_path=None, *, deadline=math.inf, memory_bytes=3 << 30, forecast=True):
    """Inspect a UAI model without constructing its rational factor tables.

    Missing implicit evidence is the canonical byte string ``b'0'``. Explicit
    evidence paths must exist. ``inventory`` includes observed coordinates;
    ``unobserved_inventory`` matches the existing modern backend convention.
    Optional forecast failure is recorded and does not reject a valid input.
    ``forecast=False`` skips the optional min-product physical forecast (a
    policy that never uses it does not pay for it); the structural facts and
    the binding are unaffected.
    """
    if isinstance(memory_bytes, bool) or not isinstance(memory_bytes, int) or memory_bytes <= 0:
        raise PlanningRefused("INVALID_TASK", "memory_bytes must be a positive integer")
    if deadline is None:
        deadline = math.inf
    if isinstance(deadline, bool) or not isinstance(deadline, (int, float)) or math.isnan(deadline):
        raise PlanningRefused("INVALID_TASK", "deadline must be an absolute monotonic timestamp")
    context = _Context(deadline, memory_bytes)
    started = time.monotonic()
    context.poll("inspection entry")
    context.charge(16384 + min(65536, max(128, memory_bytes//128))*6,
                   "streamed parser buffers")
    tokens = _Tokens(path, context)
    kind = tokens.next("UAI kind")
    if kind not in (b"BAYES", b"MARKOV"):
        context.fail("INVALID_TASK", "UAI kind must be BAYES or MARKOV")
    n = tokens.integer("variable count")
    context.charge(n * 64, "cardinality array")
    cards = []
    for _ in range(n):
        card = tokens.integer("cardinality")
        if card < 1:
            context.fail("INVALID_TASK", "cardinality must be positive")
        cards.append(card)
    context.meta.update(kind=kind.decode("ascii"), source_kind=kind.decode("ascii"),
                        cards=cards, max_cardinality=max(cards, default=0), maxcard=max(cards, default=0))
    evidence_file = Path(evidence_path) if evidence_path is not None else Path(str(path)+".evid")
    evidence, evidence_hash, evidence_bytes = _evidence(evidence_file, evidence_path is not None, cards, context)
    context.meta["evidence"] = evidence
    coordinate_count = sum(cards)
    context.charge(coordinate_count * 144, "original coordinate inventory")
    inventory = context.inventory
    unobserved = []
    for v, card in enumerate(cards):
        for a in range(card):
            if (a & 255) == 0:
                context.poll("while constructing original query inventory")
            q = (v, a)
            inventory.append(q)
            if v not in evidence:
                unobserved.append(q)
    nf = tokens.integer("factor count")
    context.charge(nf * 160, "factor scope records")
    scopes, conditioned = [], []
    for _ in range(nf):
        size = tokens.integer("factor arity", n)
        context.charge(size * 96, "scope variables and duplicate check")
        scope = tuple(tokens.integer("factor variable", n-1) for _ in range(size))
        if len(set(scope)) != len(scope):
            context.fail("INVALID_TASK", "duplicate variable in factor scope")
        scopes.append(scope)
        conditioned.append(tuple(v for v in scope if v not in evidence))
    source_entries = zeros = max_bits = max_table = effective_entries = 0
    for scope in scopes:
        count = tokens.integer("factor table length")
        product = 1
        for v in scope:
            context.poll("while validating table shape")
            product *= cards[v]
            if product > count:
                context.fail("INVALID_TASK", "factor table length differs from scope cardinalities")
        if product != count:
            context.fail("INVALID_TASK", "factor table length differs from scope cardinalities")
        source_entries += count
        max_table = max(max_table, count)
        effective_entries += math.prod(cards[v] for v in scope if v not in evidence)
        # Existing backends materialize all Fraction entries. Admit their
        # minimum object footprint before consuming a potentially huge table.
        context.charge(count * 96, "source rational-table object estimate")
        for _ in range(count):
            zero, bits = _number(tokens.next("factor value"), context)
            zeros += zero
            max_bits = max(max_bits, bits)
            context.charge((bits+7)//8, "source rational payload estimate")
    tokens.finish()
    context.meta.update(binding=dict(model_sha256=tokens.digest.hexdigest(), evidence_sha256=evidence_hash),
                        source_bytes=tokens.bytes_read, evidence_bytes=evidence_bytes,
                        inventory=inventory, unobserved_inventory=unobserved,
                        scopes=scopes, conditioned_scopes=conditioned, n_factors=nf,
                        source_entries=source_entries, effective_entries=effective_entries,
                        max_table_entries=max_table, max_input_bits_estimate=max_bits,
                        hard_zero_entries=zeros, zero_fraction=zeros/source_entries if source_entries else 0.0,
                        max_arity=max(map(len, scopes), default=0),
                        max_effective_arity=max(map(len, conditioned), default=0))
    context.meta.update(_structure(cards, evidence, conditioned, source_entries, context))
    base_charge = context.used
    remaining = max(0.0, deadline-time.monotonic())
    forecast_deadline = min(deadline, time.monotonic()+min(0.1*remaining, 0.5))
    if not forecast:
        context.meta["physical_volume"] = None
        context.meta["forecast_refusal"] = dict(kind="NOT_REQUESTED", reason="the selected policy performs no optional physical forecast")
    else:
      try:
        context.meta["physical_volume"] = _forecast(cards, evidence, conditioned,
                                                     effective_entries, context, forecast_deadline)
        context.meta["forecast_refusal"] = None
      except PlanningRefused as exc:
        context.meta["physical_volume"] = None
        context.meta["forecast_refusal"] = dict(kind=exc.kind, reason=exc.reason)
      finally:
        context.used = base_charge
    context.meta["native_forecast"] = context.meta["physical_volume"]
    context.meta["native_work"] = (2 * context.meta["physical_volume"]["sum_product"]
                                   if context.meta["physical_volume"] is not None else None)
    context.meta["native_forecast_memory_bytes"] = (context.meta["physical_volume"]["native_bytes_estimate"]
                                                    if context.meta["physical_volume"] is not None else None)
    context.meta["inspection_memory_estimate_bytes"] = context.used
    context.meta["inspection_s"] = time.monotonic()-started
    context.poll("after inspection")
    return context.meta
