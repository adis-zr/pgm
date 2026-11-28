"""Frozen benchmark generator: a deterministic SHA-256 counter stream, domain-separated per (panel, block, seed label); bits drawn by
EXACT integer choices (p = 3/4: two stream bits, +1 iff they are not both zero; p = 1/2: one bit). Antipodal panel: m/2 strings z
(duplicates and previously accepted antipodes rejected), A = {z, -z} weight 1 in accepted order; B = the first m/8 originally
generated z rows, then unique Bernoulli-p strings from the B stream until |B| = m, weight 1. Ordinary panel: m unique unbiased A
rows; B = the first m/8 A rows + unique unbiased rows. Writes <panel>.json ({n, A: [[mask, w]...], B: [...]}) and PANELS.json."""
import sys, os, json, hashlib
from pgm.algorithms.sf.core import BIT_CONVENTION

GENERATOR_VERSION = "sf-gen-1 (SHA-256 counter stream; tag = panel|block|seed|counter; bits consumed MSB-first per 32-byte block)"
PANELS = [{"name": "small_control", "n": 12, "m": 128, "kind": "antipodal", "p": "3/4", "seed": 0},
          {"name": "primary_A", "n": 24, "m": 4096, "kind": "antipodal", "p": "3/4", "seed": 0},
          {"name": "primary_B", "n": 24, "m": 4096, "kind": "antipodal", "p": "3/4", "seed": 1},
          {"name": "ordinary_control", "n": 24, "m": 4096, "kind": "ordinary", "p": "1/2", "seed": 0}]


class Stream:
    def __init__(self, panel, block, seed):
        self.tag = "%s|%s|%d" % (panel, block, seed); self.ctr = 0; self.buf = 0; self.nbits = 0

    def bit(self):
        if self.nbits == 0:
            h = hashlib.sha256(("%s|%d" % (self.tag, self.ctr)).encode()).digest(); self.ctr += 1
            self.buf = int.from_bytes(h, "big"); self.nbits = 256
        self.nbits -= 1
        return (self.buf >> self.nbits) & 1

    def coord(self, p):
        if p == "1/2":
            return self.bit()
        if p == "3/4":
            b1 = self.bit(); b2 = self.bit(); return 0 if (b1 == 0 and b2 == 0) else 1
        raise ValueError(p)

    def string(self, n, p):
        x = 0
        for i in range(n):                                   # coordinate i <-> bit i
            if self.coord(p):
                x |= (1 << i)
        return x


def generate(panel):
    n, m, kind, p, seed = panel["n"], panel["m"], panel["kind"], panel["p"], panel["seed"]
    full = (1 << n) - 1
    sa = Stream(panel["name"], "A", seed); sb = Stream(panel["name"], "B", seed)
    stats = {"A_draws": 0, "A_rejected_duplicate": 0, "A_rejected_antipode": 0, "B_draws": 0, "B_rejected_duplicate": 0}
    if kind == "antipodal":
        assert m % 8 == 0
        accepted = []; seen = set()
        while len(accepted) < m // 2:
            z = sa.string(n, p); stats["A_draws"] += 1
            if z in seen:
                stats["A_rejected_duplicate" if z in accepted else "A_rejected_antipode"] += 1; continue
            accepted.append(z); seen.add(z); seen.add(full ^ z)
        A = []
        for z in accepted:
            A.append([z, 1]); A.append([full ^ z, 1])
        B = [[z, 1] for z in accepted[: m // 8]]; bseen = set(accepted[: m // 8])
        while len(B) < m:
            y = sb.string(n, p); stats["B_draws"] += 1
            if y in bseen:
                stats["B_rejected_duplicate"] += 1; continue
            B.append([y, 1]); bseen.add(y)
    else:
        A = []; seen = set()
        while len(A) < m:
            x = sa.string(n, "1/2"); stats["A_draws"] += 1
            if x in seen:
                stats["A_rejected_duplicate"] += 1; continue
            A.append([x, 1]); seen.add(x)
        B = [[x, 1] for x, _ in A[: m // 8]]; bseen = set(x for x, _ in B)
        while len(B) < m:
            y = sb.string(n, "1/2"); stats["B_draws"] += 1
            if y in bseen:
                stats["B_rejected_duplicate"] += 1; continue
            B.append([y, 1]); bseen.add(y)
    return {"n": n, "A": A, "B": B, "panel": dict(panel), "bit_convention": BIT_CONVENTION, "generator": GENERATOR_VERSION, "stats": stats}


def main(out):
    os.makedirs(out, exist_ok=False)
    man = {"generator": GENERATOR_VERSION, "bit_convention": BIT_CONVENTION, "panels": {}}
    for p in PANELS:
        d = generate(p); path = os.path.join(out, p["name"] + ".json")
        data = json.dumps(d, separators=(",", ":")).encode(); open(path, "wb").write(data)
        inter = len(set(x for x, _ in d["A"]) & set(y for y, _ in d["B"]))
        man["panels"][p["name"]] = {**p, "sha256": hashlib.sha256(data).hexdigest(), "mA": len(d["A"]), "mB": len(d["B"]), "intersection": inter, "stats": d["stats"]}
    json.dump(man, open(os.path.join(out, "PANELS.json"), "w"), indent=1)
    print(json.dumps(man["panels"], indent=1))


if __name__ == "__main__":
    main(sys.argv[1])
