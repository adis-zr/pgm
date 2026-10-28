"""Generic elimination / junction-tree compilation (spec section 2).

Standard infrastructure, no novelty claimed. A fixed generic ordering portfolio
is evaluated on actual domain products and byte layout; no hand-written order
and no per-benchmark special casing.
"""
from __future__ import annotations
from dataclasses import dataclass, field


class PlanError(ValueError):
    pass


def primal_graph(free, card, factors):
    adj = {v: set() for v in free}
    for f in factors:
        sc = [v for v in f.scope]
        for a in sc:
            for b in sc:
                if a != b:
                    adj[a].add(b)
    return adj


# ---------------- orderings (all deterministic) ----------------

def order_ascending(free, card, adj):
    return sorted(free)


def order_descending(free, card, adj):
    return sorted(free, reverse=True)


def _simulate(adj, card, key):
    """Generic greedy elimination under a per-step lexicographic key."""
    a = {v: set(ns) for v, ns in adj.items()}
    remaining = set(a)
    order = []
    while remaining:
        best, bestk = None, None
        for v in remaining:
            k = key(v, a, card)
            if bestk is None or k < bestk:
                best, bestk = v, k
        v = best
        nb = a[v] & remaining
        for x in nb:
            for y in nb:
                if x != y:
                    a[x].add(y)
        for x in a[v]:
            a[x].discard(v)
        remaining.discard(v)
        order.append(v)
    return order


def order_min_fill(free, card, adj):
    """Spec's min-fill profile: minimize (missing neighbor pairs, product of
    cardinalities in the candidate bag, degree, original variable ID)."""
    def key(v, a, card):
        nb = sorted(a[v])
        miss = 0
        for i in range(len(nb)):
            for j in range(i + 1, len(nb)):
                if nb[j] not in a[nb[i]]:
                    miss += 1
        prod = card[v]
        for x in nb:
            prod *= card[x]
        return (miss, prod, len(nb), v)
    return _simulate(adj, card, key)


def order_min_degree(free, card, adj):
    """Min-degree with deterministic cardinality/ID ties."""
    def key(v, a, card):
        nb = sorted(a[v])
        prod = card[v]
        for x in nb:
            prod *= card[x]
        return (len(nb), prod, v)
    return _simulate(adj, card, key)


PORTFOLIO = [("ascending_ids", order_ascending), ("descending_ids", order_descending),
             ("min_fill", order_min_fill), ("min_degree", order_min_degree)]


# ---------------- bag tree construction ----------------

@dataclass
class Bag:
    idx: int
    vars: tuple                      # sorted bag variables
    eliminated: int                   # the variable eliminated at this bag
    parent: int = -1
    children: list = field(default_factory=list)
    factors: list = field(default_factory=list)   # indices of OWNED factors
    separator: tuple = ()             # vars shared with parent

    def domain(self, card):
        n = 1
        for v in self.vars:
            n *= card[v]
        return n

    def sep_domain(self, card):
        n = 1
        for v in self.separator:
            n *= card[v]
        return n


@dataclass
class Plan:
    name: str
    order: list
    bags: list
    card: dict
    free: list
    root_bags: list                   # one per connected component
    var_home: dict                    # variable -> bag index for readout
    components: list                  # list of variable sets
    induced_width: int
    largest_bag_entries: int
    sum_bag_entries: int
    sum_sep_entries: int

    def stats(self):
        return {"name": self.name, "induced_width": self.induced_width,
                "largest_bag_entries": self.largest_bag_entries,
                "sum_bag_entries": self.sum_bag_entries,
                "sum_sep_entries": self.sum_sep_entries,
                "bags": len(self.bags)}


def build_plan(name, order, free, card, factors):
    """Bucket elimination -> bag tree, with ownership and structural checks."""
    pos = {v: i for i, v in enumerate(order)}
    adj = primal_graph(free, card, factors)
    a = {v: set(ns) for v, ns in adj.items()}
    remaining = set(free)
    bags = []
    for step, v in enumerate(order):
        nb = {x for x in a[v] if x in remaining and x != v}
        bvars = tuple(sorted(nb | {v}))
        bags.append(Bag(idx=step, vars=bvars, eliminated=v))
        for x in nb:
            for y in nb:
                if x != y:
                    a[x].add(y)
        for x in a[v]:
            a[x].discard(v)
        remaining.discard(v)

    # parent: the bag eliminating the earliest-ordered variable of the separator
    for b in bags:
        rest = [x for x in b.vars if x != b.eliminated]
        if rest:
            p = min(rest, key=lambda x: pos[x])
            b.parent = pos[p]
            b.separator = tuple(sorted(rest))
            bags[b.parent].children.append(b.idx)
        else:
            b.parent = -1
            b.separator = ()

    # factor ownership: exactly one bag containing the WHOLE scope
    owner = [None] * len(factors)
    for fi, f in enumerate(factors):
        if not f.scope:
            raise PlanError("factor %d has an empty scope" % fi)
        # the bag that eliminates the earliest-ordered variable of the scope
        v = min(f.scope, key=lambda x: pos[x])
        b = bags[pos[v]]
        if not set(f.scope) <= set(b.vars):
            raise PlanError("ownership failure: factor %d scope %s not contained in bag %d %s"
                            % (fi, f.scope, b.idx, b.vars))
        owner[fi] = b.idx
        b.factors.append(fi)
    if any(o is None for o in owner):
        raise PlanError("some factor has no owner")

    # components and roots
    comp_of, comps = {}, []
    seen = set()
    for v in free:
        if v in seen:
            continue
        stack, cur = [v], set()
        while stack:
            x = stack.pop()
            if x in cur:
                continue
            cur.add(x); seen.add(x)
            stack.extend(y for y in adj[x] if y not in cur)
        for x in cur:
            comp_of[x] = len(comps)
        comps.append(cur)
    roots = [b.idx for b in bags if b.parent == -1]

    var_home = {}
    for b in bags:
        for v in b.vars:
            if v not in var_home:
                var_home[v] = b.idx
    for v in free:
        if v not in var_home:
            raise PlanError("variable %d has no home bag" % v)
        if v not in bags[var_home[v]].vars:
            raise PlanError("home bag for %d does not contain it" % v)

    iw = max(len(b.vars) - 1 for b in bags) if bags else 0
    lbe = max(b.domain(card) for b in bags) if bags else 1
    sbe = sum(b.domain(card) for b in bags)
    sse = sum(b.sep_domain(card) for b in bags)   # root separator () contributes 1
    p = Plan(name=name, order=list(order), bags=bags, card=dict(card), free=list(free),
             root_bags=roots, var_home=var_home, components=comps, induced_width=iw,
             largest_bag_entries=lbe, sum_bag_entries=sbe, sum_sep_entries=sse)
    validate_plan(p, factors)
    return p


def validate_plan(plan, factors):
    """Running intersection, separator equality, ownership, acyclicity, homes."""
    bags, card = plan.bags, plan.card
    # tree shape
    for b in bags:
        if b.parent >= 0:
            if b.idx not in bags[b.parent].children:
                raise PlanError("bag %d not registered as a child of %d" % (b.idx, b.parent))
            if b.parent <= b.idx and bags[b.parent].eliminated == b.eliminated:
                raise PlanError("degenerate parent for bag %d" % b.idx)
        # separator equality: separator == vars ∩ parent vars
        if b.parent >= 0:
            want = tuple(sorted(set(b.vars) & set(bags[b.parent].vars)))
            if b.separator != want:
                raise PlanError("bag %d separator %s != intersection with parent %s"
                                % (b.idx, b.separator, want))
            if not set(b.separator) <= set(bags[b.parent].vars):
                raise PlanError("separator of bag %d not inside its parent" % b.idx)
    # no cycles: walking to the root must terminate
    for b in bags:
        seen, x, steps = set(), b.idx, 0
        while x >= 0:
            if x in seen:
                raise PlanError("cycle in the bag tree at %d" % x)
            seen.add(x); x = bags[x].parent; steps += 1
            if steps > len(bags) + 1:
                raise PlanError("bag tree walk did not terminate")
    # running intersection: a variable's bags form a connected subtree
    occ = {}
    for b in bags:
        for v in b.vars:
            occ.setdefault(v, []).append(b.idx)
    for v, idxs in occ.items():
        s = set(idxs)
        # the highest bag (closest to root) must reach all others downward
        tops = [i for i in idxs if bags[i].parent not in s]
        if len(tops) != 1:
            raise PlanError("variable %d occupies a disconnected set of bags (tops=%s)"
                            % (v, tops))
        for i in idxs:
            x = i
            while x != tops[0]:
                x = bags[x].parent
                if x < 0 or x not in s:
                    raise PlanError("running intersection violated for variable %d" % v)
    # ownership: every factor owned exactly once, whole scope inside its bag
    cnt = {}
    for b in bags:
        for fi in b.factors:
            cnt[fi] = cnt.get(fi, 0) + 1
            if not set(factors[fi].scope) <= set(b.vars):
                raise PlanError("factor %d not contained in its owner bag %d" % (fi, b.idx))
    for fi in range(len(factors)):
        if cnt.get(fi, 0) != 1:
            raise PlanError("factor %d is owned %d times, expected exactly 1"
                            % (fi, cnt.get(fi, 0)))
    return True


def peak_live_upward(plan):
    """Peak simultaneously-live upward-message entries, by simulating the pass.

    A child's message is created when the child is processed and is freed once
    its parent has been processed. Traversing bags in post-order, the live set
    is exactly the set of already-computed messages whose parent is still
    pending. This is what actually has to be resident, not the sum of all
    messages.
    """
    card = plan.card
    bags = plan.bags
    # post-order over the whole forest (children before parents)
    order, stack = [], [b.idx for b in bags if b.parent == -1]
    seq = []
    while stack:
        x = stack.pop()
        seq.append(x)
        stack.extend(bags[x].children)
    post = list(reversed(seq))
    live, peak, cur = {}, 0, 0
    for b in post:
        # free the messages this bag consumed
        for c in bags[b].children:
            if c in live:
                cur -= live.pop(c)
        if bags[b].parent >= 0:
            e = bags[b].sep_domain(card)
            live[b] = e
            cur += e
        peak = max(peak, cur)
    return peak


def peak_live_downward(plan):
    """Peak live entries during the downward pass.

    Going root-to-leaf, a parent's outgoing message to a child must be live
    while that child is processed. A simple bound is the largest root-to-leaf
    path's separator total plus the sibling messages pending at each level.
    We simulate a depth-first schedule, which is what the engine executes.
    """
    card = plan.card
    bags = plan.bags
    peak, cur = 0, 0
    # depth-first: at any time the live downward messages are those on the
    # current root-to-node path plus the pending siblings at each level
    def walk(x, acc):
        nonlocal peak
        pend = [bags[c].sep_domain(card) for c in bags[x].children]
        tot = acc + sum(pend)
        peak = max(peak, tot)
        for c in bags[x].children:
            walk(c, acc + bags[c].sep_domain(card))
    for rt in [b.idx for b in bags if b.parent == -1]:
        walk(rt, 0)
    return peak


def byte_estimate(plan, bytes_per_entry, both_directions=True):
    """Live-memory estimate for separator message tables.

    Messages live on SEPARATORS, not full bags: a bag's belief is streamed. Dead
    messages are freed, so the estimate uses the simulated peak live set rather
    than the sum over all messages (spec: "message liveness", "free dead
    messages"). The streamed bag scratch is a few scalars, not a full table, but
    the largest separator a message occupies is charged.
    """
    card = plan.card
    per = [b.sep_domain(card) for b in plan.bags]
    total_sep = sum(per)
    up = peak_live_upward(plan)
    dn = peak_live_downward(plan) if both_directions else 0
    # the readout holds one calibrated bag's incoming messages, already counted
    # in `dn`; add the largest single separator as working room.
    live = max(up, up + dn) if both_directions else up
    largest = max(per) if per else 1
    est = (live + largest) * bytes_per_entry
    return {"bytes_per_entry": bytes_per_entry,
            "sum_sep_entries": total_sep,
            "largest_sep_entries": largest,
            "largest_bag_entries": plan.largest_bag_entries,
            "both_directions": both_directions,
            "peak_live_upward_entries": up,
            "peak_live_downward_entries": dn,
            "peak_live_entries": live,
            "sum_all_messages_bytes": (2 if both_directions else 1) * total_sep * bytes_per_entry,
            "estimate_bytes": est,
            "note": "peak simultaneously-live separator entries from a simulated "
                    "schedule, plus one largest-separator working table; bag "
                    "assignments are streamed so no full clique belief is stored."}


def choose_plan(free, card, factors, bytes_per_entry, cap_bytes, charge=None):
    """Evaluate the fixed generic portfolio; pick the cheapest that fits."""
    adj = primal_graph(free, card, factors)
    cands, errs = [], []
    for name, fn in PORTFOLIO:
        try:
            order = fn(free, card, adj)
            p = build_plan(name, order, free, card, factors)
            est = byte_estimate(p, bytes_per_entry)
            cands.append((p, est))
        except Exception as e:                      # keep the portfolio robust
            errs.append({"order": name, "error": "%s: %s" % (type(e).__name__, e)})
    if not cands:
        raise PlanError("no ordering produced a valid plan: %s" % errs)
    # rank by estimated live bytes, then by symbolic arithmetic volume
    cands.sort(key=lambda pe: (pe[1]["estimate_bytes"], pe[0].sum_bag_entries))
    fits = [pe for pe in cands if pe[1]["estimate_bytes"] <= cap_bytes]
    chosen = fits[0] if fits else None
    return {"chosen": chosen, "candidates": [(p.stats(), e) for p, e in cands],
             "errors": errs, "cap_bytes": cap_bytes,
             "fits": bool(fits)}
