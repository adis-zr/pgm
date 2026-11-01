"""The release driver's final verdict (r25, completed r26): parses the three
matrix summaries and requires the EXACT expected coverage -- every required
row identity once, each PASS, each carrying a PRESENT successful result
(`result.ok` is true: a PASS label over a false or absent result is a
contradiction, not a pass), no BLOCKED / SKIP / duplicate / missing /
unexpected required entries -- with the summaries RECOMPUTED from the rows (a
summary saying 'failed: 0' is not evidence that the required tests ran). Run
with an interpreter independent of the one under test. Prints the findings;
exits 0 only when every obligation holds.

    verdict.py ACCEPTANCE.json ROUTE.json GATE.json RUN_MARKER
"""
import json, os, sys

EXPECTED = {
    "ACCEPTANCE_MATRIX": ("rows", "row", ["P1", "P2", "P3", "P4", "P5", "P6", "P7", "P8", "P9"]),
    "ROUTE_MATRIX": ("controls", "control", ["R1", "R2", "R3", "R4", "R5", "R6", "R7"]),
    "GATE_MATRIX": ("controls", "control", ["A1", "B1", "B2", "B3", "B4"]),
}


def check(label, path, marker):
    problems = []
    if not os.path.exists(path):
        return ["%s was not produced by this run" % label], None
    if os.path.getmtime(path) < os.path.getmtime(marker):
        return ["%s is STALE (older than this run)" % label], None
    try:
        s = json.load(open(path))
    except ValueError as e:
        return ["%s is not valid JSON: %s" % (label, e)], None
    list_key, name_key, expected = EXPECTED[label]
    rows = s.get(list_key)
    if not isinstance(rows, list):
        return ["%s carries no '%s' list" % (label, list_key)], None
    seen = {}
    for r in rows:
        name = str(r.get(name_key, ""))
        ident = name.split(" ")[0]
        seen.setdefault(ident, []).append(r)
    for ident in expected:
        rs = seen.get(ident)
        if not rs:
            problems.append("%s: required row %s is MISSING" % (label, ident))
            continue
        if len(rs) != 1:
            problems.append("%s: required row %s appears %d times" % (label, ident, len(rs)))
            continue
        st = str(rs[0].get("status"))
        if st != "PASS":
            problems.append("%s: required row %s is %s, not PASS" % (label, ident, st))
        # the row's OWN result must be present and successful: status and result
        # content are one record and may not contradict each other
        res = rs[0].get("result")
        if not isinstance(res, dict):
            problems.append("%s: required row %s carries no result object (status %s)" % (label, ident, st))
        elif res.get("ok") is not True:
            problems.append("%s: required row %s has result.ok = %r under status %s" % (label, ident, res.get("ok"), st))
    unexpected = [i for i in seen if i not in expected]
    if unexpected:
        problems.append("%s: unexpected rows %s" % (label, unexpected))
    # the summary is RECOMPUTED from the rows and must agree with the file's own
    # counts; a row counts as passing only with a PASS status AND a successful result
    n_pass = sum(1 for r in rows if str(r.get("status")) == "PASS"
                 and isinstance(r.get("result"), dict) and r["result"].get("ok") is True)
    n_fail = len(rows) - n_pass
    if int(s.get("passed", -1)) != n_pass or int(s.get("failed", -1)) != n_fail:
        problems.append("%s: summary (passed %s, failed %s) disagrees with its rows (passed %d, failed %d)"
                        % (label, s.get("passed"), s.get("failed"), n_pass, n_fail))
    if n_pass != len(expected) or n_fail != 0:
        problems.append("%s: %d of %d required rows PASS, %d not PASS" % (label, n_pass, len(expected), n_fail))
    return problems, (n_pass, n_fail)


def main(argv):
    acc, route, gate, marker = argv[:4]
    problems = []
    for label, path in (("ACCEPTANCE_MATRIX", acc), ("ROUTE_MATRIX", route), ("GATE_MATRIX", gate)):
        pr, counts = check(label, path, marker)
        problems += pr
        if counts is not None:
            print("    %s: rows PASS %d / not PASS %d (recomputed)" % (label, counts[0], counts[1]))
    for pr in problems:
        print("    verdict problem: " + pr)
    return 0 if not problems else 23


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
