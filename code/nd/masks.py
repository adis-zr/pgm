"""The frozen mask rule (theory §6) on EVIDENCE-RESTRICTED factor occurrences, before any factor multiplication or
exact simplification: distinct positive values v_1 < ... < v_k of one occurrence; the largest j < k with v_{j+1} >= G v_j
(exact rational comparison, ties included); remove every entry with value <= v_j; no such j -> remove nothing. Zero
entries belong to neither channel (they weigh nothing). Also: the masked ORIGINAL model (removed entries zeroed at their
original table positions) that the existing sparse path solves for the retained law Q."""
from fractions import Fraction as Fr
from mdi import model as M

GAPS = {"G10000": Fr(10000), "G100": Fr(100)}


def restricted_occurrences(model, ev):
    """(scope, card, table, origin, orig_positions) per restricted occurrence, in original occurrence order, plus the
    scalar occurrences (fully pinned factors: (origin, value)). Own slicing (not mdi.model.restrict) so the checker and
    the producer do not share the restriction code path; `orig_positions[i]` is the original flat index of entry i."""
    occ, scalars = [], []
    for f in model.factors:
        st = f.strides()
        keep = [k for k in range(len(f.scope)) if f.scope[k] not in ev]
        base = sum(ev[f.scope[k]] * st[k] for k in range(len(f.scope)) if f.scope[k] in ev)
        if not keep:
            scalars.append((f.origin, Fr(f.table[base])))
            continue
        nsc = tuple(f.scope[k] for k in keep); ncd = tuple(f.card[k] for k in keep)
        n = 1
        for c in ncd:
            n *= c
        nst = [1] * len(ncd); acc = 1
        for k in range(len(ncd) - 1, -1, -1):
            nst[k] = acc; acc *= ncd[k]
        pos = []
        for idx in range(n):
            off, rem = base, idx
            for k in range(len(ncd)):
                d, rem = divmod(rem, nst[k]); off += d * st[keep[k]]
            pos.append(off)
        occ.append({"scope": nsc, "card": ncd, "table": [Fr(f.table[p]) for p in pos], "origin": f.origin, "orig_positions": pos})
    return occ, scalars


def gap_removed(table, G):
    """Indices of the removed entries under gap parameter G (exact)."""
    vals = sorted(set(Fr(x) for x in table if x > 0))
    j_star = None
    for j in range(len(vals) - 1):
        if vals[j + 1] >= G * vals[j]:
            j_star = j                                  # the LARGEST such j survives
    if j_star is None:
        return [], None
    thr = vals[j_star]
    return [i for i, x in enumerate(table) if 0 < Fr(x) <= thr], thr


def apply_masks(occ, G):
    """Per occurrence: removed index list and threshold; returns the list aligned with `occ`."""
    out = []
    for o in occ:
        rem, thr = gap_removed(o["table"], G)
        out.append({"origin": o["origin"], "removed": rem, "threshold": (str(thr) if thr is not None else None),
                    "entries": len(o["table"]), "positive_entries": sum(1 for x in o["table"] if x > 0)})
    return out


def masked_model(model, occ, masks):
    """The ORIGINAL model with every removed entry zeroed at its original position (entries inconsistent with the
    evidence are left as they are: restriction drops them). Scalar occurrences are unchanged."""
    by_origin = {o["origin"]: (o, mk) for o, mk in zip(occ, masks)}
    facs = []
    for f in model.factors:
        tab = [Fr(x) for x in f.table]
        if f.origin in by_origin:
            o, mk = by_origin[f.origin]
            for i in mk["removed"]:
                tab[o["orig_positions"][i]] = Fr(0)
        facs.append(M.Factor(scope=f.scope, card=f.card, table=tab, origin=f.origin))
    return M.Model(nvars=model.nvars, card=list(model.card), factors=facs, net_type=model.net_type).validate()


def mask_digest(masks):
    import hashlib
    h = hashlib.sha256()
    for mk in masks:
        h.update(("%d:%s;" % (mk["origin"], ",".join(str(i) for i in mk["removed"]))).encode())
    return h.hexdigest()
