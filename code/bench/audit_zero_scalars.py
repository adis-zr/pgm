"""Independent exact audit (review item 4): for every selected case, slice every factor at the supplied evidence; report every empty-scope
sliced factor and whether any is ZERO (which the pre-repair libDAI driver would have dropped). Also replays the adapter's forced-state proof
on each case and reports proved forced states / zero-partition witnesses. Writes ZERO_SCALAR_AUDIT.json."""
import os, sys, json
HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__))); sys.path.insert(0, HERE)
from ext import uai as U
from bench import cbi_adapter as AD


def main(S):
    man = json.load(open(os.path.join(S, "CAMPAIGN_MANIFEST.json"))); inv = {c["case"]: c for c in json.load(open(os.path.join(S, "INVENTORY.json")))["cases"]}
    out = {}
    for case in sorted({c["case"] for c in man["cells"]}):
        row = inv[case]; m = U.read_model(os.path.join(S, row.get("committed_model_path", row["model_path"]))); ev = U.read_evidence(os.path.join(S, row.get("committed_evidence_path", row["evidence_path"])))
        consts = []
        for f in m.factors:
            if all(v in ev for v in f.scope):
                consts.append((f.index, f.at({v: ev[v] for v in f.scope})))
        zero = [i for i, v in consts if v == 0]
        proved, zw = AD.prove_forced(m, ev)
        out[case] = {"evidence": len(ev), "empty_scope_factors_after_slicing": len(consts), "zero_sliced_constants": zero, "forced_states_proved_beyond_evidence": len(proved) - len(ev), "zero_partition_witness": zw}
    aff = [c for c, v in out.items() if v["zero_sliced_constants"] or v["zero_partition_witness"]]
    json.dump({"note": "exact rational slicing of every selected case at its evidence; a zero sliced constant would have been dropped by the pre-repair libDAI driver (and makes every marginal undefined)", "affected_cases": aff, "cases": out}, open(os.path.join(S, "ZERO_SCALAR_AUDIT.json"), "w"), indent=1)
    print("cases", len(out), "| with empty-scope sliced factors:", sum(1 for v in out.values() if v["empty_scope_factors_after_slicing"]), "| ZERO sliced constants:", aff, "| forced states beyond evidence:", {c: v["forced_states_proved_beyond_evidence"] for c, v in out.items() if v["forced_states_proved_beyond_evidence"]})


if __name__ == "__main__":
    main(os.path.abspath(sys.argv[1]))
