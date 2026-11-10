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


def compile_demand(P, row_cap=1_000_000, tick=lambda n=1: None, tables=None):
    """mutates the DENSE nodes' demand hints of program P in place; returns {"restricted": [...], "entries_saved": n, "skipped_cap": [...], "consumers": {nid: uses}}.
    `tables` (fid -> exact table) lets the MUL lift skip rows where a SIBLING SOURCE operand is exactly zero (the product row is zero: nothing is read)."""
    cons = P.consumers(); tables = dict(tables or {}); rec = {"restricted": [], "entries_saved": 0, "skipped_cap": [], "consumers": {n.nid: len(cons[n.nid]) for n in P.nodes}, "shared_nodes": [n.nid for n in P.nodes if len(cons[n.nid]) > 1]}
    for dfid, d in (P.derived or {}).items():                                            # derived (split) tables from the registered witnesses: demand is a STORAGE choice only (reads outside are streamed, never assumed zero),
        try:                                                                              # so an unvalidated witness can only cost work, never correctness; the validator checks the witness itself afterwards
            if d.get("kind") == "additive_split":
                tables[dfid] = tuple(d["parts"][d["index"]])
            elif d.get("kind") == "product_split":
                tables[dfid] = tuple(d["u"] if d.get("part") == "u" else d["g"])
        except Exception:
            pass
    demanded = {}                                                                     # nid -> set of demanded output indices (None = FULL)
    for r in P.roots:
        demanded[r] = set(range(P.nodes[r].volume)) if P.nodes[r].volume <= row_cap else None
    # process in reverse topological order (consumers before producers)
    for n in reversed(P.nodes):
        if n.nid not in demanded:
            demanded[n.nid] = None if not cons[n.nid] else set()
        own = demanded[n.nid]
        if own is None and n.nid not in P.roots and n.kind == IR.REDUCE and n.storage == IR.DENSE:
            pass
        # lift this node's demand to each child along every USE edge
        for ci, c in enumerate(n.children):
            child = P.nodes[c]; cur = demanded.get(c, set() if cons[c] else None)
            if own is None or cur is None:
                demanded[c] = None; continue
            if len(own) * (n.volume and 1) > row_cap:
                demanded[c] = None; rec["skipped_cap"].append(c); continue
            lifted = set()
            if n.kind == IR.ADD:
                lifted = set(own)
            elif n.kind == IR.MUL:
                pr = n.proj[ci]; zsrc = [(n.proj[j], tables[P.nodes[cj].fid], P.nodes[cj].card) for j, cj in enumerate(n.children) if j != ci and P.nodes[cj].kind == IR.SOURCE and P.nodes[cj].fid in tables]
                for idx in own:
                    d = _digits(n.card, idx); tick()
                    if any(tab[_compose(cc, [d[p] for p in pj])] == 0 for pj, tab, cc in zsrc):
                        continue                                                              # an exactly-zero sibling source entry: this product row is zero, the child entry is never read
                    lifted.add(_compose(child.card, [d[p] for p in pr]))
            elif n.kind == IR.GATHER:
                for idx in own:
                    d = _digits(n.card, idx); cd = []
                    for k, g in enumerate(n.gaxes):
                        raw = d[g["out_pos"]]; cd.append(g["cls"][raw] if g.get("cls") is not None else raw)
                    lifted.add(_compose(child.card, cd)); tick()
            elif n.kind == IR.REDUCE:
                elim = [k for k, r in enumerate(n.rmap) if r < 0]; ev = IR.prod(child.card[k] for k in elim)
                if len(own) * ev > row_cap:
                    demanded[c] = None; rec["skipped_cap"].append(c); continue
                for idx in own:
                    d = _digits(n.card, idx)
                    for t in range(ev):
                        tt = t; cd = [0] * len(child.card)
                        for k in reversed(elim):
                            cd[k] = tt % child.card[k]; tt //= child.card[k]
                        for k, r in enumerate(n.rmap):
                            if r >= 0:
                                cd[k] = n.reps[k][0][d[r]] if n.reps[k] is not None else d[r]
                        lifted.add(_compose(child.card, cd)); tick()
            else:
                demanded[c] = None; continue
            demanded[c] = cur | lifted                                                # UNION over every consumer use edge
    for n in P.nodes:
        if n.nid in P.roots or n.storage != IR.DENSE or n.kind in (IR.SOURCE, IR.MARKER, IR.CONSTANT):
            continue
        dem = demanded.get(n.nid)
        if dem is None or len(dem) >= n.volume:
            continue
        before = n.volume if n.demand == "FULL" else (0 if n.demand == "EMPTY" else len(n.demand))
        n.demand = tuple(sorted(dem)) if dem else "EMPTY"; n.prov = dict(n.prov or {}, demand="RESTRICTED_ALL_CONSUMERS", consumers=len(cons[n.nid])); rec["restricted"].append(n.nid); rec["entries_saved"] += max(0, before - len(dem))
    return rec
