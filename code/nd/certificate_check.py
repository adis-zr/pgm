"""The INDEPENDENT reconstruction checker of the two-channel certificate (theory §7). It reparses the original input files
(shared parser `mdi.model.read_uai` / `read_evidence` -- DISCLOSED shared utility), restricts with its OWN assignment-based
slicing, re-derives the masks with its OWN gap rule, recomputes the min-fill order and the first-fit grouping from scopes
and IDs alone and requires them to equal the producer's declared schedule, checks occurrence ownership (a partition), then
executes the two-channel relaxation itself with EXPLICIT pair arithmetic ((r,d)*(s,e) = (rs, re+ds+de); Python ints, dict
tables keyed by assignment tuples -- a different data layout and arithmetic path from the producer's numpy total-channel
form) and compares BOTH channels exactly. Shared with the producer: the parser, Fraction, the frozen constants."""
from __future__ import annotations
from fractions import Fraction as Fr
import itertools, math, time
from mdi import model as M

K_DEFAULT = 4096


class CheckFailure(Exception):
    pass


def _restrict_own(model, ev):
    """Assignment-based slicing: enumerate the free sub-assignments of each occurrence and look up the original entry."""
    occ, scalars = [], []
    for f in model.factors:
        free_pos = [k for k, v in enumerate(f.scope) if v not in ev]
        if not free_pos:
            scalars.append((f.origin, Fr(f.at({v: ev[v] for v in f.scope}))))
            continue
        fscope = tuple(f.scope[k] for k in free_pos); fcard = tuple(f.card[k] for k in free_pos)
        tab = {}
        for assign in itertools.product(*[range(c) for c in fcard]):
            full = dict(ev); full.update(dict(zip(fscope, assign)))
            tab[assign] = Fr(f.at({v: full[v] for v in f.scope}))
        occ.append({"origin": f.origin, "scope": fscope, "card": fcard, "table": tab})
    return occ, scalars


def _gap_removed_own(tab, G):
    vals = sorted({x for x in tab.values() if x > 0})
    j = None
    for i in range(len(vals) - 1):
        if vals[i + 1] >= G * vals[i]:
            j = i
    if j is None:
        return set()
    return {a for a, x in tab.items() if 0 < x <= vals[j]}


def _min_fill_own(free, card, scopes):
    adj = {v: set() for v in free}
    for sc in scopes:
        for a in sc:
            adj[a].update(b for b in sc if b != a)
    rem = set(free); order = []
    while rem:
        cands = []
        for v in rem:
            nb = [x for x in adj[v] if x in rem]
            miss = 0
            for i in range(len(nb)):
                for k in range(i + 1, len(nb)):
                    if nb[k] not in adj[nb[i]]:
                        miss += 1
            prod = card[v]
            for x in nb:
                prod *= card[x]
            cands.append(((miss, prod, v), v))
        key, v = min(cands)
        nb = [x for x in adj[v] if x in rem]
        for x in nb:
            for y in nb:
                if x != y:
                    adj[x].add(y)
            adj[x].discard(v)
        rem.discard(v); order.append(v)
    return order


def check(model_path, evid_path, G, record, K=K_DEFAULT, deadline=None):
    """Raises CheckFailure on any disagreement; returns the checker's own (V, U) in original units and its statistics."""
    t0 = time.monotonic()
    model = M.read_uai(model_path); ev = M.read_evidence(evid_path, model)
    free = [v for v in range(model.nvars) if v not in ev]; card = {v: model.card[v] for v in free}
    occ, scalars = _restrict_own(model, ev)
    G = Fr(G)
    masks = [_gap_removed_own(o["table"], G) for o in occ]
    # ---- schedule reconstruction from scopes and IDs only
    order = _min_fill_own(free, card, [o["scope"] for o in occ])
    if [int(x) for x in record["order"]] != order:
        raise CheckFailure("the declared elimination order is not the frozen min-fill order")
    if int(record["K"]) != K or int(record["n_occurrences"]) != len(occ) or int(record["n_scalars"]) != len(scalars) or int(record["n_free"]) != len(free):
        raise CheckFailure("declared cap / counts differ from the reconstruction")
    for v in free:
        if card[v] > K:
            raise CheckFailure("free domain above K: the certificate route must have refused")
    # ---- pair factors with cleared denominators (own construction)
    facs = {}                                         # fid -> (scope, card, {assign: (r, d)}, owned)
    C = 1
    for i, (o, rem) in enumerate(zip(occ, masks)):
        L = 1
        for x in o["table"].values():
            L = L * x.denominator // math.gcd(L, x.denominator)
        C *= L
        tab = {}
        for a, x in o["table"].items():
            w = int(x * L)
            tab[a] = (0, w) if a in rem else (w, 0)
        facs[(0, i)] = (o["scope"], o["card"], tab, frozenset({("occ", i)}))
    base = len(occ)
    for k, v in enumerate(free):
        facs[(0, base + k)] = ((v,), (card[v],), {(s,): (1, 0) for s in range(card[v])}, frozenset({("id", v)}))
    for k, (origin, val) in enumerate(scalars):
        L = val.denominator; C *= L
        facs[(0, base + len(free) + k)] = ((), (), {(): (int(val * L), 0)}, frozenset({("scalar", k)}))
    if str(C) != str(record["C"]):
        raise CheckFailure("the common scale C differs: checker %d, declared %s" % (C, record["C"]))
    live = dict(facs)
    stats = {"pair_products": 0, "pair_additions": 0, "groups": 0}
    for e, v in enumerate(order):
        if deadline is not None:
            deadline()
        brec = record["schedule"][e]
        if int(brec["var"]) != v:
            raise CheckFailure("schedule bucket %d eliminates %s, expected %d" % (e, brec["var"], v))
        bucket = sorted([fid for fid, f in live.items() if v in f[0]], key=lambda fid: (-math.prod(live[fid][1]), tuple(fid)))
        if [tuple(x) for x in brec["bucket_fids"]] != bucket:
            raise CheckFailure("bucket %d membership / order differs" % e)
        groups = []
        for fid in bucket:
            placed = False
            for g in groups:
                uv = g[1] | set(live[fid][0])
                if math.prod(card[x] for x in uv) <= K:
                    g[0].append(fid); g[1] = uv; placed = True; break
            if not placed:
                groups.append([[fid], set(live[fid][0])])
        if len(groups) != len(brec["groups"]):
            raise CheckFailure("bucket %d: %d groups reconstructed, %d declared" % (e, len(groups), len(brec["groups"])))
        new = {}
        for gi, (members, uv) in enumerate(groups):
            g = brec["groups"][gi]
            if [tuple(x) for x in g["member_fids"]] != members:
                raise CheckFailure("bucket %d group %d membership differs" % (e, gi))
            others = sorted(x for x in uv if x != v)
            if [int(x) for x in g["message_scope"]] != others or [int(x) for x in g["union_scope"]] != others + [v]:
                raise CheckFailure("bucket %d group %d scope differs" % (e, gi))
            owned = frozenset().union(*[live[fid][3] for fid in members])
            if len(owned) != sum(len(live[fid][3]) for fid in members):
                raise CheckFailure("ownership overlap inside a group")
            # explicit pair arithmetic over the union scope
            msg = {}
            for oa in itertools.product(*[range(card[x]) for x in others]):
                acc = (0, 0)
                for sv in range(card[v]):
                    full = dict(zip(others, oa)); full[v] = sv
                    prod = (1, 0)
                    for fid in members:
                        sc, cd, tab, _ = live[fid]
                        (s_, e_) = tab[tuple(full[x] for x in sc)]
                        prod = (prod[0] * s_, prod[0] * e_ + prod[1] * s_ + prod[1] * e_); stats["pair_products"] += 1
                    acc = (acc[0] + prod[0], acc[1] + prod[1]); stats["pair_additions"] += 1
                msg[oa] = acc
            new[tuple(g["message_fid"])] = (tuple(others), tuple(card[x] for x in others), msg, owned)
            stats["groups"] += 1
        for fid in bucket:
            del live[fid]
        live.update(new)
    V, D = 1, 0
    owned_all = set()
    for fid, (sc, cd, tab, owned) in live.items():
        if sc != ():
            raise CheckFailure("a non-scalar factor survives the schedule")
        (s_, e_) = tab[()]
        V, D = V * s_, V * e_ + D * s_ + D * e_
        owned_all |= owned
    expect = {("occ", i) for i in range(len(occ))} | {("id", v) for v in free} | {("scalar", k) for k in range(len(scalars))}
    if owned_all != expect:
        raise CheckFailure("ownership is not a partition of the occurrences")
    if str(V) != str(record["V_int"]) or str(D) != str(record["U_int"]):
        raise CheckFailure("channel disagreement: checker (V,U) = (%s..., %s...) vs declared (%s..., %s...)" % (str(V)[:20], str(D)[:20], str(record["V_int"])[:20], str(record["U_int"])[:20]))
    return {"V": Fr(V, C), "U": Fr(D, C), "both_channels_match": True, "schedule_reconstructed": True, "ownership_partition": True,
            "stats": stats, "wall_s": round(time.monotonic() - t0, 6), "shared_code": ["mdi.model.read_uai / read_evidence (parser)", "fractions.Fraction", "frozen constants G, K"]}
