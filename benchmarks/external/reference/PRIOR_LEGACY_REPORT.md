# Post-hoc legacy auto-dispatch diagnostic

Unmodified older deterministic entrypoint on current main `7f28259a4869a2c684d506b51072b04bb0ce4783`. This is neither the accepted v2.13.2 engine nor an implemented union of the benchmark arms.

Both-replicate completions: 7/7 (DBN_11, DBN_12, DBN_15, DBN_16, Promedus_12, Pedigree_11, ASIA). One-replicate-only: none. Qualification:2/2=True. Artifact issues:0.

The seven targets were chosen after initial benchmark outcomes. Comparisons reuse earlier-phase PGM/JT timings; they are not interleaved trials. Only two observations per target are available. Discovery, reductions, publication and the inherited tiny exact check are charged.

| Target | Legacy rep1 s | Legacy rep2 s | JT rep1 s | JT rep2 s | JT/legacy rep1 | JT/legacy rep2 | Timeout lower bound |
|---|---:|---:|---:|---:|---:|---:|---:|
| DBN_11 | 1.859 | 2.131 | 11.25 | 10.68 | 6.052 | 5.012 | — |
| DBN_12 | 3.722 | 3.865 | — | — | — | — | — |
| DBN_15 | 3.812 | 3.828 | — | — | — | — | — |
| DBN_16 | 7.337 | 7.808 | — | — | — | — | — |
| Promedus_12 | 12.1 | 11.87 | 3.212 | 2.722 | 0.2654 | 0.2292 | — |
| Pedigree_11 | 0.397 | 0.3713 | 0.572 | 0.9337 | 1.441 | 2.515 | — |
| ASIA | 0.0768 | 0.07835 | 0.01497 | 0.01494 | 0.1949 | 0.1907 | — |

At least20× in both repeats: measured none; actual-timeout lower bounds none.

At least100× in both repeats: measured none; actual-timeout lower bounds none.

Memory forecast refusals and memory kills never provide a speedup denominator. Censored bounds use the20-second cap, not observed cleanup time. A median alone cannot establish a20× or100× threshold.

| Target | Automatic routes by replicate | Result by replicate |
|---|---|---|
| DBN_11 | stream / stream | complete / complete |
| DBN_12 | stream / stream | complete / complete |
| DBN_15 | stream / stream | complete / complete |
| DBN_16 | stream / stream | complete / complete |
| Promedus_12 | support / support | complete / complete |
| Pedigree_11 | support / support | complete / complete |
| ASIA | dag / dag | complete / complete |

Against PGM, target-only gains:DBN_11, DBN_12, DBN_15, DBN_16, Pedigree_11; losses:none.

Against LIBDAI_JT, target-only gains:DBN_12, DBN_15, DBN_16; losses:none.

Published original coordinates checked:4426; faulty result files:0; largest endpoint radius:2e-08.
JT points outside legacy enclosures after the explicit5e-10 serialization allowance:0. Deterministic interval disagreements against PGM:0. These are agreement diagnostics, not independent exact truth.

The common outer ceiling is3GiB RSS. This worker additionally attempts RLIMIT_AS3GiB and its native support route uses3GiB admission; the accepted PGM engine instead retains its2.5GiB internal allowance. That inherited difference is disclosed, not silently equalized.

Legacy scored charge:59.262s; qualification:0.210s; shared charge including both:3313.978/8000s.

Any recovered advantage shows that an existing constructor or dispatch path deserves attention. This selected seven-task diagnostic cannot establish broad preservation, generalization, an instance-optimality theorem, or the historical20×–100× receipts. Primary and research-planner results remain separate and unchanged.
