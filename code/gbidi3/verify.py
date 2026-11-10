"""Separate task-bound point verifier of GENERAL_BIDI_COMPLETE_V3 (one process, one protocol for every task incl. the empty-query task):
    python -m gbidi3.verify checked_record.json output.MAR.tmp MODEL EVID out.json expected_identity.json remaining_s
(the caller supplies the EXPECTED task + execution identity + the sha256 of the exact bytes to verify, and the remaining time of the ONE cell deadline;
the verifier exits 0 only on POINT_VERIFIED and binds its receipt to the expected-identity file's hash)
(1) re-read the caller's files INTO BYTES, hash + parse them with the strict grammar (gbidi3.source); (2) the record must be INTERVALS_OK and bound to
exactly this task on EVERY binding field (raw + legacy canonical + canonical_v2 hashes of model AND evidence, variable count, cardinalities, query contract,
eps, max_width); (3) re-parse the delivered MAR decimals as exact rationals: complete rows, no extras, exact sum one, every coordinate inside the GRID-WIDENED
certified interval and within eps of every covered truth; the DELIVERED max width <= 1/100; the empty task requires exactly 'MAR 0'; (4) the pinned ADP
verifier (adp.checker.verify_point_mode) must agree on nonempty tasks. Never re-solves inference; never repairs an upstream enclosure."""
from __future__ import annotations
import os, sys, json, time, hashlib, io, contextlib
HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__))); sys.path.insert(0, HERE)
sys.set_int_max_str_digits(0)
from fractions import Fraction as Fr
from gbidi3 import source as GS, identity as ID
from adp import publish as PB


class Reject(Exception):
    pass


def main(record_path, mar_path, model_path, evid_path, out_path, expected_path=None, remaining_s=None):
    T0 = time.monotonic(); deadline = T0 + float(remaining_s) if remaining_s is not None else None; rec = {"status": "POINT_REJECTED", "verifier": "gbidi3.verify v4"}
    def tick():
        if deadline is not None and time.monotonic() > deadline:
            raise Reject("DEADLINE inside the verifier")
    try:
        if expected_path is None:
            raise Reject("no expected task / execution identity was supplied by the caller")
        exp = json.load(open(expected_path)); exp_sha = hashlib.sha256(open(expected_path, "rb").read()).hexdigest()
        chk = json.load(open(record_path))
        if chk.get("status") != "INTERVALS_OK":
            raise Reject("record status is %r, not INTERVALS_OK" % chk.get("status"))
        S = GS.Snapshot(model_path, evid_path); tb = S.task; got = chk.get("task"); tick()
        if not GS.bound_to_task(got, tb):
            bad = [k for k in GS.TASK_BINDING_FIELDS if not isinstance(got, dict) or got.get(k) != tb[k]]
            raise Reject("record is bound to a different task (%s differ)" % bad)
        if not GS.bound_to_task(exp.get("task"), tb):
            raise Reject("the caller's expected task differs from the caller's files")
        bad = ID.check_execution(chk.get("execution"), exp.get("execution"))
        if bad:
            raise Reject("record execution identity differs from the caller's expectation: %s" % bad[:3])
        with open(mar_path, "rb") as f:
            mar_bytes = f.read()
        if hashlib.sha256(mar_bytes).hexdigest() != exp.get("mar_sha256"):
            raise Reject("the delivered bytes are not the bytes the caller asked to verify")
        toks = mar_bytes.decode("utf-8").split()
        if not toks or toks[0] != "MAR":
            raise Reject("delivered file is not a MAR file")
        m = S.model; card = list(m.card)
        if len(toks) < 2 or toks[1] != str(m.nvars):
            raise Reject("MAR variable count differs from the task")
        pos = 2; rows = []
        for v in range(m.nvars):
            if pos >= len(toks) or toks[pos] != str(card[v]):
                raise Reject("row %d has the wrong length" % v)
            pos += 1; vals = toks[pos:pos + card[v]]; pos += card[v]
            if len(vals) != card[v]:
                raise Reject("row %d truncated" % v)
            try:
                rows.append([Fr(x) for x in vals])
            except (ValueError, ZeroDivisionError):
                raise Reject("row %d has a malformed decimal" % v)
        if pos != len(toks):
            raise Reject("trailing tokens in the MAR file")
        ivs = {}
        for v in range(m.nvars):
            row = (chk.get("certified_intervals") or {}).get(str(v))
            if row is None or len(row) != card[v]:
                raise Reject("interval row of variable %d missing or of wrong length" % v)
            ivs[v] = [(Fr(a), Fr(b)) for a, b in row]
            for L, U in ivs[v]:
                if not (0 <= L <= U <= 1):
                    raise Reject("malformed interval in row %d" % v)
        if m.nvars > 0:
            G = PB.grid_bits(max(card)); dmax = Fr(0)
            for v in range(m.nvars):
                wide = PB.widen(ivs[v], G); ok, why = PB.verify_point(rows[v], wide, PB.EPS)
                if not ok:
                    raise Reject("row %d: %s" % (v, why))
                dmax = max(dmax, max(U - L for L, U in wide))
            if dmax > PB.MAX_WIDTH:
                raise Reject("delivered (grid-widened) max width %s exceeds 1/100" % dmax)
            rec["delivered_max_width"] = str(dmax)
            from adp import checker as CK
            tmpo = out_path + ".adp.json"
            with contextlib.redirect_stdout(io.StringIO()):
                CK.verify_point_mode(record_path, mar_path, model_path, evid_path, tmpo)
            adp = json.load(open(tmpo)); os.remove(tmpo)
            if adp.get("status") != "POINT_VERIFIED":
                raise Reject("pinned adp.checker point mode disagrees: %s" % adp.get("reason"))
            rec["adp_checker"] = {"status": adp["status"], "wall_s": adp.get("wall_s")}
        rec.update({"status": "POINT_VERIFIED", "reason": "ok", "mar_sha256": hashlib.sha256(mar_bytes).hexdigest(), "task": tb, "execution": chk.get("execution"), "expected_identity_sha256": exp_sha, "grid_bits": PB.grid_bits(max(card)) if card else None, "rows": m.nvars})
    except Reject as ex:
        rec = {"status": "POINT_REJECTED", "reason": str(ex), "verifier": "gbidi3.verify v4"}
    except GS.InvalidInput as ex:
        rec = {"status": "POINT_REJECTED", "reason": "invalid input: %s" % ex.reason, "verifier": "gbidi3.verify v4"}
    except Exception as ex:
        rec = {"status": "POINT_REJECTED", "reason": "malformed record or input: %s: %s" % (type(ex).__name__, ex), "verifier": "gbidi3.verify v4"}
    rec["wall_s"] = time.monotonic() - T0; json.dump(rec, open(out_path, "w")); print(json.dumps(rec)); sys.exit(0 if rec["status"] == "POINT_VERIFIED" else 2)


if __name__ == "__main__":
    main(*sys.argv[1:8])
