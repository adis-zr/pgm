"""Exact source layer of AGGREGATE_DP_V1 (producer side): parsing (reused exact parser), evidence restriction, the
bounded exact source reductions with witnesses, and the original-query DECODERS. Nothing here is numeric.

Reduced model: variables are ORIGINAL ids; `dom[v]` is the sorted tuple of currently allowed ORIGINAL states; a factor
table is a dense list over the POSITIONS of those domains in UAI order (first scope variable most significant, last
varies fastest). Every reduction is an identity of the restricted law proved from the exact source tables and is
recorded as a STEP with its witness; the independent checker (adp/checker.py) re-derives every step from the raw bytes
with its own parser, its own tables and its own code, and compares the reduced model hash.

Decoder entry of an original (variable, state): ("C", eta) -> the probability is the constant eta (valid once Z > 0);
("V", y, s, eta) -> eta * P(reduced variable y takes ORIGINAL state s).

Steps and their witnesses (checker re-derivation in adp/checker.py):
  exclude   (v, state, fid)         every entry of factor fid with v=state is zero  => no positive configuration has v=state
  fix       (v, state)              dom[v] == (state,)  => v is sliced out of every factor; decoders become constants
  const     (fid, origin, value, n) the factor is one positive constant on its whole domain => global scale (0 => Z = 0)
  separate  (fid, origin, axis, ufid, gfid|const) all rows along `axis` proportional => factor = unary(axis) x remainder
  alias     (w, u, states, fid)     in factor fid the positive entries project onto a bijection w = sigma(u)
  quotient  (v, classes, rho, W, wfid) states of v whose rows are proportional in EVERY factor containing v are merged
                                     into the smallest member; new unary W(rep) = sum rho; decoder eta_a = rho_a / W(rep)
A failed or capped recognizer leaves a valid unreduced factor; it never disqualifies the model.
"""
from __future__ import annotations
import sys, time, hashlib
sys.set_int_max_str_digits(0)
from fractions import Fraction as Fr
from itertools import product as iproduct
import numpy as np
from mdi import model as M                      # REUSED: exact decimal UAI parsing, evidence reading (accepted pin, read-only)

ALL_RULES = ("exclude", "constants", "separate", "alias", "quotient")


class Capped(Exception):
    pass


def strides_of(card):
    st = [1] * len(card); acc = 1
    for k in range(len(card) - 1, -1, -1):
        st[k] = acc; acc *= card[k]
    return tuple(st)


def prod(xs):
    n = 1
    for x in xs:
        n *= x
    return n


def table_hash(table):
    h = hashlib.sha256()
    for t in table:
        h.update(("%d/%d," % (t.numerator, t.denominator)).encode())
    return h.hexdigest()


class RFactor:
    __slots__ = ("fid", "scope", "card", "table", "origin", "_rows", "_sigs")

    def __init__(self, fid, scope, card, table, origin):
        self.fid = fid; self.scope = tuple(scope); self.card = tuple(card); self.table = table; self.origin = origin; self._rows = {}; self._sigs = {}

    def touched(self):
        self._rows = {}; self._sigs = {}

    def rows_along(self, k):
        """list over positions a of axis k of the row (tuple over the other axes, in their flat order); cached until the table changes."""
        r = self._rows.get(k)
        if r is None:
            arr = np.array(self.table, dtype=object).reshape(self.card)
            r = [tuple(x) for x in np.moveaxis(arr, k, 0).reshape(self.card[k], -1)]
            self._rows[k] = r
        return r

    def row_signatures(self, k):
        """per position a of axis k: (rep position of its proportionality class, ratio pivot_a / pivot_rep); None for an all-zero row's
        class is still formed (zero rows share the zero class with ratio 1). Cached until the table changes."""
        s = self._sigs.get(k)
        if s is None:
            groups = {}; out = []
            for a, row in enumerate(self.rows_along(k)):
                piv = next((z for z in row if z != 0), None)
                if piv is None:
                    key = ("Z",); rep, base = groups.setdefault(key, (a, Fr(1))); out.append((rep, Fr(1), True))
                else:
                    key = tuple(z / piv for z in row); rep, base = groups.setdefault(key, (a, piv)); out.append((rep, piv / base, False))
            s = out; self._sigs[k] = s
        return s

    def restrict_axis(self, k, keep):
        """Keep only positions `keep` (ordered) of axis k."""
        st = strides_of(self.card); n = len(self.table); blk = self.card[k] * st[k]; out = []
        for base in range(0, n, blk):
            for a in keep:
                out.extend(self.table[base + a * st[k]: base + (a + 1) * st[k]])
        self.table = out; self.card = self.card[:k] + (len(keep),) + self.card[k + 1:]; self.touched()

    def slice_axis(self, k, a):
        self.restrict_axis(k, [a]); self.scope = self.scope[:k] + self.scope[k + 1:]; self.card = self.card[:k] + self.card[k + 1:]

    def diagonal(self, kw, ku, sigma):
        """Axis kw := sigma(axis ku): keep entries with pos_w == sigma[pos_u]; drop axis kw. The output is laid out in the
        order of the REMAINING axes (iterated explicitly: a flat scan of the input would scramble it when kw < ku)."""
        st = strides_of(self.card); rest = [j for j in range(len(self.scope)) if j != kw]; ku_r = rest.index(ku); out = []
        for idx in iproduct(*[range(self.card[j]) for j in rest]):
            off = sum(idx[i] * st[rest[i]] for i in range(len(rest))) + sigma[idx[ku_r]] * st[kw]
            out.append(self.table[off])
        self.table = out; self.scope = self.scope[:kw] + self.scope[kw + 1:]; self.card = self.card[:kw] + self.card[kw + 1:]; self.touched()

    def relabel_axis(self, kw, u, sigma_inv):
        """Axis kw (variable w) becomes variable u with w = sigma(u): new position p_u reads old position sigma[p_u]."""
        card_u = len(sigma_inv); st = strides_of(self.card); n = len(self.table); blk = self.card[kw] * st[kw]; out = []
        for base in range(0, n, blk):
            for pu in range(card_u):
                a = sigma_inv[pu]; out.extend(self.table[base + a * st[kw]: base + (a + 1) * st[kw]])
        self.table = out; self.scope = self.scope[:kw] + (u,) + self.scope[kw + 1:]; self.card = self.card[:kw] + (card_u,) + self.card[kw + 1:]; self.touched()


def canonical_source_hashes(model_path, evid_path):
    def raw(p):
        return hashlib.sha256(open(p, "rb").read()).hexdigest()
    def canon(p):
        return hashlib.sha256((" ".join(open(p).read().split())).encode()).hexdigest()
    return {"raw_model_sha256": raw(model_path), "raw_evidence_sha256": raw(evid_path), "canonical_model_sha256": canon(model_path), "canonical_evidence_sha256": canon(evid_path)}


def load(model_path, evid_path):
    m = M.read_uai(model_path); ev = M.read_evidence(evid_path, m)
    return m, ev


class Reduced:
    """Mutable reduced model with its step ledger and decoders. `work` counts table entries visited by the recognizers."""

    def __init__(self, model, ev):
        self.nvars = model.nvars; self.orig_card = list(model.card); self.ev = dict(ev)
        self.dom = {v: tuple(range(model.card[v])) for v in range(model.nvars) if v not in ev}
        self.scale = Fr(1); self.zero_proof = None; self.steps = []; self.next_fid = 0; self.work = 0
        self.dec = {}
        for v in range(model.nvars):
            self.dec[v] = ([("C", Fr(1) if s == ev[v] else Fr(0)) for s in range(model.card[v])] if v in ev else [("V", v, s, Fr(1)) for s in range(model.card[v])])
        self.factors = []
        for f in model.factors:                                      # exact evidence restriction (original table indexed before pinned coordinates drop)
            st = f.strides(); keep = [k for k in range(len(f.scope)) if f.scope[k] not in ev]
            base = sum(ev[v] * st[k] for k, v in enumerate(f.scope) if v in ev)
            if not keep:
                val = f.table[base]
                if val == 0 and self.zero_proof is None:
                    self.zero_proof = {"kind": "pinned_factor_zero", "factor_origin": f.origin}
                self.scale *= val; self.steps.append(("pinned", f.origin, str(val))); continue
            nsc = tuple(f.scope[k] for k in keep); ncd = tuple(f.card[k] for k in keep); nst = strides_of(ncd); tab = [None] * prod(ncd)
            for idx in iproduct(*[range(c) for c in ncd]):
                tab[sum(idx[j] * nst[j] for j in range(len(keep)))] = f.table[base + sum(idx[j] * st[keep[j]] for j in range(len(keep)))]
            self.factors.append(RFactor(self._fid(), nsc, ncd, tab, f.origin))
            self.work += len(tab)

    def _fid(self):
        self.next_fid += 1; return self.next_fid - 1

    # ------------------------------------------------------------------ steps (each an exact identity of the restricted law)
    def exclude(self, v, state, witness_fid):
        d = self.dom[v]; p = d.index(state); nd = tuple(s for s in d if s != state)
        for f in self.factors:
            if v in f.scope:
                f.restrict_axis(f.scope.index(v), [a for a in range(len(d)) if a != p])
        self.dom[v] = nd
        for ov in range(self.nvars):
            self.dec[ov] = [("C", Fr(0)) if (e[0] == "V" and e[1] == v and e[2] == state) else e for e in self.dec[ov]]
        self.steps.append(("exclude", v, state, witness_fid))
        if not nd:
            if self.zero_proof is None:
                self.zero_proof = {"kind": "empty_domain", "variable": v}
        elif len(nd) == 1:
            self.fix(v, nd[0])

    def fix(self, v, state):
        assert self.dom[v] == (state,)
        for f in self.factors:
            if v in f.scope:
                f.slice_axis(f.scope.index(v), 0)
        del self.dom[v]
        for ov in range(self.nvars):
            self.dec[ov] = [("C", e[3]) if (e[0] == "V" and e[1] == v) else e for e in self.dec[ov]]
        self.steps.append(("fix", v, state))

    def fold_constant(self, f):
        val = f.table[0]; self.scale *= val
        self.steps.append(("const", f.fid, str(f.origin), str(val), len(f.table)))
        if val == 0 and self.zero_proof is None:
            self.zero_proof = {"kind": "zero_constant_factor", "fid": f.fid}
        self.factors.remove(f)

    def separate(self, f, k, rows):
        axis = f.scope[k]; piv = next(i for i, z in enumerate(rows[0]) if z != 0)
        u = [r[piv] / rows[0][piv] for r in rows]; g = list(rows[0]); rest = f.scope[:k] + f.scope[k + 1:]; rcard = f.card[:k] + f.card[k + 1:]
        nu = RFactor(self._fid(), (axis,), (f.card[k],), u, "%s.u%d" % (f.origin, axis)); self.factors.remove(f); self.factors.append(nu)
        if rest:
            ng = RFactor(self._fid(), rest, rcard, g, "%s.r%d" % (f.origin, axis)); self.factors.append(ng); tail = ng.fid
        else:
            self.scale *= g[0]; tail = "const:%s" % g[0]
        self.steps.append(("separate", f.fid, str(f.origin), axis, k, nu.fid, tail))

    def alias(self, w, u, sigma, witness_fid):
        """w = sigma(u) in every positive configuration; sigma: position in dom[u] -> position in dom[w] (bijection). w leaves."""
        du, dw = self.dom[u], self.dom[w]; sigma_inv = [None] * len(dw)
        for pu, pw in enumerate(sigma):
            sigma_inv[pw] = pu
        for f in self.factors:
            if w not in f.scope:
                continue
            kw = f.scope.index(w)
            if u in f.scope:
                f.diagonal(kw, f.scope.index(u), sigma)
            else:
                f.relabel_axis(kw, u, sigma)
        inv = {dw[sigma[pu]]: du[pu] for pu in range(len(du))}                       # original state of w -> original state of u
        for ov in range(self.nvars):
            self.dec[ov] = [("V", u, inv[e[2]], e[3]) if (e[0] == "V" and e[1] == w) else e for e in self.dec[ov]]
        del self.dom[w]
        self.steps.append(("alias", w, u, [dw[sigma[pu]] for pu in range(len(du))], witness_fid))

    def quotient(self, v, classes, rho):
        """classes: {rep position: sorted member positions} (rep = min member); rho[a] = product over factors containing v of
        (row a pivot) / (row rep pivot), rho[rep] = 1. Factor rows of v reduced to the reps; new unary W(rep) = sum rho."""
        d = self.dom[v]; reps = sorted(classes); W = {r: sum(rho[a] for a in classes[r]) for r in reps}
        for f in self.factors:
            if v in f.scope:
                f.restrict_axis(f.scope.index(v), reps)
        nd = tuple(d[r] for r in reps); self.dom[v] = nd
        for ov in range(self.nvars):
            out = []
            for e in self.dec[ov]:
                if e[0] == "V" and e[1] == v:
                    a = d.index(e[2]); r = next(r for r in reps if a in classes[r]); out.append(("V", v, d[r], e[3] * rho[a] / W[r]))
                else:
                    out.append(e)
            self.dec[ov] = out
        wf = RFactor(self._fid(), (v,), (len(reps),), [W[r] for r in reps], "W%d" % v); self.factors.append(wf)
        self.steps.append(("quotient", v, {str(d[r]): [d[a] for a in classes[r]] for r in reps}, {str(d[a]): str(rho[a]) for r in reps for a in classes[r]}, wf.fid))
        if len(nd) == 1:
            self.fix(v, nd[0])

    # ------------------------------------------------------------------ recognizers (each returns True after applying ONE step)
    def pass_exclude(self):
        for f in list(self.factors):
            for k, v in enumerate(f.scope):
                sigs = f.row_signatures(k); self.work += len(f.table) // max(1, f.card[k])
                for a, (rep, _, zero) in enumerate(sigs):
                    if zero:
                        self.exclude(v, self.dom[v][a], f.fid); return True
        return False

    def pass_constants(self):
        changed = False
        for f in list(self.factors):
            if self.zero_proof is not None:
                break
            if not f.scope:
                self.fold_constant(f); changed = True; continue
            t0 = f.table[0]; self.work += len(f.table)
            if t0 > 0 and all(t == t0 for t in f.table[1:]):
                self.fold_constant(f); changed = True
        return changed

    def pass_separate(self):
        for f in list(self.factors):
            if len(f.scope) < 2:
                continue
            for k in range(len(f.scope)):
                sigs = f.row_signatures(k); self.work += len(f.table) // max(1, f.card[k])
                if all(rep == 0 and not zero for rep, _, zero in sigs):
                    self.separate(f, k, f.rows_along(k)); return True
        return False

    def pass_alias(self):
        for f in list(self.factors):
            if len(f.scope) < 2:
                continue
            arr = None
            for ku in range(len(f.scope)):
                for kw in range(len(f.scope)):
                    if kw == ku or f.card[ku] != f.card[kw]:
                        continue
                    if arr is None:
                        arr = (np.array(f.table, dtype=object).reshape(f.card) != 0); self.work += len(f.table)
                    other = tuple(j for j in range(len(f.scope)) if j not in (ku, kw))
                    pos = arr.any(axis=other) if other else arr
                    pairs = {(int(a), int(b)) for a, b in zip(*np.nonzero(pos))}
                    if len(pairs) == f.card[ku] and len({a for a, _ in pairs}) == f.card[ku] and len({b for _, b in pairs}) == f.card[kw]:
                        sigma = [None] * f.card[ku]
                        for a, b in pairs:
                            sigma[a] = b
                        u, w = f.scope[ku], f.scope[kw]
                        if w < u:                                             # the smaller id survives
                            inv = [None] * f.card[ku]
                            for a, b in enumerate(sigma):
                                inv[b] = a
                            self.alias(u, w, inv, f.fid)
                        else:
                            self.alias(w, u, sigma, f.fid)
                        return True
        return False

    def pass_quotient(self):
        for v in sorted(self.dom):
            d = self.dom[v]
            if len(d) < 2:
                continue
            fs = [f for f in self.factors if v in f.scope]
            if not fs:
                # no factor mentions v: all states are equivalent (uniform) -- a quotient to one state with rho = 1 each
                cl = {0: list(range(len(d)))}; self.quotient(v, cl, {a: Fr(1) for a in range(len(d))}); return True
            sig = {a: [] for a in range(len(d))}; ratio = {a: Fr(1) for a in range(len(d))}; ok = True
            for f in fs:
                sigs = f.row_signatures(f.scope.index(v)); self.work += len(f.table) // max(1, f.card[f.scope.index(v)])
                for a, (rep, rat, zero) in enumerate(sigs):
                    if zero:
                        ok = False; break
                    sig[a].append(rep); ratio[a] *= rat
                if not ok:
                    break
            if not ok:
                continue
            classes = {}
            for a in range(len(d)):
                classes.setdefault(tuple(sig[a]), []).append(a)
            cl = {min(mem): sorted(mem) for mem in classes.values()}
            if all(len(mem) == 1 for mem in cl.values()):
                continue
            rho = {a: ratio[a] / ratio[r] for r, mem in cl.items() for a in mem}
            self.quotient(v, cl, rho); return True
        return False

    def reduce(self, enabled, deadline=None, work_cap=100_000_000, max_passes=5000):
        """Fixpoint of the enabled recognizers. Returns the recognition record; a cap leaves a valid reduced model."""
        passes = 0; t0 = time.monotonic(); capped = None; enabled = set(enabled)
        while self.zero_proof is None:
            passes += 1
            if passes > max_passes:
                capped = "pass cap"; break
            if deadline is not None and time.monotonic() > deadline:
                capped = "wall"; break
            if self.work > work_cap:
                capped = "work cap"; break
            changed = False
            for name in ALL_RULES:
                if name in enabled and getattr(self, "pass_" + name)():
                    changed = True; break
            if not changed:
                break
        for f in list(self.factors):                                      # scope-free factors are exact constants whatever the rule set (identity; checked as const steps)
            if not f.scope and self.zero_proof is None:
                self.fold_constant(f)
        return {"passes": passes, "entries_scanned": self.work, "seconds": time.monotonic() - t0, "capped": capped, "steps": len(self.steps), "zero_proof": self.zero_proof, "rules": sorted(enabled)}

    # ------------------------------------------------------------------ records
    def record(self):
        return {"nvars": self.nvars, "orig_card": self.orig_card, "evidence": {str(v): s for v, s in sorted(self.ev.items())},
                "dom": {str(v): list(d) for v, d in sorted(self.dom.items())}, "scale": str(self.scale), "zero_proof": self.zero_proof,
                "steps": [list(s) for s in self.steps],
                "factors": [{"fid": f.fid, "scope": list(f.scope), "card": list(f.card), "origin": str(f.origin), "table_sha256": table_hash(f.table), "entries": len(f.table)} for f in sorted(self.factors, key=lambda f: f.fid)],
                "decoder": {str(v): [[e[0], str(e[1])] if e[0] == "C" else [e[0], e[1], e[2], str(e[3])] for e in es] for v, es in self.dec.items()},
                "reduced_hash": self.reduced_hash()}

    def reduced_hash(self):
        h = hashlib.sha256()
        for v in sorted(self.dom):
            h.update(("D%d:%s;" % (v, ",".join(map(str, self.dom[v])))).encode())
        for f in sorted(self.factors, key=lambda f: f.fid):
            h.update(("F%d:%s:%s;" % (f.fid, ",".join(map(str, f.scope)), table_hash(f.table))).encode())
        h.update(("S%d/%d" % (self.scale.numerator, self.scale.denominator)).encode())
        return h.hexdigest()


def proportional(row0, rows):
    piv = next((i for i, z in enumerate(row0) if z != 0), None)
    if piv is None:
        return False
    for r in rows:
        c = r[piv] / row0[piv]
        if any(a != c * b for a, b in zip(r, row0)):
            return False
    return True
