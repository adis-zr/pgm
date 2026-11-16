"""ONE candidate evaluation in a fresh supervised child: input (lambda) x mask (G). Steps, each timed and persisted:
(1) parse + own restriction + mask; (2) two-channel certificate (producer); (3) independent certificate checker;
(4) retained law through the existing sparse path (pipeline.solve on the masked model, route_policy="support": the frozen
support admission decides sparse vs dense fallback; certified enclosures + exact R from the checker's exact aggregation);
(5) sharp mixture transfer and the target-width outcomes for 0.01 / 0.02 / 0.05 (outward-rounded endpoints).
The child never reads generator annotations, original zero labels, references or oracle answers.
usage: run_candidate.py MODEL.uai MODEL.uai.evid G_NAME OUT_DIR RETAINED_WALL_S CAP_BYTES"""
import sys, os, json, time, hashlib, resource
HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)
from fractions import Fraction as Fr
from mdi import model as M
from nd import masks as MK, twochannel as TC, certificate_check as CC, retained as RT, transfer as TR


def _jdump(obj, path):
    tmp = path + ".tmp"
    with open(tmp, "w") as fh:
        json.dump(obj, fh, indent=1, default=str); fh.flush(); os.fsync(fh.fileno())
    os.replace(tmp, path)


def rss_bytes():
    r = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    return int(r) if sys.platform == "darwin" else int(r) * 1024


def main(mp, ep, gname, out, wall_s, cap_bytes):
    os.makedirs(out, exist_ok=True)
    rec = {"model": mp, "evidence": ep, "model_sha256": hashlib.sha256(open(mp, "rb").read()).hexdigest(), "evid_sha256": hashlib.sha256(open(ep, "rb").read()).hexdigest(),
           "gap": gname, "G": str(MK.GAPS[gname]), "K": TC.K_DEFAULT, "status": "STARTED", "steps": {}, "started": time.strftime("%Y-%m-%d %H:%M:%S")}
    _jdump(rec, os.path.join(out, "candidate.json"))
    t_all = time.monotonic()
    try:
        # (1) parse, restriction, mask
        t0 = time.monotonic()
        m = M.read_uai(mp); ev = M.read_evidence(ep, m)
        occ, sc = MK.restricted_occurrences(m, ev)
        mk = MK.apply_masks(occ, MK.GAPS[gname])
        free = [v for v in range(m.nvars) if v not in ev]; card = {v: m.card[v] for v in free}
        rec["mask"] = {"digest": MK.mask_digest(mk), "occurrences": len(occ), "occurrences_with_removals": sum(1 for x in mk if x["removed"]),
                       "removed_entries": sum(len(x["removed"]) for x in mk), "restricted_entries": sum(x["entries"] for x in mk), "scalars": len(sc), "free": len(free)}
        rec["steps"]["parse_restrict_mask_s"] = round(time.monotonic() - t0, 6)
        _jdump(mk, os.path.join(out, "mask.json"))
        # (2) certificate
        t0 = time.monotonic()
        try:
            cert = TC.run_certificate(occ, mk, sc, free, card)
        except TC.CertificateRefusal as e:
            rec["status"] = "CERTIFICATE_REFUSED"; rec["reason"] = str(e); rec["steps"]["certificate_s"] = round(time.monotonic() - t0, 6)
            raise SystemExit(0)
        rec["steps"]["certificate_s"] = round(time.monotonic() - t0, 6)
        rec["certificate"] = {k: v for k, v in cert.items() if k != "schedule"}
        rec["certificate"]["V"] = str(cert["V"]); rec["certificate"]["U"] = str(cert["U"])
        _jdump({k: v for k, v in cert.items()}, os.path.join(out, "certificate_full.json"))
        # (3) independent checker
        t0 = time.monotonic()
        try:
            chk = CC.check(mp, ep, MK.GAPS[gname], json.load(open(os.path.join(out, "certificate_full.json"))))
            rec["certificate_check"] = {k: (str(v) if isinstance(v, Fr) else v) for k, v in chk.items()}; rec["certificate_check"]["status"] = "VERIFIED"
        except CC.CheckFailure as e:
            rec["certificate_check"] = {"status": "FAILED", "reason": str(e)}
        rec["steps"]["certificate_check_s"] = round(time.monotonic() - t0, 6)
        # (4) retained law through the existing sparse path
        t0 = time.monotonic()
        masked = MK.masked_model(m, occ, mk)
        remaining = wall_s - (time.monotonic() - t_all)
        ret, res = RT.solve_retained(masked, ev, wall_s=max(1.0, remaining), cap_bytes=cap_bytes, plan_dir=os.path.join(out, "plans"))
        rec["steps"]["retained_solve_s"] = round(time.monotonic() - t0, 6)
        rec["retained"] = {k: v for k, v in ret.items() if k not in ("intervals",)}
        if ret["intervals"] is not None:
            _jdump(ret["intervals"], os.path.join(out, "retained_intervals.json"))
        if ret.get("refusal"):
            rec["status"] = "RETAINED_REFUSED"; rec["reason"] = ret["refusal"]; raise SystemExit(0)
        if not res.status.startswith("CERTIFIED"):
            rec["status"] = "RETAINED_NOT_CERTIFIED"; rec["reason"] = "%s: %s" % (res.status, res.reason); raise SystemExit(0)
        if ret["R"] is None:
            rec["status"] = "NO_EXACT_RETAINED_MASS"; rec["reason"] = "the checker's exact aggregation did not expose Z: no L available"; raise SystemExit(0)
        if rec["certificate_check"]["status"] != "VERIFIED":
            rec["status"] = "CERTIFICATE_CHECK_FAILED"; rec["reason"] = rec["certificate_check"]["reason"]; raise SystemExit(0)
        # (5) transfer
        t0 = time.monotonic()
        L = Fr(ret["R"]); U = cert["U"]
        rho = TR.rho_of(L, U)
        ex, rd, summ = TR.transfer_publication(ret["intervals"], ev, dict(enumerate(m.card)), rho)
        rec["steps"]["transfer_s"] = round(time.monotonic() - t0, 6)
        rec["transfer"] = summ
        rec["transfer"]["L_kind"] = "exact R (the checker's independent exact aggregation, original units)"
        rec["transfer"]["L"] = str(L); rec["transfer"]["U"] = str(U); rec["transfer"]["V_upper_retained_not_used"] = str(cert["V"])
        rec["transfer"]["U_over_V_hint"] = str(float(U / cert["V"])) if cert["V"] > 0 else None
        _jdump({str(v): [[str(a), str(b)] for a, b in rows] for v, rows in rd.items()}, os.path.join(out, "published_intervals_outward.json"))
        _jdump({str(v): [[str(a), str(b)] for a, b in rows] for v, rows in ex.items()}, os.path.join(out, "transferred_intervals_exact.json"))
        rec["status"] = "COMPLETED"
    except SystemExit:
        pass
    except BaseException as e:
        import traceback
        rec["status"] = "IMPLEMENTATION_FAULT"; rec["reason"] = "%s: %s" % (type(e).__name__, e); rec["traceback"] = traceback.format_exc()[-3000:]
    rec["child_wall_s"] = round(time.monotonic() - t_all, 6); rec["child_high_water_rss_bytes"] = rss_bytes(); rec["ended"] = time.strftime("%Y-%m-%d %H:%M:%S")
    _jdump(rec, os.path.join(out, "candidate.json"))
    print(json.dumps({k: rec.get(k) for k in ("gap", "status", "reason", "child_wall_s")}, default=str))
    return 0 if rec["status"] == "COMPLETED" else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1], sys.argv[2], sys.argv[3], sys.argv[4], float(sys.argv[5]), int(sys.argv[6])))
