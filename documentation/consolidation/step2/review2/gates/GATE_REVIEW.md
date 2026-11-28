# Step-2 protocol and analysis review

Source: `consolidate/production-layout` at `d45a1367101ff5d68597684aa29c1cecced76fd9`; frozen engine `f74f7f3da84cade7ac2bc6776087790a0c698a73`.
Scope: read-only source and committed evidence, independent compact-cell/receipt recomputation, synthetic analyzer-boundary probes. No solver run. The raw 39,220,001-byte run archive is not in the clone; therefore this review cannot independently replay the 468,324 raw coordinate checks, native-artifact inventory or launch-record checks. Its manifest is committed, not the bytes themselves.

## Findings and interpretation

### G1. The incident-excluding predicate excludes arbitrary identity failures (P2)

`benchmarks/external/analyze_suite.py:187` removes every issue whose text starts `Cell source identity failed`. It does not require the documented DBN_11/LIBDAI_BP/r1 key, a specific changed-file set, or an approved incident record. A synthetic two-arm record with unrelated identity failures in BOTH the accepted candidate and accepted reference produces ordinary validity FAIL and incident-excluding validity PASS. `ANALYSIS_BOUNDARIES.json` contains the executed result; `probe_analysis_boundaries.py` is a no-solver reproducer.

This does not create another archived identity failure. The committed run has precisely one, as disclosed, and the ordinary validity/promotion gate correctly remains FAIL/HOLD. Make the exception an explicit exact incident allowlist, or remove the secondary automated PASS and let the review record the scope. A second or different identity failure must keep the secondary predicate failed.

### G2. Unresolved nested ownership is accepted by the benchmark reader (same issue as runtime repair, P2)

`run_suite.py:275` checks only `NOT_STARTED` as an unresolved attempt. A COMPLETE public result with a `CLEANUP_UNRESOLVED` attempt passes both `contract_valid` and `all_queries_returned`. The outer receipt can separately detect surviving descendants, but this reader does not enforce the library's terminal-ownership contract. Extend the parent's runtime repair to reject the ownership-failure outcome and test it here as well. Do not create a separate broad review round for this.

This is a synthetic validator-boundary result, not an assertion that archived scored requests leaked processes.

### G3. Reference snapshots are frozen once but not checked at each cell (P2, scope limitation)

`root_identity` at `run_suite.py:182–194` records each pinned reference's source closure and native files at freeze. The live `identity()` at lines167–170 includes only the current checkout and its active native files. The pre/post cell checks at lines370 and386 call that current-checkout identity plus libDAI; `run()` never rechecks `frozen.roots` or `frozen.natives` for the external reference roots. The actual freeze's `engine_files` has 863 entries and zero reference-worktree entries.

Therefore “identity_ok on every cell” means current checkout/comparator identity, not all six executed arm roots. This is not evidence either reference changed in this run. For the next execution, bind each arm's actual source/native closure at launch and termination (or execute immutable staged closures). For this run, preserve any available post-run reference attestations and compare archived executed native artifacts to the frozen records. A whole rerun is not justified solely by a missing redundant guard in the absence of changed bytes.

### G4. Amendment-2 terminology is wrong; its actual time correction is reasonable for these cells

The frozen and amended ANALYSIS groups and pairs are identical, including completion sets and all timing ratios. All16 reclassified legacy cells are non-completing DEADLINE or DEADLINE_PARTIAL, delivered within20s. Four nevertheless publish coordinates: `1qt9` has31 and `MUNIN1`903, each in both repeats. The name `amendment_2_reclassified_non_publishing_legacy_cells` and analyzer comments saying “non-publishing” are false. Use “non-completing legacy cells.”

The outer contract is20s; the19.5s allocation provides headroom for handling/serialization. Treating these16 internal-wall excesses as diagnostics is defensible, provided the partial rows remain subject to the raw publication checks and they do not turn into completions. The amendment preserves frozen analyzer outputs and no result changes completion category, which is appropriate.

The replacement rule is broader than the explanation: `run_suite.py:258–259` accepts any finite legacy `wall_s` and does not require a non-completing outcome. The shipped new test explicitly accepts EXACT at19.6s. State the intended contract plainly: either the diagnostic applies to every legacy result under the20s outer delivery rule, or scope this correction to documented non-completions and retain the success-side check. This distinction changes no archived completion here. It is not a reason to discard the experiment.

## Independently recomputed from committed compact records and receipts

`COMPACT_RECOMPUTATION.json` records:

- 732 expected,732 observed,732 unique cell keys; no missing, extra or duplicate keys.
- 732 unique terminal receipts; every cell/receipt wall, return code, outcome and peak RSS agrees.
- Charge4130.23139837796s.
- Both-repeat completion sets exactly match ANALYSIS: accepted reference45, new accepted45, old experimental54, new experimental54, JT25, BP60 POINT_ONLY returns.
- All18 paired overhead flags independently reproduce the declared two-repeat1.25x-and0.1s rule.
- Exactly one `identity_ok:false`: DBN_11 LIBDAI_BP r1.
- Frozen and amended groups/pairs unchanged.
- Every committed file named by RUN_ARCHIVE's copied-file SHA-256 map matches its declared hash. This does not verify the unprovided raw zip.

The claimed geometry, JT exclusions, deterministic compatibility and risk checks need raw-result review; compact booleans are not an independent substitute.

## Incident scope

The initial operator log says the driver aborted before cell115. The actual `2_primary.log:114–126` shows cell114 (DBN_11 BP r1) completed numerically and then failed its POST-cell identity check; the automatic retry subsequently failed the PRE-cell check (`:127–138`). Amendment2 and START_HERE accurately disclose the in-flight affected cell, correcting that incomplete first log description. Keep the original log and append a clarification; do not rewrite it.

The reported changed file is a documentation entrypoint outside the solver/comparator execution closure. If the raw evidence confirms that narrow changed-file set, the defect is experiment provenance, not numerical inference. There is no reason on this evidence to rerun all732 cells. Keep the invalid original and execute a separately identified clean replacement of the affected comparator cell, or issue an explicitly scoped review disposition. Do not silently rewrite its `identity_ok` field or let a blanket exception declare unrelated future identity failures acceptable.

## Preservation and cost implications

The executed pinned-reference comparisons are stronger than historical summaries for same-host refactor preservation. Their matching45 and54 sets are substantive evidence. Historical experimental preservation nevertheless remains genuinely NOT_EVALUABLE until the old scored122-cell extract is supplied; a rerun of old code cannot reconstruct historical observations. The amendment disclosed this missing prerequisite before execution, but it is still a deviation from the prior brief's recovery-before-scoring requirement. Recover/analyze the old extract without rerunning solvers.

The overhead gate was prospectively advisory: flags hold promotion pending explanation. The experiment demonstrates18 latency regressions under that rule. Labeling them “common-contract overhead” does not erase their end-to-end cost. Timing decomposition is descriptive; a new checked execution-path change and matched measurement are needed to claim removal. PGM experimental54 versus JT25 is a coverage advantage, not across-the-board speed dominance; the committed mutual-completion median ratio is1.336 (experimental slower). BP60 is point-output completion, not certified inference.

## Recommended bounded next action

Retain this campaign as preservation evidence with its recorded limitations. Combine the runtime fail-closed repair and analyzer outcome/exception controls in one committed correction. Recover/share the complete raw archive and old experimental extract, reanalyze without solver reruns, and resolve the single incident cell under an appended identity. Improve the fixed API path only through a separately frozen measured change, preserving both policies and all prior completion sets. No new mathematical inference work is required to address these findings.
