# Untuned dispatch and runtime: first performance pass

The parent is the accepted consolidation baseline `f664ee7aa06851c77e9876cea409d4a04a9e4b21`.
The question is whether an existing exact method can be reached more consistently, with less common runtime work,
while preserving the full external benchmark under the same resource and accuracy contract.

## Algorithm change

The existing experimental policy admits an early exact structural attempt on physically affordable higher-order
categorical factors, but skips that attempt on binary higher-order factors. The structural solver supports both.
The candidate `automatic` policy applies the same existing admission predicate to both domains:

* forecast physical memory fits the request's memory allowance;
* forecast work does not exceed the existing rate times remaining work time;
* the attempt gets the existing quarter of remaining work time, followed by the existing fallback order.

The earlier forest, bipartite stream and pairwise branches keep their precedence. There is no new rate, threshold,
per-input parameter, benchmark-name lookup, pilot tuning or learned proposer. The accepted default and the original
experimental policy remain available. Their decision logic is preserved.

Admission is a scheduling estimate, not a promise of completion or a proof of accuracy. The new attempt can consume
time without finishing; preservation is therefore an empirical gate. Each backend still verifies its own applicable
representation and certificate. The shared publication boundary, original-coordinate inventory, prospective PAC risk
shares, single request deadline, and supervised cleanup acceptance are unchanged. The risk shares still sum to the
request's delta; structural execution has zero PAC allocation.

## General runtime changes

Public exports load lazily, avoiding inference-contract imports in a supervisor process that does not use them.
The lexical inspector has fast paths for unsigned integer and non-exponent decimal tokens. It retains the same grammar,
zero detection, conservative rational-bit estimate, memory admission and per-token deadline polls. No graph inspection
or validation is silently removed. Native kernels and numerical algorithms are unchanged.

The public result records the full proposed dispatch order, including unattempted candidates, and diagnostic phase times.
Worker records separate parsing, adapter execution and normalization. These nested intervals are not an additive cost
identity. End-to-end supervisor wall time remains the performance measure, including import, recognition, construction,
inference, checking, publication and cleanup. All new diagnostics precede the existing final publication timestamp.

## Development evidence and limitations

The complete 61-input audit covers 1,914,150 factor entries. With the optional forecast disabled, inspector metadata
matches the parent except elapsed time; on identical metadata, all old experimental candidate plans match. The new
predicate changes eight exposed task plans. This is applicability evidence, not a speed or accuracy result.

A 12-pair alternating fresh-process diagnostic measured supervisor imports at median 31.19 ms for the parent and
9.12 ms for the candidate. This attribution experiment is separate from the scored inference benchmark. It does not
explain all earlier common-contract overhead.

The first parity comparison to the historical Mac-generated reference differed in ten last-bit spectral witness
quantities on two response fixtures. All 16 deterministic cases, both wall-limited invariant records and native
fixed-trajectory outputs matched. The original comparison is retained; same-host baseline/candidate parity is run
separately, rather than relaxing or rewriting the historical reference. The 12 DGP10 controls pass on this host.

Structural, block, quotient and response implementations are reachable through the generic UAI interface. CBI and SF
need supplied specialized representations, H4 is a fixed-cohort reference, and CQR has a different query language.
Making those generic routes requires additional representation constructors and proofs, not merely another switchboard
branch. This round makes no such integration claim.

The performance protocol is `benchmarks/external/PERFORMANCE_PLAN.md` and its JSON declaration. All 61 external tasks
are exposed regression inputs. The full six-arm, two-repeat comparison uses the same host and interpreter. Historical
45/54 completion sets are retained as separate targets; no unseen-evaluation or asymptotic-scaling claim follows from
this run. The default remains accepted until a separate promotion decision.
