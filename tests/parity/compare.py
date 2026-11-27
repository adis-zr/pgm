"""Characterization comparison: a regenerated parity file against the pinned reference (tests/parity/reference_f8197e6.json).

Compared: every deterministic case's semantic view (outcome, guarantee, inventory size, published count, binding, witness,
answers = exact rational bounds / points / labels, enclosures, route, typed refusal, Z and its exact enclosure, ledger identity,
risk accounting); the wall-limited cases' invariants (binding, K, route, witness); the fixed-work response prefixes (witness
constants, eta, x0, burn-in, local plan, centers, the 75,000-step native observer prefix: state, occupation, counters,
snapshot sums) except the `layout` tag.  Timing fields are never compared.
usage: compare.py CANDIDATE.json [--reference REF.json] [--report OUT.json]
"""
import argparse, json, sys
from pathlib import Path

HERE = Path(__file__).resolve().parent


def diff(a, b, path=""):
    out = []
    if isinstance(a, dict) and isinstance(b, dict):
        for k in sorted(set(a) | set(b)):
            if k not in a: out.append((path + "/" + str(k), "<absent>", "present"))
            elif k not in b: out.append((path + "/" + str(k), "present", "<absent>"))
            else: out += diff(a[k], b[k], path + "/" + str(k))
    elif isinstance(a, list) and isinstance(b, list):
        if len(a) != len(b): out.append((path, "len %d" % len(a), "len %d" % len(b)))
        for i, (x, y) in enumerate(zip(a, b)): out += diff(x, y, path + "[%d]" % i)
    elif a != b:
        out.append((path, a, b))
    return out


def main(argv=None):
    ap = argparse.ArgumentParser(); ap.add_argument("candidate"); ap.add_argument("--reference", default=str(HERE / "reference_f8197e6.json")); ap.add_argument("--report", default=None)
    a = ap.parse_args(argv)
    ref = json.loads(Path(a.reference).read_text()); cand = json.loads(Path(a.candidate).read_text())
    report = dict(reference=a.reference, reference_commit=ref.get("commit"), candidate=a.candidate, candidate_commit=cand.get("commit"), fixtures_identical=(ref["fixtures"] == cand["fixtures"]), cases={}, wall_limited={}, response_prefix={}, differences=0)
    for key in sorted(set(ref["cases"]) | set(cand["cases"])):
        if key not in ref["cases"] or key not in cand["cases"]:
            report["cases"][key] = dict(status="MISSING", side="reference" if key not in ref["cases"] else "candidate"); report["differences"] += 1; continue
        d = diff(ref["cases"][key]["semantic"], cand["cases"][key]["semantic"])
        report["cases"][key] = dict(status="IDENTICAL" if not d else "DIFFERENT", outcome=(cand["cases"][key]["semantic"] or {}).get("outcome"), published=(cand["cases"][key]["semantic"] or {}).get("published"), differences=[dict(path=p, reference=str(x)[:200], candidate=str(y)[:200]) for p, x, y in d[:20]])
        report["differences"] += len(d)
    for key in sorted(set(ref.get("wall_limited", {})) | set(cand.get("wall_limited", {}))):
        r = ref["wall_limited"].get(key, {}); c = cand["wall_limited"].get(key, {})
        inv = [k for k in ("binding", "K", "mechanism_route", "positive_mass_witness") if r.get(k) != c.get(k)]
        report["wall_limited"][key] = dict(status="IDENTICAL_INVARIANTS" if not inv else "DIFFERENT", differing=inv, reference_outcome=r.get("outcome"), candidate_outcome=c.get("outcome"), reference_published=r.get("published"), candidate_published=c.get("published"))
        report["differences"] += len(inv)
    for key in sorted(set(ref.get("response_prefix", {})) | set(cand.get("response_prefix", {}))):
        r = dict(ref["response_prefix"].get(key, {})); c = dict(cand["response_prefix"].get(key, {})); r.pop("layout", None); c.pop("layout", None)
        d = diff(r, c)
        report["response_prefix"][key] = dict(status="IDENTICAL" if not d else "DIFFERENT", layout=dict(reference=ref["response_prefix"].get(key, {}).get("layout"), candidate=cand["response_prefix"].get(key, {}).get("layout")), differences=[dict(path=p, reference=str(x)[:200], candidate=str(y)[:200]) for p, x, y in d[:20]])
        report["differences"] += len(d)
    report["verdict"] = "IDENTICAL" if report["differences"] == 0 and report["fixtures_identical"] else "DIFFERENT"
    text = json.dumps(report, indent=1, sort_keys=True)
    if a.report: Path(a.report).write_text(text + "\n")
    print("parity %s: %d differences; cases %s; wall-limited %s; response prefix %s" % (report["verdict"], report["differences"], {k: v["status"] for k, v in report["cases"].items()}, {k: v["status"] for k, v in report["wall_limited"].items()}, {k: v["status"] for k, v in report["response_prefix"].items()}))
    return 0 if report["verdict"] == "IDENTICAL" else 1


if __name__ == "__main__":
    sys.exit(main())
