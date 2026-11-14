"""One external-comparator cell for the PAC pass (candidate v2: typed comparator zero outcomes are UNRESOLVED, never a proof; every arm carries an execution_capacity tag), REUSING the registry's qualified adapters unchanged (bench/cells.py: libDAI driver, Merlin WMB/IJGP ladder, PGMax
sum-product; ext/comparator/merlin_adapter.py: Merlin CTE exact). Writes the pass's receipt fields next to the adapter's own cell.json. The whole-worker memory
policy (3 GiB sampled process-tree RSS) and the launch-relative deadline are applied by the per-cell supervisor; the adapter's internal timeouts are set to the
cell budget as in the historical sweep. Output: <out>/cell.json (adapter record, unchanged schema) + <out>/pac_receipt.json.
    python cex/pac/comparator_cell.py <ARM> <model.uai> <evid> <out_dir> <budget_s> <nonce>"""
import sys, os, json, time, hashlib, subprocess
HERE = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))); sys.path.insert(0, HERE)
ARMS = {'LIBDAI_EXACT': 'EXACT', 'LBP': 'LBP', 'WMB': 'WMB', 'IJGP': 'IJGP', 'PGMAX_SUMPRODUCT_BP': 'PGMAX_SUMPRODUCT_BP', 'MERLIN_CTE': 'MERLIN_CTE'}
CAPACITY = {'LIBDAI_EXACT': 'exact-capacity (junction tree, binary64 point; maxmem admission 8 GiB inside the driver; not a rigorous enclosure)', 'LBP': 'approximate (loopy BP, binary64 point)', 'WMB': 'ladder of i-bounds; exact-capacity when the solver reports exact inference at the final i-bound, else approximate (recorded per run)', 'IJGP': 'same ladder rule as WMB', 'PGMAX_SUMPRODUCT_BP': 'approximate (sum-product BP, float32 JAX)', 'MERLIN_CTE': 'exact-capacity (clique-tree elimination, binary64 point)'}


def main():
    arm, mp, ep, out, budget, nonce = sys.argv[1], sys.argv[2], sys.argv[3], sys.argv[4], float(sys.argv[5]), sys.argv[6]; launch_abs = float(sys.argv[7]) if len(sys.argv) > 7 else time.monotonic()
    if os.path.exists(out): raise SystemExit('refuse: attempt directory exists')
    os.makedirs(out); t0 = time.monotonic(); deadline_abs = launch_abs + budget                                    # LAUNCH-relative deadline on the host monotonic clock (the parent's launch instant)
    rec = dict(arm=arm, nonce=nonce, model_sha256=hashlib.sha256(open(mp, 'rb').read()).hexdigest(), evidence_sha256=hashlib.sha256(open(ep, 'rb').read() if os.path.exists(ep) else b'0').hexdigest(), model_path=os.path.abspath(mp), evidence_path=os.path.abspath(ep), budget_s=budget, capacity_note=CAPACITY[arm], guarantee_type='UNGUARANTEED', adapter_packet_version='pac-comparator-packet-v4.2 (bound: arm, nonce, model / evidence sha256, budget, output sha256, wall)')
    if arm == 'MERLIN_CTE':
        from ext.comparator import merlin_adapter as MA
        r = MA.run_cell(mp, ep, out, 'cte', max(0.1, deadline_abs - time.monotonic()), mem_gib=3.0); rec['adapter'] = {k: r.get(k) for k in ('outcome', 'reason', 'merlin_process_elapsed_s', 'pin')}; rec['adapter_status'] = r.get('outcome'); ao = str(r.get('outcome'))
        # the adapter's typed outcomes are preserved: COMPARATOR_ZERO_EVIDENCE_OR_UNDERFLOW stays an UNRESOLVED numerical outcome (Merlin cannot distinguish exact zero from underflow; never a proof)
        rec['outcome'] = 'PUBLISHED' if ao == 'COMPARATOR_COMPLETED' else ('ZERO_EVIDENCE_OR_UNDERFLOW_UNRESOLVED' if 'ZERO' in ao else ('INVALID_PLAN_OR_CERTIFICATE' if 'OUTPUT_INVALID' in ao else ('MEMORY' if 'MEMORY' in ao else ('DEADLINE' if ('TIMEOUT' in ao or 'DEADLINE' in ao) else 'NOT_COMPLETED'))))
        rec['execution_capacity'] = 'exact'                                                                        # clique-tree elimination: exact-capacity binary64 point (not a rigorous enclosure)
        mar = [os.path.join(out, f) for f in os.listdir(out) if f.endswith('.MAR')]; rec['output_file'] = mar[0] if mar else None
    else:
        from bench import cells as CELLS
        cfg = {'width': '1/100', 'pgmax_iters': 200, 'pgmax_damping': 0.5}
        # bench/cells.py measures time on ITS OWN process-relative clock (now() = seconds since its import): translate the launch-relative absolute deadline into that clock
        deadline = CELLS.now() + (deadline_abs - time.monotonic())
        rec0 = {"arm": ARMS[arm], "model": mp, "evidence": ep, "deadline_s": deadline, "launch_relative_budget_remaining_at_cells_start_s": deadline, "phases_s": {}, "status": None, "pid": os.getpid(), "started_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}
        snaps = CELLS.Snapshots(out, [1.0, 5.0, deadline])
        try: CELLS.ARMS[ARMS[arm]](mp, ep, out, deadline, cfg, rec0, snaps)
        except Exception as ex: rec0['status'] = 'FAULT'; rec0['reason'] = '%s: %s' % (type(ex).__name__, ex)
        snaps.finish(); rec0['complete_response_s'] = time.monotonic() - t0; rec0['within_deadline'] = rec0['complete_response_s'] <= budget
        if rec0['status'] in ('COMPLETE', 'COMPLETE_UNCONVERGED') and not rec0['within_deadline']: rec0['status_before_deadline_check'] = rec0['status']; rec0['status'] = 'LATE_OUTPUT'
        json.dump(rec0, open(os.path.join(out, 'cell.json'), 'w'), indent=1, default=str)
        rec['adapter_status'] = rec0['status']; rec['adapter'] = {k: rec0.get(k) for k in ('effective_limits', 'exact_by_ibound', 'final_ibound', 'reason', 'output_faults', 'reference_class_candidate')}
        rec['outcome'] = {'COMPLETE': 'PUBLISHED', 'COMPLETE_UNCONVERGED': 'PUBLISHED', 'INFEASIBLE_EVIDENCE': 'ZERO_EVIDENCE_OR_UNDERFLOW_UNRESOLVED', 'TIMEOUT': 'DEADLINE', 'LATE_OUTPUT': 'DEADLINE', 'ADMISSION_REFUSED': 'MEMORY', 'KILLED_MEMORY_KILL': 'MEMORY', 'INVALID_OUTPUT': 'INVALID_PLAN_OR_CERTIFICATE', 'FAILED': 'INVALID_PLAN_OR_CERTIFICATE', 'FAULT': 'INVALID_PLAN_OR_CERTIFICATE'}.get(rec0['status'], 'NOT_COMPLETED')
        rec['output_file'] = os.path.join(out, 'output.MAR') if os.path.exists(os.path.join(out, 'output.MAR')) else None
        if arm in ('WMB', 'IJGP'): rec['execution_capacity'] = 'exact' if rec0.get('exact_by_ibound') else 'approximate'
        elif arm == 'LIBDAI_EXACT': rec['execution_capacity'] = 'exact'
        else: rec['execution_capacity'] = 'approximate'
    rec['wall_s'] = time.monotonic() - launch_abs; rec['within_budget'] = rec['wall_s'] <= budget; rec['process_start_after_launch_s'] = t0 - launch_abs
    if rec['output_file']: rec['output_sha256'] = hashlib.sha256(open(rec['output_file'], 'rb').read()).hexdigest()
    json.dump(rec, open(os.path.join(out, 'pac_receipt.json'), 'w'), indent=1, default=str); print(json.dumps({k: rec.get(k) for k in ('arm', 'outcome', 'adapter_status', 'wall_s')}))


if __name__ == '__main__': main()
