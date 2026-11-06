"""PGMax sum-product BP (temperature 1.0) MAR for one UAI model + evidence; runs in the PGMax venv. Evidence is applied by EXACT slicing of
every factor (rationals) before log-potentials are formed; zero entries become excluded configurations (EnumFactorGroup valid configs).
usage: python pgmax_mar.py MODEL EVID OUT.MAR SIDE.json NUM_ITERS DAMPING"""
import sys, os, time, json, itertools, math
T0 = time.monotonic()
sys.path.insert(0, "/Users/adis/Workspace/pgm/code")
import numpy as np
import jax; jax.config.update("jax_platform_name", "cpu")
from pgmax import fgraph, fgroup, infer, vgroup
from ext import uai as U
t_imp = time.monotonic() - T0


def main():
    mp, ep, outp, sidep, iters, damping = sys.argv[1:7]; iters = int(iters); damping = float(damping)
    t = time.monotonic(); m = U.read_model(mp); ev = U.read_evidence(ep); t_parse = time.monotonic() - t
    t = time.monotonic()
    free = [v for v in range(m.nvars) if v not in ev]
    groups = {}
    for v in free:
        groups.setdefault(m.card[v], []).append(v)
    vg = {c: vgroup.NDVarArray(num_states=c, shape=(len(vs),)) for c, vs in groups.items()}
    slot = {v: (m.card[v], groups[m.card[v]].index(v)) for v in free}
    fg = fgraph.FactorGraph(variable_groups=list(vg.values()))
    n_fac = 0; zero_Z = False
    for f in m.factors:
        fixed = {v: ev[v] for v in f.scope if v in ev}; sc = [v for v in f.scope if v not in ev]
        if not sc:
            if f.at(fixed) == 0:
                zero_Z = True
            continue
        configs = []; logp = []
        for conf in itertools.product(*[range(m.card[v]) for v in sc]):
            a = dict(zip(sc, conf)); a.update(fixed); val = f.at(a)
            if val > 0:
                configs.append(conf); logp.append(math.log(float(val)))
        if not configs:
            zero_Z = True; continue
        fg.add_factors(fgroup.EnumFactorGroup(variables_for_factors=[[vg[slot[v][0]][slot[v][1]] for v in sc]], factor_configs=np.array(configs, dtype=int), log_potentials=np.array(logp, dtype=np.float32)))
        n_fac += 1
    t_build = time.monotonic() - t
    if zero_Z:
        json.dump({"status": "zero_partition_by_sliced_factor", "phases_s": {"startup_imports": t_imp, "parse": t_parse, "convert": t_build}}, open(sidep, "w")); print("UNSUPPORTED: a sliced factor has no positive configuration (Z = 0 under the evidence); PGMax has no zero-partition output"); sys.exit(4)
    t = time.monotonic(); bp = infer.BP(fg.bp_state, temperature=1.0); arrs = bp.init(); t_compile0 = time.monotonic() - t
    t = time.monotonic(); arrs = bp.run(arrs, num_iters=iters, damping=damping); bel = bp.get_beliefs(arrs); marg = infer.get_marginals(bel)
    for c in vg:
        np.asarray(marg[vg[c]]).block_until_ready() if hasattr(np.asarray(marg[vg[c]]), "block_until_ready") else None
    marg = {c: np.asarray(marg[vg[c]], dtype=np.float64) for c in vg}; t_run = time.monotonic() - t
    t = time.monotonic(); rows = []
    for v in range(m.nvars):
        if v in ev:
            rows.append([1.0 if s == ev[v] else 0.0 for s in range(m.card[v])])
        else:
            c, i = slot[v]; rows.append([float(x) for x in marg[c][i]])
    txt = "MAR\n%d " % m.nvars + " ".join("%d %s" % (len(r), " ".join("%.10g" % x for x in r)) for r in rows) + "\n"
    tmp = outp + ".w"; open(tmp, "w").write(txt); os.replace(tmp, outp); t_ser = time.monotonic() - t
    json.dump({"phases_s": {"startup_imports": t_imp, "parse": t_parse, "convert": t_build, "plan": t_compile0, "solve": t_run, "serialize": t_ser, "total": time.monotonic() - T0},
               "config": {"temperature": 1.0, "num_iters": iters, "damping": damping, "dtype": str(np.asarray(list(marg.values())[0]).dtype) if marg else None, "jax": jax.__version__, "device": str(jax.devices()[0]), "factors": n_fac, "free_vars": len(free)}}, open(sidep, "w"))


if __name__ == "__main__":
    main()
