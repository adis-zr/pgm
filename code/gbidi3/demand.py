"""All-consumer backward DEMAND over the canonical IR (review F3; brief §7). Production (gbidi3.planner) emits TREE programs, so its bucket-level demand
pass (one consumer per message) is complete for what it creates. This module is the general compiler for programs with SHARED modules (several
consumer USE edges of one node), as the IR / kernel accept them (C03-style programs): for every DENSE node it computes the UNION over ALL consumer use
edges of the entries those consumers can read, given each consumer's own demanded entries, and restricts storage only to that union. Anything not
analyzable stays FULL (conservative). A node consumed through a REDUCE lifts every eliminated tuple (lazy: the consumer's demanded output index with
the eliminated axes free); through MUL the child's index is the projection of the parent's demanded index; through GATHER the class map expands
whole classes (a class is live if any of its raw states is demanded); through ADD the demand is forwarded unchanged. Caps: a node whose consumers'
demanded volume exceeds `row_cap` is left FULL (UNKNOWN is live). Returns a record of what was restricted and how many entries were saved."""
from __future__ import annotations
from gbidi3 import ir as IR


def _digits(card, idx):
    d = [0] * len(card)
    for k in range(len(card) - 1, -1, -1):
        d[k] = idx % card[k]; idx //= card[k]
    return d


def _compose(card, d):
    idx = 0
    for k in range(len(card)):
        idx = idx * card[k] + d[k]
    return idx


class Budget:
    """ONE aggregate optional budget for the compiler (review F5 / D3): every lifted index is a ROW inspection charged to the shared row cap (clock.spend_rows,
    which also polls the OPTIONAL discovery wall); every live demand set / union / copy is RESERVED on the host ledger (48 B per index + 64 per set) before it is
    built and released when it dies. Exhaustion raises PlanStop (caught by the caller: every node keeps FULL or its safely completed hint)."""
    def __init__(self, clock=None, ledger=None, tick=None):
        self.clock = clock; self.ledger = ledger; self.tick = tick or (lambda n=1: None); self.live = 0; self.peak = 0; self.rows = 0
    def rows_(self, n):
        self.rows += n
        if self.clock is not None:
            self.clock.spend_rows(n)                                                  # shared row cap + optional wall, polled
        else:
            self.tick(n)
    SET_BYTES_PER_INDEX = 96                                                           # documented proxy: CPython set slot (~16 B at load <= 0.6) + int object (28-32 B) + hash-table growth slack; a RESERVATION proxy, not RSS
    def reserve_set(self, n):
        b = Budget.SET_BYTES_PER_INDEX * n + 256
        if self.ledger is not None:
            self.ledger.reserve("source_ir_maps_output", b, "demand set (%d indices)" % n)
        self.live += b; self.peak = max(self.peak, self.live); return b
    def release_set(self, b):
        if self.ledger is not None:
            self.ledger.release("source_ir_maps_output", b)
        self.live -= b


def compile_demand(P, row_cap=1_000_000, tick=lambda n=1: None, tables=None, clock=None, ledger=None, optional=True):
    """mutates the DENSE nodes' demand hints of program P in place; returns the compiler's own record {"restricted": [...], "entries_saved": n, "skipped_cap":
    [...], "consumers": {nid: uses}, "shared_nodes": [...], "rows_inspected", "peak_live_bytes", "stop"}. `optional=False` (arm switch demand_masks off): the
    compiler runs its MANDATORY conservative part only (no restriction is applied; every analysable node keeps FULL) and records that it was disabled.
    `tables` (fid -> exact table) lets the MUL lift skip rows where a SIBLING SOURCE operand is exactly zero (the product row is zero: nothing is read).
    Budget: `row_cap` bounds the AGGREGATE number of lifted indices over all nodes and use edges (not per node); with `clock` the shared row cap and the
    optional discovery wall are charged / polled through clock.spend_rows; with `ledger` every live set is reserved before it is built."""
    from gbidi3.clock import PlanStop
    cons = P.consumers(); tables = dict(tables or {}); rec = {"restricted": [], "entries_saved": 0, "skipped_cap": [], "consumers": {n.nid: len(cons[n.nid]) for n in P.nodes}, "shared_nodes": [n.nid for n in P.nodes if len(cons[n.nid]) > 1], "optional_enabled": bool(optional), "rows_inspected": 0, "peak_live_bytes": 0, "stop": None}
    if not optional:
        rec["note"] = "optional demand restriction DISABLED by the arm switch: no hint applied; correctness-critical zeros / supports stay with the kernel's forward support"; return rec
    for dfid, d in (P.derived or {}).items():                                            # derived (split) tables from the registered witnesses: demand is a STORAGE choice only (reads outside are streamed, never assumed zero),
        try:                                                                              # so an unvalidated witness can only cost work, never correctness; the validator checks the witness itself afterwards
            if d.get("kind") == "additive_split":
                tables[dfid] = tuple(d["parts"][d["index"]])
            elif d.get("kind") == "product_split":
                tables[dfid] = tuple(d["u"] if d.get("part") == "u" else d["g"])
        except Exception:
            pass
    bud = Budget(clock, ledger, tick); demanded = {}; charged = {}; total_rows = 0
    def hold(nid, st, prereserved=None):
        """store a demand set under reservation: the NEW set's charge is taken BEFORE the old one is released (both are live until the assignment); a set built
        under a prior reservation (`prereserved`, the union bound) hands that charge over instead of reserving again"""
        new = None
        if st is not None:
            new = prereserved if prereserved is not None else bud.reserve_set(len(st))
        if nid in charged:
            bud.release_set(charged.pop(nid))                                                 # the previous set dies here (after the new one is charged)
        if new is not None:
            charged[nid] = new
        demanded[nid] = st
    QUANTUM = 4096
    def lift_tick(i):
        if i % QUANTUM == QUANTUM - 1:
            bud.rows_(0) if clock is None else clock.check_optional()                           # poll INSIDE a large lift (bounded quantum), not only before it
    try:
        if clock is not None:
            clock.check_optional()                                                       # an already-expired optional allowance stops the refinement BEFORE any set is built (nothing restricted)
        for r in P.roots:
            vol = P.nodes[r].volume
            if vol <= row_cap - total_rows:
                total_rows += vol; bud.rows_(vol); hold(r, set(range(vol)))
            else:
                hold(r, None)
        for n in reversed(P.nodes):                                                      # consumers before producers
            if n.nid not in demanded:
                hold(n.nid, None if not cons[n.nid] else set())
            own = demanded[n.nid]
            for ci, c in enumerate(n.children):
                child = P.nodes[c]; cur = demanded.get(c, set() if cons[c] else None)
                if own is None or cur is None:
                    hold(c, None); continue
                need = len(own) * (IR.prod(child.card[k] for k, r in enumerate(n.rmap) if r < 0) if n.kind == IR.REDUCE else 1)
                if need > row_cap - total_rows:
                    hold(c, None); rec["skipped_cap"].append(c); continue           # AGGREGATE cap: the child stays FULL (conservative), never uninspected-as-dead
                total_rows += need; bud.rows_(need); lifted = set(); tmp = bud.reserve_set(need); union_charge = None
                try:
                    if n.kind == IR.ADD:
                        lifted = set(own)
                    elif n.kind == IR.MUL:
                        pr = n.proj[ci]; zsrc = [(n.proj[j], tables[P.nodes[cj].fid], P.nodes[cj].card) for j, cj in enumerate(n.children) if j != ci and P.nodes[cj].kind == IR.SOURCE and P.nodes[cj].fid in tables]
                        for i, idx in enumerate(own):
                            lift_tick(i); d = _digits(n.card, idx)
                            if any(tab[_compose(cc, [d[p] for p in pj])] == 0 for pj, tab, cc in zsrc):
                                continue                                                  # an exactly-zero sibling source entry: this product row is zero, the child entry is never read
                            lifted.add(_compose(child.card, [d[p] for p in pr]))
                    elif n.kind == IR.GATHER:
                        for i, idx in enumerate(own):
                            lift_tick(i); d = _digits(n.card, idx); cd = []
                            for k, g in enumerate(n.gaxes):
                                raw = d[g["out_pos"]]; cd.append(g["cls"][raw] if g.get("cls") is not None else raw)
                            lifted.add(_compose(child.card, cd))
                    elif n.kind == IR.REDUCE:
                        elim = [k for k, r in enumerate(n.rmap) if r < 0]; ev = IR.prod(child.card[k] for k in elim); i = 0
                        for idx in own:
                            d = _digits(n.card, idx)
                            for t in range(ev):
                                lift_tick(i); i += 1; tt = t; cd = [0] * len(child.card)
                                for k in reversed(elim):
                                    cd[k] = tt % child.card[k]; tt //= child.card[k]
                                for k, r in enumerate(n.rmap):
                                    if r >= 0:
                                        cd[k] = n.reps[k][0][d[r]] if n.reps[k] is not None else d[r]
                                lifted.add(_compose(child.card, cd))
                    else:
                        hold(c, None); continue
                    union_charge = bud.reserve_set(len(cur) + len(lifted))              # the UNION is reserved (upper bound |cur| + |lifted|) while cur, lifted and the union are ALL live -- BEFORE it is built
                    hold(c, cur | lifted, prereserved=union_charge); union_charge = None   # the union takes over its reservation; the old set of c is released after
                finally:
                    bud.release_set(tmp)                                                  # the lift temporary dies here
                    if union_charge is not None:
                        bud.release_set(union_charge)
        if clock is not None:
            clock.check_optional()                                                       # the optional allowance is checked once more at COMMITMENT: an expired discovery applies nothing
    except PlanStop as ex:
        rec["stop"] = {"kind": ex.kind, "reason": ex.reason}                            # optional budget exhausted: whatever is not completed stays FULL (below: only completed, fully covered nodes are restricted)
        if ex.kind == "CELL_DEADLINE":
            raise
    except Exception as ex:
        if type(ex).__name__ == "MemoryStop":
            rec["stop"] = {"kind": "MEMORY_CATEGORY", "reason": str(ex)[:200]}
        else:
            raise
    # apply: a node is restricted only when EVERY consumer use edge completed its lift (a stopped compiler leaves partial nodes FULL)
    completed = set(demanded) if rec["stop"] is None else set()                        # a stopped compiler applies NOTHING: every node keeps FULL / its declared hint (conservative)
    for n in P.nodes:
        if n.nid in P.roots or n.storage != IR.DENSE or n.kind in (IR.SOURCE, IR.MARKER, IR.CONSTANT) or n.nid not in completed:
            continue
        dem = demanded.get(n.nid)
        if dem is None or len(dem) >= n.volume:
            continue
        before = n.volume if n.demand == "FULL" else (0 if n.demand == "EMPTY" else len(n.demand))
        n.demand = tuple(sorted(dem)) if dem else "EMPTY"; n.prov = dict(n.prov or {}, demand="RESTRICTED_ALL_CONSUMERS", consumers=len(cons[n.nid])); rec["restricted"].append(n.nid); rec["entries_saved"] += max(0, before - len(dem))
    for nid, b in list(charged.items()):
        bud.release_set(b)                                                               # the demand sets are consumed into the hints: release
    rec["rows_inspected"] = bud.rows; rec["peak_live_bytes"] = bud.peak; return rec
