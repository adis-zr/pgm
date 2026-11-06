"""R0 reference: exact RATIONAL variable elimination for one UAI model + evidence (min-fill order), with an independent brute-force check
when the model is tiny. Writes a JSON reference {var: [Fraction strings]} with class R0, the elapsed time, and the largest intermediate table.
Refuses (writes status REFUSED) when the forecast largest table exceeds MAX_ENTRIES; a 300 s outer cap is applied by the caller.
    python bench/ref_exact.py MODEL EVID OUT.json [MAX_ENTRIES]"""
import sys, os, json, time, itertools, heapq
HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__))); sys.path.insert(0, HERE)
sys.set_int_max_str_digits(0)
from fractions import Fraction as Fr
from ext import uai as U


def minfill_order(scopes, nvars, ev):
    adj = {v: set() for v in range(nvars) if v not in ev}
    for sc in scopes:
        sc = [v for v in sc if v not in ev]
        for a in sc:
            for b in sc:
                if a != b:
                    adj[a].add(b)
    order = []; alive = set(adj)
    while alive:
        best = None
        for v in alive:
            nb = adj[v]; fill = sum(1 for a in nb for b in nb if a < b and b not in adj[a])
            key = (fill, len(nb), v)
            if best is None or key < best[0]:
                best = (key, v)
        v = best[1]; nb = adj[v]
        for a in nb:
            for b in nb:
                if a != b:
                    adj[a].add(b)
        for a in nb:
            adj[a].discard(v)
        alive.discard(v); order.append(v)
    return order


def forecast(scopes, card, order, ev):
    """largest table (entries) produced by eliminating in `order` (symbolic)."""
    buckets = [set(v for v in sc if v not in ev) for sc in scopes]; worst = 0
    for v in order:
        joined = set()
        rest = []
        for b in buckets:
            if v in b:
                joined |= b
            else:
                rest.append(b)
        n = 1
        for u in joined:
            n *= card[u]
        worst = max(worst, n); joined.discard(v); rest.append(joined); buckets = rest
    return worst


def ve_marginals(m, ev, max_entries, deadline=None):
    # tables as dicts {scope tuple: {assignment tuple: Fr}} after slicing evidence
    tabs = []
    for f in m.factors:
        sc = tuple(v for v in f.scope if v not in ev)
        d = {}
        for conf in itertools.product(*[range(m.card[v]) for v in sc]):
            a = dict(zip(sc, conf)); a.update({v: ev[v] for v in f.scope if v in ev}); val = f.at(a)
            if val != 0:
                d[conf] = val
        tabs.append((sc, d))
    order = minfill_order([f.scope for f in m.factors], m.nvars, ev)
    worst = forecast([f.scope for f in m.factors], m.card, order, ev)
    if worst > max_entries:
        return None, {"status": "REFUSED", "reason": "forecast largest table %d > %d entries" % (worst, max_entries), "forecast_largest_table": worst}
    free = [v for v in range(m.nvars) if v not in ev]; out = {}
    def join(joined, jsc, s, d):
        shared = [u for u in s if u in jsc]; extra = [u for u in s if u not in jsc]
        jpos = {u: i for i, u in enumerate(jsc)}; spos = {u: i for i, u in enumerate(s)}; idx = {}
        for conf, val in d.items():
            key = tuple(conf[spos[u]] for u in shared); idx.setdefault(key, []).append((tuple(conf[spos[u]] for u in extra), val))
        new = {}
        for jc, jv in joined.items():
            key = tuple(jc[jpos[u]] for u in shared)
            for ex, val in idx.get(key, ()):
                new[jc + ex] = jv * val
        if len(new) > max_entries:
            raise MemoryError("intermediate table %d entries" % len(new))
        return new, jsc + tuple(extra)
    def eliminate_all_but(keep):
        cur = list(tabs); peak = 0
        for v in order:
            if v == keep:
                continue
            if deadline:
                deadline()
            inb = [t for t in cur if v in t[0]]; rest = [t for t in cur if v not in t[0]]
            if not inb:
                continue
            joined = {(): Fr(1)}; jsc = ()
            for s, d in inb:
                joined, jsc = join(joined, jsc, s, d)
            peak = max(peak, len(joined)); kpos = [i for i, u in enumerate(jsc) if u != v]; acc = {}
            for conf, val in joined.items():
                k = tuple(conf[i] for i in kpos); acc[k] = acc.get(k, Fr(0)) + val
            cur = rest + [(tuple(jsc[i] for i in kpos), acc)]
        tot = {(): Fr(1)}; jsc = ()
        for s, d in cur:
            tot, jsc = join(tot, jsc, s, d)
        res = {s: Fr(0) for s in range(m.card[keep])}; Z = Fr(0)
        for conf, val in tot.items():
            if keep in jsc:
                res[conf[jsc.index(keep)]] += val
            else:
                for s in range(m.card[keep]):
                    res[s] += val / m.card[keep] * m.card[keep] if False else val
            Z += val
        if keep not in jsc:                                            # keep had no factor touching it after slicing: uniform
            Z = Z * m.card[keep]
        return res, Z, peak
    peak_all = 0
    for v in free:
        res, Z, peak = eliminate_all_but(v); peak_all = max(peak_all, peak)
        if Z == 0:
            return None, {"status": "ZERO_PARTITION", "reason": "Z = 0 exactly"}
        out[v] = [res[s] / Z for s in range(m.card[v])]
    return out, {"status": "R0", "order": "min-fill", "forecast_largest_table": worst, "peak_table_entries": peak_all}


def brute(m, ev):
    Z = Fr(0); num = {v: [Fr(0)] * m.card[v] for v in range(m.nvars)}
    for a in itertools.product(*[range(c) for c in m.card]):
        if any(a[v] != s for v, s in ev.items()):
            continue
        w = Fr(1)
        for f in m.factors:
            w *= f.at({v: a[v] for v in f.scope})
        Z += w
        for v in range(m.nvars):
            num[v][a[v]] += w
    return None if Z == 0 else {v: [x / Z for x in num[v]] for v in num if v not in ev}


if __name__ == "__main__":
    mp, ep, outp = sys.argv[1:4]; max_entries = int(sys.argv[4]) if len(sys.argv) > 4 else 1 << 22
    t0 = time.monotonic(); m = U.read_model(mp); ev = U.read_evidence(ep)
    try:
        res, info = ve_marginals(m, ev, max_entries)
    except MemoryError as ex:
        res, info = None, {"status": "REFUSED", "reason": str(ex)}
    info["elapsed_s"] = time.monotonic() - t0; info["model"] = mp; info["evidence"] = ep; info["class"] = "R0 (exact rational VE)" if res else None
    if res is not None:
        states = 1
        for c in m.card:
            states *= c
        if states <= 1 << 16:
            b = brute(m, ev); assert b == res, "VE and brute force disagree"; info["brute_force_cross_check"] = True
        info["marginals"] = {str(v): [str(x) for x in row] for v, row in res.items()}
    json.dump(info, open(outp, "w")); print(json.dumps({k: info[k] for k in ("status", "elapsed_s", "forecast_largest_table") if k in info}))
