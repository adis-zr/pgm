"""The INDEPENDENT CHECKER'S side of constraint quotienting (bounded pilot, 3 November 2026).

The checker never consumes the producer's quotient: it RE-DERIVES the closure of forced states and
binary equality / complement relations from the ORIGINAL restricted, preprocessed factor tables with
its own implementation (a worklist over variables with explicit per-factor consistent-entry sets and
a plain parity dictionary; no shared union-find), verifies that EVERY declared relation of the program
is implied by its closure (soundness of the declaration -- a relation the checker cannot derive, a wrong
parity or a wrong forced state is a refusal), REBUILDS the quotient factor tables with its own
construction (scattering every consistent positive original entry into the quotient table and refusing
a slot written twice with different values), and only then runs the numerical verification on that
quotient. The restoration of the original rows is checked exactly (a permutation of the
representative's verified row, or an exact point mass)."""
from __future__ import annotations
from fractions import Fraction as Fr
import itertools
import time
from mdi import model as M
from mdi import arith as A


class _Closure:
    def __init__(self):
        self.fixed = {}
        self.rep = {}        # var -> (root, parity) by repeated lookup (no path compression; a different structure)
        self.members = {}    # root -> set of ALL class members (the root included), for rescheduling after a merge

    def root(self, v):
        p = 0
        seen = 0
        while v in self.rep:
            r, q = self.rep[v]
            p ^= q
            v = r
            seen += 1
            if seen > 100000:
                raise RuntimeError("cycle in the relation map")
        return v, p

    def relate(self, a, b, rel):
        """Relate a XOR b == rel. Returns the set of ALL members of the two classes when they merge
        (every one of them may now make a factor's consistent set smaller), None when nothing changed."""
        ra, pa = self.root(a)
        rb, pb = self.root(b)
        if ra == rb:
            if (pa ^ pb) != rel:
                raise A.NumericalRefusal("checker: inconsistent parity between %d and %d (zero evidence weight)" % (a, b))
            return None
        hi, lo = (ra, rb) if ra > rb else (rb, ra)
        self.rep[hi] = (lo, pa ^ pb ^ rel)
        ma = self.members.pop(hi, {hi})
        mb = self.members.get(lo, {lo})
        merged = set(ma) | set(mb)
        self.members[lo] = merged
        return merged


def rederive(factors, free, card, deadline=None, charge=None, wall_cap_s=None):
    """The checker's own fixpoint: for every factor the set of positive entries consistent with the
    current closure; a singleton projection fixes a variable; a pair projection inside the diagonal /
    anti-diagonal relates two binary variables. Worklist by variable: a factor is re-examined only when
    one of its variables changed (the producer scans every factor every pass). Returns the closure."""
    from mdi import quotient as QT
    wall_cap_s = QT.QUOTIENT_WALL_CAP_S if wall_cap_s is None else float(wall_cap_s)
    t0 = time.monotonic()
    card = dict(card)
    cl = _Closure()
    by_var = {}
    for fi, f in enumerate(factors):
        for v in f.scope:
            by_var.setdefault(v, []).append(fi)
    work = list(range(len(factors)))
    inq = set(work)
    scanned = 0
    final_pass_done = False
    while work or not final_pass_done:
        if not work:
            # the worklist is empty: ONE confirming full pass (every factor once more); if it changes
            # anything the worklist refills and the loop continues, else the fixpoint is confirmed
            final_pass_done = True
            work = list(range(len(factors)))
            inq = set(work)
        fi = work.pop()
        inq.discard(fi)
        f = factors[fi]
        scope = tuple(f.scope)
        if not scope:
            continue
        st = f.strides()
        live = []
        for idx in itertools.product(*[range(int(c)) for c in f.card]):
            scanned += 1
            if f.table[sum(idx[j] * st[j] for j in range(len(scope)))] == 0:
                continue
            ok = True
            vals = {}
            for j, v in enumerate(scope):
                if v in cl.fixed and cl.fixed[v] != idx[j]:
                    ok = False
                    break
                if int(card[v]) == 2:
                    r, p = cl.root(v)
                    val = idx[j] ^ p
                    if vals.get(r, val) != val:
                        ok = False
                        break
                    vals[r] = val
            if ok:
                live.append(idx)
        if charge is not None:
            charge(int(f.size()))
        if time.monotonic() - t0 > wall_cap_s:
            raise QT.QuotientError("checker's re-derivation exceeded its %.1f s cap" % wall_cap_s)
        if deadline is not None:
            deadline()
        if not live:
            raise A.NumericalRefusal("checker: factor over %s has no consistent positive entry (zero evidence weight)" % (scope,))
        touched = set()
        for j, v in enumerate(scope):
            states = set(e[j] for e in live)
            if len(states) == 1:
                s = next(iter(states))
                if v in cl.fixed:
                    if cl.fixed[v] != s:
                        raise A.NumericalRefusal("checker: variable %d forced to two states (zero evidence weight)" % v)
                else:
                    cl.fixed[v] = s
                    touched.add(v)
        for j1 in range(len(scope)):
            a = scope[j1]
            if int(card[a]) != 2 or a in cl.fixed:
                continue
            for j2 in range(j1 + 1, len(scope)):
                b = scope[j2]
                if int(card[b]) != 2 or b in cl.fixed:
                    continue
                pairs = set((e[j1], e[j2]) for e in live)
                rel = 0 if pairs <= {(0, 0), (1, 1)} else (1 if pairs <= {(0, 1), (1, 0)} else None)
                if rel is not None:
                    merged = cl.relate(a, b, rel)
                    if merged:
                        touched |= merged                 # EVERY member of the merged classes, not only a and b
        # a forced member forces its class (and re-examines the class's factors)
        for v in list(cl.fixed):
            if int(card.get(v, 0)) == 2:
                r, p = cl.root(v)
                s_root = cl.fixed[v] ^ p
                for u in list(cl.rep) + [r]:
                    ru, pu = cl.root(u)
                    if ru == r:
                        want = s_root ^ pu
                        if u in cl.fixed:
                            if cl.fixed[u] != want:
                                raise A.NumericalRefusal("checker: class of %d forces %d to two states (zero evidence weight)" % (r, u))
                        else:
                            cl.fixed[u] = want
                            touched.add(u)
        for v in touched:
            for g in by_var.get(v, ()):
                if g not in inq:
                    work.append(g)
                    inq.add(g)
                    final_pass_done = False               # something changed: the confirming pass is owed again
    cl.scanned = scanned
    cl.seconds = time.monotonic() - t0
    # the FINAL deadline check, on the complete elapsed time after the last operation
    if cl.seconds > wall_cap_s:
        raise QT.QuotientError("checker's re-derivation exceeded its %.1f s cap (%.3f s at completion)" % (wall_cap_s, cl.seconds))
    if deadline is not None:
        deadline()
    return cl


def verify_declaration(cl, decl, free, card):
    """Every declared relation must be implied by the checker's closure. Returns the disagreements."""
    bad = []
    fixed = {int(v): int(s) for v, s in decl["fixed"].items()}
    merged = {int(v): (int(a[0]), int(a[1])) for v, a in decl["merged"].items()}
    for v, s in fixed.items():
        if v not in free:
            bad.append("declared fixed variable %d is not a free variable" % v)
        elif v not in cl.fixed:
            bad.append("declared forced state %d=%d is not derivable" % (v, s))
        elif cl.fixed[v] != s:
            bad.append("declared forced state %d=%d, derived %d" % (v, s, cl.fixed[v]))
    for v, (rt, pr) in merged.items():
        if v not in free or rt not in free:
            bad.append("declared merge %d -> %d names a non-free variable" % (v, rt))
            continue
        if int(card[v]) != 2 or int(card[rt]) != 2:
            bad.append("declared merge %d -> %d on a non-binary variable" % (v, rt))
            continue
        if rt in fixed or rt in merged:
            bad.append("declared representative %d is itself fixed or merged" % rt)
            continue
        ra, pa = cl.root(v)
        rb, pb = cl.root(rt)
        if ra != rb:
            bad.append("declared relation %d = %d XOR %d is not derivable" % (v, rt, pr))
        elif (pa ^ pb) != pr:
            bad.append("declared parity of %d -> %d is %d, derived %d" % (v, rt, pr, pa ^ pb))
        if len(bad) >= 6:
            break
    from mdi import quotient as QT
    if QT._digest(fixed, merged) != str(decl.get("digest")):
        bad.append("the declaration's digest does not match its content")
    n_free = len([v for v in free if v not in fixed and v not in merged])
    if int(decl.get("n_free", -1)) != n_free:
        bad.append("declared n_free %s, derived %d" % (decl.get("n_free"), n_free))
    return bad


def build_quotient(r, decl, deadline=None, charge=None):
    """The checker's OWN quotient construction: scatter every original positive entry that is
    consistent with the declaration into the quotient table (indexed by the representatives'
    assignment); a slot written twice with different values is a refusal; a factor with no free
    variable left multiplies its scalar into the constant (zero -> refusal). `deadline` is polled
    once per factor; `charge(n)` receives the original entries scanned."""
    fixed = {int(v): int(s) for v, s in decl["fixed"].items()}
    merged = {int(v): (int(a[0]), int(a[1])) for v, a in decl["merged"].items()}
    free_q = [v for v in r.free if v not in fixed and v not in merged]
    const = Fr(r.constant)
    facs = []
    for f in r.factors:
        if deadline is not None:
            deadline()
        scope = tuple(f.scope)
        st = f.strides()
        reps = []
        for v in scope:
            if v in fixed:
                continue
            rv = merged[v][0] if v in merged else v
            if rv not in reps:
                reps.append(rv)
        qcard = tuple(int(r.card[v]) for v in reps)
        qst = [1] * len(reps)
        acc = 1
        for j in range(len(reps) - 1, -1, -1):
            qst[j] = acc
            acc *= qcard[j]
        if not reps:
            idx = [fixed[v] for v in scope]
            val = Fr(f.table[sum(idx[j] * st[j] for j in range(len(scope)))])
            if val == 0:
                raise A.NumericalRefusal("checker: factor %d is zero at the forced assignment (zero evidence weight)" % f.origin)
            const *= val
            continue
        tab = [None] * acc
        for idx in itertools.product(*[range(int(c)) for c in f.card]):
            # consistency of this ORIGINAL entry with the declaration
            ok = True
            qassign = {}
            for j, v in enumerate(scope):
                if v in fixed:
                    if idx[j] != fixed[v]:
                        ok = False
                        break
                    continue
                rv, pr = merged[v] if v in merged else (v, 0)
                val = idx[j] ^ pr if v in merged else idx[j]
                if qassign.get(rv, val) != val:
                    ok = False
                    break
                qassign[rv] = val
            if not ok:
                continue
            off = sum(qassign[rv] * qst[j] for j, rv in enumerate(reps))
            val = Fr(f.table[sum(idx[j] * st[j] for j in range(len(scope)))])
            if tab[off] is None:
                tab[off] = val
            elif tab[off] != val:
                raise A.NumericalRefusal("checker: the quotient slot of factor %d receives two different values" % f.origin)
        if any(t is None for t in tab):
            raise A.NumericalRefusal("checker: a quotient slot of factor %d has no consistent original entry" % f.origin)
        if charge is not None:
            charge(int(f.size()))
        facs.append(M.Factor(scope=tuple(reps), card=qcard, table=tab, origin=f.origin, scale=f.scale))
    return M.Restricted(model=r.model, evidence=dict(r.evidence), factors=facs, free=free_q,
                        card={v: int(r.card[v]) for v in free_q}, constant=const, impossible_factor=None)


def check_restoration(iv, decl, free, card):
    """The published rows of merged and fixed original variables must be EXACTLY the restoration of
    the representatives' published rows (a permutation) or exact point masses."""
    fixed = {int(v): int(s) for v, s in decl["fixed"].items()}
    merged = {int(v): (int(a[0]), int(a[1])) for v, a in decl["merged"].items()}
    fails = []
    for v in free:
        if v in fixed:
            want = [(Fr(1), Fr(1)) if s == fixed[v] else (Fr(0), Fr(0)) for s in range(int(card[v]))]
            got = [(Fr(lo), Fr(hi)) for lo, hi in iv.get(v, [])]
            if got != want:
                fails.append({"var": v, "reason": "fixed variable not published as the exact point mass at state %d" % fixed[v]})
        elif v in merged:
            rt, pr = merged[v]
            row_r = iv.get(rt)
            row_v = iv.get(v)
            if row_r is None or row_v is None or len(row_v) != 2 or len(row_r) != 2:
                fails.append({"var": v, "reason": "merged variable or its representative lacks a two-state row"})
                continue
            for s in range(2):
                if (Fr(row_v[s][0]), Fr(row_v[s][1])) != (Fr(row_r[s ^ pr][0]), Fr(row_r[s ^ pr][1])):
                    fails.append({"var": v, "state": s, "reason": "row is not the representative %d's row permuted by parity %d" % (rt, pr)})
    return fails
