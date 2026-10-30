"""Fixed forest controls for the STRICT masked representation (Gate A).

Each control runs the recognizer and admission on a fixed model and reports,
per masked candidate, the mask, whether the representation is strict, the
ACTUAL residual pair scopes and the largest residual bag (the maximum product
of cardinalities over a residual factor's scope), and the fit allowance it
charges. A strict masked representation keeps ONLY the mask's positive pair
interactions; every other positive pair is gauge-transferred exactly and its
interaction removed with a certified discrepancy. It may decline on its fit
bound; the dense compensating residual remains a differently named
alternative.

    python -m portfolio.strict_mask [OUT.json]

The file in the overseer packet was not available on this machine; this is
the build's own implementation of the named controls, labelled as such.
"""
from __future__ import annotations
import sys, os, json, math
sys.set_int_max_str_digits(0)
from fractions import Fraction as Fr

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, "tests"))


def _pair(J):
    e = math.exp(J)
    D = 10 ** 6
    return [Fr(round(e * D), D), Fr(round(D / e), D), Fr(round(D / e), D), Fr(round(e * D), D)]


def fixtures():
    from mdi import model as M
    from tests.test_mdi_research import mean_field, w, ring_of_blocks
    out = []
    f6 = [0.1 * (k + 1) * (1 if k % 2 == 0 else -1) for k in range(6)]
    out.append(("mean-field 6 J=+0.30 (complete graph)", M.read_uai(w(mean_field(6, 0.30, f6)))))
    out.append(("mean-field 6 J=-0.22 (complete graph)", M.read_uai(w(mean_field(6, -0.22, f6)))))
    out.append(("ring of blocks", M.read_uai(w(ring_of_blocks()[0]))))
    # a 3x3 grid with heterogeneous couplings: a forest mask keeps 8 of 12 edges
    n = 9
    facs = [M.Factor(scope=(v,), card=(2,), table=[Fr(1), Fr(1) + Fr(1 + v % 4, 20)], origin=v) for v in range(n)]
    k = 0
    for i in range(3):
        for j in range(3):
            v = 3 * i + j
            if j < 2:
                facs.append(M.Factor(scope=(v, v + 1), card=(2, 2), table=_pair(0.08 + 0.03 * (k % 3)), origin=100 + k)); k += 1
            if i < 2:
                facs.append(M.Factor(scope=(v, v + 3), card=(2, 2), table=_pair(0.06 + 0.02 * (k % 4)), origin=100 + k)); k += 1
    out.append(("3x3 grid, heterogeneous positive couplings", M.Model(nvars=n, card=[2] * n, factors=facs).validate()))
    return out


def run(out_path=None):
    from mdi import model as M, marked as MK, collective_route as CR, arith as A
    rows = []
    for label, m in fixtures():
        r = M.restrict(m, {})
        q = set(r.free)
        try:
            adm = CR.admit(MK.Marked.from_restricted(r, q), A.Ctx(96))
        except CR.Declined as e:
            rows.append({"fixture": label, "declined": str(e)[:160]})
            continue
        declines = [d for d in (adm[0][0].get("declines") or []) if "strict" in d]
        seen = set()
        cands = []
        for c, rmk in adm:
            cd = c["candidate"]
            key = (cd.kind, c["evaluator"])
            if key in seen or not cd.masked:
                continue
            seen.add(key)
            pairs = sorted(tuple(int(x) for x in f.scope) for f in rmk.factors if len(f.scope) == 2)
            bag = 0
            for f in rmk.factors:
                sz = 1
                for v in f.scope:
                    sz *= rmk.card[v]
                bag = max(bag, sz)
            cands.append({"kind": cd.kind, "evaluator": c["evaluator"], "strict": bool(cd.strict),
                          "mask_pairs": [list(p) for p in cd.masked], "residual_pair_scopes": [list(p) for p in pairs],
                          "residual_pairs_equal_mask": sorted(tuple(p) for p in pairs) == sorted(tuple(p) for p in cd.masked),
                          "largest_residual_bag_entries": bag, "fit_tv": str(c["fit_tv"]),
                          "kept_factors": len(c["kept_factors"]), "dropped_pairs": len(c["dropped_pairs"])})
        n_pos = sum(1 for f in r.factors if len(f.scope) == 2)
        rows.append({"fixture": label, "variables": len(r.free), "pair_factors": n_pos,
                     "masked_candidates": cands, "strict_declines": declines[:6]})
    out = {"rows": rows, "note": "build's own implementation of the fixed forest controls; strict = residual "
                                 "pairs are exactly the mask; dense compensating residual is the differently "
                                 "named alternative"}
    if out_path:
        with open(out_path, "w") as fh:
            json.dump(out, fh, indent=1)
    return out


if __name__ == "__main__":
    res = run(sys.argv[1] if len(sys.argv) > 1 else None)
    for row in res["rows"]:
        print("==", row["fixture"], "vars", row.get("variables"), "pairs", row.get("pair_factors"))
        for c in row.get("masked_candidates", []):
            print("   %-36s strict=%-5s mask=%2d residual pairs=%2d equal=%s largest bag=%d fit_tv=%s"
                  % (c["kind"], c["strict"], len(c["mask_pairs"]), len(c["residual_pair_scopes"]),
                     c["residual_pairs_equal_mask"], c["largest_residual_bag_entries"], c["fit_tv"][:12]))
        for d in row.get("strict_declines", []):
            print("   decline:", d[:140])
