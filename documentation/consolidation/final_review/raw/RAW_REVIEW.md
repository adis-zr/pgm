# Raw-evidence review of bounded completion

Reviewed repository head `0fe5f9cfcdb759c95c71cc76e537fd7b5727911b`. This review performed no inference runs and made no solver/source edits. All extraction and audit files are outside the checkout.

**Decision in this scope: PASS. The previously missing raw-evidence obligation is now closed. No new numerical, preservation, receipt, launch-binding or native-artifact defect was found.** This is an audit of delivered artifacts and their stated contracts, not an independent proof that every large-model enclosure contains its unknown exact marginal.

## Archive identity

All three repository archives match the declared SHA-256, byte count and member count. ZIP CRC checks pass. Members were checked for absolute paths and parent-directory escapes before extraction.

| Archive | SHA-256 | Members |
|---|---|---:|
| Original raw run | `4f088a35c5ee28ac97596a96ab6df3de713fba648b7999721acf14558a76d11c` | 5,925 |
| Separate post-run records | `d7743b8a510ab9e16f379cba66474ca4cacdfd026feea6738afd2d112012347a` | 52 |
| Supplement including refused first freeze | `ac1ff9a6606fbad2096cb12b5fb459bd03498ff290acf0562a41549979462fea` | 2,145 |

The original archive is byte-identical to the one named at the previous review. Later records are separate. The original failed identity observation has not been overwritten.

## Independent raw-output checks

`audit_raw.py` reads the actual per-cell `result.json` and comparator `output.MAR` files, not the compact booleans. It independently:

- hashes every frozen model/evidence input against the local repository copy;
- reconstructs the original non-evidence coordinate inventory from UAI cardinalities and evidence;
- checks exact key-set equality, uniqueness, reported counts, allowed labels, raw binding and positive-mass witness;
- parses all PGM intervals/points as exact rational numbers and checks `0 <= lo <= point <= hi <= 1`, endpoint radius at most `1/200`, zero-width EXACT rows, and simplex feasibility with unpublished states at `[0,1]`;
- checks per-request risk sums/nonnegativity and recorded per-attempt allocations, alongside rerunning the current harness's arm-contract reader;
- checks every cell against its unique outer terminal receipt, launch commit/arm/repeat/input binding, and the declared matrix;
- recomputes full completion using actual outputs, receipt success, the outer 20-second limit, cleanup and the recorded identity condition;
- checks the supplement's additional arm-closure attestation and all recorded nested cleanup outcomes;
- parses every available comparator MAR file independently, checking cardinality, finite probabilities, simplex tolerance and evidence;
- intersects deterministic and PAC intervals across both campaigns and all arms/repeats, and compares PGM intervals with available JT coordinates under the frozen `5e-10` serialization allowance.

The public API promises coordinatewise epsilon-safe points and a simplex-feasible interval box, not that its point vector sums exactly to one. The independent audit checks the actual documented contract.

| Checked quantity | Original | Supplement |
|---|---:|---:|
| Unique cells / terminal receipts | 732 / 732 | 245 / 245 |
| Charge, seconds | 4,130.231398 | 1,626.105870 |
| Raw PGM result files | 488 | 244 |
| Raw comparator MAR files | 172 | 1 |
| Published PGM coordinate instances | 468,324 | 233,228 |
| Maximum endpoint radius | 1/200 | 1/200 |
| Geometry/inventory/binding faults | 0 | 0 |
| Arm-contract or independent risk faults | 0 | 0 |
| Receipt/launch/completion discrepancies | 0 | 0 |
| Accepted both-repeat completions | 45 | 45 |
| Experimental both-repeat completions | 54 | 54 |

Original pinned accepted and experimental references independently recompute to 45 and 54; JT to 25, BP to 60 valid point-output completions under the original identity rule. The supplement's one additional BP replay is valid and on time.

Across the combined campaigns, **60,325 distinct task-coordinate groups have zero deterministic disjoint intersections and zero PAC disjoint intersections**. The latter is a consistency diagnostic, not a replacement for the request-level PAC interpretation.

JT agreement checks cover **119,224 coordinate instances in 180 original PGM outputs** and **59,612 in 90 supplement outputs**. There are zero exclusions after the frozen `5e-10` allowance. The maximum raw distance is `5e-11`; the allowance is therefore active, and this is numerical agreement with JT rather than exact-rational truth containment. Supplement comparisons reuse the unchanged original JT outputs on hash-identical inputs; they make no new timing claim.

## Native artifacts and incident

All **41 original and 22 supplement active PGM native/source/build-record artifacts** in the archives match their respective frozen hashes. The check includes the actual loaded binaries named by the per-arm native records. It does not independently rebuild the Mac binaries or claim independent validation of the external libDAI executable itself.

The sole original identity failure remains `exposed_regression__DBN_11__LIBDAI_BP__r1`. The supplement's separately recorded replay has valid output, clean receipt, valid source/arm-closure checks and wall time about 1.902 seconds. The original strict validity FAIL remains intact; the supplemental evidence resolves the practical missing clean observation. The transient documentation-only attribution remains an operator assertion, appropriately identified as such in INCIDENTS.json.

## Reproducible evidence

- `ARCHIVES.json`: archive hashes, sizes, counts, CRC outcomes.
- `audit_raw.py`, `RAW_AUDIT.json`, `RAW_AUDIT.log`: independent raw geometry/inventory/receipt/launch/risk/completion and cross-campaign checks.
- `NATIVE_ARTIFACT_CHECK.json`: active PGM native artifact hash comparisons.

The input archives and extracted trees are retained outside the repository for the parent review. The relevant results above remove the previous raw-coordinate audit limitation; no whole benchmark rerun is required in this scope.
