"""Exact rational MAR by brute-force enumeration for tiny UAI models (control oracle only)."""
import sys, itertools; sys.path.insert(0, "/Users/adis/Workspace/pgm/code")
from fractions import Fraction as Fr
from ext import uai as U
def mar(mp, ep):
    m = U.read_model(mp); ev = U.read_evidence(ep); Z = Fr(0); num = {v: [Fr(0)] * m.card[v] for v in range(m.nvars)}
    for assign in itertools.product(*[range(c) for c in m.card]):
        if any(assign[v] != s for v, s in ev.items()): continue
        w = Fr(1)
        for f in m.factors: w *= f.at({v: assign[v] for v in f.scope})
        Z += w
        for v in range(m.nvars): num[v][assign[v]] += w
    return Z, {v: [x / Z for x in num[v]] for v in range(m.nvars)} if Z else None
if __name__ == "__main__":
    Z, M = mar(sys.argv[1], sys.argv[2]); print("Z =", Z)
    for v, row in M.items(): print(v, [float(x) for x in row])
