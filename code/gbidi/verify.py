"""The separate task-bound point verifier (one process, one protocol for EVERY task including the empty-query task):
    python -m gbidi.verify checked_record.json output.MAR MODEL EVID out.json
(1) re-read the caller's files INTO BYTES, hash them, parse them with the strict grammar (gbidi.source); (2) the record must be an INTERVALS_OK
record bound to exactly this task (raw + canonical hashes of model AND evidence, variable count, cardinalities, query contract); (3) re-parse the
delivered MAR decimals as exact rationals: complete rows, exact sum one, every coordinate inside the GRID-WIDENED certified interval and within
eps of every covered truth (adp.publish.verify_point); the empty task requires exactly 'MAR 0'; (4) for nonempty tasks the pinned ADP verifier
(adp.checker.verify_point_mode) is ALSO run in this process and must agree. Never re-solves inference; never repairs an upstream enclosure."""
from __future__ import annotations
import os, sys, json, time, hashlib, io, contextlib
HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__))); sys.path.insert(0, HERE)
sys.set_int_max_str_digits(0)
from fractions import Fraction as Fr
from gbidi import source as GS
from adp import publish as PB


class Reject(Exception):
    pass


def main(record_path, mar_path, model_path, evid_path, out_path):
    T0 = time.monotonic(); rec = {"status": "POINT_REJECTED", "verifier": "gbidi.verify v2"}
    try:
        chk = json.load(open(record_path))
        if chk.get("status") != "INTERVALS_OK":
            raise Reject("record status is %r, not INTERVALS_OK" % chk.get("status"))
        S = GS.Snapshot(model_path, evid_path); tb = S.task; got = chk.get("task") or {}
        for k in ("raw_model_sha256", "raw_evidence_sha256", "canonical_model_sha256", "canonical_evidence_sha256", "nvars", "orig_card", "queries_sha256"):
            if got.get(k) != tb[k]:
                raise Reject("record is bound to a different task (%s differs)" % k)
        with open(mar_path, "rb") as f:
            mar_bytes = f.read()
        toks = mar_bytes.decode("utf-8").split()
        if not toks or toks[0] != "MAR":
            raise Reject("delivered file is not a MAR file")
        m = S.model; card = list(m.card)
        if len(toks) < 2 or int(toks[1]) != m.nvars:
            raise Reject("MAR variable count differs from the task")
        pos = 2; rows = []
        for v in range(m.nvars):
            if pos >= len(toks) or int(toks[pos]) != card[v]:
                raise Reject("row %d has the wrong length" % v)
            pos += 1; vals = toks[pos:pos + card[v]]; pos += card[v]
            if len(vals) != card[v]:
                raise Reject("row %d truncated" % v)
            rows.append([Fr(x) for x in vals])
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
            G = PB.grid_bits(max(card))
            for v in range(m.nvars):
                ok, why = PB.verify_point(rows[v], PB.widen(ivs[v], G), PB.EPS)
                if not ok:
                    raise Reject("row %d: %s" % (v, why))
            # the pinned ADP verifier must agree (same files, same record)
            from adp import checker as CK
            tmpo = out_path + ".adp.json"
            with contextlib.redirect_stdout(io.StringIO()):
                CK.verify_point_mode(record_path, mar_path, model_path, evid_path, tmpo)
            adp = json.load(open(tmpo)); os.remove(tmpo)
            if adp.get("status") != "POINT_VERIFIED":
                raise Reject("pinned adp.checker point mode disagrees: %s" % adp.get("reason"))
            rec["adp_checker"] = {"status": adp["status"], "wall_s": adp.get("wall_s")}
        rec.update({"status": "POINT_VERIFIED", "reason": "ok", "mar_sha256": hashlib.sha256(mar_bytes).hexdigest(), "task": tb, "grid_bits": PB.grid_bits(max(card)) if card else None, "rows": m.nvars})
    except Reject as ex:
        rec = {"status": "POINT_REJECTED", "reason": str(ex), "verifier": "gbidi.verify v2"}
    except GS.InvalidInput as ex:
        rec = {"status": "POINT_REJECTED", "reason": "invalid input: %s" % ex.reason, "verifier": "gbidi.verify v2"}
    except Exception as ex:
        rec = {"status": "POINT_REJECTED", "reason": "malformed record or input: %s: %s" % (type(ex).__name__, ex), "verifier": "gbidi.verify v2"}
    rec["wall_s"] = time.monotonic() - T0; json.dump(rec, open(out_path, "w")); print(json.dumps(rec))


if __name__ == "__main__":
    main(*sys.argv[1:6])
