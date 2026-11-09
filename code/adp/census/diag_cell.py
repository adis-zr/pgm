"""INSTRUMENTED full-arm cell for the census pass (observation only; same semantics and configuration as adp.cell).

    python -m adp.census.diag_cell MODEL.uai EVID.uai.evid OUT_DIR DEADLINE_S CONFIG.json

What is added, and only that:
  * the reduced-model record and the plan record are persisted IMMEDIATELY when available (before numerical execution), with derived
    per-node structural metrics (raw boundary-domain product, response-class product, bag rows, per-axis class counts per input and after
    intersection with the responsible input, single-input-elimination flag, disjoint-input-scope rank-1 volume);
  * per-node forward / backward observation at node boundaries (wall, counter deltas, resident bytes, format actually executed, sparse rows,
    referenced-child-entry counts = how many of a child's entries the parent actually looked up, computed by a boolean mask), persisted
    atomically every 0.5 s and at every node boundary (progress.json / nodes.jsonl), so a kill keeps the observed prefix;
  * the checker's own counters are taken from its record (its internals are NOT instrumented: per-node checker work is unavailable).
The numerical methods, caps, deadline, precision ladder, checker and publication are the unchanged repaired code (adp.engine / adp.checker /
adp.cell at the frozen-set hash). Instrumentation overhead is part of this cell's wall and is never subtracted."""
from __future__ import annotations
import os, sys, json, time, threading
T_START = time.monotonic()
sys.set_int_max_str_digits(0)
HERE = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))); sys.path.insert(0, HERE)
import numpy as np
from fractions import Fraction as Fr
from adp import source as SRC, engine as EN, cell as CELL
from mdi import arith as A


def now():
    return time.monotonic() - T_START


def atomic_write(path, data):
    tmp = path + ".tmp"
    with open(tmp, "w") as f:
        f.write(data); f.flush(); os.fsync(f.fileno())
    os.replace(tmp, path)


def node_metrics(P):
    """Structural per-node metrics from the plan (exact, cheap). Units: a class tuple = one core ENTRY; bag ROWS = entries x |D_x|."""
    out = []
    for nd in P.nodes:
        raw_boundary = 1
        for w in nd.scope:
            raw_boundary *= len(P.dom[w])
        axes = []
        for w in nd.scope:
            inc = [(list(ref), len(P.view_of(ref, w).reps)) for ref in nd.inputs if w in P.scope_of(ref)]
            k_out = len(nd.views[w].reps); finest = [r for r, k in inc if k == max(k for _, k in inc)] if inc else []
            axes.append({"w": w, "raw": len(P.dom[w]), "classes_per_input": inc, "classes_out": k_out, "finest_inputs": finest, "compressed": k_out < len(P.dom[w])})
        scopes = [tuple(u for u in P.scope_of(ref) if u != nd.v) for ref in nd.inputs]
        disjoint = all(not (set(a) & set(b)) for i, a in enumerate(scopes) for b in scopes[i + 1:])
        rank1_volume = len(P.dom[nd.v]) * sum(len(P.fac[ref[1]].table) if ref[0] == "F" else P.nodes[ref[1]].size for ref in nd.inputs) if disjoint and len(nd.inputs) > 1 else None
        single_input = len(nd.inputs) == 1
        out.append({"nid": nd.nid, "v": nd.v, "dom_v": len(P.dom[nd.v]), "parent": nd.parent, "comp": nd.comp, "inputs": [list(r) for r in nd.inputs], "input_scopes": [list(P.scope_of(ref)) for ref in nd.inputs], "scope": list(nd.scope),
                    "raw_boundary_domain_product": raw_boundary, "response_class_product": nd.size, "planned_core_entries": nd.size, "planned_bag_rows": nd.bag, "planned_format": nd.fmt, "axes": axes,
                    "single_input_elimination": single_input, "inputs_have_disjoint_boundary_scopes": disjoint, "rank1_terms_volume_if_disjoint": rank1_volume, "any_zero_input": P.any_zero(nd)})
    return out


class ObservedExecutor(EN.Executor):
    """Observation wrapper: identical arithmetic (every numeric method is inherited unchanged); records node-boundary events and the set of
    child entries each parent references."""

    def __init__(self, *a, obs=None, **k):
        super().__init__(*a, **k); self.obs = obs; self.cur = None; self.ref_masks = {}

    def snap(self, label):
        self.obs.snapshot(label, self)

    def _delta(self, before):
        return {k: self.c.get(k, 0) - before.get(k, 0) for k in set(self.c) | set(before) if self.c.get(k, 0) != before.get(k, 0)}

    def forward(self):
        import gmpy2
        gmpy2.set_context(self.D); self.rootvals = None
        for nd in self.P.nodes:
            self.tick(); t = time.monotonic(); before = dict(self.c); self.cur = ("forward", nd.nid); fmt_planned = nd.fmt
            if nd.fmt == "dense":
                self.forward_dense(nd)
            elif nd.fmt == "sparse":
                self.forward_sparse(nd)
            else:
                self.forward_lazy_node(nd)
            core = self.cores[nd.nid]; core.stats["forward_s"] = time.monotonic() - t
            refs = {}
            for ref in nd.inputs:
                if ref[0] == "M" and (nd.nid, ref[1]) in self.ref_masks:
                    m = self.ref_masks.pop((nd.nid, ref[1])); refs[str(ref[1])] = {"child_entries": int(m.size), "referenced": int(m.sum())}
            self.obs.node_event({"phase": "forward", "nid": nd.nid, "v": nd.v, "planned_format": fmt_planned, "executed_format": core.fmt, "wall_s": core.stats["forward_s"], "counters_delta": self._delta(before), "bytes_vals": self.bytes_vals, "bytes_adj": self.bytes_adj,
                                 "core_entries_stored": (len(core.vals) if core.vals is not None else (len(core.lazy) if core.lazy is not None else None)), "sparse_rows": core.stats.get("rows"), "sparse_out_rows": core.stats.get("out_rows"), "abandoned_sparse": core.stats.get("abandoned_sparse"), "referenced_child_entries": refs, "t_s": now()})
        self.rootvals = self.root_values(); self.cur = None

    def gather_inputs(self, nd, x_idx, c_keys, resolved=None):
        """Unchanged arithmetic; additionally marks which entries of each child core this node's bag rows reference (boolean mask, O(rows))."""
        out = super().gather_inputs(nd, x_idx, c_keys, resolved)
        if self.cur is not None and self.cur[0] == "forward" and self.cur[1] == nd.nid:
            decode = self.decode_keys(nd, c_keys)
            for ref in nd.inputs:
                if ref[0] != "M":
                    continue
                core = self.cores[ref[1]]; n = len(core.vals) if core.vals is not None else 0
                if n == 0 or core.fmt == "lazy":
                    continue
                kind, spec, nscale = self.input_states(nd, ref); flat = np.zeros(len(c_keys), dtype=np.int64)
                for item in spec:
                    if item[0] == "x":
                        flat += item[1][x_idx] * item[4]
                    else:
                        flat += item[2][decode[item[1]]] * item[4]
                if core.fmt == "sparse":
                    pos = np.searchsorted(core.keys, flat); pos = np.minimum(pos, n - 1); flat = pos[core.keys[pos] == flat]
                else:
                    flat = flat[flat < n]
                m = self.ref_masks.setdefault((nd.nid, ref[1]), np.zeros(n, dtype=bool)); m[flat] = True
        return out

    def backward(self):
        import gmpy2
        from gmpy2 import mpfr
        gmpy2.set_context(self.D)
        for v in self.P.vars:
            self.markers[v] = np.full(len(self.P.dom[v]), mpfr(0), dtype=object); self.markerE[v] = 0
        for r in self.P.roots:
            self.seed(self.cores[r], 0, mpfr(1), 0)
        for nd in reversed(self.P.nodes):
            self.tick(); t = time.monotonic(); before = dict(self.c); self.cur = ("backward", nd.nid); core = self.cores[nd.nid]
            if core.fmt == "lazy":
                self.backward_lazy(nd, core)
            else:
                self.backward_block(nd, core); self.drain()
            core.stats["backward_s"] = time.monotonic() - t
            self.obs.node_event({"phase": "backward", "nid": nd.nid, "v": nd.v, "executed_format": core.fmt, "wall_s": core.stats["backward_s"], "counters_delta": self._delta(before), "bytes_vals": self.bytes_vals, "bytes_adj": self.bytes_adj, "pending_flushes": len(self.pending), "t_s": now()})
            if core.adj is not None and core.fmt != "lazy":
                self.bytes_adj -= len(core.vals) * self.mp
            elif core.adj:
                raise EN.Stop("FAULT", "lazy adjoint deltas left unconsumed at the frontier")
            core.adj = None
            if not self.cfg.get("keep_values_after_reverse", False):
                if core.fmt == "lazy" and core.lazy:
                    for k0 in list(core.lazy):
                        self.memo_order.pop((id(core), k0), None)
                self.bytes_vals -= core.bytes; core.bytes = 0; core.vals = None; core.keys = None; core.lazy = None; core.rows_rel = None
        self.cur = None


class Observer:
    def __init__(self, out):
        self.out = out; self.events = []; self.lock = threading.Lock(); self.X = None; self.stop = False; self.phase = "start"; self.n_events = 0
        self.f = open(os.path.join(out, "nodes.jsonl"), "a")
        self.th = threading.Thread(target=self.loop, daemon=True); self.th.start()

    def node_event(self, ev):
        with self.lock:
            self.f.write(json.dumps(ev, default=str) + "\n"); self.f.flush(); os.fsync(self.f.fileno()); self.n_events += 1; self.last = ev

    def snapshot(self, label, X=None):
        X = X or self.X
        rec = {"t_s": now(), "phase": self.phase, "label": label, "events": self.n_events, "last_event": getattr(self, "last", None)}
        if X is not None:
            rec.update({"counters": dict(X.c), "bytes_vals": X.bytes_vals, "bytes_adj": X.bytes_adj, "pending_flushes": len(X.pending), "current": X.cur})
        try:
            import resource; rec["maxrss_self_bytes"] = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
        except Exception:
            pass
        atomic_write(os.path.join(self.out, "progress.json"), json.dumps(rec, default=str))

    def loop(self):
        while not self.stop:
            try:
                self.snapshot("periodic")
            except Exception:
                pass
            time.sleep(0.5)


def main():
    mp, ep, out, deadline_s, cfgp = sys.argv[1:6]; deadline = float(deadline_s); os.makedirs(out, exist_ok=True)
    cfg = dict(EN.DEFAULTS); cfg.update(json.load(open(cfgp)) if os.path.exists(cfgp) else json.loads(cfgp))
    obs = Observer(out); rec = {"arm": "AGGREGATE_DP_V1", "kind": "diagnostic", "model": mp, "evidence": ep, "deadline_s": deadline, "config": cfg, "phases_s": {}, "status": None, "pid": os.getpid(), "started_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}
    T_DL = T_START + deadline
    try:
        rec["phases_s"]["startup_imports"] = now(); t = now(); m, ev = SRC.load(mp, ep); rec["phases_s"]["parse"] = now() - t
        rec["source"] = SRC.canonical_source_hashes(mp, ep); rec["n_vars"] = m.nvars; rec["n_evidence"] = len(ev); rec["task"] = CELL.task_of(rec, m)
        obs.phase = "reductions"; t = now(); R = SRC.Reduced(m, ev); red_deadline = time.monotonic() + cfg["source_reduction_wall_fraction"] * (T_DL - time.monotonic()); rrec = R.reduce(cfg["rules"], deadline=red_deadline); rec["phases_s"]["source_reductions"] = now() - t
        kinds = {}
        for s in R.steps:
            kinds[s[0]] = kinds.get(s[0], 0) + 1
        reduced_record = R.record(); rec["reduced_hash"] = reduced_record["reduced_hash"]
        rec["reductions"] = {"free_original": m.nvars - len(ev), "free_reduced": len(R.dom), "steps": kinds, "recognition": rrec, "reduced_states": sum(len(d) for d in R.dom.values()), "scale": str(R.scale), "factors_remaining": len(R.factors), "entries_remaining": sum(len(f.table) for f in R.factors)}
        rec["source_census"] = {"factors": len(m.factors), "entries": sum(len(f.table) for f in m.factors), "zeros": sum(1 for f in m.factors for t in f.table if t == 0), "max_card": max(m.card), "card_hist": {str(c): m.card.count(c) for c in sorted(set(m.card))}, "arity_hist": {str(k): sum(1 for f in m.factors if len(f.scope) == k) for k in sorted({len(f.scope) for f in m.factors})},
                               "deterministic_factors": sum(1 for f in m.factors if any(all(sum(1 for z in row if z != 0) == 1 for row in _rows(f, k)) for k in range(len(f.scope))))}
        atomic_write(os.path.join(out, "reduced_record.json"), json.dumps(reduced_record, default=str)); obs.snapshot("reduced_persisted")
        if R.zero_proof is not None:
            rec["status"] = "INCONSISTENT_EVIDENCE_PRODUCER_PROOF"; return
        obs.phase = "plan"; t = now(); P = EN.Program(R, cfg, deadline=T_DL); rec["phases_s"]["plan"] = now() - t
        metrics = node_metrics(P); plan = P.plan_record(); plan["structure_hash"] = P.structure_hash(); plan["node_metrics"] = metrics
        atomic_write(os.path.join(out, "plan_record.json"), json.dumps(plan, default=str)); obs.snapshot("plan_persisted")
        fmts = {}
        for nd in P.nodes:
            fmts[nd.fmt] = fmts.get(nd.fmt, 0) + 1
        rec["program"] = {"nodes": len(P.nodes), "components": len(P.components), "order_capped_at": P.order_info["capped_at"], "formats_planned": fmts, "core_entries_total": sum(nd.size for nd in P.nodes), "bag_rows_total": sum(nd.bag for nd in P.nodes), "raw_boundary_product_total": sum(x["raw_boundary_domain_product"] for x in metrics), "largest_core": max(nd.size for nd in P.nodes), "largest_bag": max(nd.bag for nd in P.nodes), "structure_hash": plan["structure_hash"],
                          "single_input_eliminations": sum(1 for x in metrics if x["single_input_elimination"]), "disjoint_input_nodes": sum(1 for x in metrics if x["inputs_have_disjoint_boundary_scopes"] and len(x["inputs"]) > 1), "compressed_axes": sum(1 for x in metrics for a in x["axes"] if a["compressed"]), "axes_total": sum(len(x["axes"]) for x in metrics)}
        obs.phase = "numeric"; attempts = []; final = None
        for p in cfg["precision_ladder"]:
            if time.monotonic() > T_DL:
                final = "RESOURCE_STOP"; rec["stop"] = {"phase": "ladder", "kind": "DEADLINE"}; break
            att = {"precision": p, "phases_s": {}}; counters = {}; X = ObservedExecutor(P, p, cfg, deadline=T_DL, counters=counters, obs=obs); obs.X = X
            try:
                t = now(); X.forward(); att["phases_s"]["forward"] = now() - t; obs.snapshot("forward_done")
                t = now(); X.backward(); att["phases_s"]["backward"] = now() - t; obs.snapshot("backward_done")
                t = now(); enc, roots, Emax = X.enclosures(); att["phases_s"]["enclose"] = now() - t; att["E_max"] = Emax
            except EN.Stop as ex:
                att["stop"] = {"kind": ex.kind, "detail": ex.detail, "current": X.cur}; att["counters"] = dict(X.c); att["bytes_vals"] = X.bytes_vals; att["bytes_adj"] = X.bytes_adj; attempts.append(att); final = "RESOURCE_STOP"; rec["stop"] = {"phase": "numeric", "kind": ex.kind, "detail": ex.detail, "precision": p, "current": X.cur}; break
            except A.NumericalRefusal as ex:
                att["numeric_refusal"] = str(ex); att["counters"] = dict(X.c); attempts.append(att); continue
            att["counters"] = dict(X.c); att["formats_executed"] = CELL.fmt_counts(X); att["downgraded_to_lazy"] = X.c.get("downgraded_to_lazy", 0)
            if any(A.exact_fr(z) == 0 for z, _ in roots.values()):
                attempts.append(att); final = "ZERO_EVIDENCE_NUMERIC_UNRESOLVED"; break
            t = now(); orig = CELL.decode_rows(R, enc); att["producer_max_width"] = str(max((U - L) for row in orig.values() for L, U in row)); att["phases_s"]["provisional_enclose"] = now() - t
            cert = {"arm": "AGGREGATE_DP_V1", "model_path": os.path.abspath(mp), "evidence_path": os.path.abspath(ep), "source": rec["source"], "expected_queries": list(range(m.nvars)), "reduced": reduced_record, "plan": P.plan_record(), "precision": p, "published_points": None,
                    "checker_caps": {"dense_core_cap_entries": cfg["dense_core_cap_entries"], "dense_bag_cap_entries": cfg["dense_bag_cap_entries"], "sparse_rows_cap": cfg["sparse_rows_cap"], "lazy_cache_entries": cfg["lazy_cache_entries"], "value_bytes_cap": cfg["checker_value_bytes_cap"]}}
            atomic_write(os.path.join(out, "certificate.json"), json.dumps(cert, default=str)); del X, enc, roots; obs.X = None; import gc; gc.collect()
            obs.phase = "checker"; t = now(); chk = CELL.run_checker(out, T_DL - time.monotonic(), rec, suffix="_p%d" % p); att["phases_s"]["checker"] = now() - t; att["checker_status"] = chk.get("status"); attempts.append(att); rec["checker"] = chk
            st = chk.get("status")
            if st == "INTERVALS_OK":
                obs.phase = "publish"; t = now(); final = CELL.publish(out, m, chk, rec, "_p%d" % p); rec["phases_s"]["publish"] = rec["phases_s"].get("publish", 0.0) + (now() - t)
                if final == "CERTIFIED" or time.monotonic() > T_DL - 0.5 or p == cfg["precision_ladder"][-1]:
                    break
                continue
            final = {"ZERO_EVIDENCE_PROVED": "INCONSISTENT_EVIDENCE_CERTIFIED", "CHECKER_INCOMPLETE": "SOLVER_COMPLETE_CHECKER_INCOMPLETE", "REJECTED": "CHECK_FAILED", "CHECKER_FAULT": "FAULT", "NUMERIC_UNRESOLVED_POSITIVITY": "NUMERIC_RESOURCE_STOP", "CHECKER_NUMERIC_REFUSAL": "NUMERIC_RESOURCE_STOP"}.get(st, "FAULT"); rec["reason"] = chk.get("reason")
            if st in ("NUMERIC_UNRESOLVED_POSITIVITY", "CHECKER_NUMERIC_REFUSAL") and time.monotonic() < T_DL - 0.5:
                continue
            break
        rec["attempts"] = attempts; rec["status"] = final or "NUMERIC_RESOURCE_STOP"
    except Exception as ex:
        import traceback
        rec["status"] = "FAULT"; rec["reason"] = "%s: %s" % (type(ex).__name__, ex); rec["traceback"] = traceback.format_exc()[-2500:]
    finally:
        obs.stop = True; rec["complete_response_s"] = now(); rec["within_deadline"] = rec["complete_response_s"] <= deadline; rec["observation_events"] = obs.n_events
        try:
            import resource; rec["maxrss_self_bytes"] = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss; rec["maxrss_children_bytes"] = resource.getrusage(resource.RUSAGE_CHILDREN).ru_maxrss
        except Exception:
            pass
        try:
            obs.snapshot("final")
        except Exception:
            pass
        atomic_write(os.path.join(out, "cell.json"), json.dumps(rec, indent=1, default=str)); print(json.dumps({"status": rec["status"], "complete_response_s": round(rec["complete_response_s"], 3), "events": obs.n_events}))


def _rows(f, k):
    st = f.strides(); others = [j for j in range(len(f.scope)) if j != k]
    import itertools
    for a in range(f.card[k]):
        yield [f.table[a * st[k] + sum(idx[i] * st[others[i]] for i in range(len(others)))] for idx in itertools.product(*[range(f.card[j]) for j in others])]


if __name__ == "__main__":
    main()
