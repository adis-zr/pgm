# Deletion / move inventory (consolidation step 1)

Nothing was deleted from the research record.  Moves are by content (`git mv`); every relocated path keeps an alias shim.

## Moved (47 modules, 9 resources) -- `PATH_MAP.json`

| from | to | shim at the old path |
|---|---|---|
| `code/cex/newarm/{cex_executor,core,dag,forest,geometry,planning,reduction,stream,stream_float,support}.py` | `src/pgm/algorithms/structural/` | yes |
| `code/cex/newarm/{cex_kernel.cpp,cex_build.json,libcex_kernel.dylib,stream_kernel.cpp,stream_build.json,libstream_kernel.so}` | `src/pgm/algorithms/structural/` | n/a (resources) |
| `code/cex/blockres/{integrated,blockres,support_closure,signed_evidence,layered_contraction,ancestral_response}.py` | `src/pgm/algorithms/block/` | yes |
| `code/cex/hp/{unified_pac_planner,unified_planner,pac_actions,coarse_envelope,cost_model,global_circuit,global_optimize,global_stream,grouped_envelope,joint_optimize,joint_proposal,joint_stream,joint_witness,lifted_decoder,check_global,check_joint,check_residual,residual_bank,residual_local,residual_max_envelope,residual_stream,reservation,lp_worker}.py` | `src/pgm/algorithms/quotient/` | yes |
| `code/cex/hp/{PHASE_RATES.json,PHASE_RATES_R1.json}` | `src/pgm/algorithms/quotient/` | n/a |
| `code/cex/hp/{spectral_heatbath_run,spectral_witness,heatbath_exact,heatbath_native,markov_certificate,response_certificate,checked_tilt}.py` | `src/pgm/algorithms/response/` | yes |
| `code/cex/hp/heatbath_native.c` | `src/pgm/algorithms/response/` | n/a |
| `code/gbidi/supervise.py` | `src/pgm/runtime/supervise.py` | yes |
| `src/pgm/planning.py` | `src/pgm/planning/features.py` (package) | `pgm.planning` re-exports |
| `src/pgm/supervision.py`, `src/pgm/build.py` | `src/pgm/runtime/{supervision,build}.py` | thin entries kept |
| untracked: `code/cex/hp/heatbath_build.json`, `code/cex/hp/native_cache/`, `code/cex/newarm/native_cache/` | beside the owning implementation under `src/pgm/algorithms/` (ignored) | -- |

## Deleted

| path | commit | reason |
|---|---|---|
| `src/pgm/runtime/legacy_paths.py` | `eb71a50` | the legacy `sys.path` bridge became unnecessary once the closures import fully qualified names |

## Not moved (deliberately)

Campaign runners / analyzers / packagers / checkers under `code/cex/{hp,blockres,cqr}`, the specialists (`code/cbi`, `code/sf`,
`code/h4a`, `code/native`, `code/cex/cqr`), the frozen snapshots (`code/cex/{pac,baseline,b0_frozen_v14,newarm_dev}`), benchmark
tooling (`code/bench`, `code/ext`) and the evidence JSON records: the private records repository references them by path, and the
snapshots are pinned references.  Classification: `research/CLASSIFICATION.json`.

## Duplicates

No second live copy of a relocated module existed outside the frozen snapshots, so no active duplicate had to be removed.
