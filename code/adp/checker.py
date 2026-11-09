"""INDEPENDENT CHECKER of an AGGREGATE_DP_V1 certificate (run as a separate process: python -m adp.checker CERT.json OUT.json DEADLINE_S).

Shares with the producer ONLY: the immutable source bytes, the MPFR library (gmpy2 contexts of mdi.arith.Ctx) and numpy. Everything
else is its own: the UAI parser (ext.uai, a different lossless parser from the producer's mdi.model), the exact tables, the
re-derivation of every source step from its witness, the view (class / scale) construction, the program-structure validation
(complete bucket ownership, unique elimination, single consumption of every factor occurrence and message, dependency order),
the index arithmetic (np.unravel_index / ravel_multi_index, structured-void keys for joins -- not the producer's stride decode /
radix encode), the complete-support construction, the OUTWARD interval replay of every forward core entry and of the reverse
accumulation, the normalization (cancellation-safe), the decoders and the publication predicate on the delivered decimals.

The certificate carries NO producer intermediate numbers that are trusted: only structure (steps, order, node definitions,
views, formats, precision) and the published rows. The checker's enclosures are authoritative; the producer's published point
must satisfy the robust-center predicate against THEM.
"""
from __future__ import annotations
import sys, os, json, time, hashlib, math
sys.set_int_max_str_digits(0)
from fractions import Fraction as Fr
from itertools import product as iproduct
import numpy as np
import gmpy2
from gmpy2 import mpfr
from mdi import arith as A                               # trusted directed-rounding primitives only
from ext import uai as U                                 # the OTHER lossless UAI parser (independent of mdi.model)
from adp import publish as PB

RNDD, RNDU = gmpy2.RoundDown, gmpy2.RoundUp


class Reject(Exception):
    """A specific violated condition of the certificate."""


def _canon_hash(path):
    return hashlib.sha256((" ".join(open(path).read().split())).encode()).hexdigest()


def _raw_hash(path):
    return hashlib.sha256(open(path, "rb").read()).hexdigest()


def _thash(table):
    h = hashlib.sha256()
    for t in table:
        h.update(("%d/%d," % (t.numerator, t.denominator)).encode())
    return h.hexdigest()


# ===================================================================================================== step typing
def _int(x, what):
    if type(x) is not int or isinstance(x, bool):
        raise Reject("%s must be a JSON integer, got %r" % (what, x))
    return x


def validate_steps(steps):
    """Every step is a list with the declared arity and INTEGER identifiers / states (bool, str, float, list rejected by type)."""
    arity = {"pinned": 3, "exclude": 4, "fix": 3, "const": 5, "separate": 7, "alias": 5, "quotient": 5}
    for st in steps:
        if not isinstance(st, list) or not st or st[0] not in arity:
            raise Reject("malformed step %r" % (st,))
        if len(st) != arity[st[0]]:
            raise Reject("step %s has %d fields, expected %d" % (st[0], len(st), arity[st[0]]))
        k = st[0]
        if k == "exclude":
            _int(st[1], "exclude variable"); _int(st[2], "exclude state"); _int(st[3], "exclude witness fid")
        elif k == "fix":
            _int(st[1], "fix variable"); _int(st[2], "fix state")
        elif k == "const":
            _int(st[1], "const fid"); _int(st[4], "const entries")
        elif k == "separate":
            _int(st[1], "separate fid"); _int(st[3], "separate axis"); _int(st[4], "separate axis index"); _int(st[5], "separate unary fid")
        elif k == "alias":
            _int(st[1], "alias w"); _int(st[2], "alias u"); _int(st[4], "alias witness fid")
            if not isinstance(st[3], list) or not all(type(s) is int for s in st[3]):
                raise Reject("alias state map must be a list of integers")
        elif k == "quotient":
            _int(st[1], "quotient variable"); _int(st[4], "quotient W fid")
            if not isinstance(st[2], dict) or not isinstance(st[3], dict):
                raise Reject("quotient classes / ratios must be objects")


# ===================================================================================================== exact source replay
def _take(arr, idx, axis):
    """np.take that always returns an object ndarray (a 1-D take of a scalar index would collapse to a Fraction)."""
    return np.asarray(np.take(arr, idx, axis=axis), dtype=object)


class CFactor:
    """Checker's own table: numpy object array of Fractions over the axes (scope order)."""
    __slots__ = ("fid", "scope", "arr", "origin")

    def __init__(self, fid, scope, arr, origin):
        self.fid = fid; self.scope = list(scope); self.arr = np.asarray(arr, dtype=object); self.origin = origin

    def flat(self):
        return list(np.asarray(self.arr, dtype=object).reshape(-1))


class SourceReplay:
    def __init__(self, cert, model_path, evid_path, deadline):
        self.deadline = deadline
        m = U.read_model(model_path); m.check(); ev = U.read_evidence(evid_path)
        for v, s in ev.items():
            if not (0 <= v < m.nvars and 0 <= s < m.card[v]):
                raise Reject("evidence out of range")
        self.nvars = m.nvars; self.card = list(m.card); self.ev = ev
        if cert["source"]["raw_model_sha256"] != _raw_hash(model_path) or cert["source"]["raw_evidence_sha256"] != _raw_hash(evid_path):
            raise Reject("certificate bound to different source bytes")
        if cert["source"]["canonical_model_sha256"] != _canon_hash(model_path) or cert["source"]["canonical_evidence_sha256"] != _canon_hash(evid_path):
            raise Reject("certificate bound to a different canonical source")
        if cert["reduced"]["nvars"] != m.nvars or list(cert["reduced"]["orig_card"]) != list(m.card):
            raise Reject("declared variable count / cardinalities differ from the source")
        if {int(k): v for k, v in cert["reduced"]["evidence"].items()} != ev:
            raise Reject("declared evidence differs from the evidence file")
        self.dom = {v: list(range(m.card[v])) for v in range(m.nvars) if v not in ev}
        self.scale = Fr(1); self.zero = None; self.fid = 0; self.factors = {}; self.consumed = []
        self.dec = {v: ([("C", Fr(1) if s == ev[v] else Fr(0)) for s in range(m.card[v])] if v in ev else [("V", v, s, Fr(1)) for s in range(m.card[v])]) for v in range(m.nvars)}
        seen_origin = set()
        for f in m.factors:                                            # evidence restriction by np indexing on the ORIGINAL table
            arr = np.array(f.table, dtype=object).reshape(f.card)
            idx = tuple(ev[v] if v in ev else slice(None) for v in f.scope); sub = arr[idx]
            keep = [v for v in f.scope if v not in ev]
            if not keep:
                val = sub if not isinstance(sub, np.ndarray) else sub.reshape(-1)[0]
                if val == 0 and self.zero is None:
                    self.zero = {"kind": "pinned_factor_zero", "factor_origin": f.index}
                self.scale *= val; continue
            self.factors[self.fid] = CFactor(self.fid, keep, np.array(sub, dtype=object).reshape([m.card[v] for v in keep]), f.index); self.fid += 1
        self.pinned_steps = [s for s in cert["reduced"]["steps"] if s[0] == "pinned"]
        if len(self.pinned_steps) != sum(1 for f in m.factors if all(v in ev for v in f.scope)):
            raise Reject("pinned-factor step count differs")

    def tick(self):
        if self.deadline is not None and time.monotonic() > self.deadline:
            raise TimeoutError("checker deadline during source replay")

    # --- step re-derivation
    def replay(self, steps):
        for st in steps:
            self.tick(); kind = st[0]
            if kind == "pinned":
                continue
            if self.zero is not None:
                raise Reject("steps continue after a zero proof")
            getattr(self, "step_" + kind)(st)

    def step_exclude(self, st):
        _, v, state, fid = st
        if v not in self.dom or state not in self.dom[v]:
            raise Reject("exclude of an unknown state %s of %s" % (state, v))
        f = self.factors.get(fid)
        if f is None or v not in f.scope:
            raise Reject("exclude witness factor %s does not contain %s" % (fid, v))
        k = f.scope.index(v); p = self.dom[v].index(state)
        if not all(z == 0 for z in _take(f.arr, p, axis=k).reshape(-1)):
            raise Reject("exclude witness: row %s of factor %s along %s is not all zero" % (state, fid, v))
        self._drop(v, [p])
        for ov in self.dec:
            self.dec[ov] = [("C", Fr(0)) if (e[0] == "V" and e[1] == v and e[2] == state) else e for e in self.dec[ov]]
        self.dom[v] = [s for s in self.dom[v] if s != state]
        if not self.dom[v]:
            self.zero = {"kind": "empty_domain", "variable": v}

    def _drop(self, v, positions):
        for f in self.factors.values():
            if v in f.scope:
                k = f.scope.index(v); f.arr = np.delete(f.arr, positions, axis=k)

    def step_fix(self, st):
        _, v, state = st
        if self.dom.get(v) != [state]:
            raise Reject("fix of %s=%s but its domain is %s" % (v, state, self.dom.get(v)))
        for f in self.factors.values():
            if v in f.scope:
                k = f.scope.index(v); f.arr = _take(f.arr, 0, axis=k); f.scope.pop(k)
        del self.dom[v]
        for ov in self.dec:
            self.dec[ov] = [("C", e[3]) if (e[0] == "V" and e[1] == v) else e for e in self.dec[ov]]

    def step_const(self, st):
        _, fid, origin, value, n = st
        f = self.factors.get(fid)
        if f is None:
            raise Reject("const of unknown factor %s" % fid)
        flat = f.arr.reshape(-1)
        if len(flat) != n or any(z != flat[0] for z in flat) or str(flat[0]) != value:
            raise Reject("const witness: factor %s is not the constant %s on %d entries" % (fid, value, n))
        if flat[0] == 0:
            self.zero = {"kind": "zero_constant_factor", "fid": fid}
        self.scale *= flat[0]; del self.factors[fid]; self.consumed.append(fid)

    def step_separate(self, st):
        _, fid, origin, axis, k, ufid, tail = st
        f = self.factors.get(fid)
        if f is None or f.scope[k] != axis:
            raise Reject("separate: factor %s axis %s mismatch" % (fid, axis))
        rows = np.moveaxis(f.arr, k, 0).reshape(f.arr.shape[k], -1)
        piv = next((i for i, z in enumerate(rows[0]) if z != 0), None)
        if piv is None:
            raise Reject("separate: pivot row is zero")
        u = [r[piv] / rows[0][piv] for r in rows]
        for a, r in enumerate(rows):
            if any(x != u[a] * y for x, y in zip(r, rows[0])):
                raise Reject("separate: rows of factor %s along %s are not proportional" % (fid, axis))
        if ufid != self.fid:
            raise Reject("separate: unary fid %s != expected %s" % (ufid, self.fid))
        self.factors[self.fid] = CFactor(self.fid, [axis], np.array(u, dtype=object), "%s.u" % origin); self.fid += 1
        rest = [w for j, w in enumerate(f.scope) if j != k]
        if rest:
            if tail != self.fid:
                raise Reject("separate: remainder fid mismatch")
            g = _take(f.arr, 0, axis=k)
            self.factors[self.fid] = CFactor(self.fid, rest, g.reshape([len(self.dom[w]) for w in rest]), "%s.r" % origin); self.fid += 1
        else:
            if tail != "const:%s" % rows[0][0]:
                raise Reject("separate: constant tail mismatch")
            self.scale *= rows[0][0]
        del self.factors[fid]; self.consumed.append(fid)

    def step_alias(self, st):
        _, w, u, states, fid = st
        f = self.factors.get(fid)
        if f is None or w not in f.scope or u not in f.scope:
            raise Reject("alias witness factor %s lacks %s / %s" % (fid, w, u))
        if len(self.dom[u]) != len(self.dom[w]) or len(states) != len(self.dom[u]):
            raise Reject("alias: domain sizes differ")
        kw, ku = f.scope.index(w), f.scope.index(u); other = tuple(j for j in range(f.arr.ndim) if j not in (kw, ku))
        pos = (f.arr != 0)
        pos = pos.any(axis=other) if other else pos
        # pos is indexed [.., ku .., kw ..] in scope order: bring to (u, w)
        pos2 = np.moveaxis(pos, (0 if ku < kw else 1, 1 if ku < kw else 0), (0, 1)) if False else (pos if ku < kw else pos.T)
        sigma = {}
        for pu in range(len(self.dom[u])):
            ws = [pw for pw in range(len(self.dom[w])) if pos2[pu, pw]]
            if len(ws) != 1:
                raise Reject("alias: u position %d has %d positive partners" % (pu, len(ws)))
            sigma[pu] = ws[0]
        if len(set(sigma.values())) != len(sigma):
            raise Reject("alias: not a bijection")
        if [self.dom[w][sigma[pu]] for pu in range(len(self.dom[u]))] != list(states):
            raise Reject("alias: declared state map differs from the witness")
        for g in self.factors.values():
            if w not in g.scope:
                continue
            gw = g.scope.index(w)
            if u in g.scope:
                gu = g.scope.index(u); out_shape = [n for j, n in enumerate(g.arr.shape) if j != gw]
                it = np.ndindex(*out_shape); new = np.empty(out_shape, dtype=object)
                for idx in it:
                    full = list(idx); pu = full[gu if gu < gw else gu - 1]; full.insert(gw, sigma[pu]); new[idx] = g.arr[tuple(full)]
                g.arr = new; g.scope.pop(gw)
            else:
                perm = [sigma[pu] for pu in range(len(self.dom[u]))]; g.arr = _take(g.arr, perm, axis=gw); g.scope[gw] = u
        inv = {self.dom[w][sigma[pu]]: self.dom[u][pu] for pu in range(len(self.dom[u]))}
        for ov in self.dec:
            self.dec[ov] = [("V", u, inv[e[2]], e[3]) if (e[0] == "V" and e[1] == w) else e for e in self.dec[ov]]
        del self.dom[w]

    def step_quotient(self, st):
        _, v, classes, rho_decl, wfid = st
        if v not in self.dom:
            raise Reject("quotient of unknown variable %s" % v)
        d = self.dom[v]; fs = [f for f in self.factors.values() if v in f.scope]
        sig = {a: [] for a in range(len(d))}; ratio = {a: Fr(1) for a in range(len(d))}
        for f in fs:
            rows = np.moveaxis(f.arr, f.scope.index(v), 0).reshape(len(d), -1); groups = {}
            for a in range(len(d)):
                row = rows[a]; piv = next((z for z in row if z != 0), None)
                if piv is None:
                    raise Reject("quotient: variable %s has a zero row in factor %s (must be excluded, not merged)" % (v, f.fid))
                key = tuple(z / piv for z in row); rep, base = groups.setdefault(key, (a, piv)); sig[a].append(rep); ratio[a] *= piv / base
        cl = {}
        for a in range(len(d)):
            cl.setdefault(tuple(sig[a]), []).append(a)
        mine = {min(mem): sorted(mem) for mem in cl.values()}
        decl = {d.index(int(r)): sorted(d.index(s) for s in mem) for r, mem in classes.items()}
        if mine != decl:
            raise Reject("quotient: declared classes of %s differ from the re-derived proportionality classes" % v)
        for r, mem in mine.items():
            for a in mem:
                if Fr(rho_decl[str(d[a])]) != ratio[a] / ratio[r]:
                    raise Reject("quotient: declared ratio of state %s differs" % d[a])
        reps = sorted(mine); W = {r: sum(ratio[a] / ratio[r] for a in mine[r]) for r in reps}
        for f in fs:
            f.arr = _take(f.arr, reps, axis=f.scope.index(v))
        for ov in self.dec:
            out = []
            for e in self.dec[ov]:
                if e[0] == "V" and e[1] == v:
                    a = d.index(e[2]); r = next(r for r in reps if a in mine[r]); out.append(("V", v, d[r], e[3] * (ratio[a] / ratio[r]) / W[r]))
                else:
                    out.append(e)
            self.dec[ov] = out
        if wfid != self.fid:
            raise Reject("quotient: W factor id mismatch")
        self.factors[self.fid] = CFactor(self.fid, [v], np.array([W[r] for r in reps], dtype=object), "W%d" % v); self.fid += 1
        self.dom[v] = [d[r] for r in reps]

    def reduced_hash(self):
        h = hashlib.sha256()
        for v in sorted(self.dom):
            h.update(("D%d:%s;" % (v, ",".join(map(str, self.dom[v])))).encode())
        for fid in sorted(self.factors):
            f = self.factors[fid]; h.update(("F%d:%s:%s;" % (fid, ",".join(map(str, f.scope)), _thash(f.flat()))).encode())
        h.update(("S%d/%d" % (self.scale.numerator, self.scale.denominator)).encode())
        return h.hexdigest()


# ===================================================================================================== views (own construction)
def own_source_view(f, k):
    rows = np.moveaxis(f.arr, k, 0).reshape(f.arr.shape[k], -1); groups = {}; cls = []; reps = []; ratio = []
    for a in range(rows.shape[0]):
        row = rows[a]; piv = next((z for z in row if z != 0), None)
        if piv is None:
            cls.append(-1); ratio.append(Fr(1)); continue
        key = tuple(z / piv for z in row)
        if key not in groups:
            groups[key] = (len(reps), piv); reps.append(a)
        c, base = groups[key]; cls.append(c); ratio.append(piv / base)
    return cls, reps, ratio


def own_intersect(views, n):
    groups = {}; cls = [None] * n; reps = []; ratio = [Fr(1)] * n
    for a in range(n):
        sig = tuple(c[a] for c, _, _ in views)
        if -1 in sig:
            cls[a] = -1; continue
        if sig not in groups:
            groups[sig] = len(reps); reps.append(a)
        cls[a] = groups[sig]
    for a in range(n):
        if cls[a] >= 0:
            r = reps[cls[a]]; q = Fr(1)
            for _, _, rat in views:
                q *= rat[a] / rat[r]
            ratio[a] = q
    return cls, reps, ratio


def check_source_view_sound(f, k, decl):
    """The DECLARED view of factor f along axis k is a proved identity: every state a with class c has row_a == ratio[a] * row_rep(c)
    entrywise (exact), rep(c) is a member of c with ratio 1, every zero-class state has an all-zero row, every state is covered.
    The checker verifies the claim; it does not require the finest partition (identity views are a sound declared configuration)."""
    rows = np.moveaxis(f.arr, k, 0).reshape(f.arr.shape[k], -1); n = rows.shape[0]
    cls = list(decl["cls"]); reps = list(decl["reps"]); ratio = [Fr(x) for x in decl["ratio"]]
    if len(cls) != n or len(ratio) != n or len(set(reps)) != len(reps):
        raise Reject("view shape of factor %s axis %d" % (f.fid, k))
    if any((c < -1 or c >= len(reps)) for c in cls):
        raise Reject("view class index out of range (factor %s axis %d)" % (f.fid, k))
    for ci, r in enumerate(reps):
        if cls[r] != ci or ratio[r] != 1:
            raise Reject("view representative %d of factor %s axis %d is not a unit member of its class" % (r, f.fid, k))
    for a in range(n):
        if cls[a] == -1:
            if any(z != 0 for z in rows[a]):
                raise Reject("view: state %d of factor %s axis %d declared zero but its row is not all zero" % (a, f.fid, k))
        else:
            r = reps[cls[a]]
            if any(x != ratio[a] * y for x, y in zip(rows[a], rows[r])):
                raise Reject("view: state %d of factor %s axis %d is not %s times its representative row" % (a, f.fid, k, ratio[a]))
            if all(y == 0 for y in rows[r]):
                raise Reject("view: a positive class of factor %s axis %d has an all-zero representative" % (f.fid, k))
    return cls, reps, ratio


def check_node_view_sound(decl, incoming, n, where):
    """Inductive rule: a state is zero iff SOME input has it zero; a positive state a shares its class with its representative in
    EVERY input, and its declared ratio is the product of the inputs' ratios a : rep. Coarser-than-finest declarations are sound."""
    cls = list(decl["cls"]); reps = list(decl["reps"]); ratio = [Fr(x) for x in decl["ratio"]]
    if len(cls) != n or len(ratio) != n or len(set(reps)) != len(reps) or any((c < -1 or c >= len(reps)) for c in cls):
        raise Reject("view shape at %s" % where)
    for ci, r in enumerate(reps):
        if cls[r] != ci or ratio[r] != 1:
            raise Reject("view representative at %s is not a unit member of its class" % where)
    for a in range(n):
        anyzero = any(vc[a] == -1 for vc, _, _ in incoming)
        if cls[a] == -1:
            if not anyzero:
                raise Reject("view at %s declares state %d zero but no input has it zero" % (where, a))
            continue
        if anyzero:
            raise Reject("view at %s declares state %d positive but an input has it zero" % (where, a))
        r = reps[cls[a]]; q = Fr(1)
        for vc, vr, vrat in incoming:
            if vc[a] != vc[r]:
                raise Reject("view at %s: states %d and %d are not equivalent in every input" % (where, a, r))
            q *= vrat[a] / vrat[r]
        if ratio[a] != q:
            raise Reject("view at %s: declared ratio of state %d differs from the product of input ratios" % (where, a))
    return cls, reps, ratio


# ===================================================================================================== interval replay
class IntervalReplay:
    """Outward enclosures of every core entry of the reduced program and of every marker derivative; own index arithmetic."""

    def __init__(self, S, plan, p, caps, deadline, counters):
        self.S = S; self.plan = plan; self.p = p; self.ctx = A.Ctx(p); self.D = self.ctx.D; self.Uc = self.ctx.U; self.deadline = deadline; self.caps = caps; self.c = counters
        self.dom = S.dom; self.vars = sorted(S.dom); self.fac = S.factors
        self.nodes = plan["nodes"]; self.order = plan["order"]
        # exact zero masks and outward source enclosures
        self.flo = {}; self.fhi = {}; self.fzero = {}
        for fid, f in self.fac.items():
            flat = f.flat(); lo = np.empty(len(flat), dtype=object); hi = np.empty(len(flat), dtype=object)
            for i, q in enumerate(flat):
                lo[i], hi[i] = self.ctx.ienc(q)
            self.flo[fid] = lo.reshape(f.arr.shape); self.fhi[fid] = hi.reshape(f.arr.shape); self.fzero[fid] = np.array([q == 0 for q in flat], dtype=bool).reshape(f.arr.shape)
        self.cores = {}; self.scale_lo = {}; self.scale_hi = {}; self.bytes = 0; self.mp = 8 + sys.getsizeof(mpfr(1, p)); self.specs = {}; self.frame = None; self.pending = []; self.memo_order = __import__('collections').OrderedDict()

    def tick(self):
        if self.deadline is not None and time.monotonic() > self.deadline:
            raise TimeoutError("checker deadline during interval replay")

    def sc(self, q):
        k = (q.numerator, q.denominator)
        if k not in self.scale_lo:
            self.scale_lo[k], self.scale_hi[k] = self.ctx.ienc(q)
        return self.scale_lo[k], self.scale_hi[k]

    # --- structure
    def validate_structure(self):
        live = {("F", fid): tuple(self.fac[fid].scope) for fid in self.fac}; eliminated = set(); pos = {v: i for i, v in enumerate(self.order)}
        if sorted(self.order) != self.vars:
            raise Reject("elimination order is not a permutation of the reduced variables")
        if len(self.nodes) != len(self.order):
            raise Reject("node count differs from the order length")
        for i, nd in enumerate(self.nodes):
            v = nd["v"]
            if v != self.order[i] or nd["nid"] != i or v in eliminated:
                raise Reject("node %d: eliminated variable / id mismatch" % i)
            want = sorted([ref for ref, scp in live.items() if v in scp], key=lambda r: (r[0], r[1])); got = sorted([tuple(r) for r in nd["inputs"]], key=lambda r: (r[0], r[1]))
            if want != got:
                raise Reject("node %d: bucket inputs are not exactly the live objects containing %s" % (i, v))
            scope = set()
            for ref in got:
                scope |= set(live.pop(ref))
            scope.discard(v)
            if tuple(sorted(scope, key=lambda w: pos[w])) != tuple(nd["scope"]):
                raise Reject("node %d: scope is not the union of its inputs minus %s in order position" % (i, v))
            if nd["parent"] != (None if not nd["scope"] else self.nodes_by_var(nd["scope"][0])):
                raise Reject("node %d: parent is not the bucket of its earliest later variable" % i)
            live[("M", i)] = tuple(nd["scope"]); eliminated.add(v)
        if any(ref[0] == "F" for ref in live):
            raise Reject("a source factor occurrence was never consumed")
        if sorted(nid for (k, nid) in live if k == "M") != sorted(self.plan["roots"]):
            raise Reject("declared roots differ from the unconsumed messages")

    def nodes_by_var(self, w):
        for nd in self.nodes:
            if nd["v"] == w:
                return nd["nid"]
        raise Reject("no bucket eliminates %s" % w)

    def validate_views(self):
        """Own source views and own inductive intersections must equal the declared ones exactly."""
        fv = {}
        for fid, f in self.fac.items():
            for k, w in enumerate(f.scope):
                decl = self.plan["source_views"].get("%d:%d" % (fid, w))
                if decl is None:
                    raise Reject("source view of factor %d axis %d missing" % (fid, w))
                fv[fid, w] = check_source_view_sound(f, k, decl)
        nv = {}
        for nd in self.nodes:
            for w in nd["scope"]:
                inc = []
                for ref in nd["inputs"]:
                    k, i = ref
                    if k == "F" and w in self.fac[i].scope:
                        inc.append(fv[i, w])
                    elif k == "M" and w in self.nodes[i]["scope"]:
                        inc.append(nv[i, w])
                if not inc:
                    raise Reject("node %d: boundary variable %s is in no input" % (nd["nid"], w))
                nv[nd["nid"], w] = check_node_view_sound(nd["views"][str(w)], inc, len(self.dom[w]), "node %d axis %s" % (nd["nid"], w))
            if list(nd["radix"]) != [len(nv[nd["nid"], u][1]) for u in nd["scope"]]:
                raise Reject("node %d radix differs" % nd["nid"])
            if nd["size"] != math.prod(nd["radix"]):
                raise Reject("node %d size differs from its radix product" % nd["nid"])
        self.fv = fv; self.nv = nv

    # --- addressing (own): a node core is indexed by the tuple of OUTPUT class indices along its scope, raveled C-order
    def core_shape(self, nd):
        return tuple(nd["radix"])

    def spec(self, nd, ref):
        """Static per-(node, input) addressing data, built once from the checker's OWN views: for each axis of the input's scope
        ("x", arr_or_None, lo, hi, zero) or (w, map_out_class_to_input_coord, lo, hi)."""
        key = (nd["nid"], ref); s = self.specs.get(key)
        if s is not None:
            return s
        k, i = ref; items = []
        if k == "F":
            for w in self.fac[i].scope:
                items.append(("x", None, None, None, None) if w == nd["v"] else (w, np.array(self.nv[nd["nid"], w][1], dtype=np.int64), None, None))
        else:
            for w in self.nodes[i]["scope"]:
                cls_in, reps_in, rat_in = self.nv[i, w]
                if w == nd["v"]:
                    cls_arr = np.array([max(cc, 0) for cc in cls_in], dtype=np.int64); z = np.array([cc < 0 for cc in cls_in], dtype=bool)
                    lo = hi = None
                    if any(q != 1 for q in rat_in):
                        lo = np.array([self.sc(q)[0] for q in rat_in], dtype=object); hi = np.array([self.sc(q)[1] for q in rat_in], dtype=object)
                    items.append(("x", cls_arr, lo, hi, z if z.any() else None))
                else:
                    reps_out = self.nv[nd["nid"], w][1]; ci = np.array([cls_in[a] for a in reps_out], dtype=np.int64); rat = [rat_in[a] for a in reps_out]
                    lo = hi = None
                    if any(q != 1 for q in rat):
                        lo = np.array([self.sc(q)[0] for q in rat], dtype=object); hi = np.array([self.sc(q)[1] for q in rat], dtype=object)
                    items.append((w, ci, lo, hi))
        self.specs[key] = (k, items); return self.specs[key]

    def coords_for_input(self, nd, ref, x_pos, cls_cols):
        """Input coordinates at the bag rows, the lookup scale enclosure (lo, hi or None) and the x-zero mask (or None)."""
        k, items = self.spec(nd, ref); coords = []; slo = None; shi = None; zero = None
        if k == "F":
            for it in items:
                coords.append(x_pos if it[0] == "x" else it[1][cls_cols[it[0]]])
            return coords, None, None, None
        for it in items:
            if it[0] == "x":
                _, cls_arr, lo, hi, z = it; coords.append(cls_arr[x_pos])
                if z is not None:
                    zero = z[x_pos]
                if lo is not None:
                    gmpy2.set_context(self.D); slo = lo[x_pos] if slo is None else slo * lo[x_pos]
                    gmpy2.set_context(self.Uc); shi = hi[x_pos] if shi is None else shi * hi[x_pos]
            else:
                w, ci, lo, hi = it; cc = cls_cols[w]; coords.append(ci[cc])
                if lo is not None:
                    gmpy2.set_context(self.D); slo = lo[cc] if slo is None else slo * lo[cc]
                    gmpy2.set_context(self.Uc); shi = hi[cc] if shi is None else shi * hi[cc]
        return coords, slo, shi, zero

    def gather(self, nd, x_pos, cls_cols):
        """per input: (lo, hi, zero) object arrays over the bag rows."""
        out = []
        for ref in nd["inputs"]:
            k, i = ref; coords, slo, shi, xzero = self.coords_for_input(nd, tuple(ref), x_pos, cls_cols)
            if k == "F":
                idx = tuple(coords); lo = self.flo[i][idx]; hi = self.fhi[i][idx]; zero = self.fzero[i][idx]
            else:
                core = self.cores[i]
                if xzero is not None and xzero.any():
                    keep = ~xzero; l2, h2, z2 = self.lookup(core, self.nodes[i], [cc[keep] for cc in coords]); n = len(xzero)
                    lo = np.full(n, mpfr(0), dtype=object); hi = np.full(n, mpfr(0), dtype=object); zero = np.ones(n, dtype=bool); lo[keep] = l2; hi[keep] = h2; zero[keep] = z2
                else:
                    lo, hi, zero = self.lookup(core, self.nodes[i], coords)
                if slo is not None:
                    gmpy2.set_context(self.D); lo = lo * slo
                    gmpy2.set_context(self.Uc); hi = hi * shi
            out.append((lo, hi, zero))
        return out

    def lookup(self, core, chnd, coords):
        shape = self.core_shape(chnd)
        if core["fmt"] == "dense":
            if core["lo"].size == 0:
                n = len(coords[0]) if coords else 1
                return np.full(n, mpfr(0), dtype=object), np.full(n, mpfr(0), dtype=object), np.ones(n, dtype=bool)
            flat = np.ravel_multi_index(tuple(coords), shape) if shape else np.zeros(len(coords[0]) if coords else 1, dtype=np.int64)
            return core["lo"][flat], core["hi"][flat], core["zero"][flat]
        if core["fmt"] == "sparse":
            flat = np.ravel_multi_index(tuple(coords), shape) if shape else np.zeros(1, dtype=np.int64)
            n = len(flat); lo = np.full(n, mpfr(0), dtype=object); hi = np.full(n, mpfr(0), dtype=object); zero = np.ones(n, dtype=bool)
            if core["keys"].size:
                # own membership test: dictionary of keys (hash lookup), not searchsorted
                d = core["index"]; hit_pos = np.array([d.get(int(k), -1) for k in flat], dtype=np.int64); hit = hit_pos >= 0
                lo[hit] = core["lo"][hit_pos[hit]]; hi[hit] = core["hi"][hit_pos[hit]]; zero[hit] = False
            return lo, hi, zero
        # lazy: memo, then the current frame's resolved children, else an iterative evaluation
        flat = np.ravel_multi_index(tuple(coords), shape) if shape else np.zeros(len(coords[0]) if coords else 1, dtype=np.int64)
        n = len(flat); lo = np.empty(n, dtype=object); hi = np.empty(n, dtype=object); zero = np.empty(n, dtype=bool); fr = getattr(self, "frame", None)
        for j in range(n):
            k = int(flat[j]); r = core["cache"].get(k)
            if r is None and fr is not None:
                r = fr.get((id(core), k))
                if r is None:
                    raise Reject("checker: unresolved lazy child entry inside an evaluation frame")
            if r is None:
                r = self.eval_lazy(core, chnd, k)
            lo[j], hi[j], zero[j] = r
        return lo, hi, zero

    def bag_term(self, nd, x_pos, cls_cols):
        """(lo, hi, zero) of prod over inputs at the bag rows and the per-input arrays (for the reverse kernel)."""
        parts = self.gather(nd, x_pos, cls_cols); n = len(x_pos)
        lo = np.full(n, mpfr(1), dtype=object); hi = np.full(n, mpfr(1), dtype=object); zero = np.zeros(n, dtype=bool)
        for plo, phi, pz in parts:
            gmpy2.set_context(self.D); lo = lo * plo
            gmpy2.set_context(self.Uc); hi = hi * phi
            zero |= pz
        self.c["bag_rows"] += n; self.c["interval_mults"] += 2 * n * len(parts)
        return lo, hi, zero, parts

    def sum_groups(self, lo, hi, zero, groups, ngroups, dense_nx=None):
        """Outward sums of rows into groups. Dense bags (groups = tile pattern) reduce along a reshaped axis; sparse bags sort the
        rows by group and use reduceat."""
        self.c["interval_adds"] += 2 * len(lo)
        if dense_nx is not None:
            gmpy2.set_context(self.D); slo = np.add.reduce(lo.reshape(dense_nx, ngroups), axis=0) if dense_nx > 1 else lo.copy()
            gmpy2.set_context(self.Uc); shi = np.add.reduce(hi.reshape(dense_nx, ngroups), axis=0) if dense_nx > 1 else hi.copy()
            return np.asarray(slo, dtype=object), np.asarray(shi, dtype=object), zero.reshape(dense_nx, ngroups).all(axis=0)
        order = np.argsort(groups, kind="stable"); g = groups[order]; starts = np.flatnonzero(np.r_[True, g[1:] != g[:-1]])
        gmpy2.set_context(self.D); slo = np.add.reduceat(lo[order], starts)
        gmpy2.set_context(self.Uc); shi = np.add.reduceat(hi[order], starts)
        allz = np.logical_and.reduceat(zero[order], starts)
        out_lo = np.full(ngroups, mpfr(0), dtype=object); out_hi = np.full(ngroups, mpfr(0), dtype=object); out_z = np.ones(ngroups, dtype=bool)
        out_lo[g[starts]] = slo; out_hi[g[starts]] = shi; out_z[g[starts]] = allz
        return out_lo, out_hi, out_z

    # --- formats (own frozen rule: sparse iff some input has an exact zero; dense iff the core fits; else lazy)
    def choose_fmt(self, nd):
        if any((self.fzero[i].any() if k == "F" else (self.cores[i]["fmt"] == "sparse" or any(-1 in self.nv[i, w][0] for w in self.nodes[i]["scope"]))) for k, i in map(tuple, nd["inputs"])):
            return "sparse"
        if nd["size"] <= self.caps["dense_core_cap_entries"]:
            return "dense"
        return "lazy"

    def forward(self):
        for nd in self.nodes:
            self.tick(); fmt = self.choose_fmt(nd); nd["_fmt_checker"] = fmt
            if fmt == "dense":
                self.forward_dense(nd)
            elif fmt == "sparse":
                self.forward_sparse(nd)
            else:
                self.cores[nd["nid"]] = {"fmt": "lazy", "cache": {}, "nid": nd["nid"]}
                if nd["parent"] is None:
                    self.eval_lazy(self.cores[nd["nid"]], nd, 0)

    def bag_rows_dense(self, nd, lo_key, hi_key):
        shape = self.core_shape(nd); nx = len(self.dom[nd["v"]]); keys = np.arange(lo_key, hi_key, dtype=np.int64)
        coords = np.unravel_index(keys, shape) if shape else ()
        cls_cols = {w: np.tile(coords[j], nx) for j, w in enumerate(nd["scope"])}
        x_pos = np.repeat(np.arange(nx, dtype=np.int64), len(keys)); groups = np.tile(np.arange(len(keys), dtype=np.int64), nx)
        return x_pos, cls_cols, groups

    def forward_dense(self, nd):
        size = nd["size"]; nx = len(self.dom[nd["v"]])
        if self.bytes + 2 * size * self.mp > self.caps["value_bytes_cap"]:
            nd["_fmt_checker"] = "lazy"; self.cores[nd["nid"]] = {"fmt": "lazy", "cache": {}, "nid": nd["nid"]}; self.c["downgraded_to_lazy"] = self.c.get("downgraded_to_lazy", 0) + 1
            if nd["parent"] is None:
                self.eval_lazy(self.cores[nd["nid"]], nd, 0)
            return
        chunk = max(1, self.caps["dense_bag_cap_entries"] // nx); lo = np.empty(size, dtype=object); hi = np.empty(size, dtype=object); zero = np.empty(size, dtype=bool)
        for a in range(0, size, chunk):
            self.tick(); b = min(size, a + chunk); x_pos, cls_cols, groups = self.bag_rows_dense(nd, a, b)
            tlo, thi, tz, _ = self.bag_term(nd, x_pos, cls_cols); slo, shi, allz = self.sum_groups(tlo, thi, tz, groups, b - a, dense_nx=nx)
            lo[a:b] = slo; hi[a:b] = shi; zero[a:b] = allz
        self.cores[nd["nid"]] = {"fmt": "dense", "lo": lo, "hi": hi, "zero": zero, "nid": nd["nid"]}; self.bytes += 2 * size * self.mp; self.c["entries"] += size

    def own_support(self, nd):
        """Complete upward support of the bag in (x_pos, class columns): join of input supports (own hash-based grouping)."""
        v = nd["v"]; cols = None; rows = None
        for ref in sorted(map(tuple, nd["inputs"]), key=lambda r: (r[0], r[1])):
            k, i = ref
            if k == "F":
                f = self.fac[i]; pos = np.argwhere(~self.fzero[i]); rc = ["x" if w == v else w for w in f.scope]; rel = pos.astype(np.int64)
                keep = np.ones(len(rel), dtype=bool)
                for j, w in enumerate(f.scope):
                    if w != v:
                        cls, reps, _ = self.nv[nd["nid"], w]; isrep = np.zeros(len(cls), dtype=bool); isrep[reps] = True
                        keep &= isrep[rel[:, j]]; rel[:, j] = np.array(cls, dtype=np.int64)[rel[:, j]]
                rel = rel[keep]
            else:
                ch = self.nodes[i]; core = self.cores[i]
                if core["fmt"] == "lazy":
                    raise TimeoutError("checker: sparse join needs a lazy child's support")
                keys = core["keys"] if core["fmt"] == "sparse" else np.flatnonzero(~core["zero"])
                shape = self.core_shape(ch); crd = np.stack(np.unravel_index(keys, shape), axis=1) if (len(keys) and shape) else np.zeros((len(keys), len(shape)), dtype=np.int64)
                rc = ["x" if w == v else w for w in ch["scope"]]; rel = crd.astype(np.int64)
                for j, w in enumerate(ch["scope"]):
                    cls_in, reps_in, _ = self.nv[i, w]
                    if w == v:
                        lift = [[a for a, c in enumerate(cls_in) if c == ci] for ci in range(len(reps_in))]
                    else:
                        reps_out = self.nv[nd["nid"], w][1]; lift = [[co for co, r in enumerate(reps_out) if cls_in[r] == ci] for ci in range(len(reps_in))]
                    rel = self.lift(rel, j, lift)
            if rows is None:
                cols, rows = rc, rel
            else:
                cols, rows = self.hash_join(cols, rows, rc, rel)
            if len(rows) > self.caps["sparse_rows_cap"]:
                raise TimeoutError("checker sparse rows cap")
        return cols, rows

    def lift(self, rel, j, lift):
        out = []
        counts = np.array([len(l) for l in lift], dtype=np.int64); rep = counts[rel[:, j]]
        idx = np.repeat(np.arange(len(rel)), rep); base = rel[idx]
        flat = np.concatenate([np.array(l, dtype=np.int64) for l in lift]) if counts.sum() else np.zeros(0, dtype=np.int64)
        starts = np.concatenate([[0], np.cumsum(counts)[:-1]]); within = np.arange(len(idx)) - np.repeat(np.cumsum(rep) - rep, rep)
        base[:, j] = flat[starts[rel[idx, j]] + within]
        return base

    def hash_join(self, ca, ra, cb, rb):
        shared = [c for c in ca if c in cb]; onlyb = [c for c in cb if c not in ca]
        if not shared:
            ia = np.repeat(np.arange(len(ra)), len(rb)); ib = np.tile(np.arange(len(rb)), len(ra))
            return ca + onlyb, np.concatenate([ra[ia], rb[ib][:, [cb.index(c) for c in onlyb]]], axis=1)
        # own grouping: structured void view of the shared columns
        def keyview(r, cols):
            sub = np.ascontiguousarray(r[:, [cols.index(c) for c in shared]]); return sub.view(np.dtype((np.void, sub.dtype.itemsize * sub.shape[1]))).reshape(-1)
        ka = keyview(ra, ca); kb = keyview(rb, cb); groups = {}
        for j, k in enumerate(kb.tolist()):
            groups.setdefault(k, []).append(j)
        ia = []; ib = []
        for i, k in enumerate(ka.tolist()):
            g = groups.get(k)
            if g:
                ia.extend([i] * len(g)); ib.extend(g)
        ia = np.array(ia, dtype=np.int64); ib = np.array(ib, dtype=np.int64)
        return ca + onlyb, (np.concatenate([ra[ia], rb[ib][:, [cb.index(c) for c in onlyb]]], axis=1) if len(ia) else np.zeros((0, len(ca) + len(onlyb)), dtype=np.int64))

    def forward_sparse(self, nd):
        cols, rows = self.own_support(nd); shape = self.core_shape(nd); nx = len(self.dom[nd["v"]])
        x_pos = rows[:, cols.index("x")]; cls_cols = {w: rows[:, cols.index(w)] for w in nd["scope"]}
        keys = np.ravel_multi_index(tuple(cls_cols[w] for w in nd["scope"]), shape) if shape else np.zeros(len(rows), dtype=np.int64)
        uniq, groups = np.unique(keys, return_inverse=True)
        tlo, thi, tz, _ = self.bag_term(nd, x_pos, cls_cols)
        if tz.any():
            raise Reject("checker: a supported bag row is an exact zero (join is not a complete positive support)")
        slo, shi, _ = self.sum_groups(tlo, thi, tz, groups, len(uniq))
        self.cores[nd["nid"]] = {"fmt": "sparse", "keys": uniq, "index": {int(k): j for j, k in enumerate(uniq.tolist())}, "lo": slo, "hi": shi, "rows": (x_pos, cls_cols, groups), "nid": nd["nid"]}
        self.bytes += 2 * len(uniq) * self.mp + rows.nbytes; self.c["entries"] += len(uniq); self.c["support_rows"] += len(rows)
        if self.bytes > self.caps["value_bytes_cap"]:
            raise TimeoutError("checker value cap (sparse)")

    def lazy_child_keys(self, nd, x_pos, cls_cols):
        out = []
        for ref in nd["inputs"]:
            k, i = ref
            if k != "M" or self.cores[i]["fmt"] != "lazy":
                continue
            coords, _, _, xzero = self.coords_for_input(nd, tuple(ref), x_pos, cls_cols); shape = self.core_shape(self.nodes[i])
            flat = np.ravel_multi_index(tuple(coords), shape) if shape else np.zeros(len(x_pos), dtype=np.int64)
            if xzero is not None:
                flat = flat[~xzero]
            out.append((self.cores[i], self.nodes[i], np.unique(flat)))
        return out

    def eval_lazy(self, core, nd, key):
        """Explicit-stack evaluation (no host recursion): a frame pushes one missing lazy-child entry at a time and receives its value
        into a frame-local dict (`self.frame`), which `lookup` consults when the memo misses."""
        hit = core["cache"].get(key)
        if hit is not None:
            return hit
        stack = [[core, nd, key, {}]]; result = None
        while stack:
            c, n, k, resolved = stack[-1]
            hit = c["cache"].get(k)
            if hit is not None and len(stack) > 1:
                stack.pop(); stack[-1][3][(id(c), k)] = hit; continue
            shape = self.core_shape(n); nx = len(self.dom[n["v"]]); coords = np.unravel_index(np.array([k]), shape) if shape else ()
            cls_cols = {w: np.repeat(coords[j], nx) for j, w in enumerate(n["scope"])}; x_pos = np.arange(nx, dtype=np.int64)
            pushed = False
            for ccore, cnd, keys in self.lazy_child_keys(n, x_pos, cls_cols):
                for kk in keys.tolist():
                    if (id(ccore), kk) in resolved:
                        continue
                    hit = ccore["cache"].get(kk)
                    if hit is not None:
                        resolved[(id(ccore), kk)] = hit; continue
                    stack.append([ccore, cnd, kk, {}]); pushed = True; break
                if pushed:
                    break
            if pushed:
                continue
            self.tick(); self.frame = resolved
            tlo, thi, tz, _ = self.bag_term(n, x_pos, cls_cols); self.frame = None
            slo, shi, allz = self.sum_groups(tlo, thi, tz, np.zeros(nx, dtype=np.int64), 1, dense_nx=nx)
            res = (slo[0], shi[0], bool(allz[0])); self.c["entries"] += 1
            eb = 2 * self.mp + 96
            while c["cache"] and len(c["cache"]) >= self.caps["lazy_cache_entries"]:
                k0 = next(iter(c["cache"])); c["cache"].pop(k0); self.memo_order.pop((id(c), k0), None); self.bytes -= eb
            while self.memo_order and self.bytes + eb > self.caps["value_bytes_cap"]:
                (cid, k0), c0 = self.memo_order.popitem(last=False); c0["cache"].pop(k0, None); self.bytes -= eb
            if self.bytes + eb <= self.caps["value_bytes_cap"]:
                c["cache"][k] = res; self.memo_order[(id(c), k)] = c; self.bytes += eb
            stack.pop()
            if stack:
                stack[-1][3][(id(c), k)] = res
            else:
                result = res
        return result

    # --- backward (interval adjoints)
    def backward(self):
        self.mlo = {v: np.full(len(self.dom[v]), mpfr(0), dtype=object) for v in self.vars}; self.mhi = {v: np.full(len(self.dom[v]), mpfr(0), dtype=object) for v in self.vars}
        for r in self.plan["roots"]:
            self.seed(self.cores[r], self.nodes[r], 0, mpfr(1), mpfr(1))
        for nd in reversed(self.nodes):
            self.tick(); core = self.cores[nd["nid"]]
            self.drain()
            if core["fmt"] == "lazy":
                pend = core.get("adj") or {}
                while pend:
                    key, (alo, ahi) = pend.popitem(); self.pullback_entry(nd, core, key, alo, ahi); self.drain()
            elif core.get("adj_lo") is not None:
                if core["fmt"] == "dense":
                    size = nd["size"]; nx = len(self.dom[nd["v"]]); chunk = max(1, self.caps["dense_bag_cap_entries"] // nx)
                    for a in range(0, size, chunk):
                        b = min(size, a + chunk); x_pos, cls_cols, groups = self.bag_rows_dense(nd, a, b)
                        self.reverse_rows(nd, x_pos, cls_cols, core["adj_lo"][a + groups], core["adj_hi"][a + groups], dense_shape=(nx, b - a))
                else:
                    x_pos, cls_cols, groups = core["rows"]; self.reverse_rows(nd, x_pos, cls_cols, core["adj_lo"][groups], core["adj_hi"][groups], dense_shape=None)
            if core.get("adj"):
                raise Reject("checker: lazy adjoint deltas left unconsumed at the frontier")
            core["adj_lo"] = core["adj_hi"] = None; core["adj"] = None
            if core["fmt"] != "lazy":
                core["lo"] = core["hi"] = None                                      # frontier release (its parent's step already consumed it)

    def seed(self, core, nd, key, alo, ahi):
        if core["fmt"] == "lazy":
            core.setdefault("adj", {}); cur = core["adj"].get(key)
            if cur:
                gmpy2.set_context(self.D); lo = cur[0] + alo
                gmpy2.set_context(self.Uc); hi = cur[1] + ahi
                core["adj"][key] = (lo, hi)
            else:
                core["adj"][key] = (alo, ahi)
            return
        if core["fmt"] == "dense":
            if core["lo"].size == 0:
                return
            idx = key
        else:
            idx = core["index"].get(int(key))
            if idx is None:
                return
        if core.get("adj_lo") is None:
            n = len(core["lo"]); core["adj_lo"] = np.full(n, mpfr(0), dtype=object); core["adj_hi"] = np.full(n, mpfr(0), dtype=object)
        gmpy2.set_context(self.D); core["adj_lo"][idx] = core["adj_lo"][idx] + alo
        gmpy2.set_context(self.Uc); core["adj_hi"][idx] = core["adj_hi"][idx] + ahi

    def reverse_rows(self, nd, x_pos, cls_cols, alo, ahi, dense_shape):
        """Division-free: marker(v, x) += adj * prod(all inputs); message input j += adj * prod(others) * lookup scale. Factor
        inputs are folded first (no adjoint); prefix / suffix products run over the message inputs only."""
        parts = self.gather(nd, x_pos, cls_cols); n = len(x_pos); refs = [tuple(r) for r in nd["inputs"]]
        fac = [j for j, r in enumerate(refs) if r[0] == "F"]; msg = [j for j, r in enumerate(refs) if r[0] == "M"]
        blo, bhi = alo, ahi
        for j in fac:
            gmpy2.set_context(self.D); blo = blo * parts[j][0]
            gmpy2.set_context(self.Uc); bhi = bhi * parts[j][1]
        pre_lo = [blo]; pre_hi = [bhi]
        for j in msg:
            gmpy2.set_context(self.D); pre_lo.append(pre_lo[-1] * parts[j][0])
            gmpy2.set_context(self.Uc); pre_hi.append(pre_hi[-1] * parts[j][1])
        r = len(msg); self.c["interval_mults"] += 2 * n * (len(fac) + r) + 2 * n * max(0, r - 1); self.c["interval_adds"] += 2 * n
        if dense_shape is not None:
            gmpy2.set_context(self.D); add_lo = np.add.reduce(pre_lo[r].reshape(dense_shape), axis=1)
            gmpy2.set_context(self.Uc); add_hi = np.add.reduce(pre_hi[r].reshape(dense_shape), axis=1)
            for x in range(dense_shape[0]):
                gmpy2.set_context(self.D); self.mlo[nd["v"]][x] = self.mlo[nd["v"]][x] + add_lo[x]
                gmpy2.set_context(self.Uc); self.mhi[nd["v"]][x] = self.mhi[nd["v"]][x] + add_hi[x]
        else:
            gmpy2.set_context(self.D); np.add.at(self.mlo[nd["v"]], x_pos, pre_lo[r])
            gmpy2.set_context(self.Uc); np.add.at(self.mhi[nd["v"]], x_pos, pre_hi[r])
        suf_lo = suf_hi = None
        for i in range(r - 1, -1, -1):
            j = msg[i]
            if suf_lo is None:
                clo, chi = pre_lo[i], pre_hi[i]
            else:
                gmpy2.set_context(self.D); clo = pre_lo[i] * suf_lo
                gmpy2.set_context(self.Uc); chi = pre_hi[i] * suf_hi
            self.push(nd, refs[j], x_pos, cls_cols, clo, chi)
            if i > 0:
                gmpy2.set_context(self.D); suf_lo = parts[j][0] if suf_lo is None else suf_lo * parts[j][0]
                gmpy2.set_context(self.Uc); suf_hi = parts[j][1] if suf_hi is None else suf_hi * parts[j][1]

    def push(self, nd, ref, x_pos, cls_cols, clo, chi):
        ch = self.nodes[ref[1]]; core = self.cores[ref[1]]; coords, slo, shi, xzero = self.coords_for_input(nd, ref, x_pos, cls_cols)
        if slo is not None:
            gmpy2.set_context(self.D); clo = clo * slo
            gmpy2.set_context(self.Uc); chi = chi * shi
        shape = self.core_shape(ch); flat = np.ravel_multi_index(tuple(coords), shape) if shape else np.zeros(len(x_pos), dtype=np.int64)
        if xzero is not None:
            keep = ~xzero; flat = flat[keep]; clo = clo[keep]; chi = chi[keep]
        if core["fmt"] == "lazy":
            core.setdefault("adj", {})
            for kk, a, b in zip(flat.tolist(), clo, chi):
                cur = core["adj"].get(kk)
                if cur:
                    gmpy2.set_context(self.D); a2 = cur[0] + a
                    gmpy2.set_context(self.Uc); b2 = cur[1] + b
                    core["adj"][kk] = (a2, b2)
                else:
                    core["adj"][kk] = (a, b)
                if len(core["adj"]) > self.caps["lazy_cache_entries"]:
                    k2, (a2, b2) = core["adj"].popitem(); self.pending.append((ch, core, k2, a2, b2))
            return
        if core["fmt"] == "dense":
            if core["lo"].size == 0:
                return
            idx = flat
        else:
            d = core["index"]; pos = np.array([d.get(int(k), -1) for k in flat], dtype=np.int64); ok = pos >= 0; idx = pos[ok]; clo = clo[ok]; chi = chi[ok]
        if len(idx) == 0:
            return
        if core.get("adj_lo") is None:
            n = len(core["lo"]); core["adj_lo"] = np.full(n, mpfr(0), dtype=object); core["adj_hi"] = np.full(n, mpfr(0), dtype=object)
        order = np.argsort(idx, kind="stable"); g = idx[order]; starts = np.flatnonzero(np.r_[True, g[1:] != g[:-1]]); tgt = g[starts]
        gmpy2.set_context(self.D); core["adj_lo"][tgt] = core["adj_lo"][tgt] + np.add.reduceat(clo[order], starts)
        gmpy2.set_context(self.Uc); core["adj_hi"][tgt] = core["adj_hi"][tgt] + np.add.reduceat(chi[order], starts)
        self.c["interval_adds"] += 2 * len(idx)

    def drain(self):
        while self.pending:
            n, cr, k, a, b = self.pending.pop(); self.pullback_entry(n, cr, k, a, b)

    def pullback_entry(self, nd, core, key, alo, ahi):
        shape = self.core_shape(nd); nx = len(self.dom[nd["v"]])
        coords = np.unravel_index(np.array([key]), shape) if shape else ()
        cls_cols = {w: np.repeat(coords[j], nx) for j, w in enumerate(nd["scope"])}; x_pos = np.arange(nx, dtype=np.int64)
        self.reverse_rows(nd, x_pos, cls_cols, np.full(nx, alo, dtype=object), np.full(nx, ahi, dtype=object), dense_shape=None)

    # --- results
    def root_intervals(self):
        out = {}
        for r in self.plan["roots"]:
            core = self.cores[r]; nd = self.nodes[r]
            if core["fmt"] == "lazy":
                lo, hi, _ = self.eval_lazy(core, nd, 0)
            elif core["fmt"] == "dense":
                lo, hi = (core["_root"] if "_root" in core else (core["lo"][0], core["hi"][0])) if core["lo"] is not None else core["_root"]
            else:
                j = core["index"].get(0); lo, hi = (core["lo"][j], core["hi"][j]) if (j is not None and core["lo"] is not None) else core.get("_root", (mpfr(0), mpfr(0)))
            out[r] = (A.exact_fr(lo), A.exact_fr(hi))
        return out

    def save_roots(self):
        for r in self.plan["roots"]:
            core = self.cores[r]
            if core["fmt"] == "dense":
                core["_root"] = (core["lo"][0], core["hi"][0]) if core["lo"].size else (mpfr(0), mpfr(0))
            elif core["fmt"] == "sparse":
                j = core["index"].get(0); core["_root"] = (core["lo"][j], core["hi"][j]) if j is not None else (mpfr(0), mpfr(0))


# ===================================================================================================== driver
def normalize_rows(mlo, mhi, dom):
    """Cancellation-safe outward normalization per reduced variable: lower = Alo/(Alo+Chi), upper = Ahi/(Ahi+Clo) exactly."""
    out = {}
    for v in sorted(dom):
        lo = [A.exact_fr(x) for x in mlo[v]]; hi = [A.exact_fr(x) for x in mhi[v]]; row = []
        for s in range(len(lo)):
            Alo, Ahi = lo[s], hi[s]; Clo = sum(lo[t] for t in range(len(lo)) if t != s); Chi = sum(hi[t] for t in range(len(hi)) if t != s)
            if Ahi == 0:
                row.append((Fr(0), Fr(0))); continue
            if Chi == 0:
                row.append((Fr(1), Fr(1))); continue
            if Alo + Chi == 0:
                raise Reject("unresolved normalization (zero lower denominator with positive upper)")
            L = Alo / (Alo + Chi); Uu = Ahi / (Ahi + Clo) if Ahi + Clo > 0 else Fr(1)
            row.append((max(Fr(0), L), min(Fr(1), Uu)))
        out[v] = row
    return out


def check(cert, model_path, evid_path, expected_queries, deadline, caps):
    """Returns the checker record. Raises Reject for a specific violated condition; TimeoutError when its own work ran out."""
    t0 = time.monotonic(); counters = {"bag_rows": 0, "interval_mults": 0, "interval_adds": 0, "entries": 0, "support_rows": 0}; rec = {"checker": "adp.checker v1.1", "phases_s": {}}
    validate_steps(cert["reduced"]["steps"])
    S = SourceReplay(cert, model_path, evid_path, deadline); S.replay(cert["reduced"]["steps"]); rec["phases_s"]["source_replay"] = time.monotonic() - t0
    rec["source"] = {"raw_model_sha256": _raw_hash(model_path), "raw_evidence_sha256": _raw_hash(evid_path), "canonical_model_sha256": _canon_hash(model_path), "canonical_evidence_sha256": _canon_hash(evid_path)}
    rec["nvars"] = S.nvars; rec["orig_card"] = list(S.card); rec["precision"] = cert.get("precision")
    if S.zero is not None or cert["reduced"]["zero_proof"] is not None:
        if S.zero is None or cert["reduced"]["zero_proof"] is None:
            raise Reject("zero proof declared by only one side")
        rec["status"] = "ZERO_EVIDENCE_PROVED"; rec["zero_proof"] = S.zero; return rec
    if S.reduced_hash() != cert["reduced"]["reduced_hash"]:
        raise Reject("re-derived reduced model differs from the certificate's reduced model hash")
    if S.scale <= 0:
        raise Reject("non-positive global scale without a zero proof")
    # caller's query list
    if sorted(expected_queries) != sorted(range(S.nvars)):
        raise Reject("the caller's query contract must name every original variable in this campaign")
    t = time.monotonic(); R = IntervalReplay(S, cert["plan"], cert["precision"], caps, deadline, counters); R.validate_structure(); R.validate_views(); rec["phases_s"]["structure_views"] = time.monotonic() - t
    t = time.monotonic(); R.forward(); R.save_roots(); roots = R.root_intervals(); rec["phases_s"]["forward_intervals"] = time.monotonic() - t
    for r, (lo, hi) in roots.items():
        if hi == 0:
            rec["status"] = "ZERO_EVIDENCE_PROVED"; rec["zero_proof"] = {"kind": "component_root_zero", "root": r}; rec["roots"] = {str(k): [str(a), str(b)] for k, (a, b) in roots.items()}; return rec
    for r, (lo, hi) in roots.items():
        if lo <= 0:
            rec["status"] = "NUMERIC_UNRESOLVED_POSITIVITY"; rec["roots"] = {str(k): [str(a), str(b)] for k, (a, b) in roots.items()}; rec["counters"] = counters; return rec
    t = time.monotonic(); R.backward(); rec["phases_s"]["backward_intervals"] = time.monotonic() - t
    t = time.monotonic(); reduced_rows = normalize_rows(R.mlo, R.mhi, S.dom)
    # decode to ORIGINAL rows with the checker's OWN decoders
    orig = {}
    for v in range(S.nvars):
        row = []
        for e in S.dec[v]:
            if e[0] == "C":
                row.append((e[1], e[1]))
            else:
                y, s, eta = e[1], e[2], e[3]; pos = S.dom[y].index(s); L, Uu = reduced_rows[y][pos]; row.append((eta * L, eta * Uu))
        orig[v] = row
    wmax = max((Uu - L) for row in orig.values() for L, Uu in row)
    rec["phases_s"]["normalize_decode"] = time.monotonic() - t
    rec["certified_intervals"] = {str(v): [[str(L), str(Uu)] for L, Uu in row] for v, row in orig.items()}
    rec["max_width"] = str(wmax); rec["max_width_float"] = float(wmax); rec["width_met"] = bool(wmax <= PB.MAX_WIDTH)
    rec["roots"] = {str(k): [str(a), str(b)] for k, (a, b) in roots.items()}; rec["counters"] = counters; rec["formats"] = {str(nd["nid"]): nd.get("_fmt_checker") for nd in R.nodes}
    rec["status"] = "INTERVALS_OK"; rec["seconds"] = time.monotonic() - t0
    return rec


def verify_point_mode(checker_json, mar_path, model_path, out_path):
    """Second, separate checker invocation: re-parse the delivered MAR (ext.uai) and verify every row exactly against the
    grid-widened certified intervals of the FIRST invocation's record. The record must (1) be a completed INTERVALS_OK record,
    (2) be bound by raw + canonical hash to THE model file named here, (3) carry one full interval row per original variable."""
    T0 = time.monotonic(); chk = json.load(open(checker_json)); rec = {"status": "POINT_REJECTED"}
    try:
        if chk.get("status") != "INTERVALS_OK":
            raise Reject("checker record status is %r, not INTERVALS_OK" % chk.get("status"))
        src = chk.get("source") or {}
        if src.get("raw_model_sha256") != _raw_hash(model_path) or src.get("canonical_model_sha256") != _canon_hash(model_path):
            raise Reject("checker record is bound to a different model (source hash mismatch)")
        m = U.read_model(model_path); m.check(); card = list(m.card)
        if chk.get("nvars") != m.nvars or list(chk.get("orig_card") or []) != card:
            raise Reject("checker record variable count / cardinalities differ from the model")
        ivs = {}
        for v in range(m.nvars):
            row = (chk.get("certified_intervals") or {}).get(str(v))
            if row is None or len(row) != card[v]:
                raise Reject("interval row of variable %d missing or of wrong length" % v)
            ivs[v] = [(Fr(a), Fr(b)) for a, b in row]
            for L, Uu in ivs[v]:
                if not (0 <= L <= Uu <= 1):
                    raise Reject("malformed interval in row %d" % v)
        if set(ivs) != set(range(m.nvars)):
            raise Reject("interval rows do not cover every original variable")
        ok, why = PB.verify_mar_against_intervals(mar_path, ivs, card)
        rec = {"status": "POINT_VERIFIED" if ok else "POINT_REJECTED", "reason": why, "mar_sha256": _raw_hash(mar_path), "model_sha256": src["raw_model_sha256"], "grid_bits": PB.grid_bits(max(card))}
    except Reject as ex:
        rec = {"status": "POINT_REJECTED", "reason": str(ex)}
    except Exception as ex:
        rec = {"status": "POINT_REJECTED", "reason": "malformed record or input: %s: %s" % (type(ex).__name__, ex)}
    rec["wall_s"] = time.monotonic() - T0; json.dump(rec, open(out_path, "w")); print(json.dumps(rec))


def main():
    if sys.argv[1] == "--verify-point":
        verify_point_mode(*sys.argv[2:6]); return
    cert_path, out_path, deadline_s = sys.argv[1], sys.argv[2], float(sys.argv[3]); T0 = time.monotonic()
    cert = json.load(open(cert_path)); deadline = T0 + deadline_s if deadline_s > 0 else None
    caps = cert.get("checker_caps") or {"dense_core_cap_entries": 1 << 23, "dense_bag_cap_entries": 1 << 21, "sparse_rows_cap": 1 << 23, "lazy_cache_entries": 1 << 20, "value_bytes_cap": int(2.0 * (1 << 30))}
    try:
        rec = check(cert, cert["model_path"], cert["evidence_path"], cert["expected_queries"], deadline, caps)
    except Reject as ex:
        rec = {"status": "REJECTED", "reason": str(ex)}
    except TimeoutError as ex:
        rec = {"status": "CHECKER_INCOMPLETE", "reason": str(ex)}
    except A.NumericalRefusal as ex:
        rec = {"status": "CHECKER_NUMERIC_REFUSAL", "reason": str(ex)}
    except Exception as ex:
        import traceback
        rec = {"status": "CHECKER_FAULT", "reason": "%s: %s" % (type(ex).__name__, ex), "traceback": traceback.format_exc()[-2500:]}
    rec["wall_s"] = time.monotonic() - T0
    try:
        import resource; rec["maxrss_bytes"] = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    except Exception:
        pass
    json.dump(rec, open(out_path, "w"), default=str)
    print(json.dumps({"status": rec["status"], "wall_s": round(rec["wall_s"], 3)}))


if __name__ == "__main__":
    main()
