"""ONE pilot control in a FRESH child process (spawned by tests/test_mdi_selector_pilot.py under ext.supervise.run with a 10 s
deadline, a 1 GiB process-tree RSS limit and no grace): the whole control -- the tiny invocation AND its exact-oracle check --
runs inside the supervised child. Writes a JSON result; the parent asserts on it. Every oracle call asserts the restricted
domain size <= 4096 BEFORE enumerating. Injected values (clock jumps, forced non-admission, sleeps) are labelled `injected`."""
import sys, os, json, time, tempfile
HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE); sys.path.insert(0, os.path.join(HERE, "tests"))
from fractions import Fraction as Fr
from mdi import model as M, pipeline as PLN, oracle as O, budget as B, quotient as QT, support as SP, capacity as CAPX, selector_pilot as SPL, preprocess as PRE
import mdi.registry  # noqa: F401

MAX_STATES = 4096
EQ = lambda a, b: M.Factor(scope=(a, b), card=(2, 2), table=[Fr(1), Fr(0), Fr(0), Fr(1)], origin=10 * a + b)


def m4():       # 16 original assignments; the quotient (0=1=2) keeps the hard zero of [1,1,1,0] on (2,3)
    return M.Model(nvars=4, card=[2] * 4, factors=[EQ(0, 1), EQ(1, 2), M.Factor(scope=(2, 3), card=(2, 2), table=[Fr(1), Fr(1), Fr(1), Fr(0)], origin=23)]).validate()


def pos5():     # 32 assignments, strictly positive
    return M.Model(nvars=5, card=[2] * 5, factors=[M.Factor(scope=(v, v + 1), card=(2, 2), table=[Fr(1), Fr(2), Fr(3), Fr(4)], origin=v) for v in range(4)]).validate()


def nat2():     # 4 assignments, the natural rejection
    return M.Model(nvars=2, card=[2, 2], factors=[M.Factor(scope=(0, 1), card=(2, 2), table=[Fr(1), Fr(1), Fr(1), Fr(0)], origin=0)]).validate()


def ratio_below2():   # 1,024 assignments; one forced unary -> eliminated 1 but the schedule shrinks by less than 2x
    facs = [M.Factor(scope=(v, v + 1), card=(2, 2), table=[Fr(1), Fr(2), Fr(3), Fr(4)], origin=v) for v in range(9)] + [M.Factor(scope=(9,), card=(2,), table=[Fr(0), Fr(1)], origin=99)]
    return M.Model(nvars=10, card=[2] * 10, factors=facs).validate()


def band4():    # 4,096 restricted assignments; support ratio ~13.7; producer and checker orders equal
    from test_mdi_support_pilot import _band_chain
    return _band_chain(4, k=8, band=2, seed=31)


def perm6():    # 4,096 restricted assignments; support ratio ~10.5; producer and checker orders DIFFER
    from test_mdi_support_pilot import _perm_chain
    return _perm_chain(6, k=4, seed=1)


def restricted_states(restricted):
    n = 1
    for v in restricted.free:
        n *= int(restricted.card[v])
    return n


def oracle_contained(res, m, ev):
    restricted = M.restrict(m, ev)
    n = restricted_states(restricted)
    assert n <= MAX_STATES, "oracle refused: %d restricted states > %d" % (n, MAX_STATES)
    Z, pt = O.exact_all_marginals(restricted)
    ok = set(res.intervals) == set(range(m.nvars)) and all(Fr(res.intervals[v][a][0]) <= pt[v][a] <= Fr(res.intervals[v][a][1]) for v in pt for a in range(len(pt[v])))
    return ok, n


def run(m, ev, **kw):
    with SPL.enabled():
        res = PLN.solve(m, ev, wall_s=kw.pop("wall_s", 120), cap_bytes=1 << 30, plan_dir=tempfile.mkdtemp(), research_enabled=False, route_policy="selector", **kw)
    assert PLN._select_route.__module__ == "mdi.pipeline" and PLN.run_loaded.__module__ == "mdi.pipeline" and PLN._PILOT_HOOKS == {}
    return res


def blk_of(res):
    return res.plan["selector"]


def summary(res, m, ev, with_oracle=True):
    blk = blk_of(res)
    out = {"status": res.status, "route": blk.get("executed_route"), "attempts": [(a["mechanism"], a["verdict"], a.get("preflight"), a.get("reduction_ratio"), a.get("charged_entries")) for a in blk["attempts"]],
           "scopes": [(s["scope"], s["kind"], s["status"], s["wall_s"], s["charged_entries"]) for s in blk["scopes"]],
           "record_scopes": blk.get("record_scopes"), "binding_scopes": blk.get("binding_scopes"), "selection_scope": blk.get("selection_scope"),
           "cleanup": blk.get("cleanup"), "manifest": blk.get("optional_state_manifest"), "optional_cost": blk.get("optional_cost"), "total_optional_wall_s": blk.get("total_optional_wall_s"),
           "late_refusal": blk.get("late_refusal"), "chosen": res.plan.get("chosen"), "prices": [p["name"] for p in res.prices], "rejected_typed": [x.get("typed") for x in res.rejected],
           "caches_after": {"support": len(SP._SUPPORT_CACHE), "recognition": len(QT._RECOGNITION_CACHE), "occupancy": len(CAPX._OCCUPANCY_CACHE)},
           "executed": {k: v for k, v in (res.plan.get("executed") or {}).items() if k in ("layout",)}, "executed_quotient": ((res.plan.get("executed") or {}).get("quotient") or {}).get("reused_from_discovery"),
           "executed_support": ((res.plan.get("executed") or {}).get("support") or {}).get("reused_from_discovery"), "checker": {k: (res.checker or {}).get(k) for k in ("status", "coordinates_checked")}}
    if with_oracle and res.status.startswith("CERTIFIED"):
        ok, n = oracle_contained(res, m, ev); out["oracle"] = {"contained": ok, "restricted_states": n, "max_states": MAX_STATES}
    return out


def spy_occupancy(calls):
    orig = CAPX.occupancy_probe
    def spy(plan, factors, card, deadline=None, charge=None):
        calls.append(len(set(v for f in factors for v in f.scope))); return orig(plan, factors, card, deadline=deadline, charge=charge)
    CAPX.occupancy_probe = spy
    return orig


CONTROLS = {}
def control(fn): CONTROLS[fn.__name__] = fn; return fn


@control
def positive_bypass():
    m = pos5(); res = run(m, {}); return summary(res, m, {})


@control
def natural_rejection():
    m = nat2(); res = run(m, {}); return summary(res, m, {})


@control
def residual_zero_quotient_success():
    m = m4(); calls = []; orig = spy_occupancy(calls)
    try:
        res = run(m, {})
    finally:
        CAPX.occupancy_probe = orig
    out = summary(res, m, {}); out["occupancy_call_free_counts"] = calls; return out


@control
def late_binding_refusal_after_genuine_binding():
    m = m4(); orig = PLN.bind_loaded
    def ineligible(back, *a, **k):
        price = orig(back, *a, **k)
        if (back.program or {}).get("quotient"):
            price.eligible = False; price.ineligible_reason = "injected: declared quotient not re-derivable at binding"
        return price
    PLN.bind_loaded = ineligible
    try:
        res = run(m, {})
    finally:
        PLN.bind_loaded = orig
    return summary(res, m, {})


@control
def binding_exhausted_after_injected_work():
    m = m4(); orig = PLN.bind_loaded
    def slow_then_exhaust(back, *a, **k):
        if (back.program or {}).get("quotient"):
            time.sleep(0.025); raise PLN.ProbeExhausted("injected: 25 ms of binding work, then the window is spent")
        return orig(back, *a, **k)
    PLN.bind_loaded = slow_then_exhaust
    try:
        res = run(m, {})
    finally:
        PLN.bind_loaded = orig
    out = summary(res, m, {}); out["injected"] = {"sleep_s": 0.025, "then": "ProbeExhausted inside bind_loaded"}; return out


@control
def global_stop_at_gate():
    m = m4(); orig = B.Budget.charge
    def gate_stop(self, name, amount=1, where=""):
        cur = orig(self, name, amount, where)
        if where == "selector gate":
            raise B.BudgetExceeded(name, cur, 1, where)
        return cur
    B.Budget.charge = gate_stop
    try:
        res = run(m, {})
    finally:
        B.Budget.charge = orig
    out = summary(res, m, {}, with_oracle=False); out["reason"] = res.reason; out["injected"] = {"BudgetExceeded": "at the selector gate after its charge"}; return out


@control
def global_stop_in_recognizer():
    m = m4(); orig = B.Budget.charge
    def seven(self, name, amount=1, where=""):
        cur = orig(self, name, amount, where)
        if where == "quotient recognition" and self.used_by_source.get("%s@%s" % (name, where), 0) > 7:
            raise B.BudgetExceeded(name, self.used_by_source["%s@%s" % (name, where)], 7, where)
        return cur
    B.Budget.charge = seven
    try:
        res = run(m, {})
    finally:
        B.Budget.charge = orig
    out = summary(res, m, {}, with_oracle=False); out["injected"] = {"BudgetExceeded": "inside the recognizer after 8 charged entries"}; return out


@control
def prospective_refusal_declines_before_allocation():
    m = m4(); calls = []; orig_probe = spy_occupancy(calls); orig_admit = CAPX.admit
    def refuse_conservative(fc, wall, cap, now, **kw):
        ad = orig_admit(fc, wall, cap, now, **kw)
        if fc.get("occupancy_used") is False and len(calls) >= 1:                 # the pilot's conservative (occupancy=None) forecast for the quotient
            ad = dict(ad, certificate="INJECTED_NOT_FEASIBLE", certificate_reason="injected for the control")
        return ad
    CAPX.admit = refuse_conservative
    try:
        res = run(m, {})
    finally:
        CAPX.occupancy_probe = orig_probe; CAPX.admit = orig_admit
    out = summary(res, m, {}); out["occupancy_call_free_counts"] = calls; out["injected"] = {"CAPX.admit": "INJECTED_NOT_FEASIBLE for the conservative quotient forecast"}
    out["declined"] = [x for x in res.rejected if x.get("typed") == "QUOTIENT_DECLINED_PREFLIGHT"]; return out


@control
def ratio_below_two_rejected_before_admission_work():
    m = ratio_below2(); calls = []; orig = spy_occupancy(calls)
    try:
        res = run(m, {})
    finally:
        CAPX.occupancy_probe = orig
    out = summary(res, m, {}); out["occupancy_call_free_counts"] = calls; return out


@control
def support_two_orders():
    m = perm6(); res = run(m, {}); return summary(res, m, {})


@control
def support_same_order():
    m = band4(); res = run(m, {}); return summary(res, m, {})


@control
def static_prospective_figures_repeated_factors():
    """STATIC control (no allocation): the prospective figures distinguish operand multiplicity (a repeated factor occurrence) and
    report retained separator entries, in distinct units."""
    from mdi import plan as P
    r = M.restrict(m4(), {}); s = PRE.simplify(r)
    rr = M.Restricted(model=r.model, evidence={}, factors=list(s.factors), free=list(s.free), card=dict(s.card), constant=r.constant, impossible_factor=None)
    chk = CAPX.checker_plan(rr)
    one = SPL._prospective_probe(chk, rr.card, rr.factors)
    rr2 = M.Restricted(model=r.model, evidence={}, factors=list(s.factors) + list(s.factors), free=list(s.free), card=dict(s.card), constant=r.constant, impossible_factor=None)
    two = SPL._prospective_probe(CAPX.checker_plan(rr2), rr2.card, rr2.factors)
    return {"single": one, "doubled_factor_occurrences": two, "no_allocation": True}


if __name__ == "__main__":
    name, out_path = sys.argv[1], sys.argv[2]
    t0 = time.monotonic(); rec = {"control": name, "started": time.strftime("%Y-%m-%d %H:%M:%S")}
    try:
        rec["result"] = CONTROLS[name](); rec["ok"] = True
    except BaseException as e:
        rec["ok"] = False; rec["error"] = "%s: %s" % (type(e).__name__, e)
    rec["child_elapsed_s"] = round(time.monotonic() - t0, 4)
    json.dump(rec, open(out_path, "w"), indent=1, default=str)
    sys.exit(0 if rec["ok"] else 1)
