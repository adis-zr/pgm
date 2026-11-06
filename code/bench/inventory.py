"""Inventory + deterministic selection of the 48-case external panel (campaign spec section 3). NO inference, NO reference values read.
usage: python bench/inventory.py SWEEP_DIR   -> writes INVENTORY.json (every accessible case with hashes and structural statistics) and
PANEL_SELECTION.json (the 36 UAI + 12 bnlearn cases, anchors forced, depth cases), from the archives under SWEEP_DIR/sources."""
from __future__ import annotations
import os, sys, json, hashlib, re, collections, math
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from fractions import Fraction as Fr
from ext import uai as U

FAMILIES = ["GridBN", "Grids", "Pedigree", "Promedus", "CSP", "DBN", "ObjectDetection", "Segmentation", "Protein"]
ALIASES = {"GridBN": ["BN (UAI 2022 final MAR archive label; grid-structured Bayesian networks)"], "Promedus": ["Promedas"], "ObjectDetection": ["ObjDetect"],
           "Segmentation": ["Segment"], "Protein": ["PDB-coded side-chain models 1aie 1bxv 1g6x 1jer 1npl 1qt9 1rfs 2rta (unlabelled in the archive)"]}
BNLEARN = ["asia", "child", "insurance", "water", "mildew", "alarm", "barley", "hailfinder", "win95pts", "munin1", "andes", "diabetes"]
ANCHORS = {"Grids": ("Grids_11", "85f8d06c1fa4d68bf2b68d4fe06747cd3fc8090c87fab4c1cb811c523affb7c8", "5feceb66ffc86f38d952786c6d696c79c2dbc239dd4e91b46729d73a27fb57e9"),
           "Pedigree": ("Pedigree_11", "787afc6fa9c066e16339ae80491c60d6e26e53d7f7d6e19de1abd4ce1872a6d8", "4088a8c03d0983ced4cc243a6bf6b87a0fd8648b16e33257ed7fa236b76e92ac"),
           "Promedus": ("Promedus_12", "60176b0a0d6b247cc73ed536cd4719b82d6a64852033b83d9b72bb8e072ca94b", "c0389999d5bf7e95e6a1d3473b22cf6cf56ace515afb5dacbae0e9f72519efaa")}


def sha_file(p):
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for ch in iter(lambda: f.read(1 << 20), b""):
            h.update(ch)
    return h.hexdigest()


def canonical_model_hash(m: U.Model):
    """Content hash independent of whitespace / number formatting: network type, cardinalities, scopes, tables as reduced rationals."""
    h = hashlib.sha256(); h.update(m.net_type.encode()); h.update(json.dumps(m.card).encode())
    for f in m.factors:
        h.update(json.dumps([list(f.scope), [str(x) for x in f.table]], separators=(",", ":")).encode())
    return h.hexdigest()


def canonical_evidence_hash(ev: dict):
    return hashlib.sha256(json.dumps(sorted(ev.items()), separators=(",", ":")).encode()).hexdigest()


def family_of(name, archive):
    base = name[:-4] if name.endswith(".uai") else name
    if archive == "uai2022_final" and re.fullmatch(r"\d\w{3}", base):
        return "Protein"
    if archive == "uai2022_final" and base.startswith("BN_"):
        return "GridBN"
    fam = re.sub(r"[_-]?\d.*$", "", base)
    return {"Promedas": "Promedus", "ObjDetect": "ObjectDetection", "Segment": "Segmentation"}.get(fam, fam)


def structure(m: U.Model, ev: dict):
    card = collections.Counter(m.card); tot = sum(f.size() for f in m.factors); mx = max(f.size() for f in m.factors)
    zeros = 0; pos_min = None; pos_max = None
    for f in m.factors:
        for t in f.table:
            if t == 0:
                zeros += 1
            else:
                pos_min = t if pos_min is None or t < pos_min else pos_min; pos_max = t if pos_max is None or t > pos_max else pos_max
    adj = collections.defaultdict(set)
    for f in m.factors:
        for a in f.scope:
            for b in f.scope:
                if a != b:
                    adj[a].add(b)
    seen = set(); comps = 0
    for v in range(m.nvars):
        if v in seen:
            continue
        comps += 1; stack = [v]
        while stack:
            x = stack.pop()
            if x in seen:
                continue
            seen.add(x); stack.extend(adj[x])
    deg = [len(adj[v]) for v in range(m.nvars)]
    ar = collections.Counter(len(f.scope) for f in m.factors)
    child_last = collections.Counter(f.scope[-1] for f in m.factors)
    bn_like = all(child_last[v] == 1 for v in range(m.nvars)) and len(m.factors) == m.nvars
    pair_tabs = [f for f in m.factors if len(f.scope) == 2 and f.card == (2, 2)]
    sym = sum(1 for f in pair_tabs if f.table[1] == f.table[2])
    return {"variables": m.nvars, "factors": len(m.factors), "domain_histogram": {str(k): v for k, v in sorted(card.items())}, "max_arity": max(ar), "arity_histogram": {str(k): v for k, v in sorted(ar.items())},
            "table_entries_total": tot, "table_entries_largest": mx, "exact_zeros": zeros, "zero_fraction": zeros / tot,
            "positive_dynamic_range_log10": (math.log10(float(pos_max / pos_min)) if pos_min else None), "evidence_count": len(ev),
            "connected_components": comps, "degree_mean": sum(deg) / max(1, m.nvars), "degree_max": max(deg) if deg else 0, "degree_min": min(deg) if deg else 0,
            "topology": ("one CPT per variable (child last)" if bn_like else ("binary pairwise" if all(c == 2 for c in m.card) and max(ar) <= 2 else "general factor graph")),
            "binary_pairwise_symmetric_tables": sym, "binary_pairwise_tables": len(pair_tabs), "net_type": m.net_type}


def main(S):
    src = os.path.join(S, "sources"); inv = []
    archives = {"uai2022_tuning": {"dir": os.path.join(src, "uai2022_tuning", "MAR"), "url": "https://www.ics.uci.edu/~dechter/uaicompetition/2022/TuningBenchmarks/MAR.zip",
                                   "note": "UAI 2022 tuning MAR archive = the UAI 2014 MAR problem set (all 120 models byte-identical to Uai14/MAR_prob.tar.gz)"},
                "uai2022_final": {"dir": os.path.join(src, "uai2022_final", "MAR"), "url": "https://www.ics.uci.edu/~dechter/uaicompetition/2022/FinalBenchmarks/MAR.zip", "note": "UAI 2022 final MAR archive"}}
    seen_canon = {}
    for arch, info in archives.items():
        for fn in sorted(os.listdir(info["dir"])):
            if not fn.endswith(".uai"):
                continue
            mp = os.path.join(info["dir"], fn); ep = mp + ".evid"
            if not os.path.exists(ep):
                continue
            m = U.read_model(mp); ev = U.read_evidence(ep)
            cm, ce = canonical_model_hash(m), canonical_evidence_hash(ev)
            key = (cm, ce); dup = seen_canon.get(key)
            row = {"case": fn[:-4], "family": family_of(fn, arch), "archive": arch, "source_url": info["url"], "license": "competition benchmark distribution (UAI / UCI); see source page",
                   "model_path": os.path.relpath(mp, S), "evidence_path": os.path.relpath(ep, S), "raw_model_sha256": sha_file(mp), "raw_evidence_sha256": sha_file(ep),
                   "canonical_model_sha256": cm, "canonical_evidence_sha256": ce, "evidence_identity": "single assignment (UAI 2014 layout: <n> <var> <state> ...)",
                   "duplicate_of": dup, "task": "MAR under the supplied evidence (all unobserved variables)", "structure": structure(m, ev)}
            if dup is None:
                seen_canon[key] = fn[:-4]
            inv.append(row)
    for n in BNLEARN:
        mp = os.path.join(src, "bnlearn_uai", n + ".uai"); ep = mp + ".evid"; m = U.read_model(mp); ev = U.read_evidence(ep)
        conv = json.load(open(os.path.join(src, "bnlearn_uai", n + ".bif2uai.json")))
        inv.append({"case": n.upper(), "family": "bnlearn", "archive": "bnlearn", "source_url": "https://www.bnlearn.com/bnrepository/ (official per-network BIF links)", "license": "bnlearn repository (see network page)",
                    "model_path": os.path.relpath(mp, S), "evidence_path": os.path.relpath(ep, S), "bif_path": os.path.relpath(os.path.join(src, "bnlearn", n + ".bif.gz"), S), "raw_bif_sha256": sha_file(os.path.join(src, "bnlearn", n + ".bif.gz")),
                    "raw_model_sha256": sha_file(mp), "raw_evidence_sha256": sha_file(ep), "canonical_model_sha256": canonical_model_hash(m), "canonical_evidence_sha256": canonical_evidence_hash(ev),
                    "evidence_identity": "none (native no-evidence task)", "duplicate_of": None, "task": "MAR, no evidence (prior marginals of every variable)",
                    "conversion": {"entries_verified": conv["verification"]["entries_checked"], "row_sum_defects": len(conv["row_sum_defects"]), "note": conv["axis_convention"]}, "structure": structure(m, ev)})
    json.dump({"note": "every accessible case; selection in PANEL_SELECTION.json; no reference values were read", "cases": inv}, open(os.path.join(S, "INVENTORY.json"), "w"), indent=1)
    # ---- selection: per family, sort by (total raw table entries, source-relative path, content hash); quartile floor(4 i / n); min SHA256 of the tag string
    sel = {"rule": "CBI-EXTERNAL-48-v1: within family sort by (table_entries_total, model_path, canonical_model_sha256); quartile floor(4*i/n) (0-based); per nonempty quartile pick min SHA256('CBI-EXTERNAL-48-v1\\n<model-sha>\\n<evidence-sha>'); anchors forced into their quartile after hash binding",
           "target_denominator": 48, "families": {}, "selected": [], "anchors": {}, "shortfalls": {}}
    for fam in FAMILIES:
        rows = [r for r in inv if r["family"] == fam and r["duplicate_of"] is None]
        rows.sort(key=lambda r: (r["structure"]["table_entries_total"], r["model_path"], r["canonical_model_sha256"]))
        n = len(rows); quart = {}
        for i, r in enumerate(rows):
            q = (4 * i) // n; r["_q"] = q; quart.setdefault(q, []).append(r)
        chosen = {}
        for q, lst in quart.items():
            tag = lambda r: hashlib.sha256(("CBI-EXTERNAL-48-v1\n%s\n%s" % (r["canonical_model_sha256"], r["canonical_evidence_sha256"])).encode()).hexdigest()
            chosen[q] = min(lst, key=tag)
        anchor_note = None
        if fam in ANCHORS:
            an, hm, he = ANCHORS[fam]; cand = [r for r in rows if r["case"] == an and r["raw_model_sha256"] == hm and r["raw_evidence_sha256"] == he]
            if cand:
                a = cand[0]; replaced = chosen[a["_q"]]["case"]; chosen[a["_q"]] = a
                anchor_note = {"case": an, "quartile": a["_q"], "replaced_hashed_choice": replaced if replaced != an else None, "bound_to_historical_hashes": True}
            else:
                anchor_note = {"case": an, "bound_to_historical_hashes": False, "note": "anchor not identified by hash; deterministic selection retained"}
            sel["anchors"][fam] = anchor_note
        picks = [chosen[q] for q in sorted(chosen)]
        sel["families"][fam] = {"available_distinct": n, "selected": [r["case"] for r in picks], "quartiles": {str(q): chosen[q]["case"] for q in sorted(chosen)}, "aliases": ALIASES.get(fam, []),
                                "all_available": [r["case"] for r in rows]}
        if n < 4:
            sel["shortfalls"][fam] = {"available": n, "target": 4}
        for r in picks:
            sel["selected"].append({"case": r["case"], "family": fam, "quartile": r["_q"], "anchor": bool(fam in ANCHORS and r["case"] == ANCHORS[fam][0]), "model_path": r["model_path"], "evidence_path": r["evidence_path"],
                                    "canonical_model_sha256": r["canonical_model_sha256"], "canonical_evidence_sha256": r["canonical_evidence_sha256"]})
    for r in inv:
        r.pop("_q", None)
    for r in inv:
        if r["family"] == "bnlearn":
            sel["selected"].append({"case": r["case"], "family": "bnlearn", "quartile": None, "anchor": False, "model_path": r["model_path"], "evidence_path": r["evidence_path"],
                                    "canonical_model_sha256": r["canonical_model_sha256"], "canonical_evidence_sha256": r["canonical_evidence_sha256"]})
    # depth: per UAI family the selected case in quartile 2, else the nonempty selected quartile closest to 2 (lower on ties); bnlearn ASIA, ALARM, ANDES
    depth = []
    for fam in FAMILIES:
        qs = {int(q): c for q, c in sel["families"][fam]["quartiles"].items()}
        if not qs:
            continue
        q = 2 if 2 in qs else min(qs, key=lambda x: (abs(x - 2), x))
        depth.append({"case": qs[q], "family": fam, "quartile": q})
    for c in ("ASIA", "ALARM", "ANDES"):
        depth.append({"case": c, "family": "bnlearn", "quartile": None})
    sel["depth_cases"] = depth; sel["accessible"] = len(sel["selected"])
    json.dump(sel, open(os.path.join(S, "PANEL_SELECTION.json"), "w"), indent=1)
    print("inventory", len(inv), "cases;", "selected", len(sel["selected"]), "of 48;", "shortfalls", sel["shortfalls"]); print("anchors", sel["anchors"])
    for fam in FAMILIES:
        print("  %-16s n=%2d  %s" % (fam, sel["families"][fam]["available_distinct"], sel["families"][fam]["quartiles"]))
    print("depth:", [d["case"] for d in depth])


if __name__ == "__main__":
    main(sys.argv[1])
