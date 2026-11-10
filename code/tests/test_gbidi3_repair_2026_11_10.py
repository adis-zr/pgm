"""REPAIR CONTROLS of GENERAL_BIDI_COMPLETE_V3 after the 10 Nov 2026 adversarial review (CLAUDE_REPAIR_PROMPT sections A-F). Every control here first
failed (or could not be expressed) on the unchanged source 67d5be26 (reproductions: review_repro_r1/REPRO_R1_RESULTS.json) and passes on the repaired
code. The existing suite tests/test_gbidi3_complete.py is kept and run unchanged except for the four disclosed fixture changes (C04, C07, C22, seeds).
  RA  semantic validator: the five witnesses reject, their counterparts certify, exhaustive single-field mutations never execute a wrong program
  RB  fail-closed publication: stale / forged / missing verifier receipts, stale deliveries, nonzero exits, wrong identities -> no output.MAR
  RC  reconcilable stops through the REAL harness: exact-scalar / decoder / native successes, invalid input, cooperative stop, hard kill, launch failure, resume
  RD  one whole-path cost: fusion regression n = 3 / 10 / 25 (both candidates recorded, forced merge priced and counted dearer), sparse support-indexed
      reverse (14 binary axes, ternary multi-axis, default policy), honest reverse counters, predicted-vs-counted controls on every path
  RE  reserve-before-build + polling of actual work: one-byte cap stops before one rational is parsed, expired deadline stops before tokenization,
      fallback preparation under a one-byte cap, 200x200 discovery, native wide-ADD poll and sparse downgrade capacity release
  RF  individual qualification: nonbipartite production-path activation of demand / views / fusion with measured savings vs the disabled arm,
      one- vs two-axis EXECUTION, all-consumer demand compilation for a shared program, deterministic fixture seeds"""
from __future__ import annotations
import sys, os, json, time, random, subprocess, ctypes, copy, hashlib, tracemalloc, itertools
import pytest
HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__))); sys.path.insert(0, HERE); sys.path.insert(0, os.path.join(HERE, "tests"))
sys.set_int_max_str_digits(0)
from fractions import Fraction as Fr
from gbidi3 import executor as EX, source as GS, trusted as TR, ir as IR, validate as GV, planner as PL, memory as GM, oracle as OR, demand as DM, reconcile as RC, pilot as PI, identity as ID
from gbidi3.clock import Clock, PlanStop
from adp import source as SRC
from ext import uai as U
import test_gbidi3_complete as Q
PY = sys.executable; ENV = dict(os.environ, PYTHONPATH=HERE)


def work(cc):
    """counted primitive work of one attempt (the proxy's units: lookups / index steps, multiplies, adds, source reads, marker / gather / add visits)"""
    return sum(cc.get(k, 0) for k in ("lookups", "mults", "adds", "adjoint_adds", "source_reads", "marker_updates", "gather_visits", "add_visits", "numerator_adds"))


def jet_rows(V):
    """exact value + first-derivative evaluation of a VALIDATED program (independent of the kernel): returns the normalized original rows it computes"""
    T = V.T; P = V.P; val = {}; Q_ = [(v, a) for v in T.dom for a in range(len(T.dom[v]))]
    def add(x, y):
        return (x[0] + y[0], {k: x[1].get(k, Fr(0)) + y[1].get(k, Fr(0)) for k in Q_})
    def mul(x, y):
        return (x[0] * y[0], {k: x[1].get(k, Fr(0)) * y[0] + x[0] * y[1].get(k, Fr(0)) for k in Q_})
    for n in P.nodes:
        out = {}
        for idx in itertools.product(*(range(c) for c in n.card)):
            if n.kind == IR.SOURCE:
                off = 0
                for a, c in zip(idx, n.card):
                    off = off * c + a
                v = (V.table(n.fid)[off], {})
            elif n.kind == IR.MARKER:
                v = (Fr(1), {(n.var, idx[0]): Fr(1)})
            elif n.kind == IR.CONSTANT:
                v = (Fr(n.value), {})
            elif n.kind == IR.ADD:
                v = (Fr(0), {})
                for ch in n.children:
                    v = add(v, val[ch][idx])
            elif n.kind == IR.MUL:
                v = (Fr(1), {})
                for ch, proj in zip(n.children, n.proj):
                    v = mul(v, val[ch][tuple(idx[p] for p in proj)])
            elif n.kind == IR.GATHER:
                ix = []; scale = Fr(1)
                for g in n.gaxes:
                    raw = idx[g["out_pos"]]; ix.append(raw if g.get("cls") is None else g["cls"][raw]); scale *= Fr(1) if g.get("ratio") is None else g["ratio"][raw]
                v = mul((scale, {}), val[n.children[0]][tuple(ix)])
            else:
                ch = P.nodes[n.children[0]]; ranges = []
                for k, c in enumerate(ch.card):
                    pos = n.rmap[k]; ranges.append(range(c) if pos < 0 else ((idx[pos] if n.reps[k] is None else n.reps[k][0][idx[pos]]),))
                v = (Fr(0), {})
                for ix in itertools.product(*ranges):
                    v = add(v, val[ch.nid][ix])
            out[idx] = v
        val[n.nid] = out
    z = sum((val[r][()][0] for r in P.roots), Fr(0)); z *= (T.scale if V.scale_applied_by == "executor" else 1)
    nu = {}
    for k in Q_:
        nu[k] = sum((val[r][()][1].get(k, Fr(0)) for r in P.roots), Fr(0)) * (T.scale if V.scale_applied_by == "executor" else 1)
    rows = {}
    for v in range(T.nvars):
        rows[v] = []
        for e in T.dec[v]:
            rows[v].append(e[1] / z if e[0] == "C" else nu[(e[1], e[2])] * e[3] / z)
    return rows


# ============================================================================================================ RA  semantic validator (review A)
def _witness_programs(T, card, fs):
    """the reviewer's five illegal proposals rebuilt on the trusted snapshot (unchanged constructions) + their legal counterparts"""
    fid = T.factors[0].fid
    def finish(P, kids, elim):
        m = P.mul(kids); r = P.reduce(m, elim); P.roots = [r.nid]; return P
    def tree_swap(legal):
        P = IR.Program(); f = P.source(fid, (0, 1), (2, 2)); a = P.marker(0, 2); b = P.marker(1, 2); P = finish(P, [f, a, b], (0, 1))
        if not legal:
            m = P.nodes[-2]; m.proj = ((1, 0), m.proj[1], m.proj[2])
        return P
    def product_omit(legal):
        P = IR.Program(); P.derived = {101: {"kind": "product_split", "parent": fid, "axis_k": 0, "u": (1, 2), "g": (1, 3), "part": "u"}}
        if legal:
            P.derived[102] = {"kind": "product_split", "parent": fid, "axis_k": 0, "u": (1, 2), "g": (1, 3), "part": "g"}
        f = P.source(101, (0,), (2,)); a = P.marker(0, 2); b = P.marker(1, 2); kids = [f, a, b]
        if legal:
            kids.insert(1, P.source(102, (1,), (2,)))
        return finish(P, kids, (0, 1))
    def additive_dup(legal):
        P = IR.Program(); w = {"kind": "additive_split", "parent": fid, "parts": [(1, 1), (0, 2)], "index": 0}
        P.derived = {101: copy.deepcopy(w), 102: dict(copy.deepcopy(w), index=(1 if legal else 0))}
        f1 = P.source(101, (0,), (2,)); f2 = P.source(102, (0,), (2,)); ad = P.addn([f1, f2]); a = P.marker(0, 2); return finish(P, [ad, a], (0,))
    def forged_gather(legal):
        P = IR.Program(); f = P.source(fid, (0,), (2,)); g = P.gather(f, (0,), (2,), gaxes=[{"out_pos": 0, "ratio": (Fr(1), Fr(3))} if not legal else {"out_pos": 0}]); a = P.marker(0, 2); return finish(P, [g, a], (0,))
    def marked_view(legal):
        P = IR.Program(); f = P.source(fid, (0, 1), (2, 2)); a = P.marker(0, 2); b = P.marker(1, 2); m = P.mul([f, a, b])
        if legal:
            r = P.reduce(m, (0, 1)); P.roots = [r.nid]; return P
        r = P.reduce(m, (0,), reps={1: ((0,), (0, 0), (Fr(1), Fr(1)))}); g = P.gather(r, (1,), (2,), gaxes=[{"out_pos": 0, "cls": (0, 0), "ratio": (Fr(1), Fr(1))}]); z = P.reduce(g, (1,)); P.roots = [z.nid]; return P
    return {"tree_projection_swap": tree_swap, "product_split_omitted_complement": product_omit, "additive_split_duplicate_index": additive_dup, "forged_identity_gather_scale": forged_gather, "marked_axis_compression": marked_view}


WITNESS_INPUTS = {"tree_projection_swap": ([2, 2], [((0, 1), (1, 2, 3, 4))]), "product_split_omitted_complement": ([2, 2], [((0, 1), (1, 3, 2, 6))]), "additive_split_duplicate_index": ([2], [((0,), (1, 3))]),
                  "marked_axis_compression": ([2, 2], [((0, 1), (1, 1, 1, 1))]), "forged_identity_gather_scale": ([2], [((0,), (1, 1))])}


def _snapshot(tmp_path, name, card, fs):
    mp, ep = Q.write_uai(str(tmp_path / (name + ".uai")), card, [(sc, list(t)) for sc, t in fs]); S = GS.Snapshot(mp, ep); R = SRC.Reduced(EX._ModelAdapter(S.model), {}); R.reduce(()); return mp, ep, S, TR.TrustedReduced(R)


@pytest.mark.parametrize("name", sorted(WITNESS_INPUTS))
def test_RA1_five_witnesses_reject_and_their_legal_counterparts_certify(tmp_path, name):
    card, fs = WITNESS_INPUTS[name]; mp, ep, S, T = _snapshot(tmp_path, name, card, fs); Z, N, truth = OR.rows(S.model, S.ev); build = _witness_programs(T, card, fs)[name]
    with pytest.raises((TR.Invalid, IR.IRError)):
        GV.validate(build(False), T)
    V = GV.validate(build(True), T); assert V.record["status"] == "VALID" and jet_rows(V) == {v: list(r) for v, r in enumerate(truth)}
    for b64 in (False, True):
        def mutate(P, legal):
            p = build(legal); P.nodes = p.nodes; P.roots = p.roots; P.derived = p.derived
        with pytest.raises(EX.Refuse) as ex:                                                                  # the illegal proposal never reaches the kernel through the executor
            Q.run("GENERAL_BIDI_COMPLETE_V3", mp, ep, str(tmp_path / ("bad%d" % b64)), rules=[], b64=b64, fallback=False, hooks={"mutate_program": lambda P: mutate(P, False)})
        assert ex.value.kind == "REJECTED" and not os.path.exists(str(tmp_path / ("bad%d" % b64) / "output.MAR"))
        rec = Q.run("GENERAL_BIDI_COMPLETE_V3", mp, ep, str(tmp_path / ("ok%d" % b64)), rules=[], b64=b64, hooks={"mutate_program": lambda P: mutate(P, True)})
        st, cell = Q.publish(str(tmp_path / ("ok%d" % b64)), mp, ep, rec); assert st == "CERTIFIED" and Q.contained(rec, truth), (st, cell.get("publication"))


def _mutations(P):
    """every single-field mutation of every mutable proposal field (deterministic enumeration): yields (label, mutated program)"""
    def M(label, fn):
        Qp = copy.deepcopy(P)
        try:
            fn(Qp)
        except Exception:
            return None
        return (label, Qp)
    out = []
    for n in P.nodes:
        i = n.nid
        if len(n.axes) >= 2:
            out.append(M("axes_swap@%d" % i, lambda Qp, i=i: setattr(Qp.nodes[i], "axes", (Qp.nodes[i].axes[1], Qp.nodes[i].axes[0]) + Qp.nodes[i].axes[2:])))
            out.append(M("card_swap@%d" % i, lambda Qp, i=i: setattr(Qp.nodes[i], "card", (Qp.nodes[i].card[1], Qp.nodes[i].card[0]) + Qp.nodes[i].card[2:])))
        if n.card:
            out.append(M("card_plus@%d" % i, lambda Qp, i=i: setattr(Qp.nodes[i], "card", (Qp.nodes[i].card[0] + 1,) + Qp.nodes[i].card[1:])))
            out.append(M("card_minus@%d" % i, lambda Qp, i=i: setattr(Qp.nodes[i], "card", (max(1, Qp.nodes[i].card[0] - 1),) + Qp.nodes[i].card[1:])))
        if n.axes:
            out.append(M("axes_rename@%d" % i, lambda Qp, i=i: setattr(Qp.nodes[i], "axes", (max(a for m in Qp.nodes for a in m.axes) + 1,) + Qp.nodes[i].axes[1:])))
        if n.children:
            out.append(M("child_drop@%d" % i, lambda Qp, i=i: (setattr(Qp.nodes[i], "children", Qp.nodes[i].children[1:]), setattr(Qp.nodes[i], "proj", Qp.nodes[i].proj[1:]) if Qp.nodes[i].kind == IR.MUL else None)))
            out.append(M("child_dup@%d" % i, lambda Qp, i=i: (setattr(Qp.nodes[i], "children", Qp.nodes[i].children + Qp.nodes[i].children[:1]), setattr(Qp.nodes[i], "proj", Qp.nodes[i].proj + Qp.nodes[i].proj[:1]) if Qp.nodes[i].kind == IR.MUL else None)))
            out.append(M("child_redirect@%d" % i, lambda Qp, i=i: setattr(Qp.nodes[i], "children", (max(0, Qp.nodes[i].children[0] - 1),) + Qp.nodes[i].children[1:])))
        if n.kind == IR.MUL:
            for j in range(len(n.children)):
                if len(n.proj[j]) >= 2:
                    out.append(M("proj_swap@%d.%d" % (i, j), lambda Qp, i=i, j=j: setattr(Qp.nodes[i], "proj", tuple((pr[1], pr[0]) + pr[2:] if q == j else pr for q, pr in enumerate(Qp.nodes[i].proj)))))
                out.append(M("proj_shift@%d.%d" % (i, j), lambda Qp, i=i, j=j: setattr(Qp.nodes[i], "proj", tuple(tuple((p + 1) % len(Qp.nodes[i].axes) for p in pr) if q == j else pr for q, pr in enumerate(Qp.nodes[i].proj)))))
        if n.kind == IR.REDUCE:
            for k in range(len(n.rmap)):
                out.append(M("rmap_flip@%d.%d" % (i, k), lambda Qp, i=i, k=k: setattr(Qp.nodes[i], "rmap", tuple((-1 if r >= 0 else 0) if q == k else r for q, r in enumerate(Qp.nodes[i].rmap)))))
                if n.reps[k] is not None:
                    out.append(M("reps_merge@%d.%d" % (i, k), lambda Qp, i=i, k=k: setattr(Qp.nodes[i], "reps", tuple((r[0], tuple(0 for _ in r[1]), r[2]) if q == k and r is not None else r for q, r in enumerate(Qp.nodes[i].reps)))))
                    out.append(M("reps_ratio@%d.%d" % (i, k), lambda Qp, i=i, k=k: setattr(Qp.nodes[i], "reps", tuple((r[0], r[1], (r[2][0] * 2,) + tuple(r[2][1:])) if q == k and r is not None else r for q, r in enumerate(Qp.nodes[i].reps)))))
                    out.append(M("reps_drop@%d.%d" % (i, k), lambda Qp, i=i, k=k: setattr(Qp.nodes[i], "reps", tuple(None if q == k else r for q, r in enumerate(Qp.nodes[i].reps)))))
                else:
                    out.append(M("reps_forge@%d.%d" % (i, k), lambda Qp, i=i, k=k: setattr(Qp.nodes[i], "reps", tuple(((0,), tuple(0 for _ in range(Qp.nodes[Qp.nodes[i].children[0]].card[k])), tuple(Fr(1) for _ in range(Qp.nodes[Qp.nodes[i].children[0]].card[k]))) if q == k else r for q, r in enumerate(Qp.nodes[i].reps)))))
            out.append(M("storage_sparse@%d" % i, lambda Qp, i=i: setattr(Qp.nodes[i], "storage", IR.SPARSE)))
            out.append(M("demand_empty@%d" % i, lambda Qp, i=i: (setattr(Qp.nodes[i], "storage", IR.DENSE), setattr(Qp.nodes[i], "demand", "EMPTY"))))
            out.append(M("demand_bad@%d" % i, lambda Qp, i=i: (setattr(Qp.nodes[i], "storage", IR.DENSE), setattr(Qp.nodes[i], "demand", (Qp.nodes[i].volume,)))))
        if n.kind == IR.GATHER:
            for k in range(len(n.gaxes)):
                out.append(M("gaxes_cls@%d.%d" % (i, k), lambda Qp, i=i, k=k: setattr(Qp.nodes[i], "gaxes", tuple(dict(g, cls=tuple(0 for _ in range(Qp.nodes[i].card[g["out_pos"]])), ratio=tuple(Fr(1) for _ in range(Qp.nodes[i].card[g["out_pos"]]))) if q == k else g for q, g in enumerate(Qp.nodes[i].gaxes)))))
                out.append(M("gaxes_ratio@%d.%d" % (i, k), lambda Qp, i=i, k=k: setattr(Qp.nodes[i], "gaxes", tuple(dict(g, ratio=tuple(Fr(2) for _ in range(Qp.nodes[i].card[g["out_pos"]]))) if q == k else g for q, g in enumerate(Qp.nodes[i].gaxes)))))
                out.append(M("gaxes_pos@%d.%d" % (i, k), lambda Qp, i=i, k=k: setattr(Qp.nodes[i], "gaxes", tuple(dict(g, out_pos=(g["out_pos"] + 1) % max(1, len(Qp.nodes[i].axes))) if q == k else g for q, g in enumerate(Qp.nodes[i].gaxes)))))
        if n.kind == IR.SOURCE:
            others = sorted({m.fid for m in P.nodes if m.kind == IR.SOURCE and m.fid != n.fid})
            if others:
                out.append(M("fid_other@%d" % i, lambda Qp, i=i, o=others[0]: setattr(Qp.nodes[i], "fid", o)))
            out.append(M("fid_unknown@%d" % i, lambda Qp, i=i: setattr(Qp.nodes[i], "fid", 10 ** 6)))
        if n.kind == IR.MARKER:
            others = sorted({m.var for m in P.nodes if m.kind == IR.MARKER and m.var != n.var})
            if others:
                out.append(M("var_other@%d" % i, lambda Qp, i=i, o=others[0]: (setattr(Qp.nodes[i], "var", o), setattr(Qp.nodes[i], "axes", (o,)))))
        if n.kind == IR.CONSTANT:
            out.append(M("const_value@%d" % i, lambda Qp, i=i: setattr(Qp.nodes[i], "value", Qp.nodes[i].value * 2)))
    out.append(M("root_dup", lambda Qp: Qp.roots.append(Qp.roots[0])))
    out.append(M("root_drop", lambda Qp: Qp.roots.pop()))
    scal = [n.nid for n in P.nodes if not n.card and n.nid not in P.roots]
    if scal:
        out.append(M("root_extra", lambda Qp, s=scal[0]: Qp.roots.append(s)))
    for dfid, d in (P.derived or {}).items():
        for key in ("parent", "index", "part", "kind", "axis_k"):
            if key in d:
                out.append(M("derived_%s@%s" % (key, dfid), lambda Qp, dfid=dfid, key=key: Qp.derived[dfid].__setitem__(key, {"parent": 10 ** 6, "index": 5, "part": "g" if d.get("part") == "u" else "u", "kind": "additive_split" if d["kind"] == "product_split" else "product_split", "axis_k": 7}[key])))
        if "parts" in d:
            out.append(M("derived_parts@%s" % dfid, lambda Qp, dfid=dfid: Qp.derived[dfid].__setitem__("parts", [tuple(x * 2 for x in t) for t in Qp.derived[dfid]["parts"]])))
        if "u" in d:
            out.append(M("derived_u@%s" % dfid, lambda Qp, dfid=dfid: Qp.derived[dfid].__setitem__("u", tuple(x * 2 for x in Qp.derived[dfid]["u"]))))
    return [m for m in out if m is not None]


def _adversarial(P, T, truth):
    rejected = 0; accepted_equal = 0; wrong = []
    for label, Qp in _mutations(P):
        try:
            V = GV.validate(Qp, T)
        except (TR.Invalid, IR.IRError):
            rejected += 1; continue
        except Exception as ex:                                                                            # a crash of the validator on a malformed proposal is a defect: it must REJECT
            wrong.append((label, "validator raised %s" % type(ex).__name__)); continue
        got = jet_rows(V)
        if got == truth:
            accepted_equal += 1
        else:
            wrong.append((label, "accepted but wrong"))
    return rejected, accepted_equal, wrong


def test_RA2_every_single_field_mutation_is_rejected_or_still_exact_on_the_tree_route(tmp_path):
    card = [3, 2, 3, 2]; facs = Q.rnd_model(20, card, [(0, 1), (1, 2), (2, 3), (0, 3)], zeros=0.2); mp, ep = Q.write_uai(str(tmp_path / "m.uai"), card, facs); S, Z, N, rows = Q.truth(mp, ep)
    truth = {v: list(r) for v, r in enumerate(rows)}; total = 0
    for sw in (dict(two_axis=False), dict(two_axis=True), dict(views=False, two_axis=False, demand_masks=False, fusion=False)):
        S_, R_, T, plan, cands = Q.plan_program(mp, ep, **sw); P = plan.program; assert GV.validate(P, T).record["status"] == "VALID" and jet_rows(GV.validate(P, T)) == truth
        rej, ok, wrong = _adversarial(P, T, truth); total += rej + ok
        assert not wrong, wrong[:6]
        assert rej >= 20 and ok >= 1, (rej, ok)                                                             # most mutations are illegal; some are legal rewrites (e.g. a storage change) and stay exact
    assert total >= 150


def test_RA3_every_single_field_mutation_is_rejected_or_still_exact_on_the_shared_dag_route(tmp_path):
    mp, ep = Q.write_uai(str(tmp_path / "c03.uai"), [2], [((0,), [1, 2]), ((0,), [1, 1])]); S, Z, N, rows = Q.truth(mp, ep); truth = {v: list(r) for v, r in enumerate(rows)}
    S_, R_, T, plan, cands = Q.plan_program(mp, ep); P = Q._shared_consumer_program(T, IR.DENSE); V = GV.validate(P, T); assert V.record["status"] == "VALID" and jet_rows(V) == truth
    rej, ok, wrong = _adversarial(P, T, truth); assert not wrong, wrong[:6]; assert rej >= 15 and ok >= 1, (rej, ok)
    mp2, ep2 = Q.write_uai(str(tmp_path / "c15.uai"), [2, 2], [((0,), [1, 3]), ((1,), [2, 3])]); S2, Z2, N2, rows2 = Q.truth(mp2, ep2); truth2 = {v: list(r) for v, r in enumerate(rows2)}
    S_, R_, T2, plan2, _ = Q.plan_program(mp2, ep2, rules=()); P2 = Q._c15_program(T2); V2 = GV.validate(P2, T2); assert jet_rows(V2) == truth2
    rej2, ok2, wrong2 = _adversarial(P2, T2, truth2); assert not wrong2, wrong2[:6]; assert rej2 >= 15


# ============================================================================================================ RB  fail-closed publication (review B)
def test_RB1_publication_never_inherits_a_stale_or_forged_verifier_result(tmp_path, monkeypatch):
    card = [2, 3]; mp, ep = Q.write_uai(str(tmp_path / "t.uai"), card, [((0, 1), [1, 2, 3, 4, 5, 6]), ((0,), [2, 1])], {0: 0}); S, Z, N, rows = Q.truth(mp, ep)
    out = str(tmp_path / "x"); rec = Q.run("GENERAL_BIDI_COMPLETE_V3", mp, ep, out, rules=[], b64=False); st, cell = Q.publish(out, mp, ep, rec); assert st == "CERTIFIED" and os.path.exists(os.path.join(out, "output.MAR"))
    real_run = subprocess.run
    def fake(kind):
        def run_(cmd, **kw):
            if "gbidi3.verify" not in cmd:
                return real_run(cmd, **kw)
            pc, exp_path = cmd[7], cmd[8]
            if kind == "exit_without_receipt":
                return subprocess.CompletedProcess(cmd, 0, b"", b"")
            if kind == "nonzero_but_verified":
                r = real_run(cmd, **kw); return subprocess.CompletedProcess(cmd, 2, r.stdout, b"forced nonzero")
            r = real_run(cmd, **kw); v = json.load(open(pc))
            if kind == "wrong_hash":
                v["mar_sha256"] = "0" * 64
            elif kind == "wrong_execution":
                v["execution"] = dict(v["execution"], attempt_id="forged")
            elif kind == "wrong_task":
                v["task"] = dict(v["task"], raw_model_sha256="0" * 64)
            elif kind == "wrong_expected_hash":
                v["expected_identity_sha256"] = "0" * 64
            json.dump(v, open(pc, "w")); return r
        return run_
    for kind in ("exit_without_receipt", "nonzero_but_verified", "wrong_hash", "wrong_execution", "wrong_task", "wrong_expected_hash"):
        monkeypatch.setattr(EX.subprocess, "run", fake(kind))
        st, cell = Q.publish(out, mp, ep, rec)                                                                # the SAME record and bytes as the earlier success: the stale success must not survive
        monkeypatch.setattr(EX.subprocess, "run", real_run)
        assert st == "CHECK_FAILED" and not os.path.exists(os.path.join(out, "output.MAR")) and not os.path.exists(os.path.join(out, "output.MAR.tmp")), (kind, st, cell.get("publication"))
        assert not [f for f in os.listdir(out) if f.startswith("point_check")], kind
    st, cell = Q.publish(out, mp, ep, rec); assert st == "CERTIFIED" and os.path.exists(os.path.join(out, "output.MAR"))             # a clean retry certifies again from scratch
    # a stale POINT_VERIFIED receipt for a DIFFERENT task staged into a fresh directory never counts (the receipt tag is attempt- and bytes-specific; every point_check* is removed before launch)
    out2 = str(tmp_path / "y"); os.makedirs(out2); import shutil
    for f in os.listdir(out):
        if f.startswith("point_check") or f == "output.MAR":
            shutil.copy(os.path.join(out, f), os.path.join(out2, f))
    mp1, ep1 = Q.write_uai(str(tmp_path / "t1.uai"), card, [((0, 1), [1, 2, 3, 4, 5, 6]), ((0,), [2, 1])], {0: 1})
    st, cell = Q.publish(out2, mp1, ep1, rec); assert st == "CHECK_FAILED" and not os.path.exists(os.path.join(out2, "output.MAR")) and "bound" in cell["publication"]["reason"]
    # the verifier itself: nonzero exit + POINT_REJECTED without the expected-identity file, with a wrong expected hash, with a different execution identity
    r = subprocess.run([PY, "-m", "gbidi3.verify", os.path.join(out, "checked_record.json"), os.path.join(out, "output.MAR"), mp, ep, str(tmp_path / "v.json")], capture_output=True, cwd=HERE, env=ENV); assert r.returncode == 2 and json.load(open(tmp_path / "v.json"))["status"] == "POINT_REJECTED"
    exp = {"task": S.task, "execution": dict(rec["execution"], attempt_id="other"), "mar_sha256": EX.sha_file(os.path.join(out, "output.MAR"))}; json.dump(exp, open(tmp_path / "e.json", "w"))
    r = subprocess.run([PY, "-m", "gbidi3.verify", os.path.join(out, "checked_record.json"), os.path.join(out, "output.MAR"), mp, ep, str(tmp_path / "v2.json"), str(tmp_path / "e.json"), "20"], capture_output=True, cwd=HERE, env=ENV); assert r.returncode == 2 and "execution identity" in json.load(open(tmp_path / "v2.json"))["reason"]
    exp["execution"] = rec["execution"]; exp["mar_sha256"] = "0" * 64; json.dump(exp, open(tmp_path / "e.json", "w"))
    r = subprocess.run([PY, "-m", "gbidi3.verify", os.path.join(out, "checked_record.json"), os.path.join(out, "output.MAR"), mp, ep, str(tmp_path / "v3.json"), str(tmp_path / "e.json"), "20"], capture_output=True, cwd=HERE, env=ENV); assert r.returncode == 2 and "not the bytes" in json.load(open(tmp_path / "v3.json"))["reason"]
    # a record whose execution identity does not match the caller's build / config / route is refused BEFORE any verifier launch
    for mut in (lambda r: r["execution"]["implementation"].__setitem__("binary_sha256", "0" * 64), lambda r: r["execution"].__setitem__("config_sha256", "0" * 64), lambda r: r["execution"].__setitem__("route", "exact_scalar"), lambda r: r.__setitem__("execution", None), lambda r: r["execution"].__setitem__("protocol", "other")):
        r2 = copy.deepcopy(rec); mut(r2); o = str(tmp_path / ("m%d" % abs(hash(str(mut))) ) ); os.makedirs(o, exist_ok=True); st, cell = Q.publish(o, mp, ep, r2); assert st == "CHECK_FAILED" and "execution identity" in cell["publication"]["reason"] and not os.listdir(o) or not os.path.exists(os.path.join(o, "output.MAR")), (st, cell.get("publication"))
    # publish refuses without the caller's arm / configuration (nothing to bind against)
    cell2 = {"phases_s": {}}; st = EX.publish(out, mp, ep, rec, cell2, time.monotonic() + 30); assert st == "CHECK_FAILED" and "execution identity" in cell2["publication"]["reason"]


def test_RB2_one_launch_relative_deadline_reaches_the_verifier_and_a_late_publication_is_a_typed_stop(tmp_path):
    card = [2, 3]; mp, ep = Q.write_uai(str(tmp_path / "t.uai"), card, [((0, 1), [1, 2, 3, 4, 5, 6]), ((0,), [2, 1])]); rec = Q.run("GENERAL_BIDI_COMPLETE_V3", mp, ep, str(tmp_path / "x"), rules=[], b64=False)
    cell = {"phases_s": {}}; st = EX.publish(str(tmp_path / "x"), mp, ep, rec, cell, time.monotonic() - 1, arm=rec["arm"], cfg=rec["config"]); assert st == "RESOURCE_STOP" and "DEADLINE" in cell["publication"]["reason"] and not os.path.exists(str(tmp_path / "x" / "output.MAR"))
    # through the cell: the deadline is launch-relative when GBIDI_LAUNCH_MONO is set (an old launch stamp -> the cell stops cooperatively, classified on the launch clock)
    env = dict(ENV, GBIDI_LAUNCH_MONO="%.6f" % (time.monotonic() - 100)); out = str(tmp_path / "late")
    subprocess.run([PY, "-m", "gbidi3.cell", "GENERAL_BIDI_COMPLETE_V3", mp, ep, out, "20", "{}"], capture_output=True, cwd=HERE, env=env, timeout=120); c = json.load(open(os.path.join(out, "cell.json")))
    assert c["deadline_origin"] == "launch" and c["status"] in ("RESOURCE_STOP", "LATE_OUTPUT") and c["deadline_classification_clock"] == "launch-relative" and not os.path.exists(os.path.join(out, "output.MAR")), (c["status"], c.get("reason"))


# ============================================================================================================ RC  reconcilable stops through the REAL harness (review C)
def _manifest(tmp_path, cases, cells, mem_gib=None):
    from gbidi3 import pilot as PI
    br = json.load(open(os.path.join(HERE, "gbidi3", "BUILD_RECORD.json"))); cfg_adp = os.path.join(HERE, "runs", "mdi_2026-10-28", "AGGREGATE_DP_CENSUS_2026-11-08", "CONFIG_new_arm.json")
    man = {"pass": "QUALIFICATION_E2E_REPAIR", "manifest_status": "FROZEN", "qualification_unfrozen": True, "frozen_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(time.time() - 2)), "commit": "unfrozen", "branch": "test", "seed": PI.SEED,
           "source_files_sha256": {f: EX.sha_file(os.path.join(HERE, f)) for f in ["gbidi3/executor.py", "gbidi3/kernel3.cpp", "gbidi3/pilot.py", "gbidi3/reconcile.py", "gbidi/supervise.py"]}, "kernel_binary_sha256": br["binary_sha256"], "kernel_build": br, "python_sources_sha256": ID.python_sources_sha256(), "protocol": ID.PROTOCOL,
           "config_adp_repaired_path": os.path.relpath(cfg_adp, HERE), "config_adp_repaired_sha256": EX.sha_file(cfg_adp), "common_rules": PL.COMMON_RULES if hasattr(PL, "COMMON_RULES") else [], "arms_config": {a: dict(PL.ARMS[a], cell_config=PI.CELL_CONFIG) for a in PL.ARMS}, "ceiling_s": 28800.0, "closeout_reserve_s": 0.0, "cases": cases, "unavailable_slots": [], "cells": []}
    if mem_gib is not None:
        man["mem_gib"] = mem_gib
    for i, c in enumerate(cells):
        tid, cid = PI.canonical_task(cases[c["case"]], c, man["config_adp_repaired_sha256"], br["binary_sha256"], man["commit"])
        man["cells"].append(dict(c, index=i, task_id=tid, cell_id=cid, producer_arm=c["arm"], out_dir="cells/%s/%03d__%s__%s__%s" % (c["stage"], i, c["case"], c["arm"], tid), max_permitted_charge_s=c["budget_s"] + 6.0))
    return man


def _case(S, mp, ep, nvars):
    return dict({k: S.task[k] for k in GS.TASK_BINDING_FIELDS}, family="F", model_path=mp, evidence_path=ep, variables=nvars)


def _stage(D, name, extra_env=None):
    return subprocess.run([PY, "-m", "gbidi.supervise", "--ledger", os.path.join(D, "GB_LEDGER.jsonl"), "--scope", "stage_outer_" + name, "--job", "stage_runner:" + name, "--timeout", "600", "--cwd", HERE, "--env", "PYTHONPATH=" + HERE] + sum([["--env", "%s=%s" % kv] for kv in (extra_env or {}).items()], []) + ["--", PY, "-m", "gbidi3.pilot", "run", D, name], capture_output=True, text=True, cwd=HERE, env=ENV, timeout=900)


def test_RC1_every_attempt_outcome_is_reconciled_through_the_real_supervision_and_resume_never_relaunches(tmp_path):
    from gbidi3_closeout import report as R
    D = str(tmp_path / "run"); os.makedirs(D); inp = tmp_path / "in"; inp.mkdir(); dec = lambda q: "%d.%02d" % divmod(q.numerator * (100 // q.denominator), 100)
    card = [2, 3, 2]; facs = Q.rnd_model(12, card, [(0, 1), (1, 2), (0, 2)]); mp, ep = Q.write_uai(str(inp / "N.uai"), card, facs, {2: 1}, tokens=[[dec(x) for x in tab] for _, tab in facs]); S, Z, N, rows = Q.truth(mp, ep)
    mz = str(inp / "Z.uai"); open(mz, "w").write("MARKOV 0 1 0 1 3/7\n"); open(mz + ".evid", "w").write(""); SZ = GS.Snapshot(mz, mz + ".evid")                      # zero-variable task: exact_scalar route
    md, ed = Q.write_uai(str(inp / "D.uai"), [2, 2], [((0, 1), [1, 2, 3, 4])], {0: 0, 1: 1}); SD = GS.Snapshot(md, ed)                                                           # every variable fixed: exact_decoder route
    mi = str(inp / "I.uai"); open(mi, "w").write("MARKOV\n2\n2 2\n1\n2 0 1\n3\n1 2 3\n"); open(mi + ".evid", "w").write(""); SI = GS.Snapshot.__new__(GS.Snapshot)               # malformed (table declares 3 of 4 entries): INVALID_INPUT
    n = 3000; mk = str(inp / "K.uai"); open(mk, "w").write("\n".join(["MARKOV", str(n), " ".join(["1"] * n), str(n - 1)] + ["2 %d %d" % (i, i + 1) for i in range(n - 1)] + ["1 1"] * (n - 1)) + "\n"); open(mk + ".evid", "w").write(""); SK = GS.Snapshot(mk, mk + ".evid")   # slow enough for a HARD kill
    raw = lambda p: hashlib.sha256(open(p, "rb").read()).hexdigest()
    cases = {"N": _case(S, mp, ep, 3), "Z": _case(SZ, mz, mz + ".evid", 0), "D": _case(SD, md, ed, 2), "K": _case(SK, mk, mk + ".evid", n),
             "I": dict({k: "x" for k in GS.TASK_BINDING_FIELDS}, raw_model_sha256=raw(mi), raw_evidence_sha256=raw(mi + ".evid"), family="F", model_path=mi, evidence_path=mi + ".evid", variables=2)}
    cells = [{"stage": "ok", "arm": "GENERAL_BIDI_COMPLETE_V3", "case": "N", "budget_s": 20.0, "kind": "primary"}, {"stage": "ok", "arm": "NATIVE_PLAIN_COMPLETE_V3", "case": "N", "budget_s": 20.0, "kind": "primary"},
             {"stage": "ok", "arm": "GENERAL_BIDI_COMPLETE_V3", "case": "Z", "budget_s": 20.0, "kind": "primary"}, {"stage": "ok", "arm": "GENERAL_BIDI_COMPLETE_V3", "case": "D", "budget_s": 20.0, "kind": "primary"},
             {"stage": "ok", "arm": "GENERAL_BIDI_COMPLETE_V3", "case": "I", "budget_s": 20.0, "kind": "primary"},
             {"stage": "ok", "arm": "GENERAL_BIDI_COMPLETE_V3", "case": "K", "budget_s": 0.05, "kind": "primary"},                                                            # cooperative stop: the deadline passes during startup / parsing
             {"stage": "kill", "arm": "GENERAL_BIDI_COMPLETE_V3", "case": "K", "budget_s": 20.0, "kind": "primary", "mem_gib": 0.03},                                        # HARD kill by the real supervisor (sampled RSS over 30 MiB) before any record
             {"stage": "launch", "arm": "GENERAL_BIDI_COMPLETE_V3", "case": "N", "budget_s": 20.0, "kind": "primary"}]
    man = _manifest(tmp_path, cases, cells); json.dump(man, open(os.path.join(D, "GB_MANIFEST.json"), "w")); assert PI.reconcile_manifest(man) is None
    r1 = _stage(D, "ok"); assert "STOP:" not in r1.stdout, r1.stdout[-800:] + r1.stderr[-800:]
    r2 = _stage(D, "kill"); assert "STOP:" not in r2.stdout, r2.stdout[-800:] + r2.stderr[-800:]
    r3 = _stage(D, "launch", {"GBIDI_CELL_PY": "/nonexistent/python"}); assert "STOP:" not in r3.stdout, r3.stdout[-800:] + r3.stderr[-800:]
    rws = {(r["case"], r["arm"], r["stage"]): r for r in R.cells_ledger(D, man)}
    assert all(r["accepted"] for r in rws.values()), [(k, r["reasons"]) for k, r in rws.items() if not r["accepted"]]
    assert rws[("N", "GENERAL_BIDI_COMPLETE_V3", "ok")]["status"] == "CERTIFIED" and rws[("N", "NATIVE_PLAIN_COMPLETE_V3", "ok")]["status"] == "CERTIFIED" and rws[("N", "GENERAL_BIDI_COMPLETE_V3", "ok")]["route"] in ("mpfr", "binary64")
    assert rws[("Z", "GENERAL_BIDI_COMPLETE_V3", "ok")]["status"] == "CERTIFIED" and rws[("Z", "GENERAL_BIDI_COMPLETE_V3", "ok")]["route"] == "exact_scalar" and rws[("Z", "GENERAL_BIDI_COMPLETE_V3", "ok")]["execution"]["implementation"]["kind"] == "python_exact"
    assert rws[("D", "GENERAL_BIDI_COMPLETE_V3", "ok")]["status"] == "CERTIFIED" and rws[("D", "GENERAL_BIDI_COMPLETE_V3", "ok")]["route"] == "exact_decoder"
    assert rws[("I", "GENERAL_BIDI_COMPLETE_V3", "ok")]["status"] == "INVALID_INPUT" and rws[("I", "GENERAL_BIDI_COMPLETE_V3", "ok")]["delivered_valid_output"] is False and rws[("I", "GENERAL_BIDI_COMPLETE_V3", "ok")]["task_binding"].startswith("RAW_HASHES_ONLY")
    assert rws[("N", "GENERAL_BIDI_COMPLETE_V3", "ok")]["task_binding"] == "FULL"
    coop = rws[("K", "GENERAL_BIDI_COMPLETE_V3", "ok")]; assert coop["status"] == "RESOURCE_STOP" and coop["supervisor_outcome"] == "COMPLETED" and "DEADLINE" in (coop.get("reason") or ""), (coop["status"], coop.get("reason"))
    killed = rws[("K", "GENERAL_BIDI_COMPLETE_V3", "kill")]; assert killed["status"] == "NO_RECORD" and killed["supervisor_outcome"] == "MEMORY_KILL" and killed["resolution"] == "KILLED_NO_RECORD" and killed["producer_diagnostics"].startswith("UNAVAILABLE") and killed["expected_task"]["cell_id"] == killed["cell_id"]
    lf = rws[("N", "GENERAL_BIDI_COMPLETE_V3", "launch")]; assert lf["status"] == "LAUNCH_FAILED" and lf["supervisor_outcome"] == "LAUNCH_FAILED" and lf["resolution"] == "LAUNCH_FAILED" and lf["launch_error"]
    for key in (("N", "GENERAL_BIDI_COMPLETE_V3", "ok"), ("N", "NATIVE_PLAIN_COMPLETE_V3", "ok")):
        pts, _ = U.read_mar(os.path.join(D, rws[key]["out_dir"], "output.MAR")); assert all(abs(Fr(pts[v][s]) - rows[v][s]) < Fr(1, 200) for v in range(3) for s in range(card[v]))
    # resume: every stage again -> nothing relaunched (exactly one more START per stage runner), no RESUME_CONFLICT; the killed and launch-failed attempts stay reconciled
    led1 = open(os.path.join(D, "GB_LEDGER.jsonl")).read()
    for name, env in (("ok", None), ("kill", None), ("launch", None)):
        r = _stage(D, name, env); assert "RESUME_CONFLICT" not in r.stdout and "STOP:" not in r.stdout, r.stdout[-600:]
    led2 = open(os.path.join(D, "GB_LEDGER.jsonl")).read(); assert led2.count('"kind": "START"') == led1.count('"kind": "START"') + 3
    # accounting: every START reconciled; killed / failed attempts charged once; closeout budget compliance
    total, by, unresolved, extra = PI.charged(D); assert not unresolved and not extra["duplicate_receipts"]; B = R.budget(D, man, list(rws.values())); assert B["compliance"].startswith("every start")
    # a foreign interpreter on a NON-failed attempt is not accepted; a mismatched memory cap / timeout in START is not accepted
    idx = RC.ledger_index(D); c = man["cells"][0]; job = RC.job_name(c)
    bad = copy.deepcopy(idx); bad[job]["START"][0]["cmd"][0] = "/other/python"; r = RC.reconcile(D, man, c, bad); assert not r["accepted"] and any("interpreter" in x for x in r["reasons"])
    bad = copy.deepcopy(idx); bad[job]["START"][0]["mem_cap_gib"] = 1.0; r = RC.reconcile(D, man, c, bad); assert not r["accepted"] and any("supervision parameters" in x for x in r["reasons"])
    # a killed cell whose directory holds a forged cell.json claiming success is NOT accepted (receipt outcome MEMORY_KILL contradicts it)
    kc = man["cells"][6]; cj = os.path.join(D, kc["out_dir"], "cell.json"); good = json.load(open(cj)); forged = dict(json.load(open(os.path.join(D, man["cells"][0]["out_dir"], "cell.json")))); forged["expected_task"] = good["expected_task"]
    json.dump(forged, open(cj, "w")); r = RC.reconcile(D, man, kc, idx); json.dump(good, open(cj, "w")); assert not r["accepted"] and r["status"] == "NOT_ACCEPTED", r["reasons"][:4]


# ============================================================================================================ RD  one whole-path cost, sparse reverse, honest counters (review D)
def _forced_fusion(self, plan, bpe, caps):
    merged = set()
    for b in list(plan.buckets):
        p = b.consumer
        if p is not None and b in p.children and p.consumer is not None:
            before = PL._whole_path_cost(self, plan, bpe, caps); self._merge(b, p, plan); after = PL._whole_path_cost(self, plan, bpe, caps)
            plan.fusion_decisions.append({"child": b.bid, "consumer": p.bid, "cost_unfused": before["cold_work_proxy"], "cost_fused": after["cold_work_proxy"], "merged": True, "forced": True}); plan.mechanisms["fusion"]["merged"] += 1; merged.add(p)
    return merged


def _biased_totals(orig):
    def t(B, plan, bpe):
        r = orig(B, plan, bpe)
        return dict(r, cold_work_proxy_true=r["cold_work_proxy"], cold_work_proxy=0) if any(b.fused_from for b in plan.buckets) else r
    return t


@pytest.mark.parametrize("n", [3, 10, 25])
def test_RD1_fusion_regression_one_whole_path_cost_decides_and_ranks_and_the_forced_merge_is_dearer_in_prediction_and_in_counted_work(tmp_path, n, monkeypatch):
    f = [1 + (i % 17) for i in range(n * n)]; g = [(1 + a if a == b else 0) for a in range(n) for b in range(n)]; h = [1 + b for b in range(n)]
    NA = [sum(Fr(f[a * n + b] * (1 + b) * h[b]) for b in range(n)) for a in range(n)]; NB = [sum(Fr(f[a * n + b] * (1 + b) * h[b]) for a in range(n)) for b in range(n)]; Z = sum(NA); truth = {0: [x / Z for x in NA], 1: [x / Z for x in NB], 2: [x / Z for x in NB]}
    mp, ep = Q.write_uai(str(tmp_path / "d.uai"), [n, n, n], [((0, 1), f), ((1, 2), g), ((2,), h)])
    sw = dict(views=False, two_axis=False, orders=("original_id",), demand_masks=True)
    unf = Q._run_cfg(mp, ep, str(tmp_path / "u"), rules=[], b64=False, fusion=False, **sw); assert Q.exact_rows(unf, truth)
    mod = Q._run_cfg(mp, ep, str(tmp_path / "m"), rules=[], b64=False, fusion=True, **sw); assert Q.exact_rows(mod, truth)
    orig_fp, orig_t = PL.Builder.fusion_pass, PL.totals
    monkeypatch.setattr(PL.Builder, "fusion_pass", _forced_fusion); monkeypatch.setattr(PL, "totals", _biased_totals(orig_t))
    forced = Q._run_cfg(mp, ep, str(tmp_path / "f"), rules=[], b64=False, fusion=True, **sw); assert Q.exact_rows(forced, truth)
    monkeypatch.setattr(PL.Builder, "fusion_pass", orig_fp); monkeypatch.setattr(PL, "totals", orig_t)
    cu, cm, cf = work(Q.counters(unf)), work(Q.counters(mod)), work(Q.counters(forced)); pu, pm = unf["plan"]["totals"]["cold_work_proxy"], mod["plan"]["totals"]["cold_work_proxy"]; pf = forced["plan"]["totals"]["cold_work_proxy_true"]
    dec = [d for c in mod["plan_candidates"] if c.get("fusion_decisions") for d in c["fusion_decisions"]]
    # (1) the reviewer's merge (message bucket 0 into its consumer 1) is priced dearer by the ONE cost and DECLINED; its counted work IS dearer (the prediction orders the two plans correctly)
    d01 = [d for d in dec if d.get("child") == 0 and d.get("consumer") == 1][0]; assert d01["cost_fused"] > d01["cost_unfused"] and d01["merged"] is False
    assert pf > pu and cf > cu, (n, pf, pu, cf, cu)
    assert Q.counters(forced)["entries_materialized"] < Q.counters(unf)["entries_materialized"]                 # the forced merge DOES save materialization (the reviewer's observation) -- and is still dearer overall
    # (2) the model's own choice is never dearer than the unfused plan, in prediction AND in counted work; both candidates are recorded with the same totals the ranking used
    assert pm <= pu and cm <= cu, (n, pm, pu, cm, cu)
    cands = [(c.get("variant"), c.get("state"), c["totals"]["cold_work_proxy"]) for c in mod["plan_candidates"] if c.get("state") == "COMPLETE"]
    if mod["mechanisms"]["fusion"]["merged"]:
        assert {v for v, _, _ in cands} == {"fused", "unfused"} and [c for c in mod["plan_candidates"] if c.get("chosen")][0]["variant"] == "fused" and min(x for _, _, x in cands) == pm
        fin = [d for d in dec if d.get("final")][0]; assert fin["fused_is_cheaper"] and fin["cost_fused_after_rediscovery"] == pm and fin["cost_unfused"] == pu
    fc = [(c.get("variant"), c["totals"].get("cold_work_proxy_true", c["totals"]["cold_work_proxy"])) for c in forced["plan_candidates"] if c.get("state") == "COMPLETE"]; assert dict(fc)["unfused"] == pu and dict(fc)["fused"] == pf   # both candidates recorded under the forced merge too
    # (3) counters are honest: forward eliminated tuples (reduce_terms) and reverse visits (reverse_tuples / sparse_reverse_rows) are reported separately and both bounded by the predicted visited rows
    for rec in (unf, mod, forced):
        cc = Q.counters(rec); pred = rec["plan"]["totals"]["predicted"]
        assert cc["reduce_terms"] == pred["forward_rows"] and cc["reverse_tuples"] + cc["sparse_reverse_rows"] <= pred["forward_rows"] and cc["sparse_reverse_generic"] == 0, (cc, pred)


def test_RD2_sparse_support_indexed_reverse_14_binary_axes_ternary_multi_axis_and_default_policy(tmp_path):
    for n, extra in ((6, False), (14, False), (14, True)):
        K = 1 << n; tab = [0] * K; tab[0] = 3; tab[K - 1] = 5; facs = [(tuple(range(n)), tab)] + ([((i,), [1, 2]) for i in range(n)] if extra else [])
        mp, ep = Q.write_uai(str(tmp_path / ("s%d%d.uai" % (n, extra))), [2] * n, facs); S, Z, N, rows = Q.truth(mp, ep)
        for label, hooks in (("default_policy", None), ("forced_sparse", {"mutate_program": Q.set_storage(IR.SPARSE)})):
            rec = Q.run("GENERAL_BIDI_COMPLETE_V3", mp, ep, str(tmp_path / ("%d%d%s" % (n, extra, label))), rules=[], b64=False, hooks=hooks); a = rec["attempts"][-1]; fw = a["counters_after_forward"]; cc = a["counters"]
            assert rec["status"] == "INTERVALS_OK" and Q.exact_rows(rec, rows), (n, label, rec.get("reason"))
            sp = [x for x in rec["plan"]["node_table"] if x["kind"] == "REDUCE" and x["storage"] == IR.SPARSE]; assert sp, (n, label, "the production policy chose SPARSE" if label == "default_policy" else "forced")
            assert fw["sparse_rows_joined"] == 2 and fw["sparse_output_rows"] == 1 and fw["reduce_terms"] == 2                                       # forward: exactly the two supported rows joined
            assert cc["sparse_reverse_rows"] == 2 and cc["reverse_tuples"] == 0 and cc["sparse_reverse_generic"] == 0                                 # reverse: support-indexed deliveries to exactly the two retained rows; NO generic tuple enumeration
            assert cc["source_reads"] - fw["source_reads"] <= 2 * (1 + (n if extra else 0)) and cc["pullback_frames"] - fw["pullback_frames"] <= 2 * (2 + (n if extra else 0)), (n, extra, cc["source_reads"] - fw["source_reads"], cc["pullback_frames"] - fw["pullback_frames"])   # reverse reads bounded by the retained rows, not by 2^n
            assert cc["reduce_terms"] == fw["reduce_terms"]                                                                                           # reduce_terms is FORWARD only (never grows in reverse)
    # ternary, five axes, three supported rows + a unary consumer (nonbinary multi-axis sparse join + reverse)
    card = [3] * 5; tab = [0] * 243; tab[0] = 1; tab[121] = 2; tab[242] = 4; mp, ep = Q.write_uai(str(tmp_path / "t.uai"), card, [((0, 1, 2, 3, 4), tab), ((0,), [1, 2, 3])]); S, Z, N, rows = Q.truth(mp, ep)
    rec = Q.run("GENERAL_BIDI_COMPLETE_V3", mp, ep, str(tmp_path / "tern"), rules=[], b64=False); cc = Q.counters(rec); fw = rec["attempts"][-1]["counters_after_forward"]
    assert Q.exact_rows(rec, rows) and fw["sparse_rows_joined"] == 3 and cc["sparse_reverse_rows"] == 3 and cc["reverse_tuples"] == 0 and cc["source_reads"] - fw["source_reads"] <= 6
    # the unchanged-method witness value: a generic reverse over 2^14 tuples would have read 16,384 source entries; the repaired path reads 2
    assert EX.COUNTER_DEFINITIONS["reduce_terms"].startswith("FORWARD") and EX.COUNTER_DEFINITIONS["reverse_tuples"].startswith("REVERSE") and "sparse_reverse_rows" in EX.COUNTER_DEFINITIONS and "sparse_reverse_generic" in EX.COUNTER_DEFINITIONS


def test_RD3_predicted_versus_counted_work_on_materialized_sparse_streamed_conditioned_and_regenerated_paths(tmp_path):
    def check(rec, rows, label):
        a = rec["attempts"][-1]; fw = a["counters_after_forward"]; cc = a["counters"]; pred = rec["plan"]["totals"]["predicted"]
        assert Q.exact_rows(rec, rows) or Q.tight(rec, rows), label
        assert fw["reduce_terms"] == pred["forward_rows"], (label, fw["reduce_terms"], pred)                                                        # forward eliminated tuples == predicted visited rows (exact, not a bound)
        assert fw["entries_materialized"] <= pred["dense_entries"] and fw["sparse_output_rows"] == pred["sparse_rows"] and fw["sparse_rows_joined"] == pred["sparse_joined"], (label, fw, pred)
        assert cc["reverse_tuples"] + cc["sparse_reverse_rows"] <= pred["forward_rows"], (label, cc, pred)                                           # reverse visits never exceed the forward rows
        return fw, cc, pred
    card = [3, 3, 3, 3]; facs = Q.rnd_model(22, card, [(0, 1), (1, 2), (2, 3), (0, 3)]); mp, ep = Q.write_uai(str(tmp_path / "m.uai"), card, facs); S, Z, N, rows = Q.truth(mp, ep)
    fw, cc, pred = check(Q.run("GENERAL_BIDI_COMPLETE_V3", mp, ep, str(tmp_path / "d"), rules=[], b64=False), rows, "materialized"); assert pred["dense_entries"] >= 10 and fw["entries_materialized"] == pred["dense_entries"]
    fw, cc, pred = check(Q.run("GENERAL_BIDI_COMPLETE_V3", mp, ep, str(tmp_path / "v"), rules=[], b64=False, ledger=GM.Ledger(dict(GM.CAPS, value_cache_blocks=1))), rows, "streamed+regenerated (value cap)")
    assert pred["stream_rows"] > 0 and cc["downgrades"] >= 1                                                                                          # the planner streamed under the cap; the kernel downgraded the remaining dense root
    mp2, ep2 = Q._c16_model(str(tmp_path / "c16.uai"), 3); S2, Z2, N2, rows2 = Q.truth(mp2, ep2)
    fw, cc, pred = check(Q.run("GENERAL_BIDI_COMPLETE_V3", mp2, ep2, str(tmp_path / "c"), rules=[], b64=False), rows2, "conditioned (two-axis)")
    n = 3; f = [1 + (i % 17) for i in range(9)]; g = [(1 + a if a == b else 0) for a in range(3) for b in range(3)]; mp3, ep3 = Q.write_uai(str(tmp_path / "sp.uai"), [3, 3, 3], [((0, 1), f), ((1, 2), g), ((2,), [1, 2, 3])]); S3, Z3, N3, rows3 = Q.truth(mp3, ep3)
    fw, cc, pred = check(Q._run_cfg(mp3, ep3, str(tmp_path / "s"), rules=[], b64=False, views=False, two_axis=False, fusion=False, orders=("original_id",)), rows3, "sparse"); assert pred["sparse_rows"] == 3 and cc["sparse_reverse_rows"] == 3
    # the proxy is a consistent conservative proxy of counted work (not seconds): predicted cold work >= counted primitive work on every path above is NOT required; the ORDERING of alternatives is (RD1)
    assert EX.COUNTER_DEFINITIONS["units"].startswith("exact event counts")


# ============================================================================================================ RE  reserve before building, poll actual work (review E)
def _big_model(path, n=50000):
    open(path, "w").write("MARKOV\n1\n2\n%d\n%s\n%s" % (n // 2, "\n".join(["1 0"] * (n // 2)), "\n".join(["2 1/3 2/3"] * (n // 2)) + "\n")); open(path + ".evid", "w").write(""); return path, path + ".evid"


def test_RE1_one_byte_cap_and_expired_deadline_stop_before_one_rational_is_parsed(tmp_path, monkeypatch):
    mp, ep = _big_model(str(tmp_path / "big.uai")); calls = [0]; orig = GS.Fr
    def counted(*a, **kw):
        calls[0] += 1; return orig(*a, **kw)
    monkeypatch.setattr(GS, "Fr", counted)
    for label, caps, deadline in (("one_byte_source_cap", dict(GM.CAPS, source_ir_maps_output=1), time.monotonic() + 30), ("expired_deadline", dict(GM.CAPS), time.monotonic() - 10)):
        calls[0] = 0; tracemalloc.start(); led = GM.Ledger(caps)
        with pytest.raises(EX.Refuse) as ex:
            EX.execute("GENERAL_BIDI_COMPLETE_V3", mp, ep, str(tmp_path / label), deadline, {"budget_s": 20}, ledger=led)
        _, peak = tracemalloc.get_traced_memory(); tracemalloc.stop()
        assert ex.value.kind == "RESOURCE_STOP" and calls[0] == 0 and peak < 100_000, (label, ex.value.reason, calls[0], peak)                      # NOTHING read or parsed: no byte buffer, no token list, no rational (the model file alone is 100 KB)
        assert ("raw caller bytes" in ex.value.reason) if label == "one_byte_source_cap" else ("DEADLINE" in ex.value.reason and "0 tokens" in ex.value.reason)
    # the cell's own snapshot is under the same guard (ParseStop -> typed RESOURCE_STOP record)
    env = dict(ENV, GBIDI_LAUNCH_MONO="%.6f" % (time.monotonic() - 100)); out = str(tmp_path / "cell"); subprocess.run([PY, "-m", "gbidi3.cell", "GENERAL_BIDI_COMPLETE_V3", mp, ep, out, "20", "{}"], capture_output=True, cwd=HERE, env=env, timeout=120)
    c = json.load(open(os.path.join(out, "cell.json"))); assert c["status"] == "RESOURCE_STOP" and c["stop"]["phase"] == "snapshot" and c["stop"]["kind"] == "DEADLINE", c.get("reason")
    # the caps at EVERY later construction phase stop with a typed category stop (the earlier phases completed under the same ledger)
    small = Q.write_uai(str(tmp_path / "s.uai"), [3, 3, 3], Q.rnd_model(5, [3, 3, 3], [(0, 1), (1, 2)])); S = GS.Snapshot(*small); base = GM.model_bytes_estimate(S.model, len(S.model_bytes) + len(S.evid_bytes))
    phases = []
    S2 = GS.Snapshot(small[0], small[1], ledger=GM.Ledger()); parsed = S2.ledger_charged
    for cap in (parsed + 1000, parsed + 1500, parsed + 3000, parsed + 8000, parsed + 20000, parsed + 60000, parsed + 200000):
        led = GM.Ledger(dict(GM.CAPS, source_ir_maps_output=cap))
        try:
            EX.execute("GENERAL_BIDI_COMPLETE_V3", small[0], small[1], str(tmp_path / ("cap%d" % cap)), time.monotonic() + 30, {"budget_s": 20, "allow_binary64": False}, ledger=led); phases.append("COMPLETE")
        except EX.Refuse as ex:
            assert ex.kind == "RESOURCE_STOP" and "MEMORY_CATEGORY" in ex.reason, ex.reason; phases.append(" ".join(w for w in ("replay", "trusted", "reduced", "planner", "planning", "validated", "flat", "candidates", "snapshot", "demand") if w in ex.reason))
    assert phases[0] != "COMPLETE" and phases[-1] == "COMPLETE" and len(set(phases)) >= 4, phases                                                  # distinct construction phases refuse at distinct caps (reductions / trusted / replay / planning / validation / flatten), each BEFORE building


def test_RE2_fallback_preparation_under_a_one_byte_cap_and_the_200x200_discovery_witness(tmp_path):
    mp, ep = _big_model(str(tmp_path / "big.uai")); S = GS.Snapshot(mp, ep); led = GM.Ledger(dict(GM.CAPS, frames_scratch_pub=1)); tracemalloc.start()
    fb = EX.exact_fallback(S, time.monotonic() + 30, led); _, peak = tracemalloc.get_traced_memory(); tracemalloc.stop()
    assert fb["status"] == "MEMORY" and fb["phase"] == "preparation" and fb["allocated_before_stop"] == 0 and peak < 50_000, (fb, peak)             # stopped BEFORE slicing / converting one table
    fb = EX.exact_fallback(S, time.monotonic() - 1, GM.Ledger()); assert fb["status"] == "DEADLINE" and fb["phase"] == "preparation"
    nn = 200; view = {"dom": {0: tuple(range(nn)), 1: tuple(range(nn))}, "factors": [(0, (0, 1), (nn, nn), tuple(Fr(1 + (i % 17)) for i in range(nn * nn)))], "scale": Fr(1)}
    clock = Clock(time.monotonic() + 5, 20); clock.optional_allowance_s = 0.001; b = PL.Builder(view, PL.ARMS["GENERAL_BIDI_COMPLETE_V3"], clock); pl = PL.Plan("original_id", [0, 1]); pl.roots = b.build([0, 1], pl); t = time.monotonic()
    with pytest.raises(PlanStop) as ex:
        b.views_pass(pl)
    el = time.monotonic() - t; assert ex.value.kind == "DISCOVERY_WALL" and clock.rows == nn * nn and el < 0.5, (ex.value.kind, clock.rows, el)        # ONE strided traversal (40,000 rows, not 200 x 40,000), the optional wall fires, the hard deadline is untouched
    assert all(not bk.views for bk in pl.buckets) and all(bk.demand == "FULL" for bk in pl.buckets)                                                  # conservative identity / FULL semantics after the stop


def test_RE3_native_wide_add_polls_within_one_quantum_and_a_sparse_downgrade_releases_its_capacity(tmp_path):
    cpp = tmp_path / "probe.cpp"; exe = tmp_path / "probe"
    cpp.write_text('#include "%s/gbidi3/kernel3.cpp"\n#include <cstdio>\nint main() {\n' % HERE +
                   '  { Exec<Dbl> e(53); e.caps={1ULL<<30,1ULL<<30,1ULL<<30,1ULL<<30,1ULL<<30}; e.deadline=now_mono()-1; e.F.resize(1); e.F[0].entries=1; e.F[0].val_off=0; e.fvals.resize(1); Dbl::init(e.fvals[0],53); e.fvals[0].v=1; e.fvals[0].e=0;\n'
                   '    e.N.resize(2); auto& leaf=e.N[0]; leaf.kind=K_SOURCE; leaf.storage=S_STREAM; leaf.fid=0; leaf.volume=1; auto& add=e.N[1]; add.kind=K_ADD; add.storage=S_STREAM; add.volume=1; add.children.assign(50000,0);\n'
                   '    Dbl::T out; Dbl::init(out,53); bool ok=e.value(1,0,out); std::printf("{\\"ok\\":%s,\\"adds\\":%llu,\\"source_reads\\":%llu,\\"polls\\":%llu,\\"stop\\":%d,", ok?"true":"false",(unsigned long long)e.C.adds,(unsigned long long)e.C.source_reads,(unsigned long long)e.C.polls,e.stop); }\n'
                   '  { Exec<Dbl> e(53); e.N.resize(1); e.N[0].storage=S_SPARSE; e.sparse_vals.resize(1); e.sparse_idx.resize(1); e.sparse_complete.resize(1); e.dpos.resize(1); e.dense.resize(1); e.dense_done.resize(1); e.sparse_in_off.resize(1); e.sparse_in_idx.resize(1); e.sparse_reverse_ready.resize(1); e.sparse_cap_values.resize(1); e.sparse_cap_index.resize(1);\n'
                   '    for(int i=0;i<10000;++i){ e.sparse_vals[0].push_back({1,0}); e.sparse_idx[0].push_back(i); e.dpos[0][i]=i; e.sparse_in_idx[0].push_back(i); e.sparse_in_off[0].push_back(i); }\n'
                   '    e.used_values=10000*(Dbl::bytes(53)+sizeof(int64_t)); e.used_index=10000*48; e.sparse_cap_values[0]=e.used_values; e.sparse_cap_index[0]=e.used_index; e.sparse_complete[0]=1; e.sparse_reverse_ready[0]=1; uint64_t before=e.used_values; e.downgrade_to_stream(0);\n'
                   '    std::printf("\\"before\\":%llu,\\"used_values_after\\":%llu,\\"used_index_after\\":%llu,\\"cap_values\\":%llu,\\"cap_index\\":%llu,\\"cap_in_idx\\":%llu,\\"buckets\\":%llu}\\n",(unsigned long long)before,(unsigned long long)e.used_values,(unsigned long long)e.used_index,(unsigned long long)(e.sparse_vals[0].capacity()*sizeof(Dbl::T)),(unsigned long long)(e.sparse_idx[0].capacity()*8),(unsigned long long)(e.sparse_in_idx[0].capacity()*8),(unsigned long long)e.dpos[0].bucket_count()); }\n'
                   '  return 0; }\n')
    rb = subprocess.run(["clang++", "-std=c++17", "-O2", "-ffp-model=strict", "-ffp-contract=off", "-I/opt/homebrew/include", "-L/opt/homebrew/lib", "-o", str(exe), str(cpp), "-lmpfr", "-lgmp"], capture_output=True, text=True, timeout=300); assert rb.returncode == 0, rb.stderr[-1500:]
    r = json.loads(subprocess.run([str(exe)], capture_output=True, text=True, timeout=60).stdout)
    assert r["ok"] is False and r["stop"] == 1 and r["polls"] == 1 and r["adds"] + r["source_reads"] <= 2 * 4096, r                               # the 50,000-operand ADD polls inside its loop: the expired deadline stops it within one quantum
    assert r["before"] > 0 and r["used_values_after"] == 0 and r["used_index_after"] == 0 and r["cap_values"] == 0 and r["cap_index"] == 0 and r["cap_in_idx"] == 0 and r["buckets"] <= 1, r   # the downgrade ACTUALLY frees the backing storage (capacity 0) and releases exactly the charge


def test_RE4_capacity_accounting_integration_materialize_then_downgrade_under_a_tight_value_cap(tmp_path):
    n = 10; K = 1 << n; tab = [0] * K; tab[0] = 3; tab[K - 1] = 5; mp, ep = Q.write_uai(str(tmp_path / "s.uai"), [2] * n, [(tuple(range(n)), tab), ((0,), [1, 2])]); S, Z, N, rows = Q.truth(mp, ep)
    full = Q.run("GENERAL_BIDI_COMPLETE_V3", mp, ep, str(tmp_path / "full"), rules=[], b64=False); cf = Q.counters(full); assert Q.exact_rows(full, rows) and cf["sparse_output_rows"] >= 1 and cf["used_index_bytes"] > 0 and cf["downgrades"] == 0
    # the join's temporaries (driver rows, digit buffers, bucket lists, hash buckets, CSR) are charged to the index category: a cap just below what the join needs forces a labelled downgrade (join DISCARDED, node streamed); the final charge after the downgrade is the released value
    host = full["memory_ledger"]["used"]["source_ir_maps_output"]                                                                                 # the Python side's deterministic reservations before the kernel handoff
    for cap in (1, 64, cf["used_index_bytes"] // 2):
        led = GM.Ledger(dict(GM.CAPS, source_ir_maps_output=host + cap)); rec = Q.run("GENERAL_BIDI_COMPLETE_V3", mp, ep, str(tmp_path / ("cap%d" % cap)), rules=[], b64=False, ledger=led); c = Q.counters(rec)
        assert Q.exact_rows(rec, rows) and (c.get("downgrades", 0) >= 1 and c.get("sparse_join_discarded", 0) >= 1 and c.get("sparse_output_rows") == 0 or rec.get("route") == "exact_fallback"), (cap, c.get("downgrades"), c.get("sparse_join_discarded"), rec.get("route"), rec.get("stop"))
        if c.get("downgrades"):
            assert c["used_index_bytes"] <= 1 and c["used_values_bytes"] <= 1, c                                                                     # nothing retained after the downgrade: the charge is released with the storage


# ============================================================================================================ RF  individual qualification with actual production planning (review F)
def _tri(seed, card=(3, 3, 3, 2, 3)):
    rr = random.Random(seed)
    def tab(n, zp):
        return [Fr(0) if rr.random() < zp else Fr(rr.randint(1, 9)) for _ in range(n)]
    return list(card), [((0, 1), tab(9, 0.4)), ((1, 2), tab(9, 0.4)), ((0, 2), tab(9, 0.3)), ((2, 3), tab(6, 0.0)), ((3, 4), tab(6, 0.3))]


def _run_arms(tmp_path, name, card, facs, arms):
    mp, ep = Q.write_uai(str(tmp_path / (name + ".uai")), card, facs); S, Z, N, rows = Q.truth(mp, ep); out = {}
    for arm in arms:
        rec = Q.run(arm, mp, ep, str(tmp_path / (name + "_" + arm)), rules=[], b64=False); assert Q.contained(rec, rows) and (Q.exact_rows(rec, rows) or Q.tight(rec, rows)), (name, arm, rec.get("reason")); out[arm] = (rec, Q.counters(rec))
    return out


def test_RF1_nonbipartite_production_planning_demand_restriction_activates_and_saves_work_and_residency_versus_A1(tmp_path):
    card, facs = _tri(102); r = _run_arms(tmp_path, "tri_demand", card, facs, ("GENERAL_BIDI_COMPLETE_V3", "A1_NO_DEMAND_MASKS"))
    g, cg = r["GENERAL_BIDI_COMPLETE_V3"]; a, ca = r["A1_NO_DEMAND_MASKS"]
    assert g["mechanisms"]["demand"]["restricted_nodes"] >= 1 and g["mechanisms"]["demand"]["entries_saved"] >= 1 and a["mechanisms"]["demand"]["restricted_nodes"] == 0
    assert sum(1 for n in g["plan"]["node_table"] if n["demand"] not in ("FULL", "EMPTY")) >= 1                                                      # the restriction is in the EXECUTED validated program
    assert (g["mechanisms"]["fusion"], g["mechanisms"]["two_axis"], g["mechanisms"]["sparse"]) == (a["mechanisms"]["fusion"], a["mechanisms"]["two_axis"], a["mechanisms"]["sparse"])   # the only planning difference is the demand switch
    assert work(cg) < work(ca) and cg["entries_materialized"] < ca["entries_materialized"] and cg["reads_outside_demand"] == 0, (work(cg), work(ca), cg["entries_materialized"], ca["entries_materialized"])
    # higher arity / nonbinary, zeros, no-op and capped cases keep exact truth with the mechanism's accounting present
    card2 = [3, 3, 3, 2]; facs2 = Q.rnd_model(31, card2, [(0, 1, 2), (1, 2, 3), (0, 3), (0, 2)], zeros=0.15); r2 = _run_arms(tmp_path, "tern_cycles", card2, facs2, ("GENERAL_BIDI_COMPLETE_V3", "A1_NO_DEMAND_MASKS"))
    g2 = r2["GENERAL_BIDI_COMPLETE_V3"][0]; assert "restricted_nodes" in g2["mechanisms"]["demand"] and g2["mechanisms"]["demand"]["skipped"] >= 0


def test_RF2_nonbipartite_production_planning_response_views_activate_and_save_work_versus_A3(tmp_path):
    rr = random.Random(200); base = [rr.randint(1, 9) for _ in range(3)]; g = []
    for b in range(4):
        g += [(1, 1, 2, 3)[b] * x for x in base] if b != 3 else [rr.randint(1, 9) for _ in range(3)]
    card = [3, 4, 3]; facs = [((1, 0), g), ((1, 2), [rr.randint(1, 9) for _ in range(12)]), ((0, 2), [rr.randint(1, 9) for _ in range(9)])]      # odd cycle; factor (1,0) has proportional rows along axis 1 for states 0,1,2
    r = _run_arms(tmp_path, "tri_views", card, facs, ("GENERAL_BIDI_COMPLETE_V3", "A3_NO_RESPONSE_VIEWS")); gen, cg = r["GENERAL_BIDI_COMPLETE_V3"]; a3, ca = r["A3_NO_RESPONSE_VIEWS"]
    assert gen["mechanisms"]["views"]["compressed_axes"] >= 1 and gen["plan_validation"]["entrywise_checks"] > 0 and a3["mechanisms"]["views"]["compressed_axes"] == 0
    assert any(n["kind"] == "GATHER" for n in gen["plan"]["node_table"]) and not any(n["kind"] == "GATHER" for n in a3["plan"]["node_table"])          # the compressed message is expanded by a GATHER in the EXECUTED program
    assert work(cg) < work(ca) and cg["entries_materialized"] < ca["entries_materialized"], (work(cg), work(ca))
    # expanding / no-op: a factor without proportional rows -> no class formed, the no-op is recorded, truth exact
    card3 = [3, 3, 3]; facs3 = [((0, 1), [1, 2, 3, 4, 5, 7, 8, 9, 11]), ((1, 2), [1, 3, 2, 4, 6, 5, 7, 9, 8]), ((0, 2), [2, 3, 5, 7, 11, 13, 17, 19, 23])]
    r3 = _run_arms(tmp_path, "noop_views", card3, facs3, ("GENERAL_BIDI_COMPLETE_V3",)); g3 = r3["GENERAL_BIDI_COMPLETE_V3"][0]; assert g3["mechanisms"]["views"]["compressed_axes"] == 0


def test_RF3_nonbipartite_production_planning_fusion_activates_by_the_one_cost_and_saves_work_versus_A2(tmp_path):
    card, facs = _tri(104); r = _run_arms(tmp_path, "tri_fusion", card, facs, ("GENERAL_BIDI_COMPLETE_V3", "A2_NO_FUSION")); gen, cg = r["GENERAL_BIDI_COMPLETE_V3"]; a2, ca = r["A2_NO_FUSION"]
    assert gen["mechanisms"]["fusion"]["merged"] >= 1 and a2["mechanisms"]["fusion"]["merged"] == 0
    ch = [c for c in gen["plan_candidates"] if c.get("chosen")][0]; assert ch["variant"] == "fused" and any(c.get("variant") == "unfused" for c in gen["plan_candidates"])            # the unfused complete plan was retained and lost the ranking
    assert any(n["kind"] == "REDUCE" and n.get("prov", {}).get("fused_from") for n in gen["plan"]["node_table"])                                     # the merged node is in the EXECUTED program
    assert gen["plan"]["totals"]["cold_work_proxy"] < a2["plan"]["totals"]["cold_work_proxy"] and work(cg) < work(ca) and cg["entries_materialized"] < ca["entries_materialized"], (work(cg), work(ca))
    # the price can also DECLINE on a nonbipartite model (every candidate recorded with both costs)
    card2, facs2 = _tri(101); r2 = _run_arms(tmp_path, "tri_decline", card2, facs2, ("GENERAL_BIDI_COMPLETE_V3",)); g2 = r2["GENERAL_BIDI_COMPLETE_V3"][0]
    dec = [d for c in g2["plan_candidates"] if c.get("fusion_decisions") for d in c["fusion_decisions"] if "child" in d]; assert dec and all({"cost_unfused", "cost_fused", "merged"} <= set(d) for d in dec)


def test_RF4_one_axis_versus_two_axis_cutsets_are_actually_executed(tmp_path):
    for dcard in (2, 3, 5):
        mp, ep = Q._c16_model(str(tmp_path / ("c16_%d.uai" % dcard)), dcard); S, Z, N, rows = Q.truth(mp, ep)
        two = Q._run_cfg(mp, ep, str(tmp_path / ("two%d" % dcard)), rules=[], b64=False, two_axis=True, fusion=False); one = Q._run_cfg(mp, ep, str(tmp_path / ("one%d" % dcard)), rules=[], b64=False, two_axis=False, fusion=False)   # fusion off: the cutset policy alone shapes the region tree
        dflt = Q.run("GENERAL_BIDI_COMPLETE_V3", mp, ep, str(tmp_path / ("dflt%d" % dcard)), rules=[], b64=False); assert Q.exact_rows(two, rows) and Q.exact_rows(one, rows) and Q.exact_rows(dflt, rows)
        def two_axis_nodes(rec):
            nt = rec["plan"]["node_table"]
            return [n for n in nt if n["kind"] == "REDUCE" and n.get("prov", {}).get("two_axis") is True and len(nt[n["children"][0]]["axes"]) - len(n["axes"]) == 2]
        assert two["mechanisms"]["two_axis"]["chosen"] >= 1 and len(two_axis_nodes(two)) == two["mechanisms"]["two_axis"]["chosen"] and not two_axis_nodes(one) and one["mechanisms"]["two_axis"] == {"chosen": 0, "declined": 0, "ineligible": 0}
        assert all(n.get("prov", {}).get("cutset") == "TWO_AXIS_POLICY" for n in two_axis_nodes(two)) and all(n.get("prov", {}).get("cutset") == "ONE_AXIS" for n in one["plan"]["node_table"] if n["kind"] == "REDUCE" and n.get("prov", {}).get("cutset"))
        assert len([n for n in two["plan"]["node_table"] if n["kind"] == "REDUCE"]) == len([n for n in one["plan"]["node_table"] if n["kind"] == "REDUCE"]) - two["mechanisms"]["two_axis"]["chosen"]   # each two-axis region replaces exactly two one-axis buckets
        assert Q.counters(two)["reduce_terms"] == two["plan"]["totals"]["predicted"]["forward_rows"] and Q.counters(one)["reduce_terms"] == one["plan"]["totals"]["predicted"]["forward_rows"]
    # the conditioning-order policy is global and documented: reversed elimination order (the last eliminated variable is the outermost cutset)
    assert "REVERSE of the elimination order" in PL.Builder.build.__doc__


def test_RF5_all_consumer_demand_compilation_covers_every_use_of_a_shared_module(tmp_path):
    # w(X) (card 3) shared by two additive consumers h1 = (1,0,0) and h2 = (0,0,1): consumer 1 reads X=0 only, consumer 2 reads X=2 only; the UNION {0,2} is the demand; X=1 is read by nobody
    mp, ep = Q.write_uai(str(tmp_path / "sh.uai"), [3], [((0,), [1, 2, 3]), ((0,), [1, 0, 1])]); S, Z, N, rows = Q.truth(mp, ep); assert Z == 4
    def build(T):
        fw = [f for f in T.factors if f.table == (Fr(1), Fr(2), Fr(3))][0]; fh = [f for f in T.factors if f.table == (Fr(1), Fr(0), Fr(1))][0]
        P = IR.Program(); P.derived = {101: {"kind": "additive_split", "parent": fh.fid, "parts": [(1, 0, 0), (0, 0, 1)], "index": 0}, 102: {"kind": "additive_split", "parent": fh.fid, "parts": [(1, 0, 0), (0, 0, 1)], "index": 1}}
        w = P.source(fw.fid, fw.scope, fw.card); mk = P.marker(0, 3); shared = P.mul([w, mk]); shared.storage = IR.DENSE
        h1 = P.source(101, fh.scope, fh.card); h2 = P.source(102, fh.scope, fh.card); c1 = P.mul([shared, h1]); c2 = P.mul([shared, h2]); add = P.addn([c1, c2]); root = P.reduce(add, {0}); root.storage = IR.DENSE; P.roots = [root.nid]; return P
    def mut(P):
        S_, R_, T_, plan, cands = Q.plan_program(mp, ep); P2 = build(T_); P.nodes = P2.nodes; P.roots = P2.roots; P.derived = P2.derived
    rec = Q.run("GENERAL_BIDI_COMPLETE_V3", mp, ep, str(tmp_path / "sh"), rules=[], b64=False, hooks={"mutate_program": mut}); cc = Q.counters(rec)
    assert Q.exact_rows(rec, rows) and rec["demand_all_consumers"]["shared_nodes"] and rec["demand_all_consumers"]["restricted"] and rec["demand_all_consumers"]["entries_saved"] == 1
    sh = [n for n in rec["plan"]["node_table"] if n["kind"] == "MUL" and n["storage"] == IR.DENSE and n["demand"] == 2]; assert sh and sh[0]["prov"]["demand"] == "RESTRICTED_ALL_CONSUMERS" and sh[0]["prov"]["consumers"] == 2
    assert cc["reads_outside_demand"] == 0 and cc["marker_updates"] >= 2                                                                              # every consumer's read is inside the compiled union: nothing streamed outside the hint
    # the compiler itself: the union of two consumers vs each alone (a single-consumer pointer would restrict to ONE entry and the other consumer would read outside)
    S_, R_, T, plan, _ = Q.plan_program(mp, ep); P = build(T); r = DM.compile_demand(P, tables={f.fid: f.table for f in T.factors}); shared = [n for n in P.nodes if n.kind == IR.MUL and len(n.children) == 2 and P.nodes[n.children[1]].kind == IR.MARKER][0]
    assert shared.demand == (0, 2) and r["consumers"][shared.nid] == 2 and r["entries_saved"] == 1
    V = GV.validate(P, T); assert V.record["status"] == "VALID" and jet_rows(V) == {0: list(rows[0])}
    # unanalyzable (GATHER with class maps onto a shared node) stays FULL: conservative
    P2 = build(T); P2.nodes[2].demand = "FULL"; r2 = DM.compile_demand(P2, row_cap=1); assert P2.nodes[2].demand == "FULL" and r2["skipped_cap"]


def test_RF6_fixture_seeds_are_deterministic_and_independent_of_the_hash_seed():
    r = subprocess.run([PY, "-c", "import sys; sys.path.insert(0, %r); import test_gbidi3_complete as Q; print([Q.fixture_seed(n) for n in sorted(Q.CASES)])" % os.path.join(HERE, "tests")], capture_output=True, text=True, env=dict(ENV, PYTHONHASHSEED="1"), cwd=HERE)
    r2 = subprocess.run([PY, "-c", "import sys; sys.path.insert(0, %r); import test_gbidi3_complete as Q; print([Q.fixture_seed(n) for n in sorted(Q.CASES)])" % os.path.join(HERE, "tests")], capture_output=True, text=True, env=dict(ENV, PYTHONHASHSEED="2"), cwd=HERE)
    assert r.returncode == 0 and r.stdout == r2.stdout and r.stdout.strip(), (r.stdout, r.stderr[-300:], r2.stdout)
    assert Q.fixture_seed("nonbinary_chain") == int(hashlib.sha256(b"nonbinary_chain").hexdigest()[:8], 16) % 1000
