"""Supervised cell runner for integrated.py: python cex/blockres/run_cells.py SUBDIR TASK CAP BUDGET SCHEDULE SEED [TASK CAP BUDGET SCHEDULE SEED ...]"""
import sys, os, json, subprocess
RD = '/Users/adis/Workspace/pgm-records/code/runs/mdi_2026-10-28/BLOCKRES_2026-11-19'; IN = '/Users/adis/Workspace/pgm/docs/handoff-received-2026-11-11-certified-executor/packet/inputs'; CODE = '/Users/adis/Workspace/pgm/code'
sub = sys.argv[1]; extra = []
args = sys.argv[2:]
if '--' in args: i = args.index('--'); extra = args[i + 1:]; args = args[:i]
for i in range(0, len(args), 5):
    t, cap, B, sch, seed = args[i:i + 5]; out = os.path.join(RD, sub, '%s__cap%s_b%s_%s_s%s%s' % (t, cap, B, sch, seed, ('_' + '_'.join(x.strip('-') for x in extra)) if extra else '')); os.makedirs(out, exist_ok=True)
    cmd = [os.path.join(CODE, 'cex/blockres/job.sh'), 'blockres:%s:%s:cap%s:b%s:%s:s%s%s' % (sub, t, cap, B, sch, seed, (':' + ':'.join(x.strip('-') for x in extra)) if extra else ''), str(float(B) + 1), '3', '--', os.path.join(CODE, '.venv/bin/python'), os.path.join(CODE, 'cex/blockres/integrated.py'),
           '--input', os.path.join(IN, t + '.uai'), '--output', os.path.join(out, 'result.json'), '--budget', B, '--mb-cap', cap, '--schedule', sch, '--seed', seed] + extra
    with open(os.path.join(out, 'stdout.txt'), 'w') as so, open(os.path.join(out, 'stderr.txt'), 'w') as se: subprocess.run(cmd, cwd=CODE, stdout=so, stderr=se)
    try:
        d = json.load(open(os.path.join(out, 'result.json'))); m = d['mechanism']
        print('%s cap %s budget %s %s seed %s:' % (t, cap, B, sch, seed), d['outcome'], 'pub', d.get('published'), '/', d['K'], 'wall', round(d['wall_s'], 2), {k: (round(m[k], 4) if isinstance(m.get(k), float) else m.get(k)) for k in ('route', 'draws', 'draws_per_s', 'X_mean', 'ESS', 'largest_share', 'zero_weight_fraction', 'max_X', 'remaining', 'max_remaining_width', 'response_residual_variance_median', 'wmb')}, {k: round(v, 2) for k, v in d['phases_s'].items() if v > 0.05})
        tm = os.path.join(out, 'result.json.timing.json'); print('   timing:', open(tm).read().replace('\n', ' ')[:200] if os.path.exists(tm) else '-')
    except Exception as e: print('FAILED', t, e, open(os.path.join(out, 'stderr.txt')).read()[-300:])
