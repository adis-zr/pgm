# Independent layout migration review

**PASS — approve the migration at `63513e043e93f20fe3a23e9166fff09bc86c1926`.** No remaining source or qualification blocker was found within the declared scope. The accepted default remains unchanged.

- All 74 protected general-engine, policy, model/planning/publication, API/contract and attempt/cleanup files are byte-identical to baseline `7c67a3544afca74587ac066612a60b79c7aabdec`. Production imports use only pgm, declared dependencies and the standard library; no research/legacy imports or `sys.path` mutation remain. The physical `code/` directory is absent.
- All 485 old code paths appear exactly once in the 499-entry disposition map. Every current destination hash matches; all 175 archived originals and 8 additional preserved originals match the parent. All 47 retired aliases point to their original canonical implementation.
- The central registry preserves native representations and checker/result contracts. Four backends remain schedulable for generic UAI; CBI/SF/CQR remain explicit specialists and H4 stays reference/cohort-only. No automatic converter or guarantee relabelling was introduced.
- Formal serial qualification on the clean frozen commit passes all 10 required steps: 369 tests and 47 subtests, identical same-host parity, 12/12 DGP10 controls, numerical oracle PASS, and strict wheel relocation PASS. The sequential supplement passes HP 80/80, unified 57/57 and revision 32/32.
- The formal wheel SHA-256 is `de14d89cac6b6a137075a14d1a41bb9a9fbda84f418203d0fa086194db2134f3`. All 138 package entries independently match frozen source. Installed execution verifies CBI/SF, CQR joint/parity/conditional/Z, and all four H4 native roles with three independent certificate verdicts. Native products remain in declared external caches and installed package files remain unchanged.
- All 90 prior benchmark evidence/reference files remain byte-identical. Frozen replay restores `f14d407f50024ee29c5e8ae6bad52705bc01ec4e`, retains the original analyzer hashes, and passes. No old scored cell was rerun or relabelled by this migration.

Research source and native-provenance plumbing is now bound to the requested checkout. Historical run_revision/validate_round protocols explicitly refuse the live layout with preserved originals; the DGP10 old packet layout refuses before writing. Full historical CQR/DGP matrices still require their original pinned environment. This review does not claim every historical campaign helper is generally runnable.

The first full qualification attempt failed only because its numerical oracle dependency mpmath was absent. That failure is retained. Installing the qualification dependency and repeating all ten steps passed at the same source commit.

Six private specialist test instances and 51 inherited controls remain blocked by missing private inputs; 39 inherited portable controls pass. Public tiny witnesses do not replace those missing checks. No new latency, broad speed-dominance or unseen-evaluation claim follows from relocation; existing exposed-suite limitations remain.
