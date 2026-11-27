"""BIF (Bayesian Interchange Format, bnlearn flavour) -> exact UAI BAYES conversion with INDEPENDENT entrywise verification.

Semantics preserved: variable order = declaration order; state labels kept; each `probability ( child | parents ) { ... }` block becomes one
UAI factor with scope (parents in the BIF's declared order, child LAST) so the UAI table (last variable fastest) lists, for every parent
configuration in BIF row order, the child's distribution row verbatim. Decimal literals are parsed as EXACT rationals (Fraction('0.05'));
nothing is renormalized: a row that does not sum to one is REPORTED (`row_sum_defects`), never repaired. The verifier re-reads both files
with its own minimal parsers and checks every entry by (parent-configuration, child-state) lookup."""
from __future__ import annotations
from fractions import Fraction as Fr
import re, json, hashlib, gzip, itertools


def _read(path):
    data = gzip.open(path, "rb").read() if path.endswith(".gz") else open(path, "rb").read()
    return data.decode("utf-8", errors="strict")


def _strip_comments(s):
    s = re.sub(r"//.*", "", s); s = re.sub(r"/\*.*?\*/", "", s, flags=re.S); return s


def parse_bif(path):
    """Returns (variables: [(name, [states])], cpts: [(child, [parents], rows)]) with rows = {parent_state_tuple: [Fr...]} ('table' rows have key ())."""
    s = _strip_comments(_read(path))
    variables = []; names = set()
    for m in re.finditer(r"variable\s+(\S+)\s*\{((?:[^{}]|\{[^{}]*\})*)\}", s, flags=re.S):
        name, body = m.group(1), m.group(2)
        t = re.search(r"type\s+discrete\s*\[\s*(\d+)\s*\]\s*\{(.*?)\}", body, flags=re.S)
        if not t:
            raise ValueError("variable %s: only discrete variables are supported" % name)
        states = [x.strip() for x in t.group(2).split(",") if x.strip()]
        if len(states) != int(t.group(1)):
            raise ValueError("variable %s: declared %s states, listed %d" % (name, t.group(1), len(states)))
        if name in names:
            raise ValueError("duplicate variable %s" % name)
        names.add(name); variables.append((name, states))
    cpts = []
    for m in re.finditer(r"probability\s*\(\s*([^|)]+?)\s*(?:\|\s*([^)]*?))?\s*\)\s*\{(.*?)\}", s, flags=re.S):
        child = m.group(1).strip(); parents = [p.strip() for p in (m.group(2) or "").split(",") if p.strip()]; body = m.group(3)
        rows = {}
        for line in body.split(";"):
            line = line.strip()
            if not line:
                continue
            if line.startswith("table"):
                vals = [Fr(x) for x in line[len("table"):].replace(",", " ").split()]
                rows[()] = vals
            else:
                mm = re.match(r"\((.*?)\)\s*(.*)$", line, flags=re.S)
                if not mm:
                    raise ValueError("CPT %s: unparsed row %r" % (child, line[:60]))
                key = tuple(x.strip() for x in mm.group(1).split(",")); vals = [Fr(x) for x in mm.group(2).replace(",", " ").split()]
                if key in rows:
                    raise ValueError("CPT %s: duplicate row %s" % (child, key))
                rows[key] = vals
        cpts.append((child, parents, rows))
    return variables, cpts


def bif_to_uai(path):
    """Returns (uai_text, record). Factor i = CPT of variable i in variable-declaration order (one CPT per variable required)."""
    variables, cpts = parse_bif(path)
    idx = {n: i for i, (n, _) in enumerate(variables)}; card = [len(st) for _, st in variables]; states = {n: st for n, st in variables}
    by_child = {}
    for child, parents, rows in cpts:
        if child in by_child:
            raise ValueError("two CPTs for %s" % child)
        by_child[child] = (parents, rows)
    if set(by_child) != set(idx):
        raise ValueError("CPTs do not cover exactly the declared variables")
    factors = []; defects = []; zeros = 0; total = 0
    for name, st in variables:
        parents, rows = by_child[name]
        scope = [idx[p] for p in parents] + [idx[name]]
        combos = list(itertools.product(*[states[p] for p in parents])) if parents else [()]
        if set(rows) != set(combos) and not (not parents and set(rows) == {()}):
            missing = [c for c in combos if c not in rows]
            raise ValueError("CPT %s: rows do not cover the parent configurations (missing %s...)" % (name, missing[:2]))
        table = []
        for c in combos:
            r = rows[c]
            if len(r) != len(st):
                raise ValueError("CPT %s row %s: %d values for %d states" % (name, c, len(r), len(st)))
            if sum(r) != 1:
                defects.append({"child": name, "parents": c, "row_sum": str(sum(r))})
            table.extend(r)
        zeros += sum(1 for x in table if x == 0); total += len(table)
        factors.append((scope, table))
    lines = ["BAYES", str(len(variables)), " ".join(str(c) for c in card), str(len(factors))]
    for scope, _ in factors:
        lines.append("%d %s" % (len(scope), " ".join(str(v) for v in scope)))
    lines.append("")
    for _, table in factors:
        lines.append(str(len(table))); lines.append(" ".join(_dec(x) for x in table)); lines.append("")
    text = "\n".join(lines)
    rec = {"source": path, "variables": [{"name": n, "states": st} for n, st in variables], "n_vars": len(variables), "n_factors": len(factors),
           "card": card, "max_arity": max(len(sc) for sc, _ in factors), "table_entries": total, "exact_zeros": zeros, "row_sum_defects": defects,
           "axis_convention": "scope = parents (BIF order) then child LAST; UAI table lists child rows per parent configuration in BIF row order (last variable fastest)",
           "number_semantics": "decimal literals parsed as exact rationals; written back as exact decimals (every BIF literal is a finite decimal)"}
    return text, rec


def _dec(x: Fr):
    """Exact decimal text for a rational whose denominator divides a power of ten (every BIF literal); otherwise a/b fraction text."""
    n, d = x.numerator, x.denominator; k = 0; dd = d
    while dd % 2 == 0:
        dd //= 2; k += 1
    while dd % 5 == 0:
        dd //= 5; k += 1
    if dd != 1:
        return "%d/%d" % (n, d)
    p = 0; q = 1
    while q % d != 0:
        q *= 10; p += 1
    s = str(n * (q // d)).rjust(p + 1, "0")
    return (s[:-p] + "." + s[-p:]) if p else s


# ------------------------------------------------------------------ INDEPENDENT verification (own parsers; entrywise by lookup)
def _mini_bif(path):
    s = _strip_comments(_read(path)); out = {}
    order = re.findall(r"variable\s+(\S+)\s*\{", s)
    for m in re.finditer(r"probability\s*\(\s*([^|)]+?)\s*(?:\|\s*([^)]*?))?\s*\)\s*\{(.*?)\}", s, flags=re.S):
        child = m.group(1).strip(); parents = tuple(p.strip() for p in (m.group(2) or "").split(",") if p.strip())
        rows = {}
        for line in m.group(3).split(";"):
            line = line.strip()
            if not line:
                continue
            if line.startswith("table"):
                rows[()] = [Fr(x) for x in line[5:].replace(",", " ").split()]
            else:
                mm = re.match(r"\((.*?)\)\s*(.*)$", line, flags=re.S); rows[tuple(x.strip() for x in mm.group(1).split(","))] = [Fr(x) for x in mm.group(2).replace(",", " ").split()]
        out[child] = (parents, rows)
    states = {m.group(1): [x.strip() for x in m.group(2).split(",") if x.strip()] for m in re.finditer(r"variable\s+(\S+)\s*\{[^{}]*?\{([^{}]*)\}[^{}]*\}", s, flags=re.S)}
    return order, states, out


def verify_bif_uai(bif_path, uai_text):
    """Every UAI entry is looked up in the BIF by (parent configuration, child state); counts and cardinalities are cross-checked."""
    order, states, cpts = _mini_bif(bif_path)
    toks = uai_text.split(); assert toks[0] == "BAYES", "network type"
    n = int(toks[1]); card = [int(x) for x in toks[2:2 + n]]; nf = int(toks[2 + n]); p = 3 + n
    assert n == len(order) and nf == n, "variable / factor counts"
    assert card == [len(states[v]) for v in order], "cardinalities"
    scopes = []
    for _ in range(nf):
        k = int(toks[p]); scopes.append([int(x) for x in toks[p + 1:p + 1 + k]]); p += 1 + k
    checked = 0
    for i, sc in enumerate(scopes):
        child = order[sc[-1]]; parents, rows = cpts[child]
        assert tuple(order[v] for v in sc[:-1]) == parents, "factor %d: scope is not (parents, child) in BIF order" % i
        cnt = int(toks[p]); p += 1; vals = [Fr(x) for x in toks[p:p + cnt]]; p += cnt
        cards = [len(states[order[v]]) for v in sc]; exp = 1
        for c in cards:
            exp *= c
        assert cnt == exp, "factor %d: table length" % i
        strides = [1] * len(sc)
        for k in range(len(sc) - 2, -1, -1):
            strides[k] = strides[k + 1] * cards[k + 1]
        for flat in range(cnt):
            conf = [(flat // strides[k]) % cards[k] for k in range(len(sc))]
            key = tuple(states[order[sc[k]]][conf[k]] for k in range(len(sc) - 1)); cs = conf[-1]
            assert vals[flat] == rows[key][cs], "factor %d entry %d: UAI %s != BIF %s at %s state %s" % (i, flat, vals[flat], rows[key][cs], key, cs)
            checked += 1
    assert p == len(toks), "trailing tokens"
    return {"entries_checked": checked, "factors": nf, "variables": n}


if __name__ == "__main__":
    import sys
    text, rec = bif_to_uai(sys.argv[1]); open(sys.argv[2], "w").write(text)
    rec["verification"] = verify_bif_uai(sys.argv[1], text); rec["uai_sha256"] = hashlib.sha256(text.encode()).hexdigest()
    json.dump(rec, open(sys.argv[3], "w"), indent=1); print(json.dumps({k: rec[k] for k in ("n_vars", "n_factors", "max_arity", "table_entries", "exact_zeros", "verification")}, default=str), "row_sum_defects:", len(rec["row_sum_defects"]))
