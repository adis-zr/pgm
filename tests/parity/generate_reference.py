"""Extraction-parity reference generator (step 1 consolidation; brief section 9).

Runs the SAME tasks with explicit settings through the backend worker and the response witness / native prefix,
recording every semantic field that must survive the extraction: original inventories, coordinate mapping, exact
rational bounds / points, guarantee labels, evidence and scalar handling, positive-mass witness, refusals, resource
and risk accounting, and fixed-work numerical prefixes (operation / RNG order).  Wall-limited draw counts are NOT
compared; they are recorded under `wall_limited` for information only.

usage: python tests/parity/generate_reference.py OUT.json   (run at the pinned reference commit, then after extraction)
"""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
PY = sys.executable
FIXTURES = HERE / "fixtures"

MODELS = {
    # the API suite's asymmetric two-variable model (independent exact reference Z = 47): structural forest + block exact route
    "asym2": "MARKOV\n2\n2 2\n3\n1 0\n1 1\n2 0 1\n2\n2 1\n2\n1 3\n4\n5 2 1 8\n",
    "asym2_evidence": ("MARKOV\n2\n2 2\n3\n1 0\n1 1\n2 0 1\n2\n2 1\n2\n1 3\n4\n5 2 1 8\n", "1 0 1\n"),
    # binary pairwise bipartite path (stream / support routes), with a hard zero so the response route is screened out
    "bip4": "MARKOV\n4\n2 2 2 2\n3\n2 0 1\n2 1 2\n2 2 3\n4\n3 1 1 2\n4\n2 5 1 1\n4\n1 2 3 0\n",
    # nonbinary 3-cycle (block exact route; quotient identity / exact representation)
    "cyc3_card3": "MARKOV\n3\n3 3 2\n3\n2 0 1\n2 1 2\n2 0 2\n9\n6 5 5 5 6 5 5 5 6\n6\n5 6 6 5 5 6\n6\n6 5 5 6 6 5\n",
    # strictly positive weak pairwise (response route admissible): 4 binary variables, cycle + chord
    "pos4": "MARKOV\n4\n2 2 2 2\n4\n2 0 1\n2 1 2\n2 2 3\n2 0 2\n4\n6 5 5 6\n4\n5 6 6 5\n4\n6 5 5 6\n4\n6 5 5 6\n",
    # zero evidence mass
    "zero_mass": ("MARKOV\n2\n2 2\n3\n1 0\n1 1\n2 0 1\n2\n2 1\n2\n1 3\n4\n0 0 0 0\n", "1 0 1\n"),
}


def write_fixtures():
    FIXTURES.mkdir(exist_ok=True)
    paths = {}
    for name, spec in MODELS.items():
        model, evidence = spec if isinstance(spec, tuple) else (spec, None)
        p = FIXTURES / (name + ".uai")
        p.write_text(model)
        ev = Path(str(p) + ".evid")
        if evidence is not None:
            ev.write_text(evidence)
        elif ev.exists():
            ev.unlink()
        paths[name] = p
    return paths


def worker_cmd():
    return [PY, "-m", "pgm.backends.worker"]


def run_worker(backend, model, *, mode="auto", budget=6.0, delta="1/1000000", epsilon="1/200", seed=1, route="auto", extra=()):
    with tempfile.TemporaryDirectory(prefix="parity-") as d:
        out = Path(d) / "out.json"
        deadline = time.monotonic() + budget
        cmd = worker_cmd() + ["--backend", backend, "--input", str(model), "--output", str(out), "--deadline", repr(deadline),
                              "--epsilon", epsilon, "--delta", delta, "--seed", str(seed), "--memory-mib", "512", "--mode", mode,
                              "--structural-route", route, *extra]
        env = dict(os.environ, PYTHONPATH=str(ROOT / "src") + os.pathsep + str(ROOT / "code"), OMP_NUM_THREADS="1")
        p = subprocess.run(cmd, capture_output=True, text=True, env=env, timeout=budget + 30)
        if not out.exists():
            return dict(worker_exit=p.returncode, stderr_tail=p.stderr[-800:], output=None)
        return json.loads(out.read_text())


SEMANTIC = ("outcome", "guarantee", "K", "published", "binding", "positive_mass_witness", "answers", "enclosures")


def semantic_view(result):
    if result is None or result.get("output", 1) is None:
        return result
    view = {k: result.get(k) for k in SEMANTIC}
    mech = result.get("mechanism") or {}
    view["mechanism_route"] = mech.get("route")
    view["refusal"] = mech.get("refusal") or mech.get("adapter_refusal")
    view["Z"] = result.get("Z")
    view["Z_enclosure"] = {k: v for k, v in (result.get("Z_enclosure") or {}).items() if k in ("lo", "hi", "ln_lo_exact", "ln_hi_exact", "canonical_scalar")} if isinstance(result.get("Z_enclosure"), dict) else result.get("Z_enclosure")
    view["ledger_identity"] = mech.get("constructor_live_ledger_identity")
    view["risk"] = dict(epsilon=result.get("epsilon"), delta=result.get("delta"))
    return view


def response_prefix(model_path):
    """witness / plan constants and a FIXED-WORK native observer prefix (same seed -> identical sums), independent of wall time"""
    try:
        from pgm.algorithms.response import spectral_witness as SW, heatbath_native as HN, heatbath_exact as HX, response_certificate as RC
        from pgm.algorithms.quotient import coarse_envelope as CE
        from pgm.algorithms.structural import core as CORE
        from pgm.algorithms.response import markov_certificate as MC
        layout = "canonical"
    except ImportError:
        for sub in ("code/cex/hp", "code/cex/newarm", "code/cex/blockres"):
            sys.path.insert(0, str(ROOT / sub))
        import spectral_witness as SW, heatbath_native as HN, heatbath_exact as HX, response_certificate as RC, coarse_envelope as CE, core as CORE, markov_certificate as MC
        layout = "legacy"
    from fractions import Fraction as F
    raw, binding = CORE.read_uai(str(model_path))
    B = CE.Budget(64 << 20); clk = CE.Clock(time.monotonic() + 60, {})
    M = CE.canonicalize(raw, clk, B)
    W = SW.certify(M, B, clk, policy=SW.POLICY_REVISED)
    rec = dict(layout=layout, binding=binding, canonical_scalar=str(M.scalar), eligible=W["eligible"], g_exact=W.get("g_exact"), width_exact=W.get("width_exact"), l=W.get("l"), u=W.get("u"), attempts=len(W.get("attempts") or []))
    if W["eligible"]:
        g = F(W["g_exact"]); hbm = HX.HeatBathModel(M); n = hbm.n
        eta = RC.eta_lower(g, n); x0 = MC.choose_x0(hbm)
        cache = SW.LogCache(B, clk, "parity cache"); lp0, W0 = MC.log_p0_lower(hbm, x0, cache); t_burn, _ = MC.burn_in_steps(lp0, g, F(1, 2 * 10**6)); cache.release()
        plan = HN.local_checkpoint_plan(); centers = [HN.center_for(k) for k in hbm.cards]
        chain = HN.NativeChain(hbm, x0, 7, clk, budget=B, observer=dict(sites=list(range(n)), centers=centers, plan=plan))
        chain.run(5000); chain.set_recording(); chain.observer_start(); chain.run(70000)
        occ = chain.flush(); snaps = chain.observer_snapshots(); counters = chain.counters(); state = chain.state(); chain.close()
        rec.update(eta=str(eta), x0=x0, burn_in_steps=t_burn, ln_p0_lower=str(lp0), local_plan_head=plan[:5], centers=centers,
                   fixed_prefix=dict(steps=75000, seed=7, state=state, occupation=occ, counters={k: counters[k] for k in ("resolved", "unresolved", "null_moves", "site_rejections", "exact_fallbacks")},
                                     snapshots=[dict(site=s["site"], count=s["count"], j=s["j"], first_lo=[str(x) for x in s["first_lo"]], first_hi=[str(x) for x in s["first_hi"]], second_hi=[str(x) for x in s["second_hi"]]) for s in snaps]),
                   live_after_close=B.live)
    SW.release_retained(W, B)
    return rec


def main(out_path):
    paths = write_fixtures()
    ref = dict(generator_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(), commit=subprocess.run(["git", "-C", str(ROOT), "rev-parse", "HEAD"], capture_output=True, text=True).stdout.strip(),
               fixtures={k: hashlib.sha256(p.read_bytes()).hexdigest() for k, p in paths.items()}, cases={})
    cases = [
        ("structural/asym2", "structural", "asym2", {}), ("structural/asym2_evidence", "structural", "asym2_evidence", {}),
        ("structural/bip4_stream", "structural", "bip4", dict(route="stream")), ("structural/bip4_support", "structural", "bip4", dict(route="support")),
        ("structural/cyc3", "structural", "cyc3_card3", {}), ("structural/zero_mass", "structural", "zero_mass", {}),
        ("block/asym2", "block", "asym2", {}), ("block/asym2_exact_mode", "block", "asym2", dict(mode="exact", delta="0")),
        ("block/cyc3", "block", "cyc3_card3", {}), ("block/bip4", "block", "bip4", {}), ("block/zero_mass", "block", "zero_mass", {}),
        ("quotient/cyc3_deterministic", "quotient", "cyc3_card3", dict(mode="deterministic", delta="0")), ("quotient/asym2", "quotient", "asym2", {}),
        ("response/bip4_refused_hard_zero", "response", "bip4", {}), ("response/zero_mass", "response", "zero_mass", {}),
        ("response/pos4_exact_mode_ineligible", "response", "pos4", dict(mode="exact", delta="0")),
    ]
    for key, backend, model, kw in cases:
        t0 = time.monotonic(); r = run_worker(backend, paths[model], **kw); ref["cases"][key] = dict(settings=dict(backend=backend, model=model, **kw), semantic=semantic_view(r), seconds=round(time.monotonic() - t0, 3))
        print(key, (ref["cases"][key]["semantic"] or {}).get("outcome"), (ref["cases"][key]["semantic"] or {}).get("published"), flush=True)
    # wall-limited stochastic routes: recorded, not compared
    for key, backend, model in (("response/pos4", "response", "pos4"), ("block/pos4", "block", "pos4")):
        r = run_worker(backend, paths[model], budget=4.0); v = semantic_view(r)
        ref.setdefault("wall_limited", {})[key] = dict(outcome=v.get("outcome"), published=v.get("published"), K=v.get("K"), mechanism_route=v.get("mechanism_route"), binding=v.get("binding"), positive_mass_witness=v.get("positive_mass_witness"), guarantee=v.get("guarantee"))
        print(key, "(wall-limited)", v.get("outcome"), v.get("published"), flush=True)
    ref["response_prefix"] = {"pos4": response_prefix(paths["pos4"]), "cyc3_card3": response_prefix(paths["cyc3_card3"])}
    print("response prefix pos4 eligible", ref["response_prefix"]["pos4"]["eligible"], "eta", ref["response_prefix"]["pos4"].get("eta"))
    Path(out_path).write_text(json.dumps(ref, indent=1, sort_keys=True, default=str) + "\n")
    print("written", out_path)


if __name__ == "__main__":
    main(sys.argv[1])
