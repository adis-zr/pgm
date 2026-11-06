"""Derived positive diagnostic inputs from an ORIGINAL .uai (before evidence restriction): for every factor occurrence
with smallest positive entry m_f, every zero entry becomes lambda * m_f (exact); every positive entry is unchanged; the
graph, domains, occurrence multiplicities, evidence and queries are unchanged. lambda in {1e-6, 1e-4, 1e-2, 1}.
Writes <stem>_L<tag>.uai (exact decimal tokens) + the unchanged evidence file, and GENERATION.json (hashes, counts, the
zero locations -- generator annotations that the solver and the certificate checker never read).
usage: generate.py ORIGINAL.uai ORIGINAL.uai.evid OUT_DIR"""
import sys, os, json, hashlib
from fractions import Fraction as Fr
HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)
from mdi import model as M

LAMBDAS = [("1e-6", Fr(1, 10 ** 6)), ("1e-4", Fr(1, 10 ** 4)), ("1e-2", Fr(1, 10 ** 2)), ("1", Fr(1))]


def fr_decimal(x):
    """Exact decimal string of a rational whose denominator is 2^a 5^b (asserted)."""
    x = Fr(x)
    if x == 0:
        return "0"
    d = x.denominator; a = b = 0
    while d % 2 == 0: d //= 2; a += 1
    while d % 5 == 0: d //= 5; b += 1
    assert d == 1, "not a terminating decimal: %s" % x
    k = max(a, b)
    scaled = x * Fr(10) ** k
    assert scaled.denominator == 1
    s = str(scaled.numerator).rjust(k + 1, "0")
    return s if k == 0 else (s[:-k] + "." + s[-k:])


def write_uai(m, path):
    lines = [m.net_type, str(m.nvars), " ".join(str(c) for c in m.card), str(len(m.factors))]
    for f in m.factors:
        lines.append("%d %s" % (len(f.scope), " ".join(str(v) for v in f.scope)))
    for f in m.factors:
        lines.append(""); lines.append(str(len(f.table))); lines.append(" ".join(fr_decimal(x) for x in f.table))
    data = ("\n".join(lines) + "\n").encode("ascii")
    open(path, "wb").write(data)
    return hashlib.sha256(data).hexdigest()


def main(orig, evid, out):
    os.makedirs(out, exist_ok=False)
    m = M.read_uai(orig)
    stem = os.path.basename(orig)[:-4]
    ann = {"original": {"uai": orig, "sha256": hashlib.sha256(open(orig, "rb").read()).hexdigest(), "evid_sha256": hashlib.sha256(open(evid, "rb").read()).hexdigest(),
                        "nvars": m.nvars, "factors": len(m.factors), "entries": sum(len(f.table) for f in m.factors), "zeros": sum(1 for f in m.factors for x in f.table if x == 0)},
           "rule": "for every ORIGINAL occurrence f with smallest positive entry m_f, every zero entry := lambda * m_f (exact decimal); positives unchanged; evidence copied unchanged",
           "zero_locations": {str(f.origin): [i for i, x in enumerate(f.table) if x == 0] for f in m.factors if any(x == 0 for x in f.table)},
           "m_f": {str(f.origin): fr_decimal(min(Fr(x) for x in f.table if x > 0)) for f in m.factors if any(x > 0 for x in f.table)},
           "exceptional_factors": [f.origin for f in m.factors if not any(x > 0 for x in f.table)], "inputs": {}}
    assert not ann["exceptional_factors"], "a factor with no positive entry has no m_f: verify before launch"
    ev_bytes = open(evid, "rb").read()
    for tag, lam in LAMBDAS:
        facs = []
        for f in m.factors:
            mf = min(Fr(x) for x in f.table if x > 0)
            facs.append(M.Factor(scope=f.scope, card=f.card, table=[(lam * mf if x == 0 else Fr(x)) for x in f.table], origin=f.origin))
        mm = M.Model(nvars=m.nvars, card=list(m.card), factors=facs, net_type=m.net_type).validate()
        name = "%s_L%s" % (stem, tag)
        h = write_uai(mm, os.path.join(out, name + ".uai"))
        open(os.path.join(out, name + ".uai.evid"), "wb").write(ev_bytes)
        back = M.read_uai(os.path.join(out, name + ".uai"))                    # read back: exact equality with the intended tables
        assert all([Fr(x) for x in a.table] == [Fr(x) for x in b.table] and a.scope == b.scope for a, b in zip(mm.factors, back.factors))
        ann["inputs"][name] = {"lambda": tag, "uai_sha256": h, "evid_sha256": hashlib.sha256(ev_bytes).hexdigest(),
                               "zeros_after": sum(1 for f in back.factors for x in f.table if x == 0),
                               "min_entry": fr_decimal(min(Fr(x) for f in back.factors for x in f.table)),
                               "read_back_exact": True}
    json.dump(ann, open(os.path.join(out, "GENERATION.json"), "w"), indent=1)
    print(json.dumps({k: {kk: vv for kk, vv in v.items() if kk != "zero_locations"} for k, v in ann["inputs"].items()}, indent=1))


if __name__ == "__main__":
    main(*sys.argv[1:4])
